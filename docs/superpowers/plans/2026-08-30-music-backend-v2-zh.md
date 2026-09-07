# 音乐元数据、点歌统计、音乐订阅与榜单实施计划

> **供执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用复选框（`- [ ]`）跟踪。
>
> 本文件是英文原计划 `2026-08-30-music-backend-v2.md` 的简体中文翻译。英文原文保持不变。

**目标：** 构建统一音乐后端，深化所有音乐解析器，只记录成功的机器人点歌行为，支持歌手/专辑/歌单/公开用户的增量订阅，并分别生成本地点歌榜和平台榜单快照。

**架构：** `contracts/music.py` 定义严格的 `MusicTrack` 元数据、贡献者和互动模型。`platforms_music.py` 改为 provider 客户端/归一化模块，返回包含音乐数据的 `ParsedContent`，并在共享工具之后实现每个平台端点。`MusicRequestStore` 将规范歌曲、平台别名、成功 `bot.music` 事件和榜单快照写入 `data/music_analytics.sqlite3`。各 `MusicSubscriptionAdapter` 接入订阅 V2，但不改变其调度器。`MusicChartRegistry` 严格分离机器人本地点歌排名和平台/分类榜单。

**技术栈：** Python 3.10+、Pydantic `StrictBaseModel`、stdlib `sqlite3`、`unicodedata`、`hashlib`、现有 HTTP 工具、可选平台凭据、通过订阅 V2 使用 APScheduler、pytest 离线 fixture、`PYTHONDONTWRITEBYTECODE=1`。

**规格：** `docs/superpowers/specs/2026-08-29-social-music-backend-v2-design.md`

## 全局约束

- 只有成功解析并选定歌曲的 `bot.music` 命令才计入点歌事件；音乐链接解析、订阅发现、榜单刷新和未找到搜索均不计数。
- provider 故障转移只记录最终选中的歌曲一次，不能为每个失败 provider 写一条事件。
- 默认不保存原始查询词或明文 requester ID；只保存 request ID、会话范围、时间、provider ID 和可选的带部署盐不可逆 requester hash。
- provider 缺失字段使用 `None`，不能写 0 或估算值；每个不可得字段都必须有 limitation/source 说明。
- 贡献者保留角色：演唱、合作演唱、作词、作曲、编曲、制作、混音/重混、指挥和其他；不能把所有人员压成一个“歌手”字符串。
- 规范歌曲匹配优先使用 ISRC，其次使用已确认的平台映射，最后使用保守的标题/音乐人/时长指纹；低置信匹配保留为不同歌曲。
- 不下载完整受版权保护音频，不绕过 DRM，不伪造登录凭据，不做播放可用性测试。
- 活跃订阅数据库仍固定为 `data/subscriptions.sqlite3`；旧订阅切换只由订阅 V2 计划处理。音乐分析数据库使用 `data/music_analytics.sqlite3`。
- 不得修改 UI、文案、HTML、CSS、卡片模板或图片渲染代码。
- 不扫描或修改 `ChatBot_Runtime`、`ChatBot_Archive` 或父目录。
- 未获得用户明确授权时不得创建 Git 提交。
- 使用 `scripts/dev.ps1 -Task test`、`scripts/dev.ps1 -Task lint`、`scripts/dev.ps1 -Task runtime-layout` 验证。

## 文件范围

### 模型和存储

- 新建：`plugins/bot_unified_runtime/contracts/music.py` —— `MusicTrack`、贡献者、专辑、歌词、试听、互动、可用性、点歌事件和榜单模型。
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py` —— 导出音乐模型。
- 新建：`plugins/bot_unified_runtime/sources/music_request_store.py` —— SQLite 分析存储和歌曲归并操作。
- 新建：`plugins/bot_unified_runtime/sources/music_normalization.py` —— 标题/艺术家/版本归一化、ISRC 和指纹匹配。

### Provider 解析和注册表

- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_music.py` —— provider 客户端、端点函数和 `ParsedContent` 音乐构造。
- 修改：`plugins/bot_unified_runtime/sources/parsers/__init__.py` —— 音乐 URL parser、搜索 provider 和音乐订阅 adapter 注册钩子。
- 修改：`plugins/bot_unified_runtime/sources/parsers/cookies.py` —— 仅添加合法使用的 provider Cookie 名称/域。
- 新建：`plugins/bot_unified_runtime/sources/music_providers.py` —— provider 能力声明和共享请求上下文。该模块从媒体计划引入 `FetchContext`，所以必须先执行媒体计划任务 2，再执行本计划任务 2–3。

### 点歌接入

- 修改：`plugins/bot_unified_runtime/capabilities/music.py` —— 注入 `MusicRequestStore`，最终选中 provider 后只写一次事件，现有输出行为保持不变。
- 修改：`plugins/bot_unified_runtime/config.py` —— 分析库路径、保留期限、provider 凭据和音乐订阅/榜单源设置。
- 修改：`.env.example` —— 仅添加后端音乐设置和可选 Spotify/Apple 凭据。

### 音乐订阅与榜单

- 新建：`plugins/bot_unified_runtime/sources/subscriptions/music_adapter.py` —— provider 级歌手/专辑/歌单/公开用户增量 adapter。
- 新建：`plugins/bot_unified_runtime/sources/music_charts.py` —— 本地点歌榜聚合和平台榜单源注册表。
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/__init__.py` —— 通过 V2 registry 发现音乐 adapter。

### 验证文件

- 新建：`tests/test_music_backend_v2.py` —— 模型、归一化、provider fixture、点歌事件语义和榜单。
- 新建：`tests/test_music_subscriptions_v2.py` —— 目标解析、增量游标和 provider 能力错误。

---

## 任务 1：定义严格音乐模型和规范化工具

**文件：**

- 新建：`plugins/bot_unified_runtime/contracts/music.py`
- 新建：`plugins/bot_unified_runtime/sources/music_normalization.py`
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py`
- 测试：`tests/test_music_backend_v2.py`

**核心模型：**

```python
class MusicContributor(StrictBaseModel):
    person_id: str | None = None
    name: str
    roles: list[str] = Field(default_factory=list)
    provider_payload: dict[str, Any] = Field(default_factory=dict)

class MusicAlbumRef(StrictBaseModel):
    provider_album_id: str | None = None
    name: str = ""
    artwork_url: str | None = None
    release_date: date | None = None

class MusicEngagement(StrictBaseModel):
    like_count: int | None = None
    heart_count: int | None = None
    favorite_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    popularity: int | float | None = None
    provider_extra: dict[str, int | float | str | None] = Field(default_factory=dict)

class MusicRequestEvent(StrictBaseModel):
    request_id: str
    canonical_track_id: str
    provider: str
    provider_track_id: str
    session_scope: str
    requested_at: datetime
    requester_hash: str | None = None

class MusicRankingEntry(StrictBaseModel):
    canonical_track_id: str
    title: str
    contributors: list[MusicContributor] = Field(default_factory=list)
    request_count: int
    last_requested_at: datetime
    provider_counts: dict[str, int] = Field(default_factory=dict)

class MusicChartEntry(StrictBaseModel):
    provider_track_id: str
    rank: int
    title: str = ""
    canonical_track_id: str | None = None

class MusicChartSnapshot(StrictBaseModel):
    snapshot_id: str
    source_id: str
    platform: str
    category: str
    region: str = ""
    source_type: str
    fetched_at: datetime
    entries: list[MusicChartEntry] = Field(default_factory=list)

class MusicTrack(StrictBaseModel):
    canonical_track_id: str | None = None
    provider: str
    provider_track_id: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    contributors: list[MusicContributor] = Field(default_factory=list)
    album: MusicAlbumRef | None = None
    artwork_url: str | None = None
    duration_ms: int | None = None
    release_date: date | None = None
    track_number: int | None = None
    disc_number: int | None = None
    isrc: str | None = None
    language: str | None = None
    genres: list[str] = Field(default_factory=list)
    explicit: bool | None = None
    lyrics: dict[str, str] = Field(default_factory=dict)
    preview_url: str | None = None
    audio_url: str | None = None
    availability: dict[str, Any] = Field(default_factory=dict)
    engagement: MusicEngagement = MusicEngagement()
    limitations: dict[str, str] = Field(default_factory=dict)
```

还要实现：

```python
normalize_music_text(...)
normalize_artist_names(...)
music_fingerprint(track)
canonical_key(track)
merge_provider_track(existing, incoming)
```

`canonical_key` 有 ISRC 时返回 `isrc:<大写ISRC>`；否则使用规范化标题、排序后的主要演唱者姓名和 ±5 秒时长桶生成 `fp:<sha256>`。`live`、`cover`、`remix`、`伴奏`、`instrumental`、`DJ` 等版本提示必须保留在指纹中，不能删掉。

- [ ] **步骤 1：写失败的模型和匹配测试**

测试必须覆盖：

1. 贡献者角色不被压平；
2. ISRC 优先于标题指纹；
3. 同名不同音乐人不会合并；
4. 负时长和负计数被拒绝；
5. 合并时保留别名/贡献者并保护高置信字段。

- [ ] **步骤 2：运行测试确认模型不存在**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONDONTWRITEBYTECODE='1'; .\ChatBot_Runtime\venv\Scripts\python.exe -m pytest tests/test_music_backend_v2.py -q"
```

预期：失败，因为新模块和模型尚未定义。

- [ ] **步骤 3：实现模型和保守匹配**

使用可空数值、无时区 `date` 表示发行日期、严格贡献者角色和 JSON 可序列化 provider extra。不能从 `like_count` 推导 `heart_count`。合并时联合别名/贡献者，只用更完整的非空字段补齐，不能用低置信值覆盖已验证值。

- [ ] **步骤 4：运行聚焦测试**

预期：通过。

## 任务 2：构建 Provider 能力声明和来源工具

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/music_providers.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/http_util.py`（若媒体计划尚未完成共享上下文）
- 修改：`plugins/bot_unified_runtime/sources/parsers/cookies.py`
- 测试：`tests/test_music_backend_v2.py`

**接口：**

```python
@dataclass(frozen=True)
class MusicProviderCapabilities:
    provider: str
    supports_search: bool
    supports_track: bool
    supports_artist: bool
    supports_album: bool
    supports_playlist: bool
    supports_public_user: bool
    supports_charts: bool

MUSIC_PROVIDER_CAPABILITIES: dict[str, MusicProviderCapabilities]

def build_music_context(provider: str, config: Any) -> FetchContext: ...
def require_capability(provider: str, capability: str) -> None: ...
```

- [ ] **步骤 1：增加失败的能力矩阵和 Cookie 测试**

验证 Apple Music 支持 track 但默认不支持 public user；验证不同平台 Cookie 不串用。

- [ ] **步骤 2：运行测试确认能力声明不存在**

预期：失败。

- [ ] **步骤 3：实现能力矩阵和 Cookie 绑定**

明确声明真实能力：

- 网易云：search、track、artist、album、playlist、public user、charts；
- QQ 音乐：search、track、artist、album、playlist；public user 只有在 fixture/API 实测通过时启用；charts 来自已配置公开源；
- 酷我：search、track、artist、album、playlist；public user/charts 只有数据源实测通过时启用；
- 酷狗：search、track、artist、album、playlist；public user/charts 只有数据源实测通过时启用；
- Apple/iTunes：search、track；公开 lookup 支持 artist/album；不支持 public user；charts 只能来自已配置源；
- Spotify：配置 Web API 凭据后支持 track、artist、album、playlist、public user、charts；oEmbed 只作为链接解析 fallback；
- YouTube Music：Innertube 明确识别为音乐时才填 track 字段；频道/歌单订阅复用 YouTube adapter。

只添加合法的 provider Cookie，例如网易云 `MUSIC_U`、QQ 音乐登录键、酷我/酷狗登录键、经授权客户端使用的 Spotify `sp_dc`。Pixiv Cookie 属于媒体解析计划，不在这里处理。

- [ ] **步骤 4：运行能力测试**

预期：通过。

## 任务 3：深化所有音乐 Provider 解析器

**文件：**

- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_music.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/__init__.py`
- 测试：`tests/test_music_backend_v2.py`

**接口：**

```python
def parse_music_url(url: str, context: FetchContext) -> ParsedContent: ...
def search_music(query: str, context: FetchContext) -> MusicTrack | None: ...
def fetch_music_track(provider: str, track_id: str, context: FetchContext) -> MusicTrack: ...

def fetch_netease_song_detail(song_id: str, context: FetchContext) -> MusicTrack: ...
def fetch_netease_song_comments(song_id: str, context: FetchContext) -> MusicEngagement: ...
def fetch_netease_song_aliases(song_id: str, context: FetchContext) -> list[str]: ...
def fetch_qq_track(mid: str, context: FetchContext) -> MusicTrack: ...
def fetch_kuwo_track(rid: str, context: FetchContext) -> MusicTrack: ...
def fetch_kugou_track(file_hash: str, context: FetchContext) -> MusicTrack: ...
def fetch_apple_track(track_id: str, context: FetchContext) -> MusicTrack: ...
def fetch_spotify_track(track_id: str, context: FetchContext) -> MusicTrack: ...
```

- [ ] **步骤 1：增加 provider fixture 测试**

网易云 fixture 必须验证：别名、作词/作曲等贡献者角色、时长、评论总数和公开收藏/热度字段。Apple fixture 必须验证平台不公开的收藏数是 `None`，并有 `provider_not_exposed` limitation。Spotify 未配置凭据时必须返回结构化 `auth_required`。

- [ ] **步骤 2：运行测试确认旧扁平输出失败**

预期：失败，因为当前 provider 只返回标题、歌手、专辑、封面和音频链接等基础字段。

- [ ] **步骤 3：实现网易云详情和公开互动查询**

使用现有歌曲详情请求获得身份、专辑、封面、时长、别名、演唱者和贡献者角色。增加以下独立 helper：

- 歌曲详情：`/api/song/detail` 或经过实测确认的替代端点；
- 歌词：`/api/song/lyric`；
- 评论：`/api/v1/resource/comments/R_SO_4_{id}` 或经过实测确认的等价端点，读取响应中的总数 `total`；
- 歌曲统计/收藏端点：只有端点明确返回平台级收藏/收录总数时才填 `favorite_count`；没有可靠端点时写 `None + provider_not_exposed`，不能用当前用户是否收藏代替全站收藏数；
- 专辑/歌单/歌手端点：服务音乐订阅和别名查询。

所有请求继承 Cookie/代理/超时上下文，来源只记录脱敏端点名。评论数使用响应总数，不能用本页评论条数代替。

- [ ] **步骤 4：实现 QQ、酷我、酷狗、Apple、Spotify 和 YouTube Music 映射**

映射 fixture 中所有可获得字段：全部音乐人及角色、专辑 ID/名称、封面、时长、发行日期、ISRC、语言、流派、explicit 标记、试听 URL 和公开互动数。不可得字段保持 `None + limitation`。酷我第三方搜索只能作为明确标注的搜索 fallback，不能作为权威详情来源。Spotify 只有配置 Web API 凭据时使用 Web API；Apple iTunes 的曲目/搜索保持匿名可用。

- [ ] **步骤 5：把 `MusicTrack` 映射到 `ParsedContent` 并更新注册表**

音乐 URL 返回：

```python
ParsedContent(identity.item_kind="music_track", music=track)
```

专辑/歌单链接分别使用 `identity.item_kind="album"/"playlist"`，集合数据放入 `content.platform_extra` 或正式集合模型。搜索 provider 返回 `MusicTrack` 给点歌能力。删除旧 `stats.music_card`，音频 URL 不作为必填字段。

- [ ] **步骤 6：运行 provider fixture 测试**

预期：全部通过且不发外网请求。

## 任务 4：增加分析数据库和规范歌曲 Upsert

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/music_request_store.py`
- 修改：`plugins/bot_unified_runtime/config.py`
- 修改：`.env.example`
- 测试：`tests/test_music_backend_v2.py`

**接口：**

```python
class MusicRequestStore:
    def __init__(self, db_path: str = "data/music_analytics.sqlite3", *, retention_days: int = 365) -> None: ...
    def upsert_track(self, track: MusicTrack) -> str: ...
    def record_successful_request(self, event: MusicRequestEvent) -> bool: ...
    def request_ranking(self, *, period: str, now: datetime) -> list[MusicRankingEntry]: ...
    def save_provider_chart(self, snapshot: MusicChartSnapshot) -> None: ...
    def close(self) -> None: ...
```

- [ ] **步骤 1：写失败的 Store 测试**

覆盖：相同 request ID 只写一次；相同 ISRC 的不同 provider 歌曲使用同一 canonical ID；同名不同音乐人不合并；日榜只统计时间窗口内事件。

- [ ] **步骤 2：运行测试确认 Store 不存在**

预期：失败。

- [ ] **步骤 3：实现 Schema 和规范 Upsert**

创建：

- `schema_meta`
- `music_tracks`
- `music_provider_tracks`
- `music_track_aliases`
- `music_request_events`
- `music_chart_snapshots`
- `music_chart_entries`

request ID 唯一。`upsert_track` 计算 canonical key，创建或更新规范歌曲行，写入 provider 映射，并保留 provider 专属 JSON 元数据；规范歌曲和 provider 映射必须在同一事务中写入。

- [ ] **步骤 4：实现保留期限和周期聚合**

`request_ranking(period="day"|"week"|"year")` 使用 UTC 半开区间，以 `now` 为锚点，按 canonical track 聚合，先按次数降序，再按最后点歌时间降序。返回最新规范元数据中的标题/音乐人。保留清理只删除超过 `retention_days` 的 request event，不删除歌曲元数据或榜单快照。

- [ ] **步骤 5：运行 Store 测试**

预期：通过。

## 任务 5：只记录最终成功的 `bot.music` 事件

**文件：**

- 修改：`plugins/bot_unified_runtime/capabilities/music.py`
- 修改：`plugins/bot_unified_runtime/config.py`
- 修改：`plugins/bot_unified_runtime/__init__.py`（只改能力依赖注入）
- 测试：`tests/test_music_backend_v2.py`

**接口：**

```python
def build_music_capability(
    config: Any | None = None,
    *,
    providers: list[Any] | None = None,
    default_mode: str = "card+voice+link",
    audio_downloader: Callable[[str], str | None] | None = None,
    request_store: MusicRequestStore | None = None,
) -> Any: ...
```

- [ ] **步骤 1：写事件边界测试**

测试 provider 故障转移后只记录最终成功 provider 一次；普通音乐链接解析不写事件；未找到歌曲不写成功事件。

- [ ] **步骤 2：运行测试确认没有事件记录器**

预期：失败。

- [ ] **步骤 3：在最终选中后写事件**

只有 `item = search_fn(query)` 返回最终非空结果后、返回 `CapabilityResult` 前，才把 V2 `MusicTrack` upsert 为 canonical track 并调用 `record_successful_request` 一次。记录 `message.request_id`、会话类型、provider ID 和 UTC 时间。不能在 provider 循环中提前写事件。分析库存储失败时，点歌结果仍正常返回，只写脱敏诊断事件。

- [ ] **步骤 4：运行时只创建一个 Store 实例**

每个 runtime 创建一个 `MusicRequestStore`，注入 `build_music_capability`，关闭 runtime 时关闭 store。增加：

```python
bot_music_analytics_enabled: bool
bot_music_analytics_db_path: str = "data/music_analytics.sqlite3"
bot_music_analytics_retention_days: int = 365
```

关闭分析时不能打开数据库。

- [ ] **步骤 5：运行事件边界测试**

预期：通过，现有点歌输出行为不变。

## 任务 6：实现音乐订阅 Adapter

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/subscriptions/music_adapter.py`
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/__init__.py`
- 修改：`plugins/bot_unified_runtime/sources/music_providers.py`
- 测试：`tests/test_music_subscriptions_v2.py`

**接口：**

```python
class MusicSubscriptionAdapter(SubscriptionAdapter):
    platform: str
    target_kinds: frozenset[str]
    async def resolve_target(self, raw_target: str, ctx: FetchContext) -> SubscriptionTarget: ...
    async def fetch_incremental(self, target: SubscriptionTarget, cursors: dict[str, SubscriptionCursor], ctx: FetchContext) -> SubscriptionFetchResult: ...
```

- [ ] **步骤 1：写目标/游标 fixture 测试**

覆盖网易云歌手、网易云歌单、Spotify 专辑等目标；验证歌单重新排序不会被误判为新歌。

- [ ] **步骤 2：运行测试确认 Adapter 不存在**

预期：失败。

- [ ] **步骤 3：实现显式 Provider 目标能力**

将歌手/专辑/歌单/公开用户目标 ID 解析到 `SubscriptionTarget.target_payload`。不支持的目标返回 `unsupported_target_kind` 或 `auth_required`。必须检查 provider 能力矩阵，不能只因正则命中 URL 就接受目标。

- [ ] **步骤 4：实现集合/成员增量轮询**

- 歌手与公开用户：抓取最新 track ID 和日期；
- 专辑：抓取曲目列表并检测新增；
- 歌单：比较成员 ID 集合，只把新出现的 ID 视为新歌，排序变化不是新增；
- 用户 feed：使用 provider 时间和 stream 游标。

返回：

```python
ContentReference(
    item_id=provider_track_id,
    item_kind="music_track",
    url=canonical_provider_url,
)
```

不同目标使用独立 stream 游标。订阅 V2 调度器只对新引用调用一次音乐 parser 深化。

- [ ] **步骤 5：增加各音乐 Provider Adapter**

实现网易云、QQ 音乐、酷我、酷狗、Apple/iTunes 的已声明能力；Spotify 只有配置 Web API 凭据时启用；YouTube Music 复用 YouTube 频道/歌单 adapter，并在条目明确识别为音乐后才设置 music 类型。任何私有用户访问都必须返回 `auth_required`，不能尝试匿名绕过。

- [ ] **步骤 6：运行音乐订阅测试**

预期：通过。

## 任务 7：实现本地点歌榜和平台榜单 Registry

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/music_charts.py`
- 修改：`plugins/bot_unified_runtime/sources/music_request_store.py`
- 修改：`plugins/bot_unified_runtime/config.py`
- 修改：`.env.example`
- 测试：`tests/test_music_backend_v2.py`

**接口：**

```python
class MusicChartSource(Protocol):
    source_id: str
    category: str
    async def fetch_snapshot(self, ctx: FetchContext) -> MusicChartSnapshot: ...

class MusicChartRegistry:
    def register(self, source: MusicChartSource) -> None: ...
    def list_sources(self, *, category: str | None = None) -> list[MusicChartSource]: ...
    async def refresh(self, source_id: str, ctx: FetchContext) -> MusicChartSnapshot: ...
```

- [ ] **步骤 1：写榜单分离测试**

验证本地日榜/周榜/年榜只使用点歌事件；平台榜单快照保留 category 和 `source_type`，其中 source type 只能是经过验证的 `official_chart` 或明确标记的 `curated_playlist`。

- [ ] **步骤 2：运行测试确认榜单代码不存在**

预期：失败。

- [ ] **步骤 3：实现本地点歌榜查询**

只通过分析库提供 day/week/year 排名。使用 UTC 半开区间，返回 canonical ID、标题、贡献者、provider 分布、点歌次数和最后点歌时间。平台播放/收藏数不能混入本地点歌次数。

- [ ] **步骤 4：实现平台榜单源 Registry**

每个榜单源包含：`source_id`、`platform`、`category`、`region`、`source_type`、`endpoint_or_chart_id`、`refresh_interval_seconds` 和异步 fetcher。通过配置注册 `二次元`、`电音`、`摇滚`、`日本音乐`。策展歌单必须标记 `source_type="curated_playlist"`；只有实测为官方榜单端点的来源才能标记 `official_chart`。快照保存抓取时间、平台排名、provider track ID 和可解析出的 canonical track ID。

- [ ] **步骤 5：增加配置，不改 UI**

增加：

```python
bot_music_chart_enabled
bot_music_chart_sources
bot_music_chart_poll_interval_seconds
```

以及 provider 凭据引用。不得增加帮助文案或改变命令输出。

- [ ] **步骤 6：运行榜单测试**

预期：通过。

## 任务 8：最终接入和验证

**文件：**

- 修改：`plugins/bot_unified_runtime/__init__.py` —— 构造音乐 store、adapter 和可选榜单调度器，不改 UI handler；
- 修改：`plugins/bot_unified_runtime/sources/parsers/__init__.py` —— 确保所有音乐 URL/search 项使用 V2 类型；
- 修改：`plugins/bot_unified_runtime/config.py` —— 校验路径和数值设置；
- 测试：两个 V2 音乐测试文件。

- [ ] **步骤 1：断言行为边界**

运行：

```powershell
rg -n "music_card|PlatformParse|record_successful_request|MusicRequestStore|MusicSubscriptionAdapter|request_ranking" plugins/bot_unified_runtime --glob '*.py'
```

预期：只剩 V2 模型/store 引用；`bot.content` 或普通 URL parser 无法触发点歌事件写入。

- [ ] **步骤 2：运行全部聚焦音乐测试**

预期：通过。

- [ ] **步骤 3：运行工作区三项验证**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task runtime-layout"
```

预期：全部通过，源码树不产生缓存。

- [ ] **步骤 4：检查最终文件边界**

运行 `git status --short` 和 `git diff --check`。确认只出现预期后端文件和工作区原有改动；没有 UI/template 文件修改，没有未经授权的暂存或提交。

## 完成检查清单

- [ ] 每个音乐 parser 在可识别时都返回包含 `MusicTrack` 的 V2 `ParsedContent`。
- [ ] 网易云返回别名、全部可得贡献者角色、时长、封面和公开评论/收藏指标或明确 limitations。
- [ ] QQ、酷我、酷狗、Apple、Spotify、YouTube Music 返回所有可得结构化元数据，不伪造值。
- [ ] 只有成功的 `bot.music` 结果创建点歌事件，并且每个 request 只写一次。
- [ ] 相同 ISRC 的跨平台歌曲共用一个 canonical track；同名不同音乐人保持分离。
- [ ] 本地日榜/周榜/年榜只使用机器人点歌事实。
- [ ] 平台分类榜保留来源类型和平台排名。
- [ ] 已支持的歌手/专辑/歌单/公开用户目标可以检测新歌。
- [ ] 音乐订阅轮询复用订阅 V2 的抖动、限流、租约和退避。
- [ ] 没有修改 UI、文案、HTML、CSS、卡片模板或图片渲染代码。
- [ ] test、lint、runtime-layout 全部通过。
