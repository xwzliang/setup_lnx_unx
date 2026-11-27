# Set up Home Assistant OS

## Clean install on Proxmox

Run this from a Mac or Linux workstation with Node.js 22.4 or newer, SSH access
as root on the x86-64 Proxmox node, and access to its guest network. The installer
uses `pve`, `local-lvm`, `vmbr0`, 2 vCPUs, 4 GiB RAM, and a 32 GiB boot disk by
default. Pick an unused VM ID. Proxmox checks it cluster-wide before the download.
The guest needs DHCP on its primary interface and internet access to initialize
Home Assistant and install apps.

```sh
node setup_homeassistant/install.mjs install --vmid 106 --name haos-new
```

The installer downloads the current stable **PC VM** image on the Proxmox node,
verifies its published SHA-256 digest, creates and starts the UEFI guest, and
prints its Home Assistant URL. It prompts privately for the new owner password
before provisioning. Use `--owner-name` and `--username` to customize the owner,
or `--password-file` to run unattended with an owner password in a private file.
Run `--help` for storage, bridge, resource, release, and timeout overrides.
Use a trusted LAN for first boot and account creation over HTTP.

The clean profile completes normal Home Assistant onboarding, adds the MCP
Server integration, and installs Terminal & SSH, Advanced SSH & Web Terminal,
and Node-RED. It starts fresh Node-RED through Home Assistant ingress and
leaves direct port 1880 disabled. Home Assistant 2026.11+ includes Marketplace.
Enter the SwitchBot Cloud credentials and pair the mobile app from the web UI.
See [SwitchBot Cloud](https://www.home-assistant.io/integrations/switchbot_cloud/)
and [Marketplace](https://www.home-assistant.io/integrations/marketplace/).

To set general options during setup, pass `--settings-file` with a private
JSON object. For example, `{"location_name":"Home","time_zone":"Asia/Shanghai"}`.
Other supported fields include `latitude`, `longitude`, `country`, and `currency`.
The clean install starts with the defaults, one owner account, and a fresh
device registry, history, and Node-RED workspace.

Use `provision` to create the VM and stop at the welcome screen, including when
you plan to restore a backup.

```sh
node setup_homeassistant/install.mjs provision --vmid 106 --name haos-new
```

Use `configure` for an already booted, fresh Home Assistant OS instance.
After an interrupted configuration, rerun with `--resume` and the same owner
username and password. It skips installed apps and completed onboarding steps.
If the guest agent cannot report its address, get the IP from the Proxmox VM
console and use the same `configure` command with the URL shown there. New HAOS
installations can use port 80, while older ones can use port 8123.

```sh
node setup_homeassistant/install.mjs configure --target http://192.168.1.50
```

### Add SSH access and Xiaomi Home

Pass your `.pub` file to `--ssh-public-key` to configure and start Advanced SSH.
The installer adds the key alongside any existing keys, sets the app to start
on boot, and retains its existing SSH port if one is set. `--ssh-user` selects
the login name for a fresh app. Keep the matching private key on your workstation.

Pass `--xiaomi-home` to acknowledge the Marketplace's first-use notice and
install Xiaomi's official integration. Set `--xiaomi-browser` to a local Chrome
or Chromium executable to open the add-integration screen. The separate
browser profile routes Xiaomi's fixed `homeassistant.local:8123` callback to the
target VM's HTTP address and port. Its mapping is scoped to that window, which
lets a second Home Assistant instance keep using `homeassistant.local` on the
LAN. Review Xiaomi's terms, authorize the account, and choose the homes to
import in that browser window. See [Xiaomi Home's setup guide](https://github.com/XiaoMi/ha_xiaomi_home).

Both options work with `install`. For a VM you already set up, use `configure
--resume` with its own address and owner account.

```sh
node setup_homeassistant/install.mjs configure --resume \
  --target http://192.168.1.50 --ssh-public-key "$HOME/.ssh/id_ed25519.pub" \
  --ssh-user myuser --xiaomi-home \
  --xiaomi-browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

Run the installer tests with `node --test tests/test_homeassistant_install.mjs`.
They use fixtures for Proxmox and Home Assistant.

## Migrate an existing installation

Use `migrate.py` on your Mac or a Linux workstation with Python 3.9 or newer.
It uses the existing `ha` SSH alias to create a full encrypted Supervisor
backup. On a fresh HAOS installation it uploads the archive and restores the
Home Assistant configuration, integration entries, dashboards, automations,
users, local history, add-ons and their data, and other folders in the backup.
The source SSH add-on must provide Bash, curl, and Supervisor backup access in
its login environment. The destination uses the Home Assistant welcome screen
and needs no account, SSH add-on, or API token of its own.

### Back up the running VM

```sh
python3 setup_homeassistant/migrate.py backup
```

The command prints the full archive path. It defaults to SSH alias `ha` and
creates a new private directory under `~/.local/share/homeassistant-migration/`
each time. Use `--source another-ha` or `--output-dir /path/to/private/storage`
to override those defaults. The directory holds `home-assistant.tar`, its
SHA-256 checksum, and `restore-key.txt`. Keep the key in private storage with a
recoverable copy and keep these files out of Git. The source keeps a copy in
its local Home Assistant backup list.

### Restore on the replacement

1. Boot a fresh [Home Assistant OS installation](https://www.home-assistant.io/installation/)
   for the replacement hardware. For Proxmox, use `provision` above with
   enough space for the restored data, and a network bridge
   with access to the add-on repositories. Use the new guest's IP and leave it
   at the welcome screen. Use the same CPU architecture where possible so the
   add-on images remain available. See the [HAOS virtual-machine images](https://www.home-assistant.io/installation/alternative/).
2. Take a final backup if the source changed. Shut down the old VM before
   starting the restore, or isolate the replacement from devices and services
   so two copies of your automations cannot control the same home.
3. Pass the printed archive path and the new machine's welcome-screen URL.
   Use a trusted LAN for the default HTTP welcome screen, or HTTPS with a
   trusted certificate.

   ```sh
   python3 setup_homeassistant/migrate.py restore \
     /path/to/home-assistant.tar --target http://192.168.1.50
   ```

   The script reads the key beside its own archives. When the key is stored
   separately, pass `--key-file /path/to/key.txt` with only the key in the file.
   It prompts if a protected archive has no accompanying key. Both commands
   default to an hour for long operations. Use `--timeout` in seconds to adjust.
4. Sign in with your existing Home Assistant account. Check **Settings → System
   → Repairs** and the add-ons after Core restarts. Reattach any USB radios or
   Proxmox passthrough devices. Reconfigure host networking, DHCP reservations,
   external databases, or other outside services where applicable.

If the target goes offline during the restore, the script waits for it to come
back and reports whether Home Assistant confirmed the job or only its restored
UI is reachable. If the script reports an error, check the replacement's
Supervisor logs from its console with `ha supervisor logs` before retrying. An
existing matching upload can be reused while the target is still at the welcome
screen. You can also upload the same archive and enter its key from the welcome
screen. See [Home Assistant's backup and restore guide](https://www.home-assistant.io/common-tasks/general/backups/).
