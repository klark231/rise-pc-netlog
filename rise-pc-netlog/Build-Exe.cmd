@echo off
rem Builds dist\RiseBridge.exe (one file, no Python needed to run it). Needs Python 3 + internet once.
setlocal
cd /d "%~dp0"
set PY=py -3
where py >nul 2>nul || set PY=python
%PY% -m pip install --user cryptography pyinstaller || (pause & exit /b 1)
%PY% -m PyInstaller --noconfirm --onefile --windowed --name RiseBridge --paths rise-bridge --paths rise-bridge\tools rise-bridge\rise_bridge_app.py || (pause & exit /b 1)
if exist build\Release\dinput8.dll copy /y build\Release\dinput8.dll dist\ >nul
echo.
echo Done: dist\RiseBridge.exe
if not exist dist\dinput8.dll echo Put dinput8.dll ^(from the release zip / CI build^) next to RiseBridge.exe.
pause
