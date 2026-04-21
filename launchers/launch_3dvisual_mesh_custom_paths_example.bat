@echo off
setlocal

rem Edit these 3 lines for your own machine, then save as:
rem launch_3dvisual_mesh_custom_paths.bat

set "THREEVISUAL_PYTHONW=C:\AI\3dvisual_mesh\Scripts\pythonw.exe"
set "THREEVISUAL_PYTHON=C:\AI\3dvisual_mesh\Scripts\python.exe"
set "THREEVISUAL_HUNYUAN_REPO=D:\AI\Hunyuan3D-2"

call "%~dp0launch_3dvisual_mesh.bat"
