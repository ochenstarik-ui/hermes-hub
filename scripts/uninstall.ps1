# Hermes Hub PowerShell Uninstaller
# Removes application files and launcher. User data and credentials are preserved by default unless -PurgeUserData is explicitly passed.

[CmdletBinding()]
param(
    [switch]$PurgeUserData = $false
)

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Yellow
Write-Host "               HERMES HUB UNINSTALLER (PowerShell)                    " -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Yellow

$HermesHome = $env:HERMES_HOME
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
    $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}
$TargetDir = Join-Path $env:LOCALAPPDATA "Programs\HermesHub"

Write-Host "[1/3] Removing application binaries..." -ForegroundColor Gray
if (Test-Path $TargetDir) {
    Remove-Item -Path $TargetDir -Recurse -Force -ErrorAction SilentlyContinue
}
$HomeLauncher = Join-Path $HermesHome "HermesHub.exe"
if (Test-Path $HomeLauncher) {
    Remove-Item -Path $HomeLauncher -Force -ErrorAction SilentlyContinue
}

Write-Host "[2/3] Removing plugin integration..." -ForegroundColor Gray
$PluginDir = Join-Path $HermesHome "plugins\antigravity-provider"
if (Test-Path $PluginDir) {
    Remove-Item -Path $PluginDir -Recurse -Force -ErrorAction SilentlyContinue
}

# 3. User Data Handling
if ($PurgeUserData) {
    Write-Host "[3/3] Purging user data (--PurgeUserData specified)..." -ForegroundColor Red
    $ConfigDir = Join-Path $HermesHome "config\router_profiles.yaml"
    if (Test-Path $ConfigDir) { Remove-Item -Path $ConfigDir -Force -ErrorAction SilentlyContinue }
    $AgyProfiles = Join-Path $HermesHome "agy_profiles"
    if (Test-Path $AgyProfiles) { Remove-Item -Path $AgyProfiles -Recurse -Force -ErrorAction SilentlyContinue }
    $CodexProfiles = Join-Path $HermesHome "codex_profiles"
    if (Test-Path $CodexProfiles) { Remove-Item -Path $CodexProfiles -Recurse -Force -ErrorAction SilentlyContinue }
    $OpengoProfiles = Join-Path $HermesHome "opengo_profiles"
    if (Test-Path $OpengoProfiles) { Remove-Item -Path $OpengoProfiles -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "      User data purged."
} else {
    Write-Host "[3/3] Preserving user data and credentials." -ForegroundColor Green
    Write-Host "      Your auth profiles and settings in $HermesHome remain intact."
}

Write-Host "======================================================================" -ForegroundColor Green
Write-Host "             HERMES HUB UNINSTALLED SUCCESSFULLY                      " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
exit 0
