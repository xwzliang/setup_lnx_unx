# Install ImmortalWrt from scratch

`install_immortalwrt.py` prepares an x86-64 router from official ImmortalWrt
firmware. It initializes the root password and, when available, copies an SSH
public key from the computer running the installer. First boot configures the
hostname, LAN address, and time zone. It needs no existing router or backup.

The defaults are ImmortalWrt 25.12.2, UEFI, LAN `192.168.1.1/24`, LAN DHCP
enabled, and `Asia/Shanghai`. The firmware uses DHCP on WAN when a second
Ethernet port is available. Use `--firmware bios` for a legacy BIOS machine,
`--lan` to pick a different network, and `--no-dhcp` to disable LAN DHCP and
router advertisements. The built-in packages include LuCI. Use
`--password-file` for unattended setup, or enter the root password at the
private prompt. Use `--ssh-public-key` to select a different public key.

Run these commands from the repository root with Python 3.9+ and OpenSSH.
For password setup, use OpenSSL with `openssl passwd -6` support. Image
preparation runs on Linux with `sfdisk` (util-linux/fdisk) and e2fsprogs. On
macOS, use a Linux SSH builder. The `proxmox` command uses the Proxmox host as
its builder by default.

## Download the official image

```sh
python3 setup_openwrt/install_immortalwrt.py download \
  --image-dir /Volumes/omv/OS/openwrt/immortalwrt
```

The command verifies SHA-256 and reuses a matching download. The installer
uses that folder when mounted and `~/.cache/immortalwrt` otherwise.
`--release` selects another stable release using its published checksum.
Add `--firmware bios` to download the BIOS image.

## Install with your saved router settings and OpenClash

Create a private profile from an existing router configuration archive. The
installer uses the selected settings and OpenClash files from the archive
and builds a fresh ImmortalWrt 25.12.2 image with OpenClash 0.48.002. The
archive can be elsewhere on disk or copied from your offline backups.

```sh
python3 setup_openwrt/install_immortalwrt.py profile \
  --from-backup "$HOME/router-backup.tar.gz" \
  --output "$HOME/router-profile.tar.gz"
```

The profile includes the saved LAN and WAN, DHCP reservations, WireGuard,
system settings, firewall rules, and OpenClash subscriptions, rules and
Mihomo core. The source archive needs those UCI configs, the active OpenClash
YAML, and `/etc/openclash/core/clash_meta`. A saved local subscription
converter on port 15051 is initialized from its pinned container image and
available to OpenClash on the new router's loopback interface.

Use an x86-64 Linux builder with Docker and internet access to the package
feeds. Use `--builder` from macOS, or run locally on such a Linux host.
Pass `--router-profile` to either `prepare` or `proxmox`:

```sh
python3 setup_openwrt/install_immortalwrt.py prepare \
  --builder daily --router-profile "$HOME/router-profile.tar.gz" \
  --output "$HOME/immortalwrt-router.img"

python3 setup_openwrt/install_immortalwrt.py proxmox \
  --builder daily --router-profile "$HOME/router-profile.tar.gz" \
  --vmid 108 --isolated --lan 192.168.82.1/24 --no-dhcp --web-port 8018
```

These commands use the saved hostname and LAN settings unless you override
them. An isolated VM uses its own DHCP WAN and leaves WireGuard inactive.
For a router taking over an existing LAN, assign its LAN and WAN Ethernet
ports according to the saved interface configuration and disconnect the old
router before reusing its LAN address and DHCP server.

Keep the profile and any configured images private. They contain subscription
URLs and can contain PPPoE and WireGuard credentials. Each install takes a new
root password and generates its own SSH host keys. The image uses firewall4
and OpenClash's nftables integration. Set up any additional router services
separately.

## Install on a new Proxmox VM

Use an unused VM ID. Pick a LAN bridge that serves the new router's clients.
If a DHCP server already serves that network, choose a different bridge or
use `--no-dhcp` and a free host address. `--wan-bridge` is optional and must
be distinct from the LAN bridge.

```sh
python3 setup_openwrt/install_immortalwrt.py proxmox \
  --vmid 108 --proxmox pve --lan-bridge vmbr1 --wan-bridge vmbr0
```

The command creates and starts the VM and prints its LuCI address. Open LuCI
and sign in as `root` with the password you supplied. The default firmware
disk has a 300 MiB root partition.

For a test with an isolated QEMU network, use `--isolated` in place of
`--lan-bridge` and omit `--wan-bridge`. Optional `--ssh-port` and
`--web-port` forward connections from the Proxmox host's loopback interface.
Reach LuCI through an SSH tunnel, for example
`ssh -N -L 8080:127.0.0.1:8017 pve` if you used `--web-port 8017`.

## Prepare and flash a bootable USB stick

```sh
python3 setup_openwrt/install_immortalwrt.py prepare \
  --builder pve --output "$HOME/immortalwrt-usb.img"
```

On Linux you can omit `--builder` if the image tools are installed locally.
This command writes a raw image and its `.img.sha256` checksum. Keep the raw
image private because it contains a root password hash.

Identify the whole USB disk using `diskutil list external physical` on macOS
or `lsblk -o PATH,MODEL,SERIAL,SIZE,TRAN,RM,MOUNTPOINTS` on Linux. The
`--erase` argument identifies the disk whose partition table and data will
be overwritten. The writer checks that it is a removable USB device and
verifies the written bytes. macOS unmounts it automatically. On Linux,
unmount its partitions before running the command.

```sh
sudo python3 setup_openwrt/install_immortalwrt.py usb \
  --image "$HOME/immortalwrt-usb.img" --erase /dev/disk5
```

Replace `/dev/disk5` with the actual whole USB device. Choose the stick in
the target machine's boot menu. The system runs from the stick. For UEFI
boot, disable Secure Boot. Connect the LAN port to a test client first and
reach LuCI at the address supplied to `prepare`.
