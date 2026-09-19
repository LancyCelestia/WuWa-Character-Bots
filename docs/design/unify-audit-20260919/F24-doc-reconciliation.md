# F24 · 前端/渲染文档宣称 ↔ 实盘逐句对账单 + 订正稿（零文档修改，只出稿）

> **快照声明**：`date` 实跑 = **Sat Sep 19 17:05:14 2026**（本席取证跨 17:05–17:4x，落笔期间主会话修复波仍在动树——`tests/test_webui_constitution.py` mtime **17:12** 即本席开工后落地，凡涉此文件的判词一律标注时点）。
> **工作区**：`c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`。
> **权限与纪律**：除本文件外**零新建/零编辑/零删除**；未跑 `--write` 系门命令；未 build/未起服务/未触发渲染；未做 git 写；未派子代理；直跑 python 一律 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe` + 只读 import（跑后 `find plugins scripts tests -name __pycache__ -newer AGENTS.md` 零新增）；未触 `personas/`、`.env`、`ChatBot_Runtime/`、`ChatBot_Archive/`、`data/`、`qx.json`。
> **措辞纪律**：本文不写「已修复」作为交付宣称；凡「他席/主会话已改」只表述为**本席读到的现势字节 + 时间戳**，收口判据以主会话自己的实跑为准。

---

## 〇、方法与判词定义

- **宣称条目**：文档里**可用命令/代码证伪**的陈述句（含数字、路径、名单、时态为「现状/已/常驻/锁」的断言）。带明确日期前缀的历史时点账（AGENTS #26/#29/#41 叙述段、HANDBOOK §19-§31、席位日志的「快照」自标注段）**不记为现行宣称**，只在 §六 交叉核对时引用。
- **判词五类**：`相符` / `夸大`（宣称执法面强于断言现实）/ `过时`（搬家/换名/换值/计数漂移）/ `纯纸面`（无任何断言）/ `矛盾`（与实盘或同族文档直接打架）。拿不准写 `无法判定+所需信息`。
- **独立证据**：每条给本席亲自读到的 `文件:行` 或只读命令输出；席位日志只作旁证不作主证（用户红线）。
- 本席读到的实盘现势基线（全部亲验）：模板 7 张（`ls templates/*.html`）+ 直拼卡 4 处 = **11 面**；真身=`domains/render/card_render/`，`output/card_render/*` 为逐文件 `Compat shim`（`theme_tokens.py:1` 自述）且其 `templates/` 为空目录；`SHADOW_CSS_VARS` = 三级族（`theme_tokens.py:181-185`）；`PLATFORM_THEMES` = 17 平台 + 4 别名（`theme_tokens.py:365-396`）；`CARD_SHELL_WIDTHS` = 11 键（:85-99）；`TYPE_SCALE_PX` = {26,20,15,13,12}（:213-219）；`verify_hashes.TRACKED_FILES` = **19 项**（:34-60）；机器册 `docs/auto-facts.md` = 模板 7 / topics 77 / 测试文件 423 / config 616 / 哈希清单 19；`SETTABLE=41 / RESTART=31`（import 实数）。

---

## 一、宣称条目对账总表（共 89 条）

**判定统计（由总表判定列程序化数出，命令贴 §七）**：`相符 31 ｜ 夸大 15 ｜ 过时 31 ｜ 纯纸面 4 ｜ 矛盾 8`，合计 **89**。

### 1.1 AGENTS.md（11 条）

| # | 坐标 | 宣称（摘） | 判 | 独立证据 |
|---|---|---|---|---|
| A1 | :24 | 「渲染契约——改任何卡片模板前必读，**契约测试会拦违规**」 | **夸大** | 契约 9 条铁律+§四中有 4 族条款零断言（见 C-R13/R17 与 R3 行证据）；色彩域「拦截」实为 8 值黑名单制（`tests/test_v21r3_visual_gates.py:363-372,563-572`：`if reason and normalized not in _REGISTRY_HEXES` 只咬黑名单值，表外新散值恒绿） |
| A2 | :91 | 渲染管线载体 = `output/card_render/` | **过时** | 该目录 6 个 .py 全为转发垫片（`output/card_render/theme_tokens.py:1` "Compat shim: moved to domains/render…"）；真身 `domains/render/card_render/`（bridge.py 2001 行 vs 垫片 128 行） |
| A3 | :91 | token 单一事实来源 `theme_tokens.py` | 相符 | 值册本体在 `domains/render/card_render/theme_tokens.py`（527 行全读）；「单一来源」的失守面属细则（见 D-S13/C-R16），本句方向正确 |
| A4 | :91 | PLATFORM_THEMES 17 平台显式注册表+别名 | 相符 | `_PLATFORM_ACCENTS` 恰 17 条 + 4 别名（theme_tokens.py:365-396）；`test_rendering_contract.py:469-499` 锁覆盖与 accent 互异 |
| A5 | :91 | 「两枚阴影 token」 | **过时** | 登记族=三级 `--mica-shadow/--mica-shadow-soft/--mica-shadow-panel`（:167-185）；7 模板均有 `var(--mica-shadow-panel)` 消费（如 market:78、error:76）；旁证 F5 §5-6 |
| A6 | :91 | 半径 30-18-14/宽度登记表/间距刻度 | 相符 | `ThemeTokens` 30/18/14（:315-317）+ `CARD_SHELL_WIDTHS` + `GAP_SCALE_PX`；gate01/05/06 有牙 |
| A7 | :91 | 「test_rendering_contract.py（**6 模板**逐条断言）」 | **过时** | 测试显式枚举 7 模板（`tests/test_rendering_contract.py:67-75`） |
| A8 | :91 | UI 铁律「**恰好**两枚阴影 token」 | **过时** | 同 A5；此句与 `docs/rendering-contract.md` 铁律 6（三级族）直接互斥——同文件两处口径并存 |
| A9 | :108 | 功能表「6 Jinja 模板 + 4 处 f-string 直拼卡」 | **过时** | 模板实数 7（`ls templates/*.html | wc -l` = 7，含 error_card.html 09-13 增）；契约自己已写「7 Jinja+4 直拼=11 面」（铁律 8） |
| A10 | :126 | 错误卡载体「`runtime/error_report.py`」 | **过时** | 该旧路径文件**不存在**（本席 `ls` 实测 MISSING，连垫片都没留）；真身 `domains/ops/monitor/error_report.py:856` 渲染入口（F14 T4 行+本席核） |
| A11 | :133-141 | 第五部分验证门禁 = dev.ps1 四任务 | **过时（信息缺项）** | 全量 pytest 自 **17:12** 起含 WebUI 三门（`tests/test_webui_constitution.py` 5 用例：宪法/tsc×2/确定性/package.json 一致性+cn 行为锁）；清单未注明「全量含前端三门」，也无独立前端任务（F18 §6 已建议补 `-Task webui` 行） |

### 1.2 DESIGN-SPEC.md（19 条）

| # | 坐标 | 宣称（摘） | 判 | 独立证据 |
|---|---|---|---|---|
| D-S1 | :3-4 | 本文件入 `verify_hashes.py` SHA-256 清单 | 相符 | `tests/verify_hashes.py:43` 列 "DESIGN-SPEC.md" |
| D-S2 | :5-8 | token 钉在 `domains/render/card_render/theme_tokens.py`（真身路径+垫片注记） | 相符 | 与实盘逐字节一致；**全库唯一写对新路径的入口文档**，收口建议以其为模板（§五） |
| D-S3 | :9 | 机器册由 doc_sync --write 重生成、--check 常驻 | 相符 | `tests/test_cross_validation_gates.py:40` `test_doc_sync_auto_facts_in_sync` 常驻 subprocess --check |
| D-S4 | :15 | 「所有圆角色块用 color-mix 把 --accent 与 wash 各 **7–10%** 混入白底」 | **纯纸面** | 无任何门扫混入比；面上现存表外值：`echo.py:3409` `color-mix(... 12% ...)`、`universal_card.html:1141` .footer-colored 8%/7%+accent 28%；契约/门 9 均不管此值 |
| D-S5 | :16-20 | 阴影三级族、只准 var() 引用、禁止自造 | 相符（附注） | `SHADOW_CSS_VARS` 三级+契约测试动态白名单（test_rendering_contract.py:202-221）；附注：直拼卡被 `test_exactly_two_shadow_token_definitions` 钉成**两级面**（族内 panel 档缺席），结构性不对称未在本文件注记（F5 §3 表阴影行） |
| D-S6 | :21 | 深色遮罩一律消费 OVERLAY 四员、表外禁止 | **纯纸面** | 登记值本体有锁（test_rendering_contract.py:676-684、test_mica_shell.py:375），**面扫零断言**：全 tests 无一条拦面上非登记暗 rgba（本席 grep scrim/rgba 断言面核）；旁证 F5 §5「遮罩四员=纸面」、S8-10 |
| D-S7 | :23 | zebra vis5 数值门 ΔE≥3.0/对比≥4.5 | 相符 | `tests/test_template_visual_audit.py::test_zebra_surfaces_distinct` 在位（:218） |
| D-S8 | :23 | 语义五色「一律消费语义 token，禁止卡私红绿黄」 | **夸大** | usage 卡现势直写登记值字面量：`usage_cards.py:255-257` `.status.ok/warn/bad → #2e9e6b/#b07d1a/#d54941`（本席 17:2x 实读）；门 8 对登记值直写恒绿（动态白名单自中和，见 A1 证据），「一律消费 token」无断言 |
| D-S9 | :24 | 「v21r3 C8 收口 12.5px→12px、13.5/14.5px→14px」 | **矛盾（与实盘）** | `echo.py:3392` `font-size:12.5px`、`:3409` `font-size:14.5px` 在 17:2x 现势树原样在位（锚点 `help-subtitle`/`help-section h2`）；门只设 ≥12px 下限故不红——文档宣称强于锁与实态 |
| D-S10 | :24 | 次级文字统一 TEXT_SECONDARY 单一来源 | **夸大** | 7/7 模板 :root 手写字面量 `--text-secondary: #576272`（affinity:40、error:34 等，本席抽验）；且与注入公共段 `--text-sub:#5b6069`（BRAND_THEME.text_sub，mica_shell.py:340）**同语义双 token 双值**并存（F5 §2-1）；改值册不会全卡同步 |
| D-S11 | :24 | 直拼卡壳「一律经 shell_base_css 消费登记值」 | **夸大** | 四处调用全传字面量：`echo.py:3369 width_px=940`、`debug.py:776 880`、`usage_cards.py:233 900`、`templates.py:73 640`（本席 grep）——`CARD_SHELL_WIDTHS` 对直拼卡是文档不是来源；另 `mica_shell.py:85 _DEFAULT_SHELL_WIDTH_PX=880` 未登记（F14-5「第 12 档」） |
| D-S12 | :24 | 「卡内 mono 一律 `var(--mono-family)`」 | **过时（命名漂移）** | 公共注入 token 实名 `--font-mono`（`_PUBLIC_TOKEN_ORDER`，mica_shell.py:57）；`--mono-family` 仅 error_card 局部别名（error_card.html:37 `--mono-family: var(--font-mono)`）——规范句写的是个例名，新模板照做会私设第二命名 |
| D-S13 | :28 | 「shell/色斑/玻璃经 mica_shell 生成器单源，**手抄副本=0 是常态门**」 | **夸大** | 色斑/装饰层成立（bridge 双键 `decor_css/blobs_html` 注入 7 入口）；**壳层不成立**：145deg 壳渐变模板侧 7 份+universal 内 3 份+生成器 1 份=11 份手抄（本席 `grep -c 145deg` 实数），`mica_shell.py:393` 生成器内还手抄了 GLASS_EDGE 同值第三形态（S8-03） |
| D-S14 | :33 | 改完跑门禁=5 个测试文件 | **过时** | 渲染门族现势 ≥8 文件：另需 `test_v21r3_visual_gates.py`（九门）、`test_token_supply_chain.py`（六门）、`test_mica_shell.py`（41 例）、`test_error_card_contract.py`——清单未随 v21r3 扩面 |
| D-S15 | :44 | 交付物 SHA-256 清单（**12 文件**） | **过时** | TRACKED_FILES=19 项（`sed -n '34,60p' verify_hashes.py` 亲数；机器册同记 19） |
| D-S16 | :45 | 门位置=`tests/perf_regression.py` | **过时（坐标）** | 实名 `tests/test_perf_regression.py`（ls 实证；缺 test_ 前缀则 pytest 不收集，坐标错会误导「门不存在」） |
| D-S17 | :47 | 全量回归「**4500+ 用例**」 | **过时** | 最近波次实跑 8532/8535 级（旧审计 §1 + AGENTS #41/#42）；且与 AGENTS:32 自订「用例数不手写文档」规矩冲突——建议整格删数改指针 |
| D-S18 | :49 | autosync 钩子=conftest `_autosync_session_gate` | 相符 | `tests/conftest.py:193` 定义在位 |
| D-S19 | :53 | 「诚实边界：叙述与实现冲突时**以测试门禁的实际断言为准**并回来改本文件」 | 相符 | 本条是全部本次判词可成立的前提条款；建议将其升格为渲染域判例并在契约头部引用（§五） |

### 1.3 docs/rendering-contract.md（24 条）

| # | 坐标 | 宣称（摘） | 判 | 独立证据 |
|---|---|---|---|---|
| C-R1 | :3 | 「适用于 `plugins/bot_unified_runtime/output/card_render/` 全部卡片模板」 | **过时** | 真身 `domains/render/card_render/`（A2）；本文件在哈希清单内，改需 `--write` 仪式 |
| C-R2 | :5 | 契约机器形态=test_rendering_contract（全离线字符串/Jinja/纯函数） | 相符 | 文件 825 行全读，零网络零 playwright |
| C-R3 | :6 | 「违反**任意一条**都会被契约测试拦下」 | **夸大** | 本表 R13/R14/R15/R17 四族条款零断言 + R6 半牙 + 门 8 黑名单化；「任意一条」不实 |
| C-R4 | :12-16 | 铁律 1-5（viewport/body 透明/字重≤700/动画在 .card 内/光晕≥0.05） | 相符 | 逐条有牙（contract:167-181,190-194,440-465 + builders:186-216,296）；旁路残口按 F5 §5 登记（`font-weight:bold` 命名值、`body.xxx` 选择器、`rgb(0 0 0 / x%)` 新语法）——不改变「条款有断言」判定 |
| C-R5 | :17 | 铁律 6 阴影登记族（三级）+白名单动态派生 | 相符 | :202-255 亲验：族外 token 一票否决、box-shadow 白名单从 `SHADOW_CSS_VARS` 派生、档位→ctx 键派生（P3-12） |
| C-R6 | :19 | 铁律 8：11 面恒 3 斑+时长集+**keyframes 只允许 mica-drift-a/b/c+手抄副本禁止**+「机器门锁数量与时长集合」 | **夸大** | 数量/时长：gate02 有牙但要求 `animation:mica-drift-x Ns` **连写**（拆 `animation-name:`+`animation-duration:` 即逃，F5 §5 半牙）；keyframes 名门**只扫 7 Jinja 模板**（`test_e03_typography.py:27-35` CARD_TEMPLATES 全 .html + :232 `test_e03_no_new_keyframes`），4 直拼卡零 keyframes 名断言（test_mica_builders_contract.py 全文 grep keyframes=0）；「手抄副本禁止」在伪元素侧不成立（R23） |
| C-R7 | :20 | 铁律 9 行高刻度 11 面全量枚举 | 相符 | gate03 ×11 面（v21r3_visual_gates 文件头第 4 条声明+ALL_SURFACES=7+4）；残口 `font: 13px/1.55` 简写漏（S8-10，登记不翻案） |
| C-R8 | :35-44 | 「模板 `--wash-*` 注入点写法（兜底字面量必须与 DEFAULT_WASH_TOKENS 逐键一致，契约测试锁定）」+四行 CSS 样例 | **过时** | 7 模板 `grep -c "default('#"` 全 0（本席实跑）；步 5 后公共段由 `render_root_tokens` 注入，断言退化为「若出现 default() 才等值锁」（test_rendering_contract.py:327-345）——规范句描述的是已退役形态（S8-07 复核成立） |
| C-R9 | :46-52 | §三 平台注册表条款（17 平台/别名二跳/未知落灰/bridge 派生） | 相符 | :469-523 四测亲验；steam/epic→UNKNOWN_THEME_KEYS（theme_tokens.py:399） |
| C-R10 | :56-61 | §四 阴影行：SHADOW_CSS_VARS 唯一登记处+模板字面量等值 | 相符 | 同 C-R5 + :225-255；注意 :61「或引用 bridge 注入的同名上下文键」双形态正是 §五.5 自相矛盾处（C-R22） |
| C-R11 | :63 | MONO_FONT_STACK 展示值（逗号后带空格形态） | **过时（表层）** | 登记值无空格 `'"Cascadia Mono",Consolas,…'`（theme_tokens.py:267）；本行展示多三个空格——契约自己违反自己「逐字符一致」的语感，新人照抄文档值即与面上不一致（gate07 走归一比较故不红） |
| C-R12 | :64 | 玻璃两档+描边 0.95/0.35/0.72、表外 alpha 禁止 | 相符（附豁免） | gate09 亲验在位；染色层按 GLASS3 裁定放行（v21r3_visual_gates.py:574-588 注释区），affinity/song 两档描边以「alpha ⊆ 集」放行——两例入 §四豁免册 |
| C-R13 | :65 | 深色遮罩 OVERLAY 四员、**表外深色遮罩禁止** | **纯纸面** | 同 D-S6：值锁在、面扫零；任意新暗 rgba 上 11 面通行（F5 §5；本席 grep tests 无 scrim/遮罩面断言） |
| C-R14 | :66 | 语义色五色「finance/market --up/--down、usage/debug good/bad、affinity --score-* **一律 var() 消费**；卡私红绿黄字面量禁止」 | **夸大** | 「一律 var()」零断言；现势活反例 usage_cards.py:255-257 直写（D-S8）；「卡私字面量禁止」实际只有 5 值有效黑名单（8 值表内 3 值被登记白名单自我中和：`if reason and normalized not in _REGISTRY_HEXES`，`#b07d1a/#157347/#b42334` 永不触发——本席读 :363-372+ :560-572 复核 F5-1/S8-01 成立） |
| C-R15 | :67 | 「全模板 `--text-secondary` 单一来源」+机器门=visual_audit | **夸大** | 门名实相符（test_secondary_gray_single_source 在位 :241），但「单一来源」机制不实=7 处面字面量+等值锁（D-S10）；改 TEXT_SECONDARY 一处**不会**全卡同步 |
| C-R16 | :68 | 「11 面全量收口：**11/11.5/12.5px→12px、13.5/14.5px→14px**；echo letter-spacing .14em→.06em」 | **矛盾（与实盘）** | 后半句真（echo.py:3390 `.06em` 亲验）；前半句对 echo 不实（12.5/14.5 现势在位，D-S9 同件）；字号下限 ≥12 门本身有牙（gate04+builders:323） |
| C-R17 | :68 末 | 「TYPE_SCALE_PX 为新增/改版模板**选用**阶梯」 | **纯纸面** | 全 tests grep TYPE_SCALE = **0 消费者**（本席实跑：仅 theme_tokens.py:213 定义处一命中）；机器册/测试/门均不引用；HANDBOOK §32.5 自己登记「TYPE_SCALE_PX 声明不接线」为诚实缺口——契约行未携带此注记 |
| C-R18 | :70-72 | 间距/行高/色斑行（值引用） | 相符 | gate05/03/02 + 值册亲验一致 |
| C-R19 | :73 | 「直拼卡壳**一律经 shell_base_css 消费登记值**」+宽度先进表再消费 | **夸大** | 同 D-S11 四处字面量实参；「进表」真、「消费表」假；universal 走 payload `card_width`+zoom 第三机制（F14-6.1 表） |
| C-R20 | :77 | §五.1「复制 `market_card.html` 的 :root 结构作为起点（最小完整样例：wash 注入+**两枚阴影 token**+drift 色斑+bot 页脚）」 | **过时（三重）** | ①步 5 后 market 等模板 :root 公共段**不在文件里**（test_rendering_contract.py:103-105 注释自证；market_card.html 源内仅卡特有键+`{{ shadow_elev_panel }}` 注入位）；②「两枚阴影」旧口径（C-R5）；③正确起点=生成器上下文键，复制模板文件=复制手抄副本，与本波「值册单源」哲学相反 |
| C-R21 | :78 | §五.2「根元素必须带 card 类（`<div class="shell card">` **或** `<div class="card">`）——截图选择器契约」 | **矛盾** | 两种范式并列即契约放行分叉；实盘根容器 **5 种范式**（`.shell.card`×4 模板/`.card>.panel`/`.card.mica-stage>.card>.video-card-shell`/`.card>pre.mermaid`/`stage.card>section.shell`×3 直拼），本句连现状都没描述全；`render_shell` 第 6 形态已建未接（F14-1/F5 §3，本席 grep 根 div 亲验四类）。改写稿见 §三.4.3-21 |
| C-R22 | :81 | §五.5「阴影只准用 `var(--mica-shadow)`/`var(--mica-shadow-soft)`/`none`，**两枚 token 定义**与 SHADOW_PRIMARY/SHADOW_SECONDARY 逐字符一致」 | **矛盾（文件内自打架）** | 与同文件铁律 6/§四（三级族，panel 合法）直接冲突；模板实盘大量 `var(--mica-shadow-panel)` 消费（market:78 等 14 处）且门绿——本句是被执法面淘汰的死句，新人照抄反会漏注 panel 档 |
| C-R23 | :82 | §五.6「`prefers-reduced-motion` 关停规则由 `_MICA_DECOR_CSS` 单源产出，**模板不手写**（C13）」 | **矛盾（与实盘）** | `grep -c prefers-reduced-motion`：mermaid_card.html=**2**、universal_card.html=**1**（本席实跑，mermaid :157-159 手写伪元素关停亲读）；「模板不手写」对色斑 DOM 关停真、对两处伪元素手抄面假——属登记特例但契约未收（F5 §4/X2-X3） |
| C-R24 | :93-100 | §六 payload 桥层契约（含好感度脏数据归一：None→0.0/双向面板缺省 50.0/cls 白名单/bar 钳 0-100） | 相符（附保留） | :539-593 亲验断言在位；保留意见：50.0+「友善」+半棒在卡上与实测不可辨 = F14-8 判 P1 的「呈现层造数」策略争议，契约把它钉成了预期——属裁定项不属笔误，列入 §三矛盾表尾注与 §五待裁 |

### 1.4 docs/HANDBOOK.md（11 条，取现行/§32 涉前端者）

| # | 坐标 | 宣称（摘） | 判 | 独立证据 |
|---|---|---|---|---|
| H1 | :240（章题「当前状态」）+:256-257（§6.3） | 卡片渲染「当前状态」：`capabilities/content_parser.py`+`output/card_render/`+「底色唯一来源 PLATFORM_COLORS 经 color-mix 掺白（壳 5-11%、面板 4-8%）」+「**单柔光阴影**」 | **矛盾（对同文件 §32）** | 与同文件 §32.1（三级阴影族/wash colorsys 派生 4 token/真身 domains/）直接打架；`content_parser.py` 真身在 `domains/link_parse/capabilities/`（F14 §3.3）；§6 全节标注「当前状态」却停留在 09-12 前形态——全书唯一「现势」章反而是最大陈旧块 |
| H2 | :2208 | 机器门三层：九门×11 面/供给链六门/WebUI 宪法扫描门 | 相符 | 三门族文件俱在（test_v21r3_visual_gates.py 九门 ALL_SURFACES=11；test_token_supply_chain.py 6 test；layout-constitution.mjs+GATE_EXIT=0 F4/F18/F5 三席独立实跑一致） |
| H3 | :2208 | 「供给链六门（23 passed：77 键并集/11 面 54 变量）」 | 相符（转述注） | 六门定义在位亲验；「23 passed/54 变量」为席位实跑转述（本席未跑，按 AGENTS 铁律 5 记转述证据可，判词随门体存在） |
| H4 | :2213+§32.3 :2229 | 「dist 971.64kB/**gzip 295.78kB（预算内）**」；§32.3「（spec 预算 **<150KB gzip 达标**）」 | **矛盾** | `webui-pages2-spec.md:131-133` 白纸黑字：「预算 <150KB；基线=143.34KB gzip，三页+d3-force 后**预估总 gzip <170KB**」——实测 295.78kB 超预估 74%；同一格内引用 <150KB 又自称达标=自相矛盾；无一处门锁体积（F8 前端零性能门） |
| H5 | :2214 | 「UIACC `webui_acceptance.py` **9 页 9 PASS 双轮+全 data**（支持 mock/真控制面双源）」 | **夸大** | progress-UIACC.md 实账：第一轮=mock 8743（8 data+dashboard graceful-mixed）、第二轮=**死端口 8749 全 graceful 也算 PASS**、「全 data」=MOCKUI2 后第三轮补跑（仍是 mock）；**真控制面 8742 一轮自认未跑**（其诚实缺口 2）；脚本 `--api` 缺省即 mock 端口（F2 §0）。判据「或」语义（S8-02/F4 §④）使「PASS」不携带数据强度信息 |
| H6 | :2215、:2257 | 「版式宪法**机器门常驻**」/常驻门清单含「WebUI 版式宪法扫描门+…command_catalog（--check EXIT=0）」 | **夸大（宣称先行、现实后至）** | 记账时点（§32.7，09-19 03:48 波）三门零接线铁证：F4 §① `grep -rn "layout-constitution\|tsc\|node --test" tests/`=0（16:0x 复验维持）；**17:12** 起 `tests/test_webui_constitution.py` 落地才成真——且其中「command_catalog --check 常驻」今仍不实：全 tests 无 --check subprocess（仅 test_autosync_gate 提钩子+test_doc_sync_gates 管 config-catalog 键覆盖，非 command-catalog 新鲜度门） |
| H7 | :2206-2207 | 「SWITCH 通水：decor 双键注入 6 上下文+7 自由面 **24 段**手抄副本消灭」 | 相符（限定域内） | 装饰层维度成立（bridge:172-190 亲验注入 7 入口）；壳层维度未做归 D-S13（该句自身有域限定，不翻案） |
| H8 | :2209 | 「基线 `baseline-20260919-paused` 19/19 STABLE；**自此 PNG 字节等值=全部 19 面验收判据**」 | **夸大** | 常驻 `tests/test_render_card_samples.py` 用 FakeBackend **并不真比 PNG**（F5 §7；本席核其文件头），字节判据只活在手工脚本 `scripts/render_card_samples.py` 里；基线目录寄居 %TEMP%（脚本常量名 `baseline-20260918` 与宣称名漂移，S8-05 锚点）——「升全面验收判据」的制度化并未随门落地，TEMP 一清判据即灭而无人知 |
| H9 | :2255 | 「机器册 `docs/auto-facts.md`（RouteKind 34/**topics 77**/测试 **422**/config **610**）」 | **过时（转抄即漂移活例）** | 机器册现势：topics **77** ✓、测试文件 **423**、config **616**——HANDBOOK 把生成物数值**二次转录**进自己，生成器一动本行即红字不实；AGENTS #41 注（AGFIX 席）已因同类问题收口过一次 |
| H10 | :2234 | 预检 7→9 项、27 passed（RESTPRE） | 相符（转述注） | check_webui 在位亲验（pre_restart_check.py:63 锚）；「9 项/27 passed」为席位转述；新鲜度第四查当时**无**（F10-02/F18 §4），17:1x 后是否已并入以主会话实跑为准 |
| H11 | :2241 | 诚实缺口「**TYPE_SCALE_PX 声明不接线**；玻璃 var() 切换（P3-19 延后）」 | 相符 | 与 C-R17/D-S13 互证——§32.5 是现库**最诚实**的一格；问题是契约/DESIGN-SPEC 未反向引用此注记（订正稿统一加指针） |

### 1.5 docs/design/webui-dashboard-spec.md（4 条）

| # | 坐标 | 宣称 | 判 | 证据 |
|---|---|---|---|---|
| W1 | :14/:29/:45 | 「热改面已诚实化（**SETTABLE 41/RESTART 31**）但无（表单）界面」 | 相符 | `domains/chat_reply/runtime/settings.py:454` import 实数 len=41/31（本席 venv 只读跑）；settings-dialog 只有 baseUrl/token 两键，Phase B 表单确未做——此句今晨仍真（唯一 SETTABLE 数值宣称与实盘一致的文档行） |
| W2 | :17 | 「axonhub 统一网关 **17 渠道**」 | **过时** | 09-17 瘦身波：注册表 42→17→10→16 终态+POTCCV 两路（AGENTS #36 六/七段）；设计文档未注日期致读作现状 |
| W3 | :33-41 | Phase A 页面五块+四新端点 | 相符（计划→已越实现） | 一二期 9 页+端点群已超（F2 12 请求全落真路由）；判「目标态达成且外扩」，文档头部建议加「已被 0918/0919 波次取代，现存态看 adoption/pages2-spec」 |
| W4 | :52-54 | WebUI 好感度直显数值（用户裁定）、聊天侧定性不变 | 相符 | `webui_stats.py:279-286` ×100 展示分（F13 A2 亲验）；聊天侧口径见 AGENTS 台账 |

### 1.6 docs/design/fstring-card-dom-spec.md（4 条）

| # | 坐标 | 宣称 | 判 | 证据 |
|---|---|---|---|---|
| FS1 | :3 | 「**状态：本规格未实施**，实施前需用户裁决」 | **过时** | 值层/CSS 生成器层（render_root_tokens/shell_base_css/mica_decor_css/drift_blobs_html+宽度入册+--pc 退役+--accent-ink 归一）已随 v21r3 **接入 4 卡**（ mica_shell.py 全读+直拼卡 import 亲验）；未实施的只剩**文档装配 render_shell（生产消费数=0，本席 grep 实证）+根范式统一（D5）+body/文档头（D7）+accent 解析三副本（D8）**——「未实施」整体判词不再真（F14 §2.1 逐项复核表） |
| FS2 | :7 | 「token 值层单一来源 `output/card_render/theme_tokens.py`」 | **过时** | 同 A2 路径搬家 |
| FS3 | :24-27 | 统一对象四坐标（`capabilities/echo.py:2622-2787` 等 4 处） | **过时** | v21r2 搬家+行号漂移；F14(f) 给全四条 before→after（echo 3261-3426/debug 718-816/usage_cards 71-321/templates.py 123-220，本席按当前锚点抽验 echo:3261/debug:717 命中） |
| FS4 | :30 | 对照组「universal_card.html（1665 行…）」 | **过时（快照值转现状口吻）** | 现 1719 行（本席 wc）；属带日期可容的行数断言，建议整行改「行数以当次 wc 为准」 |

### 1.7 docs/design/visual-effects-catalog.md（5 条）

| # | 坐标 | 宣称 | 判 | 证据 |
|---|---|---|---|---|
| V1 | :3 | 「状态：设计目录，**未实施**」 | **过时** | E01 相位钉帧（test_phase_determinism*.py 两文件在位+DESIGN-SPEC:26「全 11 面」）、E03 排印族（test_e03_typography.py）、截图确定性 D2→D1 换代已发生；E10 有一票否决裁定——「全未实施」不再真，需逐 E 号记实施态 |
| V2 | :4 | 事实来源「rendering-contract（**七条铁律**）」 | **过时** | 契约现 9 条铁律（铁律 8/9 为 v21r3 增） |
| V3 | :5 | 「`output/card_render/templates/*.html`（**6 模板**现状…）」 | **过时** | 真身路径+现势 7 张 |
| V4 | :22-24 | D2 现状「`--phase` 由内联脚本 `Math.random()` **每次覆写**（universal:1688-1694，六模板同构）」+「相位脚本无契约断言」 | **过时** | 7 模板 `grep -c Math.random` 全 0（本席实跑）；现态=payload digest 注入+render_backends WAAPI 钉帧（render_backends.py:233-278）+phase 锁测在位——「现状」两格描述的已是前世 |
| V5 | :28-30 | 测试侧开关=reducedMotion 命中既有关停（契约 §五.6 强制） | 相符 | 引用关系真；关停本身的手写例外归 C-R23 不重复记 |

### 1.8 docs/acceptance-manual.md §6.6.9/6.6.10（8 条）

| # | 坐标 | 宣称 | 判 | 证据 |
|---|---|---|---|---|
| AM1 | :384 | 离线证据=「test_webui_stats.py（**53 例**）」 | **过时** | 现势收集数：文件 29 个 `def test_` 参数化展开 58（F4 §① 分文件实跑「stats 58」；本席 def 计数复核增长事实）；「例数手写进文档」本身违 AGENTS:32 规矩——建议改跑法指针 |
| AM2 | :384 | test_webui_http.py（6 例） | 相符 | 6 def/6 collected（本席+两席日志一致） |
| AM3 | §6.6.9⑧ | 「侧边栏**六项导航**（总览/调用统计/Token/延迟/好感度/日志）」 | **过时** | 二期三页后导航 9 项（F12 §一逐行表+app-shell.tsx nav 数组:46-56）；六项=一期快照 |
| AM4 | :421（⑳） | 「字号**五档 12/14/16/18/20px**」 | **矛盾** | WebUI 五档实值=**12/13/14/18/30px**（`webui/src/index.css:228-232` 注释+@utility 五块亲读；F4 dist 字节表同值）——手册数值与宪法门「字号五档」绿结果所指的档位不是同一组数；卡片侧 TYPE_SCALE 又是另一组（26/20/15/13/12），两套阶梯被文档混写成第三套 |
| AM5 | :421（⑳） | 「机器门…色值字面量/任意值字号/刻度外间距/**圆角档外值命中=0**」 | **夸大** | 门对圆角**零执法**：layout-constitution.mjs 全文无 rounded 断言（P1-3② + S8 `grep rounded`=0 复验 + F4 沙箱 `rounded-[9px]` 0 命中）；该验收项按手册跑必然「=0」——因为根本不查 |
| AM6 | :421（⑳）/pages2-spec:125 | 「内联 style 仅画布容器两处白名单（高度/侧宽）且**在 progress 登记文件+行号**」 | **夸大** | 登记制只到注释：memory-graph.tsx:182「内联白名单 #1」道德约束（门本就不扫 height，F4 无牙-S8 E-7）；且 memory-canvas.tsx:179 canvas 字体字面量在扫描面外**未登记也抓不到**（F4 无牙-4）——「白名单+登记」暗示存在一个能执法的门，实际执法半径为零 |
| AM7 | ⑱ | `max_nodes≤200`、缺省 120 | 相符 | `webui_memory_graph.py:135` `_MAX_NODES_CAP/_DEFAULT_MAX_NODES` 亲验 |
| AM8 | ⑨ | 「总览三统计卡若仍带 mock 徽章=wave-2 真接口接线未完成的如实演示（非缺陷）」 | **过时** | dashboard.tsx `grep mock` 0 命中（本席实跑）；F9 证「前端源码零 mock 分支」；该行为接线前预案，现势无 mock 徽章可看 |

### 1.9 docs/README.md（3 条）

| # | 坐标 | 宣称 | 判 | 证据 |
|---|---|---|---|---|
| DR1 | :95 | fstring-card-dom-spec「**未实施，待用户裁决**」 | **过时** | 同 FS1；README 与 spec 头**双处登记同一状态行**=双点漂移（本席：两处现均不实） |
| DR2 | :96 | render-pipeline-optimization-spec「未实施，待用户裁决」 | **过时** | 该 spec L3 状态行同样自陈未实施；但 Phase 2 两键已接线（`config.py:629-630` bot_render_max_concurrency/wait_budget_ms 亲验+AGENTS #31 13fcd30 记录+生产 .env 值不可读不核）——至少「并发/预算」子项不实「未实施」；等待策略子项无法判定（需逐 § 对 render_backends 现码） |
| DR3 | :49-51 | webui/ 行（Vite+React+Tailwind4+singlefile、dist 挂 /ui）与 mock/acceptance 脚本行 | 相符 | F2/F8/F18 三席与实盘目录互证 |

---

## 二、最严重的 3 处「夸大/矛盾」（按误导决策深度排序）

1. **「一律/全部/任意违反必拦」型单源宣称三连**——`contract:6`（任意一条必拦）+ `contract:66/D-S8`（语义色一律 var() 消费）+ `contract:65/D-S6`（遮罩表外禁止）+ `DESIGN-SPEC:28`（手抄副本=0）+ `contract:73/D-S11`（宽度经表消费）。实况：色彩域执法=**5 值有效黑名单**（8 值表内 3 值被自家登记表白名单自我中和，本席逐行验证），新散值/登记值直写/壳层手抄 11 份/字面宽度四事**全在这几句的射程外**。这是「统一变量/统一函数」命题上文档与机器最成建制的一次互相拆台，也是本批「宣称比现实强」的模板案件。
2. **`acceptance-manual:421⑳` 与 `HANDBOOK §32.2` 把「宪法门扫圆角/字号五档 12/14/16/18/20」写成验收判据**——真档位 12/13/14/18/30、真执法无圆角。执行人按手册验收会得到「全绿」的假确证（F4 沙箱已实证骗过法），属**能制造错误结论的文档**，比不实更危险一档。
3. **`HANDBOOK:2215/2257`「版式宪法机器门常驻」+`:2214`「9 页 9 PASS 双轮+全 data」**——前者在记账时点（03:48）零接线（F4 16:0x grep=0 复证），至 17:12 才由本批修复波做实；后者把 mock+死端口 graceful 双轮压写成「双轮+全 data」且真源一轮从未执行（progress-UIACC 自供）。两者叠加的净效应：后来者会以为「前端产物层已有常驻执法 + 验收对过真后端」——**两句都不真**。

---

## 三、文档内部矛盾表（同一事实多口径；「真相源」=应然唯一登记者）

| # | 事实 | 口径 A（错/旧） | 口径 B（对） | 真相源裁定 |
|---|---|---|---|---|
| X1 | 模板数 | AGENTS:91/:108「6」、catalog:5「6」 | 机器册「7」=contract 铁律 8「7+4=11 面」=实 ls | 机器册（代码枚举）；contract 记「11 面」口径；AGENTS 改指针 |
| X2 | 阴影 token 数/族 | AGENTS:91「恰好两枚」、**contract 自己的 :77/:81 两处**「两枚」、market_card.html 头注释「两枚阴影 token」、mica_shell 头注「两枚」 | contract 铁律 6/§四=三级族（值册 :167-185）；DESIGN-SPEC:16-20 三级 | `theme_tokens.SHADOW_CSS_VARS`；「两枚」仅对 4 直拼卡成立（builders:229 钉死），必须写成「模板三级族/直拼卡两级面（不对称待裁）」 |
| X3 | token 文件路径 | AGENTS:91/108、contract:3、fstring spec:7、catalog:5 走 `output/card_render/` | DESIGN-SPEC:5-8（真身+垫片注记）+机器册 | DESIGN-SPEC 措辞为准，余四改指针；垫片存在期允许括注 |
| X4 | 前端门是否常驻 | HANDBOOK:2215/2257（03:48 时无效；17:12 起三门成真常驻，**command_catalog --check 至今仍不常驻**） | F4 §① 实测表 + 本席 grep（tests 内无 command_catalog --check subprocess） | 常驻清单=「跑一次 grep tests/ 的现势」——文档只写指针+判据命令，不写清单本体；catalog 新鲜度如要称门，先补 subprocess 锁 |
| X5 | 卡面数 | AGENTS「6+4」 | 契约 11 面；F14 补「骨架变体 13 套/根容器 5 范式+1 未接入」 | 「面」=11（机器册+contract）；「骨架/范式」是新轴，contract 现无此轴（铁律 10 缺位，F14 §7.1 亲证结构锁=只有根类名 1 条） |
| X6 | 字号档 | acceptance-manual⑳「12/14/16/18/20」；AGENTS:91「TYPE_SCALE」不写值 | WebUI=index.css 五档 12/13/14/18/30；卡片=TYPE_SCALE_PX {26,20,15,13,12}（且零门） | 两套阶梯分名分源：`index.css @utility fs-*`（WebUI 唯一真身，宪法门咬档名）与 `theme_tokens.TYPE_SCALE_PX`（卡侧，声明级）；文档禁再混写 |
| X7 | 宽度档位数 | contract §四列 7+4=11 键（与值册一致） | F14-5 补：`_DEFAULT_SHELL_WIDTH_PX=880` 第 12 档未登记 + universal payload 第三机制 + mermaid_max 异语义同表 | `CARD_SHELL_WIDTHS` 为唯一表，先收编 mica_shell 缺省（改查表或删参）再谈 11 键 |
| X8 | 现势渲染态 | HANDBOOK §6.3「单柔光阴影/PLATFORM_COLORS 掺白底色/旧路径」 | HANDBOOK §32/contract/值册 | §6.3 整节重写或加「09-12 史前快照，现势看 §32+contract」抬头（AGENTS 维护规矩本意=§1-§18 权威正文，现正文已不权威=最大内部打架） |
| X9 | config 字段数 | AGENTS:32「529」、HANDBOOK:2255「610」 | 机器册「616」 | 机器册（--check 常驻互证）；两处改指针 |
| X10 | 用例数 | DESIGN-SPEC:47「4500+」、acceptance :384「53 例」 | AGENTS:32 自订规矩「数以实跑为准」 | 实跑输出；文档删固定数 |
| X11 | TYPE_SCALE 执法 | contract/DESIGN-SPEC 未写「无门」 | HANDBOOK §32.5「声明不接线」 | 以 §32.5 为准回写 contract（一处加注） |
| X12 | 手抄副本=0 | DESIGN-SPEC:28（不限定域） | F5 §4 实数（壳层 11 份/玻璃 .glass 手抄 2 份 affinity:90、song:91）+contract 铁律 8（域限定装饰层） | contract 铁律 8 的限定句为准；DESIGN-SPEC 补域限定 |
| （尾注） | 好感卡缺省 50.0 | contract:99 把它写成契约预期 | F14-8：卡上 50.0+「友善」+半棒与实测不可辨=呈现层造数面（同段 steps 却用「—」，同卡两策略） | 属**用户裁定项**（改 `_pair` 缺数语义会砸既有锁），本席只登记冲突不改判 |

---

## 四、订正稿（before→after 全文；套用权在主会话；凡在哈希清单内的文件套用后须 `verify_hashes.py --write` 仪式重录，由收尾席统一执行）

### 4.1 AGENTS.md

**4.1-1（L24）**
- before：`docs/rendering-contract.md（渲染契约——改任何卡片模板前必读，契约测试会拦违规）`
- after：`docs/rendering-contract.md（渲染契约——改任何卡片模板前必读。执法地图：阴影族/宽度/gap/行高/字号下限/字体栈/玻璃档/色斑数量与时长有 11 面硬断言（v21r3 九门+契约族）；色彩散值当前为黑名单制（可被新值绕过，白名单化=F5-1/S8-01 待修）；遮罩四员/语义色 var() 消费/TYPE_SCALE/直拼卡 keyframes 四条暂无断言——各条执法面以契约「断言位置」列与 §七豁免登记表为准）`

**4.1-2（L91 渲染管线段整段）**
- before：`**渲染管线**：`output/card_render/` 云母+液态玻璃+釉瑚渐变漂移。**token 单一事实来源 `theme_tokens.py`**（BRAND 本命色/PLATFORM_THEMES 17 平台显式注册表+别名/两枚阴影 token/半径 30-18-14/宽度登记表/间距刻度；...）**UI 铁律**：...恰好两枚阴影 token、失败→纯文本兜底契约零破坏。`
- after：`**渲染管线**：`domains/render/card_render/`（兼容垫片 `output/card_render/`，模板真身在其 `templates/`，垫片 templates/ 已空）。**token 单一事实来源 `theme_tokens.py`**（BRAND 本命色/PLATFORM_THEMES 17 平台显式注册表+别名/三级阴影族 `SHADOW_CSS_VARS`（--mica-shadow 壳 / --mica-shadow-panel 面板 / --mica-shadow-soft 瓦片；f-string 直拼卡现势为两级面，缺 panel 档——被 builders 契约测试钉死，不对称待裁）/半径 30-18-14 + 内径刻度 {4,6,8,12,16}+pill/圆特例/宽度登记表 `CARD_SHELL_WIDTHS`（11 键；4 张直拼卡调用点现传字面量未查表，见 F14-5）/间距刻度/行高刻度/色斑恒 3 枚 46/52/58s；`docs/rendering-contract.md` 为规范正文+执法地图）；平台色只做 accent（--accent 不作底色，wash-mist 打底+色斑混入默认 35%、error 卡 24 为登记豁免）；`bridge.py` 消费注册表并保持历史导出面兼容。契约机器形态=`tests/test_rendering_contract.py`（7 模板逐条断言）+`test_mica_builders_contract.py`（4 处 f-string 直拼卡）+`test_v21r3_visual_gates.py`（九门×11 面）+`test_e03_typography.py`/`test_token_supply_chain.py`/`test_template_visual_audit.py`/`test_phase_determinism*.py`。→ `render_backends.py` playwright 常驻浏览器 `.card` 元素截图（WAAPI 钉帧 fail-open，钉帧成功率现不可观测=F5-6）。**UI 铁律**：无 `<meta viewport>`、body 透明、字重≤700、动画必须在 .card 内、光晕 alpha≥0.05、阴影只准登记族（模板三级/直拼卡两级）、失败→纯文本兜底契约零破坏。`

**4.1-3（L108 功能表行）**
- before：`| 卡片渲染 | output/card_render/ | 釉瑚云母卡片（见第三部分渲染管线；6 Jinja 模板 + 4 处 f-string 直拼卡全部走 theme_tokens 契约） | 随各能力 |`
- after：`| 卡片渲染 | domains/render/card_render/（垫片 output/card_render/，其 templates/ 现为空目录） | 釉瑚云母卡片（见第三部分渲染管线；**7 Jinja 模板 + 4 处 f-string 直拼卡 = 契约口径 11 面**，全部走 theme_tokens 契约；骨架/区段/字段命名未统一且无结构锁，见 docs/design/unify-audit-20260919/F14-card-ia.md） | 随各能力 |`

**4.1-4（L126 错误卡行）**
- before：`统一错误报告卡 | runtime/error_report.py + card_render/templates/error_card.html + ...`
- after：`统一错误报告卡 | domains/ops/monitor/error_report.py（旧路径无垫片）+ domains/render/card_render/templates/error_card.html + ...`（行内其余文字不动）

**4.1-5（L133-141 第五部分）**
- before：（四条 dev.ps1 命令 + 真机验收行）
- after：在代码块后追加两行：
```
# 说明：全量 test 自 2026-09-19 起含 WebUI 三门（版式宪法/tsc --noEmit×2/图布局确定性，
# tests/test_webui_constitution.py，硬依赖 node——缺 node 判 FAIL 不 skip）；渲染九门/供给链门同在树内。
```

**4.1-6（L32、顺带同族）**
- before：`config.py 529 字段（bot_* 口径，机器册 docs/auto-facts.md 为准）`
- after：`config.py 全 pydantic（bot_* 字段数以机器册 docs/auto-facts.md 为准，本文不转录数值）`——本席现值：机器册=616，AGENTS 529/HANDBOOK 610 两处均漂（矛盾表 X9）。

### 4.2 DESIGN-SPEC.md（哈希件，随收尾 --write）

**4.2-1（§一.2 :15）**
- before：`所有圆角色块用 `color-mix` 把 `--accent` 与 wash 各 7–10% 混入白底——"粉里透蓝、蓝里透粉"，禁止纯色死块。`
- after：`圆角色块以 color-mix 混入 accent/wash 成「粉里透蓝」质感，**常用档 7–10%**；混入比当前为构图目验项、无机器门（面上已存在 12%/28% 等功能性变体，如 echo 标题带、universal .footer-colored——如需收紧先建门再收面，禁以「一律 7-10%」作拦截宣称）。`

**4.2-2（§一.3 :16-20 末追加）**
- after 追加：`两级/三级不对称现状（2026-09-19 登记）：4 张 f-string 直拼卡的公共段只注入 --mica-shadow/--mica-shadow-soft 两级（tests/test_mica_builders_contract.py::test_exactly_two_shadow_token_definitions 钉死），L2 panel 档现仅 7 张 Jinja 模板经 bridge 上下文消费；「全模板三级族」宣称对直拼卡不成立，升三级或显式登记两级豁免待裁。`

**4.2-3（§一.4 :21）**
- before：`...一律消费 **OVERLAY 四员登记值**...，禁止表外深色遮罩。`
- after：`深色遮罩**应**消费 OVERLAY 四员登记值（值册+注入面有锁）；面扫执法暂缺——任意暗 rgba 散值当前不触任何门（F5/S8 登记），收紧方案见 docs/rendering-contract.md §四该行「执法面」列与 F24 对账单 §五豁免登记表的补门建议。`

**4.2-4（§一.7 :24）**
- before：`...已收口...echo letter-spacing .14em→.06em、gap 9px→8px）；TYPE_SCALE_PX 阶梯为新增/改版模板的选用基准，六张既有卡经实弹验收的展示级字号（26/23/22/17px 等）不受追溯；...直拼卡壳一律经 shell_base_css 消费登记值）；...mono 一律 var(--mono-family)...`
- after（同段内三处替换）：
  - 收口句改为：`...C8 收口适用于 7 张模板面（已落，门 4 锁 ≥12px）；**echo 直拼卡现势仍存 12.5px/14.5px**（echo.py `_help_mica_html` 区段，改值或改口径待裁，门因 ≥12 下限不红）；letter-spacing .14em→.06em、gap 9px→8px 已核实在位。`
  - 宽度句改为：`直拼卡壳宽度已入 `CARD_SHELL_WIDTHS` 登记，但四处调用现以字面量传 `width_px=`，**改表不跟随**（F14-5）；收口动作=调用点改查表 + mica_shell 私有缺省 880 并入登记表。`
  - mono 句改为：`卡内 mono 一律消费公共注入键 `var(--font-mono)`（error_card 内另有局部别名 --mono-family: var(--font-mono)，新模板勿再自造别名）。`

**4.2-5（§一.11 :28 ②）**
- before：`模板自动生效（shell/色斑/玻璃经 `mica_shell` 生成器单源，手抄副本=0 是常态门）；`
- after：`色斑/装饰层/玻璃规则经 `mica_shell` 生成器单源（已通水）；**壳层 wash 渐变与 150deg 描边仍是面上手抄**（模板侧 11 份 + 生成器内 1 份，F5 §4/S8-03），手抄=0 是目标态非当前门事实；收口方案=上下文键 `shell_css` 注入（F5-2 有稿）。`

**4.2-6（§二.2 :33 + §三表 :43-47）**
- before：`改完跑门禁：...5 个文件...`；表中`tests/test_rendering_contract.py 等 5 族`/`12 文件`/`4500+ 用例`/`tests/perf_regression.py`
- after：门禁清单改列全 8 件：`test_rendering_contract + test_mica_builders_contract + test_v21r3_visual_gates + test_token_supply_chain + test_template_visual_audit + test_e03_typography + test_phase_determinism(_2) + test_mica_shell`；哈希行改`交付物 SHA-256 清单（项数见 docs/auto-facts.md「哈希清单范围」行，现为 19）`；性能行改`tests/test_perf_regression.py`；全量行改`全量回归（用例数以最近一次 dev.ps1 -Task test 实跑为准，本文件不转录）`。

**4.2-7（§二.6 :37）**
- before：`...`python scripts/command_catalog.py --write`——两者 `--check` 均已进 pytest 常驻门。`
- after：`doc_sync --check 已进 pytest 常驻门（test_cross_validation_gates.py）；command_catalog --write 联动目录与文档，但其 --check **尚无 pytest 常驻 subprocess 锁**（现靠一致性测试族+autosync 钩子+人肉执行，F24 对账 AM/H6 条）——如需宣称常驻，先补锁再改词。`

### 4.3 docs/rendering-contract.md（哈希件；改动最密集，逐条给稿）

**4.3-1（L3 抬头）**
- before：`> 适用于 `plugins/bot_unified_runtime/output/card_render/` 全部卡片模板。`
- after：`> 适用于全部 11 个渲染面：7 张 Jinja 模板（`plugins/bot_unified_runtime/domains/render/card_render/templates/*.html`，error_card 为 2026-09-13 增）+4 处 f-string 直拼卡（`domains/chat_reply/capabilities/echo.py` `_help_mica_html`、`domains/ops/admin/debug.py` `_llm_setup_mica_html`、`domains/render/card_render/usage_cards.py`、`domains/render/templates.py`）。历史路径 `output/card_render/` 为 v21r2 兼容垫片（其 templates/ 已空）。`

**4.3-2（L6）**
- before：`> 任何 AI 或人，改模板前先读完本页；违反任意一条都会被契约测试拦下。`
- after：`> 任何 AI 或人，改模板前先读完本页。各条铁律的执法面在「断言位置」列如实登记：**有牙条款**违反必红；**半牙条款**列明可绕形态；**纸面条款**当前是规范承诺、无机器拦截（收紧路线见 §八「豁免登记与待补门」）。`
（并执行 4.3-3 的表列改造。）

**4.3-3（铁律 8 :19「机器门锁数量与时长集合」句 + 铁律表增设列）**
- before：`...手抄副本禁止；error 卡 wash_blob_mix=24 为显式登记豁免 | 两枚/零枚卡与私调时长是 v21r3 审计实锤的漂移源；机器门锁数量与时长集合 |`
- after：`...装饰层（DOM 斑/keyframes/reduced-motion 关停）由 mica_shell 生成器单源产出，手抄禁止；伪元素侧两处登记特例仍为手写（见 §八 E-2/E-3）；error 卡 wash_blob_mix=24 为显式登记豁免 | 数量与时长：gate02 覆盖 11 面（要求 `animation:mica-drift-x Ns` 连写形态，拆分写法可绕——已登记旁路）；keyframes 名门（e03）只覆盖 7 张 Jinja 模板，4 直拼卡现仅靠生成器同源、无独立名门（待补，见 §八 D-1）|`

**4.3-4（L35-44 §二 wash 注入写法）**
- before：`模板 `--wash-*` 注入点写法（兜底字面量必须与 `DEFAULT_WASH_TOKENS = derive_wash_tokens('#607080')` 逐键一致，契约测试锁定；值随派生算法单一来源，勿手改）：` + CSS 样例块
- after：`公共段（含 --wash-* 四键）自 v21r3 步 5 起由 `mica_shell.render_root_tokens` 单一注入，模板文件不再书写兜底字面量（现势 7 模板 `default('...')` 实例数=0）。历史形态注：早期模板内联 `default('#d9e0e7')` 等兜底字面量须与 `DEFAULT_WASH_TOKENS` 逐键一致——如任何面重新出现该形态，契约测试仍按等值锁判红。`

**4.3-5（L63 mono 展示值）**
- before：`| `MONO_FONT_STACK`（v21r3 C9） | `"Cascadia Mono", Consolas, "JetBrains Mono", "Courier New", monospace" |`
- after：`| `MONO_FONT_STACK`（v21r3 C9） | `"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace`（登记值逗号后无空格，引用以 theme_tokens.py 为准） |`

**4.3-6（L65 遮罩行——「要么补断言要么删宣称」裁定件）**
- 推荐选择：**补断言（短期先改词挂债）**。
- 断言设计要点（供补门席）：新增 `gate10_scrims`——对 11 面 CSS 文本提取 `rgba(r,g,b,a)` 且 `r+g+b<300`（暗色系）且出现于 background/gradient stop 位的字面量，白名单=OVERLAY_SCRIMS 四员逐值 + 功能常量（遮罩外的边框/滚动条登记值）+ §八 豁免册；命中表外即红。注意与 gate09（白玻璃）、glow 下限（铁律 5）划界，避免同值双门互踩。
- 过渡 after（若不补门）：`| 深色遮罩 | `OVERLAY_SCRIMS` 四员（v21r3 C5） | 四员值（scrim_badge/banner/code/media 逐值照册）已锁值册与注入面；**面扫暂无断言**——「表外深色遮罩禁止」为规范承诺，执法收紧前新增暗 rgba 不触门（债项 D-2） |`

**4.3-7（L66 语义色行）**
- before：`...一律 `var()` 消费；卡私红绿黄字面量禁止（universal amber 装饰族豁免，非语义色） |`
- after：`...应经 `var(--semantic-*)/--score-*` 消费；字面量直写**登记值**当前按等值放行（gate08 白名单=登记表动态派生），卡私**表外**色值仅命中 8 员黑名单时拦截（其中 #b07d1a/#157347/#b42334 已被登记值白名单中和，有效黑名单=#d64545/#1a9e6c/#555/#444/#999 五值）——「禁止卡私红绿黄字面量」的全称执法待 gate08 白名单化（F5-1/S8-01 方案在案）；universal amber 装饰族豁免（非语义色，§八 E-4）；活反例登记：usage_cards `.status.*` 直写 #2e9e6b/#b07d1a/#d54941（改 var() 消费一行为出了稿未执行，§八 D-3） |`

**4.3-8（L67 次级文字行）**
- before：`全模板 `--text-secondary` 单一来源；...机器门 `test_template_visual_audit.py`；...`
- after：`次级灰目标态=单一来源：现势为「值册 TEXT_SECONDARY(#576272) + 7 模板 :root 等值手抄 + test_secondary_gray_single_source 等值锁」——**改值册不会全卡自动同步**（手抄未收敛前，"单一来源"指唯一合法值、不指注入路径）；另一缺口：公共注入段的 `--text-sub`(#5b6069，BRAND_THEME.text_sub) 与 `--text-secondary` 同语义双 token 双值并存，收口方案（text-secondary 并入 render_root_tokens 公共段并裁双值孰真）列 §八 D-4；...（对比门句保留）`

**4.3-9（L68 字号行）**
- before：`...机器门锁 11 面（v21r3 C8：11/11.5/12.5px→12px、13.5/14.5px→14px 已收口；echo letter-spacing .14em→.06em、gap 9px→8px）；`TYPE_SCALE_PX` 为新增/改版模板选用阶梯，既有卡实弹验收字号不受追溯 |`
- after：`字号下限 ≥12px 由机器门锁 11 面（gate04+builders:323）；C8 收口在 7 张模板面已落，**echo 直拼卡现势仍存 12.5px/14.5px**（下限门不咬、收口口径对直拼卡未兑现，改值或改口径待裁 §八 D-5）；letter-spacing/gap 已核实在位；`TYPE_SCALE_PX` 为新增/改版模板**选用**阶梯——纯声明、无机器门（test 全树零消费，见 HANDBOOK §32.5「声明不接线」），存量展示级字号不受追溯 |`

**4.3-10（L73 宽度行 + L83 §五.7 同步）**
- before：`...直拼卡壳一律经 `shell_base_css` 消费登记值 |`
- after：`...4 张直拼卡宽度已入表，但调用点现传 `width_px=<字面量>`（echo 940/debug 880/usage 900/media 640），**不经查表**；`mica_shell._DEFAULT_SHELL_WIDTH_PX=880` 为未登记第 12 缺省档——收口=实参改 `CARD_SHELL_WIDTHS[...]` + 缺省并表（§八 D-6） |`

**4.3-11（L77 §五.1 起点条）**
- before：`1. 复制 `market_card.html` 的 `:root` 结构作为起点（它是最小完整样例：wash 注入 + 两枚阴影 token + drift 色斑 + bot 页脚）。`
- after：`1. 新卡**不复制任何 CSS 声明**：Jinja 卡以 `bridge._card_root_tokens(...) + **_vis4_context()`（`decor_css`/`blobs_html`/`shadow_elev_panel`/`divider_line` 等上下文键）为唯一起点（照 finance_card.html 的消费法）；f-string 卡经 `mica_shell.render_shell()/render_root_tokens/shell_base_css` 装配。公共 :root 段自步 5 起不在模板文件内书写——「复制 market_card.html 的 :root」在现架构下无处可抄。`

**4.3-12（L78 §五.2 根容器条——F14 改写稿采纳 + 现状注记）**
- before：`2. 根元素**必须**带 `card` 类（`<div class="shell card">` 或 `<div class="card">`）——截图选择器契约。`
- after：`2. 根元素**必须**带 `card` 类（截图选择器契约，`render_backends` 固定 query `.card`）。统一目标态（待裁+待迁）：全项目唯一装配式 = `render_shell()` 的 `<div class="card {stage}"><section class="{shell_class}">…</section></div>`（shell_class 空则单层）。现势注记（2026-09-19 登记，非合规清单）：存量并存 5 种根容器形态——`<div class="shell card">`（affinity/error/finance/market）、`<div class="card">`（mermaid/song）、`.card>.panel`（media 直拼）、`.card.mica-stage>.card>.video-card-shell`（universal 视频分支）、`.stage.card>section.shell`（echo/debug/usage）；本条历史文字「两种并列合规」作废，新卡**禁用**任何未在目标态出现的自造骨架，迁移逐面带截图基线执行（F14-1）。`

**4.3-13（L81 §五.5 两枚阴影句）**
- before：`5. 阴影只用 `var(--mica-shadow)` / `var(--mica-shadow-soft)` / `none`，两枚 token 定义与 `SHADOW_PRIMARY`/`SHADOW_SECONDARY` 逐字符一致；...`
- after：`5. 阴影只准 `none`/`var()` 引用 `SHADOW_CSS_VARS` 登记族三员（--mica-shadow/--mica-shadow-panel/--mica-shadow-soft）；模板 :root 定义与登记值等值或经 bridge 上下文键注入（与铁律 6/§四同口径，本条旧「两枚」措辞系 vis4 换代前遗留）；白玻璃只允许 GLASS_MAIN/GLASS_FOOT 两档 + 描边 0.95/0.35/0.72（v21r3 C3；染色层放行按 §八 E-5）。`

**4.3-14（L82 §五.6 reduced-motion 句）**
- before：`...`prefers-reduced-motion` 关停规则由 `mica_shell._MICA_DECOR_CSS` 单源产出，模板不手写（C13）。`
- after：`...`.drift-blob` DOM 色斑的关停规则由 `mica_shell` 装饰层单源产出，模板不手写（C13）；mermaid_card.html（::before/::after 双斑）与 universal_card.html（伪元素段）仍各存**手写关停+手写伪元素 drift**，属登记特例（§八 E-2/E-3，随骨架迁移动态作废）。`

**4.3-15（新增 §八「豁免登记与待补门」——全文即本文件 §五，直接可粘）** + 同时在 §六末尾加指针行：`- 逐能力接线不改变本契约；卡片「区段/字段命名」骨架轴现无契约条款亦无断言（结构锁=根类名 1 条，F14 §7.1 亲证），立项与否随 v21r4 裁决（§八 D-7）。`

### 4.4 docs/HANDBOOK.md

**4.4-1（§6.3 抬头 :256 前插一行 + :257 两处旧句）**
- before：（:257 内）`管线：`capabilities/content_parser.py:render_card_png`...→ `output/card_render/`（bridge + templates/）。规范铁律：底色唯一来源 `PLATFORM_COLORS`（bridge.py）经 `--accent` 变量 `color-mix` 掺白派生（外壳 5-11%、面板 4-8%），**禁写死品牌色**；单柔光阴影；...`
- after：`管线：`domains/link_parse/capabilities/content_parser.py:render_card_png`（事实注 2026-09-19：该中央出卡件现居能力域、8 消费方经垫片路径导入，收口方案=F14-6 emitter）→ `domains/render/card_render/`（bridge + templates/，`output/card_render/` 为垫片）。**本节以下为 2026-09-12 前形态的史前快照**（「底色 PLATFORM_COLORS 掺白 5-11%/4-8%」「单柔光阴影」已被 wash 四 token 派生 + vis4 三级阴影族取代，现势铁律以 `docs/rendering-contract.md`+§32.1 为准）；...`（其余正文保留原样加历史注）

**4.4-2（:2213/§32.3 WebUI 行「预算内/达标」）**
- before：`...971.64kB/gzip 295.78（预算内）。` / `dist 单文件 971.64kB/gzip 295.78kB（spec 预算 <150KB gzip 达标）零 CDN`
- after：`...971.64kB/gzip 295.78kB（**超 pages2-spec §6 预算口径：总 gzip 预估 <170KB、单项引用值 <150KB，实测 295.78kB≈预估 1.7 倍——预算裁定权交用户**：要么改预算承认 singlefile 全内联形态，要么拆分/裁剪依赖）。`（零 CDN 保留——该句真，F8 实证）

**4.4-3（:2214 UIACC 行）**
- before：`UIACC `webui_acceptance.py` 9 页 9 PASS 双轮+全 data（支持 mock/真控制面双源）。`
- after：`UIACC `webui_acceptance.py`：mock 8743 一轮（8 data+dashboard graceful）+死端口 8749 一轮（全 graceful 判 PASS）；MOCKUI2 补齐后端点夹具复跑一轮 9/9 全 data——**三轮均为 mock 夹具，真控制面 8742 未跑**（progress-UIACC 诚实缺口 2 在案）；判据「或」语义（graceful 也 PASS）收紧方案见 F24 §一 AM/S8-02。`

**4.4-4（:2215/:2257「常驻」两处 + command_catalog）**
- before：`版式宪法机器门常驻；...` / `- 常驻门：`tests/test_v21r3_visual_gates.py`（九门）+供给链六门+WebUI 版式宪法扫描门+verify_hashes/doc_sync/command_catalog（--check EXIT=0）。`
- after：`版式宪法门：0918 波交付+0919 PAGES2 修正；**接入 pytest 常驻=2026-09-19 17:12 `tests/test_webui_constitution.py`（F18 设计稿落地，硬依赖 node=缺 node 判 FAIL 不 skip）**；接入前（含本波次 03:48 记账时点）该门仅挂 `npm run build` 前置+人肉跑——引用本句需知时序。` / `- 常驻门（现势清单以 grep 为准，本行 2026-09-19 收口）：`tests/test_v21r3_visual_gates.py`（九门）+`test_token_supply_chain.py`（六门）+`test_webui_constitution.py`（WebUI 三门+package.json 一致性+cn 行为锁）+`test_cross_validation_gates.py`（verify_hashes/doc_sync --check subprocess）；**command_catalog --check 不属常驻 subprocess 门**（靠 test_doc_sync_gates 键覆盖+一致性测试族+autosync 钩子+人肉 --write，措辞如须「常驻」以补锁为准）。`

**4.4-5（:2209 PNG 字节判据句）**
- before：`基线 `baseline-20260919-paused` **19/19 STABLE**...；自此 PNG 字节等值=全部 19 面验收判据...`
- after：`样张基线（%TEMP%/shorekeeper-samples/，脚本内目录名 baseline-20260918*）19/19 STABLE=手工脚本 `scripts/render_card_samples.py` 于 09-19 时点的实跑结论；**判据制度现状**：常驻 `test_render_card_samples.py` 走 FakeBackend 不真比字节，基线不入库不入哈希、TEMP 清理即永久失锁，且钉帧成功率零观测（F5 §6/§7、S8-05）——「PNG 字节等值=全面验收判据」要成立，需先落：基线 sha256 旁车入库+`pinned==0` 告警+浏览器指纹字段（列 §八 D-8）。`

**4.4-6（:2255 机器册转抄行）**
- before：`机器册 `docs/auto-facts.md`（RouteKind 34/topics 77/测试 422/config 610）`
- after：`机器册 `docs/auto-facts.md`（数值以当次 --check 通过态为准，本行不转录——现势：RouteKind 34/topics 77/测试文件 423/config 616/哈希清单 19，2026-09-19 17:2x 亲读）`（更彻底做法：删数值只留指针）

### 4.5 docs/acceptance-manual.md

**4.5-1（:384 例数两处）**
- before：`离线证据=tests/test_webui_stats.py（53 例）+ tests/test_webui_http.py（6 例）+ control_plane 全族回归 290 passed`
- after：`离线证据=定向复跑 `pytest tests/test_webui_stats.py tests/test_webui_http.py -q`（数以当次实跑为准；0919 波收口时点 58+6），control_plane 全族回归见 progress-BACKEND 实跑记录`
**4.5-2（§6.6.9⑧ 导航数）** before `侧边栏六项导航（总览/调用统计/Token/延迟/好感度/日志）` → after `侧边栏九项导航（总览/调用统计/Token/延迟/好感度/日志/知识库/插件/记忆图谱；二期三页 0918 增）`
**4.5-3（:421⑳ 两判据）** before `（色值字面量/任意值字号/刻度外间距/圆角档外值命中=0）；零硬编码色值与字号（...字号五档 12/14/16/18/20px；间距 4px 刻度；圆角 30/18/14）` → after `（门实际四判据=裸 hex/阶梯外字号类/刻度外 padding·gap 类/调色板类名——**圆角当前无门**（rounded 断言不存在，`rounded-[9px]` 类任意值放行；补门方案=F4 N4/P1-3 改法，补成前本验收项不得含「圆角命中=0」预期）；字号五档实值=**12/13/14/18/30px**（fs-caption/body/card/page/num，index.css @utility 为唯一档源）；间距 4px 栅格；圆角由 index.css theme 钉值 md/lg/xl=14/18/30 间接保证（类名形态安全、任意值形态无执法）`；同格「内联 style 仅两处白名单」句后追加：`注：该白名单是注释制——门不扫内联尺寸，登记靠 progress 文件+行号（执法半径如实，memory-canvas 字体字面量现游离于门与登记之外，§八 E-8 收编）`

### 4.6 三份规格状态行

**4.6-1 fstring-card-dom-spec.md:3**：采用 F14 §7.2(f) 全文（「**部分实施（2026-09-19 复核）**：值层与生成器层已接入 4 卡；render_shell 整文档装配（生产消费数=0）、根范式统一（D5）、body/文档头（D7）、accent 三副本（D8）、宽度查表（D6 实质项）未实施」+四坐标修正清单）——本席复验其每条证据仍真，照抄可用。
**4.6-2 render-pipeline-optimization-spec.md:3**：before `状态：设计规格（本规格未实施...）` → after `状态：部分实施（2026-09-19 复核）——等待预算/并发两键已接线（config.py bot_render_max_concurrency/bot_render_wait_budget_ms，13fcd30/AGENTS #31）；信号驱动等待/渲染缓存/热点清理各子项实施态待逐 § 对 render_backends.py 现码复核，未复核子项不得沿用旧「未实施」或新「已实施」判词。`
**4.6-3 visual-effects-catalog.md:3-5**：状态行改 `状态：特效目录（2026-09-19 起逐 E 号记分实施态：E01 相位 digest 已实施（test_phase_determinism*）、E03 排印族已实施（test_e03_typography）、E10 一票否决维持；其余逐号待复核）`；事实来源两处 `七条铁律`→`九条铁律（本目录成文时为七条）`、`output/card_render/templates/*.html（6 模板）`→`domains/render/card_render/templates/*.html（现 7 模板）`；D2 行「现状」两格加历史冠：`（历史现状=09-13 时点；今：Math.random 内联脚本已从全 7 模板移除（grep 实测 0），相位由 payload digest 注入+WAAPI 钉帧，锁测在位）`
**4.6-4 docs/README.md:95-96**：两行状态括注分别改 `（部分实施：值层/生成器层已接入，DOM 装配层待裁）`、`（部分实施：并发/预算两键已接线，余子项复核中）`——与 4.6-1/2 同步，防双点登记再漂移。

### 4.7「机器门锁死/一票否决/常驻」措辞统一表（用户特别要求①）

| 位置 | 现词 | 实际执法面 | 替换 |
|---|---|---|---|
| AGENTS:24 / contract:6 | 「契约测试会拦违规/任意一条必拦」 | 9 条铁律+§四中 4 族零断言、gate08 黑名单 5 值有效 | 见 4.1-1 / 4.3-2 |
| contract:19（铁律 8 原因列） | 「机器门锁数量与时长集合」 | gate02 有牙（连写形态）；keyframes 名门仅 7 模板 | 见 4.3-3 |
| contract:65 / DESIGN-SPEC:21 | 「表外深色遮罩禁止」（语义=门拦） | 零面扫 | 见 4.2-3 / 4.3-6 |
| contract:66 / DESIGN-SPEC:23 | 「一律 var() 消费、卡私字面量禁止」 | 等值放行直写+5 值黑名单；usage 直写实反 | 见 4.3-7 |
| DESIGN-SPEC:28 | 「手抄副本=0 是常态门」「表外值由机器门一票否决」 | 壳层 11 份手抄无份数门 | 见 4.2-5；「一票否决」保留给阴影/半径/宽度/字体/gap/行高/下限六族（确有牙） |
| HANDBOOK:2215/2257 | 「常驻」 | 03:48 时点零接线→17:12 成真；catalog 仍不常驻 | 见 4.4-4 |
| acceptance-manual:421⑳ | 「圆角档外值命中=0」 | 无圆角门 | 见 4.5-3 |
| AGENTS #41/DESIGN-SPEC:27（「由测试门禁实际断言为准」） | DESIGN-SPEC:53 已有总缓冲句 | — | 保留并升格：在 contract:6 与 AGENTS:24 指向该判例句 |

---

## 五、豁免登记表草案（可直接粘为 `docs/rendering-contract.md` §八；本席不粘）

> 规矩：豁免只有两个合法来源——本表登记，或值册登记（登记即等值放行，不算豁免）。新增豁免须注明裁定出处；列外=违例。失效条件到点的豁免应删行并执行收口。

| # | 豁免物 | 所在面 | 理由 | 验收判据 | 登记批次 | 失效条件 |
|---|---|---|---|---|---|---|
| E-1 | `wash_blob_mix=24`（默认 35） | error 卡（bridge `_card_root_tokens` 参数实值） | v21r3 C2 显式裁定：红 accent 卡混 35 过艳，视觉不变硬约束 | `test_core_registry_blob_constants_exact` 邻域 + bridge 参数等值（24 出现即须配本行） | 0918 通水波 | 若 error 卡壳重绘经用户裁定，行删 |
| E-2 | `.card::before/::after` 双斑 + 手写 reduced-motion 关停（时长 46/58s 咬登记集） | mermaid_card.html | 伪元素形态先于通水存在；C13 根修只收 DOM 斑侧 | gate02 时长/名称集合绿；手写关停规则恰含两伪元素选择器（多一处=红）；份数注释在模板内 | 0918（MISC 换血波） | F14-1 骨架迁移把伪元素改走 blobs_html 时行删 |
| E-3 | 「双伪元素+DOM 第 3 斑」混合体、斑几何私调（::before 62%/-16%/-24% ≠ _BLOB_SPECS 58%/-14%/-22%） | universal_card.html | 宽版双栏历史构图验收过；几何偏差=登记名同源参数私调 | 相位锁测（test_phase_determinism_2 守卫）绿；斑几何改动需先改本行 | 0918 通水波 | 同上随骨架统一收编 |
| E-4 | amber 装饰族 6-7 枚（#ff9800/#e65100/#f5b83b/#f0b429/#b77900/#fff7d6 系）+ `--blue:#23ade5` + 认证徽 `#1d9bf0` + 中性对 #e4e6eb/#f1f2f3 族 | universal_card.html | 契约 §四「amber 装饰族豁免」在案；--blue/认证蓝为上游平台语义色复刻非品牌色 | gate08 不红（黑名单外）；**如执行 4.3-7 补白名单门，本行值必须先迁入豁免册或值册** | 0912-0918 散点（本表首次集中收编） | 色族收编进 theme_tokens 后并入「登记即放行」，本行删 |
| E-5 | `.footer-colored` 描边白 0.98/0.88（+accent28% 染色中段） | universal :1141 | GLASS3 席 0919 主会话裁定=sanctioned 变体，现仅活在门 docstring | gate09 染色层整层放行；本行落地后 docstring 裁定指针化 | 0919 GLASS3 | 描边层如改 `var(--mica-glass-edge)` 消费则删 |
| E-6 | 两档描边变体 `.ttl`（song）/`.pill`（affinity）（.95/.35 无 .72） | 2 模板 | 「成员判定」语义天然放行；裁定为合法档位了事（S8 E-5 二选一，推荐此） | gate09 现口径绿即合规；如改「EDGE 全模式匹配」门则本行失效并需改面 | 0919 F5/S8 发现→本表登记 | 全模式匹配门落地时收编或删 |
| E-7 | affinity :root 内联 `style=background:…linear-gradient(150deg,…)` 描边副本 7 处（:251-281 区段） | affinity_card.html | 行内 zebra 叠层需要 per-row 覆写；手抄副本暂无法参数化 | 份数不增（新增内联描边=红，先改本行或收编）；视觉与 canonical 等值 | 0913 vis4 存量 | `--mica-glass-edge` 可被 inline 消费的机制落地时收编 |
| E-8 | recharts 图元字号 12px CSS 钉死 | webui/index.css:316-321 | SVG tick/legend 不吃 Tailwind 类；与 fs-caption 同值有意为之 | 定义处集中（选择器表内命中=1 处）；宪法门禁 tsx `fontSize:` 互补成立 | 0919 WEBUIFE | WebUI 字号定义层如被扩门收编则并册 |
| E-9 | canvas 字体字面量 `context.font='12px "Segoe UI", …'` | webui memory-canvas.tsx:179 | canvas 2D 不吃 CSS 变量（需 getComputedStyle 读 token，未做）；现游离于一切门与登记之外——**本行即 P1-3④ 的补登记** | 补门前：字体栈与 FONT_FAMILY_STACK 一致目验；补门后（F4 N4 方案 `context.font` 扫描）改判红为合法登记态 | 0918 审计发现→本表收编 | 读 token 版实施时行删 |
| E-10 | 内联 `style={{height:480}}` 「内联白名单 #1」 | memory-graph.tsx:182（注：非 memory-canvas.tsx，旧审计坐标错） | pages2-spec :125 两处白名单之一（画布高度）；道德约束非机器约束（门本不扫尺寸内联） | 白名单实例=2 处（高度+侧栏宽）不得增 | 0918 PAGES2 | 内联尺寸扩门落地时程序化 |
| E-11 | 宽度门整体剥离 `@media` 块（559/720px 断点不入册） | 九门 gate06 设计取舍 | 断点是视口概念非壳宽；入册会混淆两轴 | 剥离仅限 @media 块内；块外私有宽度=红 | 0918 协调裁定（门注） | 如需「断点登记表」另立新轴 |
| E-12 | 直拼卡阴影两级面（无 --mica-shadow-panel） | 4 直拼卡 | builders:229 测试钉死=事实上的裁定；缺 panel 未致视觉缺（两档够用） | 公共段阴影键集合恰={--mica-shadow,--mica-shadow-soft}；如升三级先改本行 | 本表 0919 首登（前零记载，X 项收编） | 三级面裁定+改测时行删 |
| E-13 | 存量展示级字号（26/23/22/17px 等）不受 TYPE_SCALE 追溯 | 各卡 | 实弹验收过的构图不因换档回溯（契约 §四原句） | TYPE_SCALE 仅约束新/改版选值（声明级，见 D-1 补门建议）；存量白名单=样张基线 19 面 | 0912 契约原句 | 无（永久条款） |
| E-14 | media 卡不传 viewport（吃后端缺省 640×400 / 672×480 两套） | templates.py 出卡路 + render_backends 两缺省 | 现状如此、640 档贴边有裁阴影风险但未被证实出过坏图（禁渲染未证） | F14-10 收口（viewport 登记表+统一缺省常量）前：改后端缺省须同步本行 | 本表 0919 首登 | emitter/viewport 登记落地时行删 |

**待补门登记（「纸面条款」四条的 D 系列，配 4.3 各稿引用）**：D-1 直拼卡 keyframes 名门（builders 加 @keyframes 名集断言，推荐补——一测即得）；D-2 遮罩面扫门（4.3-6 方案）；D-3 usage `.status.*` 改 var() 消费（一行）；D-4 `--text-sub/--text-secondary` 双 token 并轨（先裁值）；D-5 echo 12.5/14.5 改值或 C8 口径加注；D-6 宽度查表收口（含 mica_shell 缺省并表）；D-7 卡骨架契约（F14-12 建议集）；D-8 样张基线入库+钉帧观测（S8-05/F5-5/6）。

---

## 六、旧审计（audit-20260919-unify-wave.md）需回写订正清单（12 条；本席不改旧文）

| 旧条目 | 本批改判 | 现势证据（本席/席位实测） |
|---|---|---|
| P0-1 日历炸弹 | 已被在飞修复波收掉，**状态应改「已解除」** | `test_webui_http.py:55-61` 动态种子+注释自证；F4（6 passed）/F13（64 passed）/本席核其字面量全树唯一残存= `test_webui_stats.py:596` 夹具非窗筛（非炸弹） |
| P0-2 web_search 地雷 | **按方案 B 解决**（垫片不再需要），状态应改「已解除（B 案）」 | `capability_protocols.py:1128` 现 import `domains.core.search import web_search`（行号自 1273 漂移）；旧路径文件不存在=零引用残留（旧文 §2 P0-2 收尾判据成立） |
| P0-3 提交漂移 | 维持 P0 未动 + **升级面补记**：整个 `webui/` 从未入 git（`git ls-files webui/`=0，F10-01；本席不重跑 git 写类命令） | F10 §三实跑 + F4 N1 |
| P1-1 行高塌陷 | 状态应改「已落地待裁」+ **根因纠正**：主因非「Tailwind 同层拼顺序」单解，而是 **tailwind-merge 对自定义 `@utility`（fs-*）失明→cn() 无法折叠基类 leading-none**（twMerge v3 顶层 classGroups 被 mergeConfigs 丢弃/组名错不报错=静默失效） | `webui/src/components/ui/card.tsx:34` 现值 `cn('font-semibold', className)`（本席实读）；`tests/test_webui_constitution.py::test_cn_merges_type_ladder_classes` 行为锁（17:12 落地，docstring 自述根因）；F4 层叠表对 16:2x dist 仍真（时序注） |
| P1-2 三门游离 | 状态应改「已常驻（17:12）」且**方案换轨**：旧文 skipif 草案被 F4 裁定否决（缺 node=FAIL 不 skip），落地形态=F18 §2 | `tests/test_webui_constitution.py` 在案；`webui/package.json` scripts 已含 test/check（本席实读） |
| P1-3 宪法门四缺 | 四缺复验成立；两处文字订正：①「同文件双标」坐标错——「内联白名单 #1」在 memory-graph.tsx:182，canvas 字体在 memory-canvas.tsx:179；②「height:480 标了白名单所以双标」的暗示不成立（门不扫内联尺寸，白名单是道德约束）——S8 已给完整改判 | S8 §一 P1-3 行 + 本席核两文件 |
| P1-4 logs 重放重复行 | **仍在**（17:2x 未动），维持待执行 | F12 未列（非其域）；S8 :77-88/:165-173 无去重复验在案 |
| P2-9 dev 代理缺 /admin | **已补**（vite.config.ts:23 现含 `/admin/api/v1`）；但**旧文改法文本自身带新坑**：其建议 `process.env.VITE_API_BASE_URL` 读不到 .env（loadEnv 才通，F10-05 双通道暗坑）——回写时须把改法换成 loadEnv 版 | 本席 grep vite.config.ts + F10-05 |
| P2-10 五处控件漏 fs-* | **拆分改判**：4 处仍在（settings-dialog:106/:127、knowledge:205、memory-graph:144）；**logs.tsx:249/:261 两 select 系误读**（现值本就 `h-8 … fs-caption`，文件 mtime 早于审计自陈复核时刻——报告所述形态从未存在）；「后果=浏览器默认 16px」夸大（preflight font:inherit+父级 fs-body 路径） | S8 核销表 P2-10 行 + F12 九页实测（本席抽验 knowledge:205 无 fs- 在位） |
| P2-11 `?? 0` 造数 | **已解除**（dashboard.tsx `grep "?? 0"`=0，本席实跑；F9 快照同证） | 上左 |
| P2-18 tts mypy | **已解除**（tts.py:328-330 现用 `error_body` 新变量名，本席实读） | 上左 |
| P3-20/21 | P3-21 **已解除**（package.json test/check 在位，且被常驻门第 4 用例锁住双入口不漂移）；P3-20 **仍在**（logs.tsx 两条死 eslint-disable 注释，F10-10 16:3x 复验，本席未重跑） | 本席读 package.json + F10 §四 |
| §1 门禁实测表 | 回写时加注：「3 failed」为 12:47–14:22 时点账，其后至 17:2x 修复波陆续落地（P0-1/P0-2/P2-11/P2-18 等），**全量当前态需重跑方能记账**（本席禁全量，不背书现值） | 时间线=各席 date 戳 |

**旧文 §3 核验通过清单两条加注**：#1「模板内 @keyframes 手抄副本清零」域限定于装饰层成立，壳层手抄另账（D-S13）；#4「九门…非玩具门」总评成立，但「禁表外 hex」一名应改判（F5-1/S8-01 半无牙）——与本表 X 系列不重复计。

---

## 七、真相源收口建议（用户任务⑥）

**分账原则**：一个事实只在一处「登记」，其余位置只准出现「指针」。

| 承载物 | 唯一承载 | 例 |
|---|---|---|
| `docs/auto-facts.md`（机器册，--check 常驻） | 一切**可生成计数**：模板清单/RouteKind/topics/测试文件数/config 字段数/哈希清单项数 | 禁再手抄进任何文档 |
| `theme_tokens.py`+`mica_shell.py`（代码） | 一切**值**：色/阴影/玻璃/遮罩/语义色/半径/间距/行高/字号档/宽度表/色斑 | 文档引用值须注「以值册为准」 |
| `docs/rendering-contract.md`（哈希件） | 卡片/渲染**规范句 + 每条执法面 + §八豁免册**（本文件 4.3 全部稿并入后升格为前端渲染唯一规范正文） | 其他文档谈渲染只给指针 |
| `DESIGN-SPEC.md`（哈希件） | 三规范**方法论**（值册-投影-机器门三层、判例句 L53、执行动作） | 不再复制值清单/计数 |
| `docs/HANDBOOK.md` | **波次史**（带日期时点的账，含 §32/§33）；§6「当前状态」章要么删要么改「现势快照统一指向 contract+机器册」 | 「已完成」必带实跑指针 |
| `AGENTS.md` | 30 秒身份 + 硬约束 + **指针**；所有可数名词改「见机器册/契约」 | 529 之类数字从此绝迹 |
| `webui/src` 各真身（index.css/router/api-client…）+ `layout-constitution.mjs` | WebUI 版式档位/端点面/路由清单 | 前端设计文档只写「为什么」，现状以代码+门输出为准 |
| `docs/design/unify-audit-20260919/*` | **时点审计证据**，非事实源；结论被引用处回写主文档后原样封存 | 防「审计文档当规范用」 |

**现存的重复登记热点（=本次漂移事故源，收成一行/处+余改指针）**：①阴影枚数 5 处（AGENTS、contract×2、DESIGN-SPEC、market 头注释、mica_shell 头注）→ 1 处值册+契约；②模板/面数 4 处；③真身路径 5 处；④「常驻门清单」3 处（AGENTS 五、DESIGN-SPEC 三、HANDBOOK §32.7）→ 留 HANDBOOK 单点+grep 判据；⑤宽度值 3 处（表/调用实参/测试断言，F14-5「三写」）→ 收编查表一处；⑥UIACC 结果 2 处（AGENTS #41/HANDBOOK §32.2）；⑦SETTABLE 2 处（AGENTS #34/dashboard-spec）+代码真身；⑧TYPE_SCALE 3 处（值册/契约/§32.5 诚实缺口）——订正稿全部按「值一处、文一指针」落。

---

## 八、复跑命令（本席取证主命令，只读零副作用）

```bash
date                                                              # → Sat Sep 19 17:05:14 2026
ls plugins/bot_unified_runtime/domains/render/card_render/templates/*.html | wc -l          # 7
head -1 plugins/bot_unified_runtime/output/card_render/theme_tokens.py                        # Compat shim…
grep -c '"' <(sed -n '34,60p' tests/verify_hashes.py) 手动核 = 19 项（TRACKED_FILES 段亲读）
grep -n "CARD_TEMPLATES" -A9 tests/test_rendering_contract.py | head                          # 7 模板枚举
grep -n "def test_" tests/test_e03_typography.py | tail -1                                    # no_new_keyframes 仅 .html 面
grep -rn "TYPE_SCALE" tests/                                                                  # 0 消费者（纯纸面实证）
grep -rn "OVERLAY_SCRIMS\|scrim" tests/test_v21r3_visual_gates.py tests/test_template_visual_audit.py  # 0（遮罩纸面实证）
sed -n '363,372p;560,572p' tests/test_v21r3_visual_gates.py                                   # gate08 黑名单+白名单中和
grep -c "145deg" plugins/.../templates/*.html .../mica_shell.py                               # 模板 10 份+生成器 1 份
grep -n "width_px=" plugins/bot_unified_runtime/domains/ | grep -v mica_shell.py              # 4 处字面量
grep -n "12.5px\|14.5px" plugins/.../domains/chat_reply/capabilities/echo.py                  # 3392/3409 现势在位
grep -n -- "--text-secondary: #576272" plugins/.../templates/*.html                           # 7/7 手抄
sed -n '255,257p' plugins/bot_unified_runtime/domains/render/card_render/usage_cards.py       # 语义三色直写现势
grep -c Math.random plugins/.../templates/*.html | grep -v ':0'                               # 空（E01 换代实证）
grep -n "windowToday\|speakerCount" webui/src/locales/zh-CN/common.json                       # L-2/L-8 时点仍在（17:2x）
sed -n '228,232p' webui/src/index.css                                                          # 五档真值 12/13/14/18/30
grep -n "mock" webui/src/pages/dashboard.tsx                                                   # 0 命中
grep -rn "SETTABLE_KEYS" plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py   # 真身 :454；import 实数 41/31
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'.');from plugins.bot_unified_runtime.domains.chat_reply.runtime.settings import SETTABLE_KEYS,RESTART_REQUIRED_KEYS as R;print(len(SETTABLE_KEYS),len(R))"
# 本文判词统计（对 §一 总表判定列）：
grep -o "| 相符" F24-doc-reconciliation.md | wc -l; grep -o "夸大" F24-doc-reconciliation.md | wc -l 等（详见文内数字自核）
```

**树卫生自证**：本席全程未直跑裸解释器（唯一 python 调用带三件套+venv）；未新建除本文件外任何文件；`git status --porcelain` 增量应仅本文件一行。

**总表自核计数（落笔后 `grep -o` 于 §一 各表判定列实测）**：相符 **31** ｜ 夸大 **15** ｜ 过时 **31** ｜ 纯纸面 **4** ｜ 矛盾 **8** ｜ 合计 **89**。若与他席口径冲突，以本表逐行为准、他处汇总句作废。
