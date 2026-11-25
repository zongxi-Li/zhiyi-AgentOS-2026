@echo off
chcp 65001 >nul
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local-stack.ps1" -Action up -NoPause
if errorlevel 1 (
  echo.
  echo Startup failed. See messages above.
  pause
)
