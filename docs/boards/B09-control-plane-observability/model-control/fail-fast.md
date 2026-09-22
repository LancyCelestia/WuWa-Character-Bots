# 模型路由与账本 · 链级快速中止与冷却

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.model-control · 链级快速中止与冷却

- 层级：一级 B09 → 二级 model-control → 三级 `fail-fast`
- 实现落点：`plugins/bot_unified_runtime/llm`、`plugins/bot_unified_runtime/domains/chat_reply/llm_engine`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

治「全网故障时把整条故障转移链一路撞到底、烧满预算才给降级回复」。一次 `generate()` 调用链内，若连续若干跳都是网络类失败（连不上或读超时），就判定大概率全网性故障，立即中止剩余候选链，走既有失败面出用户可见回复。同时把「配置缺失」这类没碰网络的失败单独做重复冷却，避免同一坏渠道每轮都白白占一次跳。

## 怎么调用

判据内建在 `domains/chat_reply/llm_engine/model_router.py`（旧路径 `llm/model_router.py` 是再导出垫片），不是独立入口，随每次模型调用生效：

- 网络类失败集合 `domains/chat_reply/llm_engine/model_router.py::_NETWORK_FAILFAST_KINDS`（`network`、`timeout`）；连续计数达到 `model_router.py::_FAILFAST_CONSECUTIVE_NETWORK` 即中止剩余链、抛出最后一个异常，交由能力层失败面处理。
- `4xx`/`auth`/`server`/`rate_limited` 都是「服务端可达」的证据，出现即打断连续计数；未分类的 `provider_error` 按保守原则也打断（宁可少触发、不误杀单渠道抖动）；`config_missing` 为中性——既不计数也不打断，因为它根本没走到网络。
- 计数随单次请求结束销毁，无跨请求状态。

## 开关与参数

刻意不引入新配置键（用户裁定：总预算不借这个开关去调）。相关常量与既有键：

- `model_router.py::_FAILFAST_CONSECUTIVE_NETWORK`、`_NETWORK_FAILFAST_KINDS`：模块常量，改行为即改代码。
- 整链预算 `config.py::Config.bot_chat_failover_max_seconds`（缺省秒数以 `config.py` 该字段为准；生产 `.env` 有覆盖时以 `.env` 为准）。
- `config_missing` 重复冷却阈值 `model_router.py::_CONFIG_MISSING_COOLDOWN_THRESHOLD` 与倍率 `_CONFIG_MISSING_COOLDOWN_MULTIPLIER`，冷却时长 = 倍率 × `Config.bot_chat_channel_cooldown_seconds`。前两次不冷却，保留「配置问题不等于渠道不可用」的语义（动态注册表改 key 后一跳即愈）。计数器本体在 `channel_health.py::ChannelHealthStore.record_config_missing`（内存态、进程生命周期）。

## 失败时看到什么

用户侧不感知「中止」这件事本身——中止只是把等待时间从「烧满预算」压缩到「连续数跳网络失败」，随后仍走既有失败面：私聊是五池守岸人话术轮换，群聊是 A-19 降级池温和短句。日志侧会带链路与错误类别轨迹（沿用告警 `[kind,chain=N,last=…]` 口径）。`config_missing` 达到阈值时，`model_router.py::_health_record_config_missing` 打一条 `kind=config_missing_repeated` 观测日志，该渠道被降速到队尾，渠道修复后冷却自然过期。

## 测试与验收

`tests/test_llm_failfast.py`（全离线 FakeProvider：连续网络失败触发中止、非网络类打断计数、`config_missing` 中性不计数、前两次不冷却第三次起顺延）。真机（重启后）：断掉全部上游令整链全网络类失败，确认出降级回复的时间明显短于整链预算，且日志出现 fail-fast 轨迹。
