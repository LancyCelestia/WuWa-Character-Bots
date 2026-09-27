# 金融行情 · 个股行情

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 个股行情

- 层级：一级 B05 → 二级 finance → 三级 `stocks`
- 路由席位：`STOCKS`（matcher `stocks`，command=True）
- 判定优先级：42
- 能力 id：`bot.stocks`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
- 帮助主题：个股行情
<!-- BOARD-AUTO:END -->

## 这个入口做什么

点名一家公司（`英伟达股价` / `市值` / `stock price` / 繁体 `股價`）出一张个股卡：现价与涨跌、OHLCV 走势、KDJ 等技术指标、总市值、logo 与品牌色，另有多日收益分布箱形图；不点名时输出科技巨头速览面板。**问的是非上市公司时不给价格**——只给有来源、有口径、标注时点的公开估值/公告说明。

## 怎么调用

- 席位 `STOCKS`、能力 id `bot.stocks`；闭包 `domains/finance/capabilities/stocks.py:build_stocks_capability(config, *, render_backend)`。
- 触发谓词 `is_stocks_command`（短文本、无链接、显式股票词或公司别名+股票语境）；别名/symbol 解析在 `domains/finance/data/stock_data.py:resolve_company_query` 与 `resolve_stock_symbols`，ASCII 别名走词边界匹配（防 `metadata` 误中 `meta`）。
- 取数四路独立降级：`fetch_stock_quote` / `fetch_stock_ohlcv` / `fetch_market_cap` / `fetch_stock_quotes`（批量面板），口径与非上市红线见 `single-stocks` 卡片。
- 指标：`compute_kdj` 与 `compute_all_technical_indicators`（MACD/RSI/WR/CCI）；分布：`boxplot_stats` / `build_boxplot_from_ohlcv`。
- 出卡：`build_stocks_card_payload` 走 `render_finance_card_html` 的 sections/rows 契约；折线 `finance_chart.line_chart_svg`、箱形 `box_plot_svg`；渲染失败一律回退纯文本 `format_stock_brief`。
- logo：`local_logo_uri`（clearbit 主源 → Google s2 二源 → 「守」字圆点），PNG magic 校验后落盘（目录以 `config.py` 的路径键为准，经 runtime_paths 重映射进 Runtime 数据根），`warm_logo_cache` 幂等预热。

## 开关与参数

- `bot_stocks_enabled`（缺省 True）。优先级比 `market` 更靠后一位（数值以 `domains/chat_reply/runtime/base_router.py` 的 `RouteRule` 行 为准）但**谓词更专用**，两者互不抢路由；「行情」裸词永远归 `market`。
- 超时/缓存沿用 `bot_market_*`；东财空响应受 `bot_market_retry_on_empty` 管。
- 卡面无 logo 属模板槽位休眠，不是异常。

## 失败时看到什么

每一块数据各自降级，绝不连坐也绝不补数：现价取不到写 `unavailable` + 原因，K 线坏行逐行跳过并转 `degraded`、全失败转 `unavailable`，市值字段缺失时 `value=None` 而不是 0，指标窗口不足写"暂缺"。非上市公司走**独立分支**：结构性不触任何行情外呼，因此也不可能出现"编出来的价格字段"。

## 测试与验收

离线：`tests/test_stock_data.py`、`tests/test_stock_technical_indicators.py`、`tests/test_stocks_hijack_guard.py`（劫持清零：占卜/天气/商品词不让个股抢）、`tests/test_market_fin_phase1.py`、`tests/test_route_priority_disambiguation.py`。非上市红线由结构锁用例钉住（该分支无价格字段可断言）。
真机：`英伟达股价` 连发两次验 logo 缓存命中（第二次不再下载）；`英伟达市值`、`OpenAI 估值`（应给公告口径说明、无任何价格）。
