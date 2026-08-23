"""Test ensuring ModelDiscoveryService reachability via the agreed entrypoint."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_model_discovery_entrypoint_reaches_service_directly():
    """Verify that router/model_discovery.py directly exports ModelDiscoveryService with .get()."""
    try:
        import antigravity_provider.router.model_discovery as md_module
    except ImportError as exc:
        pytest.fail(f"Could not import agreed module 'antigravity_provider.router.model_discovery': {exc}")

    assert hasattr(
        md_module, "ModelDiscoveryService"
    ), "Module 'antigravity_provider.router.model_discovery' must expose 'ModelDiscoveryService'"

    from antigravity_provider.router.model_discovery import ModelDiscoveryService

    assert hasattr(
        ModelDiscoveryService, "get"
    ), "ModelDiscoveryService must provide a '.get()' classmethod/factory"
    assert callable(ModelDiscoveryService.get), "ModelDiscoveryService.get must be callable"

    service = ModelDiscoveryService.get()
    assert service is not None, "ModelDiscoveryService.get() must return an initialized instance"
    assert isinstance(
        service, ModelDiscoveryService
    ), "ModelDiscoveryService.get() must return an instance of ModelDiscoveryService"
    assert service is ModelDiscoveryService.get(), "ModelDiscoveryService.get() must return a singleton instance"


@pytest.mark.unit
def test_model_discovery_service_methods_and_cache_interface():
    """Verify standard methods of ModelDiscoveryService instance."""
    from antigravity_provider.router.model_discovery import ModelDiscoveryService

    service = ModelDiscoveryService.get()
    assert hasattr(service, "get_cached"), "ModelDiscoveryService must implement get_cached()"
    assert hasattr(service, "refresh_models"), "ModelDiscoveryService must implement refresh_models()"

    # Test cache read for a standard provider
    cached = service.get_cached("antigravity")
    assert isinstance(cached, dict), "get_cached must return a dictionary"
    assert "models" in cached, "cached payload must contain 'models' key"
