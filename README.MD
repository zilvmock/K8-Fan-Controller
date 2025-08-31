### K8 Fan Controller

[![Status: Proof of Concept](https://img.shields.io/badge/status-proof_of_concept-blue?style=flat-square)](#)
[![Stability: Experimental](https://img.shields.io/badge/stability-experimental-orange?style=flat-square)](#)

Lightweight systemd service for the GMKtech K8 Plus mini PC that automatically adjusts fan speeds to keep temperatures safe while minimizing noise. It reads temperatures, maps them through a simple ramp, and writes PWM values to the kernel interfaces.

**Kernel/pwm requirement**: The K8 Plus needs an it87-compatible driver to expose PWM controls. See the [it87 kernel module](https://github.com/frankcrawford/it87).

#### How It Works
- Periodically reads temperature sensors via `lm-sensors` (`sensors -j`).
- Computes target speeds per role (CPU/case) from a configurable ramp.
- Writes PWM via sysfs and restores automatic mode on shutdown.

#### Install (Debian/Ubuntu)
Run this in a terminal:

```
git clone https://github.com/zilvmock/K8-Fan-Controller.git && \
  cd K8-Fan-Controller && \
  chmod +x install.sh uninstall.sh && \
  sudo ./install.sh
```

Then edit `/etc/k8-fan-controller-config.toml` and run `k8fc reload`.

Helpful commands: `k8fc status`, `k8fc log`, `k8fc reload`, `k8fc stop`.

#### Uninstall
`sudo ./uninstall.sh` removes the service, config, logs, helper, and restores fans to automatic.

For configuration details and advanced topics, see the repository wiki.
