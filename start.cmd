@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" %*
if errorlevel 1 (
  echo.
  echo MAPLE could not start. Review the error above.
  if not defined CI pause
  exit /b 1
)
