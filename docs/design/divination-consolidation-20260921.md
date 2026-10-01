# 占卜域双实现：判定与收编方案（2026-09-21，用户裁定 11 的条件句已核完）

> 用户原话：**「11.C（如果两个算法都合理就 C 合并到一起，如果不好的话就保留最好用的那一套）」**。
> 本文是那条条件句的**判定结果**，同时是实施席 WP9 的施工依据。
> 取证方式：逐符号 grep + 消费方反查（未整读大文件），2026-09-21 主会话亲核。

## 一、实况：不是"两套完整实现"，而是**两套各自缺半边**

| 面 | `data/draw_store.py`（行数以该文件真身为准，**聊天能力在用**） | `domains/divination/store/draw_store.py`（行数以该文件真身为准，**控制面 REST 在用**） |
|---|---|---|
| 入口证据 | `domains/divination/capabilities/divination.py:40` import；`:443` 文档写明"注入 draw_store 即启用持久化"；`:636/:654` 真消费 | `plugins/bot_unified_runtime/control_plane/api/divination.py:47` import `store.draw_store.DrawError` |
| **算法**（牌库索引/card_id 反查/牌库版本/发牌 PRNG/日程键） | ✅ **全**：`build_card_index:90`、`card_id_for:115`、`_compute_deck_revision:123`（sha256[:16]）、`validate_spread:181`、`SeededPrng:194`/`HmacPrng:225`（确定性可复现）、`daily_fortune_day_key:261` | ❌ 无，另抄了一份索引：`domains/divination/service/tarot_draw.py:51 build_card_index`、`:86 card_id_for`（牌库本体 `data.tarot.DECK` 是共用的，抄的是**构建与反查**） |
| **存储**（表/幂等/配额/版本留痕） | ⚠ 只有两张"够用"表：`daily_fortune:350`、`tarot_draws:362`，幂等靠 `INSERT OR IGNORE:443` | ✅ **全**：`draws:102`（`draw_id` PRIMARY KEY + `idempotency_key` UNIQUE:124 + dedupe UNIQUE:125）、`QuotaPolicy:60`、列含 `algorithm_revision/deck_revision/key_id/seed_digest` |
| **异常类型** | `class DrawError:70` | `class DrawError:50` ——**同名两个类**，且 `domains/divination/service/tarot_draw.py:28` 引的是 **store 的**，而 `:22` 引牌库用 data 侧 ⇒ 同域内 `except DrawError` 存在"捕不到另一颗"的结构性风险（与 D6 在册的"同名类跨包 except 互不命中"同族） |

**判定**：两套都**不是废件**，也都**不完整**。所以她条件句的第一支成立 —— **按 C 合并**；
但合并的切法不是"共用一个 DB 实例"这么粗：**按面各取一边**。

## 二、收编方案（唯一真身 = 算法取 data、存储取 store、异常取一份）

1. **算法真身 = `data/`**：`build_card_index`/`card_id_for`/`_compute_deck_revision`/`SeededPrng`/`HmacPrng`/`validate_spread`/`daily_fortune_day_key`
   → 抽为 `domains/divination/service/deck_math.py`（或直接留 data 并由 store 复用，**由实施席按 import 图择一，但全仓只能有一份**）。
   `domains/divination/service/tarot_draw.py:51/:86` 的副本**删除改复用**（尺子②：一个事实一份）。
2. **存储真身 = `store/DrawStore`**（它有幂等/去重/配额/版本列，是 V2.1-S12 合同口径的载体）：
   - `data/` 的 `daily_fortune` 与 `tarot_draws` **迁入** `draws` 同构模型：`kind` 维（fortune/tarot）+ `scope_key`（day_key / draw_id），
     或退一步：`data/` 的两个方法改为**委托** `store/DrawStore`，自身不再开库（**推荐这条**，改动面更小、不动现有表）；
   - 单一 `DrawError`（`store/` 保留，`data/` 改为 re-export 或一并迁入），锁死"同域只许一颗"。
3. **运行数据不可丢**（铁律 2）：用户历史抽牌存在 `daily_fortune`/`tarot_draws` 两表内 ——
   **不 DROP、不清空**。迁移走「先双读影子 → 再单读真身」；任何一次性搬运都要**守恒断言**（人数/条数/按 day_key 分组数一致）
   + 迁移前 `%TEMP%` 备份（本仓既有规程）。
4. **抽牌可复现性不得退化**：`HmacPrng` 的 seed 材料（day_key + key_id）与 `deck_revision`/`algorithm_revision` 三件必须
   一起落到同一行，否则"同一天同一人重抽变牌"这种用户可感知问题会重新出现。今天 data 侧有 seed、store 侧有版本列，
   **合并后必须同时具备**（这条要写成测试）。
5. **幂等语义对齐**：data 侧 `INSERT OR IGNORE`（同键静默忽略）与 store 侧 `idempotency_key UNIQUE`（并发只建一次）
   语义接近但**返回值不同**（前者拿不到"是否新建"）⇒ 合并后统一为 `(record, created: bool)` 契约，聊天侧提示语据此走。

## 三、验收（实施席必须给实跑）

- 抽一次塔罗 → 聊天与控制面 REST **看到同一条记录**（今天看不到：两张表两个库路径）；
- 同一 `day_key` 重抽 → 返回同一副牌且 `created=False`（可复现 + 幂等）；
- 配额用尽 → 两侧同语义拒绝（今天只有 store 侧有 `QuotaPolicy`，聊天侧无配额）；
- `except DrawError` 在两条路径上都能捕到（锁"只有一颗异常类"）；
- 全仓 `grep` 证明 `build_card_index`/`card_id_for`/`DrawStore`/`DrawError` **各只剩一处定义**（尺子①②判据）；
- 既有 `tests/test_divination*.py`、`test_divination_service_v21.py`、`test_multi_calendar.py` **一条不许摘牌**。

## 四、需要主会话配合的事（席不得自行动手）
- 若需要新配置键（例如把配额做成可配：`bot_divination_quota_*`）→ 写日志交接段，**`config.py`/catalog/`.env.example`/`SETTABLE_KEYS` 由主会话统一落**；
- 若必须动 `docs/db-owners.md` 登记表迁移 → 写交接段（该文件另有旧路径棘轮，由 WP11b 席在收）；
- 禁 `--write` 重录生成物；收尾由主会话集中做一次。
