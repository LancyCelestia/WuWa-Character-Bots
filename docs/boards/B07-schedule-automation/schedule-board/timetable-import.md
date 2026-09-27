# 日程板与智能代答 · 课表文本/图片导入

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B07.schedule-board · 课表文本/图片导入

- 层级：一级 B07 → 二级 schedule-board → 三级 `timetable-import`
- 实现落点：`plugins/bot_unified_runtime/domains/schedule/capabilities/schedule_board.py`、`plugins/bot_unified_runtime/domains/schedule/service/board_store.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

把课表整批记进她的日程板。文本形态：「日程 导入」或「课表 导入 …」后跟多行 `周五 8:00-9:40 高数 教三302 单`；图片形态：发来课表截图、配一句「课表」即可。认出的每行落成一条周循环条目，**缺省按隐私存**——导入≠公开，对外可答是她另下的决定（「日程 公开 N」）。同一份课表重发（同标题+同星期+同刻）不双记。含单双周教学的行必须带一句「学期 2026-09-07」锚，缺了就回问，不替她猜日期。生效条件：记录腿总闸 `bot_schedule_enabled` 开。

## 怎么调用

- 判据：`schedule_board.py` 的 `_BOARD_IMPORT_RE`（「日程导入 / 课表导入 / 课表 / 課表 / kebiao」+ 可选正文），经与路由腿同源的 `is_schedule_surface` 进车道。
- 能力入口：`build_schedule_board_capability` 内部分发 `_handle_import`——消息带图片段先走 `_import_image`（图片优先，随附文字按学期先验喂识别、不双路重复记），纯文本走 `_import_text`，逐行 `_parse_import_line` 解析（只收显式时刻行，不猜节次；每批行数上限以本件 `_MAX_IMPORT_LINES` 常量为准）。
- 识图腿：`domains/schedule/timetable.py::recognize_timetable` 把截图解析成 `TimetableDraft`，其 `missing_clarifications()` 把待澄清事项先摆出来、不代填；`build_timetable_provider` 惰性 import 并**只读消费** `domains.media.ingest.vision_describe.build_vision_provider`，不养第二份识图真身。
- 落表腿：文本与图片两路都汇到 `_commit_entries` → `_add_entry`，组装意图后仍经 `ScheduleService.submit_plan` + `expand_occurrences` 提交（乐观 revision、幂等物化归引擎），本入口不开第二条写口。

## 开关与参数

- `bot_schedule_enabled`（缺省 False，`.env` 名 `BOT_SCHEDULE_ENABLED`）：导入面的前置闸，关时「课表」二字就是普通聊天。本族基础键走 `.env`，未开 `/bot runtime set` 热改面（口径见 `config.py` 注释）。
- 识图可用与否以 `BOT_VISION_ENABLED` 与识图 registry `bot_vision_model_registry` 为准（registry 空或关时 provider 为 None → 诚实回「没读成」，绝不编课程）；在册未接线的 `bot_schedule_timetable_enabled` **不是**本面读点。
- 学期锚词面、行格式与单双周标记以本件常量 `_SEMESTER_RE`、`_IMPORT_LINE_RE` 为准；地点进 `loc:` 标签不进标题。

## 失败时看到什么

- 一行都没读实：「这份里我一行都没能读实……给我文本版就好——我不猜节次表」，随附如实点名没读实的行数。
- 单双周缺学期锚：「学期第一天我猜不了——首行加一句『学期 …』再导入一次」，本批不落。
- 识图后端不可用：「这张图这会儿没读成——识图后端没接稳，把课表文字发我也行」；图里认不出课程：「这张图里我没认出课程……」；有待澄清事项：回前两条澄清问句，不代猜。
- 存储没就绪：「这会儿日程表没接上（存储未就绪），稍后再发一次」。
- 与板完全重复：「这份和板上已有的完全重复，没有新增」；批内个别行落不上计入「N 条没落上」回话，不整批回滚。

## 测试与验收

`tests/test_schedule_board.py`：`test_import_text_lines_and_dedupe`（文本行解析与去重）、`test_import_requires_semester_for_parity_lines`（单双周必回问）、`test_import_image_clarify_path_no_guess`（图片待澄清不代填）、`test_import_image_commits_private`（图片批按隐私落库）、`test_board_reuses_engine_tables_only` 与 `test_recurring_teaching_week_stored_in_engine`（教学周规则落引擎表）。重发不双记另有 `tests/test_schedule_board_privacy_sched20.py` G3 锁。逐命令口径见 `docs/command-catalog.md`【日程】节；真机验收暂无本入口专属编号（挂账见 schedule-board README「现行缺陷」）。
