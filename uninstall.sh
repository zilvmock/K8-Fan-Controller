#!/usr/bin/env bash
# Smart Fan Controller for GMKtech K8 Plus Mini PC uninstall script

set -euo pipefail

echo "Uninstalling Smart Fan Controller for GMKtech K8 Plus..."

# Require root
if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "This script must be run as root (use sudo)"
  exit 1
fi

read -r -p "This will stop services, delete files, and set fans to automatic. Continue? [y/N]: " CONFIRM
case "${CONFIRM,,}" in
  y|yes) ;;
  *) echo "Aborted."; exit 0;;
esac

# Try to detect unit name(s)
UNIT_A="k8-fan-controller.service"

stop_disable_unit() {
  local unit="$1"
  if systemctl list-unit-files | grep -q "^$unit"; then
    echo "Stopping and disabling $unit..."
    systemctl stop "$unit" 2>/dev/null || true
    systemctl disable "$unit" 2>/dev/null || true
  else
    # Still try to stop if running by name
    systemctl stop "$unit" 2>/dev/null || true
  fi
}

# Stop and disable possible units
if command -v systemctl >/dev/null 2>&1; then
  stop_disable_unit "$UNIT_A"
fi

echo "Setting fans to automatic (where supported)..."
python3 - <<'PY'
import os
try:
    import tomllib as toml
except Exception:
    import tomli as toml  # type: ignore
paths = ['/etc/k8-fan-controller-config.toml']
try:
    for cfg_path in paths:
        if os.path.exists(cfg_path):
            with open(cfg_path,'rb') as f:
                cfg = toml.load(f)
            for fan in cfg.get('fans', []):
                ep = fan.get('enable_path')
                if ep and os.path.exists(ep):
                    try:
                        with open(ep,'w') as fw:
                            fw.write('2')
                    except Exception:
                        pass
except Exception:
    pass
PY

# Fallback: sweep sysfs for any pwm*_enable files and set to auto
for path in /sys/class/hwmon/hwmon*/pwm*_enable; do
  [ -e "$path" ] || continue
  if [ -w "$path" ]; then echo 2 > "$path" 2>/dev/null || true; fi
done

echo "Removing installed files and logs..."
rm -f /etc/systemd/system/k8-fan-controller.service || true
rm -f /etc/logrotate.d/k8-fan-controller || true
rm -f /etc/k8-fan-controller-config.toml || true
rm -f /var/log/k8-fan-controller.log || true
rm -f /var/log/k8-fan-controller.log.* || true
rm -rf /opt/k8-fan-controller || true
rm -f /etc/profile.d/k8fc.sh || true

if command -v systemctl >/dev/null 2>&1; then
  echo "Reloading systemd daemon..."
  systemctl daemon-reload || true
  systemctl reset-failed k8-fan-controller.service 2>/dev/null || true
fi

# Clean up temporary installer artifacts
rm -f /tmp/fans_map.txt 2>/dev/null || true

# Offer to remove packages installed by installer (keep python3)
if command -v apt-get >/dev/null 2>&1; then
  echo
  echo "Optional: remove packages added by installer (lm-sensors, logrotate, python3-tomli)."
  read -r -p "Remove lm-sensors, logrotate, and python3-tomli now? [y/N]: " REMOVE_PKGS
  case "${REMOVE_PKGS,,}" in
    y|yes)
      export DEBIAN_FRONTEND=noninteractive
      apt-get remove -y --purge lm-sensors logrotate python3-tomli || true
      apt-get autoremove -y || true
      ;;
    *) echo "Keeping lm-sensors, logrotate, and python3-tomli installed.";;
  esac
fi

echo
echo "Uninstall complete. Summary:"
echo "  - Services stopped/disabled (if present): $UNIT_A"
echo "  - Fans set to automatic where possible"
echo "  - Removed: /opt/k8-fan-controller (bundle), /etc/k8-fan-controller-config.toml, service units, logrotate entry, log file, k8fc helper"
echo "  - Packages removed (if selected): lm-sensors, logrotate, python3-tomli"

exit 0
