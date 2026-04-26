@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Virtual environment not found.
  echo Run setup.bat first.
  exit /b 1
)

echo ============================================
echo Create Django Superuser
echo ============================================
echo.

set /p SU_USER=Username: 
if "%SU_USER%"=="" (
  echo [ERROR] Username is required.
  exit /b 1
)

set /p SU_EMAIL=Email (optional): 

set /p SU_PASS1=Password: 
if "%SU_PASS1%"=="" (
  echo [ERROR] Password is required.
  exit /b 1
)

set /p SU_PASS2=Confirm password: 
if not "%SU_PASS1%"=="%SU_PASS2%" (
  echo [ERROR] Passwords do not match.
  exit /b 1
)

set "DJANGO_SUPERUSER_USERNAME=%SU_USER%"
set "DJANGO_SUPERUSER_EMAIL=%SU_EMAIL%"
set "DJANGO_SUPERUSER_PASSWORD=%SU_PASS1%"

echo.
echo Creating superuser...
".venv\Scripts\python.exe" manage.py createsuperuser --noinput
if errorlevel 1 (
  echo [ERROR] Superuser creation failed. The user may already exist.
  exit /b 1
)

echo [OK] Superuser created successfully.
exit /b 0
