@echo off
setlocal
chcp 65001 >nul
title Morimens MAA Assistant - Windows x64
cd /d "%~dp0"
set "POWERSHELL64=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if defined PROCESSOR_ARCHITEW6432 set "POWERSHELL64=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
echo ============================================================
echo  忘却前夜同调率循环助手 - Windows 10/11 x64
echo ============================================================
echo 启动目录：%CD%
echo.
if not exist "%POWERSHELL64%" (
  echo [错误] 未找到 64 位 Windows PowerShell：%POWERSHELL64%
  set "RESULT=1"
  goto :finish
)
"%POWERSHELL64%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_and_run.ps1"
set "RESULT=%ERRORLEVEL%"
:finish
echo.
if "%RESULT%"=="0" (
  echo 助手已经启动。可以关闭本窗口。
) else (
  echo 启动失败，窗口将保留。请发送 startup_win64.log。
)
echo.
pause
endlocal & exit /b %RESULT%
