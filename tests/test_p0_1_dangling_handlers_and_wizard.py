import re
import subprocess
from pathlib import Path
import pytest


APP_JS_PATH = Path("src/antigravity_provider/router/web/static/app.js")
INDEX_HTML_PATH = Path("src/antigravity_provider/router/web/static/index.html")


@pytest.fixture
def app_js_content():
    assert APP_JS_PATH.exists(), f"{APP_JS_PATH} does not exist"
    return APP_JS_PATH.read_text(encoding="utf-8")


@pytest.fixture
def index_html_content():
    assert INDEX_HTML_PATH.exists(), f"{INDEX_HTML_PATH} does not exist"
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def _is_function_defined(code: str, func_name: str) -> bool:
    patterns = [
        rf"function\s+{re.escape(func_name)}\s*\(",
        rf"async\s+function\s+{re.escape(func_name)}\s*\(",
        rf"(?:const|let|var)\s+{re.escape(func_name)}\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>",
        rf"(?:const|let|var)\s+{re.escape(func_name)}\s*=\s*(?:async\s*)?function\s*\(",
    ]
    return any(re.search(p, code) for p in patterns)


@pytest.mark.unit
def test_p0_1_open_add_account_wizard_defined(app_js_content):
    """P0-1: openAddAccountWizard must be defined in app.js."""
    assert _is_function_defined(app_js_content, "openAddAccountWizard"), (
        "openAddAccountWizard is called in DOM/events but has 0 definitions in app.js"
    )


@pytest.mark.unit
def test_p0_1_handle_node_account_change_defined(app_js_content):
    """P0-1: handleNodeAccountChange must be defined in app.js."""
    assert _is_function_defined(app_js_content, "handleNodeAccountChange"), (
        "handleNodeAccountChange is called in overview/routing diagrams but has 0 definitions in app.js"
    )


@pytest.mark.unit
def test_p0_1_handle_node_model_change_defined(app_js_content):
    """P0-1: handleNodeModelChange must be defined in app.js."""
    assert _is_function_defined(app_js_content, "handleNodeModelChange"), (
        "handleNodeModelChange is called in overview/routing diagrams but has 0 definitions in app.js"
    )


@pytest.mark.unit
def test_p0_1_handle_refresh_provider_models_defined(app_js_content):
    """P0-1: handleRefreshProviderModels must be defined in app.js."""
    assert _is_function_defined(app_js_content, "handleRefreshProviderModels"), (
        "handleRefreshProviderModels is called in overview/routing diagrams but has 0 definitions in app.js"
    )


@pytest.mark.unit
def test_p0_1_check_updates_defined(app_js_content):
    """P0-1: checkUpdates must be defined in app.js."""
    assert _is_function_defined(app_js_content, "checkUpdates"), (
        "checkUpdates is called at DOMContentLoaded and button click but has 0 definitions in app.js"
    )


@pytest.mark.unit
def test_p0_1_all_html_and_template_handlers_defined(app_js_content, index_html_content):
    """P0-1: All inline event handlers used in HTML and template literals must have matching definitions in app.js."""
    combined = index_html_content + "\n" + app_js_content
    handler_pattern = re.compile(r'on(?:click|change|submit|input|keydown|keyup|dragstart|dragover|dragleave|drop|dragend)\s*=\s*["\x27](?:return\s+)?([a-zA-Z0-9_$]+)\s*\(', re.IGNORECASE)
    
    used_handlers = set(handler_pattern.findall(combined))
    assert used_handlers, "No event handlers found in HTML/JS"

    missing = [h for h in sorted(used_handlers) if not _is_function_defined(app_js_content, h)]
    assert not missing, f"The following handlers are called in UI but missing function definitions: {missing}"


@pytest.mark.unit
def test_p0_1_wizard_contracts_and_actions(app_js_content):
    """P0-1: Wizard must use startDeviceAuth, startRedirectAuth, add_account and support manual slot selection."""
    assert "showWizardStep1" in app_js_content
    assert "showWizardStep2" in app_js_content
    assert "showWizardStep3" in app_js_content
    assert "finishAddAccount" in app_js_content
    # Wizard slot selection & SSH port-forward tunnel hints
    assert "buildSlotOptions" in app_js_content
    assert "startDeviceAuth" in app_js_content
    assert "startRedirectAuth" in app_js_content
    assert "wiz-redirect-tunnel" in app_js_content or "ssh -L" in app_js_content
    # Base url manual input for local LLM
    assert "wiz-base-url-input" in app_js_content


@pytest.mark.unit
def test_p0_1_node_dom_execution_contract():
    """P0-1: Execute targeted Node.js script to simulate DOM loading and verify all 5 handlers are callable."""
    res = subprocess.run(
        ["node", "tests/test_web_handlers_dom_contract.js"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node DOM contract test failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


@pytest.mark.unit
def test_p0_1_no_elementsmap_in_production_app_js(app_js_content):
    """P0-1 regression: elementsMap must NOT appear in production app.js.
    elementsMap is a test-only artifact — its use in openAddAccountWizard caused
    a ReferenceError in the real browser where elementsMap is undefined.
    Any test-only element-caching must live inside the Node test sandbox only.
    """
    assert 'elementsMap' not in app_js_content, (
        "elementsMap must not appear in production app.js — "
        "it is a test-only variable. openAddAccountWizard must not reference it."
    )


# ─────────────────────────────────────────────────────────────────────────────
# TDD: owner-selected slots for every account-connect flow (P0-1 remainder)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_tdd_grok_codex_shows_slot_picker_before_device_auth(app_js_content):
    """TDD GAP-1: Grok/Codex device-auth must show owner slot picker BEFORE startDeviceAuth.
    The grok/openai-codex branch in showWizardStep2 must include wiz-device-slot select.
    """
    # Find the grok/openai-codex branch in showWizardStep2
    # It must have a slot select element, not just device-auth-box
    assert "wiz-device-slot" in app_js_content, (
        "GAP-1: grok/codex flow must have 'wiz-device-slot' select element in the template"
    )
    # The slot select must use buildSlotOptions to populate options
    assert "buildSlotOptions" in app_js_content


@pytest.mark.unit
def test_tdd_finish_add_account_sends_profile_id(app_js_content):
    """TDD GAP-2: finishAddAccount must send chosen profile_id/slot in add_account payload.
    It must NOT silently find_free_slot for the owner.
    """
    # finishAddAccount must read wiz-device-slot OR wiz-redirect-slot
    # and include profile_id in the payload
    assert "wiz-device-slot" in app_js_content or "wiz-redirect-slot" in app_js_content, (
        "GAP-2: finishAddAccount must read a slot select element (wiz-device-slot or wiz-redirect-slot)"
    )
    # The payload passed to add_account must include profile_id
    # Look for pattern: payload.profile_id or payload['profile_id']
    finish_fn_match = re.search(
        r'async function finishAddAccount\([^)]*\)\s*\{(.*?)\n\}',
        app_js_content,
        re.DOTALL
    )
    assert finish_fn_match, "finishAddAccount function not found"
    finish_body = finish_fn_match.group(1)
    # Must contain profile_id in the payload
    assert "profile_id" in finish_body, (
        "GAP-2: finishAddAccount must include 'profile_id' in the add_account payload"
    )


@pytest.mark.unit
def test_tdd_wizard_step3_dynamic_roles_from_snapshot_routing(app_js_content):
    """TDD GAP-3: Wizard step 3 must NOT hardcode only 6 legacy role IDs.
    It must build role options from currentSnapshot.routing if snapshot agents exist.
    """
    # Find showWizardStep3 function
    step3_match = re.search(
        r'function showWizardStep3\([^)]*\)\s*\{(.*?)(?=\nfunction|\nconst|\nlet|\nvar|\n$)',
        app_js_content,
        re.DOTALL
    )
    assert step3_match, "showWizardStep3 function not found"
    step3_body = step3_match.group(1)

    # Must reference currentSnapshot.routing for dynamic role building
    assert "currentSnapshot.routing" in step3_body, (
        "GAP-3: showWizardStep3 must use currentSnapshot.routing to build role options dynamically"
    )

    # The dynamic branch (roleIds.length > 0) must NOT be the fallback hardcoded list.
    # Check that roleIds (from Object.keys(routing)) is used to build options dynamically.
    # The presence of "roleIds.map" or "Object.keys(routing)" indicates dynamic path.
    assert ("roleIds.map" in step3_body or "Object.keys" in step3_body), (
        "GAP-3: showWizardStep3 must use roleIds.map(...) to build options dynamically from currentSnapshot.routing"
    )


@pytest.mark.unit
def test_tdd_all_new_template_handlers_defined(app_js_content):
    """TDD GAP-4: All onclick/onchange in app.js template literals must have function definitions.
    After GAP-1/2/3 fixes, verify no new dangling handlers were introduced.
    """
    combined = app_js_content  # index.html already checked in existing test
    handler_pattern = re.compile(
        r'on(?:click|change|submit|input|keydown|keyup|dragstart|dragover|dragleave|drop|dragend)\s*=\s*["\'](?:return\s+)?([a-zA-Z0-9_$]+)\s*\(',
        re.IGNORECASE
    )
    used_handlers = set(handler_pattern.findall(combined))
    if not used_handlers:
        pytest.skip("No event handlers found in app.js template literals")
    missing = [h for h in sorted(used_handlers) if not _is_function_defined(app_js_content, h)]
    assert not missing, f"GAP-4: Handlers called in templates but missing definitions: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# TDD: P0-2b OpenRouter / NVIDIA wizard buttons
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_p0_2b_wizard_openrouter_button_exists(app_js_content):
    """P0-2b: showWizardStep1 must have onclick showWizardStep2('openrouter')."""
    assert "showWizardStep2('openrouter')" in app_js_content, (
        "P0-2b: showWizardStep1 is missing onclick showWizardStep2('openrouter') button"
    )


@pytest.mark.unit
def test_p0_2b_wizard_nvidia_button_exists(app_js_content):
    """P0-2b: showWizardStep1 must have onclick showWizardStep2('nvidia')."""
    assert "showWizardStep2('nvidia')" in app_js_content, (
        "P0-2b: showWizardStep1 is missing onclick showWizardStep2('nvidia') button"
    )


@pytest.mark.unit
def test_p0_2b_wizard_openrouter_step2_has_slot_and_base_url(app_js_content):
    """P0-2b: showWizardStep2('openrouter') must render slot picker + base URL input."""
    # The openrouter branch must use wiz-redirect-slot and wiz-base-url-input
    step2_match = re.search(
        r"function showWizardStep2\([^)]*\)\s*\{(.*?)(?=\nfunction|\nconst|\nlet|\nvar|\nasync function|\n$)",
        app_js_content,
        re.DOTALL
    )
    assert step2_match, "showWizardStep2 function not found"
    step2_body = step2_match.group(1)
    # Find the openrouter branch
    openrouter_branch = re.search(
        r"providerId\s*===\s*['\"]openrouter['\"]",
        step2_body
    )
    assert openrouter_branch, "showWizardStep2 has no openrouter branch"
    # The openrouter branch must have slot selector and base URL input
    openrouter_section = step2_body[openrouter_branch.start():]
    # Find the next provider branch or end
    next_branch = re.search(
        r"if\s*\(\s*providerId\s*===\s*['\"]",
        openrouter_section[20:]
    )
    openrouter_chunk = openrouter_section[:20 + next_branch.start()] if next_branch else openrouter_section[20:]
    assert "wiz-redirect-slot" in openrouter_chunk, (
        "P0-2b: openrouter branch must use wiz-redirect-slot for slot selection"
    )
    assert "wiz-base-url-input" in openrouter_chunk, (
        "P0-2b: openrouter branch must have wiz-base-url-input for optional base URL"
    )


@pytest.mark.unit
def test_p0_2b_wizard_nvidia_step2_has_slot_and_base_url(app_js_content):
    """P0-2b: showWizardStep2('nvidia') must render slot picker + base URL input."""
    step2_match = re.search(
        r"function showWizardStep2\([^)]*\)\s*\{(.*?)(?=\nfunction|\nconst|\nlet|\nvar|\nasync function|\n$)",
        app_js_content,
        re.DOTALL
    )
    assert step2_match, "showWizardStep2 function not found"
    step2_body = step2_match.group(1)
    # nvidia may be in a combined OR branch with openrouter, or standalone
    nvidia_branch = re.search(
        r"providerId\s*===\s*['\"]nvidia['\"]",
        step2_body
    )
    assert nvidia_branch, "showWizardStep2 has no nvidia branch"
    nvidia_section = step2_body[nvidia_branch.start():]
    next_branch = re.search(
        r"if\s*\(\s*providerId\s*===\s*['\"]",
        nvidia_section[20:]
    )
    nvidia_chunk = nvidia_section[:20 + next_branch.start()] if next_branch else nvidia_section[20:]
    assert "wiz-redirect-slot" in nvidia_chunk, (
        "P0-2b: nvidia branch must use wiz-redirect-slot for slot selection"
    )
    assert "wiz-base-url-input" in nvidia_chunk, (
        "P0-2b: nvidia branch must have wiz-base-url-input for optional base URL"
    )


@pytest.mark.unit
def test_p0_2b_proceedtostep3_sets_slot_for_openrouter_and_nvidia(app_js_content):
    """P0-2b: proceedToWizardStep3 must set window._wiz_device_profile for openrouter and nvidia."""
    proceed_match = re.search(
        r"function proceedToWizardStep3\([^)]*\)\s*\{(.*?)(?=\nfunction|\nasync function|\n$)",
        app_js_content,
        re.DOTALL
    )
    assert proceed_match, "proceedToWizardStep3 function not found"
    proceed_body = proceed_match.group(1)
    # openrouter and nvidia must be listed alongside antigravity/claude redirect-auth flow
    # so that window._wiz_device_profile is set before showWizardStep3
    assert "openrouter" in proceed_body, (
        "P0-2b: proceedToWizardStep3 must handle openrouter to persist slot selection"
    )
    assert "nvidia" in proceed_body, (
        "P0-2b: proceedToWizardStep3 must handle nvidia to persist slot selection"
    )


# ─────────────────────────────────────────────────────────────────────────────
# TDD: P0-3 Local LLM server discovery button in wizard step 2
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_p0_3_discover_local_models_action_referenced(app_js_content):
    """P0-3: discover_local_models action must be referenced in app.js."""
    assert "discover_local_models" in app_js_content, (
        "P0-3: discover_local_models action must be referenced in app.js"
    )


@pytest.mark.unit
def test_p0_3_discover_button_in_local_wizard_step2(app_js_content):
    """P0-3: showWizardStep2 local branch must have 'Найти на этом компьютере' button
    that calls discoverLocalServers or executeAction('discover_local_models')."""
    step2_match = re.search(
        r"function showWizardStep2\([^)]*\)\s*\{(.*?)(?=\nfunction|\nconst|\nlet|\nvar|\nasync function|\n$)",
        app_js_content,
        re.DOTALL
    )
    assert step2_match, "showWizardStep2 function not found"
    step2_body = step2_match.group(1)
    # Find the local provider branch
    local_branch = re.search(
        r"providerId\s*===\s*['\"]local['\"]",
        step2_body
    )
    assert local_branch, "showWizardStep2 has no local provider branch"
    local_section = step2_body[local_branch.start():]
    # Find the extent of this branch (until next major provider branch or end)
    next_branch = re.search(
        r"if\s*\(\s*providerId\s*===\s*['\"]",
        local_section[20:]
    )
    local_chunk = local_section[:20 + next_branch.start()] if next_branch else local_section[20:]
    # Must contain the discover button label
    assert "Найти на этом компьютере" in local_chunk, (
        "P0-3: local wizard step 2 must have 'Найти на этом компьютере' button"
    )
    # Must call discover_local_models
    assert "discover_local_models" in local_chunk, (
        "P0-3: local wizard step 2 must call discover_local_models action"
    )


@pytest.mark.unit
def test_p0_3_discover_fills_base_url_input(app_js_content):
    """P0-3: discovered servers list must fill wiz-base-url-input on selection."""
    # There must be a handler that sets wiz-base-url-input value from discovered server
    assert "wiz-base-url-input" in app_js_content, (
        "P0-3: wiz-base-url-input must be present for filling discovered server URL"
    )
    # The handler for discovered servers must reference both servers result and wiz-base-url-input
    # Look for a function that handles discover_local_models response
    discover_match = re.search(
        r"function\s+(\w*discover\w*)\s*\(",
        app_js_content,
        re.IGNORECASE
    )
    assert discover_match, "P0-3: no function handling discover_local_models response found"
    handler_name = discover_match.group(1)
    handler_match = re.search(
        rf"function\s+{re.escape(handler_name)}\s*\([^)]*\)\s*\{{(.*?)\n\}}",
        app_js_content,
        re.DOTALL
    )
    assert handler_match, f"handler {handler_name} body not found"
    handler_body = handler_match.group(1)
    assert "wiz-base-url-input" in handler_body, (
        "P0-3: discover handler must fill wiz-base-url-input with selected server URL"
    )
