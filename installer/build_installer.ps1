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

Write-Host "Compiling HermesHubSetup.exe..." -ForegroundColor Cyan
& $CscPath /target:winexe /out:"$OutFile" /r:System.Windows.Forms.dll /r:System.Drawing.dll "$SourceFile"

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
