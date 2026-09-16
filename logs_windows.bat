@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0logs_windows.ps1" %*
exit /b %errorlevel%

