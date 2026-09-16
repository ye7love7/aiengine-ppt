@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if not "%~1"=="" if /I not "%~1"=="--foreground" if /I not "%~1"=="--background" (
  echo [ERROR] Unknown argument: %~1
  exit /b 1
)
echo [INFO] Stopping service ...
call "%~dp0stop_windows.bat"
if errorlevel 1 exit /b %errorlevel%

set "PORT=%PPT_SERVICE_PORT%"
if "%PORT%"=="" set "PORT=8000"
rem If the PID file was lost, clean up an orphaned project uvicorn listener.
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; foreach ($x in $c) { $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $x.OwningProcess) -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'uvicorn.*service_api\.main:app') { Stop-Process -Id $x.OwningProcess -Force -ErrorAction SilentlyContinue } }"
rem Wait briefly for uvicorn and the listening socket to be released.
for /l %%I in (1,1,20) do (
  powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if (-not $c) { exit 0 } else { exit 1 }"
  if not errorlevel 1 goto :port_ready
  >nul timeout /t 1 /nobreak
)
for /l %%I in (1,1,10) do (
  powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if (-not $c) { exit 0 } else { exit 1 }"
  if not errorlevel 1 goto :port_ready
  >nul timeout /t 1 /nobreak
)
echo [ERROR] Port %PORT% is still in use after stopping the service.
echo [INFO] Check the process with: netstat -ano ^| findstr :%PORT%
exit /b 1

:port_ready
echo [INFO] Starting service ...
call "%~dp0start_windows.bat" %*
exit /b %errorlevel%
:help
echo Usage: restart_windows.bat [--foreground ^| --background]
exit /b 0
