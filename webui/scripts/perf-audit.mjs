// 性能预算取证（W18 阶段 0）：LCP / CLS / 长任务 / DOM 节点数 / JS 堆。
// 用 CDP 的真实指标（Performance.getMetrics + LayoutShift/LongTask 的 PerformanceObserver），
// 不引 Lighthouse（要装包，本波禁止）。
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile');
const PORT = 9336;
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

const OBS = `(() => {
  window.__m = { lcp: 0, cls: 0, longTasks: [], fcp: 0 };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__m.lcp = Math.max(window.__m.lcp, e.startTime); }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__m.cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__m.longTasks.push(Math.round(e.duration)); }).observe({ type: 'longtask', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__m.fcp = e.startTime; }).observe({ type: 'paint', buffered: true });
  } catch {}
})();`;

try {
  for (const route of cfg.routes ?? []) {
    s.events.length = 0;
    await s.send('Page.addScriptToEvaluateOnNewDocument', { source: OBS });
    const loaded = s.once('Page.loadEventFired', 20000);
    const t0 = Date.now();
    await s.send('Page.navigate', { url: `${BASE}${route}` });
    await loaded;
    const loadMs = Date.now() - t0;
    await sleep(cfg.wait ?? 4000);

    const m = await s.send('Performance.getMetrics');
    const map = Object.fromEntries((m.metrics ?? []).map((x) => [x.name, x.value]));
    const ev = await s.send('Runtime.evaluate', {
      expression: `(() => ({
        lcp: Math.round(window.__m?.lcp ?? 0),
        fcp: Math.round(window.__m?.fcp ?? 0),
        cls: Number((window.__m?.cls ?? 0).toFixed(4)),
        longTasks: (window.__m?.longTasks ?? []).slice(0, 10),
        longTaskCount: (window.__m?.longTasks ?? []).length,
        nodes: document.getElementsByTagName('*').length,
        scripts: document.scripts.length,
        sheets: document.styleSheets.length,
        imgs: document.images.length,
        canvases: document.querySelectorAll('canvas').length,
      }))()`,
      returnByValue: true,
    });
    const v = ev.result?.value ?? {};
    console.log(
      JSON.stringify(
        {
          route,
          loadMs,
          fcp: v.fcp,
          lcp: v.lcp,
          cls: v.cls,
          longTasks: v.longTasks,
          longTaskCount: v.longTaskCount,
          nodes: v.nodes,
          scripts: v.scripts,
          sheets: v.sheets,
          canvases: v.canvases,
          jsHeapMB: Number(((map.JSHeapUsedSize ?? 0) / 1048576).toFixed(2)),
          domNodes: map.Nodes ?? null,
          layoutCount: map.LayoutCount ?? null,
          recalcStyleCount: map.RecalcStyleCount ?? null,
          taskDurationMs: Math.round((map.TaskDuration ?? 0) * 1000),
        },
        null,
        0
      )
    );
    await s.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: '1' }).catch(() => {});
  }
} finally {
  chrome.kill();
}
