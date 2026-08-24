# Compile HermesHubSetup.exe and package dist release

$CscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $CscPath)) {
    $CscPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot = Split-Path -Parent $ScriptDir
$SourceFile = Join-Path $ScriptDir "HermesHubSetup.cs"
$DistDir = Join-Path $RepoRoot "dist"
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
$OutFile = Join-Path $DistDir "HermesHubSetup.exe"

$LauncherDir = Join-Path $RepoRoot "launcher"
$HubCs = Join-Path $LauncherDir "HermesHub.cs"
$HubWebCs = Join-Path $LauncherDir "HermesHubWeb.cs"

Write-Host "Compiling native launchers..." -ForegroundColor Cyan
if (Test-Path $HubCs) {
    $HubExe = Join-Path $LauncherDir "HermesHub.exe"
    & $CscPath /target:winexe /out:"$HubExe" /r:System.Windows.Forms.dll /r:System.Drawing.dll "$HubCs"
}
if (Test-Path $HubWebCs) {
    $HubWebExe = Join-Path $LauncherDir "HermesHubWeb.exe"
    & $CscPath /target:winexe /out:"$HubWebExe" /r:System.Windows.Forms.dll /r:System.Drawing.dll "$HubWebCs"
}

# Собираем полезную нагрузку: всё, что нужно PerformInstall на целевой машине.
# Она вшивается в exe ресурсом, чтобы установщик был одним файлом и не требовал
# копировать репозиторий.
Write-Host "Packing payload..." -ForegroundColor Cyan
$PayloadDir = Join-Path $env:TEMP ("hubpayload_" + [guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Force $PayloadDir | Out-Null
foreach ($item in @("src", "launcher", "assets", "config", "scripts")) {
    $srcPath = Join-Path $RepoRoot $item
    if (Test-Path $srcPath) {
        Copy-Item $srcPath -Destination (Join-Path $PayloadDir $item) -Recurse -Force
    }
}
# Каталоги сборки и кеши в дистрибутив не нужны.
Get-ChildItem $PayloadDir -Recurse -Directory -Include "__pycache__", ".venv", "node_modules" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$PayloadZip = Join-Path $env:TEMP "hub_payload.zip"
if (Test-Path $PayloadZip) { Remove-Item $PayloadZip -Force }
Compress-Archive -Path (Join-Path $PayloadDir "*") -DestinationPath $PayloadZip -CompressionLevel Optimal
$payloadKB = [int]((Get-Item $PayloadZip).Length / 1KB)
Write-Host "Payload packed: $payloadKB KB" -ForegroundColor Gray

Write-Host "Compiling HermesHubSetup.exe..." -ForegroundColor Cyan
& $CscPath /target:winexe /out:"$OutFile" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.IO.Compression.FileSystem.dll /resource:"$PayloadZip",payload "$SourceFile"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Installer compiled successfully: $OutFile" -ForegroundColor Green
    
    # Generate SHA256 Checksums
    $sha256 = (Get-FileHash -Path $OutFile -Algorithm SHA256).Hash
    $checksumContent = "$sha256  HermesHubSetup.exe"
    $checksumFile = Join-Path $DistDir "checksums.txt"
    Set-Content -Path $checksumFile -Value $checksumContent -Encoding UTF8
    Write-Host "Generated checksum: $checksumFile" -ForegroundColor Green
    Write-Host "SHA256: $sha256" -ForegroundColor Gray
} else {
    Write-Error "Installer compilation FAILED with exit code $LASTEXITCODE"
}

Remove-Item $PayloadDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PayloadZip -Force -ErrorAction SilentlyContinue
