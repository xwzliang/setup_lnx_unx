# Migrate Home Assistant OS

Use `migrate.py` on your Mac or a Linux workstation with Python 3.9 or newer.
It uses the existing `ha` SSH alias to create a full encrypted Supervisor
backup. On a fresh HAOS installation it uploads the archive and restores the
Home Assistant configuration, integration entries, dashboards, automations,
users, local history, add-ons and their data, and other folders in the backup.
The source SSH add-on must provide Bash, curl, and Supervisor backup access in
its login environment. The destination uses the Home Assistant welcome screen
and needs no account, SSH add-on, or API token of its own.

## Back up the running VM

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

## Set up the replacement

1. Boot a fresh [Home Assistant OS installation](https://www.home-assistant.io/installation/)
   for the replacement hardware. For Proxmox, use the official KVM/Proxmox disk
   image with UEFI, enough space for the restored data, and a network bridge
   with access to the add-on repositories. Use the new guest's IP and leave it
   at the welcome screen. Use the same CPU architecture where possible so the
   add-on images remain available. See the [HAOS virtual-machine images](https://www.home-assistant.io/installation/alternative/).
2. Take a final backup if the source changed. Shut down the old VM before
   starting the restore, or isolate the replacement from devices and services
   so two copies of your automations cannot control the same home.
3. Pass the printed archive path and the new machine's URL. Use a trusted LAN
   for the default HTTP welcome screen, or HTTPS with a trusted certificate.

   ```sh
   python3 setup_homeassistant/migrate.py restore \
     /path/to/home-assistant.tar --target http://192.168.1.50:8123
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
