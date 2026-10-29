param(
    [Parameter(Mandatory=$true)][ValidateSet('up','status','down')][string]$Action,
    [Parameter(Mandatory=$true)][string]$RunDir,
    [string]$Workspace,
    [string]$Python = "$env:TEMP\kinlin-n01a-20261028\venv\Scripts\python.exe",
    [ValidateSet('tauri','electron')][string]$Shell = 'tauri',
    [switch]$Desktop
)
$ErrorActionPreference = 'Stop'
$nativeArgs = @("$PSScriptRoot\desktop_runtime.py", $Action, '--run-dir', $RunDir)
if ($Workspace) { $nativeArgs += @('--workspace', $Workspace) }
if ($Desktop) { $nativeArgs += '--desktop' }
if ($Desktop -and $Shell) { $env:KINLIN_DESKTOP_SHELL = $Shell }
& $Python @nativeArgs
exit $LASTEXITCODE
