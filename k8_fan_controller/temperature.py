from __future__ import annotations

from collections import deque
from typing import Deque, Dict


class TemperatureHistory:
    """Maintains a sliding window of recent temperature snapshots."""

    def __init__(self, max_samples: int):
        self.max_samples = max(1, int(max_samples))
        self._samples: Dict[str, Deque[float]] = {}
        self._last_seen: Dict[str, int] = {}
        self._cycle = 0

    def update(self, temperatures: Dict[str, float]):
        """Append current readings and trim to the configured window size."""
        if not temperatures:
            return

        self._cycle += 1
        maxlen = self.max_samples
        for sensor, value in temperatures.items():
            series = self._samples.get(sensor)
            if series is None or series.maxlen != maxlen:
                series = deque(series or (), maxlen=maxlen)
                self._samples[sensor] = series
            series.append(float(value))
            self._last_seen[sensor] = self._cycle

        # Drop sensors that have not reported for a full window
        stale_cutoff = self._cycle - maxlen
        for sensor in list(self._samples.keys()):
            if self._last_seen.get(sensor, 0) <= stale_cutoff:
                self._samples.pop(sensor, None)
                self._last_seen.pop(sensor, None)

    def averaged(self) -> Dict[str, float]:
        """Return per-sensor averages across the window to smooth noise."""
        if not self._samples:
            return {}
        return {
            sensor: sum(values) / len(values)
            for sensor, values in self._samples.items()
            if values
        }
