param([string]$Python = "python", [string]$SkillRoot = "$env:USERPROFILE/.codex/skills/lx-tool-creator")
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & $Python scripts/build_package.py
    if ($LASTEXITCODE -ne 0) { throw "Manifest failed" }
    & $Python "$SkillRoot/scripts/package_release.py" $PSScriptRoot --output "$PSScriptRoot/dist/LXTool-package.zip"
    if ($LASTEXITCODE -ne 0) { throw "Build failed" }
} finally { Pop-Location }
