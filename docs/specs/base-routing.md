# 基层统一路由与输出闭环（Base Routing & Output Loop）

## 1. 目标

所有入站消息先进入**基层（Base Layer）**，由确定性算法判断走哪条路：

- 确定性插件：天气 / 链接解析 / 点歌 / 维基 / Epic / 历史上的今天 / 订阅 /
  管理员命令 / 昵称别名 / 自动发送；
- 人格大模型：普通自然语言聊天（带人格、世界观、价值观、方法论回复）。

子能力执行完把 `CapabilityResult` 交回基层，基层统一做安全审查、渲染
（文本 / 卡片 / 合并转发）后交给 NapCat 发到 QQ。**任何子能力都不直接发消息。**

## 2. 基层路由算法

实现：`plugins/bot_unified_runtime/runtime/base_router.py`
入口：`classify_message_route(text, *, config, alias_resolver) -> RouteDecision`

优先级顺序（与 NoneBot matcher 注册顺序一致，数字小者先）：

| 优先级 | 路由 kind | capability_id | 判断依据 |
| --- | --- | --- | --- |
| 10 | alias | bot.alias | 昵称命令（/岸宝… /守岸人…，斜杠可省略） |
| 11 | admin | bot.status | /bot 或 bot 前缀（管理员命令） |
| 12 | subscribe | bot.subscribe | 订阅命令（中文/英文） |
| 13 | auto_send | bot.auto_send | “报存 给 A 发…” |
| 20 | meme | bot.meme | /表情 列表、/表情 <key> <文字>、/meme help |
| 40 | music_mode | bot.music_mode | /点歌模式 |
| 41 | music | bot.music | /点歌 <歌名> |
| 41 | today_history | bot.today_history | /历史上的今天 |
| 41 | wiki | bot.wiki | /wiki、/维基百科 等 |
| 41 | epic | bot.epic | /epic、/epicfree 等 |
| 41 | weather | bot.weather | /天气、/查天气 |
| 45 | natural_command | bot.natural_command | “帮我查天气”“来首歌”等自然语言意图（归一化后执行） |
| 46 | content | bot.content | 文本含 http(s) 链接 |
| 50 | chat | bot.chat | 其余自然语言（人格大模型） |
| 999 | ignore | bot.ignore | 空消息 / 命令被禁用 |

特性：
- **纯确定性、可解释**：每次判定带 `reason` 和 `audit_tags`，可审计；
- 功能开关关闭时，对应命令落到 `ignore`，不会被误送到人格大模型；
- 判定的唯一事实来源就是这张表，NoneBot matcher 的 rule 也调用它，
  避免“matcher 一套判断、文档一套判断”漂移。

## 3. 子能力返回到基层的执行闭环

```
IncomingMessage
   -> Base Router classify_message_route()      # 基层判断走哪条路
   -> RuntimePipeline.handle(message, capability)
        -> policy（角色/限流/安静时段/回复预算）
        -> capability(...)                        # 子函数执行（查询/解析/点歌/LLM）
        -> CapabilityResult                        # 子函数把结果交回基层
        -> review（安全/隐私/人格漂移审查）
        -> render（文本/卡片/合并转发）
        -> SendRequest -> SendQueue -> NapCat -> QQ
```

- 管理员可用 `/bot route <文本>` 查看基层对任意文本的判定（路由/能力/优先级/理由）。
- 所有路由最终都回到同一个 `RuntimePipeline`，因此审计、回执、去重、
  限频和日志是统一收口的。

## 4. 人格文件来源（权威顺序）

- `BOT_PERSONA_FILES` 指向用户提供并维护的三份档案：
  `守岸人档案.md`、`守岸人人格档案.md`、`守岸人人格设定.md`；
- `BOT_KNOWLEDGE_FILES` 为可检索知识（含 `鸣潮库街区百科v2.md` 等），
  由基层的知识检索注入人格大模型的对话路由。

## 5. 昵称/点名与群聊接话

- **@ 点名**：OneBot 消息段里的 `CQ:at` 直接命中本机器人 id 即视为点名。
- **名字/昵称点名**：`runtime/mentions.py::detect_name_mention` 识别
  “岸宝，…”“守岸人 今天天气怎么样”“呼叫守岸人”以及句中
  “大家好，守岸人，在吗”等写法；规则保守，避免“岸宝贝”“守岸人设”
  这类包含关系误触发。人格昵称来自 `BOT_PERSONA_NICKNAMES`。
- **群聊门禁**（`policy/gate.py`）：群消息默认只有
  “命令前缀 / 昵称命令 / @点名 / 名字点名”才回复；
  `BOT_GROUP_CHAT_AUTO_REPLY_ENABLED=true` 时按
  `BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY` 对未点名消息做**确定性哈希
  抽签**回复（同一条消息结果永远一致，可审计，默认关闭）。
- 私聊不设门禁，直接进入基层路由。

## 6. 自然语言命令层（优先级 45）

`runtime/natural_language.py::detect_natural_command` 用确定性规则把
自然说法归一化成标准命令后仍走对应子能力，不经大模型：

- “帮我查一下杭州天气 / 杭州天气怎么样” -> `天气 杭州`
- “来首晴天 / 放首歌 晴天 / 帮我放一首周杰伦的歌” -> `点歌 …`
- “帮我查维基 鸣潮” -> `wiki 鸣潮`
- “今天有什么免费游戏” -> `epic`
- “今天历史上发生了什么” -> `历史上的今天`

规则刻意保守，普通闲聊（“今天天气不错”“播放量好高”）不命中；
含 http 链接时基层让位给链接解析（优先级 46 在前，此处 45 主动跳过）。

## 7. 接口清单（INTERFACE_MANIFEST）

所有可能接口提前登记，`/bot routes` 可审计，`base_router.py::
build_interface_manifest()` 为唯一事实来源：

| interface_id | 含义 | 状态 |
| --- | --- | --- |
| transport.onebot | NapCat / OneBot V11 传输 | active |
| core.gscore | GsCore / 早柚核心桥（ws://HOST:PORT/BOT_ID?token=TOKEN） | active |
| parser.content | 平台链接解析插件组 | active |
| persona.chat | 人格大模型对话（人格档案+向量知识库） | active |
| capability.weather / music / wiki / epic / today_history | 确定性能力 | active |
| capability.subscribe | 订阅博主/直播推送 | active |
| capability.meme | 表情包生成（本地 meme-generator-rs） | active |
| capability.auto_send | 自动发送/定时任务 | active |
| capability.emotion | 情绪状态注入（上下文能力，不占文本路由） | active |
| capability.game_live | 游戏直播状态 | reserved |
| capability.meme_absorb | 吸收群友表情入库 | reserved |
| capability.gscore | GsCore 上行命令进入基层路由 | reserved |
