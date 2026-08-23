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
时按概率做确定性哈希抽签接话。

## 2. 问法矩阵（权威实现见 tests/test_route_matrix.py）

| 问法示例 | 路由 kind | 优先级 | 进入的匹配器/处理程序 | 归一化命令 / 实际能力 |
| --- | --- | --- | --- | --- |
| `/岸宝帮助`、`/岸宝天气 杭州`、`守岸人点歌 晴天`（斜杠可省略） | alias | 10 | `on_message` alias -> `_handle_alias` | 昵称解析 -> help/weather/music/… |
| `/bot status`、`/bot routes`、`/bot subscribe add …` | admin | 11 | `on_command("bot")` -> `_handle_status` 内部分派 | status/routes/subscribe/download/… |
| `/订阅 状态`、`/订阅 添加 <链接>` | subscribe | 12 | `_is_standalone_subscribe_event` -> `_handle_standalone_subscribe` | bot.subscribe |
| `报存 给 A 发邮件，主题…` | auto_send | 13 | `_is_auto_send_plain_text` | bot.auto_send |
| `/表情 列表`、`/meme petpet 可爱`、`/表情帮助` | meme | 20 | `_is_meme_event` -> `_handle_meme` | bot.meme -> 本地 meme-generator-rs |
| `/点歌模式 卡片` | music_mode | 40 | `_is_music_mode_event` | bot.music_mode |
| `/点歌 晴天` | music | 41 | `_is_music_event` -> `_handle_music` | bot.music（网易云/酷我/酷狗/QQ/Apple/Spotify 依次） |
| `/历史上的今天` | today_history | 41 | `_is_today_history_event` | bot.today_history |
| `/wiki 鸣潮`、`/WIKIPEDIA Python` | wiki | 41 | `_is_wiki_event` | bot.wiki |
| `/epic`、`/Epic Free`、`/Epic 免费` | epic | 41 | `_is_epic_event` | bot.epic |
| `/天气 杭州`、`/查天气 上海` | weather | 41 | `_is_weather_event` | bot.weather（中国气象局 NMC） |
| `帮我查一下杭州天气` / `杭州天气怎么样` / `帮我查天气 杭州` | natural_command | 45 | `_is_natural_event` -> `_handle_natural` | 归一化 `天气 杭州` -> bot.weather |
| `来首晴天` / `放首歌 晴天` / `帮我放一首周杰伦的歌` | natural_command | 45 | 同上 | 归一化 `点歌 …` -> bot.music |
| `帮我查维基 鸣潮` | natural_command | 45 | 同上 | 归一化 `wiki 鸣潮` -> bot.wiki |
| `今天有什么免费游戏` | natural_command | 45 | 同上 | 归一化 `epic` -> bot.epic |
| `今天历史上发生了什么` | natural_command | 45 | 同上 | 归一化 `历史上的今天` -> bot.today_history |
| `看这个 https://www.bilibili.com/video/BV1xx411c7mD` | content | 46 | `_is_content_parse_event` -> `_handle_content` | bot.content（平台解析+卡片渲染） |
| `今天有点累，陪我说说话。`、`漂泊者是谁` | chat | 50 | `_is_plain_chat_event` -> `_handle_chat` | bot.chat（人格档案+向量知识库+LLM） |
| `今天天气不错`、`播放量好高` | chat | 50 | 同上（**故意不劫持闲聊**） | bot.chat |
| 空消息 | ignore | 999 | 无 | 无回复 |

## 3. 表情包命令（已接入两个入口）

- 本项目自研：`/表情 列表`、`/表情 <key> <文字>`（`｜`分隔多段）、`/表情帮助`，
  走基层统一流水线（审查/日志/发送队列）。
- 已安装 NoneBot 官方插件 `nonebot_plugin_memes_api`（MIT，v0.5.1），
  后端同为本地 `meme-generator-rs`（`MEME_GENERATOR_BASE_URL=http://127.0.0.1:2233`），
  支持 `摸 @某人`、`表情列表`、`随机表情` 等 Alconna 关键词玩法。
- 后端 Windows 版已部署于 `C:\Software\MemeGenerator\meme.exe`，
  服务端口 2233，素材已下载到 `%USERPROFILE%\.meme_generator\resources`。


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

- 下载走 yt-dlp：cookie（Netscape）+ 代理 `BOT_DOWNLOAD_PROXY`（外网走 7890）+ 单线程重试 1 次 + 高度上限 1080P + 单文件 200MB 上限；
- 目录配额 LRU 最旧先删：下载 2GB/7 天、点歌 512MB、卡片 256MB、表情 256MB，每次落盘即清理；
- 配置：`BOT_DOWNLOAD_CACHE_MAX_BYTES/MAX_AGE_DAYS`、`BOT_MUSIC_CACHE_MAX_BYTES`、`BOT_CARD_CACHE_MAX_BYTES`、`BOT_MEME_CACHE_MAX_BYTES`；
- 运行入口：`nb run --reload`，代码改动自动热重载，无需手动重启终端。

## 8. 联网检索质量增强（v3，本轮再放宽）

- 检索条数不设硬限制（默认 12 条，`BOT_WEB_SEARCH_MAX_RESULTS=0` 表示不限制，内部安全上限 24 条），并自动补“百科 / 简介 成立 作品 发展历程 / 是什么 介绍 / 最新 / 更新 内容”等多组查询合并去重；
- 过滤字典/拼音/笔顺类垃圾结果（按域名与标题特征），只保留与查询关键词相关的来源；
- 自动打开最相关结果页面抽取正文（≤900 字）注入回复，让模型拿到真实事实而非只有标题摘要；
- 提示词强制：现实问题必须基于检索结果先给事实、结果没有就明说“未检索到”，禁止用世界观或想象替代；
- 管理员 `/bot search` 同样最多 6 条；回复末尾“🔎 已联网检索”仅管理员可见，0 条时也会提示“源不可达或无相关结果”。

## 9. 下载参数（本轮）

- 超时 600 秒；单文件上限 1GB；分辨率不设上限（最高画质，含 8K/Hi-Res）；
- 画质阶梯自动降级：最高 → 2160 → 1440 → 1080 → 720，超 1GB 自动降级；
- 网易云优先 999000（Hi-Res）再退 320kbps；缓存只清理配置目录内文件（LRU 最旧先删 + 保鲜期）。


- 提示词强制：先回答核心疑问→百科事实→系统观+哲学化词汇（因果/时间性/结构/边界/涌现/存在/秩序/回声/意义），事实不得牺牲准确性；检索不足必须明说“检索结果未覆盖该问题”并复述问题，禁止用世界观或想象替代。