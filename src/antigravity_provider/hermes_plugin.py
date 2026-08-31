from __future__ import annotations

import argparse
import logging
from typing import Any

from .agy_subprocess import agy_generate
from .hermes_provider import DEFAULT_MODEL, PLACEHOLDER_API_KEY, PLACEHOLDER_API_KEY_ENV, PROVIDER_NAME, register_provider_profile
from .runtime import ensure_provider_profile_files, format_antigravity_error, openai_completion_object

logger = logging.getLogger(__name__)


def _is_antigravity_request(provider: str | None, request: dict[str, Any]) -> bool:
    if (provider or "").strip().lower() in {PROVIDER_NAME, "google-antigravity"}:
        return True
    return False


def _error_message(exc: Exception) -> str:
    message = " ".join(str(exc).split()) or type(exc).__name__
    if "could not determine client id" in message.lower() or "connection error" in message.lower():
        message += " If this happened after installing or updating the plugin, restart Hermes/Desktop and retry."
    return f"Antigravity request failed: {message}"


def antigravity_llm_execution(**kwargs: Any) -> Any:
    request = kwargs.get("request") or {}
    next_call = kwargs.get("next_call")
    provider = kwargs.get("provider") or request.get("provider")
    model = kwargs.get("model") or request.get("model")
    session_id = kwargs.get("session_id") or request.get("session_id")

    # 1. Try routing through Multi-Provider Account Router if enabled
    try:
        from .router import get_router_engine
        engine = get_router_engine()
        if engine.config.enabled:
            # Check if router has any configured and enabled profiles.
            # Empty configuration must not break Hermes and falls through cleanly.
            has_active_profiles = bool(
                engine.config.profiles and any(p.enabled for p in engine.config.profiles.values())
            )
            if not has_active_profiles:
                logger.info("Router has no active profiles; passing call downstream to Hermes")
                try:
                    from antigravity_provider.router.telemetry_service import TelemetryService
                    TelemetryService.get().record_bypass(
                        role="unassigned",
                        reason="В роутере нет активных профилей — вызов передан штатному Hermes",
                    )
                except Exception:
                    pass
                if callable(next_call):
                    return next_call(request)
                return request

            role = kwargs.get("role") or request.get("role")
            if not role and isinstance(request.get("metadata"), dict):
                role = request["metadata"].get("role")

            if provider and not role and not any(p.provider == provider for p in engine.config.profiles.values()):
                logger.info("Explicit provider %r not managed by router; passing call downstream to Hermes", provider)
                try:
                    from antigravity_provider.router.telemetry_service import TelemetryService
                    TelemetryService.get().record_bypass(
                        role="unassigned",
                        reason=f"Провайдер '{provider}' не управляется роутером — вызов передан штатному Hermes",
                    )
                except Exception:
                    pass
                if callable(next_call):
                    return next_call(request)
                return request

            allow_default_fallback = not provider or provider == "antigravity"
            resolved_role, resolution_source = engine.resolve_role_with_source(
                request,
                explicit_role=role,
                model=model,
                provider=provider,
                session_id=session_id,
                fallback_to_default=allow_default_fallback,
            )

            if not resolved_role:
                try:
                    from antigravity_provider.router.telemetry_service import TelemetryService
                    TelemetryService.get().record_bypass(
                        role="unassigned",
                        reason="Роль для запроса не определена — вызов передан штатному Hermes",
                    )
                except Exception:
                    pass
                if callable(next_call):
                    return next_call(request)
                return request

            if resolved_role:
                source_labels = {
                    "explicit": "явная роль",
                    "model_match": "по модели и провайдеру",
                    "session_affinity": "по устойчивости сессии",
                    "default_fallback": "роль по умолчанию",
                }
                source_label = source_labels.get(resolution_source, resolution_source)

                completion = engine.route_request(request, role=resolved_role, session_id=session_id)

                # Исчерпанная цепочка — это отказ роутера, а не ответ модели.
                # Возвращать её текст Гермесу нельзя: он подменит собой настоящий
                # ответ провайдера, который Гермес выбрал бы сам, и пользователь
                # получит «Failover Exhausted» вместо работы. Плагин обязан быть
                # незаметным при отказе: пропускаем вызов дальше по цепочке.
                if isinstance(completion, dict) and completion.get("router_error"):
                    logger.warning(
                        "Router failover exhausted for role %r; passing the call downstream to Hermes: %s",
                        resolved_role,
                        completion.get("failover_trail"),
                    )
                    try:
                        from antigravity_provider.router.telemetry_service import TelemetryService
                        TelemetryService.get().record_bypass(
                            role=resolved_role,
                            reason=f"Цепочка для роли '{resolved_role}' исчерпана — вызов передан штатному Hermes",
                            resolution_source=resolution_source,
                        )
                    except Exception:
                        pass
                    try:
                        from antigravity_provider.router.unified_health import EventLogService
                        EventLogService.get().log(
                            category="routing",
                            message=f"Цепочка для роли '{resolved_role}' исчерпана; вызов передан штатному обработчику Hermes",
                            details=f"Признак выбора роли: {source_label}",
                            level="warning",
                        )
                    except Exception:
                        pass
                    if callable(next_call):
                        return next_call(request)
                    return openai_completion_object(completion)

                # Log successful Hermes routing event with factual role origin and profile
                try:
                    from antigravity_provider.router.unified_health import EventLogService
                    meta = completion.get("router_metadata", {}) if isinstance(completion, dict) else {}
                    served_profile = meta.get("profile_id", "default")
                    served_provider = meta.get("provider", provider or "unknown")
                    served_model = (
                        meta.get("selected_model")
                        or (meta.get("selection_trace") or {}).get("selected_model")
                        or model
                        or "default"
                    )
                    EventLogService.get().log(
                        category="routing",
                        message=f"Запрос Hermes направлен роли '{resolved_role}' ({source_label})",
                        details=f"Профиль: '{served_profile}' ({served_provider}), модель: {served_model}",
                        level="info",
                    )
                except Exception:
                    pass

                if isinstance(completion, dict) and "error" in completion and not completion.get("choices"):
                    err_text = format_antigravity_error(completion.get("error"))
                    completion = {
                        "model": str(request.get("model") or DEFAULT_MODEL),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": err_text},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    }
                return openai_completion_object(completion)
    except Exception as router_exc:
        logger.debug("Router invocation fell back to default provider: %s", router_exc)

    # 2. Fallback to standard Antigravity single-provider subprocess
    if not _is_antigravity_request(provider, request):
        return next_call(request) if callable(next_call) else request
    try:
        completion = agy_generate(request)
        if isinstance(completion, dict) and "error" in completion and not completion.get("choices"):
            err_text = format_antigravity_error(completion.get("error"))
            completion = {
                "model": str(request.get("model") or DEFAULT_MODEL),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": err_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
    except Exception as exc:
        logger.exception("agy_generate raised: %s", exc)
        completion = {
            "model": str(request.get("model") or DEFAULT_MODEL),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": _error_message(exc)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
    return openai_completion_object(completion)


def _save_placeholder_api_key() -> None:
    try:
        from hermes_cli.config import get_env_value, save_env_value

        if not (get_env_value(PLACEHOLDER_API_KEY_ENV) or "").strip():
            save_env_value(PLACEHOLDER_API_KEY_ENV, PLACEHOLDER_API_KEY)
    except Exception:
        return


def _setup_cli(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="antigravity_command")

    login = sub.add_parser("login", help="use agy Keychain credentials, falling back to browser OAuth")
    login.add_argument("--no-keychain", action="store_true", help="skip agy Keychain and run browser OAuth")
    login.add_argument("--no-browser", action="store_true", help="print the auth URL instead of opening a browser")
    login.add_argument("--timeout", type=int, default=300, help="seconds to wait for the OAuth callback")

    select = sub.add_parser("select", help="set Antigravity as the active Hermes model without opening the model picker")
    select.add_argument("model", nargs="?", default=DEFAULT_MODEL)

    sub.add_parser("status", help="show credential status")
    sub.add_parser("logout", help="remove saved browser OAuth credentials")


def _select_model(model_id: str) -> None:
    try:
        from hermes_cli.config import load_config, save_config
    except Exception as exc:
        raise SystemExit(f"Hermes config helpers are not available: {exc}") from exc
    config = load_config()
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {"default": model_cfg} if model_cfg else {}
    model_cfg["provider"] = PROVIDER_NAME
    model_cfg["default"] = model_id
    model_cfg["base_url"] = "http://127.0.0.1:8765/v1"
    model_cfg["api_mode"] = "chat_completions"
    config["model"] = model_cfg
    save_config(config)
    print(f"Default Hermes model set to {model_id} via provider '{PROVIDER_NAME}'.")
    print("Restart any running Hermes/Desktop session to use updated plugin code.")


def _status() -> None:
    from .credentials import CredentialStore, load_agy_keychain_credentials

    store = CredentialStore.default()
    keychain = load_agy_keychain_credentials()
    data = keychain or store.load()
    source = "agy Keychain" if keychain else ("browser OAuth" if data else "none")
    has_refresh = bool(data.get("refresh_token") or data.get("refresh"))
    has_access = bool(data.get("access_token") or data.get("access") or data.get("token"))
    print(f"credentials: {source}")
    print(f"access token: {'yes' if has_access else 'no'}")
    print(f"refresh token: {'yes' if has_refresh else 'no'}")
    if data.get("email"):
        print(f"account: {data['email']}")


def _handle_cli(args: argparse.Namespace) -> None:
    command = getattr(args, "antigravity_command", None) or "status"
    if command == "login":
        from .oauth import run_login

        ensure_provider_profile_files()
        _save_placeholder_api_key()
        run_login(open_browser=not args.no_browser, timeout=args.timeout, prefer_keychain=not args.no_keychain)
        print("Antigravity login complete.")
        return
    if command == "select":
        ensure_provider_profile_files()
        _save_placeholder_api_key()
        _select_model(args.model)
        return
    if command == "logout":
        from .credentials import CredentialStore

        CredentialStore.default().delete()
        print("Saved Antigravity browser OAuth credentials removed.")
        return
    _status()


def register(ctx: Any) -> None:
    register_provider_profile()
    ctx.register_cli_command(
        name="agy",
        help="Manage the Google Antigravity Hermes provider plugin",
        description="Login, status, and model selection helpers for Google Antigravity.",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
    )
    ctx.register_middleware("llm_execution", antigravity_llm_execution)
