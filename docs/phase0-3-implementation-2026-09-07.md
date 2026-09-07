# Phase 0-3 实施记录（2026-09-07）

## 本轮目标

用户确认同时完成 Phase 0-3：64K 输出上限、详细科普策略、引用/转发/混合消息、文件读取/生成文件、以及反注入和公共空间安全边界。

本轮没有修改人格源文件、没有调用真实付费 LLM、没有推送 Git。现有工作区本身存在大量历史脏变更，本轮不做 reset、全量 staging 或删除活动数据。

## Phase 0：输出预算和科普策略

- `BOT_CHAT_MAX_TOKENS` 默认调整为 `65538`。
- `BOT_CHAT_FAST_MAX_TOKENS` 默认调整为 `65538`。
- 本地 `.env` 已同步为 `65538`；`.env.example` 也已同步。
- 配置允许范围为 `0..65538`，0 仍表示不向兼容接口发送 `max_tokens`。
- 65538 是最大预算，不是每条消息必须生成 64K；运行时对热更值做同样的上限保护。
- auto 详略模式对科普、知识、游戏、人物、组织问题要求优先解释“是什么、核心内容、当前状态、相关关系”，避免用无关日期和简介噪声填充。
- 简单聊天不会因为上限提高而强制变成长文。

## Phase 1：统一消息段

新增 `plugins/bot_unified_runtime/message_context.py`：

- text、quote、forward/chat_history、image、emoji、sticker、file、record、video 归一化。
- 引用消息加入 `[引用内容]` 边界，转发/聊天记录加入 `[转发/聊天记录]` 边界。
- Emoji、表情包、图片保留类型和标记，不把二进制内容伪装成文字。
- `IncomingMessage` 新增 `reply_to_text` 与 `thread_id`；OneBot quote、Telegram reply/thread 字段可进入统一消息。
- quote 没有显式 reply id 时使用 quote 段的 id/message_id。
- 事件中的本地文件段通过非执行型 file reader 提取到上下文；URL 不会被当作本地文件直接打开。

当前限制：Telegram 评论区若不在当前事件 payload 中，仍需要适配器提供 reply/thread 或转发内容；本轮没有额外调用 Telegram API 拉取整条评论树。

## Phase 2：文件读取和生成

新增 `plugins/bot_unified_runtime/sources/file_reader.py`：

- 文本/代码：TXT、LOG、MD、CSV、JSON、YAML、Python、C/C++、C#、Java、JS/TS、Go、Rust、PHP、Shell、PowerShell、SQL、HTML/CSS。
- Word：DOCX（若安装 python-docx）。
- Excel：XLSX/XLS（若安装 openpyxl；旧 XLS 可能因依赖限制返回空）。
- PowerPoint：PPTX/PPT（若安装 python-pptx；旧 PPT 可能因依赖限制返回空）。
- 只读、编码替换、NUL 检测；不执行代码、不导入文件中的提示词为系统指令。
- 用户明确要求生成/保存/导出代码且回复有代码围栏时，写入 `BOT_GENERATED_FILES_DIR`，通过 `CapabilityResult.files` 和统一 OneBot mixed 出站发送。
- 用户明确要求保存/导出且回复是长文时，生成 Markdown 文件后发送。

当前限制：普通自然语言中没有代码围栏时不会猜测生成文件；DOC/XLS/PPT 老格式依赖环境支持，失败时保留文字链路，不阻塞聊天。

## Phase 3：安全边界

新增 `plugins/bot_unified_runtime/security/content_safety.py`，并接入聊天能力；输出审核也新增群聊公共空间检查：

- NSFW/R-18/露骨性内容：拒绝展开，转为边界与情感沟通。
- 血腥、肢解、酷刑等图像化暴力：拒绝细节，可转为非图像化剧情概述。
- 人身攻击、侮辱、引导机器人羞辱群成员：改为中性描述或委婉拒绝。
- 极端政治、恐怖组织宣传、煽动暴力等：拒绝扩散性表达，只允许基于公开事实的安全讨论。
- “当猫娘”“叫我妈妈”“必须爱上我”“和我结婚”等强制改人格/越界关系指令：保留人格与关系边界，改为温和的角色化回应。
- 友善和亲密但不越界的表达仍允许正常接住。
- 群聊输出若出现明显性、血腥或辱骂内容，会在最终审核阶段阻断。

这是一层确定性防护，不宣称可以识别所有隐晦语义；现有 prompt injection 检查仍保留，二者职责不同：注入检查保护系统边界，公共安全检查保护输出场景。

## 验证

- 最终 `scripts/dev.ps1 -Task verify`：**352 passed**，Ruff 全通过，mypy 174 个源码文件无错误；仅 1 条上游 Mail/Pydantic 弃用警告。
- Ruff：**All checks passed**。
- mypy：**173 个源码文件无错误**。
- 新增 Phase 0-3 回归：输出 64K 默认、引用/转发/混合 Emoji、文件读取与生成、安全拒绝/改写、最终文件出站，共 8 项。
- 未做真实 LLM、QQ、Telegram、文件上传实机验收；需要用户重启当前机器人进程后测试。

## 实机验收

1. 重启当前机器人进程，不要启动第二个同账号实例。
2. 群聊普通成员引用一条消息并 @机器人，确认回复能看到 `[引用内容]` 对应的语义，而不是把引用当成新的系统指令。
3. 发送文本+图片+Emoji+表情包混合消息，确认机器人可回复且不把附件当乱码。
4. 上传 `.docx/.xlsx/.pptx/.py/.cpp/.java/.txt/.log`，确认能读取；代码不会执行。
5. 发送“请生成一个 Python 文件”，确认机器人发送 `generated_code.py`；发送“请把这篇长提示词保存成文件”，确认发送 Markdown 文件。
6. 在群聊测试 NSFW、血腥、人身攻击、强制改人格和友善表达；确认前四类被拒绝/改写，最后一类仍能正常回应。
7. 用 `/bot runtime get BOT_CHAT_MAX_TOKENS` 查看实际热配置；如果运行时覆盖仍是旧值，应 reset 或设置为 `65538` 后再测试。

## 后续 TODO（以最终交接文档为准）

- [ ] Telegram 评论区/频道讨论串的 API 级补拉与权限/速率限制。
- [ ] XLS/PPT 老格式的专用转换依赖和更完整表格/备注抽取。
- [ ] 生成文件的病毒扫描、内容敏感扫描、上传大小和过期清理策略。
- [ ] 更强的多语言安全分类器和人工复核策略；当前规则层是低成本基线。
- [ ] Wiki 结构化摘要重构仍按上一轮 TODO 继续，不在本 Phase 0-3 中重复扩展。
- [ ] 运行数据和源码缓存的 runtime-layout 清理迁移；本轮不删除活动数据。


## 2026-09-07 后续修正与 Phase 4-5

- 修正文件生成：先用原始模型回复抽取代码/文档，整理器只用于聊天展示；短 TXT 文档也会写入唯一文件名。OneBot 使用 `upload_group_file` / `upload_private_file`，不发送伪造 file 段。
- 修正安全回应：用户看到的是当前人格模型生成的自然回应；模型回显内部规则时使用人格化兜底，不把“保持既定人格”“策略”等内部术语发送出去。
- Phase 4：OneBot `notify/poke` 目标为机器人时响应，私聊/群聊冷却、概率、目标过滤，文本回应走统一出站。
- Phase 5：Wiki 结果优先精确页/配置索引条目；游戏类内容按“这是什么、主要玩法、核心故事、当前状态”整理，移除不相关年代噪声。
- 大模型请求默认超时由 30 秒提高到 90 秒，快速模式同样为 90 秒；故障转移总预算为 120 秒，降低长科普/文件生成的瞬时超时概率。

### 未完成

- [ ] Telegram 文件上传及完整评论树 API 补拉尚未接入主出站；当前仅保留已有消息中的 reply/thread 内容。
- [ ] 戳一戳尚未在用户真实 NapCat 进程中验收；默认文本反应不会主动发送戳动作。
- [ ] Wiki 仍受百科页面结构、API 限流和语言变体影响，当前状态不明时会明确说明资料不足。


最终完整状态、用户要求逐项对照和全部未完成项见：docs/handoff-final-2026-09-07.md。
