#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — Linux Uninstaller
# Removes application files, plugin integration, launcher and .desktop shortcuts.
# Preserves user data and credentials by default unless --purge-user-data is passed.
# ==============================================================================

set -e

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

# 1. Remove Plugin Integration
echo "[1/3] Removing plugin integration..."
if [ -d "$HERMES_HOME/plugins/antigravity-provider" ]; then
    rm -rf "$HERMES_HOME/plugins/antigravity-provider"
    echo "      Removed $HERMES_HOME/plugins/antigravity-provider"
fi

# 2. Remove Launchers and Shortcuts
echo "[2/3] Removing application launchers and desktop entries..."
rm -f "$HOME/.local/bin/hermes-hub-web"
rm -f "$HERMES_HOME/bin/hermes-hub-web"
rm -f "$HOME/.local/share/applications/hermes-hub-web.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# 3. User Data Handling
if [ "$PURGE_USER_DATA" = "true" ]; then
    echo "[3/3] Purging user data (--purge-user-data specified)..."
    rm -f "$HERMES_HOME/config/router_profiles.yaml"
    rm -rf "$HERMES_HOME/agy_profiles"
    rm -rf "$HERMES_HOME/codex_profiles"
    rm -rf "$HERMES_HOME/opencode_profiles"
    echo "      User configuration and profiles purged."
else
    echo "[3/3] Preserving user data and credentials."
    echo "      Your router profiles, auth keys, and settings in $HERMES_HOME remain intact."
fi

echo ""
echo "======================================================================"
echo "       HERMES HUB UNINSTALLED SUCCESSFULLY FROM LINUX                 "
echo "======================================================================"
exit 0
