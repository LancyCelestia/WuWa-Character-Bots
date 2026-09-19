# S8 敌对审计：统一渲染 + 统一前端（渲染 token 单一来源 / 机器门牙口 / WebUI 一致性与验收判据）

> **快照声明**：`date` 实取 = **Sat Sep 19 15:59:40 2026**（复核延续至 16:1x）。本席只读取证 + 定向测试实跑，零写盘（除本文件）。
> **在飞口径**：①`domains/render/templates.py` mtime **2026-09-19 15:59（本席开审同分钟，确认在飞）**——涉及它的结论一律标注「按 16:0x 快照字节」；`docs/design/COMPACT-CHECKPOINT.md` 顶部明示 INTG 收尾席在飞（哈希/doc_sync 三 --write 重录待跑）。②`tests/verify_hashes.py --check` 于 16:01 实跑 **exit 0**——在飞文件当前字节恰与清单一致，不代表不会瞬断。③`webui/**` 全部文件 mtime ≤ 03:54、`webui/dist/index.html` = 03:55（src 无文件新于 dist），前端域本席视作静态；行号全部以**锚点字符串**重定位后复核。
> **禁触纪律自证**：未改任何独占文件；`verify_hashes` 仅 `--check`；未跑 `npm run build`；`node scripts/layout-constitution.mjs` 先通读源码确认**纯只读**（仅 readdirSync/readFileSync，零写盘）后实跑。

---

## 第一部分：2026-09-19 审计（`docs/design/audit-20260919-unify-wave.md`）前端/渲染条目核销表

**总裁决：14 条被审条目中 0 条已被改掉、13 条仍在、1 条（P2-10）六处坐标中 4 处仍在 + 2 处报告本身写错（有反证）。P1-3 实质成立但含一处引用坐标错误。**

| # | 条目 | 判定 | 实读证据（锚点 + 当时行号 + 复跑命令） |
|---|------|------|------|
| P1-1 | `card.tsx:31` `leading-none` 层叠塌陷 | **仍在** | `webui/src/components/ui/card.tsx:31` 现读 `cn('leading-none font-semibold', className)` 逐字在位（mtime 02:00<审计）。dist 层叠**本席重跑取证**（只读 node）：`.fs-card{…line-height:1.375rem}` @字节 949677、`.leading-none{--tw-leading:1;line-height:1}` @949805 → leading-none 后生成恒赢，与审计 §6.4 数值逐字节一致。**注**：修复验证命令 `npm run build` 属本席禁区，只报不修。 |
| P1-2 | 三道前端门游离于 pytest 之外 | **仍在** | `tests/test_webui_constitution.py` 不存在（ls 实证）；`grep -rn "layout-constitution\|tsc -b\|node --test" tests/ scripts/dev.ps1` **0 命中**。缓解面（如实记录）：`package.json` build=`node scripts/layout-constitution.mjs && vite build`（宪法门已挂 build 前置），`tests/test_pre_restart_check.py:313-325` 断言 dist 形态——但 `tsc -b` 与 `node --test graph-layout.test.ts` 仍无任何自动化入口。 |
| P1-3 | 宪法门执法面四缺 | **仍在（四点全实锤）+ 一处引用坐标错** | 门全文读毕（66 行）。①margin 族不扫：`OFF_SCALE_SPACING` 前缀族 `(?:p\|px\|py\|pt\|pb\|pl\|ps\|pe\|gap\|gap-x\|gap-y)` 无 m 族，`mt-7`（Tailwind v4 动态刻度=28px 真渲染）畅通——现存活例 `settings-dialog.tsx:86 mb-4`（在刻度内所以无害）；②圆角无门：全脚本 `grep rounded` = **0 命中**，「三档锁死」只活在 `index.css:184-186` 注释+钉值；③`rgba(/hsl(` 不扫：0 命中，内联任意值（如 `border: 1px solid rgba(255,255,255,.98)`，universal_card 同款写法在 WebUI 侧同类）可绕；④`memory-canvas.tsx:179` `context.font = '12px "Segoe UI"…'` 逐字在位、零登记——**引用纠错**：审计写「同文件 height:480 标了内联白名单 #1，双标」，实测 `内联白名单` 全 webui 仅 1 命中=`memory-graph.tsx:182`（页面层），canvas 字体在组件层 `memory-canvas.tsx`，「同文件」不成立（双标结论本身仍成立，坐标须改）。门实跑（只读）：`GATE_EXIT=0`。 |
| P1-4 | 日志页重放重复行 | **仍在** | `logs.tsx:77-88` `appendRows` 现读无去重逻辑；`:165-168` `resubscribe` 与 `:170-173` `applyFilters` 均 `sessionStorage.removeItem(CURSOR_KEY); startStream(null)` 而 **rows 不清空**。React `key={row.cursor}`（:289）重放必双写同键。补充观察：`webui_acceptance.py` 的 logs 页控制台断言其实能抓到「duplicate key」类 console.error（不在噪声白名单），但验收流不点「重新订阅」→结构性不触发。 |
| P1-5' | 零 ErrorBoundary | **仍在** | `grep -rn "ErrorBoundary\|componentDidCatch\|getDerivedStateFromError" webui/src/` = **0 命中**；`main.tsx:32-40` `root.render(<StrictMode>…<RouterProvider/>)` 裸奔在位（文件 mtime 早于审计，未变）。 |
| P2-9 | dev 代理漏 `/admin/api/v1` | **仍在** | `vite.config.ts:18-23` proxy 仅 `'/api/v1'` 一条（mtime 00:42 未变）；消费面在位：`api-client.ts:450-452` `health: () => apiRequest('/admin/api/v1/health')` + `statusBot: '/admin/api/v1/status/bot'`，dashboard 两卡恒依赖。后端真端点在位（`api/health.py:50` `APIRouter(prefix="/admin/api/v1")`）→ 仅 dev 模式断链，生产 /ui 同源不受影响（与审计口径一致）。 |
| P2-10 | 五处表单控件漏 fs-* | **拆分判定：4 处仍在，2 处报告写错（反证）** | **仍在**：`settings-dialog.tsx:106` `:127`、`knowledge.tsx:205`、`memory-graph.tsx:144`——四行现读 `h-9 …` 无 `fs-`，锚点逐字命中。**报告写错**：审计称 `logs.tsx:249`/`:261` 两 select「h-9 无 fs-」——实读两行现为 `className='h-8 rounded-md border bg-background px-2 fs-caption'`，且 logs.tsx **mtime 02:06:24 早于审计自身复核时刻 14:22**（审计原文也写「前端文件 mtime 全部 ≤02:06」）→ 文件自 02:06 未变过，报告所述形态在该文件从未存在，属误读。附带：全文只有这两个 select、无其它 input，无可辩解的坐标漂移空间。**后果口径也存疑**：Tailwind v4 preflight 对表单元素 `font: inherit`，settings-dialog 两 input 父容器 `:96` 有 `fs-body` → 「渲染浏览器默认 16px」的断言对这两处不成立（缺类是事实，16px 后果是夸大）；knowledge:205/memory-graph:144 父面无 fs-* 则继承 body 基础字号，需目验定夺。 |
| P2-11 | dashboard `?? 0` 造数 | **仍在** | `dashboard.tsx:184` `formatInt(tokensData.totals?.calls ?? 0)`、`:187` `tokens.input.value ?? 0` + `output.value ?? 0` 三处逐字在位。**同页自证矛盾**：`CallsDetailGroup :70` 对 `active_users` 用 `!= null ? formatInt : '—'`（正确语义），同文件 :184/:187 却兜 0。 |
| P2-12 | 移动端无导航 | **仍在** | `app-shell.tsx:71-75` `aside … hidden h-svh w-60 … md:flex` 在位；header `:106-120` 仅 ThemeSwitch+Settings 钮；nav 数组（:46-56）只渲染进 aside。九页在 <md 视口无触控入口。 |
| P2-13 | a11y 三件 | **全部仍在** | ①`settings-dialog.tsx:77-93`：弹窗容器为裸 `div`（无 `role='dialog'`/`aria-modal`/`aria-labelledby`），全文件零 keydown/Esc 处理、零焦点管理；②`logs.tsx:287` `aria-live='polite'` 逐字在位（行号都没漂）；③`plugins.tsx:128` `<h2 className='fs-page'>` 在位（grep 唯一命中）。 |
| P2-14 | theme-switch absolute 脆弱 | **仍在** | `theme-switch.tsx:20` `<Moon className='absolute size-[1.2rem]…'` 在位（Sun 在 :19，审计「19-20」=两图标行，成立）；`button.tsx` `grep relative` = **0 命中**（cva 基类确无定位上下文），当前不飞纯靠「absolute 无 inset 保持静态位置」规范特性。 |
| P2-17 | 渲染豁免散点无总册 | **仍在** | `docs/rendering-contract.md` 全文 101 行读毕：**无「豁免登记表」章节**（铁律 8 行内嵌 error=24、§4 行内嵌 amber 豁免、C3 行内嵌玻璃档，均为散点行内表述）；song `.ttl`/affinity `.pill` 描边两档（实读：`border-box linear-gradient(150deg,.95,.35)` 两档 vs canonical 三档 .95/.35/.72）**任何文档零记载**，纯靠门 9 的「alpha ⊆ 集合」成员判定碰巧放行；mermaid 伪元素特例仅模板内注释（`mermaid_card.html:124-126`）；universal `--blue:#23ade5`/`#1d9bf0` 认证徽章蓝 = 模板内「语义色豁免」注释级，未入 theme_tokens 任何登记。落地草案见本文件 §四。 |
| P3-20 | 死 eslint-disable + 无 lint 基建 | **仍在** | `logs.tsx:121` `:144` `// eslint-disable-next-line react-hooks/exhaustive-deps` 两行逐字在位；`package.json` devDependencies 无 eslint/prettier——注释指向不存在的 linter。 |
| P3-21 | 统一 `npm run check/test` 入口 | **仍在** | scripts 实读：`dev/build/typecheck/lint:layout/preview` 五键，**无 `test`、无 `check`**；`node --test src/lib/graph-layout.test.ts` 仍无 npm 入口（宪法门已进 build 前置=部分缓解，三门合跑入口仍缺）。 |
| （附带）P2-15 | X-Frame-Options + IPv6 白名单 | **仍在（越界快检，非本席独占面）** | `api-client.ts:42` `LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost'])` 无 `::1`；`grep X-Frame-Options control_plane/_app.py api/webui.py` = 0 命中。 |

**核销统计：仍在=13 ｜ 已被改掉=0 ｜ 报告本身写错=P2-10 之 logs.tsx 两坐标（另 P1-3 含一处「同文件」引用错，实质不改判）。**

---

## 第二部分：新发现台账（S8 席，七要素齐；全部只报不改）

> 严重度定标：P0=生产即炸 ｜ P1=门禁实质无牙/契约-实现背离可致错绿 ｜ P2=单一来源失守点（现值一致、漂移无防）｜ P3=文档/卫生债。

### S8-01【P1】九门「禁表外 hex」实为黑名单门——门 9 对新散值永久放行，且黑名单三员为死字面

- **坐标**：`tests/test_v21r3_visual_gates.py:363-372`（`_FORBIDDEN_HEX`）、`:559-572`（`test_gate08_forbidden_hex`）。
- **锚点**：`if reason and normalized not in _REGISTRY_HEXES:`。
- **根因**：断言逻辑=「仅当命中黑名单 8 员且不在登记表白名单才记红」。①任意新表外 hex（如 `#1d9bf0` 类平台色复写、error 卡 `#e6e8ee`/`#f2b8b5`）`reason=None` → 恒绿；②黑名单中 `#b07d1a`/`#157347`/`#b42334` 三员**本身即 SEMANTIC_WARNING/SCORE_HOT/SCORE_COLD 的登记值**，被 `_REGISTRY_HEXES` 动态豁免 → 三条永不触发（死字面）；③文件头宣称「禁表外 hex（…未登记值在面文本内一律记红）」与实现不符。连带：`docs/rendering-contract.md` §4 语义色「一律 var() 消费、卡私红绿黄字面量禁止」条款**无对应断言**——活反例=`usage_cards.py:255-257` 直写 `#2e9e6b/#b07d1a/#d54941` 三枚登记值字面量（同文件 :290 `#fff`），三门合跑 289 passed 照样绿。
- **建议改法**：before `if reason and normalized not in _REGISTRY_HEXES` → after 白名单制：`if normalized not in _REGISTRY_HEXES | _FUNCTIONAL_HEX`（`_FUNCTIONAL_HEX`={#fff,#ffffff,#000} 等功能常量，需裁决入册），并把 usage_cards 三处改 `var(--semantic-*)`（token 已由 `render_root_tokens` 注入，消费面现成）。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21r3_visual_gates.py -q -p no:cacheprovider --basetemp="$TEMP/s8-01"` 改前绿（现状）、植入 `#123456` 样本后必红。
- **回归锁**：无（本条即补课对象）。

### S8-02【P1】`webui_acceptance.py` 判据「或」语义：后端全灭也能 9 页 9 PASS

- **坐标**：`scripts/webui_acceptance.py:268-304`（模式判定）。锚点：`result["mode"] = "data" if ok_marker else ("graceful" if graceful_marker else None)`。
- **根因**：每页 PASS 条件=数据标志**或**通用降级文案（`COMMON_GRACEFUL` 含「加载失败/暂无数据」）任一出现 + body ≥30 字 + 无非白名单控制台错。**退出码只数 FAIL，不要求 data 模式**→对着零后端跑，九页全部 graceful 全绿；「9 页 9 PASS」字样本身不携带数据强度信息，只有逐页 mode 列可辨。正面确认（如实记录）：判据并非「HTTP 200」级——它真驱动 DOM 文案/DOM 选择器断言且 pageerror 永不豁免，比状态码强一档；但**无字段级断言**（DOM 数值 vs API JSON 零对照），且 dashboard ok 标记「在线/降级」中「降级」二字亦可能出现在降级语境文案里（误判 data 的正则性风险，未实锤触发路径）。
- **建议改法**：before `return 1 if fails else 0` → after 增 `--require-data` 旗标（任一页 mode≠data 即非零退出），mock/真机双跑各断一次；mock 模式下可选抽一字段对照（如 calls 页 `total_calls` DOM 数值 == mock 固定夹具值）。
- **验证**：不起任何后端 `python scripts/webui_acceptance.py --pages all` → 现状退出码 0（全 graceful）；加旗标后应红。
- **回归锁**：无。

### S8-03【P2】`mica_shell.py` 内 `shell_base_css` 手抄 GLASS_EDGE 字面量 = 值册之后的第二来源（同文件！）

- **坐标**：`plugins/bot_unified_runtime/domains/render/card_render/mica_shell.py:393`。锚点：`linear-gradient(150deg, rgba(255,255,255,.95) 0%, rgba(255,255,255,.35) 55%, rgba(255,255,255,.72) 100%) border-box`。
- **根因**：同文件 `glass_rules_css()`（:238-243）经 `{GLASS_EDGE}` 常量插值消费，而 `shell_base_css()` 把**同值**以 `.95/.35/.72` 缩写形态硬写第二份。theme_tokens 若改 GLASS_EDGE：`glass_rules_css` 自动跟、`shell_base_css` 恒旧——单源承诺在生成器内部破口。门 9 只按「border-box 白 alpha ⊆ {0.95,0.35,0.72}」**成员判定**，两档/乱序/缺 stop 一律放行（song `.ttl`、affinity `.pill` 两档描边即活例，见 §四豁免表 E-5），抓不到该漂移；且该测试端 alpha 集合本身是**第三份硬编码**（不派生自 GLASS_EDGE 字符串）。
- **建议改法**：before 硬写渐变 → after `shell_base_css` 内以 `GLASS_EDGE`（剥 attach 后缀或新增 `glass_edge_css()` 助手）插值；门 9 增一条「canonical EDGE 三 stop 逐子串匹配 --mica-glass-edge 登记值」的派生断言（替掉字面集合或与之并存）。
- **验证**：改后跑 `tests/test_v21r3_visual_gates.py tests/test_mica_builders_contract.py tests/test_mica_shell.py`（同 S8-01 三件套命令）+ `verify_hashes.py --check`（mica_shell 入册后，见 S8-04）。
- **回归锁**：现状**无**；落地后由门 9 派生断言承担。

### S8-04【P2】哈希清单盲区：`mica_shell.py`（壳层唯一生成器）与 `render_backends.py`（WAAPI 钉帧）不在 `render_hashes.json` 19 项内

- **坐标**：`tests/render_hashes.json`（19 键全集实读）；登记定义 `tests/verify_hashes.py:32`（`MANIFEST`）+ `TRACKED_FILES`。锚点：`"plugins/bot_unified_runtime/domains/render/card_render/bridge.py"`（在列邻居）。
- **根因**：v21r3 把公共段全部收编进 mica_shell、把字节确定性收编进 render_backends 之后，这两文件成为渲染域**行为牵动面最大**的实现，但哈希门覆盖的是模板 HTML + theme_tokens/bridge/usage_cards/templates.py/renderer.py + 5 份文档——恰缺新枢轴。改动 mica_shell 的色斑几何/降级媒体查询/钉帧注释外逻辑，`--check` 恒静默。样张基线（`baseline-20260919-paused`）可兜一部分（见 S8-05），但基线本体在 %TEMP%（下一条）。
- **建议改法**：before 19 项 → after `TRACKED_FILES` 增补 `domains/render/card_render/mica_shell.py`、`domains/render/render_backends.py` 两行，由收尾席 `--write` 重录（本席禁写）。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check` exit 0。
- **回归锁**：哈希门自身。

### S8-05【P2】PNG 字节等值验收基线只活在 `%TEMP%/shorekeeper-samples/`——易失目录、不入库、无哈希

- **坐标**：`scripts/render_card_samples.py:1056-1057`。锚点：`Path(tempfile.gettempdir()) / "shorekeeper-samples" / "baseline-20260918"`。
- **根因**：AGENTS #41/COMPACT-CHECKPOINT 宣称「19/19 STABLE、PNG 字节等值升全面验收判据」，基线目录实存（本席只读 `ls $TEMP/shorekeeper-samples/` 见 baseline-20260918 + after-* 诸目录 + `01_universal_bilibili_video.png/.sha256` 三件套）——但全在临时盘：清磁盘/重启策略变更即灭，无源码树/哈希清单/Runtime 归档面。钉帧机制自身复核：`render_backends.py:251-278` fail-open 属实（无 evaluate→return、异常静默）；`animations="disabled"` 排除论证以注释+探针记录在位（:237-246），且**两条截图路径（元素/full_page）均先 `_pin_card_animations(page)` 后分叉**（:692-705 实读）→「取舍与截图路径不一致」之虞排除；两截图调用均未传 animations 参数（grep 实锤=注释外零使用），与「不采纳 disabled」口径自洽。本席**未实跑**样张（会写 temp 产物、非独占面必需），字节等值以既有报告转述记账、不背书。
- **建议改法**：基线 sha256 旁车清单（脚本本就产 `.sha256`）另落一份进 `tests/`（如 `tests/card_samples_hashes.json`）入哈希门，PNG 本体留 temp 可再生。
- **验证**：`verify_hashes.py --check`；`python scripts/render_card_samples.py`（有 playwright 环境处）重跑对照。
- **回归锁**：现状无（基线灭=判据灭而无人知）。

### S8-06【P2】版式宪法门可稳定骗过的写法清单（攻击取证，非穷举）——「六断言类别」中五类的实锤绕过

- **坐标**：`webui/scripts/layout-constitution.mjs:28-39`（六正则全集）。锚点：`const OFF_SCALE_SPACING = /\b(?:p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y)-(?!…)/`。
- **根因/攻击样本**（三类最稳，全部基于正则实读，非推测）：
  1. **margin 族 + `pr-*` 脱刻度**：`mt-7`（28px）、`pr-5`（20px）——p 族前缀表**漏了 `pr`**（有 ps/pe 无 pr，审计未发现的增量），m 族整族不扫（审计已发）；`m-[13px]` 连任意值形态也不在 `OFF_SCALE_ARBITRARY` 前缀表。
  2. **染色/遮罩内联色**：`bg-[rgba(15,18,24,.4)]`、canvas `ctx.fillStyle='rgba(255,255,255,.5)'`、SVG `fill="orange"`——HEX 只咬 `#` 字面、PALETTE 只咬 Tailwind 类名形态，函数式色与 CSS 命名色零防线；活体白样本=`memory-canvas.tsx:179` 字体（门跑绿）。
  3. **扫描面外定义层**：只 walk `src/**/*.{ts,tsx}`——`index.css` 本身（五档阶梯、rounded 三档、recharts 12px 的**定义处**）加一行 `.x{font-size:21px}` 门恒绿；圆角使用侧无门（P1-3②）+ 定义侧无门=rounded 全链裸奔。
- **建议改法**：①前缀表补 `pr|m|mx|my|mt|mb|ml|mr|ms|me|space-x|space-y`（负值放行与否=用户裁决，接审计 §5 决策点 4）；②增 `ROUNDED_ARBITRAL / COLOR_FN / NAMED_COLOR` 三门（canvas 语境可带显式豁免表，见 §四 W-2）；③扫描面扩 `*.css` 或单设「定义层自检」（index.css 的 @utility 块结构断言）。
- **验证**：临时 tsx 植入三样本 → `cd webui && node scripts/layout-constitution.mjs` 必红 → 删回绿（本席未植入=纪律）。
- **回归锁**：门自身 + 待建的 P1-2 常驻化。

### S8-07【P3】渲染契约 §2 wash 注入写法条款已空转（模板零 `default('#` 实例）

- **坐标**：`docs/rendering-contract.md:35-44`（「模板 --wash-* 注入点写法（兜底字面量必须与 DEFAULT_WASH_TOKENS 逐键一致）」+ CSS 样例块）；断言面 `tests/test_rendering_contract.py:330-345`。锚点：`declared = re.search(r"default\('([^']*)'\)", value)`。
- **根因**：七模板 `grep -c "default('#"` 全 0（实跑）——「步 5」后 bridge 直注派生值，兜底字面量形态整树退役；契约仍以规范口吻规定该形态，断言退化为「若声明则等值」的条件锁。条款与树脱节（文档债，非行为 bug）。
- **建议改法**：契约 §2 该段改注「历史形态（步 5 前），现行=bridge 注入单源，default() 出现即须等值」；或不改文档、在豁免/沿革表登记。
- **验证**：`pytest tests/test_rendering_contract.py -q`（不受影响，纯文档面）。
- **回归锁**：n/a。

### S8-08【P3】media 卡兜底色字面量三写 + `#4a5866` 与派生公式不等值

- **坐标**：`plugins/bot_unified_runtime/domains/render/templates.py:143-145`（**15:59 在飞文件，按 16:0x 快照**）。锚点：`pc_dark = _esc(payload.get("platform_color_dark")) or "#4a5866"`。
- **根因**：`#607080` 有常量 `UNKNOWN_PLATFORM_COLOR` 而直写字面；`#4a5866` 声称同语义「深一档」但 `_darken_hex("#607080")` 实算=`#4c5966`（本席按 theme_tokens:116-119 公式复算）——不等值；`96,112,128` 第三次写。当前 `--accent-dark` 在本卡 CSS 零消费（:150 注释自证），视觉零影响，属潜伏漂移（若未来卡身消费 accent-dark 即出现两套「灰卡深色」）。
- **建议改法**：`or UNKNOWN_PLATFORM_COLOR` / `or _darken_hex(UNKNOWN_PLATFORM_COLOR)` / rgb 由 hex 现算。
- **验证**：`pytest tests/test_v21r3_visual_gates.py -k media -q`。
- **回归锁**：门 8（字体）/门 7（宽度）管不到色；无——建议随 S8-01 白名单化后自动入网。

### S8-09【P3】三处「宣称口径 vs 机器现实」漂移（文档卫生打包）

1. `docs/design/fstring-card-dom-spec.md:3` 头部仍标「**本规格未实施**，实施前需用户裁决」——壳层/token/宽度登记/`--accent` 命名统一（D2/D3/D5 壳层部分/D6/D7、pc 家族退役）已随 v21r3 落地；**残余 DOM 差异**（本席实测）：壳类名四式 `help-shell/setup-shell/shell/panel` 未合并（spec §3.1 目标态）、media 卡根 = `div.card > div.panel`（div 非 section、**无 `<!doctype html>`**，templates.py:207-208 vs usage_cards.py:236 有）、「相位内联脚本」已改 `--phase` 注入+生成器路（spec §1.2-5 形态过时）、D4 状态色写法（=S8-01 活例）、D8 accent 解析仍多份。该文件被哈希清单锁着（`--check` 绿），锁的恰是含过时状态行的字节。
2. `AGENTS.md:91/108` 渲染管线仍写「`output/card_render/` …6 Jinja 模板」——真身=`domains/render/card_render/`、模板现数=**7**（universal/market/affinity/mermaid/song/finance/error 枚举实读）。
3. 双实例问题裁决（B5）：`output/**`=**纯垫片**（`output/card_render/theme_tokens.py` 头 1 行 = "Compat shim"，bridge/mica_shell/usage_cards/templates/renderer 等同形态；mica_shell 垫片注释自证 2026-09-18 星转发教训），全仓 `class PlaywrightRenderBackend` 唯一定义在 `domains/render/render_backends.py:407`——**无第二实现**；但旧路径消费面仍有 ~55 个文件（grep 计数），退役完成度按 `docs/design/v21r2-shim-retirement-inventory.md` 在途（波次台账 #42 RET2b/RET3）。
- **建议改法**：spec 头部状态行改「壳层已实施（v21r3），余项=D4/D8/类名合并/doctype，待裁决」；AGENTS 两处路径+模板数同步；随收尾波 `verify_hashes --write`。
- **验证**：doc_sync/哈希门；`pytest tests/test_rendering_contract.py -k doc_exists`。
- **回归锁**：`test_rendering_contract_doc_exists` 只锁关键词存在，不锁 freshness。

### S8-10【P3】契约条款 ↔ 机器断言差集穷举（B2-2 交付；有文档条款、无对应断言者）

| 契约条款（出处） | 现状断言 | 缺口 |
|---|---|---|
| §4 深色遮罩「表外禁止」 | 仅 `test_core_registry_overlay_scrims_exact` 锁登记值本身 | **无面扫**：任意 `rgba(28,30,38,0.5)` 类新遮罩在 11 面任意处放行（S8-01 同族） |
| §4 语义色「一律 var() 消费、卡私字面禁止」 | 门 8=legacy 黑名单 | usage_cards 直写实锤（S8-01） |
| 铁律 3 字重 ≤700 | `font-weight\s*:\s*(\d+)` 数字制 | `font-weight: bold`/命名值、`font:` 简写内 `700 ` 全漏 |
| 铁律 9 行高刻度 | 数字制 line-height 扫 | `font: 13px/1.55` 简写、`line-height:1.4rem` 数值语义误判（14 不在刻度会误红——方向保守，可接受但登记） |
| §4 字号下限 12px | `font-size: Npx` | `em/rem/pt/%` 单位与 `font:` 简写漏；mermaid SVG 属性 `font-size="10"` 不在 CSS 语法内（门 8 字体栈亦不咬该属性名） |
| 铁律 8 keyframes 单名 | `test_animation_selectors_are_card_scoped` **仅扫 7 模板源文件** | 直拼卡 `render_shell(css=卡身私有段)` 面**无 keyframes 名门**（v21r3 门 2 只认 `animation:mica-drift-*` 命中集，其它动画名不申报不违规）；现状 4 卡零自有 keyframes（渲染语料实扫），缺口为将来时 |
| §4 阴影「族外一票否决」 | box-shadow var()/none 白名单 + token 定义等值（真·正门制）| ✅ 无缺口（本域最硬一门，正面记录） |
| 铁律 8 恒 3 枚/时长集 | 门 2 全 11 面 + 注释剥离双语料 | ✅ 有效；mermaid 伪元素两枚 + 生成器一枚的组成方式仅注释级记载（§四 E-1） |
| §4 zebra ΔE ≥3.0/对比 ≥4.5 | `tests/test_template_visual_audit.py` 在位（实存核验） | ✅（未逐断言精读，登记存在性） |

**豁免率人均口径**：289 条参数化断言（132+58+99 实收）vs 成文豁免登记 10 项（§四表）≈ **3.5%**——数字健康，但**结构性空洞不在数量在形态**：门 9-hex 与版式宪法门属「加豁免后该门已无牙」（前者恒免一切新值；后者五类绕法），而阴影门/半径门/宽度门/玻璃门（成员判定部分）确有牙。裁决详见 §五。

---

## 第三部分：C7/C8/C9 结论（非缺陷面，证据登记）

- **C7 端点对表**：前端 12 端点（`api-client.ts:448-483` 全集）对 `control_plane` 真面 **12/12 存在、零 404 面**（health.py:50 / webui.py stats×3+affinity / events.py sources+stream / webui_ext knowledge×2+plugins+memory）；开发面 P2-9 除外。②后端有、WebUI 不消费的大群（features/config/actions/llm/metrics/workspaces/divination 等）属控制面其它客户端与 OpenAPI 面，**不判死端点**，仅登记「WebUI 未接线」（含 `/api/v1/logs/{event_id}` 单事件查询）。③一致性：window 枚举 24h/7d/30d 两端对齐（`webui_stats.py:46` 白名单校验）；`page_size≤100`/`max_nodes≤200` 服务端钳制在位（webui_knowledge.py:193 / webui_memory_graph.py:135），前端 `maxNodes ?? 200` 恰好顶格；时间戳 events `created_at` 带 tz-aware ISO（events.py:171-172），`last_message_at` 同源（webui_stats.py:208）——前端 `new Date()` 解析无歧义；可空性唯一口径裂口=dashboard `?? 0`（已列 P2-11），其余 null→'—' 语义一致（active_users/definition/chunk_count 等 optional 链实读）。
- **C8 mock 边界**：夹具在**独立进程**（`scripts/webui_mock_server.py`，stdlib http.server，FIXED_NOW=2026-09-18T12:00Z 确定性锚）+测试侧 fixture；生产 `control_plane/**` grep "mock" **零命中**（无任何配置开关串味路径）。残余风险面=用户在设置面板把 baseUrl 手填 8743 看到假数据——白名单限环回（api-client:42-70 含 userinfo 欺骗防线），且假数据全带固定 09-18 时间戳可辨。判据强度结论见 **S8-02**（本席最重要的 C8 发现）。
- **C9 dist 同步**：`find webui/src -type f -newer webui/dist/index.html` = **0**（dist 03:55 > 全部 src ≤03:54）→ mtime 序一致；**内容级同步不可证**（重建=npm run build 属禁区），按「序一致+无哈希锁」如实记录：dist **零哈希锁定**（render_hashes 19 键无 webui 项），`pre_restart_check` 只断形态（存在/尺寸/无外链 script|link——测试夹具=任意合法 HTML 亦 PASS，test_pre_restart_check.py:294-341 实读）。陈旧但形态合法的 dist 恒绿=已知取舍，登记为 S8-11 卫生债（并建议 dist 的 sha256 进 pre_restart 报告字段，改法归下一位）。

---

## 第四部分：豁免登记表草案（P2-17 落地内容；本席不动 rendering-contract.md）

> 每条=豁免物｜所在面｜依据出处｜牙口判定。归册建议：新增「§七 豁免登记表」章节由下一席执行（该文件在哈希清单内，需 `--write` 重录联动）。

| # | 豁免物 | 面 | 现出处 | 牙口判定 |
|---|---|---|---|---|
| E-1 | error 卡 `wash_blob_mix=24`（vs 默认 35） | 模板×1 | 契约铁律 8 + `bridge.py:1807` 参数实值 | 有牙（参数化生成器显式传参，非注释） |
| E-2 | mermaid 伪元素 `.card::before/::after` 色斑（时长 58s/46s）+ 生成器整层供给的惰性面 | 模板×1 | 仅 `mermaid_card.html:124-126` 注释 | 半牙（门 2 咬时长/名称集合，组成方式无锁） |
| E-3 | universal amber 装饰族 6 枚（#ff9800/#e65100/#f5b83b/#f0b429/#b77900/#fff7d6）+ `--blue:#23ade5` + `#1d9bf0` 认证徽章蓝 + `#f1f2f3/#ffffff` bg 对 | 模板×1 | 契约 §4「amber 装饰族豁免」一句 + 模板内注释；**未入 theme_tokens 登记** | 无牙（黑名单外散值恒绿；「豁免唯一途径=登记进 theme_tokens」的门面话与实现互洽但表未含这些值，逻辑=本来就不拦） |
| E-4 | `.footer-colored` border-box 白 alpha 0.98/0.88 | 模板×1 | `test_v21r3_visual_gates.py:585-588` 裁定登记（GLASS3 席，2026-09-19） | 有牙有据（染色层按设计放行；同族 `border:1px solid rgba(255,255,255,.98)` 直写面**不在**该登记文字覆盖内——归册时请写清「仅限染色渐变层」边界） |
| E-5 | song `.ttl` / affinity `.pill` 描边两档（.95,.35 无 .72 stop） | 模板×2 | **零记载**（纯靠门 9 alpha 成员判定放行） | 无牙（登记后也应保持「成员判定」语义则永远抓不到，需「EDGE 全模式匹配」才谈得上有牙——建议登记为「两档变体=合法档位」了事） |
| E-6 | recharts 图元 12px CSS 钉死 | webui/index.css:316-321 | CSS 注释 + 宪法门「tsx 禁 fontSize」互补 | 有牙（定义处集中） |
| E-7 | memory-graph.tsx:182 `style={{height:480}}`「内联白名单 #1」 | webui×1 | JSX 注释（编号制！） | 半牙（gate 实际只拦 `fontSize:`，height 内联本不在扫描面——「白名单」注释是道德约束非机器约束） |
| E-8 | memory-canvas.tsx:179 canvas `12px "Segoe UI"…` 字体 | webui×1 | **零登记** | 无牙（=P1-3④，归册必办） |
| E-9 | 门 7 宽度：@media 块整体剥离 + <500px 地板 | 九门 | 门内注释（协调裁定 2026-09-18） | 设计取舍，登记口径 |
| E-10 | 门 9-hex 白名单=登记表动态派生（含 #576272/#18191c 等 token 面抄写放行） | 九门 | 门内注释 + 契约 §4「字面量须与登记值逐字符一致」 | 有牙（等值锁）——但与 S8-01 的黑名单空转一体两面：**等值的直写有锁、不等值的新散值无锁**。 |

---

## 第五部分：门的实际牙口——一句话裁决

**值册与供给链的「正门制」在阴影/半径/宽度/字体/色斑/玻璃成员判定上确有牙（289/289 绿且能咬活例），但色彩域的「禁表外」是名义条款（黑名单空转）、WebUI 宪法门是「六扫五绕」的浅网、哈希门漏着两个新枢轴文件（mica_shell/render_backends）且验收基线寄居 %TEMP%、验收脚本「全降级也 PASS」——四道门里两道半是礼貌门，收口宣称在「统一」方向属实、在「锁死」方向言过。**

---

## 附：本席实跑命令与输出（全部只读/临时盘）

```
$ date                                   → Sat Sep 19 15:59:40 2026
$ pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py tests/test_v21r3_visual_gates.py -q
  → 289 passed in 3.19s（收集数 132/58/99）
$ python tests/verify_hashes.py --check  → exit 0
$ node scripts/layout-constitution.mjs   → GATE_EXIT=0（先通读源码确认纯只读）
$ node -e "<dist 字节偏移探针>"           → fs-card@949677 / leading-none@949805（与审计 §6.4 逐字节一致）
$ grep 锚点若干（各台账行内附）
卫生自证：全程 PYTHONDONTWRITEBYTECODE=1 + --basetemp=$TEMP/s8-* + -p no:cacheprovider；
跑后门 `find plugins scripts tests -name __pycache__ -o -name .pytest_cache` 类目录零新增（本席未直跑裸 python -c import）。
```
