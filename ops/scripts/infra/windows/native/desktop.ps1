param(
    [Parameter(Mandatory=$true)][ValidateSet('up','status','down')][string]$Action,
    [Parameter(Mandatory=$true)][string]$RunDir,
    [string]$Workspace,
    [string]$Python = "$env:TEMP\kinlin-n01a-20261028\venv\Scripts\python.exe",
    [switch]$Desktop
)
$ErrorActionPreference = 'Stop'
$nativeArgs = @("$PSScriptRoot\desktop_runtime.py", $Action, '--run-dir', $RunDir)
if ($Workspace) { $nativeArgs += @('--workspace', $Workspace) }
if ($Desktop) { $nativeArgs += '--desktop' }
& $Python @nativeArgs
exit $LASTEXITCODE
