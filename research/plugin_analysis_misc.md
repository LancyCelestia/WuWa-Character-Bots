# NoneBot 通用插件源码分析报告（12 个）

> 目标：为 `plugins/bot_unified_runtime`（统一流水线，已有天气接口与点歌功能）提供可借鉴点与优先级判断。
> 方法：逐仓库下载源码（`main` 失败回退 `master`），逐文件阅读 README / `__init__.py` / 核心模块 / `pyproject.toml`，endpoint 均从源码原样抄录。
> 源码解压在 `research/plugin_sources/` 下。

---

## 0. 总览

| # | 插件 | 功能 | 数据源 / 外部依赖 | 需 key/cookie | 许可证 | 可用性 |
|---|------|------|------------------|:---:|------|--------|
| 1 | multincm | 网易云多选点歌 | 网易云 weapi/eapi（经 pyncm） | 游客可用，VIP 需 cookie | MIT | 部分能用 |
| 2 | picsearcher | 多引擎搜图 | saucenao/ascii2d/iqdb/trace.moe/yandex/exhentai | exhentai 需 cookie | GPL-3.0 | 已失效/需大改 |
| 3 | helper-recall | 撤回查看 | 纯 OneBot API | 否 | MIT | 能用 |
| 4 | autohelp | 自动帮助 | 本地插件自省 | 否 | MIT | 部分能用 |
| 5 | epicfree | Epic 限免游戏 | Epic store backend | 否 | MIT | 能用 |
| 6 | plus-one | +1 复读 | 无（纯内存） | 否 | MIT | 能用（默认哑火） |
| 7 | datastore | 数据存储基座 | 无（SQLAlchemy/Alembic） | 否 | MIT | 能用 |
| 8 | nmcweather | 天气（NMC） | 中国气象局 nmc.cn | 否 | MIT（缺文件） | 部分能用 |
| 9 | weather_lite | 天气（wttr.in） | wttr.in | 否 | MIT | 部分能用 |
| 10 | chatrecorder | 聊天记录落库 | 无（ORM 本地库） | 否 | MIT | 能用 |
| 11 | today-in-history | 历史上的今天 | 百度百科接口 | 否 | MIT | 部分能用/高风险 |
| 12 | mediawiki | 维基百科查询 | MediaWiki `api.php` | 否 | AGPL-3.0 | 部分能用 |

---

## 1. nonebot-plugin-multincm（网易云多选点歌）

- 仓库：`lgc-NB2Dev/nonebot-plugin-multincm`，`master` 分支。10 个月前停更。
- **功能概述**：网易云歌曲/电台/声音/歌单/专辑的「多选」点歌，可翻页选择、登录账号点 VIP 歌、发音乐卡片/语音/文件、看歌词图。插件自述「获取的是播放链接，不消耗会员下载次数」。
- **命令用法**（README 原样）：
  - 搜索：`点歌 [歌名/音乐ID]`（别名 `网易云` `wyy` `网易点歌` `wydg` `wysong`）；`网易声音`（`wysy` `wyprog`）；`网易电台`（`wydt` `wydj`）；`网易歌单`（`wygd` `wypli`）；`网易专辑`（`wyzj` `wyal`）
  - 操作：`解析`（`resolve` `parse` `get`）、`直链`（`direct`）、`上传`（`upload`）、`歌词`（`lrc` `lyric` `lyrics`）——均需「回复音乐卡片/链接」
- **依赖**（`pyproject.toml`）：`nonebot2>=2.4.4`、`nonebot-plugin-htmlrender>=0.6.8`、`nonebot-plugin-alconna>=0.60.3`、`nonebot-plugin-localstore>=0.7.4`、`pyncm>=1.8.1`、`typing-extensions>=4.15.0`、`httpx>=0.28.1`、`jinja2>=3.1.6`、`cookit[...]>=0.13.2`、`nonebot-plugin-waiter>=0.8.1`、`cachetools>=6.2.1`、`yarl>=1.22.0`、`silk-python>=0.2.7`、`qrcode>=8.2`。Python `>=3.10,<4.0`。
- **许可证**：MIT。

### 用到的 API/endpoint（核心产出）

网易云请求**全部委托 `pyncm` 库**（`mos9527/pyncm`），用 `WeapiCryptoRequest` / `EapiCryptoRequest` 做 AES/RSA 加密。插件源码里**显式写出的接口路径只有 5 个**（电台/声音相关），其余在 pyncm 内部：

显式路径（`data_source/raw/request.py`）：
| 用途 | 加密方式 | 路径 | 参数 |
|------|---------|------|------|
| 搜索电台 | Eapi | `/eapi/search/voicelist/get` | keyword, scene=normal, limit, offset |
| 搜索声音/节目 | Weapi | `/api/search/voice/get` | keyword, scene=normal, limit, offset |
| 电台详情 | Weapi | `/api/djradio/v2/get` | id |
| 电台节目列表 | Weapi | `/weapi/dj/program/byradio` | radioId, limit, offset |
| 节目详情 | Weapi | `/api/dj/program/detail` | id |

pyncm 调用（`request.py` import；**具体 URL 在 pyncm 库内部，不在本插件源码中**，下表右列是按 NeteaseCloudMusicApi 生态约定的对应路径，属推断）：
- `cloudsearch.GetSearchResult`（搜索，stype=SONG/PLAYLIST/ALBUM）→ 对应 `/api/cloudsearch/pc`
- `track.GetTrackAudio`（播放链接，bitrate）→ `/api/song/enhance/player/url`
- `track.GetTrackDetail`（歌曲详情，`privileges` 字段返回可播等级）→ `/api/v3/song/detail`
- `track.GetTrackLyrics`（歌词）→ `/api/song/lyric`
- `playlist.GetPlaylistInfo`（歌单）→ `/api/v6/playlist/detail`
- `album.GetAlbumInfo`（专辑）→ `/api/album/{id}`
- 列表页交互指令（`search.py`）：退出 `退出/tc/取消/qx/quit/q/exit/e/cancel/c/0`；上一页 `上一页/syy/previous/p`；下一页 `下一页/xyy/next/n`；跳页 `page/跳页/页 + 页码`；选择直接输序号
- 缩略图：封面 URL 追加 `?param={size}y{size}`；音卡签名 POST `NCM_CARD_SIGN_URL`（JSON `{type,url,audio,title,image,singer}`）

登录（`data_source/raw/login.py`）：
- `LoginQrcodeUnikey` / `LoginQrcodeCheck`；二维码 URL = `https://music.163.com/login?codekey={uni_key}`
- `LoginViaAnonymousAccount`（游客 anonymous token）、`LoginViaCookie(MUSIC_U)`、`LoginViaCellphone`（短信/密码）、`LoginViaEmail`、`GetCurrentLoginStatus`
- 会话持久化：`DumpSessionAsString` / `LoadSessionFromString`，存到本地 session 文件

卡片/跳转：`https://music.163.com/song?id={id}`、`https://music.163.com/{type}?id={id}`；短链 `https://163cn.tv` 用 `resolve_short_link` 解析。

**是否需 key/cookie**：游客（anonymous token）可点非 VIP 歌；点 VIP 试听需 `NCM_COOKIE_MUSIC_U`（登录态 cookie）。二维码/短信/手机/邮箱登录 README 自标「可能已无法使用」。

### 亮点算法与数据结构
- **pyncm 封装层**：`ncm_request()` 统一校验 `ret["code"]==200` 并抛 `NCMResponseError`；用 `partial` 把搜索函数特化为 `search_song/search_playlist/search_album`。
- **分页/翻页交互**：`calc_min_index(page)` 计算 offset；`interaction/cache.py` 缓存「用户最近一次操作」（TTL 12h、LRU 上限 1024），配合 `waiter` 实现多轮点选。
- **LRC 合并**（`utils/lrc_parser.py`）：翻译歌词与原词合并、去空行、日文罗马音上置。
- **渲染**：`render/` 用 Jinja2 模板 + htmlrender(playwright) 生成歌曲列表卡与歌词图。
- **发送策略**：卡片/语音(silk 转码)/文件三态可配；`NCM_OB_V11_LOCAL_MODE` 控制 OneBot V11 是否本地下载再上传；`NCM_CARD_SIGN_URL` 可把音卡签名交给 LLOneBot/NapCat。

### 是否还能用
**部分能用**。
- 点歌主体接口（cloudsearch/song url/detail/lyric）仍是网易云现行的 weapi/eapi，且 `NeteaseCloudMusicApi`（Node，Binaryify 系）仍在活跃维护（近期 CHANGELOG 仍在更新），说明接口本身未死。
- **主要隐患在 pyncm 停更**：`pyncm>=1.8.1` 已长期无实质维护，其硬编码的 weapi/eapi 加解密 key 与 anonymous token 流程一旦被网易轮换即静默失效。插件停更 10 个月 + 依赖全部为浮动下限（`alconna>=0.60.3`、`pyncm>=1.8.1` 等）会带来兼容性漂移风险。
- 结论：**不建议整体引入**。借鉴其架构/算法，但网易云「深搜 + 播放」若需要，应改用维护中的 Node `NeteaseCloudMusicApi` 服务或 pyncm 的活跃 fork，而非这条已停更的纯 Python 链路。

---

## 2. nonebot_plugin_picsearcher（搜图）

- 仓库：`synodriver/nonebot_plugin_picsearcher`，`main` 分支，版本 `0.1.6rc1`。
- **功能概述**：把图片 URL 送进多个以图搜图引擎，返回相似图/相似度/来源链接。支持 6 个引擎。
- **命令用法**：`搜图`（别名 `search`，需 `@bot`），交互提示 `从哪里查找呢? ex/nao/trace/iqdb/ascii2d`，再给图；被动命令 `上一张图是什么` / `上一张` / `这是什么` 对群内最近一张图走 saucenao。
- **依赖**（`setup.py`）：`aiohttp`、`lxml`。`install_requires` **未声明 nonebot2**（bug）。Python `>=3.7`。
- **许可证**：GPL-3.0。
- **最大坑**：全程 `from nonebot.adapters.cqhttp import ...`——这是已被 `onebot.v11` 取代的旧适配器包名，现代 NoneBot 无法直接运行。

### 用到的 API/endpoint（逐个抄录）

| 引擎 | 方法 | URL | 参数/请求体 | 返回 | 鉴权 |
|------|------|-----|------------|------|------|
| saucenao | POST | `https://saucenao.com/search.php` | multipart，字段 `file`（`content_type=image/jpeg, filename=blob`） | HTML，XPath 抓 `div.result>table`（相似度/标题/pixiv id/member） | 无 key；纯 HTML 抓取 |
| ascii2d | GET | `https://ascii2d.net/search/url/{url}` | 图片 URL 直接拼路径 | HTML，XPath 抓 `div.row.item-box`（缩略图/名称/作者/原图/作者链接） | 无 |
| iqdb | POST | `http://iqdb.org/` | multipart：`MAX_FILE_SIZE=""`、`service[]=1..6,11,13`、`file`、`url=""` | HTML，XPath 抓 `div#pages>table` | 无（需带伪造 Cookie 头） |
| trace.moe | POST | `https://api.trace.moe/search?cutBorders=1&anilistID=` | multipart 字段 `image` | JSON `result[]`（anilist, similarity, from, to, filename, episode, image, video） | 无 key |
| trace.moe 补充 | POST | `https://trace.moe/anilist` | GraphQL（AniList 查询 `Page.media(id_in, type:ANIME)` 拿 title/isAdult） | JSON `data.Page.media[]` | 无 key |
| yandex | GET | `https://yandex.com/images/search?rpt=imageview&url={url}` | 图片 URL 作 query | HTML，XPath 抓 `li.other-sites__item` | 无（反爬强） |
| exhentai | POST | `https://exhentai.org/upload/image_lookup.php` | multipart：`sfile`(图)、`f_sfile=search`、`fs_similar=on` | HTML，XPath 抓 `td.gl3c.glname`（本子名/链接/缩略图） | 需 `EX_COOKIE` |
| e-hentai（无 cookie 时） | POST | `https://upld.e-hentai.org/image_lookup.php` | 同上 | 同上 | 无 cookie 走此地址 |

### 亮点
- 后端统一抽象为 `async def get_des(url) -> AsyncGenerator[MessageSegment]`，`__init__.py` 里用 mode 字符串分发到各引擎。
- `utils.limiter()` 限制返回条数；群聊「风险控制模式」下用合并转发（`send_group_forward_msg`）打包多条结果。
- 被动图缓存 `pic_map[group_id]=url` 记录群内最近一张图。

### 是否还能用
**基本已失效 / 需大改**：cqhttp 适配器已废弃；全部走 HTML 抓取（saucenao/ascii2d/iqdb/yandex 的 DOM 早已变）；yandex 反爬；trace.moe 现在有官方带 key 的 JSON API（更稳）。**不建议整合**。若要搜图能力，优先 Saucenao/trace.moe 官方 API（需 key），或用维护中的 `YetAnotherPicSearch`。

---

## 3. nonebot-plugin-helper-recall（撤回查看）

- 仓库：`Wojusensei/nonebot-plugin-helper-recall`，`main` 分支。
- **功能概述**：帮普通群员撤回自己「超时无法撤回」的消息（Bot 以管理员身份代撤）。
- **命令用法**：引用自己发的消息 + 发送 `/撤回`。
- **依赖**（`pyproject.toml`）：`nonebot2>=2.3.0`、`nonebot-adapter-onebot>=2.0.0`。
- **许可证**：MIT。

### API/endpoint
**无外部 HTTP API**，只调 OneBot V11 协议动作：
- `bot.get_group_member_info(group_id, user_id=bot.self_id)` → 校验 Bot 自身是否 `admin/owner`
- `bot.delete_msg(message_id=reply.message_id)` → 执行撤回

### 亮点
- `is_recall_command()` 用 `event.get_plaintext().strip()` + 遍历 `command_start` 精确匹配 `/撤回`，而非 `on_command`——因为「引用 + /撤回」时消息首段是 reply 段，`on_command` 只查首段会漏触发（这是踩坑点，值得借鉴）。
- 错误信息区分「超时/权限」并做脱敏，不把原始 API 异常发到群里。

### 是否还能用
**能用，即装即用，风险极低**。现代写法、依赖窄、纯协议调用。

---

## 4. nonebot-plugin-autohelp（自动帮助）

- 仓库：`ffreemt/nonebot-plugin-autohelp`，`master` 分支，版本 `0.1.7`。
- **功能概述**：自动汇总「已加载插件」的命令/别名/`__doc__`，响应 help 指令。
- **命令用法**：`/help` `!help` `help` `菜单` `caidan` `/i`（正则 `^[/!#]?\s*(?:help|menu|帮助|菜单|caidan|info)|[/#]i`，大小写不敏感）；`help -d`/`--details`/`details`/`详细` 附带各插件 `__doc__`；`-h` 打印 usage；3 秒限流。
- **依赖**（`pyproject.toml`）：`nonebot2 ^2.0.0-alpha.16`、`nonebot-adapter-onebot ^2.0.0-beta.1`、`logzero ^1.7.0`。Python `^3.8`。
- **许可证**：MIT。

### API/endpoint
**无网络 API**。全靠本地自省：`nonebot.get_loaded_plugins()` → 每个插件的 `module.__file__`，再用正则 `^[^#]*\s*=\s+(?:nonebot\.)?on_command\([\s\S]*?\)` + `ast.literal_eval` 从源码文本里扒 `command` 与 `aliases`。

### 亮点
- 「从源码抽取 on_command 别名」的思路（`fetch_plugin_info.py` / `parse_cmd.py`）。
- `argparse` 驱动帮助子命令。

### 是否还能用
**部分能用，需改造**。`nonebot.Config()` 在现代稳定版已被移除会直接报错；依赖钉死 alpha/beta 无法与现代 nonebot2 共存；别名提取只认 `aliases={...}` 集合字面量，现代插件常用元组/`alconna` 会失效。**借鉴理念即可**：改用 `get_loaded_plugins()` → `plugin.metadata`（`__plugin_meta__.usage/description`）重做自动帮助。

---

## 5. nonebot-plugin-epicfree（Epic 免费游戏）

- 仓库：`FlanChanXwO/nonebot-plugin-epicfree`，`main` 分支，src 布局。
- **功能概述**：查询/订阅 Epic Game Store 每周限免游戏，定时推送（合并转发）。
- **命令用法**：`epic` 系列（订阅/退订/查询，README 的 `epic刷新` **源码未实现**）。
- **依赖**（`pyproject.toml`）：`httpx>=0.27`、`nonebot-adapter-onebot>=2.4.6`、`nonebot-plugin-apscheduler>=0.5`、`nonebot2>=2.4.4`、`pytz`、`nonebot-plugin-localstore>=0.7.4`。Python `>=3.10`。
- **许可证**：MIT（`LICENCE` 文件）。

### API/endpoint（核心产出）
唯一真实接口，**无 key/cookie**，可选 http/socks5 代理：

```
GET https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions
  params: locale=zh-CN, country=CN, allowCountries=CN
  headers: Referer=https://www.epicgames.com/store/zh-CN/, Content-Type=application/json; charset=utf-8, 固定浏览器 UA
  timeout: 10s
```
返回取 `res.json()["data"]["Catalog"]["searchStore"]["elements"]`，每条元素关键字段：
- `title`、`description`、`keyImages[]`（type ∈ Thumbnail/VaultOpened/DieselStoreFrontWide/OfferImageWide 取图）
- `promotions.promotionalOffers[0].promotionalOffers[0].endDate`（RFC3339，转 Asia/Shanghai 显示结束时间）
- `price.totalPrice.fmtPrice.originalPrice / discountPrice`（`discountPrice == "0"` 才算免费）
- `seller.name` + `customAttributes`（developerName/publisherName）
- `url` 或由 `offerMappings[].pageSlug` / `catalogNs.mappings[].pageSlug` / `customAttributes[productSlug]` 拼 `https://store.epicgames.com/zh-CN/p/{slug}`

（endpoint 来自 Epic 官方商店前端后端主机，未公开稳定承诺；参考 RSSHub `/epicgames` 路由与 `epicstore_api` 包。）

### 亮点
- 分层清晰：`data_source.py`（取数/解析）、`schedule.py`（APScheduler cron + 恢复）、`config.py`（代理拼装）。
- 持久化用 localstore 三 JSON（订阅状态/推送历史/调度）。
- 去重：把消息里的 `https://store.epicgames.com...` 链接作为唯一指纹比对上次推送（`check_push`，实际是死代码，但思路可借鉴）。
- 定时推送用 `node_custom` 合并转发打包图文。

### 是否还能用
**能用**。现代依赖，接口免 key，可整体移植。风险：Epic 未公开接口可能漂移/被地区墙，需保留代理与兜底。

---

## 6. nonebot-plugin-plus-one（+1 复读）

- 仓库：`yejue/nonebot-plugin-plus-one`，`main` 分支，仅 3 个 py 文件（README 自称「40 行复读姬」）。
- **功能概述**：群聊里连续出现两条相同消息时，Bot 复读。
- **命令用法**：无命令，被动触发（`on_message`）。
- **依赖**：仓库**无 `pyproject.toml`**；代码推断 `nonebot2` + `nonebot_plugin_session` + `pydantic`。
- **许可证**：MIT。

### API/endpoint
**无网络 API**。纯内存 `msg_dict = {}`（`group_id → 最近消息列表`），`on_message(priority=config.plus_one_priority, block=False)` 监听。

### 亮点/注意点
- 消息相等判断 `is_equal()`：单张图片按 `file_size` 判等（**有误判风险**，不同图可能同 size）；其余用 `Message` 的 `==`。
- 用 `nonebot_plugin_session.extract_session` 跨适配器取 `group_id`。
- 配置：`plus_one_priority`（代码默认 1，README 写 10，不一致）、`plus_one_white_list`（默认 `[]` = **完全不触发**）。

### 是否还能用
**能用，但默认哑火（白名单为空），价值低**。整合时可内联 handler 逻辑、去掉 session 插件依赖、图片去重改用哈希。

---

## 7. nonebot-plugin-datastore（数据存储）

- 仓库：`he0119/nonebot-plugin-datastore`，`main` 分支，v1.3.1。
- **功能概述**：NoneBot2 的**数据基础设施库**（非聊天插件）。为每个插件提供独立的数据/缓存/配置目录 + SQLAlchemy 异步 ORM + Alembic 迁移 + 多后端配置存储。
- **命令用法**（nb-cli）：`nb datastore dir/migrate/upgrade/downgrade [--name plugin_name]`。
- **依赖**：`nonebot2[httpx]>=2.3.0`、`nonebot-plugin-localstore`、`sqlalchemy[aiosqlite]>=2.0`、`alembic>=1.9.1`。
- **许可证**：MIT。

### API/endpoint
**无外部 API**。核心接口：
- `get_plugin_data(name=None)` → `PluginData`（`cache_dir/config_dir/data_dir`、`config.get/set`、`dump_json/load_json/dump_pkl/open/exists/download_file/network_file`、`Model`、`metadata`、`migration_dir`）
- `get_session()`（配合 `Depends` 注入 `AsyncSession`）、`create_session()`
- `pre_db_init` / `post_db_init` 钩子（保证 DB 初始化前/后执行）

### 亮点算法与数据结构
- **每插件独立 SQLAlchemy registry**：`Model` 用 `@declared_attr __tablename__` 自动加前缀 `{plugin_name}_{class_name_lower}`，避免多插件表名冲突；需要跨插件关联时 `use_global_registry()`。
- **调用栈识别插件名**：`get_caller_plugin_name()` 从调用方 frame 反推插件名，实现「无参取自己的 PluginData」。
- **配置 provider 抽象**：`json/yaml/toml/database` 四种 `ConfigProvider`，`resolve_dot_notation` 按配置字符串动态加载。
- **NetworkFile**：先本地后网络的 JSON 下载 + 缓存 + `process_data` 后处理。
- **异步化 Alembic CLI**：`script/` 内用 `asyncio` + mako 模板生成迁移脚本。

### 是否还能用
**能用**（活跃维护）。它是 `chatrecorder` 依赖的 `nonebot-plugin-orm` 的上位替代/同类。**对我们的项目**：我们是「单运行时、非多插件商店」，无需 per-plugin registry，但其「表名前缀 + Alembic 迁移纪律 + 配置 provider」值得在我们扩展持久层时借鉴。

---

## 8. nonebot-plugin-nmcweather（天气·中国气象局）

- 仓库：`orchiddream/nonebot-plugin-nmcweather`，`main` 分支，v0.1.3。
- **功能概述**：中国气象局 NMC 实时天气查询（按省份-区县/城市名），支持查询省份下全部区县。
- **命令用法**：`天气 北京`、`天气 河北-石家庄`（别名 `查天气`）；`支持区县 江苏`（别名 `查询区县` `可查区县`）。
- **依赖**（`pyproject.toml`）：`nonebot2 ^2.4.2`、`nonebot-adapter-onebot ^2.4.6`、`httpx >=0.28.1,<=1.0.0`。Python `^3.10`。
- **许可证**：`pyproject.toml` 声明 MIT，**但仓库缺 LICENSE 文件**（引用时需向作者补全）。

### API/endpoint（核心产出）
数据源是**中国气象局 NMC（nmc.cn）**——**不是**和风/彩云/OpenWeather。**免 key/cookie**：

```
GET https://www.nmc.cn/rest/weather?stationid={stationid}&_={int(time.time()*1000)}
```
- `stationid`：来自本地打包的 `qx.json`（约 2500 条 `{code, province, city, url}`），两级模糊匹配（省份简称 + 城市前缀）命中 `code`。
- 返回结构：`data.real.{station, weather, wind, sunriseSunset, publish_time}`；`weather` 含 `info/temperature/feelst/temperatureDiff/humidity/rain/icomfort`，`wind` 含 `direct/power/speed`。
- 未知值约定：`9999` / `9999.0` 一律转 `❓`（`format_value` 统一兜底）。
- `icomfort` 舒适度映射表（-4..4 → 中文描述，9999 → ❓）。

### 亮点
- 本地码表 `qx.json` 离线做城市→站号匹配（不联网查城市码）。
- 对 NMC 返回的「9999 占位」做了系统性兜底。
- 结构化字段渲染成固定格式中文报告。

### 是否还能用
**部分能用**：NMC 网页/移动端的 `rest/weather` 是**非公开、无契约**的接口（官网页面前端在用），有被改动的风险，需实测；但当前字段结构清晰、免 key、覆盖国内区县，很适合做「中文城市名 → 天气」的免费数据源。

---

## 9. nonebot_plugin_weather_lite（天气·wttr.in）

- 仓库：`zjkwdy/nonebot_plugin_weather_lite`，`main` 分支，v0.0.1。
- **功能概述**：wttr.in 天气查询的极简包装（返回天气 PNG 图）。
- **命令用法**：`天气 城市名`（别名 `wttr` `weather` `tianqi`）；城市名支持多语言/全球（`北京`=`Beijing`=`Peking`）；README 提到 `城市名_format=v2|v3`、`城市名_lang=xx`、`天气 Moon` 等高级用法（实为透传给 wttr.in）。
- **依赖**（`setup.py`）：`nonebot2 >=2.0.0b1`、`nonebot-adapter-onebot >=2.0.0b1`。
- **许可证**：MIT。

### API/endpoint（核心产出）
数据源是 **wttr.in**（**不是**和风/彩云）。**免 key**。代码唯一请求：

```
GET http://zh.wttr.in/{escape(city)}.png
```
返回一张 PNG 天气图，直接 `MessageSegment.image(file=..., cache=False)` 发送。代码里没有解析任何 JSON——README 的 `_format/_lang` 是 wttr.in 服务端自己解析的查询串，插件只是拼 URL。

### 是否还能用
**部分能用**：wttr.in 服务仍在线、免 key、全球覆盖；插件极简但老旧（`http` 明文、无超时/错误处理、依赖 beta）。适合做**免 key 的图片兜底**，不适合做结构化天气数据源。

### 天气两个对比结论
| | nmcweather | weather_lite |
|---|---|---|
| 数据源 | 中国气象局 `nmc.cn/rest/weather` | `wttr.in` |
| 是否需 key | 否 | 否 |
| 输出 | 结构化中文字段（温度/湿度/风/日出日落/舒适度） | 一张 PNG 图 |
| 城市覆盖 | 国内区县（本地 qx.json 码表） | 全球 |
| 稳定性 | 非公开接口，需实测 | 服务在线但插件老旧 |
| **建议** | **更适合直接借鉴**（结构化字段 + 国内码表 + 9999 兜底 + 舒适度映射） | 仅作免 key 图片兜底 |

---

## 10. nonebot-plugin-chatrecorder（聊天记录）

- 仓库：`noneplugin/nonebot-plugin-chatrecorder`，`main` 分支，v0.7.0。
- **功能概述**：library 型基础设施，把入站/出站消息统一落库，供其他插件查询。
- **依赖**（`pyproject.toml`）：`nonebot2 ^2.3.0`、`nonebot-plugin-orm >=0.7.0,<1.0.0`、`nonebot-plugin-uninfo >=0.6.1,<1.0.0`、`nonebot-plugin-localstore >=0.6.0,<1.0.0`；适配器组可选（onebot/console/kaiheila/telegram/feishu/discord/dodo/satori/qq）。
- **许可证**：MIT。

### API/endpoint
**无外部 HTTP API**。落库靠两个钩子：`event_postprocessor`（记录入站）+ `Bot.on_called_api`（记录 Bot 发出的消息，type=`message_sent`）。

核心查询接口（`record.py`）：
- `get_message_records(**kwargs)` → `Sequence[MessageRecord]`
- `get_messages(**kwargs)` → `list[Message]`（反序列化 onebot 消息段）
- `get_messages_plain_text(**kwargs)` → `Sequence[str]`
- `filter_statement(**kwargs)`：支持按 bot/adapter/scope/scene/user/时间区间/消息类型 过滤（`uninfo` 的四张表 `BotModel/SceneModel/SessionModel/UserModel` join）

### 亮点算法与数据结构
- 数据模型 `MessageRecord`：`session_persist_id`（会话持久化 id）、`time`（**UTC**）、`type`（message/message_sent）、`message_id`、`message`（JSON 存 onebot 消息段）、`plain_text`（TEXT，忽略非文本段）。
- 用 `nonebot-plugin-uninfo` 做**跨适配器**的 bot/用户/场景统一建模，查询接口与具体平台解耦。
- 消息段序列化/反序列化（`message.py` 的 `serialize_message/deserialize_message`）兼容 `message_sent` 的 `on_called_api` 返回结构。

### 是否还能用
**能用，且维护活跃**。这是我们统一运行时最值得对齐的「消息持久化范式」——尤其「入站 + 出站双钩子」能把 Bot 自己的回复也记进历史，配合现有 `character/history.py` 与 `audit/` 直接复用。

---

## 11. nonebot-plugin-today-in-history（历史上的今天）

- 仓库：`AquamarineCyan/nonebot-plugin-today-in-history`，`master` 分支。
- **功能概述**：查「历史上的今天」，支持按群/按好友每日定时推送（文本或 `text_to_pic` 图片）。
- **命令用法**：`历史上的今天`；子参数 `设置/推送 HH:MM`、`状态`、`取消/关闭`。
- **依赖**（`pyproject.toml`）：`nonebot-plugin-apscheduler`、`nonebot-plugin-htmlrender`、`nonebot-plugin-localstore`、`httpx`、`nonebot-adapter-onebot`、`ujson`(可选)。
- **许可证**：MIT。

### API/endpoint（核心产出）
数据来源是**百度百科的非公开接口**（**不是内置 JSON**；本地 `PUSHDATA.json` 只存推送计划，不存历史数据）：

```
GET https://baike.baidu.com/cms/home/eventsOnHistory/{month}.json   # month = 今天 MM
```
- 请求头无特殊要求，`r.encoding = "unicode_escape"`；响应经 `_html_to_json_handle()` 清洗（去 `<\/a>`、去 `<a target=...>` 标签、去 `desc` 值、修 `title` 内引号）后 `json.loads`。
- 返回结构：`data[month][month+day]` 数组，每项 `{year, title}`；组装成 `历史上的今天 MMDD\nYYYY 标题\n...`。
- 每日 00:30 APScheduler 刷新缓存到 localstore `history_cache.json`（`date` + `info`），当天复用缓存。

### 亮点
- 「每日缓存 + 定时刷新」结构清晰；`get_history_info_with_cache()` 保证不重复请求。
- `on_notice(GroupIncreaseNoticeEvent)` 新群自动补推。

### 是否还能用
**部分能用 / 高风险**：百度百科该接口是非公开且经常改动的（清洗器 `_html_to_json_handle` 是为当时的响应格式手写的，接口一变就 `JSONDecodeError`）。**数据源需替换**；只借鉴其「APScheduler + 每日缓存 + text_to_pic」的推送骨架。

---

## 12. nonebot-plugin-mediawiki（维基百科查询）

- 仓库：`KoishiMoe/nonebot-plugin-mediawiki`，`main` 分支，v1.2.8。
- **功能概述**：在群里查维基（Wikipedia/萌百等），支持 `[[条目]]` 内联触发、`wiki` 命令、`wiki.shot` 截图。
- **命令用法**：`[[条目]]`（模板 `{{...}}`、raw `((...))`）；`wiki 条目`；`wiki.shot 条目`（Playwright 整页截图）；每群可配置不同 wiki 前缀（api 地址）。
- **依赖**（`pyproject.toml`）：`aiohttp`、`nonebot-adapter-onebot`、`nonebot-plugin-localstore`、`playwright`(可选)、`nb-cli`(可选)。
- **许可证**：AGPL-3.0（外层插件与内层 `mediawiki/` 子包目录下另有 MIT LICENSE 的 `pymediawiki-async` 内层实现）。

### API/endpoint（核心产出）
标准 MediaWiki API，**无 key/cookie**：

```
GET https://{lang}.wikipedia.org/w/api.php     # 默认基址；每群可通过 config 换成任意 MediaWiki（如萌百 moegirl）
  params: format=json（恒加）、action=query（缺省）
  action=opensearch: search={q}, limit, redirects=resolve
  list=search: srsearch={q}, srlimit, srprop
  meta=siteinfo: siprop=extensions|general
  prop=extracts / prop=pageimages 等（内层 pymediawiki-async 的 MediaWikiPage）
```
- 默认 User-Agent：`python-mediawiki/VERSION-0.1.0/(https://github.com/KoishiMoe/pymediawiki-async)/BOT`——**不合规**（MediaWiki 官方要求唯一可联系 UA，否则可能被限流/封禁，需自行覆盖）。
- 登录（可选）：`action=query&meta=tokens&type=login` 取 token → `action=login`。

### 亮点
- 内层 `mediawiki/mediawiki.py` 是完整的 `MediaWiki.create(url=...)` 异步封装（搜索/摘要/消歧义/分类/跨维基/坐标），带 memoize 缓存、限速、代理。
- 消歧义处理：`PageError` → `search()` 给候选列表让用户选；`DisambiguationError` → 列出含义选项。
- 每群前缀配置（`config_manager.py` + localstore），`wiki.shot` 走 Playwright 渲染截图。

### 是否还能用
**部分能用**：MediaWiki `action=query` 接口本身长期稳定；但作者声明不积极维护、截图功能重且 beta、默认 UA 不合规。**建议**：绕过外层 AGPL，直接复用**内层 MIT 的 `pymediawiki-async`** 或自写 `api.php` 薄层（几行 `action=query&prop=extracts&format=json`），即可零许可证负担地实现 wiki 查询。

---

## 13. 整合进 `bot_unified_runtime` 的建议与优先级

我们的运行时现状（已确认源码）：`plugins/bot_unified_runtime/` 统一流水线，已有 `capabilities/music.py`（点歌：网易云旧匿名接口 + QQ/酷我/酷狗/Apple/Spotify）、`character/temporal.py`（天气：Open-Meteo 免 key，`WeatherProvider` 协议）、`character/history.py`（SQLite 对话历史）、`audit/logger.py`（审计 + 敏感信息脱敏）、`sources/registry.py` + `sources/credentials.py` + `sources/parsers/*`（链接解析）、`policy/`（限流/静默/角色）、`sender/onebot.py`。

### P0 —— 立即并入（低风险高价值）
1. **helper-recall**：作为一个 capability（如 `bot.recall`）。纯 OneBot `delete_msg`，落到我们 `sender/onebot.py` 的协议层即可；借鉴其「引用消息时首段非文本导致 on_command 失效」的判断方式，避免踩同一个坑。
2. **chatrecorder**：作为「消息落库范式」对齐目标。我们 `character/history.py` 目前只记对话，未统一捕获 Bot 出站消息；借鉴其 `event_postprocessor` + `on_called_api` 双钩子与 `uninfo` 跨适配器身份建模，补全我们的历史完整性（尤其 Bot 自己的回复、跨 onebot 场景 id）。

### P1 —— 高价值、中等改造量
3. **nmcweather**：新增第二个 `WeatherProvider` 实现（`NMCWeatherProvider`）。它补齐我们现有 Open-Meteo 的短板——Open-Meteo 要经纬度、无法按「中文城市名」查；NMC 的 `qx.json` 码表 + `rest/weather` 免 key 可直接实现「天气 北京」这类自然指令。移植其 `find_city_code` 两级匹配、`9999` 兜底、舒适度映射。
4. **epicfree**：作为独立 capability（`bot.epic`）。接口免 key、无登录，直接复用 `store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions`，配我们已有 `scheduler`（apscheduler）与 `sources/registry` 的 HTTP 出口 + 代理配置。注意去除其死代码、把「链接指纹去重」做成真实现。
5. **datastore**：不全量引入（我们是单运行时，不需要 per-plugin registry），但借鉴「表名前缀 + Alembic 迁移纪律 + config provider（json/yaml/toml/db）」来规范化我们新增的持久化（如把 `audit`、`character/memory` 的裸 SQLite 收敛到统一迁移管理）。

### P2 —— 参考/架构级借鉴（不整体引入）
6. **multincm**：**不 vendor**（pyncm 停更 + 依赖重）。借鉴其：游客 anonymous token + `MUSIC_U` cookie 登录、weapi/eapi 加密封装层、分页/多选交互缓存、`163cn.tv` 短链解析（我们已有 `resolve_short_link`）。若将来需要网易云「深搜 + 试听」，改用维护中的 Node `NeteaseCloudMusicApi` 服务或 pyncm 活跃 fork；当前保留 `platforms_music.py` 的旧匿名接口即可。
7. **mediawiki**：**绕开外层 AGPL**，复用内层 MIT `pymediawiki-async` 或自写 `api.php` 薄层，实现 `bot.wiki` capability；务必自定义合规 User-Agent。
8. **autohelp**：借鉴「自动帮助」理念，用 `get_loaded_plugins() → metadata` 重做（不要学它的正则扒源码）。

### P3 —— 跳过/可选
9. **picsearcher**：不整合（cqhttp 废弃 + 全 HTML 抓取 + GPL）。要搜图改用 Saucenao/trace.moe 官方 API。
10. **weather_lite**：仅当想要「免 key 天气图片」时作兜底；结构化场景用 NMC/Open-Meteo。
11. **today-in-history**：借鉴 APScheduler + 每日缓存骨架，**替换数据源**（百度百科接口不稳定）。
12. **plus-one**：可选内联成彩蛋；修正图片去重（用哈希而非 file_size）并给白名单默认值。

### 许可证红线
- **mediawiki（AGPL-3.0）**：网络服务场景有传染性，不得直接 import 外层包；只能用内层 MIT 或自写。
- **picsearcher（GPL-3.0）**：不建议拷贝其代码。
- 其余均为 MIT（nmcweather 声明 MIT 但缺 LICENSE 文件，引用前需向作者确认）。
