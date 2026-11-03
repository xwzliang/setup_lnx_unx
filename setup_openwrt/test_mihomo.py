import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_outage import client_address, probe
import install_mihomo as m


class UpgradeTests(unittest.TestCase):
    def test_pinned_architecture_selection(self):
        self.assertIn('amd64-compatible', m.release('x86_64')[0])
        self.assertIn('arm64', m.release('aarch64')[0])
        self.assertEqual(len(m.release('x86_64')[1]), 64)
        with self.assertRaises(ValueError):
            m.release('mips')

    def test_local_client_address_detection(self):
        self.assertEqual(client_address(None, None, '192.168.5.22'), '192.168.5.22')
        self.assertEqual(client_address('server', '192.168.5.103', None), '192.168.5.103')
        with self.assertRaises(ValueError):
            client_address(None, '192.168.5.99', '192.168.5.22')
        with self.assertRaises(ValueError):
            client_address('server', None, '192.168.5.22')

    def test_local_probe_binds_detected_address_without_ssh(self):
        with patch('test_outage.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='200', stderr='')) as run:
            self.assertEqual(probe(None, '192.168.5.22', 'https://example.com/'), (0, '200', ''))
            command = run.call_args.args[0]
            self.assertEqual(command[0], 'curl')
            self.assertEqual(command[command.index('--interface')+1], '192.168.5.22')

    def test_remote_probe_still_uses_ssh(self):
        with patch('test_outage.ssh', return_value=SimpleNamespace(returncode=0, stdout='200', stderr='')) as ssh:
            probe('server', '192.168.5.103', 'https://example.com/')
            self.assertEqual(ssh.call_args.args[0], 'server')
            self.assertIn('--interface 192.168.5.103', ssh.call_args.args[1])

    def exercise(self, failure=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for d in ['etc/openclash/core','etc/config','etc/init.d','etc/openclash-killswitch','usr/sbin','tmp/lock','stage','bin']:
            (root/d).mkdir(parents=True,exist_ok=True)
        for name in ['openclash','network','firewall','dhcp']:
            (root/'etc/config'/name).write_text('original '+name)
        (root/'etc/openclash/core/clash_meta').write_text('old core')
        (root/'etc/init.d/openclash').write_text('#!/bin/sh\n# enable_meta_core\nexit 0\n')
        (root/'etc/init.d/openclash').chmod(0o755)
        (root/'usr/sbin/openclash-killswitch').write_text('#!/bin/sh\nexit 0\n')
        (root/'usr/sbin/openclash-killswitch').chmod(0o755)
        tools = {
            'flock':'#!/bin/sh\nexit 0\n',
            'nohup':'#!/bin/sh\ntouch "$TEST_ROOT/watchdog-armed"\n',
            'uci':'''#!/bin/sh
case "$*" in
 'changes openclash') exit 0;;
 '-q get openclash.config.small_flash_memory') echo 0;;
 '-q get openclash.config.config_path') echo /etc/openclash/config/test.yaml;;
 set*) echo mutated >"$TEST_ROOT/etc/config/openclash";;
 *) exit 0;;
esac
''',
        }
        for name, content in tools.items():
            f=root/'bin'/name;f.write_text(content);f.chmod(0o755)
        core=b'#!/bin/sh\nif [ "$1" = -t ] && [ "$FAIL" = yes ]; then exit 1; fi\necho "Mihomo Meta v1.19.33"\n'
        (root/'stage/core.gz').write_bytes(gzip.compress(core))
        (root/'stage/validate-path').write_text('')
        env={**os.environ,'TEST_ROOT':str(root),'FAIL':'yes' if failure else 'no','PATH':str(root/'bin')+':'+os.environ['PATH']}
        def run(source, name):
            for prefix in ['/etc/', '/usr/sbin/', '/usr/share/', '/tmp/lock/']:
                source=source.replace(prefix,str(root)+prefix)
            source=source.replace('-C /\n','-C '+str(root)+'\n').replace('-C / ', '-C '+str(root)+' ')
            f=root/'stage'/name;f.write_text(source)
            return subprocess.run(['sh',str(f),str(f.parent)],env=env,capture_output=True)
        result=run(m.UPGRADE,'upgrade.sh')
        return root,result,run

    def test_preflight_failure_does_not_mutate_or_arm(self):
        root,result,_=self.exercise(True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((root/'etc/openclash/core/clash_meta').read_text(),'old core')
        self.assertEqual((root/'etc/config/openclash').read_text(),'original openclash')
        self.assertFalse((root/'stage/pending').exists())
        self.assertFalse((root/'watchdog-armed').exists())

    def test_upgrade_and_independent_rollback(self):
        root,result,run=self.exercise()
        self.assertEqual(result.returncode,0,(root/'stage/upgrade.log').read_text())
        self.assertTrue((root/'watchdog-armed').exists())
        self.assertEqual((root/'stage/result').read_text().strip(),'ready')
        self.assertIn('SAFE_PATHS=',(root/'etc/init.d/openclash').read_text())
        restored=run(m.RESTORE,'restore.sh')
        self.assertEqual(restored.returncode,0,(root/'stage/rollback.log').read_text())
        self.assertEqual((root/'etc/openclash/core/clash_meta').read_text(),'old core')
        self.assertEqual((root/'etc/config/openclash').read_text(),'original openclash')
        self.assertNotIn('SAFE_PATHS=',(root/'etc/init.d/openclash').read_text())
        self.assertFalse((root/'stage/pending').exists())


if __name__=='__main__':
    unittest.main()
