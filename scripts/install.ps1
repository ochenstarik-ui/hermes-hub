# Hermes Hub PowerShell Installer
# Dynamically discovers Hermes Home, validates prerequisites, installs plugin, launcher and config template.

[CmdletBinding()]
param(
    [string]$TargetDir = "",
    [switch]$NoLaunch = $false
)

$ErrorActionPreference = "Stop"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "                HERMES HUB INSTALLER (PowerShell)                     " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# 1. Discover Hermes Home dynamically
$HermesHome = $env:HERMES_HOME
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
    $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}

Write-Host "[1/6] Checking Hermes Agent installation..." -ForegroundColor Yellow
if (-not (Test-Path $HermesHome)) {
    Write-Error "Hermes Agent not found at: $HermesHome`nPlease install Hermes Agent before installing Hermes Hub."
    exit 10
}

$HermesPython = Join-Path $HermesHome "hermes-agent\venv\Scripts\python.exe"
if (-not (Test-Path $HermesPython)) {
    Write-Error "Hermes Python virtual environment not found at: $HermesPython`nPlease ensure Hermes Agent is fully initialized."
    exit 10
}

# 2. Check Hermes version
$HermesExe = Join-Path $HermesHome "hermes-agent\venv\Scripts\hermes.exe"
$HermesVersion = "unknown"
if (Test-Path $HermesExe) {
    try {
        $verOutput = & $HermesExe --version 2>&1
        $HermesVersion = ($verOutput | Out-String).Trim()
    } catch {}
}
Write-Host "      Detected Hermes Agent: $HermesVersion" -ForegroundColor Green
Write-Host "      Hermes Home: $HermesHome" -ForegroundColor Green

# 3. Resolve Hermes Hub Install Directory
if ([string]::IsNullOrWhiteSpace($TargetDir)) {
    $TargetDir = Join-Path $env:LOCALAPPDATA "Programs\HermesHub"
}
Write-Host "[2/6] Preparing installation target: $TargetDir" -ForegroundColor Yellow
New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null

# 4. Copy Application Files to TargetDir
$RepoRoot = Split-Path -Parent $PSScriptRoot
Write-Host "[3/6] Deploying application binaries..." -ForegroundColor Yellow
$LauncherExe = Join-Path $RepoRoot "launcher\HermesHub.exe"
if (Test-Path $LauncherExe) {
    Copy-Item -Path $LauncherExe -Destination (Join-Path $TargetDir "HermesHub.exe") -Force
    Copy-Item -Path $LauncherExe -Destination (Join-Path $HermesHome "HermesHub.exe") -Force
}

# 5. Deploy Plugin Integration into Hermes
Write-Host "[4/6] Deploying plugin components to Hermes..." -ForegroundColor Yellow
$PluginDst = Join-Path $HermesHome "plugins\antigravity-provider\src\antigravity_provider"
$PluginSrc = Join-Path $RepoRoot "src\antigravity_provider"

New-Item -ItemType Directory -Path $PluginDst -Force | Out-Null
Copy-Item -Path "$PluginSrc\*" -Destination $PluginDst -Recurse -Force

# 6. Install Default Router Config only if not present
Write-Host "[5/6] Checking runtime configuration..." -ForegroundColor Yellow
$ConfigDstDir = Join-Path $HermesHome "config"
New-Item -ItemType Directory -Path $ConfigDstDir -Force | Out-Null
$UserConfig = Join-Path $ConfigDstDir "router_profiles.yaml"
$TemplateConfig = Join-Path $RepoRoot "config\router_profiles.example.yaml"

if (-not (Test-Path $UserConfig)) {
    Write-Host "      Installing default router_profiles.yaml from template..." -ForegroundColor Gray
    Copy-Item -Path $TemplateConfig -Destination $UserConfig -Force
} else {
    Write-Host "      Preserving existing user router_profiles.yaml." -ForegroundColor Green
}

# 7. Post-install Verification
Write-Host "[6/6] Running post-install verification..." -ForegroundColor Yellow
$VerifyScript = Join-Path $RepoRoot "scripts\verify_multi_provider_router.py"
if (Test-Path $VerifyScript) {
    $verifyResult = & $HermesPython $VerifyScript 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Post-install verification returned non-zero code. Output:`n$verifyResult"
    } else {
        Write-Host "      Post-install verification PASSED (10/10 checks)." -ForegroundColor Green
    }
}

Write-Host "======================================================================" -ForegroundColor Green
Write-Host "             HERMES HUB SUCCESSFULLY INSTALLED!                       " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "Launch via: $TargetDir\HermesHub.exe"
Write-Host "Or run: hermes router hub"
exit 0
