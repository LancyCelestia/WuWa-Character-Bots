// 请求计数巡检（W18 阶段 0）：数一次页面加载到底打了几发请求、几发打到同一个源。
// 与 diagnose.mjs 的区别：这里**故意注入一个错 token**，然后统计 401/429 序列，
// 用来证明「错令牌 → 自锁 60 秒」是否真实存在。
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile');
const PORT = 9335;
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

const reqs = [];
s.ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === 'Network.responseReceived') {
    const r = m.params.response;
    if (r.url.includes('/admin/api/') || r.url.includes('/api/')) {
      reqs.push({ url: r.url.replace(BASE, ''), status: r.status, t: Date.now() });
    }
  }
});

try {
  if (cfg.storage) {
    const src = Object.entries(cfg.storage)
      .map(([k, v]) => `try{localStorage.setItem(${JSON.stringify(k)},${JSON.stringify(v)})}catch{}`)
      .join(';');
    await s.send('Page.addScriptToEvaluateOnNewDocument', { source: src });
  }
  const t0 = Date.now();
  const loaded = s.once('Page.loadEventFired', 20000);
  await s.send('Page.navigate', { url: `${BASE}${cfg.route}` });
  await loaded;
  await sleep(cfg.wait ?? 6000);

  const byStatus = {};
  for (const r of reqs) byStatus[r.status] = (byStatus[r.status] ?? 0) + 1;
  console.log(`route=${cfg.route}  total=${reqs.length}  statuses=${JSON.stringify(byStatus)}`);
  for (const r of reqs) console.log(`  +${String(r.t - t0).padStart(5)}ms  ${r.status}  ${r.url.slice(0, 90)}`);

  const info = await s.send('Runtime.evaluate', {
    expression: "({body:document.body.innerText.replace(/\\s+/g,' ').slice(0,400)})",
    returnByValue: true,
  });
  console.log('BODY:', info.result?.value?.body);
} finally {
  chrome.kill();
}
