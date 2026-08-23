import os
import sys
import importlib
from pathlib import Path

def test_hermes_home_overrides_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'custom_home'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'bad_localappdata'))
    
    from antigravity_provider import paths
    from antigravity_provider.router import model_discovery_service
    
    assert str(paths.get_hermes_home()) == str(tmp_path / 'custom_home')
    
    discovery = model_discovery_service.ModelDiscoveryService()
    assert str(tmp_path / 'custom_home') in str(discovery._cache_path)
    assert 'bad_localappdata' not in str(discovery._cache_path)
    
    assert str(tmp_path / 'custom_home') in str(paths.get_router_profiles_path())
    assert 'bad_localappdata' not in str(paths.get_router_profiles_path())
