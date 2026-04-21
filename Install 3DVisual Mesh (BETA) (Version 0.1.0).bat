@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\install_3dvisual_mesh.ps1"
if errorlevel 1 (
  echo.
  echo 3DVisual Mesh could not install.
  echo Read the message above, then try again.
  pause
  exit /b 1
)
