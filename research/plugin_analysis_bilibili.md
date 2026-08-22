# NoneBot B站相关插件源码分析报告（可借鉴）

> 分析日期：基于 10 个 GitHub 仓库最新源码（tar.gz 解压于 `research/plugin_sources/`）。
> 目标：为 `plugins/bot_unified_runtime` 统一流水线提供「可借鉴点 + 端点清单 + 整合优先级」。
> 现有流水线已具备：B站视频/直播/空间/收藏夹/动态(opus)/番剧解析（`sources/parsers/platforms_bilibili.py`）+ yt-dlp 下载（`capabilities/download.py`）+ 媒体分析 + 统一发送审计；能力经 `build_xxx_capability(...) -> CapabilityResult` 返回；凭据走 `sources/credentials.py`（Netscape cookie 文件 / `BOT_CREDENTIAL_BILIBILI` 环境变量）。

## 总览

| # | 插件 | 许可证 | 核心机制 | 可用性 | 整合优先级 |
|---|------|--------|----------|--------|-----------|
| 1 | bilicover（封面提取） | MIT | 裸调 `view` 取 `data.pic` | 部分能用 | 低 |
| 2 | bilibili-image（图片） | AGPL-3.0 | 裸调 view/article/dynamic 接口 | 部分能用（动态/专栏基本失效） | 低~中 |
| 3 | searchBiliInfo（信息搜索） | MIT | 官方接口 + 大量第三方 VTB 接口 | 部分能用（第三方多已挂） | 低~中 |
| 4 | bili-helper（助手） | MIT | 自实现 WBI 签名 + BV↔AV + 评论截图 | 部分能用 | 高（抽 wbi/bv2av） |
| 5 | bililive（直播/动态订阅） | AGPL-3.0 | 批量直播接口 + polymer 动态 + Playwright 截图 | 部分能用 | 中 |
| 6 | parser（链接解析） | MIT | 委托 `bilibili-api-python` SDK（wbi/curl_cffi） | 能用 | 高 |
| 7 | bilidownloader-woju（下载） | MIT | SDK `wbi/playurl` DASH + ffmpeg 合并 | 能用 | 中 |
| 8 | bili-query（查询/订阅） | MIT | SDK wbi + sqlite 订阅推送 | 能用 | 中 |
| 9 | bili2mp4（转 mp4） | MIT | 委托 yt-dlp（player_client android/web） | 能用 | 中~低 |
| 10 | bililivedm（直播弹幕） | **无 LICENSE** | WebSocket 弹幕协议栈（protover3/brotli） | 部分能用 | 高（协议栈） |

**关键共性结论**：
- 2019–2022 年的老插件（1/2/3）普遍**裸调 API、无 wbi 签名、无 buvid3/b_nut/dm_img**，面对 B站 2023 年后风控加固（wbi 签名强制、`-352` 风控、评论/动态/专栏需登录 cookie）已大面积失效或仅剩公开接口可用。
- 2024–2026 年的新插件（6/7/8/9）普遍**改用 `bilibili-api-python` SDK 或 yt-dlp 来"免费获得" wbi 签名与风控绕过**，自身几乎不写裸 HTTP。
- 我们现有 `platforms_bilibili.py` 仍属"裸 API + cookie"一代，**未实现 wbi 签名、无 curl_cffi 模拟浏览器、opus 走的是 `polymer/detail` 而非更合适的 `opus/detail`**，是本次借鉴的重点。

---

## 1. A-kirami/nonebot-plugin-bilicover（B站封面提取）

**仓库**：`nonebot-plugin-bilicover-master`，License **MIT**。

### 功能与命令
提取 B站视频封面。触发词 `on_startswith(("提取封面","B站封面","bilibili封面","B站封面提取"))`，参数为正则抓取 `BV`/`av` 号（`__init__.py:8-28`）。无短链解析。

### 依赖
`nonebot2>=2.0.0b2`、`nonebot-adapter-onebot>=2.0.0b1`、`httpx>=0.23.1`；Python ≥3.8。

### API/endpoint（全插件仅 1 个）
- **GET** `https://api.bilibili.com/x/web-interface/view`
  - params：`bvid` 或 `aid`
  - headers：`User-Agent: Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 Chrome/64.0.3282.167`、`Referer: https://www.bilibili.com`，**无 Cookie**
  - 返回字段：`content["data"]["pic"]`（封面原图 URL），再 `client.get(cover_url)` 取图片字节 `MessageSegment.image(image.content)`。

### 凭据
无（不注入 SESSDATA、无 wbi、无 buvid）。

### 亮点算法
无实质算法：直接取 `data.pic`，**无清晰度/尺寸选择、无 @ 后缀裁剪、无 wbi、无短链**。正则 `(?P<bv>bv\w+)|(?P<av>av\d+)`（`re.I`），`\w` 在 Python3 会吞中文，属潜在小 bug。

### 可用性：部分能用
`view` 接口仍是主流、未强制 wbi，封面场景一般可跑通；但无 cookie/旧 UA/无 buvid 在高风控下可能触发 `-352`。

### 整合建议（低）
与现有「B站视频解析」**完全重叠**（`pic` 就是 `view` 返回字段之一，我们 `_lookup_video_by_id` 已取 `data.pic`）。**不要独立实现**；如需高清封面可自行对 `pic` 做 URL 改造（去 `_...` 后缀/换 `@` 尺寸），本插件未做。

---

## 2. jcjrobert/nonebot-plugin-bilibili-image（B站图片）

**仓库**：`nonebot-plugin-bilibili-image-master`，License **AGPL-3.0**（⚠️ 强 copyleft，复用需开源，注意传染）。

### 功能与命令
封面提取 + 动态图片 + 专栏图片。命令（`on_command`，priority=12，block）：
- `b站封面/B站封面 + bv号/url/短链`（不支持 av 号）
- `动态图片/动态下载/动态获取 + 动态id/url/短链`
- `专栏图片/专栏下载/专栏获取 + cv号/url/短链`

依赖 go-cqhttp 专属 API：`send_group_forward_msg`（合并转发预览）、`upload_group_file/upload_private_file`（zip 上传）。

### 依赖
`nonebot2>=2.0.0-beta.4`、`nonebot-adapter-onebot`、`httpx>=0.19.0`、`beautifulsoup4>=4.0.0`。

### API/endpoint
- **GET** `https://api.bilibili.com/x/web-interface/view?bvid={bvid}`（`video.py:30`）→ `data.title/owner.name/tname/pic`
- **GET** `https://api.bilibili.com/x/article/viewinfo?id={cvid}`（`article.py:32`）→ `data.banner_url/title`
- **GET** `https://www.bilibili.com/read/cv{cvid}`（HTML，`article.py:54`）→ BeautifulSoup `#article-content` 下 `<img data-src>`，补 `https:` 前缀
- **GET** `https://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/get_dynamic_detail?dynamic_id={did}`（`dynamic.py:32`）→ `resp["data"]["card"]`，若 `card.desc.type==2`（图片动态）→ `json.loads(card.card)["item"]["pictures"]` 逐个取 `p["img_src"]`

请求头仅 UA（Chrome/96），**无 Referer、无 Cookie、无 wbi/buvid/b_nut/dm_img**。

### 凭据
无 Cookie。配置：`nickname`、`max_forward_msg_num`（合并转发条数上限）、`bilibili_image_save_local`。

### 亮点算法
- `b23.tv` 短链：`httpx.AsyncClient(follow_redirects=True)` 取重定向后 URL（video/article/dynamic 三处各自实现）。
- 正则解析：`(av|BV)[0-9a-zA-Z]+`、`(cv|id=)[0-9]+`、动态取第一个数字。
- 图片动态过滤 `desc.type==2`；专栏 `banner_url` 首图 + 正文懒加载 `data-src` 图。
- `zip_images`（ZIP_BZIP2）+ `imghdr` 识别扩展名；`retry` 3 次/间隔 3s；合并转发按 `ceil(len/max)` 分片。

### 可用性：部分能用（动态/专栏基本失效）
- 封面可用（`view` 仍稳）。
- 动态 `dynamic_svr/get_dynamic_detail` **需 SESSDATA**，无 cookie 时返回 `-101` 或被风控 → 失效。
- 专栏 `article/viewinfo` + `read/cv` 页面无 wbi/无 buvid 易 `-352`，且正文懒加载 `data-src` 前端已改版 → 很可能失效。

### 整合建议（低~中）
封面/动态图片与现有解析**重叠**（直接复用现有 `pic` 与动态 `pictures/img_src`）。唯一增量是**专栏图片抓取**思路（`x/article/viewinfo` + `read/cv`），但必须补 **wbi + SESSDATA + 新 UA**。可借鉴的通用技巧：`b23.tv` 重定向、动态 `type==2` 过滤、banner 首图策略。**不要借鉴** go-cqhttp 专属 API（已废弃）；AGPL-3.0 代码直接复用有传染风险。

---

## 3. Ikaros-521/nonebot_plugin_searchBiliInfo（B站信息搜索）

**仓库**：`nonebot_plugin_searchBiliInfo-master`（v1.8.1），License **MIT**。

### 功能与命令
B站用户/主播信息查询 + VTB 数据看板。命令（`on_command`/`on_regex`，`__init__.py:115-157`）：`/查`、`/查直播`、`/查舰团`、`/查昵称`、`/查收益`、`/查观看`、`/查弹幕`、`/查牌子`、`/查人气`、`/查装扮`、`/营收`、`/涨粉`、`/DD风云榜`、`/v详情` `/v直播势` `/v急上升` `/v急下降` `/v舰团` `/vdd` `/v宏观`、`/dmk查用户` `/dmk查直播` `/dmk分析`、`/blg查弹幕` `/blg查入场` `/blg查礼物` `/blg直播记录` `/blg直播间sc`、`/lap查用户` `/lap查牌子` `/lap查充电` `/lapdd排行榜`、`/zero查用户` `/zero被关注`、`斗虫`、`/eh查直播`、`/vtb网站`。

### 依赖
`aiohttp`、`nonebot2`、`nonebot-adapter-onebot`、`nonebot-plugin-htmlrender`；Python ^3.8。无 wbi 库。

### API/endpoint
请求头（`__init__.py:98-110`）：`content-type: text/plain`、`cookie`（由 env `searchBiliInfo_cookie` 填充）、UA（QQ浏览器 Chrome/94）。**无 Referer、无 wbi、无 csrf**。

**A. B站官方接口（稳定，可借鉴）**：
- `GET https://account.bilibili.com/api/member/getCardByMid?mid={uid}` → `card.name/mid/fans`
- `GET https://api.live.bilibili.com/xlive/app-room/v2/guardTab/topList?roomid={room_id}&page=1&ruid={uid}&page_size=0` → `data.info.num`（舰团数）
- `GET https://api.live.bilibili.com/room/v2/Room/room_id_by_uid?uid={uid}` → `data.room_id`
- `GET https://api.bilibili.com/x/web-interface/search/type?page_size=10&keyword={kw}&search_type=bili_user` → `data.result[]`（`mid/uname/fans`）
- `GET https://app.bilibili.com/x/v2/space/garb/list?pn=1&ps=100&vmid={uid}` → `data.list[]`（`garb_title/fans_number/images[]/title_bg_image`）

**B. 第三方 VTB 接口（个人站点，多已挂/需 CF 校验）**：
- `danmakus.com/api/search/user/detail`（弹幕明细）、`danmakus.com/api/search/user/channel`（观看）、`danmakus.com/api/info/channel`（直播信息）、`danmakus.com/api/info/live`（单场收益）
- `api.vtbs.moe/v1/guard/{uid}`、`api.vtbs.moe/v1/detail/{uid}`
- `www.vtbs.fun:8050/rank/income`、`www.vtbs.fun:8050/rank/incfans`（dateRange 需 URL-encode 日/周/月榜）
- `ddstats-api.ericlamm.xyz/stats?top={n}`
- `laplace.live/api/user-medals/{uid}`、`edge-fetcher.xn--7dvy22i.com/api/bilibili/upower/{uid}`（充电榜）
- `api.zeroroku.com/bilibili/author/famous-fans?mid={uid}`
- `eihei.gendaimahou.net/listen/livepic.php?uid={uid}`（直播图片流，关 SSL）

**C. Playwright 截图页**：`vtbs.moe/*`、`danmakus.com/*`、`biligank.com/live/*`、`matsuri.icu/channel/*`、`laplace.live/*`、`zeroroku.com/*`、`stats.nailv.live/compare/arena`（斗虫）等，注入 JS 展开折叠/删除导航后整页截图。

### 凭据
仅 `buvid3`（非必填），env `searchBiliInfo_cookie="buvid3=...; "`。无 SESSDATA/bili_jct/wbi。

### 亮点算法
- `data_preprocess()`（`__init__.py:2291-2342`）**uid→本地别名表→官方搜索** 三级解析，可直接复用为"用户定位"。
- 本地数据 `data.py`（`{mid,uname,roomid}`，源自 `api.vtbs.moe/v1/short`）+ `data_medal.py`（牌子名→用户）。
- 数据清洗：`timestamp_to_date()` 毫秒→日期；直播时长=(stop-start)/3600 小时；收入/粉丝"万/亿"自适应；`filter_markdown()` 去特殊字符防表格超长；`collections.Counter` 统计观看；`md_to_pic` 渲染图片并设行数上限。

### 可用性：部分能用（大量失效）
作者自述"部分功能已失效，多是第三方接口挂了"。官方 5 个接口仍可用；danmakus/vtbs.fun/ddstats/laplace/zeroroku/eihei 等第三方已挂或需 CF 校验；Playwright 截图依赖第三方在线 + Chromium，流量大。

### 整合建议（低~中）
`/查`、`/查昵称`、`/查装扮` 与现有「空间解析」重叠；`/查直播` 与「直播解析」部分重叠。**增量借鉴**：① 5 个官方稳定接口并入空间/用户解析作字段增强；② `data_preprocess` 三级解析；③ 收益/营收的数据清洗工具。**不建议**移植 Playwright 截图 VTB 看板与已失效第三方接口。

---

## 4. krimeshu/nonebot-plugin-bili-helper（B站助手）

**仓库**：`nonebot-plugin-bili-helper-master`，License **MIT**。

### 功能与命令
解析 B站分享卡片（含微信小程序/图文卡片）、评论截图、视频信息。命令：发卡片/链接自动解析；`设置B站Cookie X`（superuser 私聊）写入本地 `cookie_store.json`。仅 OneBot v11，不提供下载。

### 依赖
`aiohttp`、`nonebot2`、`nonebot-adapter-onebot`、`nonebot-plugin-htmlrender`、`nonebot-plugin-localstore`。

### API/endpoint（仅 3 个 B站端点）
- **GET** `https://api.bilibili.com/x/web-interface/view`（params `aid`/`bvid`）→ 视频信息
- **GET** `https://api.bilibili.com/x/v2/reply/wbi/main`（params `oid`/`type`/`mode=3`/`pagination_str`/`plat`/`seek_rpid`/`web_location`，**需 wbi 签名**）→ 评论
- **GET** `https://api.bilibili.com/x/web-interface/nav` → 取 wbi 的 `wbi_img.img_url/sub_url`（mixin key 来源）
- 短链 `b23.tv` 用 HEAD 重定向解析。

请求头统一 UA / `Referer: https://www.bilibili.com/` / 整串 Cookie。

### 凭据
整串 Cookie（含 SESSDATA/bili_jct/buvid3/DedeUserID 等），经 superuser 私聊命令写入 `cookie_store.json`，**无 .env cookie 变量、不拆字段、未实现 buvid 生成/b_nut/b_lsid/risky 风控**（风控仅 WBI 一处）。

### 亮点算法（本插件最有借鉴价值）
- **WBI 签名**（`modules/bilibili_encoder.py`）：盐表 `mixin_key_enc_tab` 取 `img_key+sub_key` 重排取前 32 位 → 参数加 `wts`（时间戳）→ 按 key 排序 → 过滤字符 `!'()*` → urlencode → `md5(query + mixin_key)` 得 `w_rid`。
- **BV↔AV 转换**（`modules/bv2av.py`）纯函数：`XOR_CODE/MASK_CODE` + `BASE=58` 字符码表；av→bv 时交换下标 `[3]↔[9]`、`[4]↔[7]`。
- **小程序/图文卡片解析**：`com.tencent.miniapp` → `meta.detail_*.qqdocurl`；`com.tencent.tuwen` → `meta.news.jumpUrl`。
- 评论 HTML→截图：htmlrender/playwright 渲染 `bilibili/comment.html` 后截图 JPEG。

### 可用性：部分能用
`video_info` + BV/AV 稳定；评论依赖登录 cookie 且受风控影响；小程序解析仅 OneBot v11；截图依赖 playwright 环境。

### 整合建议（高）
- **高优先级**：抽出 `bv2av.py`（纯函数，零依赖）+ `WbiEncoder`（直接补我们 `platforms_bilibili.py` 缺失的 wbi 签名能力）。
- **中优先级**：补分享卡片（小程序/图文 JSON）的短链解析入口；评论 `wbi/main` 参数。
- **低优先级/避免**：HTML 截图渲染、明文 `cookie_store.json` 存凭据（我们已有更安全的 `credentials.py` 掩码存储）。

---

## 5. Akiyy-dev/nonebot-plugin-bililive（B站直播/动态订阅推送）

**仓库**：`nonebot-plugin-bililive-master`，License **AGPL-3.0**（⚠️ 传染性强，复用需开源）。

### 功能与命令
UP 主开播/下播/新动态推送到 QQ。命令：`帮助`、`关注 UID`（别名`添加主播`）、`取关 UID`、`关注列表`、`开启直播 UID`/`关闭直播 UID`、`开启动态 UID`/`关闭动态 UID`、`开启全体 UID`/`关闭全体 UID`（@全体）、`开启权限`/`关闭权限`、`已开播`。UID 接受纯数字/链接/UP 名/短链。仅 OneBot V11。

### 依赖
`httpx`、`nonebot-adapter-onebot`、`apscheduler`、`localstore`、`playwright>=1.58`、`tortoise-orm[asyncpg]`、`click`；Python ≥3.10。首次自动装 Chromium。

### API/endpoint
- **POST** `https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids`（`bilibili_api.py:51`），headers UA+`Referer: https://www.bilibili.com/`，body `{"uids":[...]}`，返回 `data` 为 `{uid: {live_status(2=直播中), uname, live_time, short_id, room_id, title, cover_from_user, keyframe, area_v2_name, area_v2_parent_name}}` —— **批量直播状态查询，未登录即可用，是本插件最有价值端点**。
- **GET** `https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}`（`libs/dynamic/web.py:5`），headers 桌面 Chrome/122 + `Referer: https://space.bilibili.com/{uid}/dynamic`，cookies 传入 → `data.items[]`（当前仅解析 `id_str`/`type`/`modules.module_author.name`）。
- 辅助：`GET https://api.bilibili.com/x/web-interface/search/type?keyword={kw}&search_type=bili_user`；`GET https://api.bilibili.com/x/web-interface/card?mid={uid}` → `data.card.name`；`b23.tv` 短链还原。

### 凭据
无 SESSDATA env。cookie 来自内置 Playwright 持久化上下文（数据目录 `browser/`）或外部 Chromium CDP，`get_bilibili_cookies()` 读 `www.bilibili.com`/`api.bilibili.com` cookie。README 建议在浏览器里登录常用 B站账号以降低风控。验证码服务 token `BILILIVE_CAPTCHA_TOKEN`。

### 亮点算法
- **直播轮询状态机**（`live_pusher.py`）：APScheduler 定时（默认 10s，`coalesce=True`），一次 POST 批量查全部 UID；内存 `status` dict 差分（`live_status` 归一化 2→0，变化才推）；`live_time` dict 记开播时间算下播时长。
- **动态增量 + 风控冷却**（`dynamic_pusher.py`）：按 uid 持久化 `dynamic_offset`（最新动态 id）只推新增；`WEB_SKIP_DYNAMIC_TYPES` 过滤直播推荐/广告；`-412`（被 ban）冷却 300s、其他错误 600s；并发 `Semaphore(4)` + 1s 节流。
- 动态 card JSON（`item/desc/display`）Pydantic 建模**已被注释停用**（现役只走 polymer 3 字段 + 截图），可作旧结构参考。
- Playwright 截图 + 极验验证码（`captcha_solver.py` 调 `https://captcha-cd.ngworks.cn` 识别点击坐标）——重且脆。

### 可用性：部分能用
直播批量查询可用；polymer `feed/space` 依赖登录 cookie 且高频抓取触发 `-412`（插件已内置冷却）；截图/验证码方案重、维护脆。

### 整合建议（中）
- **中优先级**：① `get_status_info_by_uids` 批量直播状态查询（比逐房间轮询省请求，做订阅 UP 集合统一探测）；② 动态增量 offset + `-412`/600s 退避状态机（复刻到现有动态抓取防重复推+防风控）。
- **低/避免**：Playwright 截图、极验验证码、Chromium 自动装、Tortoise ORM 订阅存储。AGPLv3 注意开源义务。

---

## 6. fllesser/nonebot-plugin-parser（多平台链接解析）

**仓库**：`nonebot-plugin-parser-master`（v2.6.7），License **MIT**。⭐ 与我们流水线**最相关**的插件。

### 功能与命令
链接分享自动解析：B站（视频/直播/动态/图文 opus/专栏/收藏夹）+ 抖音/微博/小红书/快手/AcFun/YouTube/TikTok/Twitter/NGA。发链接/BV/av/卡片/小程序自动解析。命令：
- `bm BV号 [分集]`（下载 B站音频）、`ym 链接`（YouTube 音频）、`blogin`（superuser 私聊扫码获取 B站凭证）、`开启解析`/`关闭解析`（群级开关）。

### 依赖
`httpx`、`curl_cffi`（模拟浏览器）、`msgspec`、`pillow`、`aiofiles`、`rich`、`beautifulsoup4`、**`bilibili-api-python>=17.4.2,<18.0.0`**、`nonebot2`、`alconna`、`uninfo`、`localstore`、`apscheduler`、`apilmoji`。可选 `yt-dlp`/`htmlrender`/`emosvg`。外部组件 ffmpeg + Deno（yt-dlp ≥2025.11.12 要求）。

### 核心架构（关键借鉴点）
**插件自身几乎不写 B站 HTTP 请求**，全部委托 `bilibili-api-python` SDK：
```python
from bilibili_api import HEADERS, Credential, select_client, request_settings
select_client("curl_cffi")                 # 用 curl_cffi 而非 httpx
request_settings.set("impersonate", "chrome131")  # 浏览器指纹伪装
```
即 **wbi 签名、cookie 刷新、浏览器指纹伪装（curl_cffi chrome131）全部由 SDK 内置完成**。

### API/endpoint（从依赖库 `bilibili-api-python 17.4.2` 源码直抄）
| 解析器 | SDK 调用 | 端点（方法/URL/参数） |
|---|---|---|
| 视频信息 | `Video.get_info()` | `GET https://api.bilibili.com/x/web-interface/view`（`bvid`/`aid`，无需登录）|
| 视频下载流 | `video.get_download_url(page_index)` | `GET https://api.bilibili.com/x/player/wbi/playurl`（**wbi 签名**；`qn=127`、`fnval=4048`、`fnver=0`、`fourk=1`、`gaia_source=pre-load`、`isGaiaAvoided=true`、`avid`/`bvid`/`cid`、`from_client=BROWSER`、`web_location=1315873`）→ `data.dash.video[]`/`audio[]`（`baseUrl`/`bandwidth`/`codecid`/`codecs`）|
| AI 总结 | `video.get_ai_conclusion(cid)` | `GET https://api.bilibili.com/x/web-interface/view/conclusion/get`（**wbi**；`aid`/`bvid`/`cid`/`up_mid`/`web_location=333.788`，需登录 cookie）→ `data.model_result.summary` |
| 直播 | `LiveRoom.get_room_info()` | `GET https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom`（`room_id`，内部先短 ID→真实 room_id）→ `room_info{title,cover,keyframe,tags,area_name,parent_area_name}`、`anchor_info.base_info{uname,face}` |
| 动态 | `Dynamic.get_info()` | `GET https://api.bilibili.com/x/polymer/web-dynamic/v1/detail`（**wbi**；`id`、`timezone_offset=-480`、`platform=web`、`gaia_source=main_web`、`features=itemOpusStyle,opusBigCover,...`、`web_location=333.1368`、`x-bili-device-req-json`、`x-bili-web-req-json`）→ `item.modules.module_author/module_dynamic{major,desc}` |
| 图文 opus | `Opus.get_info()` | `GET https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail`（`id`、`timezone_offset=-480`、`features=...`）→ `item.basic.title`、`item.modules[]` 段落 `paragraphs[]{para_type,text.nodes[],pic.pics[]}` |
| 专栏 | `Article.turn_to_opus()` | `GET https://api.bilibili.com/x/article/view` → 转 opus 再走 opus detail |
| 收藏夹 | `get_video_favorite_list_content(fid)` | `GET https://api.bilibili.com/x/v3/fav/resource/list`（`media_id`、`pn=1`、`ps=20`、`order=mtime`、`tid=0`、`type=0`、`platform=web`、`web_location=333.1387`）→ `info{title,cover,upper}`、`medias[]{title,cover,intro,link}`（link 为 `bilibili://video/<avid>`）|
| 登录校验/wbi key | `Credential.check_valid()` | `GET https://api.bilibili.com/x/web-interface/nav`（`data.isLogin`；也是 wbi mixin_key 来源）|

**下载 CDN 必须带 `Referer: https://www.bilibili.com` + `User-Agent`**（SDK 注释明确）。

### 凭据
- 配置 `parser_bili_ck="SESSDATA=...;ac_time_value=..."`（必须含 SESSDATA，附加 AI 总结；`ac_time_value` 仅用于刷新 cookie，取 `window.localStorage.ac_time_value`）。
- `blogin` 命令走 `QrCodeLogin` 扫码获取；`Credential` 内置 `check_valid()/check_refresh()/refresh()` 自动续期（刷新需 SESSDATA+ac_time_value+bili_jct）。
- 其它：`parser_bili_video_codes=["avc","av01","hev"]`、`parser_bili_video_quality=80`（1080p）、`parser_duration_maximum=480`、`parser_max_size=90`（MB）、`parser_disabled_platforms`、`parser_render_type`（default/common/htmlrender）。

### 亮点算法
- **URL 匹配规则（`handle` 装饰器链）**：`@handle("b23.tv", r"b23\.tv/...")`、`@handle("BV", r"^(?P<bvid>BV[0-9a-zA-Z]{10})(?:\s)?(?P<page_num>\d{1,3})?$")`、`@handle("/av", ...)`、`@handle("/dynamic/", ...)`、`@handle("/opus/", ...)`、`@handle("t.bili", ...)`、`@handle("live.bili", ...)`、`@handle("/favlist", ...)`、`@handle("/read/", ...)` —— 正则按平台/形态分发到对应 parser，可复用到我们 `sources/parsers/__init__.py` 的分发层。
- **下载流选择**：`VideoDownloadURLDataDetecter.detect_best_streams(video_max_quality, codecs, no_dolby_video=True, no_hdr=True)` 挑最优音/视频流；`downloader.download_av_and_merge(v_url, a_url)`（ffmpeg 合并音视频）→ mp4。
- **分 P 处理**：`extract_info_with_page(page_num)` 多 P 时取对应页 title/duration/cover（`pages[].first_frame`）。
- **AI 总结**：登录态下 `get_ai_conclusion(cid)` 取 `model_result.summary`。

### 可用性：能用
最新维护（v2.6.7），SDK 自动处理 wbi/风控 + curl_cffi chrome131 指纹，是最"抗风控"的实现。注意依赖 `bilibili-api-python` 版本需跟进。

### 整合建议（高）—— 与现有实现详细对照
- **重叠**：视频/直播/动态/收藏夹解析与 `platforms_bilibili.py` 完全重叠（且现有还用 `relation/stat`、`space/navnum` 做作者增强，parser 反而没有作者粉丝数）。
- **增量（高价值）**：
  1. **改用 `bilibili-api-python`（或至少补 wbi 签名）** —— 我们现有裸 API 无 wbi，动态/opus 接口会被 `-352` 风控；这是最应借鉴的一处。可选方案：直接依赖 SDK 的 `Credential + Video/LiveRoom/Dynamic/Opus/favorite_list`（如 bili-query 那样），或把 bili-helper 的 `WbiEncoder` 移植进 `http_util`。
  2. **下载走 `x/player/wbi/playurl`（fnval=4048 DASH）** —— 比 yt-dlp 更可控（清晰度/编码/无 Dolby/无 HDR），可与我们现有 yt-dlp 下载并存作为 B站专用快速通道；借鉴 `download_av_and_merge` + `Referer/UA` 头。
  3. **opus 图文用独立端点 `x/polymer/web-dynamic/v1/opus/detail`** —— 我们现有 `_parse_opus` 用 `polymer/detail`，对纯图文 opus 可能字段不全，建议补 opus 专端点。
  4. **curl_cffi + impersonate chrome131** —— 反风控利器，可替换我们解析层的 httpx。
  5. **Credential 扫码登录 + 自动刷新**（`blogin`/`QrCodeLogin`/`check_refresh`）—— 可对接我们 `credentials.py` 的凭据生命周期。
  6. **AI 总结、专栏、多平台** —— 若需扩展能力面可整取，但优先级低于 1/2/3。
- **避免重复**：渲染（PIL/htmlrender 卡片）与我们的统一渲染/发送审计重复，不需要引入。

---

## 7. Wojusensei/nonebot-plugin-bilidownloader-woju（B站下载）

**仓库**：`nonebot-plugin-bilidownloader-woju-main`，License **MIT**。

### 功能与命令
下载音频/视频/封面。命令：`/mp3 链接/BV号`（发 M4A 音频，自动最高音质）、`/mp4 链接/BV号`（发 MP4）、`/封面图 链接/BV号`。经 `upload_group_file/upload_private_file` 上传（需 Lagrange/NapCat 支持）。

### 依赖
`httpx`、**`bilibili-api-python`**、`nonebot2`、`nonebot-adapter-onebot`、`nonebot-plugin-localstore`；Python ≥3.10。

### API/endpoint（经 `bilibili-api-python`，自身不写裸 URL）
- `video.Video(bvid).get_info()` → `x/web-interface/view`
- `video.get_download_url(page_index=0)` → `x/player/wbi/playurl`（**wbi 签名**，DASH）→ `d["dash"]["audio"]`/`["video"]`，`best()` 取 `max(bandwidth)["baseUrl"]`
- `video.get_download_url(page_index=0, html5=True)` → `d["durl"][0]["url"]`（单文件 MP4，自带音轨，低清，无 ffmpeg 时回退）

### 凭据
无（匿名；SDK 匿名 wbi）。配置：`bilibili_downloader_max_file_mb=500`、`bilibili_downloader_ffmpeg_path=`。

### 亮点算法
- **DASH 音视频分离**：`/mp4` 分别下载 `dash.video` + `dash.audio`（各取 bandwidth 最高），再用 `ffmpeg -y -i video -i audio -c copy out.mp4` **无损合并**（`mux_av`，`__init__.py:151-168`）。
- **无 ffmpeg 回退**：`html5=True` 走 `durl` 单文件 MP4（流畅画质）。
- **流式下载**：`httpx.stream` 逐块写盘（256KB），按 `content-length` + 累计字节双重限流；随机文件名防并发。
- **CDN 403 修复**：下载头强制 `Referer: https://www.bilibili.com/` + Chrome/124 UA（`DOWNLOAD_HEADERS`）。

### 可用性：能用
依赖 `bilibili-api-python` 自动 wbi，匿名可下 DASH（高清晰度/大会员档可能受限）。

### 整合建议（中）
- **重叠**：我们已有 `download.py`（yt-dlp）。本插件证明"SDK 直下 DASH"是可用的**B站专用轻量替代**。
- **增量借鉴**：① `ffmpeg -c copy` 无损合并音视频 + `html5` 回退；② 流式下载 + `Referer/UA` 头（CDN 403 修复）；③ 按 `bandwidth` 选流、`/mp3` 单独音频、`/封面图` 命令（可并入我们的下载能力做细分命令）。

---

## 8. Wojusensei/nonebot-plugin-bili-query（B站查询/订阅）

**仓库**：`nonebot-plugin-bili-query-main`（v0.2.0），License **MIT**。

### 功能与命令
用户/视频查询 + UP 新视频订阅推送。命令：`/help`、`/用户查询 <uid|空间链接>`、`/视频查询 <BV|链接|短链>`、`/订阅 <uid|空间链接>`（仅群聊）、`/取消订阅 <uid>`。

### 依赖
`nonebot2>=2.3`、`onebot`、`localstore`、`apscheduler`、**`bilibili-api-python>=17`**、`httpx`；Python ≥3.10。

### API/endpoint（经 `bilibili-api-python`，匿名 wbi）
- `user.User(int(uid)).get_user_info()` → `x/space/wbi/acc/info?mid={uid}`（**wbi**）→ `name/face/stat{follower,following,video,likes,article,dynamic}`
- `u.get_videos(ps=N)` → `x/space/wbi/arc/search?mid={uid}&ps={N}`（**wbi**）→ `list.vlist[]{title,bvid,aid,created,play,length}`
- `video.Video(bvid=bv).get_info()` → `x/web-interface/view?bvid=` → `title/stat{view,like,coin,share,favorite}/owner/desc/duration`
- `b23.tv` 短链：`httpx.AsyncClient(follow_redirects=True)` 取重定向后 `resp.url` 提 BV。

### 凭据
无（匿名 wbi）。仅配置 `bili_query_check_interval_minutes=5`。

### 亮点算法
- **正则解析器**（`parser.py`）：`parse_uid`（space 链接/`uid:` 前缀/裸数字）、`parse_bv`（`BV[0-9A-Za-z]{10}`）、`parse_b23_url`、`parse_video_url`——轻量无依赖。
- **订阅基线机制**：订阅时记最新视频 bvid+created 为基线；定时任务首次只建基线不播报；之后 `bvid != last_bvid and timestamp > last_time` 才通知（防旧视频误报）。
- **sqlite 订阅表**（`subscriptions(group_id,uid,last_video_bvid,last_video_time)`，`UNIQUE(group_id,uid)`），同步操作经 `asyncio.to_thread` 包装；多群同订按 UID 分组去重、一次查询向所有订阅群广播。

### 可用性：能用
v0.2.0（2026）修复 NoneBot2 2.4+/pydantic v2 适配，带测试套件。核心走 wbi 接口，风险是匿名 wbi 可能被限流/字段不全。

### 整合建议（中 + 低）
- **重叠**：`/用户查询`、`/视频查询` 与现有空间/视频解析重叠（现有还带作者粉丝增强）。
- **增量借鉴（中）**：① **订阅推送设计**（基线 + last_bvid/last_time 增量判定 + 按 UID 去重 + sqlite）——现有流水线未见订阅能力，值得借鉴；② `parse_uid/parse_bv/parse_b23_url` 正则前置层；③ `b23.tv` 重定向。
- **低**：用户/视频查询字段能力已覆盖，无需新增命令面。

---

## 9. j1udu/nonebot-plugin-bili2mp4（B站链接转 mp4）

**仓库**：`nonebot-plugin-bili2mp4-master`，License **MIT**。

### 功能与命令
群内自动检测 B站链接并转 mp4 发送。管理员私聊（superuser）：`fhelp`、`转换 <群号>`、`停止转换 <群号>`、`设置B站COOKIE <cookie>`、`清除B站COOKIE`、`设置清晰度 <数字>`（0=不限）、`设置最大大小 <数字>MB`、`查看参数`、`查看转换列表`。

### 依赖
**`yt-dlp`**、`nonebot2`、`onebot`、`nonebot-plugin-localstore`（+ 外部 ffmpeg/ffprobe）。

### API/endpoint
**无直接 B站 API**，全委托 yt-dlp，关键参数：
- `extractor_args={"bili": {"player_client": ["android","web"], "lang": ["zh-CN"]}}`
- `format` 用自定义 `format_selector`（选 avc/hvc 视频轨 + m4a/webm 音频轨合并）、`merge_output_format="mp4"`、`noplaylist=True`、`max_filesize`。

### 凭据
整串 Cookie（至少 `SESSDATA/bili_jct/DedeUserID/buvid3`），`设置B站COOKIE` 后由 `_ensure_cookiefile()` **转成 Netscape 格式**（`.bilibili.com TRUE / FALSE <expiry> <name> <value>`）传给 yt-dlp `cookiefile`。

### 亮点算法
- **链接提取**：从消息段 `text`/`json`/`xml`/`share` 卡片递归 `_walk_strings` + `_find_urls_in_text`（还解析 `url`/`qqdocurl`/`jumpUrl`/`webpageUrl` query 参数）；`b23.tv` 短链 HEAD→GET 重定向。
- **清晰度分级候选**：`format_map`（1080→[≥1080,≥720,best]、720、480）逐级回退。
- **ffprobe 校验**：下载后 `ffprobe -select_streams v:0 -show_entries stream=width,height` 检查分辨率、按 max_filesize 删超限文件。
- **yt-dlp 格式选择**：`format_selector` 选 avc/hvc 视频 + 匹配容器音频合并 mp4（避免 mkv）。

### 可用性：能用
yt-dlp 对 B站 持续适配；`player_client=["android","web"]` 是当前较稳的取流策略。风险是 yt-dlp 更新需同步。

### 整合建议（中~低）
- **重叠**：我们已有 yt-dlp `MediaDownloader`。**增量借鉴**：① `extractor_args bili player_client=["android","web"]` + `lang=zh-CN` 提升 B站取流成功率；② Cookie 字符串→Netscape 转换（可接入我们 `credentials.py` 的 cookie 文件生成）；③ 消息段 json/xml/share 卡片链接提取 + 清晰度/大小分级 + ffprobe 校验（我们 `download.py` 已有 `max_height/max_bytes`，可补 ffprobe 校验与卡片链接提取）。

---

## 10. STESmly/nonebot_plugin_bililivedm（B站直播弹幕）

**仓库**：`nonebot_plugin_bililivedm-main`，**无 LICENSE 文件**（⚠️ 默认保留权利，直接复用有合规风险；底层 `blivedm/` 是 xfgryujk/blivedm 的改写，协议可参考其 MIT 上游）。

### 功能与命令
WebSocket 监听直播间弹幕/礼物/上舰/SC，转发到自建 WS 端点。无 QQ 命令，纯事件驱动。配置：`bililiveid`（房间号）、`bilitoken`（SESSDATA，可选）、`bililivedown=on`、`loadws=ws://127.0.0.1:8000/bilidm`（事件转发地址）。转发 JSON：`{user_id,nickname,message,room_id,type(message|super_chat),price}`。

### 依赖
`nonebot2>=2.2.1`、`aiohttp`、**`Brotli>=1.1.0`**（弹幕 brotli 解压）、`yarl`；Python ≥3.8。

### API/endpoint（弹幕协议栈，最有价值）
- `GET https://api.bilibili.com/x/web-interface/nav` → `data.isLogin/mid`
- `GET https://www.bilibili.com/` → 让服务端种 `buvid3`
- `GET https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom`（`room_id`）→ `data.room_info.room_id`（真实房间号）/`data.room_info.uid`（短 ID→真实 ID 转换）
- `GET https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo`（`id=room_id&type=0`）→ `data.host_list[]{host,port,wss_port,ws_port}` + `data.token`（认证 key）
- **弹幕 WS**：`wss://{host_list[i].host}:{host_list[i].wss_port}/sub`（多 host 按 `retry_count % len` 轮换）
- **认证包**：`Operation.AUTH(7)`，body `{"uid": 0或mid, "roomid": 真实房间号, "protover": 3, "platform": "web", "type": 2, "buvid": buvid3, "key": token}`；包头 `struct '>I2H2I' = (pack_len, 16, 1, operation, seq_id=1)`
- **心跳**：`Operation.HEARTBEAT(2)` body `{}`，30s；`AUTH_REPLY(8)` 后立即补一次心跳；`HEARTBEAT_REPLY(3)` 前 4 字节大端 = 人气值（官方已废弃）
- 开放平台：`POST https://live-open.biliapi.com/v2/app/start|heartbeat|end`（HMAC-SHA256 签名头 `x-bili-accesskeyid/x-bili-content-md5/x-bili-signature-method/x-bili-signature-nonce/x-bili-signature-version/x-bili-timestamp`；start body `{code,app_id}`）

### 凭据
`bilitoken`（SESSDATA）注入 aiohttp `cookie_jar`；`buvid3` 自动种；无 bili_jct（只读无写）。开放平台需 `access_key_id/secret/app_id/身份码`（插件未接线）。

### 亮点算法
- **完整弹幕协议栈**（`ws_base.py`）：`HEADER_STRUCT '>I2H2I'` 头 + `ver/operation/seq_id` + 一个 WS 帧内多包分包循环 + `protover 0/1/2(zlib)/3(brotli)` 双解压（brotli 为当前 web 标准）；`DANMU_MSG` 的 `info[]` 逐下标解析（`info[0]` 元信息/`info[1]` 内容/`info[2]` 用户/`info[3]` 勋章/`info[4]` 等级/`info[5]` 头衔/`info[7]` 舰队）。
- **认证+心跳闭环**：getDanmuInfo 取 token → AUTH → AUTH_REPLY 校验 → 30s 心跳保活。
- **开放平台 HMAC-SHA256 签名** + 场次（game）心跳 20s —— 规避 cookie 风控的官方通道。

### 可用性：部分能用（且插件外壳质量差）
- `blivedm` 协议库本体基本可用（protover3/brotli/token 是现行 web 协议）。
- **插件外壳有缺陷**：`room_id = random.choice(TEST_ROOM_IDS)` 在 `TEST_ROOM_IDS` 赋值前可能执行（竞态/NameError）；只监听 5s 就 stop；`send_data` 每事件新开 ClientSession+重连。应视为"blivedm 协议库搬运容器"，不可直接上线。
- 开放平台可用但需申请，插件未接线。

### 整合建议（高，仅协议栈）
- **高优先级**：借鉴 `blivedm/clients/web.py + ws_base.py` 的弹幕协议实现（protover3/brotli、auth 包、心跳、短 ID→房间号、`DANMU_MSG` 解析），做成统一流水线的「直播弹幕实时输入源」——这是我们现有"直播解析"缺失的实时能力。**建议以 xfgryujk/blivedm（MIT）上游为参考**，而非本无 LICENSE 仓库。
- **中优先级**：开放平台 `open_live.py` 的 HMAC 签名 + start/heartbeat/end（若想规避 cookie 风控、稳定监听）。
- **低/避免**：`loadws` 转发外壳、每事件重连、线程启动逻辑——应由统一发送审计管线取代。

---

## 汇总：整合优先级与重叠表

| 优先级 | 借鉴项 | 来源插件 | 落点建议 |
|---|---|---|---|
| **高** | WBI 签名 `WbiEncoder` + BV↔AV `bv2av`（纯函数） | bili-helper(#4) | 补进 `sources/parsers/http_util.py`，解决现有动态/opus 无 wbi 被风控 |
| **高** | 改用/引入 `bilibili-api-python` SDK（wbi+curl_cffi chrome131+cookie 刷新） | parser(#6) | 替换/增强 `platforms_bilibili.py` 裸 API |
| **高** | 直播弹幕协议栈（protover3/brotli/auth/心跳/DANMU_MSG） | bililivedm(#10) | 新增实时弹幕输入源（参考 MIT 上游 blivedm） |
| **高** | `x/player/wbi/playurl` DASH 下载（fnval=4048）+ `ffmpeg -c copy` 合并 + Referer/UA | parser(#6)+bilidownloader(#7) | B站专用下载通道，与 yt-dlp 并存 |
| **高** | opus 图文独立端点 `x/polymer/web-dynamic/v1/opus/detail` | parser(#6) | 补现有 `_parse_opus`（现用 polymer/detail） |
| 中 | 批量直播状态 `POST /room/v1/Room/get_status_info_by_uids` | bililive(#5) | 订阅 UP 集合统一探测 |
| 中 | 动态增量 offset + `-412`/600s 风控退避状态机 | bililive(#5) | 现有动态抓取防重复/防风控 |
| 中 | 订阅推送（基线 + last_bvid/last_time 增量 + sqlite + 多群去重） | bili-query(#8) | 新增 UP 订阅推送能力 |
| 中 | `parse_uid/parse_bv/parse_b23_url` 正则前置 + b23.tv 重定向 | bili-query(#8)/parser(#6) | 并入 `sources/parsers` 分发层 |
| 中 | yt-dlp `extractor_args bili player_client=["android","web"]` + Cookie→Netscape | bili2mp4(#9) | 增强现有 `MediaDownloader` |
| 中 | 官方稳定接口 `getCardByMid`/`room_id_by_uid`/`guardTab/topList`/`search/type`/`garb list` + `data_preprocess` 三级解析 | searchBiliInfo(#3) | 空间/用户解析字段增强 |
| 低 | 封面提取（`data.pic`）、动态/专栏图片抓取 | bilicover(#1)/bilibili-image(#2) | 与现有重叠，仅专栏图片为增量（需补 wbi+cookie） |
| 低/避免 | Playwright 截图、极验验证码、HTML 截图渲染、go-cqhttp 专属 API、明文 cookie 存储、Tortoise ORM、loadws 转发 | #2/#3/#4/#5/#10 | 不与统一流水线耦合 |

**许可证红线**：bilibili-image(#2) 与 bililive(#5) 为 **AGPL-3.0**，直接复用代码需评估开源义务；bililivedm(#10) **无 LICENSE**，仅可参考其 MIT 上游 blivedm。

**最核心的一条建议**：现有 `platforms_bilibili.py` 是"裸 API + cookie"一代实现，没有 wbi 签名、没有浏览器指纹伪装，动态/opus 接口在高风控下会被 `-352` 拦截。最省力的升级路径是**引入 `bilibili-api-python`（parser/bilidownloader/bili-query 三插件已验证）**，用它替换自写裸请求，即可一次性获得 wbi 签名 + curl_cffi 指纹 + Credential 扫码/刷新 + DASH 下载流；再按需补上弹幕协议栈与订阅推送即可覆盖其余增量。
