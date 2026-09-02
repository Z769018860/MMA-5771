@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\debug" mkdir "runtime\debug"
start "" explorer.exe "%~dp0runtime\debug"
exit /b 0
