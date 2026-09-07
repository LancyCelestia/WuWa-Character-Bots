# ChatBot 项目缺失与欠缺分析计划

## 目标
系统扫描当前源码工作区内的代码、README/Markdown、配置文件和前后端目录，严格依据用户给定的预期平台、核心功能与 Web UI 清单，产出带有具体文件路径证据的 Markdown 差距分析报告。

## 阶段
- [complete] 阶段1：根目录、配置与仓库状态探索
- [complete] 阶段2：README/Markdown 文档审查
- [complete] 阶段3：目录树与模块映射
- [complete] 阶段4：核心 Python/NoneBot/API/数据库代码走查
- [complete] 阶段5：Web UI 前后端代码审查
- [complete] 阶段6：预期清单交叉比对、质量风险归纳与报告撰写
- [complete] 阶段7：验证报告证据、保留审查过程文件`n- [complete] 阶段8：补充后端控制面需求规格与用户确认决策

## 最终结论
当前项目是“后端统一运行时 + NoneBot 适配器 + 多平台链接解析/部分订阅”的 alpha 版本，不是已经具备目标 Web UI 和完整平台生态的全量版本。报告必须明确区分：适配器接入、链接解析、搜索、订阅抓取、消息推送、Web UI 这五种不同完成度。

## 约束
- 只扫描当前工作区 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`；不递归扫描 Runtime、Archive 或上级目录。
- 不臆测不存在的实现；只依据代码/文档/配置的可定位证据判断。
- 外部网页内容只作为 NoneBot 背景参考，不替代本地代码证据。
- 不修改业务源码；规划文件为本次审查过程文件。

## 交付结构
1. 项目探索摘要
2. 生态与平台接入差距分析
3. 核心功能差距分析
4. Web UI 系统差距分析
5. 架构与代码质量欠缺分析
6. 改进与优先级建议

## 2026-09-05 后端核心切片

- [in_progress] 根据 `docs/superpowers/plans/2026-09-05-backend-core-slice-zh.md` 实现单轮后端执行单元。
- [pending] 完成全量验证、仅暂存本轮文件并尝试 Git 远端推送。

## 2026-09-06 搜索 API 与 PowerShell 兼容

- [complete] 修复 `scripts/dev.ps1` 在 Windows PowerShell 5.1 下的解析错误与中文输出编码。
- [complete] 实现 Tavily -> You.com -> LangSearch 搜索 API 链式适配，TinyFish 可选正文抓取，未配置 key 时安全跳过。
- [complete] 通过搜索 provider 协议测试、核心后端 smoke、NoneBot startup smoke、人格与上下文 smoke。
- [pending] 将当前搜索适配从共享脏工作树中隔离为下一笔本地 alpha-test Git 备份；不得混入用户既有修改。
- [pending] 单独设计并实施人格系统提示词、世界观实体知识、来源政策和现实知识引用合同。

## 2026-09-06 真实聊天后端优先

- [in_progress] 验证真实 LLM provider 与 RuntimePipeline 聊天链路。
- [pending] 修复真实聊天链路阻塞点并保留可回归 smoke。
- [pending] 将人格 Prompt 重构列为后续任务，不在本阶段改动人格源文件。

## 2026-09-06 真实聊天后端优先 - 结果

- [complete] 真实 LLM provider 配置体检通过。
- [complete] `chat-smoke` 真实 provider 返回 `llm_status=ok`、`receipt_state=sent`、`llm_finish_reason=stop`。
- [complete] 控制台真实聊天返回实际模型回复。
- [pending] 人格 Prompt 重构、上下文编译器和 approved digest 闸门后置；未修改人格源文件。

## 2026-09-06 真实运行底座与消息闭环

- [in_progress] 写入完整底座状态与未完成清单 `docs/backend-base-status-2026-09-06.md`。
- [pending] 新增 `backend-base-smoke`，聚合 NoneBot/plugin/startup/backend/transport 离线底座检查。
- [pending] 实机 NapCat/OneBot 连接、真实 QQ 收发和统一出站网关仍待验证/实现。
- [pending] 人格 Prompt 重构、ContextCompiler、WorldModel、Memory Gate、ToolCatalog 后置。

## 2026-09-06 真实运行底座与消息闭环 - 结果

- [complete] 完成底座链路审计并写入 `docs/backend-base-status-2026-09-06.md`。
- [complete] 新增并验证 `backend-base-smoke`：NoneBot/plugin、startup、OneBot fake transport、backend pipeline 均通过。
- [pending] NapCat 实机连接、真实 QQ 收发、边缘能力统一出站仍待实机环境验证和后续改造。

## 2026-09-06 统一消息网关增量结果

- [complete] 主能力路径接入 `IngressGateway` 和 `UnifiedDeliveryGateway`。
- [complete] `backend-base-smoke` 通过；真实 `chat-smoke` 复测通过。
- [pending] 文件接收/文档导出/订阅等边缘能力仍有直接 `bot.send()`/`bot.call_api()`，下一阶段迁移到统一出站。
- [pending] NapCat 实机连接和真实 QQ 收发必须在用户启动 NapCat/测试账号后验收。

## 2026-09-06 图片/表情消息无回复修复

- [complete] 定位 image 事件被监听 matcher 消费但未进入聊天能力的路由缺口。
- [complete] 接入 image/face/mface/marketface/sticker 到 chat matcher，并为空文本提供视觉占位消息。
- [complete] 通过事件适配、视觉能力、统一网关和 startup/transport 回归。
- [pending] 用户需要在真实 QQ 上重新发送图片和表情包，验证当前视觉 provider、图片 URL 获取和 OneBot 回传。

## 2026-09-06 详细回答、统一模型优先级与 Memory Router

- [in_progress] 让知识/人物/组织/关系问题默认采用详细回答策略，临时关闭 fast mode 并提升输出上限；不修改人格源文件。
- [pending] 实现模型与视觉模型唯一 priority 槽位算法，修复命令、显示和路由顺序。
- [pending] 让 memory extraction 复用主聊天 ModelRouter，修复 401 和异常堆栈噪声。
- [pending] 完善 help 与参数设置说明，并运行针对性回归。

## 2026-09-06 本轮收尾（以前述旧状态之后的本节为准）
- [complete] 记忆抽取复用聊天路由；备用凭据、独立预算、并发限制与冷却回归通过。
- [complete] 详细回答配置传递、搜索证据传入、唯一 priority 槽位及帮助说明回归通过。
- [complete] 本地完整测试 309 passed；用户此前已确认文本与图片实机回复。
- [pending] 真实抽取凭据/数据库及回答质量重启验收；视觉命令全量对齐、Mail 实机诊断仍未完成。
- [pending] 全仓 lint 6 项和 runtime-layout 运行产物/156 个缓存路径问题。
- [pending] 完整待办和操作边界见 docs/chat-memory-routing-fixes-2026-09-06.md；不推送 Git，不改人格源文件。

## 2026-09-06 群聊与来源质量补丁
- [complete] 群聊整包引号清理、维基精确标题优先、梗结果相关性/去重、无效 Cookie 安全降级。
- [complete] backend-smoke 输出明确为离线 static provider；lint 修复并通过。
- [pending] 真实群聊普通成员、Wikipedia/梗网络源、视频 Cookie 和 NapCat 仍需用户实机复验。

## 2026-09-06 22:40 实测问题续修
- [in_progress] 按句引号（保留内引用）、角色列表片段检索、小红书 discovery 路由、Cookie 内存规范化与日志降频。
- [in_progress] doctor 当前解释器 CLI 定位及 verify 24 项类型问题。
- [pending] 一次完整 verify、doctor 和 Markdown 交接；不推送、不修改原 Cookie/人设、不做付费模型调用。

## 2026-09-06 22:40 续修交接
- 按句引号、Wiki 列表条目、小红书 discovery 路由、Cookie 内存规范化与降噪、doctor 解释器路径、mypy 类型问题已处理。
- 四个用户 Wiki 查询已通过公开 API 真实入口复验；QQ 和用户 Cookie 平台实机验收未代做。
- 以 docs/live-chat-followup-2026-09-06.md 为本轮准确说明；此前整份 Cookie 跳过和仅整条引号清理描述已过时。

## 聊天最终自然语言输出
- [in_progress] 最终渲染层去掉聊天引号/Markdown，常见 LaTeX 转可读表达；正文、分段、图片说明保持一致。
- [pending] 保留 URL、英文撇号和管理员参数；补最终 OneBot 发送验证、完整 verify 和交接文档。

## 聊天最终自然语言输出收尾
- [complete] bot.chat 正文和最终渲染文本/分段/图片说明接入确定性纯文本整理；不改人格 Prompt、不增加模型调用。
- [complete] 用户宝宝样例、Markdown/LaTeX、模拟 OneBot 最终 payload 定向回归通过。
- [pending] 用户重启实际运行进程后 QQ 实测；审计标识 chat_plain_text:v1。详见 docs/chat-plain-text-output.md。

## 2026-09-07 Phase 0-3 完成记录
- [complete] 64K 输出预算/科普详细策略、统一 quote/forward/mixed message、文件读取/生成文件、安全边界基线已接入。
- [complete] 完整 verify：343 passed、Ruff 通过、mypy 173 源码文件通过。
- [pending] Telegram 评论树 API 补拉、老格式文件依赖、生成文件扫描/清理和更强语义安全分类器。
- 详见 docs/phase0-3-implementation-2026-09-07.md。

## 2026-09-07 实测修复及 Phase 4–5
- [in_progress] 原始代码先保存、短文档明确落盘、真实上传 API/回执；安全决定留在内部并复用人格模型。
- [pending] 超时预算协调、限频戳一戳统一出站、Wiki 分节定向摘要、帮助/参数和完整回归。
- 不改人设源文件、不推送、不调用真实付费模型。

## 2026-09-07 Phase 4-5 续修
- 文件生成改为原始回复抽取并调用真实 OneBot 上传 API；安全拒绝改为人格化模型回应/兜底。
- Phase 4 文本戳一戳冷却已注册；Phase 5 Wiki 游戏摘要已接入。Telegram 评论树、真实 NapCat poke、复杂 Wiki 仍待实机验收。

## 2026-09-07 最终收尾

- [complete] 修正 Phase 0-3 上传测试夹具参数名冲突；定向测试 17 passed。
- [complete] 修正 chat.py 中安全分支 max_tokens 类型转换；完整 verify 352 passed、Ruff 通过、mypy 174 源码文件通过。
- [complete] backend-smoke、backend-base-smoke、doctor 均通过；明确记录 static/fake transport 与 napcat_connected=false 的边界。
- [complete] 统一 `.env.example` 中重复的聊天输出上限配置，保留 65538 唯一权威项。
- [complete] 创建最终交接文档 `docs/handoff-final-2026-09-07.md`，列出用户全部要求、已完成、未完成、验收步骤、数据安全和后续优先级。
- [pending] runtime-layout 仍失败：源码 data 运行产物和 156 个 Python 缓存路径未清理；必须先做归档/校验再清理。
- [pending] 不推送 Git；当前工作区历史脏变更未拆分为可安全 alpha test 提交。

## 2026-09-07 alpha.2 收尾（参考插件取长补短）

- [complete] 修复 pytest 临时目录顽疾：`dev.ps1 Invoke-Test` 固定 `PYTEST_DEBUG_TEMPROOT` 与 `--basetemp` 到每进程专属 Runtime cache 目录，绕开 `%TEMP%\pytest-of-*` 中损坏的循环符号链接（ACL 拒绝访问，无法提权修复）。
- [complete] 修复 mail bridge 测试 flake：测试状态文件从 `Path.cwd()` 迁到 pytest tmp_path；`_save` 增加原子替换瞬时锁重试（Windows 文件扫描器竞争）。
- [complete] 完成 12 个社区插件取长补短评审，结论见 `docs/plugin-benchmark-2026-09-07.md`；采纳 3 项（掉线通知/搜索重试/Wiki 缓存限流），5 项明确不引入并记录理由。
- [complete] 新增掉线管理员通知（`runtime/disconnect_notice.py`，Telegram+邮件双渠道带冷却，默认关闭）。
- [complete] 搜索适配器增加瞬时错误原地重试；`.env.example` 补 Tavily `search_depth`/`time_range` 透传示例。
- [complete] `sources/mediawiki.py` 增加 TTL 缓存+最小间隔限流（交接 P2.9 落地）。
- [complete] 全量 verify：361 passed、Ruff 通过、mypy 175 源码文件通过。
- [pending] 真实 NapCat 重启验收（私聊/群聊/引用/图片/文件/poke）仍需用户实机执行。
- [pending] 显式文件清单提交并推送 v0.0.1-alpha.2（用户已授权推送，禁用 `git add -A`）。
