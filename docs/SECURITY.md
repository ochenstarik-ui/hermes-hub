# Hermes Hub — Security Policy & Controls

## 1. Security Invariants
1. **Zero Secret Leaks**: All credentials, tokens, and OAuth keys reside solely in `%LOCALAPPDATA%\hermes\` and are excluded from Git via `.gitignore`.
2. **Policy Enforcement**:
   - `WebPolicy`: Outbound URL traffic is restricted to verified provider domains. Requests to internal cloud metadata IP `169.254.169.254` or local networks are blocked.
   - `ToolPolicy`: Commands matching destructive patterns (`format`, `rmdir /s /q c:\`, `del /f /s /q c:\windows`) are blocked before invocation.
3. **Process Sandboxing & Registry**:
   - Every background process spawned by the hub is tagged with a unique UUID, PID, and spawn timestamp in `LifecycleSupervisor`.
   - Cleanup is strictly limited to verified owned processes. Generic `taskkill` or `killall` commands are prohibited.
4. **Audit Logging**:
   - Security-relevant events (URL blocking, credential operations, role changes) are appended to `%LOCALAPPDATA%\hermes\logs\hermes-hub.log` and displayed in the Event Log.
