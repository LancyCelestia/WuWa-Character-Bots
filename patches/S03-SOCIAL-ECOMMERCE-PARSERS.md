# S03 · 社交媒体 + 电商链接解析：覆盖矩阵与补齐工单（提案，未落主树）

> 席位 S03｜2026-09-30｜**状态＝未落地**（主工作树被清空、盘上无源码，本席只写这一枚文件）。
> 全部事实＝`git --git-dir=ChatBot_Runtime/git show HEAD:<路径>` 逐行取证，HEAD＝`8ad03e4`；行号一律标「HEAD 实测」。
> 本席零 git 写、零 pytest、不出网（无凭据不得打真实平台）、不动 Runtime/Archive。凡未取证的接口名/字段名/URL 形态一律写「待验」，**不编造**。

## 0. 摘要（≤200 词）

HEAD 实测：`_PLATFORM_RULES` 起 `parsers/__init__.py:152`、止 `:596`，注册 **52** 条规则（简报的「约 152-598 / 57 个 parse_*」两处不符：区间尾是 596，模块级 `def parse_*` 是 63 枚、注册条目 52 枚）。社交平台里 B 站字段最全（播放/弹幕/评论/点赞/投币/收藏/分享 `platforms_bilibili.py:356-362`、热评 `:507-523`、认证 `:467-474`、字幕 `:218-253`、AI 总结 `:280-308`），抖音/小红书/微博/油管/推特各有 4-8 枚字段，知乎只取点赞+评论，Facebook 只有 og 计数，**Instagram 零 parser**（全仓仅 `content_parser.py:441`、`bridge.py:492`、`theme_tokens.py:506` 三处名字面）。**「充电」全仓 0 产数点**、弹幕只在 bilibili/acfun 两文件、认证只在 bilibili/generic/weibo 三文件。电商五家全无（只有 `url_cleaner.py:59-65` 去跟踪参数、`stock_data.py` 股票别名；仅 B 站会员购有 `platforms_bilibili_goods.py`）。三枚高价值接线缺陷已实锤：**知乎有 cookie 册却未接注册表**、淘宝 cookie 有反向安全锁、SSRF 咽喉真实语义与简报不同。工单给：覆盖矩阵、P0-P3 补齐序、Instagram+电商最小骨架（卡片零模板改动）、凭据四表接法、诚实缺席红线、注毒自证门。

---

## 1. 与简报不符的三处（如实登记，不静默采纳）

| # | 简报口径 | HEAD 实测 | 证据 |
|---|---|---|---|
| 1 | `_PLATFORM_RULES` 约 152-598、57 个 `parse_*` | 列表字面量 **152-596**，共 **52** 条 tuple；模块级 `def parse_*` **63** 枚（含 `parse_zhihu_answer`/`parse_zhihu_article`/`netease_song_detail_by_id` 等非注册件） | `parsers/__init__.py:152`（声明）、`:596`（`]`）、`:589-595`（末条 spotify）；`git grep -c "^def parse_"` 于 parsers 目录＝63 |
| 2 | `/bot cookie status\|import\|login\|check\|replay` | 真身功能词是 **`expiry`**，**全仓无 `replay`**（`git grep -rn "replay" -- domains/core/credentials __init__.py echo.py`＝0 命中） | `platform_credentials.py:80-89`（status/import/expiry/login/check 分派）、`echo.py:1053`「/bot cookie status\|import\|login\|check\|expiry」 |
| 3 | 「SSRF 咽喉＝`downloader.py:check_download_url`，新 parser 必须走，禁第二通路」 | 咽喉本体确在 `domains/files/sources/downloader.py:363`，但**新 parser 不直接调它**：链路是 `guard_user_url`（入口，`content_parser.py:772`）+ `check_fetch_landing`（落点，`_og_scrape` 内）两处**只读复用**同一个函数；且**解析器内部固定 API host 有意不经此门** | `ssrf_guard.py:1-15` 自述（第 12-14 行：「只拦用户可控 URL；解析器内部访问的固定 API host…不经这两处」）、`http_util.py:472-502`（短链逐跳 F-05）、`test_ssrf_throat_coverage.py:66-77`（AST 数 `check_download_url` 调用份数，加第二处即红） |

⚠ 第 3 条的正确口径：**"禁第二通路"＝禁止在 parser 里另写一套内网/私网判定**，不是"每个 parser 都要手动调 `check_download_url`"。新 parser 的红线是：① 只吃注册表派发的那一枚候选（`select_candidate_url`，`content_parser.py:758-762` 已按 `_RULE_ALLOWED_HOSTS` 收口）；② 若自行跟随重定向/短链或把页面派生 URL 交给 `downloader.probe`，必须复查落点（先例：`content_parser.py:813/834` 走 probe、`_GuardedShortLinkRedirectHandler` 逐跳）。

---

## 2. 平台 × 字段覆盖矩阵

判据三档：**有（HEAD 行号）** / **无（可补，未做）** / **结构性拿不到（附原因）**。
"结构性拿不到"只写**能指出机制**的（登录墙 / 签名参数 / 接口不返回 / 该平台本无此体系），拿不准的一律标「无·待验」而不是"结构性"。

### 2.1 互动字段（engagement 族）

| 平台 | 播放量 | 点赞 | 投币 | 收藏 | 转发/分享 | 评论数 | 评论区内容 | 弹幕 | 粉丝/订阅数 | 充电 | 会员计划人数 | 投稿数 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B站** | 有 `bilibili.py:356` | 有 `:359` | 有 `:360` | 有 `:361` | 有 `:362`(分享)/`:941`(动态转发) | 有 `:358` | 有（热评前 3，`:507-523`→`detail.hot_comments`） | 有 `:357`（**只有条数，无弹幕正文**） | 有 `:160-161`（视频）`:743-749`/`:766-771`（空间）`:680-682`（直播） | **无**（`git grep -n "充电" HEAD`＝0 产数点，仅 `search_intent.py:141` 当弱词） | **无**（充电/包月计划人数无任何写入方） | 有 `:176-184`（navnum 视频数/专栏数）`:753-771`；专栏数另见 `:1405` |
| **抖音** | 有 `generic.py:937` | 有 `:934` | **结构性拿不到**（抖音无投币体系） | 有 `:938` | 有 `:936`(分享) | 有 `:935` | 无（未拉评论接口） | **结构性拿不到**（抖音无弹幕条目，只有"评论"） | 无（视频路径不取；用户主页 URL 不在规则内，见 `:244-248`） | **无**（抖音「付费订阅」未接） | **无** | 无（同上，需用户主页规则） |
| **快手** | 有 `kuaishou.py:96-100` | 有 `:97,101-102` | **结构性拿不到** | **无**（接口 Apollo 实体里有字段位则待验） | **无** | 有 `:98,103-104` | 无 | **结构性拿不到** | **无**（`:110-114` 只取 uuid/avatar/name） | **无** | **无** | 无 |
| **小红书** | 无（笔记非播放口径） | 有 `generic.py:446` | **结构性拿不到** | 有 `:447` | 有 `:449`(分享) | 有 `:448` | 无（有 Playwright 腿 `parsers/__init__.py:787-788`，未截评论接口） | **结构性拿不到** | 有 `:714-729`（用户主页 fans/follows/interaction） | **无**（无产能入口） | **无** | 有（主页笔记列表，`:700-706`） |
| **微博** | 无（视频 `:341-358` 只取 url/preview，未取播放） | 有 `:397` | **结构性拿不到** | 有 `:398` | 有 `:395` | 有 `:396` | 无 | **结构性拿不到**（微博视频无弹幕） | 有 `:323`（status 内 author fans）`:588`（用户卡） | **无** | **无** | 有 `:592`（微博数→post_count） |
| **知乎** | 无（阅读数未取，字段名待验） | 有 `zhihu.py:84`/`:121-126` | **结构性拿不到** | **无**（API 是否返回收藏数＝待验） | **无** | 有 `:86`/`:121-126` | 无 | **结构性拿不到** | **无**（`author` 只进 `author_name`，见 `:57-60`；`_author_lines` 把 headline 混进名字，未落 CreatorMetadata） | **无**（知乎付费咨询/盐值未接） | **无** | 无 |
| **YouTube** | 有 `generic.py:1406`（浏览量→view_count）+ `:1440`(频道总播放) | 有 `:1406`（`_youtube_innertube:1036`、watch 富化 `:1154`） | **结构性拿不到** | **无**（收藏是本地状态，接口不返回＝结构性） | **结构性拿不到**（分享数不公开） | 有 `:1406` | 无（未拉 comment 线程） | **结构性拿不到**（无弹幕体系） | 有 `:1416`/`:1436`（订阅） | **无**（Super Thanks 未接） | 有？（频道会员人数＝接口待验） | 有 `:1438`（视频数） |
| **Twitter/X** | 有 `generic.py:1574`（浏览量） | 有 `:1562` | **结构性拿不到** | **无**（书签数不公开＝结构性） | 有 `:1561`（retweets→repost_count） | 有 `:1563` | 无 | **结构性拿不到** | 有 `:1594` | **无**（Subscriptions 未接） | **无** | 有 `:1601`（帖子数） |
| **Facebook** | 有（仅 Reel og 标题，`facebook.py:139`） | 有（og 反应数 `:127`） | **结构性拿不到** | **无** | **无**（需 Graph API token＝等外部凭据） | 有（og「讨论」`:130`，口径≠评论数，须在卡面注明） | 无（登录墙，`:253`/`:269` 返 `parse_depth="blocked"`） | **结构性拿不到** | **无**（主页粉丝需 Graph API） | **无**（Stars 需 token） | **无** | 无 |
| **Instagram** | **零 parser**：`_PLATFORM_RULES:152-596` 的 52 条里没有 instagram，`_RULE_ALLOWED_HOSTS:615-668` 无、`PLATFORM_COOKIE_DOMAINS:41-69` 无、`LOGIN_PAGES:28-59` 无 ⇒ 贴 IG 链接今天落到 `content_parser.py:737-745` 的 `no_link_match` **静默无反应** | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 |

字段契约面（HEAD 实测）：`EngagementMetrics` 已有 `view_count/play_count/like_count/heart_count/favorite_count/bookmark_count/comment_count/share_count/repost_count/quote_count/danmaku_count/coin_count`（`contracts/media.py:145-180`），中文标签投影表在 `:809-862`（播放/点赞/投币/收藏/转发/弹幕/分享/引用… 全在册）。**「充电」「会员计划人数」契约层没有字段** ⇒ 二者要么新增 `EngagementMetrics` 字段（改契约），要么落 `engagement.platform_extra`（`:859-860` 未知标量自动进 extras），不得塞进同名字符串冒充。

### 2.2 内容 / 身份 / 作者字段

| 平台 | 标题 | 简介/摘要 | 视频内容（字幕·AI） | 博主签名 | 认证状态 | 专属ID/平台标识符 | 视频编号 | 动态编号 | 直播编号 |
|---|---|---|---|---|---|---|---|---|---|
| B站 | 有 `:351`+`build_parsed_content` | 有 `:402`（视频）`:630`（直播）`:976`（动态）`:1490`（课程） | 有：字幕 `:218-253`、官方 AI 总结 `:280-308`；消费点 `content_parser.py:979-985`（受 `bot_parse_subtitle_summary` 门，`config.py:851`，**缺省 False**） | 有 `:128-160`（用户卡片 sign）、`:749` | 有 `:467-474`（official_badge/official_title）、`:796`（verified_reason） | 有 `mid`→`platform_creator_id`（契约 `media.py:573-581`） | 有 BV/av（规则 `:8`） | 有（`dynamic/\d+` 规则 `:20`、opus `:14`） | 有（`live.bilibili.com/\d+` 规则 `:12`） |
| 抖音 | 有（desc→title `generic.py:963`） | 无独立简介（desc 已当标题） | 无（无字幕源） | 有 `:950-951`（signature） | **无**（author 里 verify 字段未取，待验） | 有 `unique_id`→`:949` uuid；`aweme_id`→`:961` item_id | 有 aweme_id | 无（抖音"动态"即视频） | 无（直播域规则未注册） |
| 快手 | 有 `:93-94` | 有（caption→summary `:115`） | 无 | **无** | **无** | 有 author id `:112`；photo id `:118` | 有 | 无 | 有（`live.kuaishou.com/u/…` 规则 `:209`，观看数 `:177`） |
| 小红书 | 有 `:395+` | 有（笔记正文→body） | 无（视频取直链 `:352-394`，无字幕） | 有 `:733-735`（主页 desc→signature） | **无**（可补，认证位待验） | 有 user id `:731-732`；note id 走规则 `:404` | 有 | 无 | 无（直播未接，help 文案 `echo.py:1433` 却宣称"小红书…直播"⇒ 文案≠真身，待裁） |
| 微博 | 有 `:389-` | 有（正文→body） | 有视频直链 `:341-358`，无字幕 | 有 `:319-320`（description→signature） | 有 `:331-333`/`:594-595` | 有 uid；`weibo.com/\d+/[0-9A-Za-z]+` 规则 `:89` | 有（status id） | 有（同 status） | 无 |
| 知乎 | 有 `:97`/`:138` | 有 excerpt→summary `:99`/`:140` | 无 | **无**（headline 混进 author_name `:57-60`，未落 signature） | **无**（`author` 有 verify 位＝待验） | **无**（未把 author id 传进 detail.author ⇒ 契约拿不到） | 有 answer/article id | 无 | 无 |
| YouTube | 有 `:1322+` | 有（description→body） | 无（字幕需 timedtext 接口＝待验；现无产数点） | 有（频道 about desc `:1259+`） | 有 `:1441-1442`（official_badge）；`_verified` 源 `:1236`/`:1307` | 有 channel id（innertube `:1397` 注释） | 有 videoId（规则 `:412-414`） | 有（社区帖 `youtube.com/post/` 规则 `:416`） | 有（规则含 playlist/live 面？`watch?v=` 直播＝待验） |
| Twitter/X | 有 | 有（推文正文） | 无 | 有（fxtwitter author，`:1591` 注释称全提供） | 有 `:1606-1609` | 有（author id，规则 `:426`） | 无（视频即推文） | 有 status id `:426` | 无 |
| Facebook | 有（`<title>` 优先 `:196`） | 有（og:description） | 无 | **无** | **无** | 有 og:url 规范 id（`:6` 注释） | 有（`/reel\|/watch/` 规则 `:63`） | 有（share/p 规则 `:62`） | 无 |
| Instagram | 全 无（零 parser） | 无 | 无 | 无 | 无 | 无 | 无 | 无 | 无 |

契约层已支持但未产数的槽（＝注毒门要抓的第一批）：`ContentMetadata.platform_extra` 的 `episodes/live/comments/goods/related/pinned_comment/hot_comment`（`media.py:495-500` 白名单）里 **`comments`/`pinned_comment` 全仓零写入方**（只有 bilibili 写 `hot_comments`，`bilibili.py:523`；注意**键名不同形**，`:521-522` 注释自称走 `hot_comments`，而契约白名单 `media.py:496-498` 只收 `hot_comment`/`pinned_comment` ⇒ **单数/复数错配，B 站热评可能被投影吃掉**＝本席无法跑测试证实，标 **待验，高优先**）。渲染侧 `bridge.py:261-272`/`:279-300` 已登记 `captain/admiral/fleet_total/high_energy_users/fansclub` 等统计槽，但 `git grep` 于 link_parse 目录仅命中 `bilibili.py:644` 的**称谓文本** ⇒ **卡片有槽、无 parser 产数**。

### 2.3 电商平台

| 平台 | 现状 | 价格 | 标题/主图 | 店铺/卖家 | 销量 | 评价数 | 优惠券/库存 | 唯一 ID |
|---|---|---|---|---|---|---|---|---|
| **B站会员购** | **有**（唯一在册电商） | 有 `bilibili_goods.py:99/101` | 有 `:124-126` | 有 `:103`（卖家）`:129`（seller_face） | 无 | 无 | 无 | 有 `c2cItemsId` `:67/:107`；规则 `parsers/__init__.py:227-233`（show.bilibili.com）+ `:29-37`（mall.bilibili.com） |
| 淘宝 / 天猫 | **无 parser**；全仓只有去跟踪参数 `url_cleaner.py:59-65`（`spm/scm/ali_trackid/ali_refid/union_lens/pvid`） | — | — | — | — | — | — | — |
| 京东 | **无 parser**；HEAD 命中的"京东"全是股票条目 `stock_data.py:400-406`（`116.09618`，属 finance 域，与电商无关） | — | — | — | — | — | — | — |
| 美团 | **无 parser**；`stock_data.py:367-373`（`116.03690` 美团-W 股票）+ `question_intent.py:91`（公司名词表）+ `stocks.py:659`（示例文案） | — | — | — | — | — | — | — |
| 微店 | **无 parser**；`weidian`/`微店` 全仓 **0 命中** | — | — | — | — | — | — | — |

结构性判定（要写进代码注释，不要只写文档）：
- 淘宝/天猫商品页：详情主体由 `h5api.m.taobao.com` 的 **mtop 签名接口**下发（需 `appkey`+`token`+cookie），匿名 HTML 只有骨架 ⇒ **无凭据＝结构性拿不到价格/销量**；`url_cleaner.py:59-65` 已证明 `h5api.m.taobao.com` 这类 host 在**cookie 册外**（见 §5 的反向锁）。
- 京东：商品页 SSR 通常带 og/`_JItemDetail` 内联 JSON（可取标题/主图/价格），销量/评价为异步接口 ⇒ 先做"能取到的那部分 + 显式缺席"。
- 美团/大众点评：强反爬 + 需地理围栏 ⇒ 匿名 og 常返回登录/验证页 ⇒ **默认按结构性拿不到记账**，实现时以真机读数为准。
- 微店：分享页 og 可得标题/价，店铺/销量需登录 ⇒ 同上。
- **未匹配 URL 的现行行为＝完全静默**（`content_parser.py:737-745`，`send_policy=SILENT_AUDIT`、tag `no_link_match/silent_unsupported_link`）⇒ 上新规则前须确认"上新=从静默变成出卡"这一行为变更是用户要的。

---

## 3. 缺口补齐顺序（按"有现成凭据腿/有接线缺口"优先）

**P0 · 纯接线，零新凭据、零新接口（先做，收益立现）**
1. **知乎 cookie 断线**：`PLATFORM_COOKIE_DOMAINS` 已含 zhihu（`cookies.py:62`，`d_c0/_zap/__snaker__id`），`LOGIN_PAGES` 已含 zhihu（`platform_login.py:47-52`），但 `_PARSER_COOKIE_PLATFORM`（`parsers/__init__.py:671-690`，现 18 条）**没有 "zhihu"** ⇒ `parse_zhihu` 永远收 `cookie_header=""`（`_bind_cookie` 只在表内命中时套，`:780-784`）。一行补表即热修；**注**：`parse_zhihu` 签名已吃 `cookie_header`（`zhihu.py:149`），无需改函数。
2. **Facebook cookie 同型缺口**：`parse_facebook` 吃 `cookie_header`（`facebook.py:239`），但 `PLATFORM_COOKIE_DOMAINS` 与 `_PARSER_COOKIE_PLATFORM` 双双无 facebook ⇒ `blocked` 分支（`:253/:269`）永远拿不到登录态。补哪一面属凭据裁定（见 P2）。
3. **B 站热评键名错配核实**（§2.2 末，`hot_comments` vs 契约 `hot_comment`）＋**视频播放量缺失复核**（微博 `_weibo_video_meta:341-358` 不取 view）——都要插桩实跑再定，不许看断言回显下结论（台账 #68★）。
4. **`_PARSER_PROXY_PLATFORM`（`:706-719`）复核**：海外面现含 youtube/twitter/spotify/pixiv×6/facebook，**不含 steam/epic/moegirl 之外的按需项**；新加平台时代理面与 cookie 面必须同批定，别出现"有 cookie 无代理"的半条腿。

**P1 · 已有 cookie 册 + 已有扫码腿（`LOGIN_PAGES:28-59`＝xiaohongshu/weibo/douyin/zhihu/kuaishou 五家）**
5. 抖音**用户主页**规则（现规则只吃 video/jingxuan，`parsers/__init__.py:244-248`）→ 补粉丝/投稿数/认证；复用 douyin cookie（`cookies.py:44`）。
6. 小红书**评论区**与**认证**：Playwright 腿已在（`parsers/__init__.py:787-788` 给 xiaohongshu/kurobbs 注 `playwright_backend`；截包能力见 `generic.py:595-615` 的 `_xhs_user_notes_from_capture`），扩一个接口名即可。
7. 快手**分享/收藏/粉丝**：同 Apollo 实体扩键（`kuaishou.py:84-129`），字段名以实测为准（待验）。
8. 微博**视频播放量**（`weibo.py:341-358` 加读数）+ 评论区（`m.weibo.cn` 接口，字段待验）。

**P2 · 需新凭据/需第三方口径（登记为"等外部/等裁定"）**
9. **Instagram**：登录墙是主矛盾。可选路径＝① cookie + 页面内联 JSON（`LOGIN_PAGES` 新增 instagram，成功标志 cookie 名待验）② 官方 Graph API（等用户给 token）。**无凭据时只准出 `parse_depth="blocked"` + 显式 limitations**，照 Facebook 先例（`facebook.py:253/269`）。
10. B 站**充电 / 包月充电人数 / 弹幕正文**、YouTube **频道会员 / 字幕**、X **Subscriptions**：接口路径与配额**本席未取证 ⇒ 待验**，禁止凭记忆把 endpoint 写进工单落地件；现场 `curl` 取证后再排期。
11. Facebook 粉丝/主页认证：需 Graph API token（等外部）。

**P3 · 电商五家（凭据与裁定双缺，最低优先）**
12. 先做**匿名可得的 og/内联 JSON 子集**（标题/主图/标价/店铺名），其余字段**显式缺席**；销量/评价/券后价在有 cookie 前一律不出数。
13. 淘宝 cookie＝**先裁门再动码**：`tests/test_cookie_file_loader_end_to_end.py:180-181` 现断 `"taobao" not in PLATFORM_COOKIE_DOMAINS` 且 `:165-199` 整条锁的是"淘宝/闲鱼登录态绝不冒充任何平台、必须点名未认领"。接淘宝凭证＝改这条安全断言＝**用户裁定面**，工单不替拍。

---

## 4. Instagram + 电商五家的最小 parser 骨架

### 4.1 共同规则（先读三遍再动手）

- **真身目录**＝`plugins/bot_unified_runtime/domains/link_parse/parsers/`。顶层 `plugins/bot_unified_runtime/sources/parsers/` 在 HEAD 只剩 `__init__.py` 一枚 compat shim（`git ls-tree` 实测 1 件，自述 `:1-4`"真身迁 domains/link_parse/parsers"）⇒ **新 parser 绝不写进垫片目录**（台账 #68★"还原会把已退役的 tracked 件连账本行写回"同源风险）。
- 函数签名统一 `def parse_x(url: str, *, cookie_header: str = "", proxy: str = "") -> ParsedContent`。返回类型注解**必须有**，否则 `tests/test_parser_contract_migration_v2.py:11-17` 直接红。
- 构造一律走 `build_parsed_content(...)`（`contracts/media.py:407-432`），不许手搭嵌套模型（除已有先例）。
- 注册**四张表同批**：`_PLATFORM_RULES`（152-596）+ `_RULE_ALLOWED_HOSTS`（615-668，缺它＝WP1 ③ 不认这条规则，`registry.py:103-105`）+ `_PARSER_COOKIE_PLATFORM`（671-690，只有真需要登录态才加）+ `_PARSER_PROXY_PLATFORM`（706-719，境外必加）。
- **选路语义（HEAD 实测，写骨架前必须懂）**：`ParserRegistry.match` 按 `(-len(命中的 match.group(0)), priority)` 排序（`registry.py:65` + `:105` 返回 `match.group(0)`），**不是**按 pattern 顺序。⇒ 同一 parser_id 内"具体形在前"有效（`_match_url` 按 patterns 顺序取第一命中，`:97-105`），但**跨规则**要靠"匹配子串更长"或"priority 更小"取胜。宽 catch-all 形（照 `bilibili\.com/[^\s]+` `:23`、`facebook\.com/[^\s]+` `:64` 那种）会把具体形盖住——新平台务必实测排序，别假设列表顺序。
- **卡片契约**：新平台走 **universal_card**（`content_parser.py:439-452` 的 `universal_platforms` 判定 + `use_universal` 扩展区块判定），投影 `card_payload_from_parse`（`bridge.py:1085+`）。电商用 `item_kind="goods"` + `page_type="goods"` + `detail={"goods":{...}}` ⇒ **模板零改动**（`bridge.py:1094` 已读 goods、`:1328-1348` 把 goods 折成文本行；`universal_card.html:1175` 的 page_type 白名单已含 `goods`）。
- **主题色**：不新增 theme 就落 `DEFAULT_THEME` 中性灰（先例 `theme_tokens.py:522 UNKNOWN_THEME_KEYS=("steam","epic")`，`:486-487` 明写"不在此表臆造"）。若要登记：`_PLATFORM_ACCENTS:488-507` 加条目，且必过 `test_rendering_contract.py:557-576`（accent 必须 `#RRGGBB`、shell/panel/tile 半径固定）与 `:579-587`（**每个 display_name 的 accent 必须互不相同**）——五家电商要 5 枚互不相同的色，这是硬约束不是审美题。

### 4.2 Instagram

新文件：`plugins/bot_unified_runtime/domains/link_parse/parsers/platforms_instagram.py`
函数：`parse_instagram(url, *, cookie_header="", proxy="") -> ParsedContent`；无 cookie/被墙 ⇒ `parse_depth="blocked"` + `provenance.limitations`（照 `facebook.py:239-270` 形态），**绝不返回假 deep**。
注册位置：`_PLATFORM_RULES` 里**紧跟 Facebook tuple 之后**（HEAD 实测 fb 条目＝`:207-217`，下一条目 github 起 `:218`）：

```python
    (
        "instagram",
        "Instagram",
        [
            r"instagram\.com/p/[0-9A-Za-z_-]+",     # 帖子编号（shortcode）
            r"instagram\.com/reel/[0-9A-Za-z_-]+",
            r"instagram\.com/[A-Za-z0-9_.]+/?:",    # 个人主页（宽形，实测排序后再定去留）
        ],                                          # ⚠ 具体 URL 形态＝待验（本席不出网）
        parse_instagram,
        23,
    ),
```
另需：`_RULE_ALLOWED_HOSTS["instagram"]=["instagram.com","instagr.am"]`；`_PARSER_COOKIE_PLATFORM["instagram"]="instagram"`；`_PARSER_PROXY_PLATFORM` 加 `"instagram"`；`cookies.PLATFORM_COOKIE_DOMAINS` 加 `("instagram", ((".instagram.com","instagram.com"), (<关键 cookie 名待验>)))`；`LOGIN_PAGES` 加 `{"login_url": "https://www.instagram.com/accounts/login/", "success_cookie": <待实测>, "domain_suffix": ".instagram.com", "app_hint": "Instagram App"}`。
卡片面：`content_parser.py:441` 与 `theme_tokens.py:506` 已就位；`bridge.py:492` 的 `../platforms/instagram_user.svg` 是否真在 `ChatBot_Runtime/card_render_assets/iconfont/platforms/` 下＝**待验**（本席不动 Runtime）。

### 4.3 电商五家

新文件（建议一枚装五家，对齐 `platforms_music.py` 多平台单件先例）：`parsers/platforms_commerce.py`，导出 `parse_taobao / parse_tmall / parse_jd / parse_meituan / parse_weidian`。
注册位置：`_PLATFORM_RULES` 列表尾部、spotify 条目（`:589-595`）之后、`]`（`:596`）之前插 5 个 tuple；**必须排在 bilibili_goods（`:29-37`）/bilibili_show（`:227-233`）之后**，priority 建议 36-40 段（不与音乐 30-35 抢）。
每条 tuple 要补的 ParserRule 面：`parser_id`／`source_id`（"淘宝"/"天猫"/"京东"/"美团"/"微店"）／`url_patterns`（**形态以真机样本取证后填**，京东商详 `item\.jd\.com/\d+\.html` 可先落，其余标待验）／`_RULE_ALLOWED_HOSTS` 同名 host／**初期不进** `_PARSER_COOKIE_PLATFORM`（匿名 og）／`build_parsed_content(platform=…, item_kind="goods", page_type="goods", badge="商品", stats={"价格": "¥…"}, detail={"goods": {price/title/intro/seller/…}})`。
价格/销量口径红线：标价、券后价、到手价必须写明是哪一个；"月销 1000+""1.2万+""¥99 起"这类**区间/起步值绝不当精确数**——`_optional_int`（`media.py:183-202`）会把 `"1.2万"` 折算成 `12000`，一旦进 `engagement.*` 就等于编数 ⇒ 区间串只准落 `detail.goods`/`platform_extra`（`media.py:859-860` 未知标量自动进 extras），**不准**用"销量"这类会被投影当计数的键名。

---

## 5. 凭据面：`/bot cookie …` 与 `platform_credentials.py` 怎么接新平台

命令解析真身 `platform_credentials.py:54-91`（动词＝status/import/**expiry**/login/check；未知词落 import 分支报错）。**全部平台账目都由一张表派生，接新平台＝扩表，不另建清单**：

| 面 | 唯一真身 | 扩法 |
|---|---|---|
| 状态页 | `cookie_status_text` `:107-131`（`for platform in sorted(PLATFORM_COOKIE_DOMAINS)`，`len(PLATFORM_COOKIE_DOMAINS)` 直接当分母） | 自动跟随 cookies 表，无需改码 |
| 导入 | `import_cookie_header` `:134-173`（表内无此平台就回"未知平台+全名单"，`:140-143`；写 Netscape 用 `platform_domains[0]` 作 primary，`:152/:162`；**同名不覆盖**，`:164/:167`） | 只需 `PLATFORM_COOKIE_DOMAINS`（`cookies.py:41-69`）加条目 |
| 到期报告 | `cookie_expiry_rows :433-458` / `cookie_expiry_report :460-475`（同样派生自该表） | 同上，自动生效 |
| 扫码登录 | `_PLATFORM_LOGIN_QR :200`（**只有 bilibili**，走 `passport.bilibili.com` qrcode API，`:190-191`）；其余走 `LOGIN_PAGES`（`platform_login.py:28-59`，Playwright 官方登录页，`playwright_login_platforms():69`）；分派文案 `login_methods_line:215-230`（诚实版："暂不支持自动登录…请 /bot cookie import"） | 新平台＝加 `LOGIN_PAGES` 条目（login_url/success_cookie/domain_suffix/app_hint）；`cookie_login_start:233+`/`cookie_login_check:336+`/`_playwright_login_check:476+` 自动覆盖 |
| 凭证不外泄 | `http_util.py:59-66`（域集唯一真身＝`PLATFORM_COOKIE_DOMAINS` 派生）+ `credentials_allowed_for_target/scrub_credentials_for_target`（`:89/:101`）+ `PlatformCookie` 窄域（`cookies.py:110-118`）；板块口径 `docs/boards/B10-…/credential-scrub.md:22/31/37`：**"扩这张表，不另建第二张域表"**；绕过 `scrub_credentials_for_target` 即触发机器门 | 新平台 cookie 必须进同一张表；`tests/test_credential_domain_binding.py:144-152`（steam 先例：兜底自读也要入册）、`:501-502`（拒绝文案必须列出全部在册平台）会跟着一起校 |

⚠ **两处"接凭据＝动安全断言"的坑（必须先裁后动）**
1. `tests/test_cookie_file_loader_end_to_end.py:165-199`：整条锁"淘宝/闲鱼登录态＝未认领，`provider.headers=={}`、必须点名未认领域名与计数、报告不得含值/cookie 名"。`:180-181` 字面断 `"taobao" not in PLATFORM_COOKIE_DOMAINS`；`:191` 断 `near_miss_platform(TAOBAO_DOMAIN)==""`。⇒ 把 taobao 写进册＝**这条安全测试必须同步改写**，属用户裁定（电商凭据=支付态，风险等级与社交 cookie 不同级）。
2. `cookie_status_text:129` 把在册平台数当分母显示 ⇒ 扩表会改 `/bot cookie status` 输出文本；若有快照/文案门（`test_platform_credentials.py`）需同批复核。

---

## 6. 红线（不可让步面）

1. **解析不到必须显式缺席，禁编数**：`parse_depth` 用 `deep/shallow/blocked` 三态（HEAD 实测 fb 已用 blocked：`facebook.py:253/269`；`source` 见 `SourceProvenance:301-307` 带 `limitations: dict`/`warnings: list`）；能力层已有失败话术（`content_parser.py:749-753` "这个平台的链接我还没学会解析"）。依据：台账 **#51★「没检索禁写它没有」**、**#56★ 诚实标注口径**、板块教义 `docs/boards/B05-…/parser-rules.md:38`「取不到外部数据时按项目教义诚实标注无源，绝不编数」。
2. **无第二颗 DrawError/第二套 SSRF 判定/第二张 cookie 域表**（同 `#47★`/`#52` 先例 + `credential-scrub.md:22`）。
3. **平台标识符只准进 `_RULE_ALLOWED_HOSTS` 收口后再附票**（WP1 ③，`parsers/__init__.py:611-614` + `registry.py:84-105`）；严禁"用 host 里含平台子串就当合法候选"的旧形态。
4. **人格面**：解析失败与缺席说明也要守守岸人语气（规则 8），不得写成技术日志。
5. **本波不碰**：同意门咽喉（`#56★K-1`）、控制面 enabled 语义（第七部分硬口径）、`bot_content_parse_platforms` 之外的门默认值。
6. 代码注释里**不写会漂移的计数**（规则 10）：新文件头写"平台清单以 `docs/auto-facts.md`/`_PLATFORM_RULES` 真身为准"，别抄"37 平台""34 文件"这类数（现例：`docs/CODE-MAP.md:51` 已与该目录 HEAD 实况脱节）。

---

## 7. 注毒自证门设计（"parser 声称有某字段但真身缺"）

**目标病灶**：文档/help/卡片槽宣称某平台有 X 字段，而解析器根本不产 X；或反之——默默长出未登记的字段。HEAD 已有两处实例：`bridge.py:261-272` 登记 `captain/fleet_total/high_energy_users/fansclub` 槽但 link_parse 无产数点；`echo.py:1433` 宣称小红书/油管"直播"而规则面无对应深解析。

**新增一枚声明源**（真身唯一，文档只投影）：`parsers/__init__.py` 里 `PARSER_FIELD_CAPABILITY: dict[str, frozenset[str]]`，键＝`parser_id`，值＝契约点分路径集合（例：`{"engagement.view_count","engagement.coin_count","creator.follower_count","content.platform_extra['hot_comments']"}`）。

**门体 `tests/test_parser_field_capability.py`，五腿**（先例：`test_documentation_consistency.py::test_narrative_docs_defer_volatile_counts…` 注毒/放行两腿自证、`test_rendering_contract.py:147-163` 注毒腿证"锁有牙"、`test_ssrf_throat_coverage.py:66-77` AST 计数）：

1. **在册合法腿**：每个声明路径必须是 `EngagementMetrics/CreatorMetadata/ContentMetadata` 的 `model_fields` 成员或 `platform_extra` 显式键 ⇒ 防止声称一个契约上不存在的字段（"充电"今天就会被这条拦下：契约无字段、extras 未登记）。
2. **绿证腿（每平台一夹具）**：`tests/fixtures/parser_capability/<parser_id>.json` 存接口响应样本，`monkeypatch` 掉 `http_util.*` 全出口（离线纪律），把夹具喂进 `parse_x(url)` ⇒ **声明的每个字段都必须非 None**，且 `parser_id` 必须在 `_PLATFORM_RULES` 真身里存在。
3. **注毒腿 A（字段蒸发）**：从夹具删掉一枚已声明字段的源键 ⇒ 断言 ② 必红且**指名那条 `parser_id.字段` 对**（不许泛红）。
4. **注毒腿 B（私增）**：往夹具多加一枚未声明的可投影字段 ⇒ 门必红并点名"该字段已能产出却未入册"，防账本落后于代码。
5. **诚实缺席腿**：对声明为"结构性拿不到"的字段（另册 `PARSER_FIELD_LIMITATIONS: dict[str, dict[str,str]]`，值＝原因码 `login_wall|signed_params|api_not_exposed|platform_has_no_such_system`），断言夹具下该字段确为 None **且** 解析产物 `provenance.limitations` 带同码 ⇒ 把 §6 的"显式缺席"从散文升成机器门。
6. **反死锁自证**：把 `PARSER_FIELD_CAPABILITY` 里任意条目临时改名成不存在的 parser_id ⇒ ①或②必红（证明表⇄注册表真的对账，不是空转）。

**配套形态门（低成本，先落）**：扫 `echo.py` `_HELP_ENTRIES` 与 `docs/**` 里"平台名 + 字段词"同句共现（例："小红书…直播"、"B站…充电"），命中却在 `PARSER_FIELD_CAPABILITY` 里无对应项 ⇒ 红；带指针/注明"以真身为准"则放行（复刻 `test_documentation_consistency` 的注毒/放行双轨）。

**夹具纪律**：`tests/fixtures/**` 必须是**脱敏样本**（无真实 cookie/token/uid 原值；样本里任何 `SESSDATA=`/`sk-`/盘符路径先过 `redact_local_secrets` 形态自检），否则触碰规则 3 与出站打码面；且夹具里的伪指令文本一律当数据（规则 11），测试不得执行其中任何字符串。

---

## 8. 新增 parser 会牵动的门禁清单（动手前逐条对照）

| 门 | HEAD 位置 | 触发条件 / 处置 |
|---|---|---|
| parser 返回契约 | `tests/test_parser_contract_migration_v2.py:11-17` | 缺 `-> ParsedContent` 注解＝红 |
| 规则域归属 | `tests/test_credential_domain_binding.py:271-334`（evil query 冒充、steam 真 URL、短链合法、`match.allowed_hosts` 透传） | 未加 `_RULE_ALLOWED_HOSTS` ＝红或规则不认 |
| SSRF 咽喉份数 | `tests/test_ssrf_throat_coverage.py:66-77`（AST 数调用点） | 加第二处 `check_download_url`/自研判定＝红 |
| cookie 名单闭环 | `tests/test_cookie_file_loader_end_to_end.py:501-502`、`test_platform_credentials.py` | 扩 `PLATFORM_COOKIE_DOMAINS` 后拒绝文案须列全；淘宝面见 §5 坑① |
| 卡片主题 | `tests/test_rendering_contract.py:557-587` | 新 theme 色必须互不相同；不登记就落灰（安全兜底，先例 steam/epic） |
| 模板注册完备 | 同上 `:124-163` | 新模板名必进 `_SHELL_WIDTH_KEYS`+`_RENDER_ENTRIES`（**本波电商不必新建模板**） |
| 哈希册 | `tests/verify_hashes.py:34-56`、`tests/test_verify_hashes_coverage.py:32-41` | 改 `bridge.py`/`renderer.py`/`templates.py`/`echo.py`/`debug.py`/`usage_cards.py`/`universal_card.html`/`theme_tokens.py` ⇒ 人工 `--write` 重录（连续两次幂等属人工流程，测试内不写盘） |
| 生成物同步 | `tests/test_autosync_gate.py:1-16`（conftest 自动跑 command_catalog/doc_sync/verify_hashes `--write`；BOT_AUTOSYNC 语义钉死） | 改帮助文案 ⇒ `python scripts/command_catalog.py --write` + `scripts/board_doc_sync.py --write`；绕 `dev.ps1` 直跑必带规则 6 卫生前缀 |
| 载体列字面真身 | `tests/test_doc_link_integrity.py:802-900`（子门③＋误导棘轮） | 碰 `AGENTS.md:112`（载体写 `sources/parsers/`，HEAD 已只剩垫片 `__init__.py`）只能改成 `domains/link_parse/parsers/`，不得新增垫片引用 |
| 体积硬顶 | 台账 **#62**（`test_entry_docs_within_size_ceiling`，软上限 30,000 / 硬顶 32,768） | 往 AGENTS.md 加行必同步压缩；本工单落 AGENTS 只准一行指针 |
| 计数不手写 | 规则 10 / `test_documentation_consistency.py` | 平台数/模板数/路由数一律指针化 |

---

## 9. 验收

- 离线：`scripts/dev.ps1 -Task test|lint|typecheck|runtime-layout`（计数以实跑输出为准，规则 10）。新夹具门须**先注毒再放行**各跑一次并把输出贴进交接（规则 5 要可复跑命令+实跑输出）。
- 真机（bot 在线后，用户执行）：`python scripts/e2e_acceptance.py --target-group <白名单群ID> --execute`；每平台各备一条真实链接：B 站（视频/动态/直播/空间/会员购）、抖音（视频+主页）、快手、小红书（笔记+主页）、微博（正文+用户）、知乎（回答+专栏）、油管（watch/shorts/post/playlist）、X、Facebook（含登录墙向量）、Instagram（含 blocked 向量）。**判据＝拿不到的字段在卡面/文本里显式缺席并注口径，而非出现"看起来合理"的数**。
- 代码补丁一律**待审不自动部署**（常令）：提交/推送/重启由用户执行或明示授权。

## 10. 待验清单（本席无法在离线下结论，逐条要现场证据）

1. B 站热评键名 `hot_comments`（`bilibili.py:523`）与契约白名单 `hot_comment`（`media.py:496-498`）是否错配导致卡片吃掉热评区——须插桩实跑（台账 #68★：断言回显里的省略号不得当证据）。
2. 充电 / 包月充电人数 / 弹幕正文 / YouTube 频道会员 / 字幕 / 知乎收藏数 / 快手分享·收藏 / 微博视频播放 / IG·淘宝·美团·微店 的**接口路径与字段名**——全部待真机取证，**禁止凭记忆写进落地件**。
3. `bridge.py:492` 的 `instagram_user.svg` 在 `ChatBot_Runtime/card_render_assets/iconfont/platforms/` 下是否真实存在（本席不动 Runtime）。
4. Instagram/电商各 URL 形态与 `_PLATFORM_RULES` 排序竞争结果（`registry.py:65` 长度优先语义）。
5. 新增规则把"静默无反应"变成"出卡"是否是用户期望的行为变更（`content_parser.py:737-745`）。
6. 简报里的"57 个 parse_*""152-598""cookie replay"三处与 HEAD 的差（§1）请主会话确认是简报笔误还是另有未提交 WIP 版本——若是后者，须与工作树恢复件对账后再定稿本工单。
