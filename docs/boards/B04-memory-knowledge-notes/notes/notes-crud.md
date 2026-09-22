# 笔记与授时 · 记/看/放下/列表

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.notes · 记/看/放下/列表

- 层级：一级 B04 → 二级 notes → 三级 `notes-crud`
- 实现落点：`plugins/bot_unified_runtime/domains/notes/capabilities/notes.py`、`plugins/bot_unified_runtime/domains/notes/store`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

会话内的 Markdown 笔记 CRUD：「笔记 记 内容」新增（可附图，图字节落盘、`content_md` 里以 `![图片N](文件名)` 行引用）、「笔记列表」清单、「笔记 看 N」回看（纯文本化展示并补发配图）、「删笔记 N」删除（图片文件随行清理）。内容含 `- [ ]` 勾选框即自动判为待办（kind=todo）。触发词全部收在 REMINDER 路由的 `is_reminder_command` 判定里，不新增 RouteKind——笔记词形已并入 route-matrix 的 reminder 行。生效条件：`bot_notes_enabled`。

## 怎么调用

- 能力构造与判据：`domains/notes/capabilities/notes.py::build_notes_capability`、`is_notes_command`（这组触发正则被 `domains/schedule/capabilities/reminder.py` 跨文件显式引用，是登记在册的接线形态）。
- 存储：`domains/notes/store/notes_store.py::build_notes_store(config)` → `NotesStore`（`add` / `get` / `list_notes` / `count_chat` / `delete`），SQLite 经 runtime_paths 解析，读写都以 `chat_id`（即 `message.session_id`）为会话隔离边界。
- 展示与图片：`note_display_text`（去勾选框与图片行的纯文本形）、`note_image_files`（回看时按引用行找回图文件）；图片段提取 `_extract_image_segments`、落盘 `_save_note_images`、随删清理 `_cleanup_images`。
- 出站走统一产出链（review → renderer → send_queue），本件只产 `CapabilityResult`。

## 开关与参数

- `bot_notes_enabled`（缺省 True）、`bot_notes_db_path`（缺省 `data/notes.sqlite3`，进 `path_fields` 重映射到 Runtime 数据根）、`bot_notes_max_per_chat`（缺省 200，会话级容量）。逐键现值以 `docs/config-catalog-full.md` 与 `config.py` 为准。
- 能力层每次经 `build_notes_store(config)` 现取现读；上限在 capability 内 `getattr(config, "bot_notes_max_per_chat", …)` 逐条消息读取。
- 新增分支把内容截到 4000 字再入库（`capability` 内 `content_md[:4000]`，本会话见 `domains/notes/capabilities/notes.py`）。

## 失败时看到什么

编号不存在→「这个会话里没有第 N 条笔记」类回话（view/delete/done 三处各自文案，均引导「笔记列表」对号）；容量满→「已经收满 … 条了，先整理一下」；裸「笔记」与无法识别形态→统一用法提示 `_USAGE_TEXT`；勾选/删除的并发窗口（预检后条目被他人改动）按未命中回话，绝不编造成功。全部是守岸人文本回复，无静默路径。

## 测试与验收

`tests/test_notes.py`（CRUD、触发形态、图片链）、`tests/test_notes_item_checkoff.py`（条目粒度勾选，见 mark-done 页）。真机验收编号：未确认——需对照 `docs/acceptance-manual.md` 笔记相关小节现文。
