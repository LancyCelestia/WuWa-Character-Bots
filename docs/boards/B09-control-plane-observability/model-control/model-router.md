# 模型路由与账本 · 优先级组与失败转移

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.model-control · 优先级组与失败转移

- 层级：一级 B09 → 二级 model-control → 三级 `model-router`
- 实现落点：`plugins/bot_unified_runtime/llm`、`plugins/bot_unified_runtime/domains/chat_reply/llm_engine`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定「这句话交给哪个模型、走哪条渠道、失败了换谁」。它把 provider/channel/model 三级
注册表变成一次有序候选链：规则自动选型（不烧钱做智能）、管理员手动指定最优先、时段
分组其次、优先级与渠道健康再其次；每次调用共用一个总预算，逐跳失败转移，全程可观测。
真身 `domains/chat_reply/llm_engine/model_router.py`（旧路径 `llm/model_router.py` 是
再导出垫片）。

## 怎么调用

- **注册表**：`BOT_MODEL_REGISTRY` 条目含 `id/model/base_url/api_key/group/tags/priority`
  （priority 越小越先选）；`api_key` 支持 `env:变量名` 引用与列表多密钥故障转移。运行时
  设置文件（Runtime `data/settings/` 实例件）合并出的注册表**覆盖优先于 `.env` 同名条目**，
  动态刷新在 `ModelRouter._refresh_dynamic_registry`，合并期按身份排除「同模型同端点」的
  重复兜底渠道。
- **思考强度（effort）**：档位即渠道 tags（各家族档位集合以该件常量为准）；请求时取
  条目 `effort` > 全局 `bot_chat_reasoning_effort` > 家族基线（`baseline_effort`，家族
  最低档）；复杂任务判定会把来自全局/基线的档位临时升到家族最高档（`default_effort`），
  但亲密会话抑制升档（`_intimate_mode_for_session`，RP 长文本易误触发）。接口不支持
  reasoning_effort 时自动去参重试。
- **选型顺序**（纯规则）：① 管理员手动指定（`/bot model set <id>`）→ ②
  `bot_model_priority_groups` 时段分组命中（`parse_priority_groups` /
  `resolve_active_priority_group`，按组内 order）→ ③ priority 升序 → ④ 候选失败按序
  转移下一个。渠道健康参与排序：`_health_filter_candidates` 过滤、
  `_health_ema_latencies` EWMA 延迟择优、`_demote_cooling_candidates` 冷却降位；
  `_strict_priority_enabled` 可切换回严格优先级序。
- **预算与并发**：整链预算 `bot_chat_failover_max_seconds`（缺省以 `config.py` 字段为准，
  生产 `.env` 可覆盖）；单跳地板 `_failover_min_hop_seconds`；影子并发择优由
  `bot_chat_hedged_requests_enabled` 控制（赢家出结果、落选者进账本 attempts）。链级
  fail-fast 与 `config_missing` 冷却见同板块 [fail-fast](fail-fast.md)；上下文钳制见
  [context-caps](context-caps.md)。
- **多模态声明门**：渠道 tags 声明 `native-audio`/`native-video` 等才允许原生媒体入
  payload（缺省不放行 fail-closed）；判据公共口 `ModelRouter.supports_native_media`，
  与 `declared_native_media_kinds` 同源，不用 HTTP 状态推断。
- **出口归账**：`generate()` 成功或最终失败各出一行 draft 给账本 sink（见
  [billing-ledger](billing-ledger.md)），响应体 `id` 供网关归因反查。

## 开关与参数

配置键前缀登记为 `bot_model_`、`bot_llm_`、`bot_chat_failover_`；逐键（含
`bot_chat_reasoning_effort`、`bot_chat_hedged_requests_enabled`、优先级组、预算与冷却类）
的缺省与热更性以 `config.py` 真身字段与 `docs/config-catalog-full.md` 为准，枚数不在本页
手写。注册表本体当前主要经 `.env` + 运行时设置覆盖文件管理，改后按铁律重启生效。
谁能改：手动选模、价格修订属管理员命令面（`/bot model …`）。

## 失败时看到什么

单跳失败按类别定性（network/timeout 为网络类；auth/4xx/server/rate_limited 说明服务端
可达；config_missing 根本没碰网络），失败轨迹进告警与账本 attempts，用户不感知逐跳过程。
整链烧完才见失败面：私聊走五池守岸人话术轮换、群聊走 A-19 降级池温和短句；超时对应
kind=`timeout`/`deadline_exceeded`，后者不可自动重试。渠道被熔断式降速只影响排序，不
产生用户可见错误；恢复靠冷却自然过期。

## 测试与验收

`tests/test_model_router_failover.py`、`tests/test_model_router_channel_failover.py`
（转移序与健康过滤）、`tests/test_llm_failfast.py`（链级中止）、
`tests/test_model_effort_groups_and_pricing.py`、`tests/test_model_family_pricing.py`
（档位与计价家族）、`tests/test_model_context_caps.py`（钳制）、
`tests/test_native_av_input.py`（原生媒体声明门）。用例数以最近一次
`scripts/dev.ps1 -Task test` 实跑为准。真机（重启后）：`/bot model` 看当前链序与实际
服务渠道，`/bot runtime list` 核对覆盖文件在场；网关侧留一跳失败证据（告警带
`[kind,chain=N,last=…]` 轨迹）。
