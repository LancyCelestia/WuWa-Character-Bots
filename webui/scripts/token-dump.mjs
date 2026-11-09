#!/usr/bin/env node
// 令牌漂移门（W18 阶段 1）：把 design-tokens.json 与真身逐值比对。
//
// 为什么需要：`design-tokens.json` 一旦与代码脱钩，它就变成一份假文档 ——
// 新来的人照着它调，改出来的东西和线上不一样。这类腐烂人眼发现不了：
// 实测过一次，手写报告里的 muted-foreground 还是 0.497，代码已经 0.46。
//
// 三类真身：
//   ① `webui/src/index.css` —— 绝大多数值
//   ② TS 常量文件（`$source` 指向哪个文件就查哪个）
//   ③ Tailwind v4 默认 theme（`--spacing`，不在本仓 CSS 里）
//
// 判据：每条非数组/非布尔/非纯中文说明的 $value，都必须能在它声明的真身里
// 找到逐字对应（空白归一化后）。找不到 = 文档陈旧，当场红。
//
// 复跑：node scripts/token-dump.mjs
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const tokens = JSON.parse(readFileSync(join(ROOT, 'design-tokens.json'), 'utf8'));
const normalize = (s) => String(s).replace(/\s+/g, ' ').trim();

const cache = new Map();
function sourceFor(relPath) {
  // `$source` 允许写成 `webui/src/x.ts:88` 这种人读形态（带仓名与行号）；
  // 落到文件系统时要剥成相对 webui/ 的纯路径。带行号是为了让读者能跳过去，
  // 不代表脚本要按行解析 —— 行号会漂移，逐行比对等于给自己造红。
  const key = (relPath ?? 'src/index.css')
    .replace(/^webui\//, '')
    .replace(/:\d+(-\d+)?$/, '');
  if (!cache.has(key)) {
    const full = resolve(ROOT, key);
    let text;
    try {
      text = readFileSync(full, 'utf8');
    } catch {
      text = '';
    }
    cache.set(key, normalize(text));
  }
  return cache.get(key);
}

const CSS = sourceFor('src/index.css');

/** 递归取所有 { $value } 叶，带上路径与声明的 $source。 */
function walk(node, path, inheritedSource, sink) {
  if (node === null || typeof node !== 'object') return;
  const source = typeof node.$source === 'string' ? node.$source : inheritedSource;
  if ('$value' in node) {
    sink.push({ path, node, source });
    return;
  }
  for (const [key, child] of Object.entries(node)) {
    if (key.startsWith('$')) continue;
    walk(child, path ? `${path}.${key}` : key, source, sink);
  }
}
const leaves = [];
walk(tokens, '', null, leaves);

let checked = 0;
const missing = [];
const skipped = [];

for (const leaf of leaves) {
  const { path, node, source } = leaf;
  const value = node.$value;
  if (Array.isArray(value) || typeof value === 'boolean') {
    skipped.push(path);
    continue;
  }
  if (typeof value === 'number') {
    // 数值型（阈值/常量）在任意真身里以数字或字符串形态出现都算在场。
    checked += 1;
    const hay = source ? sourceFor(source) : CSS;
    if (hay.includes(String(value))) continue;
    missing.push({ path, value, source: source ?? 'src/index.css' });
    continue;
  }
  // 纯中文说明型 $value 不做逐字比对（它们的真身是文档本身）。
  if (/^[\u4e00-\u9fff]/.test(String(value).trim())) {
    skipped.push(path);
    continue;
  }
  // `$external: true` = 真身不在本仓（Tailwind 默认值、行为约定）。这类条目逐字
  // 比对会永远红，而它们恰恰最需要人读，所以显式标出来，不是悄悄放过。
  if (node.$external === true) {
    skipped.push(path);
    continue;
  }
  checked += 1;
  const hay = source ? sourceFor(source) : CSS;
  if (hay.includes(normalize(value))) continue;
  if (node.alias) {
    const aliasDecl = new RegExp(`${node.alias}\\s*:`);
    if (CSS.test ? CSS.test(aliasDecl.source) : aliasDecl.test(CSS)) continue;
  }
  missing.push({ path, value, source: source ?? 'src/index.css' });
}

console.log(`令牌漂移门：比对 ${checked} 条，跳过 ${skipped.length} 条（数组/布尔/中文说明），缺失 ${missing.length} 条`);
if (missing.length) {
  for (const m of missing) {
    console.error(`  缺失 ${m.path} = ${JSON.stringify(m.value)}  （真身 ${m.source}）`);
  }
  process.exit(1);
}
console.log('全部通过：design-tokens.json 与真身无漂移');
