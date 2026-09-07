# ChatBot 最终收尾交接文档

> 版本：alpha 收尾交接
> 日期：2026-09-07
> 工作区：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
> 当前分支：`v0.0.1-alpha.1`
> 交接原则：以本文件为最终状态说明；早期文档中的 309/343 项测试数字、旧的 4096/8192 描述均以本文件为准。

## 0. 一句话结论

当前源码已经具备可运行的 NoneBot + OneBot V11 后端聊天 alpha 基础：本地后端主链路、真实 LLM 配置诊断、文本与图片 QQ 实机回复（以用户实测为依据）、引用/转发/混合消息归一化、模型故障转移、Wiki 基础检索、文件读取/生成、安全边界基线和离线统一出站测试均已建立。

它还不是最终生产版。最重要的未完成项是：完整所有能力统一出站、Telegram 评论树/文件 API、人格 Prompt 重构、结构化世界观与 Evidence Ledger、长时记忆审批写入、群聊公共状态、生成文件安全扫描、真实搜索四家逐家验收、NapCat poke 实机验收、运行数据迁移清理和新的 alpha 备份包。

## 1. 不可违反的约束

- 本轮没有 Git push；没有向 `origin` 推送。
- 没有发送真实 QQ/Telegram 消息；离线 smoke 使用 fake transport。
- 没有调用新的真实付费 LLM；`backend-smoke` 使用 `static` provider。
- 没有修改原始人格源文件和世界观源文件。
- 没有删除 Runtime 中的 SQLite、FAISS、向量库、记忆、Cookie、订阅、媒体缓存、日志或虚拟环境。
- 不得执行 `git reset`、`git checkout --`、`git add -A`、删除活动数据或把密钥写入聊天。
- 当前工作区有历史混合脏变更，不能把整个工作区直接当成“本轮干净补丁”。

## 2. 最终验证证据

### 2.1 最后一次完整 verify

执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Task verify
```

结果：

- `docs-check passed`
- 发现 `bot_unified_runtime`，309 个本地插件 Python 文件
- `352 passed, 1 warning`
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 174 source files`
- 唯一 warning 是上游 `nonebot.adapters.mail` 的 Pydantic V2 弃用提示，不是本项目测试失败。

### 2.2 最后一次 backend-smoke

结果为：

- `ok=true`
- `provider=static`
- `model=static`
- `receipt_state=sent`
- `web_search_used=false`
- `chat_plain_text:v1`
- 明确提示“未调用外部模型”。

这只证明离线后端执行单元可运行，不证明真实模型、真实搜索或 NapCat 在线。

### 2.3 最后一次 backend-base-smoke

结果为 `ok=true`，包括：

- NoneBot、OneBot adapter、插件导入成功；
- `matcher_count=21`；
- persona=`shorekeeper`；
- persona files=1、knowledge files=17，缺失数为 0；
- `chat_provider=openai_compatible`、`chat_model=gpt-5.6-terra`、key 仅显示 `set`；
- fake OneBot 的 text/image/json/mixed/fallback/forward 与错误分类通过；
- `napcat_connected=false`、`real_transport_used=false`，即没有假装完成真实连接。

### 2.4 doctor

最后一次 doctor 为 `ok=true`：

- Python 3.12.10；
- NoneBot、OneBot、APScheduler、插件导入成功；
- `nb_cli=ok`；
- `ready_for_nonebot_run=true`；
- 当前 provider=`openai_compatible`；
- 当前配置模型=`gpt-5.6-terra`；
- key 只显示 `set`，绝不在文档中记录值。

### 2.5 runtime-layout

当前仍为失败：

- 源码区存在 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\data` 运行产物；
- 检测到 156 个 Python 缓存路径。

这项没有强行清理，因为当前工作区存在历史活动数据，且删除可能破坏运行状态。后续必须先做 manifest、hash、SQLite integrity_check、备份验证，再清理。

## 3. 当前真实主链路

```text
NapCat OneBot V11 WebSocket
  -> NoneBot OneBot Adapter
  -> NoneBot Event
  -> _incoming_from_nonebot_event()
  -> IngressGateway
  -> IncomingMessage
  -> 路由/权限/限流/安静时间/群策略
  -> RuntimePipeline
  -> chat / wiki / parser / download / subscribe 等能力
  -> CapabilityResult
  -> Review/纯文本整理/文件附件投影
  -> SendRequest
  -> SQLite 或内存 SendQueue
  -> UnifiedDeliveryGateway
  -> sender.onebot / sender.nonebot
  -> OneBot API
  -> NapCat
  -> QQ
```

关键代码：

- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\bot.py`：NoneBot 启动入口。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\__init__.py`：handler、事件转换、能力装配、发送调度。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\runtime\ingress.py`：`IngressGateway`。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\runtime\pipeline.py`：统一决策与能力执行主流水线。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sender\gateway.py`：`UnifiedDeliveryGateway`。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sender\onebot.py`：OneBot 消息段、文件上传、回执和失败分类。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sender\queue.py`：队列。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sender\receipts.py`：发送回执。

### 已完成的统一边界

- 主聊天能力进入统一入站标准化和 RuntimePipeline。
- 主聊天、图片/表情聊天和主要文本能力通过统一能力结果和发送请求。
- 普通文本经过统一 OneBot/NoneBot sender。
- `text/image/json/mixed/forward` 有离线传输测试。
- 用户已经实测 QQ 纯文本、图片能够回复。

### 仍未做到“所有能力 100% 统一”的部分

- 文件下载、文件上传必须调用 OneBot `get_file/download_file/upload_*`，这些是平台副作用，当前仍存在 handler 中的直接 `bot.call_api()`；它们还没有抽成独立 `FileTransferGateway`。
- 订阅推送存在独立投递分支，幂等、回执和审计还没有完全收敛到同一个文件传输/消息出站合同。
- Telegram 文件、评论区 API 补拉尚未接入统一主出站。
- 跨平台原始事件幂等表、result-unknown 全局恢复机制、统一副作用确认策略尚未完成。

## 4. 已完成内容清单

### 4.1 输出预算和回答完整度

- `BOT_CHAT_MAX_TOKENS` 默认上限为 `65538`。
- `BOT_CHAT_FAST_MAX_TOKENS` 默认上限为 `65538`。
- 合法范围为 `0..65538`，0 表示不向兼容接口发送 `max_tokens`。
- 65538 是上限，不是每条消息强制生成 64K。
- 知识、游戏、人物、组织问题会优先要求模型回答：是什么、核心内容、当前状态、相关人物/组织关系、与问题最相关的部分。
- 普通聊天不会因为上限提高而强制写成长文。
- 当前本地 `.env` 已设置 65538，且 `BOT_CHAT_FAST_MODE=false`，便于验收知识库、人格和检索能力。
- `.env.example` 已去除重复 token 配置，只保留一组权威的 65538 设置。

### 4.2 消息输入

新增：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\message_context.py`

支持归一化：

- 文本；
- OneBot quote；
- forward/chat history；
- 图片；
- Emoji；
- QQ face/mface/marketface/sticker；
- 文件；
- record/audio；
- video；
- Telegram 已有 reply/thread 字段。

`IncomingMessage` 增加：

- `reply_to_text`；
- `thread_id`；
- 混合消息段投影。

安全边界：

- 引用内容明确放入 `[引用内容]` 边界；
- 转发内容明确放入 `[转发/聊天记录]` 边界；
- 附件不会伪装成系统指令；
- URL 不会被当成本地文件路径直接打开。

限制：如果 Telegram 评论/讨论串不在当前事件 payload 中，本轮不会自动调用 Telegram API 拉完整评论树。

### 4.3 文件读取和文件生成

新增：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sources\file_reader.py`

只读解析支持：

- TXT、LOG、MD、CSV、JSON、YAML；
- Python、C、C++、C#、Java、JavaScript、TypeScript、Go、Rust、PHP、Shell、PowerShell、SQL、HTML、CSS；
- DOCX；
- XLSX/XLS；
- PPTX/PPT。

规则：

- 不执行用户上传的代码；
- 有 NUL 的未知二进制不强行读入；
- 文本使用容错编码；
- 文档解析依赖对应 Python 包；旧 `.xls/.doc/.ppt` 可能因系统未安装转换器而退化为失败提示；
- 读取到的文件内容属于不可信数据，不得覆盖系统/人格/工具边界。

生成逻辑：

- 用户明确要求“生成/保存/导出代码文件”时，使用模型原始回复提取代码；不能先经过 Markdown/自然语言清理；
- Python 代码会用 `ast.parse` 做语法检查；
- 文件名有随机后缀，避免覆盖；
- 用户要求生成短 TXT 时也会落盘，不再要求超过 4000 字；
- `CapabilityResult.files` 传递附件；
- OneBot 使用 `upload_group_file` 或 `upload_private_file`；
- 不再伪造 OneBot `file` 消息段；
- 长文档/提示词明确要求保存时，先写文件，再发送文件。

已修复的原问题：代码不会再因为自然语言整理破坏缩进、字符串和 `print`，也不会只把代码当聊天正文；但必须在请求中明确说“生成文件/保存为文件”，否则普通代码讲解不会猜测要上传文件。

### 4.4 输出整理

新增：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\output\plain_text.py`

作用：

- 只处理 `bot.chat` 正文；
- 去除逐句外层中文/英文引号；
- 保留真实内层引用、URL、英文撇号和设置参数；
- 将常见 Markdown 标题、列表、粗体、斜体、删除线、代码围栏转为自然文本；
- 将常见 LaTeX 形式转为可读表达；
- 不增加 LLM 调用；
- 不修改人格 Prompt 和人格源文件。

已覆盖用户给出的“宝宝”样例；仍需对复杂 TeX、嵌套 Markdown 和特殊 Unicode 做持续补充。

### 4.5 记忆 401 修复

- 自动记忆抽取改为复用主聊天 `ModelRouter` 的注册表、凭据引用、优先级和故障转移配置。
- 不再使用另一套可能失效的基础 key。
- 抽取使用独立调用状态，不污染聊天诊断状态。
- 有独立 timeout、max tokens、并发限制和错误冷却。
- 失败不会阻塞正常回复，日志不打印原始鉴权异常。
- `BOT_MEMORY_EXTRACT_ENABLED=false` 可暂停自动抽取，不删除已有记忆。

尚未完成真实重启后的记忆数据库持久化验收；也没有完成“启动时关闭后通过热设置自动创建 writer”的完整热启用。

### 4.6 模型路由和参数

当前优先级算法：

1. 手动指定模型；
2. 当前生效时段组的 `order`；
3. 注册表的基础 priority；
4. 故障转移时按同一顺序继续尝试可用候选。

Priority 不是简单允许重复数字的排序，而是 `1..N` 的唯一槽位。移动模型时其他模型自动顺移，越界位置收敛到首尾。

文本模型指令已覆盖：

```text
/bot model list
/bot model set <id|auto>
/bot model add <id> model=<实际模型ID> base_url=<URL> key=<密钥|env:变量> [tags=fast,strong] [priority=<n>]
/bot model update <id> model=... actual_model_id=... base_url=... key=... alias=... aliases=... tags=... effort=... priority=...
/bot model priority <id> <槽位>
/bot model think <off|low|medium|high|xhigh|max>
/bot model remove <id>
/bot model reset
```

配置项：

- `model`/`actual_model_id`：改变实际请求模型 ID；
- `base_url`：改变 API 地址；
- `alias`/`aliases`：改变简称；
- `effort` 或 `/bot model think`：改变思考强度；
- `BOT_CHAT_REASONING_EFFORT`：全局默认思考强度；
- `priority`：改变唯一优先级槽位；
- `BOT_MODEL_SCHEDULE`：按时段切换；
- `BOT_MODEL_PRIORITY_GROUPS`：按时段组提供候选顺序。

视觉模型已有 add/update/priority/remove 和模型、Base URL、key、简称、effort、实际模型 ID 字段，但与文本模型相比仍缺少完整实机链路和全部帮助/默认思考强度对齐验收。

如何查看当前模型：

- `/bot model list`：查看候选模型、优先级和故障转移顺序，不代表上一条回答实际使用了哪个模型；
- `/bot status`、`/bot recent`：查看安全诊断摘要；
- `/bot llm`：做一次新的短连接诊断，显示 provider/model，但可能产生新的模型费用；
- `chat-smoke`/`console` 输出 `llm_provider`、`llm_model`；
- live chat 审计标签包含 `model:<实际返回模型>`，并会记录 usage/finish reason（密钥和正文不写入公开输出）。

当前 `.env` 的非秘密配置是：

```text
BOT_CHAT_PROVIDER=openai_compatible
BOT_CHAT_MODEL=gpt-5.6-terra
BOT_CHAT_BASE_URL=https://newapi.qianqianye.com/v1
BOT_CHAT_FAST_MODE=false
BOT_CHAT_MAX_TOKENS=65538
BOT_CHAT_FAST_MAX_TOKENS=65538
```

### 4.7 搜索 API

已按用户指定适配：

- Tavily：主搜索；
- You.com：备用搜索；
- TinyFish：正文抓取；
- LangSearch：备用搜索；
- Bing：不接入。

配置在 `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\config.py` 与 `.env.example`；endpoint 可自定义，不强行猜测供应商地址。默认 fallback 为 You/LangSearch，TinyFish 仅作为正文抓取能力。

已完成 provider 协议、请求映射、失败降级和无 key 安全跳过测试；未完成四家真实账号、额度、区域 endpoint、超时和 SLA 的逐家联网验收。

### 4.8 Wiki

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\sources\mediawiki.py` 已加入：

- 精确标题优先；
- 拒绝无关的 opensearch 候选；
- 配置索引页优先；
- 角色列表精确条目边界提取；
- 游戏摘要按“这是什么、主要玩法、核心故事、当前状态”组织；
- 过滤立项/公布/发行等无关时间噪声；
- 缺少当前状态时明确说明资料不足，不编造。

已对公开入口复验：守岸人、鸣潮守岸人、漂泊者、卡提希娅· 均能命中角色列表条目。

未完成：所有游戏页面结构化字段、多语言标题转换、页面变化缓存、限流、复杂模板和任意百科站点兼容。

### 4.9 安全与反注入

新增：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\security\content_safety.py`

已覆盖低成本确定性基线：

- NSFW/R-18/露骨性内容；
- 血腥、肢解、酷刑、极端暴力；
- 极端政治、恐怖组织宣传、煽动暴力；
- 人身攻击、公开羞辱、要求叫他人“废物”等；
- 强制当猫娘、叫妈妈、强制爱上用户、求婚等人格/关系越界。

处理方式：

- 规则只作为内部约束，不直接把“策略”“保持既定人格”“response_guidance”发给用户；
- 尽量由当前人格模型自然回应；
- 模型回显内部规则时使用人格化兜底；
- 群聊公共空间对明显性、血腥、辱骂输出进行最终审核；
- 对友善、亲密但不过界的话仍允许角色接住；
- 对求婚、性内容、强制改人格采用含蓄、有边界、有世界观的回应，而不是机械模板。

限制：这是规则基线，不是万无一失的语义安全分类器；隐晦攻击、编码绕过、图片内容审核和人工复核仍未完成。

### 4.10 戳一戳

新增：

`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\plugins\bot_unified_runtime\capabilities\poke.py`

已实现：

- 只响应目标确实是机器人自己的 poke；
- 私聊冷却；
- 群聊全局冷却与单用户冷却；
- 概率控制；
- 低扰民文本反馈；
- 文本反馈经统一出站。

配置：

```text
BOT_POKE_ENABLED
BOT_POKE_PRIVATE_COOLDOWN_SECONDS
BOT_POKE_GROUP_COOLDOWN_SECONDS
BOT_POKE_PROBABILITY
BOT_POKE_ADMIN_BYPASS
```

未完成：真实 NapCat poke 验收、主动调用 OneBot `send_poke` 反戳、Telegram poke、图片/表情包/语音 poke 素材。

## 5. 用户要求逐项对照

| 用户要求 | 状态 | 说明 |
|---|---|---|
| 后端主链路和统一底座优先 | ✅ | 离线 base smoke、backend smoke、NoneBot startup、fake transport 通过 |
| 真实聊天可用 | ✅/需继续观察 | 用户已实测文本有回应；真实 provider 稳定性仍需持续观察 |
| NapCat -> OneBot -> QQ 闭环 | 🟨 | 用户已实测文本和图片；本轮最终未代做真实重启验收 |
| 不推送 origin | ✅ | 没有 push |
| Tavily 主、You 备、TinyFish 正文、LangSearch 备用 | ✅/🟨 | Tavily/You 已真实账号 smoke 通过（2026-09-08，见 19.6）；TinyFish/LangSearch 未验收 |
| Bing 不接 | ✅ | 未加入 Bing |
| 人格源文件不擅改 | ✅ | 本轮没有修改人格源文件 |
| 64K 输出上限 | ✅ | 65538 上限已接入，非强制长度 |
| 详细知识/人物/组织关系回答 | 🟨 | 已改回答策略，世界观结构化 RAG 尚未完成 |
| memory extraction 401 | ✅/🟨 | 路由复用和异常隔离已修复，真实记忆写入需重启验收 |
| 唯一 priority | ✅ | 1..N 槽位、移动自动顺移 |
| 模型 add/update/priority/effort/Base URL/简称/实际 ID | ✅/🟨 | 文本模型已覆盖；视觉模型命令和实机仍需对齐 |
| help 和参数设置 | ✅/🟨 | 文本 help 已同步；部分历史文档和视觉模型说明仍需统一 |
| 去除引号、Markdown、LaTeX 噪声 | ✅/🟨 | 已有确定性整理，复杂边界待扩展 |
| 图片/表情接收和回复 | ✅/🟨 | 用户确认图片可回复；表情包有代码覆盖但仍需更多实机样本 |
| 引用、聊天记录、评论读取 | 🟨 | 当前 payload 内可读；Telegram 评论树 API 未补拉 |
| 文本+图片+Emoji+表情包发送 | ✅/🟨 | OneBot mixed 构造通过；各类 NapCat 版本仍需实测 |
| 读 Word/Excel/PPT/代码/TXT/Log | ✅/🟨 | 新格式优先；老格式依赖环境 |
| 自动生成代码文件 | ✅/🟨 | 明确生成文件意图时落盘并上传；病毒扫描未做 |
| 长文写文件后发送 | ✅/🟨 | 已接入；专用文档 LLM 和所有平台文件出站未完全统一 |
| 反 NSFW/血腥/极端政治/辱骂 | ✅基线 | 规则+人格化回应；不是完整分类器 |
| 反人格破坏和关系越界 | ✅基线 | 内部安全规则不外显；复杂攻击仍需强化 |
| PokePro 思路适配 | 🟨 | 已有低扰民文本 poke；未引入外部插件代码，未做主动反戳 |
| Wiki 精确命中和指向性梗概 | ✅/🟨 | 主要样例已修复，复杂页面仍有限 |
| 备份成功、可继续调试 | 🟨 | 源码仍保留；本轮没有创建新的压缩归档包 |

## 6. 明确未完成清单

### P0：下一步必须优先

1. 重启唯一 NoneBot 进程，做真实 NapCat 私聊、群聊、普通成员、引用、图片、表情包、文件上传验收。
2. 把文件上传/下载抽成 `FileTransferGateway`，统一幂等键、回执、失败分类、审计和过期清理。
3. 将订阅推送、文档导出、视觉回应、poke 等能力逐一审计，删除不必要的直接 sender/call_api 分支。
4. 建立跨平台入站事件幂等表和出站 result-unknown 恢复策略。
5. 真实验证 memory extraction：provider、数据库、写入、失败冷却、重启后恢复。

### P1：知识和人格可靠性

1. 不修改人格源文件的前提下，增加只读 `PersonaContract`。
2. 建立 `WorldEntity/Relation/Claim` 结构化世界观索引。
3. 建立 `EvidenceLedger`：来源、时间、权威等级、原始证据、摘要、冲突组。
4. 建立 `AnswerPlan`：先判断问题类型，再选择人物/组织/关系/现实事件/搜索/工具路径。
5. 做 claim-based RAG，而不是把大段检索原文直接塞进 Prompt。
6. 建立用户记忆 `propose -> policy -> approve -> commit`，支持冲突、删除、撤销、回滚审计。
7. 建立群聊公共 `SceneState/SceneBrief`，与个人长时记忆隔离；识别多人复读、起哄和话题趋势。
8. 对网页、搜索结果、上传文件、引用内容、记忆和工具输出加 TrustLevel/TaintFlag，隔离间接 Prompt Injection。
9. 对模型输出做“事实声明是否有证据”的后审计，避免模型新增世界观事实。

### P2：模型、搜索、工具和运营

1. 视觉模型与文本模型的全部命令、help、effort、默认思考强度、优先级和实际调用链对齐。
2. 为每次 LLM 调用写结构化 `LLMCallRecord`，稳定显示 provider、实际模型、路由尝试、tokens、延迟、费用和失败原因。
3. 完成 Tavily/You/TinyFish/LangSearch 的真实账号逐家 smoke、额度和故障转移验证。——2026-09-08 Tavily/You 已通过且两家间真实故障转移演练完成（19.6）；剩 TinyFish/LangSearch 逐家 smoke、TinyFish fetch 半段与额度控制台核查。
4. 建立正式 `ToolCatalog`：工具能力、参数 schema、权限、风险、超时、回滚和降级。
5. 网页正文抓取增加反注入隔离、去广告、正文评分、来源合并和引用定位。——2026-09-08 第一步已落地：通用 `fetch_page_text` 结构性去噪（HTML 注释、`script/style/noscript/template/iframe/object/embed/svg` 隐藏块、`<head>` 整块剥离后再入 Prompt，新增 2 项回归测试，367 passed/Ruff 过）；剩正文评分、来源合并、引用定位与 P1.8 级 TrustLevel 架构。
6. 生成文件增加病毒扫描、敏感内容扫描、大小限制、TTL 清理和安全文件名。
7. Telegram 评论区/讨论串 API 补拉、权限、分页、速率限制、Telegram 文件发送。
8. 邮件适配器做真实连接、认证、超时和 worker 验收；当前只完成异常韧性代码测试。
9. Wiki 增加多语言标题转换、缓存、限流和复杂模板支持。
10. Poke 增加真实 `send_poke`、Telegram 适配和管理员/群策略细化。

### P3：数据迁移、备份和发布

1. 生成源码与 Runtime 文件清单、SHA256、大小、mtime 和来源映射。
2. 对 SQLite 执行 `integrity_check`、`foreign_key_check`、schema/row-count 核对。
3. 将旧数据整合成一次归档备份，压缩后校验可解压、可读、可恢复；不得覆盖旧备份。
4. 确认 `BOT_RUNTIME_DATA_DIR`、`LOCALSTORE_*_DIR`、Cookie、向量库、记忆库和生成文件目录全部在 `ChatBot_Runtime`。
5. 只在备份验证成功后清理源码区 `data/`、`__pycache__`、pytest/Ruff/mypy 缓存。
6. 采用显式文件清单创建 alpha test 备份；严禁 `git add -A`。
7. 只有用户再次明确授权后，才考虑推送到指定 alpha test 远端；禁止 `origin`。

## 7. 真实测试操作顺序

### 7.1 启动前

```powershell
cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Task doctor
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Task backend-base-smoke
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Task backend-smoke -Message '本地闭环测试'
```

不要启动第二个同 QQ 账号进程。

### 7.2 NapCat

1. NapCat WebUI 建立 WebSocket 服务器。
2. Host 使用 `127.0.0.1`，端口与 `.env.prod` 一致，Access Token 与本地配置一致。
3. 启动机器人：

```powershell
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\venv\Scripts\python.exe bot.py
```

4. 看日志确认 OneBot V11 连接成功。
5. 私聊测试：你好、你是谁、维基 鸣潮、生成一个 Python 文件。
6. 群聊测试：@机器人、引用他人消息、文本+图片+Emoji+表情包、普通成员发言。
7. 上传 `.txt/.log/.py/.cpp/.java/.docx/.xlsx/.pptx`，确认只读解析，不执行代码。
8. 发送“请生成一个 Python 文件”与“生成一个 txt 文档”，确认收到文件而非代码大段正文。
9. 测试 `/bot model list`、`/bot status`、`/bot recent`、`/bot help 模型`。
10. 测试 `/bot llm` 前确认接受一次短诊断调用可能产生费用。

### 7.3 低成本关闭可选算力

```text
/bot runtime set BOT_CHAT_FAST_MODE false
/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false
/bot runtime set BOT_CHAT_MAX_TOKENS 65538
```

验收知识、人格和检索时建议关闭自动记忆抽取；完成验证后再开启。关闭抽取不会删除已有记忆。

## 8. 运行数据、密钥和 Prompt 审计

- Runtime 数据目标：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data`。
- 不把真实 key 写入 `BOT_MODEL_REGISTRY`，使用 `env:BOT_API_KEY_*`。
- 不把 key、Cookie、签名 URL、完整敏感 Prompt 发到群聊或交接文档。
- Prompt audit 默认会记录脱敏后的消息和上下文摘要；长期保留、访问权限、批准 digest 还需完善。
- 人格源文件必须只读；后续 Prompt 重构只能新增编译层、合同层和审计层，不能覆盖源内容。

## 9. 相关文档索引

- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\backend-base-status-2026-09-06.md`：后端底座、统一网关和未完成清单。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\phase0-3-implementation-2026-09-07.md`：Phase 0-3 实施记录。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\live-chat-followup-2026-09-06.md`：引号、Wiki、Cookie、视频和 doctor 续修。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\chat-plain-text-output.md`：自然语言输出整理。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\search-api-adapters-2026-09-06.md`：四家搜索 API 适配配置。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\acceptance-manual.md`：验收和接入手册。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\napcat-setup.md`：NapCat/OneBot 配置。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\COMMANDS.md`：命令和参数。
- `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\task_plan.md`、`findings.md`、`progress.md`：过程记录。

## 10. 交接后的第一件事

先不要继续改人格 Prompt。先按第 7 节重启并完成一次真实 NapCat 验收；记录每条消息的时间、是否回复、`request_id`、脱敏的 `audit_tags`、实际模型和 `receipt_state`。如果失败，优先判断失败阶段：`ingress`、`context`、`llm`、`review`、`upload`、`onebot`，不要只看最后一条报错。

---

**当前可交付判断：** 这是一个已经有后端运行底座、可做真实聊天验收的 alpha 测试状态；不是完成所有用户要求的生产状态。所有未完成项均已在本文件列出，后续改动必须同步更新本文件、`task_plan.md`、`findings.md` 和 `progress.md`。

## 11. 用户需求完整登记

以下不是推测，是本项目在多轮交接中明确提出、必须保留的需求集合。下一位接手者不得只看“已完成”部分而遗漏这些约束。

### 11.1 项目边界、Git 和备份

- 优先后端主链路、数据处理、入站、出站和可执行单元。
- 先做可用 alpha，不急于完善所有插件。
- 不允许使用 `origin` 推送；如未来推送，只能推到用户指定的 alpha test 位置，并注明用途。
- 后续用户又明确要求暂时不推送，先保证备份成功。
- 不得上传真实文件数据，不得把 API key、Cookie、用户聊天隐私提交到 Git。
- 需要判断哪些文件能安全迁入 `ChatBot_Runtime`，迁移前必须验证、归档、可恢复。
- 老数据要整合成一次归档备份，必要时可调回；不能直接删除活动数据。
- 人格、世界观源文件不能由 AI 擅自改动。

### 11.2 后端运行底座

- 统一基座、统一运行、统一消息进入、统一消息处理、统一消息出发、统一消息输出。
- 完成 NapCat 接收信息、OneBot 事件、NoneBot 处理、OneBot 出站、NapCat 发回 QQ 的闭环。
- 需要有 offline smoke、backend smoke、startup smoke、transport smoke 和真实 NapCat 实机测试步骤。
- 所有能力尽量走统一出站；文件上传、订阅推送、Telegram、Mail 等不能长期各写一套不可审计的发送逻辑。
- 失败必须能区分 ingress/context/llm/review/upload/onebot/timeout，并保留 request_id、receipt_state 和安全审计信息。

### 11.3 人格、世界观、RAG、记忆

- 不直接重写人格 Prompt 源文件。
- 需要把角色人格、世界观实体、现实检索证据、用户记忆、工具边界做成可版本化合同；后续确定采用更好的结构化模型，而不是把大段文本直接注入上下文。
- 要降低 Prompt 注入算力和幻觉；世界观和网络搜索内容必须经过压缩、证据化、相关性筛选和冲突处理。
- 游戏人物、组织、关系问题不能只截取网页开头，要说明身份、关系、核心经历、当前状态和资料缺口。
- 短时记忆要能适应群聊大量消息；长时记忆要有专门数据库、写入审核、冲突处理、删除、撤销和回滚。
- 群聊需要有公共话题状态，识别多人复读、起哄、趋势和上下文；公共状态不能污染个人记忆。
- 现实网络信息要有来源、时间、权威等级和事实冲突处理。

### 11.4 LLM、模型和参数

- 回复不能 OOC，不能机械式安全模板；安全回应也要使用角色人格和世界观。
- 验收知识库、人格、世界观、联网检索能力时，暂时不要过度压缩回复。
- 输出预算设置到 65538（约 64K）作为上限，但不是强制每次输出 64K。
- 修复 memory extraction 401，并让它复用正常聊天的模型路由。
- 能查看当前实际 provider/model，并能调整模型。
- Priority 必须一对一唯一槽位，不能多个模型共用同一个 Priority。
- 模型和视觉模型的管理要支持：添加、修改、改变优先级、改变思考强度、改变 Base URL、改变默认思考强度、改变简称、改变实际模型 ID，并让 help 同步。
- 模型路由要有合理的手动指定、时间段、基础 priority、故障转移规则。

### 11.5 搜索 API

- 只接入 Tavily、You.com、TinyFish、LangSearch。
- Tavily 主搜索；You.com 备用；TinyFish 用于正文抓取；LangSearch 备用。
- 不接 Bing。
- 所有 endpoint、超时、查询数、正文抓取、降级顺序要可配置。

### 11.6 消息、媒体、文件和文档

- 支持 QQ/Telegram 引用内容、回复内容、聊天记录、评论区/讨论串内容。
- 支持文本与图片混合、Emoji、表情包、图片接收与发送。
- 支持读取 Word、Excel、PPT、Python、C、C++、C#、Java、TXT、Log 等。
- 用户要求生成代码时，优先生成并发送真实文件，不能把代码破坏后作为一堆文本发送。
- 用户要求生成长文、Prompt、人设、文档时，写入文件后再发送。
- 文件中的内容只能作为不可信数据读取，不能把文件里的 Prompt 当系统指令。

### 11.7 安全、群聊和人格边界

- 防 NSFW、R-18、血腥暴力、极端政治宣传、煽动暴力、人身攻击和群聊羞辱。
- 防止用户强制机器人当猫娘、叫妈妈、喊不当称呼、求婚、性关系或改变人格。
- 友善亲密表达可以接住；激进表白、求婚和性内容需要以角色口吻委婉、有温度地处理，不能把内部安全术语发出来。
- 群聊中要考虑不适合公共空间的表达，优先换话术、委婉拒绝、中性描述和角色化转化。

### 11.8 Poke、Wiki、视频和媒体

- 参考 `astrbot_plugin_pokepro` 的低扰民思路适配 NoneBot。
- 至少支持戳一戳的文本反应；图片、表情包、语音素材暂缓。
- Wiki 必须精确命中真实词条，不能把《鸣潮》误命中为角色列表，也不能把守岸人误命中为守夜人国家。
- Wiki 摘要要有指向性，游戏优先说明是什么、制作方、类型、玩法、故事和当前状态，去掉无关时间噪声。
- B 站、YouTube、推特、小红书解析的 Cookie 错误不能刷屏、不能泄露 Cookie、不能因一个坏行丢掉所有有效 Cookie。

## 12. 已写过的计划和计划演进

### 12.1 初始审查计划

`task_plan.md` 最初包含：

1. 根目录、配置、仓库状态探索；
2. README/Markdown 审查；
3. 目录树和模块映射；
4. NoneBot/API/数据库核心代码走查；
5. Web UI 审查；
6. 需求清单交叉比对；
7. 验证报告和审查过程留档；
8. 补充后端控制面需求与用户确认决策。

初始结论是：项目是“后端统一运行时 + NoneBot 适配器 + 多平台链接解析/部分订阅”的 alpha，不是完整 Web UI 和完整平台生态。

### 12.2 后端优先计划

随后计划切换为：

- 先实现单轮后端执行单元；
- 再完成真实 LLM provider 配置体检；
- 再完成 RuntimePipeline、NoneBot startup、fake OneBot transport；
- 再做 IngressGateway 和 UnifiedDeliveryGateway；
- 最后由用户启动 NapCat 做真实 QQ 验收。

### 12.3 Phase 0–5 计划

- Phase 0：65538 输出上限、详细回答和科普结构；
- Phase 1：quote/forward/chat history/mixed media 统一输入；
- Phase 2：文件读取、代码文件、文档文件和长文档附件；
- Phase 3：群聊安全、反注入、人格边界和自然拒绝；
- Phase 4：低扰民 poke 文本反馈；
- Phase 5：Wiki 精确条目和结构化摘要。

这些 Phase 的基础代码和测试已完成，但其中多项仍需要真实平台验收，不能把离线测试等同于生产完成。

### 12.4 还没有写成独立实施计划的内容

以下只是任务清单/方向，尚未形成可直接执行的独立计划文档：

- PersonaContract 和只读人格编译器；
- WorldEntity/Relation/Claim 图谱；
- EvidenceLedger 和搜索证据压缩器；
- AnswerPlan/DecisionEngine；
- Memory Gate 和记忆回滚审计；
- Group SceneState/SceneBrief；
- ToolCatalog 和工具权限/风险合同；
- FileTransferGateway；
- LLMCallRecord 和模型实际调用可观测性；
- Runtime 迁移 manifest、SQLite 校验和可恢复归档；
- Telegram 评论树和文件出站；
- 真实四家搜索 API 验证矩阵。

## 13. 实际执行量和代码量

### 13.1 可核实的测试和检查执行量

最终可核实结果：

- 完整 pytest：352 项通过；
- Phase 0–5 定向回归：17 项通过；
- Ruff：通过；
- mypy：174 个源码文件无错误；
- backend-smoke：通过；
- backend-base-smoke：通过；
- doctor：通过；
- docs-check：通过；
- runtime-layout：失败，发现源码运行产物和 156 个 Python 缓存路径；
- 用户实机反馈：QQ 纯文本可回复，图片可回复；本轮没有重新代替用户操作真实 QQ。

### 13.2 当前源码和测试规模

直接扫描当前工作区可见文件得到：

- `plugins/` 下 Python 文件：174 个；
- `plugins/` Python 总行数：约 61,563 行；
- `tests/` 下 Python 文件：62 个；
- `tests/` Python 总行数：约 8,477 行；
- 当前工作区 Git 状态条目：352 个；
  - modified：83；
  - deleted：131；
  - untracked：138。

注意：这些是当前工作区规模，不等同于本次单次会话原创代码量。

### 13.3 当前 Git 差异规模

对已被 Git 跟踪的差异做统计：

- 涉及 214 个 tracked files；
- 增加约 14,527 行；
- 删除约 41,855 行。

这个数字包含多轮历史工作、归档整理、文件迁移/删除和用户原有脏变更，不能归因给某一个模型或某一轮。当前禁止 `git add -A`，必须先拆分文件清单。

### 13.4 本次收尾额外改动

本次最终收尾阶段可明确归因的文件：

1. `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot\docs\handoff-final-2026-09-07.md`：新增完整交接文档；
2. `.env.example`：去除重复聊天输出上限配置；
3. `COMMANDS.md`：修正 65538/抽取 token 的陈旧说明；
4. `tests/test_phase0_3_features.py`：修正 fake Bot 的 `call_api(api, **kw)` 测试签名；
5. `plugins/bot_unified_runtime/capabilities/chat.py`：修正安全分支 max_tokens 类型转换；
6. `docs/phase0-3-implementation-2026-09-07.md`：更新最终验证数字；
7. `task_plan.md`：追加最终收尾状态；
8. `progress.md`：追加最终验证日志；
9. `findings.md`：追加最终发现和风险。

## 14. 明天建议执行的完整方案

### 明天上午：先确认能跑和能收发

1. 不修改人格 Prompt，不修改世界观源文件。
2. 运行 doctor、backend-base-smoke、backend-smoke。
3. 启动唯一 NapCat/NoneBot 实例。
4. 用一个私聊账号和一个普通群成员分别测试：文本、引用、图片、表情包、文件、生成 `.py`、生成 `.txt`。
5. 保存每个失败的 `request_id`、stage、model、receipt_state，不保存 key/Cookie/完整 Prompt。

### 明天中午：完成统一出站审计

1. 搜索所有 `bot.send()`、`bot.call_api()`、`send_group_msg()`、`send_private_msg()`。
2. 保留平台必要 API，但全部封装到 FileTransferGateway/PlatformActionGateway。
3. 为文件上传、下载、订阅推送增加幂等键、审计和 result-unknown。
4. 增加真实 OneBot payload 回归，确认不再发送伪造 `file` segment。

### 明天下午：先做可靠上下文，不做大 Prompt 注入

1. 只读加载人格源文件，生成 PersonaContract 摘要。
2. 世界观实体拆成 entity/relation/claim，不把整篇知识库注入模型。
3. 搜索结果经过 EvidenceLedger，再生成小型 EvidenceDigest。
4. 以 AnswerPlan 决定是否查知识库、联网、工具和记忆。
5. 在 live LLM 前写入 prompt artifact、摘要、hash 和 approved digest。

### 明天晚上：做记忆和群聊

1. 记忆抽取使用主路由，但写入必须经过候选审核。
2. 个人记忆、群公共状态、引用内容分离存储。
3. 只保留最近必要的短时窗口；群聊使用低成本 SceneBrief，不把整群历史塞入 Prompt。
4. 用“多人复读/起哄/上下文延续”作为第一批群聊状态回归样例。

## 15. 仍未做的问题总表

### 未做或只做了代码层

- 真实 NapCat poke 和主动反戳；
- Telegram 评论树、讨论串和文件出站；
- Mail 真实账号连接和 worker 实机；
- 四家搜索 API 真实账户逐家测试；
- Wiki 复杂页面、多语言、缓存、限流；
- 老 `.doc/.xls/.ppt` 转换链；
- 文件病毒扫描、敏感内容扫描、大小限制、TTL 清理；
- 视觉模型真实路由、视觉命令全部对齐；
- 每次 live LLM 实际 provider/model/route attempts 的稳定展示；
- Prompt artifact 审批闸门强制接入 live call；
- Claim-based RAG、EvidenceLedger、Trust/Taint；
- 长时记忆 propose/policy/approve/commit；
- 群聊公共状态和多人复读识别；
- 工具目录、工具权限、工具回滚、工具失败降级；
- 所有边缘能力完全统一出站；
- Runtime 迁移、归档、完整性校验和源码 data 清理；
- alpha test 文件清单和安全 Git 提交；
- Web UI/Control Plane。

### 已知问题但没有继续冒险处理

- `runtime-layout` 发现源码 data 和缓存，不能直接删除；
- `.pytest-final-temp` 权限残留曾导致普通沙箱测试无法创建临时目录，已通过项目规定的外部 Runtime 验证入口完成最终 verify，但残留路径仍需后续安全清理；
- 早期文档存在旧测试数字、旧 token 说明和旧“未完成”描述，本报告已明确以最终状态为准，但没有重写所有历史文档；
- 当前工作区有大量删除和未跟踪文件，不具备直接提交条件；
- 没有创建新的压缩归档包，因此“代码备份完成”不能等同于“本轮已有可恢复发布包”。

## 16. 疑虑、顾虑和需要下一位特别确认的地方

1. **真实模型到底是哪家。** 当前配置显示 OpenAI-compatible 和 `gpt-5.6-terra`，但实际请求可能经过模型注册表和故障转移；`/bot model list` 只能看候选，必须从本次 request 的审计/diagnostic 读取实际返回模型。
2. **离线 static smoke 容易造成错觉。** backend-smoke 的 `ok=true` 不代表真实 LLM、搜索、NapCat 或文件上传成功。
3. **用户实测与最终源码状态可能错位。** 用户确认过文本和图片回复，但如果进程没有重启，QQ 仍可能运行旧源码；下一次验收必须确认唯一进程和启动时间。
4. **模型回答质量还没有客观评测集。** “更像守岸人”“关系说清楚”“知识库命中”目前主要靠人工感受，没有建立固定问题集、期望证据和 OOC 评分。
5. **安全规则仍是正则基线。** 不能宣称万无一失；图片、编码绕过、隐晦政治、隐晦羞辱和网页反注入仍有风险。
6. **文件生成有副作用。** 代码可以被生成和上传，但尚未做病毒扫描、敏感信息扫描、执行隔离、文件大小和自动过期清理。
7. **Runtime 数据归属不够清晰。** 源码 data 中有活动文件，不能确认每个 SQLite/向量/设置文件是否都能移动；迁移前必须停机和做校验。
8. **Git 不能直接处理。** 当前分支和工作区不是干净 alpha patch，必须由人审核文件清单，不能用全量 staging。
9. **代码量统计存在边界差异。** `verify` 某次输出曾显示 309 个插件 Python 文件，而当前直接扫描 `plugins/` 得到 174 个；这说明统计时可能存在路径、缓存或时间点差异，下一位应先核对文件边界，不能拿两个数字做发布承诺。
10. **历史文档可能互相矛盾。** 交接时优先看本文件、最终 `task_plan.md/progress.md/findings.md` 和最新测试输出；旧日期文档只作为历史记录。

## 17. 下一位接手者的最短路径

1. 阅读本文件第 2、3、6、14、16 节。
2. 阅读 `docs/external-runtime-access.md` 和 `docs/workspace-archive-policy.md`。
3. 运行 `doctor`、`backend-base-smoke`、`backend-smoke`。
4. 检查 `.env` 非秘密配置，不打印 key。
5. 确认 NapCat 只启动一个实例。
6. 完成真实 QQ 最小验收后，再开始 FileTransferGateway。
7. 不先改人格，不先做大 Prompt，不先删除 Runtime 数据，不先 Git push。
8. 每完成一个合同，同时更新：
   - `docs/handoff-final-2026-09-07.md`；
   - `task_plan.md`；
   - `findings.md`；
   - `progress.md`；
   - 对应测试和命令证据。

## 18. 最终交接声明

本项目当前是“可运行、可测试、可以进入真实 NapCat 验收”的 alpha 后端，不是全部需求完成的生产机器人。

已完成的重点是：统一后端主链路基础、OneBot/NoneBot 传输边界、真实 LLM 配置底座、模型优先级、记忆路由修复、输入媒体归一化、文件读写、自然语言输出、安全基线、Wiki 定向修复和低扰民 poke 文本。

未完成的重点是：生产级知识/人格编译器、证据化 RAG、长时记忆审批、群聊公共状态、完整工具系统、全能力统一出站、Telegram/搜索真实验收、数据迁移归档、Git alpha 发布和完整运维控制面。

交接时不得把“测试通过”表述成“所有用户要求已经完成”，也不得把“用户曾经实测成功”扩大解释为“当前所有平台均已验收”。

## 19. 2026-09-07 alpha.2 增补（v0.0.1-alpha.2 交付记录）

本章由 alpha.2 收尾会话追加，数字以本章为准；上文 352/174 为 alpha.1 收尾时的历史记录。

### 19.1 测试基建修复

- `%TEMP%\pytest-of-LancyCelestia\pytest-current` 是指向父目录的循环符号链接且 ACL 拒绝访问，导致 pytest 会话收尾崩溃（第 15 节已知顽疾的根因）。未提权无法删除该链接；已改为在 `scripts/dev.ps1` 的 `Invoke-Test` 中固定 `PYTEST_DEBUG_TEMPROOT` 与 `--basetemp` 到每进程专属的 Runtime cache 目录，verify 从此与共享 temp 根隔离。
- `tests/test_mail_bridge.py` 此前把状态文件写入源码树工作目录，与运行中的机器人实例/文件扫描器竞争造成 `os.replace` 偶发 WinError 5；已迁到 pytest 临时目录，并给 `mail_bridge._save` 加瞬时锁重试。

### 19.2 参考插件取长补短（应用户要求完成）

12 个社区插件已克隆到源码树外评审，逐插件结论、采纳与拒绝理由见 `docs/plugin-benchmark-2026-09-07.md`。落地三项：

1. **掉线管理员通知**（借鉴 nonebot_plugin_disconnect_notice）：新增 `runtime/disconnect_notice.py`，掉线时经仍在线的 Telegram 管理员私聊与邮件桥通知，按 bot 冷却（默认 600s），默认关闭；配置 `BOT_DISCONNECT_NOTICE_*`（见 `.env.example`）。
2. **搜索适配器加固**（对比 nonebot-plugin-tavily）：`_JsonSearchProvider` 对 `httpx.TransportError` 原地重试（默认 1 次/0.25s 退避），HTTP 状态错误仍走链式回退；Tavily `search_depth`/`time_range` 经 `BOT_WEB_SEARCH_PROVIDER_OPTIONS` 透传即可，无需改码，文档已补。
3. **Wiki 缓存+限流**（P2.9）：`sources/mediawiki.py` 模块级 TTL 缓存 900s + 最小请求间隔 1s，四个 API 调用点收敛到 `_cached_get_json`；提供 `clear_wiki_cache()`。

明确不引入：htmlrender（Mica 卡片体系冲突）、memes（重依赖）、help（已归档且弱于现有帮助）、songpicker2/multincm（音乐链路已自有且质量优先选流）、WWwiki/analysis_bilibili（异构/自有实现已覆盖）；personification 与 parser-lite 记为 P1 设计参考。

### 19.3 alpha.2 验证证据

- 完整 verify：`361 passed, 1 warning`（唯一 warning 仍为上游 mail 适配器 Pydantic 弃用提示）；Ruff `All checks passed!`；mypy `Success: no issues found in 175 source files`。
- 新增回归：`tests/test_disconnect_notice.py`（6 项）、搜索重试 2 项、wiki 缓存 1 项。
- 本轮仍遵守：无真实 QQ/Telegram 消息发送、无真实付费 LLM 调用、未修改人格/世界观源文件、未删除 Runtime 活动数据。

### 19.5 alpha.2 二轮增补：搜索适配深度对齐（对标 nonebot-plugin-tavily）

- **Tavily 一级参数**：`BOT_WEB_SEARCH_TAVILY_SEARCH_DEPTH`（basic|advanced）、
  `BOT_WEB_SEARCH_TAVILY_TIME_RANGE`（day|week|month|year），构建链时自动注入请求体；
  `BOT_WEB_SEARCH_PROVIDER_OPTIONS` 同名键优先，可按 provider 细调。
- **正文抓取回退链**：TinyFish fetch → Tavily extract（`BOT_WEB_SEARCH_TAVILY_EXTRACT_ENABLED`，
  默认关）→ 通用抓取；`CompositePageFetchProvider` 单抓取器失败自动下一个。
- **search-smoke 任务**：`dev.ps1 -Task search-smoke` 对每家已配置 key 的提供器做一次只读真实
  查询（默认查询"鸣潮 守岸人"），输出 ok/延迟/命中摘要；**不发送任何 QQ/Telegram 消息**。
  实测当前 `.env` 的 `BOT_SEARCH_TAVILY_API_KEY`/`BOT_SEARCH_YOU_API_KEY` 均为空——
  **用户填 key 后重跑该任务即完成 P2.3 的逐家真实验收**（这是本轮唯一无法代办的收尾）。
- You.com 适配确认：现有 `YouSearchProvider`（POST、`X-API-Key`、body `{query,count}`、
  可选 `freshness` 等 options 透传）与官方 API 形态一致，无需改码。
- 验证：`365 passed`；Ruff 全过；mypy 176 源码文件无错。新增回归：Tavily extract、
  复合抓取链、builder 组合、一级参数注入（4 项）。
- **推送状态（重要）**：本地提交 `683ea06`（alpha.2 主体）已完成，分支 `v0.0.1-alpha.2` 与
  附注标签已创建；但对 origin 的多次推送均被远端挂断（HTTP 408 / curl 55 send failure，
  疑似本机到 GitHub 的网络对大 POST 不友好，`ls-remote` 可通）。已尝试 postBuffer 157286400
  与强制 HTTP/1.1。**如推送仍失败，可换网络/代理后执行：**
  `git push -u origin refs/heads/v0.0.1-alpha.2:refs/heads/v0.0.1-alpha.2` 与
  `git push origin refs/tags/v0.0.1-alpha.2:refs/tags/v0.0.1-alpha.2`
  （分支与标签同名，必须用完整 refspec）。

### 19.4 仍然未完成（承接第 6 节，优先级不变）

P0.1 真实 NapCat 重启验收、P0.2 FileTransferGateway（按第 17 节顺序须在真实验收之后）、P0.4 幂等表与 result-unknown 恢复、P0.5 记忆抽取实机验证、P1 全部、P2/P3 其余项均未变。runtime-layout 仍失败（源码 data 活动数据 + 少量缓存残留），按第 7/8 节流程处理，未强行清理。

### 19.6 2026-09-08 搜索 API 真实验收（Agent B，只读 smoke）

**结论：Tavily（主）与 You.com（备）真实账号 smoke 双双通过，全程只读、未发送任何 QQ/Telegram 消息，未改动任何代码。**

- **key 落位**：本机此前不存在任何搜索 API key（`.env`/环境变量/Runtime 均无）。用户提供后按 `.env.example:256-261` 约定写入 `.env`：真实 key 存 `BOT_SEARCH_TAVILY_API_KEY` / `BOT_SEARCH_YOU_API_KEY`，链路字段以 `env:` 间接引用（`BOT_WEB_SEARCH_TAVILY_API_KEY=env:BOT_SEARCH_TAVILY_API_KEY`、`BOT_WEB_SEARCH_YOU_API_KEY=env:BOT_SEARCH_YOU_API_KEY`）。`.env` 在 `.gitignore:23` 内，不会入库。
- **无 key 基线**（填 key 前跑了一次）：`[FAIL] chain 0ms no provider configured`，退出码 1——证明 smoke 工具链本身（模块导入、`.env` 加载、Runtime venv 调用、无 key 时快速失败不发音）行为正确。
- **真实验收**（`dev.ps1 -Task search-smoke`，查询词「鸣潮 守岸人」，各一次只读请求）：

  ```
  [OK ] tavily        3500ms  3 hits: 守岸人
  [OK ] you           4530ms  3 hits: 守岸人_百度百科
  search-smoke: at least one provider answered   （退出码 0）
  ```

- **观察**：两家延迟 3.5–4.5s，均略超 `BOT_WEB_SEARCH_TIMEOUT_SECONDS=3`——httpx 超时按 connect/read 分相计时，单相不超时则请求整体可超 3s；线上有 45s 故障转移总时限兜底，暂无需调参，但若后续观察到超时率上升可优先上调该值。
- **仍未覆盖（同日二轮演练后剩余）**：TinyFish / LangSearch 无 key 未验收；抓取回退链的 TinyFish fetch 半段同因未验；额度消耗需登 Tavily 控制台核查（key 为 dev 档 tvly-dev-，本轮全部实弹合计约消耗 5–6 个检索 credit，生产放量前需核查用量）。
- **同日二轮：真实故障转移与一级参数/extract 实弹演练**（全部在内存 Config 上改配置、不动 `.env`、不改代码；各场景一次只读请求；临时脚本放源码树外 `%TEMP%\search_drill_b\`）：
  - 端点不可达（`api.tavily.invalid` → TransportError，含 0.25s 原地重试）：链自动回退 You，3 hits，6.7s，`last_provider_name=you`；
  - 无效 key（401 HTTPStatusError，按设计不重试直接回退）：You 应答，3 hits，4.9s；
  - 一级参数实弹（`search_depth=advanced` + `time_range=month`）：Tavily 正常应答，3 hits 且首条为月内 TapTap 攻略贴（时效过滤生效迹象），8.4s；
  - Tavily extract 实弹：`example.com` 经生产类 `TavilyExtractFetchProvider` 取回 167 字符 markdown 正文（3.4s），解析键 `results[].raw_content` 与官方响应匹配；维基百科「守岸人」URL 在 Tavily 侧真实 404（响应 `failed_results`），适配器按设计返回空串、由上层通用抓取兜底——首轮演练该 URL 0 字符即此因，非缺陷。
  - **结论：Tavily→You 真实故障转移在传输错误与 401 两类失败下均验证通过；一级参数与 extract 半段回退链实弹可用。**

### 19.7 alpha.2 四轮增补：入站事件幂等表（P0.4 前半，2026-09-08 提交 62e6911）

- 新增 `runtime/event_idempotency.py`：进程内 TTL 幂等表（键 `adapter|bot_id|message_id`；
  缺稳定 message_id 的事件不去重避免误伤；同一键对同一 capability 只放行一次，
  **不同能力互不影响**——保护合法多 matcher 流程；TTL 与容量上限自动回收）。
- `RuntimePipeline` 新增可选 `idempotency_table`：在 `handle/handle_async` 最前判定，
  重复事件返回 `BLOCKED` 回执并写审计 `duplicate_event`（stage=policy）；
  幂等表异常时放行，不阻断主链路。
- 配置 `BOT_EVENT_IDEMPOTENCY_ENABLED`（**默认 false**——真实 NapCat 验收期间保持关闭，
  验收通过后再开启；TTL/容量可调，见 `.env.example`）。
- 验证：373 passed、Ruff 全过、mypy 177 源码文件无错；新增回归
  `tests/test_event_idempotency.py`（8 项：键构造、同能力拦截/异能力放行、TTL 过期、
  容量淘汰、pipeline 开关两侧行为）。
- **P0.4 后半仍未完成**：幂等表跨重启持久化（SQLite/文件快照）与出站 result-unknown
  全局恢复机制。
- 同轮收尾：并行会话（搜索验收）的 `fetch_page_text` 反注入/去广告加固已验证并代为提交
  （374 passed，提交 0f88976）；其 handoff §19.6 记录保持原样。

### 19.8 alpha.2 五轮增补：幂等表 SQLite 持久化（P0.4 后半之一，提交 c3aa200）

- 新增 `SqliteEventIdempotencyTable`：与进程内表同一 claim 接口，数据落
  `BOT_EVENT_IDEMPOTENCY_DB_PATH`（data/ 前缀自动重映射 Runtime 数据根）；
  wall clock 时间戳，**重启后重放事件仍被拦截**。
- 工厂 `build_event_idempotency_table`：开关关闭→None；db_path 非空→SQLite；留空→进程内表。
- 测试 377 passed（新增：跨实例拦截重放、TTL 过期重放放行、容量淘汰、工厂选型）；
  Ruff/mypy 全过。
- **P0.4 剩余**：出站 result-unknown 全局恢复机制（发送结果未知时的记录与重连对账）。
- **Git 状态**：分支 `v0.0.1-alpha.2`（c3aa200）与附注标签（指向 713e2bc）均已推送
  origin 并 ls-remote 验证；alpha.2 推送至此全部完成。

### 19.9 alpha.2 六轮增补：12 插件逐项硬对比与实装（2026-09-08）

用户要求"对比原生代码，原生不好就用插件替换，保持最佳性能"。逐项实测定论：

**已实装（2 项）：**

1. **htmlrender 的常驻浏览器模式 → 吸收进原生 `PlaywrightRenderBackend`**：
   原生实现每张卡片冷启动一个 Chromium（订阅批量推送每张多付数百毫秒启动税），
   借鉴 htmlrender 的常驻模式重写：懒启动、跨渲染复用、`new_page` 失败自动重启
   浏览器、渲染异常重置常驻实例、渲染完只关 page 不关 browser。
   未直接装 htmlrender 插件的原因：其产出与我们的 Mica 卡截图等价，装整插件会引入
   第二套浏览器管理与 alconna 依赖；性能收益全部来自生命周期模式，已原生吸收
   （`tests/test_render_backends.py` 断言两次渲染仅启动一次 Chromium）。

2. **nonebot-plugin-memes（表情包生成）→ 真实接入 venv + 守门加载**：
   我们只有表情包图库/搜索，没有**生成**能力——这是 12 个里唯一的能力空白实装项。
   `pip install nonebot-plugin-memes`（依赖链 uninfo/localstore/orm/waiter 已验证），
   `nonebot.init()` 后实弹加载成功；`bot.py` 守门加载（`BOT_MEMES_PLUGIN_ENABLED`，
   **默认 false**），加载失败仅打印降级告警不阻断主 bot。

**维持原生（10 项，代码级对比后原生胜出）：**

| 插件 | 对比结论 |
|---|---|
| tavily | 原生 4 家链式回退+瞬时重试+一级参数+extract 复合抓取、真实 key 验收；对方单提供器无回退 |
| with-ai-agents | 对方是独立 agent 运行时，与统一管线冲突；原生路由/故障转移/模型管理远超 |
| parser-lite | 原生 23 平台 vs 对方约 10；其评论区渲染记为后续增强 |
| personification | 群参与决策/用户画像清单记入 P1 参考；整体替换等于推翻统一运行时 |
| songpicker2 | 作者自述不稳定、仅网易云；原生 5 供应商+选流质量优先 |
| analysis_bilibili | 其 ExpiringCache 每项一线程（有缺陷）；原生 WBI+订阅管线完整 |
| multincm | 其"多候选编号点歌"交互记为 UX 增强；数据源单网易云 |
| help | 仓库已 Archived；原生 Mica 帮助卡逐参数写全 |
| disconnect_notice | 思路已原生落地（Telegram+邮件+冷却）；其 Server酱/PushPlus 渠道暂无对应账号 |
| WWwiki | 原生已有库街区 3 万条向量化知识库+MediaWiki；biligame 数据重叠，PIL 卡与 Mica 规范冲突 |

**TinyFish 端点核查（P2.3 尾巴）**：key 已入 `.env`（BOT_SEARCH_*）；默认
`api.search.tinyfish.ai/search` 与 `/extract`、`/v1/extract` 均 404（返回官网 HTML），
官方 API 路径已变更，需登录其控制台/docs 确认新端点后填
`BOT_WEB_SEARCH_TINYFISH_FETCH_ENDPOINT` 方可启用抓取半段；未确认前链路自动降级，
不影响 Tavily/You/LangSearch 已验收的三家搜索。
