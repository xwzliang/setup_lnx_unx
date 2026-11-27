import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { configure, guestAddress, targetOrigin, welcomeOrigin } from '../setup_homeassistant/install.mjs';
import { configureSsh, installXiaomiHome, localPublicKey, parsePublicKey, xiaomiBrowserArgs } from '../setup_homeassistant/install-extras.mjs';

const target = 'http://192.0.2.10:8123';
const addons = ['core_ssh', 'a0d7b954_ssh', 'a0d7b954_nodered'];
const options = { username: 'new-owner', 'owner-name': 'New Owner', timeout: 1000 };

test('selects a public key from the machine running the installer', async (t) => {
  const directory = mkdtempSync(join(tmpdir(), 'ha-local-ssh-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const key = (type) => `${type} ${Buffer.concat([Buffer.from([0, 0, 0, type.length]), Buffer.from(type), Buffer.alloc(40, 1)]).toString('base64')}`;
  assert.equal(await localPublicKey(undefined, directory), undefined);
  const rsa = join(directory, 'id_rsa.pub');
  writeFileSync(rsa, key('ssh-rsa'));
  assert.equal(await localPublicKey(undefined, directory), key('ssh-rsa'));
  writeFileSync(join(directory, 'id_ed25519.pub'), key('ssh-ed25519'));
  assert.equal(await localPublicKey(undefined, directory), key('ssh-ed25519'));
  assert.equal(await localPublicKey(rsa, directory), key('ssh-rsa'));
});

test('Advanced SSH adds a public key once and starts only the selected add-on', async () => {
  const encoded = Buffer.concat([Buffer.from([0, 0, 0, 11]), Buffer.from('ssh-ed25519'),
    Buffer.from([0, 0, 0, 32]), Buffer.alloc(32, 1)]).toString('base64');
  const key = parsePublicKey(`ssh-ed25519 ${encoded} workstation\n`);
  assert.equal(key, `ssh-ed25519 ${encoded}`);
  assert.throws(() => parsePublicKey('-----BEGIN OPENSSH PRIVATE KEY-----'), /public key/);
  assert.throws(() => parsePublicKey(`ssh-rsa ${encoded}`), /public key/);
  const app = { state: 'stopped', boot: 'manual', network: { '22/tcp': null },
    options: { ssh: { username: 'hassio', authorized_keys: [], password: '', allow_tcp_forwarding: false } } };
  const updates = [];
  const supervisor = async (endpoint, method = 'get', data) => {
    if (endpoint === '/addons/core_ssh/info') return { state: 'stopped' };
    if (endpoint.endsWith('/info')) return app;
    assert.equal(method, 'post');
    updates.push(endpoint.split('/').at(-1));
    if (endpoint.endsWith('/options')) Object.assign(app, data);
    if (endpoint.endsWith('/start')) app.state = 'started';
  };
  await configureSsh(supervisor, key, 'local-user');
  await configureSsh(supervisor, key, 'local-user');
  assert.deepEqual(updates, ['options', 'start']);
  assert.deepEqual(app.options.ssh, { username: 'local-user', authorized_keys: [key], password: '', allow_tcp_forwarding: false });
  assert.equal(app.network['22/tcp'], 22);
  assert.equal(app.boot, 'auto');
});

test('Xiaomi setup installs the catalog repository once and scopes the callback to its browser', async () => {
  const repository = { full_name: 'XiaoMi/ha_xiaomi_home', id: 'catalog-id', installed: false };
  const actions = [];
  const call = async ({ type, repository: repo, repository_id }) => {
    if (type === 'marketplace/info') return { warning_accepted: false };
    if (type === 'marketplace/repositories/list') return [repository];
    if (type === 'marketplace/repository/info') {
      assert.equal(repository_id, repository.id);
      return repository;
    }
    actions.push(type);
    if (type === 'marketplace/repository/install') {
      assert.equal(repo, repository.id);
      repository.installed = true;
    }
  };
  await installXiaomiHome(call, 1000);
  await installXiaomiHome(call, 1000);
  assert.deepEqual(actions, ['marketplace/warning/accept', 'marketplace/repository/install']);
  const args = xiaomiBrowserArgs('http://192.0.2.10', '/tmp/test-profile');
  assert.ok(args.includes('--host-resolver-rules=MAP homeassistant.local 192.0.2.10:80'));
  assert.ok(args.includes('--user-data-dir=/tmp/test-profile'));
  assert.equal(args.at(-1), 'http://192.0.2.10/config/integrations/add?domain=xiaomi_home');
  assert.ok(xiaomiBrowserArgs(target, '/tmp/test-profile').includes('--host-resolver-rules=MAP homeassistant.local 192.0.2.10:8123'));
  assert.throws(() => xiaomiBrowserArgs('http://homeassistant.local', '/tmp/test-profile'), /IPv4/);
});

test('guest IP belongs to the configured primary NIC', () => {
  const interfaces = [
    { 'hardware-address': '02:00:00:00:00:01', 'ip-addresses': [{ 'ip-address': '172.30.32.1' }] },
    { 'hardware-address': '02:00:00:ab:00:02', 'ip-addresses': [
      { 'ip-address': 'fe80::1' }, { 'ip-address': '169.254.10.12' }, { 'ip-address': '192.0.2.10' },
    ] },
  ];
  assert.equal(guestAddress(interfaces, '02:00:00:AB:00:02'), '192.0.2.10');
  assert.equal(guestAddress(interfaces, '02:00:00:00:00:03'), undefined);
  assert.throws(() => targetOrigin(`${target}/api`), /base URL/);
});

test('onboarding uses the live port on the assigned guest without following redirects', async (t) => {
  const responses = new Map();
  const fetch = t.mock.method(globalThis, 'fetch', async (url, request) => {
    assert.equal(request.redirect, 'error');
    assert.equal(new URL(url).hostname, '192.0.2.10');
    return responses.get(new URL(url).origin);
  });
  const modern = 'http://192.0.2.10';
  responses.set(modern, Response.json({ installation_type: 'Home Assistant OS' }));
  responses.set(target, Response.redirect('http://192.0.2.13'));
  assert.equal(await welcomeOrigin('192.0.2.10'), modern);
  responses.set(modern, new Response(null, { status: 503 }));
  responses.set(target, Response.json({ installation_type: 'Home Assistant OS' }));
  assert.equal(await welcomeOrigin('192.0.2.10'), target);
  responses.set(target, Response.redirect('http://192.0.2.13'));
  assert.equal(await welcomeOrigin('192.0.2.10'), undefined);
  assert.equal(fetch.mock.callCount(), 6);
});

test('Proxmox provisioning imports only a verified image and stops on conflicts', (t) => {
  const folder = mkdtempSync(join(tmpdir(), 'ha-provision-test-'));
  t.after(() => rmSync(folder, { force: true, recursive: true }));
  const stub = join(folder, 'fixture');
  writeFileSync(stub, `#!${process.execPath}
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const { basename, join } = require('node:path');
const args = process.argv.slice(2);
const mode = process.env.HA_PROVISION_TEST_MODE;
const archive = 'fixture for haos_ova-18.4.qcow2.xz';
const hash = (data) => createHash('sha256').update(data).digest('hex');
switch (basename(process.argv[1])) {
  case 'id': console.log('0'); break;
  case 'uname': console.log('x86_64'); break;
  case 'pvesh':
    if (args[1] === '/cluster/nextid' && mode === 'occupied') process.exit(255);
    if (args[1] === '/storage/local-lvm') console.log('{"content":"images,rootdir"}');
    break;
  case 'mktemp': console.log(fs.mkdtempSync(join(process.env.HA_PROVISION_TEST_DIR, 'image-'))); break;
  case 'curl':
    if (args.includes('-o')) fs.writeFileSync(args[args.indexOf('-o') + 1], archive);
    else if (args.at(-1).endsWith('stable.json')) console.log('{"hassos":{"ova":"18.4"}}');
    else console.log(JSON.stringify({ assets: [{ name: 'haos_ova-18.4.qcow2.xz',
      digest: 'sha256:' + (mode === 'bad-digest' ? '0'.repeat(64) : hash(archive)) }] }));
    break;
  case 'sha256sum': {
    const [digest, file] = fs.readFileSync(0, 'utf8').trim().split('  ');
    if (hash(fs.readFileSync(file)) !== digest) process.exit(1);
    break;
  }
  case 'xz': process.stdout.write('test qcow2 data'); break;
  case 'qemu-img': console.log('{"format":"qcow2","virtual-size":34359738368}'); break;
  case 'qm': fs.appendFileSync(join(process.env.HA_PROVISION_TEST_DIR, 'qm.log'), JSON.stringify(args) + '\\n'); break;
}
`, { mode: 0o700 });
  for (const command of ['id', 'uname', 'pvesh', 'ip', 'mktemp', 'curl', 'sha256sum', 'xz', 'qemu-img', 'qm']) {
    symlinkSync(stub, join(folder, command));
  }
  const script = fileURLToPath(new URL('../setup_homeassistant/provision-proxmox.sh', import.meta.url));
  const log = join(folder, 'qm.log');
  const run = (mode) => spawnSync('bash', [script, '125', 'haos-new', 'local-lvm', 'vmbr0', '4096', '2', '48'], {
    encoding: 'utf8', env: { ...process.env, PATH: `${folder}:${process.env.PATH}`,
      HA_PROVISION_TEST_DIR: folder, HA_PROVISION_TEST_MODE: mode },
  });
  assert.equal(run('occupied').status, 255);
  assert.match(run('bad-digest').stderr, /failed its SHA-256 check/);
  assert.throws(() => readFileSync(log), { code: 'ENOENT' });
  const result = run('ok');
  assert.equal(result.status, 0, result.stderr);
  const [create, resize, start] = readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(create.slice(0, 4), ['create', '125', '--name', 'haos-new']);
  assert.ok(create.includes('local-lvm:0,efitype=4m,pre-enrolled-keys=0'));
  assert.ok(create.some((arg) => arg.startsWith('local-lvm:0,import-from=')));
  assert.deepEqual(resize, ['disk', 'resize', '125', 'scsi0', '48G']);
  assert.deepEqual(start, ['start', '125']);
});

test('a configured target receives no password or mutation by default', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 404 }));
  await assert.rejects(configure(target, options, 'sentinel-secret'), /welcome screen/);
  assert.equal(fetch.mock.callCount(), 1);
  assert.equal(fetch.mock.calls[0].arguments[1].method, 'GET');
});

test('fresh setup creates the owner and sends the expected Supervisor requests', async (t) => {
  const mutations = [];
  const installed = new Set();
  const steps = ['user', 'core_config', 'analytics', 'integration'];
  let onboarded = false;
  let country = null;
  t.mock.method(globalThis, 'fetch', async (url, request) => {
    assert.equal(new URL(url).origin, target);
    assert.equal(request.redirect, 'error');
    const path = new URL(url).pathname;
    if (request.method === 'POST') mutations.push(path);
    switch (path) {
      case '/api/onboarding': return Response.json(steps.map((step) => ({ step, done: onboarded })));
      case '/api/onboarding/installation_type': return Response.json({ installation_type: 'Home Assistant OS' });
      case '/api/onboarding/users': {
        const data = JSON.parse(request.body);
        assert.equal(data.password, 'sentinel-secret');
        assert.equal(data.username, options.username);
        assert.equal(data.client_id, `${target}/`);
        return Response.json({ auth_code: 'owner-code' });
      }
      case '/auth/login_flow': return Response.json({ flow_id: 'owner-flow' });
      case '/auth/login_flow/owner-flow': return Response.json({ result: 'owner-code' });
      case '/auth/token':
        assert.equal(request.body.get('code'), 'owner-code');
        return Response.json({ access_token: 'short-token', refresh_token: 'temporary-session' });
      case '/api/config':
        assert.equal(request.headers.Authorization, 'Bearer short-token');
        return Response.json({ components: ['hassio'], country });
      case '/api/onboarding/core_config':
      case '/api/onboarding/analytics':
      case '/api/onboarding/integration': return Response.json({});
      case '/api/config/config_entries/flow': return Response.json({ flow_id: 'mcp-flow' });
      case '/api/config/config_entries/flow/mcp-flow': return Response.json({ type: 'create_entry' });
      case '/api/config/config_entries/flow_handlers':
        assert.equal(request.headers.Authorization, 'Bearer short-token');
        return Response.json(['xiaomi_home']);
      case '/auth/revoke':
        assert.equal(request.body.get('token'), 'temporary-session');
        return new Response(null, { status: 200 });
      default: throw new Error(`Unexpected request ${path}`);
    }
  });

  const requests = [];
  class FakeSocket extends EventTarget {
    constructor(url) {
      super();
      assert.equal(url, 'ws://192.0.2.10:8123/api/websocket');
      queueMicrotask(() => this.reply({ type: 'auth_required' }));
    }
    reply(data) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) })); }
    close() {}
    send(raw) {
      const data = JSON.parse(raw);
      if (data.type === 'auth') {
        assert.equal(data.access_token, 'short-token');
        return this.reply({ type: 'auth_ok' });
      }
      requests.push(data);
      let result;
      if (data.type === 'config_entries/get') result = onboarded ? [{ entry_id: 'mcp-entry' }] : [];
      else if (data.type === 'marketplace/info') result = { warning_accepted: true };
      else if (data.type === 'marketplace/repositories/list') result = [{ full_name: 'XiaoMi/ha_xiaomi_home', installed: true }];
      else if (data.endpoint === '/store/addons') result = { addons: [{ slug: 'core_ssh' }] };
      else if (data.endpoint === '/store/repositories' && data.method === 'get') result = [];
      else if (data.endpoint === '/addons') result = { addons: [...installed].map((slug) => ({ slug })) };
      else if (data.endpoint?.endsWith('/install')) installed.add(data.endpoint.split('/')[2]);
      else if (data.endpoint === '/addons/a0d7b954_nodered/info') {
        result = onboarded ? { state: 'started' } : { state: 'stopped', options: { ssl: true }, network: { '80/tcp': 1880 } };
      }
      this.reply({ id: data.id, success: true, result });
    }
  }
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'WebSocket');
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeSocket });
  t.after(() => Object.defineProperty(globalThis, 'WebSocket', descriptor));
  await configure(target, { ...options, 'xiaomi-home': true }, 'sentinel-secret');
  assert.deepEqual([...installed], addons);
  const coreUpdate = {
    id: 1, type: 'config/core/update',
    country: 'CN', currency: 'CNY', language: 'en', time_zone: 'Asia/Shanghai', unit_system: 'metric',
  };
  assert.deepEqual(requests[0], coreUpdate);
  const settings = requests.find(({ endpoint }) => endpoint === '/addons/a0d7b954_nodered/options');
  const start = requests.find(({ endpoint }) => endpoint === '/addons/a0d7b954_nodered/start');
  assert.equal(settings.data.network['80/tcp'], null);
  assert.match(settings.data.options.credential_secret, /^[a-f0-9]{64}$/);
  assert.ok(settings.id < start.id);
  assert.deepEqual(mutations, [
    '/api/onboarding/users', '/auth/token', '/api/onboarding/core_config', '/api/onboarding/analytics',
    '/api/onboarding/integration', '/api/config/config_entries/flow', '/api/config/config_entries/flow/mcp-flow', '/auth/revoke',
  ]);

  onboarded = true;
  const resume = { ...options, resume: true };
  await t.test('resume applies defaults when the country is missing', async () => {
    requests.length = 0;
    await configure(target, resume, 'sentinel-secret', { location_name: 'Home' });
    assert.deepEqual(requests[0], { ...coreUpdate, location_name: 'Home' });
  });
  await t.test('resume preserves existing settings and accepts explicit overrides', async () => {
    country = 'SG';
    requests.length = 0;
    await configure(target, resume, 'sentinel-secret');
    assert.ok(!requests.some(({ type }) => type === 'config/core/update'));
    requests.length = 0;
    await configure(target, resume, 'sentinel-secret', { time_zone: 'Asia/Singapore' });
    assert.deepEqual(requests[0], { id: 1, type: 'config/core/update', time_zone: 'Asia/Singapore' });
  });
});
