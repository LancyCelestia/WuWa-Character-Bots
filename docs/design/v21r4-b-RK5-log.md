# v21r4-B · RK5 席日志（控制面三小债）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

## 断点记录

### T0 取证完成（改前证据）

**任务 1 · 动作明细消毒 xfail**
- 目标：`tests/test_v21_risk_red_cp_app.py:300` `test_risk4_action_details_survive_to_client`（strict xfail，RK4 取证新增）。
- 根因：`control_plane/actions.py:238` 把动作结果 `details` 借道 `RuntimeLogEvent.to_dict()` 走事件白名单消毒（`events.py::_safe_details`，DETAIL_KEYS=ID/数值键+summary）；`connected`/`source` 不在白名单、布尔值在任何分支都不存活 → napcat.status/queue.*/diagnostics.snapshot 明细全灭（`{"connected": false, "source": ...}` → `{}`）。
- 既有契约锚：`tests/test_control_plane_actions.py:52` 断言 `{"token":"secret","request_id":"req_safe"}` → `{"request_id":"req_safe"}`（凭证形键名丢弃、ID 键保留）——新消毒必须保住。
- 裁定：属产品实现缺口（测试本身正确），按交接书授权做动作域专用消毒修根因后转正。修法：actions.py 新增 `_sanitize_action_details`（布尔/有限非负数值/脱敏未变更且标识符形短串/嵌套 dict·list 结构保留；凭证形键名整键丢弃；fail closed 与事件面同口径），替换 RuntimeLogEvent 借道调用；events.py 零改动。

**任务 2 · OpenAPI 重复 operationId**
- 实证：`create_control_plane_app(...).openapi()` 发出 `UserWarning: Duplicate Operation ID traces_api_v1_traces_get for function traces at .../api/v1.py`。
- 根因：`_app.py:511` platform router 挂 `prefix="/api/v1"`（真数据 `GET /traces`，platform.py:102）与 `_app.py:539` v1 router（自带 `prefix="/api/v1"`，v1.py:226 恒 503 stub）同 name+path+method → FastAPI 同 unique_id 撞车，schema `paths["/api/v1/traces"]["get"]` 被后注册者覆写。全 schema 147 op 仅此一对撞车。
- 修法：v1.py stub 端点显式 `operation_id="traces_stub_api_v1_traces_get"`（1 行）；platform 真端点保默认 id 不破坏既有消费面；回归断言加进 tests/test_control_plane_v1.py（全 schema opid 唯一 + 零 Duplicate 警告）。

**任务 3 · platform.py mypy 两错**
- 实证（`-m mypy --explicit-package-bases --ignore-missing-imports <file>`，与 dev.ps1 typecheck 同参）：
  - `platform.py:79: error: Incompatible return value type (got "Callable[[dict[str, Any], str], Coroutine[Any, Any, dict[str, Any]]]", expected "Callable[..., dict[str, Any]]")`
  - `platform.py:254: error: Incompatible return value type (got "Callable[[str, dict[str, Any] | None], Coroutine[Any, Any, dict[str, Any]]]", expected "Callable[..., dict[str, Any]]")`
- 根因：`_make_upsert`/`_make_lifecycle` 声明返回同步 `Callable[..., dict]` 实返 async 工厂。修法：两处标注改 `Callable[..., Coroutine[Any, Any, dict[str, Any]]]`（collections.abc.Coroutine），零运行时改动。
- 基线备注：同命令下根 `__init__.py` 另有 2 个 attr-defined 既有错（1209/1214，WIRE-SVC 席域文件，本席禁改零接触，如实记录）。

## 终稿（2026-09-18 · RK5 三项交付，全部实跑验证）

### 交付 1 · 动作明细消毒 xfail 转正 ✅
- `plugins/bot_unified_runtime/control_plane/actions.py`：新增动作域专用消毒 `_sanitize_action_details`（布尔/有限非负数值/脱敏未变更且标识符形短串/嵌套 dict·list 放行；`_ACTION_KEY_DENY` 凭证形键名整键丢弃；budget 256/depth 4；fail closed），`execute()` 不再借道 `RuntimeLogEvent` 事件白名单（events.py 零改动）。
- `tests/test_v21_risk_red_cp_app.py`：删除 `@pytest.mark.xfail(strict=True)`，`test_risk4_action_details_survive_to_client` 转正常驻回归，台账注记更新为已修。
- 实跑：`pytest tests/test_v21_risk_red_cp_app.py tests/test_control_plane_actions.py tests/test_control_plane_actions_api.py tests/test_control_plane_events.py tests/test_control_plane_v1.py` → **50 passed**（含转正用例与既有消毒契约 `{"token":"secret","request_id":"req_safe"}`→`{"request_id":"req_safe"}` 保持）；具名复跑 `test_risk4_action_details_survive_to_client` **PASSED**。
- 定性：属产品实现缺口（测试正确），按交接书授权修根因转正，非硬转。

### 交付 2 · OpenAPI Duplicate OpID 清零 ✅
- `plugins/bot_unified_runtime/control_plane/api/v1.py`：traces stub 显式 `operation_id="traces_stub_api_v1_traces_get"`（platform 真端点保默认 id，消费面零破坏）。
- `tests/test_control_plane_v1.py`：新增回归锁 `test_openapi_operation_ids_are_unique`（全 schema opid 唯一 + 零 Duplicate Operation ID 警告 + stub opid 可寻址）。
- 实跑：改前 app.openapi() 发 `UserWarning: Duplicate Operation ID traces_api_v1_traces_get`；改后复检 **duplicate warnings: NONE**，traces 族 opid 全唯一；新回归锁 **PASSED**。

### 交付 3 · platform.py mypy 两错清零 ✅
- `plugins/bot_unified_runtime/control_plane/api/platform.py`：`_make_upsert`/`_make_lifecycle` 返回标注改 `Callable[..., Coroutine[Any, Any, dict[str, Any]]]`（async 工厂实返协程），零运行时改动。
- 实跑：改前 `platform.py:79/254` 两处 `[return-value]` 错；改后 scoped mypy（与 dev.ps1 同参 `--explicit-package-bases --ignore-missing-imports`）三触碰文件 **0 error**。备注：导入闭包里根 `__init__.py:1209/1214` 有 2 个 attr-defined 既有错（改前基线已在，WIRE-SVC 席域文件，本席禁改零接触），非本席引入。

### 验收门
- 全树 `ruff check .`：本席 5 个触碰文件（actions.py / api/v1.py / api/platform.py / test_v21_risk_red_cp_app.py / test_control_plane_v1.py）scoped **All checks passed**；全树余 2 错在 `tests/test_phase_determinism.py`（I001）与 `tests/test_v21r3_visual_gates.py`（UP033）——两文件均为并行席位在途（git status：`M` / 未跟踪新文件），按文件域互斥不碰，非本席引入（改前已存在）。
- 扩面回归：控制面+风险红+接线 20 文件 **436 passed in 70.16s**（离线 mock，无真实 LLM/发送/监听）。
- `doc_sync.py` EXIT=0 零漂移（auto-facts.md 既有在途 M 属并行批次，未触碰）；`command_catalog.py --check` → **current (77 topics)**。
- 树卫生：源码树无 `data/`、无 `__pycache__`/`*.pyc` 残留；禁改清单（theme_tokens/render_hashes/domains/render/card_render/验收矩阵/根__init__ 等）零触碰；无 git 写操作。

### 席位状态
RK5 三项交付全部完成，本席收工。遗留移交：全树 ruff 两错归 test_phase_determinism/test_v21r3_visual_gates 所属席位；根 `__init__.py` 两处 mypy attr-defined 归 WIRE-SVC 席位。
