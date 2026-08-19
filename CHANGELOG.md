# Changelog

All notable changes to **Hermes Hub** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-20

### Added
- **Standalone Architecture**: Extracted Hermes Hub into independent repository `E:\Agent projects\hermes-hub`.
- **Multi-Provider Account Router**: Full routing, failover, session affinity, and concurrency leasing across 3 tiers:
  - OpenAI Codex (3 accounts: `codex-orch`, `codex-worker-1`, `codex-worker-2`).
  - Antigravity OAuth (10 accounts: 7 active work/spare slots, 3 cold spares).
  - OpenCode Go (3 accounts: `opengo-1`, `opengo-2`, `opengo-3`).
- **Visual Dashboard («Команда Hermes»)**: Modern dark-mode UI with logical team grouping (Orchestrator, Subagents, Spares), status badges, and non-blocking test execution.
- **Auto Assignment Engine**: Automatic slot discovery, role assignment, and duplicate account detection based on email/account ID.
- **Dedicated Windows Launcher (`HermesHub.exe`)**: Standalone C# launcher with safe asynchronous port detection, health check gate (HTTP 200), and Edge App Mode integration.
- **Windows Setup Installer (`HermesHubSetup.exe`)**: Modern Windows installer wizard with pre-flight checks (Hermes Agent 0.20.4+ detection), unattended silent mode (`/silent`, exit codes 0, 10, 11, 12), repair, update, and safe uninstaller.
- **Automated Verification Suite**: Full test coverage (`test_multi_provider_router.py`) and verification scripts.
