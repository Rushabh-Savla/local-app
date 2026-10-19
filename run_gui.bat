@echo off
rem ==============================================================================
rem 1-Click Desktop GUI Launcher for Annotators (Windows)
rem ==============================================================================
cd /d "%~dp0"
set PYTHONPATH=%~dp0

set PYTHON_BIN=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_BIN=.venv\Scripts\python.exe
)

start "" "%PYTHON_BIN%" desktop_app.py

