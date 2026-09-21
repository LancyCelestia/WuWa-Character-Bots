# U24 / R24 中央决策引擎落差审计（2026-09-20 统一性审计波）

> 席位：R24-DECISION（上一波同名席位无产出，本席从零）。只读审计；本席未改任何代码/配置/文档（除本文件），未 git 写，未跑全量 pytest，未真实发送/触网，未读 `.env` 明文值（只做键名存在性计数）。
> 证据格式：`文件:行` + 锚点字符串（行号会漂，以锚点重定位）。全部行号=2026-09-20 本席实读工作树快照。
> 真身口径：决策域真身=`plugins/bot_unified_runtime/domains/core/decision/`（v21r2 重组）；顶层 `plugins/bot_unified_runtime/decision/` 两文件均为 compat shim（锚点 `Compat shim: decision 包已迁 domains/core/decision`）。路由真身=`domains/chat_reply/runtime/base_router.py`（`runtime/base_router.py` 为 shim，锚点 `moved to plugins.bot_unified_runtime.domains.chat_reply.runtime.base_router`）。

## §0 一行结论

**「中央决策」目前不在中央：决策引擎在代码上是真骨架+假开关（engine_only 触发回落、派发接收端三层断裂、全树零生产消费者），在生产上是零运行（`.env` 无 `BOT_DECISION_ENGINE_MODE` 键、Runtime 无 `decision_trace.sqlite3`）；影子对照唯一的读取出口 `/bot decision` 生产分发链零接线（与 U7 初判独立复核一致，且本席补实：敲 `/bot decision` 只会得到一张教你敲 `/bot decision` 的帮助页）——当前不能安全接管，接管的第一件必做事是把影子跑起来并让分歧数据可读。**

## §1 现状链路图（决策引擎实际挂载点）

```
QQ/TG 事件
 → __init__.py 摄取 _incoming_from_nonebot_event（ingress.py 的 AdapterSource 骨架不在此链，零消费者）
 → 真决策＝legacy 双轨：
    ①matcher 轨：51 个 on_message/on_notice/on_command 注册（本席 grep `= on_(message|notice|command|fullmatch|startswith)(` 实测），
      谓词多数经 _cached_route_decision → base_router.classify_message_route(text)（纯文本，无 mention/回复链感知）
    ②/bot 命令轨：单一 on_command handler（锚点 `async def _handle_status(bot: Bot, event: Event, args=CommandArg())`，
      __init__.py:6486 一带）内部 34+ 个 `elif command_text ==` 手工分支——不查 RouteKind 表，除 status/help 外无引擎对应物
 → 门禁四层（全在 RuntimePipeline._prepare，pipeline.py:479 起，顺序单源固定）：
      ProductFeatureGate(484，未登记 id fail-closed) → runtime_enabled(501) → roles(522)
      → runtime_control(526) → evaluate_policy 黑白名单/主动搭话门(547，真身 domains/chat_reply/policy/gate.py:215)
      → quiet_hours(570) → reply_budget → RateLimiter.check_and_record(611) → 幂等 _claim_event(652，A-18：全门禁后置，
      duplicate 回滚限流账 653)
 → capabilities/* → Review → 输出管线 → SendQueue / 直连面
 ※ 决策引擎唯一挂载点 = pipeline.handle/handle_async 入口第 1 行
   `_observe_decision_shadow(message, capability_id)`（pipeline.py:1102 与 :1133 两处，锚点同名）——
   shadow 模式下只算 plan、写 DecisionTrace（内存 deque + 异步 SQLite），legacy_only（缺省）下两次属性读取即返回。
   引擎不产出任何发送：Dispatcher 生产零装配；ActionPlan 无任何下游消费者能执行它。
 ※ 完全绕开该观测点的流量（shadow 永不可见）：调度器族 12 族（登记表枚举）、C 类直连、on_notice 事件、
   未命中任何 matcher 的静默消息（根本没进 pipeline）。
```

## §2 逐条发现

### D1 「中央决策」实然形态

#### 部件接入状态总表（逐部件 grep+调用链证据）

| 部件（真身坐标） | 公开面 | 实际接入状态 | 证据 |
|---|---|---|---|
| `domains/core/decision/engine.py` `CentralDecisionEngine` | decide/decide_with_trace | **仅 shadow 观测**（且生产从未运行） | 唯一生产入口=shadow.py `_get_engine()`；shadow 唯一钩子=pipeline.py:1102/:1133；生产模式=legacy_only（见 F-5） |
| `shadow.py` | observe_pipeline_event/resolve_decision_mode | 已接线、被缺省配置关闭的休眠旁路 | 消费者= pipeline.py 锚点 `_observe_decision_shadow` |
| `dispatcher.py` `Dispatcher` | dispatch(plan, ctx) | **完全孤儿（生产零 import）** | grep `decision.dispatcher\|decision import Dispatcher`：命中=仅 tests（test_decision_engine_shadow.py:24、test_v21_dispatch_outbound_wiring.py:43、test_v21_risk_red_dispatch_and_telegram.py:26）；根 `__init__.py` grep `decision` 无 Dispatcher 装配（L5043 一带 import 的是 control_plane.dispatcher 执行器，不是中央 Dispatcher） |
| `ingress.py` `AdapterSource/OneBotSource/TelegramSource/DEFAULT_SOURCES` | 归一化插件点 | **完全孤儿**（`DEFAULT_SOURCES` 全树零消费者，含测试）；OneBotSource 仅测试 import（test_decision_engine_shadow.py:402/:412） | grep `DEFAULT_SOURCES\|AdapterSource` 排除 ingress.py 自身与包 `__init__` → 零命中；摄取生产链仍走 `__init__. _incoming_from_nonebot_event` |
| `trace.py` 记录侧 `SqliteDecisionTraceSink.record` | shadow 落盘 | 已接线、休眠（同 shadow）；**生产从未产生过一行** | `ChatBot_Runtime/decision_trace.sqlite3` 不存在（本席 `ls` 实证）；`.env` 键计数 `grep -c "^BOT_DECISION_ENGINE_MODE" .env`=0 |
| `trace.py` 查询侧 `recent()` | 供 /bot decision | **唯一消费者是生产不可达的 builder**（见 F-1）；其余消费=tests + scripts/e2e_acceptance.py:547（离线验收夹具，非生产） | grep `get_decision_trace_sink`：生产命中仅 echo.py:189（build_decision_query_result 内），该函数全树无生产调用方 |
| `outbound.py`/`outbound_contracts.py`/`outbound_registry.py` | OutboundIntent/Transport 固定映射/准入租约 + 入口接管登记表 | **契约+登记表有真生产消费者，但不经引擎**：poke 回戳/贴表情经 `control_plane/dispatcher.py:17` `from plugins...domains.core.decision.outbound import` + `__init__.py:5043` 一带装配（矩阵 V21-DELIVERY-001/DISPATCH-001 所记「收编门面」）；`build_default_takeover_registry` 生产零消费者（消费=仅 tests/test_campus_digest.py、test_outbound_v21.py、test_v21_s0_collect.py） | 见 F-2/F-4 计数 |
| `decision/__init__.py`、`decision/trace.py`（顶层） | compat shim | 活垫片；echo 查询侧 import 走旧路径 `plugins.bot_unified_runtime.decision.trace`（echo.py:188 锚点），仍解析到真身 | shim 锚点 `Compat shim: decision 包已迁 domains/core/decision（v21r2 重组 RWOC 尾声波）`；decision.trace 在 RET2b 挂起清单（HANDOFF-V21R5 §131/240） |

#### 双脑实况（legacy 真决策 vs 影子决策）——结构性规则差异清单

两脑**共用同一个分类函数**（engine.py:37 `from plugins.bot_unified_runtime.runtime.base_router import ... classify_message_route`，经 shim 到真身；engine docstring 锚点 `ROUTE_RULES 与其 TTL-LRU 缓存不动`），所以分歧不来自算法分叉，而来自**输入面、覆盖面、语境面**三处不同构：

1. **输入面不同构**：`classify_message_route(text, config, alias_resolver)` 是纯文本函数（真身 base_router.py:689 一带，锚点 `def classify_message_route`）；legacy matcher 谓词持有 NoneBot Event（@提及、回复链、语音段、notice_type、段级 URL/json）。引擎仅建模了两个段级特例（engine.py `_urls_from_segments` 与 `_has_media_segments`，锚点 `_is_plain_chat_event 特例`），其余事件语境缺失即判定不同构。base_router 全文件 grep `mention` 零命中——@提及驱动进群聊天在分类器里根本不存在。
2. **裁决面不同构**：legacy 是 51 个 matcher 的 priority/block 竞态（含 6 个 `block=False` 旁路监听），单次消息可触发多 handler；引擎=单事件单 ActionPlan + `BYPASS_ABILITIES` 仅 2 条（meme_absorb/dirty_guard，engine.py:100-107 锚点 `旁路型能力注册表`）。且**旁路面在影子中是死的**：`observe_pipeline_event` 构造 DecisionContext 从不传 `bypass_capability_id`（shadow.py:220-226 锚点 `context = DecisionContext(`，字段缺省 ""），plan_for_bypass 生产影子路径永不触发。
3. **准入门不在引擎**：引擎把 Mute/Idempotency/Audience 三环写成 `allowed=None` 移交现行 pipeline（engine.py:250-298 锚点 `shadow: 幂等由 pipeline._claim_event 独占`）——即影子只比「谁处理」，不比「是否处理」。接管后这四层归谁（见 D2）没有裁决。
4. **命令轨不同构**：/bot 子命令面是 `_handle_status` 的 34+ 手工 elif 分支，每分支自带 capability 细分（bot.memory/bot.help/bot.logs/bot.model…）；ROUTE_RULES 的 ADMIN 规则只回一个笼统 `RouteKind.ADMIN/"bot.status"`（base_router.py 锚点 `管理员命令（/bot …）`）。影子等价表把 admin 映射为 {bot.status, bot.routes, bot.route}，/bot 链真实入口能力（bot.help/bot.logs/bot.poke 等）不在表内 → 全部记「不可比」。
5. **覆盖面有硬缺口**：对照表 `_ROUTE_KIND_LEGACY_EQUIVALENTS` 只覆盖 25/34 RouteKind，未建模 9 个：`bond/commodities/daily_assist/fx/group_info/media_archive/northbound/stocks/tts`（本席实跑探针输出，见 F-3）；表数据源注释自述为「2026-09-12 grep 盘点」（shadow.py:146-148 锚点 `数据来源：__init__.py 全部 pipeline 入口`），无同步门，随路由表演化单调过时。

#### 接管开关的真实语义（D1.4）

- 取值集合：`SUPPORTED_MODES={legacy_only, shadow}`；`RESERVED_FUTURE_MODES={engine_only}`；非法/未启用值一律回落 legacy_only（shadow.py:34-38/:50-63，锚点 `RESERVED_FUTURE_MODES = {"engine_only"}`、`normalize_decision_mode`）。
- 解析链：nonebot driver config → 进程 os.environ → 缺省，逐事件解析（shadow.py:66-86 锚点 `resolve_decision_mode`）。**不读插件 Config、不读 runtime_settings 覆盖**：`BOT_DECISION_ENGINE_MODE` 不在 SETTABLE_KEYS 也不在 RESTART_REQUIRED_KEYS（`domains/chat_reply/runtime/settings.py:333/:454` 两表 grep `DECISION` 零命中）→ 运行时改键被拒且拒语不提示需重启；**唯一改法=改 .env + 重启**。
- 开启后现网会变什么：`shadow`＝主链行为零变化（钩子 fail-open，shadow.py:15 锚点 `全链 fail-open`），新增的是每事件一次纯函数分类 + deque + 异步 SQLite 写（Runtime 目录首次出现 decision_trace.sqlite3）；`engine_only`＝**什么都不变**（回落 legacy_only + 一条 warning），因为派发接收端不存在（F-2）。

### D2 四层判定重叠矩阵（要不要处理/谁处理/能不能处理）

| 层 | 载体（真身） | 输入 | 判定 | 拒绝后对外表现 | 审计记录 |
|---|---|---|---|---|---|
| L1 路由 | base_router ROUTE_RULES 33 条规则（锚点 `ROUTE_RULES: list[RouteRule] = build_route_rules()`，真身:591）+ 51 matcher 竞态 | Event（谓词各异性）+纯文本分类 | 谁处理/不处理 | IGNORE＝**无声无息，零回执零审计**（无任何一行记录「这条被不回复」） | 无 |
| L2 功能门 | ProductFeatureGate（domains/ops/features/feature_gate.py:35），pipeline._prepare 首位（:484） | (message, capability_id) | 功能是否在岗 | BLOCKED 回执「这项功能暂时不可用。」+ audit event=reason；**未登记 id fail-closed**（U3 实锤：bot.file/group_welcome 等 4 id 未登记→管理端 21 处出站文案被吞；本席复认坐标 pipeline.py:487-488 锚点 `feature_state_unavailable`） | AuditRecord stage=policy |
| L3 门禁 | policy/gate.py:215 evaluate_policy + quiet_hours + reply_budget + RateLimiter（pipeline.py:547/570/603/611） | message+capability（SQLite 限流装配期快照=台账#3 同族） | 黑白名单/安静时间/额度 | BLOCKED 回执「该场景下未启用主动回复。」；**群聊静默失败特例把回执清空**（pipeline.py:458-473 锚点 `is_group_silent_failure`）→ 同一层两种对外表现（私聊有文案/群聊静默） | AuditRecord event=quiet_hours_blocked/rate_limited 等 |
| L4 幂等 | EventIdempotencyTable，`_claim_event`（pipeline.py:652，锚点 `审查 A-18：幂等 claim 移到全部门禁`） | request/事件键+capability | 重复投递 | duplicate 回执（静默）+限流账回滚(653) | 无专属 event 名（走 _duplicate_receipt） |

1. **同一决定两处表达、表现不一致**：功能门拒（L2）给「这项功能暂时不可用。」+policy 审计；路由拒（L1）完全静默无审计；同一「不响应」的用户可见形态相差一个量级。且 L2 未登记 id 与 L2 已登记关闭在审计里都是拒绝，但根因不同（配置缺失 vs 主动关闭）——U3 已定 P1，本席不重复记账只引用。
2. **判定顺序单源性**：pipeline 内顺序单源固定（上表 L2→L3→L4，_prepare 一次读尽）；但**引擎决策链顺序与现网顺序不同构**：engine docstring 钉的是 `NoticeGate → MuteGate → IdempotencyGate → Router → AudienceGate → ActionResolver`（engine.py:8-9 锚点 `决策链顺序固定`），即幂等**前置于**路由/受众；现网是路由最先（matcher 竞态）、幂等最后（A-18 修复明确「被拦事件不许消耗幂等键」，pipeline.py:645-650 锚点）。接管时若照引擎现序落地，会把 A-18 修掉的「重发被当 duplicate 吞掉」缺陷**原样复活**——这是七要素级的根因条目（发现 F-6）。同族先例=U4 所记 SQLite/InMemory 限流顺序不一致（已修）。
3. **接管后四层归属建议（明确切分，不笼统）**：必须留中央＝L1 路由表 + L4 幂等（规格 §2.3.4 pipeline 独占 claim 的裁决**应反转归中央**，否则中央永远要回读旁路）+ 群黑白名单（L3 的 audience 部分）；必须留通道＝Transport 固定映射/租约/call_api 本体（outbound_registry 已定义 BY_DESIGN/CHANNEL_BODY 语义，锚点 `SendQueue worker 合法通道本体，非绕行`）；应并入路由表＝`_handle_status` 的 34+ elif 命令轨（现 ADMIN 一条笼统规则必须先细化成 per-command 行，否则接管后 /bot 全家族退化成 bot.status）+ 调度器族 12 族的触发语义（登记表 EntryKind.SCHEDULER 已有位，状态全 legacy）。

#### 编号发现清单（七要素）

**F-1｜P1｜`/bot decision` 生产分发链零接线：影子证据的唯一查询出口在生产不可用，帮助页还在教一条用不了的命令**
- 坐标：`plugins/bot_unified_runtime/__init__.py:6486-7189`（/bot 命令链，锚点 `async def _handle_status(bot: Bot, event: Event, args=CommandArg())`）；`domains/chat_reply/runtime/aliases.py:187-188`（锚点 `"决策": "bot.decision",`）；`domains/chat_reply/capabilities/echo.py:160`（锚点 `def build_decision_query_result`）；`domains/chat_reply/runtime/capability_registry.py:528`（锚点 `HelpTopicDecl(topic="决策", admin_only=True, capability="/bot decision")`）。
- 根因：登记四层齐备（verb map / help topic / `_HELP_ENTRIES` echo.py:2430 一带 / 命令规格清单 echo.py:3144-3148），但 /bot if/elif 链 34+ 分支无 decision 分支，末尾兜底 `elif command_text != "status":`（锚点同前）把任何未知子命令转 help；昵称路径 `bot.decision` 落 `_handle_alias` 的 else（锚点 `昵称命令 /{resolution.verb} 请在 /bot 形式下使用`）只回一句引导。
- 证据：本席独立复核——`grep -rn build_decision_query_result plugins/` 生产命中仅 echo.py 定义处，零调用方；调用方只有 `tests/test_decision_trace_persistence.py:18` 与 `scripts/e2e_acceptance.py:80/:547`（离线验收夹具）。**净效果：生产里敲 `/bot decision` 得到一张帮助主题页，页内【示例】写着 `/bot decision`（echo.py:2448 锚点 `【示例】/bot decision ｜ /bot decision 50`）——命令教自己，永远停在帮助页**（与 U7 初判相互独立地一致；本席补此闭环形态）。
- 影响：接管决策所需的分歧数据在 QQ 生产面无任何读取路径；管理员按文档操作只会得到循环指路。
- 改法：before=/bot 链无分支 → after=在 `_handle_status` elif 链新增 `elif command_text == "decision" or command_text.startswith("decision "):` 分支接 `build_decision_query_result(actor_roles=..., query=...)`（**复用既有 logs 分支同构先例，不建第三条旁路**）。
- 验证：`dev.ps1 -Task test` 相关族 + scoped `tests/test_decision_trace_persistence.py`（现 59 passed 基线见 F-5）+ 真机 `/bot decision 20` 返回痕迹列表（重启后）。
- 归属：后端统一（决策/命令交叉面）；命令面登记普查归 U7。

**F-2｜P1｜接管接收端三层断裂：engine_only 假开关 + ActionPlan↔Dispatcher 接口断裂 + 中央 Dispatcher 生产零装配——「拨开关即接管」在代码上不成立**
- 坐标：`domains/core/decision/shadow.py:36-38`（锚点 `RESERVED_FUTURE_MODES = {"engine_only"}`）+ `:50-63`（回落 legacy_only）；`domains/core/decision/engine.py:70-84`（ActionPlan 字段册，锚点 `class ActionPlan`）；`domains/core/decision/dispatcher.py:68-84`（锚点 `intents = [` 与 `"no_outbound"`）。
- 根因：①`engine_only` 一律回落 legacy_only（诚实的 fail-closed，文档口径一致）；②`Dispatcher.dispatch` 只消费 `plan.outbound_intents`，而 `ActionPlan` 冻结 dataclass **无此字段**，全树 `grep outbound_intents plugins/` 除 dispatcher.py 自身外零命中=无任何生产者；③文本/卡片能力派发 dispatcher docstring 自认「仍属迁移阶段 2+」（锚点 `能力派发（复用 _run_capability_through_pipeline A 类骨架）仍属迁移阶段 2+`）；④`Dispatcher` 生产零 import（见总表），影子钩子也从不传 `bypass_capability_id`（shadow.py `context = DecisionContext(` 五参构造，锚点同前）→ BYPASS_ABILITIES 在活体影子中亦为死面。
- 证据（实跑）：`$TEMP/r24_probe1.py` 输出——`has outbound_intents field: False`；对真实 ActionPlan 以 `engine_only` 语境 + 已绑 executor 调 dispatch，返回 `DispatchOutcome(status='no_outbound', detail='engine_only plan carries no outbound intent')`。测试全绿是因为测试用 `SimpleNamespace(outbound_intents=[...])` 鸭子对象（tests/test_v21_dispatch_outbound_wiring.py:301-327 锚点 `DecisionDispatcher(`），掩盖了真实类型断裂。
- 影响：所谓「接管待阶段 2」的真实含义被本席定量为：缺 ①plan 载荷字段设计+生产者 ②Dispatcher 生产装配 ③能力派发周期实现，三段全无代码——接管不是配置债而是结构性代码债。
- 改法：先补 ActionPlan 载荷契约（或重定义 Dispatcher 输入协议）并加类型锁测试（禁鸭子对象：断言真实 ActionPlan 必走通），再谈 engine_only 解锁。
- 验证：新增锁测试 + scoped 复跑 59 passed 不回归。
- 归属：决策域（B2 阶段 1/2 本体）。

**F-3｜P2｜影子对照表覆盖缺口+无同步门：34 个 RouteKind 只建模 25 个，新面路由永久「不可比」**
- 坐标：`domains/core/decision/shadow.py:149-175`（锚点 `_ROUTE_KIND_LEGACY_EQUIVALENTS: dict[str, frozenset[str]] = {`）；表源注释 `shadow.py:146-148`（锚点 `数据来源：__init__.py 全部 pipeline 入口的 capability_id 字面量盘点（2026-09-12 grep）`）。
- 证据（实跑）：`$TEMP/r24_probe3.py` → `RouteKind total: 34 modeled kinds: 25`；未建模 9 个=`bond/commodities/daily_assist/fx/group_info/media_archive/northbound/stocks/tts`（即 09-12 之后上车的全金融面/媒体归档/每日助理/TTS 等）；`_MODELED_LEGACY_CAPABILITIES=25` vs `__init__.py` 里 `capability_id="bot.*"` 字面量 31 个（bot.file/bot.poke/bot.reply/bot.search/bot.mail.*/bot.group_welcome… 不在表内）+`/bot` 链的 bot.help/bot.memory 等。
- 根因：人工快照表、无「RouteKind 枚举 ⊆ 对照表键集」一致性门（route-matrix 覆盖门不查此表）。
- 影响：agree=False 只在「两侧都已建模」时给出（compare_with_legacy 设计如此，锚点 `agree=False 仅在`）——设计正确地防稀释，但代价是**新领域的分歧根本无法表达**；一致率只对历史子集有效。
- 改法：补 9 kind+新增能力映射 + 新增一致性测试（RouteKind 全值必须出现在表或显式豁免清单）。
- 验证：新增测试 + `pytest tests/test_decision_engine_shadow.py`。
- 归属：决策域。

**F-4｜P2｜shadow 观测面=会话式 A/B 管线事件；调度器族/直连/notice/未命中消息零影子——接管依据只覆盖半壁流量**
- 坐标：`shadow.py:13-15`（锚点 `C 类直连与 notice 不经 pipeline，是本阶段影子覆盖的已知边界`）；`outbound_registry.py` 调度器族 12 条全部 `MigrationStatus.LEGACY`（本席 `$TEMP/r24_probe2.py` 实跑：`matchers: 50 {'legacy': 50} checklist_incomplete=50/50`、`schedulers: 12 {'legacy': 12}`、`direct_sends: 12（bypass_suspect 4）`）。
- 根因：钩子物理位置在 `pipeline.handle/handle_async` 首行；不经过 pipeline 的触发（U4 所记「第二/第三分发器」同族）对引擎不可见。
- 影响：AGENTS 宣称 shadow「与 legacy 做影子对照」——对照样本先天缺全部主动出站流量；接管评估若以 shadow 数据为准会系统性低估风险面。
- 改法：接管前置条件 G6（入口收编）完成后自然消除；短期在报告/决策依据里显式声明样本边界。
- 验证：登记表 status 迁移计数（probe2 复跑）+收编族回归。
- 归属：决策域×分发域（U4/S0 交叉）。

**F-5｜P2｜影子从未在生产运行过一天，且「一致率≥99%」验收标准无任何测量出口——阶段 0 验收形式上不可判定**
- 坐标：规格 `docs/design/central-decision-engine.md:274`（锚点 `shadow 运行 ≥3 天` + `分类一致率 ≥99%`）；`config-catalog-full.md:771`（锚点 `_decision_engine_mode | legacy_only`）；本席取证：`grep -c "^BOT_DECISION_ENGINE_MODE" .env` = **0**（只数键名未读值）；`.env.example` 计数=0；`ls ../ChatBot_Runtime/decision_trace.sqlite3` = **不存在**；聚合出口取证：decision 域与 echo 查询段 `grep COUNT(*)` 零命中，sink 查询面只有逐行 `recent(limit)`（trace.py:300，锚点 `def recent`）。
- 根因：接管判据依赖的数据管道三段全断——没人开模式（键缺省即关闭）→ 开了也没有聚合/一致率计算 → 逐行出口 F-1 又不可达。
- 影响：「Phase-1 shadow 记录分歧」目前是**无一行实证的生产陈述**（AGENTS 台账 P95 0.039ms 是性能数，不是语义数；本席按 mandate 问语义：无任何分歧率数据存在）。离线旁证：scoped 4 件 **59 passed**（`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 …pytest tests/test_decision_engine_shadow.py tests/test_decision_trace_persistence.py tests/test_v21_dispatch_outbound_wiring.py tests/test_v21_risk_red_dispatch_and_telegram.py --basetemp=$TEMP/r24-tests -p no:cacheprovider`，2026-09-20 实跑）——**离线绿≠生产有数据**，恰相反：生产零数据已被上面三件取证钉死。
- 改法：G1（查询出口）+G2（agree 聚合出口：分歧率/不可比率分桶计数）→ 用户拨 `.env` 开 shadow ≥3 天 → 以真数据裁决阶段 0 验收。
- 验证：shadow 段后 `decision_trace.sqlite3` 存在 + `SELECT agree, COUNT(*) GROUP BY agree` 手工可跑 + `/bot decision` 出真数据。
- 归属：决策域（工具）+用户裁决债（开不开 shadow、观察几天）。

**F-6｜P2｜引擎决策链幂等前置 vs 现网幂等后置（A-18 修复语义）顺序相反——按引擎现序接管会复活「被拦重发被 duplicate 吞」缺陷**
- 坐标：`engine.py:8-9`（锚点 `决策链顺序固定：NoticeGate → MuteGate → IdempotencyGate → Router`）；`pipeline.py:645-651`（锚点 `审查 A-18：幂等 claim 移到全部门禁…旧序 handle 先 claim 再 _prepare，被拦事件也消耗幂等键，同一条被拦消息的重发（用户重试）会被当 duplicate 吞掉`）+ `:652 _claim_event` 后置 + `:653` 限流账回滚。
- 根因：阶段 0 文档锁的链序早于 A-18 修复，两侧未对账。
- 影响：接管实现若照抄 engine docstring 顺序＝回归已修复缺陷（拒绝先于审计/幂等先于门，正是任务书点名的同族顺序病）。
- 改法：before=docstring 链序=旧语义 → after=链序文档改为「路由→门禁→（后置）幂等」并把 claim 语义在阶段 1 落地时随迁；加语义锁测试钉死「幂等必在 audience/mute 判定之后」。
- 验证：新增锁测试 + `pytest tests/test_a18_gate_idempotency_rollback.py`（U4 已证表现绿，接管改造后须仍绿）。
- 归属：决策域。

**F-7｜P3｜`Config.bot_decision_engine_mode` 字段是执行侧零消费者的二源镜像**
- 坐标：`config.py:236`（锚点 `bot_decision_engine_mode: str = "legacy_only"`）+ `:999-1006`（锚点 `_normalize_decision_engine_mode`，其合法集含 `engine_only` 原样放行，与 shadow.normalize 的回落语义不一致）；执行侧读取的是 driver.config/os.environ（`shadow.py:74-81` 锚点 `getattr(nonebot.get_driver().config, DECISION_MODE_CONFIG_KEY, None)`）。
- 证据：`grep -rn bot_decision_engine_mode plugins/` 生产命中=config.py 两处+shadow 常量/docstring，无任何读插件 Config 判模式的代码。
- 影响：两套归一化合法集不同（Config 放行 engine_only、shadow 回落）；字段进 529 字段机器册但改它不改变行为——「配置面登记/执行面消费」错位同族（台账 #3 热改族旁支）。
- 改法：resolve 链增加插件 Config 级（或删字段留 env/driver 单源），二选一，禁三源。
- 验证：test_decision_engine_shadow.py:344-350 Config 归一段 + 新增「改 Config 字段不改行为/改 env 改行为」显式断言。
- 归属：配置面（U6 交叉）。

**F-8｜P3｜matcher 数口径漂移三处：35/38/51/50**
- 坐标：`engine.py:6`（锚点 `引擎与现行 35 matcher 并存`）；`central-decision-engine.md:237`（锚点 `38 matcher → 引擎单一入口`）；本席实测 `grep -cE "= on_(message|notice|command|fullmatch|startswith)\(" __init__.py`=51；登记表 matchers=50（probe2）。
- 影响：接管工作量与「逐入口收编」完整性判断的基线数不实。
- 改法：以登记表现为单一事实源，文档数字改为「以 `build_default_takeover_registry()` 计数为准」或机器册投影。
- 验证：probe2 复跑数与文档一致。
- 归属：文档债。

**F-9｜P3｜ingress.py 为纯孤儿骨架，且 OneBotSource 反向 import 根 `__init__` 私有函数**
- 坐标：`ingress.py:41`（锚点 `from plugins.bot_unified_runtime import _incoming_from_nonebot_event`）；消费者=grep 零命中（DEFAULT_SOURCES 全树无引用，含测试）。
- 影响：摄取归一（mandate「一切先经中央」的第一跳）零进度；且域→根的函数内反向依赖是 U5 所计反向边家族的新样本（虽 fail-open 于惰性导入，仍属方向违例）。
- 改法：接线前把归一实现迁至域内正身、根侧转调；或直接裁定退役该骨架。
- 验证：AST 反向边门（U5 体系）。
- 归属：决策域×架构收编（U5 交叉）。

**F-10｜P3｜trace 无门禁语境/终态字段：agree 只比「谁处理」，不比「该不该回复」**
- 坐标：`trace.py:61-79`（DecisionTrace 字段册，锚点 `class DecisionTrace`——无 gate/budget/quiet/幂等结果字段，无 receipt state）；观测时机 `pipeline.py:1102`（handle 首行，先于 `_prepare` 全部门禁）。
- 影响：影子数据无法回答接管验收的真问题「若引擎接管，用户可见结果是否相同」——被门拦掉的事件与放行事件在 trace 里同形；request_id 可与 AuditRepository 手工 join，但无任何查询工具做此关联（F-1/F-5 同害）。
- 改法：trace 增 legacy_gate_outcome 二段记录（_complete/duplicate/blocked 回填），或提供 join 查询出口。
- 验证：新字段序列化往返测试（test_decision_trace_persistence 同族扩展）。
- 归属：决策域。

**F-11｜P3｜验收矩阵 V21-DISPATCH-001 implementation 列表述误导：「decision dispatch 真实派发周期」实为 control_plane 执行器周期，中央 Dispatcher 本体零生产消费者**
- 坐标：`backend-v2-acceptance-matrix.md:36`（该行，锚点 `V21-DISPATCH-001`；列文 `OutboundSideEffectExecutor 统一出站执行器+decision dispatch 真实派发周期`）；production_wiring 列自己已如实记 `engine_only 触发点生产侧无调用方`。
- 判定：**三列无一虚称 wired**（矩阵诚实），但 implementation 列把「门面 DTO+旁路执行器在位」表述成近似「中央派发已运转」，与 F-2 实测对照易被接手方高估进度。
- 改法：该列补限定语「（派发=统一出站执行器；CentralDecisionEngine/Dispatcher 本体未接）」。
- 验证：文档 diff 复核。
- 归属：文档债（矩阵回填席）。

### D3 V2.1 合同与实况对账（决策/分发线）

承诺清单（规格原文短句→实况三态）：

| # | 承诺（坐标+锚点） | 三态 | 证据 |
|---|---|---|---|
| C1 | 单入口/单次分类/单一 ActionPlan（central-decision-engine.md §2.3.2，锚点 `ActionPlan 唯一性 + 互斥组`） | **已实现未接线**（引擎内成立，生产派发不消费） | F-2（probe1：真实 plan 走不到任何动作） |
| C2 | shadow 逐事件比对 ≥3 天、一致率 ≥99%（:274 锚点 `shadow 运行 ≥3 天`） | **规格有、工具半有、生产零运行**：比对逻辑有、测量/聚合出口无、模式从未开 | F-5 |
| C3 | AdapterSource 摄取归一（§2.3.1，锚点 `规格 §2.3.1 接口草案`） | **规格有代码无接线**（骨架在、零接线、生产摄取仍旧链） | F-9 |
| C4 | Dispatcher 出站收编（guide §10 锚点 `逐能力迁移…接管后旧 matcher 只转交，同事件同幂等键`；OutboundIntent 全字段） | **已实现且接线（限 poke/贴表情两组副作用，待重启生效）**——但「同事件同幂等键」在 F-10 语义下未被影子验证过 | `__init__.py:5043` 一带装配 + 矩阵 DELIVERY-001；离线≠生产生效 |
| C5 | 阶段 1 每能力 `enabled` 热改回滚开关（:287 锚点 `ActionResolver 行带 enabled 开关（运行时热改，走 runtime_settings）`） | **规格有代码无**：ActionResolver 无 enabled 面（engine.py grep `enabled` 仅命中 bot_chat_enabled），SETTABLE_KEYS 无决策键 | D1.4 取证 |
| C6 | 启动门拒绝未登记入口/出站绕行（guide §10 锚点 `启动门拒绝未登记入口/出站绕行`） | **规格有代码无**（service_wiring 零命中；bypass_suspect 4 条仍在岗） | grep 零命中 + probe2 |
| C7 | 38/51 matcher→引擎单一入口，按能力逐个迁、删旧口（§3 锚点 `删旧口`） | **0/50 开始**：登记表 50 matcher 全 legacy、接管三问 0/69 完成 | probe2 |

矩阵对账（决策/路由/分发/出站/门控相关行逐核，live 列全 0 属预期不重报）：V21-DISPATCH-001（见 F-11，判定=不虚称 wired）、V21-DELIVERY-001/002（收编表述与代码相符，「待重启」标注诚实）、V21-TRACE-001（「无生产写入方保持」诚实）、V21-REG-001/002（U2 地盘不重报）、V21-SCHEDULE-003（安静时间=门禁线，U10 地盘）。**「矩阵说 wired 但代码零接线」=0 条；「矩阵 not_wired 但代码已接线」=0 条；表述误导 1 条（F-11，P3）**。与 U4「无过度宣称」结论一致，本席在其上补充的是 §〇 层面的总账：诚实的 partial ≠ 可接管。

### D4 接管前置条件清单（按依赖排序）

| 序 | 前置条件 | 阻塞什么 | 具体动作（文件级→函数） | 债型 | 动现网风险 |
|---|---|---|---|---|---|
| G1 | `/bot decision` 接进生产分发链（或裁撤四层登记） | 分歧数据无读取出口→接管验收不可证（F-1） | `__init__.py _handle_status` elif 链加 decision 分支接 `echo.build_decision_query_result`（复用 logs 分支先例） | 代码债 | 低（新增 admin 查询分支；**会改 QQ 面=需重启验收**，标红但影响面极小） |
| G2 | agree/不可比率聚合出口 | 一致率无测量→C2 验收不可判（F-5/F-10） | `decision/trace.py` 增分桶计数（recent 旁挂 aggregate）+ G1 出口展示 | 代码债 | 无（旁路只读） |
| G3 | 对照表补 9 RouteKind+一致性门 | 新领域分歧不可表达（F-3） | `shadow.py _ROUTE_KIND_LEGACY_EQUIVALENTS` 补表 + `tests/` 加「RouteKind 枚举⊆表∪豁免」门 | 代码债 | 无 |
| G4 | shadow 钩子补旁路语境传参 | BYPASS 面死代码（F-2④） | `shadow.observe_pipeline_event` 增 bypass 入参并由 pipeline 侧 matcher 元数据提供 | 代码债 | 低（仅影子数据形态） |
| G5 | ActionPlan 载荷契约补全 + Dispatcher 生产装配 + engine_only 真语义（=规格阶段 1/2 本体） | 接管无接收端（F-2） | `engine.ActionPlan` 增 intents 字段+生产者；`__init__.py` 装配中央 Dispatcher；派发周期复用 `_run_capability_through_pipeline` | 代码债（大宗） | **高，标红**（改 QQ 主通道行为，须重启+acceptance 全流程） |
| G6 | 入口/出站收编：50 matcher、12 调度器族、7 控制面路由组三问补齐→逐点接管；4 条 bypass_suspect 归咽喉 | 观测与派发的样本半壁缺口（F-4）；S0 在飞面 | `outbound_registry.build_default_takeover_registry` 逐项 checklist 落答案→status 迁移 | 代码债+用户裁决债（哪些调度器许接管） | **高，标红** |
| G7 | 生产开 shadow ≥3 天（G1-G3 之后才有意义） | 无一日影子实证（F-5） | 用户动作：`.env` 置 `BOT_DECISION_ENGINE_MODE=shadow` + 提权重启；此后数据经 G1/G2 读 | **用户裁决债**（开/何时开/观察期） | 主链行为零变化（fail-open），但新增 SQLite 落盘与线程 |
| G8 | 判定顺序单源裁决（引擎链序对齐 A-18 语义；四层职责按 D2.3 切分） | 照序接管=复活已修缺陷（F-6） | 规格文本 + 语义锁测试 | 代码债+用户裁决债（拒绝对外表现统一口径：静默 vs 回执哪种） | 中（接管期才显形） |
| G9 | 规格开放问题 Q1-Q7 裁决（on_command 壳形态等） | 阶段 2 工作量与形态未定（AGENTS 台账 #4 同条） | `central-decision-engine.md` §开放问题逐条 | **用户裁决债** | — |

**当前能否安全接管：不能。** 第一件必做的事=**G1+G2（把分歧出口接通并加聚合）**，随后 G7（开 shadow 跑满观察期）——在此之前任何接管裁决都是在无数据条件下签字；G5 三断裂是比开关更深的代码债，缺它连「拨了开关会发生什么」都无法在代码层回答。

## §3 严重度分布

**P1×2（F-1、F-2）｜P2×4（F-3、F-4、F-5、F-6）｜P3×5（F-7、F-8、F-9、F-10、F-11）＝11 条。** 交叉引用不重复计：U3 功能门吞消息（其 P1）、U4 调度器旁路、U7 命令登记普查、U2 S10 零消费者——本席只引用作前置证据，不另立条。

## §4 接管路线的门槛清单

见 D4 表 G1-G9（依赖序即表序）。一句话版：**先让数据可读（G1/G2），再让数据可比（G3/G4），再让数据存在（G7），同时补接收端代码（G5/G6），全程夹两项用户裁决（G8 口径、G9 形态）——九门齐开之前，`BOT_DECISION_ENGINE_MODE` 保持 legacy_only 是唯一诚实状态。**

## §5 未覆盖清单

1. webui/、domains/render/**、card_render、theme_tokens、TTS/语音面：本席按禁改令未审（含「webui 是否另有 decision trace 读取端点」未核——若有，F-1 的「唯一出口」限定于后端 Python 分发链）。
2. 控制面 `/api/v1` 各端点与决策域的关系归 U20，本席仅核 plugins 侧消费者 grep。
3. `.env` 只数键名未读值：若生产以**进程环境变量**（非 .env）注入 BOT_DECISION_ENGINE_MODE，本席取证不覆盖（os.environ 分支）；ChatBot_Runtime 无 decision_trace.sqlite3 已从侧面证否「生产曾跑过 shadow」。
4. 常驻生产进程（旧版码）与当前工作树的行为差异：本席全部结论=工作树快照；矩阵 live 列全 0 属预期，未重报。
5. git 历史比对（行号漂移归因）未做——并行会话改写中，锚点字符串为准。
6. `decision_trace` 与 AuditRepository/receipt 的 request_id join 可行性仅静态断言「可手工 join」，未做关联查询实作验证。

## §6 树卫生自查

本席取证全部用 `-B` + `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest 用 `--basetemp=$TEMP/r24-tests -p no:cacheprovider`；探针脚本 `$TEMP/r24_probe1.py / r24_probe2.py / r24_probe3.py` 全在树外。自查计数见本席收尾实跑（§6 末表）：源码树 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/`data/` 计数与 qx.json 存在性——**（回填于收尾实跑后）**。

---

### 附录 A：本席实跑命令与输出（证据复跑件）

| 命令（全部带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，解释器 `../ChatBot_Runtime/venv/Scripts/python.exe -B`） | 输出（原样） |
|---|---|
| `$TEMP/r24_probe1.py`（ActionPlan×Dispatcher 断裂） | `has outbound_intents field: False`；`dispatch(real ActionPlan, engine_only) -> DispatchOutcome(status='no_outbound', detail='engine_only plan carries no outbound intent')` |
| `$TEMP/r24_probe2.py`（接管登记表清点） | `matchers: 50 ({'legacy': 50}, 'checklist_incomplete=50/50')`；`schedulers: 12 ({'legacy': 12}, 'checklist_incomplete=12/12')`；`route_groups: 7 (…, 7/7)`；`route total: 62`；`direct_sends: 12 Counter({'bypass_suspect': 4, 'by_design': 4, 'channel_body': 2, 'read_path': 2})` |
| `$TEMP/r24_probe3.py`（对照表覆盖清点） | `RouteKind total: 34 modeled kinds: 25`；`unmodeled kinds: ['bond','commodities','daily_assist','fx','group_info','media_archive','northbound','stocks','tts']`；`modeled legacy capabilities: 25` |
| scoped pytest（4 决策件） | `59 passed in 5.79s`（离线绿；生产生效另证） |
| `grep -c "^BOT_DECISION_ENGINE_MODE" .env` / `grep -c "BOT_DECISION" .env.example` | `0` / `0`（只回计数，未读任何值） |
| `ls ../ChatBot_Runtime/decision_trace.sqlite3` | `No such file or directory` |
| `grep -cE "= on_(message|notice|command|fullmatch|startswith)\(" __init__.py` | `51` |
| `grep -oE 'capability_id="bot\…' __init__.py \| sort -u \| wc -l` | `31` |

### 附录 B：前席关系与不重复声明

U4（dispatch）已证「legacy_only 缺省真实、shadow 不接管、无过度宣称」——本席不重证，直接以其为底座，把问题推进到「接管接收端缺什么、分歧数据为什么不可得」；U7（command）的 `/bot decision` 初判被本席独立复核成立并补实「帮助页教自己」闭环形态（F-1）；U2（S10 零消费者）/U3（功能门 fail-closed 吞消息）/U15（输出旁路）结论按 mandate 作 D4 前置条件引用，未重报其清单。
