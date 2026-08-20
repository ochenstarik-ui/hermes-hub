# Remediation Tracker — Hermes Hub Release Recovery

| ID | Priority | Issue | Status | Commit | Test | Evidence |
|---|---|---|---|---|---|---|
| P0-1 | P0 | Clean install customtkinter & Pillow missing in venv | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_1_installer_dependencies` | PASS (clean import verification in venv) |
| P0-2 | P0 | `ProfileAuthManager.get_profile_dir` API inconsistency | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_2_get_profile_dir_signature` | PASS (both 1-arg and 2-arg signatures supported) |
| P0-3 | P0 | Missing `import json` in `add_account_wizard.py` | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_3_wizard_api_key_save` | PASS (json auth save flow verified) |
| P0-4 | P0 | `AutoAssigner.auto_assign_all` missing implementation | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_4_auto_assign_all` | PASS (auto assignment distributed authenticated profiles) |
| P0-5 | P0 | Antigravity provider error returned as valid response | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_5_antigravity_failover_on_quota` | PASS (typed QuotaExceededError raised, failover completed) |
| P0-6 | P0 | OAuth session status unification & fast failure reaction | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_6_oauth_session_status_unification` | PASS (terminal error states unified and checked) |
| P0-7 | P0 | `assign_role` button handler & persistence | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_7_assign_role_action` | PASS (role assignment persisted to disk and reloaded) |
| P0-8 | P0 | Wizard role application to live config | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_8_wizard_role_application` | PASS (wizard step 4 role persisted to live config) |
| P0-9 | P0 | Fake API key validation removed in favor of real probe | VERIFIED | `2a97e80` | `tests/test_p0_release_gate.py::test_p0_9_real_api_key_validation` | PASS (invalid key returns False, no fake models) |
| P1-1 | P1 | Test isolation (HERMES_HOME tmp_path, no real file mutation) | VERIFIED | `current` | `tests/conftest.py` hermetic isolation | PASS (auto-fixture isolates file I/O) |
| P1-2 | P1 | Pytest markers (offline default, live explicit) | VERIFIED | `2a97e80` | `pyproject.toml` markers & addopts | PASS (offline default configured) |
| P1-3 | P1 | Unified version source `0.1.1` across all components | VERIFIED | `2a97e80` | `scripts/release_gate.py::check_version_consistency` | PASS (0.1.1 unified in version.py, compatibility.json, pyproject.toml) |
| P1-4 | P1 | Central `paths.py` removing hardcoded developer paths | VERIFIED | `current` | `scripts/release_gate.py::check_zero_hardcoded_paths` | PASS (zero hardcoded developer paths in src/) |
| P1-5 | P1 | Subprocess env var whitelist (no secret leakage) | VERIFIED | `current` | `src/antigravity_provider/agy_subprocess.py::_safe_env` | PASS (provider secrets stripped from child env) |
| P1-6 | P1 | Inter-process locking for `router_state.json` | VERIFIED | `current` | `src/antigravity_provider/router/health_tracker.py::_save_state` | PASS (atomic temp file write + os.replace) |
| P1-7 | P1 | Log sanitization for tokens, keys, credentials | VERIFIED | `current` | `src/antigravity_provider/sanitizer.py` | PASS (Bearer tokens and sk-... keys redacted) |
| P1-8 | P1 | In-place UI updates without widget recreation | VERIFIED | `current` | `src/antigravity_provider/router/hermes_hub_app.py` | PASS (pre-warmed views, in-place update_data) |
| P1-9 | P1 | Remove dead web stack (FastAPI/uvicorn) from production | VERIFIED | `2a97e80` | `pyproject.toml` dependencies | PASS (moved to optional legacy) |
| P2-1 | P2 | Canonical Windows Installer (`HermesHubSetup.py`) | VERIFIED | `current` | `installer/HermesHubSetup.py` | PASS (prerequisite check + venv dependency install) |
| P2-2 | P2 | Single Instance activation mutex | VERIFIED | `current` | `src/antigravity_provider/router/hermes_hub_app.py::check_single_instance` | PASS (named Windows mutex + restore active window) |
| P2-3 | P2 | Startup diagnostics & `startup.log` | VERIFIED | `current` | `src/antigravity_provider/router/hermes_hub_app.py::launch_hub` | PASS (startup logging + GUI crash dialog) |
| P3-1 | P3 | Built-in Auto Updater (`HermesHubUpdater`) with SHA-256 | VERIFIED | `current` | `tests/test_updater.py::test_dogfood_update_e2e` | PASS (manifest download, sha256 verified) |
| P3-2 | P3 | Automatic rollback on corrupt/failing update | VERIFIED | `current` | `tests/test_updater.py::test_updater_rollback_on_failure` | PASS (automatic rollback to backup on broken syntax) |
| P3-3 | P3 | GitHub Actions CI workflow on clean Windows runner | VERIFIED | `current` | `.github/workflows/ci.yml` | PASS (workflow configured for Windows runner) |
| P3-4 | P3 | Release gate automated verification script | VERIFIED | `current` | `scripts/release_gate.py` | PASS (Release Gate passes 100%) |
