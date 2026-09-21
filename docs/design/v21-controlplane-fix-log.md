# V2.1 控制面修复席日志（A10 第三次派遣）

> 席位：控制面修复席；基线：`docs/design/v21-s0-baseline.md`（控制面域 60 失败/错误）。
> 纪律：直跑解释器=Runtime venv；PYTHONDONTWRITEBYTECODE=1；PYTHONUTF8=1；BOT_AUTOSYNC=0；pytest `--basetemp=$TEMP/v21-cpfix3/* -p no:cacheprovider`；禁 git 写、禁子代理、未动取证席域与禁触测试。
> 本页随修随写：每收绿一组立即落盘。

## 结论速览

- 基线控制面域 60 失败/错误 → 归纳为 **3 个根因（A/B/C）**，其中 A 为单点硬锚（`_app.py:425 UnboundLocalError`），B 为 A 解封后第二层（`api/platform.py` FastAPIError），C 为 1 条过期测试断言。
- 收绿终态：**控制面全域 457 passed / 0 failed**（17 个测试文件，实跑 final 轮）；`tests/test_control_plane_v1.py` 单跑 3 passed 无回归；改动文件 ruff `All checks passed` + mypy `Success: no issues found in 2 source files`。
- 取证席 strict-xfail 转 XPASS 2 条（预期收益，转正归取证席）。

## 根因分组总表

| # | 位置 | 根因 | 修法 | 波及测试（基线） |
|---|---|---|---|---|
| A | `control_plane/_app.py:425`（同型 465） | `_path` 仅在 `if event_service is None and events_path:` 分支内局部导入，而 425 行 action_path、465 行 platform_path **无条件**使用 → 任何 `event_service` 注入或未配 events_db 的 `create_control_plane_app` 调用即 `UnboundLocalError: _path`。基线硬锚点，独立入口 `serve()` 同炸 | `from .factory import _path, build_feature_service` 提级到模块顶（`_app` 顶部本就导入 `.factory`，零新增循环风险），删除分支内重复局部导入 | services 20E、actions_api 7E、workspaces_api 2E、host_guard 14F、m1 9F、log_collectors 2F、resources 1F、v1 2F、runtime_feature_gate 3F 的 setup/首层崩 |
| B | `control_plane/api/platform.py:66-82` `upsert`（A 解封后第二层） | `principal: Principal` 无默认值 → FastAPI 当必填 body 字段；`Principal` 为普通 dataclass 非 Pydantic 模型 → PydanticSchemaGenerationError → `FastAPIError: Invalid args for response field`（fastapi/utils.py:75），`build_platform_router` 注册期整体炸，app 工厂任何配置都无法完成装配 | 移除死参数 `principal`（函数体零使用；鉴权由路由级 `dependencies=[Depends(write_dependency)]` 承担，非削弱） | 同上族第二层 ERROR |
| C | `tests/test_control_plane_services.py:184` | 断言 `actions.available is False` 与 WIP 中途态不符：前批已在 `_app.py` 默认装配 `ControlActionService`（13 动作注册）+ `api/actions.py` 路由 + 专属测试文件，`api/v1.py:74` 按注入诚实上报 available=True | **按前批实现意图修断言** → `is True`，测试内附注释注明理由；协议发现语义本就是「有服务才宣称」，非改断言掩盖 | test_protocol_discovery_does_not_advertise_unimplemented_services |
| D（静态门顺手修） | `api/platform.py:187` / `:366` | WIP 残留 mypy 2 错（非本轮引入）：① rollback `version` 为 `Any\|None` 直传 `int()`；② audio 分支 `provider` 跨类型复用（ASR 赋给 Vision 变量） | ① None 先显式 422「回滚版本无效」（与原 `int(None)→TypeError→422` 行为等价）；② 局部重命名 `asr_provider`，零行为变化 | 无（ruff/mypy 门禁） |

**归属说明**：host_guard 14 / m1 9 / log_collectors 2 / resources 1 / v1 2 / runtime_feature_gate 3 / actions_api 7E / workspaces_api 2E 全部实跑确认为根因 A（部分叠加 B）的同源扩散，无独立缺陷、无需逐条改动；`test_distinct_admin_tokens_are_required`（基线单独 FAILED）实跑随根因 A/B 修复自动转绿，无独立改动。

## 阶段实跑记录（全部实跑，解释器=Runtime venv）

### 阶段1：services 域（基线 1F+20E → 24 passed）

- 复现（修复前）：`pytest tests/test_control_plane_services.py` → `24 errors`，首层全部 `UnboundLocalError: cannot access local variable '_path'` @ `_app.py:425`。
- 修 A 后：`1 failed, 4 passed, 19 errors`——第二层 `FastAPIError ... <class '...auth.Principal'> is a valid Pydantic field type` @ `api/platform.py:77`。
- 修 B 后：`1 failed, 23 passed`（仅剩 test_protocol_discovery，断言 actions 可用性）。
- 修 C 后收绿：`24 passed, 3 warnings in 8.27s`。

### 阶段2：扩散域逐一实跑确认（全部同源 A/B，零新增改动）

```
tests/test_control_plane_actions_api.py + tests/test_control_plane_workspaces_api.py → 9 passed
tests/test_control_plane_host_guard.py → 17 passed（基线 14F 同源根因 A）
tests/test_control_plane_m1.py + log_collectors + resources + v1 → 48 passed（基线 14F 同源）
tests/test_runtime_feature_gate.py → 10 passed（基线 3F 同源）
```

### 阶段3：控制面全域收绿（17 文件实跑）

```
pytest tests/test_control_plane_actions.py actions_api events host_guard lifecycle
  log_collectors m1 metrics resources sandbox services v1 workspaces workspaces_api
  config_control_service runtime_feature_gate sqlite_feature_store
→ 457 passed, 5 warnings in 34.64s   （final 轮复跑同结果）
```

### 阶段4：静态门 + 回归门

- ruff（改动文件，--no-cache）：`All checks passed!`
- mypy（项目口径 `--explicit-package-bases --ignore-missing-imports`，改动 2 文件）：初跑 `platform.py` 2 错（根因 D）→ 修后 `Success: no issues found in 2 source files`。
- `tests/test_control_plane_v1.py` 单独复跑：`3 passed in 1.89s`（无回归）。
- 零缓存自查：control_plane 包与 tests 下无 `__pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache/data/`（find 实跑空输出）。

## 取证席域 XPASS 记录（只记录，转正归取证席）

`tests/test_v21_risk_red_cp_app.py`（禁触域）实跑观察：`2 failed, 11 xfailed`——
- `test_risk4_default_app_creation_survives_without_events_db` → **XPASS(strict)**（其 xfail 理由文本即根因 A 原文，已修复）；
- `test_risk4_app_creation_survives_with_events_db` → **XPASS(strict)**（其 xfail 理由即根因 B，已修复）。

两条为「修复使其变 XPASS 转红」的预期收益，strict 标记下计 FAILED；**未触碰该文件**，转正（移除 xfail 标记）由取证席负责。

## 遗留与登记项

1. **Duplicate Operation ID 告警**（非失败）：`traces_api_v1_traces_get` 重复——`api/v1.py` traces 路由与 `api/platform.py` `/traces` 路由 OpenAPI operation-id 撞名，仅影响 openapi.json 导出面告警。本域 openapi_url 默认关闭，影响有限；登记给主会话裁决是否改名（属接口面变更，未擅动）。
2. **禁触域基线失败不在本席账内**：test_affinity_v21_budget 7F、test_channel_health_v2 1F、test_cross_validation_gates doc_sync 1F（机器事实册漂移，属并行文档编辑）。
3. **取证席域**：risk_red 其余 11 条仍按预期 xfailed；XPASS 2 条待其转正。
4. 本席改动文件（3 代码/测试 + 本日志，未 commit，工作树共享）：
   - `plugins/bot_unified_runtime/control_plane/_app.py`（根因 A）
   - `plugins/bot_unified_runtime/control_plane/api/platform.py`（根因 B、D）
   - `tests/test_control_plane_services.py`（根因 C）
