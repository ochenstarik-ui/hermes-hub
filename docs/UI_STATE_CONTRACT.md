# Hermes Hub UI state contract

- Contract version: **1.0**
- Published against: **`f171a8069d97aef5d3a45f838daed63abf2e69c1`**
- Contract owner: `antigravity/state-layer`
- Consumer: `codex/ui-redesign`

This document describes the backend state that the native UI may render. It is
descriptive of the code at the published commit, not of intended future data.
Fields marked **real** are backed by persisted configuration, authentication
metadata, runtime health or provider responses. Fields marked **derived** are
computed from real fields. Fields marked **estimated** or **placeholder** must
be labelled as such or hidden by the UI.

## 1. Snapshot boundary

### `HubSnapshot`

Defined in `router/state_store.py` as a frozen dataclass.

| Field | Type | Reality and meaning |
|---|---|---|
| `generation` | `int` | **Real local sequence.** Monotonically increases for every accepted rebuild within one process. Starts at 1; an empty bootstrap snapshot uses 0. |
| `timestamp` | `float` | **Real local time** (`time.time()`) when the snapshot was built. |
| `profiles_by_provider` | `dict[str, list[ProfileViewModel]]` | **Derived** normalized profiles grouped by provider. |
| `all_profiles` | `dict[str, ProfileViewModel]` | **Derived** map keyed by `profile_id`. Profile IDs are assumed globally unique by this map. |
| `readiness` | `SystemReadiness` | **Derived** readiness summary. |
| `agents` | `list[AgentViewModel]` | **Derived** current role assignments. |
| `providers` | `list[ProviderSummary]` | **Derived** provider summaries. |
| `routing` | `dict[str, RolePipeline]` | **Derived** routing pipelines keyed by role ID. |
| `quotas` | `dict[str, QuotaSnapshot]` | Mixed. Keyed by `profile_id`; see provider truth matrix below. |
| `metrics` | `dict[str, Any]` | **Real local diagnostics only:** generation, build duration, profile counts and refresh counters. These are not provider throughput/error metrics. |
| `is_stale` | `bool` | `True` only for the empty bootstrap snapshot at this version. No age-based stale policy is implemented yet. |

Consistency guarantees:

- The store publishes one snapshot reference after building it under an
  `RLock`; readers never observe the assignment half-complete.
- `frozen=True` prevents replacing dataclass attributes, but nested dicts,
  lists and contained models remain mutable. The snapshot is therefore
  shallowly immutable, not deeply immutable.
- `generation` is the UI comparison key. A public `seq` field does **not**
  exist in version 1.0.
- Scheduler request `seq` is internal to `HubStateStore`; stale requests are
  rejected when `seq < _latest_applied_seq`. The accepted `seq` is not exposed
  to the UI.
- `get_snapshot()` returns the cached snapshot; on first use it performs a
  non-forced state build.

## 2. Account and health models

### `ProfileViewModel`

| Field | Type | Optional | Reality and meaning |
|---|---|---:|---|
| `profile_id` | `str` | no | **Real configuration slot/profile ID.** |
| `display_name` | `str` | no | **Real configured name** when present; otherwise a local fallback. |
| `account_identity` | `str` | no | Best available identifier: email → display name → provider account ID → profile ID. Real when auth metadata/JWT contains identity; fallback otherwise. |
| `provider` | `str` | no | **Real normalized provider ID.** |
| `provider_display_name` | `str` | no | **Derived localized/display label.** |
| `assigned_roles` | `list[str]` | no | **Derived from router config.** Includes primary/fallback annotations. |
| `primary_role` | `str` | yes | **Derived/configured.** May be absent. |
| `is_main_account` | `bool` | no | **Real local profile preference.** |
| `is_main_orchestrator` | `bool` | no | **Derived from orchestrator chain.** |
| `auth_state` | `str` | no | Normalized auth state; meanings below. |
| `health_state` | `str` | no | Normalized health state; meanings below. |
| `health_label_ru` | `str` | no | **Derived presentation label.** |
| `model_states` | `dict[str, ModelFamilyHealth]` | no | **Derived from local health tracker/runtime observations.** Empty if unobserved. |
| `cooldown_remaining_sec` | `int` | no | **Derived local runtime state.** Zero when unknown/not cooling down. |
| `last_checked_at` | `str` | yes | **Real local check time string**, not a provider timestamp. |
| `enabled` | `bool` | no | **Real config state.** |
| `is_cold_spare` | `bool` | no | **Derived/configured.** |
| `is_empty_slot` | `bool` | no | **Derived** placeholder slot with no configured auth. |
| `email` | `str` | logically yes | Real only if available from saved auth/JWT; empty string otherwise. |
| `plan` | `str` | logically yes | Display text. At version 1.0 several providers receive inferred defaults; UI must show only if `plan_code != UNKNOWN` **and** source is made trustworthy in a later contract revision. |
| `plan_code` | `str` | no | May be inferred (`PRO`, `PLUS`, `MAX`, etc.); not uniformly provider-confirmed. |
| `quota_snapshot` | `QuotaSnapshot` | yes | See quota matrix. |
| `preferred_models` | `list[str]` | no | **Real config/model-discovery values** when present. |

`auth_state` values:

| Value | Meaning |
|---|---|
| `AUTHENTICATED` | Saved authentication material passed the local presence/shape checks. It does not guarantee a fresh remote token check. |
| `AUTH_REQUIRED` | No usable saved authentication material is available. |
| `AUTH_EXPIRED` | Backend identified expired authentication. Not all providers can distinguish this from `AUTH_REQUIRED`. |

`health_state` values:

| Value | Meaning |
|---|---|
| `healthy` | Locally considered available. |
| `quota_low` | Local/provider quota evidence indicates a warning threshold. |
| `quota_exhausted` | Runtime/provider evidence indicates exhausted quota. |
| `cooldown` | Local health tracker has an active cooldown. |
| `rate_limited` | Runtime observed a rate limit. |
| `not_configured` | Empty slot/no account. |
| `auth_required` | Authentication missing. |
| `auth_expired` | Authentication expired when distinguishable. |
| `disabled` | Disabled in configuration. |
| `cold_spare` | Configured reserve not currently active. |
| `unhealthy` | Failure not represented by a more specific state. |
| `not_tested` | No usable health observation exists. |

### `ModelFamilyHealth`

`family`, `display_name`, `status`, `status_label_ru` are required derived
fields. `cooldown_remaining_sec` defaults to 0. `reset_at` and `reason` are
optional and exist only when the local health tracker recorded them.

## 3. Identity and plan provenance

`AccountIdentity` carries provider/profile ID, optional email, display name,
provider account ID, organization, `SubscriptionPlan`, auth method,
authenticated flag and local verification time.

Identity preference is contractual:

1. email;
2. display name/username;
3. provider account ID;
4. profile ID fallback.

The backend never exposes access tokens, refresh tokens, authorization codes
or raw API keys through these ViewModels.

`SubscriptionPlan.source` may be `provider_api`, `provider_auth`, `jwt_claim`,
`inferred` or `unknown`. At version 1.0 plan detection in
`AccountQuotaService._resolve_identity()` assigns inferred provider defaults
when explicit metadata is missing. Therefore the UI must hide a plan badge
unless a later contract revision supplies trustworthy plan provenance alongside
`ProfileViewModel`.

## 4. Quota models

### `QuotaSnapshot`

| Field | Type | Reality and meaning |
|---|---|---|
| `account_id` | `str` | Real local profile/account key. |
| `provider` | `str` | Real normalized provider ID. |
| `buckets` | `list[QuotaBucket]` | Separate pools; never combine them into one percent. |
| `fetched_at` | timezone-aware `datetime` | Real local collection time. |
| `stale_after_seconds` | `int` | Local cache TTL, default 300 seconds. |
| `source` | `str` | Provenance. `baseline`, `estimated`, `unconfigured`, `local_heuristic` imply `is_estimated=True`. |
| `unavailable_reason` | `Optional[str]` | Human-readable reason when data cannot be collected. |
| `is_estimated` | property | Derived solely from `source`. |

### `QuotaBucket`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Stable bucket key. |
| `display_name` | `str` | User-facing label. This is the requested logical `label`. |
| `model_family` | `Optional[str]` | Family/pool selector when known. |
| `used_percent` | `Optional[float]` | 0–100; reconciled from remaining percent when one side exists. |
| `remaining_percent` | `Optional[float]` | 0–100; reconciled from used percent when one side exists. |
| `used_absolute` | `Optional[int]` | Requested logical `used`. |
| `remaining_absolute` | `Optional[int]` | Absolute remaining quantity. |
| `limit_absolute` | `Optional[int]` | Requested logical `limit`. |
| `reset_at` | `Optional[datetime]` | Reset time if measured or estimated. |
| `reset_in_seconds` | `Optional[int]` | Relative reset duration if known. |
| `period` | `Optional[str]` | `5h`, `7d`, `30d`, `sliding`, or provider-specific. |
| `status` | `str` | `healthy`, `warning`, `exhausted`, `unknown`; derived from remaining values where available. |

Requested fields `unit` and `scope` do not exist in version 1.0. The closest
available fields are absolute-value semantics implied by the provider and
`model_family`/`period`. The UI must not invent units.

### Provider truth matrix at contract version 1.0

| Provider | Buckets emitted | Values | Reset | Source / UI treatment |
|---|---|---|---|---|
| Antigravity | Claude 5h, Claude Weekly, Gemini 5h, Gemini Weekly | Percent/absolute values are absent | Locally projected +5h/+7d | `baseline`; **estimated**, label explicitly. No live provider quota call. |
| OpenAI Codex | Session, Weekly | Values absent | Locally projected +5h/+7d | `baseline`; **estimated**. |
| OpenCode Go | Sliding, Weekly, Monthly | Values absent | Weekly/monthly locally projected; sliding reset absent | `baseline`; **estimated**. |
| Claude | Current session, Current week | Values absent | Locally projected +5h/+7d | `baseline`; **estimated**. |
| Grok | Weekly, GrokChat, GrokBuild, frequent tasks, normal tasks | Usage/remaining absent. Task limits 10/30 are static placeholders. | Mostly absent | `baseline`; **estimated**. |
| Unknown provider | One default bucket | Values and reset absent | absent | `baseline`; **estimated**. |
| Unconfigured account | No buckets | no data | absent | `unconfigured`; show unavailable reason. |

Runtime 429 handling may set one matching bucket to 100% used / 0% remaining
with a locally assumed reset duration. This is real evidence of exhaustion but
the reset time remains estimated.

## 5. Team and routing models

### `AgentViewModel`

Required fields: role ID/name/description, optional assigned profile ID and
display name, provider ID/display name, model, account identity, routing
position, status/status label, active flag and orchestrator flag.
`cooldown_remaining_sec` is derived local runtime state.

Reality notes:

- role/profile chain comes from router configuration;
- the selected model is the first preferred model or the string `default`;
- active selection is the first healthy profile in the chain;
- there is no active-session field and no per-agent quota field in version 1.0.

### `RolePipeline`

Fields: `role_id`, `role_name_ru`, `default_model`, `max_failover`,
`session_affinity`, `active_profile_id`, `nodes`.

Each `PipelineNode` contains profile ID, display name, provider display name,
model, health status/label, active flag and cooldown seconds. Node order is the
configured primary → fallback order. The first healthy node is marked active.

Version 1.0 does not include account identity, quota snapshot/status or a
failover reason in each node. The UI may show the order and health but must not
invent why a switch happened.

### `ProviderSummary`

Contains provider ID/name; total, connected, online, auth-required,
quota-exhausted and cold-spare counts; discovered model names; and a local last
refresh time string. Counts are derived from `ProfileViewModel` objects.

### `SystemReadiness`

Contains state (`healthy`, `limited`, `degraded`, `critical`), localized title
and summary, ready/total counts for roles, connected/total accounts,
ready/total providers, and warning strings. All values are derived from the
current local profile and routing state; they are not remote SLA metrics.

## 6. Event bus contract

Callbacks receive `(event_name: str, payload: Any)`. Delivery is synchronous on
the publishing thread unless the caller uses `publish_to_ui(root, ...)`, which
schedules through `root.after(0, ...)`.

| Event | Payload contract at v1.0 | Emission status |
|---|---|---|
| `ACCOUNT_UPDATED` | `{profile_id, profile, generation}` | Emitted after targeted account delta rebuild when the profile exists. |
| `ACCOUNT_ADDED` | Intended `{provider, profile_id, profile?, generation?}` | Declared only; no canonical publisher yet. |
| `ACCOUNT_REMOVED` | Intended `{provider, profile_id, generation?}` | Declared only. |
| `ACCOUNT_AUTH_CHANGED` | Intended `{provider, profile_id, auth_state, generation?}` | Declared only. |
| `QUOTA_UPDATED` | `{provider, profile_id, quota_snapshot}` | Emitted by `HubStateStore.apply_delta_quota_updated`; generation absent. Collector listeners use a separate callback API. |
| `QUOTA_STALE` | Intended `{provider, profile_id}` | Declared only. |
| `PROVIDER_HEALTH_CHANGED` | Intended provider summary/delta | Declared only. |
| `ROUTING_UPDATED` | Intended `{role_id, pipeline, reason?, generation?}` | Declared and consumed by UI, but no canonical backend publisher. |
| `ROUTING_SLOT_UPDATED` | Intended targeted role/slot delta | Declared only. |
| `AGENT_UPDATED` | Intended `{role_id, agent, generation?}` | Declared only. |
| `SYSTEM_READINESS_CHANGED` | `SystemReadiness` object | Emitted after every accepted full rebuild. |
| `REFRESH_STARTED` | `{key, seq}` | Emitted by scheduler before a task. |
| `REFRESH_COMPLETED` | `{generation, duration_ms}` | Emitted by state store after rebuild. |
| `REFRESH_FAILED` | `{key, error}` | Emitted by scheduler on failure. Error text must already be secret-safe. |

Quota/account events are intended to update one stable UI widget keyed by
`profile_id`; they must not be treated as instructions to reconstruct every
account card.

## 7. Backend gaps

The following cannot be honestly implemented by UI code alone:

1. No provider currently supplies live numeric quota values through
   `AccountQuotaService`; every configured-provider collector returns baseline
   buckets.
2. Antigravity bucket separation exists structurally, but the four values and
   reset times are not measured from provider responses.
3. `HubSnapshot` has no public request `seq`; it exposes only generation.
4. Snapshot immutability is shallow.
5. `is_stale` has no age/source policy beyond the empty bootstrap snapshot.
6. Plan provenance is not carried into `ProfileViewModel`; inferred plans
   cannot be distinguished safely by the UI.
7. `AgentViewModel` lacks active session and quota data.
8. `PipelineNode` lacks account identity, quota state and failover reason.
9. Most targeted event constants are declared but have no canonical publisher.
10. Single/all scheduler triggers start nested asynchronous quota workers and
    may rebuild state before those quota workers finish.
11. Stale-response protection records `seq` before the slow work is complete,
    so the current implementation does not fully prove that a late result can
    never overwrite a newer result.
12. Provider latency, RPS, error percentage, costs and remote SLA are absent.
    The UI must display `Н/Д` or omit those blocks.

Any contract extension must update this document and identify the implementing
commit before UI code relies on the new fields.
