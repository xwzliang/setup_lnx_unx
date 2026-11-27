#!/usr/bin/env bash
# Run on the Proxmox node. install.mjs supplies the VM settings over SSH.
set -euo pipefail

vmid=$1 name=$2 storage=$3 bridge=$4 memory=$5 cores=$6 disk_gb=$7 version=${8:-}

if [[ ! $disk_gb =~ ^[0-9]{1,5}$ ]]; then
    echo 'Expected a numeric disk size in GiB.' >&2
    exit 1
fi

if [[ $(id -u) != 0 || $(uname -m) != x86_64 ]]; then
    echo 'Provisioning requires root on an x86-64 Proxmox node.' >&2
    exit 1
fi
for command in qm pvesh ip python3 curl sha256sum xz qemu-img; do
    command -v "$command" >/dev/null
done

# The cluster checks both QEMU and LXC IDs. qm create also checks for races.
pvesh get /cluster/nextid --vmid "$vmid" >/dev/null
ip link show dev "$bridge" >/dev/null
pvesh get "/storage/$storage" --output-format json | python3 -c '
import json, sys
storage = json.load(sys.stdin)
if storage.get("disable") or "images" not in storage.get("content", "").split(","):
    sys.exit("The selected Proxmox storage must allow VM disk images.")
'

if [[ -z $version ]]; then
    version=$(curl -fsSL --retry 2 --max-time 30 https://version.home-assistant.io/stable.json | \
        python3 -c 'import json, sys; print(json.load(sys.stdin)["hassos"]["ova"])')
fi
if [[ ! $version =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]]; then
    echo 'Expected a stable Home Assistant OS version such as 18.4.' >&2
    exit 1
fi

work=$(mktemp -d /var/tmp/haos-install.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
asset="haos_ova-$version.qcow2.xz"
repo='home-assistant/operating-system'
digest=$(curl -fsSL --retry 2 --max-time 30 "https://api.github.com/repos/$repo/releases/tags/$version" | \
    python3 -c '
import json, re, sys
assets = json.load(sys.stdin)["assets"]
digest = next((item.get("digest") for item in assets if item["name"] == sys.argv[1]), None)
if not digest or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    sys.exit("The release lacks the PC VM image or its SHA-256 digest.")
print(digest.removeprefix("sha256:"))
' "$asset")

echo "Downloading Home Assistant OS $version on Proxmox." >&2
curl -fsSL --retry 2 --max-time 900 -o "$work/$asset" \
    "https://github.com/$repo/releases/download/$version/$asset"
if ! printf '%s  %s\n' "$digest" "$work/$asset" | sha256sum --check --status; then
    echo 'The HAOS image failed its SHA-256 check.' >&2
    exit 1
fi
image="$work/haos.qcow2"
xz -dc -- "$work/$asset" > "$image"
image_size=$(qemu-img info --output=json "$image" | python3 -c '
import json, sys
info = json.load(sys.stdin)
if info["format"] != "qcow2" or "backing-filename" in info:
    sys.exit("Expected a standalone qcow2 image.")
print(info["virtual-size"])
')
disk_size=$((10#$disk_gb * 1024 * 1024 * 1024))
if (( disk_size < image_size )); then
    echo 'The requested VM disk is smaller than the official image.' >&2
    exit 1
fi

qm create "$vmid" --name "$name" --memory "$memory" --cores "$cores" \
    --ostype l26 --machine q35 --bios ovmf --agent enabled=1 \
    --scsihw virtio-scsi-single --net0 "virtio,bridge=$bridge,firewall=1" \
    --efidisk0 "$storage:0,efitype=4m,pre-enrolled-keys=0" \
    --scsi0 "$storage:0,import-from=$image,discard=on,iothread=1" \
    --boot order=scsi0
if (( disk_size > image_size )); then
    qm disk resize "$vmid" scsi0 "${disk_gb}G"
fi
qm start "$vmid"
