from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # Python <=3.10
    import tomli as _toml  # type: ignore

from .sysfs_utils import resolve_fan_paths


class ConfigManager:
    """Loads and validates controller configuration from TOML file."""
    def __init__(self, path: str):
        self.path = path
        self.config: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        """Load TOML config from `self.path` or raise FileNotFoundError."""
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Config file not found: {self.path}. Run install.sh first.")
        with open(self.path, 'rb') as f:
            self.config = _toml.load(f)
        return self.config

    def save(self):
        """Saving TOML with comments is not supported by this tool.

        Edit the file manually and use the provided reload helper.
        """
        raise NotImplementedError("ConfigManager.save is intentionally disabled for TOML")

    def validate(self, logger=None):
        """Validate presence and shape of critical configuration fields."""
        cfg = self.config
        required_top = [
            "check_interval", "max_fan_speed", "hysteresis", "averaging_samples",
            "min_change_interval", "emergency_temp", "critical_temp",
            "sensor_whitelist", "ramp_start", "ramp_range", "curve_min_speed",
            "rpm_ignore_floor"
        ]
        for key in required_top:
            if key not in cfg:
                raise KeyError(f"Missing config key: {key}")

        fans = cfg.get('fans')
        if not isinstance(fans, list) or not fans:
            raise ValueError("Config must include non-empty 'fans' list from installer")

        adaptive_defaults = {
            'adaptive_enabled': True,
            'adaptive_drop_step': 5,
            'adaptive_raise_step': 15,
            'adaptive_stable_cycles': 5,
            'adaptive_temp_window': 1.5,
            'adaptive_temp_aggressive': 3.0,
        }
        for key, default in adaptive_defaults.items():
            cfg.setdefault(key, default)

        cfg['adaptive_enabled'] = bool(cfg.get('adaptive_enabled'))
        cfg['adaptive_drop_step'] = max(1, int(cfg.get('adaptive_drop_step')))
        cfg['adaptive_raise_step'] = max(1, int(cfg.get('adaptive_raise_step')))
        cfg['adaptive_stable_cycles'] = max(1, int(cfg.get('adaptive_stable_cycles')))
        cfg['adaptive_temp_window'] = float(cfg.get('adaptive_temp_window'))
        cfg['adaptive_temp_aggressive'] = float(cfg.get('adaptive_temp_aggressive'))

        for f in fans:
            for k in ["name", "role", "pwm_path"]:
                if k not in f:
                    raise KeyError(f"Fan entry missing '{k}': {f}")
            if not resolve_fan_paths(f, logger):
                raise FileNotFoundError(
                    f"Unable to resolve PWM path for {f.get('name', f.get('pwm_path', 'unknown'))}"
                )
            if not Path(f["pwm_path"]).exists():
                raise FileNotFoundError(f"PWM path not found: {f['pwm_path']}")
            if f.get("enable_path") and not Path(f["enable_path"]).exists():
                if logger:
                    logger.warning(f"Enable path not found for {f['name']}: {f['enable_path']}")
            if f.get("rpm_path") and not Path(f["rpm_path"]).exists():
                if logger:
                    logger.warning(f"RPM path not found for {f['name']}: {f['rpm_path']}")

        csr = cfg.get('critical_sensors_by_role', {})
        if not isinstance(csr, dict):
            if logger:
                logger.warning("'critical_sensors_by_role' missing or invalid; falling back to all sensors for roles")
            cfg['critical_sensors_by_role'] = {}
