# Control Plane Provider、模型与用量监控需求

> 编写日期：2026-09-05  
> 状态：需求整理与接口设计，尚未进入业务代码实现。  
> 外部附件中的 JavaScript extractor 仅作为格式样例，不执行、不直接信任、不把单一站点字段假定为所有供应商通用字段。

## 1. 目标

为后续 TailAdmin Vue 控制面提供稳定后端合同，先完成供应商、模型、连接检测、余额/用量、日志统计和权限策略，UI 后置。

核心原则：

1. 供应商配置与模型配置分离。
2. 菜单显示名与真实 API model ID 分离。
3. 完整 URL、非完整 URL、相对路径和自定义 endpoint 均可表达。
4. 余额、Token 消耗、单次费用和日志统计分开建模。
5. 没有协议就返回 `unsupported`，不能把未知余额或未知消耗显示为 0。
6. 所有高风险请求、脚本 extractor 和连接检测均有超时、限额、审计和凭据隔离。
7. API 先稳定，TailAdmin Vue 只消费 DTO，不直接读写 `.env` 或 SQLite。

## 2. 供应商配置合同

建议领域模型 `ProviderConfig`：

```text
provider_id: string                 稳定内部 ID，不随显示名变化
name: string                        供应商名称
note: string                        备注
official_url: string                官网链接，可为空
base_url: string                    基础 URL，可为完整或非完整 URL
api_request_url: string             官网/请求地址，可为完整或相对地址
api_style: enum                     openai_compatible/responses/anthropic/custom
enabled: bool                       是否启用
credential_ref: string              凭据引用，不保存明文 Key
balance_adapter_id: string          余额查询适配器
balance_script_id: string           自定义余额脚本引用
model_list_endpoint: string         获取模型列表地址
website_probe_endpoint: string      网站联通检测地址
model_probe_endpoint: string        模型联通检测地址
chat_probe_policy: object           模型对话联通检测策略
request_headers_template: object    非敏感请求头模板
request_query_template: object      查询参数模板
request_body_template: object       请求体模板
url_join_policy: object             URL 拼接规则
request_timeout_seconds: number     默认请求超时
balance_poll_interval_seconds: int  余额自动查询间隔
model_poll_interval_seconds: int    模型列表自动查询间隔
created_at: datetime
updated_at: datetime
```

### 2.1 URL 规则

必须支持以下输入：

```text
https://example.com
https://example.com/v1
https://example.com/v1/chat/completions
/v1
v1
chat/completions
```

内部不要用字符串拼接散落处理。统一通过 `EndpointResolver` 生成：

```text
resolve_base_url(provider.base_url)
resolve_request_url(provider.base_url, provider.api_request_url, operation)
resolve_model_list_url(provider.base_url, provider.model_list_endpoint)
resolve_probe_url(provider.base_url, endpoint, operation)
```

规则需要明确：

- 是否自动补 scheme；
- 是否去除末尾 `/`；
- 是否允许 endpoint 已经包含 `/v1`；
- 是否允许 endpoint 已经包含 `/chat/completions`；
- 完整 URL 优先于 base URL 拼接；
- 禁止 URL 内嵌用户名、密码、API Key；
- 公网模式禁止任意 SSRF，必须做域名/IP 策略检查；
- loopback、内网、代理和公网目标分别记录安全状态。

## 3. 模型配置合同

建议领域模型 `ModelConfig`：

```text
model_id: string                     内部稳定 ID
provider_id: string                  所属供应商
menu_name: string                    菜单显示名，可统一大小写/格式
actual_model_id: string              实际请求 ID，原样保存、原样发送
model_aliases: list[string]          搜索/命令别名
enabled: bool                        是否启用
is_default: bool                     是否为供应商默认模型
context_window_tokens: int           上下文窗口
max_output_tokens: int               最大输出
reasoning_level: string              思考等级
judicial_level: string               用户原始需求字段，暂作可扩展等级字段
custom_parameters: object             供应商/模型自定义参数
capabilities: list[string]            chat/vision/tools/embedding 等
input_price_per_million: number      输入基础价格
cache_create_price_per_million: number
cache_read_price_per_million: number
output_price_per_million: number
billing_multiplier: number           计费倍率
currency: string                     计费币种
pricing_source: string               价格来源和版本
priority: int
health_state: string                 healthy/degraded/disabled/unknown
last_probe_at: datetime
created_at: datetime
updated_at: datetime
```

### 3.1 显示名和真实模型 ID

必须严格保持：

```text
菜单显示名：用户可修改，用于 UI、命令和列表展示
实际模型 ID：供应商/API 使用，保存原样，不能因为统一格式而 lower-case 或重写
```

例如：

```json
{
  "menu_name": "GPT-6 Astra",
  "actual_model_id": "gpt-6-astra"
}
```

排序、默认模型、模型列表和盲测均通过内部 `model_id` 关联，不能使用显示名作为唯一键。

### 3.2 默认模型和获取模型列表

必须提供：

```text
GET  /admin/api/v1/providers/{provider_id}/models
POST /admin/api/v1/providers/{provider_id}/models/refresh
GET  /admin/api/v1/models
POST /admin/api/v1/providers/{provider_id}/default-model
```

模型列表来源按优先级：

1. 供应商官方模型列表接口；
2. OpenAI-compatible `GET /models`；
3. 自定义模型列表 endpoint；
4. 手工登记的模型；
5. 缓存的上一次成功列表。

模型列表返回必须同时包含：

```text
actual_model_id
menu_name
provider_id
capabilities
context_window_tokens
pricing_state
health_state
last_seen_at
```

获取列表失败时不能覆盖已有模型；应返回错误状态并保留旧缓存。

## 4. 自定义窗口、思考等级和扩展等级

“自定义窗口”建议拆成两个明确字段：

- `context_window_tokens`：供应商模型允许的最大上下文；
- `request_context_budget_tokens`：本项目单次请求实际使用预算。

思考等级建议统一为：

```text
off / low / medium / high / xhigh / max / ultra / custom
```

不同供应商映射通过 `ReasoningAdapter` 处理：

```text
OpenAI-compatible: reasoning_effort
Responses API: reasoning.effort
Qwen/DashScope: enable_thinking + thinking_budget
Anthropic: provider-specific extended thinking
Custom: custom_parameters
```

用户提出的“司法等级”目前无法确定准确业务含义，不能擅自解释。暂时保留为：

```text
judicial_level: string | null
custom_parameters: object
```

收到您后续的准确字段说明后，再决定它是安全等级、审计等级、回答等级还是其他业务参数。

## 5. 计费模型

余额金额不能替代 Token 消耗统计。系统必须分别保存：

```text
BalanceSnapshot
- provider_id
- account_ref
- plan_name
- total_amount
- used_amount
- remaining_amount
- currency
- valid
- queried_at
- source
- raw_status_code

LLMCallRecord
- request_id
- session_id
- provider_id
- model_id
- actual_model_id
- prompt_tokens
- cache_creation_tokens
- cache_read_tokens
- completion_tokens
- total_tokens
- input_cost
- cache_creation_cost
- cache_read_cost
- output_cost
- total_cost
- billing_multiplier
- currency
- latency_ms
- status
- error_kind
- started_at
- completed_at
- source
```

费用计算建议：

```text
实际费用 =
  prompt_tokens / 1,000,000 * input_price
+ cache_creation_tokens / 1,000,000 * cache_creation_price
+ cache_read_tokens / 1,000,000 * cache_read_price
+ completion_tokens / 1,000,000 * output_price
然后乘以 billing_multiplier
```

如果某供应商的计费公式不是上述形式，使用 `PricingAdapter`，并保存公式版本和来源。

## 6. 日志监听与 Token 统计

### 6.1 日志来源

实现 `UsageCollector`，按优先级采集：

1. LLM provider 响应中的 usage 字段；
2. 本项目发送/运行日志中的结构化 usage；
3. 供应商 usage API；
4. 自定义 extractor；
5. 无法确认时标记 `unknown`，不猜测。

当前项目已有：

- `runtime/usage_monitor.py`；
- `runtime/pricing.py`；
- `sources/runtime_event_log.py`。

后续应从日志文本聚合迁移到 `LLMCallRecord`，日志只作为审计和故障诊断来源。

### 6.2 站点差异

各站点的“消耗量、消耗客户数、消耗前用量、消耗进、首进总量”等字段不得强行映射成同一个字段。使用：

```text
ProviderUsageSnapshot
- provider_id
- metric_name
- metric_value
- metric_unit
- metric_semantics
- source_endpoint
- queried_at
- raw_field_path
- confidence
```

每个供应商可定义字段映射：

```json
{
  "used": "data.used_quota",
  "remaining": "data.quota",
  "total": "data.quota + data.used_quota",
  "unit": "USD",
  "metric_semantics": "provider_quota_units"
}
```

表达式计算必须在受限 evaluator 内执行，不能使用 Python `eval` 或任意 JavaScript 环境。

## 7. 余额和用量查询配置

后端配置至少支持：

```text
website_password_ref       网站访问密码引用
request_url                请求地址
user_uid                   用户数字 UID
access_token_ref           Bearer/API Token 引用
request_timeout_seconds    请求超时时间
auto_query_interval        自动查询间隔
http_method                GET/POST/...
headers_template           请求头模板
query_template             查询参数模板
body_template              请求体模板
extractor_id               提取器引用
extractor_source           受限脚本引用
currency                   币种
unit_scale                 单位换算倍率
timezone                   时间区
retry_policy               重试和退避
```

密码、Token、Cookie 只允许使用 `credential_ref`，不返回明文。

## 8. 提取器执行安全

附件说明要求 extractor 支持 ES2020+、变量替换和对象返回。该能力必须隔离：

- 独立 worker 或受限 JavaScript runtime；
- 禁止网络、文件、进程、模块加载、动态 import、宿主对象访问；
- 仅向脚本注入脱敏后的 response、baseUrl、userId 和 credential proxy；
- 设置 CPU 时间、内存、执行时长、输出大小和嵌套深度上限；
- 只允许返回 JSON 可序列化对象；
- 记录脚本版本、输入哈希、输出字段、错误和耗时；
- 禁止把完整响应、密码、Token、Cookie 写入日志；
- 表达式和字段映射优先于脚本；脚本只处理无法声明式表达的供应商差异。

支持的标准返回字段：

```text
isValid: boolean?
invalidMessage: string?
remaining: number?
unit: string?
planName: string?
total: number?
used: number?
extra: string?
```

新增字段必须进入 `extra` 或版本化 schema，不直接破坏旧 extractor。

## 9. 三类联通检测

### 9.1 网站联通检测

只验证：DNS/TLS/HTTP 状态、代理、请求耗时和证书安全；不发送 LLM 消耗请求。

```text
POST /admin/api/v1/providers/{id}/probes/website
```

### 9.2 模型联通检测

优先调用模型列表或轻量模型 metadata 接口；如果供应商没有该接口，则使用最小请求并限制 Token。

```text
POST /admin/api/v1/models/{id}/probes/connectivity
```

### 9.3 模型对话联通检测

使用固定、可审计、低成本 Prompt：

```text
请只回复 CONNECTED
```

检测必须记录：模型、实际 model ID、耗时、HTTP 状态、Token、费用、响应 schema 和错误类型。默认不进入正常聊天历史，不触发记忆抽取，不触发外部工具。

## 10. 查询 API

### 10.1 余额

```text
GET /admin/api/v1/providers/{id}/balance/current
GET /admin/api/v1/providers/{id}/balance/history
POST /admin/api/v1/providers/{id}/balance/refresh
```

### 10.2 Token 和费用

```text
GET /admin/api/v1/usage/summary?window=24h&scope=all
GET /admin/api/v1/usage/summary?window=7d&scope=provider&provider_id=...
GET /admin/api/v1/usage/summary?window=30d&scope=model&model_id=...
GET /admin/api/v1/usage/summary?window=365d&scope=session&session_id=...
GET /admin/api/v1/usage/summary?window=all&scope=all
GET /admin/api/v1/usage/timeseries
GET /admin/api/v1/usage/breakdown
```

返回必须细分：

```text
prompt_tokens
cache_creation_tokens
cache_read_tokens
completion_tokens
total_tokens
input_cost
cache_creation_cost
cache_read_cost
output_cost
total_cost
currency
priced_calls
unpriced_calls
unknown_usage_calls
```

## 11. 告警

阈值范围支持：

```text
global / provider / model / session
```

阈值支持：

- 剩余额度低于阈值；
- 当日/周期费用超过阈值；
- 输入 Token 超过阈值；
- 缓存创建 Token 超过阈值；
- 缓存读取 Token 超过阈值；
- 输出 Token 超过阈值；
- 供应商或模型连续联通失败；
- 余额查询失效或凭据过期。

通知渠道：

- QQ；
- Telegram；
- Mail。

每个通知渠道独立配置目标、启用状态、冷却、重试、失败回退和审计记录。

## 12. 与 TailAdmin Vue 的关系

当前不实现 UI。后端完成以下 DTO 后，再接入 TailAdmin Vue：

- ProviderSummaryDTO；
- ModelSummaryDTO；
- ModelListDTO；
- ProbeResultDTO；
- BalanceSnapshotDTO；
- UsageSummaryDTO；
- UsageTimeseriesDTO；
- AlertPolicyDTO；
- CommandCatalogDTO；
- ExtractorStatusDTO。

UI 只负责：

- 供应商和模型增删改；
- 默认模型和菜单名；
- URL/请求地址配置；
- 模型列表刷新；
- 三类联通检测；
- 余额和 Token 图表；
- 预警策略；
- extractor 启用/禁用和测试。

## 13. 暂不实现和等待资料

以下内容等待用户提供提取器代码和脚本说明后再定稿：

1. 各站点实际余额 endpoint 和认证头；
2. `baseUrl` 是官网地址、API 根地址还是控制台地址；
3. `userId`/数字 UID 的来源与是否必需；
4. 不同站点余额单位和换算倍率；
5. NewAPI、TokenPlan、Sub2API、自建站的响应字段差异；
6. extractor 表达式是否允许跨字段计算；
7. “司法等级”的准确含义和映射方式；
8. 日志中“消耗进、首进总量”等字段的确切语义；
9. 哪些站点允许自动轮询，轮询频率和限流；
10. 网站密码与 API Token 是否由同一凭据引用管理。

## 14. 实施顺序

1. 盘点现有模型注册表、价格表、运行时 settings 和日志字段。
2. 建立 Provider/Model/Endpoint/Probe 的结构化后端模型。
3. 建立 URL resolver 和模型显示名/实际 ID 分离。
4. 建立 `LLMCallRecord`，把 Token/费用从日志文本迁移为结构化事实。
5. 建立 balance adapter 和受限 extractor 合同。
6. 完成网站、模型、模型对话三类联通检测。
7. 完成余额、Token、费用和告警 API。
8. 清理订阅旧实现和异步风险。
9. 补齐优先平台能力。
10. 最后引入 TailAdmin Vue UI。

## 15. 公网访问、无公网 IP 和中国大陆部署

### 15.1 结论

没有公网 IPv4/IPv6 不会阻止公网访问控制面，因为可以由本机主动建立出站长连接，再由中继端把请求转回本机。Cloudflare Tunnel 官方文档明确支持无公网 IP、无入站端口的 outbound-only tunnel；frp 官方文档则要求 `frps` 部署在具有公网 IP 的服务器上，内网机器运行 `frpc`。因此两者的部署前提不同：Cloudflare Tunnel 使用托管边缘网络，frp 需要自己的公网中继服务器。（参见 Cloudflare Tunnel 与 frp 官方文档）

但是“技术上可行”不等于“在中国大陆网络中必然稳定”。海外边缘节点、DNS、TLS、长连接和中继线路都必须通过实际网络验证，不能把 Cloudflare Tunnel 当作中国大陆可用性的保证。

### 15.2 推荐部署层次

```text
浏览器
  ↓ HTTPS
公网入口：国内/香港/其他可达中继
  ├── Nginx/Caddy/云负载均衡
  ├── TLS、限流、基础认证、请求体限制
  └── frps 或受控 Tunnel 服务
          ⇅ 出站长连接
本地 Windows 主机
  ├── Control Plane API 127.0.0.1:<control-port>
  ├── NoneBot Runtime
  └── Worker/数据库/凭据
```

优先顺序：

1. **公网中继 VPS + frp + Nginx/Caddy**：线路、域名、日志和访问控制最可控；需要一个可公网访问的中继节点。
2. **Cloudflare Tunnel**：不需要公网 IP和入站端口，但必须实测中国大陆访问、长连接稳定性和域名可达性；适合作为备选线路。
3. **现有 2Mbps 内网穿透**：可以承载控制面 API 和低频配置操作，但不适合大文件、图片批量、视频、音频、持续终端流和高频 SSE。

### 15.3 2Mbps 穿透限制下的流量策略

控制面必须默认启用：

- gzip/Brotli；
- 静态资源缓存；
- 列表分页；
- 日志只返回最近 N 行；
- 日志流按 2-5 秒合并后发送；
- 单连接输出上限；
- playground 默认非流式或低频分片；
- 大文件通过本地下载或单独受限任务，不通过控制面隧道转发；
- 图片/卡片只返回缩略图或本地任务状态；
- 轮询和余额查询在本地执行，浏览器读取缓存快照。

建议的第一版默认限制：

```text
control_api_response_max_bytes = 1 MiB
terminal_tail_lines = 200
terminal_stream_max_bytes_per_minute = 256 KiB
playground_concurrency = 1
file_upload_via_tunnel = false
file_task_max_bytes = 10 MiB
balance_poll_min_interval = 300 seconds
```

这些是默认值，不是不可修改的硬编码；UI/API 可在管理员授权后调整，但每次调整要记录审计。

### 15.4 公网安全要求

公网模式禁止直接把 NoneBot 8080 或任意调试端口暴露给互联网。只允许公开独立的 Control Plane 入口，并且：

- 反向代理设置可信代理列表；
- API 使用 HTTPS；
- 不接受未经认证的健康信息和配置详情；
- 登录失败限速和账户锁定；
- Token 只通过 Authorization header 或 HttpOnly Secure Cookie；
- 不把 Token 放在 URL；
- 密码使用 Argon2id/scrypt 等密码哈希；
- TOTP 使用 RFC 6238，生成标准 `otpauth` QR，Aegis 可通过标准 TOTP/HOTP 条目导入；（参见 RFC 6238 与 Aegis 标准 TOTP 导入说明）
- 高风险操作需要密码重新验证 + TOTP/设备确认；
- 设备、Session、Refresh Token 可单独撤销；
- 每个控制面操作写入审计；
- 反向代理和应用层都限制请求体、并发、超时和 WebSocket/SSE 数量。

## 16. 单一中央决策层和统一出口

### 16.1 强制架构

所有事件必须遵循：

```text
NoneBot Adapter / Scheduler / Worker Event
                ↓
        IngressNormalizer
                ↓
        CentralDecisionEngine
                ↓
            ActionPlan
       ┌────────┼─────────┐
       │        │         │
     SILENT   CHAT      PLUGIN
       │        │         │
       └────────┴─────────┘
                ↓
        Policy / Permission / Quota / Approval
                ↓
        CapabilityExecutor
                ↓
        UnifiedDeliveryGateway
                ↓
        Receipt + Audit + Diagnostics
```

中央决策层是唯一决定者，必须决定：

- 不回复；
- 走小模型自然语言回复；
- 走大模型自然语言回复；
- 走某个插件能力；
- 走网络搜索；
- 走文件分析；
- 走订阅推送；
- 走轻量规则反应；
- 阻断并返回安全提示；
- 延迟、排队或请求人工批准。

### 16.2 当前代码的迁移问题

当前 `plugins/bot_unified_runtime/__init__.py` 已有 `_cached_route_decision` 和多种 `on_message` matcher，但不同 handler 仍直接构造和执行 capability。后续不能继续增加平行 matcher。

迁移目标：

1. matcher 只负责接收事件和调用 `IngressNormalizer`；
2. 所有普通消息统一进入一个 `RuntimeIngress.handle_event()`；
3. 文件、邮件、戳一戳、订阅定时器等非普通文本事件也转换为统一 `RuntimeEvent`；
4. `CentralDecisionEngine.decide()` 返回不可变 `ActionPlan`；
5. 只有 `CapabilityExecutor` 可以调用能力；
6. 只有 `UnifiedDeliveryGateway` 可以向 QQ/Telegram/Mail/Console 发送；
7. 业务 capability 不得直接调用 `bot.send()`、`bot.call_api()` 或其他平台发送函数；
8. 所有结果先转为统一 `CapabilityResult`，再由策略层决定是否发送；
9. 所有发送必须产生统一 Receipt、Audit 和 Diagnostic；
10. 发生冲突时按 `ActionPlan` 的优先级、风险等级、幂等键和截止时间裁决。

### 16.3 能力注册合同

新功能只能注册描述和执行器，不再注册独立消息入口：

```text
CapabilityDescriptor
- capability_id
- trigger_intents
- event_types
- required_roles
- risk_level
- privacy_level
- dependencies
- cost_class
- can_run_in_group
- can_run_in_private
- supports_async
- handler
- renderer
- delivery_policy
```

中央路由按以下顺序选择：

```text
安全阻断
→ 管理员/系统控制
→ 明确命令
→ 文件/媒体/链接解析
→ 订阅/预警/主动事件
→ 轻量规则反应
→ 搜索/知识库/聊天
→ 静默
```

同一事件只能有一个最终 `ActionPlan`。诊断、日志、审计和回执可以旁路记录，但不能产生第二个回复。

### 16.4 冲突避免规则

- 每个事件有唯一 `event_id` 和 `dedupe_key`；
- 每个能力声明优先级、互斥组和终止策略；
- 一个事件进入 `SILENT`、`BLOCKED` 或已排队后，不再由低优先级 handler 改写；
- 同一目标同一时间只能有一个主动推送计划；
- capability 不直接读写其他 capability 的内部状态；
- 传输失败由统一发送层重试，不能让业务层自行再次发送；
- 所有系统事件都记录 decision trace，显示“为什么选择聊天/插件/静默”；
- 任何临时直发必须标记为基础设施异常通道，并禁止承载普通业务回复。

### 16.5 统一入口伪代码

```python
async def handle_event(event: RuntimeEvent) -> DeliveryReceipt:
    message = ingress_normalizer.normalize(event)
    decision = await central_decision_engine.decide(message)
    if decision.action is ActionKind.SILENT:
        return receipt_for_silent(message, decision)

    checked = await policy_engine.check(message, decision)
    if checked.blocked:
        return await delivery_gateway.deliver(checked.block_message)

    result = await capability_executor.execute(
        decision.capability_id,
        message,
        decision,
    )
    rendered = renderer.render(result)
    return await delivery_gateway.deliver(
        delivery_planner.plan(message, decision, rendered)
    )
```

这段伪代码是目标合同，不代表当前源码已经实现。实施时必须先写失败测试，证明当前平行入口会产生重复/冲突，再逐步迁移。

## 17. 协议、供应商身份和计费身份分离

同一个模型可能通过官方 API、API 中转站、自搭站点或聚合网关访问。不能只根据模型名称判断价格、协议或余额。建议把以下概念分开：

```text
provider_type: official / relay / self_hosted / aggregator
api_protocol: openai_chat / openai_responses / anthropic_messages / custom
upstream_vendor: 实际模型厂商，可为空
billing_owner: 实际扣费账户/中转站账户
endpoint_host: 实际访问域名
pricing_profile_id: 本地计费规则
balance_profile_id: 余额查询规则
usage_source: provider_response / local_log / provider_usage_api / extractor
```

### 17.1 OpenAI 和 A 社 Cloud 兼容

模型接口至少预留以下协议适配器：

```text
OpenAI Chat Completions
OpenAI Responses
A 社 Cloud/厂商专用协议
Anthropic Messages 类协议
Custom JSON HTTP
```

“API 根地址”是配置的核心语义。请求地址由根地址、协议和 operation resolver 生成，不要求用户手工填写完整的 `/chat/completions` 或 `/messages` 路径。

如果某个中转站对外提供 OpenAI-compatible 接口，即使底层实际转发到其他模型，也应记录：

```text
api_protocol = openai_chat
upstream_vendor = actual vendor if known
provider_type = relay
billing_owner = relay account
```

这样可以避免把“OpenAI 协议兼容”错误理解为“官方 OpenAI 计费”。

### 17.2 计费倍率、汇率和活动

余额显示和 API 实际花费需要分别记录：

```text
BalanceUnitProfile
- balance_currency
- display_currency
- balance_to_display_rate
- rate_source
- rate_effective_from
- rate_effective_to

RechargePromotion
- provider_id
- promotion_name
- paid_amount
- credited_amount
- effective_rate
- valid_from
- valid_to
- conditions

SubscriptionPlan
- plan_id
- provider_id
- plan_name
- plan_type: day/week/month/year/custom
- included_quota
- included_tokens if known
- overage_policy
- valid_from
- valid_to
- status

PricingProfile
- provider_id
- model_id
- input_price
- cache_creation_price
- cache_read_price
- output_price
- billing_multiplier
- currency
- formula_version
- effective_from
- effective_to
- source
```

例如“1 人民币对应 3 美元余额”不能直接写入模型单价，应写成余额单位换算规则；“充 1 美元只支付 0.6 人民币”应写入充值优惠，不能降低实际 Token 单价；月卡、日卡、周卡、年卡必须以套餐记录表达。

默认费用视图提供三种数值：

1. provider reported cost：供应商返回的费用；
2. local estimated cost：根据本地 Token 和价格表估算；
3. effective paid cost：结合充值折扣、套餐和汇率计算的有效成本。

三者不一致时必须显示差异和来源，不能静默覆盖。

### 17.3 官方规则与中转规则防混淆

每次调用记录必须同时带上：

```text
protocol_source: official / relay / self_hosted
pricing_source: provider / configured / inferred / unknown
usage_source: response / log / API / extractor
```

对于中转站：

- 中转站的模型名只用于请求路由，不代表官方模型注册；
- 中转站的余额单位只代表中转站账户，不代表官方账户；
- 中转站的倍率、折扣、套餐和限流规则优先于官方价格；
- 官方价格只作为参考基线，不得自动覆盖中转站价格；
- 如果没有明确价格来源，费用显示为 `unpriced` 或 `estimated`；
- 通过本地日志计算的 Token 只能说明本次请求发送/返回的 Token，不一定等于供应商账单 Token；
- 官方和中转站的调用必须在报表中分组展示。

## 18. NewAPI 专用余额适配器

用户提供的 extractor 应作为 NewAPI 专用适配器的输入合同，不直接作为通用所有站点模板。

### 18.1 NewAPI 请求合同

```text
GET {baseUrl}/api/user/self
Content-Type: application/json
Authorization: Bearer {accessToken}
User-Agent: cc-switch/1.0
New-Api-User: {userId}
```

其中：

- `baseUrl` 是 NewAPI 的 API 根地址；
- `accessToken` 是凭据引用，不保存明文；
- `userId` 是 NewAPI 必需的数字 UID；
- `New-Api-User` 只在 NewAPI adapter 中自动加入；
- 其他供应商不默认发送该请求头；
- `quota`、`used_quota` 的除数 `500000` 是 NewAPI 余额单位换算，不得应用到其他站点；
- `unit: USD` 需要视为站点返回/配置的显示单位，不能直接证明是官方美元价格。

建议标准化为：

```text
remaining = quota / configured_quota_scale
used = used_quota / configured_quota_scale
total = remaining + used
plan_name = data.group
```

`configured_quota_scale` 默认可填 `500000`，但必须是 NewAPI balance profile 的配置，不写死在全局计费器。

### 18.2 NewAPI 状态映射

```text
success=true and data present -> valid
success=false                -> provider_error or invalid
401/403                      -> auth_required
429                          -> rate_limited
5xx                          -> provider_error/retryable
missing quota fields        -> invalid_response
```

保存 `planName`、`remaining`、`used`、`total`、`unit` 和原始字段路径；不保存完整响应中的 Token、密码或 Cookie。

## 19. Extractor 规则

### 19.1 是否允许跨字段计算

允许，但分为两层：

1. 默认层：JSONPath/JMESPath 字段读取、加减乘除、条件表达式、单位换算；
2. 扩展层：受限 ES2020 extractor，只用于复杂条件和供应商特殊响应。

不能使用任意 Python `eval`、Node.js 进程对象、文件系统、网络、模块加载或动态 import。

### 19.2 可执行范围

Extractor 只能接收：

```text
response: 已解析 JSON 的只读副本
baseUrl: 已校验的根地址
userId: 非敏感 UID
credential proxy: 不可读取原文的认证代理
```

Extractor 只能返回 JSON 可序列化的结果：

```text
isValid
invalidMessage
remaining
unit
planName
total
used
extra
```

### 19.3 版本和回滚

每个 extractor 保存：

```text
extractor_id
provider_id
version
source_hash
enabled
created_by
approved_by
last_tested_at
last_test_result
```

修改 extractor 后先在沙箱测试响应样例，再允许上线；失败时保留上一版本，不覆盖可用 extractor。

## 20. 日志 Token 指标合同

用户明确要求的指标拆分如下：

```text
first_token_at                    首字/首个输出 Token 出现时间
first_token_latency_ms            首 Token 延迟
request_started_at
request_completed_at
total_latency_ms
prompt_tokens                     输入 Token 总量
cache_creation_tokens             缓存创建 Token
cache_read_tokens                 缓存读取 Token
completion_tokens                 输出 Token
total_tokens
prompt_cost
cache_creation_cost
cache_read_cost
completion_cost
total_cost
```

其中：

```text
total_latency_ms = completed_at - started_at
first_token_latency_ms = first_token_at - started_at
```

若上游没有流式响应或没有首 Token 时间，字段为 `unknown`，不使用总耗时伪造首 Token 延迟。

日志采集必须支持：

- 本项目统一结构化事件；
- OpenAI usage 字段；
- Responses usage 字段；
- Anthropic usage 字段映射；
- NewAPI/中转站 usage 字段；
- 自定义 extractor；
- 手工字段映射。

不同站点的“消耗客户数、消耗前用量、首进总量”等指标保存为 `provider_metric_name` 和 `metric_semantics`，不强行转换为 Token。

## 21. SakuraFrp 传输预算与低带宽控制

用户实际使用 SakuraFrp：每日流量额度 3GB，隧道带宽最高 10Mbps。该限制是本项目控制面的硬约束，不把 10Mbps 当作可以持续跑满的目标。

SakuraFrp 官方文档说明：穿透流量按 frpc 与节点之间的上行/下行计算，协议额外开销不计入账户扣费；实际速度还受本机上行带宽和节点共享负载影响；`bandwidth_limit` 的配置单位实际是 MiB/KiB 兼容单位，而不是普通十进制 Mbps。citeturn1search0turn1search1

### 21.1 硬预算

```text
sakurafrp.daily_traffic_budget_bytes = 3 * 1024 * 1024 * 1024
sakurafrp.tunnel_bandwidth_cap_mibps = 10
sakurafrp.control_plane_default_cap_mibps = 2
sakurafrp.warning_thresholds = 50%, 75%, 90%, 100%
```

`10Mbps` 在用户语义中表示 SakuraFrp 隧道最高带宽；实现时必须明确单位并统一为内部 bytes/sec，不能直接把 `10` 传入一个单位未知的底层配置。

建议实际运行配置：

- SakuraFrp 隧道配置带宽上限不高于 `10M`，并在 UI/API 显示实际单位为 `MiB/KiB` 兼容单位；
- Control Plane API 默认限速远低于隧道上限，建议初始 `2Mbps` 左右；
- 单个请求响应上限默认 1MiB；
- SSE/WebSocket 日志默认关闭或严格限速；
- 文件上传、文件下载、图片原图、视频、音频和批量导出默认不经过控制面隧道；
- 余额、用量、模型列表使用本地缓存快照，浏览器只读取增量变化；
- playground 默认非流式，流式输出采用合并分片并设每分钟预算；
- 接近 90% 日流量时自动关闭非必要刷新、图表高频轮询和日志流；
- 达到 100% 时只保留低流量健康检查、配置读取和本地 Bot 运行，禁止主动大数据传输。

### 21.2 流量计量

新增本地 `TunnelTrafficMeter`，不依赖 SakuraFrp 面板才能做保护：

```text
TunnelTrafficSample
- tunnel_id
- direction: ingress/egress
- bytes
- request_id
- endpoint
- content_type
- started_at
- completed_at
- source: proxy/access_log/app_counter
```

计量优先级：

1. 反向代理 access log 的请求/响应字节；
2. Control Plane middleware 的请求/响应字节；
3. SSE/WebSocket 分片累计字节；
4. 文件任务和 API 请求分开计量。

SakuraFrp 账户流量与本地 HTTP 字节数可能因封装、重试和协议差异不同，因此 UI 同时显示：

- 本地估算传输量；
- SakuraFrp 面板已使用量（管理员手工/接口同步）；
- 估算差异；
- 最后同步时间。

不能把本地估算值伪装成 SakuraFrp 账单精确值。

### 21.3 断路策略

传输预算状态机：

```text
NORMAL
  ↓ 50%
WATCH
  ↓ 75%
THROTTLED
  ↓ 90%
EMERGENCY
  ↓ 100%
BLOCK_NONESSENTIAL
```

各状态行为：

- `NORMAL`：允许正常控制面读取和低频 playground。
- `WATCH`：提高审计频率，禁止自动刷新间隔低于 30 秒。
- `THROTTLED`：禁止日志流和大响应，模型列表/余额刷新改为手动。
- `EMERGENCY`：只保留健康检查、配置摘要、告警和管理员操作。
- `BLOCK_NONESSENTIAL`：拒绝文件传输、图表大查询、连续日志、原图和流式回答。

断路器必须只影响穿透控制面，不影响本地 Bot 在内网中的正常运行。

### 21.4 SakuraFrp 配置建议

SakuraFrp 文档提供 `bandwidth_limit` 配置，并明确其单位是兼容上游的 MB/KB、实际为 MiB/KiB；因此本项目不能只保存一个模糊的 `10Mbps` 字符串，应同时保存：

```text
user_declared_bandwidth_mbps = 10
sakurafrp_bandwidth_limit = "10M"
internal_bandwidth_bytes_per_second = resolved value
unit_source = sakurafrp_config
```

如果需要更保守，建议 SakuraFrp 配置上限低于 10M，把剩余空间留给协议、节点波动和其他内网流量。不要启用已弃用的 XTCP 作为主要方案；SakuraFrp 文档说明其在复杂国内 NAT 环境下打洞成功率低，且该功能已弃用。citeturn1search9

### 21.5 管理面设计原则

在 2Mbps-10Mbps、3GB/日条件下，TailAdmin Vue 后续只能展示聚合数据和缓存快照：

- 不默认自动播放实时日志；
- 不在首页加载大图表全量数据；
- 不让浏览器轮询每个 provider；
- 不通过隧道代理外部模型正文流量；
- 不上传文件到公网控制面；
- 对每个高流量操作显示预计流量和确认框；
- 对图表使用服务端聚合、分页和时间桶；
- 控制面和 Bot 业务流量分开计量、分开限额。
