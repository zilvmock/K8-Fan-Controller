from __future__ import annotations

import json
import subprocess
from typing import Dict, Optional


class SensorsReader:
    """Reads temperature data via lm-sensors and prepares role-specific views."""
    def __init__(self, config: Dict, logger):
        self.config = config
        self.logger = logger

    def get_sensors_json(self) -> Optional[Dict]:
        """Run `sensors -j` and parse JSON, handling common failures."""
        try:
            result = subprocess.run(
                ['sensors', '-j'],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            if result.returncode != 0:
                self.logger.error(f"sensors command failed with code {result.returncode}")
                return None
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            self.logger.error("sensors command timed out")
            return None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"sensors command failed: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse sensors JSON output: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error getting sensor data: {e}")
            return None

    def extract_temperatures(self, sensors_data: Dict) -> Dict[str, float]:
        """Extract a flat mapping of sensor name -> temperature (°C)."""
        temperatures: Dict[str, float] = {}
        if not sensors_data:
            return temperatures
        try:
            for adapter_name, adapter_data in sensors_data.items():
                if not any(allowed in adapter_name for allowed in self.config["sensor_whitelist"]):
                    continue
                if not isinstance(adapter_data, dict):
                    continue
                for sensor_name, sensor_data in adapter_data.items():
                    if not isinstance(sensor_data, dict):
                        continue
                    if any(temp_key in sensor_data for temp_key in ['temp1_input', 'temp2_input', 'temp3_input']):
                        for temp_key in ['temp1_input', 'temp2_input', 'temp3_input']:
                            if temp_key in sensor_data:
                                temp_value = sensor_data[temp_key]
                                if isinstance(temp_value, (int, float)) and temp_value > 0:
                                    full_sensor_name = f"{adapter_name}:{sensor_name}:{temp_key}"
                                    temperatures[full_sensor_name] = float(temp_value)
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
