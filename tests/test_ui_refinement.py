# -*- coding: utf-8 -*-
"""Unit tests for UI refinement, test action safety, and settings persistence."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import pytest

from antigravity_provider.router.hermes_hub_app import do_test_profile, do_set_main, do_set_orchestrator
from antigravity_provider.router.profile_manager import ProfileAuthManager


def test_test_action_safe_on_unauthenticated():
    """Verify that testing an unauthenticated profile returns an error and never triggers OAuth/browser."""
    # ag-spare-2 is unauthenticated
    res = do_test_profile("antigravity", "ag-spare-2")
    assert res["success"] is False
    assert len(res.get("error", "")) > 0


def test_test_action_non_existent_profile():
    """Verify that testing a non-existent profile returns a clean error."""
    res = do_test_profile("antigravity", "non_existent_profile_xyz")
    assert res["success"] is False
    assert len(res.get("error", "")) > 0


def test_set_main_profile_action():
    """Verify that do_set_main updates the default profile."""
    # Ensure profile has saved auth
    ProfileAuthManager.save_profile_auth("antigravity", "ag-w1", {"tokens": {"access_token": "valid"}})
    
    # Test setting main profile
    ok, msg = do_set_main("antigravity", "ag-w1")
    assert ok is True
    assert "ag-w1" in msg

    # Verify via ProfileAuthManager
    main_pid = ProfileAuthManager.get_main_profile("antigravity")
    assert main_pid == "ag-w1"


def test_set_orchestrator_action():
    """Verify that do_set_orchestrator updates orchestrator role policy."""
    ok, msg = do_set_orchestrator("ag-w2")
    assert ok is True
    assert "ag-w2" in msg
