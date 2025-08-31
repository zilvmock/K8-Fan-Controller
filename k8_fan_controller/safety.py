from __future__ import annotations

import time
from typing import Dict


class SafetyManager:
    """Enforces hard safety rules independent of the normal control policy."""
    def __init__(self, config: Dict, fan_io, logger):
        self.config = config
        self.fan_io = fan_io
        self.logger = logger

    def handle_critical_temperature(self, max_temp: float) -> bool:
        """Return True after forcing auto mode if critical temperature exceeded."""
        critical_temp = self.config["critical_temp"]
        if max_temp >= critical_temp:
            self.logger.critical(f"CRITICAL TEMPERATURE: {max_temp:.1f}°C >= {critical_temp}°C")
            self.logger.critical("Restoring automatic fan control for safety")
            self.fan_io.restore_automatic_mode()
            time.sleep(30)
            return True
        return False
