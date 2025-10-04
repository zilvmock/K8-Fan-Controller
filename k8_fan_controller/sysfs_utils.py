from __future__ import annotations

import glob
import os
from typing import Any, Dict, Iterable, Optional

_SYSFS_HWMON_GLOB = "/sys/class/hwmon/hwmon*"


def _read_strip(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read().strip()
    except OSError:
        return None


def ensure_fan_metadata(fan: Dict[str, Any]) -> None:
    """Populate derived metadata fields (pwm_attr, enable_attr, rpm_attr)."""
    pwm_attr = fan.get("pwm_attr")
    if not pwm_attr:
        pwm_path = fan.get("pwm_path")
        if pwm_path:
            fan["pwm_attr"] = os.path.basename(pwm_path)
    pwm_attr = fan.get("pwm_attr")

    enable_attr = fan.get("enable_attr")
    if not enable_attr:
        enable_path = fan.get("enable_path")
        if enable_path:
            fan["enable_attr"] = os.path.basename(enable_path)
        elif pwm_attr:
            fan["enable_attr"] = f"{pwm_attr}_enable"

    rpm_attr = fan.get("rpm_attr")
    if not rpm_attr:
        rpm_path = fan.get("rpm_path")
        if rpm_path:
            fan["rpm_attr"] = os.path.basename(rpm_path)
        elif pwm_attr and pwm_attr.startswith("pwm"):
            suffix = pwm_attr[3:] or "1"
            fan["rpm_attr"] = f"fan{suffix}_input"


def _candidate_directories(fan: Dict[str, Any]) -> Iterable[str]:
    seen = set()
    candidates: list[str] = []

    def add_path(path: Optional[str]):
        if not path:
            return
        real = os.path.realpath(path)
        if real in seen:
            return
        if os.path.isdir(real):
            seen.add(real)
            candidates.append(real)

    hwmon_hint = fan.get("hwmon_path_hint")
    if hwmon_hint:
        add_path(hwmon_hint)

    pwm_path = fan.get("pwm_path")
    if pwm_path:
        dirname = os.path.dirname(pwm_path)
        if dirname:
            add_path(dirname)

    device_path = fan.get("device_path")
    if device_path:
        for hw_dir in sorted(glob.glob(os.path.join(device_path, "hwmon", "hwmon*"))):
            add_path(hw_dir)

    hwmon_name = fan.get("hwmon_name")
    if hwmon_name:
        for hw_dir in glob.glob(_SYSFS_HWMON_GLOB):
            name = _read_strip(os.path.join(hw_dir, "name"))
            if name == hwmon_name:
                add_path(hw_dir)

    for hw_dir in glob.glob(_SYSFS_HWMON_GLOB):
        add_path(hw_dir)

    for candidate in candidates:
        yield candidate


def resolve_fan_paths(fan: Dict[str, Any], logger=None) -> bool:
    """Ensure the fan dict points at existing sysfs paths.

    Returns True if a valid PWM path is confirmed/resolved, else False.
    Updates enable/rpm paths when present.
    """
    ensure_fan_metadata(fan)

    pwm_path = fan.get("pwm_path")
    if pwm_path and os.path.exists(pwm_path):
        # Refresh hint for future lookups and confirm ancillary paths
        hwmon_dir = os.path.realpath(os.path.dirname(pwm_path))
        fan["hwmon_path_hint"] = hwmon_dir
        _populate_related_paths(fan, hwmon_dir)
        return True

    pwm_attr = fan.get("pwm_attr")
    if not pwm_attr:
        if logger:
            logger.error("Unable to determine pwm_attr for fan %s", fan.get("name", "unknown"))
        return False

    original_path = pwm_path
    original_resolved = os.path.realpath(original_path) if original_path else None
    for hw_dir in _candidate_directories(fan):
        candidate = os.path.join(hw_dir, pwm_attr)
        if os.path.exists(candidate):
            resolved = os.path.realpath(candidate)
            fan["pwm_path"] = resolved
            fan["hwmon_path_hint"] = hw_dir
            _populate_related_paths(fan, hw_dir)
            if logger and original_resolved and resolved != original_resolved:
                logger.info(
                    "Resolved fan %s pwm path from %s to %s",
                    fan.get("name", pwm_attr),
                    original_path,
                    fan["pwm_path"],
                )
            elif logger and not original_path:
                logger.info(
                    "Resolved fan %s pwm path to %s",
                    fan.get("name", pwm_attr),
                    fan["pwm_path"],
                )
            return True

    if logger:
        logger.error(
            "Unable to resolve pwm path for fan %s (attr=%s)",
            fan.get("name", pwm_attr),
            pwm_attr,
        )
    return False


def _populate_related_paths(fan: Dict[str, Any], hw_dir: str) -> None:
    if not fan.get("hwmon_path_hint"):
        fan["hwmon_path_hint"] = hw_dir
    if not fan.get("hwmon_name"):
        name = _read_strip(os.path.join(hw_dir, "name"))
        if name:
            fan["hwmon_name"] = name
    if not fan.get("device_path"):
        device = os.path.join(hw_dir, "device")
        if os.path.exists(device):
            fan["device_path"] = os.path.realpath(device)

    enable_attr = fan.get("enable_attr")
    if enable_attr:
        enable_candidate = os.path.join(hw_dir, enable_attr)
        if os.path.exists(enable_candidate):
            fan["enable_path"] = enable_candidate
    rpm_attr = fan.get("rpm_attr")
    if rpm_attr:
        rpm_candidate = os.path.join(hw_dir, rpm_attr)
        if os.path.exists(rpm_candidate):
            fan["rpm_path"] = rpm_candidate


def resolve_all_fans(fans: Iterable[Dict[str, Any]], logger=None) -> bool:
    """Attempt to resolve paths for all fans; returns True if all succeed."""
    success = True
    for fan in fans:
        if not resolve_fan_paths(fan, logger):
            success = False
    return success
