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
