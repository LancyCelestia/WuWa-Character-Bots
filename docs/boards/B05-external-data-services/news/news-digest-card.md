# 快讯与历史上的今天 · 新闻摘要卡

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.news · 新闻摘要卡

- 层级：一级 B05 → 二级 news → 三级 `news-digest-card`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe/feeds`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「快讯」聚合成一张紧凑的摘要卡：一组来源条目，每条带来源徽章、时间戳、标题与摘要片段，
浮在守岸人本命釉瑚云母底之上。它是 B05「外部资讯与数据服务」里把散点新闻收敛成一屏可读结论的
呈现端——取不到的源绝不补齐，条目为空时诚实出「暂无」占位。数据来自 `bot.news` 能力的聚合结果，
本卡只负责把它摆清楚。

## 怎么调用

模板真身：`plugins/bot_unified_runtime/domains/render/card_render/templates/news_digest_card.html`。
渲染入口：`bridge.render_news_digest_card_html(payload)`，字段 `title / sub / foot / items=[{source,time,name,snip}] /
platform_color / bot_name / bot_avatar_url / feature_label`；缺省落守岸人品牌蓝、空字段区块静默隐藏、
任何输入都不抛异常（渲染面铁律：失败降级纯文本）。质感与点歌候选卡 / 全球股指卡同族（玻璃浮层 + 漂移色斑 + 品牌胶囊）。

## 开关与参数

- 卡宽：以 `theme_tokens.CARD_SHELL_WIDTHS["news_digest"]` 登记值为准（键名 `news_digest`）。
- 静态中文文案：唯一住 `bridge._CARD_TEXT`（键 `static_news_*`），模板只留参数引用。
- token（洗色 / 阴影 / 半径 / 间距 / 字号）：全走 `theme_tokens`，经 bridge 注入，模板零私有值。

## 失败时看到什么

聚合无源或条目全被过滤时，卡体显示「暂无可展示的条目」占位；渲染层异常在能力侧兜底为纯文本，
卡面不因单条脏数据整体炸出。具体降级文案以能力真身与运行期错误面为准。

## 测试与验收

- 契约：`tests/test_rendering_contract.py`（逐模板枚举已含本卡，锁 viewport / 透明 / 字重 / 阴影族 / 宽度 / 间距 / wash / 动画作用域 / 零硬编码中文）。
- 视觉对照样张：`.superpowers/sdd/news-card-samples/`（同一份新闻数据的四种质感：Mica、液态玻璃、釉瑚漂移、摘要专属）。
- 出图真机验收随「快报」能力走 `docs/acceptance-manual.md` 对应小节。

