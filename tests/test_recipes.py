"""Recipe integration tests. Only temporary fixture scripts can execute here."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from setup_tool import catalog, cli, managers, recipes
from test_setup import invoke


class MigratedCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packages = catalog.load_catalog()

    def test_every_recipe_previews_without_processes(self):
        with patch.object(cli, "load_catalog", return_value=self.packages), patch(
            "subprocess.run", side_effect=AssertionError("preview executed a process")
        ):
            for item in self.packages.values():
                for name, recipe in item.get("recipes", {}).items():
                    for target in recipe["os"]:
                        with self.subTest(package=item["name"], recipe=name, target=target):
                            code, output, error = invoke(recipe["action"], item["name"], "--recipe", name, "--os", target)
                            self.assertEqual(code, 0, error)
                            self.assertIn("Nothing executed", output)

    def test_all_original_files_are_mapped_to_package_owned_files(self):
        mapping = json.loads((catalog.ROOT / "docs/recipe-migration.json").read_text())
        for old, new in mapping.items():
            with self.subTest(old=old):
                original, destination = catalog.ROOT / old, catalog.ROOT / new
                self.assertTrue(original.is_symlink())
                self.assertTrue(destination.is_file())
                self.assertEqual(original.resolve(), destination.resolve())
                self.assertTrue(destination.resolve().is_relative_to(catalog.ROOT / "packages"))
        scripts = {r["script"] for item in self.packages.values() for r in item.get("recipes", {}).values()}
        for old, new in mapping.items():
            if Path(old).suffix in {".sh", ".py"} and not Path(old).name.startswith("test_"):
                self.assertIn(new, scripts)

    def test_shell_and_python_sources_parse_without_running(self):
        for item in self.packages.values():
            for recipe in item.get("recipes", {}).values():
                path = catalog.ROOT / recipe["script"]
                with self.subTest(path=path):
                    if recipe["interpreter"] == "python3":
                        compile(path.read_text(), str(path), "exec")
                    else:
                        result = subprocess.run([recipe["interpreter"], "-n", str(path)], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                    # Bash syntax checking cannot parse embedded Python helpers.
                    text = path.read_text()
                    if "<<'PYCONFIG'" in text:
                        embedded = text.split("<<'PYCONFIG'", 1)[1].split("\n", 1)[1].split("\nPYCONFIG", 1)[0]
                        compile(embedded, str(path) + ":embedded-python", "exec")

    def test_shell_configuration_is_repeatable_in_temporary_home(self):
        with tempfile.TemporaryDirectory(prefix="setup-shell-config-") as directory:
            home = Path(directory)
            # Fixtures satisfy downloads; these tests may only write this home.
            (home / ".oh-my-zsh/custom/plugins/zsh-autosuggestions").mkdir(parents=True)
            (home / ".local/share/setup_lnx_unx").mkdir(parents=True)
            (home / ".local/share/setup_lnx_unx/z.sh").write_text("# fixture\n")
            for shell in ("bash", "zsh"):
                rc = home / f".{shell}rc"
                rc.write_text("# keep personal settings\n")
                recipe = self.packages[shell]["recipes"][shell + "-setup"]
                environment = dict(os.environ, HOME=str(home))
                for _ in range(2):
                    result = subprocess.run(["bash", "-e", str(catalog.ROOT / recipe["script"])],
                                            env=environment, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                text = rc.read_text()
                self.assertTrue(text.startswith("# keep personal settings\n"))
                self.assertEqual(text.count(f'"$HOME/.{shell}_aliases"'), 2)

    def test_combined_zsh_plan_includes_install_and_configure(self):
        with patch("subprocess.run", side_effect=AssertionError("preview ran a process")):
            code, output, error = invoke("setup", "zsh", "--os", "ubuntu")
        self.assertEqual(code, 0, error)
        self.assertLess(output.index("apt-get install"), output.index("Recipe: zsh-setup"))

    def test_keyboard_requires_explicit_variant(self):
        code, _, errors = invoke("configure", "keyboard", "--os", "ubuntu")
        self.assertEqual(code, 2)
        self.assertIn("Choose a configure recipe", errors)

    def test_remove_and_run_cannot_be_selected_implicitly(self):
        for action, package in (("remove", "zotero"), ("run", "workstation")):
            code, _, error = invoke(action, package, "--os", "ubuntu")
            self.assertEqual(code, 2)
            self.assertIn("requires --recipe", error)

    def test_openwrt_recipe_can_be_previewed(self):
        code, output, error = invoke("run", "passwall", "--recipe", "ensure-passwall", "--os", "openwrt")
        self.assertEqual(code, 0, error)
        self.assertIn("sh -e", output)

    def test_show_selected_source_and_filtered_json(self):
        code, output, error = invoke("show", "zsh", "--recipe", "zsh-setup", "--source")
        self.assertEqual(code, 0, error)
        self.assertIn("oh-my-zsh", output)
        code, output, _ = invoke("show", "comfyui", "--os", "macos", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(all("macos" in r["os"] for r in json.loads(output)["recipes"].values()))


class RecipeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="setup-recipes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = self.root / "packages/demo"
        folder.mkdir(parents=True)
        script = folder / "configure.py"
        script.write_text('''import json, os, pathlib, sys
path = pathlib.Path(os.environ["SETUP_LOG"])
with path.open("a") as file:
    file.write(json.dumps({"phase":"configure", "argv":sys.argv[1:], "cwd":os.getcwd(), "value":os.environ.get("SETUP_VALUE")}) + "\\n")
sys.exit(int(os.environ.get("SETUP_FAIL", "0")))
''')
        self.log = self.root / "events.jsonl"
        self.recipe = {"action": "configure", "os": ["ubuntu"], "script": "packages/demo/configure.py",
                       "interpreter": "python3", "description": "Fixture", "effects": "Writes only temporary test data",
                       "requires": [], "parameters": {
                           "LOG": {"description": "Fixture log", "required": True},
                           "VALUE": {"description": "Literal test input"},
                           "FAIL": {"description": "Fixture status", "default": "0"}}}
        self.item = {"name": "demo", "description": "Fixture", "install": {"ubuntu": {"manager": "apt", "package": "demo"}},
                     "recipes": {"settings": self.recipe}, "defaults": {"configure": {"ubuntu": "settings"}}}
        for mock in (patch.object(cli, "load_catalog", return_value={"demo": self.item}),
                     patch.object(cli, "detect_os", return_value="ubuntu"),
                     patch.object(recipes, "ROOT", self.root),
                     patch.object(recipes, "local_path", lambda path, root=self.root: catalog.local_path(path, root)),
                     patch.object(managers, "require"), patch.object(managers, "install", self.fake_install)):
            mock.start()
            self.addCleanup(mock.stop)

    def fake_install(self, method):
        with self.log.open("a") as file:
            file.write(json.dumps({"phase": "install", "package": method["package"]}) + "\n")

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_combined_apply_order_and_literal_parameter_forwarding(self):
        value = 'spaces; $(touch NEVER) "quotes"'
        code, _, error = invoke("setup", "demo", "--apply", "--set", "LOG=" + str(self.log),
                                "--set", "VALUE=" + value, "--configure-arg=--fixture", "--configure-arg=two words")
        self.assertEqual(code, 0, error)
        self.assertEqual([e["phase"] for e in self.events()], ["install", "configure"])
        event = self.events()[1]
        self.assertEqual(event["value"], value)
        self.assertEqual(event["argv"], ["--fixture", "two words"])
        self.assertEqual(event["cwd"], str(self.root / "packages/demo"))

    def test_missing_required_parameter_blocks_install_too(self):
        code, _, error = invoke("setup", "demo", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("requires --set LOG", error)
        self.assertEqual(self.events(), [])

    def test_wrong_os_never_executes(self):
        with patch.object(cli, "detect_os", return_value="macos"):
            code, _, error = invoke("setup", "demo", "--os", "ubuntu", "--apply", "--set", "LOG=" + str(self.log))
        self.assertEqual(code, 2)
        self.assertIn("refusing", error)
        self.assertEqual(self.events(), [])

    def test_unknown_parameters_and_manager_arguments_are_rejected(self):
        for args in (("configure", "demo", "--set", "HOME=/tmp"),
                     ("install", "demo", "--", "extra-package")):
            self.assertEqual(invoke(*args)[0], 2)
        self.assertEqual(self.events(), [])

    def test_script_status_is_reported(self):
        code, _, error = invoke("configure", "demo", "--apply", "--set", "LOG=" + str(self.log), "--set", "FAIL=23")
        self.assertEqual(code, 2)
        self.assertIn("exit code 23", error)

    def test_failed_install_stops_before_configuration(self):
        with patch.object(managers, "install", side_effect=catalog.SetupError("fixture installation failed")):
            code, _, error = invoke("setup", "demo", "--apply", "--set", "LOG=" + str(self.log))
        self.assertEqual(code, 2)
        self.assertIn("fixture installation failed", error)
        self.assertEqual(self.events(), [])

    def test_positional_arguments_are_not_interpreted_by_a_shell(self):
        argument = '; touch ' + str(self.root / "SHOULD_NOT_EXIST")
        code, _, error = invoke("configure", "demo", "--apply", "--set", "LOG=" + str(self.log), "--", argument)
        self.assertEqual(code, 0, error)
        self.assertEqual(self.events()[0]["argv"], [argument])
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())

    def test_recipe_paths_and_default_action_are_validated(self):
        recipes.validate_recipes(self.item, self.root)
        self.item["defaults"]["install"] = {"ubuntu": "settings"}
        with self.assertRaises(ValueError):
            recipes.validate_recipes(self.item, self.root)
        self.item["defaults"].pop("install")
        self.recipe["script"] = "/etc/passwd"
        with self.assertRaises(catalog.SetupError):
            recipes.validate_recipes(self.item, self.root)

    def test_configure_commands_can_be_provided_by_install_phase(self):
        self.recipe["requires"] = ["package-provided-command"]
        initial = recipes.shutil.which
        def available(command):
            if command == "package-provided-command":
                return "/fixture/command" if self.events() else None
            return initial(command)
        with patch.object(recipes.shutil, "which", side_effect=available):
            code, _, error = invoke("setup", "demo", "--apply", "--set", "LOG=" + str(self.log))
        self.assertEqual(code, 0, error)

    def test_reserved_parameters_are_rejected(self):
        self.recipe["parameters"]["REPO_ROOT"] = {"description": "bad override"}
        with self.assertRaisesRegex(ValueError, "reserved"):
            recipes.validate_recipes(self.item, self.root)


if __name__ == "__main__":
    unittest.main()
