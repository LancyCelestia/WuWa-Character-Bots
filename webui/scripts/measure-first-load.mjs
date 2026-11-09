#!/usr/bin/env node
// 首屏关键路径传输量（UI3 性能预算的量尺，非建议）。
//
// 口径：index.html + 它直接 <script type=module src> 引的 JS（gzip）+ <link rel=stylesheet>
// 引的 CSS（gzip）。**不含**路由懒加载的页面 chunk 与图表 chunk——那些是进页后才拉的，
// 预算判的是「打开 /console/ 看到总览，网络上要花多少字节」。
//
// gzip 用 node:zlib 现算（与服务器/浏览器 content-encoding 同量级），不读 dist 里的
// .gz 旁车（本项目不产旁车）。
import { gzipSync, constants } from 'node:zlib';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = join(ROOT, 'dist');
const BUDGET_KB = 600;

const gz = (buf) => gzipSync(buf, { level: constants.Z_BEST_COMPRESSION }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;

const html = readFileSync(join(DIST, 'index.html'), 'utf8');
const refs = new Set();
for (const m of html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)) refs.add(m[1]);
for (const m of html.matchAll(/<link[^>]+href="([^"]+\.css)"/g)) refs.add(m[1]);

const rows = [];
let totalRaw = 0;
let totalGz = 0;
const assetPath = (ref) => {
  const rel = ref.replace(/^\/console\//, '').replace(/^\//, '');
  return join(DIST, rel);
};

const htmlBuf = Buffer.from(html);
totalRaw += htmlBuf.length;
totalGz += gz(htmlBuf);
rows.push(['index.html', htmlBuf.length, gz(htmlBuf)]);

for (const ref of refs) {
  let p;
  try {
    p = assetPath(ref);
    if (!statSync(p).isFile()) continue;
  } catch {
    continue;
  }
  const buf = readFileSync(p);
  const g = gz(buf);
  rows.push([ref.split('/').pop(), buf.length, g]);
  totalRaw += buf.length;
  totalGz += g;
}

for (const [name, raw, g] of rows) {
  console.log(`  ${name.padEnd(34)} ${String(raw).padStart(9)} B  gzip ${String(g).padStart(8)} B`);
}
console.log(`  ${'首屏关键路径合计'.padEnd(30)} ${String(totalRaw).padStart(9)} B  gzip ${String(totalGz).padStart(8)} B  → ${kb(totalGz)} (预算 ${BUDGET_KB} KB)`);

// 落一张全量清单，报告里引用（懒加载 chunk 的体积也要可查）。
const all = readdirSync(join(DIST, 'assets'))
  .filter((n) => n.endsWith('.js') || n.endsWith('.css'))
  .map((n) => ({ n, size: statSync(join(DIST, 'assets', n)).size }))
  .sort((a, b) => b.size - a.size);
console.log('  ── 全部 chunk（前 8）──');
for (const { n, size } of all.slice(0, 8)) console.log(`  ${n.padEnd(34)} ${String(size).padStart(9)} B`);

const over = totalGz > BUDGET_KB * 1024;
console.log(over ? `  ❌ 超出预算 ${kb(totalGz - BUDGET_KB * 1024)}` : `  ✅ 预算内，余量 ${kb(BUDGET_KB * 1024 - totalGz)}`);
process.exit(over ? 1 : 0);
