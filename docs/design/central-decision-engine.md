# B2 · 中央决策层 / 统一事件入口（CentralDecisionEngine）设计规格

- 状态：**规格稿（未实现）**。本文只写设计规格，不含实现代码；细度以"下一会话可直接照做"为准。
- 规格来源：`handoff-comprehensive-2026-09-05.md` §3.3「目标中央决策流 + 十条强制规则」（原件已归档：`ChatBot_Archive\2026-09-12\docs-archive-2026-09-12.zip` 内 `handoff-comprehensive-2026-09-05.md`；工作区 `docs/HANDBOOK.md:81` 的 B2 行即指向该节）。注：任务指名的 `docs/project-audit-and-modernization-roadmap-2026-09-05.md` §3 只是「当前架构概览」，十条强制规则实际在 comprehensive 09-05 §3.3——两份均已归档，本文按 comprehensive §3.3 对齐。
- 姊妹规格：`docs/design/file-transfer-gateway.md`（B3）。B3 依赖本文的阶段 1-2 完成后的"统一派发底座"，但可先行做 sender 层内收敛（见 B3 文档）。
- 基线：本文全部 file:line 现状引用于 2026-09-12 对当前工作树 grep/实读核实；无法核实的项明确标注 `unknown`。

---

## 1. 现状盘点（全部经 grep 核实）

### 1.1 入口总账

所有 NoneBot matcher 都注册在 `plugins/bot_unified_runtime/__init__.py` 的 `_register_nonebot_handlers()`（`__init__.py:2710`，模块尾部 `__init__.py:6567` 调用一次）。**共 38 个 matcher、38 个 `.handle()`**（2026-09-13 复核：`@*.handle()` 共 38 处，从 `__init__.py:3785` 到 `__init__.py:6396`；on_message 33 / on_notice 3 / on_command 2）。`plugins/` 下只有 `bot_unified_runtime` 一个插件包，无其他 matcher 入口。
>
> 注：下文各表/明细中的 `L` 行号是 2026-09-12 规格成文时快照，代码后续有漂移；matcher 总数与类型分布以上述 2026-09-13 复核为准。

按类型与优先级（NoneBot 数值越小越先跑）：

| 类型 | 数量 | matcher（优先级, block） |
|---|---|---|
| `on_command` | 2 | `status`（11, True, L3595）；`mail_control`（10, True, L3603） |
| `on_notice` | 3 | `group_upload_notice`（6, False, L3698）；`poke_notice`（7, False, L3744）；`file_notice`（8, False, L3734） |
| `on_message` | 33 | 见下表 |

`on_message` 明细（L = `__init__.py` 行号）：

| 优先级 | matcher |
|---|---|
| 3, False | `dirty_guard_matcher`（L3719，脏话守卫，可撤回消息） |
| 8, True | `file_export`（L3824）；`cookie_admin`（L3942）；`nickname_set`（L3949）；`group_file_stats`（L3975） |
| 8, False | `mail_notice`（L3610，注意：它是 on_message 不是 notice） |
| 9, False | —（`mail_notice` 已计入上条） |
| 10, True | `alias`（L4353） |
| 10, False | `meme_absorb`（L3635，**无 rule，所有消息都进**） |
| 12, True | `subscribe_cmd`（L4343） |
| 13, True | `auto_send`（L3602） |
| 20, True | `meme`（L3624） |
| 22, True | `meme_library`（L3633） |
| 40, True | `music_mode`（L4325） |
| 41, True ×14 | `music`（L4326）`today_history`（L4327）`wiki`（L4330）`moegirl`（L4331）`epic`（L4335）`weather`（L4336）`market`（L4337）`divination`（L4338）`news`（L4339）`randpic`（L4340）`reminder`（L4341）`eat`（L4342）`fx`（L4436）`affinity`（L4453，行号为 2026-09-13 补录时实测） |
| 42, True | `stocks`（L4437，行号为 2026-09-13 补录时实测） |
| 44, True | `moegirl_question`（L4332） |
| 45, True | `natural`（L3625） |
| 46, True | `image_search`（L3892）；`content`（L4324） |
| 50, True | `chat`（L3611） |

已知优先级暗坑（代码注释自证）：`group_file_stats` 必须压在 p=8，否则会被 p=11 的 `status`（on_command，block=True）完全遮蔽成死代码（`__init__.py:3974-3975` 注释）。

### 1.2 现状拓扑（文字版）

```text
                       ┌──────────────────────── 适配器（bot.py:176/177/197 注册） ───────────────────────┐
                       │  OneBot V11 (SnowLuma)      Telegram      ResilientMailAdapter                  │
                       └──────────────────────────────────┬──────────────────────────────────────────────┘
                                                          ▼
                    38 个 NoneBot matcher（_register_nonebot_handlers, __init__.py:2710）
   ┌──────────────────────────────────────────────────┼──────────────────────────────────────────────┐
   │ 规则层（各 matcher 的 _is_*_event）                                                            │
   │  • 多数读 _cached_route_decision（L710-734，事件级 state 缓存）                                  │
   │    └→ classify_message_route（base_router.py:495）→ ROUTE_RULES 24 条（base_router.py:396-421） │
   │  • 少数自带正则/ isinstance 判断：image_search(L3891)、group_file_stats(L3972)、                │
   │    nickname_set(L3945)、file_notice(L3690)、poke(L3741)、mail(L3564) 等                          │
   └──────────────────────────────────────────────────┬──────────────────────────────────────────────┘
                                                      ▼
                     各 handler（35 个，__init__.py:3700-6225，共 ~2500 行内联闭包）
   共同骨架（三种写法并存）：
   A. _run_capability_through_pipeline（L2118）：IngressGateway→IncomingMessage → pipeline.handle*
      → _find_sent_request(L1690) → _deliver_transport_send_request(L2053) → 诊断/运维通知/历史归档
   B. 手写同构（image_search L3895、content L5779 等）：_incoming_from_nonebot_event(L1030) →
      pipeline.handle_async → _find_sent_request → _deliver_transport_send_request → matcher.finish
   C. 直连 bot.call_api（不走发送队列，见 §1.4）：dirty_guard L3730、poke L3759-3766、
      file_export 上传 L3864-3877、cookie QR 图片 L4012-4023、cookie 到期提醒任务 L3360
                                                      ▼
                     RuntimePipeline（domains/chat_reply/runtime/pipeline.py）
   _prepare（pipeline.py:431）：runtime_enabled → 角色解析 → runtime_control → evaluate_policy
   （domains/chat_reply/policy/gate.py，群黑白名单/触发门禁）→ quiet_hours → reply_budget → rate_limit → BotDecision
   _claim_event（pipeline.py:810）：EventIdempotencyTable/Sqlite 幂等（domains/chat_reply/runtime/event_idempotency.py）
   _complete：能力执行 → Review → 渲染 → SendRequest → SendQueue.submit
                                                      ▼
   SendQueue（domains/transport/sender/queue.py Protocol；InMemory/SQLite 双实现）
      ↙ handler 内显式补投递（内存队列回执是"假 sent"）        ↘ 后台 worker（_register_send_queue_scheduler,
   _deliver_transport_send_request（L2053）→ UnifiedDeliveryGateway        L1335，drain SQLite 队列）
   （domains/transport/sender/gateway.py）→ send_onebot_v11 / send_nonebot_message             （同一对 transport）
                                                      ▼
                     传输层 + 回执 + 审计 + 诊断
```

背景直连流（不经 matcher，也无用户事件上下文）：

- 订阅推送：scheduler outbox → `_deliver_v2_event`（`__init__.py:3212`）→ 合成 `IncomingMessage` → pipeline → `_deliver_transport_send_request`（`__init__.py:3276`）。
- 队列 worker：`_register_send_queue_scheduler`（`__init__.py:1335`）→ `send_onebot_v11`/`send_nonebot_message`（`__init__.py:1360` 附近）。
- 运维告警：`_deliver_admin_alert`（`__init__.py:2942`）→ `send_onebot_v11`/`send_nonebot_message`。
- cookie 到期每日提醒：`bot.call_api("send_private_msg")` **直连**（`__init__.py:3360-3364`）。
- Mail 出站：`send_mail_from_account`（`domains/transport/mail/mail_bridge.py`，被 `domains/transport/mail/mail_bridge.py` 与 `domains/ops/monitor/disconnect_notice.py:188` 调用）走 adapter 的 `send_mail`/`send_to`，**不经过 UnifiedDeliveryGateway**；普通邮件回复则在 `domains/transport/sender/nonebot.py/439`（经 gateway，text-only）。
- GsCore 桥入站：`domains/ops/integrations/gscore_bridge.py:147/265-267` 以回调 `on_message` 注入（非 NoneBot matcher），最终是否汇入 pipeline 由桥接调用方决定（本仓内未见接线点，`unknown`：GsCore 桥当前是否在生产启用）。

### 1.3 已具备的统一基础（可直接复用，不要重造）

- `IncomingMessage`（`domains/core/contracts/runtime.py:121`，含 reply_chain/mentions_bot/name_mention_only/隐私级/角色）。
- `BotDecision`（`domains/core/contracts/runtime.py:184`）、`PolicyEvaluation`（:170）。
- `CapabilityResult`（`domains/core/contracts/runtime.py:209`）。
- `RuntimePipeline`（`domains/chat_reply/runtime/pipeline.py`）：policy/quiet_hours/reply_budget/rate_limit/idempotency/BotDecision 已在 `_prepare` 收口。
- `SendRequest`（`domains/core/contracts/runtime.py:274`，含 dedupe_key/cooldown_key/expires_at/deadline_monotonic）、`DeliveryReceipt`（:323）、`AuditRecord`（:336）。
- 路由注册表 `ROUTE_RULES`（`domains/chat_reply/runtime/base_router.py`，24 条，声明式，带 TTL-LRU 分类缓存 :539-551）。
- 幂等：`EventIdempotencyTable`/`SqliteEventIdempotencyTable`（`domains/chat_reply/runtime/event_idempotency.py/84`），pipeline 内 `_claim_event`（`pipeline.py:810`）。
- 接口清单 `INTERFACE_MANIFEST`（`base_router.py:427`，含 active/reserved 审计位）。

### 1.4 违反十条强制规则的现状点（逐条对照）

十条规则原文见归档件 comprehensive-09-05 §3.3（本文引编号）：

| # | 强制规则 | 现状差距（file:line） |
|---|---|---|
| 1 | 所有事件必须经过中央决策层 | 38 个 matcher 平行入口（§1.1）；三类 handler 写法（§1.2 A/B/C） |
| 2 | 新功能不得绕过决策层直发 | 无守门机制约束新 handler；C 类写法仍被复制 |
| 3 | capability 不得直接调用平台发送 API | capability 层总体守约；违规在 handler/任务层：`__init__.py:3730/3759/3766/3864/3872/4012/4019/3360` |
| 4 | 只有统一发送网关可发送 | `domains/transport/mail/mail_bridge.py`（SMTP 直连）、`__init__.py:3360`（call_api 直发）绕过 gateway |
| 5 | 一个事件只产生一个最终 ActionPlan | 双 matcher 可同时命中（如 p=8 admin 系与 p=11 status 分裂；`meme_absorb` p=10 block=False 与 p=20 meme 并存），依赖 NoneBot block 语义而非中央裁决 |
| 6 | 旁路日志/诊断不产生第二条业务消息 | 基本满足（诊断只写 store）；`_notify_operational_receipt` 运维通知是第二条消息，属设计内豁免（unknown：是否需在 ActionPlan 中显式建模） |
| 7 | 事件必须有 event_id/dedupe_key/截止时间/风险级/优先级 | `request_id`+`dedupe_key`+`deadline_monotonic`+`risk_level` 已有（`domains/core/contracts/runtime.py:122/285/298/227`）；"决策优先级"目前散在 matcher priority + ROUTE_RULES.priority 两处 |
| 8 | 重试只由发送层负责 | `domains/transport/sender/onebot.py` 副作用进度 + queue worker 重试已收口；但 handler 内"补投递"模式（B 类）意味着**业务层参与了一次投递编排**（形态上在 handler，实际调用的是发送层函数） |
| 9 | 冲突由中央层用优先级/互斥组/风险级/幂等键裁决 | 目前由 NoneBot matcher priority + block 承担；无互斥组概念 |
| 10 | 所有决策必须可解释 | `RouteDecision.reason`（`base_router.py:107`）+ `BotDecision.decision_reason`（`domains/core/contracts/runtime.py:195`）+ `/bot why`（build_why_result）已具雏形；无单一"决策记录"视图把"为什么静默/阻断"串起来 |

---

## 2. 目标架构

### 2.1 设计原则

1. **不推倒重写**：`RuntimePipeline`、`SendQueue`、`UnifiedDeliveryGateway`、`CapabilityResult`/`SendRequest`/`DeliveryReceipt` 是已验证的 Sentinel 契约，**本设计不改其字段与语义**（只允许新增可选字段，见 §2.6）。
2. 引擎吃掉的是 **matcher 层的"入口+规则+派发编排"**（§1.2 中 35 个入口和 A/B/C 三类写法），不是 pipeline 内部的门禁链。
3. 单一入口、单次分类、单一 ActionPlan、决策全程可解释可审计。

### 2.2 目标拓扑

```text
任何 Event（OneBot / Telegram / Mail / GsCore 桥 / Console）
   ↓
IngressNormalizer（统一归一化；现 IngressGateway L2136 + _incoming_from_nonebot_event L1030
   + mail/telegram 分支收敛为 AdapterSource 插件点）
   ↓
IncomingMessage + DecisionContext（adapter 元数据、raw event 句柄、事件分类预判）
   ↓
CentralDecisionEngine.decide(ctx)  ──单次执行、单输出──▶  ActionPlan（见 2.4）
   决策链（顺序固定，全部产出 DecisionTrace 记录）：
   ① NoticeGate      通知/请求类事件分流（戳一戳/群上传/离线文件/脏话守卫）
   ② MuteGate        全局暂停/运行时开关（现 runtime_control，pipeline.py:258）
   ③ IdempotencyGate 幂等 claim（现 pipeline._claim_event 上移到决策前）
   ④ Router          ROUTE_RULES 确定性分类（base_router.py:424 原样复用）+
                     正则私有命令表（image_search/nickname/群文件统计等收编为 Rule）
   ⑤ AudienceGate    群黑白名单/触发门禁（现 evaluate_policy 中群场景判定，gate.py:244-288）
   ⑥ ActionResolver  RouteKind → ActionPlan.kind + capability_id + 互斥组 + 风险级
   ↓
ActionPlan
   ├── REPLY_TEXT / REPLY_CARD      （聊天/命令/解析…全部走 CapabilityExecutor）
   ├── NOTICE_ACTION                 （poke 回戳、群文件登记、脏话撤回——副作用显式化）
   ├── FILE_INBOUND / FILE_OUTBOUND  （挂 B3 FileTransferGateway）
   ├── PASSIVE_ABSORB                （meme_absorb 旁路吸收，不回复）
   ├── SILENT                        （判定"不该回"，含 reason）
   └── BLOCKED                       （门禁拦截，含 reason）
   ↓
Dispatcher（引擎内）：
   • 交互类 → RuntimePipeline.handle_async（pipeline 内 policy/rate/budget/review/render 照旧）
           → 投递编排从 handler 上收到 Dispatcher（现 A/B 两类写法的公共化）
   • 通知类 → 对应 NoticeExecutor（内部仍走统一发送函数，禁 call_api 直连）
   • SILENT/BLOCKED → 只写 DecisionTrace，零发送
   ↓
RuntimePipeline → SendQueue → UnifiedDeliveryGateway → 传输层 → 回执/审计/诊断（全部不变）
```

### 2.3 组件规格

#### 2.3.1 IngressNormalizer（入口归一化）

- 位置：新模块 `plugins/bot_unified_runtime/ingress/`（新目录），实现 `AdapterSource` Protocol：`can_handle(event) -> bool`、`normalize(event, bot_id) -> IncomingMessage | None`、`kind(event) -> Literal["message","notice","request","meta"]`。
- 首批三个实现：`OneBotSource`（移植 `_incoming_from_nonebot_event` `__init__.py:1030` + PrivateFileNoticeEvent 补模型 `__init__.py:751-770`）、`TelegramSource`（移植现 telegram 分支逻辑；现位置散于 `_event_adapter_kind` `__init__.py:3540-3562` 一带）、`MailSource`（移植 `_is_mail_event`/mail handler L4058 起的归一段）。
- GsCore 桥：`gscore_bridge.py` 的回调注入保持不变，桥侧把 payload 转成 `IncomingMessage` 后调用引擎（阶段 3 再接，见 §3）。

#### 2.3.2 CentralDecisionEngine（决策核心）

- 位置：`plugins/bot_unified_runtime/decision/engine.py`（新目录 `decision/`）。
- 接口草案（签名级，实现时按此落地）：

```python
@dataclass(frozen=True)
class ActionPlan:
    action: ActionKind          # REPLY_TEXT/REPLY_CARD/NOTICE_ACTION/FILE_*/PASSIVE_ABSORB/SILENT/BLOCKED
    capability_id: str          # 复用现有 id 体系（bot.chat/bot.status/…）
    route: RouteDecision        # 原样携带 base_router 的判定与 reason
    mutual_group: str           # 互斥组；同组内同事件只允许第一个命中者
    risk_level: RiskLevel
    priority: int               # 继承 ROUTE_RULES.priority；notice 类用 notice 优先级
    reason: str                 # 规则 10：决策可解释（人可读）
    trace_id: str               # DecisionTrace 主键
    deadline_monotonic: float | None

class CentralDecisionEngine:
    def decide(self, ctx: DecisionContext) -> ActionPlan: ...
    async def dispatch(self, plan: ActionPlan, ctx: DecisionContext) -> DeliveryReceipt | None: ...
```

- `DecisionContext`：`IncomingMessage` + raw event 弱引用 + adapter kind + 预提取的 segments（避免 handler 里重复 `_extract_onebot_raw_segments`）。
- **决策链必须一次跑完并产出唯一 ActionPlan**（规则 5）；链上每一环落一行 `DecisionTrace`（新结构：stage/kind/allowed/reason/ms），并入 `RuntimeDiagnostic` 或独立 SQLite 表（推荐独立表 `decision_trace`，供 `/bot why` 升级查询）。
- 互斥组语义：同一 `mutual_group` 的规则按 priority 排序，第一个命中即停；跨组默认互斥（一个事件一个 plan），显式声明 `allow_parallel=True` 的旁路型能力（`meme_absorb`、`dirty_guard`）除外——它们命中后**不终结**决策，但被标记为"旁路"且不允许产生业务回复。

#### 2.3.3 Dispatcher（派发器）

- 收敛现 handler 的公共骨架（§1.2 A/B 类）为唯一实现：

```python
async def _dispatch_capability(ctx, plan) -> DeliveryReceipt:
    message = ctx.message
    receipt = await pipeline.handle_async(message, offload_capability(capability_factory(plan)))
    await _notify_operational_callback(...)            # L2081 原样
    sent_request = _find_sent_request(send_queue, message.request_id)   # L1690 原样
    if sent_request:
        receipt = await _deliver_transport_send_request(bot, event, sent_request, ...)  # L2053 原样
        await _notify_operational_callback(...)
    _record_runtime_diagnostic(...)                    # 原样
    return receipt
```

- `matcher.finish()` 语义替换：引擎统一用返回回执驱动 NoneBot 的 `finish`（现 `should_finish_nonebot_matcher` 判断保留），但 `finish` 调用点收敛到 Dispatcher 一处。

#### 2.3.4 与 RuntimePipeline 的边界（关键裁定）

- **pipeline 保留**：policy/quiet_hours/reply_budget/rate_limit/review/render/idempotency 二次校验（防订阅推送等无事件入口绕过决策层时失守）。
- **上收到引擎**：事件分类、群触发门禁的"预判"（仅用于决定是否产生 plan；pipeline 内仍全量执行同一定律，双保险，代价是纯函数查询，已有 TTL 缓存）。
- 幂等：`_claim_event` 在 pipeline 中**保留**（pipeline.py:810），引擎侧不重复 claim，避免双表语义漂移；引擎只消费 pipeline 的 duplicate 回执决定 SILENT 展示。

### 2.4 规则逐条落地方式（§1.4 差距 → 方案）

| # | 落地 |
|---|---|
| 1 | 38 matcher → 引擎单一入口；NoneBot 侧只留 1 个 `on_message` + 1 个 `on_notice` + 1 个 `on_command`（`/bot` 保留命令前缀解析收益，内部转投引擎）或全部 `on_message`（阶段 2 决定，见开放问题 Q4） |
| 2 | 引擎注册表成为唯一入口；`INTERFACE_MANIFEST`（base_router.py:427）加 `entry_engine: bool` 审计列；CI 加 grep 检查：新增 `on_message(`/`on_command(` 出现在 `decision/` 之外即 fail |
| 3/4 | C 类直连点迁移清单（§3 阶段表逐行列出）；Mail SMTP 收编为 `UnifiedDeliveryGateway` 的 `mail_sender` 通道（网关扩展，与 B3 同一批做） |
| 5 | ActionPlan 唯一性 + 互斥组；迁移期用"决策日志比对"验证与旧 matcher 行为一致（§3 验收） |
| 7 | ActionPlan 携带 priority/risk/deadline；`decision_trace` 落库 |
| 9 | 互斥组 + IdempotencyGate；幂等键沿用 `build_event_dedupe_key`（event_idempotency.py:25） |
| 10 | `/bot why` 升级为读 `decision_trace`：输出"命中规则→门禁结果→为何静默/阻断" |

### 2.5 通知类事件的处理（戳一戳/群上传/离线文件/脏话守卫）

- 归一为 `kind="notice"` 的 `DecisionContext`，走 NoticeGate → `NOTICE_ACTION`。
- 副作用显式化：回戳改为经发送层的扩展 API 通道（现 `__init__.py:3759-3766` 的 `group_poke`/`friend_poke` 收进 `domains/transport/sender/onebot.py` 的 poke 通道函数，仍由 send 层持有 `call_api`，符合规则 4 的"统一网关"解释——网关允许按通道扩展）。
- 撤回（`delete_msg`，`__init__.py:3730`）同理收进 send 层 `moderation` 通道。
- 群文件登记（`_handle_group_upload` L3700）是纯本地副作用，保留为 NoticeExecutor 内部逻辑，不经发送层。

### 2.6 Sentinel 契约不变声明

以下契约**不改字段、不改语义、不换名字**；实现只允许"新增可选字段/新类型"：

- `CapabilityResult`（domains/core/contracts/runtime.py:209）、`BotDecision`（:184）、`PolicyEvaluation`（:170）
- `SendRequest`（:274）、`DeliveryReceipt`（:323）、`RenderedOutput`（:263）、`AuditRecord`（:336）
- `SendQueue` Protocol（domains/transport/sender/queue.py）及 InMemory/SQLite 双实现
- `UnifiedDeliveryGateway`（domains/transport/sender/gateway.py）——只允许新增通道，不允许改 `deliver()` 签名
- `RuntimePipeline.handle/handle_async`（domains/chat_reply/runtime/pipeline.py）签名不变

新增类型：`ActionPlan`、`DecisionTrace`、`AdapterSource`、`DecisionContext`（全部放 `decision/` 新模块，contracts 只在需要被 pipeline 消费时才增量挂接）。

---

## 3. 迁移路径（四阶段，每阶段可独立合入并回滚）

总原则：**引擎骨架与现行 38 matcher 并存 → 按能力逐个迁 → 删旧口**。每阶段迁移 = 把目标 matcher 的 rule+handler 改写为 ROUTE_RULES 行（如已是）+ `ActionResolver` 行 + 删原 matcher；引擎提供 `migration_mode` 配置（`legacy_only` / `shadow` / `engine_only`，键名建议 `bot_decision_engine_mode`，默认 `legacy_only`）。

### 阶段 0：引擎骨架 + shadow 模式（只记不发）

- 内容：搭 `decision/` 目录、IngressNormalizer（OneBot 先行）、CentralDecisionEngine、DecisionTrace 落库、Dispatcher（复用 A 类骨架函数）；`shadow` 模式下引擎对所有事件只算 plan 写 trace，**不产生任何发送**；旧 matcher 照常工作。
- 验收标准：
  1. shadow 运行 ≥3 天，`decision_trace` 与实际旧 matcher 命中做逐事件比对：分类一致率 ≥99%（允许边缘：visual/audio/forward 放行 chat 的特例 `_is_plain_chat_event` L3581-3589 已建模）；
  2. 引擎决策单事件耗时 P95 ≤ 5ms（纯函数 + 缓存）；
  3. `PYTHONDONTWRITEBYTECODE=1` 下跑 `dev.ps1 -Task test/lint` 全绿，新增 decision 单测覆盖互斥组/幂等/静默路径。
- 回滚：配置切回 `legacy_only`（零代码回滚）；DDL 只增表不锁旧表。

### 阶段 1：低风险旁路类迁移（4 个）

- 内容：`meme_absorb`（L3635）、`dirty_guard_matcher`（L3719）、`group_upload_notice`（L3698）、`poke_notice`（L3744）→ 引擎 `PASSIVE_ABSORB`/`NOTICE_ACTION`。同时把 poke/撤回的 call_api 收进 send 层通道（§2.5）。
- 验收标准：
  1. 群图片吸收成功率与 VLM 打标量与迁移前 7 日均值差 ≤10%；
  2. 戳一戳回戳+话术双路径实测通过（SnowLuma 真机，验收法参照 acceptance-manual）；
  3. 脏话撤回在测试群实测撤回成功、无权限群静默；
  4. 这 4 个旧 matcher 删除后 grep 无残留引用。
- 回滚：单能力粒度——`ActionResolver` 行带 `enabled` 开关（运行时热改，走 runtime_settings），关掉即回到"该能力由旧 matcher 接管"——**要求旧 matcher 删除推迟到阶段 3 复核后**（见阶段 3 内容注）。

### 阶段 2：命令类迁移（18 个）

- 内容：p=8/10/11/12/13/20/22/40 的命令与控制面：`alias`、`status`（on_command）、`mail_control`、`subscribe_cmd`、`auto_send`、`meme`、`meme_library`、`music_mode`、`file_export`、`cookie_admin`、`nickname_set`、`group_file_stats`、`file_notice`。`file_export` 的 upload 直连（L3864-3877）与 cookie QR 直发（L4012-4023）改走 B3 网关或发送层通道（若 B3 未就绪，先改走 `SendQueue.submit`，禁止保留 call_api 直连）。
- 验收标准：
  1. 全部命令在私聊+群两个环境各实测一轮（COMMANDS.md 清单对账）；
  2. `/bot routes` 审计输出（list_route_rules_for_audit，base_router.py:560）与引擎 trace 一致；
  3. shadow↔engine 对比期无行为差异工单；
  4. 优先级暗坑回归：`/bot 群文件` 在 `/bot` 存在下仍命中群文件统计（L3974 注释场景写进回归测试）。
- 回滚：同阶段 1 机制（每能力独立开关）。

### 阶段 3：查询/聊天/解析迁移（13 个）+ 直连流收编

- 内容：p=41-50 全部：`content`、`image_search`、`music`、`natural`、`moegirl_question`、`moegirl`、`wiki`、`epic`、`weather`、`market`、`divination`、`news`、`randpic`、`reminder`、`eat`、`chat`、`mail_notice`、`today_history`。同时收编背景直连流：cookie 到期提醒（L3360）、运维告警 `_deliver_admin_alert`（L2942）、订阅推送 `_deliver_v2_event`（L3212）改为构造 `DecisionContext`（来源标记 `origin=scheduler`）过引擎；Mail SMTP 出站并网关。
- 验收标准：
  1. 聊天长对话回归（人格/记忆/引用链各 3 例）；
  2. 链接解析 21 平台抽测 ≥5 平台（按 standard-parse-card-acceptance 标准）；
  3. 订阅推送真实增量一轮 + 邮件回复真机一轮；
  4. 删除全部旧 matcher 与 rule 函数，`grep -n "on_message\|on_command\|on_notice" plugins/` 只剩引擎内 1-3 处注册点。
- 回滚：本阶段合入前旧 matcher 代码先以 `git revert` 单提交粒度保留（阶段 1/2 的开关在旧代码删除后失效，故旧码删除统一放本阶段末尾，确认 14 天无回切需求）。

### 阶段 4：收尾

- 内容：`migration_mode` 删除（只留 engine 路径）；`/bot why` 接 decision_trace；INTERFACE_MANIFEST 全量 active 校对；更新 `docs/route-matrix.md` 与 HANDBOOK B2 行销项。
- 验收：全量三门禁（test/lint/runtime-layout）+ 路由矩阵文档与实现一致性抽查。

---

## 4. 风险与开放问题

### 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | NoneBot matcher 语义（priority/block/STOP）与引擎互斥组行为不完全等价，迁移期出现双回复或漏回复 | shadow 比对 + 每能力开关 + 阶段 1 先拿旁路类练手 |
| R2 | 35 入口的隐式依赖（如 `CommandArg`、`matcher.finish`、state 缓存键 `_bot_unified_route_decision` L707）被引擎路径遗漏 | 阶段 2/3 验收含 COMMANDS.md 全量对账；grep 检查清单入 CI |
| R3 | 引擎成为新单点：一处异常全 bot 失聪 | decide() 全链 try/except 兜底为 SILENT+告警（沿用 result_unknown 思想）；Dispatcher 异常走运维通知 |
| R4 | 决策耗时叠加（旧路径一次分类，引擎路径若与 pipeline 双跑门禁会增加延迟） | 引擎侧只做预判不重复执行有副作用检查；沿用 TTL-LRU 缓存；P95 预算入阶段 0 验收 |
| R5 | 直连流收编（订阅/告警/定时任务）无用户事件上下文，DecisionContext 缺 bot 句柄 | `origin=scheduler` 分支允许 bot_provider 选择逻辑照旧（`_select_queue_bot` L1281） |
| R6 | 与 B3 并行开发撞文件（sender/ 与 __init__.py 都是热点） | B2 不改 sender/ 语义只新增通道入口；约定 B3 先行做 sender 层内收敛（其阶段 1 不依赖 B2） |

### 开放问题（8 个，动工前需裁定）

1. **Q1** `/bot` 命令（on_command）是否保留 NoneBot 命令解析（CommandArg/前缀/别名机制）由引擎内重写，还是保留唯一一个 on_command 壳直投引擎？影响阶段 2 工作量约 30%。（unknown：runtime_admin.py 命令表对 CommandArg 的依赖深度需在阶段 2 排期时实测）
2. **Q2** GsCore 桥（gscore_bridge.py 回调注入）当前生产是否启用、应挂引擎哪个入口——影响阶段 3 范围。
3. **Q3** `mail_notice` 的 `block=False` p=9 与 mail 控制命令 p=10 的先后关系在引擎互斥组下如何映射（notice 类与命令类是否同组）。
4. **Q4** 阶段 4 终态：NoneBot 侧留 `on_message`+`on_notice` 两个壳（推荐），还是单 `on_message` 内部识别 notice（少一层注册，但失去 adapter 级 rule 短路）。
5. **Q5** `decision_trace` 存 SQLite 还是并入 RuntimeDiagnostic 现有存储；保留期与 `/bot why` 查询语法。
6. **Q6** 运维通知（`_notify_operational_receipt`，规则 6 豁免）是否要在 ActionPlan 里显式建 `SIDE_CHANNEL` 类型以便审计区分"第二条业务消息"。
7. **Q7** 阶段 1 开关回切的时效承诺：旧 matcher 在阶段 1/2 期间保留双份代码，是否接受期间的维护双写成本。
8. **Q8** Console 适配器（SessionType.CONSOLE 有枚举与 sender 支持，`console_chat.py` 是独立 REPL 非 matcher）是否纳入引擎入口体系。
