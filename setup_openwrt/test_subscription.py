import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import install_openclash_subscription as sub


class SubscriptionTests(unittest.TestCase):
    def test_env_literal_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('SUBSCRIPTIONS="ONE TWO"\nACTIVE_SUBSCRIPTION=ONE\nSUB_ONE_URL="https://one.example/a?x=$(id)&k=abc"\nSUB_TWO_URL=https://two.example/sub\n')
            env = sub.read_env(path)
            entries, active, config = sub.settings(env, ['TWO'], False)
            self.assertEqual(entries[0][0], 'TWO')
            self.assertEqual(active, 'ONE')
            self.assertIn('$(id)', env['SUB_ONE_URL'])
            self.assertEqual(len(sub.settings(env, [], True)[0]), 2)
            with self.assertRaises(ValueError):
                sub.settings(env, ['MISSING'], False)
            env['SUB_TWO_CONFIG'] = 'ONE'
            with self.assertRaises(ValueError):
                sub.settings(env, [], True)

    def run_worker(self, failure='', check_only=False, count=1, activate=False, existing=False, switch_only=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for path in ['etc/config', 'etc/openclash/config', 'etc/openclash/backup', 'etc/init.d', 'tmp/lock', 'lib', 'bin', 'stage']:
            (root / path).mkdir(parents=True, exist_ok=True)
        (root / 'etc/config/openclash').write_text('original uci')
        for name in ['one', 'two']:
            (root / f'etc/openclash/config/{name}.yaml').write_text('original ' + name)
            (root / f'etc/openclash/backup/{name}.yaml').write_text('old backup ' + name)
        helpers = 'config_load() { :; }; config_foreach() { :; }\n'
        if existing:
            helpers = 'config_load() { :; }; config_get() { entry_name=$wanted; }; config_foreach() { local section=cfg123; "$1" "$section"; }\n'
        (root / 'lib/functions.sh').write_text(helpers)
        scripts = {
            'flock': '#!/bin/sh\nexit 0\n',
            'ruby': '#!/bin/sh\n[ "$FAIL" != validation ]\n',
            'curl': '''#!/bin/sh
agent=
while [ "$#" -gt 0 ]; do
  if [ "$1" = -A ]; then shift; agent=$1; fi
  if [ "$1" = -o ]; then shift; out=$1; fi
  shift
done
printf "%s\n" "$agent" >>"$TEST_ROOT/agents"
printf converted >"$out"
if [ "$FAIL" = fallback ] && [ "$agent" = Clash ]; then printf 403; exit 0; fi
if [ "$FAIL" = fetch ] || { [ "$FAIL" = second ] && [ "$out" = candidates/two.yaml ]; }; then printf 403; else printf 200; fi
''',
            'uci': '''#!/bin/sh
case "$*" in
  'changes openclash') exit 0 ;;
  '-q get openclash.config.config_path') echo /different.yaml ;;
  '-q get '*) exit 1 ;;
  batch) cat >"$TEST_ROOT/batch" ;;
  'revert openclash') exit 0 ;;
  'commit openclash') echo changed >"$TEST_ROOT/etc/config/openclash"; [ "$FAIL" != commit ] ;;
  *) exit 1 ;;
esac
''',
        }
        for name, script in scripts.items():
            path = root / 'bin' / name
            path.write_text(script)
            path.chmod(0o755)
        core = root / 'etc/openclash/clash'
        core.write_text('#!/bin/sh\n[ "$FAIL" != core ]\n')
        core.chmod(0o755)
        entries = [('ONE', 'one', "https://one.example/sub?a='x'&b=$(touch PWNED)", sub.TEMPLATE)]
        if count == 2:
            entries.append(('TWO', 'two', 'https://two.example/sub', sub.TEMPLATE))
        init = root / 'etc/init.d/openclash'
        init.write_text('#!/bin/sh\nexit 1\n')
        init.chmod(0o755)
        if failure == 'restart_success':
            init.write_text('#!/bin/sh\nexit 0\n')
            pidof = root / 'bin/pidof'
            pidof.write_text('#!/bin/sh\necho 123\n')
            pidof.chmod(0o755)
            (root / 'proc/123').mkdir(parents=True)
            (root / 'proc/123/cmdline').write_bytes(b'clash\0-f\0' + str(root / 'etc/openclash/one.yaml').encode() + b'\0')
            uci = root / 'bin/uci'
            uci.write_text(uci.read_text().replace('echo /different.yaml', 'echo ' + str(root / 'etc/openclash/config/one.yaml')))
        script = sub.worker(entries, 'ONE' if activate else 'OTHER', 'one' if activate else 'other', 15051, check_only, switch_only)
        for prefix in ['/etc/', '/lib/', '/tmp/lock/', '/proc/']:
            script = script.replace(prefix, str(root) + prefix)
        run = root / 'stage/run.sh'
        run.write_text(script)
        result = subprocess.run(['sh', str(run), str(run.parent)], env={**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'], 'FAIL': failure, 'TEST_ROOT': str(root)}, capture_output=True)
        self.assertFalse((run.parent / 'PWNED').exists())
        return root, result

    def test_success_backups_and_quoting(self):
        root, result = self.run_worker(count=2)
        self.assertEqual(result.returncode, 0, (root / 'stage/worker.log').read_text())
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'converted')
        backup = root / ('stage/backup' + str(root) + '/etc/openclash/config/one.yaml')
        self.assertEqual(backup.read_text(), 'original one')
        self.assertEqual((root / 'stage/backup/openclash').read_text(), 'original uci')
        self.assertIn('$(touch PWNED)', (root / 'batch').read_text())
        self.assertEqual((root / 'stage/result').read_text().strip(), 'installed')

    def test_failures_leave_configs_unchanged(self):
        for failure in ['fetch', 'validation', 'core', 'second', 'commit']:
            with self.subTest(failure=failure):
                root, result = self.run_worker(failure, count=2)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
                self.assertEqual((root / 'etc/config/openclash').read_text(), 'original uci')
                self.assertEqual((root / 'etc/openclash/backup/one.yaml').read_text(), 'old backup one')

    def test_existing_section_with_openwrt_dynamic_scope(self):
        root, result = self.run_worker(existing=True)
        self.assertEqual(result.returncode, 0, (root / 'stage/worker.log').read_text())
        batch = (root / 'batch').read_text()
        self.assertIn('openclash.cfg123.name=', batch)
        self.assertNotIn('=config_subscribe', batch)

    def test_restart_failure_restores_config(self):
        root, result = self.run_worker(activate=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
        self.assertEqual((root / 'etc/config/openclash').read_text(), 'original uci')
        self.assertEqual((root / 'stage/result').read_text().strip(), 'rolled-back')

    def test_user_agent_fallback_and_cleanup(self):
        root, result = self.run_worker('fallback')
        self.assertEqual(result.returncode, 0, (root / 'stage/worker.log').read_text())
        self.assertEqual((root / 'agents').read_text().splitlines()[:2], ['Clash', 'Quantumultx'])
        self.assertFalse(list((root / 'etc/openclash/config').glob('.subscription-fetch.*')))
        self.assertIn('/data/${fetch_dir##*/}/source.yaml', (root / 'stage/run.sh').read_text())

    def test_switch_only_needs_no_urls(self):
        entries, active, config = sub.settings(
            {'SUBSCRIPTIONS': 'ONE TWO', 'ACTIVE_SUBSCRIPTION': 'TWO'},
            ['TWO'], False, require_urls=False)
        self.assertEqual(entries, [('TWO', 'TWO', '', '')])
        self.assertEqual(active, 'TWO')

    def test_switch_only_validation_skips_fetch_and_conversion(self):
        root, result = self.run_worker(check_only=True, activate=True, switch_only=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((root / 'agents').exists())
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
        self.assertFalse((root / 'batch').exists())

    def test_switch_only_success_preserves_yaml_and_backs_up_settings(self):
        root, result = self.run_worker('restart_success', activate=True, switch_only=True)
        self.assertEqual(result.returncode, 0, (root / 'stage/worker.log').read_text())
        self.assertEqual((root / 'stage/result').read_text().strip(), 'installed')
        self.assertEqual((root / 'stage/backup/openclash').read_text(), 'original uci')
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
        self.assertFalse((root / 'agents').exists())

    def test_switch_only_invalid_config_leaves_settings(self):
        root, result = self.run_worker('core', activate=True, switch_only=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / 'batch').exists())
        self.assertEqual((root / 'etc/config/openclash').read_text(), 'original uci')

    def test_switch_only_restart_failure_restores_settings(self):
        root, result = self.run_worker(activate=True, switch_only=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((root / 'agents').exists())
        self.assertEqual((root / 'etc/config/openclash').read_text(), 'original uci')
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
        batch = (root / 'batch').read_text()
        self.assertIn('config.config_path=', batch)
        self.assertNotIn('.address=', batch)

    def test_check_only_does_not_write(self):
        root, result = self.run_worker(check_only=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((root / 'etc/openclash/config/one.yaml').read_text(), 'original one')
        self.assertFalse((root / 'batch').exists())


if __name__ == '__main__':
    unittest.main()
