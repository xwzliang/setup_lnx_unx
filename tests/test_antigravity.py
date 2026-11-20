import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('app_installer', ROOT / 'packages/antigravity-app/scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class AntigravityTests(unittest.TestCase):
    def archive(self, name='Antigravity-x64/antigravity'):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as bundle:
            entry = tarfile.TarInfo(name)
            entry.mode = 0o755
            content = b'#!/bin/sh\nexit 0\n'
            entry.size = len(content)
            bundle.addfile(entry, io.BytesIO(content))
        data.seek(0)
        return data

    def run_install(self, home, archive):
        with patch.object(installer.Path, 'home', return_value=home), patch.object(installer.platform, 'system', return_value='Linux'), patch.object(installer.platform, 'machine', return_value='x86_64'), patch.object(installer.urllib.request, 'urlopen', return_value=archive):
            installer.install()

    def test_replaces_existing_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = home / '.local/share/antigravity'
            old.mkdir(parents=True)
            (old / 'old-file').write_text('old')
            launcher = home / 'bin/antigravity'
            launcher.parent.mkdir()
            launcher.symlink_to(old / 'antigravity')
            self.run_install(home, self.archive())
            self.assertFalse((old / 'old-file').exists())
            self.assertEqual(launcher.resolve(), old / 'antigravity')
            self.assertTrue(os.access(launcher, os.X_OK))
            self.assertIn(str(old / 'antigravity'), (home / '.local/share/applications/antigravity.desktop').read_text())

    def test_unsafe_archive_leaves_old_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            old = home / '.local/share/antigravity'
            old.mkdir(parents=True)
            (old / 'old-file').write_text('old')
            with self.assertRaises(tarfile.FilterError):
                self.run_install(home, self.archive('../../escape'))
            self.assertEqual((old / 'old-file').read_text(), 'old')

    def test_cli_native_update_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            agy = folder / 'agy'
            agy.write_text('#!/bin/sh\necho "$1" >> "$AGY_TEST_LOG"\nif [ "$1" = update ]; then exit "${AGY_TEST_STATUS:-0}"; fi\n')
            agy.chmod(0o755)
            log = folder / 'calls'
            env = dict(os.environ, PATH=f'{folder}:/usr/bin:/bin', AGY_TEST_LOG=str(log))
            script = ROOT / 'packages/agy/scripts/update.sh'
            result = subprocess.run(['bash', str(script)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ['--version', 'update', '--version'])
            log.unlink()
            result = subprocess.run(['bash', str(script)], env=dict(env, AGY_TEST_STATUS='7'), capture_output=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(log.read_text().splitlines(), ['--version', 'update'])
