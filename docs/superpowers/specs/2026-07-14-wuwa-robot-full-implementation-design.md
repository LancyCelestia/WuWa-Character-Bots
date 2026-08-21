# WuWa 角色机器人全量落地设计规格

> 日期：2026-07-15
>
> 状态：用户已复核并批准；已纳入通用角色包、动态关系、永久群归档与多平台能力矩阵
>
> 适用范围：`plugins/wuwa_unified_runtime/`、配套测试、迁移、运行脚本与运维界面
>
> 权威来源：仓库根文档、`docs/specs/`、角色档案、研究结论及当前代码行为；本文定义后续实现的目标契约

## 0. 一页摘要

本项目不是只做一个守岸人聊天插件，而是建设一个可扩展的角色机器人运行时：鸣潮角色是第一批角色包，后续可以接入其他鸣潮角色和其他 IP，且不需要重写投递、记忆、知识、媒体或运维基础设施。

用户已确认的产品方向：

- 角色采用通用 `UniversePack + CharacterPack` 注册接口；守岸人、爱弥斯、菲比只是首批实现。
- 机器人根据明确自述、称呼偏好、对话内容和长期互动形成可纠正的用户呈现提示与好感度，但不把说话风格刻板地断言为性别事实。
- 关系可从陌生、熟悉发展为好友、亲密朋友、闺蜜或同伴；伴侣分支必须有明确且持续的用户信号，不能只靠分数自动认定。
- 所有关系模式保持克制、中立，不说露骨内容，不主动撒狗粮，不表现占有、嫉妒或情感绑架；群聊不公开私人好感度或关系状态。
- 群归档逐群启用后默认永久保留文字、链接和消息结构，并从原始记录中提炼可追溯的群级长期记忆；不自动下载大型媒体文件。
- 自动发送必须预览和确认，高风险路径增加管理员确认。
- 平台适配以能力矩阵覆盖国内常用社交、视频、直播、动态、商城、音乐和游戏百科；优先官方/公开接口，并通过缓存、限流、重试、浏览器降级和结构漂移检测提高稳定性，不绕过验证码、登录墙或访问控制。
- 实施顺序仍为 M1 投递正确性、M2 通用角色/人格知识、M3 用户能力、M4 自动化、M5 真实投递与运维。

## 1. 目标与成功定义

本项目要在保留现有统一运行时契约的前提下，把仓库中已经描述但尚未完整落地的角色机器人能力实现为可运行、可迁移、可审计、可验证的生产级系统，并把鸣潮特有内容封装为可替换角色/IP 包。

成功不以“存在类或接口”为准，而以行为证据为准：

- 用户消息从统一入口进入，所有真实投递都经过同一个 `DeliveryCoordinator`。
- 守岸人、爱弥斯、菲比及未来其他 IP 角色的人格、历史、记忆与关系状态不会串用。
- 本地百科按文章检索并提供安全引用，不能因为“召回到文本”就假装答案可靠。
- Wiki、媒体、群总结、天气、告警、订阅和自动发送均遵守权限、隐私、确认、安静时间和投递策略。
- SQLite 并发、重启、租约过期、容量不足和外部超时都有明确且可观察的状态。
- 本地单元/集成测试、真实启动烟测、在线只读验证和真实授权投递被明确区分，任何一层都不能替代另一层。
- 文档、配置、迁移与代码保持兼容；旧部署不会因新字段缺失而被静默误路由。

## 2. 已知基线、事实与边界

### 2.1 当前事实

- 当前核心链路是 `IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord`。
- M0 已具备聊天、人格/知识文档、记忆、历史、情绪、权限、注入防护、回复预算、限速、安静时间、诊断、审计、持久队列和 OneBot transport 等基础能力，但部分语义仍未贯通。
- 当前唯一实际启用人格是守岸人；爱弥斯与菲比只有资料，没有安全的会话绑定和数据隔离。
- 当前百科文件约 59,014 行；本次审计的版本包含 3,521 个目录项，目录到第 3,531 行结束，正文从第 3,533 行开始。
- `守岸人.txt` 与 `守岸人档案.md` 内容指纹相同，摄取时必须去重。
- 当前环境声明了 `nonebot_plugin_htmlkit`，但无法成功导入；在全新环境验证通过前，图片渲染只能视为可选后端，文本降级是强制路径。
- 真实 LLM、真实 NapCat/QQ 投递和某些在线来源依赖外部凭据或运行环境，本地测试不能替代这些验证。

### 2.2 工作区边界

- 当前工作树包含大量用户未提交的 M0 代码与文档，它们是本设计的真实基线。
- 实施不得 reset、clean、revert、覆盖或顺带提交这些基线变更。
- 每个实施任务只修改任务明确列出的文件；暂存和提交前必须逐文件核对。
- 设计优先使用增量、可回滚迁移，不以重写现有运行时为手段。

### 2.3 设计优先级

发生冲突时使用以下顺序：

1. 正确性。
2. 安全与隐私。
3. 兼容性与可维护性。
4. 简单性。
5. 性能。

## 3. 总体架构

目标系统保持现有契约链，但把“计划”和“副作用”严格分开：

```text
Adapter Event
  -> IncomingMessage Normalizer
  -> Policy / Permission / Rate / Quiet-Hours Gate
  -> BotDecision (persona_profile_id is authoritative)
  -> Capability (pure intent/result, no transport)
  -> Output Review
  -> Deterministic Render
  -> DispatchPlan
  -> DeliveryCoordinator
       -> durable queue / claim / lease fencing
       -> route registry / kill-switch recheck
       -> transport adapter
       -> receipt repository / delivery audit
```

辅助服务通过显式协议接入：

- `UniverseRegistry`、`PersonaRegistry`、`PersonaResolver`、`CharacterContextProvider`
- `KnowledgeProvider`、`PlatformSourceAdapter`、`GroupMessageArchive`、`GroupMemoryConsolidator`
- `WeatherProvider`、`OfficialAlertProvider`
- `AutoSendRepository`、`SubscriptionRepository`、`KillSwitchRepository`
- `TransportRegistry`、`ReceiptRepository`、`AuditLogger`

以下层禁止直接调用 OneBot、NapCat、邮件或任意外部发送 API：

- capability
- persona / knowledge / memory / history
- parser / source adapter
- renderer
- scheduler / watcher

它们只能生成结构化结果、状态转换请求或 `DispatchPlan`。

## 4. 里程碑与交付顺序

| 里程碑 | 核心交付 | 进入条件 | 完成条件 |
| --- | --- | --- | --- |
| M1 | 运行时安全修复、`DeliveryCoordinator`、路由与队列 fencing | 当前 M0 门禁可复现 | 所有真实发送只有一个所有者，handler/并发/多 bot 测试通过 |
| M2 | B1 守岸人人格注册与文章级知识；B2 三角色隔离与切换；通用角色/IP 包接口 | M1 投递语义稳定 | 首批三角色及跨 IP fixture 的人格、历史、记忆、关系和引用不串用 |
| M3 | Wiki、媒体卡片、群总结、天气查询与官方告警规范化 | M2 知识和审查可复用 | 每项能力有确定性 fallback、权限/隐私和来源证据 |
| M4 | 自动发送、告警/内容订阅、cursor、digest、持久 kill switch | M1 协调器和 M3 source 可用 | durable 状态机及 standing authorization 经重启/竞争/失败测试 |
| M5 | 真实 transport 验证和认证运维 UI | M1-M4 状态可观察 | 真实验证等级可区分，UI 安全边界和浏览器测试通过 |

不得为了展示后续能力而跳过前置里程碑。例如，三角色切换不能先于 persona-aware 历史与记忆迁移，自动发送不能先于 durable 确认状态机。

## 5. M1：运行时正确性与唯一投递协调器

### 5.1 先行安全修复

在引入协调器前先以小任务修复以下独立问题：

- `/wuwa why` 与其他管理诊断命令使用统一角色/权限检查，不能只凭命令可达就泄漏诊断信息。
- 所有 handler、帮助文本、路由器和被动群聊判断使用同一动态命令前缀配置，不保留硬编码 `/wuwa` 分支。
- 群聊上下文只投影群作用域或明确允许的公共事实；个人记忆不能因为同一 sender 出现在群里而注入。
- 记忆写入命令拆为“解析计划 -> 权限/隐私审查 -> 提交副作用”；审查阻断时数据库零写入。
- readiness/doctor 在已有事件循环中不得调用 `asyncio.run()`；同步和异步入口分别提供明确 API。
- NoneBot handler 集成测试必须覆盖真实 matcher 回调到 `DispatchPlan` 的路径，不能只测内部 helper。
- `scripts/dev.ps1 verify` 的缺依赖、跳过项和失败都必须可见；全新虚拟环境安装后门禁可复现。
- 依赖必须由提交到仓库的锁定或约束文件复现；可选依赖缺失只能使对应能力明确 not-ready，不能让验证脚本静默跳过。

### 5.2 `DispatchPlan`

运行时 pipeline 的终点从“提交发送”改为生成不可变计划。建议内部模型如下：

- `DispatchPlan`
  - `request_id`
  - `capability_id`
  - `persona_profile_id`
  - `origin_route`：`platform/adapter/bot_id/session_id/message_id`
  - `items: tuple[DispatchItem, ...]`
  - `audit_events: tuple[PlannedAuditEvent, ...]`
  - `created_at`
  - `decision_hash`
- `DispatchItem`
  - `dispatch_id`
  - `content`
  - `directive`
  - `target`
  - `dedupe_key`
  - `cooldown_key`
  - `expires_at`
  - `depends_on_dispatch_id`
- `DeliveryDirective`
  - `timing`：immediate、queued、digest
  - `target_mode`：current、private_actor、admin、explicit
  - `approval`：none、actor、admin、actor_and_admin
  - `visibility`：normal、redirect_notice
- `PlannedAuditEvent`
  - `event_id`
  - `stage/event/severity`
  - `public_message`
  - `redacted_debug`
  - `dedupe_key`

对外继续接受现有 `SendPolicy`，在单一映射函数中转换为内部 directive：

| 现有策略 | 内部语义 |
| --- | --- |
| `IMMEDIATE` | immediate + current + none + normal |
| `QUEUED` | queued + current + none + normal |
| `DIGEST` | digest + current + none + normal；digest 服务未启用时明确 hold |
| `PRIVATE_FALLBACK` | primary：immediate + private_actor + none + normal；可选 notice：immediate + current + none + redirect_notice，并依赖 primary |
| `ADMIN_CONFIRM` | queued + 保留已经解析出的 target mode + admin + normal |
| `SILENT_AUDIT` | plan-level audit event；不生成 `DeliveryDirective` 或 transport item |

策略映射不得散落在 pipeline、handler、worker 或 transport 中。

`SILENT_AUDIT` 的计划可以有零个 `items`，但必须至少有一个 audit event。coordinator 对空投递计划持久化事件并返回 `ReceiptState.SKIPPED`、`transport=audit-only` 的幂等回执；pipeline 不直接写 delivery audit。

### 5.3 通用审批契约

M1 提供可供 `ADMIN_CONFIRM`、私聊敏感操作及后续自动发送复用的通用审批仓库。审批不是进程内布尔值。

`ApprovalRecord` 至少包含：

- `approval_id`、`dispatch_id`、`request_id`
- `approval_kind`：actor 或 admin
- `required_subject_id` 或 required role
- `payload_hash`、`version`
- `state`：pending、approved、rejected、cancelled、expired
- `expires_at`、`acted_at`、`acted_by`
- `reason` 与审计 metadata

流程：

1. coordinator 持久化 dispatch item 与全部所需 approval records，并把 item 置为 `held_approval`。
2. 确认命令或运维 API 必须认证操作者，并提交 approval id、version 和 payload hash。
3. repository 使用 `state=pending AND version=? AND payload_hash=?` 条件更新；重复确认返回原结果。
4. 全部所需审批通过后，只更新 approval 前置条件并调用 `EligibilityEvaluator`；只有不存在其他 hold reason 时才恢复 `resume_state`。
5. 任一审批拒绝或取消时，item 转为 `cancelled`；审批过期时转为 `expired`。
6. 内容、目标、人格、渠道或风险发生变化时生成新 version，旧审批全部失效，不能沿用。

审批 hold 不增加 transport attempt count。审批操作、过期和释放均写入脱敏审计。

### 5.4 `DeliveryCoordinator` 所有权

`DeliveryCoordinator` 是以下动作的唯一所有者：

- 写入与更新 durable queue。
- claim、lease、重试和终态转换。
- transport 路由与调用。
- 写入 `DeliveryReceipt`。
- 写入 delivery-stage audit。
- 在 transport 前二次检查持久 kill switch。

其他组件的边界：

- pipeline：只返回 `DispatchPlan`。
- handler：只调用 coordinator 并结束框架回调；业务正文、错误提示和重定向提示均不得通过 `matcher.finish`、`event.send` 或 bot API 旁路发送。
- scheduler/watcher：只生成待投递计划，不选择在线 bot。
- queue repository：只持久化和执行条件更新，不决定业务策略。
- transport adapter：只执行一个已路由的 `SendRequest`，不修改队列。

为兼容已有调用方，可保留 `RuntimePipeline.handle()` 包装，但它必须内部调用 `plan()` 和 coordinator；任何旁路发送都视为缺陷。

### 5.5 即时与排队统一路径

即时发送也必须经过以下流程：

1. 持久化 queue row。
2. 获取带随机 `lease_token` 的 claim。
3. 校验租约仍有效、路由可用、kill switch 未开启。
4. 调用 transport。
5. 使用 `state=processing AND lease_token=?` 条件更新终态。
6. 持久化 receipt 与 audit。

这样可以避免 handler 即时发送与 worker 同时发送同一请求。内存队列只允许用于明确的测试替身，生产配置必须可识别并报告其非持久属性。

### 5.6 私聊回退

`ReviewAction.MOVE_PRIVATE` 或 `SendPolicy.PRIVATE_FALLBACK` 最多产生两个 item：

1. private primary：正文，仅发给原发起者可验证的私聊目标。
2. group redirect notice：无敏感内容的固定短提示，依赖 primary 成功。

规则：

- 无法确定私聊目标时，不猜测账号；主项进入明确阻断/hold 状态。
- primary 只有在 transport 明确接受并产生 `SENT` 回执后，notice 才可 claim。
- `delivery_unknown`、失败或过期时不发送 notice。
- notice 失败不重发 primary。
- 两个 item 使用不同 dedupe key，共享 correlation/request id。
- notice 不得包含正文摘要、目标私聊账号或触发隐私审查的字段。

### 5.7 bot 与 transport 路由

`SendRequest` 增加带兼容默认值的 `platform`、`adapter`、`bot_id`。所有新请求必须显式填充；旧 JSON 仍可读取。

路由键为：

```text
(platform, adapter, bot_id, target_scope)
```

`TransportRegistry` 只接受精确匹配或经过配置声明的别名。禁止以下回退：

- 选择“第一个在线 bot”。
- 选择“唯一在线 bot”。
- 忽略 adapter 或 platform。
- 把未知旧记录绑定到当前进程账号。

旧 queue row 缺少路由时进入内部状态 `held_unroutable`，由运维界面显示并允许管理员显式修复或取消，绝不自动发送。

### 5.8 队列状态与 fencing

内部状态至少覆盖：

- 可执行：`pending`、`retry_wait`
- 已占用：`processing`
- 暂停：`held_kill_switch`、`held_unroutable`、`held_approval`、`held_dependency`、`held_digest`
- 终态：`sent`、`batched`、`skipped`、`blocked`、`failed_final`、`expired`、`cancelled`、`delivery_unknown`

持久字段至少包括：

- `lease_token`
- `lease_expires_at`
- `claimed_from_state`：本次 claim 前的 `pending` 或 `retry_wait`
- `not_before`
- `next_attempt_at`
- `transport_started_at`
- `terminal_at`
- `platform/adapter/bot_id`
- `attempt_count`
- `last_error_code`
- `content_hash` 或等价版本标识
- `hold_reasons`：全部未满足前置条件的有序集合
- `eligibility_version`
- `resume_state`：解除全部 hold 后恢复到 `pending` 或 `retry_wait`

单一 `state` 只用于索引和展示，不能作为“唯一阻断原因”。`hold_reasons` 保存全部未满足条件，`EligibilityEvaluator` 是唯一可执行性真源。它至少检查：

- 到期/取消。
- 精确 route 是否存在且 adapter 已注册；临时连接失败由 transport retry 处理，不伪装成缺 route。
- 当前 version 的 actor/admin approvals。
- `depends_on_dispatch_id` 是否达到要求终态。
- digest item 是否仍等待组装。
- 所有适用 kill switches。

每次 enqueue、审批/路由/依赖/digest/kill-switch 变化、hold 扫描以及 claim 后 transport 前都重新计算 eligibility。存在多个 hold 时全部持久化，并按 `held_kill_switch > held_unroutable > held_approval > held_dependency > held_digest` 选择展示 state；优先级不丢弃其他原因。

任何“释放”操作只更新其负责的前置条件，然后调用 evaluator；不得直接把 item 写成 `pending`。进入 held state 时保存 `resume_state`；只有 `hold_reasons` 为空且未到期时，evaluator 才恢复该状态。原本处于 `retry_wait` 的 item 保留原 `next_attempt_at`，不会因一次 hold/release 提前重试。

状态转换由下表限定：

| 当前状态 | 触发者与条件 | 下一状态 |
| --- | --- | --- |
| `pending` | worker 在 `not_before <= now` 且未过期时事务 claim | `processing` |
| `retry_wait` | worker 在 `next_attempt_at <= now` 且未过期时事务 claim | `processing` |
| `processing` | transport 成功且 lease token 匹配 | `sent` |
| `processing` | 明确可重试错误、attempt 未超限 | `retry_wait` |
| `processing` | 明确不可重试错误或 attempt 超限 | `failed_final` |
| `processing` | timeout/断线，或 transport 已开始后 lease 丢失 | `delivery_unknown` |
| `processing` | transport 尚未开始且 lease 过期 | `retry_wait` |
| 任一 held state | 对应前置条件变化后统一重算 | 另一个 held state、`pending` 或终态 |
| `held_approval` | 拒绝、取消或过期 | `cancelled` 或 `expired` |
| `held_digest` 且唯一 hold reason 为 digest | M4 digest assembler 在同一事务建立 digest dispatch | `batched` |
| `processing` 且尚未开始 transport | claim 后复检发现任意 hold reason | 对应 held state，并清除 lease |
| 任意非终态 | 明确取消或到期检查 | `cancelled` 或 `expired` |

只有 `pending` 与到期的 `retry_wait` 可被普通 transport worker claim。claim 事务必须同时写入 `claimed_from_state`；claim 后在同一 lease 下复检。复检失败且 transport 尚未开始时，以 `claimed_from_state` 更新 `resume_state`，再回到 evaluator 选择的 held state 并清除 lease。`held_digest` 只能由 digest assembler 处理；M4 未启用前保持 hold。`held_unroutable` 不因 bot 上线自动释放，只有精确 route 配置变化才触发重算。

`attempt_count` 只在 transport 调用前、与 `transport_started_at` 同一事务递增；hold/release 不增加次数。重试使用有上限的指数退避与抖动，并把计算后的 `next_attempt_at` 持久化。所有释放、取消和终态更新使用状态/version CAS。

不变量：

- claim 必须在事务内完成。
- 终态写入必须匹配当前 lease token。
- 过期 worker 的回执不能覆盖新 worker 的状态。
- prune 只能删除终态记录。
- 如果容量被非终态记录占满，enqueue 明确失败并产生可操作告警；不能删除 pending 以腾空间。
- `delivery_unknown` 表示 transport timeout 或连接中断时“可能已发送”；默认不自动重试。
- 系统只承诺 durable dedupe、单活租约与 at-least-once 处理，不宣称 OneBot 外部 exactly-once。

### 5.9 回执、错误与审计

公开回执保持现有 `ReceiptState` 兼容，内部细分状态通过错误码和审计暴露。新增公开枚举值需要单独兼容审查，不能为了内部便利直接破坏序列化消费者。

错误至少分为：

- `policy_denied`
- `approval_required`
- `unroutable`
- `kill_switch_active`
- `queue_capacity_exhausted`
- `lease_lost`
- `transport_rejected`
- `transport_retryable`
- `delivery_unknown`
- `expired`
- `internal_error`

审计记录只保留可脱敏诊断字段；正文、群归档原文、凭据和私密记忆不得进入通用 audit。

## 6. M2：人格注册、隔离与文章级知识

### 6.1 两阶段启用

#### B1：守岸人优先

B1 只启用守岸人，但先建立可扩展边界：

- typed persona manifest registry
- legacy config adapter
- default-only resolver
- profile-aware context、reviewer、fallback 和缓存
- 安全关系边界
- 结构化文档摄取与知识检索

B1 不开放 `/wuwa character`，不迁移历史/记忆 schema，不让爱弥斯或菲比对用户可选。

#### B2：三角色启用

B2 必须先完成：

- history 与 memory 的 `persona_profile_id` 作用域。
- `persona_bindings` 持久表及迁移。
- 旧数据回填到迁移时的唯一旧默认人格。
- 三角色 reviewer、fallback、关系规则和测试矩阵。

完成后才启用守岸人、爱弥斯、菲比和 `/wuwa character`。

### 6.2 Persona manifest

manifest 是运行时人格真源，至少包含：

- `universe_id`、`franchise_id`、`character_id`
- `profile_id`、`display_name`、`version`、`enabled`
- `core_identity`
- `speech_rules`
- `relationship_policy`
- `safety_overrides`
- `tone_profiles`
- `source_refs`
- `knowledge_collections`
- `fallback_templates`

`UniversePack` 定义 IP/世界观级 namespace、知识集合、命令别名、来源许可和可用 capability；`CharacterPack` 只定义角色人格、语气、关系策略、角色知识引用和素材。通用 runtime 不得导入守岸人或鸣潮专用模块。`/wuwa character` 作为鸣潮兼容入口，内部调用通用角色选择 capability；未来 IP 可以注册独立前缀或统一角色入口。

全局角色身份使用 canonical key：

```text
persona_key = universe_id + ":" + character_id + ":" + profile_id
```

- 三个 component 都是经过 schema 校验的稳定 slug，不能包含 `:`，大小写归一化后比较。
- `pack_schema_version` 定义 manifest 结构版本；`pack_version` 定义内容版本，不进入稳定 persona key。
- pack 只从配置声明的 registry roots 或显式 entry points 发现，不扫描任意工作目录。
- 两个 pack 注册同一 canonical key、同一 namespace alias 或同一命令前缀时启动失败并报告冲突来源，不能按加载顺序覆盖。
- alias 只用于输入解析，resolver 的输出永远是 canonical key。
- pack 升级保留 canonical key；删除、拆分或重命名 key 必须提供显式 migration alias 和数据迁移，不能静默新建人格。

原始 Markdown、TXT、DOCX 的职责是 provenance、lore 和可检索材料，不会因为出现“必须”“系统”“用户是漂泊者”等关键词自动升级为 system 指令。

配置优先级：

1. 显式 manifest。
2. 无 manifest 时，由旧 `BOT_PERSONA_*` / `BOT_TONE_*` 生成守岸人 legacy profile。

一旦配置了 manifest：

- 不与旧字段隐式合并。
- 旧字段存在时输出安全 warning。
- manifest 损坏时启动失败或进入明确 not-ready，不回退 legacy。

### 6.3 人格选择真源

`BotDecision.persona_profile_id` 是本次请求的人格选择唯一真源；为保持现有字段兼容，其值升级为上述全局 canonical persona key。以下组件必须使用同一个 key：

- context provider
- prompt compiler
- tone resolver
- memory/history scope
- output reviewer
- fallback renderer
- dedupe key
- `DispatchPlan` / `SendRequest`
- audit metadata

`audit_tags` 只能记录事实，不能反向改变人格。默认配置 `BOT_RUNTIME_DEFAULT_PERSONA` 必须由 resolver 实际消费。

legacy adapter 将旧值 `shorekeeper` 显式映射为配置声明的 canonical key，例如 `wuwa:shorekeeper:shorekeeper`。无法唯一映射的旧值进入 not-ready/迁移错误，不根据 display name 或列表顺序猜测。

### 6.4 绑定与作用域

`persona_bindings` 以平台、adapter、bot、会话和用户为显式作用域。推荐优先级：

1. 用户在当前私聊的绑定。
2. 群/频道明确允许的会话绑定。
3. bot 级默认人格。
4. 全局默认人格。

群级切换必须有管理员权限；私聊用户可切换自己的绑定。绑定目标必须存在且 enabled。删除或禁用 profile 时，现有绑定进入可观察的 invalid 状态，并回到已配置默认值，不默默选择列表首项。

历史与记忆键至少包含：

```text
platform / adapter / bot_id / session scope / subject_id / canonical persona_key
```

现有单人格数据在 B2 迁移时归属到迁移记录中的旧默认 profile；迁移前后数量与作用域必须可核对。

### 6.5 关系与表达边界

默认用户身份未知，不自动认定为漂泊者、特定性别、恋人、唯一伴侣或专属对象。

新增 persona-scoped `RelationshipState`：

- `presentation_hint`：unknown、feminine、masculine、neutral 或 user-defined。
- `presentation_confidence` 与可审计但不外显的 evidence provenance。
- `affinity`、`familiarity`、`trust`、`rapport`。
- `relationship_mode`：visitor、acquaintance、friend、close_friend、best_friend、companion、partner。
- `version`、`last_transition_at` 与用户可撤销/纠正标记。

持久化键与投影边界：

```text
platform / adapter / bot_id / subject_user_id / canonical persona_key / evidence_scope / scope_id
```

- `evidence_scope=private` 只由该用户与 bot 的私聊更新，私聊回复也只读取该 private state。
- `evidence_scope=group_public` 必须包含 group/channel id，只由同一群的公开互动更新；群聊只读取同一群的 public state。
- 私聊 affinity、partner/best_friend mode、私密称呼和 presentation 证据默认不投影到群聊。
- 群聊 public state 的输出关系上限为 friend/companion，并强制使用群可见中性称呼；即使 private state 是 partner，也不能通过语气、昵称或暗示泄漏。
- 群聊证据默认不提升 private relationship mode；未来若允许合并，必须由用户明确 opt-in，并记录来源群和撤销边界。
- 用户设置的 account-global 称呼偏好只有在其明确标记为 public 时才可跨 scope 使用。

呈现与性别判断规则：

- 用户明确自述、主动选择的身份或称呼偏好权重最高。
- 代词、持续自称和明确角色扮演语境可以形成中等证据。
- 名字、语气、兴趣和行为只能形成低置信提示，不能单独断言性别。
- 置信度不足时使用中性称呼；推断不能用于权限、风险、价格、推荐资格或其他实质决策。
- 用户纠正后立即覆盖旧提示，并允许查看、重置或删除相关状态。

好感度与关系转换规则：

- 分数来自持续互动、共同经历、边界尊重和明确反馈，不因付费、频繁刷消息或情绪施压而奖励。
- 使用阈值、滞回和时间证据避免一次对话突然跨级；不同角色分别计分，不能跨 persona 复制亲密度。
- friend、close_friend、best_friend 或 companion 可以随长期互动自然形成。
- partner 不能只因好感度高自动形成，必须同时存在明确、持续且可撤销的用户关系信号，并通过角色关系策略允许。
- 用户明确扮演女漂时，可根据互动发展为同伴、闺蜜或克制的伴侣；不能把该偏好自动套到其他用户。

表达边界：

- 群聊不展示私人 affinity、presentation 推断或 relationship mode，不进行针对单一成员的暧昧表演。
- 所有模式禁止露骨内容、公开撒狗粮、占有、嫉妒、排他承诺和情感绑架。
- partner 仍以自然陪伴、信任和共同经历表达，不依赖直白情话或身体/性暗示。
- 原始剧情中的关系不能直接映射为当前用户关系。
- profile reviewer 检查称谓、错误性别断言、关系跳级、排他性、身份误认和人格漂移。
- fallback 文案来自当前 profile，不得硬编码守岸人。

### 6.6 文档摄取

统一 loader 支持 Markdown、TXT、DOCX，并输出：

- 规范化文本。
- source id、revision、内容指纹。
- 文档类型：manifest-support、lore、encyclopedia、research。
- 标题、段落/行位置、抓取质量标记。
- trust 与使用限制。

内容指纹相同的材料只建立一个正文实体，可保留多个 provenance alias。格式损坏、导航残留、脚本片段和重复块必须标注质量，不能直接作为高置信证据。

### 6.7 库街区百科解析

当前百科 revision 的解析流程：

1. 读取目录区并获得有序标题列表。
2. 校验当前 revision 的预期目录数 3,521；数量变化时记录 revision drift，而不是永久硬编码通过。
3. 从正文起点按目录标题顺序识别文章边界。
4. 文章内部的 `##`、重复标题或抓取残片不能误切成新文章。
5. 目录文本永不进入检索索引。
6. 空文章、重复文章和明显损坏片段保留诊断，但降低质量或不可答。

解析器必须有覆盖以下情况的 fixture：正常文章、重复标题、空正文、长文章、内部标题、损坏技能块、干净 lore 块和 revision drift。

### 6.8 确定性检索

第一阶段使用标准库实现，不引入向量数据库或新检索依赖：

- 中文字符 2-gram / 3-gram。
- 英文/数字 token 归一化。
- 文章级 BM25 召回。
- 文章内证据句/段二次选择。

三个评分维度分离：

- relevance：查询与文章/证据的相关度，始终是主要排序依据。
- scrape quality：抓取完整性、噪声、重复和可读性。
- trust：来源类型与修订来源的可信等级。

quality 与 trust 只能校正相关结果，不能让高质量但无关的文章超过高度相关证据。权重写入版本化配置，并用固定查询集回归。

### 6.9 可答性、置信度和引用

`RetrievalResult` 明确包含：

- `answerable: bool`
- `confidence: float`
- `articles`
- `evidence_spans`
- `citations`
- `stale: bool`
- `diagnostics`

`answerable` 由最低相关度、查询覆盖、证据质量、有效长度和歧义联合判断，不能使用 `bool(chunks)`。

引用格式为安全结构，例如：

```text
[K1] 守岸人角色资料 · 第 3 段 · revision kurobbs-v2
```

引用不得包含本机绝对路径、用户名或工作区结构。公共 Wiki 直接由结构化证据确定性渲染；聊天模型只能引用提供的 citation id，不能编造来源。

### 6.10 缓存与重建

- 索引对象构建后不可变，通过原子引用替换。
- 首次构建失败时 provider 进入 not-ready，并返回可操作错误。
- 已有索引重建失败时继续使用 last-known-good，结果显式 `stale=true`，同时发出诊断告警。
- 缓存键包含 source fingerprint、parser version、tokenizer version 和 scoring config version。
- 不在 B1 引入热重载；管理员显式 reload 或进程启动时重建。

## 7. M3：用户可见能力

### 7.1 公共 Wiki

`/wuwa wiki <查询>` 与普通聊天共享同一个 `KnowledgeProvider`，不能维护第二套互相漂移的索引。

输出顺序：

1. 规范化实体/问题。
2. 检索文章及证据。
3. 根据 `answerable/confidence` 选择回答、澄清或不可答。
4. 由纯函数生成 `game_wiki_card:v1` 与同源文本 fallback。
5. reviewer 检查卡片字段、fallback、引用和外链。
6. renderer 能用图片后端时生成 artifact，否则发送 fallback。

首批外部补充只允许有明确来源的 Kuro 公共角色、武器、声骸与新鲜活动信息。兑换码、日历或其他实时内容在没有权威 provenance 前返回“当前未提供可靠来源”，不抓取聚合站猜测。

### 7.2 媒体解析

`/wuwa parse <url>` 使用 allowlist `PlatformSourceAdapter`。群自动解析默认关闭，并要求逐群 opt-in；单条消息最多解析一个资源。

每个平台通过 capability manifest 声明实际支持范围：

- public profile / channel
- dynamic / feed / article
- long video / short video
- live room / replay metadata
- commerce product / storefront metadata
- music track / album / artist / playlist
- game wiki / official announcement / activity

首版固定覆盖矩阵如下。状态：`P=supported_public`、`A=auth_required`、`B=source_blocked`、`N=not_applicable`。

| 平台/adapter | 子里程碑 | 主页 | 动态/文章 | 视频 | 直播 | 商城 | 音乐 | 百科 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Bilibili | M3a | P | P | P | P | P | N | P |
| KuroBBS/库街区 | M3a | P | P | P | N | N | N | P |
| TapTap | M3a | P | P | P | N | P | N | P |
| Bilibili Wiki | M3a | N | N | N | N | N | N | P |
| official-game-site family | M3a | N | P | P | B | P | N | P |
| 微博 | M3b | P | P | P | B | A | N | N |
| 抖音 | M3b | P | P | P | P | P | N | N |
| 快手 | M3b | P | P | P | P | P | N | N |
| 小红书 | M3b | P | P | P | P | P | N | N |
| 知乎 | M3b | P | P | P | N | N | N | N |
| 百度贴吧 | M3b | P | P | P | N | N | N | N |
| 斗鱼 | M3b | P | N | P | P | N | N | N |
| 虎牙 | M3b | P | N | P | P | N | N | N |
| 网易云音乐 | M3c | P | B | P | B | N | P | N |
| QQ 音乐 | M3c | P | N | P | B | N | P | N |
| 酷狗音乐 | M3c | P | N | P | P | N | P | N |
| 酷我音乐 | M3c | P | N | P | B | N | P | N |
| 咪咕音乐 | M3c | P | N | P | P | N | P | N |

矩阵验收语义：

- `P`：M3 必须有 URL/实体匹配、fixture parser、规范化模型、确定性卡片/fallback、失败矩阵和 fake integration；网络允许时每个平台至少执行一个 online-readonly smoke。
- `A`：M3 只实现 auth-required 识别与阻断测试；SecretStore、撤销和审计完成后在 M5 单独启用，不计入 M3 公开功能。
- `B`：实现确定性 `source_blocked`/challenge 结果、健康诊断和 kill switch，不把无法稳定访问伪装成支持。
- `N`：adapter 必须明确报告 capability 不适用，不能误匹配到其他 parser。

M3a、M3b、M3c 分别交付游戏/Bilibili、社交/直播和音乐矩阵；对应子里程碑只有在所有 `P` 单元通过最低证据后才完成。新增平台必须更新版本化矩阵和验收 fixture，不能用开放式范围措辞扩大已完成声明。

首个完整证明仍以 Bilibili 为主，但不只覆盖视频：实现视频、动态、直播状态和会员购商品 metadata。商城适配只提供商品卡片、价格/库存时间戳和官方链接；下单、支付、抢购和账号资产操作属于独立高风险能力，在凭据存储与二次确认完成前不开放。

媒体与直播规则：

- 不下载或重托管完整视频、直播和音乐文件。
- 不读取或复制用户浏览器 cookie；需要登录态的 adapter 只能使用用户显式提供、存入 SecretStore 且可撤销的专用凭据。
- 不访问私信、评论管理、直播控制或非公开账号数据。
- 音乐默认只提供合法公开 metadata、封面和官方播放链接，不重新分发完整音频或受版权保护的完整歌词。
- 不把未公开数据写入公共缓存。

Fetcher 必须拒绝：

- 非 HTTPS。
- URL userinfo。
- 环回、私网、link-local 和解析后落入受限网段的地址。
- 非 allowlist host 或非法跨域重定向。
- 超过限制的响应体。
- 未允许的 content-type。

平台稳定性与“反反爬”边界：

- 优先官方 API、公开结构化数据、RSS/公开 feed 和服务端允许的页面。
- 使用 per-host 限流、条件请求、内容缓存、指数退避、抖动、熔断和请求合并，减少对站点压力。
- 必要且条款允许时使用受限浏览器渲染作为公开页面降级路径，并限制脚本、下载、跳转和资源大小。
- adapter 保存 fixture、schema fingerprint、解析器版本和 last-known-good；结构变化时自动降级并告警，而不是返回错误字段。
- 遇到验证码、登录墙、签名校验失败、明确 robots/条款限制或访问控制时返回 `source_blocked_challenge` / `source_auth_required`，不实施验证码破解、指纹伪装或访问控制绕过。
- 每个平台独立 kill switch；连续失败不能拖垮其他平台。

外部 source 结果先规范化为版本化结构，再生成对应卡片和同源文本 fallback。网络异常、解析漂移和授权页面必须明确失败，不交给 LLM 猜测。

### 7.3 渲染与 artifact

卡片 compiler 是纯函数，输入相同结构就得到相同布局数据和 fallback 文本。artifact store 负责内容哈希、过期时间、mime、尺寸和清理，不保存凭据。

渲染顺序：

1. compiler 生成结构化卡片和 fallback。
2. reviewer 同时审查两者。
3. 可用后端生成图片 artifact。
4. transport 支持且 artifact 有效时发送图片。
5. 任一步失败都发送同一份已审查 fallback，不重新让 LLM 生成。

`nonebot_plugin_htmlkit` 只有在全新环境 import、最小渲染和真实 transport 上传均通过后，才可标记为 ready。

### 7.4 手动群总结

新增独立 `GroupMessageArchive`，不能复用只记录机器人对话轮次的 history repository。

归档规则：

- 逐群 opt-in，默认关闭。
- scope：platform/adapter/bot/group。
- 每次从 disabled 变为 enabled 都递增 `archive_generation`；每条原文记录所属 generation。
- 当前部署默认 `retention_mode=forever`，永久保留文字、链接、回复关系和结构化 segment metadata；不自动下载大型图片、语音、视频或文件正文。
- 不设置通过删除旧记录实现的容量上限；按时间分区、压缩冷数据并建立必要索引。达到磁盘高水位时告警并明确报告写入失败风险，不能静默裁剪历史。
- 原始消息不进入 audit 或通用诊断。
- 关闭 opt-in 或 bot 离群时立即停止新写入，但在 forever 模式下保留既有记录供授权查询；重新启用创建新 generation。
- 只有显式“删除群归档”操作才创建包含 scope、`cutoff_generation`、cutoff time 的 durable purge tombstone。
- 删除命令的本地事务只负责：锁定旧 generation、写入 tombstone、创建幂等 purge job、切换到新 generation，并使旧代立即对查询、summary、memory retrieval 不可见。
- purge job 状态为 `purge_pending -> purge_running -> purge_completed`，失败进入带重试信息的 `purge_failed_retryable` 或需人工处理的 `purge_failed_final`。
- worker 按 tombstone 幂等清理全部时间分区、全文索引、派生群记忆、artifact 引用和备份删除清单；进程重启后继续未完成 job。
- 命令即时回执只能表示“删除请求已接受且旧数据已隐藏”；只有 job 完成后才报告“全部副本已清除”。
- 删除审计只记录脱敏 scope hash、删除条数和完成时间，不保存被删正文。
- 恢复流程必须先重放 tombstone，再开放读取，保证已显式删除的旧代不会从备份复活。
- tombstone 只有在主存储和所有备份中的对应代均确认清除后才可 GC。

`GroupMemoryConsolidator` 定期或按管理员命令从原始归档提炼群级长期记忆：

- 只提取长期话题、共同经历、明确决定、行动项和可验证偏好，不建立成员心理画像。
- 每条记忆保留 source message ids、generation、confidence、created/updated time，可追溯回原始证据。
- 原始归档和提炼记忆分表；构造 prompt 时只检索相关记忆与少量证据，不把全部聊天记录塞入模型。
- 群级记忆不能写入个人私聊记忆，也不能跨群、跨 bot、跨 persona 或跨 IP 复用。
- 删除原始 generation 时同步删除或重建受影响的派生记忆。

`/wuwa summary [N|--since|--topic]`：

- 默认 100 条，范围 20..300。
- 最长回看 24 小时。
- 清洗后输入最多 24,000 字。
- 单群冷却 120 秒。
- 排除命令自身、空文本、机器人系统提示和重复消息。
- 成员 id 替换为本次请求稳定的匿名标签。

LLM 只接收标记为 untrusted evidence 的 JSON，并以低温生成严格 schema；解析失败最多修复一次。仍失败时确定性返回消息数、时间范围、主要词项与链接，不推断成员观点或决定。

输出仅包含主要话题、决定、行动项、未解决问题、关键链接和范围。禁止成员画像、排名、心理诊断和争议裁决。

### 7.5 天气

`/wuwa weather <地点> [tomorrow|3d]` 使用统一 `WeatherProvider`：

- 群聊必须显式地点。
- 私聊默认地点需要用户明确同意，只存行政区，不存精确坐标。
- 地点歧义返回候选，不自动选第一项。
- 输出包含来源、观测/预报时间和缓存状态。
- provider 失败时只允许使用最多 2 小时的 stale cache，并显式标注。

官方预警由独立 `OfficialAlertProvider` 提供。未配置预警来源时明确显示不可用，不能从天气码推测“官方预警”。

### 7.6 官方告警规范化与订阅门禁

M3 只交付 `OfficialAlertProvider`、normalized alert schema、来源/时间/等级校验和管理员手动预览；不启用 scheduler、cursor、digest 或自动投递。

M4 通用订阅仓库完成后才启用告警订阅：

- 只有管理员可创建、修改或删除告警订阅。
- 创建或修改时确认精确目的地、地区、等级、频率和 quiet-hours 策略，形成版本化 standing authorization；授权范围内的后续告警不逐条确认。
- 新订阅首次只 prime cursor，不回放历史洪水。
- 蓝/黄默认进入 digest；橙/红可即时，但 quiet-hours 绕过必须单独显式配置。
- 去重键为 provider + alert_id + revision。
- 只有首次、等级升级、实质变化、解除或终报产生新 dispatch intent。
- 连续 provider 失败进入管理员摘要，不能对群反复刷屏。
- scheduler 只生成 normalized alert 与 dispatch intent，仍由 coordinator 投递。

## 8. M4：自动发送、订阅与持久控制

### 8.1 自动发送状态机

采用“关系型当前状态 + append-only transition events”，不使用完整 event sourcing。

状态：

```text
building
  -> preview_ready
  -> actor_confirmed
  -> admin_confirmed (when required)
  -> confirmed_pending_dispatch
  -> dispatching
  -> sent | partially_sent | failed_final | delivery_unknown | cancelled | expired
```

允许根据风险跳过不需要的 admin 状态，但每个用户发起的 `AutoSendBatch` 都必须对该 version 取得请求人确认；不允许用一次确认建立无限期的任意内容发送授权。

不变量：

- preview 绑定 version、payload_hash、actor、expiry 和 recipient snapshot。
- confirm/cancel 使用条件更新，竞争时只有一个转换成功。
- 重复 confirm 返回原 batch，不创建第二批发送。
- 编辑生成新 version，并 supersede 旧 preview。
- 过期 preview 不可确认。
- 每个收件人独立解析、上下文构造、review、dispatch 与 receipt。

超过 3 个收件人、full personalization、高风险内容或邮件渠道需要额外管理员确认。SecretStore、撤销和二次确认未落地前，邮件与凭据型渠道保持阻断。

### 8.2 收件人与个性化安全

- 收件人必须来自 allowlist address book、明确账号绑定或管理员批准的映射。
- 歧义不自动选择。
- 未解析、已 opt-out、禁止渠道或地址推断失败时阻断该收件人。
- 不从昵称编造邮箱、QQ 或其他地址。
- 跨收件人不得泄漏其他人的私密记忆或关系事实。
- personalization 只能使用对该目标与该用途明确允许的数据。

### 8.3 订阅、cursor 与 digest

订阅投递与用户发起的 `AutoSendBatch` 是两种授权模型：

- 创建或修改订阅时，管理员一次性确认精确 source、destination、过滤条件、频率、quiet-hours 和即时等级，形成有版本、有到期/撤销能力的 standing authorization。
- 订阅范围内的后续 normalized event 可按该授权自动生成 dispatch，不要求每条再次确认。
- destination、source、过滤条件、即时等级或 quiet-hours bypass 任一变化都会使旧授权失效并要求重新确认。
- 不在 standing authorization 范围内的自由文本、收件人定向内容或高风险动作仍走通用审批/`AutoSendBatch` 流程。

watcher 处理顺序：

1. 拉取 source。
2. 解析并规范化候选。
3. 持久化 candidate 与 suppression/dedupe 结论。
4. 在同一事务边界或可恢复协议中 CAS 推进 cursor。
5. 生成 dispatch intent。

fetch、parse、auth、captcha 或 upstream schema change 失败时不得推进 cursor。

- 新订阅首次 prime，不回放全历史。
- 群订阅默认每日一条 digest，最多 10 项。
- cursor、candidate、suppression、digest batch 和 delivery receipt 均持久化。
- digest 组装是确定性过程；LLM 可生成摘要，但不能决定是否漏掉已选项目。

### 8.4 持久 kill switch

kill switch scope：

- global
- capability
- account/bot
- destination
- subscription
- auto-send batch

开关状态、操作者、原因、创建时间和过期时间持久化并审计。coordinator 在 claim 后、transport 前必须重新检查，避免任务排队后策略变化仍被发送。

命中开关的 item 进入 `held_kill_switch`，不会丢失；恢复后需显式或受控地重新排队。紧急 global switch 的读取失败采用 fail-closed。

## 9. M5：真实 transport 与运维界面

### 9.1 NapCat/OneBot 验证等级

健康状态分层报告：

1. configured：配置存在且格式可解析。
2. process_visible：目标进程/端口可见。
3. connected：WebSocket/HTTP 会话建立。
4. api_accepted：OneBot API 接受请求并返回成功。
5. readback_verified：能通过受支持方式读回 provider message id 或状态。
6. human_acknowledged：人工确认目标实际收到。

任何报告必须标明达到的最高等级。fake transport、online readonly 和真实发送不是同一证据。

真实 probe 默认只读。会产生消息的 probe 必须：

- 管理员显式启用。
- 指定精确 bot 与测试目标。
- 显示将发送的固定内容。
- 二次确认。
- 写入 probe receipt/audit。

### 9.2 运维 UI

M5 UI 实施前必须先使用 `frontend-design-ui-ux` 产出锁定的设计规格，再由工程任务实现。

第一阶段 UI：

- 只绑定 `127.0.0.1`。
- 只读展示 readiness、queue、held 状态、receipts、source freshness、persona registry、迁移版本和 kill switch 状态。
- 所有字段按角色鉴权并脱敏。
- 不显示消息正文、群归档原文、凭据或私密记忆。

开放写操作前必须具备：

- 认证会话与最小权限角色。
- CSRF 防护。
- SecretStore。
- 二次确认与操作审计。
- 幂等 API。
- 浏览器端安全测试。

对外网绑定、邮件配置、full personalization 和凭据录入在上述门禁完成前保持关闭。

## 10. 跨领域安全要求

### 10.1 输入与注入

- 用户文本、群归档、网页、媒体 metadata、百科正文都标记为 untrusted content。
- 外部内容不能改变 system 指令、权限、persona 选择或工具 allowlist。
- URL fetch 经过 DNS/IP 重检、重定向限制、大小和类型限制。
- 结构化模型使用 `extra=forbid` 或等价严格校验；未知字段不能静默进入 transport。

### 10.2 隐私

- 群、私聊、用户、persona 和 bot/account 都是独立作用域。
- 最小化保存；精确位置、凭据、群原文和个人记忆使用不同 repository 与保留策略。
- forever 群归档是经管理员显式 opt-in 的例外：启用时必须在群内发送可见说明，只保存已声明的消息字段，并始终提供查询、导出、停用和显式删除入口。
- presentation、affinity 和 relationship state 属于可纠正的敏感个性化数据；用户可查看、覆盖、重置或删除，且不得用于权限或其他实质决策。
- audit 只保存必要 metadata 和脱敏错误。
- “转私聊”不意味着可以把用户的任意私密资料注入当前回答。

### 10.3 权限与确认

- 管理命令统一使用角色服务，不在 handler 中自建布尔判断。
- 每个用户发起的 `AutoSendBatch` 需要该 batch/version 的 actor confirmation；高风险路径叠加 admin confirmation。
- 订阅事件依赖创建/更新时的版本化 standing authorization，不逐条确认；超出授权范围即阻断。
- quiet-hours 绕过、群 archive opt-in、自动解析和预警即时推送都必须显式配置。
- 默认 deny，缺配置不猜测。

## 11. 数据模型与迁移策略

所有 SQLite schema 使用显式版本表与事务迁移。迁移前后记录表行数、关键非空计数和版本；失败回滚，不留下半迁移状态。

主要增量：

| 领域 | 目标变更 | 兼容策略 |
| --- | --- | --- |
| send queue | route、lease token、terminal time、error code、content hash | 新列可空读取；旧缺 route 行 hold，不自动发送 |
| history | persona/profile scope | B2 事务回填到记录中的旧默认人格 |
| memory | persona/profile scope 与索引 | B2 同 history；删除/保留语义不变 |
| persona bindings | 新表 | 无绑定时使用显式默认 resolver |
| relationship state | presentation hint、affinity dimensions、mode、evidence/version | 默认 unknown/visitor；旧会话不推断性别或伴侣关系 |
| group archive | 独立原始归档、generation、tombstone 与派生群记忆 | 默认关闭采集；启用后永久保留，不迁移现有 history |
| auto-send | batch、recipient、transition event | 旧 preview 文案不视为可确认 batch |
| subscription | cursor、candidate、suppression、digest | 首次只 prime |
| kill switch | scope、actor、reason、expiry | 不依赖进程内变量 |

迁移应优先 additive。需要重建 SQLite 表时，使用新表复制、校验、原子替换；不直接删除用户数据。每个迁移都有空库、旧库、重复执行、失败回滚和数据计数测试。

## 12. 来源、版权与许可边界

- 仓库内角色档案和百科按项目已有用途作为本地知识输入；运行时引用只输出短证据与来源标题，不暴露本机路径。
- raw dossier 是 provenance/lore，不自动成为行为指令。
- 外部 adapter 必须记录 source、fetch time、revision/etag、允许用途和缓存期限。
- 没有明确授权或条款依据时，不批量镜像、不重托管媒体、不长期保存完整页面；只处理实现功能所需的公开 metadata 与短引用。
- 社交、直播、音乐、商城和游戏百科 adapter 只处理其 capability manifest 声明且有权访问的内容；不下载完整媒体、不窃取浏览器登录态、不自动交易，也不绕过验证码或访问控制。
- 对来源许可、服务条款或接口稳定性不能作未经核验的法律/官方保证；实现记录事实和限制，并允许随时关闭 adapter。
- 用户生成内容、群消息和个人数据不作为公共知识库训练或跨会话复用来源。

## 13. 可观察性与错误处理

每个请求使用同一 request/correlation id 串联 decision、capability、review、render、dispatch、queue、transport、receipt 和 audit。

诊断至少展示：

- 当前配置 readiness 与缺失项。
- persona registry/default/binding 健康状态。
- knowledge revision、文章数、构建时间和 stale 状态。
- queue 各状态计数、最老 pending、过期 lease、held 原因。
- transport route 与连接等级，不暴露凭据。
- source 最近成功/失败时间、cursor 和 schema drift。
- migration version。

错误必须包含稳定 `error_code`、可公开消息、脱敏 private debug 和 debug id。不得吞异常后返回“成功”；也不得把完整异常、URL query credential 或正文泄漏给群用户。

## 14. 兼容与发布策略

### 14.1 兼容原则

- 保留现有核心 Pydantic 契约字段；新增字段有安全默认值，内部复杂状态优先留在内部模型。
- 旧 `BOT_PERSONA_*` / `BOT_TONE_*` 在 B1 通过 legacy adapter 继续工作。
- 现有 `RuntimePipeline.handle()` 可作为兼容包装，但统一进入 coordinator。
- 旧 queue JSON/SQLite 可读取；缺路由记录 hold。
- 命令前缀、管理员角色和默认人格都从统一配置读取。
- 文本 fallback 永远可用，不要求图片后端才能启动。

### 14.2 发布门禁

每个里程碑按以下顺序发布：

1. 契约与迁移测试。
2. shadow/read-only 或 feature flag 路径。
3. 单一测试会话启用。
4. 小范围群/私聊 opt-in。
5. 完整启用。

高风险能力默认关闭：群 archive、自动解析、天气告警即时推送、自动发送、写操作 UI、真实 probe 和外网 source。

schema metadata 记录 `schema_version` 与 `min_reader_version`。发布采用 expand/activate 两步：先部署能读取旧/新字段但默认不写新状态的兼容版本，验证通过后再打开 feature flag 写入新状态。

回滚规则：

- activate 前可以回到旧二进制，因为尚未写入新状态。
- activate 后的常规回滚是关闭 feature flag，并继续运行当前兼容 reader，或部署明确支持当前 `min_reader_version` 的兼容修复版本。
- 已写入新状态后，禁止启动不理解该 schema/state 的旧二进制；启动时必须 fail closed，而不是尝试猜读。
- 表重建迁移前创建受控备份并校验，迁移失败事务回滚；不提供会删除新数据的自动 down migration。
- 回滚始终保留新数据，恢复功能时继续使用原 version/CAS 语义。

## 15. 测试与验证

### 15.1 TDD 与任务级门禁

每个行为变更先写会失败的测试并确认 RED，再做最小实现到 GREEN。任务完成前运行：

- 定向 pytest。
- 受影响模块 ruff。
- 受影响模块 mypy。
- 相关 docs/plugin checks。

里程碑完成前运行仓库完整 `scripts/dev.ps1 verify`。

### 15.2 必测矩阵

M1：

- 默认/自定义前缀，群/私聊/频道，管理员/普通用户。
- handler -> plan -> coordinator -> fake transport 全链。
- 所有 `SendPolicy` × `ReviewAction`。
- `MOVE_PRIVATE` 主项成功、失败、unknown、notice 失败。
- 两 worker 竞争、租约过期、旧 token 回写、崩溃恢复。
- 多 bot 精确路由、bot 离线、旧记录缺 route。
- route + approval + dependency + kill switch 多重 hold 的不同释放顺序，以及 claim 后复检回 hold。
- 容量被 pending 占满、terminal-only prune。
- memory 命令被阻断时零写入。

M2：

- legacy/manifest 优先级、损坏 manifest、cache invalidation。
- 三角色与跨 IP fixture 的默认/绑定/禁用/不存在 profile。
- 群/私聊/跨用户/跨 bot/跨 universe/跨 persona 历史、记忆和关系隔离。
- 明确自述、低置信行为提示、误判纠正、中性回退与 presentation 删除。
- affinity 阈值/滞回、不同关系分支、partner 明确信号门禁和跨 persona 隔离。
- dossier 指令注入、露骨/撒狗粮/排他表达、关系跳级和 profile-aware fallback。
- 3,521 目录解析基线、revision drift、重复/空/损坏文章。
- 中文/英文/别名查询、无答案、歧义、引用无本机路径。
- 首次构建失败与 last-known-good stale。

M3：

- Wiki 低/高置信与文本 fallback。
- 平台 capability matrix：动态、长短视频、直播、商城、音乐、百科与不支持能力的明确降级。
- M3a/M3b/M3c 固定矩阵中每个 `P/A/B/N` 单元的对应 fixture、阻断或 online-readonly 证据。
- URL SSRF、重定向、大小、content-type、限流/熔断、challenge/auth wall 和 parser drift。
- renderer import 缺失、渲染失败、artifact 过期和 transport 不支持图片。
- 群 archive opt-in、永久保留、无静默裁剪、generation/cutoff tombstone、恢复防复活、派生记忆追溯/删除、匿名化、冷却和 fallback summary。
- 天气位置歧义、同意、stale cache、预警未配置。
- OfficialAlertProvider 规范化、来源时间、等级和管理员手动预览。

M4：

- preview/confirm/cancel 竞争、过期、重复确认、新版本 supersede。
- 多收件人部分失败、opt-out、地址歧义、跨收件人隐私。
- watcher 失败不推进 cursor、首次 prime、digest 上限。
- 告警订阅 standing authorization、升级、解除、quiet-hours 与 digest。
- kill switch 重启持久化及 claim 后二次检查。

M5：

- health 等级不夸大。
- probe 双确认、精确目标和 receipt。
- UI 鉴权、脱敏、CSRF、只读边界和 loopback 绑定。
- 浏览器端 queue/held/source/persona 状态展示。

### 15.3 验证等级

| 等级 | 能证明 | 不能证明 |
| --- | --- | --- |
| unit | 纯函数、模型、状态机 | 真实框架和外部系统 |
| integration_fake | 模块协作与副作用顺序 | 外部 provider 行为 |
| local_smoke | NoneBot/本地进程可启动 | 在线账号实际可用 |
| online_readonly | 网络、认证或公开 source 可读 | 消息实际送达 |
| real_e2e | 指定环境下真实调用结果 | 其他账号/网络或永久可靠性 |

交付报告必须逐项注明等级、命令、退出码和外部前提。

## 16. 需求覆盖与验收映射

| 需求 | 主要里程碑 | 最低证据 |
| --- | --- | --- |
| R01-R03 统一入口、权限、隐私与运行时策略 | M1 | handler 集成、权限矩阵、零旁路发送 |
| R04 LLM/prompt 安全与就绪 | M1-M2 | provider smoke、注入与错误矩阵 |
| R05-R08 人格、关系、记忆、文档与知识 | M2 | 通用角色包、三角色/跨 IP 隔离、动态关系、文章检索、引用与 stale 测试 |
| R09 Wiki | M3 | 确定性回答/卡片/fallback |
| R10-R12 source、平台能力、媒体、渲染与审查 | M3-M4 | 多平台 capability fixture、网络只读、challenge 降级、审查矩阵 |
| R13-R14 投递与队列 | M1 | 全策略、双 worker、多 bot、崩溃恢复 |
| R15 自动发送 | M4 | durable confirmation 与逐收件人回执 |
| R16 群总结与群级记忆 | M3 | 永久独立 archive、可追溯 consolidation、隐私和 fallback |
| R17 天气/告警 | M3-M4 | provider fixture、normalized preview、opt-in alert flow |
| R18 扩展推荐能力 | M3+ | 每个 adapter 独立 source contract；无可靠来源时明确不可用 |
| R19 adapter/真实 NapCat/Mail | M5 | 指定凭据环境的分级验证；Mail 在 SecretStore 前阻断 |
| R20 管理、迁移与 WebUI | M1-M5 | migration、operator audit、browser tests |
| R21 高风险账号绑定 | M4-M5 | credential store、撤销、私聊和二次确认 |
| R22 可复现门禁 | 全程 | fresh venv、完整 verify、启动 smoke |

R18 不是一个允许任意抓取的兜底入口。每个新能力必须有独立的来源、权限、缓存、隐私、失败和验收契约；没有可靠来源或合法可用边界时，正确实现是显式不可用，而不是由 LLM 编造。

## 17. 明确不采用的方案

- 不在当前阶段重写为完整 event sourcing。
- 不让 pipeline、handler、scheduler 或 capability 各自发送。
- 不对 OneBot 声称 exactly-once。
- 不在 B1 直接开放三角色切换。
- 不把 runtime、记忆或命令实现硬编码为鸣潮专用；IP 差异进入 UniversePack/CharacterPack。
- 不根据姓名、兴趣或说话风格单独断言用户性别。
- 不让 affinity 分数单独触发 partner，也不在任何关系模式输出露骨、撒狗粮或占有表达。
- 不用关键词从原始档案自动生成 system 指令。
- 不把整本百科或整篇长文章注入单轮 prompt。
- 不用高质量分数掩盖低相关度。
- 不在第一阶段引入向量数据库、磁盘向量索引或新检索依赖。
- 不把聊天历史当作群消息归档。
- 不从天气码推测官方预警。
- 不在无确认状态下真实自动发送。
- 不用“第一个在线 bot”修复缺失路由。
- 不因图片渲染失败阻断文本功能。
- 不以“反反爬”为名破解验证码、伪造设备指纹、窃取 cookie 或绕过登录/访问控制。
- 不在完成认证、CSRF、SecretStore 和二次确认前开放运维写操作。

## 18. 实施纪律

- 先用 `writing-plans` 把本规格拆为可独立验收的 TDD 任务。
- 使用 `subagent-driven-development` 时，每项任务使用新的 implementer，并经过规格符合性和代码质量两轮审查。
- 维护 `.superpowers/sdd/progress.md`，记录任务、commit、测试证据、审查与修复。
- 任何任务发现规格矛盾或需要扩大权限时，停止该任务并回到设计决策，不自行跨范围实现。
- M5 运维 UI 先经过 `frontend-design-ui-ux`，再写生产 UI 代码。
- 每个 commit 只包含本任务文件，不包含用户既有脏工作树变更。

## 19. 本规格自审清单

- 已覆盖 M1-M5 与 R01-R22。
- 已定义 pipeline、coordinator、queue、transport 的唯一所有权。
- 已定义 bot route、lease fencing、terminal-only prune 和 `delivery_unknown`。
- 已定义通用角色/IP 包、B1/B2 人格门禁、历史/记忆迁移、presentation/affinity 和关系安全边界。
- 已定义 3,521 篇当前基线的目录解析、文章召回、证据选择、可答性、引用和 stale cache。
- 已定义 Wiki、多平台动态/视频/直播/商城/音乐适配、卡片 fallback、永久群归档与群级记忆、天气与官方告警。
- 已定义自动发送、订阅 cursor/digest、kill switch 和 live probe。
- 已定义外部来源、版权/许可的保守边界，未声称未核验授权。
- 已区分 unit、fake integration、local smoke、online readonly 与 real E2E。
- 未留下未决占位标记、伪命令输出或未经执行的通过声明。
