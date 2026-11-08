@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First create .venv and install requirements-all.txt. See README_FIRST.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "radio-map\serve.py" %*
if errorlevel 1 pause
