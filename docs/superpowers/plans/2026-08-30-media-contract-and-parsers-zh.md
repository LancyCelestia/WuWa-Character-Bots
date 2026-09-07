# 统一媒体契约与解析器迁移实施计划

> **供执行代理使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用复选框（`- [ ]`）跟踪。
>
> 本文件是英文原计划 `2026-08-30-media-contract-and-parsers.md` 的简体中文翻译。英文原文保持不变。

**目标：** 用一个严格的 `ParsedContent` 模型替换尚未完成的 `PlatformParse`/旧字典契约，并让所有已注册内容解析器返回该模型，同时不改变 UI 模板或渲染标记。

**架构：** `contracts/media.py` 作为权威的类型模型；它从 `contracts/music.py` 引入唯一的 `MusicTrack`，使音乐元数据在解析器、点歌、订阅和榜单之间共享。解析器直接返回 `ParsedContent`，并共享 `FetchContext`、`SourceProvenance` 和结构化 `ParseFailure` 语义。内容能力层和渲染边界只通过后端投影消费新模型，HTML/CSS/模板保持不变。

**依赖顺序：** 先执行 `2026-08-30-music-backend-v2.md` 的任务 1（创建 `contracts/music.py`），再执行本计划。后续媒体任务都依赖该模型。`ParseFailure` 只在本计划任务 2 的 `sources/parsers/context.py` 中定义一次，所有解析器和测试统一导入它。

**技术栈：** Python 3.10+、现有 `StrictBaseModel` 使用的 Pydantic、stdlib `dataclasses`、现有 `urllib` HTTP 工具、已有的平台 Playwright 后端、pytest fixture、`PYTHONDONTWRITEBYTECODE=1`。

## 全局约束

- 不保留、也不新增 `PlatformParse`、`stats` 或非正式 `detail` 字典的运行时兼容路径。
- 所有已注册解析器必须返回 `ParsedContent`；拿不到的字段使用 `None`，并在 `provenance.limitations` 中说明，不能伪造为 0。
- `media_params` 和凭据属于运维数据，不能进入公共内容元数据。
- 输出模板、CSS、HTML、图片渲染器和用户可见文案不在本计划范围；只能修改后端到渲染器之间的投影。
- 一次内容请求只允许调用解析器一次；候选 URL 匹配必须只依赖规则，不得通过调用解析器探测。
- 所有网络访问必须通过现有 HTTP 工具或 Playwright 后端，并显式接收超时、代理、Cookie 和 trace 上下文。
- 不扫描或修改 `ChatBot_Runtime`、`ChatBot_Archive` 或父目录。
- 未获得用户明确授权时不得创建 Git 提交；每个任务停在验证检查点。
- 测试使用 `scripts/dev.ps1 -Task test`，代码检查使用 `scripts/dev.ps1 -Task lint`，目录布局检查使用 `scripts/dev.ps1 -Task runtime-layout`。

## 文件范围

### 契约与请求边界

- 修改：`plugins/bot_unified_runtime/contracts/media.py` —— 身份、内容、创作者、互动、媒体、音乐、来源和失败模型。
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py` —— 导出 V2 模型。
- 新建：`plugins/bot_unified_runtime/sources/parsers/context.py` —— `FetchContext`、`FetchEnvelope` 和结构化错误工具。
- 修改：`plugins/bot_unified_runtime/sources/parsers/http_util.py` —— 保留上下文请求头并提供脱敏响应信息。
- 修改：`plugins/bot_unified_runtime/sources/parsers/__init__.py` —— V2 解析器 callable 类型、注册表和只按规则匹配。
- 修改：`plugins/bot_unified_runtime/sources/parsers/types.py` —— 删除 `PlatformParse`，导出 V2 注册表使用的 `ParsedContent`/`ParseFn` 别名。

### 运行时和渲染边界

- 修改：`plugins/bot_unified_runtime/capabilities/content_parser.py` —— 消费 `ParsedContent`、只解析一次并生成后端结果字段。
- 修改：`plugins/bot_unified_runtime/output/card_render/bridge.py` —— 读取 V2 类型命名空间，不改模板输入和 CSS。
- 修改：`plugins/bot_unified_runtime/output/card_render/models.py` —— 接收现有渲染器需要的 V2 投影字段。

`output/templates.py` 明确不在文件范围内，不得修改；后端投影必须继续提供现有模板输入键。

### 平台解析器迁移

- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_bilibili.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_bilibili_goods.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_generic.py` —— 小红书、YouTube、X/Twitter、抖音和 Pixiv 扩展解析器。
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_pixiv.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_weibo.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_acfun.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_epic.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_facebook.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_huajia.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_kuaishou.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_kurobbs.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_lofter.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_mihuashi.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_miyoushe.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_moegirl.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_skland.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_steam.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/platforms_xiaoheihe.py`
- 新建：`plugins/bot_unified_runtime/sources/parsers/platforms_telegram.py` —— `t.me/<public_channel>/<message_id>` 解析器；订阅抓取在订阅计划中处理。

### 验证文件

- 新建：`tests/test_media_contract_v2.py`
- 新建：`tests/test_required_platform_parsers.py`
- 新建：`tests/test_parser_registry_v2.py`

---

## 任务 1：定义 V2 强类型媒体契约

**文件：**

- 修改：`plugins/bot_unified_runtime/contracts/media.py`
- 修改：`plugins/bot_unified_runtime/contracts/__init__.py`
- 测试：`tests/test_media_contract_v2.py`

**接口：**

- `ContentIdentity`
- `ContentMetadata`
- `CreatorMetadata`
- `VerificationMetadata`
- `EngagementMetrics`
- `MediaAsset`
- `SourceProvenance`
- `ParsedContent`

`ParsedContent` 从 `contracts/music.py` 导入唯一的 `MusicTrack`；解析器注册表只接受 `ParsedContent` 返回值。

- [ ] **步骤 1：先写失败的契约测试**

测试必须覆盖：

1. 内容指标与创作者指标分别保存；
2. `ParsedContent.minimal(...)` 对未知字段使用 `None` 和 `limitations`；
3. `MediaAsset.access_headers` 拒绝 `Cookie`、`Authorization`、`Proxy-Authorization` 以及其他 token 型请求头。

示例断言：

```python
item = ParsedContent(
    identity=ContentIdentity(
        platform="youtube",
        item_id="v1",
        item_kind="video",
        canonical_url="https://youtube.com/watch?v=v1",
    ),
    content=ContentMetadata(title="标题", body="正文"),
    creator=CreatorMetadata(
        platform_creator_id="c1",
        name="作者",
        follower_count=10,
        post_count=4,
    ),
    engagement=EngagementMetrics(view_count=100, like_count=7),
    media=[MediaAsset(asset_type="image", url="https://img/v1.jpg", order=0)],
    provenance=SourceProvenance(
        parse_depth="deep",
        auth_mode="anonymous",
        fetched_at=datetime.now(timezone.utc),
        source_endpoints=["youtube.oembed"],
    ),
)
assert item.creator.post_count == 4
assert item.engagement.view_count == 100
```

- [ ] **步骤 2：运行测试确认模型尚不存在**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:PYTHONDONTWRITEBYTECODE='1'; .\ChatBot_Runtime\venv\Scripts\python.exe -m pytest tests/test_media_contract_v2.py -q"
```

预期：失败，因为 V2 模型和 `ParsedContent.minimal` 尚未定义。

- [ ] **步骤 3：实现严格模型**

在 `StrictBaseModel` 上实现以下字段：

- `ContentIdentity`：`platform`、`item_id`、`item_kind`、`canonical_url`、可空 `parent_id`、`visibility`、`availability`；
- `ContentMetadata`：`title`、`body`、`summary`、`tags`、`language`、`published_at`、`updated_at`、`platform_extra`；
- `CreatorMetadata`：平台创作者 ID、昵称、handle、头像、主页、简介、签名、认证、粉丝、关注、获赞、收藏、帖子、长视频、短视频、视频总数和注册时间；
- `EngagementMetrics`：浏览、播放、点赞、爱心、收藏、书签、评论、分享、转发、引用、弹幕、投币和 `platform_extra`；
- `MediaAsset`：资源类型、URL、预览 URL、尺寸、时长、格式、码率、帧率、HDR、顺序和非敏感访问请求头；
- `SourceProvenance`：解析深度、认证模式、抓取时间、脱敏端点、限制和警告；
- `ParsedContent`：身份、内容、可空创作者、互动、媒体、可空 `MusicTrack` 和来源。

`ParsedContent.minimal(...)` 用于返回只有标题/链接的阻断或浅解析结果。增加校验：拒绝敏感请求头、负数时长和无效核心 ID。

- [ ] **步骤 4：运行契约测试**

预期：`tests/test_media_contract_v2.py` 全部通过。

- [ ] **步骤 5：检查格式，不提交**

运行：

```powershell
git diff --check -- plugins/bot_unified_runtime/contracts/media.py plugins/bot_unified_runtime/contracts/__init__.py tests/test_media_contract_v2.py
```

预期：无空白错误；除非用户明确授权，不执行 `git add` 或 `git commit`。

## 任务 2：增加共享抓取上下文和结构化失败

**文件：**

- 新建：`plugins/bot_unified_runtime/sources/parsers/context.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/http_util.py`
- 测试：`tests/test_media_contract_v2.py`

**接口：**

```python
FetchContext(
    platform: str,
    timeout_seconds: float,
    cookie_header: str = "",
    proxy: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    trace_id: str = "",
    extra_headers: dict[str, str] = {},
)
FetchEnvelope[T](
    payload: T,
    final_url: str,
    status_code: int | None,
    fetched_at: datetime,
    source_endpoint: str,
    warnings: list[str],
)
ParseFailure(
    code: str,
    platform: str,
    operation: str,
    retryable: bool,
    retry_after_seconds: int | None = None,
    public_message: str = "",
)
```

所有解析器统一使用 `context`；Cookie 只进入真实请求，不进入异常、日志、来源端点或公开返回。

- [ ] **步骤 1：写失败测试**

测试 `build_request_headers(context)` 能保留真实 Cookie 给请求，同时 `context.sanitized_headers()` 将 Cookie 脱敏为 `<redacted>`，普通 trace 头保持可见。

- [ ] **步骤 2：运行测试确认工具不存在**

预期：失败，因为 `FetchContext` 和 `build_request_headers` 尚未实现。

- [ ] **步骤 3：实现上下文和脱敏工具**

实现冻结 dataclass、请求头构造、`sanitize_url(url)` 以及 HTTP 错误分类。`sanitize_url` 必须删除或隐藏包含 `token`、`key`、`sign`、`auth`、`cookie`、`sid` 的查询参数。现有 HTTP 工具接收 `FetchContext` 并返回脱敏的响应信息。

- [ ] **步骤 4：运行测试并检查导入**

预期：媒体契约与上下文测试通过，无敏感值进入异常信息。

## 任务 3：切换解析器注册表和内容能力到 V2

**文件：**

- 修改：`plugins/bot_unified_runtime/sources/parsers/types.py`
- 修改：`plugins/bot_unified_runtime/sources/parsers/__init__.py`
- 修改：`plugins/bot_unified_runtime/capabilities/content_parser.py`
- 修改：`plugins/bot_unified_runtime/output/card_render/bridge.py`
- 修改：`plugins/bot_unified_runtime/output/card_render/models.py`
- 测试：`tests/test_parser_registry_v2.py`

**接口：**

```python
ParseFn = Callable[[str, FetchContext], ParsedContent]
parse_to_backend_result(item: ParsedContent) -> dict[str, object]
```

- [ ] **步骤 1：写注册表和只调用一次的测试**

测试内容：

1. 所有注册 parser 都是可调用的 V2 函数；
2. `parse_matched_url(urls, parse_fn, context)` 只调用 `parse_fn` 一次；
3. 规则匹配不通过真实解析器探测 URL。

示例：

```python
calls = []

def parse_once(_url, _context):
    calls.append(1)
    return item

result = parse_matched_url(
    ["https://example.test/1"],
    parse_once,
    FetchContext.anonymous("example"),
)
assert result == item
assert len(calls) == 1
```

- [ ] **步骤 2：运行测试确认旧边界失败**

预期：失败，因为当前注册表仍使用旧返回类型并可能重复调用解析器。

- [ ] **步骤 3：实现 V2 注册表边界**

删除 `PlatformParse` 导入和旧类型注解。`build_content_parser_registry(...)` 为每个解析器绑定 Cookie、代理、超时和 Playwright 上下文。内容能力层按以下顺序执行：

1. 构造一次 `FetchContext`；
2. 用 `ParserRegistry` 只按规则匹配；
3. 调用选中的 parser 一次；
4. 从 `ParsedContent` 命名空间构造 `CapabilityResult`；
5. 将结构化失败映射到既有回退边界，不能泄漏异常正文。

更新 bridge 和 models，使其读取 `identity`、`content`、`creator`、`engagement`、`media` 和 `music`。保持现有模板输入键不变。

- [ ] **步骤 4：运行注册表和契约测试**

预期：新测试通过。

- [ ] **步骤 5：运行 lint**

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task lint"
```

## 任务 4：迁移七个必需社交平台解析器

**文件：**

- 修改：Bilibili、小红书、YouTube、X/Twitter、Pixiv、微博现有解析器；
- 新建：`plugins/bot_unified_runtime/sources/parsers/platforms_telegram.py`；
- 修改：`plugins/bot_unified_runtime/sources/parsers/cookies.py`；
- 测试：`tests/test_required_platform_parsers.py`。

**统一接口：**

```python
parse_bilibili(url: str, context: FetchContext) -> ParsedContent
parse_xiaohongshu(url: str, context: FetchContext) -> ParsedContent
parse_youtube(url: str, context: FetchContext) -> ParsedContent
parse_twitter_x(url: str, context: FetchContext) -> ParsedContent
parse_pixiv(url: str, context: FetchContext) -> ParsedContent
parse_weibo(url: str, context: FetchContext) -> ParsedContent
parse_telegram(url: str, context: FetchContext) -> ParsedContent
```

- [ ] **步骤 1：建立离线 fixture 和失败断言**

每个平台至少准备一个 JSON/HTML fixture，验证标题、正文、作者 ID、作者指标、内容指标、全部媒体 URL 和 limitations。Telegram 私有邀请链接必须抛出 `ParseFailure`，不能当成公开频道。

- [ ] **步骤 2：运行 fixture 测试确认旧返回形状失败**

预期：失败，因为当前 fixture helper 和 V2 返回结构尚未实现。

- [ ] **步骤 3：迁移 Bilibili 与小红书**

Bilibili：保留现有 view、dynamic/opus、live、番剧、收藏夹、合集等接口，映射正文、全部图片、播放/弹幕/评论/点赞/投币/收藏/分享、作者资料、时长和发布时间；注册日期标记为 `platform_not_public`。

小红书：保留页面初始状态、`user_posted` JSON、Playwright 和 HTML fallback；映射全部 `imageList`、视频预览、笔记正文、发布时间和互动数据；只有接口明确返回 `total` 时才填真实帖子数，否则写入 limitation。

- [ ] **步骤 4：迁移 YouTube、X/Twitter、Pixiv 和微博**

YouTube：让 parser 先调用现有 Innertube，再使用 HTML fallback；所有请求传递 Cookie/代理；补齐时长、简介、标签、分类、频道 ID、长短视频统计和公开互动数；分享数与点踩数明确标记不可得。

X/Twitter：fxtwitter 负责单帖深化；OG fallback 必须继续传代理；全部媒体、引用/回复/转发关系进入新模型；`auth_token`/`ct0` 不得进入来源元数据。

Pixiv：接入 `.pixiv.net` 和 `PHPSESSID`；补齐全部分页图片、标签、作者统计、R18/AI/可见性限制。

微博：长文本第二跳继承 Cookie、代理、超时和 trace；完整映射配图/视频预览以及值为 0 的互动计数；作者指标独立保存。

- [ ] **步骤 5：实现 Telegram 公开消息解析器**

支持 `t.me/<username>/<message_id>` 和 `telegram.me/<username>/<message_id>`。抓取频道名称、消息 ID、时间、正文、预览媒体、浏览量、反应和转发数（页面明确出现时）。频道 username 作为创作者 ID；私有邀请、成员数、删除历史和完整评论线程写入 limitations。

- [ ] **步骤 6：运行必需平台 fixture 测试**

预期：全部通过，且不发起外网请求。

## 任务 5：迁移其余已注册解析器

**文件：**其余各平台 parser 文件；测试：`tests/test_parser_registry_v2.py`。

- [ ] **步骤 1：增加参数化返回类型测试**

遍历 `_PLATFORM_RULES` 中的每个 parser ID，使用 `get_type_hints(parser).get("return") is ParsedContent` 断言返回类型。

- [ ] **步骤 2：运行测试获取未迁移清单**

预期：只列出尚未改造的 parser。

- [ ] **步骤 3：迁移游戏、社区、电商和百科解析器**

把 AcFun、Steam、Epic、Facebook、萌娘百科、小黑盒、米游社、森空岛、库街区、米画师、画加、LOFTER、B站商品等数据映射到统一命名空间。Facebook/Instagram 登录墙结果返回 `blocked`，不能伪造 deep 结果。

- [ ] **步骤 4：迁移 generic 分支和 OG fallback**

抖音、快手、Pixiv 小说/系列/用户/比赛/排行以及其余 OG 分支，在只有浅信息时使用 `ParsedContent.minimal`，并为每个缺失的请求字段写入 limitation。

- [ ] **步骤 5：运行完整离线 parser 测试**

预期：所有已注册 ID 通过。

## 任务 6：完成注册绑定和后端验证

- [ ] **步骤 1：登记 Telegram、Pixiv Cookie 和上下文绑定**

注册 Telegram URL 规则；为 Pixiv 绑定 Cookie provider；保证 YouTube、X/Twitter、Pixiv、Facebook、Telegram 使用配置代理，Bilibili/微博使用配置超时和可选代理。

- [ ] **步骤 2：搜索可执行旧契约**

运行：

```powershell
rg -n "PlatformParse|from .*parsers\.types import PlatformParse|stats=.*music_card|detail=.*author" plugins/bot_unified_runtime/sources/parsers plugins/bot_unified_runtime/capabilities/content_parser.py
```

预期：执行代码中不存在旧契约引用；任何命中都必须删除，而不是包一层兼容适配器。

- [ ] **步骤 3：运行三项工作区验证**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command ".\scripts\dev.ps1 -Task runtime-layout"
```

预期：全部通过，且源码树没有 `__pycache__`、`*.pyc`、`.pytest_cache`、`.ruff_cache` 或 `.mypy_cache`。

- [ ] **步骤 4：记录验证检查点**

运行 `git status --short`，确认只出现本计划文件和原有工作区改动；未经授权不暂存、不提交。

## 完成检查清单

- [ ] `ParsedContent` 是唯一的 parser 返回契约。
- [ ] `_PLATFORM_RULES` 中所有 parser（包括 Telegram 和音乐 parser）都已注册并使用 V2 类型。
- [ ] 七个必需社交平台保留所有可获得的内容、作者、互动和媒体字段。
- [ ] 缺失字段保持可空，并有明确 limitations。
- [ ] 一个消息 URL 只调用一次 parser。
- [ ] 没有修改 HTML、CSS、模板标记或图片渲染实现。
- [ ] test、lint、runtime-layout 全部通过。
