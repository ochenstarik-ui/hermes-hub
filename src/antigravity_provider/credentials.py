from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def _default_credentials_path() -> Path:
    return _hermes_home() / ".antigravity_oauth.json"


class CredentialStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()

    @classmethod
    def default(cls) -> "CredentialStore":
        return cls(_default_credentials_path())

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def save(self, credentials: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent), text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=2, sort_keys=True)
                f.write("\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def delete(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _expiry_to_epoch(value: object) -> float | object:
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return value


def parse_agy_keychain_secret(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("go-keyring-base64:"):
        raw = base64.b64decode(raw.split(":", 1)[1]).decode("utf-8")
    data = json.loads(raw)
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, dict) or not token.get("access_token"):
        return {}
    return {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "expires_at": _expiry_to_epoch(token.get("expiry")),
        "token_type": token.get("token_type", "Bearer"),
        "source": "agy-keychain",
    }


def load_agy_keychain_credentials(*, runner: Callable[[], str] | None = None) -> dict[str, Any]:
    if runner is None and sys.platform != "darwin":
        return {}

    def default_runner() -> str:
        return subprocess.check_output(
            ["security", "find-generic-password", "-a", "antigravity", "-s", "gemini", "-w"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8")

    try:
        return parse_agy_keychain_secret((runner or default_runner)())
    except Exception:
        return {}
