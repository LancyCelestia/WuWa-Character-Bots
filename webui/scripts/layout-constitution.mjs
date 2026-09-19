// 版式宪法机器门（2026-09-18 用户裁定⑤；2026-09-19 F19 席「补牙」扩容；
// 2026-09-20 R5-fix2 席 ⑧ 族判据倒换=「枚举坏形态」→「默认拒绝 + 显式放行清单」）：
// 构建前扫描 src/**/*.{ts,tsx}，锁定「全部一致」——
//   ① 禁裸 hex 色值（一律走 index.css 语义 token / tone-*）；
//   ② 字号只许五档阶梯 utility（fs-page/fs-card/fs-body/fs-caption/fs-num），
//      禁 text-{xs..5xl} 与 text-[..px] 任意值、style.fontSize 内联；
//      （R5-fix1 2026-09-19 补牙：本条括号臂旧式尾部 \b 在「右方括号之后」永不成立 → 该臂
//       自始空转，任意值字号单写（不配 fs-*）全程静默放行。现改「以长度单位收尾」显式臂。
//       【R5-fix2 账面更正】旧注「色值任意值不沾，颜色归 ①④ 与语义 token 管辖」是未经核实
//       的背书（评审 C2 实证 text-[rgb()/oklch()/hsl() 字面量] 真出 color，而 ① 只拦 hex、
//       ④ 只拦调色板名）——text-[…] 任意值自 R5-fix2 起整体收进 ⑧ 命名空间默认拒绝，
//       本臂仅保留「长度字面量收尾」一形作硬红冗余（保守方向，不撤）。台账 R5-fix2.md §一。）
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
// —— R5 立族、R5-fix1 补三型绕行、R5-fix2 判据倒换（2026-09-19/20，台账 R5-impl.md /
//    R5-fix1.md / R5-fix2.md）——
//   ⑧ 任意值命名空间【默认拒绝 + 显式放行清单】（实现见下方 ⑧′ 代码块，形制、清单、准入
//      判据、编译实证逐条在 R5-fix2.md §二/§三）：凡 utility+`-[…]`/`-(…)` 形、凡
//      `[属性:值]` 形、凡 `[--名:值]` 形 = 命名空间成员，默认即红；绿色出口只有 A1—A8
//      八条放行（var token 读 / 老式色包装 hsl(rgb)(var(--t)) / 纯视口数值·仅盒子几何族 /
//      规范环 ring-[3px] / 网格轨道 auto|fr|minmax / transition 属性名清单 / 纯角度 /
//      无单位行高比例）。calc()/min()/max()/clamp()/env()/theme() 函数形一律不放行
//      （证明不了「任何 token 取值下不脱栅」就拒）；任意属性形零放行（font 简写一枚
//      偷字号+权重+行高，编译实证）；自定义属性**写入**通道 V1—V4 成族封死
//      （类侧 [--x:…]、字面量 '--x:…'、inline style 引号键/计算键、setProperty/cssText），
//      放行 A1/A2 的前提「定义侧受管辖」由此成立：类通道之外只剩 index.css token 台账面。
//      命中族 arb-box/arb-ring/arb-color/arb-prop（沿用名，⑤⑥⑦旧自测锁不破）+ arb-ns/
//      vardef/arb-trunc（新增）——全部硬红，不再进「登记即绿」脱栅棘轮（评审 Z1 洗白路径
//      废除）；p/gap/space/m/rounded 的方括号形由 ③⑤⑥ 的默认拒绝臂管辖，不双开。
//      残余缺口逐条列名（不得再写「已管」二字）见 R5-fix2.md §五。
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
//   R5-fix2 起棘轮账只收 ⑨ canvas 族：offgridRatchetClaim 退化为单族判定，仍具纯函数
//   +双向锁（「arb-*/vardef 不得回灌棘轮账」自此常驻）。
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
//    显式值形。色值任意值（color: 提示 / hsl(var(--x)) / rgb/oklch 字面量）不构成长度值、
//    本臂不沾——但「颜色归 ①④ 管辖」旧注为假（评审 C2 实证），色面自 R5-fix2 起由 ⑧
//    命名空间默认拒绝管辖，本臂只守「长度字面量收尾」一形（冗余保守面，不撤）。
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

// ============================================================================
// ⑧′ 任意值命名空间【默认拒绝 + 显式放行清单】（R5-fix2 判据倒换，台账 R5-fix2.md §二）
// ----------------------------------------------------------------------------
// 旧 ⑧（R5/R5-fix1 版）是「三张工具清单 + 34 枚属性名」的**黑名单枚举**——评审第二轮
// fresh-compile 实证其永远慢攻击者一步：text-[calc(1rem+1px)] 等函数形偷字号（C1）、
// text-[rgb()/oklch()/hsl() 字面量] 偷非 token 色（C2）、arb-prop 值门 fail-open（Y1）、
// [--x:…] 枚内定义 + 圆括号 size-(--x)/p-(--x) 对旧正则零可见（Y2）。根因一句话：
// 「已被别人管/不在清单里」是未经核实的背书。现行判据反向：
//   凡 utility 名 + `-[…]` 或 `-(…)`、凡 `[属性:值]`、凡 `[--名:值]` = 任意值命名空间成员，
//   **默认即红**；绿色出口只有 A1—A8 八条放行，准入判据=按「能否产出 脱栅几何/非 token 色/
//   脱五档字号/脱三档圆角」逐条论证（一行可复核的理由与 Tailwind v4 编译实证全在台账）。
// 可见面=字符串字面量（Tailwind oxide 编译器自身只从字面量提候选 ⇒ 门所见 ⊇ 可挂载面）；
// 字面量内容按空格切 piece；链侧（splitChain 的 chain，如 `data-[state=open]:`/`[&>svg]:`）
// 只产选择器不产声明值，判 base 即判产物。旧 ①—④ 文本级臂原样保留（注释行也抓，保守面）。
// 判定前统一剥净：前导 !、尾随 !、透明度后缀 /n、/n%、/[n]（R5-fix1 F3-① 的负号前缀在
// splitChain 之后剥）。截断形（空格把 -[ / -( 半截留在字面量里：含空格 calc、动态拼接
// `w-[${n}px]`）判红 arb-trunc——它产不出可挂载 CSS，但该形出现在类字面量里就该重写，
// 拒不释（宁误伤勿静放；评审对「空格形 harmless」的判定不构成长绿理由）。
// p/gap/space/m/rounded 的**方括号**形不在本判据重复开火：③⑤⑥ 对它们是「除 var 外全红」
// 的默认拒绝臂（③ 甚至更严——var 也红），双开只造一 token 两红；`-(…)` 圆括号形由本判据
// 全权接管（旧门对 p-(--x) 零可见 = 倒换当场新抓，编译实证 .p-\(--x\){padding:var(--x)}）。
// ============================================================================

const ARB_UTIL_BRACKET = /^([A-Za-z][A-Za-z0-9-]*)-\[([\s\S]*)\]$/;
const ARB_UTIL_PAREN = /^([A-Za-z][A-Za-z0-9-]*)-\(([\s\S]*)\)$/;
const ARB_PROP_FORM = /^\[([A-Za-z][A-Za-z0-9-]*)\s*:\s*([\s\S]*)\]$/;
const ARB_VARDEF_FORM = /^\[--[A-Za-z0-9_-]+\s*:[\s\S]*\]$/;
const ARB_STRING_VARDEF = /^--[A-Za-z0-9_-]+\s*:/; // 字面量内 '--x:37px'（cssText/注入串形态）
// —— A1—A8 放行清单（值形判定全部白名单化——「像不像见过的坏例子」不再是判据）——
// A1 裸 var token 读：x-[var(--n)] / x-[<类型提示>:var(--n)] / x-(--n)（圆括号是它的简写）。
//    产出恒等于 token 本值（编译实证 text-(--x)→color:var(--x)、size-(--x)→width/height:
//    var(--x)）；准入前提「定义侧受管辖」由 V1—V4 写入通道封死成立（见 INLINE_VARDEF_ARMS）。
const A1_VAR = /^(?:[a-z][a-z0-9-]*:\s*)?var\(\s*--[A-Za-z0-9_-]+\s*\)$/i;
// A2 老式色包装 hsl/rgb(a)?(var(--n))，仅 color 工具族与 text：函数只是格式壳、值仍是
//    token（shadcn 上游形制，沿用旧放行）；hsl(220_10%_50%) 这类无 var 的裸函数=红（C2）。
const A2_WRAP = /^(?:hsla|rgba|hsl|rgb)\(\s*var\(\s*--[A-Za-z0-9_-]+\s*\)\s*\)$/;
// A3 纯视口数值（仅盒子几何族）：栅格是定像素装置，视口相对值无从 4px 量化，属「合法脱栅」
//    而非事故（R5 §2 旧裁定沿用）；字号/行高/圆角/环宽四轴不吃此通道（脱五档字号优先）。
const A3_VIEWPORT = /^\d+(?:\.\d+)?(?:vh|svh|lvh|dvh|vw|svw|lvw|dvw|vi|vb)$/;
// A4 规范焦点环 ring-[3px]（shadcn 上游规范值；扩编=宪法修改须用户裁定，收窄随时可行）。
const A4_RING = new Set(['3px']);
// A5 网格轨道 grid-cols/grid-rows：分段只许 auto|0|Nfr|minmax(同形)——fr/auto 是父容器相对
//    分配单位（与 A3 同理），清单里不存在固定长度字面量 ⇒ 造不出脱栅定值。
const A5_TRACK = /^(?:auto|0|\d+(?:\.\d+)?fr|minmax\((?:auto|0|\d+(?:\.\d+)?fr),(?:auto|0|\d+(?:\.\d+)?fr)\))$/;
// A6 transition-[属性名,清单]：纯 CSS 标识符列表，零值字节 ⇒ 四判据不可达。
const A6_IDENT = /^[a-z][a-z0-9-]*$/i;
// A7 纯角度（rotate/-x/-y/-z、skew-x/-y）deg|grad|rad|turn：无长度量纲（旧「变换不追」裁定
//    从此具名封闭——translate-*-[7px] 能造脱栅位移 ⇒ 不在清单 ⇒ 拒，评审「族形制宽度」收口）。
const A7_ANGLE = /^\d+(?:\.\d+)?(?:deg|grad|rad|turn)$/;
// A8 leading-[无单位比例]：比例不产 px（编译实证 line-height:1.07）；length 形
//    leading-[13px] 在清单外=红（行高旁路 fs-* 档位面）。
const A8_RATIO = /^\d+(?:\.\d+)?$/;
const N_GEOM = /^(?:size|[wh]|min-(?:w|h)|max-(?:w|h)|inset(?:-[xy])?|top|right|bottom|left|basis(?:-[xy])?)$/;
const N_COLOR = /^(?:bg|border(?:-[trblxyse])?|outline|fill|stroke|shadow|divide(?:-[trblxy])?)$/;
const N_GRID = /^grid-(?:cols|rows)$/;
const N_ANGLE = /^(?:rotate|rotate-[xyz]|skew-[xy])$/;
// 方括号形已由 ③⑤⑥ 默认拒绝管辖的具名族（括号跳判；圆括号形不跳——那是旧门盲区）。
const N_SKIP_BRACKET = /^(?:p|px|py|pt|pb|pl|pr|ps|pe|gap|gap-x|gap-y|space-x|space-y|m|ms|me|mt|mb|ml|mx|my|rounded(?:-[trblxyse])?)$/;
const VALUE_LOOKS_COLOR = /^(?:color:|#|rgb|rgba|hsl|hsla|oklch|oklab|lab|lch|color-mix|light-dark)/i;
const TRUNC_HINT = /-\[|-\(|\[--|\[[a-z][a-z0-9-]*:/i;
const ARB_DECOR_TRAIL = /(?:!|\/\d+(?:\.\d+)?%?|\/\[[^\]]*\])$/;
const STRING_LITERAL = /'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`/g;
const TEMPLATE_EXPR = /\$\{(?:[^{}]|\{[^{}]*\})*\}/g;
// V2—V4 inline 写入通道（代码侧行形；V1 类侧由 arbPieceViolation 的 VARDEF 判定承担）。
const INLINE_VARDEF_ARMS = [
  [/(['"])(--[A-Za-z0-9_-]+)\1\s*:/, 'inline style 引号键写入（V2）'],
  [/\[\s*(['"])(--[A-Za-z0-9_-]+)\1\s*\]\s*:/, 'inline style 计算键写入（V3）'],
  [/\.setProperty\s*\(\s*(['"])(--[A-Za-z0-9_-]+)\1/, 'setProperty 自定义属性写入（V4）'],
  [/\bcssText\s*=[^\n]*--/, 'cssText 整串样式含自定义属性写入（V4）'],
];
function stripArbDecorations(piece) {
  let s = piece.replace(/^!+/, '');
  let prev;
  do { prev = s; s = s.replace(ARB_DECOR_TRAIL, ''); } while (s !== prev);
  return s;
}
function unbalancedOpen(s) {
  let depth = 0;
  for (const c of s) {
    if (c === '[' || c === '(') depth += 1;
    else if (c === ']' || c === ')') depth = Math.max(0, depth - 1);
  }
  return depth > 0;
}
function arbAllow(name, raw) {
  const v = raw.replace(/\s+/g, '');
  if (A1_VAR.test(raw) || A1_VAR.test(v)) return true; // A1
  if ((N_COLOR.test(name) || name === 'text') && A2_WRAP.test(v)) return true; // A2
  if (name === 'ring') return A4_RING.has(v); // A4（环族具名封闭：视口/其余字面量不吃别的通道）
  if (N_GEOM.test(name) && A3_VIEWPORT.test(v)) return true; // A3
  if (N_GRID.test(name) && v !== '' && v.split('_').every((s) => A5_TRACK.test(s))) return true; // A5
  if (name === 'transition' && v !== '' && v.split(',').every((s) => A6_IDENT.test(s))) return true; // A6
  if (N_ANGLE.test(name) && A7_ANGLE.test(v)) return true; // A7
  if (name === 'leading' && A8_RATIO.test(v)) return true; // A8
  return false;
}
function arbFamilyFor(name, value) {
  if (name === 'ring') return 'arb-ring';
  if (N_COLOR.test(name)) return 'arb-color';
  if (name === 'text' && VALUE_LOOKS_COLOR.test(value)) return 'arb-color'; // C2：非 token 色字面量
  if (N_GEOM.test(name)) return 'arb-box';
  return 'arb-ns'; // 清单外具名/未具名 utility（font/leading-length/tracking/translate/opacity/…）
}
function arbPieceViolation(piece) {
  const stripped = stripArbDecorations(piece);
  if (!stripped) return null;
  if (unbalancedOpen(stripped) && TRUNC_HINT.test(stripped)) {
    return { family: 'arb-trunc', token: stripped, msg: `截断任意值 ${stripped}（空格/动态拼接把 -[ 或 -( 半截留在字面量里——该形产不出可挂载 CSS，但出现在类字面量里就该重写，拒不释）` };
  }
  if (ARB_STRING_VARDEF.test(stripped)) {
    return { family: 'vardef', token: stripped, msg: `字面量内自定义属性写入 ${stripped}（V1—V4 成族封死——token 定义只许活在 index.css）` };
  }
  const [, baseRaw] = splitChain(stripped);
  const base = baseRaw.replace(/^-+/, ''); // 负号前缀（R5-fix1 F3-① 口径沿用）
  if (!base) return null;
  if (ARB_VARDEF_FORM.test(base)) {
    return { family: 'vardef', token: piece, msg: `自定义属性定义 ${base}（类侧 [--name:…] 写入通道成族封死；token 请进 index.css 值册，消费走 x-[var(--token)] / x-(--token)）` };
  }
  if (ARB_PROP_FORM.test(base)) {
    return { family: 'arb-prop', token: piece, msg: `任意属性形 ${base}（默认拒绝零放行，含 var 读也不放：属性名可为 font 等复合简写，一枚偷字号+权重+行高三轴；token 读一律走 utility 形 x-[var(--t)]）` };
  }
  let m = ARB_UTIL_BRACKET.exec(base);
  let bracketed = true;
  if (!m) { m = ARB_UTIL_PAREN.exec(base); bracketed = false; }
  if (!m) return null; // 非任意值形：具名工具类由 ①—⑦ 各轴管辖
  const name = m[1].toLowerCase();
  if (bracketed && N_SKIP_BRACKET.test(name)) return null; // ③⑤⑥ 括号臂已默认拒绝，不双开
  const value = bracketed ? m[2] : `var(${m[2]})`; // x-(--n) ≡ x-[var(--n)]（v4 简写归一）
  if (arbAllow(name, value)) return null;
  return { family: arbFamilyFor(name, value), token: piece, msg: `任意值 ${piece}（命名空间默认拒绝：utility/值形不在 A1—A8 放行清单——calc/min/max/clamp/env/theme 函数形与一切清单外字面量均拒；放行准入见台账 R5-fix2.md §二）` };
}
function arbitraryNamespaceHits(lineText) {
  const hits = [];
  const seen = new Set();
  const push = (h) => {
    if (!h) return;
    const k = `${h.family}|${h.token}`;
    if (!seen.has(k)) { seen.add(k); hits.push(h); }
  };
  for (const lit of lineText.matchAll(STRING_LITERAL)) {
    const body = lit[0].slice(1, -1).replace(TEMPLATE_EXPR, ' '); // 模板插值段=代码非类文本
    for (const piece of body.split(/\s+/)) push(arbPieceViolation(piece));
  }
  for (const [rx, label] of INLINE_VARDEF_ARMS) {
    const m = rx.exec(lineText);
    if (m) push({ family: 'vardef', token: m[0], msg: `${label} ${m[0]}（自定义属性写入通道成族封死——A1/A2 放行的前提「定义侧受管辖」＝只剩 index.css token 台账面）` });
  }
  return hits;
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
  // ⑧′（R5-fix2）任意值命名空间默认拒绝：字符串字面量=编译器可见面，逐 piece 判定；
  // inline 自定义属性写入通道（V2—V4）同函数收口（旧 arbPropHits 行级臂与 arbViolation
  // base 臂均废除——被本函数整体取代，族名沿用则旧自测锁不破）。
  for (const h of arbitraryNamespaceHits(lineText)) hits.push(h);
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
// 脱栅 canvas 字面量棘轮（R5 立账；R5-fix2 起 ⑧′ 任意值命中改硬红、不再入本账——评审 Z1：
// 「登记即永久绿」是最狠违例的最软出口，唯一合法出口=扩充 A1—A8 放行清单=改门=评审面）。
// 键=文件相对路径|命中 token，只减不增。种子原为 3 枚：两枚脱栅盒子尺寸已按 R5 台账 §4 的
// 改法（改栅格刻度 20px 档）由主会话随 commit 97eccbc 还清并同步删行——那是正确的收窄动作，
// 非本席改动；账上仅余 ⑨ canvas 一枚存量：97eccbc 同时查明「canvas 字号走 readToken」不
// 成立（Canvas2D 的 font 只接受绝对长度、自定义属性不参与计算，相对单位被静默丢弃回落
// 10px）→ 该枚无「只减」路径，出口只剩 探针量算 computed px 或 行级豁免+EXEMPTION_BASELINE
// 登记（须用户裁），见 R5-fix1.md §四.2。
const OFFGRID_RATCHET = new Map([
  ['components/graph/memory-canvas.tsx|canvas-font-12px', 1],
]);
// 行级豁免基线（layout-allow: 认领登记表）。快照口径 2026-09-19：现树 0 条标记 → 空集。
const EXEMPTION_BASELINE = new Map();

const ALLOW_MARK = /\/\/\s*layout-allow:\s*(.+?)\s*$/;
// ⑨ 族命中是否进「脱栅棘轮账」的纯判定（R5-fix1 抽出常驻自测；R5-fix2 收缩为单族：
// arb-*/vardef 一律硬红不入账，带 layout-allow 标记时改走豁免账——两账不串纪律不变）。
function offgridRatchetClaim(hit, lineText) {
  return hit.family === 'canvas-font' && !ALLOW_MARK.test(lineText);
}
const weightClaims = new Map(); // key -> [{at}]
const exemptClaims = new Map(); // key -> [{at}]
const offgridClaims = new Map(); // key -> [{at, msg}]（R5-fix2 起仅 ⑨ canvas 族）
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
        // ⑨ canvas 字面量 → OFFGRID_RATCHET 账（带行级 layout-allow 标记时不静默吞进棘轮，
        // 优先走豁免账——与权重双写同款两账不串纪律，判定纯函数常驻自测）。
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
  // 脱栅 canvas 字面量棘轮（R5 立、R5-fix2 收缩为 ⑨ 单族）
  for (const [key, extra, allowed] of excessEntries(offgridClaims, OFFGRID_RATCHET)) {
    for (const e of extra) VIOLATIONS.push(`${e.at}  [脱栅] 未登记的 canvas 字面量（OFFGRID_RATCHET 基线 ${allowed}）：改回五档阶梯/探针量算，确需脱栅须用户裁定后登记棘轮并写明理由（只减不增）：${e.msg}`);
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
  // ⑧′ 任意值（默认拒绝面）：负样本（必须命中）
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
  // ⑧′ 正样本（放行清单通道与具名工具类，near-miss 不得误伤）
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
  // R5-fix1 F3-① 正样本：剥负号后放行通道照旧生效；角度族自 R5-fix2 起具名封闭（A7 在册）
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
  // R5-fix1 F3-③ 其余样本：
  // 【R5-fix2 改判三行 green→red（评审 Z1/任务判据⑤「复合简写要么进清单受管要么拒」：
  //  任意属性形零放行——属性名可为 font 简写，一枚偷字号+权重+行高，编译实证；token 读
  //  一律走 utility 形 x-[var(--t)]，该形有 A1 绿路在，改判不堵任何合法出口。green→red
  //  属收紧方向，不在「放宽即绿」雷区）】
  ['<div className=\'[width:var(--content-max)]\' />', 'arb-prop'],
  ['type SizeBox = [width: number, height: number];', null],
  ['<div className=\'[transform:translateX(13px)]\' />', 'arb-prop'],
  ['<div className=\'[color:var(--brand)] [.border-b]:pb-6\' />', 'arb-prop'],
  ['<div className=\'transition-[color,box-shadow] grid-rows-[auto_auto]\' />', null],
  // —— R5-fix2 C1（函数形/复合简写偷五档字号，fresh-compile 逐条实证真出 font-size）负样本 ——
  ['<div className=\'text-[calc(1rem+1px)]\' />', 'arb-ns'],
  ['<div className=\'text-[min(2rem,3vw)]\' />', 'arb-ns'],
  ['<div className=\'text-[clamp(12px,1.5vw,14px)]\' />', 'arb-ns'],
  ['<div className=\'md:text-[calc(1rem*1.2)]\' />', 'arb-ns'],
  ['<div className=\'text-[calc(1rem+1px)]/50\' />', 'arb-ns'],
  ['<div className=\'[font:600_13px/1_sans]\' />', 'arb-prop'],
  ['<div className=\'[font:13px/1.5_sans-serif]\' />', 'arb-prop'],
  // —— R5-fix2 C1 三证/Y2 主证（[--名:…] 定义 + 消费组合）负样本 ——
  ['<div className=\'[--fs:13px]\' />', 'vardef'],
  ['<div className=\'[font-size:var(--fs)]\' />', 'arb-prop'],
  ['<div className=\'[--fs:13px] [font-size:var(--fs)]\' />', 'vardef'],
  ['<div className=\'[--x:37px]\' />', 'vardef'],
  ['<div className=\'[--x:37px] size-(--x)\' />', 'vardef'],
  ['<div className=\'[--x:13px] [font-size:var(--x)]\' />', 'vardef'],
  // —— R5-fix2 C2（text-[…] 非 token 色字面量，fresh-compile 实证真出 color）负样本 ——
  ['<div className=\'text-[rgb(31,35,41)]\' />', 'arb-color'],
  ['<div className=\'text-[oklch(0.5_0.1_200)]\' />', 'arb-color'],
  ['<div className=\'text-[hsl(220_10%_50%)]\' />', 'arb-color'],
  ['<div className=\'text-[color:rgb(31,35,41)]\' />', 'arb-color'],
  ['<div className=\'sm:text-[rgb(31,35,41)]\' />', 'arb-color'],
  // —— R5-fix2 Y1（arb-prop fail-open：数字开头小写单位之外的真值全洗白）负样本 ——
  ['<div className=\'[width:13PX]\' />', 'arb-prop'],
  ['<div className=\'[width:calc(2rem+2px)]\' />', 'arb-prop'],
  ['<div className=\'[height:calc(1px+2rem)]\' />', 'arb-prop'],
  ['<div className=\'[margin:calc(10px+1px)]\' />', 'arb-prop'],
  ['<div className=\'[grid-template-columns:minmax(0,500px)]\' />', 'arb-prop'],
  ['<div className=\'[line-height:1.8]\' />', 'arb-prop'],
  // —— R5-fix2 「白名单外即自由」收口负样本（旧门因「未列名所以没人管」而绿的形，全部转红）——
  ['<div className=\'font-[550]\' />', 'arb-ns'],
  ['<div className=\'leading-[13px]\' />', 'arb-ns'],
  ['<div className=\'tracking-[0.4px]\' />', 'arb-ns'],
  ['<div className=\'translate-x-[7px]\' />', 'arb-ns'],
  ['<div className=\'-translate-y-[7px]\' />', 'arb-ns'],
  ['<div className=\'opacity-[0.7]\' />', 'arb-ns'],
  ['<div className=\'text-[13PX]\' />', 'arb-ns'],
  ['<div className=\'text-[env(safe-area-inset-top)]\' />', 'arb-ns'],
  ['<div className=\'text-[theme(spacing.5)]\' />', 'arb-ns'],
  ['<div className=\'p-(37px)\' />', 'arb-ns'],
  ['<div className=\'w-(10px)\' />', 'arb-box'],
  // —— R5-fix2 截断形负样本（含空格 calc / 动态拼接：产不出可挂载 CSS 也判红，宁误伤）——
  ['<div className=\'w-[calc(100% - 32px)]\' />', 'arb-trunc'],
  ['const cls = `text-[${n}px]`;', 'arb-trunc'],
  // —— R5-fix2 vardef inline（V1—V4）负样本 ——
  ['const css = \'--x:37px\';', 'vardef'],
  ['<div style={{ \'--x\': \'37px\' }} />', 'vardef'],
  ['<div style={{ [\'--x\']: \'37px\' }} />', 'vardef'],
  ['el.style.setProperty(\'--x\', v);', 'vardef'],
  ['el.style.cssText = \'--x:37px\';', 'vardef'],
  ['el.style.cssText = `color:red;--x:${v}px`;', 'vardef'], // 仅 cssText 臂可见（模板+前缀文本），D4 吃不到的判别样本
  // —— R5-fix2 放行清单正样本 A1—A8（清单合法成员必须仍绿）——
  ['<div className=\'text-(--brand)\' />', null],
  ['<div className=\'size-(--x)\' />', null],
  ['<div className=\'h-(--x)\' />', null],
  ['<div className=\'p-(--x)\' />', null], // 旧门括号盲区，A1 收编（写入通道已封=定义侧可证）
  ['<div className=\'w-[var(--x)]\' />', null],
  ['<div className=\'bg-[var(--x)]/[0.55]\' />', null],
  ['<div className=\'text-[color:var(--brand)]\' />', null],
  ['<div className=\'dark:text-[color:var(--brand)]\' />', null],
  ['<div className=\'text-[length:var(--fs-brand)]\' />', null],
  ['<div className=\'bg-[hsl(var(--card))]\' />', null],
  ['<div className=\'basis-[33vw] h-[100dvh]\' />', null],
  ['<div className=\'grid grid-rows-[auto_1fr_minmax(0,1fr)]\' />', null],
  ['<div className=\'transition-[color,box-shadow,opacity]\' />', null],
  ['<div className=\'rotate-[45deg] skew-x-[3deg]\' />', null],
  ['<div className=\'leading-[1.07]\' />', null],
  // —— R5-fix2 现树真形制 + TS/文案噪声正样本（误伤反证锁）——
  ['<div className=\'has-data-[slot=card-action]:grid-cols-[1fr_auto]\' />', null],
  ['<a className=\'fs-caption [&.active]:text-primary\' />', null],
  ['const v = getComputedStyle(el).getPropertyValue(\'--tone-warn\');', null],
  ['person: \'--chart-1\',', null],
  ['const [a, b] = useFoo();', null],
  ['const d = JSON.parse(\'[1,2]\');', null],
  ['const s = `剩余 ${left} 项`;', null],
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
  // （注：任意值色值的执法面自 R5-fix2 起移交给 ⑧′ 命名空间门——旧注「颜色归①④」为假；
  //  本表正样本仅锁 ② 自身不越界，text-[rgb(…)] 的 arb-color 负锁在 SELFTEST 新表）
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

// 脱栅棘轮路由判定（R5-fix2 起仅 ⑨ canvas 入棘轮账；arb-*/vardef 一律硬红不入账、
// 带 layout-allow 走豁免账——两账不串）双向自测：这一段是唯一的执法路径，常驻锁。
// 【R5-fix2 改判两行 true→false：arb-box/arb-prop 不再进棘轮（「登记即绿」洗白路径废除，
// 评审 Z1）——该行仍必红，只是直进 VIOLATIONS 而非 OFFGRID_RATCHET 账，收紧方向】
const CLAIM_SELFTEST = [
  ['arb-box', '<div className=\'w-[37px]\' />', false],
  ['arb-prop', '<div className=\'[width:13px]\' />', false],
  ['canvas-font', 'context.font = \'12px sans-serif\';', true],
  ['arb-color', '<div className=\'bg-[oklch(0.5_0.1_200)]/50\' /> // layout-allow: 弹层遮罩色待收', false],
  ['arb-ring', '<button className=\'focus-visible:ring-[2px]\' /> // layout-allow: 焦点环宽待裁', false],
  ['margin', '<div className=\'mt-7\' />', false],
  ['radius', '<div className=\'rounded-sm\' />', false],
  ['arb-ns', '<div className=\'font-[550]\' />', false],
  ['vardef', '<div className=\'[--x:37px]\' />', false],
  ['arb-trunc', '<div className=\'w-[calc(100% - 32px)]\' />', false],
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
console.log(`版式宪法机器门：全部通过（自测 ${SELFTEST_TOTAL}/${SELFTEST_TOTAL}；hex=0 / 字号五档（含任意值长度形态）/ 间距 4px 栅格（p·m·gap·space 全族）/ 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值命名空间默认拒绝（utility 方括号+圆括号、任意属性形零放行、[--名:值] 与 inline V2—V4 自定义属性写入成族封死、截断形判红；A1—A8 放行清单=var token 读·老式色包装·纯视口·规范环 3px·网格轨道·transition 清单·纯角度·无单位行高，calc/min/max/clamp/env 函数形一律拒）/ canvas 字体字面量；行级豁免 ${exemptN}/${EXEMPTION_BASELINE.size} 基线，棘轮只减不增；权重双写白名单 ${weightN} 处存量在册；脱栅棘轮 ${offgridN} 处存量在册（canvas 专属，只减不增））`);
