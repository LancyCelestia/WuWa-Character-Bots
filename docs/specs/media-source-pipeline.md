# 媒体来源流水线

本文定义富媒体链接解析、来源适配器、订阅、卡片渲染和推送投递契约。

相关文档：

- `docs/specs/runtime-parameter-flow.md`
- `docs/specs/input-output-contracts.md`
- `docs/specs/auto-send-capability.md`
- `research/implementation_design_supplement.md`

必须保留统一运行时边界：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

media adapter 可以解析、抓取、归一化和生成渲染候选，但不能直接发送。真实投递仍通过 `SendRequest -> DeliveryReceipt -> AuditRecord`。

来源适配器短链路：

```text
SourceAdapter -> FetchRequest -> FetchResult -> ParsedItem/CapabilityResult -> RenderRequest -> SendRequest -> DeliveryReceipt
```

## 范围

### 目标

- 解析媒体链接、平台分享卡、小程序卡片和命令输入。
- 支持订阅 Bilibili UP 主、博主、直播间、RSS/feed、音乐平台和未来流媒体来源。
- 通过公平调度器轮询，具备 cursor、去重、重试、冷却和摘要。
- 把媒体项渲染为文本、卡片、图片、合并转发或混合输出，并保留文本 fallback。
- 所有推送都走统一发送队列和审计。
- 未来平台通过 source adapter 插入，不新增各自直发插件。

### 首版不做

- 不做大规模抓取或搬运。
- 不绕过平台条款、验证码、登录和 robots 策略。
- parser 输入不携带原始 cookie。
- 不让高频 UP/博主更新在群里刷屏。
- 未经授权不重分发媒体文件。
- source adapter 内不能有平台专用 sender。

## 本地 parser 插件参考

重点参考：

```text
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser
```

该插件的关键结构：

- `main.py`：统一入口，负责事件监听、命令、订阅、音乐、解析调度。
- `core/parsers/base.py`：`BaseParser` 自动注册，`@handle(keyword, pattern)` 声明关键词和正则。
- `core/data.py`：`ParseResult`、`Author`、`MediaContent`、`Comment`、`MusicInfo`。
- `core/render_html/models.py`：`RenderPayload`、`SubscriptionRecord` 等渲染和订阅数据。
- `core/subscriber/*`：多平台订阅、轮询、去重、push mode。
- `core/render.py` / `core/render_html/*` / `core/templates/*`：卡片渲染。
- `core/sender.py`：发送计划、合并转发、文本 fallback。

可吸收经验：

- 解析器只返回 `ParseResult`，不在 parser 里发送。
- 关键词预过滤 + 正则匹配 + 最长关键词优先。
- 短链接先重定向，再归一化为 canonical id。
- 数据模型统一承载作者、正文、来源 URL、统计、媒体、评论、转发、音乐信息。
- 订阅有 cursor、recent ids、push mode、图片限制、平台轮询间隔、jitter、跨平台去重。
- 卡片渲染必须有文本 fallback。

本项目要进一步收口：

- `core/sender.py` 的直发逻辑在新项目里要下沉为 transport adapter。
- media capability 只产出 `CapabilityResult` / `CardRenderModel` / `SendRequest`。
- 真正调用 NoneBot/NapCat 发送 API 的只有 sender 层，并返回 `DeliveryReceipt`。

## 参考插件结论

| 参考 | 可用模式 | 本项目归一化规则 |
| --- | --- | --- |
| `nonebot_plugin_parser` | parser registry、keyword/regex、`ParseResult`、渲染拆分、缓存清理。 | source adapter 先归一化，再渲染/发送。 |
| `nonebot_bison` | 平台抽象、目标解析、加权调度、批量抓取、队列发送、重试。 | 采用调度/队列思想，补齐 `DeliveryReceipt`。 |
| `nonebot_plugin_bilichat` | Bilibili 链接、动态/直播订阅、冷却、富媒体开关。 | 作为 Bilibili adapter 参考，直发改为 `SendRequest`。 |
| `analysis_bilibili` / `bili_helper` / `bili_fav_watcher` | Bilibili URL 形态、API、HTML 卡片、收藏夹 watcher。 | 私密/凭据来源后置。 |
| `nonebot_plugin_htmlrender` / `htmlkit` / `cardimg` | HTML/Markdown/template 渲染。 | 渲染作为服务，不作为能力逻辑。 |
| `kuwo` / `qqmusic_reco` | 音乐搜索和曲目模型。 | 输出 metadata 和官方链接，不重分发完整音频。 |
| AstrBot GsCore adapter | 队列、重连、下游分发、回执关联。 | 桥接输出也要显式关联回执。 |

## 标准媒体链路

```text
SourceInput
-> SourceAdapter
-> ParseRequest
-> FetchRequest
-> FetchResult
-> ParsedMediaItem
-> NormalizedMediaItem
-> CapabilityResult
-> ReviewResult
-> CardRenderModel
-> RenderedOutput
-> SendRequest
-> DeliveryReceipt
-> AuditRecord
```

订阅链路：

```text
SubscriptionSpec
-> SchedulerTick
-> FetchRequest
-> FetchResult
-> SubscriptionCursor
-> PushCandidate
-> ReviewResult
-> RenderedOutput
-> SendRequest
-> DeliveryReceipt
```

规则：

- 用户触发解析和后台订阅共用 adapter 契约。
- 订阅 cursor 只在成功归一化和去重后更新。
- 渲染是后期阶段，不能隐藏来源、风险和隐私标签。
- source adapter 可以建议 `send_policy`，最终由审查和运行时决定。

## Parser、Compiler、Push 三层

```text
Parser: user/share/scheduler input -> normalized source identity
Compiler: source facts -> CapabilityResult/CardRenderModel/RenderArtifact
Push tool: subscription event -> reviewed SendRequest and DeliveryReceipt
```

| 组件 | 输入 | 输出 | 拥有 | 不能拥有 |
| --- | --- | --- | --- | --- |
| `SourceAdapter` | 链接、分享卡、命令、scheduler tick | `ParseRequest`、`FetchRequest`、`ParsedMediaItem` | 平台解析和抓取归一化 | 最终发送、人格改写 |
| `ItemNormalizer` | API/HTML/transcript 原始数据 | `NormalizedMediaItem` | item identity、creator、metrics、source refs | 隐私降级 |
| `CardCompiler` | `NormalizedMediaItem`、模板策略 | `CardRenderModel` | 卡片 payload 和 fallback | 浏览器/截图 transport |
| `RenderBackend` | `RenderRequest` | `RenderArtifact` | HTML/Markdown/template 渲染 | 来源解析 |
| `SubscriptionWatcher` | `SubscriptionSpec`、cursor、tick | `PushCandidate[]` | 轮询、cursor、候选去重 | 直接推送 |
| `PushRouter` | `PushCandidate`、review result | `SendRequest` | 队列/摘要/即时策略映射 | 调用平台 API |

## 场景参数流

| 场景 | 输入 | 贯穿参数 | 归一化输出 | 默认发送策略 |
| --- | --- | --- | --- | --- |
| 直接 Bilibili 链接 | `SourceInput.urls`、消息段、会话策略 | canonical URL、BV/AV/dynamic id、dedupe、cache、timestamp | `CapabilityResult(kind=media)` + 可选 `CardRenderModel` | `immediate`, `max_messages=1` |
| 创作者订阅 | `SubscriptionSpec`、tick、cursor | source id、target id、filters、cursor、quiet hours、digest、rate-limit | `PushCandidate(reason=new_item)` | 群里 `queued` 或 `digest` |
| 直播状态变化 | 上次状态、当前状态、直播元数据 | status diff、start/end、cover、cooldown | `PushCandidate(reason=live_started/live_ended)` | 配置后 immediate 或 digest |
| Blog/RSS 更新 | feed URL、etag、last-modified、作者映射 | cursor、content hash、source URL、title、summary | `NormalizedMediaItem(feed_post)` | 默认 digest |
| 音乐搜索/链接 | 命令或音乐 URL | track id、artist、album、availability、source link | `CapabilityResult(kind=music)` | 命令触发 immediate/private |
| 卡片渲染 | 已审查媒体项、template id | render id、template、theme、max bytes、fallback | `RenderArtifact` / `RenderedOutput` | 继承审查策略 |

每个场景保留 `request_id`、`source_id`、`privacy_level`、`risk_level`、`dedupe_key`、`cooldown_key` 和审计引用。

## Source Adapter Contract

```text
MediaSourceAdapter
- source_id
- display_name
- supported_inputs
- supported_item_kinds
- auth_modes
- default_privacy
- default_risk_level
- rate_limit_keys
- parse(input, context) -> ParseRequest | RejectReason
- resolve(parse_request) -> FetchRequest | ParsedMediaItem | RejectReason
- fetch(fetch_request) -> FetchResult
- parse_fetch_result(fetch_result) -> ParsedMediaItem[]
- normalize(parsed_items, context) -> NormalizedMediaItem[]
- render_model(item, context) -> CardRenderModel | None
```

规则：

- `source_id` 稳定出现在审计、缓存、去重和限频 key 中。
- 不支持输入时返回 `RejectReason`，不要乱抛异常。
- cookie/oauth/qr 等认证流使用引用，不传原始 cookie。
- 平台异常映射到共享错误分类。

### ParserRegistry

```text
ParserRegistry
- parser_id
- source_id
- priority
- keyword_patterns
- url_patterns
- share_card_extractors
- supported_domains
- supported_item_kinds
- short_link_policy: ignore, single_redirect, follow_final
- canonical_id_policy
- cooldown_policy
- cache_policy
- enabled_scopes
- risk_level
```

规则：

- 多个 parser 命中时按优先级运行。
- 允许沿用 `astrbot_plugin_parser` 的 `@handle(keyword, pattern)` 思路：`keyword_patterns` 先做快速子串过滤，再做正则匹配。
- 同一来源多个 keyword 命中时，默认最长 keyword 优先，减少通用规则抢走专用规则。
- 显式 enable 表控制 parser 是否启用；未启用的平台不能被 URL fallback 绕过。
- 通用 URL fallback 只能作为低优先级兜底，并受 SSRF、robots、超时、大小、域名和私有网段策略约束。
- 正则只产生候选，最终身份来自 canonical id。
- `b23.tv` 等短链先按超时/重定向限制解析，再去重。
- OneBot/NapCat JSON 小程序和富分享卡是 `input_kind=share_card`，不是普通文本猜测。
- cache key 优先 canonical source identity，raw URL 只是 fallback。
- 被动群聊不支持的链接静默；显式解析命令给可执行错误。

### PlatformCapabilityMatrix

```text
PlatformCapabilityMatrix
- source_id
- item_kinds
- input_kinds
- canonical_ids
- auth_modes
- parser_priority
- default_render_modes
- subscription_supported
- webhook_supported
- risk_notes
```

Bilibili 初始矩阵：

| 输入 | Canonical id | Item kind | 说明 |
| --- | --- | --- | --- |
| `BV...` / `av...` | `bvid` / `aid` | `video` | 去重前统一成一个视频 id。 |
| `b23.tv` / 短链 | resolved canonical URL | any supported item | 抓取前解析重定向。 |
| PGC episode / season | `ep_id` / `season_id` | `pgc` | season 和 episode 分开。 |
| 直播间 | `room_id` | `live` | 支持直播状态订阅。 |
| 专栏文章 | `cv_id` | `article` | 文本/卡片 + 来源链接。 |
| 动态 / opus | `dynamic_id` / `opus_id` | `dynamic` | 订阅可按动态类型过滤。 |
| 收藏夹 | `fav_id` 或 item id | `favorite_item` | 凭据能力完成前私聊/管理员。 |
| OneBot JSON 小程序 | `qqdocurl` / `jumpUrl` | resolved item | 先解析 app/meta 字段。 |

矩阵是声明式的，新增平台不应改 runtime router。

## 输入模型

### SourceInput

```text
SourceInput
- request_id
- session_id
- capability_id
- source_hint
- input_kind: link, text, command, share_card, scheduler, webhook
- raw_text
- urls
- message_segments
- share_card_fields
- origin_message_id
- sender_id
- target_scope
- privacy_level
- risk_level
```

例子：

- 用户在群里发 Bilibili BV 链接。
- 用户发音乐链接或搜索命令。
- scheduler tick 检查订阅 UP 主。
- 命令要求渲染文章、wiki 页或创作者更新。

OneBot/NapCat 富卡字段建议归一化到 `share_card_fields`：

```text
share_card_fields
- qqdocurl
- jumpUrl
- musicUrl
- playUrl
- videoUrl
- preview
- title
- desc
- app
- meta
```

这些字段只作为候选 URL/标题/摘要来源，不能当可信事实或运行时指令。

### ParseRequest

```text
ParseRequest
- request_id
- source_id
- canonical_url
- platform_item_id
- item_kind_hint: video, dynamic, article, live, music, image, wiki, feed
- options
- requested_render_mode
- cache_key
- dedupe_key
- privacy_level
- risk_level
```

规则：

- 短链先 canonicalize 再 dedupe。
- 原始 URL 用于审计，canonical URL 用于缓存。
- `options` 是结构化 flags，不是原始命令字符串。

### FetchRequest / FetchResult

```text
FetchRequest
- request_id
- session_id
- capability_id
- source_id
- url_or_endpoint
- method
- params
- body
- headers_ref
- auth_mode: none, api_key, cookie, oauth, qr, bridge
- cache_key
- ttl_seconds
- timeout_seconds
- retry_policy
- min_interval_key
- priority: immediate, normal, background
- privacy
- allowed_content_types
- robots_policy
```

```text
FetchResult
- request_id
- session_id
- capability_id
- source_id
- ok
- status_code
- final_url
- content_type
- body_ref
- parsed_json
- fetched_at
- source_etag
- source_last_modified
- rate_limit_remaining
- error_kind
- debug_id
```

规则：

- 每次外部 fetch 都有超时、重试、缓存、限频。
- `auth_mode=cookie/oauth/qr` 会提高风险，通常要求私聊/管理员配置。
- 大 body 存 `body_ref`，不复制到每个阶段。
- 失败 fetch 不更新订阅 cursor。

## 输出模型

### ParsedMediaItem

```text
ParsedMediaItem
- request_id
- session_id
- capability_id
- source_id
- platform
- item_id
- item_kind: video, dynamic, article, live, music, image_set, wiki, feed_post
- title
- author_id
- author_name
- author_avatar
- summary
- text
- url
- canonical_url
- published_at
- updated_at
- media
- stats
- comments
- pinned_comment
- hot_comment
- repost
- page_type
- extra
- send_groups
- tags
- raw_ref
- confidence
- risk_level
- privacy_level
```

### NormalizedMediaItem

```text
NormalizedMediaItem
- request_id
- capability_id
- item_id
- source_id
- normalized_kind
- title
- subtitle
- body
- source_url
- source_timestamp
- creator
- media_refs
- metrics
- comments_summary
- repost_ref
- page_type
- extra_refs
- send_group_policy
- actions
- tags
- language
- confidence
- risk_level
- privacy_level
- dedupe_key
```

规则：

- `dedupe_key` 优先平台 id，其次 canonical URL，最后 content hash。
- 统计数据可缺省。
- 创作者别名和展示名与 source id 分开。
- `ParseResult.author.description` 和 `follower_count` 可映射到 `creator.profile_summary` 或 card header 元数据。
- `comments`、`pinned_comment`、`hot_comment` 默认只进入卡片摘要；完整评论图属于显式命令能力。
- `repost` 以 `repost_ref` 或嵌套 item 表示，避免把递归对象直接塞进 prompt。
- `send_groups` 只提供渲染/发送分组建议，最终仍由 `RenderedOutput -> SendRequest` 决定。

### CapabilityResult 映射

```text
CapabilityResult
- kind: media, article, subscription_post, music, game_card, warning
- title
- summary
- body
- url
- source
- source_timestamp
- images
- actions
- confidence
- risk_level
- privacy_level
- private_recommended
- send_policy
- debug_id
```

规则：

- 直接链接解析通常建议 `send_policy=immediate`。
- 订阅通常建议 `queued` 或 `digest`。
- 敏感或高频来源建议 `private_recommended=true`。

## 订阅模型

### SubscriptionSpec

```text
SubscriptionSpec
- subscription_id
- source_id
- platform
- target_id
- target_name
- target_kind: creator, blogger, live_room, feed, favorite_folder, keyword, playlist
- subscribers
- destination_scope
- destination_id
- filters
- cursor
- cursor_kind: latest_id, timestamp, etag, last_modified, page_token, status_snapshot
- poll_interval_seconds
- schedule_type: interval, cron, manual
- timezone
- min_interval_key
- batch_group
- auth_mode
- credential_ref
- send_policy
- quiet_hours
- digest_policy
- health_state: healthy, degraded, paused, auth_required, backoff, disabled
- backoff_until
- failure_count
- enabled
- created_by
- updated_by
- owner_operator_ids
- privacy_level
- risk_level
```

规则：

- 订阅按目标和目的地 opt-in。
- 群订阅需要群管理、superuser 或配置运营者。
- 每个订阅都有 list/delete/pause/resume/inspect/check-now。
- 需要 cookie 或私密账号数据的订阅后置。
- `credential_ref` 指密钥/联系人库，不存原始 cookie。

### SubscriptionCursor

```text
SubscriptionCursor
- subscription_id
- source_id
- target_id
- last_seen_item_id
- last_seen_timestamp
- last_success_at
- last_failure_at
- failure_count
- backoff_until
- cursor_payload
- version
```

规则：

- 普通订阅在成功归一化和去重后更新 cursor。
- 紧急告警在 `SendRequest` accepted 后更新 cursor。
- 失败 fetch/parse/login/captcha/upstream_changed 不更新 cursor。

### PushCandidate

```text
PushCandidate
- request_id
- subscription_id
- item
- reason: new_item, updated_item, live_started, live_ended, digest_due, alert
- target_scope
- target_id
- priority
- dedupe_key
- cooldown_key
- expires_at
- send_policy
- risk_level
- privacy_level
```

规则：

- 渲染前和发送前都去重。
- 低优先级推送可合并为 digest。
- urgent alert 需要显式来源策略。

## Subscription Command Flow

订阅必须通过命令或管理界面显式配置。订阅命令不是推送，只创建或更新 `SubscriptionSpec`。

示例：

```text
订阅 B站UP 123456 到本群，动态和视频走日报
订阅 博主 https://example.com/feed 给我私聊推送
暂停订阅 bilibili:creator:123456
查看本群订阅
立即检查 bilibili:creator:123456
```

### SubscriptionCommand

```text
SubscriptionCommand
- request_id
- actor_sender_id
- action: create, update, pause, resume, delete, list, inspect, check_now
- source_id
- target_kind
- target_descriptor
- destination_scope
- destination_id
- filters
- send_policy
- digest_policy
- quiet_hours
- auth_mode
- created_by
- risk_level
- privacy_level
```

规则：

- 群订阅需要管理员权限。
- “这个 UP 主” 必须解析成明确 `target_id` 后才能保存。
- `check_now` 也走 watcher flow 并去重。
- cookie-backed/favorite-folder 首版阻断。
- 每个订阅可查看、暂停、删除、检查，用户能知道为什么机器人推送。

### Watcher Tick Semantics

```text
SchedulerTick
-> load enabled SubscriptionSpec
-> enforce min_interval_key and backoff
-> build FetchRequest
-> parse FetchResult
-> compare SubscriptionCursor
-> create PushCandidate
-> update cursor according to cursor policy
-> queue/digest SendRequest
```

## Bilibili 推送规则

首个具体平台建议是 Bilibili，因为参考覆盖直接解析、动态轮询、直播状态、富媒体卡片和收藏夹 watcher。

### 支持目标

| Target kind | Cursor | Push reason | 默认策略 |
| --- | --- | --- | --- |
| `creator` videos | latest video id 或发布时间 | `new_item` | 群里 digest |
| `creator` dynamics | latest dynamic id | `new_item` / `updated_item` | 群里 digest |
| `live_room` | 上次直播状态和开播时间 | `live_started` / `live_ended` | 配置后 immediate |
| `article` author | latest article id 或时间 | `new_item` | digest |
| `favorite_folder` | latest favorite item id 或 content hash | `new_item` | 私聊/管理员优先 |

### BilibiliSubscriptionOptions

```text
BilibiliSubscriptionOptions
- include_video
- include_dynamic
- include_article
- include_live
- include_favorite
- dynamic_type_filters
- rich_media_enabled
- at_all_policy: never, live_only, configured_alerts
- content_cooldown_seconds
- duplicate_scope: destination, source_target, global
- first_run_policy: prime_cursor, send_recent, dry_run_only
```

规则：

- 首次运行默认 `prime_cursor`，只记录当前最新，不推历史。
- 动态类型过滤在渲染和发送前执行。
- 直播开始/结束是状态转移，不是普通新帖。
- `@all` 需要管理员配置，通常只给直播或紧急告警。
- 富媒体开关影响 `CardRenderModel`，不影响 parser identity。
- 验证码、风控、登录要求、403、429 进入 backoff 和管理员审计。

## 渲染模型

### CardRenderModel

```text
CardRenderModel
- render_id
- template_id
- source_id
- item_kind
- title
- subtitle
- body
- creator
- cover_image_ref
- media_refs
- stats
- badges
- source_url
- published_at
- footer
- theme
- width
- max_height
- text_fallback
- privacy_level
- risk_level
```

规则：

- 模板输入必须结构化并转义。
- 卡片要有可见来源归属。
- renderer 失败时返回文本 fallback。
- 渲染保留来源、风险、隐私元数据。

### RenderRequest / RenderArtifact

```text
RenderRequest
- request_id
- render_id
- render_mode: text, card, image, forward, mixed
- template_id
- payload
- output_format: png, jpg, webp, text
- viewport_width
- viewport_height
- device_scale_factor
- wait_until: load, domcontentloaded, networkidle
- wait_selector
- screenshot_full_page
- jpeg_quality
- cache_key
- timeout_seconds
- max_bytes
- privacy_level
- risk_level
```

```text
RenderArtifact
- artifact_id
- request_id
- mime_type
- bytes_ref
- width
- height
- size_bytes
- text_fallback
- source_ref
- render_debug_id
```

规则：

- `bytes_ref` 指 localstore/filehost/object storage。
- HTML 渲染必须声明 viewport、scale、wait、timeout、format、quality、byte limit。
- 渲染缓存按 payload hash 和 template version，而不是只按 URL。
- 私密 artifact 默认不能暴露为公共 URL。
- 推荐三阶回退：HTML/Playwright 或 htmlkit -> PIL/local renderer -> text fallback。
- 每次回退都保留同一个 `render_id`、`request_id`、`render_debug_id`，便于排障。

### RenderBackendStatus

```text
RenderBackendStatus
- backend_id: htmlrender, htmlkit, cardimg, markdown, text
- available
- startup_mode: lazy, startup, external
- browser_engine: playwright, browserless, none
- version
- cache_dir
- last_health_check_at
- failure_reason
```

## Card Compilation Pipeline

卡片编译是从来源事实到渲染 payload 的确定性转换，不编造摘要事实，不抓取无关数据。

```text
NormalizedMediaItem
-> CardTemplatePolicy
-> CardRenderModel
-> RenderRequest
-> RenderArtifact
-> RenderedOutput(text_fallback + artifact ref)
```

### CardTemplatePolicy

```text
CardTemplatePolicy
- source_id
- item_kind
- allowed_templates
- default_template
- theme
- max_width
- max_height
- max_bytes
- include_metrics
- include_comments
- include_qrcode
- include_source_url
- fallback_mode: text, compact_text, block
```

### TemplateCatalog

```text
TemplateCatalogEntry
- template_id
- renderer_backend
- source_id
- item_kinds
- required_vars
- optional_vars
- default_render_options
- resource_roots
- theme_modes
- text_fallback_fields
- validation_schema_ref
- template_version
```

初始模板：

| Template id | 用途 |
| --- | --- |
| `bili_video_compact` | 视频详情卡。 |
| `bili_dynamic_compact` | 动态卡。 |
| `bili_live_alert` | 开播/下播提醒。 |
| `bili_comment_image` | 显式命令触发的评论图。 |
| `music_track_compact` | 歌曲 metadata 卡。 |
| `feed_post_compact` | 博客/feed 更新。 |
| `game_wiki_card` | 公共游戏/wiki 卡。 |
| `cardimg:minote` | 通用笔记卡。 |
| `cardimg:simple` | 简单卡片 fallback。 |
| `cardimg:ncm_zhusha` | 音乐风格卡。 |
| `cardimg:ncm_card` | 音乐卡。 |
| `cardimg:bili` | Bilibili 风格卡。 |
| `cardimg:help` | 帮助卡。 |
| `cardimg:table` | 表格卡。 |

缺必填变量时要在浏览器渲染前失败。

## 平台例子

### 直接视频链接解析

```text
SourceInput(link)
-> ParseRequest(canonical BV/AV URL)
-> FetchRequest(video API)
-> ParsedMediaItem(video)
-> CapabilityResult(media)
-> CardRenderModel
-> SendRequest(immediate, max_messages=1)
```

默认策略：

- 同群重复链接在冷却期静默跳过。
- 来源格式变更时只给一次带 `debug_id` 的可执行失败。
- 富渲染失败时发送标题、作者、来源链接和短摘要。

### UP / 博主订阅

```text
SubscriptionSpec
- source_id: bilibili
- target_kind: creator
- target_id: mid
- filters: dynamic_type, video, live, article
- cursor: latest dynamic id and live status
```

默认策略：

- 群里走 digest，除非配置即时。
- `@all` 必须管理员配置且有高优先级理由。
- 图片卡片必须先审查后发送。

### 音乐平台

```text
MusicItem
- source_id
- platform
- track_id
- playlist_id
- title
- artists
- album
- duration
- bitrate
- quality
- format
- cover_url
- preview_url
- official_url
- source_url
- source_playlist
- availability
- weight
- recommendation_reason
- render_mode
- source_confidence
```

规则：

- 优先发 metadata 卡和官方链接。
- 不重分发完整音频，除非政策和来源允许。
- 搜索结果限量，推荐私聊或命令触发。
- 音乐推荐可使用偏好记忆，但需要同意。
- `preview_url` 不是重发音频文件的许可。

### Blog / Feed / 多媒体账号

```text
SubscriptionSpec
- source_id: rss, website, weibo, xhs, youtube, bilibili
- target_kind: blogger, feed, creator, channel, keyword
- target_id: canonical feed URL, platform id, or verified handle
- filters: tags, title keywords, content type, language
- cursor: etag, last-modified, last item id, published_at, content hash
```

规则：

- 优先官方 feed/API，少用页面抓取。
- 动态、视频、文章等拆成不同 `item_kind`。
- 跨平台重复先按 canonical URL，再按平台 id，再按内容 hash 去重。
- 摘要短而带来源链接，不全文搬运。

### 游戏/wiki 页面

公共游戏/wiki 页面归一化为 `game_card` 或 `article`。鸣潮 wiki、公共攻略、角色卡、游戏文本搜索是低风险；账号面板、token、排名、个人计算是 credentialed，后续实现。

## End-To-End Field Examples

### Direct Link Parse

```text
SourceInput
- request_id: req_001
- session_id: group_10001
- capability_id: media_parse
- source_hint: bilibili
- input_kind: link
- urls: ["https://b23.tv/xxxx"]
- risk_level: low
```

```text
ParseRequest
- request_id: req_001
- source_id: bilibili
- canonical_url: https://www.bilibili.com/video/BV...
- platform_item_id: BV...
- item_kind_hint: video
- cache_key: bilibili:video:BV...
- dedupe_key: bilibili:video:BV...
```

```text
FetchRequest
- request_id: req_001
- source_id: bilibili
- url_or_endpoint: video_info_api
- params: { bvid: BV... }
- headers_ref: public_default
- auth_mode: none
- timeout_seconds: 10
- retry_policy: short_user_waiting
- min_interval_key: bilibili:video_info
```

```text
CapabilityResult -> RenderRequest -> SendRequest
- kind: media
- template_id: bili_video_compact
- send_policy: immediate
- max_messages: 1
- DeliveryReceipt.state: sent | skipped | failed_retryable | failed_final
```

### Subscription Push

```text
SchedulerTick
- request_id: req_sub_001
- subscription_id: sub_bili_123
- source_id: bilibili
- target_id: mid_123456
- cursor: { latest_dynamic_id: "987" }
```

```text
PushCandidate
- request_id: req_sub_001
- capability_id: media_subscription
- source_id: bilibili
- reason: new_item
- dedupe_key: bilibili:dynamic:988
- cooldown_key: destination:group_10001:bilibili:mid_123456
- send_policy: digest
- risk_level: low
```

```text
SendRequest -> DeliveryReceipt -> AuditRecord
- target_scope: group
- target_id: group_10001
- priority: background
- expires_at: digest window end
- receipt state: queued then sent, skipped, blocked, or failed_final
- audit tags: media_subscription, source:bilibili, subscription:sub_bili_123
```

## Scheduler 和队列策略

调度器必须提供：

- 每个 source 的 rate limit；
- 每个 target 的最小间隔；
- 公平权重，避免低频目标饿死；
- jitter，避免同一时间爆发；
- 平台支持时使用批量 API；
- 429、403、captcha、login-required、timeout、parser-change 退避；
- cursor 持久化；
- 新订阅 dry-run / admin inspection。

发送队列必须提供：

- 幂等 `request_id`；
- 目标间隔；
- 重试上限；
- 发送前去重；
- `accepted`、`queued`、`sent`、`skipped`、`blocked`、`failed_retryable`、`failed_final` 回执；
- 后台失败给管理员汇总。

## 去重与防抖

媒体解析需要两层防抖：

```text
LinkDebounce
- session_id
- raw_url_or_share_card_hash
- debounce_window_seconds

ResourceDebounce
- session_id
- source_id
- canonical_item_id_or_resource_hash
- debounce_window_seconds
```

规则：

- link-level 防抖避免同一原始链接短时间重复解析。
- resource-level 防抖避免短链、长链、分享卡指向同一资源时重复发送。
- 解析失败应允许清除 link-level 防抖，方便用户修复后重试。
- 群聊重复命中通常静默；私聊或显式命令可返回简短提示。
- 防抖命中也应写低噪声审计，便于解释“为什么没推”。

## 隐私与风险

| 来源/动作 | 默认 |
| --- | --- |
| 公共链接解析 | 已启用群中允许，带冷却。 |
| 创作者订阅 | 管理员/用户 opt-in，群里默认 digest。 |
| 直播提醒 | opt-in，配置后可 immediate。 |
| 音乐搜索 | 命令触发，只发 metadata/link。 |
| 收藏夹 watcher | 私聊/管理员，直到隐私策略明确。 |
| Cookie/API key 来源 | 私聊/管理员配置，只用 credential refs。 |
| 同人抓取 | 后续，默认私密，要求来源条款。 |
| 媒体重托管 | 默认阻断，除非来源和策略允许。 |

## 错误处理

| 失败 | 运行时行为 |
| --- | --- |
| 不支持链接 | 群里静默；显式命令说明格式。 |
| 命令非法 | 返回期望格式。 |
| 限频 | 排队或提示冷却。 |
| 需要登录 | 引导私聊/管理员配置，别刷重试。 |
| 验证码/风控 | backoff，订阅受影响时通知管理员。 |
| parser changed | 标记 `upstream_changed`，附 `debug_id`。 |
| 渲染失败 | 尽量文本 fallback。 |
| 重复 item | 群里静默跳过。 |
| transport 失败 | 返回 `failed_retryable` 或 `failed_final`。 |

## OneBot V11 / NapCat 消息段处理

- NapCat 作为 OneBot V11 实现接入，推荐 `messagePostFormat: 'array'`。
- 入站 `message` 数组保存在 `SourceInput.message_segments` 和 `IncomingMessage.raw_segments`。
- JSON 小程序、富分享卡、图片、文件、at、reply 等先归一化，不让 parser 直接依赖 adapter 类型。
- 出站图片卡片、文本 fallback、合并转发等由 sender/transport adapter 转成 OneBot/NapCat 消息段。
- NapCat 的 API 返回值映射到 `DeliveryReceipt`，不能只看调用无异常。

## 模块边界

```text
plugins/bot_unified_runtime/sources/
  registry.py
  contracts.py
  fetcher.py
  cache.py
  bilibili.py
  music.py
  wiki.py

plugins/bot_unified_runtime/subscriptions/
  models.py
  scheduler.py
  cursors.py
  digest.py

plugins/bot_unified_runtime/rendering/
  card_model.py
  templates.py
  html_renderer.py
  fallbacks.py

plugins/bot_unified_runtime/sender/
  queue.py
  receipts.py
```

依赖规则：

- `sources/*` 可依赖 fetch/cache/contracts，但不能依赖具体 send API。
- `subscriptions/*` 可调用 source adapter 并创建 `PushCandidate`。
- `rendering/*` 把已审查模型转为 `RenderedOutput`。
- `sender/*` 是唯一能触碰 transport adapter 的层。

## 验收检查

首版应测试：

- 不支持链接不触发 source fetch。
- 短链在去重前 canonicalize。
- 每个外部 fetch 有 timeout、retry、rate-limit key。
- source adapter 输出映射到 `CapabilityResult`。
- 重复媒体项跳过第二次群输出。
- 订阅命令创建/更新 `SubscriptionSpec`，不直接推送。
- fetch 失败不推进 cursor。
- 成功归一化/去重后才推进 cursor。
- 群订阅默认 digest 或 queued。
- Bilibili 动态/视频/直播归一化为不同 item kind。
- blog/feed 通过 canonical URL、item id 或 content hash 去重。
- 音乐搜索只返回 metadata 和来源链接，不重托管音频。
- 卡片编译包含来源和文本 fallback。
- 渲染失败降级文本。
- source adapter 不能调用 transport API。
- 每个 queued push 都产生 `DeliveryReceipt`。
- 凭据来源被阻断时写脱敏 `AuditRecord`。

## 设计结论

富媒体能力应构建为 source pipeline，而不是很多独立发送插件：

- parser 归一化链接和平台数据；
- subscription 用公平调度和 cursor 轮询；
- renderer 编译结构化卡片；
- sender 发送已审查输出并返回回执；
- Bilibili、博客、音乐、wiki、游戏卡片都作为 adapter 插入。

这样未来扩展平台会更顺，也能保持防刷屏、隐私、审计和输出一致性。
