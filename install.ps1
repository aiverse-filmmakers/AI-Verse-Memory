$ErrorActionPreference = "Stop"

$Target = if ($env:AI_VERSE_MEMORY_TARGET) { $env:AI_VERSE_MEMORY_TARGET } else { (Get-Location).Path }
$LocalInstaller = Join-Path $PSScriptRoot "scripts\install.py"

$Python = Get-Command python -ErrorAction SilentlyContinue
$UsePyLauncher = $false
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if ($Python) { $UsePyLauncher = $true }
}
if (-not $Python) { throw "Python 3 is required. Install Python, then rerun this installer." }

function Run-Python([string[]]$Arguments) {
    if ($UsePyLauncher) { & $Python.Source -3 @Arguments }
    else { & $Python.Source @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE" }
}

if (Test-Path $LocalInstaller) {
    Run-Python @($LocalInstaller, "--target", $Target, "--source-dir", $PSScriptRoot)
    exit 0
}

$Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-verse-memory-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Temp | Out-Null
try {
    $Installer = Join-Path $Temp "install.py"
    Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/scripts/install.py" -OutFile $Installer
    Run-Python @($Installer, "--target", $Target)
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
