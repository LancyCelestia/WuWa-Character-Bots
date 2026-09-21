# 控制面 API 与工作区 · 白名单远程动作

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.control-plane-api · 白名单远程动作

- 层级：一级 B09 → 二级 control-plane-api → 三级 `remote-actions`
- 实现落点：`plugins/bot_unified_runtime/control_plane`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把"运维动作"变成可预览、可确认、可审计、可幂等重放的一等资源，而不是一堆
散在 shell 里的命令。动作**必须是启动装配时显式注册的异步 handler**——HTTP 参数
永远不会被当成代码、路径或平台 API 名来执行，这是本卡的第一红线。

一次动作的完整生命周期：预览（拿到一次性确认令牌）→ 执行（校验令牌 + 幂等键 +
CAS 版本）→ 受控异步运行（超时截断）→ 落回执与审计。任何一步失败都有稳定错误码，
不出现"不知道发没发生"的中间态；真出现了就明确记为 `unknown`，绝不猜成功。

## 怎么调用

实现：`control_plane/actions.py:ControlActionService`（业务）+
`control_plane/api/actions.py:build_actions_router`（HTTP 投影）。

| 端点 | 语义 |
|---|---|
| `GET /api/v1/actions` | 动作目录（含版本、角色、超时、是否需要确认） |
| `GET /api/v1/actions/{action_id}` | 单动作描述 |
| `POST /api/v1/actions/{action_id}/preview` | 签发确认令牌（TTL 300 秒，同身份同动作只留最新一枚） |
| `POST /api/v1/actions/{action_id}/execute` | 执行；需 `confirmation_token` + `idempotency_key` + `expected_version` |
| `GET /api/v1/actions/runs` / `runs/{run_id}` | 运行记录（回执状态、结果摘要、error_code） |
| `POST /api/v1/actions/runs/{run_id}/cancel` | 协作式取消（只 `task.cancel()`，不强杀线程/进程） |

现役注册的 13 个动作 id 就是核心要求点名的那一组（`runtime.reload`、
`runtime.safe_restart`、`adapter.reconnect`、`napcat.status`、`queue.pause`、
`queue.resume`、`queue.drain`、`logging.level`、`resources.refresh`、
`llm.routes.reload`、`knowledge.reindex`、`memory.maintenance`、
`diagnostics.snapshot`），装配点在 `_app.py`（`action_ids` 常量 + `_default_action`）。
`/bot` 侧与 HTTP 侧共用同一 Service；WebUI 插件目录的 `config_actions` 字段读
`ControlActionService.registry_pairs()`（零 DB 访问的 id+label 投影）。

## 开关与参数

- 权限：`super_admin` 独享 preview/execute/cancel（`_validate` 与 `cancel` 双处判）。
- 描述符约束（`ControlActionDescriptor.__post_init__`）：`timeout_seconds` 必须落在
  `(0, 300]` 且有限；`rollback_supported=True` **构造期即 raise**
  （"Rollback adapter is not implemented"）——所以目录里回滚能力恒为 false，
  这是诚实登记而不是遗漏。
- 参数面：`parameter_schema` 固定 `additionalProperties: false` 且无属性，
  `_validate` 拒绝任何非空 parameters（422「该动作不接受额外参数。」）。
- 幂等：`(actor, idem)` 唯一，重放返回首次回执；同键不同请求摘要 → 409
  `idempotency_conflict`。
- 并发闸：全局 `running`/`unknown` 记录数 ≥ 16 → 429 `action_capacity`；
  同一动作已有 `running`/`unknown` → 409 `action_busy`。
- 开关依赖：构造时可注入 `feature_allowed(action_id)`，被功能门关住的动作 409
  `feature_disabled`。
- 存储：`bot_control_plane_actions_db`（缺省 `data/control_plane_actions.sqlite3`，
  经 runtime_paths 重映射；**需重启**，装配期一次性建表）。

## 失败时看到什么

13 个动作**都注册了**，但执行适配器分三档，回执里如实标：

- **真做**：`logging.level`（改 root logger 级别）、`resources.refresh`（现采一份快照）、
  `diagnostics.snapshot`（自报 control_plane 运行态）、`napcat.status`（走装配注入的
  实时探针 `runtime_state_probe`；探针未配置时明确
  `{connected:false, source:"probe_not_configured"}`，**不拿装配期标量冒充连接声明**）。
- **半做（依赖注入才生效）**：`queue.pause|resume|drain` 需要装配时传入 send_queue，
  取不到方法就返回 `status=degraded, execution="send_queue_not_connected"`；
  `runtime.reload` 只重读设置存储覆盖，不做资源 reload。
- **只登记不执行**：其余（`runtime.safe_restart`、`adapter.reconnect`、
  `llm.routes.reload`、`knowledge.reindex`、`memory.maintenance`）统一返回
  `status=degraded, state="registered", execution="adapter_not_connected"`。
  degraded 是**合法回执**（审计记 `succeeded`），但 `details.execution` 明说没接上——
  读侧必须看 details，不能只看 status。

其他失败面：存储不可用 503 `action_store_unavailable`（宁可不做也不做无痕动作）、
确认过期/不匹配 409 `confirmation_required`、超时 `state=timed_out` +
`error_code=action_timeout`、超时后仍取消不掉 `state=unknown` +
`action_outcome_unknown`（此时重复执行被 `action_busy` 挡住，须人工核查）、
handler 抛任何异常 → `state=failed, error_code=action_failed`（不回显异常文本）。

已知限制两条：① 动作结果明细经 `_sanitize_action_details` 白名单化，凭证形键名、
URL、路径、自由文本、异常正文一律丢弃；② `cancel` 只能取消**本进程当前持有**的任务，
控制面重启后遗留的 `running` 记录不可取消（409 `action_not_cancellable`），
且该 id 会因 `action_busy` 一直挡到人工清理。

## 测试与验收

`tests/test_control_plane_actions.py`（CAS/幂等/确认令牌单次消费/超时→unknown/
并发闸/取消/回滚构造期拒绝）、`test_control_plane_actions_api.py`（端点姿态与错误码）、
`test_control_plane_v1.py`（目录投影）。
真机（开总开关后）：`GET /api/v1/actions` → 13 条；对 `diagnostics.snapshot`
走 preview→execute 两拍，核对 `runs/{run_id}` 状态推进与
`cp_action_audit` 序列；对 `logging.level` 尝试带 `{"level":"DEBUG"}` → 预期 422
（参数面结构性关闭，这是现状不是故障）。
