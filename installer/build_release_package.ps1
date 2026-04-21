param(
    [switch]$CopyToDesktop,
    [switch]$OpenDist
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "[3DVisual Mesh Release] $Message" -ForegroundColor Cyan
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

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$DistDir = Join-Path $RootDir "dist"
$ReleaseName = "3DVisual Mesh Share (BETA) (Version 0.1.0)"
$ReleaseDir = Join-Path $DistDir $ReleaseName
$ZipPath = Join-Path $DistDir ($ReleaseName + ".zip")
$DesktopTarget = Join-Path ([Environment]::GetFolderPath("Desktop")) $ReleaseName
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
    "Start 3DVisual Mesh (BETA) (Version 0.1.0).bat",
    "Install 3DVisual Mesh (BETA) (Version 0.1.0).bat"
)

Write-Step "Building clean release package"

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
if (Test-Path -LiteralPath $ReleaseDir) {
    Remove-Item -LiteralPath $ReleaseDir -Recurse -Force
}
if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
foreach ($item in $RootItems) {
    Copy-FilteredItem -SourceBase $RootDir -DestinationBase $ReleaseDir -RelativePath $item
}

Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath -Force
Write-Step "Portable zip ready"
Write-Host "Folder: $ReleaseDir" -ForegroundColor DarkGray
Write-Host "Zip:    $ZipPath" -ForegroundColor DarkGray

if ($CopyToDesktop) {
    Write-Step "Copying share folder to Desktop"
    $desktopRoot = [Environment]::GetFolderPath("Desktop")
    $resolvedDesktopTarget = [IO.Path]::GetFullPath($DesktopTarget)
    if (-not $resolvedDesktopTarget.StartsWith($desktopRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Desktop target resolved outside the Desktop folder."
    }
    if (Test-Path -LiteralPath $resolvedDesktopTarget) {
        Remove-Item -LiteralPath $resolvedDesktopTarget -Recurse -Force
    }
    Copy-Item -LiteralPath $ReleaseDir -Destination $resolvedDesktopTarget -Recurse -Force
    Write-Host "Desktop copy: $resolvedDesktopTarget" -ForegroundColor DarkGray
}

if ($OpenDist) {
    Start-Process explorer.exe $DistDir
}
