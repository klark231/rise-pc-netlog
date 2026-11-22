@echo off
rem Joins YOUR OWN host many times with different MACs and records the host's hello for each (about 5 minutes).
cd /d "%~dp0rise-bridge"
set PY=python
where python >nul 2>nul || set PY=py
%PY% -m pip install --quiet cryptography
set /p SRV=Server [meoli.viewdns.net]: 
if "%SRV%"=="" set SRV=meoli.viewdns.net
set /p KEY=Matchmaking key (empty if none): 
%PY% tools\hello_probe.py %SRV% --key "%KEY%"
pause
