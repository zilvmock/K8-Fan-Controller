#!/usr/bin/env bash
# Smart Fan Controller for GMKtech K8 Plus Mini PC installation script

set -euo pipefail
shopt -s extglob

echo "Installing Smart Fan Controller for GMKtech K8 Plus..."

# Require root
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "This script must be run as root (use sudo)"
  exit 1
fi

# Debian/Ubuntu-only: install dependencies with apt-get
echo "Installing required packages (python3, lm-sensors, logrotate, tomli if needed) via apt-get..."
if ! command -v apt-get >/dev/null 2>&1; then
  echo "Error: apt-get not found. This installer supports Debian/Ubuntu only."
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends python3 lm-sensors logrotate python3-tomli || \
  apt-get install -y --no-install-recommends python3 lm-sensors logrotate || true

# Run sensors-detect non-interactively
echo "Running sensors-detect non-interactively to configure lm-sensors..."
if command -v sensors-detect >/dev/null 2>&1; then
  # Using --auto makes piping `yes` unnecessary and avoids SIGPIPE with pipefail
  if sensors-detect --auto; then
    :
  else
    echo "Warning: sensors-detect exited non-zero; continuing. You may need to run it manually." >&2
  fi
else
  echo "Warning: sensors-detect not found after installation; skipping auto configuration."
fi

# Check for required dependencies (lm-sensors JSON output)
echo "Validating lm-sensors ('sensors -j')..."
if ! sensors -j > /dev/null 2>&1; then
  echo "Error: 'sensors -j' failed. Ensure lm-sensors is configured (run 'sensors-detect' manually)."
  exit 1
fi

echo
echo "IMPORTANT: Adapters in the config must match your system for correct operation."

echo "Scanning sensors to propose adapter groups..."

SENSOR_DETECTION=$(python3 - <<'PY'
import json
import subprocess

DEFAULT_WHITELIST = {
    "k10temp-pci-",
    "coretemp-isa-",
    "zenpower-pci-",
    "amdgpu-pci-",
    "it8613-isa-",
    "nvme-pci-",
    "acpitz-acpi-",
    "spd5118-i2c-",
}

DEFAULT_CPU = {
    "k10temp-pci-",
    "coretemp-isa-",
    "zenpower-pci-",
    "amdgpu-pci-",
}

DEFAULT_CASE = {
    "nvme-pci-",
    "amdgpu-pci-",
    "it8613-isa-",
    "acpitz-acpi-",
    "spd5118-i2c-",
}

ROLE_PATTERNS = {
    "cpu": ["k10temp", "coretemp", "zenpower", "tctl", "amdgpu", "radeon"],
    "case": ["nvme", "it86", "acpitz", "pch", "amdgpu", "radeon", "spd"],
}


def canonical(name: str) -> str:
    parts = name.split('-')
    if len(parts) <= 1:
        return name
    while len(parts) > 1:
        last = parts[-1]
        lowered = last.lower()
        if not last:
            parts = parts[:-1]
            continue
        if last.isdigit() or (len(last) <= 4 and all(c in "0123456789abcdef" for c in lowered)):
            parts = parts[:-1]
        else:
            break
    if len(parts) == 1:
        return parts[0]
    return '-'.join(parts) + '-'


used_defaults = False
try:
    output = subprocess.check_output(['sensors', '-j'], text=True, timeout=10)
    data = json.loads(output)
    adapters = list(data.keys())
except Exception:
    adapters = []
    used_defaults = True

whitelist = set()
role_map = {role: set() for role in ROLE_PATTERNS.keys()}

for adapter in adapters:
    canon = canonical(adapter)
    if canon:
        whitelist.add(canon)
    else:
        whitelist.add(adapter)
    lower = adapter.lower()
    for role, patterns in ROLE_PATTERNS.items():
        if any(p in lower for p in patterns):
            role_map[role].add(canon or adapter)

if not whitelist:
    used_defaults = True
    whitelist = set(DEFAULT_WHITELIST)

summary_lines = []
raw_adapters = sorted(adapters)
summary_lines.append("System adapters (raw from sensors -j):")
if raw_adapters:
    for name in raw_adapters:
        summary_lines.append(f"  - {name}")
else:
    summary_lines.append("  (none detected)")
summary_lines.append("")
sorted_whitelist = sorted(whitelist)
summary_lines.append("Proposed adapter prefixes to whitelist:")
if used_defaults:
    summary_lines.append("  (using defaults; sensors -j unavailable)")
for name in sorted_whitelist:
    summary_lines.append(f"  - {name}")
summary_lines.append("")
summary_lines.append("Role assignments (prefixes):")
for role in sorted(role_map.keys()):
    entries = sorted(role_map[role])
    if not entries:
        entries = sorted(DEFAULT_CPU if role == 'cpu' else DEFAULT_CASE)
        summary_lines.append(f"  {role}: (defaults) {', '.join(entries)}")
    else:
        summary_lines.append(f"  {role}: {', '.join(entries)}")

if not role_map['cpu']:
    role_map['cpu'].update(DEFAULT_CPU)
if not role_map['case']:
    role_map['case'].update(DEFAULT_CASE)

config_lines = []
if used_defaults:
    config_lines.append('# sensor_whitelist populated with defaults (auto-detect unavailable)')
else:
    config_lines.append('# sensor_whitelist populated automatically from sensors -j')
config_lines.append('sensor_whitelist = [')
for idx, name in enumerate(sorted_whitelist):
    comma = ',' if idx < len(sorted_whitelist) - 1 else ''
    config_lines.append(f'  "{name}"{comma}')
config_lines.append(']')
config_lines.append('')
config_lines.append('[critical_sensors_by_role]')
for role in sorted(role_map.keys()):
    entries = sorted(role_map[role])
    if not entries:
        continue
    config_lines.append(f'{role} = [')
    for idx, name in enumerate(entries):
        comma = ',' if idx < len(entries) - 1 else ''
        config_lines.append(f'  "{name}"{comma}')
    config_lines.append(']')

print('\n'.join(summary_lines))
print('__SPLIT__')
print('\n'.join(config_lines))
PY
)

SENSOR_SUMMARY=${SENSOR_DETECTION%%__SPLIT__*}
SENSOR_CONFIG_TOML=${SENSOR_DETECTION#*__SPLIT__}
SENSOR_CONFIG_TOML=${SENSOR_CONFIG_TOML#__SPLIT__\n}

echo
echo "Detected sensor configuration:"
printf '%s\n' "$SENSOR_SUMMARY"
echo
read -r -p "Use these sensor adapters and role assignments? [Y/n]: " SENSOR_ACCEPT
case "${SENSOR_ACCEPT,,}" in
  y|yes|"" ) echo "Adapters confirmed." ;;
  *)
    read -r -p "Have you already updated k8-config-default.toml with the correct adapters? [y/N]: " SENSOR_DEFAULT_OK
    case "${SENSOR_DEFAULT_OK,,}" in
      y|yes)
        echo "Using adapters from k8-config-default.toml."
        SENSOR_CONFIG_TOML=$(python3 - <<'PY'
import json
import subprocess
try:
    import tomllib as toml
except Exception:
    import tomli as toml  # type: ignore

DEFAULT_WHITELIST = {
    "k10temp-pci-",
    "coretemp-isa-",
    "zenpower-pci-",
    "amdgpu-pci-",
    "it8613-isa-",
    "nvme-pci-",
    "acpitz-acpi-",
    "spd5118-i2c-",
}

DEFAULT_CPU = {
    "k10temp-pci-",
    "coretemp-isa-",
    "zenpower-pci-",
    "amdgpu-pci-",
}

DEFAULT_CASE = {
    "nvme-pci-",
    "amdgpu-pci-",
    "it8613-isa-",
    "acpitz-acpi-",
    "spd5118-i2c-",
}

def load_defaults():
    try:
        with open('k8-config-default.toml', 'rb') as f:
            cfg = toml.load(f)
    except Exception:
        cfg = {}
    whitelist = cfg.get('sensor_whitelist') or []
    roles = cfg.get('critical_sensors_by_role') or {}
    if not whitelist:
        whitelist = sorted(DEFAULT_WHITELIST)
    blocks = []
    blocks.append('sensor_whitelist = [')
    for idx, name in enumerate(whitelist):
        comma = ',' if idx < len(whitelist) - 1 else ''
        blocks.append(f'  "{name}"{comma}')
    blocks.append(']')
    blocks.append('')
    blocks.append('[critical_sensors_by_role]')
    if roles:
        for role in sorted(roles.keys()):
            entries = roles[role] or []
            blocks.append(f'{role} = [')
            for idx, name in enumerate(entries):
                comma = ',' if idx < len(entries) - 1 else ''
                blocks.append(f'  "{name}"{comma}')
            blocks.append(']')
    else:
        blocks.append('cpu = [')
        defaults = sorted(DEFAULT_CPU)
        for idx, name in enumerate(defaults):
            comma = ',' if idx < len(defaults) - 1 else ''
            blocks.append(f'  "{name}"{comma}')
        blocks.append(']')
        blocks.append('case = [')
        defaults = sorted(DEFAULT_CASE)
        for idx, name in enumerate(defaults):
            comma = ',' if idx < len(defaults) - 1 else ''
            blocks.append(f'  "{name}"{comma}')
        blocks.append(']')
    print('\n'.join(blocks))

load_defaults()
PY
        )
        ;;
      *)
        echo "Please edit k8-config-default.toml to match your sensors and re-run."
        exit 1
        ;;
    esac
    ;;
esac

# Detect correct PWM path
found=0
declare -a found_pwms=()
for hwmon in /sys/class/hwmon/hwmon*; do
    base_pwm_files=("$hwmon"/pwm+([0-9]))
    if compgen -G "$hwmon"/pwm+([0-9]) > /dev/null; then
        echo "Found fan controls in: $hwmon"
        for pwm in "${base_pwm_files[@]}"; do
            if [ -w "$pwm" ]; then
                echo "  -> Writable control: $(basename "$pwm")"
                found=1
                found_pwms+=("$pwm")
            else
                echo "  -> Found but not writable (need root?): $(basename "$pwm")"
            fi
        done
    fi
done

if [ $found -eq 0 ]; then
    echo "Error: No PWM fan controls found! Run 'sensors-detect' and reboot, then re-run this installer."
    exit 1
fi

if [ ${#found_pwms[@]} -gt 0 ]; then
  echo "Current fan controls and speeds:"
  for pwm in "${found_pwms[@]}"; do
    pwm_name=$(basename "$pwm")
    pwm_val="?"
    if [ -r "$pwm" ]; then
      pwm_val=$(cat "$pwm" 2>/dev/null || echo "?")
    fi
  rpm_path="$(dirname "$pwm")/fan${pwm_name#pwm}_input"
    if [ -f "$rpm_path" ] && [ -r "$rpm_path" ]; then
      rpm_val=$(cat "$rpm_path" 2>/dev/null || echo "?")
      echo "  -> $pwm_name: ${pwm_val} (PWM), ${rpm_val} RPM"
    else
      echo "  -> $pwm_name: ${pwm_val} (PWM)"
    fi
  done
fi

echo "Interactive fan identification (we'll spin each fan briefly):"

# Prepare mapping file for Python to build config later
FANS_MAP_FILE="/tmp/fans_map.txt"
> "$FANS_MAP_FILE"

SELECTED_CPU_PWM=""
SELECTED_CPU_ENABLE=""

for pwm in "${found_pwms[@]}"; do
  pwm_name=$(basename "$pwm")
  dir=$(dirname "$pwm")
  enable_path="$dir/${pwm_name}_enable"
  rpm_path="$dir/fan${pwm_name#pwm}_input"

  hwmon_path="$dir"
  hwmon_name=""
  if [ -f "$dir/name" ]; then
    hwmon_name=$(tr -d '\n' < "$dir/name" 2>/dev/null || echo "")
  fi
  device_path=""
  if [ -e "$dir/device" ]; then
    device_path=$(readlink -f "$dir/device" 2>/dev/null || echo "")
  fi
  enable_attr=""
  if [ -n "$enable_path" ]; then
    enable_attr=$(basename "$enable_path")
  else
    enable_attr="${pwm_name}_enable"
  fi
  rpm_attr=""
  if [ -n "$rpm_path" ]; then
    rpm_attr=$(basename "$rpm_path")
  elif [[ "$pwm_name" == pwm* ]]; then
    rpm_attr="fan${pwm_name#pwm}_input"
  fi

  prev_enable=""
  if [ -f "$enable_path" ] && [ -r "$enable_path" ]; then
    prev_enable=$(cat "$enable_path" 2>/dev/null || echo "")
    # Try to enable manual control
    if [ -w "$enable_path" ]; then echo 1 > "$enable_path" 2>/dev/null || true; fi
  fi

  # Capture current duty and RPM
  prev_pwm=$(cat "$pwm" 2>/dev/null || echo "")
  rpm_before=""
  if [ -f "$rpm_path" ] && [ -r "$rpm_path" ]; then
    rpm_before=$(cat "$rpm_path" 2>/dev/null || echo "")
  fi

  echo "-- Testing $pwm_name: setting to max (255) for identification..."
  if [ -w "$pwm" ]; then echo 255 > "$pwm" 2>/dev/null || true; fi
  sleep 2

  rpm_after=""
  if [ -f "$rpm_path" ] && [ -r "$rpm_path" ]; then
    rpm_after=$(cat "$rpm_path" 2>/dev/null || echo "")
  fi

  # If we can read RPM and it's 0 before and after, skip as non-existing
  if [ -n "$rpm_before" ] && [ -n "$rpm_after" ] && [ "$rpm_before" = "0" ] && [ "$rpm_after" = "0" ]; then
    echo "  -> $pwm_name appears non-existent or not working (0 RPM). Skipping."
  else
    # Ask user to classify this fan, wait up to 10s while spinning at max
      # Keep prompting up to 300s (5 min) for a valid answer: c/k/s/q
      start_ts=$(date +%s)
      answered=0
      while true; do
        now_ts=$(date +%s)
        elapsed=$(( now_ts - start_ts ))
        if [ $elapsed -ge 300 ]; then
          echo "  -> Timed out for this fan; continuing without assignment."
          break
        fi
        remain=$(( 300 - elapsed ))
        echo -n "  -> Identify $pwm_name role: [c]pu / [k]ase / [s]kip / [q]uit (${remain}s left): "
        if read -r -t "$remain" answer; then
          case "${answer,,}" in
            q|quit)
              echo "  -> Quitting per user request. Restoring fan state..."
              # Restore prior duty and enable before quitting
              if [ -n "$prev_pwm" ] && [ -w "$pwm" ]; then echo "$prev_pwm" > "$pwm" 2>/dev/null || true; fi
              if [ -n "$prev_enable" ] && [ -w "$enable_path" ]; then echo "$prev_enable" > "$enable_path" 2>/dev/null || true; fi
              # Set all fans to automatic for safety
              for path in /sys/class/hwmon/hwmon*/pwm*_enable; do
                [ -e "$path" ] || continue
                if [ -w "$path" ]; then echo 2 > "$path" 2>/dev/null || true; fi
              done
              exit 0
              ;;
            c|cpu)
              if [ -n "$SELECTED_CPU_PWM" ]; then
                echo "  -> CPU fan already defined; choose case, skip, or quit."
                continue
              fi
              echo "  -> Recorded $pwm_name as CPU fan"
              printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
                "$pwm_name" "cpu" "$pwm" "$enable_path" "$rpm_path" \
                "$hwmon_path" "$hwmon_name" "$device_path" "$enable_attr" "$rpm_attr" >> "$FANS_MAP_FILE"
              SELECTED_CPU_PWM="$pwm"
              SELECTED_CPU_ENABLE="$enable_path"
              answered=1
              break
              ;;
            k|case)
              echo "  -> Recorded $pwm_name as case fan"
              printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
                "$pwm_name" "case" "$pwm" "$enable_path" "$rpm_path" \
                "$hwmon_path" "$hwmon_name" "$device_path" "$enable_attr" "$rpm_attr" >> "$FANS_MAP_FILE"
              answered=1
              break
              ;;
            s|skip)
              echo "  -> Skipping $pwm_name (no role assigned)"
              answered=1
              break
              ;;
            *)
              echo "  -> Invalid choice. Please enter c, k, s, or q."
              ;;
          esac
        else
          # read timed out; loop will re-check remaining time
          :
        fi
      done
    fi

  # Restore prior duty and enable before continuing
  if [ -n "$prev_pwm" ] && [ -w "$pwm" ]; then echo "$prev_pwm" > "$pwm" 2>/dev/null || true; fi
  if [ -n "$prev_enable" ] && [ -w "$enable_path" ]; then echo "$prev_enable" > "$enable_path" 2>/dev/null || true; fi
  sleep 1
done

# Create directories
echo
echo "Installing fan controller package..."
echo "Creating directories..."
INSTALL_ROOT="/opt/k8-fan-controller"
rm -rf "$INSTALL_ROOT"
mkdir -p "$INSTALL_ROOT"
mkdir -p /var/log

echo "Locating zipapp bundle..."
ZIPAPP_SRC=""
if [[ -f "k8-fan-controller.pyz" ]]; then
  ZIPAPP_SRC="k8-fan-controller.pyz"
else
  shopt -s nullglob
  mapfile -t _zip_matches < <(printf '%s\n' k8-fan-controller-*.pyz | sort)
  shopt -u nullglob
  if [[ ${#_zip_matches[@]} -gt 0 ]]; then
    last_index=$(( ${#_zip_matches[@]} - 1 ))
    ZIPAPP_SRC="${_zip_matches[$last_index]}"
  fi
fi

TMP_ZIPAPP_DIR=""
if [[ -z "$ZIPAPP_SRC" ]]; then
  if [[ -d "k8_fan_controller" ]]; then
    echo "No prebuilt zipapp found; building from local sources..."
    TMP_ZIPAPP_DIR=$(mktemp -d)
    python3 -m zipapp k8_fan_controller \
      -p "/usr/bin/env python3" \
      -o "$TMP_ZIPAPP_DIR/k8-fan-controller.pyz"
    ZIPAPP_SRC="$TMP_ZIPAPP_DIR/k8-fan-controller.pyz"
  else
    echo "Error: zipapp bundle not found and source directory 'k8_fan_controller' unavailable"
    exit 1
  fi
else
  echo "Using existing bundle: $ZIPAPP_SRC"
fi

echo "Copying bundle to $INSTALL_ROOT..."
cp "$ZIPAPP_SRC" "$INSTALL_ROOT/k8-fan-controller.pyz"
chmod 755 "$INSTALL_ROOT/k8-fan-controller.pyz"

if [[ -n "$TMP_ZIPAPP_DIR" ]]; then
  rm -rf "$TMP_ZIPAPP_DIR"
fi

# Install systemd service
echo "Installing systemd service..."
cat > /etc/systemd/system/k8-fan-controller.service << 'SERVICE'
[Unit]
Description=GMKtech K8 Fan Controller
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/env python3 /opt/k8-fan-controller/k8-fan-controller.pyz
Restart=on-failure
RestartSec=5
WorkingDirectory=/opt/k8-fan-controller
User=root

[Install]
WantedBy=multi-user.target
SERVICE

echo "Creating configuration file: /etc/k8-fan-controller-config.toml"
OUT_TOML="/etc/k8-fan-controller-config.toml"
FANS_MAP_FILE="/tmp/fans_map.txt"
mkdir -p /etc

{
cat <<'TOML'
# K8 Fan Controller Configuration (TOML)
#
# Edit values and run `k8fc reload` to apply.

# check_interval: seconds between control loop iterations
check_interval = 1

# averaging_samples: number of recent samples to average per sensor
averaging_samples = 6

# min_change_interval: seconds to wait between applying speed changes
min_change_interval = 1

# min_speed_change: minimum percent delta before applying changes
min_speed_change = 3

# max_fan_speed: upper bound for duty cycle (percent)
max_fan_speed = 100

# hysteresis: temperature hysteresis (°C) to avoid oscillation on downshift
hysteresis = 3

# emergency_temp: force max speed at/above this temperature (°C)
emergency_temp = 75

# critical_temp: restore automatic mode for safety at/above this temperature (°C)
critical_temp = 85

# ramp_start: temperature (°C) where the ramp begins
ramp_start = 50

# ramp_range: degrees (°C) from ramp_start to reach max_fan_speed
ramp_range = 15

# curve_min_speed: percent duty when at/below (ramp_start - hysteresis if above min)
curve_min_speed = 20

# rpm_ignore_floor: skip lowering speed if estimated RPM would drop below this
rpm_ignore_floor = 800

# Adaptive controller settings
adaptive_enabled = true
adaptive_drop_step = 5
adaptive_raise_step = 15
adaptive_stable_cycles = 5
adaptive_temp_window = 1.5
adaptive_temp_aggressive = 3.0

# cpu_auto: if true, leave CPU fan(s) in motherboard automatic mode
cpu_auto = false

# roles: roles under control; if absent, inferred from fans[]
# roles = ["cpu", "case"]
TOML

printf "%s\n" "$SENSOR_CONFIG_TOML"

cat <<'TOML'

# Fans discovered by installer
# Add/edit entries as needed
TOML

if [[ -f "$FANS_MAP_FILE" ]]; then
  while IFS=$'\t' read -r name role pwm_path enable_path rpm_path hwmon_path hwmon_name device_path enable_attr rpm_attr; do
    [[ -z "$name" ]] && continue
    echo "[[fans]]"
    echo "name = \"$name\""
    echo "role = \"$role\""
    if [[ -n "$pwm_path" ]]; then echo "pwm_path = \"$pwm_path\""; fi
    if [[ -n "$enable_path" ]]; then echo "enable_path = \"$enable_path\""; fi
    if [[ -n "$rpm_path" ]]; then echo "rpm_path = \"$rpm_path\""; fi
    if [[ -n "$hwmon_path" ]]; then echo "hwmon_path_hint = \"$hwmon_path\""; fi
    if [[ -n "$hwmon_name" ]]; then echo "hwmon_name = \"$hwmon_name\""; fi
    if [[ -n "$device_path" ]]; then echo "device_path = \"$device_path\""; fi
    if [[ -n "$enable_attr" ]]; then echo "enable_attr = \"$enable_attr\""; fi
    if [[ -n "$rpm_attr" ]]; then echo "rpm_attr = \"$rpm_attr\""; fi
    echo
  done < "$FANS_MAP_FILE"
fi

# Example presets (commented):
#
# [preset.safest]
# ramp_start = 50
# ramp_range = 15
# curve_min_speed = 15
# cpu_auto = true
# rpm_ignore_floor = 800
# roles = ["case"]
#
# [preset.standart]  # default-like
# ramp_start = 50
# ramp_range = 15
# curve_min_speed = 20
# cpu_auto = false
# rpm_ignore_floor = 800
# roles = ["cpu", "case"]
#
# [preset.aggresive]
# ramp_start = 40
# ramp_range = 10
# curve_min_speed = 30
# cpu_auto = false
# rpm_ignore_floor = 1000
# roles = ["cpu", "case"]
} > "$OUT_TOML"

echo "Wrote TOML config to $OUT_TOML"






# Logrotate configuration for the controller log
echo "Installing logrotate configuration..."
cat > /etc/logrotate.d/k8-fan-controller << 'LOGROTATE'
/var/log/k8-fan-controller.log {
  weekly
  rotate 4
  missingok
  notifempty
  compress
  delaycompress
  copytruncate
}
LOGROTATE

# Reload systemd and enable service
if command -v systemctl >/dev/null 2>&1; then
  echo "Enabling and starting service..."
  systemctl daemon-reload
  systemctl enable k8-fan-controller.service
  systemctl start k8-fan-controller.service
  echo "Service status:"
  systemctl status k8-fan-controller.service --no-pager -l || true
else
  echo "systemctl not found. Skipping service enable/start."
fi

echo
echo "Installation complete!"
echo
# Determine service unit name for messaging
UNIT_NAME="k8-fan-controller.service"

# Install k8fc helper aliases/functions
cat > /etc/profile.d/k8fc.sh <<'BASH'
# K8 Fan Controller helper commands
k8fc() {
  cmd="$1"; shift || true
  unit="k8-fan-controller.service"
  case "$cmd" in
    help|"" )
      cat <<USAGE
K8 Fan Controller (k8fc) commands:
  k8fc reload                           - Reload daemon and restart service
  k8fc stop                             - Stop service and set fans to auto
  k8fc log                              - Tail service logs
  k8fc status                           - Show service status, key paths, and recent logs
USAGE
      ;;
    reload)
      systemctl daemon-reload
      systemctl restart "$unit"
      ;;
    stop)
      systemctl stop "$unit"
      # Restore automatic mode for all fans based on config
      python3 - <<'PY'
import os
import sys
try:
    import tomllib as toml
except Exception:
    import tomli as toml  # type: ignore

resolve = None
sys.path.insert(0, '/opt/k8-fan-controller/k8-fan-controller.pyz')
try:
    from k8_fan_controller.sysfs_utils import resolve_fan_paths  # type: ignore
    resolve = resolve_fan_paths
except Exception:
    resolve = None

cfg_path = '/etc/k8-fan-controller-config.toml'
try:
    with open(cfg_path, 'rb') as f:
        cfg = toml.load(f)
    for fan in cfg.get('fans', []):
        try:
            if resolve is not None:
                resolve(fan)
        except Exception:
            pass
        ep = fan.get('enable_path')
        if ep and os.path.exists(ep):
            try:
                with open(ep, 'w') as fw:
                    fw.write('2')
            except Exception:
                pass
except Exception:
    pass
print('Fans set to automatic where possible')
PY
      ;;
    log)
      journalctl -u "$unit" -f
      ;;
    status)
      echo "Service unit: $unit"
      echo "Config:       /etc/k8-fan-controller-config.toml"
      echo "Service file: /etc/systemd/system/$unit"
      echo "Install dir:  /opt/k8-fan-controller"
      echo "Bundle:       /opt/k8-fan-controller/k8-fan-controller.pyz"
      echo "Log file:     /var/log/k8-fan-controller.log"
      echo "Logrotate:    /etc/logrotate.d/k8-fan-controller"
      echo "Helper:       /etc/profile.d/k8fc.sh"
      echo
      echo "Systemd status:"
      systemctl is-enabled "$unit" 2>/dev/null || true
      systemctl is-active "$unit" 2>/dev/null || true
      systemctl status "$unit" --no-pager -l | sed -n '1,10p' || true
      echo
      echo "Recent logs:"
      journalctl -u "$unit" -n 20 --no-pager || true
      ;;
    *)
      echo "Usage: k8fc {help|reload|stop|log|status}"
      ;;
  esac
}
BASH
echo "Aliases installed. Use 'k8fc help' for available commands."
echo
echo
echo "The script ran SUCCESSFULLY!"
echo "Summary:"
echo "  - Installed packages: python3, lm-sensors, logrotate"
echo "  - Installed controller bundle to: /opt/k8-fan-controller/k8-fan-controller.pyz"
echo "  - Created systemd unit: /etc/systemd/system/$UNIT_NAME"
echo "  - Generated config: /etc/k8-fan-controller-config.toml"
echo "  - Log file: /var/log/k8-fan-controller.log"
echo "  - Logrotate rule: /etc/logrotate.d/k8-fan-controller"
echo "  - Shell helper: /etc/profile.d/k8fc.sh (command: 'k8fc')"
echo
echo "Next steps: open a new shell or 'source /etc/profile.d/k8fc.sh' to use 'k8fc'."
echo "Try: 'k8fc help' or 'k8fc status' to verify things are running."
echo
