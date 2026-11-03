"""Exercise deployment branches without Docker, network access, or a real router."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SubconverterTests(unittest.TestCase):
    def run_installer(self, scenario, *options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "commands.jsonl"
            config = root / "config"
            fake = '''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
a=sys.argv[1:]
with open(os.environ['FAKE_LOG'],'a') as f: f.write(json.dumps([name]+a)+'\\n')
case=os.environ['FAKE_CASE']
if name=='ssh': os.execv('/bin/sh',['sh','-c',a[-1]])
if name=='curl': print('subconverter v0.9.9 backend'); sys.exit(0)
if a[:2]==['container','inspect']: sys.exit(1 if case=='new' else 0)
if a[:2]==['inspect','--format']:
    t=a[2]
    if '.Config.Image' in t: print('other/image:1' if case=='conflict' else 'xwzliang/subconverter-custom:0.0.2')
    elif '.RestartPolicy' in t: print('always')
    elif '.NetworkMode' in t: print('default')
    elif '.Privileged' in t: print('false')
    elif '.PortBindings' in t: print('0.0.0.0:15051:25500/tcp')
    elif '.Mounts' in t: print('bind|'+os.environ['FAKE_CONFIG']+'|/data|true')
    elif '.State.Running' in t: print('false' if case=='stopped' else 'true')
    else: sys.exit(2)
'''
            for name in ("ssh", "docker", "curl"):
                path = root / name
                path.write_text(fake)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ["PATH"],
                       FAKE_CASE=scenario, FAKE_LOG=str(log), FAKE_CONFIG=str(config))
            result = subprocess.run(["bash", str(Path(__file__).with_name("install_subconverter.sh")),
                                     "--config-dir", str(config), *options],
                                    env=env, capture_output=True, text=True, timeout=10)
            commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, commands, str(config)

    def test_new_deployment_matches_current_router(self):
        r, commands, config = self.run_installer("new", "--router", "192.168.8.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("root@192.168.8.1", commands[0])
        run = next(c for c in commands if c[:2] == ["docker", "run"])
        self.assertIn("0.0.0.0:15051:25500/tcp", run)
        self.assertIn("type=bind,src="+config+",dst=/data", run)
        self.assertIn("always", run)
        self.assertEqual(run[-1], "xwzliang/subconverter-custom:0.0.2")

    def test_matching_container_is_not_restarted(self):
        r, commands, _ = self.run_installer("existing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("root@192.168.5.1", commands[0])
        self.assertFalse(any(c[:2] in (["docker", "run"], ["docker", "start"], ["docker", "pull"]) for c in commands))

    def test_stopped_matching_container_is_started(self):
        r, commands, _ = self.run_installer("stopped")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(["docker", "start", "subconverter"], commands)

    def test_conflict_fails_without_mutating_container(self):
        r, commands, _ = self.run_installer("conflict")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("left unchanged", r.stderr)
        self.assertFalse(any(c[0] == "docker" and c[1] in ("run", "start", "stop", "rm", "pull") for c in commands))

    def test_shell_metacharacters_are_rejected_before_ssh(self):
        r, commands, _ = self.run_installer("new", "--image", "image;reboot")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
