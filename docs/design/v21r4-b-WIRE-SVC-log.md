# v21r4-B WIRE-SVC 席位日志（B2① 服务装配组）

> 席位=WIRE-SVC｜包=B2①（L39 WORLD / L40 KB / L42 DB / L43 TEACH；L41 MEM 明确不接）｜开始=2026-09-18
> 纪律：全离线 mock；缺省=关；不把矩阵改 wired；离线 passed ≠ 生产生效。

## 检查点 1（开工调研完成，2026-09-18）

已核实代码实况（源码级 verified）：

- `build_worldbook_service`：`plugins/bot_unified_runtime/domains/chat_reply/character/worldbook_service.py:415`（缺省路径走 `runtime_path(DEFAULT_WORLDBOOK_DB_PATH)`）；生产调用点=0（grep 全包仅声明处+tests）。
- `build_knowledge_service`：`domains/chat_reply/character/knowledge_service.py:505`；生产调用点=0。显式传 `stores` 时直接包装（不触嵌入/网络）；不传时按 config 装两源（persona+kb_wiki，kb_wiki 受既有 `bot_kb_wiki_enabled` 门）。
- `DatabaseBroker` / `build_database_broker`：`runtime/database_broker.py:181/448`；生产调用点=0。懒打开不触库文件；预注册 5 查询。
- `TeachingService`：`domains/chat_reply/character/teaching_service.py:217`；无 build_* 工厂，构造即建库（mkdir+schema，急切 I/O）；生产调用点=0。
- L41 MEM：`build_memory_service_v21` 无人调用；**blocked=用户未裁决「独立新库 vs 同源同库」（HANDOFF-V21R4-B §3.4/§七.2），本席零改动 memory 文件**。
- 装配根现状：`domains/*/__init__.py` 全为单行 docstring（无装配逻辑）；真实装配根=根 `__init__.py` 的 `_register_nonebot_handlers`（3428 行起，内含全部 `_register_*_scheduler` 门控装配块）。
- config 键现状：`bot_teaching_enabled=True` / `bot_database_broker_enabled=True`（config.py:165/169，S8 批预留，「未接线，生产装配属后续席位」注释在册；catalog 824/825 行已登记）；**无** worldbook/knowledge_service/装配主门键。
- 关键裁定：teaching/broker 既有分门键缺省 True，直接用它们做唯一门会违反「缺省=关」→ 新增主门 `bot_v21_service_wiring_enabled`（缺省 False），生效门=主门 ∧ 分门；分门优先复用既有键（teaching/broker），WORLD/KB 新增分门键（均缺省 False）。
- 新增键 3 枚：`bot_v21_service_wiring_enabled` / `bot_worldbook_enabled` / `bot_knowledge_service_enabled`（全部缺省 False），同步 catalog + .env.example + doc_sync --write。
- 文件域已在 `v21r4-b-coordination.md` 认领（含 config.py 三键插入，追加式最小改动）。

## 检查点 2（实现落盘）

- 新文件 `plugins/bot_unified_runtime/runtime/service_wiring.py`：
  - `v21_service_gates(config)`：门=主门∧分门映射；
  - `build_v21_services(config, ...)`：逐服务 try/except 装配（fail-open 与既有调度装配同风格，失败记 warning 跳过该服务）；
  - `register_v21_services(config)`：装配并写入模块级注册表 `_SERVICES`；`get_v21_service` / `v21_service_ids` / `reset_v21_services`（测试用）。
  - L41：本模块对 memory 零 import 零引用（docstring 记 blocked 原因）。
- 根 `__init__.py` 最小插入：`_register_nonebot_handlers` 内 daily_assist 块后（~4123 行）一段主门门控 `register_v21_services(config)`，try/except 不崩装配。
- 测试：`tests/test_v21_wire_svc_assembly.py`（门开装配+注册表可查 / 门关零装配零文件 / 分门独立 / fail-open / 根插入静态断言 / 新键缺省 False AST 断言）。

（后续检查点与最终证据见下）

## 检查点 3（实现+文档同步完成，实跑证据 2026-09-19 00:3x-00:4x）

落盘文件（全部实跑验证）：

1. **新装配模块** `plugins/bot_unified_runtime/runtime/service_wiring.py`（唯一装配逻辑所在；`v21_service_gates` / `build_v21_services` / `register_v21_services` / `get_v21_service` / `v21_service_ids` / `reset_v21_services`；fail-open 单服务跳过；L41 memory 零 import 零引用）。
2. **根装配点（最小插入）** `plugins/bot_unified_runtime/__init__.py`：`_register_nonebot_handlers` 内 daily_assist 块之后（插后位于 ~4124-4143 行），主门 `bot_v21_service_wiring_enabled` 门控 + try/except，`register_v21_services(config)`，装配成功记 `v21 services wired: <ids>`。
3. **config.py 三新键**（S8 块后追加，均缺省 False）：`bot_v21_service_wiring_enabled` / `bot_worldbook_enabled` / `bot_knowledge_service_enabled`；顺带把 S8 注释「本轮未接线，生产装配属后续席位」改为「装配见 runtime/service_wiring.py，受主门缺省关约束」（既有 `bot_teaching_enabled`/`bot_database_broker_enabled` 键及其缺省 True **原样未动**，作分门复用）。
4. **docs/config-catalog-full.md**：新增三键三行；`_teaching_enabled`/`_database_broker_enabled` 两行的「未接线」措辞改为「装配已落盘（主门缺省关）待重启生效」。
5. **.env.example**：S8 段后新增 B2① 主门块（三键+注释）。
6. **docs/auto-facts.md**：`doc_sync.py --write` 重生成（610 bot_* 字段含本批 3 键；同批收敛了此前在树的其他波次漂移：RouteKind 34/TTS、topics 77、test 文件数、domains/render 路径——均为树内既有事实）。
7. **新测试** `tests/test_v21_wire_svc_assembly.py` 12 例。

实跑证据（解释器 ChatBot_Runtime/venv/Scripts/python.exe，全离线）：

- `pytest tests/test_v21_wire_svc_assembly.py` → **12 passed**（门缺省关=零装配零文件/四服务门开各装配+注册表可查/分门独立/fail-open/register 幂等+reset/根插入静态断言/L41 memory 不在注册表常驻锁）。
- `pytest tests/test_v21_database_broker.py tests/test_v21_knowledge_service.py tests/test_v21_teaching_service.py tests/test_persona_service_v21.py tests/test_v21_wire_svc_assembly.py` → **96 passed**（四服务存量套件全绿+新测试）。
- `pytest tests/test_backend_unit.py tests/test_campus_digest.py tests/test_b07_sender_level_ingest.py tests/test_doc_sync_gates.py tests/test_v21_s10_protocols.py tests/test_v21_dispatch_outbound_wiring.py` → **105 passed, 1 skipped**（config 消费方+根 import 方+门禁测试无回归）。
- `python -m ruff check .` → **All checks passed!**
- `python scripts/command_catalog.py --check` → **command catalog is current (77 topics)**。
- `python scripts/doc_sync.py --check` → 一致（--write 后）。

事故记录（诚实台账）：首轮测试 stub 门缺省笔误（teaching/broker 分门误设 True）致一次门开装配把空 schema 教导库写进 Runtime data（`ChatBot_Runtime/data/teaching_knowledge.sqlite3`，28672 字节）——已备份 `%TEMP%\wiresvc_runtime_backup\teaching_knowledge.sqlite3.stray-20260919` 后删除，Runtime 恢复原状；stub 修正后全绿且复跑确认 Runtime 无新文件。

**L41（V21-MEM-001）blocked 记录**：不接线。原因=用户未裁决「记忆库独立新库 vs 同源同库」（HANDOFF-V21R4-B-20260918.md §3.4、§七.2）。本席对 memory 相关文件零改动（service_wiring.py 对 memory 零 import；测试有「memory 不在注册表」常驻锁）。

（余项：全量回归一次 + 装配坐标/调用链终稿）

## 终稿（交付清单 + 实跑证据，2026-09-19 00:5x）

### 交付物与装配坐标

| 项 | 坐标 | 内容 |
|---|---|---|
| 装配模块（新） | `plugins/bot_unified_runtime/runtime/service_wiring.py` | `v21_service_gates`:64 / `build_v21_services`:80 / `register_v21_services`:165 / `get_v21_service`:173；fail-open 单服务跳过；L41 memory 零 import 零引用 |
| 根装配点（最小插入） | `plugins/bot_unified_runtime/__init__.py:4124-4143` | `_register_nonebot_handlers` 内、daily_assist 块后；主门 `bot_v21_service_wiring_enabled`（缺省 False）门控 + try/except；成功记 `v21 services wired: <ids>` |
| 主门+新分门键 | `plugins/bot_unified_runtime/config.py:174/176/178` | `bot_v21_service_wiring_enabled=False` / `bot_worldbook_enabled=False` / `bot_knowledge_service_enabled=False`；teaching/broker 复用既有键（config.py:165/169，缺省 True 原样未动） |
| L39 WORLD | 调用 `build_worldbook_service`（worldbook_service.py:415，零改动） | 门=主门∧`bot_worldbook_enabled` |
| L40 KB | 调用 `build_knowledge_service`（knowledge_service.py:505，零改动） | 门=主门∧`bot_knowledge_service_enabled` |
| L42 DB | 调用 `build_database_broker`（runtime/database_broker.py:448，零改动） | 门=主门∧既有`bot_database_broker_enabled` |
| L43 TEACH | 调用 `TeachingService(runtime_path(bot_teaching_db_path))`（teaching_service.py:217，零改动） | 门=主门∧既有`bot_teaching_enabled`；memory_service 刻意不传 |
| 文档同步 | docs/config-catalog-full.md（S8 区 +3 行、2 行措辞更新）；.env.example（B2① 块 +3 键）；docs/auto-facts.md（doc_sync --write ×2 收敛） | — |
| 新增测试 | `tests/test_v21_wire_svc_assembly.py` 12 例（全离线 tmp_path/:memory:） | — |

### 装配后调用链（重启后生效形态）

bot.py → 插件加载 → `_register_nonebot_handlers`（根 `__init__.py:4126` 主门门控）
→ `register_v21_services(config)`（service_wiring.py:165）
→ `build_v21_services`（:80）→ 既有 `build_worldbook_service` / `build_knowledge_service` / `build_database_broker` / `TeachingService`（四者实现零改动）
→ 进程内注册表 `_SERVICES`
→ 消费方（能力/控制面，后续席位）经 `get_v21_service("worldbook"|"knowledge"|"database_broker"|"teaching")` 取用。
缺省态（主门 False）：该链路整体短路，零装配零副作用，现网行为零改变。

### 实跑证据（解释器=ChatBot_Runtime/venv/Scripts/python.exe；全离线）

1. `pytest tests/test_v21_wire_svc_assembly.py` → **12 passed**（门缺省关=零装配零文件；四服务门开各装配+注册表可查；分门独立；fail-open；register 幂等/reset；根插入静态断言；memory 不在注册表常驻锁）。
2. `pytest tests/test_v21_database_broker.py tests/test_v21_knowledge_service.py tests/test_v21_teaching_service.py tests/test_persona_service_v21.py tests/test_v21_wire_svc_assembly.py` → **96 passed**（四服务存量测试全绿）。
3. `pytest tests/test_backend_unit.py tests/test_campus_digest.py tests/test_b07_sender_level_ingest.py tests/test_doc_sync_gates.py tests/test_v21_s10_protocols.py tests/test_v21_dispatch_outbound_wiring.py` → **105 passed, 1 skipped**。
4. 全量（`pytest tests --ignore=tests/test_webui_http.py --ignore=tests/test_webui_stats.py`，00:49-00:55）：**4 failed, 8185 passed, 12 skipped, 4 xfailed**。基线=1 failed（linux.do 样本缺失，总纲 §2.6「不要修」）。余 3 failed 全部归因并行席位在飞态、与本席改动面零交集：
   - `test_cross_validation_gates.py::test_verify_hashes_manifest_clean` + `test_verify_hashes_coverage.py::test_builder_drift_gate_red_then_green`：哈希清单 7 项漂移全在**前端波次独占文件**（theme_tokens.py/rendering-contract.md/DESIGN-SPEC.md/domains/render/**）+ 两文件（ops/admin/debug.py、chat_reply/capabilities/echo.py）为其他席位所改——`verify_hashes.py --write` 本席禁用（总纲 §六：合流时前端统一重录）。
   - `test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync`：多席位并发改树导致的机器册再漂移（webui 席 00:47 新增测试文件等）；本席已再次 `doc_sync.py --write` 收敛，`--check` 复跑**通过**（5 passed 含该门禁）。
   - 首轮全量（00:40-00:48）曾现 `test_v21_wiredirect_unified_path.py` 3 failed：同文件隔离复跑 **4 passed**、二次全量**全过**——系 REM-DAWN 席 00:37-38 并发改 `domains/schedule/store/reminders.py` 与全量跑窗重叠的瞬态，与本席零交集（WIRE-DIRECT 席已在协调表让步记录：根装配段归本席）。
   - 补记：00:55 一次全量重跑因 webui 席在飞态（test_webui_http.py 00:47 引用尚不存在的 control_plane/webui_stats.py）collection 中断——该两模块以 --ignore 排除后取得上数。
5. `python -m ruff check .`：本席四文件（service_wiring.py/config.py/根__init__.py/新测试）**All checks passed!**（00:40 全树曾全绿；00:57 起 F 波次在飞新文件 mica_shell.py 引入 2 处 ISC004，归前端，本席无权触碰）。
6. `python scripts/command_catalog.py --check` → **command catalog is current (77 topics)**。
7. `python scripts/doc_sync.py --check` → **通过**（00:58 收敛后）。

### 状态口径（诚实红线）

- 本席交付=**接线已落盘+离线证据**；全部改动**未 commit / 未重启 / 未部署**，生产生效待用户重启。
- 验收矩阵 L39/L40/L42/L43 **本席零改动**（矩阵独占写=MAT 席）；四行 production_wiring 是否升 wired 由重启后 live 证据决定。
- L41（V21-MEM-001）**blocked**：用户未裁决「独立新库 vs 同源同库」（总纲 §3.4/§七.2）；本席对 memory 零改动（新模块零 import；测试常驻锁「memory 不在注册表」）。
- 事故记录：见检查点 3（首轮测试 stub 笔误致 Runtime data 一过性教导库文件，已备份 %TEMP%\wiresvc_runtime_backup 后删除，Runtime 复归原状；修正后复跑确认零新文件）。

——WIRE-SVC 席终（2026-09-19 00:5x）。
