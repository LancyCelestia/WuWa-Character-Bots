# 提醒督促 · 时间点解析词表

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.reminders · 时间点解析词表

- 层级：一级 B07 → 二级 reminders → 三级 `natural-time-parsing`
- 实现落点：`plugins/bot_unified_runtime/domains/schedule`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把「几点/多久之后/某个时段」这类中文时间说法解析成一个明确的未来时刻 + 事项文字。它是提醒链的解析层（机制件，不占路由席位），输入是一句原始消息，产出是 `ReminderIntent(remind_at, text, label)`；解析失败或没有提醒信号就返回 `None`。生效条件：句中含提醒信号词（提醒/叫我/记得叫，含繁体）。

## 怎么调用

真身在 `domains/schedule/store/reminders.py:parse_reminder_intent`（配套 `_REMIND_SIGNAL_RE`、`_ABS_TIME_RE`、`_PERIOD_ONLY_RE`、`_REL_MINUTES_RE`、`_REL_HOURS_RE`、`_REL_HALF_HOUR_RE`、`_PERIOD_DEFAULTS`、`_DAY_OFFSETS`）。判定优先级：先相对时间（半小时后 / N 分钟后 / N 小时后），再绝对时刻（带或不带时段词），最后"只有时段词"（如「今晚」→ 20:00）。无明确日词且算出的时刻已过点 → 顺延到明天。缺 `now` 时取配置时区当前时刻（经 timesync 校正）。

覆盖的口语形态（示例，非全量清单）：「12点」「12点半」「下午3点」「明天早上8点」「今晚8点」「半小时后」。日词表收 今天/今晚/今早/明天/明早/明晚/后天；时段缺省表把 凌晨/早上/上午/中午/下午/傍晚/晚上/今晚 映射到基准钟点。

## 开关与参数

无独立配置键；时区口径随 `config.bot_timezone`（缺省 `Asia/Hong_Kong`），由 `build_reminder_store` 在装配期调 `configure_reminder_timezone` 绑定。事项文字截断 120 字。

「明早」= 次日（否则会被当裸「8点」记成今天上午）；「今晚/明晚 + 1~11 点」且无时段词时按晚间语义 +12h（「明晚8点」= 次日 20:00），显式 ≥12 的时辰保持字面不调整——这一族是**已落码待重启生效**，线上未生效。

## 失败时看到什么

无提醒信号、解析不出时间、或算出的目标时刻不晚于现在 → 返回 `None`，由能力层回一句用法提示，不入库、不报错。非法钟点（如 25 点）同样返回 `None`。

## 测试与验收

`tests/test_reminder.py`（各形态解析与顺延/过点判定）。相关：`tests/test_v21r2_reminder_guards.py`。
