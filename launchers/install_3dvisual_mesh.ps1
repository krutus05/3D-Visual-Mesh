param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\3DVisual Mesh",
    [switch]$NoLaunch,
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "[3DVisual Mesh Installer] $Message" -ForegroundColor Cyan
}

function Test-ShouldSkipPath {
    param(
        [string]$RelativePath,
        [bool]$IsDirectory
    )

    $parts = $RelativePath -split "[\\/]+" | Where-Object { $_ }
    foreach ($part in $parts) {
        if ($script:ExcludeDirNames -contains $part) {
            return $true
        }
    }

    if (-not $IsDirectory) {
        $leaf = Split-Path -Path $RelativePath -Leaf
        if ($script:ExcludeFileNames -contains $leaf) {
            return $true
        }
        if ([IO.Path]::GetExtension($leaf) -eq ".pyc") {
            return $true
        }
    }

    return $false
}

function Copy-FilteredItem {
    param(
        [string]$SourceBase,
        [string]$DestinationBase,
        [string]$RelativePath
    )

    $sourcePath = Join-Path $SourceBase $RelativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        return
    }

    $item = Get-Item -LiteralPath $sourcePath -Force
    if ($item.PSIsContainer) {
        if (Test-ShouldSkipPath -RelativePath $RelativePath -IsDirectory $true) {
            return
        }

        $destinationPath = Join-Path $DestinationBase $RelativePath
        New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null

        foreach ($child in Get-ChildItem -LiteralPath $sourcePath -Force) {
            $childRelative = Join-Path $RelativePath $child.Name
            Copy-FilteredItem -SourceBase $SourceBase -DestinationBase $DestinationBase -RelativePath $childRelative
        }
        return
    }

    if (Test-ShouldSkipPath -RelativePath $RelativePath -IsDirectory $false) {
        return
    }

    $destinationPath = Join-Path $DestinationBase $RelativePath
    $destinationDir = Split-Path -Parent $destinationPath
    if ($destinationDir) {
        New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null
    }
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}

function New-AppShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$WorkingDirectory,
        [string]$IconPath,
        [string]$Description
    )

    $shortcutDir = Split-Path -Parent $ShortcutPath
    if ($shortcutDir) {
        New-Item -ItemType Directory -Force -Path $shortcutDir | Out-Null
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    if (Test-Path -LiteralPath $IconPath) {
        $shortcut.IconLocation = $IconPath
    }
    $shortcut.Save()
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$InstallDir = [Environment]::ExpandEnvironmentVariables($InstallDir)
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

$ReleaseLabel = "3DVisual Mesh (BETA) (Version 0.1.0)"
$StartLauncherName = "Start 3DVisual Mesh (BETA) (Version 0.1.0).bat"
$InstallLauncherName = "Install 3DVisual Mesh (BETA) (Version 0.1.0).bat"
$UninstallBatchName = "Uninstall 3DVisual Mesh.bat"
$DesktopShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "3DVisual Mesh.lnk"
$StartMenuFolder = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\3DVisual Mesh"
$StartShortcutPath = Join-Path $StartMenuFolder "3DVisual Mesh.lnk"
$UninstallShortcutPath = Join-Path $StartMenuFolder "Uninstall 3DVisual Mesh.lnk"
$ExcludeDirNames = @(".runtime", ".vendor", "__pycache__", "preview_cache", "sheet_cache", "mentor_cases", "dist", "installer")
$ExcludeFileNames = @("3dvisual_mesh.log", "app_settings.json")
$RootItems = @(
    "app",
    "assets",
    "blender_addon",
    "launchers",
    "plugins",
    "website",
    "CONTRIBUTING.md",
    "FRIEND_SETUP.txt",
    "GAME_DEV_ROADMAP.md",
    "OPEN_SOURCE_VISION.md",
    "README.md",
    "START_HERE_EASY.txt",
    "THREE_AI_ARCHITECTURE.md",
    "requirements_one_click_common.txt",
    "requirements_one_click_windows_amd.txt",
    "requirements_one_click_windows_nvidia.txt",
    $StartLauncherName,
    $InstallLauncherName
)

if ($InstallDir -eq $SourceRoot) {
    throw "Install target cannot be the same as the current package folder."
}

Write-Step "Installing $ReleaseLabel"
Write-Host "Source: $SourceRoot" -ForegroundColor DarkGray
Write-Host "Target: $InstallDir" -ForegroundColor DarkGray

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

foreach ($item in $RootItems) {
    Copy-FilteredItem -SourceBase $SourceRoot -DestinationBase $InstallDir -RelativePath $item
}

$uninstallBatchPath = Join-Path $InstallDir $UninstallBatchName
@"
@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launchers\uninstall_3dvisual_mesh.ps1"
"@ | Set-Content -LiteralPath $uninstallBatchPath -Encoding ASCII

$iconPath = Join-Path $InstallDir "assets\3dvisual_mesh_icon.ico"
$startLauncherPath = Join-Path $InstallDir $StartLauncherName

New-AppShortcut `
    -ShortcutPath $StartShortcutPath `
    -TargetPath $startLauncherPath `
    -WorkingDirectory $InstallDir `
    -IconPath $iconPath `
    -Description "Start 3DVisual Mesh"

New-AppShortcut `
    -ShortcutPath $UninstallShortcutPath `
    -TargetPath $uninstallBatchPath `
    -WorkingDirectory $InstallDir `
    -IconPath $iconPath `
    -Description "Uninstall 3DVisual Mesh"

if (-not $NoDesktopShortcut) {
    New-AppShortcut `
        -ShortcutPath $DesktopShortcutPath `
        -TargetPath $startLauncherPath `
        -WorkingDirectory $InstallDir `
        -IconPath $iconPath `
        -Description "Start 3DVisual Mesh"
}

Write-Step "Install complete"
Write-Host "Desktop shortcut: $DesktopShortcutPath" -ForegroundColor DarkGray
Write-Host "Start Menu folder: $StartMenuFolder" -ForegroundColor DarkGray

if (-not $NoLaunch) {
    Write-Step "Starting 3DVisual Mesh..."
    Start-Process -FilePath $startLauncherPath -WorkingDirectory $InstallDir
}
