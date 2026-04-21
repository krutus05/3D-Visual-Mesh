from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass

try:
    import psutil
except ImportError:  # pragma: no cover - optional fallback
    psutil = None


def _bytes_to_gb(value: int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / (1024 ** 3)
    except Exception:
        return None


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _hidden_startup_kwargs() -> dict:
    kwargs: dict = {}
    if os.name != "nt":
        return kwargs

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    kwargs["startupinfo"] = startupinfo
    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def _run_powershell_json(script: str, timeout: float = 5.0) -> dict | list | None:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **_hidden_startup_kwargs(),
        )
    except Exception:
        return None

    if completed.returncode != 0:
        return None

    payload = completed.stdout.strip()
    if not payload:
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


@dataclass
class SystemSnapshot:
    cpu_name: str = "Unknown CPU"
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    cpu_percent: float | None = None
    ram_total_gb: float | None = None
    ram_used_gb: float | None = None
    ram_percent: float | None = None
    gpu_name: str = "Unknown GPU"
    vram_total_gb: float | None = None
    vram_used_gb: float | None = None
    app_vram_used_gb: float | None = None
    gpu_percent: float | None = None
    gpu_temp_c: float | None = None
    note: str = ""


class SystemMonitor:
    def __init__(self):
        self._static_snapshot = self._build_static_snapshot()
        self._last_gpu_refresh = 0.0
        self._gpu_cache: dict = {}

        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

    def _build_static_snapshot(self) -> SystemSnapshot:
        snapshot = SystemSnapshot()

        if psutil is not None:
            try:
                memory = psutil.virtual_memory()
                snapshot.ram_total_gb = _bytes_to_gb(memory.total)
            except Exception:
                pass

            try:
                snapshot.cpu_cores = psutil.cpu_count(logical=False)
                snapshot.cpu_threads = psutil.cpu_count(logical=True)
            except Exception:
                pass

        hardware_info = _run_powershell_json(
            """
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors
            $gpu = Get-CimInstance Win32_VideoController |
              Where-Object { $_.Name -and $_.Name -notmatch 'Microsoft Basic|Remote Display' } |
              Select-Object Name, AdapterRAM
            [pscustomobject]@{
              cpu = $cpu
              gpu = $gpu
            } | ConvertTo-Json -Compress -Depth 4
            """
        )

        if isinstance(hardware_info, dict):
            cpu_info = hardware_info.get("cpu") or {}
            gpu_info = hardware_info.get("gpu") or []
            if isinstance(gpu_info, dict):
                gpu_info = [gpu_info]

            snapshot.cpu_name = cpu_info.get("Name") or snapshot.cpu_name
            snapshot.cpu_cores = snapshot.cpu_cores or cpu_info.get("NumberOfCores")
            snapshot.cpu_threads = snapshot.cpu_threads or cpu_info.get("NumberOfLogicalProcessors")

            if gpu_info:
                primary_gpu = gpu_info[0]
                snapshot.gpu_name = primary_gpu.get("Name") or snapshot.gpu_name
                reported_ram = _bytes_to_gb(primary_gpu.get("AdapterRAM"))
                if reported_ram and reported_ram > 1.0:
                    snapshot.vram_total_gb = reported_ram

        try:
            import torch

            if torch.cuda.is_available():
                snapshot.gpu_name = torch.cuda.get_device_name(0) or snapshot.gpu_name
                total_memory = getattr(torch.cuda.get_device_properties(0), "total_memory", None)
                snapshot.vram_total_gb = _bytes_to_gb(total_memory) or snapshot.vram_total_gb
        except Exception:
            pass

        return snapshot

    def _refresh_gpu_cache(self):
        now = time.monotonic()
        if (now - self._last_gpu_refresh) < 5.0 and self._gpu_cache:
            return

        live_gpu = _run_powershell_json(
            """
            $gpuUsage = $null
            $gpuMem = $null
            $gpuTemp = $null

            try {
              $samples = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples |
                Where-Object { $_.Path -match 'phys_0' -and $_.InstanceName -match 'engtype_3d|engtype_compute' }
              if ($samples) {
                $gpuUsage = ($samples | Measure-Object -Property CookedValue -Maximum).Maximum
              }
            } catch {}

            try {
              $memSamples = (Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction Stop).CounterSamples
              if ($memSamples) {
                $gpuMem = ($memSamples | Measure-Object -Property CookedValue -Maximum).Maximum
              }
            } catch {}

            try {
              $sensor = Get-CimInstance -Namespace 'root/LibreHardwareMonitor' -ClassName Sensor -ErrorAction Stop |
                Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -match 'GPU|Hot Spot|Edge' } |
                Select-Object -First 1
              if ($sensor) {
                $gpuTemp = $sensor.Value
              }
            } catch {}

            [pscustomobject]@{
              gpu_percent = $gpuUsage
              vram_used_bytes = $gpuMem
              gpu_temp_c = $gpuTemp
            } | ConvertTo-Json -Compress
            """
        )

        self._gpu_cache = live_gpu if isinstance(live_gpu, dict) else {}
        self._last_gpu_refresh = now

    def snapshot(self) -> SystemSnapshot:
        snapshot = SystemSnapshot(**self._static_snapshot.__dict__)

        if psutil is not None:
            try:
                snapshot.cpu_percent = _safe_round(psutil.cpu_percent(interval=None), 1)
            except Exception:
                pass

            try:
                memory = psutil.virtual_memory()
                snapshot.ram_total_gb = snapshot.ram_total_gb or _bytes_to_gb(memory.total)
                snapshot.ram_used_gb = _bytes_to_gb(memory.total - memory.available)
                snapshot.ram_percent = _safe_round(memory.percent, 1)
            except Exception:
                pass

        self._refresh_gpu_cache()
        if self._gpu_cache:
            snapshot.gpu_percent = _safe_round(_safe_float(self._gpu_cache.get("gpu_percent")), 1)
            snapshot.vram_used_gb = _bytes_to_gb(self._gpu_cache.get("vram_used_bytes"))
            snapshot.gpu_temp_c = _safe_round(_safe_float(self._gpu_cache.get("gpu_temp_c")), 1)

        try:
            import torch

            if torch.cuda.is_available():
                snapshot.app_vram_used_gb = _bytes_to_gb(torch.cuda.memory_reserved(0))
        except Exception:
            pass

        if snapshot.gpu_temp_c is None:
            snapshot.note = "GPU temp appears only if LibreHardwareMonitor is running with sensors exposed."

        return snapshot


def describe_snapshot(snapshot: SystemSnapshot) -> tuple[str, str, str]:
    cpu_bits: list[str] = [snapshot.cpu_name]
    if snapshot.cpu_cores and snapshot.cpu_threads:
        cpu_bits.append(f"{snapshot.cpu_cores}C / {snapshot.cpu_threads}T")

    gpu_bits: list[str] = [snapshot.gpu_name]
    if snapshot.vram_total_gb is not None:
        gpu_bits.append(f"{snapshot.vram_total_gb:.1f} GB VRAM")

    live_bits: list[str] = []
    if snapshot.cpu_percent is not None:
        live_bits.append(f"CPU {snapshot.cpu_percent:.0f}%")
    if snapshot.ram_percent is not None and snapshot.ram_used_gb is not None and snapshot.ram_total_gb is not None:
        live_bits.append(f"RAM {snapshot.ram_percent:.0f}% ({snapshot.ram_used_gb:.1f}/{snapshot.ram_total_gb:.1f} GB)")
    if snapshot.gpu_percent is not None:
        live_bits.append(f"GPU {snapshot.gpu_percent:.0f}%")
    if snapshot.vram_used_gb is not None and snapshot.vram_total_gb is not None:
        live_bits.append(f"VRAM {snapshot.vram_used_gb:.1f}/{snapshot.vram_total_gb:.1f} GB")
    elif snapshot.vram_used_gb is not None:
        live_bits.append(f"VRAM {snapshot.vram_used_gb:.1f} GB used")
    if snapshot.app_vram_used_gb is not None:
        live_bits.append(f"App VRAM {snapshot.app_vram_used_gb:.1f} GB")
    if snapshot.gpu_temp_c is not None:
        live_bits.append(f"Temp {snapshot.gpu_temp_c:.0f} C")

    return (
        " | ".join(cpu_bits),
        " | ".join(gpu_bits),
        " | ".join(live_bits) if live_bits else "Live usage data not available yet.",
    )
