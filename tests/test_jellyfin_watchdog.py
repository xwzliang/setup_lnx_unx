import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "packages/jellyfin/scripts/watchdog.py"
SPEC = importlib.util.spec_from_file_location("jellyfin_watchdog", SCRIPT)
WATCHDOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WATCHDOG)


class JellyfinWatchdogTests(unittest.TestCase):
    def test_healthy_service_is_left_alone(self):
        with patch.object(WATCHDOG, "healthy", return_value=True), patch.object(
            WATCHDOG, "processes"
        ) as processes:
            WATCHDOG.recover()
        processes.assert_not_called()

    def test_backend_still_running_is_left_alone_after_failed_probes(self):
        backend = ["12", str(os.getuid()), str(WATCHDOG.APP / "Contents/MacOS/jellyfin")]
        with patch.object(WATCHDOG, "healthy", return_value=False), patch.object(
            WATCHDOG.time, "sleep"
        ), patch.object(WATCHDOG, "launcher_path"), patch.object(
            WATCHDOG, "processes", return_value=[backend]
        ), patch.object(WATCHDOG, "quit_launcher") as quit_launcher, patch.object(
            WATCHDOG.subprocess, "run"
        ) as open_app:
            with self.assertRaisesRegex(RuntimeError, "backend is still running"):
                WATCHDOG.recover()
        quit_launcher.assert_not_called()
        open_app.assert_not_called()

    def test_missing_backend_relaunches_a_stale_wrapper(self):
        launcher = str(WATCHDOG.APP / "Contents/MacOS/Jellyfin Server")
        stale = ["12", str(os.getuid()), launcher]
        with patch.object(WATCHDOG, "healthy", side_effect=[False, False, False, True]), patch.object(
            WATCHDOG.time, "sleep"
        ), patch.object(WATCHDOG, "launcher_path", return_value=launcher), patch.object(
            WATCHDOG, "processes", side_effect=[[stale], []]
        ), patch.object(WATCHDOG, "quit_launcher") as quit_launcher, patch.object(
            WATCHDOG.subprocess, "run"
        ) as open_app:
            WATCHDOG.recover()
        quit_launcher.assert_called_once_with("12")
        open_app.assert_called_once_with(
            ["/usr/bin/open", "-gj", "-a", str(WATCHDOG.APP)], check=True, timeout=10
        )
