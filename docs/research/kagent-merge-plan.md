# План слияния Hermes Hub → KAgent

Источник — план владельца от 2026-09-02, положен в репозиторий, чтобы не жил
только файлом на рабочем столе. Оценка и условия исполнения — в
[kagent-merge-decision.md](kagent-merge-decision.md).

## Цель

KAgent становится единой AI Agent Operating Platform. Функциональность Hermes Hub
переносится нативно, Hermes Hub и Hermes Agent перестают быть зависимостями,
Hermes Hub архивируется. Hermes Hub на переходный период — донор функциональности
и эталон поведения, не встраиваемая библиотека.

## Разделение обязанностей

- **Orchestrator** выбирает агента, workflow, инструменты, контекст, проверку,
  момент завершения.
- **AI Router** выбирает провайдера, модель, аккаунт, локально/облако, failover,
  проверяет квоту, доступность, бюджет, вычислительный узел.

> Orchestrator выбирает агента и задачу. Router выбирает модель, провайдера и
> аккаунт.

## Что переносится из Hermes

Multi-provider router; адаптеры провайдеров (Antigravity, Claude, Codex,
DeepSeek, Grok, Local, NVIDIA, Ollama, OpenCode, OpenRouter); менеджер
аккаунтов/профилей (несколько аккаунтов на провайдера, приоритет, quota,
cooldown, health, concurrency); health-состояния; quota manager; session
affinity; lease/concurrency; model registry; capability-routing; локальные
модели и вычислительные узлы; agent registry (15 ролей как декларативные
Agent Definition); Dual Coder как workflow; Guardian как policy-слой; Cost
Controller как системная подсистема; failover-policy с таксономией ошибок;
telemetry в существующий Observability; audit routing-решений.

## Что НЕ переносить

Hermes-specific bootstrap; дублирующий Web API и отдельный UI; process-local
архитектуру; JSONL как основное хранилище telemetry; формат настроек Hermes;
update flow Hermes; роль orchestrator как отдельный runtime; код, привязанный к
структуре Hermes Agent; compatibility-слои, не нужные после миграции.

Секреты: не переносить хранилище Hermes один-в-один. Порядок — внешний Secret
Manager → OS/keyring → шифрованное хранение в БД → материализация только на время
запроса. Запрещено: ключи в обычных JSON, отдача секретов через API, секреты в
telemetry/audit/трейсах.

## Фазы

- **Phase 0 — Security baseline (блокер).** Auth/RBAC; защита расхода провайдера;
  service-auth; безопасное хранение секретов; уникальная request identity;
  реальный E2E. Выход: нет неавторизованного execution и мутаций проекта/задачи;
  расход защищён; CI зелёный; E2E по настоящему пути зелёный.
- **Phase 1 — контракты Router.** AIExecutionRequest, AIExecutionResult,
  ProviderAdapter, Model/Account descriptor, таксономия ошибок, RoutingDecision.
  Провайдеры пока не переносить. Выход: contract-тесты, fake-адаптер, роутер на
  тестовых провайдерах.
- **Phase 2 — Provider SDK.** timeout, cancellation, streaming, маппинг ошибок,
  usage, cost, health, discovery. Выход: новый провайдер добавляется без правки
  ядра.
- **Phase 3 — перенос адаптеров.** Порядок: openai-compatible → Claude →
  OpenRouter → Google/Antigravity → Grok → DeepSeek → NVIDIA → Ollama → Codex →
  OpenCode → local. Для каждого: parity, таксономия ошибок, health/auth/
  streaming/timeout/quota/regression тесты.
- **Phase 4 — Account Manager.** Безопасные credentials, приоритет, quota,
  cooldown, health, concurrency, переходы состояний.
- **Phase 5 — Router Engine.** role/capability routing, scoring, preferred chain,
  health/quota awareness, same-account и cross-account/provider fallback, session
  affinity, auto-return primary, failover trace.
- **Phase 6 — распределённое состояние.** Redis (health, leases, affinity,
  cooldown), PostgreSQL (providers, accounts, models, policies, budgets, usage,
  nodes, agents).
- **Phase 7 — локальные модели / compute nodes.** node agent: регистрация,
  heartbeat, инвентарь моделей и ресурсов, execution, queue, GPU.
- **Phase 8 — Agent Registry.** декларативные определения: capabilities, tools,
  permissions, routing policy, budgets, model constraints.
- **Phase 9 — Guardian** как policy enforcement: валидация команд, границы ФС,
  сигналы prompt injection, детект секретов, проверка прав инструментов, сетевая
  политика, классификация разрушительных действий.
- **Phase 10 — Cost Controller.** оценочная и фактическая стоимость, жёсткие
  бюджеты, наследование, cloud/local оптимизация, alerts, kill switch.
- **Phase 11 — Workflows.** Dual Coder как workflow; шаблоны Coder+Reviewer,
  Coder+Tester, Security Review, Multi-model Consensus, Local Draft + Cloud
  Review.
- **Phase 12 — UI.** разделы Providers, Accounts, Models, Routing, Nodes, Quotas,
  Budgets, Usage, Health, Agents.
- **Phase 13 — parity-тесты.** Чек-лист до отключения Hermes: все провайдеры,
  несколько аккаунтов, quota exhaustion, rate limit, auth failure, failover,
  локальные модели, session affinity, выбор модели, health, telemetry, Dual
  Coder, роли.
- **Phase 14 — decommission Hermes.** запрет новых фич → deprecated → KAgent
  единственный production path → удаление зависимостей → финальный релиз Hermes →
  archived.

## Критерий отказа от Hermes

Архивировать только когда KAgent умеет: все нужные облачные провайдеры;
несколько аккаунтов; локальный AI; авто-выбор модели; failover; учёт quota;
health; session affinity; telemetry; расчёт cost; роли агентов; эквивалент Dual
Coder; проверки Guardian; бюджеты; работу на Windows/Linux; полный parity-набор.

## Обязательные P0 KAgent до миграции (из его аудита, часть проверена ревьюером)

Control Plane auth/RBAC (не доверять `x-actor-id`); авторизация
`/v1/execute` и `/v1/decide` (**подтверждено: сейчас открыты**); уникальная
request identity; фикс double-consume TOTP; настоящий E2E через Gateway, не mock;
добавить LICENSE (**подтверждено: отсутствует**).
