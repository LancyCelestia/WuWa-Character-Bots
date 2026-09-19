# F13 · WebUI 指标口径正确性审计（2026-09-19）

## 0. 快照声明

- 审计日期：`date` 实跑 = **2026-09-19 16:53 +0800**（本机时区 Asia/Singapore = UTC+8，与生产 `bot_timezone=Asia/Hong_Kong` 同偏移，本文全部时区推演按 UTC+8 成立）。
- **工作树在飞**：`git status --porcelain` 共 **889 项**（HEAD=`56d1461`）；本席引用的
  `plugins/bot_unified_runtime/control_plane/{webui_stats,metrics,webui_*,api/webui,api/v1}.py` 与 `webui/` **全部是未跟踪新文件（??）**，`domains/chat_reply/llm_engine/{ledger,model_router,channel_health}.py`、`domains/ops/audit/logger.py` 等在被并发迁移改写。下文行号=本席读到的工作树态，提交后一律以当次实跑为准。
- 本席零修改（除本文件）。实跑取证只用了：定向 pytest 两批（§6）、`$TEMP` 内临时 SQLite + 真服务代码只读复算两次（BR-1/BR-2）、node 纯函数验证一次（BR-3）。输出原样贴入。
- 后端文件（`control_plane/*`、`domains/*`）按分工**只给指针不改**；「建议改法」凡落后端者一律标 `[指针]`。

## 1. 指标字典全表（本席主交付）

列定义——**显示名**：界面文案（zh-CN locale）；**i18n key**；**TS 字段**：`webui/src/lib/api-client.ts` DTO；**后端来源**：端点 + 聚合函数（文件:行）；**窗口**：滚动 N 秒 / 全历史 / 无；**单位**；**含缓存/失败**：该数字是否把缓存 token、失败调用算进来；**可 null**：后端字段可否为空；**quality**：未知/部分上报的表达方式。

判词列：✅=名实相符；⚠=有口径瑕疵；❌=界面上的数字不是它宣称的东西。

### 1.1 总览页 `webui/src/pages/dashboard.tsx`（9 卡 + 键值明细）

| # | 显示名 | i18n key | TS 字段 | 后端来源 | 窗口 | 单位 | 含缓存/失败 | 可 null | quality 表达 | 判词 |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | 控制面健康（在线/降级徽章） | `dashboard.overview.health` | `HealthData.ok` | `GET /admin/api/v1/health` → `api/health.py:52-70` | 请求时刻瞬时 | 布尔 | 检查项 ping，无窗口 | 否 | 检查项芯片 ok/bad | ✅（是**控制面组件**健康，非 bot 全链路；文案未越权） |
| D2 | 健康时间戳 | —（裸渲染） | `generated_at` | `health.py:70`（本地时区 ISO） | — | 时刻 | — | 否 | — | ✅ `formatDateTime` 本地显 |
| D3 | Bot 进程运行时长 | `botProcess`/`formatUptime` | `uptime_seconds` | `health.py:72-94`，`started_at` 缺省=**控制面 app 创建时刻**（`_app.py:253-254`） | 请求时刻−started | 秒（显 天/时/分） | — | 是→— | — | ⚠ `[指针]` 独立进程启动控制面时该数字宣称的是「Bot 进程」，实际=控制面自身；生产进程内装配（`__init__.py:3848-3858` 未传 started_at）≈bot 初始化时刻，可接受但有冒充面 |
| D4 | 启动于 + 时区 | `startedAt` | `started_at`,`timezone` | 同上；tz=`config.bot_timezone` | — | 时刻+名 | — | tz 可空→省略 | — | ✅ |
| D5 | 调用数（24h） | `calls24h` | `CallsData.total_calls` | `api/webui.py:50-59` → `webui_stats.AuditCallStatsService.calls`（`webui_stats.py:113-225`）：`audit_records` 表全行计数 | 滚动 24h（UTC 瞬时比较，正确） | **审计行数**（非消息数、非能力调用数：每条消息写 3-8 行、调度器凭据巡检每 6h 也写行——`audit/logger.py:56-61` 自述、`__init__.py:1701-1725`） | 含未归属/含系统行 | 否 | 脚注 unknown/unattributed 单列 | ❌ 单位不是「调用/消息」；且表按 `bot_audit_max_items`（默认 **1000 行**，`config.py:203`）截尾，窗内行数>1000 时静默少计，界面零提示 |
| D6 | 时间戳未知/未归属条数 | `callsFootnote` | `unknown_timestamp_calls`,`unattributed_calls` | `webui_stats.py:169-171/181-182` | 全表 | 行 | — | 否 | 即 quality 本体 | ✅（数值未 formatInt 千分位，瑕疵） |
| D7 | LLM 调用（24h 账本） | `llm24h` | `TokensData.totals.calls` | `api/webui.py:61-76` → `metrics.LedgerMetricsService.token_families`（`metrics.py:260-327`）：`llm_call_records` COUNT(*) **含失败行**（无 status 过滤） | 宣称 24h；**实际窗=[−32h,−8h]，见 F-1** | 次 | 含失败调用 | 否 | 无标注 | ❌ 窗错位（F-1）；且与 D5 并排时两者都叫「调用/24h」但单位（账本行 vs 审计行）不同——并列无换算说明 |
| D8 | 输入/输出 token（同卡副行） | `tokens.input/output` | `totals.tokens.input.value` | `metrics.py:201-213` | 同 D7 | token | input 为 prompt 原值（含缓存读，见 F-4） | **可 null（quality=unknown）** | — | ❌ `dashboard.tsx:187-188` 把 null 经 `?? 0` 显示成「0」——「未知不是 0」原则在总览卡被前端击穿（L-1） |
| D9 | 渠道健康 N−M/N | `channels`,`channelsFootnote` | 计算：`latency.items` | `latency_view`（`webui_stats.py:303-338`）← `channel_health.report()`（`channel_health.py:324-347`） | 瞬时当前值 | 渠道条目数 | 连败>0 计异常（脚注已申明） | items 可空→0/0 | 「异常」徽章 | ⚠ 分母=**曾被巡检/调用过的条目数**，未测过的注册渠道不在其中；「总数」读起来像全注册面（C-8） |
| D10 | 未接入（队列/告警） | `notWired` | — | 无端点 | — | — | — | — | 显式占位文案 | ✅ 不造数范本 |
| D11 | 今日（24 小时）组·调用数 | `windowToday`,`rowCalls` | `total_calls` | D5 同源（24h 窗） | 滚动 24h | 审计行 | 同 D5 | 否 | — | ❌ 文案「今日」=日历日语义，实为滚动窗（L-2）；单位问题同 D5 |
| D12 | 近 7 天组·调用数 | `window7d`,`rowCalls` | 同上（7d 窗） | 同上 | 滚动 7d | 审计行 | **≤1000 行截尾**→常与 24h 相等 | 否 | — | ❌ 饱和时「近 7 天 ≈ 今日」用户见为 bug（F-2） |
| D13 | 活跃用户（两组） | `rowActiveUsers`+hint | `active_users?` | `webui_stats.py:205`（窗口内可归属用户去重） | 随窗 | 人 | unattributed 不计（hint 已申明） | 旧控制面缺字段→— | — | ✅ 口径诚实；与记忆图谱「人物」数不同源（F-8） |
| D14 | 最后消息（两组） | `rowLastMessage` | `last_message_at?` | `webui_stats.py:175-176,207-209`：**全表窗内最大 created_at，任何 stage/任何 session 都算** | 随窗 | 时刻 | 含调度器/队列行 | 无记录→— | — | ❌ 名「消息」实「任意审计事件」；凭据巡检每 6h 一行 → 永不会显示比 6h 更旧（L-4） |

### 1.2 调用统计页 `calls.tsx`

| # | 显示名 | i18n key | TS 字段 | 后端来源 | 窗口 | 单位 | 含缓存/失败 | 可 null | quality | 判词 |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | 窗口内调用 | `calls.total` | `total_calls` | D5 | 24h/7d/30d 滚动，UTC 正确 | 审计行 | — | 否 | 徽章 ×2 | ❌ 单位/截尾同 D5 |
| C2 | 趋势折线点（bucket_start,calls） | `calls.trend` | `trend.items[]` | `webui_stats.py:213-221`：**`sorted(trend,reverse=True)[:limit]`——与 TopN 共用 limit 参数**（页面传 10） | 窗内**最新 10 桶** | 行/桶 | — | 空窗→[] | — | ❌ 「7 天+按小时」图只覆盖 10/168 桶，头部 total=72 而图总和=10（F-3，实跑 BR-2）；且缺计数桶不上图、类别轴等距=时间畸变（G-1） |
| C3 | 趋势轴标签 | —（`formatBucket`） | `bucket_start` | 后端 UTC 桶（`metrics._utc_bucket`） | — | 时刻 | — | — | — | ❌ `formatBucket`（`format.ts:41-48`）把 UTC 桶标签转**浏览器本地钟**显示，而 `trendDesc` 原文宣称「{{timezone}}」=UTC——同一页脚注与轴自相矛盾（L-3；BR-3 实证 02:00Z→显示 10:00） |
| C4 | 按能力 TopN | `byCapability` | `by_capability[]` | `webui_stats.py:185-187`（能力码原文） | 随窗 | 行 | — | 能力空→「（能力未知）」键 null | — | ✅ 名实相符（行=审计行，但能力行主要来自 invoke stage，量级贴近调用；仍受 1000 行截尾） |
| C5 | 按会话 TopN | `bySession` | `by_session[]` | `webui_stats.py:177-179` HMAC 假名 | 随窗 | 行 | — | 否（假名） | — | ✅ 隐私口径已申明 |
| C6 | 按用户 TopN | `byUser` | `by_user[]` | `_user_from_session`（`webui_stats.py:87-99`）OneBot 约定派生 | 随窗 | 行 | — | — | unattributed 徽章 | ✅ 派生不出不造人 |
| C7 | TopList 条宽 | — | — | 前端 `Math.max(2, calls/max*100)%`（`calls.tsx:77`） | — | % | — | — | — | ⚠ 最小 2% 底宽：1 次调用也画 2% 条，小值视觉放大（G-4，次要） |
| C8 | 时间窗/桶切换 | `calls.window.*`,`bucket.*` | 组件 state | 纯前端；两页各自独立 state，默认 24h/hour | — | — | — | — | — | ⚠ 切到 30d 不重置 bucket（默认仍 hour→10/720 桶，加重 C2）；跨页窗口不共享属 IA 席，此处只记数字后果 |

### 1.3 Token 面板 `tokens.tsx`

| # | 显示名 | i18n key | TS 字段 | 后端来源 | 窗口 | 单位 | 含缓存/失败 | 可 null | quality | 判词 |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 | 调用（窗口总量卡） | `tokens.callsLabel` | `totals.calls` | D7 | 宣称窗（实际错位 F-1） | 账本行 | **含失败行**（无 status 过滤，`metrics.py:106-110`） | 否 | — | ❌ 窗错位；⚠ 「次调用」含失败未注明（`attempt_total` 恒 unknown 已申明，但 calls 本身没带口径） |
| T2 | 输入/输出/缓存读/缓存建（总量+族行） | `tokens.input` 等 | `TokenBlock.value` | `metrics.py:90-97`：仅 `typeof=integer AND >=0` 求和 | 同 T1 | token | **prompt 含缓存读**（OpenAI 兼容 usage 原样入库，`providers.py:356-379` 不扣减），而计费侧按 `prompt−cache_read−cache_creation` 计费（`ledger.py:246-264` `billed_input`）——同一列两套摄入 | 全未知→null | `?N`=全缺/`~N`=部分缺（`tokens.tsx:29-43`） | ❌ 堆叠图四项相加把 cache_read **重复计数**（F-4）；null 在列表显示 — ✅ 但 Tooltip 显示 0（L-1b） |
| T3 | 堆叠柱（族×4 项） | `tokens.stackTitle`,`stackDesc` | `families[].tokens.*` | `token_families` 族归一 `pricing.model_family_key`（casefold+剥推理档，`metrics.py:309-311`） | 同 T1 | token | 见 T2 | 是（段缺=不画） | 图外 qualityHint | ⚠ 文案未告知「输入含缓存读」；堆叠总和≠总 token；无名族只进总量（`metrics.py:306-308`）+`totalsDesc` 已申明 ✅ 半边 |
| T4 | 模型族明细（calls + 4×value + 徽章） | `tokens.families`,`calls` | `TokenFamilyRow` | 同上 | 同 T1 | 行/token | 含失败行 | 值可 null→— | ?/~N | ⚠ |
| T5 | 共 N 族 | `familiesDesc` | `families.length` | 受 `limit=20` 截尾（**按 calls 降序的前 20 族**） | — | 族 | — | — | stackTitle 写「前 20 族」 | ✅ 上限如实；⚠ 恰好 20 时用户无从知道被截（建议加「≤20，按调用排序」——stackTitle 已有「前 20 族」，可接受） |

### 1.4 延迟页 `latency.tsx`（渠道延迟）

| # | 显示名 | i18n key | TS 字段 | 后端来源 | 窗口 | 单位 | 含缓存/失败 | 可 null | quality | 判词 |
|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 渠道（N） | `latency.channels` | `items.length` | `channel_health` SQLite 行 | 当前值 | 条 | — | 空→暂无数据 | — | ⚠ 计数=「有过健康记录」的条目，非注册渠道数（同 D9） |
| L2 | 渠道名 | —（mono 列） | `channel` | `latency_view` 把 **`model_id`（注册渠道条目 id）**改名 `channel`（`webui_stats.py:320`） | — | 文本 | — | — | — | ✅ 语义正确（该库 key 即渠道条目 id；「模型名≠渠道」的用户裁定未被违反——本席专门核过 `channel_health.py:55` 注释） |
| L3 | 状态章 | — | `state` | ∈{ok, temporarily_unavailable}（`channel_health.py:27-28`） | 瞬时 | 枚举 | — | 空串→chip「unknown」 | tone 色 | ⚠ `stateTone`（`latency.tsx:13-19`）匹配 fail/degrade/timeout 等**永不出现**的值；真实非 ok 值靠 `consecutive_fails>0` 兜红，色≠状态本身（依赖副作用，脆弱） |
| L4 | EWMA | `latency.source` 头注 | `ema_ms` | `record_success` 半衰 0.3（`channel_health.py:162-195`） | 全历史递推（**无样本窗**） | ms | **探针(max_tokens=1)与真实聊天混入同一条 EWMA**（`probe_all` 与 router `_health_record_*` 同写一列，`model_router.py:575-603,1425-1445,2191-2240`） | 从未成功→null→— | — | ❌ 「渠道延迟」不区分 1-token 探针与真实生成延迟，两类样本量纲同、语义异；30d/7d 等窗概念不存在 |
| L5 | 最近延迟 | `last` | `latency_ms` | 同上（最近一次成功，含探针） | 单次 | ms | 失败时后端写 NULL→— | — | — | 同 L4 混源 |
| L6 | 样本 N 次 | `samples`,`samplesCount` | `samples` | **只统计成功**（失败分支不动 samples，`channel_health.py:222-247`） | 累计（不随窗） | 次 | 不含失败 | 否 | — | ❌ 「样本」名实=成功样本数；错误率/失败累计**不可从此页推导**（只有当前连败 streak）（G-5，宣称的「延迟分位数/错误率」两指标在 WebUI 整体不存在，见 §1.10） |
| L7 | 连败 ×N | — | `consecutive_fails` | 当前连败（成功后清零） | 瞬时 | 次 | — | 否 | 红章 | ✅ |
| L8 | 末列（错误原文 或 最后成功时刻 二选一） | — | `last_error`\|\|`last_ok_at` | `webui_stats.py:326-327`（脱敏 200 字符） | — | 文本/时刻 | — | 空→formatDateTime('')=— | — | ⚠ 列语义随内容切换、无列题，读侧易把时刻当错误 |
| L9 | 延迟历史 | `history`,`noHistory` | `history.status/reason` | 后端硬编码 `{unavailable, not_persisted}`（`webui_stats.py:336`） | — | — | — | — | 显式不可用 | ✅ 不画假曲线范本 |

### 1.5 好感度榜 `affinity.tsx`

| # | 显示名 | i18n key | TS 字段 | 后端来源 | 窗口 | 单位 | 可 null | quality | 判词 |
|---|---|---|---|---|---|---|---|---|---|
| A1 | 共 N 人 | `affinity.total` | `total` | `webui_stats.py:267` `COUNT(*)` 全表 | 无窗 | 人 | 否 | — | ⚠ 榜单 `limit=100`，total>100 时页面无「已截断」提示（L-6） |
| A2 | 分数 ±X.Y | — | `score` | `webui_stats.py:279-286`：内部 −1..1 ×100 钳 ±100，round 1 位 | 当前态 | 展示分（v4 口径，基准 10=友善） | 否 | — | ✅ 与 2026-09-15「面板直显数值」用户裁定一致（聊天内侧定性两处不同源已注释） |
| A3 | 档位章 | — | `tier`,`tier_name` | `tier_for_affinity`/`tier_name_for_affinity`（`affinity.py:432-467`，档 id −4..+3） | — | 枚举 | 否 | 色阶 tierTone（`affinity.tsx:15-22`）| ✅ 色阶与 8 档语义一致；scoreClass 与 chip 在 ≥50 区间色相分叉（文本蓝/章紫）属视觉一致性席，仅备案 |
| A4 | 互动 N 次 | `interactions` | `interaction_count` | 库列直读（`webui_stats.py:288`） | 累计 | 次 | `int(x or 0)`——**NULL 变 0** | — | ❌ `[指针]` 后端把 NULL 落 0（未知不是 0 的破口，`[指针]` 只记）；前端只在 `nickname` 非空时才显示互动数（`affinity.tsx:43`）——**指标显示被无关字段门控**（L-5） |
| A5 | 更新于 | — | `updated_at` | 库列文本直写（可空串） | — | 时刻 | 空串→— | — | ✅；⚠ `[指针]` 写入方时区口径未在本席链路内实证 |
| A6 | 畸形 affinity | — | `affinity`,`score` | `webui_stats.py:276-278`：**坏值静默回退 0.1→显示 +10.0** | — | — | 否（被编造） | 无标记 | ❌ `[指针]` 造基准数冒充真值，违背「绝不造数」；前端无从分辨（后端域，仅指针） |

### 1.6 插件页 `plugins.tsx`（状态类指标）

| # | 显示名 | TS 字段 | 来源 | 判词 |
|---|---|---|---|---|
| P1 | 组数量徽章 N 项 | `group.items.length` | `webui_plugins.py` 四组装配 | ✅ |
| P2 | 热更新即可/要重启 | `hot_reload: boolean\|null` | builtins=descriptor；adapters/migrated=False；null 不渲染（三态严格） | ✅ 范本 |
| P3 | 版本 v… | `version?` | 发行元数据/域字面量；builtins 恒 null→不渲染 | ✅ |
| P4 | 别名/配置入口 | `trigger_hints`,`config_actions` | features aliases；/actions 注册表 | ✅ 措辞已降为「别名」 |
| P5 | **启用状态** | `enabled?: boolean\|null`（DTO 有、后端已给，`webui_plugins.py:226,244`） | **前端从未渲染 item.enabled** | ❌ 用户列的「插件状态」指标（开/关）数据在手不上屏——总览看不到哪些内置能力实际关停（L-7） |

### 1.7 记忆图谱 `memory-graph.tsx`

| # | 显示名 | i18n key | TS 字段 | 来源 | 窗口 | 单位 | 判词 |
|---|---|---|---|---|---|---|---|
| M1 | 人物 | `stats.persons` | `stats.persons` | `webui_memory_graph.py:351-376`：**窗内 turns 说话人 ∪ user_affinity 全表** | 混（昵称/好感全时） | 人 | ❌ 挂「近 24 小时」窗下实含全时成分；dataScopeBody 只申明了好感权重与昵称，未申明「人物数含全时好感档案」（F-6） |
| M2 | 群聊/对话 | `stats.groups/conversations` | 同名 | 窗内 turns 聚合 | 窗内 | 个 | ✅ |
| M3 | 长期记忆 | `stats.longTermMemories` | `len(facts)` | 按 updated_at（回退 created_at）窗筛 | 窗内 | 条 | ✅ |
| M4 | 已学规则 | `stats.learnedRules` | `quirks+昵称数` | 昵称**不过窗**（:357-359） | 混 | 条 | ⚠ 同 M1 |
| M5 | **发言条数** | `stats.speakerCount` | `speaker_count` | `webui_memory_graph.py:356`：`sum(1 for p if turns>0)` = **窗内发言的人数（去重）** | 窗内 | **人** | ❌ 中文标签写「发言条数」、英文写 "Messages"——单位级错标（L-8）；窗内真实条数=各会话 weight 之和，界面不可得 |
| M6 | 截断章 | `truncated` | `truncated`,`nodes.length` | ≤max_nodes(200) 按度数截 | — | 节点 | ✅「仅显示关联最多的 N 个节点」用截后数，名实相符；stats 恒截前总量已申明 ✅ |
| M7 | 关联度 | `degree` | 前端 `computeDegrees`（`graph-layout.ts:47-55`） | 对截断后 node/edge 集重算 | — | 边数 | ✅（与后端截断前 degree 排序口径不同属设计内） |
| M8 | 权重 | `weight` | 后端节点 weight：**person=好感 −1..1，group/conv=窗内 turns 数，memory/rule=1** | 详情侧栏原样显 | — | **每类型不同量纲共用一行「权重」** | ❌ 同一行标签混三种单位（L-9） |

### 1.8 知识库 `knowledge.tsx`

| # | 显示名 | TS 字段 | 来源 | 判词 |
|---|---|---|---|---|
| K1 | 共 N 条 / 分页范围 | `total`,`page*` | `webui_knowledge.py`（terms COUNT） | ✅ Pager 名实相符 |
| K2 | 文本块 N / 表情 N 条 | `chunk_count`,`count` | 集合侧真值；`typeof==='number'` 才渲染 | ✅ 缺不猜 |
| K3 | 集合条数 `KnowledgeCollection.count`（nullable+reason） | `count` | **DTO 有、前端 chips 未渲染**（`knowledge.tsx:226` chip 只有名称+未启用） | ⚠ 数据在手不上屏（同 P5 类，缺口径脚注可选） |

### 1.9 日志尾流 `logs.tsx`

| # | 显示名 | 来源 | 判词 |
|---|---|---|---|
| G1 | 显示 N 条 · 溢出丢弃 M 条（上限 500） | 前端行缓冲（`logs.tsx:77-88`） | ✅ 丢弃数显式，不谎「全量」 |
| G2 | 当前游标 / 心跳 Xs 前 / 重连第 N 次 | SSE 帧 id、心跳注释帧、退避计数（`sse.ts`） | ✅ 时钟用本地到达间隔，语义自洽 |
| G3 | 事件时间列 | `created_at`（`runtime_event_log`，aware） | ✅ `formatTime` 本地显，无「UTC」宣称，不矛盾 |

### 1.10 用户点名但**界面上不存在**的指标（不存在的诚实清单）

| 指标 | 结论 |
|---|---|
| token 成本/费用（¥/毫厘） | WebUI 零展示：账本有 `total_cost_milli/pricing_source/unpriced`（`ledger.py:559-563`），`/api/v1/metrics/overview` 也不含费用投影；「未计价显示成什么」在 UI 层无从谈起——聊天侧 `/bot model usage` 才有「未计价」文案（`test_model_family_pricing.py:165` 锁）。真账仍以网关为准（AGENTS 台账 #36 四段）。 |
| 延迟分位数 P50/P95 | 前后端皆无（EWMA+最近值+连败是唯一延迟面）；EWMA 与分位数无混用可能。 |
| 错误率（%） | 无；且从 latency 页不可推导（L6）。账本侧 `failed_calls` 在 `/api/v1/metrics/*` 有而 WebUI 不消费。 |
| 缓存命中率 | 无（只有 cache_read 绝对量，且分母口径待定，见 F-4）。 |
| 独立 stats 页 | 不存在——`/api/v1/metrics/{overview,models,sessions,tokens,trends,resources}` 是控制面/OpenAPI 面，WebUI 唯一消费者是 `stats/tokens`；`[指针]` 其中 **`GET /metrics/tokens` 实际调用 `overview`**（`api/v1.py:218-220`），端点名≠内容，若日后前端接上必踩。 |

字典合计：**62 条**（D1-14、C1-8、T1-5、L1-9、A1-6、P1-5、M1-8、K1-3、G1-3，另 §1.10 缺位 5 项）。

## 2. 口径分叉清单（同一语义多处计算，逐条差异条件 + 最小复现）

**F-1（P0）「近 24 小时」在 tokens 面与 calls 面不是同一个窗——tokens 窗整体后滑 8 小时，最近 8 小时账本调用在界面上消失。**
- 两条路径：①`webui_stats.py:153-155` 用 `datetime` 真值比较（cutoff 为 aware UTC），任何偏移文本都正确归一——**calls 页/总览调用数窗正确**；②`metrics.py:296-303` `token_families` 用 `datetime.now(timezone.utc).isoformat()` 的**文本**做 `completed_at >= ? AND < ?` 字典序比较（P3-9 取舍），而生产 `completed_at` 由 `model_router.py:1758` `datetime.now(self._zone)` 写入，`self._zone`=`config.bot_timezone`=Asia/Hong_Kong（`config.py:272`，`.env.example:435`）即 **+08:00 偏移文本**。UTC 边界 × +08:00 行文本 = 按「墙上钟字段」比较 → 窗=[local−32h, local−8h]。
- **实跑复现（BR-1，真服务代码 + 临时库，生产格式）**：种 4 行（6min/10h/26h/31h 前），`token_families(window="24h")` 输出：`totals.calls=3`，families 含 26h 与 31h 行、**丢 6min 行**；期望恰相反。原文：
  ```
  now_utc        = 2026-09-19T08:45:27+00:00
  totals.calls   = 3
  families       = {'deepseek-v4.1-flash': 1, 'gpt-5.6-terra': 1, 'grok-4.6': 1}
  判定: 含26h行 = True | 含31h行 = True | 丢6min行 = True
  ```
- 直接误导决策：Token 面板/总览 LLM 卡的 token 量、族排序、「最近在用什么模型」全部错位 8 小时；白天高峰数据缺席、隔夜旧数据冒充「今日」。
- 改法：`[指针]` 后端唯一收口点=`metrics.py` `token_families` 边界（改 datetime 真值比较或按存储偏移生成边界；`_CHANNEL_AGGREGATE_*` 的「同偏移文本序」前提在跨 UTC/+08:00 时不成立）。前端唯一可为=窗文案降级为「按服务端窗」+口径脚注，直至后端修。
- 回归锁：现有 `test_webui_stats.py:420-467` **只种 +00:00 文本**（`started.isoformat()`，UTC now）——锁住了一个生产不存在的形状；`test_control_plane_metrics.py:83-105` 已示范混偏移种子（+08:00/−05:00/Z）但只测 `_read` 路径。补 token_families 混偏移用例即成锁。

**F-2（P1）「调用数」三处会给出不同数字（用户点名题）。**
- ①`stats/calls.total_calls`=audit_records **窗内行数**（每消息 3-8 行 + scheduler/queue/sender 系统行；表**1000 行截尾**，`config.py:203`+`logger.py:209-221`）；②`stats/tokens.totals.calls`=账本行数（含失败、窗错位 F-1）；③`control_plane_audit` 表（HTTP 审计）与 runtime_event_log（日志页不计数）根本未被 UI 聚合。
- 差异条件（可复算）：每条消息平均 r∈[3,8] 行 → 24h 真消息数 m 满足 total_calls≈r·m+调度行；当 r·m>1000，total_calls 钉死 ≤1000，且 7d 与 30d 同为 1000（**「近 7 天」与「今日」显示同值即饱和信号**）。llm24h ≤ 真 LLM 调用（最近 8h 被切，F-1）。
- 改法：`[指针]` 单元语义（stage/event 过滤为「一次请求一行」）归后端；前端可先行=卡题改「审计行数」+「受保留上限 1000 行截尾」脚注 + 达 1000 时黄徽章（`total_calls===1000` 近似判据，宜由后端回 `retention_capped` 布尔，指针）。
- 回归锁：无（无任何测试断言保留上限对窗的影响）。

**F-3（P1）趋势图与头部总数不同窗覆盖：`limit` 一参三吃。**
- `webui_stats.py:213-221` trend 取 `sorted(trend,reverse=True)[:limit]`；calls 页传 `limit:10`（`calls.tsx:94`）同时决定 TopN 与趋势桶数。
- **实跑复现（BR-2）**：72 行、小时桶 7d 窗 → `total_calls=72`、`trend.items` 仅 10 桶共 10 次：
  ```
  total_calls      = 72 (72 行审计记录，全部真在 7d 窗口内)
  trend.items 条数 = 10
  trend 计数之和   = 10
  ```
- 差异条件：window×bucket 的总桶数 > limit（24h+hour=24>10、7d+hour=168、30d 任意）。图上折线之和 ≠ 头部「窗口内调用」，用户按图读趋势会低估 6-70 倍。
- 改法：`[指针]` 后端应拆 `trend_limit`（或恒回全桶，体积已受桶数天然限制）；前端可先行=CardDescription 补「仅画最新 {{shown}} 桶（本窗约 {{expected}} 桶）」，expected 由 window×bucket 纯前端可算；并在切窗时重置 bucket（`calls.tsx:89-90`）。
- 回归锁：无（`test_webui_stats.py` 种数据恒 <limit 桶，未钉截断语义）。

**F-4（P1）tokens 的 input/cache 重复计数——计费与展示两套摄入并存。**
- 计费（正确侧）：`ledger.py:250-251` `billed_input = max(0, prompt − cached_read − cached_write)`——明示假定 **prompt 含缓存**。
- 展示（分叉侧）：`providers.py:356-379` 归一时**原样保留** prompt_tokens、另存 cache_read；`metrics.py:90-97` 四列独立求和；`tokens.tsx:160-162` 四项 `stackId='tokens'` **堆叠相加**。OpenAI 兼容 usage（含 DeepSeek `prompt_cache_hit_tokens`、OpenAI `prompt_tokens_details.cached_tokens`）里 cached ⊆ prompt → 堆叠总宽把缓存 token 计两次；Anthropic 风格 input 不含 cache，同图又是对的——**同一图上两种供应商语义混叠**。
- 差异条件：任一行 `cache_read_tokens>0` 且来自 OpenAI 兼容归一（本项目四模型全部经 axonhub OpenAI 兼容面）。复算思路：取一行 `{prompt=1000, cache_read=800, completion=100}` → 图宽=1900，真值=1000+100=1100；账本同时存 `total_tokens`（=1100 类值）可作交叉验证，UI 未显示。
- 改法：`[指针]` 归一层二选一：要么入库前 `prompt−=cache_read`（与计费式统一后计费式同步简化），要么展示层加「输入(含缓存)」说明 + 堆叠改分组；前端最小改=`tokens.stackDesc` 追加「输入列为原始 prompt（OpenAI 兼容含缓存读），四项相加≠总 token」+显示 `total_tokens` 做对照（需后端回传该列，指针）。
- 回归锁：**方向相反的锁存在**——`test_webui_stats.py:460-504` 把 `prompt=10(含 cache_read=2)` 与 cache_read=2 并列为两个独立求和项并断言 input.value=40 等，等于把「重叠照加」钉成契约；改口径需动此锁（提示主会话，别当成测试腐化）。

**F-5（P1）时区三口径：UTC 桶 / 本地标签 / 「今日」滚动窗（用户点名题④⑤）。**
- 桶计算 UTC（`metrics._utc_bucket`、`trend.timezone="UTC"`）→ 轴标签 `formatBucket` **本地钟**（BR-3：`2026-09-19T02:00:00Z` → zh-CN 本地显 `10:00`；日桶 `00:00Z` 显当天日期但聚合区间=本地 08:00→次日 08:00）→ 脚注 `trendDesc` 又把后端 `timezone:"UTC"` 原样印上——同页三处两种钟。台账 #3 同源旧账（调度器系统本地时区）在 WebUI 的投影。
- 跨日矛盾条件：任何 UTC+8 观察点，「按天」视图首尾两天的桶与用户日历日差 8h；23 点前后与日切附近桶对不上「今日」。
- 改法（前端可自闭环）：`format.ts:41-48` 两函数加 `timeZone:'UTC'`（标签=桶真身）并把 trendDesc 改为「{{timezone}} 桶」；或维持本地标签但文案改「UTC 分桶·本地显示」。滚动窗「今日」措辞见 L-2。
- 回归锁：无（测试断 `timezone=="UTC"` 字符串，不测显示层）。

**F-6（P2）「人物/发言」两页两单位**：calls 面 active_users（窗内、可归属、OneBot 派生）vs memory-graph 人物（窗内 turns ∪ **全时**好感档案 ∪ 昵称主）——同屏导航两页对「有多少人在说话」给出不同数；差异条件：存在窗内无发言但有好感档案的用户（常态）。改法：M1 卡加「含未在本窗发言的好感档案用户」脚注（前端 dataScopeBody 已有半句，扩到统计卡）。锁：无。

**F-7（P2）「渠道健康 N−M/N」的分母**：store 行数=「至少被巡检/真实调用过一次」的渠道条目（`channel_health.py` 无行=从没测过）；重启后保留（SQLite）故稳态≈注册面，但**新注册未巡检渠道与已剪除渠道都会缺席分母**；差异条件：注册表刚改、巡检未跑完一轮。改法：`[指针]` 端点回 `registered_total`；前端脚注「=有健康记录的条目」。（探针混样见 L4/G-5。）锁：无。

**F-8（P2）latency 页「内存健康库」措辞**：i18n `latency.source` 称「channel_health **内存**健康库」，实为 SQLite 持久库（`channel_health.py:72-84`，跨重启保留正是其卖点）；措辞会让用户误判「重启后归零」。前端一行文案自闭环。锁：无。

**F-9（P2）unattributed 行仍进 total/trend/能力/会话榜**（只不进用户榜）：口径在 hint 里申明了（✅），但「活跃用户」hint 已写、D14 未写「任意事件」（见 L-4）。仅登记。

**F-10（P2）账本 calls 含失败行、无失败徽章**（T1）：`/api/v1/metrics/overview` 面有 `successful/failed/unknown_status` 三分（`metrics.py:56-60,166-174`）且把未知状态诚实单列，而 tokens 端点只回裸 calls——两 API 同库不同投影。改法：tokens 端点回 `successful_calls`（指针）或前端从 quality 徽章区解释；最小文案「含失败调用」可先行。锁：`test_control_plane_metrics.py` 锁了 overview 三分，未锁 tokens 面。

**F-11（P3）`/admin/api/v1/status/bot` 的 started_at**：控制面独立进程=CP 创建时刻冒充「Bot 进程」；生产进程内装配≈bot 启动，可接受。指针：装配处传真实 bot 启动锚（`_app.py:253-254`）。

**F-12（P3）`[指针]` S1 已知旧账不复述**：`runtime_event_log`/事件流与三张 SQLite 计数面之间无对账端点（本轮不动后端）。

## 3. null / unknown / 降级 语义链判定表

后端三态（字段 null｜语义包 source_unavailable(reason)｜缺字段(旧控制面)）→ 前端表达，逐链核对：

| 链 | 后端态 | 前端显示 | 判定 |
|---|---|---|---|
| `last_message_at=null`（窗内无记录） | `webui_stats.py:207-209` | — | ✅ |
| `active_users` 缺字段（旧控制面） | optional | — | ✅ |
| TokenBlock.value=null（quality=unknown） | `metrics.py:201-213` | 列表/总量卡 `—` + `?N` 徽章 | ✅ |
| 同上，**总览 LLM 卡** | `dashboard.tsx:187-188` `?? 0` | **「0」** | ❌ L-1 |
| 同上，**tokens 堆叠 Tooltip** | `tokens.tsx:157` `Number(null)=0` | **「0」**（BR-3 证 `Number(null)===0`） | ❌ L-1b |
| `source_unavailable` 全卡 | `resolveSemantic`→`useSemanticQuery`→`SemanticState` | 「暂无数据」+ known reason 人话/原码回显 | ✅（reasonKey 表覆盖全部已知码，未知码不编语义 ✅ 范本） |
| latency `history` 不可用 | `{status:unavailable,reason:not_persisted}` | 「后端显式标记不可用——不画假曲线」 | ✅ |
| memory-graph 部分源 missing | `sources{name:missing/unreadable}`+stats 0 | 统计卡照显 0（源级计数本就 0）+详情侧「数据源 X 不可用（missing）」 | ✅（0 是真 0，非编造） |
| `ema_ms/latency_ms=null`（从未成功） | store NULL | — | ✅ |
| `interaction_count` NULL | **后端已把 NULL 变 0**（`int(x or 0)`） | 「互动 0 次」 | ⚠ 破口在 `[指针]` webui_stats.py:288 |
| affinity 畸形值 | **后端编 0.1** | 「+10.0」无标记 | ❌ 后端域（A6），前端无责 |
| `unknown_timestamp_calls` | 计数单列 | 徽章+hint | ✅ |
| SSE 410 缺口 | `gap` 态 | 缺口横幅+「不静默重置」文案 | ✅ |
| knowledge `count:null+reason` | DTO 可空 | chips 不渲染计数 | ⚠ 不是错数，是可看未看（K3） |

**「不造数」违规合计：前端 3 处（L-1 两枚 + L-1b），后端指针 2 处（A4/A6）。**

## 4. 时间窗与刷新一致性

- 各页窗独立 state（calls 24h/7d/30d、tokens 同枚举、memory-graph 多 all），无 URL 承载；**总览与子页各持一份请求**（同 `window` 同端点不同 queryKey，`refetchInterval` 30s/60s/120s 各异）→ 同一时刻两屏数字可差一个刷新相位（±几行），窗本身服务端逐秒滑——属可预期但用户会当 bug；建议卡脚注回显「数据时刻 as_of」（后端信封现无 generated_at——指针；前端可退而显示「每 60s 自动刷新」已有）。
- SSE 只用于 logs 单页，无快照/增量混源回退问题；react-query 同 key 串行 refetch 不会后旧覆新。**跨 key 无一致性事务**：总览 calls(24h) 与 tokens(24h) 取数时刻差可达 ~60s，窗又滑——两卡「24 小时」并排本就不应承诺可互相印证（文案已分「audit_records/账本」，✅ 半解决）。
- 默认值互恰性：dashboard=24h、calls=24h/hour、tokens=24h、memory-graph=24h——一致 ✅；唯一暗坑=calls 页换 30d 保 hour（C8）。

## 5. 图表正确性判定

| # | 点 | 判定 |
|---|---|---|
| G-1 | calls 趋势：recharts 类别轴**等距**摆放 UTC 桶 + 后端零计数桶缺省不上报 → 折线跨空桶直连（=把「没人说话的小时」抹平）；叠加 F-3 只画最新 10 桶 | ❌ 欺骗性（趋势形状失真）；改法：前端按 window×bucket 补 0 桶（可自闭环），或至少脚注「空桶未画」 |
| G-2 | tokens 堆叠：数值轴 0 起点 ✅；但 F-4 双计 + T2 段 null→Tooltip 0 | ❌（口径）+❌（tooltip） |
| G-3 | latency 历史：显式 unavailable，不画假曲线 | ✅ 范本 |
| G-4 | TopList HTML 条 `Math.max(2,·)%` 最小底宽 | ⚠ 小值放大，建议 title 注明「条宽含最小 2%」 |
| G-5 | 箱形/百分位图 | 不存在——与 `latency` 页语义无冲突（顺带核对通过） |
| G-6 | 双轴/次坐标 | 无；memory-graph 画布半径用「关联度（截断后重算）」与 M6/M7 申明一致 | ✅ |

欺骗/失真点数：**4**（G-1、G-2（含 tooltip）、G-4、G-2 口径部分与 F-3 交叠不重复计）。

## 6. 契约测试真实性

- **日历炸弹（用户点名题⑥）**：`tests/test_webui_http.py::_audit_table` 已改**动态种子** `(now−1h).isoformat()`，注释自证「2026-09-19 时间炸弹事故」已收口。**本席单跑实证：绿**——
  `tests/test_webui_http.py + tests/test_webui_stats.py`：**64 passed**（12.37s，`--basetemp=$TEMP/f13-webui-1 -p no:cacheprovider`）；另 `tests/test_control_plane_metrics.py + tests/test_webui_memory_graph.py`：**116 passed**。
- 数值断言覆盖率仍薄：`test_webui_http.py:122` 仅 `total_calls==1` 一枚数值断言，其余全形状/信封/认证（形状锁本身是好实践，问题在下条）。
- **「测试绿但口径错」的空间**（逐名）：
  1. `test_webui_stats.py::ledger_db` 种子全为 **UTC 文本**→ F-1 永不现形（混偏移样本只进了不窗筛的 `_read` 路径，`test_control_plane_metrics.py:83-105`）。**补一行「+08:00 文本种 26h/31h 行」即红**。
  2. trend `[:limit]`（F-3）无锁：现有夹具桶数恒 <limit。
  3. `?? 0`（L-1）无锁：无测试渲染 dashboard 组件断言 null→「—」。
  4. F-4 的锁是**反向锁**（把重叠照加钉成契约）——修口径时该锁须一并改判，主会话动手前必读 `test_webui_stats.py:479-519`。
  5. 显示层时区（F-5）超出 Python 契约射程，无前端单测基建（工程化席另论）。
- `tests/test_datafix_runtime_paths.py`、哈希门与指标无涉，核过不赘。

## 7. 可核验性建议（每指标最小自证法；无锚数字点名）

范式沿用行情/汇率卡「显式基准+口径+延迟」先例。总改法：**前端已解析但丢弃的 `data.source` 上屏**（`useSemanticQuery` ok 态已带 `source` 字段，页面全未渲染——零成本口径戳），并在每张卡脚注给「对账指针」：

| 指标 | 自证法（对账指针） | 当前可否自证 |
|---|---|---|
| 调用数/趋势 | 只读 SQL：`SELECT COUNT(*) FROM audit_records WHERE created_at>=<cutoff>`（Runtime 库，mode=ro）；行数≠消息数需按 `request_id` 去重对——UI 无此口径 | ❌ 应加「=审计行数，保留 ≤1000」脚注 + `COUNT(DISTINCT request_id)` 后端指针 |
| LLM 调用/token | `llm_call_records` 直查 + **与 axonhub 控制台对真账**（AGENTS #36：bot 价=渠道假定估价，真账以网关为准）；`total_tokens` 列可作堆叠图交叉校验 | ⚠ 现 UI 无法提示窗错位 8h（F-1 修前必自证失败）|
| 成本 | UI 无此数——如需上屏必须连带 `pricing_source/unpriced` 三态与「以网关为准」注记 | 缺位 |
| 渠道 EWMA/样本 | 对账 `channel_health.sqlite3`（mode=ro）；探针 vs 真实调用需分源才可验——现混源不可分（L4） | ❌ 指针：store 增 `probe_samples/real_samples` 分列 |
| 好感度 | 对 user_affinity 库 `affinity×100` 心算即合；档位名与 `affinity.py` §4 表一致 | ✅ |
| 记忆图谱 | `conversation_turns` 窗内行数=各会话 weight 之和（UI 未显，M5 修后可验） | ❌ |
| 插件/知识 | 与 `/bot status`、`command-catalog` 对别名/条数 | ✅（P5 上屏后更全） |
| 延迟页渠道数 | 与「模型注册表」条目数对账需分母（F-7） | ❌ |

## 8. 新发现台账（七要素；`[指针]`=后端域只给坐标不改）

**L-1｜P1｜`webui/src/pages/dashboard.tsx:187-188`**
锚点：`formatInt(tokensData.totals?.tokens.input.value ?? 0)`
根因：TokenBlock.value=null（unknown 全缺）被 `?? 0` 造 0，违反「未知不是 0」（同页 tokens.tsx 已有 — 处理，两屏同字段两态）。
改法：`…?.tokens.input.value ?? 0)` → `…?.tokens.input.value)`（`formatInt` 本身 null→—）；output 同理。
验证：`pnpm -C webui test`（若有组件测）或手工注入 `value:null` 快照；回归锁：无→建议补 dashboard 渲染断言。

**L-1b｜P2｜`webui/src/pages/tokens.tsx:157`**
锚点：`formatter={(value, name) => [formatInt(Number(value)), String(name)] as [string, string]}`
根因：堆叠段 null → `Number(null)=0`（BR-3 实证）→ Tooltip 造 0。
改法：`formatInt(Number(value))` → `value == null ? '—' : formatInt(Number(value))`。
验证：hover 含 `?N` 族行看 Tooltip。锁：无。

**L-2｜P1｜`webui/src/locales/zh-CN/common.json:91`（en 镜像同 key）**
锚点：`"windowToday": "今日（24 小时）"`
根因：窗是**滚动** 86400s（`webui_stats.py:153-155` datetime 减法），「今日」承诺日历日。
改法：→ `"近 24 小时"`；`callsDetailDesc` 首句「今日与近 7 天」→「近 24 小时与近 7 天」。验证：对照 `state.noData` 窗说明/后端注释。锁：无。

**L-3｜P1｜`webui/src/lib/format.ts:41-48` + `calls.tsx:152`**
锚点：`return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });`
根因：UTC 桶用浏览器本地钟显示，同页 trendDesc 印 `timezone:"UTC"`——轴与脚注矛盾（BR-3：02:00Z→「10:00」）。
改法：两函数 options 各加 `timeZone: 'UTC'`（与后端 UTC 分桶对齐），trendDesc 补一句「轴=UTC」；（备选：保持本地并在 desc 改「UTC 分桶·本地显示」，二选一改完全页一致）。验证：dev 环境看 0 时桶标签。锁：无。

**L-4｜P1｜`webui/src/locales/zh-CN/common.json:95` + `[指针]` `control_plane/webui_stats.py:175-176,207-209`**
锚点：`"rowLastMessage": "最后消息"`
根因：`last_message_at`=窗内**任意审计行**最大 created_at（scheduler 凭据巡检每 6h 一行：`__init__.py:1693-1725`；queue/sender 行同理）——「最后消息」永不过 6h。
改法（前端）：→ `"最近审计事件"` + hint「含调度/队列事件，非仅消息」；`[指针]` 后端应只取 invoke/user 会话行或加 `last_user_message_at`。验证：无消息的 6h 内观察该值是否=巡检时刻。锁：无（BACKEND3 批只锁了「缺字段→—」）。

**L-5｜P2｜`webui/src/pages/affinity.tsx:43`**
锚点：`{item.nickname ? \` · ${t('affinity.interactions', …)}\` : ''}`
根因：互动数显示被昵称字段门控——无名用户丢一个独立指标。
改法：条件从 `item.nickname ?` 改为恒渲染（sender_id 行已展示）。验证：种 nickname='' 行。锁：无。

**L-6｜P3｜`webui/src/pages/affinity.tsx:81`**
锚点：`{t('affinity.total', { count: data.total })}`
根因：`limit=100` 截尾无提示，total>100 时「共 N 人」与行数对不上像丢数据。
改法：`items.length < total` 时追加「（显示前 100）」。锁：无。

**L-7｜P2｜`webui/src/pages/plugins.tsx:38-99`（PluginCard 无 enabled 消费）+ `api-client.ts:374` DTO `enabled?: boolean | null`**
锚点：`enabled?: boolean | null;`（注释已声明 builtins 含）
根因：内置能力「启用/关停」三态不上屏——用户点名指标缺位；且 `features` API 的 enabled 本就不可宣称插件停用（控制面校正节），上屏时措辞用「功能树状态」。
改法：PluginCard 对 `item.enabled !== null/undefined` 渲染 开/关/未知 三态章（同 HotReloadBadge 形态）。验证：`/api/v1/plugins` 手核。锁：`test_webui_plugins.py` 只锁 API 面。

**L-8｜P1｜`webui/src/locales/zh-CN/common.json:254`**
锚点：`"speakerCount": "发言条数"`
根因：后端 `speaker_count`=窗内**发言人数**（`webui_memory_graph.py:356`，`sum(1 for person … turns>0)`）；en 镜像 "Messages" 同错。
改法：zh→「发言人数」，en→"Speakers"；（若产品要条数，`[指针]` 后端补 `turns_in_window`）。验证：任何窗内一人两条以上即现形（条数>人数）。锁：`test_webui_memory_graph.py` 锁数值未锁标签。

**L-9｜P3｜`webui/src/pages/memory-graph.tsx:225-232`**
锚点：`{selectedNode.weight !== null && (`
根因：「权重」行跨节点类型混量纲（好感 −1..1 / turns 数 / 常数 1），数字对但语义不标。
改法：按 `selectedNode.type` 换标签（好感值/窗内发言数/固定 1）或加 hint。锁：无。

**L-10｜P2｜`webui/src/locales/zh-CN/common.json:149`**
锚点：`"source": "channel_health 内存健康库当前值 · 30s 自动刷新"`
根因：「内存健康库」与实现（SQLite 持久，`channel_health.py:66-84`）相反，误导「重启即失忆」。
改法：→「channel_health 持久健康库 · 当前值快照 · 30s 自动刷新（探针与真实调用混样，样本只计成功）」。锁：无。

**F-1a｜P0（后端指针 + 前端知情权）｜`[指针]` `control_plane/metrics.py:296-303` 边界构造 × `domains/chat_reply/llm_engine/model_router.py:1758` 写入偏移（生产 +08:00）**
锚点（后端）：`(now - timedelta(seconds=_WINDOW_SECONDS[window])).isoformat(), now.isoformat(),`
根因：文本字典序窗 × 混偏移存储 → 窗后滑 8h（BR-1 实跑红）。
前端可自闭环部分：**无**——只能加脚注「窗口边界以服务端文本比较，偏移口径修复前勿作对账依据」（不建议长期挂，等后端修）。
验证：§6-1 复现脚本；改后回归锁=`test_webui_stats.py::ledger_db` 增种 `(now−26h).astimezone(ZoneInfo("Asia/Hong_Kong"))` 行并断言 24h 窗不含它。

**F-2a/F-3a｜P1（后端指针）**：`[指针]` `webui_stats.py:213-221` trend `[:limit]` 与 TopN 拆参；`domains/ops/audit/logger.py:209-221` 保留上限应在端点回 `retention_capped`/`total_rows_scanned`；单元语义（行→次）按 `request_id` 去重或 stage 过滤。前端已列可先行文案（§2）。锁：皆无。

**A6a｜P2（后端指针）**：`[指针]` `webui_stats.py:276-278` 畸形 affinity→0.1 造基准值；应回显 `quality:"invalid_row"` 或剔除计数，前端才可如实标「—/坏值」。锁：无。

## 9. 结论摘要（判词）

- 会**直接误导用户决策**的分叉两条：**F-1（Token 窗整体错 8h，实跑证红）**、**F-2（「调用数」=审计行数×1000 行帽，7d/30d 饱和恒等）**。其余 P1：F-3 趋势覆盖率、F-4 cache 双计、F-5 三钟矛盾、L-1 null→0、L-4「最后消息」单位、L-8 发言条数单位。
- 「不造数」违规：前端 3 处（均可自闭环）、后端指针 2 处（归他人）。
- 日历炸弹：已修、本席单跑**绿**（64 passed）。
- 正面范本也应记档：`SemanticState`/reasonKey 不编语义、latency 历史「不画假曲线」、logs 溢出丢弃显式、plugins 三态徽章、knowledge `typeof==='number'` 才渲染。
