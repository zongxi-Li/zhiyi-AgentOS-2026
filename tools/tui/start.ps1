#!/usr/bin/env pwsh
param(
    [ValidateSet("lawyer", "teacher", "programmer", "writer")]
    [string]$Role = "lawyer",
    # N03 persistent_runtime 的 AI 端口（默认 18761）
    [int]$Port = 18761
)

$ErrorActionPreference = "Stop"
$PYTHON = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $PYTHON) {
    throw "python.exe 不在 PATH；请先安装 Python 3.14 并把 python 加入 PATH。"
}
$TUI_SRC = Join-Path $PSScriptRoot "src"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$TUI_SRC;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $TUI_SRC
}

function Test-HttpHealth {
    param([int]$HealthPort)

    $client = [System.Net.Http.HttpClient]::new()
    try {
        $client.Timeout = [TimeSpan]::FromSeconds(2)
        $url = "http://127.0.0.1:$HealthPort/health"
        $response = $client.GetAsync(
            $url,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        try {
            return $response.IsSuccessStatusCode
        } finally {
            $response.Dispose()
        }
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " ZhiYi AgentOS TUI Launcher (native N03)" -ForegroundColor Cyan
Write-Host " Role: $Role  |  API: http://127.0.0.1:$($Port)/ai" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# TUI 不在本脚本内拉起/监管后端：N03 persistent.ps1 是唯一栈生命周期 owner。
Write-Host ""
Write-Host "[1/2] Checking native AgentOS backend on port $Port..." -NoNewline
$ok = $false
for ($i = 0; $i -lt 15; $i++) {
    if (Test-HttpHealth $Port) {
        Write-Host " OK" -ForegroundColor Green
        $ok = $true
        break
    }
    Write-Host "." -NoNewline
    Start-Sleep -Milliseconds 1000
}
if (-not $ok) {
    Write-Host " UNAVAILABLE" -ForegroundColor Red
    Write-Host "       Start the N03 persistent stack first:" -ForegroundColor Red
    Write-Host "       .\ops\scripts\infra\windows\native\persistent.ps1 -Action up" -ForegroundColor Red
    exit 1
}

Write-Host "[2/2] Starting TUI..." -ForegroundColor Yellow
$env:AGENTOS_API_URL = "http://127.0.0.1:$Port/ai"
& $PYTHON -m kinlin_tui.app os --role $Role

Write-Host "Done." -ForegroundColor Green
