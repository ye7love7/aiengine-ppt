@echo off
setlocal

cd /d "%~dp0"

set "LOG_DIR=%PPT_SERVICE_LOG_DIR%"
if "%LOG_DIR%"=="" set "LOG_DIR=%~dp0runtime"

set "PID_FILE=%PPT_SERVICE_PID_FILE%"
if "%PID_FILE%"=="" set "PID_FILE=%LOG_DIR%\service_api.pid"

if not exist "%PID_FILE%" (
  echo [INFO] No PID file found. Service may already be stopped.
  exit /b 0
)

set /p SERVICE_PID=<"%PID_FILE%"
if "%SERVICE_PID%"=="" (
  echo [INFO] PID file is empty. Removing stale PID file.
  del "%PID_FILE%" >nul 2>nul
  exit /b 0
)

powershell -NoProfile -Command "try { Stop-Process -Id %SERVICE_PID% -Force -ErrorAction Stop; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo [INFO] Process %SERVICE_PID% is not running or could not be stopped. Removing stale PID file.
) else (
  echo [INFO] Stopped service PID %SERVICE_PID%
)

del "%PID_FILE%" >nul 2>nul
exit /b 0
