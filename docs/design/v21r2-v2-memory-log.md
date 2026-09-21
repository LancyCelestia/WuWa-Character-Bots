# v21r2 V2 席（S8 记忆服务补全）工作日志

席位：V2.1 批次 V2 席 / S8 记忆服务补全（V21-MEM-001）。
日期：2026-09-17。工作树多席并行 WIP，本席只动：`character/memory_service.py`、`character/memory_store_v21.py`（上一席已落盘的配套存储层，bug 修复必需）、`tests/test_memory_service_v21.py`、`docs/db-owners.md` 追加行。

## 0. 磁盘真态核实（rg + ls 实证）

- `plugins/bot_unified_runtime/character/memory_service.py` **存在**（36903B，09-17 09:09）。
- `tests/test_memory_service_v21.py` **存在**（25625B，09-17 16:06）。台账 #36⑦ 所述 ：39 非法占位行**已被注释化解**（注释文本在盘），AGENTS.md 收尾巡检"文件缺失"结论过时。
- 上一席还落盘了配套存储层 `character/memory_store_v21.py`（四表 SQLite）。
- 引用面：全仓仅 `tests/test_memory_service_v21.py` 引用二者，**零生产接线**（装配属后续席位），修改面安全。
- 基线实跑（venv 直跑，`--basetemp=%TEMP%/v21r2-v2-baseline`）：**12 failed / 25 passed**。

## 1. 对照 V21-MEM-001 三张清单（通读 + 基线实跑得出）

### 已实现（保留）
- 记忆实体字段齐备：owner/session/source/confidence/created_at/used_at/expires_at(TTL)/version/status(active|pending_review|forgotten)/kind 五值封闭枚举（preference/fact/event/reflection/proposal）；人格/权限/路由在类型系统上不可表达（`MemoryKind("persona")` ValueError）。
- 生命周期：propose（pending_review 提议）→ approve（管理员专属，MemoryPermissionError 门）/ reject（留痕墓碑 reason=reject，永不注入）。
- 遗忘=墓碑：forget 固定顺序（先写墓碑提交→清索引→清缓存→活动行退役）；sweep_expired（TTL 清扫 reason=ttl）；查询层 SQL 永远带墓碑排除（`NOT IN tombstones`）。
- 重建：rebuild_projection 先重放墓碑（同 id 行强制 forgotten + 清索引）再重建投影索引。
- 备份恢复：backup_to（SQLite backup API 在线备份含墓碑表）/ restore_from（先取存量墓碑→页级恢复→墓碑回插→重放→重建）。
- 隔离：owner+session 作用域过滤在存储层 SQL 强制；跨平台身份默认不合并，显式绑定表（memory_identity_bindings_v21）才合并；共享知识（owner_id='shared'）审核制。
- 注入同源：build_injection_preview 与 build_injection_plan 同一函数（预览仅 refresh_used_at=False）。
- 教导红线：propose_teaching 只许 preference/fact，source 强制 teaching。
- 审计面：audit_records（含 forgotten 原文）/ audit_tombstones（不留原文只留摘要指纹）。

### 缺失（本席补全）
- M1【forget 权限校验】任何人可遗忘任何人的记忆（无 owner/admin 校验）——跨用户操作面失守。补：本人（forgotten_by==owner_id）或管理员（actor_role）才可；查无此 ID 先报 MemoryNotFoundError。
- M2【MemoryDraft.text 空白校验】`text="  "` 可过 DTO（仅 min_length=1）；platform/session_id/source 有 strip 校验，text 漏了。
- M3【sensitivity 口径未真沿用】docstring 声称"MEMORY_SENSITIVITIES 口径沿用"，实际未引用存量 `character/memory.py` 的 `normalize_memory_sensitivity`（public/group/personal/crededentialed 四值），sensitivity 是自由字符串。补真引用。
- M4【恢复后绑定丢失】restore_from 只保留墓碑，备份之后新建的跨平台绑定随整库替换丢失。补：与墓碑同模式保留（先取→替换→回插）。
- M5【反思来源实证】source 自由字符串可承载 reflection，但无测试证明反思来源记忆字段齐备且可注入——补测试锁。

### 有 bug（基线 12 failed 根因，全部实跑定位）
- B1【幂等 UNIQUE 索引缺失｜store 真缺陷】docstring 声称"幂等键 UNIQUE(owner_id, source_event_id)"，schema **根本没建该约束**：8 线程同 source_event_id 并发 propose 产生 8 行（基线 `assert 8 == 1`）。修：partial unique index `(owner_id, source_event_id) WHERE source_event_id <> ''`（空串不参与幂等的既有语义由 WHERE 保留）。
- B2【touch_used 缓存不失效】刷新 used_at 后不清候选缓存 → 后续注入计划读到旧 used_at，recency 分不变（基线 `assert 0.27 > 0.27`）。修：touch_used 内按行所属 scope 逐出缓存。
- B3【初始激活版本虚高】propose 规则自动批准走 _activate 使 version 1→2；初始激活应为 version 1，管理员批准才 +1（低置信→approve 断言 version==2 与直批断言 version==1 两测试共同锁定的契约）。修：_activate 加 bump_version 参数。
- B4【排除归因候选面缺口】注入计划候选取数 statuses=(active,pending)+SQL 排除墓碑行 → 被遗忘/被拒记忆根本不进候选，excluded 归因（reason=tombstone）永远为空（基线 `assert [] == [TOMBSTONE]`）；docstring 承诺"预览含被排除原因（tombstone/…）"未兑现。修：候选改含 forgotten 行且不排除墓碑（读路径逐条 has_tombstone 复核兜底，排除保证不受影响）。
- T1【测试自身缺陷×7】①stale_cache 用 insert_entry 模拟复活撞 PK（IntegrityError）→ 改 update_entry 翻 status；②budget 用例预算 200 装不下 300 字首条，断言方向反了 → 预算改 302；③proposal 用例吃 draft() 默认 source="teaching" 撞教导红线 → 显式 source="extraction"；④blank_source_event 用 audit[0] 在同刻 created_at 平局下取错行 → 改对照捕获的 first id；⑤preview=real 用例在真实注入跑完之后才取 before used_at → 重排断言顺序；⑥test_plan_rejects_unknown_fields 走 tmp_path_probe() 泄漏临时目录 → 改 tmp_path fixture；⑦forget 管理员调用点缺 actor_role="admin"（配合 M1 新签名）。

## 2. 改动坐标（最小 diff）

### character/memory_store_v21.py
- `_SCHEMA_STATEMENTS` 追加：`CREATE UNIQUE INDEX IF NOT EXISTS ux_memory_owner_source_event ON memory_entries_v21 (owner_id, source_event_id) WHERE source_event_id <> ''`（B1）。注：v21 库为全新库未投产，无存量重复行迁移问题；若异常库存在重复行，建索引会响亮失败（诚实暴露，不做静默降级）。

### character/memory_service.py
- `MemoryDraft`：text 非空白校验（strip）；sensitivity 经 `character/memory.py normalize_memory_sensitivity` 校验（M2/M3）。
- `forget`：签名加 `actor_role: str = "user"`；查无先 NotFound，再校验 本人(owner_id==forgotten_by) 或 admin 角色（M1）。
- `touch_used`：更新后按行 scope `_evict_cache`（B2）。
- `_activate`：加 `bump_version` 参数；propose 自动批准路径 bump=False（B3）。
- `_cached_scope_rows`：候选取数 statuses=(ACTIVE,PENDING,FORGOTTEN)+exclude_tombstones=False，注释同步（B4）。
- `restore_from`：墓碑保留逻辑同样应用于绑定表（M4）。

### tests/test_memory_service_v21.py
- 修复 T1 组 7 处测试缺陷；新增：重建等价（重建前后查询面逐字段等价）、反思来源字段齐备+可注入、sensitivity 四值+非法值拒绝、forget 管理员/本人/越权三态、恢复后绑定保留。

## 3. 实跑记录（命令+输出）

解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe`，env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=%TEMP%/v21r2-v2-*` `-p no:cacheprovider`，全程未触 dev.ps1。

1. **基线**（修复前）：`pytest tests/test_memory_service_v21.py` → **12 failed / 25 passed**（6.65s）。失败根因见 §1。
2. **修复后**：同命令 → **41 passed**（7.88s，含新增 4 例：重建等价×2/反思来源/sensitivity）。
3. **存量回归**：`pytest tests/test_memory_sanitize.py tests/test_memory_router_reuse.py tests/test_persona_prompt_and_memory.py tests/test_reflection.py` → **33 passed**（2.79s）。
4. **终跑合跑**：v21 测试 + 存量回归 4 文件 → **74 passed**（9.83s）。
5. **Ruff**：`ruff check memory_service.py memory_store_v21.py test_memory_service_v21.py` → **All checks passed!**（修掉 I001/RUF100 死占位注释/C408/BLE001 四项，均测试文件内）。
6. **mypy**（仓库口径 `--explicit-package-bases --ignore-missing-imports`）：本席两源文件 **0 错**；输出仅 control_plane/api/platform.py 2 错（台账 #36 已记录的既有错，非本席引入）。
7. **树卫生**：无源码树 `data/` 残留；`qx.json` 完好；`tests/__pycache__` 两枚 .pyc 为并行兄弟席位运行残留（非本席产物，未动避免竞态）。
8. **登记**：db-owners.md 第二节追加 memory_v21 一行（四表+partial UNIQUE 索引）；v21r2-COORDINATION.md 追加状态行（UTF-8 字节验证零损伤）。

## 3.1 改动文件清单（本席实际触碰）

- `plugins/bot_unified_runtime/character/memory_store_v21.py`（+幂等 partial UNIQUE 索引）
- `plugins/bot_unified_runtime/character/memory_service.py`（forget 权限/touch_used 缓存失效/_activate bump_version/候选面归因/DTO text+sensitivity 校验/restore 保绑定/import）
- `tests/test_memory_service_v21.py`（修 7 缺陷+新增 4 测试+删死占位注释+Ruff 四项）
- `docs/db-owners.md`（仅追加一行）
- `docs/design/v21r2-v2-memory-log.md`（本日志，新建）
- `docs/design/v21r2-COORDINATION.md`（追加一行）

未触碰：验收矩阵（按令）、config.py（本席零新增配置键，故 A26 无增量）、capabilities/、__init__.py 及其余禁触域。

## 4. V21-MEM-001 四列状态行

| 行 | implementation | production_wiring | offline_validation | live_validation |
|---|---|---|---|---|
| V21-MEM-001 记忆审核/遗忘/重建与备份墓碑；跨用户/拒绝记忆隔离，恢复后不复活 | done（memory_service.py+memory_store_v21.py，本席修 4 bug 补 5 缺失；confidence=high） | not_wired（零生产接线；装配属后续席位；build_memory_service_v21 装配入口已备，默认库经 runtime_path 重映射） | done（tests/test_memory_service_v21.py 全绿实跑，见 §3；confidence=high） | unknown（无生产 bot 实跑） |

## 5. 前提冲突报告（不自行改前提）

任务书要求"memory_service 必须与既有记忆栈同源同库，不另起炉灶"；上一席落盘实现为**独立新库** `data/memory_v21.sqlite3`（memory_store_v21.py docstring 明示"不迁移不共用库文件，切换属装配席位"，理由：存量 memory_facts 表无 version/status/tombstone/expires 列，墓碑模型无法在其上成立）。本席维持上一席设计不推翻（最小 diff、零生产接线、装配裁决权在后续席位/用户），并以两处"真沿用"收敛口径：sensitivity 校验直引存量 `normalize_memory_sensitivity`；propose 即 memory_extract/reflection 后续接线的唯一入库口。若用户裁定必须同库，需在装配席位做 schema 迁移，非本席最小 diff 可容纳。
