#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# restore_gpu_fan.sh
#
# Description:
#   Restores default NVIDIA GPU fan control and removes configurations
#   created by setup_gpu_fan.sh.
#
# Actions:
#   1. Stops and disables nvidia-fan-control.service
#   2. Removes /etc/systemd/system/nvidia-fan-control.service
#   3. Removes /usr/local/bin/set-nvidia-fan-speed.sh
#   4. Removes /etc/X11/xorg.conf and /etc/X11/xorg.conf.backup (restoring default Xorg auto-config)
#   5. Reloads systemd daemon
#
# Usage:
#   sudo ./restore_gpu_fan.sh [OPTIONS]
#
# Options:
#   -h, --help         Show this help message and exit
# ==============================================================================

show_help() {
    cat << 'HELP_EOF'
Usage:
  sudo ./restore_gpu_fan.sh [OPTIONS]

Description:
  Restores the system to its default state prior to running setup_gpu_fan.sh.
  Stops and removes the nvidia-fan-control systemd service, removes the helper
  script in /usr/local/bin, and cleans up the generated /etc/X11/xorg.conf.

Options:
  -h, --help         Display this help message and exit

Examples:
  sudo ./restore_gpu_fan.sh
HELP_EOF
}

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use -h or --help for usage information." >&2
            exit 1
            ;;
    esac
done

echo "==> Restoring default NVIDIA GPU fan configuration..."

# 1. Stop and disable systemd service if present
if systemctl list-unit-files | grep -q "nvidia-fan-control.service"; then
    echo "==> Stopping and disabling nvidia-fan-control.service..."
    sudo systemctl stop nvidia-fan-control.service 2>/dev/null || true
    sudo systemctl disable nvidia-fan-control.service 2>/dev/null || true
fi

# 2. Remove systemd service file and helper script
echo "==> Removing service files and helper scripts..."
sudo rm -f /etc/systemd/system/nvidia-fan-control.service
sudo rm -f /usr/local/bin/set-nvidia-fan-speed.sh
sudo systemctl daemon-reload

# 3. Remove generated X11 configuration to restore default driver auto-detection
if [[ -f "/etc/X11/xorg.conf" ]]; then
    echo "==> Removing /etc/X11/xorg.conf..."
    sudo rm -f /etc/X11/xorg.conf
fi
if [[ -f "/etc/X11/xorg.conf.backup" ]]; then
    sudo rm -f /etc/X11/xorg.conf.backup
fi

# 4. If an isolated Xorg :99 is running, stop it
if pgrep -f "Xorg :99" &>/dev/null; then
    echo "==> Stopping headless Xorg :99 instance..."
    sudo pkill -f "Xorg :99" 2>/dev/null || true
fi

echo "==> Restoration complete! System reverted to stock defaults."
