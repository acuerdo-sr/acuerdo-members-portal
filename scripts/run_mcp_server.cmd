@echo off
setlocal

set "ROOT=%~dp0.."
set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"

if exist "%PYTHON_EXE%" goto run

where python.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python.exe"
  goto run
)

where py.exe >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py.exe"
  goto run
)

echo Python was not found. Install Python and run: pip install -r requirements.txt 1>&2
exit /b 1

:run
cd /d "%ROOT%"
"%PYTHON_EXE%" "%ROOT%\scripts\mcp_server.py"
