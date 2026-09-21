# V21R2 命令格式统一规格 · 附录A：现状盘点（真值源逐条坐标）

> 本文件是 CMD 席规格的**事实附录**：现存全部 77 个帮助主题的触发词/权限/路由坐标盘点。
> 真值源（本附录每条都可回溯，零编造）：
> - `plugins/bot_unified_runtime/capabilities/echo.py` 的 `_HELP_ENTRIES`（L446 起，本席逐行 grep 实证 77 个 topic）
> - `plugins/bot_unified_runtime/runtime/base_router.py` 的 `RouteKind`（L99-133）与 `build_route_rules()`（L551-588）
> - `plugins/bot_unified_runtime/runtime/capability_registry.py` 的 ROUTE_CAPABILITY_DECLARATIONS（C-06 单一声明源）
> - `docs/command-catalog.md`（`scripts/command_catalog.py --write` 自动生成物，77 模块 / 501 别名 / 33 路由规则，与本附录交叉核对一致）
> - `COMMANDS.md`（人读版，口径同源）
>
> 权限口径：`_PUBLIC_HELP_TOPICS`（echo.py L266-273）= 37 个公开主题；其余 40 个 `admin_only: True`。
> 路由优先级：数值越小越先命中（base_router `classify_message_route` 按 (priority, 声明序) 稳定排序）。
> 别名一律**原样收录**，未做任何增删；「建议新增」只出现在主规格的九形态矩阵里。

## A.0 总量核对

| 口径 | 数值 | 证据 |
|---|---|---|
| 帮助主题 | **77** | echo.py `"topic"` 计 77 处（L448~L2423）；command-catalog.md 头部「模块数：77」 |
| 触发别名 | **501** | command-catalog.md 头部「别名数：501」 |
| 公开模块 / 仅管理员 | **37 / 40** | `_PUBLIC_HELP_TOPICS` 37 项；catalog 头部同值 |
| 路由规则 | **33**（含 5 内部能力 stocks/fx/commodities/bond/northbound 无独立帮助页） | catalog「路由规则数：33」；base_router 注册表 32 行 + IGNORE 兜底 |
| 既有目录与代码已知漂移 | 1 处 | echo.py L785 帮助文本写「二次元问句(44)」，代码实值 priority=**46**（capability_registry.py:165、base_router.py:584）——本席只登记不改动 |

## A.1 管理员 `/bot` 前缀命令族（路由 ADMIN priority 11，`_admin_command_match`）

以下主题全部经 `/bot <topic> [子命令] [参数]` 进入（能力入口栏给出各 topic 实际动词面）。

| # | 主题 | echo.py 行 | 权限 | 能力入口 / 子命令面 | 触发别名（原样） |
|---|---|---|---|---|---|
| 1 | 功能管理 | 448 | 仅管理员（改仅超管） | /bot feature `list`/`get`/`enable`/`disable`/`reset`/`preview` | 功能管理；feature |
| 2 | 状态 | 470 | 仅管理员 | /bot status（无参） | 状态；狀態；status |
| 3 | 记忆 | 494 | 全员（仅本人） | /bot memory `add`/`list`/`delete`（--sensitivity=） | 记忆；memory |
| 4 | 为什么 | 522 | 仅管理员 | /bot why [id] | 为什么；为啥；why |
| 5 | 回执 | 543 | 仅管理员 | /bot receipt <id> | 回执；receipt |
| 6 | 审计 | 563 | 仅管理员 | /bot audit <request_id> | 审计；audit |
| 7 | 最近 | 583 | 仅管理员 | /bot recent [数量 1-20 默认5] | 最近；recent |
| 8 | 队列 | 604 | 仅管理员 | /bot queue（无参） | 队列；queue |
| 9 | 上下文 | 624 | 仅管理员 | /bot context [文本] | 上下文；context |
| 10 | 对话 | 646 | 仅管理员 | /bot dialogue [文本] | 对话；dialogue；对话测试 |
| 11 | 接入 | 667 | 仅管理员 | /bot setup llm | 接入；setup；llm setup |
| 12 | 配置 | 690 | 仅管理员 | /bot config（无参） | 配置；config |
| 13 | 就绪 | 710 | 仅管理员 | /bot readiness（无参） | 就绪；readiness |
| 14 | 角色 | 730 | 仅管理员 | /bot roles（无参） | 角色；roles |
| 15 | 人格 | 750 | 仅管理员 | /bot persona（自检无参；运行期切换走 /bot runtime persona） | 人格；persona |
| 16 | 路由 | 770 | **全员只读** | /bot route <文本>｜/bot routes | 路由；route；routes |
| 17 | 历史 | 796 | 仅管理员 | /bot history clear | 历史；history；清理历史 |
| 18 | 暂停 | 816 | 仅管理员 | /bot pause｜/bot resume | 暂停；暫停；pause；resume；恢复；继续；繼續 |
| 19 | 回复 | 838 | 仅管理员 | /bot reply [详细\|科普\|详尽\|精简\|简洁\|默认\|自动] | 回复；reply；详略 |
| 20 | 模型 | 863 | 仅管理员 | /bot model `list`/`set`/`add`/`update`/`priority`/`effort`/`think`/`price`/`search`/`usage`/`health`/`probe`/`routes`/`vision`/`remove`/`reset`；/bot llm 诊断 | 模型；model；llm；渠道；切换模型 |
| 21 | 用量 | 927 | 仅管理员 | /bot model usage [today\|YYYY-MM-DD]｜/bot model price | 用量；usage；账单；花费；监控 |
| 22 | 设置 | 957 | 仅管理员 | /bot runtime `set`/`get`/`list`/`reset`/`nickname`/`persona`/`instance`(--) | 设置；runtime；参数；設置；參數；运行时 |
| 23 | 搜索 | 998 | 仅管理员 | /bot search <问题> | 搜索；search |
| 24 | 解析 | 1018 | 仅管理员 | /bot parse [数量 1-100 默认10] | 解析；parse |
| 25 | 凭据 | 1038 | 仅管理员 | /bot alert check [--probe]；/bot cookie `status`/`import`/`login`/`check`/`expiry` | 凭据；凭证；憑據；憑證；登录凭证；登錄憑證；alert；cookie |
| 26 | 群策略 | 1071 | 仅管理员 | /bot group `list`/`add`/`del`/`set`/`clear`（档位 black1\|black2\|white1\|white2） | 群策略；group；群 |
| 27 | 群文件 | 1103 | 仅管理员（仅群聊） | /bot 群文件（无参） | 群文件；群文件统计 |
| 28 | 日志 | 1124 | 仅管理员 | /bot logs [debug\|info\|warning\|error] [数量 1-200 默认50] | 日志；logs |
| 29 | 文件 | 1148 | 仅管理员 | `文件 <md\|markdown\|docx\|pptx\|xlsx\|pdf> <主题>`（matcher:admin_file_export，无 /bot 前缀） | 文件；文件导出；导出 |
| 30 | 身份 | 1169 | 管理员（4 自助子命令全员） | /bot identity `show`/`set`/`tag`/`clear`＋自助 `set-name`/`set-gender`/`unset-name`/`unset-gender` | 身份；identity；会话身份 |
| 31 | 怪癖 | 1211 | 仅管理员 | /bot quirk `list`/`approve`/`retire`/`add` | 怪癖；quirk；人格怪癖 |
| 32 | 限流 | 1243 | 仅管理员 | 配置型（无独立命令）：/bot runtime set BOT_RATE_LIMIT_* / BOT_QUIET_HOURS_* 等 11 键 | 限流；句数帽；安静时间；情绪豁免；自动接话 |
| 33 | 合并转发 | 1276 | 仅管理员 | 配置型：/bot runtime set BOT_RENDER_FORWARD_* 4 键 | 合并转发；转发合并 |
| 34 | 群摘要 | 1304 | 仅管理员 | 配置型：BOT_SHARED_GROUP_CONTEXT_ENABLED / BOT_GROUP_DIGEST_* 9 键 | 群摘要；群聊摘要；群概要 |
| 35 | 视频理解 | 1338 | 仅管理员 | 配置型：BOT_VISION_* / BOT_VIDEO_* 9 键 | 视频理解；识图；vision；视频 |
| 36 | 运行开关 | 1370 | 仅管理员 | .env 5 键（SEND_QUEUE/WORKER/AUDIT/RECEIPTS/DIAGNOSTICS），改后重启 | 运行开关；诊断开关；持久化开关 |
| 37 | 邮件 | 1401 | 仅管理员（仅 TG 管理端） | /mail `status`/`accounts`/`use`/`send`/`pause`/`resume` | 邮件；电子邮件；mail；email；邮箱 |
| 38 | Telegram | 1435 | 仅管理员 | .env 配置型：TELEGRAM_BOTS / BOT_TELEGRAM_ADMIN_* | telegram；tg；电报；纸飞机；飞机 |
| 39 | 供应商 | 1461 | 仅管理员 | .env BOT_MODEL_REGISTRY＋probe_llm_providers.py --max-tokens | 供应商；provider；providers；模型供应商；包台 |
| 40 | 忽略 | 2396 | 仅管理员（排障语义） | 无专属命令（IGNORE 兜底 + 未知命令 60s 引导） | 忽略；ignore |
| 41 | 决策 | 2423 | 仅管理员 | /bot decision [N 1-100 默认20] | 决策；决策引擎；decision |
| 42 | 媒体归档 | 2051 | 仅管理员（min_role 默认 super_admin） | `收藏\|归档 [分类=] [IP=] [角色=]`＋`存聊天记录`（媒体+指令同条/回复媒体触发） | 收藏；归档；存图；收图；存聊天记录；存记录；archive；shoucang；guidang |

注：订阅（/订阅）虽走 SUBSCRIBE 路由且全员可用，因目录口径归「子功能」，见 A.2 第 43 行。

## A.2 子功能族（自然语言/短命令触发，无需 /bot 前缀）

| # | 主题 | echo.py 行 | 权限 | 路由 kind @ priority → capability | 触发别名（原样） |
|---|---|---|---|---|---|
| 43 | 订阅 | 1488 | 全员（群内 add/list 需管理员） | SUBSCRIBE @12 → bot.subscribe | 订阅；訂閱；subscribe |
| 44 | 点歌 | 1522 | 全员（点歌模式=管理员） | MUSIC @41 + MUSIC_MODE @40 → bot.music / bot.music_mode | 点歌；music；點歌；点唱；點唱；song；diange；dg；diangemoshi；dgms |
| 45 | 表情 | 1553 | 全员 | MEME @20 → bot.meme | 表情；meme；表情包；表情生成；表情制作；表情包制作；表情产生；表情包产生；表情製作；表情包製作；表情產生；表情包產生；biaoqing；biaoqingbao；bqb；biaoqingshengcheng；bqsc |
| 46 | 偷表情 | 1578 | 全员 | MEME_LIBRARY @22 → bot.meme_library | 偷表情；偷表情包；偷圖；偷图；表情隨機；隨機表情；隨機表情包；表情抽籤；steal；toubiaoqing；tbq；toubiaoqingbao；tbqb |
| 47 | 搜图 | 1604 | 全员 | on_message matcher（非 RouteKind） | 搜图；搜圖；以图搜图 |
| 48 | 天气 | 1624 | 全员 | WEATHER @41 → bot.weather | 天气；weather；天氣；查天氣；天氣預報；tianqi；tq；chatianqi；ctq |
| 49 | 行情 | 1650 | 全员 | MARKET @41 → bot.market | 行情；market；stock market；股指；股市；大盘；美股行情；港股行情；A股行情；B股行情；莫斯科股指；莫斯科行情；hangqing；hq；gushi；gs；dapan；dp；guzhi |
| 50 | 个股行情 | 1672 | 全员 | STOCKS @42 → bot.stocks | 个股行情；股价；股票价格；市值；股價；個股；英伟达股价；AMD 股价；英特尔股价；美股股价；stocks；stock；gujia；gj；gupiao |
| 51 | 商品行情 | 1701 | 全员 | COMMODITIES @41 → bot.commodities | 商品行情；黄金；金价；白银；银价；原油；油价；铜价；大宗商品；黃金；金價；白銀；銀價；油價；銅價；gold；silver；oil；commodity；huangjin；jinjia；youjia；yuanyou；baiyin |
| 52 | 国债收益率 | 1726 | 全员 | BOND @41 → bot.bond | 国债收益率；国债；债券收益率；期限利差；收益率曲线；中美国债；國債；債券收益率；guozhai；xianqilicha |
| 53 | 北向资金 | 1749 | 全员 | NORTHBOUND @41 → bot.northbound | 北向资金；北上资金；北向；沪股通；深股通；北向資金；北上資金；滬股通；beixiang；hugutong；shengutong |
| 54 | 汇率 | 1772 | 全员 | FX @41 → bot.fx | 汇率；匯率；主要货币；美元兑人民币；100日元换多少人民币；USD/CNY；fx；forex；exchange rate；huilv；换算；換算 |
| 55 | 占卜 | 1801 | 全员 | DIVINATION @41 → bot.divination | 占卜；塔罗；八字；算命；算卦；起卦；塔羅；排盤；排盘；命盤；命盘；四柱；搖卦；摇卦；今日塔羅；今日塔罗；今天塔羅；今天塔罗；塔羅三張；塔罗三张；divination；tarot；bazi；iching；zhanbu；taluo；tl；suanming；suangua；sg；qigua；qg；求籤；求签；六十四卦；金錢卦；金钱卦；生辰八字；算一卦；起一卦；摇一卦；搖一卦；掷一卦；擲一卦；占一卦；一卦；每日一签；每日一簽；每日一抽；paipan；sizhu；mingpan；pp；mp；yaogua；yg；liushisigua；lssg；jinqiangua；hexagram |
| 56 | 快报 | 1831 | 全员 | NEWS @41 → bot.news | 快报；快報；今日快报；早报；早報；晚报；晚報；今日热点；今日熱點；科技新闻；科技新聞；AI新闻；AI新聞；AI快報；财经快报；財經快報；财经新闻；財經新聞；国际新闻；國際新聞；news；kuaibao；kb；jinrikuaibao；jrkb |
| 57 | 维基 | 1859 | 全员 | WIKI @41 → bot.wiki | 维基；wiki；百科；weiji；wjbk |
| 58 | 萌娘百科 | 1880 | 全员 | MOEGIRL @41 + MOEGIRL_QUESTION @46 → bot.moegirl | 萌娘百科；萌百；moegirl；mengbai；mb；是誰；是什麼；介紹一下；是谁；是什么；介绍一下 |
| 59 | 历史上的今天 | 1904 | 全员（群内设置/取消需管理员） | TODAY_HISTORY @41 → bot.today_history | 历史上的今天；today；today in history；今日；lssd；jinrilishi；jrls |
| 60 | 下载 | 1933 | 全员 | /bot download（ADMIN 前缀族；裸「下载」不走路由） | 下载；download |
| 61 | 昵称 | 1959 | 全员（/bot 昵称 set 管理员） | ALIAS @10 → bot.alias | 昵称；alias |
| 62 | 链接 | 1984 | 全员 | CONTENT @46 → bot.content | 链接；links |
| 63 | 草稿 | 2005 | 全员（仅预览） | AUTO_SEND @13 → bot.auto_send | 草稿；autosend；自动发送；报存；報存 |
| 64 | 吃什么 | 2026 | 全员 | EAT @41 → bot.eat | 吃什么；吃啥；菜谱；eat；food；recipe；chishenme；csm；caipu；cp；zenmezuo；zmz |
| 65 | 群信息 | 2075 | 全员（公告/精华仅管理员；仅群聊） | GROUP_INFO @41 → bot.group_info | 群信息；本群信息；群资料；群主是谁；谁是群主；群人数；群公告；群精华；精华消息；本群多大了 |
| 66 | 好感度 | 2100 | 全员 | AFFINITY @41 → bot.affinity | 好感度；好感；好感查看；查询好感；查詢好感；親密度；affinity；haogandu；hgd；haoganchakan；hgck；chaxunhaogan；cxhg |
| 67 | Epic | 2129 | 全员 | EPIC @41 → bot.epic | epic；epic free；epic 免费；免费游戏；免費遊戲；遊戲免費；steam免費；游戏免费；steam免费；steam 免费 |
| 68 | 随机图 | 2149 | 全员 | RANDPIC @41 → bot.randpic | 随机图；来张图；隨機圖；來張圖；randpic；suijitu；sjt；laizhangtu；lzt |
| 69 | 提醒 | 2175 | 全员 | REMINDER @41 → bot.reminder | 提醒；reminder；叫我；记得叫；記得叫；定时提醒；tixingliebiao；txlb；wodetixing；wdtx；kankantixing；kktx；younaxietixing；ynxt |
| 70 | 笔记 | 2202 | 全员 | REMINDER @41（复用提醒路由）→ bot.reminder | 笔记；筆記；biji；note；笔记列表；bijiliebiao；bjlb |
| 71 | 收件箱 | 2232 | 全员 | DAILY_ASSIST @42 → bot.daily_assist | 收件箱；inbox；shoujianxiang |
| 72 | 语音 | 2256 | 全员（需 BOT_TTS_ENABLED） | TTS @41 → bot.tts | 语音；tts；yuyin；语音合成 |
| 73 | 帮助 | 2280 | 全员（可见范围按角色） | ADMIN 前缀族内 help 分支 | 帮助；help；菜单 |
| 74 | 聊天 | 2305 | 全员 | CHAT @50 → bot.chat（兜底，不可显式调用） | 聊天；chat；闲聊 |
| 75 | 戳一戳 | 2328 | 全员 | on_notice（非 RouteKind） | 戳一戳；poke |
| 76 | 表情收库 | 2350 | 全员（被动机制） | meme_absorb（无命令） | 表情收库；表情库；biaoqingku；bqk |
| 77 | 自然语言 | 2372 | 全员 | NATURAL_COMMAND @45 → bot.natural_command | 自然语言；自然语言命令 |

## A.3 内部/配置型登记（无用户直呼命令，防止把 API/内部语义当命令）

- 内部路由能力 5 条（capability_registry note 列为权威）：`bot.stocks` / `bot.fx` / `bot.commodities` / `bot.bond` / `bot.northbound`——均有帮助页（见 A.2），但触发词在 capabilities/stocks.py、fx.py、market.py 内，不在 _HELP_ENTRIES aliases 之外另设。
- 路由 IGNORE @999 兜底 + 未知命令形态 60s/会话引导（echo.py build_ignore_guide_result）。
- 接口清单 reserved 2 条：capability.game_live、capability.gscore（base_router L615/L621，未实现，无命令）。
- 控制面 REST（loopback 8742）与 `/bot workspace` / `/bot action`：**不存在聊天命令**（COMMANDS.md L147-149 明示），不得写入命令目录。

## A.4 既有两字母/三字母缩写占用表（九形态冲突检查的底册）

在用拼音缩写：dg dgms hq gs dp gj tq ctq tbq kb csm cp sjt lzt txlb wdtx kktx ynxt bjlb hgd hgck cxhg mb wjbk lssd jrls yg pp mp tl sg qg lssg bqk bqb gupiao(全拼)。
英文词在用：music song meme steal weather market stocks stock gold silver oil commodity wiki moegirl news today download alias inbox tts chat poke help search route routes parse audit receipt recent why queue context dialogue config readiness roles persona runtime model llm feature group mail email tg telegram provider providers memory identity quirk decision ignore reply status history resume pause note food recipe subscribe inbox archive remind(er)。

**永不启用（AGENTS.md 台账 #27 裁定）**：`zb` `bz` `sz` `sm`——任何新形态别名与之撞车即标红禁用。
