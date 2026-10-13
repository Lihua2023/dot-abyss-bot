param([Parameter(Mandatory=$true)][string]$Folder, [string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $projectRoot '.venv-release\Scripts\python.exe' }
& $Python (Join-Path $PSScriptRoot 'verify_release.py') $Folder --report (Join-Path $projectRoot 'validation-output\isolated-release.json')
if ($LASTEXITCODE) { throw 'Release verification failed' }
