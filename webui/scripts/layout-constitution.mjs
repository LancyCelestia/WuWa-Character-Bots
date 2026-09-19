// 版式宪法机器门（2026-09-18 用户裁定⑤）：构建前扫描 src/**/*.{ts,tsx}，
// 锁定「全部一致」——
//   ① 禁裸 hex 色值（一律走 index.css 语义 token / tone-*）；
//   ② 字号只许五档阶梯 utility（fs-page/fs-card/fs-body/fs-caption/fs-num），
//      禁 text-{xs..5xl} 与 text-[..px] 任意值、style.fontSize 内联；
//   ③ padding/gap 只用 4px 栅格刻度 {4,8,12,16,24}（Tailwind 后缀 0/1/2/3/4/6）；
//   ④ 禁 Tailwind 调色板类名直引（text-white/bg-black/50/text-amber-500 等）——
//      色只许语义 token（primary/muted/accent/destructive/tone-*/chart-*/scrim 等）。
//      （FE2 增补：光扫裸 hex 挡不住调色板类名，宪法③的盲区。）
// 用法：node scripts/layout-constitution.mjs（exit 1 = 有违例，逐条打印 文件:行）。
// 零依赖纯 Node，接入 package.json build 前置。
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(fileURLToPath(new URL('.', import.meta.url)), '..', 'src');
const VIOLATIONS = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const stat = statSync(path);
    if (stat.isDirectory()) walk(path);
    else if (/\.(ts|tsx)$/.test(name)) check(path);
  }
}

const HEX = /#(?:[0-9a-fA-F]{3,8})\b/g;
const OFF_LADDER_TEXT = /\btext-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl|\[[^\]]*\])\b/g;
const INLINE_FONT_SIZE = /\bfontSize\s*:/g;
// 4px 栅格刻度：Tailwind 数字后缀 0/1/2/3/4/6（=0/4/8/12/16/24px）。
// PAGES2 修复：旧式 (?!0?\b|1\b|…) 因「空匹配+词边界恒真」整条空转（p-5/gap-8 也抓不到）；
// 改为「刻度数字后不得跟数字或小数点」——p-4/p-0 放行，p-5/p-14/p-0.5/p-1.5 全抓。
const OFF_SCALE_SPACING = /\b(?:p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y)-(?!0(?![\d.])|1(?![\d.])|2(?![\d.])|3(?![\d.])|4(?![\d.])|6(?![\d.]))(?:\d+(?:\.\d+)?)\b/g;
const OFF_SCALE_ARBITRARY = /\b(?:p|px|py|pt|pb|pl|gap|gap-x|gap-y)-\[/g;
// ④ 调色板直引：色工具前缀 + Tailwind 色板族名（语义名 primary/muted/tone-* 天然不在表内）。
const PALETTE_CLASS = /\b(?:text|bg|border|ring|fill|stroke|from|to|via|outline|decoration|divide|accent|caret|shadow)-(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black|white)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g;
// 允许的五档阶梯（防拼错）。
const ALLOWED_LADDER = /\bfs-(page|card|body|caption|num)\b/;

function check(path) {
  const text = readFileSync(path, 'utf8');
  const rel = relative(SRC, path).split(sep).join('/');
  const scan = (regex, label) => {
    for (const match of text.matchAll(regex)) {
      const line = text.slice(0, match.index).split('\n').length;
      VIOLATIONS.push(`${rel}:${line}  ${label}: ${match[0]}`);
    }
  };
  scan(HEX, '裸 hex 色值（用 index.css token / tone-*）');
  scan(OFF_LADDER_TEXT, '阶梯外字号（五档：fs-page/fs-card/fs-body/fs-caption/fs-num）');
  scan(INLINE_FONT_SIZE, '内联 fontSize（用五档阶梯）');
  scan(OFF_SCALE_SPACING, '间距脱离 4px 栅格 {0,4,8,12,16,24}');
  scan(OFF_SCALE_ARBITRARY, '任意值间距（用栅格刻度）');
  scan(PALETTE_CLASS, '调色板类名直引（用 index.css 语义 token / tone-* / scrim）');
  void ALLOWED_LADDER; // 文档性：阶梯类名清单见上。
}

walk(SRC);

if (VIOLATIONS.length > 0) {
  console.error(`版式宪法机器门：${VIOLATIONS.length} 处违例`);
  for (const line of VIOLATIONS) console.error(`  ${line}`);
  process.exit(1);
}
console.log('版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）');
