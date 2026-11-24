"""Exercise the updater with fake Codex/curl; never download or install software."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'packages/codex/scripts/update.sh'

class CodexUpdateTests(unittest.TestCase):
    def test_standalone_update_and_download_failure(self):
        for status in (0, 22):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = root / 'packages/standalone/version/bin/codex'
                binary.parent.mkdir(parents=True)
                binary.write_text('#!/bin/sh\necho fixture-version\n')
                binary.chmod(0o755)
                (root / 'codex').symlink_to(binary)
                curl = root / 'curl'
                curl.write_text('#!/bin/sh\nwhile [ "$1" != --output ]; do shift; done\n'
                                'printf "echo fixture-installer\\n" > "$2"\n'
                                f'exit {status}\n')
                curl.chmod(0o755)
                result = subprocess.run(['bash', str(SCRIPT)], env=dict(os.environ, PATH=str(root)+':/usr/bin:/bin'), capture_output=True, text=True)
                self.assertEqual(result.returncode, status)
                self.assertEqual('fixture-installer' in result.stdout, status == 0)

    def test_refuses_other_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'codex'
            binary.write_text('#!/bin/sh\nexit 99\n')
            binary.chmod(0o755)
            result = subprocess.run(['bash', str(SCRIPT)], env=dict(os.environ, PATH=directory+':/usr/bin:/bin'), capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('standalone', result.stderr)
