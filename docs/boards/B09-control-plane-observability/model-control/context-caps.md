# 模型路由与账本 · 上下文与输出钳制

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.model-control · 上下文与输出钳制

- 层级：一级 B09 → 二级 model-control → 三级 `context-caps`
- 实现落点：`plugins/bot_unified_runtime/llm`、`plugins/bot_unified_runtime/domains/chat_reply/llm_engine`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

给每次模型调用上一道「上下文总量」的天花板：请求发出前把输入消息按估算 token 裁剪、把显式设置过大的输出 `max_tokens` 压回上限。目的是防止长会话或长上下文请求打爆上游、放大成本与延迟。它不改写内容语义，只做「超了就削、没超原样」。

## 怎么调用

单一入口 `domains/chat_reply/llm_engine/model_router.py::_enforce_context_caps(messages, options, max_input_tokens, max_output_tokens)`，由 `build_model_router` 装配进 `ModelRouter`，在串行与影子两条出数路径上都会经过（同语义）。粗估走 `model_router.py::_estimate_messages_tokens`：CJK 约每字 1 token、ASCII 约每 4 字符 1 token、每条另加固定开销。

- 输出侧：`options["max_tokens"]` 只封顶不托底——未设置或 0 保持「模型自行决定」的既有契约，仅当调用方显式设置且超过上限时压到上限。
- 输入侧：估算超过 `max_input_tokens` 时，从最旧的非 `system` 消息开始逐条丢弃，直到不超限或只剩一条；`system` 永不被裁。

## 开关与参数

- `config.py::Config.bot_chat_max_input_tokens`（缺省 131072）、`Config.bot_chat_max_output_tokens`（缺省 65536）。装配时通过 `getattr(config, …, DEFAULT_MAX_INPUT_TOKENS)` 读取，缺字段回落到模块常量 `model_router.py::DEFAULT_MAX_INPUT_TOKENS` / `DEFAULT_MAX_OUTPUT_TOKENS`。
- 改动这两个键要重启生效（装配期快照，非热改面）。谁可改：`.env`/Config，属管理员配置面。

## 失败时看到什么

不是错误路径、无用户可见文案：正常范围内逐字节不变。超限时表现为「旧的非 system 上下文被裁掉」或「`max_tokens` 被压小」，回复本身仍正常返回。裁剪依赖粗估器，对中英混排/结构化 JSON 的估算有误差，属预期边界——它保证的是「不超过天花板」，不是「裁到刚好」。

## 测试与验收

`tests/test_model_context_caps.py`（估算器 CJK/ASCII 口径、输出只封顶不托底三态、输入超限从最旧非 system 丢起）。真机（重启后）：构造一段远超上限的长历史，确认请求仍可出回复且上游不因超长报错；账单/日志不出现超长被拒。
