$ErrorActionPreference = "Stop"

$BaseUrl = "https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main"
$Target = if ($env:AI_VERSE_MEMORY_TARGET) { $env:AI_VERSE_MEMORY_TARGET } else { (Get-Location).Path }
$Runtime = Join-Path $Target ".ai-verse-memory"
$Marker = "AI-VERSE-MEMORY:START"

function Fetch-File([string]$Url, [string]$Destination) {
    $parent = Split-Path -Parent $Destination
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
}

$Python = Get-Command python -ErrorAction SilentlyContinue
$UsePyLauncher = $false
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
    if ($Python) { $UsePyLauncher = $true }
}
if (-not $Python) {
    throw "Python 3 is required. Install Python, then rerun this installer."
}

function Run-Python([string[]]$Arguments) {
    if ($UsePyLauncher) {
        & $Python.Source -3 @Arguments
    } else {
        & $Python.Source @Arguments
    }
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE" }
}

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "scenarios") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "evidence") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "state") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Target ".claude\skills\ai-verse-memory") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Target ".agents\skills\ai-verse-memory") | Out-Null

Fetch-File "$BaseUrl/scripts/memory.py" (Join-Path $Runtime "memory.py")
Fetch-File "$BaseUrl/protocol/MEMORY-PROTOCOL.md" (Join-Path $Runtime "MEMORY-PROTOCOL.md")
Fetch-File "$BaseUrl/migration/MIGRATION.md" (Join-Path $Runtime "MIGRATION.md")
Fetch-File "$BaseUrl/templates/scenario.md" (Join-Path $Runtime "SCENARIO-TEMPLATE.md")
Fetch-File "$BaseUrl/SKILL.md" (Join-Path $Target ".claude\skills\ai-verse-memory\SKILL.md")
Fetch-File "$BaseUrl/SKILL.md" (Join-Path $Target ".agents\skills\ai-verse-memory\SKILL.md")

$Profile = Join-Path $Runtime "profile.md"
if (-not (Test-Path $Profile)) {
    Fetch-File "$BaseUrl/templates/profile.md" $Profile
}

$ProtocolBlock = @"

<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, project state, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->
"@

function Add-Protocol([string]$Path) {
    if (-not (Test-Path $Path)) { New-Item -ItemType File -Force -Path $Path | Out-Null }
    $existing = Get-Content -Raw -Path $Path -ErrorAction SilentlyContinue
    if ($null -eq $existing -or -not $existing.Contains($Marker)) {
        Add-Content -Path $Path -Value $ProtocolBlock -Encoding UTF8
    }
}

Add-Protocol (Join-Path $Target "CLAUDE.md")
Add-Protocol (Join-Path $Target "AGENTS.md")

$GitIgnore = Join-Path $Target ".gitignore"
if (-not (Test-Path $GitIgnore)) { New-Item -ItemType File -Force -Path $GitIgnore | Out-Null }
$GitIgnoreText = Get-Content -Raw -Path $GitIgnore -ErrorAction SilentlyContinue
if ($null -eq $GitIgnoreText -or -not (($GitIgnoreText -split "`r?`n") -contains ".ai-verse-memory/")) {
    Add-Content -Path $GitIgnore -Value "`n# AI-Verse Memory local runtime and personal memory`n.ai-verse-memory/" -Encoding UTF8
}

$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
$HermesHome = Join-Path $HOME ".hermes"
if ($Hermes -or (Test-Path $HermesHome)) {
    $HermesSkill = Join-Path $HermesHome "skills\ai-verse\ai-verse-memory"
    New-Item -ItemType Directory -Force -Path $HermesSkill | Out-Null
    Fetch-File "$BaseUrl/SKILL.md" (Join-Path $HermesSkill "SKILL.md")
    Write-Host "Installed Hermes skill: $HermesSkill\SKILL.md"
}

Push-Location $Target
try {
    Run-Python @(".ai-verse-memory/memory.py", "init")
    Run-Python @(".ai-verse-memory/memory.py", "doctor")
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "AI-Verse Memory installed in: $Target"
Write-Host "Claude skill: .claude/skills/ai-verse-memory/SKILL.md"
Write-Host "Codex skill:  .agents/skills/ai-verse-memory/SKILL.md"
Write-Host "Memory store: .ai-verse-memory/ (Git-ignored by default)"
Write-Host ""
Write-Host "If this Agent-OS already contains useful historical context, ask your agent:"
Write-Host '  "Run the AI-Verse Memory initial migration for this repository."'
Write-Host ""
Write-Host "Otherwise memory is ready for new work immediately."
