[CmdletBinding()]
param(
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$desktopDir = Join-Path $repoRoot 'apps\desktop\electron'
$frontendDir = Join-Path $repoRoot 'apps\frontend'

function Pause-Launcher {
  param([string]$Message)
  Write-Host $Message -ForegroundColor Yellow
  Read-Host '按 Enter 关闭此窗口'
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $node) {
  Pause-Launcher '未找到 node.exe，请先安装 Node.js 并确认 node 已加入 PATH。'
  exit 1
}

if (-not (Test-Path (Join-Path $frontendDir 'node_modules\vite\bin\vite.js'))) {
  Pause-Launcher "缺少前端依赖，请先执行：`n  Set-Location `"$frontendDir`"`n  npm ci"
  exit 1
}

if (-not (Test-Path (Join-Path $desktopDir 'node_modules\electron\cli.js'))) {
  Pause-Launcher "缺少 Electron 运行时，请先执行：`n  Set-Location `"$desktopDir`"`n  npm install`n（网络受限时先执行 `$env:ELECTRON_MIRROR='https://npmmirror.com/mirrors/electron/'）"
  exit 1
}

if ($CheckOnly) {
  Write-Host 'Electron 桌面版启动脚本检查通过。' -ForegroundColor Green
  exit 0
}

# electron.exe / node.exe 是通用进程名，只能按命令行包含本仓库 electron 目录来识别
# 残留的开发进程，绝不按进程名清理无关应用。
$staleProcesses = @(
  Get-CimInstance Win32_Process -Filter "Name='electron.exe' OR Name='node.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine.Contains($desktopDir) }
)
foreach ($process in $staleProcesses) {
  Write-Host "正在关闭残留 Electron 开发进程（PID $($process.ProcessId)）..." -ForegroundColor DarkYellow
  Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

$occupiedPort = Get-NetTCPConnection -State Listen -LocalPort 15100 -ErrorAction SilentlyContinue
if ($occupiedPort) {
  Pause-Launcher '15100 端口已经被其他程序占用，请关闭旧的开发窗口后再重试。'
  exit 1
}

Set-Location $desktopDir
. (Join-Path $PSScriptRoot 'infra\windows\native\terminal-env.ps1')
Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
# 外部 shell 可能带 ELECTRON_RUN_AS_NODE=1（例如工具链/调试器注入）；保留它会让
# electron.exe 退化成普通 Node，main.js 里 electron.protocol 为 undefined 而启动失败。
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Write-Host '正在启动知弈 AgentOS 热更新桌面版（Electron）...' -ForegroundColor Cyan
Write-Host '修改 frontend 源码后，Vite 会自动更新桌面窗口。关闭桌面窗口即可结束本次开发运行。' -ForegroundColor Gray

& $node.Source scripts\dev.mjs
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
  Pause-Launcher "Electron 桌面版启动失败，退出码：$exitCode"
}

exit $exitCode
