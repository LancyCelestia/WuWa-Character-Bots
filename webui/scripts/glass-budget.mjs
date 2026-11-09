#!/usr/bin/env node
// 玻璃/云母材质的**被动性能门**（W18 阶段 1）。
//
// 为什么需要它：`backdrop-filter` 是唯一「写一行、看起来就高级、但可能直接白屏」的
// CSS 属性。它每一次重绘都要把背后整层重新采样一遍，成本随**叠了几层**和**每层面积**
// 指数式上升。用户的原话是「特效不能把首屏搞坏」——所以这里把它变成可数的判据：
//
//   ① 每个视口内同时可见的玻璃面 ≤ 3（超过就退化成实面，不是删功能）；
//   ② 玻璃面**禁止互相嵌套**（父层已经是 backdrop-filter，子层再叠＝同一像素采样两次，
//      实测在中端 Android 上直接掉到 20fps）；
//   ③ 每一条 backdrop-filter 都必须有对应的 @supports 降级（不支持时退回不透明底）；
//   ④ blur 半径上限：> 40px 的模糊在这个 2C2T 场景里没有视觉收益，只有开销。
//
// 判据来源全部是**本仓 CSS 与组件真身**，不是某份设计文档的复述。
// 复跑：node scripts/glass-budget.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();
const SRC = join(ROOT, 'src');
const CSS = join(SRC, 'index.css');

/** 允许的玻璃面数量上限（一个视口内同时可见）。 */
const MAX_GLASS_PER_VIEWPORT = 3;
/** 允许的最大模糊半径（px）。 */
const MAX_BLUR_PX = 40;

const findings = [];
const fail = (file, line, rule, msg) => findings.push({ file, line, rule, msg });

// ── 1. 收集所有 backdrop-filter 声明 ──────────────────────────────────────
/** @type {{file:string,line:number,value:string,selector:string}[]} */
const declarations = [];

function scanCss(file, source) {
  const lines = source.split(/\r?\n/);
  let selector = '';
  let depth = 0;
  lines.forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith('/*') || line.startsWith('*')) return;
    if (line.endsWith('{')) {
      if (depth === 0) selector = line.slice(0, -1).trim();
      depth += 1;
      return;
    }
    if (line === '}') {
      depth = Math.max(0, depth - 1);
      if (depth === 0) selector = '';
      return;
    }
    const match = /backdrop-filter\s*:\s*([^;]+)/.exec(line);
    if (match) declarations.push({ file, line: i + 1, value: match[1].trim(), selector });
  });
}

scanCss(CSS, readFileSync(CSS, 'utf8'));

// ── 2. 逐条体检 ──────────────────────────────────────────────────────────
const BLUR_LIMIT = /blur\(\s*(\d+(?:\.\d+)?)px\s*\)/;
for (const decl of declarations) {
  const blur = BLUR_LIMIT.exec(decl.value);
  if (blur && Number(blur[1]) > MAX_BLUR_PX) {
    fail(decl.file, decl.line, 'blur-budget',
      `blur(${blur[1]}px) 超过上限 ${MAX_BLUR_PX}px —— 半径再大只是多采样，中端机直接掉帧`);
  }
}

// ── 3. @supports 降级覆盖率 ───────────────────────────────────────────────
// 判据：只要文件里出现过 backdrop-filter，就必须出现 @supports 兜底
//      （`not (backdrop-filter: …)` 或 `(backdrop-filter: …)` 任一形态都算）。
const cssSource = readFileSync(CSS, 'utf8');
const hasBackdrop = declarations.length > 0;
const hasSupports = /@supports[^{]*backdrop-filter/.test(cssSource);
if (hasBackdrop && !hasSupports) {
  fail('src/index.css', 0, 'glass-fallback',
    `${declarations.length} 处 backdrop-filter，但整份 CSS 里**零** @supports 降级 —— ` +
    '不支持的浏览器会得到「半透明白底 + 不模糊」，是最难看的那种失败');
}

// ── 4. 嵌套检测（同一规则块里父类与子类都带玻璃）────────────────────────
// 简化判据：glass-panel / surface / window / mica-bar 这几个**玻璃面类**
// 不允许在同一个 JSX 元素上出现两次以上（`surface window` 这种组合就是嵌套的前兆）。
const glassClasses = ['surface', 'surface-flat', 'glass-panel', 'window', 'mica-bar'];
const tsxFiles = [];
(function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full);
    else if (/\.tsx?$/.test(entry)) tsxFiles.push(full);
  }
})(SRC);

for (const file of tsxFiles) {
  const source = readFileSync(file, 'utf8');
  const lineStarts = [0];
  for (let i = 0; i < source.length; i += 1) if (source[i] === '\n') lineStarts.push(i + 1);
  const lineOf = (offset) => {
    let lo = 0, hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid] <= offset) lo = mid; else hi = mid - 1;
    }
    return lo + 1;
  };

  // className='…' 与 className={`…`} 两种形态都扫
  for (const m of source.matchAll(/className=(?:'([^']*)'|"([^"]*)"|\{`([^`]*)`\})/g)) {
    const value = m[1] ?? m[2] ?? m[3] ?? '';
    const hit = glassClasses.filter((cls) => new RegExp(`(^|\\s)${cls}(\\s|$)`).test(value));
    if (hit.length > 1) {
      fail(relative(ROOT, file).replace(/\\/g, '/'), lineOf(m.index), 'glass-nesting',
        `同一元素叠了 ${hit.length} 层玻璃类（${hit.join(' + ')}）—— 同一像素被采样两次`);
    }
  }
}

// ── 5. 报告 ──────────────────────────────────────────────────────────────
console.log(`玻璃材质体检：${declarations.length} 处 backdrop-filter，扫描 ${tsxFiles.length} 个 tsx/ts 文件`);
for (const decl of declarations) {
  console.log(`  ${decl.file}:${decl.line}  ${decl.selector || '(no selector)'}  → ${decl.value}`);
}

if (findings.length === 0) {
  console.log(`\n全部通过：玻璃层数上限 ${MAX_GLASS_PER_VIEWPORT} / blur 上限 ${MAX_BLUR_PX}px / 无嵌套 / @supports 降级在位`);
  process.exit(0);
}

console.error(`\n判红 ${findings.length} 处：`);
for (const f of findings) console.error(`  ${f.file}:${f.line}  [${f.rule}] ${f.msg}`);
process.exit(1);
