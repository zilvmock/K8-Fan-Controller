from __future__ import annotations

from typing import Dict, Set


class SpeedPolicy:
    """Encapsulates how temperatures map to target fan speeds.

    Open for extension: alternate policies can be introduced without changing
    the controller. This class contains no I/O and is easy to test.
    """

    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger

    def calculate_target_temperature(self, temperatures: Dict[str, float]) -> float:
        """Weighted aggregate used for global reasoning if needed.

        Not currently used by the controller, but kept for completeness and
        potential future strategies that consider cross-role coupling.
        """
        if not temperatures:
            return 0.0
        csr = self.config.get('critical_sensors_by_role', {}) or {}
        if csr:
            adapters = set()
            for lst in csr.values():
                adapters.update(lst or [])
            role_crit = [v for k, v in temperatures.items() if any(ad in k.split(':', 1)[0] for ad in adapters)]
            if role_crit:
                all_vals = list(temperatures.values())
                max_critical = max(role_crit)
                avg_all = sum(all_vals) / len(all_vals)
                return max_critical * 0.7 + avg_all * 0.3
        return max(temperatures.values())

    def target_temp_for_role(self, role: str, temperatures: Dict[str, float], sensors_reader) -> float:
        """Pick the role's governing temperature (typically max of its sensors)."""
        role_temps = sensors_reader.sensors_for_role(temperatures, role)
        if not role_temps:
            return 0.0
        return max(role_temps.values())

    def calculate_fan_speed(self, target_temp: float, current_speed: int) -> int:
        """Map role temperature to a raw percent target using configured curve."""
        emergency_temp = self.config["emergency_temp"]
        max_speed = self.config["max_fan_speed"]
        hysteresis = self.config["hysteresis"]
        if target_temp >= emergency_temp:
            return max_speed
        return self._target_percent(
            target_temp=target_temp,
            current_percent=current_speed if current_speed is not None else 0,
            hysteresis=hysteresis,
            max_speed=max_speed,
        )

    def apply_rpm_floors(self, target_speeds: Dict[str, int], current_speeds: Dict[str, int], current_rpms: Dict[str, int]) -> Dict[str, int]:
        """No proactive bump-ups based on RPM floors.

        Initial RPM floor logic has been removed; we only guard against
        lowering speeds below a safe RPM via `clamp_floor_when_lowering`.
        """
        return target_speeds

    def clamp_floor_when_lowering(self, target_speeds: Dict[str, int], current_speeds: Dict[str, int], current_rpms: Dict[str, int]) -> Dict[str, int]:
        """Prevent reductions that would drop a role under its RPM ignore floor.

        Applies to both 'cpu' and 'case'. Raising speed is unaffected. Uses a
        simple proportional estimate based on current RPM and percent.
        """
        updated = dict(target_speeds)
        floor = int(self.config.get('rpm_ignore_floor', 800))
        for role in list(updated.keys()):
            cur_pct = current_speeds.get(role)
            raw_target = updated.get(role)
            cur_rpm = current_rpms.get(role)
            if (
                raw_target is not None and cur_pct is not None and cur_pct > 0 and
                cur_rpm is not None and cur_rpm > 0 and
                raw_target < cur_pct
            ):
                est_rpm = cur_rpm * (raw_target / float(cur_pct))
                if est_rpm < floor:
                    self.logger.debug(
                        f"{role.upper()} lowering skipped to avoid < {floor} RPM (est {int(est_rpm)}RPM)"
                    )
                    updated[role] = cur_pct
        return updated

    def smooth_targets(self, target_speeds: Dict[str, int], current_speeds: Dict[str, int]) -> Dict[str, int]:
        """Apply targets directly, clamped to 0..100.

        Step limiting is not applied here; the controller enforces
        `min_change_interval` and `min_speed_change` to avoid chatter.
        """
        direct: Dict[str, int] = {}
        for role, raw_target in target_speeds.items():
            direct[role] = int(max(0, min(100, raw_target)))
        return direct

    # Internal helpers
    def _target_percent(self, target_temp: float, current_percent: int, hysteresis: int, max_speed: int) -> int:
        """Compute target fan percent from temperature using a simple ramp.

        Uses config keys: ramp_start, ramp_range, curve_min_speed.
        """
        rstart = float(self.config['ramp_start'])
        rrange = max(float(self.config['ramp_range']), 1.0)
        min_spd = int(self.config['curve_min_speed'])

        effective_threshold = rstart - (hysteresis if current_percent > min_spd else 0)

        if target_temp <= effective_threshold:
            return min_spd
        if target_temp >= rstart + rrange:
            return max_speed

        ratio = (target_temp - effective_threshold) / rrange
        ratio = max(0.0, min(1.0, ratio))
        return min_spd + int(ratio * (max_speed - min_spd))
