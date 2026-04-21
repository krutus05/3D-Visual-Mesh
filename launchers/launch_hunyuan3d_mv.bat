@echo off
setlocal

set "ROOTDIR=%~dp0.."
set "PYTHON_EXE=%THREEVISUAL_PYTHON%"
if not defined PYTHON_EXE if exist "%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\python.exe" set "PYTHON_EXE=%ROOTDIR%\.runtime\3dvisual_mesh\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%ROOTDIR%\.runtime\amd3d\Scripts\python.exe" set "PYTHON_EXE=%ROOTDIR%\.runtime\amd3d\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=%USERPROFILE%\amd3d\Scripts\python.exe"
set "APPDIR=%THREEVISUAL_HUNYUAN_REPO%"
if not defined APPDIR if exist "%ROOTDIR%\.vendor\Hunyuan3D-2" set "APPDIR=%ROOTDIR%\.vendor\Hunyuan3D-2"
if not defined APPDIR set "APPDIR=G:\Hunyuan3D-2"

if not exist "%PYTHON_EXE%" (
  echo ERROR: python.exe not found at "%PYTHON_EXE%"
  echo Check that your AI environment still exists.
  pause
  exit /b 1
)

if not exist "%APPDIR%\gradio_app.py" (
  echo ERROR: Hunyuan3D-2 not found at "%APPDIR%"
  echo Update APPDIR in this file if you moved the repo.
  pause
  exit /b 1
)

cd /d "%APPDIR%"

echo Starting Hunyuan3D-2 multiview UI...
echo When the terminal shows a local URL, open it in your browser.
echo Use Front / Back / Left / Right images for better shape quality.

"%PYTHON_EXE%" gradio_app.py --model_path tencent/Hunyuan3D-2mv --subfolder hunyuan3d-dit-v2-mv --low_vram_mode --disable_tex

echo.
echo The app stopped or hit an error.
pause
