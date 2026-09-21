# 金融行情 · 个股 OHLCV 与分布

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 个股 OHLCV 与分布

- 层级：一级 B05 → 二级 finance → 三级 `single-stocks`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

个股域的数据层真身（不注册路由）：公司注册表（ticker→secid→市场→币种→品牌色→logo 域名）、四类取数、五个技术指标、分布统计，以及**非上市公司红线**的落地处。`stocks` 入口与 B04 的知识问答都用它，禁止第二份实现。

## 怎么调用

- 真身：`domains/finance/data/stock_data.py`。注册表读点：`list_listed_companies`（含美股与 A股/港股切片）、`list_cn_hk_companies`、`find_company_ref(ticker)`、`resolve_company_query(text)`；非上市名单在 `NON_PUBLIC_EQUITIES` 注册表，`openai_equity_note()` 给带来源的公开估值说明。
- 取数：`fetch_stock_quote` / `fetch_stock_ohlcv(days=90)` / `fetch_market_cap` / `fetch_stock_quotes(symbols)`（批量面板）/ `fetch_stock_history(symbol, days)`。字段口径实测核验（写在该文件头注）：现价 f2 / 涨跌 f3 / 涨跌额 f4 / 量 f5 / 高低开收 f15-f18 / **总市值以 f20 为准**（`f116` 惯用法实测无值，已废弃）。
- 指标：`compute_kdj`、`compute_macd`、`compute_rsi`、`compute_wr`、`compute_cci`、`compute_all_technical_indicators`（每个独立判窗口）。
- 分布：`boxplot_stats`（type-7 分位，与 Excel `QUARTILE.INC` 同口径）、`build_boxplot_from_ohlcv`（按日取一个数值成分布）。
- 韧性：`_network_retry` 三取数点退避重试（治 `push2his` 的 `RemoteDisconnected`）；空响应重试共用 `market_data` 的重试缝。
- 缓存清理：`reset_stock_cache()` / `reset_stock_history_cache()`。

## 开关与参数

无独立键，沿用 `bot_stocks_enabled`、`bot_market_timeout_seconds`、`bot_market_cache_seconds`、`bot_market_retry_on_empty`。K 线根数、指标周期是调用方参数（`days`、`period`），非配置面。

## 失败时看到什么

- 上市股票：状态对象三态 `ok/degraded/unavailable` + `note`，缺数一律 `None` 不造 0；单位词按币种（未登记币种用 ISO 代码，不冒充美元）。
- 非上市公司：**不发任何行情请求**，只回有出处的估值/公告说明与口径标注；结构上不存在价格字段，因此也无法被误渲染成价格。
- 指标窗口不足："暂缺"，不用更短窗口偷偷算一个交差。
- 分布样本不足：`boxplot_stats` 返回 `(None, "insufficient_data")`，调用方跳过该区块。

## 测试与验收

离线：`tests/test_stock_data.py`（含 f20/列序/坏行/非上市红线）、`tests/test_stock_technical_indicators.py`（五指标逐一口径）、`tests/test_stocks_hijack_guard.py`、`tests/test_market_fin_phase1.py`。
真机：`英伟达股价`（现价+走势+指标齐、缺项标注）、`特斯拉近一月股价`（多日分布箱形）、`OpenAI 市值`（应给公告口径说明、拒绝出价格）。
