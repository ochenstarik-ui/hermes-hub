#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — Linux Uninstaller
# Removes application files, plugin integration, launcher and .desktop shortcuts.
# Preserves user data and credentials by default unless --purge-user-data is passed.
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_HERMES_HOME="$HOME/.hermes"
HERMES_HOME="${HERMES_HOME:-$DEFAULT_HERMES_HOME}"

PURGE_USER_DATA=false
for arg in "$@"; do
    if [ "$arg" = "--purge-user-data" ] || [ "$arg" = "-p" ]; then
        PURGE_USER_DATA=true
    fi
done

echo "======================================================================"
echo "           HERMES HUB UNINSTALLER (Linux / POSIX)                     "
echo "======================================================================"
echo "Hermes Home : $HERMES_HOME"
echo ""

# 0. Остановка работающего хаба.
#
# Тот же порядок, что в install-linux.sh, и по той же причине: файлы под
# работающим процессом здесь не просто устаревают, а исчезают. С
# --purge-user-data это ещё и rm -rf каталогов, на которые у живого процесса
# открыты файловые дескрипторы — на Linux это не роняет процесс, но он
# продолжает отвечать по старому порту после «успешного» удаления, и
# следующая попытка что-то с ним сделать бьётся об уже удалённые файлы.
echo "[0/4] Остановка работающего Hermes Hub..."
# shellcheck source=./lib_stop_running_hub.sh
. "$SCRIPT_DIR/lib_stop_running_hub.sh"
stop_running_hub || true
echo ""

# 1. Remove Plugin Integration
echo "[1/4] Removing plugin integration..."
if [ -d "$HERMES_HOME/plugins/antigravity-provider" ]; then
    rm -rf "$HERMES_HOME/plugins/antigravity-provider"
    echo "      Removed $HERMES_HOME/plugins/antigravity-provider"
fi

# 2. Remove Launchers and Shortcuts
echo "[2/4] Removing application launchers and desktop entries..."
rm -f "$HOME/.local/bin/hermes-hub-web"
rm -f "$HERMES_HOME/bin/hermes-hub-web"
rm -f "$HOME/.local/bin/hermes-hub-stop"
rm -f "$HOME/.local/bin/lib_stop_running_hub.sh"
rm -f "$HOME/.local/share/applications/hermes-hub-web.desktop"
rm -f "$HOME/.local/share/applications/hermes-hub-stop.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# 3. User Data Handling
if [ "$PURGE_USER_DATA" = "true" ]; then
    echo "[3/4] Purging user data (--purge-user-data specified)..."
    rm -f "$HERMES_HOME/config/router_profiles.yaml"
    rm -rf "$HERMES_HOME/agy_profiles"
    rm -rf "$HERMES_HOME/codex_profiles"
    rm -rf "$HERMES_HOME/opencode_profiles"
    echo "      User configuration and profiles purged."
else
    echo "[3/4] Preserving user data and credentials."
    echo "      Your router profiles, auth keys, and settings in $HERMES_HOME remain intact."
fi

# 4. Post-uninstall verification: пойманный хаб действительно молчит.
echo "[4/4] Verifying no hub process remains..."
REMAINING="$(pgrep -u "$(id -u)" -f "antigravity_provider.router.web|hermes_hub_web_entry" 2>/dev/null | tr '\n' ' ')"
if [ -n "$REMAINING" ]; then
    echo "      ⚠ Всё ещё работает: $REMAINING — удаление файлов это не остановило."
else
    echo "      Хаб не работает."
fi

echo ""
echo "======================================================================"
echo "       HERMES HUB UNINSTALLED SUCCESSFULLY FROM LINUX                 "
echo "======================================================================"
exit 0
