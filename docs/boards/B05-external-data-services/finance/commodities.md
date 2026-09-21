# 金融行情 · 商品行情

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 大宗商品

- 层级：一级 B05 → 二级 finance → 三级 `commodities`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`黄金` / `白银` / `铜价` / `原油` / `大宗商品`：一张商品卡，按 贵金属 / 基本金属 / 能源 分组，红涨绿跌，能拿到走势的随行 30 日折线。接入的是 COMEX 金/银/铜与 NYMEX 原油（WTI）主力连续，**铜用 COMEX 替代 LME 并把这个替代事实写在卡上**。

## 怎么调用

- 路由侧：席位 `COMMODITIES`、能力 id `bot.commodities`，闭包 `domains/finance/capabilities/market.py:build_commodities_capability(config, *, render_backend)`，谓词 `is_commodity_command`（短文本、无链接、**命中股票词时让路**）。
- 数据侧真身：`domains/finance/data/commodities_data.py` — `fetch_commodity_quotes`（快照）、`fetch_commodity_trend(secid, ...)`（30 日收盘，复用东财 kline 族，带 `end`、瞬断按 `_retry_transient` 退避）、`commodity_availability()`（覆盖表：有源记 `eastmoney:<secid>`，无源项显式登记）、`group_commodity_quotes` / `format_commodity_line` / `format_commodities_brief`、`reset_commodities_cache` / `reset_commodities_trend_cache`。
- 出卡：与股指/债券/北向共用 `_card_common_payload` + `_render_finance_sections_card`（sections/rows 契约，零模板改动），走势线 `finance_chart.line_chart_svg`。
- 价格精度：`format_price` 随量级给位（高价两位、低价三位），不四舍五入成"整数美元"。

## 开关与参数

- 开关读点：`domains/chat_reply/runtime/base_router.py` 以 `getattr(config, "bot_commodities_enabled", True)` 判定，**但 `config.py` 里没有这个字段、目录册也没有登记** ⇒ 现实中关不掉（缺省恒 True）。这是"读点先于声明"的欠账，记在本功能 README 现行缺陷，别把它当成可热改的旋钮。
- 超时/缓存沿用 `bot_market_timeout_seconds`、`bot_market_cache_seconds`、`bot_market_retry_on_empty`。
- 优先级 37（2026-09-21 拆位结果，越专用越靠前）——**代码已在、线上未生效**，需提交并由用户提权重启。
- 市场号规律（101=COMEX、102=NYMEX）写在数据层头注，改 secid 只改这一处。

## 失败时看到什么

- 快照失败：`user_copy` 池的数据源失败人话。
- 走势失败：该区块「暂无历史走势数据」（push2his 瞬断的常态表现，属诚实降级）。
- **无源品种明确不接**：LME 铜在东财多个候选 secid 实测全部无行、LME 官网无免 key 稳定公开接口 ⇒ 铜用 COMEX 主力连续（美元/磅）替代并在卡上说明，绝不冒充 LME 口径；布伦特原油未实测到有效 secid ⇒ 暂不接入，用户问就答"没有可信来源"，不用 WTI 顶替。

## 测试与验收

离线：`tests/test_commodities_data.py`（secid 宇宙、无源登记、替代说明、分组与量纲）、`tests/test_market_fin_phase1.py`、`tests/test_route_priority_disambiguation.py`（商品/股指/个股互不抢）。
真机：`docs/acceptance-manual.md` §6.6.3 ①（铜行必须带 LME 替代注记）；`布伦特原油` 应显式拒绝而非给 WTI。
