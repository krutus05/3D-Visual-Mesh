param(
    [switch]$CheckOnly,
    [switch]$ForceReinstall,
    [switch]$RepairInstall,
    [switch]$NoLaunch,
    [ValidateSet("auto", "amd", "nvidia")]
    [string]$GpuKind = "auto"
)

$ErrorActionPreference = "Stop"

$script:SetupSteps = @(
    "Detect GPU",
    "Check disk space",
    "Check Python",
    "Create local environment",
    "Install common dependencies",
    "Install GPU dependencies",
    "Check model cache",
    "Verify Torch GPU",
    "Start app"
)
$script:StepStatus = @{}
foreach ($step in $script:SetupSteps) {
    $script:StepStatus[$step] = "pending"
}
$script:ActiveLogPath = $null
$script:TranscriptStarted = $false

function Write-LauncherLine {
    param(
        [string]$Message,
        [ConsoleColor]$Color = [ConsoleColor]::Cyan
    )

    Write-Host ""
    Write-Host "[3DVisual Mesh] $Message" -ForegroundColor $Color
}

function Show-ProgressChecklist {
    $ordered = foreach ($step in $script:SetupSteps) {
        $state = $script:StepStatus[$step]
        $marker = switch ($state) {
            "done" { "[x]" }
            "active" { "[>]" }
            "failed" { "[!]" }
            default { "[ ]" }
        }
        "$marker $step"
    }

    Write-Host ""
    Write-Host ($ordered -join [Environment]::NewLine) -ForegroundColor DarkGray
}

function Set-ProgressStep {
    param(
        [string]$Name,
        [string]$Message
    )

    foreach ($step in $script:SetupSteps) {
        if ($script:StepStatus[$step] -eq "active") {
            $script:StepStatus[$step] = "done"
        }
    }
    if ($script:StepStatus.ContainsKey($Name)) {
        $script:StepStatus[$Name] = "active"
    }

    Write-LauncherLine $Message
    Show-ProgressChecklist
}

function Complete-ProgressStep {
    param([string]$Name)
    if ($script:StepStatus.ContainsKey($Name)) {
        $script:StepStatus[$Name] = "done"
    }
}

function Fail-ProgressStep {
    param([string]$Name)
    if ($script:StepStatus.ContainsKey($Name)) {
        $script:StepStatus[$Name] = "failed"
    }
    Show-ProgressChecklist
}

function Stop-LauncherTranscript {
    if ($script:TranscriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {
        }
        $script:TranscriptStarted = $false
    }
}

function Write-CommandLine {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    $rendered = @($Executable) + ($Arguments | ForEach-Object {
            if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ }
        })
    Write-Host ("Command: {0}" -f ($rendered -join " ")) -ForegroundColor DarkGray
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

function Ensure-Directory {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Test-DirectoryHasFiles {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return $null -ne (Get-ChildItem -LiteralPath $Path -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Test-WheelhouseAvailable {
    param(
        [string]$CommonDir,
        [string]$GpuDir
    )

    return (Test-DirectoryHasFiles -Path $CommonDir) -and (Test-DirectoryHasFiles -Path $GpuDir)
}

function Expand-SplitWheelFiles {
    param([string[]]$Directories)

    foreach ($dir in $Directories) {
        if (-not (Test-Path -LiteralPath $dir)) {
            continue
        }

        $groupedParts = @{}
        Get-ChildItem -LiteralPath $dir -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(?<base>.+\.whl)\.part(?<index>\d{3})$' } |
            ForEach-Object {
                $baseName = $Matches["base"]
                $index = [int]$Matches["index"]
                $outputPath = Join-Path $_.DirectoryName $baseName
                if (-not $groupedParts.ContainsKey($outputPath)) {
                    $groupedParts[$outputPath] = @()
                }
                $groupedParts[$outputPath] += [pscustomobject]@{
                    Index = $index
                    Path = $_.FullName
                    Length = $_.Length
                }
            }

        foreach ($outputPath in $groupedParts.Keys) {
            $parts = @($groupedParts[$outputPath] | Sort-Object Index)
            $expectedSize = ($parts | Measure-Object -Property Length -Sum).Sum
            $needsRebuild = $true

            if (Test-Path -LiteralPath $outputPath) {
                try {
                    $existingSize = (Get-Item -LiteralPath $outputPath).Length
                    $needsRebuild = $existingSize -ne $expectedSize
                } catch {
                    $needsRebuild = $true
                }
            }

            if (-not $needsRebuild) {
                continue
            }

            Write-LauncherLine ("Rebuilding split wheel file {0}..." -f [IO.Path]::GetFileName($outputPath)) Yellow
            $tempPath = "$outputPath.rebuild"
            if (Test-Path -LiteralPath $tempPath) {
                Remove-Item -LiteralPath $tempPath -Force
            }

            $writeStream = [IO.File]::Open($tempPath, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                foreach ($part in $parts) {
                    $readStream = [IO.File]::OpenRead($part.Path)
                    try {
                        $readStream.CopyTo($writeStream)
                    } finally {
                        $readStream.Dispose()
                    }
                }
            } finally {
                $writeStream.Dispose()
            }

            if (Test-Path -LiteralPath $outputPath) {
                Remove-Item -LiteralPath $outputPath -Force
            }
            Move-Item -LiteralPath $tempPath -Destination $outputPath -Force
        }
    }
}

function Test-ModelCacheReady {
    param([string]$HubCacheDir)
    if (-not (Test-Path -LiteralPath $HubCacheDir)) {
        return $false
    }

    $requiredRepos = @(
        "models--tencent--Hunyuan3D-2",
        "models--tencent--Hunyuan3D-2mv"
    )

    foreach ($repoName in $requiredRepos) {
        $repoDir = Join-Path $HubCacheDir $repoName
        if (-not (Test-Path -LiteralPath $repoDir)) {
            return $false
        }

        $hasSnapshots = $null -ne (Get-ChildItem -LiteralPath (Join-Path $repoDir "snapshots") -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
        $hasBlobs = $null -ne (Get-ChildItem -LiteralPath (Join-Path $repoDir "blobs") -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
        if (-not ($hasSnapshots -or $hasBlobs)) {
            return $false
        }
    }

    return $true
}

function Test-FreeDiskSpace {
    param(
        [string]$Path,
        [double]$RequiredGB,
        [string]$ModeLabel
    )

    $absolute = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($absolute)
    $drive = [IO.DriveInfo]::new($root)
    $freeGb = [math]::Round($drive.AvailableFreeSpace / 1GB, 1)
    Write-Host ("Free disk space on {0}: {1} GB" -f $root, $freeGb) -ForegroundColor DarkGray

    if ($freeGb -lt $RequiredGB) {
        throw (
            "{0} needs about {1} GB free, but only {2} GB is available on {3}. " +
            "Free some space first, then run Start 3DVisual Mesh again."
        ) -f $ModeLabel, $RequiredGB, $freeGb, $root
    }
}

function Resolve-Layout {
    $resourcesCandidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $isPackageLayout = Test-Path -LiteralPath (Join-Path $resourcesCandidate "app")

    if ($isPackageLayout) {
        $rootDir = [IO.Path]::GetFullPath((Join-Path $resourcesCandidate ".."))
        $resourcesDir = $resourcesCandidate
        $appRoot = Join-Path $resourcesDir "app"
        $launchersDataDir = Join-Path $resourcesDir "launchers"
        $toolsDir = Join-Path $resourcesDir "tools"
        $pythonRuntimeDir = Join-Path $resourcesDir "python"
        $venvDir = Join-Path $resourcesDir ".venv"
        $vendorDir = Join-Path $resourcesDir "vendor"
        $repoDir = Join-Path $vendorDir "Hunyuan3D-2"
        $commonRequirementsFile = Join-Path $appRoot "requirements_one_click_common.txt"
        $amdRequirementsFile = Join-Path $appRoot "requirements_one_click_windows_amd.txt"
        $nvidiaRequirementsFile = Join-Path $appRoot "requirements_one_click_windows_nvidia.txt"
        $stateFile = Join-Path $resourcesDir ".bootstrap_state.json"
    } else {
        $rootDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
        $resourcesDir = Join-Path $rootDir "resources"
        $appRoot = $rootDir
        $launchersDataDir = Join-Path $rootDir "launchers"
        $toolsDir = Join-Path $rootDir "tools"
        $pythonRuntimeDir = Join-Path $resourcesDir "python"
        $preferredVenvDir = Join-Path $resourcesDir ".venv"
        $legacyVenvDir = Join-Path $rootDir ".runtime\3dvisual_mesh"
        $legacyAmdVenvDir = Join-Path $rootDir ".runtime\amd3d"
        if (Test-Path -LiteralPath $preferredVenvDir) {
            $venvDir = $preferredVenvDir
        } elseif (Test-Path -LiteralPath $legacyVenvDir) {
            $venvDir = $legacyVenvDir
        } elseif (Test-Path -LiteralPath $legacyAmdVenvDir) {
            $venvDir = $legacyAmdVenvDir
        } else {
            $venvDir = $preferredVenvDir
        }
        $vendorDir = Join-Path $resourcesDir "vendor"
        $repoDir = if (Test-Path -LiteralPath (Join-Path $vendorDir "Hunyuan3D-2")) {
            Join-Path $vendorDir "Hunyuan3D-2"
        } elseif (Test-Path -LiteralPath (Join-Path $rootDir ".vendor\Hunyuan3D-2")) {
            Join-Path $rootDir ".vendor\Hunyuan3D-2"
        } else {
            Join-Path $vendorDir "Hunyuan3D-2"
        }
        $commonRequirementsFile = Join-Path $rootDir "requirements_one_click_common.txt"
        $amdRequirementsFile = Join-Path $rootDir "requirements_one_click_windows_amd.txt"
        $nvidiaRequirementsFile = Join-Path $rootDir "requirements_one_click_windows_nvidia.txt"
        $stateFile = Join-Path $resourcesDir ".bootstrap_state.json"
    }

    $modelsDir = Join-Path $resourcesDir "models"
    $hfHome = Join-Path $modelsDir "huggingface"
    $hfHubCache = Join-Path $hfHome "hub"
    $logsDir = Join-Path $resourcesDir "logs"
    $wheelCommonDir = Join-Path $resourcesDir "wheels\common"
    $wheelAmdDir = Join-Path $resourcesDir "wheels\amd"
    $wheelNvidiaDir = Join-Path $resourcesDir "wheels\nvidia"
    $appEntryFile = Join-Path $appRoot "app\ui_native.py"

    return @{
        RootDir = $rootDir
        ResourcesDir = $resourcesDir
        AppRoot = $appRoot
        LaunchersDataDir = $launchersDataDir
        ToolsDir = $toolsDir
        PythonRuntimeDir = $pythonRuntimeDir
        VenvDir = $venvDir
        VendorDir = $vendorDir
        RepoDir = $repoDir
        CommonRequirementsFile = $commonRequirementsFile
        AmdRequirementsFile = $amdRequirementsFile
        NvidiaRequirementsFile = $nvidiaRequirementsFile
        StateFile = $stateFile
        ModelsDir = $modelsDir
        HFHome = $hfHome
        HFHubCache = $hfHubCache
        LogsDir = $logsDir
        WheelCommonDir = $wheelCommonDir
        WheelAmdDir = $wheelAmdDir
        WheelNvidiaDir = $wheelNvidiaDir
        AppEntryFile = $appEntryFile
        IsPackageLayout = $isPackageLayout
    }
}

function Get-GpuInfo {
    param([string]$RequestedKind)

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

function Test-CommandVersion {
    param(
        [string]$Executable,
        [string[]]$PrefixArguments
    )

    try {
        & $Executable @PrefixArguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Resolve-PythonCandidate {
    param($Layout)

    $bundledCandidates = @(
        (Join-Path $Layout.PythonRuntimeDir "python.exe"),
        (Join-Path $Layout.PythonRuntimeDir "Scripts\python.exe")
    )
    foreach ($candidate in $bundledCandidates) {
        if ((Test-Path -LiteralPath $candidate) -and (Test-CommandVersion -Executable $candidate -PrefixArguments @())) {
            return @{
                Executable = $candidate
                PrefixArguments = @()
                Source = "bundled"
            }
        }
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-CommandVersion -Executable "py" -PrefixArguments @("-3.12")) {
            return @{
                Executable = "py"
                PrefixArguments = @("-3.12")
                Source = "system"
            }
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Test-CommandVersion -Executable "python" -PrefixArguments @()) {
            return @{
                Executable = "python"
                PrefixArguments = @()
                Source = "system"
            }
        }
    }

    return $null
}

function Invoke-PythonCommand {
    param(
        $PythonCandidate,
        [string[]]$Arguments
    )

    Write-CommandLine -Executable $PythonCandidate.Executable -Arguments ($PythonCandidate.PrefixArguments + $Arguments)
    & $PythonCandidate.Executable @($PythonCandidate.PrefixArguments + $Arguments)
}

function Resolve-VenvExecutable {
    param(
        [string]$VenvDir,
        [string]$Name
    )

    return Join-Path $VenvDir ("Scripts\{0}" -f $Name)
}

function Ensure-HunyuanRepo {
    param(
        [string]$RepoDir,
        [string]$VendorDir,
        [string]$ZipUrl,
        [string]$Commit,
        [switch]$AllowDownload
    )

    if (Test-Path -LiteralPath $RepoDir) {
        return
    }

    if (-not $AllowDownload) {
        throw (
            "Hunyuan backend is missing at {0}. " +
            "Use the matching Full Offline Package or allow online install so the backend can be downloaded."
        ) -f $RepoDir
    }

    Ensure-Directory -Path $VendorDir

    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-LauncherLine "Downloading the pinned Hunyuan3D-2 repo with git..." Yellow
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

    Write-LauncherLine "Downloading the pinned Hunyuan3D-2 zip..." Yellow
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

    $sourceDir = Get-ChildItem -LiteralPath $extractDir -Directory | Select-Object -First 1
    if (-not $sourceDir) {
        throw "Could not extract the Hunyuan3D-2 archive."
    }

    Move-Item -LiteralPath $sourceDir.FullName -Destination $RepoDir
    Remove-Item -LiteralPath $zipPath -Force
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}

function Offer-OnlineFallback {
    param([string]$Reason)

    Write-LauncherLine $Reason Yellow
    Write-Host "[1] Use Online Install" -ForegroundColor DarkGray
    Write-Host "[2] Exit" -ForegroundColor DarkGray
    $choice = Read-Host "Choose 1 or 2"
    return $choice -eq "1"
}

function Invoke-PipInstall {
    param(
        [string]$PythonExe,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    Write-CommandLine -Executable $PythonExe -Arguments $Arguments
    & $PythonExe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Get-LocalRequirementsHash {
    param([string[]]$Files)

    return (
        $Files |
            ForEach-Object { (Get-FileHash -Algorithm SHA256 -LiteralPath $_).Hash }
    ) -join ";"
}

function Get-DesiredState {
    param(
        $Layout,
        [string]$SelectedGpu,
        [bool]$OfflineReady,
        [string]$BootstrapVersion
    )

    $requirementsFile = if ($SelectedGpu -eq "amd") { $Layout.AmdRequirementsFile } else { $Layout.NvidiaRequirementsFile }
    $requirementsHash = Get-LocalRequirementsHash -Files @($Layout.CommonRequirementsFile, $requirementsFile)
    $repoCommit = "f8db63096c8282cb27354314d896feba5ba6ff8a"

    return @{
        requirements_hash = $requirementsHash
        repo_commit = $repoCommit
        bootstrap_version = $BootstrapVersion
        gpu_kind = $SelectedGpu
        offline_ready = $OfflineReady
    }
}

function Test-StateMatches {
    param(
        [string]$StateFile,
        $DesiredState
    )

    if (-not (Test-Path -LiteralPath $StateFile)) {
        return $false
    }

    try {
        $existing = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json
        return (
            $existing.requirements_hash -eq $DesiredState.requirements_hash -and
            $existing.repo_commit -eq $DesiredState.repo_commit -and
            $existing.bootstrap_version -eq $DesiredState.bootstrap_version -and
            $existing.gpu_kind -eq $DesiredState.gpu_kind
        )
    } catch {
        return $false
    }
}

function Save-StateFile {
    param(
        [string]$StateFile,
        $DesiredState
    )

    $DesiredState | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8
}

$Layout = Resolve-Layout
$RepoCommit = "f8db63096c8282cb27354314d896feba5ba6ff8a"
$RepoZipUrl = "https://github.com/Tencent-Hunyuan/Hunyuan3D-2/archive/$RepoCommit.zip"
$BootstrapStateVersion = "0.1.1-r1"

foreach ($dir in @(
        $Layout.ResourcesDir,
        $Layout.LogsDir,
        $Layout.ModelsDir,
        $Layout.HFHome,
        $Layout.LaunchersDataDir
    )) {
    Ensure-Directory -Path $dir
}

$LikelyFreshInstall = -not (Test-Path -LiteralPath (Resolve-VenvExecutable -VenvDir $Layout.VenvDir -Name "python.exe"))
$ActiveLogName = if ($RepairInstall) {
    "repair.log"
} elseif ($CheckOnly) {
    "launcher.log"
} elseif ([bool]$ForceReinstall -or $LikelyFreshInstall) {
    "install.log"
} else {
    "launcher.log"
}
$script:ActiveLogPath = Join-Path $Layout.LogsDir $ActiveLogName
Start-Transcript -LiteralPath $script:ActiveLogPath -Force | Out-Null
$script:TranscriptStarted = $true

try {
    if (-not (Test-Path -LiteralPath $Layout.AppEntryFile)) {
        throw "App launch file was not found at $($Layout.AppEntryFile)."
    }
    foreach ($file in @($Layout.CommonRequirementsFile, $Layout.AmdRequirementsFile, $Layout.NvidiaRequirementsFile)) {
        if (-not (Test-Path -LiteralPath $file)) {
            throw "Missing requirements file: $file"
        }
    }

    if ($RepairInstall) {
        $ForceReinstall = $true
        Write-LauncherLine "Repair Install mode is running. Missing pieces will be rechecked and reinstalled when possible." Yellow
    }

    $env:HF_HOME = $Layout.HFHome
    $env:HF_HUB_CACHE = $Layout.HFHubCache
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

    Set-ProgressStep -Name "Detect GPU" -Message "Detecting GPU backend..."
    $GpuInfo = Get-GpuInfo -RequestedKind $GpuKind
    $SelectedGpu = $GpuInfo.kind
    $DetectedGpuNames = @($GpuInfo.names)
    if (-not $SelectedGpu) {
        $detectedText = if ($DetectedGpuNames.Count -gt 0) { $DetectedGpuNames -join "; " } else { "No AMD Radeon or NVIDIA GPU detected." }
        throw "This package currently supports Windows AMD Radeon and NVIDIA GPUs only. Detected: $detectedText"
    }
    $GpuWheelDir = if ($SelectedGpu -eq "amd") { $Layout.WheelAmdDir } else { $Layout.WheelNvidiaDir }
    $GpuRequirementsFile = if ($SelectedGpu -eq "amd") { $Layout.AmdRequirementsFile } else { $Layout.NvidiaRequirementsFile }
    $GpuLabel = if ($SelectedGpu -eq "amd") { "AMD / ROCm for Windows" } else { "NVIDIA / CUDA" }
    if ($SelectedGpu -eq "amd") {
        $env:ROCM_SDK_TARGET_FAMILY = "custom"
    } else {
        Remove-Item Env:\ROCM_SDK_TARGET_FAMILY -ErrorAction SilentlyContinue
    }
    $DetectedText = if ($DetectedGpuNames.Count -gt 0) { $DetectedGpuNames -join " | " } else { "No GPU names returned by Windows." }
    Write-Host ("Detected adapters: {0}" -f $DetectedText) -ForegroundColor DarkGray
    Write-Host ("GPU path selected: {0}" -f $GpuLabel) -ForegroundColor DarkGray
    if ($SelectedGpu -eq "nvidia" -and -not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        Write-LauncherLine "NVIDIA GPU detected, but nvidia-smi was not found. Your NVIDIA driver may be missing or outdated." Yellow
    }
    Complete-ProgressStep -Name "Detect GPU"

    Set-ProgressStep -Name "Check disk space" -Message "Checking disk space..."
    $RequiredDiskGb = if ($RepairInstall) { 10.0 } elseif ($Layout.IsPackageLayout) { 8.0 } else { 12.0 }
    Test-FreeDiskSpace -Path $Layout.RootDir -RequiredGB $RequiredDiskGb -ModeLabel "3DVisual Mesh setup"
    Complete-ProgressStep -Name "Check disk space"

    Set-ProgressStep -Name "Check Python" -Message "Checking Python 3.12..."
    $PythonCandidate = Resolve-PythonCandidate -Layout $Layout
    if (-not $PythonCandidate) {
        throw "Python runtime missing. Use the Full Offline Package with Python included or run the Online Installer."
    }
    Write-Host ("Python source: {0}" -f $PythonCandidate.Source) -ForegroundColor DarkGray
    Complete-ProgressStep -Name "Check Python"

    Set-ProgressStep -Name "Create local environment" -Message "Creating or reusing the local Python environment..."
    $VenvPythonExe = Resolve-VenvExecutable -VenvDir $Layout.VenvDir -Name "python.exe"
    $VenvPythonWExe = Resolve-VenvExecutable -VenvDir $Layout.VenvDir -Name "pythonw.exe"
    $NeedCreateVenv = $ForceReinstall -or -not (Test-Path -LiteralPath $VenvPythonExe)
    if ($NeedCreateVenv -and -not $CheckOnly) {
        if ((Test-Path -LiteralPath $Layout.VenvDir) -and -not (Test-Path -LiteralPath $VenvPythonExe)) {
            Remove-Item -LiteralPath $Layout.VenvDir -Recurse -Force
        }
        Ensure-Directory -Path (Split-Path -Parent $Layout.VenvDir)
        Invoke-PythonCommand -PythonCandidate $PythonCandidate -Arguments @("-m", "venv", $Layout.VenvDir)
        if ($LASTEXITCODE -ne 0) {
            throw "Local Python environment could not be created."
        }
    } elseif ($NeedCreateVenv -and $CheckOnly) {
        Write-LauncherLine "Check-only: local venv does not exist yet, but the Python runtime is available." Yellow
    }
    if (-not (Test-Path -LiteralPath $VenvPythonExe) -and -not $CheckOnly) {
        throw "Local Python environment could not be created."
    }
    Complete-ProgressStep -Name "Create local environment"

    Expand-SplitWheelFiles -Directories @($Layout.WheelCommonDir, $GpuWheelDir)
    $OfflineWheelhouseReady = Test-WheelhouseAvailable -CommonDir $Layout.WheelCommonDir -GpuDir $GpuWheelDir
    $AllowOnlineInstall = -not $OfflineWheelhouseReady
    if (-not $OfflineWheelhouseReady) {
        $missingParts = @()
        if (-not (Test-DirectoryHasFiles -Path $Layout.WheelCommonDir)) {
            $missingParts += "resources\wheels\common"
        }
        if (-not (Test-DirectoryHasFiles -Path $GpuWheelDir)) {
            if ($SelectedGpu -eq "amd") {
                $missingParts += "resources\wheels\amd"
            } else {
                $missingParts += "resources\wheels\nvidia"
            }
        }
        if ($CheckOnly) {
            Write-LauncherLine ("Check-only: local dependency wheels are missing from {0}." -f ($missingParts -join ", ")) Yellow
        } else {
            $onlineChoice = Offer-OnlineFallback -Reason ((
                "Local dependency wheels are missing from {0}. " +
                "Choose Online Install to download dependencies now, or Exit and use the matching GPU Hotfix Pack or Full Offline Package."
            ) -f ($missingParts -join ", "))
            if (-not $onlineChoice) {
                throw "Install cancelled because local dependency wheels are missing."
            }
        }
    }

    $DesiredState = Get-DesiredState -Layout $Layout -SelectedGpu $SelectedGpu -OfflineReady $OfflineWheelhouseReady -BootstrapVersion $BootstrapStateVersion
    $NeedInstall = [bool]$ForceReinstall -or -not (Test-StateMatches -StateFile $Layout.StateFile -DesiredState $DesiredState)

    Ensure-HunyuanRepo -RepoDir $Layout.RepoDir -VendorDir $Layout.VendorDir -ZipUrl $RepoZipUrl -Commit $RepoCommit -AllowDownload:$AllowOnlineInstall

    Set-ProgressStep -Name "Install common dependencies" -Message "Installing common app dependencies..."
    if ($NeedInstall -and -not $CheckOnly) {
        if ($OfflineWheelhouseReady) {
            Invoke-PipInstall `
                -PythonExe $VenvPythonExe `
                -Arguments @("-m", "pip", "install", "--no-index", "--find-links", $Layout.WheelCommonDir, "-r", $Layout.CommonRequirementsFile) `
                -FailureMessage (
                    "Common dependency install failed from the local wheelhouse. " +
                    "Fix: run Repair Install or extract the matching GPU Hotfix Pack. Log: $($script:ActiveLogPath)"
                )
        } else {
            Invoke-PipInstall `
                -PythonExe $VenvPythonExe `
                -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel") `
                -FailureMessage (
                    "Failed to upgrade pip, setuptools, or wheel. " +
                    "Fix: check internet access, then run Repair Install. Log: $($script:ActiveLogPath)"
                )
            Invoke-PipInstall `
                -PythonExe $VenvPythonExe `
                -Arguments @("-m", "pip", "install", "-r", $Layout.CommonRequirementsFile) `
                -FailureMessage (
                    "Common dependency install failed. " +
                    "Fix: run Repair Install or extract the matching GPU Hotfix Pack. Log: $($script:ActiveLogPath)"
                )
        }
    } elseif ($NeedInstall -and $CheckOnly) {
        Write-LauncherLine "Check-only: common dependency install is still pending for this machine." Yellow
    } else {
        Write-Host "Existing common dependency state matches this package." -ForegroundColor DarkGray
    }
    Complete-ProgressStep -Name "Install common dependencies"

    Set-ProgressStep -Name "Install GPU dependencies" -Message "Installing GPU-specific dependencies..."
    if ($NeedInstall -and -not $CheckOnly) {
        if ($OfflineWheelhouseReady) {
            Invoke-PipInstall `
                -PythonExe $VenvPythonExe `
                -Arguments @("-m", "pip", "install", "--no-index", "--find-links", $Layout.WheelCommonDir, "--find-links", $GpuWheelDir, "-r", $GpuRequirementsFile) `
                -FailureMessage ((
                    "{0} dependency install failed. Reason: local Torch runtime wheel is missing or incompatible. " +
                    "Fix: extract the matching GPU Hotfix Pack, use the Full Offline Package, or run Online Installer with internet. Log: {1}"
                ) -f $GpuLabel, $script:ActiveLogPath)
        } else {
            Invoke-PipInstall `
                -PythonExe $VenvPythonExe `
                -Arguments @("-m", "pip", "install", "-r", $GpuRequirementsFile) `
                -FailureMessage ((
                    "{0} dependency install failed. " +
                    "Fix: run Repair Install or extract the matching GPU Hotfix Pack. Log: {1}"
                ) -f $GpuLabel, $script:ActiveLogPath)
        }

        Invoke-PipInstall `
            -PythonExe $VenvPythonExe `
            -Arguments @("-m", "pip", "install", "-e", $Layout.RepoDir) `
            -FailureMessage (
                "The Hunyuan backend install failed. " +
                "Fix: run Repair Install or use the matching Full Offline Package. Log: $($script:ActiveLogPath)"
            )
        Save-StateFile -StateFile $Layout.StateFile -DesiredState $DesiredState
    } elseif ($NeedInstall -and $CheckOnly) {
        Write-LauncherLine "Check-only: GPU dependency install is still pending for this machine." Yellow
    } else {
        Write-Host "Existing GPU dependency state matches this package." -ForegroundColor DarkGray
    }
    Complete-ProgressStep -Name "Install GPU dependencies"

    Set-ProgressStep -Name "Check model cache" -Message "Checking the local model cache..."
    $ModelCacheReady = Test-ModelCacheReady -HubCacheDir $Layout.HFHubCache
    if ($ModelCacheReady) {
        $env:HF_HUB_OFFLINE = "1"
        Write-Host ("Model cache detected at {0}. Offline model reuse is enabled." -f $Layout.HFHubCache) -ForegroundColor DarkGray
    } else {
        Remove-Item Env:\HF_HUB_OFFLINE -ErrorAction SilentlyContinue
        Write-LauncherLine (
            "Model cache is missing. First run may download model files unless using a Full Offline Package with models included."
        ) Yellow
    }
    Complete-ProgressStep -Name "Check model cache"

    Set-ProgressStep -Name "Verify Torch GPU" -Message "Verifying Torch GPU access..."
    if (-not $CheckOnly) {
        Write-CommandLine -Executable $VenvPythonExe -Arguments @(
            "-c",
            "import sys, torch; ok=torch.cuda.is_available(); print('CUDA=' + str(ok)); print('DEVICE=' + (torch.cuda.get_device_name(0) if ok else 'NONE')); sys.exit(0 if ok else 3)"
        )
        $TorchCheck = & $VenvPythonExe -c "import sys, torch; ok=torch.cuda.is_available(); print('CUDA=' + str(ok)); print('DEVICE=' + (torch.cuda.get_device_name(0) if ok else 'NONE')); sys.exit(0 if ok else 3)"
        if ($LASTEXITCODE -ne 0) {
            throw ((
                "{0} runtime verification failed. " +
                "Likely cause: the GPU driver/runtime is missing or incompatible. " +
                "Fix: check your AMD/NVIDIA driver, then run Repair Install. Log: {1}"
            ) -f $GpuLabel, $script:ActiveLogPath)
        }
        $TorchCheck | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
    }
    Complete-ProgressStep -Name "Verify Torch GPU"

    if ($CheckOnly) {
        Write-LauncherLine "Check-only mode passed." Green
        Stop-LauncherTranscript
        exit 0
    }

    Set-ProgressStep -Name "Start app" -Message "Starting 3DVisual Mesh..."
    $env:THREEVISUAL_WORKSPACE_ROOT = $Layout.AppRoot
    $env:THREEVISUAL_RESOURCES_DIR = $Layout.ResourcesDir
    $env:THREEVISUAL_TOOLS_DIR = $Layout.ToolsDir
    $env:THREEVISUAL_LAUNCHER_DATA_DIR = $Layout.LaunchersDataDir
    $env:THREEVISUAL_HUNYUAN_REPO = $Layout.RepoDir
    $env:THREEVISUAL_PYTHON = $VenvPythonExe
    $env:THREEVISUAL_PYTHONW = $VenvPythonWExe

    if (-not $RepairInstall -and -not $NoLaunch) {
        Start-Process -FilePath $VenvPythonWExe -ArgumentList @("-m", "app.ui_native") -WorkingDirectory $Layout.AppRoot
    } else {
        Write-Host "Launch skipped." -ForegroundColor DarkGray
    }
    Complete-ProgressStep -Name "Start app"
    Write-Host ("Log file: {0}" -f $script:ActiveLogPath) -ForegroundColor DarkGray
} catch {
    foreach ($step in $script:SetupSteps) {
        if ($script:StepStatus[$step] -eq "active") {
            Fail-ProgressStep -Name $step
            break
        }
    }
    Write-LauncherLine $_.Exception.Message Red
    Write-Host ("Log file: {0}" -f $script:ActiveLogPath) -ForegroundColor DarkGray
    Stop-LauncherTranscript
    throw
}

Stop-LauncherTranscript
