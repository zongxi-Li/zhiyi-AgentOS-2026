[CmdletBinding()]
param(
  [string]$HomeDir = "$env:LOCALAPPDATA\ZhiyiNative\default",
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $env:LOCALAPPDATA 'ZhiyiNative\python\Scripts\python.exe'
$runtime = Join-Path $PSScriptRoot 'infra\windows\native\persistent_runtime.py'

try {
  foreach ($required in @($python, $runtime, (Join-Path $HomeDir 'environment.json'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Required local runtime file not found: $required"
    }
  }
  if ($CheckOnly) {
    Write-Host 'Local desktop launcher checks passed.'
    exit 0
  }
  Set-Location $repoRoot
  Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
  Write-Host 'Starting local services and Electron. Please wait...' -ForegroundColor Cyan
  Write-Host "Home: $HomeDir"
  & $python $runtime open --home $HomeDir
  if ($LASTEXITCODE -ne 0) { throw "Local startup failed (exit $LASTEXITCODE). See $HomeDir\logs." }
} catch {
  Write-Host $_.Exception.Message -ForegroundColor Red
  if (-not $CheckOnly) { [void](Read-Host 'Press Enter to close this window') }
  exit 1
}
