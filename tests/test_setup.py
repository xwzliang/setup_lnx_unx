"""Offline behavioral tests: fake managers, temporary config, no installations."""
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

from setup_tool import catalog, cli, configuration, managers


def invoke(*args):
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        code = cli.main(list(args))
    return code, output.getvalue(), errors.getvalue()


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packages = catalog.load_catalog()

    def test_every_install_and_configuration_can_preview_without_a_subprocess(self):
        with patch.object(cli, "load_catalog", return_value=self.packages), patch(
            "subprocess.run", side_effect=AssertionError("preview executed a command")
        ):
            for item in self.packages.values():
                for action in ("install", "configure"):
                    for target in item.get(action, {}):
                        with self.subTest(package=item["name"], action=action, target=target):
                            code, output, errors = invoke(action, item["name"], "--os", target)
                            self.assertEqual(code, 0, errors)
                            self.assertIn("Nothing executed", output)

    def test_alias_and_os_filter(self):
        code, output, _ = invoke("show", "docker.io", "--os", "macos", "--json")
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertEqual(list(result["install"]), ["macos"])
        self.assertEqual(result["install"]["macos"]["options"], ["--cask"])
        self.assertEqual(catalog.resolve(self.packages, "rg")["name"], "ripgrep")

    def test_search_finds_setup_path_and_os(self):
        code, output, _ = invoke("search", "setup_proxmox", "--os", "debian", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["name"], "proxmox-autologin")
        code, output, _ = invoke("search", "google-chrome", "--os", "macos", "--json")
        self.assertEqual(code, 0)
        self.assertIn("google-chrome", [item["name"] for item in json.loads(output)])

    def test_reference_only_package_is_not_executable(self):
        with patch("subprocess.run", side_effect=AssertionError("executed legacy script")):
            code, _, errors = invoke("install", "proxmox-autologin", "--os", "debian", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("No managed install recipe", errors)

    def test_host_mismatch_refuses_before_running_anything(self):
        with patch.object(cli, "detect_os", return_value="ubuntu"), patch(
            "subprocess.run", side_effect=AssertionError("wrong host executed a command")
        ):
            code, _, errors = invoke("install", "git", "--os", "macos", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("refusing", errors)

    def test_unknown_host_does_not_inherit_ubuntu(self):
        with patch.object(cli, "detect_os", return_value="fedora"):
            code, _, errors = invoke("install", "git")
        self.assertEqual(code, 2)
        self.assertIn("Unsupported execution OS", errors)

    def test_os_detection_uses_exact_id(self):
        with patch.object(catalog.platform, "system", return_value="Linux"), patch.object(
            Path, "read_text", return_value='ID=linuxmint\nID_LIKE="ubuntu debian"\n'
        ):
            self.assertEqual(catalog.detect_os(), "linuxmint")
        with patch.object(catalog.platform, "system", return_value="Darwin"):
            self.assertEqual(catalog.detect_os(), "macos")

    def test_unknown_package_and_empty_search_are_actionable(self):
        code, _, errors = invoke("show", "does-not-exist")
        self.assertEqual(code, 2)
        self.assertIn("Try: ./setup search", errors)
        self.assertEqual(invoke("search", "nothing-matches-this-name")[0], 1)

    def test_entry_point_works_outside_repository(self):
        result = subprocess.run([str(catalog.ROOT / "setup"), "show", "tmux", "--os", "ubuntu"],
                                cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("apt-get install -y tmux", result.stdout)

    def test_generated_index_is_current(self):
        self.assertEqual((catalog.ROOT / "docs/packages.md").read_text(), cli.index(self.packages))

    def test_all_package_scripts_are_discoverable(self):
        references = {ref["path"] for item in self.packages.values() for ref in item.get("references", [])}
        for path in (catalog.ROOT / "packages").rglob("*"):
            if path.suffix in {".sh", ".py"} and not path.name.startswith("test_"):
                self.assertIn(str(path.relative_to(catalog.ROOT)), references)

    def test_repository_uses_only_package_owned_entry_points(self):
        self.assertFalse((catalog.ROOT / "legacy").exists())
        self.assertEqual([path.name for path in catalog.ROOT.iterdir() if path.is_symlink()], [])


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "packages/demo").mkdir(parents=True)
        self.item = {"name": "demo", "description": "Example",
                     "install": {"ubuntu": {"manager": "apt", "package": "demo"}}}

    def load(self):
        (self.root / "packages/demo/package.json").write_text(json.dumps(self.item))
        return catalog.load_catalog(self.root)

    def test_valid_manifest_loads(self):
        self.assertEqual(self.load()["demo"]["name"], "demo")

    def test_rejects_shell_fragments_and_options_disguised_as_packages(self):
        for value in ("demo; touch /tmp/bad", "--help", "$(curl example.com)", "git vim"):
            with self.subTest(value=value):
                self.item["install"]["ubuntu"]["package"] = value
                with self.assertRaises(catalog.SetupError):
                    self.load()

    def test_rejects_missing_and_escaping_references(self):
        for value in ("missing.sh", "/etc/passwd", "../outside.sh"):
            self.item["references"] = [{"path": value, "os": ["ubuntu"], "note": "Example"}]
            with self.assertRaises(catalog.SetupError):
                self.load()

    def test_rejects_typo_and_bad_shapes(self):
        for key, value in (("instal", {}), ("aliases", "wrong"), ("install", []),
                           ("references", {}), ("notes", [3])):
            with self.subTest(key=key):
                old = dict(self.item)
                self.item[key] = value
                with self.assertRaises(catalog.SetupError):
                    self.load()
                self.item = old

    def test_rejects_duplicate_aliases_and_unknown_configuration(self):
        self.item["aliases"] = ["demo"]
        with self.assertRaises(catalog.SetupError):
            self.load()
        self.item.pop("aliases")
        self.item["configure"] = {"ubuntu": "run-arbitrary-script"}
        with self.assertRaises(catalog.SetupError):
            self.load()


FAKE_MANAGER = '''import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ["SETUP_TEST_LOG"], "a") as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "dpkg-query":
    if os.environ.get("SETUP_TEST_INSTALLED"):
        print("install ok installed", end="")
        sys.exit(0)
    sys.exit(1)
if name == "sudo":
    # Record the requested argv; never escalate or execute a real manager.
    sys.exit(int(os.environ.get("SETUP_TEST_FAILURE", "0")))
raise SystemExit("Unexpected fake-manager invocation: " + name)
'''


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "calls.jsonl"
        for name in ("sudo", "apt-get", "dpkg-query"):
            path = self.root / name
            path.write_text(f"#!{sys.executable}\n" + FAKE_MANAGER)
            path.chmod(0o755)
        self.environment = patch.dict(os.environ, {"PATH": str(self.root), "SETUP_TEST_LOG": str(self.log)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_apply_requests_exactly_one_package(self):
        with patch.object(cli, "detect_os", return_value="ubuntu"):
            code, _, errors = invoke("install", "git", "--apply")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.calls(), [["dpkg-query", "-W", "-f=${Status}", "git"],
                                       ["sudo", "apt-get", "install", "-y", "git"]])

    def test_already_installed_skips_installation(self):
        with patch.dict(os.environ, {"SETUP_TEST_INSTALLED": "1"}), patch.object(cli, "detect_os", return_value="ubuntu"):
            code, output, _ = invoke("install", "git", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("skipped", output)
        self.assertEqual(len(self.calls()), 1)

    def test_manager_failure_propagates(self):
        with patch.dict(os.environ, {"SETUP_TEST_FAILURE": "42"}), patch.object(cli, "detect_os", return_value="ubuntu"):
            code, _, errors = invoke("install", "git", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("exit code 42", errors)
        self.assertEqual(len(self.calls()), 2)

    def test_missing_manager_is_not_bootstrapped(self):
        with patch("subprocess.run", side_effect=AssertionError("bootstrap attempted")):
            with self.assertRaisesRegex(catalog.SetupError, "no automatic bootstrap"):
                managers.install({"manager": "brew", "package": "git"})


class AdapterTests(unittest.TestCase):
    def test_all_managers_execute_only_the_selected_package(self):
        for method, expected in [
            ({"manager": "brew", "package": "docker", "options": ["--cask"]}, ["brew", "install", "--cask", "docker"]),
            ({"manager": "snap", "package": "emacs", "options": ["--classic"]}, ["sudo", "snap", "install", "--classic", "emacs"]),
            ({"manager": "npm", "package": "@vue/cli"}, ["npm", "install", "--global", "@vue/cli"]),
            ({"manager": "go", "package": "example.org/cli@latest"}, ["go", "install", "example.org/cli@latest"]),
            ({"manager": "pip", "package": "python-lsp-server[all]"}, [sys.executable, "-m", "pip", "install", "python-lsp-server[all]"]),
        ]:
            with self.subTest(manager=method["manager"]), patch.object(managers, "require"), patch.object(
                managers, "installed", return_value=False
            ), patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
                managers.install(method)
                self.assertEqual(run.call_args.args[0], expected)
                self.assertNotIn("shell", run.call_args.kwargs)
                if method["manager"] == "brew":
                    self.assertEqual(run.call_args.kwargs["env"]["HOMEBREW_NO_AUTO_UPDATE"], "1")

    def test_brew_checks_casks_separately(self):
        with patch.object(managers, "capture", return_value=subprocess.CompletedProcess([], 0, "docker 1.0")) as read:
            self.assertTrue(managers.installed({"manager": "brew", "package": "docker", "options": ["--cask"]}))
        self.assertEqual(read.call_args.args[0], ["brew", "list", "--cask", "--versions", "docker"])

    def test_npm_checks_exact_distribution_not_a_substring(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({"dependencies": {"webpack-cli": {}}}))
        with patch.object(managers, "capture", return_value=result):
            self.assertFalse(managers.installed({"manager": "npm", "package": "webpack"}))

    def test_pip_requires_virtual_environment_and_resolves_extras(self):
        with patch.object(managers.shutil, "which", return_value=sys.executable), patch.object(sys, "prefix", sys.base_prefix):
            with self.assertRaisesRegex(catalog.SetupError, "virtual environment"):
                managers.require("pip")
        with patch.object(managers, "capture", side_effect=AssertionError("must resolve extras")):
            self.assertFalse(managers.installed({"manager": "pip", "package": "python-lsp-server[all]"}))


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        home = patch.object(Path, "home", return_value=self.root)
        home.start()
        self.addCleanup(home.stop)

    def test_vim_is_repeatable_and_preserves_conflicts(self):
        with contextlib.redirect_stdout(io.StringIO()):
            configuration.configure("vim-filetypes")
            configuration.configure("vim-filetypes")
        path = self.root / ".vim/ftdetect/setup_lnx_unx.vim"
        self.assertEqual(path.read_text(), configuration.VIM_FILETYPES)
        path.write_text("personal settings")
        with self.assertRaisesRegex(catalog.SetupError, "differs"):
            configuration.configure("vim-filetypes")
        self.assertEqual(path.read_text(), "personal settings")

    def test_vim_refuses_file_symlink(self):
        path = self.root / ".vim/ftdetect/setup_lnx_unx.vim"
        path.parent.mkdir(parents=True)
        target = self.root / "personal.vim"
        target.write_text("original")
        path.symlink_to(target)
        with self.assertRaisesRegex(catalog.SetupError, "symlink"):
            configuration.configure("vim-filetypes")
        self.assertEqual(target.read_text(), "original")

    def test_git_preserves_identity_and_existing_alias(self):
        config = self.root / "gitconfig"
        config.write_text('[user]\n name = Test User\n[alias]\n co = switch\n')
        real_run = subprocess.run

        def temporary_git(argv, **kwargs):
            # Older Git versions ignore GIT_CONFIG_GLOBAL. Route every command
            # explicitly to the fixture so tests cannot read/write user config.
            self.assertEqual(argv[:3], ["git", "config", "--global"])
            return real_run(["git", "config", "--file", str(config), *argv[3:]], **kwargs)

        with patch("subprocess.run", side_effect=temporary_git), contextlib.redirect_stdout(io.StringIO()):
            configuration.configure("git-aliases")
            before = config.read_text()
            configuration.configure("git-aliases")
        self.assertEqual(config.read_text(), before)
        self.assertIn("name = Test User", before)
        self.assertIn("co = switch", before)
        self.assertIn("unstage = reset HEAD", before)

    def test_tmux_existing_unrelated_path_is_preserved(self):
        path = self.root / ".tmux/plugins/tpm"
        path.mkdir(parents=True)
        marker = path / "personal"
        marker.write_text("keep")
        with self.assertRaisesRegex(catalog.SetupError, "not the expected checkout"), patch(
            "subprocess.run", side_effect=AssertionError("must not clone over existing directory")
        ):
            configuration.configure("tmux-plugins")
        self.assertEqual(marker.read_text(), "keep")

    def test_tmux_clone_is_explicit_and_mocked(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            configuration.configure("tmux-plugins")
        self.assertEqual(run.call_args.args[0], ["git", "clone", configuration.TPM_URL,
                                               str(self.root / ".tmux/plugins/tpm")])


if __name__ == "__main__":
    unittest.main()
