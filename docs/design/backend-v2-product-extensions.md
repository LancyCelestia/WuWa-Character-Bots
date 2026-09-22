# 后端 V2.1 产品扩展：算法、参数、计费、恢复和实战验收

本文件补充[主规范](backend-v2-implementation-guide.md)，对应[验收矩阵](backend-v2-acceptance-matrix.md)。以下函数名、DTO、接口和参数是实施目标，除明确注明的存量事实外，不代表已实现或可调用。本轮仅写文档；没有调用付费服务、发送测试消息或修改生产好感度。

设计取舍：复用已有 ledger、AffinityStore、占卜牌组、检索、SendQueue；新增统一服务和事件适配，不再建平行账本/发送器。采用有界确定性算法＋可重放事件；LLM负责理解和表达，不负责决定权限、金额、分数或是否已发送。表中默认值是首版可调政策，实施时进入注册表，不写死在多个调用方。

## 1. LLM、TTS、AI绘图统一用量与计费

### 1.1 数据模型和事实源

复用 `llm/ledger.py`，经迁移扩展成 Usage/Billing Service。存量已有输入、输出、总Token、缓存创建/读取和按次价格；目前存在“prompt含缓存”的计算假定及缺缓存价格时回退普通输入价，不能不经provider语义核查直接推广到TTS/绘图。

| 实体 | 必须字段与约束 |
|---|---|
| UsageAttempt | operation_id、attempt_id、provider_request_id、provider/channel/model、task_kind、owner/scope、trace_id、started/finished_at、outcome、usage_status、raw_usage_schema_version |
| UsageQuantity | metric（input/output/total/cache_create/cache_read tokens、characters、audio_seconds、images、requests）、value、unit、status、source；value为有限非负数或null |
| PriceRevision | price_id、version、provider/channel/model、effective_from/to、currency、计量分母、计费组成、取整规则、provider适配版本、来源与审核者 |
| ChargeLine | attempt_id、line_id、metric、quantity、unit_price、denominator、price_revision、amount、currency、status、billing_group |
| Settlement | reserved/estimated/settled/partial/unknown/refunded、已知金额、未知项、invoice_ref、调整关联；不可覆盖历史结算 |

`usage_status=measured/estimated/unknown/not_applicable`；免费但实际已知为0与未知区分。Token总数优先provider报告；只有适配器确认各项集合不重叠时才推导。缓存Token通常是输入的子集，不能加到total上二次累计。记录 `input_semantics=inclusive_cache/exclusive_cache/unknown` 和 `cache_creation_includes_read=false/true/unknown`，不支持的组合拒绝自动结算。

TTS字符、秒、请求数与绘图图片、分辨率档、请求数可以独立计费。只有服务真实报告Token时才填Token；否则展示“不适用”或“未知”，不得按字符伪造精确Token。缓存创建、缓存读取同理。channel若被AxonHub隐藏，保存unknown，不拿模型名冒充渠道。

### 1.2 计算算法

接口：`normalize_usage(provider_schema, raw) -> UsageSnapshot`；`resolve_price(attempt_started_at, route) -> PriceRevision`；`quote_usage(...)`；`reserve_budget(...)`；`settle_attempt(...)`；`reconcile_unknown(...)`；`adjust_charge(...)`；`aggregate_usage(filter, bucket)`。

价格和金额用Decimal序列化为十进制字符串或足够精度的定点整数，禁止浮点金额。价格包含税费/折扣的语义显式记录，最终provider账单优先；历史数据不得用今天价格重算后覆盖。旧cost_milli保留迁移来源与精度，不凭空恢复被舍入的小数。

已验证inclusive且缓存类别互斥时：

```text
ordinary_input = input_tokens - cache_create_tokens - cache_read_tokens
token_cost = (ordinary_input × input_rate
              + cache_create_tokens × create_rate
              + cache_read_tokens × read_rate
              + output_tokens × output_rate) / token_denominator
```

差值负数返回 `usage_inconsistent`，不能max(0)掩盖异常。exclusive语义下ordinary_input=input_tokens。缺缓存用量但输入总量已知时，只能报价区间或partial；缺缓存价格不得默认等于普通价，除非该provider价格规则明确如此。

计费组配置 `composition=additive/exclusive/tiered`：按次费是否叠加Token费、请求费是否已经涵盖多张图片，由价格规则决定。不同币种分别汇总；换汇展示必须带汇率来源、时间与估算标记。

确定性算例（均为虚拟测试价格，不是生产报价）：

- 输入1000含创建100/读取200，输出100；每百万输入2、输出8、创建2.5、读取0.2：普通输入700，金额=0.00249；total=1100，不能写1400。
- 同例明确另加每次0.01：金额=0.01249；exclusive请求套餐0.01时金额仅0.01。
- TTS 1200字符、每百万字符15：0.018；Token字段not_applicable。绘图2张、每张0.04：0.08；不伪造Token。
- 缓存读取价未知：已知部分与未知读取项分开，total_cost=null、status=partial，不能展示“最终总价0.00245”。

### 1.3 调用、重试、预算与接口

operation表述用户一次任务；每次provider尝试独立attempt。失败、取消、超时、failover仍可能计费，均入账；provider重复usage回调以attempt＋来源事件键去重。重试费用属于原operation，不能只统计最后成功模型。

次数分别记录requested/submitted/succeeded/billed_requests，账单未知时billed_requests=null，不用成功数代替计费次数。缓存创建如有5分钟/1小时等不同价格档，记录cache_tier及provider真实数量；reasoning、audio、image Token若为input/output子项，不再叠加total。一个请求多张图片按实际数量结算，重试是否重复收费由provider事实决定，不由状态码推测。

预留预算通过SQLite事务CAS扣占可用预算，并发不能超卖。请求受理后UNKNOWN不立即释放预算或重发；按provider状态/账单对账，有据再结算或撤销。无查询能力则unknown挂账并告警。取消只标cancel_requested，保留可能已产生费用。价格缺失且无已授权保守上限时，付费任务返回 `price_unavailable`；不以unknown绕过预算。预算按任务、主体、provider与测试run限制；初始金额由授权包提供，不猜充值额。

目标REST（均`/api/v1`前缀）：GET `/usage/attempts`、`/usage/summary`、`/usage/rankings`、`/billing/prices`、`/billing/settlements/{id}`；POST `/billing/quote`、`/billing/prices/preview`、`/billing/prices/activate`、`/billing/reconciliations`、`/billing/adjustments`。修改须角色、CAS、幂等与审计；报价不等于provider执行。SSE `usage.recorded/billing.settled/budget.threshold`。

测试：inclusive/exclusive、缓存交叠、负数/NaN、缺字段、不支持单位、微额精度、价格跨生效边界、混合币种、退款、取消后收费、重复回调、重试汇总、并发预留、未知对账和月账重算。排行榜合计须与同过滤条件下attempt账本一致。管理员可按模型/渠道/会话/能力/测试run看费用，普通用户只能看自己授权范围；敏感排行读取审计。

## 2. 好感度事件、误扣修复与回复策略

### 2.1 已发现风险与根因验证

源码检查：`domains/chat_reply/character/affinity.py::classify_behavior` 将 `safety_action == "refuse"` 归为insult；内部[-1,1]乘100展示；insult基础-0.10还有多因素乘数；日限额主要是次数。`observe(delta_override=...)` 绕过常规额度；现有poke默认0.5直接传入，存在内部0.5对应展示50分的单位风险。

用户报告“测试grok性相关路由，一晚掉40多点”登记为真实投诉、历史因果unknown。先用合成输入复现分类/单位问题，再在授权下取最小脱敏事件重放，不读出原始聊天或擅自恢复40分。模型拒答与路由失败不能证明用户辱骂。

### 2.2 事件与单位

新增 `AffinityEvent(event_id, principal_id, bot_id, scope, source_event_id, occurred_at, received_at, category, evidence_kind, confidence, proposed_points, applied_points, reason_code, policy_revision, before/after, test_run_id)`。服务公开单位统一 `points`，范围[-100,100]；存量normalized通过唯一版本适配器转为points，迁移前后抽样对账，不能重复乘100。

`score_relationship_signal(message, trusted_context)` 与 `classify_content_topic(...)`、`review_content(...)`、`preview_route(...)` 分离。`refusal/provider_error/format_error/medical_question/quoted_abuse/product_criticism/authorized_test` 默认关系delta=0；主题路由不自动扣分。确属对人直接辱骂/反复骚扰才提交有证据的negative事件；不确定则neutral。昵称等输入不能伪造关系事件的来源。

管理员人工调整也是具名事件；普通插件不允许任意delta_override。测试身份由可信AcceptanceRun绑定，不能由聊天文本“这是测试”自行取得权限；但正常询问无论是否测试都不应被误罚。

### 2.3 首版有界算法

| 参数（注册域 affinity） | 初始值/范围 | 消费位置 |
|---|---|---|
| positive_points | 0.2 / 0..1 | score_signal |
| tease_points | 0；亲昵玩笑不自动扣分 | score_signal |
| negative_points / insult_points | -0.3 / -1.0，各限制[-1,0] | score_signal |
| confidence_min | 0.9 / 0.8..1 | uncertain→neutral |
| factor_product_min/max | 0.5 / 1.25 | clamp_context_factors |
| max_negative_per_event | 1.0分 / 0..2 | apply_event |
| max_loss_6h / max_loss_24h | 2 / 4分，必须6h≤24h | rolling_budget |
| max_gain_24h | 3分 / 0..10 | rolling_budget |
| interaction_cooldown_seconds | 60 / 10..3600 | 去刷分，不阻止正常回复 |
| poke_gain_points / poke_gain_24h | 0.1 / 0.5分 | 同一全局增益预算内 |
| passive_decay_enabled | false | 缺席不默认扣分 |

这些默认值是保护误判的工程起点，需要回归数据校准。旧好感设计里与此冲突的固定值迁为policy_revision，不两套并存。

算法：

```text
候选变化 = 基础points × clamp(上下文因子乘积, 0.5, 1.25)
负向幅度 = min(abs(候选变化), 单事件上限,
               6h剩余扣分预算, 24h剩余扣分预算)
正向幅度 = min(候选变化, 24h剩余增益预算, 来源专项预算)
实际变化 = clamp(当前points + 有符号幅度, -100, 100) - 当前points
```

预算按 `(principal_id, bot_id)` 跨会话汇总，不因切群重置。DB事务内写唯一source_event_id、读取滚动聚合、更新CAS和outbox；重复事件只返回既有结果。滑动窗口用可信接收时间，显示保留发生时间；过旧/未来事件隔离，不能通过伪造时钟刷新预算。按时间索引有界查询，24h以上历史归档不影响审计。重启和午夜均不重置滚动预算。

函数：`classify_relationship_event`、`normalize_legacy_points`、`preview_affinity_event`、`apply_affinity_event`、`remaining_budget`、`replay_affinity_events`、`propose_compensation`、`apply_compensation`、`build_affinity_style`。并发冲突重读后有限重算；存储失败不在内存偷偷改分。错误：`affinity_unit_mismatch/affinity_evidence_missing/version_conflict/storage_unavailable`，来源不充分返回neutral并记判定原因。

### 2.4 补偿与回复算法

修复流程：冻结旧policy和相关事件摘要→离线重放新旧算法→列明被误分类事件与差额→管理员确认→追加compensation事件→更新投影。补偿不受普通增益预算限制，但有独立管理权限和明确reason，不能删除旧事件；同一修复批次最多应用一次。只有余额、无来源证据时给出“无法精确恢复”，禁止猜值。

好感决定表达温度、熟悉称谓、主动关怀频率，不能改变权限、人格边界、费用或是否允许性内容。沿用已有分档阈值，在每条阈值附近±2分用smoothstep插值，避免一句话跨档骤变；主动互动进入较高档需再超阈值2分，退出低于阈值2分，防抖。允许称谓由AddressingContext单独决定。

`style = {warmth, familiarity, verbosity, initiative, address_policy_id}`，所有维度有界，LLM不接收“低分就惩罚用户”的指令。低好感仍礼貌、不攻击、不冷暴力；高好感不承诺无限服从。群聊和私聊分模板，默认只显示定性变化。主动互动冷却/白名单/安静时间始终先于style。模型输出的emotion不直接计分，也不反向强化下一次惩罚。

验收：相同100条路由测试/拒答不扣分；固定时钟连续辱骂触及预算后不继续减；一晚滚动24h损失≤4（除具名管理调整）；两群/重启/跨午夜不能绕过；并发poke只加一次且0.1分不是10分；反复夸赞不刷满；引用辱骂/投诉/性健康/否定句保持neutral；错误补偿重放幂等；所有分档回复保持人格边界。历史下降原因与新算法正确性是两份验收证据。

## 3. 占卜、每日运势、塔罗

### 3.1 组织与算法

注册父节点 `divination`，子节点 `fortune/tarot/bazi/coin/render/interpretation`；共享DivinationService、DrawStore、AssetService、ModelBroker。复用 `domains/divination/data/tarot.py` 78张牌和现有八字历法算法，不为统一入口重写专业计算。每种方法登记 algorithm_version、数据来源、局限，娱乐解释不得伪装成确定预言或专业决策。

每日运势默认等级与整数权重：大吉10、中吉25、小吉30、平25、小凶8、凶2，总100。权重允许版本化调整，但不能按用户付费/好感秘密改变概率。使用服务端HMAC-SHA256派生种子（principal＋bot＋本地日期＋rule_version），由可审计PRNG进行拒绝采样消除取模偏差，按累计权重抽取；保存day_key唯一结果，算法/密钥轮换不能让当天重抽。密钥由核心管理不暴露给插件；审计保存key_id与种子摘要，不宣称用户可独立验证未公开种子的公平性。

塔罗：固定78张唯一card_id；Fisher–Yates或标准无放回抽样选k张，正逆位独立Bernoulli(p=0.5)。默认阵型single(1)、past_present_future(3)、celtic_cross(10)，不接受任意k或未知位置名。核心生成随机材料、持久化结果后再解读。`draw_id` 重试不变，LLM不得换牌、换正逆位或伪造第79张牌。随机源生产使用系统安全随机或经审核的确定性派生源，测试使用注入seed；不要用Python hash跨进程重放。

### 3.2 契约、函数、参数

请求 `DrawRequest(kind, spread_id, question≤500字, timezone_id, workspace_id, idempotency_key)`；身份/日期来自可信context。结果 `draw_id, cards[{card_id, position_id, orientation}], fortune_grade, interpretation_lines, algorithm_revision, deck_revision, asset_ids, trace_id, disclaimer_id`。

函数：`validate_spread`、`draw_without_replacement`、`draw_daily_fortune`、`persist_draw_once`、`build_interpretation_context`、`interpret_draw`、`render_draw`、`get_draw`。GET `/divination/capabilities`、POST `/divination/draws`、GET `/divination/draws/{id}`，命令/help由同一descriptor投影。

默认每主体塔罗冷却60秒、每天20次（工作区独立配额）；每日运势一次，重读不限于合理读限流；LLM解释预算输入2000/输出600 Token（估算必须标来源），deadline 20s；卡片渲染8s预算，失败保留牌面纯文本。素材使用合法登记牌图，缺图就文本，不临时抓来源不明图片。占卜结果不能自动改好感度、创建日程或调用交易动作。

错误：`invalid_spread/deck_integrity_mismatch/feature_disabled/rate_limited`；模型失败返回既有牌面的本地解释而非重抽；渲染失败产生incident但不丢抽取结果。

测试：78唯一/22大56小；k范围、无重复、朝向；固定seed回归；多seed频率容差按样本置信区间设定，不用不稳定随机门禁；同日跨会话相同、跨日/时区变更限制；并发创建唯一；重启与密钥轮换不刷新结果；LLM胡编牌面被拒；图文一致；八字原回归集保持，出生时区/夏令时/节气边界按原算法证据复核。

## 4. 全场景日程链、课表和提醒

### 4.1 统一模型

`SchedulePlan(owner, timezone, calendar_revision, revision, state)` 包含 `TaskTemplate`、`DependencyEdge`、`RecurrenceRule`、`Occurrence`、`ReminderPolicy`。任务可为fixed_time、duration、relative_to_start、relative_to_finish；边含predecessor、relation、offset_seconds、failure_policy。Toplevel plan启停与子任务继承同一Feature语义，单个规则暂停不影响已发送历史。

先做DAG拓扑排序O(V+E)，再计算最早可行开始/结束。输入max_tasks=100、max_edges=300；不接受循环。硬预约时间不能因前置晚点被静默顺延，输出conflict；有软时间窗才允许重算并给差异预览。LLM从自然语言/图片提取草稿，不替用户确认日期、出发地、目的地、交通或校历。

| 模板 | 默认链条 | 特有参数与边界 |
|---|---|---|
| 课表 | 起床/准备→课前→上课→课后事项 | 学期起点、节次表、单双周、校历例外必须明确 |
| 上班 | 起床→早餐→通勤→到岗→午餐→下班 | 工作日与轮班表分开；调休不等于学校停课 |
| 出门/办事 | 材料清单→出发→到达→办理→返程 | 地点/营业时间/预约窗口，资料缺失unknown |
| 出行/游玩 | 证件→打包→出发→安检/候车→行程→返程 | 航班/车次变更仅授权来源，估算路程标estimated |
| 抢票/抢课 | 资格/账号检查→资料准备→开售前提醒→开售提醒→结果登记 | 精确时间/来源/时区；只提醒与授权只读监测 |
| 购物 | 清单→比价→预算检查→活动提醒→用户下单记录→收货/退换截止 | 不自动下单付款，不保证价格实时有效 |
| 吃饭/日常 | 食材/准备→用餐→后续事务 | 工作日/周末不同模板，允许snooze、skip |

抢票/抢课不含抢占资源、绕验证码、批量注册或绕平台限流；自动购买、付款不在本授权范围。日程地址是用户提供的业务数据，不推断精确位置。

### 4.2 时间、识别、调度

时间UTC存储，IANA时区展示；本地重复时刻需fold/确认，不存在时刻提示修正，不能随OS时区漂移。一次/每日/每周/指定周几/单双教学周RRULE有限子集；物化未来30天、每plan最多1000实例、全局受资源预算限制。课表截图保留行列/合并区域/周次/置信度；缺学期起点和节次表不能发布。

`occurrence_id=hash(rule_id, rule_revision, scheduled_at_utc)`，每reminder offset另有唯一reminder_id。调度器持久化lease领取，默认轮询5s（不是实时保证）、单次最多50条；DB时间索引找due，不每轮扫描全部用户。重启reconcile到期项。

提醒策略：一般事件默认开始前10分钟＋准点，抢票/抢课前10分钟/1分钟/准点可配置；单实例最多4条。通勤时间无路程来源时由用户给buffer，不用LLM猜ETA。QuietHours默认延后非紧急；用户显式批准的硬时点提醒可例外，例外必须可查询。每主体默认每分钟3条、每小时20条，超限合并摘要；发送已排队不重复物化。

> **口径限定（2026-09-20 合流更正，裁决出处=`docs/design/emergency-info-outbound-gate-spec-20260920.md` §2）**：上面那句里的「3/分钟、20/小时、超限合并摘要」是**本文件所设计的日程 v2 引擎内部缺省**（`domains/schedule/service/schedule_service.py:152-153`），该引擎**至今未接生产**——`bot_schedule_delivery_enabled` 缺省 False（`config.py:451`）且全仓零生产调用点，「超限合并摘要」所依赖的 `build_digest` 亦为留接口未实现。因此这三个数值**不得用来描述现役生产**。现役真值是另外两套口径：①入站 chat 限流（用户消息触发的回复）=`config.py:982-986` 的 `bot_rate_limit_chat_global/session/sender_max_requests`（代码缺省 60/6/4 每 60s）+ `bot_rate_limit_chat_sender_min_interval_seconds=45`，生产实值取 `.env`；②出站主动投递中央闸=`bot_outbound_gate_*` 口径（每主体 2/分钟·6/小时，总闸缺省关闭，真身 `domains/transport/sender/outbound_gate.py`）。三套数字描述三个不同对象，互相引用即为错。另：群句数帽 `bot_rate_limit_group_max_per_hour/minute` 缺省 0=关闭（`config.py:989-990`），帮助页里「用户口径建议 60/小时、3/分钟」属该帽的人工建议值，同样与本句的引擎缺省无关。

错过策略 `skip/send_once/digest/ask`；默认普通提醒在15分钟grace内send_once，超出digest，抢票等过时提醒标expired并报告错过，不继续当“即将开售”。发送UNKNOWN先对账；前置失败由failure_policy阻断/提醒风险，不能假设已完成。修改源时间重算未来实例，返回diff及new_revision；确认与发送前重新校验版本。取消与发送在受控发送许可处线性化，已在途无法保证撤回。

函数：`parse_plan`、`recognize_timetable`、`validate_plan_dag`、`resolve_calendar`、`expand_occurrences`、`preview_reschedule`、`confirm_plan`、`claim_due`、`mark_task_done`、`snooze`、`cancel_occurrence`、`reconcile_missed`。POST `/schedules/drafts`、`/{id}/preview`、`/{id}/confirm`、`/{id}/reschedule`；GET `/schedules`、`/{id}/occurrences`；POST `/reminders/{id}/snooze|skip|complete`（竖线表示三个独立路径，不是字面URL）。

错误：`schedule_cycle/missing_calendar/ambiguous_local_time/schedule_conflict/occurrence_expired/version_conflict`。证据不足保留草稿、列字段，不返回成功导入。测试覆盖全部模板、单双周/跨年/调休、夏令时、时钟倒拨、不同日期同名课程、重复图片、前置晚点、取消竞态、离线一周、定时队列洪峰、平台断线恢复、安静时间与批准例外。

## 5. 戳一戳、平台Emoji、Sticker与Meme

标准 `InteractionEvent(platform, bot, actor, target, event_id, kind, is_add, occurred_at)`，`ExpressionCandidate(kind, platform_asset_id/asset_id, emotion_tags, persona_tags, safety_tags, source, version)`。Reaction（贴到某条消息）、Emoji文本/平台段、Sticker（独立贴纸消息）、Meme图片四种语义不能混称一种。

`plan_poke` 在去重/目标校验/开关/白名单/冷却后，确定性加权选择一个主回复（fixed/llm/meme/sticker/emoji），可叠加一次回戳、定性好感变化和必要@。使用event_id＋policy_version经SHA256派生选择值，权重缺候选时重新归一；不是发送五条主回复。LLM失败/图库空/平台不支持均回本地话术；好感变化由§2事件服务提交一次，发送重试不得重复计分。

默认mix权重fixed35/llm35/meme15/sticker10/emoji5；cooldown=30s，每主体每小时12个主回复，回戳最多1，跟戳chain_depth≤1、ttl=10s，仅回应当前用户对Bot的新事件。自己的回戳引发通知直接抑制。无平台事件ID时用actor/target/kind/2秒窗指纹，登记dedupe_quality=approximate，不能宣称精确。

`select_expression`：先硬过滤场景、平台支持、权限、NSFW政策，再语义/情绪/人格分数减最近重复惩罚。默认保留最近20个素材ID，不保存无界字典；语义分归一至[0,1]，评分权重注册，温度0.3加权采样，可固定seed测试。普通聊天主动表情默认概率0.15、冷却120s、每天20次；严重悲伤、投诉、故障通知默认只发得体文本，避免错贴庆祝素材。同一回复Reaction与主动Meme互斥策略由policy明确。

QQ face_id和超级表情来自经版本验证目录；unknown名称显示“QQ表情#ID”，不保证未经真机验证ID可发送。TG依据bot权限、聊天reaction配置、sticker_set/file_id能力表；无原生支持时只能明示文本/图片回退。收到is_add=false不记正反馈。素材采集image/mface/sticker全部登记来源和留存策略，下载走Broker；收库不等于允许任意素材出站。

函数：`normalize_interaction`、`claim_interaction`、`plan_poke`、`select_expression`、`validate_platform_expression`、`build_interaction_intents`。所有poke/reaction/sticker/meme经SendQueue，平台不支持记 `unsupported_platform_capability`；不直接call_api兜底。验收含自己通知/双Bot互戳/重启配额/取消reaction/缺图/权限撤销/部分发送/主回复唯一、QQ+TG真实媒体回执和admin查看。

## 6. 多平台 Web Search

### 6.1 统一协议和来源能力矩阵

复用现有搜索链和链接解析。SearchBroker约束网络与凭据；隔离provider负责请求/解析，search结果只是证据，不是system指令。本轮未联网验证任何平台API，以下是目标适配策略，实际可用性全部待实测。

| source_id | 优先方式 | 有条件fallback与限制 |
|---|---|---|
| bilibili（哔哩哔哩/B站） | 已授权官方接口/现有合规公开检索 | 搜索引擎site:bilibili.com；字幕单独标available/unknown |
| xiaohongshu（小红书） | 授权连接器或用户明确授权可访问内容 | site:xiaohongshu.com；登录/风控受限返回restricted |
| youtube（YouTube） | YouTube Data检索及授权字幕能力 | site:youtube.com；搜索命中不等于字幕已读取 |
| x（推特/Twitter/X） | 授权X API、已批准连接器 | site:x.com并标索引滞后，保护内容不访问 |
| github | 官方repo/code/issues搜索，各自权限/配额 | site:github.com；私库只在授予scope内，不送公共搜索引擎 |
| linux_do（Linux Do） | 站点允许的Discourse检索或授权连接器 | site:linux.do；会员区保持登录权限边界 |
| csdn | 合规搜索provider、公开页面读取 | site:blog.csdn.net；付费正文不绕过 |
| zhihu | 授权能力/公开索引 | site:zhihu.com；片段与全文分别标记 |
| cnki | 有授权的知网检索/机构连接器 | site:cnki.net只提供可验证元数据/链接；无权不取全文 |
| general | 已登记通用搜索provider链 | 无provider就dependency_unavailable，不编造结果 |

### 6.2 DTO、算法与参数

`SearchRequest(query≤500字, source_ids≤5, kinds, date_range, language, limit=10≤20, cursor, workspace_id)`；`SearchHit(id, title, canonical_url, source_id, author, published_at|null, retrieved_at, snippet, content_level=metadata/snippet/full, retrieval_mode, access_status, relevance, citation_id)`。源站发布时间未知保持null，不能用抓取时间替代。

函数：`plan_search`、`authorize_sources`、`search_provider`、`normalize_hit`、`deduplicate_hits`、`rank_hits`、`fetch_reference`。按source任务并发上限2（业务内部I/O，不代表派AI子代理），总deadline12s、单源6s、最多一次可安全重试。规范化URL但保留内容标识参数，platform item_id优先去重；多路排名RRF k=60，时效加权只在任务要求新鲜度时启用，记录排序理由。

TTL普通300s、热点60s；缓存键含owner/scope/query/source/version，私有内容绝不与公众共用。结果返回per_source状态；部分失败可partial，全部失败返回dependency_unavailable。空结果有明确“未检索到”，与超时不同。引用使用后端发放citation_id，引用正文中的命令无执行权。

POST `/search/preview`、`/search/queries`；GET `/search/queries/{id}`、`/search/sources`；POST `/search/references/{id}/fetch`。fetch只能选本次授权命中的reference，不接任意服务URL。SSRF按DNS解析、连接目标及每次重定向校验，限大小/解压比/类型；拒绝localhost/内网/metadata端点，防TOCTOU与DNS rebinding。

测试：九平台离线契约fixture、provider限流/auth/空结果/部分失败、游标绑定主体、跨源重复、伪造引用、Prompt注入、重定向内网、搜索摘要误标全文、知网访问受限、私库不外泄。真实验收每平台记录实际模式与来源证据；fixture通过不能标全部站点live可用。

## 7. 自我修复、自我痊愈与admin故障通知

### 7.1 两种恢复边界

运行自愈 `detect→classify→plan→authorize→recover→verify→observe→close/escalate`。允许重连、有限重试、重启崩溃隔离worker、回退失败资源代际、重建可再生缓存、UNKNOWN对账；不修改代理/Token/角色/人格/审核边界，不自动删库、重启生产主进程或盲重发外部动作。

恢复动作本身进入ControlActionRegistry，带executor、前置条件、验证器、补偿器、费用/资源预算。每resource＋error_fingerprint 10分钟最多3次；指数退避1..30s full jitter；健康持续60s且三个探测成功才closed，未通过后置验证不能宣称痊愈。损坏数据和鉴权失败直接隔离并通知；依赖恢复后优先对账再恢复队列，防雪崩。

代码自修 `cluster→reproduction_bundle→isolated_checkout→RED_test→minimal_patch→targeted_test→security/contract_checks→review_required`。每故障最多2轮候选；禁止删测试、调低阈值、关闭权限、自动部署/commit/push。输出diff资产、构建摘要、复现命令、前后结果、残余风险与回滚建议。不可访问敏感原文的修复器只获得脱敏最小复现。权限/证据不足就blocked，不伪称自行修好。

### 7.2 Incident与管理员可见性

`Incident` 必含：incident_id、fingerprint、severity、first/last_seen_at_utc、display_timezone、count、state、platform、bot_id、脱敏会话引用、entrypoint、capability、plugin/release、function_symbol、stage、build_id、config/persona_revision、error_code、cause_error_id、trace_id、debug_id、影响范围、diagnosis/confidence、recovery_actions、verify_result、建议处理步骤、safe_artifact_ids。

“触发地点”是适配器/平台/会话/功能/进程阶段，不臆测用户地理位置；地点敏感字段仅给授权admin。展示解释区分“已知原因”和“可能原因”，不能把LLM诊断当事实。公开回复只给自然话术与debug_id，不暴露调用栈、内部路径或凭据。

严重度：critical为数据完整性/权限/审计链中断；error为功能失败；warning为可控降级；info为恢复。相同fingerprint＋resource 300s聚合，首次error/critical立即写incident并出通知；默认admin每分钟最多3条、每小时30条，其余汇总，critical仍保留首条与影响扩大事件。恢复通知一次，重复失败不无限刷屏。脱敏在持久化前完成，原始安全证据如需保存使用独立受限策略。

通知目标是注册且验证过身份的私有admin会话，不能自动把异常发到触发群。通过SendQueue＋持久化outbox；SendQueue/平台本身故障时写本地incident和控制面事件，恢复后补通知。告警发送失败只更新incident delivery，不再次生成同级通知，防递归。

函数：`record_incident`、`aggregate_incident`、`explain_failure`、`plan_recovery`、`execute_recovery`、`verify_recovery`、`prepare_patch_candidate`、`notify_admin`。GET `/incidents`、`/{id}`、`/{id}/timeline`；POST `/{id}/ack`、`/{id}/recoveries`；GET `/repairs/{id}`；POST `/repairs/{id}/review`。人工审核通过也不自动部署，部署另走具名授权控制动作。目标命令 `/bot incidents list|show|ack`、`/bot recovery preview|run`、`/bot repairs show`，实现后才进入现行help。

测试：断网恢复、凭据失效不重试、worker死循环配额、DB写失败、发送未知、10分钟恢复预算、误分类、通知去重、管理员权限撤销、告警链自己故障、修复补丁无法越权部署。痊愈必须包含后置探测和稳定窗口证据，不能“进程已拉起”即闭环。

## 8. 一次授权、自动实战验收与admin媒体产物

### 8.1 授权包

下一实施AI开工读取现有明确授权，把真正未知项合成一次请求：测试bot/白名单目标、admin收件人、允许provider/model、按币种预算及单项上限、时间窗、允许临时数据与清理范围、真实发送类型、维护重启/迁移许可。此前已批准的隔离和自修边界不再问。不能从“全部你做主”猜测他人收件地址、无限费用或强杀管理员Bot。

`AcceptanceAuthorization(id, principal, allowed_targets, allowed_scenarios, provider_allowlist, currency_budgets, max_requests, max_assets, valid_from/to, maintenance_actions, data_scope, revoke_version)` 由可信控制面保存，默认拒绝未列动作；授权摘要可审计且绑定run。续期/提高金额/新目标才需新授权。当前文档交付不需要这些外部授权，也不会代用户新建授权包。

实施按阶段连续推进，阶段结束只记证据不等批准；某外部依赖缺失时标blocked并继续其余工作，最后一次汇总阻断。遇新的真实不可逆风险仍必须升级，不为“不停工”静默扩大范围。

### 8.2 测试Runner与证据

自动Runner复用 `scripts/e2e_acceptance.py`，串行执行注册Scenario，禁止扫描所有联系人随意发送。`AcceptanceRun` 包含build_id、manifest_revision、authorization_id、mode、fixture_set_version、started/finished、budget、场景结果、artifact_ids和总报告。每个场景保存真实输入入口、assertions、trace/usage/receipt IDs、资源峰值、预期/实际、失败根因、cleanup结果。

层级：L0纯函数与临时DB；L1本地fake协议；L2真实OS沙箱/本地渲染文件；L3已配置provider真实模型；L4白名单测试Bot/admin平台端到端。L4沿用已批准单实例，不为测试启动第二生产poller。层级单独记录；blocked/skipped/unknown不得算pass，人工主观体验保持pending_review。

| 场景 | 自动验证 | 给admin的真实产物与剩余人工观察 |
|---|---|---|
| 普通聊天/路由/人格 | 真实输入→路由→Review→队列→回执，拒答不误扣 | 回复、路由摘要、费用；模型人格质量抽查 |
| TTS/语音 | 合成解码、时长、静音比例、编码、平台voice/file类型 | 可播放音频、文本、usage；自然度/发音人工评审；ASR回译仅辅助 |
| HTML卡片渲染 | 实际Playwright渲染、DOM尺寸/溢出、超时、截图非空 | PNG、场景参数、渲染耗时；排版美观人工抽查 |
| AI绘图 | 真实provider任务、magic/解码/尺寸、参数核验、取消/未知 | 原生图像资产、种子（若提供）、实际费用；提示遵从性抽查 |
| 图片/OCR/GIF | 已知样本、文本误差/坐标、真实帧时间覆盖 | 原图授权副本、结果、对照图；空识别与失败区分 |
| ASR/视频/字幕 | 时间戳单调、已知语音转写、至少多帧与音轨证据 | 可播放样本、抽帧拼图、字幕与误差报告 |
| Office/PDF/代码文件 | 真实docx/pptx/xlsx/pdf及旧格式负样本、表格结构 | 解析预览、生成代码文件可下载；不执行代码 |
| 日程/课表 | 固定钟仿真＋授权真实短期提醒、重启/取消/重复 | 草稿/确认差异、实际提醒、平台回执 |
| poke/reaction/sticker/meme | 真实事件输入、发送类型、防环/防刷/好感事务 | QQ/TG实际互动回执、图片贴纸；不假造“真人戳了” |
| 搜索/知识/记忆 | 各源实际访问状态、引用、索引重建、遗忘 | 可读来源及提取结果；受限源标blocked |
| 控制面/动作/恢复 | HTTP身份/SSE续传、每注册动作实际后置效果 | 操作时间线、恢复前后探测、敏感原文不导出 |

媒体断言分四步：生成成功→资产校验→平台投递回执→admin有权获取。仅存在PNG不代表渲染正确，更不代表admin收到；平台无read receipt时不能假称admin已观看。需要真实人为触发的平台事件可登记external_step_pending，自动runner通过已有事件回放只能算回放覆盖。

GET `/acceptance/scenarios`、`/acceptance/runs`、`/acceptance/runs/{id}`、`/acceptance/runs/{id}/artifacts`；POST `/acceptance/runs`、`/{id}/cancel`；目标命令 `/bot acceptance list|run|show|artifacts|retry`。所有入口同一Service；run写操作须管理员＋授权包，重试新attempt保留历史。SSE `acceptance.case.finished/artifact.ready/run.finished`。

admin收到一条摘要＋受控媒体合集（默认最多5个直接附件，其余通过授权asset接口取），可逐项调用试听/查看/下载。下载用asset_id、身份/作用域检查与短期授权，不能裸露Runtime路径、无鉴权公网链接或URL中的Bearer。报告保留30天、测试大资产默认7天（未关闭失败证据受保护），配额满先拒绝新run，不删审计；测试数据带run_id，cleanup只处理登记资源。

测试Runner自身：预算耗尽/授权过期撤销后不再新调用；重启续跑不重发成功part；报告接收失败保留待取资产；取消保留已计费attempt；真实语音fallback区分原生voice与音频文件；不把fake结果混入live。性能初始场景为固定100会话/每会话10事件、媒体1并发，记录硬件/可用内存/负载/时间窗；阈值在基线后冻结并审查，不随失败抬高。

## 9. 参数、函数、设定、help与文档的联动投影

### 9.1 单一元数据来源

`ProductManifest + Pydantic DTO/Config + CommandDescriptor + ErrorRegistry + PriceSchema + ScenarioRegistry` 经过验证编译为不可变manifest_revision，输出OpenAPI、WebUI菜单、help、配置册、错误册、README生成区、命令目录与需求覆盖矩阵。共享注册事实，不把所有业务文本混成一个巨型文件。

新增元数据：`ParameterDescriptor(key, owner, schema_ref, default, unit, range, scopes, privacy, consumer_refs, reload_strategy, help_id, test_ids)`；`OperationDescriptor(id, handler_ref, request/response_ref, grants, feature_id, errors, examples, side_effects, scenario_ids)`；`TextTemplate(id, locale, persona_scope, placeholders_schema, version, fallback_id)`。计费单位/好感points/日程秒明确unit；接口不能省略单位让调用方猜。

模板用于固定话术/帮助/错误/通知，个性化文案只传有schema参数；主人格正文独立受保护，不由help生成器改写。动态业务结果当然可以一次性，但关键策略常量、公开参数、错误码、操作说明、固定模板必须有owner与事实源。

### 9.2 编译、消费与漂移门

函数：`collect_manifests`、`resolve_schema_refs`、`validate_consumers`、`validate_template_arguments`、`compile_catalog`、`project_openapi`、`project_commands`、`project_help`、`project_docs`、`check_projection_drift`。AST扫描发现入口/发送/参数访问；动态注册须显式manifest，不能把静态扫描当安全证明。

配置patch先schema校验和CAS，再发布revision，reload消费者在同一资源代际装配；消费者必须报告applied_revision，未确认不能返回热改完成。启动前校验未知参数、无消费者参数、无help命令、未登记错误、模板缺变量；对明确休眠预留参数登记status=dormant和理由，禁止冒充已生效。

`--check`纯比较、无配置访问/插件执行/文件写入，`--write`只生成标记区，稳定排序与换行，连续生成两次字节相同。schema语义变化产compatibility diff；移除公共字段需要deprecated及兼容期限。注册文档不等于扫描函数后自动改写全部代码；专业算法只改治理边界。

投影测试：修改一个参数默认值→API schema/help/文档一致；改变单位必产生兼容差异；未知模板字段/悬空handler/循环引用门禁失败；消费者仍用旧值不得applied；不同权限help隐藏敏感项；菜单不把无handler占位项显示为可用；生成器只读运行时不会启动NoneBot。

现行 `COMMANDS.md/docs/command-catalog.md/docs/auto-facts.md` 只在真实实现并运行生成器后更新；本轮规划的命令/API不写成现行可用。人工架构文档与机器事实分区，不用LLM自由总结替代参数真相。

## 10. 实施执行卡与补充错误

每个上述叶功能都按主规范执行卡填写：ID/父节点、DTO、handler、算法、参数/单位/上限、权限、资源、幂等、事务、错误、观测、测试、装配与证据。函数名是目标符号，若已有等价函数则登记adapter映射，不复制实现。

补充错误集中注册：`usage_inconsistent`(502)、`price_unavailable`(503)、`budget_exceeded`(429)、`affinity_unit_mismatch`(422)、`affinity_evidence_missing`(409)、`invalid_spread`(422)、`deck_integrity_mismatch`(503)、`schedule_cycle`(422)、`missing_calendar`(409)、`ambiguous_local_time`(422)、`schedule_conflict`(409)、`occurrence_expired`(409)、`unsupported_platform_capability`(422)、`acceptance_authorization_expired`(403)。全部含debug_id/trace_id和可操作建议，保留旧码兼容映射；不能让Adapter自行发明另一套错误或吞掉失败返回成功。

实施顺序仍为主规范S0—S16。新增要求进入同一验收矩阵，不再作为“以后再做”的旁支。外部能力缺失必须具体列provider/凭据/编码器/日志源/平台事件/授权阻断，而不是用“协议完成”宣称全部可发布。
