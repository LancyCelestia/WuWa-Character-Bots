# 卡片渲染 · Jinja 模板与 f-string 直拼卡

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.card-render · Jinja 模板与 f-string 直拼卡

- 层级：一级 B08 → 二级 card-render → 三级 `templates`
- 实现落点：`plugins/bot_unified_runtime/domains/render`、`docs/rendering-contract.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

产出「一张卡的完整 HTML」。两套形态并存，且都要过同一份契约：

- **Jinja 模板族**：`domains/render/card_render/templates/*.html`（模板清单以该目录的 glob 现算为准，并由 `scripts/doc_sync.py` 派生进机器册）。
- **f-string 直拼卡**：不走模板文件，在 Python 里拼 HTML。四处真身分别是 `domains/chat_reply/capabilities/echo.py`（帮助卡）、`domains/ops/admin/debug.py`（LLM 检查卡）、`domains/render/card_render/usage_cards.py`（账单卡）、`domains/render/templates.py`（媒体归档卡）。

两派的共同点：数据先归一再入模板，样式一律来自 `theme_tokens` + `mica_shell` 生成器注入，所有字段经 `html.escape` 防注入。**具体有哪些模板、有几张直拼卡，由 `scripts/doc_sync.py` 派生进机器册 `docs/auto-facts.md`，本页不写数量**（历史教训：手写过的每一版都在几天内过期）。

注意 `domains/render/templates.py` 的双重身份：它既是媒体卡的真身，又对 universal/song 两卡提供再导出，别把「从这里 import」当成「这里有实现」。

## 怎么调用

一律经 `domains/render/card_render/bridge.py` 的公开函数，它们是纯函数：输入 payload 字典（也接受 PlatformParse 投影或部分字段缺失的字典），输出 HTML 字符串。

- `render_universal_card_html` / `render_market_card_html` / `render_finance_card_html` / `render_affinity_card_html` / `render_song_candidates_html` / `render_error_card_html` / `render_mermaid_html`
- `domains/render/templates.py:render_media_card_html`（媒体归档卡）
- `domains/render/card_render/usage_cards.py:usage_report_mica_html` / `render_usage_card_png`

能力层拿到的通常是「HTML → 交后端出图 → 失败回文字」这一整段，不自己拼 shell。归一层（`parse_to_render_payload`、`flat_projection`、各 `_as_*` 强转、好感度卡脏数据归一）也在 bridge 内，模板只负责展示不决定发送。

新卡接入按 `docs/rendering-contract.md` §五 的清单走，第一步就是**不复制任何 CSS 声明**：Jinja 卡以 `_card_root_tokens(...) + **_vis4_context()` 为唯一起点，直拼卡经 `render_shell`/`render_root_tokens`/`shell_base_css` 装配。

## 开关与参数

模板本身没有开关。影响形态的输入是 payload 里的显式选择：

- `card_width`（universal 卡宽度由 payload 驱动，配合 zoom 第三机制）
- `phase` / `--phase`（由 `payload_phase` 从内容摘要派生，钉动画初相）
- `wash_blob_mix`（平台色混入比，缺省 35，error 卡按登记豁免传 24）
- `prefix_parts`（能力声明的前置部件，如群聊 @ 段，由 renderer 前置拼接，不由模板决定）

生效条件：**必须重启**。模板与 Python 拼卡都是代码，无热加载。

## 失败时看到什么

模板层的失败被刻意压成两种，都不该是运行异常：

- **payload 脏或缺**：区块整体隐藏，缺省值填充（`None`/字符串分数归 0.0、双向面板缺省 50.0、bar 钳 0–100、`None` 显示「—」）。传 `None` 或 `{}` 也返回可截图的 HTML，不抛 `TypeError`。
- **内容超出承载**：长文本分片与合并转发由 renderer 决定（见 [outbound-copy](../outbound-copy/README.md)），模板不做截断策略。

出图阶段的失败（后端不可用、`.card` 缺失、超时）不在本页，见 [render-backend](render-backend.md)；它的唯一外部表现是「这条回复变成纯文本」，用户看不到报错。

## 测试与验收

`tests/test_rendering_contract.py`（Jinja 族逐条，含脏 payload 不抛异常锁 `test_affinity_card_never_raises_on_dirty_payload`）、`tests/test_mica_builders_contract.py`（直拼卡同口径）、`tests/test_template_visual_audit.py`、`tests/test_v21r3_visual_gates.py`（gate 系列按渲染面现算覆盖）、`tests/test_universal_card_visual.py`、`tests/test_error_card_contract.py`、`tests/test_mica_shell.py`。模板清单与渲染面数由 `scripts/doc_sync.py` 派生，漂移只读校验 `--check`；交付物哈希由 `tests/verify_hashes.py` 记账。

真机验收＝重启后 `docs/acceptance-manual.md` §6.6.10 的逐卡触发清单（逐卡项目以该手册该节的现文为准）。
