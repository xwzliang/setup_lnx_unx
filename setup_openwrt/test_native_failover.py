#!/usr/bin/env python3
"""Test installed Mihomo fallback/failback in an isolated core; no Internet probes."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from install_openclash_killswitch import Installer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router', default='192.168.5.1')
    parser.add_argument('--port', type=int, default=22)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', args.router) or not 1 <= args.port <= 65535:
        parser.error('Invalid router or SSH port')
    servers = []
    with tempfile.TemporaryDirectory(prefix='oc-native-test-') as temp:
        remote = Installer(args, Path(temp)/'ssh')
        stage = None
        try:
            remote.connect()
            occupied = remote.remote("netstat -lnt | awk '$4 ~ /:1929[78]$/ {print $4}'")
            if occupied:
                raise RuntimeError('Isolated test ports 19297/19298 are already in use')
            nodes = []
            for name in ['preferred-one', 'preferred-two', 'backup']:
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        self.send_response(204 if self.server.healthy else 503)
                        self.end_headers()
                    def do_CONNECT(self):
                        self.send_response(200)
                        self.end_headers()
                        self.connection.settimeout(3)
                        while self.rfile.readline().strip():
                            pass
                        status = b"204 No Content" if self.server.healthy else b"503 Unavailable"
                        self.connection.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    def log_message(self, *args):
                        pass
                server = ThreadingHTTPServer((remote.client_ip, 0), Handler)
                server.healthy = True
                servers.append(server)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                nodes.append({'name': name, 'type': 'http', 'server': remote.client_ip, 'port': server.server_port})
            health = {'url': 'http://example.invalid/health', 'interval': 1,
                      'lazy': False, 'timeout': 1000, 'expected-status': '204'}
            config = {'mixed-port': 19298, 'bind-address': '127.0.0.1',
                      'external-controller': '127.0.0.1:19297', 'mode': 'rule',
                      'log-level': 'error', 'ipv6': False, 'proxies': nodes,
                      'proxy-groups': [
                          dict(health, name='preferred', type='url-test', proxies=['preferred-one', 'preferred-two']),
                          dict(health, name='backup-provider', type='url-test', proxies=['backup']),
                          dict(health, name='regional', type='fallback', proxies=['preferred', 'backup-provider'])],
                      'rules': ['MATCH,regional'], 'profile': {'store-selected': False}}
            stage = remote.remote('umask 077; mktemp -d /tmp/native-failover.XXXXXX')
            if not re.fullmatch(r'/tmp/native-failover\.[A-Za-z0-9]+', stage):
                stage = None
                raise RuntimeError('Unexpected test staging directory')
            remote.remote('cat >'+stage+'/config.yaml', json.dumps(config))
            remote.remote(f'nohup /etc/openclash/core/clash_meta -d {stage} -f {stage}/config.yaml >{stage}/core.log 2>&1 </dev/null & echo $! >{stage}/pid')
            def expect(wanted):
                deadline = time.monotonic()+25
                while time.monotonic() < deadline:
                    result = remote.remote('curl -fsS http://127.0.0.1:19297/proxies/regional || true')
                    if result and json.loads(result)['now'] == wanted:
                        return
                    time.sleep(1)
                raise RuntimeError('Native fallback did not select '+wanted)
            expect('preferred')
            servers[0].healthy = False
            time.sleep(3)
            expect('preferred')
            print('One preferred node failed: provider retained.', flush=True)
            servers[1].healthy = False
            expect('backup-provider')
            print('All preferred nodes failed: backup selected.', flush=True)
            servers[0].healthy = True
            expect('preferred')
            print('Preferred recovered: automatically restored.', flush=True)
        finally:
            if stage:
                remote.remote(f'test ! -f {stage}/pid || kill "$(cat {stage}/pid)"; rm -rf {stage}')
            for server in servers:
                server.shutdown()
                server.server_close()
            subprocess.run(remote.ssh+['-O','exit',remote.target], capture_output=True)

if __name__ == '__main__':
    main()
