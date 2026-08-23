import time
import json
import os
import logging
import threading
from typing import Any, Dict, Tuple, Optional, Callable

from antigravity_provider.router.router_config import load_router_config, save_router_config
from antigravity_provider.router.profile_manager import ProfileAuthManager
from antigravity_provider.router.unified_health import EventLogService
from antigravity_provider.router.auto_assigner import AutoAssigner
from antigravity_provider.router.scheduler import HermesRefreshScheduler
from antigravity_provider.updater import UpdateManager
from antigravity_provider import paths
from antigravity_provider.router.adapters import get_adapter

logger = logging.getLogger('hermes.router.actions')

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

def do_test_profile(provider: str, profile_id: str) -> Dict[str, Any]:
    config = load_router_config()
    pcfg = config.get_profile(profile_id)
    if not pcfg:
        return {'success': False, 'error': f"Профиль '{profile_id}' не найден"}

    status = ProfileAuthManager.get_profile_status(pcfg.provider, profile_id)
    if not status.get('authenticated'):
        return {'success': False, 'error': 'Аккаунт не добавлен. Сначала выполните подключение.'}

    if status.get('is_expired') or status.get('expired') or status.get('status') == 'EXPIRED':
        return {'success': False, 'error': 'Авторизация истекла, требуется повторный вход.'}

    model = pcfg.preferred_models[0] if pcfg.preferred_models else 'default'
    t0 = time.time()
    try:
        auth_data = ProfileAuthManager.load_profile_auth(pcfg.provider, profile_id)
        if not auth_data:
            return {'success': False, 'error': 'Сохранённые данные авторизации не найдены'}
        adapter = get_adapter(pcfg.provider)
        runtime_ready = adapter.health_check(pcfg)
        el = round(time.time() - t0, 2)
        if not runtime_ready:
            return {
                'success': False,
                'duration_sec': el,
                'error': 'Локальный runtime провайдера недоступен; повторная авторизация не запускалась',
            }
        EventLogService.get().log(
            'system', f'Локальная проверка профиля {profile_id} ({model}) пройдена за {el}s.', level='success'
        )
        return {
            'success': True,
            'model': model,
            'duration_sec': el,
            'response': 'Авторизация сохранена; runtime провайдера доступен',
        }
    except Exception as e:
        EventLogService.get().log('system', f'Ошибка теста {profile_id} ({model}): {e}', level='error')
        return {'success': False, 'model': model, 'duration_sec': round(time.time() - t0, 2), 'error': str(e)}

def do_delete_credentials(provider: str, profile_id: str) -> Tuple[bool, str]:
    auth_p = ProfileAuthManager.get_profile_dir(provider, profile_id) / 'auth.json'
    if auth_p.is_file():
        try:
            auth_p.unlink()
            EventLogService.get().log('account', f'Учетные данные для {profile_id} удалены.', level='warning')
            return True, f"Учетные данные для '{profile_id}' удалены"
        except Exception as e:
            return False, f'Ошибка удаления: {e}'
    return True, 'Учетные данные отсутствовали'

def do_save_settings(settings: Dict[str, Any]) -> Tuple[bool, str]:
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

    from antigravity_provider.router.quota_collector import AccountQuotaService

    AccountQuotaService.get().set_refresh_interval(int(settings.get("quota_refresh_interval_sec", 300)))
    return True, "Настройки сохранены"
 
 
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

    discovered = ModelDiscoveryService.get().get_models(provider)
    if discovered is None:
        return False, f"Список моделей провайдера '{provider}' ещё не получен. Сначала нажмите «Обновить список моделей»."

    if model not in discovered:
        return False, f"Модель '{model}' отсутствует в списке обнаруженных моделей провайдера '{provider}'"

    updated = load_router_config()
    target = updated.profiles[profile_id]
    target.preferred_models = [model] + [m for m in target.preferred_models if m != model]
    updated.profiles[profile_id] = target

    if role_id and role_id in updated.roles:
        updated.roles[role_id].default_model = model

    if save_router_config(updated):
        try:
            from antigravity_provider.router.state_store import HubStateStore
            HubStateStore.get().refresh(force_scan=True)
        except Exception:
            pass
        EventLogService.get().log(
            "model", f"Для профиля {profile_id} ({provider}) установлена модель '{model}'.", level="info"
        )
        return True, f"Модель '{model}' успешно сохранена для профиля {profile_id}"
    return False, "Не удалось сохранить файл конфигурации"


class ActionExecutor:
    """Shared execution layer for Desktop and Web actions."""
    
    @classmethod
    def execute(cls, action: str, data: Dict[str, Any], async_runner: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Execute the specified action.
        If async_runner is provided, long actions will be dispatched to it.
        async_runner should accept (func, name).
        """
        pid = data.get('profile_id', '')
        prov = data.get('provider', '')
        
        # Purely UI navigation actions return True for Web API (no-op on server side).
        if action in ['oauth', 'add_account', 'account_details', 'agent_settings', 'edit_route', 'open_routing', 'assign_role']:
            return {'ok': True, 'message': 'Навигация'}
            
        if action == 'set_main':
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
                async_runner(lambda: do_test_profile(prov, pid), 'TestProfile')
                return {'ok': True, 'message': 'запущено'}
            else:
                res = do_test_profile(prov, pid)
                return {'ok': res.get('success', False), 'message': res.get('response') or res.get('error'), 'data': res}
                
        elif action == 'delete_credentials':
            ok, msg = do_delete_credentials(prov, pid)
            return {'ok': ok, 'message': msg}
            
        elif action == 'auto_assign_all':
            if async_runner:
                async_runner(lambda: AutoAssigner.auto_assign_all(), 'AutoAssignAll')
                return {'ok': True, 'message': 'запущено'}
            else:
                AutoAssigner.auto_assign_all()
                return {'ok': True, 'message': 'Успешно'}
                
        elif action == 'refresh_data':
            return {'ok': True, 'message': 'Обновление данных'}
            
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
                
        elif action == 'save_settings':
            ok, msg = do_save_settings(data)
            return {'ok': ok, 'message': msg}
            
        elif action == 'check_updates':
            if async_runner:
                async_runner(lambda: UpdateManager().check_for_updates(), 'CheckUpdates')
                return {'ok': True, 'message': 'запущено'}
            else:
                res = UpdateManager().check_for_updates()
                return {'ok': True, 'message': 'Успешно', 'data': res}
                
        else:
            return {'ok': False, 'message': f'Неизвестное действие: {action}', 'unknown': True}
