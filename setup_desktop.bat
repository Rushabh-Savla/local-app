@echo off
rem ==============================================================================
rem 1-Click Desktop Shortcut Installer for Windows Workstations
rem ==============================================================================
cd /d "%~dp0"

set "PYTHON_BIN=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not %errorlevel% equ 0 (
        where py >nul 2>&1
        if %errorlevel% equ 0 (
            set "PYTHON_BIN=py"
        )
    )
)

"%PYTHON_BIN%" setup_desktop_icon.py
pause
