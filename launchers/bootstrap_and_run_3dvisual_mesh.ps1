param(
    [switch]$CheckOnly,
    [switch]$ForceReinstall,
    [ValidateSet("auto", "amd", "nvidia")]
    [string]$GpuKind = "auto"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "[3DVisual Mesh] $Message" -ForegroundColor Cyan
}

function Invoke-CheckedCommand {
    param(
        [scriptblock]$Command,
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Resolve-BootstrapPython {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $null = & py -3.12 -c "import sys; print(sys.version)"
            if ($LASTEXITCODE -eq 0) {
                return "py -3.12"
            }
        } catch {}
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        try {
            $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -eq 0 -and $version -eq "3.12") {
                return "python"
            }
        } catch {}
    }

    return $null
}

function Ensure-PythonInstalled {
    $bootstrap = Resolve-BootstrapPython
    if ($bootstrap) {
        return $bootstrap
    }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Step "Python 3.12 not found. Trying winget install..."
        if (-not $CheckOnly) {
            & winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
        }
        $bootstrap = Resolve-BootstrapPython
        if ($bootstrap) {
            return $bootstrap
        }
    }

    throw "Python 3.12 is missing. Install Python 3.12, then run this launcher again."
}

function Invoke-PythonCommand {
    param(
        [string]$BootstrapPython,
        [string[]]$Arguments
    )

    if ($BootstrapPython -eq "py -3.12") {
        & py -3.12 @Arguments
    } else {
        & python @Arguments
    }
}

function Get-GpuInfo {
    param(
        [string]$RequestedKind
    )

    $controllers = @()
    try {
        $controllers = @(Get-CimInstance Win32_VideoController -ErrorAction Stop)
    } catch {
        $controllers = @()
    }

    $names = @(
        $controllers |
            ForEach-Object { "$($_.Name)".Trim() } |
            Where-Object { $_ }
    )

    if ($RequestedKind -ne "auto") {
        return @{
            kind = $RequestedKind
            names = $names
        }
    }

    if ($names | Where-Object { $_ -match "NVIDIA" }) {
        return @{
            kind = "nvidia"
            names = $names
        }
    }

    if ($names | Where-Object { $_ -match "AMD|Radeon" }) {
        return @{
            kind = "amd"
            names = $names
        }
    }

    return @{
        kind = $null
        names = $names
    }
}

function Ensure-HunyuanRepo {
    param(
        [string]$RepoDir,
        [string]$VendorDir,
        [string]$ZipUrl,
        [string]$Commit
    )

    if (Test-Path -LiteralPath $RepoDir) {
        return
    }

    New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Step "Downloading Hunyuan3D-2 with git..."
        if (-not $CheckOnly) {
            Invoke-CheckedCommand -Command {
                & git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git $RepoDir
            } -FailureMessage "Git clone failed for Hunyuan3D-2."

            Invoke-CheckedCommand -Command {
                & git -C $RepoDir checkout $Commit
            } -FailureMessage "Git checkout failed for Hunyuan3D-2."
        }
        return
    }

    Write-Step "Downloading Hunyuan3D-2 zip..."
    if ($CheckOnly) {
        return
    }

    $zipPath = Join-Path $VendorDir "hunyuan3d2.zip"
    $extractDir = Join-Path $VendorDir "hunyuan3d2_extract"

    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    if (Test-Path -LiteralPath $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }

    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $sourceDir = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    if (-not $sourceDir) {
        throw "Could not extract Hunyuan3D-2 archive."
    }

    Move-Item -LiteralPath $sourceDir.FullName -Destination $RepoDir
    Remove-Item -LiteralPath $zipPath -Force
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $RootDir ".runtime"
$VendorDir = Join-Path $RootDir ".vendor"
$PreferredVenvDir = Join-Path $RuntimeDir "3dvisual_mesh"
$LegacyVenvDir = Join-Path $RuntimeDir "amd3d"
$VenvDir = if (Test-Path -LiteralPath $PreferredVenvDir) { $PreferredVenvDir } elseif (Test-Path -LiteralPath $LegacyVenvDir) { $LegacyVenvDir } else { $PreferredVenvDir }
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$PythonWExe = Join-Path $VenvDir "Scripts\pythonw.exe"
$RepoDir = Join-Path $VendorDir "Hunyuan3D-2"
$CommonRequirementsFile = Join-Path $RootDir "requirements_one_click_common.txt"
$AmdRequirementsFile = Join-Path $RootDir "requirements_one_click_windows_amd.txt"
$NvidiaRequirementsFile = Join-Path $RootDir "requirements_one_click_windows_nvidia.txt"
$StateFile = Join-Path $RuntimeDir "one_click_state.json"
$RepoCommit = "f8db63096c8282cb27354314d896feba5ba6ff8a"
$RepoZipUrl = "https://github.com/Tencent-Hunyuan/Hunyuan3D-2/archive/$RepoCommit.zip"

foreach ($file in @($CommonRequirementsFile, $AmdRequirementsFile, $NvidiaRequirementsFile)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Missing requirements file: $file"
    }
}

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null

$GpuInfo = Get-GpuInfo -RequestedKind $GpuKind
$SelectedGpu = $GpuInfo.kind
$DetectedGpuNames = @($GpuInfo.names)

if (-not $SelectedGpu) {
    $detectedText = if ($DetectedGpuNames.Count -gt 0) {
        $DetectedGpuNames -join "; "
    } else {
        "No AMD Radeon or NVIDIA GPU detected."
    }
    throw "This package currently supports Windows AMD Radeon and NVIDIA GPUs only. Detected: $detectedText"
}

$RequirementsFile = if ($SelectedGpu -eq "amd") { $AmdRequirementsFile } else { $NvidiaRequirementsFile }
$GpuLabel = if ($SelectedGpu -eq "amd") { "AMD / ROCm for Windows" } else { "NVIDIA / CUDA" }

Write-Step "GPU path selected: $GpuLabel"
if ($DetectedGpuNames.Count -gt 0) {
    Write-Host ("Detected adapters: " + ($DetectedGpuNames -join " | ")) -ForegroundColor DarkGray
}

$RequirementsHash = @(
    (Get-FileHash -Algorithm SHA256 -LiteralPath $CommonRequirementsFile).Hash
    (Get-FileHash -Algorithm SHA256 -LiteralPath $RequirementsFile).Hash
) -join ";"
$DesiredState = @{
    requirements_hash = $RequirementsHash
    repo_commit = $RepoCommit
    bootstrap_version = "0.1.0"
    gpu_kind = $SelectedGpu
}

$BootstrapPython = Ensure-PythonInstalled

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Step "Creating local Python environment..."
    if (-not $CheckOnly) {
        Invoke-PythonCommand -BootstrapPython $BootstrapPython -Arguments @("-m", "venv", $VenvDir)
    }
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    if ($CheckOnly) {
        Write-Step "Check-only: local venv does not exist yet, but bootstrap path is valid."
    } else {
        throw "Local python environment could not be created."
    }
}

Ensure-HunyuanRepo -RepoDir $RepoDir -VendorDir $VendorDir -ZipUrl $RepoZipUrl -Commit $RepoCommit

$NeedInstall = $ForceReinstall.IsPresent -or -not (Test-Path -LiteralPath $StateFile)
if (-not $NeedInstall) {
    try {
        $ExistingState = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        if (
            $ExistingState.requirements_hash -ne $DesiredState.requirements_hash -or
            $ExistingState.repo_commit -ne $DesiredState.repo_commit -or
            $ExistingState.bootstrap_version -ne $DesiredState.bootstrap_version -or
            $ExistingState.gpu_kind -ne $DesiredState.gpu_kind
        ) {
            $NeedInstall = $true
        }
    } catch {
        $NeedInstall = $true
    }
}

if ($NeedInstall) {
    Write-Step "Installing one-click requirements for $GpuLabel..."
    if (-not $CheckOnly) {
        Invoke-CheckedCommand -Command {
            & $PythonExe -m pip install --upgrade pip setuptools wheel
        } -FailureMessage "Failed to upgrade pip, setuptools, or wheel."

        Invoke-CheckedCommand -Command {
            & $PythonExe -m pip install -r $RequirementsFile
        } -FailureMessage "Failed to install Python requirements for $GpuLabel."

        Invoke-CheckedCommand -Command {
            & $PythonExe -m pip install -e $RepoDir
        } -FailureMessage "Failed to install the pinned Hunyuan3D-2 package."

        $DesiredState | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
    }
}

Write-Step "Checking torch runtime..."
if (-not $CheckOnly) {
    $TorchCheck = & $PythonExe -c "import torch; import sys; ok=torch.cuda.is_available(); print('CUDA=' + str(ok)); print('DEVICE=' + (torch.cuda.get_device_name(0) if ok else 'NONE')); sys.exit(0 if ok else 3)"
    if ($LASTEXITCODE -ne 0) {
        throw "Torch installed, but GPU runtime is not ready. Check the $GpuLabel driver/runtime on this machine."
    }
}

if ($CheckOnly) {
    Write-Step "Check-only mode passed."
    exit 0
}

Write-Step "Starting 3DVisual Mesh..."
$env:THREEVISUAL_PYTHON = $PythonExe
$env:THREEVISUAL_PYTHONW = $PythonWExe
$env:THREEVISUAL_HUNYUAN_REPO = $RepoDir
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

Start-Process -FilePath $PythonWExe -ArgumentList @("-m", "app.ui_native") -WorkingDirectory $RootDir
