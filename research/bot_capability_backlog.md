# 机器人能力 Backlog

## 目的

这个 backlog 记录统一机器人除了基础聊天之外可以解决的实际问题。排序刻意保守：先交付小而有用、低风险、低噪声的功能，再考虑高风险自动化。

优先级含义：

- P0：可靠角色机器人的基础设施。
- P1：有用且低到中风险的用户可见功能。
- P2：有价值，但需要同意、隐私策略或更多基础设施。
- P3：强大但风险高、容易吵、依赖凭据或成本高。

## P0 基础能力

| 能力 | 触发方式 | 用户价值 | 参考来源 | 说明 |
| --- | --- | --- | --- | --- |
| 安全 LLM 聊天 | 私聊、提及、显式聊天命令 | 基础自然对话 | `pxchat`, `aitalk`, `llmchat`, `deepseek`, OutputPro, AntiPromptInjector | 必须经过 policy、OOC、最终输出审查。 |
| 短期上下文窗口 | 内部自动使用 | 对话更连贯 | `pxchat/context.py`, `chatrecorder` | 日志是不可信事实。 |
| 统一权限和冷却 | 每条消息/工具调用 | 避免刷屏、滥用和误操作 | `permission`, `blacklist`, `authrespond`, Bison, OutputPro | 订阅和主动能力前必须完成。 |
| 手动群总结 | `总结 N` / 管理员命令 | 快速回顾聊天 | `summary-group`, `chatrecorder` | 使用存储记录、限制范围、加冷却。 |
| 公共游戏/wiki MVP | 显式命令 | 不绑定账号也能查游戏信息 | WWwiki, arktools, gscode, starrail_calendar | 第一阶段只用公共数据。 |

## P1 低风险实用工具

| 能力 | 触发方式 | 用户价值 | 参考来源 | 说明 |
| --- | --- | --- | --- | --- |
| 链接解析 | 用户发链接或显式解析命令 | 把链接变成可读卡片 | `nonebot_plugin_parser`, `bilichat`, `resolver`, 本地 `astrbot_plugin_parser` | 群自动解析可配置且有冷却。 |
| Bilibili 视频/动态/直播 | 链接、命令、订阅 | 媒体预览和 UP 更新 | `bilichat`, `bililive`, Bison, 本地 parser | cookie 可选且受控。 |
| Wiki/搜索命令 | `搜`, `百科`, `wiki` | 手动查资料 | `tavily`, `mediawiki`, `anime` | 搜索结果是不可信上下文。 |
| 天气查询和预警 | 命令、管理员订阅 | 日常实用和紧急提醒 | `heweather`, `nmcweather`, `weather_rank` | 注意位置隐私和告警疲劳。 |
| 一次性交通查询 | 命令 | 火车/路线信息 | `12306-ticket` | 持续监控后置。 |
| 兑换码/日历 | 命令或低频摘要 | 游戏工具 | `gscode`, `starrail_calendar`, GsCore 公共命令 | 低风险公共信息。 |
| 统一卡片渲染 | 内部渲染 | 输出更清楚 | `htmlrender`, `htmlkit`, `cardimg`, WWwiki 模板 | 集中控制风格、大小和 fallback。 |

## P2 个性化和推荐

| 能力 | 触发方式 | 用户价值 | 参考来源 | 说明 |
| --- | --- | --- | --- | --- |
| 偏好记忆 | 显式 opt-in | 推荐和语气更贴合 | ProactiveChat、群分析、GsCore memory 思路 | 需要查看/删除/导出。 |
| ACG 推荐 hub | 命令或私聊摘要 | 动漫、漫画、小说、游戏、电影、纪录片、综艺建议 | Tavily, MediaWiki, Pixivbot, Anime, QQMusic/Kuwo | 来源 + 排名，不靠纯 LLM 猜。 |
| 同人推荐 | 默认私聊命令 | 找同人文、图、漫画、cos、视频 | Pixivbot, genshin_cos, parser/search | 遵守平台条款、版权、NSFW，默认私密。 |
| 群知识库 | 管理员 opt-in | 保存有用链接、攻略、FAQ | chatrecorder, 群分析, GsCore knowledge | 需要整理和隐私边界。 |
| 私聊主动提醒 | opt-in 定时 | 温和生活辅助 | ProactiveChat scheduler | 安静时间、随机化、未回复上限。 |
| 抽卡模拟 | 命令/小游戏 | 趣味互动 | `arkgacha`, `ww_gacha_sim`, GsCore 游戏插件 | 明确标注模拟。 |
| 网页编码辅助 | 私聊/管理员命令 | 解释代码、小脚本、review | LLM tool gate, MarshoAI | 群里不任意执行；需要权限和隔离。 |

## P3 后续高风险

| 能力 | 触发方式 | 用户价值 | 参考来源 | 后置原因 |
| --- | --- | --- | --- | --- |
| 账号游戏面板 | 私聊绑定后 | 个人游戏数据 | GenshinUID, StarRailUID, ZZZeroUID, XutheringWavesUID | cookie/token/UID 隐私，需要私聊存储。 |
| 抽卡记录导入 | 私聊同意后 | 个人抽卡历史 | gachalogs, wwgachalogs, GsCore | authkey 和历史敏感。 |
| QQ 空间自动化 | 人工/管理员确认 | 角色社交存在感 | qzone_ultra | 账号行为、声誉、限频风险。 |
| 群内自主聊天 | 管理员 opt-in | 群更活跃 | ProactiveChat, pxchat | 很容易吵，需要强配额和话题判断。 |
| 大规模表情/同人抓取 | 手动/管理员管线 | 丰富媒体人格 | sticker_saver, memes, parser/search | 同意、版权、存储、审核。 |
| 群内完整 coding agent | 管理员命令 | 高级开发助手 | MarshoAI/MCP | 工具执行风险和长输出噪声。 |
| 自主管理动作 | 明确人工确认 | 管理辅助 | BotShepherd, LLM action surfaces | 禁言/踢人/撤回等不能模型自主。 |

## 生活向能力想法

- 每日简报：天气、日程、通勤风险、订阅更新和一句温和提醒。
- 专注计时：私聊番茄钟、休息提醒、任务摘要。
- 习惯提醒：喝水、睡眠、服药文字提醒；不做医疗建议。
- 事件记忆：生日、纪念日、游戏刷新、直播、番剧更新时间。
- 家务清单：倒垃圾、快递、购物清单、群共享 todo。
- 情绪支持：只在用户主动表达时温和回应，不公开诊断。
- 群摘要：热门链接、未解决问题、决策、好笑语录、行动项。
- ACG 追踪：番剧、漫画、小说、游戏卡池/活动。
- 旅行助手：车票/航班/酒店摘要、延误/天气提醒、行程摘要。
- 个人归档：找上次那张图、链接、攻略、代码片段。

## 第一可用功能集

第一版只建议包括：

1. 带人格契约的安全 LLM 聊天。
2. 少量来源的手动链接解析。
3. 手动群总结。
4. 天气查询和管理员配置告警。
5. 公共游戏 wiki/code/calendar 命令。
6. 统一卡片渲染和输出安全。

这样能快速有用，同时保持系统可调试。
