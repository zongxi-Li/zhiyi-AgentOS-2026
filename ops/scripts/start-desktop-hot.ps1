[CmdletBinding()]
param(
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$desktopDir = Join-Path $repoRoot 'apps\desktop'
$frontendDir = Join-Path $repoRoot 'apps\frontend'

function Pause-Launcher {
  param([string]$Message)
  Write-Host $Message -ForegroundColor Yellow
  Read-Host '按 Enter 关闭此窗口'
}

$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
  Pause-Launcher '未找到 npm.cmd，请先安装 Node.js 并确认 npm 已加入 PATH。'
  exit 1
}

if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
  Pause-Launcher "缺少前端依赖，请先执行：`n  Set-Location `"$frontendDir`"`n  npm ci"
  exit 1
}

if (-not (Test-Path (Join-Path $desktopDir 'node_modules'))) {
  Pause-Launcher "缺少桌面依赖，请先执行：`n  Set-Location `"$desktopDir`"`n  npm ci"
  exit 1
}

if ($CheckOnly) {
  Write-Host '热更新桌面版启动脚本检查通过。' -ForegroundColor Green
  exit 0
}

# 防止已有桌面版本与本次开发版同时存在，避免误看旧页面。
$installedProcesses = @(Get-Process -Name 'kinlin-desktop' -ErrorAction SilentlyContinue)

foreach ($process in $installedProcesses) {
  Write-Host "正在关闭已安装桌面版本（PID $($process.Id)）..." -ForegroundColor DarkYellow
  if ($process.MainWindowHandle -ne 0) {
    $null = $process.CloseMainWindow()
    $null = $process.WaitForExit(3000)
  }
  if (-not $process.HasExited) {
    Stop-Process -Id $process.Id
  }
}

$occupiedPort = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue
if ($occupiedPort) {
  Pause-Launcher '3000 端口已经被其他程序占用，请关闭旧的开发窗口后再重试。'
  exit 1
}

Set-Location $desktopDir
Write-Host '正在启动知弈 AgentOS 热更新桌面版...' -ForegroundColor Cyan
Write-Host '修改 frontend 源码后，Vite 会自动更新桌面窗口。关闭桌面窗口即可结束本次开发运行。' -ForegroundColor Gray

& $npm.Source run dev
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
  Pause-Launcher "热更新桌面版启动失败，退出码：$exitCode"
}

exit $exitCode
