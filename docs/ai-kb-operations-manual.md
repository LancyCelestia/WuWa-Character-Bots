# 守岸人机器人运维知识手册（AI 知识库专用）

本文档是守岸人 QQ 机器人（NoneBot2 + 统一运行时插件 bot_unified_runtime）的运维说明书，专门写入机器人的向量知识库。当用户询问"怎么加模型、某指令怎么用、为什么配置不就绪、机器人为什么不回复"等问题时，机器人应以本文档的事实为依据作答。文档约定：所有命令都在 QQ 对话框输入；带 `/bot` 前缀的指令多数仅管理员可用；配置键写法为 `.env` 中的大写形式，修改 `.env` 后必须重启机器人才生效。

## 一、机器人与权限体系

机器人的人格是守岸人（昵称岸宝），基于 NoneBot2 框架，通过 SnowLuma 协议端接入 QQ，运行时插件为 plugins/bot_unified_runtime。发送者被划分为五种角色：user（普通）、trusted（受信任）、enterprise（企业）、admin（管理员）、blocked（黑名单）。角色由发送者 ID 决定，名单配置在 `.env` 中，多个角色可以叠加。

管理员由 `.env` 中的 BOT_ADMIN_USER_IDS 决定（QQ 管理员）和 BOT_TELEGRAM_ADMIN_USER_IDS（Telegram 管理员）。取值可以是 JSON 数组（如 `["123","456"]`）或分号、逗号分隔的字符串（如 `123;456`）。把自己设为管理员的方法：编辑 `.env`，把你的 QQ 号加进 BOT_ADMIN_USER_IDS，然后重启机器人。注意：BOT_ADMIN_USER_IDS 不支持热更，不能用 `/bot runtime set` 在线修改；NoneBot 官方的 SUPERUSERS 配置在本插件中不生效，写了也没有用。设置是否成功，可以用 `/bot roles` 或 `/bot recent` 验证：能返回数据说明管理员身份已生效。

普通账户触发管理员指令时，不会执行任何操作，只会收到固定的拒绝回执。例如诊断类指令回执为"只有管理员可以查看运行时排障记录。"，运行时管理类指令回执为"该命令只允许管理员使用。"，日志类回执为"只有管理员才能查询运行时日志。"。`/bot 帮助` 总览对普通账户只显示公开功能主题（主题清单以 `plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py` 的 `_PUBLIC_HELP_TOPICS` 现算为准），管理员登录后才能看到全部诊断主题。

## 二、大模型接入：七个必配键

机器人对话由 OpenAI 兼容接口的大模型驱动，主配置有七个必配键，全部在 `.env` 中设置。第一，BOT_CHAT_PROVIDER：供应商类型，填 openai_compatible 表示真实模型，填 static 表示本地占位模型（不联网）。第二，BOT_CHAT_MODEL：对话使用的模型名字符串，必须填供应商提供的真实模型名，不能留占位符。第三，BOT_CHAT_API_KEY：API 密钥，可以填真实密钥，更安全的做法是填 `env:变量名` 引用同文件里另一个环境变量；密钥永远不会被回显到任何输出里。第四，BOT_CHAT_BASE_URL：OpenAI 兼容接口地址，必须以 http(s):// 开头，一般以 /v1 结尾，地址里不允许内嵌账号密码。第五，BOT_CHAT_TEMPERATURE：采样温度，范围 0.0 到 2.0，数值越高回复越随机。第六，BOT_CHAT_MAX_TOKENS：单次回复的输出上限，非负整数，填 0 即不设上限。第七，BOT_CHAT_TIMEOUT_SECONDS：单次请求超时秒数，必须是正数。

配置是否就绪由 `/bot config`（管理员）检查。判定规则：API 密钥为空或等于占位符（如 your-api-key、replace-me、test-key 等）视为缺失；模型名为空或占位符（如 your-model-name、replace-me 等）视为缺失；BASE_URL 缺失、协议不对或内嵌账号密码都会报错，其中内嵌账号密码会报 openai_base_url_unsafe，属于安全问题必须移除。温度、max_tokens、超时超出合法范围也会报对应错误。全部通过且 provider 为 openai_compatible 时状态为 ready；有错误为 blocked；没有错误但仍是 static 占位供应商则为 local_only。接入完成后用 `/bot llm`（管理员）做一次真实连接诊断，它会用当前配置发起一次短调用并报告结果，不会修改任何配置。

## 三、多供应商注册表与故障转移队列

除主配置外，机器人支持多个模型供应商并存，注册表配置键为 BOT_MODEL_REGISTRY（JSON 对象）。每个条目包含：id（自定义名称）、model（模型名）、base_url（接口地址）、api_key（密钥，支持 env:变量名 引用，也支持列表形式实现同一模型多密钥轮流转移）、tags（档位标签）、priority（全局优先级，整数，1 到 999，数字越小越优先被调用）。密钥本身存放在 BOT_API_KEY_开头的环境变量里（如 BOT_API_KEY_QIANQIANYE），注册表中用 `env:` 引用，绝不写明文。

故障转移队列的排序规则是：候选为注册表中所有 tags 不含 manual 的条目，按 priority 从小到大排列。每次生成时先按当前消息挑档位：消息长度超过复杂任务字数门（`plugins/bot_unified_runtime/domains/chat_reply/llm_engine/model_router.py` 的 `_COMPLEX_MIN_CHARS`），或包含"教程、排查、分析、翻译、总结、比较、代码、配置、部署"等关键词时判定为复杂任务，先尝试 strong 档模型，fast 档排在后；普通消息则先尝试 fast 档。快速模式（BOT_CHAT_FAST_MODE 开启时）会把候选截断为 BOT_CHAT_FAST_MAX_CANDIDATES 个（填 0 即不限制）。整个转移过程受 BOT_CHAT_FAILOVER_MAX_SECONDS（缺省值以 `plugins/bot_unified_runtime/config.py` 的 `bot_chat_failover_max_seconds` 现算为准，生产 `.env` 可覆盖）和请求级总预算双重限制，防止连续失败把响应拖到分钟级。

调用时的转移规则：按队列顺序逐个尝试，每个候选先试它的第一个密钥，失败再试下一个密钥（如果配了多个），整个候选失败后切换到队列里的下一个模型。缺少密钥的候选会被直接跳过（记为 config_missing），不会中断流程。如果管理员用 `/bot model set <id>` 手动指定了模型，则先试指定模型，失败后仍按队列顺序转移其余候选。转移顺序和每次尝试结果可以用 `/bot model list` 查看。

## 四、大模型的增加、修改、删除、启用与禁用

新增模型供应商用命令 `/bot model add <id> model=<模型名> base_url=<接口地址> key=<API密钥或env:变量名> [tags=fast,strong] [group=<分组>] [priority=<数字>]`。参数含义：id 是你给模型起的名字，之后 set、update、remove 都用它；model 填供应商提供的模型名，原样填写；base_url 必须以 /v1 结尾；key 填 API 密钥或 `env:变量名` 引用（更安全，密钥不会回显）；tags 可选，逗号分隔，fast 表示日常档、strong 表示复杂任务档、vision 或 multimodal 或 vlm 表示允许直接接收图片；priority 可选，越小越先被调用，省略默认 100。完整示例：`/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=env:BOT_API_KEY_MYAPI tags=fast,strong priority=1`。常见错误：等号两边加了空格会报"参数格式应为 键=值"；漏写 model= 或 base_url= 会提示必填。新增完成后立即生效，无需重启，并自动进入故障转移队列。

修改模型参数用 `/bot model update <id> <键=值 ...>`，只写要改的项，例如 `/bot model update myapi key=env:BOT_API_KEY_NEW priority=3`，可修改的键有 model、base_url、key、group、tags、priority。只调故障转移顺序用 `/bot model priority <id> <数字>`。手动切换当前模型用 `/bot model set <id|auto>`，auto 表示回到自动选型；`/bot model reset` 清除手动指定回到自动选型。删除自定义模型用 `/bot model remove <id>`，注意来自 .env 的 BOT_MODEL_REGISTRY 条目不能删除，只能用 update 覆盖其参数。

需要特别说明"启用和禁用"：机器人没有独立的模型启用/禁用开关。要把一个模型移出自动故障转移队列但保留手动可选，用 `/bot model update <id> tags=manual`，打上 manual 标签后它不再参与自动排队，但仍可用 `/bot model set <id>` 手动指定使用；要恢复参与自动队列，用 `/bot model update <id> tags=fast,strong` 把标签改回来即可。要彻底删除则用 remove（仅限运行时新增的条目）。预设名（BOT_MODEL_PRESETS 中定义的短名，如 terra、luna）只能手动指定，永远不会自动参与排队。

## 五、模型相关辅助功能

图片识别（视觉）模型独立管理：`/bot model vision list` 查看候选与开关；`/bot model vision add <id> model=<视觉模型> base_url=<接口> key=<密钥> [priority=<n>]` 新增；update、priority、remove 同主模型规则；`/bot model vision mode relay|direct` 切换模式，relay 表示先用视觉模型把图片转成文字，direct 表示把图片直接传给 tags 含 vision/multimodal/vlm 的主模型，失败只回退一次 relay。识别开关用 `/bot runtime set BOT_VISION_ENABLED true|false` 热更。

推理强度用 `/bot model think <off|low|medium|high>` 设置，off 表示不向模型发送 reasoning_effort 字段。联网搜索用 `/bot model search <on|off>` 热切换。Token 用量用 `/bot model usage [today|YYYY-MM-DD]` 查询，按模型分组汇总输入、输出和总 Token。分时段自动换模型用 `/bot runtime set BOT_MODEL_SCHEDULE <JSON>`，例如 `/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}`，支持跨零点时间窗，窗口外自动回到正常选型。

## 六、运行时参数热更

管理员可用 `/bot runtime set <键> <值>` 在线修改参数并立即生效，无需重启；`/bot runtime get <键>` 读取当前值（标注是覆盖值还是 .env 默认）；`/bot runtime list` 列出全部覆盖项；`/bot runtime reset [键]` 清除覆盖（省略键名则全部清除）。覆盖值持久保存在运行时数据目录的 runtime_settings 实例文件中。可以热更的键共二十个：BOT_CHAT_TEMPERATURE（温度 0-2）、BOT_CHAT_MAX_TOKENS（回复上限）、BOT_CHAT_MODEL（主模型）、BOT_CHAT_REASONING_EFFORT（推理强度，可填空、off、low、medium、high）、BOT_TRANSPORT_TIMEOUT_SECONDS（发送硬超时，值域与缺省以 `plugins/bot_unified_runtime/config.py` 的 `bot_transport_timeout_seconds` 及其校验器现算为准）、BOT_MODEL_SCHEDULE（分时段换模型 JSON）、BOT_REPLY_MAX_CHARS_PER_MESSAGE（单条消息字数上限）、BOT_REPLY_DETAIL（详略档位，详细、精简、默认）、BOT_MUSIC_MODE（点歌输出模式）、BOT_MEME_SEARCH_ENABLED、BOT_WEB_SEARCH_ENABLED、BOT_WEB_SEARCH_ADMIN_NOTICE、BOT_PERSONA_ACTION_BRACKETS、BOT_VISION_ENABLED、BOT_VISION_MODE（relay 或 direct）、BOT_CONTENT_VIDEO_AUTO_SEND（解析视频直发开关）、BOT_GROUP_BLACK1、BOT_GROUP_BLACK2、BOT_GROUP_WHITE1、BOT_GROUP_WHITE2（群策略四档）。

不在这二十个键白名单里的配置（例如管理员名单、人格文件清单、各类数据库路径），都只能改 `.env` 后重启机器人生效。多实例部署时可用 `--instance <名称>` 指定目标实例，`/bot runtime instance list` 列出已创建的实例设置文件。昵称也可以热管理：`/bot runtime nickname add|remove|list <昵称>`，添加后立即参与昵称触发。

## 七、对话框指令：系统与诊断类

`/bot status` 查看运行状态摘要（所有人可用）。`/bot why [编号]` 解释最近一次回复的路由与决策，编号可选。`/bot receipt <编号>` 查询发送回执状态（管理员）。`/bot audit <请求编号>` 查询审计事件（管理员）。`/bot recent [数量]` 查看最近诊断、回执与审计的排障摘要，数量 1 到 20，默认 5（管理员）。`/bot queue` 查看发送队列的待发、处理中、重试、失败计数（管理员）。`/bot logs [级别] [数量]` 查看运行时事件日志，级别可选 debug、info、warning、error，默认 info；数量 1 到 200，默认 50；两个参数先级别后数量（管理员）。`/bot parse [数量]` 查看最近的链接解析历史，数量 1 到 100，默认 10。`/bot route <文本>` 判定一段文本会命中哪条路由；`/bot routes` 打印全部路由表。长期记忆用 `/bot memory add <内容>` 添加（字数上限以 `plugins/bot_unified_runtime/config.py` 的 `bot_memory_max_chars` 现算为准）、`/bot memory list` 列出、`/bot memory delete <fact_id>` 删除，记忆按发送者与会话隔离。

深度诊断指令（均管理员）：`/bot context [文本]` 展示一条消息实际注入给模型的上下文构成；`/bot dialogue [文本]` 本地跑一轮对话诊断，不影响线上状态；`/bot llm` 做一次真实模型连接诊断；`/bot setup llm` 输出七个必配键的接入检查卡（含每项的取值范围与当前值，密钥不展示）；`/bot config` 做配置就绪体检（脱敏）；`/bot readiness` 聚合环境、配置、上下文、对话链路的总体就绪状态；`/bot persona` 自检人格材料强度与语气规则；`/bot roles` 查看各角色数量摘要（不含具体 ID）；`/bot history clear` 清空本会话最近对话；`/bot pause` 与 `/bot resume` 软暂停与恢复全部回复（暂停期间 status、help、why、receipt、audit、recent、queue、context、llm、setup、config、readiness、dialogue、roles、history 等控制类指令仍可用）；`/bot search <问题>` 验证联网检索链路。帮助本身用 `/bot help <主题>` 或 `/bot 帮助 <主题>` 查看某主题详情。

## 八、对话框指令：运行时管理与群策略

`/bot group` 系列管理群聊回复策略，分四个档位：black1 完全静默，black2 仅被 @ 或显式命令时回复，white1 正常回复加自然提问，white2 仅被 @ 时回复。用法：`/bot group list` 查看各档位名单；`/bot group add <档位> <群号>` 加入（群号可一次填多个）；`/bot group del`、`/bot group set`（覆盖）、`/bot group clear <档位>`（清空）。全部仅管理员。

私聊里机器人对所有消息放行；群聊里只有命令、昵称命令、被 @ 或写昵称点名才会触发回复，其余消息静默观察（受四档黑白名单约束）。群聊被门禁拒绝时机器人保持静默；限流触发时回复"当前会话/目标/整体回复过于频繁，已临时降频。"；安静时段（BOT_QUIET_HOURS 配置，默认 00:00 到 06:00，管理员角色默认绕过）回复"当前处于安静时间，已暂停非必要回复。"。回复详略档位用 `/bot reply <详细|精简|默认>` 调整，别名科普、详尽等于详细，简洁等于精简，自动等于默认；无参数查看当前档位；仅管理员。凭据健康检查用 `/bot alert check`，加 `--probe` 会在线探测各平台 Cookie 是否有效，返回 401 或 403 即需要重新登录。

## 九、对话框指令：日常功能（普通账户可用）

订阅推送：`/订阅 add <平台链接或 platform:kind:id>` 添加订阅，可加"私聊我"改为私聊推送，加 `--digest` 表示只进每天 20:00 的订阅日报；`/订阅 list` 列出；`/订阅 remove|pause|resume|check <编号>` 管理；`/订阅 status` 查看系统状态。支持 B 站（UP 主、直播间、番剧、收藏夹、合集）和小红书创作者，直接粘贴主页或直播间链接即可。点歌：发送 `点歌 <歌名或关键词>`，机器人多平台依次搜索并发歌；输出方式由管理员用 `点歌模式 <卡片|语音|音频|链接>` 设置，可组合如"卡片和语音"，普通用户查询或修改点歌模式都会收到"只有管理员才能修改点歌输出模式。"。表情生成：`表情 <模板名> <文字>`（多段文字用全角竖线分隔），`表情 列表` 列出模板。表情库：`偷表情 [关键词]` 按权重随机发图（冷却时长以 `plugins/bot_unified_runtime/config.py` 的 `bot_meme_library_cooldown_seconds` 现算为准），`表情库统计` 查看库存。

查询类：`天气 <城市>` 查中国气象局天气，同名城市用"省-市"区分（如 河北-大城）；`支持区县 <省>` 列出该省可查区县。`维基 <词条>` 查 MediaWiki 百科。`epic` 查 Epic 本周免费游戏。`历史上的今天` 立即查询；`历史上的今天 设置 8:00` 设置每日推送时间；`状态` 与 `取消` 管理推送。下载：`/bot download <链接>` 下载 B 站、油管、推特、小红书、抖音的视频或音频，单文件大小上限以 `plugins/bot_unified_runtime/domains/files/capabilities/download.py` 读取的 `bot_download_max_bytes` 现算为准，超高分辨率自动降级；注意必须带 /bot 前缀，只写"下载 链接"不会触发下载。链接解析：直接发送平台链接（可混在文字里），机器人自动回复解析信息卡，支持 B 站、抖音、小红书、油管、推特、微博、Lofter、Pixiv、小黑盒、米游社、森空岛、库街区、Lofter、快手、acfun、steam 及音乐平台等；群聊里解析失败会静默。自然语言也能触发：例如"杭州天气怎么样"会归一化为天气查询，"来首晴天"触发点歌，"帮我查一下维基 鸣潮"触发维基，"这周有什么免费游戏"触发 epic，"今天历史上发生了什么"触发历史上的今天。昵称命令：`守岸人帮助`、`岸宝天气 杭州` 这类"昵称+动词"写法等价于对应 /bot 指令，斜杠可省略；未映射的动词（如记忆、配置、暂停）会提示改用 /bot 形式。

## 十、人格与知识库的喂养机制

机器人的人格与知识来自两条通道，机制不同。人格文件（BOT_PERSONA_FILES 指定的 markdown）会以原文整体注入系统提示词，不走向量检索，所以人格文件要精炼；人格文件的内容修改会热生效（按文件修改时间缓存），但修改 `.env` 的文件清单本身需要重启。知识文件（BOT_KNOWLEDGE_FILES 指定的列表）切块尺寸以 `plugins/bot_unified_runtime/config.py` 的知识库切块字段（`bot_knowledge_*`）现算为准，段落块，用本地 Ollama 的 bge-m3 模型向量化（维度以 `plugins/bot_unified_runtime/config.py` 的 `bot_embedding_dimensions` 现算为准）后存入运行时数据目录的 knowledge_embeddings.sqlite3 和 FAISS 索引；对话时按"向量余弦加关键词"双通道检索最相关的少数几块注入。知识文件支持 .md、.txt 和 .docx 三种格式。

向知识库添加新文档的流程：第一步，把文件放到任意位置（推荐 personas/shorekeeper/knowledge/ 目录），支持绝对路径；第二步，把文件路径追加进 `.env` 的 BOT_KNOWLEDGE_FILES（JSON 数组）；第三步，在电脑上运行 `scripts\dev.ps1 -Task knowledge-sync` 分块并向量化入库；第四步，重启机器人，然后对话验证。删除块的语义必须牢记：每次同步以当次传入的全量文件清单为准，清单之外的旧知识块会被全部删除，所以同步永远要传全量清单；机器人运行中进程内存里的清单在重启前是旧的，入库后必须尽快重启，否则旧进程的下一次知识检索会按旧清单把新入库的块删掉。嵌入链路：本地 Ollama（默认 http://127.0.0.1:11434/v1，模型 bge-m3）优先，远程嵌入接口兜底；本地模型名或地址变化会触发全库重新嵌入，不要随意修改 BOT_EMBEDDING_LOCAL_MODELS。

wiki 百科知识库（第二通道）：由外部 Crawl Wiki 项目提供游戏/梗百科文档（根目录以 `plugins/bot_unified_runtime/config.py` 的 `bot_kb_wiki_root` 现算为准，缺省为空、需运维在 `.env` 指向导出目录；文档量级以导出库现算为准），机器人用独立的 kb_wiki_embeddings.sqlite3 向量库承载，与上面的文件知识库互不干扰、检索结果合并注入。日常同步全自动：每日按 BOT_KB_WIKI_SYNC_HOUR:MINUTE（缺省以 `plugins/bot_unified_runtime/config.py` 的 `bot_kb_wiki_sync_hour`/`bot_kb_wiki_sync_minute` 现算为准）增量同步，启动后另有一次补偿同步，无变更时零开销。手动操作：`dev.ps1 -Task kb-sync` 做增量同步加补嵌入；首轮灌库或需全量对账时加 `-KbFull`（流式读 documents.jsonl，首轮全量嵌入耗时以实跑为准，断点续跑可随时中断重跑）；`-KbNoEmbed` 只同步元数据不嵌入。BOT_KB_WIKI_TOPICS 可逗号分隔限定 topic 白名单（如"梗知识,鸣潮"，留空＝不限定，可用 topic 以导出库现算为准）。改嵌入模型后必须用 kb-sync（CLI 路径带自动重置）重跑，机器人进程内不会自动清空旧向量。

## 十一、凭据、Cookie 与密码安全

平台 Cookie 以 Netscape 格式存放在运行时数据目录的 platform_cookies.txt（配置键 BOT_COOKIES_FILE），更换 Cookie 直接覆盖该文件并重启机器人；任何日志、审计和消息输出都不会打印 Cookie 内容。Cookie 健康用 `/bot alert check` 检查过期时间，加 `--probe` 在线探测，401 或 403 即需要重新登录。SnowLuma 协议端首次扫码登录后应在 WebUI（默认 http://127.0.0.1:5099）修改一次 WebUI 密码；SnowLuma 与机器人之间的 WebSocket 访问令牌必须与 `.env.prod` 中 ONEBOT_WS_URLS 里的 token 完全一致；QQ 登录建议使用小号。所有密钥类配置（模型 API 密钥、邮箱授权码等）只存放在本地 `.env`，一律用 `env:变量名` 方式引用，不会回显，不进入文档和日志。邮箱功能（/mail 指令族）仅允许从 Telegram 管理端操作，QQ 端会收到"邮件控制命令仅允许从 Telegram 管理端执行。"。

## 十二、常见问题排查

机器人不回复时的排查顺序：第一步 `/bot status` 看运行状态；第二步 `/bot setup llm` 看七个必配键哪些标红；第三步 `/bot llm` 做真实连接诊断，确认密钥、地址、模型名是否有效；第四步 `/bot why` 查看最近一次回复被哪条规则拦截（如安静时段、限流、群门禁、暂停）；第五步 `/bot recent` 查看最近的诊断、回执与审计摘要。群聊不回复通常是被群策略档位拦截（用 `/bot group list` 查看），或消息既不是命令也没有 @ 和昵称点名。回复内容异常时可用 `/bot context` 查看实际注入的上下文，用 `/bot route <文本>` 验证文本命中的路由。配置改动不生效时先确认是否属于可热更的二十个键，不属于就必须重启机器人。发送失败可查 `/bot queue` 与 `/bot receipt <编号>`。

## 十三、电脑端开发与验证命令

所有开发与验证命令在电脑上从源码目录执行统一入口 `scripts\dev.ps1`，写法为 `powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task <任务名>"`。常用任务：doctor 检查依赖；run 启动机器人；readiness-smoke 聚合本地就绪状态；config-smoke 检查配置；persona-smoke 检查人格与知识来源；context-smoke 生成上下文数字摘要；llm-smoke 检查大模型连通；embedding-smoke 检查嵌入服务；knowledge-sync 分块并向量化知识库（修改外部数据，必须传全量文件清单）；test、lint、typecheck、verify 分别跑回归测试、代码检查、类型检查和总检查。运行数据统一存放在源码区之外的 ChatBot_Runtime 目录（向量库、记忆、日志、下载、Cookie 等），源码目录不应出现数据库和缓存文件。

## 十四、wiki 向量库 ANN 索引的运维（换代守卫、内存门、SQ8 量化、断点续传、一键重建）

本节管的是第十节所述 wiki 百科知识库那条通道的 FAISS 索引：它什么时候可用、问答为什么会变慢、怎么安全重建。判据的权威真身在 `plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py`（ANN 侧常量块与载入判定）和 `plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py`（同步收尾与观测面），本文只给运维口径与读法；**所有数量级、体积、门价一律现算，不要抄本文或任何文档里的数字**（波次全账见 `docs/HANDBOOK.md` §50）。

### 14.1 索引可用性与「暴力扫描」的判别

向量检索有两条腿：ANN 索引可用就走索引，不可用就回落全库暴力扫描（慢而全，绝不给错答案，代价是每条消息多等）。回落的三个判据在载入路径里各自点名：`pair refused`（索引与序列表成对性不齐）、`completeness refused`（索引没追上库侧计数戳）、`coverage refused`（计数戳追上了，但这一代索引没装下发布点之后新提交的嵌入批次）。运维看日志判别，不靠猜。想不启动就能看一眼，跑重启前体检：`../ChatBot_Runtime/venv/Scripts/python.exe scripts/pre_restart_check.py`，读第 13 项 `ann_pair`——PASS＝可用；UNSTAMPED＝从没盖过完备性戳；MEMORY_SKIP＝上一轮被内存门挡下；REFUSED＝这一代不可用；NOT_APPLICABLE＝不适用（没建过）。中间三项的后果是同一条：每条消息付暴力扫描。

### 14.2 换代守卫：为什么「数对上了」仍可能不可用

库侧有一枚计数戳 `knowledge_meta.ann_expected_vector_count`，嵌入和删除都往它记账（对称记账）。于是一夜之内「先删一批、又嵌一批」会把戳拉回原值：索引条数看着正好等于戳，实际却没装下新嵌那批、还留着已删条目的死 id——这就是换代守卫要治的假绿。第二种证明是嵌入代次：`knowledge_meta.ann_embed_generation` 数「已提交的嵌入批次数」，只与向量同事务在唯一写点推进；每代索引在发布时盖上「这一代覆盖证到第几批」（代际证明 `ann_pair_attestation` 的 `embed_generation` 字段）。载入时当前代次超前于盖章值即判拒并回落暴力扫描，等下一次重建。三条语义要记牢：纯删除轮不推进代次（覆盖形状是超集，继续放行）；代际证明被删而代次非零同样判拒（否则「删一行 meta」就同时关掉两道门）；补盖新戳的自证动作不盖代次章。

**今天真值（必须与上段同读）**：生产库里 `ann_embed_generation` 这一行还不存在，代际证明里的盖章值是 0 ⇒ 守卫处于「0 对 0」的惰性在场，要到下一次真补嵌才第一次开口。这是存量兼容的设计形态，不是缺陷，但**也不许当成已在执法**。判它有没有牙的现算尺＝那一行是否非空（非 None）、日志里是否出现过 `coverage refused`。另外只读体检第 13 项目前不读代次（键名册里没这一枚），所以代次判决只能在载入路径的日志里看见，重启前看不到。

### 14.3 内存门与门价：为什么重建会自己停下来

整代重建的常驻内存峰值由索引结构决定，不由批宽决定，所以开火前先量可用物理内存，不足就**不开火**：旧索引原样保留，并在三处留痕——WARNING 日志、`knowledge_meta.ann_build_last_memory_skip` 一行度量（含连续与累计跳过次数）、经 kb-sync 既有告警口发出的五要素诊断卡。要价的算法是「已经吃掉的实账 + 剩余条数的模型价」，并按索引存储位宽派生；早先版本把首批实测斜率线性外推到剩余全部，会报出数倍于真实峰值的要价，得出「任何机器都永远不许开火」的死锁结论，已改。被内存门挡下**不**放行完备性闸，检索仍走暴力扫描。确要在低内存硬跑：`powershell -File scripts/dev.ps1 -Task kb-sync` 加 `--ann-force-low-memory`（显式越门会另记痕，越门中的轮次仍可取消）。这些阈值全是模块常量、不是配置键——要改走代码评审，不走 `.env`。

### 14.4 SQ8 量化：为什么现在较小的可用内存也能重建

索引存储已从全精度换成 SQ8 量化（每维一个字节），体积约为原来的三成，内存门要价随之下降。代价是检索结果里约百分之一点几的 top-4 槽位与全精度不同（并列近邻换位），属在册代价，不是链路故障。位宽与量化器类型是成对在册的两枚常量（`_ANN_INDEX_BYTES_PER_DIM` 与 `_ANN_INDEX_QUANTIZER_NAME`），必须一起改，只改一枚会被回归拦下。图结构参数（HNSW 连接数等）刻意没动——一旦变了，那份「三成体积、约一点几成差异」的对照实测就失去前提，得重跑离线对照再改注释。

### 14.5 断点续传：为什么中途被杀不再从第 0 条重跑

整代重建按 rowid 顺序分段扫描，每推进一个复检窗就把半成品落到索引同目录的两枚 `.wip-` 前缀文件，外加 `knowledge_meta.ann_build_checkpoint` 一行（记已装条数、游标 rowid、代次、计数戳、维数、时刻）。**被内存门收火之前也先落一次**，所以每一轮至少推进一个窗，多轮循环能把大库一轮一轮啃完；发布成功后检查点三件套自动清除。续跑只在「代次与计数戳都没变」时进行，任一枚变了就丢弃并从第 0 条重跑——这是刻意的：期间补嵌会让续跑光标永久漏掉新写入的行，期间删除会让半成品留着死 id。半成品用前缀命名，与线上两枚零共前缀，任何按线上名展开的清理或通配都不会误认。它是**纯加速器**，不是任何一道门的旁路：内存门、完备性闸、代次闸的判据一字未动，发布点仍是唯一提交点。

运维读法：重建反复停在中途却不见进展 ⇒ 看 `ann_build_last_memory_skip` 的读数与日志里的中途收火行（它会点名下一轮从哪个 rowid 续装）；反复从第 0 条重跑 ⇒ 多半是这期间爬虫还在补嵌或删行（代次或戳不等），换安静窗再跑。

### 14.6 关键词通道的喂口（FTS）

向量之外的关键词兜底通道此前只在「有 ANN 重建的那一夜」才被建；零变更夜整段跳过重建，于是错过一次就每夜都不建、关键词通道恒空。现在改在 kb-sync 收尾**无条件幂等 ensure 一次**（签名对上就快返回），覆盖夜间定时任务、启动补偿与命令行三条路径。同步结果与 `kb_sync_last_summary` 里能看到三枚观测键 `fts_built`、`fts_rows`、`fts_signature`，公开摘要常驻一行「关键词通道」实况，建不成会点名（`fts5 unavailable`）不再静默。那次全表计数只在维护线程做，绝不放进对话请求路径。命令行手工触发同第十节：`dev.ps1 -Task kb-sync`（首轮灌库或全量对账加 `-KbFull`，只同步元数据加 `-KbNoEmbed`）。

### 14.7 一键重建脚本的用法与验收判据

在册重启口＝`ChatBot_Runtime/restart_bot.ps1`。ANN 整库重建＝`ChatBot_Runtime/rebuild_ann_kb_wiki.ps1`，六步：预检（向内存门要价、核对盘量与空闲）→ 停 bot → 保险目录 sha256 对账后**把现索引搬走**（是搬走不是删除，保险目录在仓外，结束时打印路径）→ 跑 kb-sync **多轮自动续跑**直到索引落地（轮数有上限）→ 验收探针 → 带 stdout/stderr 重定向起 bot，结束时弹 Windows 提示。每轮一份独立 UTF-8 日志（`ChatBot_Runtime/logs/rebuild_ann_kb_wiki_<UTC 时间戳>.log`）。只想看数字不动任何东西，加 `-CheckOnly` 只跑预检那一步。脚本本体在 ChatBot_Runtime 内、不入源码仓，正文只准 ASCII（PowerShell 5.1 读无 BOM 的 UTF-8 脚本会静默不执行）。

**验收判据（现算，别抄文档数字）**：探针一次打出 `embed_generation`、代际证明里的盖章值、`expected_stamp`、`faiss_ntotal`、`fts_rows`、`chunks`、已嵌入数这一组读数。合格线＝`faiss_ntotal` 与计数戳、库侧条数、已嵌入数四值相等，且 `fts_rows` 同为该量级；起 bot 后判活以 netstat 为准＝8080 处于 LISTENING 且 3001 已连，两者同属新起的进程。若 `embed_generation` 仍为空（None）而盖章值是 0，说明换代守卫还在惰性在场状态，需要一次真补嵌才开口——这不算失败，但也不许叙述成已在执法。若探针报 `UNREADABLE`，索引文件本身坏了：旧那对仍在保险目录里，按脚本末行打印的路径取回。

## 十五、每天把上游百科的新内容并进知识库（日增量链）

二游每个版本都会更新百科，而且**是慢慢加进已有词条**的——今天加一句、明天补一张表。所以日增量链要抓的是「已被编辑的旧页」，不是「本地还没有的页」。这条区别决定了用哪个入口：

- ✅ 现役入口＝`incremental_daily_runner.py`（爬虫仓根目录）。它按 `JOBS` 表逐条 job（枚数与内容以该文件为准，本文不手写）走「读各源全站变更流 → 只抓变更涉及的页 → 合进该主题的正卷 → 末尾自动导出知识库」。变更流里既有新页也有旧页的编辑，正是「慢慢加」这一形态。
- ❌ 不要用 `recrawl_pipeline.py --stage crawl` 当日常入口：那一腿是**补缺口**（`resume=True`，skip 的含义是「本地已有」），已有词条被上游改了内容它一条也不会重取，一夜下来报「全部 skip」而知识库零变化，看着绿、实际瞎。它的位置是首轮与全量重刷。

日常编排件＝`D:\Coding\03_Data\daily_kb_update\daily_update.ps1`，缺省**演练**（跑的是夜间 runner 自己的 `--dry-run`：打印每条 job 的真命令行，零子进程、零请求），加 `-Execute` 才真爬真发布。五段：预检（盘量下限、锁、代理端口与上游域名的只读可达性）→ 语料快照册子 + 自对账 → 夜间 runner → 交付门（`recrawl_pipeline --stage verify`，只读本地正文，零网络）→ 验收（`kb_export_cli --check --json`）。发布段是** repair 位**：runner 自己已经发布了，这一段只在它没报绿色导出时才补一次，所以一夜不会导出两遍。

计划任务＝`ChatBot_DailyKB_Update`，每天 04:20 跑 `-Execute`，注册件 `install_daily_task.ps1` 同目录、可重复执行（同名 `-Force` 原地替换，不删任何东西）。选 04:20 的两个理由：bot 自己的知识库同步在 23:40，两条链不许同时读写同一份发布件（23:00 那档撞过，在册缺陷）；而 04:20 爬完发布出来的东西，当晚 23:40 bot 就吃得到。机器当时 asleep 或关机 ⇒ `StartWhenAvailable` 回来即补跑；两次触发重叠 ⇒ 后到者直接退出。

**读法（判断「昨天到底更新没」）**：
- 每次跑完落一份 `logs\daily-<时刻>.summary.txt`，里头有各段退出码、`documents/added/changed/removed`、发布件体积与 sha256、盘量；同时弹一次 Windows 提示（只有真跑才弹，演练不抢焦点）。
- 夜间 runner 的 rc 是**有问题的 job 条数**，不是「链断了」。判发布与否只认它自己打的结论行 `done: N/M games ok, K failed, kb_export=OK|FAILED`。萌百与 fandom 那批 job 需要本机代理（127.0.0.1:7890）在线；代理不在 ⇒ 一夜 K 很大而 `kb_export=OK`，这属于「降级」不是「失败」，摘要与提示都会点名。
- 逐主题的日志在爬虫仓 `logs\incremental\<日期>_<主题>.log`，交付门逐路输出在 `crawl_output\pipeline_logs\`。

手工补跑（不等明天 04:20）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Coding\03_Data\daily_kb_update\daily_update.ps1" -Execute
```

想先看清今天会动什么，去掉 `-Execute` 即可（演练）。

向量嵌入与 ANN 换代仍按第十四节，由她本地跑——日增量链只负责把语料与发布件推到最新，一夜新增的条数量级很小，bot 的 23:40 同步会把嵌入顺手补上；ANN 索引不需要每天重建，攒到一轮明显涨量或门报短装时再走那把脚本。
