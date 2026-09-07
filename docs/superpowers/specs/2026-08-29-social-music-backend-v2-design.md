# 社交媒体解析、订阅与音乐后端 V2 设计

> 日期：2026-08-29  
> 状态：已确认，待实施  
> 范围：仅后端数据源、抓取、契约、存储、调度、统计与返回逻辑；不修改 UI、输出文案、HTML/CSS、卡片模板或图片渲染

## 1. 目标与验收边界

本项目重建社交媒体与音乐后端的数据契约和订阅基础设施。新实现不兼容旧 `PlatformParse`、旧订阅 SQLite 表或旧解析器内部返回结构。切换到 V2 时，现有 `subscriptions.sqlite3` 一次性保留为 `subscriptions_old.sqlite3`，新后端继续使用标准路径 `subscriptions.sqlite3` 创建全新数据库；不得覆盖已经存在的 `subscriptions_old.sqlite3`。

完成状态必须同时满足：

1. 所有已注册内容解析器返回同一个强类型后端契约，不再用无约束的 `stats/detail` 字典表达核心字段。
2. 解析结果区分内容、创作者、互动、媒体、音乐、数据来源和字段不可用原因。
3. Bilibili、小红书、YouTube、X/Twitter、Telegram 公开频道、Pixiv、微博具备完整订阅 adapter：目标识别、首次建基线、增量查询、持久去重、游标、失败退避、健康状态和推送候选返回。
4. 音乐解析返回歌曲别名、全部可获得的音乐人及角色、专辑、封面、时长和平台公开互动数；网易云必须查询评论数和平台可公开获得的收藏/热度数据。
5. 只统计机器人 `bot.music` 点歌行为；普通音乐链接解析、订阅发现和榜单同步不计入点歌次数。
6. 支持音乐歌手、专辑、歌单和公开用户目标的增量更新；平台确实不支持的目标在创建订阅时返回结构化 `unsupported_target_kind`，不伪造能力。
7. 支持本地机器人点歌日榜、周榜、年榜，以及可配置的二次元、电音、摇滚、日本音乐等平台榜单源。
8. 每次平台请求有超时、平台级并发限制、请求抖动、指数退避和 `Retry-After` 处理；不得以批量并发突发请求平台。
9. 不可公开取得的数据保持 `null` 并记录原因；不得用零、空字符串或估算值冒充真实数据。
10. 通过工作区规定的 test、lint、runtime-layout 三项验证，且不在源码树产生缓存。

## 2. 非目标

本轮不做：

- UI、文本展示、卡片布局、HTML、CSS、图片渲染和视觉验收；
- 下载受版权保护的完整音乐或绕过会员、地域、登录、数字版权管理限制；
- 获取平台不公开的数据、私密内容、成员身份或删除历史；
- 为 Lofter、萌娘百科、allCPP、米画师、画加、库街区、森空岛、米游社、抖音、快手、Facebook、Instagram 实现订阅抓取；
- 迁移旧订阅数据库或继续支持旧 `PlatformParse`；
- 将平台热度与机器人点歌次数混为一个排名指标。

这些长尾平台的内容解析仍须迁移到新解析契约；只是暂不提供订阅 adapter。

## 3. 现状、变更后状态与影响分析

### 3.1 变更前

- 解析器实际返回 `sources/parsers/types.py::PlatformParse`。
- `stats` 同时混放内容互动、创作者统计、时长、发布时间和 QQ 音乐传输参数。
- `detail` 是非正式字典协议，平台之间键名和层级不一致。
- 内容能力对同一链接可能调用解析器两次，增加延迟和风控概率。
- 订阅使用旧 SQLite、顺序轮询和单个 watcher；Bilibili 直播状态仅保存在内存。
- YouTube、X、Telegram、Pixiv、微博没有完整订阅 adapter。
- 音乐结果没有统一歌曲模型，点歌成功只留下审计标签，不能可靠聚合。

### 3.2 变更后

- 所有解析器直接返回 `ParsedContent`。
- 所有核心字段都有明确类型、命名空间和空值语义。
- 订阅 V2 使用新数据库、到期队列、租约、per-target 抖动、平台并发限制、持久游标和 outbox。
- 必需平台 adapter 只负责目标解析与增量发现；单条内容深化复用同平台解析客户端。
- 音乐使用 `MusicTrack`、平台别名映射和专用点歌事件表。
- 渲染系统不参与本轮设计；后端只在既有输出边界提供结构化投影，不修改模板。

### 3.3 收益

- 一份元数据契约覆盖解析、订阅、音乐和榜单，消除重复映射。
- 作者指标与帖子/视频指标不会再串栏。
- 统一请求上下文、限流和缓存降低请求量与平台风控概率。
- 新平台只需实现客户端与 adapter，不需修改 watcher、存储或推送主流程。
- 点歌行为和平台热度可独立统计、独立解释。

### 3.4 风险与控制

| 风险 | 触发条件 | 控制措施 |
|---|---|---|
| 全量契约替换造成大范围回归 | 任一旧 parser 尚未迁移 | 编译期类型约束；平台注册表只接受 `ParsedContent`；按平台注册 fixture；合并前一次性切换 |
| 平台封禁或验证码 | 同域请求突发、固定轮询节奏、Cookie 失效 | per-target 抖动、平台并发上限、最小间隔、指数退避、健康状态、Cookie 不自动重试轰炸 |
| 第三方网页结构变化 | X GraphQL、Telegram 网页、小红书 Playwright 改版 | 数据源客户端与 adapter 分离；HTML/JSON fixture；结构化 degraded 原因；备用通道接口 |
| 首次订阅刷历史消息 | 新目标没有游标 | 首次成功只写 baseline，不产推送；显式 backfill 另设后端参数且默认 0 |
| 重启后重复推送 | 内存状态丢失 | 游标、seen item、直播场次与 outbox 全部持久化 |
| 同名歌曲错误合并 | 标题相同但演唱者或版本不同 | ISRC 优先；其次人工别名；最后使用标题+音乐人+时长指纹并保留置信度 |
| 不可得字段被误判为 0 | 平台缺键或受限 | 可空整数；仅响应明确返回 0 时写 0；`limitations` 记录原因 |
| 并行会话覆盖工作树 | 当前核心文件存在大量未提交改动 | 实施前逐文件读取最新内容；按模块串行编辑；不恢复、删除或提交无关变化 |

### 3.5 可逆性

新后端使用标准数据库路径和独立 V2 schema。切换时只允许把旧 `subscriptions.sqlite3` 原子保留为 `subscriptions_old.sqlite3`，不得覆盖同名旧备份；新库创建失败时应停止切换并保留旧库。回退时可以恢复旧代码并读取 `subscriptions_old.sqlite3`；V2 数据保留但不再被读取。由于用户明确选择不兼容旧契约，不提供自动降级到旧 parser 的运行时开关。

## 4. 总体架构

```text
Incoming URL / music command / scheduler tick
        │
        ├── SourceRegistry ── URL/target matching
        │
        ├── PlatformClient ── HTTP/HTML/Playwright/API requests
        │       └── RequestPolicy: timeout, proxy, cookie, rate limit, jitter, retry
        │
        ├── PlatformParser ── raw payload → ParsedContent
        │
        ├── SubscriptionAdapter ── target → new ContentReference[] + cursor
        │       └── Parser/Client deepen each new reference only once
        │
        ├── MusicResolver ── provider result → MusicTrack → canonical track
        │
        └── Stores
                ├── subscriptions.sqlite3
                │   └──（切换前旧库安全保留为 subscriptions_old.sqlite3）
                └── music_analytics.sqlite3
```

### 4.1 模块边界

- **契约层**：只定义模型、枚举和协议；不发网络请求。
- **平台客户端层**：只处理端点、请求参数、认证、代理、响应校验和原始载荷；不决定推送。
- **解析层**：把平台载荷归一为 `ParsedContent`；不写数据库。
- **订阅 adapter 层**：解析目标、获取增量引用、推进游标；不直接发送消息。
- **调度层**：领取到期任务、施加抖动/租约/并发限制、调用 adapter、写 outbox。
- **音乐统计层**：规范化歌曲、记录点歌事件、生成聚合榜单；不解析社交内容。
- **发送边界**：消费 outbox 并交给现有运行时；本轮不修改展示结构。

## 5. 新统一内容契约

权威模型放在 `contracts/media.py`。旧 `PlatformParse` 删除；`sources/parsers/types.py` 删除或只保留不含旧类型的解析协议导出。

### 5.1 顶层模型

```python
class ParsedContent(StrictBaseModel):
    identity: ContentIdentity
    content: ContentMetadata
    creator: CreatorMetadata | None = None
    engagement: EngagementMetrics = EngagementMetrics()
    media: list[MediaAsset] = []
    music: MusicTrack | None = None
    provenance: SourceProvenance
```

### 5.2 身份与内容

```python
class ContentIdentity:
    platform: str
    item_id: str
    item_kind: ContentKind
    canonical_url: str
    parent_id: str | None
    visibility: Visibility
    availability: Availability

class ContentMetadata:
    title: str
    body: str
    summary: str
    tags: list[str]
    language: str | None
    published_at: datetime | None
    updated_at: datetime | None
```

`ContentKind` 至少包括：`video`、`short_video`、`live`、`post`、`note`、`article`、`dynamic`、`image_set`、`illust`、`manga`、`novel`、`music_track`、`album`、`playlist`、`profile`、`episode`、`product`、`unknown`。

### 5.3 创作者模型

```python
class CreatorMetadata:
    platform_creator_id: str | None
    name: str
    handle: str | None
    avatar_url: str | None
    profile_url: str | None
    bio: str | None
    signature: str | None
    verification: VerificationMetadata | None
    follower_count: int | None
    following_count: int | None
    received_like_count: int | None
    received_favorite_count: int | None
    post_count: int | None
    long_video_count: int | None
    short_video_count: int | None
    video_count: int | None
    joined_at: datetime | None
```

不包含“发布者人数”字段。

`VerificationMetadata` 保存 `verified`、`type`、`label` 和平台返回的认证说明。昵称、ID、handle 和认证说明不得拼入同一个字符串。

### 5.4 互动指标

```python
class EngagementMetrics:
    view_count: int | None
    play_count: int | None
    like_count: int | None
    heart_count: int | None
    favorite_count: int | None
    bookmark_count: int | None
    comment_count: int | None
    share_count: int | None
    repost_count: int | None
    quote_count: int | None
    danmaku_count: int | None
    coin_count: int | None
    platform_extra: dict[str, int | float | str | bool | None]
```

`like_count`、`heart_count`、`favorite_count`、`bookmark_count` 保持分离；只有平台语义明确相同才映射，不能为填满字段而互相复制。

### 5.5 媒体资源

```python
class MediaAsset:
    asset_type: MediaAssetType
    url: str | None
    preview_url: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    mime_type: str | None
    bitrate: int | None
    fps: float | None
    dynamic_range: str | None
    order: int
    access_headers: dict[str, str]
```

`access_headers` 只允许保存非敏感访问要求，例如图片 Referer；不得保存 Cookie、Authorization 或令牌。

### 5.6 来源、空值和限制

```python
class SourceProvenance:
    parse_depth: ParseDepth
    auth_mode: AuthMode
    fetched_at: datetime
    source_endpoints: list[str]
    limitations: dict[str, str]
    warnings: list[str]
```

示例：

```json
{
  "limitations": {
    "creator.joined_at": "platform_not_public",
    "engagement.share_count": "platform_not_exposed",
    "creator.follower_count": "hidden_by_creator"
  }
}
```

只记录端点路径或服务名，不记录含令牌、Cookie 或签名参数的完整敏感 URL。

## 6. 平台客户端与解析器

### 6.1 共用请求上下文

所有客户端接收同一 `FetchContext`：

- timeout；
- proxy；
- cookie header 或 credential reference；
- user agent/header profile；
- platform rate limiter；
- trace ID；
- Playwright backend（可选）。

客户端返回 `FetchEnvelope[T]`：载荷、最终 URL、HTTP 状态、抓取时间、数据源名和非敏感警告。

同一链接在一次能力调用中只解析一次。候选 URL 匹配先用规则完成，不通过真实解析器试探；解析成功对象直接进入后续流程。

### 6.2 必需平台字段与来源

#### Bilibili

来源包括现有 view、dynamic/opus、space、relation、navnum、live、bangumi、favorite、collection 等 API。解析必须归一：

- 视频/动态正文、封面和全部可得图片；
- 播放、弹幕、评论、点赞、投币、收藏、分享；
- 作者 ID、昵称、头像、签名、粉丝、关注、视频/专栏/帖子统计；
- 发布时间、时长、直播状态；
- 注册日期标为 `platform_not_public`。

#### 小红书

来源为页面初始状态、`user_posted` JSON 和用户页状态；必要时使用 Playwright。必须归一：

- 笔记标题、正文、全部图片/视频预览、发布时间；
- 点赞、收藏、评论、接口真实返回的分享数；
- 作者 ID、昵称、头像、签名、粉丝、关注、获赞与收藏、真实笔记总数；
- 非本人不可见的浏览量或转发数据保持 `null`。

#### YouTube / YouTube Music

普通 YouTube 使用 oEmbed、Innertube player/next、watch 页和 channel/about；订阅增量优先使用公开 Atom Feed。必须归一：

- 视频 ID、标题、简介、缩略图、时长、发布日期；
- 浏览、点赞、评论；
- channel ID、名称、handle、头像、简介、订阅数、长视频/短视频/总视频数、注册日期和认证；
- Shorts、直播、首播和普通视频分类；
- 分享数和点踩数标为平台不公开。

`music.youtube.com` 仍复用 YouTube 身份解析，但在能识别曲目时填充 `MusicTrack`；无法可靠识别时返回普通视频内容，不虚构音乐字段。

#### X/Twitter

单帖优先使用 fxtwitter 深化；创作者订阅使用登录态网页 GraphQL 时间线，官方 API v2 作为可替换 backend 接口。必须归一：

- 正文、全部媒体预览、发布时间；
- 浏览、点赞、回复、转发、引用和接口公开的书签数；
- reply、quote、repost 的关系；
- 作者 ID、handle、昵称、头像、简介、粉丝、关注、帖子数、注册日期和认证；
- GraphQL query id/feature 参数由客户端配置或页面 bootstrap 解析，不散落在 adapter 中。

#### Telegram

内容解析支持 `t.me/<channel>/<message_id>`；订阅仅支持 `t.me/s/<public_channel>`。必须归一：

- 频道 username、名称、头像/简介（页面公开时）；
- 消息 ID、正文、时间、媒体预览；
- 页面显示的浏览、转发、反应数据；
- 置顶消息标记和公开评论入口；
- 私有邀请链接、成员身份、历史删除记录返回结构化不可用原因。

Bot API 管理频道模式预留 `TelegramManagedChannelBackend` 协议，但不假设 Bot API 可以读取任意历史。

#### Pixiv

使用 `/ajax/illust`、`pages`、`user/profile/all`、用户详情、小说与系列接口。必须归一：

- 插画/漫画/动图/小说分类、标题、简介、标签、创建/上传时间；
- 全部作品图片引用、尺寸、动图元数据；
- 浏览、点赞、收藏、评论；
- 作者 ID、昵称、头像、简介、粉丝、关注、作品数；
- R18、AI 生成、可见性和访问限制；
- Cookie provider 新增 Pixiv 域和 `PHPSESSID`，原图 Referer 要求进入非敏感 `access_headers`。

#### 微博

使用移动 status API、PC ajax fallback、移动页面 render data 和用户时间线容器。必须归一：

- 正文、长文、全部配图/视频预览、发布时间、来源客户端和位置（接口返回时）；
- 点赞、评论、转发、收藏；
- 转发原帖关系；
- 作者 ID、昵称、头像、简介、认证说明、粉丝、关注、微博数和注册日期（接口公开时）；
- 长文第二跳必须继承 Cookie、代理和超时。

### 6.3 其他已注册解析器

Lofter、萌娘百科、allCPP、米画师、画加、库街区、森空岛、米游社、抖音、快手、Facebook、Steam、Epic、AcFun、画师平台及其他注册项全部改为返回 `ParsedContent`。每个平台必须：

- 填充真实可得的内容、创作者、互动、媒体和来源字段；
- 把平台特有数值放入 `platform_extra`；
- 把不可得核心字段写入 `limitations`；
- 不提供订阅 adapter，直到后续单独实现。

Instagram 不宣称可用：只保留未来客户端/adapter 注册接口；当前公开内容被登录墙阻断时返回 `blocked`。

## 7. 订阅 V2

### 7.1 新数据库

新数据库路径固定为 `data/subscriptions.sqlite3`。V2 切换前若该文件存在，先以原子重命名方式保留为 `data/subscriptions_old.sqlite3`；若 `subscriptions_old.sqlite3` 已存在则停止并报告，禁止覆盖。V2 只读写新的 `subscriptions.sqlite3`，不读取、不迁移旧库内容。

核心表：

1. `subscription_targets`
   - id、platform、target_kind、target_key、display_name；
   - `target_payload` JSON；
   - source_mode、enabled、health_state；
   - base_interval_seconds、jitter_ratio；
   - next_poll_at、lease_until、failure_count、backoff_until；
   - created_at、updated_at。

2. `subscription_destinations`
   - target_id；
   - transport、scope、destination_id、bot_id；
   - send_policy、digest_enabled、enabled。

3. `subscription_cursors`
   - target_id、stream；
   - last_item_id、last_timestamp、cursor_payload；
   - updated_at；
   - `(target_id, stream)` 唯一。

4. `subscription_seen_items`
   - target_id、item_kind、item_id、published_at、discovered_at；
   - `(target_id, item_kind, item_id)` 唯一。

5. `subscription_outbox`
   - event_id、target_id、item_kind、item_id、payload；
   - state、attempts、next_attempt_at、created_at、sent_at；
   - `(target_id, item_kind, item_id, event_type)` 唯一。

6. `subscription_poll_log`
   - target_id、started_at、finished_at、result、item_count、error_code；
   - 不保存 Cookie、token、原始异常正文。

所有 schema 创建和升级脚本幂等；由于数据库是 V2 新库，只需要维护 V2 内部的 schema version。

### 7.2 调度、抖动和限流

调度器短周期唤醒并原子领取到期目标，而不是每次把全部订阅同时轮询。

每个目标的下一次执行时间：

```text
stable_phase = hash(target_id) mod base_interval
cycle_jitter = random(-jitter_window, +jitter_window)
next_poll_at = cycle_boundary + stable_phase + cycle_jitter
```

默认策略：

- `jitter_ratio = 0.20`，可按平台覆盖；
- 同平台并发默认 1；
- 全局并发默认 3；
- 同域请求之间有最小间隔；
- Playwright 平台默认更长轮询周期；
- 服务器返回 `Retry-After` 时严格采用；
- 失败退避使用指数退避加 full jitter，并设置上限；
- 认证失败和验证码进入 `auth_required/blocked`，不在短周期内反复重试；
- 每个目标使用数据库租约，防止多实例重复执行；
- 首次抓取只建立 baseline，默认不创建 outbox。

### 7.3 adapter 协议

```python
class SubscriptionAdapter(Protocol):
    platform: str
    target_kinds: frozenset[SubscriptionTargetKind]

    async def resolve_target(
        self, raw_target: str, ctx: FetchContext
    ) -> SubscriptionTarget: ...

    async def fetch_incremental(
        self,
        target: SubscriptionTarget,
        cursors: dict[str, SubscriptionCursor],
        ctx: FetchContext,
    ) -> SubscriptionFetchResult: ...
```

`SubscriptionFetchResult` 返回 `ContentReference[]`、每个 stream 的新游标、健康状态、建议下次轮询时间和结构化错误；adapter 不写库、不发送消息。

### 7.4 必需 adapter

| 平台 | target kinds | 增量游标 |
|---|---|---|
| Bilibili | creator、live_room、bangumi、favorite、collection | video BVID、dynamic ID、episode ID、collection item ID、live session ID |
| 小红书 | creator | note ID + published_at |
| YouTube | channel、playlist | video ID + published_at |
| X/Twitter | creator | numeric status ID + timeline cursor |
| Telegram | public_channel | message ID；独立 pinned marker |
| Pixiv | creator、novel_creator、novel_series | illust、manga、novel 分 stream 游标 |
| 微博 | creator | status ID/BID + published_at |

每个新引用只深化解析一次。订阅 adapter 与链接 parser 共用 platform client，不复制请求参数和字段映射。

## 8. 音乐模型、点歌统计、订阅与榜单

### 8.1 音乐模型

```python
class MusicTrack:
    canonical_track_id: str | None
    provider: str
    provider_track_id: str
    title: str
    aliases: list[str]
    contributors: list[MusicContributor]
    album: MusicAlbumRef | None
    artwork_url: str | None
    duration_ms: int | None
    release_date: date | None
    track_number: int | None
    disc_number: int | None
    isrc: str | None
    language: str | None
    genres: list[str]
    explicit: bool | None
    lyrics: LyricsBundle | None
    preview: AudioPreview | None
    engagement: MusicEngagement
    availability: ProviderAvailability
```

`MusicContributor` 使用角色枚举并允许平台扩展：`performer`、`featured_artist`、`lyricist`、`composer`、`arranger`、`producer`、`remixer`、`conductor`、`other`。同一音乐人可有多个角色。

`MusicEngagement` 至少包括：

- like/heart；
- favorite/collection；
- comment；
- share；
- popularity；
- 网易云独立来源标识。

平台没有公开指标时保持 `null`。

### 8.2 平台深化

- **网易云**：歌曲详情、歌词、评论/动态资源、歌手、专辑、歌单和公开用户端点；查询别名、全部可得贡献者、时长、封面、评论总数，以及平台明确公开的收藏/热度数据。
- **QQ 音乐**：musicu/song detail/search/lyric/album/playlist 数据；读取歌手、专辑、时长、封面、公开热度和贡献者字段。
- **酷我**：官方详情、歌词、歌手/专辑/歌单端点优先；第三方搜索不作为权威元数据源。
- **酷狗**：搜索、song info、歌词、歌手/专辑/歌单公开端点；使用 HTTPS 可用端点，无法避免 HTTP 时记录安全限制并不传敏感 Cookie。
- **Apple Music/iTunes**：iTunes Search/Lookup 获取公开曲目和 30 秒试听；需要 Apple Developer Token 的能力通过可选客户端启用。
- **Spotify**：Spotify Web API，Client Credentials 用于公开曲目、艺人、专辑、歌单和用户数据；未配置凭据时只保留公开 oEmbed 链接解析并明确能力限制。
- **YouTube Music**：从 YouTube/Innertube 可确认的音乐字段构造 `MusicTrack`，不把普通视频自动当歌曲。

### 8.3 点歌行为数据库

新数据库路径默认：`data/music_analytics.sqlite3`。

核心表：

- `music_tracks`：规范歌曲和最新元数据；
- `music_provider_tracks`：provider + provider_track_id → canonical_track_id；
- `music_track_aliases`：平台别名和标准别名；
- `music_request_events`：成功点歌事件；
- `music_chart_snapshots`：平台榜单快照；
- `music_chart_entries`：榜单曲目及排名。

点歌事件只在 `bot.music` 最终选定一首歌曲后写一次，记录：request ID、canonical track ID、provider、provider track ID、会话类型、时间。默认不保存原始搜索词和用户明文 ID；如果需要独立点歌人数，只保存带部署盐的不可逆哈希。

歌曲归并优先级：

1. 标准化 ISRC；
2. 已确认的平台映射；
3. 规范化标题 + 排序后的主要音乐人 + 时长桶指纹；
4. 低置信匹配不自动合并，保留独立 canonical track。

### 8.4 音乐动态订阅

音乐订阅 adapter 使用同一订阅 V2 协议，支持 `artist`、`album`、`playlist`、`public_user`。每个平台显式公布能力矩阵：

- 网易云：四类目标；
- QQ 音乐：artist、album、playlist，public_user 仅在公开接口实测可用时启用；
- 酷我：artist、album、playlist；
- 酷狗：artist、album、playlist；
- Apple/iTunes：artist、album；需开发者 token 的 playlist/user 不默认启用；
- Spotify：配置 Client Credentials 后支持公开 artist、album、playlist、public_user；
- YouTube Music：channel/playlist 复用 YouTube 订阅目标并输出音乐条目。

歌单和公开用户使用“成员集合变化”检测新曲，不把排序变化误判为新歌。删除曲目可以记录变更事件，但默认不产生“新歌”推送。

### 8.5 榜单

两类榜单完全分离：

1. `bot_request`：从 `music_request_events` 聚合日榜、周榜、年榜；
2. `provider_chart`：从平台公开榜单或配置的权威歌单生成二次元、电音、摇滚、日本音乐等快照。

榜单源由后端注册表配置：platform、chart ID/URL、category、刷新周期、地区、来源类型。快照保留抓取时间、平台排名和原始 provider track ID。若某分类只能由策展歌单代表，必须标记 `source_type=curated_playlist`，不能宣称是平台官方热榜。

## 9. 错误模型与健康状态

统一错误代码：

- `not_found`
- `unsupported_url`
- `unsupported_target_kind`
- `auth_required`
- `auth_expired`
- `rate_limited`
- `blocked`
- `captcha_required`
- `region_restricted`
- `private_content`
- `upstream_changed`
- `timeout`
- `network_error`
- `invalid_payload`

错误对象包含 platform、operation、retryable、retry_after、公开安全信息和内部 debug ID。不得包含 Cookie、token、签名 URL 或完整原始响应。

订阅健康状态：`healthy`、`degraded`、`auth_required`、`rate_limited`、`blocked`、`unsupported`、`paused`。状态变化持久化并影响下一次调度。

## 10. 缓存与资源控制

- 单次消息内共享 request-scoped cache，避免同 URL 重复抓取。
- 平台详情短时缓存按 platform + item ID + auth scope 建键。
- 订阅增量响应不跨目标错误复用。
- Cookie 登录态缓存与匿名缓存分离。
- HTML/JSON 原始载荷只在内存中短暂存在，默认不落盘。
- 大列表先只取 ID/时间，再仅深化新条目；不得每轮重新深化全部历史。
- Playwright 只用于无稳定 HTTP 通道的平台，并限制独立并发和更长轮询周期。

## 11. 测试策略

遵守工作区“少量关键回归测试”约束，使用少数聚合测试文件和离线 fixture：

1. `test_media_contract_v2.py`
   - 严格模型、空值语义、时间规范、敏感字段拒绝、所有 parser 返回新类型。

2. `test_required_platform_parsers.py`
   - Bilibili、小红书、YouTube、X、Telegram、Pixiv、微博关键 JSON/HTML fixture；
   - 多媒体、作者数据、互动数据和 limitations；
   - Cookie/代理参数传递；
   - 同链接只抓一次。

3. `test_subscription_v2.py`
   - 七个平台 target resolve、首次 baseline、增量、游标、持久去重；
   - 重启不重复推送；
   - outbox 唯一性；
   - lease、防并发重复；
   - per-target 抖动、指数退避、Retry-After 和平台并发限制。

4. `test_music_backend_v2.py`
   - 七类音乐来源的元数据映射；
   - 网易云评论/收藏或热度查询；
   - contributor 角色；
   - ISRC/指纹归并；
   - 点歌成功只记一次、链接解析不计数；
   - 日/周/年榜和平台分类榜分离。

5. `test_parser_registry_v2.py`
   - 所有注册 parser 都返回 `ParsedContent`；
   - 长尾平台缺字段必须有 limitations；
   - 不存在旧 `PlatformParse` 消费路径。

网络实测作为受控 smoke，不放入默认离线测试；只使用公开测试目标和已有配置，不打印凭据。

## 12. 实施顺序

1. 新契约、统一错误、请求上下文和平台客户端协议。
2. 新订阅数据库、store、调度器、抖动/限流/退避、outbox。
3. 必需七个平台 parser/client/adapter。
4. 音乐模型、六个平台与 YouTube Music 深化、点歌统计数据库。
5. 音乐动态 adapter 与榜单 registry。
6. 所有剩余已注册 parser 一次性迁移到新契约。
7. 更新后端配置、诊断和必要文档；不修改 UI/文案/图片渲染。
8. 离线测试、受控 smoke、lint、runtime-layout。

代码切换采用单一 V2 主路径。阶段开发期间允许分支内暂时不能运行，但最终合并状态不得同时保留旧新 parser 契约或隐式兼容层。

## 13. 决策日志

| 决策 | 选择 | 理由 | 被否决方案 |
|---|---|---|---|
| 解析契约 | 全量替换为强类型 `ParsedContent` | 用户确认系统尚未完整实现，无需承担旧契约兼容成本 | 覆盖层双写、平台独立结构 |
| 发布者人数 | 删除 | 用户确认是口误 | 保留 `publisher_count` |
| 订阅存储 | `subscriptions.sqlite3` 使用全新 V2 schema；旧库改名为 `subscriptions_old.sqlite3` | 保留回退路径，同时让新实现使用标准文件名；旧内容不迁移 | 原地复用旧 schema、迁移旧 SQLite |
| 风控控制 | per-target 抖动 + 平台并发限制 + 指数退避 | APScheduler 单 job jitter 不能阻止同一 tick 内平台突发请求 | 只给全局 job 设置 jitter |
| X 时间线 | 登录态网页 GraphQL 主通道，官方 API backend 预留 | 复用现有 Cookie/代理，不强依赖尚未提供的开发者 token | 只用单帖 fxtwitter、强制 API v2 |
| Telegram | 公开频道网页拉取；Bot API 管理频道协议预留 | Bot API 不能读取任意公开频道历史 | 把 Bot API 当历史接口 |
| 首次订阅 | 只建 baseline | 防止首次添加后刷屏 | 默认回补历史 |
| 点歌统计 | 专用事实表，只记最终成功点歌 | 审计标签不足以可靠聚合，且普通链接不应计数 | 复用 parse history 或审计标签 |
| 榜单 | 本地点歌榜与平台榜分离 | 两类热度含义不同 | 合并为单一分数 |
| 长尾订阅 | 保留统一协议，不创建空 adapter | 空实现制造虚假能力和维护噪声 | 为所有平台预建占位文件 |
| 前端 | 不修改 | 用户明确限定后端工作 | 同步重构卡片/UI |

## 14. 规格自检结论

- 无未决条目或待选架构分支。
- 方案 B、删除发布者人数、`subscriptions.sqlite3`/`subscriptions_old.sqlite3` 切换规则和轮询抖动均已纳入。
- 统一契约、平台解析、订阅、音乐统计和榜单的边界互不重叠。
- 所有不可公开数据都有明确空值与限制记录规则。
- 本规格可分解为一份逐文件实施计划；不需要再次扩大目标范围。
