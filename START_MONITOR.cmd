@echo off
chcp 65001 >nul
title AI Broker Monitor
cd /d "%~dp0"

echo AI Broker Monitor
echo.
echo Open this window = monitor is running.
echo Close this window or press Ctrl+C = monitor stops.
echo.

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File ".\scripts\ai_broker.ps1" -Mode Monitor
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo Monitor exited with code: %EXIT_CODE%
if "%EXIT_CODE%"=="0" echo Monitor stopped.
echo.
pause
exit /b %EXIT_CODE%

