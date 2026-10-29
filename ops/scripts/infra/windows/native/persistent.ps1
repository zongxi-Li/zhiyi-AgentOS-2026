param(
    [Parameter(Mandatory=$true)][ValidateSet('init','up','status','down','recover','backup','restore')][string]$Action,
    [string]$HomeDir = "$env:LOCALAPPDATA\ZhiyiNative\default",
    [string]$Python = "$env:LOCALAPPDATA\ZhiyiNative\python\Scripts\python.exe",
    [string]$PostgresBin = "$env:LOCALAPPDATA\ZhiyiNative\dependencies\postgresql-15.19\pgsql\bin",
    [string]$Memurai = "$env:LOCALAPPDATA\ZhiyiNative\dependencies\memurai-4.1.2\memurai.exe",
    [string]$ProviderKeyFile,
    [string]$Workspace,
    [string]$Snapshot,
    [ValidateSet('tauri','electron')][string]$Shell = 'tauri',
    [switch]$Desktop
)
$ErrorActionPreference = 'Stop'
$nativeArgs = @("$PSScriptRoot\persistent_runtime.py",$Action,'--home',$HomeDir)
if ($Action -eq 'init') {
    $nativeArgs += @('--postgres-bin',$PostgresBin,'--memurai',$Memurai)
    if ($ProviderKeyFile) { $nativeArgs += @('--provider-key-file',$ProviderKeyFile) }
    if ($Workspace) { $nativeArgs += @('--workspace',$Workspace) }
}
if ($Desktop) { $nativeArgs += '--desktop' }
if ($Desktop -and $Shell) { $env:KINLIN_DESKTOP_SHELL = $Shell }
if ($Snapshot) { $nativeArgs += @('--snapshot',$Snapshot) }
& $Python @nativeArgs
exit $LASTEXITCODE
