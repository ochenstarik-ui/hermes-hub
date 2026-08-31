from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from antigravity_provider.router.router_config import (
    RolePolicy,
    RouterConfig,
    RouterProfileConfig,
    save_router_config,
)
from antigravity_provider.router.workflow_service import (
    WorkflowService,
    WorkflowDefinition,
    WorkflowEdge,
    get_canonical_a36_pipeline,
)


class TestA36AntigravityPipeline(unittest.TestCase):
    """P0-1 .. P0-5: Antigravity pipeline graph, loops, limits, models and execution."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a36_")
        self.config_path = Path(self.tmp_dir) / "router_profiles.yaml"
        self.state_path = Path(self.tmp_dir) / "workflow_state.json"

        self.profiles = {
            "ag-orch-fallback": RouterProfileConfig(
                profile_id="ag-orch-fallback",
                provider="antigravity",
                preferred_models=["gemini-3.7-flash"],
            ),
            "ag-w1": RouterProfileConfig(
                profile_id="ag-w1",
                provider="antigravity",
                preferred_models=["gemini-3.7-flash", "gemini-3.7-flash-high"],
            ),
            "ag-w2": RouterProfileConfig(
                profile_id="ag-w2",
                provider="antigravity",
                preferred_models=["gemini-3.1-pro-high", "gemini-3.1-pro-low"],
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
        self.wf_service = WorkflowService(self.state_path)
        self.wf_service.workflow = get_canonical_a36_pipeline()

    def tearDown(self):
        self.env_patcher.stop()

    def test_canonical_pipeline_graph_structure(self):
        """P0-1: Canonical graph matches orchestrator, two coders, reviewer layout."""
        snapshot = self.wf_service.snapshot()
        agents = {a["id"]: a for a in snapshot["agents"]}

        # 1. Check all 4 agents exist
        self.assertIn("manager", agents)
        self.assertIn("developer-1", agents)
        self.assertIn("developer-2", agents)
        self.assertIn("code-reviewer", agents)

        # 2. Check model bindings
        self.assertEqual(agents["manager"]["execution_config"]["model"], "gemini-3.7-flash")
        self.assertEqual(agents["developer-1"]["execution_config"]["model"], "gemini-3.7-flash")
        self.assertEqual(agents["developer-2"]["execution_config"]["model"], "gemini-3.1-pro-high")
        self.assertEqual(agents["code-reviewer"]["execution_config"]["model"], "claude-opus-4-6-thinking")

        # 3. Check account bindings
        self.assertEqual(agents["manager"]["execution_config"]["account"], "ag-orch-fallback")
        self.assertEqual(agents["developer-1"]["execution_config"]["account"], "ag-w1")
        self.assertEqual(agents["developer-2"]["execution_config"]["account"], "ag-w2")
        self.assertEqual(agents["code-reviewer"]["execution_config"]["account"], "ag-w3")

        # 4. Check edges and feedback loops
        definition = snapshot["definition"]
        self.assertEqual(definition["start_agent_id"], "manager")
        edges = {(e["source"], e["target"], e["condition"]) for e in definition["edges"]}

        # Forward flow
        self.assertIn(("manager", "developer-1", "SUCCESS"), edges)
        self.assertIn(("developer-1", "developer-2", "SUCCESS"), edges)
        self.assertIn(("developer-2", "code-reviewer", "REVIEW_PASSED"), edges)
        self.assertIn(("code-reviewer", "manager", "REVIEW_PASSED"), edges)

        # Inner feedback loop: developer-2 -> developer-1 on REVIEW_FAILED
        self.assertIn(("developer-2", "developer-1", "REVIEW_FAILED"), edges)

        # Outer feedback loop: code-reviewer -> developer-2 (NOT developer-1!) on REVIEW_FAILED
        self.assertIn(("code-reviewer", "developer-2", "REVIEW_FAILED"), edges)

    def test_live_execution_with_triggered_inner_loop(self):
        """P0-3: Live execution run with Coder 2 returning work to Coder 1."""
        step_call_count = {"developer-1": 0, "developer-2": 0, "code-reviewer": 0, "manager": 0}
        step_history = []

        class FakePipelineEngine:
            def reload_config(self):
                return None

            def route_request(self, request, role=None, session_id=None):
                step_call_count[role] = step_call_count.get(role, 0) + 1
                step_history.append((role, step_call_count[role]))

                if role == "manager":
                    if step_call_count["manager"] == 1:
                        return {
                            "choices": [{"message": {"content": "SUCCESS: Task dispatched to Developer 1"}}],
                            "router_metadata": {"profile_id": "ag-orch-fallback", "selected_model": "gemini-3.7-flash"},
                        }
                    else:
                        return {
                            "choices": [{"message": {"content": "ACCEPTED: Project verified and accepted by Orchestrator"}}],
                            "router_metadata": {"profile_id": "ag-orch-fallback", "selected_model": "gemini-3.7-flash"},
                        }
                elif role == "developer-1":
                    if step_call_count["developer-1"] == 1:
                        return {
                            "choices": [{"message": {"content": "SUCCESS: Initial code implementation"}}],
                            "router_metadata": {"profile_id": "ag-w1", "selected_model": "gemini-3.7-flash"},
                        }
                    else:
                        return {
                            "choices": [{"message": {"content": "SUCCESS: Fixed error handling per Coder 2 feedback"}}],
                            "router_metadata": {"profile_id": "ag-w1", "selected_model": "gemini-3.7-flash"},
                        }
                elif role == "developer-2":
                    if step_call_count["developer-2"] == 1:
                        # First check: Reject and return to developer-1
                        return {
                            "choices": [{"message": {"content": "REVIEW_FAILED: Missing error handling and edge cases"}}],
                            "router_metadata": {"profile_id": "ag-w2", "selected_model": "gemini-3.1-pro-high"},
                        }
                    else:
                        # Second check: Approve and advance to reviewer
                        return {
                            "choices": [{"message": {"content": "REVIEW_PASSED: Code approved by Coder 2"}}],
                            "router_metadata": {"profile_id": "ag-w2", "selected_model": "gemini-3.1-pro-high"},
                        }
                elif role == "code-reviewer":
                    return {
                        "choices": [{"message": {"content": "REVIEW_PASSED: Security and architecture approved"}}],
                        "router_metadata": {"profile_id": "ag-w3", "selected_model": "claude-opus-4-6-thinking"},
                    }
                return {"choices": [{"message": {"content": "SUCCESS"}}]}

        with patch("antigravity_provider.router.router_engine.get_router_engine", return_value=FakePipelineEngine()):
            self.wf_service.start("Создать модуль аутентификации с валидацией токенов")
            thread = self.wf_service._thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "Workflow thread hung during execution")

        # Verify completed execution status
        self.assertEqual(
            self.wf_service.run["status"],
            "completed",
            f"Run failed with error: {self.wf_service.run.get('error')}, events: {[e.message for e in self.wf_service.events]}",
        )

        # Verify transition sequence
        expected_sequence = [
            ("manager", 1),
            ("developer-1", 1),
            ("developer-2", 1),  # Returns REVIEW_FAILED -> triggers loop back to dev-1
            ("developer-1", 2),  # dev-1 fixes code
            ("developer-2", 2),  # dev-2 approves -> REVIEW_PASSED
            ("code-reviewer", 1),  # reviewer approves -> REVIEW_PASSED
            ("manager", 2),  # manager acceptance -> completed
        ]
        self.assertEqual(step_history, expected_sequence)

        # Verify transition events
        transitions = [e.message for e in self.wf_service.events if e.type == "WORKFLOW_TRANSITION"]
        self.assertIn("Переход developer-2 → developer-1: REVIEW_FAILED", transitions)
        self.assertIn("Переход developer-2 → code-reviewer: REVIEW_PASSED", transitions)
        self.assertIn("Переход code-reviewer → manager: REVIEW_PASSED", transitions)

    def test_iteration_limit_cutoff_and_event(self):
        """P0-2: Loop iteration cutoff emits WORKFLOW_MAX_ITERATIONS and sets failed status."""
        self.wf_service.workflow.max_iterations = 2
        self.wf_service._save()

        class InfiniteLoopEngine:
            def reload_config(self):
                return None

            def route_request(self, request, role=None, session_id=None):
                if role == "manager":
                    return {"choices": [{"message": {"content": "SUCCESS: Start task"}}]}
                elif role == "developer-1":
                    return {"choices": [{"message": {"content": "SUCCESS: Dev 1 draft"}}]}
                elif role == "developer-2":
                    # Always reject to simulate unending loop
                    return {"choices": [{"message": {"content": "REVIEW_FAILED: Reject again"}}]}
                return {"choices": [{"message": {"content": "SUCCESS"}}]}

        with patch("antigravity_provider.router.router_engine.get_router_engine", return_value=InfiniteLoopEngine()):
            self.wf_service.start("Тест предела итераций")
            thread = self.wf_service._thread
            self.assertIsNotNone(thread)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

        self.assertEqual(self.wf_service.run["status"], "failed")
        self.assertIn("Достигнут предел итераций", self.wf_service.run["error"])
        self.assertTrue(any(e.type == "WORKFLOW_MAX_ITERATIONS" for e in self.wf_service.events))

    def test_agent_model_reconfiguration(self):
        """P0-4: Changing model on agent updates configuration and router policy."""
        # Update developer-1 model to gemini-3.7-flash-high
        updated = self.wf_service.update_agent("developer-1", {"model": "gemini-3.7-flash-high"})
        self.assertEqual(updated.id, "developer-1")

        snap = self.wf_service.snapshot()
        dev1 = next(a for a in snap["agents"] if a["id"] == "developer-1")
        self.assertEqual(dev1["execution_config"]["model"], "gemini-3.7-flash-high")

    def test_multi_account_parallelism_without_global_mutex(self):
        """P0-4: Requests to distinct Antigravity accounts execute concurrently without blocking."""
        from antigravity_provider.router.router_engine import RouterEngine

        engine = RouterEngine(self.config)
        execution_times = {}

        def slow_execution(profile_id, duration=0.2):
            t0 = time.monotonic()
            time.sleep(duration)
            execution_times[profile_id] = round(time.monotonic() - t0, 3)
            return {
                "choices": [{"message": {"content": f"output from {profile_id}"}}],
                "router_metadata": {"profile_id": profile_id, "provider": "antigravity"},
            }

        mock_adapter = MagicMock()
        mock_adapter.invoke.side_effect = lambda profile, req: slow_execution(profile.profile_id)

        with patch("antigravity_provider.router.router_engine.get_adapter", return_value=mock_adapter):
            import concurrent.futures

            start_t = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                f1 = executor.submit(engine.route_request, {"model": "gemini-3.7-flash"}, role="developer-1")
                f2 = executor.submit(engine.route_request, {"model": "gemini-3.1-pro-high"}, role="developer-2")
                f3 = executor.submit(engine.route_request, {"model": "claude-opus-4-6-thinking"}, role="code-reviewer")

                r1 = f1.result(timeout=2)
                r2 = f2.result(timeout=2)
                r3 = f3.result(timeout=2)

            total_elapsed = time.monotonic() - start_t

        # 3 calls taking 0.2s each running in parallel should take ~0.2-0.5s total, NOT serialized 0.6s+ on quiet CPU
        self.assertLess(total_elapsed, 1.5, f"Execution was serialized instead of parallel: {total_elapsed:.3f}s")
        self.assertEqual(r1["choices"][0]["message"]["content"], "output from ag-w1")
        self.assertEqual(r2["choices"][0]["message"]["content"], "output from ag-w2")
        self.assertEqual(r3["choices"][0]["message"]["content"], "output from ag-w3")


if __name__ == "__main__":
    unittest.main()
