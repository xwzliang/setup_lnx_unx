#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { isIPv4 } from 'node:net';
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline/promises';
import { setTimeout as sleep } from 'node:timers/promises';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';

const APPS = ['core_ssh', 'a0d7b954_ssh', 'a0d7b954_nodered'];
const NODE_RED = 'a0d7b954_nodered';
const COMMUNITY_REPOSITORY = 'https://github.com/hassio-addons/repository';
const ONBOARDING = '/api/onboarding';
const FLOW = '/api/config/config_entries/flow';
const HELP = `Install Home Assistant OS from scratch on Proxmox or configure a fresh HAOS host.

  install.mjs install --vmid ID [Proxmox options] [Home Assistant options]
  install.mjs provision --vmid ID [Proxmox options]
  install.mjs configure --target URL [Home Assistant options]

Proxmox options
  --proxmox ALIAS     SSH host (default pve)
  --storage ID       Disk storage (default local-lvm)
  --bridge NAME      Network bridge (default vmbr0)
  --name NAME        VM name (default haos)
  --memory MIB       RAM in MiB (default 4096)
  --cores COUNT      vCPUs (default 2)
  --disk-gb GIB      Disk in GiB (default 32)
  --haos-version V   HAOS version (default current stable PC VM image)

Home Assistant options
  --owner-name NAME      Owner display name (default Home Administrator)
  --username NAME        Home Assistant owner username (default admin)
  --password-file PATH   Local file holding only the owner password
  --settings-file PATH   Optional JSON with Home Assistant general settings
  --resume               Sign in to continue a previously started configure run

  --timeout SECONDS   Time allowed for first boot or an app operation (default 1200)
`;

function identifier(value, label, pattern = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/) {
  if (typeof value !== 'string' || !pattern.test(value)) throw new Error(`Invalid ${label}.`);
  return value;
}

function integer(value, label, min, max) {
  if (!/^\d+$/.test(value ?? '') || Number(value) < min || Number(value) > max) {
    throw new Error(`${label} must be between ${min} and ${max}.`);
  }
  return String(Number(value));
}

export function targetOrigin(value) {
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Use a Home Assistant base URL such as http://192.168.1.50:8123.');
  }
  return url.origin;
}

function run(command, args, { input, capture = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: [input ? 'pipe' : 'ignore', capture ? 'pipe' : 'inherit', capture ? 'pipe' : 'inherit'] });
    let stdout = '';
    let stderr = '';
    if (capture) {
      child.stdout.setEncoding('utf8').on('data', (chunk) => { stdout += chunk; });
      child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });
    }
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(stderr.trim() || `${command} exited with ${code ?? 'a signal'}.`));
    });
    if (input) {
      child.stdin.on('error', (error) => { if (error.code !== 'EPIPE') reject(error); });
      child.stdin.end(input);
    }
  });
}

function proxmox(remote, command, options) {
  return run('ssh', ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o',
    'ServerAliveInterval=15', '-o', 'StrictHostKeyChecking=yes', '--', remote, command.join(' ')], options);
}

export function guestAddress(interfaces, mac) {
  const guest = interfaces.find((item) => item['hardware-address']?.toLowerCase() === mac.toLowerCase());
  return guest?.['ip-addresses']?.find(({ 'ip-address': ip }) => (
    isIPv4(ip) && !/^(0\.|127\.|169\.254\.)/.test(ip)
  ))?.['ip-address'];
}

async function request(origin, path, { method = 'GET', data, form, token, statuses = [] } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${origin}${path}`, {
    method, headers, body: form ?? (data === undefined ? undefined : JSON.stringify(data)),
    redirect: 'error', signal: AbortSignal.timeout(30000),
  });
  if (statuses.includes(response.status)) return null;
  if (!response.ok) throw new Error(`${method} ${path} returned HTTP ${response.status}.`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

async function provision(options) {
  const remote = identifier(options.proxmox, '--proxmox', /^(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*$/);
  const { vmid } = options;
  const settings = [vmid, identifier(options.name, '--name'), identifier(options.storage, '--storage'),
    identifier(options.bridge, '--bridge'), integer(options.memory, '--memory', 2048, 1048576),
    integer(options.cores, '--cores', 2, 128), integer(options['disk-gb'], '--disk-gb', 16, 16384)];
  if (options['haos-version']) {
    settings.push(identifier(options['haos-version'], '--haos-version', /^\d+\.\d+(?:\.\d+)?$/));
  }
  const input = await readFile(new URL('./provision-proxmox.sh', import.meta.url));
  await proxmox(remote, ['/bin/bash', '-s', '--', ...settings], { input });
  const config = await proxmox(remote, ['qm', 'config', vmid], { capture: true });
  const mac = /^net0: virtio=([a-f\d:]{17})(?:,|$)/im.exec(config)?.[1];
  if (!mac) throw new Error(`Could not identify VM ${vmid}'s MAC address.`);
  console.error(`Waiting for VM ${vmid} to reach the Home Assistant welcome screen.`);
  const deadline = Date.now() + options.timeout;
  let origin;
  while (Date.now() < deadline) {
    try {
      const interfaces = await proxmox(remote, ['qm', 'guest', 'cmd', vmid, 'network-get-interfaces'], { capture: true });
      const address = guestAddress(JSON.parse(interfaces), mac);
      if (address) {
        origin = `http://${address}:8123`;
        const info = await request(origin, `${ONBOARDING}/installation_type`);
        if (info?.installation_type === 'Home Assistant OS') return origin;
      }
    } catch {
      // The guest agent and Core start independently on first boot.
    }
    await sleep(5000);
  }
  throw new Error(`VM ${vmid} was created but Home Assistant did not reach its welcome screen in time. ${
    origin ? `Last URL: ${origin}.` : 'Check its Proxmox console for the assigned IP.'}`);
}

async function passwordFor(options) {
  if (options['password-file']) {
    const password = (await readFile(options['password-file'], 'utf8')).replace(/\r?\n$/, '');
    if (password) return password;
    throw new Error('The password file is empty.');
  }
  if (!process.stdin.isTTY) throw new Error('Use --password-file when running without a terminal.');
  const state = spawnSync('stty', ['-g'], { stdio: ['inherit', 'pipe', 'inherit'], encoding: 'utf8' });
  if (state.status !== 0 || spawnSync('stty', ['-echo'], { stdio: 'inherit' }).status !== 0) {
    throw new Error('Could not disable password echo. Use --password-file.');
  }
  const tty = createInterface({ input: process.stdin, output: process.stderr, terminal: false });
  const interrupted = new AbortController();
  const interrupt = () => interrupted.abort();
  process.once('SIGINT', interrupt);
  tty.once('close', interrupt);
  try {
    const password = await tty.question('Home Assistant owner password: ', { signal: interrupted.signal });
    process.stderr.write('\n');
    if (!options.resume) {
      const confirmation = await tty.question('Confirm password: ', { signal: interrupted.signal });
      process.stderr.write('\n');
      if (confirmation !== password) throw new Error('Passwords do not match.');
    }
    if (!password) throw new Error('Enter a nonempty password.');
    return password;
  } finally {
    tty.close();
    process.removeListener('SIGINT', interrupt);
    spawnSync('stty', [state.stdout.trim()], { stdio: 'inherit' });
  }
}

function wsMessage(socket, accept, timeout, send) {
  return new Promise((resolve, reject) => {
    const finish = (error, value) => {
      clearTimeout(timer);
      socket.removeEventListener('message', receive);
      socket.removeEventListener('error', disconnected);
      socket.removeEventListener('close', disconnected);
      if (error) reject(error);
      else resolve(value);
    };
    const disconnected = () => finish(new Error('Home Assistant WebSocket disconnected.'));
    const receive = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (accept(message)) finish(null, message);
      } catch (error) {
        finish(error);
      }
    };
    const timer = setTimeout(() => finish(new Error('Home Assistant WebSocket request timed out.')), timeout);
    socket.addEventListener('message', receive);
    socket.addEventListener('close', disconnected);
    socket.addEventListener('error', disconnected);
    try { send?.(); } catch (error) { finish(error); }
  });
}

async function withSocket(origin, token, timeout, configure) {
  const socket = new WebSocket(`${origin.replace(/^http/, 'ws')}/api/websocket`);
  let id = 0;
  try {
    await wsMessage(socket, ({ type }) => type === 'auth_required', 30000);
    const auth = await wsMessage(socket, ({ type }) => ['auth_ok', 'auth_invalid'].includes(type), 30000,
      () => socket.send(JSON.stringify({ type: 'auth', access_token: token })));
    if (auth.type !== 'auth_ok') throw new Error('Home Assistant rejected the owner session.');
    const call = async (message) => {
      const requestId = ++id;
      const reply = await wsMessage(socket, ({ id: replyId }) => replyId === requestId, timeout,
        () => socket.send(JSON.stringify({ ...message, id: requestId })));
      if (!reply.success) throw new Error(`${message.endpoint ?? message.type} failed (${reply.error?.code ?? 'unknown error'}).`);
      return reply.result;
    };
    await configure(call);
  } finally {
    socket.close();
  }
}

export async function configureApps(call) {
  const supervisor = (endpoint, method = 'get', data) => call({ type: 'supervisor/api', endpoint, method, data, timeout: null });
  const store = new Set((await supervisor('/store/addons')).addons.map(({ slug }) => slug));
  if (APPS.some((slug) => slug.startsWith('a0d7b954_') && !store.has(slug))) {
    const repositories = await supervisor('/store/repositories');
    if (!repositories.some(({ slug, url }) => slug === 'a0d7b954' || url === COMMUNITY_REPOSITORY)) {
      await supervisor('/store/repositories', 'post', { repository: COMMUNITY_REPOSITORY });
    } else {
      await supervisor('/store/reload', 'post');
    }
  }
  const installed = new Set((await supervisor('/addons')).addons.map(({ slug }) => slug));
  for (const slug of APPS) {
    if (installed.has(slug)) continue;
    console.error(`Installing ${slug}.`);
    await supervisor(`/addons/${slug}/install`, 'post');
  }
  const finalApps = new Set((await supervisor('/addons')).addons.map(({ slug }) => slug));
  if (APPS.some((slug) => !finalApps.has(slug))) throw new Error('Supervisor did not report all requested apps as installed.');

  const nodeRed = await supervisor(`/addons/${NODE_RED}/info`);
  if (nodeRed.state === 'stopped' && !nodeRed.options?.credential_secret) {
    // The stand-alone Nginx listener defaults to port 1880. Disable it
    // before starting Node-RED so access goes through Home Assistant ingress.
    await supervisor(`/addons/${NODE_RED}/options`, 'post', {
      boot: 'auto', network: { ...nodeRed.network, '80/tcp': null },
      options: { ...nodeRed.options, credential_secret: randomBytes(32).toString('hex') },
    });
  }
  if (nodeRed.state === 'stopped' && (!nodeRed.options?.credential_secret || nodeRed.network?.['80/tcp'] === null)) {
    await supervisor(`/addons/${NODE_RED}/start`, 'post');
  }
}

async function acquireSession(origin, options, password) {
  const clientId = `${origin}/`;
  const identity = { client_id: clientId, redirect_uri: clientId };
  let code;
  if (options.resume) {
    const flow = await request(origin, '/auth/login_flow', {
      method: 'POST', data: { ...identity, handler: ['homeassistant', null] },
    });
    identifier(flow.flow_id, 'login flow ID');
    const login = await request(origin, `/auth/login_flow/${flow.flow_id}`, {
      method: 'POST', data: { client_id: clientId, username: options.username, password },
    });
    code = login.result;
  } else {
    const owner = await request(origin, `${ONBOARDING}/users`, {
      method: 'POST', data: { client_id: clientId, name: options['owner-name'], username: options.username, password, language: 'en' },
    });
    code = owner.auth_code;
  }
  if (typeof code !== 'string' || !code) throw new Error('Owner sign-in did not return an authorization code. Complete any sign-in prompts in Home Assistant.');
  return request(origin, '/auth/token', { method: 'POST', form: new URLSearchParams({
    grant_type: 'authorization_code', client_id: clientId, code,
  }) });
}

export async function configure(origin, options, password, settings) {
  const steps = await request(origin, ONBOARDING, { statuses: [401, 404] });
  if (!options.resume) {
    if (!Array.isArray(steps) || !steps.some(({ step, done }) => step === 'user' && done === false)) {
      throw new Error('The target must be at the welcome screen. Use --resume only on the intended new installation.');
    }
    const type = await request(origin, `${ONBOARDING}/installation_type`);
    if (type.installation_type !== 'Home Assistant OS') throw new Error('Expected a fresh Home Assistant OS target.');
  }
  const session = await acquireSession(origin, options, password);
  const token = session.access_token;
  if (!token || !session.refresh_token) throw new Error('Home Assistant did not return a usable owner session.');
  const post = (path, data) => request(origin, path, { method: 'POST', data, token });
  const pending = (step) => steps?.some((entry) => entry.step === step && entry.done === false);
  try {
    const info = await request(origin, '/api/config', { token });
    if (!info.components?.includes('hassio')) throw new Error('Supervisor is unavailable on the target.');
    await withSocket(origin, token, options.timeout, async (call) => {
      if (settings) await call({ ...settings, type: 'config/core/update' });
      if (pending('core_config')) await post(`${ONBOARDING}/core_config`);
      if (pending('analytics')) await post(`${ONBOARDING}/analytics`);
      if (pending('integration')) {
        await post(`${ONBOARDING}/integration`, { client_id: `${origin}/`, redirect_uri: `${origin}/` });
      }
      const entries = await call({ type: 'config_entries/get', domain: 'mcp_server' });
      if (!entries.length) {
        const flow = await post(FLOW, { handler: 'mcp_server' });
        identifier(flow.flow_id, 'MCP Server setup flow ID');
        const result = await post(`${FLOW}/${flow.flow_id}`, {});
        if (result.type !== 'create_entry') throw new Error('Home Assistant did not finish the MCP Server integration setup.');
      }
      await configureApps(call);
    });
    console.error('Home Assistant is set up. Complete Xiaomi Home, SwitchBot Cloud, mobile pairing, and SSH app configuration in the web UI.');
  } finally {
    try {
      await request(origin, '/auth/revoke', { method: 'POST', form: new URLSearchParams({ token: session.refresh_token }) });
    } catch {
      console.error('Could not revoke the temporary setup session. You can revoke it in the owner profile.');
    }
  }
}

function argumentsFor(argv) {
  const string = (value) => ({ type: 'string', default: value });
  const { values, positionals } = parseArgs({ args: argv, allowPositionals: true, options: {
    help: { type: 'boolean', short: 'h' }, vmid: { type: 'string' }, target: { type: 'string' },
    proxmox: string('pve'), storage: string('local-lvm'), bridge: string('vmbr0'), name: string('haos'),
    memory: string('4096'), cores: string('2'), 'disk-gb': string('32'), 'haos-version': { type: 'string' },
    'owner-name': string('Home Administrator'), username: string('admin'), 'password-file': { type: 'string' },
    'settings-file': { type: 'string' }, resume: { type: 'boolean' }, timeout: string('1200'),
  } });
  return { options: values, command: positionals[0], extra: positionals.slice(1) };
}

async function main(argv) {
  const { options, command, extra } = argumentsFor(argv);
  if (options.help || !command) { console.log(HELP); return; }
  if (extra.length || !['install', 'provision', 'configure'].includes(command)) throw new Error('Use install, provision, or configure. See --help.');
  if (options.resume && command !== 'configure') throw new Error('--resume applies only to configure.');
  if (options.target && command !== 'configure') throw new Error('--target applies only to configure.');
  if (command === 'configure' && (!options.target || options.vmid)) throw new Error('Configure requires --target and uses an existing VM.');
  options.timeout = Number(integer(options.timeout, '--timeout', 10, 7200)) * 1000;
  const target = options.target && targetOrigin(options.target);
  if (!target) options.vmid = integer(options.vmid, '--vmid', 100, 999999999);
  let password;
  let settings;
  if (command !== 'provision') {
    if (typeof WebSocket !== 'function') throw new Error('Configuration requires Node.js 22.4 or newer.');
    identifier(options.username, '--username', /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/);
    if (options['settings-file']) {
      settings = JSON.parse(await readFile(options['settings-file'], 'utf8'));
      if (!settings || typeof settings !== 'object' || Array.isArray(settings) || 'id' in settings || 'type' in settings) {
        throw new Error('--settings-file must contain an object with Home Assistant general settings.');
      }
    }
    password = await passwordFor(options);
  }
  const origin = target ?? await provision(options);
  console.log(origin);
  if (command !== 'provision') {
    try {
      await configure(origin, options, password, settings);
    } catch (error) {
      throw new Error(`${error.message} For an interrupted setup, use configure --target ${origin} --resume with the same username.`);
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error) => { console.error(`Error: ${error.message}`); process.exitCode = 1; });
}
