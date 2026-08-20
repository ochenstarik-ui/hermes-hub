# Hermes Hub — Installer Architecture

## Canonical Windows Installer
- **Canonical Binary:** `HermesHubSetup.exe` (built from `HermesHubSetup.cs`)
- **Build Script:** `build_installer.ps1` (compiles `HermesHubSetup.cs` using standard .NET Framework `csc.exe` present on all Windows 10/11 machines without extra toolchains).

## Development & Helper Scripts
- `HermesHubSetup.py`: Internal development helper script for testing installer logic in Python. Not distributed as a primary installer artifact.
- `install.ps1`: Deprecated legacy bootstrap script for earlier development environments.

## Testing Policy (S7)
- **Unit Tests:** Must NEVER modify user Windows Registry (`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall`) or Start Menu shortcuts.
- **Integration Tests:** Executed against isolated sandbox mock directories.
- **Live VM Tests:** Real Windows installer execution is reserved for disposable CI/VM environments.
