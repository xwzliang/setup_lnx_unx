import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

class Failover(unittest.TestCase):
    def run_transform(self, active='one.yaml', bad=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = {'proxies': [{'name': 'node', 'type': 'ss'}], 'proxy-groups': [
                {'name': '新加坡', 'type': 'url-test', 'proxies': ['node']},
                {'name': '🚀 节点选择', 'type': 'select', 'proxies': ['node', 'DIRECT']},
                {'name': '🎯 全球直连', 'type': 'select', 'proxies': ['DIRECT', '🚀 节点选择']},
                {'name': '🐟 漏网之鱼', 'type': 'select', 'proxies': ['DIRECT', '🚀 节点选择']},
                {'name': 'DIRECT selector', 'type': 'select', 'proxies': ['DIRECT', 'node']}],
                'rules': ['DOMAIN,domestic.example,DIRECT', 'MATCH,新加坡']}
            for file in ['one', 'two']:
                source = json.loads(json.dumps(config, ensure_ascii=False))
                if file == 'two':
                    source['proxy-groups'] = [g for g in source['proxy-groups'] if g['name'] not in ['🚀 节点选择', '🐟 漏网之鱼', '🎯 全球直连']]
                if bad and file == 'two':
                    source['proxy-groups'][0]['proxies'] = ['DIRECT']
                (root/(file+'.yaml')).write_text(json.dumps(source, ensure_ascii=False))
            (root/'runtime.yaml').write_text(json.dumps(config, ensure_ascii=False))
            code = '''require 'json'; require ARGV.shift
c=YAML.load_file(ARGV[0]); original=Marshal.load(Marshal.dump(c)); mapping={'ONE'=>'one','TWO'=>'two'}
ProviderFailover.apply(c,mapping,ARGV[1],ARGV[2]); first=Marshal.load(Marshal.dump(c))
ProviderFailover.apply(c,mapping,ARGV[1],ARGV[2]); abort 'not idempotent' unless first==c
abort 'rules changed' unless c['rules']==original['rules']
puts JSON.generate(c)
'''
            result = subprocess.run(['ruby', '-e', code, str(HERE/'provider_failover.rb'), str(root/'runtime.yaml'), active, td], text=True, capture_output=True)
            return result

    def test_preferred_order_regions_and_idempotence(self):
        for active, preferred in [('one.yaml', 'ONE'), ('two.yaml', 'TWO')]:
            r = self.run_transform(active)
            self.assertEqual(r.returncode, 0, r.stderr)
            c = json.loads(r.stdout)
            g = c['proxy-groups'][0]
            self.assertEqual(g['type'], 'fallback')
            self.assertTrue(g['proxies'][0].startswith('setup-failover/'+preferred+'/'))
            self.assertFalse(g['lazy'])
            groups = {g['name']: g for g in c['proxy-groups']}
            self.assertEqual(groups['DIRECT selector']['proxies'], ['DIRECT', 'node'])
            self.assertEqual(groups['🎯 全球直连']['proxies'], ['DIRECT'])
            for name in ['🚀 节点选择', '🐟 漏网之鱼']:
                self.assertEqual(groups[name]['type'], 'fallback')
                self.assertEqual(len(groups[name]['proxies']), 2)
                self.assertNotIn('DIRECT', groups[name]['proxies'])
            self.assertEqual(len(c['proxies']), 3)

    def test_invalid_active_or_direct_backup_rejected(self):
        self.assertNotEqual(self.run_transform('unknown.yaml').returncode, 0)
        self.assertNotEqual(self.run_transform(bad=True).returncode, 0)

if __name__ == '__main__': unittest.main()
