#!/usr/bin/env bash
set -euo pipefail
umask 077

vmid=$1 name=$2 storage=$3 firmware=$4 digest=$5
shift 5

# Check the cluster inventory, including containers and guests on other nodes.
pvesh get /cluster/resources --type vm --output-format json |
    python3 -c 'import json, sys
if any(entry["vmid"] == int(sys.argv[1]) for entry in json.load(sys.stdin)):
    sys.exit("VM ID is already in use: " + sys.argv[1])' "$vmid"

stage=$(mktemp -d /var/tmp/immortalwrt.XXXXXXXX)
trap 'rm -rf -- "$stage"' EXIT
image=$stage/firmware.img
cat > "$image"
printf '%s  %s\n' "$digest" "$image" | sha256sum --check --status

if [[ $firmware == uefi ]]; then
    boot=(--bios ovmf --efidisk0 "$storage:0,efitype=4m,pre-enrolled-keys=0")
else
    boot=(--bios seabios)
fi
qm create "$vmid" --name "$name" --memory 1024 --cores 2 --ostype l26 \
    --scsihw virtio-scsi-pci --scsi0 "$storage:0,import-from=$image" \
    --boot order=scsi0 --serial0 socket "${boot[@]}" "$@"
qm start "$vmid"
