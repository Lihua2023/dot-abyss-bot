param([switch]$Observe, [switch]$Verify, [string]$Config = 'config.json')
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$releasePython = Join-Path $PSScriptRoot '.venv-release\Scripts\python.exe'
if (Test-Path -LiteralPath $releasePython) {
    $runnerPython = $releasePython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $runnerPython = (py -3.12 -c 'import sys;print(sys.executable)').Trim()
    if ($LASTEXITCODE) { throw 'Please install Python 3.12 x64 with Tcl/Tk' }
} else {
    $runnerPython = (Get-Command python -ErrorAction Stop).Source
}
if ($Verify) {
    & $runnerPython (Join-Path $PSScriptRoot 'verify_offline.py')
} else {
    $configPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $PSScriptRoot $Config }
    if ($Observe) {
        & $runnerPython (Join-Path $PSScriptRoot 'app.py') observe --config $configPath --delay 8
    } else {
        & $runnerPython (Join-Path $PSScriptRoot 'app.py') settings --config $configPath
    }
}
exit $LASTEXITCODE
