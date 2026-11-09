// 无头 Chrome 截图/巡检驱动（零依赖，CDP over WebSocket）。
//
// 用法：
//   node scripts/shoot.mjs <shot.json>
// shot.json: { "base":"http://127.0.0.1:8742", "out":"../tmp/shots",
//              "shots":[{"name":"desktop-1920","url":"/console/","width":1920,"height":1080}, ...],
//              "probe":[{"name":"routes","urls":["/console","/console/calls","/console/nope"]}] }
//
// 为什么不用 puppeteer/playwright：本波禁止装包，而 CDP 的 Page.captureScreenshot +
// Runtime.evaluate 已经够用（截全页用 captureBeyondViewport）。
//
// ⚠️ --user-data-dir 必须落在工程内（本机 Chrome 对系统临时目录的写入会被 ACL 拒）。
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const cfgPath = process.argv[2];
if (!cfgPath) {
  console.error('usage: node scripts/shoot.mjs <shot.json>');
  process.exit(2);
}
const cfg = JSON.parse(readFileSync(resolve(ROOT, cfgPath), 'utf8'));
const BASE = cfg.base ?? 'http://127.0.0.1:8742';
const OUT = resolve(ROOT, cfg.out ?? '../tmp/shots');
const PROFILE = join(ROOT, '.chrome-profile');
const PORT = 9333;
mkdirSync(OUT, { recursive: true });
mkdirSync(PROFILE, { recursive: true });

const CHROME = cfg.chrome ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const args = [
  '--headless=new',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`,
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-extensions',
  '--hide-scrollbars',
  '--force-device-scale-factor=1',
  '--autoplay-policy=no-user-gesture-required',
  '--font-render-hinting=none',
  'about:blank',
];
const chrome = spawn(CHROME, args, { stdio: ['ignore', 'pipe', 'pipe'] });
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
  throw new Error(`chrome devtools not reachable\n${chromeErr.slice(-2000)}`);
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
        const { resolve: ok, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else ok(msg.result);
      } else if (msg.method) {
        this.events.push(msg);
      }
    });
  }
  send(method, params = {}) {
    this.id += 1;
    const id = this.id;
    return new Promise((ok, reject) => {
      this.pending.set(id, { resolve: ok, reject });
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
  // Chrome 155：/json/new 只接受 PUT（GET 回 405）。
  const target = await fetchJson('/json/new?about:blank', 'PUT');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, err) => {
    ws.addEventListener('open', ok, { once: true });
    ws.addEventListener('error', err, { once: true });
  });
  return new Session(ws);
}

const results = [];
try {
  await fetchJson('/json/version');
  const session = await connect();
  await session.send('Page.enable');
  await session.send('Runtime.enable');
  await session.send('Log.enable');

  for (const shot of cfg.shots ?? []) {
    const w = shot.width ?? 1920;
    const h = shot.height ?? 1080;
    await session.send('Emulation.setDeviceMetricsOverride', {
      width: w,
      height: h,
      deviceScaleFactor: shot.dpr ?? 1,
      mobile: Boolean(shot.mobile),
      screenWidth: w,
      screenHeight: h,
    });
    if (shot.touch) await session.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
    session.events.length = 0;
    if (shot.script) {
      // 注入脚本在页面加载前跑（放 localStorage / 包一层 fetch 之类）
      await session.send('Page.addScriptToEvaluateOnNewDocument', { source: shot.script });
    }
    const loaded = session.once('Page.loadEventFired', 20000);
    await session.send('Page.navigate', { url: `${BASE}${shot.url}` });
    await loaded;
    await sleep(shot.wait ?? 1600);
    // prep：按序执行的页面内脚本（用于「先填令牌再截参数页」这类必须交互才出数据的场景）。
    for (const step of shot.prep ?? []) {
      // 不 awaitPromise：prep 里通常是「像用户那样点一下」，等待交给 prepWait。
      // 之前用 awaitPromise 时 CDP 偶发不回（异步链里有 setTimeout 挂着），整轮卡死。
      await session.send('Runtime.evaluate', { expression: step, awaitPromise: false });
      await sleep(shot.prepWait ?? 900);
    }
    const evalRes = await session.send('Runtime.evaluate', {
      expression: shot.eval ?? '({title: document.title, hash: location.hash, path: location.pathname})',
      returnByValue: true,
      awaitPromise: true,
    });
    const info = evalRes.result?.value;
    if (shot.name) {
      const png = await session.send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: true,
      });
      const file = join(OUT, `${shot.name}.png`);
      writeFileSync(file, Buffer.from(png.data, 'base64'));
      results.push({ name: shot.name, file, url: `${BASE}${shot.url}`, info });
      console.log(`shoot ${shot.name} ${w}x${h} -> ${file}`);
      console.log(`   info ${JSON.stringify(info)}`);
    } else {
      results.push({ name: shot.probeName ?? 'probe', url: `${BASE}${shot.url}`, info });
      console.log(`probe ${shot.url} -> ${JSON.stringify(info)}`);
    }
    if (shot.script) {
      await session.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: '1' }).catch(() => {});
    }
  }

  // 路由巡检：只看「落到的路径 / 是否出现 # / 页面标题」，不截图
  for (const probe of cfg.probe ?? []) {
    for (const path of probe.urls) {
      session.events.length = 0;
      const loaded = session.once('Page.loadEventFired', 20000);
      const resp = await session.send('Page.navigate', { url: `${BASE}${path}` });
      await loaded;
      await sleep(probe.wait ?? 900);
      const evalRes = await session.send('Runtime.evaluate', {
        expression: `({path: location.pathname, hash: location.hash, h1: (document.querySelector('h1')?.textContent ?? '').trim(), body: document.body.innerText.slice(0, 160).replace(/\\s+/g,' ')})`,
        returnByValue: true,
      });
      results.push({ probe: path, status: resp.errorText ?? 200, ...evalRes.result?.value });
      console.log(`probe ${path} -> ${JSON.stringify({ ...(evalRes.result?.value ?? {}), frameId: resp.frameId ? 'ok' : 'none' })}`);
    }
  }
  writeFileSync(join(OUT, 'results.json'), JSON.stringify(results, null, 2));
} finally {
  chrome.kill();
  await sleep(400);
  try {
    rmSync(PROFILE, { recursive: true, force: true });
  } catch {
    /* 文件锁未放时留到下次 */
  }
}
