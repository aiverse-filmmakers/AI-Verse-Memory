$ErrorActionPreference = "Stop"

$Target = if ($env:AI_VERSE_MEMORY_TARGET) { $env:AI_VERSE_MEMORY_TARGET } else { (Get-Location).Path }
$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { $null }
$LocalInstaller = if ($ScriptRoot) { Join-Path $ScriptRoot "scripts\install.py" } else { $null }
$LocalManifest = if ($ScriptRoot) { Join-Path $ScriptRoot "manifest.json" } else { $null }

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

$UseLocal = $false
if ($LocalInstaller -and $LocalManifest -and (Test-Path $LocalInstaller) -and (Test-Path $LocalManifest)) {
    $ManifestText = Get-Content -Raw -Path $LocalManifest -ErrorAction SilentlyContinue
    if ($ManifestText -match '"name"\s*:\s*"ai-verse-memory"') { $UseLocal = $true }
}

if ($UseLocal) {
    Run-Python @($LocalInstaller, "--target", $Target, "--source-dir", $ScriptRoot)
    exit 0
}

# `irm <install.ps1> | iex` has no PSScriptRoot. Download the installer entrypoint,
# stable installer payload, and shared compatibility classifier together.
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-verse-memory-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $Temp | Out-Null
try {
    $Base = "https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/scripts"
    foreach ($File in @("install.py", "install_engine.py", "os_compat.py")) {
        Invoke-WebRequest -UseBasicParsing -Uri "$Base/$File" -OutFile (Join-Path $Temp $File)
    }
    Run-Python @((Join-Path $Temp "install.py"), "--target", $Target)
} finally {
    Remove-Item -Recurse -Force $Temp -ErrorAction SilentlyContinue
}
