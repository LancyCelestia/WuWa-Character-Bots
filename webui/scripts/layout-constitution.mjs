// 版式宪法机器门（2026-09-18 用户裁定⑤；2026-09-19 F19 席「补牙」扩容）：
// 构建前扫描 src/**/*.{ts,tsx}，锁定「全部一致」——
//   ① 禁裸 hex 色值（一律走 index.css 语义 token / tone-*）；
//   ② 字号只许五档阶梯 utility（fs-page/fs-card/fs-body/fs-caption/fs-num），
//      禁 text-{xs..5xl} 与 text-[..px] 任意值、style.fontSize 内联；
//      （R5-fix1 2026-09-19 补牙：本条括号臂旧式尾部 \b 在「右方括号之后」永不成立 → 该臂
//       自始空转，任意值字号单写（不配 fs-*）全程静默放行。现改「以长度单位收尾」显式臂，
//       可选 length: 类型提示同收；色值任意值（类型提示 color / hsl(var(--x)) 形态）不沾，
//       颜色归 ①④ 与语义 token 管辖。台账 R5-fix1.md F1。）
//   ③ padding/gap 只用 4px 栅格刻度 {4,8,12,16,24}（Tailwind 后缀 0/1/2/3/4/6）；
//      （R5-fix1 补孔：旧清单缺 pr（右内边距，规则名本已含 pl/ps/pe）、缺 space-x/space-y
//       （兄弟间距属性，且 ⑤ 只认 m 族 → 三者长期执法空白）；数字臂与括号臂同补。台账 F4。）
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
// —— R5 补牙两族（2026-09-19，台账 docs/design/unify-audit-20260919/R5-impl.md）——
//   ⑧ 任意值方括号（arb 族）：F19 §5-C 登记的「下一枚脱栅任意值不得静默入库」收口。
//      管盒子尺寸与定位（size/w/h/min-w/min-h/max-w/max-h/inset/top/right/bottom/left/
//      basis 及其 -x/-y）、焦点环（ring）、色影类（bg/border/
//      fill/stroke/shadow/outline 及 divide）的 `-[…]` 形态；三条放行通道——
//      a) var(--) 通道（与 margin/radius 同口径）；
//      b) 视口单位白名单：盒子值全量为纯视口数值（{vh,svh,lvh,dvh,vw,svw,lvw,dvw,vi,vb}）——
//         栅格是定像素装置，视口相对限高/限宽无从 4px 量化，属「合法脱栅」而非事故
//         （现树命中：logs.tsx max-h-[60vh]、settings-dialog max-h-[90svh]）；
//      c) 规范焦点环白名单：仅 ring-[3px]（shadcn 上游规范值 6 处同构，几何描边语义非
//         间距语义；现树 badge/button/settings-dialog/knowledge/memory-graph，见 R5 §2）。
//      其余任意值 → OFFGRID_RATCHET 棘轮（只减不增；R5 种子 3 枚中的两枚脱栅盒子尺寸已随
//      commit 97eccbc 还清并同步删行，在册余 1 枚 = ⑨ canvas 字面量，见棘轮账旁注）。
//      R5-fix1（2026-09-19）补三型绕行（各带双向自测，台账 R5-fix1.md F3）：
//        · 负号前缀：入口与 ⑤⑥ 同型剥 `-`（旧式裸 `^` 锚定 → 负前缀整族静默放行）；
//        · 透明度后缀：入口剥尾 `/nn` 修饰符（旧式要求右括号收尾 → 带修饰符永不匹配）；
//        · 任意属性形态：另立 arb-prop 小族，行级匹配「方括号内 属性:值」，仅拦清单内
//          尺寸/间距/排印属性（Tailwind 官方逃生口，四族旧规无一能看）。
//      不管：p/gap/m/rounded 的括号（③⑤⑥已管，不双开；③ 的清单自 R5-fix1 起真的含
//      pr/ps/pe/space-x/space-y）、字号任意值括号（②已管——R5-fix1 起该说法才成为事实）、
//      变体选择器（[&>svg] 等）、
//      轨道/属性清单（grid-cols-[1fr_auto] / transition-[color,box-shadow]，非尺寸字面量）。
//      刻意不追且此前未在册的缺口（变换/透明/延迟/outline-offset/行高字距/px 关键字值/
//      含空格与 calc 复合式/未列名任意属性，以及两枚白名单「族形制、不看修饰符链」的宽度）
//      逐条列名与理由见 docs/design/unify-audit-20260919/R5-fix1.md §三——不得当「已管」。
//   ⑨ canvas 字体字面量（canvas-font 族）：`.font = '…Npx…'` 直写绕过五档阶梯单一事实源
//      （index.css 宪法注释「统一由这里钉死」同款语义），出口=行级豁免+基线登记（须用户裁）
//      或探针量算后写绝对值。动态拼接（`${n}px`）无静态数字可审 = 原理性管不到，如实记账。
//      现树 1 处 memory-canvas.tsx:179 → 棘轮在册。
//      【R5-fix1 更正】旧注所写「走 readToken/CSS 变量」在 Canvas2D 上不成立（自定义属性不参与
//      font 计算、相对长度被静默丢弃回落 10px），照做即「账面收口、画布标签变小」，见台账。
// 行级豁免：命中行行尾 `// layout-allow: <理由≥4字>` —— 认领必须命中本文件
//   EXEMPTION_BASELINE（快照口径 2026-09-19 为空集）：新增豁免=红（棘轮只减不增，
//   扩编须用户裁定后由门维护席登记）；空/短理由=红（防旁路后门）。
// 自测锁：本文件内置自测（每次全量跑强制执行，无需参数），正/负样本各若干条，任何规则
//   「补了个假牙」（正则空转/被改坏）即 exit 1——PAGES2 恒真空转与 F19 prescan
//   selftest 抓到 hsl/rounded-sm 两型静默漏判的教训常驻化。
//   两张账各自锁：新族（⑤—⑨）走 lineRuleHits（自测与真扫同一实现）；旧族（①—④ 文本级
//   正则扫描）不经该函数，故 R5-fix1 另立 LEGACY_RULES 命中表，复用同一批正则对象做双向
//   自测——F1 的根因正是「旧族没有自测面，空转臂无人能看见」，堵一次就常驻一次。
//   脱栅棘轮的路由判定（命中 → 进棘轮账 / 带 layout-allow 时改走豁免账）同具纯函数
//   offgridRatchetClaim，双向锁死「两账不串」。
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
// ② 字号阶梯（R5-fix1 修 F1）：档位臂口径不变；括号臂旧式尾部 \b 在「] 之后」永不成立
//    → 恒不匹配（等价于该臂从未存在），现改为「可选 length: 类型提示 + 以长度单位收尾」的
//    显式值形，色值任意值（color: 提示 / hsl(var(--x)) / 十六进制）不构成长度值 → 不误伤，
//    var 通道与 calc 复合式随 ⑧ 同口径放行（诚实缺口，台账在册）。
const OFF_LADDER_TEXT = /\btext-(?:xs|sm|base|lg|xl|2xl|3xl|4xl|5xl|6xl)\b|\btext-\[(?:length:)?[^\]]*[\d.](?:px|rem|em|ch|ex|pt|pc|in|cm|mm|%|svh|lvh|dvh|vh|svw|lvw|dvw|vw|vi|vb)\]/g;
const INLINE_FONT_SIZE = /\bfontSize\s*:/g;
// 4px 栅格刻度：Tailwind 数字后缀 0/1/2/3/4/6（=0/4/8/12/16/24px）。
// PAGES2 修复：旧式 (?!0?\b|1\b|…) 因「空匹配+词边界恒真」整条空转（p-5/gap-8 也抓不到）；
// 改为「刻度数字后不得跟数字或小数点」——p-4/p-0 放行，p-5/p-14/p-0.5/p-1.5 全抓。
// R5-fix1 补孔（F4 同族）：pr（右内边距，旧清单只有 pl/ps/pe）与 space-x/space-y（兄弟间距
// 属性，⑤ 只认 m 族）——三者在两臂均长期缺席 = 执法空白，现补齐。
const OFF_SCALE_SPACING = /\b(?:p|px|py|pt|pb|pl|pr|ps|pe|gap|gap-x|gap-y|space-x|space-y)-(?!0(?![\d.])|1(?![\d.])|2(?![\d.])|3(?![\d.])|4(?![\d.])|6(?![\d.]))(?:\d+(?:\.\d+)?)\b/g;
const OFF_SCALE_ARBITRARY = /\b(?:p|px|py|pt|pb|pl|pr|ps|pe|gap|gap-x|gap-y|space-x|space-y)-\[/g;
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

// —— ⑧ 任意值方括号（arb 族，R5；R5-fix1 补三型绕行）：token 级（splitChain 后的 base），
//    三条放行通道见文件头。盒子/焦点环/色影三张工具清单刻意不含 p/gap/m/rounded/text
//    （③⑤⑥②已管，防一族两红——R5-fix1 起 ②③ 的「已管」才成为事实：②补活括号臂、
//    ③补 pr/ps/pe/space-x/space-y 两臂；旧口径下「已管」对二者均为假，见台账 F1/F4）。——
const ARB_BOX = /^(?:size|[wh]|(?:min|max)-(?:w|h)|(?:inset|top|right|bottom|left|basis)(?:-[xy])?)-\[(.*)\]$/;
const ARB_RING = /^ring-\[(.*)\]$/;
const ARB_COLOR = /^(?:bg|border(?:-[trblxyse])?|outline|fill|stroke|shadow|divide(?:-[trblxy])?)-\[(.*)\]$/;
// 视口单位白名单（宪法注记：栅格=定像素装置，视口相对值无栅格语义可审，族级白名单收编）。
const VIEWPORT_VALUE = /^\d+(?:\.\d+)?(?:vh|svh|lvh|dvh|vw|svw|lvw|dvw|vi|vb)$/;
// 规范焦点环白名单（族定义见 R5 台账 §2；扩编=宪法修改须用户裁定，收窄=随时可行）。
const CANONICAL_RING = new Set(['3px']);
// 透明度修饰符后缀（R5-fix1 F3-②）：旧式三条正则要求「右方括号收尾」，带该后缀永不匹配。
const OPACITY_MODIFIER = /\/\d{1,3}(?:\.\d+)?$/;
function arbViolation(base) {
  // R5-fix1 F3-①：入口与 ⑤⑥ 同型剥负号前缀（旧式裸 ^ 锚定工具名 → 负前缀整族静默放行）；
  // F3-②：同处剥透明度修饰符，剥后仍走同一批白名单通道（视口/var/规范环）。
  const body = base.replace(/^-+/, '').replace(OPACITY_MODIFIER, '');
  let m = ARB_BOX.exec(body);
  if (m) {
    const v = m[1];
    if (/var\(|--/.test(v) || VIEWPORT_VALUE.test(v)) return null;
    return { family: 'arb-box', msg: `任意值盒子尺寸 ${base}（视口单位/ var token 之外禁直写，改栅格刻度或登记 OFFGRID_RATCHET）` };
  }
  m = ARB_RING.exec(body);
  if (m) {
    const v = m[1];
    if (/var\(|--/.test(v) || CANONICAL_RING.has(v)) return null;
    return { family: 'arb-ring', msg: `任意值焦点环宽 ${base}（规范环仅 ring-[3px]，其余走 var(--ring-width) 或登记棘轮）` };
  }
  m = ARB_COLOR.exec(body);
  if (m) {
    const v = m[1];
    if (/var\(|--/.test(v)) return null;
    return { family: 'arb-color', msg: `任意值色/描边/阴影字面量 ${base}（用 index.css 语义 token / var 通道，确需即登记棘轮）` };
  }
  return null;
}

// —— ⑧ 第四型「任意属性形态」（R5-fix1 F3-③）：Tailwind 官方逃生口（方括号内直写 CSS
//    属性:值）绕过工具名解析，②③⑤⑥⑧旧臂无一能看（TOKEN_SPLIT 还会把「变体选择器 +
//    属性形态」腰斩，故本型按行级匹配，不进 base 判定）。只拦清单内的尺寸/间距/描边/
//    排印属性；值必须真是「数字 + 长度单位」才红——TS 标注元组（属性名后跟类型名）与
//    var/calc 通道一律放行。未列名属性（transform/filter/grid-template/line-height/
//    letter-spacing/outline-offset…）刻意不追，缺口在台账 §三在册，不得再声称「已管」。
const ARB_PROP_DENY = new Set([
  'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
  'inset', 'inset-inline', 'inset-block', 'top', 'right', 'bottom', 'left', 'flex-basis',
  'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left', 'margin-inline', 'margin-block',
  'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'padding-inline', 'padding-block',
  'gap', 'row-gap', 'column-gap',
  'border-radius', 'border-width', 'outline-width', 'font-size',
]);
const ARB_PROP_LITERAL = /\[([a-z][a-z0-9-]*):([^\]]*)\]/g;
// 长度字面量：数字（可带小数点）+ 长度单位，且单位后为收尾或分隔（空格/下划线/逗号/括号）。
const ARB_PROP_DIM_VALUE = /^\s*[\d.]+\s*(?:px|rem|em|ch|ex|pt|pc|cm|mm|in|vh|svh|lvh|dvh|vw|svw|lvw|dvw|vi|vb|%)(?=$|[\s_,)/])/;
function arbPropHits(lineText) {
  const out = [];
  for (const m of lineText.matchAll(ARB_PROP_LITERAL)) {
    const prop = m[1];
    const val = m[2];
    if (!ARB_PROP_DENY.has(prop)) continue;
    if (/var\(|--/.test(val)) continue;
    if (!ARB_PROP_DIM_VALUE.test(val)) continue;
    out.push({ family: 'arb-prop', token: m[0], msg: `任意属性形态 ${m[0]}（${prop} 属尺寸/间距/描边/字号轴，旁路工具类与 4px 栅格；改回工具类刻度或 var token，确需脱栅须登记 OFFGRID_RATCHET 并写明理由）` });
  }
  return out;
}

// —— ⑨ canvas 字体字面量（canvas-font 族，R5）：`.font = '…<N>px…'` 行级判定。
//    动态拼接（`${n}px` 无静态数字）原理性管不到，如实记账（R5 台账 §3）。——
const CANVAS_FONT_LITERAL = /\.font\s*=\s*[^;\n]*?(\d+(?:\.\d+)?)px/;
// 五档阶梯 px 值册（index.css @utility fs-* 同源，快照 2026-09-19）——只用于消息提示，
// 判据本身是「字面量即旁路单一事实源」，与值是否在档无关。
const LADDER_PX = new Set(['18', '14', '13', '12', '30']);

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
  const cf = CANVAS_FONT_LITERAL.exec(lineText);
  if (cf) {
    const px = cf[1];
    hits.push({
      family: 'canvas-font',
      token: `canvas-font-${px}px`,
      msg: `canvas 字体字号字面量 ${px}px（旁路五档阶梯单一事实源，用 readToken/CSS 变量或行级豁免+基线登记；${LADDER_PX.has(px) ? `值恰在档（fs 阶梯 ${px}px）仍禁副本` : '值亦脱五档'}）`,
    });
  }
  // ⑧ 第四型（R5-fix1 F3-③）：任意属性形态行级判定，与 ⑨ 同层（token 切分不可靠，见上注）。
  for (const h of arbPropHits(lineText)) hits.push(h);
  const seenRadius = new Map(); // chain -> [tokens]
  const writers = new Map();    // prop#chain -> [tokens]
  const fsTokens = new Set();
  for (const raw of lineText.split(TOKEN_SPLIT)) {
    if (!raw) continue;
    const [chain, base] = splitChain(raw);
    const mv = marginViolation(base);
    if (mv) hits.push({ family: 'margin', token: base, msg: mv });
    const av = arbViolation(base);
    if (av) hits.push({ family: av.family, token: base, msg: av.msg });
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
// 脱栅任意值/canvas 字面量棘轮（R5；键=文件相对路径|命中 token，只减不增）。修一处删一行。
// 种子原为 3 枚：两枚脱栅盒子尺寸已按 R5 台账 §4 的改法（改栅格刻度 20px 档）由主会话随
// commit 97eccbc 还清并同步删行——那是正确的收窄动作，非本席改动；余 1 枚 canvas 字面量
// 长期在册：97eccbc 同时查明「canvas 字号走 readToken」不成立（Canvas2D 的 font 只接受绝对
// 长度、自定义属性不参与计算，相对单位被静默丢弃回落 10px）→ 该枚无「只减」路径，出口只剩
// 探针量算 computed px 或 行级豁免+EXEMPTION_BASELINE 登记（须用户裁），见 R5-fix1 台账 §四。
const OFFGRID_RATCHET = new Map([
  ['components/graph/memory-canvas.tsx|canvas-font-12px', 1],
]);
// 行级豁免基线（layout-allow: 认领登记表）。快照口径 2026-09-19：现树 0 条标记 → 空集。
const EXEMPTION_BASELINE = new Map();

const ALLOW_MARK = /\/\/\s*layout-allow:\s*(.+?)\s*$/;
// ⑧⑨ 族命中是否进「脱栅棘轮账」的纯判定（R5-fix1 抽出常驻自测：旧形制只在一次性手工
// 实证里验过，测试面零常驻）。带 layout-allow: 标记时改走豁免账——两账不串（与权重双写
// 同款纪律），故此处必须先看标记。
function offgridRatchetClaim(hit, lineText) {
  return (hit.family === 'canvas-font' || hit.family.startsWith('arb-')) && !ALLOW_MARK.test(lineText);
}
const weightClaims = new Map(); // key -> [{at}]
const exemptClaims = new Map(); // key -> [{at}]
const offgridClaims = new Map(); // key -> [{at, msg}]（R5 ⑧⑨ 族）
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
      if (offgridRatchetClaim(hit, lineText)) {
        // R5 ⑧⑨：脱栅任意值/canvas 字面量 → OFFGRID_RATCHET 账（带行级 layout-allow 标记时
        // 不静默吞进棘轮，优先走豁免账——与权重双写同款两账不串纪律，判定纯函数常驻自测）。
        const key = `${rel}|${hit.token}`;
        const list = offgridClaims.get(key) || [];
        list.push({ at: `${rel}:${i + 1}`, msg: hit.msg });
        offgridClaims.set(key, list);
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
  // 脱栅任意值/canvas 字面量棘轮（R5）
  for (const [key, extra, allowed] of excessEntries(offgridClaims, OFFGRID_RATCHET)) {
    for (const e of extra) VIOLATIONS.push(`${e.at}  [脱栅] 未登记的任意值/canvas 字面量（OFFGRID_RATCHET 基线 ${allowed}）：改回栅格刻度/var token/白名单通道，确需脱栅须登记棘轮并在台账写明理由（只减不增）：${e.msg}`);
  }
  for (const [key, n] of OFFGRID_RATCHET) {
    const got = offgridClaims.get(key)?.length || 0;
    if (got < n) NOTICES.push(`脱栅棘轮条目富余：${key} 登记 ${n} 实见 ${got} —— 已清理请同步收窄 OFFGRID_RATCHET（棘轮只减不增）`);
  }
}

walk(SRC);
settleRatchets();

// —— 自测锁：每条新规则都必须对负样本（应命中）与正样本（应放行）双双成立；
//    任何一次改动把规则改成空转，这里先红。三张表各自复用真实扫描的同一实现：
//    SELFTEST→lineRuleHits（⑤—⑨）、LEGACY_SELFTEST→LEGACY_RULES 同一批正则对象（①—④）、
//    CLAIM_SELFTEST→offgridRatchetClaim（棘轮路由），计数合流入绿单。——
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
  // ⑧ 任意值方括号：负样本（必须命中）
  ['<span className=\'size-[1.2rem]\' />', 'arb-box'],
  ['<div className=\'w-[37px]\' />', 'arb-box'],
  ['<div className=\'max-h-[400px]\' />', 'arb-box'],
  ['<div className=\'h-[10rem]\' />', 'arb-box'],
  ['<div className=\'min-w-[52ch]\' />', 'arb-box'],
  ['<div className=\'left-[7px]\' />', 'arb-box'],
  ['<div className=\'basis-[33.3%]\' />', 'arb-box'],
  ['<button className=\'focus-visible:ring-[2px]\' />', 'arb-ring'],
  ['<button className=\'ring-[0.5rem]\' />', 'arb-ring'],
  ['<div className=\'bg-[rgba(31,35,41,0.04)]\' />', 'arb-color'],
  ['<div className=\'border-[2px]\' />', 'arb-color'],
  // ⑧ 任意值方括号：正样本（白名单通道与不管形态，near-miss 不得误伤）
  ['<div className=\'flex max-h-[90svh] overflow-y-auto\' />', null],
  ['<div className=\'max-h-[60vh] min-h-svh\' />', null],
  ['<button className=\'focus-visible:ring-[3px] rounded-md\' />', null],
  ['<div className=\'w-[var(--content-max)] ring-[color:var(--ring)]\' />', null],
  ['<div className=\'grid grid-cols-[1fr_auto] transition-[color,box-shadow]\' />', null],
  ['<a className=\'[&>svg]:size-4 has-[>svg]:px-3\' />', null],
  // ⑨ canvas 字体字面量：负样本
  ['context.font = \'12px "Segoe UI", sans-serif\';', 'canvas-font'],
  ['ctx.font = `13px ui-sans-serif`;', 'canvas-font'],
  // ⑨ canvas 字体字面量：正样本（间接引用无静态数字=放行；px 字面量不沾 .font= 不误伤）
  ['context.font = CANVAS_LABEL_FONT;', null],
  ['const labelSpec = \'12px sans-serif\';', null],
  // —— R5-fix1 F3-① 负号前缀：负样本（旧式裸 ^ 锚定 → 整族静默放行）——
  ['<div className=\'-top-[3px]\' />', 'arb-box'],
  ['<div className=\'-inset-x-[5px]\' />', 'arb-box'],
  ['<div className=\'-basis-[10%]\' />', 'arb-box'],
  // R5-fix1 F3-① 正样本：剥负号后白名单通道照旧生效；变换族刻意不在清单（缺口在册）
  ['<div className=\'-top-[50vh]\' />', null],
  ['<div className=\'-rotate-[13.5deg]\' />', null],
  // —— R5-fix1 F3-② 透明度修饰符后缀：负样本（旧式要求右括号收尾 → 永不匹配）——
  ['<div className=\'bg-[oklch(0.5_0.1_200)]/50\' />', 'arb-color'],
  ['<div className=\'border-[2px]/50\' />', 'arb-color'],
  ['<button className=\'focus-visible:ring-[2px]/50\' />', 'arb-ring'],
  // R5-fix1 F3-② 正样本：var 通道 + 后缀照旧放行；普通色板/语义类的后缀不得凭空造出命中
  ['<div className=\'bg-[hsl(var(--card))]/50\' />', null],
  ['<div className=\'ring-ring/50 focus-visible:ring-destructive/20\' />', null],
  // —— R5-fix1 F3-③ 任意属性形态：负样本（Tailwind 官方逃生口，旧四族无一能看）——
  ['<div className=\'[width:13px]\' />', 'arb-prop'],
  ['<div className=\'[font-size:13px]\' />', 'arb-prop'],
  ['<div className=\'[margin:3px_auto]\' />', 'arb-prop'],
  ['<div className=\'[&>*]:[width:7px]\' />', 'arb-prop'],
  ['<div className=\'[padding:1.4rem_0.7rem]\' />', 'arb-prop'],
  // R5-fix1 F3-③ 正样本：var 通道、非长度值（TS 标注元组）、未列名属性、清单外括号形态全绿
  ['<div className=\'[width:var(--content-max)]\' />', null],
  ['type SizeBox = [width: number, height: number];', null],
  ['<div className=\'[transform:translateX(13px)]\' />', null],
  ['<div className=\'[color:var(--brand)] [.border-b]:pb-6\' />', null],
  ['<div className=\'transition-[color,box-shadow] grid-rows-[auto_auto]\' />', null],
];

// —— 旧族（①—④）自测面（R5-fix1）：这六条正则跑在 check() 的文本级 scan() 上、不经
//    lineRuleHits，所以「某一条臂空转」在旧测试面完全隐形——F1 的根因正是如此（② 的括号臂
//    因尾部 \b 恒不成立而自始未生效，台账却记成「② 已管」）。此处复用同一批正则对象做双向
//    锁定（负样本须命中该族、正样本须整行零命中），与真实扫描同一份正则，杜绝两张皮。——
const LEGACY_RULES = [
  ['hex', HEX],
  ['off-ladder-text', OFF_LADDER_TEXT],
  ['inline-font-size', INLINE_FONT_SIZE],
  ['off-scale-spacing', OFF_SCALE_SPACING],
  ['off-scale-arbitrary', OFF_SCALE_ARBITRARY],
  ['palette-class', PALETTE_CLASS],
];

function legacyRuleNames(lineText) {
  const fams = [];
  for (const [name, re] of LEGACY_RULES) if (lineText.match(re)) fams.push(name); // 全局正则：match 归零 lastIndex，不与真扫串味
  return fams;
}

const LEGACY_SELFTEST = [
  // ② 字号五档：任意值长度形态负样本（R5-fix1 F1 的主证——单写、不配 fs-*，⑦ 抓不到）
  ['<div className=\'text-[13px]\' />', 'off-ladder-text'],
  ['<div className=\'text-[13px] mt-1\' />', 'off-ladder-text'],
  ['<div className=\'text-[0.8rem] rounded-md\' />', 'off-ladder-text'],
  ['<div className=\'text-[1.4em]\' />', 'off-ladder-text'],
  ['<div className=\'text-[length:13px]\' />', 'off-ladder-text'],
  ['<div className=\'text-xs\' />', 'off-ladder-text'], // 档位臂回归锁（本次改动不得削弱旧行为）
  // ② 正样本：语义色工具类与「任意值色值」（长度单位之外的值）不得误伤
  ['<span className=\'text-muted-foreground\' />', null],
  ['<span className=\'text-primary\' />', null],
  ['<span className=\'fs-caption text-tone-warn\' />', null],
  ['<div className=\'text-[color:var(--brand)]\' />', null],
  ['<div className=\'text-[hsl(var(--card))]\' />', null],
  // ③ 间距：R5-fix1 F4 补孔负样本（pr / ps / pe / space-x / space-y 括号与数字两臂）
  ['<div className=\'pe-[13px]\' />', 'off-scale-arbitrary'],
  ['<div className=\'space-y-[9px] space-x-[9px]\' />', 'off-scale-arbitrary'],
  ['<div className=\'pr-[13px]\' />', 'off-scale-arbitrary'],
  ['<div className=\'pr-7 space-y-7\' />', 'off-scale-spacing'],
  // ③ 正样本：新列名属性的在档刻度值必须照旧放行（near-miss）
  ['<div className=\'pr-2 pl-6 pe-3 ps-1 space-y-2 gap-x-4\' />', null],
  ['<button className=\'pointer-events-none select-none\' />', null],
];

// 脱栅棘轮路由判定（⑧⑨ 命中 → 棘轮账；带 layout-allow → 豁免账，两账不串）双向自测：
// 这一段是唯一的执法路径，R5 只留过一次性手工实证（台账 §5a/§5b），无常驻锁=下次改坏无人知。
const CLAIM_SELFTEST = [
  ['arb-box', '<div className=\'w-[37px]\' />', true],
  ['arb-prop', '<div className=\'[width:13px]\' />', true],
  ['canvas-font', 'context.font = \'12px sans-serif\';', true],
  ['arb-color', '<div className=\'bg-[oklch(0.5_0.1_200)]/50\' /> // layout-allow: 弹层遮罩色待收', false],
  ['arb-ring', '<button className=\'focus-visible:ring-[2px]\' /> // layout-allow: 焦点环宽待裁', false],
  ['margin', '<div className=\'mt-7\' />', false],
  ['radius', '<div className=\'rounded-sm\' />', false],
];

const SELFTEST_TOTAL = SELFTEST.length + LEGACY_SELFTEST.length + CLAIM_SELFTEST.length + 2; // +2 = 标记解析两断言

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
  // 旧族（①—④ 文本级正则）双向锁
  for (const [line, expect] of LEGACY_SELFTEST) {
    const fams = legacyRuleNames(line);
    if (expect === null) {
      if (fams.length > 0) fails.push(`误伤（旧族）：${line} → 命中 [${fams.join(',')}]（应零命中）`);
    } else if (!fams.includes(expect)) {
      fails.push(`漏判（旧族）：${line} → 命中 [${fams.join(',') || '(空)'}]（应含 ${expect}）`);
    }
  }
  // 脱栅棘轮路由判定双向锁（执法路径本体：进哪本账，不得静默吞、不得两账互串）
  for (const [family, lineText, expect] of CLAIM_SELFTEST) {
    const got = offgridRatchetClaim({ family }, lineText);
    if (got !== expect) fails.push(`棘轮路由失效：family=${family} 该行认领=${got} 应=${expect}（行=${lineText}）`);
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
const offgridN = [...OFFGRID_RATCHET.values()].reduce((a, b) => a + b, 0);
console.log(`版式宪法机器门：全部通过（自测 ${SELFTEST_TOTAL}/${SELFTEST_TOTAL}；hex=0 / 字号五档（含任意值长度形态）/ 间距 4px 栅格（p·m·gap·space 全族）/ 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值方括号（盒子/环/色影/任意属性形态，负号前缀与透明度修饰符同判，var+视口+规范环 3px 白名单）/ canvas 字体字面量；行级豁免 ${exemptN}/${EXEMPTION_BASELINE.size} 基线，棘轮只减不增；权重双写白名单 ${weightN} 处存量在册；脱栅棘轮 ${offgridN} 处存量在册（只减不增））`);
