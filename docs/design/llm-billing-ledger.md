# B5 设计规格：LLMCallRecord 结构化计费表 + Provider/Balance 适配

> 状态：设计规格（本轮不含实现代码），目标读者为下一实施会话。
> 上游裁决文档：
> - `docs/project-audit-and-modernization-roadmap-2026-09-05.md`（归档 zip 内；本文输入：§6.2、§7.7、§9 阶段 4、§14.5）
> - `docs/control-plane-provider-and-usage-requirements-2026-09-05.md`（工作区内；本文输入：§5 LLMCallRecord、§6.1 UsageCollector、§17 计费身份分离、§18 NewAPI 适配、§20 指标合同）
> 配套文档：`docs/design/control-plane-api.md`（/usage 端点消费本表）。
> 日期：2026-09-12。现状断言均经 grep 核实（标注文件与行号区间）；无法核实处标注 unknown。

---

## 1. 目标与裁决对齐

| 裁决 | 来源 | 本文落实 |
|---|---|---|
| 文本日志聚合"不适合作为供应商、会话、图表、账单和历史查询的长期事实源" | roadmap §7.7 | 新建 `llm_call_records` 表为唯一计费事实源 |
| 每次模型调用写结构化记录（provider/model/session/tokens/费用/延迟/状态/错误/时间）；`runtime_event_log` 退回运行日志职责 | roadmap §9 阶段 4.1-4.2 | §3 DDL + §4 写入点 |
| 不能查询余额的 provider 标 `balance_capability=unsupported`，不能伪造为 0 | roadmap §9 阶段 4.5 | §7.1 适配器合同 |
| 余额、Token 消耗、单次费用分开建模；未知余额/消耗显示 unknown 不是 0 | 需求文档 §1.4-1.5 | §3/§7 |
| 首字延迟无数据时为 unknown，不用总耗时伪造 | 需求文档 §20 | §3 `first_token_latency_ms` 可空 |

## 2. 现状盘点（全部 grep 核实）

### 2.1 当前计量链路（文本聚合）

```text
llm/providers.py:352  _extract_usage()      归一化 OpenAI/DeepSeek/Anthropic 三类缓存字段
                                            → cache_read_tokens / cache_write_tokens（:352-377）
llm/providers.py:86   LLMReply.raw_usage    usage 以 dict 挂在回复上（LLMReply 还有 attempts: list[str]，:99）
capabilities/chat.py:2020 _llm_usage_audit_tags()
                                            把 usage 折成审计标签：llm_usage_prompt_tokens: / …_completion_tokens:
                                            / …_total_tokens: / …_cache_read_tokens: / …_cache_write_tokens:
                                            / …_cost_milli: 或 llm_usage_cost_unpriced:1（:2020-2058）
                                            cost 经 pricing.model_call_cost_milli 计算（只按 prompt+completion 计价）
__init__.py:987       _runtime_tag_values() 从发送请求的审计标签反解出 usage 字段
__init__.py:5718      _log_runtime_event(…, "transport_receipt", …)
                                            把 usage 写进文本事件行；注意：total_tokens<=0 时
                                            usage 字段整体不写（__init__.py:1025-1026）
sources/runtime_event_log.py:178  aggregate_llm_usage_range()
                                            逐行文本解析：只认 event=transport_receipt 行、
                                            按 request_id 去重、total_tokens>0 过滤、
                                            cost_milli 与 cost_unpriced=1 计数、按模型名分组
runtime/usage_monitor.py:240  _aggregate_since()  调用上述聚合（60s 阈值巡检 + 13/18/23 点报告的数据源）
```

文本日志文件：`data/runtime_events.log`（`BOT_RUNTIME_LOG_FILE`），默认 2 MB 轮转、仅保留 `.old` 一代（runtime_event_log.py:5-10,57-62,77-96）。

### 2.2 该链路的结构性缺陷（本设计动机）

1. **保留窗口极短**：2 MB × 2 代，数小时到一两天即被轮转覆盖；无法支撑 7d/30d/365d 窗口（roadmap §6.2 明确缺失）。
2. **计费与投递耦合**：聚合只统计 `transport_receipt` 行——usage 先被折成发送审计标签、再在消息投递时回写日志，LLM 调用本身没有独立落账点；发送失败/静默路径的调用存在漏计风险（影响幅度未量化，unknown）。
3. **计价不完整**：`model_call_cost_milli` 只按 input+output 计价（pricing.py:46-62），cache_read/cache_write token 虽统计但不参与费用；费用单位毫厘（1 元 = 1000 毫厘，pricing.py:52）。
4. **价格双轨**：计费用 `Config.bot_model_prices`（config.py:637）；渠道排序用注册表条目 `price_in/price_out`（model_router.py:298-299，按 `(price_in+price_out)/2` 均值升序，缺价渠道靠后，model_router.py:297,521-523）。两处价格可能不一致，无对账。
5. **无维度**：按模型名分组是唯一维度；无 provider/channel、无 session、无 effort、无错误类型聚合、无耗时分布。
6. **attempts 只进文本**：`ModelRouter.generate()` 的 attempts 标记（`{model_id}:{error_kind}` / `{model_id}:success` / `{model_id}:config_missing` / `failover:deadline` / `hedged:{id}:winner|loser`，model_router.py:1028,1375,1398,1464,1480-1482）发布在 `reply.attempts`/`self.last_attempts`（D6 语义：attempts 归调用私有，出口统一发布，model_router.py:1313-1367），未结构化落库。
7. **诊断表不承担账单**：`runtime_diagnostics` 有 llm_status/provider/model/error_kind 与基础三项 token（diagnostics.py:60-76），但保留约 100 条、无 cache/费用/耗时/attempts，定位是排障不是计费。

### 2.3 错误类型枚举（现状，供 status/error_kind 沿用）

`providers.py` 中 `LLMProviderError.error_kind` 的实际赋值：`timeout`（:214,557）、`provider_error`（:220,567）、`schema`（:465,470,515）、`empty_response`（:507,521）、`config_missing`（:412,416）、`rate_limited`（:252 归类）、`network`（:559）。`_FAILOVER_ERROR_KINDS`（:31）为可触发故障转移的子集（含 `rate_limited` 等，完整成员清单以 :31-52 为准）。

## 3. LLMCallRecord 表结构（DDL 草案）

库：新独立 SQLite `data/llm_billing.sqlite3`（路径经 `scripts/runtime_paths.py` 重映射机制，与 channel_health `resolve_default_db_path` 同法，channel_health.py:356）。开 WAL；写入方单写多读。

```sql
CREATE TABLE IF NOT EXISTS llm_call_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 标识与作用域
    request_id  TEXT NOT NULL,            -- 消息/任务级请求 id（现 RuntimeEventLog 同名语义）
    call_seq    INTEGER NOT NULL DEFAULT 1,  -- 同一 request_id 内第几次 generate（记忆抽取/摘要等旁路调用 >1）
    session_id  TEXT NOT NULL DEFAULT '',    -- 会话作用域（私聊/群/旁路任务为 'task:<capability>' 形态）
    capability  TEXT NOT NULL DEFAULT '',    -- 'bot.chat' / 'memory.extract' / 'group.digest' 等

    -- 时间与延迟（需求文档 §20 指标合同）
    started_at    TEXT NOT NULL,            -- ISO8601 本地时区
    completed_at  TEXT NOT NULL,
    duration_ms   INTEGER,                  -- completed_at - started_at
    first_token_latency_ms INTEGER,       -- 无流式首字数据时 NULL（=unknown，不伪造）

    -- 渠道与模型（roadmap 阶段 4.1 字段口径）
    provider_id   TEXT NOT NULL DEFAULT '',  -- 阶段1 = 渠道 model_id（现无独立 provider 实体，见 §8 开放问题1）
    model_id      TEXT NOT NULL,             -- 注册表渠道 id（ModelSpec.model_id）
    actual_model  TEXT NOT NULL DEFAULT '',  -- 实际请求的上游模型名（ModelSpec.model）
    effort        TEXT NOT NULL DEFAULT '',  -- 本调用生效的 reasoning effort（_resolve_effort 结果）
    routing_group TEXT NOT NULL DEFAULT '',  -- ModelSpec.routing_group

    -- Token（未知为 NULL；上游无 usage 时不得写 0 冒充）
    prompt_tokens          INTEGER,
    cache_creation_tokens  INTEGER,
    cache_read_tokens      INTEGER,
    completion_tokens      INTEGER,
    total_tokens           INTEGER,

    -- 费用（毫厘，1 元=1000 毫厘，沿用 pricing.py 口径；NULL=unpriced）
    input_cost_milli      INTEGER,
    cache_read_cost_milli INTEGER,        -- 过渡期 NULL（§5 计价口径）
    output_cost_milli     INTEGER,
    total_cost_milli      INTEGER,
    currency              TEXT NOT NULL DEFAULT 'CNY',
    pricing_source        TEXT NOT NULL DEFAULT 'unknown',  -- registry | model_prices | inferred | unknown
    unpriced              INTEGER NOT NULL DEFAULT 0,

    -- 路由轨迹与结果
    attempts_json TEXT NOT NULL DEFAULT '[]',  -- ModelRouter attempts 标记数组（§2.1.6 格式）
    attempts_count INTEGER NOT NULL DEFAULT 0,
    finish_reason  TEXT NOT NULL DEFAULT '',   -- safe_llm_finish_reason 白名单值
    status         TEXT NOT NULL,              -- success | provider_failed | deadline
    error_kind     TEXT NOT NULL DEFAULT '',   -- §2.3 枚举
    error_summary  TEXT NOT NULL DEFAULT '',   -- 脱敏短文本（redact_private_debug 后，≤200 字符）

    -- 记账元数据
    source     TEXT NOT NULL DEFAULT 'router',  -- router | backfill
    schema_ver INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_llm_call_started ON llm_call_records (started_at);
CREATE INDEX idx_llm_call_model   ON llm_call_records (model_id, started_at);
CREATE INDEX idx_llm_call_session ON llm_call_records (session_id, started_at);
CREATE INDEX idx_llm_call_request ON llm_call_records (request_id);
```

粒度裁决：**一行 = 一次 `ModelRouter.generate()` 调用**（成功或最终失败各一行）。failover 中间渠道的逐次尝试不单列行，由 `attempts_json` 承载（与 D6"attempts 归调用私有、出口统一发布"的单点发布语义天然对齐，model_router.py:1313-1316）。影子并发（hedged）的 loser 渠道已在 attempts 标记中体现（`hedged:{id}:loser`），不单列。

保留策略：明细表全量保留 90 天；长期事实进日聚合表（§5.2），聚合表不设过期。删除任务挂 APScheduler 每日一次。

## 4. 写入点设计

### 4.1 唯一写入点：`ModelRouter.generate()` 出口

`generate()`（model_router.py:1267）在出口处（成功 `reply` 与最终异常两分支，即 attempts 整体发布到 `reply.attempts`/`exc.attempts` 的同一位置，model_router.py:1364-1385）组装一条 `LLMCallDraft` 并交给注入的 recorder：

```text
LLMCallDraft = {
  request_id, call_seq, session_id, capability,        # 经 generate() kwargs/上下文传入（新增可选参数）
  started_at, completed_at, duration_ms,
  provider_id/model_id/actual_model/effort/routing_group,  # 胜出渠道 ModelSpec
  tokens…（reply.raw_usage 归一化；失败调用全 NULL）,
  attempts_json = attempts, attempts_count = len(attempts),
  finish_reason, status, error_kind,
  cost 四项 + pricing_source（由 PricingService 计算，§5）
}
```

设计约束：

1. **router 不依赖 DB**：recorder 以 Protocol 注入（`class CallRecordSink: def submit(draft) -> None`），router 只依赖 Protocol；smoke/测试注入内存假件（现有 `tests/test_model_router_failover.py` 的注入风格沿用）。
2. **失败不阻塞业务**：`submit()` 内部 catch 全部异常只打日志——计费故障不得影响聊天（与 `_log_runtime_event` 同等容错纪律，__init__.py:979）。
3. **SQLite 写入**：`submit()` 入内存队列（`queue.SimpleQueue`）+ 单独写线程批量 flush（每 2 秒或 50 条）；进程退出 atexit 冲刷。理由：generate 运行于 worker 线程（roadmap §7.1 语境），直接在调用线程写 SQLite 会把盘抖动带进聊天延迟。队列无界上限 10_000 条，满则丢弃最旧并计数告警。
4. **旁路 LLM 调用同口径**：记忆抽取、群摘要等旁路 generate 走同一 router 出口，`capability` 字段区分；`call_seq` 由 router 内 per-request 计数器维护。

### 4.2 与现有链路的关系（不删除，降级）

| 现有件 | 处置 |
|---|---|
| `chat.py _llm_usage_audit_tags`（chat.py:2020） | 保留——审计标签仍供 QQ 报告/诊断使用 |
| `__init__.py transport_receipt` 事件（:5718） | 保留——运行日志职责（roadmap 阶段 4.2 原话） |
| `runtime_event_log.aggregate_llm_usage_range`（:178） | 保留为**兼容层**：仅在 ledger 为空/不可用时由 B4 usage service 回退调用（control-plane-api.md §6.2） |
| `usage_monitor._aggregate_since`（usage_monitor.py:240） | 切换到 `LedgerService.aggregate()`；加配置 `BOT_USAGE_LEDGER_FALLBACK_TEXT=true`（默认 true 一个版本，验证对拍后可关） |
| `diagnostics.runtime_diagnostics`（diagnostics.py:121） | 不动——排障职责 |

## 5. 费用计算与价格统一

### 5.1 PricingService

新建 `runtime/ledger/pricing_service.py`，合并双轨价格（§2.2.4）：

```text
price_lookup(model_id, actual_model) -> PriceBook | None
PriceBook = { input, output, cache_read=None, cache_create=None, currency, source }
优先级：1) 注册表条目 price_in/price_out（model_router.py:298）
        2) bot_model_prices[actual_model]（config.py:637，经 pricing.parse_model_prices）
        3) None → unpriced=1，全部 cost 列 NULL
```

计费公式（过渡口径）：

```text
input_cost  = prompt_tokens / 1e6 * input_price
output_cost = completion_tokens / 1e6 * output_price
total       = round((input_cost + output_cost) * 1000)  # 毫厘
```

**cache 计价过渡裁决**：现状费用不含 cache token（pricing.py:46-62），价格表只有 input/output 两价。cache_read_cost 列本阶段写 NULL、总费用维持现状口径（不高估），等需求文档 §5 四价模型（input/cache_create/cache_read/output 各价）在配置面落地后启用完整公式——届时 `schema_ver` 升 2，只影响增量行。token 数照实入列（对账上游账单时需要）。

`pricing_source` 逐调用记录实际命中来源；registry 与 model_prices 同名条目价格不一致不告警（排序价与计费价语义不同），但 LedgerService 提供对账查询（§6.3）暴露差异。

### 5.2 日聚合表（长期事实源）

```sql
CREATE TABLE IF NOT EXISTS llm_usage_daily (
    day TEXT NOT NULL,                    -- 'YYYY-MM-DD' 本地日
    dimension TEXT NOT NULL,              -- 'all' | 'model' | 'session'
    dimension_key TEXT NOT NULL DEFAULT '',
    calls INTEGER NOT NULL DEFAULT 0,
    failed_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_milli INTEGER NOT NULL DEFAULT 0,   -- NULL 成本不计入，另记 unpriced_calls
    unpriced_calls INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, dimension, dimension_key)
);
```

由每日任务回填昨日 + 启动时补齐缺口（幂等 upsert）；当日实时查询走明细表。

## 6. 聚合查询（LedgerService）

### 6.1 窗口与维度

窗口枚举：`24h / 7d / 30d / 365d / all`（本地时区滚动窗口；`all` 不限时间）。维度：`all / model / session`（provider 维度待独立 provider 实体后启用，§8 开放问题 1）。

### 6.2 参考查询

按模型 7 天成本：

```sql
SELECT model_id,
       COUNT(*) AS calls,
       SUM(status='success') AS ok_calls,
       SUM(prompt_tokens)  AS prompt_tokens,
       SUM(cache_read_tokens) AS cache_read_tokens,
       SUM(completion_tokens) AS completion_tokens,
       SUM(total_tokens)   AS total_tokens,
       SUM(total_cost_milli) AS total_cost_milli,
       SUM(unpriced) AS unpriced_calls
FROM llm_call_records
WHERE started_at >= :since
GROUP BY model_id
ORDER BY total_cost_milli DESC;
```

按会话 24 小时（B4 `usage/summary?scope=session` 数据源）；日聚合报表直接读 `llm_usage_daily`。

### 6.3 对账查询（运维用）

- 双轨价差：`registry price_in/out` vs `bot_model_prices` 同名条目差异清单；
- 文本聚合 vs ledger 同窗对拍（`aggregate_llm_usage_range` 结果与明细表求差），差值 > 2% 时在用量报告标注"数据源切换中"；
- unpriced 调用清单（引导补价格配置）。

## 7. Provider/Balance 适配

### 7.1 适配器接口

```python
class BalanceAdapter(Protocol):
    capability: Literal["newapi_self", "openai_dashboard", "unsupported"]
    async def fetch(self, ctx: BalanceContext) -> BalanceSnapshot: ...
# BalanceContext: { base_url, credential_ref 解析后的临时 token(仅内存), user_uid, timeout, quota_scale, unit }
# BalanceSnapshot（需求文档 §5 BalanceSnapshot 字段口径）:
# { provider_id, valid: bool, invalid_message: str,
#   remaining: float|None, used: float|None, total: float|None,
#   plan_name: str, currency: str, unit: str,
#   source_endpoint: str, raw_status_code: int|None, queried_at: datetime }
```

- 每渠道 `ModelSpec` 侧挂 `balance_adapter_id`（阶段 1 经注册表条目扩展字段或控制面配置，未配置 = `unsupported`——UI/API 呈现 unsupported，不伪造 0）；
- 失败映射（需求文档 §18.2 口径）：`success=true`→valid；401/403→auth_required；429→rate_limited；5xx→provider_error(retryable)；字段缺失→invalid_response；`valid=false` 时数值字段为 NULL，不回 0。

### 7.2 NewAPI 适配器（合同形态）

按需求文档 §18.1（用户确认口径，verified）：

```text
GET {baseUrl}/api/user/self
Content-Type: application/json
Authorization: Bearer {accessToken}
New-Api-User: {userId}
换算：remaining = quota / configured_quota_scale；used = used_quota / configured_quota_scale
      total = remaining + used；plan_name = data.group
configured_quota_scale 默认 500000，但必须是该渠道 balance profile 配置，不写死全局
```

`/v1/dashboard/billing/subscription` 与 `/v1/dashboard/billing/usage`（openai_dashboard 合同）：one-api/new-api 系站点的通用兼容形态为——subscription 回 `hard_limit_usd` 等字段（one-api 语义：表示剩余额度口径），usage 回 `total_usage`（0.01 美元分口径），`remaining = hard_limit_usd - total_usage/100`。此口径为 high 置信的社区通用合同，**各站点实现差异未经逐站实测（unknown）**，实施时必须以目标站点实际响应为准并允许按渠道覆盖字段路径（字段映射机制复用需求文档 §6.2 `ProviderUsageSnapshot` 的 `raw_field_path` 思路）。两类合同的开关：`balance_adapter_id = newapi_self | openai_dashboard | custom:<extractor_id>`。

安全：token 只存 `credential_ref`（`env:VAR` 引用，同 ModelSpec 机制 model_router.py:316）；适配器日志不得含 token/Cookie 完整响应；`New-Api-User` 头只在 newapi_self 适配器中发送（需求文档 §18.1 明令）。

### 7.3 余额缓存策略

```sql
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    valid INTEGER NOT NULL,
    invalid_message TEXT NOT NULL DEFAULT '',
    remaining REAL, used REAL, total REAL,
    currency TEXT NOT NULL DEFAULT '',
    plan_name TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    source_endpoint TEXT NOT NULL DEFAULT '',
    raw_status_code INTEGER,
    queried_at TEXT NOT NULL
);
CREATE INDEX idx_balance_provider ON balance_snapshots (provider_id, queried_at);
```

- **读路径一律走快照**：API/UI 只读最近一条，不在请求路径上实时拉取（公网 3GB/日预算下尤其如此，control-plane-api.md §9.4）；
- 自动轮询间隔：每渠道可配，下限 300 秒（需求文档 §15.3 `balance_poll_min_interval=300`）；`unsupported` 渠道不轮询；
- 退避：429 → 指数退避至多 1 小时；连续 3 次失败 → 暂停该渠道轮询并告警；
- 手动刷新：`POST /admin/api/v1/providers/{id}/balance/refresh`（B4 端点）绕过 TTL 但受 60 秒限频；刷新结果写快照，失败也写 invalid 行（保留失败事实）；
- 历史快照保留 90 天，供 `balance/history` 曲线。

## 8. Extractor 沙箱（仅登记，不设计实现）

按任务边界与需求文档 §8/§19，用户自定义余额脚本（ES2020 extractor）**本轮只登记为待用户脚本占位**：

- 注册表字段：`extractor_id, provider_id, version, source_hash, enabled(默认 false), created_by, last_tested_at, last_test_result`（需求文档 §19.3 原样采纳）；
- 红线（将来实现时不可妥协）：禁 `eval`、禁网络/文件/进程/模块加载、仅注入脱敏 response/baseUrl/userId/credential proxy、CPU/内存/时长/输出上限、只返回 JSON 可序列化对象；
- 本阶段 `custom:<extractor_id>` 适配器选择器保留但选择即报 `extractor_not_available`；
- 触发条件：用户提供各站点脚本与字段说明后，另立设计文档再实现（需求文档 §13 列出 10 项待资料）。

## 9. 历史回填（一次性，可选）

`scripts/runtime_paths.py` 同级的回填脚本（放 `scripts/`，运行于 Runtime 环境）：解析现存 `runtime_events.log(.old)` 的 `transport_receipt` 行 → 明细行（`source='backfill'`，cache/费用字段按可得性，缺失 NULL）→ upsert 当日 `llm_usage_daily`。文本窗口通常仅 1-2 天，回填价值有限；脚本必须幂等（request_id 去重，同聚合器 seen_requests 语义 runtime_event_log.py:238-244）。不作为验收项。

## 10. 分阶段交付与回滚

| 阶段 | 内容 | 验收 | 回滚 |
|---|---|---|---|
| M1 | DDL 建库 + CallRecordSink + router 出口接线 + PricingService | 单测：成功/失败/旁路调用各产一行；attempts_json 与 reply.attempts 一致；计费故障不影响聊天（sink 抛错演练） | router 侧 recorder 注入参数缺省 None → 完全不写，行为回到现状 |
| M2 | LedgerService 聚合 + usage_monitor 切换（fallback 开关） | 7 天窗口数字与文本聚合对拍（重叠期差值 <2%）；QQ 报告正常 | 置 `BOT_USAGE_LEDGER_FALLBACK_TEXT=true` 即回文本聚合 |
| M3 | 日聚合表 + B4 /usage 端点切正式源 | 窗口/维度端点实测；unpriced 清单可见 | 端点回 fallback（control-plane-api.md §6.2） |
| M4 | BalanceAdapter（newapi_self + openai_dashboard）+ 快照缓存 + 刷新端点 | 对至少一个 NewAPI 系渠道实测快照；unsupported 渠道如实呈报 | 不注册 adapter 即无该功能，无残留 |
| M5 | 90 天清理任务 + 回填脚本（可选） | 清理后索引/体积核查 | 删除任务即可 |

## 11. 测试要求

- pytest：DDL 迁移幂等、sink 队列冲刷与丢弃告警、PricingService 三级价查、聚合 SQL 与手算对拍、balance 适配器（httpx MockTransport：200/401/429/5xx/字段缺失五类）、快照 TTL/退避。
- 对拍测试：同一批 fixture 事件分别过文本聚合器与 ledger，断言 tokens/calls 一致（费用允许差异：cache 计价口径不同需在断言中显式声明）。
- 实测：dev.ps1 `test`/`lint` 三任务（工作区规定入口）；真渠道调用后查行落库。

## 12. 开放问题

1. **provider 实体时机**：现无独立 Provider 领域对象，`provider_id` 阶段 1 以渠道 `model_id` 兼充；等控制面 Provider/Model 分离管理（需求文档 §2/§3）落地后是否迁移字段——迁移成本 vs 收益待 M4 后评估。
2. cache_read/cache_write 计价的启用时点与默认折扣系数（四价模型需配置面先行）。
3. 旁路调用（记忆抽取/摘要）的 `session_id` 命名规范（`task:<capability>` 暂定，需与诊断/审计侧统一）。
4. `call_seq` 的 per-request 计数器在 router 无状态化前提下如何传递（kwargs 注入 vs request 上下文对象）——实施会话定。
5. openai_dashboard 各站点响应字段实测（§7.2 已标 unknown），决定字段路径覆盖机制的最终形态。
6. balance 快照是否并入 `llm_billing.sqlite3`（当前裁决并入同库，若轮询渠道多可拆）。
7. 回填脚本的运行入口是否纳入 dev.ps1（倾向不纳入，保持 scripts 手动）。
