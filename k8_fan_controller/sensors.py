from __future__ import annotations

import json
import subprocess
from typing import Dict, Iterable, Optional, Tuple


class SensorsReader:
    """Reads temperature data via lm-sensors and prepares role-specific views."""
    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger
        whitelist = config.get("sensor_whitelist", ()) or ()
        self._adapter_whitelist: Tuple[str, ...] = tuple(whitelist)
        self._temp_keys: Tuple[str, ...] = ("temp1_input", "temp2_input", "temp3_input")

    def get_sensors_json(self) -> Optional[Dict]:
        """Run `sensors -j` and parse JSON, handling common failures."""
        try:
            proc = subprocess.Popen(
                ['sensors', '-j'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            self.logger.error("sensors command not found")
            return None
        except Exception as exc:
            self.logger.error(f"Failed to start sensors command: {exc}")
            return None

        data: Optional[Dict] = None
        try:
            assert proc.stdout is not None
            data = json.load(proc.stdout)
        except json.JSONDecodeError as exc:
            self.logger.error(f"Failed to parse sensors JSON output: {exc}")
        except Exception as exc:
            self.logger.error(f"Unexpected error reading sensors output: {exc}")
        finally:
            if proc.stdout:
                proc.stdout.close()

        stderr_output = ""
        try:
            returncode = proc.wait(timeout=10)
            if proc.stderr:
                stderr_output = proc.stderr.read()
        except subprocess.TimeoutExpired:
            proc.kill()
            self.logger.error("sensors command timed out")
            return None
        finally:
            if proc.stderr:
                proc.stderr.close()

        if returncode != 0:
            detail = f": {stderr_output.strip()}" if stderr_output else ""
            self.logger.error(f"sensors command failed with code {returncode}{detail}")
            return None

        return data

    def read_temperatures(self) -> Optional[Dict[str, float]]:
        sensors_data = self.get_sensors_json()
        if sensors_data is None:
            return None
        return self.extract_temperatures(sensors_data)

    def extract_temperatures(self, sensors_data: Dict) -> Dict[str, float]:
        """Extract a flat mapping of sensor name -> temperature (°C)."""
        temperatures: Dict[str, float] = {}
        if not sensors_data:
            return temperatures
        whitelist = self._adapter_whitelist
        temp_keys: Iterable[str] = self._temp_keys
        try:
            for adapter_name, adapter_data in sensors_data.items():
                if whitelist and not any(token in adapter_name for token in whitelist):
                    continue
                if not isinstance(adapter_data, dict):
                    continue
                for sensor_name, sensor_data in adapter_data.items():
                    if not isinstance(sensor_data, dict):
                        continue
                    recorded = False
                    for temp_key in temp_keys:
                        temp_value = sensor_data.get(temp_key)
                        if isinstance(temp_value, (int, float)) and temp_value > 0:
                            full_sensor_name = f"{adapter_name}:{sensor_name}:{temp_key}"
                            temperatures[full_sensor_name] = float(temp_value)
                            recorded = True
                    if recorded:
                        continue
                    elif 'Tctl' in sensor_name and isinstance(sensor_data, (int, float)):
                        if sensor_data > 0:
                            full_sensor_name = f"{adapter_name}:Tctl"
                            temperatures[full_sensor_name] = float(sensor_data)
                    elif 'edge' in sensor_name and isinstance(sensor_data, (int, float)):
                        if sensor_data > 0:
                            full_sensor_name = f"{adapter_name}:edge"
                            temperatures[full_sensor_name] = float(sensor_data)
                    elif 'Composite' in sensor_name and isinstance(sensor_data, (int, float)):
                        if sensor_data > 0:
                            full_sensor_name = f"{adapter_name}:Composite"
                            temperatures[full_sensor_name] = float(sensor_data)
        except Exception as e:
            self.logger.error(f"Error extracting temperatures: {e}")
        return temperatures

    def validate_temperatures(self, temperatures: Dict[str, float]) -> bool:
        """Basic sanity checks and advisory warnings about configured adapters."""
        if not temperatures:
            self.logger.warning("No temperature readings found")
            return False
        for sensor, temp in temperatures.items():
            if temp < 0 or temp > 150:
                self.logger.warning(f"Unreasonable temperature reading: {sensor} = {temp}°C")
                return False
        csr = self.config.get('critical_sensors_by_role', {}) or {}
        if csr:
            flat = set()
            for lst in csr.values():
                flat.update(lst or [])
            any_match = any(any(ad in name.split(':', 1)[0] for ad in flat) for name in temperatures.keys())
            if not any_match:
                self.logger.warning("No role-critical sensors matched; continuing with all sensors")
        return True

    def sensors_for_role(self, temperatures: Dict[str, float], role: str) -> Dict[str, float]:
        """Filter temperatures to the subset relevant for the given role."""
        mapping = self.config.get('critical_sensors_by_role', {}) or {}
        adapters = mapping.get(role)
        if not adapters:
            return temperatures
        out: Dict[str, float] = {}
        for name, val in temperatures.items():
            adapter = name.split(':', 1)[0]
            if any(a in adapter for a in adapters):
                out[name] = val
        return out or temperatures
