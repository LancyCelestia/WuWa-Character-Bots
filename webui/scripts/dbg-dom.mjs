// 一次性诊断：为什么对比度采样是 0。看 DOM 里到底有没有 main、文本节点在哪。
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PROFILE = join(ROOT, '.chrome-profile.dbg');
const PORT = 9342;
mkdirSync(PROFILE, { recursive: true });
const BASE = 'http://127.0.0.1:8742';

const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',
  ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
   '--no-first-run', '--no-default-browser-check', '--disable-extensions',
   '--force-device-scale-factor=1', '--hide-scrollbars', 'about:blank'],
  { stdio: ['ignore', 'pipe', 'pipe'] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path, method = 'GET') {
  for (let i = 0; i < 120; i += 1) {
    try { const res = await fetch(`http://127.0.0.1:${PORT}${path}`, { method }); if (res.ok) return await res.json(); } catch {}
    await sleep(150);
  }
  throw new Error('devtools unreachable');
}
class S {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.addEventListener('message', (ev) => { const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) { const { ok, err } = this.pending.get(m.id); this.pending.delete(m.id);
        if (m.error) err(new Error(JSON.stringify(m.error))); else ok(m.result); }
      else if (m.method) this.events.push(m); }); }
  send(method, params = {}) { const id = (this.id += 1);
    return new Promise((ok, err) => { this.pending.set(id, { ok, err }); this.ws.send(JSON.stringify({ id, method, params })); }); }
  once(method, timeout = 20000) { return new Promise((ok) => { const t0 = Date.now();
    const poll = async () => { const i = this.events.findIndex((e) => e.method === method);
      if (i >= 0) return ok(this.events.splice(i, 1)[0]);
      if (Date.now() - t0 > timeout) return ok(null);
      await sleep(40); return poll(); }; void poll(); }); }
}

const target = await fetchJson('/json/new?about:blank', 'PUT');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, err) => { ws.addEventListener('open', ok, { once: true }); ws.addEventListener('error', err, { once: true }); });
const s = new S(ws);
await s.send('Page.enable');
await s.send('Runtime.enable');
await s.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

try {
  const loaded = s.once('Page.loadEventFired', 25000);
  await s.send('Page.navigate', { url: `${BASE}${process.argv[2] ?? '/console/calls'}` });
  await loaded;
  await sleep(3000);
  const ev = await s.send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
    const q = (sel) => document.querySelectorAll(sel).length;
    const main = document.querySelector('main');
    const sample = [];
    if (main) {
      for (const el of main.querySelectorAll('*')) {
        const own = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim().length > 1);
        if (!own.length) continue;
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        sample.push({ tag: el.tagName, text: own[0].textContent.trim().slice(0,30), w: Math.round(r.width), h: Math.round(r.height), color: cs.color, fs: cs.fontSize, fw: cs.fontWeight });
        if (sample.length >= 12) break;
      }
    }
    return { hasMain: !!main, mainRect: main ? main.getBoundingClientRect().toJSON() : null,
             counts: { p: q('main p'), h1: q('main h1'), td: q('main td'), button: q('main button'), all: q('main *') },
             sample, bodyLen: document.body.innerText.length };
  })()` });
  console.log(JSON.stringify(ev.result?.value, null, 2));
} finally { chrome.kill(); }
