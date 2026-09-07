# 守岸人机器人运维知识手册（AI 知识库专用）

本文档是守岸人 QQ 机器人（NoneBot2 + 统一运行时插件 bot_unified_runtime）的运维说明书，专门写入机器人的向量知识库。当用户询问"怎么加模型、某指令怎么用、为什么配置不就绪、机器人为什么不回复"等问题时，机器人应以本文档的事实为依据作答。文档约定：所有命令都在 QQ 对话框输入；带 `/bot` 前缀的指令多数仅管理员可用；配置键写法为 `.env` 中的大写形式，修改 `.env` 后必须重启机器人才生效。

## 一、机器人与权限体系

机器人的人格是守岸人（昵称岸宝），基于 NoneBot2 框架，通过 NapCat 协议端接入 QQ，运行时插件为 plugins/bot_unified_runtime。发送者被划分为五种角色：user（普通）、trusted（受信任）、enterprise（企业）、admin（管理员）、blocked（黑名单）。角色由发送者 ID 决定，名单配置在 `.env` 中，多个角色可以叠加。

管理员由 `.env` 中的 BOT_ADMIN_USER_IDS 决定（QQ 管理员）和 BOT_TELEGRAM_ADMIN_USER_IDS（Telegram 管理员）。取值可以是 JSON 数组（如 `["123","456"]`）或分号、逗号分隔的字符串（如 `123;456`）。把自己设为管理员的方法：编辑 `.env`，把你的 QQ 号加进 BOT_ADMIN_USER_IDS，然后重启机器人。注意：BOT_ADMIN_USER_IDS 不支持热更，不能用 `/bot runtime set` 在线修改；NoneBot 官方的 SUPERUSERS 配置在本插件中不生效，写了也没有用。设置是否成功，可以用 `/bot roles` 或 `/bot recent` 验证：能返回数据说明管理员身份已生效。

普通账户触发管理员指令时，不会执行任何操作，只会收到固定的拒绝回执。例如诊断类指令回执为"只有管理员可以查看运行时排障记录。"，运行时管理类指令回执为"该命令只允许管理员使用。"，日志类回执为"只有管理员才能查询运行时日志。"。`/bot 帮助` 总览对普通账户只显示公开功能主题（订阅、点歌、表情、天气、维基、历史上的今天、下载、昵称、链接、Epic），管理员登录后才能看到全部诊断主题。

## 二、大模型接入：七个必配键

机器人对话由 OpenAI 兼容接口的大模型驱动，主配置有七个必配键，全部在 `.env` 中设置。第一，BOT_CHAT_PROVIDER：供应商类型，填 openai_compatible 表示真实模型，填 static 表示本地占位模型（不联网）。第二，BOT_CHAT_MODEL：对话使用的模型名字符串，必须填供应商提供的真实模型名，不能留占位符。第三，BOT_CHAT_API_KEY：API 密钥，可以填真实密钥，更安全的做法是填 `env:变量名` 引用同文件里另一个环境变量；密钥永远不会被回显到任何输出里。第四，BOT_CHAT_BASE_URL：OpenAI 兼容接口地址，必须以 http(s):// 开头，一般以 /v1 结尾，地址里不允许内嵌账号密码。第五，BOT_CHAT_TEMPERATURE：采样温度，范围 0.0 到 2.0，数值越高回复越随机。第六，BOT_CHAT_MAX_TOKENS：单次回复的输出上限，大于等于 0 的整数，0 表示不设上限。第七，BOT_CHAT_TIMEOUT_SECONDS：单次请求超时秒数，必须是正数。

配置是否就绪由 `/bot config`（管理员）检查。判定规则：API 密钥为空或等于占位符（如 your-api-key、replace-me、test-key 等）视为缺失；模型名为空或占位符（如 your-model-name、replace-me 等）视为缺失；BASE_URL 缺失、协议不对或内嵌账号密码都会报错，其中内嵌账号密码会报 openai_base_url_unsafe，属于安全问题必须移除。温度、max_tokens、超时超出合法范围也会报对应错误。全部通过且 provider 为 openai_compatible 时状态为 ready；有错误为 blocked；没有错误但仍是 static 占位供应商则为 local_only。接入完成后用 `/bot llm`（管理员）做一次真实连接诊断，它会用当前配置发起一次短调用并报告结果，不会修改任何配置。

## 三、多供应商注册表与故障转移队列

除主配置外，机器人支持多个模型供应商并存，注册表配置键为 BOT_MODEL_REGISTRY（JSON 对象）。每个条目包含：id（自定义名称）、model（模型名）、base_url（接口地址）、api_key（密钥，支持 env:变量名 引用，也支持列表形式实现同一模型多密钥轮流转移）、tags（档位标签）、priority（全局优先级，整数，1 到 999，数字越小越优先被调用）。密钥本身存放在 BOT_API_KEY_开头的环境变量里（如 BOT_API_KEY_QIANQIANYE），注册表中用 `env:` 引用，绝不写明文。

故障转移队列的排序规则是：候选为注册表中所有 tags 不含 manual 的条目，按 priority 从小到大排列。每次生成时先按当前消息挑档位：消息超过 300 字，或包含"教程、排查、分析、翻译、总结、比较、代码、配置、部署"等关键词时判定为复杂任务，先尝试 strong 档模型，fast 档排在后；普通消息则先尝试 fast 档。快速模式（BOT_CHAT_FAST_MODE 开启时）会把候选截断为 BOT_CHAT_FAST_MAX_CANDIDATES 个（0 表示不限制）。整个转移过程受 BOT_CHAT_FAILOVER_MAX_SECONDS（默认 45 秒）和请求级总预算双重限制，防止连续失败把响应拖到分钟级。

调用时的转移规则：按队列顺序逐个尝试，每个候选先试它的第一个密钥，失败再试下一个密钥（如果配了多个），整个候选失败后切换到队列里的下一个模型。缺少密钥的候选会被直接跳过（记为 config_missing），不会中断流程。如果管理员用 `/bot model set <id>` 手动指定了模型，则先试指定模型，失败后仍按队列顺序转移其余候选。转移顺序和每次尝试结果可以用 `/bot model list` 查看。

## 四、大模型的增加、修改、删除、启用与禁用

新增模型供应商用命令 `/bot model add <id> model=<模型名> base_url=<接口地址> key=<API密钥或env:变量名> [tags=fast,strong] [group=<分组>] [priority=<数字>]`。参数含义：id 是你给模型起的名字，之后 set、update、remove 都用它；model 填供应商提供的模型名，原样填写；base_url 必须以 /v1 结尾；key 填 API 密钥或 `env:变量名` 引用（更安全，密钥不会回显）；tags 可选，逗号分隔，fast 表示日常档、strong 表示复杂任务档、vision 或 multimodal 或 vlm 表示允许直接接收图片；priority 可选，越小越先被调用，省略默认 100。完整示例：`/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=env:BOT_API_KEY_MYAPI tags=fast,strong priority=1`。常见错误：等号两边加了空格会报"参数格式应为 键=值"；漏写 model= 或 base_url= 会提示必填。新增完成后立即生效，无需重启，并自动进入故障转移队列。

修改模型参数用 `/bot model update <id> <键=值 ...>`，只写要改的项，例如 `/bot model update myapi key=env:BOT_API_KEY_NEW priority=3`，可修改的键有 model、base_url、key、group、tags、priority。只调故障转移顺序用 `/bot model priority <id> <数字>`。手动切换当前模型用 `/bot model set <id|auto>`，auto 表示回到自动选型；`/bot model reset` 清除手动指定回到自动选型。删除自定义模型用 `/bot model remove <id>`，注意来自 .env 的 BOT_MODEL_REGISTRY 条目不能删除，只能用 update 覆盖其参数。

需要特别说明"启用和禁用"：机器人没有独立的模型启用/禁用开关。要把一个模型移出自动故障转移队列但保留手动可选，用 `/bot model update <id> tags=manual`，打上 manual 标签后它不再参与自动排队，但仍可用 `/bot model set <id>` 手动指定使用；要恢复参与自动队列，用 `/bot model update <id> tags=fast,strong` 把标签改回来即可。要彻底删除则用 remove（仅限运行时新增的条目）。预设名（BOT_MODEL_PRESETS 中定义的短名，如 terra、luna）只能手动指定，永远不会自动参与排队。

## 五、模型相关辅助功能

图片识别（视觉）模型独立管理：`/bot model vision list` 查看候选与开关；`/bot model vision add <id> model=<视觉模型> base_url=<接口> key=<密钥> [priority=<n>]` 新增；update、priority、remove 同主模型规则；`/bot model vision mode relay|direct` 切换模式，relay 表示先用视觉模型把图片转成文字，direct 表示把图片直接传给 tags 含 vision/multimodal/vlm 的主模型，失败只回退一次 relay。识别开关用 `/bot runtime set BOT_VISION_ENABLED true|false` 热更。

推理强度用 `/bot model think <off|low|medium|high>` 设置，off 表示不向模型发送 reasoning_effort 字段。联网搜索用 `/bot model search <on|off>` 热切换。Token 用量用 `/bot model usage [today|YYYY-MM-DD]` 查询，按模型分组汇总输入、输出和总 Token。分时段自动换模型用 `/bot runtime set BOT_MODEL_SCHEDULE <JSON>`，例如 `/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}`，支持跨零点时间窗，窗口外自动回到正常选型。

## 六、运行时参数热更

管理员可用 `/bot runtime set <键> <值>` 在线修改参数并立即生效，无需重启；`/bot runtime get <键>` 读取当前值（标注是覆盖值还是 .env 默认）；`/bot runtime list` 列出全部覆盖项；`/bot runtime reset [键]` 清除覆盖（省略键名则全部清除）。覆盖值持久保存在运行时数据目录的 runtime_settings 实例文件中。可以热更的键共二十个：BOT_CHAT_TEMPERATURE（温度 0-2）、BOT_CHAT_MAX_TOKENS（回复上限）、BOT_CHAT_MODEL（主模型）、BOT_CHAT_REASONING_EFFORT（推理强度，可填空、off、low、medium、high）、BOT_TRANSPORT_TIMEOUT_SECONDS（发送硬超时，0 到 600 秒之间，默认 15）、BOT_MODEL_SCHEDULE（分时段换模型 JSON）、BOT_REPLY_MAX_CHARS_PER_MESSAGE（单条消息字数上限）、BOT_REPLY_DETAIL（详略档位，详细、精简、默认）、BOT_MUSIC_MODE（点歌输出模式）、BOT_MEME_SEARCH_ENABLED、BOT_WEB_SEARCH_ENABLED、BOT_WEB_SEARCH_ADMIN_NOTICE、BOT_PERSONA_ACTION_BRACKETS、BOT_VISION_ENABLED、BOT_VISION_MODE（relay 或 direct）、BOT_CONTENT_VIDEO_AUTO_SEND（解析视频直发开关）、BOT_GROUP_BLACK1、BOT_GROUP_BLACK2、BOT_GROUP_WHITE1、BOT_GROUP_WHITE2（群策略四档）。

不在这二十个键白名单里的配置（例如管理员名单、人格文件清单、各类数据库路径），都只能改 `.env` 后重启机器人生效。多实例部署时可用 `--instance <名称>` 指定目标实例，`/bot runtime instance list` 列出已创建的实例设置文件。昵称也可以热管理：`/bot runtime nickname add|remove|list <昵称>`，添加后立即参与昵称触发。

## 七、对话框指令：系统与诊断类

`/bot status` 查看运行状态摘要（所有人可用）。`/bot why [编号]` 解释最近一次回复的路由与决策，编号可选。`/bot receipt <编号>` 查询发送回执状态（管理员）。`/bot audit <请求编号>` 查询审计事件（管理员）。`/bot recent [数量]` 查看最近诊断、回执与审计的排障摘要，数量 1 到 20，默认 5（管理员）。`/bot queue` 查看发送队列的待发、处理中、重试、失败计数（管理员）。`/bot logs [级别] [数量]` 查看运行时事件日志，级别可选 debug、info、warning、error，默认 info；数量 1 到 200，默认 50；两个参数先级别后数量（管理员）。`/bot parse [数量]` 查看最近的链接解析历史，数量 1 到 100，默认 10。`/bot route <文本>` 判定一段文本会命中哪条路由；`/bot routes` 打印全部路由表。长期记忆用 `/bot memory add <内容>` 添加（建议不超过 1200 字）、`/bot memory list` 列出、`/bot memory delete <fact_id>` 删除，记忆按发送者与会话隔离。

深度诊断指令（均管理员）：`/bot context [文本]` 展示一条消息实际注入给模型的上下文构成；`/bot dialogue [文本]` 本地跑一轮对话诊断，不影响线上状态；`/bot llm` 做一次真实模型连接诊断；`/bot setup llm` 输出七个必配键的接入检查卡（含每项的取值范围与当前值，密钥不展示）；`/bot config` 做配置就绪体检（脱敏）；`/bot readiness` 聚合环境、配置、上下文、对话链路的总体就绪状态；`/bot persona` 自检人格材料强度与语气规则；`/bot roles` 查看各角色数量摘要（不含具体 ID）；`/bot history clear` 清空本会话最近对话；`/bot pause` 与 `/bot resume` 软暂停与恢复全部回复（暂停期间 status、help、why、receipt、audit、recent、queue、context、llm、setup、config、readiness、dialogue、roles、history 等控制类指令仍可用）；`/bot search <问题>` 验证联网检索链路。帮助本身用 `/bot help <主题>` 或 `/bot 帮助 <主题>` 查看某主题详情。

## 八、对话框指令：运行时管理与群策略

`/bot group` 系列管理群聊回复策略，分四个档位：black1 完全静默，black2 仅被 @ 或显式命令时回复，white1 正常回复加自然提问，white2 仅被 @ 时回复。用法：`/bot group list` 查看各档位名单；`/bot group add <档位> <群号>` 加入（群号可一次填多个）；`/bot group del`、`/bot group set`（覆盖）、`/bot group clear <档位>`（清空）。全部仅管理员。

私聊里机器人对所有消息放行；群聊里只有命令、昵称命令、被 @ 或写昵称点名才会触发回复，其余消息静默观察（受四档黑白名单约束）。群聊被门禁拒绝时机器人保持静默；限流触发时回复"当前会话/目标/整体回复过于频繁，已临时降频。"；安静时段（BOT_QUIET_HOURS 配置，默认 00:00 到 06:00，管理员角色默认绕过）回复"当前处于安静时间，已暂停非必要回复。"。回复详略档位用 `/bot reply <详细|精简|默认>` 调整，别名科普、详尽等于详细，简洁等于精简，自动等于默认；无参数查看当前档位；仅管理员。凭据健康检查用 `/bot alert check`，加 `--probe` 会在线探测各平台 Cookie 是否有效，返回 401 或 403 表示需要重新登录。

## 九、对话框指令：日常功能（普通账户可用）

订阅推送：`/订阅 add <平台链接或 platform:kind:id>` 添加订阅，可加"私聊我"改为私聊推送，加 `--digest` 表示只进每天 20:00 的订阅日报；`/订阅 list` 列出；`/订阅 remove|pause|resume|check <编号>` 管理；`/订阅 status` 查看系统状态。支持 B 站（UP 主、直播间、番剧、收藏夹、合集）和小红书创作者，直接粘贴主页或直播间链接即可。点歌：发送 `点歌 <歌名或关键词>`，机器人多平台依次搜索并发歌；输出方式由管理员用 `点歌模式 <卡片|语音|音频|链接>` 设置，可组合如"卡片和语音"，普通用户查询或修改点歌模式都会收到"只有管理员才能修改点歌输出模式。"。表情生成：`表情 <模板名> <文字>`（多段文字用全角竖线分隔），`表情 列表` 列出模板。表情库：`偷表情 [关键词]` 按权重随机发图（有 20 秒冷却），`表情库统计` 查看库存。

查询类：`天气 <城市>` 查中国气象局天气，同名城市用"省-市"区分（如 河北-大城）；`支持区县 <省>` 列出该省可查区县。`维基 <词条>` 查 MediaWiki 百科。`epic` 查 Epic 本周免费游戏。`历史上的今天` 立即查询；`历史上的今天 设置 8:00` 设置每日推送时间；`状态` 与 `取消` 管理推送。下载：`/bot download <链接>` 下载 B 站、油管、推特、小红书、抖音的视频或音频，单文件上限 1GB，超高分辨率自动降级；注意必须带 /bot 前缀，只写"下载 链接"不会触发下载。链接解析：直接发送平台链接（可混在文字里），机器人自动回复解析信息卡，支持 B 站、抖音、小红书、油管、推特、微博、Lofter、Pixiv、小黑盒、米游社、森空岛、库街区、Lofter、快手、acfun、steam 及音乐平台等；群聊里解析失败会静默。自然语言也能触发：例如"杭州天气怎么样"会归一化为天气查询，"来首晴天"触发点歌，"帮我查一下维基 鸣潮"触发维基，"这周有什么免费游戏"触发 epic，"今天历史上发生了什么"触发历史上的今天。昵称命令：`守岸人帮助`、`岸宝天气 杭州` 这类"昵称+动词"写法等价于对应 /bot 指令，斜杠可省略；未映射的动词（如记忆、配置、暂停）会提示改用 /bot 形式。

## 十、人格与知识库的喂养机制

机器人的人格与知识来自两条通道，机制不同。人格文件（BOT_PERSONA_FILES 指定的 markdown）会以原文整体注入系统提示词，不走向量检索，所以人格文件要精炼；人格文件的内容修改会热生效（按文件修改时间缓存），但修改 `.env` 的文件清单本身需要重启。知识文件（BOT_KNOWLEDGE_FILES 指定的列表）会被切成约 600 字的段落块，用本地 Ollama 的 bge-m3 模型（1024 维）向量化后存入运行时数据目录的 knowledge_embeddings.sqlite3 和 FAISS 索引；对话时按"向量余弦加关键词"双通道检索最相关的少数几块注入。知识文件支持 .md、.txt 和 .docx 三种格式。

向知识库添加新文档的流程：第一步，把文件放到任意位置（推荐 personas/shorekeeper/knowledge/ 目录），支持绝对路径；第二步，把文件路径追加进 `.env` 的 BOT_KNOWLEDGE_FILES（JSON 数组）；第三步，在电脑上运行 `scripts\dev.ps1 -Task knowledge-sync` 分块并向量化入库；第四步，重启机器人，然后对话验证。删除块的语义必须牢记：每次同步以当次传入的全量文件清单为准，清单之外的旧知识块会被全部删除，所以同步永远要传全量清单；机器人运行中进程内存里的清单在重启前是旧的，入库后必须尽快重启，否则旧进程的下一次知识检索会按旧清单把新入库的块删掉。嵌入链路：本地 Ollama（默认 http://127.0.0.1:11434/v1，模型 bge-m3）优先，远程嵌入接口兜底；本地模型名或地址变化会触发全库重新嵌入，不要随意修改 BOT_EMBEDDING_LOCAL_MODELS。

## 十一、凭据、Cookie 与密码安全

平台 Cookie 以 Netscape 格式存放在运行时数据目录的 platform_cookies.txt（配置键 BOT_COOKIES_FILE），更换 Cookie 直接覆盖该文件并重启机器人；任何日志、审计和消息输出都不会打印 Cookie 内容。Cookie 健康用 `/bot alert check` 检查过期时间，加 `--probe` 在线探测，401 或 403 表示需要重新登录。NapCat 协议端首次扫码登录后应在 WebUI（默认 http://127.0.0.1:6099）修改一次 WebUI 密码；NapCat 与机器人之间的 WebSocket 访问令牌必须与 `.env.prod` 中 ONEBOT_WS_URLS 里的 token 完全一致；QQ 登录建议使用小号。所有密钥类配置（模型 API 密钥、邮箱授权码等）只存放在本地 `.env`，一律用 `env:变量名` 方式引用，不会回显，不进入文档和日志。邮箱功能（/mail 指令族）仅允许从 Telegram 管理端操作，QQ 端会收到"邮件控制命令仅允许从 Telegram 管理端执行。"。

## 十二、常见问题排查

机器人不回复时的排查顺序：第一步 `/bot status` 看运行状态；第二步 `/bot setup llm` 看七个必配键哪些标红；第三步 `/bot llm` 做真实连接诊断，确认密钥、地址、模型名是否有效；第四步 `/bot why` 查看最近一次回复被哪条规则拦截（如安静时段、限流、群门禁、暂停）；第五步 `/bot recent` 查看最近的诊断、回执与审计摘要。群聊不回复通常是被群策略档位拦截（用 `/bot group list` 查看），或消息既不是命令也没有 @ 和昵称点名。回复内容异常时可用 `/bot context` 查看实际注入的上下文，用 `/bot route <文本>` 验证文本命中的路由。配置改动不生效时先确认是否属于可热更的二十个键，不属于就必须重启机器人。发送失败可查 `/bot queue` 与 `/bot receipt <编号>`。

## 十三、电脑端开发与验证命令

所有开发与验证命令在电脑上从源码目录执行统一入口 `scripts\dev.ps1`，写法为 `powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task <任务名>"`。常用任务：doctor 检查依赖；run 启动机器人；readiness-smoke 聚合本地就绪状态；config-smoke 检查配置；persona-smoke 检查人格与知识来源；context-smoke 生成上下文数字摘要；llm-smoke 检查大模型连通；embedding-smoke 检查嵌入服务；knowledge-sync 分块并向量化知识库（修改外部数据，必须传全量文件清单）；test、lint、typecheck、verify 分别跑回归测试、代码检查、类型检查和总检查。运行数据统一存放在源码区之外的 ChatBot_Runtime 目录（向量库、记忆、日志、下载、Cookie 等），源码目录不应出现数据库和缓存文件。
