"""Hermes Hub — Preflight Dependency & Readiness Check Service (Dependency Agent).

Performs comprehensive zero-quota preflight validation of local environment, CLI tools,
Python dependencies, local inference endpoints, role chain credentials, and disk permissions.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from antigravity_provider import paths
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.router_config import load_router_config

logger = logging.getLogger("hermes.router.preflight")


@dataclass
class PreflightItem:
    check_id: str
    name: str
    status: str  # "PASS" | "FAIL" | "WARN"
    message: str
    remediation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightReport:
    success: bool
    passed_count: int
    failed_count: int
    warn_count: int
    checks: List[PreflightItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "warn_count": self.warn_count,
            "checks": [c.to_dict() for c in self.checks],
        }


class PreflightCheckService:
    """Zero-quota dependency and readiness inspection service."""

    _instance: Optional[PreflightCheckService] = None

    @classmethod
    def get(cls) -> PreflightCheckService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def check_cli_dependencies(self) -> List[PreflightItem]:
        """Check for external CLI executables and critical Python packages."""
        items: List[PreflightItem] = []

        # 1. Antigravity CLI (agy)
        agy_path = shutil.which("agy") or shutil.which("agy.exe")
        if agy_path:
            items.append(
                PreflightItem(
                    check_id="cli_agy",
                    name="CLI Antigravity (agy)",
                    status="PASS",
                    message=f"Исполняемый файл agy найден: {agy_path}",
                )
            )
        else:
            items.append(
                PreflightItem(
                    check_id="cli_agy",
                    name="CLI Antigravity (agy)",
                    status="WARN",
                    message="Утилита 'agy' не найдена в системном PATH.",
                    remediation="Установите agy CLI или добавьте каталог установки в системную переменную PATH.",
                )
            )

        # 2. Python package: fastapi
        fastapi_spec = importlib.util.find_spec("fastapi")
        if fastapi_spec is not None:
            items.append(
                PreflightItem(
                    check_id="pkg_fastapi",
                    name="Библиотека FastAPI",
                    status="PASS",
                    message="Пакет fastapi успешно импортируется в окружении.",
                )
            )
        else:
            items.append(
                PreflightItem(
                    check_id="pkg_fastapi",
                    name="Библиотека FastAPI",
                    status="FAIL",
                    message="Пакет 'fastapi' не установлен в текущем Python окружении.",
                    remediation="Выполните 'pip install fastapi' для работы веб-интерфейса и REST API.",
                )
            )

        # 3. Python package: uvicorn
        uvicorn_spec = importlib.util.find_spec("uvicorn")
        if uvicorn_spec is not None:
            items.append(
                PreflightItem(
                    check_id="pkg_uvicorn",
                    name="Библиотека Uvicorn",
                    status="PASS",
                    message="Пакет uvicorn успешно импортируется в окружении.",
                )
            )
        else:
            items.append(
                PreflightItem(
                    check_id="pkg_uvicorn",
                    name="Библиотека Uvicorn",
                    status="FAIL",
                    message="Пакет 'uvicorn' не установлен в текущем Python окружении.",
                    remediation="Выполните 'pip install uvicorn' для запуска веб-сервера.",
                )
            )

        return items

    def check_local_servers(self) -> List[PreflightItem]:
        """Poll {base_url}/models with 2.0s timeout for active local provider profiles."""
        items: List[PreflightItem] = []
        config = load_router_config()
        local_profiles = [p for p in config.profiles.values() if p.provider == "local" and p.enabled]

        if not local_profiles:
            items.append(
                PreflightItem(
                    check_id="local_servers_none",
                    name="Локальные серверы LLM",
                    status="PASS",
                    message="Активные локальные профили (llama.cpp/vLLM) не настроены.",
                )
            )
            return items

        from antigravity_provider.router.adapters.local_adapter import LocalLLMAdapter

        adapter = LocalLLMAdapter()

        for pcfg in local_profiles:
            base_url = adapter._resolve_base_url(pcfg)
            api_key = adapter._resolve_api_key(pcfg)
            headers = {"Accept": "application/json", "User-Agent": "hermes-preflight/1.0"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            models_url = f"{base_url}/models"
            try:
                req = urllib.request.Request(models_url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status in (200, 204):
                        items.append(
                            PreflightItem(
                                check_id=f"local_srv_{pcfg.profile_id}",
                                name=f"Локальный сервер {pcfg.profile_id} ({base_url})",
                                status="PASS",
                                message=f"Локальный сервер доступен (HTTP {resp.status}).",
                            )
                        )
                    else:
                        items.append(
                            PreflightItem(
                                check_id=f"local_srv_{pcfg.profile_id}",
                                name=f"Локальный сервер {pcfg.profile_id} ({base_url})",
                                status="FAIL",
                                message=f"Сервер вернул неожиданный статус HTTP {resp.status}",
                                remediation=f"Проверьте настройки и логи сервера {base_url}.",
                            )
                        )
            except urllib.error.HTTPError as http_err:
                items.append(
                    PreflightItem(
                        check_id=f"local_srv_{pcfg.profile_id}",
                        name=f"Локальный сервер {pcfg.profile_id} ({base_url})",
                        status="FAIL",
                        message=f"HTTP ошибка при обращении к {models_url}: {http_err.code} {http_err.reason}",
                        remediation=f"Убедитесь, что сервер на {base_url} поддерживает OpenAI-совместимый эндпоинт /v1/models.",
                    )
                )
            except Exception as exc:
                items.append(
                    PreflightItem(
                        check_id=f"local_srv_{pcfg.profile_id}",
                        name=f"Локальный сервер {pcfg.profile_id} ({base_url})",
                        status="FAIL",
                        message=f"Не удалось подключиться к {base_url}: {exc}",
                        remediation=f"Запустите локальный сервер llama.cpp / vLLM / Ollama по адресу {base_url}.",
                    )
                )

        return items

    def check_auth_credentials(self) -> List[PreflightItem]:
        """Verify credential presence for all profiles referenced in active role chains.

        ZERO QUOTA BURN: Only inspects local auth files and keyring status. Never calls paid APIs.
        """
        items: List[PreflightItem] = []
        config = load_router_config()

        # Collect all profile IDs in active role chains
        referenced_pids: set[str] = set()
        for role_policy in config.roles.values():
            for pid in role_policy.preferred_chain:
                referenced_pids.add(pid)

        if not referenced_pids:
            items.append(
                PreflightItem(
                    check_id="auth_chains_empty",
                    name="Учетные данные цепочек ролей",
                    status="WARN",
                    message="В активных ролях не настроены цепочки профилей.",
                    remediation="Настройте цепочки профилей в разделе Маршрутизация.",
                )
            )
            return items

        for pid in sorted(referenced_pids):
            pcfg = config.get_profile(pid)
            if not pcfg:
                items.append(
                    PreflightItem(
                        check_id=f"auth_{pid}",
                        name=f"Профиль {pid}",
                        status="FAIL",
                        message=f"Профиль '{pid}' указан в цепочке роли, но отсутствует в конфигурации.",
                        remediation=f"Удалите '{pid}' из цепочки роли или настройте профиль в router_profiles.yaml.",
                    )
                )
                continue

            status = ProfileAuthManager.get_profile_status(pcfg.provider, pid)
            is_authenticated = status.get("authenticated", False)
            is_expired = status.get("is_expired", False) or status.get("expired", False) or status.get("status") == "EXPIRED"

            if is_authenticated and not is_expired:
                items.append(
                    PreflightItem(
                        check_id=f"auth_{pid}",
                        name=f"Авторизация {pid} ({pcfg.provider})",
                        status="PASS",
                        message="Учетные данные действительны и сохранены локально.",
                    )
                )
            elif is_expired:
                items.append(
                    PreflightItem(
                        check_id=f"auth_{pid}",
                        name=f"Авторизация {pid} ({pcfg.provider})",
                        status="FAIL",
                        message=f"Срок действия авторизации для профиля '{pid}' истек.",
                        remediation=f"Выполните повторный вход для профиля {pid} в разделе Аккаунты.",
                    )
                )
            else:
                items.append(
                    PreflightItem(
                        check_id=f"auth_{pid}",
                        name=f"Авторизация {pid} ({pcfg.provider})",
                        status="FAIL",
                        message=f"Учетные данные для профиля '{pid}' ({pcfg.provider}) не найдены.",
                        remediation=f"Подключите профиль {pid} через кнопку 'Добавить аккаунт' или 'hermes router login'.",
                    )
                )

        return items

    def check_system_environment(self) -> List[PreflightItem]:
        """Verify HERMES_HOME presence and read/write permissions for config and logs."""
        items: List[PreflightItem] = []

        # 1. HERMES_HOME directory
        try:
            home_dir = paths.get_hermes_home()
            if home_dir.is_dir():
                items.append(
                    PreflightItem(
                        check_id="env_hermes_home",
                        name="Каталог HERMES_HOME",
                        status="PASS",
                        message=f"Каталог существует: {home_dir}",
                    )
                )
            else:
                items.append(
                    PreflightItem(
                        check_id="env_hermes_home",
                        name="Каталог HERMES_HOME",
                        status="FAIL",
                        message=f"Каталог {home_dir} не существует или не является директорией.",
                        remediation="Проверьте права доступа и создайте каталог HERMES_HOME.",
                    )
                )
        except Exception as exc:
            items.append(
                PreflightItem(
                    check_id="env_hermes_home",
                    name="Каталог HERMES_HOME",
                    status="FAIL",
                    message=f"Ошибка доступа к HERMES_HOME: {exc}",
                    remediation="Убедитесь, что переменная HERMES_HOME указывает на корректный доступный путь.",
                )
            )

        # 2. Config Directory Write Test
        try:
            config_dir = paths.get_config_dir()
            test_file = config_dir / f".preflight_probe_{os.getpid()}.tmp"
            test_file.write_text("probe", encoding="utf-8")
            test_file.unlink()
            items.append(
                PreflightItem(
                    check_id="env_config_writable",
                    name="Права на запись в каталог конфигурации",
                    status="PASS",
                    message=f"Права на запись в {config_dir} подтверждены.",
                )
            )
        except Exception as exc:
            items.append(
                PreflightItem(
                    check_id="env_config_writable",
                    name="Права на запись в каталог конфигурации",
                    status="FAIL",
                    message=f"Нет прав на запись в {paths.get_config_dir()}: {exc}",
                    remediation="Предоставьте текущему пользователю права на запись в каталог конфигурации.",
                )
            )

        # 3. Logs Directory Write Test
        try:
            logs_dir = paths.get_logs_dir()
            test_file = logs_dir / f".preflight_probe_{os.getpid()}.tmp"
            test_file.write_text("probe", encoding="utf-8")
            test_file.unlink()
            items.append(
                PreflightItem(
                    check_id="env_logs_writable",
                    name="Права на запись в каталог логов",
                    status="PASS",
                    message=f"Права на запись в {logs_dir} подтверждены.",
                )
            )
        except Exception as exc:
            items.append(
                PreflightItem(
                    check_id="env_logs_writable",
                    name="Права на запись в каталог логов",
                    status="FAIL",
                    message=f"Нет прав на запись в {paths.get_logs_dir()}: {exc}",
                    remediation="Предоставьте текущему пользователю права на запись в каталог логов.",
                )
            )

        return items

    def run_all_checks(self) -> PreflightReport:
        """Run all readiness checks and return aggregated PreflightReport."""
        all_items: List[PreflightItem] = []
        all_items.extend(self.check_cli_dependencies())
        all_items.extend(self.check_system_environment())
        all_items.extend(self.check_auth_credentials())
        all_items.extend(self.check_local_servers())

        passed = sum(1 for item in all_items if item.status == "PASS")
        failed = sum(1 for item in all_items if item.status == "FAIL")
        warn = sum(1 for item in all_items if item.status == "WARN")

        return PreflightReport(
            success=(failed == 0),
            passed_count=passed,
            failed_count=failed,
            warn_count=warn,
            checks=all_items,
        )
