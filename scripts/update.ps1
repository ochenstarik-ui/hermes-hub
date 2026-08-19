# Hermes Hub PowerShell Updater
# Updates application binaries, launcher and plugin files while preserving all user credentials, auth.json, and router_profiles.yaml.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "                HERMES HUB UPDATER (PowerShell)                       " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$HermesHome = $env:HERMES_HOME
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
    $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}

if (-not (Test-Path $HermesHome)) {
    Write-Error "Hermes Agent directory not found at $HermesHome. Cannot update."
    exit 10
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $env:LOCALAPPDATA "Programs\HermesHub"

Write-Host "[1/3] Updating application binaries..." -ForegroundColor Yellow
$LauncherExe = Join-Path $RepoRoot "launcher\HermesHub.exe"
if (Test-Path $LauncherExe) {
    Copy-Item -Path $LauncherExe -Destination (Join-Path $TargetDir "HermesHub.exe") -Force
    Copy-Item -Path $LauncherExe -Destination (Join-Path $HermesHome "HermesHub.exe") -Force
}

Write-Host "[2/3] Updating plugin code..." -ForegroundColor Yellow
$PluginDst = Join-Path $HermesHome "plugins\antigravity-provider\src\antigravity_provider"
$PluginSrc = Join-Path $RepoRoot "src\antigravity_provider"
Copy-Item -Path "$PluginSrc\*" -Destination $PluginDst -Recurse -Force

Write-Host "[3/3] Preserving user credentials and router configuration..." -ForegroundColor Green
Write-Host "      Auth files, API keys, and router_profiles.yaml kept untouched."

Write-Host "======================================================================" -ForegroundColor Green
Write-Host "             HERMES HUB SUCCESSFULLY UPDATED!                         " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
exit 0
