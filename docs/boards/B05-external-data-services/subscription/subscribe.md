# 订阅与更新推送 · 订阅命令

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.subscription · 订阅命令

- 层级：一级 B05 → 二级 subscription → 三级 `subscribe`
- 路由席位：`SUBSCRIBE`（matcher `subscribe`，command=True）
- 判定优先级：12
- 能力 id：`bot.subscribe`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe`、`plugins/bot_unified_runtime/sources/subscriptions`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

订阅系统的命令面：把用户说的「/订阅 添加 <链接>」「订阅 add <目标>」「订阅 列表」「订阅 取消 <id>」等统一归一、鉴权、落库，并回一句人话。它不取数、不推送——只负责"这条订阅关系是否成立、归谁管"。

## 怎么调用

- 席位 `SUBSCRIBE`、能力 id `bot.subscribe`、优先级 12（比多数资讯类入口靠前，因为它是命令而非查询）。
- 文本归一：`domains/subscribe/capabilities/subscribe.py:normalize_subscribe_text`（把 `/订阅 添加 …`、`订阅 add …`、`subscribe add …` 统一成规范形态）、`is_subscribe_command`、`is_standalone_subscribe_command`。
- 命令后端真身：`domains/subscribe/capabilities/subscribe_v2.py:build_subscribe_capability_v2(*, store, adapters, config)`，动作分支 `add / list / pause / resume / remove`（+ `check`、`status` 由旧壳承接）。
- 目标解析全部委托给 adapter 层（`domains/subscribe/adapters/__init__.py:SubscriptionRegistry` 与 `build_subscription_registry_v2`），本文件不写任何平台知识。
- 落库委托 `SubscriptionStoreV2`（目标、目的地、游标、seen、outbox）。

## 开关与参数

- `bot_subscribe_enabled`（缺省 True，总开关）；`bot_subscribe_db_path`（库路径的缺省值以 `config.py` 该字段为准，经 runtime_paths 重映射）。
- 每平台一布尔：`bot_subscribe_platform_bilibili/_xiaohongshu/_youtube/_telegram/_pixiv/_weibo/_netease`（缺省 True）。关掉某平台后 `add` 该平台目标会被显式拒绝，**既有订阅行不删**（轮询侧跳过）。
- 节律键：`bot_subscribe_poll_interval_seconds`（缺省 300）、`max_items_per_tick`（20）、`jitter_ratio`（0.20）、`global_concurrency`（3）、`platform_concurrency`（1）、`min_interval_seconds`（1.0）、`lease_seconds`（120）、`retry_base_seconds`（60）、`retry_cap_seconds`（1800）、`outbox_interval_seconds`（15）。
- `bot_subscribe_card_enabled`（缺省 True）：推送是否出卡。
- 装配期读取，改这些值需重启；逐键语义以 `docs/config-catalog-full.md` 为准。

## 失败时看到什么

- 目标形态不对：回用法句（`订阅 add <公开目标>`），不猜用户想订什么。
- 群内 `add` 但发送者非管理员：拒绝话术（`subscribe_add_denied`）——**add 会把推送目的地写成本群**，所以这是权限面而不是偏好面。
- `list` 越权：只回自己可见的范围（历史上曾向所有人泄露全部订阅，已按审计项收口）。
- 订一个"认得但暂不支持"的平台（QQ 音乐/酷我/酷狗/Apple Music/Spotify 已摘除）：抛 `SubscriptionTargetNotice`，用户看到明确"暂不支持 + 目前还能订什么"，而不是静默成功。
- 已关闭的平台：当场说明该平台的订阅开关关着，不假装落库成功。

## 测试与验收

离线：`tests/test_subscribe_capability_v2.py`（动作矩阵与话术）、`tests/test_subscribe_capability_bridge.py`（新旧壳桥接）、`tests/test_subscribe_platform_switch_j02.py`（per-platform 开关唯一实现、关平台时 add 拒绝且旧行不动）、`tests/test_subscription_target_metadata_v2.py`、`tests/test_music_subscription_removed_platforms_j06_v2.py`、`tests/test_twitter_subscription_registration_j01_v2.py`、`tests/test_auditfix_subscriptions_capabilities.py`。
真机：群内管理员 `订阅 add <B站UP主空间链接>` → `订阅 列表` 可见；普通成员同令被拒；私聊 `订阅 add <链接>` 后只有本人能 pause/remove；`/bot help 订阅` 看参数说明。
