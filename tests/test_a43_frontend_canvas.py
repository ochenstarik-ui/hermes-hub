"""Automated tests for Task A43: Frontend Canvas and Brandbook Layouts."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "antigravity_provider" / "router" / "web" / "static"


def test_index_html_canvas_viewport_and_kpis():
    html_path = STATIC_DIR / "index.html"
    assert html_path.exists(), "index.html must exist"
    content = html_path.read_text(encoding="utf-8")

    # Fonts
    assert "Cinzel" in content, "Cinzel font must be linked in head"
    assert "Inter" in content, "Inter font must be linked in head"

    # Canvas Viewport
    assert 'id="workflow-viewport"' in content, "workflow-viewport wrapper must exist"
    assert 'id="workflow-edges"' in content
    assert 'id="workflow-node-layer"' in content

    # 6 KPIs
    assert 'id="workflow-kpi-active"' in content
    assert 'id="workflow-kpi-online"' in content
    assert 'id="workflow-kpi-latency"' in content
    assert 'id="workflow-kpi-tokens"' in content
    assert 'id="workflow-kpi-success"' in content
    assert 'id="workflow-kpi-status"' in content


def test_workflow_css_canvas_flexibility_and_viewport():
    css_path = STATIC_DIR / "workflow.css"
    assert css_path.exists(), "workflow.css must exist"
    content = css_path.read_text(encoding="utf-8")

    # Flexible canvas height (not locked at 430px)
    assert ".workflow-canvas" in content
    assert "height: 430px" not in content, "workflow-canvas must not have fixed 430px height"
    assert "min-height" in content

    # Viewport transform
    assert ".workflow-viewport" in content
    assert "transform-origin: 0 0" in content or "transform-origin:0 0" in content

    # 6 KPI columns
    assert "repeat(6" in content, "KPI grid must have 6 columns"


def test_workflow_js_pan_zoom_and_6_kpis():
    js_path = STATIC_DIR / "workflow.js"
    assert js_path.exists(), "workflow.js must exist"
    content = js_path.read_text(encoding="utf-8")

    # Pan and zoom state
    assert "panX:" in content or "panX =" in content
    assert "panY:" in content or "panY =" in content
    assert "isPanning" in content
    assert "updateCanvasTransform" in content

    # Wheel listener
    assert "addEventListener('wheel'" in content or 'addEventListener("wheel"' in content

    # Fit graph
    assert "function fitWorkflowGraph" in content

    # 6th KPI status
    assert "workflow-kpi-status" in content


def test_app_js_no_mock_numbers_and_all_views_defined():
    app_js_path = STATIC_DIR / "app.js"
    assert app_js_path.exists(), "app.js must exist"
    content = app_js_path.read_text(encoding="utf-8")

    # No hardcoded fake progress bars or mock dates in routing
    assert 'width:70%' not in content and 'width: 70%' not in content
    assert '26 авг.,' not in content

    # Views must be defined
    assert "function renderAnalyticsView" in content
    assert "function renderHealthView" in content
    assert "function renderLogsView" in content
    assert "function fetchLogs" in content
    assert "function renderLogsList" in content


def test_style_css_three_themes():
    css_path = STATIC_DIR / "style.css"
    assert css_path.exists(), "style.css must exist"
    content = css_path.read_text(encoding="utf-8")

    # Dark theme
    assert 'body[data-theme="dark"]' in content
    # Medium theme
    assert 'body[data-theme="medium"]' in content
    # Light theme
    assert 'body[data-theme="light"]' in content
