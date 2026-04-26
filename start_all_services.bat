@echo off
setlocal

REM =========================
REM Aether local stack launcher
REM Opens 2 terminals:
REM 1) Django runserver
REM 2) Ollama server
REM =========================

set "PROJECT_DIR=%~dp0"

echo.
echo Starting services from: %PROJECT_DIR%
echo Using Ollama on: http://127.0.0.1:11434
echo.

start "Aether - Django Runserver" cmd /k "cd /d "%PROJECT_DIR%" && python manage.py runserver"
start "Aether - Ollama Serve" cmd /k "ollama serve"

echo All terminals launched.
echo.
echo Pull required models once:
echo   ollama pull glm-ocr:latest
echo   ollama pull qwen2.5:7b
echo Keep them open while using the app.
echo.
pause

