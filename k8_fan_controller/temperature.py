from __future__ import annotations

import time
from typing import Dict, List, Tuple


class TemperatureHistory:
    """Maintains a sliding window of recent temperature snapshots."""
    def __init__(self, max_samples: int):
        self.max_samples = int(max_samples)
        self._history: List[Tuple[float, Dict[str, float]]] = []

    def update(self, temperatures: Dict[str, float]):
        """Append current readings and trim to the configured window size."""
        self._history.append((time.time(), dict(temperatures)))
        if len(self._history) > self.max_samples:
            self._history = self._history[-self.max_samples:]

    def averaged(self) -> Dict[str, float]:
        """Return per-sensor averages across the window to smooth noise."""
        if not self._history:
            return {}
        sensor_readings: Dict[str, List[float]] = {}
        for _, temps in self._history:
            for sensor, temp in temps.items():
                sensor_readings.setdefault(sensor, []).append(temp)
        return {k: sum(v) / len(v) for k, v in sensor_readings.items() if v}
