#!/usr/bin/env node
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { isIPv4 } from 'node:net';
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline/promises';
import { setTimeout as sleep } from 'node:timers/promises';
import { parseArgs } from 'node:util';
import { pathToFileURL } from 'node:url';
import { configureSsh, installXiaomiHome, localPublicKey, openXiaomiBrowser } from './install-extras.mjs';

const APPS = ['core_ssh', 'a0d7b954_ssh', 'a0d7b954_nodered'];
const NODE_RED = 'a0d7b954_nodered';
const COMMUNITY_REPOSITORY = 'https://github.com/hassio-addons/repository';
const ONBOARDING = '/api/onboarding';
const FLOW = '/api/config/config_entries/flow';
const DEFAULT_GENERAL_SETTINGS = {
  country: 'CN',
  currency: 'CNY',
  language: 'en',
  time_zone: 'Asia/Shanghai',
  unit_system: 'metric',
};
const HELP = `Install Home Assistant OS from scratch on Proxmox or configure a fresh HAOS host.

  install.mjs install --vmid ID [Proxmox options] [Home Assistant options]
  install.mjs provision --vmid ID [Proxmox options]
  install.mjs configure (--target URL | --vmid ID) [Home Assistant options]
  install.mjs mcp --target URL [MCP options]

Proxmox options
  --proxmox ALIAS     SSH host (default pve)
  --local-proxmox     Run Proxmox commands directly on the current node
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
  --settings-file PATH   Optional JSON that overrides the general defaults
  --ssh-public-key PATH  Override the OpenSSH public key discovered on this machine
  --ssh-user NAME        Advanced SSH login name (default: its configured user)
  --no-ssh               Skip Advanced SSH configuration
  --no-trusted-web-login Skip LAN passwordless web login configuration for a Proxmox VM
  --xiaomi-home          Install Xiaomi Home and acknowledge the Marketplace notice
  --xiaomi-browser PATH  Open Xiaomi authorization in this Chrome/Chromium executable
  --resume               Sign in to continue a previously started configure run
  --resume-if-needed     Sign in if onboarding already created the owner
  --mcp-codex            Register the new server in local Codex and start OAuth

MCP options
  --mcp-name NAME        Codex server name (default homeassistant)
  --mcp-login            Start browser authorization for an existing entry (mcp command)
  --mcp-token-file PATH  Use an existing HA admin token to install the server integration (mcp command)

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

function mcpEndpoint(value) {
  if (!value) throw new Error('MCP setup requires --target with a Home Assistant URL.');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.search || url.hash || !(url.pathname === '/' || /^\/api\/mcp(?:\/[^/]+)?\/?$/.test(url.pathname))) {
    throw new Error('Use a Home Assistant base URL or MCP endpoint URL for --target.');
  }
  return url.pathname === '/' ? `${url.origin}/api/mcp` : url.href.replace(/\/$/, '');
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
  if (remote === null) return run(command[0], command.slice(1), options);
  return run('ssh', ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o',
    'ServerAliveInterval=15', '-o', 'StrictHostKeyChecking=yes', '--', remote, command.join(' ')], options);
}

export function guestAddress(interfaces, mac) {
  return guestIPv4(interfaces, mac)?.['ip-address'];
}

function guestIPv4(interfaces, mac) {
  const guest = interfaces.find((item) => item['hardware-address']?.toLowerCase() === mac.toLowerCase());
  return guest?.['ip-addresses']?.find(({ 'ip-address': ip }) => (
    isIPv4(ip) && !/^(0\.|127\.|169\.254\.)/.test(ip)
  ));
}

async function request(origin, path, { method = 'GET', data, form, token, statuses = [], timeout = 30000 } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${origin}${path}`, {
    method, headers, body: form ?? (data === undefined ? undefined : JSON.stringify(data)),
    redirect: 'error', signal: AbortSignal.timeout(timeout),
  });
  if (statuses.includes(response.status)) return null;
  if (!response.ok) throw new Error(`${method} ${path} returned HTTP ${response.status}.`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export async function welcomeOrigin(address, allowConfigured = false) {
  // New HAOS installs use port 80 and redirect port 8123. Older installs can
  // still serve port 8123 directly. Probe the same guest IP without following redirects.
  return Promise.any([`http://${address}`, `http://${address}:8123`].map(async (origin) => {
    const probes = [request(origin, `${ONBOARDING}/installation_type`, { timeout: 5000 }).then((info) => {
      if (info?.installation_type !== 'Home Assistant OS') throw new Error('Home Assistant OS is not ready.');
    })];
    if (allowConfigured) {
      probes.push(request(origin, '/auth/providers', { timeout: 5000 }).then((providers) => {
        if (!Array.isArray(providers) || !providers.some(({ type }) => type === 'homeassistant')) {
          throw new Error('Home Assistant sign-in is not ready.');
        }
      }));
    }
    await Promise.any(probes);
    return origin;
  })).catch(() => undefined);
}

function proxmoxRemote(options) {
  return options['local-proxmox'] ? null :
    identifier(options.proxmox ?? 'pve', '--proxmox', /^(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*$/);
}

async function primaryMac(remote, vmid) {
  const config = await proxmox(remote, ['qm', 'config', vmid], { capture: true });
  const mac = /^net0: virtio=([a-f\d:]{17})(?:,|$)/im.exec(config)?.[1];
  if (!mac) throw new Error(`Could not identify VM ${vmid}'s MAC address.`);
  return mac;
}

async function primaryIPv4(remote, vmid, mac) {
  const interfaces = await proxmox(remote, ['qm', 'guest', 'cmd', vmid, 'network-get-interfaces'], { capture: true });
  return guestIPv4(JSON.parse(interfaces), mac);
}

async function provision(options) {
  const remote = proxmoxRemote(options);
  const { vmid } = options;
  const settings = [vmid, identifier(options.name, '--name'), identifier(options.storage, '--storage'),
    identifier(options.bridge, '--bridge'), integer(options.memory, '--memory', 2048, 1048576),
    integer(options.cores, '--cores', 2, 128), integer(options['disk-gb'], '--disk-gb', 16, 16384)];
  if (options['haos-version']) {
    settings.push(identifier(options['haos-version'], '--haos-version', /^\d+\.\d+(?:\.\d+)?$/));
  }
  const input = await readFile(new URL('./provision-proxmox.sh', import.meta.url));
  await proxmox(remote, ['/bin/bash', '-s', '--', ...settings], { input });
  return waitForGuest(remote, vmid, options.timeout);
}

async function waitForGuest(remote, vmid, timeout, allowConfigured = false) {
  const mac = await primaryMac(remote, vmid);
  console.error(`Waiting for Home Assistant on VM ${vmid}.`);
  const deadline = Date.now() + timeout;
  let address;
  while (Date.now() < deadline) {
    try {
      const currentAddress = (await primaryIPv4(remote, vmid, mac))?.['ip-address'];
      if (currentAddress) {
        address = currentAddress;
        const origin = await welcomeOrigin(address, allowConfigured);
        if (origin) return origin;
      }
    } catch {
      // The guest agent and Core start independently on first boot.
    }
    await sleep(5000);
  }
  throw new Error(`Home Assistant on VM ${vmid} did not become ready in time. ${
    address ? `Last reported IP: ${address}.` : 'Check its Proxmox console for the assigned IP.'}`);
}

async function verifiedGuest(origin, options) {
  const remote = proxmoxRemote(options);
  const { vmid } = options;
  const primary = await primaryIPv4(remote, vmid, await primaryMac(remote, vmid));
  const ip = primary?.['ip-address'];
  if (ip !== new URL(origin).hostname || !Number.isInteger(primary.prefix) || primary.prefix < 1 || primary.prefix > 32) {
    throw new Error(`Use the primary IPv4 URL of VM ${vmid} to configure its LAN web login.`);
  }
  return { remote, vmid, address: `${ip}/${primary.prefix}` };
}

async function guestCommand(guest, command, input) {
  const args = ['qm', 'guest', 'exec', guest.vmid, '--timeout', '120'];
  if (input) args.push('--pass-stdin', '1');
  const reply = JSON.parse(await proxmox(guest.remote, [...args, '--', ...command], { input, capture: true }));
  if (reply.exited !== 1 || reply.exitcode !== 0) {
    throw new Error(reply['err-data']?.trim() || `Guest command failed on VM ${guest.vmid}.`);
  }
  return reply['out-data']?.trim();
}

async function configureWebLogin(origin, guest, owner) {
  if (!owner?.is_owner) throw new Error('LAN web login requires the Home Assistant owner account.');
  const ownerId = identifier(owner.id, 'Home Assistant owner ID', /^[a-f0-9]{32}$/);
  const script = await readFile(new URL('./trusted-web-login.py', import.meta.url));
  const output = await guestCommand(guest, ['/usr/bin/docker', 'exec', '-i', 'homeassistant', 'python3', '-', guest.address, ownerId], script);
  const [status, network] = output?.split(' ') ?? [];
  if (!['changed', 'unchanged'].includes(status) || !network) throw new Error('The guest did not report its trusted web login configuration.');
  if (status === 'changed') {
    console.error(`Restarting Home Assistant Core on VM ${guest.vmid} to enable passwordless LAN login.`);
    await guestCommand(guest, ['/usr/bin/ha', '--no-progress', 'core', 'restart']);
    for (let attempt = 0; attempt < 30; attempt++) {
      try {
        await request(origin, '/auth/providers', { timeout: 4000 });
        break;
      } catch (error) {
        if (attempt === 29) throw new Error('Home Assistant did not respond after restarting Core.', { cause: error });
      }
      await sleep(2000);
    }
  }
  console.error(`Home Assistant web login is passwordless for ${network}.`);
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
    return await configure(call);
  } finally {
    socket.close();
  }
}

async function configureMcpServer(call, post) {
  const entries = await call({ type: 'config_entries/get', domain: 'mcp_server' });
  if (entries.length) return entries.some(({ disabled_by: disabledBy }) => !disabledBy);
  const flow = await post(FLOW, { handler: 'mcp_server' });
  if (flow.type === 'create_entry' || (flow.type === 'abort' && flow.reason === 'already_configured')) return true;
  identifier(flow.flow_id, 'MCP Server setup flow ID');
  const result = await post(`${FLOW}/${flow.flow_id}`, {});
  if (result.type !== 'create_entry' && !(result.type === 'abort' && result.reason === 'already_configured')) {
    throw new Error('Home Assistant did not finish the MCP Server integration setup.');
  }
  return true;
}

async function configureCodexMcp(endpoint, name, login = false) {
  const codex = (args, options) => run('codex', ['mcp', ...args], options).catch((error) => {
    if (error.code === 'ENOENT') throw new Error('Install Codex CLI and make codex available on PATH.');
    throw error;
  });
  const entries = JSON.parse(await codex(['list', '--json'], { capture: true }));
  if (!Array.isArray(entries)) throw new Error('Codex did not return a list of MCP servers.');
  const entry = entries.find((candidate) => candidate.name === name);
  if (!entry) {
    await codex(['add', name, '--url', endpoint]);
    console.log(`Registered ${name} in Codex. Finish authorization if Codex opens a browser.`);
    return;
  }
  if (entry.transport?.type !== 'streamable_http' || entry.transport.url !== endpoint) {
    throw new Error(`Codex already has a different MCP server named ${name}. Use --mcp-name to choose another name.`);
  }
  if (entry.enabled === false) throw new Error(`The ${name} MCP server is disabled in Codex.`);
  if (login) await codex(['login', name]);
  else console.log(`${name} is already registered in Codex. Use --mcp-login to start OAuth again if needed.`);
}

function supervisorApi(call) {
  return (endpoint, method = 'get', data) => call({ type: 'supervisor/api', endpoint, method, data, timeout: null });
}

export async function configureApps(call) {
  const supervisor = supervisorApi(call);
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

export async function configure(origin, options, password, settings, guest) {
  const steps = await request(origin, ONBOARDING, { statuses: [401, 404] });
  const pending = (step) => Array.isArray(steps) && steps.some((entry) => entry.step === step && entry.done === false);
  if (options['resume-if-needed'] && !pending('user')) options = { ...options, resume: true };
  if (!options.resume) {
    if (!pending('user')) {
      throw new Error('The target must be at the welcome screen. Use --resume only on the intended new installation.');
    }
    const type = await request(origin, `${ONBOARDING}/installation_type`);
    if (type.installation_type !== 'Home Assistant OS') throw new Error('Expected a fresh Home Assistant OS target.');
  }
  const session = await acquireSession(origin, options, password);
  const token = session.access_token;
  if (!token || !session.refresh_token) throw new Error('Home Assistant did not return a usable owner session.');
  const post = (path, data) => request(origin, path, { method: 'POST', data, token });
  let owner;
  let needsXiaomiAuthorization = false;
  try {
    const info = await request(origin, '/api/config', { token });
    if (!info.components?.includes('hassio')) throw new Error('Supervisor is unavailable on the target.');
    const defaults = options.resume && info.country ? {} : DEFAULT_GENERAL_SETTINGS;
    const general = { ...defaults, ...settings };
    await withSocket(origin, token, options.timeout, async (call) => {
      if (guest) owner = await call({ type: 'auth/current_user' });
      if (Object.keys(general).length) await call({ ...general, type: 'config/core/update' });
      if (pending('core_config')) await post(`${ONBOARDING}/core_config`);
      if (pending('analytics')) await post(`${ONBOARDING}/analytics`);
      if (pending('integration')) {
        await post(`${ONBOARDING}/integration`, { client_id: `${origin}/`, redirect_uri: `${origin}/` });
      }
      await configureMcpServer(call, post);
      await configureApps(call);
      if (options.sshKey) await configureSsh(supervisorApi(call), options.sshKey, options['ssh-user']);
      if (options['xiaomi-home']) {
        await installXiaomiHome(call, options.timeout);
        const xiaomiEntries = await call({ type: 'config_entries/get', domain: 'xiaomi_home' });
        if (xiaomiEntries.length === 0) {
          const handlers = await request(origin, '/api/config/config_entries/flow_handlers', { token });
          if (!handlers.includes('xiaomi_home')) throw new Error('Xiaomi Home is installed but its setup flow is unavailable. Check Home Assistant Repairs.');
          needsXiaomiAuthorization = true;
        }
      }
    });
    if (guest) await configureWebLogin(origin, guest, owner);
    if (needsXiaomiAuthorization) {
      if (options['xiaomi-browser']) await openXiaomiBrowser(origin, options['xiaomi-browser']);
      else console.error(`Finish Xiaomi authorization at ${origin}/config/integrations/add?domain=xiaomi_home. Use --xiaomi-browser to route the callback to this instance.`);
    }
    console.error('Home Assistant is set up. Connect cloud accounts and pair the mobile app in the web UI.');
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
    proxmox: { type: 'string' }, 'local-proxmox': { type: 'boolean' },
    storage: string('local-lvm'), bridge: string('vmbr0'), name: string('haos'),
    memory: string('4096'), cores: string('2'), 'disk-gb': string('32'), 'haos-version': { type: 'string' },
    'owner-name': string('Home Administrator'), username: string('admin'), 'password-file': { type: 'string' },
    'settings-file': { type: 'string' }, resume: { type: 'boolean' }, 'resume-if-needed': { type: 'boolean' }, timeout: string('1200'),
    'ssh-public-key': { type: 'string' }, 'ssh-user': { type: 'string' }, 'xiaomi-home': { type: 'boolean' },
    'xiaomi-browser': { type: 'string' }, 'no-ssh': { type: 'boolean' }, 'no-trusted-web-login': { type: 'boolean' },
    'mcp-codex': { type: 'boolean' }, 'mcp-name': { type: 'string' },
    'mcp-login': { type: 'boolean' }, 'mcp-token-file': { type: 'string' },
  } });
  return { options: values, command: positionals[0], extra: positionals.slice(1) };
}

async function main(argv) {
  const { options, command, extra } = argumentsFor(argv);
  if (options.help || !command) { console.log(HELP); return; }
  if (extra.length || !['install', 'provision', 'configure', 'mcp'].includes(command)) throw new Error('Use install, provision, configure, or mcp. See --help.');
  if ((options.resume || options['resume-if-needed']) && command !== 'configure') {
    throw new Error('Resume options apply only to configure.');
  }
  if (options.resume && options['resume-if-needed']) throw new Error('Use one resume option.');
  if (options.proxmox && options['local-proxmox']) throw new Error('Choose either --proxmox or --local-proxmox.');
  if (options.target && !['configure', 'mcp'].includes(command)) throw new Error('--target applies only to configure or mcp.');
  if (options['no-ssh'] && (options['ssh-public-key'] || options['ssh-user'])) throw new Error('--no-ssh cannot be combined with SSH options.');
  if (options['xiaomi-browser'] && !options['xiaomi-home']) throw new Error('--xiaomi-browser requires --xiaomi-home.');
  if (command === 'provision' && (options['ssh-public-key'] || options['xiaomi-home'])) throw new Error('Use install or configure to set up SSH or Xiaomi Home.');
  if (command === 'configure' && !options.target && !options.vmid) throw new Error('Configure requires --target or --vmid.');
  if (options['mcp-codex'] && !['install', 'configure'].includes(command)) {
    throw new Error('--mcp-codex applies only to install or configure. Use mcp for an existing server.');
  }
  if (command !== 'mcp' && (options['mcp-login'] || options['mcp-token-file'])) {
    throw new Error('--mcp-login and --mcp-token-file apply only to the mcp command.');
  }
  if (options['mcp-name'] !== undefined && command !== 'mcp' && !options['mcp-codex']) {
    throw new Error('--mcp-name requires the mcp command or --mcp-codex.');
  }
  const mcpName = identifier(options['mcp-name'] ?? 'homeassistant', '--mcp-name', /^[a-zA-Z0-9][a-zA-Z0-9_-]*$/);
  options.timeout = Number(integer(options.timeout, '--timeout', 10, 7200)) * 1000;
  if (command === 'mcp') {
    const endpoint = mcpEndpoint(options.target);
    if (options['mcp-token-file'] !== undefined) {
      if (typeof WebSocket !== 'function') throw new Error('MCP server setup requires Node.js 22.4 or newer.');
      const token = (await readFile(options['mcp-token-file'], 'utf8')).trim();
      if (!token || /[^\x21-\x7e]/.test(token)) throw new Error('The MCP token file must contain a single Home Assistant admin access token.');
      const origin = new URL(endpoint).origin;
      const enabled = await withSocket(origin, token, options.timeout, (call) => configureMcpServer(call,
        (path, data) => request(origin, path, { method: 'POST', data, token })));
      if (!enabled) throw new Error('The existing MCP Server integration is disabled in Home Assistant.');
      console.log('Home Assistant MCP Server integration is configured.');
    }
    await configureCodexMcp(endpoint, mcpName, options['mcp-login']);
    return;
  }
  const target = options.target && targetOrigin(options.target);
  if (!target || options.vmid) options.vmid = integer(options.vmid, '--vmid', 100, 999999999);
  let password;
  let settings;
  if (command !== 'provision') {
    if (typeof WebSocket !== 'function') throw new Error('Configuration requires Node.js 22.4 or newer.');
    identifier(options.username, '--username', /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/);
    if (options['ssh-user']) identifier(options['ssh-user'], '--ssh-user', /^[a-z_][a-z0-9_-]{0,31}$/);
    if (!options['no-ssh']) {
      options.sshKey = await localPublicKey(options['ssh-public-key']);
      if (!options.sshKey) console.error('No local SSH public key was found. Use --ssh-public-key to enable Advanced SSH.');
    }
    if (options['settings-file']) {
      settings = JSON.parse(await readFile(options['settings-file'], 'utf8'));
      if (!settings || typeof settings !== 'object' || Array.isArray(settings) || 'id' in settings || 'type' in settings) {
        throw new Error('--settings-file must contain an object with Home Assistant general settings.');
      }
    }
    password = await passwordFor(options);
  }
  const origin = target ?? (command === 'configure'
    ? await waitForGuest(proxmoxRemote(options), options.vmid, options.timeout, options.resume || options['resume-if-needed'])
    : await provision(options));
  console.log(origin);
  if (command !== 'provision') {
    try {
      const guest = options.vmid && !options['no-trusted-web-login'] ? await verifiedGuest(origin, options) : undefined;
      await configure(origin, options, password, settings, guest);
    } catch (error) {
      throw new Error(`${error.message} For an interrupted setup, use configure --target ${origin} --resume with the same username.`);
    }
    if (options['mcp-codex']) await configureCodexMcp(mcpEndpoint(origin), mcpName);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error) => { console.error(`Error: ${error.message}`); process.exitCode = 1; });
}
