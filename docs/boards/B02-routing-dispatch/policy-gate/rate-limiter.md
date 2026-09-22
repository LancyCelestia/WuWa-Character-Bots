# 门禁与限流 · 双实现限流与回滚

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate · 双实现限流与回滚

- 层级：一级 B02 → 二级 policy-gate → 三级 `rate-limiter`
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

对 `bot.chat` 类请求做滑动窗口限流与防刷屏，返回一个放行/拒绝决定。输入是 `IncomingMessage` + `capability_id`，产出是 `RateLimitDecision`（带 `allowed`、`reason`、`retry_after_seconds`、`audit_tags`）。非 chat 能力、开关关闭、角色豁免等情况一律放行。

## 怎么调用

统一入口是 `plugins/bot_unified_runtime/domains/chat_reply/policy/rate_limit.py::RateLimiter`（Protocol，方法 `check_and_record`）。构造工厂 `build_rate_limiter(config, *, settings_provider=None)`：`bot_rate_limit_db_path` 非空时返回 `SQLiteRateLimiter`，否则 `InMemoryRateLimiter`。审查 A-18 的额度回滚 `rollback()` 是**可选能力、故意不进 Protocol**——调用方（pipeline）用 `getattr` 探测，缺失即跳过（fail-open）；两个内置实现都提供了它。「放行即记账」的生效集由 `_sender_interval_record_applies` / `_group_windows_record_applies` 定义，check 与 rollback 共用同一判据以免管理员的下一次豁免消息被残留记账误拦。

## 开关与参数

设置类 `RateLimitSettings` 由 `build_rate_limit_settings(config)` 从 `bot_rate_limit_*` 与 `bot_group_proactive_*` 键装配（键名在该函数体内以 `getattr` 引用，可在那里核对）。`pass settings_provider` 给 `build_rate_limiter` 时群句数帽/情绪豁免**每次判定实时求值**（可经 `/bot runtime set` 热改），否则退回启动期快照。`SQLiteRateLimiter` 不支持 callable settings，走 SQL 窗口。R3 同人点名最小间隔（`chat_sender_min_interval_seconds`，缺省 45 秒）对所有人一致、不受 `bypass_roles` 豁免；情绪低落命中 `_DISTRESS_LABELS` 时豁免群句数帽。

## 失败时看到什么

拒绝时 `allowed=False`，`reason` 指出触发的哪一道：`sender_min_interval` / `target_min_interval` / `global_window_exceeded` / `session_window_exceeded` / `sender_window_exceeded` / `group_hour_exceeded` / `group_minute_exceeded` / `proactive_cooldown` / `proactive_window_exceeded`。`retry_after_seconds` 给解禁估计。`InMemoryRateLimiter` 求值失败回退默认设置（保持限流、不放开）；`distress_exemption` 识别失败按「不豁免」处理。桶键集合有低频清扫，避免长期运行无界增长。

## 测试与验收

`tests/test_group_rate_limit.py`、`tests/test_sqlite_rate_limit_group.py`（群句数帽两实现同语义）、`tests/test_policy_sender_interval.py`（R3 点名最小间隔，含 InMemory/SQLite 顺序一致）、`tests/test_rate_limit_silent_and_chat_forward.py`、`tests/test_a18_gate_idempotency_rollback.py`（额度回滚）。
