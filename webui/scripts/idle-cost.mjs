// 空闲期样式重算取证（W18 阶段 0）：把「持续动画」的代价量化成数字。
//
// 手法：加载完成后读一次 Performance.getMetrics，静置 N 秒再读一次，取差值。
// 同一路由跑两遍：一遍正常（动效开），一遍在页面加载前把 `data-motion='off'` 挂上。
// 差值之比就是「氛围动画每秒烧掉多少次样式重算」。不猜，只量。
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile');
const PORT = 9337;
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
await s.send('Performance.enable');
await s.send('Runtime.enable');

const metrics = async () => {
  const m = await s.send('Performance.getMetrics');
  return Object.fromEntries((m.metrics ?? []).map((x) => [x.name, x.value]));
};

try {
  const rows = [];
  for (const route of cfg.routes ?? []) {
    for (const mode of ['on', 'off']) {
      s.events.length = 0;
      if (mode === 'off') {
        await s.send('Page.addScriptToEvaluateOnNewDocument', {
          source: `document.addEventListener('DOMContentLoaded',()=>{document.documentElement.dataset.motion='off'},true);try{new MutationObserver((_,o)=>{const h=document.documentElement;if(h&&h.dataset.motion!=='off'){h.dataset.motion='off';o.disconnect();}}).observe(document.documentElement,{childList:false,attributes:false})}catch{};try{Object.defineProperty(document,'__x',{value:1})}catch{};(function tick(){const h=document.documentElement;if(h&&h.dataset.motion!=='off')h.dataset.motion='off';requestAnimationFrame(tick)})();`,
        });
      }
      const loaded = s.once('Page.loadEventFired', 20000);
      await s.send('Page.navigate', { url: `${BASE}${route}` });
      await loaded;
      await sleep(1500);
      const a = await metrics();
      await sleep(cfg.idleMs ?? 4000);
      const b = await metrics();
      rows.push({
        route,
        motion: mode,
        idleMs: cfg.idleMs ?? 4000,
        recalc: Math.round(b.RecalcStyleCount - a.RecalcStyleCount),
        layout: Math.round(b.LayoutCount - a.LayoutCount),
        taskMs: Math.round((b.TaskDuration - a.TaskDuration) * 1000),
        scriptMs: Math.round((b.ScriptDuration - a.ScriptDuration) * 1000),
        heapMB: Number(((b.JSHeapUsedSize ?? 0) / 1048576).toFixed(2)),
        motionAttr: (await s.send('Runtime.evaluate', { expression: "document.documentElement.dataset.motion ?? 'unset'", returnByValue: true })).result?.value,
      });
      await s.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: '1' }).catch(() => {});
    }
  }
  for (const r of rows) console.log(JSON.stringify(r));
} finally {
  chrome.kill();
}
