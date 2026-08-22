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
