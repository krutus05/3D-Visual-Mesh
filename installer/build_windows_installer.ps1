param(
    [switch]$CopyToDesktop
)

$ErrorActionPreference = "Stop"

function Resolve-IsccPath {
    $command = Get-Command ISCC -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidatePaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )

    foreach ($candidatePath in $candidatePaths) {
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidatePath
        }
    }

    return $null
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildReleaseScript = Join-Path $ScriptDir "build_release_package.ps1"
$InstallerScript = Join-Path $ScriptDir "3dvisual_mesh_setup.iss"
$InstallerOutputPath = Join-Path (Join-Path $ScriptDir "..\dist") "3DVisualMeshSetup_0.1.0.exe"
$DesktopReleaseDir = Join-Path ([Environment]::GetFolderPath("Desktop")) "3DVisual Mesh Share (BETA) (Version 0.1.0)"

& $BuildReleaseScript @(
    if ($CopyToDesktop) { "-CopyToDesktop" }
)

$isccPath = Resolve-IsccPath
if (-not $isccPath) {
    throw "Inno Setup 6 was not found. Install it first, then run this script again. Suggested command: winget install JRSoftware.InnoSetup"
}

& $isccPath $InstallerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed to build the Windows installer."
}

if ($CopyToDesktop -and (Test-Path -LiteralPath $InstallerOutputPath) -and (Test-Path -LiteralPath $DesktopReleaseDir)) {
    Copy-Item -LiteralPath $InstallerOutputPath -Destination (Join-Path $DesktopReleaseDir "3DVisualMeshSetup_0.1.0.exe") -Force
}

Write-Host ""
Write-Host "[3DVisual Mesh Release] Windows installer build finished." -ForegroundColor Green
Write-Host "Output: dist\\3DVisualMeshSetup_0.1.0.exe" -ForegroundColor DarkGray
