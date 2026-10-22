#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# setup_gpu_fan.sh
#
# Description:
#   Sets a static minimum fan speed for NVIDIA GPUs on Linux (desktop or headless).
#   Prevents GPU fan cycling (0 RPM to 100% burst) when idling with loaded models.
#
# Usage:
#   sudo ./setup_gpu_fan.sh [OPTIONS] [SPEED_PERCENT]
#
# Arguments:
#   SPEED_PERCENT      Target fan speed in % (30-100, default: 35)
#
# Options:
#   -h, --help         Show this help message and exit
#
# Examples:
#   sudo ./setup_gpu_fan.sh         # Installs and sets fan speed to default 35%
#   sudo ./setup_gpu_fan.sh 40      # Installs and sets fan speed to 40%
#
# Runtime Management:
#   Once installed, you can adjust fan speed on the fly at any time without reinstalling:
#     sudo /usr/local/bin/set-nvidia-fan-speed.sh <SPEED>
#
#   Check service status:
#     systemctl status nvidia-fan-control.service
# ==============================================================================

show_help() {
    cat << 'HELP_EOF'
Usage:
  sudo ./setup_gpu_fan.sh [OPTIONS] [SPEED_PERCENT]

Description:
  Configures X11 Coolbits (cool-bits=28) and installs a persistent systemd service
  (nvidia-fan-control.service) to maintain a static minimum fan speed for NVIDIA GPUs.
  Works in both desktop (active X11 session) and headless server environments.

Arguments:
  SPEED_PERCENT      Target fan speed percentage between 30 and 100 (Default: 35)

Options:
  -h, --help         Display this help message and exit

Examples:
  sudo ./setup_gpu_fan.sh         # Sets static speed to 35% (recommended)
  sudo ./setup_gpu_fan.sh 40      # Sets static speed to 40%

Post-Install Commands:
  Change fan speed on the fly:
    sudo /usr/local/bin/set-nvidia-fan-speed.sh <SPEED>

  Check background service status:
    systemctl status nvidia-fan-control.service

  View GPU temperature & fan telemetry:
    nvidia-smi --query-gpu=temperature.gpu,fan.speed,power.draw --format=csv
HELP_EOF
}

# Parse options
TARGET_FAN_SPEED="35"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        [0-9]*)
            TARGET_FAN_SPEED="$1"
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use -h or --help for usage information." >&2
            exit 1
            ;;
    esac
done

if (( TARGET_FAN_SPEED < 30 || TARGET_FAN_SPEED > 100 )); then
    echo "ERROR: Fan speed must be between 30 and 100 (got: ${TARGET_FAN_SPEED}%)." >&2
    exit 1
fi

echo "==> Configuring NVIDIA GPU minimum fan speed: ${TARGET_FAN_SPEED}%"

# 1. Ensure nvidia-smi and nvidia-settings exist
if ! command -v nvidia-smi &>/dev/null; then
    echo "ERROR: nvidia-smi not found. Please install NVIDIA drivers first." >&2
    exit 1
fi

if ! command -v nvidia-settings &>/dev/null; then
    echo "==> Installing nvidia-settings..."
    sudo apt-get update -qq && sudo apt-get install -y nvidia-settings
fi

# 2. Configure X11 Coolbits for manual fan control
echo "==> Generating/updating /etc/X11/xorg.conf with Coolbits=28..."
sudo mkdir -p /etc/X11
if command -v nvidia-xconfig &>/dev/null; then
    sudo nvidia-xconfig --cool-bits=28 --allow-empty-initial-configuration --no-probe-all-gpus 2>/dev/null || true
fi

# Ensure ModulePath includes Ubuntu multiarch driver directory if nvidia_drv.so is there
NVIDIA_XORG_DIR=$(dirname "$(find /usr/lib -name nvidia_drv.so 2>/dev/null | head -n 1)")
if [[ -n "${NVIDIA_XORG_DIR}" ]] && grep -q 'Section "Files"' /etc/X11/xorg.conf 2>/dev/null; then
    if ! grep -q "${NVIDIA_XORG_DIR}" /etc/X11/xorg.conf; then
        sudo sed -i "/Section \"Files\"/a \    ModulePath \"${NVIDIA_XORG_DIR}\"\n    ModulePath \"/usr/lib/xorg/modules\"" /etc/X11/xorg.conf
    fi
fi

# 3. Create the fan control helper script in /usr/local/bin
echo "==> Creating /usr/local/bin/set-nvidia-fan-speed.sh..."
sudo tee /usr/local/bin/set-nvidia-fan-speed.sh > /dev/null << 'SCRIPT_EOF'
#!/usr/bin/env bash
SPEED="${1:-35}"

# Detect running Xorg display or launch dedicated headless Xorg
DISP=""
AUTH=""

# Check if an existing X server with NVIDIA driver is running
for d in :0 :1; do
    if [[ -S "/tmp/.X11-unix/X${d#:}" ]]; then
        for a in /run/user/*/gdm/Xauthority /run/user/*/.mutter-Xwaylandauth* /var/run/lightdm/root/$d /root/.Xauthority; do
            if [[ -f "$a" ]] && DISPLAY="$d" XAUTHORITY="$a" nvidia-settings -q fans &>/dev/null; then
                DISP="$d"
                AUTH="$a"
                break 2
            fi
        done
        if DISPLAY="$d" nvidia-settings -q fans &>/dev/null; then
            DISP="$d"
            break
        fi
    fi
done

# If no active X server exposes NVIDIA fan control, start a lightweight headless Xorg instance
if [[ -z "$DISP" ]]; then
    DISP=":99"
    if ! [[ -S "/tmp/.X11-unix/X99" ]]; then
        Xorg :99 -config /etc/X11/xorg.conf -noreset -sharevts +extension GLX +extension RANDR +extension RENDER &>/dev/null &
        sleep 2
    fi
fi

# Query number of GPUs
NUM_GPUS=$(nvidia-smi --query-gpu=count --format=csv,noheader | head -n 1)

for ((g=0; g<NUM_GPUS; g++)); do
    echo "Setting GPU $g fan control to manual and target speed to ${SPEED}%..."
    if [[ -n "$AUTH" ]]; then
        DISPLAY="$DISP" XAUTHORITY="$AUTH" nvidia-settings -a "[gpu:${g}]/GPUFanControlState=1" &>/dev/null || true
        for f in $(DISPLAY="$DISP" XAUTHORITY="$AUTH" nvidia-settings -q fans 2>/dev/null | grep -o '\[fan:[0-9]*\]' | sort -u); do
            DISPLAY="$DISP" XAUTHORITY="$AUTH" nvidia-settings -a "${f}/GPUTargetFanSpeed=${SPEED}" &>/dev/null || true
        done
    else
        DISPLAY="$DISP" nvidia-settings -a "[gpu:${g}]/GPUFanControlState=1" &>/dev/null || true
        for f in $(DISPLAY="$DISP" nvidia-settings -q fans 2>/dev/null | grep -o '\[fan:[0-9]*\]' | sort -u); do
            DISPLAY="$DISP" nvidia-settings -a "${f}/GPUTargetFanSpeed=${SPEED}" &>/dev/null || true
        done
    fi
done

echo "Fan speed command dispatched on display ${DISP}."
SCRIPT_EOF

sudo chmod +x /usr/local/bin/set-nvidia-fan-speed.sh

# 4. Create a systemd service to persist across boots
echo "==> Creating /etc/systemd/system/nvidia-fan-control.service..."
sudo tee /etc/systemd/system/nvidia-fan-control.service > /dev/null << SERVICE_EOF
[Unit]
Description=Set NVIDIA GPU Static Minimum Fan Speed
After=multi-user.target graphical.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/set-nvidia-fan-speed.sh ${TARGET_FAN_SPEED}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# 5. Enable and start the service
echo "==> Enabling and starting nvidia-fan-control.service..."
sudo systemctl daemon-reload
sudo systemctl enable nvidia-fan-control.service
sudo systemctl restart nvidia-fan-control.service

echo "==> Done! NVIDIA GPU fan speed set to ${TARGET_FAN_SPEED}%."
