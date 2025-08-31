#!/usr/bin/env python3
from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Dict

from .config import ConfigManager
from .fan_io import FanIO
from .policy import SpeedPolicy
from .safety import SafetyManager
from .sensors import SensorsReader
from .temperature import TemperatureHistory


class FanController:
    """Coordinates sensor reading, policy, and fan I/O.

    The controller wires together the subsystems and runs a periodic loop
    that:
    - reads temperatures via `SensorsReader`
    - computes per-role target speeds via `SpeedPolicy`
    - enforces safety constraints via `SafetyManager`
    - applies speed changes via `FanIO`

    Dependencies are injectable to support testing and follow dependency
    inversion; when not provided, sensible defaults are constructed.
    """

    def __init__(
        self,
        config_file: str = "/etc/k8-fan-controller-config.toml",
        *,
        logger: logging.Logger | None = None,
        cfg_mgr: ConfigManager | None = None,
        fan_io: FanIO | None = None,
        sensors: SensorsReader | None = None,
        temp_history: TemperatureHistory | None = None,
        policy: SpeedPolicy | None = None,
        safety: SafetyManager | None = None,
    ):
        self.config_file = config_file
        self.logger = logger or self._setup_logging()

        # Load + validate config
        self.cfg_mgr = cfg_mgr or ConfigManager(self.config_file)
        self.config = self.cfg_mgr.load()
        self.cfg_mgr.validate(self.logger)
        self.logger.info(f"Loaded configuration from {self.config_file}")

        # Subsystems (constructed if not injected)
        self.fan_io = fan_io or FanIO(self.config, self.logger)
        self.sensors = sensors or SensorsReader(self.config, self.logger)
        self.temp_history = temp_history or TemperatureHistory(self.config["averaging_samples"]) 
        self.policy = policy or SpeedPolicy(self.config, self.logger)
        self.safety = safety or SafetyManager(self.config, self.fan_io, self.logger)

        # State
        self.consecutive_failures = 0
        self.max_failures = 3
        self.emergency_shutdown = False
        self.last_target_speeds_by_role: Dict[str, int] = {}

        # Signals (graceful shutdown restores auto mode)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle SIGINT/SIGTERM by restoring auto mode and exiting."""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.emergency_shutdown = True
        self.fan_io.restore_automatic_mode()
        sys.exit(0)

    def _setup_logging(self) -> logging.Logger:
        """Create a default logger that logs to file and stderr.

        Falls back to stderr-only if the log file cannot be opened (e.g. when
        not running as root). Returns the configured logger so callers can
        inject their own if desired.
        """
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        # Always log to stderr
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        # Try file logging
        try:
            fh = logging.FileHandler('/var/log/k8-fan-controller.log')
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            # Not fatal; continue with stderr-only
            pass
        return logger

    def run_cycle(self) -> bool:
        """Execute one control loop iteration.

        Returns True to continue, False to stop (e.g. after a critical event
        or too many consecutive failures).
        """
        try:
            sensors_data = self.sensors.get_sensors_json()
            if sensors_data is None:
                self.consecutive_failures += 1
                self.logger.error(f"Failed to get sensor data (failure {self.consecutive_failures}/{self.max_failures})")
                if self.consecutive_failures >= self.max_failures:
                    self.logger.critical("Too many consecutive failures, restoring automatic mode")
                    self.fan_io.restore_automatic_mode()
                    return False
                return True

            temps = self.sensors.extract_temperatures(sensors_data)
            if not self.sensors.validate_temperatures(temps):
                self.consecutive_failures += 1
                self.logger.error(f"Invalid temperature data (failure {self.consecutive_failures}/{self.max_failures})")
                if self.consecutive_failures >= self.max_failures:
                    self.logger.critical("Too many consecutive failures, restoring automatic mode")
                    self.fan_io.restore_automatic_mode()
                    return False
                return True

            # Success path
            self.consecutive_failures = 0
            self.temp_history.update(temps)
            avg_temps = self.temp_history.averaged()
            roles = set(self._roles_to_control())
            target_temps_by_role = {r: self.policy.target_temp_for_role(r, avg_temps, self.sensors) for r in roles}
            max_temp = max(temps.values())

            if self.safety.handle_critical_temperature(max_temp):
                return False

            current_speeds = self.fan_io.get_current_speed_by_role(roles)
            if not current_speeds:
                self.logger.error("Could not read current fan speeds")
                return True

            target_speeds = {r: self.policy.calculate_fan_speed(target_temps_by_role[r], current_speeds.get(r, 0)) for r in roles}
            current_rpms = self.fan_io.get_current_rpm_by_role(roles)
            target_speeds = self.policy.apply_rpm_floors(target_speeds, current_speeds, current_rpms)
            target_speeds = self.policy.clamp_floor_when_lowering(target_speeds, current_speeds, current_rpms)
            smooth_targets = self.policy.smooth_targets(target_speeds, current_speeds)

            # Log compact summary for observability
            sensor_count = len(temps)
            rpms = current_rpms
            self.logger.info(
                f"Sensors: {sensor_count}, Max: {max_temp:.1f}°C, Targets: " +
                ", ".join([f"{r}={target_temps_by_role[r]:.1f}°C" for r in sorted(target_temps_by_role.keys())]) +
                "; Speeds: " +
                ", ".join([f"{r}={current_speeds.get(r,0)}%->{smooth_targets.get(r,0)}%" for r in sorted(smooth_targets.keys())]) +
                ("; RPMs: " + ", ".join([f"{r}={rpms[r]}" for r in sorted(rpms.keys())]) if rpms else "")
            )

            # Apply changes if deltas exceed threshold and interval elapsed
            min_change = int(self.config.get('min_speed_change', 3))
            if any(abs(smooth_targets.get(r,0) - current_speeds.get(r,0)) >= min_change for r in smooth_targets.keys()):
                if time.time() - self.fan_io.last_change_ts < self.config["min_change_interval"]:
                    return True
                if self.fan_io.set_fan_speeds_by_role(smooth_targets, roles):
                    self.last_target_speeds_by_role = dict(smooth_targets)
                    self.logger.info("Applied smoothed per-role fan speeds")
                else:
                    self.logger.error("Failed to set fan speed")
            return True

        except Exception as e:
            self.logger.error(f"Unexpected error in run cycle: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self.logger.critical("Too many consecutive failures, restoring automatic mode")
                self.fan_io.restore_automatic_mode()
                return False
            return True

    def run(self):
        self.logger.info("Fan controller starting...")
        try:
            # Backup modes and set according to config (cpu_auto)
            self.fan_io.backup_current_pwm_mode()
            self.fan_io.enable_modes_from_config()
            self.logger.info("Fan controller started successfully")

            while not self.emergency_shutdown:
                if not self.run_cycle():
                    self.logger.info("Exiting due to critical failure")
                    break
                time.sleep(self.config["check_interval"])

        except KeyboardInterrupt:
            self.logger.info("Fan controller stopped by user")
        except Exception as e:
            self.logger.critical(f"Fatal error: {e}")
        finally:
            self.logger.info("Restoring automatic fan control...")
            self.fan_io.restore_automatic_mode()
            self.logger.info("Fan controller stopped")

    def _roles_to_control(self) -> list[str]:
        roles = self.config.get('roles')
        if roles:
            return list(roles)
        # Fallback: infer from fans list
        unique = []
        seen = set()
        for fan in self.config.get('fans', []):
            r = fan.get('role')
            if r and r not in seen:
                seen.add(r)
                unique.append(r)
        return unique
