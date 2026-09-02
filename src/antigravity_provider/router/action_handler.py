import csv
import io
import time
import json
import os
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional, Callable, List

from antigravity_provider.router.router_config import load_router_config, save_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.scheduler import HermesRefreshScheduler
from antigravity_provider.updater import UpdateManager
from antigravity_provider import paths
from antigravity_provider.router.adapters import get_adapter

logger = logging.getLogger('hermes.router.actions')
_test_locks_guard = threading.Lock()
_test_locks: dict[str, Any] = {}

def do_set_main(provider: str, profile_id: str) -> Tuple[bool, str]:
    ok, msg = ProfileAuthManager.set_main_profile(provider, profile_id)
    if ok:
        EventLogService.get().log(
            'account', f'Профиль {profile_id} назначен основным аккаунтом Hermes ({provider}).', level='info'
        )
    return ok, msg

def do_set_orchestrator(profile_id: str) -> Tuple[bool, str]:
    ok, msg = AutoAssigner.set_primary_orchestrator(profile_id)
    if ok:
        EventLogService.get().log(
            'routing', f'Профиль {profile_id} назначен главным оркестратором команды.', level='info'
        )
    return ok, msg

def do_test_profile(provider: str, profile_id: str, timeout: float = 10.0, discovered_models: Optional[List[str]] = None) -> Dict[str, Any]:
    valid, reason = AutoAssigner.validate_slot(provider, profile_id)
    if not valid:
        return {"success": False, "error": reason}
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        AutoAssigner.ensure_profile_definition(provider, profile_id)
        config = load_router_config()
        pcfg = config.get_profile(profile_id)
    if not pcfg:
        return {'success': False, 'error': f"Профиль '{profile_id}' не найден"}

    status = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
    if status.get('is_expired') or status.get('expired') or status.get('status') == 'EXPIRED':
        return {'success': False, 'error': 'Авторизация истекла, требуется повторный вход.'}

    if not status.get('authenticated'):
        return {'success': False, 'error': 'Аккаунт не добавлен. Сначала выполните подключение.'}

    candidates = discovered_models if discovered_models is not None else pcfg.preferred_models
    if not candidates:
        return {'success': False, 'error': 'Сервер отвечает, но доступных моделей для тестового запроса нет' if discovered_models == [] else 'Каталог моделей не получен; сначала запросите список моделей'}
    model = next((model for model in pcfg.preferred_models if model in candidates), candidates[0])
    t0 = time.time()
    try:
        auth_data = ProfileAuthManager.load_profile_auth(pcfg.provider, profile_id)
        if not auth_data and pcfg.provider != 'antigravity':
            return {'success': False, 'error': 'Локальные данные авторизации не найдены'}
        adapter = get_adapter(pcfg.provider)
        
        req = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1
        }
        
        import threading
        result_container = []
        error_container = []
        
        with _test_locks_guard:
            invoke_lock = _test_locks.setdefault(profile_id, threading.Lock())
        if not invoke_lock.acquire(blocking=False):
            return {'success': False, 'error': 'Предыдущий запрос этого аккаунта ещё не завершился'}

        def _call_invoke():
            try:
                result_container.append(adapter.invoke(pcfg, req))
            except Exception as e:
                error_container.append(e)
            finally:
                invoke_lock.release()
                
        t = threading.Thread(target=_call_invoke, daemon=True)
        try:
            t.start()
        except Exception:
            invoke_lock.release()
            raise
        t.join(timeout=timeout)
        
        el = round(time.time() - t0, 2)
        
        if t.is_alive():
            return {
                'success': False,
                'duration_sec': el,
                'error': f'Превышено время ожидания ответа от провайдера ({timeout:g}с). Повторите проверку.',
            }
            
        if error_container:
            raise error_container[0]
            
        from .health_tracker import HealthTracker
        ht = HealthTracker()
        ht.mark_success(profile_id, model)
        
        EventLogService.get().log(
            'system', f'Успешная проверка подключения {profile_id} ({model}) за {el}s.', level='success'
        )
        return {
            'success': True,
            'model': model,
            'duration_sec': el,
            'response': 'Авторизация подтверждена, ответ провайдера получен',
        }
    except Exception as e:
        EventLogService.get().log('system', f'Сбой проверки {profile_id} ({model}): {e}', level='error')
        return {'success': False, 'model': model, 'duration_sec': round(time.time() - t0, 2), 'error': str(e).strip() or type(e).__name__}

def do_delete_credentials(provider: str, profile_id: str, actor: str = "system") -> Tuple[bool, str]:
    # Сигнатура get_profile_dir — (profile_id, provider), а здесь её звали
    # наоборот. Внутри есть костыль, молча исправляющий перестановку, но только
    # для antigravity, openai-codex и opencode-go. Для grok, claude и local путь
    # получался неверным, файл «не находился», и кнопка удаления РАПОРТОВАЛА
    # УСПЕХ, ничего не удалив. Используем готовый помощник, который берёт
    # аргументы в правильном порядке.
    from antigravity_provider.router.profile_manager import get_profile_auth_path

    auth_p = get_profile_auth_path(provider, profile_id)
    if auth_p.is_file():
        try:
            auth_p.unlink()
            from .state_store import HubStateStore
            from antigravity_provider.router.quota_collector import AccountQuotaService
            AccountQuotaService.get().forget_profile(provider, profile_id)
            HubStateStore.get().apply_delta_account_removed(provider, profile_id)
            EventLogService.get().log(
                'account',
                f'Учетные данные для {profile_id} удалены.',
                level='warning',
                actor=actor,
                action='delete_credentials',
                target_profile=profile_id,
                outcome='success',
            )
            return True, f"Учетные данные для '{profile_id}' удалены"
        except Exception as e:
            EventLogService.get().log(
                'account',
                f'Ошибка удаления учётных данных {profile_id}: {e}',
                level='error',
                actor=actor,
                action='delete_credentials',
                target_profile=profile_id,
                outcome='failed',
            )
            return False, f'Ошибка удаления: {e}'
    # Отсутствие файла — это не успех удаления. Раньше такой ответ выглядел
    # для пользователя как «сработало», хотя аккаунт оставался подключённым.
    return False, f"Учетных данных для '{profile_id}' не найдено — удалять нечего"

def do_save_settings(settings: Dict[str, Any]) -> Tuple[bool, str]:
    if "obsidian_vault_path" in settings:
        from antigravity_provider.router.settings_service import validate_obsidian_vault_path
        val_ok, val_msg, _ = validate_obsidian_vault_path(settings["obsidian_vault_path"])
        if not val_ok:
            return False, f"Ошибка настройки хранилища Obsidian: {val_msg}"

    settings_file = paths.get_hermes_home() / "hub_settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if settings_file.exists():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update(settings)
    try:
        # Запись через временный файл и os.replace: обрыв на середине не
        # должен оставить настройки битыми. В домашнем каталоге Hermes уже
        # лежит config.yaml.corrupt.<дата>.bak — этот риск не теоретический.
        temp_file = settings_file.with_suffix(".json.tmp")
        temp_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_file, settings_file)
    except Exception as e:
        return False, f"Не удалось сохранить настройки: {e}"

    from antigravity_provider.router.settings_service import invalidate_settings_cache
    invalidate_settings_cache()

    try:
        from antigravity_provider.router.router_config import load_router_config, save_router_config
        rcfg = load_router_config()
        updated_rcfg = False
        if "quota_threshold_percent" in settings:
            rcfg.quota_threshold_percent = float(settings["quota_threshold_percent"])
            updated_rcfg = True
        if "quota_threshold_action" in settings:
            rcfg.quota_threshold_action = str(settings["quota_threshold_action"])
            updated_rcfg = True
        if updated_rcfg:
            save_router_config(rcfg)
    except Exception:
        pass

    try:
        from antigravity_provider.router.state_store import HubStateStore
        HubStateStore.get().refresh(force_scan=True)
    except Exception:
        pass

    from antigravity_provider.router.quota_collector import AccountQuotaService

    AccountQuotaService.get().set_refresh_interval(int(settings.get("quota_refresh_interval_sec", 300)))
    return True, "Настройки сохранены"
 
 
def _model_matches_discovered(model: str, discovered: list[str]) -> bool:
    if model in discovered:
        return True
    model_short = model.split("/")[-1]
    for d in discovered:
        if d == model or d == model_short:
            return True
        d_short = d.split("/")[-1]
        if d_short == model or d_short == model_short:
            return True
        if d.startswith(model + "-") or d.startswith(model + ":"):
            return True
        if d_short.startswith(model_short + "-") or d_short.startswith(model_short + ":"):
            return True
        import re
        d_base = re.sub(r"-(high|medium|low|none|thought|thinking)(?:-(high|medium|low|none))?$", "", d_short)
        model_base = re.sub(r"-(high|medium|low|none|thought|thinking)(?:-(high|medium|low|none))?$", "", model_short)
        if d_base == model_short or d_base == model_base or d_short == model_base:
            return True
    return False


def do_set_model(profile_id: str, model: str, role_id: Optional[str] = None) -> Tuple[bool, str]:
    if not model or not str(model).strip() or str(model).strip() == "Список моделей ещё не получен":
        return False, "Не указана модель для установки"
    model = str(model).strip()

    config = load_router_config()
    if not profile_id and role_id:
        role = config.roles.get(role_id)
        if role and role.preferred_chain:
            profile_id = role.preferred_chain[0]

    if not profile_id or profile_id not in config.profiles:
        return False, f"Профиль '{profile_id}' не найден в конфигурации"

    pcfg = config.profiles[profile_id]
    provider = pcfg.provider

    from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
    from antigravity_provider.router.model_registry import ModelRegistry

    discovered = ModelDiscoveryService.get().get_models_with_metadata(provider, profile_id).get("models") or ModelDiscoveryService.get().get_models(provider)
    if discovered is None:
        try:
            discovered = ModelDiscoveryService.get().discover_models_sync(provider, timeout=5.0)
        except Exception:
            discovered = None

    canonical = [m.model_id for m in ModelRegistry.get().list_models(provider=provider)]
    canonical_short = [m.split("/")[-1] for m in canonical]

    is_canonical = (
        model in canonical
        or model in canonical_short
        or _model_matches_discovered(model, canonical)
    )

    if not discovered:
        if not is_canonical:
            return False, f"Кэш моделей для провайдера '{provider}' пуст, а модель '{model}' не найдена в списке известных моделей."
    else:
        matches_discovered = _model_matches_discovered(model, discovered)
        if not matches_discovered and not is_canonical:
            return False, f"Модель '{model}' отсутствует в списке обнаруженных моделей провайдера '{provider}'"

    updated = load_router_config()
    target = updated.profiles[profile_id]
    target.preferred_models = [model] + [m for m in target.preferred_models if m != model]
    updated.profiles[profile_id] = target

    if role_id and role_id in updated.roles:
        updated.roles[role_id].default_model = model

    if save_router_config(updated):
        from .state_store import HubStateStore
        HubStateStore.get().apply_delta_profile_preferences(profile_id, target.preferred_models)
        EventLogService.get().log(
            "model", f"Для профиля {profile_id} ({provider}) установлена модель '{model}'.", level="info"
        )
        return True, f"Модель '{model}' успешно сохранена для профиля {profile_id}"
    return False, "Не удалось сохранить файл конфигурации"


def do_save_request_options(profile_id: str, request_options: Any) -> Tuple[bool, str]:
    if not profile_id or not str(profile_id).strip():
        return False, "Не указан идентификатор профиля"

    if isinstance(request_options, str):
        try:
            request_options = json.loads(request_options)
        except Exception as exc:
            return False, f"Некорректный JSON параметров запроса: {exc}"

    if not isinstance(request_options, dict):
        return False, "Параметры запроса должны быть объектом (словарём)"

    cfg = load_router_config()
    if profile_id not in cfg.profiles:
        return False, f"Профиль '{profile_id}' не найден в конфигурации"

    pcfg = cfg.profiles[profile_id]
    pcfg.request_options = request_options
    cfg.profiles[profile_id] = pcfg

    if save_router_config(cfg):
        try:
            from antigravity_provider.router.state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
        except Exception:
            pass
        EventLogService.get().log(
            "account",
            f"Параметры запроса для профиля {profile_id} ({pcfg.provider}) сохранены.",
            level="info",
        )
        return True, f"Параметры запроса для профиля {profile_id} успешно сохранены"
    return False, "Не удалось сохранить файл конфигурации"


# Подключённый аккаунт обязан появиться в списке сразу.
#
# Учётные данные сохраняются на диск, но состояние профилей берётся из кэша
# UnifiedHealthService, а фоновый цикл веб-сервера обновляет снапшот с
# force_scan=False, то есть кэш не трогает. Проверено исполнением: после входа
# профиль оставался not_configured и при обычном refresh, и переходил в
# not_tested только при force_scan=True. Владелец видел «аккаунт подключён» и
# пустой список аккаунтов.
#
# Функция объявлена на уровне модуля намеренно: как вложенная она была видна
# не всем точкам завершения входа, и device-flow получал NameError внутри
# обработки успеха.
def _rescan_after_auth(provider=None, profile_id=None) -> None:
    def refresh():
        try:
            from .state_store import HubStateStore
            from .account_probe_service import AccountProbeService
            if provider and profile_id:
                HubStateStore.get().apply_delta_account_added(provider, profile_id)
            else:
                HubStateStore.get().refresh(force_scan=True)
                AccountProbeService.get().schedule_all()
        except Exception as exc:
            logger.warning("Не удалось обновить состояние после входа: %s", exc)
    threading.Thread(target=refresh, name="auth-state-refresh", daemon=True).start()


def generate_quotas_export(format: str = "json") -> Any:
    """Generate comprehensive limits and quotas export across all providers and profiles."""
    from antigravity_provider.router.quota_collector import AccountQuotaService
    config = load_router_config()
    quota_service = AccountQuotaService.get()

    profiles_data: List[Dict[str, Any]] = []
    flat_rows: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Sort profiles by provider then profile_id
    sorted_profiles = sorted(config.profiles.values(), key=lambda p: (p.provider, p.profile_id))

    for pcfg in sorted_profiles:
        prov = pcfg.provider
        pid = pcfg.profile_id

        status = ProfileAuthManager.get_profile_status(prov, pid)
        is_auth = bool(status.get("authenticated"))
        identity = quota_service.get_identity(prov, pid)
        quota_snap = quota_service.get_snapshot(prov, pid)

        plan_name = identity.plan.display_name if (identity and identity.plan) else "UNKNOWN"
        ident_str = identity.primary_identifier() if identity else pid

        buckets_list: List[Dict[str, Any]] = []
        source = quota_snap.source if quota_snap else "unconfigured"
        fetched_at = quota_snap.fetched_at.isoformat() if (quota_snap and quota_snap.fetched_at) else now_iso
        unavail = quota_snap.unavailable_reason if quota_snap else None

        if quota_snap and quota_snap.buckets:
            for b in quota_snap.buckets:
                b_dict = {
                    "id": b.id,
                    "name": b.display_name,
                    "model_family": b.model_family,
                    "period": b.period,
                    "used_percent": b.used_percent,
                    "remaining_percent": b.remaining_percent,
                    "used_absolute": b.used_absolute,
                    "remaining_absolute": b.remaining_absolute,
                    "limit_absolute": b.limit_absolute,
                    "reset_at": b.reset_at.isoformat() if b.reset_at else None,
                    "reset_in_seconds": b.reset_in_seconds,
                    "reset_formatted": b.formatted_reset(),
                    "status": b.status,
                    "formatted_remaining": b.formatted_remaining(),
                }
                buckets_list.append(b_dict)
                flat_rows.append({
                    "provider": prov,
                    "profile_id": pid,
                    "identity": ident_str,
                    "plan": plan_name,
                    "auth_status": "AUTHENTICATED" if is_auth else "UNCONFIGURED",
                    "bucket_id": b.id,
                    "bucket_name": b.display_name,
                    "model_family": b.model_family or "",
                    "period": b.period or "",
                    "remaining_percent": f"{b.remaining_percent:.1f}%" if b.remaining_percent is not None else "",
                    "used_percent": f"{b.used_percent:.1f}%" if b.used_percent is not None else "",
                    "remaining_absolute": b.remaining_absolute if b.remaining_absolute is not None else "",
                    "limit_absolute": b.limit_absolute if b.limit_absolute is not None else "",
                    "status": b.status,
                    "reset_at": b.reset_at.isoformat() if b.reset_at else "",
                    "reset_formatted": b.formatted_reset() or "",
                    "formatted_remaining": b.formatted_remaining(),
                    "source": source,
                    "fetched_at": fetched_at,
                })
        else:
            flat_rows.append({
                "provider": prov,
                "profile_id": pid,
                "identity": ident_str,
                "plan": plan_name,
                "auth_status": "AUTHENTICATED" if is_auth else "UNCONFIGURED",
                "bucket_id": "",
                "bucket_name": "",
                "model_family": "",
                "period": "",
                "remaining_percent": "",
                "used_percent": "",
                "remaining_absolute": "",
                "limit_absolute": "",
                "status": "unconfigured" if not is_auth else "unknown",
                "reset_at": "",
                "reset_formatted": "",
                "formatted_remaining": unavail or ("Аккаунт не подключён" if not is_auth else "Н/Д"),
                "source": source,
                "fetched_at": fetched_at,
            })

        profiles_data.append({
            "provider": prov,
            "profile_id": pid,
            "display_name": getattr(pcfg, "display_name", None) or (identity.display_name if identity else None) or pid,
            "identity": ident_str,
            "plan": plan_name,
            "authenticated": is_auth,
            "auth_status": "AUTHENTICATED" if is_auth else "UNCONFIGURED",
            "source": source,
            "fetched_at": fetched_at,
            "unavailable_reason": unavail,
            "buckets": buckets_list,
        })

    if format.lower().strip() == "csv":
        output = io.StringIO()
        fieldnames = [
            "provider", "profile_id", "identity", "plan", "auth_status",
            "bucket_id", "bucket_name", "model_family", "period",
            "remaining_percent", "used_percent", "remaining_absolute", "limit_absolute",
            "status", "reset_at", "reset_formatted", "formatted_remaining",
            "source", "fetched_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in flat_rows:
            writer.writerow(row)
        return output.getvalue()

    return {
        "exported_at": now_iso,
        "total_profiles": len(profiles_data),
        "profiles": profiles_data,
        "rows": flat_rows,
    }


def do_reset_router_config(actor: str = "user:web") -> Dict[str, Any]:
    """Reset router configuration to clean default state (0 profiles, 13 canonical roles with empty chains).

    Guaranteed to create a timestamped backup of router_profiles.yaml first.
    Strictly preserves all credentials in ~/.hermes/agy_profiles, codex_profiles,
    opengo_profiles, claude_profiles, grok_profiles, and hub_settings.json.
    """
    import shutil
    from pathlib import Path
    from antigravity_provider.router.router_config import (
        get_default_router_config,
        save_router_config,
    )

    env_config = os.environ.get("HERMES_ROUTER_CONFIG", "").strip()
    if env_config:
        config_path = Path(env_config).expanduser()
    else:
        config_path = paths.get_router_profiles_path()

    backup_name = None
    if config_path.exists():
        try:
            backup_path = config_path.with_name(f"{config_path.name}.bak_{int(time.time())}")
            shutil.copy2(config_path, backup_path)
            backup_name = backup_path.name
        except Exception as exc:
            logger.warning("Не удалось создать резервную копию перед сбросом конфигурации: %s", exc)

    clean_cfg = get_default_router_config()
    saved = save_router_config(clean_cfg, config_path)
    if not saved:
        return {
            "ok": False,
            "message": "Не удалось записать чистую конфигурацию в файл",
        }

    try:
        from antigravity_provider.router.state_store import HubStateStore
        HubStateStore.get().refresh(force_scan=True)
    except Exception:
        pass

    EventLogService.get().log(
        "routing",
        f"Конфигурация маршрутизатора сброшена в исходное состояние (резервная копия: {backup_name or 'нет'}). Учётные данные и подключенные аккаунты сохранены.",
        level="warning",
        actor=actor,
        action="reset_router_config",
        outcome="success",
    )

    return {
        "ok": True,
        "message": "Конфигурация маршрутизатора сброшена. Учётные данные и подключенные аккаунты сохранены.",
        "backup_file": backup_name,
    }


class ActionExecutor:
    """Shared execution layer for Desktop and Web actions."""
    
    _connect_lock = threading.Lock()
    _pending_connections: Dict[str, str] = {}

    @classmethod
    def execute(cls, action: str, data: Dict[str, Any], async_runner: Optional[Callable] = None, actor: str = "user:web") -> Dict[str, Any]:
        if action != "add_account":
            return cls._execute(action, data, async_runner, actor)
        import hashlib
        from .account_probe_service import AccountProbeService
        fingerprint = hashlib.sha256(json.dumps([
            data.get("provider"), data.get("token") or data.get("api_key"), data.get("base_url")
        ]).encode()).hexdigest()
        with cls._connect_lock:
            cls._pending_connections = {key: pid for key, pid in cls._pending_connections.items() if AccountProbeService.get().state(pid).get("state") == "checking"}
            previous = cls._pending_connections.get(fingerprint)
            if previous and AccountProbeService.get().state(previous).get("state") == "checking":
                return {"ok": False, "message": f"Аккаунт {previous} уже сохранён и проверяется. Дождитесь результата."}
            result = cls._execute(action, data, async_runner, actor)
            if result.get("ok"):
                cls._pending_connections[fingerprint] = result["data"]["profile_id"]
            return result

    @classmethod
    def _execute(cls, action: str, data: Dict[str, Any], async_runner: Optional[Callable] = None, actor: str = "user:web") -> Dict[str, Any]:
        """
        Execute the specified action.
        If async_runner is provided, long actions will be dispatched to it.
        async_runner should accept (func, name).
        """
        pid = data.get('profile_id', '')
        prov = data.get('provider', '')
        # Провайдер часто не передают: веб-клиент шлёт только profile_id, и
        # раньше удаление из-за этого искало файл не в том каталоге и отвечало
        # «удалять нечего». Идентификатор профиля однозначен — берём провайдера
        # из конфигурации, чтобы работал любой вызывающий.
        if not prov and pid:
            try:
                _pcfg = load_router_config().get_profile(pid)
                if _pcfg:
                    prov = _pcfg.provider
            except Exception:
                pass
            if not prov:
                for prefix, p_name in [
                    ("ag-", "antigravity"),
                    ("codex-", "openai-codex"),
                    ("opengo-", "opencode-go"),
                    ("claude-", "claude"),
                    ("grok-", "grok"),
                    ("local-", "local"),
                    ("openrouter-", "openrouter"),
                    ("nvidia-", "nvidia"),
                    ("ollama-", "ollama"),
                    ("vllm-", "vllm"),
                ]:
                    if pid.startswith(prefix):
                        prov = p_name
                        break
            if not prov:
                from antigravity_provider.router.profile_manager import get_profile_auth_path
                for candidate_prov in ("antigravity", "openai-codex", "opencode-go", "claude", "grok", "local", "openrouter", "nvidia", "ollama", "vllm"):
                    if get_profile_auth_path(candidate_prov, pid).is_file():
                        prov = candidate_prov
                        break

        if action in {
            'create_agent',
            'update_agent',
            'delete_agent',
            'read_agent_file',
            'save_agent_file',
            'save_workflow',
            'start_workflow',
            'stop_workflow',
        }:
            try:
                from antigravity_provider.router.workflow_service import execute_workflow_action

                return execute_workflow_action(action, data)
            except (ValueError, OSError) as exc:
                return {'ok': False, 'message': str(exc)}

        # Device-flow для Grok и Codex через веб. Backend был готов давно, но
        # наружу не выведен: веб-мастер показывал заглушку «не реализовано», и
        # подключить эти провайдеры можно было только из десктопа. Настоящие
        # адрес и код выдаёт провайдер — интерфейс их только отображает.
        if action == 'start_device_auth':
            provider = (data.get('provider') or '').strip().lower()
            slot = data.get('profile_id') or AutoAssigner.find_free_slot(provider)
            if not slot:
                return {'ok': False, 'message': f'Нет свободного слота для провайдера {provider}'}
            valid, reason = AutoAssigner.validate_slot(provider, slot)
            if not valid:
                return {'ok': False, 'message': reason}
            try:
                if provider == 'grok':
                    from antigravity_provider.router.grok_oauth import start_grok_oauth

                    session_id, url, code = start_grok_oauth(slot)
                elif provider in ('openai-codex', 'codex'):
                    from antigravity_provider.router.codex_oauth import start_codex_oauth

                    session_id, url, code = start_codex_oauth(slot)
                else:
                    return {'ok': False, 'message': f'Провайдер {provider} не использует код устройства'}
            except Exception as exc:
                return {'ok': False, 'message': f'Не удалось начать авторизацию: {exc}'}

            if not code:
                return {'ok': False, 'message': 'Провайдер не выдал код устройства'}
            return {
                'ok': True,
                'message': 'Код устройства получен',
                'data': {'session_id': session_id, 'url': url, 'code': code, 'profile_id': slot},
            }

        if action == 'poll_device_auth':
            provider = (data.get('provider') or '').strip().lower()
            session_id = data.get('session_id') or ''
            if provider == 'grok':
                from antigravity_provider.router.grok_oauth import get_grok_oauth_session

                session = get_grok_oauth_session(session_id)
            elif provider in ('openai-codex', 'codex'):
                from antigravity_provider.router.codex_oauth import get_codex_oauth_session

                session = get_codex_oauth_session(session_id)
            else:
                return {'ok': False, 'message': f'Провайдер {provider} не использует код устройства'}

            if session is None:
                return {'ok': False, 'message': 'Сессия авторизации не найдена или истекла'}

            status = getattr(session, 'status', 'unknown')
            if status == 'completed':
                _rescan_after_auth()
                return {'ok': True, 'message': 'Аккаунт подключён', 'data': {'status': status}}
            if status in ('failed', 'timeout'):
                reason = getattr(session, 'error_msg', None) or 'Авторизация не завершена'
                return {'ok': False, 'message': reason, 'data': {'status': status}}
            return {'ok': True, 'message': 'Ожидание подтверждения', 'data': {'status': status}}

        if action == 'probe_account_models':
            # Определение доступных аккаунту моделей. Запускается только по
            # явному действию владельца: каталог NVIDIA публичный и о правах
            # аккаунта ничего не сообщает, поэтому доступность выясняется
            # опросом, а он тратит вызовы и упирается в ограничения частоты.
            from .model_entitlements import probe_account_models, load_entitlements
            from .model_discovery_service import ModelDiscoveryService

            pid = data.get('profile_id') or ''
            prov_norm = (prov or data.get('provider') or '').strip().lower()
            if not pid or not prov_norm:
                return {'ok': False, 'message': 'Не указан профиль или провайдер'}

            if data.get('cached_only'):
                cached = load_entitlements(prov_norm, pid)
                if not cached:
                    return {'ok': True, 'message': 'Н/Д: доступность моделей ещё не определялась', 'data': {}}
                return {'ok': True, 'message': 'Сохранённый результат', 'data': cached}

            auth = ProfileAuthManager.load_profile_auth(prov_norm, pid) or {}
            token = (auth.get('api_key') or auth.get('token') or '').strip()
            if not token:
                return {'ok': False, 'message': f'У профиля {pid} нет сохранённого API-ключа'}

            pcfg = load_router_config().get_profile(pid)
            base_url = (getattr(pcfg, 'custom_base_url', None) or auth.get('base_url') or '').strip()
            if not base_url:
                base_url = 'https://integrate.api.nvidia.com/v1' if prov_norm.startswith('nvidia') else ''
            if not base_url:
                return {'ok': False, 'message': f'Не известен адрес провайдера для {pid}'}

            models = ModelDiscoveryService.get().get_models(prov_norm) or []
            if not models:
                return {'ok': False, 'message': 'Каталог моделей ещё не получен — сначала запросите список'}

            res = probe_account_models(prov_norm, pid, token, base_url, models)
            d = res.to_dict()
            msg = (
                f"Доступно {len(res.available)} из {d['total']}; "
                f"не выдано {len(res.unavailable)}; "
                f"не определено {len(res.undetermined)}"
            )
            return {'ok': True, 'message': msg, 'data': d}

        if action == 'validate_connection':
            from .connection_preflight import validate_connection
            return validate_connection(prov, data.get('token') or data.get('api_key') or '', data.get('base_url') or '', data.get('preferred_model') or '')

        # Подключение аккаунта: сохранение профиля и учетных данных (P0-1)
        if action == 'add_account':
            prov_norm = (prov or data.get('provider') or '').strip().lower()
            if not prov_norm:
                return {'ok': False, 'message': 'Провайдер не указан'}

            if prov_norm in ('google-antigravity', 'agy'):
                prov_norm = 'antigravity'
            elif prov_norm in ('codex', 'openai'):
                prov_norm = 'openai-codex'
            elif prov_norm in ('opencode', 'opengo'):
                prov_norm = 'opencode-go'
            elif prov_norm in ('anthropic',):
                prov_norm = 'claude'
            elif prov_norm in ('xai',):
                prov_norm = 'grok'
            elif prov_norm in ('local-llm', 'llama.cpp'):
                prov_norm = 'local'
            elif prov_norm in ('nvidia-nim',):
                prov_norm = 'nvidia'

            target_role = data.get('target_role', 'coder-primary')
            base_url = (data.get('base_url') or '').strip()
            token = (data.get('token') or data.get('api_key') or '').strip()
            slot = data.get('profile_id')

            if slot:
                valid, reason = AutoAssigner.validate_slot(prov_norm, slot)
                if not valid:
                    return {'ok': False, 'message': reason}
            # Поддержку провайдера проверяем ДО требования ключа: у чужого
            # провайдера ключ не поможет, и сообщение «не указан API-ключ»
            # уводит владельца не туда.
            _SUPPORTED_DIRECT_ADD = (
                'openrouter', 'nvidia', 'claude', 'anthropic', 'opencode-go', 'opencode',
                'openai-codex', 'codex', 'grok', 'xai', 'antigravity', 'google-antigravity',
                'local', 'local-llm', 'llama.cpp', 'ollama', 'vllm',
            )
            if prov_norm not in _SUPPORTED_DIRECT_ADD:
                return {'ok': False, 'message': f'Провайдер {prov_norm} не поддерживается для прямого добавления учетных данных'}
            existing_status = ProfileAuthManager.get_profile_status(prov_norm, slot) if slot else {}
            if not token and prov_norm not in ('local', 'vllm', 'ollama') and not existing_status.get('authenticated'):
                if prov_norm in ('antigravity', 'google-antigravity', 'claude', 'anthropic'):
                    return {'ok': False, 'message': 'Авторизация через браузер не завершена. Пожалуйста, откройте ссылку входа или вставьте адрес возврата.'}
                return {'ok': False, 'message': 'Не указан API-ключ или не завершена авторизация'}
            validation = None
            if token or prov_norm in ('local', 'vllm', 'ollama'):
                from .connection_preflight import validate_connection
                validation = validate_connection(prov_norm, token, base_url, data.get('preferred_model') or '')
                if not validation['ok']:
                    return validation
                base_url = validation['data']['base_url']
            slot = slot or AutoAssigner.find_free_slot(prov_norm) or f'{prov_norm}-1'

            status = ProfileAuthManager.get_profile_status(prov_norm, slot)
            is_authenticated = bool(status.get("authenticated"))

            default_base_urls = {
                'openrouter': 'https://openrouter.ai/api/v1',
                'nvidia': 'https://integrate.api.nvidia.com/v1',
                'nvidia-nim': 'https://integrate.api.nvidia.com/v1',
                'ollama': 'http://127.0.0.1:11434',
                'local': 'http://127.0.0.1:8081/v1',
                'local-llm': 'http://127.0.0.1:8081/v1',
                'llama.cpp': 'http://127.0.0.1:8081/v1',
                'vllm': 'http://127.0.0.1:8081/v1',
            }

            if not base_url and prov_norm in default_base_urls:
                base_url = default_base_urls[prov_norm]

            # Validate required credentials per provider only if NOT already authenticated
            if not is_authenticated:
                if prov_norm == 'openrouter':
                    if not token:
                        return {'ok': False, 'message': 'Не указан API-ключ для OpenRouter'}
                elif prov_norm in ('nvidia', 'nvidia-nim'):
                    if not token:
                        return {'ok': False, 'message': 'Не указан API-ключ для NVIDIA NIM'}
                elif prov_norm in ('claude', 'anthropic'):
                    if not token:
                        return {'ok': False, 'message': 'Авторизация через браузер не завершена. Пожалуйста, откройте ссылку входа или вставьте адрес возврата.'}
                elif prov_norm in ('opencode-go', 'opencode'):
                    if not token:
                        return {'ok': False, 'message': 'Не указан API-ключ для OpenCode Go'}
                elif prov_norm in ('local', 'local-llm', 'llama.cpp', 'ollama', 'vllm'):
                    if not base_url:
                        return {'ok': False, 'message': f'Не указан URL сервера для {prov_norm}'}
                elif prov_norm in ('openai-codex', 'codex', 'grok', 'xai'):
                    if not token:
                        return {'ok': False, 'message': f'Не указан API-ключ для {prov_norm}'}
                elif prov_norm in ('antigravity', 'google-antigravity'):
                    if not token and not is_authenticated:
                        return {'ok': False, 'message': 'Авторизация через браузер не завершена. Пожалуйста, откройте ссылку входа или вставьте адрес возврата.'}
                else:
                    return {'ok': False, 'message': f'Провайдер {prov_norm} не поддерживается для прямого добавления учетных данных'}

            slot = slot or AutoAssigner.find_free_slot(prov_norm)
            if not slot:
                return {'ok': False, 'message': 'Нет свободного слота'}
            ok, def_msg = AutoAssigner.ensure_profile_definition(prov_norm, slot)
            if not ok:
                return {'ok': False, 'message': def_msg}

            # Save credentials if new token / base_url provided or for local/token providers
            if token or base_url or not is_authenticated:
                existing_auth = ProfileAuthManager.load_profile_auth(prov_norm, slot) or {}
                auth_data: Dict[str, Any] = {
                    "provider": prov_norm,
                    "profile_id": slot,
                    "created_at": existing_auth.get("created_at", time.time()),
                }
                auth_data.update(existing_auth)
                if base_url:
                    auth_data["base_url"] = base_url
                if token:
                    auth_data["api_key"] = token
                    auth_data["token"] = token
                try:
                    ProfileAuthManager.save_profile_auth(prov_norm, slot, auth_data)
                except Exception as e:
                    return {'ok': False, 'message': f'Ошибка при сохранении учетных данных {slot}: {e}'}

            try:
                # Учётные данные сохраняются выше и только при их наличии.
                # Повторный вызов здесь обращался к auth_data, которой у уже
                # авторизованного аккаунта не существует: перевод аккаунта в
                # другую роль падал с ошибкой, хотя ключ вводить не требуется.
                # Слот мог принадлежать другому аккаунту: старое опознание
                # обязано уйти вместе с прежними учётными данными.
                from antigravity_provider.router.quota_collector import AccountQuotaService
                AccountQuotaService.get().forget_profile(prov_norm, slot)
                AutoAssigner.assign_profile_to_role(slot, target_role, is_primary=False)
                if validation:
                    from .model_discovery_service import ModelDiscoveryService
                    ModelDiscoveryService.get().remember_models(prov_norm, slot, validation['data']['models'])
                if data.get('preferred_model'):
                    ok, message = do_set_model(slot, data['preferred_model'])
                    if not ok:
                        return {'ok': False, 'message': message}
                _rescan_after_auth(prov_norm, slot)
                from antigravity_provider.router.account_probe_service import AccountProbeService
                if validation:
                    AccountProbeService.get().record_validation(prov_norm, slot, validation)
                    return {'ok': True, 'message': validation['message'], 'data': {'profile_id': slot, 'models': validation['data']['models']}}
                # Проверку у провайдера не ждём в самом действии. Для
                # Antigravity она идёт через CLI и в худшем случае занимает до
                # 90 с на захват замка, до 65 на каталог моделей и до 90 на
                # пробный вызов — около четырёх минут молчания при обещанной
                # «минуте на этап». Владелец видит это как зависший мастер.
                #
                # Провайдеры с ключом сюда не попадают: их подключение уже
                # проверено предварительной проверкой выше и возвращается
                # сразу, как того требует A54.
                probe = AccountProbeService.get()
                started = probe.schedule(prov_norm, slot, force=True)
                if started or probe.state(slot).get('state') == 'checking':
                    return {
                        'ok': True,
                        'message': 'Аккаунт подключён. Проверка у провайдера идёт в фоне, '
                                   'результат появится в карточке.',
                        'data': {'profile_id': slot, 'check': 'running'},
                    }
                # Фоновая служба не работает — проверяем здесь, иначе результата
                # не будет вовсе. Ручная проверка обязана работать и без неё.
                result = probe.check_now(prov_norm, slot)
                result.setdefault('data', {})['profile_id'] = slot
                return result
            except Exception as e:
                return {'ok': False, 'message': f'Ошибка при сохранении учетных данных {slot}: {e}'}

        # Чисто навигационные действия. edit_route и assign_role сюда НЕ входят:
        # A25 внёс их в этот список, но в A24 они выполняют настоящую работу —
        # сохранение цепочки и назначение роли — обработчики ниже. Проглотив их
        # здесь, мы бы молча сломали перестановку блоков в маршрутизации.
        # ── Вход через CLI в терминале (Antigravity native login, A57) ──
        if action in ('start_native_auth', 'start_native_agy_login', 'start_terminal_auth'):
            provider = (data.get('provider') or '').strip().lower()
            if provider in ('google-antigravity', 'agy'):
                provider = 'antigravity'
            if provider != 'antigravity':
                return {'ok': False, 'message': f'Провайдер {provider} не поддерживает вход через agy CLI'}

            slot = data.get('profile_id')
            force = bool(data.get('force') or data.get('confirmed') or data.get('overwrite'))
            from antigravity_provider.agy_subprocess import start_native_agy_login

            ok, msg, res_data = start_native_agy_login(profile_id=slot, force=force)
            return {'ok': ok, 'message': msg, 'data': res_data}

        if action in ('poll_native_auth', 'poll_native_agy_login', 'poll_terminal_auth'):
            session_id = data.get('session_id') or ''
            from antigravity_provider.agy_subprocess import poll_native_agy_login

            ok, msg, res_data = poll_native_agy_login(session_id)
            if ok and res_data.get('status') == 'completed':
                slot = res_data.get('profile_id')
                # Вход через терминал завершается своим путём и мимо add_account.
                # Учётные данные при этом на диске, профиль числится
                # подключённым — но записи о нём в конфигурации маршрутизатора
                # нет, а список аккаунтов строится по ней. Владелец входил
                # успешно и видел пустой экран.
                if slot:
                    def_ok, def_msg = AutoAssigner.ensure_profile_definition('antigravity', slot)
                    if not def_ok:
                        return {
                            'ok': False,
                            'message': f'Вход выполнен, но аккаунт не зарегистрирован: {def_msg}',
                            'data': res_data,
                        }
                _rescan_after_auth('antigravity', slot)
            return {'ok': ok, 'message': msg, 'data': res_data}

        if action in ('cancel_native_auth', 'cancel_native_agy_login', 'cancel_terminal_auth'):
            session_id = data.get('session_id') or ''
            from antigravity_provider.agy_subprocess import cancel_native_agy_login

            ok, msg = cancel_native_agy_login(session_id)
            return {'ok': ok, 'message': msg}

        # ── Вход по localhost-redirect (Antigravity / Claude запасной путь) ──
        # Раньше веб-мастер писал «авторизация через веб-интерфейс
        # невозможна» и отправлял в консоль по SSH. Это неверно:
        # ProfileOAuthSession.handle_manual_callback_url принимает адрес
        # возврата, вставленный руками, и завершает обмен кода на токены.
        # Значит браузер нужен ГДЕ УГОДНО, а не на той же машине: владелец
        # открывает ссылку у себя, а адрес из строки браузера возвращает в Hub.
        if action == 'start_redirect_auth':
            provider = (data.get('provider') or '').strip().lower()
            if provider in ('google-antigravity',):
                provider = 'antigravity'
            if provider not in ('antigravity', 'claude'):
                return {'ok': False, 'message': f'Провайдер {provider} не использует вход по ссылке'}
            slot = data.get('profile_id') or AutoAssigner.find_free_slot(provider)
            if not slot:
                return {'ok': False, 'message': f'Нет свободного слота для провайдера {provider}'}
            valid, reason = AutoAssigner.validate_slot(provider, slot)
            if not valid:
                return {'ok': False, 'message': reason}
            try:
                if provider == 'antigravity':
                    from antigravity_provider.router.profile_oauth import (
                        get_oauth_session,
                        start_profile_oauth,
                    )

                    session_id, url, port = start_profile_oauth(slot)
                    redirect_uri = getattr(get_oauth_session(session_id), 'redirect_uri', '')
                else:
                    from antigravity_provider.router.claude_oauth import start_claude_oauth

                    session_id, url = start_claude_oauth(slot)
                    port, redirect_uri = 0, ''
            except Exception as exc:
                return {'ok': False, 'message': f'Не удалось начать авторизацию: {exc}'}

            return {
                'ok': True,
                'message': 'Ссылка авторизации получена',
                'data': {
                    'session_id': session_id,
                    'url': url,
                    'port': port,
                    'redirect_uri': redirect_uri,
                    'profile_id': slot,
                    'provider': provider,
                    # Antigravity возвращает код в адресной строке, Claude
                    # показывает его на странице — подсказка в интерфейсе
                    # должна отличаться, иначе владелец ищет не то.
                    'paste_kind': 'url' if provider == 'antigravity' else 'code',
                },
            }

        if action == 'submit_redirect_callback':
            session_id = data.get('session_id') or ''
            raw_value = data.get('callback_url') or data.get('url') or data.get('code') or ''
            provider = (data.get('provider') or 'antigravity').strip().lower()
            if provider == 'claude':
                from antigravity_provider.router.claude_oauth import get_claude_oauth_session

                session = get_claude_oauth_session(session_id)
                if not session:
                    return {'ok': False, 'message': 'Сессия авторизации не найдена или уже завершена'}
                ok, msg = session.handle_auth_code(raw_value)
                if ok:
                    _rescan_after_auth()
            else:
                from antigravity_provider.router.profile_oauth import get_oauth_session

                session = get_oauth_session(session_id)
                if not session:
                    return {'ok': False, 'message': 'Сессия авторизации не найдена или уже завершена'}
                ok, msg = session.handle_manual_callback_url(raw_value)
            if ok:
                _rescan_after_auth()
            return {'ok': ok, 'message': msg}

        if action == 'poll_redirect_auth':
            session_id = data.get('session_id') or ''
            from antigravity_provider.router.profile_oauth import get_oauth_session

            session = get_oauth_session(session_id)
            if not session:
                return {'ok': False, 'message': 'Сессия авторизации не найдена'}
            status = getattr(session, 'status', 'unknown')
            if status == 'completed':
                _rescan_after_auth()
                return {'ok': True, 'message': 'Аккаунт подключён', 'data': {'status': 'completed'}}
            if status in ('failed', 'cancelled'):
                return {'ok': False, 'message': session.error_msg or 'Авторизация не удалась'}
            # timeout закрывает только слушатель: вставленный вручную адрес
            # по-прежнему принимается, поэтому это не конечный отказ.
            return {'ok': True, 'message': 'Ожидание подтверждения', 'data': {'status': 'pending'}}

        if action == 'cancel_redirect_auth':
            from antigravity_provider.router.profile_oauth import cancel_oauth_session

            cancel_oauth_session(data.get('session_id') or '')
            return {'ok': True, 'message': 'Авторизация отменена'}

        if action in ['oauth', 'account_details', 'agent_settings', 'open_routing']:
            return {'ok': True, 'message': 'Навигация'}

        if action in ['save_chain', 'reorder_chain', 'edit_route']:
            role_id = data.get('role_id') or data.get('role') or data.get('role_name', '')
            chain = data.get('chain') or data.get('desired_chain') or data.get('preferred_chain') or data.get('nodes') or []
            if isinstance(chain, str):
                chain = [p.strip() for p in chain.split(',') if p.strip()]
            ok, msg = AutoAssigner.persist_role_chain(role_id, list(chain))
            return {'ok': ok, 'message': msg}

        elif action == 'assign_role':
            target_role = data.get('role_id') or data.get('target_role') or data.get('role') or data.get('role_name', '')
            target_pid = pid or data.get('profile_id') or data.get('profile', '')
            is_primary = data.get('is_primary', True)
            ok, msg = AutoAssigner.assign_profile_to_role(target_pid, target_role, is_primary=bool(is_primary))
            if ok:
                EventLogService.get().log('routing', f'Профиль {target_pid} назначен на роль {target_role}.', level='info')
            return {'ok': ok, 'message': msg}

        elif action == 'set_main':
            ok, msg = do_set_main(prov, pid)
            return {'ok': ok, 'message': msg}

        elif action == 'set_model':
            model_name = data.get('model', '')
            role_id = data.get('role_id', '')
            ok, msg = do_set_model(pid, model_name, role_id=role_id)
            return {'ok': ok, 'message': msg}

        elif action == 'set_orchestrator':
            ok, msg = do_set_orchestrator(pid)
            return {'ok': ok, 'message': msg}

        elif action == 'test':
            if async_runner:
                return cls._execute('check_account', {'provider': prov, 'profile_id': pid}, async_runner, actor)
            else:
                res = do_test_profile(prov, pid)
                return {'ok': res.get('success', False), 'message': res.get('response') or res.get('error'), 'data': res}
                
        elif action == 'clear_accounts':
            from .profile_manager import get_profile_auth_path
            protected_root = (paths.get_hermes_home() / 'agy_profiles').resolve()
            targets, protected = [], []
            for profile_id, profile in load_router_config().profiles.items():
                auth_path = get_profile_auth_path(profile.provider, profile_id)
                if profile.provider in ('antigravity', 'google-antigravity', 'agy') or auth_path.is_symlink() or auth_path.resolve().is_relative_to(protected_root):
                    protected.append(profile_id)
                elif auth_path.is_file():
                    targets.append({'provider': profile.provider, 'profile_id': profile_id})
            preview = {'targets': targets, 'protected': protected}
            if not data.get('confirmed'):
                return {'ok': True, 'message': f'Будут удалены ключи {len(targets)} аккаунтов. Antigravity исключён из очистки.', 'data': preview}
            # Require the exact displayed list. A newly added account is never silently deleted.
            if data.get('targets') != targets:
                return {'ok': False, 'message': 'Список аккаунтов изменился. Повторите предварительный просмотр.', 'data': preview}
            errors = []
            for target in targets:
                ok, message = do_delete_credentials(target['provider'], target['profile_id'], actor=actor)
                if not ok:
                    errors.append(message)
            return {'ok': not errors, 'message': '; '.join(errors) if errors else f'Удалены ключи {len(targets)} аккаунтов. Antigravity сохранён.', 'data': preview}

        elif action == 'delete_credentials':
            dry_run = bool(data.get('dry_run', False))
            confirmed = bool(data.get('confirmed', True))
            from antigravity_provider.router.profile_manager import get_profile_auth_path
            auth_p = get_profile_auth_path(prov, pid)
            if dry_run:
                exists = auth_p.is_file()
                EventLogService.get().log(
                    'security',
                    f'Сухой прогон удаления учётных данных {pid}',
                    actor=actor,
                    action='delete_credentials',
                    target_profile=pid,
                    outcome='dry_run',
                    level='info',
                )
                return {
                    'ok': True,
                    'dry_run': True,
                    'message': f"Сухой прогон: будет удалён файл {auth_p.name} ({'найден' if exists else 'не найден'})",
                    'data': {'path': str(auth_p), 'exists': exists, 'provider': prov, 'profile_id': pid},
                }
            if not confirmed:
                EventLogService.get().log(
                    'security',
                    f'Запрошено подтверждение удаления учётных данных {pid}',
                    actor=actor,
                    action='delete_credentials',
                    target_profile=pid,
                    outcome='denied',
                    level='warning',
                )
                return {
                    'ok': False,
                    'confirmation_required': True,
                    'message': f"Требуется подтверждение удаления учётных данных для '{pid}'",
                    'data': {'path': str(auth_p), 'provider': prov, 'profile_id': pid},
                }

            ok, msg = do_delete_credentials(prov, pid, actor=actor)
            return {'ok': ok, 'message': msg}

        elif action == 'dry_run_delete':
            from antigravity_provider.router.security_guard import get_workspace_guard
            targets = data.get('paths') or ([data.get('path')] if data.get('path') else [])
            guard = get_workspace_guard()
            res = guard.dry_run_deletion(targets)
            EventLogService.get().log(
                'security',
                f"Сухой прогон удаления: {res['total_files']} файлов, {res['total_dirs']} каталогов (риск: {res['risk_level']})",
                actor=actor,
                action='dry_run_delete',
                outcome='dry_run',
                level='info',
            )
            return {'ok': True, 'message': 'Сухой прогон выполнен', 'data': res}
            
        elif action == 'preview_auto_assign':
            res = AutoAssigner.preview_auto_assign()
            return {'ok': res.get('success', False), 'message': res.get('message', ''), 'data': res}

        elif action == 'set_default_role':
            role = (data.get('default_role') or data.get('role') or '').strip().lower()
            if not role:
                return {'ok': False, 'message': 'Не указана роль по умолчанию'}
            from antigravity_provider.router.role_registry import RoleRegistry
            canonical_role = RoleRegistry.resolve_canonical_role(role)
            rcfg = load_router_config()
            rcfg.default_role = canonical_role
            if not save_router_config(rcfg):
                return {'ok': False, 'message': 'Не удалось сохранить конфигурацию роутера'}
            do_save_settings({'default_role': canonical_role})
            try:
                from antigravity_provider.router.state_store import HubStateStore
                HubStateStore.get().refresh(force_scan=True)
            except Exception:
                pass
            EventLogService.get().log(
                'routing',
                f'Роль по умолчанию изменена на {canonical_role}.',
                level='info',
                actor=actor,
                action='set_default_role',
                outcome='success',
            )
            return {'ok': True, 'message': f'Роль по умолчанию изменена на {canonical_role}', 'data': {'default_role': canonical_role}}

        elif action == 'auto_assign_all':
            if async_runner:
                async_runner(lambda: AutoAssigner.auto_assign_all(), 'AutoAssignAll')
                return {'ok': True, 'message': 'запущено'}
            else:
                res = AutoAssigner.auto_assign_all()
                return {'ok': res.get('success', False), 'message': res.get('message', 'Успешно'), 'data': res}
                
        elif action == 'refresh_data':
            return {'ok': True, 'message': 'Обновление данных'}
            
        elif action == 'check_account':
            from antigravity_provider.router.account_probe_service import AccountProbeService
            valid, reason = AutoAssigner.validate_slot(prov, pid)
            if not valid:
                return {'ok': False, 'message': reason or 'Неверный профиль'}
            return AccountProbeService.get().check_now(prov, pid)

        elif action == 'check_all_accounts':
            from antigravity_provider.router.account_probe_service import AccountProbeService
            if not AccountProbeService.get().enabled:
                return {"ok": False, "message": "Фоновая служба проверки не запущена. Перезапустите веб-сервер."}
            count = AccountProbeService.get().schedule_all(force=True)
            return {'ok': True, 'message': f'Запущена проверка {count} аккаунтов'}

        elif action == 'refresh_all':
            if async_runner:
                async_runner(lambda: HermesRefreshScheduler.get().trigger_refresh_all(), 'RefreshAll')
                return {'ok': True, 'message': 'запущено'}
            else:
                HermesRefreshScheduler.get().trigger_refresh_all()
                return {'ok': True, 'message': 'Успешно'}
                
        elif action == 'refresh_account':
            if async_runner:
                async_runner(lambda: HermesRefreshScheduler.get().trigger_refresh_account(prov, pid), 'RefreshAccount')
                return {'ok': True, 'message': 'запущено'}
            else:
                HermesRefreshScheduler.get().trigger_refresh_account(prov, pid)
                return {'ok': True, 'message': 'Успешно'}

        elif action == 'refresh_models':
            if pid:
                from .account_probe_service import AccountProbeService
                valid, reason = AutoAssigner.validate_slot(prov, pid)
                if not valid:
                    return {'ok': False, 'message': reason or 'Неверный профиль'}
                return AccountProbeService.get().check_now(prov, pid, models_only=True)
            from antigravity_provider.router.model_discovery_service import ModelDiscoveryService
            service = ModelDiscoveryService.get()
            if prov:
                if async_runner:
                    async_runner(lambda: service.discover_models_sync(prov), 'RefreshModels')
                    return {'ok': True, 'message': 'запущено'}
                else:
                    res = service.discover_models_sync(prov)
                    return {'ok': True, 'message': 'Успешно', 'data': res}
            else:
                if async_runner:
                    async_runner(lambda: service.refresh_all_async(), 'RefreshAllModels')
                    return {'ok': True, 'message': 'запущено'}
                else:
                    service.refresh_all_async()
                    return {'ok': True, 'message': 'запущено'}
                
        elif action == 'save_settings':
            ok, msg = do_save_settings(data)
            return {'ok': ok, 'message': msg}

        elif action in ['save_request_options', 'set_request_options']:
            options = data.get('request_options', {})
            target_pid = pid or data.get('profile_id', '')
            ok, msg = do_save_request_options(target_pid, options)
            return {'ok': ok, 'message': msg}
            
        elif action == 'discover_local_models':
            # Поиск уже запущенных локальных серверов на машине.
            #
            # Раньше адрес вводился руками, и владелец должен был помнить, на
            # каком порту у него llama.cpp, Ollama или LM Studio. Опрашиваются
            # известные порты на петле; наружу идёт только то, что ответило.
            # Ни одной выдуманной модели: список берётся у самого сервера.
            from antigravity_provider.router.local_discovery import discover_local_servers

            host = (data.get('host') or '127.0.0.1').strip() or '127.0.0.1'
            try:
                servers = discover_local_servers(host=host)
            except Exception as exc:
                return {'ok': False, 'message': f'Поиск локальных серверов не удался: {exc}'}

            usable = [s for s in servers if not s.error]
            if not servers:
                return {
                    'ok': True,
                    'message': 'Локальных серверов не найдено. Запустите Ollama, LM Studio или llama.cpp либо введите адрес вручную.',
                    'data': {'servers': [], 'host': host},
                }
            return {
                'ok': True,
                'message': f'Найдено серверов: {len(usable)}',
                'data': {'servers': [s.to_dict() for s in servers], 'host': host},
            }

        elif action == 'check_updates':
            # Проверка выполняется СИНХРОННО и всегда возвращает данные.
            #
            # В фоновом режиме действие отвечало «запущено» с пустым data, и
            # результат до интерфейса не доходил вообще: проверено запросом,
            # ответ был {"ok":true,"message":"запущено","data":{}}. Кнопка
            # обновления при этом не могла появиться никогда.
            #
            # Это один HTTP-запрос к API релизов с таймаутом 10 секунд, а не
            # многоминутная установка, поэтому ждать его допустимо. Установка
            # (apply_update) по-прежнему уходит в фон.
            res = UpdateManager().check_for_updates()
            if res.error:
                return {'ok': False, 'message': res.error, 'data': res.to_dict()}
            return {
                'ok': True,
                'message': res.message or ('Доступно обновление' if res.update_available else 'Установлена последняя сборка'),
                'data': res.to_dict(),
            }

        elif action == 'apply_update':
            mgr = UpdateManager()
            if async_runner:
                async_runner(lambda: mgr.install_latest_update(), 'ApplyUpdate')
                return {'ok': True, 'message': 'Установка обновления запущена в фоновом режиме'}
            else:
                ok, msg = mgr.install_latest_update()
                return {'ok': ok, 'message': msg}

        elif action == 'get_update_status':
            mgr = UpdateManager()
            status = mgr.get_status_dict()
            return {'ok': True, 'message': status.get('message') or 'Статус получен', 'data': status}

        elif action == 'get_update_progress':
            mgr = UpdateManager()
            progress = mgr.get_progress_dict()
            return {'ok': True, 'message': progress.get('message') or 'Ход обновления', 'data': progress}

        elif action == 'cancel_update':
            # Отмена принимается не всегда: после начала установки отменять уже
            # нечего. Отвечаем тем, что произошло на самом деле, иначе владелец
            # видит «отменено» поверх продолжающейся установки.
            mgr = UpdateManager()
            progress = mgr.cancel_download()
            if progress.get('cancel_accepted'):
                return {'ok': True, 'message': 'Загрузка обновления отменена', 'data': progress}
            reason = progress.get('cancel_refused_reason') or 'Отмена сейчас невозможна'
            return {'ok': False, 'message': reason, 'data': progress}

        elif action == 'run_preflight':
            from antigravity_provider.router.preflight_service import PreflightCheckService
            service = PreflightCheckService.get()
            report = service.run_all_checks()
            msg = f"Проверка готовности: {report.passed_count} успешно, {report.failed_count} ошибок, {report.warn_count} предупреждений"
            return {'ok': report.success, 'message': msg, 'data': report.to_dict()}

        elif action == 'export_quotas':
            fmt = (data.get('format') or 'json').strip().lower()
            res = generate_quotas_export(format=fmt)
            if fmt == 'csv':
                return {
                    'ok': True,
                    'message': 'Экспорт лимитов успешно сформирован (CSV)',
                    'data': {'format': 'csv', 'content': res, 'filename': 'hermes_quotas_export.csv'}
                }
            else:
                return {
                    'ok': True,
                    'message': 'Экспорт лимитов успешно сформирован (JSON)',
                    'data': {'format': 'json', 'report': res, 'filename': 'hermes_quotas_export.json'}
                }

        elif action in ['reset_router_config', 'reset_to_empty_config']:
            res = do_reset_router_config(actor=actor)
            return {'ok': res.get('ok', False), 'message': res.get('message', ''), 'data': res}

        elif action == 'get_skills':
            from antigravity_provider.router.skills_service import SkillsService
            skills = SkillsService.get().discover_skills()
            return {'ok': True, 'message': f'Обнаружено скиллов: {len(skills)}', 'data': {'skills': [s.to_dict() for s in skills]}}

        elif action == 'assign_skill':
            from antigravity_provider.router.skills_service import SkillsService
            s_name = data.get('skill_name') or data.get('name') or ''
            a_id = data.get('agent_id') or data.get('id') or ''
            try:
                res = SkillsService.get().assign_skill(s_name, a_id)
                return {'ok': True, 'message': res.get('message', 'Скилл назначен'), 'data': res}
            except Exception as exc:
                return {'ok': False, 'message': str(exc)}

        elif action == 'unassign_skill':
            from antigravity_provider.router.skills_service import SkillsService
            s_name = data.get('skill_name') or data.get('name') or ''
            a_id = data.get('agent_id') or data.get('id') or ''
            try:
                res = SkillsService.get().unassign_skill(s_name, a_id)
                return {'ok': True, 'message': res.get('message', 'Скилл удалён'), 'data': res}
            except Exception as exc:
                return {'ok': False, 'message': str(exc)}

        elif action == 'get_skills_usage':
            from antigravity_provider.router.skills_service import SkillsService
            usage = SkillsService.get().get_skills_usage()
            return {'ok': True, 'message': usage.get('message', ''), 'data': usage}

        elif action == 'diagnose_skill':
            from antigravity_provider.router.skills_service import SkillsService
            s_name = data.get('skill_name') or data.get('name')
            f_path = data.get('path') or data.get('filepath')
            c_text = data.get('content')
            try:
                diag = SkillsService.get().diagnose_skill(skill_name=s_name, filepath=f_path, content=c_text)
                return {'ok': True, 'message': 'Диагностика завершена', 'data': {'diagnosis': diag.to_dict()}}
            except Exception as exc:
                return {'ok': False, 'message': str(exc)}

        elif action == 'check_obsidian_vault':
            from antigravity_provider.router.settings_service import validate_obsidian_vault_path
            v_path = data.get('obsidian_vault_path') or data.get('path') or data.get('vault_path')
            is_valid, msg, details = validate_obsidian_vault_path(v_path)
            return {'ok': is_valid, 'message': msg, 'data': details}

        elif action == 'setup_memory':
            from antigravity_provider.router.settings_service import setup_memory_structure
            v_path = data.get('obsidian_vault_path') or data.get('vault_path')
            p_name = data.get('project_name', 'hermes-hub')
            res = setup_memory_structure(vault_path=v_path, project_name=p_name)
            return {'ok': res.get('ok', False), 'message': res.get('message', ''), 'data': res}

        elif action == 'get_compression_status':
            from antigravity_provider.router.settings_service import get_hub_settings
            from antigravity_provider.router.local_supervisor import LocalSupervisor

            hub_settings = get_hub_settings()
            c_pid = hub_settings.get('compressor_profile_id')
            c_pcfg = None
            if c_pid:
                try:
                    c_pcfg = load_router_config().get_profile(c_pid)
                except Exception:
                    pass
            supervisor = LocalSupervisor()
            status_data = supervisor.get_compression_status(c_pcfg)
            status_data['threshold_percent'] = hub_settings.get('compression_threshold_percent', 75.0)
            status_data['keep_recent_messages'] = hub_settings.get('compression_keep_recent_messages', 3)
            status_data['compression_enabled'] = hub_settings.get('compression_enabled', True)
            return {'ok': True, 'message': 'Статус сжатия получен', 'data': status_data}

        elif action == 'get_compression_history':
            from antigravity_provider.router.context_compressor import ContextCompressor
            history = ContextCompressor().get_compression_history(limit=int(data.get('limit', 20)))
            return {'ok': True, 'message': f'Получено записей: {len(history)}', 'data': {'history': history}}

        elif action == 'test_compression':
            from antigravity_provider.router.settings_service import get_hub_settings
            from antigravity_provider.router.local_supervisor import LocalSupervisor

            hub_settings = get_hub_settings()
            c_pid = data.get('profile_id') or hub_settings.get('compressor_profile_id')
            c_pcfg = None
            if c_pid and c_pid != 'none':
                try:
                    c_pcfg = load_router_config().get_profile(c_pid)
                except Exception:
                    pass

            test_messages = [
                {"role": "system", "content": "You are a software engineer."},
                {"role": "user", "content": "Hermes Hub server runs on 192.168.1.81:8765. The primary coder is on port 8081 with 224K context (229376 tokens), generating at 107.4 tok/s. VRAM usage: 30008 MiB. Active branch: antigravity/a56-context-compression, Commit SHA: 26f7d2c, version v0.1.2. Local compressor is on port 8082."},
                {"role": "assistant", "content": "Acknowledged. All server metrics and ports are noted."},
                {"role": "user", "content": "Now run preflight diagnostics for LocalSupervisor and ContextCompressor in src/antigravity_provider/router/local_supervisor.py."},
                {"role": "assistant", "content": "Diagnostics completed successfully. Memory vault is at /srv/projects/AI-Memory."},
                {"role": "user", "content": "What is our current task?"},
            ]

            supervisor = LocalSupervisor()
            new_msgs, outcome = supervisor.compress_context_if_needed(
                messages=test_messages,
                target_context_limit=32768,
                compressor_profile=c_pcfg,
                threshold_percent=0.0,  # force compression
                keep_recent_messages=2,
            )
            return {
                'ok': outcome.status == 'SUCCESS',
                'message': outcome.status_message,
                'data': {
                    'outcome': asdict(outcome) if hasattr(outcome, '__dataclass_fields__') else outcome.__dict__,
                    'messages_before_count': len(test_messages),
                    'messages_after_count': len(new_msgs),
                }
            }

        else:
            return {'ok': False, 'message': f'Неизвестное действие: {action}', 'unknown': True}
