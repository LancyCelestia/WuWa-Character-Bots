// 版式宪法机器门（2026-09-18 用户裁定⑤；2026-09-19 F19 席「补牙」扩容）：
// 构建前扫描 src/**/*.{ts,tsx}，锁定「全部一致」——
//   ① 禁裸 hex 色值（一律走 index.css 语义 token / tone-*）；
//   ② 字号只许五档阶梯 utility（fs-page/fs-card/fs-body/fs-caption/fs-num），
//      禁 text-{xs..5xl} 与 text-[..px] 任意值、style.fontSize 内联；
//   ③ padding/gap 只用 4px 栅格刻度 {4,8,12,16,24}（Tailwind 后缀 0/1/2/3/4/6）；
//   ④ 禁 Tailwind 调色板类名直引（text-white/bg-black/50/text-amber-500 等）——
//      色只许语义 token（primary/muted/accent/destructive/tone-*/chart-*/scrim 等）。
//      （FE2 增补：光扫裸 hex 挡不住调色板类名，宪法③的盲区。）
// —— F19 补牙三族（2026-09-19，台账 docs/design/unify-audit-20260919/F19-gate-teeth.md）——
//   ⑤ margin 全族同栅格：m/ms/me/mt/mb/ml/mx/my 只许 {0,1,2,3,4,6} 或 auto，
//      禁负 margin、禁任意值（var(--) 内联变量除外）——旧门只管 p/gap 不管 m，是执法空白；
//   ⑥ 圆角三档：rounded 只许 md/lg/xl（=14/18/30px 值册，index.css 显式钉值）；
//      rounded-full 以「无方向后缀几何圆」形制族级白名单收编（圆点/胶囊/进度条=9999px
//      几何语义，非档位；快照 12 处，见 F19 台账 §2）；禁裸 rounded/rounded-sm/none/2xl/
//      任意值/带方向的 full；同链（同修饰符前缀）两条 rounded 双写=违例；
//   ⑦ 同元素排版属性双写（F16 规则 F1）：fs-* 是三属性合一类（font-size+line-height+
//      font-weight）且曾对 tailwind-merge 不可见，与 leading-*/font-{weight}/text-{size}
//      并写时胜负由产物层叠裁决（次序不可控，F16 §2.4 实测）→ 写码期直接禁止第二条。
//      修饰符链不同的类（如 [&.active]:font-medium 对 fs-body）按特异性裁决、安全，不算双写
//      （F16 §1.2 裁定）。font-weight×fs-* 双写走「只减不增」棘轮白名单（16 处存量登记，
//      快照口径 2026-09-19 17:5x，逐条清单见 F19 台账 §5；施工期间并发席新增 1 处已收编）。
// 行级豁免：命中行行尾 `// layout-allow: <理由≥4字>` —— 认领必须命中本文件
//   EXEMPTION_BASELINE（快照口径 2026-09-19 为空集）：新增豁免=红（棘轮只减不增，
//   扩编须用户裁定后由门维护席登记）；空/短理由=红（防旁路后门）。
// 自测锁：本文件内置自测（每次全量跑强制执行，无需参数），正/负样本各若干条，任何规则
//   「补了个假牙」（正则空转/被改坏）即 exit 1——PAGES2 恒真空转与 F19 prescan
//   selftest 抓到 hsl/rounded-sm 两型静默漏判的教训常驻化。
// 用法：node scripts/layout-constitution.mjs [--src <目录>]（exit 1 = 有违例，逐条打印
//   文件:行）。--src 为调试/演示口（默认扫本包 src/），正式门禁不带参数。
// 零依赖纯 Node，接入 package.json build 前置。
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ARGV = process.argv.slice(2);
const SRC_IDX = ARGV.indexOf('--src');
const SRC = SRC_IDX >= 0 && ARGV[SRC_IDX + 1]
  ? resolve(ARGV[SRC_IDX + 1])
  : join(fileURLToPath(new URL('.', import.meta.url)), '..', 'src');
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

// ============================================================================
// F19 补牙件（⑤margin / ⑥圆角 / ⑦同元素双写 + 豁免棘轮 + 自测锁）
// ============================================================================

const SCALE_OK = new Set(['0', '1', '2', '3', '4', '6']);

// —— ⑥ 圆角：三档 + full 几何族白名单（token 级解析，杜绝 F19 prescan 抓到的
//    「rounded-sm 被单字方向组截胡静默放行」型漏判）。——
const RADIUS_TIERS_OK = new Set(['md', 'lg', 'xl']);
const RADIUS_DIRS = new Set(['t', 'b', 'l', 'r', 'x', 'y', 's', 'e']);
function radiusViolation(base) {
  // base 例：rounded / rounded-t-lg / rounded-[9px] / rounded-full
  if (base === 'rounded') return '裸 rounded（0.25rem 脱三档值册）';
  if (!base.startsWith('rounded-')) return null;
  const seg = base.slice('rounded-'.length);
  if (seg.startsWith('[')) return /var\(|--/.test(seg) ? null : `任意值圆角 ${base}（许可 md/lg/xl/无方向full）`;
  const parts = seg.split('-');
  const dir = parts.length > 1 && RADIUS_DIRS.has(parts[0]) ? parts[0] : '';
  const tier = dir ? parts[1] : parts[0];
  if (RADIUS_TIERS_OK.has(tier)) return null;
  if (tier === 'full') return dir ? `${base}：rounded-full 白名单仅收编「无方向后缀」几何圆形制` : null;
  return `脱三档圆角 ${base}（许可 md/lg/xl/无方向full）`;
}

// —— ⑤ margin：同 4px 栅格；负值全禁；任意值仅 var(--) 放行；auto 放行。——
function marginViolation(base) {
  // base 例：mt-7 / -mb-2 / m-[9px] / mx-auto / ms-1
  let body = base;
  let neg = false;
  if (body.startsWith('-')) { neg = true; body = body.slice(1); }
  const m = /^m([seltxyb]?)-(.*)$/.exec(body);
  if (!m) return null;
  const [, , suffix] = m;
  if (suffix === 'auto') return neg ? `负 margin ${base}（auto 取负语义可疑，禁）` : null;
  if (neg) return `负 margin ${base}（禁；用 gap/justify/order 替代，确需即申请行级豁免+基线登记）`;
  if (suffix.startsWith('[')) return /var\(|--/.test(suffix) ? null : `任意值 margin ${base}（用栅格刻度 {0,4,8,12,16,24}px 或 var token）`;
  if (/^\d+(?:\.\d+)?$/.test(suffix)) return SCALE_OK.has(suffix) ? null : `margin 脱离 4px 栅格 {0,4,8,12,16,24}：${base}`;
  return `margin 脱档形态 ${base}（许可 {0,1,2,3,4,6}/auto/var）`;
}

// —— ⑦ 同元素排版双写（F16 规则 F1）——
// fs-* 三属性合一；内建类按 F16 §1.5 口径归属属性。font-mono/font-sans 属 font-family，
// 与权重族名不同集，天然不误伤（权重名单精确到九个具名档）。
const FS_UTIL = /^fs-(?:page|card|body|caption|num)$/;
const WEIGHT_CLASS = /^font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black)$/;
const LEADING_CLASS = /^leading-[a-zA-Z0-9[\]()./%#-]+$/;
const TEXTSIZE_CLASS = /^(?:text-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl)$|text-\[[^\]]*(?:px|rem|em)[^\]]*\]$)/;
const TOKEN_SPLIT = /[^A-Za-z0-9_[\]()./%,#*:-]+/;
const COMMENT_LINE = /^\s*(?:\/\/|\*|\/\*)/;

// 修饰符链切分：只在括号深度 0 处按最后一个 ':' 切（`[&_svg:not([class*='size-'])]:size-4`
// 与 `m-[length:var(--x)]` 这类「任意值内含冒号」的 token 不被腰斩）。
function splitChain(tok) {
  let depth = 0;
  let last = -1;
  for (let i = 0; i < tok.length; i += 1) {
    const c = tok[i];
    if (c === '[' || c === '(') depth += 1;
    else if (c === ']' || c === ')') depth -= 1;
    else if (c === ':' && depth === 0) last = i;
  }
  return last < 0 ? ['', tok] : [tok.slice(0, last), tok.slice(last + 1)];
}

// 行级纯函数：返回该行「新规则命中」清单 [{family, token, msg}]，不触碰全局状态
// （自测锁与真实扫描共用同一实现——杜绝「自测过、真扫空转」两张皮）。
function lineRuleHits(lineText) {
  const hits = [];
  const seenRadius = new Map(); // chain -> [tokens]
  const writers = new Map();    // prop#chain -> [tokens]
  const fsTokens = new Set();
  for (const raw of lineText.split(TOKEN_SPLIT)) {
    if (!raw) continue;
    const [chain, base] = splitChain(raw);
    const mv = marginViolation(base);
    if (mv) hits.push({ family: 'margin', token: base, msg: mv });
    if (/^(-)?rounded/.test(base)) {
      const rv = radiusViolation(base.replace(/^-/, ''));
      if (rv) hits.push({ family: 'radius', token: base, msg: rv });
      const list = seenRadius.get(chain) || [];
      if (!list.includes(base)) list.push(base);
      seenRadius.set(chain, list);
    }
    if (FS_UTIL.test(base)) {
      fsTokens.add(base);
      for (const p of ['font-size', 'line-height', 'font-weight']) {
        const k = `${p}#${chain}`; const l = writers.get(k) || []; l.push(base); writers.set(k, l);
      }
    }
    else {
      const p = WEIGHT_CLASS.test(base) ? 'font-weight'
        : LEADING_CLASS.test(base) ? 'line-height'
        : TEXTSIZE_CLASS.test(base) ? 'font-size' : null;
      if (p) { const k = `${p}#${chain}`; const l = writers.get(k) || []; l.push(base); writers.set(k, l); }
    }
  }
  for (const [chain, list] of seenRadius) {
    if (list.length > 1) hits.push({ family: 'radius', token: list.join('+'), msg: `同元素圆角双写（链'${chain}'）：${list.join(' + ')}——一个元素一个圆角档` });
  }
  // 一行 ≥3 枚不同 fs-* 不可能是同一元素挂三档字号，必是登记表/清单字面量
  // （如 lib/utils.ts 的 TYPE_LADDER 注册数组）——双写判定让位于此类登记行。
  if (fsTokens.size >= 3) return hits.filter((h) => !h.family.startsWith('dup-'));
  for (const [key, list] of writers) {
    const uniq = [...new Set(list)];
    if (uniq.length < 2) continue;
    const [prop, chain] = key.split('#');
    hits.push({ family: `dup-${prop}`, token: uniq.sort().join('+'), chain, msg: `同元素 ${prop} 双写（fs-* 多属性合一，胜负靠层叠，禁）：${uniq.join(' + ')}` });
  }
  return hits;
}

// —— 棘轮账（快照口径 2026-09-19 17:36，键=文件相对路径|该行去重排序后的 token 组合，
//    值=允许条数；不含行号——并发编辑行号必漂，键形制随行号免疫。只减不增：
//    认领超量=红；基线富余=提示收窄。清理一处置换一名单，逼账面透明。）——
const WEIGHT_RATCHET = new Map([
  ['components/patterns/patterns.tsx|font-medium+fs-caption', 3],
  ['components/ui/badge.tsx|font-medium+fs-caption', 1],
  ['components/ui/button.tsx|font-medium+fs-body', 1],
  ['pages/affinity.tsx|font-medium+fs-body', 1],
  ['pages/affinity.tsx|font-medium+fs-caption', 1],
  ['pages/calls.tsx|font-medium+fs-caption', 2],
  ['pages/dashboard.tsx|font-medium+fs-caption', 1],
  ['pages/latency.tsx|font-medium+fs-caption', 1],
  ['pages/memory-graph.tsx|font-medium+fs-caption', 2],
  ['pages/tokens.tsx|font-medium+fs-caption', 3],
]);
// 行级豁免基线（layout-allow: 认领登记表）。快照口径 2026-09-19：现树 0 条标记 → 空集。
const EXEMPTION_BASELINE = new Map();

const ALLOW_MARK = /\/\/\s*layout-allow:\s*(.+?)\s*$/;
const weightClaims = new Map(); // key -> [{at}]
const exemptClaims = new Map(); // key -> [{at}]
const NOTICES = [];

function report(rel, lineNo, lineText, family, token, msg) {
  const at = `${rel}:${lineNo}`;
  const m = ALLOW_MARK.exec(lineText);
  if (m) {
    const reason = m[1].trim();
    if (reason.length < 4) {
      VIOLATIONS.push(`${at}  空豁免理由（layout-allow: 后须≥4字真实理由）: ${token}`);
      return;
    }
    const key = `${rel}|${family}|${token}`;
    const list = exemptClaims.get(key) || [];
    list.push({ at });
    exemptClaims.set(key, list);
    return; // 认领成败在收账阶段判（棘轮）
  }
  VIOLATIONS.push(`${at}  [${family}] ${msg}: ${token}`);
}

function check(path) {
  const text = readFileSync(path, 'utf8');
  const rel = relative(SRC, path).split(sep).join('/');
  const lines = text.split('\n');
  const scan = (regex, label) => {
    for (const match of text.matchAll(regex)) {
      const lineIdx = text.slice(0, match.index).split('\n').length - 1;
      report(rel, lineIdx + 1, lines[lineIdx], 'legacy', match[0], label);
    }
  };
  scan(HEX, '裸 hex 色值（用 index.css token / tone-*）');
  scan(OFF_LADDER_TEXT, '阶梯外字号（五档：fs-page/fs-card/fs-body/fs-caption/fs-num）');
  scan(INLINE_FONT_SIZE, '内联 fontSize（用五档阶梯）');
  scan(OFF_SCALE_SPACING, '间距脱离 4px 栅格 {0,4,8,12,16,24}');
  scan(OFF_SCALE_ARBITRARY, '任意值间距（用栅格刻度）');
  scan(PALETTE_CLASS, '调色板类名直引（用 index.css 语义 token / tone-* / scrim）');
  void ALLOWED_LADDER; // 文档性：阶梯类名清单见上。

  // —— F19 新族：逐行扫（注释行不判，F16 §1.5 同口径）——
  lines.forEach((lineText, i) => {
    if (COMMENT_LINE.test(lineText)) return;
    for (const hit of lineRuleHits(lineText)) {
      if (hit.family === 'dup-font-weight' && hit.token.includes('fs-') && hit.token.includes('font-') && !ALLOW_MARK.test(lineText)) {
        // 权重双写 → 先进棘轮账，不直接红；app-shell [&.active] 型特异性安全组合
        // 天然不产命中（链不同），无需在此放行。
        const key = `${rel}|${hit.token}`;
        const list = weightClaims.get(key) || [];
        list.push({ at: `${rel}:${i + 1}`, msg: hit.msg });
        weightClaims.set(key, list);
        continue;
      }
      report(rel, i + 1, lineText, hit.family, hit.token, hit.msg);
    }
  });
}

// 棘轮纯函数：认领超出基线的条目（key -> [claims]，基线 key -> 额度）→ 超额清单。
function excessEntries(claims, baseline) {
  const bad = [];
  for (const [key, list] of claims) {
    const allowed = baseline.get(key) || 0;
    if (list.length > allowed) bad.push([key, list.slice(allowed), allowed]);
  }
  return bad;
}

function settleRatchets() {
  // 权重双写棘轮
  for (const [key, extra, allowed] of excessEntries(weightClaims, WEIGHT_RATCHET)) {
    for (const e of extra) VIOLATIONS.push(`${e.at}  [dup-font-weight] 权重双写未登记（fs-* + font-*）：新增须换 fs-* 档位或登记 WEIGHT_RATCHET（棘轮只减不增，基线 ${allowed}）: ${e.msg}`);
  }
  for (const [key, n] of WEIGHT_RATCHET) {
    const got = weightClaims.get(key)?.length || 0;
    if (got < n) NOTICES.push(`权重双写白名单条目富余：${key} 登记 ${n} 实见 ${got} —— 已清理请同步收窄 WEIGHT_RATCHET（棘轮只减不增）`);
  }
  // 行级豁免棘轮
  for (const [key, extra, allowed] of excessEntries(exemptClaims, EXEMPTION_BASELINE)) {
    for (const e of extra) {
      VIOLATIONS.push(`${e.at}  豁免膨胀（未登记基线）：${key} ×${(exemptClaims.get(key) || []).length}（基线 ${allowed}）——layout-allow 新增须用户裁定后登记 EXEMPTION_BASELINE（棘轮只减不增）`);
    }
  }
  for (const [key, n] of EXEMPTION_BASELINE) {
    const got = exemptClaims.get(key)?.length || 0;
    if (got < n) NOTICES.push(`豁免基线条目富余：${key} 登记 ${n} 认领 ${got} —— 请同步收窄 EXEMPTION_BASELINE（棘轮只减不增）`);
  }
}

walk(SRC);
settleRatchets();

// —— 自测锁：每条新规则都必须对负样本（应命中）与正样本（应放行）双双成立；
//    任何一次改动把规则改成空转，这里先红。共用 lineRuleHits，与真实扫描同一实现。——
const SELFTEST = [
  // margin：负样本（必须命中）
  ['<div className=\'mt-7\' />', 'margin'],
  ['<div className=\'-mb-2\' />', 'margin'],
  ['<div className=\'m-[9px]\' />', 'margin'],
  ['<div className=\'mx-0.5\' />', 'margin'],
  ['<div className=\'ms-14\' />', 'margin'],
  ['<div className=\'-mx-auto\' />', 'margin'],
  ['<div className=\'my-px\' />', 'margin'],
  // margin：正样本（必须零命中）
  ['<div className=\'mt-1 mx-auto ml-6 my-0 me-4\' />', null],
  ['<div className=\'w-max min-w-0 max-w-lg item-center\' />', null],
  ['<div className=\'p-5 gap-8\' />', null], // p/gap 归旧族管辖，新族不抢不重
  ['<div className=\'m-[length:var(--toolong)]\' />', null], // var 通道放行
  // 圆角：负样本
  ['<div className=\'rounded-sm\' />', 'radius'],
  ['<div className=\'rounded\' />', 'radius'],
  ['<div className=\'rounded-2xl\' />', 'radius'],
  ['<div className=\'rounded-[9px]\' />', 'radius'],
  ['<div className=\'rounded-none\' />', 'radius'],
  ['<div className=\'rounded-t-full\' />', 'radius'],
  ['<div className=\'rounded-md rounded-full\' />', 'radius'],
  // 圆角：正样本
  ['<div className=\'rounded-md\' />', null],
  ['<div className=\'rounded-full\' />', null],
  ['<div className=\'rounded-lg sm:rounded-xl\' />', null],
  ['<div className=\'rounded-[var(--r-tile)]\' />', null],
  // 双写：负样本（含 F16 A2 原病灶形态与任意值行高）
  ['<p className=\'fs-caption leading-relaxed\' />', 'dup-line-height'],
  ['<p className=\'fs-body leading-[1.9]\' />', 'dup-line-height'],
  ['<p className=\'fs-body font-medium\' />', 'dup-font-weight'],
  ['<p className=\'fs-caption font-bold\' />', 'dup-font-weight'],
  ['<p className=\'dark:fs-body dark:font-medium\' />', 'dup-font-weight'],
  ['<p className=\'fs-num text-[13px]\' />', 'dup-font-size'],
  ['<p className=\'fs-body text-lg\' />', 'dup-font-size'],
  ['<p className=\'fs-caption fs-body\' />', 'dup-font-size'],
  ['<p className=\'font-medium font-bold\' />', 'dup-font-weight'],
  // 双写：正样本（特异性安全组合与 font-family 必须零命中——app-shell 两行的形制）
  ['<a className=\'fs-caption [&.active]:font-medium\' />', null],
  ['<span className=\'truncate font-mono fs-caption text-muted-foreground\' />', null],
  ['<span className=\'fs-num tabular-nums\' />', null],
  // 登记表字面量（≥3 枚 fs-* 同行为注册清单，非元素双写）必须放行
  ['const TYPE_LADDER = [\'fs-page\', \'fs-card\', \'fs-body\', \'fs-caption\', \'fs-num\'];', null],
];

function selftest() {
  const fails = [];
  for (const [line, expect] of SELFTEST) {
    const fams = new Set(lineRuleHits(line).map((h) => h.family));
    if (expect === null) {
      if (fams.size > 0) fails.push(`误伤：${line} → 命中 [${[...fams].join(',')}]（应放行）`);
    } else if (!fams.has(expect)) {
      fails.push(`漏判：${line} → 命中 [${[...fams].join(',') || '(空)'}]（应含 ${expect}）`);
    }
  }
  // layout-allow 标记解析自测（旁路后门防线）
  if (!ALLOW_MARK.test('// layout-allow: 弹层视口限高')) fails.push('标记解析漏判：正常 // layout-allow: 理由');
  if (ALLOW_MARK.exec('// layout-allow: 短')?.[1].trim().length >= 4) fails.push('空/短理由门失效：layout-allow: 短 应被拒');
  // 棘轮纯函数自测：认领超基线必须判超额（豁免膨胀门不得空转），恰好等于基线不得误报
  {
    const claims = new Map([['k1', [{ at: 'a' }, { at: 'b' }]], ['k2', [{ at: 'c' }]]]);
    const base = new Map([['k1', 1], ['k2', 1]]);
    const bad = excessEntries(claims, base);
    if (bad.length !== 1 || bad[0][0] !== 'k1' || bad[0][1].length !== 1) fails.push('棘轮失效：认领超基线未判红（豁免膨胀门空转）');
    if (excessEntries(new Map([['k2', [{ at: 'c' }]]]), base).length !== 0) fails.push('棘轮误伤：额度内认领被判超额');
  }
  return fails;
}

const selfFails = selftest();
if (selfFails.length > 0) {
  console.error(`版式宪法机器门自测失败（规则空转/误伤 ${selfFails.length} 条，门本体有牙性被破坏，拒绝出具绿单）：`);
  for (const f of selfFails) console.error(`  ${f}`);
  process.exit(1);
}

for (const n of NOTICES) console.log(`提示：${n}`);

if (VIOLATIONS.length > 0) {
  console.error(`版式宪法机器门：${VIOLATIONS.length} 处违例`);
  for (const line of VIOLATIONS) console.error(`  ${line}`);
  process.exit(1);
}
const exemptN = [...exemptClaims.values()].reduce((s, l) => s + l.length, 0);
const weightN = [...WEIGHT_RATCHET.values()].reduce((a, b) => a + b, 0);
console.log(`版式宪法机器门：全部通过（自测 ${SELFTEST.length + 2}/${SELFTEST.length + 2}；hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0；行级豁免 ${exemptN}/${EXEMPTION_BASELINE.size} 基线，棘轮只减不增；权重双写白名单 ${weightN} 处存量在册）`);
