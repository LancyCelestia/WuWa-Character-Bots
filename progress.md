# 审查进度日志

- 2026-09-05：创建 task_plan.md、findings.md、progress.md，准备按 7 个阶段扫描。
- 2026-09-05：完成阶段1根目录与配置初盘；已记录 Git 工作树状态、NoneBot 启动装配、适配器注册与缓存卫生问题。
- 2026-09-05：Markdown 初扫因 `.pytest_cache` 权限错误失败；将采用 Git 文件清单/显式目录排除替代。
- 2026-09-05：目录树初次命令因 PowerShell 语法错误中断，已修正。
- 2026-09-05：目录汇总第一次因根目录文件路径处理错误中断，已改用安全相对路径。
- 2026-09-05：AST 索引初次因 stdout 编码失败；已改用 UTF-8 输出环境变量。
- 2026-09-05：补充 pyproject、环境键分组、配置格式清单与目录统计；进入代码/文档主题交叉检查。
- 2026-09-05：核对 NoneBot 官方 quick-start/GitHub，仅用于说明 adapter/plugin 边界；本地完成度判断仍以源码证据为准。
- 2026-09-05：订阅引用检索遇到缓存目录权限错误；已切换到显式排除遍历。
- 2026-09-05：天气源文件名假定错误；改由 capability import 和实际清单定位。
- 2026-09-05：完成目录映射与核心生产代码走查；确认解析平台广、业务能力不等价于完整平台接入；发现订阅 capability 的 `asyncio.run` 事件循环风险、同步网络能力未全面 offload、用量监控没有 Web UI/图表/余额查询。
- 2026-09-05：规定测试入口因工作区临时目录创建权限拒绝而未运行。
- 2026-09-05：测试备选入口因当前 Python 环境缺少 pytest 未执行。
- 2026-09-05：规定 lint 入口因外部 Runtime 缓存写权限失败；准备临时目录重定向复核。
- 2026-09-05：直接 Ruff 检查完成但发现 6 个 lint 问题；继续尝试使用外部 Runtime venv 的 pytest 并将临时目录重定向到系统 Temp。
- 2026-09-05：pytest 收集 279 项，首轮 240 passed/39 errors，原因是 Temp 目录权限；准备改用可写的可视化目录重跑。
- 2026-09-05：pytest 第二轮迁移 basetemp 后长时间无进展，已中断；测试不宣称通过。
- 2026-09-05：完成 Config 字段与 .env/.env.example/.env.prod 的静态映射核对；记录 19 个示例独有键、2 个实际独有键。
- 2026-09-05：Web UI 静态检查的 Git 路径传递遇到 Unicode 转义问题；已有显式遍历结果足以证明 Web 资源清单，记录后继续。
- 2026-09-05：订阅引用命令因 PowerShell 参数解析失败；已记录，继续用已有证据。
- 2026-09-05：完成预期平台、核心功能、Web UI、架构风险与验证结果交叉比对；形成最终报告素材。
- 2026-09-05：最终 AST/docs/plugin/runtime-layout 校验完成；Ruff 稳定报告 6 项；pytest 未能获得完整结论，审查结束。

- 2026-09-05：写入正式审计与现代化路线图 `docs/project-audit-and-modernization-roadmap-2026-09-05.md`，共 662 行；完成章节与关键词校验，未修改业务源码。

- 2026-09-05：根据用户决策补充 TailAdmin Vue 后置 UI、后端优先、可插拔公网认证、可配置搜索/余额 provider、文件执行策略和详细 Phase 0-9 计划；并将 6.4 小节移动到 Web UI 审计章节内。

- 2026-09-05：根据新增模型配置、URL、默认模型/模型列表、计费、余额、日志 Token、联通检测和 extractor 安全要求，新增 `docs/control-plane-provider-and-usage-requirements-2026-09-05.md`；当前不实现提取器和业务代码，等待用户提供站点脚本资料。

- 2026-09-05：根据 SakuraFrp 实际条件补充硬性传输预算：每日 3GB、隧道最高 10Mbps、控制面默认约 2Mbps、预算状态机、流量计量和断路策略；记录 SakuraFrp MiB/KiB 单位和节点/上行带宽限制。
- 2026-09-05：用户确认后端优先首批，新增 `backend_unit.py` 单轮 JSON 执行入口，接通现有 RuntimePipeline/知识上下文/静态 provider。
- 2026-09-05：新增可选订阅初始化 fail-open 边界；订阅数据库初始化失败时记录审计并继续核心 NoneBot handler 注册。
- 2026-09-05：focused tests 2 项通过；`backend-smoke` 通过；`startup-smoke` 通过。
- 2026-09-06：修复 `scripts/dev.ps1` 在 Windows PowerShell 5.1 下的帮助 here-string 解析错误；用户粘贴的 smoke 命令已复跑通过。
- 2026-09-06：新增 Tavily/You.com/LangSearch 搜索 API 适配和 TinyFish 正文抓取适配；6 项 provider 协议测试、8 项本轮回归测试通过。
- 2026-09-06：修复 Windows PowerShell 5.1 下 `scripts/dev.ps1` 全任务解析失败及中文输出乱码；用户贴出的 smoke 命令复跑成功。
- 2026-09-06：完成 Tavily/You.com/LangSearch 搜索链与 TinyFish 可选正文抓取的配置化 adapter，未配置 key 安全空链；8 项本轮测试和所有针对性 Ruff 检查通过。
- 2026-09-06：未执行任何 Git push；本地 alpha-test 分支仍指向 `48bd676`，本轮搜索集成因依赖共享脏文件尚未另行提交。
- 2026-09-06：完成 Runtime 数据迁移分类与上下文编译器设计；本轮只做审计和方案，不修改业务实现，不执行 Git push。
- 2026-09-06：用户确认复制验证迁移和单次归档备份方向；形成防御型上下文编译器、claim graph、证据账本、污点追踪和工具授权票据设计，等待进入正式 spec/Phase 0 实现。
- 2026-09-06：用户确认人格 Prompt 重构后置，当前优先真实 LLM 聊天和后端主链路可用性。
- 2026-09-06：真实 `chat-smoke` 通过：OpenAI-compatible provider 返回 ok/stop/sent，并完成一次真实控制台聊天；人格 Prompt 重构继续保留在 TODO，未修改人格源文件。
- 2026-09-06：新增后端底座状态与未完成清单 `docs/backend-base-status-2026-09-06.md`，明确主聊天链路已通但边缘直接发送、实机 NapCat、统一出站网关仍未完成。
- 2026-09-06：`backend-base-smoke` 通过：NoneBot/plugin/startup/OneBot fake transport/backend pipeline 全部通过；真实 NapCat 连接仍未验证。
- 2026-09-06：新增并接入 `IngressGateway`/`UnifiedDeliveryGateway` 到主能力处理和出站路径；`backend-base-smoke` 全部通过。
- 2026-09-06：真实控制台聊天复测出现一次 30 秒后 provider 瞬态失败，记录为未完成稳定性验收；未修改人格 Prompt。
- 2026-09-06：文件 handler 文本提示已迁移到统一 RuntimePipeline/UnifiedDeliveryGateway；文件 call_api 副作用和专用文档生成 LLM 仍列为后续边界。
- 2026-09-06：根据实机日志修复图片/表情无回复：visual segments 现在进入 chat matcher，空文本补内部占位消息；相关 23 项回归测试通过。
- 2026-09-06：图片实机测试通过；下一优先级为修复 memory extraction 401 和提升游戏人物/关系问题的详细回答能力。

## 2026-09-06 本轮最终验证
- 完整规定入口测试：309 passed，1 条上游 Mail/Pydantic 警告；git diff --check 退出 0。
- lint 未通过：pricing.py / usage_monitor.py 共 6 项。runtime-layout 未通过：data 运行产物及 156 个缓存路径；未清理活动数据。
- 记录本轮路由、完整度、优先级及 help 修复和未完成项：docs/chat-memory-routing-fixes-2026-09-06.md。
- 按用户节省算力要求，不再发真实模型诊断、不推送、不扩展新子系统。真实 QQ 文本/图片可用以用户反馈为准；本轮记忆鉴权仍待重启验收。

## 2026-09-06 群聊/来源/视频解析修复
- 新增群聊整条回复外引号回归、维基精确匹配与无关候选拒绝、梗结果相关性/URL 去重、Cookie 安全降级测试。
- 完整回归扩展至 314 项；本轮最新一次完整测试通过，lint 通过。backend-smoke 通过且明确使用 static provider。
- 不推送 Git、不调用真实付费模型；真实群聊和外部来源仍待实机复测。

## 2026-09-06 22:40 续修交接
- 按句引号、Wiki 列表条目、小红书 discovery 路由、Cookie 内存规范化与降噪、doctor 解释器路径、mypy 类型问题已处理。
- 四个用户 Wiki 查询已通过公开 API 真实入口复验；QQ 和用户 Cookie 平台实机验收未代做。
- 以 docs/live-chat-followup-2026-09-06.md 为本轮准确说明；此前整份 Cookie 跳过和仅整条引号清理描述已过时。

## 最终验证证据
- 完整 `scripts/dev.ps1 verify` 退出 0：328 passed（1 条上游 Mail/Pydantic 弃用警告），Ruff All checks passed，mypy 169 source files 无错误。
- `doctor` 退出 0：ok=true，nb_cli=ok，ready_for_nonebot_run=true。
- `runtime-layout` 未通过：data 活动产物及 156 个源码缓存路径；独立于 verify，未删除。
- 四项真实公开 Wiki 查询均 matched=True；QQ、视频/小红书真实登录态未代替用户验收。

## 聊天最终自然语言输出收尾
- [complete] bot.chat 正文和最终渲染文本/分段/图片说明接入确定性纯文本整理；不改人格 Prompt、不增加模型调用。
- [complete] 用户宝宝样例、Markdown/LaTeX、模拟 OneBot 最终 payload 定向回归通过。
- [pending] 用户重启实际运行进程后 QQ 实测；审计标识 chat_plain_text:v1。详见 docs/chat-plain-text-output.md。

最终完整 verify：退出码 0；335 passed，1 条上游 Mail/Pydantic 弃用警告；Ruff All checks passed；mypy 170 个源码文件无错误。未调用真实 LLM 或发送 QQ 消息。

## 2026-09-07 Phase 0-3 完成记录
- [complete] 64K 输出预算/科普详细策略、统一 quote/forward/mixed message、文件读取/生成文件、安全边界基线已接入。
- [complete] 完整 verify：343 passed、Ruff 通过、mypy 173 源码文件通过。
- [pending] Telegram 评论树 API 补拉、老格式文件依赖、生成文件扫描/清理和更强语义安全分类器。
- 详见 docs/phase0-3-implementation-2026-09-07.md。

## 2026-09-07 Phase 4-5 续修
- 文件生成改为原始回复抽取并调用真实 OneBot 上传 API；安全拒绝改为人格化模型回应/兜底。
- Phase 4 文本戳一戳冷却已注册；Phase 5 Wiki 游戏摘要已接入。Telegram 评论树、真实 NapCat poke、复杂 Wiki 仍待实机验收。

## 2026-09-07 最终收尾

- 完成测试夹具、mypy 类型和 `.env.example` 重复配置收尾修正。
- 最终验证：352 passed；Ruff 全通过；mypy 174 个源码文件无错误；backend-smoke、backend-base-smoke、doctor 通过。
- runtime-layout 仍失败，原因是源码 data 运行产物和 156 个 Python 缓存路径；没有删除活动数据。
- 写入 `docs/handoff-final-2026-09-07.md`，作为后续唯一完整交接清单。
- 没有 Git push、没有真实消息发送、没有修改人格源文件。

## 2026-09-07 alpha.2 进度

- 修复 verify 基建（pytest 临时目录、mail 测试 flake），基线恢复全绿。
- 完成参考插件评审与三项采纳落地；新增 `tests/test_disconnect_notice.py` 等回归，测试 352→361。
- 全量 verify：361 passed；Ruff 全通过；mypy 175 个源码文件无错误。
- 按用户授权准备显式清单提交并推送 v0.0.1-alpha.2；未使用 `git add -A`，未触碰活动运行数据与人格源文件。
