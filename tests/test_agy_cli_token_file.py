"""agy 2.0 читает вход не из oauth_creds.json.

Сравнение рабочего профиля владельца с неработающим показало единственное
значимое различие: у рабочего есть `.gemini/antigravity-cli/antigravity-oauth-token`,
у неработающего — только `.gemini/oauth_creds.json`. Оба файла с токенами были
на месте и одинакового размера, но `agy models` отвечал «Please sign in to view
available models».

Формат подтверждён на машине владельца: верхний уровень — ключи `auth_method`
и `token`, значение `auth_method` — `consumer`.
"""
from __future__ import annotations

import json
import time

from antigravity_provider.router.profile_manager import ProfileAuthManager


def _write(tmp_path):
    return ProfileAuthManager.write_agy_oauth_creds(
        tmp_path,
        {
            "access_token": "ya29.TEST-ACCESS",
            "refresh_token": "1//TEST-REFRESH",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "token_type": "Bearer",
            "id_token": "eyJTEST",
            "expiry_date": int((time.time() + 3600) * 1000),
        },
    )


def test_antigravity_cli_token_written(tmp_path):
    _write(tmp_path)
    target = tmp_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    assert target.is_file(), "agy читает вход именно отсюда"

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert sorted(payload) == ["auth_method", "token"]
    assert payload["auth_method"] == "consumer"
    assert payload["token"]["access_token"] == "ya29.TEST-ACCESS"
    assert payload["token"]["refresh_token"] == "1//TEST-REFRESH"


def test_expiry_written_in_both_formats(tmp_path):
    _write(tmp_path)
    target = tmp_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    token = json.loads(target.read_text(encoding="utf-8"))["token"]
    # Node-формат — миллисекунды, Go-шный oauth2.Token — строка RFC3339.
    assert isinstance(token["expiry_date"], int)
    assert token["expiry"].endswith("Z")


def test_gemini_creds_still_written(tmp_path):
    """Прежний файл остаётся: его читают другие части agy и сам хаб."""
    target_file = _write(tmp_path)
    assert target_file == tmp_path / ".gemini" / "oauth_creds.json"
    creds = json.loads(target_file.read_text(encoding="utf-8"))
    assert creds["access_token"] == "ya29.TEST-ACCESS"
    assert "auth_method" not in creds


def test_auth_method_taken_from_working_neighbour(tmp_path):
    """Значение способа входа берётся у уже работающего профиля, если он есть."""
    neighbour = tmp_path / "ag-working" / ".gemini" / "antigravity-cli"
    neighbour.mkdir(parents=True)
    (neighbour / "antigravity-oauth-token").write_text(
        json.dumps({"auth_method": "workforce", "token": {}}), encoding="utf-8"
    )

    profile = tmp_path / "ag-new"
    profile.mkdir()
    _write(profile)

    payload = json.loads(
        (profile / ".gemini" / "antigravity-cli" / "antigravity-oauth-token").read_text(
            encoding="utf-8"
        )
    )
    assert payload["auth_method"] == "workforce"


def test_empty_login_writes_nothing(tmp_path):
    """Вход без токена не должен оставлять ни одного файла учётных данных."""
    try:
        ProfileAuthManager.write_agy_oauth_creds(tmp_path, {"email": "x@y.z"})
    except ValueError:
        pass
    else:  # pragma: no cover - защита от возврата прежнего поведения
        raise AssertionError("пустой вход обязан отказывать")

    assert not (tmp_path / ".gemini" / "oauth_creds.json").exists()
    assert not (
        tmp_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    ).exists()
