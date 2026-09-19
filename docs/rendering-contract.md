# 渲染契约（Card Rendering Contract）

> 适用于全部 **11 个渲染面**：7 张 Jinja 模板（`plugins/bot_unified_runtime/domains/render/card_render/templates/*.html`，error_card 为 2026-09-13 增）+4 处 f-string 直拼卡（`domains/chat_reply/capabilities/echo.py` `_help_mica_html`、`domains/ops/admin/debug.py` `_llm_setup_mica_html`、`domains/render/card_render/usage_cards.py`、`domains/render/templates.py`）。历史路径 `output/card_render/` 为 v21r2 兼容垫片（其 `templates/` 已空，垫片逐文件自述 "Compat shim: moved to domains/render/…"）。
> 单一事实来源：`theme_tokens.py`（守岸人品牌主题 + 平台受控变体 + shell 常量）。
> 契约的机器可执行形态：`tests/test_rendering_contract.py`（全离线，字符串/Jinja2/纯函数断言）。
> 任何 AI 或人，改模板前先读完本页。各条规则的执法面在下表「断言位置」列如实登记——**有牙条款**违反必红；**半牙条款**列明可绕形态；**纸面条款**当前是规范承诺、无机器拦截（收紧路线与豁免册见 §八「豁免登记与待补门」）。叙述与断言冲突时，以测试门禁的实际断言为准并回来改本文件（DESIGN-SPEC §三「诚实边界」总判例句，2026-09-20 F24/DOC1b 订正）。

## 一、铁律（所有模板，无例外）

| # | 规则 | 原因 / 实现要点 | 断言位置（2026-09-20 登记） |
|---|------|----------------|----------------|
| 1 | **无 `<meta viewport>`**（`META_VIEWPORT_POLICY = "forbidden"`） | 截图走 playwright `new_page(viewport=...)`，meta viewport 仅移动仿真生效，只会造成双宽度来源 | **有牙**：`test_rendering_contract.py` 逐条 |
| 2 | **body 透明**（`body { background: transparent; ... }`） | 截图 `omit_background=True` 依赖透明底出圆角卡 | **有牙**：契约族 + `test_mica_builders_contract.py`（直拼卡） |
| 3 | **字重 ≤ 700**（`FONT_WEIGHT_MAX = 700`） | 中文粗体渲染发糊，700 封顶 | **有牙**：字重数值比较；登记旁路=命名值 `bold` 形态不吃数值比较（F5 §5） |
| 4 | **动画元素必须在 `.card` 子树内** | 截图目标是 `.card`（`render_backends` 固定 `query_selector(".card")`）；色斑可走 `.card::before/::after` 伪元素或 `.card` 内 `.drift-blobs` 容器 | **有牙**：`.card` 子树断言；登记旁路=`body.xxx` 选择器形态（F5 §5） |
| 5 | **光晕 alpha ≥ 0.05** | 低于该阈值的柔光在生产裁剪后不可见却增加合成开销 | **有牙**：光晕 alpha 下限扫描；登记旁路=`rgb(0 0 0 / x%)` 新语法形态（F5 §5） |
| 6 | **阴影只准用登记族**（vis4 分级）：`theme_tokens.SHADOW_CSS_VARS` 为唯一登记处——`--mica-shadow`(L3 外壳) + `--mica-shadow-panel`(L2 面板大件) + `--mica-shadow-soft`(L1 瓦片小件)；`box-shadow` 只允许 `none` / `var()` 引用登记表成员，**禁止表外值（含 inset 内高光、光晕）**；契约/审计测试白名单从登记表动态派生，新增档位先入册再使用 | 统一投影体系 + 层次可辨；内高光语言由 1px 渐变描边（padding-box/border-box 双背景）承担，不走阴影 | **有牙**：契约族白名单从 `SHADOW_CSS_VARS` 动态派生、族外（含 inset）一票否决；直拼卡公共段恰两级为 `test_mica_builders_contract.py::test_exactly_two_shadow_token_definitions` 钉死的登记特例（§八 E-12，升三级待裁） |
| 7 | **渲染失败 → 纯文本兜底，契约零破坏** | 后端 `render_card` 失败返回 `None`；各能力收到 `None`/空 PNG 必须回退纯文本（如点歌候选列表、mermaid 代码块原样保留）；bridge 各 `render_*_html` 对 `None`/`{}` payload 不抛异常 | **有牙**：bridge 纯函数 None/{} 断言 + 各能力回退路径断言（`test_mica_shell.py` 邻族） |
| 8 | **色斑三枚门（v21r3 C2）**：全部 11 面（7 Jinja 模板 + 4 f-string 直拼卡）恒 3 枚 `.drift-blob`（drift-a/b/c），`animation` 时长集合恰 {46,52,58}s；keyframes 只允许 `mica-drift-a/b/c`；装饰层（DOM 斑/keyframes/reduced-motion 关停）由 `mica_shell._MICA_DECOR_CSS + DRIFT_BLOBS_HTML` 生成器单源产出、手抄禁止——伪元素侧两处登记特例仍为手写（§八 E-2/E-3）；error 卡 `wash_blob_mix=24` 为显式登记豁免 | 两枚/零枚卡与私调时长是 v21r3 审计实锤的漂移源 | **半牙**：数量/时长 gate02 覆盖 11 面，但要求 `animation: mica-drift-x Ns` **连写**形态——拆成 `animation-name:`+`animation-duration:` 即逃（已登记旁路）；keyframes 名门（`test_e03_typography.test_e03_no_new_keyframes`）只扫 7 张 Jinja 模板，4 直拼卡现仅靠生成器同源、无独立名断言（待补 §八 D-1） |
| 9 | **行高门（v21r3 C7）**：`line-height` 只允许刻度 {1.0, 1.1, 1.15, 1.2, 1.4, 1.5, 1.6}（`test_e03_typography._LINE_HEIGHT_SCALE`）；1.55/1.65 等散值禁止——11 面全量（含 error_card 与 4 张直拼卡）纳入枚举，脱刻度一票否决 | E03 门此前漏枚举 error/直拼卡，1.55/1.65 在门外通行 | **有牙**：gate03 全量枚举 11 面；登记旁路=`font: 13px/1.55` 简写漏格（S8-10，待补门） |

## 二、守岸人本命色（品牌基底，不可被平台色覆盖）

淡蓝 / 白 / 深蓝 / 少量星空紫。实现为釉瑚云母洗四 token（`theme_tokens.derive_wash_tokens`）：

| token | 色相锚点 | 用途 |
|-------|---------|------|
| `--wash-1` | 淡蓝 210°（可被平台色相 ±30° 内轻推，比例 0.5） | 主透色 |
| `--wash-2` | 星空紫 265°（固定） | 次透色 + 外壳投影染色 |
| `--wash-3` | 深蓝 228°（固定） | 第三色透底 |
| `--wash-mist` | 雾底淡蓝 214°（固定，明度 ≥94%） | 打底 |

- 外壳底色**只能**是 `theme_tokens.SHELL_WASH_GRADIENT` 这一条 145deg 多色交织渐变（VIS1 2026-09-20 用户裁定改版：色标 4→7、色相 3→4——wash-1/2/3 回绕交织 + `--wash-blob-1` 平台混入色作第 4 交织色相，混入比自 06 基准档 55/48/40 上浮至 55–72 区间=「不透明度全部调高」；首色标仍 `var(--wash-mist) 0%` 打底，`test_pc_never_paints_brand_base` 取相锁保持）；供给=渲染器 `--mica-shell-wash` 公共段注入（`mica_shell.render_root_tokens`/`theme_to_css_vars` 双路同源），7 张模板与 `shell_base_css` 直拼卡一律消费该单源，**模板侧 145deg 色标手抄副本=0**（原 10 份已收编；universal `.video-card-shell` 末层不透明托底与 `.mica-surface` 染色层非壳底、另计）。`--accent` 永远不做底色。
- 平台色只允许两层受控出场：accent（徽章/高亮/链接）与 `--wash-blob-1`（≤35% 混入主色斑）。
- 灰阶 / 未知平台推力归零 → 纯本命洗。公共段（含 `--wash-*` 四键）自 v21r3 步 5 起由 `mica_shell.render_root_tokens` **单一注入**，模板文件不再书写兜底字面量（现势 7 模板 `default('#…')` 实例数=0，2026-09-20 复核）。历史形态注：早期模板内联 `default('#d9e0e7')` 等兜底字面量须与 `DEFAULT_WASH_TOKENS = derive_wash_tokens('#607080')` 逐键一致——**如任何面重新出现该形态，契约测试仍按等值锁判红**（`test_rendering_contract.py` 退化断言在位；值随派生算法单一来源，勿手改）。

## 三、平台主题注册表 `PLATFORM_THEMES`

- 定义在 `theme_tokens.py`：每平台一条 `ThemeTokens`（accent / accent_dark / accent_light / wash 四 token / 统一布局 token / 展示名 / 别名）。
- **只收录代码中真实存在的平台 identifier**；别名（xhs→xiaohongshu、x→twitter、cpp→allcpp、ncm→netease）走 `THEME_ALIASES` 第二跳。
- 社交媒体（bilibili/小红书/抖音/微博/YouTube/Twitter·X/pixiv/LOFTER/AllCPP/Facebook/Instagram）与音乐平台（网易云/QQ 音乐/酷狗/酷我/Apple Music/Spotify）各自独立、accent 互不相同（可辨认）。
- 未知平台：`get_platform_theme(未知) → DEFAULT_THEME`（中性灰 `#607080`，安全 fallback，不臆造）。steam/epic 有 identifier 无登记色，同样落 DEFAULT_THEME。
- `bridge.py` 消费注册表派生 `PLATFORM_COLORS` / `PLATFORM_OFFICIAL_NAMES` / `_PLATFORM_FOOTER_LABELS`（历史导出名保持不变，`_derive_wash_tokens` 为 `derive_wash_tokens` 的兼容别名，echo/debug/usage_cards/templates 依赖它，勿删）。

## 四、统一 Shell 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `--r-shell` | `30px` | 外壳圆角（全卡一致，v21r3 C1：**只允许 `var(--r-shell)` 引用**，壳级字面量禁止） |
| `--r-panel` / `--r-tile` | `18px` / `14px` | 面板 / 瓦片圆角 |
| `RADIUS_INNER_PX` | `{4, 6, 8, 12, 16}` | 内径合法集（v21r3 C1）；pill=`999px`、圆=`50%`、无圆角=`0` 为登记特例；迁移映射 28→30、20/24→18、11→12；universal 私设 `--radius-lg/md/sm` 已废除 |
| 阴影 | `SHADOW_CSS_VARS`（= SHADOW_LEVELS 三级族） | 阴影档位的唯一登记处：shell/panel/tile 三级；模板内字面量必须与登记值逐字符一致（或引用 bridge 注入的同名上下文键） |
| 字体 | `FONT_FAMILY_STACK` | 全卡同栈；模板内硬编码（CSS 不能吃 HTML 转义），契约测试锁一致 |
| `MONO_FONT_STACK`（v21r3 C9） | `"Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace`（登记值逗号后**无空格**，引用以 `theme_tokens.py` 为准） | mono 单源；卡内一律消费公共注入键 `var(--font-mono)`（error_card 内局部别名 `--mono-family: var(--font-mono)` 系个例，新模板勿再自造别名）或生成器注入，裸 `Consolas,monospace` 等字面量禁止；mermaid JS `fontFamily` 与 `.source-badge` 类 sans 字面量必须与 `FONT_FAMILY_STACK` 逐字一致 |
| 玻璃 | `GLASS_MAIN` / `GLASS_FOOT`（v21r3 C3） | 两档白玻璃：MAIN `rgba(255,255,255,.66)→.44`（面板/行面）、FOOT `.66→.46`（页脚胶囊/脚带）；边缘描边 `0.95/0.35/0.72`；表外 alpha（0.68/0.55/0.60/0.50/0.52 等）禁止；着色 color-mix 层可叠加以保留色调 |
| 深色遮罩 | `OVERLAY_SCRIMS` 四员（v21r3 C5） | `scrim_badge` rgba(10,12,16,0.72) / `scrim_banner` rgba(15,18,24,0.10) / `scrim_code` rgba(28,30,38,0.94) / `scrim_media` rgba(38,46,56,0.75)（逐值以值册为准）；四员值与注入面有锁、**面扫暂无断言**——「表外深色遮罩禁止」为规范承诺，新增暗 rgba 当前不触任何门（债项 §八 D-2，`gate10_scrims` 补门设计见 F24 §四 4.3-6） |
| 语义色 | `SEMANTIC` 五色（v21r3 C4） | DANGER `#d54941` / SUCCESS `#2e9e6b` / WARNING `#b07d1a` / SCORE_HOT `#157347` / SCORE_COLD `#b42334`；finance/market `--up/--down`、usage/debug `good/bad`、affinity `--score-*` **应**经 `var()` 消费——执法现状如实登记：字面量直写**登记值**按等值放行（gate08 白名单=登记表动态派生），表外卡私色仅命中 8 员黑名单时拦截，其中 `#b07d1a/#157347/#b42334` 已被登记值白名单中和，**有效黑名单=#d64545/#1a9e6c/#555/#444/#999 五值**；「禁止卡私红绿黄字面量」的全称执法待 gate08 白名单化（F5-1/S8-01 方案在案，§八 D 系列）；universal amber 装饰族豁免（非语义色，§八 E-4）；活反例登记：`usage_cards.py` `.status.ok/warn/bad` 直写 `#2e9e6b/#b07d1a/#d54941`（2026-09-20 复核在位，改 var() 消费一行了结 §八 D-3） |
| 次级文字 | `TEXT_SECONDARY`（`#576272`，vis5） | 次级灰**目标态**=单一来源；现势=「值册 TEXT_SECONDARY(#576272) + 7 模板 :root 等值手抄（2026-09-20 复核 7/7 在位）+ `test_secondary_gray_single_source` 等值锁」——**改值册不会全卡自动同步**（手抄收敛前，「单一来源」指唯一合法值、不指注入路径）；另一缺口：公共注入段 `--text-sub`(#5b6069，BRAND_THEME.text_sub) 与此同语义**双 token 双值**并存，并轨先裁值（§八 D-4）；对三档 zebra 表面对比 ≥4.5:1（WCAG AA@12px）为**有牙**门 `test_template_visual_audit.py`；旧散值 #7a828c/#8a919b/#66727f/#7a8699 已收编（market/finance 已同步收编）；v21r3 C6：legacy 灰 #555/#444/#999 一并收编进 `--text-main`/`--text-secondary` 并入黑名单门 |
| 字号下限 | `12px` | UI 铁律；**有牙**：下限 ≥12px 机器门锁 11 面（`test_v21r3_visual_gates` gate04 + `test_mica_builders_contract.py`）；v21r3 C8 收口已在 7 张 Jinja 模板面落地（11/11.5/12.5px→12px、13.5/14.5px→14px），**echo 直拼卡现势仍存 12.5px/14.5px**（`echo.py` `_help_mica_html` 区段，下限门不咬、C8 口径对直拼卡未兑现，改值或改口径待裁 §八 D-5）；echo letter-spacing .14em→.06em、gap 9px→8px 已核实在位；`TYPE_SCALE_PX` 为新增/改版模板**选用**阶梯——纯声明、无机器门（tests 全树零消费者，「声明不接线」注见 HANDBOOK §32.5），既有卡实弹验收字号不受追溯（§八 E-13） |
| zebra 表面 | `SURFACE_TINTS` 三档 | vis5 数值门：onstage 相邻 ΔE(a,b)≥3.0、对 neutral ≥2.5；text_sub 对每档 ≥4.5:1 |
| 间距 | `GAP_SCALE_PX = {3,4,6,7,8,10,12,14,16}` | 模板 `gap` 只允许取刻度内值，禁止发明新间距 |
| 行高 | `{1.0, 1.1, 1.15, 1.2, 1.4, 1.5, 1.6}` | 契约铁律 9；v21r3 C7 收敛后直拼卡纳入枚举 |
| 色斑 | `BLOB_COUNT=3`、时长 `{46,52,58}s`（a/b/c） | 契约铁律 8（v21r3 C2）；装饰层单源 `mica_shell`；`WASH_BLOB_MIX` 默认 35、error 卡 24 豁免登记；**stop 混入比（VIS1 2026-09-20 用户裁定「背景不透明度调高」上浮）**：a 60/38/10、b 38/22/8、c 34/20/8（全 ≥5% 光晕下限），universal/mermaid 伪元素手抄斑同步等值（E-2/E-3「同构」语义保持） |
| 壳底渐变 | `SHELL_WASH_GRADIENT`（`--mica-shell-wash`，VIS1 2026-09-20 新增登记） | 145deg 七色标多色交织（mist 打底 + w1/w2/w3/blob-1 回绕），全 11 面壳底唯一来源；改版动因与数值依据=本册 §二 与 `docs/design/unify-audit-20260919/VIS1-impl.md` §1 对照表 |
| 宽度 | `CARD_SHELL_WIDTHS` | 宽度按内容族登记：universal 1440（payload `card_width` 驱动）/ affinity 1180 / market·finance 1080 / song_panel 980 / mermaid_max 840（fit-content 上限）/ error 1080；**v21r3 C10 增补直拼卡四键：help 940 / usage 900 / debug 880 / media 640**；新模板宽度必须先进本表；**执法现状**：4 张直拼卡宽度虽已入表，调用点现以字面量传 `width_px=`（echo 940/debug 880/usage 900/media 640，**不经查表、改表不跟随**，2026-09-20 复核在位），`mica_shell._DEFAULT_SHELL_WIDTH_PX=880` 为未登记第 12 缺省档——收口=实参改 `CARD_SHELL_WIDTHS[...]` + 缺省并表（§八 D-6）；universal 走 payload `card_width`+zoom 第三机制（F14-6.1） |

## 五、新增模板接入步骤（checklist）

1. 新卡**不复制任何 CSS 声明**：Jinja 卡以 `bridge._card_root_tokens(...) + **_vis4_context()`（`decor_css`/`blobs_html`/`shadow_elev_panel`/`divider_line` 等上下文键）为唯一起点（照 `finance_card.html` 的消费法）；f-string 卡经 `mica_shell.render_shell()/render_root_tokens/shell_base_css` 装配。公共 :root 段自步 5 起不在模板文件内书写——历史「复制 `market_card.html` 的 :root 结构」在现架构下**无处可抄**（该文件 :root 只剩卡特有键+注入位），且复制模板文件=复制手抄副本，与本波「值册单源」哲学相反。
2. 根元素**必须**带 `card` 类（截图选择器契约，`render_backends` 固定 query `.card`）。统一目标态（待裁+待迁）：全项目唯一装配式 = `render_shell()` 的 `<div class="card {stage}"><section class="{shell_class}">…</section></div>`（shell_class 空则单层）。**现势注记（2026-09-19 登记，非合规清单）**：存量并存 5 种根容器形态——`<div class="shell card">`（affinity/error/finance/market）、`<div class="card">`（mermaid/song）、`.card>.panel`（media 直拼）、`.card.mica-stage>.card>.video-card-shell`（universal 视频分支）、`.stage.card>section.shell`（echo/debug/usage）；本条历史文字「`shell card` 或 `card` 两种并列合规」**作废**（并列即放行分叉，F14-1），新卡禁用任何未在目标态出现的自造骨架，迁移逐面带截图基线执行。
3. 无 `<meta viewport>`；`body { background: transparent; }`；字重 ≤700。
4. 底色只用 wash 渐变；`--accent` 只做 accent；`--wash-blob-1` 混入 ≤35%。
5. 阴影只准 `none` / `var()` 引用 `SHADOW_CSS_VARS` 登记族**三员**（`--mica-shadow` 壳 / `--mica-shadow-panel` 面板 / `--mica-shadow-soft` 瓦片）；模板 :root 定义与登记值等值或经 bridge 上下文键注入（与铁律 6/§四同口径；本条旧「两枚 token 与 SHADOW_PRIMARY/SHADOW_SECONDARY 逐字符一致」措辞系 vis4 换代前遗留，作废——直拼卡两级面另按 §八 E-12 登记）。白玻璃只允许 GLASS_MAIN/GLASS_FOOT 两档 + 描边 0.95/0.35/0.72（v21r3 C3；染色层放行按 §八 E-5），深色遮罩应只用 OVERLAY 四员（C5，执法面见 §四该行）。
6. 动画元素全部放 `.card` 子树内；`@keyframes` 只允许 `mica-drift-a/b/c`；色斑恒 3 枚、时长集合恰 {46,52,58}s（铁律 8，v21r3 C2）；`prefers-reduced-motion`：`.drift-blob` DOM 色斑的关停规则由 `mica_shell._MICA_DECOR_CSS` 装饰层单源产出、模板不手写（C13）；**mermaid_card.html（::before/::after 双斑）与 universal_card.html（伪元素段）仍各存手写关停+手写伪元素 drift，属登记特例**（§八 E-2/E-3，随骨架迁移动态作废）。
7. gap 取自 `GAP_SCALE_PX`；行高取自铁律 9 刻度（C7）；内径取自 `RADIUS_INNER_PX` 合法集 {4,6,8,12,16}（pill=999px/圆=50% 特例，C1）；宽度先进 `CARD_SHELL_WIDTHS` 登记（含 help/usage/debug/media 四键，C10）并经 `shell_base_css` 消费——**现势四处调用仍传字面量不经查表（§八 D-6 待收口），新卡一律查表形态**。
8. 新平台先在 `theme_tokens._PLATFORM_ACCENTS` 登记（含展示名与别名），再在 `bridge._PLATFORM_LOGO_FILES`（可选）补图标。
9. 跑契约测试：

   ```bash
   PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_rendering_contract.py -q --basetemp="$TEMP/c1-contract" -p no:cacheprovider
   ```

10. 渲染失败路径（后端缺失/超时/异常 → `None`）必须由调用方回退纯文本；新增 `render_*_html` 对 `None`/`{}` payload 不抛异常。

## 六、payload 接线（bridge 层通用契约）

- `render_universal_card_html(payload)`：通用解析卡，接受 PlatformParse 投影 / 部分 RenderPayload 字典 / `None`；缺字段 → 对应区块整体隐藏，不抛异常（详见 bridge 模块 docstring）。
- `render_market_card_html(payload)`：股指卡（groups/rows/trend/trend_note/source_note/updated_at/delayed_note）。
- `render_finance_card_html(payload)`：股票/汇率金融卡（stocks/fx 共用壳；主题取 `BRAND_THEME` 本命基底）——属金融任务文件域，契约规则与本页一致。
- `render_affinity_card_html` / `render_song_candidates_html` / `render_mermaid_html`：各自能力域；同样遵守本页全部铁律。
- **好感度卡脏数据归一**（vis5 加固，2026-09-13）：rows/steps/tiers/bot_to_user/user_to_bot 逐字段桥层归一——score None/字符串/缺键 → 0.0（双向面板缺省 50.0）、bar 钳 0-100、cls 白名单 {up,down,flat}、None 值显示 "—"；模板 `%.1f` 格式化不再可能抛 TypeError（铁律 7 的前置保证），回归 `test_rendering_contract.py::test_affinity_card_never_raises_on_dirty_payload`。
- 逐能力接线（天气/菜谱/历史/占卜/游戏/usage → 统一 payload）由各能力调用既有 `render_*_html`；bridge 层不感知能力业务。
- 逐能力接线不改变本契约；卡片「区段/字段命名」**骨架轴**现无契约条款亦无断言（结构锁=根类名 1 条，F14 §7.1 亲证），立项与否随 v21r4 裁决（§八 D-7）。

## 八、豁免登记与待补门（2026-09-20 并入，源=F24 对账单 §五草案，DOC1-b 席套用）

> 编号说明：本节按波次引用惯例直称「§八」（全文交叉引用均写 §八，不补 §七空节，避免指针漂移）。
> 规矩：豁免只有两个合法来源——本表登记，或值册登记（登记即等值放行，不算豁免）。新增豁免须注明裁定出处；列外=违例。失效条件到点的豁免应删行并执行收口。

| # | 豁免物 | 所在面 | 理由 | 验收判据 | 登记批次 | 失效条件 |
|---|---|---|---|---|---|---|
| E-1 | `wash_blob_mix=24`（默认 35） | error 卡（bridge `_card_root_tokens` 参数实值） | v21r3 C2 显式裁定：红 accent 卡混 35 过艳，视觉不变硬约束 | `test_core_registry_blob_constants_exact` 邻域 + bridge 参数等值（24 出现即须配本行） | 0918 通水波 | 若 error 卡壳重绘经用户裁定，行删 |
| E-2 | `.card::before/::after` 双斑 + 手写 reduced-motion 关停（时长 46/58s 咬登记集） | mermaid_card.html | 伪元素形态先于通水存在；C13 根修只收 DOM 斑侧 | gate02 时长/名称集合绿；手写关停规则恰含两伪元素选择器（多一处=红）；份数注释在模板内 | 0918（MISC 换血波） | F14-1 骨架迁移把伪元素改走 blobs_html 时行删 |
| E-3 | 「双伪元素+DOM 第 3 斑」混合体、斑几何私调（::before 62%/-16%/-24% ≠ _BLOB_SPECS 58%/-14%/-22%） | universal_card.html | 宽版双栏历史构图验收过；几何偏差=登记名同源参数私调 | 相位锁测（test_phase_determinism_2 守卫）绿；斑几何改动需先改本行 | 0918 通水波 | 同上随骨架统一收编 |
| E-4 | amber 装饰族 6-7 枚（#ff9800/#e65100/#f5b83b/#f0b429/#b77900/#fff7d6 系）+ `--blue:#23ade5` + 认证徽 `#1d9bf0` + 中性对 #e4e6eb/#f1f2f3 族 | universal_card.html | 契约 §四「amber 装饰族豁免」在案；--blue/认证蓝为上游平台语义色复刻非品牌色 | gate08 不红（黑名单外）；**如执行 §四语义色行补白名单门（F5-1/S8-01），本行值必须先迁入本册或值册** | 0912-0918 散点（本表首次集中收编） | 色族收编进 theme_tokens 后并入「登记即放行」，本行删 |
| E-5 | `.footer-colored` 描边白 0.98/0.88（+accent 28% 染色中段） | universal `.footer-colored` 区段 | GLASS3 席 0919 主会话裁定=sanctioned 变体，现仅活在门 docstring | gate09 染色层整层放行；本行落地后 docstring 裁定指针化 | 0919 GLASS3 | 描边层如改 `var(--mica-glass-edge)` 消费则删 |
| E-6 | 两档描边变体 `.ttl`（song）/`.pill`（affinity）（.95/.35 无 .72） | 2 模板 | 「成员判定」语义天然放行；裁定为合法档位了事（S8 E-5 二选一，推荐此） | gate09 现口径绿即合规；如改「EDGE 全模式匹配」门则本行失效并需改面 | 0919 F5/S8 发现→本表登记 | 全模式匹配门落地时收编或删 |
| E-7 | ~~affinity :root 内联 `style="background:…linear-gradient(150deg,…)"` 描边副本 7 处~~ **已收编失效（VIS1 2026-09-20）**：affinity/song/universal/market/finance 全部行内 zebra 描边副本改 `var(--mica-glass-edge)` 消费（失效条件「可被 inline 消费的机制落地」达成——公共段早已注入该变量，本波完成消费迁移）；份数=0 | —（行删，按「失效条件到点的豁免应删行并执行收口」规矩保留此划线注） | 0913 vis4 存量→0920 收编 | 已失效 |
| E-8 | recharts 图元字号 12px CSS 钉死 | webui/index.css 图元段 | SVG tick/legend 不吃 Tailwind 类；与 fs-caption 同值有意为之 | 定义处集中（选择器表内命中=1 处）；宪法门禁 tsx `fontSize:` 互补成立 | 0919 WEBUIFE | WebUI 字号定义层如被扩门收编则并册 |
| E-9 | canvas 字体字面量 `context.font='12px "Segoe UI", …'` | webui memory-canvas.tsx | canvas 2D 不吃 CSS 变量（需 getComputedStyle 读 token，未做）；现游离于一切门与登记之外——**本行即 P1-3④ 的补登记** | 补门前：字体栈与 FONT_FAMILY_STACK 一致目验；补门后（F4 N4 方案 `context.font` 扫描）改判红为合法登记态 | 0918 审计发现→本表收编 | 读 token 版实施时行删 |
| E-10 | 内联 `style={{height:480}}` 「内联白名单 #1」 | webui memory-graph.tsx（注：非 memory-canvas.tsx，旧审计坐标错） | pages2-spec 两处白名单之一（画布高度）；道德约束非机器约束（门本不扫尺寸内联） | 白名单实例=2 处（高度+侧栏宽）不得增 | 0918 PAGES2 | 内联尺寸扩门落地时程序化 |
| E-11 | 宽度门整体剥离 `@media` 块（559/720px 断点不入册） | 九门 gate06 设计取舍 | 断点是视口概念非壳宽；入册会混淆两轴 | 剥离仅限 @media 块内；块外私有宽度=红 | 0918 协调裁定（门注） | 如需「断点登记表」另立新轴 |
| E-12 | 直拼卡阴影两级面（无 --mica-shadow-panel） | 4 直拼卡 | `test_mica_builders_contract.py::test_exactly_two_shadow_token_definitions` 钉死=事实上的裁定；缺 panel 未致视觉缺（两档够用） | 公共段阴影键集合恰={--mica-shadow,--mica-shadow-soft}；如升三级先改本行 | 本表 0919 首登（前零记载，X2 项收编） | 三级面裁定+改测时行删 |
| E-13 | 存量展示级字号（26/23/22/17px 等）不受 TYPE_SCALE 追溯 | 各卡 | 实弹验收过的构图不因换档回溯（契约 §四原句） | TYPE_SCALE 仅约束新/改版选值（**声明级、无门**，见 §四字号下限行与 HANDBOOK §32.5）；存量白名单=样张基线 19 面 | 0912 契约原句 | 无（永久条款） |
| E-14 | media 卡不传 viewport（吃后端缺省 640×400 / 672×480 两套） | templates.py 出卡路 + render_backends 两缺省 | 现状如此、640 档贴边有裁阴影风险但未被证实出过坏图（禁渲染未证） | F14-10 收口（viewport 登记表+统一缺省常量）前：改后端缺省须同步本行 | 本表 0919 首登 | emitter/viewport 登记落地时行删 |

**待补门登记（「纸面/半牙条款」的 D 系列，配 §二/§四/§五各引用）**：
- **D-1** 直拼卡 keyframes 名门（builders 加 @keyframes 名集断言，一测即得，推荐补）。
- **D-2** 遮罩面扫门 `gate10_scrims`（对 11 面 CSS 提取暗色系 rgba 且位于 background/gradient stop 位，白名单=OVERLAY_SCRIMS 四员+功能常量+本册；与 gate09 白玻璃、铁律 5 光晕下限划界防同值双门互踩；设计全文=F24 §四 4.3-6）。
- **D-3** usage_cards `.status.*` 改 var() 消费（一行）。
- **D-4** `--text-sub`(#5b6069) / `--text-secondary`(#576272) 双 token 并轨（先裁值，再把 text-secondary 并入 render_root_tokens 公共段）。
- **D-5** echo 直拼卡 12.5px/14.5px 改值，或 C8 口径加注（裁后执行）。
- **D-6** 宽度查表收口：四处 `width_px=` 字面量改 `CARD_SHELL_WIDTHS[...]` + `_DEFAULT_SHELL_WIDTH_PX=880` 并表。
- **D-7** 卡骨架契约（区段清单/顺序/字段名最小册，F14-12 建议集；立「铁律 10」与否随 v21r4 裁决）。
- **D-8** 样张基线入库 + 钉帧成功率观测（基线 sha256 旁车入库、`pinned==0` 告警、浏览器指纹字段；治 %TEMP% 一清判据即灭，S8-05/F5-5/6）。
- **D-9** 瓦片白玻璃双背景的字面量收口被 `test_template_visual_audit.py::test_list_tiles_keep_glass_surface` 阻挡（VIS1 2026-09-20 实碰回滚）：该门按规则体**字面含 padding-box+border-box** 取相，market `.index`/finance `.row`/affinity `.glass`/song `.glass`/error `.row(.alt)` 六处改 var() 消费必红；本席禁改该测试（非可写面），已还原等值字面。收口=先把该门取相改为「字面或 var(--mica-glass-main/edge) 消费皆合法」再做迁移（改门属断言语义变更，待裁）。
- **D-10** mermaid 节点圆角例外（VIS1 2026-09-20 用户裁定落地）：mermaid_card.html 页尾新增渲染后 polygon→圆角 path 替换脚本 + `.node rect` CSS rx——打破 vis4「SVG 图形内部零触碰」旧例（动因=用户明裁「矩形、菱形全部改圆角」，themeVariables/classDef 实测无落点）；范围锁 `.node` 子树，连线/箭头/文字零触碰；如后续 mermaid 升级致 DOM 形态变化，此脚本与探针结论（VIS1-impl §3.3）为回归基线。
