# Hermes Hub — Multi-Provider Router Engine

## 1. Overview
The Multi-Provider Router routes AI task requests from Hermes Agent to the best available provider and profile based on role policies, live health status, quota cooldowns, and session affinity.

## 2. Supported Providers
1. **Google Antigravity**:
   - OAuth 2.0 PKCE authentication with per-profile sandbox directory isolation (`%LOCALAPPDATA%\hermes\agy_profiles\<id>`).
   - Models: `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-thinking`.
2. **OpenAI Codex**:
   - Direct API key authentication with per-model token bucket quota tracking.
   - Models: `gpt-5.3-codex`, `gpt-5.1-codex-mini`.
3. **OpenCode Go**:
   - API key authentication for rapid code generation.
   - Models: `opencode-go-3`.
4. **DeepSeek (Roadmap P1)**:
   - Responses API & Chat completions adapter.
   - Models: `deepseek-chat`, `deepseek-reasoner`.

## 3. Logical Roles & Routing Chains
- **orchestrator**: Primary high-capacity model with reasoning capabilities.
- **coder**: Code generation and refactoring engine.
- **reviewer**: Read-only fail-closed code reviewer.
- **researcher**: Web and codebase search specialist.
- **tester**: Deterministic test runner.
- **general**: Fallback and conversational agent.

## 4. Health & Quota Lifecycle
- **Strict Status Priority Resolver**:
  1. Disabled -> `STATUS_DISABLED` ("Отключён")
  2. No credentials -> `STATUS_NOT_CONFIGURED` ("Аккаунт не добавлен") — never `QUOTA_EXHAUSTED` or `HEALTHY`.
  3. Auth error -> `STATUS_AUTH_EXPIRED` ("Требуется повторная авторизация")
  4. Active Cooldown / Quota -> `STATUS_QUOTA_EXHAUSTED` ("Квота исчерпана")
  5. Rate limit -> `STATUS_RATE_LIMITED` ("Лимит запросов")
  6. Probe error -> `STATUS_UNHEALTHY` ("Ошибка")
  7. Live healthy -> `STATUS_HEALTHY` ("Работает")
