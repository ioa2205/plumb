"""Machine state recorded at the start and end of every benchmark (HARDWARE.md protocol).

Readings that need administrator rights (the CPU package temperature) are
recorded as unavailable with the reason, never estimated.
"""

import json
import subprocess
import winreg
from datetime import UTC, datetime
from typing import Any

import psutil

from backend.memory import read_memory

# Windows 11 power mode overlays (HKLM\...\Power\User\PowerSchemes).
POWER_MODES = {
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "Best power efficiency",
    "00000000-0000-0000-0000-000000000000": "Balanced",
    "3af9b8d9-7c97-431d-ad78-34a8bfea439f": "Better performance",
    "ded574b5-45a0-4f42-8737-46345c09c238": "Best performance",
}

_CIM_SCRIPT = (
    "$tz = Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation "
    "| Select-Object Name, Temperature, PercentPassiveLimit, ThrottleReasons; "
    "$cpu = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation "
    "| Where-Object Name -eq '_Total' "
    "| Select-Object PercentProcessorPerformance, ProcessorFrequency, PercentofMaximumFrequency; "
    "$scheme = (powercfg /getactivescheme) -join ' '; "
    "@{ thermal_zones = @($tz); cpu = $cpu; power_scheme = $scheme } | ConvertTo-Json -Depth 4"
)


def _run(argv: list[str], timeout: float = 20) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv to system tools
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _power_mode() -> dict[str, str]:
    key_path = r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            ac = str(winreg.QueryValueEx(key, "ActiveOverlayAcPowerScheme")[0])
    except OSError as error:
        return {"ac_overlay": "unavailable", "reason": str(error)}
    return {"ac_overlay": ac, "name": POWER_MODES.get(ac.lower(), "unknown overlay")}


def _cim() -> dict[str, Any]:
    out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _CIM_SCRIPT])
    if not out:
        return {"error": "CIM query failed"}
    data = json.loads(out)
    zones = []
    for zone in data.get("thermal_zones") or []:
        kelvin = zone.get("Temperature")
        zones.append(
            {
                "name": zone.get("Name"),
                "celsius": round(kelvin - 273.15, 1) if isinstance(kelvin, int | float) else None,
                "percent_passive_limit": zone.get("PercentPassiveLimit"),
                "throttle_reasons": zone.get("ThrottleReasons"),
            }
        )
    return {
        "thermal_zones": zones,
        "cpu": data.get("cpu"),
        "power_scheme": data.get("power_scheme"),
    }


def _gpu() -> dict[str, Any]:
    fields = "name,temperature.gpu,memory.used,memory.free,driver_version,pstate,clocks.sm"
    out = _run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"])
    if not out:
        return {"error": "nvidia-smi unavailable"}
    values = [v.strip() for v in out.strip().splitlines()[0].split(",")]
    return dict(zip(fields.split(","), values, strict=False))


def machine_state() -> dict[str, Any]:
    battery = psutil.sensors_battery()
    memory = read_memory()
    cim = _cim()
    return {
        "time": datetime.now(UTC).isoformat(),
        "power_plugged": battery.power_plugged if battery else None,
        "battery_percent": battery.percent if battery else None,
        "power_scheme": cim.pop("power_scheme", None),
        "power_mode": _power_mode(),
        "memory": {
            "total_bytes": memory.total_bytes,
            "available_bytes": memory.available_bytes,
            "commit_limit_bytes": memory.commit_limit_bytes,
            "commit_used_bytes": memory.commit_used_bytes,
        },
        "cpu_package_temperature": (
            "unavailable: needs administrator (MSAcpi_ThermalZoneTemperature)"
        ),
        "acpi_thermal_zones_note": "ACPI zones are chassis sensors, not the CPU package",
        **cim,
        "gpu": _gpu(),
    }
