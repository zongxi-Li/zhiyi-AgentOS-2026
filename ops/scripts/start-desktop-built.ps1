param(
  [switch]$Build,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$frontendDir = Join-Path $projectRoot 'appsrontend'
$electronDir = Join-Path $projectRoot 'apps\desktop\electron'
$executable = Join-Path $electronDir 'release\win-unpacked\Zhiyi AgentOS Electron.exe'

if ($CheckOnly) {
  Write-Host "Packaged desktop executable: $executable"
  Write-Host 'Runs the packaged Electron host without Vite. Builds on first use or with -Build.'
  exit 0
}

if ($Build -or -not (Test-Path -LiteralPath $executable)) {
  if (-not (Test-Path (Join-Path $electronDir 'node_modules\electron\cli.js'))) {
    throw 'Missing Electron dependencies. Run npm install in apps/desktop/electron.'
  }
  $previousApiOrigin = [Environment]::GetEnvironmentVariable('VITE_API_BASE_URL', 'Process')
  Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
  try {
    Push-Location $frontendDir
    & npm.cmd run build:electron
    if ($LASTEXITCODE -ne 0) { throw 'Frontend electron build failed.' }
    Pop-Location
    Push-Location $electronDir
    & npm.cmd run pack
    if ($LASTEXITCODE -ne 0) { throw 'Electron pack failed.' }
    Pop-Location
  } finally {
    if ($null -ne $previousApiOrigin) { Set-Item Env:VITE_API_BASE_URL $previousApiOrigin }
    Pop-Location -ErrorAction SilentlyContinue
  }
}

Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
& $executable
exit $LASTEXITCODE
