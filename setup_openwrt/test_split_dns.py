import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from install_openclash_split_dns import worker, RESTORE, WATCH, HOOK_TEXT

HERE = Path(__file__).resolve().parent

class SplitDNS(unittest.TestCase):
    def config(self):
        return {'proxy-groups':[{'name':'SG','type':'select','proxies':['node']}],
                'proxies':[{'name':'node','type':'ss'}],
                'dns':{'nameserver':['223.5.5.5'],'fallback':['8.8.8.8'],
                       'nameserver-policy':{'+.example.com':'119.29.29.29'},
                       'proxy-server-nameserver-policy':{'+.example.com':'119.29.29.29'},
                       'fake-ip-filter':['+.example.com']},
                'rules':['DOMAIN,foreign.example,DIRECT','DOMAIN,protected.example,SG',
                         'IP-CIDR,17.0.0.0/8,DIRECT','GEOIP,CN,DIRECT','MATCH,DIRECT']}

    def transform(self, c, group='SG'):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'config.yaml'
            opts=Path(td)/'settings.yaml'
            path.write_text(json.dumps(c)); opts.write_text(json.dumps({'proxy_group':group}))
            r=subprocess.run(['ruby',str(HERE/'split_dns.rb'),str(path),str(opts)],capture_output=True,text=True)
            data=subprocess.check_output(['ruby','-ryaml','-rjson','-e','puts JSON.generate(YAML.load_file(ARGV[0]))',str(path)],text=True)
            return r.returncode,json.loads(data)

    def test_explicit_foreign_direct_preserved_unknown_proxied(self):
        rc,c=self.transform(self.config())
        self.assertEqual(rc,0)
        self.assertEqual(c['rules'][:2],self.config()['rules'][:2])
        self.assertIn('IP-CIDR,17.0.0.0/8,DIRECT,no-resolve',c['rules'])
        self.assertNotIn('GEOIP,CN,DIRECT',c['rules'])
        self.assertEqual(c['rules'][-2:],['GEOSITE,cn,DIRECT','MATCH,SG'])

    def test_no_inherited_dns_escape_and_idempotence(self):
        rc,c=self.transform(self.config())
        d=c['dns']
        self.assertEqual(d['nameserver'],['https://1.1.1.1/dns-query#SG'])
        self.assertEqual(d['direct-nameserver'],['https://223.5.5.5/dns-query#DIRECT'])
        self.assertEqual(d['proxy-server-nameserver'],d['direct-nameserver'])
        for k in ['fallback','nameserver-policy','proxy-server-nameserver-policy']:
            self.assertNotIn(k,d)
        self.assertEqual(self.transform(c),(0,c))

    def test_direct_fallback_rejected_even_nested(self):
        c=self.config()
        c['proxy-groups'].append({'name':'nested','proxies':['node','DIRECT']})
        c['proxy-groups'][0]['proxies']=['nested']
        rc,result=self.transform(c)
        self.assertNotEqual(rc,0)
        self.assertEqual(result['rules'],['MATCH,REJECT'])

    def test_missing_group_and_cycles_fail_closed(self):
        c=self.config()
        self.assertNotEqual(self.transform(c,'missing')[0],0)
        c['proxy-groups'][0]['proxies']=['SG']
        self.assertNotEqual(self.transform(c)[0],0)

    def test_ip_only_apps_get_domain_routing_without_destination_override(self):
        c=self.config()
        c['sniffer']={'enable':False, 'skip-domain':['Mijia Cloud'],
                      'sniff':{'HTTP':{'ports':[8888],'override-destination':True}}}
        rc,c=self.transform(c)
        self.assertEqual(rc,0)
        s=c['sniffer']
        self.assertTrue(s['enable'])
        self.assertTrue(s['parse-pure-ip'])
        self.assertFalse(s['override-destination'])
        self.assertFalse(s['force-dns-mapping'])
        self.assertEqual(s['skip-domain'],['Mijia Cloud'])
        self.assertIn(8888,s['sniff']['HTTP']['ports'])
        for protocol in ['HTTP','TLS','QUIC']:
            self.assertFalse(s['sniff'][protocol]['override-destination'])
        self.assertEqual(c['rules'][-1],'MATCH,SG')

    def test_workers_shell_syntax(self):
        for script in [worker(),worker(True),RESTORE,WATCH,HOOK_TEXT]:
            subprocess.run(['sh','-n'],input=script,text=True,check=True)

if __name__=='__main__': unittest.main()
