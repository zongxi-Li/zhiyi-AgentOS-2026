param(
  [switch]$Build,
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$desktopDir = Join-Path $projectRoot 'apps\desktop'
$cargo = Get-Command cargo -ErrorAction Stop
$npm = Get-Command npm.cmd -ErrorAction Stop

Push-Location (Join-Path $desktopDir 'src-tauri')
try {
  $metadata = & $cargo.Source metadata --no-deps --format-version 1
  if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve the desktop build directory.' }
  $targetDir = ($metadata | ConvertFrom-Json).target_directory
} finally { Pop-Location }
$executable = Join-Path $targetDir 'release\kinlin-desktop.exe'

if ($CheckOnly) {
  Write-Host "Built desktop executable: $executable"
  Write-Host 'Loads bundled assets without Vite. Builds on first use or with -Build.'
  exit 0
}

if ($Build -or -not (Test-Path -LiteralPath $executable)) {
  if (-not (Test-Path -LiteralPath (Join-Path $desktopDir 'node_modules'))) { throw 'Missing desktop dependencies. Run npm ci in apps/desktop.' }
  $previousApiOrigin = [Environment]::GetEnvironmentVariable('VITE_API_BASE_URL', 'Process')
  Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
  Push-Location $desktopDir
  try {
    & $npm.Source run build -- --no-bundle
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
  } finally {
    Pop-Location
    if ($null -ne $previousApiOrigin) { $env:VITE_API_BASE_URL = $previousApiOrigin }
  }
}
Start-Process -FilePath $executable -WorkingDirectory $desktopDir
