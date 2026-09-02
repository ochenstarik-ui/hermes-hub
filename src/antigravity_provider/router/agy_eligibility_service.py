"""Hermes Hub — Antigravity CLI (agy) Eligibility State Detection Service.

Provides 100% read-only analysis of the agy binary machine code to determine whether
the region eligibility check is active, removed (patched by owner), or undetermined.
Strictly NEVER modifies or writes to executable files, and NEVER downloads external code.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from antigravity_provider.agy_subprocess import (
    build_safe_subprocess_env,
    get_agy_exe,
    hidden_process_kwargs,
)
from antigravity_provider.router.event_bus import (
    EVENT_AGY_ELIGIBILITY_CHANGED,
    EventBus,
)
from antigravity_provider.router.settings_service import get_hub_settings
from antigravity_provider.router.unified_health import EventLogService

logger = logging.getLogger("hermes.router.agy_eligibility")

STATUS_CHECK_REMOVED = "check_removed"
STATUS_CHECK_ACTIVE = "check_active"
STATUS_UNKNOWN = "unknown"

# ── Machine Code Signatures ──────────────────────────────────────────
# x86-64 Original:
#   test rax,rax ; je eligible ; cmp byte[rax+8],0 ; jne eligible ; call failure
#   cmp byte[rax+8], 0 is \x80\x78\x08\x00
X86_ORIG_SHORT = re.compile(rb"\x48\x85\xc0\x74.\x80\x78\x08\x00\x75.", re.DOTALL)
X86_ORIG_NEAR = re.compile(rb"\x48\x85\xc0\x0f\x84....\x80\x78\x08\x00\x0f\x85....", re.DOTALL)
X86_ORIG_STANDALONE = re.compile(rb"\x80\x78\x08\x00", re.DOTALL)

# x86-64 Patched:
#   test rax,rax ; je eligible ; test rax,rax ; nop ; jne eligible
#   test rax,rax ; nop is \x48\x85\xc0\x90
X86_PATCH_SHORT = re.compile(rb"\x48\x85\xc0\x74.\x48\x85\xc0\x90\x75.", re.DOTALL)
X86_PATCH_NEAR = re.compile(rb"\x48\x85\xc0\x0f\x84....\x48\x85\xc0\x90\x0f\x85....", re.DOTALL)

# arm64 Original & Patched signatures
# In Go arm64, struct field [X0, #8] access followed by conditional branch:
# LDRB Wn, [X0, #8] -> \x0n\x20\x40\x39
ARM64_ORIG_PATTERN = re.compile(rb"[\x00-\x1f]\x20\x40\x39", re.DOTALL)
# Patched replaces LDRB / branch with NOP (\x1f\x20\x03\xd5) or MOV X0, X0 (\xe0\x03\x00\xaa)
ARM64_PATCH_PATTERN = re.compile(rb"\x1f\x20\x03\xd5", re.DOTALL)


class AgyEligibilityService:
    """Thread-safe, read-only analyzer of agy CLI binary eligibility check status."""

    _instance: Optional[AgyEligibilityService] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cached_state: Optional[Dict[str, Any]] = None
        self._last_binary_path: Optional[str] = None
        self._last_mtime: float = -1.0
        self._last_sha256: Optional[str] = None
        self._last_status: Optional[str] = None
        self._last_status_label: Optional[str] = None
        self._last_version: Optional[str] = None

    @classmethod
    def get(cls) -> AgyEligibilityService:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def invalidate_cache(self) -> None:
        """Clear cached eligibility state to force re-reading binary on next check."""
        with self._lock:
            self._cached_state = None
            self._last_mtime = -1.0

    def _extract_version(self, exe_path: str) -> str:
        """Truthfully extract version from agy executable."""
        try:
            res = subprocess.run(
                [exe_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
                env=build_safe_subprocess_env(),
                **hidden_process_kwargs(),
            )
            raw = res.stdout.strip() or res.stderr.strip()
            if raw:
                # E.g. "1.1.23" or "Antigravity CLI 1.1.23"
                m = re.search(r"(\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?|\d+\.\d+)", raw)
                if m:
                    return m.group(1)
                return raw.splitlines()[0][:50]
        except Exception as exc:
            logger.debug("Could not run agy --version: %s", exc)
        return "Н/Д (не удалось определить версию)"

    def _analyze_binary_bytes(self, data: bytes) -> Tuple[str, str, str]:
        """Analyze binary machine code bytes.

        Returns:
            (status, status_label_ru, detail_ru)
        """
        # 1. Check for patched x86-64 signature
        if X86_PATCH_SHORT.search(data) or X86_PATCH_NEAR.search(data):
            return (
                STATUS_CHECK_REMOVED,
                "Проверка снята",
                "Патч начальной проверки доступности активен. Ветвление направлено в разрешённый режим.",
            )

        # 2. Check for original x86-64 signature
        if X86_ORIG_SHORT.search(data) or X86_ORIG_NEAR.search(data):
            return (
                STATUS_CHECK_ACTIVE,
                "Проверка на месте",
                "Проверка доступности Antigravity активна. Аккаунт может отклоняться Google по региону. Примените патч или настройте прокси.",
            )

        # 3. Check for arm64 patched / orig if context matches
        if ARM64_PATCH_PATTERN.search(data) and b"EPD_ELIGIBILITY" in data:
            if not ARM64_ORIG_PATTERN.search(data):
                return (
                    STATUS_CHECK_REMOVED,
                    "Проверка снята",
                    "Патч начальной проверки доступности (ARM64) активен.",
                )

        if ARM64_ORIG_PATTERN.search(data) and b"EPD_ELIGIBILITY" in data:
            return (
                STATUS_CHECK_ACTIVE,
                "Проверка на месте",
                "Проверка доступности Antigravity (ARM64) активна. Аккаунт может отклоняться Google по региону.",
            )

        # 4. Unknown / Unsupported
        return (
            STATUS_UNKNOWN,
            "Н/Д: сигнатура проверки не найдена",
            "Сигнатура проверки доступности не найдена в бинарнике (возможно, неподдерживаемая версия agy).",
        )

    def check_eligibility_state(
        self,
        force: bool = False,
        custom_binary_path: Optional[str | Path] = None,
    ) -> Dict[str, Any]:
        """Perform 100% read-only evaluation of agy binary eligibility state.

        Guarantees:
        - NEVER writes to or alters the executable file.
        - Calculates SHA-256 before and after evaluation.
        - Emits EventBus event and EventLogService audit record upon state transitions.
        """
        with self._lock:
            # Resolve binary path
            if custom_binary_path:
                exe_path_str = str(custom_binary_path)
            else:
                try:
                    exe_path_str = get_agy_exe()
                except Exception as exc:
                    exe_path_str = ""
                    error_msg = str(exc)

            settings = get_hub_settings()
            patch_script_path = settings.get("agy_patch_script_path", "").strip()

            if not exe_path_str:
                state = {
                    "status": STATUS_UNKNOWN,
                    "status_label_ru": "Н/Д: исполняемый файл agy не найден",
                    "detail_ru": f"Утилита agy не обнаружена в системе: {error_msg if 'error_msg' in locals() else 'путь не найден'}",
                    "version": "Н/Д",
                    "binary_path": "",
                    "binary_sha256": "",
                    "binary_size_bytes": 0,
                    "checked_at": time.time(),
                    "patch_script_path": patch_script_path,
                }
                self._cached_state = state
                return dict(state)

            p = Path(exe_path_str)
            if not p.is_file():
                state = {
                    "status": STATUS_UNKNOWN,
                    "status_label_ru": "Н/Д: файл не найден",
                    "detail_ru": f"Файл {p} не существует или не является файлом",
                    "version": "Н/Д",
                    "binary_path": str(p),
                    "binary_sha256": "",
                    "binary_size_bytes": 0,
                    "checked_at": time.time(),
                    "patch_script_path": patch_script_path,
                }
                self._cached_state = state
                return dict(state)

            try:
                stat = p.stat()
                mtime = stat.st_mtime
                size = stat.st_size
            except OSError as exc:
                state = {
                    "status": STATUS_UNKNOWN,
                    "status_label_ru": f"Н/Д: нет доступа к файлу ({exc.strerror or exc})",
                    "detail_ru": f"Не удалось прочитать атрибуты файла {p}: {exc}",
                    "version": "Н/Д",
                    "binary_path": str(p),
                    "binary_sha256": "",
                    "binary_size_bytes": 0,
                    "checked_at": time.time(),
                    "patch_script_path": patch_script_path,
                }
                self._cached_state = state
                return dict(state)

            # Return cached state if nothing changed and not forced
            if (
                not force
                and self._cached_state is not None
                and self._last_binary_path == str(p)
                and self._last_mtime == mtime
            ):
                # Update patch_script_path if settings changed
                self._cached_state["patch_script_path"] = patch_script_path
                return dict(self._cached_state)

            # Read-only binary read and hash computation
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except OSError as exc:
                state = {
                    "status": STATUS_UNKNOWN,
                    "status_label_ru": f"Н/Д: ошибка чтения файла ({exc.strerror or exc})",
                    "detail_ru": f"Не удалось прочитать бинарный файл {p}: {exc}",
                    "version": "Н/Д",
                    "binary_path": str(p),
                    "binary_sha256": "",
                    "binary_size_bytes": size,
                    "checked_at": time.time(),
                    "patch_script_path": patch_script_path,
                }
                self._cached_state = state
                return dict(state)

            sha256_hash = hashlib.sha256(data).hexdigest()
            status, status_label_ru, detail_ru = self._analyze_binary_bytes(data)

            # Extract version
            version = self._extract_version(str(p))

            state = {
                "status": status,
                "status_label_ru": status_label_ru,
                "detail_ru": detail_ru,
                "version": version,
                "binary_path": str(p),
                "binary_sha256": sha256_hash,
                "binary_size_bytes": len(data),
                "checked_at": time.time(),
                "patch_script_path": patch_script_path,
            }

            # Detect state transition and emit notifications (P0-3)
            previous_status = self._last_status
            previous_label = self._last_status_label or previous_status or "Н/Д"
            previous_sha = self._last_sha256

            if previous_status is not None and previous_status != status:
                logger.info(
                    "AGY eligibility state changed: %s -> %s (sha256: %s)",
                    previous_status,
                    status,
                    sha256_hash[:12],
                )
                EventBus.get().publish(EVENT_AGY_ELIGIBILITY_CHANGED, dict(state))

                level = "warning" if status == STATUS_CHECK_ACTIVE else "info"
                EventLogService.get().log(
                    category="security",
                    message=(
                        f"Состояние проверки доступности agy изменилось: "
                        f"{previous_label} → {status_label_ru}"
                    ),
                    details=f"Исполняемый файл: {p} (SHA-256: {sha256_hash[:16]}..., Версия: {version})",
                    level=level,
                    actor="system",
                    action="agy_eligibility_change",
                    target_profile="antigravity",
                    outcome="success",
                )
            elif previous_sha is not None and previous_sha != sha256_hash:
                logger.info("AGY binary hash changed: %s -> %s", previous_sha[:12], sha256_hash[:12])
                EventLogService.get().log(
                    category="system",
                    message=f"Обнаружено изменение исполняемого файла agy (SHA-256: {sha256_hash[:16]}..., статус: {status_label_ru})",
                    level="info",
                    actor="system",
                    action="agy_binary_updated",
                    target_profile="antigravity",
                )

            self._last_binary_path = str(p)
            self._last_mtime = mtime
            self._last_sha256 = sha256_hash
            self._last_status = status
            self._last_status_label = status_label_ru
            self._last_version = version
            self._cached_state = state

            return dict(state)
