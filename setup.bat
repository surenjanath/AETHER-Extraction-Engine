@echo off
setlocal

cd /d "%~dp0"

echo ============================================
echo Offline Receipt System - Initial Setup
echo ============================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>&1
  if %errorlevel%==0 (
    set "PYTHON=python"
  ) else (
    echo [ERROR] Python was not found on PATH.
    echo Install Python 3.11+ and rerun this script.
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/6] Creating virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create virtual environment.
    exit /b 1
  )
) else (
  echo [1/6] Virtual environment already exists. Skipping.
)

echo [2/6] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Failed to upgrade pip.
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found in project root.
  exit /b 1
)

echo [3/6] Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Dependency installation failed.
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    echo [4/6] Creating .env from .env.example...
    copy /Y ".env.example" ".env" >nul
  ) else (
    echo [4/6] .env.example not found. Skipping .env creation.
  )
) else (
  echo [4/6] .env already exists. Skipping.
)

echo [5/6] Running database migrations...
".venv\Scripts\python.exe" manage.py migrate
if errorlevel 1 (
  echo [ERROR] Migrations failed.
  exit /b 1
)

echo [6/6] Setup finished successfully.
echo.
echo Next steps:
echo 1) Run create_superuser.bat to create an admin account.
echo 2) Start Ollama: ollama serve
echo 3) Run run.bat to start Django server.
echo.

choice /m "Create superuser now"
if errorlevel 2 (
  echo Skipped superuser creation.
  exit /b 0
)

call create_superuser.bat
exit /b %errorlevel%
