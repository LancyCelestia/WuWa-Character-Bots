# HANDOFF — 统一性审查三会话全量归档（2026-09-19）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](docs/snowluma-setup.md)。

> **这是什么**：把会话 `22bb78f8`（后端统一审计波）与 `b0a268b2`（补跑+修复波）的全部上下文、调查结果、审查结论、失败归因与相关记忆，装进一个可冷启动的文件。
> **归档口径**：分层——正文给可接手的蒸馏，附录给关键片段逐字，其余用**绝对路径指针**（原始数据 37.6 MB 本就在盘上，不复制第二份）。
> **给谁看**：下一个接手 AI。本文件自包含，不需要任何会话上下文即可开工。
> **汇编者**：会话 `04ca6038`（2026-09-19 17:24 起），非上述任何一波的参与者。
> **诚实声明**：本文件不新增任何未经席位举证的结论。凡汇编者本人复核过的标 `✅`；推断标「推断」；没查清的写「未查清」，不填空。

---

## §0 一页速览：实际上是**三个**并行会话，不是一个

归档过程中发现：用户当时把同一条 mandate **按域拆成了两个并行审计会话**，再串一个修复会话。只归档用户点名的两个会**漏掉 1.2 MB 的同主题结论**。

| 波 | 会话 id | 域 | 编号体系 | 席数 | 产物 | 结局 |
|---|---|---|---|---|---|---|
| A | `22bb78f8-5286-4bf0-80b2-12d415f0e5dd` | **后端**全域统一 | U1–U24 | 24（超发，mandate 是 10） | 21 份 `docs/design/audit-20260920-unify-U*.md`，6,536 行 | 16:55:42 被 406 封，17:23 彻底停 |
| B | `3b50fe67-c6e5-4ef0-a55d-f78e323076e4` | **TTS**专项 | D1–D10 → T1–T31 | 10 满载 + 补派 | **31 份** `.superpowers/sdd/2026-09-19-unify-audit/report-*.md`，**1.2 MB** | 跑完（多数 `DONE_WITH_CONCERNS`） |
| C | `b0a268b2-bfa5-4b69-87b8-aeba3f74a62d` | 承接 A 的缺口：补跑 + 修复 | R20–R24 / F1–F4 / G1 | 10（守住上限） | 覆写 U20/U23、新建 U24、**F1 修复完成**、10 个回归锁测试 | 18:00:06 被同一个 406 封 |

**波 B 此前不在任何汇总里。** `docs/design/audit-20260920-unify-summary.md` §7.1 曾写「TTS 面本次等于没审」——**该条只对波 A 成立，对全局是错的，须修订**。

---

## §1 用户 mandate（三波共同源头，逐字）

波 A 首条消息（15:46）原文：

> 全面审查一遍，用最残酷无情的态度去找出来所有的错误、漏洞、问题，统一消息、统一协议、统一架构、统一函数、统一变量、统一参数，上面所有东西都需要经过中央处理的统一指令，然后再去接着派给各个插件去处理，然后TTS这边也是同理
> 允许派遣**10并发子代理，保持时刻满载，一个结束就派新的上去**，understand？
> 复述一遍我的要求

附件引用：`audit-20260919-unify-wave.md`、`HANDOFF-V21R5-20260920.md`、`AGENTS.md`、`HANDOFF-V21R4-20260918.md`、一份 7dde20e7…txt。

波 B `plan.md` §0 把判定标准提炼成一句（**这是全案的尺**）：

> 本审计的判定标准不是「代码写得乱不乱」，而是：**这句话在今天的树上是否为真。** 凡「本应经中央、实际绕过中央」的每一处，都是缺陷；中央本身若有多份定义/多份实现/零接线，也是缺陷（且是更严重的缺陷）。

### mandate 的两次改判

| 时刻 | 用户原话 | 后果 |
|---|---|---|
| 16:02（波 A） | 「**你只需要查后端**，可以吗？understand？**停止非后端的检查**」 | 波 A 砍掉前端/TTS；波 B 因此被立为独立会话专审 TTS |
| 16:27（波 A） | campus 旁路「需要改，**改成走中央决策（但是不准新建旁支）**」 | 升格为全案硬纪律，见下 |

「不准新建旁支」在波 C `master-plan.md` §二 被写成可执行条款：
> 要求「走中央」的，复用已存在的中央入口与正例，**不得造第三套**；缺机制就停下来报候选清单。

---

## §2 合并时间线（本地钟，2026-09-19）

```
15:46  A 开工，mandate 下达（10 并发上限）
15:49  B 建 plan.md，主代理自证地基事实 F1–F10
15:52  B 首轮派 D1–D10 十席
16:02  A 被改判「只查后端」→ B 收「只查 TTS」改判，D1–D6/D8–D10 九席 TaskStop（半成品报告作废）
16:24  B 转 Wave T，T2 起报
16:27  A 下达「走中央决策、不准新建旁支」
16:34  B TTS 波进入满载
16:55:42  ★ A 首条真实 406 Session blocked（capability_protocols 层）
16:56:18  A 的 U24 派下 0.576 秒即被拒（tool_uses=0）
17:00–17:32  B 继续产出 T14–T17、T25、T29…（不受 A 封禁影响 ⇒ 证明封禁按 sessionId 隔离）
17:12–17:15  A 用户连发「全修」「全修」「全部去修理，现在开始进行」——全部撞墙
17:16  A 「test」「继续」——仍撞墙
17:19  A 「迅速收尾，我要重启」
17:23  A 重发 mandate + 四技能引用，会话终止
17:24  C 开工：「22bb78f8 你能看到这个 id 的对话结果和工作区成果吗？」
17:25  C 派 Wave 1 十席（R20–R24 / F1–F4 / G1），并发上限 10
17:3x  C 四条待裁事项请示用户，用户未答 → 按保守缺省执行并留痕
17:32  B T16 报出「语音出站三条宣称全假」
17:36–18:15  B 持续补派至 T31
17:4x–17:5x  C 的 F1 完成修复并落回归锁
18:00:06  ★ C 首条真实 406（此前 35 分钟正常）
18:00:05–18:02:39  C 十席在 2 分钟内集体报 failed
18:05  C 用户发「继续」，无回复，会话终止
18:14  B 最后写入
```

---

## §3 审查结果

### 3.1 波 A · 后端统一审计（21 份，6,536 行）

**权威载体已是** `docs/design/audit-20260920-unify-summary.md`（357 行，含 §2 五条 P0 / §3 十二个 P1 主题 / §4 十七条待裁 / §5 十二条正面结论 / §6 执行顺序 / §7 缺口）。**本文件不重复它**，只给指针与增量。

分报告索引（全部 `docs/design/audit-20260920-unify-`，行数）：
`U1-invest`673 `U2-proto`261 `U3-outbound`453 `U4-dispatch`240 `U5-arch`1529 `U6-config`402 `U7-command`293 `U9-function`310 `U10-gate`212 `U11b-sec`337 `U12-llm`329 `U13-db`242 `U15-output`222 `U16-green`215 `U17-campus-wire`108 `U18-persona`227 `U19-correct`215 `U20-cp`66→**已覆写** `U21-conc`80 `U22-sandbox`43 `U23-adapter`79→**已覆写**

**波 A 主代理自证的地基事实**（`plan.md` §1，10 条，被后续各席反复引用）：

| # | 事实 | 证据 |
|---|---|---|
| F1 | 中央能力协议层 `runtime/capability_protocols.py` **1929 行、生产零导入**，仅测试导入 | grep 命中全在 tests/，plugins/ 下零命中 |
| F2 | `CapabilityResult` **两份同名定义** | `domains/core/contracts/runtime.py:226`（canonical）vs `runtime/capability_protocols.py:151` |
| F3 | 根 `__init__.py` = **8668 行 / 370KB / 95 顶层 def-class / 60 处 matcher 注册** | wc + grep |
| F4 | `runtime/` 包内 **22 个 18 行垫片 + 4 个未迁移真身**（capability_protocols 1929 / database_broker 481 / loop_watchdog 203 / service_wiring 184），后四者在 `domains/` 下**无对应文件** | 逐文件 wc + find 零命中 |
| F5 | 能力回调签名**至少三种形态** | `(message, decision: BotDecision)` / `(message, _decision: BotDecision)` / `(message, _decision: Any)` |
| F6 | `IncomingMessage(` 构造点 **16 处 / 8 文件** | grep -rn |
| F7 | 直接 `call_api`/`bot.send` 的文件 **13 个** | grep -rln |
| F8 | 旧路径垫片有**两种语义不兼容写法**：PEP562 `__getattr__` 活解析（tts.py 18 行）vs `import *` 快照绑定（weather.py 8 行）；`capabilities/` 下 37 文件行长 1–18 混杂 | head 对比 + wc |
| F9 | 根目录污染：字面 `%TEMP%` 空目录、`COORDINATION.md` 与 `docs/design/v21r2-COORDINATION.md` **双份占域台账**、`findings.md`/`progress.md`/`task_plan.md`/`审查结论与重构计划.md`、5 张 WebUI 截图 PNG | ls |
| F10 | 前次同主题审计已在：`audit-20260919-unify-wave.md`（469 行 / 20 条台账） | grep |

**主代理推论（原文）**：
> 中央处理层在「协议/注册/派发」三面均**存在但未接管**，现行真实中央是根 `__init__.py` 这个 8668 行上帝文件。**用户主张的架构与现实相反。**

⇒ 这是全案最重的一条，且**被波 A 的 U5-F-08（根文件 59% 集中在一个函数）与 U3/U4/U15/U18 的「六面并列入口」独立佐证**。

### 3.2 波 B · TTS 专项（31 份，1.2 MB）——**此前无人归档**

指针：`.superpowers/sdd/2026-09-19-unify-audit/`
- `plan.md` 5,862B — 判定标准 + 地基事实 F1–F10（上表来源）
- `briefs.md` 26,197B / `briefs-tts.md` 24,968B — 席位简报
- `progress.md` 51,585B — **唯一进度真相源**（该波明确未建 TodoList，理由：10 席随时补位，todos 立刻失真）
- `report-T1…T31 + report-D7` — 31 份分域报告

**去重总账 = `report-T29.md`（TTS 缺陷去重总账，全席合并唯一编号版）** ⇒ 接手 TTS 面**先读 T29，不要从 31 份平铺读**。

席位地图（状态取自各报告抬头）：

| 域 | 报告 |
|---|---|
| 引擎侧 | T2 契约复核(GPT-SoVITS V2Pro 只读) · T12 引擎可用性与运维面 · T25 合成参数与音质取证 · T3 参考音频池与语料实况 |
| 入站 | T13 语音入站与转写链路(ASR/摄取/预转码/隐私) · T22 **入站转写注入绕过独立复现** · T27 群聊劫持终态矩阵 |
| 出站 | **T16 原子性/重放/幂等** · T17 审核失明 + 跨通道外流 · T4 编解码与 QQ 可播性 · T9 语音内容政策与隐私 |
| 统一性 | T23 **中央惯例符合性矩阵**（对「项目自己立的规矩」逐条判决） · T6 配置与登记「五处同生」对表 · T7 **文档宣称 vs 实码能力诚实性复核** |
| 工程面 | T5 测试与门禁实跑 · T8 性能与资源有界性 · T11 离线端到端可执行验证 · T21 生产日志里的语音实况 · T24 工具链与自检测有效性 · T14 可观测性/审计/账本 · T18 交付可追溯性与回滚证据 · T31 版本保护落地单 |
| 触发面 | T15 触发词劫持面实测 · T26 对话自动配音「打开后会发生什么」量化预测 |
| 方案席（不施工） | T10 中央化收编施工图 · T20 可用性与引擎安全收口施工图 · T30 修复施工阶梯与回归锁设计（**一律不施工**，R-1 裁定遵守） |
| 对抗复核 | **T19 对已报 P0/P1 的对抗性证伪** · T28 被审方自审件与本波报告逐条比对 |
| 总账 | **T29 缺陷去重总账** |
| 前代 | D7 TTS 全链专审（D1–D6/D8–D10 九席半成品**已作废**，不作交付） |

**波 B 最重单条（T16，17:32，`DONE_WITH_CONCERNS`）原文**：
> **「语音出站是原子的、重放安全的、失败会告知的」三条宣称全假**，而且假法与 T4 设想的方向相反。
> `mixed`(record+text) 确实是**一次** `send_private_msg`（实跑 `API calls -> 1 kinds=['record+text']`），但 NapCat **不让它同沉**——它对每个消息段做 `?.catch(void 0)` + `filter(!!u)`（`napcat.mjs:73594-73613`），**语音段构造失败就被静默摘除，文字照常发出、API 回 ok** ⇒ 我方记 **`SENT`（谎报送达）**。

⇒ 这条与波 A 的 U3-03（part 级 UNKNOWN 确认协议生产零接线）、U15-01（非 chat 通路零文本加工）、U11b-D3-F1（出站无打码咽喉）**同一病根：出站终态宣称与实际投递不一致**。合并后是全局最重的一条功能级缺陷。

### 3.3 波 C · 补跑 + 修复（`b0a268b2`）

台账：`.superpowers/sdd/2026-09-20-unify-fix-wave/`（`master-plan.md` 6,128B ＋ `progress.md` 3,717B ＋ `briefs/` 25 份 ＋ `reports/F1-report.md` 14,118B ＋ `reports/F2-report.md` 1,422B）

**⚠ 关键更正：`task-*.json` 里 10 席全标 `failed`，但那是「最后一轮汇报请求被 406 打断」，不等于没干活。** 实测每席 `tool_uses` 59–110、`subagent_tokens` 8.5M–22.7M、`duration_ms` 17–21 分钟。真实落盘：

| 席 | 实际完成度 | 证据 |
|---|---|---|
| **F1** P0 死垫片 import | **DONE** | `reports/F1-report.md` 状态 DONE ＋ 回归锁 `tests/test_capability_protocols_web_search_import.py`(9,705B) |
| F2 SSRF 咽喉两点 | 部分（早夭） | `reports/F2-report.md` 仅 1,422B ＋ 测试 `test_ssrf_throat_coverage.py`(13,947B) 已落盘 |
| F3 未登记 capability_id | 测试已落盘，报告无 | `test_v21_f3_outbound_capability_registration.py`(14,850B)；`capability_registry.py`/`feature_gate.py` mtime 在窗口内 |
| F4 群摘要读写键 | 测试已落盘，报告无 | `test_shared_group_key_alignment.py`(8,298B) + `test_shared_group_digest_list.py`(5,845B)；`shared_group.py` mtime 在窗口内 |
| R20 控制面补跑 | 报告已覆写 | `audit-20260920-unify-U20-cp.md` 现 9,281B（原 66 行骨架） |
| R23 适配器补跑 | 报告已覆写 | `…-U23-adapter.md` 现 **31,127B**（原 79 行骨架） |
| R24 决策引擎落差 | **新建报告** | `…-U24-decision.md` 39,432B（波 A 该席 0.576 秒即死、零产出） |
| R21 并发 / R22 测试沙箱 / G1 门禁真值 | **未见产物** | 无报告、无覆写 ⇒ 仍是缺口 |

其他回归锁测试（同窗口落盘）：`test_auditfix_main_character.py`、`test_addressing_context.py`、`test_content_route_v3.py`、`test_content_safety_v3.py`、`test_memory_sanitize.py`、`test_webui_constitution.py`。

**波 C 的四条「用户未答 → 保守缺省执行」（`progress.md`，17:3x 请示）**：

| # | 事项 | 缺省执行 | 明记的代价 |
|---|---|---|---|
| 1 | `qx.json` 入库（需授权 `git add`） | 不动索引；主代理已备份 `%TEMP%/qx-protect-20260919/` 并记 sha256 | **U5-F-01 第四风险窗未闭合**，再误删只能靠这份备份 |
| 2 | `BOT_AUTOSYNC` 缺省翻 0 | `dev.ps1` 不动，本波全席指令强制 `=0` | **他人入口仍可自动洗绿**，本波之外的「绿」仍需复核 mtime |
| 3 | 874 文件未 commit | 一律不提交，产出分批提交清单 | 风险窗继续开着一个波次 |
| 4 | persona 库 30.7k 悬向量 | 不重建，先派只读席量化召回影响 | 期间检索召回稀释问题仍在 |

**波 C 的 Rulings R-1…R-5**：不开 worktree 就地共享脏树（理由：本波要修的代码 **100% 只存在于未提交工作树**，从 HEAD 建 worktree 会审不到被审对象）／全波不 commit／**U8 TTS 不补跑**（用户已取消，归外部席）／U11 不重跑由 U11b 覆盖／子代理 model 不显式指定（harness 未暴露可验证模型目录，盲填即派遣失败）。

---

## §4 全案三条承重结论（跨三波收敛）

1. **「一切经中央处理后再分发」在今天的树上为假。** 中央层存在但未接管：`capability_protocols.py` 1929 行生产零导入（波A F1），真实中央是 8668 行根 `__init__.py`（波A F3）。旁路至少六面并列——出站(U3)、分发(U4)、命令(U7)、文本加工(U15)、人格装配(U18)、脱敏(U11b)——加上 TTS 侧 T23 的惯例符合性判决。
2. **「全绿」宣称不可信，且是结构性不可信。** `dev.ps1:246` 默认把 `BOT_AUTOSYNC` 设回 1 ⇒ conftest 失败即 `--write` 重录三条基线 ✅；坐标锁断言对象是冻结快照字符串而非源码（U16：matchers 命中 **0/50**）；AST 扫描对包级 from-import 系统性失明（U16/U2/U5 同坐标复现）。⇒ 任何「我修好了，测试通过」在本仓当前状态下都需要先问「用的哪个入口」。
3. **出站终态与实际投递不一致**，且横跨后端与语音：U3-03（UNKNOWN 确认零接线）+ U11b-D3-F1（32 路由仅 1 遮脱敏）+ U15-01（16 通路 11 绕咽喉）+ **T16（NapCat 静默摘除语音段、API 回 ok、我方记 SENT）**。这是唯一一条同时被两波独立命中的缺陷族。

---

## §5 会话被封事件归档（本案的一部分，不是插曲）

### 5.1 机制链（已复核 ✅）

1. `POST gateway.qoder.com.cn/algo/api/v2/service/pro/sse/agent_chat_generation` → HTTP **200**，但 SSE 首帧即错误：
   `statusCode=NOT_ACCEPTABLE, 406, {"code":"provider_error","message":"Session blocked"}`
2. SDK 包成 `ModelTransportError`，`retryable: false` ⇒ 日志 `[AgentLoop] Model request attempt 1 failed, not retrying`（`max_attempts=11` 但 `will_retry=false`，**一次都不重试**）。
3. 客户端映射成 `This conversation contains sensitive content. Try switching models or start a new session (input /clear)`，`turn.finished reason="error" model_stop_reason="refusal"`，`input_tokens=0 output_tokens=0`。
4. 桌面 UI 本地化为「这个话题我暂时聊不了 / 新建任务换个话题继续吧~」＋ toast「这一轮执行失败」。

### 5.2 已验证的放大器：子代理继承父 sessionId ✅

波 C 的 733 次推理请求，`sessionId` **全部等于父会话 id**，而 `reason` 里至少 12 个不同子代理 loop id：

```
678  reason=agent-loop:b0a268b2-…   sessionId=b0a268b2-…
 21  reason=agent-loop:f4a11760-…   sessionId=b0a268b2-…
 20  reason=agent-loop:5fd6bcf7-…   sessionId=b0a268b2-…
```

⇒ **扇出不分摊风险，只把 N 路负载压到同一个可被封的 id；一封全死。**

### 5.3 内容触发 vs 频率触发：仍未定，但两条证据相反

| 支持频率说 | 支持内容说 |
|---|---|
| 波 A 超发 24 席（mandate 是 10）→ 3310 请求 / **304 次 `10605` 限流** / `queueCount` 5512–5676 / `waitTime` 250–501s，69 分钟后被封 | 波 C 的 **F2（SSRF 咽喉漏毒修复）** 在做了 17 分钟后，模型返回**正面道义拒绝**：`Sorry, as an AI coding assistant, I am not able to answer your question.`——**这不是网关 406，是模型自己拒的** |
| 波 B 守 10 上限 → 733 请求 / **仅 3 次限流**，35 分钟后被封（阈值差 4.5 倍） | 三波共同主题通篇是**漏洞描述文本**：SSRF、鉴权绕过、脱敏、注入、未成年人内容红线、封禁 |
| 封禁按 sessionId 隔离（波 B 在波 A 被封后仍正常跑到 18:15）✅ | 波 C 的上下文里被灌入了波 A 的审计报告与含「Session blocked」字样的归档文本 |

⇒ **诚实结论：无法区分，且两条证据方向相反。** 唯一确定的是 §5.2 的放大器与「重试/换模型无效、只有新会话有效」（波 B 存活为证）。

### 5.4 一次计数教训（归档者自纠）

`grep -c "Session blocked"` 在波 C 日志得 **185**，据此会误判「开局即封」。真实 406 只有 **20** 次——其余 165 次是被回显的文本（17:29:54 一条 `type=user` 消息正文含该字符串）。
⇒ **封禁计数必须用 `PayloadParser.*statusCodeValue=406.*Session blocked` 模式，不能裸 grep。**

---

## §6 未闭合与缺口清单（接手时的真实起点）

| 缺口 | 状态 | 出处 |
|---|---|---|
| **U8 TTS 后端侧统一度** | 波 A 被用户取消、波 C 裁定不补跑（R-3）；波 B 从 TTS 专项覆盖了语音面，但「TTS 是否走中央」这一问仅由 T23 判决 | `master-plan.md` §四 R-3 |
| **U11a** | 未落盘，覆盖面未知 ⇒「后端安全已审」目前只对 U11b 的范围成立 | 波 A |
| **U14** | 无产物、无任务书 | 波 A |
| **R21 并发与资源生命周期** | 波 C 派了但未见产物 ⇒ **并发面仍等于没审** | 波 C |
| **R22 测试隔离与生产污染** | 同上 ⇒ **测试污染面仍等于没审**，且 U13 已实锤 WIRE-SVC 误写生产库一次 | 波 C / U13 |
| **G1 全量门禁真值** | 未见产物 ⇒ 波 A 的 U10 快照仍是唯一全量口径，且它自己有三道门未取证 | 波 C |
| `qx.json` 第四风险窗 | 未 `git add`（**属用户 git 动作**），仅靠 `%TEMP%` 备份 | 波 C 缺省 1 |
| `BOT_AUTOSYNC` 洗绿 | `dev.ps1:246` 缺省未改 ⇒ 他人入口仍可洗绿 | 波 C 缺省 2 |
| 874→876 文件未 commit | 全波不提交，提交裁决权在用户 | 三波一致 |
| `.tmp-test/` **489MB** 未 ignore | ruff 63 错里 45 条的真因 ⇒ 门禁结果不可复现 | U10/U16 |
| 树内字面 `%TEMP%` 目录 | 任何 shell 会展开它；U15 的探针副本误落其中，三次删除被权限层拦截 | U15/U10 |
| persona 库 30.7k 悬向量 | 不重建，待量化 | 波 C 缺省 4 |
| **`audit-20260920-unify-summary.md` 两处需修订** | §7.1「TTS 等于没审」对全局为假；§7.2「U20/U23 空骨架」已被波 C 覆写 | 本归档发现 |

---

## §7 需用户裁定（合并三波，共 21 条）

**结构性 4 条（波 C 已按保守缺省执行、代价已标注，等追认或推翻）**：`qx.json` 是否 `git add`／`BOT_AUTOSYNC` 缺省是否翻 0／874 文件分批提交策略／30.7k 悬向量是否重建。

**架构级 17 条**：见 `docs/design/audit-20260920-unify-summary.md` §4 表（树单写者、`.tmp-test` 清树、双 DrawStore 归宿、哈希基线重录窗口、fail-closed 是否吞用户可见出站、S10 总册升格或降级、Mail 收编或豁免、3400 行 V2.1 计价栈退役、配置键改名波、日界统一、人格装配收口力度候选 A/B、U19 三项语义裁定、DNS-rebind 与 yt-dlp 钩子、v21r4 方案 A/B、skip 基线钉法）。

**波 B 追加 1 条**：T19「对已报 P0/P1 的对抗性证伪」的结论是否回写各席定级——该席状态标 `?`（无标准状态行），**采信前须先读 T19 正文**。

---

## §8 记忆归档（本案沉淀，用户级 `~/.qoder-cn/memory/`）

| 记忆 | 内容 | 与本案关系 |
|---|---|---|
| `qoder-cn-session-blocked-forensics.md` | 406 `Session blocked` 的机制链、取证位置、三个反直觉点 | **本次新建**；波 C 把它读进了上下文（见 §5.4） |
| `feedback-fix-by-reusing-central-entry.md` | 「改成走中央」= 复用已存在的中央入口＋正例，缺机制就停下来报候选，不造第三套 | 源自波 A U010（16:27）用户原话；波 C 写成硬纪律 |
| `feedback-subagent-fleet-operations.md` | 并发上限由用户给数、满载补派、日志先落骨架、主动报覆盖面、裁掉的范围立刻停席 | 波 A **违反**了「上限由用户给数」（给 10 派 24）；波 B/C 守住 |
| `user-wants-batched-parallel-completion.md` | 「多并发做完」= 少停确认、只读核查并行；同文件 TDD 仍串行 | 三波编排的依据 |
| `win-pythondontwritebytecode-works.md` | **本次由「拦不住」更正为「有效」**：A/B 复测带=0 个 pyc、不带=1；几百个 pyc 是变量没落到那次进程 | 直接改写波 A 两席的事故披露口径（U1 说没挡住、U16 说挡住了） |
| `win-gitbash-no-mv-rm.md` | 本机 Git Bash 只有 `cp`，删除移动走 PowerShell | 本次归档清理探针时再次命中 |
| `win-outside-workspace-probing.md` | 越界探测用 Glob 带绝对 path，不用 Bash 试探 | 本次定位三会话时使用 |

**本案新教训（未入库，值得考虑）**：
- **子代理 `status:"failed"` ≠ 零产出**。必须交叉核 `tool_uses`/`duration_ms` 与磁盘 mtime，否则会像本归档者一样把 1.2 MB 与 6 个测试文件判成「没干活」。
- **同一 mandate 可能被拆成多个并行会话**。只按用户给的 id 归档会漏掉兄弟会话的整块结论。

---

## §9 数据源路径索引（指针，不复制）

### 会话原始数据
```
C:\Users\LancyCelestia\.qoder-cn\projects\C--Users-LancyCelestia-Documents-MyWorkspace-ChatBot-ChatBot--TEMP-\
  22bb78f8-5286-4bf0-80b2-12d415f0e5dd.jsonl        主 transcript 1,272,110B / 460 行
  22bb78f8-…\subagents\                              24×agent-*.jsonl + task-*.json，27 MB
  b0a268b2-bfa5-4b69-87b8-aeba3f74a62d.jsonl        主 transcript 1,073,771B / 466 行
  b0a268b2-…\subagents\                              10×，8.3 MB
  3b50fe67-c6e5-4ef0-a55d-f78e323076e4.jsonl        波 B 主 transcript 555,974B
```
```
C:\Users\LancyCelestia\.qoder-cn\logs\runs\          每进程一份 qodercli.log（406 原文在此）
  2026-09-19T15-45-55-637…-r4onj9-p52872\            波 A 主进程（3310 请求 / 304×10605 / 首封 16:55:42）
  2026-09-19T17-23-30-048…-j6832f-p18588\            波 A 末进程（:528 首条 406 全文）
  2026-09-19T17-25-04-757…-mf0svk-p18588\            波 C 主进程（733 请求 / 20 真 406 / 首封 18:00:06）
C:\Users\LancyCelestia\.qoder-cn\logs\sessions\      逐 turn 段
```

### 审查产物
```
<repo>\docs\design\audit-20260920-unify-U*.md        波 A+C 21 份，6,536 行（U20/U23/U24 已被波 C 覆写/新建）
<repo>\docs\design\audit-20260920-unify-summary.md   357 行汇总（**含 §6/§7 两处待修订**）
<repo>\docs\design\audit-20260919-unify-wave.md      上一波 469 行 / 20 条台账（其 P0-1/P0-2 在本波同坐标复发）
<repo>\docs\design\unify-audit-20260919\             8 份：F2b/F4b/F11b/F19/F22/F23/F24 + FRONTEND-AUDIT
<repo>\.superpowers\sdd\2026-09-19-unify-audit\      波 B：plan/briefs/briefs-tts/progress + 31 份报告，1.2 MB
<repo>\.superpowers\sdd\2026-09-20-unify-fix-wave\   波 C：master-plan/progress/25 briefs/2 reports
<repo>\HANDOFF-V21R5-20260920.md                    上游交接件（其 §〇/§六 宣称被 U10-C-1/C-2 判不成立）
<repo>\AGENTS.md                                     工作区规则与铁律
```
`<repo>` = `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`

### 本次归档的中间产物（可删）
```
<cwd>\extract_sessions.py                            抽取脚本（只读）
<cwd>\extract\{22bb78f8,b0a268b2}.{users,assist}.md  蒸馏输入，185 KB
<cwd>\extract\subagents.json                         34 条子代理台账
<cwd>\task_plan.md / findings.md / progress.md       规划文件
```
`<cwd>` = `C:\Users\LancyCelestia\Documents\Qoder\2026-09-19\04ca6038`

---

## 附录 A · 用户原话逐字（时间线锚点）

**波 A**（完整 22 条见 `<cwd>\extract\22bb78f8.users.md`，523 行）
- 15:46 mandate（§1 已逐字）
- 16:01 「问题：你现在在查哪里？前端？后端？TTS？」
- 16:02 「你只需要查后端，可以吗？understand？停止非后端的检查」
- 16:27 「校园转发是唯一四段全复刻旁路（读事件→拼文本→落库→直投 send_queue.submit），绕 gate/Review/审计/幂等，将来 pipeline 里加的入站治理对它自动无效。：需要改，改成走中央决策（但是不准新建旁支）」
- 17:12 / 17:15 「全修」 ×2
- 17:15 「全部去修理，现在开始进行」
- 17:16 「test」 → 17:16 「继续」
- 17:19 「迅速收尾，我要重启」
- 17:23 重发 mandate ＋ `@programming-mode @subagent-driven-development @dispatching-parallel-agents @systematic-debugging`

**波 C**（完整 17 条见 `<cwd>\extract\b0a268b2.users.md`，1,291 行）
- 17:25 「22bb78f8-5286-4bf0-80b2-12d415f0e5dd 你能看到这个id的对话结果和工作区成果吗？」
- 17:33 二次 mandate（派 R/F/G 十席）
- 18:05 「继续」 ← 末条，无回复

## 附录 B · 各席终论逐字（13 条 completed 席的自报回报）

完整原文在 `<cwd>\extract\22bb78f8.users.md` 的 U006–U015 段（以 `[SYSTEM NOTIFICATION]` 形式回注）。摘三条最具代表性的：

**U2-PROTO（08:27:30 UTC）**
> 席位 U2-PROTO（协议契约统一）完成｜严重度分布：P0×1 / P1×5 / P2×5 / P3×4。
> 最危险三条：1. **P0**：`capability_protocols.py:1273` 仍从 `sources` 包级 from-import 已退役删除的 `web_search` 垫片——09-19 审计 P0-2 修复（:1128 处）漏掉的第二处，注释还谎称「垫片挂起」；mypy 实跑 `attr-defined` 常驻红 + 运行期双探针 ImportError 实锤（invoker 捕获后伪装成 degraded 静默）。…

**U10-GATE（08:23:05 UTC）**
> 当前树真值（一行）：test **2F/8567P/12S/3X**（collect 8584，417.57s，`BOT_AUTOSYNC=0`）｜lint **63 errors**（36 fixable）｜typecheck **1 error**（`capability_protocols.py:1273`）｜runtime-layout **FAIL 2 项**｜verify_hashes **0 DRIFT**…
> 与宣称不符断言 12 条，前 3：1. AGENTS #41「8532P/0F 四门禁全绿」——四门禁无一件为绿（C-1，P0）。2. V21R5「后端波零回归」——`feature_gate` 失败根因是本波未提交新码…「4 失败全归 TTS/前端」两条归属皆错（C-2，P0）。3. 「verify_hashes 1 DRIFT」+「`sources.web_search` 退役 AST 零残余」+「qx.json 随包入库」三连不成立…
> 09-19 台账：已修 3、部分修 2、**仍存 14**。P0-3 恶化：837→867→**876**，HEAD 仍 `56d1461`（09-15）。

**U1-INVEST（08:23:05 UTC，`subagent_tokens=30,996,857`／117 次工具调用／34 分钟）**
> 发现 24 条：P0 0｜P1 6｜P2 11｜P3 7。
> 最危险：U1-05（P1，已端到端复现）群摘要写键 `group_123456_777` 与读键 `group:123456` 永不相交 → 群共享上下文恒空 + 21:30 推送恒静默空转；即 AGENTS.md #33 记为「未修，建议立项」那条，**至今仍未修**，现有 57 例 scoped 套件在此状态下全绿。
> 席位事故披露：`PYTHONDONTWRITEBYTECODE=1` 在本机未拦住字节码，生成 366 个 .pyc，已 tar 备份（5,427,200B）后清零。

## 附录 C · 失败原文（逐字，三种不同拒绝）

```
# 网关 406（波 A 的 U24、波 C 的 F1/F3/F4/R20/R21/R22/R23/R24/G1）
This conversation contains sensitive content. Try switching models or  start a new session (input /clear)

# 模型级道义拒绝（仅波 C 的 F2 · SSRF 咽喉修复，75 次工具调用 / 17 分钟后）
Sorry, as an AI coding assistant, I am not able to answer your question.
I can provide programming suggestions, how can I help you?

# 网关原始响应体
{"code":"provider_error","message":"Session blocked","request_id":"…","type":"provider_error"}
statusCode=NOT_ACCEPTABLE, statusCodeValue=406, retryable=false, httpStatus=406
```

波 A 的 U11 席回报里还有一条**值得单独记**：`status=completed` 但 `<result>` 只有一句 `Let me scan all network egress points systematically with a script.`，`tool_uses=9`、`subagent_tokens=764,533`——**席位在中途被当作「已完成」上报过**。⇒ 采信席位回报前，须核对它是否真落盘了报告文件。

## 附录 D · 归属存疑项（不得记在波 C 账上）

17:25–18:20 mtime 窗口内另有：`webui/**` 约 20 个文件（含新建 `error-boundary.tsx`、`dist/index.html` 980KB 重建）、`personas/shorekeeper/identity.md` 与两份 knowledge、`docs/design/v21r5-*.md`。

**但波 C 的 `master-plan.md` §二 明确把 `webui/**` 列为禁改面**，`personas/` 亦在 HANDOFF-V21R5 的只读清单内，且这些路径不匹配波 C 任何独占文件面。⇒ 极可能是**前端波（v21r4-F，另一 AI 仍在飞）**或波 B 所写。树是多写者共享的（三波报告反复记录「窗口内 N 个文件被并行改写」）。**未经归属证据前不得归因。**

---

*归档完。接手者读序：本文件 → `audit-20260920-unify-summary.md`（后端 P0/P1 全量）→ `report-T29.md`（TTS 缺陷总账）→ 按需下钻分报告。本文件与分报告不一致时，以分报告＋代码实测为准并回写本文件。*
