# 安全与凭据护栏 · 出站危险命令审查

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.security-guardrails · 出站危险命令审查

- 层级：一级 B10 → 二级 security-guardrails → 三级 `outbound-command-screen`
- 实现落点：`plugins/bot_unified_runtime/domains/core/credentials`、`plugins/bot_unified_runtime/domains/chat_reply/security/__init__.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/dangerous_command.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/injection.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/display_guard.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/spoof_audit.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/database_broker.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

补「bot 教用户执行破坏性命令」这条此前没人管的出站形态：注入内容或模型幻觉完全可以让回复以守岸人口吻递出一行 `rm -rf /`。对**即将出站**的纯文本做窄形态匹配（unix `rm` 递归+强制旗标∧危险目标、Windows `rd/del/erase`、PowerShell `Remove-Item`、`format` 盘符、`mkfs`、`dd` 直写块设备、`reg delete` 机器蜂巢带 `/f`、`shutdown` 执行旗标、fork bomb、`diskpart clean`——族清单以真身函数体在册族名为准），命中即把正文**整体换成固定人话警告**（不含可复制命令原文）并落审计。窄尺双条件（递归+强制 ∧ 危险目标）保住日常教学/财经内容零误伤。

## 怎么调用

两层分工（裁定见两真身 docstring，非第二真身）：

- **chat 层裁决＋审计（主）**：`domains/chat_reply/security/dangerous_command.py::screen_dangerous_command_output(text) -> DangerousCommandVerdict(hit, families, replacement)`。挂点在 `chat.py` 出站审查（`_unsafe_output_reasons` 一带）：`verdict.hit` 为真时把 `reply.text` 换成 `verdict.replacement`，审计标签 `dangerous_command_output` 与逐族 `dangerous_command_output:<family>`；与既有 `artifact_review_blocked` 语义**并列不互斥**——两腿都基于替换前原文现算，本腿 hit 只换文不阻断、artifact 腿照旧全拦（双命中时全拦且 families 证据仍在审计）。
- **渲染层出站咽喉的行内兜底**：`domains/render/plain_text.py::redact_destructive_commands`，经 `renderer.py` 咽喉链（`redact_local_secrets(redact_destructive_commands(...))`）行内打码、**围栏代码块（教学语境）豁免**，罩 chat 之外的其余能力出站与 chat 漏网面；与密钥打码同层不互踩（双向链式幂等）。

## 开关与参数

**无配置键**：主腿纯函数、零 IO、零配置读、零网络，命中即换、没有「关闭审查」的开关；兜底腿随渲染咽喉常驻。改动一律走代码（重启生效）。替换话术唯一真身＝`REPLACEMENT_TEXT` 常量，禁在调用点拼接命中片段。

## 失败时看到什么

审查器对任何输入（含空串/非字符串退化形态）**都不抛**——非字符串一律按无命中放行，审查器自身故障绝不把出站链路打挂（与 fail-open 同一哲学：安全话术宁可缺席，不可阻断主链路）。命中时用户看到固定模板话术（「这句回复我拦下来了：里面混着会抹盘、清系统或者动引导级设置的破坏性命令……」），不回显命中原文、不携带命令形态——「关于危险命令的报告」本身不得成为新载体。排障按审计标签 `dangerous_command_output:<family>` 反查命中族。

## 测试与验收

`tests/test_dangerous_command_output_gate.py`（判据三维：逐族命中正样必命中、日常教学/财经窄尺反例必放行、注毒自证）、`tests/test_dangerous_command_outbound_wiring.py`（chat 层接线锁：hit 换文＋审计标签＋两腿并列语义）、`tests/test_destructive_command_redaction.py`（渲染层打码腿：围栏豁免、与密钥打码链式幂等）。真机验收无独立条目：属安全面观察——诱导性问句不应得到可复制的破坏性命令行，命中轮在审计里留族标签。
