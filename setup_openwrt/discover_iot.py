#!/usr/bin/env python3
"""Match DHCP leases to Home Assistant/Xiaomi identity via miIO hello or cloud MAC."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess

HA_EXPORT = r'''
import json
from pathlib import Path
result={}
for p in Path('/config/.storage/xiaomi_home/miot_devices').glob('*.dict'):
    data,_=json.JSONDecoder().raw_decode(p.read_bytes().decode(errors='ignore'))
    for did,v in data.items():
        # Never export tokens, nested sub_devices, account or Wi-Fi credentials.
        result[did]={k:v.get(k) for k in ('did','name','model','parent_id','connect_type')}
# Optional live inventory refresh. Authentication remains on the HA host.
if REFRESH_CLOUD:
    import urllib.request, ast
    consts={}
    tree=ast.parse(Path('/config/custom_components/xiaomi_home/miot/const.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name):
            try:consts[node.target.id]=ast.literal_eval(node.value)
            except (ValueError,TypeError):pass
    entries=json.loads(Path('/config/.storage/core.config_entries').read_text())['data']['entries']
    for entry in entries:
        if entry.get('domain')!='xiaomi_home':continue
        cfg=entry['data']; region=cfg['cloud_server']
        if region not in ('cn','de','i2','ru','sg','us'):raise ValueError('Unsupported Xiaomi region')
        authpath=Path('/config/.storage/xiaomi_home/miot_config')/(str(cfg['uid'])+'_'+region+'.dict')
        auth,_=json.JSONDecoder().raw_decode(authpath.read_bytes().decode(errors='ignore'))
        host=consts['DEFAULT_OAUTH2_API_HOST']
        if host!='ha.api.io.mi.com':raise ValueError('Unexpected Xiaomi API host')
        if region!='cn':host=region+'.'+host
        def request(path,body):
            headers={'Content-Type':'application/json','X-Client-BizId':'haapi',
                     'X-Client-AppId':consts['OAUTH2_CLIENT_ID'],
                     'Authorization':'Bearer'+auth['auth_info']['access_token']}
            req=urllib.request.Request('https://'+host+path,data=json.dumps(body).encode(),headers=headers)
            with urllib.request.urlopen(req,timeout=20) as response:data=json.load(response)
            if data.get('code')!=0:raise RuntimeError('Xiaomi inventory API failed; code '+str(data.get('code')))
            return data['result']
        homes=request('/app/v2/homeroom/gethome',{'limit':150,'fetch_share':True,'fetch_share_dev':True,'plat_form':0,'app_ver':9})
        rooms={}
        for home in homes.get('homelist',[])+homes.get('share_home_list',[]):
            for room in home.get('roomlist',[]):
                for did in room.get('dids',[]):rooms[str(did)]=room.get('name','')
        body={'limit':200,'get_split_device':True,'get_third_device':True,'dids':[]}
        for _ in range(20):
            page=request('/app/v2/home/device_list_page',body)
            for v in page.get('list',[]) or []:
                did=str(v.get('did',''))
                if not did:continue
                result[did]={k:v.get(k) for k in ('did','name','model','parent_id','mac')}
                result[did]['connect_type']=v.get('pid')
                result[did]['room']=rooms.get(did,'')
            if not page.get('has_more'):break
            body['start_did']=page['next_start_did']
        else:raise RuntimeError('Inventory pagination limit reached')
print(json.dumps(list(result.values()),ensure_ascii=False))
'''

def ssh(host, command, data=None):
    if not re.fullmatch(r'[A-Za-z0-9_@.:-]+',host) or host.startswith('-'):
        raise ValueError('Invalid SSH host')
    return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,command],
                          input=data,text=True,capture_output=True,check=True,timeout=30).stdout

def hello(ip):
    ipaddress.IPv4Address(ip)
    for _ in range(2):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            try:
                s.sendto(bytes.fromhex('21310020')+b'\xff'*28,(ip,54321))
                packet,source=s.recvfrom(2048)
                if source[0]==ip and source[1]==54321 and len(packet)>=32 and packet[:2]==b'!1':
                    return str(struct.unpack('!I',packet[8:12])[0])
            except (socket.timeout,OSError):
                pass
    return None

def discover(router, ha, refresh_cloud=False):
    devices=json.loads(ssh(ha,'python3 -','REFRESH_CLOUD='+repr(refresh_cloud)+'\n'+HA_EXPORT))
    by_did={d['did']:d for d in devices}
    leases=[]
    for line in ssh('root@'+router,'cat /tmp/dhcp.leases').splitlines():
        a=line.split()
        if len(a)>=4:
            leases.append({'mac':a[1].lower(),'ip':str(ipaddress.IPv4Address(a[2])),'hostname':a[3]})
    with ThreadPoolExecutor(max_workers=12) as pool:
        dids=list(pool.map(hello,[x['ip'] for x in leases]))
    matched=[]
    for lease,did in zip(leases,dids):
        d=by_did.get(did)
        evidence='HA Xiaomi device ID = live miIO hello ID; MAC/IP from active DHCP lease'
        if d is None and did is None:
            candidates=[v for v in devices if v.get('connect_type')==0 and
                        str(v.get('mac','')).lower()==lease['mac']]
            if len(candidates)==1:
                d=candidates[0]
                evidence='Live Xiaomi cloud Wi-Fi MAC = active DHCP MAC; no miIO hello response'
        if d is not None and not str(d.get('model','')).startswith('miwifi.'):
            matched.append(dict(lease,did=d['did'],name=d['name'],model=d['model'],room=d.get('room',''),evidence=evidence))
    known={x['did']:x for x in matched}
    children=[]
    for d in devices:
        if d.get('parent_id') or str(d['did']).startswith('blt.'):
            parent=known.get(d.get('parent_id'))
            children.append(dict(d,gateway_ip=parent['ip'] if parent else None))
    return {'version':1,'devices':matched,'gateway_children':children,
            'unmatched_devices':[d for d in devices if d['did'] not in known and not d.get('parent_id') and not str(d['did']).startswith('blt.')],
            'note':'Only devices matched by live miIO identity or exact cloud Wi-Fi MAC and DHCP lease are selected. BLE sensors have no DHCP IP; unspecified BLE gateway associations are not inferred.'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--router',default='192.168.5.1')
    p.add_argument('--ha',default='ha',help='Home Assistant SSH alias, with /config readable')
    p.add_argument('--refresh-cloud',action='store_true',help='Read current Xiaomi inventory through HA credentials; credentials never leave HA except to Xiaomi')
    p.add_argument('--output',type=Path,default=Path(__file__).with_name('iot_devices.json'))
    a=p.parse_args()
    result=discover(a.router,a.ha,a.refresh_cloud)
    fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    os.chmod(a.output,0o600)
    for d in result['devices']:print(d['ip'],d['name'],d['model'])
    print('Confirmed devices:',len(result['devices']),'Private inventory:',a.output)

if __name__=='__main__':main()
