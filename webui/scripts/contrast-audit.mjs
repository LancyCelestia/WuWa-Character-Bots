// 对比度实测门（W18 阶段 1）：采样真实渲染像素，不用计算样式猜底色。
//
// 为什么必须取像素：玻璃/云母面板的 background 是 color-mix(… transparent)，
// 计算样式只给带 alpha 的半透明值；而 WCAG 要的是最终合成到屏幕上的颜色。
// 半透明面板背后是壁纸（1080p 视频帧），计算样式根本不知道它是什么色。
//
// 为什么截两次：只截一次时「框内出现最多的非前景色」会被文字抗锯齿边污染 ——
// 实测把 7 处正常文字判成 1.4~2.1:1 的红。正确做法是把文字变透明再截一次：
// 文字仍占位（版式不变），像素全被清空，剩下纯背景。背景测量因此是精确值。
//
// 前景色取自 getComputedStyle().color 再经 1x1 canvas 落到 sRGB —— 本仓库颜色
// token 全走 oklch，手写解析会失败（实测采样数被打成 0 一次）。
//
// 判据（用户预算）：正文 >=4.5:1；大字（>=24px，或 >=18.66px 且 bold）>=3:1。
// 复跑：node scripts/contrast-audit.mjs tmp/w18b-contrast2.json
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfg = JSON.parse(readFileSync(resolve(ROOT, process.argv[2]), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const PROFILE = join(ROOT, '.chrome-profile.ct');
const PORT = 9341;
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
    '--hide-scrollbars',
    'about:blank',
  ],
  { stdio: ['ignore', 'pipe', 'pipe'] }
);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path, method = 'GET') {
  for (let i = 0; i < 120; i += 1) {
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

/** 页面内：挑出承载信息的文本叶子节点，颜色归一化到 sRGB。 */
const COLLECT = `(() => {
  const px1 = document.createElement('canvas');
  px1.width = 1; px1.height = 1;
  const pxCtx = px1.getContext('2d', { willReadFrequently: true });
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('main *, aside a, header *')) {
    const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own.length) continue;
    const text = own.map((n) => n.textContent).join('').trim();
    if (text.length < 2 || text.length > 160 || seen.has(text)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.bottom < 2 || r.top > innerHeight - 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) < 0.1) continue;
    pxCtx.clearRect(0, 0, 1, 1);
    pxCtx.fillStyle = cs.color;
    pxCtx.fillRect(0, 0, 1, 1);
    const px = pxCtx.getImageData(0, 0, 1, 1).data;
    // 🔴 渐变文字（background-clip:text + color:transparent）必须排除。
    //    它的计算色 alpha=0，量出来是 rgba(0,0,0,0) 对底色的比值（实测 1.47:1 假红）。
    //    真实前景色在 background-image 的渐变停靠点上，只有像素知道——
    //    由 gradient-text-contrast.mjs 单独测。
    if (px[3] === 0) continue;
    seen.add(text);
    out.push({ text: text.slice(0, 40), fg: [px[0], px[1], px[2]], color: cs.color,
               fontSize: cs.fontSize, fontWeight: cs.fontWeight,
               box: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) } });
    if (out.length >= 90) break;
  }
  return out;
})()`;

/**
 * 页面内：把无文字截图画进 canvas，取每个框内 60% 区域的中位色当背景。
 * 内缩 20% 躲开面板自身的 1px 描边与圆角。
 */
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
    const fg = it.fg;
    if (!fg || fg.length < 3) continue;
    const ix = Math.round(it.box.w * 0.2), iy = Math.round(it.box.h * 0.2);
    const x0 = Math.max(0, it.box.x + ix), y0 = Math.max(0, it.box.y + iy);
    const x1 = Math.min(c.width, it.box.x + it.box.w - ix), y1 = Math.min(c.height, it.box.y + it.box.h - iy);
    if (x1 - x0 < 2 || y1 - y0 < 2) continue;
    const data = ctx.getImageData(x0, y0, x1 - x0, y1 - y0).data;
    const rs = [], gs = [], bs = [];
    const step = Math.max(1, Math.floor(((x1 - x0) * (y1 - y0)) / 4000));
    for (let i = 0, n = 0; i < data.length; i += 4, n += 1) {
      if (n % step !== 0) continue;
      rs.push(data[i]); gs.push(data[i + 1]); bs.push(data[i + 2]);
    }
    if (!rs.length) continue;
    const med = (arr) => { const s = [...arr].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
    const bg = [med(rs), med(gs), med(bs)];
    const L1 = lum(fg[0], fg[1], fg[2]), L2 = lum(bg[0], bg[1], bg[2]);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const px = parseFloat(it.fontSize);
    const large = px >= 24 || (Number(it.fontWeight) >= 700 && px >= 18.66);
    rows.push({ text: it.text, color: it.color, fs: it.fontSize, fw: it.fontWeight,
                bg: 'rgb(' + bg.join(' ') + ')',
                ratio: Math.round(ratio * 100) / 100, need: large ? 3 : 4.5 });
  }
  return rows;
})()`;

/** 文字变透明：版式不变、像素清空。伪元素与 SVG 文字一起处理。 */
const BLANK_TEXT = `(() => {
  const st = document.createElement('style');
  st.id = '__contrast_blank';
  st.textContent = '*,*::before,*::after{color:transparent!important;text-shadow:none!important;-webkit-text-fill-color:transparent!important}svg text,svg tspan{fill:transparent!important;stroke:none!important}';
  document.head.appendChild(st);
})()`;
const UNBLANK_TEXT = `(() => { document.getElementById('__contrast_blank')?.remove(); })()`;

const target = await fetchJson('/json/new?about:blank', 'PUT');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((ok, err) => {
  ws.addEventListener('open', ok, { once: true });
  ws.addEventListener('error', err, { once: true });
});
const s = new S(ws);
await s.send('Page.enable');
await s.send('Runtime.enable');
await s.send('Emulation.setDeviceMetricsOverride', {
  width: cfg.width ?? 1440,
  height: cfg.height ?? 900,
  deviceScaleFactor: 1,
  mobile: false,
});

const results = [];
try {
  for (const route of cfg.routes ?? []) {
    s.events.length = 0;
    const loaded = s.once('Page.loadEventFired', 25000);
    await s.send('Page.navigate', { url: `${BASE}${route}` });
    await loaded;
    await sleep(cfg.wait ?? 2600);

    const got = await s.send('Runtime.evaluate', { expression: COLLECT, returnByValue: true });
    if (got.exceptionDetails) {
      console.error(`${route} 采集异常:`, JSON.stringify(got.exceptionDetails).slice(0, 400));
      results.push({ route, error: 'collect-exception' });
      continue;
    }
    const items = got.result?.value ?? [];

    await s.send('Runtime.evaluate', { expression: BLANK_TEXT });
    await sleep(140);
    const shot = await s.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
    await s.send('Runtime.evaluate', { expression: UNBLANK_TEXT });

    const measured = await s.send('Runtime.evaluate', {
      expression: MEASURE(shot.data, items),
      awaitPromise: true,
      returnByValue: true,
    });
    if (measured.exceptionDetails) {
      console.error(`${route} 测量异常:`, JSON.stringify(measured.exceptionDetails).slice(0, 400));
      results.push({ route, error: 'measure-exception' });
      continue;
    }
    const rows = (measured.result?.value ?? []).sort((a, b) => a.ratio - b.ratio);
    const failed = rows.filter((x) => x.ratio < x.need);
    results.push({ route, sampled: rows.length, failed: failed.length, rows });
    console.log(`\n${route}  采样 ${rows.length} 处，不达标 ${failed.length} 处`);
    for (const row of failed.slice(0, 12)) {
      console.log(
        `  FAIL ${String(row.ratio).padStart(5)}:1 (需 ${row.need})  ${row.color} ${row.fs}/${row.fw} on ${row.bg}  「${row.text}」`
      );
    }
  }
} finally {
  writeFileSync(join(ROOT, 'tmp', 'w18b-contrast-result.json'), JSON.stringify(results, null, 2));
  chrome.kill();
}
