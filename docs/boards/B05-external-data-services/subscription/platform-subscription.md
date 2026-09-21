# 订阅与更新推送 · 各平台订阅通道

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B05.subscription · 各平台订阅通道

- 层级：一级 B05 → 二级 subscription → 三级 `platform-subscription`
- 实现落点：`plugins/bot_unified_runtime/domains/subscribe`、`plugins/bot_unified_runtime/sources/subscriptions`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

各平台的"怎么认目标、怎么取增量"（纯机制件，不注册路由）。每个 adapter 声明自己支持哪些平台与形态（URL 或 `platform:kind:id`），并把"上次读到哪"变成游标，让上层只需要问一句"有什么新的"。

## 怎么调用

- 注册表：`domains/subscribe/adapters/__init__.py:build_subscription_registry` / `build_subscription_registry_v2`——同目录 `adapters/` 下各平台适配模块由 pkgutil 自动发现并读模块级 `ADAPTERS`，加平台不需要改中央代码。
- 契约：每个 adapter 提供目标解析 + `fetch_latest`（新条目）+（可选）`fetch_live_statuses`（开播探测），失败统一返回 `SourceFetchResult(health_state="degraded")`，错误文本只留异常类型名（不外泄敏感正文）。
- 现有实现：`bilibili_adapter.py`（创作者/直播/番剧/收藏夹/合集，游标按列表顺序切到 `last_id` 为止）、`xiaohongshu_adapter.py`（创作者主页，优先监听 `user_posted` 接口、退化到页面正则，两次都失败判 degraded；专栏 `column` 复用同链路并滤视频型；直播不做探测）、`adapters/social_v2.py`（B站/小红书/YouTube/X·Twitter/Telegram/Pixiv/微博 的 V2 目标解析与取数，X 走带鉴权 GraphQL 客户端，Cookie 判据与 fetch 门同源）、`adapters/music_v2.py`（网易云歌单/专辑/歌手/用户；五个平台按审查项摘除并给人话提示，恢复条件写在头注）。
- 调度组合：`domains/subscribe/store/subscription_watcher.py:build_subscription_watcher(store, adapters, ctx_factory, max_items_per_tick)` → `tick()`（产出 `PushCandidate`，digest 订阅改写 `digest_pending`）、`live_tick()`、`flush_digests()`；退避期未到不重试（`_backoff_active`）。
- 运行时装配：`domains/subscribe/store/subscription_runtime_v2.py:build_subscription_runtime_v2(config, *, delivery_fn, context_factory)` 与 `register_subscription_runtime_v2(...)`（根装配面调用）。

## 开关与参数

每平台一枚 `bot_subscribe_platform_*`；X/Twitter 额外要求 Cookie（`auth_token` + `ct0`），Cookie 来源与 B05.link-parse 共用 `bot_cookies_file`（Netscape 格式，值只在 transport 边界使用、不进日志）；`bot_subscribe_min_interval_seconds`、`bot_subscribe_lease_seconds`、`bot_subscribe_retry_base_seconds` / `_cap_seconds` 控制单平台节奏。

## 失败时看到什么

- 取数失败**不产生推送、也不产生"更新"字样**：游标不前移，下轮再来；用户侧最多是"没收到提醒"，等管理员告警面（B09）浮现。
- 风控/需要登录：degraded，错误正文不外泄；网易云匿名探测遇风控时"取不到就返回零条目，不伪造"。
- 平台已摘除：`SubscriptionTargetNotice` 人话（说明该暂不支持、当前可订什么）。
- 目标不属本平台：泛化"无法识别"，交由 registry 汇总，不冒充别家平台。

## 测试与验收

离线：`tests/test_social_subscription_adapters_v2.py`、`tests/test_social_subscription_fetch_v2.py`、`tests/test_subscription_live_column_kinds.py`（live/column 形态）、`tests/test_music_subscription_v2.py` 与同族 4 件、`tests/test_twitter_subscription_graphql_v2.py`、`tests/test_subscription_cursor_v2.py`（数值 id 用整型比较的游标截止）、`tests/test_subscription_context_v2.py`。
真机：订一个更新频繁的 B 站 UP 主，等到真有投稿时收到一条且**不重复**；订已摘除平台链接看到"暂不支持"；`bot_subscribe_platform_x=false` 后 add 被拒且既有行仍在。
