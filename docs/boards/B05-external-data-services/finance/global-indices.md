# 金融行情 · 全球指数与走势图

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 全球指数与走势图

- 层级：一级 B05 → 二级 finance → 三级 `global-indices`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

指数域的数据层真身（不注册路由）：决定"哪些指数在宇宙里、每个 secid 谁供给、哪些市场结构性无源、走势怎么取、两源怎么核"。`market` 入口只消费这一层，注册表一改，卡面与文本同时跟随。

## 怎么调用

- 真身：`domains/finance/data/market_data.py`。指数宇宙与分组顺序、`INDEX_UNAVAILABLE`（无源登记）、`PENDING_INDEX_CANDIDATES`（只登记不上卡的候选，如用 ETF 代理某国指数——是否接受属语义裁决，等用户）、`index_unavailable_entries()`（卡面注记与测试的唯一读点）都在这一份，条数以文件为准、文档不手写。
- 主源：东财 `push2.eastmoney.com/api/qt/ulist.np/get`，`fltt=2` 让数值直接以小数返回；secid 前缀 1=上交所、0=深交所、100=国际指数；无效 secid 不报错，只会从 `data.diff` 里消失——所以"少一行"必须按缺数处理。
- 备选源：MOEX ISS `https://iss.moex.com/.../boards/SNDX/securities/IMOEX.json`（东财无该指数），按列名取 `CURRENTVALUE`（缺则 `LASTVALUE`），列序变更不敏感；单源失败该指数缺席，不拖垮整卡。
- 走势：`fetch_index_trend(secid, *, timeout_seconds, cache_seconds)` 近 30 日收盘（旧→新），东财 kline 族**必须带 `end`**（2026-09-13 接口变更，缺它返空），瞬断走 `_retry_transient` 退避重试；MOEX 走 ISS history 尾部窗口。
- 单点网络出口：`_fetch_payload` / `_fetch_moex_quote` / `_fetch_northbound_channel`——测试 monkeypatch 这些函数即可拦截全部外呼。
- 缓存清理：`reset_market_cache()`、`reset_market_trend_cache()`（测试与运维手动刷新）。

## 开关与参数

沿用 `bot_market_timeout_seconds` / `bot_market_cache_seconds` / `bot_market_retry_on_empty`（见 `market` 卡片）；重试退避的 sleep 单点是 `empty_backoff_sleep()`，测试在此打桩。无鉴权、无 Cookie。

## 失败时看到什么

本层永远不抛异常：失败收敛成空列表 / 空元组，由能力层给 `user_copy` 池的人话。设计上是"缺一行就少一行"：缺数、停牌（值是 `"-"`）、非数字一律跳过，绝不补 0、绝不插值、绝不用前一日顶替。走势全失败 → 卡上「暂无历史走势数据」。

## 测试与验收

离线：`tests/test_market_card.py`、`tests/test_market_backoff.py`、`tests/test_market_fin_phase1.py`、`tests/test_market_crosscheck_tencent_gbk.py`、`tests/test_finance_market_expansion.py`。回归锁覆盖：`end` 参数缺失即红、列序变更、无效 secid 静默消失、MOEX 单源失败不拖整卡。
真机：`行情` 与 `行情 俄罗斯`（MOEX 折线）、无源市场提问看「暂无」注记。
