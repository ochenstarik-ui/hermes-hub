"""Обход проверки доступности по стране — через прокси, а не патч бинарника.

Вход владельца через терминал прошёл: agy запустился в изолированном каталоге и
опознал аккаунт. Отказал Google: «Eligibility check failed: Your current account
is not eligible for Antigravity, because it is not currently available in your
location». Проверка смотрит на адрес выхода.

Правильный ответ — выйти через разрешённую страну. У владельца несколько узлов
в разных странах, поэтому адрес задаётся и общий, и на каждый профиль отдельно.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from antigravity_provider.agy_subprocess import (
    proxy_env_overrides,
    resolve_provider_proxy,
    write_login_helper,
)
from antigravity_provider.router.settings_service import _normalize_proxy_url


@pytest.mark.parametrize(
    "given, expected",
    [
        ("socks5://127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("127.0.0.1:1080", "socks5://127.0.0.1:1080"),
        ("http://proxy.example.com:8080", "http://proxy.example.com:8080"),
        ("socks5h://10.0.0.5:1080", "socks5h://10.0.0.5:1080"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_valid_addresses_are_kept(given, expected):
    assert _normalize_proxy_url(given) == expected


@pytest.mark.parametrize(
    "junk",
    ["мусор!!", "не адрес вовсе", "ftp://1.2.3.4:21", "socks5://1.2.3.4:99999", "://"],
)
def test_junk_is_rejected_not_dressed_up_with_a_scheme(junk):
    """Приписать socks5:// можно чему угодно.

    Если бы мусор проходил, он выглядел бы принятым, а все обращения провайдера
    молча ломались бы без внятной причины.
    """
    assert _normalize_proxy_url(junk) == ""


def test_env_covers_upper_lower_and_socks():
    env = proxy_env_overrides("socks5://127.0.0.1:1080")

    # Go читает HTTPS_PROXY, curl и многие библиотеки — https_proxy,
    # ALL_PROXY нужен для socks5.
    assert set(env) == {
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    }
    assert set(env.values()) == {"socks5://127.0.0.1:1080"}


def test_no_proxy_means_no_variables():
    assert proxy_env_overrides("") == {}
    assert proxy_env_overrides("   ") == {}


def test_profile_address_wins_over_the_common_one():
    """Узлы в разных странах: разным аккаунтам может требоваться разный выход."""
    with patch(
        "antigravity_provider.router.profile_manager.ProfileAuthManager.load_profile_auth",
        return_value={"proxy_url": "socks5://nl.example:1080"},
    ), patch(
        "antigravity_provider.router.settings_service.get_hub_settings",
        return_value={"provider_proxy_url": "socks5://de.example:1080"},
    ):
        assert resolve_provider_proxy("ag-1") == "socks5://nl.example:1080"


def test_common_address_is_used_when_profile_has_none():
    with patch(
        "antigravity_provider.router.profile_manager.ProfileAuthManager.load_profile_auth",
        return_value={},
    ), patch(
        "antigravity_provider.router.settings_service.get_hub_settings",
        return_value={"provider_proxy_url": "socks5://de.example:1080"},
    ):
        assert resolve_provider_proxy("ag-1") == "socks5://de.example:1080"


def test_login_script_exports_the_proxy(tmp_path):
    with patch(
        "antigravity_provider.agy_subprocess.resolve_provider_proxy",
        return_value="socks5://127.0.0.1:1080",
    ):
        body = write_login_helper(tmp_path, "/usr/local/bin/agy", "ag-1").read_text(
            encoding="utf-8"
        )

    assert "HTTPS_PROXY=" in body
    assert "export " in body and "ALL_PROXY" in body
    assert "socks5://127.0.0.1:1080" in body


def test_login_script_without_proxy_mentions_none(tmp_path):
    with patch("antigravity_provider.agy_subprocess.resolve_provider_proxy", return_value=""):
        body = write_login_helper(tmp_path, "/usr/local/bin/agy", "ag-1").read_text(
            encoding="utf-8"
        )

    assert "PROXY" not in body
