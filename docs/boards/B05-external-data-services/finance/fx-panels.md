# 金融行情 · 汇率面板与定向换算

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 汇率面板与定向换算

- 层级：一级 B05 → 二级 finance → 三级 `fx-panels`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

汇率域的数据层真身（不注册路由）：哪些货币对**有源**、是什么口径（现汇/现钞/中间价/100 单位）、缺币怎么登记、交叉价怎么算。`fx` 入口只消费这一层，"能不能报这个数"由这里的覆盖表说了算。

## 怎么调用

- 真身：`domains/finance/data/fx_data.py`。覆盖表读点 `fx_pair_availability()`（有源 → `eastmoney:<secid> <rate_type>`；无源显式登记在 `FX_UNAVAILABLE_PAIRS`），条数以该文件为准、文档不手写。
- 主源：东财 `push2 ulist.np/get?fltt=2`，字段 f2=汇率 / f3=涨跌% / f4=涨跌额 / f12=代码 / f13=市场号 / f14=名称 / f18=昨收；已实测 secid 与市场号规律（直盘、人民币中间价、离岸人民币各成一族）写在该文件头注。
- 单位口径：`unit_base`（如 100 日元一档的中间价），展示与换算都经它折算，避免"1 日元 ≈ 4.36 人民币"这种量级事故。
- 备选源：`open.er-api.com/v6/latest/{base}`（快照链路，函数 `fetch_fx_snapshot`）；**诚实边界**：该端点在本机环境实测同样不可达，因此它只作为已实现但常态失败的兜底，不是"另一个一定能用的源"。
- 交叉价：`cross_rate_from_usd(usd_table, base, quote)` 纯函数（USD 三角），换不出 `None`。
- 单点网络出口：`_fetch_payload`（东财）、`_fetch_fx_payload`（快照）；缓存清理 `reset_fx_cache()`。

## 开关与参数

无独立键（沿用 `bot_fx_enabled` 与 `bot_market_*` 族）。基准货币、目标集合是 `fetch_fx_snapshot(base, targets)` 的参数，由调用方显式给；解析层的"面板 vs 换算"语义在 `parse_fx_query` / `wants_major_rates`，加新币只改这一处。

## 失败时看到什么

这一层不产生用户可见文案，只交状态：缺行或 f2 非数的货币对**直接跳过**（绝不造数）、`missing_currencies` 显式列出缺哪些、整体失败 `status=unavailable`、`updated_at` 解析不出来就留 `None`（不硬造"更新时间"）。日 K 实测全空 ⇒ `history` 恒空，上层写"暂无历史走势数据"。

## 测试与验收

离线：`tests/test_fx_data.py`（覆盖表、无源对、单位口径、交叉价 None、快照缺币）、`tests/test_fx_card_semantics.py`。回归锁包含"新增无源币种必须进登记表"的形态断言。
真机：`汇率 美元 兑 韩元`（直盘）、`新台币`（应点名无源）、`AED 汇率`（同上）。
