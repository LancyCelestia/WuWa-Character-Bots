# 快讯与历史上的今天 · 今日快报

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.news · 今日快报

- 层级：一级 B05 → 二级 news → 三级 `news`
- 路由席位：`NEWS`（matcher `news`，command=True）
- 判定优先级：41
- 能力 id：`bot.news`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe/feeds`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`快报` / `早报` / `晚报` / `今日热点` / `科技新闻` / `AI快报` / `财经新闻` / `国际新闻`（繁体同族同表生效）：出一屏当日要闻，标题带来源，条目下带一行摘要。类目从同一句话里提取：财经→finance、国际→world、科技/AI/人工智能→tech、其余→mix（跨类目轮转，保证多样性）。

## 怎么调用

- 席位 `NEWS`、能力 id `bot.news`；闭包 `domains/subscribe/capabilities/news.py:build_news_capability(config)`，谓词 `is_news_command`，类目提取 `extract_news_category`。
- 数据真身：`domains/subscribe/feeds/news_feeds.py:fetch_headlines(category, *, timeout_seconds, cache_seconds, max_items)` → `format_news_brief`。内部：`_feeds_for`（类目→源列表）、`_fetch_single_feed`（单源失败静默返空）、`parse_feed`（RSS2.0/Atom/RDF 通吃）、`_merge_dedup`（URL 去重，mix 轮转合并）、`_clean_title`（剥标签/反转义/压空白）、`_entry_summary`（首段纯文本）。
- 单点网络出口 `_fetch_feed_text(url, timeout)`：测试 monkeypatch 它即可拦截全部外呼；`reset_news_cache()` 供测试与运维。
- 纯文本产出，不出卡（快讯形态刻意保持轻，渲染面归 B08 的通用管线）。

## 开关与参数

- `bot_news_enabled`（缺省 True）、`bot_news_timeout_seconds`、`bot_news_cache_seconds`（按类目分桶）、`bot_news_max_items`（条数语义由用户裁定过，三键缺省值以 `config.py` 为准）。
- 逐键含义以 `docs/config-catalog-full.md` 为准；均为装配期读取的静态配置，热改当轮不生效。

## 失败时看到什么

- 部分源失败：条目变少，**不报错也不声明**（见本功能 README 缺陷 1）。
- 全部源失败：从 `domains/chat_reply/capabilities/user_copy.py` 的数据源失败池轮换出一句人话（reason=「快报暂时拉不到」），不缓存失败结果，下一句就能重试。
- 坏 XML / 返回 HTML / 超过读取上限（限长读，防被大页面拖死）：该源当作无结果跳过。
- 命中不到任何类目：回退 mix 全源轮转，而不是回一句"不支持该类目"。

## 测试与验收

离线：`tests/test_news.py`（类目提取、去重与轮转、坏源静默、缓存只存成功、条数上限）、`tests/test_traditional_news_randpic.py`（繁体触发）。
真机：`快报`、`科技新闻`、`AI快报`、`快報`（繁体）；负样本 `新闻`、`搜索一下最近的 AI 新闻`（应走搜索链路，不被本入口抢）。
