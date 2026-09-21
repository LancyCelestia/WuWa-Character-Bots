# v21r2 板块重组 RWOC 席施工日志 — 尾声波 ops+core 域（2026-09-17）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> 席位：RWOC（板块重组执行·尾声波=ops+core）。施工图：`v21r2-reorg-plan.md` §2（§2.2 域结构 + §2.3 完整映射表）。
> 零 git 写操作、未 commit（共享工作树多席并行，提交裁决权在用户）。
> 固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r2-rwoc -p no:cacheprovider`；未跑 dev.ps1（席位禁令）。
> 在飞禁触面：RWC3(capabilities/chat.py)、RWC4(pipeline/ingress/base_router)、RWPA1(domains/creation)、S10(media/files/location 协议化)、S11(domains/schedule)。

## 一、范围裁定（以方案书 §2.3 映射表为准）

**ops 域 23 件**：
- `capabilities/{debug,runtime_admin,runtime_logs}.py` → `domains/ops/admin/`
- `capabilities/feature_control.py` + `runtime/{feature_catalog,feature_gate}.py` → `domains/ops/features/`
- `runtime/{error_report,alerts,event_store,event_service,usage_monitor,intent_telemetry,result_unknown,disconnect_notice}.py` + `sources/runtime_event_log.py` → `domains/ops/monitor/`
- `audit/{__init__,logger,file_logger}.py` → `domains/ops/audit/`
- 根 `{smoke,route_demo,console_chat,diagnostics}.py` → `domains/ops/smoke/`
- `sources/gscore_bridge.py` → `domains/ops/integrations/`

**core 域 36 件**：
- 根 `config_readiness.py` → `domains/core/config/`
- `contracts/` 11 件整体 → `domains/core/contracts/`（垫片长期保留，方案 §2.3/§3.1）
- `decision/` 9 件整体 → `domains/core/decision/`
- `supervisor/` 7 件整体 → `domains/core/supervisor/`
- `capabilities/platform_credentials.py` + `sources/{credentials,credential_health}.py` → `domains/core/credentials/`
- `sources/{search_service,search_api,web_search,mcp_web_search_server,search_smoke}.py` → `domains/core/search/`

**不迁**：`control_plane/`（方案书明标「在飞批，最后动」，本波不认领）；`config.py` 案 B（方案 §4.3：仅全波收口后独立 PR）；`sources/{search_intent,acg_search}.py`（SEARCH 席新落，不在方案书映射表）；`runtime/{capability_protocols,database_broker,loop_watchdog}.py`（方案书 41 件之外的新文件，非映射对象，留守）。

（以下随施工滚动补记）

## 二、波前取证（实跑）

- AST 名字级扫描器（`$TEMP/v21r2-rwoc/scan.py`，含 import/相对解析/对象式与字符串式补丁/字符串常量四轨）：旧路径 import 位点 1727（插件树 1500+，tests 223，scripts/bot.py 记账在案）；补丁位点 29 处/10 文件（全 OBJ 式，STR 式 0）；字符串常量锚 22 处。
- monkeypatch 清零对象（12 文件）：test_error_report(12 处)、test_error_card_async(4)、test_thread_pool_atexit_hooks(5)、test_search_api_providers(3)、test_a18_gate_idempotency_rollback、test_auditfix_wave3_resources(pcred_mod)、test_config_control_service(audit.logger)、test_decision_engine_shadow(shadow_module)、test_supervisor_isolation(windows_sandbox)。
- 文本锚定：`tests/verify_hashes.py:53` + `tests/test_verify_hashes_coverage.py:34` + `docs/auto-facts.md`（debug.py 路径随迁）；`tests/test_copy_redline_gate.py` gate_scope（usage_monitor/error_report 真身迁出后扫描面扩 domains/ops/**）；`control_plane/log_collectors.py` _SUBSYSTEMS（decision→decision_engine 锚补 canonical 前缀）；`decision/outbound_registry.py:498-502` trace 路径串（RWC2 移交本波统一对账）。
- 包 init 形态清点：contracts/__init__ 纯聚合 re-export（无副作用注册）；decision/__init__ 纯惰性 _LAZY_EXPORTS；supervisor/__init__ 绝对自导入 6 处；audit/__init__ 相对 .logger 1 处。
- 基线态：verify_hashes --check 有 1 项**既有** DRIFT（capabilities/echo.py，在飞席位 WIP，非本波面）；doc_sync check 在基线即 AssertionError（`class RouteKind(str, Enum):` 正则在 RWC4 在飞真身上失配，非本波面）——两项按「零新增归因」口径对账。

## 三、移动与真身随迁修正

- **建包 10**：`domains/{ops,core}` 域根 + `ops/{admin,features,monitor,smoke,integrations}` + `core/{config,credentials,search}` 全部纯 docstring `__init__.py`（防环零导入）。
- **mv 59 件**（文件系统移动，脚本 `$TEMP/v21r2-rwoc/move.py` 单次执行，含前置断言：contracts/ 无 S10 漂移文件、目标域不存在、59 源件齐）。WIP 随迁零内容改动（contracts/runtime.py=M、envelope/errors/request、decision/outbound*、supervisor/ 整包均为未提交/未跟踪态，按 RW6-RWC2 先例随迁）。
- **真身随迁修正**（移动同波，39 处替换规则确定性重写）：
  - 移动集内互引旧绝对路径 → canonical：contracts×N（error_report/alerts/event_store/event_service/usage_monitor/feature_gate/debug/runtime_admin/runtime_logs/smoke/route_demo/console_chat/diagnostics/config_readiness/audit 族/search_smoke/gscore_bridge/runtime_event_log 等）、`runtime.{error_report,alerts,event_store,usage_monitor}`、`sources.{credentials,credential_health,web_search,search_api}`、`decision.{engine,trace,outbound_contracts,outbound_registry,dispatcher,shadow,ingress}`、`supervisor.*` 自导入 6 处。
  - 相对→绝对：feature_control/feature_gate/feature_catalog `..contracts`/`..control_plane.*`/`.capability_registry`/`.feature_catalog`；intent_telemetry `.question_intent`（留守 runtime→绝对旧路）；search_api/web_search/mcp_web_search_server/search_smoke 互引；contracts/{auto_send,character,finance,media,music}`.runtime`/`.music` + `__init__` 六段；audit/__init__ `.logger`；supervisor/{sandbox_windows,appcontainer_windows} 相对 6 处（含函数级惰性）。
  - `decision/__init__.py` `_LAZY_EXPORTS` 19 条目标串 → canonical（保轻导入惰性语义）。
  - **RWC2 移交对账**：`decision/outbound_registry.py:498-502` trace 证据路径串 `runtime/model_schedule.py:133/:162` → `domains/chat_reply/llm_engine/model_schedule.py:*`、`runtime/usage_monitor.py:396/:656/:674` → `domains/ops/monitor/usage_monitor.py:*`（行号不变，零测试锚定，rg 实证）。
  - 零改动（跨域走现行垫片，W7 裁定口径）：`runtime.{pricing,model_schedule→shim,base_router,settings,capability_registry,question_intent,cache_policy,aliases}`、`llm.*`、`control_plane.*`、`mail_bridge`、`character/*`、`capabilities/{chat,user_copy,echo}`、`output/*`、`sender/*`、`sources/parsers/*`、根 `config`、`message_context`。

## 四、垫片（59 张 = 55 模块 + 4 包 init，全部 PEP 562 活转发）

- 55 张模块垫片：capabilities×5、runtime×10、sources×9、根×5（smoke/route_demo/console_chat/diagnostics/config_readiness）、audit×2、contracts×10、decision×8、supervisor×6——`__getattr__` 实时解析 canonical（RW11/W16/RWC2 模板），调用期旧路 import × canonical 补丁时序分裂天然免疫。
- 4 张包垫片（audit/contracts/decision/supervisor 旧位 `__init__.py`）：包属性优先、AttributeError 再惰性 import canonical 子模块（RWC2 llm 形）——`from audit import logger`、`from contracts import runtime` 型子模块绑定返回 canonical 模块对象。
- **同一性冒烟（实跑）**：canonical 13 模块导入 OK；18 对新旧模块 same-object 断言 + 11 公有名 `is` 校验；contracts 包 8 公有名 identity OK；decision 惰性出口 Dispatcher/CentralDecisionEngine/DecisionTrace identity OK；**插件根导入 OK**（nonebot.init + load，root `__init__.py:78` 多行 `from .contracts import` 多行括号盲区经活转发天然同源，零改动）。

## 五、测试同波改写（9 文件 / 14 位点，monkeypatch 29→0）

| 测试文件 | 形态 | 改写 |
|---|---|---|
| test_error_report.py | 模块别名×2（顶块+函数级）+ 名字导入×2 | 切 canonical |
| test_error_card_async.py | 模块别名+名字导入 | 切 canonical |
| test_thread_pool_atexit_hooks.py | 模块别名 | 切 canonical |
| test_a18_gate_idempotency_rollback.py | 函数级模块别名 | 切 canonical |
| test_auditfix_wave3_resources.py | `from capabilities import platform_credentials as pcred_mod`（子模块绑定=垫片对象陷阱） | 切 canonical |
| test_decision_engine_shadow.py | `import …decision.shadow as shadow_module`（sys.modules 绑定陷阱） | 切 canonical |
| test_supervisor_isolation.py | `import …supervisor.windows_sandbox as ws`（同上） | 切 canonical |
| test_search_api_providers.py | 函数级 `from sources import web_search` ×3（同上） | 切 canonical |
| test_config_control_service.py | `from audit import logger` + setattr(logger,…)（垫片活转发下双解皆活，仍归一 canonical 保口径） | 切 canonical |

纯名字导入消费（contracts 159 文件 + decision/supervisor/monitor/features 族 50+ 文件）垫片覆盖零改动。**文本锚定同步**：①`tests/verify_hashes.py` TRACKED_FILES debug.py→canonical + `tests/test_verify_hashes_coverage.py` BUILDER_SOURCES 同步 + `tests/render_hashes.json` 外科更名（内容不变哈希不变）+ `docs/auto-facts.md` 清单路径同更；②`tests/test_copy_redline_gate.py` gate_scope 扩 `domains/ops/**/*.py`（error_report/usage_monitor 真身迁入防假豁免，W10/W15a 先例）；③`control_plane/log_collectors.py` `_SUBSYSTEMS` 补 `"domains.core.decision": "decision_engine"` 锚（trace/shadow `getLogger(__name__)` 随迁防事件源降级 bot，W14/W15b/W15d 先例）。


## 六、回归（RWOCc 第三棒实跑收口）

> RWOC 静默死亡后 RWOCb 续跑 28 分钟撞 1302 阵亡未及更新日志；RWOCc（2026-09-18）取证判定 RWOC 已完成移动/垫片/真身修正/测试改写/文本锚定全部五面（见下），本席零代码改动，只补回归与终验。固定解释器 venv python；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；basetemp=`%TEMP%/v21r2-rwocc-*`；未跑 dev.ps1。

**取证结论（RWOCc 复核，全部实跑证据）**：
- 迁移状态判定：canonical 侧 core（config/contracts 11/credentials/decision 9/supervisor 7/search）+ ops（admin/features/monitor 9/audit/smoke/integrations）真身齐；原位 60 处（55 模块垫片+4 包 init+supervisor 包垫片串口径校准）逐一 grep 证实均含 `Compat shim` 且指向正确 canonical。decision/ 原位 9 件全为 18 行垫片；**dispatcher.py 真身零内容改动随迁 DSP 成果**（domains/core/decision/dispatcher.py 垫片化，原位留 18 行活转发）。
- **AST 终验**：canonical core+ops 全量 `ast.parse`+名字级扫描（import/ImportFrom/import_module/`__import__` 四轨）旧路径引用=**0**；旧文件路径字符串常量（`runtime/error_report.py:NNN` 型）=**0**；`outbound_registry.py` trace 路径串已 canonical（§三 RWC2 对账实证复核）。
- **monkeypatch 清零复核**：全库 grep 证实测试面零 `setattr`-on-legacy-module；残余 3 处 legacy 别名（test_error_card_contract.py:149 / test_error_report.py:547 / test_operational_failures.py:43）逐处核验均为**只读/call-through**（`_COOLDOWN_LINES` 读取、`build_admin_alert_send_request` 等调用），活转发下与 canonical 同源，无需改写。
- **同一性冒烟（本席 fresh-process 重跑，canonical-first 序）**：20 对新旧模块公有名 attribute `is` 全同源（NONE fails）；`from contracts import runtime` 包级子模块绑定→canonical OK；`decision` 惰性出口 Dispatcher/CentralDecisionEngine identity OK。

**测试实跑（三批 + 门禁）**：
| 批次 | 用例 | 结果 |
|---|---|---|
| 批1（§五 9 改写文件+文本锚定门） | test_error_report / error_card_async / error_card_contract / thread_pool_atexit_hooks / a18_gate_idempotency_rollback / auditfix_wave3_resources / decision_engine_shadow / supervisor_isolation / search_api_providers / config_control_service / copy_redline_gate / verify_hashes_coverage | **292 passed / 1 skipped / 2 failed**（2 failed 全部=test_copy_redline_gate 撞 S14b 在飞文件，归因见 §七①；沙箱复核排除 S14b 三子包后门禁两测试全绿） |
| 批2（core+ops 域家族） | decision_trace_persistence / bot_supervisor / platform_credentials / search_service_v21 / disconnect_notice / event_service_v21 / result_unknown / runtime_feature_gate / runtime_subfeatures / feature_store_integrity / sqlite_feature_store / smoke_config / usage_billing_v21 / usage_card / usage_card_channels / prompt_audit | **348 passed** |
| 批3（legacy 消费者走垫片） | auditfix_runtime_policy / a20_sender_session_order / a03_timeout_retry_semantics / audit_fixes_b / datafix_runtime_paths / detail_and_priority / auditfix_llm_route / channel_health_v2 / operational_failures / feature_cards / phase0_3_features / settings_hot_audit / word_boundary_fix | **229 passed** |
| 门禁 | verify_hashes --check | **EXIT=0**（§二基线既有 echo.py DRIFT 已随在飞席位收敛消失） |
| 门禁 | test_doc_sync_gates | **4 passed**（§二基线 AssertionError 已消失——RWC4 在飞面已收敛） |
| 收集 | 全库 `pytest --collect-only -q` | **8061 collected / 0 error** |
| 导入 | canonical 66 模块+59 垫片+插件根 | **全 OK** |
| 静态 | ruff owned face（core 全域+ops 除 S14b 三子包+原位垫片） | 4 处（decision/outbound.py RUF022 + outbound_registry.py C409×3，归因见 §七②） |

## 七、偏差与移交

1. **copy_redline_gate 红两条（环境性，非本波面）**：S14b 在飞新建 `domains/ops/incident/service.py:215` 存在硬 SyntaxError（`clock: (() -> float) | None = None`——箭头 lambda 非法注解语法，py_compile 实证复现），落入 RWOC 随真身扩面的 `domains/ops/**/*.py` 扫描域被门禁正确拦截；同域 `collectors/napcat_tail.py:47` import 该 redact_text（连带面）。**S14b 新建件零触碰纪律未破**：本席未改其文件、未给门禁加 SyntaxError 容忍（红线门语义不容稀释），以 glob 沙箱（排除 incident/collectors/recovery）实证门禁其余全绿=本波面零新增红。待 S14b 修完语法后门禁自愈转绿。
2. **ruff 4 处（DSP 谱系 WIP 内容，非迁移引入）**：`domains/core/decision/outbound.py`（RUF022 `__all__` 未排序）与 `outbound_registry.py`（C409×3）——两文件 HEAD 不存在（RWC2 手术未提交 WIP），RWOC 按「随迁零内容改动」原则原样搬移，内容归 DSP 谱系所有；本席不越权代改，留 DSP 线或独立 lint 波收敛。
3. **包垫片子模块绑定时序语义（记录备案）**：`from contracts import runtime` 型 from-import 在「canonical 先导入」序下经 `__getattr__` 绑定 canonical 模块对象；一旦 legacy 子模块（垫片文件）先被 import，import 机制会在包上设真名属性使其绑定垫片模块对象——两态下所有公有名 attribute 皆 canonical 同源（20 对 `is` 实证），仅模块对象同一性有別，且全库已零 sys.modules/模块对象式 monkeypatch 打点，无实际影响面。
4. **移交**：ops+core 两域迁移（59 件移动+55 模块垫片+4 包垫片+真身随迁修正+测试改写+文本锚定）经本席全量复核**收官**；§五 改写 9 文件与全部垫片自 RWOC 后未被再动（git status 比对）。根 `__init__.py` 惰性导入切换仍留子波 5（本波未认领）；control_plane/config.py 案B/sources{search_intent,acg_search}/runtime{capability_protocols,database_broker,loop_watchdog} 仍按 §一不迁。
