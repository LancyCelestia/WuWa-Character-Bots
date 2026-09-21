# L41（MEM-001 记忆服务生产接线）即插执行预案

> **预案，不构成实施授权。**
> 席位：L41-PLAN（v21r4-B）｜落盘：2026-09-18｜状态：**待用户裁决——未裁决、未接线、未生效、未实施**（本席零代码改动，全文只读取证 + 本文档）。
> 用途：用户在 wave-snapshot §二勾选裁决后，装配席按本预案直接施工，把「裁决→落地」缩到最短。
> 输入：`docs/design/v21r4-L41-decision-memo.md`（MEM-DEC 裁决材料，推荐 A 案）；WIRE-SVC 席装配先例（`runtime/service_wiring.py` + 根 `__init__.py` 插入段 + `tests/test_v21_wire_svc_assembly.py`）。
> 坐标纪律：**本文全部 file:line 均为本席 2026-09-18 实读核实**，未验坐标一律标 unknown；对 memo 坐标的勘误见 §6。

---

## 〇、前置与授权边界（先读）

1. **两案（A/B）均须用户在 `docs/design/v21r4-b-wave-snapshot.md` §二裁决后才可动码**：
   - wave-snapshot §二 = 统一裁决清单（:45）；L41 记忆库 = 组 2（§2.2，:82-96）：主裁定单选 **A 独立新库 / B1 同文件并存 / B2 改造 memory_facts 本体 / 暂不裁决** + 各案附加项。
   - 前置纪律原文（本席实读核实）：`HANDOFF-V21R4-B-20260918.md:158`「**未裁决前 L41 不得接线。**」
   - memo 裁决清单：`docs/design/v21r4-L41-decision-memo.md` §⑤（:117-137）。
2. **本文档不是实施授权**：裁决前 `runtime/service_wiring.py` 对 memory 相关模块零 import 零引用（service_wiring.py:21-23 实读），必须维持。
3. 现状口径（全部实读核实）：L41 production_wiring = **not_wired**；主门 `bot_v21_service_wiring_enabled` 缺省 False（config.py:174）；`V21_SERVICE_WIRING_IDS` 仅四 id、memory 不在列（service_wiring.py:53-58）；全批未 commit、未重启、未部署。
4. 本预案只覆盖**装配接线**（service_wiring 增补 + config 键 + 门禁同步 + 测试）；v21 记忆的消费面（chat 注入点、/bot memory 管理指令迁移、控制面 UI）**不在 L41 范围**（memo §附：145 同口径，unknown 不展开）。

---

## 一、共同装配面（两案共用，WIRE-SVC 先例坐标）

### 1.1 装配调用链与插入点

```
bot.py → 插件加载 → 根 __init__.py 主门门控装配段 → register_v21_services(config)
       → build_v21_services（各服务分支）→ _SERVICES 注册表 → 消费方 get_v21_service(id)
```

| 环节 | 坐标 | 实读事实 |
|---|---|---|
| 根装配段 | `plugins/bot_unified_runtime/__init__.py:4124-4144` | :4126 主门 `if getattr(config, "bot_v21_service_wiring_enabled", False):`；:4128-4130 惰性 import；:4132 `register_v21_services(config)`；:4133-4138 有注册才 info 日志；:4139-4144 整段 try/except fail-open（warning 不崩主链路）。**A 案此文件零改动**（见 §2.3-S4） |
| 装配模块 | `plugins/bot_unified_runtime/runtime/service_wiring.py` | :53-58 `V21_SERVICE_WIRING_IDS` 四 id 元组；:61 `_SERVICES` 进程内注册表；:64-77 `v21_service_gates`（主门 ∧ 分门 dict）；:80-87 `build_v21_services(config, *, 显式路径 kwargs)`；:96-106 `_assemble` 单服务 fail-open 帮手（except → warning → 跳过）；:136-161 **teaching 分支＝照抄模板**（惰性 import → `runtime_path` 解析路径 :142-157 → 构造 :159）；:165-170 `register_v21_services` 先清后填幂等；:173-175 `get_v21_service` 未装配一律返回 None；:182-184 `reset_v21_services` |
| 门键定义 | `plugins/bot_unified_runtime/config.py` | :174 主门（False）；:176 worldbook（False）；:178 knowledge（False）；:165-166 teaching 分门+路径键先例（True / `data/teaching_knowledge.sqlite3`） |
| 路径重映射 | `scripts/runtime_paths.py:60-75`（`runtime_path`）；config 侧解析闭包 `config.py:1043-1051` + 应用循环 :1115-1116 | 两侧对齐口径（互为镜像，:66-67 与 config.py:1043-1044 注释互指）；`data/...` 相对路径重映射进 `BOT_RUNTIME_DATA_DIR`（runtime_paths.py:52-57） |

### 1.2 MemoryServiceV21 / MemoryStoreV21 直构参数清单（实证）

以 `tests/test_memory_service_v21.py:60-63` 实构方式为准（实读核实）：

```python
store = MemoryStoreV21(tmp_path / "memory_v21.sqlite3")
return MemoryServiceV21(store, clock=fake), fake
```

| 类 | 构造签名 | 坐标 | 行为要点 |
|---|---|---|---|
| `MemoryStoreV21` | `__init__(self, path: str \| Any)` **path 必填无默认** | `domains/chat_reply/character/memory_store_v21.py:91-98`（类 :88） | 连接即开（check_same_thread=False + RLock :93-94）→ `PRAGMA journal_mode=WAL` + `busy_timeout=1000`（:95-96）→ **ensure_schema 急切建表**（:98 → :106-110，四表 + partial UNIQUE `ux_memory_owner_source_event` :76-80）。**装配即落库文件**（与 database_broker 的懒打开相反，对照 test_v21_wire_svc_assembly.py:183 注释） |
| `MemoryServiceV21` | `__init__(self, store: MemoryStoreV21, *, clock: Callable[[], datetime] \| None = None)` | `domains/chat_reply/character/memory_service.py:207-214`（类 :204） | `clock=None` 缺省 `_utc_now`（UTC aware，:183-185）；生产装配**不传 clock**（真实时钟即缺省）。常量：AUTO_APPROVE_CONFIDENCE=0.5（:28）、DEFAULT_INJECTION_BUDGET_CHARS=1200（:27） |
| 导入路径 | canonical=`domains/chat_reply/character/`（装配席照 teaching 先例用 canonical，service_wiring.py:139-141 同款惰性 import）；顶层 `character/memory_service.py` / `character/memory_store_v21.py` 为 PEP 562 live re-export 垫片（垫片自述 :1-18，canonical 指针 store 垫片 :10；service 垫片头 6 行本席实读） | — | 测试经垫片路径导入（test_memory_service_v21.py:27、:40），两路等价 |

**全树不存在 `build_memory_service_v21` 函数**（memo §附：144 结论，本席采信；装配席须直构，勿找不存在的 builder）。

### 1.3 消费方注册 id 提案（共同项）

- **提案 id：`"memory"`**。依据：①既有 id 风格为小写下划线（worldbook/knowledge/database_broker/teaching，service_wiring.py:53-58）；②常驻锁测试已经用 `"memory"` 作占位断言键（test_v21_wire_svc_assembly.py:228 `get_v21_service("memory") is None`），接线后语义自然反转。
- **首个自然消费方＝TeachingService**：构造签名 `TeachingService(db_path, *, memory_service=None)`（`domains/chat_reply/character/teaching_service.py:220-227` 实读），现装配刻意不传（service_wiring.py:158-159 注释+实参）。接线后可选增强＝teaching 分支改传 `get_v21_service("memory")`（走 `propose_teaching`，memory_service.py:286）——**属可选二期，不在 L41 最小接线内**，动它要加 teaching 分支回归。
- 其余消费方（chat 注入、/bot memory 迁移）：unknown，超范围（§〇.4）。

### 1.4 失败面（fail-open，对齐 WIRE-SVC 先例）

两案共用，三层防护全部现成、零新增代码：

1. **单服务层**：`_assemble`（service_wiring.py:96-106）捕一切异常 → `logger.warning("v21 service wiring: memory assembly failed: <ExcType>")` → 跳过该服务，其余照常（先例实证测试：test_v21_wire_svc_assembly.py:269-283）。
2. **整段层**：根 `__init__.py:4139-4144` try/except → warning，装配失败不崩启动。
3. **消费方层**：`get_v21_service("memory")` 未装配/未知 id 一律 None（service_wiring.py:173-175），消费方须 None 检查（本批无消费方，风险为零）。

记忆特有失败面：`MemoryStoreV21.__init__` 连接/建表异常（磁盘、权限、路径被占用）会在 `_assemble` 内被转成 warning 跳过——**不会**半装配（服务要么完整进注册表要么缺席）。

### 1.5 回滚＝拨门（共同项）

- `bot_memory_service_v21_enabled=false`（或主门 `bot_v21_service_wiring_enabled=false`）→ 重启 → gates 短路 → build 返回不含 memory → `register_v21_services` 先清后填（:165-170）→ 注册表无 memory。**配置级回滚，无需回滚代码**（门关时代码惰性不执行，gates dict 与 build 分支同门）。
- 回滚不删数据：已生成的库文件留在运行数据区（受「运行数据不可删」铁律保护）；`memory_index_v21` 投影可整表清、其余三表禁清（db-owners.md:54 实读）。
- 测试隔离用 `reset_v21_services()`（:182-184），生产进程不调用。

---

## 二、A 案分支（独立新库，memo 推荐案）

### 2.1 config 门键提案

| 键 | 提案值 | 缺省 | 说明 |
|---|---|---|---|
| 分门（开关） | `bot_memory_service_v21_enabled` | **False** | 本预案任务书指定名。注意：memo §⑤（:129）给的备选名是 `bot_memory_v21_enabled`——两处提案名不一致，**以用户裁决勾选为准**，下文统一按 `bot_memory_service_v21_enabled` 书写；若用户选 memo 名，全局替换即可 |
| 路径键 | `bot_memory_v21_db_path` | `"data/memory_v21.sqlite3"` | memo §⑤（:128）建议值，本席无异议 |
| 主门 | 复用既有 `bot_v21_service_wiring_enabled`（config.py:174） | False | 不新增 |

生效语义＝**主门 ∧ 分门**（`v21_service_gates` 现成模式，service_wiring.py:64-77）；**不采用**「路径键非空即接」的 teaching 简化式（memo §⑤ 给了两个选项），理由：显式 False 缺省与 worldbook/knowledge 分门（config.py:176/:178）同构、与常驻锁测试的 stub 门矩阵（test_v21_wire_svc_assembly.py:66-73）同构，审计面最清晰。若用户偏好路径非空即接，删掉分门键、gates 改判空串即可（差异 1 行）。

### 2.2 装配插入点坐标（逐步，对齐 service_wiring 既有模式）

| 步 | 文件 | 坐标 | 改动 |
|---|---|---|---|
| S1 | `config.py` | :178 后（B2① 块内，紧邻 worldbook/knowledge 两键） | 新增两字段：`bot_memory_service_v21_enabled: bool = False` + `bot_memory_v21_db_path: str = "data/memory_v21.sqlite3"`，附注释；**同步修订 ：173 注释**「L41 memory 待用户裁决不接」→ 已裁决字样（防注释与事实漂移） |
| S2 | `config.py` | :1110（`"bot_teaching_db_path"` 行）后 | path_fields 元组追加 `"bot_memory_v21_db_path"`（元组整体 ：1053-1114，应用循环 ：1115-1116 自动重映射） |
| S3 | `service_wiring.py` | :53-58 | `V21_SERVICE_WIRING_IDS` 追加 `"memory"`（五 id）；:52 行注释「四个…L41 memory 不在列」同步修订 |
| S4 | `service_wiring.py` | :64-77 | `v21_service_gates` 追加 `"memory": master and bool(getattr(config, "bot_memory_service_v21_enabled", False))` |
| S5 | `service_wiring.py` | :80-87 | `build_v21_services` 签名追加 kwarg `memory_db_path: str \| Path \| None = None`（照 teaching_db_path 先例，仅供测试注入 tmp_path） |
| S6 | `service_wiring.py` | :161 后（teaching 分支之后、`return services` :162 之前） | 新增 memory 分支（草图见下） |
| S7 | `service_wiring.py` | :21-23 | 模块 docstring「L41 刻意缺席」段改写为已接线说明 |
| S8 | 根 `__init__.py` | **零改动** | 装配段 ：4124-4144 是 id 无关的：`register_v21_services(config)` 自动带上新服务，`wired` 日志自动含 memory（:4136-4138 `",".join(sorted(wired))`） |
| S9 | 注册面文档 | `docs/config-catalog-full.md:824` 格式（`_teaching_enabled` 行式） | 追加 `_memory_service_v21_enabled` / `_memory_v21_db_path` 行 |
| S10 | 注册面文档 | `.env.example:688` 后（B2① 块尾，worldbook/knowledge 之后） | 追加 3-4 行（两键+注释，缺省 false） |
| S11 | 注册面文档 | `docs/db-owners.md:54` | 行改写：env 列填 `BOT_MEMORY_V21_DB_PATH`；**修正失真函数名**（该行现写 `build_memory_service_v21`，全树不存在——改为「`MemoryServiceV21(MemoryStoreV21(path))` 直构，经 runtime/service_wiring.py 装配」）；「暂无独立配置键」字样删除 |
| S12 | 注册面文档 | `docs/auto-facts.md` | 若 config 字段数口径在册，跑 doc_sync `--write` 同步（WIRE-SVC 先例，coordination 表第 9 行） |

**S6 草图（提案，未实施）**——严格照 teaching 模板（service_wiring.py:136-161）：

```python
if gates.get("memory"):

    def _build_memory() -> Any:
        from plugins.bot_unified_runtime.domains.chat_reply.character.memory_service import (
            MemoryServiceV21,
        )
        from plugins.bot_unified_runtime.domains.chat_reply.character.memory_store_v21 import (
            MemoryStoreV21,
        )
        from scripts.runtime_paths import runtime_path

        path = (
            memory_db_path
            if memory_db_path is not None
            else runtime_path(
                str(
                    getattr(config, "bot_memory_v21_db_path", "")
                    or "data/memory_v21.sqlite3"
                )
            )
        )
        # 生产不传 clock（缺省 UTC 真实时钟，memory_service.py:183-185/214）。
        return MemoryServiceV21(MemoryStoreV21(path))

    _assemble("memory", _build_memory)
```

### 2.3 测试计划（A 案）

**必改的既有断言（常驻锁改写）**——`tests/test_v21_wire_svc_assembly.py`：

| 坐标 | 现状（实读） | 接线后 |
|---|---|---|
| :11 | docstring「L41（memory）：注册表 id 全集不含 memory（裁决前不接的常驻锁）」 | 改写为已接线口径 |
| :98-103 | `v21_service_gates(config) == {四键 dict}` **整 dict 精确相等断言** | 追加 `"memory": False`（不加必炸） |
| :224-225 | `set(registered) == set(V21_SERVICE_WIRING_IDS)` | 自动适配（与导入常量比对，零改动） |
| :226-228 | L41 常驻锁：`assert "memory" not in v21_service_ids()` + `get_v21_service("memory") is None` | **锁反转**：该测试（:199 `test_all_four_services_registered_together`）stub 需加 `bot_memory_service_v21_enabled=True` + memory 注入路径，断言改为 `"memory" in ids`；「门关缺席」语义移入新增的门矩阵用例 |
| :229 | `get_v21_service("unknown-id") is None` | 保留不动 |
| :66-73 | `_stub_config` 门矩阵 | 追加 `bot_memory_service_v21_enabled: False` + `bot_memory_v21_db_path` 缺省行 |
| :81-88 | `test_real_config_defaults_keep_wiring_off` | 追加两断言：`config.bot_memory_service_v21_enabled is False`；`config.bot_memory_v21_db_path` 已被重映射出源码树（进 Runtime data 根） |

**新增用例（照 teaching 模板 ：186-196，全部离线 tmp_path）**：

1. **门开装配**：stub 主门+分门 True、`memory_db_path=tmp_path/"m.sqlite3"` → `register_v21_services` 返回含 memory → `get_v21_service("memory")` isinstance `MemoryServiceV21` → **文件已落盘**（MemoryStoreV21 急切建表，memory_store_v21.py:98——与 broker 懒打开断言 ：183 相反，可作区分性断言）。
2. **门关零副作用**：分门 False（或仅主门 False）→ build 无 memory、`tmp_path` 目录空（照 ：104-107 模式）、`get_v21_service("memory") is None`。
3. **fail-open**：`memory_db_path` 指向父级是文件的路径（照 ：269-283 的 blocked 手法）→ memory 缺席、其余服务照常注册。
4. **根静态断言**：:305-311 现状已通过且无需改（S8 零改动）；可加一条 memory 分支存在于 service_wiring 源码的静态断言（防再被静默移除）。
5. **零接触确认**：`tests/test_memory_service_v21.py` 41 例**一行不改**（现构造方式即 A 案终态）；如需可加「装配产出的 service 通过同一契约冒烟一条」（可选）。

**静态门禁（接线席实跑）**：`tests/test_doc_sync_gates.py:321`（新键须登记 catalog）/ :329（全字段覆盖）+ runtime-layout + ruff + mypy 本域；全量 `dev.ps1 -Task test` 一次。**禁真实 LLM**——本接线全程无 LLM 依赖。

### 2.4 预估工作量（A 案）

| 项 | 量级 |
|---|---|
| 代码 diff | config.py ~8 行 + service_wiring.py ~30 行（含 docstring）+ 根 `__init__.py` 0 行 ≈ **40 行级** |
| 测试 | test_v21_wire_svc_assembly.py 改 6 处 + 新增 3-4 例 ≈ 100-130 行；memory 契约 41 例零改动 |
| 文档 | config-catalog 1-2 行、.env.example 3-4 行、db-owners :54 行改写、auto-facts（doc_sync --write）、本预案回执注记 |
| 席位工期 | **单个装配席一次在飞可完成**（小：装配级，与 memo §③ A 行「工作量级：小（装配级）」一致）；不含全量回归排队时间 |
| 风险 | 最低：不触碰旧栈任何消费点（§3.1 表全部零改动）；唯一新增运行时行为是门开后的库文件落盘 |

---

## 三、B 案分支（同源同库）

### 3.1 B1（同文件并存）——同一装配面的差异点

装配面与 A 案**完全同构**（S3-S8 步 identical；S1/S2/S9-S11 按下表换内容），差异只在 store 指向与登记面：

| 维度 | A 案 | B1 差异 |
|---|---|---|
| store 路径来源 | 新键 `bot_memory_v21_db_path`（默认独立文件） | S6 草图中路径解析改读 **既有 `bot_memory_db_path`**（config.py:185，生产=`data/wuwa_memory.sqlite3`，`.env` 实态 per memo §2.2）；S1/S2 两步**不需要**（零新路径键，仅保留分门键） |
| 空路径护栏 | 不需要（有默认值） | **必须加**：`bot_memory_db_path` 缺省空串（config.py:185），空=旧栈回退内存实现在册契约（db-owners.md:19 实读「空=内存」）。B1 下路径为空应**放弃装配**（记 warning 跳过）而不是给 v21 塞 `:memory:` 一次性库——门语义改为 `master ∧ 分门 ∧ 路径非空` |
| gate 键 | `bot_memory_service_v21_enabled` | 同名保留，**不得复用** `bot_memory_enabled`（config.py:184）——旧键语义绑旧栈写入门（`_build_memory_writer` 四重门：enabled∧extract∧db_path∧provider=openai_compatible，根 `__init__.py:367-372` 实读），两栈开关解耦才能独立回滚 |
| db-owners | :54 行补 env 键 | **:19 行（wuwa_memory）必须改写**：该行现口径「聊天记忆属活动数据禁删；只经 /bot memory 指令操作」须扩写覆盖 v21 四表——尤其「墓碑表禁清、memory_index_v21 可整表清」与新文件相反的清理语义并存于同一文件（:54 实读）；:54 行同步改（同 A 案 S11） |
| 消费点 | 全部零接触 | **代码仍零接触**（旧栈消费方继续读 memory_facts），但运行面变成同文件双栈并存 |

**风险清单（引 memo §③ B1 :82 原文四条，逐条给本席实读锚点）**：

1. **同文件双连接写竞争**——旧栈 `_connect` 为普通连接，无 WAL 无 busy_timeout（`domains/chat_reply/character/memory.py:237-240` 实读：裸 `sqlite3.connect` + row_factory，完）；v21 连接 WAL + busy_timeout=1000ms + check_same_thread=False（memory_store_v21.py:94-96，完）。memo 原文：「需补并发回归验证」。附加技术事实：journal_mode=WAL 是库级持久属性（SQLite 语义），v21 首连即改写整库 journal mode，旧栈后续所有连接在 WAL 库上裸奔——**本席未实测旧栈连接在 WAL 化文件上的行为**（unknown，接线席须以并发回归实测补证）。
2. **备份/清理语义耦合**——memo 原文：「db-owners 对 wuwa_memory 的登记必须改写以覆盖『v21 墓碑禁清』，误清旧库即连带毁墓碑（项目铁律：运行数据不可删，高危区）」。锚点：db-owners.md:19 vs :54 两行语义合并。
3. **生命周期被单键绑定**——memo 原文：「`bot_memory_db_path` 清空即旧栈回退内存实现（db-owners.md:73 契约），v21 库随之落空」。（db-owners.md:73 为 memo 引述，本席未逐字复核该行——unknown；:19 行的「空=内存」口径已实读。）
4. **v21 分门与旧 `bot_memory_enabled` 语义纠缠**——memo 原文如上；本席处置＝独立分门键（见上表 gate 行）。

**B1 测试计划增量**（在 A 案 §2.3 之上）：新增双连接并发回归（旧 `SQLiteMemoryRepository` 写 + v21 store 写交错，断言无 `sqlite3.OperationalError: database is locked` 类失败）；`_stub_config` 的 memory 路径行改为指向与 tmp 旧库同文件以模拟并存。

**B1 工作量对比**：装配级同 A + db-owners :19/:54 双行改写 + 并发回归新测 ≈ **A × 1.3-1.5**；可逆性中（B1→A 需拆表迁移，memo §③ :83）。

### 3.2 B2（改造 memory_facts 本体）——不建议，仅存目

- 结构性障碍 verified：memory_facts 建表 DDL 无 version/status/tombstone/expires 列（memory.py:205-217 实读，memo §③ :85 同结论）；墓碑模型（永不 DELETE + 行翻 forgotten + 墓碑防复活）需 schema 迁移才可成立。
- 回归面＝全部旧栈消费点（本席实读核实坐标）：回复后写入器 `_build_memory_writer`（根 `__init__.py:363-382`）；/bot memory 指令路由（根 `__init__.py:6237-6245`，db_path 门 ：6242）；chat 注入消费（`domains/chat_reply/capabilities/chat.py:779-783`、预算分区 ：1478/:1509/:1528、注入拼装 ：1567-1568）；admin debug 统计（`domains/ops/admin/debug.py:1175`）；smoke diagnostics（`domains/ops/smoke/diagnostics.py:59/:160/:205/:320`）。
- 工作量级＝**大**（DDL 迁移设计席 + 五消费点全回归 + 行级语义映射），触碰「运行数据不可删」活数据表，可逆性低（memo §④.2 不建议，本席同口径）。**本预案不为 B2 提供即插施工图**；若用户裁定 B2，须另立迁移设计席位，不走本预案快速通道。

### 3.3 三案工作量速览（承接 memo §③ 对比表，加席位口径）

| 维度 | A 独立新库 | B1 同文件并存 | B2 改表 |
|---|---|---|---|
| 本预案施工图 | 有（§2 全套） | 有（§3.1 差异点 + A 案复用） | 无（另立席） |
| 席位工期 | 小（1 席 1 次） | 小偏中（1 席 1 次 + 并发回归） | 大（多席） |
| 旧栈回归风险 | 零 | 低-中（双连接） | 高（五消费点） |
| 可逆性 | 高 | 中 | 低 |

---

## 四、诚实边界与 unknown 清单

- 本席零代码改动、零 git 写操作、零真实 LLM 调用；未重跑任何测试（41 例契约全绿系 memo 转述的基线证据，非本席实跑）。
- **坐标勘误（对 memo，本席实读更正）**：
  - memo §2.2「memory_extract 写入器 `__init__.py:361-382`」→ 实际 `_build_memory_writer` def 在 **:363**（门 :367-372、repository 构造 :382）；
  - memo §2.2「/bot memory 路由 `:6240`」→ 实际 **:6237-6245**（db_path 门 :6242）；
  - memo §③「chat 注入统计 `chat.py:2414`」→ **:2414 处无 memory 内容**；chat 的 memory 消费实际在 :779-783（_memory_lines）、:1478/:1509/:1528（预算分区）、:1567-1568（注入拼装）。
- unknown（无证据不写）：旧栈连接的生命周期细节（仅实证 `_ensure_schema` 处 `with self._connect()` 用法 memory.py:202，其余调用点未逐一遍历）；旧库 wuwa_memory.sqlite3 行数/体积（避触运行数据，memo §附同口径）；db-owners.md:73 原文（未逐字复核）；v21 装配后的真实消费方行为（超 L41 范围）。
- 状态口径：本预案落盘时点 L41 = **not_wired**；本文所有「接线后」均为假设语态，**不得读作已生效/已裁决**。
