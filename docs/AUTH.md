# Hermes Hub — Authentication & Profile Security

## 1. Profile Storage & Isolation
All user authentication records, tokens, and OAuth credentials are stored in user-isolated directories under `%LOCALAPPDATA%\hermes\`:
- Antigravity profiles: `%LOCALAPPDATA%\hermes\agy_profiles\<profile_id>\auth.json`
- Codex profiles: `%LOCALAPPDATA%\hermes\codex_profiles\<profile_id>\auth.json`
- OpenCode Go profiles: `%LOCALAPPDATA%\hermes\opengo_profiles\<profile_id>\auth.json`

## 2. Security Invariants
- **Zero Credentials in Git**: `.gitignore` strictly prevents all `auth.json`, tokens, keys, and private data from entering version control.
- **Strict Masking**: Emails and account identifiers are masked in presentation models (`a***@gmail.com`, `sk-...1234`).
- **Safe Test Actions**: The "⚡ Тест" action checks existing credentials locally; it never opens browser windows or triggers unauthenticated OAuth flows.
- **MAIN Account vs Primary Orchestrator Separation**:
  - `MAIN Account`: The default account used for Hermes Agent CLI operations (`ProfileAuthManager.set_main_profile`).
  - `Primary Orchestrator`: The lead profile assigned position 0 in the orchestrator routing chain (`AutoAssigner.set_primary_orchestrator`).
