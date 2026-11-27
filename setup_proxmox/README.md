# Install Proxmox VE on a fresh machine

`install.py` builds an unattended **Proxmox VE 9.3-1 x86-64** ISO for one
machine. It verifies the stock ISO against Proxmox's published SHA-256,
generates an answer file, and embeds it and a first-boot script using the
official Proxmox auto-install assistant. The target can install from the
prepared media without an answer server or an existing Proxmox host.

## Describe the new machine

Copy [the example profile](profile.example.json) to a private directory. Set
the new node's FQDN, administrator email, static management IPv4 address,
gateway, DNS, Ethernet port MAC, and target disk ID. Pick an unused management
address on your LAN.

Identify the Ethernet port and disk from a Linux live environment.

```sh
ip -br link
lsblk -d -o NAME,SIZE,MODEL,SERIAL,WWN,TRAN
udevadm info --query=property --name=/dev/nvme0n1 | grep -E '^ID_(SERIAL(_SHORT)?|WWN(_WITH_EXTENSION)?)='
```

Replace the example device node with the drive you intend to erase. Use an
exact, unique `ID_SERIAL_SHORT`, `ID_SERIAL`, `ID_WWN`, or `ID_WWN_WITH_EXTENSION`
value in the profile. Confirm it matches exactly one target disk before
booting the installer. The automated install erases that disk and uses ext4
with Proxmox's standard LVM storage layout. The installer configures the
selected Ethernet port as the uplink for `vmbr0`.

The example uses English keyboard layout, China, and `Asia/Shanghai`.
`repository` selects the enterprise repository or the home-lab
`no-subscription` repository. The latter disables the stock enterprise PVE
and Ceph entries. First boot enables the TRIM timer and checks that the
management services, bridge, and storage are available. Set `"upgrade": true`
to run a package upgrade at first boot using the target's network.

## Build and boot

The build workstation needs Python 3.8+, Docker, curl, OpenSSH, and OpenSSL
with `openssl passwd -6` support. Docker runs the official amd64 assistant
on Linux or macOS, including Apple Silicon with amd64 emulation. On Linux
with the current assistant already installed, add `--native`. Allow space
for the stock ISO, prepared ISO, and a temporary ISO copy.

```sh
cp setup_proxmox/profile.example.json "$HOME/proxmox-profile.json"
# Edit the profile with the new machine's settings before building the ISO.
python3 setup_proxmox/install.py \
  --profile "$HOME/proxmox-profile.json" \
  --output "$HOME/proxmox-unattended.iso"
```

The script downloads the pinned stock ISO to `~/.cache/proxmox-iso`. Use
`--stock-iso` to supply a local copy. The root password prompt is private.
For unattended ISO builds, pass `--password-file` with a private one-line
file. The installer includes the first available standard public key from
`~/.ssh`. Use `--ssh-public-key` to choose another. Keep the generated ISO
private because it contains the root password hash.

Check the adjacent `.iso.sha256` file before writing the ISO to a USB stick
with a raw image writer, or mount the ISO as virtual media in a management
controller. Boot the intended node from this media. The automated entry
starts after the boot menu countdown. Set the installed disk ahead of the
installer media for subsequent boots.

Open `https://<management-address>:8006/` and sign in as `root@pam`. First
boot reports to the systemd journal. Run these checks from the node.

```sh
journalctl -u proxmox-first-boot-multi-user.service -b
cat /var/lib/setup-proxmox/first-boot-complete
pvesm status
```

Proxmox documents the [ISO and checksum](https://download.proxmox.com/iso/),
[automated installation](https://pve.proxmox.com/wiki/Automated_Installation),
and [package repositories](https://pve.proxmox.com/wiki/Package_Repositories).

## Create the existing VM profiles on a new node

After Proxmox is running, use `create_vms.py` from macOS or Linux with
Python 3.9+, OpenSSH, curl, and root SSH access to the target node. The
defaults in [vm_profiles.json](vm_profiles.json) reproduce the names and
virtual hardware of the existing VMs.

| VM ID | Name | Boot or installation media |
| --- | --- | --- |
| 100 | `ubuntu` | Ubuntu 20.04.3 desktop ISO |
| 101 | `windows` | Windows 10 22H2 and VirtIO 0.1.240 ISOs |
| 102 | `omv` | OpenMediaVault 7.4.17 ISO |
| 103 | `mac` | macOS Sonoma 14.1.1 and OpenCore v21 images |
| 104 | `daily-ubuntu` | Ubuntu 20.04.3 desktop ISO |
| 105 | `ha` | HAOS 18.4 preinstalled boot disk |

Preview all six profiles, or pass names to select specific guests. Use
`--apply` to create them.

```sh
python3 setup_proxmox/create_vms.py
python3 setup_proxmox/create_vms.py --proxmox new-pve --apply
python3 setup_proxmox/create_vms.py ha --vmid 106 --name ha-new --apply
```

A VM ID or name already in use aborts the request before media transfers.
The script leaves new VMs stopped and preserves their configured host
autostart policy. Use `--no-onboot` to disable autostart. When selecting one
profile, `--vmid`, `--name`, `--cores`, `--memory` (MiB) and `--disk-gb`
override its defaults. The storage and bridge defaults are `local-lvm`,
`local` for ISOs, and `vmbr0`. Change them with `--storage`,
`--iso-storage` and `--bridge` on nodes with a different layout. Size the
target node for the selected profiles, especially `ubuntu` and `windows`.

The script verifies every image against its pinned SHA-256. It reuses
matching ISOs already on Proxmox, searches `--image-dir` (repeatable) and
the `/Volumes/DeepLearn/OS` and `/Volumes/omv/OS` trees, then downloads
available exact releases into `~/.cache/setup-proxmox/vm-media`. Supply
your matching Windows, VirtIO, macOS and OpenCore images if the target and
the local image directories lack them. An ISO already present with
different contents stops the creation. This workflow provisions new disks
and attaches the installer media, or imports the clean HAOS image. For
unattended guest configuration, see the
[Home Assistant](../setup_homeassistant/README.md) and
[OpenMediaVault 8](../setup_openmediavault/README.md) installers.

Proxmox generates new MAC addresses, SMBIOS UUIDs and VM generation IDs
for the new guests. Keep the private `vm-hardware.json` file at
`~/.config/setup-proxmox/vm-hardware.json`, with mode 0600, and copy it
privately to another workstation when needed. Use `--hardware-file` to
specify another path. The `mac` profile loads its recorded QEMU arguments
from `mac.args`. The optional `--with-passthrough` flag loads the original
`hostpci*`, `usb*`, and `omv.sata1` values from the per-profile objects.
Review those host-specific addresses on the new node before using them.
The OMV data partition must be unmounted on the host and unattached to
other guests.

If Proxmox rejects an option after creating a guest, inspect that VM ID on
the node. Successful guests from the batch are retained for use.
