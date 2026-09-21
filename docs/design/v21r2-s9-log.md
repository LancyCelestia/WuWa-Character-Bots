# v21r2 S9 席日志 — 模型控制 REST 全量 + Workspace 服务（2026-09-18）

## 〇、席位合同
- 交付：/api/v1/llm/* 全量（providers/channels/models 列表+详情、health 聚合、routes、routes/preview、models/{id}/test、config/preview+apply、cache/reload）+ Workspace 服务收口（real_session 确认路径诚实 503 not_wired、审计+Trace）。
- 合同：docs/核心要求.md §九/§十一、backend-v2-implementation-guide.md、control-plane-workspaces.md、验收矩阵 V21-ROUTE-001 / V21-WORKSPACE-001。
- 禁触：llm/model_router.py、channel_health.py（只读消费）、chat.py、personas/、__init__.py、policy/、bot.py、sender/*、domains/**、character/*、content_route.py。

## 一、现状侦察结论（实施前提）
1. Workspace 服务层 `control_plane/workspaces.py` + API `control_plane/api/workspaces.py` + `factory.build_workspace_service` 已由前波落地（sandbox 生成器、确认 token 哈希消费、幂等回执、审计表、TTL prune），非"纯 503 占位"；残余缺口=①real_session deliver 端口缺失时 send 会先消费确认再报 workspace_send_unknown（不诚实、烧确认）；②envelope meta 无 trace_id。
2. `api/llm.py` 既有 LLMControlCatalog 只有 providers/channels/models/health/routes 最小面：无 EWMA/健康/优先级/预算/effort/fingerprint、无 routes/preview 真投影、无 models test、无 config preview+apply、无 cache reload。无测试断言其错误码，可安全重写。
3. R1 语义（只读消费，不改排序）：`ModelRouter.route_ids/channels_for_model`（严格注册表优先级）+ `_health_filter_candidates` → `_demote_cooling_candidates` → INTIMATE grok 钉一守卫发生在 `_generate_impl`（model_router.py:1875-1909）。preview 投影按同一管线顺序调用只读函数（import 复用，不复制语义）。
4. 健康库：`channel_health.get_channel_health_store()` 进程级单例、路径 runtime 重映射。控制面服务必须**可注入** store（测试隔离，不触 Runtime）；_app 已解析的 channel_health_store 需一线传入 build_v1_router。
5. 认证：读依赖=_v1_read_dependency（读 token→roles=("admin",)；超管 token→("super_admin","admin")）；写依赖=超管 token。RBAC：读=admin+、写=super_admin，与既有依赖天然对齐。
6. envelope：/api/v1 统一走 `control_plane/api/protocol.py::envelope`（meta 缺 trace_id）；S2 `contracts/envelope.py` 是 V2.1 权威但旧侧适配明确留给后续席位——本席做**增量**：meta 加 trace_id 键（全树仅 1 处断言 meta["schema_version"]，加键安全）。
7. 错误码：新端点尽量用 `contracts/errors.py` 注册码（resource_not_found/permission_denied/validation_error/confirmation_required/version_conflict/dependency_unavailable）；既有依赖层 403 "forbidden" 为存量事实不动。**席位本地诚实码两个**：503 `not_configured`（llm live 测试）、503 `not_wired`（workspace 真实发送）——不在 41 注册表内，系合同原文点名的诚实标记，登记于本日志备查（contracts/errors.py 非本席文件域，不加表）。

## 二、改动清单（计划）
| 文件 | 动作 |
|---|---|
| control_plane/llm_admin.py（新） | LLMControlService：注册表/渠道/模型/健康/路由投影（复用 build_model_registry/_preset_specs/_main_fallback_spec + ModelRouter 只读消费）+ fingerprint（sha256 前 12 hex，永不回明文）+ routes/preview 管线投影 + dry 单模型校验 + config LLM 键白名单（bot_chat_/bot_model_/bot_llm_/bot_content_route_ 前缀）+ cache rebuild + 审计事件（RuntimeLogEvent source=control_plane） |
| control_plane/api/llm.py（重写） | 全 13 端点；读=admin+ 依赖；config/preview+apply、cache/reload 走写依赖（超管）；models test dry=读、live=内部超管门+确认门+503 not_configured |
| control_plane/api/v1.py | 换装 LLMControlService；签名加 channel_health_store/event_bus 两参 |
| control_plane/_app.py | build_v1_router(...) 传入 channel_health_store 与 app.state.event_bus（两行） |
| control_plane/api/protocol.py | envelope meta 增 trace_id（additive） |
| control_plane/workspaces.py | send() 确认路径：token 校验通过后、**消费前**检查 real_session deliver 端口 → 503 not_wired（确认不烧、幂等键不污染）；审计/trace 已有 request_id，envelope trace 由 API 层补 |
| tests/test_v21_s9_llm_api.py（新） | envelope/RBAC/详情无明文凭证/严格优先级投影/INTIMATE 钉一投影/preview 零副作用/dry 校验/live 诚实 503/config 预览+应用/cache reload |
| tests/test_v21_s9_workspace.py（新） | sandbox 隔离（独立 session/Prompt、模拟发送、不写生产店）/real_session 建门+脱敏预览/确认门/not_wired 不烧确认/旧确认失效/审计 trail |
| docs/db-owners.md | 追加 S9 段：cp_workspaces / cp_workspace_audit / cp_workspace_sends（前波建表未登记，本席补登） |

## 三、四列状态（本席视角，共享矩阵不改）
- V21-ROUTE-001：partial → 本席后 API 面完整（读投影+预览+配置面+reload）；执行门（控制面直接驱动生产路由）仍不在本轮——四列 status 建议 partial→partial(API 全量落地)。
- V21-WORKSPACE-001：partial → sandbox 隔离与确认协议已有+本席补 not_wired 诚实化与 trace；real_session 真实发送端口本轮不实装（合同如此）。

## 四、实跑证据（全部直跑；解释器=Runtime venv；env PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；pytest --basetemp=$TEMP/v21r2-s9* -p no:cacheprovider）

1. 新增测试两文件：`12 passed in 7.26s`
   - tests/test_v21_s9_llm_api.py（6 例）：凭证零明文泄露（含 fingerprint 逐字节核对、query 串剥离、env 名不回传）、provider/channel/model 详情与严格优先级投影、health 聚合 degraded/cooling/unavailable、routes 策略面、routes/preview（auto/模型名聚合/INTIMATE 模拟/冷却回落+健康过滤+零副作用）、models test dry 校验+live 越权 403→409 确认门→503 not_configured、config preview 不落盘/apply 逐键 CAS 链推进+RBAC 403/非 LLM 键 422、cache reload 作用域诚实注记、审计事件（RuntimeLogEvent 白名单键适配）。
   - tests/test_v21_s9_workspace.py（6 例）：sandbox 独立 session/模拟发送/消息脱敏落库、real_session 超管门+只读脱敏上下文（prompt 剥离+密钥打码）、real_session deliver 端口缺失 send=503 not_wired 且**确认不消费**（重试仍 not_wired 而非 confirmation_required、状态恒 idle）+带端口对照组 queued、无适配器建 real_session=503、消息变更使旧确认失效、HTTP RBAC（读令牌 403）+审计 trail+envelope trace_id。
2. 控制面存量回归 12 文件：`365 passed, 4 warnings in 43.88s`（warning=api/platform.py(V1席批次)与 api/v1.py 并存 /traces 致 openapi Duplicate Operation ID，**存量非本席引入**）。
3. ruff 触达 8 文件：`All checks passed!`。mypy（--explicit-package-bases --ignore-missing-imports）本域 3 文件零错误；带出 2 错均在 control_plane/api/platform.py（V1 席在飞既有基线，与本席零交集）。
4. 树卫生：PYTHONDONTWRITEBYTECODE=1+basetemp 隔离直跑，源码树无 data//__pycache__/.pytest_cache 新增；健康库经 monkeypatch 注入 tmp，全程零触碰 Runtime。

## 五、诚实边界与四列（本席记账）

- **席位本地错误码**：503 `not_configured`（llm live 测试端口未实装）、503 `not_wired`（workspace 真实发送端口未实装）——合同原文点名，不在 contracts/errors.py 41 注册表内（该文件非本席域未加表）；其余新码全走注册表（resource_not_found/permission_denied/unsupported_parameter/confirmation_required/version_conflict/config_store_unavailable）。
- **routes/preview 语义**：投影≠执行。会话滞回态活在 bot 进程，控制面跨进程不可读；`simulate_intimate=true` 是显式模拟（head_models 推导对齐 content_route.py:288-296），响应 `state_source` 如实标注 simulated / not_available_cross_process。执行门未接（验收矩阵该列维持）。
- **cache/reload**：只重建控制面进程内投影缓存；bot 进程路由缓存须经 `llm.routes.reload` 动作（/api/v1/actions/.../execute），响应 note 内置该指引。
- **凭证**：只回 SHA-256 前 12 hex fingerprint + 状态 + 密钥数；base_url 只回 origin（剥 query/fragment）；测试断言明文/env 名全响应体零命中。
- **config/apply 非原子**：逐键 CAS 链式推进（version 随返回行推进），中途失败保留已应用前缀并告警事件；preview 先行全量校验降低半途概率。
- **_app.py 最小触达**：仅 build_v1_router(...) 增传 channel_health_store 与 event_bus 两参（接线必需，已在协调文件报备）。
- 四列建议：V21-ROUTE-001 = partial（API 面：providers/channels/models/health/routes/preview/test/config/cache 全量落地+实跑证据；执行门未接）；V21-WORKSPACE-001 = partial→sandbox 隔离/确认协议/审计齐备，real_session 生成与只读脱敏已实现，**真实发送端口本轮不实装**（合同如此，send 缺端口=诚实 503 not_wired，不烧确认）。
- db-owners.md：追加 `data/control_plane_workspaces.sqlite3`（cp_workspaces/cp_workspace_audit/cp_workspace_sends 三表，前波建表未登记，本席补登）。

## 六、遗留
1. llm live 测试与 workspace real_session 真实发送两端口待装配席接线（接线后删 503 短路即可，协议已就位）。
2. not_configured/not_wired 两码若裁决收编进 contracts/errors.py 41 注册表，由 S2/协议席统一加表后本席改引用。
3. traces Duplicate Operation ID 告警（platform.py vs v1.py）建议 V1 席收口。
4. 未 commit（共享工作树，提交裁决权在用户）。
