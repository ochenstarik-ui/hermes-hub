import pytest
from antigravity_provider.router.web.server import sanitize_snapshot

def test_sanitize_snapshot_removes_secrets():
    raw_snap = {
        "generation": 1,
        "profiles_by_provider": {
            "codex": [
                {
                    "profile_id": "test",
                    "access_token": "secret123",
                    "refresh_token": "secret456",
                    "safe_field": "hello"
                }
            ]
        },
        "quotas": {
            "api_key": "some_key",
            "usage": 10,
            "jwt_token": "eyJhb..."
        },
        "safe_list": [
            {"safe_key": "hidden", "public": "visible"}
        ]
    }
    
    clean_snap = sanitize_snapshot(raw_snap)
    
    assert "access_token" not in clean_snap["profiles_by_provider"]["codex"][0]
    assert "refresh_token" not in clean_snap["profiles_by_provider"]["codex"][0]
    assert "safe_field" in clean_snap["profiles_by_provider"]["codex"][0]
    
    assert "api_key" not in clean_snap["quotas"]
    assert "jwt_token" not in clean_snap["quotas"]
    assert "usage" in clean_snap["quotas"]
    
    assert "safe_key" in clean_snap["safe_list"][0]
    assert "public" in clean_snap["safe_list"][0]

