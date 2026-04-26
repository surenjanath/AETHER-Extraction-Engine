@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run setup.bat first.
  exit /b 1
)

echo ============================================
echo Offline Receipt System - Run Server
echo ============================================
echo.

echo Starting Django server on 0.0.0.0:8000 ...
echo Access locally:      http://127.0.0.1:8000/
echo Access on LAN:       http://YOUR_LOCAL_IP:8000/
echo Press CTRL+C to stop.
echo.

".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
exit /b %errorlevel%
