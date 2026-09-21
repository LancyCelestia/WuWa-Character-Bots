# 金融行情 · 北向资金

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 北向资金口径

- 层级：一级 B05 → 二级 finance → 三级 `northbound`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`北向资金` / `北上资金`：沪股通、深股通各自的当日**成交总额、成交笔数、领涨股、参考指数收盘**，一张卡。**卡上没有、也不会有"净买入"这个数字**——交易所自 2024-08 起停止披露北向净买入，本项目因此不设该字段，并在卡面显式写明口径。这既是本入口的全部职责，也是它最重要的红线。

## 怎么调用

- 路由侧：席位 `NORTHBOUND`、能力 id `bot.northbound`；闭包 `domains/finance/capabilities/market.py:build_northbound_capability(config, *, render_backend)`，谓词 `is_northbound_command`（短文本、无链接；「南向资金」不在本入口语义内，不触发属预期）。
- 数据真身：`domains/finance/data/market_data.py` —— `NorthboundFlow`（单通道当日成交快照，**无净买入字段**）、`fetch_northbound_flows(timeout_seconds, cache_seconds)`、`format_northbound_brief`、`reset_northbound_cache()`；每通道独立网络出口 `_fetch_northbound_channel(mutual_type, ...)`，行解析 `_parse_northbound_flow` 缺交易日或全部数值缺失就返回 `None`（该通道缺席，不造行）。
- 出卡：与股指/商品/债券共用 `_card_common_payload` + `_render_finance_sections_card`（sections/rows 契约）。
- 量纲：上游成交额以百万计，卡面按亿元展示，换算链 `/100` 有回归锁盯着，防"量级差 100 倍"这种静默错。

## 开关与参数

- 开关读点 `getattr(config, "bot_northbound_enabled", True)` 在 `domains/chat_reply/runtime/base_router.py`，但 **`config.py` 未声明该字段** ⇒ 线上关不掉（详见本功能 README 现行缺陷）。
- 超时/缓存沿用 `bot_market_timeout_seconds` / `bot_market_cache_seconds`；北向快照有独立 TTL 常量与独立缓存（`reset_northbound_cache`），与指数快照互不影响。
- 优先级 39（拆位后）——代码已在、线上未生效。

## 失败时看到什么

- 两通道都取不到：数据源失败人话。
- 单通道缺/字段缺：该行缺席或在卡上标"暂无"，领涨股为空就整段省略，不用零或占位。
- 交易日口径：上游给的是哪个交易日必须随数显式标出，休市/延迟时用户能看出来自己读的是哪一天。
- 用户追问"今天净流入多少"：答"该口径自 2024-08 起不再披露，只有成交额口径"——**任何情况都不给净买入数值**。

## 测试与验收

离线：`tests/test_northbound_data.py`（无净买入字段的结构断言、缺数不造行、亿元换算量纲自洽）、`tests/test_market_fin_phase1.py`、`tests/test_route_priority_disambiguation.py`。
真机：`docs/acceptance-manual.md` §6.6.3 ③——成交总额量级存疑就查 `/100` 换算链；卡面出现任何"净买入/净流入"字样即视为回归。
