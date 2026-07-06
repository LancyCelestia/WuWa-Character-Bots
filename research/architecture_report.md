# NoneBot / AstrBot 架构研究报告

## 目的

本文把已下载的 NoneBot 插件源码和本地 AstrBot 插件经验转成统一角色机器人实现建议。当前目标不是立刻堆功能，而是决定哪些结构、算法、存储、解析流、输出控制和功能优先级值得复用。

## 证据基线

- 项目根目录：`C:\Users\LancyCelestia\WuWa-Character-Bots`。
- 当前 NoneBot 项目仍是新工程，`plugins/` 里没有自定义本地插件。
- 已下载 NoneBot wheel：70 个。
- 已解压 NoneBot 源码目录：70 个。
- 已浅克隆 GsCore/GScore 仓库：12 个。
- 官方 registry 快照：2026-07-06，共 903 条。
- 本地 AstrBot 参考：`C:\Users\LancyCelestia\.astrbot\data\plugins`。
- 用户重点 parser 插件：`C:\Users\LancyCelestia\.astrbot\data\plugins\astrbot_plugin_parser`。

完整路径和逐插件证据见：

- `research/downloaded_sources.md`
- `research/plugin_analysis_matrix.md`
- `research/astrbot_plugin_analysis_matrix.md`
- `research/astrbot_plugin_sources/inventory.md`

## 结论摘要

高置信方案是构建小而硬的统一运行时：

```text
IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult -> ReviewResult -> RenderedOutput -> SendRequest -> DeliveryReceipt -> AuditRecord
```

这条链路解决三个核心问题：

1. 不让每个插件直接抢着回复。
2. 不让 LLM 决定所有插件效果。
3. 不让发送成功、审计和隐私散落在各能力里。

能力插件只负责“做事并返回结构化结果”；统一运行时负责“能不能做、怎么说、怎么渲染、发到哪里、是否成功、如何审计”。

## 直接复用 / 适配复用 / 自研

| 能力 | 推荐来源 | 复用级别 | 原因 |
| --- | --- | --- | --- |
| 原始消息归档 | `nonebot-plugin-chatrecorder` | 直接依赖候选 | library 风格，ORM/uninfo 支持好，暴露查询 API。 |
| parser 架构 | `nonebot-plugin-parser`、AstrBot `astrbot_plugin_parser` | 适配模式 | parser registry、`ParseResult`、渲染、缓存、fallback 很强，但发送必须统一收口。 |
| 订阅调度 | `nonebot-bison`、本地 parser 订阅模块 | 适配模式 | 平台抽象、加权调度、批量抓取、队列/间隔/重试适合防刷屏。 |
| Bilibili 解析/订阅 | `bilichat`、`analysis_bilibili`、`bili_helper`、`bili_fav_watcher`、本地 parser | 适配或直接 adapter | Bilibili 是首个低风险媒体订阅目标。 |
| 群总结 | `summary_group` | 适配或直接依赖候选 | 显式命令、数量限制、冷却和管理员定时总结符合不扰民原则。 |
| 输出守卫 | `word_censor`、AstrBot `outputpro` | 适配模式 | 最终输出钩子必须能拦截 LLM 和非 LLM 输出。 |
| 人格/记忆 | `pxchat`、`shiro-personification`、`antipromptinjector`、`angel_memory` | 只适配模式 | 思路好，但直接复用容易变成大单体或失控群聊。 |
| 公共游戏/wiki 卡片 | `WWwiki`、`XutheringWavesUID`、`arktools`、`starrail-calendar` | 适配或直接 adapter | 公开、非 cookie 查询是早期安全能力。 |
| 账号面板/抽卡/绑定 | `gspanel`、`zzzpanel`、`gachalogs` 等 | 后续受控 | 涉及 cookie、authkey、QR、个人数据，必须先有密钥和撤销。 |
| 卡片渲染 | `cardimg`、`htmlrender`、`htmlkit`、本地 parser HTML/PIL 渲染 | 直接依赖候选或适配 | 渲染应作为统一服务，避免每个能力各做一套视觉。 |

## 统一架构

建议模块：

1. `runtime/intake`：把 NoneBot、OneBot V11、NapCat、Mail、Console 事件转成 `IncomingMessage`。
2. `runtime/policy`：权限、会话模式、冷却、限频、隐私、风险。
3. `runtime/router`：识别命令、提及、链接、订阅、总结、游戏查询、普通聊天。
4. `runtime/capabilities`：执行 parser、搜索、wiki、天气、总结、推荐、游戏查询等能力。
5. `character`：情绪、记忆、人设、语气、上下文组装。
6. `knowledge`：知识来源、导入、切块、检索、引用。
7. `output/review`：人格/OOC、安全、隐私、防刷屏、最终审查。
8. `rendering`：文本、卡片、图片、合并转发、fallback。
9. `sender`：队列、transport adapter、`DeliveryReceipt`。
10. `audit`：策略、能力、审查、渲染、发送、失败全链路记录。

## 核心接口

### CapabilityResult

每个 parser/search/game/weather/summary 工具返回：

- `kind`
- `title`
- `summary`
- `body`
- `url`
- `source`
- `confidence`
- `risk_level`
- `privacy_level`
- `private_recommended`
- `send_policy`

### BotDecision

运行时在生成前决定：

- `should_respond`
- `mode`
- `trigger`
- `capability_id`
- `target_scope`
- `max_messages`
- `send_policy`
- `persona_profile_id`
- `context_budget`

### PersonaProfile

人格不是一段 prompt，而是结构化数据：

- `identity`
- `role_boundaries`
- `worldview`
- `style_rules`
- `speech_examples`
- `forbidden_behaviors`
- `forbidden_phrases`
- `world_mapping`
- `refusal_templates`
- `ooc_thresholds`

## 人格优先与插件例外

普通自然语言回复必须依靠人设、性格、记忆、知识库和情绪感知来生成。也就是先确定“这个角色是谁、怎么说话、记得什么、能引用什么”，再生成回复。

但插件效果不能由 LLM 直接编：

- 链接解析：走 `SourceInput -> ParserRegistry -> FetchRequest -> ParsedMediaItem -> CardRenderModel`。
- 媒体卡片：走确定性模板和渲染器。
- 游戏/wiki 卡片：走来源数据和模板。
- 订阅推送：走 watcher、cursor、dedupe、digest、SendRequest。
- 音乐平台：优先 metadata 和官方链接，不让 LLM 猜资源。

LLM 最多生成安全、可关闭的人格化短说明，不能替代 parser/source/renderer。

## 本地 parser 插件迁移结论

`astrbot_plugin_parser` 的好设计：

- `BaseParser` 自动注册。
- `@handle(keyword, regex)` 关键词/正则匹配。
- keyword 最长优先。
- `ParseResult` 统一承载作者、正文、媒体、评论、统计、转发、音乐。
- link-level 与 resource-level 防抖。
- 订阅有 `recent_ids`、filters、push mode、jitter、task gap、跨平台去重。
- 渲染有 HTML/Playwright、PIL、文本 fallback。

迁移时不能照搬的点：

- `event.send`、`context.send_message` 不能出现在 capability、parser、subscription watcher 中。
- cookie/QR 登录必须进入 credential subsystem，只传 `credential_ref` 或 `headers_ref`。
- Generic screenshot fallback 必须有 SSRF、robots、域名、超时、大小和隐私策略。
- 多 bot emoji 仲裁是 OneBot/AstrBot 特化能力，只能作为 adapter 可选策略，不进入核心 runtime。

## 防打扰规则

- 群聊默认观察。
- 群里只有提及、命令、管理员订阅、安全告警或明显有帮助的问题才回复。
- 群主动消息默认摘要，不频繁单条推送。
- 私聊主动提醒必须 opt-in，支持暂停、稍后、关闭。
- 不公开给用户贴情绪标签。
- 同人、账号数据、个性化推荐默认私聊。
- 定时/订阅发送必须有队列、间隔、重试上限、去重。

## 优先级

### P0: 通信基础

- LLM provider adapter。
- 上下文记录和短期会话记忆。
- 统一命令和权限。
- 群/私聊策略门。
- 人格契约和 OOC checker。
- 输出安全审查和发送队列。
- 显式提及/私聊基础聊天。

### P1: 实用低噪声工具

- Bilibili、常见视频/音乐/wiki 链接 parser MVP。
- 手动搜索、ACG/wiki/游戏查询命令。
- 显式群总结。
- 天气/灾害提醒。
- 公共鸣潮和其他游戏 wiki/cards。
- 创作者/平台更新订阅摘要。

### P2: 个性化和推荐

- 带同意和可见控制的偏好记忆。
- ACG/news/同人/音乐推荐 hub。
- 私聊提醒和轻量 check-in。
- 群知识库和定期群报告。
- 私聊或管理员启用的网页编码辅助。

### P3: 高风险/高维护

- QQ 空间发帖、点赞、评论、转发。
- cookie/QR/账号面板。
- 大规模同人抓取、重托管、表情包学习。
- 群里常驻自动发帖。
- 群内完整 coding agent。

## 第一实现切片

第一版插件应是统一 runtime shell，不是巨型功能插件：

1. 运行时契约模型。
2. 策略门。
3. 审计日志。
4. 输出收口。
5. 一个 LLM adapter。
6. 一个低风险 parser。
7. 一个总结命令。
8. 一个公共游戏/wiki 或天气命令。
9. 一个渲染路径和一个发送路径。

这条切片能验证 intake、policy、capability、persona、review、render、send、audit 是否真的闭环。

## 已解决和推迟的问题

- 首个人格可以先用一个明确的鸣潮角色或中性助手，但必须写成 `PersonaProfile`。
- GsCore/GScore 来源选择见 `research/implementation_design_supplement.md`。
- Milestone 1 以 OneBot V11 / NapCat QQ 为主要目标，同时保留 Console/Mail adapter 边界。
- 账号绑定、cookie、QR、authkey、抽卡历史、个人面板全部后置。
