# 设计规格：f-string 卡 DOM 层统一（共享 mica 卡壳 `mica_shell`）

> **状态（2026-09-19 复核、2026-09-20 随 F24/DOC1-b 落稿）：部分实施。** 值层与 CSS 生成器层（`render_root_tokens`/`shell_base_css`/`mica_decor_css`/`drift_blobs_html`+宽度入册+`--pc` 退役）**已接入 4 卡**；**DOM/文档装配层（`render_shell`，生产消费者数=0，2026-09-20 全树 grep 复核）、根元素范式统一（规格 D5）、body/文档头统一（D7）、accent 解析三副本（D8）、宽度按表消费（D6 实质项，四处调用仍传字面量）五项未实施**，仍待用户裁决。剩余差异与结构锁缺口见 `unify-audit-20260919/F14-card-ia.md` §2.1/§7.1。目标读者为下一实施会话。
> 上游：`docs/handover-c-20260913.md` 未完成项 #4——「usage_cards/echo/debug 三处 f-string 卡
> 与 Jinja 模板的『布局结构层』统一（当前只统一了 token 值层，DOM 各自独立）｜低优先级重构」。
> 契约基线：`docs/rendering-contract.md`（本规格是其向 **DOM 结构层** 的延伸，七条铁律（现为九条，
> v21r3 增 8/9 两条）全部原样继承，无冲突；对照见 §1.5）。token 值层单一来源 `domains/render/card_render/theme_tokens.py`
> （历史路径 `output/card_render/theme_tokens.py` 为 v21r2 兼容垫片）已统一且**不在本规格改动范围内**。
> 日期：2026-09-13。现状断言均经源码核实（标注 `文件:行号`）；工作量数字均为**估算**。

---

## 0. 范围与不做什么

**做**：盘点四处 f-string/拼接 HTML 卡 builder 的 DOM 差异；裁决共享卡壳方案；给出分阶段迁移步骤与测试门。

**不做**：不改任何 token 值（theme_tokens 为唯一来源，只消费）；不动 `bridge.py` 公共面；**不删
`bridge._derive_wash_tokens` 历史别名**（rendering-contract §三明令勿删）；不动 `render_backends.py`
（`.card` 截图选择器契约）；不触碰 personas；实施时禁 git 写操作由用户执行。

统一对象（即 `tests/test_mica_builders_contract.py` 的四个 builder，`tests/test_mica_builders_contract.py:151-156`）：

| # | builder | 位置（2026-09-20 随 v21r2 域重组+行号漂移复核；行数以当次 grep 函数体为准） | 卡片 |
|---|---------|------|------|
| 1 | `_help_mica_html` | `domains/chat_reply/capabilities/echo.py:3268` 起函数体 | `/bot help` 命令手册卡（总览/详情两形态） |
| 2 | `_llm_setup_mica_html` | `domains/ops/admin/debug.py:717` 起函数体 | LLM 接入检查卡（管理员） |
| 3 | `usage_report_mica_html` | `domains/render/card_render/usage_cards.py:74` 起函数体 | 模型用量/账单报告卡 |
| 4 | `render_media_card_html` | `domains/render/templates.py:112`（CSS 源 `_CARD_CSS` :74） | 旧媒体解析卡（降级器，调用方 `domains/link_parse/capabilities/content_parser.py`） |

对照组（已统一的 Jinja 范本）：`domains/render/card_render/templates/universal_card.html`（行数以当次 wc 为准，2026-09-20 实测 1675，
`.card` 即壳）与 `templates/finance_card.html`（`<div class="shell card">`，上下文键消费法的新卡起点范例——见 `docs/rendering-contract.md` §五.1 2026-09-20 订正版）。

---

## 1. 现状盘点

### 1.1 DOM 结构差异表（问题 1）

| 维度 | echo 帮助卡 | debug LLM 检查卡 | usage 报告卡 | media 旧解析卡 |
|---|---|---|---|---|
| **根元素**（`.card` 契约） | `div.help-stage.card > section.help-shell`（echo.py:2783） | `div.setup-stage.card > section.setup-shell`（debug.py:802） | `div.stage.card > section.shell`（usage_cards.py:178） | `div.card > div.panel` **双层**，`.panel` 才是壳（templates.py:249） |
| **壳选择器** | `.help-shell`（私有名） | `.setup-shell`（私有名） | `.shell`（通用名） | `.panel`（私有名） |
| **壳宽** | 940px（echo.py:2729） | 880px（debug.py:751） | 900px（usage_cards.py:121） | 640px（templates.py:72） |
| **宽度登记** | 无（`CARD_SHELL_WIDTHS` 无条目，theme_tokens.py:84-91） | 无 | 无 | 无 |
| **accent 变量命名** | `--accent`/`--accent-ink`（f-string 直插） | 同左 + `--good`/`--bad`（debug.py:742） | 同左 | `--accent`/`--accent-dark`/`--accent-rgb`（`__占位符__`.replace 链，templates.py:202-219） |
| **别名 token** | `--ink`/`--muted`（echo.py:2720） | 有 | 有 | 无 |
| **截图 viewport** | 1040×1200（echo.py:2842） | 940×1000（debug.py:837） | 950×1000（usage_cards.py:225） | 后端默认 + alpha 裁剪（content_parser.py:401,415-417） |
| **头部** | `.help-head` flex：avatar-wrap 52px（图或「守」字兜底）+ kicker/title 27px/subtitle + 右侧 chip「发 /bot help 获取本图」（echo.py:2758-2766,2785） | `.setup-head` 块级：kicker「管理员诊断 · 只读」+ title 28px + status 药丸（ok/blocked/warn）+ message（debug.py:780-788,804） | `.head.glass` 块级：kicker + title 26px + status 药丸（ok/warn/bad）+ window 行「窗口 · 生成于」（usage_cards.py:150-159,180-185） | 无统一头部：可选 cover-wrap 240px + badge，title 19px/author 在 `.body` 内（templates.py:143-159,221-260） |
| **行布局** | `.help-grid.masonry`（column-count:2 瀑布流）或 `.single`；节卡 `.help-section.glass`+h2(dot)；行 `.command-row`=pill 命令药丸+desc（echo.py:2768-2778,2686-2706） | `.setup-body` grid gap6；行 `.row.glass` flex=语义圆点(.dot.ok/.bad)+row-key(Consolas)+row-desc+row-range+右值 row-value（debug.py:789-798,723-734） | `.totals` 4 列 `.tile.glass` 指标瓦片 + `.mhead/.mrow` 6 列 grid 表（模型/输入/缓存命中/缓存创建/输出/费用，含 unpriced 变体）（usage_cards.py:160-174,186-198） | `.stats` flex 药丸 + `.summary` pre-wrap 段落（templates.py:153-157,231-235） |
| **页脚** | `.help-foot` flex 两端：tip 提示 + `.help-bot-pill`（头像/兜底+名 · 命令手册）（echo.py:2779-2782,2785） | `.setup-foot`：「**下一步：**」next_step 一段（debug.py:799-801,804） | `.foot`：静态计费说明一行（浅白底）（usage_cards.py:176-177,202） | `.card-footer-bot`：cfb-avatar/「守」字 dot + cfb-name + cfb-label，虚线上边框（templates.py:160-170,236-246） |
| **状态语义色写法** | —（chip 用 accent） | `var(--good)`/`var(--bad)` + warn 字面 `#b07d1a`（debug.py:784-787） | 全字面 hex `#1a9e6c/#b07d1a/#d64545`（usage_cards.py:156-158） | — |

### 1.2 逐字节一致的公共段（真正该抽取的东西）

以下四份拷贝高度一致（Jinja 六模板同源），每份 ~70 行 × 4 ≈ 280 行重复：

1. **`:root` token 块骨架**：`--phase` / wash 四 token / `--wash-blob-1` / `--text-main/sub` /
   `--font-family` / `--r-shell/panel/tile` / 两枚阴影 token——值全部出自 theme_tokens
   （echo.py:2715-2723 ≈ debug.py:737-745 ≈ usage_cards.py:106-114 ≈ templates.py:59-66）。
2. **壳背景 CSS**：145deg wash 渐变 padding-box + 150deg 内高光描边 border-box +
   `box-shadow:var(--mica-shadow)`（echo.py:2729-2733 等）。
3. **漂移色斑族**：`.drift-blobs` + 三 `.drift-blob` + `@keyframes mica-drift-a/b/c` +
   `prefers-reduced-motion` 关停（echo.py:2736-2753 ≈ debug.py:758-775 ≈ usage_cards.py:128-145 ≈
   templates.py:86-133）。
4. **`.glass` 液态玻璃面板**（内高光描边 + `--mica-shadow-soft`）。
5. **相位内联脚本**（随机 `--phase`，失败静默；echo.py:2786-2787 ≈ debug.py:805-806 ≈
   usage_cards.py:204-205 ≈ templates.py:39-42 `_PHASE_JS`）。
6. **失败纯文本兜底链**（铁律 #7）：`render_backend` 不可用/异常 → 空串 → 文本回退
   （echo.py:2829,2863-2864；debug.py:818,863-874；usage_cards.py:216-239；content_parser 渲染失败路径）。

### 1.3 真实漂移点清单（除类名私有化外）

| # | 漂移 | 证据 |
|---|------|------|
| D1 | `.glass` 第一层白 alpha：三卡 `.66` vs media `.68` | templates.py:137 vs echo.py:2755 |
| D2 | accent 命名：`--accent` 系（三卡）vs `--accent` 系（media + Jinja 六模板契约口径） | §1.1 表 |
| D3 | 别名 `--ink`/`--muted` 仅三能力卡有 | echo.py:2720 |
| D4 | usage 状态色字面 hex vs debug 的 `var(--good)/var(--bad)`（同值异写） | usage_cards.py:156-158 vs debug.py:785-786 |
| D5 | 根元素两范式：`stage.card > shell` 双层 vs `card > panel`（`.panel` 不带 card） | §1.1 表 |
| D6 | 四卡壳宽（940/880/900/640）均未入 `CARD_SHELL_WIDTHS` 登记 | theme_tokens.py:84-91 |
| D7 | body 边距微差（echo 多 `padding:0`；media 用 `*` 选择器归零） | echo.py:2725 vs templates.py:45 |
| D8 | accent 解析助手三份私有副本，数学同构（×0.8 clamp）：`echo._resolve_help_accent`（echo.py:2581-2590，走 bridge._darken:263）/ `debug._llm_setup_accent`（debug.py:688-697）/ `usage.usage_card_accent`（usage_cards.py:33-39，走 theme_tokens._darken_hex:108-111） | 已核实 bridge.py:263 ≡ theme_tokens.py:108-111 |

### 1.4 与 rendering-contract 七条铁律的继承对照

| 铁律 | 现状 | 本规格 |
|---|------|--------|
| 1 无 meta viewport | 四卡已满足（44 断言之一） | 壳模板固有，不回归 |
| 2 body 透明 | 已满足 | 同上 |
| 3 字重 ≤700 | 已满足 | 同上 |
| 4 动画在 `.card` 子树内 | 色斑在壳内、壳在 `.card` 内 | 骨架固化此关系 |
| 5 光晕 alpha ≥0.05 | 已满足 | 壳唯一来源后更难破 |
| 6 恰好两枚阴影 token | 已满足且值单一来源 | SHELL_CSS 唯一定义点 |
| 7 失败→纯文本兜底 | 调用方 try/except→空串→文本 | builder 签名/返回不变，链路零改动 |

### 1.5 与 Jinja 对照组的差异本质

finance_card.html 的壳 = 「`:root` 契约 token 块 + 同一 wash 渐变壳 + 色斑 + bot 页脚」，
但 DOM 命名已规范（`shell card` 同元素、`--accent` 口径、宽度入 `CARD_SHELL_WIDTHS` 键 `finance:1080`）。
四处 f-string 卡缺的不是视觉（token 值层已统一），而是**这一层 DOM 命名与装配的规范化**。

---

## 2. 目标架构：三方案权衡（问题 2）

### 2.1 方案 a：四处全部迁 Jinja 模板

做法：`templates/` 新增 4 份模板（help/llm_setup/usage/media）+ `bridge.py` 增 4 个
`render_*_html` + 注册进 `test_rendering_contract.py` 的 `CARD_TEMPLATES` 与
`CARD_SHELL_WIDTHS` 键表（该测试明令显式枚举、禁 glob，test_rendering_contract.py:42-56）；
四个 builder 退化为 payload 组装；`test_mica_builders_contract.py` fixture 改指 bridge 函数。

- 迁移成本：**高**（估算 10-12 代理轮次，见 §7）。4 份模板 + bridge 面扩大 + 两处测试登记 +
  Jinja autoescape 与 `| safe` 边界重新审计（help 的 pills、usage 的 rows 全走上下文）。
- 回归风险：**中**。新失败面：双转义、safe 边界、context 键名笔误、`default()` 兜底字面量。
- 收益：**最大且最远**——rendering-contract §五 checklist 的 gap 刻度/宽度审计/wash default
  断言全自动继承；渲染管线单一（Jinja 一种）。
- 判断：长期正确，但对四张低频卡（帮助/管理员诊断/账单/降级媒体卡）收益兑现慢，与
  「低优先级重构」定位不匹配。

### 2.2 方案 b：Python 侧共享壳函数 `mica_shell()`（推荐）

做法：新增 `domains/render/card_render/mica_shell.py`，持有 `SHELL_CSS`、`ROOT_TOKENS` 模板与
`mica_shell_html(...)`（签名见 §3.2）。四个 builder 的壳段（`:root` 共享 token 块 + 壳 +
色斑 + 玻璃 + 相位脚本）改调它；头部/主体/页脚的 HTML 与私有 CSS 留在各卡，作为
`head_html/body_html/foot_html/extra_css` 实参传入。

- 迁移成本：**低**（估算 5-6 轮）。纯提取重构，输出可与现状逐字节对齐（唯一例外见 D1 参数化）。
- 回归风险：**低**。`test_mica_builders_contract.py` 零改动全绿即为硬门（§4.1）。
- 收益：四份壳 → 一份（~280 行 → ~90 行）；下一张 f-string 卡壳零拷贝；`mica_shell_html`
  的参数面即未来 Jinja context 键面——**不堵死方案 a**，后续升级是机械搬运。
- 缺点（已知取舍）：库内并存两种装配风格（f-string 卡身 + Jinja 解析卡）；gap 刻度/宽度
  审计不自动继承，需测试补（§5）。

### 2.3 方案 c：维持现状，只做 CSS 变量对齐

做法：只修 D1（.68→.66）与 D4（状态色写法）等值层项。

- 成本极低（约 1 轮），收益也极低：D1 是像素级不可感知差异，D4 同值异写无行为差。
  「DOM 各自独立」原状保留，交接件 #4 不成立，下一张卡继续抄 70 行壳。
- 判断：**否决**。其全部价值已被方案 b 的 Phase 0/P5 吸收。

### 2.4 对比与推荐

| 维度 | a 全 Jinja | **b 共享壳（推荐）** | c 只对齐变量 |
|---|---|---|---|
| 迁移成本 | 高（10-12 轮估算） | **低（5-6 轮估算）** | 极低（1 轮） |
| 回归风险 | 中 | **低** | 极低 |
| 消除重复 | 彻底 | **壳层 100%（占重复面 ~90%）** | 无 |
| 交接件 #4 | 解决 | **解决** | 不解决 |
| 升级路径 | 终态 | **保留 a 为可选后续** | 无 |

**推荐 b**，理由：①重复的 90% 集中在壳层，卡身（头部/行/页脚）本就是各卡业务语义，共享收益低；
②成本约为 a 的一半、风险最低且有现成 44 断言做门；③a 的独占收益（autoescape、契约 checklist
自动继承）对此四张低频卡偏低，且 b 的签名设计使 a 日后可机械达成。**本推荐需用户裁决后生效（§8.1）。**

---

## 3. 统一壳规格（方案 b 目标形态）

### 3.1 目标 DOM 骨架（四卡一致，含 media）

```html
<!doctype html>
<html><head><meta charset="utf-8"><style>{ROOT_TOKENS}{SHELL_CSS}{extra_css}</style></head>
<body>
<div class="{stage_cls} card"><section class="shell">
  <div class="drift-blobs" aria-hidden="true"><span class="drift-blob drift-a"></span><span class="drift-blob drift-b"></span><span class="drift-blob drift-c"></span></div>
  {head_html}
  {body_html}
  {foot_html}
</section></div>
<script>try{document.documentElement.style.setProperty("--phase",Math.random().toFixed(4));}catch(e){}</script>
</body></html>
```

- media 卡的 `div.card > div.panel` 并入此骨架（D5 消除）：`panel → shell`，`.card` 上移到根。
- **类名合并（help-shell/setup-shell/panel → shell）安全依据**：截图只 query `.card`
  （render_backends 固定，rendering-contract 铁律 #4）；四卡 PNG 摘要输入均不含 HTML
  （echo.py:2853 `is_admin+body`；debug.py:851-853 `status_label+rows`；usage_cards.py:234
  `request_id+prefix`；content_parser.py:406-415 `canonical_url/title`）——改名不产生缓存副作用。

### 3.2 `mica_shell_html()` 签名（建议）

```python
# domains/render/card_render/mica_shell.py
def mica_shell_html(
    *,
    width: int,                   # 壳宽 px；P5 起必须 ∈ CARD_SHELL_WIDTHS 注册值
    accent: str,                  # #RRGGBB（bot_help_card_color 派生；媒体卡传平台色）
    accent_ink: str,
    stage_cls: str = "stage",     # 根 div 的非 card 类（help-stage/setup-stage 可原样保留）
    head_html: str,               # 已转义装配好的头部段
    body_html: str,
    foot_html: str,
    extra_css: str = "",          # 卡身私有 CSS（原样搬运；禁止再写 :root 共享 token）
    extra_tokens: str = "",       # 卡级 :root 追加（如 debug 的 --good/--bad）
    glass_alpha: float = 0.66,    # media 迁移期传 0.68 保零像素变化；终态统一见 §8.2
) -> str
```

**职责边界**：
- 壳函数负责：doctype/head/style 装配、`:root` 共享 token 块、壳背景/色斑/玻璃/相位脚本、
  根元素 `.card` 契约。纯字符串拼接（相位脚本用普通字符串常量，templates.`_PHASE_JS` 同文迁入），
  **不做任何转义**——实参必须已转义（各卡沿用 `_esc`/`html.escape` 现状），转义职责不上移，
  兜底链因此零改动。
- 卡侧负责：头部/主体/页脚 HTML 与私有 CSS；accent 解析收敛为壳模块单份
  `resolve_accent_pair(color) -> tuple[str, str]`（吸收 D8 三份私有副本）。
- 导入方向：`mica_shell.py` 只 import `theme_tokens`（`derive_wash_tokens`/`BRAND_THEME`/
  `SHADOW_PRIMARY/SECONDARY`/`FONT_FAMILY_STACK`，纯函数无 bridge 依赖）；capability 模块与
  `output/templates.py` 向下 import，无环。沿用四卡现行的函数内延迟 import 风格。

### 3.3 `:root` 兼容别名策略（两步走，治 D2/D3）

- **Phase 1-5（零卡身改动路径）**：壳输出契约口径 `--accent`/`--accent-dark` + 兼容别名
  `--accent`/`--accent-ink`/`--ink`/`--muted`（media 的 `--accent-rgb` 经 `extra_tokens` 保留，
  其规则本未消费该变量）。卡身 CSS 一字不改。
- **终态（可选，独立裁决）**：卡身 CSS 改写为 `--accent` 口径后删除别名。

`bridge._derive_wash_tokens` 历史别名不在本重构中删除（rendering-contract §三明令勿删）；
四卡经壳函数直连 theme_tokens 后不再依赖它，但别名为其余调用面保留。

---

## 4. 迁移步骤与测试门（问题 3）

### 4.1 必须原样保留的既有断言

`tests/test_mica_builders_contract.py` 共 11 个测试函数 × 4 builder 参数化 = 44 项，
**全部原样保留、零改动全绿是 P1-P4 的硬门**。其中四条关键不变量（用户点名 + 契约铁律）：

| 断言 | 不变量 | 对应铁律 |
|------|--------|---------|
| `test_no_meta_viewport` | 无 `<meta viewport>` | #1 |
| `test_body_transparent` | body 透明 | #2 |
| `test_font_weight_at_most_700` | 字重 ≤700 | #3 |
| `test_exactly_two_shadow_token_definitions` + `test_box_shadow_only_tokens` + `test_shadow_token_values_single_source` | 恰好两枚阴影 token 且值单一来源 | #6 |

其余（`test_root_element_has_card_class`、`test_radius_tokens_from_theme`、
`test_font_family_token_from_theme`、`test_text_tokens_from_theme`、`test_glow_alpha_floor`）
同为契约断言，一并保留。**失败纯文本兜底（铁律 #7）**不在该文件内：由各调用方
`_try_render_*` 的 try/except→空串→文本回退承担（§1.2 第 6 条）——迁移中 builder 签名与
返回类型 `str` 不变、壳函数纯拼接不抛异常，兜底链零改动即视为保留。

### 4.2 分阶段步骤（每阶段独立 commit、独立测试门）

| 阶段 | 内容 | 测试门 |
|------|------|--------|
| **P0** | 新建 `domains/render/card_render/mica_shell.py`（~120 行）+ `tests/test_mica_shell.py`：壳函数自身过全部 8 组契约断言 + 防回潮断言（见 §5） | 新测试绿 + 全量 `dev.ps1 test/lint/typecheck` 绿；纯新增无调用方，零回归面 |
| **P1** | echo 帮助卡接线：壳段换 `mica_shell_html`，卡身 CSS/HTML 原样搬 `extra_css`/三段实参 | 44 断言绿 + 全量绿 |
| **P2** | debug LLM 检查卡接线（`--good/--bad` 走 `extra_tokens`） | 同上 |
| **P3** | usage 报告卡接线（status 色写法维持现状，统一见 §8.4） | 同上 |
| **P4** | media 卡接线：`_CARD_CSS` 拆壳/卡身，`__占位符__` replace 链退役，`glass_alpha=0.68` 参数过渡 | 44 断言 + `test_rendering_contract.py` 全绿（media 不在其模板枚举内）+ content_parser 离线 mock 冒烟 |
| **P5**（可选，需裁决 §8） | 宽度登记四键入 `CARD_SHELL_WIDTHS` + mica 侧 gap 刻度断言 + glass_alpha 终态统一 + 别名清理（独立 commit） | 44 断言 + 宽度断言绿 |
| **P6**（可选，更大裁决） | 升级方案 a 全 Jinja 化：`mica_shell_html` 参数面 → Jinja context，机械搬运 | `CARD_TEMPLATES` 注册 + 全套契约 |

每阶段验证命令（遵守源码树零缓存规矩）：

```bash
PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_mica_builders_contract.py tests/test_mica_shell.py -q \
  --basetemp="$TEMP/p-mica" -p no:cacheprovider
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
```

真机验收（**需 bot 重启后**，生产常驻需用户提权重启）：`/bot help`、`/bot help 点歌`（详情形态）、
管理员 `/bot setup llm`、`/bot model usage`、任一解析降级路径出 PNG 目测。

---

## 5. 契约测试的延续与升级

- **延续**：方案 b 下四个 builder 函数名/签名/返回不变 → `test_mica_builders_contract.py`
  的 `_BUILDERS` fixture（:151-156）与全部 44 项断言**原样延续、零修改**；这是 P1-P4 每步的回归门。
- **升级**（P0 落地）：新增 `tests/test_mica_shell.py`，两类断言：
  1. 壳函数自身产出满足现有 8 组断言的同构检查（复用该文件的解析助手逻辑）；
  2. 防回潮：`echo.py`/`debug.py`/`usage_cards.py`/`templates.py` 源文件不再包含
     `mica-drift-a` 等 keyframes 字面与 `--mica-shadow:` 定义（壳唯一来源锁定）——
     防止未来某卡把壳段抄回去。
- P5 若获裁决：mica 侧补 gap 刻度断言（复用 `GAP_SCALE_PX`）与宽度登记断言；
  `test_rendering_contract.py` 的模板显式枚举表不扩（其纪律「禁 glob」保持）。

---

## 6. 风险清单与回滚方式（问题 4）

| # | 风险 | 等级 | 缓解 | 回滚 |
|---|------|------|------|------|
| 1 | 类名合并/别名遗漏导致卡身样式失效（视觉回归） | 中 | 每卡独立 Phase；44 断言 + 真机 PNG 目测；类名不在任何截图/测试选择器依赖内（仅 `.card`） | revert 该 Phase 单个 commit |
| 2 | HTML 转义回归（壳层误转义或漏转义） | 低 | 转义职责留卡侧（现状函数），壳层零转义逻辑；P0 断言覆盖注入样例 | 同上 |
| 3 | 全量测试回归（~1760 用例面） | 低 | 每 Phase 跑全量 test/lint/typecheck | 同上 |
| 4 | PNG 缓存/配额清理行为变化 | 低 | 摘要输入不含 HTML（§3.1 已核实）；`prune_prefixed` 前缀不动 | — |
| 5 | 双装配风格长期并存的债 | 中 | 壳签名按 Jinja context 面设计，P6 可机械升级；本规格显式记为已知取舍 | — |
| 6 | 生产未重启导致新旧实现并存误判 | 低 | 遵守「改码必须重启才生效」铁律；验收窗口由用户掌控 | — |

**回滚总则**：每 Phase 独立 commit（逐文件显式 add，禁 `git add -A`）；`mica_shell.py` 纯新增，
P1-P4 任一回滚 = revert 对应 commit 即恢复该卡 f-string 版本（git 历史全量可溯）；P0 文件无
调用方，可独立删除。

---

## 7. 工作量估算（**估算**，非承诺；1 轮 ≈ 单会话完成「改码 + 实跑测试门」一个完整批次）

| 阶段 | 轮次（估算） | 说明 |
|------|-------------|------|
| P0 壳 + 壳测试 | 1 | mica_shell.py ~120 行 + test_mica_shell.py ~100 行 |
| P1-P3 三卡接线 | 各 1 | 含全量测试实跑 |
| P4 media 接线 | 1-2 | `_CARD_CSS` 拆分最碎 |
| 收尾（HANDBOOK/台账同步） | 1 | 交接规矩 |
| **方案 b 合计** | **5-6** | |
| 方案 a 全 Jinja（对照） | 10-12（估算） | 4 模板 + bridge + 双测试登记 |
| 方案 c（对照，不推荐） | ~1 | 不解决 #4 |

---

## 8. 开放问题（实施前需用户裁决）

1. **方案终裁**：b（本文推荐）vs a vs c。
2. **glass alpha 终态**：统一 `.66`（三卡多数，建议）或 `.68`；P4 迁移期用 `glass_alpha` 参数保
   media 零像素变化，但终态必须二选一。
3. **别名 token 终态**：保留 `--accent` 系别名，或一次性把卡身 CSS 改写为 `--accent` 口径后删别名
   （建议后者，独立 commit）。
4. **状态语义色统一**：usage 的字面 hex 与 debug 的 `--good/--bad` 是否统一为壳级
   `--good/--bad/--warn` 三枚 token（建议统一，经 `extra_tokens` 注入）。
5. **宽度登记**：`help:940 / llm_setup:880 / usage:900 / media:640` 四键是否入
   `CARD_SHELL_WIDTHS`（入表即接受宽度审计断言）。
6. **真机验收窗口**：全部改动需 bot 重启生效（生产常驻、管理员权限启动，重启由用户执行）。
