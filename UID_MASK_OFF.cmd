@echo off
setlocal
cd /d "%~dp0"
>"uid_mask_enabled.txt" echo 0
if not exist "uid_mask.pid" exit /b 0
for /f "usebackq delims=" %%P in ("uid_mask.pid") do taskkill /pid %%P /f >nul 2>nul
del /q "uid_mask.pid" >nul 2>nul
exit /b 0
