# 人格对话与回复 · 失败与降级话术池

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.chat-reply · 失败与降级话术池

- 层级：一级 B03 → 二级 chat-reply → 三级 `failure-copy-pools`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py`、`plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

失败面不是一句「出错了」，而是**几套各有语义的话术池**，按「谁的失败、在哪个场景」
选用，并且同一会话内轮换、不连发重复。它保证三件事：用户永远知道发生了什么、
她始终是她（不机器腔、不甩锅）、错误细节只进日志与诊断卡不进聊天正文。
生效条件：任何一条回复路径产不出正常正文（模型链失败、装配缺件、门拒绝、能力异常）。

## 怎么调用

现役池与出口（调用方只准取这些函数或常量，禁止在能力文件里自拼失败句）：

- `capabilities/chat.py:persona_failure_message(session_id)` ——私聊人格生成失败池
  （常量 `_PERSONA_FAILURE_MESSAGES`）。带 `session_id` 时纯按会话游标
  `(offset) % n` 顺序轮换，游标表有容量上限；不带会话（无游标可跟踪）才退回随机。
- `capabilities/chat.py:injection_guard_message(session_id)` ——疑似提示注入的温和拒答池，
  同款游标轮换；措辞不点名用户「你在注入」。
- `capabilities/user_copy.py:ADMIN_GATE_TEMPLATES`（模板 `ADMIN_GATE_REQUIRED`）——
  管理员门拒绝池，调用点 `random.choice(...).format(action=...)`，动词由能力自己给。
- `capabilities/user_copy.py:DATASOURCE_FAILURE_TEMPLATES`（模板 `DATASOURCE_TEMP_FAILURE`）
  ——外部数据源临时失败池，`reason` 传「X 暂时拉不到」式短语。
- `capabilities/user_copy.py:GROUP_FAILURE_ACK_TEMPLATES` ——群聊能力执行失败的
  会话级降级短句，由 `runtime/pipeline.py`（审查 A-19 锚点）统一投放，
  **本域不自拼**（R-16②）。
- 内部异常走统一错误诊断卡 `domains/ops/monitor/error_report.py`（两段式：文本回执先行、
  卡图稍后补发；冷却闸内降级为一句纯文本），归 B09 叙述，本板块只保证兜底文案。
- 池内轮换的通用实现是 `domains/assistant/daily/store/daily_assist.py:pick_variant`
  （跨域复用的那一份）；`chat.py` 内的「危险/安抚」示例句走它，不再造第二套轮换。
- 模型侧错误分类到「人话」的映射在 `chat.py:_operational_issue` +
  `llm_engine/providers.py:public_llm_error_message`，本池只取结果句、不重复分类。

## 开关与参数

- 话术池本身是**代码内常量**，不是配置：没有「改文案=改 .env」这条路，也不该有。
  改文案 = 改代码 + 重启（铁律），并必须过文案红线门。
- 群聊降级短句的投放受管线节流表与会话级窗口控制；限流拦截、安静时间拦截、
  `pipeline_busy` 超载快败**故意静默**，不入池（这是 2026-09-12 实弹裁定的语义分界，
  别把它们「修」成有反馈）。
- 错误卡的开关是 `bot_error_card_enabled`（缺省 True）与其冷却闸，详见 B09。
- 私聊失败是否重试到可见，取决于 B02 的 `bot_chat_failover_max_seconds` 与链级
  fail-fast 参数；池只负责「最终失败时说哪句」。

## 失败时看到什么

本节即失败面本体，按场景对照：

| 场景 | 用户看到 | 细节去哪 |
|---|---|---|
| 私聊模型链全红 | 人格失败池一句（同会话不重复） | 日志 + 告警（带 kind/chain/last 轨迹） |
| 群里能力失败 | A-19 降级池一句温和短句 | 正文压空 + SILENT_AUDIT，错误细节不进群 |
| 疑似注入他人指令 | 反注入温和拒答池一句 | 审计标签 + 日志 |
| 需要管理员权限 | 「要 X，找管理员来操作。」池内变体 | 审计 |
| 外部源拉不到 | 「X 暂时拉不到，稍后再试。」池内变体 | 重试与退避日志 |
| 内部异常 | 文本回执先行 + 稍后补诊断卡 | 全栈脱敏进卡与运行日志 |
| 无池可取（极端） | `_GENERIC_OPERATIONAL_MESSAGE` 运维句 | 日志 |

## 测试与验收

`tests/test_persona_failure_messages.py`（池轮换：连发不重复、无会话退回随机、
池外禁句不出现在正文）、`tests/test_user_copy_unification_gate`（回潮拦截：
能力文件自拼失败句会红）、`tests/test_bgroup_chat_pipeline.py`（A-19 群聊降级 + 节流）、
`tests/test_content_safety_v*.py` 中拒答句形态断言（反注入/守界温和句）。
真机：把模型链全断（停网关）后私聊与群聊各发一条，肉眼核对两池文案不同源、
且正文里不出现异常类型名与本地路径。
