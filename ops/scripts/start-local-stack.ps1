[CmdletBinding()]
param(
  # 动作：up=启动服务栈 / down=停止 / status=查看状态 / restart=重启 / recover=停后重起（保留数据）
  [ValidateSet('up','down','status','restart','recover')][string]$Action = 'up',
  # 指定 home 目录；不传时自动选择（见下方说明）
  [string]$HomeDir,
  # 显式切回旧的 default home（仅当它已完成 C2 schema 升级后使用）
  [switch]$UseDefaultHome,
  # 同时拉起 Electron 桌面窗口；默认只启动无界面的服务栈
  [switch]$Desktop,
  # 启动失败时不暂停（给自动化调用用）
  [switch]$NoPause
)

# ---------------------------------------------------------------------------
# 知弈 AgentOS · 本地一键启动 / 停止（N03 原生栈）
#
# 关于 home 的选择：
#   - 默认优先使用 %LOCALAPPDATA%\ZhiyiNative\verify-home —— 这是从旧 home
#     提取模型密钥后全新初始化的干净 home，已实测可完整启动（7 服务 + 真实对话）。
#   - 旧的 default home 停留在 C2 旧 schema（缺 workspace 投影触发器），启动器按
#     安全策略拒绝自动修复；如已完成正式升级，可用 -UseDefaultHome 切回。
#   - 也可直接用 -HomeDir 指定任意 home。
#
# 典型用法：
#   .\ops\scripts\start-local-stack.ps1                    # 启动（默认 home）
#   .\ops\scripts\start-local-stack.ps1 -Action down       # 停止
#   .\ops\scripts\start-local-stack.ps1 -Action status     # 状态 + 健康探测
#   .\ops\scripts\start-local-stack.ps1 -Action restart    # 重启
#   .\ops\scripts\start-local-stack.ps1 -Desktop           # 连桌面窗口一起起
#   .\ops\scripts\start-local-stack.ps1 -UseDefaultHome    # 用旧 default home
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$nativeRoot = Join-Path $env:LOCALAPPDATA 'ZhiyiNative'
$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$entry      = Join-Path $repoRoot 'ops\scripts\infra\windows\native\persistent.ps1'
$python     = Join-Path $nativeRoot 'python\Scripts\python.exe'
$defaultHome  = Join-Path $nativeRoot 'default'
$verifiedHome = Join-Path $nativeRoot 'verify-home'

if (-not $HomeDir) {
  if ($UseDefaultHome)               { $HomeDir = $defaultHome }
  elseif (Test-Path (Join-Path $verifiedHome 'environment.json')) { $HomeDir = $verifiedHome }
  else                               { $HomeDir = $defaultHome }
}

function Write-Step([string]$msg) { Write-Host "[知弈] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[知弈] $msg" -ForegroundColor Green }
function Write-Warn2([string]$msg) { Write-Host "[知弈] $msg" -ForegroundColor Yellow }

# Windows PowerShell 5.1 会把外部进程写到 stderr 的内容升级成终止性错误（受
# $ErrorActionPreference='Stop' 影响）。这里临时降级，避免启动器/探测脚本的正常
# stderr 输出把脚本打断，同时保留真实退出码。
function Invoke-Native([scriptblock]$Block) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    # 输出直接送到宿主控制台，避免外部命令的 stdout 被函数当成返回值收集，
    # 污染后面的退出码判断（否则 $code 会变成「JSON + 退出码」数组）。
    & $Block | Out-Host
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prev
  }
}

try {
  foreach ($required in @($python, $entry)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "缺少必需文件：$required`n请先按 README「Windows 原生启动（N03）」第 1-2 步准备依赖。"
    }
  }
  if (-not (Test-Path -LiteralPath (Join-Path $HomeDir 'environment.json') -PathType Leaf)) {
    throw "home 尚未初始化：$HomeDir`n请先执行一次 init（见 README），或换一个已初始化的 home。"
  }

  Write-Step "动作=$Action  Home=$HomeDir"

  $realAction = $Action
  if ($Action -eq 'restart') {
    Write-Step 'restart = 先 down 再 up...'
    if ($Desktop) { $null = Invoke-Native { & $entry down -HomeDir $HomeDir -Python $python -Desktop } }
    else          { $null = Invoke-Native { & $entry down -HomeDir $HomeDir -Python $python } }
    $realAction = 'up'
  }

  # 端口清单（与后端构建复制的同一份合同），用于 TCP 探测和展示
  $portsFile = Join-Path $repoRoot 'apps\backend\src\shared\runtime-defaults.json'
  $ports = $null
  if (Test-Path -LiteralPath $portsFile) {
    $ports = (Get-Content $portsFile -Raw -Encoding UTF8 | ConvertFrom-Json).ports
  }

  # 1 秒 TCP 探测：核心服务是否有端口在监听。用于两处：
  #   1) up 幂等——已经在跑就不再重复启动（启动器会拒绝并报 "already owns running processes"）
  #   2) 全停时跳过下面的长时间 HTTP 健康探测
  function Test-StackListening {
    if (-not $ports) { return $false }
    foreach ($p in @($ports.backend, $ports.ai, $ports.frontend)) {
      $client = New-Object System.Net.Sockets.TcpClient
      try {
        $iar = $client.BeginConnect('127.0.0.1', [int]$p, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(1000) -and $client.Connected) { return $true }
      } catch {} finally { $client.Close() }
    }
    return $false
  }
  $anyListening = Test-StackListening

  $skipLaunch = $false
  if ($realAction -eq 'up' -and $anyListening) {
    Write-Warn2 '检测到服务已在运行，跳过重复 up（如需彻底重启请用 -Action restart / recover）。'
    $skipLaunch = $true
    $code = 0
  }

  if (-not $skipLaunch) {
    if ($Desktop) { $code = Invoke-Native { & $entry $realAction -HomeDir $HomeDir -Python $python -Desktop } }
    else          { $code = Invoke-Native { & $entry $realAction -HomeDir $HomeDir -Python $python } }
  }
  # status 动作会用非 0 退出码表达「服务当前是 DOWN」——这是合法查询结果，不是错误。
  if ($code -ne 0 -and $realAction -ne 'status') {
    throw "启动器 $realAction 失败（exit=$code）。日志：$HomeDir\logs"
  }
  # up/recover 成功后服务刚起来，重新探测刷新状态，否则会用启动前的旧值错误跳过健康探测。
  if ((-not $skipLaunch) -and ($realAction -in @('up','recover'))) {
    $anyListening = Test-StackListening
  }

  if ($Action -in @('up','restart','status','recover')) {
    Write-Host ''
    if (-not $anyListening) {
      Write-Warn2 '当前没有服务在监听（栈处于 DOWN 状态）。健康探测跳过；请先执行 -Action up 启动。'
    } else {
    Write-Step '健康探测...'
    $probe = @'
import json, os, sys, time, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
headers = {"Content-Type":"application/json","Origin":"kinlin-app://shell","X-Zhiyi-Local-Request":"1"}
targets = [
    ("backend", "http://127.0.0.1:%s/api/health/ready"),
    ("ai",      "http://127.0.0.1:%s/health"),
    ("frontend","http://127.0.0.1:%s/"),
]
with open(sys.argv[1], encoding="utf-8") as f:
    ports = json.load(f)["ports"]
ok = 0
for name, tmpl in targets:
    url = tmpl % ports[name]
    last = ""
    for _ in range(12):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with opener.open(req, timeout=4) as r:
                r.read(200)
                print("  %-9s HTTP %d  %s" % (name, r.status, url))
                ok += 1
                break
        except Exception as e:
            last = type(e).__name__
            time.sleep(1)
    else:
        print("  %-9s FAILED (%s)  %s" % (name, last, url))
print("HEALTHY=%d/3" % ok)
'@
    $probeFile = Join-Path $env:TEMP 'zhiyi-probe-stack.py'
    [System.IO.File]::WriteAllText($probeFile, $probe, (New-Object System.Text.UTF8Encoding $false))
    if ($ports) {
      $null = Invoke-Native { & $python $probeFile $portsFile }
    } else {
      Write-Warn2 '未找到 runtime-defaults.json，跳过健康探测'
    }
    Remove-Item $probeFile -ErrorAction SilentlyContinue
    } # end else (健康探测)

    Write-Host ''
    Write-Ok '服务地址：'
    if ($ports) {
      Write-Host "  前端界面      http://127.0.0.1:$($ports.frontend)/"
      Write-Host "  后端 API      http://127.0.0.1:$($ports.backend)/api/health/ready"
      Write-Host "  AI 内核       http://127.0.0.1:$($ports.ai)/health"
      Write-Host "  Host          http://127.0.0.1:$($ports.host)/"
      Write-Host "  Terminal      http://127.0.0.1:$($ports.terminal)/"
      Write-Host "  PostgreSQL    127.0.0.1:$($ports.postgres)   Redis 127.0.0.1:$($ports.redis)"
      if ($Desktop) { Write-Host "  Electron CDP  127.0.0.1:$($ports.debug)" }
    }
    if ($anyListening) {
      Write-Warn2 '服务在当前窗口的进程树内运行；关闭窗口即停止。需要常驻请保持窗口打开。'
    }
  }

} catch {
  Write-Host "[知弈] $($_.Exception.Message)" -ForegroundColor Red
  Write-Warn2 '排查建议：先跑 -Action status，再看日志目录，必要时用 -Action recover（数据会保留）。'
  if (-not $NoPause) { [void](Read-Host '启动失败，按回车关闭窗口') }
  exit 1
}
