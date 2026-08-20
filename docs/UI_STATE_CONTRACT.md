# Hermes Hub — UI State & ViewModel Contract

**Document Version:** 1.0.0  
**Date:** 2026-08-21  
**Status:** Canonical Interface Specification for UI (Codex Assignment B) & State Layer (Antigravity Assignment A)  
**Scope:** `src/antigravity_provider/router/state_store.py`, `unified_health.py`, `account_identity.py`, `event_bus.py`

---

## 1. Executive Architecture & Invariants

1. **Single Source of Truth (`HubSnapshot`):** The entire UI layer reads state exclusively from the immutable `HubSnapshot` supplied by `HubStateStore.get().get_snapshot()` or emitted via `EventBus`. Views MUST NOT call scanning/probing methods (e.g. `scan_all()`).
2. **Delta Updates via `EventBus`:** Incremental updates (quota shifts, single account mutations, route swaps) dispatch targeted typed events on `EventBus.get()`.
3. **Data Truthfulness Invariant:** Unverified or offline metrics MUST report `is_estimated = True` with source `"baseline"` or `"estimated"`, and percentages as `None` (UI displays «Доступна» / «(оценка)»). Fabricated percentages or false `*_api` source labels are strictly forbidden.

---

## 2. Core Snapshot Model: `HubSnapshot`

Immutable snapshot (`@dataclass(frozen=True)`) representing the state of Hermes Hub at generation `generation`.

| Field | Type | Description | Real / Simulated |
|---|---|---|---|
| `generation` | `int` | Monotonically increasing generation number (increments on every snapshot update). | **Real** |
| `timestamp` | `float` | UNIX epoch timestamp when snapshot was created (`time.time()`). | **Real** |
| `profiles_by_provider` | `Dict[str, List[ProfileViewModel]]` | Profiles grouped by provider identifier (`"antigravity"`, `"openai-codex"`, `"opencode-go"`, `"claude"`, `"grok"`). | **Real** |
| `all_profiles` | `Dict[str, ProfileViewModel]` | Flat lookup map of all profiles indexed by `profile_id`. | **Real** |
| `readiness` | `SystemReadiness` | Aggregated system readiness, role coverage metrics, and warnings. | **Real** |
| `agents` | `List[AgentViewModel]` | List of logical agent roles and their active routing status. | **Real** |
| `providers` | `List[ProviderSummary]` | Summary status per provider for quick overview cards. | **Real** |
| `routing` | `Dict[str, RolePipeline]` | Role pipelines mapping `role_id` to failover nodes. | **Real** |
| `quotas` | `Dict[str, QuotaSnapshot]` | Map of `profile_id` -> `QuotaSnapshot`. | **Real** |
| `metrics` | `Dict[str, Any]` | Internal metrics (e.g. `refresh_runs_total`, `refresh_failures_total`). | **Real** |
| `is_stale` | `bool` | True if background refresh is overdue (> 300s). | **Real** |

### Helper Methods
- `get_profile(profile_id: str) -> Optional[ProfileViewModel]`
- `get_provider_profiles(provider: str) -> List[ProfileViewModel]`
- `get_role_pipeline(role_id: str) -> Optional[RolePipeline]`

---

## 3. Account View Model: `ProfileViewModel`

Model representing an individual account/slot card in UI views.

| Field | Type | Nullable / Optional | Description & Values |
|---|---|---|---|
| `profile_id` | `str` | No | Unique profile identifier (e.g. `"ag-w1"`, `"codex-slot-1"`). |
| `display_name` | `str` | No | User-facing display title (e.g. `"Antigravity Slot 1"`). |
| `account_identity` | `str` | No | Primary user identity (email, account ID, or profile ID). |
| `provider` | `str` | No | Provider ID (`"antigravity"`, `"openai-codex"`, `"opencode-go"`, `"claude"`, `"grok"`). |
| `provider_display_name` | `str` | No | Formatted provider name (e.g. `"Google Antigravity"`, `"OpenAI Codex"`). |
| `assigned_roles` | `List[str]` | No | List of role names assigned to this profile. |
| `primary_role` | `Optional[str]` | Yes | Primary assigned role name (or `None` if unassigned / spare). |
| `is_main_account` | `bool` | No | True if designated as Main Account for general execution. |
| `is_main_orchestrator` | `bool` | No | True if designated as Orchestrator profile. |
| `auth_state` | `str` | No | `"AUTHENTICATED"` \| `"AUTH_REQUIRED"` \| `"AUTH_EXPIRED"` \| `"UNCONFIGURED"`. |
| `health_state` | `str` | No | `"healthy"` \| `"warning"` \| `"exhausted"` \| `"rate_limited"` \| `"cooldown"` \| `"auth_required"` \| `"disabled"` \| `"cold_spare"` \| `"unhealthy"` \| `"not_configured"`. |
| `health_label_ru` | `str` | No | Localized Russian status text (e.g. `"Готов"`, `"Исчерпан"`, `"Ограничение"`). |
| `model_states` | `Dict[str, ModelFamilyHealth]` | No | Per-family health records (e.g. `{"gemini": ModelFamilyHealth(...)}`). |
| `cooldown_remaining_sec` | `int` | No | Seconds until cooldown/rate-limit expires (`0` if healthy). |
| `last_checked_at` | `Optional[str]` | Yes | Formatted time string (e.g. `"15:42:10"` or `"недавно"`). |
| `enabled` | `bool` | No | True if slot is enabled in `router_profiles.yaml`. |
| `is_cold_spare` | `bool` | No | True if authenticated but unassigned to any active role chain. |
| `is_empty_slot` | `bool` | No | True if unauthenticated placeholder slot. |
| `email` | `str` | No | Email parsed from JWT/API (empty string if unavailable). |
| `plan` | `str` | No | Localized plan string (e.g. `"Тариф: MAX"`, `"Тариф: PRO"`, `"Тариф: неизвестен"`). |
| `plan_code` | `str` | No | Normalized plan code (`"PRO"`, `"PLUS"`, `"MAX"`, `"SUPERGROK"`, `"UNKNOWN"`). |
| `quota_snapshot` | `Optional[QuotaSnapshot]` | Yes | Associated quota snapshot object. |
| `preferred_models` | `List[str]` | No | List of configured models for this profile. |

---

## 4. Quota Models: `QuotaSnapshot` & `QuotaBucket`

### `QuotaSnapshot` Schema
- `account_id: str` — Profile or Account ID
- `provider: str` — Provider ID
- `buckets: List[QuotaBucket]` — 1 to 4 limit buckets
- `fetched_at: datetime` — UTC timestamp of measurement
- `stale_after_seconds: int` — Expiry window (default 300s)
- `source: str` — `"baseline"` \| `"estimated"` \| `"runtime_event"` \| `"provider_api"`
- `is_estimated: bool` — **True** if offline baseline / heuristic, **False** if verified live API
- `freshness_label() -> str` — e.g. `"Обновлено: только что"`, `"Обновлено: 5 мин назад"`

### `QuotaBucket` Schema
- `id: str` — e.g. `"antigravity.claude.5h"`, `"codex.weekly"`, `"grok.frequent_tasks"`
- `display_name: str` — e.g. `"5h"`, `"Weekly"`, `"Задачи"`, `"Запросы"`
- `model_family: Optional[str]` — Model family bounded by this bucket (`"gemini"`, `"claude"`, `"gpt"`, `"grok"`, `"opencode"`)
- `used_percent: Optional[float]` — `0.0 .. 100.0` or `None` if unmeasured
- `remaining_percent: Optional[float]` — `0.0 .. 100.0` or `None` if unmeasured
- `used_absolute: Optional[int]` — Absolute units used (if reported by provider API)
- `remaining_absolute: Optional[int]` — Absolute units remaining
- `limit_absolute: Optional[int]` — Absolute maximum limit
- `reset_at: Optional[datetime]` — UTC reset timestamp
- `reset_in_seconds: Optional[int]` — Seconds until quota reset
- `period: Optional[str]` — `"5h"`, `"7d"`, `"30d"`, `"sliding"`
- `status: str` — `"healthy"`, `"warning"`, `"exhausted"`, `"unknown"`
- `formatted_remaining() -> str` — e.g. `"Доступна"`, `"Осталось 85%"`, `"150/1000"`
- `formatted_reset() -> Optional[str]` — e.g. `"Сброс через 1ч 45м"`, `None`

---

## 5. Actual Provider Quota Breakdown (Live vs Estimated)

| Provider | Real Quota APIs Available? | Buckets Populated | `source` | `is_estimated` | Notes |
|---|---|---|---|---|---|
| **Google Antigravity** | Partial (via CLI runtime 429 reset parsing) | `antigravity.claude.5h`, `antigravity.claude.weekly`, `antigravity.gemini` | `"baseline"` or `"runtime_event"` | `True` (baseline) / `False` (on 429 event) | Baseline shows «Доступна (оценка)». On 429, parses exact reset duration. |
| **OpenAI Codex** | Device flow / local token | `codex.primary.weekly` | `"baseline"` or `"runtime_event"` | `True` (baseline) / `False` (on 429 event) | Baseline shows «Доступна (оценка)». |
| **xAI Grok** | Device flow / token | `grok.frequent_tasks`, `grok.daily_quota` | `"baseline"` or `"runtime_event"` | `True` (baseline) / `False` (on 429 event) | Baseline shows «Доступна (оценка)». |
| **Anthropic Claude** | Token / PKCE | `claude.session.5h`, `claude.weekly` | `"baseline"` or `"runtime_event"` | `True` (baseline) / `False` (on 429 event) | Baseline shows «Доступна (оценка)». |
| **OpenCode Go** | Local CLI / API key | `opencode.tasks` | `"baseline"` | `True` | Baseline shows «Доступна (оценка)». |

---

## 6. Routing & System ViewModels

### `SystemReadiness`
- `state: str` — `"healthy"` \| `"limited"` \| `"degraded"` \| `"critical"`
- `title_ru: str` — Summary title (e.g. `"Система готова к работе"`)
- `summary_ru: str` — Explanatory status text
- `roles_ready_count: int`, `total_roles: int`
- `accounts_connected_count: int`, `total_accounts: int`
- `providers_ready_count: int`, `total_providers: int`
- `warnings: List[str]` — Critical warning strings for banner display

### `AgentViewModel`
- `role_id: str` — Logical role (e.g. `"coder-primary"`, `"reviewer"`)
- `role_name_ru: str`, `role_description_ru: str`
- `assigned_profile_id: Optional[str]`, `assigned_display_name: Optional[str]`
- `provider: str`, `provider_display_name: str`, `model: str`
- `routing_position: str` — `"Primary"`, `"Fallback 1"`, `"Fallback 2"`
- `status: str` — `"healthy"`, `"exhausted"`, `"auth_required"`, `"unconfigured"`
- `is_active: bool`, `is_main_orchestrator: bool`, `cooldown_remaining_sec: int`

### `RolePipeline` & `PipelineNode`
- `RolePipeline`: `role_id`, `role_name_ru`, `default_model`, `max_failover`, `session_affinity`, `active_profile_id`, `nodes: List[PipelineNode]`
- `PipelineNode`: `profile_id`, `display_name`, `provider`, `model`, `status`, `status_label_ru`, `is_active: bool`, `cooldown_remaining_sec: int`

### `ProviderSummary`
- `provider_id: str`, `provider_name: str`, `total_slots: int`, `connected_count: int`, `online_count: int`
- `auth_required_count: int`, `quota_exhausted_count: int`, `cold_spare_count: int`
- `discovered_models: List[str]`, `last_refresh_at: str`

---

## 7. EventBus Event Catalog & Payloads

Subscribers register with `EventBus.get().subscribe(event_name, callback)`:

| Event Constant | Name String | Payload Schema | Trigger Condition |
|---|---|---|---|
| `EVENT_ACCOUNT_UPDATED` | `"ACCOUNT_UPDATED"` | `{"provider": str, "profile_id": str, "profile": ProfileViewModel}` | Single profile auth, role, or state changed |
| `EVENT_ACCOUNT_ADDED` | `"ACCOUNT_ADDED"` | `{"provider": str, "profile_id": str}` | New account authorized / connected |
| `EVENT_ACCOUNT_REMOVED` | `"ACCOUNT_REMOVED"` | `{"provider": str, "profile_id": str}` | Account removed / disconnected |
| `EVENT_ACCOUNT_AUTH_CHANGED` | `"ACCOUNT_AUTH_CHANGED"` | `{"provider": str, "profile_id": str, "auth_state": str}` | Token expired or auth invalidated |
| `EVENT_QUOTA_UPDATED` | `"QUOTA_UPDATED"` | `{"provider": str, "profile_id": str, "snapshot": QuotaSnapshot}` | Single account quota changed (429 or refresh) |
| `EVENT_QUOTA_STALE` | `"QUOTA_STALE"` | `{"provider": str, "profile_id": str}` | Quota snapshot expired |
| `EVENT_PROVIDER_HEALTH_CHANGED` | `"PROVIDER_HEALTH_CHANGED"` | `{"provider": str, "summary": ProviderSummary}` | Aggregate provider health shift |
| `EVENT_ROUTING_UPDATED` | `"ROUTING_UPDATED"` | `{"role_id": str, "pipeline": RolePipeline}` | Active role routing modified |
| `EVENT_ROUTING_SLOT_UPDATED` | `"ROUTING_SLOT_UPDATED"` | `{"role_id": str, "node": PipelineNode}` | Failover occurred to backup node |
| `EVENT_AGENT_UPDATED` | `"AGENT_UPDATED"` | `{"role_id": str, "agent": AgentViewModel}` | Agent role status changed |
| `EVENT_SYSTEM_READINESS_CHANGED`| `"SYSTEM_READINESS_CHANGED"`| `{"readiness": SystemReadiness}` | Global readiness level shifted |
| `EVENT_REFRESH_STARTED` | `"REFRESH_STARTED"` | `{"scope": str, "provider": Optional[str], "seq": int}` | Background refresh task started |
| `EVENT_REFRESH_COMPLETED` | `"REFRESH_COMPLETED"` | `{"scope": str, "provider": Optional[str], "seq": int}` | Background refresh task succeeded |
| `EVENT_REFRESH_FAILED` | `"REFRESH_FAILED"` | `{"scope": str, "provider": Optional[str], "error": str, "seq": int}` | Background refresh task failed |

---

## 8. Backend Gaps (Known Limitations & Gaps)

To maintain complete transparency and prevent UI fabrication:

1. **Live Quota Metrics:**
   - OpenAI, xAI, and Claude do not offer public standard REST endpoints for real-time per-second token balances on OAuth device tokens without dedicated organization admin keys.
   - Consequently, initial state reports `source="baseline"`, `is_estimated=True`, and percentages as `None`.
   - Quotas transition to `status="exhausted"`, `source="runtime_event"`, `is_estimated=False` with exact reset timers **only upon encountering real provider 429 responses** during runtime execution.
2. **Subscription Expiry Timestamps:**
   - `SubscriptionPlan.expires_at` and `renews_at` are populated when present in JWT claims (e.g. Google CloudCode / Anthropic JWT claims); otherwise they are `None`.
3. **Model Discovery:**
   - Static default fallback models are provided when offline or before the first CLI invocation.
