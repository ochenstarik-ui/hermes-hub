from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)
from antigravity_provider.router.router_engine import RouterEngine, get_router_engine
from antigravity_provider.hermes_plugin import antigravity_llm_execution
from antigravity_provider.router.settings_service import save_hub_settings, invalidate_settings_cache


class TestA35RoleResolution(unittest.TestCase):
    """P0-1 & P0-2: Role resolution and failover safety for Hermes Hub integration."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a35_")
        self.config_path = Path(self.tmp_dir) / "router_profiles.yaml"
        self.settings_path = Path(self.tmp_dir) / "hub_settings.json"

        self.profiles = {
            "ag-orch-fallback": RouterProfileConfig(
                profile_id="ag-orch-fallback",
                provider="antigravity",
                preferred_models=["gemini-3.7-flash"],
            ),
            "ag-w1": RouterProfileConfig(
                profile_id="ag-w1",
                provider="antigravity",
                preferred_models=["gemini-3.7-flash"],
            ),
            "ag-w2": RouterProfileConfig(
                profile_id="ag-w2",
                provider="antigravity",
                preferred_models=["gemini-3.1-pro-high"],
            ),
            "ag-w3": RouterProfileConfig(
                profile_id="ag-w3",
                provider="antigravity",
                preferred_models=["claude-opus-4-6-thinking"],
            ),
        }

        self.roles = {
            "manager": RolePolicy(
                role_name="manager",
                preferred_chain=["ag-orch-fallback"],
                default_model="gemini-3.7-flash",
            ),
            "developer-1": RolePolicy(
                role_name="developer-1",
                preferred_chain=["ag-w1"],
                default_model="gemini-3.7-flash",
            ),
            "developer-2": RolePolicy(
                role_name="developer-2",
                preferred_chain=["ag-w2"],
                default_model="gemini-3.1-pro-high",
            ),
            "code-reviewer": RolePolicy(
                role_name="code-reviewer",
                preferred_chain=["ag-w3"],
                default_model="claude-opus-4-6-thinking",
            ),
        }

        self.config = RouterConfig(
            enabled=True,
            default_role="manager",
            roles=self.roles,
            profiles=self.profiles,
        )
        save_router_config(self.config, self.config_path)

        self.env_patcher = patch.dict(
            "os.environ",
            {
                "HERMES_HOME": self.tmp_dir,
                "HERMES_ROUTER_PROFILES": str(self.config_path),
            },
        )
        self.env_patcher.start()
        invalidate_settings_cache()
        self.engine = RouterEngine(self.config)

    def tearDown(self):
        self.env_patcher.stop()
        invalidate_settings_cache()

    def test_explicit_role_resolution_level1(self):
        """Level 1: Explicit role in arguments, request or metadata takes highest priority."""
        # 1. Via explicit_role arg
        role, source = self.engine.resolve_role_with_source({}, explicit_role="developer-2")
        self.assertEqual(role, "developer-2")
        self.assertEqual(source, "explicit")

        # 2. Via request['role']
        role, source = self.engine.resolve_role_with_source({"role": "code-reviewer"})
        self.assertEqual(role, "code-reviewer")
        self.assertEqual(source, "explicit")

        # 3. Via request['metadata']['role']
        role, source = self.engine.resolve_role_with_source({"metadata": {"role": "manager"}})
        self.assertEqual(role, "manager")
        self.assertEqual(source, "explicit")

    def test_model_and_provider_resolution_level2(self):
        """Level 2: Resolution by model and provider dynamically configured in router roles."""
        # gemini-3.1-pro-high -> configured default_model for developer-2
        role, source = self.engine.resolve_role_with_source({}, model="gemini-3.1-pro-high")
        self.assertEqual(role, "developer-2")
        self.assertEqual(source, "model_match")

        # claude-opus-4-6-thinking -> configured default_model for code-reviewer
        role, source = self.engine.resolve_role_with_source({}, model="claude-opus-4-6-thinking")
        self.assertEqual(role, "code-reviewer")
        self.assertEqual(source, "model_match")

        # gemini-3.7-flash -> configured default_model for manager / developer-1
        role, source = self.engine.resolve_role_with_source({}, model="gemini-3.7-flash")
        self.assertIn(role, ["manager", "developer-1"])
        self.assertEqual(source, "model_match")

    def test_session_affinity_resolution_level3(self):
        """Level 3: Resolution by session affinity for session_id."""
        sess_id = "sess-affinity-test-123"
        # Register affinity record in router engine
        self.engine.affinity.set_affinity(sess_id, role="developer-2", profile_id="ag-w2")

        role, source = self.engine.resolve_role_with_source({}, session_id=sess_id)
        self.assertEqual(role, "developer-2")
        self.assertEqual(source, "session_affinity")

    def test_default_fallback_role_level4(self):
        """Level 4: Default fallback role when no explicit, model, or session affinity matched."""
        # By default, default_fallback gives 'manager'
        role, source = self.engine.resolve_role_with_source(
            {"messages": [{"role": "user", "content": "hello"}]},
            fallback_to_default=True,
        )
        self.assertEqual(role, "manager")
        self.assertEqual(source, "default_fallback")

        # Configurable via hub_settings.json
        save_hub_settings({"default_role": "code-reviewer"})
        role, source = self.engine.resolve_role_with_source(
            {"messages": [{"role": "user", "content": "hello"}]},
            fallback_to_default=True,
        )
        self.assertEqual(role, "code-reviewer")
        self.assertEqual(source, "default_fallback")

    def test_no_prompt_guessing_returns_none_when_fallback_disabled(self):
        """Zero prompt guessing: unspecified role returns None when fallback_to_default=False."""
        req = {"messages": [{"role": "system", "content": "You are a senior coding agent developer"}]}
        role, source = self.engine.resolve_role_with_source(req, fallback_to_default=False)
        self.assertIsNone(role)
        self.assertEqual(source, "none")

    def test_router_error_never_returned_as_assistant_content_to_hermes(self):
        """Safety Fuse: Router failover exhaustion (router_error) passes call downstream to next_call."""
        downstream_calls = []

        def mock_next(req):
            downstream_calls.append(req)
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "clean-downstream-response"},
                        "finish_reason": "stop",
                    }
                ]
            }

        # Mock engine route_request to return failover exhaustion error payload
        exhausted_payload = {
            "router_error": True,
            "error_type": "exhausted",
            "message": "All 3 profiles in role 'manager' failed",
            "failover_trail": ["ag-orch-fallback: timeout"],
        }

        with patch("antigravity_provider.router.get_router_engine", return_value=self.engine):
            with patch.object(self.engine, "route_request", return_value=exhausted_payload):
                res = antigravity_llm_execution(
                    request={"messages": [{"role": "user", "content": "test safety"}]},
                    next_call=mock_next,
                    provider="antigravity",
                    model="gemini-3.7-flash",
                    session_id="sess-safety-1",
                )

        # Verified: Downstream call was executed and router error text did NOT become the assistant message
        self.assertEqual(len(downstream_calls), 1)
        content = res["choices"][0]["message"]["content"]
        self.assertEqual(content, "clean-downstream-response")
        self.assertNotIn("exhausted", content.lower())
        self.assertNotIn("router_error", content.lower())

    def test_empty_profile_config_passes_cleanly_to_next_call(self):
        """Empty profile configuration must not break Hermes and falls through cleanly."""
        empty_config = RouterConfig(enabled=True, roles={}, profiles={})
        empty_engine = RouterEngine(empty_config)

        downstream_calls = []

        def mock_next(req):
            downstream_calls.append(req)
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "clean-passthrough-response"},
                        "finish_reason": "stop",
                    }
                ]
            }

        with patch("antigravity_provider.router.get_router_engine", return_value=empty_engine):
            res = antigravity_llm_execution(
                request={"messages": [{"role": "user", "content": "test passthrough"}]},
                next_call=mock_next,
                provider="antigravity",
                model="gemini-3.7-flash",
            )

        self.assertEqual(len(downstream_calls), 1)
        self.assertEqual(res["choices"][0]["message"]["content"], "clean-passthrough-response")

    def test_hermes_call_records_event_log_and_telemetry(self):
        """Successful Hermes routing records chosen role, reason, profile, and telemetry."""
        from antigravity_provider.router.unified_health import EventLogService

        mock_completion = {
            "choices": [{"message": {"role": "assistant", "content": "model-output-ok"}}],
            "router_metadata": {
                "provider": "antigravity",
                "profile_id": "ag-w2",
                "selected_model": "gemini-3.1-pro-high",
            },
        }

        with patch("antigravity_provider.router.get_router_engine", return_value=self.engine):
            with patch.object(self.engine, "route_request", return_value=mock_completion):
                res = antigravity_llm_execution(
                    request={"messages": [{"role": "user", "content": "test event logging"}]},
                    provider="antigravity",
                    model="gemini-3.1-pro-high",
                    session_id="sess-log-1",
                )

        content = (
            res.choices[0].message.content
            if hasattr(res, "choices")
            else res["choices"][0]["message"]["content"]
        )
        self.assertEqual(content, "model-output-ok")
        events = EventLogService.get().get_events(limit=10, category="routing")
        self.assertTrue(any("developer-2" in e.message for e in events))
        matching_event = next(e for e in events if "developer-2" in e.message)
        self.assertIn("по модели и провайдеру", matching_event.message)
        self.assertIn("ag-w2", matching_event.details)


if __name__ == "__main__":
    unittest.main()
