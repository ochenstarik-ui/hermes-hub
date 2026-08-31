from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from antigravity_provider.router.action_handler import ActionExecutor, do_save_settings
from antigravity_provider.router.role_registry import RoleRegistry, get_role_definition, normalize_role_name
from antigravity_provider.router.router_config import RouterConfig, save_router_config
from antigravity_provider.router.settings_service import (
    get_hub_settings,
    save_hub_settings,
    setup_memory_structure,
    validate_obsidian_vault_path,
)
from antigravity_provider.router.skills_service import (
    SkillDoctor,
    SkillsService,
    parse_skill_frontmatter,
)
from antigravity_provider.router.workflow_service import (
    CANONICAL_NODE_POSITIONS,
    WorkflowService,
    get_canonical_pipeline,
)


class TestA49SubagentsSkillsMemory(unittest.TestCase):
    """A49: 14 canonical roles, SkillDoctor, Skills Tab, and Obsidian Vault integration."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="hermes_test_a49_")
        self.config_path = Path(self.tmp_dir) / "router_profiles.yaml"
        self.state_path = Path(self.tmp_dir) / "workflow_state.json"
        self.usage_path = Path(self.tmp_dir) / "skills_usage.json"
        self.skills_dir = Path(self.tmp_dir) / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        self.env_patcher = patch.dict(
            "os.environ",
            {
                "HERMES_HOME": self.tmp_dir,
                "HERMES_ROUTER_PROFILES": str(self.config_path),
            },
        )
        self.env_patcher.start()

        # Reset singletons
        SkillsService._instance = None

    def tearDown(self):
        SkillsService._instance = None
        self.env_patcher.stop()

    def test_canonical_14th_role_skill_doctor(self):
        """P0-1: 14th canonical role skill-doctor is registered with correct Russian metadata and aliases."""
        canonical_roles = RoleRegistry.list_canonical_roles()
        self.assertGreaterEqual(len(canonical_roles), 14)
        self.assertIn("skill-doctor", canonical_roles)

        doc_role = get_role_definition("skill-doctor")
        self.assertIsNotNone(doc_role)
        self.assertEqual(doc_role.role_id, "skill-doctor")
        self.assertEqual(doc_role.display_name_ru, "Скилл-доктор")
        self.assertEqual(doc_role.short_name_ru, "Скилл-доктор")
        self.assertEqual(doc_role.tier, "expert")
        self.assertIn("skill-doctor", doc_role.capabilities)
        self.assertIn("diagnostics", doc_role.capabilities)

        # Test aliases
        self.assertEqual(normalize_role_name("skill-doctor"), "skill-doctor")
        self.assertEqual(normalize_role_name("skill_doctor"), "skill-doctor")
        self.assertEqual(normalize_role_name("скилл-доктор"), "skill-doctor")
        self.assertEqual(normalize_role_name("скиллдоктор"), "skill-doctor")

    def test_canonical_14_roles_pipeline_graph_and_positions(self):
        """P0-1: Canonical workflow graph contains forward pipeline, 3 return loops (max_iterations=5), and non-overlapping coordinates."""
        pipeline = get_canonical_pipeline()
        self.assertEqual(pipeline.start_agent_id, "manager")
        self.assertEqual(pipeline.max_iterations, 5)

        edges = [(e.source, e.target, e.condition) for e in pipeline.edges]
        # Forward edges
        self.assertIn(("manager", "dependency-agent", "SUCCESS"), edges)
        self.assertIn(("dependency-agent", "developer-1", "SUCCESS"), edges)
        self.assertIn(("researcher", "developer-1", "SUCCESS"), edges)
        self.assertIn(("developer-1", "developer-2", "SUCCESS"), edges)
        self.assertIn(("developer-2", "code-reviewer", "REVIEW_PASSED"), edges)
        self.assertIn(("code-reviewer", "tester", "REVIEW_PASSED"), edges)
        self.assertIn(("tester", "tech-writer", "SUCCESS"), edges)
        self.assertIn(("tech-writer", "manager", "SUCCESS"), edges)

        # 3 return loops with max_iterations=5
        return_loops = [e for e in pipeline.edges if e.condition == "REVIEW_FAILED"]
        self.assertEqual(len(return_loops), 3)

        loop_map = {e.source: (e.target, e.max_iterations) for e in return_loops}
        self.assertEqual(loop_map["developer-2"], ("developer-1", 5))
        self.assertEqual(loop_map["code-reviewer"], ("developer-2", 5))
        self.assertEqual(loop_map["tester"], ("developer-1", 5))

        # Check non-overlapping coordinates
        self.assertEqual(len(CANONICAL_NODE_POSITIONS), 14)
        pos_set = set()
        for role_id, pos in CANONICAL_NODE_POSITIONS.items():
            coord = (pos["x"], pos["y"])
            self.assertNotIn(coord, pos_set, f"Overlap detected for role {role_id} at {coord}")
            pos_set.add(coord)

    def test_skill_doctor_valid_skill(self):
        """P0-4: SkillDoctor approves well-formed SKILL.md with single-line description and 3-part triggers."""
        content = """---
name: frontend-design
description: Design-quality skill for AI agents building websites, landing pages, and web app UI. Use when creating web interfaces, styling UI components, refining typography and layout, or reviewing frontend design. Do NOT use for backend-only logic, database migrations, or server configuration.
tags: [frontend, design, ui, css]
---

# Frontend Design Guidelines

## Instructions
Follow modern Linear/Stripe design aesthetics.

## Examples
```css
.card { border-radius: 8px; }
```
"""
        diag = SkillDoctor.diagnose(content, filename="SKILL.md", filepath="/path/to/SKILL.md")
        self.assertTrue(diag.is_valid)
        self.assertEqual(len(diag.critical_errors), 0)
        self.assertEqual(diag.skill_name, "frontend-design")
        self.assertEqual(len(diag.test_queries["positive"]), 3)
        self.assertEqual(len(diag.test_queries["negative"]), 2)
        self.assertIn("frontend-design", diag.report_markdown)

    def test_skill_doctor_multiline_description_critical_error(self):
        """P0-4: SkillDoctor flags multiline description as a critical error and generates single-line fix."""
        broken_content = """---
name: broken-skill
description: |
  This is a multiline description
  which violates the strict Antigravity single-line rule.
tags: [test]
---

# Broken Skill Body
"""
        diag = SkillDoctor.diagnose(broken_content, filename="SKILL.md", filepath="/path/to/SKILL.md")
        self.assertFalse(diag.is_valid)
        self.assertTrue(any("строго в одну строку" in err for err in diag.critical_errors))
        self.assertFalse(diag.checks["single_line_description"]["passed"])

        # Fixed description must be single-line
        self.assertNotIn("\n", diag.fixed_description)
        self.assertNotIn("\r", diag.fixed_description)
        self.assertTrue(len(diag.fixed_description) > 20)

    def test_skill_doctor_wrong_filename(self):
        """P0-4: SkillDoctor rejects filenames that are not strictly 'SKILL.md'."""
        content = "---\nname: my-skill\ndescription: Single line description. Use when testing. Do not use for production.\n---\nBody"
        diag = SkillDoctor.diagnose(content, filename="skill.markdown")
        self.assertFalse(diag.is_valid)
        self.assertTrue(any("SKILL.md" in err for err in diag.critical_errors))

    def test_skills_service_discovery_assignment_and_usage(self):
        """P0-2, P0-3: Skills discovery, subagent assignment in workflow_state.json, and truthful usage tracking."""
        # Create a sample skill in test skills_dir
        skill_dir = self.skills_dir / "code-analyzer"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            """---
name: code-analyzer
description: Performs deep AST and lint analysis of codebases. Use when analyzing code quality, running static analysis, or checking architecture rules. Do NOT use for editing files directly.
tags: [analysis, linter, ast]
---

# Code Analyzer Instructions
Run checks before review.
""",
            encoding="utf-8",
        )

        wf_service = WorkflowService(self.state_path)
        skills_service = SkillsService(usage_path=self.usage_path)

        # 1. Discovery
        skills = skills_service.discover_skills(extra_paths=[self.skills_dir])
        self.assertTrue(any(s.name == "code-analyzer" for s in skills))

        # 2. Assign skill to developer-1
        res = skills_service.assign_skill("code-analyzer", "developer-1")
        self.assertTrue(res["ok"])
        self.assertIn("skill:code-analyzer", wf_service.agents["developer-1"].tools)

        # Verify persistence in workflow_state.json
        state_data = json.loads(self.state_path.read_text(encoding="utf-8"))
        dev1_data = next(a for a in state_data["agents"] if a["id"] == "developer-1")
        self.assertIn("skill:code-analyzer", dev1_data["tools"])

        # 3. Usage tracking (truthfulness test)
        initial_usage = skills_service.get_skills_usage()
        self.assertFalse(initial_usage["has_usage"])
        self.assertEqual(initial_usage["message"], "Н/Д: вызовы со скиллами ещё не регистрировались")

        # Record invocations
        skills_service.record_skill_usage("code-analyzer", "developer-1", success=True, duration_ms=120.5)
        skills_service.record_skill_usage("code-analyzer", "developer-1", success=False, duration_ms=45.0)

        updated_usage = skills_service.get_skills_usage()
        self.assertTrue(updated_usage["has_usage"])
        self.assertEqual(updated_usage["total_calls"], 2)
        self.assertEqual(updated_usage["skills"]["code-analyzer"]["usage_count"], 2)
        self.assertEqual(updated_usage["skills"]["code-analyzer"]["success_count"], 1)
        self.assertEqual(updated_usage["skills"]["code-analyzer"]["failed_count"], 1)

        # 4. Unassign skill
        unres = skills_service.unassign_skill("code-analyzer", "developer-1")
        self.assertTrue(unres["ok"])
        self.assertNotIn("skill:code-analyzer", wf_service.agents["developer-1"].tools)

    def test_obsidian_vault_validation_and_memory_setup(self):
        """P0-5, P0-6: Obsidian vault path validation and non-destructive canonical structure deployment."""
        # 1. Empty vault path is valid (hub works without Obsidian)
        val_ok, val_msg, details = validate_obsidian_vault_path("")
        self.assertTrue(val_ok)
        self.assertFalse(details["configured"])

        # 2. Non-existent vault path is invalid
        val_ok, val_msg, details = validate_obsidian_vault_path("/path/that/does/not/exist/12345")
        self.assertFalse(val_ok)
        self.assertIn("не существует", val_msg)

        # 3. Directory without .obsidian is rejected as not an Obsidian vault
        plain_dir = Path(self.tmp_dir) / "plain_dir"
        plain_dir.mkdir(parents=True, exist_ok=True)
        val_ok, val_msg, details = validate_obsidian_vault_path(str(plain_dir))
        self.assertFalse(val_ok)
        self.assertIn(".obsidian", val_msg)

        # 4. Valid Obsidian vault with existing notes (must never be deleted)
        vault_dir = Path(self.tmp_dir) / "AI-Memory"
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / ".obsidian").mkdir(parents=True, exist_ok=True)
        
        # Pre-existing notes
        existing_note = vault_dir / "00_SYSTEM" / "AGENT_PROTOCOL.md"
        existing_note.parent.mkdir(parents=True, exist_ok=True)
        existing_note.write_text("# Existing Protocol\nDo not overwrite.", encoding="utf-8")

        val_ok, val_msg, details = validate_obsidian_vault_path(str(vault_dir))
        self.assertTrue(val_ok)
        self.assertTrue(details["configured"])
        self.assertGreaterEqual(details["notes_count"], 1)

        # Deploy memory structure
        setup_res = setup_memory_structure(vault_path=str(vault_dir), project_name="hermes-hub")
        self.assertTrue(setup_res["ok"])

        # Verify canonical directories exist
        self.assertTrue((vault_dir / "00_SYSTEM").is_dir())
        self.assertTrue((vault_dir / "01_PROJECTS" / "hermes-hub").is_dir())
        self.assertTrue((vault_dir / "01_PROJECTS" / "hermes-hub" / "worklog").is_dir())
        self.assertTrue((vault_dir / "03_LESSONS").is_dir())
        self.assertTrue((vault_dir / "04_PATTERNS").is_dir())
        self.assertTrue((vault_dir / "05_AGENTS").is_dir())
        self.assertTrue((vault_dir / "worklog").is_dir())

        # Verify existing note was preserved untouched
        self.assertEqual(existing_note.read_text(encoding="utf-8"), "# Existing Protocol\nDo not overwrite.")

    def test_settings_service_and_action_handler_integration(self):
        """P0-5, P0-6: ActionExecutor actions for skills and Obsidian memory."""
        # 1. Action: get_skills
        res = ActionExecutor.execute("get_skills", {})
        self.assertTrue(res["ok"])
        self.assertIn("skills", res["data"])

        # 2. Action: diagnose_skill on inline content
        res_diag = ActionExecutor.execute(
            "diagnose_skill",
            {
                "content": "---\nname: tester-skill\ndescription: Test skill. Use when testing. Do NOT use otherwise.\n---\nBody",
            },
        )
        self.assertTrue(res_diag["ok"])
        self.assertIn("diagnosis", res_diag["data"])

        # 3. Action: check_obsidian_vault
        res_vault = ActionExecutor.execute("check_obsidian_vault", {"obsidian_vault_path": ""})
        self.assertTrue(res_vault["ok"])

        # 4. Settings save with invalid obsidian vault path must fail
        save_ok, save_msg = do_save_settings({"obsidian_vault_path": "/non/existent/vault/path/xyz"})
        self.assertFalse(save_ok)
        self.assertIn("Obsidian", save_msg)


if __name__ == "__main__":
    unittest.main()
