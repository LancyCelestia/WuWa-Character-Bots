# B4 设计规格：Control Plane API（/admin/api/v1）+ SakuraFrp 公网接入

> 状态：设计规格（本轮不含实现代码），目标读者为下一实施会话。
> 上游裁决文档：
> - `docs/project-audit-and-modernization-roadmap-2026-09-05.md`（已归档至 `ChatBot_Archive/2026-09-12/docs-archive-2026-09-12.zip`，关键节 §7/§8/§9 阶段 2/§12/§14/§16/§17）
> - `docs/control-plane-provider-and-usage-requirements-2026-09-05.md`（工作区内，§10/§15/§21 为本文直接输入）
> 日期：2026-09-12。现状断言均经 grep 核实（标注文件与行号区间）；无法核实处标注 unknown。

---

## 1. 裁决对齐（不可妥协项）

| 裁决 | 来源 | 本文落实 |
|---|---|---|
| API 先行、TailAdmin Vue UI 最后 | roadmap §12、§14.11、§17.1 | 本文只定义 API 与传输层；UI 不在范围，本文 DTO 是未来 UI 的唯一消费面 |
| UI/API 只消费稳定契约，不直接读写 `.env`、SQLite 或 Python 全局对象 | roadmap §8.1.2、§17.1 | 所有配置读写经 service 层，写侧复用 `RuntimeSettingsStore` 白名单机制 |
| Bot Runtime 与控制面分离：聊天/解析/订阅不依赖 Web UI | roadmap §8.1.1 | 控制面为只读挂载 + 白名单写动作，整体默认关闭（`BOT_CONTROL_PLANE_ENABLED=false`） |
| 凭据永不回传明文，只回 `credential_state` / `key_fingerprint` | roadmap §8.3 末段、需求文档 §7 | §8.3 掩码规则 |
| 公网必须分层：TLS/反代 → 认证限流 → API → Runtime | roadmap §17.2 | §9 SakuraFrp 专节 |
| 公网不接受未认证健康信息；禁把 NoneBot webhook 端口直接暴露 | 需求文档 §15.4 | §6.1 认证范围、§9.3 隔离端口 |

## 2. 现状基线（全部 grep 核实）

| 事实 | 证据位置 |
|---|---|
| 项目无任何自定义 HTTP API / Web 路由；唯一 HTML 是卡片渲染模板 | roadmap §6（审计结论，与本次源码盘点一致：`plugins/bot_unified_runtime/output/card_render/templates/` 下无服务路由） |
| FastAPI 已随依赖可用：`nonebot2[fastapi]>=2.5.0` | `pyproject.toml:8` |
| NoneBot driver 挂载 OneBot V11 / Telegram / Mail 三适配器 | `bot.py:176,177,197` |
| 配置写侧已有命令级实现：`RuntimeSettingsStore` 白名单 `SETTABLE_KEYS`（约 60 键），落盘 `data/runtime_settings.json`（`BOT_RUNTIME_SETTINGS_FILE`），转换失败即拒绝写入 | `plugins/bot_unified_runtime/runtime/settings.py:338-411`（白名单表）、`:418`（类定义）、`:605 set_override` |
| 模型/渠道状态：`ChannelHealthStore` SQLite（`model_id, state ok|unavailable, consecutive_fails, latency_ms, last_error, last_ok_at`），连续失败达阈值转 `unavailable`，提供 `snapshot/is_available/unavailable_ids/latencies` | `llm/channel_health.py:51-250` |
| 渠道注册表：`Config.bot_model_registry`（dict，env JSON 容错解析）、`ModelSpec`（含 `api_key/api_keys` 支持 `env:VAR` 引用） | `config.py:627`；`llm/model_router.py:281-345`（`_resolve_api_key` 支持 `env:` 前缀） |
| 发送队列：SQLite `send_requests` + `send_request_parts`（`state TEXT`，`'partial'` 为非 ReceiptState 的内部态），接口含 `submit/claim_due/mark_sent/mark_retryable_failure/mark_final_failure`，退避 `retry_base_seconds=30 / retry_max_seconds=300 / max_attempts` | `sender/queue.py:30,239-248,1344,1394,1538` |
| 发送回执落库：`delivery_receipts` 表 | `sender/receipts.py:262` |
| 订阅状态：V2 store SQLite，默认 `data/subscriptions.sqlite3` | `sources/subscription_store_v2.py:60,68` |
| 用量/费用：文本日志聚合（见 B5 文档 §2）；阈值巡检 60 秒 + 13/18/23 点报告；阈值默认输出 5M / 输入 50M token / 日费 10 元；报告状态 `data/usage_report_state.json` | `runtime/usage_monitor.py:240-291`；`.env.example:181-182` |
| 运行事件日志：单文件纯文本 `data/runtime_events.log`（`BOT_RUNTIME_LOG_FILE`），默认 2MB 轮转保留 `.old` 一代 | `sources/runtime_event_log.py:5-10,57-62` |
| 诊断表：`runtime_diagnostics`（SQLite，保留约 100 条），含 llm_status/llm_provider/llm_model/llm_error_kind/基础 token 三项，无费用/耗时/attempts | `diagnostics.py:60-76,121-127` |
| 脱敏：`redact_private_debug()` 四段正则（key=value 秘密、`Authorization: Bearer`、裸 Bearer、`sk-` 密钥）→ `[redacted]` | `audit/logger.py:38-53` |
| 审计仓库：内存有界版（FIFO 1000，`bot_audit_max_items` 对齐）+ 持久版 | `audit/logger.py:56-80` |
| SakuraFrp 前期调研：3GB/日 流量额度、10Mbps 隧道带宽上限、`bandwidth_limit` 单位为 MiB/KiB 兼容单位、XTCP 已弃用 | 需求文档 §21（用户确认口径） |

明确**不存在**的东西（避免实施会话误假设）：无 FastAPI 路由、无鉴权中间件、无 token 存储、无隧道流量计量、无公网域名/证书管理代码。

## 3. 总体架构

### 3.1 模块布局

按 roadmap §8.2 收敛为最小可用形态（阶段 2 口径：状态 + 安全子集配置 + 运维动作；Provider/Model CRUD 全量管理与盲测不在本阶段）：

```text
plugins/bot_unified_runtime/control_plane/
├── __init__.py            # create_control_plane_app() -> FastAPI；总开关与挂载
├── auth.py                # Bearer token 校验、失败限速、审计钩子
├── audit.py               # 控制面操作审计（复用 audit 仓库与 redact_private_debug）
├── services/
│   ├── status_service.py  # 聚合 bot/模型健康/队列/订阅/Usage 只读视图
│   ├── config_service.py  # RuntimeSettingsStore 白名单读写 + registry 只读投影
│   └── ops_service.py     # 重探/清缓存/队列重试等白名单动作
├── api/
│   ├── health.py          # /admin/api/v1/health, /status/*
│   ├── config.py          # /config/*
│   ├── ops.py             # /ops/*
│   ├── usage.py           # /usage/*（挂 B5 聚合，见 llm-billing-ledger.md）
│   └── tunnel.py          # /tunnel/*（流量计量与断路器状态）
└── tunnel_meter.py        # TunnelTrafficMeter + 断路器状态机（§9.5）
```

规则：

1. `services/` 不 import NoneBot Event/matcher；通过构造注入既有单例（channel_health store、SendQueue、RuntimeEventLog、B5 LedgerService、RuntimeSettingsStore）。
2. `api/` 只做参数校验、DTO 序列化、错误码映射；无业务逻辑。
3. 与 `/bot runtime set` 命令共享同一个 `RuntimeSettingsStore`——命令与 API 修改同一份状态（roadmap §9 阶段 2.6 的同源原则）。

### 3.2 挂载与端口

**裁决：控制面使用独立 uvicorn 监听，默认 `127.0.0.1:8742`，不复用 NoneBot webhook 端口。**

理由：

1. 公网穿透（frpc）只转发这一个端口，天然与 NoneBot webhook 端口隔离（需求文档 §15.4 明令禁止暴露 webhook 端口）；
2. 断路器/限速/审计中间件可独立于聊天链路演化；
3. 隧道摘除、重启控制面不影响 bot 正常收发。

配置键（新增，全部默认关闭/环回）：

```text
BOT_CONTROL_PLANE_ENABLED=false          # 总开关，默认关
BOT_CONTROL_PLANE_HOST=127.0.0.1         # 只允许 127.0.0.1/::1；改公网绑定必须在配置目录放显式确认文件（见 §9.7）
BOT_CONTROL_PLANE_PORT=8742              # 避开 8080（webhook）与 8765（BOT_GSCORE_PORT，.env.example:406）
BOT_CONTROL_PLANE_TOKEN_SHA256=          # 见 §5.1；为空则 API 除 /healthz 外一律 503
```

实现方式：NoneBot `on_startup` 中以 `asyncio.create_task` 启动独立 `uvicorn.Server(ServerConfig(app, host, port))`（uvicorn 随 `nonebot2[fastapi]` extras 安装，pyproject.toml:8 已含）；`on_shutdown` 优雅停止。不与 driver 共享事件循环之外的线程。

## 4. 协议与通用约定

- REST + JSON（UTF-8）；`Content-Type: application/json`。
- 基路径 `/admin/api/v1`；本地无鉴权探针 `/healthz`（仅回 `{"ok":true}`，不回任何配置/版本细节）。
- 时间统一 ISO 8601 本地时区（与 RuntimeEventLog 现状一致）；费用单位毫厘（1 元 = 1000 毫厘，沿用 `runtime/pricing.py:52` 口径）。
- 分页：`limit`（默认 50，上限 200）+ `offset`；响应体上限默认 1 MiB（超限截断并带 `truncated: true`）。
- 错误体（对齐 roadmap §7.3：不回 `str(exc)`）：

```json
{ "error": { "code": "config_value_invalid", "debug_id": "cp-20260912-ab12cd34", "message": "白名单键转换失败：BOT_CHAT_TEMPERATURE" } }
```

完整异常只进控制面审计日志，绑定 `debug_id`。

## 5. 认证规格（阶段 1 形态）

### 5.1 Bearer Token

- 管理员生成 32 字节随机 token（`secrets.token_urlsafe(32)`），配置中只存 SHA-256（`BOT_CONTROL_PLANE_TOKEN_SHA256`）；明文只在生成时展示一次。
- 请求头 `Authorization: Bearer <token>`；Token 不允许出现在 URL/query（需求文档 §15.4）。
- 中间件顺序：`auth → rate_limit → body_limit → route`；除 `/healthz` 外全部 `/admin/api/v1/*` 需认证（公网模式下 `/healthz` 也只返回常量 ok，无信息量，满足"不接受未认证健康信息"的同时保留探活）。
- 恒定时间比较（`hmac.compare_digest`）；失败限速：同一来源 60 秒内 5 次失败 → 返回 429 并审计（来源记录到 /32 与 /128 掩码粒度）。
- `TOKEN_SHA256` 为空：`/healthz` 正常，其余端点一律 503 `control_plane_not_provisioned`（防止"忘了配 token 就裸奔"）。

### 5.2 未来可插拔（只留接口，不实现）

roadmap §17.2 要求支持密码/TOTP/设备配对/反代认证头/OIDC 与角色。阶段 1 的 `auth.py` 暴露 `Authenticator` Protocol（`async def authenticate(request) -> Principal | None`，`Principal{subject, roles}`），Bearer 实现为该协议的第一个实现；角色字段先固定 `admin`。CSRF 只在引入 Cookie 会话时才需要，Bearer header 形态不需要。

## 6. Endpoint 清单

### 6.1 健康与状态（只读）

| Method | Path | 说明 | 数据源（已存在，注入） |
|---|---|---|---|
| GET | `/healthz` | 本地存活探针，无鉴权无信息 | — |
| GET | `/admin/api/v1/health` | 进程内组件健康：driver 状态、各 store 可达性、scheduler 活性 | 注入单例的 `ping()` |
| GET | `/admin/api/v1/status/bot` | bot 概览：启动时间、适配器连接态、persona、默认模型、runtime settings 摘要 | config + settings store |
| GET | `/admin/api/v1/status/models` | 渠道健康快照数组：`model_id, state(ok/unavailable), consecutive_fails, latency_ms, last_error(脱敏), last_ok_at`；绝不包含 api_key/base_url 凭据段 | `ChannelHealthStore.snapshot()/latencies()`（channel_health.py:97-125,239） |
| GET | `/admin/api/v1/status/queue` | 发送队列：各 state 计数、最老待处理行年龄、`max_attempts/retry_base_seconds` 配置回显 | `sender/queue.py` 计数查询（state 枚举以 queue.py 为准，'partial' 投影为 `failed_final`，见 queue.py:1538 注释口径） |
| GET | `/admin/api/v1/status/subscriptions` | 订阅 V2 概览：目标数、按平台分组计数、调度器下次运行时间 | `subscription_store_v2`（只读连接）；详细 schema 标注 unknown，实施时以 store 实际表为准 |
| GET | `/admin/api/v1/status/diagnostics?limit=` | 最近 N 条运行诊断（runtime_diagnostics 投影，天然无正文） | `diagnostics.py` |

`status/models` 响应示例：

```json
{ "items": [ { "model_id": "qian-night-gemini", "state": "ok", "consecutive_fails": 0,
  "latency_ms": 812, "last_error": "", "last_ok_at": "2026-09-12T10:03:11+08:00" } ],
  "generated_at": "2026-09-12T10:05:00+08:00" }
```

### 6.2 Usage 查询（挂 B5）

| Method | Path | 说明 |
|---|---|---|
| GET | `/admin/api/v1/usage/summary?window=24h\|7d\|30d\|365d\|all&scope=all\|model\|session&model_id=&session_id=` | 汇总：prompt/completion/cache_read/cache_write tokens、cost_milli、calls、unpriced_calls |
| GET | `/admin/api/v1/usage/by-model?window=` | 按渠道/模型分组 |
| GET | `/admin/api/v1/usage/timeseries?window=&bucket=hour\|day` | 时间序列（服务端分桶，供未来图表） |

实现直接调用 B5 `LedgerService.aggregate()`（`docs/design/llm-billing-ledger.md` §5）。**兼容层**：B5 表未建成/为空时，`usage_service` 回退 `RuntimeEventLog.aggregate_llm_usage_range()` 并在响应带 `"source": "text_log_fallback"`，UI/脚本可见数据口径。

### 6.3 配置读写（安全子集）

| Method | Path | 说明 |
|---|---|---|
| GET | `/admin/api/v1/config/settings` | 白名单全量键 + 当前生效值（store 覆盖值与 Config 默认值分别回显：`{key, override, effective, secret}`） |
| GET | `/admin/api/v1/config/settings/{key}` | 单键读取；非白名单键 404（不泄露键存在性差异——统一 404） |
| PUT | `/admin/api/v1/config/settings/{key}` | 写覆盖；服务端执行与 `set_override` 相同的 converter，失败 422 + `debug_id` |
| DELETE | `/admin/api/v1/config/settings/{key}` | 删除覆盖，回退 Config 默认 |
| GET | `/admin/api/v1/config/models` | 渠道注册表**只读投影**（阶段 1 不提供写 API，见 §10 阶段边界） |

写侧规则：

1. 可写键集合 = `runtime/settings.py SETTABLE_KEYS`（settings.py:338-411），API 侧不再自行新增键——白名单只有一处真相；
2. 每次写操作前先在审计里记录 `key, value_hash(sha256 前 12 位), 操作者=token subject`，值本身不落审计（值可能含群号等半敏感信息）；
3. 禁止写 `.env`：API 只操作 runtime store 覆盖层（对齐 roadmap §9 阶段 2.2 "`.env` 为只读启动种子"）。

`config/models` 只读投影示例（掩码规则见 §8.3）：

```json
{ "items": [ { "model_id": "qian-night-gemini", "model": "gemini-x", "base_url_host": "api.example.com",
  "priority": 100, "group": "", "effort": "", "price_in": 2.0, "price_out": 8.0,
  "credential_state": "set", "key_fingerprint": "sha256:9f2a…", "tags": ["fast"] } ] }
```

### 6.4 运维动作（白名单 POST，全部幂等或带确认参数）

| Method | Path | 说明 | 现有可复用机制 |
|---|---|---|---|
| POST | `/admin/api/v1/ops/models/reprobe` | 对全部或指定 `model_id` 重新健康探测：清 `consecutive_fails` 并发起轻量连通检查（复用渠道探测逻辑；`ModelSpec` 全候选遍历）。响应回每渠道新 state | `channel_health.record_success/record_failure`（channel_health.py:152,186） |
| POST | `/admin/api/v1/ops/models/{model_id}/unblock` | 将 `unavailable` 渠道手动复位为 `ok`（计数清零） | `channel_health` 同上 |
| POST | `/admin/api/v1/ops/cache/clear?scope=prompt_preview\|video_pipeline\|card` | **枚举白名单**缓存清理；未知 scope 422。不提供"清全部" | 各缓存模块暴露的现有清理入口（实施时逐一接线；无入口的 scope 先不注册） |
| POST | `/admin/api/v1/ops/queue/{request_id}/retry` | 单条终态失败请求重新入队（`mark_retryable_failure` 语义 + retry_count 归零） | `sender/queue.py mark_*` 接口（queue.py:239-248 附近） |
| POST | `/admin/api/v1/ops/queue/retry-failed` | 批量重试终态失败行；body 需 `{"confirm": true}`；单次上限 50 条 | 同上 |
| POST | `/admin/api/v1/ops/usage/report` | 立即触发一次用量报告（等价 13/18/23 点任务手动执行） | `usage_monitor` 报告函数（usage_monitor.py:253 起注册的内闭包，需抽出具名函数供两处复用） |
| POST | `/admin/api/v1/ops/tunnel/reset` | 断路器状态复位到 NORMAL（仅本地来源允许，见 §9.5） | tunnel_meter |

运维动作硬规则：

- 一律 POST，不缓存、不幂等重放保护则必须带 `confirm`；
- 不暴露任意命令执行/文件操作/CMD 控制台（roadmap §12 明令）；
- 每个动作写控制面审计（§8.5）。

### 6.5 审计与隧道

| Method | Path | 说明 |
|---|---|---|
| GET | `/admin/api/v1/audit/control-plane?limit=` | 控制面操作审计流（含隧道状态迁移） |
| GET | `/admin/api/v1/tunnel/status` | 断路器状态、今日流量估算（本地计）、配额 3GB、阈值 50/75/90/100% 消耗比、frpc 进程活性（本机进程探测） |
| GET | `/admin/api/v1/tunnel/traffic?window=` | `TunnelTrafficSample` 聚合（按小时桶） |

## 7. 传输层中间件（顺序即链）

1. `AccessLog` → tunnel_meter（请求/响应字节计量，§9.5）；
2. `BodyLimit`：请求体上限 256 KiB（运维动作足够）；
3. `Auth`（§5）；
4. `RateLimit`：全局 60 req/min、写端点 10 req/min、usage 查询 30 req/min；超限 429 + `Retry-After`；
5. `ResponseCap`：响应序列化后 > 1 MiB 则截断大数组字段（保留 `truncated` 标记）；
6. `ErrorHandler`：统一错误体（§4），`except Exception` 只落审计 + debug_id。

## 8. 安全边界专节

### 8.1 防本机内容外泄（沿用 plain_text redact 思路）

现状核心机制：事件日志只写"安全短文本"，docstring 明令禁止正文/密钥/原始异常（`__init__.py:962`）；`redact_private_debug()` 在入库前对秘密模式打码（audit/logger.py:38-53）。控制面沿用并收紧：

1. **DTO 白名单制**：每个响应模型逐字段声明；任何 endpoint 不得出现 `plain_text`、`text_fallback`、消息正文、知识库原文、记忆 facts、聊天历史字段。status/audit 类端点只能投影请求 id、状态枚举、计数字段；
2. `status/diagnostics` 投影 `runtime_diagnostics` 时剔除 `audit_tags` 中带正文风险的自由文本标签，只保留 `model:`/`llm_error:`/`llm_usage_*:`/`llm_route_attempt:` 前缀标签（标签前缀语义见 `__init__.py:998-1026`）；
3. 错误响应永不回 `str(exc)`（roadmap §7.3）；审计私有字段入库前一律过 `redact_private_debug()`；
4. 日志类查询（如未来接入 RuntimeEventLog.read_recent）默认关闭——文本日志虽已脱敏，但为防编排失误外泄，阶段 1 不开放 log tail endpoint（列入 §10 阶段 4 再评）。

### 8.2 绑定与公网

- 默认仅 `127.0.0.1`；frpc 也运行在本机，隧道侧流量对控制面而言仍来自 loopback——因此"是否公网"由 §9.5 断路器配置态决定，而非源地址判断；
- 拒绝 `Host` 头不在白名单（`127.0.0.1:8742`、未来公网域名）的请求（防 DNS rebinding）。

### 8.3 凭据掩码规则（硬约束）

| 输入 | API 输出 |
|---|---|
| `ModelSpec.api_key/api_keys`（含 `env:VAR` 引用，model_router.py:316-345） | `credential_state: "set"|"missing"`；`key_fingerprint: "sha256:" + 前 12 位十六进制`；`credential_ref`（`env:VAR` 时的变量名——变量名不敏感，值敏感） |
| base_url | 只回 host 部分（`base_url_host`），path/query 丢弃（可能内嵌 token 的 URL 视为污染） |
| Cookie/平台凭据（`data/platform_cookies.txt` 等） | 阶段 1 不建任何读取端点 |
| 任何配置值 | `secret: true` 标记的键（如含 TOKEN/KEY/COOKIE 字样的白名单键）只回掩码 `***` + fingerprint |

### 8.4 请求安全汇总

HTTPS 由隧道出口终止（§9.2）；Token 只走 Authorization header；登录失败限速（§5.1）；写动作二次确认参数；请求体/响应体双限值；每操作审计。

### 8.5 控制面审计记录

新增表 `control_plane_audit`（可与 B5 ledger 同库或独立 `data/control_plane.sqlite3`，推荐同库不同表，减少连接数）：

```sql
CREATE TABLE IF NOT EXISTS control_plane_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,                -- ISO8601 本地时区
    subject TEXT NOT NULL,           -- token subject（阶段1固定 'bearer-admin'）
    source TEXT NOT NULL,            -- 'local' | 'tunnel'
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    query TEXT NOT NULL DEFAULT '',  -- 已脱敏：剔除 token/secret 参数值
    status_code INTEGER NOT NULL,
    bytes_out INTEGER NOT NULL DEFAULT 0,
    debug_id TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''  -- redact_private_debug 后的短文本
);
CREATE INDEX idx_cp_audit_ts ON control_plane_audit (ts);
```

## 9. SakuraFrp 公网规格

### 9.1 硬预算（用户确认口径，需求文档 §21.1）

```text
sakurafrp.daily_traffic_budget_bytes = 3 GiB (3 * 1024^3)
sakurafrp.tunnel_bandwidth_cap = 用户声明 10Mbps；SakuraFrp band_width_limit 配置单位实为 MiB/KiB 兼容单位
control_plane_default_cap = 2 Mbps（控制面自限，低于隧道上限，留给协议开销与波动）
warning_thresholds = 50% / 75% / 90% / 100%
```

单位纪律：配置里同时保存 `user_declared_bandwidth_mbps=10` 与内部 `bytes_per_second`（换算值），不把裸 `10` 直接传给单位未知的底层配置（需求文档 §21.4）。

### 9.2 部署形态

```text
浏览器/客户端 --HTTPS--> SakuraFrp 节点（TLS 终止、域名）
        --frp 隧道（本机 frpc 出站长连接）--> 本机 frpc
        --> 127.0.0.1:8742  Control Plane API（auth → rate_limit → …）
        --> Bot Runtime / stores
```

- frpc 仅做转发，不做认证；**认证前置**由 §5 中间件保证：任何业务字节返回之前完成 token 校验；
- frpc 进程与配置文件放源码树外（Runtime 数据区），仓库内只留文档与配置模板；
- 不启用 XTCP（官方已弃用，复杂 NAT 下打洞成功率低，需求文档 §21.4）；
- 如未来启用 frps 侧 token/OP，本设计不变（认证仍双保险）。

### 9.3 上游不可用自动摘除（断路器之一）

两层摘除：

1. **frpc 层**：SakuraFrp 隧道配置启用对 `127.0.0.1:8742` 的健康检查（frp `health check` 语义），控制面进程停止时节点自动摘除该隧道，避免节点侧 502 黑洞与无效流量计费；
2. **应用层**：控制面启动时与运行中探测 frpc：对本机 frpc 的管理端口/进程存在性做轻量检查（实施时按 frpc 实际版本确定探测手段——unknown，实施会话需实测）；连续 3 次失败 → 标记 `tunnel_down`，`/tunnel/status` 如实呈现，并向管理员 QQ 发一次性告警（复用 usage_monitor 的管理员告警通道，usage_monitor.py:294 `_dispatch`）。应用层**不**主动停 frpc 进程（避免误杀共享隧道），只做状态呈报与限流联动。

### 9.4 流量策略（默认值，管理员可调，每次调整进审计）

| 项 | 默认 |
|---|---|
| 响应体上限 | 1 MiB |
| 日志类端点 | 阶段 1 不开放（§8.1.4） |
| SSE/WebSocket | 不提供 |
| 文件上传（经隧道） | 禁止 |
| usage timeseries | 服务端分桶 + limit≤200 点 |
| balance/模型列表刷新 | 本地定时器执行，API 只读缓存快照 |

### 9.5 流量计量与断路状态机（需求文档 §21.2/§21.3 落地）

`control_plane/tunnel_meter.py`：

```sql
CREATE TABLE IF NOT EXISTS tunnel_traffic_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('ingress','egress')),
    bytes INTEGER NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'app_counter'   -- app_counter | access_log
);
CREATE INDEX idx_tunnel_ts ON tunnel_traffic_samples (ts);
```

当日窗口（本地日界）累计后驱动状态机：

```text
NORMAL →(≥50%) WATCH →(≥75%) THROTTLED →(≥90%) EMERGENCY →(100%) BLOCK_NONESSENTIAL
```

| 状态 | 行为 |
|---|---|
| NORMAL | 正常 |
| WATCH | usage/timeseries 与 by-model 响应减半（bucket 变粗），审计加频 |
| THROTTLED | 禁用 timeseries 与 status/subscriptions 大响应；仅 summary 与 status/bot/models |
| EMERGENCY | 仅 health、tunnel/status、ops/tunnel/reset、usage/summary(24h) |
| BLOCK_NONESSENTIAL | 上述之外全部 503 `tunnel_budget_exhausted`；本地 Bot 收发不受影响 |

状态迁移写 `control_plane_audit`，并按 §9.3.2 通道通知管理员。`ops/tunnel/reset` 允许管理员在确认 SakuraFrp 面板余量后复位（次日自动归零）。

### 9.6 计量口径诚实性

本地 HTTP 字节 ≠ SakuraFrp 账单字节（封装/重试/协议差异）。`/tunnel/status` 同时回 `local_estimate_bytes` 与 `panel_reported_bytes`（管理员手动同步字段，存 runtime settings），并显示差异与最后同步时间；不得把本地估算伪装成账单精确值（需求文档 §21.2）。

### 9.7 公网显式开启开关

当且仅当 `BOT_CONTROL_PLANE_HOST` 非 loopback 时，要求配置目录存在 `control_plane_public.confirmed` 确认文件（内容含确认日期），否则启动失败——防止一次误改配置就把控制面绑到 0.0.0.0。默认部署形态下公网只经 frpc，host 保持 loopback，此文件不存在。

## 10. 分阶段交付与回滚

| 阶段 | 内容 | 验收 | 回滚 |
|---|---|---|---|
| M1 API 骨架 | control_plane 包、auth、审计表、`/healthz`+`/health`、独立 uvicorn 挂载、总开关 | token 缺失时 503；错误体合规；lint/test 通过 | `BOT_CONTROL_PLANE_ENABLED=false`（默认即关）；删除包目录无残留引用 |
| M2 状态面 | §6.1 全部只读端点 + §6.2 usage（含文本聚合 fallback） | 与 QQ 侧 `/bot status`/用量报告数字对拍一致 | 关开关即整体摘除；只读端点无状态副作用 |
| M3 配置面 | §6.3 settings 白名单读写、registry 只读投影 | API 写入与 `/bot runtime set` 效果一致（同一 store）；掩码合规（无任何明文键值外泄的自动化断言测试） | 删除 override 走 DELETE 端点或清 runtime_settings.json；`.env` 全程未被写 |
| M4 运维动作 | §6.4 全部 POST | 重探/重试/清缓存实测生效且审计留痕 | 动作均为幂等或 confirm 保护；无独立回滚需求 |
| M5 公网穿透 | frpc 配置、tunnel_meter、断路器、/tunnel/* | 断路器各状态行为按 §9.5 表现；frpc 健康检查摘除实测 | 停 frpc + 关 tunnel 开关；应用层断路器随 `BOT_CONTROL_PLANE_ENABLED=false` 一并停用 |
| M6（不在本文） | TailAdmin Vue UI | — | UI 仅消费本契约；UI 故障不影响 API（roadmap §17.1） |

依赖关系：M2 的 usage 端点建议等 B5 ledger M1 落地后切正式数据源（否则长期跑 fallback）。M5 依赖 M1-M3 稳定。UI 永远最后（裁决）。

## 11. 测试要求

- pytest：auth（缺 token/错 token/限速）、掩码断言（对全部响应模型做"无 api_key/cookie/plain_text 字样"扫描测试）、settings PUT 合法/非法值、断路器状态机（注入字节数驱动迁移）、错误体格式。
- 实测：dev.ps1 `test`/`lint`/`runtime-layout` 三任务通过（工作区 AGENTS.md 规定入口）。
- 手工：`curl` 全端点冒烟（本地）；frpc 转发后经公网域名全端点冒烟 + 流量计数与 SakuraFrp 面板粗对拍。

## 12. 开放问题

1. frpc 健康探测手段（管理端口版本差异）——unknown，实施时按实际 frpc 版本定（§9.3.2）。
2. 订阅 V2 store 的表结构投影字段——unknown，M2 实施时读 `subscription_store_v2.py` 实际 schema 定 DTO。
3. `ops/cache/clear` 各 scope 的现有清理入口完整度——需逐缓存模块核实（部分模块可能无清理函数，先不注册）。
4. usage 文本聚合 fallback 与 B5 正式数据源并存的周期长短（决定 fallback 是否带告警标记）。
5. 公网域名与 SakuraFrp 节点选择（国内/香港线路实测），属部署决策非本设计。
6. 反代认证头/TOTP 等认证方式接入时序（roadmap §17.2 完整矩阵），阶段 1 不决。
