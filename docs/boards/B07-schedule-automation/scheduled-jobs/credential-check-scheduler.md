# 调度器族与定时推送 · 凭据到期巡检

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.scheduled-jobs · 凭据到期巡检

- 层级：一级 B07 → 二级 scheduled-jobs → 三级 `credential-check-scheduler`
- 实现落点：`plugins/bot_unified_runtime/__init__.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

凭据（cookie）到期/失效的定时巡检：开机后按周期在线探测各平台 cookie 是否还能用，一旦有失效的，就用一份"讲清楚怎么了"的告警私聊提醒管理员，免得订阅/抓取在无人知晓时静默失败。

## 怎么调用

真身 `__init__.py:_register_credential_check_scheduler`。注册 interval 任务（job id `bot_credential_check`，`max_instances=1`、`coalesce=True`），回调把探测 `check_credentials_and_report(config, probe=True)` 下放 `asyncio.to_thread`（探测是同步 urllib HTTP，串行多平台可达数十秒，绝不能在事件循环上跑），拿到 `needs_reauth` 的报告后：写审计记录，命中问题则组 `AlertContent`（含出了什么错、影响、怎么解决、位置、时间）经 `send_admin_alert_requests` 私聊 `bot_admin_user_ids`，并就地投递。

## 开关与参数

- 装配门：`bot_credential_check_enabled`（缺省 False，关则不注册）。
- `bot_credential_check_interval_hours`（缺省值与钳制下限以 `config.py` 该字段声明为真身）。收件人取 `bot_admin_user_ids`，为空则发不出（不猜人）。凭据本身的读取与域名归因见 B05/B10 的凭据与凭证咽喉。

## 失败时看到什么

探测整体抛异常 → 只落一条 `credential_check_error` 中危审计、当轮放弃，不炸机器人；无问题 → 记 `credential_check_ok` 低危、不推送。选不到可用 bot 时告警仅入队不外发。

## 测试与验收

`tests/test_platform_credentials.py`（探测与到期判定）、`tests/test_credential_domain_binding_gate.py`（凭据域名归因门）。真机验收：造一条失效 cookie，下一巡检周期管理员私聊收到告警。
