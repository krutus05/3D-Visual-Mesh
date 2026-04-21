@echo off
setlocal

set "ROOTDIR=%~dp0.."
set "PYW=%THREEVISUAL_PYTHONW%"
if not defined PYW if exist "%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\pythonw.exe" set "PYW=%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\pythonw.exe"
if not defined PYW if exist "%ROOTDIR%\.runtime\amd3d\Scripts\pythonw.exe" set "PYW=%ROOTDIR%\.runtime\amd3d\Scripts\pythonw.exe"
if not defined PYW set "PYW=%USERPROFILE%\amd3d\Scripts\pythonw.exe"
set "THREEVISUAL_HUNYUAN_REPO=%THREEVISUAL_HUNYUAN_REPO%"
if not defined THREEVISUAL_HUNYUAN_REPO if exist "%ROOTDIR%\.vendor\Hunyuan3D-2" set "THREEVISUAL_HUNYUAN_REPO=%ROOTDIR%\.vendor\Hunyuan3D-2"
if not defined THREEVISUAL_HUNYUAN_REPO set "THREEVISUAL_HUNYUAN_REPO=G:\Hunyuan3D-2"
set "LOGFILE=%~dp03dvisual_mesh.log"

if not exist "%PYW%" (
  echo ERROR: pythonw.exe not found at "%PYW%"
  echo.
  echo Tip:
  echo Set THREEVISUAL_PYTHONW to your venv pythonw.exe path.
  echo Example:
  echo set "THREEVISUAL_PYTHONW=C:\AI\3dvisual_mesh\Scripts\pythonw.exe"
  pause
  exit /b 1
)

if not exist "%ROOTDIR%\app\ui_native.py" (
  echo ERROR: App file not found at "%ROOTDIR%\app\ui_native.py"
  pause
  exit /b 1
)

if not exist "%THREEVISUAL_HUNYUAN_REPO%" (
  echo ERROR: Hunyuan repo not found at "%THREEVISUAL_HUNYUAN_REPO%"
  echo.
  echo Tip:
  echo Set THREEVISUAL_HUNYUAN_REPO to your Hunyuan3D-2 folder.
  echo Example:
  echo set "THREEVISUAL_HUNYUAN_REPO=D:\AI\Hunyuan3D-2"
  pause
  exit /b 1
)

cd /d "%ROOTDIR%"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

"%PYW%" -m app.ui_native 1>>"%LOGFILE%" 2>>&1
