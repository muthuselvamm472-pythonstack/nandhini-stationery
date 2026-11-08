@echo off
setlocal
title Nandhini Stationery - Server ^& Dashboard Launcher
cd /d "%~dp0"

echo ======================================================================
echo           NANDHINI STATIONERY - LAUNCHING SERVER...
echo ======================================================================
echo.

:: Detect Python executable
set "PY_CMD="

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "PY_CMD=py"
    ) else (
        if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
            set "PY_CMD=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
        )
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python was not found on your system!
    echo Please ensure Python is installed and added to PATH.
    echo.
    pause
    exit /b 1
)

"%PY_CMD%" run_server.py

pause
