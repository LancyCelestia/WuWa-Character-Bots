# V21-S5 Usage/Billing Service 实施日志（A14 计费席）

> 状态：代码+测试完成，全部门禁实跑通过（2026-09-17）。未 commit（共享工作树，提交裁决权在用户）；未部署。
> 合同：`docs/design/backend-v2-product-extensions.md` §1 全节（数据模型/算法/算例/预算），对应 V21-BILL-001/002/003。

## 1. 交付物（全部新增，零文件冲突）

| 文件 | 角色 |
|---|---|
| `plugins/bot_unified_runtime/llm/billing_entities.py` | 严格 Pydantic 实体层 + 错误码 + 金额纪律（Decimal/禁浮点/普通记数序列化） |
| `plugins/bot_unified_runtime/llm/billing_pricing.py` | 语义层：normalize_usage / PriceBook.resolve_price / quote_usage（inclusive/exclusive/区间） |
| `plugins/bot_unified_runtime/llm/billing_service.py` | 服务层：SQLite 存储、CAS 预算、结算/调整/退款、回调去重、聚合、账本迁移与观测面适配 |
| `tests/test_billing_service_v21.py` | 58 例全离线回归（tmp_path SQLite，无网络无 NoneBot 运行时） |
| 本文档 | 实施日志 |

分层依赖单向：`entities ← pricing ← service`；entities 为叶子（仅 pydantic+stdlib，不 import 本包任何模块——`contracts/__init__` 会经 character 链拉起重依赖，故 `V21StrictBase` 按 envelope.py 同例做有意的本地最小复制，收敛归后续装配席位）。

## 2. ledger 复用关系（适配点而非重写）

`llm/ledger.py` **一行未改**。三个适配点：

1. **存量迁移（读）**：`BillingService.migrate_ledger_records(ledger_db_path)` 以只读 URI 连接读 `llm_call_records`，逐行导入为 UsageAttempt + Settlement：
   - `attempt_id=legacy-{request_id}-{call_seq}`、`source_event_key=ledger:{request_id}:{call_seq}` → 重跑幂等（去重表拦截）；
   - 旧 `cost_milli` 保精度迁移：`Decimal(milli)/1000`（毫厘粒度如实保留，**不凭空恢复被舍入的小数**），行级 `pricing_source`（如 channel_spec）记入结算 note；
   - **绝不重算**：迁移不查询 PriceBook——即使事后登记同窗口高价，迁移行金额不变（有测试锁死）；未计价行（unpriced=1）落 `unknown` 结算（「未知不是 0」口径延续）。
2. **观测面回写（写）**：`attach_ledger_sink(sink)` 经既有 `CallRecordSink` 协议在结算后组装 `LLMCallDraft` 提交（fail-open 吞异常，同 ledger 契约）。语义边界显式：draft 的 `prompt_tokens` 传 provider 报告原值（「prompt 含缓存」扣减逻辑归 ledger 自身口径），`total_cost_milli` 由 nano 精度 Decimal 显式量化到毫厘（精度差异如实降级，不假装无损），`pricing_source="billing_v21"`。
3. **口径分界**：新链路不再继承旧账本两处已定性缺陷——「缺缓存价静默回退普通输入价」改为仅 `PriceRevision.cache_price_follows_input=True`（provider 规则显式声明）才回退；`max(0, prompt−cache)` 改为负数抛 `usage_inconsistent`。

## 3. 实体与语义实现要点

### 实体（§1.1 逐字段）
- `UsageAttempt`：operation/attempt/provider_request_id/provider/channel/model/task_kind/owner/scope/trace_id/test_run_id/started/finished/outcome/usage_status/input_semantics/cache_creation_includes_read(bool|null)/raw_usage_schema_version/quantities/source_event_key；
- `UsageQuantity`：metric（9 种，单位由 METRIC_UNITS 钉死）/value/unit/status/source/cache_tier（缓存创建分档）。不变量：value=null ⇔ status∈{unknown,not_applicable}（**未知≠零**）；float 入参在 pydantic before 阶段直接拒绝；
- `PriceRevision`：price_id/version/provider/channel/model/生效窗口（半开 `[from,to)`）/currency(ISO-4217)/components/composition/rounding/cache_price_follows_input/tax_note/source/reviewed_by/adapter_version；
- `ChargeLine`：数量×单价/分母→金额；`amount=None`+`unpriced_unknown_price` = 有量无价（不出假总价）；`amount=0`+`not_billed` = 套餐涵盖（与未知区分）；负金额仅限 refunded/adjustment 行；
- `Settlement`：六态 reserved/estimated/settled/partial/unknown/refunded；不变量 `total_amount is None ⇔ status∈{partial,unknown}`；partial 必须登记 unknown_metrics；**历史不可覆盖** = 调整/退款一律追加 revision（UNIQUE(attempt_id,revision) 硬约束 + prev 链）。
- 所有金额序列化恒为十进制普通记数字符串（`format(v,"f")`，1e-8 → `"0.00000001"` 禁科学计数法）；行级量化精度 nano(1e-9)。

### 语义（§1.2 逐条）
- normalize_usage 按 provider schema 适配注册表定语义缺省（openai=inclusive+includes_read=False；anthropic=exclusive；axonhub/generic=unknown），raw 显式字段优先；token 指标在 tts/image 任务下 not_applicable（**不按字符伪造 Token**，除非 provider 真报告）；负数/NaN/非法 usage 字段降级 unknown 并留痕，绝不造 0；
- total 三规则：provider 报告优先 → 仅 exclusive（适配器确认不重叠）才推导（estimated/derived_non_overlapping）→ inclusive 绝不推导（缓存是输入子集，防二次累计）；
- quote_usage 语义门：inclusive+includes_read∈{True,unknown}+缓存量非零 → `unsupported_usage_semantics` 拒绝自动结算；inclusive+互斥 → ordinary=input−create−read，负数 → `usage_inconsistent`（**禁 max(0)**）；exclusive → ordinary=input；inclusive+缓存用量缺失 → 缓存价与输入价不同（task_uses_cache）则 partial+区间（low/high），缓存不单独计价则按全输入精确计价；unknown 语义 → partial 保守；
- 缺缓存价：默认不回退、行记 unpriced_unknown_price → total=null+partial（known_amount 承载已知部分）；仅显式规则回退且行标 `price_source="follows_input_rule"`；
- 价格解析：`resolve_price(attempt_started_at, route)` 半开区间（边界时刻属新版本）；同版本渠道/模型精确匹配胜通配；无覆盖 → `price_unavailable`。

### 服务（§1.3 逐条）
- 预算：`ensure_budget`（授权包登记，不猜充值额）→ `reserve_budget` SQLite `BEGIN IMMEDIATE` 事务 CAS（微元整数算术，available=limit−reserved−used，不足抛 `budget_exceeded`，并发不超卖）→ `consume_reservation`/`release_reservation`；
- UNKNOWN 纪律：受理后不立即释放预算不重发；`reconcile_unknown` 有 invoice/usage 证据 → 结算，`billed=False` 证据 → 撤销预留，无证据 → 挂账 + alert；partial 结算的预留保持挂起等对账；
- 取消：outcome=cancelled 不阻止结算（取消后收费入账）；
- 去重：`billing_usage_events` 主键 (attempt_id, source_event_key)，重复回调零重复计费；
- 重试归账：多 attempt 同 operation_id，聚合费用归原 operation（失败 attempt 费用不消失）；
- 聚合：`aggregate_usage(UsageFilter, bucket)` 支持 operation/model/channel/provider/owner/task_kind/day 分桶；金额按币种分别汇总（不换汇）；`billed_requests` 在存在未结算/未知结算 attempt 时 =null（**不用成功数顶替**）；
- 调整/退款：`adjust_charge` 追加 revision（deltas 逐计量、refund 全额反向），净额钳制非负，原始行逐字节保留。

## 4. 确定性算例实跑（虚拟测试价，非生产报价）

| 算例 | 断言（全部实跑通过） |
|---|---|
| ① 输入1000含创建100/读取200输出100；价 2/8/2.5/0.2 每百万 | ordinary=700；金额=0.00249；total_tokens=1100（provider 报告，非 1400） |
| ②a 同例+每请求 0.01（additive） | 金额=0.01249 |
| ②b exclusive 请求套餐 0.01 | 金额=0.01（token 行 amount=0/not_billed） |
| ③ TTS 1200 字符×15/百万；绘图 2 张×0.04 | 0.018 / 0.08；Token=not_applicable，零 token 计费行 |
| ④ 缓存读取价未知 | total_amount=null + partial；known=0.00245（读取项单列 200 未计价） |

附加算例：exclusive 语义全输入计价（0.00249 同式）；`cache_price_follows_input=True` 显式回退（0.0028，行标 follows_input_rule）；inclusive 交叠负数（200<100+200）→ usage_inconsistent。

## 5. 测试与门禁证据（实跑）

```
命令（解释器/环境按直跑纪律）：
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_billing_service_v21.py \
  --basetemp="$TEMP/v21-billing" -p no:cacheprovider -q
→ 58 passed in 4.64s

ruff（同解释器，4 文件）：All checks passed!
mypy（--explicit-package-bases --ignore-missing-imports，cache 落 TEMP）：
  billing 三模块 0 错误（控制台仅剩 control_plane/api/platform.py 2 个存量错误，非本席文件域）
树卫生：无 __pycache__/*.pyc；qx.json 完好
```

覆盖清单（任务书 18 项全命中）：inclusive/exclusive、缓存交叠负数、NaN 拒绝（pydantic finite + 实体校验双门）、缺字段、不支持单位/计量、微额精度（1 token×0.01/1M=0.00000001 TEXT 精确保留）、价格跨生效边界（含边界时刻归属）、混合币种分币汇总、退款（追加 revision+净额0+原行保留）、超额退款拒绝、取消后收费、重复回调去重、重试汇总归原 operation、并发预留不超卖（8 线程×2 实例争 1000μ → 恰 3 成 900μ）、月账重算一致（日桶合计==总计，重跑逐项相等）、排行榜合计==attempt 账本、billed_requests 账单未知=null、legacy 迁移保精度/不重算/幂等、价格登记跨重启持久。

## 6. 已知边界与遗留

1. **REST 端点与 SSE 事件属后续席位**（GET /usage/attempts|summary|rankings、/billing/prices|settlements、POST /billing/quote|prices/preview|activate|reconciliations|adjustments；SSE usage.recorded/billing.settled/budget.threshold）。本层为离线语义/存储层，函数面即 §1.2 接口清单，REST 薄封装即可。
2. **tiered 计费为结构预留**：composition 字段与 PriceComponent.bracket_up_to 已登记，阶梯费率选择未实装（任务书测试项未要求，按最小实现纪律不做半吊子）。
3. **权限/审计面未做**：排行敏感读取审计、普通用户仅见自己范围——归 REST/控制面席位（聚合层已支持 owner/test_run_id 过滤）。
4. **迁移窗口**：`migrate_ledger_records` 全量读（无 window_days 分批）；生产首迁若账本大需加批次游标（表有 id 主键可增量）。
5. **并行席位重叠上报（需协调人裁决）**：`llm/usage_service.py`（1632 行，头部标注「W5 席 / S5」）+ `tests/test_usage_billing_v21.py` 为工作树中**已存在的未跟踪 WIP**，与 S5 范围同题。本席按任务书文件域（billing_service.py 族，全部新增）实现，**未读改/未依赖**该 WIP，零文件冲突；两套实现的收敛（或裁留）建议由协调人统一裁决，本日志 §2/§3 语义口径可作比对基准。
6. 预算维度登记了 scope_kind（principal/operation/provider/test_run 由调用方组合），「按测试 run 限制」的授权包联动属 §8 AcceptanceRun 席位。
