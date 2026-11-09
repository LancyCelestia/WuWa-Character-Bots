// 诊断巡检（W18 阶段 0）：按路由收三类证据，不截图。
//   ① Runtime.exceptionThrown —— 未捕获异常（白屏/坏交互的直接原因）
//   ② Log.entryAdded         —— 严重级别 warning/error（含 CSP 拒绝、资源 404）
//   ③ Network.loadingFailed  —— 请求层失败（接口/资源）
//   ④ Runtime.consoleAPICalled level=error —— React 抛错、主动 console.error
//
// 用法：node scripts/diagnose.mjs <diag.json>
// diag.json: { "base": "...", "routes": ["/console/", "/console/#/dashboard"], "wait": 2500,
//              "storage": { "key": "value" } }   ← storage 在页面加载前写入 localStorage
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfgPath = process.argv[2];
if (!cfgPath) {
  console.error('usage: node scripts/diagnose.mjs <diag.json>');
  process.exit(2);
}
const cfg = JSON.parse(readFileSync(resolve(ROOT, cfgPath), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile');
const PORT = 9334;
mkdirSync(PROFILE, { recursive: true });

const CHROME = cfg.chrome ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--force-device-scale-factor=1',
    '--autoplay-policy=no-user-gesture-required',
    'about:blank',
  ],
  { stdio: ['ignore', 'pipe', 'pipe'] }
);
let chromeErr = '';
chrome.stderr.on('data', (d) => (chromeErr += d.toString()));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path, method = 'GET') {
  for (let i = 0; i < 100; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}${path}`, { method });
      if (res.ok) return await res.json();
    } catch {
      /* not up yet */
    }
    await sleep(150);
  }
  throw new Error(`chrome devtools not reachable\n${chromeErr.slice(-1500)}`);
}

class Session {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.events = [];
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { ok, err } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) err(new Error(JSON.stringify(msg.error)));
        else ok(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    });
  }
  send(method, params = {}) {
    this.id += 1;
    const id = this.id;
    return new Promise((ok, err) => {
      this.pending.set(id, { ok, err });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  once(method, timeout = 15000) {
    return new Promise((ok) => {
      const started = Date.now();
      const poll = async () => {
        const idx = this.events.findIndex((e) => e.method === method);
        if (idx >= 0) return ok(this.events.splice(idx, 1)[0]);
        if (Date.now() - started > timeout) return ok(null);
        await sleep(50);
        return poll();
      };
      void poll();
    });
  }
}

async function connect() {
  const target = await fetchJson('/json/new?about:blank', 'PUT');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, err) => {
    ws.addEventListener('open', ok, { once: true });
    ws.addEventListener('error', err, { once: true });
  });
  return new Session(ws);
}

const out = [];
try {
  await fetchJson('/json/version');
  const s = await connect();
  await s.send('Page.enable');
  await s.send('Runtime.enable');
  await s.send('Log.enable');
  await s.send('Network.enable');

  for (const route of cfg.routes ?? []) {
    s.events.length = 0;
    if (cfg.storage) {
      const src = Object.entries(cfg.storage)
        .map(([k, v]) => `try{localStorage.setItem(${JSON.stringify(k)},${JSON.stringify(v)})}catch{}`)
        .join(';');
      await s.send('Page.addScriptToEvaluateOnNewDocument', { source: src });
    }
    const loaded = s.once('Page.loadEventFired', 20000);
    await s.send('Page.navigate', { url: `${BASE}${route}` });
    await loaded;
    await sleep(cfg.wait ?? 2500);

    const exceptions = s.events
      .filter((e) => e.method === 'Runtime.exceptionThrown')
      .map((e) => {
        const d = e.params.exceptionDetails;
        return {
          text: d.text,
          desc: d.exception?.description?.split('\n').slice(0, 3).join(' | ') ?? null,
          url: d.url ?? null,
          line: d.lineNumber ?? null,
        };
      });
    const logs = s.events
      .filter((e) => e.method === 'Log.entryAdded')
      .map((e) => ({ level: e.params.entry.level, source: e.params.entry.source, text: e.params.entry.text }))
      .filter((e) => e.level === 'error' || e.level === 'warning');
    const netFails = s.events
      .filter((e) => e.method === 'Network.loadingFailed')
      .map((e) => ({ url: e.params.requestId, err: e.params.errorText, blocked: e.params.blockedReason ?? null }))
      .slice(0, 12);
    const consoleErrs = s.events
      .filter((e) => e.method === 'Runtime.consoleAPICalled' && e.params.type === 'error')
      .map((e) => e.params.args.map((a) => a.value ?? a.description ?? a.type).join(' ').slice(0, 300));

    const info = await s.send('Runtime.evaluate', {
      expression:
        "({title:document.title,hash:location.hash,rootChildren:document.getElementById('root')?.childElementCount ?? -1,bodyLen:document.body.innerText.length,h1:(document.querySelector('h1')?.textContent??'').trim(),hasNav:!!document.querySelector('nav'),hasMain:!!document.querySelector('main')})",
      returnByValue: true,
    });

    out.push({ route, info: info.result?.value, exceptions, consoleErrs, netFails, logs: logs.slice(0, 12) });
    console.log(`\n=== ${route} ===`);
    console.log(JSON.stringify(out[out.length - 1], null, 2));
  }
} finally {
  chrome.kill();
}
