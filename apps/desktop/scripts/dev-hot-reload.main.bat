@echo off
setlocal EnableExtensions
title 知弈 · 开发版（热更新）
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"

cd /d "C:\Users\LZX\Desktop\kinlin_ai\apps\desktop"
if errorlevel 1 (
    echo   [ERROR] project directory not found.
    pause
    exit /b 1
)

cls
echo(
echo   %ESC%[90m──────────────────────────────────────────%ESC%[0m
echo(
echo     %ESC%[96m● 知弈 AgentOS%ESC%[0m  %ESC%[97m开发版 · 热更新%ESC%[0m
echo(
echo     %ESC%[90mdev server   http://127.0.0.1:15100%ESC%[0m
echo     %ESC%[90m改前端代码即时生效，无需重新编译%ESC%[0m
echo     %ESC%[90m关闭桌面窗口或本窗口即可退出%ESC%[0m
echo(
echo   %ESC%[90m──────────────────────────────────────────%ESC%[0m
echo(

set "KILLED="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :15100 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1 && set "KILLED=1"
)
if defined KILLED (
    echo   %ESC%[33m●%ESC%[0m 已清理 15100 端口上的残留进程
) else (
    echo   %ESC%[32m●%ESC%[0m 端口 15100 就绪
)
echo(
echo   %ESC%[96m»%ESC%[0m 正在启动开发环境，桌面窗口马上弹出…
echo(
rem dev 期 API 走 15100 vite 代理，清空残留环境变量防止压过 .env.desktop
set "VITE_API_BASE_URL="
rem 直连本地 tauri CLI，绕过 npx 的约 3.4 秒解析开销（实测 4.0s vs 0.57s）
call "node_modules\.bin\tauri.cmd" dev
if errorlevel 1 (
    echo(
    echo   %ESC%[91m× 开发环境异常退出。若刚关闭应用属正常，%ESC%[0m
    echo   %ESC%[91m  否则请把上方日志发给开发助手排查%ESC%[0m
    echo(
    pause
) else (
    echo(
    echo   %ESC%[92m√ 开发会话已结束，3 秒后自动关闭本窗口%ESC%[0m
    ping -n 4 127.0.0.1 >nul
)
exit /b 0
