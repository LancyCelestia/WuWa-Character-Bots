# 金融行情 · 全球股指行情

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 全球股指行情

- 层级：一级 B05 → 二级 finance → 三级 `market`
- 路由席位：`MARKET`（matcher `market`，command=True）
- 判定优先级：41
- 能力 id：`bot.market`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`行情` / `大盘` / `股指` / `全球股市`（可带市场词：美股/港股/A股/日经/纳斯达克…），出一张全球指数面板卡：按 中国区 / 亚太 / 欧美 分组，红涨绿跌、点位与涨跌幅带符号，命中市场词时只展示对应指数。数据来自东方财富 push2 免费接口（免 key），俄罗斯 MOEX 走上文所述的 ISS 官方备选源。

## 怎么调用

- 席位 `MARKET`、能力 id `bot.market`；闭包 `domains/finance/capabilities/market.py:build_market_capability(config, *, render_backend)`。
- 触发谓词 `domains/finance/capabilities/market.py:is_market_command`：短文本、**不带链接**（带链接归 B05.link-parse）、命中触发词且不撞"房价/基金/币圈"等非股市语境；市场词提取在 `market_filter_secids`。
- 取数：`domains/finance/data/market_data.py:fetch_index_quotes`（快照，失败返回空列表、绝不抛）+ `fetch_index_trend(secid, ...)`（近 30 日收盘，MOEX 走 ISS history 尾部窗口拿真实收盘，不再画假线）。
- 核验：`domains/finance/data/market_crosscheck.py:crosscheck_quotes` → `format_crosscheck_note` 作为卡脚注。
- 出卡：`domains/finance/data/finance_chart.py:line_chart_svg` 缩略折线 + B08 的金融卡渲染管线；文案统一走 `format_market_brief`。
- 同文件里还住着商品/债/北向三个能力的闭包与谓词（`build_commodities_capability` 等），四个席位刻意分开注册，见各自卡片。

## 开关与参数

- `bot_market_enabled`（缺省 True）：本入口总开关。
- `bot_market_timeout_seconds`、`bot_market_cache_seconds`（进程内 TTL；两键缺省值以 `config.py` 为准）、`bot_market_retry_on_empty`（缺省 True，东财"200 空体"至多再试一次）。
- 本入口与同族席位（个股/汇率/商品/债/北向）的优先级数值以 `domains/chat_reply/runtime/base_router.py` 的 `RouteRule` 行为准；2026-09-21 修复波做过**拆位**（越专用越靠前）并收紧 market 词表把「兑/原油/国债/债券/北向/沪深股通」让路——该改动**代码已在、线上未生效**（未提交、未重启）。

## 失败时看到什么

- 快照取不到：一句数据源失败人话（从 `domains/chat_reply/capabilities/user_copy.py` 的 DATASOURCE_FAILURE 池轮换，reason=「行情数据暂时拉不到」），不报错、不留空卡。
- 走势取不到：卡上「暂无历史走势数据」；单源失败的指数**缺席**而非造点。
- 无源市场：卡面「暂无」注记区显式说明（如澳门无证券交易所、东财未收录迪拜综合指数），绝不静默省略。
- 交叉核验通道挂：脚注不出现（沉默），主数据照常展示。

## 测试与验收

离线：`tests/test_market_card.py`、`tests/test_market_backoff.py`（空响应重试与关闭后逐字节一致）、`tests/test_market_exclusion_guard.py`（非股市语境让路）、`tests/test_market_crosscheck_tencent_gbk.py`（编码与量级）、`tests/test_route_priority_disambiguation.py`（拆位与语料自证）。
真机：`docs/acceptance-manual.md` §6.6.3；`行情`、`美股行情`、`莫斯科股指`（应见真折线）、`美元兑人民币行情`（应让路给汇率，属拆位后的预期）。
