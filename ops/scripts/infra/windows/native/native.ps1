param(
    [Parameter(Mandatory=$true)][ValidateSet('fixtures','preflight','up','status','down','smoke')][string]$Action,
    [Parameter(Mandatory=$true)][string]$RunDir,
    [string]$Python = 'python',
    [int]$AiPort = 18761,
    [int]$HostPort = 18765
)
$ErrorActionPreference = 'Stop'
& $Python "$PSScriptRoot\native_runtime.py" $Action --run-dir $RunDir --ai-port $AiPort --host-port $HostPort
exit $LASTEXITCODE
