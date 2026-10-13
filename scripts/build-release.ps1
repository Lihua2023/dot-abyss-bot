param([string]$Python = '', [switch]$SkipReplay)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv-release\Scripts\python.exe' }
$env:PYTHONIOENCODING = 'utf-8'
Push-Location $projectRoot
try {
    & $Python -m pip check
    if ($LASTEXITCODE) { throw 'Dependency check failed' }
    if (-not $SkipReplay) {
        & $Python verify_offline.py
        if ($LASTEXITCODE) { throw 'Offline replay failed' }
    }
    & $Python app.py self-test --gui-check --report validation-output/source-self-test.json
    if ($LASTEXITCODE) { throw 'Source smoke check failed' }
    & $Python verify_packaging.py
    if ($LASTEXITCODE) { throw 'Packaging regressions failed' }
    & $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/DotAbyss.spec
    if ($LASTEXITCODE) { throw 'PyInstaller failed' }
    if ($SkipReplay) {
        & $Python scripts/assemble_release.py --skip-replay
    } else {
        & $Python scripts/assemble_release.py
    }
    if ($LASTEXITCODE) { throw 'Release assembly failed' }
} finally { Pop-Location }
