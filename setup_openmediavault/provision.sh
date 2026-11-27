#!/usr/bin/env bash
# Run on the Proxmox node. Standard input contains a tar archive from install.py.
set -euo pipefail
vmid=$1 name=$2 storage=$3 iso_storage=$4 bridge=$5 memory=$6 cores=$7 boot_gb=$8 data_gb=$9 onboot=${10}
provision_tag=${11:-}

if [[ $(id -u) != 0 || $(uname -m) != x86_64 ]]; then
    echo 'Run as root on an x86-64 Proxmox node.' >&2
    exit 1
fi
for command in qm pvesh pvesm ip python3 tar sha512sum qemu-img genisoimage; do
    command -v "$command" >/dev/null
done
pvesh get /cluster/nextid --vmid "$vmid" >/dev/null
pvesh get /cluster/resources --type vm --output-format json | python3 -c '
import json, sys
if any((guest.get("name") or "").casefold() == sys.argv[1] for guest in json.load(sys.stdin)):
    sys.exit("Another Proxmox guest has this name.")
' "$name"
ip link show dev "$bridge" >/dev/null

check_storage() {
    pvesh get "/storage/$1" --output-format json | python3 -c '
import json, sys
storage = json.load(sys.stdin)
if storage.get("disable") or sys.argv[1] not in storage.get("content", "").split(","):
    sys.exit("The selected Proxmox storage must allow " + sys.argv[1] + ".")
' "$2"
}
check_storage "$storage" images
check_storage "$iso_storage" iso

umask 077
work=$(mktemp -d /var/tmp/setup-omv.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
tar -xf - -C "$work" -- checksum image.qcow2 user-data
printf 'instance-id: setup-omv-%s\nlocal-hostname: %s\n' "$vmid" "$name" > "$work/meta-data"

digest=$(cat "$work/checksum")
[[ $digest =~ ^[[:xdigit:]]{128}$ ]]
printf '%s  %s\n' "$digest" "$work/image.qcow2" | sha512sum --check --status
image_bytes=$(qemu-img info --output=json "$work/image.qcow2" | python3 -c '
import json, sys
image = json.load(sys.stdin)
if image["format"] != "qcow2" or image.get("backing-filename"):
    sys.exit("Expected a standalone Debian qcow2 image.")
print(image["virtual-size"])
')
if (( boot_gb * 1073741824 < image_bytes )); then
    echo 'The boot disk is too small for the Debian image.' >&2
    exit 1
fi

seed="$iso_storage:iso/setup-omv-$vmid-${work##*.}.iso"
seed_path=$(pvesm path "$seed")
mkdir -p -- "$(dirname "$seed_path")"
genisoimage -quiet -volid cidata -joliet -rock -output "$work/seed.iso" "$work/user-data" "$work/meta-data"
# The atomic create fails if the VMID was claimed while the image downloaded.
qm create "$vmid" --name "$name" --description "Created by setup_openmediavault" --tags "setup-omv${provision_tag:+;$provision_tag}" \
    --memory "$memory" --cores "$cores" --cpu x86-64-v2-AES --ostype l26 \
    --agent enabled=1 --scsihw virtio-scsi-single --net0 "virtio,bridge=$bridge,firewall=1" \
    --onboot 0 --startup order=1
install -m 0644 -- "$work/seed.iso" "$seed_path"
qm set "$vmid" --ide2 "$seed,media=cdrom" \
    --scsi0 "$storage:0,import-from=$work/image.qcow2,discard=on,iothread=1"
if (( boot_gb * 1073741824 > image_bytes )); then
    qm disk resize "$vmid" scsi0 "${boot_gb}G"
fi
if (( data_gb > 0 )); then
    qm set "$vmid" --scsi1 "$storage:$data_gb,serial=omvdata$vmid,discard=on,iothread=1"
fi
qm set "$vmid" --boot order=scsi0
qm start "$vmid"
qm set "$vmid" --onboot "$onboot"
