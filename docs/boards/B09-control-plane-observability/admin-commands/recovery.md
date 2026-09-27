# 管理命令面 · 自愈与回滚

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.admin-commands · 自愈与回滚

- 层级：一级 B09 → 二级 admin-commands → 三级 `recovery`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/admin`、`plugins/bot_unified_runtime/domains/ops/incident`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把散在各处的「出问题了自己修」逻辑收拢成一条有纪律的链路：**分类 → 预算 → 动作 →
验证 → 稳定窗口 → 风暴熔断**。自愈只做重连、有限重试、worker 恢复、缓存重建、资源
回滚、UNKNOWN 对账六类；代码修复不在自愈范围（归类 `PATCH_REQUIRED` 不可重试、只上报
——补丁必须待审，绝不自动部署）。真身 `domains/ops/recovery/service.py::RecoveryService`
（V21-HEAL-001 唯一载体）。

## 怎么调用

服务本体依赖全注入、全离线确定性可测——**它自己不做任何真实重连/回滚**：

- 恢复动作由注入的 `executor` 执行（装配席把 SnowLuma 重连、worker 恢复等真实执行体
  接进来；`DEFAULT_ACTION_BY_KIND` 把故障 kind 映射到六动作之一）。
- 上报经 `IncidentReporter` 协议对接 `domains/ops/incident/service.py::IncidentService`
  （结构化事件 + 同因聚合，见 [diagnostics](diagnostics.md)）；真实 admin 推送
  （SendQueue/outbox）由接线席注入 sink，本模块默认只走 stdlib log、不碰出站。
- 动作后走注入的 `verifier` 复核；没有 verifier 时诚实标注 `verified=None`（未验证），
  **不伪称已恢复**。
- 可注入 `rng` 保证退避 jitter 离线可复现。

**接线现状（如实）**：根 `__init__.py` 现算无 import——本载体「建成未通电」，
挂接坐标留在 `docs/design/v21r2-s14-log.md` §三；历史自愈行为仍散在
`domains/ops/monitor/alerts.py`（重连对账）与出站 worker（挂起重试）处。禁止把
「自愈可恢复运行」叙述成已经过这条统一链路。

## 开关与参数

- 预算：每资源滚动窗（`attempt_window_seconds`）最多
  `max_attempts_per_window` 次动作，超预算**升级上报、不再动作**（窗长与次数缺省
  以构造参数为准，本页不写死）。
- 退避：full-jitter 指数退避，基础与上限是模块常量（1s 起步、30s 封顶口径写在件内）。
- 稳定窗口：动作成功后 `stable_window_seconds` 内同组件复发 → 档位升级
  warning→error→critical；窗口外安静则归零重来。
- 风暴熔断：全局滚动窗内启动次数超 `storm_threshold` → 熔断打开（只上报不动作），
  冷却期满放行一次探测，再超阈再熔断——防「故障→恢复→再故障」递归放大。
- executor 实现侧纪律（服务不注册此类动作）：数据库疑损不删库；不更改密钥/代理/
  权限/人格/审计。
- 本入口无独立 `.env` 开关：通电与否是装配问题，不是配置问题。

## 失败时看到什么

对调用方**永远透明**：executor/reporter/verifier 抛异常一律捕获降级（fail-open），
绝不外溢；不可重试类只上报绝不硬试（重试必然复发）。用户/管理员侧看到的是 Incident
通知（带首次时间、累计计数、档位），而非静默的动作尝试；恢复失败表现为升级档位的
告警，恢复成功也只在 verifier 通过时才声称成功。

## 测试与验收

`tests/test_v21_s14_recovery.py`（六动作映射、预算窗、jitter 退避确定性、稳定窗口
升档、风暴熔断与探测、fail-open、verified=None 诚实面）、`tests/test_v21_s14_incident.py`
（载体对接）。用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑为准。真机验收在接线
之后才有意义：断一次协议端连接，确认走的是本链路的「重连动作 + 验证 + 事件上报」，
且滚动预算窗内同一资源动作次数不超预算（窗长以构造参数为准）。
