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
