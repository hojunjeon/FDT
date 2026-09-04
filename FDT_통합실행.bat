@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title FDT 통합 실행기

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\fdt_launcher.ps1" %*
set "FDT_RC=%ERRORLEVEL%"

if not "%FDT_RC%"=="0" (
  echo.
  echo [종료] 오류로 종료되었습니다. 코드: %FDT_RC%
  pause
)
exit /b %FDT_RC%
