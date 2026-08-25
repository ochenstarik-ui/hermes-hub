"""
Hermes Hub — Web Client Invariants & Contract Verification Suite
Tests adherence to docs/web-api/CONTRACT.md and A16 requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "antigravity_provider" / "router" / "web" / "static"
SNAPSHOT_EXAMPLE = REPO_ROOT / "docs" / "web-api" / "snapshot.example.json"


def test_static_assets_exist_and_no_build_dependencies():
    """Verify that index.html, style.css, app.js exist and have zero build / npm dependencies."""
    index_html = STATIC_DIR / "index.html"
    style_css = STATIC_DIR / "style.css"
    app_js = STATIC_DIR / "app.js"

    assert index_html.is_file(), f"Missing {index_html}"
    assert style_css.is_file(), f"Missing {style_css}"
    assert app_js.is_file(), f"Missing {app_js}"

    html_content = index_html.read_text(encoding="utf-8")
    # No React, Webpack, Vite, npm or external bundle references
    assert "react" not in html_content.lower()
    assert "webpack" not in html_content.lower()
    assert "vite" not in html_content.lower()
    assert "<script src=\"app.js\"></script>" in html_content
    assert "<link rel=\"stylesheet\" href=\"style.css\">" in html_content


def test_snapshot_fixture_validity_and_completeness():
    """Verify snapshot.example.json conforms to HubSnapshot contract."""
    assert SNAPSHOT_EXAMPLE.is_file(), f"Missing {SNAPSHOT_EXAMPLE}"
    with open(SNAPSHOT_EXAMPLE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Top level keys
    required_keys = [
        "generation", "seq", "timestamp", "profiles_by_provider",
        "all_profiles", "readiness", "agents", "providers",
        "routing", "quotas", "metrics", "is_stale"
    ]
    for key in required_keys:
        assert key in data, f"Missing required top-level key: {key}"

    # Verify monotonic seq structure
    assert isinstance(data["seq"], int)
    assert data["seq"] >= 1

    # Verify profiles count
    assert len(data["all_profiles"]) >= 16, "Must contain real profiles fixture"

    # Zero leaked tokens / secrets in snapshot
    raw_text = json.dumps(data)
    forbidden_tokens = ["access_token", "refresh_token", "api_key", "client_secret"]
    for tok in forbidden_tokens:
        # Key shouldn't exist as actual secret payload
        assert f'"{tok}": "sk-' not in raw_text
        assert f'"{tok}": "gho_' not in raw_text


def test_monotonic_seq_logic_in_app_js():
    """Verify app.js contains strict monotonic seq checking to prevent stale response overwrites."""
    app_js_content = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "lastAppliedSeq" in app_js_content
    assert "snapshot.seq < lastAppliedSeq" in app_js_content
    assert "Stale snapshot" in app_js_content


def test_account_card_compact_height_and_quota_rendering():
    """Verify CSS has 164px compact fixed height and app.js renders multi-pool quota cells."""
    style_css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert "164px" in style_css
    assert ".account-card" in style_css
    assert "overflow: hidden" in style_css

    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "renderQuotaCell" in app_js
    assert "remaining_percent" in app_js
    assert "unavailable_reason" in app_js
    assert "Н/Д" in app_js


def test_headless_server_auth_matrix():
    """Клиент не должен показывать выдуманные коды и зашитые адреса провайдеров.

    Раньше этот тест ТРЕБОВАЛ наличия "https://x.ai/device" в коде — то есть
    закреплял дефект как требование. Адрес отдаёт 404, а рядом стояли
    выдуманные коды устройства GRK-7842 и CDX-9104: мастер не был подключён к
    серверу, и пользователь вводил бы несуществующий код бесконечно.
    Настоящие адрес и код выдаёт провайдер в ответе device-flow.
    """
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    for fake in ("GRK-7842", "CDX-9104"):
        assert app_js.count(fake) <= 1, (
            f"выдуманный код устройства {fake} снова показывается пользователю"
        )

    for line in app_js.splitlines():
        if line.lstrip().startswith("//"):
            continue
        assert "x.ai/device" not in line, (
            "зашитый адрес x.ai/device вернулся в интерфейс; он отдаёт 404, "
            "настоящий приходит от провайдера в verification_uri"
        )

    # Раньше здесь требовалось слово "Headless": мастер писал, что на сервере
    # без экрана вход невозможен, и отправлял в консоль по SSH. Утверждение
    # оказалось ложным — сервер принимает вставленное вручную значение
    # (handle_manual_callback_url и handle_auth_code), поэтому браузер нужен
    # где угодно, а не на машине с Hub. Требовать это предупреждение значило
    # защищать заглушку, как прежде защищался адрес x.ai/device.
    # Проверяем текст, который видит владелец, а не комментарии в коде:
    # история дефекта описана рядом и содержит то же слово.
    for line in app_js.splitlines():
        if line.lstrip().startswith("//"):
            continue
        assert "невозможна" not in line, (
            "вернулось утверждение, что вход через веб невозможен; "
            "вход по вставленной ссылке поддержан сервером"
        )
    for needed in ("startRedirectAuth", "submit_redirect_callback"):
        assert needed in app_js, f"нет настоящего потока входа по ссылке: {needed}"
    # Требование упоминать консоль agy — остаток той же заглушки: вход больше
    # не идёт через консоль, поэтому отсылать к ней значит вводить в
    # заблуждение. Вместо этого проверяем, что владельцу сказано главное —
    # ссылку можно открыть на любой машине.
    assert "на любой машине" in app_js, (
        "не сказано, что ссылку авторизации можно открыть на другой машине"
    )
    assert "launcher/main.py" not in app_js, "инструкция ведёт на несуществующий файл"


def test_actions_contract_handling():
    """Verify POST /api/action handles ok: false as valid 200 business response and displays feedback in-place."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "POST" in app_js
    assert "/api/action" in app_js
    assert "executeAction" in app_js
    assert "modal-feedback-area" in app_js


def test_client_distinguishes_loading_from_missing_data():
    """Загрузка не должна выглядеть как отсутствие данных.

    Опрос провайдера идёт в фоне и занимает секунды. Пока он не завершился,
    корзины квот пусты. Клиент показывал в этот момент «Н/Д» — то же самое,
    что при подключённом аккаунте без лимитов, — и владелец решил, что
    лимиты не подтягиваются вовсе. Сервер отдаёт признак is_loading;
    клиент обязан его учитывать.
    """
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert "is_loading" in app_js, "клиент игнорирует признак загрузки из снапшота"
    assert "Загрузка" in app_js, "нет отдельного текста для состояния загрузки"

    # Причина отказа важнее флага: если провайдер уже ответил «лимитов не
    # даю», это не загрузка, и показывать «Загрузка…» бесконечно нельзя.
    assert "!unavailableReason" in app_js or "! unavailableReason" in app_js, (
        "состояние загрузки не подавляется при известной причине отказа"
    )
