# L41（MEM-001 记忆服务生产接线）用户裁决材料

> **裁决材料，不构成实施。**
> 席位：MEM-DEC（v21r4-B）｜落盘：2026-09-18｜状态：**待用户裁决——未裁决、未接线、未生效**（本席零代码改动，全文只读取证）。
> 前置纪律：HANDOFF-V21R4-B-20260918.md §3.4「未裁决前 L41 不得接线」（HANDOFF-V21R4-B-20260918.md:158）。本文仅供裁决，不改变任何现状。

---

## ① 冲突原文与来源

**主来源（冲突报告正文）：`docs/design/v21r2-v2-memory-log.md` §5（:87-89），原文照录：**

> 任务书要求"memory_service 必须与既有记忆栈同源同库，不另起炉灶"；上一席落盘实现为**独立新库** `data/memory_v21.sqlite3`（memory_store_v21.py docstring 明示"不迁移不共用库文件，切换属装配席位"，理由：存量 memory_facts 表无 version/status/tombstone/expires 列，墓碑模型无法在其上成立）。本席维持上一席设计不推翻（最小 diff、零生产接线、装配裁决权在后续席位/用户），并以两处"真沿用"收敛口径：sensitivity 校验直引存量 `normalize_memory_sensitivity`；propose 即 memory_extract/reflection 后续接线的唯一入库口。若用户裁定必须同库，需在装配席位做 schema 迁移，非本席最小 diff 可容纳。

**引用链（三处登记，口径一致）：**

- `docs/design/v21r2-matrix-backfill-draft.md:55`（L41 行证据列尾）：「**前提冲突待用户裁决：独立新库 vs「同源同库」（v2 §5）**」；同文件 :105（V2 行）：「**前提冲突报告**（独立新库 vs 同源同库，v2 §5）待用户裁决」。注：该草案章节为〇/一/二/三/四，**无 §5**；任务所称「§5」即 v21r2-v2-memory-log.md §5。
- `HANDOFF-V21R4-B-20260918.md:158`（§3.4 已知的前提冲突与阻塞）：「**L41（MEM-001）前提冲突待裁决**：记忆库走**独立新库**还是**「同源同库」**？（草案 v2 §5 记为待裁决）——**未裁决前 L41 不得接线。**」；同文件 :196、:262、:292 三处重复登记。
- `plugins/bot_unified_runtime/config.py:173`（主门注释行）：「L41 memory 待用户裁决不接。」；`runtime/service_wiring.py:21`：「**L41（V21-MEM-001）刻意缺席**：记忆库走独立新库还是「同源同库」待用户裁决」。

---

## ② 现状取证（两案对比的技术事实底座）

### 2.1 v21 记忆实现真身（已实现、零接线、未 commit）

| 项 | 事实 | 证据 |
|---|---|---|
| 存储层 | `MemoryStoreV21`：四表 schema（memory_entries_v21 / memory_tombstones_v21 / memory_identity_bindings_v21 / memory_index_v21）+ partial UNIQUE `ux_memory_owner_source_event`；`__init__(path)` **path 必填无默认**；WAL + busy_timeout=1000ms + check_same_thread=False/RLock；ensure_schema 幂等 | `plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py:25`（_SCHEMA_STATEMENTS 起）、:88（类）、:91（__init__）、:106（ensure_schema） |
| 服务层 | `MemoryServiceV21`：审核/遗忘/墓碑/绑定/注入投影；sensitivity 四值词表 `("public","group","personal","credentialed")`；`propose_teaching` 为 teaching 语义挂点 | `.../character/memory_service.py:55`、:204、:286 |
| 构造方式 | 直接 `MemoryServiceV21(MemoryStoreV21(path), clock=...)`；**全树不存在名为 `build_memory_service_v21` 的函数**（rg 零命中） | `tests/test_memory_service_v21.py:60-63`（make_service 实证）；诚实修正：db-owners.md:54 与 matrix-backfill:55 所写「build_memory_service_v21 就绪」应读作「MemoryServiceV21+MemoryStoreV21 模块对就绪、可直构」 |
| 测试 | 41 例契约全绿（本席未重跑；基线证据=v2-memory-log §3 与 HANDOFF-V21R4-B 交付记录） | `grep -c "def test_" tests/test_memory_service_v21.py` = 41（本席实数）；导入走顶层垫片路径（test:27、:40） |
| 垫片 | 顶层 `character/memory_service.py`、`character/memory_store_v21.py` 均为 PEP 562 live re-export 垫片（v21r2 S8 板块重组迁移），canonical 在 `domains/chat_reply/character/` | `plugins/bot_unified_runtime/character/memory_store_v21.py:1-18`（垫片自述） |
| git 状态 | 实现/测试/装配模块/日志五文件全部 `??`（未跟踪=未 commit） | `git status --short` 本席只读实查（2026-09-18） |
| 库登记 | `data/memory_v21.sqlite3`（V2.1 S8，待生成：零生产接线，装配属后续席位；**暂无独立配置键**）；墓碑表禁清、memory_index_v21 可整表清 | `docs/db-owners.md:54` |

### 2.2 既有记忆栈现状（「同源」所指）

| 项 | 事实 | 证据 |
|---|---|---|
| 旧记忆库 | `SQLiteMemoryRepository`，表 `memory_facts`，列=fact_id/subject_user_id/session_id/memory_kind/text/confidence/source/sensitivity/scope_key/created_at/updated_at——**无 version/status/tombstone/expires 列**（v2 §5 否认同库改造的直接依据，verified） | `domains/chat_reply/character/memory.py:205-216`（建表）、:44（类） |
| 连接参数 | 旧栈 `_connect` 为普通连接，**无 WAL、无 busy_timeout** | `memory.py:237-240` |
| 配置键 | `bot_memory_enabled`（缺省 False）、`bot_memory_db_path`（缺省 ""，入 path_fields 重映射）；空 db_path=内存实现为在册契约 | `config.py:184`、:185、:1067；`docs/db-owners.md:73` |
| 生产实态 | `.env:97-100`：`BOT_MEMORY_DB_PATH=data/wuwa_memory.sqlite3`、`BOT_MEMORY_ENABLED=true`、`BOT_MEMORY_EXTRACT_ENABLED=true`——**旧栈在生产是文件库且开启** | `.env`（gitignored，本席只读抽查仅此三键） |
| 生产消费点 | ①memory_extract 回复后写入器（门=enabled∧extract∧db_path 非空∧provider=openai_compatible）；②`/bot memory` 指令路由传 db_path；③admin debug 与 smoke diagnostics 统计 memory_facts 行数 | `plugins/bot_unified_runtime/__init__.py:361-382`、:6240；`domains/ops/admin/debug.py:1175`；`domains/ops/smoke/diagnostics.py:59/:160/:205/:320` |
| 栈的其他成员 | 历史=独立库（`bot_history_db_path` 缺省 ""，表 conversation_turns）；反思=独立库（`bot_reflection_db_path` 默认 data/reflection.sqlite3）——**「既有记忆栈」本身即按功能分文件的多库格局，并不存在单一记忆总库** | `config.py:194`、:253、:1069、:1068；`domains/chat_reply/character/history.py:316-318`、:626 |

### 2.3 DatabaseBroker 白名单机制是否涵盖记忆表

- 机制：仅注册 query_id 可执行 + 参数化 + 只读连接（mode=ro）+ 2s/200 行有界执行，注册期静态拒绝任意 SQL（database_broker.py:1-27 四层安全模型）。
- **默认注册表五个查询全部指向 send_queue / affinity / ledger / audit / subscriptions 五库，不涵盖 memory_facts，亦不涵盖 memory_v21 四表**（`runtime/database_broker.py:344` 起 build_default_registry，:346-353 docstring 列举）。broker 本身「不改任何存量库的写入路径」（:27）。
- 结论：**两案与 DatabaseBroker 收口均无耦合**——无论记忆落在哪个文件，后续都可通过注册新 db 别名+query_id 纳入只读查询面；broker 不影响写路径选型。

### 2.4 装配组现状（接线要落进去的框架）

- 主门 `bot_v21_service_wiring_enabled` 缺省 False（`config.py:174`），分门=worldbook/knowledge（新键缺省 False，config.py:176/:178）+ teaching/database_broker（复用既有键）；生产调用点 `__init__.py:4124` 起主门门控 + fail-open（:4129/:4132 grep 实证）。
- `V21_SERVICE_WIRING_IDS` 仅四 id，**memory 不在列**（`runtime/service_wiring.py:53-58`）；teaching 分支已留挂点：`TeachingService(path)` 构造时「memory_service 刻意不传（None），零 memory 依赖」（service_wiring.py:158）。
- 可照抄的先例=teaching：config 键带真实默认路径（`bot_teaching_db_path` 默认 `data/teaching_knowledge.sqlite3`，config.py:166）+ path_fields 登记（config.py:1110）+ 装配分支 runtime_path 解析（service_wiring.py:141-156）+ db-owners 登记（db-owners.md:55）；persona_service.py:33 已把「memory_v21.sqlite3 先例」引作 path 解析样板。

---

## ③ 两案技术对比

### 案 A：独立新库（现实现默认落点 `data/memory_v21.sqlite3`）

| 维度 | 评估 |
|---|---|
| 实现改动 | **零**。现实现即按 A 落盘（memory_store_v21.py 建四张 `*_v21` 独立表；db-owners.md:54 在册）。 |
| 迁移成本 | 零（空库起步）。**已知取舍**：旧 memory_facts 存量事实不进 v21 库；v21 propose 定位为 memory_extract/reflection 后续接线的唯一入库口（v2-memory-log.md:89），旧栈继续按现契约运行。 |
| 隔离性 | 最优。墓碑「禁清」、投影「可整表清」（db-owners.md:54）落在独立文件上，与 wuwa_memory.sqlite3 的备份/清理语义互不纠缠。 |
| 备份恢复 | 独立文件独立备份；损坏爆炸半径不波及聊天记忆活数据。 |
| DatabaseBroker 收口 | 无耦合（§2.3）。 |
| 接线工作量级 | **小（装配级）**：①config 新键（建议 `bot_memory_v21_db_path`，默认 `data/memory_v21.sqlite3`）+ path_fields + config-catalog + .env.example + doc_sync 门同步；②service_wiring 增 "memory" id + build 分支（照 teaching 模板约 20 行）+ gates 映射（分门键可复用新键非空判定或另立 `bot_memory_v21_enabled`）；③根 `__init__.py` 装配点已在主门内、零改动。 |
| 回归面 | 41 例契约 + doc_sync/config-catalog 门禁 + runtime-layout + ruff/mypy 本域；不触碰任何旧栈消费点（§2.2 表），旧链路零回归风险。 |
| 可逆性 | **高**。分门/主门关闭=零装配零副作用；日后若改选 B，可写 attach+copy 迁移脚本（v21 行永不 DELETE 语义保留，迁移方向单行道可审计）。 |

### 案 B：同源同库（两个可执行的读法）

**B1（轻读法）：同文件并存**——`MemoryStoreV21` 直接指向 `bot_memory_db_path`（生产=`data/wuwa_memory.sqlite3`），四张 `*_v21` 表与 `memory_facts` 同文件并存，不动旧表。

- 满足「同库、不另起炉灶」字面；无 schema 迁移；实现改动≈A（装配时换 path 来源即可）。
- **新增冲突面**：①同文件双连接写竞争——旧栈连接无 WAL/busy_timeout（memory.py:237-240），v21 连接 WAL+1000ms（memory_store_v21.py:91-101），需补并发回归验证；②备份/清理语义耦合——db-owners 对 wuwa_memory 的登记必须改写以覆盖「v21 墓碑禁清」，误清旧库即连带毁墓碑（项目铁律：运行数据不可删，高危区）；③生命周期被单键绑定——`bot_memory_db_path` 清空即旧栈回退内存实现（db-owners.md:73 契约），v21 库随之落空；④v21 分门与旧 `bot_memory_enabled` 语义纠缠。
- 工作量级：装配级同 A ＋ db-owners 改写 ＋ 双连接并发回归（新增）。可逆性：**中**（B1→A 需拆表迁移）。

**B2（重读法）：改造 memory_facts 表本体**——在 wuwa_memory.sqlite3 的 memory_facts 上加 version/status/tombstone/expires 列与部分唯一索引，v21 服务直读直写该表。

- v2 §5 否决理由 verified：存量表确无这些列（memory.py:205-216），墓碑模型（永不 DELETE+行翻 forgotten+墓碑防复活）无法在现表上成立；「若用户裁定必须同库，需在装配席位做 schema 迁移，非本席最小 diff 可容纳」（v2-memory-log.md:89）。
- 工作量级：**大**——生产表 DDL 迁移 + 全部旧栈消费方回归（memory_extract 写入器 __init__.py:361-382、/bot memory 路由 :6240、chat 注入统计 chat.py:2414、admin debug :1175、smoke diagnostics）+ 新旧语义行级映射设计。可逆性：**低**（生产聊天记忆表 schema 手术，反向迁移难，事故直达「不可删」活数据）。

### 对比速览

| 维度 | A 独立新库 | B1 同文件并存 | B2 改造 memory_facts |
|---|---|---|---|
| 实现改动 | 零 | ≈A | 大（schema 迁移） |
| 旧栈回归风险 | 零 | 低-中（双连接） | 高（五个消费点全回归） |
| 备份/清理 | 独立最干净 | 耦合 | 耦合且高危 |
| 与任务书字面 | 相悖（待裁决豁免） | 相符 | 相符（且是重读法） |
| 可逆性 | 高 | 中 | 低 |

---

## ④ 推荐案与理由

**推荐案 A（独立新库，`data/memory_v21.sqlite3`）。**

1. **最小 diff 且已验证**：现实现即 A，41 例契约按 A 写就并全绿（基线）；选 A=零实现改动、纯装配增量，选 B 任何一个读法都要新增实现/迁移工作。
2. **数据模型不兼容是结构性事实**：memory_facts 无 version/status/tombstone/expires 列（memory.py:205-216 实证），墓碑模型无法其上成立；B2 需对生产聊天记忆活数据做 schema 手术，触碰「运行数据不可删」铁律高危区，收益率最低风险最高。
3. **「既有记忆栈」本非单一库**（memory/history/reflection 各自独立文件，§2.2）——「同源同库」中的「库」在现状里并无唯一所指，A 并未破坏任何现存同源格局，只是新增一个按功能分文件的同级成员，与栈的既有组织方式一致。
4. **故障与运维隔离**：墓碑禁清/投影可再生两种截然相反的清理语义（db-owners.md:54）落在独立文件上最不易误操作；备份恢复互不波及。
5. **可逆性保底**：A→B 未来可迁移（attach+copy），B→A（尤其 B2）成本陡增；先 A 后续想合库仍有路，先 B2 想反悔几乎没有。
6. DatabaseBroker 收口两案皆不受影响（§2.3），不构成选 B 的理由。

**若用户坚持字面「同库」**：请选 B1（同文件并存）并接受其冲突面清单，**不建议 B2**。

---

## ⑤ 用户裁决清单（勾选即裁决）

**主裁定（单选）：**

- [ ] **A. 独立新库**（推荐）——维持现实现落点，纯装配接线
- [ ] **B1. 同源同库·同文件并存**——`*_v21` 四表并入 `bot_memory_db_path` 指向的库（生产=wuwa_memory.sqlite3）与 memory_facts 并存
- [ ] **B2. 同源同库·改造 memory_facts 本体**——生产表加列迁移（不建议，见 §④.2）
- [ ] 暂不裁决，L41 继续保持 not_wired

**若选 A，附加裁定：**

- [ ] 新库路径键名：`bot_memory_v21_db_path`（建议）／其他：＿＿＿＿；默认值 `data/memory_v21.sqlite3`（建议）／其他：＿＿＿＿
- [ ] 分门形态：复用「路径键非空」即接（teaching 式）／另立 `bot_memory_v21_enabled` 缺省 False（更保守）
- [ ] 旧 memory_facts 存量事实**不迁移**进 v21 库（建议，现状取舍）／要求迁移（需追加迁移脚本席位）

**若选 B1，附加裁定：**

- [ ] 确认接受 db-owners 的 wuwa_memory 登记改写（覆盖「v21 墓碑禁清」语义）
- [ ] 旧栈连接是否补 WAL/busy_timeout 以对齐双连接并发口径（建议补）

**后续归属（无论何案）：** 裁决后由装配席位按本 memo §2.4 框架接线（service_wiring 增补+config 键+门禁同步），接线属另席实施，本 memo 不构成实施。

---

## 附：诚实边界

- 本席未重跑任何测试（41 例全绿系转述 v2-memory-log §3 与 HANDOFF-V21R4-B 交付记录的基线证据，非本席实跑）；未做任何真实 LLM 调用；未做任何 git 写操作。
- `build_memory_service_v21` 函数名在全树不存在（rg 零命中，本席实查）——matrix-backfill:55 / db-owners.md:54 的该表述为名称失真，实际就绪物=MemoryServiceV21+MemoryStoreV21 模块对（可直构）。
- 旧库 wuwa_memory.sqlite3 的行数/体积未查（避免触碰运行数据，标 unknown）；v21 未来消费面（chat 注入点、/bot memory 管理指令迁移、控制面管理 UI）超出 L41 装配范围，未调研（unknown）。
- 全文状态口径：L41 production_wiring = **not_wired**；主门 `bot_v21_service_wiring_enabled` 缺省 False；全批未 commit、未重启、未部署（HANDOFF-V21R4-B-20260918.md:3）。
