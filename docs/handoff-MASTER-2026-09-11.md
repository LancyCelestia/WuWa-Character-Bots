# Handoff 主控文档（MASTER · 2026-09-11）

> **定位：所有交接文档的单一入口。** 接手者从本文出发，按 §一 权威链读正文，按 §三 总账领任务。
> 本文只做三件事：①裁决文档族谱的权威关系（历史上多份文档互相声称"唯一活文档"，已在 §一 终裁）；
> ②把散落在 8+ 份文档里的**未完成事项合并成一份总账**（§三，逐条标来源与现状，防止重做与遗漏）；
> ③给出现行事实速查（§四）。正文细节不复制到本文，一律指向权威文档对应节。
> 成文：2026-09-11 深夜 · 分支 `v0.0.1-alpha.2` · HEAD `7c0b615` · 门禁 **1033 passed / 0 failed + lint 全绿**（实跑）。
> **刷新（2026-09-12 接手会话）**：本文结构不变，事实以 §二 09-12 对账行为准；总账增补见 §三.0；最新增量=`handoff-session-2026-09-12-review-fixes.md` → `handoff-session-2026-09-12-final.md`（含 §0.1 虚报勘误与 §8 五轨收尾）。
> 维护规则：每轮交付后更新 §三 勾销状态 + §四 基线数字；新会话交接报告在 docs/ 新建带日期文件并登记进 §一。

## 一、文档族谱与权威链（终裁）

### 阅读顺序

1. **本文**（入口 + 总账）→ 2. `handoff-2026-09-10-full.md`（**权威正文**：系统全貌/硬约束/排障/协作协议/§15 任务分组）→ 3. `handoff-session-2026-09-11-bgroup-verify.md`（B组验证轮 + bot.py 启动修复）→ 4. `handoff-session-2026-09-12-review-fixes.md`（评审修复 + 配置治理 + axonhub，20 提交）→ 5. `handoff-session-2026-09-12-final.md`（最新增量：综合修复**含 §0.1 虚报勘误** + §8 五轨收尾轮）→ 6. 按需查 §三 标注的需求底稿。

### 族谱表（时间序）

| 文档 | 时点 | 性质 | 当前状态 |
|---|---|---|---|
| `handover-2026-08-29.md` | 08-29 | 会话交接（后端韧性/P1-P5/X GraphQL 半成品） | 已被 08-31 取代；**§9.3 分片幂等规格、§10 七平台深化需求仍是有效底稿**（被 §三 引用） |
| `handover-2026-08-31.md` | 08-31 | 全量快照（253 passed 时代，含 §〇 紧急事项） | 已过时；§2.9 待办清单是后续多轮销项的对照底稿 |
| `handover-2026-09-01.md` | 09-01 | 周期快照（267 passed：V2 清理/六平台深化/视频直发） | 已过时；§四 剩余待办仍部分有效（并入 §三） |
| `handoff-comprehensive-2026-09-05.md` | 09-05 | 全量审计（现状/目标架构/路线图/305 配置字段/风险登记） | 历史存证；**§3 目标架构、§8-15 设计规格（Provider/计费/沙箱/穿透）是未竟长线的需求源** |
| `backend-base-status/chat-memory-routing-fixes/live-chat-followup/search-api-adapters/phase0-3-implementation/plugin-benchmark/standard-parse-card-acceptance`（7 份 09-06→09-07 期报） | 09-06/07 | 过程期报 | 内容已并入 09-07 handoff 修复史，仅存档价值 |
| `handoff-final-2026-09-07.md` | 09-09 定稿 | 活文档（684 passed 时代） | **已冻结**（自称被 09-10 版取代）；§8 修复史索引有价值 |
| `handoff-final-2026-09-10.md` | 09-10 | 活文档（865 passed：审计修复轮精简版） | 已被 full 版超越（两版曾同时自称"唯一活文档"，**以 full 版为准**，本文件头部已加指向） |
| `handoff-2026-09-10-full.md` | 09-10/11 | **全量手册**（§13 审计 90 项 + §14 解析深度手册 + §15 第二轮 A/B/C 任务分组） | **权威正文**；§15 已含 09-11 验证会话补记 |
| `code-reaudit-2026-09-11.md` | 09-11 | 并行会话新落的代码复审报告 | 本会话未读，状态 unknown——接手者自行评估后把有效项并入 §三 |
| `handoff-session-2026-09-11-bgroup-verify.md` | 09-11 | B组验证与补强会话交接（做好的/没做好的全清单） | 增量，与 full 版 §15 补记配套 |
| `handoff-session-2026-09-12-review-fixes.md` | 09-11/12 | 评审修复 + 配置治理会话（P0-1 二十提交拆分入库、axonhub 网关、热改键 42→63、引用链/语音/转发修复、群限流） | 有效增量；其 §4.2 未修清单大半已由后续轮销项 |
| `handoff-session-2026-09-12-final.md` | 09-12 | 综合修复收尾交接 | **半可信**：`.env` 侧声明真实、**代码侧声明大面积虚报**（见其 §0.1 勘误核验表）+ §8 五轨收尾轮（可信，带提交哈希） |
| 根目录 `task_plan.md`/`findings.md`/`progress.md` | 早期 | 过程 scratch | 早期会话遗留，无权威性；随归档批次处理 |

### 权威冲突终裁记录

`handoff-final-2026-09-10.md` 与 `handoff-2026-09-10-full.md` 同时自称权威——**终裁：full 版胜出**（覆盖 §13/§14/§15，且 §15 仍在其上活动更新）；精简版降级为历史存证。

## 二、现行事实速查（数字以此为准，其余细节读权威正文）

> ⚠️ **2026-09-11 评审更正（本节原文已过期）**：下文「HEAD `7c0b615` · 1033 passed」是 **02:11 的旧快照**；实测 HEAD 已推进到 `cbb5161`（晚 26 个提交），工作树门禁为 **1320+ passed**，mypy **222 文件零 issue**。数字请在每次交付时重新实跑填写，不要沿用旧值。首份评审报告见 `review/REVIEW-3819299..cbb5161.md`。
>
> ✅ **2026-09-12 对账刷新（以此为准）**：评审会话 20 提交 + 反思补偿后，接手会话实测：**工作树干净、bot.py 启动修复已入库（f4e29a2）、「未提交规模」清零**——重启前置仅剩提权动作本身。门禁（09-12 两波收尾终局实跑）：**1511 passed / ruff 全过 / mypy 223 文件零 issue**；当日提交链 `8f0abbe..a2f6923` 共 12 提交（明细=final 文档 §8/§8.5）。

- **门禁（2026-09-11 评审轮实跑，工作树）**：pytest **1320 passed / 0 failed / 1 warning**（68.5s）、ruff **All checks passed**、mypy **Success: no issues found in 222 source files**、`dev.ps1`。
  - 旧记录（已被取代）：1033 passed（09-11 02:4x 于 `7c0b615`）；mypy 205 文件（09-10）。
- **⚠️ 生产进程仍运行 09-09 旧代码**（管理员权限，重启被阻塞，见 full 版 §4.3）——09-10 起的全部交付（含 Gemini 置顶、算法 v2、审计 90 项、B组 14 项）**都在等提权重启生效**。重启前置：先提交 bot.py 启动崩溃修复（见下）。
- **⚠️ bot.py 启动修复未提交**：工作树已修（async `on_startup` + `get_running_loop()`），HEAD 仍是坏的 import 期写法。**这是生产重启的硬前置。**
  - 评审补充（H1）：HEAD 那版的问题不是"启动即崩"，而是 `asyncio.get_event_loop()` 取到的**与运行循环不是同一对象**（实测 `loop1 is loop2 == False`）→ 降噪处理器**从未生效**，并触发 "There is no current event loop" 告警（3.14 下该写法直接报错）。`tests/` 里**没有**任何测试 import `bot.py`，故门禁绿不能证明它。
- **⚠️ 未提交规模（评审 H1/H2 实测）**：`git status` 显示 **63 个已跟踪文件 dirty（+2426/−414）** + **34 个未跟踪**（含 **26 个回归测试文件 / 280 用例**，占全量 21.3%）。**这些不在 HEAD** —— 检出 HEAD 时门禁数字不可复现。重启前必须先把工作树提交入库。
- 工作树常年多会话在途改动：开工先 `git log` 查时效（09-11 教训：两个会话同晚开工同一任务组，靠 git log 才避免重写），再按 full 版 §11 协作协议（禁 `git add -A`、共享文件动前登记、§11.4 部分暂存）。
- push 用完整 refspec：`refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2`（分支与 tag 同名）；推送 origin 仅按用户明确指示。

## 三、未完成总账（跨 8 份文档合并去重，逐条标来源与现状）

### 0. 2026-09-12 对账增补（新会话先读这段，再往下翻旧账）

- **已销项（09-11 评审会话，证据=其 20 提交链 f4e29a2..75e57ad + 反思补偿 c7657a7）**：发送队列/审计/回执/诊断启用（.env）、引用链结构化+递归、语音入站、转发聊天记录、群限流双窗口（InMemory）、axonhub 统一网关、热改键 42→63、队列毒行隔离、SSRF 护栏、历史明文 key 清洗等——明细见 review-fixes 文档 §1。
- **已销项（09-12 接手会话五轨收尾，证据=8f0abbe..4606f34 + 超时对齐 C7）**：群摘要白/黑名单接线、SQLite 限流器群帽、系统提示词紧凑压缩、/bot help 补全（identity/quirk/新键）、Telegram file_id→字节、昵称 9 个仓库侧对齐、RAG 领域词战双/库洛、LLM 默认超时对齐生产。明细=final 文档 §8.1。
- **新发现**：final 交接文档（09-11 综合修复会话）代码侧声明大面积虚报——好感度 9 档/γ=2.0、baseline_effort、回复相关性规则等未落库，核验表见 final §0.1；权威正文被编辑器锁定，4 处勘误在 `review/handoff-2026-09-10-full.corrections-20260912.patch`（`--check` 已过，关编辑器后 `git apply -p0`）。
- **已销项（09-12 第二波五轨）**：G-INDEX（B股+MOEX ISS，`47a5176`）、G-DIGEST 夜推（`f90a96f`）、G-MERMAID（`6aa808e`）、G-SUB-LIVE（`a2f6923`）、虚报补实批（`b0ca5b4`）+ randpic validator 潜伏 P0 修复。门禁终局 **1511 passed / ruff / mypy 223 全绿**。明细=final 文档 §8.5。
- **需用户决策**：好感度 9 档 [-100,+100] + γ=2.0 改版是否立项（现状=4 档 [0,100] γ=1.0，affinity-design.md 与代码一致）。

### A. 等用户前置（代码无工作，勿白做）

| 项 | 来源 | 备注 |
|---|---|---|
| NapCat/生产 bot 提权重启 | full §9 | **最高优先**；~~重启前先提交 bot.py 修复~~ 已入库（f4e29a2），前置全部满足，仅剩提权动作 |
| B站/X/知乎/linux.do cookie、微博重灌 | full §9/§15 | `/bot cookie import`，灌后触发 A-3/A-4/A-5 回归 |
| umi 充值、QIANQIANYE 换 key、ds-official key、toolcode-gemini 下架 | full §9 | 渠道运维 |
| 21 平台真实分享链接、QQ 订阅推送目标 | full §15 | 供 A-5/C-6 实测 |
| （旧建议）Telegram Token / QQ 授权码轮换 | 08-29 §二.11 | 用户始终未确认是否已轮换；建议复核 |

### B. 代码侧开放项（按域分组；领任务先核对 full §15 是否又撞车）

| # | 项 | 规格来源 | 现状 |
|---|---|---|---|
| B1 | 分片发送幂等恢复与部分成功续发（part 级进度/UNKNOWN 确认协议/部分成功续发） | **08-29 §9.3 完整规格** | 开放——A7/A8/A11（09-10）已做请求级副作用进度，part 级仍未做 |
| B2 | 中央决策层/统一事件入口（CentralDecisionEngine；现仍多入口 matcher） | 09-05 §3.3 十条强制规则 | 架构长线，未动 |
| B3 | FileTransferGateway 统一文件出站（现 handler 直连 call_api） | 09-10-full §10.5 | 架构长线 |
| B4 | Control Plane API + TailAdmin Vue UI（后置策略已定）+ SakuraFrp 公网（3GB/日、10Mbps、断路器、认证） | 09-05 §7/§14/§15/§16-17 | 后置未动；**API 先行、UI 最后**的顺序已裁定 |
| B5 | LLMCallRecord 结构化计费表（现 usage_monitor 仍是日志文本聚合）、Provider/Balance 适配（NewAPI 合同已给）、Extractor 沙箱（等用户脚本） | 09-05 §8-13 | 后置/待用户资料 |
| B6 | 音乐动态订阅与真实榜单（QQ/酷我/酷狗/Spotify 订阅、MusicChartRegistry 真实 source、歌曲字段补全） | 08-31 §2.9-4（详单 08-29 §10.5） | 开放 |
| B7 | 平台深化残余：TG fixture 覆盖（嵌套 DOM/置顶/多反应/编辑删除）、xhs user_posted 正文时间互动、YT Atom/shorts、微博 card group/长文/置顶变体 | 08-29 §10.4 / 09-01 §四-2 | 开放 |
| B8 | target metadata 持久化 API（X rest ID 等显式落库）+ 订阅 V1/V2 双轨清理合并 | 08-31 §2.9-5 / 09-05 §16.2 | 开放 |
| B9 | 架构级长线：claim-based RAG、TrustLevel 反注入体系、ToolCatalog、PersonaContract 结构化知识 | 09-10-full §10.5 | 长线 |
| B10 | 气象预警、QQ 空间日记（草稿+审批）、戳一戳统一 reaction、表情包端到端验证、多模型盲测/Playground、`/bot commands` 命令透明化 catalog、搜索质量评测/引用策略、DB owner 清单与迁移统一 | 09-05 §5/§16-18/§20 | 登记未做 |
| B11 | P4 Crawl Wiki `/bot wiki` | 08-29 §9.4 | **用户明令暂缓**——不得扫描/导入 `D:\Coding\Crawl Wiki` |
| B12 | 本会话 parked Minor ×3（限长用例断言偏宽/缺双代理键用例/矩阵缩进）+ result_unknown 台账 TTL | `.superpowers/sdd/b-group-2026-09-11/progress.md` | 低优先级 |
| B13 | universal_card.html 写死品牌色残留（VIP/认证徽章/Top3 序号） | 09-10-full §9 | 卡 UI 迭代时收敛，改后必跑样例截图+三门禁 |
| B14 | LangSearch 真实 key 验收 | 09-10-full §9 | 等用户 key |
| B15 | 知识库 `sync_chunks` 按清单删块语义：运行中进程清单过期仍会删清单外新块（08-31 §〇 事故） | 08-31 §五-2 | C组 C-5 已加 (mtime,size) 签名缓存减少重读，但**删除语义本身未变**——根治需改契约，未立项 |

### C. 已销项对照（防重做——动手前先查这里）

视频直发✅(09-01) · ParsedContent 扁平投影删除✅(09-01) · 管线检视 13 条全部✅(09-10 两会话+09-11 验证轮，#1/#2/#3/#4/#5/#6/#7/#8/#9/#10/#11/#12/#13) · chat.py 三项延后（MCP 负缓存/输出装箱/抽取有界化）✅ · 好感度 dispatch 接线✅(6de4aa2) · spicy_filter flaky✅ · 小名否定宽度✅ · 全库 urlopen 清零✅(09-11 temporal 收尾) · vision 三模式✅ · Steam 周免✅ · 解析注册表缓存/probe 重入/订阅权限等审计 90 项✅(09-10) · B组 14 项✅(09-11 并行会话，本会话独立验证属实) · 测试树 test_perf_* 评估✅保留不归档 · P1/P2/P3/P5 后端韧性✅(08-30)。

## 四、归档建议（待用户批准，本会话未移动任何文件）

按 `docs/workspace-archive-policy.md`（压缩→验证→移出）可归档至 `ChatBot_Archive`：handover-2026-08-29 / 08-31 / 09-01、handoff-comprehensive-2026-09-05、handoff-final-2026-09-07、handoff-final-2026-09-10（被超越版）、7 份 09-06/07 期报、根目录三份 scratch。**§一 族谱表已保全其索引价值，移出不丢信息。** 保留在 docs/：本文、`handoff-2026-09-10-full.md`（权威正文）、`handoff-session-2026-09-11-bgroup-verify.md`、活动设计文档（affinity-design 等）。
