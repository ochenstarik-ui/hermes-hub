#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — Linux Web Application Launcher
# Starts the background web server if not already active, waits for /api/health,
# and opens the UI in application window mode (--app=URL) or handles headless mode.
# ==============================================================================

set -e

DEFAULT_HERMES_HOME="$HOME/.hermes"
HERMES_HOME="${HERMES_HOME:-$DEFAULT_HERMES_HOME}"

# 1. Discover Python Runtime
PYTHON_BIN=""
if [ -f "$HERMES_HOME/hermes-agent/venv/bin/python3" ]; then
    PYTHON_BIN="$HERMES_HOME/hermes-agent/venv/bin/python3"
elif [ -f "$HERMES_HOME/hermes-agent/venv/bin/python" ]; then
    PYTHON_BIN="$HERMES_HOME/hermes-agent/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
else
    echo "❌ Error: Python 3 not found on system." >&2
    exit 1
fi

# 2. Configure Environment and Read Settings (Host/Port)
export PYTHONPATH="$HERMES_HOME/plugins/antigravity-provider/src:$HERMES_HOME/hermes-agent:$PYTHONPATH"

HOST="127.0.0.1"
PORT=5800

SETTINGS_FILE="$HERMES_HOME/hub_settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    PARSED_PORT="$("$PYTHON_BIN" -c "import json; print(json.load(open('$SETTINGS_FILE')).get('web_api_port', 5800))" 2>/dev/null || echo 5800)"
    if [ -n "$PARSED_PORT" ] && [ "$PARSED_PORT" -gt 0 ] 2>/dev/null; then
        PORT="$PARSED_PORT"
    fi
    PARSED_HOST="$("$PYTHON_BIN" -c "import json; h = json.load(open('$SETTINGS_FILE')).get('web_api_host', '127.0.0.1'); print('127.0.0.1' if h in ('0.0.0.0', '') else h)" 2>/dev/null || echo '127.0.0.1')"
    if [ -n "$PARSED_HOST" ]; then
        HOST="$PARSED_HOST"
    fi
fi

TARGET_URL="http://$HOST:$PORT/"
HEALTH_URL="http://$HOST:$PORT/api/health"

# Function to check server health
check_health() {
    # sys импортируется здесь, а не внутри except: раньше на УСПЕШНОМ ответе
    # возникал NameError, его ловил тот же except, и проверка всегда сообщала
    # об отказе — сервер работал, а лаунчер писал «failed to respond».
    "$PYTHON_BIN" -c "
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen('$HEALTH_URL', timeout=0.8) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    sys.exit(0 if data.get('ok') is True else 1)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1
}

# 3. Start Web Server if not already active
SERVER_STARTED_BY_US=false
if ! check_health; then
    echo "Starting Hermes Hub Web Server in background..."
    LOG_FILE="$HERMES_HOME/hermes_web_server.log"
    nohup "$PYTHON_BIN" -m antigravity_provider.router.web > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    SERVER_STARTED_BY_US=true

    # Wait for server readiness (polling /api/health)
    READY=false
    for i in $(seq 1 75); do
        if check_health; then
            READY=true
            break
        fi
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            echo "❌ Error: Web server process terminated unexpectedly. Check $LOG_FILE" >&2
            exit 1
        fi
        sleep 0.2
    done

    if [ "$READY" != "true" ]; then
        echo "❌ Error: Web server failed to respond at $HEALTH_URL within 15 seconds." >&2
        exit 1
    fi
fi

# 4. Headless Server Check (SSH / No Graphical Display)
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    echo "======================================================================"
    echo "  Hermes Hub Web Server is running (Headless Mode)"
    echo "  Web Interface URL: $TARGET_URL"
    echo ""
    echo "  To access the interface from your local computer, forward the port:"
    echo "    ssh -L $PORT:127.0.0.1:$PORT user@server"
    echo ""
    echo "  Then open in your browser:"
    echo "    $TARGET_URL"
    echo "======================================================================"
    exit 0
fi

# 5. Graphical Environment: Search for Chromium-based browser in priority order
CHROMIUM_BIN=""

for b in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge microsoft-edge-stable brave-browser; do
    if command -v "$b" >/dev/null 2>&1; then
        CHROMIUM_BIN="$(command -v "$b")"
        break
    fi
done

if [ -n "$CHROMIUM_BIN" ]; then
    # Launch in Application Window mode without address bar, tabs, or menus
    # Отдельный профиль: иначе запущенный браузер передаёт окно уже
    # работающему экземпляру и сразу завершается — ожидание его закрытия
    # срабатывает мгновенно. На Windows это приводило к тому, что сервер
    # убивали, пока страница ещё грузилась.
    BROWSER_PROFILE="$HERMES_HOME/web_browser_profile"
    mkdir -p "$BROWSER_PROFILE"
    "$CHROMIUM_BIN" --app="$TARGET_URL" --window-size=1400,900         --user-data-dir="$BROWSER_PROFILE" --no-first-run --no-default-browser-check "$@"
else
    # Fallback to standard default browser
    echo "Запуск в обычном браузере: режим приложения (без адресной строки) требует Google Chrome, Chromium или Microsoft Edge."
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$TARGET_URL"
    elif command -v sensible-browser >/dev/null 2>&1; then
        sensible-browser "$TARGET_URL"
    elif command -v firefox >/dev/null 2>&1; then
        firefox "$TARGET_URL"
    else
        echo "Please open $TARGET_URL in your web browser."
    fi
fi

exit 0
