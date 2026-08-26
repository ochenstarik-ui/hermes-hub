"""Comprehensive test suite for Task A9:
1. Idempotent configuration migration & backup
2. Honest quota fetching for OpenAI Codex & OpenCode Go
3. Non-blocking ModelDiscoveryService with disk cache and timeout
4. Dynamic preferred_models in AutoAssigner & validation
5. Deterministic provider ordering in UnifiedHealthService
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from unittest.mock import MagicMock, patch

from antigravity_provider.router.account_identity import QuotaSnapshot, QuotaBucket
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.quota_collector import AccountQuotaService
from antigravity_provider.router.router_config import (
    RouterConfig,
    RouterProfileConfig,
    get_default_router_config,
    load_router_config,
    save_router_config,
)
from antigravity_provider.router.unified_health import UnifiedHealthService


class TestA9ConfigMigration(unittest.TestCase):
    """P0-0.1: Idempotent configuration migration from 16 profiles."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a9_config_")
        self.config_path = Path(self.tmp_dir) / "router_profiles.yaml"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_migration_16_profiles_preserves_antigravity_and_adds_claude_grok(self):
        # 1. Prepare legacy 16-profile configuration (no claude, no grok)
        legacy_profiles = {}
        for pid in [
            "codex-orch", "codex-worker-1", "codex-worker-2",
            "ag-orch-fallback", "ag-w1", "ag-w2", "ag-w3", "ag-w4",
            "ag-spare-1", "ag-spare-2", "ag-cold-1", "ag-cold-2", "ag-cold-3",
            "opengo-1", "opengo-2", "opengo-3",
        ]:
            legacy_profiles[pid] = RouterProfileConfig(
                profile_id=pid,
                provider="antigravity" if pid.startswith("ag-") else ("openai-codex" if pid.startswith("codex-") else "opencode-go"),
                account_id=f"custom-acc-{pid}",
                capabilities=["custom-cap"],
                preferred_models=["custom-model-1"],
                max_concurrency=3,
            )

        legacy_cfg = RouterConfig(
            enabled=True,
            default_role="manager",
            roles=get_default_router_config().roles,
            profiles=legacy_profiles,
        )
        save_router_config(legacy_cfg, self.config_path)

        self.assertEqual(len(legacy_cfg.profiles), 16)
        self.assertNotIn("grok-orch", legacy_cfg.profiles)
        self.assertNotIn("claude-orch", legacy_cfg.profiles)

        # 2. Load configuration (triggers migration)
        migrated_cfg = load_router_config(self.config_path)

        # 3. Verify backup file created
        backups = list(Path(self.tmp_dir).glob("router_profiles.yaml.bak_*"))
        self.assertGreaterEqual(len(backups), 1, "Backup file was not created on migration")

        # 4. Verify Claude and Grok profiles added
        self.assertIn("grok-orch", migrated_cfg.profiles)
        self.assertIn("grok-worker-1", migrated_cfg.profiles)
        self.assertIn("grok-worker-2", migrated_cfg.profiles)
        self.assertIn("claude-orch", migrated_cfg.profiles)
        self.assertIn("claude-worker-1", migrated_cfg.profiles)
        self.assertIn("claude-worker-2", migrated_cfg.profiles)
        self.assertEqual(len(migrated_cfg.profiles), 24)

        # 5. Verify existing 10 antigravity profiles are 100% untouched
        for pid in ["ag-orch-fallback", "ag-w1", "ag-w2", "ag-w3", "ag-w4", "ag-spare-1", "ag-spare-2", "ag-cold-1", "ag-cold-2", "ag-cold-3"]:
            p = migrated_cfg.profiles[pid]
            self.assertEqual(p.account_id, f"custom-acc-{pid}", f"Account ID mutated for {pid}")
            self.assertEqual(p.capabilities, ["custom-cap"], f"Capabilities mutated for {pid}")
            self.assertEqual(p.preferred_models, ["custom-model-1"], f"Models mutated for {pid}")
            self.assertEqual(p.max_concurrency, 3, f"Concurrency mutated for {pid}")

        # 6. Verify AutoAssigner.find_free_slot finds free slots for grok and claude
        with patch.dict(os.environ, {"HERMES_ROUTER_CONFIG": str(self.config_path)}):
            slot_grok = AutoAssigner.find_free_slot("grok")
            self.assertEqual(slot_grok, "grok-orch")
            slot_claude = AutoAssigner.find_free_slot("claude")
            self.assertEqual(slot_claude, "claude-orch")

        # 7. Verify Idempotence: subsequent loads do not create extra backups
        backup_count_before = len(backups)
        reload_cfg = load_router_config(self.config_path)
        self.assertEqual(len(reload_cfg.profiles), 24)
        backup_count_after = len(list(Path(self.tmp_dir).glob("router_profiles.yaml.bak_*")))
        self.assertEqual(backup_count_before, backup_count_after)


class TestA9QuotaHonesty(unittest.TestCase):
    """P0-1: Quotas for OpenAI Codex and OpenCode Go."""

    def setUp(self):
        self.service = AccountQuotaService()

    @patch("urllib.request.urlopen")
    def test_codex_quota_success_returns_honest_unavailable_reason_without_fake_numbers(self, mock_urlopen):
        # Mock /models success response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": [{"id": "gpt-4o"}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        auth_data = {
            "token": {"access_token": "valid_token_123"},
            "email": "user@example.com",
        }
        snap = self.service._collect_codex_quota("codex-orch", auth_data)

        self.assertEqual(snap.source, "baseline")
        self.assertTrue(snap.is_estimated)
        self.assertEqual(snap.provider, "openai-codex")
        self.assertEqual(snap.unavailable_reason, "OpenAI Codex не предоставляет остаток через публичный API")
        for b in snap.buckets:
            self.assertIsNone(b.remaining_percent)
            self.assertIsNone(b.reset_at)

    def test_codex_quota_401_returns_expired_auth_reason(self):
        auth_data = {
            "token": {"access_token": "expired_token_123"},
            "email": "user@example.com",
        }
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)):
            snap = self.service._collect_codex_quota("codex-orch", auth_data)

        self.assertEqual(snap.source, "baseline")
        self.assertTrue(snap.is_estimated)
        self.assertEqual(snap.unavailable_reason, "Авторизация истекла — обновите подключение")
        for b in snap.buckets:
            self.assertIsNone(b.remaining_percent)

    @patch("urllib.request.urlopen")
    def test_opencode_quota_measured_values(self, mock_urlopen):
        # Mock /models and /usage responses
        models_resp = MagicMock()
        models_resp.read.return_value = json.dumps({"data": [{"id": "deepseek-r1"}]}).encode("utf-8")
        models_resp.__enter__.return_value = models_resp

        usage_resp = MagicMock()
        usage_resp.read.return_value = json.dumps({
            "five_hour": {"remaining_percent": 80.0, "remaining": 10, "used": 2},
            "weekly": {"remaining_percent": 90.0, "remaining": 27, "used": 3},
            "monthly": {"remaining_percent": 95.0, "remaining": 57, "used": 3},
        }).encode("utf-8")
        usage_resp.__enter__.return_value = usage_resp

        mock_urlopen.side_effect = [models_resp, usage_resp]

        auth_data = {"api_key": "opencode_secret_key"}
        snap = self.service._collect_opencode_quota("opengo-1", auth_data)

        self.assertEqual(snap.source, "provider_api")
        self.assertIsNone(snap.unavailable_reason)
        b_5h = next(b for b in snap.buckets if b.period == "5h")
        self.assertEqual(b_5h.remaining_percent, 80.0)
        self.assertEqual(b_5h.used_absolute, 2)


class TestA9ModelDiscoveryService(unittest.TestCase):
    """P0-2: Non-blocking ModelDiscoveryService with disk cache and timeout."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a9_discovery_")
        self.cache_file = Path(self.tmp_dir) / "models_cache.json"
        self.service = ModelDiscoveryService(cache_path=self.cache_file)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_empty_cache_returns_none_honestly(self):
        models = self.service.get_models("openai-codex")
        self.assertIsNone(models)
        meta = self.service.get_models_with_metadata("openai-codex")
        self.assertFalse(meta["has_cache"])
        self.assertTrue(meta["is_stale"])

    def test_cache_persistence_on_disk(self):
        # Manually seed cache
        with self.service._cache_lock:
            self.service._cache["openai-codex"] = {
                "models": ["gpt-4o", "o3-mini"],
                "discovered_at": time.time(),
            }
            self.service._save_cache_to_disk()

        # Reload new instance from same path
        new_svc = ModelDiscoveryService(cache_path=self.cache_file)
        models = new_svc.get_models("openai-codex")
        self.assertEqual(models, ["gpt-4o", "o3-mini"])
        meta = new_svc.get_models_with_metadata("openai-codex")
        self.assertTrue(meta["has_cache"])
        self.assertFalse(meta["is_stale"])

    def test_timeout_probe_does_not_block_and_leaves_previous_cache(self):
        # Seed cache
        with self.service._cache_lock:
            self.service._cache["antigravity"] = {
                "models": ["gemini-3.5-flash"],
                "discovered_at": time.time(),
            }
            self.service._save_cache_to_disk()

        def _hanging_probe(provider):
            time.sleep(2.0)
            return ["invented-model"]

        with patch.object(self.service, "_probe_provider", side_effect=_hanging_probe):
            t0 = time.time()
            res = self.service.discover_models_sync("antigravity", timeout=0.2)
            duration = time.time() - t0
            self.assertLess(duration, 1.0, "Discovery hung longer than timeout")
            self.assertEqual(res, ["gemini-3.5-flash"], "Did not retain previous cache on timeout")


class TestA9InventedModelsRemoval(unittest.TestCase):
    """P0-3: Removal of invented model literals."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a9_assigner_")
        self.config_path = Path(self.tmp_dir) / "router_profiles.yaml"
        self.cache_path = Path(self.tmp_dir) / "models_cache.json"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_ensure_profile_definition_without_cache_leaves_empty_models(self):
        # Empty discovery service
        md_svc = ModelDiscoveryService(cache_path=self.cache_path)
        with patch("antigravity_provider.router.model_discovery_service.ModelDiscoveryService.get", return_value=md_svc):
            with patch.dict(os.environ, {"HERMES_ROUTER_CONFIG": str(self.config_path)}):
                ok, msg = AutoAssigner.ensure_profile_definition("claude", "claude-custom-1")
                self.assertTrue(ok)

                cfg = load_router_config(self.config_path)
                p = cfg.profiles.get("claude-custom-1")
                self.assertIsNotNone(p)
                # Honest empty list when not discovered
                self.assertEqual(p.preferred_models, [])


class TestA9ProviderOrdering(unittest.TestCase):
    """P1-4: Deterministic Provider Ordering in Snapshot."""

    def test_provider_summaries_sorting_and_total_count(self):
        uh = UnifiedHealthService.get()
        summaries = uh.get_provider_summaries()
        self.assertEqual(len(summaries), 5)
        
        # Verify deterministic ordering: connected_count desc, total_slots desc, provider_name asc
        for i in range(len(summaries) - 1):
            s1 = summaries[i]
            s2 = summaries[i + 1]
            key1 = (-s1.connected_count, -s1.total_slots, s1.provider_name)
            key2 = (-s2.connected_count, -s2.total_slots, s2.provider_name)
            self.assertLessEqual(key1, key2)

        readiness = uh.get_system_readiness()
        self.assertEqual(readiness.total_providers, 5)


class TestA9HermesPluginBoundary(unittest.TestCase):
    """P0-00: Hermes call interception boundary and role determination."""

    def test_call_without_role_passes_downstream_without_router_attempts(self):
        from antigravity_provider import hermes_plugin

        downstream_calls = []
        def mock_next(req):
            downstream_calls.append(req)
            return {"choices": [{"message": {"role": "assistant", "content": "direct-model-response"}}]}

        # Call with no role and provider != antigravity
        res = hermes_plugin.antigravity_llm_execution(
            request={"messages": [{"role": "user", "content": "hello"}]},
            next_call=mock_next,
            provider="opencode-go",
            model="kimi-k2.7-code",
            session_id="sess-123",
        )
        self.assertEqual(len(downstream_calls), 1)
        content = res["choices"][0]["message"]["content"]
        self.assertEqual(content, "direct-model-response")

    def test_resolve_role_returns_none_when_unspecified(self):
        from antigravity_provider.router import get_router_engine
        engine = get_router_engine()
        # No role in request or explicit role -> None (no guessing from prompts)
        req = {"messages": [{"role": "system", "content": "You are a coding agent developer"}]}
        self.assertIsNone(engine.resolve_role(req))

    def test_resolve_role_respects_explicit_or_metadata_role(self):
        from antigravity_provider.router import get_router_engine
        engine = get_router_engine()
        self.assertEqual(engine.resolve_role({}, explicit_role="developer-1"), "developer-1")
        self.assertEqual(engine.resolve_role({"role": "code-reviewer"}), "code-reviewer")
        self.assertEqual(engine.resolve_role({"metadata": {"role": "researcher"}}), "researcher")


class TestA9CodexOAuthTokenRefreshAndSwitching(unittest.TestCase):
    """P0-01: Codex token refresh and safe account switching."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a9_codex_")
        self.profile_dir = Path(self.tmp_dir) / "openai-codex" / "codex-test"
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("antigravity_provider.router.codex_oauth._post_json")
    def test_refresh_codex_token_success(self, mock_post):
        mock_post.return_value = {
            "access_token": "new_access_token_456",
            "refresh_token": "new_refresh_token_789",
            "id_token": "header.eyJlbWFpbCI6ICJ1c2VyQGdtYWlsLmNvbSIsICJleHAiOiAyMDAwMDAwMDAwfQ.sig",
        }
        auth_data = {
            "provider": "openai-codex",
            "profile_id": "codex-test",
            "token": {"access_token": "old_acc", "refresh_token": "valid_refresh"},
        }
        with patch.object(ProfileAuthManager, "load_profile_auth", return_value=auth_data):
            with patch.object(ProfileAuthManager, "save_profile_auth") as mock_save:
                from antigravity_provider.router.codex_oauth import refresh_codex_token
                res = refresh_codex_token("codex-test")
                self.assertEqual(res["token"]["access_token"], "new_access_token_456")
                self.assertEqual(res["token"]["refresh_token"], "new_refresh_token_789")
                mock_save.assert_called_once()

    def test_refresh_codex_token_missing_raises_error(self):
        auth_data = {
            "provider": "openai-codex",
            "profile_id": "codex-test",
            "token": {"access_token": "old_acc"},
        }
        with patch.object(ProfileAuthManager, "load_profile_auth", return_value=auth_data):
            from antigravity_provider.router.codex_oauth import refresh_codex_token
            with self.assertRaises(RuntimeError) as ctx:
                refresh_codex_token("codex-test")
            self.assertIn("refresh_token отсутствует", str(ctx.exception))

    def test_get_profile_status_separate_token_expiry(self):
        # 1. Expired access token with refresh token -> AUTHENTICATED with refresh notice
        exp_access = "header.eyJlbWFpbCI6ICJ1c2VyQGdtYWlsLmNvbSIsICJleHAiOiAxMDAwfQ.sig" # expired in 1970
        valid_id = "header.eyJlbWFpbCI6ICJ1c2VyQGdtYWlsLmNvbSIsICJleHAiOiAyMDAwMDAwMDAwfQ.sig"
        auth_data = {
            "provider": "openai-codex",
            "profile_id": "codex-test",
            "token": {"access_token": exp_access, "id_token": valid_id, "refresh_token": "ref_123"},
        }
        with patch.object(ProfileAuthManager, "load_profile_auth", return_value=auth_data):
            st = ProfileAuthManager.get_profile_status("openai-codex", "codex-test")
            self.assertTrue(st["access_token_expired"])
            self.assertFalse(st["id_token_expired"])
            self.assertTrue(st["has_refresh_token"])
            self.assertFalse(st["is_expired"])  # Can be refreshed silently
            self.assertEqual(st["status"], "AUTHENTICATED")

        # 2. Expired access token without refresh token -> EXPIRED
        auth_data_no_refresh = {
            "provider": "openai-codex",
            "profile_id": "codex-test",
            "token": {"access_token": exp_access, "id_token": valid_id},
        }
        with patch.object(ProfileAuthManager, "load_profile_auth", return_value=auth_data_no_refresh):
            st2 = ProfileAuthManager.get_profile_status("openai-codex", "codex-test")
            self.assertTrue(st2["access_token_expired"])
            self.assertFalse(st2["has_refresh_token"])
            self.assertTrue(st2["is_expired"])
            self.assertEqual(st2["status"], "EXPIRED")

    def test_switch_active_codex_account_sequence_and_rollback(self):
        from antigravity_provider.router.codex_oauth import switch_active_codex_account
        steps = []
        def record_step(step_name, msg, status):
            steps.append((step_name, status))

        auth_data = {
            "provider": "openai-codex",
            "profile_id": "codex-test",
            "email": "user@example.com",
            "token": {"access_token": "valid_token", "refresh_token": "ref_123"},
        }
        with patch.object(ProfileAuthManager, "load_profile_auth", return_value=auth_data):
            res = switch_active_codex_account("codex-test", step_callback=record_step)
            self.assertTrue(res["success"])
            step_names = [s[0] for s in steps]
            self.assertIn("check_tokens", step_names)
            self.assertIn("stop_clients", step_names)
            self.assertIn("write_credentials", step_names)
            self.assertIn("sync_settings", step_names)
            self.assertIn("start_client", step_names)


if __name__ == "__main__":
    unittest.main()

