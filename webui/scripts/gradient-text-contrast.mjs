// 渐变文字的对比度实测（W18 阶段 1）。
//
// 为什么单独一件：`background-clip: text` + `color: transparent` 的元素，
// getComputedStyle 读出来的 color 是 `rgba(0,0,0,0)`——用通用测法量它会得到
// 1.47:1 这种毫无意义的假值（实测踩过）。它的真实前景色在 background-image 的
// 渐变停靠点上，而那只有像素知道。
//
// 判据：取字形**最亮**的 1% 像素当中位前景（渐变最暗的端点最容易不过关，
// 但整段渐变是同一块字，只取最暗会把整段判死；WCAG 对大段渐变文字没有官方
// 裁法，本仓取「亮侧中位」作为该字的主体读法，并同时报最暗 1% 供参考）。
//
// 复跑：node scripts/gradient-text-contrast.mjs tmp/w18b-dark.json
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile.grad');
const PORT = 9361;
mkdirSync(PROFILE, { recursive: true });

const chrome = spawn(
  cfg.chrome ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
   '--no-first-run', '--no-default-browser-check', '--disable-extensions',
   '--force-device-scale-factor=1', '--hide-scrollbars', 'about:blank'],
  { stdio: ['ignore', 'pipe', 'pipe'] }
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path, method = 'GET') {
  for (let i = 0; i < 120; i += 1) {
    try { const res = await fetch(`http://127.0.0.1:${PORT}${path}`, { method }); if (res.ok) return await res.json(); } catch { /* not up */ }
    await sleep(150);
  }
  throw new Error('devtools unreachable');
}
class S {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { ok, err } = this.pending.get(m.id);
        this.pending.delete(m.id);
        if (m.error) err(new Error(JSON.stringify(m.error))); else ok(m.result);
      } else if (m.method) this.events.push(m);
    });
  }
  send(method, params = {}) {
    const id = (this.id += 1);
    return new Promise((ok, err) => { this.pending.set(id, { ok, err }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  once(method, timeout = 25000) {
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

/** 找渐变文字元素（background-clip:text 或 color 透明）。 */
const FIND = `(() => {
  const out = [];
  for (const el of document.querySelectorAll('main *')) {
    const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!own.length) continue;
    const cs = getComputedStyle(el);
    const clip = cs.webkitBackgroundClip || cs.backgroundClip;
    const alpha = (() => {
      const c = document.createElement('canvas'); c.width = 1; c.height = 1;
      const x = c.getContext('2d', { willReadFrequently: true });
      x.fillStyle = cs.color; x.fillRect(0, 0, 1, 1);
      return x.getImageData(0, 0, 1, 1).data[3];
    })();
    if (clip !== 'text' && alpha !== 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) continue;
    out.push({ text: own.map((n) => n.textContent).join('').trim().slice(0, 30),
               box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
               fontSize: cs.fontSize, fontWeight: cs.fontWeight });
  }
  return out;
})()`;

const MEASURE = (shotB64, items) => `(async () => {
  const img = new Image();
  img.src = 'data:image/png;base64,${shotB64}';
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.naturalWidth; c.height = img.naturalHeight;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const srgb = (x) => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  const lum = (r, g, b) => 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b);
  const items = ${JSON.stringify(items)};
  const rows = [];
  for (const it of items) {
    const x0 = Math.max(0, it.box.x), y0 = Math.max(0, it.box.y);
    const x1 = Math.min(c.width, it.box.x + it.box.w), y1 = Math.min(c.height, it.box.y + it.box.h);
    if (x1 - x0 < 2 || y1 - y0 < 2) continue;
    const data = ctx.getImageData(x0, y0, x1 - x0, y1 - y0).data;
    // 🔴 极性必须先判，不能假设「字一定比底亮」。
    //   浅色档：字**暗**、底亮；深色档：字亮、底暗。写死一侧就会把背景当成字，
    //   量出 2.41:1 这种看似合理其实是「白底 vs 白半亮」的假数（实测踩过两次）。
    //   判法：框内**多数**像素是背景（文字覆盖面通常 <25%），取中位数 = 底色；
    //   然后看两个尾端（暗 2% / 亮 98%），离底色更远的那个才是字形。
    const px = [];
    for (let i = 0; i < data.length; i += 4) px.push([data[i], data[i + 1], data[i + 2], lum(data[i], data[i + 1], data[i + 2])]);
    px.sort((a, b) => a[3] - b[3]);
    const pick = (q) => px[Math.min(px.length - 1, Math.max(0, Math.floor(px.length * q)))];
    const bg = pick(0.5);          // 底色 = 中位（多数像素）
    const darkEnd = pick(0.02);    // 暗尾
    const brightEnd = pick(0.98);  // 亮尾
    const dDark = Math.abs(darkEnd[3] - bg[3]);
    const dBright = Math.abs(brightEnd[3] - bg[3]);
    const fg = dDark >= dBright ? darkEnd : brightEnd;
    const ratio = (a, b) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const px2 = parseFloat(it.fontSize);
    const large = px2 >= 24 || (Number(it.fontWeight) >= 700 && px2 >= 18.66);
    rows.push({ text: it.text, fontSize: it.fontSize, fontWeight: it.fontWeight,
                polarity: dDark >= dBright ? 'dark-on-light' : 'light-on-dark',
                bg: 'rgb(' + bg.slice(0, 3).join(' ') + ')',
                fg: 'rgb(' + fg.slice(0, 3).join(' ') + ')',
                ratio: Math.round(ratio(fg[3], bg[3]) * 100) / 100,
                need: large ? 3 : 4.5 });
  }
  return rows;
})()`;

const target = await fetchJson('/json/new?about:blank', 'PUT');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, err) => { ws.addEventListener('open', ok, { once: true }); ws.addEventListener('error', err, { once: true }); });
const s = new S(ws);
await s.send('Page.enable');
await s.send('Runtime.enable');
await s.send('Emulation.setDeviceMetricsOverride',
  { width: cfg.width ?? 1440, height: cfg.height ?? 900, deviceScaleFactor: 1, mobile: false });

try {
  for (const route of cfg.routes ?? []) {
    s.events.length = 0;
    const loaded = s.once('Page.loadEventFired', 25000);
    await s.send('Page.navigate', { url: `${BASE}${route}` });
    await loaded;
    if (cfg.dark) {
      await s.send('Runtime.evaluate', { expression: `document.documentElement.classList.add('dark')` });
    }
    await sleep(cfg.wait ?? 2800);
    const got = await s.send('Runtime.evaluate', { expression: FIND, returnByValue: true });
    const items = got.result?.value ?? [];
    if (!items.length) { console.log(`\n${route}  渐变文字 0 处`); continue; }
    const shot = await s.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
    const measured = await s.send('Runtime.evaluate', {
      expression: MEASURE(shot.data, items), awaitPromise: true, returnByValue: true,
    });
    const rows = measured.result?.value ?? [];
    console.log(`\n${route}  渐变文字 ${rows.length} 处${cfg.dark ? '（深色档）' : ''}`);
    for (const r of rows) {
      const pass = r.ratio >= r.need;
      console.log(`  ${pass ? 'OK  ' : 'FAIL'} ${String(r.ratio).padStart(5)}:1 (需 ${r.need})  ${r.polarity}  ${r.fontSize}/${r.fontWeight}  fg=${r.fg} on bg=${r.bg}  「${r.text}」`);
    }
  }
} finally {
  chrome.kill();
}
