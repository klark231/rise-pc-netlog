@echo off
rem Rise Bridge launcher (runs the window from Python source). Needs Python 3 for Windows; installs 'cryptography' itself.
setlocal
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), or run:
  echo     winget install Python.Python.3.12
  echo then double-click this file again.
  pause & exit /b 1
)
%PY% -c "import cryptography, tkinter" >nul 2>nul
if errorlevel 1 (
  echo Installing the 'cryptography' package...
  %PY% -m pip install --user cryptography
  %PY% -c "import tkinter" >nul 2>nul || echo Note: this Python has no tkinter, so the window can't open; falling back to console mode.
)
%PY% rise-bridge\rise_bridge_app.py %*
if errorlevel 1 pause
