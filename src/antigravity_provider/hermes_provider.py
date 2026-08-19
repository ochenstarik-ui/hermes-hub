from __future__ import annotations

from typing import Any

from .models import DEFAULT_MODEL, KNOWN_MODELS, clamp_reasoning_effort

PROVIDER_NAME = "antigravity"
PLACEHOLDER_API_KEY_ENV = "ANTIGRAVITY_HERMES_API_KEY"
PLACEHOLDER_API_KEY = "antigravity-dummy-default"
DUMMY_BASE_URL = "http://127.0.0.1:8765/v1"


def _reasoning_effort(reasoning_config: dict | None, model: str | None = None) -> str | None:
    if not isinstance(reasoning_config, dict):
        return None
    if reasoning_config.get("enabled") is False:
        return "off"
    effort = str(reasoning_config.get("effort") or "").strip().lower().replace("_", "-")
    if effort in {"none", "off", "disabled"}:
        return "off"
    if effort in {"minimal", "minimum", "low", "medium", "high", "xhigh", "max"}:
        return clamp_reasoning_effort(model or DEFAULT_MODEL, effort)
    return None


def register_provider_profile() -> bool:
    """Register the Antigravity provider when running inside Hermes."""
    try:
        from providers import register_provider
        from providers.base import OMIT_TEMPERATURE, ProviderProfile
    except Exception:
        return False

    class AntigravityProfile(ProviderProfile):
        def build_api_kwargs_extras(
            self,
            *,
            reasoning_config: dict | None = None,
            **context: Any,
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            top_level: dict[str, Any] = {}
            effort = _reasoning_effort(reasoning_config, context.get("model"))
            if effort:
                top_level["reasoning_effort"] = effort
            return {}, top_level

        def get_max_tokens(self, model: str | None) -> int | None:
            return KNOWN_MODELS.get(model or "") or KNOWN_MODELS.get(DEFAULT_MODEL)

        def fetch_models(self, **kwargs: Any) -> list[str] | None:
            # Dynamic discovery from agy subprocess, fallback to static list
            try:
                from .agy_subprocess import discover_models
                dynamic = discover_models()
                if dynamic:
                    return list(dynamic.keys())
            except Exception:
                pass
            return list(KNOWN_MODELS)

    register_provider(
        AntigravityProfile(
            name=PROVIDER_NAME,
            aliases=("google-antigravity",),
            display_name="Google Antigravity",
            description="Google Antigravity via Hermes in-process provider plugin",
            env_vars=(PLACEHOLDER_API_KEY_ENV,),
            base_url=DUMMY_BASE_URL,
            auth_type="api_key",
            supports_health_check=False,
            supports_vision=True,
            fallback_models=tuple(KNOWN_MODELS),
            default_aux_model=DEFAULT_MODEL,
            fixed_temperature=OMIT_TEMPERATURE,
        )
    )
    return True


# Directory-style model-provider plugins are imported for side effects.
register_provider_profile()
