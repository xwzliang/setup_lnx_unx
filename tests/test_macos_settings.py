"""Exercise macOS update-notification suppression with temporary shims."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "packages/macos-settings/scripts/disable_update_notifications.sh"


class DisableUpdateNotificationsTests(unittest.TestCase):
    def _create_shims(self, root: Path, *, os_name: str = "Darwin", sudo_non_interactive: bool = False) -> Path:
        bindir = root / "bin"
        bindir.mkdir(exist_ok=True)
        log = root / "commands.log"
        ncprefs_file = root / "ncprefs.plist"

        def write_shim(name: str, body: str) -> None:
            path = bindir / name
            path.write_text(f"#!/bin/sh\n{body}\n")
            path.chmod(0o755)

        write_shim("uname", f'echo "{os_name}"')
        write_shim("killall", f'printf "killall %s\\n" "$*" >> "{log}"')
        write_shim("pkill", f'printf "pkill %s\\n" "$*" >> "{log}"')
        write_shim("launchctl", f'printf "launchctl %s\\n" "$*" >> "{log}"')
        write_shim("softwareupdate", f'printf "softwareupdate %s\\n" "$*" >> "{log}"')
        if sudo_non_interactive:
            write_shim("sudo", f'if [ "$1" = "-n" ]; then exit 0; fi\nprintf "sudo %s\\n" "$*" >> "{log}"\n"$@"')
        else:
            write_shim("sudo", f'if [ "$1" = "-n" ]; then exit 1; fi\nprintf "sudo %s\\n" "$*" >> "{log}"\n"$@"')

        defaults = bindir / "defaults"
        defaults.write_text(f'''#!{sys.executable}
import pathlib, plistlib, sys

log = pathlib.Path({str(log)!r})
ncprefs = pathlib.Path({str(ncprefs_file)!r})
with log.open("a") as fh:
    fh.write("defaults " + " ".join(sys.argv[1:]) + "\\n")

cmd = sys.argv[1]
if cmd == "export":
    target = ncprefs if sys.argv[2] == "com.apple.ncprefs" else pathlib.Path(sys.argv[2])
    if target.exists():
        sys.stdout.buffer.write(target.read_bytes())
    else:
        sys.exit(1)
elif cmd == "import":
    target = ncprefs if sys.argv[2] == "com.apple.ncprefs" else pathlib.Path(sys.argv[2])
    data = sys.stdin.buffer.read()
    plistlib.loads(data)
    target.write_bytes(data)
''')
        defaults.chmod(0o755)
        return log

    def test_defers_notifications_disables_ncprefs_and_clears_update_badge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            prefs = home / "Library/Preferences"
            prefs.mkdir(parents=True)
            sys_prefs = prefs / "com.apple.systempreferences.plist"
            with sys_prefs.open("wb") as fh:
                plistlib.dump({
                    "AttentionPrefBundleIDs": {
                        "com.apple.FollowUpSettings.FollowUpSettingsExtension": 1,
                        "com.apple.unrelated.setting": 1,
                    },
                    "KeepOtherKey": "preserved",
                }, fh)

            ncprefs = root / "ncprefs.plist"
            with ncprefs.open("wb") as fh:
                plistlib.dump({
                    "apps": [
                        {
                            "bundle-id": "_SYSTEM_CENTER_:com.apple.SoftwareUpdateNotification",
                            "auth": 7,
                            "flags": 327688855,
                        },
                        {
                            "bundle-id": "com.example.other",
                            "auth": 7,
                            "flags": 1234,
                        },
                    ]
                }, fh)

            log = self._create_shims(root, sudo_non_interactive=False)
            env = dict(os.environ, HOME=str(home), PATH=f"{root / 'bin'}:/usr/bin:/bin")
            result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("skipped system-wide", result.stdout)
            lines = log.read_text().splitlines()
            self.assertIn("defaults write com.apple.SoftwareUpdate UserNotificationDate -date 2099-01-01 00:00:00 +0000", lines)
            self.assertIn("defaults write com.apple.SoftwareUpdate MajorOSUserNotificationDate -date 2099-01-01 00:00:00 +0000", lines)
            self.assertTrue(any(line.startswith("launchctl disable gui/") and line.endswith("/com.apple.SoftwareUpdateNotificationManager") for line in lines))
            self.assertTrue(any(line.startswith("launchctl bootout gui/") and line.endswith("/com.apple.SoftwareUpdateNotificationManager") for line in lines))
            self.assertIn("pkill -KILL -f /SoftwareUpdateNotificationManager.app/Contents/MacOS/SoftwareUpdateNotificationManager", lines)
            self.assertIn("killall usernoted", lines)
            self.assertIn("killall NotificationCenter", lines)
            self.assertIn("killall Dock", lines)
            self.assertFalse(any(line.startswith("sudo ") for line in lines))

            updated = plistlib.loads(sys_prefs.read_bytes())
            self.assertEqual(updated["AttentionPrefBundleIDs"], {"com.apple.unrelated.setting": 1})
            self.assertEqual(updated["KeepOtherKey"], "preserved")

            updated_nc = plistlib.loads(ncprefs.read_bytes())
            su_entry = updated_nc["apps"][0]
            self.assertEqual(su_entry["auth"], 0)
            self.assertEqual(su_entry["flags"] & 0x0300001F, 0)
            self.assertEqual(updated_nc["apps"][1]["flags"], 1234)

            restore = subprocess.run(["bash", str(SCRIPT), "--restore"], env=env, capture_output=True, text=True)
            self.assertEqual(restore.returncode, 0, restore.stderr)
            restored_nc = plistlib.loads(ncprefs.read_bytes())
            self.assertEqual(restored_nc["apps"][0]["auth"], 7)
            self.assertEqual(restored_nc["apps"][0]["flags"] & 0x03000017, 0x03000017)

    def test_with_sudo_flag_disables_automatic_check_and_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            log = self._create_shims(root, sudo_non_interactive=False)
            env = dict(os.environ, HOME=str(home), PATH=f"{root / 'bin'}:/usr/bin:/bin")
            result = subprocess.run(
                ["bash", str(SCRIPT), "--with-sudo", "--defer-until", "2040-01-01 00:00:00 +0000"],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            lines = log.read_text().splitlines()
            self.assertIn("defaults write com.apple.SoftwareUpdate UserNotificationDate -date 2040-01-01 00:00:00 +0000", lines)
            self.assertIn("sudo softwareupdate --schedule off", lines)
            self.assertIn("sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled -bool false", lines)
            self.assertIn("sudo defaults write /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload -bool false", lines)

    def test_rejects_non_macos_and_unknown_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._create_shims(root, os_name="Linux")
            env = dict(os.environ, HOME=str(root), PATH=f"{root / 'bin'}:/usr/bin:/bin")
            non_mac = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
            self.assertEqual(non_mac.returncode, 1)
            self.assertIn("only supports macOS", non_mac.stderr)

            self._create_shims(root, os_name="Darwin")
            bad_opt = subprocess.run(["bash", str(SCRIPT), "--bogus"], env=env, capture_output=True, text=True)
            self.assertEqual(bad_opt.returncode, 2)
            self.assertIn("Unknown argument", bad_opt.stderr)


if __name__ == "__main__":
    unittest.main()
