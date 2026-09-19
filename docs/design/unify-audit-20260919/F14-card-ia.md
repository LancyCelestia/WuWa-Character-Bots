# F14 卡片信息架构审计（卡面骨架 / 信息层级 / 中央装配层）

## 快照声明

- 取证时间：`Sat Sep 19 16:36:22 2026`（本席开工时刻），成文于同日 17:00 前后。
- **本域可能有活跃写者**：F5 席本轮实测 `tests/verify_hashes.py` manifest 在 15:39 被在飞波重录，说明渲染/前端波仍在写盘。本席**全程只读**：未执行任何 `--write`、未启动 playwright/截图/渲染/样张、未跑 pytest（因此未运行任何 python 解释器）、未新建除本文件外的任何文件。
- 因此本文所有 `文件:行号` 均为**上述时间窗的快照坐标**，在飞波可能已使其漂移；引用前请按 §9 给出的 `grep -n` 锚点字符串重定位。
- 工作区：`c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
- 真身目录：`plugins/bot_unified_runtime/domains/render/`（模板 `card_render/templates/`，直拼卡 4 处分驻 `card_render/usage_cards.py`、`domains/render/templates.py`、`domains/chat_reply/capabilities/echo.py`、`domains/ops/admin/debug.py`）；`output/`、`output/card_render/` 为 v21r2 重组后的兼容垫片（`output/card_render/bridge.py:1` 自述 "Compat shim: moved to domains/render/card_render.bridge"）。
- 与其它席的分工边界：**颜色值/rgba/px 数值单源、壳层渐变手抄份数、gate08 黑名单、哈希门缺口 = F5 已交**（`F5-card-render-tokens.md` F5-2/F5-4 已点名 `render_shell` 零生产消费与 `width_px=940` 字面量）。本席只判**装了哪些区、顺序、同一信息的落点与字段命名、未知如何呈现、能力→卡片入参形态**；与 F5 重叠处一律标「→ 见 F5-×」不重复记账。

---

## 0. 一句话裁决（五问五答）

| 问 | 裁决 |
|---|---|
| 卡面有多少？ | **11 面**（7 Jinja 模板 + 4 f-string 直拼卡，与 `docs/rendering-contract.md` 铁律 8「11 面」口径一致），但 `universal_card.html` 一个文件内含**两套互斥骨架**（按 22 个 `page_type` 白名单分支）、帮助卡一个 builder 内含**两套装配来源**（总览用结构化 `sections`／详情用正文反解）→ 实际**骨架变体 13 套**。 |
| 骨架统一吗？ | **不统一**。根容器就有 **5 种范式**（`.shell.card` 单元件 / `.card>.panel` 双件 / `.card.mica-stage>.card>.video-card-shell` 三件 / `.card>pre.mermaid` / `.X.card>section.Y`），另有第 6 种 `mica_shell.render_shell()` 已实现**零生产消费**（→ F5-4）。区段层无任何锁。 |
| 有中央装配层吗？ | **半个**。事实上的中央出卡装配 `render_card_png()` 住在**一个能力**（`domains/link_parse/capabilities/content_parser.py:363`）里，被 8 个能力经**已废弃顶层路径**导入；另有 10 处能力各自内联 `render_backend.render_card({...})` 自拼 viewport/落盘/清理，**两套管线的配额与剪枝策略不同**（F14-6）。 |
| 同一信息同一位置同一语义吗？ | **否**。页脚署名 3 套类名族、标题 5 种来源、时间戳 4 种命名 + 3 面无、来源脚注 1-4 条不一、操作提示仅 4/11 面有且落点三处不同、未知表达 5 种（详 §2、§4）。 |
| 卡片走「说人话/打码」出口吗？ | **不走**。`output/plain_text.py::redact_local_secrets`/`humanize_reply` 只覆盖**文本**（渲染层 `naturalize_chat_text` 更只对 `capability_id=="bot.chat"` 生效），卡片 PNG 在 `renderer.py:207-221` 作为 `media_parts` **原样透传**；卡片内文案唯一保护是 `html.escape`（防注入，不防技术串）。 |

---

## 1. 卡片面穷举清单（11 面 + 变体）

计数命令（本席实跑，只读）：

```bash
ls plugins/bot_unified_runtime/domains/render/card_render/templates/*.html | wc -l   # 7
grep -rln "<!doctype html>" --include=*.py plugins/ | wc -l                            # 5（含 mica_shell 与两个 shim 的文档串，真直拼卡 4 处）
grep -rn "\.render_card(\|render_card_png(" --include=*.py plugins/bot_unified_runtime/domains | wc -l  # 出卡点全集
```

图例：区段顺序 = 该卡 DOM 自上而下的实际装配序；`—` = 该区**不存在**。

| # | 卡面 | 用途 | 构造/渲染坐标（快照） | 根容器范式 | 区段顺序 | 标题来源 | 未知/无数据表达 |
|---|---|---|---|---|---|---|---|
| T1 | `universal_card.html` 分支 A（视频族） | 22 类内容解析通用卡（宽版） | `bridge.py:1317 render_universal_card_html` → `_TEMPLATE.render`；模板 :1179-1229 | `.card.mica-stage > .card > .video-card-shell`（三件，宽度 `calc({{card_width}}/scale)` :1015） | 作者栏(头像+5行) → 平台工具块 → 标题(引号壳) → 封面 → 指标列 → 内容摘要 → 音乐署名 → 热评 → 嘉宾 → 页脚 | payload `title`（:1220） | 区块整体隐藏（`models.py:49` 契约「字段缺失时对应区块整体隐藏」） |
| T2 | `universal_card.html` 分支 B（经典族） | 同上，非 22 类 | 同 :1231-1719 | `.card`（单件，`width:{{card_width}}` :83） | `.header`(5 行 L1-L5) → 正文 → `.footer`(平台名 + bot 胶囊) | payload `title`（:1315） | 同上，且 L1/L2/L4 各有「投影 items」与「硬编码字段」**双路渲染** |
| T3 | `affinity_card.html` | 好感度（群榜 / 私聊双向） | `bridge.py:1656 render_affinity_card_html`；模板 :236-303 | `.shell.card`（单元件） | `.head`(icon+title+subtitle+`.pill`) → `.grid` 瓦片 → 双向 `.panel` → `.rules` → `.foot` → `.bot-foot` | payload `title`，缺省 `'好感度'`（:242） | steps `None→"—"`（bridge :1712）；score 缺省 → **50.0 + tier「友善」**（双向面板）/ `0.0`（榜单行） |
| T4 | `error_card.html` | 能力失败统一诊断卡 | `bridge.py:1767 render_error_card_html` ← `domains/ops/monitor/error_report.py:856`；模板 :172-211 | `.shell.card` | `.head`(`.sigil` 守 + `.head-titles` + `.head-badge`) → `.human` → 触发回显 → 栈摘录 → 触发方法 → 配置快照 → 版本与构建 → 平台与协议 → IDs 与时间 → `.bot-foot` | payload **`card_title`**（别卡叫 `title`），缺省 `'运行异常'` | `.section` 列表为空 → **整区隐藏**；`exc_type` 缺省 `'EXCEPTION'` |
| T5 | `finance_card.html` | 个股/汇率/商品/债券/北向共用壳 | `bridge.py:1530 render_finance_card_html` ← stocks/fx/market(3 topic)；模板 :110-148 | `.shell.card` | `.head`(title+subtitle+`.head-badge`) → `.section`(标题+`.grid` 行[label/sub/value/delta + trend_svg|trend_note]) → `.data-foot`(3 槽) → `.bot-foot` | payload `title`，缺省 `'金融速览'`（bridge :1571） | label 缺省 **`"—"`**（bridge :1560）；行缺 svg → `trend_note` 文案；区块空则丢弃 |
| T6 | `market_card.html` | 全球股指 18 指数 | `bridge.py:1455 render_market_card_html` ← `market.py:742`；模板 :113-154 | `.shell.card` | `.head`(title+subtitle，**无 badge**) → `.group`(组标题+`.grid` 行[name/price/pct/chg + spark|trend_note]) → `.data-foot`(4 槽) → `.bot-foot` | **模板硬编码字面量 `全球股指速览`**（:115，payload 无 `title` 键） | name 缺省 → **`"指数"`**（bridge :1487）；<2 点 → 折线隐藏 + `trend_note` |
| T7 | `song_candidates.html` | 点歌多候选 | `bridge.py:1599 render_song_candidates_html` ← `music.py:654`；模板 :256-284 | `.card > .panel` | `.head`(`.head-left`:title+`.sub` ‖ `.ttl` 有效期 chip) → `.list` 行(num/name/meta) → `.foot` 操作提示 → `.bot-foot` | **模板组句** `找到 {{candidates|length}} 首「{{query}}」相关歌曲`（:260） | name 缺省 → `"未知歌曲"`；query 缺省 → `"未知关键词"` |
| T8 | `mermaid_card.html` | G-MERMAID 流程图 | `bridge.py:1914 render_mermaid_html`；模板 :159-166 | `.card > pre.mermaid` | `<pre class="mermaid">` → `.bot-foot`（**无 .bf-avatar**，`.bf-dot` 内**硬编码「守」**，不随 bot_name） | **无标题区** | **无数据区**（代码原样进 `<pre>`；语法错误由 `wait_js` 判定返 None） |
| D1 | `render_media_card_html`（f-string） | 旧媒体解析卡（通用卡降级器） | `domains/render/templates.py:123-220`（CSS :46-116）← `content_parser.py:447` | `.card > .panel`（`.panel` 才是壳，双件） | 可选 cover-wrap(+`.badge`) → `.body`(title→author→stats→summary→footer) → `.card-footer-bot` | payload `title`，缺省 **`"未命名内容"`**（:131） | 无封面 → 封面区整体折叠；`footer=="about:blank"` → 置空隐藏（:138）；stats 非标量丢弃（:182） |
| D2 | `usage_report_mica_html`（f-string） | 模型用量/账单 | `card_render/usage_cards.py:71-321` ← `usage_monitor.py:673` | **`<div class="stage card">` + `<section class="shell">`** | `<header class="head glass">`(kicker→title→status→window) → `.totals` 8 瓦片 → `<main>` mhead+mrow(+渠道子行) → `.unote` → `.foot` 计费口径 → `<footer class="bot-foot">` | **函数具名参数 `title=`**（非 payload 键） | 费用缺省 **`"未计价"`**（模型行 :149）**vs** `"0.00"`（渠道子行 :135）；缓存率缺省 `"占输入 —"`；`_fmt_int(None)→"0"` |
| D3 | `_help_mica_html`（f-string） | `/bot help` 手册卡（总览/详情） | `domains/chat_reply/capabilities/echo.py:3261-3426` | `<div class="help-stage card">` + `<section class="help-shell">` | `<header class="help-head">`(avatar-wrap→kicker→title→subtitle‖`.help-chip`) → `<main class="help-body">` 网格/单栏 → `<footer class="help-foot">`(tip ‖ `.help-bot-pill`) | **两种来源**：总览 = 结构化 `sections`；详情 = **正则反解正文**（:3294-3313） | 无「未知」区；`.pill`/`.desc` 靠 CSS 省略号截断 |
| D4 | `_llm_setup_mica_html`（f-string） | LLM 接入检查（管理员） | `domains/ops/admin/debug.py:718-816` | `<div class="setup-stage card">` + `<section class="setup-shell">` | `<header class="setup-head glass">`(kicker→title→status→message) → `<main class="setup-body">` 7 行(dot+key+desc+range+value) → `<footer class="setup-foot">` 下一步 | **函数内字面量 `LLM 接入检查`**（:815） | 值缺省 `"（空）"`；key 缺值 `"缺失或占位符"`；**全卡无 bot 署名区** |

**统计：同类区段各有多少套写法**

| 区段 | 套数 | 明细 |
|---|---|---|
| 根容器/外壳 | **5（+1 未接入）** | `.shell.card`×4（T3/T4/T5/T6）｜`.card>.panel`×2（T7/D1）｜`.card.mica-stage>.card>.video-card-shell`（T1）｜`.card` 平铺（T2）｜`.card>pre.mermaid`（T8）｜`stage.card>section.shell`×3 不同类名（D2/D3/D4）｜`render_shell()` 第 6 种，生产 0 消费 |
| 页眉容器类名 | **4** | `.head`（T3-T7,D2）｜`.header`（T2）｜`.help-head`/`.setup-head`（D3/D4，带 `<header>` 语义标签）｜无（T8、D1 把 title 塞进 `.body`） |
| 标题字号 | **6 档** | 19px(D1) / 20px(T4) / 21px(T5,T6) / 26px(D2) / 27-28px(D3,D4) / 30px(T3)；T1/T2 随模板内序 |
| 副标题字段名 | **3** | `subtitle`（T3/T5/T6）｜`.sub` = `platform_name`（T7）｜`header_sub`（D3）；T4 用 payload 不存在的**硬编码串** `RUNTIME DIAGNOSTIC · 泰缇斯系统` |
| 徽章/状态区 | **6 套** | `.pill`(T3)｜`.head-badge`(T4 放**异常类名**、T5 放口径词)｜`.pct/.chg .up/.down/.flat`(T6)｜`.delta.up/.down/.flat`(T5)｜`.status.ok/.warn/.bad`(D2)｜`.setup-status.ok/.warn/.blocked`(D4)；T1/T2/T7/T8/D1/D3 无状态位 |
| 页眉 bot 署名 | **3 套类名族** | `.footer-bot-*` + `.footer-parser-text`（T1/T2）｜`.bot-foot` + `.bf-avatar/.bf-dot/.bf-name`（T3-T8,D2）｜`.card-footer-bot` + `.cfb-avatar/.cfb-dot/.cfb-name/.cfb-label`（D1）｜`.help-bot-pill`+`.help-bot-avatar`（D3）；**D4 = 无**；T8 = 无头像通道 |
| 键值行字段名 | **5** | `label/value`（T4、T5）｜`name/price/pct/change`（T6）｜`k/v`+`mcell`（D2）｜`key/desc/range/value/ok`（D4）｜`item.label/item.value` 投影（T1/T2 `header_l2_items`） |
| 时间戳/新鲜度 | **4 命名 + 3 面无** | `updated_at`+模板前缀「数据时间」(T5/T6)｜`generated_at`+「生成于」(D2)｜`timestamp`/`edit_timestamp`(T1/T2)｜`id_pairs` 里的「IDs 与时间」行(T4)｜**无**：T3/T7/T8/D1/D3/D4 |
| 来源/口径脚注 | **1-4 条不等** | T6 `source_note+数据时间+delayed_note+crosscheck_note`（4）｜T5 同前 3（`crosscheck_note` **在 finance 通道被静默丢弃**——`render_finance_card_html` 不读该键）｜T3/T7/D2/D3/D4 各 1 条模板内硬编码文案｜T1/T2/D1/T8 无来源区 |
| 操作提示（CTA） | **仅 4/11 面** | T7 `.foot` 独立区｜D2 混在 `.foot` 计费说明里｜D3 头部 `.help-chip` + 页脚 `.tip` 两处｜D4 `.setup-foot`「下一步：」；余 7 面无 |
| 「未知/无数据」表达 | **5 法** | 显式中文词（`未知歌曲`/`未知关键词`/`未命名内容`/`未计价`/`（空）`）｜全角破折号 `—`（T5 label、T3 steps、D2 缓存率）｜**整块隐藏**（T1/T2/T4/D1）｜数字 `0`/`0.00`（D2 `_fmt_int`、渠道子行费用）｜与真值同形的默认数（T3 score `50.0`+tier「友善」、T6 name「指数」） |

---

## 2. 骨架统一性判定（对照两份规格）

### 2.1 f-string 卡与 Jinja 模板卡还剩几处 DOM 不一致

`docs/design/fstring-card-dom-spec.md`（状态行仍为「**本规格未实施，实施前需用户裁决**」，日期 2026-09-13）的 D1-D8 漂移清单，逐项对今晨快照复核：

| 规格项 | 今晨实况 | 判定 |
|---|---|---|
| D1 `.glass` alpha 分叉 | 已由 `theme_tokens.GLASS_MAIN/FOOT` 单源 | 已收（值层，F5 域） |
| D2/D3 accent 家族与 `--ink/--muted` | `render_root_tokens` 全卡同发；`test_mica_builders_contract.py:424 test_media_card_gained_missing_public_tokens` 锁定 | 已收 |
| D4 状态色字面 hex | 仍直写（`usage_cards.py:255-257` `#2e9e6b/#b07d1a/#d54941`；`debug.py:796-798` 混用 `var(--good)`+字面 `#b07d1a`） | → 见 F5-3（值域） |
| **D5 根元素两范式** | **仍全开且更扩散**：实测 5 种范式（§1 表），规格的 2 种已过时 | **未收，本席主案（F14-1）** |
| **D6 四卡壳宽未入册** | 名义已入 `CARD_SHELL_WIDTHS`（`theme_tokens.py:93-99` C10），**但四处调用仍传字面量** `shell_base_css(..., width_px=940/900/880/640)`，函数本身不查表（`mica_shell.py:371-398` 只收 `width_px` 形参，默认 `_DEFAULT_SHELL_WIDTH px=880` 亦为私有字面量） | **实质未收**（→ F5-4 已点 width_px；本席补「登记表非事实来源」的 IA 后果，F14-5） |
| **D7 body 边距/文档层各写一份** | 仍全开：`echo.py:3376`（含 `padding:0`）/`debug.py:783`（**无 `padding:0`**）/`usage_cards.py:240`（无）/`templates.py:46-65`（`*{margin:0;padding:0}`）+ `render_shell` 第 5 份 + 7 模板各自 `body{}` = **同一 body 规则 12 份手写** | **未收**，`render_shell` 未接入所致（F14-2） |
| D8 accent 解析三份私有副本 | 仍在：`echo.py:3220 _resolve_help_accent(str)`｜`debug.py:705 _llm_setup_accent(Config)`｜`usage_cards.py:39 usage_card_accent(Config)`，前二者走 `bridge._darken`、第三者走 `theme_tokens._darken_hex`，**签名不同类、加深函数不同** | **未收**（本席 F14-4；值等义性由 F5 判） |
| 规格的 `*{box-sizing}` | `echo/debug/usage` 三份一致 `box-sizing:border-box`；`templates.py:47` 多带 `margin:0;padding:0`；7 模板各自为政 | 未收（并入 F14-2） |
| 规格的 `<title>` 文档标题 | 仅 `render_shell`（零消费）会写 `<title>`；**11 面全部无 `<title>`** | 未收（并入 F14-2） |

**净结论**：值层已通水，**结构层零进展**；规格的 D5/D7/D8 + `<title>` 四项 100% 保持原状，D6 只做了「登记不接线」。

### 2.2 同一信息在不同卡里位置/标签/有无不一致（用户要的「统一参数」落点）

| 同一信息 | 不一致实况（可直接落手核对） |
|---|---|
| 卡片标题 | **5 种来源**：payload `title`（T3/T5/T1/T2/D1）／payload **`card_title`**（T4）／函数具名参数（D2）／模板硬编码字面量（T6 `全球股指速览`、D4 `LLM 接入检查`）／模板组句（T7）。能力无法改 T6/T8/D4 的标题（T8 干脆无标题区）。 |
| 「这是哪个功能」署名 | 3 套类名族 + 1 处无（§1 表）；`· ` 分隔符在三族里各硬写一遍（`universal:1227`、`templates.py:204`、`bridge` 各模板 :`<span>· {{feature_label}}`），D2 里 `<span>· {feature_label}</span>` **连类名都没有**。 |
| 数据时间 | 标签前缀写在模板里（`数据时间 {{updated_at}}` T5/T6 vs `生成于 {{generated_at}}` D2），T3/T7/T8/D1/D3/D4 **无该位**；T1/T2 的发布时间在**作者栏第 5 行**而非脚注区。 |
| 来源/口径 | 同为「来源说明」：T6 用 4 个 payload 键并排 `.data-foot`；D2 用**函数体内硬编码整句**（`:318`）；T3 用**模板内硬编码整句**（`:94`）；T7 用模板内硬编码 CTA 兼口径；T1/T2/D1 **只印一条 URL 或什么都不印**。 |
| 状态/徽章 | 同位异义：T4 的 `.head-badge` 印 **Python 异常类名**，T5 的 `.head-badge` 印 **中文口径词**（`延迟行情`），同名同类同位置。 |
| 走势线 | 三种机制：T6 = payload `trend=[float]` 交 `bridge._spark_points`（128×40，`bridge.py:1430`）；T5 = payload `trend_svg` **能力直出 SVG 串**经 `|safe`（`bridge.py:1527` 正则放行 + 模板 :126）；T5 箱形 = `chart.svg`。且 `_trend_svg_safe`(market.py:283)/`_trend_svg`(stocks.py:219)/`_spark_points`(bridge.py:1430) 是**同一视觉语义的三份实现**（F14-7）。 |
| 「未知」 | 5 法（§1 末行）；同卡内亦不统一（D2 模型行「未计价」vs 渠道子行「0.00」）。 |
| 截断 | 6 处 CSS 各自为政：`.footer-media-id`、`.mcell`、`.cname`、`.pill`(max-width:62%)、`.label`/`.name`、`error .value{word-break:break-all}`、仅 D3 有 `-webkit-line-clamp:2`。**PNG 不可滚动 → 省略号即静默丢信息，且无「内容已截断」披露位**。 |

### 2.3 `templates.py` 的 UNKNOWN/派生兜底在卡片上如何呈现（只判呈现，不判色值）

- 该文件 :143-145 以**字面量** `"#607080"/"#4a5866"/"96,112,128"` 复刻 `theme_tokens.UNKNOWN_PLATFORM_COLOR`（:29）——是否引常量属 F5 值域；本席只判：**未知平台在 D1 媒体卡上呈现为一张完全正常、带品牌色与本命洗的卡，无任何「来源未知」可辨痕迹**，与 `rendering-contract.md` §三「未知平台…不臆造」的精神只做了一半（不臆造数据，但**臆造了「这是一张已识别平台的卡」这一事实**）。
- 更硬的呈现缺口：`models.py:49` 把「缺字段 → 区块整体隐藏」写成契约。缺数据的卡与「该类型本就无此区」的卡**像素级同形**，用户在 QQ 里无法区分「上游没取到」与「这个平台没有播放数」。这是「绝不编数」原则的镜像风险：**没编数字，但编出了「完整性」**。T1 分支 A 尤甚（指标条 `{% if stats_bar_items %}`）。
- `badge_text = feature_label or platform`（:171-177）：注释自认「裸平台键如 `eat` 无意义」，兜底仍是裸 `platform` 键 → `feature_label` 传空时**英文小写枚举直接上徽章位**。

---

## 3. 能力 → 卡片的数据契约（入参形态统计）

### 3.1 六种入参形态（同一「卡片」概念，六种调用面）

| 形态 | 机制 | 使用者 | 结构校验 |
|---|---|---|---|
| P1 dataclass 投影 | `ParsedContent → RenderPayload(**)`，`_render_payload_from_data`+`_coerce_field`（bridge:1244）按**当前值类型**猜型归一，再 `to_dict()` 全量进 Jinja 上下文 | T1/T2（唯一） | 有（缺省值兜底） |
| P2 桥层具名 kwargs | 自由 dict 进 `render_*_html`，bridge 逐键手工归一，**以显式关键字实参**渲染模板 | T5/T6/T7/T3/T4（5 面） | 有（白名单归一，**未声明键静默丢弃**） |
| P3 直拼 dict | 能力自拼 dict 交 builder，builder 内 `payload["x"]` 直取、无归一层 | D1（`card_payload_from_parse` 产物）、D4（`_llm_setup_*`） | **无** |
| P4 直拼具名参数 | `func(config, *, kicker, title, totals, model_rows, ...)` | D2（唯一） | 参数表即契约 |
| P5 结构化 + 文本反解 | `sections: list[tuple[str, list[tuple[str,str]]]]` **或** `body: str` 正则反解 | D3（双模） | **无**（反解靠 `【】`/`总览`/`：` 字面） |
| P6 裸字符串 | `render_mermaid_html(code: str)` | T8 | 无 |

→ **「sections」这个词在两个面上指两种互斥结构**：T5 = `list[dict{name,rows}]`，D3 = `list[tuple[str, list[tuple[str,str]]]]`。这是「统一参数」最尖锐的一处反例。

### 3.2 字段同义异名表

| 语义 | 出现的字段名 | 坐标 | 判定 |
|---|---|---|---|
| 主色入参 | `platform_color`（T1-T2、T4-T7、D1）／**`pc`**（T3） | `bridge.py:1671 pc = _as_str(data.get("pc"))` vs 其余 `data.get("platform_color")` | **`--pc` 家族已按 2026-09-18 裁定退役，但**能力→桥层**的入参名仍是 `pc`；`mica_shell.py:316-319` 的退役声明只覆盖 CSS token 层 |
| 分组 | `groups=[{name,rows}]`（T6）／`sections=[{name,rows}]`（T5）／D3 `sections=[tuple]` | `bridge.py:1471 / :1543`、`echo.py:3268` | 三词一义，两种结构 |
| 行标题 | `label`（T5/T4）／`name`（T6）／`key`（D4）／`who`+`name`（T3）／`k`（D2 瓦片） | 模板 :81/:122/:110、`debug.py:806` | 五词一义 |
| 行说明 | `sub`（T5）／`desc`（D4）／`.sub`(T7 平台名)／`subtitle`（页眉） | | 四词，且 `sub` 在同卡内既指行说明又指页眉副题（T7） |
| 值 | `value`（T4/T5/D4）／`price`（T6）／`v`（D2）／`stat_items`（D1） | | |
| 涨跌语义 | `cls`（T5/T6，**bridge 侧由 `change_pct` 反推**，能力传的 `cls` 被忽略：`bridge.py:1489-1493`）／`delta.cls`／D2 `cost unpriced`／D4 `dot.ok/.bad` | | 同名 `cls` 在 T5 被尊重、在 T6 被覆写 |
| 走势 | `trend`(数列)/`trend_note`（T6）vs `trend_svg`(HTML 串)/`trend_note`（T5） | `bridge.py:1487 / :1558` | 一「数」一「标记」两范式 |
| 状态词 | `status_label`+`status_kind`（D2/D4）vs `badge`（T5）vs `pill`（T3）vs `head-badge`（T4=异常类名） | | `status_kind` 三档取值两卡不同：`ok/warn/bad`（D2）vs `ok/warn/**blocked**`（D4），**而 D4 自己行内圆点又用 `ok/bad`**（`debug.py:749`）——同卡三态两套第三值名 |
| 未知成本 | `"未计价"`（模型行）vs `"0.00"`（渠道子行） | `usage_cards.py:149 / :135` | 同卡同义两形 |

### 3.3 「没有中央装配层」的具体点（本席独占结论）

1. **中央出卡装配住在能力里**：`content_parser.py:363 render_card_png()` 是事实上的共用管线（天气/菜谱/点歌/占卜/订阅 Epic/历史上的今天/内容解析 共 8 个消费方），却：① 位于 `domains/link_parse/capabilities/` 而非渲染域；② 8 个消费方**全部经已废弃顶层路径** `plugins.bot_unified_runtime.capabilities.content_parser` 导入（`divination.py:595`、`eat.py:520`、`weather.py:269`、`music.py:548`、`epic.py:66`、`today_history.py:189`、`render_projection.py:153`、`console_chat.py:33`）。
2. **另一条并行管线**：10 处能力内联 `render_backend.render_card({...})` 自拼 viewport+落盘+digest+剪枝（market×2、fx、stocks×2、music、affinity、echo、debug、usage、error_report）。两套管线的差异不是风格而是**策略**：Path A 有 `enforce_quota`（按字节配额，`content_parser.py:360`），Path B 只有 `prune_prefixed keep=120/200`（按条数），**usage/debug/error 三处连条数剪枝都没有**（F14-6）。
3. **卡片选择规则在能力里**：`render_card_png` 内以 23 个平台键的硬编码集合 `universal_platforms`（:390-395）+「有无 detail 扩展区块」决定这张内容走 T1/T2 通用卡还是 D1 媒体卡。骨架派发无注册表、无中央决策面。
4. **文档层各自为政**：11 面各自手写 `<!doctype>`/`<head>`/`<style>`/`body{}`/`.card{}`，`mica_shell.render_shell()`（:401-447，铁律内建、带 `<title>`）**生产零消费**（→ 与 F5-4 同一事实，本席补 IA 后果：下一张直拼卡仍需手抄 12 处）。
5. **HTML 直出自能力层**：T5 的 `trend_svg` 由能力生成整段 `<svg>` 串、桥层只做 `^<svg…</svg>$` 形状放行、模板 `|safe` 注入；D3 帮助卡的 `.pill`/`.desc` 亦在 builder 内手拼。渲染域没有「图元→卡片」的中间表示层。
6. **导入面三条路径混用**：`output.card_render.bridge`（6 能力）、`output.templates`（music/content_parser）、`domains.render.card_render.*`（echo:3280、debug:727、usage_cards:23、templates.py:34）——**同一文件内混用**（`echo.py:3222` 走垫片、`:3280` 走真身）。

---

## 4. 文案与人话层（统一消息的出口面）

### 4.1 出口覆盖事实

- `renderer.render_reviewed_output` 的自然化只对 `is_chat`（`capability_id=="bot.chat"`）生效（`renderer.py:191/197-198`），`redact_local_secrets` 在渲染层**一次都不调**；卡片以 `result.images` 进 `media_parts` **原样透传**（:207-209）。
- 结论：**卡片图上的文字不经「说人话/打码」出口**。唯一逐字段脱敏的是诊断卡自己（`error_report.py:352/373/447/695` 四处显式 `redact_local_secrets`）——它是 11 面里唯一自觉接入的，其余 10 面靠「数据本来就来自上游接口」这一假设。

### 4.2 技术串上屏违规点（实测计数：**8 条**，其中 1 条值域已穷举证实可触发）

| # | 面:坐标 | 上屏内容 | 定性 |
|---|---|---|---|
| 1 | T4 `error_card.html:179` | 副标题**英文技术串字面量** `RUNTIME DIAGNOSTIC · 泰缇斯系统` | 违反去 AI 味/守岸人语气；同卡其余区全中文 |
| 2 | T4 :180 | 徽章位印 **Python 异常类名**（`exc_type`，缺省 `"EXCEPTION"`） | 该位他卡印中文口径词；对管理员是有用的，但位置语义与他卡冲突 |
| 3 | **D4 `debug.py:842`** | `_LLM_SETUP_NEXT_ACTIONS.get(next_action, next_action)` 未命中即**原样印 snake_case 枚举** | **已证可达**：值域 9 个（`fix_python_environment/fix_config/fix_context/fix_chat_pipeline/fix_llm_provider/fix_nonebot/fix_transport/configure_real_llm/llm_smoke`，见 `smoke.py:2653-2681`），表内仅 3 个 → **6 个值会在「下一步：」后裸出** |
| 4 | D4 `debug.py:833` | 状态位同理 `(status_key or "未知状态", "warn")` 原样兜底 | 潜伏：当前 3 个生产值全映射（`smoke.py:1960-1964`），故**暂不可触发**，P3 |
| 5 | D1 `templates.py:240` | `footer = flat["canonical_url"]` → 图片上印**裸 URL**（不可点） | 同信息在 T1/T2 是 `<a>`（同样不可点）或直接不显 |
| 6 | D1 :172 | 徽章 `feature_label or platform` → 裸平台键 `eat`/`weibo` 级英文 | 注释自认无意义，兜底未修 |
| 7 | D2 :310 | 「统计口径」瓦片**恒显 `"按调用时价格"`**，且 `style="font-size:13px"` 内联硬压字号 | 该位是数据槽，写的是常设文案 |
| 8 | T1 :1217 | `data-platform-technical="{{platform_official_name}}"` 属性名自陈「技术串」 | 不上屏，仅 IA 气味；P3 |

### 4.3 卡片侧造数点（对照「绝不编数」）

| 点 | 坐标 | 事实 | 判定 |
|---|---|---|---|
| 好感度双向面板缺数即画真值 | `bridge.py:1678-1682`（`_pair`：score 缺省 50.0、tier 缺省「友善」、bar 取 score） | 私聊卡缺 `bot_to_user` → 卡上出现 **50.0 + 半条进度棒 + 「友善」**，与真实测量不可辨；`50.0` 亦非项目基准（AGENTS.md：基准 10=档0） | **P1**（`rendering-contract.md:99` 已把 50.0 写成既定归一策略，故非「无人知」，而是**该策略在卡片呈现面上等价于造数**；同文件同段又为 steps 选 `"—"`——同卡两策略） |
| 用量 `_fmt_int(None)= "0"` | `usage_cards.py:62-68` | 缺键/脏值 → 画 `0`，`0` 是合法 token 数 | **P2**（同卡费用位已用「未计价」，证明作者知道该区分，只是没覆盖 token 位） |
| 渠道子行费用 `or "0.00"` | `usage_cards.py:135` | 未计价渠道画 0.00 元 | **P2**（与 :149「未计价」同卡冲突） |
| 股指行名缺省「指数」/金融 label 缺省「—」 | `bridge.py:1487 / :1560` | 一真值形、一破折号 | P3（不造数，只不一致） |
| 汇率缺数行 | `fx.py:113-118` | 把「暂无数据」塞进 `label`、缺数说明塞进 `value`，`cls:"flat"` | 诚实（有文案），但**语义挪用**：label/value 被当标题/正文用 | P3 |
| mermaid/未知平台 | T8、D1 | 无「未知」标记 | P2（§2.3） |

---

## 5. 降级与失败形态覆盖表

| 面 | bridge/builder 对空 payload | 后端不可用 | 渲染异常/空图 | 落盘后清理 | 结论 |
|---|---|---|---|---|---|
| T1 universal | 不抛（`test_rendering_contract.py:551`） | `render_card_png` 返 None | try→None | `enforce_quota`（按字节） | ✅ 完整 |
| T2 universal-B | 同上（同函数） | 同 | 同 | 同 | ✅ |
| T3 affinity | 不抛（:577 脏数据 5 例） | `affinity.py:271` 返 "" | :302 返 "" | `prune_prefixed keep=200` | ✅ |
| T4 error | 空 payload 契约 | 后端 None→`build_text_fallback` | :897 返 ""→文本 | **无** | ⚠ 兜底✅、配额❌ |
| T5 finance | 不抛 | stocks/fx/market 三处各自 "" | "" | `keep=120` | ✅（文本兜底）|
| T6 market | 不抛 | `market.py:669` 段 "" | "" | `keep=120` | ✅ |
| T7 song | 不抛 | `music.py:624` 返 None | :664 返 None | `enforce_quota`（music.py:393） | ✅ |
| T8 mermaid | n/a（str 入参） | `_MERMAID_BACKEND=None`→`render_mermaid_png` 返 None | 重试预算 :1833 | 无（不落卡目录） | ✅ 代码块原样回文本 |
| D1 media | 不抛 | 共用 `render_card_png` | 同 | `enforce_quota` | ✅ |
| D2 usage | n/a | `usage_cards.py:333` 返 "" | :354 返 "" | **无 prune、无 quota** | ⚠ 兜底✅、**卡片目录无界增长**❌ |
| D3 help | n/a | `echo.py:3468` 返 "" | 返 "" | `keep=200` | ✅ |
| D4 debug | n/a | `debug.py:828` 返 "" | 返 "" | **无** | ⚠ 兜底✅、配额❌ |

**铁律 7 判定**：12/12（含两分支）**纯文本兜底成立**——`rendering-contract.md` 铁律 7 的「契约零破坏」在本域**没有发现破口**（正面结论）。缺口全在**兜底之后**：三处（T4/D2/D4）出卡不落配额、且冷却文案假定「卡已发出」。

**错误卡分区与宣称对照**：AGENTS.md 台账 #31/命令面宣称「人话区/回显/栈摘录/配置快照/IDs」**五段**，模板实为 **人话区 + 7 个 `.section`**（触发回显/栈摘录/触发方法/配置快照/版本与构建/平台与协议/IDs 与时间）+ 页脚 help_text。宣称**少列 3 段**（触发方法/版本与构建/平台与协议），help_text 未提。→ 文档欠陈（F14-9），非代码缺陷。

**冷却降级的可行动信息**：`_COOLDOWN_LINES` 12 句**每句都断言「细节都在刚才那张卡上」**（`error_report.py:88-104` 注释自认「每句都指回刚才那张卡」），而闸机 `allow()` 在 `:1111` **发卡之前**记账；若首发的卡渲染失败走了 `build_text_fallback`，则 60s 内的第二句在**谎称存在一张用户从未收到的卡**，且不再复述 `_FALLBACK_HELP_TEXT` 里的重试指引。→ **P2**（信息缺失 + 虚假指称各一处）。
同处第二发现：冷却用 `random.choice`（:973），人话区用**会话游标轮换**（:337 `_HUMAN_CURSOR`）——同一「池+游标」范式两套实现。P3。

---

## 6. 尺寸与密度

### 6.1 宽度：**登记表面、字面真相**（三源）

`CARD_SHELL_WIDTHS`（`theme_tokens.py:85-99`）11 键。实际消费方式：

| 面 | 登记值 | 出卡宽度的真正来源 | 一致？ |
|---|---|---|---|
| T1/T2 universal | 1440 | **payload `card_width`**（`models.py:153` 默认 `"1440px"`；模板 :83 直插、:1015 `calc()/zoom`），**不经登记表的 zoom 语义** | 值等，源不同（契约 §四自认「payload 驱动」= 承认双写） |
| T3 affinity | 1180 | 模板内 CSS 字面量 | 等值 |
| T5/T6/error | 1080 | 模板内 CSS 字面量 | 等值 |
| T7 song_panel | 980 | 模板内字面量（**外层 `.card` fit-content 另计**） | 等值 |
| T8 mermaid_max | 840 | `fit-content` 上限（不是壳宽） | 语义与他面不同（**第 N 档：这根本不是壳宽档，是同名列**） |
| D1-D4 | 640/900/880/940 | `shell_base_css(..., width_px=<字面量>)`，**未 import 登记表**（`templates.py:73`、`usage_cards.py:233`、`debug.py:776`、`echo.py:3369`） | 等值，改表不跟随 |
| `mica_shell._DEFAULT_SHELL_WIDTH_PX` | — | **私有 880 字面量**（`mica_shell.py:85`），与 `debug` 同值同义却不同源 | 第 12 档（未登记的缺省壳宽） |

→ 「有没有第 N 档」答案：**有，两类**：① `_DEFAULT_SHELL_WIDTH_PX=880` 未登记；② `mermaid_max` 与壳宽不同语义却同表；③ T1 的 `card_width/zoom` 第三机制。改 `CARD_SHELL_WIDTHS` 一个值，最多 4 面跟随（经 `shell_base_css` 传参的调用点全是字面量 → 0 面跟随），gate06/`test_rendering_contract.py:713-724` 会红——**测试用字面量二次硬编码登记值**，把「双写」升级为「三写」（登记表 + 调用实参 + 断言）。

### 6.2 截图 viewport：第二套宽度，7 档，与壳宽无规则

| 面 | 壳宽 | viewport | 余量 |
|---|---|---|---|
| universal | 1440 | 1504×1000 | +64（`content_parser.py:430` 注释写「1504 = 1440 + 56」——**自身算术不通**，28×2=56≠64） |
| affinity | 1180 | 1240×1400 | +60 |
| market/finance/error | 1080 | 1160×1400/1600/1800 | +80 |
| song | 980 | 1040×900 | +60 |
| help | 940 | 1040×1200 | +100 |
| usage | 900 | 950×1000 | +50 |
| debug | 880 | 940×1000 | +60 |
| mermaid | ≤840 | 840×640 | 0 |
| **media** | 640 | **不传** → 后端缺省 | 两后端两套缺省：`render_backends.py:393` `{640,400}` vs `:582` `{672,480}` —— **同一张卡在两个后端下差 32px**（640 档正好贴边，阴影/色斑可能被裁） |

→ 余量 0/50/60/64/80/100 **六档无规则**，且 viewport 与壳宽的关系（安全余量/阴影外扩）**没有单点定义、没有登记、没有断言**。这是「统一参数」在尺寸轴上的完整缺口。

### 6.3 长文本三种出口：选择规则是单点，卡片截断不是

- 单点部分（✅ 正面）：文本侧「chunks vs 合并转发」集中在 `renderer.py`（`split_text_chunks` :286、`should_forward_long_text` :376、`should_forward_by_node_count` :387），阈值经 `config.bot_render_forward_min_chars=1500` 与 `node_chars=900/min_nodes=4` 参数化，用户口径注释在 :396。
- 非单点部分（❌）：**「这条内容进卡后被 CSS 截断」与上述规则互不知情**——卡片只知自己宽（§6.1），能力层按文本长度决定分片/合并，两者无共享预算；`.mcell`（模型名 6 列 grid）、`.pill`（命令名 62% 上限）都在 PNG 上被省略号吃掉且**无「已截断」披露**。
- 图表位与文字区冲突：T6 `spark`(128×40) 与 T5 能力直出 svg 与 `.info`（`nowrap+ellipsis`）同行 flex，长名先被截；D2 8 瓦片塞 `repeat(4,1fr)` 两行，「统计口径」瓦片被迫内联降到 13px。规则各卡自定，无「图占几列/文字几列」登记。

---

## 7. 锁与文档

### 7.1 三个契约测试里有没有结构锁？——**裁决：一条都没有（除根类名）**

| 测试件 | 断言主题（逐节） | 结构/命名类断言 |
|---|---|---|
| `tests/test_rendering_contract.py`（13 节，:162-786） | viewport 禁令/body 透明/字重/阴影族值/半径-宽度-gap/wash/动画作用域/光晕 alpha/PLATFORM_THEMES 注册表/空 payload 不抛/脏 payload 不抛/文档存在/CORE 值册逐字符/导出面 | **0 条**区段结构与字段命名。最接近的是 §10「失败→纯文本兜底」（行为）与 :273 宽度审计（值） |
| `tests/test_mica_builders_contract.py`（10 节） | 同上 + **:204 根元素带 `.card` 类** + :400 公共 token **顺序**统一 + :408 四 builder 公共段逐字符相同 | **1 条**（根类名）。:400 **证明「顺序锁定」技术存在**，却只用于 CSS 声明序，未用于 DOM 区段序 |
| `tests/test_v21r3_visual_gates.py`（门 01-09 × 11 面） | 半径登记制/色斑三枚/行高/字号/gap/壳宽登记/字体两栈/禁表外 hex/玻璃档 | **0 条** |

**结论**：`test_public_token_subset_and_order_unified` 锁住了「CSS 变量声明顺序」，**没有任何一条锁住「卡片区段顺序 / 区段存在性 / 载荷字段命名」**。「骨架不统一完全无锁」——一句话成立。页脚署名区存在性仅有 1 面对象锁（`test_mica_builders_contract.py:357` 只测 usage 自己），D4 无署名、T8 无头像通道**测不出来**。

### 7.2 应改文档（before→after，本席不改，交主会话）

**(a) `AGENTS.md:108`（功能表 · 卡片渲染行）**
- before：`| 卡片渲染 | output/card_render/ | 釉瑚云母卡片（见第三部分渲染管线；6 Jinja 模板 + 4 处 f-string 直拼卡全部走 theme_tokens 契约） | 随各能力 |`
- after：`| 卡片渲染 | domains/render/card_render/（兼容垫片 output/card_render/，其 templates/ 现为空目录） | 釉瑚云母卡片（见第三部分渲染管线；7 Jinja 模板 + 4 处 f-string 直拼卡 = 契约口径 11 面，全部走 theme_tokens 契约；骨架/区段未统一，见 docs/design/unify-audit-20260919/F14-card-ia.md） | 随各能力 |`
- 证据：`ls .../card_render/templates/*.html | wc -l` → 7；`head -1 output/card_render/bridge.py` → "Compat shim: moved to domains/render/card_render.bridge (v21r2 reorg W13 render)"；`ls -d output/card_render/templates/` → 存在且为空（2026-09-18 03:17）。

**(b) `AGENTS.md:91`（渲染管线段，同段双处之一）**
- before：`**渲染管线**：`output/card_render/` 云母+液态玻璃+釉瑚渐变漂移。**token 单一事实来源 `theme_tokens.py`**（BRAND 本命色/PLATFORM_THEMES 17 平台显式注册表+别名/两枚阴影 token/半径 30-18-14/宽度登记表/间距刻度；…）`
- after：`**渲染管线**：`domains/render/card_render/`（兼容垫片 `output/card_render/`）云母+液态玻璃+釉瑚渐变漂移。**token 单一事实来源 `theme_tokens.py`**（BRAND 本命色/PLATFORM_THEMES 显式注册表+别名/**三级阴影族 `SHADOW_CSS_VARS`（--mica-shadow/--mica-shadow-panel/--mica-shadow-soft）**/半径 30-18-14 + 内径刻度 {4,6,8,12,16}/宽度登记表 `CARD_SHELL_WIDTHS`（**11 面调用点仍传字面量，未真正消费**）/间距刻度/行高刻度/色斑 3 枚；…）`
- 证据：`theme_tokens.py:167-184`（SHADOW_LEVELS/SHADOW_CSS_VARS 3 键）+ 契约 §四「阴影…三级族」。

**(c) `AGENTS.md:172`（台账 #26 内「6 Jinja 模板与 4 处 f-string 卡」）** — 历史账条目。建议**不改数字**（该句记的是 09-13 当时事实），在其后补一句：`（2026-09-13 后 error_card.html 加入，模板面现 7 张；契约口径 11 面，见 docs/rendering-contract.md 铁律 8）`。

**(d) `docs/rendering-contract.md:78`（§五 接入步骤第 2 条）—— 契约自身在合法化分叉**
- before：`2. 根元素**必须**带 `card` 类（`<div class="shell card">` 或 `<div class="card">`）——截图选择器契约。`
- after：`2. 根元素**必须**带 `card` 类（截图选择器契约）。全项目**唯一允许**一种装配式：`<div class="card {stage}"><section class="{shell_class}">…</section></div>`，由 `mica_shell.render_shell()` 产出（`shell_class=""` 时退化为单层）。`<div class="shell card">`（同类双名并挂）与 `<div class="stage card">` 为**待迁形态**，新卡禁用。`
- 理由：现文一句里并列两种根元素 = 契约主动放行 5 范式分叉。

**(e) `docs/rendering-contract.md:77`（§五 第 1 条 = 「复制文件」）—— 装配层缺失被写进流程**
- before：`1. 复制 `market_card.html` 的 `:root` 结构作为起点（它是最小完整样例…）。`
- after：`1. 新 Jinja 卡以 `bridge._card_root_tokens(...) + _vis4_context() + blobs_html/decor_css 上下文键` 为唯一起点（照 `finance_card.html` 的上下文消费法），**不得复制任何 CSS 声明**；f-string 卡一律经 `mica_shell.render_shell()` 装配文档层与外壳。`
- 证据：`shell_base_css`/`mica_decor_css`/`render_root_tokens` 已是生成器，`render_shell` 是整文档装配件（`mica_shell.py:401-447`）却无消费者（§3.3-4）。

**(f) `docs/design/fstring-card-dom-spec.md:3`（状态行过时）**
- before：`> **状态：设计规格（本规格未实施，实施前需用户裁决）。**`
- after：`> **状态（2026-09-19 复核）：部分实施。** 值层与 CSS 生成器层（`render_root_tokens`/`shell_base_css`/`mica_decor_css`/`drift_blobs_html`）**已接入 4 卡**；**DOM/文档装配层（`render_shell`）、根元素范式统一（规格 D5）、body/文档头统一（D7）、accent 解析三副本（D8）、宽度按表消费（D6 实质项）四项未实施**，仍待用户裁决。剩余差异与结构锁缺口见 `unify-audit-20260919/F14-card-ia.md` §2.1/§7.1。`
- 并修该规格 §0 表的 4 处失效坐标：`capabilities/echo.py:2622-2787`→`domains/chat_reply/capabilities/echo.py:3261-3426`；`capabilities/debug.py:700-806`→`domains/ops/admin/debug.py:718-816`；`output/card_render/usage_cards.py:51-205`→`domains/render/card_render/usage_cards.py:71-321`；`output/templates.py:178-262`→`domains/render/templates.py:123-220`（CSS :46-115）。

**(g) `docs/rendering-contract.md` §六 缺 `error_card` 与「卡片骨架」小节** —— 建议新增「铁律 10（骨架）」：区段清单/顺序/字段名的最小契约（本席不代拟终稿，台账 F14-8 给了建议集）。

---

## 8. 新发现台账（七要素）

> 严重度定义：P0=数据真实性/安全；P1=用户可见错误或统一性主张实质不成立；P2=一致性缺陷可容忍但有代价；P3=卫生/文档。

| # | 严重度 | 坐标（快照） | 锚点字符串（重定位用） | 根因 | 建议改法 before→after（可直接落手） | 验证命令（零副作用） | 有无回归锁 |
|---|---|---|---|---|---|---|---|
| **F14-1** | **P1** | `domains/render/card_render/templates/universal_card.html:1179/1206/1231`；`templates.py:206-219`；`usage_cards.py:294`；`echo.py:3423`；`debug.py:813`；4 模板 `<div class="shell card">` | `class="card mica-stage"` / `<div class="card">` / `class="panel"` / `class="stage card"` | 两套渲染机制无共享装配件：根容器/外壳 **5 种范式**并存，契约 :78 又把两种写法并列成「合规」，故无人违规也无人收敛 | 定一范式（推荐 `render_shell` 的 `card {stage} > section {shell}`）→ 4 张 `<div class="shell card">` 模板与 media 卡 `.card>.panel` 逐面迁移（每面单独 PR + 截图基线）；契约 :78 按 §7.2(d) 改写；`universal` 内层再套 `.card` 的双 `.card` 嵌套**先改名** `video-card-shell`（截图选择器 `query_selector(".card")` 命中的是外层，内层同名属遗留） | `grep -n 'class="[a-z-]*card' plugins/bot_unified_runtime/domains/render/card_render/templates/*.html`（人读枚举，期望迁移后全部为 `class="card …"` 单层）+ `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_rendering_contract.py tests/test_mica_builders_contract.py -q -p no:cacheprovider --basetemp="$TEMP/f14-1"` | **无**（根类名有锁、根范式无锁） |
| **F14-2** | **P1** | `mica_shell.py:401-447`（`def render_shell(`），生产 0 消费；`echo.py:3376`/`debug.py:783`/`usage_cards.py:240`/`templates.py:46-65` | `def render_shell(` / `body {{ margin:0; font-family` | 装配件已建未接入（v21r3 只做值层通水）→ 文档层 `<!doctype>`/`<head>`/`body{}`/`.card{}`/`*{box-sizing}` **12 份手写**，`debug/usage` 缺 `padding:0`，11 面全无 `<title>` | 四直拼卡 return 段改调 `render_shell(title=卡题, tokens=root_tokens, css=<卡特有 CSS>, stage_class="help-stage", shell_class="help-shell", shell_width_px=CARD_SHELL_WIDTHS["help"])`（与 F5-4 同一动作，本席补 `title` 与 body 归一两项验收判据）；7 模板文档层另议（依赖 F14-1） | `grep -c "body[ ]*{" plugins/bot_unified_runtime/domains/render/**`（迁移前 12 → 迁移后 5（1 生成器 + 4 模板族残留，终态 1））；`pytest tests/test_mica_shell.py tests/test_mica_builders_contract.py -q`（同上参数） | 有（`test_mica_shell.py:135-256` 锁 `render_shell` 自身铁律，**但没锁「生产必须消费它」**）→ 建议补一条：`assert "render_shell" in 生产 import 集`（AST 或 `git grep` 断言） |
| **F14-3** | **P1** | `echo.py:3294-3313`（`for raw_line in body.splitlines():` / `line.endswith("总览")`） | `if line.startswith("【") and line.endswith("】")` | 帮助卡**反向解析自己那份人话文本**当数据源（详情形态），结构化形态（总览 `sections`）与文本形态二选一，两形态骨架也不同（`.help-grid.masonry` vs `.single`）→ 违背「一切先经中央统一指令再派发」：卡不是结构的下游，而是字符串的下游 | `_try_render_help_image(body, …, sections=…)` 改为**强制 `sections` 必填**：详情页也由 `_HELP_ENTRIES` 直接产 `sections`（数据已在手，见 `echo.py:3437-3452` 的 `_help_category_body` 就是同一批 entry 的文本化），删除 body 反解分支；body 仅用于 `text_fallback` | 只读核对：`grep -n "sections" plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py \| wc -l` 与 `grep -n "splitlines()" …/echo.py`（改后详情路径 0 命中）；`pytest tests/test_command_catalog*.py tests/test_doc_sync_gates.py -q`（同上参数） | **无**（`_HELP_ENTRIES` 有文档一致性门，卡片消费面零锁） |
| **F14-4** | **P1** | 同义异名双点：`bridge.py:1671`（`pc = _as_str(data.get("pc"))`）；`bridge.py:1778`（`card_title=_as_str(data.get("card_title"))`）；`echo.py:3268` vs `bridge.py:1543`（`sections` 双结构） | `data.get("pc")` / `data.get("card_title")` | 「`--pc` 退役」只做了 CSS token 层（`mica_shell.py:316-319`），**能力→桥层入参名**没退役；`title` 在诊断卡又叫 `card_title`；`sections` 一词两结构 | ①`data.get("pc")`→`data.get("platform_color") or data.get("pc")`（过渡双读，一版后删 `pc`），并把 `affinity.py` 构造点键名同步；②`card_title`→统一 `title`（同法双读过渡）；③D3 `sections` 改 `list[dict]`（`{name, rows:[{pill, desc}]}`），与 T5 同名同构；④`rendering-contract.md` §六新增「字段命名册」小节（§7.2(g)） | `grep -rn '"pc"\|"card_title"' plugins/bot_unified_runtime/domains/ \| wc -l`（现状>0 → 改后 0）；`pytest tests/test_rendering_contract.py tests/test_affinity_card*.py -q` | **无**（字段名零锁） |
| **F14-5** | **P1** | `templates.py:73`、`usage_cards.py:233`、`debug.py:776`、`echo.py:3369`（`width_px=640/900/880/940`）；`mica_shell.py:85`（`_DEFAULT_SHELL_WIDTH_PX = 880`）；`models.py:153`（`card_width: str = "1440px"`） | `shell_base_css("panel", width_px=640)` | 宽度**三源**（登记表 / 调用字面量 / 测试断言字面量 `test_rendering_contract.py:713-724`），另有 universal 走 payload `card_width`、`mermaid_max` 是同表异语义列、`_DEFAULT_SHELL_WIDTH_PX` 未登记 → 「宽度登记表」对 4 张直拼卡是**文档而非来源** | 四处 `width_px=<字面量>` → `width_px=CARD_SHELL_WIDTHS["media"/"usage"/"debug"/"help"]`；`mica_shell` 缺省值改 `CARD_SHELL_WIDTHS` 派生（或删参改必传）；`mermaid_max` 迁出本表或改名 `mermaid_fit_max`；`:713-724` 的 12 条字面量断言改为「断言调用实参 = 表值」的同源自洽 | `grep -rn "width_px=" plugins/bot_unified_runtime/domains/ \| grep -v CARD_SHELL_WIDTHS`（现状 4 → 0）；`pytest tests/test_v21r3_visual_gates.py tests/test_rendering_contract.py -q` | 有但**只锁值不锁消费方式**（gate06 用动态读表，故字面量与表值同漂移时门不红） |
| **F14-6** | **P1** | `content_parser.py:363`（`def render_card_png(`）+ 8 个 `from plugins.bot_unified_runtime.capabilities.content_parser import` 消费方；对照 10 处内联 `render_backend.render_card(`；`usage_cards.py:324-355`、`debug.py:819-860`、`error_report.py:839-900`（三处**无 prune/quota**） | `capabilities.content_parser import (` / `def render_usage_card_png(` | 中央出卡管线**住在能力里、挂在废弃垫片路径上**；与之并行的内联管线各写 viewport/落盘/digest/清理，策略还分裂（Path A `enforce_quota` 按字节 vs Path B `prune_prefixed` 按条数 vs 三处不清理） | ①新文件 `domains/render/card_render/emitter.py`：`emit_card(render_backend, html, *, prefix, card_dir, viewport, digest_parts, quota)` 收口 viewport 选择/落盘命名/prune+quota；②`render_card_png` 迁入其中，`content_parser` 与 8 能力改指新址；③`usage/debug/error` 三处补 `prune_prefixed(..., keep=120)` 或统一 `enforce_quota`；④`domains/render/templates.py:142` 的 `target = Path(card_dir or "data/cards")` 缺省字面量一并收编（现 8 处各写 `"data/cards"` 缺省，与 runtime_paths 重映射精神冲突） | `grep -rn "render_backend.render_card(\|render_card_png(" plugins/bot_unified_runtime/domains \| wc -l`（现状 20 → 改后 1 实现 + N 次 `emit_card`）；`grep -c "prune_prefixed\|enforce_quota" plugins/bot_unified_runtime/domains/render/card_render/*.py`（现状 0 → 3） | **无**（卡片生命周期零锁；台账 #31「prune 关账」只对 divination/today_history 两目录补了自管） |
| **F14-7** | **P2** | `market.py:283-294 _trend_svg_safe` / `stocks.py:219-228 _trend_svg` / `bridge.py:1430-1453 _spark_points`（三者 128×40 同几何）；`bridge.py:1527`（`^<svg…</svg>$` 放行 + 模板 `|safe`） | `def _trend_svg_safe(` / `def _spark_points(` | 同一「走势折线」三套实现，两套在能力层产 **HTML 串**穿过 `|safe` 上屏（桥层只能做形状白名单，不能做语义审查），一套在桥层算点位 | 能力层只交数据（`trend=[float]`），T5/T6 统一由 `bridge` 出 SVG（把 `_spark_points` 升级为唯一实现，内部改调 `finance_chart.line_chart_svg` 以消除 128×40 与色值双写）；`trend_svg` 入参退役为 `trend`，正则白名单保留一版做兼容；箱形图（唯一必须留 SVG 的形态）改走 `chart_spec` dict | `grep -rn "trend_svg\|_spark_points\|line_chart_svg" plugins/bot_unified_runtime/domains/ \| wc -l`（现 14+ → 收敛）；`pytest tests/test_stocks*.py tests/test_fx*.py tests/test_market*.py tests/test_rendering_contract.py -q` | 有（SVG 形状正则 + 金融卡回归族），但**锁的是放行规则、不是装配归属** |
| **F14-8** | **P2** | `bridge.py:1678-1682`（`score = _num(src.get("score"), 50.0)`）；`usage_cards.py:62-68`（`_fmt_int` 返 `"0"`）、`:135`（`or "0.00"`）；`models.py:49`（「字段缺失时对应区块整体隐藏」） | `_num(src.get("score"), 50.0)` / `def _fmt_int(` | 「未知」缺统一表达件，且两处把未知**画成真值**：双向面板 50.0+半棒+「友善」在卡上与实测无异（`rendering-contract.md:99` 已把 50.0 写成策略，而同段对 steps 选 `"—"`，同卡两制）；token 位 `0`/`0.00` 亦与真值同形。「整块隐藏」让**无数据**与**该类型无此区**像素同形 | ①`_pair` 缺数返回 `{"score":None,"tier":"暂无数据","bar":None}`，模板 `dscore` 空值显「—」并**不画进度棒**（与 steps 的 `"—"` 同制）；②`_fmt_int(value, *, dash_when_missing=True)`：None/脏值 → `"—"`，仅真 0 → `"0"`；渠道子行 `cost_text` 缺省 `"未计价"`（与 :149 对齐）；③新增卡片级「数据缺口区」槽位（`gaps: list[str]`），凡区块因缺数据隐藏即在缺口区留一行「无 X 数据」，消除同形歧义；④把「未知表达 5 法 → 2 法（`—` / 中文词）+ 缺口区」写进 `rendering-contract.md` 新铁律 10 | `grep -n "50.0" plugins/bot_unified_runtime/domains/render/card_render/bridge.py`（现 2 → 1 或 0）；`pytest tests/test_rendering_contract.py::test_affinity_card_never_raises_on_dirty_payload tests/test_affinity*.py -q` | **有但反向**：`test_affinity_card_never_raises_on_dirty_payload` + `rendering-contract.md:99` 把 50.0 当**预期**钉住了 → 改前须同步改门（属规格裁定，非本席可自改） |
| **F14-9** | **P2** | `renderer.py:197-198`（`elif is_chat: text = naturalize_chat_text(text)`）、`:207-209`（`media_parts` 原样透传）；`plain_text.py:286/340` | `elif is_chat:` / `for image in result.images or []:` | 卡片图上的文字**不经**说人话/打码出口：卡片文案唯一保护是 `html.escape`；11 面里只有诊断卡逐字段 `redact_local_secrets`。上屏技术串实测 8 处（§4.2），其中 `debug.py:842` 的 6 个 `fix_*` 枚举值可裸出 | ①出口收口：`render_*_html` 入口统一过一遍 `_card_text_safe(text)`（新件：`redact_local_secrets` + 英文枚举/snake_case 拦截 + 「未映射即记日志并显中文兜底」）；②`_LLM_SETUP_NEXT_ACTIONS` 与 `smoke` 值域补全（6 值），并把该表与 `_readiness_recommended_commands`/`_readiness_public_message` 三表合一（一处登记三处消费）；③T4 副标题 `RUNTIME DIAGNOSTIC · 泰缇斯系统` → 「系统自检 · 泰缇斯第二实例」；④`templates.py:172` 徽章兜底去裸 `platform`，改查 `PLATFORM_OFFICIAL_NAMES`→失败显「外部内容」；⑤`footer` 位 URL 改显平台域名或整区隐藏（URL 在 PNG 上不可点） | `grep -rn "_LLM_SETUP_NEXT_ACTIONS" -A 6 plugins/bot_unified_runtime/domains/ops/admin/debug.py`（目测 3→9 项）；离线单测：`pytest tests/test_debug*.py tests/test_llm_setup*.py -q`（构造 6 个未映射 next_action 断言输出无 `_`）；`grep -n "RUNTIME DIAGNOSTIC" plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html`（→0） | **无**（卡片文案出口零锁；`test_content_safety*` 管的是聊天文本面） |
| **F14-10** | **P2** | 11 处 `"viewport": {"width": …}` 字面量（`content_parser.py:430`、`affinity.py:281`、`market.py:251/742`、`fx.py:161`、`stocks.py:450/492`、`echo.py:3481`、`music.py:658`、`debug.py:847`、`error_report.py:863`、`usage_cards.py:341`）；注释算术自相矛盾同处 | `"viewport": {"width": 1504, "height": 1000}` / `1504 = 1440 + 56` | 截图视口是壳宽之外的第 12 个宽度轴，余量 0/50/60/64/80/100 六档无规则、无登记、无断言；`media` 卡不传 viewport → 两个后端两套缺省（`render_backends.py:393` 640×400 vs `:582` 672×480）同一张卡差 32px | 新登记 `CARD_VIEWPORT_GUTTER_PX: dict[str, int]`（或直接 `viewport_for(shell_key)→(w+2*G, h)` 函数，缺省 G=40）替换 11 处字面量；`media` 卡显式传 viewport；两处后端缺省统一为同一常量；修 `:430` 注释（28×2 与实际 +64 矛盾，写出真实外扩来源） | `grep -rn '"viewport": {"width"' plugins/bot_unified_runtime/domains \| wc -l`（11 → 0）；`pytest tests/test_render_backends*.py tests/test_rendering_contract.py -q` | **无**（viewport 与壳宽关系零登记零断言） |
| **F14-11** | **P2** | `error_report.py:88-104`（`_COOLDOWN_LINES` 12 句）+ `:973`（`random.choice`）+ `:1111`（`session_gate.allow(`） | `"细节都在刚才那张卡上"` | 冷却文案 12/12 假定「卡已发给用户」，而闸机在发卡**之前**记账；首发若走 `build_text_fallback`（无图）则第二句是对用户不存在的物件做指引，且不重申重试口径；另：同一「话术池」范式人话区用游标轮换、冷却用纯 random（同会话可复读） | ①`_COOLDOWN_LINES` 改中性指代（「细节我上面已经说过」），或让 `allow()` 返回是否**真的发过卡**、据此选池（新增 `_COOLDOWN_TEXT_ONLY_LINES`）；②冷却池改走 `_HUMAN_CURSOR` 同款会话游标（与 :337 同一 `rotating_line(pool, session_id)` 单函数） | `grep -c "那张卡" plugins/bot_unified_runtime/domains/ops/monitor/error_report.py`（12 → 0）；`pytest tests/test_error_card*.py -q` | 有（错误卡契约测试族），但**未锁文案与发卡事实的一致性** |
| **F14-12** | **P2** | 结构锁缺口：`tests/test_rendering_contract.py`（13 节）、`tests/test_mica_builders_contract.py:204`（唯一结构断言＝根类名）、`tests/test_v21r3_visual_gates.py`（门 01-09） | `test_public_token_subset_and_order_unified` | 三条契约线**全在断言值/CSS**；区段清单、区段顺序、区段存在性（页眉/署名/时间戳/来源脚注/CTA/缺口）、载荷字段命名**零断言**（§7.1）；「公共段顺序统一」证明顺序锁技术可行却未用于 DOM | 新增 `tests/test_card_skeleton_contract.py`（离线纯字符串，零渲染）：①面清单常量 11 与 `CARD_TEMPLATES`+builder 集一致；②每面「必备区存在性」表（页眉 `title`、署名 `bot-foot`/`footer-bot`/`card-footer-bot` 三族之一、时间或来源区**二选一**）；③根范式白名单（迁移后收成 1）；④载荷字段命名册断言（禁 `pc`/`card_title`，`sections` 必为 dict 形态）；⑤`render_shell` 必须被生产 import（AST 门） | 写后 `pytest tests/test_card_skeleton_contract.py -q --basetemp="$TEMP/f14-12" -p no:cacheprovider`（新文件，零在飞冲突；实施归主会话/F 席） | **无**（本条即缺口本身） |
| **F14-13** | **P2** | `echo.py:3220`、`debug.py:705`、`usage_cards.py:39` | `def _resolve_help_accent(` / `def usage_card_accent(` | 规格 D8 原样存活：同语义「按 `bot_help_card_color` 派生 (accent, accent_dark)」三份私有实现，**入参两类**（str vs Config）、**加深两套**（`bridge._darken` vs `theme_tokens._darken_hex`）；一处改函数即两卡漂移 | 单点化：`theme_tokens.accent_pair(color: str) -> tuple[str, str]`；三处改调它（`debug`/`usage` 内部先 `str(getattr(config,"bot_help_card_color",""))`）；`usage_card_accent`/`_llm_setup_accent` 删除；补一条 `test_all_cards_accent_pair_single_source`（断言三卡 root_tokens 的 `--accent-dark` 同源） | `grep -rn "_darken_hex\|_darken(" plugins/bot_unified_runtime/domains/ \| grep -v theme_tokens.py`（现 5+ → 0 于卡侧）；`pytest tests/test_mica_builders_contract.py tests/test_token_supply_chain.py -q` | 有（`test_*_token_from_theme` 系锁值等义），但**不锁「实现份数=1」** |
| **F14-14** | **P3** | 11 面 CSS 截断：`universal_card.html:1143`（`.footer-media-id`）、`usage_cards.py:270/56`（`.mcell`/`.cname`）、`echo.py:3413`（`.pill` max-width:62%）、`finance_card.html:81`、`market_card.html:81`、`error_card.html:111`（`word-break:break-all`） | `text-overflow:ellipsis` | 静态 PNG 上省略号＝**静默丢信息**，无「已截断」披露位，也无与 chunks/合并转发共享的长度预算 | 统一为「卡片长度预算」登记（`CARD_TRUNCATION: dict[面, {max_lines, policy}]`），并强制被截断时在缺口区（F14-8③）留一行「内容已截断」；命令名/模型名类**优先换行而非截断**（`.pill`/`.mcell.model` 属信息本体，截了就没法照抄命令） | `grep -rno "text-overflow:ellipsis" plugins/bot_unified_runtime/domains/render \| wc -l`（现 8+ → 登记后逐面判定） | **无** |
| **F14-15** | **P3** | `mermaid_card.html:163`（`.bf-dot` 内字面「守」，**且无 `.bf-avatar` 通道**）；`affinity/error/finance/market/song` 均为 `{{ (bot_name)[:1] }}` + avatar 分支；`universal:1227` 用 `default('A', true)` 第三兜底 | `<span class="bf-dot">守</span>` | 署名区 3 类名族之外，首字兜底与头像通道两套实现：mermaid 恒「守」（改名/换号即错），universal 的兜底字母 `'A'` 与其余的 `'守'` 第三种取值 | 抽 Jinja 宏 `templates/_macros.html::bot_signature(bot_name, bot_avatar_url, feature_label)`（纯文本宏，不涉渲染），7 模板统一消费；D1 `.cfb-*` 族与 T1 `.footer-bot-*` 族随 F14-1 迁移收敛 | `grep -rn "bf-dot\|cfb-dot\|footer-bot-dot" plugins/bot_unified_runtime/domains/render \| wc -l`（现 3 族 11 处 → 宏 1 处 + 少量直拼）；`pytest tests/test_rendering_contract.py -q` | **无**（署名区一致性仅 D2 一面有对象锁） |
| **F14-16** | **P3** | `models.py:153-155`（`card_width: str` / `scale_factor: float`）经 `_coerce_field`(`bridge.py:1249`) 仅 `_as_str`，直插 CSS（`universal_card.html:83/1015`） | `card_width: str = "1440px"` | 彩色字段有 `_safe_css_color` 白名单，**宽度/缩放无等价校验**（无 `_safe_css_length`）；当前**无可达外部路径**（全仓无调用方传 `card_width`，`scale_factor` 来自 `bot_card_ui_scale` 且 `content_parser.py:426` 已钳 0.5-2.0），属纵深防御缺口而非活漏洞（安全归属 F7，此条只报「同类字段的校验不对称」） | `_coerce_field` 增分支：`field_name in {"card_width"} → 正则 ^\d{2,4}px$ 否则回落默认`；`font_scale/scale_factor` 钳到 [0.5,2.0]（把能力层的钳位上收到桥层，避免第二调用方漏钳） | `grep -n "card_width" plugins/bot_unified_runtime/domains/render/card_render/bridge.py`（现状仅透传 → 加校验后命中 1）；`pytest tests/test_rendering_contract.py -q` | 有（色彩侧 `_safe_css_color` 有门），长度侧无 |
| **F14-17** | **P3** | `output/card_render/templates/`（空目录）；`domains/render/templates.py:142` 等 8 处 `Path(card_dir or "data/cards")`；三套 cache_policy 入口（`runtime/cache_policy.py` 垫片 vs `domains/chat_reply/runtime/cache_policy.py` 真身）+ `prune_prefixed` vs `_prune_card_dirs` 两函数 | `def _prune_card_dirs(` | 重组遗留的入口/路径歧义（不改变行为，属卫生与「统一函数」主张的口径噪声） | 随 F14-6 的 `emitter.py` 一次性收口：删空目录、缺省卡目录改读 config、`_prune_card_dirs` 并入 `cache_policy.prune_tree_prefixed` | `find plugins/bot_unified_runtime/output -type d -empty`（现 1 → 0）；`git status --short`（应无源码树新缓存） | n/a |

**跨席重复声明（不重复记账，仅索引）**：`render_shell` 零消费 / `width_px` 字面量 = **F5-4**；壳层渐变手抄份数、状态色直写、`--mica-shadow-panel` 三级族与两级面不对称 = **F5-2/F5 表 :67**；卡片模板 hex 计数与 gate08 黑名单化 = **F5 §5**。本席 17 条均为**骨架/区段/命名/出口/装配归属**轴上的新账。

---

## 9. 取证方法与只读纪律自证

**用了什么**：`Grep`/`Read`/`Glob` + 只读 `ls/wc/sed -n/grep -c/find/date`。所有行号来自本会话读取输出。

**没用/不会用**（硬纪律）：未跑任何 `python`（因此无 `PYTHONDONTWRITEBYTECODE/--basetemp/-p no:cacheprovider` 需求，源码树零缓存新增由 §9 末命令自证）、未 `verify_hashes.py --write`、未 `doc_sync.py --write`、未 `command_catalog.py --write`、未起 playwright/截图/样张、未 `npm run build`、未跑 pytest（定向小集亦未跑——本席全部结论可静态取证）、未做任何 git 写操作、未派子代理、未碰进程、未读 `.env`/`personas/`/`ChatBot_Archive/`/`ChatBot_Runtime/`、未碰 `domains/weather/assets/qx.json`、除本文件外零新建零修改。

**本文所有可复跑命令**（只读，零副作用）：

```bash
# 面数与骨架
ls plugins/bot_unified_runtime/domains/render/card_render/templates/*.html | wc -l
grep -rln "<!doctype html>" --include=*.py plugins/
grep -rn 'class="[a-z-]*card' plugins/bot_unified_runtime/domains/render/card_render/templates/*.html
grep -rn "bf-dot\|cfb-dot\|footer-bot-dot" plugins/bot_unified_runtime/domains/render | wc -l
# 入参与字段
grep -rn '"pc"\|"card_title"\|data.get("pc")' plugins/bot_unified_runtime/domains/render/card_render/bridge.py
grep -rn "shell_base_css(" plugins/bot_unified_runtime/domains | grep -v mica_shell.py
grep -rn '"viewport": {"width"' plugins/bot_unified_runtime/domains | wc -l
grep -rn "capabilities.content_parser import" plugins/bot_unified_runtime | wc -l
grep -rn "_resolve_help_accent\|def usage_card_accent\|def _llm_setup_accent" plugins/
grep -rn "prune_prefixed\|enforce_quota\|_prune_card_dirs" plugins/bot_unified_runtime/domains
# 结构锁有无
grep -n "^def test_" tests/test_rendering_contract.py tests/test_mica_builders_contract.py tests/test_v21r3_visual_gates.py | wc -l
grep -rn "order\|sequence\|field name\|section" tests/test_rendering_contract.py | wc -l   # 期望 0 命中结构断言
# 技术串
grep -n "RUNTIME DIAGNOSTIC" plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html
grep -c "那张卡" plugins/bot_unified_runtime/domains/ops/monitor/error_report.py
find plugins/bot_unified_runtime/output -type d -empty
```

**未取证 / 边界（诚实标注）**：
- 未做真机出图比对（禁渲染），故「省略号实际吃掉多少字符」「余量不足是否裁阴影」为**静态推断**，需重启后 `scripts/e2e_acceptance.py` 或人工截图定案。
- `smoke.py` 的 `llm_next_action` 值域取自 `_readiness_recommended_commands/_readiness_public_message` 两个 `if` 链（:2664-2697）与 `return` 分支，**未做全树穷举**；F14-9 的「6 个值可裸出」成立的前提是该链即全集——主会话动手前请再核一次表。
- 「12 份 body 规则」「11 处 viewport」「14+ trend_svg 引用」均为 `grep` 计数快照，在飞波改一处即变数；引用时以锚点字符串为准。
- 未验证 `webui/`（F2/F3/F9/F10 席域），卡片侧与 WebUI 是否共享区段命名**未查**——若后续要「前端一面」的统一，这是空白格。
