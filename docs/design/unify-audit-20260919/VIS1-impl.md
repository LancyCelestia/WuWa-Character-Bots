# VIS1 — 卡片渲染视觉整改实施日志（2026-09-20）

Status: DONE

> 真身路径：`plugins/bot_unified_runtime/domains/render/card_render/`（下文简写 `card_render/`；`output/card_render/` 为 compat shim，不动）。
> 需求源=用户 2026-09-20 六条裁定（统一 R 角 / 背景多色交织+不透明度调高 / 01·02 排版基准+06 不透明度基准 / mermaid 节点全圆角 / 15_help 两列登记待接入 / 不得破坏品牌胶囊）。
> 落盘纪律：每完成一族立刻 append 一节。

## 0. 取证清单（铁律摘录，2026-09-20 实读 DESIGN-SPEC.md v2 + docs/rendering-contract.md）

有牙铁律（本席必须守住，逐条对应执法测试）：
1. 无 `<meta viewport>`（契约 §一.1，test_rendering_contract 逐条）。
2. body 透明（§一.2，契约族 + builders）。
3. 字重 ≤700（§一.3，数值比较；命名值 `bold` 旁路已登记）。
4. 动画元素必须在 `.card` 子树内（§一.4；mermaid/universal 伪元素双斑=登记特例 E-2/E-3）。
5. 光晕 alpha≥0.05（§一.5；rgba 与 color-mix 对 transparent 两式均扫，**下限 0.05/5%，调高永远安全**）。
6. 阴影只准 `SHADOW_CSS_VARS` 登记族（族外/inset 一票否决；直拼卡公共段恰两级=E-12 钉死）。
7. 渲染失败→纯文本兜底零破坏；`--accent` 永不作大面积底色；平台色仅两层=accent 与 `--wash-blob-1`（混入 ≤35%，`test_pc_never_paints_brand_base` 数值锁：正则只锁 `--wash-blob-1` 定义行内 `var(--accent) N%` 的 N≤35——**本席不动 wash_blob_mix 参数（35/24），只把 --wash-blob-1 作为渐变色标消费，等效 accent 覆盖=0.35×混入比≤35%，语义不变**）。
8. 色斑恒 3 枚、时长集合恰 {46,52,58}s（gate02；**色标 alpha 无数值锁**）。
9. 行高刻度、字号下限 12px、gap 刻度、宽度登记表、font-family 两栈逐字、禁表外 hex 黑名单、白玻璃两档 (0.66,0.44)/(0.66,0.46)+描边 {0.95,0.35,0.72}（gate09，**纯白 rgba 层才判层；含 color-mix()/var() 的染色层与 token 消费放行**）。
10. 半径：外壳只 `var(--r-shell)`=30；面板/瓦片 `--r-panel`=18/`--r-tile`=14；内径合法集 {4,6,8,12,16}+pill 999+圆 50%+0/inherit/var()；私设 `--radius-*` 禁止（gate01）。**三档族不扩，本席不新造档位**。
11. 值册唯一 + 改值只改值册 + 新视觉先入册再引用（DESIGN-SPEC §一.11 v21r3 立法）。壳层 145deg 渐变与 150deg 描边=面上手抄（模板 10 份+生成器 1 份），「收口=上下文键/值册注入」在案（F5-2/S8-03/E-7）——本席落此收口。
12. **逐字符锁死、不可动的登记值**（改=触既有断言红线）：GLASS_MAIN/GLASS_FOOT/GLASS_EDGE（test_core_registry_glass_tiers_exact + gate09 双锁）、语义五色、遮罩四员、`test_shell_base_css_carries_visual_shell` 锁 shell_base_css 必须含字面量 `linear-gradient(145deg, var(--wash-mist) 0%`（→ 生成器保持字面内插、不走 var() 消费）、`test_pc_never_paints_brand_base` 锁每面 CSS 含 `linear-gradient(145deg,` + `var(--wash-mist)`（→ 新壳渐变的**首个色标必须保持** `var(--wash-mist) 0%` 起始；模板改 var() 消费后该串经 `--mica-shell-wash` 注入 :root 仍在渲染产物里命中）。
13. 供给链六门动态（引用⊆并集、注入键落地、无固定计数锁）→ 新增公共 token 进 `_PUBLIC_TOKEN_ORDER` 安全；`test_public_token_subset_and_order_unified` 从 mica_shell 动态读序 → 尾部追加自动一致。
14. 胶囊（CAP1）：`brand_capsule_css/html` 只用 --r-pill/--r-circle/GLASS_FOOT/GLASS_EDGE/glow/shadow-soft token——本席改壳背景与半径**不触碰 capsule 段**；壳渐变 token 化后胶囊随 GLASS_FOOT var 消费零变化。

## 1. 三面背景参数对照表（所有数值改动之依据）

取证口径：`card_width`/排版基准面 = `01_universal_bilibili_video`、`02_universal_bilibili_bgv`（universal_card.html）；不透明度基准 = `06_market_commodities`（finance_card.html，商品/国债/北向三形态共用）。其余「太单一」判定面=全部 11 面共用同一壳渐变的卡面。

| 面 | 背景层 | 色标 | 色数 | 各自 alpha/混入 | 混合模式 | 尺寸 |
|---|---|---|---|---|---|---|
| 06 finance（不透明度基准） | 壳 `.shell` L1 | 145deg：mist@0 / w1@30 / w2@64 / w3@100，逐标 color-mix 入 mist | 4 | 55% / 48% / 40%（wash 对 mist 混入比；操作数皆不透明 hex→整层不透明） | normal，padding-box | 1080px 壳满铺 |
| 06 finance | 壳 L2 描边 | 150deg 白 .95/.35/.72 | 1(白) | 0.95/0.35/0.72 | border-box | 1px 边 |
| 06 finance | 装饰色斑 ×3 | radial：blob-1(a) 50/28/6%、w-2(b) 30/16/5%、w-3(c) 26/14/5%（对 transparent） | 3 色 | 峰值 50/30/26% | closest-side 渐隐 | 58%/52%/64% 宽 |
| 06 finance | 瓦片 `.index/.row` | 白玻璃 0.66→0.44 + EDGE 描边；zebra 覆内联 `var(--surface-a/b)`+EDGE 手抄 | — | GLASS_MAIN 档 | padding/border-box | 网格瓦片 |
| 01/02 universal（排版基准） | `.card`（非 video 直出） | 同上 4 标 145deg | 4 | 55/48/40 | normal | payload 宽 |
| 01/02 universal | `.video-card-shell` | 同 4 标 + 托底 `linear-gradient(145deg,#f7f4fa→#eef0f9)` | 4+2 | 同上；托底不透明 | 首层已全不透明→托底实际被遮蔽（vis2r 深色窗保险层，保留） | 双栏宽版 |
| 01/02 universal | `.mica-surface` 面板 | 145deg 染色：accent 10%→白 .82 / w2 9%→白 .64 / accent 7%→白 .84 | 3 | 白基底 .82/.64/.84 | 染色层（gate09 放行族） | 面板 |
| 01/02 universal | 伪元素双斑+DOM 第3斑（E-3 混合体） | a/b 伪元素+ c DOM 斑 | 3 | 50/28/6、30/16/5（与生成器同构手抄） | radial 渐隐 | 58%/52%/64% |
| 其余面（market/affinity/song/mermaid/error/4 直拼卡） | 壳 | **与 06 逐字符同**（145deg 4 标 55/48/40 + 150deg EDGE），共 10 份模板手抄 + 生成器 1 份 | 4 | 同上 | — | 各壳宽 |

**判定**：①「颜色单一」根因=11 面共用同一 4 色标单调渐层（mist→w1→w2→w3 单向滑行、无交织回绕），且 universal 另有大面积 `.mica-surface` 高白面板压色；②「不透明度」在壳层语义=color-mix 混入比（混入比越高→离雾底越远、色越实），06 认可档=55/48/40；③全 11 面壳层参数**本就一致**，差异全在装饰色斑 alpha 与覆盖密度——故整改=统一升格「生成器+值册」单源，一次改值 11 面同动。

**新壳渐变（登记值 `SHELL_WASH_GRADIENT`，多色交织+混入比按 06 档整体上浮 ~1.2–1.3×）**：
145deg：`var(--wash-mist) 0%` → `--wash-blob-1 62%`@16 → `--wash-1 72%`@34 → `--wash-2 62%`@52 → `--wash-3 55%`@70 → `--wash-2 60%`@86 → `--wash-1 70%`@100（色标 4→7、色相 3→4 系含平台色混入斑、回绕交织；首标保持 mist 打底锁 12 条款⑫；blob-1 等效 accent 覆盖 0.35×0.62≈21.7% ≤35%）。
色斑 alpha 同步调高：a 50/28/6→60/38/10、b 30/16/5→38/22/8、c 26/14/5→34/20/8（全 ≥5% 光晕下限）。
**观感声明（如实）**：原「色斑≤35%」条款锁的是 `--wash-blob-1` 定义内的 accent 混入比（数值锁正则只读该定义行），本席未动 35/24 参数；壳渐变把 blob-1 当第 4 色相消费使**局部**wash 浓度上浮，叠加色斑 alpha 调高后全卡背景彩度显著高于原设计——依据数即 06 档混入比×上浮系数（55→72≈1.31），非新增执法数值。白玻璃两档（0.66/0.44/0.46）被逐字符锁死，**不属本席可调面**——如用户要玻璃层也提不透明度，属改锁定断言，列待裁 §5。

## 2. 半径统一档位判定

- 三档族 30/18/14 + 内径合法集 {4,6,8,12,16} + pill/圆 = 既有档位，**不扩族、不新造档**（gate1 半径门保持绿）。
- 「统一」落法=**同角色同 token、字面量全收敛 var() 消费**（token 已随 render_root_tokens 公共段注入全 11 面）：
  - 外壳 → `var(--r-shell)`（7 模板已在位，复核确认）；
  - 面板级容器 → `var(--r-panel)`；瓦片/行级 → `var(--r-tile)`（跨面已一致，维持）;
  - 徽章/胶囊/标签 → `var(--r-pill)`（含 universal `.handle-tag/.id-tag/.profile_tags` 等 chip 族由 12px/`var(--r-panel)` **收编为 pill**——此为唯一的角色级改值，动因=同角色跨面/跨区块不一致的用户原话裁定）；
  - 头像/圆点 → `var(--r-circle)`；
  - 其余内径小件（媒体角标、缩略图、标记条等）→ `var(--r-inner-xs/sm/md/lg/xl)` 等值换 token（12px→`var(--r-inner-lg)` 等，**像素零漂移**）。
- 排查记录：七模板无 `--radius-lg/md/sm` 私设残留（已废）；`border-radius: inherit/0` 复位面保留。

## 3. 施工记录

### 3.2 背景多色交织 + 不透明度调高 —— 已完成（实跑 496 passed/0 failed）

裁定：排版基准 01/02 的结构/字号/栅格零触碰；不透明度=壳层釉瑚渐变的 wash 混入比（06 档 55/48/40 为锚，上浮 ~1.2–1.3× 至 55–72 区间，色标 4→7、色相 3→4——`--wash-blob-1` 平台混入色作为第 4 交织色相消费，等效 accent 覆盖 0.35×0.62≈21.7%≤35% 数值锁不动，`--accent` 本体仍永不入底色）。

| 改动 | 落点 |
|---|---|
| 新登记值 `SHELL_WASH_GRADIENT`（7 色标回绕交织渐变，首标保持 `linear-gradient(145deg, var(--wash-mist) 0%` 双锁形态） | `theme_tokens.py`（新增段+`__all__`+`theme_to_css_vars` 注入 `--mica-shell-wash`） |
| 公共段追加 `--mica-shell-wash`（表尾，动态序一致）；`shell_base_css` 145deg/150deg 手抄改内插登记常量（直拼 4 卡自动跟随）；色斑 `_BLOB_SPECS` stop 上浮 a 50/28/6→60/38/10、b 30/16/5→38/22/8、c 26/14/5→34/20/8（全 ≥5% 光晕下限） | `mica_shell.py` |
| 7 模板 `.shell/.card/.panel` 背景块改 `var(--mica-shell-wash) padding-box, var(--mica-glass-edge)`（模板侧 145deg 色标手抄 9 处退役，DESIGN-SPEC §一.11 壳层收口 F5-2 落地）；universal `.video-card-shell` 同法+不透明托底保留；E-2/E-3 伪元素斑同步等值（mermaid×2、universal×3 段） | `templates/*.html` |
| zebra 行内联 150deg 描边手抄（affinity 10、song 2、universal 3、market 2、finance 2 处）改 `var(--mica-glass-edge)` 消费；universal `.video-metric-card/.video-card-summary/.video-topbar` 区段 + `.footer` 档改 `var(--mica-glass-main/-foot)` 消费 | 同上 |

**回滚件（如实）**：market `.index`/finance `.row`/affinity `.glass`/song `.glass`/error `.row(.alt)` 六处瓦片规则的白玻璃双背景字面量先改 var() 消费后**还原**——`tests/test_template_visual_audit.py::test_list_tiles_keep_glass_surface`（非本席可写件）按规则体**字面含 padding-box+border-box** 断言，var() 消费必红；该族瓦片维持登记值等值字面（gate09 白名单放行），瓦片面收口需先改审计门取相（列 §5 待裁）。

**测试**：`tests/test_rendering_contract.py + test_mica_builders_contract.py + test_v21r3_visual_gates.py + test_token_supply_chain.py + test_template_visual_audit.py + test_mica_shell.py + test_e03_typography.py + test_phase_determinism{,_2}.py + test_error_card_contract.py` 合跑 **496 passed / 0 failed**（`--basetemp=$TEMP/vis1b -p no:cacheprovider` 三件套）。既有断言零放宽零删除（本席未改任何测试文件）。

### 3.1 圆角统一 —— 已完成（实跑 496 passed/0 failed，与 3.2 合跑）

落点=既有档位收敛，**未扩族**（--r-shell 30/--r-panel 18/--r-tile 14 + 内径 {4,6,8,12,16}→`--r-inner-xs..xl` + pill/圆，全部经 render_root_tokens 公共段注入，模板侧零新值）：
- 七张模板 border-radius 硬编码字面量 **55 处**全量收敛为 `var()` 消费（universal 41/song 3/affinity 5/market 1/finance 2/error 2/mermaid 1；含 `<style>` 规则与内联 `style=""` 两处形态；`0`/`inherit` 复位保留）；像素等值迁移，唯二改值见下条。
- 角色统一（用户「不同位置半径不一致」原话的像素面）：universal `.uid-tag/.handle-tag/.id-tag`（12px→`var(--r-pill)`，与本卡 `.topic-chip`、全卡徽章族对齐）；universal 画像标签内联 `var(--r-panel)`→`var(--r-pill)`（标签=胶囊角色）。
- 自查：`grep border-radius templates/*.html | grep -v var() | grep -v inherit | grep -v '0'` = **0 残余**；模板无新增硬编码 hex/px 半径/alpha。
- 胶囊组件零触碰（`brand_capsule_*` 本就全 var() 消费）。

### 3.3 mermaid 节点圆角（待做）

### 3.3 mermaid 节点圆角 —— 已完成（合跑 496 passed/0 failed + 生产路径实渲取证）

取证（探针 `%TEMP%/vis1b/probe_mermaid.py` 四变体，本地 mermaid.min.js 内联、离线）：
- 通道判定=mermaid@11 default 主题输出 DOM：矩形节点 `<rect class="basic label-container">`（无 rx 属性）、菱形/平行四边形/六边形 `<polygon class="label-container" transform="translate(…)">`、圆端/圆为 path/ellipse（本已圆滑）、箭头 marker 亦 polygon（在 defs，禁扫）。
- **themeVariables.borderRadius 实测零作用**（v1 与 v0 DOM 逐字节同）；classDef 无圆角落点 → 最小改动两条：
  1. CSS：`.card .mermaid .node rect { rx: var(--r-inner-lg); ry: var(--r-inner-lg); }`（Chromium SVG2 几何属性走 CSS，实测 cssRx=12px 生效；消费内径档 12px，不新造档）；
  2. 页尾脚本：渲染完成后把 `.node polygon` 以同坐标替换为圆角 `<path>`（每角 min(12, 0.3×邻边) 收角+二次贝塞尔；**复制全部属性含 transform**——探针实锤漏拷 transform=形状平移）；MutationObserver 等首帧，fail-open。
- 生产路径验证：`bridge.render_mermaid_png`（page.route 本地素材拦截原链）出图 `%TEMP%/vis1b/mermaid-probe/prod_render.png`——矩形/菱形/平行四边形/六边形全圆角、连线箭头文字零改动、品牌胶囊完好。
- 落点=`templates/mermaid_card.html`（CSS 一段+script 一段+头注记）；「SVG 图形内部零触碰」旧例对本裁定开例已在契约 §六/头注登记。

### 3.4 15_help_index 两列 —— 待接入项（本席禁动 echo.py，坐标如下）

现状取证（只读，2026-09-20 本席实查 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py`）：
- 正身函数=`_help_mica_html`（:3279 起）；外层已是 2 栏瀑布流 `.help-grid.masonry { column-count:2 }`（:3413，6a8dcf6 旧批已落）；
- **用户所见「四列」真因**=分区内 `.command-list { display:block; columns:2 }`（:3420）把行再切两栏 → 2×2=视觉四栏；`@media (max-width:559px)` 退回单栏对（:3439-3440）；
- 配套防溢出 `.command-row .desc { -webkit-line-clamp:2 }`（:3424）是按 211px 窄栏调的，改两栏后栏宽≈450px，钳行可放宽。

施工坐标（接手席执行，行号以当时实况为准——该文件多席高频改）：
1. `echo.py:3420` `.help-grid.masonry .command-list` 的 `columns:2` → `columns:1`（或直接删该属性、保留 `display:block`→`grid` 回单列）；:3439-3440 媒体查询里对应 `columns:1` 行同步清理；
2. :3424 `.desc` line-clamp 复核（栏宽翻倍后 2 行钳制大概率多余，目验样张定）；
3. 改后必跑：`tests/test_mica_builders_contract.py` + `test_v21r3_visual_gates.py[echo_help]` + `test_rendering_contract.py`；`verify_hashes` 会红（echo.py 在清单内，由收尾席统一 `--write`，改者禁自录）；
4. 样张目验：`python scripts/render_card_samples.py --only help --out %TEMP%/…`；
5. 本席拿不到的东西=该文件后续在飞 diff 与样张目验结论，故只交坐标不执行。
胶囊/壳背景零改动（echo 卡壳经 `shell_base_css` 自动跟随本波新背景）。

## 4. 契约测试实跑记录

命令（零缓存三件套，basetemp 落仓库外）：
`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py tests/test_v21r3_visual_gates.py -p no:cacheprovider --basetemp="$TEMP/vis1b" -q`

| 时点 | 范围 | 结果 |
|---|---|---|
| 背景族完成后 | 简报三件 + 邻族共 10 文件（+token_supply_chain/template_visual_audit/mica_shell/e03/phase_determinism×2/error_card_contract） | **496 passed / 0 failed** |
| 中途一次 | 同上 | 5 failed（=瓦片玻璃 var() 收口触 `test_list_tiles_keep_glass_surface` 字面取相，**非放宽测试而是回滚六处生产字面**）→ 修复后复跑归零 |
| 半径族完成后 | 同上 10 文件 | **496 passed / 0 failed** |
| mermaid 族完成后 | 同上 10 文件 | **496 passed / 0 failed** |
| 终跑（简报三件） | test_rendering_contract + test_mica_builders_contract + test_v21r3_visual_gates | **289 passed / 0 failed** |
| 生产路径实渲 | `bridge.render_mermaid_png`（page.route 本地 mermaid 素材）→ %TEMP PNG + `scripts/render_card_samples.py --out $TEMP/vis1b-shot` 19 面 | 见 §7 样张记录 |

**断言自证（红线）**：本席**未修改任何测试文件、未放宽/删除任何既有断言**——可写三测试件（rendering_contract/mica_builders/v21r3_visual_gates）零改动；`test_list_tiles_keep_glass_surface` 触红时的处置=还原生产侧字面量（见 D-9），不是改门。全部改动仅落在：theme_tokens.py / mica_shell.py / templates/*.html（7 张）/ docs（本日志+rendering-contract+DESIGN-SPEC）。bridge.py 与 domains/render/templates.py 实际零改动（壳背景经 root_tokens 公共段与 shell_base_css 自动跟随）。

## 5. 待用户裁的点

1. **白玻璃两档不透明度**：用户「所有背景不透明度全部调高」的字面若覆盖 `.glass` 面板层（0.66→0.44/0.46），需改 `test_core_registry_glass_tiers_exact` 逐字符锁 + gate09 `_GLASS_FILL_TIERS` 常量——属修改既有断言，本席红线不动，列此待裁（壳背景与色斑层已按裁定上浮，不受此限）。
2. **D-9 瓦片玻璃 var() 收口**：需先把 `test_template_visual_audit` 取相改合法化（改门=断言语义变更）再迁移六处字面，或永久保留等值字面（现态）。
3. **15_help_index 两列**：真因=分区内 `columns:2` 叠乘外层两栏（§3.4），施工在 echo.py（他席在飞），坐标已交。
4. **样张基线换代**：本波 11 面 PNG 字节全变属预期；`verify_hashes --write` 与样张新基线重录归收尾席（本席双禁）。
5. **universal 高白面板遮蔽**：01/02 排版基准裁定下 `.mica-surface` 未动；若目验后仍觉背景色不够透，调该层（染色层，无逐字符锁）是下一刀。

## 6. 逐项落点速查（交回口径）

| 用户裁定 | 落点 |
|---|---|
| ①R 角统一 | `templates/*.html` 55 处字面量→`var(--r-*)`（既有档，零扩族）+ universal 标签族收编 pill；`theme_tokens.py` 档位不动 |
| ②背景多色交织+不透明度调高 | `theme_tokens.SHELL_WASH_GRADIENT`（新登记值）→ `--mica-shell-wash` 公共段（`mica_shell.render_root_tokens`）+ `shell_base_css` 内插 + 7 模板 var() 消费；色斑 alpha=`mica_shell._BLOB_SPECS`（+E-2/E-3 伪元素同构同步） |
| ③01/02 排版基准 / 06 不透明度基准 | 排版零触碰；06 档混入比 55/48/40 为锚上浮至 55–72 区间（对照表 §1） |
| ④mermaid 矩形/菱形圆角 | `templates/mermaid_card.html`：`.node rect` CSS rx（`var(--r-inner-lg)`）+ 页尾 polygon→圆角 path 脚本（复制全属性含 transform，fail-open） |
| ⑤15_help 两列 | 未动 echo.py，§3.4 精确坐标待接入 |
| ⑥胶囊不破坏 | `brand_capsule_*` 零接触；生产路径实渲样张胶囊完好（头像位/中文名/英文/功能名全在） |

## 7. 样张记录（可选步，已完成，零入树）

- `python scripts/render_card_samples.py --out %TEMP%/vis1b-shot` → **19/19 面 STABLE**（双渲 PNG 逐字节确定=新背景/新脚本未破钉帧确定性；manifest 19 卡全 deterministic）。
- 目验：01/02 排版零动、背景四相交织+混入比上浮可见；06 与全 11 面壳底同源；14_mermaid_flow 首跑暴露**竞态**——「svg 在场即断开观察器」漏掉后补的 polygon（菱形未圆角），改**常驻 MutationObserver+幂等转换**（已转形状是 path 不再命中，重复调用零副作用）后 `--only mermaid_flow --out %TEMP%/vis1b-shot2` 复跑：矩形/菱形全圆角、STABLE、胶囊完好。
- 基线重录（verify_hashes/样张 after 对比）=收尾席职责，本席双禁未执行。

## 8. 终态

Status: DONE（本席范围：①②③④⑥+⑤登记；断言零放宽零删除；改动面=theme_tokens.py/mica_shell.py/7 张模板/三份文档；bridge.py 与 domains/render/templates.py 实际零改动=公共段自动跟随；树卫生复查零 __pycache__/data/.pytest_cache）。
复跑命令（简报三件套）：见 §4——终跑 **289 passed**（三件）/ **496 passed**（含邻族 10 文件）。
