#!/usr/bin/env bash
# ==============================================================================
# Hermes Hub — Linux Installation Script
# Mirrors plugin files, registers .desktop entry, creates application launcher,
# and supports both desktop and headless server environments.
# ==============================================================================

set -e

HUB_VERSION="0.1.1"
DEFAULT_HERMES_HOME="$HOME/.hermes"
HERMES_HOME="${HERMES_HOME:-$DEFAULT_HERMES_HOME}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "======================================================================"
echo "           HERMES HUB INSTALLER (Linux / POSIX)                       "
echo "======================================================================"
echo "Version     : $HUB_VERSION"
echo "Hermes Home : $HERMES_HOME"
echo "Source Root : $REPO_ROOT"
echo ""

# 1. Check / Discover Python Runtime and Hermes Environment
echo "[1/6] Checking Python and Hermes environment..."
PYTHON_BIN=""

if [ -f "$HERMES_HOME/hermes-agent/venv/bin/python3" ]; then
    PYTHON_BIN="$HERMES_HOME/hermes-agent/venv/bin/python3"
elif [ -f "$HERMES_HOME/hermes-agent/venv/bin/python" ]; then
    PYTHON_BIN="$HERMES_HOME/hermes-agent/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Error: Python 3 not found on system. Please install Python 3.9+." >&2
    exit 10
fi

PY_VER="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "      Using Python: $PYTHON_BIN (v$PY_VER)"

# Ensure Hermes Home Directory Structure
mkdir -p "$HERMES_HOME"
mkdir -p "$HERMES_HOME/config"
mkdir -p "$HERMES_HOME/plugins/antigravity-provider/src"
mkdir -p "$HERMES_HOME/plugins/antigravity-provider/assets"
mkdir -p "$HOME/.local/bin"
mkdir -p "$HOME/.local/share/applications"

# 2. Check and Install Dependencies
echo "[2/6] Verifying Python dependencies..."
DEPS_OK=true
"$PYTHON_BIN" -c "import fastapi, uvicorn, pydantic, psutil, yaml; print('DEPS_OK')" >/dev/null 2>&1 || DEPS_OK=false

if [ "$DEPS_OK" != "true" ]; then
    echo "      Installing required packages (fastapi, uvicorn, pydantic, psutil, pyyaml)..."
    "$PYTHON_BIN" -m pip install --no-warn-script-location -q fastapi uvicorn pydantic psutil pyyaml || {
        echo "⚠️ Warning: pip install returned non-zero code. Trying with --user..."
        "$PYTHON_BIN" -m pip install --user --no-warn-script-location -q fastapi uvicorn pydantic psutil pyyaml || true
    }
fi

# 3. Mirror Plugin Files to ~/.hermes/plugins/antigravity-provider (with cleanup of stale files)
echo "[3/6] Deploying plugin source files (mirrored)..."
PLUGIN_SRC="$REPO_ROOT/src/antigravity_provider"
PLUGIN_DST="$HERMES_HOME/plugins/antigravity-provider/src/antigravity_provider"

if [ -d "$PLUGIN_SRC" ]; then
    mkdir -p "$PLUGIN_DST"
    # Use rsync with --delete if available, or python mirroring
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' "$PLUGIN_SRC/" "$PLUGIN_DST/"
    else
        "$PYTHON_BIN" -c "
import os, shutil
src = r'$PLUGIN_SRC'
dst = r'$PLUGIN_DST'
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
"
    fi
else
    echo "❌ Error: Source directory $PLUGIN_SRC not found!" >&2
    exit 12
fi

# Deploy Assets
if [ -d "$REPO_ROOT/assets" ]; then
    mkdir -p "$HERMES_HOME/plugins/antigravity-provider/assets"
    cp -r "$REPO_ROOT/assets/"* "$HERMES_HOME/plugins/antigravity-provider/assets/" 2>/dev/null || true
fi

# Deploy helper scripts. Они лежат в поставке, но раньше не разворачивались,
# поэтому вспомогательных инструментов (например открытия хаба в домашнюю сеть)
# на установленной машине просто не оказывалось.
if [ -d "$REPO_ROOT/scripts" ]; then
    mkdir -p "$HERMES_HOME/scripts"
    cp -r "$REPO_ROOT/scripts/"*.py "$HERMES_HOME/scripts/" 2>/dev/null || true
    cp -r "$REPO_ROOT/scripts/"*.sh "$HERMES_HOME/scripts/" 2>/dev/null || true
fi

# 4. Write Deployment Manifest
echo "[4/6] Writing deployment manifest..."
MANIFEST_FILE="$HERMES_HOME/plugins/antigravity-provider/deployment_manifest.json"
# Коммит берётся из BUILD_COMMIT (кладёт сборщик самораспаковывающегося
# установщика, где git недоступен), иначе — из репозитория. Запасного
# литерала нет намеренно: неизвестный коммит должен читаться как неизвестный,
# а не как чужой чужой номер сборки.
if [ -f "$REPO_ROOT/BUILD_COMMIT" ]; then
    GIT_COMMIT="$(tr -d ' 	
' < "$REPO_ROOT/BUILD_COMMIT")"
else
    GIT_COMMIT="$(cd "$REPO_ROOT" 2>/dev/null && git rev-parse --short HEAD 2>/dev/null || echo 'не определён')"
fi
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)"

cat <<EOF > "$MANIFEST_FILE"
{
  "version": "$HUB_VERSION",
  "deployed_at": "$TIMESTAMP",
  "git_commit": "$GIT_COMMIT",
  "platform": "linux"
}
EOF

# Deploy Template Config only if not existing
if [ ! -f "$HERMES_HOME/config/router_profiles.yaml" ] && [ -f "$REPO_ROOT/config/router_profiles.example.yaml" ]; then
    echo "      Installing default router_profiles.yaml from template..."
    cp "$REPO_ROOT/config/router_profiles.example.yaml" "$HERMES_HOME/config/router_profiles.yaml"
else
    echo "      Preserving existing user router_profiles.yaml."
fi

# 5. Deploy Launcher Executable and .desktop Entry
echo "[5/6] Creating application launcher and .desktop entry..."
LAUNCHER_SRC="$REPO_ROOT/launcher/hermes-hub-web.sh"
if [ ! -f "$LAUNCHER_SRC" ]; then
    LAUNCHER_SRC="$SCRIPT_DIR/hermes-hub-web.sh"
fi

LAUNCHER_BIN="$HOME/.local/bin/hermes-hub-web"
cp "$LAUNCHER_SRC" "$LAUNCHER_BIN"
chmod +x "$LAUNCHER_BIN"

# Also place in ~/.hermes/bin for convenience
mkdir -p "$HERMES_HOME/bin"
cp "$LAUNCHER_SRC" "$HERMES_HOME/bin/hermes-hub-web"
chmod +x "$HERMES_HOME/bin/hermes-hub-web"

# Create .desktop file
DESKTOP_FILE="$HOME/.local/share/applications/hermes-hub-web.desktop"
ICON_PATH="$HERMES_HOME/plugins/antigravity-provider/assets/branding/app/HermesHub.ico"
if [ ! -f "$ICON_PATH" ]; then
    ICON_PATH="utilities-terminal"
fi

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=Hermes Hub Web
GenericName=Multi-Agent & Multi-Provider Control Hub
Comment=Multi-Agent & Multi-Provider Control Hub for Hermes Agent
Exec=$LAUNCHER_BIN
Icon=$ICON_PATH
Terminal=false
Categories=Development;Utility;
StartupNotify=true
StartupWMClass=hermes-hub-web
EOF

chmod +x "$DESKTOP_FILE"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

# 6. Post-install Smoke Test Verification
echo "[6/6] Running post-install verification smoke test..."
"$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$HERMES_HOME/plugins/antigravity-provider/src')
import antigravity_provider.router.web.server
print('HERMES_HUB_LINUX_VERIFY_OK')
" || {
    echo "❌ Error: Post-install verification failed!" >&2
    exit 14
}

echo ""
echo "======================================================================"
echo "       HERMES HUB SUCCESSFULLY INSTALLED ON LINUX!                    "
echo "======================================================================"
echo "Application Launcher : $LAUNCHER_BIN"
echo "Desktop Shortcut     : $DESKTOP_FILE"
echo ""
echo "To launch the Web Application window:"
echo "  $LAUNCHER_BIN"
echo ""
echo "Or open 'Hermes Hub Web' from your Applications menu."
echo "======================================================================"
exit 0
