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

### 19.10 alpha.2 七轮增补：multincm 多候选点歌移植（2026-09-08）

把评审矩阵中标记"可移植"的 multincm 编号选择交互真正落进原生点歌能力：

- `platforms_music.py` 新增 `search_netease_music_candidates`（一次搜索返回轻量候选
  {id/name/artist/album}，0 次额外请求）与 `netease_song_detail_by_id`（编号选定后取详情）。
- `capabilities/music.py`：歧义判定=无同名精确命中且候选≥2 → 返回编号列表
  （含有效期提示），按会话存 TTL 候选（默认 300s、上限 256 会话）；用户回复
  『点歌 <编号>』完成二次选择并写 `music_candidate_pick` 审计；编号选择意图
  （无会话/过期）不再触发新候选列表，直接走普通搜索防误触；精确命中沿用
  "直接播放"既有行为。渲染路径收敛为单一 `_render_hit`，消除两份重复代码。
- 配置 `BOT_MUSIC_CANDIDATES_ENABLED`（**默认 false**，保持既有"第一命中直接播放"）+
  TTL/条数可调（`.env.example`）；`/bot help 点歌` 已同步交互说明与常见错误。
- 验证：387 passed、Ruff 全过、mypy 177 无错；新增回归
  `tests/test_music_candidates_v2.py`（5 项：歧义列表、精确命中直播、编号选择、
  无会话回退、开关关闭保持旧行为）。
- 顺手修正：`RuntimePipeline.idempotency_table` 注解放宽为双后端联合类型（mypy）。

### 19.11 alpha.2 八轮增补：parser-lite API 移植第一批（2026-09-08）

用户提供 parser-lite 1.3.5 本地包（`Downloads\Archives\...`）。核查结论：`api_txt/` 是
**25 个平台的 API 响应样本集**（JSON fixtures + 2 个解码脚本），移植=按样本理解响应
结构实现原生解析。原生路由表已有 37 个平台条目，与样本集去重后**真空白 15 个**：
5eplay、buff、coolapk、douban、doubao、ds（抖音站内系列）、heybox、hupu、illu（米画师，
与原生 mihuashi 重叠待确认）、linux.do、qsmusic（全民K歌）、taptap、wmpvp、zhihu、zlb。

**本批已落地（3 项）：**

1. **B 站官方 AI 视频总结**（`bilibili/ai_conclusion.json` 样本 → 原生）：
   `platforms_bilibili.py` 新增 `_bilibili_ai_conclusion`（view/conclusion/get，WBI 签名，
   `BOT_BILIBILI_AI_SUMMARY=0` 可关）；解析 B 站视频自动追加「AI总结/AI大纲」行并存
   `detail.ai_conclusion`。实测该端点现已要求登录（code -101）——**导入 B 站 Cookie 后
   自动生效**，无 Cookie 静默跳过不影响主链路。
2. **UP 主获赞数**：`_author_enrichment` 增加 upstat（WBI 签名）调用，写入
   Creator.received_like_count 与统计行「获赞」；风控拦截时静默跳过。
   此前用户要的字段中播放/点赞/投币/收藏/转发/弹幕/评论数、发布时间（published_at
   精确到秒）、标题/封面/简介、UP 昵称/头像/签名（card sign）、粉丝/关注/视频数/专栏数、
   aid/bvid/UID 原生已有。
3. **平台凭证管理指令**（对标 parser-lite 的凭证指令）：新增
   `capabilities/platform_credentials.py` + 管理员 matcher（priority=8，复用
   `_is_admin_origin` 门控）：`cookie`/`凭证` 查看全部 17 平台凭证状态（只显示
   cookie 名与到期日，永不回显值）；`cookie import <平台> <Cookie头>` 把浏览器复制的
   Cookie 头追加写入 Netscape cookies.txt（同名不覆盖），解析链每解析重建 provider
   故即时热生效。测试 `tests/test_platform_credentials.py`（5 项）。

**配套改进**：`wbi.py` nav 签名键加 30 分钟线程安全缓存（此前每次签名都请求 nav）。

**后续批次（按优先级，见未完成清单）：**
- 批次 A（新平台）：zhihu、douban、taptap、coolapk、hupu → heybox、linux.do、doubao、
  qsmusic、ds → 小众对战平台（5eplay/buff/wmpvp/zlb，需玩家生态才有价值）；
  每平台流程=读样本 JSON → 写 platforms_<name>.py + 路由正则 → 解析回归测试。
- 批次 B（体验增强）：多候选点歌推广到 QQ/酷狗/酷我（酷狗需把 pagesize=1 改多候选，
  QQ 选曲受 vkey 登录门槛约束）；评论区渲染、Live Photo 渲染、图文/视频/音频渲染增强
  （依赖批次 A 的元数据字段齐全）；AI 总结推广到其他平台（逐平台找官方/模型侧端点）。
- 帮助与文档：新平台上线时同步 `/bot help` 主题与 COMMANDS.md。

### 19.12 alpha.2 九轮增补：TinyFish 修复/命令统一/防御强化/5 插件评估（2026-09-08）

1. **TinyFish Search 端点修复并真实验收（P2.3 搜索半段关闭）**：用户提供官方文档——
   新端点为 `GET https://api.search.tinyfish.ai`（旧 `/search` 后缀已 404）。已更新
   `_DEFAULT_ENDPOINTS["tinyfish"]` 并用真实 key 实测：ASCII/中文查询均返回结构化
   results[].{position,site_name,title,snippet,url}，原生 `TinyFishWebSearchProvider`
   代码路径实测 3 hits。search-smoke 全链四家就绪（tavily/you/langsearch 3 家当轮全绿）。
   **Fetch 端点仍未确认**（docs.tinyfish.ai 的 Fetch 页需登录态，直抓只得到 659 字节）；
   用户从 docs 复制 Fetch 的 cURL 示例后填 `BOT_WEB_SEARCH_TINYFISH_FETCH_ENDPOINT` 即启用。
2. **命令格式统一**：新增的管理指令一律 `/bot <模块词> <功能词> [参数]`。
   `/bot cookie` 模块已改造：`/bot cookie`（状态）、`/bot cookie status`、
   `/bot cookie import <平台> <Cookie头>`；不再接受裸 `cookie` 形式。测试同步更新（5 项）。
3. **防御强化（反注入/越界内容）**：`content_safety.py` 新增 `excessive_intimacy` 类别
   （温和重构不硬拒）——覆盖 强加称谓（叫我/喊我/当我/做我/当你 + 老婆/老公/爸爸/爸比/
   妈妈/妈咪/奶奶/姥姥/女儿/儿子/姐姐/哥哥/主人）、宠物化扮演（汪汪叫/当狗/做狗/
   像狗一样/趴好/拴住）。**管理员放宽**：`assess_public_content(..., admin=True)` 跳过
   `excessive_intimacy` 与 `persona_breaking` 两个软类别；色情/血腥/骚扰/政治四类硬
   类别对管理员依旧拦截。chat 能力按 `message.sender_roles` 传入 admin。新增回归
   2 项（越界样例 6 连测 + 管理员放宽/硬类别保持）。
4. **新一批 5 插件评估**（应用户要求）：
   - nonebot-plugin-memory（lanxinmob）：通用每用户 LTM；原生记忆抽取+向量知识+预算
     体系更深且已集成 → 维持原生，设计参考。
   - nonebot-plugin-datastore（he0119）：SQLAlchemy 统一存储层；原生为直连 sqlite3
     各存储（回执/队列/审计/记忆/遥测）。引入=全存储层重写，成本>>收益 → 不引入，
     记为"未来统一存储层"参考。
   - YetAnotherPicSearch（lgc-NB2Dev）：ASCII2D/Saucenao 反搜图——**原生确无此能力**，
     记为能力空白候选；需要 Saucenao/Ascii2d API key 与独立 matcher 装配，待用户提供
     key 后按 memes 模式（venv+守门加载）接入。
   - nonebot-plugin-mediawiki（KoishiMoe）：通用 MediaWiki 封装；原生 mediawiki.py 有
     精确命中逻辑+TTL 缓存+限流且已适配 → 维持原生。
   - nb2-wiki（ZombieFly）：功能子集 → 不引入。
5. **parser-lite 15 平台移植**：批次计划见 §19.11（zhihu/douban/taptap/coolapk/hupu 为
   批次 A 首选）；本批未新增平台，下一批按"读样本 JSON → 写解析 → 路由正则 → 回归测试"
   流程逐个落地。

### 19.13 alpha.2 十轮增补：TinyFish Fetch 闭环/记忆清洗/侮辱外号防御/后续路线图（2026-09-08）

1. **TinyFish Fetch 接入 + 四家搜索全线闭环（P2.3 完成）**：用户提供官方文档——
   Fetch 端点为 `POST https://api.fetch.tinyfish.ai`（body `{"urls":[...],"format":"markdown"}`）。
   已改 `TinyFishFetchProvider` 请求体与默认端点（`BOT_WEB_SEARCH_TINYFISH_FETCH_ENDPOINT`
   默认值已填），**真实 key 实弹抓取 example.com 正文成功**；测试断言同步新响应结构。
   至此 Search（Tavily 主/You 备/LangSearch 备/TinyFish）+ Fetch 正文抓取全部真实 key 验收。
2. **记忆库清洗（防御强化，用户授权）**：新增 `security/memory_sanitize.py`——扫描
   `memory_facts` 全部文本，按 5 类模式（nsfw/graphic_violence/insult/petplay/forced_persona）
   命中后先复制进 `memory_quarantine` 隔离表（含类别+时间，可审计可恢复）再删除；
   支持 `--dry-run/--apply`；dev.ps1 任务 `memory-sanitize`（`-Apply` 才真删）。
   **首轮实跑：17 条记忆全部干净，0 命中**。4 项回归测试。
3. **侮辱人格/恶意外号防御**：content_safety 新增 `insult_nickname` 类别（侮辱词根绰号、
   人格贬损句式 → 温和重构）；普通善意小名（"叫我小岸""阿月""团子"）不误伤；
   **侮辱他人对管理员也不放宽**（侮辱不是管理特权）。1 项回归（含小名放行对照）。
4. **后续路线图登记（用户 2026-09-08 指令，按批次推进）：**
   - **批次 C（社交记忆体系，P1 核心）**：好感度系统（增减规则+差异化态度）、用户
     身份/印象/标签（行为→印象→态度，不人身攻击）、角色小名/外号标签体系（被喊小名
     即出现并回应、可用小名称呼用户）、群聊公共记忆与多人复读/戏弄应对（"怎么一个个
     都当复读机"）、私聊=漂泊者/群聊=群昵称（非管理员禁用漂泊者称呼）。参考
     lanxinmob/memory、anywhere-llm、nyaturingtest 设计，代码自研。
   - **批次 D（群治理）**：群文件自动整理（学习 zhongwen-4/group-file-admin 思路自研
     并改进）；逆天发言检测撤回（学习 PamiNET/nodirtymsg 算法思路，**不复制代码**，
     该仓库只读无人维护）。
   - **批次 E（管理员绑定）**：两个管理员账号（澜汐/霞月）绑定同一人，称呼可用
     Lancy/LancyCelestia——**待用户提供两个 QQ 号**后写入 `BOT_ADMIN_USER_IDS`
     （或用户自行 `/bot runtime set BOT_ADMIN_USER_IDS [号1,号2]`）。
   - **批次 F**：说人话（去 AI 味）应用于回复整理层（strip_outer_speech_quotes 之后）。
5. 验证：398 passed；Ruff/mypy 全过。

### 19.14 alpha.2 十一轮增补：并行大交付（2026-09-08）

用户要求"一次性并行完成 handoff 未竟项（P0.4 尾/批次 A/B/C/D/E/F）"。本批交付：

**P0.4 完成：出站 result-unknown 账本与重连对账**
- 新增 `runtime/result_unknown.py`：OneBot 发送超时（结果未知）持久化到
  `data/result_unknown.sqlite3`（按 request_id 去重）；`on_bot_connect` 自动对账——
  超 24h 的标记 expired，仍 pending 的写 `result_unknown_reconciled` 事件。
  设计上不做自动重发（OneBot 无法查询历史消息是否送达，盲发会重复）。测试 3 项。
- 排查了用户报告的 `[运行时告警] stage=onebot kind=send_exception source_bot=3958874605`：
  该 bot 是 Mail 适配器账户（3958874605@qq.com），根因=SMTP 发信异常重试 3 次失败
  （日志已轮转无法取详情）；属邮件通道已知韧性场景，不影响 QQ 主链路，告警抑制器
  已有 5 分钟窗口防刷屏。

**防御强化补全（用户点名）**
- `insult_nickname` 类别：侮辱性外号/人格贬损（"以后就叫你死胖子/给你起外号叫蠢驴/
  你就是个废物"）→ 温和重构；普通善意小名（小岸/阿月/团子）不误伤；
  侮辱类对管理员也不放宽（侮辱不是管理特权）。测试含正反对照。

**批次 C 第一批：动态好感度 + 群聊复读**
- 新增 `character/affinity.py`：SQLite 行为驱动好感度（positive +0.02 / tease -0.01 /
  negative -0.05 / insult -0.10，clamp [0,1]）+ 印象标签（友善/老朋友/爱抱怨/口无遮拦/
  爱戏弄，按累计行为打标）+ 四档态度（亲近/友善/客气/严厉——最低档也绝不辱骂）。
- 融合规则：行为层有记录时覆盖 RelationshipContext 的 affinity/attitude；
  静态档案的称呼/偏好/备注保留。chat 层每条消息自动观察（safety 联动分类）。
- 新增 `runtime/parrot.py` 群聊复读检测：窗口（60s）内 ≥3 个不同用户发同一文本 →
  吐槽一次（"怎么一个个都当复读机…"），冷却 300s；bot 自身/指令/长文本不参与。
- 配置：`BOT_AFFINITY_ENABLED`（默认开）、`BOT_PARROT_*`。
- 小名体系：`DynamicAffinityStore.set_nickname`（用户昵称存储已就绪），
  `/bot` 管理指令与"被喊小名即出现"的 mentions 联动列入下一批（需 mentions 层配合）。

**批次 A 首批三平台：知乎/豆瓣/TapTap**
- 新增 `platforms_zhihu.py`（answer/article v4 API）、`platforms_douban.py`（rexxar
  topic API）、`platforms_taptap.py`（webapiv2 moment/video）；路由正则注册 +
  Cookie 平台键（d_c0/dbcl2 等）+ 契约对齐（`-> ParsedContent`，未匹配 URL raise）。
  测试用 parser-lite 样本 JSON mock 验证（含字段/路由/未知 URL 三类，共 5 项）。
  知乎/豆瓣未登录可能 403——导入 Cookie（`/bot cookie import zhihu ...`）即增强。

**批次 B 首批：多候选点歌推广到 QQ/酷狗/酷我**
- `platforms_music.py` 新增 `search_qqmusic_candidates/kugou_candidates/kuwo_candidates`
  （QQ n=5、酷狗 pagesize 1→5、酷我 rn=5）；候选详情函数签名升级为
  `detail_fn(candidate, *, query)`：网易云按 song_id、酷我走真实 wapi 详情、
  QQ/酷狗从候选直接构建（QQ 音频本就受 vkey 登录门槛约束）。四平台全部支持编号选择。

**批次 F 首批：搜索结果质量过滤（污染源处理，用户提问的落地）**
- `web_search.py` 新增 `filter_search_hits`：低质域名（pinterest/csdn 登录墙/quora/
  百度跳转链/docin 等文库农场）直接剔除；短摘要命中降权排后不丢弃。链式回退返回
  前统一过滤——**搜索结果是污染源时的处理路径：先域名黑名单→正文去噪（已有的
  HTML 注释/隐藏块剥离）→ Prompt 前信任边界（safety context 隔离），三层递进。**

**其余核查结论**
- mediawiki（KoishiMoe）/nb2-wiki 复核：未发现值得吸收的独有能力（前者核心是
  基于 infobox 的模板化摘要，与我们定向提取+LLM 摘要路线重叠；后者功能子集）。
- analysis_bilibili：独有可吸收点已确认仅 ExpiringCache（实现有缺陷不采用）；
  其 UP 空间/排行 API 我们已用更好实现。
- YetAnotherPicSearch 接入步骤已给用户（Saucenao/Ascii2d key 获取教程），
  配置就绪后按 memes 守门模式接入。
- 双管理员：`BOT_ADMIN_USER_IDS=["3865067623","1722380002"]` 已确认在 `.env`
  （澜汐/霞月两账号同权，称呼 Lancy/LancyCelestia 用于人格 prompt 层）。

验证：416 passed；Ruff 全过；mypy 185 源码文件无错。

### 19.15 alpha.2 十二轮增补：全平台覆盖/搜图/小名联动/评论区/说人话/群治理（2026-09-08）

用户一次性下达批次 A/B/C/D/E/F 全量并提供了三把 key。本批交付：

**批次 A 完成——15 个真空白平台全部接入（共 11 个新解析文件路由）**
- linux.do + zlb.ink（Discourse 共用解析器，/t/{id}.json → 标题/作者/首楼正文/回复数/点赞数/发布时间）
- 酷安（__NEXT_DATA__ feed props：动态正文/作者/点赞/评论/时间/图组）
- 虎扑（bbs-mobileapi + md5 签名 HUPU_SALT，样本暴露的签名算法原生实现）
- 完美对战（news getAppNewsById）、5E（forum/topic/{id}）、网易大道 ds（facade feedId）
- 汽水音乐（分享页 loaderData track 解析）、豆包 AI 视频（get_video_share_info，
  play_info/user_info/prompt 结构，AI 生成标记）、米画师 illu + BUFF（无公开详情 API → OG meta 兜底）
- heybox 确认与现有 xiaoheihe 同 API（无需重复）
- 路由+Cookie 平台键（linuxdo/d_c0、coolapk/dkToken、hupu、buff/session）+ 8 项样本 mock 测试

**SauceNAO 反搜图（YetAnotherPicSearch 能力空白，原生实现）**
- `sources/sauce_search.py`：db=999 全库、similarity 排序、解析 title/member/ext_urls；
  **真实 key 实弹通过**（B站封面 80.4% 识别出画师 Mikaduki Neko）。
- 能力 `bot.image_search`：`搜图` + 同条消息图片 → 反搜结果（相似度/标题/作者/链接）；
  matcher priority=46 经统一管线，key 可 `BOT_SAUCENAO_API_KEY` 或 env:SAUCENAO_API_KEY。

**小名体系 mentions 联动（批次 C）**
- `/bot 昵称 set <QQ号> <小名>`（管理员）写入 user_affinity.nickname；
- mention 判定链追加动态小名扫描（60s 缓存全表快照）：**用户喊任意已设小名即可唤醒对话**；
- prompt 侧此前已支持用小名称呼用户（快照 nickname 字段）。

**批次 B：B站热门评论区渲染**
- 视频解析新增 x/v2/reply 热门评论前 3 条（作者/文本/点赞）进 detail.hot_comments；
  解析卡评论区区块渲染（失败静默）。LivePhoto 属 iOS 私有格式（OneBot 不支持
  发送）→ 不实现，记录原因。

**批次 F：说人话输出层**
- `output/plain_text.py` 新增 `humanize_reply`：确定性剥离 AI 客套开场
  （好的！/当然可以/以下是/没错）与总结腔收尾（总之/综上所述/以上就是全部内容/
  希望这能帮到你/有问题随时问我），已接入 chat 输出链（naturalize 之后）。

**批次 D：群文件整理 + 逆天发言撤回（自研，未复制任何插件代码）**
- `capabilities/group_files.py`：GroupFileStore 记录 group_upload notice
  （群/文件/大小/时间）→ `/bot 群文件` 输出统计（总量/类型分布/最近列表/整理建议；
  OneBot 无文件夹移动 API，诚实落地为记录+统计+提醒）。
- DirtyGuard 逆天发言检测：severe（违禁/危害类）→ 可撤回（delete_msg，需群管理员
  权限）、warn（辱骂类）→ 仅记录；`BOT_DIRTY_GUARD_ENABLED`（默认关）+
  `BOT_DIRTY_GUARD_DELETE`（默认关）双层开关，误伤风险受控。

**运行时告警修复（用户贴的三类报错）**
1. Telegram 轮询重复堆栈刷屏（代理抖动，16:48/17:40/19:10 三条）：之前 5 分钟
   限速仍放行全栈；现改为**完整堆栈直接吞掉**（韧性层的简短重试行保留），
   恢复后打一条 "Telegram poll recovered"。轮询失败本身由适配器自动重试，无需干预。
2. `stage=onebot send_exception source_bot=3958874605`：Mail 账户 SMTP 发信异常
   （重试 3 次），属邮件通道已知场景；QQ 主链路不受影响。
3. `stage=llm deadline_exceeded / auth`：外部 LLM 服务超时/认证失败，failover 总时限
   45s 已兜底重试其他模型；如持续出现请 `/bot llm` 检查当前 provider 健康。

验证：428 passed；Ruff 全过；mypy 191 源码文件无错。key 全部只入本地 `.env`（不入库）。

### 19.16 alpha.2 十三轮增补：启动闪退修复/点歌默认语音/小名自学/全球天气/告警降噪（2026-09-08 晚）

用户报告启动闪退并提供运行日志。根因与修复：

1. **启动闪退（P0 修复）**：`NameError: build_character_affinity_store is not defined`——
   该函数上一轮被 append 到 `__init__.py` 文件末尾，而模块加载时
   `_register_nonebot_handlers()`（4708 行）在定义之前调用它。已把
   `build_character_affinity_store`/`_affinity_store_runtime` 移到定义调用点之前，
   插件导入验证通过。**教训：模块加载期执行的顶层调用，其依赖函数必须放在调用点之前。**
2. **点歌默认发送语音**：默认输出模式从 `card` 改为 **`card+voice+link`**（卡片/封面 +
   语音试听 + 链接）。音质链本就是最优优先：登录态下 Hi-Res（999000kbps）→ 320kbps →
   outer 直链兜底；`BOT_MUSIC_MODE` 运行时设置仍可覆盖（当前无持久覆盖，重启即生效）。
   "未提供音乐卡片"提示是网易云卡片数据缺失的正常降级（封面替代）。
3. **小名自学（不再只靠管理员指令）**：用户说"叫我XX/你可以叫我XX/以后叫我XX"时
   自动提取并写入昵称（正则抽取，1-12 字，与现昵称不同才覆盖）；群友互相称呼的
   采纳需对话上下文消歧，列入后续。
4. **全球天气兜底（海外/街道级）**：NMC 城市库查不到时自动降级 **Open-Meteo**
   （geocoding+forecast，免 key、点位级精度覆盖乡镇/村庄/海外）；
   同名地名按人口排序取主要城市（修复"高雄"命中四川同名村）；
   网络抖动静默降级不影响 NMC 主路径；代理透传（`bot_download_proxy`）。
   本机验证窗口期实弹返回过真实数据（高雄 25.1°C 阴）；乡镇级中文 geocoding
   覆盖有限属数据源能力边界。
5. **控制台报错修复（断网场景）**：用户贴的 gaierror/Mail TimeoutError/TG NetworkError
   全部源于**本机断网**（DNS getaddrinfo failed），各通道重试行为正常。三项降噪：
   - TG 轮询完整堆栈直接吞掉（韧性层简短行保留），恢复打 "poll recovered"；
   - **asyncio 裸 future 堆栈**（"Task exception was never retrieved" 40 行）：
     `bot.py` 注册 loop exception handler，网络类异常降为一行 WARNING 摘要
     （不掩盖：类型与错误仍可见），非网络异常走默认处理器；
   - Mail worker 断网期重试日志稀疏化（第 1/2/4/8... 次打 ERROR，其余 DEBUG）。
   llm timeout/schema/auth 与 result_unknown/send_exception 的 [运行时告警] 推送
   属正确的管理员通知机制（按要求"不掩盖 bug"保留），不是 bug；
   auth 频繁出现请 `/bot llm` 检查 provider 健康。
6. heybox 复核：与现有 xiaoheihe 同 API，无需重复接入。

验证：428 passed；Ruff 全过；mypy 192 源码文件无错。

### 19.17 alpha.2 十四轮增补：启动确认/被动感知/画像提取/音乐模式（2026-09-08 晚二）

1. **"无法启动"排查结论**：`startup-smoke` 干跑通过（27 matcher）+ 直接运行 `bot.py`
   实测正常（NapCat connected、群消息正常处理、Uvicorn 8080）。用户此前看到的闪退
   是 §19.16 已修复的 NameError（旧代码）或**双开实例 8080 端口占用**（第二个实例
   立即退出表现为"闪退"）。重启前请先在任务管理器确认旧 python 进程已全部结束。
2. **被动感知（白名单2 也生效）**：观察从 chat 能力层移到 `_handle_chat` 入口——
   所有到达 handler 的群/私聊消息（含白名单2 不 @ 的）都会：
   - 行为观察（好感度/印象标签累计）；
   - **画像自述提取**：正则识别"我来自X / 我今年X岁 / 我是X / 最近在X / 我喜欢X /
     爱X / 擅长X / 在玩X"写入 `profile_notes`（去重上限 12 条），注入 prompt
     "已知画像：…可在对话中自然体现，不逐条复述"；
   - 小名自学（"叫我XX"）。
   印象/画像只影响语气，不改变回复策略（白名单2 依旧只 @ 才回）。
3. **群友称呼采纳（@解析）**：本轮完成被动感知基座；"采纳群友对某人的称呼为昵称"
   涉及 @ 段归属消歧（防止乱起外号污染），列入下一批。
4. **音乐信息布局确认**：现状已符合要求——歌名/歌手/专辑/链接合并在一条文本消息，
   语音/音频是独立消息单独发送（OneBot record/file 段与文本段分投）。
   默认模式本轮已改 `card+voice+link`，音质链 Hi-Res→320k→试听。
5. 顺手修复：EscapeWarning 清零（正则 raw string 化）、I001/F401 清理。
6. 验证：428 passed（0 SyntaxWarning）；Ruff 全过；mypy 192 源码文件无错；
   bot.py 启动实测 NapCat connected + 群消息处理正常。

### 19.18 alpha.2 十五轮增补：全量 Cookie 生效/点歌信息修复/B站字段归位/Help图修复/TG图文/模板压缩（2026-09-08 深夜）

用户提供了浏览器全量 cookies.txt（2936 行）与五组问题。本批处理：

1. **Cookie 全量导入（重大解锁）**：用户文件直接落位
   `ChatBot_Runtime/data/platform_cookies.txt`（Netscape 2899 条全解析）。
   **17/18 平台登录态生效**：B站(SESSDATA/bili_jct)、网易云(MUSIC_U)、知乎(d_c0)、
   微博(SUB/SUBP)、抖音(sessionid)、QQ音乐、酷狗、酷我、小黑盒、Twitter、YouTube、
   库街区、萌娘、AcFun、快手、斯克兰、米游社。生效即解锁：B站 AI 总结+高清视频解析、
   网易云 Hi-Res/320k 音质、知乎登录态解析等。重启后自动生效（解析链热读）。
   `credential-smoke` 可随时复查到期状态。
2. **点歌只发语音（已修）**：`BOT_MUSIC_MODE` 三处持久设置均无覆盖——用户看到的
   是旧默认 card 时代行为；当前默认 `card+voice+link`（♪歌名/歌手/专辑/链接一条文本
   +封面+语音独立发送），重启即生效。
3. **B站字段归位**：粉丝/关注/视频数/专栏数/获赞从视频数据栏移除，
   仅保留在作者栏（Creator 字段：follower_count/following_count/video_count/
   received_like_count 等），视频栏回归播放/点赞/投币/收藏/分享/弹幕/评论。
4. **Help 图片版消失（根因修复）**：常驻浏览器重构引入**线程绑定回归**——sync
   playwright 对象只能在创建线程使用，help 渲染工作线程调用即静默失败降级纯文字。
   已改线程局部存储（每线程各自常驻实例），跨线程双实测 OK，帮助图恢复；
   一级分组（解析/点歌/天气/凭据等【】区块）与二级详情（`/bot help <主题>`）
   结构本就存在，图片恢复后即完整可用。
5. **Telegram 图文同发（修复）**：TG sender 此前只发 text 丢弃图片；现支持
   `send_photo(chat_id, photo=<图片URL>, caption=文字)` 图文一条（caption 上限 1024）。
6. **解析模板压缩**：UP主头像栏 80→56px、二维码 88→60px、作者字号 18→15px
   （约 1/3 压缩，减少空隙）。
7. 断网降噪补全（Mail 稀疏日志/loop handler/TG 恢复提示）见 §19.16；本轮验证全绿。

验证：428 passed；Ruff 全过；mypy 192 源码文件无错。

### 19.19 alpha.2 十六轮增补：实卡反馈修复批（2026-09-08 深夜二）

用户实卡测试反馈六组问题，全部定位并处理：

1. **点歌仍不发信息/链接（真根因找到）**：上轮只替换了一处 mode fallback——群聊
   自然语言分支（2963 行）与 music matcher 分支（4395 行）的
   `or "card"` **仍在**。本轮两处全部改为 `bot_music_default_mode`（card+voice+link）。
2. **B站作者栏数据全空（上轮迁移的映射断裂）**：`_author_enrichment` 的 counts
   （视频数/专栏数）没有写进 author 标准键，Creator 消费不到。已补
   `video_count`/`post_count`；粉丝/关注/获赞原有链路（fans/following/received_likes）
   映射表确认在位。
3. **发布时间补秒**：B站摘要发布时间从 `年月日` → **`年月日 时:分:秒`** 完全体。
4. **AI 总结/大纲（解释+分隔）**：数据源是 B站官方 AI 接口（基于视频字幕/内容生成，
   非简介；字幕缺失或低质量时内容可能难懂——数据源限制非代码问题）。
   已在简介与 AI 内容之间插入空行分隔。
5. **热评缺失**：热评此前只进 detail 未渲染；现在热门评论前 3 条（作者/内容/点赞）
   直接进摘要"热门评论"区块，纯文本与解析卡都能看到。
6. **"提示没有 Cookie"**：Cookie 文件已落位且 17/18 平台验证生效——截图的小红书
   浅层提示是**旧进程未重启**的表现；重启后解析链即读到新 Cookie。
   （小红书正文/图集接口即使有 Cookie 也可能要求更高级别登录态，属平台风控。）
7. **UI 调整（按截图逐项）**：二维码 60→56px 与头像等高、容器 padding 4→2px、
   UP主栏整体压缩；左下角平台 Logo 与右上角统一平台色（color-mix 派生）；
   右下角"守岸人/Shorekeeper Parser"中英文统一 14px、统一淡平台色；页脚
   padding 14→8px、头像 30→24px 整体压缩。
8. **Help 引导**：初始页副标题改为明确引导"输入 /bot 帮助 <模块名> 展开该模块的
   命令与参数详情"。三级菜单（模块→命令→参数）结构在 detail 里已具备。
9. **诚实记录（未完成，下批）**：YouTube/Twitter 深度博主数据（订阅数/加入时间/
   长短视频数/签名）需要频道 about 页与 GraphQL user 字段的额外 API 调研，
   与平台风控对抗，单独立批处理。媒体选流优先级（杜比视界>HDR>8K>4K>2K>1080P、
   杜比全景声>Hi-Res）此前已实现（见记忆 chatbot-media-download-quality）。

验证：428 passed；Ruff 全过；mypy 192 源码文件无错。

### 19.20 alpha.2 十七轮增补：重启生效实证/字段类型修复/YT-Twitter 深度数据确认（2026-09-08 深夜二）

用户反馈"没改过来，没有任何生效"。排查结论：

1. **"没生效"= 旧进程**。实测证据：当前 8080 无监听、无存活 python 进程（旧实例已退），
   代码侧两处 mode 分支均已是 `bot_music_default_mode`（grep 验证无 `or "card"` 残留），
   模拟解析路径输出 `card+voice+link`。**下次启动即全量新代码**；若再遇"闪退/不生效"，
   先任务管理器确认旧 python 进程已全部结束再启动。
2. **B站作者栏字段类型修复**：`fans`/`received_likes` 原是字符串（int() 转换被覆盖），
   已强制 int；`video_count`/`post_count` 键名对齐（counts["视频数"]→video_count、
   counts["专栏数"]→post_count）；补 `following_count`。带 Cookie 实测：
   `{'fans': 945086, 'video_count': 258634, 'post_count': 1, 'received_likes': 7054035}`
   全 int 到位，Creator 字段（follower/following/video/获赞）重启后完整填充。
3. **YouTube/Twitter 深度博主数据（更正 §19.19 的"下批"判断）**：复查发现
   `_youtube_about_enrich` **早已提取**订阅数/视频数/加入时间/简介/认证，消费链
   `stats["订阅"]→Creator.follower_count`、`created_at→joined_at` 完整在位；
   **Twitter 实弹实测**：签名/粉丝529/关注536/帖子6/加入时间 2023-06-12 全部返回。
   §19.19 将其记为"下批"是过时判断，以本节为准。
   短视频/长视频分列 YouTube 页面不提供（频道的 shorts 计数需额外分类抓取），
   仍记为数据源边界。
4. UI 调整（二维码等高/Logo 统一/守岸人淡粉/页脚压缩）与 Help 引导见 §19.19，
   重启后生效。
5. 验证：428 passed；Ruff 全过；mypy 192 源码文件无错。

### 19.21 alpha.2 十八轮增补：NapCat 登录冲突处置/TG 图文本地卡修复/TG 点歌语音补全/TG help 无声修复（2026-09-09 凌晨）

**现场**：用户重启电脑后反馈 NapCat 连不上（二维码已保存+「当前账号(3958874605)已登录，无法重复登录」×2）；TG 端点歌有封面无语音、带图链接解析只有文字没有图、`/bot help` 完全无回应（重启电脑依旧）。

**取证结论（全部实机验证）**：
1. **NapCat**：NapCat 以框架模式跑在 QQNT 内（QQ.exe PID 持有 6099 WebUI），OneBot 为 WS 服务端模式（127.0.0.1:3001，token ShoreKeeper，配置 C:\Software\NapCat\config\onebot11_3958874605.json）。实测 3001 无监听；bot（python bot.py，forward-WS 客户端，.env.prod `ONEBOT_WS_URLS`）会自动重连，无需重启。二维码+「已登录无法重复登录」组合 = 快速登录残留会话与当前 NT 会话状态冲突，账号登录没走完 → OneBot 服务没起。
   **处置序列**：`C:\Software\NapCat\KillQQ.bat` 杀净 QQ → `launcher.bat` 重拉 → 等快速登录成功（WebUI http://127.0.0.1:6099 看状态）→ `netstat -ano | findstr 3001` 见 LISTENING 即恢复；仍报错则在登录窗手动扫码一次刷新本机会话。
2. **TG 图文没图（root cause）**：`sender/nonebot.py` 旧逻辑只把 `http(s)://` 开头的图片部件交给 send_photo——解析卡/帮助卡是**本地渲染 PNG**，直接被跳过落到纯文本；点歌封面是远程 URL 所以能显示。修复：`_telegram_photo_reference` 支持本地存在的文件（适配器 `process_input_file` 原生读本地转 multipart，≤10MB 校验）。
3. **TG 点歌无语音（root cause）**：renderer 把 music 的 record part 透传到 parts，但 TG 分支只处理 image/file，record 被整体忽略。修复：新增 `_prepare_telegram_voice`——sendVoice 仅认 OGG/OPUS，非 .ogg 源先 httpx 落地 + ffmpeg 转 OGG/OPUS（`%TEMP%/bot_tg_voice` 按 md5 缓存），ffmpeg 不可用或转换失败降级 sendAudio（mp3 附件可播），下载失败再降级直链 audio；语音发送异常只告警不炸图文。
4. **TG help 无回应（root cause）**：help 图片变体 `body=""`，旧代码 `text` 为空直接 SKIPPED，图片部件根本没机会发送。修复：空文本仅在「无 TG 媒体部件」时才 SKIPPED；媒体全部不可发且无文本时显式 raise（FAILED_RETRYABLE + 运维通知），不再无声吞掉。
5. 附带：caption >1024 时不再硬截断——图先发，正文单独成条；图片发送失败降级纯文本，避免队列重试造成重复图。

**验证**：`tests/test_nonebot_sender.py` 新增 5 回归（本地卡无文本直发 photo、封面+语音降级 audio、ffmpeg 转换走 sendVoice、图片失败回退文本、媒体不可发非静默）；dev.ps1 lint/typecheck/test 全绿（433 passed，mypy 192 文件 Success）。NapCat 侧为运维处置，无代码改动。
