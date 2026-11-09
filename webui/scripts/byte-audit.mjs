// 传输字节取证（W18 阶段 0）：用户硬约束是 2C2T / 2G / 20GB 月流量，
// 所以「一次冷加载到底传多少字节」是最该量的数。走 CDP 的 getResponseBody 累加。
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, cfg.profile ?? '.chrome-profile');
const PORT = 9338;
mkdirSync(PROFILE, { recursive: true });

const chrome = spawn(
  cfg.chrome ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--force-device-scale-factor=1',
    'about:blank',
  ],
  { stdio: ['ignore', 'pipe', 'pipe'] }
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function fetchJson(path, method = 'GET') {
  for (let i = 0; i < 100; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}${path}`, { method });
      if (res.ok) return await res.json();
    } catch {
      /* not up */
    }
    await sleep(150);
  }
  throw new Error('devtools unreachable');
}

class S {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { ok, err } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) err(new Error(JSON.stringify(m.error)));
        else ok(m.result);
      } else if (m.method) this.events.push(m);
    });
  }
  send(method, params = {}) {
    const id = (this.id += 1);
    return new Promise((ok, err) => {
      this.pending.set(id, { ok, err });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  once(method, timeout = 15000) {
    return new Promise((ok) => {
      const t0 = Date.now();
      const poll = async () => {
        const i = this.events.findIndex((e) => e.method === method);
        if (i >= 0) return ok(this.events.splice(i, 1)[0]);
        if (Date.now() - t0 > timeout) return ok(null);
        await sleep(40);
        return poll();
      };
      void poll();
    });
  }
}

const target = await fetchJson('/json/new?about:blank', 'PUT');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, err) => {
  ws.addEventListener('open', ok, { once: true });
  ws.addEventListener('error', err, { once: true });
});
const s = new S(ws);
await s.send('Page.enable');
await s.send('Network.enable');
await s.send('Runtime.enable');

// 缓存禁用 + 视口模拟（手机档才有意义：用户手机也可能开）
await s.send('Network.setCacheDisabled', { cacheDisabled: true });
if (cfg.width) {
  await s.send('Emulation.setDeviceMetricsOverride', {
    width: cfg.width,
    height: cfg.height ?? 900,
    deviceScaleFactor: 1,
    mobile: Boolean(cfg.mobile),
    screenWidth: cfg.width,
    screenHeight: cfg.height ?? 900,
  });
  if (cfg.mobile) await s.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
}

const rows = [];
const bodies = new Map();
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === 'Network.responseReceived') {
    const r = m.params.response;
    if (!r.url.startsWith(BASE)) return;
    rows.push({
      id: m.params.requestId,
      url: r.url.replace(BASE, ''),
      type: m.params.type,
      mime: r.mimeType,
      encoded: r.encodedDataLength ?? 0,
      status: r.status,
    });
  }
  if (m.method === 'Network.loadingFinished') {
    const rec = rows.find((x) => x.id === m.params.requestId);
    if (rec) rec.encoded = m.params.encodedDataLength ?? rec.encoded;
  }
});

try {
  const loaded = s.once('Page.loadEventFired', 25000);
  await s.send('Page.navigate', { url: `${BASE}${cfg.route}` });
  await loaded;
  await sleep(cfg.wait ?? 3000);

  const byType = {};
  let total = 0;
  for (const r of rows) {
    byType[r.type] = (byType[r.type] ?? 0) + r.encoded;
    total += r.encoded;
  }
  const top = [...rows].sort((a, b) => b.encoded - a.encoded).slice(0, 12);
  console.log(`route=${cfg.route} width=${cfg.width ?? 'default'}`);
  console.log(`total=${(total / 1024).toFixed(1)} KiB  requests=${rows.length}`);
  console.log('byType=' + JSON.stringify(Object.fromEntries(Object.entries(byType).map(([k, v]) => [k, `${(v / 1024).toFixed(1)}KiB`]))));
  for (const t of top) console.log(`  ${(t.encoded / 1024).toFixed(1).padStart(8)} KiB  ${t.type.padEnd(10)} ${t.url.slice(0, 78)}`);

  // 月流量推算：按「每次冷加载 = total」估。
  // 单位别混：MiB 是 1024 进制、GB 是 10^9；上一版把 MiB 标成 GB，
  // 算出「14294 GB/月」这种不可能的数。两边都给，按运营商口径取。
  const perLoadMiB = total / 1048576;
  console.log(`\n单次冷加载 = ${perLoadMiB.toFixed(3)} MiB`);
  console.log('月流量推算（服务器上限 20GB/月）：');
  for (const n of [1000, 5000, 20000, 50000]) {
    const gib = (perLoadMiB * n) / 1024;
    const gb10 = (total * n) / 1e9;
    const flag = gib > 20 ? '  ← 超预算' : '';
    console.log(`  ${String(n).padStart(6)} 次/月 → ${gib.toFixed(2)} GiB (${gb10.toFixed(2)} GB 十进制)${flag}`);
  }
  console.log(`  20GiB 盈亏平衡：${Math.floor((20 * 1024) / perLoadMiB)} 次/月`);
} finally {
  chrome.kill();
}
