# 提醒督促 · 提醒

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.reminders · 提醒

- 层级：一级 B07 → 二级 reminders → 三级 `reminder`
- 路由席位：`REMINDER`（matcher `reminder`，command=True）
- 判定优先级：41
- 能力 id：`bot.reminder`
- 实现落点：`plugins/bot_unified_runtime/domains/schedule`
- 帮助主题：提醒
<!-- BOARD-AUTO:END -->

## 这个入口做什么

提醒命令入口（`RouteKind.REMINDER`，判定优先级 41，`capability_id=bot.reminder`）。输入是一句自然语言或显式查询：新增（「12点提醒我写作业」）、列表（「提醒列表 / 我的提醒」）、取消（「取消提醒 <id 前缀>」）、自然语言勾选（「作业做完了」）。产出是一条 `CapabilityResult`（`SILENT_AUDIT` 落审计，正文即回执）。生效条件：路由命中 `is_reminder_command`，且提醒总闸 `bot_reminder_enabled`（缺省 True）开着。

## 怎么调用

- 路由判定：`domains/schedule/capabilities/reminder.py:is_reminder_command`（信号词 + 可解析出时间，或列表/取消/笔记/勾选形态）。
- 能力工厂：`domains/schedule/capabilities/reminder.py:build_reminder_capability`，返回 `(message, decision) -> CapabilityResult`，与 eat 等能力同构。
- 它依赖的中央件：`domains/schedule/store/reminders.py:build_reminder_store`（进程级共享 SQLite）、`...:parse_reminder_intent`（时间点解析）、笔记面 `domains/notes/capabilities/notes.py:build_notes_capability`。勾选消歧追问状态存进程内 dict（TTL 以该件常量为准，运维/测试清理口 `clear_checkoff_pending_for_tests`）。

## 开关与参数

- `bot_reminder_enabled`（缺省 True）：总闸。`bot_reminder_db_path`（库路径的缺省值以 `config.py` 该字段为准，进 path_fields 重映射）。`bot_reminder_llm_extract_enabled`（缺省 False，进阶 LLM 抽取轨留接口）。单会话待办有上限（store 内 `max_pending_per_session`，非独立配置键）。
- 配置键逐键以 `docs/config-catalog-full.md` 为准；热更性遵循铁律「改代码/改配置需重启生效」，装配期快照类键改后当轮不生效。
- 谁能改：新增/取消是会话内人人可用的行为面（群聊任何人可说「X做完了」勾对应会话待办），配置键改动是管理员/运维侧。

## 失败时看到什么

- 时间解析不出：回用法提示「想让我什么时候提醒你？例如…」。
- 判定像转发粘贴：回「这一大段像是原样转发的文字，我就不放进待办啦」。24h 内重复事项：回「这条我刚才记过啦」。清单满时的排满提示以「这个会话的提醒已经排满 20 条了」这句真身话术为准，不静默丢旧。
- 勾选唯一候选只是"有点像"：不替用户做主，追问「你说的是这件吗」，回肯定词才勾；多候选并列：回带编号清单，回序号择一；候选已不在（到点/取消）：诚实说"刚刚已经不在待办里了"。
- 到点投递失败：只记 `reminder {} not delivered ... kept for retry` 日志，不炸主链路，下一轮重投。

## 测试与验收

`tests/test_reminder.py`（解析/存储/命令面）、`tests/test_reminder_tone.py`（分型文案）、`tests/test_v21r2_reminder_guards.py`（粘贴/超限守卫）；真机验收见 `docs/acceptance-manual.md` 提醒相关条目。
