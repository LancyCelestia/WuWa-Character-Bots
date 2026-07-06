# NoneBot 官方 Registry 相关性扫描

## 快照

- 来源：`https://registry.nonebot.dev/plugins.json`。
- 快照文件：`research/nonebot_plugin_sources/official_registry_plugins_2026-07-06.json`。
- 快照条目数：`903`。
- 第一批下载 NoneBot wheel：`53`。
- 第二批下载 NoneBot wheel：`17`。
- 本次研究下载的 NoneBot 源码证据合计：`70`。

官方插件商店很大，所以筛选按需求相关性进行，而不是下载全部 registry。第二批补充了第一批没有覆盖但直接支持生活工具、治理、Bilibili、群 AI、ACG 资源或轻互动设计的插件。

## 第二批候选

| 插件 | 纳入原因 | 早期复用判断 | 风险/优先级 |
| --- | --- | --- | --- |
| `nonebot_plugin_access_control` | 成熟权限和调用限频，支持 session、ORM、APScheduler、Alconna。 | P0 治理强参考，API 验证后可能直接依赖。 | 低/中，权限正确性很关键。 |
| `nonebot_plugin_reminder` | 持久化定时提醒，APScheduler/localstore/SAA 风格。 | 借鉴提醒 UX 和持久化，统一私聊优先调度。 | P1，隐私和提醒疲劳。 |
| `nonebot_plugin_clock` | 闹钟/日常提醒命令和调度。 | 私人提醒命令语法参考。 | P1，OneBot 偏重且公开使用会吵。 |
| `nonebot_plugin_class_schedule` | 课程表、节假日、提醒、文本/图片 fallback。 | 生活助手强参考。 | P1/P2，个人日程隐私。 |
| `nonebot_plugin_ai_timetable` | 小爱课程表导入/查询。 | 课程表导入参考。 | P2，账号/数据敏感。 |
| `nonebot_plugin_analysis_bilibili` | Bilibili 视频/番剧/直播/文章/动态解析。 | 与 Bilichat/BiliHelper 比较，作为覆盖参考。 | P1，直发和 API/rate 风险。 |
| `nonebot_plugin_bili_helper` | Bilibili 分享提取、评论、cookie、HTML 模板。 | Bilibili parser/render 参考，输出必须集中。 | P1/P2，cookie 和 OneBot 风险。 |
| `nonebot_plugin_bili_fav_watcher` | Bilibili 收藏夹 watcher。 | 收藏夹订阅参考；Bison 调度更强。 | P1/P2，认证/限频风险。 |
| `nonebot_plugin_autopush` | 简单定时推送。 | 仅参考；统一队列/digest 应替代直推。 | P2，刷屏风险。 |
| `nonebot_plugin_ai_groupmate` | 虚拟群友、群记忆、媒体存储、latest-only worker。 | 群参与节流和队列折叠强参考。 | P1/P2，隐私/OOC/刷屏。 |
| `nonebot_plugin_aiochatllm` | LLM 聊天包装。 | provider/命令参考，仍优先统一 LLM adapter。 | P0/P1，API key 风险。 |
| `nonebot_plugin_anywhere_llm` | 泛用 LLM anywhere/chat 插件。 | 触发表面和存储参考。 | P1，群聊过度参与风险。 |
| `nonebot_plugin_animeres` | 动漫资源搜索。 | 内容政策确认后作为推荐/搜索来源。 | P2/P3，版权和内容风险。 |
| `nonebot_plugin_anime_trace` | 动漫/Gal 角色识图。 | 图片搜索工具参考。 | P2，OneBot 特化转发/图片输出。 |
| `nonebot_plugin_acgnshow` | ACG 展会查询。 | 生活 + ACG 事件查询参考。 | P1/P2，外部来源可靠性。 |
| `nonebot_plugin_badrawcard` | Blue Archive 抽卡模拟。 | 抽卡模拟模式参考。 | P2，娱乐刷屏风险。 |
| `nonebot_plugin_boardgame` | 桌游命令和状态管理。 | 互动状态机参考。 | P2，不是首里程碑核心。 |

## 设计影响

- `access_control` 保留在治理 shortlist，可能比手写 ACL 更适合调用配额和会话权限。
- 增加 `personal_reminder` 能力族，但必须私聊优先、同意、安静时间、snooze、delete/list。
- Bilibili 解析要多来源对比：`bilichat` 看成熟订阅，`analysis_bilibili` 看内容覆盖，`bili_helper` 看富渲染和 cookie 模式。
- `ai_groupmate` 证明群 AI 必须折叠过期回复，不能让 LLM 队列堆积后迟到发言。
- 动漫资源和同人工具默认私聊/命令触发，直到版权、NSFW、来源条款和群策略明确。

## Registry  caveat

这次扫描不表示 903 个 registry 条目都适合本项目。后续仍应使用 curated shortlist：只有当新候选能加强计划中的能力族，或提供更好的架构模式时才加入。
