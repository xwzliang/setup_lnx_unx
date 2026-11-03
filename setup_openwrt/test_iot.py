import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
FAKE_UCI='''#!/usr/bin/env python3
import json,os,sys
p=os.environ['UCI_STATE']; s=json.load(open(p)); a=[x for x in sys.argv[1:] if x!='-q']; cmd=a[0]
if cmd=='changes':print('')
elif cmd=='show':
 for k,v in s.items():
  if k.startswith('dhcp.') and v=='host': print(k+'=host')
elif cmd=='get':
 if a[1] not in s:sys.exit(1)
 print(s[a[1]])
elif cmd=='set':
 k,v=a[1].split('=',1); s[k]=v; json.dump(s,open(p,'w'))
elif cmd=='commit':pass
else:sys.exit(2)
'''

class Reservations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'uci').write_text(FAKE_UCI); (self.root/'uci').chmod(0o755)
        self.state=self.root/'state.json'
        self.base={'network.lan.ipaddr':'192.168.5.1','network.lan.netmask':'255.255.255.0',
                   'dhcp.existing':'host','dhcp.existing.ip':'192.168.5.100','dhcp.existing.mac':'aa:bb:cc:dd:ee:00'}
        self.state.write_text(json.dumps(self.base))
        self.leases=self.root/'leases'; self.leases.write_text('0 aa:bb:cc:dd:ee:02 192.168.5.135 gateway *\n')
        self.inventory=self.root/'iot.json'
        self.devices=[{'ip':'192.168.5.135','mac':'aa:bb:cc:dd:ee:02'}]
        self.env=dict(os.environ,PATH=str(self.root)+':'+os.environ['PATH'],UCI_STATE=str(self.state),IOT_LEASES=str(self.leases))
    def run_script(self,mode):
        self.inventory.write_text(json.dumps({'devices':self.devices}))
        return subprocess.run(['ruby',str(HERE/'iot_reservations.rb'),str(self.inventory),mode],env=self.env,capture_output=True,text=True)
    def test_check_no_mutation_then_idempotent_apply(self):
        self.assertEqual(self.run_script('check').returncode,0)
        self.assertEqual(json.loads(self.state.read_text()),self.base)
        self.assertEqual(self.run_script('apply').returncode,0)
        applied=self.state.read_text()
        self.assertEqual(self.run_script('apply').returncode,0)
        self.assertEqual(self.state.read_text(),applied)
        self.assertEqual(self.run_script('verify').returncode,0)
        self.assertEqual(json.loads(applied)['dhcp.existing.mac'],self.base['dhcp.existing.mac'])
    def test_reservation_conflict_aborts_before_any_write(self):
        self.devices.append({'ip':'192.168.5.100','mac':'aa:bb:cc:dd:ee:04'})
        self.assertNotEqual(self.run_script('apply').returncode,0)
        self.assertEqual(json.loads(self.state.read_text()),self.base)
    def test_stale_lease_duplicate_and_router_ip_rejected(self):
        for devices in [[{'ip':'192.168.5.140','mac':'aa:bb:cc:dd:ee:02'}],self.devices*2,
                        [{'ip':'192.168.5.1','mac':'aa:bb:cc:dd:ee:02'}]]:
            self.devices=devices
            self.assertNotEqual(self.run_script('apply').returncode,0)
            self.assertEqual(json.loads(self.state.read_text()),self.base)
    def test_offline_existing_reservation_preserved(self):
        self.assertEqual(self.run_script('apply').returncode,0)
        self.leases.write_text('')
        self.assertEqual(self.run_script('apply').returncode,0)

if __name__=='__main__':unittest.main()
