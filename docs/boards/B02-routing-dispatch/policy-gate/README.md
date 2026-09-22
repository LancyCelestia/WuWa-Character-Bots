# B02.policy-gate 门禁与限流

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate 门禁与限流

> 角色/黑白名单/安静时间/限流/幂等，全能力共用的准入面。

- 归属板块：[B02](../README.md)
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
- 路由席位：`ADMIN`
- 能力 id：`bot.status`
- 帮助主题：角色, 群策略, 限流, 暂停, 为什么
- 配置键前缀：`bot_rate_limit_`, `bot_quiet_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [管理员命令](admin.md) | ADMIN | bot.status | — | 11 |
| [六级角色与权限叠加](role-model.md) | — | — | — | — |
| [安静时间与主动搭话门](quiet-hours.md) | — | — | — | — |
| [双实现限流与回滚](rate-limiter.md) | — | — | — | — |
| [入站幂等](idempotency.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

在能力真正开始干活之前，先统一回答一句话：这条消息现在该不该回、能不能回、多久才允许再回。如果每个能力自己判，就会出现"同一个群 A 能力回、B 能力不回"这种说不通的分裂，也一定会出现漏判。

本功能把所有会话共用的准入面收在一处：角色解析、黑白名单、监听专用号、安静时间、限流、入站幂等。判定口径唯一，能力侧只消费结论。

## 处理流程

```mermaid
flowchart LR
  msg[IncomingMessage] --> roles[roles.resolve_roles]
  roles --> gate[gate.evaluate_policy]
  gate --> quiet[quiet_hours.check]
  quiet --> rl[rate_limiter.check_and_record]
  rl --> idem[event_idempotency 判重]
  idem --> cap[能力执行]
```

硬否决在最前两道：命中 `blocked` 角色（`reason="sender_blocked"`）、入站风险被判 CRITICAL（`reason="critical_input_risk"`）。其后只对群会话生效：监听专用机器人号一律只收不发（`listen_only_account`），群名单优先级为黑名单1 > 黑名单2 > 白名单2 > 白名单1，黑名单是硬否决。私聊不做群策略限制。各段真身分别是 `domains/chat_reply/policy/roles.py`、`gate.py::evaluate_policy`、`quiet_hours.py::QuietHoursChecker.check`、`rate_limit.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/event_idempotency.py`，由 `plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py` 在能力执行前逐段调用；本目录不写死调用行序（以 pipeline 源码为准）。

## 边界与降级

- 真身与垫片：`plugins/bot_unified_runtime/policy/` 是 v21r4-B 重组留下的再导出垫片，判据只有一份，写在 `domains/chat_reply/policy/`。改行为只准改后者。
- 限流是**双实现**（内存版与 SQLite 版），同一套判据两个存储后端，语义必须一致；SQLite 路径不支持热改，装配期取快照。
- 安静时间/主动搭话门依赖好感度档位，好感度取不到时按不放行处理（宁可少打扰）。
- 幂等表未配置时判重整段跳过，属"关闭"不是"故障"。
- 拒绝一律带回 `reason`，不是静默消失；群聊被拦族按既有口径静默，不额外解释。

## 测试与验收

`tests/test_why_role_gate.py`、`tests/test_admin_roster_and_roles.py`、`tests/test_group_policy.py`、`tests/test_policy_quiet_hours.py`、`tests/test_group_rate_limit.py`、`tests/test_rate_limit_silent_and_chat_forward.py`、`tests/test_policy_sender_interval.py`、`tests/test_policy_soft_mention_gate.py`、`tests/test_event_idempotency.py`、`tests/test_a18_gate_idempotency_rollback.py`（清单以本目录各三级入口页逐条为准）。真机验收条目见 `docs/acceptance-manual.md` 对应门禁小节。

## 现行缺陷

SQLite 限流路径与部分调度器族都是装配期配置快照，热改不当夜生效——已登记在 AGENTS 台账「已知问题」表（架构取舍，待统一改造），不是本波新洞。
