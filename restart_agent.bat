@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart_agent.ps1"
set "result=%ERRORLEVEL%"
echo.
if not "%result%"=="0" echo Restart did not complete. Read the message above before trying again.
pause
exit /b %result%
