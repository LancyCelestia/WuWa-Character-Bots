# v21r4-B RET2B-PREP 席日志——RWOC 面 55 张垫片冲突矩阵 + 安全子集退役

- 席位：RET2B-PREP（2026-09-18 开工，断点续跑）；对象=交接书 §6.1 挂账 RET2b 梯队：EP1 盘点波次标记 RWOC 的 55 张垫片（前任零落盘）。
- 施工图=`docs/design/v21r2-shim-retirement-inventory.md`；协调表已登记；方法沿 RET1/RET3 先例：①逐张复验消费方（AST+rg 双轨，本席扫描器快照 `%TEMP%/v21r4-ret2b-scan.json`）→②消费方改指 canonical→③AST 级零残余验证→④备份至 `%TEMP%/v21r4-ret2b-backup/plugins/bot_unified_runtime/<相对路径>` 后删垫片→⑤域回归实跑。
- 挂起判定域（在飞/禁触面）：根 `__init__.py`（RWC5-b）｜前端域 domains/render/**、output/card_render/**、视觉门禁族测试 + QA 漂移面 echo.py/debug.py｜control_plane/api + tests/test_controlplane*（RK5/硬禁）｜RWC6-b 旧路径 policy·security 及其新领地 domains/chat_reply/{policy,security}（保守）｜REM-DAWN/EVE 的 schedule/store/reminders.py + tests/test_reminder.py｜WIRE-SVC 的 config.py/service_wiring/database_broker｜S0-COLLECT 的 domains/transport/sender/file_gateway.py、domains/core/decision/outbound_registry.py、tests/test_v21_s0_collect.py。
- 纪律：固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r4-ret2b-<批名> -p no:cacheprovider -q`；零 git 写操作；每批 ≤10 张，ruff 本批文件零错 + 域测试绿再下一批。

## 一、冲突矩阵（55 张逐张判定，2026-09-18 实扫现状）

图例：判定 ∈ 安全可退 / 挂起 / 已清（前席已删，非本席动作）。

| # | 垫片 | canonical（`_CANONICAL`） | 消费面现状（本席实扫） | 判定 | 依据 |
|---|---|---|---|---|---|
| 1 | `config_readiness` | domains.core.config.config_readiness | src: chat_reply/capabilities/**echo**、chat_reply/pipeline/backend_unit；串: tests/test_perf_hotpath | **挂起** | 前端邻接（echo.py=QA 在飞漂移面） |
| 2 | `console_chat` | domains.ops.smoke.console_chat | src: backend_unit、prompt_preview；canonical 文件用法串 3 行 | 安全可退 | 消费方无在飞写者 |
| 3 | `diagnostics` | domains.ops.smoke.diagnostics | 0 | 安全可退 | 零消费 |
| 4 | `route_demo` | domains.ops.smoke.route_demo | 0 AST；canonical 用法串 2 行 | 安全可退 | 零消费 |
| 5 | `smoke` | domains.ops.smoke.smoke | src: chat_reply/security/memory_sanitize、scripts/e2e_acceptance；tst ×2 | 安全可退 | memory_sanitize=RWC6-b 已完工况无在飞写者，机械改一行 |
| 6 | `audit.file_logger` | domains.ops.audit.file_logger | 0 | 安全可退 | 零消费 |
| 7 | `audit.logger` | domains.ops.audit.logger | src: control_plane/{actions,audit,config_store,events,workspaces}（非 api/）、chat_reply/llm_engine/ledger；tst ×2 | 安全可退 | RK5 域=control_plane/api，本组非 api/ |
| 8 | `capabilities.debug` | domains.ops.admin.debug | tst ×5 含 test_v21r3_visual_gates、test_phase_determinism*（前端域测试）；canonical 本体=QA 漂移面 | **挂起** | 前端域测试消费 |
| 9 | `capabilities.feature_control` | domains.ops.features.feature_control | tst: test_runtime_feature_gate（函数级） | 安全可退 | 纯测试消费 |
| 10 | `capabilities.platform_credentials` | domains.core.credentials.platform_credentials | src: **根 `__init__`**；tst ×3 | **挂起** | 根 `__init__` 消费（RWC5-b 禁触） |
| 11 | `capabilities.runtime_admin` | domains.ops.admin.runtime_admin | src: **根 `__init__`**、ops/smoke/console_chat；tst ×11 | **挂起** | 根 `__init__` 消费（RWC5-b 禁触） |
| 12 | `capabilities.runtime_logs` | domains.ops.admin.runtime_logs | tst: test_help_deep_teaching_n2re（函数级） | 安全可退 | 纯测试消费 |
| 13 | `contracts.auto_send` | domains.core.contracts.auto_send | src: schedule/auto_send/parser | 安全可退 | schedule 在飞面仅 store/reminders.py |
| 14 | `contracts.character` | domains.core.contracts.character | src: chat_reply/character ×8 + sources/acg_search；tst ×2 | 安全可退 | character 无在飞写者（WIRE-SVC 明示 character 零改动） |
| 15 | `contracts.envelope` | domains.core.contracts.envelope | src: chat_reply/character/knowledge_service；tst: test_event_service_v21 | 安全可退 | — |
| 16 | `contracts.errors` | domains.core.contracts.errors | src: divination/service/divination_service；tst ×2 | 安全可退 | WIRE-DIRECT 对 divination 只读 |
| 17 | `contracts.finance` | domains.core.contracts.finance | src: finance/stocks、finance/data/{fx_data,stock_data}；tst ×7 | 安全可退 | — |
| 18 | `contracts.media` | domains.core.contracts.media | src ×35：parsers ×29+、link_parse/__init__、types、registry、music、**render/card_render/bridge**、sources/__init__；tst ×12 | **挂起** | 前端禁改（render/bridge 消费）+面过大 |
| 19 | `contracts.music` | domains.core.contracts.music | src: parsers/platforms_music、music/data ×3；tst ×5 | 安全可退 | — |
| 20 | `contracts.request` | domains.core.contracts.request | src: divination_service；tst: test_event_service_v21 | 安全可退 | — |
| 21 | `contracts.runtime` | domains.core.contracts.runtime | src ×9：**chat_reply/{policy,security} ×4（RWC6-b 新领地）**、**transport/sender/file_gateway（S0-COLLECT 域）**、daily_assist、shared_export、llm_engine/providers、media_registry | **挂起** | RWC6-b 领地 + S0-COLLECT 认领 |
| 22 | `contracts.subscription` | domains.core.contracts.subscription | src ×9：subscribe/adapters ×4、capabilities/subscribe、store ×4；tst ×22 | 安全可退 | subscribe 域无在飞写者（量大单列一批） |
| 23 | `decision.dispatcher` | domains.core.decision.dispatcher | tst ×2 | 安全可退 | 纯测试消费 |
| 24 | `decision.engine` | domains.core.decision.engine | tst: test_decision_engine_shadow | 安全可退 | 纯测试消费 |
| 25 | `decision.ingress` | domains.core.decision.ingress | tst: test_decision_engine_shadow | 安全可退 | 纯测试消费 |
| 26 | `decision.outbound` | domains.core.decision.outbound | src: control_plane/dispatcher、meme/reactions/engine；tst ×4 含 **test_v21_s0_collect** | **挂起** | S0-COLLECT 认领面 |
| 27 | `decision.outbound_contracts` | — | 文件已不存在（零消费，前席已清） | 已清 | 非本席动作 |
| 28 | `decision.outbound_registry` | — | 文件已不存在（零消费，前席已清；canonical 真身=domains/core/decision/outbound_registry.py 归 S0-COLLECT，未触） | 已清 | 非本席动作 |
| 29 | `decision.shadow` | domains.core.decision.shadow | src: chat_reply/runtime/pipeline（函数级）；tst: test_decision_engine_shadow | 安全可退 | — |
| 30 | `decision.trace` | domains.core.decision.trace | src: **echo（QA 漂移面）**、scripts/e2e_acceptance；tst ×2 | **挂起** | 前端邻接（echo.py） |
| 31 | `runtime.alerts` | domains.ops.monitor.alerts | src: subscribe/store/subscription_store_v2、transport/sender/worker；tst ×4 | 安全可退 | — |
| 32 | `runtime.disconnect_notice` | domains.ops.monitor.disconnect_notice | tst: test_disconnect_notice | 安全可退 | — |
| 33 | `runtime.error_report` | domains.ops.monitor.error_report | src: chat_reply/runtime/pipeline；tst ×2 | 安全可退 | — |
| 34 | `runtime.event_service` | domains.ops.monitor.event_service | tst: test_event_service_v21 | 安全可退 | 纯测试消费 |
| 35 | `runtime.event_store` | domains.ops.monitor.event_store | tst: test_event_service_v21 | 安全可退 | 纯测试消费 |
| 36 | `runtime.feature_catalog` | domains.ops.features.feature_catalog | src: control_plane/factory（非 api/）；tst ×2 | 安全可退 | — |
| 37 | `runtime.feature_gate` | domains.ops.features.feature_gate | src: chat_reply/runtime/pipeline；tst ×2 | 安全可退 | — |
| 38 | `runtime.intent_telemetry` | domains.ops.monitor.intent_telemetry | src: chat_reply/capabilities/chat | 安全可退 | chat.py 无在飞写者 |
| 39 | `runtime.result_unknown` | domains.ops.monitor.result_unknown | tst: test_result_unknown | 安全可退 | 纯测试消费 |
| 40 | `runtime.usage_monitor` | domains.ops.monitor.usage_monitor | src: **根 `__init__`**；tst ×4 | **挂起** | 根 `__init__` 消费（RWC5-b 禁触） |
| 41 | `sources.credential_health` | domains.core.credentials.credential_health | 0 AST；canonical 注释串 1 行 | 安全可退 | 零消费 |
| 42 | `sources.credentials` | — | 文件已不存在（零消费，前席已清） | 已清 | 非本席动作 |
| 43 | `sources.gscore_bridge` | domains.ops.integrations.gscore_bridge | 0 AST；canonical 注释串 1 行 | 安全可退 | 零消费 |
| 44 | `sources.mcp_web_search_server` | domains.core.search.mcp_web_search_server | 0 AST；canonical 注释串 2 行 | 安全可退 | 零消费 |
| 45 | `sources.runtime_event_log` | domains.ops.monitor.runtime_event_log | src: chat_reply/capabilities/chat；tst ×5 | 安全可退 | — |
| 46 | `sources.search_api` | domains.core.search.search_api | src: food/eat、media/search/sauce_search、runtime/capability_protocols；tst ×1 | 安全可退 | — |
| 47 | `sources.search_service` | domains.core.search.search_service | src: runtime/capability_protocols；tst ×1 | 安全可退 | — |
| 48 | `sources.search_smoke` | domains.core.search.search_smoke | 0 AST；canonical 用法串 1 行 | 安全可退 | 零消费 |
| 49 | `sources.web_search` | domains.core.search.web_search | src ×4 含 **control_plane/api/platform（禁改）**；tst ×5 | **挂起** | control_plane/api 消费（硬禁） |
| 50 | `supervisor.acl_windows` | domains.core.supervisor.acl_windows | tst: test_sandbox_windows（函数级） | 安全可退 | 纯测试消费 |
| 51 | `supervisor.appcontainer_windows` | domains.core.supervisor.appcontainer_windows | 0 | 安全可退 | 零消费 |
| 52 | `supervisor.ipc` | domains.core.supervisor.ipc | tst: test_supervisor_isolation | 安全可退 | 纯测试消费 |
| 53 | `supervisor.job_objects` | domains.core.supervisor.job_objects | tst: test_sandbox_windows（函数级） | 安全可退 | 纯测试消费 |
| 54 | `supervisor.sandbox_windows` | — | 文件已不存在（零消费，前席已清） | 已清 | 非本席动作 |
| 55 | `supervisor.windows_sandbox` | domains.core.supervisor.windows_sandbox | tst: test_supervisor_isolation | 安全可退 | 纯测试消费 |

**补充发现（EP1 盘点后新增垫片）**：父包 `decision/__init__.py`、`audit/__init__.py`、`contracts/__init__.py`、`supervisor/__init__.py` 为 RWOC 尾声波新增的包级 PEP562 垫片（`_CANONICAL_PKG`），EP1 清单未收录。按 EP1 §3-4「同目录整批退役」：`audit/__init__`、`supervisor/__init__` 随其子模块清零后同批退役并删空目录；`decision/__init__` 因 `decision.outbound` 挂起必须存活；`contracts/__init__` 因 `contracts.media`、`contracts.runtime` 挂起必须存活。

**矩阵小结**：55 = 安全可退 41 + 挂起 10（前端邻接×3：config_readiness/decision.trace/capabilities.debug；根 `__init__`×3：platform_credentials/runtime_admin/runtime.usage_monitor；S0-COLLECT×2：decision.outbound/sources.web_search 属 control_plane api 复合；RWC6-b+S0 复合×1：contracts.runtime；前端+面过大×1：contracts.media）+ 已清（前席）4。

## 二、批次台账

### 批1（10 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | diagnostics、route_demo、audit.file_logger、capabilities.feature_control、capabilities.runtime_logs、runtime.result_unknown、decision.{engine,ingress,dispatcher,shadow}.py |
| 改写 | 7 文件：test_decision_engine_shadow（4 行含 decision 包绑定 Dispatcher 行）、test_help_deep_teaching_n2re:183、test_result_unknown:5、test_runtime_feature_gate:61、test_v21_dispatch_outbound_wiring:35、test_v21_risk_red_dispatch_and_telegram:26、chat_reply/runtime/pipeline.py:355（函数级）；另 canonical 用法串 route_demo.py:4-5 更新 |
| AST 零残余 | 全仓 grep `bot_unified_runtime.(diagnostics\|route_demo\|audit.file_logger\|capabilities.(feature_control\|runtime_logs)\|runtime.result_unknown\|decision.(engine\|ingress\|dispatcher\|shadow))` = 0 命中 |
| 备份 | `%TEMP%/v21r4-ret2b-backup/plugins/bot_unified_runtime/<相对路径>`（10 件，sha256 字节核验） |
| 回归 | 7 文件 pytest：**99 passed**（6.15s） |
| ruff | 6 处 I001（canonical 字典序变化+pipeline.py WIP 遗留 1 处）→ `--fix` 仅限本批 8 文件后 0 残余 |
| 备注 | decision/__init__ 包垫片存活（decision.outbound 挂起所需）；test_decision_engine_shadow:19 包绑定行顺改 canonical 包 |

### 批2 + 批2b（13 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役（批2，10 张） | audit.logger、runtime.{alerts,disconnect_notice,error_report,event_service,event_store,feature_catalog,feature_gate,intent_telemetry}.py、console_chat |
| 退役（批2b，3 张，解禁） | capabilities.platform_credentials、capabilities.runtime_admin、runtime.usage_monitor |
| **矩阵修正（v2 重扫）** | ①扫描器父绑定缺陷修复（同父包多垫片单名覆盖→集合匹配），批1/批2 已退 20 张复验零残余；②根 `__init__.py` 三处「消费」为 v1 误报（根 init 全部直指 canonical：`from .domains.core.config.config_readiness import` 等）→ platform_credentials/runtime_admin/usage_monitor 三张由挂起**解禁为安全可退**；矩阵挂起数 10→7 |
| 改写 | 批2：22 文件 31 处（control_plane/{actions,events,audit,config_store,workspaces,factory}、chat_reply/{llm_engine/ledger,runtime/pipeline,capabilities/chat,pipeline/backend_unit,runtime/prompt_preview}、subscribe/store/subscription_store_v2、transport/sender/worker、canonical console_chat 用法串 4 行、tests ×13；含 2 处相对导入 `from ..audit.logger`/`from ..runtime.feature_catalog`、3 处父绑定 `from …runtime import alerts/error_report as x`）；批2b：18 文件 25 处（含父绑定 `from …capabilities import runtime_admin as ra`、`import …capabilities.runtime_admin as mod` 双形态） |
| AST 零残余 | 批2 后全仓 grep（子模块+父绑定形态）= 0；批2b 后同法 = 0；v2 全量重扫 retired 集合 = CLEAN |
| 备份 | `%TEMP%/v21r4-ret2b-backup/`（13 件，sha256 字节核验） |
| 回归 | 批2：16 文件 **239 passed/1 skipped**（修复 1 处漏网父绑定 test_error_card_contract:152 后复跑）；批2b：17 文件 **285 passed** |
| ruff | 批2 22 处 I001、批2b 9 处 I001 → `--fix` 仅限本批文件后 0 残余 |
| 备注 | **audit/__init__ 包垫片判定反转：存活不退**——其为 EP1 清单外 RWOC 尾声波包垫片，自身消费方 ~25 文件（`from …audit import InMemoryAuditLogger`，含前端邻接 echo.py/pipeline.py），非本席 55 张范围且不可安全清零 |

### 批3（6 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | contracts.{auto_send,envelope,errors,finance,music,request}.py |
| 改写 | 26 文件 43 处模块路径替换（src 10：knowledge_service、divination_service、stocks、fx_data、stock_data、platforms_music、music_normalization、music_request_store×2、music_charts、schedule/auto_send/parser；tests 16：finance/music/divination/event/schedule 族）；**tests/test_contracts_v21.py 直载面 CONTRACTS_DIR 改指 canonical**（envelope/errors/request 三契约模块纯度直载+源检的 NEW_MODULES 面，垫片文件即被测件）；探针 probe_target 同步改指 canonical |
| AST 零残余 | 全仓 grep=0 |
| 备份 | `%TEMP%/v21r4-ret2b-backup/`（6 件，sha256 核验） |
| 回归 | 17 文件：**580 passed/2 skipped** |
| ruff | 15 处 I001 → --fix 本批文件后 0 残余 |

### 批4（4 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | contracts/character.py、sources/{runtime_event_log,search_api,search_service}.py |
| 改写 | 23 文件：chat_reply/character ×8（contracts.character 真身消费）、acg_search、chat.py、eat ×2、sauce_search、capability_protocols（含混合行 `from …sources import search_service, web_search` 拆行——**web_search 挂起维持旧路径不动**）、tests ×8；**capability_protocols search.unified / search.reference.fetch 两描述符 implementation_ref 改钉 canonical**（门禁 test_every_descriptor_has_required_fields_and_resolvable_refs 抓到引用已删垫片，按 RET3 批3 门禁改钉先例处置）；途中一次替换吞逗号语法错，当场修复并复跑 |
| AST 零残余 | 全仓 grep=0 |
| 备份 | `%TEMP%/v21r4-ret2b-backup/`（4 件，sha256 核验） |
| 回归 | 10 文件：190 passed/1 skipped + 复跑 5 文件 128 passed/1 skipped → **全绿** |
| ruff | 15 处 I001 → --fix 后 0 残余（capability_protocols.py All checks passed） |

### 批5（5 张 + supervisor/__init__ 包垫片，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | supervisor/{acl_windows,appcontainer_windows,ipc,job_objects,windows_sandbox}.py + **supervisor/__init__.py 包垫片**（RWOC 尾声波包垫片；消费清零后按 EP1 §3-4 同批退役）+ supervisor/ 空目录移除 |
| 改写 | test_sandbox_windows（5 处）、test_supervisor_isolation（3 处）→ `domains.core.supervisor`（canonical 包导出面同名，父绑定/子模块路径一次替换） |
| AST 零残余 | 全仓 grep=0 |
| 备份 | `%TEMP%/v21r4-ret2b-backup/plugins/bot_unified_runtime/supervisor/`（6 件，sha256 核验） |
| 回归 | 2 文件：**23 passed**（Windows 真机原语面） |
| 备注 | decision/__init__、audit/__init__、contracts/__init__ 三个包垫片因挂起张（decision.outbound / audit 包消费群 / contracts.media+runtime）存活 |

### 批6（6 张 + dev.ps1 调用面，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | contracts/subscription.py、smoke.py、sources/{credential_health,gscore_bridge,mcp_web_search_server,search_smoke}.py |
| 改写 | ①subscription：32 文件（src 9 + tests 23）单一路径替换；②smoke：chat_reply/security/memory_sanitize:157（RWC6-b 已完工新领地，机械一行）、test_chat_and_sources_regressions ×2、test_smoke_config、scripts/e2e_acceptance:136；③**scripts/dev.ps1 调用面 30 处**：smoke ×21、console_chat ×1、route_demo ×2、sources.credential_health/gscore_bridge/search_smoke ×3（本席退役后果）+ **backend_unit ×2、runtime.prompt_preview ×1（RET3 已删垫片的 dev.ps1 遗留断链，顺带修复）**；security.memory_sanitize ×2 为 RWC6-b 垫片按其"垫片保旧路径"设计**不动**；④canonical 文件内 5 处 `python -m` 用法注释改指 canonical |
| AST 零残余 | .py 全仓 grep=0；dev.ps1 除 RWC6-b security.memory_sanitize 外旧路径=0 |
| 备份 | `%TEMP%/v21r4-ret2b-backup/`（6 件，sha256 核验） |
| 回归 | 25 文件（subscription 全消费测试+smoke 族）：**212 passed** |
| ruff | 10 处 I001 → --fix 后 0 残余 |

## 三、终验与移交（2026-09-18）

| 验收项 | 结果 | 证据 |
|---|---|---|
| 退役张数 | **44 张**（本席 40 文件删除 + 前席已清 4 张记账确认）+ 附加 1 件 supervisor/__init__ 包垫片；55 = 44 + 挂起 7 + 前席已清 4 | 批1-6 台账 |
| 挂起（7 张，未触） | config_readiness（echo 前端漂移面）、capabilities.debug（视觉门禁测试消费+canonical 本体漂移）、contracts.media（render/bridge+35 src 面过大）、contracts.runtime（RWC6-b policy/security 新领地+S0-COLLECT file_gateway）、decision.outbound（S0-COLLECT test_v21_s0_collect）、decision.trace（echo 前端漂移面）、sources.web_search（control_plane/api 硬禁） | §一矩阵 |
| AST 零残余 | 修正版扫描器（v2，父绑定集合匹配）全仓重扫：退役 40 张全部文件缺失+消费边 0；挂起 7 张完好未触；整树 pytest --collect-only **8531 collected / 0 error**（旧路径 import 断裂由测试网兜底验证） | `%TEMP%/ret2b-final-scan.txt`、scan2.json |
| 备份位置 | `%TEMP%/v21r4-ret2b-backup/plugins/bot_unified_runtime/<相对路径>`（40+1 件，逐件 sha256 字节核验后删原件） | 各批台账 |
| 域回归合计 | 批1 99 + 批2 239/1s + 批2b 285 + 批3 580/2s + 批4 190/1s+128/1s + 批5 23 + 批6 212 = **1756 passed / 5 skipped / 0 failed** | 各批命令见台账 |
| doc_sync | `--check` 漂移定位=模板清单（前端在飞新增模板）+测试文件数（LIVE-TOOL 新增 test_v21_live_evidence_tool.py）+哈希清单范围（前端清单扩面）——均非本席触碰面；按席位验收授权 `--write` 收敛事实册（5 行事实更新，仅 docs/auto-facts.md）后 `--check` **PASS** | 命令实跑 |
| command_catalog | `--check` PASS，**command catalog is current (77 topics)** | 命令实跑 |
| verify_hashes | `--check` **15 项 DRIFT——全部为前端域文件**（QA-PROBE 时点 8 项→现 15 项，前端在飞波持续演化：mermaid/song/error_card 模板+theme_tokens+bridge+usage_cards+templates+rendering-contract+DESIGN-SPEC+echo+debug），**零一项涉本席触碰/删除面**；按红线**未执行 --write**（重录归前端收口席），不停手（红非本席引起，QA 已预在案） | 命令实跑输出在案 |
| 禁触面核查 | 根 `__init__.py`、domains/render/**、output/card_render/**、theme_tokens.py、tests/render_hashes.json、policy/security 旧路径、control_plane/api、docs/design/backend-v2-acceptance-matrix.md：零改动 | 批台账触碰面清单 |
| 诚实红线 | 以上全部为离线测试与门禁证据；生产 bot 未重启，任何「生效」表述均不适用；零 git 写操作，全部改动停在工作树待用户裁决提交 | — |

**移交清单（合流波/后续席位）**：①挂起 7 张待其冲突面收口后退役（前端域 3：config_readiness/decision.trace/capabilities.debug——config_readiness 与 decision.trace 的消费改写点=echo.py:config_readiness import+decision.trace import；contracts.media 35 src 面；contracts.runtime 9 src 面；decision.outbound+sources.web_search 待 S0-COLLECT/控制面收口）；②包垫片 3 件存活（decision/audit/contracts __init__）；③dev.ps1 中 security.memory_sanitize 旧路径 2 处=RWC6-b 垫片保留面，其收口时需同步 dev.ps1:867-868。



