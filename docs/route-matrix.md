# 全问法路由矩阵（Route Matrix）

> 所有入站文本先进入基层路由器 `plugins/bot_unified_runtime/runtime/base_router.py`，
> 判定后由 NoneBot 匹配器把消息交给对应处理程序，子能力执行完把
> `CapabilityResult` 交回 `RuntimePipeline`（基层）统一审查/渲染，最后经
> NapCat(OneBot V11) 发回 QQ。**任何子能力都不直接发消息。**

离线演示：`scripts/dev.ps1 route-demo`；真实接口烟测：`scripts/dev.ps1 route-smoke`。

## 1. 从问法到回复的完整链路

```
QQ/NapCat 消息
  -> base_router.classify_message_route(text)      # 确定性路由（kind/优先级/归一化命令/理由）
  -> NoneBot matcher（rule 复用同一路由表）          # alias/admin/subscribe/.../natural/chat
  -> 处理程序 handler（如 _handle_natural / _handle_alias / _handle_meme）
  -> 对应能力 capability（天气/点歌/维基/Epic/历史/订阅/表情包/链接解析/人格 LLM）
  -> CapabilityResult 交回 RuntimePipeline          # 安全审查 -> 渲染（文本/卡片/合并转发）
  -> SendQueue -> NapCat -> QQ
```

群聊门禁（`policy/gate.py`）在进入能力前执行：私聊放行；群聊只有
**命令 / 昵称命令 / @点名 / 写昵称点名**才放行，其余为
`passive_group_message` 静默观察；`BOT_GROUP_CHAT_AUTO_REPLY_ENABLED=true`
时按概率做确定性哈希抽签接话，且主动搭话受好感档门控
（`bot_proactive_affinity_gate_enabled`，默认开：仅对好感档 ≥ 亲近的用户主动接话）。

## 2. 问法矩阵（设计文档；以 plugins/bot_unified_runtime 路由实现与 tests/ 下路由回归为准）

| 问法示例 | 路由 kind | 优先级 | 进入的匹配器/处理程序 | 归一化命令 / 实际能力 |
| --- | --- | --- | --- | --- |
| `/岸宝帮助`、`/岸宝天气 杭州`、`守岸人点歌 晴天`（斜杠可省略） | alias | 10 | `on_message` alias -> `_handle_alias` | bot.alias：昵称解析 -> help/weather/music/… |
| `/bot status`、`/bot routes`、`/bot subscribe add …` | admin | 11 | `on_command("bot")` -> `_handle_status` 内部分派 | bot.status：status/routes/subscribe/… ；**逐条权限以代码为准**：`status`/`parse`/`reply`/`群文件`/`cookie`/`logs`/`search`/`group` 等为管理员专属（能力入口 `actor_roles` 判定，未传即拒绝）；`download` **对普通成员开放**（仅 `/bot download` 形式；裸「下载 …」当前不走路由，落人格聊天），安全边界由 `sources/downloader.check_download_url` 承担（只放行 http/https，拒绝内网/环回/保留地址与 `localhost`/云元数据主机，含 DNS 解析后的私网 IP 与十进制/十六进制 IP 形态） |
| `/订阅 状态`、`/订阅 添加 <链接>`、英文 `subscribe` | subscribe | 12 | `_is_standalone_subscribe_event` -> `_handle_standalone_subscribe` | bot.subscribe |
| `报存 给 A 发邮件，主题…` | auto_send | 13 | `_is_auto_send_plain_text` | bot.auto_send |
| `/表情 列表`、`/meme petpet 可爱`、`meme generate`、`表情製作/表情產生 族`、`/表情帮助` +拼音触发（见 catalog） | meme | 20 | `_is_meme_event` -> `_handle_meme` | bot.meme -> 本地 meme-generator-rs |
| `/偷表情 关键词`、`偷图/偷圖 关键词`、`随机表情/表情抽签`、`表情库统计`、英文 `steal`/`steal meme`/`meme random`/`meme stats` +拼音触发（见 catalog） | meme_library | 22 | `_is_meme_library_event` | bot.meme_library（群图收库 NSFW 降权；心情低时吵闹梗软重抽） |
| `/点歌模式 卡片`、`點歌模式 卡片`、`music mode link`、`song mode` +拼音触发（见 catalog） | music_mode | 40 | `_is_music_mode_event` | bot.music_mode |
| `/点歌 晴天`、`点唱/點唱 晴天`、英文 `music`/`song <歌名>` +拼音触发（见 catalog） | music | 41 | `_is_music_event` -> `_handle_music` | bot.music（网易云/酷我/酷狗/QQ/Apple/Spotify 依次） |
| `/历史上的今天`、`歷史上的今天`、英文 `today in history`（可裸发）、`/today`/`/history`（必须带斜杠） +拼音触发（见 catalog） | today_history | 41 | `_is_today_history_event` | bot.today_history |
| `/wiki 鸣潮`、`/WIKIPEDIA Python`、`维基/維基百科 鸣潮` +拼音触发（见 catalog） | wiki | 41 | `_is_wiki_event` | bot.wiki |
| `/epic`、`/Epic Free`、`/Epic 免费`、`免费游戏`、英文 `steamfree`/`steam free` | epic | 41 | `_is_epic_event` | bot.epic |
| `/天气 杭州`、`/查天气 上海`、`天气预报/天氣預報 <城市>`、英文 `weather <city>` +拼音触发（见 catalog） | weather | 41 | `_is_weather_event` | bot.weather（中国气象局 NMC 主通道 2 次重试+预警支路+Open-Meteo 兜底） |
| `行情`、`股指/大盘/股市`、`B股行情`、`莫斯科股指`、英文 `market`/`markets`/`stock market` +拼音触发（见 catalog） | market | 41 | `_is_market_event` -> `_handle_market` | bot.market（东财 push2 17 指数 + MOEX ISS 备选源；市场词过滤） |
| `快报`、`今日快报 科技`、`早报/晚报/今日热点/科技新闻/AI新闻/AI快报/财经新闻/财经快报/国际新闻`、繁體同族 10 词（`快報/早報/晚報/今日熱點/科技新聞/AI新聞/AI快報/財經新聞/財經快報/國際新聞`）、英文 `news`/`tech news`/`ai news` +拼音触发（见 catalog） | news | 41 | `_is_news_event` | bot.news（V2EX 真 Atom + IT之家/少数派/华尔街见闻/BBC中文；自动过滤营销条目，默认 20 条） |
| `八字`、`塔罗 三张`、`占卜`、`排盘/四柱/金钱卦/摇卦`、英文 `bazi`/`tarot`/`iching`/`hexagram`/`divination` +拼音触发（见 catalog） | divination | 41 | `_is_divination_event` | bot.divination（Meeus 节气八字含藏干权重/塔罗 78/金钱卦） |
| `随机图`、`来张图`、繁體 `隨機圖/來張圖`、英文 `randpic` +拼音触发（见 catalog） | randpic | 41 | `_is_randpic_event` | bot.randpic（只读 BOT_RANDPIC_DIRS 自定义文件夹，绝不自建目录） |
| `12点提醒我写作业`、`提醒列表`、`取消提醒 <id前缀>`、英文 `reminder`/`reminders`/`my reminders`/`reminder list`/`list reminders`（仅列表查询面） +拼音触发（见 catalog） | reminder | 41 | `_is_reminder_event` | bot.reminder（自然语言时间点→会话待办→每分钟投递；进阶轨 LLM 抽取默认关） |
| `好感度`、`好感度 算法`、`好感/亲密度/親密度`、英文 `affinity` +拼音触发（见 catalog） | affinity | 41 | `_is_affinity_event` | bot.affinity（v5 多因素线性步长：-100~+100、基准 10=档0友善、8 档温和态度连续过渡，算法说明定性、不展示固定加减数值；双向卡/群榜/算法卡） |
| `吃什么`、`中午吃什么啊`、`菜谱/怎么做 <菜名>`、英文 `eat`/`food`/`recipe <菜名>` +拼音触发（见 catalog） | eat | 41 | `_is_eat_event` | bot.eat（60 道本地库+LLM 约束推荐+Mica 卡） |
| `汇率`、`美元兑人民币`、`100日元换多少人民币`、繁體 `匯率/兌換/換匯`、英文 `fx`/`forex`/`exchange rate` +拼音触发（见 catalog） | fx | 41 | `fx_match` | bot.fx（多语言触发：汇率/兑换/换汇/匯率等；与 stocks 重叠时 fx 优先 41<42） |
| `英伟达股价`、`公司别名`、`股价/股價/個股`、英文 `stock`/`stocks`（裸词=九巨头面板）；`市值` 需与公司别名共现触发（如 `英伟达市值`，裸词不触发） +拼音触发（见 catalog） | stocks | 42 | `stocks_match` | bot.stocks（个股行情兜底：短文本+无链接+命中公司别名或股价/市值词） |
| `/萌娘 鸣潮`、`萌娘百科/萌百 <条目>`、英文 `moegirl` +拼音触发（见 catalog） | moegirl | 41 | `_is_moegirl_event` | bot.moegirl（萌娘百科查询） |
| 直接问「XX是谁？」等二次元实体问句 | moegirl_question | 46 | `_is_moegirl_question_event` | bot.moegirl（剥出实体 2-30 字自动查询；未命中降级人格聊天；2026-09-13 起 44→46 让路 NL 层，天气/wiki 形问句由域词守卫拒绝） |
| `杭州天气怎么样` | natural_command | 45 | `_is_natural_event` -> `_handle_natural` | bot.natural_command：归一化 `天气 杭州` -> bot.weather（「帮我查一下杭州天气」「帮我查天气 杭州」自 2026-09-13 moegirl_question 让路后同落本层归一化 weather） |
| `来首晴天` / `放首歌 晴天` / `帮我放一首周杰伦的歌` | natural_command | 45 | 同上 | 归一化 `点歌 …` -> bot.music |
| `帮我查维基 鸣潮` | natural_command | 45 | 同上 | 归一化 `wiki 鸣潮` -> bot.wiki（2026-09-13 moegirl_question 让路后真实落点与本行一致） |
| `今天有什么免费游戏` | natural_command | 45 | 同上 | 归一化 `epic` -> bot.epic |
| `今天历史上发生了什么` | natural_command | 45 | 同上 | 归一化 `历史上的今天` -> bot.today_history |
| `看这个 https://www.bilibili.com/video/BV1xx411c7mD` | content | 46 | `_is_content_parse_event` -> `_handle_content` | bot.content（平台解析+卡片渲染） |
| `今天有点累，陪我说说话。`、`漂泊者是谁` | chat | 50 | `_is_plain_chat_event` -> `_handle_chat` | bot.chat（人格档案+向量知识库+LLM） |
| `今天天气不错`、`播放量好高` | chat | 50 | 同上（**故意不劫持闲聊**） | bot.chat |
| 空消息 | ignore | 999 | 无 | bot.ignore（无回复） |

## 3. 表情包命令（已接入两个入口）

- 本项目自研：`/表情 列表`、`/表情 <key> <文字>`（`｜`分隔多段）、`/表情帮助`，
  走基层统一流水线（审查/日志/发送队列）。
- 已安装 NoneBot 官方插件 `nonebot_plugin_memes_api`（MIT，v0.5.1），
  后端同为本地 `meme-generator-rs`（`MEME_GENERATOR_BASE_URL=http://127.0.0.1:2233`），
  支持 `摸 @某人`、`表情列表`、`随机表情` 等 Alconna 关键词玩法。
- 后端 Windows 版已部署于 `C:\Software\MemeGenerator\meme.exe`，
  服务端口 2233。数据目录（config.toml/fonts/images 素材）已迁入
  `ChatBot_Runtime\data\meme_generator`（2026-09-11 自 `%USERPROFILE%\.meme_generator`
  迁入，原路径留有 junction 兜底）。meme.exe 0.2.3 经 `MEME_HOME` 环境变量定位数据
  目录，统一用 `ChatBot_Runtime\scripts\start_meme_server.ps1` 启动（进程内设置
  `MEME_HOME`）；直启 `meme.exe run` 会回退主目录旧路径（经 junction 仍落到同一目录）。


## 4. 现实问题 vs 世界观问题的智能判定 v2（不斩断联网权限）

判定入口：`runtime/question_intent.py::classify_question_intent`，按意图分层：

1. 现实信号（公司/官方/所在地/演唱会/音乐会/漫展/价格/汇率/新闻/现实…）→ 联网，**永不因领域词被切断**；
2. 时效信号（今天/最新/更新/版本/什么时候/开服/复刻…）→ 联网；
3. 实体问句“X是什么/是谁”：
   - X 不是领域词（习近平是谁/库洛游戏是什么公司）→ 联网做百科检索（自动补“百科”）；
   - X 是领域词（鸣潮是什么/艾弥斯是谁）→ 本地知识库优先，**携带联网回退**；
4. 领域词 + 知识意图 → 知识库优先 + 联网回退；
5. 本地知识库 `answerable=false` 或置信度 < 0.35 时，即便领域词问题也回退联网；
6. 寒暄/天气小聊/一般知识 → neutral，不联网、不拖慢。

因此“鸣潮今天更新了什么”“库洛所在地”“鸣潮演唱会”都会联网；“鸣潮里的今州是什么”先走知识库、知识库答不了才联网。每次判定带 reason，审计里记 `web_decision:` 与 `web_search_hits:`；**仅管理员可见回复末尾的“🔎 已联网检索 N 条”调试标记，普通用户看不到**。管理员可用 `/bot search <问题>` 直接验证联网是否可用。检索源：DuckDuckGo→Bing 链式，走 `BOT_DOWNLOAD_PROXY`（127.0.0.1:7890）。

## 5. 解析结果分区展示

链接解析正文按固定区块输出，肉眼可辨：
【标题】/【作者】/【数据】/【简介】/【视频参数】（分辨率·时长·动态范围）/
【音频参数】（音乐=码率·格式·声道·音质；视频=仅音质 Hi-Res 标注）/【链接】。


## 6. 点歌输出组合（管理员可调）

`/点歌模式 <组合>` 或自然语言“以后点歌只发卡片和语音”；部件：
card=平台音乐卡片（无卡信息用封面）、voice=语音、file=音频文件、link=链接。
组合示例：`只发卡片`、`只发链接`、`只发音频`、`卡片和语音`、`卡片+链接`、
`卡片和文件`、`music mode card+link`、`點歌模式 卡片和語音`。
默认 `card+voice+link`（兼容旧“card”）。

## 7. 下载与缓存策略（不挤占硬盘）

- 下载走 yt-dlp：cookie（Netscape）+ 代理 `BOT_DOWNLOAD_PROXY`（外网走 7890）+ 单线程重试 1 次 + 高度默认不限（`BOT_DOWNLOAD_MAX_HEIGHT=0`）+ 单文件默认 1GB 上限（`BOT_DOWNLOAD_MAX_BYTES`）；
- 目录配额 LRU 最旧先删：下载 2GB/7 天、点歌 512MB、卡片 256MB、表情 256MB，每次落盘即清理；
- 配置：`BOT_DOWNLOAD_CACHE_MAX_BYTES/MAX_AGE_DAYS`、`BOT_MUSIC_CACHE_MAX_BYTES`、`BOT_CARD_CACHE_MAX_BYTES`、`BOT_MEME_CACHE_MAX_BYTES`；
- 运行入口：`nb run --reload`，代码改动自动热重载，无需手动重启终端。

## 8. 联网检索质量增强（v3，本轮再放宽）

- 检索条数不设硬限制（默认 20 条，`BOT_WEB_SEARCH_MAX_RESULTS=0` 表示不限制，内部安全上限 24 条），并自动补“百科 / 简介 成立 作品 发展历程 / 是什么 介绍 / 最新 / 更新 内容”等多组查询合并去重；
- 过滤字典/拼音/笔顺类垃圾结果（按域名与标题特征），只保留与查询关键词相关的来源；
- 自动打开最相关结果页面抽取正文（≤900 字）注入回复，让模型拿到真实事实而非只有标题摘要；
- 提示词强制：现实问题必须基于检索结果先给事实、结果没有就明说“未检索到”，禁止用世界观或想象替代；
- 管理员 `/bot search` 同样最多 6 条；回复末尾“🔎 已联网检索”仅管理员可见，0 条时也会提示“源不可达或无相关结果”。

## 9. 下载参数（本轮）

- 超时 600 秒；单文件上限 1GB；分辨率不设上限（最高画质，含 8K/Hi-Res）；
- 画质阶梯自动降级：最高 → 2160 → 1440 → 1080 → 720，超 1GB 自动降级；
- 网易云优先 999000（Hi-Res）再退 320kbps；缓存只清理配置目录内文件（LRU 最旧先删 + 保鲜期）。


- 提示词强制：先回答核心疑问→百科事实→系统观+哲学化词汇（因果/时间性/结构/边界/涌现/存在/秩序/回声/意义），事实不得牺牲准确性；检索不足必须明说“检索结果未覆盖该问题”并复述问题，禁止用世界观或想象替代。

## 10. 群聊表情包机器人（bot.meme_library）

- 监听：on_message priority=10 block=False，群图异步下载（httpx）、MD5 去重、≤5MB、SQLite 元数据；
- 发送：`偷表情 [关键词|情绪标签|私聊]`（权重随机）、`表情库统计`；
- 权重：守岸人×8 → 鸣潮/战双/库洛×4 → ACG×1.5 → 普通×1；非表情×0.25；NSFW≥0.2 降权、≥0.8 永不发送；
- 可选 VLM 打标（BOT_MEME_LIBRARY_VLM_*，TAG_PROMPT 返回 is_meme/description/emotion/scene/persona/nsfw）；
- 工程：冷却 20s、群黑白名单、LRU 30 天/20000 张、异步下载绝不阻塞事件循环。
