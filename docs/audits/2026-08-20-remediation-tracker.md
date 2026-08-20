# Remediation Tracker — Hermes Hub Release Recovery

| ID | Priority | Issue | Status | Commit | Test | Evidence |
|---|---|---|---|---|---|---|
| P0-1 | P0 | Clean install customtkinter & Pillow missing in venv | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_1_installer_dependencies` | PASS (clean import verification) |
| P0-2 | P0 | `ProfileAuthManager.get_profile_dir` API inconsistency | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_2_get_profile_dir_signature` | PASS (both 1-arg and 2-arg signatures supported) |
| P0-3 | P0 | Missing `import json` in `add_account_wizard.py` | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_3_wizard_api_key_save` | PASS (json auth save flow verified) |
| P0-4 | P0 | `AutoAssigner.auto_assign_all` missing implementation | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_4_auto_assign_all` | PASS (auto assignment distributed authenticated profiles) |
| P0-5 | P0 | Antigravity provider error returned as valid response | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_5_antigravity_failover_on_quota` | PASS (typed QuotaExceededError raised, failover to fallback completed) |
| P0-6 | P0 | OAuth session status unification & fast failure reaction | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_6_oauth_session_status_unification` | PASS (terminal error states unified and checked) |
| P0-7 | P0 | `assign_role` button handler & persistence | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_7_assign_role_action` | PASS (role assignment persisted to disk and reloaded) |
| P0-8 | P0 | Wizard role application to live config | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_8_wizard_role_application` | PASS (wizard step 4 role persisted to live config) |
| P0-9 | P0 | Fake API key validation removed in favor of real probe | VERIFIED | pending | `tests/test_p0_release_gate.py::test_p0_9_real_api_key_validation` | PASS (invalid key returns False, no fake models) |
| P1-1 | P1 | Test isolation (HERMES_HOME tmp_path, no real file mutation) | IN_PROGRESS | pending | `tests/conftest.py` hermetic isolation | pending |
| P1-2 | P1 | Pytest markers (offline default, live explicit) | VERIFIED | pending | `pyproject.toml` markers & addopts | PASS (offline default configured) |
| P1-3 | P1 | Unified version source `0.1.1` across all components | VERIFIED | pending | `src/antigravity_provider/version.py` | PASS (0.1.1 unified in version.py, compatibility.json, pyproject.toml) |
| P1-4 | P1 | Central `paths.py` removing hardcoded developer paths | VERIFIED | pending | `src/antigravity_provider/paths.py` | PASS (central paths with HERMES_HOME support) |
| P1-5 | P1 | Subprocess env var whitelist (no secret leakage) | IN_PROGRESS | pending | `tests/test_subprocess_security.py` | pending |
| P1-6 | P1 | Inter-process locking for `router_state.json` | IN_PROGRESS | pending | `tests/test_state_concurrency.py` | pending |
| P1-7 | P1 | Log sanitization for tokens, keys, credentials | IN_PROGRESS | pending | `tests/test_log_sanitization.py` | pending |
| P1-8 | P1 | In-place UI updates without widget recreation | IN_PROGRESS | pending | UI benchmark | pending |
| P1-9 | P1 | Remove dead web stack (FastAPI/uvicorn) from production | VERIFIED | pending | `pyproject.toml` dependencies | PASS (moved to optional legacy) |
| P2-1 | P2 | Canonical Windows Installer (`HermesHubSetup.exe`) | IN_PROGRESS | pending | `tests/test_installer.py` | pending |
| P2-2 | P2 | Single Instance activation mutex | IN_PROGRESS | pending | `tests/test_single_instance.py` | pending |
| P2-3 | P2 | Startup diagnostics & `startup.log` | IN_PROGRESS | pending | `tests/test_startup_diagnostics.py` | pending |
| P3-1 | P3 | Built-in Auto Updater (`HermesHubUpdater`) with SHA-256 | IN_PROGRESS | pending | `tests/test_updater.py` | pending |
| P3-2 | P3 | Automatic rollback on corrupt/failing update | IN_PROGRESS | pending | `tests/test_updater_rollback.py` | pending |
| P3-3 | P3 | GitHub Actions CI workflow on clean Windows runner | IN_PROGRESS | pending | `.github/workflows/ci.yml` | pending |
| P3-4 | P3 | Release gate automated verification script | IN_PROGRESS | pending | `scripts/release_gate.py` | pending |
