import { spawn } from 'node:child_process';
import { mkdtemp } from 'node:fs/promises';
import { isIPv4 } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

const SSH = '/addons/a0d7b954_ssh';
const XIAOMI_REPOSITORY = 'xiaomi/ha_xiaomi_home';

export function parsePublicKey(value) {
  const match = /^([\w@.-]+)[ \t]+([A-Za-z0-9+/]+={0,2})(?:[ \t]+[^\r\n]*)?$/.exec(value.trim());
  if (match) {
    const [, type, encoded] = match;
    const bytes = Buffer.from(encoded, 'base64');
    if (bytes.length >= 4) {
      const size = bytes.readUInt32BE();
      if (size > 0 && size < bytes.length - 4 && bytes.subarray(4, 4 + size).toString('ascii') === type &&
          /^(?:ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)$/.test(type)) {
        return `${type} ${bytes.toString('base64')}`;
      }
    }
  }
  throw new Error('Expected one OpenSSH public key. Pass your .pub file.');
}

export async function configureSsh(supervisor, key, username) {
  const app = await supervisor(`${SSH}/info`);
  const other = await supervisor('/addons/core_ssh/info');
  const ssh = app.options?.ssh;
  if (!ssh || !Array.isArray(ssh.authorized_keys)) throw new Error('Advanced SSH returned unexpected options.');
  const port = app.network?.['22/tcp'] ?? 22;
  if (other.state === 'started' && other.network?.['22/tcp'] === port) {
    throw new Error('Terminal & SSH is already using the selected SSH port.');
  }
  if (username && username !== ssh.username && (ssh.authorized_keys.length || ssh.password)) {
    throw new Error('Advanced SSH already has account credentials. Reuse its configured username.');
  }
  const present = ssh.authorized_keys.some((line) => line.trim().split(/\s+/).slice(0, 2).join(' ') === key);
  const requestedUser = username ?? ssh.username;
  const reconfigure = !present || requestedUser !== ssh.username || app.boot !== 'auto' || app.network?.['22/tcp'] !== port;
  if (reconfigure) {
    await supervisor(`${SSH}/options`, 'post', {
      boot: 'auto', network: { ...app.network, '22/tcp': port },
      options: { ...app.options, ssh: { ...ssh, username: requestedUser,
        authorized_keys: present ? ssh.authorized_keys : [...ssh.authorized_keys, key] } },
    });
  }
  if (app.state === 'stopped') await supervisor(`${SSH}/start`, 'post');
  else if (reconfigure) await supervisor(`${SSH}/restart`, 'post');
  if ((await supervisor(`${SSH}/info`)).state !== 'started') throw new Error('Advanced SSH did not start. Check its app logs.');
  console.error(`Advanced SSH configured for ${requestedUser} on port ${port}.`);
}

export async function installXiaomiHome(call, timeout) {
  const deadline = Date.now() + Math.min(timeout, 60000);
  let repo;
  let info;
  do {
    info = await call({ type: 'marketplace/info' });
    const repositories = await call({ type: 'marketplace/repositories/list', categories: ['integration'] });
    repo = repositories.find(({ full_name }) => full_name.toLowerCase() === XIAOMI_REPOSITORY);
    if (repo || (!info.startup && !info.has_pending_tasks)) break;
    await sleep(2000);
  } while (Date.now() < deadline);
  if (!repo) throw new Error('Xiaomi Home is unavailable in the Marketplace catalog. Check Marketplace and retry.');
  if (repo.installed) return;
  if (!info.warning_accepted) await call({ type: 'marketplace/warning/accept' });
  await call({ type: 'marketplace/repository/install', repository: repo.id });
  const installed = await call({ type: 'marketplace/repository/info', repository_id: repo.id });
  if (!installed.installed) throw new Error('Marketplace did not confirm the Xiaomi Home installation.');
}

export function xiaomiBrowserArgs(origin, profile) {
  const target = new URL(origin);
  if (target.protocol !== 'http:' || !isIPv4(target.hostname)) {
    throw new Error('Use the HAOS guest’s HTTP IPv4 URL for Xiaomi authorization.');
  }
  return [
    `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--incognito',
    `--host-resolver-rules=MAP homeassistant.local ${target.hostname}:${target.port || '80'}`,
    `${target.origin}/config/integrations/add?domain=xiaomi_home`,
  ];
}

export async function openXiaomiBrowser(origin, executable) {
  const profile = await mkdtemp(join(tmpdir(), 'ha-xiaomi-browser-'));
  const args = xiaomiBrowserArgs(origin, profile);
  await new Promise((resolve, reject) => {
    const child = spawn(executable, args, { detached: true, stdio: 'ignore' });
    child.once('error', reject);
    child.once('spawn', () => { child.unref(); resolve(); });
  });
  console.error('Opened Xiaomi Home setup in a separate browser session. Accept Xiaomi’s terms, sign in, and choose the homes to import.');
}
