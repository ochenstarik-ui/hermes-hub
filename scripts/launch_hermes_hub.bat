@echo off
setlocal
title Hermes Hub Launcher

echo ======================================================================
echo   HERMES HUB LAUNCHER (Multi-Agent & Multi-Provider Control Hub)
echo ======================================================================
echo.

set "HERMES_PYTHON=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "%HERMES_PYTHON%" (
    echo [ERROR] Hermes Python environment not found at:
    echo %HERMES_PYTHON%
    pause
    exit /b 1
)

set "PYTHONPATH=%LOCALAPPDATA%\hermes\plugins\antigravity-provider\src;%~dp0..\plugins\antigravity-provider\src;%PYTHONPATH%"

echo Starting Hermes Hub Server on http://127.0.0.1:5800 ...
"%HERMES_PYTHON%" -m antigravity_provider.router.cli_commands web --port 5800

endlocal
