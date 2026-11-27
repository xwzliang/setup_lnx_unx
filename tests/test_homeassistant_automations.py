"""Exercise the automation file transaction with an isolated config directory."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "setup_homeassistant"))
try:
    import automation_remote as worker
    import manage_automations as client
finally:
    sys.path.pop(0)


class AutomationDeploymentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.original = {worker.AUTOMATIONS: "- id: original\n", worker.XIAOMI: "original package\n"}
        for name, value in self.original.items():
            item = self.root / name
            item.parent.mkdir(exist_ok=True)
            item.write_text(value)
            item.chmod(0o640)
        for override in (patch.object(worker, "CONFIG", self.root), patch.object(worker, "validate_yaml"),
                         patch.object(worker, "check_layout")):
            override.start()
            self.addCleanup(override.stop)

    def test_matching_deploy_is_read_only(self):
        with patch.object(worker, "check_core") as validate, patch.object(worker, "reload_domain") as reload:
            self.assertEqual(worker.apply(self.original), {"status": "unchanged"})
        validate.assert_not_called()
        reload.assert_not_called()
        self.assertFalse((self.root / ".automation-deploy-backups").exists())

    def test_packages_are_validated_before_ordered_reload_and_backed_up(self):
        updated = {worker.AUTOMATIONS: "- id: revised\n", worker.XIAOMI: "revised package\n"}
        events = []

        def core_check():
            self.assertEqual(worker.read_managed(), updated)
            events.append("check")

        with patch.object(worker, "check_core", side_effect=core_check), patch.object(
                worker, "reload_domain", side_effect=events.append):
            result = worker.apply(updated)
        self.assertEqual(events, ["check", "shell_command", "automation"])
        self.assertEqual(worker.read_managed(), updated)
        for name in worker.MANAGED:
            self.assertEqual((Path(result["backup"]) / name).read_text(), self.original[name])
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o640)

    def test_failed_core_check_restores_files_without_reloading(self):
        updated = {**self.original, worker.AUTOMATIONS: "invalid configuration\n"}
        with patch.object(worker, "check_core", side_effect=worker.DeployError("Invalid config")), patch.object(
                worker, "reload_domain") as reload:
            with self.assertRaisesRegex(worker.DeployError, "Previous YAML restored"):
                worker.apply(updated)
        self.assertEqual(worker.read_managed(), self.original)
        reload.assert_not_called()

    def test_failed_reload_tries_to_reload_the_restored_yaml(self):
        updated = {**self.original, worker.AUTOMATIONS: "- id: revised\n"}
        with patch.object(worker, "check_core"), patch.object(
                worker, "reload_domain", side_effect=[worker.DeployError("Unavailable"), None]) as reload:
            with self.assertRaisesRegex(worker.DeployError, "Previous YAML restored"):
                worker.apply(updated)
        self.assertEqual(worker.read_managed(), self.original)
        self.assertEqual(reload.call_args_list, [call("automation"), call("automation")])

    def test_failed_validation_does_not_clobber_a_concurrent_edit(self):
        updated = {**self.original, worker.AUTOMATIONS: "- id: revise\n"}
        concurrent_edit = "- id: from_ui\n"

        def check():
            (self.root / worker.AUTOMATIONS).write_text(concurrent_edit)

        with patch.object(worker, "check_core", side_effect=check), patch.object(worker, "reload_domain") as reload:
            with self.assertRaisesRegex(worker.DeployError, "Review the private backup"):
                worker.apply(updated)
        reload.assert_not_called()
        self.assertEqual(worker.read_managed()[worker.AUTOMATIONS], concurrent_edit)


class AutomationCheckoutTests(unittest.TestCase):
    def test_checkout_keeps_local_edits_unless_replacement_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            working = Path(directory) / "worktree"
            data = {name: "initial YAML\n" for name in worker.MANAGED}
            with patch.object(client, "WORKTREE", working), patch.object(client, "BASELINE", working / ".baseline"):
                with patch("builtins.print"):
                    client.checkout(data)
                    (working / worker.AUTOMATIONS).write_text("unsealed edit\n")
                    with self.assertRaisesRegex(client.AutomationError, "Working YAML differs"):
                        client.checkout(data)
                    self.assertEqual((working / worker.AUTOMATIONS).read_text(), "unsealed edit\n")
                    client.checkout(data, replace=True)
                self.assertEqual(client.local_files(), data)
                self.assertEqual((working / ".baseline").read_text().strip(), client.fingerprint(data))


if __name__ == "__main__":
    unittest.main()
