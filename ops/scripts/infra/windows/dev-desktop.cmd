@echo off
chcp 65001 >nul
title Zhiyi Desktop - Hot Reload Dev
rem Launcher for the Tauri desktop dev mode (vite hot reload on port 15100).
rem Repo layout: this script lives at <repo>\ops\scripts\infra\windows\.
cd /d "%~dp0..\..\..\..\apps\desktop"

if not exist "node_modules\.bin\tauri.cmd" (
    echo [dev-desktop] First run: installing desktop dependencies...
    call npm install
    if errorlevel 1 goto :fail
)
if not exist "..\frontend\node_modules\.bin\vite.cmd" (
    echo [dev-desktop] First run: installing frontend dependencies...
    pushd ..\frontend
    call npm install
    if errorlevel 1 goto :fail
    popd
)

echo [dev-desktop] Starting tauri dev (hot reload, devUrl http://127.0.0.1:15100)...
echo [dev-desktop] Close the desktop window or this console to stop.
rem Desktop development must use the 15100 Vite proxy, not a stale shell API URL.
set "VITE_API_BASE_URL="
call npm run dev
goto :end

:fail
echo.
echo [dev-desktop] Failed. See the errors above.

:end
echo.
echo [dev-desktop] Exited. This window stays open so you can read the logs.
pause
