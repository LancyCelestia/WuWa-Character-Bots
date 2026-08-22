# 任务计划

## 目标

下载并分析合适的 NoneBot 插件，对比现有 AstrBot 插件，形成可执行的统一角色机器人插件系统设计建议。

当前该研究目标已经完成。下一阶段不是继续盲目找插件，而是按核心规格实现统一 NoneBot 运行时插件。

## 范围

1. 从官方商店和 GitHub 项目中筛选 NoneBot 插件候选。
2. 下载候选源码到工作区，方便离线分析。
3. 检查 `C:\Users\LancyCelestia\.astrbot` 下已有 AstrBot 插件。
4. 对比插件结构、事件入口、解析、存储、调度、API 调用、渲染、输出和反馈模式。
5. 提出统一架构、优先级和不扰民的实用能力清单。
6. 将核心运行时、输入输出、自动发送、人格/记忆/知识库、媒体解析/订阅/卡片渲染写成中文规格。

## 阶段

- [x] Phase 0: 确认工作区状态并初始化研究文件。
- [x] Phase 1: 建立候选插件清单。
- [x] Phase 2: 下载选定 NoneBot 插件源码。
- [x] Phase 3: 按类别分析下载的 NoneBot 插件。
- [x] Phase 4: 分析相关 AstrBot 插件架构。
- [x] Phase 5: 对比模式并提取可复用设计规则。
- [x] Phase 6: 产出建议报告和下一步实现范围。
- [x] Phase 7: 按 2026-07-06 官方 registry 快照补充第二批候选。
- [x] Phase 8: 补齐 fetch/crawl、投递反馈、GsCore 来源选择和运行时契约。
- [x] Phase 9: 将核心入口和 specs 中文化，并补充人格优先、插件确定性输出、NoneBot/NapCat 边界。

## 候选类别

- AI / LLM / persona / memory
- 链接解析、媒体解析、订阅
- 搜索、推荐、知识检索
- 天气、灾害、交通、生活工具
- 游戏查询生态：Wuthering Waves、Arknights、Endfield、Genshin、Star Rail、Zenless Zone Zero
- 群聊分析、总结、记录
- 安全、权限、反注入、反刷屏
- 渲染、卡片、图片输出、合并转发

## 已定决策

- 统一运行时链路以 `IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord` 为准。
- capability adapter、source adapter、parser、provider 不能直接发送消息。
- 普通自然语言回复必须使用 `PersonaProfile`、`ToneProfile`、记忆和知识库上下文。
- 链接解析、媒体卡片、游戏/wiki 卡片、订阅推送等插件效果走确定性 parser/source/render/send 链路，不能让 LLM 编造。
- GScore 来源选择记录在 `research/implementation_design_supplement.md`；ZZZ 以 `ZZZure/ZZZeroUID` 为主，鸣潮以 `Loping151/XutheringWavesUID` 为主。
- 高风险能力默认私聊、管理员确认或后续阶段；账号绑定能力必须先有密钥存储、脱敏、撤销和审计。
- 官方插件目前是参考证据和模式来源。首个实现应先做窄的 runtime shell，只在契约合适时才引入直接依赖。

## 验证要求

- 下载来源路径记录在 `research/downloaded_sources.md`。
- 每类插件至少有架构笔记或说明为何不采用。
- 最终建议区分直接复用、适配复用、自研。
- 文档验证通过：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 docs-check
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 verify
```

## 下一步

实现 Milestone 0/1：

1. 统一运行时插件骨架。
2. Pydantic/数据类契约模型。
3. policy gate、audit logger、output choke point。
4. 一个安全 LLM adapter。
5. 一个低风险 parser、一个摘要命令、一个天气或公共游戏/wiki 命令。

## 本轮（2026-08-22）：Lofter / allcpp / Pixiv 深度解析

背景：上一会话最后要求「加入 lofter、allcpp、pixiv 的解析」。当前这三站仍是占位卡片（SPA 降级）或半成品，
本轮把已验证的公开接口落地为深度解析，并纳入统一注册表。

### 已验证事实（实测 2026-08-22）
- Lofter 标签页：POST https://api.lofter.com/newapi/tagPosts.json（UA LOFTER-Android 8.2.36，表单
  product/postTypes/offset/postYm/.../tag/type=total），返回 code=0 + data.list[]，含 postView.title/digest/
  firstImage/photoCount/tagList/publishTime、postCount(喜欢/评论/转发/分享/热度)、blogInfo(昵称/博客名)。
- Lofter 帖子详情（仅数字 {blogId}_{postId}）：POST https://api.lofter.com/oldapi/post/detail.api
  ?product=lofter-android-7.9.10（表单 targetblogid/postid/supportposttypes/needgetpoststat），返回
  response.posts[0].post：title/content(HTML)/photoLinks(JSON，含 ow/oh/orign)/firstImageWH/tagList/wordCount/
  blogPageUrl/blogInfo/postCount(postHot 等)。新版 permalink 令牌 /post/{token} 的解析接口未公开，保留 og 降级。
- Lofter 主题页：https://www.lofter.com/theme/preview/{id} 服务端内嵌 this.p={themeid:'...',previewBlogName:'...'}。
- allcpp 活动详情：https://www.allcpp.cn/allcpp/event/event.do?event=N 服务端内嵌 eventParam.*（EID/picUrl/
  eventName/sDate/eDate/enterAddress/eventTag/desContent/isOnly/eventType）与 WORKSOBJNAME/EVENTUSERID。
- Pixiv：www.pixiv.net 直连不可达，经 127.0.0.1:7890 可用；ajax/illust 返回 userId/userName/width/height/
  pageCount/likeCount/bookmarkCount/viewCount/commentCount/urls；ajax/illust/{id}/pages 返回每页 urls+width/height；
  ajax/user/{id}/profile/all 返回 illusts/manga/novels（计数=字典键数）。
- 结论：pixiv 需加入代理平台集合（BOT_DOWNLOAD_PROXY）；Lofter/allcpp 无需 cookie 与代理。

### 任务拆分（并行子代理，互不重叠写集）
1. platforms_lofter.py + http_util.http_post_form + tests/test_lofter_parser.py
2. platforms_allcpp.py + tests/test_allcpp_parser.py
3. platforms_pixiv.py（含 pages/profile-all 深解析与 proxy 参数）+ tests/test_pixiv_parser.py

### 集成（主控）
- platforms_generic.py 移除旧 parse_lofter/parse_allcpp/parse_pixiv；parsers/__init__.py 改导入并把 pixiv 加入
  _PARSER_PROXY_PLATFORM；更新受影响测试与 README/COMMANDS；全量 verify；commit。
