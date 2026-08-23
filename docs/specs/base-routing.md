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
| 18 | subscribe | bot.subscribe | 订阅命令（中文/英文） |
| 19 | alias | bot.alias | 昵称命令（/岸宝… /守岸人…） |
| 20 | admin | bot.status | /bot 或 bot 前缀 |
| 21 | auto_send | bot.auto_send | “报存 给 A 发…” |
| 43 | music_mode | bot.music_mode | /点歌模式 |
| 44 | music | bot.music | /点歌 <歌名> |
| 44 | today_history | bot.today_history | /历史上的今天 |
| 44 | wiki | bot.wiki | /wiki、/维基百科 等 |
| 44 | epic | bot.epic | /epic、/epicfree 等 |
| 44 | weather | bot.weather | /天气、/查天气 |
| 46 | content | bot.content | 文本含 http(s) 链接 |
| 50 | chat | bot.chat | 其余自然语言 |
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
