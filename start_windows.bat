@echo off
setlocal

cd /d "%~dp0"

set "HOST=%PPT_SERVICE_HOST%"
if "%HOST%"=="" set "HOST=0.0.0.0"

set "PORT=%PPT_SERVICE_PORT%"
if "%PORT%"=="" set "PORT=8000"

set "LOG_DIR=%PPT_SERVICE_LOG_DIR%"
if "%LOG_DIR%"=="" set "LOG_DIR=%~dp0runtime"

set "PID_FILE=%PPT_SERVICE_PID_FILE%"
if "%PID_FILE%"=="" set "PID_FILE=%LOG_DIR%\service_api.pid"

set "STDOUT_LOG=%PPT_SERVICE_STDOUT_LOG%"
if "%STDOUT_LOG%"=="" set "STDOUT_LOG=%LOG_DIR%\service_api.out.log"

set "STDERR_LOG=%PPT_SERVICE_STDERR_LOG%"
if "%STDERR_LOG%"=="" set "STDERR_LOG=%LOG_DIR%\service_api.err.log"

set "MODE=background"
if /I "%~1"=="--foreground" set "MODE=foreground"
if /I "%~1"=="--background" set "MODE=background"
if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if not "%~1"=="" if /I not "%~1"=="--foreground" if /I not "%~1"=="--background" if /I not "%~1"=="--help" if /I not "%~1"=="-h" (
  echo [ERROR] Unknown argument: %~1
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python is not available in PATH.
  exit /b 1
)

python -c "import uvicorn" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uvicorn is not installed in the current Python environment.
  exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if exist "%PID_FILE%" (
  set /p EXISTING_PID=<"%PID_FILE%"
  if not "%EXISTING_PID%"=="" (
    powershell -NoProfile -Command "try { if (Get-Process -Id %EXISTING_PID% -ErrorAction Stop) { exit 0 } } catch { exit 1 }"
    if not errorlevel 1 (
      echo [ERROR] Service already running with PID %EXISTING_PID%
      echo [INFO] Stdout log: %STDOUT_LOG%
      echo [INFO] Stderr log: %STDERR_LOG%
      exit /b 1
    )
  )
  del "%PID_FILE%" >nul 2>nul
)

echo [INFO] Starting Offline PPT Master service ...
echo [INFO] Open: http://127.0.0.1:%PORT%/frontend

if /I "%MODE%"=="foreground" (
  python -m uvicorn service_api.main:app --host %HOST% --port %PORT%
  exit /b %errorlevel%
)

for /f %%P in ('powershell -NoProfile -Command "$p = Start-Process -FilePath python -ArgumentList @('-m','uvicorn','service_api.main:app','--host','%HOST%','--port','%PORT%') -WorkingDirectory '%CD%' -RedirectStandardOutput '%STDOUT_LOG%' -RedirectStandardError '%STDERR_LOG%' -WindowStyle Hidden -PassThru; $p.Id"') do set "SERVICE_PID=%%P"

if "%SERVICE_PID%"=="" (
  echo [ERROR] Failed to start service in background.
  exit /b 1
)

> "%PID_FILE%" echo %SERVICE_PID%
echo [INFO] Service started in background.
echo [INFO] PID: %SERVICE_PID%
echo [INFO] Stdout log: %STDOUT_LOG%
echo [INFO] Stderr log: %STDERR_LOG%
exit /b 0

:help
echo Usage: start_windows.bat [--foreground ^| --background]
echo.
echo Defaults:
echo   host: %HOST%
echo   port: %PORT%
echo   pid:  %PID_FILE%
echo   out:  %STDOUT_LOG%
echo   err:  %STDERR_LOG%
exit /b 0
