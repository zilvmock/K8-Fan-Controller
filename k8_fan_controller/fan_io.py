from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from .sysfs_utils import resolve_fan_paths

class FanIO:
    """Low-level interaction with sysfs PWM and RPM.

    This class is intentionally focused on I/O only (SRP). It exposes
    idempotent helpers for backing up/restoring modes and setting speeds.
    """

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        self.original_pwm_mode: Optional[Dict[str, str]] = None
        self.last_change_ts = 0.0

        for fan in self.config.get('fans', []):
            resolve_fan_paths(fan, self.logger)

    @staticmethod
    def _percent_to_pwm(percent: int) -> int:
        percent = max(0, min(100, int(percent)))
        return int(percent * 255 / 100)

    @staticmethod
    def _pwm_to_percent(pwm_val: int) -> int:
        pwm_val = max(0, min(255, int(pwm_val)))
        return int(round(pwm_val * 100 / 255))

    def backup_current_pwm_mode(self):
        """Capture the current pwm*_enable values to restore later."""
        if self.original_pwm_mode is None:
            self.original_pwm_mode = {}
        for fan in self.config.get('fans', []):
            ep = fan.get('enable_path')
            if not ep or ep in self.original_pwm_mode:
                continue
            try:
                with open(ep, 'r') as f:
                    self.original_pwm_mode[ep] = f.read().strip()
            except Exception as e:
                self.logger.debug(f"Skipping backup for {ep}: {e}")

    def enable_modes_from_config(self):
        """Put relevant fans in manual/auto according to config (cpu_auto)."""
        for fan in self.config.get('fans', []):
            role = fan.get('role', '')
            ep = fan.get('enable_path')
            if not ep:
                continue
            try:
                with open(ep, 'w') as f:
                    if role == 'cpu' and bool(self.config.get('cpu_auto', False)):
                        f.write('2')  # automatic
                    else:
                        f.write('1')  # manual
            except Exception as e:
                self.logger.warning(f"Could not set mode on {ep}: {e}")

    def restore_automatic_mode(self):
        """Restore saved pwm*_enable values (fallback to auto=2)."""
        try:
            for fan in self.config.get('fans', []):
                ep = fan.get('enable_path')
                if not ep:
                    continue
                try:
                    if isinstance(self.original_pwm_mode, dict) and ep in self.original_pwm_mode:
                        val = self.original_pwm_mode[ep]
                    else:
                        val = '2'
                    with open(ep, 'w') as f:
                        f.write(val)
                except Exception as e:
                    self.logger.debug(f"Failed restoring mode for {ep}: {e}")
        except Exception as e:
            self.logger.error(f"Failed to restore modes: {e}")

    def get_current_speed_by_role(self, roles: Set[str]) -> Dict[str, int]:
        """Average current percent duty per role from pwm values."""
        role_speeds: Dict[str, List[int]] = {}
        for fan in self.config.get('fans', []):
            role = fan.get('role')
            if role not in roles:
                continue
            try:
                with open(fan['pwm_path'], 'r') as f:
                    pwm_val = int(f.read().strip())
                    pct = self._pwm_to_percent(pwm_val)
                    role_speeds.setdefault(role, []).append(pct)
            except Exception:
                continue
        return {r: int(sum(v)/len(v)) for r, v in role_speeds.items() if v}

    def get_current_rpm_by_role(self, roles: Set[str]) -> Dict[str, int]:
        """Average current RPM per role where rpm_path exists."""
        role_rpms: Dict[str, List[int]] = {}
        for fan in self.config.get('fans', []):
            role = fan.get('role')
            rpm_path = fan.get('rpm_path')
            if role not in roles or not rpm_path:
                continue
            try:
                with open(rpm_path, 'r') as f:
                    val = int(f.read().strip())
                    if val > 0:
                        role_samples = role_rpms.setdefault(role, [])
                        role_samples.append(val)
            except Exception:
                continue
        return {r: int(sum(v)/len(v)) for r, v in role_rpms.items() if v}

    def set_fan_speeds_by_role(self, speed_map: Dict[str, int], roles: Set[str]) -> bool:
        """Set each role's fans to a target percent (0..100).

        Returns True if all writes succeed, False otherwise. Updates
        `last_change_ts` only on full success to cooperate with the
        controller's min_change_interval enforcement.
        """
        ok = True
        for fan in self.config.get('fans', []):
            role = fan.get('role')
            if role not in roles:
                continue
            if role == 'cpu' and bool(self.config.get('cpu_auto', False)):
                continue
            if role not in speed_map:
                continue
            pct = max(0, min(100, int(speed_map[role])))
            pwm_value = self._percent_to_pwm(pct)
            try:
                with open(fan['pwm_path'], 'w') as f:
                    f.write(str(pwm_value))
            except Exception as e:
                self.logger.error(f"Failed setting {fan['name']} ({role}) to {pct}%: {e}")
                ok = False
        if ok:
            self.last_change_ts = time.time()
        return ok
