# 守岸人命令手册（人读版）

与机器人内 `/bot help <模块>` 深度帮助页同一口径：每个模块、每条指令、每个参数。

完整自动同步教程目录：[docs/command-catalog.md](docs/command-catalog.md)。修改 `_HELP_ENTRIES` 后运行 `python scripts/command_catalog.py --write`，一致性测试会拒绝过期文档。
- 参数标注：`<x>` 必填、`[x]` 可选；「默认」指省略参数时的行为。
- 权限标注以代码内 actor_roles 判定为准（`仅管理员` / `全员`）。
- 数据真相源：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py`（RWC3 迁移后真身）的 `_HELP_ENTRIES`；模块/别名总数以 [docs/command-catalog.md](docs/command-catalog.md) 的自动统计为准，不在此手写。
- 开发/运维任务（dev.ps1、测试、smoke）见本文末尾「开发命令速查」。

## 总览

- 帮助本体：`/bot help`、`/bot 帮助`（`/岸宝帮助`、`守岸人帮助` 等昵称形式等价）。
- 模块深页：`/bot help <模块名>`（如 `/bot help 点歌`）；分类手册：`/bot help 管理员`、`/bot help 大模型`、`/bot help 子功能`。
- 普通成员只见公开模块；管理员另见管理员专属模块（含本手册全部内容）。

## 管理员专属（/bot 前缀命令族）

| 模块 | 指令 | 作用 | 关键参数 |
|---|---|---|---|
| 状态 | `/bot status` | 运行状态摘要（暂停/角色/存储/LLM） | 无 |
| 为什么 | `/bot why [id]` | 解释最近一次决策与错误 | id：可选，request_id/debug_id |
| 决策影子 | `/bot decision [N]`（别名 `决策`/`决策引擎`/`decision`，昵称形式等价） | 查看影子决策引擎的路由分歧痕迹 | N：条数可选，1-100 默认 20；内容=时间/路由类别/引擎判定与现行判定/一致或分歧/耗时，自由文本字段打码截断，不含消息原文；痕迹已落盘、重启可查历史；影子模式默认关闭（legacy_only）下查到「暂无记录」属预期，不是故障 |
| 回执 | `/bot receipt <id>` | 查发送回执 | id 必填 |
| 审计 | `/bot audit <request_id>` | 查审计事件 | request_id 必填 |
| 最近 | `/bot recent [数量]` | 诊断+回执+审计合并摘要 | 数量 1-20，默认 5 |
| 队列 | `/bot queue` | 发送队列状态 | 无 |
| 历史 | `/bot history clear` | 清本会话最近对话 | 无 |
| 上下文 | `/bot context [文本]` | 看注入给模型的上下文 | 文本可选 |
| 对话 | `/bot dialogue [文本]` | 本地跑一轮对话诊断 | 文本可选；可能一次 LLM 调用 |
| 接入 | `/bot setup llm` | LLM 七键接入清单 | 无 |
| 配置 | `/bot config` | 配置体检（脱敏） | 无 |
| 就绪 | `/bot readiness` | 聚合就绪状态 | 无 |
| 角色 | `/bot roles` | 角色数量摘要 | 无 |
| 人格 | `/bot persona` | 人格材料自检 | 无 |
| 暂停 | `/bot pause` / `/bot resume` | 软暂停/恢复 | 无 |
| 回复 | `/bot reply [模式]` | 回复详略档位 | 详细/科普/详尽→detail；精简/简洁→concise；默认/自动→auto；持久化 |
| 日志 | `/bot logs [级别] [数量]` | 运行时事件日志 | 级别 debug\|info\|warning\|error 默认 info；数量 1-200 默认 50 |
| 解析 | `/bot parse [数量]` | 全局解析历史 | 数量 1-100，默认 10 |
| 搜索 | `/bot search <问题>` | 验证联网检索 | 问题必填 |
| 凭据 | `/bot alert check [--probe]`、`/bot cookie status\|import\|login\|check\|expiry` | 凭据健康与 18 平台 cookie 导入 | `--probe` 可选；import：`<平台> <Cookie头>`；login/check 仅 bilibili 支持扫码 |
| 群策略 | `/bot group list\|add\|del\|set\|clear …` | 群黑白名单四档 | 档位 black1\|black2\|white1\|white2；群号数字可多个 |
| 群文件 | `/bot 群文件` | 群上传统计（仅群聊） | 无 |
| 文件 | `文件 <格式> <主题>` | 生成文档并上传群文件 | 格式 md\|markdown\|docx\|pptx\|xlsx\|pdf |
| 身份 | `/bot identity show\|set\|tag\|clear`；自助 `/bot identity set-name\|set-gender\|unset-name\|unset-gender` | 会话级身份记忆＋用户自助称谓偏好 | set `<昵称>`；tag 逗号分隔最多 8 个；自助四子命令所有用户可用、只能改自己（set-gender 取值 male\|female\|nonbinary\|custom\|unknown，set-name ≤32 字）；对本会话生效，人格不变 |
| 怪癖 | `/bot quirk list\|approve\|retire\|add` | 人格怪癖审核制 | list [pending\|active\|retired] 上限 20；approve/retire `<id前缀>` 唯一命中；add 直添即生效 |
| 邮件 | `/mail status\|accounts\|use\|send\|pause\|resume` | Gmail/QQ 收发控制 | 仅 Telegram 管理端；send 三/四段用 `\|` 分隔 |

### 大模型相关

| 模块 | 指令 | 作用 | 关键参数 |
|---|---|---|---|
| 模型 | `/bot model list\|set\|add\|update\|priority\|effort\|think\|price\|search\|usage\|health\|probe\|routes\|vision\|remove\|reset`（`/bot llm` 诊断） | 模型注册表/故障转移/健康/计费总控 | add：`<id> model= base_url= key= [tags=] [effort=] [group=] [priority=]`；effort/think 档位 off\|low\|medium\|high\|xhigh\|max(default=清除)；price `input=/output=/cache_read=/cache_creation=/per_call=`（元/1M tokens；per_call 为元/请求，按次计费）；usage [today\|YYYY-MM-DD]；全部热改即时生效 |
| 用量 | `/bot model usage [日期]`、`/bot model price …` | Token 账单、价格维护、阈值提醒与 13/18/23 点定时报告 | 日期可选；阈值 .env：BOT_USAGE_ALERT_* |
| 设置 | `/bot runtime set\|get\|list\|reset\|nickname\|persona\|model\|instance` | 运行时参数热改（白名单键，优先于 .env，可 `--instance <名称>`） | persona：list\|switch `<id\|default>`\|probability `<id> <0-1>`；nickname：add\|remove\|list |
| 供应商 | BOT_MODEL_REGISTRY（.env） | 静态供应商注册表 | priority 1-999；探测脚本 `--max-tokens` 1-4096 默认 32 |
| Telegram | TELEGRAM_BOTS、BOT_TELEGRAM_ADMIN_*（.env） | TG 提醒与远程控制 | JSON 数组 |

### 运行开关类（.env 键，改后重启）

- 限流：`BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR/_PER_MINUTE`（≥0，0=该帽不生效）、`BOT_RATE_LIMIT_EMOTION_EXEMPT`（默认 true）、`BOT_GROUP_CHAT_AUTO_REPLY_ENABLED`（默认 false）+`…_PROBABILITY`（0..1 默认 0.004，2026-09-12 实弹调低防自我触发限流）、安静时间 6 键 `BOT_QUIET_HOURS_*`——以上均可 `/bot runtime set` 热改。
- 点名回复节流：`BOT_RATE_LIMIT_CHAT_SENDER_MIN_INTERVAL_SECONDS`（默认 45，同一人点名回复最小间隔秒数，0=关闭）——可 `/bot runtime set` 热改。
- 合并转发：`BOT_RENDER_FORWARD_MIN_NODES`（默认 4）/`_MIN_CHARS`（1500）/`_MAX_NODES`（0=不限）/`_NODE_CHARS`（≥200，默认 900），热改；消费在装配期，需重启。
- 群摘要：`BOT_SHARED_GROUP_CONTEXT_ENABLED`（默认 false）、`BOT_GROUP_DIGEST_LIST_MODE`（whitelist|blacklist|off|all）、`BOT_GROUP_DIGEST_WHITELIST/BLACKLIST`——热改；每日通讯总结推送 `BOT_GROUP_DIGEST_PUSH_ENABLED`（默认 true）+`BOT_GROUP_DIGEST_PUSH_TIME`（HH:MM，默认 21:30，仅白名单群、非 whitelist 零推送）——.env 键，重启生效。
- 视频理解：`BOT_VISION_ENABLED`（默认 false）、`BOT_VISION_MODE`（relay|direct）、`BOT_VISION_REPLY_PROBABILITY`（0..1 默认 1.0）、`BOT_VIDEO_UNDERSTANDING_ENABLED`（默认 false）等——热改。
- 运行开关：`BOT_SEND_QUEUE_ENABLED`、`BOT_SEND_QUEUE_WORKER_ENABLED`、`BOT_AUDIT_ENABLED`、`BOT_RECEIPTS_ENABLED`、`BOT_DIAGNOSTICS_ENABLED`——均默认 false，.env 键，重启生效。

## 子功能（无需 /bot 前缀，自然语言/短命令触发）

| 模块 | 触发 | 作用 | 关键参数 |
|---|---|---|---|
| 订阅 | `/订阅 add\|list\|pause\|resume\|remove` | 平台新内容推送 | add `<公开目标>`（群内需管理员）；pause/resume/remove `<id>` 目的地粒度 |
| 点歌 | `点歌 <歌名>`、`点歌 <编号>`、`点歌模式 <模式>` | 搜歌发送（候选选择窗默认开启） | 同名/多候选 ≥2 首一律先出候选卡询问，回复序号数字（如 `2`）或 `点歌 2` 即选播，不再直接播首选；候选 300 秒内有效，不回复不播放；模式 卡片\|语音\|音频\|链接\|全部可组合（管理员持久化） |
| 表情 | `表情 <模板> [文字]`、`表情 列表` | meme-generator-rs 生成表情 | 文字多段用 ｜ |
| 偷表情 | `偷表情 [关键词]`、`表情库统计` | 表情库加权随机 | 关键词/情绪标签可选 |
| 搜图 | `搜图`＋图片 | SauceNAO 反搜来源 | 图片需同条消息 |
| 天气 | `天气 <城市>` | NMC 天气（支持 2527 区县级查询） | 同名城市 省-市；查询词需像地名 |
| 行情 | `行情`＋可选市场词 | 全球股指（东方财富，60s 缓存） | A股/B股/上证B/深证B/美股/港股/日经/纳斯达克/道指/标普/莫斯科/俄罗斯 等 |
| 个股行情 | `英伟达股价`、`AMD 股价`、`英特尔股价`、`股价`、`股價`、`個股`、英文 `stocks`＋公司别名；`市值` 须与公司别名共现（如 `英伟达市值`，裸词不触发） | 个股行情（OHLCV/市值，出金融卡；数据带来源与延迟标注） | 与「行情」互不抢路由（裸「行情」归行情）；OpenAI 未上市，只给有来源的公开估值说明 |
| 汇率 | `汇率`、`美元兑人民币`、`100日元换多少人民币`、`匯率`/`兌換` 等 | 汇率查询/主要货币面板（出金融卡） | 11 币种、基准货币明确；中间价口径带延迟标注；TWD/MOP/AED 暂无行情会明说；与 stocks 重叠时汇率优先 |
| 占卜 | `占卜`、`塔罗 [三张\|每日一抽]`、`八字 <生日时间>` | 金钱卦/塔罗/八字（含地支藏干） | 日期 `1998年3月2日\|1998-03-02\|1998/3/2`；只给日期按午时；1900-2100 年 |
| 快报 | `快报`/`早报`/`晚报`/`今日热点`/`科技新闻`/`AI新闻`/`财经快报`/`财经新闻`/`国际新闻`；昵称形式 `守岸人 快报`/`守岸人 AI新闻` 等等价触发 | RSS 聚合快报（10 分钟缓存）：默认 20 条；标题下带 RSS 摘要行（治标题党）；自动过滤营销条目（求职/招聘/推广/优惠等） | 类目：财经/国际/科技·AI/综合轮转；裸「新闻」不触发 |
| 维基 | `维基 <词条>` | MediaWiki 百科 | 默认中文维基 |
| 萌娘百科 | `萌娘百科 <词条>`；直接问「XX是谁？」 | 萌百查询＋实体问句自动查询 | 问句剥出实体 2-30 字；未命中转聊天 |
| 历史上的今天 | `历史上的今天 [设置 HH:MM\|状态\|取消]` | 当日历史＋每日推送 | 群内设置/取消需管理员 |
| 下载 | `/bot download <链接>`（裸发「下载 …」当前不走路由，请用 /bot 前缀） | yt-dlp 下载回传；多连接并行（分片 8 并发+16MB Range 分块，装有 aria2c 时自动委托 -x16）；平台有 CC 字幕时自动下载保存（srt 优先、zh 简体优先），回复显示「字幕已保存：路径」 | 单文件 ≤1GB；拒绝内网地址 |
| 昵称 | `守岸人/岸宝 <命令>`；`/bot 昵称 set <QQ号> <小名>` | 昵称触发命令（后者管理员）；繁体触发词已支持：`點歌`/`快報`/`財經新聞`/`國際新聞`/`親密度`/`天氣`/`天氣預報`/`隨機圖`/`來張圖` 等 | 昵称表经 `/bot runtime nickname` 维护 |
| 链接 | 直接发 http(s) 链接 | 平台信息卡解析 | B站/抖音/小红书/油管/推特/GitHub 等 |
| 草稿 | `报存 给 <收件人> 发消息\|邮件[，主题：…，内容：…]` | 自动发送草稿预览 | 收件人可用 、,， 分隔多个；当前仅预览不实发 |
| 吃什么 | `吃什么 [三选一\|辣度\|忌口]`、`菜谱 <菜名>` | 家常菜推荐/菜谱 | 约束描述自动走 AI 菜谱 |
| 好感度 | `好感度`/`好感查看`/`查询好感`/`好感`/`好感值`/`亲密度`/`affinity`；`好感度 算法` | 双向好感（-100~+100 八档，v5 多因素线性步长） | `好感` 仅独立成词时触发（防「好感消失了」误触）；群聊出榜，`我` 只看自己，`算法` 输出 v5 定性说明（多因素：说话温度×相处时长×第一印象×当日心情，不展示固定加减数值） |
| Epic | `epic`/`免费游戏`/`steam免费` | Epic+Steam 每周限免 | 无参数 |
| 随机图 | `随机图`/`来张图` | 自建图库随机发图（仅发原图本体，不附带「随机图片」等文字标注） | 目录 `BOT_RANDPIC_DIRS`；触发词 `BOT_RANDPIC_TRIGGER_WORDS` |
| 语音 | `说 <文本>`、`语音 <文本>`、`念 <文本>`、`朗读 <文本>`、`语音合成 <文本>`；繁體 `說`/`語音`/`唸`/`朗讀`/`語音合成`；英文 `tts`/`say`（大小写不敏感）；拼音 `shuo`/`yuyin`/`nian`/`langdu` | 文本合成守岸人音色语音（本机 GPT-SoVITS v2ProPlus，深度帮助 `/bot help 语音`） | 触发词后必须跟正文，只发「说」等裸触发词不占路由、交回人格对话；正文默认上限 200 字（`BOT_TTS_MAX_CHARS`，硬顶 `BOT_TTS_HARD_MAX_CHARS`）；追加词 `BOT_TTS_TRIGGER_WORDS` 与内置 16 词合并非替换；繁體正文保留繁體用字不转简；失败降级：私聊守岸人口吻文案（如「嗓子还没接上——语音服务好像没在跑」），群内走中央 A-19 降级池；总开关 `BOT_TTS_ENABLED`、参考音频 `BOT_TTS_REF_AUDIOS`、自动配音 `BOT_TTS_AUTO_REPLY_*`（默认关） |
| 提醒 | `<时间>提醒我 <事项>`、`提醒列表`、`取消提醒 <id前缀>` | 到点主动督促 | id 前缀 4-12 位唯一命中；事项 ≤120 字 |
| 记忆 | `/bot memory add\|list\|delete` | 个人长期记忆（全员，仅本人） | add 支持 `--sensitivity=personal\|group\|public\|credentialed`（默认 personal）；群聊 list 只见 public/group |
| 路由 | `/bot route <文本>`、`/bot routes` | 路由判定/路由表（全员只读） | 文本必填 |

**拼音与英文触发**：子功能各能力的触发词除中文/繁體（见上表「昵称」行）外，另有英文与拼音全拼/缩写等价形态（如 `点歌`/`diange`/`dg`、`行情`/`hangqing`/`hq`）。
- 每个能力的完整词表（英文/拼音全拼/缩写/繁體）以 `/bot help <模块>` 深度页与 [docs/command-catalog.md](docs/command-catalog.md) 为准，此处不逐词罗列。
- 拼音缩写为渐进特性：上线后观察群聊误伤，行级可回撤——`.env` 无法逐词关闭，回撤＝改词表（删除对应能力触发正则或 `_HELP_ENTRIES` 别名中的词条，重启后生效）。
- 两字母缩写（如 `dg`/`hq`）在群聊可能撞日常语义，遇到误触发按上条指引回撤对应词条即可。

## 开发命令速查

统一入口 `scripts/dev.ps1`（优先使用工作区外 `ChatBot_Runtime\venv`）。常用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 help        # 任务帮助
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 doctor      # 依赖体检
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 test        # pytest 全量回归
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 lint        # ruff check
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 verify      # docs/plugin/pytest/ruff/mypy 总检
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 run         # 启动 NoneBot
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 console     # 控制台对话
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 backend-smoke -Message "测试后端主链路"
```

完整任务表（smoke/queue/transport/credential/knowledge-sync 等约 40 项）执行 `dev.ps1 help` 查看；测试策略、路径与安全规则见 `AGENTS.md`、`WORKSPACE_GUIDE.md` 与 `docs/ai-setup-knowledge-pack.md`。运行数据统一在 `ChatBot_Runtime\data\`；`.env`、Cookie、Token、数据库内容不进入聊天、日志或文档。


## 功能控制（控制面服务同源）

| 指令 | 权限与效果 |
|---|---|
| `/bot feature list` / `/bot feature get <ID>` | 管理员只读，返回稳定ID、有效状态及版本。 |
| `/bot feature enable\|disable\|reset <ID>` | 仅超管；CAS写入状态与审计。主Pipeline的新任务受门禁控制，已运行任务不强杀。 |
| `/bot feature preview <ID> on\|off\|reset` | 仅超管；返回影响节点，不修改状态。 |

示例：`/bot feature disable bot.plugin.weather`。详细帮助：`/bot help 功能管理`。

`/bot runtime set`、`reset` 、模型写操作和核心人格 switch/probability 仅超管可修改。参数API与命令共用ConfigControlService及按实例隔离SQLite，资源重载尚未完成的键明确拒绝热改，不假称更新成功。当前仅覆盖已登记主能力，入站媒体/自动副作用的细分门禁仍在迁移。

功能管理同义入口：`/bot 功能管理 ...` 归一到 `/bot feature ...`；`/bot help feature` 与 `/bot help 功能管理` 返回同一帮助。昵称形式只给管理指令引导，不绕过 `/bot` 直接执行写操作。


## 细分功能管理（本批接线）

既有 `/bot feature` 服务现在可控制 `bot.ingress.file_read`、`bot.ingress.audio_transcode`、`bot.ingress.telegram_media`、`bot.ingress.reply_lookup`、`bot.plugin.poke.reply`、`bot.plugin.poke.poke_back` 等细分 ID。完整目录以 `/bot feature list` 和 API 能力树为准，详见 `docs/design/control-plane-registry.md`。

- 查询：`/bot feature get bot.ingress.file_read`（管理员）。
- 预览：`/bot feature preview bot.ingress.file_read off`（超管）。
- 关闭：`/bot feature disable bot.ingress.file_read`（超管）。
- 恢复继承：`/bot feature reset bot.ingress.file_read`（超管）。

父级关闭不能被子级 enable 突破；修改影响后续事件，不强杀运行中处理。树开关不会绕过原有配置、概率、冷却或安全权限。没有新增绕过 SendQueue 的调试指令。

## 工作区和动作后端说明

工作区REST及动作REST已分别提供服务适配，详见 `docs/design/control-plane-workspaces.md`、`docs/design/control-plane-services.md`。本批没有新增 `/bot workspace` 或 `/bot action` 指令，不要把API路径当聊天命令。真实生产发送端口和默认生产运维动作尚未装配，不能用接口存在来判断生产功能可用。
