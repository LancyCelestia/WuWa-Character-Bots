# 笔记与授时 · 自然语言完成勾选

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.notes · 自然语言完成勾选

- 层级：一级 B04 → 二级 notes → 三级 `mark-done`
- 实现落点：`plugins/bot_unified_runtime/domains/notes/capabilities/notes.py`、`plugins/bot_unified_runtime/domains/notes/store`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

笔记待办的勾选与撤销。显式编号形态「做完 N」（另有「完成/办完」词形）勾掉该篇**第一个未勾条目**——勾选粒度是条目而非整篇（审查 A-06）；要点名具体事项，说「〈事项〉做完了」走自然语言勾选，由提醒能力统一消歧（未完成提醒 + 笔记待办一起进候选池，多命中列编号候选问人，唯一候选但相似度不足先追问「是这件吗」）。撤销侧（审查 A-14）：「取消勾选 X」「X 还没做/没做完」在已勾条目里模糊匹配回写 `[ ]`。

## 怎么调用

- 编号勾选与撤销：`domains/notes/capabilities/notes.py` 的 `_NOTES_DONE_RE` 分支与 `_extract_undo_query` → `_handle_undo`；存储改写走 `domains/notes/store/notes_store.py::NotesStore.mark_item_done` / `mark_item_undone`（条目级），兼容路径 `mark_done`（整篇）。
- 自然语言勾选：`domains/schedule/capabilities/reminder.py::extract_checkoff_query`（短句门槛、疑问句不收）与 `_handle_checkoff`——候选名对笔记待办取**逐条未勾条目行**（`Note.todo_match_texts`）而非标题行，否则「买牛奶」永远勾不掉「采购清单」里那一行；匹配判定走 `resolve_todo_match`（hit / uncertain / 歧义多候选）。
- 追问回收：光杆肯定词或序号由 `_consume_checkoff_followup` 按会话内进程态消化（`_PendingOption` 固化 id，回收时**按 id 重新定位**再勾，绝不凭旧下标盲勾）；撤销面「无候选让位」与勾选面同一口径。

## 开关与参数

- 与笔记共用 `bot_notes_enabled`：关闭时自然语言勾选的候选池不含笔记待办（`reminder.py::_handle_checkoff` / `_locate_and_mark` 两处 `getattr` 门实核），只剩提醒候选。
- 词形门槛为模块常量非配置键：`_CHECKOFF_MAX_CHARS` / `_CHECKOFF_QUERY_MAX_CHARS`（勾选面）、`_NOTES_UNDO_MAX_CHARS` / `_NOTES_UNDO_QUERY_MAX_CHARS`（撤销面）；追问态 TTL 与容量上限见 `reminder.py` 模块常量。刻意不收「取消笔记/删笔记/取消提醒」词形——删除是另一个决定，与撤销零抢路由。

## 失败时看到什么

编号无此笔记→未命中回话；指向普通笔记（非待办）→「它不是待办」温和说明；已勾过→「已经完成过了。安心。」；勾掉最后一件→整篇完成文案，否则报「这篇还剩 N 件」。并发窗口内笔记被删/改写→按未命中回话不编造。自然勾选无任何候选→整句让位给普通流程（不抢话）；追问过期→提示重新说一遍；候选已从清单消失→gone 兜底文案。

## 测试与验收

`tests/test_notes_item_checkoff.py`（条目勾选/撤销/歧义矩阵）、`tests/test_notes.py`（显式编号链）。提醒侧勾选与追问回收的用例在 schedule 域测试件（见 B07）。真机验收编号：未确认——需对照 `docs/acceptance-manual.md` 现文。
