@echo off
setlocal

set "ROOTDIR=%~dp0.."
set "PYTHON_EXE=%THREEVISUAL_PYTHON%"
if not defined PYTHON_EXE if exist "%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\python.exe" set "PYTHON_EXE=%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%ROOTDIR%\.runtime\amd3d\Scripts\python.exe" set "PYTHON_EXE=%ROOTDIR%\.runtime\amd3d\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=%USERPROFILE%\amd3d\Scripts\python.exe"
set "THREEVISUAL_HUNYUAN_REPO=%THREEVISUAL_HUNYUAN_REPO%"
if not defined THREEVISUAL_HUNYUAN_REPO if exist "%ROOTDIR%\.vendor\Hunyuan3D-2" set "THREEVISUAL_HUNYUAN_REPO=%ROOTDIR%\.vendor\Hunyuan3D-2"
if not defined THREEVISUAL_HUNYUAN_REPO set "THREEVISUAL_HUNYUAN_REPO=G:\Hunyuan3D-2"

if not exist "%PYTHON_EXE%" (
  echo ERROR: python.exe not found at "%PYTHON_EXE%"
  echo.
  echo Tip:
  echo Set THREEVISUAL_PYTHON to your venv python.exe path.
  echo Example:
  echo set "THREEVISUAL_PYTHON=C:\AI\3dvisual_mesh\Scripts\python.exe"
  pause
  exit /b 1
)

if not exist "%ROOTDIR%\app\ui_web.py" (
  echo ERROR: App file not found at "%ROOTDIR%\app\ui_web.py"
  pause
  exit /b 1
)

if not exist "%THREEVISUAL_HUNYUAN_REPO%" (
  echo ERROR: Hunyuan repo not found at "%THREEVISUAL_HUNYUAN_REPO%"
  echo.
  echo Tip:
  echo Set THREEVISUAL_HUNYUAN_REPO to your Hunyuan3D-2 folder.
  pause
  exit /b 1
)

cd /d "%ROOTDIR%"

set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"

echo Starting 3DVisual Mesh Web...
echo It should open in your browser automatically.
echo Output meshes will be saved to your Desktop.

"%PYTHON_EXE%" -m app.ui_web

echo.
echo The app stopped or hit an error.
pause
