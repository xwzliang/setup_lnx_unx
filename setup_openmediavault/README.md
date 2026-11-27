# Install OpenMediaVault on Proxmox

Run the installer from macOS or Linux with Python 3.9+, OpenSSH, and a
public key for this workstation. The Proxmox SSH alias must resolve to root
on the target x86-64 node. The workstation needs internet access for an
image download. The guest needs internet access for packages and DHCP
on its bridge. Use a trusted LAN during first boot.

```sh
python3 setup_openmediavault/install.py install --vmid 106 --name omv-new
```

Choose an unused VM ID and a distinct hostname of up to 15 characters
for Samba. The installer checks both VM and container IDs, reuses a verified
Debian 13 cloud image or downloads it if needed, verifies SHA-512 again
on Proxmox, and installs the supported OpenMediaVault 8 release with the
[OMV-Extras installer](https://github.com/OpenMediaVault-Plugin-Developers/installScript).

The installer uses `/Volumes/DeepLearn/OS/omv` as its image cache when
available, otherwise `~/.cache/setup-openmediavault/images`. Set
`--image-dir` to use a different local directory. It retains the image and
its SHA-512 checksum for later runs. The existing
[OpenMediaVault 7 ISO](https://docs.openmediavault.org/en/stable/releases.html)
can be kept alongside the cloud image for recovery.

Defaults are `pve`, `local-lvm` for VM disks, `local` for the cloud-init
ISO, `vmbr0`, 4 cores, 16 GiB RAM, and a 32 GiB boot disk. Use
`--storage`, `--iso-storage`, `--bridge`, `--cores`, `--memory`, or
`--boot-gb` to override them. DHCP assigns the IP address. Proxmox starts
the VM at host boot unless you pass `--no-onboot`. The default guest
time zone is `Asia/Singapore`. Override it with `--timezone`.

## Data disk and Samba

The default profile creates a separate 32 GiB virtual data disk. The guest
formats only the blank disk with the serial and size assigned by the
installer, mounts it as ext4 through OMV, and makes it the first member of
the `omv` mergerfs pool. The pool starts with the same create policy
(`epmfs`), minimum free space (4 GiB), and file cache setting as the original
NAS. OMV exports a writable SMB2+ share named `omv` for the new local user.
`--data-gb` changes the disk size. Use `--data-gb 0` to omit the data disk
and share.

The installer applies the existing
[Samba memory fix](../packages/samba/scripts/linux/setup_omv_smb_aio.py) and
verifies the generated share has `aio write size = 0`. It also checks that
Samba accepts an authenticated connection to the share.

## Reuse the filesystem on sata1

For an installer-created VM provisioned with `--data-gb 0`, attach the
physical partition to `sata1` by its PARTUUID. Run this after the VM has
started with the disk attached.

```sh
python3 setup_openmediavault/install.py configure --vmid 102 --reuse-sata1
```

The installer reads the UUID of the existing ext4 filesystem from the
attached partition, checks that it is clean, and persists the mount in
OMV. It registers existing directories as Samba shares while preserving
their contents, ownership, modes, and ACLs. Each share uses the installer
SMB account and retains the disk's existing Unix permissions. The SMB
credentials are added to the installation file when needed.

By default, the share named `omv` uses the existing `omv` directory.
Pass `--existing-shares` with the saved layout to use other share names
or paths. Paths are relative to the filesystem root. Use `"."` explicitly
if a share covered the whole filesystem. The optional `readonly` and
`browseable` flags default to `false` and `true`.

```sh
python3 setup_openmediavault/install.py configure --vmid 102 --reuse-sata1 \
  --existing-shares '[{"name":"omv","path":"."},{"name":"Media","path":"Media","readonly":true}]'
```

The Proxmox first-boot job runs this mode automatically when it attaches
the saved physical partition. Set `vm_setup.omv_shares` in the private
Proxmox machine profile to include the same layout in the installer ISO.
Missing directories and conflicting mounts or shares cause setup to stop.

## Access and reruns

The installer prints the DHCP address and saves the generated web and SMB
passwords in a local file with mode 0600. The default file is
`~/.local/state/setup-openmediavault/<proxmox-alias>-<vmid>.txt`. Use
`--credentials-file` to choose another path. The web user is `admin`.
The SSH and SMB user is `omvadmin` by default. SSH uses the local public
key or the key passed with `--ssh-public-key`. Pass `--user` to set a
different account name. Password and root SSH logins are disabled.

If the installer was interrupted after the VM started, verify that first
boot completed in the Proxmox console or read
`/var/log/cloud-init-output.log` in the guest, then run:

```sh
python3 setup_openmediavault/install.py configure --vmid 106
```

`configure` accepts the same `--proxmox` and `--credentials-file` options
and checks the installer identity before making guest changes. After setup
completes, rerunning it verifies the services and retrieves the original
credentials. If you rotate a password, use the current credentials instead
of the installation file. If a package download failed during first boot,
rerun `/usr/local/sbin/setup-omv-bootstrap` as root on the guest after
fixing connectivity, then run `configure` again. The small
`setup-omv-*.iso` on the ISO storage
contains the cloud-init seed and public key. If you later remove the VM,
you can remove its seed ISO separately.
