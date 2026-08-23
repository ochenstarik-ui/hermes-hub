# Hermes Hub UI state contract

- Contract version: **1.2**
- Published against: **`9ffc815ed59f7fd364e176ffef20bf29d545bc46`**
- Contract owner: `antigravity/release-readiness`
- Consumer: `codex/ui-redesign`

This document describes the backend state that the native UI may render. It is
descriptive of the code at the published commit. Fields marked **real** are
backed by persisted configuration, authentication metadata, runtime health or
provider responses. Fields marked **derived** are computed from real fields.
Fields marked **estimated** or **placeholder** must be labelled as such or
hidden by the UI.

---

## 1. Snapshot boundary

### `HubSnapshot`

Defined in `router/state_store.py` as a frozen dataclass.

| Field | Type | Reality and meaning |
|---|---|---|
| `generation` | `int` | **Real local sequence.** Monotonically increases for every accepted rebuild within one process. Starts at 1; an empty bootstrap snapshot uses 0. |
| `seq` | `int` | **Real request sequence token.** Monotonically increasing counter of the latest completed refresh request. Guaranteed to equal or exceed `generation`. |
| `timestamp` | `float` | **Real local time** (`time.time()`) when the snapshot was built. |
| `profiles_by_provider` | `dict[str, list[ProfileViewModel]]` | **Derived** normalized profiles grouped by provider. |
| `all_profiles` | `dict[str, ProfileViewModel]` | **Derived** map keyed by `profile_id`. Profile IDs are unique by this map. |
| `readiness` | `SystemReadiness` | **Derived** readiness summary. |
| `agents` | `list[AgentViewModel]` | **Derived** current role assignments with active quota and session tracking. |
| `providers` | `list[ProviderSummary]` | **Derived** provider summaries. |
| `routing` | `dict[str, RolePipeline]` | **Derived** routing pipelines keyed by role ID. |
| `quotas` | `dict[str, QuotaSnapshot]` | Keyed by `profile_id`; see provider truth matrix below. |
| `metrics` | `dict[str, Any]` | **Real local diagnostics:** generation, sequence, build duration, profile counts and refresh counters. |
| `is_stale` | `bool` | `True` for uninitialized bootstrap snapshots or when background refresh is overdue (> 300s). |

Consistency guarantees:

- The store publishes one snapshot reference after building it under an `RLock`; readers never observe a partially-built snapshot.
- `generation` and `seq` are public comparison keys for the UI.
- Stale background worker responses (`seq < _latest_applied_seq`) are strictly rejected and discarded.
- `get_snapshot()` returns the cached snapshot without blocking disk scans.

---

## 2. Account and health models

### `ProfileViewModel`

| Field | Type | Optional | Reality and meaning |
|---|---|---:|---|
| `profile_id` | `str` | no | **Real configuration slot/profile ID.** |
| `display_name` | `str` | no | **Real configured name** when present; otherwise localized slot fallback. |
| `account_identity` | `str` | no | Best available identifier: email → display name → provider account ID → profile ID. |
| `provider` | `str` | no | **Real normalized provider ID.** |
| `provider_display_name` | `str` | no | **Derived localized/display label.** |
| `assigned_roles` | `list[str]` | no | **Derived from router config.** |
| `primary_role` | `str` | yes | **Derived/configured.** May be absent for spare slots. |
| `is_main_account` | `bool` | no | **Real local profile preference.** |
| `is_main_orchestrator` | `bool` | no | **Derived from orchestrator chain.** |
| `auth_state` | `str` | no | Normalized auth state (`AUTHENTICATED`, `AUTH_REQUIRED`, `AUTH_EXPIRED`, `NOT_CONFIGURED`). |
| `health_state` | `str` | no | Normalized health state (`healthy`, `not_tested`, `quota_exhausted`, `rate_limited`, `cooldown`, `disabled`, `cold_spare`, `not_configured`, `unhealthy`). |
| `health_label_ru` | `str` | no | **Derived presentation label.** |
| `model_states` | `dict[str, ModelFamilyHealth]` | no | **Derived from local health tracker/runtime observations.** |
| `cooldown_remaining_sec` | `int` | no | **Derived local runtime state.** Zero when healthy. |
| `last_checked_at` | `str` | yes | **Real local check time string** (`%H:%M:%S`). |
| `last_success_at` | `str` | yes | **Time of last successful network test** (`%H:%M:%S`). |
| `enabled` | `bool` | no | **Real config state.** |
| `is_cold_spare` | `bool` | no | **Derived/configured.** |
| `is_empty_slot` | `bool` | no | **Derived** placeholder slot with no configured auth. |
| `email` | `str` | no | Extracted from saved auth/JWT claims; empty string if unavailable. |
| `plan` | `str` | no | Display text (e.g. `"Тариф: MAX"`, `"Тариф: PRO"`). |
| `plan_code` | `str` | no | Normalized code (`PRO`, `PLUS`, `MAX`, `SUPERGROK`, `UNKNOWN`). |
| `plan_source` | `str` | no | **Real provenance:** `"provider_api"`, `"jwt_claim"`, `"provider_auth"`, `"inferred"`, `"unknown"`. UI uses this to display `PlanBadge` only when trustworthy (`!= "unknown"`). |
| `quota_snapshot` | `QuotaSnapshot` | yes | Associated quota snapshot object. |
| `preferred_models` | `list[str]` | no | **Real config/model-discovery values.** |

---

## 3. Quota models

### `QuotaSnapshot`

| Field | Type | Reality and meaning |
|---|---|---|
| `account_id` | `str` | Real local profile/account key. |
| `provider` | `str` | Real normalized provider ID. |
| `buckets` | `list[QuotaBucket]` | Separate capacity pools; never combine them into one percent. |
| `fetched_at` | timezone-aware `datetime` | Real local collection time. |
| `stale_after_seconds` | `int` | Local cache TTL, default 300 seconds. |
| `source` | `str` | Provenance: `"runtime_event"`, `"jwt_claim"`, `"provider_auth"`, `"baseline"`, `"unconfigured"`. |
| `unavailable_reason` | `Optional[str]` | Human-readable reason when data cannot be collected. |
| `is_estimated` | property | `True` for baseline/unconfigured; `False` for verified runtime events and provider claims. |

### `QuotaBucket`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Stable bucket key (`antigravity.claude.5h`, `antigravity.gemini.5h`, `codex.primary.weekly`, `claude.session.5h`, `grok.frequent_tasks`). |
| `display_name` | `str` | User-facing label (`"Claude 5h"`, `"Gemini 5h"`, `"Codex Weekly"`). |
| `model_family` | `Optional[str]` | Family selector (`"claude"`, `"gemini"`, `"gpt"`, `"grok"`, `"opencode"`). |
| `used_percent` | `Optional[float]` | 0.0–100.0 or `None` if unmeasured. |
| `remaining_percent` | `Optional[float]` | 0.0–100.0 or `None` if unmeasured. |
| `used_absolute` | `Optional[int]` | Absolute units used if reported. |
| `remaining_absolute` | `Optional[int]` | Absolute units remaining. |
| `limit_absolute` | `Optional[int]` | Absolute maximum limit. |
| `reset_at` | `Optional[datetime]` | UTC reset timestamp. |
| `reset_in_seconds` | `Optional[int]` | Seconds until quota reset. |
| `period` | `Optional[str]` | `"5h"`, `"7d"`, `"30d"`, `"sliding"`. |
| `status` | `str` | `"healthy"`, `"warning"`, `"exhausted"`, `"unknown"`. |

### Provider Truth Matrix at v1.3

| Provider | Buckets emitted | Values | Reset | Source / UI treatment |
|---|---|---|---|---|
| **Antigravity** | `antigravity.claude.5h`, `antigravity.gemini.5h`, `antigravity.claude.7d`, `antigravity.gemini.7d` | Measured Cloud Code capacity pool percentages (or per-model pool). On 429: exact 0% remaining. | Measured from Cloud Code resetTime. On 429: extracted from server response. | Live: `provider_api`, `is_estimated=False`. 429 event: `runtime_event`, `is_estimated=False`. |
| **OpenAI Codex** | `codex.session`, `codex.weekly` | Probes `/models` endpoint with stored credentials, refresh token on 401. Values: `None` with explicit `unavailable_reason`. | `None`. No synthetic reset times. | Live: `provider_api`, `is_estimated=False`, `unavailable_reason: "OpenAI Codex не предоставляет остаток через публичный API"`. |
| **OpenCode Go** | `opencode.5h`, `opencode.7d`, `opencode.30d` | Probes `/models` and `/usage`. When usage returned: measured percent & USD amounts. If 401/403/404: `None` with explicit reason. | Measured `reset_at` from `/usage` or `None`. | Live: `provider_api`, `is_estimated=False`. When usage endpoint unexposed: `unavailable_reason: "OpenCode Go не предоставляет остаток через публичный API"`. |
| **Claude** | `claude.session`, `claude.weekly` | Values: `None` with explicit `unavailable_reason`. | `None`. No synthetic reset times. | Live: `provider_api`, `is_estimated=False`, `unavailable_reason: "Claude не предоставляет остаток через публичный API"`. |
| **Grok** | `grok.weekly`, `grok.chat`, `grok.build`, `grok.frequent_tasks`, `grok.normal_tasks` | Values: `None` with explicit `unavailable_reason`. | `None`. No synthetic reset times. | Live: `provider_api`, `is_estimated=False`, `unavailable_reason: "Grok не предоставляет остаток через публичный API"`. |

### Provider Sorting Guarantee in Snapshot
`HubSnapshot.providers` is guaranteed to be deterministically ordered by:
1. `connected_count` descending (providers with active authenticated accounts appear first)
2. `total_slots` descending
3. `provider_name` ascending (alphabetical tie-breaker)

---

## 4. Team and routing models

### `AgentViewModel`

| Field | Type | Description |
|---|---|---|
| `role_id` | `str` | Logical role (`"orchestrator"`, `"coder-primary"`, `"reviewer"`, etc.). |
| `role_name_ru` | `str` | Localized role title (`"Главный оркестратор"`, `"Кодер 1"`). |
| `role_description_ru` | `str` | Localized role description. |
| `assigned_profile_id` | `Optional[str]` | Active profile ID assigned to this role. |
| `assigned_display_name` | `Optional[str]` | Display name of assigned profile. |
| `provider` | `str` | Active provider ID. |
| `provider_display_name` | `str` | Localized provider name. |
| `model` | `str` | Selected active model. |
| `account_identity` | `str` | Masked identity of the active account. |
| `routing_position` | `str` | `"Primary"`, `"Fallback 1"`, `"Fallback 2"`. |
| `status` | `str` | `"healthy"`, `"quota_exhausted"`, `"auth_required"`, etc. |
| `status_label_ru` | `str` | Localized status text (`"Работает"`, `"Исчерпан"`). |
| `is_active` | `bool` | True if healthy and receiving requests. |
| `is_main_orchestrator` | `bool` | True if role is orchestrator. |
| `cooldown_remaining_sec` | `int` | Active cooldown in seconds. |
| `session_id` | `Optional[str]` | Active affinity session bound to this agent. |
| `active_quota_status` | `str` | Status of governing quota bucket (`"healthy"`, `"warning"`, `"exhausted"`). |
| `active_quota_label` | `str` | Human-readable quota state (e.g. `"Осталось 85%"`, `"Доступна"`). |

### `PipelineNode` & `RolePipeline`

Each `PipelineNode` represents one failover step in a role's route:

| Field | Type | Description |
|---|---|---|
| `profile_id` | `str` | Profile ID for this step. |
| `display_name` | `str` | Slot display name. |
| `provider` | `str` | Localized provider name. |
| `model` | `str` | Model configured for this step. |
| `account_identity` | `str` | Masked account identity for this node. |
| `status` | `str` | Health status of this node (`"healthy"`, `"quota_exhausted"`). |
| `status_label_ru` | `str` | Localized status text. |
| `quota_status` | `str` | Quota health status (`"healthy"`, `"exhausted"`). |
| `is_active` | `bool` | True if this node is currently handling traffic. |
| `cooldown_remaining_sec` | `int` | Cooldown in seconds. |
| `failover_reason` | `Optional[str]` | Real reason why traffic switched from this node (e.g. `"Primary исчерпал квоту (429)"`, `"Требуется авторизация"`). `None` for active node or standby reserve. |

`RolePipeline`: `role_id`, `role_name_ru`, `default_model`, `max_failover`, `session_affinity`, `active_profile_id`, `nodes: List[PipelineNode]`.

---

## 5. Event bus contract

Callbacks receive `(event_name: str, payload: Any)`. All events carry active `generation` and `seq` tokens.

| Event Constant | Name String | Payload Contract (v1.2) | Canonical Publisher Site |
|---|---|---|---|
| `EVENT_ACCOUNT_UPDATED` | `"ACCOUNT_UPDATED"` | `{"profile_id": str, "profile": ProfileViewModel, "generation": int, "seq": int}` | `HubStateStore.apply_delta_account_updated` |
| `EVENT_ACCOUNT_ADDED` | `"ACCOUNT_ADDED"` | `{"provider": str, "profile_id": str, "profile": ProfileViewModel, "generation": int, "seq": int}` | `HubStateStore.apply_delta_account_added` |
| `EVENT_ACCOUNT_REMOVED` | `"ACCOUNT_REMOVED"` | `{"provider": str, "profile_id": str, "generation": int, "seq": int}` | `HubStateStore.apply_delta_account_removed` |
| `EVENT_ACCOUNT_AUTH_CHANGED` | `"ACCOUNT_AUTH_CHANGED"` | `{"provider": str, "profile_id": str, "auth_state": str, "generation": int, "seq": int}` | `HubStateStore.publish_auth_changed` |
| `EVENT_QUOTA_UPDATED` | `"QUOTA_UPDATED"` | `{"provider": str, "profile_id": str, "snapshot": QuotaSnapshot, "quota_snapshot": QuotaSnapshot, "generation": int, "seq": int}` | `HubStateStore.apply_delta_quota_updated` |
| `EVENT_ROUTING_UPDATED` | `"ROUTING_UPDATED"` | `{"role_id": str, "active_profile_id": str, "pipeline": RolePipeline, "generation": int, "seq": int}` | `HubStateStore.apply_delta_route_changed`, `RouterEngine.route_request` |
| `EVENT_AGENT_UPDATED` | `"AGENT_UPDATED"` | `{"role_id": str, "agent": AgentViewModel, "generation": int, "seq": int}` | `HubStateStore.apply_delta_route_changed` |
| `EVENT_SYSTEM_READINESS_CHANGED`| `"SYSTEM_READINESS_CHANGED"`| `{"readiness": SystemReadiness, "generation": int, "seq": int}` | `HubStateStore.refresh` |
| `EVENT_REFRESH_STARTED` | `"REFRESH_STARTED"` | `{"key": str, "seq": int}` | `HermesRefreshScheduler._execute_task` |
| `EVENT_REFRESH_COMPLETED` | `"REFRESH_COMPLETED"` | `{"generation": int, "seq": int, "duration_ms": float}` | `HubStateStore.refresh` |
| `EVENT_REFRESH_FAILED` | `"REFRESH_FAILED"` | `{"key": str, "error": str, "seq": int}` | `HermesRefreshScheduler._execute_task` |

---

## 6. Closed Gaps & Audit Status

| Gap ID | Description | Status | Implementation Details / Commit |
|---|---|---|---|
| **Gap 1 & 2** | Antigravity Claude vs Gemini bucket isolation & truthful 429 reset parsing | **Closed** | Multi-bucket model-family isolation in `quota_collector.py` with exact reset timestamps parsed on runtime 429 events (`2035c14`). |
| **Gap 3** | Public `seq` in `HubSnapshot` | **Closed** | `HubSnapshot.seq` exposed to UI; matches accepted refresh token (`2035c14`). |
| **Gap 5** | Stale state policy (`is_stale`) | **Closed** | Explicit policy: `is_stale=True` for uninitialized bootstrap snapshots or when age exceeds 300 seconds (`state_store.py`). |
| **Gap 6** | Plan provenance for `PlanBadge` | **Closed** | `ProfileViewModel.plan_source` added (`"provider_api"`, `"jwt_claim"`, `"provider_auth"`, `"inferred"`, `"unknown"`). UI displays badge only when trustworthy (`2035c14`). |
| **Gap 7** | `AgentViewModel` active session and quota | **Closed** | `session_id`, `active_quota_status`, and `active_quota_label` added (`2035c14`). |
| **Gap 8** | `PipelineNode` identity, quota, and failover reason | **Closed** | `account_identity`, `quota_status`, and real `failover_reason` added (`2035c14`). |
| **Gap 9** | Canonical publishers for all declared events | **Closed** | Every declared event constant has a dedicated, verified publisher in `state_store.py` / `router_engine.py`. Dead event constants removed (`2035c14`). |
| **Gap 10** | Scheduler async quota race | **Closed** | Scheduler triggers complete quota collection before invoking snapshot rebuild (`2035c14`). |
| **Gap 11** | Stale response protection verification | **Closed** | `seq` recorded only on completion; late responses strictly dropped with test proof (`2035c14`). |
| **Gap 12** | Empirical Call Telemetry & Metrics | **Closed (Self-Measured)** | `TelemetryService` captures real call latency, exact token usage reported in provider `usage`, failover events, and USD cost (when user pricing is defined). All metrics carry `source: "own_measurement"`. When no calls exist in the query window, values are `None` (`has_data=False`), never fake zeros (`antigravity/telemetry`). |
| **Gap 13** | Host Hardware Indicators (`psutil`) | **Closed (Self-Measured)** | `HostMetricsService` captures real host CPU (%), RAM (MB/%), Disk (GB/%), and network I/O with `source: "host_measurement"` (`antigravity/dashboard-data`). |

---

## 7. Active Limitations & Backend Constraints

The following constraints are active in the backend and must be strictly respected by the UI:

| Gap ID | Limitation | Constraint & UI Requirement |
|---|---|---|
| **Gap 4** | Shallow Immutability of Snapshot | `HubSnapshot` is defined with `dataclass(frozen=True)` which prevents attribute reassignments. However, contained lists and dictionaries remain standard mutable Python collections. **UI Constraint:** The UI must treat `HubSnapshot` and all nested view models as strictly read-only and must never mutate any collection or object in place. |
| **Gap 14** | External Provider Server Internals & SLA | The backend cannot measure external provider server-side RPS, external datacenter SLA uptime percentages, task priority queue subsystems, or scheduled maintenance windows (these concepts do not exist in Hermes Hub). **UI Constraint:** The UI must display `Н/Д` (Нет данных) or omit these cards. The UI must never generate fictional numbers or render mock graphs. |

---

## 8. Telemetry, Host Metrics, and Active Calls Contract

The backend exposes real empirical metrics via `TelemetryService.get().get_breakdown(...)`, `HostMetricsService.collect()`, and `HubSnapshot.metrics`:

### 8.1 Call Telemetry & Routing Distribution (`source: "own_measurement"`)

Accessible at `HubSnapshot.metrics["telemetry"]`:
- `global`: Overall `TelemetryAggregates` dictionary across all calls in the window (default 24h).
- `by_provider`: `{provider_id: TelemetryAggregates}` including `call_share` (e.g. `0.45`, `0.35`, `0.20`), median latency `latency_p50_ms`, and `total_calls`.
- `by_role`: `{role_id: TelemetryAggregates}` with `total_calls`, `latency_p50_ms`, and `total_tokens`.

| Field | Type | Provenance | Description / Absence Behavior |
|---|---|---|---|
| `source` | `str` | `"own_measurement"` | Identifies measurements taken by Hermes Hub router itself. |
| `has_data` | `bool` | Empirical | `True` if at least 1 router call occurred in the window; `False` if no calls recorded. |
| `total_calls` | `int` | Empirical | Total number of invocation attempts in the window. |
| `successful_calls` | `int` | Empirical | Count of successful invocations (including successful failovers). |
| `failed_calls` | `int` | Empirical | Count of terminal failures. |
| `call_share` | `Optional[float]` | Computed | Ratio of filtered calls to total window calls (`0.0` to `1.0`), or `None` if no calls in window. |
| `error_rate` | `Optional[float]` | Computed | Ratio of failed calls to total calls (`0.0` to `1.0`), or `None` if `has_data=False`. |
| `latency_p50_ms` | `Optional[float]` | Empirical | Median invocation latency in milliseconds, or `None` if `has_data=False`. |
| `latency_p95_ms` | `Optional[float]` | Empirical | 95th percentile invocation latency in milliseconds, or `None` if `has_data=False`. |
| `latency_max_ms` | `Optional[float]` | Empirical | Maximum invocation latency in milliseconds, or `None` if `has_data=False`. |
| `total_prompt_tokens` | `Optional[int]` | Provider `usage` | Sum of prompt tokens reported by providers, or `None` if no `usage` returned. |
| `total_completion_tokens` | `Optional[int]` | Provider `usage` | Sum of completion tokens reported by providers, or `None` if no `usage` returned. |
| `total_tokens` | `Optional[int]` | Provider `usage` | Sum of all tokens reported by providers, or `None` if no `usage` returned. |
| `total_cost_usd` | `Optional[float]` | User Pricing | Computed USD cost based on user-configured `pricing` in `router_profiles.yaml`, or `None` if no pricing configured. |
| `failovers_count` | `int` | Empirical | Number of failover switches from initial profile. |
| `failover_reasons` | `Dict[str, int]` | Empirical | Histogram of failover triggers (`"quota_exhausted"`, `"rate_limited"`, `"auth_required"`, etc.). |

### 8.2 Host System Metrics (`source: "host_measurement"`)

Accessible at `HubSnapshot.metrics["host"]`:

| Field | Type | Provenance | Description / Absence Behavior |
|---|---|---|---|
| `source` | `str` | `"host_measurement"` | Measured directly on the local machine via `psutil`. |
| `has_data` | `bool` | Empirical | `True` if `psutil` data is available; `False` if unavailable or on error. |
| `cpu_percent` | `Optional[float]` | `psutil` | Host CPU utilization percentage (`0.0` to `100.0`), or `None` if unavailable. |
| `memory_percent` | `Optional[float]` | `psutil` | Host RAM utilization percentage (`0.0` to `100.0`), or `None` if unavailable. |
| `memory_used_mb` | `Optional[float]` | `psutil` | Used physical memory in megabytes. |
| `memory_total_mb` | `Optional[float]` | `psutil` | Total physical memory in megabytes. |
| `disk_percent` | `Optional[float]` | `psutil` | Root disk partition utilization percentage (`0.0` to `100.0`), or `None` if unavailable. |
| `disk_used_gb` | `Optional[float]` | `psutil` | Used disk storage in gigabytes. |
| `disk_total_gb` | `Optional[float]` | `psutil` | Total disk storage in gigabytes. |
| `net_speed_mbps` | `Optional[float]` | `psutil` | Live total network throughput in Megabits per second (Mbps) computed across sampling intervals, or `None` on initial sample. |
| `net_sent_mbps` | `Optional[float]` | `psutil` | Live outbound network throughput in Megabits per second (Mbps). |
| `net_recv_mbps` | `Optional[float]` | `psutil` | Live inbound network throughput in Megabits per second (Mbps). |
| `net_bytes_sent` | `Optional[int]` | `psutil` | Cumulative bytes sent since host boot (raw counter). |
| `net_bytes_recv` | `Optional[int]` | `psutil` | Cumulative bytes received since host boot (raw counter). |

> **Measurement Note (CPU Warm-up):** The first CPU measurement is pre-warmed during service initialization to prevent cold-start `0.0%` artifacts. Subsequent measurements read the differential counters non-blockingly.

### 8.3 Active Calls Telemetry (`source: "own_measurement"`)

- `HubSnapshot.metrics["active_calls_total"]`: `int` (Total ongoing concurrency leases managed across all profiles by `RouterEngine`).
- `HubSnapshot.metrics["active_calls_by_profile"]`: `Dict[str, int]` (Active concurrency leases per profile ID).
- `ProfileViewModel.active_leases`: `int` (Current number of active leases for this specific profile).

---

## 9. Configuration Preservation Status

| Component | Status | Behavior & Details |
|---|---|---|
| **Header Comments & Structure** | **Supported** | All leading YAML comments, document banners, and blank lines before the first dictionary key (`existing_comments`) are preserved across file writes. |
| **Inline Section Annotations** | **Partially Supported** | Inline dictionary comments (such as comments inside `profiles`, `roles`, or `pricing`) are normalized during canonical YAML serialization (`safe_dump`). |

## 10. Граница между учётными системами Hub и Hermes (System Boundaries)

Hub и Hermes используют разные множества профилей и настроек. Чтобы интерфейс корректно отображал происходящее и не вводил пользователя в заблуждение, важно понимать границу между ними.

### 10.1 Что Hub получает от Hermes на каждом вызове
При вызове antigravity_llm_execution (через middleware) Hub фактически получает от Hermes только следующие данные:
- 	ask_id
- 	urn_id
- api_request_id
- session_id
- platform
- model
- provider
- ase_url
- api_mode
- api_call_count
- 
equest (payload: список сообщений, temperature и т.д.)

**Явно:** роли агента среди передаваемых данных нет.

### 10.2 Чего Hub не видит
Hub не имеет доступа к внутреннему контексту Hermes. В частности, Hub не видит:
- Профиль Hermes, которым выполняется текущий вызов (например, agy-05, worker-fast, deepseek и др.).
- Настройки конфигурации задач (delegate_task, max_concurrent_children и т.д.).
- Состав и иерархию субагентов Hermes.

### 10.3 Чем Hub управляет
Hub является независимой системой и полностью управляет:
- Собственными профилями (например, ag-w1, ag-orch-fallback, codex-orch, opengo-*, claude-*, grok-*).
- Цепочками отказоустойчивости (failover), привязанными к его собственным профилям.
- Квотами и авторизацией своих аккаунтов.

### 10.4 Чем Hub не управляет
Hub **не управляет ничем** из перечисленного в пункте 10.2. Он не может изменять состав агентов Hermes, перенастраивать профили Hermes или управлять делегированием задач.

---

## 11. Варианты связывания профилей Hub и Hermes

Поскольку один и тот же аккаунт пользователя может существовать в двух системах под разными именами (например, agy-05 в Hermes и ag-w2 в Hub), существуют следующие варианты их связывания. **Внимание:** ни один из вариантов не должен реализовываться без явного решения владельца продукта.

| Вариант | Что становится возможным | Что ломается / Риски | Объем работы |
|---|---|---|---|
| **1. Сопоставление по идентичности аккаунта (email)** | Автоматическое связывание большинства профилей без ручной настройки. | Профили без email (например, worker-fast, deepseek, API-ключи OpenCode) не могут быть сопоставлены. Надежность зависит от гарантий Hermes по предоставлению идентичности. | ~3–4 дня. Требует извлечения identity на стороне Hermes и передачи в Hub. |
| **2. Чтение профилей Hermes (Single Source of Truth)** | Единый источник истины: Hub перестает вести свой список профилей и полностью отражает конфигурацию Hermes. | Теряются сущности, специфичные для Hub: цепочки отказоустойчивости (failover chains), распределение ролей Hub. Квоты сложнее привязывать к профилям. | ~8–12 дней. Требует глубокого рефакторинга конфигурации и движка роутинга Hub. |
| **3. Явная таблица соответствия (Profile Mapping Table)** | Полный контроль и предсказуемость. Владелец может вручную связать любой профиль Hermes (например, agy-05) с профилем Hub (ag-w2). | Требует ручной настройки от пользователя в UI Hub. | ~4–5 дней. Требует добавления конфигурации hermes_profile_map в 
outer_profiles.yaml и поддержки в UI. |

**Рекомендация:**
Наиболее безопасным и предсказуемым является **Вариант 3 (Явная таблица соответствия)**. Он сохраняет независимость систем (сохраняются цепочки отказоустойчивости Hub) и позволяет обрабатывать профили без email. Вариант 1 можно добавить позже как механизм автозаполнения для Варианта 3, чтобы упростить ручную настройку.
