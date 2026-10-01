# B04.notes 笔记与授时

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.notes 笔记与授时

> Markdown 笔记 CRUD、自然语言勾选、NTP 授时时序。

- 归属板块：[B04](../README.md)
- 实现落点：`plugins/bot_unified_runtime/domains/notes/capabilities/notes.py`、`plugins/bot_unified_runtime/domains/notes/store`
- 帮助主题：笔记
- 配置键前缀：`bot_notes_`, `bot_time_sync_`（逐键以目录册为准）

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
| [记/看/放下/列表](notes-crud.md) | — | — | — | — |
| [自然语言完成勾选](mark-done.md) | — | — | — | — |
| [NTP 授时与钟差钳制](time-sync.md) | — | — | — | — |
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

你说"记一下：周三要交总结"，她要能原样存下来、之后原样还给你，还能在你说"总结写完了"时把对应那一件勾掉。这件事和"记忆"看着像，其实是**两套存储、两种语义**，本板块反复强调这条红线：

- **笔记**（`domains/notes/`，库路径以 `config.py` 的 `bot_notes_db_path` 为准）：你说存什么就是什么，Markdown 原文照存，不加工、不归纳、不参与人格与好感。删除是真删除。
- **记忆**（`domains/chat_reply/character/` 的 memory 族，库 `BOT_MEMORY_DB_PATH` 指向的聊天记忆库）：她自己从对话里推断出来的关于你的事实，有来源、置信度、衰减和墓碑。

两边互不镜像：删了笔记不会去动记忆库，写进记忆的内容也不会出现在笔记列表里。唯一的公共部分是"它们最终都可能被拼进同一轮 prompt"，那是 B03 的注入面负责的事。

授时（NTP/HTTPS 校时）放在本功能名下，是因为它存在的唯一理由就是给提醒与笔记的时序判断提供可信的"现在几点"——它不改系统钟，只提供一个校正后的 `now()`。

## 处理流程

```mermaid
flowchart LR
  msg[B01 摄取的消息+图片段] --> trig{is_notes_command 词形判定}
  trig -->|命中 REMINDER 路由| cap[domains/notes/capabilities/notes.py]
  cap --> st[NotesStore 单表 notes，读写必带 chat_id]
  cap --> img[data/notes_images 落盘，库内只留引用行]
  ts[domains/schedule/timesync/timesync.py now] --> cap
  st --> res[CapabilityResult 守岸人文案] --> out[B08 出站]
```

## 边界与降级

- **总闸**：`bot_notes_enabled` 缺省 True；`bot_notes_db_path` 经 `scripts/runtime_paths.py` 重映射到 Runtime，不落源码树（启动期不建库）。
- **路由席位**：笔记**不占** `RouteKind`——全部词形收在提醒判定 `is_reminder_command` 里（`RouteKind.REMINDER`），因此它没有自己的路由席位与优先级，帮助层与审计层的能力 id 记账是 `bot.reminder`（见本页列出的现行缺陷）。
- **限额**：单会话笔记数达 `bot_notes_max_per_chat`（缺省值以 `config.py` 该字段为准）时 `add` 返回 None，由能力层给人话提示而不是静默丢弃；单条笔记图片上限 `_MAX_NOTE_IMAGES`、单图字节上限 `_MAX_IMAGE_BYTES`（判据在能力层，store 只认文本）。
- **图片来源与落点双查**：随笔记发来的图片走 SSRF 入口护栏，`file://`/本地路径读取有字节上限，落盘目录名消毒防穿越；删笔记时图片文件随笔记一起清（引用已不在，留着只会积灰）。
- **隔离两层**（2026-09-30 W6 加固，形制照记忆体系那条硬闸 `SQLiteMemoryRepository.retrieve`：`requester_id != subject_user_id` 即拒）：① 会话域——一切读写都带 `chat_id`（= `message.session_id`），A 群看不到 B 群；② 归属域——读/列/删/勾四类操作每次把**发言人**当归属人交给 store（谓词随之恒带 `AND user_id = ?`），能力层再比一次记录自身的归属人。此前第 ② 层只是碰巧成立：现网群会话键形如 `group_<群号>_<uid>`，隔离全靠上游键形态、`notes_store` 自身零判据零测试；现在不再依赖它。不传归属人的会话域调用（提醒族自然语言勾选 `_locate_and_mark`，它只握有 session_key）口径逐字不变。单会话容量配额随归属人计，与可见面同量纲——否则别人记的条目会把她看不见也删不掉的名额占死。
- **授时降级链**：NTP 全败 → HTTPS `Date` 头估偏移 → 多源互证 → 回退系统钟，每级一行日志。`|offset|` 超 `bot_time_sync_max_drift_ms`（缺省值以 `config.py` 该字段为准）或 RTT 超上限的应答，在**单源**口径下不可信、拒收换下一台；整轮被全拒后另有一级互证出口（至少两个不同来源彼此一致、且往返干净到没被建连耗时污染，才取中位数，并以 warning 劝运维去开系统时间同步）——四条资格尺与实现真身见 [NTP 授时与钟差钳制](time-sync.md)。防火墙拦 UDP 123 时走 HTTPS、再不成回退系统钟**属预期行为**，不是故障；⚠ 但"回退系统钟"**不等于**"偏差仍被钳在阈值内"——那一刻用的就是系统钟本身，差多少取决于它自己偏多少。

## 测试与验收

- `tests/test_notes.py`：笔记 CRUD、触发词形态、图片收纳与限额。
- `tests/test_notes_item_checkoff.py`：单条待办的逐项勾选/取消勾选与歧义语义。
- `tests/test_timesync.py`、`tests/test_v21r2_stall_timesync_http.py`：SNTP 报文与偏移钳制、HTTPS 兜底与停摆面。
- 真机：`docs/acceptance-manual.md` 的提醒/笔记面（含「<事项>做完了」并列候选必须追问、不得硬编码矛盾）；重启后看日志里 timesync 首次校时是否成功（本机 UDP 123 被拦时会先出现转 HTTPS 的一行，整链仍失败才见"回退系统钟"warning；出现"多源互证"＝本机系统钟自己就偏了，处置是去开系统时间同步）。
- 用例数以最近一次 `dev.ps1 -Task test` 实跑为准，本文不手写。

## 现行缺陷

1. **归属口径分叉**（P2，待用户裁）：帮助/能力登记表把「笔记」记在 `bot.reminder` 名下，而实现是独立域 `domains/notes/` ⇒ 账单与审计里笔记被算进提醒族。裁决项 = `docs/audit-20260921.md` 的 V1-9 / M-9 / D8（改 id 会影响历史连续性，故不擅改）。
2. **成员级隔离粒度无证据**（P1，V3-8）→ **已修**（2026-09-30 W6）：归属谓词落进 `notes_store` 的读/列/删/勾四类操作、能力层再设判定层归属闸，双向锁在 `tests/test_notes.py` 的「归属硬闸」段（注毒腿 `test_store_owner_predicate_blocks_foreign_list_get_delete` / `test_capability_group_member_cannot_read_or_delete_others`，反向锁 `test_capability_new_note_owned_by_sender_in_shared_session` 等）。原设计**没有**超管代查面，加固也不新增（`test_capability_no_admin_proxy_lookup_face` 钉着）。⚠ 残留两条：① 提醒族自然语言勾选（`domains/schedule/capabilities/reminder.py::_locate_and_mark` / `_handle_checkoff`）仍按会话域读笔记——它只握 session_key、拿不到发言人，现网键形态下不受影响，待该域自行接归属人参数；② 库里 `user_id` 为空的历史无主行在归属域一律不可见（fail-closed，会话域读面仍能看到），要不要认领/清理由运维裁。
3. **撤销勾选的整链生效有半截**（P2，在册）：撤销词形已并入能力层的 `is_notes_command`，但生产路由判定 `reminder.is_reminder_command` 是按正则清单显式引用本模块的，撤销两组正则待其一行收编后才在**整链**生效——此前只有能力层离线可验证完整行为。真机现象是"能力认得、路由不放行"。
4. **旧路径 owner 名未更新**：`docs/db-owners.md` 的 notes 行 owner 仍写 `character/notes_store.py`（再导出垫片），真身是 `domains/notes/store/notes_store.py`；该行的"待生成：生产未重启"标注同样要看重启实况，别读成已落库。
