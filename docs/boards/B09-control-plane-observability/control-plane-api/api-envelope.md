# 控制面 API 与工作区 · 统一响应与错误码

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.control-plane-api · 统一响应与错误码

- 层级：一级 B09 → 二级 control-plane-api → 三级 `api-envelope`
- 实现落点：`plugins/bot_unified_runtime/control_plane`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

规定"控制面说每一种话时句子长什么样"：成功是一个 envelope，失败也是一个 envelope，
两边都带同一个关联 id 集合。前端只需写一套解析器，不必为每个端点特判。

结构由 `plugins/bot_unified_runtime/control_plane/api/protocol.py:envelope` 与 `ErrorInfo` 钉死：
`data` / `error` / `meta{request_id, trace_id, schema_version, generated_at}`。
`schema_version` 恒 `"v1"`（字面量类型，写错直接过不了 pydantic）；`generated_at` 是
UTC ISO 毫秒。成功与失败**共用同一个信封**，`error` 里带 `code`、`message`、
`debug_id`、`request_id`、`retryable`、`field_errors`。

## 怎么调用

- 端点内部：`from .protocol import envelope`，直接 `return _ok(payload)`；
  需要复用同一次请求的 `request_id` 时传 `request_id=request.state.cp_request_id`
  （该值由 app 层 `_request_context_middleware` 写进 `contextvar`，端点不自己造新 id）。
- 业务层抛错：`raise ControlPlaneError(status, code, message)`（`plugins/bot_unified_runtime/control_plane/api/__init__.py`），
  或 Service 层 `ControlServiceError(code, message, status_code)`（`services.py`）——
  两者都由 app 级 exception handler 转成信封，端点里不手写错误体。
- 错误体组装唯一出口：`_app.py:error_response`。它同时负责写
  `request.state.cp_debug_id` / `cp_error_code`（审计中间件读这两个字段落痕）、
  `X-Request-ID` 与 `Cache-Control: no-store` 响应头，并把 `retryable` 判成
  `status in (429, 503)`。
- DTO 校验：请求体一律 `extra="forbid"` 的 pydantic 模型（`FeatureChangePayload`、
  `ConfigValuePayload`、`ActionExecutePayload` 等），`expected_version` 强制非负严格 int。
- OpenAPI：`GET /api/v1/openapi.json` 返回整份 schema，并给每条 `/api/v1/*` 操作
  注入 `security: [{ControlPlaneBearer: []}]`；同一份 schema 由
  `tests/test_control_plane_v1.py` 与 RK5 的 operationId 唯一性锁把关。

## 开关与参数

没有开关——它是协议层，关掉就等于控制面不可用。可调的只有两件：

- 载荷上限：分页参数在端点签名里写死区间（`limit` 常见 `ge=1, le=100/500`），
  越界即 422，不静默截断。
- 错误码登记表：`ERROR_RESPONSES` 列出会被 schema 声明的状态码
  （400/401/403/404/409/410/422/429/500/503），新增状态码要同处补一行。

## 失败时看到什么

- 永远看到结构化错误，**不会**看到 Python 异常文本、SQL、路径或环境变量原文。
  `RequestValidationError` 被有意降级成固定文案「请求参数未通过校验。」，因为 FastAPI
  默认会把 `input`/`ctx` 回显，那可能带着刚提交的密钥。
- 未捕获异常 500 `internal_error`：响应体里没有栈，服务端日志只落
  `request_id` + 异常类型名（`_handle_unexpected`）。
- 存储不可用 503 且 `retryable=true`，客户端可以按 `Retry-After`（认证限速场景）退避。
- 版本冲突 409：`version_conflict` / `idempotency_conflict` / `action_busy` 三类语义
  不同，必须区分处理——前者重读后重试，中者说明幂等键用错了，后者禁止重复执行。
- 410 `cursor_expired` 是日志/事件流专属：保留窗口已推进，要求客户端**显式**重新订阅，
  不允许静默重置游标把缺口糊过去。

## 测试与验收

`tests/test_control_plane_v1.py`（envelope 形状、request_id 贯通、OpenAPI 安全声明）、
`test_control_plane_m1.py`（错误体与 debug_id）、`test_control_plane_actions_api.py`
（409/422/503 各态）、`test_control_plane_events.py`（410/422/503 与 SSE 帧）、
`test_secret_redaction_hardening.py` 与 `test_f03_notice_redaction.py`（脱敏出口）。
真机：任选一个端点用错 token、错版本、缺字段三种姿势各打一次，确认三者分别返回
401 / 409 / 422 且响应体不含任何路径或异常文本；`GET /api/v1/openapi.json`
人工核对 `security` 是否已注入每条操作。
