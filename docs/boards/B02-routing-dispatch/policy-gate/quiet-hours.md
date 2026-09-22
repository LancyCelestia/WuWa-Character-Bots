# 门禁与限流 · 安静时间与主动搭话门

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.policy-gate · 安静时间与主动搭话门

- 层级：一级 B02 → 二级 policy-gate → 三级 `quiet-hours`
- 实现落点：`plugins/bot_unified_runtime/policy`、`plugins/bot_unified_runtime/domains/chat_reply/policy`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

在设定时段内压低机器人的主动搭话，但绝不挡真人有意的请求。输入 `IncomingMessage` + `capability_id`，产出 `QuietHoursDecision`。缺省关闭（`QuietHoursSettings.enabled` 默认 False）。

## 怎么调用

判定件是 `plugins/bot_unified_runtime/domains/chat_reply/policy/quiet_hours.py::QuietHoursChecker.check`。工厂 `build_quiet_hours_checker(config, *, settings_provider=None)`：给 provider 时每次判定实时求值（安静时间可读运行时 store 热改，不被装配期快照吃掉），否则退回启动期快照。它只负责「这段时间能不能主动说话」，主动接话的概率抽签与好感门在 `gate.py` 与 rate_limit 层，别处不重复实现。

## 开关与参数

`QuietHoursSettings` 的时间与时区由 `build_quiet_hours_settings(config)` 从 `bot_quiet_hours_*` 键装配（`enabled`/`start`/`end`/`timezone`/`session_types`/`bypass_roles`，键名在该函数体内以 `getattr` 引用可核对）。时段用 `HH:MM` 字符串、按 `zoneinfo` 命名时区判定，跨零点窗口（start>end）与相等窗口（视为全天静默）都有处理；时区非法在 validator 阶段直接 `ValueError`。`session_types` 只接受 `private`/`group`。

## 失败时看到什么

放行有多种 `reason`：`disabled`、`role_bypass`（管理员豁免）、`session_type_excluded`（会话类型不在管控集合）、`outside_quiet_hours`、`direct_request_bypass`（点名或 `capability_id` 非 `bot.chat`/`bot.content` 的直接请求）。唯一拒绝是 `reason="quiet_hours"`、`allowed=False`。设置求值失败回退默认（不误拦消息）。

## 测试与验收

`tests/test_policy_quiet_hours.py`（时段/豁免/直连请求分流）、`tests/test_v21r2_hotzone_quiet_silence.py`（静默带行为）。
