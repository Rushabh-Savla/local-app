@echo off
rem ==============================================================================
rem 1-Click Desktop GUI Launcher for Annotators (Windows)
rem Resolves installation directory even if copied or run from Desktop.
rem ==============================================================================
setlocal enabledelayedexpansion

set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

rem Check if desktop_app.py exists in current directory
if not exist "%APP_DIR%\desktop_app.py" (
    if exist "%LOCALAPPDATA%\nas_annotation\app_path.txt" (
        set /p APP_DIR=<"%LOCALAPPDATA%\nas_annotation\app_path.txt"
    )
)

if not exist "%APP_DIR%\desktop_app.py" (
    echo [ERROR] Could not find desktop_app.py in "%APP_DIR%".
    echo Please run setup_desktop_icon.bat inside your local-app folder first.
    pause
    exit /b 1
)

cd /d "%APP_DIR%"
set "PYTHONPATH=%APP_DIR%;%PYTHONPATH%"

rem Find Python executable
set "PYTHON_BIN=python"
if exist "%APP_DIR%\.venv\Scripts\pythonw.exe" (
    set "PYTHON_BIN=%APP_DIR%\.venv\Scripts\pythonw.exe"
) else if exist "%APP_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%APP_DIR%\.venv\Scripts\python.exe"
) else if exist "%APP_DIR%\..\.venv\Scripts\pythonw.exe" (
    set "PYTHON_BIN=%APP_DIR%\..\.venv\Scripts\pythonw.exe"
) else if exist "%APP_DIR%\..\.venv\Scripts\python.exe" (
    set "PYTHON_BIN=%APP_DIR%\..\.venv\Scripts\python.exe"
) else (
    where pythonw >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_BIN=pythonw"
    ) else (
        where python >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_BIN=python"
        ) else (
            where py >nul 2>&1
            if !errorlevel! equ 0 (
                set "PYTHON_BIN=py"
            ) else (
                rem Fallback to WSL if installed
                where wsl >nul 2>&1
                if !errorlevel! equ 0 (
                    echo Launching via WSL...
                    wsl -e bash -c "cd '$(wslpath '%APP_DIR%')' && ./run_gui.sh"
                    exit /b 0
                )
                echo [ERROR] Python not found. Please install Python 3.10+ from python.org.
                pause
                exit /b 1
            )
        )
    )
)

start "" "%PYTHON_BIN%" desktop_app.py %*
