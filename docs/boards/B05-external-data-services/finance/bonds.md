# 金融行情 · 国债收益率与期限利差

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 国债收益率与期限利差

- 层级：一级 B05 → 二级 finance → 三级 `bonds`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

债券域的数据层真身（不注册路由）：一张东财 datacenter 报表列 → 期限的映射表，加上"利差优先取上游直供列、缺了才推导并标注"的口径。它决定卡上能出现哪几个期限、哪些字段永远不该出现。

## 怎么调用

- 真身：`domains/finance/data/bond_data.py`。出口 `fetch_bond_yields(timeout_seconds, cache_seconds)`；解析 `parse_bond_snapshot(payload, fetched_at=None)` 纯函数（可直接吃真样例）；展示 `format_bond_brief`；缓存清理 `reset_bond_cache()`。
- 端点：东财 `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPTA_WEB_TREASURYYIELD&...&sortTypes=-1&pageSize=2`（免 key），`_first_row` 取最新一行。
- 列名→期限映射的**出处与自证**写在该模块头注（映射取自公开适配层源码，并用实测行做过交叉验证：利差列与两期限列逐位自洽才敢用）。改映射必须重跑那套自证，不许凭直觉换列名。
- 利差：`_spread_with_fallback` —— 优先直供列（中/美各一枚 `10Y−2Y`），缺失且两期限齐才做纯算术推导并在快照里标"计算值"。

## 开关与参数

无独立键；沿用 `bot_market_timeout_seconds` 与 `bot_market_retry_on_empty` 一族（路由级开关的实况见 [国债收益率](bond.md) 与本页所属 README 的缺陷条）。`pageSize=2`、排序方向是模块常量级形态参数。

## 失败时看到什么

- 整包失败 → `status=unavailable`，能力层给数据源失败人话。
- 单期限缺 → 该点位 `None` 并进 `missing` 列表，卡上显式列出缺哪几档。
- **1Y 永远不出现**：该报表无 1 年期列，中债官网与其他免费源在本机环境实测不可达或映射不可证 ⇒ 按「无源不接」处理，绝不用 2Y 冒充 1Y。
- GDP 年增率两列实测恒 null ⇒ 不接，不显示 0。

## 测试与验收

离线：`tests/test_bond_data.py`（列映射逐档、利差直供/推导两分支、missing 点名、无 1Y 与无 GDP 的结构断言）、`tests/test_market_fin_phase1.py`。
真机：`国债收益率` 与 `期限利差` 同义触发；对照公开收盘值时**先看交易日与口径标注**，跨日与收盘/盘中差异不算数据错。
