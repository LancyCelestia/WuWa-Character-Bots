# 金融行情 · 国债收益率

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.finance · 国债收益率

- 层级：一级 B05 → 二级 finance → 三级 `bond`
- 路由席位：`BOND`（matcher `bond`，command=True）
- 判定优先级：38
- 能力 id：`bot.bond`
- 实现落点：`plugins/bot_unified_runtime/domains/finance`
- 帮助主题：国债收益率
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`国债收益率` / `期限利差`：中美两国 2/5/10/30 年期国债收益率与 10Y−2Y 期限利差，一张卡，带交易日、收盘口径与延迟标注。**没有 1 年期这一行**（无源），也不自行拼凑其他期限组合。

## 怎么调用

- 席位 `BOND`、能力 id `bot.bond`；闭包 `domains/finance/capabilities/market.py:build_bond_capability(config, *, render_backend)`，谓词 `is_bond_command`（短文本、无链接；「债券基金」撞非债语境时让路）。
- 数据真身：`domains/finance/data/bond_data.py:fetch_bond_yields(timeout_seconds, cache_seconds)` → `BondYieldSnapshot`（各期限 `BondYieldPoint`，缺数 `value=None`）→ `format_bond_brief`；卡走 sections/rows 契约。
- 期限利差的取数口径见同目录机制页 [国债收益率与期限利差](bonds.md)（优先取上游直供利差列，缺失才纯算术推导并标"计算值"）。

## 开关与参数

- 开关读点：`domains/chat_reply/runtime/base_router.py` 以 `getattr(config, "bot_bond_enabled", True)` 判定，但 **`config.py` 未声明该字段** ⇒ 线上关不掉（缺省恒 True），属欠账非旋钮（详见本功能 README 现行缺陷）。
- 超时/缓存沿用 `bot_market_timeout_seconds`、`bot_market_cache_seconds`、`bot_market_retry_on_empty`。
- 优先级 38（拆位后）——代码已在、线上未生效，待提交与重启。
- 报表端点、列名→期限映射的出处与交叉验证方法都写在 `bond_data.py` 头注，属该文件事实。

## 失败时看到什么

- 整表拉不到：数据源失败人话，不出半张卡。
- 单个期限缺：该点位 `unavailable` 并在"缺项"里点名，不留空也不补 0。
- 利差上游列缺失且两期限都在：给推导值并**明确标注是计算值**；两期限不齐则整条利差不出。
- GDP 年增率列实测恒 null ⇒ 该字段不接，卡上不会出现"GDP 零值"这类假值。

## 测试与验收

离线：`tests/test_bond_data.py`（列映射、缺数三态、利差优先取直供列与回退推导的分支、无 1Y 的结构断言）、`tests/test_market_fin_phase1.py`。
真机：`docs/acceptance-manual.md` §6.6.3 ②；`国债收益率` 出卡且**无 1Y 行**，`债券基金`、`货币基金` 不应触发本入口。
