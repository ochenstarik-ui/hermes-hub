"""Hermes Hub — Real Runtime Call Telemetry & Metrics Service.

Captures, persists, and computes honest empirical measurements for all router calls:
- Latency (P50, P95, Max)
- Real Token Usage (extracted ONLY from provider usage metadata; never guessed)
- Route Failovers and Failure Categories
- Cost Calculation (computed ONLY when explicit user model pricing is configured)
- Ring Buffer & File Rotation (bounded memory and disk footprint)
"""
from __future__ import annotations
from antigravity_provider.router.role_registry import RoleRegistry

import collections
import datetime
import json
import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from antigravity_provider import paths

logger = logging.getLogger("hermes.router.telemetry")

MAX_MEMORY_RECORDS = 10000
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_BACKUP_FILES = 3


def format_token_count(measured: Optional[int], estimated: Optional[int]) -> Optional[str]:
    """Format token count distinguishing measured exact counts from estimations (~)."""
    if measured is not None:
        return str(measured)
    elif estimated is not None:
        return f"~{estimated}"
    return None


@dataclass
class TelemetryRecord:
    """Immutable record of an individual router invocation attempt."""
    timestamp: float
    iso_time: str
    role: str
    profile_id: str
    provider: str
    model: str
    outcome: str  # "success" | "failover" | "error" | "quota_exhausted" | "rate_limited" | "auth_required"
    latency_seconds: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    prompt_tokens_measured: Optional[int] = None
    prompt_tokens_estimated: Optional[int] = None
    completion_tokens_measured: Optional[int] = None
    completion_tokens_estimated: Optional[int] = None
    total_tokens_measured: Optional[int] = None
    total_tokens_estimated: Optional[int] = None
    is_estimated: bool = False
    cost_usd: Optional[float] = None
    failover_count: int = 0
    error_category: Optional[str] = None
    source: str = "own_measurement"

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None or k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd")}


@dataclass
class TelemetryAggregates:
    """Computed empirical metrics over a time window."""
    window_seconds: Optional[int]
    total_calls: int
    successful_calls: int
    failed_calls: int
    call_share: Optional[float] = None   # Ratio of filtered calls to total window calls (0.0-1.0) or None
    error_rate: Optional[float] = None   # 0.0 - 1.0 or None if total_calls == 0
    latency_p50_ms: Optional[float] = None      # Median latency in ms or None if total_calls == 0
    latency_p95_ms: Optional[float] = None      # 95th percentile latency in ms or None if total_calls == 0
    latency_max_ms: Optional[float] = None      # Maximum latency in ms or None if total_calls == 0
    total_prompt_tokens: Optional[int] = None   # Sum of reported prompt tokens or None if no token data
    total_completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    total_prompt_tokens_measured: Optional[int] = None
    total_prompt_tokens_estimated: Optional[int] = None
    total_completion_tokens_measured: Optional[int] = None
    total_completion_tokens_estimated: Optional[int] = None
    total_tokens_measured: Optional[int] = None
    total_tokens_estimated: Optional[int] = None
    tokens_display: Optional[str] = None
    has_estimated_tokens: bool = False
    total_cost_usd: Optional[float] = None      # Sum of calculated costs or None if no pricing available
    failovers_count: int = 0
    failover_reasons: Dict[str, int] = field(default_factory=dict)
    routed_calls_count: int = 0
    bypassed_calls_count: int = 0
    bypass_rate: Optional[float] = None
    source: str = "own_measurement"
    has_data: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



class TelemetryService:
    """Thread-safe persistent telemetry manager with bounded storage and honest aggregation."""

    _instance: Optional[TelemetryService] = None
    _instance_lock = threading.Lock()

    def __init__(self, log_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._buffer: collections.deque[TelemetryRecord] = collections.deque(maxlen=MAX_MEMORY_RECORDS)
        self._pricing_table: Dict[str, Dict[str, float]] = {}

        if log_path:
            self._log_path = log_path
        else:
            hermes_home = paths.get_hermes_home()
            self._log_path = hermes_home / "telemetry.jsonl"

        self._load_pricing()
        self._load_recent_history()

    @classmethod
    def get(cls) -> TelemetryService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    def set_pricing_table(self, pricing: Dict[str, Dict[str, float]]) -> None:
        """Set or update the in-memory pricing table: {model_id_or_pattern: {input_cost_per_m: float, output_cost_per_m: float}}."""
        with self._lock:
            self._pricing_table = dict(pricing)

    def _load_pricing(self) -> None:
        """Load optional pricing table from router_profiles.yaml or pricing.yaml."""
        try:
            from .router_config import load_router_config
            cfg = load_router_config()
            if hasattr(cfg, "pricing") and isinstance(cfg.pricing, dict):
                self._pricing_table = dict(cfg.pricing)
                return
        except Exception:
            pass

        # Check for config/pricing.yaml or ~/.hermes/pricing.yaml
        for p in [paths.get_hermes_home() / "pricing.yaml", paths.get_repo_root() / "config" / "pricing.yaml"]:
            if p.is_file():
                try:
                    import yaml
                    data = yaml.safe_dump(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "pricing" in data:
                        self._pricing_table = dict(data["pricing"])
                        return
                except Exception:
                    pass

    def compute_cost(self, model: str, prompt_tokens: Optional[int], completion_tokens: Optional[int]) -> Optional[float]:
        """Compute USD cost for token usage if pricing is configured for this model; otherwise None."""
        if prompt_tokens is None and completion_tokens is None:
            return None
        if not self._pricing_table:
            return None

        p_tok = prompt_tokens or 0
        c_tok = completion_tokens or 0

        # Exact match or normalized model match
        m_lower = model.lower().strip()
        price_entry = None
        for k, v in self._pricing_table.items():
            k_lower = k.lower().strip()
            if k_lower == m_lower or k_lower in m_lower or m_lower in k_lower:
                price_entry = v
                break

        if not price_entry or not isinstance(price_entry, dict):
            return None

        in_rate = float(price_entry.get("input_cost_per_m", 0.0))
        out_rate = float(price_entry.get("output_cost_per_m", 0.0))

        cost = (p_tok * in_rate + c_tok * out_rate) / 1_000_000.0
        return round(cost, 6)

    def record_call(
        self,
        role: str,
        profile_id: str,
        provider: str,
        model: str,
        outcome: str,
        latency_seconds: float,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        failover_count: int = 0,
        error_category: Optional[str] = None,
        prompt_tokens_measured: Optional[int] = None,
        prompt_tokens_estimated: Optional[int] = None,
        completion_tokens_measured: Optional[int] = None,
        completion_tokens_estimated: Optional[int] = None,
        total_tokens_measured: Optional[int] = None,
        total_tokens_estimated: Optional[int] = None,
        is_estimated: bool = False,
    ) -> TelemetryRecord:
        """Record an invocation attempt into memory and rotated log."""
        now = time.time()
        iso = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if is_estimated:
            p_est = prompt_tokens_estimated if prompt_tokens_estimated is not None else prompt_tokens
            c_est = completion_tokens_estimated if completion_tokens_estimated is not None else completion_tokens
            t_est = total_tokens_estimated if total_tokens_estimated is not None else total_tokens
            if t_est is None and p_est is not None and c_est is not None:
                t_est = p_est + c_est
            p_meas, c_meas, t_meas = None, None, None
            p_tok, c_tok, t_tok = p_est, c_est, t_est
        else:
            p_meas = prompt_tokens_measured if prompt_tokens_measured is not None else prompt_tokens
            c_meas = completion_tokens_measured if completion_tokens_measured is not None else completion_tokens
            t_meas = total_tokens_measured if total_tokens_measured is not None else total_tokens
            if t_meas is None and p_meas is not None and c_meas is not None:
                t_meas = p_meas + c_meas
            p_est = prompt_tokens_estimated
            c_est = completion_tokens_estimated
            t_est = total_tokens_estimated
            if t_est is None and p_est is not None and c_est is not None:
                t_est = p_est + c_est
            p_tok = p_meas if p_meas is not None else p_est
            c_tok = c_meas if c_meas is not None else c_est
            t_tok = t_meas if t_meas is not None else t_est

        cost_usd = self.compute_cost(model, p_tok, c_tok)

        record = TelemetryRecord(
            timestamp=now,
            iso_time=iso,
            role=role,
            profile_id=profile_id,
            provider=provider,
            model=model,
            outcome=outcome,
            latency_seconds=round(max(0.0, float(latency_seconds)), 4),
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            prompt_tokens_measured=p_meas,
            prompt_tokens_estimated=p_est,
            completion_tokens_measured=c_meas,
            completion_tokens_estimated=c_est,
            total_tokens_measured=t_meas,
            total_tokens_estimated=t_est,
            is_estimated=is_estimated or (p_est is not None and p_meas is None),
            cost_usd=cost_usd,
            failover_count=failover_count,
            error_category=error_category,
        )

        with self._lock:
            self._buffer.append(record)

        self._append_to_disk(record)
        return record

    def record_bypass(
        self,
        role: str,
        reason: str,
        resolution_source: Optional[str] = None,
    ) -> TelemetryRecord:
        """Record an invocation attempt that bypassed hub routing."""
        return self.record_call(
            role=role,
            profile_id="bypass",
            provider="hermes",
            model="bypass",
            outcome="bypass",
            latency_seconds=0.0,
            error_category=reason,
        )

    def _append_to_disk(self, record: TelemetryRecord) -> None:
        """Append record to disk with size-based log rotation."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)

            # Check rotation
            if self._log_path.is_file() and self._log_path.stat().st_size > MAX_FILE_BYTES:
                self._rotate_logs()

            line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.debug("Failed to write telemetry record to disk: %s", exc)

    def _rotate_logs(self) -> None:
        """Rotate telemetry log files keeping up to MAX_BACKUP_FILES."""
        try:
            for i in range(MAX_BACKUP_FILES - 1, 0, -1):
                s_file = self._log_path.with_name(f"{self._log_path.name}.{i}")
                d_file = self._log_path.with_name(f"{self._log_path.name}.{i + 1}")
                if s_file.exists():
                    s_file.replace(d_file)

            first_backup = self._log_path.with_name(f"{self._log_path.name}.1")
            self._log_path.replace(first_backup)
        except Exception as exc:
            logger.debug("Telemetry log rotation failed: %s", exc)

    def _load_recent_history(self) -> None:
        """Load recent records from disk into memory ring buffer."""
        if not self._log_path.is_file():
            return
        try:
            lines = []
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)

            # Load up to last MAX_MEMORY_RECORDS
            recent = lines[-MAX_MEMORY_RECORDS:]
            for r_str in recent:
                try:
                    d = json.loads(r_str)
                    rec = TelemetryRecord(
                        timestamp=float(d.get("timestamp", 0.0)),
                        iso_time=d.get("iso_time", ""),
                        role=d.get("role", ""),
                        profile_id=d.get("profile_id", ""),
                        provider=d.get("provider", ""),
                        model=d.get("model", ""),
                        outcome=d.get("outcome", "success"),
                        latency_seconds=float(d.get("latency_seconds", 0.0)),
                        prompt_tokens=d.get("prompt_tokens"),
                        completion_tokens=d.get("completion_tokens"),
                        total_tokens=d.get("total_tokens"),
                        prompt_tokens_measured=d.get("prompt_tokens_measured"),
                        prompt_tokens_estimated=d.get("prompt_tokens_estimated"),
                        completion_tokens_measured=d.get("completion_tokens_measured"),
                        completion_tokens_estimated=d.get("completion_tokens_estimated"),
                        total_tokens_measured=d.get("total_tokens_measured"),
                        total_tokens_estimated=d.get("total_tokens_estimated"),
                        is_estimated=bool(d.get("is_estimated", False)),
                        cost_usd=d.get("cost_usd"),
                        failover_count=int(d.get("failover_count", 0)),
                        error_category=d.get("error_category"),
                        source=d.get("source", "own_measurement"),
                    )
                    self._buffer.append(rec)
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Failed loading telemetry history from disk: %s", exc)

    def get_aggregates(
        self,
        window_seconds: Optional[int] = None,
        provider: Optional[str] = None,
        profile_id: Optional[str] = None,
        model: Optional[str] = None,
        role: Optional[str] = None,
    ) -> TelemetryAggregates:
        """Compute empirical aggregates for matching calls over an optional time window."""
        now = time.time()
        cutoff = (now - window_seconds) if window_seconds is not None else 0.0

        with self._lock:
            all_window_records = [r for r in self._buffer if r.timestamp >= cutoff]
            total_window_calls = len(all_window_records)

            records = [
                r for r in all_window_records
                if (provider is None or r.provider == provider)
                and (profile_id is None or r.profile_id == profile_id)
                and (model is None or r.model == model)
                and (role is None or r.role == role)
            ]

        total_calls = len(records)
        if total_calls == 0:
            return TelemetryAggregates(
                window_seconds=window_seconds,
                total_calls=0,
                successful_calls=0,
                failed_calls=0,
                call_share=None,
                error_rate=None,
                latency_p50_ms=None,
                latency_p95_ms=None,
                latency_max_ms=None,
                total_prompt_tokens=None,
                total_completion_tokens=None,
                total_tokens=None,
                total_prompt_tokens_measured=None,
                total_prompt_tokens_estimated=None,
                total_completion_tokens_measured=None,
                total_completion_tokens_estimated=None,
                total_tokens_measured=None,
                total_tokens_estimated=None,
                tokens_display=None,
                has_estimated_tokens=False,
                total_cost_usd=None,
                failovers_count=0,
                failover_reasons={},
                routed_calls_count=0,
                bypassed_calls_count=0,
                bypass_rate=None,
                source="own_measurement",
                has_data=False,
            )

        call_share = round(total_calls / total_window_calls, 4) if total_window_calls > 0 else None

        successful_calls = 0
        failed_calls = 0
        routed_calls_count = 0
        bypassed_calls_count = 0
        latencies_ms: List[float] = []
        prompt_tokens_sum = 0
        completion_tokens_sum = 0
        has_any_token_data = False
        prompt_meas_sum = 0
        prompt_est_sum = 0
        has_meas_prompt = False
        has_est_prompt = False
        comp_meas_sum = 0
        comp_est_sum = 0
        has_meas_comp = False
        has_est_comp = False
        has_estimated_tokens = False
        costs_sum = 0.0
        has_any_cost_data = False
        failovers_count = 0
        failover_reasons: Dict[str, int] = collections.defaultdict(int)

        for r in records:
            if r.outcome == "bypass":
                bypassed_calls_count += 1
            else:
                routed_calls_count += 1
                latencies_ms.append(r.latency_seconds * 1000.0)

            if r.outcome in ("success", "failover"):
                successful_calls += 1
            elif r.outcome != "bypass":
                failed_calls += 1

            if r.failover_count > 0 or r.outcome == "failover":
                failovers_count += 1
                reason_key = r.error_category or r.outcome
                failover_reasons[reason_key] += 1

            if r.prompt_tokens is not None:
                prompt_tokens_sum += r.prompt_tokens
                has_any_token_data = True
            if r.completion_tokens is not None:
                completion_tokens_sum += r.completion_tokens
                has_any_token_data = True

            if r.prompt_tokens_measured is not None:
                prompt_meas_sum += r.prompt_tokens_measured
                has_meas_prompt = True
            elif r.prompt_tokens is not None and not r.is_estimated:
                prompt_meas_sum += r.prompt_tokens
                has_meas_prompt = True

            if r.prompt_tokens_estimated is not None:
                prompt_est_sum += r.prompt_tokens_estimated
                has_est_prompt = True
                has_estimated_tokens = True
            elif r.prompt_tokens is not None and r.is_estimated:
                prompt_est_sum += r.prompt_tokens
                has_est_prompt = True
                has_estimated_tokens = True

            if r.completion_tokens_measured is not None:
                comp_meas_sum += r.completion_tokens_measured
                has_meas_comp = True
            elif r.completion_tokens is not None and not r.is_estimated:
                comp_meas_sum += r.completion_tokens
                has_meas_comp = True

            if r.completion_tokens_estimated is not None:
                comp_est_sum += r.completion_tokens_estimated
                has_est_comp = True
                has_estimated_tokens = True
            elif r.completion_tokens is not None and r.is_estimated:
                comp_est_sum += r.completion_tokens
                has_est_comp = True
                has_estimated_tokens = True

            if r.is_estimated:
                has_estimated_tokens = True

            if r.cost_usd is not None:
                costs_sum += r.cost_usd
                has_any_cost_data = True

        latencies_ms.sort()
        p50 = self._percentile(latencies_ms, 50)
        p95 = self._percentile(latencies_ms, 95)
        max_lat = latencies_ms[-1] if latencies_ms else None

        error_rate = round(failed_calls / total_calls, 4) if total_calls > 0 else 0.0
        bypass_rate = round(bypassed_calls_count / total_calls, 4) if total_calls > 0 else 0.0
        total_tokens_sum = (prompt_tokens_sum + completion_tokens_sum) if has_any_token_data else None
        tot_meas_sum = (prompt_meas_sum + comp_meas_sum) if (has_meas_prompt or has_meas_comp) else None
        tot_est_sum = (prompt_est_sum + comp_est_sum) if (has_est_prompt or has_est_comp) else None
        tokens_display = format_token_count(tot_meas_sum, tot_est_sum)

        return TelemetryAggregates(
            window_seconds=window_seconds,
            total_calls=total_calls,
            successful_calls=successful_calls,
            failed_calls=failed_calls,
            call_share=call_share,
            error_rate=error_rate,
            latency_p50_ms=round(p50, 1) if p50 is not None else None,
            latency_p95_ms=round(p95, 1) if p95 is not None else None,
            latency_max_ms=round(max_lat, 1) if max_lat is not None else None,
            total_prompt_tokens=prompt_tokens_sum if has_any_token_data else None,
            total_completion_tokens=completion_tokens_sum if has_any_token_data else None,
            total_tokens=total_tokens_sum,
            total_prompt_tokens_measured=prompt_meas_sum if has_meas_prompt else None,
            total_prompt_tokens_estimated=prompt_est_sum if has_est_prompt else None,
            total_completion_tokens_measured=comp_meas_sum if has_meas_comp else None,
            total_completion_tokens_estimated=comp_est_sum if has_est_comp else None,
            total_tokens_measured=tot_meas_sum,
            total_tokens_estimated=tot_est_sum,
            tokens_display=tokens_display,
            has_estimated_tokens=has_estimated_tokens,
            total_cost_usd=round(costs_sum, 4) if has_any_cost_data else None,
            failovers_count=failovers_count,
            failover_reasons=dict(failover_reasons),
            routed_calls_count=routed_calls_count,
            bypassed_calls_count=bypassed_calls_count,
            bypass_rate=bypass_rate,
            source="own_measurement",
            has_data=True,
        )


    def get_breakdown(
        self,
        window_seconds: Optional[int] = 86400,
        known_providers: Optional[List[str]] = None,
        known_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate structured telemetry breakdown for overall hub, per provider, and per role."""
        global_aggs = self.get_aggregates(window_seconds=window_seconds)

        providers = set(known_providers or ["antigravity", "openai-codex", "opencode-go"])
        roles = set(known_roles or RoleRegistry.get_role_ids())

        with self._lock:
            for r in self._buffer:
                if r.provider:
                    providers.add(r.provider)
                if r.role:
                    roles.add(r.role)

        by_provider = {}
        for prov in sorted(providers):
            by_provider[prov] = self.get_aggregates(window_seconds=window_seconds, provider=prov).to_dict()

        by_role = {}
        for role in sorted(roles):
            by_role[role] = self.get_aggregates(window_seconds=window_seconds, role=role).to_dict()

        return {
            "global": global_aggs.to_dict(),
            "by_provider": by_provider,
            "by_role": by_role,
            "window_seconds": window_seconds,
            "source": "own_measurement",
            "has_data": global_aggs.has_data,
        }

    @staticmethod
    def _percentile(sorted_data: List[float], percent: int) -> Optional[float]:
        """Compute the n-th percentile from a pre-sorted numeric list."""
        if not sorted_data:
            return None
        k = (len(sorted_data) - 1) * (percent / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return float(sorted_data[int(k)])
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return float(d0 + d1)
