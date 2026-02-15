@echo off
chcp 65001 >nul
title ClaudeStation - One-Click Setup
echo ============================================
echo   ClaudeStation - One-Click Deployment
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM Check Python version >= 3.11
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    if %%a LSS 3 (
        echo [ERROR] Python 3.11+ required. Found: %PYVER%
        pause
        exit /b 1
    )
    if %%a EQU 3 if %%b LSS 11 (
        echo [ERROR] Python 3.11+ required. Found: %PYVER%
        pause
        exit /b 1
    )
)
echo [OK] Python %PYVER% detected.

REM Create virtual environment
if not exist "venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

REM Activate and install dependencies
echo [SETUP] Installing dependencies (this may take a few minutes)...
call venv\Scripts\activate.bat

pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt 2>&1 | findstr /V "already satisfied"

if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your network connection.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.

REM Create data directory
if not exist "%USERPROFILE%\ClaudeStation" (
    mkdir "%USERPROFILE%\ClaudeStation"
    echo [OK] Data directory created: %USERPROFILE%\ClaudeStation
) else (
    echo [OK] Data directory exists: %USERPROFILE%\ClaudeStation
)

echo.
echo ============================================
echo   Setup Complete! Starting ClaudeStation...
echo ============================================
echo.

REM Launch
python main.py
pause
