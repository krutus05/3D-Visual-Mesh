@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\bootstrap_and_run_3dvisual_mesh.ps1"
if errorlevel 1 (
  echo.
  echo 3DVisual Mesh could not start.
  echo Read the message above, then try again.
  pause
  exit /b 1
)
