# Архитектура Hermes Hub

## 1. Концепция и назначение
**Hermes Hub** — централизованная панель управления и отказоустойчивый роутер запросов для **Hermes Agent**.

```mermaid
graph TD
    A[Пользователь / Hermes Agent CLI] --> B[Multi-Provider Router Engine]
    C[HermesHub.exe / Web UI] --> D[FastAPI Backend :8765]
    D --> B
    B --> E{Logical Role Policies}
    E -->|Tier 1| F[OpenAI Codex Pool (3 slots)]
    E -->|Tier 2| G[Antigravity OAuth Pool (10 slots)]
    E -->|Tier 3| H[OpenCode Go API Pool (3 slots)]
    B --> I[Health & Quota Tracker]
    B --> J[Session Affinity Engine]
    B --> K[Concurrency Lease Manager]
```

## 2. Ключевые компоненты
- **Router Engine (`router_engine.py`)**: Сопоставляет роль задачи (`orchestrator`, `coder-primary`, `reviewer`, `research`, `fast`) с цепочкой профилей и выполняет failover при исчерпании квот.
- **Session Affinity (`session_affinity.py`)**: Удерживает единый профиль и модель на протяжении диалоговой сессии пользователя.
- **Health & Quota Tracker (`health_tracker.py`)**: Отслеживает доступность семейств моделей (`gemini`, `claude`, `gpt`, `deepseek`) и выставляет экспоненциальный cooldown (300s -> 3600s).
- **Auto Assignment Engine (`auto_assigner.py`)**: Автоматически распределяет новые аккаунты по свободным слотам ролей.
- **GUI Server (`gui_server.py`) & UI (`gui_cockpit.html`)**: Предоставляет темный дашборд «Команда Hermes».
- **Launcher (`HermesHub.exe`)**: Нативный C# лаунчер с health check gate (HTTP 200) и Edge App Mode.
- **Setup Installer (`HermesHubSetup.exe`)**: Мастер установки с pre-flight проверками Hermes Agent 0.20.4+.
