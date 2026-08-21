# AstrBot 万能链接解析器（astrbot_plugin_parser）源码分析报告

> 源码位置：`research/astrbot_plugin_parser/astrbot_plugin_parser-main/`
> 版本：v1.5.6（metadata.yaml:5）｜作者：Zhalslar｜核心源自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser)（README.md:148）
> 本文所有行号均针对上述源码目录内的文件。

---

## 0. 结论速览（复刻可行性）

- **许可证 MIT**，逻辑可自由参考/移植（见 §6）。
- 整体架构是「**关键词+正则双匹配 → 平台解析器 → 统一 ParseResult → 下载器/渲染器/发送器**」的流水线，与本项目 `bot_unified_runtime` 已有的 `sources/registry.py` + `contracts/media.py` 高度同构，可平滑映射（见 §8）。
- **值得原样搬**：`core/cookie.py`（纯 stdlib 的 CookieJar）、`core/download.py`（aiohttp 流式下载 + yt-dlp + 大小/时长限制）、`core/data.py`（数据结构）、`core/utils.py`（ffmpeg 合并）、`core/render.py`（PIL 卡片渲染，仅依赖 PIL/apilmoji）、`core/debounce.py`、`core/exception.py`。
- **不值得搬**：`core/arbiter.py`（多 bot 抢解析的 QQ 表情仲裁，本项目单 bot 场景不需要）、AstrBot 专属的消息事件/发送 API 封装。
- 各平台解析手段差异巨大：B 站/网易云走**官方公开 API**；抖音/小红书/小黑盒走 **HTML 嵌入 JSON 逆向**（小黑盒还需**逆向签名算法**）；YouTube/TikTok 走 **yt-dlp**；Twitter 走 **第三方接口 xdown.app**。难度见 §7 表格。

---

## 1. 整体架构

### 1.1 消息流水线（main.py）

入口 `ParserPlugin.on_message`（main.py:114-226），监听全部消息事件，流程固定：

```
事件 → 白/黑名单过滤(umo) → 消息链非空 → @机制(被@其他bot则跳过)
     → JSON卡片提取(extract_json_url, main.py:154-161) → 引用回复解析(164-173)
     → 关键词+正则双重匹配(main.py:178-188)
     → 仲裁(仅 aiocqhttp 群聊, 192-208) → link防抖(210-214)
     → parser.parse(keyword, searched) → resource_id防抖(219-223)
     → sender.send_parse_result(226)
```

关键设计：

- **匹配是「关键词 + 正则」双重判定**（main.py:178-188）：先看关键词是否在文本里，再跑该关键词对应的正则。所有解析器把 `(keyword, pattern)` 对汇集到一个全局列表 `key_pattern_list`，**按关键词长度降序排序**（main.py:101-102），长关键词优先，避免短词抢匹配（如 `"douyin"` 不会抢走 `"v.douyin"`）。
- **解析器注册**（main.py:67-106）：`BaseParser.get_all_subclass()` 自动收集所有子类（`base.py:89-93` 的 `__init_subclass__` 自动注册）；按配置 `enabled_platforms()` 过滤（config.py:201-202）；**一个平台一个实例**；`parser_map[keyword] = parser`。
- 解析异常在 main.py 里**没有 try/except**，直接冒泡给 AstrBot 框架记录——复刻时建议自行捕获并回一条提示。

### 1.2 解析器协议（core/parsers/base.py + example.py）

```python
# base.py:38-50  装饰器：给方法挂 (keyword, pattern) 对，可叠加多个
def handle(keyword: str, pattern: str): ...

# base.py:53-114  抽象基类
class BaseParser:
    platform: ClassVar[Platform]          # 子类必须声明
    def __init__(self, config, downloader)  # 自带 session(aiohttp, 惰性创建, 带proxy/超时)
    async def parse(self, keyword, searched: re.Match) -> ParseResult   # 分发到 _handlers[keyword]
    async def parse_with_redirect(self, url) -> ParseResult  # 单次重定向(取Location)后再匹配解析
    @classmethod def search_url(cls, url) -> (keyword, Match)  # 遍历本平台 _key_patterns
    @classmethod def result(cls, **kwargs) -> ParseResult      # 构建结果
    # 内容工厂：create_author / create_video_content / create_image_contents /
    #           create_dynamic_contents / create_audio_content / create_graphics_content /
    #           create_file_content / create_video_content_by_task（base.py:223-344）
```

`__init_subclass__`（base.py:89-109）自动收集所有 `@handle` 到 `cls._handlers[keyword]` 和 `cls._key_patterns`，因此**新增平台 = 新建一个继承 BaseParser 的类 + 若干 @handle 方法**，无需改任何注册代码。example.py 给出了完整范例（短链重定向 → API 请求 → 组 contents → 返回 result）。

### 1.3 统一结果结构（core/data.py）——复刻时照抄

```python
# data.py:172-347
@dataclass
class ParseResult:
    platform: Platform            # {name, display_name}
    author: Author | None         # {name, avatar: Path|Task[Path], description}
    title: str | None
    text: str | None
    timestamp: int | None         # 秒
    url: str | None
    contents: list[MediaContent]  # 主内容
    send_groups: list[SendGroup]  # 可选分组发送 {contents, force_merge, render_card}
    extra: dict                   # 额外信息，render 显示 extra["info"]
    repost: ParseResult | None    # 转发内容（递归渲染成嵌套卡片）
    render_image: Path | None
    _resource_id: str             # blake2b(8字节) 内容指纹，用于防抖（data.py:284-347）

# 媒体内容类型（data.py:16-122）——按类型分派下载/发送/渲染
MediaContent (path_task: Path | Task[Path])   # 基类，支持异步 Task 惰性下载
├─ ImageContent
├─ AudioContent  (+ duration)
├─ FileContent   (+ name)
├─ VideoContent  (+ cover: Path|Task, duration)  # .display_duration -> "时长: m:ss"
├─ TextContent   (+ text，无文件路径)
├─ DynamicContent(+ gif_path，视频转gif用)
└─ GraphicsContent(+ text 图前文字, alt 居中描述)  # 渲染时文字在前图片在后
```

- `ParseResult.header`（data.py:201-209）= `"{display_name} @{author} | {title}"`，作为文本 fallback 的头部。
- `get_resource_id()`（data.py:284-347）：对 platform/url/timestamp/author/contents 结构做 O(1) 无 IO 指纹，同链接同内容多次解析得到同一 id，用于「资源级防抖」。

---

## 2. 各平台解析手段（逐平台）

### 2.1 Bilibili（core/parsers/bilibili/）—— 官方 API，难度：中

**手段**：封装第三方库 `bilibili-api-python`（requirements.txt:7），HTTP 层用 `curl_cffi` impersonate chrome131（bilibili/__init__.py:23-29）。底层 endpoint 均为 B 站官方公开 API（`api.bilibili.com/x/web-interface/...` 等，由库内部实现），**匿名可用**；登录（SESSDATA）只用于 AI 总结/更高清/部分风控场景。

| 链接特征（handle 正则） | 接口（经 bilibili-api） | 关键字段 → 输出 |
|---|---|---|
| `b23.tv/xxx`、`bili2233.cn/xxx`（__init__.py:55-60） | 重定向后走下面规则 | — |
| `BVxxx` / `bilibili.com/video/BVxxx?p=n`（62-72） | `Video(bvid).get_info()` + `get_download_url(page_index)` | VideoInfo: bvid/title/desc/duration/owner{name,face}/stat/pages → 视频+封面+AI总结 |
| `av123456` / `/av123456?p=n`（88-98） | 同上（用 aid） | 同上 |
| `bilibili.com/dynamic/{id}`、`t.bilibili.com/{id}`（100-105） | `bilibili_api.dynamic.Dynamic(id, credential).get_info()` | DynamicInfo: author/图片列表/文本 → 图集 |
| `bilibili.com/opus/{id}`（125-129） | `bilibili_api.opus.Opus(id, credential).get_info()` | 段落树(文本/图片节点) → GraphicsContent 列表 |
| `bilibili.com/read/cv{id}`（119-123） | `Article(id).turn_to_opus()` 转 opus 复用 | 同上 |
| `live.bilibili.com/{room}`（107-111） | `LiveRoom(room_display_id, credential).get_room_info()` | 标题/封面/关键帧/主播 → 图片×2 |
| `favlist?fid={id}`（113-117） | `get_video_favorite_list_content(fid)` | 收藏夹封面+简介 → GraphicsContent（注意会被风控） |
| `bmBVxxx`（74-86，音频） | `extract_download_urls` 只取音频流 | 音频 |

**下载流选择**（__init__.py:392-448）：`VideoDownloadURLDataDetecter.detect_best_streams(video_max_quality, codecs, no_dolby_video=True, no_hdr=True)`；dash 返回 `(video_url, audio_url)`，二者并发下载后 **ffmpeg `-c copy` 合并**（utils.py:61-104 `merge_av`，命令 `ffmpeg -y -i v -i a -c copy -map 0:v:0 -map 1:a:0 out`）；MP4 流则直下。请求头必须带 `Referer: https://www.bilibili.com/`（__init__.py:39-44）。
**AI 总结**：有登录态时 `video.get_ai_conclusion(cid)`（__init__.py:159-167），结果放 `extra["info"]`。

### 2.2 抖音 Douyin（core/parsers/douyin/）—— HTML 逆向，难度：中偏高

**手段**：抓分享页 HTML 里的 `window._ROUTER_DATA` JSON（douyin/__init__.py:199-228），**不登录**，但需要匿名 `ttwid` cookie（自动注册）。

| 链接特征 | 请求 | 关键字段 → 输出 |
|---|---|---|
| `v.douyin.com/xxx` 短链（73-77） | 重定向（`allow_redirects=False` 取 Location，__init__.py:175-197，顺带收 Set-Cookie） | → 长链接走下面 |
| `douyin.com/video|note/{vid}`、`m.douyin.com/share/...`、`iesdouyin.com/share/...`、`jingxuan.douyin.com/m/...`（84-91） | 构造 canonical 页 `https://www.iesdouyin.com/share/{ty}/{vid}/`，iOS UA GET，正则抓 `window\._ROUTER_DATA\s*=\s*(.*?)</script>`（212-215） | RouterData.loaderData["video_(id)/page"|"note_(id)/page"].videoInfoRes.item_list[0] → VideoData{create_time, author.nickname, desc, images, video.play_addr/cover/duration} |
| `aweme_id=xxx`、裸 18-20 位数字（81-83） | 同上 | 同上 |

**ttwid 注册**（__init__.py:117-173）：`POST https://ttwid.bytedance.com/ttwid/union/register/`，JSON body `{"region":"cn","aid":1768,"needFid":false,"service":"www.iesdouyin.com","union":true,"fid":""}`，从 `Set-Cookie` 捕获 `ttwid`（domain=iesdouyin.com），必要时再 GET `redirect_url` 补 cookie。

**去水印**（两条路，__init__.py:243-265）：
1. `play_addr.url_list` 中 URL 做 `"playwm" → "play"` 字符串替换（douyin/video.py:55）；
2. 优先用 `play_addr.uri`（video_id）探测无水印 play 端点：`GET https://aweme.snssdk.com/aweme/v1/play/?video_id={id}&ratio={ratio}`，ratio 依次试 `1080p/720p/540p/360p`（__init__.py:291-325），带 `Range: bytes=0-1` 看 `Content-Range` 拿总大小，**选最大者**；失败回退 play_addr。

**图集 slides**（__init__.py:339-392）：`GET https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/?aweme_ids=[{vid}]&request_source=200`，**Android UA**；返回 `aweme_details[0]` → `images[].url_list`（图片）+ `images[].video.play_addr.url_list`（动态，下载后转 gif 的 DynamicContent）。

### 2.3 TikTok（core/parsers/tiktok.py）—— yt-dlp，难度：中（网络前提）

整文件 53 行：`vt/vm.tiktok.com` 短链先 `get_redirect_url`（tiktok.py:28-30），然后全部交给 yt-dlp：`ytdlp_extract_info`（标题/缩略图/时长/频道）+ `ytdlp_download_video(format="best")`（tiktok.py:32-46）。cookie 以 Netscape 文件形式喂给 yt-dlp（cookiejar.cookie_file）。**必须能访问境外网络**。

### 2.4 小红书 XHS（core/parsers/xhs.py）—— HTML 逆向，难度：中偏难

**手段**：GET 笔记详情页抓 `window.__INITIAL_STATE__` JSON（xhs.py:216-223，`undefined→null` 替换后 json.loads）。**强依赖 cookie**（web_session 等）且 URL 里必须带 `xsec_token`。

| 链接特征 | 请求 | 关键字段 → 输出 |
|---|---|---|
| `xhslink.com/xxx`、`xhslink.cn/xxx`（45-49） | 重定向（iOS 头） | → 长链接 |
| `xiaohongshu.com/explore/{xhs_id}?xsec_token=...`（52-66） | 浏览器头 GET explore 页 | `note.noteDetailMap[xhs_id].note` → NoteDetail{type,title,desc,user.nickname/avatar,imageList[].urlDefault,video} |
| `xiaohongshu.com/discovery/item/{xhs_id}?xsec_token=...`（52-66） | iOS 头 GET discovery 页（explore 失败时 fallback） | `noteData.data.noteData` → NoteData + `normalNotePreloadData`（**无水印图**，xhs.py:186-193） |

**视频去水印**（xhs.py:226-253）：`video.media.stream` 选 `h265 > h264 > av1 > h266` 的 `masterUrl`（h265 无水印、h264 有水印）。无 cookie 时 `noteDetailMap` 通常为空或直接登录墙 → ParseException（xhs.py:220）。

### 2.5 小黑盒 Xiaoheihe（core/parsers/xiaoheihe.py）—— 官方 API + 逆向签名，难度：难

**手段**：官方 API + **自研逆向签名**（hkey/_time/nonce）+ 设备指纹（V4_EP/V4_DATA 常量，xiaoheihe.py:19-117），HTTP 用 curl_cffi impersonate chrome131（xiaoheihe.py:1051-1066）。

| 链接特征 | 请求 | 关键字段 → 输出 |
|---|---|---|
| `xiaoheihe.cn/app/bbs/link/{link_id}`（137-142） | `GET https://api.xiaoheihe.cn/bbs/app/link/tree`，query 带 `os_type=web&app=heybox&client_type=web&version=999.0.4&x_client_type=web&x_app=heybox_website&device_id=...&link_id=...&owner_only=1` + 签名 `{hkey,_time,nonce}` + cookie `x_xhh_tokenid`（358-392） | `result.link` → title/user/text(JSON blocks)/images/has_video/video_url |
| `api.xiaoheihe.cn/v3/bbs/app/api/web/share?link_id=`（144-149） | 同上 | 同上 |
| `xiaoheihe.cn/app/topic/game/{type}/{appid}`（160-167） | GET 游戏页 HTML，抓 `<script id="__NUXT_DATA__">`，devalue 解引用（410-464），启发式找 game dict（466-513） | game{name,name_en,score,price,screenshots,video_url} |
| `api.xiaoheihe.cn/game/share_game_detail?appid=`（151-158） | 同上 | 同上 |
| 补充（346-356） | `GET https://api.xiaoheihe.cn/game/game_introduction/?steam_appid=X&return_json=1` | about_the_game/release_date/developers/publishers |

**token 自动获取**（289-344）：`POST https://fp-it.portal101.cn/deviceprofile/v4`，body `{appId:"heybox_website", organization:"0yD85BjYvGFAvHaSQ1mc", ep:V4_EP, data:V4_DATA, os:"web", encode:5, compress:2}` → `detail.deviceId` → token = `"B" + device_id`。**签名算法**（949-1035）：`_ov/_sv/_av/_interleave/_mix_columns`（AES 列混合 + 字符表 AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89 映射）。
视频：link 的 `video_url` 直下；.m3u8 用 `ytdlp_download_video_relaxed`（842-854）。图片只收 `imgheybox.max-c.com` 域（915-930）。

### 2.6 YouTube（core/parsers/youtube.py）—— yt-dlp，难度：中（网络前提）

- 视频：`ytdlp_extract_info` + `ytdlp_download_video(format="bv*[height<=720]+ba/b[height<=720]", js_runtimes={"node":{}})`（youtube.py:40-57，node 用于 JS 解混淆）；**超时长只发封面图**（49-66）；`ym` 前缀命令 → `ytdlp_download_audio`（flac，75-109）。
- 作者信息单独调**官方 InnerTube API**：`POST https://www.youtube.com/youtubei/v1/browse?prettyPrint=false`，body `{context:{client:{clientName:"WEB",clientVersion:"2.20251002.00.00",hl:"zh-HK",gl:"US",...}}, browseId: channel_id}` → `metadata.channelMetadataRenderer`（title/description/avatar.thumbnails[0].url）（youtube.py:111-144）。
- 需要 cookie（否则部分媒体无法解析，youtube.py:23-24 警告）+ 代理。

### 2.7 Twitter/X（core/parsers/twitter.py）—— 第三方接口，难度：中但脆弱

- **第三方解析站 xdown.app**：`POST https://xdown.app/api/ajaxSearch`，form `{q: 推文URL, lang: "zh-cn"}`，头带 `Origin/Referer: https://xdown.app/`（twitter.py:30-43）。`resp.status == "ok"` 时 `data` 是渲染好的 HTML。
- HTML 解析（73-141）：`img` → 封面；`a.tw-button-dl` / `a.abutton` 的**文本**判断类型——含「下载 MP4」→ 视频直链、含「下载图片」→ 图片列表、含「下载 gif」→ gif（DynamicContent）；`h3` → 标题。作者恒为「无用户名」。
- 链接特征：`twitter.com/{user}/status/{id}`、`x.com/{user}/status/{id}`（45-58）。

### 2.8 网易云 NCM（core/parsers/ncm.py）—— 官方 API，难度：容易

| 链接特征 | 请求 | 关键字段 → 输出 |
|---|---|---|
| `music.163.com/#/song?id=X`、`y.music.163.com/m/song?id=X`（32-33） | ① `GET https://music.163.com/api/song/detail/?id=X&ids=[X]` ② `GET https://music.163.com/api/song/enhance/player/url?ids=[X]&br=320000`（36-39） | ① songs[0]: name/alias/album.name/picUrl/artists[].name/img1v1Url/duration ② data[0].url 播放地址 |
| `163cn.tv/xxx`（26-30） | 302 重定向后走上面 | 同上 |
| `music.126.net/*.mp3`（88-97） | 直链下载 | 音频 |
| `music.163.com/song/media/outer/url?...`（99-113） | 直链下载 | 音频 |

带 `Referer: https://music.163.com`。**坑**：代码把音频包成 `VideoContent`（ncm.py:73-75）发送——复刻时直接发 audio/record 即可。VIP 歌曲 `data[0].url` 为 null；匿名下 enhance/player/url 偶发风控，配 MUSIC_U cookie 更稳。

---

## 3. 渲染层与发送层

### 3.1 渲染（core/render.py）—— PIL 图片卡片，**不是 HTML 模板**

- `Renderer.render_card(result)`（render.py:422-437）：两遍式——先 `_calculate_sections` 量高度（render.py:530-601），再 `_draw_sections` 逐段绘制（871-892），输出 PNG 落盘 `cache_dir/card_{uuid}.png`。
- 卡片 800px 宽白底（render.py:243），段落按序：Header（圆形头像 + 蓝色昵称 + 灰色时间 + 右上平台 logo，957-1006）→ 标题（1008-1018）→ 封面（缩放到内容宽度、居中叠加 30% 透明播放按钮，1020-1036）→ 图片网格（1020-1036/1133-1202：1 张全宽；2/4 张 2 列；其余 3 列九宫格，最多 9 张，超出叠「+N」半透明遮罩，1204-1235）→ 正文 → extra → 转发卡片（递归渲染后 0.88 缩放嵌灰底圆角框，703-717/1096-1131）。
- 字体：内置 `core/resources/HYSongYunLangHeiW-1.ttf`（render.py:297），`FontInfo` 做逐字宽度缓存 + CJK 宽度优化（60-102）；emoji 由 `apilmoji` 从 jsdelivr CDN 拉取（311-316，config.py:239）。
- `_wrap_text`（1321-1391）：像素级自动换行，标点不落行首。
- **复刻建议**：render.py 除 `astrbot.api.logger` 外不依赖 AstrBot，可直接搬运；若不需要图片卡片，可只保留 `ParseResult.header` + 文本 + 直发媒体（见 3.2 降级路径）。

### 3.2 发送（core/sender.py）

`MessageSender.send_parse_result`（sender.py:313-345）策略：

1. **发送计划**（79-126）：contents 分 light（Image/Graphics/Text）与 heavy（Video/Audio/File/Dynamic）；`render_card = 仅单一重媒体且无轻媒体且配置 single_heavy_render_card`；段数 ≥ `forward_threshold` 时 `force_merge`。
2. **预览卡片**（128-146）：render_card 且未合并时，卡片作为独立消息先发。
3. **构建消息段**（148-224）：`Image.fromFileSystem` / `Video.fromFileSystem` / `Record.fromFileSystem`（音频按配置 `audio_to_file` 转 `File(name, file=file_uri)`）/ `File`；下载失败按异常类型降级（见 §5）。
4. **合并转发**（226-248）：`Nodes([Node(uin=self_id, name="解析器", content=[seg])...])`——OneBot 合并转发，以机器人自身身份。
5. **全失败 → 文本 fallback**（250-261）：`header + text/info` 拼成纯文本发送。

### 3.3 下载器（core/download.py）

- `streamd`（83-151）：aiohttp 流式（1MB chunk），**三重大小限制**——`Content-Length` 预检、`Content-Length: 0` 抛 ZeroSizeException、边下边累计超 `max_size` 抛 SizeLimitException（114-129）；重试 `download_retry_times` 次（退避 1+attempt 秒）；代理 per-parser 可配；文件已存在直接复用（97-98）；文件名 = URL md5 前 16 位 + 后缀（utils.py:194-210）。
- yt-dlp 封装（265-446）：`ytdlp_extract_info`（skip_download，msgspec 校验成 VideoInfo，带 `LimitedSizeDict` 缓存）、`ytdlp_download_video`（时长超 `max_duration` 抛 DurationLimitException；ffmpeg 转 mp4）、`ytdlp_download_audio`（转 flac）、`ytdlp_download_video_relaxed`（宽松找产物）。
- `download_av_and_merge`（245-263）：B 站 dash 视频+音频并发下载 → `merge_av`（ffmpeg `-c copy`）。

---

## 4. Cookie 管理（core/cookie.py）

**纯 stdlib 实现，可整体搬走**。核心：

```python
# cookie.py:14-59
@dataclass
class Cookie: domain, path, name, value, secure, expires   # + is_expired/match

# cookie.py:62-81
class CookieJar(config, parser_cfg, domain):
    cookie_file = data_dir / "cookies" / f"{parser_cfg.name}_cookies.txt"  # Netscape 格式
```

- **三个来源**（62-81）：① 配置里的 `cookies` 字符串（自动识别「header 分号格式」或「Netscape 文件格式」，142-276）；② 磁盘文件加载（307-329）；③ **响应 Set-Cookie 自动更新**（`update_from_response`，333-439：按 name/domain/path 合并，过期清理 `purge_expired`，自动写盘）。
- 对外：`get_cookie_header_for_url(url)`（105-113）按 URL 域名/path/secure 精确取匹配 cookie（domain 匹配支持 `.suffix` 通配，41-48）。

**各平台所需 cookie**：

| 平台 | 关键 cookie | 获取方式 |
|---|---|---|
| Bilibili | SESSDATA、DedeUserID、bili_jct、ac_time_value | 配置填写或扫码登录（`blogin` 命令，main.py:244-252）→ `bilibili_credential.json`（login.py:17-31）；`credential` 属性自动 check_valid/check_refresh（login.py:103-132） |
| 抖音 | `ttwid`（iesdouyin.com） | **匿名自动注册**（§2.2），不填也能用 |
| 小红书 | `web_session`（等全套） | 手动填配置，**必备** |
| 小黑盒 | `x_xhh_tokenid` | 自动生成 `B{device_id}`（§2.5），也可手动填 |
| YouTube/TikTok | 完整登录 cookie | 手动填，转 Netscape 文件喂 yt-dlp |
| Twitter | xdown.app cookie | 可选 |
| 网易云 | MUSIC_U（可选，VIP 稳定用） | 手动填 |

---

## 5. 失败与降级 / 防刷防重

### 5.1 异常体系（core/exception.py）

```
ParseException
├─ TipException
├─ DownloadException
│   ├─ DownloadLimitException
│   │   ├─ SizeLimitException      # 超大小
│   │   └─ DurationLimitException  # 超时长
│   ├─ ZeroSizeException           # 0 字节
│   └─ RedirectException           # 重定向失败
```

### 5.2 发送层降级（sender.py）

- 轻媒体下载失败：跳过；`show_download_fail_tip` 开启时补一句「此项媒体下载失败」（174-181）。
- 重媒体超限：提示「此项媒体超过时长/大小限制」（198-206）。
- **全部失败 → 文本 fallback**（`_build_text_fallback`，250-261）——保证永远有东西回。
- 发送计划保证「单一重媒体 + 卡片」不刷屏；段数超阈值合并转发（§3.2）。

### 5.3 解析层降级（各 parser 内）

- 小红书：explore 失败自动 fallback discovery（xhs.py:60-66）。
- 抖音：play 端点探测失败回退 `play_addr` 直链（douyin/__init__.py:249-259）；canonical 页失败统一提示「分享已删除或资源直链提取失败」（105-107）。
- 小黑盒：m3u8 → yt-dlp；图片按域过滤去噪。
- B 站：无 cookie 时 AI 总结降级为提示文案（__init__.py:166-167）。

### 5.4 防刷/防重（core/debounce.py + arbiter.py）

- `Debouncer`（debounce.py:8-47）：**会话级**（`{session: {key: ts}}`）双通道——`hit_link(umo, link)` 在解析前（main.py:212，短链原文）与 `hit_resource(umo, resource_id)` 在解析后（main.py:221，内容指纹，§1.3），间隔 `debounce_interval` 秒，≤0 禁用。
- `EmojiLikeArbiter`（arbiter.py:50-200）：多 bot 并存时用**表情点赞**竞争——`set_msg_emoji_like(emoji_id=289)` 占坑 → 1 秒窗口收集 `fetch_emoji_like` 参与者 → 确定性顺序 `(msg_time//60) % n`（196-199）→ 表情 124 递补确认。**本项目单 bot 不需要**。

---

## 6. 许可证

- **MIT License**（LICENSE:1），Copyright (c) 2024 Les Freire——可自由使用/修改/再分发，仅需保留版权声明。
- 本项目 README（README.md:148）注明核心代码源自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser)（同为开源项目）。**移植逻辑到本项目（含商用）无许可证障碍**；若要搬运大段代码，建议同时保留两个版权声明（MIT 要求保留原声明）。
- 注意第三方依赖各自的许可/条款：yt-dlp（Unlicense）、bilibili-api-python（MIT）、curl_cffi（MIT）、apilmoji 等均宽松；但**平台 ToS 风险**（逆向接口）属于运营层面问题，与许可证无关。

---

## 7. 坑与难度评估（逐平台）

| 平台 | 难度 | 原因 / 坑 |
|---|---|---|
| Bilibili | 中 | 依赖 `bilibili-api-python` + `curl_cffi`（需二进制/编译，Windows 有预编译 wheel）；dash 下载必须带 Referer 否则 403；高清（1080P+）部分需登录；favlist 有风控（__init__.py:362）；AI 总结必须登录；hvc1→hev codec 归一化 hack（__init__.py:421-424） |
| 抖音 | 中偏高 | ttwid 注册接口与 `_ROUTER_DATA` 结构随时可能变；必须 iOS UA + Referer；无水印需 play 端点探测或 playwm→play 替换；slides 接口要 Android UA |
| 小红书 | 中偏难 | **无 cookie 基本不可用**（登录墙）；URL 必须带 `xsec_token`（分享链接自带）；`__INITIAL_STATE__` 里 `undefined` 需替换；风控严、易触发验证码；图床 URL 需 `urlDefault/urlSizeLarge` 字段 |
| 小黑盒 | **难** | 需要**逆向签名算法**（hkey：`_ov/_sv/_av/_interleave` + AES 列混合，949-1035）与**设备指纹常量**（V4_EP/V4_DATA，19-117，疑似加密载荷，可能过期）；必须 curl_cffi impersonate chrome131；`__NUXT_DATA__` devalue 反序列化 + 启发式找 game dict（易碎）；token 生成链路（fp-it.portal101.cn）若变更则全挂 |
| YouTube | 中（网络前提） | 必须代理；yt-dlp 需要 node.js runtime 做 JS 解混淆（download.py:358-359 `js_runtimes`）；browse API 需匹配 clientVersion；无 cookie 时部分视频不可解析 |
| TikTok | 中（网络前提） | 必须代理；短链重定向；yt-dlp 格式选择受平台风控影响 |
| Twitter/X | 中但**脆弱** | 依赖第三方 `xdown.app`（可能限流/付费/跑路，接口是 form 提交返回 HTML）；HTML class 名（tw-button-dl/abutton）易变；拿不到作者名 |
| 网易云 | **容易** | 纯官方 API、参数简单；坑点：VIP 歌曲 url 为 null、匿名偶发风控（可配 MUSIC_U）、源码把音频包成 VideoContent 发送（复刻时修正）；163cn.tv 短链需重定向 |

**通用坑**：
- 短链解析依赖 `Location` 头单次跳转（base.py:175-196），某些平台跳两次（`get_final_url` 可多次，198-221）。
- JSON 卡片提取 `extract_json_url`（utils.py:231-306）：QQ 卡片的真实 URL 藏在 `meta.miniapp.legacyUrl` 等 18 个字段路径里，且有 QZone/b23.tv/xhslink 的优先关键词排序——**复刻时直接抄这份优先级表**。
- 媒体直链普遍有过期时间（抖音 play、B 站 dash 均有 ttl），**拿到 URL 后应立即下载**，不要等渲染完再下（本插件下载与渲染并行：`path_task: Task[Path]`）。
- 无 cookie 时的行为要可预期：抖音/小黑盒/B 站/网易云匿名可用；小红书必须 cookie；YouTube/TikTok 必须有网络。

---

## 8. 在本项目（NoneBot2 + bot_unified_runtime）中复刻的映射方案

本项目已有同构骨架（`plugins/bot_unified_runtime/contracts/media.py`、`sources/registry.py`），**不需要把 AstrBot 的插件外壳搬过来，只需移植核心逻辑**：

### 8.1 映射表

| AstrBot 插件 | bot_unified_runtime 对应物 |
|---|---|
| `@handle(keyword, pattern)` + BaseParser 自动注册（base.py:38-109） | `ParserRule(parser_id, source_id, keyword_patterns=[...], url_patterns=[...], priority)` 注册进 `ParserRegistry`（registry.py:8-34，已按最长关键词+priority 排序，等价于 main.py:101-102 的长关键词优先） |
| `key_pattern_list` 双重匹配（main.py:178-188） | `ParserRegistry.match(SourceInput)`（registry.py:15-34）——**直接复用，零移植成本** |
| `ParseResult` + `MediaContent` 体系（data.py） | `ParsedMediaItem` / `NormalizedMediaItem`（media.py:69-107）。建议为 `media` 列表元素定义子 schema：`{kind: image|video|audio|file|graphics|text, path_or_url, cover, duration, text, alt, name}`，一一对应 MediaContent 子类 |
| `parse_with_redirect` / `search_url`（base.py:146-168） | 可整段搬到平台 parser 基类（与 AstrBot 无耦合） |
| `Downloader`（download.py）+ `CookieJar`（cookie.py）+ `utils.merge_av` | **直接拷贝**（仅 `astrbot.api.logger` 换成 nonebot 的 logger；`config` 换成 bot_unified_runtime 的 Config/数据目录） |
| `Renderer`（render.py，PIL 卡片） | 直接拷贝；或跳过卡片，用 `NormalizedMediaItem.title/body` 文本 + 直发媒体 |
| `MessageSender`（sender.py） | 换成 NoneBot2 消息构造：`MessageSegment.image(file=Path)` / `video` / `record` / `file`；合并转发用 `MessageSegment.forward`（构造 `Message` 列表）；本项目 `sender/onebot.py` 已有发送通道，产出 `Message` 后接入即可 |
| 文本 fallback（sender.py:250-261） | `NormalizedMediaItem.title/body/creator` 直接可用 |
| `Debouncer`（debounce.py） | 现有 `ParseRequest.cache_key/dedupe_key`（media.py:63-64）承载；如需「link 防抖」可照搬 debounce.py（纯 dict+time） |
| `EmojiLikeArbiter`（arbiter.py） | 不需要（单 bot） |
| 每平台 `cookies` 配置 + CookieJar | 直接复用 CookieJar；cookie 文件放插件数据目录，配置项照抄 §4 表格 |

### 8.2 每平台落地清单（输入链接特征 → 请求 → 字段 → 渲染输出）

| 平台 | 链接特征（url_patterns） | 请求 | 取哪些字段 | 渲染输出 |
|---|---|---|---|---|
| Bilibili | `b23.tv/...`、`BV[0-9a-zA-Z]{10}`、`av\d{6,}`、`/dynamic/\d+`、`/opus/\d+`、`/read/cv\d+`、`live.bilibili.com/\d+` | bilibili-api（官方 API，匿名可用） | title/desc/duration/owner.name/owner.face/stat/pages；dash v+a URL | 卡片(标题+封面+统计) + mp4 视频；动态→图集；直播→封面图×2 |
| Douyin | `v.douyin.com/...`、`douyin.com/(video\|note)/\d+`、`iesdouyin.com/share/...`、`aweme_id=\d+` | ttwid 注册 + `iesdouyin.com/share/{ty}/{vid}/` 抓 `_ROUTER_DATA`；play 端点去水印 | desc/create_time/nickname/avatar/play_addr(uri)/cover/duration；slides 走 slidesinfo API | 视频(mp4 无水印) + 封面；note→图集；slides→图片+动态 |
| TikTok | `(www\|vt\|vm).tiktok.com/...` | yt-dlp（代理前提） | title/channel/thumbnail/duration/timestamp | mp4 视频 + 封面 |
| XHS | `xhslink.com/...`、`xiaohongshu.com/(explore\|discovery/item)/[0-9a-zA-Z]+\?...` | GET 详情页抓 `__INITIAL_STATE__`（需 cookie+xsec_token） | noteDetailMap[xhs_id].note：type/title/desc/user/imageList/video.stream(h265优先) | 视频(masterUrl) 或 图集（无水印图）；文字 desc |
| Xiaoheihe | `xiaoheihe.cn/app/bbs/link/...`、`api.xiaoheihe.cn/...web/share?link_id=`、`xiaoheihe.cn/app/topic/game/...` | link/tree API（签名+token）；游戏页 `__NUXT_DATA__`；game_introduction API | link: title/text(JSON blocks)/images/video_url；game: name/score/price/screenshots/video_url | 图集+视频（m3u8 走 yt-dlp）；游戏详情卡片 |
| YouTube | `youtu.be/...`、`youtube.com/(watch\|shorts)...` | yt-dlp + youtubei/v1/browse（作者信息） | title/duration/thumbnail/timestamp/channel | mp4(≤720P) + 封面；超时长只发封面；`ym` 前缀→flac |
| Twitter | `(twitter\|x).com/.../status/\d+` | xdown.app ajaxSearch（第三方） | HTML: a.tw-button-dl/abutton href（按文本区分 mp4/图/gif）、h3 | 视频/图集/gif；标题 |
| NCM | `music.163.com/#/song?id=`、`163cn.tv/...`、`music.126.net/*.mp3` | `api/song/detail/` + `api/song/enhance/player/url?br=320000`（官方，匿名可用） | name/artists/album.picUrl/duration + data[0].url | 音频（record/file）+ 封面（**建议发 audio，不要照抄它包成 VideoContent 的写法**） |

### 8.3 建议实施顺序（按难度/性价比）

1. **地基**：搬 `exception.py` / `data.py` / `utils.py` / `download.py` / `cookie.py` / `debounce.py`，写 `SourceInput → ParseRequest` 适配与 `media` 条目 schema。
2. **B 站 + 网易云**（官方 API，最容易跑通全链路）。
3. **抖音**（HTML 逆向 + ttwid，去水印逻辑照抄）。
4. **YouTube/TikTok**（yt-dlp 封装现成，配代理与 node 运行时）。
5. **小红书**（需 cookie，先出「未配置 cookie 提示」降级）。
6. **小黑盒 / Twitter**（依赖逆向签名与第三方服务，最后做，且默认关闭）。
