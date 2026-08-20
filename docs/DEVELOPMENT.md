# Hermes Hub — Development & Contribution Guide

## 1. Setup & Environment
```bash
# Clone the repository
git clone https://github.com/ochenstarik-ui/hermes-hub.git
cd hermes-hub

# Sync dependencies using uv
uv sync

# Run tests
uv run pytest -v tests/
```

## 2. Code Structure
- `src/antigravity_provider/router/`:
  - `hermes_hub_app.py`: Desktop application root controller.
  - `unified_health.py`: Unified health status resolver, system readiness, and event logging.
  - `router_engine.py`: Multi-provider request execution and failover logic.
  - `profile_manager.py`: Credential storage and isolation.
  - `auto_assigner.py`: Role assignment recommendation and conflict resolution.
  - `ui/`:
    - `theme.py`: Obsidian Forest brand tokens and typography.
    - `components.py`: Reusable UI components.
    - `views/`: View frames (Team, Accounts, Routing, Providers, Health, Logs, Settings, About).
  - `supervisor/`: LifecycleSupervisor and PolicyEnforcer (WebPolicy, ToolPolicy).
  - `skills/`: UnifiedSkillRegistry.
  - `capability/`: CapabilityMatrix.
  - `scheduler/`: ScheduledTaskSafetyCoordinator.
  - `adapters/`: Provider adapters (Antigravity, Codex, OpenCode, DeepSeek).

## 3. Running Verification Suite
```bash
python scripts/verify_multi_provider_router.py
uv run pytest -v tests/
```
