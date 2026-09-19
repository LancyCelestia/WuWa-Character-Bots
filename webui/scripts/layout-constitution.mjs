// 版式宪法机器门（2026-09-18 用户裁定⑤；2026-09-19 F19 席「补牙」扩容；
// 2026-09-20 R5-fix2 席 ⑧ 族判据倒换=「枚举坏形态」→「默认拒绝 + 显式放行清单」；
// 2026-09-21 R5-fix3 席 C-3 修复=⑩ 定义侧 .css 进扫描面 + A1「token 读」整类取消，
//   台账 docs/design/unify-audit-20260919/R5-fix3.md）：
// 构建前扫描 src/ 下 .ts/.tsx/.css 三类文件，锁定「全部一致」——
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
//   ⑧ 任意值命名空间【默认拒绝 + 显式放行清单】（实现见下方 ⑧′ 代码块，准入判据、编译实证
//      逐条在 R5-fix2.md §二/§三 + R5-fix3.md §2）：凡 utility+`-[…]`/`-(…)` 形、凡
//      `[属性:值]` 形、凡 `[--名:值]` 形 = 命名空间成员，默认即红；绿色出口只有放行清单
//      （老式色包装 hsl(rgb)(var(--t)) / 纯视口数值·仅盒子几何族 / 规范环 ring-[3px] /
//      网格轨道 auto|fr|minmax / transition 属性名清单 / 纯角度 / 无单位行高比例）。
//      【R5-fix3（评审 C-3 修复）】旧 A1「裸 var token 读」整类取消：其正当性写成「定义侧
//      受管辖」而 .css 从不进扫描——text-[length:var(--radius-sm)] 编译出 font-size:8px
//      （tailwindcss 4.3.3 实证，--radius-sm:8px 就在 index.css:183）即活体反例；且
//      「utility→受管轴」映射完备性不可证（与 R5-fix2 废除枚举黑名单同一失败模式），
//      不修修补补、整类转默认拒。⑤margin/⑥radius 的 `[var(…)]` 例外臂同步取消（同洞）。
//      token 消费自此只剩受管具名类（fs-*/rounded-md·lg·xl/语义色·tone-*/栅格刻度）。
//      calc()/min()/max()/clamp()/env()/theme() 函数形一律不放行
//      （证明不了「任何 token 取值下不脱栅」就拒）；任意属性形零放行（font 简写一枚
//      偷字号+权重+行高，编译实证）；自定义属性**写入**通道 V1—V4 成族封死
//      （类侧 [--x:…]、字面量 '--x:…'、inline style 引号键/计算键、setProperty/cssText），
//      「定义侧受管辖」自此由 ⑩ 机器兑现（不再是一句未经核实的前提）。
//      命中族 arb-box/arb-ring/arb-color/arb-prop（沿用名，⑤⑥⑦旧自测锁不破）+ arb-ns/
//      vardef/arb-trunc（新增）——全部硬红，不再进「登记即绿」脱栅棘轮（评审 Z1 洗白路径
//      废除）；p/gap/space/m/rounded 的方括号形由 ③⑤⑥ 的默认拒绝臂管辖，不双开。
//      残余缺口逐条列名（不得再写「已管」二字）见 R5-fix2.md §五 + R5-fix3.md §7。
//   ⑩【R5-fix3 新增】定义侧扫描面：walk() 自此含 `.css`。本地样式（src/**/*.css + 相对路径
//      @import 可达文件；包导入跳过并逐条打印提示）机器判：受管命名空间定义带（--radius-md/
//      lg/xl·--r-shell/panel/tile=三档 14/18/30px，可经 var 链归一；--text-* 首长度=五档阶梯；
//      --font-weight-*=≤700；--spacing=唯一值 0.25rem/4px）、受管声明带（font-size=五档、
//      font-weight≤700、border-radius=三档、padding/margin/gap=4px 栅格——正则位置无关，
//      覆盖 @theme/:root/.dark/@layer 包裹/@utility 定义体内部）、hex 直写（css-hex，剥注释后）
//      与 url() 写入（css-url，值册 token 是色/长度/字体栈、永不该是 URL）、@apply 令牌复用
//      ①—⑧ 同一批判定函数。理由（R5-fix3 §1 编译证据）：@theme{--radius-md:37px}/
//      --text-rogue:8px/--spacing:7px 毒化的是**具名类**（rounded-md/text-rogue/p-1），
//      根本不经过 ⑧——只取消读放行堵不住定义侧投毒，两半必须并施。
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
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
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
    else if (/\.css$/i.test(name)) checkCss(path); // R5-fix3 ⑩：定义侧进扫描面
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
  if (seg.startsWith('[')) return `任意值圆角 ${base}（许可 md/lg/xl/无方向full；R5-fix3 起 var token 读同拒——A1 整类取消，圆角只走三档具名类，台账评审 C-3）`;
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
  if (suffix.startsWith('[')) return `任意值 margin ${base}（用栅格刻度 {0,4,8,12,16,24}px；R5-fix3 起 var token 读同拒——A1 整类取消，台账评审 C-3）`;
  if (/^\d+(?:\.\d+)?$/.test(suffix)) return SCALE_OK.has(suffix) ? null : `margin 脱离 4px 栅格 {0,4,8,12,16,24}：${base}`;
  return `margin 脱档形态 ${base}（许可 {0,1,2,3,4,6}/auto）`;
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
//   **默认即红**；绿色出口只有放行清单（A1 已于 R5-fix3 整类取消，现行=A2—A8 七条），准入判据
//   =按「能否产出 脱栅几何/非 token 色/脱五档字号/脱三档圆角」逐条论证（一行可复核的理由与
//   Tailwind v4 编译实证全在台账 R5-fix2.md / R5-fix3.md）。
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
// —— 放行清单（值形判定全部白名单化——「像不像见过的坏例子」不再是判据）——
// 【R5-fix3：A1 已整类取消。】原 A1「裸 var token 读 x-[var(--n)] / x-[<类型提示>:var(--n)] /
// x-(--n)」的前提「定义侧受管辖」从未被机器兑现（walk() 旧版不收 .css），评审 C-3 活体实证：
// text-[length:var(--radius-sm)] 真编译出 font-size: var(--radius-sm) 而 --radius-sm: 8px 就在
// index.css:183（脱五档+破 12px 下限）；同通道 font-[var] → font-weight、rounded-[var] → 任意
// 圆角、m/gap/leading/border/w 各轴全可达（tailwindcss 4.3.3 逐条编译，R5-fix3.md §1）。
// 不选「按值校验保留 A1」而选整类取消的理由：读侧要判安全必须维护 utility→CSS 属性的全量映射，
// 且跨轴洗白（间距合法值被 length: 提示读成字号）结构不可见——映射完备性不可证，与 R5-fix2
// 废除枚举黑名单同因。旧 A2—A8 顺延为现行清单；var 链/命名空间投毒由 ⑩ 定义侧扫描兜住。
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
  // R5-fix3：旧 A1（var token 读）整类取消——不再有「x-[var(--n)]/x-(--n) 恒绿」通道。
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
    return { family: 'vardef', token: piece, msg: `自定义属性定义 ${base}（类侧 [--name:…] 写入通道成族封死；token 请进 index.css 值册——值册由 ⑩ 机器判带，R5-fix3 起类侧无 token 读通道，消费走 fs-*/rounded-md·lg·xl/语义色等受管具名类）` };
  }
  if (ARB_PROP_FORM.test(base)) {
    return { family: 'arb-prop', token: piece, msg: `任意属性形 ${base}（默认拒绝零放行，含 var 读也不放：属性名可为 font 等复合简写，一枚偷字号+权重+行高三轴；token 消费走受管具名类，类侧无 var 读通道=R5-fix3 判据）` };
  }
  let m = ARB_UTIL_BRACKET.exec(base);
  let bracketed = true;
  if (!m) { m = ARB_UTIL_PAREN.exec(base); bracketed = false; }
  if (!m) return null; // 非任意值形：具名工具类由 ①—⑦ 各轴管辖
  const name = m[1].toLowerCase();
  if (bracketed && N_SKIP_BRACKET.test(name)) return null; // ③⑤⑥ 括号臂已默认拒绝，不双开
  const value = bracketed ? m[2] : `var(${m[2]})`; // x-(--n) ≡ x-[var(--n)]（v4 简写归一）
  if (arbAllow(name, value)) return null;
  return { family: arbFamilyFor(name, value), token: piece, msg: `任意值 ${piece}（命名空间默认拒绝：utility/值形不在 A2—A8 放行清单——var token 读整类已取消（R5-fix3/C-3），calc/min/max/clamp/env/theme 函数形与一切清单外字面量均拒；放行准入见台账 R5-fix2.md §二 + R5-fix3.md §2）` };
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
    if (m) push({ family: 'vardef', token: m[0], msg: `${label} ${m[0]}（自定义属性写入通道成族封死——「定义侧受管辖」= 类通道之外只剩 index.css token 台账面，且台账面自身自 R5-fix3 起进 ⑩ 扫描受值带机判）` });
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

// ============================================================================
// ⑩ 定义侧扫描面（R5-fix3，评审 C-3）：本地 .css 值带机判——「定义侧受管辖」的机器兑现。
// 类侧 A1 取消只堵住「任意值读 token」；@theme{--radius-md:37px}/--text-rogue:8px/
// --spacing:7px 毒化的是具名类（rounded-md/text-rogue/p-1，tailwindcss 4.3.3 编译实证，
// R5-fix3.md §1 P1/P2/P3/P5/P7），不经 ⑧——故定义侧必须进扫描。判**可机判带**：
//   受管命名空间定义（--radius-md/lg/xl·--r-shell/panel/tile=三档 14/18/30px（var 链归一，
//   链不可解=fail-closed 拒）；--text-* 首长度=五档阶梯；--font-weight-*=≤700；
//   --spacing=唯一 {0.25rem,4px}——四者都注册工具类、都是「一枚定义毒化一族」的面）；
//   受管声明（font-size=五档 / font-weight≤700 / border-radius=三档 / padding|margin|gap
//   族=4px 栅格 / font 简写零放行）——属性名正则位置无关，@layer 包裹与 @utility 定义体
//   内部同在面上；hex 直写（剥注释后，与 ① 同正则对象同源）；url() 写入（值册 token 是
//   色/长度/字体栈、永不该是 URL——@import url() 语法除外）；@apply 令牌复用 ①—⑧ 同一批
//   判定函数（CSS_LEGACY_ARMS 直接引用 LEGACY 正则对象本体，杜绝两张皮）。
// 不可机判残余（值册颜色语义、--radius-sm 等无受管消费面的遗留定义、行高带、html 内联面）
// 逐条具名登记于 R5-fix3.md §7，不写「已管」。棘轮纪律：css-* 全为硬红不入任何账。
// ============================================================================

const CSS_CUSTOM_DEF = /(^|[{;\s])(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+)/g;
const CSS_DECL = /(^|[{;\s])([a-z][a-z0-9-]*)\s*:\s*([^;{}]+)/g;
const CSS_URL_ALL = /\burl\s*\(/gi;
const CSS_LEN = /\b(\d+(?:\.\d+)?)(px|rem)\b/gi;
const CSS_IMPORT = /@import\s+(?:url\(\s*)?['"]([^'"]+)['"]/gi;
const CSS_APPLY = /@apply\s+([^;{}]+)/gi;
const TIER_DEF_NAMES = new Set(['--radius-md', '--radius-lg', '--radius-xl', '--r-shell', '--r-panel', '--r-tile']);
const CSS_LADDER_PX = [12, 13, 14, 18, 30]; // 五档阶梯 px 值册（@utility fs-* 同源快照，与 LADDER_PX 字符串册同值）
const CSS_TIER_DECL = /^border(?:-[a-z-]+)?-radius$/i;
const CSS_GRID_DECL = /^(?:padding|margin|gap|row-gap|column-gap)(?:-(?:inline|block|top|right|bottom|left|inline-start|inline-end|block-start|block-end))?$/i;
const CSS_WEIGHT_NAMES_OK = new Set(['thin', 'extralight', 'light', 'normal', 'medium', 'semibold', 'bold']); // 具名 ≤700 集；extrabold/black 拒
// 与 LEGACY_RULES 同一批正则对象（真扫=自测同一实现的定义侧版本）。
const CSS_LEGACY_ARMS = [
  ['hex', HEX], ['off-ladder-text', OFF_LADDER_TEXT], ['inline-font-size', INLINE_FONT_SIZE],
  ['off-scale-spacing', OFF_SCALE_SPACING], ['off-scale-arbitrary', OFF_SCALE_ARBITRARY], ['palette-class', PALETTE_CLASS],
];
function stripCssComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
}
function cssLenPx(num, unit) { return String(unit).toLowerCase() === 'rem' ? num * 16 : num; }
function cssLengths(value) {
  const out = [];
  for (const m of value.matchAll(CSS_LEN)) out.push(cssLenPx(parseFloat(m[1]), m[2]));
  return out;
}
function cssResolveValue(value, defs, depth = 0) {
  // var(--x) 整值链归一（全部定义参与，含 .dark 二次定义——任一终值脱带即红，保守向）；
  // 含 fallback、不可解、循环 → 原样返回（band* 判不过 = fail-closed）。
  const t = value.trim();
  const m = /^var\(\s*(--[A-Za-z0-9_-]+)\s*\)$/i.exec(t);
  if (!m || depth > 8) return [t];
  const list = defs.get(m[1].toLowerCase());
  if (!list || !list.length) return [`var(${m[1]})`];
  const out = [];
  for (const v of list) out.push(...cssResolveValue(v, defs, depth + 1));
  return out;
}
function cssBandTier(t) {
  if (/^0$/i.test(t)) return true;
  const m = /^(\d+(?:\.\d+)?)(px|rem)$/i.exec(t);
  return !!m && [14, 18, 30].includes(cssLenPx(parseFloat(m[1]), m[2]));
}
function cssBandLadderFirst(t) {
  const m = /^(\d+(?:\.\d+)?)(px|rem)$/i.exec(t);
  return !!m && CSS_LADDER_PX.includes(cssLenPx(parseFloat(m[1]), m[2]));
}
function cssBandLadderValue(v) {
  const seg = String(v).split('/')[0];
  if (/calc|clamp|env|min\(|max\(|color|var\(/i.test(seg)) {
    const lens = cssLengths(seg);
    return lens.length > 0 && CSS_LADDER_PX.includes(lens[0]) && !/var\(|calc|clamp|env|min\(|max\(/i.test(seg);
  }
  const lens = cssLengths(seg);
  return lens.length > 0 && CSS_LADDER_PX.includes(lens[0]);
}
function cssBandWeight(t) {
  if (/^\d+(?:\.\d+)?$/.test(t)) { const n = parseFloat(t); return n >= 1 && n <= 700; }
  return CSS_WEIGHT_NAMES_OK.has(t.toLowerCase());
}
function cssBandGrid(v) {
  if (/var\(|calc|clamp|env|min\(|max\(/i.test(v)) return false; // 函数形不可自证=拒（与 ⑧ 同纪律）
  return cssLengths(v).every((px) => px === 0 || Math.abs(px % 4) < 1e-9);
}
function cssBandTierValue(v) {
  if (/var\(|calc|clamp|env|min\(|max\(/i.test(v)) return false;
  const ls = cssLengths(v);
  if (!ls.length) return /%|auto|0$/i.test(v); // 百分比几何圆/关键字放行，绝对长度必须入三档
  return ls.every((px) => px === 0 || [14, 18, 30].includes(px));
}
function cssFileHits(rawText) {
  const text = stripCssComments(rawText);
  const linesArr = text.split('\n');
  const lineAt = (idx) => text.slice(0, idx).split('\n').length;
  const hits = [];
  const push = (line, family, token, msg) => hits.push({ line, family, token, msg });
  // 定义表（同名多定义全部保留：:root 与 .dark 各一条，任一脱带即红）
  const defs = new Map();
  for (const m of text.matchAll(CSS_CUSTOM_DEF)) {
    const key = m[2].toLowerCase();
    const arr = defs.get(key) || [];
    arr.push(m[3].trim());
    defs.set(key, arr);
  }
  // 全局面：hex（① 同正则）与 url()（@import url() 语法行除外）
  for (const m of text.matchAll(HEX)) push(lineAt(m.index), 'css-hex', m[0], '样式表内裸 hex 色值（色值只许以 oklch/rgb/var 链等形态进值册——与 ① 同门）');
  for (const m of text.matchAll(CSS_URL_ALL)) {
    const ln = lineAt(m.index);
    if (/@import/i.test(linesArr[ln - 1] || '')) continue;
    push(ln, 'css-url', m[0], 'url() 写入样式（值册 token 是色/长度/字体栈、永不该是 URL——远端拉取/数据夹带面，R5-fix3 §2 判据）');
  }
  // 受管命名空间定义带
  for (const m of text.matchAll(CSS_CUSTOM_DEF)) {
    const name = m[2].toLowerCase();
    const value = m[3].trim();
    const ln = lineAt(m.index);
    if (TIER_DEF_NAMES.has(name)) {
      for (const t of cssResolveValue(value, defs)) {
        if (!cssBandTier(t)) push(ln, 'css-tier', `${name}:${value}`, `圆角档位 token 定义脱三档 ${name}→${t}（许可 14/18/30px 或归一到该集的 var 链；rounded-md/lg/xl 具名类消费此值——@theme/:root/@layer/@utility 内写同判，编译实证 P1）`);
      }
    }
    if (/^--text-/.test(name) && !/--line-height$/.test(name)) {
      for (const t of cssResolveValue(value, defs)) {
        if (!cssBandLadderFirst(t)) push(ln, 'css-ladder', `${name}:${value}`, `--text-* 定义首长度脱五档阶梯（→${t}）——@theme 的 --text-* 命名空间注册新字号具名类（text-rogue→8px 编译实证 P2），绕过 ② 的档位名单，只能锁定义带`);
      }
    }
    if (/^--font-weight-/.test(name)) {
      for (const t of cssResolveValue(value, defs)) {
        if (!cssBandWeight(t)) push(ln, 'css-weight', `${name}:${value}`, `字重 token 脱带（→${t}，许可数值 1–700 或具名 thin..bold）——@theme --font-weight-* 注册 font-* 具名类（font-heavy→900 编译实证 P3）`);
      }
    }
    if (name === '--spacing') {
      for (const t of cssResolveValue(value, defs)) {
        if (!/^(?:0\.25rem|4px)$/i.test(t)) push(ln, 'css-spacing', `--spacing:${value}`, `--spacing 重定义只许 0.25rem/4px（→${t}）——一枚定义毒化全树 p/m/gap/w/h 数字刻度（p-1=calc(var(--spacing)*1) 编译实证 P5）`);
      }
    }
  }
  // 受管声明带（属性名精确匹配，位置无关 → @layer/@utility 体内声明同在面上）
  for (const m of text.matchAll(CSS_DECL)) {
    const name = m[2].toLowerCase();
    const value = m[3].trim();
    const ln = lineAt(m.index);
    if (name === 'font') { push(ln, 'css-ladder', `font:${value}`, 'css `font` 简写声明零放行（一枚偷字号+权重+行高三轴——与任意属性形同判据）'); continue; }
    if (name === 'font-size') {
      let ok = cssBandLadderValue(value);
      if (!ok && /^var\(/i.test(value)) ok = cssResolveValue(value, defs).every(cssBandLadderFirst);
      if (!ok) push(ln, 'css-ladder', `font-size:${value}`, `样式内 font-size 声明脱五档阶梯 ${CSS_LADDER_PX.join('/')}px（字号只许 fs-* @utility 五档与图表 12px 同值位——@layer 包裹/@utility 体内同判，编译实证 P6/P7）`);
      continue;
    }
    if (name === 'font-weight') {
      let ok = /^\d+(?:\.\d+)?$/.test(value) ? cssBandWeight(value) : CSS_WEIGHT_NAMES_OK.has(value.toLowerCase());
      if (!ok && /^var\(/i.test(value)) ok = cssResolveValue(value, defs).every(cssBandWeight);
      if (!ok) push(ln, 'css-weight', `font-weight:${value}`, '样式内 font-weight 声明脱带（许可 1–700 数值或具名 thin..bold；≤700 宪法同轴）');
      continue;
    }
    if (CSS_TIER_DECL.test(name)) {
      let ok = cssBandTierValue(value);
      if (!ok && /^var\(/i.test(value)) ok = cssResolveValue(value, defs).every(cssBandTier);
      if (!ok) push(ln, 'css-tier', `border-radius 族:${value}`, '样式内圆角声明脱三档 {14,18,30}px（或百分比几何圆）——与 ⑥ 具名类同档');
      continue;
    }
    if (CSS_GRID_DECL.test(name)) {
      let ok = cssBandGrid(value);
      if (!ok && /^var\(/i.test(value)) ok = cssResolveValue(value, defs).every((t) => cssBandGrid(t) && !/^var\(/i.test(t));
      if (!ok) push(ln, 'css-scale', `${name}:${value}`, '样式内 padding/margin/gap 声明脱 4px 栅格（与 ③⑤ 同带；函数形不可自证=拒）');
      continue;
    }
  }
  // @apply 臂：令牌复用 ①—⑧ 同一批判定（@apply 把违例形态写进选择器=等价于挂给 JSX）
  for (const m of text.matchAll(CSS_APPLY)) {
    const ln = lineAt(m.index);
    for (const tok0 of m[1].trim().split(/\s+/)) {
      const tok = tok0.replace(/^!/, '');
      if (!tok) continue;
      let why = null;
      for (const [rname, re] of CSS_LEGACY_ARMS) { if (tok.match(re)) { why = `旧族 ${rname}`; break; } }
      if (!why) {
        const mv = marginViolation(tok);
        if (mv) why = mv;
        else if (/^(-)?rounded/.test(tok)) { const rv = radiusViolation(tok.replace(/^-/, '')); if (rv) why = rv; }
      }
      if (!why) { const av = arbPieceViolation(tok); if (av) why = av.msg; }
      if (why) push(ln, 'css-apply', tok, `@apply 内含违例类（${why}）`);
    }
  }
  const imports = [];
  for (const m of text.matchAll(CSS_IMPORT)) imports.push({ spec: m[1], line: lineAt(m.index) });
  hits.sort((a, b) => a.line - b.line);
  return { hits, imports };
}

const CSS_VISITED = new Set();
function checkCss(entryPath) {
  const queue = [entryPath];
  while (queue.length) {
    const abs = resolve(queue.shift());
    if (CSS_VISITED.has(abs)) continue;
    CSS_VISITED.add(abs);
    if (!existsSync(abs)) continue;
    const raw = readFileSync(abs, 'utf8');
    const rel = relative(SRC, abs).split(sep).join('/');
    const { hits, imports } = cssFileHits(raw);
    const lines = raw.split('\n');
    for (const h of hits) report(rel, h.line, lines[h.line - 1] || '', h.family, h.token, h.msg);
    for (const imp of imports) {
      const spec = imp.spec;
      const target = resolve(join(abs, '..', spec));
      if (!/^[a-z-]+:|^\/\//i.test(spec) && /\.css$/i.test(target) && existsSync(target)) {
        queue.push(target); // 本地相对导入：定义侧随链进面（P7 编译实证——导入链把毒定义送进产物）
      } else {
        NOTICES.push(`@import 跳过：${rel}:${imp.line} '${spec}' 非本地树 .css——上游包样式由 package.json/lockfile 评审面管，扫描面外；登记 R5-fix3.md §7`);
      }
    }
  }
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
  // 【R5-fix3 改判】旧「var 通道放行」样本转红：m-[…var…] 经 ⑤ 的 var 例外臂编译出
  // margin: var(--x)（评审 C-3 同洞家族，编译实证 R5-fix3.md §1 m-[length:var(--radius-sm)]）。
  ['<div className=\'m-[length:var(--toolong)]\' />', 'margin'],
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
  // 【R5-fix3 改判】旧「rounded-[var(…) 放行」样本转红：编译实证 `rounded-[var(--radius-sm)]`
  // → border-radius: var(--radius-sm)=8px 脱三档（R5-fix3.md §1，A1 取消的 ⑥ 同臂洞）。
  ['<div className=\'rounded-[var(--r-tile)]\' />', 'radius'],
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
  // 【R5-fix3 改判】旧「var 读正样本」转红：w-[var(--x)]→width、ring-[color:var(--x)]→环色
  // 皆 A1 通道（token 值不受管时=脱栅几何/非 token 色，评审 C-3；定义侧洞另由 ⑩ 兜）。
  ['<div className=\'w-[var(--content-max)] ring-[color:var(--ring)]\' />', 'arb-box'],
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
  // —— R5-fix3 放行清单正样本 A2—A8（清单合法成员必须仍绿）——
  // 【R5-fix3 改判九行 green→red：原 A1「token 读」整类取消（评审 C-3）。原断言「token 读恒绿、
  //  产出恒等于 token 本值所以安全」是错的——其安全外包给一条从未机器兑现的「定义侧受管辖」，
  //  而 text-[length:var(--radius-sm)] 用仓库里已存在的 --radius-sm:8px 编译出 font-size:8px
  //  （脱五档+破 12px 下限，tailwindcss 4.3.3 实证 R5-fix3.md §1）。收紧方向，非放宽。】
  ['<div className=\'text-(--brand)\' />', 'arb-ns'],
  ['<div className=\'size-(--x)\' />', 'arb-box'],
  ['<div className=\'h-(--x)\' />', 'arb-box'],
  ['<div className=\'p-(--x)\' />', 'arb-ns'],
  ['<div className=\'w-[var(--x)]\' />', 'arb-box'],
  ['<div className=\'bg-[var(--x)]/[0.55]\' />', 'arb-color'],
  ['<div className=\'text-[color:var(--brand)]\' />', 'arb-color'],
  ['<div className=\'dark:text-[color:var(--brand)]\' />', 'arb-color'],
  ['<div className=\'text-[length:var(--fs-brand)]\' />', 'arb-ns'],
  // R5-fix3 新增读通道反例（评审未见过的形态，各自先有编译实证再入门锁，R5-fix3.md §4）：
  ['<div className=\'gap-(--radius-sm)\' />', 'arb-ns'], // gap: var(--radius-sm) 编译实证
  ['<div className=\'border-[var(--radius-sm)]\' />', 'arb-color'], // border-color: var(--radius-sm) 编译实证
  ['<div className=\'leading-[var(--radius-sm)]\' />', 'arb-ns'], // line-height: var(--radius-sm) 编译实证
  ['<div className=\'m-(--radius-md)\' />', 'arb-ns'], // margin: var(--radius-md) 编译实证（括号形⑤盲区）
  // 放行清单在册成员（A2—A8）必须照旧绿：
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
  // R5-fix3：⑩ 定义侧族一律硬红不入棘轮（与 arb-*/vardef 同纪律——「登记即绿」不适用新面）。
  ['css-tier', '@theme { --radius-md: 37px; }', false],
  ['css-ladder', '@layer components { .c { font-size: 9px; } }', false],
  ['css-url', ':root { --evil: url(\"https://x/y.woff2\"); }', false],
];

// —— ⑩ 定义侧自测锁（R5-fix3，评审 C-3）：与 checkCss 真扫共用 cssFileHits 纯函数（同一
//    实现、双向锁定）。每条负样本都先有 tailwindcss 4.3.3 编译实证（P1—P7 + §1 各表，
//    台账 R5-fix3.md §1/§4——「@theme 命名空间写入 / --*:url(...) / layer() 包裹 /
//    @utility 定义体内部 / @import 链 / var 链归一毒化」逐条），再证旧门不可见或新门判红。
//    正样本=值册现行全形态复刻（真 index.css 零误伤的机判面镜像）+ 在带定义变体。——
const CSS_LEDGER_POS = [
  "@import 'tailwindcss';",
  '@custom-variant dark (&:is(.dark *));',
  ':root { --radius: 14px; --r-shell: 30px; --r-panel: 18px; --r-tile: 14px;',
  '  --wash-1: oklch(0.903 0.0122 248); /* 注释里的 #d9e0e7 剥注释后不得造命中 */',
  '  --background: var(--wash-mist); --shadow: 0 12px 32px color-mix(in srgb, var(--wash-2) 26%, transparent), 0 3px 10px rgba(31, 35, 41, 0.05); }',
  '.dark { --tone-warn: oklch(0.828 0.113 84.5); }',
  "@theme inline { --color-card: var(--card); --radius-md: var(--r-tile); --radius-lg: var(--r-panel); --radius-xl: var(--r-shell); --font-sans: 'Segoe UI', 'Microsoft YaHei', sans-serif; --radius-sm: 8px; --spacing: 0.25rem; }",
  '@layer base { * { @apply border-border outline-ring/50; scrollbar-width: thin; scrollbar-color: var(--border) transparent; } html { @apply overflow-x-hidden; } body { @apply bg-background text-foreground min-h-svh w-full font-sans antialiased; } button:not(:disabled), [role=\"button\"] { cursor: pointer; } }',
  '@utility fs-caption { font-size: 0.75rem; line-height: 1.125rem; font-weight: 400; }',
  '@utility tone-face-warn { background: color-mix(in srgb, var(--tone-warn) 14%, transparent); }',
  '@utility no-scrollbar { &::-webkit-scrollbar { display: none; } -ms-overflow-style: none; scrollbar-width: none; }',
  '.recharts-cartesian-axis-tick text { font-size: 12px; }',
].join('\n');
const CSS_SELFTEST = [
  // 正样本：真值册复刻必须整面零命中（防过拦把 index.css 判红=误伤）
  [CSS_LEDGER_POS, null],
  ['@theme { --text-fs-caption: 12px; }', null], // 在带定义放行——证判据=值带而非名字黑名单
  ['@import "tailwindcss";', null], // 包导入=扫描面外（跳过提示另有实跑锁），本身非违例
  // 负样本（P# = R5-fix3.md §1 编译证据编号）
  ['@theme { --radius-md: 37px; }', 'css-tier'], // P1：rounded-md 具名类编出 37px 脱三档
  ['@theme { --radius-lg: var(--evil); } :root { --evil: 21px; }', 'css-tier'], // var 链归一后仍判（洗白通道）
  ['@theme { --text-rogue: 8px; }', 'css-ladder'], // P2：新字号具名类 text-rogue=8px
  ['@layer base { :root { --font-weight-heavy: 900; } }', 'css-weight'], // P3：layer 包裹内的命名空间写入
  ['@theme { --spacing: 7px; }', 'css-spacing'], // P5：一枚定义毒化全树数字刻度
  [":root { --evil: url('https://x/y.woff2'); }", 'css-url'], // P4：--*:url(...) 写入
  ['@utility rogue-pad { padding: 7px; }', 'css-scale'], // P6：@utility 定义体内部声明
  ['@layer components { .card { font-size: 9px; } }', 'css-ladder'], // P6：layer 包裹内脱档字号
  ['@utility x { --radius-xl: 13px; }', 'css-tier'], // @utility 体内档位 token 投毒（13px=梯值亦不赦——轴不对）
  ['@theme inline { --radius-lg: calc(18px + 4px); }', 'css-tier'], // 函数形定义不可自证=拒
  ['@utility a { border-radius: 9px; }', 'css-tier'], // 声明面圆角脱档
  [':root { color: #ff0000; }', 'css-hex'], // 样式内裸 hex（① 同门扩到定义侧）
  ['@layer base { .b { @apply text-xs; } }', 'css-apply'], // @apply 把 ② 违例写进选择器
  ['@layer base { .b { @apply rounded-sm; @apply -mt-2; } }', 'css-apply'], // @apply 六/五族违例
  ['@utility y { font: 600 13px sans-serif; }', 'css-ladder'], // font 简写声明零放行（同 arb-prop 判据）
];

const SELFTEST_TOTAL = SELFTEST.length + LEGACY_SELFTEST.length + CLAIM_SELFTEST.length + CSS_SELFTEST.length + 3; // +3 = 标记解析两断言 + import 提取一断言

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
  // ⑩ 定义侧双向锁（R5-fix3）：与 checkCss 真扫共用 cssFileHits——「自测过、真扫空转」两张皮
  // 在新面上不得重生（F1 教训的 ⑩ 版）。
  for (const [cssText, expect] of CSS_SELFTEST) {
    const fams = new Set(cssFileHits(cssText).hits.map((h) => h.family));
    if (expect === null) {
      if (fams.size > 0) fails.push(`误伤（定义侧）：${cssText.slice(0, 72)}… → 命中 [${[...fams].join(',')}]（应放行）`);
    } else if (!fams.has(expect)) {
      fails.push(`漏判（定义侧）：${cssText.slice(0, 72)}… → 命中 [${[...fams].join(',') || '(空)'}]（应含 ${expect}）`);
    }
  }
  // import 提取锁：@import  specifier 三种写法必须全数列出（跟随逻辑失效=定义侧导入链失明）
  {
    const imps = cssFileHits('@import "./b.css";\n@import url(\'../pkg/x.css\');\n@import "tailwindcss";').imports.map((i) => i.spec);
    if (imps.length !== 3 || imps[0] !== './b.css' || imps[1] !== '../pkg/x.css' || imps[2] !== 'tailwindcss') {
      fails.push(`import 提取失效：应列 3 条 specifier，实得 [${imps.join('|')}]（跟随逻辑在 checkCss，--src 探针目录实跑锁见 R5-fix3.md §4）`);
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
const offgridN = [...OFFGRID_RATCHET.values()].reduce((a, b) => a + b, 0);
console.log(`版式宪法机器门：全部通过（自测 ${SELFTEST_TOTAL}/${SELFTEST_TOTAL}；hex=0 / 字号五档（含任意值长度形态）/ 间距 4px 栅格（p·m·gap·space 全族）/ 调色板类=0 / margin 同栅格 / 圆角三档+full 白名单 / 同元素双写=0 / 任意值命名空间默认拒绝（utility 方括号+圆括号、任意属性形零放行、[--名:值] 与 inline V2—V4 自定义属性写入成族封死、截断形判红；放行清单 A2—A8=老式色包装·纯视口·规范环 3px·网格轨道·transition 清单·纯角度·无单位行高——var token 读整类已取消 R5-fix3/C-3，calc/min/max/clamp/env 函数形一律拒）/ 定义侧 .css 扫描（值册命名空间带=圆角三档·字号五档·字重≤700·--spacing 唯一值，受管声明带=font-size/weight/border-radius/间距栅格，hex/url 写入拒，@apply 复用同判，相对 import 链随进——@theme/:root/@layer/@utility 位置无关全覆盖）/ canvas 字体字面量；行级豁免 ${exemptN}/${EXEMPTION_BASELINE.size} 基线，棘轮只减不增；权重双写白名单 ${weightN} 处存量在册；脱栅棘轮 ${offgridN} 处存量在册（canvas 专属，只减不增））`);
