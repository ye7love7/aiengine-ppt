@echo off
setlocal

cd /d "%~dp0"

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

echo [INFO] Using current Python environment.
echo [INFO] Open: http://127.0.0.1:8000/frontend
python -m uvicorn service_api.main:app --host 0.0.0.0 --port 8000

endlocal
