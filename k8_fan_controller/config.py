from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # Python <=3.10
    import tomli as _toml  # type: ignore


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

        for f in fans:
            for k in ["name", "role", "pwm_path"]:
                if k not in f:
                    raise KeyError(f"Fan entry missing '{k}': {f}")
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
