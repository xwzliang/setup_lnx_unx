import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import update_openclash_rules as rules


@unittest.skipUnless(shutil.which('ruby'), 'Ruby required for YAML validation tests')
class RulesTests(unittest.TestCase):
    def run_update(self, mode='', check_only=False):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        for d in ['etc/openclash/custom','etc/config','etc/init.d','lib','tmp/lock','bin','stage']:
            (root/d).mkdir(parents=True,exist_ok=True)
        old='- DOMAIN,old.test,DIRECT\n'
        new=old if mode=='same' else '- DOMAIN,new.test,DIRECT\n'
        if mode=='invalid': new='rules: invalid\n'
        (root/'stage/rules.yaml').write_text(new)
        (root/'etc/openclash/custom/openclash_custom_rules.list').write_text(old)
        (root/'etc/openclash/live.yaml').write_text('rules:\n'+old+'- MATCH,DIRECT\n')
        (root/'etc/config/openclash').write_text('old settings')
        (root/'lib/functions.sh').write_text('config_load() { :; };\n')
        scripts={
            'bin/flock':'#!/bin/sh\nexit 0\n',
            'bin/pidof':'#!/bin/sh\necho 123\n',
            'bin/uci':'''#!/bin/sh
case "$*" in
  'changes openclash') exit 0;;
  '-q get openclash.config.config_path') echo /etc/openclash/config/live.yaml;;
  '-q get openclash.config.enable_custom_clash_rules') echo 1;;
  set*) echo new >"$TEST_ROOT/etc/config/openclash";;
  *) exit 0;;
esac
''',
            'etc/openclash/clash':'#!/bin/sh\n[ "$MODE" != core-fail ]\n',
            'etc/init.d/openclash':'''#!/bin/sh
echo restart >>"$TEST_ROOT/restarts"
[ "$MODE" != restart-fail ] || exit 1
cp candidate.yaml "$TEST_ROOT/etc/openclash/live.yaml"
''',
        }
        for path,source in scripts.items():
            f=root/path; f.write_text(source); f.chmod(0o755)
        script=rules.worker(check_only)
        for prefix in ['/etc/','/usr/sbin/','/lib/','/tmp/lock/']:
            script=script.replace(prefix,str(root)+prefix)
        f=root/'stage/run.sh'; f.write_text(script)
        r=subprocess.run(['sh',str(f),str(f.parent)],capture_output=True,env={**os.environ,'TEST_ROOT':str(root),'MODE':mode,'PATH':str(root/'bin')+':'+os.environ['PATH']})
        return root,r

    def test_install_backs_up_and_applies_rules(self):
        root,r=self.run_update()
        self.assertEqual(r.returncode,0,(root/'stage/worker.log').read_text())
        self.assertEqual((root/'stage/result').read_text().strip(),'installed')
        self.assertIn('new.test',(root/'etc/openclash/custom/openclash_custom_rules.list').read_text())
        self.assertEqual((root/'stage/backup/openclash').read_text(),'old settings')
        backup=root/('stage/backup'+str(root)+'/etc/openclash/custom/openclash_custom_rules.list')
        self.assertIn('old.test',backup.read_text())

    def test_validation_and_restart_failures_preserve_old_rules(self):
        for mode in ['invalid','core-fail','restart-fail']:
            with self.subTest(mode=mode):
                root,r=self.run_update(mode)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('old.test',(root/'etc/openclash/custom/openclash_custom_rules.list').read_text())
                self.assertEqual((root/'etc/config/openclash').read_text(),'old settings')

    def test_unchanged_rules_do_not_restart(self):
        root,r=self.run_update('same')
        self.assertEqual(r.returncode,0,(root/'stage/worker.log').read_text())
        self.assertEqual((root/'stage/result').read_text().strip(),'unchanged')
        self.assertFalse((root/'restarts').exists())

    def test_check_only_does_not_change_settings(self):
        root,r=self.run_update(check_only=True)
        self.assertEqual(r.returncode,0,(root/'stage/worker.log').read_text())
        self.assertIn('old.test',(root/'etc/openclash/custom/openclash_custom_rules.list').read_text())
        self.assertFalse((root/'restarts').exists())


if __name__=='__main__': unittest.main()
