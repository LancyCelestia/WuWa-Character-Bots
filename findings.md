# 研究发现

## 工作区基线

- 项目根目录：`C:\Users\LancyCelestia\WuWa-Character-Bots`。
- 当前是一个新的 NoneBot 项目，`plugins/` 下还没有本地运行时插件。
- 已有依赖：NoneBot2、OneBot、APScheduler、localstore、Alconna、filehost、ORM、htmlkit。
- AstrBot 参考插件位于 `C:\Users\LancyCelestia\.astrbot`。

## 初始需求

- 先下载和分析合适插件，再写自定义代码。
- 对比 NoneBot 插件与现有 AstrBot 插件。
- 明确正确的组织结构、算法、解析/输入/输出流、反馈和发送方式。
- 设计实用能力：网页编码辅助、ACG 推荐、群总结、同人推荐、游戏查询、媒体解析、自动发送等。

## 下载和覆盖情况

- 已验证 70 个 NoneBot wheel、70 个解压源码目录，以及 12 个 GsCore/GScore git 仓库。
- 具体路径记录在 `research/downloaded_sources.md`。
- 结构索引记录在 `research/nonebot_plugin_sources/structure_index.json`、`second_batch_structure_index.json` 和 `research/gscore_sources/structure_index.json`。

## 高置信架构方向

统一运行时比“很多插件各自抢着回复”更稳：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

核心规则：

- 能力插件返回结构化结果，不直接发送。
- 群聊保守且 opt-in；私聊可以更温暖，但必须尊重同意和隐私。
- 聊天记录、记忆、搜索结果、抓取内容、桥接输出都是不可信事实。
- 所有输出都经过人格、隐私、安全、防刷屏、渲染和发送检查。
- 情绪、记忆、人设、知识库是上下文服务，不是发送器。
- 媒体 parser 和订阅先归一化来源数据，再渲染，再通过统一 sender 发送。

## NoneBot / AstrBot 插件结论

- `nonebot_plugin_parser` 和用户本地 `astrbot_plugin_parser` 提供了最强 parser 模式：`BaseParser` 自动注册、`@handle()` keyword/regex、`ParseResult`、媒体模型、渲染、缓存和 fallback。
- 本项目应保留 parser/renderer/sender 分层，但把 sender 直发升级为 `RenderedOutput -> SendRequest -> DeliveryReceipt`。
- `nonebot_bison` 的平台抽象、加权调度、批量抓取、队列发送、重试和间隔控制适合订阅系统。
- `nonebot_plugin_bilichat`、`analysis_bilibili`、`bili_helper`、`bili_fav_watcher` 是 Bilibili 解析和订阅参考。
- `nonebot_plugin_chatrecorder` 适合作为原始消息归档层。
- `nonebot_plugin_word_censor` 和 AstrBot `outputpro` 说明最终输出守卫必须存在，且非 LLM 输出也要能被拦截。
- `summary_group` 的显式命令、消息数量限制、冷却和管理员定时总结适合防刷屏。
- `WWwiki`、`XutheringWavesUID` 适合作为公共鸣潮知识/卡片参考。
- `gspanel`、`zzzpanel`、`gachalogs` 等账号能力是后续高风险阶段。

## 用户本地 parser 插件补充发现

参考路径：

```text
C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser
```

关键发现：

- `main.py` 是三合一入口：链接解析、订阅、点歌。
- `core/parsers/base.py` 用 `BaseParser.__init_subclass__` 自动注册 parser，用 `@handle(keyword, pattern)` 声明匹配规则。
- `core/data.py` 的 `ParseResult` 携带平台、作者、标题、正文、来源 URL、媒体、评论、转发、音乐信息、统计和稳定资源指纹。
- `core/subscriber/*` 提供多平台订阅、cursor、recent ids、push mode、图片限制、jitter、task gap、跨平台 hash 去重。
- `core/render.py` 和 `core/render_html/*` 有 HTML/Playwright、PIL、文本 fallback 的渲染回退。
- `core/sender.py` 会构建发送计划、合并转发和 fallback，但在新项目中应变成 transport adapter，而不是 capability 可直接调用的发送器。

已写入 `docs/specs/media-source-pipeline.md` 的迁移点：

- `ParserRegistry.keyword_patterns`、最长 keyword 优先、通用 URL fallback。
- OneBot/NapCat 富卡字段：`qqdocurl`、`jumpUrl`、`musicUrl`、`playUrl`、`videoUrl`。
- `ParseResult` 字段到 `ParsedMediaItem` / `NormalizedMediaItem` 的映射。
- HTML/Playwright -> PIL/local renderer -> text fallback。
- link-level 与 resource-level 双防抖。
- 订阅的 `recent_ids`、`filter_types`、`filter_regex`、`push_mode`、`image_limit`、`live_atall`、jitter 和跨平台去重。

## AI / 人格 / 安全 / 输出

- 最强的架构模式是中央输出收口：LLM 和插件输出都必须过统一输出流水线。
- `antipromptinjector` 提供输入风险检测和人格兼容评分思路。
- 主动行为必须 opt-in、空闲触发、安静时间、配额限制、随机抖动，并限制每个窗口消息数。
- 人格保持应分层：结构化 `PersonaProfile`、prompt guardrails、不可信上下文标签、OOC 审查、rewrite/block、最终清理。
- 普通自然语言回复必须依靠人设、性格、记忆和知识库。
- 插件效果例外：链接解析、媒体卡片、游戏/wiki 卡片、订阅推送不能让 LLM 直接编，必须走确定性解析和渲染。

## GsCore / GScore 结论

- `Genshin-bots/gsuid_core` 是主要 core runtime 参考，应桥接，不应直接合并。
- `nonebot-plugin-genshinuid` 是 NoneBot 到 gsuid-core 的桥接参考。
- `astrbot_plugin_gscore_adapter` 的队列、重连、下游分发、回执关联值得复用。
- ZZZ 以 `ZZZure/ZZZeroUID` 为主要参考。
- 鸣潮以 `Loping151/XutheringWavesUID` 为主要参考，`ScoreEcho` 可在许可和数据正确性确认后参考。
- 首个桥接里程碑只开放公共帮助、兑换码、wiki、日历、攻略等低风险命令；阻断 QR、cookie、token、authkey、账号面板、抽卡历史、资源下载和管理动作。

## 能力优先级

- P0：统一命令/权限、策略门、人格契约、输出审查、发送队列、审计、基础聊天。
- P1：Bilibili/常见媒体链接解析、手动搜索、公共游戏/wiki、群总结、天气、订阅摘要、卡片渲染。
- P2：偏好记忆、ACG/同人/音乐推荐、私聊提醒、群知识库、网页编码辅助。
- P3：账号绑定、QQ 空间自动化、大规模同人抓取、群内常驻自动发帖、完整群内 coding agent。

## 遇到的问题

| 问题 | 尝试 | 处理 |
| --- | --- | --- |
| `gh` CLI 未安装 | 尝试 `gh search repos` 查 GScore/GenshinUID/StarRailUID/ZZZUID | 改用 GitHub API 和直接仓库 URL。 |
| `apply_patch` 曾被 Windows sandbox helper 取消 | 早期尝试更新研究 Markdown | 当时用 PowerShell 写研究文档；本轮按用户授权和当前权限继续使用 `apply_patch`。 |
| PowerShell 字符串替换/插值错误 | 带反引号替换 Markdown | 改用正则和格式化字符串并验证输出。 |

## 当前结论

研究和设计目标已经完成。现在应进入实现前的最后准备：以中文核心 specs 为准，先实现窄的统一运行时插件，不要直接把参考插件整体搬进来。

## 2026-08-22：Lofter / allcpp / Pixiv 接口实测记录

### Lofter（api.lofter.com，无 cookie，需移动端 UA）
- 标签列表 POST `https://api.lofter.com/newapi/tagPosts.json`
  表单：product=lofter-android-8.2.36、postTypes=（全部）、offset=0、postYm=、returnGiftCombination=、
  recentDay=0、protectedFlag=0、range=0、firstpermalink=null、style=0、tag=<tag>、type=total
  返回：{"msg":"成功","code":0,"data":{"list":[{"postData":{"postView":{id,blogId,title,type,digest,permalink,
  firstImage:{orign,ow,oh,raw},photoCount,tagList,publishTime},"postCount":{responseCount,favoriteCount,
  reblogCount,shareCount,viewCount,hotCount,subscribeCount}},"blogInfo":{blogNickName,blogName,blogId,
  bigAvaImg,selfIntro}}]}}
- 帖子详情 POST `https://api.lofter.com/oldapi/post/detail.api?product=lofter-android-7.9.10`
  表单：targetblogid、postid、supportposttypes=1,2,3,4,5,6、needgetpoststat=1
  返回：meta.status=200、response.posts[0].post{id,type,blogId,title,publishTime,digest/content(HTML),
  firstImageUrl(JSON 数组),photoLinks(JSON 数组,每项 rw/rh/ow/oh/raw/orign/middle),photoCaptions,
  firstImageWH[w,h],wordCount,blogPageUrl,tagList,ipLocation,postCount{responseCount,favoriteCount,
  reblogCount,shareCount,viewCount,subscribeCount,postHot},blogInfo{blogName,blogNickName,bigAvaImg,homePageUrl}}
- 主题页 `https://www.lofter.com/theme/preview/{id}` 服务端内嵌 `this.p={themeid:'120002',previewBlogName:'lofterphoto3'}`。
- 新版 permalink /post/{token}（如 844ef704_2bd1d2f81）无法用数字 id 直接解析，newapi/postDetail.json、
  v1.1/postDetail.api、v2.0/postDetail.api 均 404；web 端为 React SPA 无 SSR。保留 og 降级 + 待查前端接口。

### allcpp（www.allcpp.cn，无 cookie）
- 活动页 `https://www.allcpp.cn/allcpp/event/event.do?event=6733` 服务端内嵌：
  var worksObjId=6733; var WORKSOBJNAME="..."; var EVENTUSERID=1136855;
  eventParam.EID/picUrl/eventName/lastDays/sDate/eDate/enterAddress/eventTag/desContent/isOnly/eventType
  （eventType: 1茶会 2综合同人展 3 ONLY展 4游戏展 5线上活动；isOnly:1 独家）
- 列表接口 GET `https://www.allcpp.cn/allcpp/event/eventMainListV2.do`（time/sort/keyword/pageNo/pageSize/
  positionStatus/type/day/isOnline/ticketStatus），图片前缀 https://imagecdn3.allcpp.cn/upload。
- 注意事项：geteventdetail2.do 的 eventid 与页面 event 参数 ID 空间不一致（eventid=6733 返回另一场次），
  因此解析以页面 SSR eventParam 为准，不用该接口。

### Pixiv（www.pixiv.net 直连被墙，必须走 127.0.0.1:7890）
- ajax/illust/{id}：body{illustId,title,userName,userId,width,height,pageCount,likeCount,bookmarkCount,
  viewCount,commentCount,illustType,description,tags:{tags[]},urls{mini/thumb/small/regular/original},sl}
- ajax/illust/{id}/pages：body[{urls{thumb_mini/small/regular/original},width,height}]
- ajax/user/{id}/profile/all：body{illusts/manga/novels 各为 {作品id:null}，计数=键数；bookmarkCount 等}
- ajax/user/{id}?full=1：follower/following（已有实现使用）
- 封面用 embed.pixiv.net/artwork.php?illust_id={id} 代理图（QQ 可加载）。


## 2026-08-22：bilibili-api-python 可用性实测 + 端点挖掘（参考实现依据）

### 结论：库本身可用（GPL-3.0，仅作离线参考，代码不入项目）
- 版本：17.4.2（2026-06-19）与 16.2.0 的 sdist 已下载到 `research/bilibili_api_sdists/`（git 忽略）。
- 在独立临时 venv（未污染项目依赖）安装 17.4.2 + curl_cffi/httpx 实测：
  - 免登录可用：video.get_info()（stat 播放/点赞/投币/收藏/弹幕/评论 + pages）、
    user.get_user_info()、user.get_videos(ps=5)（wbi 签名）、bangumi.get_overview()。
  - 带 cookies.txt 登录态（SESSDATA/bili_jct/buvid3/DedeUserID 均存在）可用：
    user.get_dynamics_new()（返回 12 条动态含 id_str）、live.get_room_info()（完整房间信息）、
    bangumi.get_episodes()（集数列表）。live.get_general_info() 返回空，get_room_info 已够用。
- 构造签名：Bangumi(media_id=-1, ssid=-1, epid=-1)；LiveRoom(room_display_id)；ChannelSeries(uid, type_, id_)。

### 关键端点清单（摘自 17.4.2 data/api/*.json，只记录事实、不复制 GPL 代码）
- 视频：GET x/web-interface/view（aid/bvid）；x/player/pagelist（分P）；x/web-interface/archive/stat；
  x/player/wbi/playurl（WBI，fnval=4048 DASH）。
- UP主视频：GET x/space/wbi/arc/search（mid/pn/ps，**WBI**）；置顶 x/space/top/arc（vmid）。
- 动态：GET x/polymer/web-dynamic/v1/feed/space（host_mid/offset/timezone_offset=-480/features，**WBI**，
  需 x-bili-device-req-json/x-bili-web-req-json 指纹头）；单条 x/polymer/web-dynamic/v1/detail（WBI）；
  图文 opus x/polymer/web-dynamic/v1/opus/detail（timezone_offset/id）。
- 直播：GET xlive/web-room/v1/index/getInfoByRoom（room_id）。
- 番剧：GET pgc/view/web/season（season_id/ep_id）；pgc/web/season/section（剧集分段）；pgc/web/season/stat（追番/弹幕/播放/硬币）。
- 合集：GET x/polymer/web-space/seasons_series_list（mid/page_num/page_size，合集列表）；
  x/polymer/web-space/seasons_archives_list（mid/season_id/page_num/page_size，合集内视频）；
  旧版系列 x/series/archives（mid/series_id/pn/ps）。
- 收藏夹：GET x/v3/fav/folder/info（media_id）；x/v3/fav/resource/list（media_id/pn/ps/order/type/tid/platform/web_location）；
  x/v3/fav/folder/created/list-all（up_mid）。
- 用户计数：GET x/space/navnum（mid）。
- 决策：沿用已批准计划——WBI 自研移植（MIT bili-helper 参考），运行时不自带 GPL 库；
  端点/参数/返回字段以本文件与库源码 JSON 为准，实现时用项目 http_util + cookies.txt 实测验证。


## 2026-08-22：nonebot-plugin-orm SQLite 底座结论

- `nonebot-plugin-orm 0.8.3` 的 `sqlite`/`default` extra 指向 `sqlalchemy[aiosqlite]`；只装主包不会带 aiosqlite，启动会因缺驱动报「没有数据库」。
- 配置键为 `SQLALCHEMY_DATABASE_URL`；未配置且没有 binds 时会退到插件数据目录，本项目显式写 `sqlite+aiosqlite:///data/nonebot_orm.sqlite3`（相对项目根目录），避免迁移 CLI 与运行时落在不同文件。
- nb-cli 1.7 已移除 `nb run --env-file`；`nonebot.init()` 默认加载 `.env` + `.env.prod`，因此 `nb orm upgrade`、`nb orm check`、`nb run` 在项目根目录直接执行即可，三者都会读到同一连接串。
- NapCat 反向 WS 可用查询参数传 token：`ws://127.0.0.1:3001/?access_token=<token>`；token 与 NapCat WebUI 网络配置必须一致。

### 补充结论（启动烟测暴露）
- NoneBot 2.5 的反向 WS 客户端能力由 `~websockets` 驱动器提供；`~fastapi+~httpx` 只给 HTTP 客户端+ASGI 服务，`ONEBOT_WS_URLS` 会被 OneBot V11 忽略。
- 含 `from __future__ import annotations` 的插件，若 handler/rule 注解使用 `Event`、`Bot`、`T_State`，这些名字必须在模块全局可见；只写在注册函数内部的局部 import 无法被 NoneBot 的 ForwardRef 求值使用。

### 补充结论（QQ 实测定向）
- 安全审查的正则不能只认 `key=非空白`：状态/诊断输出普遍使用 `api_key=set`、`token=missing` 这类占位值，会把正常命令误拦成“输出未通过安全或隐私检查”。
- 放行策略限定为 `set/missing/[redacted]` 三个占位值；真实密钥（如 `sk-...`、任意长 token）仍会被拦截并脱敏。


## 2026-08-23：本轮新增结论

- 向量知识库默认关闭，避免误用不支持 `/embeddings` 的服务；启用前必须确认 model/base_url/API key 属于支持 embeddings 的 OpenAI-compatible 服务。
- 大文件（约 3.8MB 百科）适合向量检索；顺序取块回退会偏向列表靠前的文件，因此增加了跨文件关键词检索作为中间回退。
- NapCat 图片段对相对本地路径不稳定，统一转绝对路径后发送成功率提高。

## 2026-08-23：PostgreSQL/asyncpg 关键结论
- Windows 上 psycopg 3 异步明确拒绝 ProactorEventLoop；nb run 不执行项目 bot.py，无法靠 bot.py 设置 SelectorEventLoop 兜底，且 nb-cli 自身在 SelectorEventLoop 下不能 spawn 子进程。最终选 asyncpg（兼容 Proactor 循环），恢复标准 
b orm 流程。
- EDB PostgreSQL 17 安装器可静默安装：--mode unattended --unattendedmodeui none --prefix/--datadir/--superpassword/--serverport/--servicename；服务创建需 UAC 提权，退出码 0 且数据目录初始化即成功。
- URL 中密码含 @ 必须编码为 %40；NoneBot 环境变量值不自动做 URL 解码，需在连接串里预编码。
- nonebot-plugin-orm 的 _engines/_metadatas 由 driver on_startup 初始化，命令行迁移需 nb-cli 正常加载插件链；nb-cli 1.7 无 --env-file 参数，.env/.env.prod 由 nonebot.init 自动加载。

## 2026-08-23：B站商品与卡片渲染结论

- B站魔力赏市集列表接口：POST https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list，请求体 {sortType, priceFilters:["0-100000001"], discountFilters:["0-101"], categoryFilter, nextId}，需登录 Cookie，未登录返回 code=83001002，且会触发 -412 风控。
- 返回 data.data[] 字段：c2cItemsId/c2cItemsName/showPrice/showMarketPrice/price(分)/uid/uname/uface/detailDtoList[].name|img|marketPrice|itemsId；c2cItemsId 即详情页 itemsId。
- 市集商品详情页为 SPA，无稳定公开详情 JSON；当前方案是列表接口按 itemsId 翻页匹配（最多 5 页），未命中/风控则 og 或浅层降级。
- 参考实现 BiliMagicMarketScraper / BilibiliMall-Crawler 均为 MIT/Apache 兼容的自研参照，仅用于确认请求体字段，代码未并入。
- astrbot_plugin_parser 为 MIT（Copyright (c) 2024 Les Freire），仅移植模板结构与 RenderPayload 字段设计，GPL 的 bilibili-api-python 未使用。
- 2026-08-23 真实只读烟测：市集列表接口带完整登录 Cookie（含 buvid3/4）+ Origin 仍返回 code=0/data.data=null，说明当前需要设备指纹等 Web 逆向信息；本项目按契约实现列表匹配，真实环境命中为空时自动走 og/浅层降级，不阻断消息链路。

## 2026-08-23：阿里云百炼 qwen3.7-text-embedding 调用方式

- 模型 ID：`qwen3.7-text-embedding`；OpenAI 兼容端点：POST `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/embeddings`，经典公共云地址 `https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings` 也可用。
- 请求体：`{"model":"qwen3.7-text-embedding","input":[...],"dimensions":1024,"encoding_format":"float"}`；Header `Authorization: Bearer <API_KEY>`；`dimensions` 可选 2560/2048/1536/1024(默认)/768/512/256，OpenAI 兼容模式用复数 `dimensions`，DashScope 原生模式用单数 `dimension`。
- 返回 `data[].embedding` + `index`，与 OpenAI 格式一致，直接按 index 排序即可。
- 限制：字符串列表最多 20 条/请求、单行 128,000 Token；本项目把嵌入批大小从 32 下调为 10（同时兼容 v4 的 10 条上限）。
- 项目已支持 `BOT_EMBEDDING_DIMENSIONS`，并新增 `embedding-smoke`（连通性）与 `knowledge-sync`（预建库、断点续跑）两条本地命令。

## 2026-08-23：本地 Ollama bge-m3 优先嵌入

- Ollama OpenAI 兼容端点：`POST http://127.0.0.1:11434/v1/embeddings`，body `{"model":"bge-m3","input":[...]}`；bge-m3 返回 1024 维，单条上下文 8192。
- 坑1：无 Key 时不能发送空 `Authorization: Bearer ` 头，httpx 会抛 LocalProtocolError（非法头值）；本地链必须整头省略。
- 坑2：bge-m3 首次推理要加载模型，实测约 15 秒，本地超时设为 60s（原来 5s 会误判不可用而切到远程）。
- 多链优先级：本地链（bge-m3）→ 远程链（qwen3.7-text-embedding,text-embedding-v4）；成功后 sticky 到当前链，失败再切。
- 模型/端点切换安全：knowledge_meta.embedding_signature 记录端点+模型指纹，变化时自动清空全部旧向量重嵌，避免不同向量空间混用。
- 真实烟测：embedding-smoke 命中 `127.0.0.1:11434 / bge-m3`；knowledge-sync 用 bge-m3 重建 2777/2777 行；语义检索命中守岸人人格档案/设定。

## 2026-08-23：本地未运行时的静默回退保证

- 回退路径已用真实死端口（127.0.0.1:11435）端到端验证：本地连接失败 → 自动切 `https://dashscope.aliyuncs.com/compatible-mode/v1` 的 `qwen3.7-text-embedding`，返回 1024 维，exit=0、无异常输出。
- provider 对每条链逐个 try/except：ConnectError、HTTP 404（模型未拉取）、HTTP 4xx/5xx、返回体缺 `data` 等全部静默跳到下一链；所有链都失败时返回空列表，store.retrieve 返回空并回退关键词/顺序取块，不打断对话。
- 配套回归测试：本地 404 / 结构异常 / 全链不可用 三条用例锁定该保证。

## 2026-08-23：对话体验四项修复的结论
- 颜文字断行根因1：动作格式器把“(≧▽≦)”这类括号当成动作描写拆到单独一行；修复规则=括号内无汉字且无嵌套括号时视为颜文字保持原位。
- 颜文字断行根因2：合并转发的超长段落硬切在固定字符位，可能从表情中间切断；改为优先在句末标点/空白处断开。
- “平台单条消息长度限制”提示来自 chat 输出预算；现支持 0=不限制（BOT_REPLY_MAX_CHARS_PER_MESSAGE / BOT_REPLY_*_MAX_MESSAGES / BOT_RENDER_FORWARD_MIN_CHARS 均为 0），完整回复单条直发、不追加提示。
- angel_heart / angel_memory 均为 AGPL-3.0：只借鉴模块化提示词分区、两级决策、工具化检索的设计思路，未复制代码或原文；详见 research/angel_prompt_patterns.md。
- 世界观“打哑谜”修复：系统提示新增“先事实后感受”规则——先给名词的确切定义，再表达人格感受；知识库检索 top_k 提到 6、上下文预算提高到 4096/6144。

## 2026-08-23：基层统一路由架构
- 新增 `runtime/base_router.py`：所有入站文本先做确定性分类（订阅/别名/管理员/自动发送/点歌模式/点歌/历史/wiki/epic/天气/链接解析/人格对话/忽略），带 reason+audit_tags 可审计。
- NoneBot 的 12 个 matcher rule 全部改为调用基层路由器，避免“matcher 一套判断、文档一套判断”漂移；matcher_count 保持 12。
- 新增 `/bot route <文本>`：管理员可在 QQ 里直接查看基层对任意文本的判定（路由/能力/优先级/理由）。
- 人格权威来源切换为用户三份文件：守岸人档案.md、守岸人人格档案.md、守岸人人格设定.md（BOT_PERSONA_FILES）。
- 执行闭环不变：子能力返回 CapabilityResult → 基层 review/render → SendRequest → NapCat；子能力不直接发消息。