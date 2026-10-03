# 文件网关与受控下载 · 入站文件上下文回填注记

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B08.file-gateway · 入站文件上下文回填注记

- 层级：一级 B08 → 二级 file-gateway → 三级 `incoming-file-context`
- 实现落点：`plugins/bot_unified_runtime/domains/files`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

落盘文件的**内容理解**供件（文件链路波 · 需求 16，2026-10-03）：notice 腿把管理员发来的文件存进 `incoming/` 后，把「文件名 / 类型 / 可读性 / 限长正文」打成一条带 T2 标注的上下文注记，与语法调试报告并列随统一管线回给用户——bot 不再只会说「收到了文件」，而是真的读过、读不动时诚实说没读到。判据三条不变量：读取只走 `read_supported_file`（内容问题诚实降级、绝不抛）；T2 打标只走 `labelled_text` 咽喉（文件正文恒 T2，超管上传也不升档）；读不动时的措辞只交 `file_read_failure_note` 唯一真身（不复制、不并态）——「没读」绝不写成「没有」。

与摄取腿的分工：普通消息里的文件段在入站摄取时有另一条回填（`_incoming_from_nonebot_event` 的 `file_context` 注入，受 `bot.ingress.file_read` 特性门管）；本入口只管 **notice 腿**（管理员私聊文件接收）落盘件的理解注记，两者共用同一批 file_reader 真身、不建第二套读数点。

## 怎么调用

真身 `domains/files/sources/file_reader.py::build_incoming_file_context_note(path, *, original_name="", max_chars=CONTEXT_NOTE_DEFAULT_MAX_CHARS) -> str`。接线点在根 `__init__.py` 的 `file_notice` 处理器（B08.file-gateway 的被动面之一）：平台取文件落盘成功后，线程池里调本口，注记拼在 `[文件调试] …` 报告之后一并交 `_send_text_through_unified_pipeline`。`original_name` 传**给人看的原始文件名**（落盘件名是 `<时间戳>_原名` 形态，不该出现在注记里）；正文收录缺省预算 `CONTEXT_NOTE_DEFAULT_MAX_CHARS`（注记进的是对话上下文，逐轮占窗，刻意远小于全文读取口的 120000；要放宽显式传参）。

## 开关与参数

无独立配置键：notice 腿回填随 `file_notice` 处理器常开，预算是调用参数缺省（逐值以 `file_reader.py` 该常量声明为真身）。类型标签表 `_FILE_KIND_LABELS`（文本/代码/文档/PDF/表格/演示）与 kind 同住一处，表外 kind 原样上注记、不编类型名。

## 失败时看到什么

整体 fail-honest：任何意外（含路径读不到、解析器缺依赖）折成一句「这次没能生成入站文件的上下文注记（程序侧异常，不是文件损坏，内容没有读）」并记 WARNING，绝不打断入站链路、绝不假装读过。空正文但读取成功（空文件/非文字形态）出一句可核对的事实，不猜内容。

## 测试与验收

`tests/test_incoming_file_context_note.py`（注记形态、T2 打标、失败措辞真身逐字、预算截断）。真机：管理员私聊发一个文本文件，收到的调试回报里应带「[入站文件：…]」注记段；发一个读不动的二进制，注记应诚实说明没有读出内容。
