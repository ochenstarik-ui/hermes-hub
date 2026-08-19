# Build HermesHub.exe from C# source code using .NET Framework csc.exe

$CscPath = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $CscPath)) {
    $CscPath = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$SourceFile = Join-Path $ScriptDir "HermesHub.cs"
$OutFile = Join-Path $ScriptDir "HermesHub.exe"

Write-Host "Compiling HermesHub.exe..." -ForegroundColor Cyan
& $CscPath /target:winexe /out:"$OutFile" /r:System.Windows.Forms.dll /r:System.Drawing.dll "$SourceFile"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build SUCCESS: $OutFile" -ForegroundColor Green
} else {
    Write-Error "Build FAILED with exit code $LASTEXITCODE"
}
