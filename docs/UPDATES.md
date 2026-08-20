# Hermes Hub — Auto-Update & Integrity Architecture

## 1. Overview
Hermes Hub includes an autonomous, fail-safe update engine designed to safely upgrade the application while strictly protecting user credentials, configurations, and active sessions.

## 2. Security Invariants
- **Cryptographic Verification**: Every downloaded package is verified against a SHA-256 digest before any files are unpacked.
- **Hermetic Staging**: Update packages are downloaded to `%LOCALAPPDATA%\hermes\updates\staging` and never overwrite active executing binaries directly.
- **Zero Secret Ingestion**: Updates NEVER overwrite user OAuth tokens, API keys, `router_profiles.yaml`, `hub_settings.json`, or `router_state.json`.
- **Zero Hardcoded Developer PATs**: The updater utilizes versioned release manifests and signed release asset endpoints without storing privileged credentials in the client application.

## 3. Update Manifest Schema (`update_manifest.json`)
```json
{
  "version": "0.1.2",
  "channel": "stable",
  "minimum_hermes_version": "0.20.0",
  "published_at": "2026-08-20T17:00:00Z",
  "package_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/download/v0.1.2/hermes-hub-0.1.2.zip",
  "sha256": "4b2e8d9a1f3c5e7b8a9d0c2e4f6a8b0c2d4e6f8a0b2c4d6e8f0a2b4c6d8e0f2a",
  "release_notes_url": "https://github.com/ochenstarik-ui/hermes-hub/releases/tag/v0.1.2",
  "changelog": "Stabilization fixes, P0 blocker resolutions, and performance improvements."
}
```

## 4. Rollback & Fail-Safe Protocol
1. **Pre-Update Backup**: The updater creates a complete snapshot of `src/`, `assets/`, `config/`, and `launcher/` in `%LOCALAPPDATA%\hermes\updates\backup_prev`.
2. **Post-Update Syntax & Import Verification**:
   - `py_compile` is executed across all unpacked `.py` modules.
   - An isolated Python sub-process verifies import integrity (`from antigravity_provider.version import __version__`).
3. **Automatic Rollback**: If syntax errors, import failures, or process crashes are detected, the updater immediately restores the previous working snapshot from `backup_prev` and notifies the user:
   > *"Обновление не удалось. Выполнен автоматический откат к предыдущей версии."*

## 5. Verification Suite
The update and rollback mechanisms are covered by automated unit and integration tests in `tests/test_updater.py`:
- `test_version_comparison`: Validates semantic version precedence.
- `test_sha256_verification`: Validates cryptographic checksum calculations.
- `test_bad_hash_rejection`: Validates immediate rejection of corrupted/tampered payloads.
- `test_updater_rollback_on_failure`: Validates automatic snapshot rollback on broken syntax.
- `test_dogfood_update_e2e`: Simulates live upgrade from `0.1.1` to `0.1.2`.
