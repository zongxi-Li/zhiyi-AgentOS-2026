# Read only the purpose-separated terminal transport credential into this process.
$terminalPython = Join-Path $env:LOCALAPPDATA 'ZhiyiNative\python\Scripts\python.exe'
$terminalHome = Join-Path $env:LOCALAPPDATA 'ZhiyiNative\default'
if ($env:KINLIN_NATIVE_HOME) { $terminalHome = $env:KINLIN_NATIVE_HOME }
if ((Test-Path -LiteralPath $terminalPython) -and (Test-Path -LiteralPath (Join-Path $terminalHome 'environment.json'))) {
  $terminalValues = & $terminalPython "$PSScriptRoot\terminal_service.py" --home $terminalHome
  if ($LASTEXITCODE -eq 0) {
    $terminalConfig = ($terminalValues -join "`n") | ConvertFrom-Json
    $env:KINLIN_TERMINAL_ENDPOINT = $terminalConfig.KINLIN_TERMINAL_ENDPOINT
    $env:KINLIN_TERMINAL_TOKEN = $terminalConfig.KINLIN_TERMINAL_TOKEN
  }
  $terminalValues = $null
  $terminalConfig = $null
}
