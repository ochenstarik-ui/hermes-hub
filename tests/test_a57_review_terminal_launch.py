"""Проверки по итогам разбора A57 ревьюером.

Мастер сообщал «Терминал запущен (/usr/bin/x-terminal-emulator) для слота
ag-6», а окна не появлялось. На сервере владельца в это время висел
`[xfce4-terminal] <defunct>` — терминал стартовал и немедленно умирал.

Причин три, и каждая проверяется здесь.

1. `x-terminal-emulator` на Ubuntu указывает на `xfce4-terminal.wrapper`, а
   xfce4-terminal держит один процесс на сеанс: новый вызов передаёт задание
   работающему экземпляру и завершается. Нужен `--disable-server`.
2. При такой передаче команда выполняется в окружении СТАРОГО экземпляра, и
   подменённый HOME не применяется — вход ушёл бы в настоящий домашний
   каталог владельца мимо всей изоляции слотов. Поэтому окружение задаёт сам
   сценарий, а не наследование.
3. С ключом -e окно закрывается вместе с командой, и причину отказа прочесть
   нельзя. Сценарий ждёт нажатия клавиши.

И отдельно: возврат Popen ничего не говорит об открытии окна.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from antigravity_provider import agy_subprocess
from antigravity_provider.agy_subprocess import (
    find_terminal_emulator,
    write_login_helper,
)


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(agy_subprocess, "_is_windows", lambda: False)
    monkeypatch.setenv("DISPLAY", ":0")


def _only(available: set[str]):
    def _which(name):
        return f"/usr/bin/{name}" if name in available else None

    return _which


# ── Сценарий входа ──

def test_helper_sets_environment_itself(tmp_path):
    helper = write_login_helper(tmp_path, "/usr/local/bin/agy", "ag-6")
    body = helper.read_text(encoding="utf-8")

    assert "HOME=" in body and str(tmp_path) in body
    assert "export HOME" in body
    assert "/usr/local/bin/agy" in body


def test_helper_keeps_the_window_open(tmp_path):
    body = write_login_helper(tmp_path, "/usr/local/bin/agy", "ag-6").read_text(encoding="utf-8")

    assert "read " in body, "иначе окно исчезнет вместе с agy и причина отказа пропадёт"
    assert "$status" in body, "код возврата agy должен быть виден владельцу"


def test_helper_contains_no_secrets(tmp_path):
    body = write_login_helper(tmp_path, "/usr/local/bin/agy", "ag-6").read_text(encoding="utf-8").lower()

    for forbidden in ("access_token", "refresh_token", "api_key", "bearer", "ya29."):
        assert forbidden not in body


# ── Выбор эмулятора ──

def test_xfce4_terminal_gets_disable_server(linux, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", _only({"xfce4-terminal", "x-terminal-emulator"}))

    cmd, err, _ = find_terminal_emulator("ag-6", "/usr/local/bin/agy", tmp_path)

    assert err is None
    assert cmd[0] == "/usr/bin/xfce4-terminal"
    assert "--disable-server" in cmd, (
        "без этого вызов уходит работающему экземпляру и окно не открывается"
    )


def test_alternatives_wrapper_is_the_last_resort(linux, monkeypatch, tmp_path):
    """x-terminal-emulator — обёртка над альтернативами, лишний слой."""
    monkeypatch.setattr(shutil, "which", _only({"x-terminal-emulator", "xterm"}))

    cmd, err, _ = find_terminal_emulator("ag-6", "/usr/local/bin/agy", tmp_path)

    assert err is None
    assert cmd[0] == "/usr/bin/xterm"


def test_terminal_discovery_creates_nothing(linux, monkeypatch, tmp_path):
    """Поиск терминала — запрос, а не действие: файлов после него не остаётся."""
    monkeypatch.setattr(shutil, "which", _only({"xterm"}))

    cmd, err, _ = find_terminal_emulator("ag-6", "/путь/к/запуску", tmp_path)

    assert err is None
    assert "/путь/к/запуску" in cmd
    assert not (tmp_path / ".hermes-agy-login.sh").exists()


def test_missing_terminal_lists_what_was_checked(linux, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", _only(set()))

    cmd, err, checked = find_terminal_emulator("ag-6", "/usr/local/bin/agy", tmp_path)

    assert cmd is None
    assert err
    assert len(checked) >= 5
    assert any("xterm" in item for item in checked)


# ── Запуск подтверждается, а не объявляется ──

def test_immediate_exit_is_reported_as_failure(linux, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", _only({"xterm"}))
    monkeypatch.setattr(agy_subprocess.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        agy_subprocess, "get_agy_exe", lambda: "/usr/local/bin/agy", raising=False
    )

    class _DeadProcess:
        def __init__(self, *a, **k):
            pass

        def poll(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", _DeadProcess)

    ok, msg, data = agy_subprocess.start_native_agy_login(profile_id="ag-6", force=True)

    assert ok is False
    assert "окно не открылось" in msg
    assert data.get("exit_code") == 1


# ── Пустые слоты появлялись сами ──

def test_asking_for_a_path_creates_nothing(tmp_path, monkeypatch):
    """У владельца накопилось 25 каталогов профилей при единицах заведённых.

    Причина: get_profile_dir создавал каталог при каждом обращении, а в коде
    зашит список «стандартных» слотов — ag-orch-primary, ag-orch-fallback,
    ag-1..ag-20, ag-w1..ag-w10. Любой обход этого списка материализовал их все.
    Спросить, где профиль жил бы, и завести его — разные действия.
    """
    from antigravity_provider import paths

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    root = tmp_path / "agy_profiles"

    for pid in ("ag-orch-primary", "ag-w7", "ag-19", "ag-cold-3"):
        paths.get_profile_dir(pid, "antigravity")

    assert not root.exists() or not any(root.iterdir()), (
        "запрос пути не должен оставлять каталоги на диске"
    )

    created = paths.get_profile_dir("ag-1", "antigravity", create=True)
    assert created.is_dir()
    assert sorted(p.name for p in root.iterdir()) == ["ag-1"]


# ── Дисплей ищется не только в окружении ──

def test_display_from_environment_wins(monkeypatch):
    from antigravity_provider.agy_subprocess import detect_graphical_session

    monkeypatch.setenv("DISPLAY", ":0")
    found, checked = detect_graphical_session()

    assert found["DISPLAY"] == ":0"
    assert any("DISPLAY (задан: :0)" in item for item in checked)


def test_display_is_asked_from_systemd_when_environment_is_empty(monkeypatch):
    """Хаб запускается через nohup: по SSH он остаётся без DISPLAY.

    Измерено на сервере владельца: loginctl show-user даёт сеанс c1, а
    show-session c1 — Type=x11, Display=:10. Отказываться, не спросив, рано.
    """
    from antigravity_provider import agy_subprocess as m

    for var in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("USER", "ochenstarik")
    monkeypatch.setattr(m.shutil, "which", lambda n: "/usr/bin/loginctl" if n == "loginctl" else None)

    answers = {("show-user", "ochenstarik"): "c1", ("show-session", "c1", "Type"): "x11",
               ("show-session", "c1", "Display"): ":10"}

    class _Res:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    def _run(cmd, **kwargs):
        if cmd[1] == "show-user":
            return _Res(answers[("show-user", cmd[2])])
        return _Res(answers[("show-session", cmd[2], cmd[-1])])

    monkeypatch.setattr(m.subprocess, "run", _run)
    found, checked = m.detect_graphical_session()

    assert found == {"DISPLAY": ":10"}
    assert any("loginctl сеанс c1" in item for item in checked)


def test_wayland_session_is_reported_as_wayland(monkeypatch):
    from antigravity_provider import agy_subprocess as m

    for var in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("USER", "owner")
    monkeypatch.setattr(m.shutil, "which", lambda n: "/usr/bin/loginctl" if n == "loginctl" else None)

    class _Res:
        def __init__(self, out):
            self.stdout, self.returncode = out, 0

    def _run(cmd, **kwargs):
        if cmd[1] == "show-user":
            return _Res("2")
        return _Res("wayland" if cmd[-1] == "Type" else "wayland-0")

    monkeypatch.setattr(m.subprocess, "run", _run)
    found, _ = m.detect_graphical_session()

    assert found == {"WAYLAND_DISPLAY": "wayland-0"}


def test_no_session_anywhere_lists_what_was_asked(monkeypatch):
    from antigravity_provider import agy_subprocess as m

    for var in ("DISPLAY", "WAYLAND_DISPLAY", "MIR_SOCKET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(m.shutil, "which", lambda _n: None)

    found, checked = m.detect_graphical_session()

    assert found == {}
    assert any("loginctl (не найден)" in item for item in checked)
