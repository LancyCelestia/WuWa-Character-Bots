# 紧急预警出卡「施工图」（CARD-MAP 席，2026-09-20）

> 本文是**施工图 + diff 原文，不是实施**：本席未改任何 render/生产文件（独占可写面=本文 +
> `reports/CARDMAP-report.md` + `%TEMP%/emergency-card-mock/` 样张）。
> 用户已裁定 R-8=「等 render 冷却后一次性完成」⇒ 本文所有 diff **一律不 apply**。
> 全部 `文件:行` 为 2026-09-20 03:27–03:35 直读磁盘所得；开工基线 `HEAD=15ed31f`、
> render 面 `git status --porcelain` = **12 件 `M`**（收工复测见 report）。树脏且 HEAD 每几分钟一动
> ⇒ **一律按符号名定位，行号只作二次确认**。

## 0. 一句话结论

1. **推荐路线乙（复用 finance_card sections/rows 零模板改动）**——本域出卡对契约测试与哈希登记的扰动：
   路线乙 = 2 面（值册 1 + 域能力层 1），路线甲 = **约 14 面**（含 6 个测试枚举面、1 个哈希跟踪项新增、
   3 处「11 面/7 张」文档口径、样张脚本与基线扩面）。§2 给逐面对账表与理由，不两头堵。
2. 等级四级色**必须新增登记**在 `theme_tokens.py`（D-3 色走 token）——抄 `ERROR_ACCENT/ERROR_THEME` 正例
   （定义 `theme_tokens.py:424-425`、bridge 注入面 `bridge.py:1824-1869`，§1 逐坐标）。P1/P2/P3 取值=待裁点 C6①。
3. render 冷热简报修正：**`verify_hashes --check` 于本席 03:31:42 实测已 EXIT=0**（brief 03:24 所述
   「2 项渲染面漂移」已被 T84 收口笔 `863fee6` 重录化解）；开工判据三条件现只差两件：
   **12 件 render 面未入库** + **mtime 未静默**（`bridge.py` 02:11:12、`templates.py` 02:57:24）。

---

# C1 色族：`theme_tokens.py` 告警四级（正例=ERROR_ACCENT/ERROR_THEME）

## 1.1 正例的完整生命周期（定义→注入→消费，全坐标）

| 环节 | 坐标 | 事实 |
|---|---|---|
| 定义 | `domains/render/card_render/theme_tokens.py:418-425` | 「系统主题（非平台，独立于平台注册表）」节：`ERROR_ACCENT = "#d54941"`（:424）→ `ERROR_THEME = _make_theme("system_error", "运行异常", ERROR_ACCENT)`（:425）。注释钉死命名纪律：**不进 `PLATFORM_THEMES`**（平台注册表只收「内容来源平台」，系统态不污染该命名空间，:420-421）；云母洗由 `derive_wash_tokens` 从 accent 派生、mist 保持本命打底（:422-423） |
| 导出 | `theme_tokens.py:508-509` | `__all__` 显式列 `"ERROR_ACCENT", "ERROR_THEME"` |
| bridge import | `bridge.py:63-92`（`ERROR_THEME` 在 :67） | 单一来源 import 面 |
| bridge 注入 | `bridge.py:1824-1870`（`render_error_card_html`） | `platform_color=ERROR_THEME.accent`（:1838）、`**_derive_wash_tokens(ERROR_THEME.accent)`（:1862）、`root_tokens=_card_root_tokens(ERROR_THEME.accent, phase=payload_phase(data), wash_blob_mix=24)`（:1867-1869）；模板注册 `_ERROR_CARD_TEMPLATE = _ENV.get_template("error_card.html")`（:1807） |
| 上下文公共段 | `bridge.py:178-192`（`_vis4_context`：vis4 六键+CORE 值册+decor_css/blobs_html）、`bridge.py:195-218`（`_capsule_context`：CAP1 品牌胶囊） | 每张 Jinja 卡必消费的三件管道 |
| :root 组装 | `bridge.py:221-257`（`_card_root_tokens`）→ `mica_shell.py:377-435`（`render_root_tokens`：`--phase/--accent/--accent-dark/--wash-1..3/--wash-mist/--wash-blob-1` + 公共三十项，error 卡 `wash_blob_mix=24` 按卡传参 :242-243） | 「平台色只做 accent、wash 打底」的实现点 |
| 导出面门 | `tests/test_rendering_contract.py:727-730` | `bridge.__all__` 必须显式导出 `render_error_card_html`（新 builder 照此办理） |

**「平台色只做 accent」如何满足**（`docs/rendering-contract.md` §二 :33-34）：外壳底色**只能**是
`linear-gradient(145deg, var(--wash-mist) 0%, …)` wash 渐变，`--accent` 永远不做底色；平台/系统色只允许
两层受控出场 = accent（徽章/高亮/链接）+ `--wash-blob-1`（≤35% 混入主色斑；error 卡登记特例 24%，
契约 §八 E-1 :101）。四级告警色走同一通道：作 `--accent` 与 badge 色，**不作任何大面积底色**；
mist 打底由 `derive_wash_tokens`（`theme_tokens.py:141-166`，明度 0.96 :48）保证本命基底不丢。

**连带面核查（PLATFORM_THEMES 17 平台 + 别名族）**：`_PLATFORM_ACCENTS`（:381-400，17 员）、
`THEME_ALIASES`（:408-412）、`UNKNOWN_THEME_KEYS`（:415）、`bridge.PLATFORM_COLORS/PLATFORM_OFFICIAL_NAMES`
派生面（`bridge.py:94-106`）、供给链 S3「BRAND/ERROR/DEFAULT 三主题并集」（`tests/test_token_supply_chain.py:47-49`）
⇒ **四级系统主题不注册进平台表，以上全部零连带**。这正是抄 ERROR_THEME 的最大理由。

## 1.2 diff 原文（`theme_tokens.py`，**不 apply**）

锚点=符号 `ERROR_THEME`（现 :424-425 之后、`get_platform_theme` :428 之前）：

```python
 ERROR_ACCENT = "#d54941"
 ERROR_THEME = _make_theme("system_error", "运行异常", ERROR_ACCENT)
+
+# ==================== 紧急预警四级（CARD-MAP 施工图 2026-09-20，R-8；未 apply） ====================
+# 紧急预警卡（bot.emergency_info）专用系统主题：色名语义锚 = 紧急域对外文案唯一口径
+# （domains/emergency_info/contracts.py:85-88，P0=红色/P1=橙色/P2=黄色/P3=蓝色，D-3 等级单一枚举）。
+# 与 ERROR_THEME 同族纪律——不进 PLATFORM_THEMES、不造第二等级枚举（色只是 EmergencyLevel 的投影）。
+# P0 复用 SEMANTIC_DANGER 登记值（与 ERROR_ACCENT 同值异名——异常语义≠灾害语义，等值双登记合规，
+# DESIGN-SPEC §一.11④「任何新视觉先入册后引用」）。P1/P2/P3 取值 = 待裁点 C6①（通用告警语义色 vs
+# 鸣潮本命色族），下方为**候选甲（通用告警语义色）**，apply 前按裁定删改；本席不落盘。
+EMERGENCY_P0_ACCENT = SEMANTIC_DANGER       # 登记值 #d54941（红）
+EMERGENCY_P1_ACCENT = "#c05a12"             # 候选甲·暗橙（白玻璃面上文字对比 ≥4.5:1 取向；目验靠 §V 样张）
+EMERGENCY_P2_ACCENT = SEMANTIC_WARNING      # 候选甲·= #b07d1a 暗琥珀登记值（「黄色预警」以可读暗金呈现）
+EMERGENCY_P3_ACCENT = BRAND_ACCENT          # 候选甲·= #318ce7 守岸人本命淡蓝（蓝色预警与品牌色天然同值）
+EMERGENCY_THEMES: dict[str, ThemeTokens] = {
+    "P0": _make_theme("system_emergency_p0", "红色预警", EMERGENCY_P0_ACCENT),
+    "P1": _make_theme("system_emergency_p1", "橙色预警", EMERGENCY_P1_ACCENT),
+    "P2": _make_theme("system_emergency_p2", "黄色预警", EMERGENCY_P2_ACCENT),
+    "P3": _make_theme("system_emergency_p3", "蓝色预警", EMERGENCY_P3_ACCENT),
+}
```

`__all__`（现 :499-544，字母序段内）追加：

```python
     "DEFAULT_WASH_TOKENS",
+    "EMERGENCY_P0_ACCENT",
+    "EMERGENCY_P1_ACCENT",
+    "EMERGENCY_P2_ACCENT",
+    "EMERGENCY_P3_ACCENT",
+    "EMERGENCY_THEMES",
     "ERROR_ACCENT",
```

**候选乙（鸣潮本命色族，供 C6① 对照）**：四级 accent 全取 `BRAND_ACCENT` 单色，等级差只走 badge 文字
（「红色预警」等四字已在 contracts.py:85-88 唯一锁定）+ `--wash-2` 星空紫浓度分档。视觉一致性最高、
新增 hex=0，但**牺牲气象预警用户的红橙黄蓝生命线认知**（国家预警信号色标是公众语义）。本席作为
施工图作者倾向候选甲，**裁定权在用户**（列 C6①，不裁）。

**level→token 映射不住 render 面**：映射表放域能力层（`domains/emergency_info/` 内
`{EmergencyLevel.P0: EMERGENCY_P0_ACCENT, …}`，import theme_tokens 常量），与 error_report 先例同构
（`domains/ops/monitor/error_report.py:853-857` 只在能力侧 import bridge builder，render 域零感知业务）。

---

# C2 模板路线对比（甲=新第 8 张 Jinja；乙=复用 sections/rows 契约）

## 2.0 先纠一处简报口径（不纠则误导裁定）

简报路线乙写「复用 **universal_card.html** 的 sections/rows 契约」——**真身是 finance_card.html**：
商品/国债/北向三卡先例的权威注释在 `domains/finance/capabilities/market.py:147`
（「三者共用既有渲染契约（render_finance_card_html sections/rows），模板零改动」），DOM 槽位在
`finance_card.html:108-128`（`{% for section in sections %}` → `section.rows` 的
label/value/delta/cls/sub/trend_note），payload 归一在 `bridge.py:1572-1643`。
`universal_card.html`（1675 行）是**平台解析卡**（RenderPayload 90+ 字段、bilibili 统计/评论/视频语境，
`models.py:48-88`），无通用 sections 槽——紧急卡硬挤它反而要做 payload 语义扭曲。**下文路线乙 = 复用
finance_card 壳**（先例同型、字段天然对得上：badge=等级、subtitle=区域、rows=预警条目、
source_note=出处、updated_at=发布时间、delayed_note=时效说明）。

## 2.1 路线甲连带面全清单（新增 `emergency_card.html` 第 8 张）

| # | 面 | 坐标 | 要动什么 |
|---|---|---|---|
| 1 | 模板文件 | `domains/render/card_render/templates/emergency_card.html`（新增） | 全新 DOM，全部契约面自带合规 |
| 2 | bridge 三件 | 照 `bridge.py:1807/1824-1870` 正例 | `_ENV.get_template` + `render_emergency_card_html` + `__all__` 导出 |
| 3 | 值册宽度 | `theme_tokens.py:98-112` `CARD_SHELL_WIDTHS` + 新键 | 新模板宽度必须先入表（契约 §五.7；gate07 动态读表 `test_v21r3_visual_gates.py:20-21`） |
| 4 | 契约枚举×3 | `tests/test_rendering_contract.py:67-75`（CARD_TEMPLATES）、`:78-86`（_SHELL_WIDTH_KEYS）、`:106-114`（_RENDER_ENTRIES） | 三处 +1 条目；:12-13 明文「显式枚举，禁止 glob」⇒ **漏一处=该模板脱门裸奔**（不红，但永久失管） |
| 5 | 九门枚举 | `tests/test_v21r3_visual_gates.py:65-74`（_TEMPLATE_SURFACES）+ payload builder | 9 门 × 11 面 → × 12 面（9 条新用例自动跑） |
| 6 | 供给链枚举 + S-D 硬门 | `tests/test_token_supply_chain.py:71-79` + `:455-461` | **S-D 双向登记门**：新模板落盘未登记 = 直接红 ⇒ 此面**不可漏**；另需补该面的渲染取样函数（:232-260 同型） |
| 7 | 排印枚举 | `tests/test_e03_typography.py:27-35`（CARD_TEMPLATES） | +1；行高/字号/新 keyframes 名集断言自动扩面 |
| 8 | 相位钉帧枚举 | `tests/test_phase_determinism.py:197` 附近 renderer map | 新 builder 应入册（E01 全 11 面口径→12 面） |
| 9 | 视觉审计 | `tests/test_template_visual_audit.py`（zebra ΔE/对比门，`theme_tokens.py:209` 引用在案） | 若模板用三档表面 zebra ⇒ 扩面；不用则至少核对不触黑名单 |
| 10 | 哈希清单 | `tests/verify_hashes.py:34-60`（TRACKED_FILES，现 19 项，docstring :16-20） | **新模板入册 19→20 + 全量 `--write` 重录 `tests/render_hashes.json`**（theme_tokens/bridge 本就要改，但新增跟踪项是唯一「清单本体变更」面） |
| 11 | 样张脚本 | `scripts/render_card_samples.py`（18 样张，`tests/test_render_card_samples.py:1-4` 断言面） | +1 变体 → 该测试扩面 + **样张基线**（baseline-20260919-paused 19/19 STABLE 判据，AGENTS #41②）→ 基线重录 |
| 12 | 文档口径×3 | `docs/rendering-contract.md:3`（「全部 **11 个渲染面**：7 张 Jinja+4 直拼」）、`DESIGN-SPEC.md:25,27,34`（「11 面」多处+门族清单）、`docs/design/visual-effects-catalog.md:6`（「现 7 模板」） | 三处改数 ⇒ 前两者是**哈希跟踪件**，改了就再进 `--write` 序列 |
| 13 | 胶囊/装饰合规 | 新模板必须消费 `{{ capsule_css/capsule_html }}`（CAP1「所有图片加胶囊」，`bridge.py:195-218`）+ `{{ decor_css/blobs_html }}`（铁律 8 单源，契约 :19） | 模板内合规成本 |
| 14 | 导出面门 | `tests/test_rendering_contract.py:727-730` 正例 | 建议同步补 `render_emergency_card_html` 断言（否则无人锁 __all__） |

**甲的扰动定量**：测试枚举面 6 件必改（其中 1 件是硬门 S-D）+ 哈希跟踪清单新增 1 项 + 哈希重录涉及
≥6 个跟踪件（theme_tokens/bridge/新模板/契约/DESIGN-SPEC/catalog）+ 样张基线换代 + 「模板数 7→8、
11 面→12 面」三处文档口径。**HEAD 每几分钟一动、render 12 件未入库的窗口里，这张清单上任何一件
都可能在写前被别人改过 ⇒ 竞态面最大。**

## 2.2 路线乙连带面全清单（复用 finance_card 壳）

| # | 面 | 坐标 | 要动什么 |
|---|---|---|---|
| 1 | 值册 | `theme_tokens.py`（C1 diff） | 四级 token 登记（**甲乙共同前置**，D-3 色走 token） |
| 2 | 域能力层 | `domains/emergency_info/`（新文件，非 render 面） | 组 payload + 调 `bridge.render_finance_card_html` + 后端截图 + 失败回文本（逐字照抄 `market.py:231-258` `_render_finance_sections_card` 形态：`render_backend None/不可用→""`、png 非 bytes/空→`""`→调用方纯文本，铁律 7 实证样板） |

**零改面清单（乙的全部诱惑所在）**：模板文件 0、`bridge.py` 0（`render_finance_card_html` 已接受
`platform_color` 自由 accent——`bridge.py:1583-1586` 缺省 BRAND 本命、可传等级色，且
`_safe_css_color` 守卫非法值回退）、测试枚举 6 件 0、S-D 双向门 0（templates/ 无新文件）、哈希跟踪
清单 0 项新增（theme_tokens 的 `--write` 重录甲乙都躲不掉，不算差异）、文档「11 面」口径 0、
样张基线 0（**可选**加一张 emergency 变体样张进 `render_card_samples.py`，属加分项非扰动项）。

乙的表达力缺口（如实登记）：finance_card DOM 无「时效条/倒计时」槽位；等级色只出现在 `--accent`
（badge/分隔线/wash-blob ≤35% 层），色块不做大底——这与「色斑≤35%、accent 不作底色」契约正好同向。
`cls={up,down,flat}` 涨跌语义与紧急卡无关（delta 缺省即不渲染，`finance_card.html:119`）；
trend_svg 槽不用（bridge :1596-1597 只放行内部 finance_chart 产物，域侧传空串即静默隐藏）。

## 2.3 裁定建议（不两头堵）

**推荐路线乙**。理由按用户判据权重排：
1. **对契约测试与哈希登记的扰动小**——乙 2 面 vs 甲 14 面（§2.1 全表），且甲的 6 个枚举面里有 1 个
   硬门（S-D）+ 5 个「漏了不红、永久失管」的静默面（:12-13 禁止 glob 的注释就是给这种漂移立的碑）；
   哈希重录序列甲比乙多 3 个文档件 + 1 个清单本体变更（19→20），与 CAP2 胶囊线（HEAD 02:43:50
   `6551c93`）和仍在飞的 12 件 `M` 撞车窗口显著更宽。
2. **用户裁定 R-8 =「冷却后一次性完成」** ⇒ 扰动面数量 = 施工时长 = 撞车概率，乙直接小一个量级。
3. 仓内先例同型且已走过完整验收（商品/国债/北向三卡，零模板改动）。
4. **换甲触发条件（预先钉死，避免将来温水煮）**：若 C6② 裁定「卡片必须含倒计时/时效条」等
   finance_card 表达不出的 DOM 元素，**直接切甲**、一次性承担 §2.1 全清单——不要「改 finance_card 模板
   加槽」这条中间路（那会把金融域三卡的样张基线和 `test_rendering_contract.py` 金融断言全拖下水，
   两头扰动都占）。

---

# C3 UI 铁律核对表（逐条：本卡怎么满足）

> 判据两态：**路线乙**下模板现件已全量合规（finance_card 是 v21r3 通水波+样张基线 STABLE 的存量面），
> 本域新增面（值册 token + 域 payload）只需守「注入值不越册」；**路线甲**下新模板逐条自带。
> 每条给：规则出处（docs/rendering-contract.md §一 铁律表 :10-20、§四 :45-64；DESIGN-SPEC.md §一）+
> 执法门 + 本卡满足方式。

| # | 铁律 | 门（执法点） | 路线乙如何满足 | 路线甲额外义务 |
|---|---|---|---|---|
| 1 | 无 `<meta viewport>`（META_VIEWPORT_POLICY="forbidden"，`theme_tokens.py:72`） | 契约 test_no_meta_viewport（`test_rendering_contract.py:167-173`，逐 CARD_TEMPLATES） | 复用模板已在册已过门；本域侧=不注入任何 meta（payload 无此面） | 新模板文件禁出现 meta；入 CARD_TEMPLATES 后自动受门 |
| 2 | body 透明（截图 omit_background 依赖） | 契约 test_body_transparent（:175-183）+ test_full_page_fallback_screenshot_omits_background（:786） | 同左（`finance_card.html:39-40` 现合规） | 新模板 `body{background:transparent}` |
| 3 | 字重 ≤700（FONT_WEIGHT_MAX=700，`theme_tokens.py:74`） | 契约 test_font_weight_at_most_700（:190-204）；登记旁路=命名值 bold（契约 :14） | 模板现值 ≤700（badge 650 等，`finance_card.html:64,81,85`）；payload 只喂文本不改 CSS | 等级徽章若加粗≤700；禁 bold 字面量 |
| 4 | 动画必须在 `.card` 子树 | 契约 test_animation_selectors_are_card_scoped（:440-453）+ test_animations_render_inside_card（:421） | 色斑层由 `{{ decor_css }}/ {{ blobs_html }}` 生成器单源（`bridge.py:170-192`），根容器 `div.shell.card`（`finance_card.html:99`） | 新根必须带 `.card` 类（契约 §五.2 截图选择器契约）；时效条若做=循环动画或干脆静态（视觉目录 §0.1 推论 2：一击性动画会被 0ms 档截成鬼影帧——`docs/design/visual-effects-catalog.md` :17-21） |
| 5 | 光晕 alpha ≥0.05 | 契约 test_glow_alpha_floor（:455-467） | `--glow-accent`=accent 20%/8% color-mix（`theme_tokens.py:200-204`），远过下限 | 同 token 消费即可 |
| 6 | 阴影只准分级族（SHADOW_CSS_VARS 三员，`theme_tokens.py:194-198`） | 契约 test_shadow_tokens_within_family + token 值等值锁（:206-257，白名单从登记表**动态派生**） | 壳 `var(--mica-shadow)`、行瓦 `var(--mica-shadow-panel)`（`finance_card.html:51,78`）；本域侧=不新增阴影 | 禁族外值含 inset；新档位先入 SHADOW_CSS_VARS 再引用（DESIGN-SPEC §一.11④） |
| 7 | 半径 30-18-14 + 内径 {4,6,8,12,16} + pill/圆特例 | 契约 test_shell_radius_tokens（:259-270）+ v21r3 门第1条（`test_v21r3_visual_gates.py:12-15`） | 模板 `var(--r-shell)/var(--r-tile)/999px` 现合规（`finance_card.html:43,73,65`） | 外壳只允许 var(--r-shell)，禁壳级字面量（契约 §四 :49） |
| 8 | 宽度登记表（CARD_SHELL_WIDTHS，`theme_tokens.py:98-112`） | 契约 test_shell_width_is_audited（:272-295）+ gate07 动态读表（v21r3 :20-21）+ test_core_registry_shell_widths_direct_cards（:711-725） | finance=1080 已在册（:103）；**乙零新增** | 甲须先入表新键（如 `"emergency": 1080`）再在模板消费——进表真、消费表假的历史欠账（契约 §八 D-6）新卡不得复制 |
| 9 | 间距刻度 GAP_SCALE_PX={3,4,6,7,8,10,12,14,16}（`theme_tokens.py:77`） | 契约 test_gaps_use_audited_scale（:301-309）+ gate06 | 模板现值全在刻度（gap:12/10/8/4×14 等） | 新模板 gap 只准刻度值 |
| 10 | 行高刻度 {1.0,1.1,1.15,1.2,1.4,1.5,1.6}（契约铁律 9 :20）+ 字号 ≥12px | test_e03_typography（CARD_TEMPLATES 枚举 :27-35）+ gate04/gate05 | 模板存量已过（v21r3 C7/C8 收口波洗过） | 新模板选值走 TYPE_SCALE_PX 阶梯（`theme_tokens.py:226-232`，选用基准：display26/title20/body15/label13/caption12） |
| 11 | 色斑恒 3 枚、时长恰 {46,52,58}s；keyframes 只 mica-drift-a/b/c | gate02（v21r3）+ 契约铁律 8（:19，半牙旁路已登记） | 生成器单源注入（`finance_card.html:59,100`） | 同左（甲新模板必须消费 decor_css/blobs_html 注入键，禁手抄） |
| 12 | 平台/系统色只做 accent、wash-mist 打底、色斑混入 ≤35% | 契约 §二 :33-34 + test_brand_wash_tokens_injected（:318-346）+ test_pc_never_paints_brand_base（:348-350） | 等级色走 `platform_color`→`--accent`（bridge :1583-1586/:1621），wash 由 `derive_wash_tokens` 派生、mist 恒本命打底（`theme_tokens.py:141-166`）；`--wash-blob-1` 混入=缺省 35%（`bridge.py:242` 注 wash_blob_mix 缺省 35、error 24） | 甲同法；若视觉过艳可照 error 卡先例申请按卡 wash_blob_mix 豁免登记（契约 §八 E-1） |
| 13 | 渲染失败→纯文本兜底、契约零破坏 | 契约 test_renderers_never_raise_on_empty_payload（:551-575）+ test_null_backend_keeps_text_fallback_contract（:604-607）+ test_mermaid_png_falls_back_to_none_without_backend（:596） | **正例现抄**：`market.py:237-258`——后端 None/不可用→`""`；png 非 bytes/空→`""`；调用方以空串走纯文本；bridge builder 对 None/{} 不抛（`render_finance_card_html` 入参 `payload_dict|None=None`，`bridge.py:1572`） | 甲新 builder 必须同型「None/{} 可渲染」+ 入 `_RENDER_ENTRIES`（:106-114 的 entries 都用 `{}` 调用 ⇒ 天然被 :551 门覆盖） |
| 14 | 品牌胶囊 CAP1（所有图片加胶囊）+ 相位 digest 钉帧 | `bridge.py:195-218`；`test_phase_determinism*.py`（DESIGN-SPEC §三.2 门族） | 模板消费 capsule_css/capsule_html（`finance_card.html:95,135`）+ `phase=payload_phase(data)`（bridge :1636）⇒ 同 payload 同截图字节 | 甲同法 + 入 phase 确定性 renderer map（§2.1 面 8） |

---

# C4 连带面与门（出卡面全清点——先数清再动工）

## 4.1 出卡「几面」直答

WIRE-MAP 证明注册九面实为十面；**出卡面**同理清点：**路线乙 = 2 面实改 + 4 面零改须知；路线甲 = 14 面**
（§2.1 全表）。乙的 4 面「零改须知」：

1. `test_mica_builders_contract.py` 与 4 处 f-string 直拼卡（echo `_help_mica_html` /
   debug `_llm_setup_mica_html` / `usage_cards.py` / `templates.py::render_media_card_html`，
   `tests/test_mica_builders_contract.py:1-15`）——**本卡不需要第 5 处直拼**：直拼是
   「帮助/诊断/账单/媒体降级器」场景的历史形态，v21r3 后新卡一律走 bridge/Jinja 正道；硬做第 5 处
   = 把「11 面」治理口径（契约 :3、DESIGN-SPEC :25/:27、九门与供给链两套枚举）全部重立法。
2. `renderer.py` 出站零改（mixed 序见 C6③）。
3. WIRE-MAP 十面（路由/help/config/db-owners/生成物）与本域出卡面**零交集**，勿混授权、勿并批施工。
4. `docs/rendering-contract.md` §六 payload 接线表（:84-92）：乙=可在 `render_finance_card_html` 行
   （:88）补「紧急卡复用（platform_color=等级色）」一句——**属文档诚实面，改则进哈希重录**，
   不改不红（无机器门解析该表，纸面条款）。

## 4.2 契约测试两件套是否动

- `test_rendering_contract.py`：乙=零动（新色**不塞进 SEMANTIC_COLORS**、走独立 EMERGENCY_* 常量
  ⇒ :644-658 `test_core_registry_semantic_colors_exact` 等值锁零扰；登记进 SEMANTIC_COLORS 才会撞表）。
- `test_mica_builders_contract.py`：两路线均零动（§4.1-1）。

## 4.3 `verify_hashes --write` 重录序列与撞车点

**纪律（DESIGN-SPEC §一.11③ 明文）**：值册或模板改动后跑 `--write` 重录，**由收尾席统一执行，
改文件的席位不得自行 `--write`**。重录触发件（乙）：`theme_tokens.py`（改）+
`docs/rendering-contract.md`（若做 §4.1-4 文档行）；（甲另加）新模板入 TRACKED_FILES
（`tests/verify_hashes.py:34-60`，清单本体 19→20）+ `DESIGN-SPEC.md`/`visual-effects-catalog.md`
口径行改。**实跑节奏**：全部源件改完 → 门族绿 → 收尾席一次 `--write` → `--check` EXIT=0 即封。

**撞车点（逐件点名，03:27–03:33 实测）**：
1. TRACKED 19 件中 **9 件在 12 件 `M` 未入库集合内**（theme_tokens.py、bridge.py、templates.py、
   7 张 Jinja 中 6 张除 mermaid 外全 `M`＋mermaid 也 `M`，加 error/affinity/finance/market/song/
   universal 全部）⇒ 出卡席改 theme_tokens 与该批未提交改动**同文件叠加**，必须先等入库（P-1′）。
2. CAP2 品牌胶囊线 `6551c93`（02:43:50，bridge/mica_shell/模板胶囊注入面）与 T84 收口 `863fee6`
   （render_hashes 对齐重录；本席 03:31:42 实测 `--check` EXIT=0、render_hashes.json mtime 03:31）
   ⇒ 哈希登记刚定版、且历史上多次被 autosync 抢录（台账 #41/T84 先例）——施工期任何 `--check` 红
   先查 HEAD 是否新增跟踪件改动，别急着归因本席。
3. 三个文档跟踪件 `docs/rendering-contract.md` 02:40 / `DESIGN-SPEC.md` 02:35 /
   `docs/design/visual-effects-catalog.md` 02:44 刚被 F24/DOC1 系改过（03:33 实测 git status 均
   干净）⇒ 动前读最新态 + 15 分钟静默窗。

## 4.4 其余文档面

`docs/design/visual-effects-catalog.md`（哈希跟踪件，`verify_hashes.py:47`）：本卡**零新特效**——
色斑/玻璃/胶囊/相位全部消费既有生成器 ⇒ 目录正文零动；唯一例外=C6② 若裁「做时效条/倒计时」=
新特效，**先入目录立 E 号再实施**（DESIGN-SPEC §一.11④「任何新视觉先入册后引用」）。
`DESIGN-SPEC.md` 版本行（:1「根部钉死版 v2 · vis4 层次化升级」+ :25/:27「11 面」口径）：乙零动；
甲改口径 ⇒ 重录。`tests/render_hashes.json`/`docs/auto-facts.md`：生成物，收尾席/`doc_sync` 代跑
（auto-facts 现 `M`，出卡席不碰）。

---

# C5 落地次序与回滚（P-1… 风格照 WIRE-MAP §6；本席零执行）

## 5.1 开工前置条件（全部硬门，任一不满足 ⇒ 不开工）

| # | 条件 | 判据（只读命令） | 本席 03:2x–03:3x 实测 |
|---|---|---|---|
| P-1′ | render 12 件 `M` 已入库 | `git status --porcelain -- plugins/bot_unified_runtime/domains/render/` 无输出 | **未满足（12 件 M，03:27:31）** |
| P-2′ | 哈希登记定版 | `python tests/verify_hashes.py --check; echo EXIT=$?` = 0 | **已满足（03:31:42 EXIT=0）**；开工时仍须复测（HEAD 分钟级在动） |
| P-3′ | 冷热静默 | `ls -l --time-style=+%H:%M:%S` theme_tokens.py / bridge.py / templates.py / 契约 / DESIGN-SPEC / render_hashes.json mtime 距今 >15 分钟且不再被写 | **未满足**（templates.py 02:57:24；render_hashes.json 03:31 刚写） |
| P-4′ | 基线红名单记账 | 跑 §5.2 步骤 4 门族一遍，红条原样写进开工席 report 首节（WIRE-MAP §6.3 步骤 0 同规） | 待开工席执行（本席无写权；哈希 EXIT=0 侧证现基线大概率全绿） |
| P-5′ | 写权清单齐备 | `domains/render/card_render/theme_tokens.py` + `domains/emergency_info/**` +（可选）`docs/rendering-contract.md` §六行 + 收尾席 `--write` 承接承诺（施工席不得自行）；甲另加 §2.1 全 14 面 | 主会话授权时逐项勾选 |
| P-6′ | C6 三点已裁 + 甲/乙路线已裁 | 用户裁定记录在案 | 待裁（样张 §V 即为此备） |
| P-7′ | 禁 commit/部署 | 生效口径永远写「代码+测试完成，重启生效」（铁律 4/7） | 本席与开工席同守 |

## 5.2 执行序（推荐乙；甲的差异在括号内）

| 步 | 动作 | 立刻跑什么 | 预期 |
|---|---|---|---|
| 1 | `theme_tokens.py` 四级 token 登记（C1 diff，按裁定取候选甲/乙值）+ `__all__` | `tests/test_rendering_contract.py tests/test_token_supply_chain.py` | 全绿（新常量零断言引用=零扰；S-A/S-D 不动） |
| 2 | 域内 RED 用例先行（B 波纪律先 RED 后 GREEN）：等级→accent 映射断言（P0→#d54941）、badge 文案逐字取 `contracts.py:85-88`、未定级 None 不出卡 | `tests/test_emergency_info_core.py`（新增函数） | 先 RED 后 GREEN |
| 3 | 能力层出卡函数：market `market.py:231-258` 逐字同型——`render_card(html, viewport 1160×1400, dsf 2, wait_ms 0)`→PNG→`prune_prefixed`；任何失败→`""`→纯文本 | 该域测试 + `tests/test_rendering_contract.py::test_renderers_never_raise_on_empty_payload` | 全绿；无后端环境自动走回退分支 |
| 4 | 门族 ≥8 件合跑（DESIGN-SPEC §三.2 清单：rendering_contract / mica_builders / v21r3_visual_gates / token_supply_chain / template_visual_audit / e03_typography / phase_determinism×2 / mica_shell） | 同卫生规范 | 全绿（乙路线红=本设计对某门认知错，停下来改施工图再来） |
| 5 | （可选加分）`scripts/render_card_samples.py` +1 emergency 变体样张 | `tests/test_render_card_samples.py` | 构造断言面 +1；像素基线属真机窗（契约 §八 D-8 样张基线现状=%TEMP 一清判据即灭，不在本批背） |
| 6 | 文档面：契约 §六表补「紧急卡复用」行（可选）；（甲=§2.1 面 4-12 全清单 + 三文档口径同步） | `verify_hashes --check` 预跑 | DRIFT 属预期实证（待收尾重录） |
| 7 | **收尾席统一**：`python tests/verify_hashes.py --write` → `--check` EXIT=0 → `dev.ps1` 四门禁（`test/lint/typecheck/runtime-layout`，主会话确认无在飞席） | 见 AGENTS.md 第五部分 | 全绿封版；「代码+测试完成，重启生效」 |

**红了怎么退**：步骤 1/2/3 任一步红 ⇒ 只回退本步 diff（先 `git diff -- <文件> > %TEMP%/cmap-step<N>.patch`
存档，再 `git apply -R --check` 试探后 `git apply -R`）；步骤 4 红且定位为他席在飞 ⇒ 按
WIRE-MAP/B4a 先例**只记录不修、不归因本席**；步骤 7 `--write` 前发现 TRACKED 件又被抢改 ⇒ 停，
回 P-2′ 重测，严禁顺手重录别人在飞件。

## 5.3 回滚命令（写清，**本席不执行**）

1. 受跟踪件（theme_tokens/契约/DESIGN-SPEC 等）：`git diff -- <文件> > %TEMP%/cmap-<名>.patch` 存档 →
   `git apply -R %TEMP%/cmap-<名>.patch`（先 `--check`）。⚠ 共享树只有在「该文件本次仅本席动过」时
   才允许 `git checkout -- <文件>`；禁 `git checkout -- .`/`git restore .`/`git stash`/`git clean`
   （铁律 4 + WIRE-MAP §6.4 同规）。
2. 未跟踪新增（甲=模板文件；乙若只改值册则跳过）：先整目录备份 `%TEMP%/cmap-<ts>/`，再用 venv python
   删（本机 Git Bash 无 `rm`/`mv`，shared-brief §3.8）：
   `"../ChatBot_Runtime/venv/Scripts/python.exe" -c "import os; os.remove(r'<路径>')"`.
3. 生成物（render_hashes/auto-facts/command-catalog）：**还原源面后重跑对应 `--write`**，禁手改生成物
   （WIRE-MAP §6.4-3）。
4. 回滚自证：重跑 §5.2 步骤 4 门族 + `verify_hashes --check`，红名单须逐条回到 P-4′ 基线快照
   （逐条比对，不比「大概差不多」）。

---

# C6 待裁（只列不裁）

| # | 待裁点 | 事实与约束（供裁定，不带结论） | 牵连 |
|---|---|---|---|
| ① | **等级色取值：通用告警语义色 vs 鸣潮本命色族** | 候选甲已写入 §1.2 diff（P0 复用登记 #d54941、P1 新登记暗橙 #c05a12、P2=SEMANTIC_WARNING #b07d1a、P3=BRAND_ACCENT #318ce7）；候选乙=四级单 accent（本命蓝）+徽章文字分级。**硬事实**：`domains/emergency_info/contracts.py:85-88` 对外文案已锁「红色/橙色/黄色/蓝色预警」——选乙则文案说「红色」而卡面无红，文字-色彩背离须同步改文案（触 WIRE-MAP help 面，非 render 面）。样张 §V 按甲案出，供目验 | C1 diff 定稿；P-6′ |
| ② | **卡片是否含倒计时/时效条** | 乙路线=只能 `delayed_note`/`sub` 文案近似（`finance_card.html:129-132` 槽位）；真 DOM=切甲路线（§2.1 全 14 面）**且**属新特效⇒先入 visual-effects-catalog 立 E 号（§4.4）。**上游硬约束**：NMC findAlarm 只有发布时间、无失效时间（AGENTS 台账 #9 已知边界）⇒ 时效条只能展示「发布时间 + 源未给失效时间」的诚实形态，**禁倒计时假时效**（B11 帮助文案「源未给失效时间就不假装知道有效期」同源）。动画形态另受鬼影帧约束（catalog §0.1 推论 2：0ms 截图档把一次性动画截成半透明） | 路线甲/乙分水岭；§2.3 换甲触发条件 |
| ③ | **语音与卡片的先后序** | **现状**：出站序=[前置件(如群@段), 图片(卡), 语音, 视频, 文件, 正文(最后追加)]（`renderer.py:302-325, 355-358`：images 先于 audio 入列、text 尾随）。可选形态：a) 维持现状（卡先·语音后·正文尾）；b) 语音先卡后（只改能力层 parts 摆放，render 面零动）；c) 学错误卡两段式（毫秒级文本回执先行、卡+语音 ≈3-33s 后补发，AGENTS #41 台账 de6ba91 先例——P0 时效性与渲染延迟的权衡）。渲染成本实测锚：单卡中位 2.28–3.10s、99% 在 Chromium 侧（visual-effects-catalog :7） | 只涉能力层/push 侧编排，不进本施工图 render diff |

---

# §V 样张（%TEMP%/emergency-card-mock/，仓库零写入）

生成方式：venv python 纯字符串函数（import `theme_tokens` 常量 + `mica_shell.render_root_tokens /
mica_decor_css / drift_blobs_html / brand_capsule_css / brand_capsule_html`，**不调 renderer /
render_backends、不跑仓库出图脚本、不写仓库任何路径**）手搓 4 份独立 HTML（C6① 候选甲四级各一张，
finance_card 同款壳：1080px 壳 + 145deg 本命 wash + zebra 玻璃行瓦 + 3 枚漂移斑 + 品牌胶囊摆位）；
playwright chromium `page.set_content` → `.card` bbox clip → `omit_background=True`、dsf=2，
PNG 落同目录。**截图绝对路径清单与目验要点见 `reports/CARDMAP-report.md` §样张**（用户判据优先于
指标：四级色是否「一眼分清红橙黄蓝」、暗橙在淡蓝 mist 底上是否脏、蓝色是否与本命底过融）。

---

# 附：本席复跑证据（全部只读；render 面零写入、零 git 写、零子代理）

| # | 命令 | 输出摘要 |
|---|---|---|
| 1 | `date` / `git rev-parse --short HEAD` / `git status --porcelain -- domains/render/ \| wc -l` | 03:27:31 / `15ed31f` / **12**（逐件清单见 report 心跳） |
| 2 | `PYTHONDONTWRITEBYTECODE=1 …python.exe tests/verify_hashes.py --check` | **无输出，EXIT=0**（03:31:42）⇒ 简报「2 项渲染面漂移」已被 T84 `863fee6` 化解（`render_hashes.json` mtime 03:31） |
| 3 | `ls -l --time-style=+%H:%M:%S` render 关键件 | theme_tokens 01:38:19 / 模板群 01:45–01:59 / bridge 02:11:12 / templates.py 02:57:24 / DESIGN-SPEC 02:35 / 契约 02:40 / catalog 02:44 |
| 4 | `git status --porcelain -- 契约/DESIGN-SPEC/catalog/render_hashes/auto-facts` | 仅 `M docs/auto-facts.md`（三文档件干净） |
| 5 | 直读定位（grep/Read） | ERROR 正例链、finance 复用契约、renderer 出站序、emergency contracts 等级表、六个测试枚举面、S-D 双向门等全部坐标（本文逐处引用） |
| 6 | `git log --oneline -3`（收工时复跑） | 见 report 收工记账（本席读文件后未再有 render 面变更：theme_tokens/bridge 等 mtime 在 03:35 复测未动） |

**生效边界**：本文与样张是**图纸产出**，不改生产行为；render 面在本席收工时点仍为「12 件 M 未入库、
出卡零实施」。收工 HEAD 与 render 面状态以 report 心跳为准。
