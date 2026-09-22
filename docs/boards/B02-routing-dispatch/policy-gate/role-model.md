# 门禁与限流 · 六级角色与权限叠加

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate · 六级角色与权限叠加

- 层级：一级 B02 → 二级 policy-gate → 三级 `role-model`
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把发送者的 QQ/Telegram 号解析成一串角色标签，供门禁与人格上下文共用一份口径。输入 `IncomingMessage`（读 `sender_id`），产出按固定次序排列的角色列表。它只解析、不做任何允许/拒绝判定。

## 怎么调用

真身是 `plugins/bot_unified_runtime/domains/chat_reply/policy/roles.py::RoleSettings.resolve_roles`。构造入口 `build_role_settings(config)`，从 `bot_admin_user_ids`、`bot_telegram_admin_user_ids`、`bot_super_admin_user_ids`、`bot_enterprise_user_ids`、`bot_trusted_user_ids`、`bot_blocked_user_ids` 六组名单装配成 `frozenset`。角色标签常量与全序在 `roles.py::ROLE_ORDER`；审计标签由 `role_audit_tags(roles)` 生成（普通用户不产标签）。

### 六级与叠加规则

六级为 `user` / `trusted` / `enterprise` / `admin` / `super_admin` / `blocked`，人人都有 `user` 打底。关键一条：**超管自动叠加 admin**——命中 `super_admin` 名单时同时加入 `admin`，因此既有只认 admin 的判定点（`runtime_admin`、pipeline 私聊管理门等）无需逐一感知超管。`blocked` 命中即入列表，由 `gate.py::evaluate_policy` 在最前硬否决。返回值按 `ROLE_ORDER` 过滤，顺序稳定。

## 开关与参数

角色判定是**装配期快照**：名单来自 `Config` 的 `bot_*_user_ids`，改 `.env` 后需重启生效，不经运行时热改（区别于 rate_limit / quiet_hours 的 provider 实时求值）。这是已知架构取舍，登记在 AGENTS 台账，勿在别处另写一份名单解析。

## 失败时看到什么

本件不抛业务异常、也不拦截；它只贴标签。真正的拒绝发生在 `gate.py::evaluate_policy` 读 `ROLE_BLOCKED in actor_roles` 时，返回 `reason="sender_blocked"`。名单为空即无人有额外角色，属正常态不是故障。

## 测试与验收

`tests/test_admin_roster_and_roles.py`（名单装配 + 超管叠加 admin）、`tests/test_why_role_gate.py`（角色在门禁的判定）。
