$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "[3DVisual Mesh Uninstall] $Message" -ForegroundColor Yellow
}

$InstallRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DesktopShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "3DVisual Mesh.lnk"
$StartMenuFolder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\3DVisual Mesh"
$TempScriptPath = Join-Path $env:TEMP ("3dvisual_mesh_uninstall_" + [Guid]::NewGuid().ToString("N") + ".cmd")

Write-Step "Removing shortcuts"
if (Test-Path -LiteralPath $DesktopShortcutPath) {
    Remove-Item -LiteralPath $DesktopShortcutPath -Force
}
if (Test-Path -LiteralPath $StartMenuFolder) {
    Remove-Item -LiteralPath $StartMenuFolder -Recurse -Force
}

Write-Step "Scheduling install folder removal"
$escapedInstallRoot = $InstallRoot.Replace('"', '""')
@"
@echo off
ping 127.0.0.1 -n 3 > nul
rmdir /s /q "$escapedInstallRoot"
del /f /q "%~f0"
"@ | Set-Content -LiteralPath $TempScriptPath -Encoding ASCII

Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$TempScriptPath`""
Write-Step "Uninstall scheduled. This window can close now."
