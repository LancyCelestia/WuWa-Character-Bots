# 订阅 V2 与社交平台 Adapter 实施计划

> **供执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用复选框（`- [ ]`）跟踪。
>
> 本文件是英文原计划 `2026-08-30-subscription-v2-and-social-adapters.md` 的简体中文翻译。英文原文保持不变。

**目标：** 用新的持久化订阅 V2 调度器替换尚未完成的订阅流水线，并为 Bilibili、小红书、YouTube、X/Twitter、公开 Telegram 频道、Pixiv 和微博实现完整的增量订阅 adapter。

**架构：** `contracts/subscription.py` 定义 V2 的订阅目标、游标、内容引用、抓取结果、推送目的地和 outbox 契约。`SubscriptionStore` 将目标、游标、已见条目、租约、失败状态和 outbox 持久化到 `data/subscriptions.sqlite3`；首次启动 V2 前，如果该路径存在旧 schema，则原子保留为 `data/subscriptions_old.sqlite3`，且禁止覆盖已有备份。`SubscriptionScheduler` 负责每个目标的抖动、平台/全局并发、重试/退避和首次基线；adapter 只负责目标解析和增量引用获取。

**技术栈：** Python 3.10+、Pydantic `StrictBaseModel`、stdlib `sqlite3`、`asyncio`、`xml.etree.ElementTree`、现有 HTTP 工具、现有 Playwright 后端、APScheduler、pytest fixture、`PYTHONDONTWRITEBYTECODE=1`。

**规格：** `docs/superpowers/specs/2026-08-29-social-music-backend-v2-design.md`

## 全局约束

- 使用全新的 V2 schema；不得读取、迁移或合并旧 schema 中的行。
- V2 活跃数据库路径固定为 `data/subscriptions.sqlite3`；原有旧文件只允许保留为 `data/subscriptions_old.sqlite3`。
- 改名必须受保护：如果 `subscriptions_old.sqlite3` 已存在，立即停止并报告不可重试的迁移冲突，禁止覆盖；如果 V2 schema 创建失败，不得破坏旧文件。
- 新目标第一次成功轮询只建立基线，不产生推送事件。
- 后续所有条目必须由数据库按 `(target_id, item_kind, item_id)` 去重，不能只依赖进程内存。
- 每个 HTTP/Playwright 请求都必须接收超时、代理、Cookie、User-Agent、trace ID 和平台限流上下文；凭据不能进入日志、载荷或错误信息。
- 必须具备目标级抖动、平台并发、全局并发、最小请求间隔、租约、指数退避和 `Retry-After`；只设置 APScheduler 任务级 jitter 不够。
- 必须实现的订阅源是 Bilibili、小红书、YouTube、X/Twitter、公开 Telegram 频道、Pixiv 和微博；长尾平台在本计划中只保留解析器，不做订阅抓取。
- Telegram 指公开频道源轮询（`t.me/s/<username>`）；Bot API 管理频道是明确预留的协议边界，不能假称 Bot API 能读取任意历史。
- X/Twitter 使用已授权的 `auth_token`/`ct0` Cookie 和配置代理访问网页 GraphQL；不能在配置会话之外尝试发现凭据。
- 不得修改 UI、文案、HTML、CSS、卡片模板或图片渲染代码；现有命令文案保持不变。
- 不扫描或修改 `ChatBot_Runtime`、`ChatBot_Archive` 或父目录。
- 未获得用户明确授权时不得创建 Git 提交。
- 使用 `scripts/dev.ps1 -Task test`、`scripts/dev.ps1 -Task lint` 和 `scripts/dev.ps1 -Task runtime-layout` 验证。

## 文件范围

### V2 契约和持久化

- 修改：`plugins/bot_unified_runtime/contracts/subscription.py` —— 用 V2 模型和 adapter 协议替换未完成的订阅模型。
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py` —— 导出 V2 订阅契约。
- 新建：`plugins/bot_unified_runtime/sources/subscription_migration.py` —— 安全的旧文件改名和 V2 schema 初始化。
- 修改：`plugins/bot_unified_runtime/sources/subscription_store.py` —— V2 SQLite 存储和事务性租约/outbox 操作。
- 新建：`plugins/bot_unified_runtime/sources/subscription_scheduler.py` —— 抖动、限流、重试、基线和 adapter 编排。
- 修改：`plugins/bot_unified_runtime/config.py` —— V2 数据库和调度参数。
- 修改：`.env.example` —— 仅添加后端 V2 配置项。

### Adapter 注册和共享工具

- 修改：`plugins/bot_unified_runtime/sources/subscriptions/__init__.py` —— 发现 V2 `ADAPTERS`、校验能力声明、异步解析目标。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/common.py` —— 游标排序、公开计数/时间解析和引用构造工具。
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/bilibili_adapter.py` —— V2 引用 adapter 和持久化直播场次游标。
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/xiaohongshu_adapter.py` —— V2 引用 adapter 和带总数信息的游标。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/youtube_adapter.py` —— 频道/歌单 Atom feed adapter。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/twitter_adapter.py` —— 已授权的 X 网页 GraphQL 时间线 adapter。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/telegram_adapter.py` —— 公开频道 HTML adapter。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/pixiv_adapter.py` —— 创作者/小说创作者 AJAX adapter。
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/weibo_adapter.py` —— 博主时间线 adapter。

### 运行时接入

- 修改：`plugins/bot_unified_runtime/capabilities/subscribe.py` —— 使用 V2 目标、存储和 registry 契约，不改变命令文案。
- 修改：`plugins/bot_unified_runtime/__init__.py` —— 初始化 V2 store、调度器、adapter 深化器和 outbox 投递；不改变投递序列化/UI。
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_weibo.py` —— 如果媒体解析计划尚未完成上下文透传，则在此修复微博长文请求。

Telegram adapter 同时需要暴露 `TelegramManagedChannelBackend` 协议边界，为未来 Bot API 事件接入预留接口；本计划只实现公开 HTML 轮询。

### 验证文件

- 新建：`tests/test_subscription_v2.py` —— schema 迁移、存储事务、抖动、租约、退避和基线。
- 新建：`tests/test_subscription_adapters_v2.py` —— 七个平台目标和 fixture 解析。
- 新建：`tests/test_subscription_runtime_v2.py` —— 调度器初始化和假传输 outbox 边界。

---

## 任务 1：用 V2 模型替换订阅契约

**文件：**

- 修改：`plugins/bot_unified_runtime/contracts/subscription.py`
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py`
- 测试：`tests/test_subscription_v2.py`

**接口：**

```python
class SubscriptionTarget(StrictBaseModel):
    id: str
    platform: str
    target_kind: str
    target_key: str
    display_name: str = ""
    target_payload: dict[str, Any] = Field(default_factory=dict)
    source_mode: str = "pull"
    enabled: bool = True
    health_state: str = "healthy"
    base_interval_seconds: int = 300
    jitter_ratio: float = 0.20
    baseline_initialized: bool = False
    next_poll_at: datetime | None = None
    lease_until: datetime | None = None
    failure_count: int = 0
    backoff_until: datetime | None = None
    created_at: datetime
    updated_at: datetime

class SubscriptionCursor(StrictBaseModel):
    target_id: str
    stream: str = "default"
    last_item_id: str = ""
    last_timestamp: datetime | None = None
    cursor_payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime

class ContentReference(StrictBaseModel):
    item_id: str
    item_kind: str
    url: str
    published_at: datetime | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)

class SubscriptionFetchResult(StrictBaseModel):
    items: list[ContentReference] = Field(default_factory=list)
    cursors: list[SubscriptionCursor] = Field(default_factory=list)
    health_state: str = "healthy"
    error_code: str = ""
    retryable: bool = False
    retry_after_seconds: int | None = None
    suggested_interval_seconds: int | None = None

class SubscriptionDestination(StrictBaseModel):
    id: str
    target_id: str
    transport: str
    scope: str
    destination_id: str
    bot_id: str = ""
    enabled: bool = True
    digest_enabled: bool = False

class SubscriptionOutboxEvent(StrictBaseModel):
    event_id: str
    target_id: str
    item: ContentReference
    reason: str
    state: str = "pending"
    attempts: int = 0
    next_attempt_at: datetime
    created_at: datetime
```

`SubscriptionAdapter` 必须定义 `platform`、`target_kinds: frozenset[str]`、`async resolve_target(raw_target: str, ctx: FetchContext) -> SubscriptionTarget` 和 `async fetch_incremental(target: SubscriptionTarget, cursors: dict[str, SubscriptionCursor], ctx: FetchContext) -> SubscriptionFetchResult`。可执行的 V2 代码中删除旧的 `NormalizedSubscriptionItem`、`PushCandidate` 和同步 `fetch_latest` 协议引用，不添加旧模型别名。

- [ ] **步骤 1：写失败的模型测试**

测试一个带明确目标 ID/目标类型的 YouTube 目标，以及一个带明确条目类型/条目 ID 的内容引用。

- [ ] **步骤 2：运行测试确认旧契约失败**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONDONTWRITEBYTECODE='1'; .\ChatBot_Runtime\venv\Scripts\python.exe -m pytest tests/test_subscription_v2.py -q"
```

预期：失败，因为 V2 模型和字段尚未定义。

- [ ] **步骤 3：实现 V2 Pydantic 契约**

使用带时区的 `datetime`；拒绝空 ID 和负间隔；将 `jitter_ratio` 限制在 `0 <= value <= 1`；让 `source_payload` 中的平台可选数据支持空值。导出 V2 契约，不为被删除的旧模型增加别名。

- [ ] **步骤 4：运行聚焦测试**

预期：`tests/test_subscription_v2.py` 中的契约测试通过。

## 任务 2：实现安全数据库切换和 V2 Store

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/subscription_migration.py`
- 修改：`plugins/bot_unified_runtime/sources/subscription_store.py`
- 测试：`tests/test_subscription_v2.py`

**接口：**

```python
def prepare_subscription_database(primary_path: str) -> str: ...

class SubscriptionStore:
    def __init__(self, db_path: str = "data/subscriptions.sqlite3") -> None: ...
    @property
    def db_path(self) -> str: ...
    def upsert_target(self, target: SubscriptionTarget) -> None: ...
    def get_target(self, target_id: str) -> SubscriptionTarget | None: ...
    def list_targets(self, *, due_before: datetime | None = None) -> list[SubscriptionTarget]: ...
    def claim_due_target(self, target_id: str, now: datetime, lease_seconds: int) -> bool: ...
    def release_target(self, target_id: str, *, next_poll_at: datetime) -> None: ...
    def get_cursors(self, target_id: str) -> dict[str, SubscriptionCursor]: ...
    def save_fetch_result(self, target: SubscriptionTarget, result: SubscriptionFetchResult, *, baseline: bool) -> list[SubscriptionOutboxEvent]: ...
    def record_failure(self, target_id: str, error_code: str, *, retry_at: datetime) -> None: ...
    def claim_outbox(self, now: datetime, limit: int) -> list[SubscriptionOutboxEvent]: ...
    def mark_outbox_sent(self, event_id: str, sent_at: datetime) -> None: ...
    def mark_outbox_retry(self, event_id: str, next_attempt_at: datetime) -> None: ...
```

- [ ] **步骤 1：写迁移和事务存储测试**

测试必须覆盖：

1. 已有 `subscriptions.sqlite3` 且无备份时，会被安全改名为 `subscriptions_old.sqlite3`，然后创建新的主库；
2. `subscriptions_old.sqlite3` 已存在时，主库和备份都保持不变，并抛出迁移冲突；
3. 相同条目第二次保存时不会产生第二个 seen item 或 outbox event；
4. 基线保存不产生 outbox，后续轮询才产生 outbox。

示例：

```python
connection = sqlite3.connect(primary)
connection.execute("CREATE TABLE subscriptions(id TEXT)")
connection.commit()
connection.close()
assert prepare_subscription_database(str(primary)) == str(primary)
assert backup.exists()
assert primary.exists()
```

- [ ] **步骤 2：运行测试确认 migration/store 不存在**

预期：失败，因为迁移工具和 V2 Store 操作尚未实现。

- [ ] **步骤 3：实现受保护的切换流程**

`prepare_subscription_database(primary_path)` 必须：

1. 解析父目录，并使用独占锁文件；
2. 如果主库已有 V2 `schema_meta(version=2)`，直接返回，不重复切换；
3. 如果主库存在旧 `subscriptions` 表但没有 V2 标记，检查 `subscriptions_old.sqlite3`、`-wal` 和 `-shm` 均不存在，再持锁用 `os.rename` 改名；任何目标文件已存在都必须在改名前报错；
4. 如果主库不存在，在同目录创建临时 SQLite 文件，初始化 V2 schema、执行 fsync，再原子改名为主库；
5. schema/bootstrap 失败时只删除临时文件，保留旧主库或旧备份。

旧库改名不能使用可能覆盖目标的 `os.replace`。

- [ ] **步骤 4：实现 V2 schema 和事务操作**

创建 `schema_meta`、`subscription_targets`、`subscription_destinations`、`subscription_cursors`、`subscription_seen_items`、`subscription_outbox` 和 `subscription_poll_log`。增加以下唯一约束：目标身份、游标 `(target_id, stream)`、已见条目 `(target_id, item_kind, item_id)`、outbox `(target_id, item_kind, item_id, reason)`。`save_fetch_result` 必须在一个事务中写入 seen item 和 outbox，只在条目处理完成后更新游标；基线抓取只标记 `baseline_initialized`，不产生 outbox。

- [ ] **步骤 5：运行迁移/存储测试**

预期：全部通过，并证明已有 `subscriptions_old.sqlite3` 时不会被覆盖。

## 任务 3：增加目标级抖动、限流、租约和重试编排

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/subscription_scheduler.py`
- 修改：`plugins/bot_unified_runtime/config.py`
- 修改：`.env.example`
- 测试：`tests/test_subscription_v2.py`

**接口：**

```python
class PlatformThrottle:
    def __init__(self, *, per_platform_limit: int, global_limit: int, min_interval_seconds: float) -> None: ...
    async def run(self, platform: str, operation: Callable[[], Awaitable[T]]) -> T: ...

class SubscriptionScheduler:
    async def poll_due_once(self, *, now: datetime | None = None) -> list[SubscriptionOutboxEvent]: ...
    async def deliver_outbox_once(self, *, limit: int = 20) -> int: ...
    def next_poll_at(self, target: SubscriptionTarget, *, now: datetime, random_value: float) -> datetime: ...
```

- [ ] **步骤 1：写抖动和退避失败测试**

测试目标级抖动范围、首次基线不推送、第二次轮询推送，以及 `Retry-After` 优先于指数退避。

抖动测试应使用固定时间和 `random_value=0.0/1.0`，验证 `base_interval_seconds=300`、`jitter_ratio=0.20` 时执行时间位于 240–360 秒范围内。

- [ ] **步骤 2：运行测试确认调度器不存在**

预期：失败，因为 `SubscriptionScheduler` 和 `PlatformThrottle` 尚未实现。

- [ ] **步骤 3：实现稳定错峰和每轮抖动**

使用 `hashlib.blake2b(target.id.encode(), digest_size=8)` 从目标 ID 派生区间内的稳定相位；使用注入的 `[0, 1]` 随机值计算 `uniform(-window, +window)`。下一次执行时间至少为 `now + 1 秒`。目标 ID 不能成为所有周期永久固定的执行时间，每一轮都要有新的抖动。

- [ ] **步骤 4：实现限流和数据库租约**

使用一个全局 `asyncio.Semaphore`、每个平台一个 semaphore 和每个平台的单调时钟最近请求时间。`PlatformThrottle.run` 在等待最小间隔时不能占用 semaphore；请求本身完成后立即释放。调用 adapter 前原子领取目标租约；有其他 worker 持有有效租约时跳过。无论成功还是异常，都必须在 `finally` 中释放租约并持久化下一次抖动时间。

- [ ] **步骤 5：实现重试和健康状态迁移**

把 adapter 结果映射为 `healthy`、`degraded`、`auth_required`、`rate_limited`、`blocked`、`unsupported` 和 `paused`。可重试失败使用 `min(cap, base * 2**failure_count) + full_jitter`；若存在 `retry_after_seconds`，严格使用该值。认证失败、验证码、私有内容和不支持的能力不能进入短周期重试循环。轮询日志只保存错误码和计数。

- [ ] **步骤 6：增加配置字段**

增加以下后端配置，旧备份路径不作为配置项，而是由主路径同目录固定派生为 `subscriptions_old.sqlite3`：

```python
bot_subscribe_db_path: str = "data/subscriptions.sqlite3"
bot_subscribe_jitter_ratio: float = 0.20
bot_subscribe_global_concurrency: int = 3
bot_subscribe_platform_concurrency: int = 1
bot_subscribe_min_interval_seconds: float = 1.0
bot_subscribe_lease_seconds: int = 120
bot_subscribe_retry_base_seconds: int = 60
bot_subscribe_retry_cap_seconds: int = 1800
bot_subscribe_outbox_batch_size: int = 20
```

保留现有轮询间隔作为目标默认间隔，不添加 UI 文案。

- [ ] **步骤 7：运行调度器测试**

预期：通过。

## 任务 4：更新 adapter 发现和共享引用工具

**文件：**

- 修改：`plugins/bot_unified_runtime/sources/subscriptions/__init__.py`
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/common.py`
- 测试：`tests/test_subscription_adapters_v2.py`

**接口：**

```python
class SubscriptionRegistry:
    def register(self, adapter: SubscriptionAdapter) -> None: ...
    def find(self, platform: str) -> SubscriptionAdapter | None: ...
    async def resolve_target(self, raw_target: str, ctx: FetchContext) -> SubscriptionTarget: ...
    def list_adapters(self) -> list[SubscriptionAdapter]: ...
```

- [ ] **步骤 1：写发现和工具测试**

测试重复平台注册会失败，公开引用具备稳定的去重身份，时间/数量解析可以处理平台字符串格式。

- [ ] **步骤 2：运行测试确认 registry 仍是旧协议**

预期：失败，因为当前 registry 是同步/旧协议。

- [ ] **步骤 3：实现 V2 发现机制**

自动导入 `*_adapter.py`，要求模块级 `ADAPTERS` 列表；校验 platform 唯一、`target_kinds` 非空，并提供异步目标解析。不得保留旧的四键 dict 截断；adapter 必须返回带 `target_payload` 的完整 `SubscriptionTarget`。

- [ ] **步骤 4：实现共享解析工具**

添加 `parse_public_int`、`parse_iso_datetime`、`filter_newer_references`、`stable_item_id` 和 `make_content_reference`。当游标条目不在有限 feed 中时，`filter_newer_references` 使用发布时间和数据库已见条目继续判断，而不是丢弃整页。Telegram/微博置顶条目按显式标记过滤，不能按列表位置猜测。

- [ ] **步骤 5：运行发现测试**

预期：通过。

## 任务 5：迁移 Bilibili 和小红书 Adapter 到 V2

**文件：**

- 修改：`plugins/bot_unified_runtime/sources/subscriptions/bilibili_adapter.py`
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/xiaohongshu_adapter.py`
- 测试：`tests/test_subscription_adapters_v2.py`

**接口：**

- `BilibiliAdapter.platform == "bilibili"`，目标类型为 `creator`、`live_room`、`bangumi`、`favorite`、`collection`；
- `XiaohongshuAdapter.platform == "xiaohongshu"`，目标类型为 `creator`；
- 两者都实现 `resolve_target(raw_target, ctx)` 和 `fetch_incremental(target, cursors, ctx)`。

- [ ] **步骤 1：增加目标解析和游标 fixture 测试**

覆盖：Bilibili 空间、直播间和小红书用户主页；验证 Bilibili 直播场次游标持久化后，重启/第二次抓取不会把同一场次重复视为新事件。

- [ ] **步骤 2：运行 adapter 测试确认旧协议失败**

预期：失败，因为旧 adapter 返回旧条目形状，直播状态只在内存中保存。

- [ ] **步骤 3：重写 Bilibili 结果归一化**

复用现有 WBI、view、feed、PGC、收藏夹、合集和直播接口。返回只包含规范 URL 和已脱敏 ID 的 `ContentReference`。视频、动态、剧集、合集和直播场次分别使用独立 stream；直播场次 ID 写入 `cursor_payload`，不能把实例字典作为唯一边沿检测状态。

- [ ] **步骤 4：重写小红书结果归一化**

保留 `/api/sns/web/v1/user_posted` 的 `capture_json` 和 HTML fallback。将 `note_id`、类型、标题、发布时间和规范 URL 映射为引用。如果接口明确返回 `user_posted.total`，则写入游标 payload；没有 total 时仍返回健康引用，同时记录限制，不把当前页条数当作用户笔记总数。

- [ ] **步骤 5：运行 Adapter fixture 测试**

预期：Bilibili 和小红书测试通过。

## 任务 6：实现 YouTube 和公开 Telegram Adapter

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/subscriptions/youtube_adapter.py`
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/telegram_adapter.py`
- 测试：`tests/test_subscription_adapters_v2.py`

**接口：**

- YouTube 目标类型：`channel`、`playlist`；支持 `/channel/UC...`、`/@handle`、`/playlist?list=...`、`youtube:channel:<id>`、`youtube:playlist:<id>`；
- Telegram 目标类型：`public_channel`；支持 `https://t.me/s/<username>`、`https://t.me/<username>/<message_id>`、`telegram:public_channel:<username>`。

- [ ] **步骤 1：写 Atom/HTML fixture 测试**

YouTube fixture 验证 video ID、发布时间、URL 和游标；Telegram fixture 验证置顶旧帖被排除、较新消息保留；私有邀请链接必须抛出 `ParseFailure`。

- [ ] **步骤 2：运行 fixture 确认新 Adapter 不存在**

预期：失败，因为新模块和 fixture 解析函数尚未实现。

- [ ] **步骤 3：实现 YouTube Atom 客户端**

使用：

```text
https://www.youtube.com/feeds/videos.xml?channel_id={id}
https://www.youtube.com/feeds/videos.xml?playlist_id={id}
```

`@handle` 只在首次解析时通过频道页/Innertube bootstrap 解析频道 ID，并写入 `target_payload`，之后不能每轮重复解析。解析 entry 的 video ID、标题、URL、`published` 和 `updated`。新引用由调度器的深化器调用 V2 YouTube parser，补齐简介、时长、作者指标和媒体。

- [ ] **步骤 4：实现公开 Telegram HTML 客户端**

使用 Telegram User-Agent 抓取 `https://t.me/s/{username}`。解析 `data-post`、消息 ID、时间、正文、图片/视频预览 URL、页面显示的浏览量、反应和转发数。游标不在当前有限页面时，才使用保存在 `cursor_payload` 的 `before` 分页参数。按页面显式 pinned 标记排除置顶消息。拒绝邀请 hash 和私有用户名；不能调用 Bot API 历史接口。

- [ ] **步骤 5：运行 YouTube/Telegram 测试**

预期：通过。

## 任务 7：实现 X/Twitter、Pixiv 和微博 Adapter

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/subscriptions/twitter_adapter.py`
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/pixiv_adapter.py`
- 新建：`plugins/bot_unified_runtime/sources/subscriptions/weibo_adapter.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_weibo.py`（确保上下文透传）
- 测试：`tests/test_subscription_adapters_v2.py`

**接口：**

- X 目标类型：`creator`；支持 `https://x.com/<handle>`、`https://twitter.com/<handle>`、`twitter:creator:<handle>`；
- Pixiv 目标类型：`creator`、`novel_creator`、`novel_series`；支持 `/users/<uid>`、`pixiv:creator:<uid>` 和系列链接；
- 微博目标类型：`creator`；支持 `https://weibo.com/u/<uid>`、`https://weibo.com/<uid>`、`weibo:creator:<uid>`。

- [ ] **步骤 1：写已授权时间线 fixture 测试**

测试 X GraphQL fixture 能过滤回复并保留数字游标；Pixiv 能将插画和小说分为独立 stream；微博能排除显式置顶微博。

- [ ] **步骤 2：运行聚焦测试确认新 Adapter 不存在**

预期：失败，因为新客户端和 fixture 解析函数尚未实现。

- [ ] **步骤 3：实现已授权的 X GraphQL 时间线客户端**

使用配置的 `TwitterGraphQLBackend`，操作名为 `UserTweets` 和 `UserTweetsAndReplies`，由客户端组装 query ID、feature flags 和 `variables`。handle 只在首次解析时换成 rest ID，并写入 `target_payload`。只有配置中的 `auth_token`/`ct0` 通过 `FetchContext` 发送，所有请求都传代理。解析推文节点、数字 status ID、时间、作者 handle、回复/转发/引用关系和媒体引用。如果 query ID 或响应结构无效，返回 `upstream_changed`/`auth_required`，不能转为未授权匿名抓取，也不能把空响应静默当作无更新。

- [ ] **步骤 4：实现 Pixiv AJAX 时间线客户端**

先给 Cookie provider 增加 `.pixiv.net` 和 `PHPSESSID`，再调用 `/ajax/user/{uid}/profile/all`。维护 `illust`、`manga` 和 `novel` 三个 stream；在详情查询后按服务端 `createDate`/`uploadDate` 排序，不能用作品 ID 数值代替时间。游标 payload 只保存 ID 和时间；新 ID 由 V2 parser 深化为完整媒体与作者字段。

- [ ] **步骤 5：实现微博时间线客户端**

使用 `m.weibo.cn/api/container/getIndex` 和微博 parser 已要求的移动 XHR 头；PC `weibo.com/ajax/profile/info` 只用于作者补充。首次解析时保存 container ID；排除显式置顶条目；返回带时间的 status ID/BID。微博长文本详情必须继承初始请求的 Cookie、代理、超时和 trace 上下文。

- [ ] **步骤 6：运行三个 Adapter fixture 套件**

预期：通过，且序列化后的引用中不出现凭据。

## 任务 8：接入 V2 命令、运行时初始化和 outbox 投递

**文件：**

- 修改：`plugins/bot_unified_runtime/capabilities/subscribe.py`
- 修改：`plugins/bot_unified_runtime/__init__.py`
- 修改：`plugins/bot_unified_runtime/sources/subscription_scheduler.py`
- 测试：`tests/test_subscription_runtime_v2.py`

**接口：**

```python
def build_subscribe_capability(*, store: SubscriptionStore, registry: SubscriptionRegistry, config: Config) -> Callable: ...

def build_subscription_runtime(*, config: Config, parser_registry: dict[str, Any], bot_provider: Callable[[], Any] | None) -> dict[str, Any]: ...
```

- [ ] **步骤 1：写初始化和目的地安全测试**

测试运行时使用 `subscriptions.sqlite3` 主路径，并验证 Telegram transport 不会被误当成 OneBot 目的地发送；没有对应 sender 时，outbox 标记为 `blocked_transport`。

- [ ] **步骤 2：运行聚焦运行时测试确认旧初始化失败**

预期：失败，因为当前运行时仍创建旧 store/watcher，且假定所有目的地都是 OneBot。

- [ ] **步骤 3：用 V2 组件替换订阅初始化**

更新 `_register_subscription_scheduler`，调用 `prepare_subscription_database`，构造 `SubscriptionStore`、`SubscriptionRegistry`、`SubscriptionScheduler` 和注入式 parser 深化器。注册一个短周期 APScheduler 唤醒任务，只领取到期目标；不产生全局突发。日报能力只有在 V2 digest 开启时才保留。

- [ ] **步骤 4：更新命令持久化，不改变命令文案**

让 `subscribe add` 调用异步 `registry.resolve_target`，保存返回的 `SubscriptionTarget` 并创建 V2 destination 行。list/pause/resume/remove/check 按 target ID 和健康状态操作。保留现有公开命令字符串和回复文本；这里只改存储和后端调用。

- [ ] **步骤 5：实现 outbox 深化和安全 transport 边界**

每个 outbox 引用只调用一次 parser registry，并把 `ParsedContent` 投影保存到 outbox payload。只有注册了 sender 的 transport 才投递；OneBot 继续使用现有 sender；不支持的 transport 标记为 `blocked_transport`，只有配置改变后才允许重试。绝不能把 Telegram 源频道 ID 解读为 OneBot 目的地 ID。

- [ ] **步骤 6：运行运行时测试**

预期：运行时、V2 store 和七个平台 adapter 测试全部通过。

## 任务 9：删除可执行旧订阅路径并完成验证

**文件：**

- 修改：`plugins/bot_unified_runtime/sources/subscription_store.py`
- 修改：`plugins/bot_unified_runtime/sources/subscription_watcher.py` —— 只有仍有导入时才修改；确认无引用后删除旧可执行文件。
- 修改：`plugins/bot_unified_runtime/sources/subscriptions/__init__.py`
- 修改：`plugins/bot_unified_runtime/__init__.py`
- 测试：三个 V2 订阅测试文件。

- [ ] **步骤 1：搜索已删除的可执行接口**

运行：

```powershell
rg -n "NormalizedSubscriptionItem|PushCandidate|fetch_latest|build_subscription_watcher|subscriptions_v2\.sqlite3|bot_subscribe_old_db_path|SubscriptionStore\(" plugins/bot_unified_runtime --glob '*.py'
```

预期：只剩 V2 引用，以及有意保留的 `subscriptions_old.sqlite3` 路径；运行时代码不再导入旧 watcher 或旧模型。

- [ ] **步骤 2：运行全部 V2 订阅测试**

预期：通过。

- [ ] **步骤 3：运行工作区三项验证**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task runtime-layout"
```

预期：全部通过，源码树无缓存文件。

- [ ] **步骤 4：检查最终 diff 边界**

运行 `git diff --check` 和 `git status --short`，确认没有 UI/template 文件被修改，也没有未经授权的暂存或提交。

## 完成检查清单

- [ ] `subscriptions.sqlite3` 是 V2 数据库路径。
- [ ] 旧主库安全保留为 `subscriptions_old.sqlite3`，且不会覆盖已有备份。
- [ ] 七个必需社交订阅 adapter 都能解析目标并产出增量引用。
- [ ] 基线、游标、已见条目、租约、重试、健康状态和 outbox 能跨进程重启保留。
- [ ] 轮询具备目标级抖动和平台/全局限流。
- [ ] X/Twitter 不会退回未授权匿名时间线抓取。
- [ ] Telegram 只处理公开频道页面，不虚构 Bot API 历史读取能力。
- [ ] 可执行旧订阅协议已删除。
- [ ] 没有修改 UI、文案、HTML、CSS 或图片渲染代码。
- [ ] test、lint、runtime-layout 全部通过。
