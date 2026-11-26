# Jellyfin on macOS

Run the following from the repository on the Mac that runs Jellyfin, as the
same user who runs the app. That user must be logged into the Mac desktop.

```sh
./setup configure jellyfin --recipe watchdog --apply
```

The LaunchAgent checks Jellyfin on `127.0.0.1:8096` every minute while the user
is logged in. If the backend has exited, it stops a leftover menu-bar launcher,
opens `/Applications/Jellyfin.app`, and checks that the server is responding
again. Repeated health failures while the backend is still running are logged
without interrupting the process.

See `~/Library/Logs/jellyfin-watchdog.log` for recovery attempts and errors.
Disable the watchdog before intentionally stopping Jellyfin for maintenance.
Running the configure recipe again re-enables it.

```sh
service="gui/$(id -u)/com.setup-lnx-unx.jellyfin-watchdog"
launchctl disable "$service"
launchctl bootout "$service"
```
