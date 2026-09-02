@echo off
setlocal
cd /d "%~dp0"
>"uid_mask_enabled.txt" echo 1
if exist "uid_mask.pid" (
  for /f "usebackq delims=" %%P in ("uid_mask.pid") do tasklist /fi "PID eq %%P" 2>nul | find "%%P" >nul && exit /b 0
)
start "Morimens UID Mask" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0uid_mask.ps1"
exit /b 0
