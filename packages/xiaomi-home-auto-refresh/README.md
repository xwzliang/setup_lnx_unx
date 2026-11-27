# Xiaomi Home device-list refresh

Installs a Home Assistant automation for the Xiaomi Home device-list notification.
It listens for additions to the selected Xiaomi Home account. It previews the
same Options flow as **Configure → Update device list** and confirms it only when
there are additions and **zero removals**. Existing homes, control mode, and other
configuration options are preserved. Offline-only notifications do not trigger a
refresh. The automation dismisses the triggering Xiaomi notice after a confirmed
import. It leaves the notice visible when the refresh is skipped, finds no new
devices, or fails. A newer notice queued during the import gets checked on its own.

This recipe is designed for Home Assistant OS on the same host as Xiaomi Home.
It uses Home Assistant's administrator-only options API at `127.0.0.1:8123`,
where the Home Assistant Core shell command runs. It is scoped to a single
Xiaomi Home entry without device filters. The known flow is Xiaomi Home v0.4.7
and Home Assistant Core 2026.11.3. If an upgrade changes the options form, the
runner cancels the flow. Reloading Xiaomi Home is part of a successful refresh,
so its entities may briefly reconnect.

## Install on Home Assistant OS

Home Assistant must already have `packages: !include_dir_named packages` under
`homeassistant:` in its configuration. The installer uses the shared Home
Assistant administrator credential in `/config/.home-assistant/token`
(mode 0600). If the file is absent, create a long-lived access token in an
administrator's Home Assistant profile and enter it at the installer's hidden
prompt. Keep the token out of Git, YAML, shell arguments, and command history.

Run these commands from your checkout with `ha` set up as your Home Assistant
SSH alias.

```sh
scp setup_homeassistant/xiaomi_home_auto_refresh.py ha:/tmp/
ssh -t ha 'sudo -n python3 /tmp/xiaomi_home_auto_refresh.py install'
```

For a configuration directory available on the current machine, use the setup
catalog. Omit `--apply` to preview the install itself.

```sh
./setup configure xiaomi-home-auto-refresh --apply -- --config-dir /config install
```

In Home Assistant, open **Settings → Tools → YAML** and click **Check
configuration**. Reload **Shell Command**, then **Automations**. If those reload
buttons are unavailable, restart Core after the check. A preview of the current
device-list diff can be run without confirming the flow:

```sh
ssh ha 'sudo -n python3 /config/xiaomi_home_auto_refresh/refresh.py run'
```

A manual `run --apply` uses the same zero-removal gate as the automation. The
next matching new-device notification triggers automatic refresh. The automation's
trace records the result. A refresh API error is logged in Home Assistant.
You can turn off **Xiaomi Home · Import newly discovered devices** in the
Automations list.

[Xiaomi Home configuration options](https://github.com/XiaoMi/ha_xiaomi_home#configuration-options) ·
[Home Assistant notifications](https://www.home-assistant.io/integrations/persistent_notification/)
