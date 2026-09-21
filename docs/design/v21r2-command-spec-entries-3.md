# V21R2 命令规格 · 全量条目正文 Part 3（模型 / 系统 / 帮助 · 管理面）

> 模板与九形态标注规则同 Part 1 头注。本部分全部为管理面（`/bot` 前缀族，路由 ADMIN @11 或独立 matcher）；四段式按 R4 规则加领域段，旧 `/bot <topic>` 形态全部兼容保留。

## 十二、领域：模型（model）

#### E-45 模型·渠道（/bot 模型 渠道 list|set|add|update|priority|effort|think|price|search|health|probe|routes|vision|remove|reset + 诊断）
- 四段式：`/bot 模型 渠道 <函数> [参数…]`；诊断=`/bot 模型 渠道 诊断`
- 旧形态：/bot model <函数>…；/bot llm（诊断）；别名 模型/model/llm/渠道/切换模型。echo.py 863
- 九形态：EN全=model(既有)｜EN简=—｜EN语=switch model(既有 切换模型)｜简中=模型/渠道/切换模型(既有)｜繁中=模型(同形)｜中简=—｜拼全=qudao(既有别名 渠道)/moxing(建议,未占用)｜拼首=qd(慎,多义,观察)｜组合=llm setup(接入域既有)
- 权限：管理员（改动即时生效；key 永不回显，群聊禁发真实 Key 用 key=env:变量名）
- 参数（逐函数）：| 函数 | 参数 | 类型/必填 | 可用范围 | 默认 | 用途 |
|---|---|---|---|---|---|
| list | 无 | — | — | — | 看底表（候选/档位/顺序/时段分组/健康/价格） |
| set | id\|auto | 必填 | 注册表 id 或 auto | — | 手动钉死模型；auto 撤销。优先级：手动指定>时段组 order>基础 priority |
| add | `<id> model= base_url= key= [tags=] [effort=] [group=] [priority=]` | id/model/base_url/key 必填 | model=供应商模型名原样；base_url=http(s):// 开头一般 /v1 结尾；key=sk-xxx 或 env:变量名；tags=档位逗号分隔；priority=整数越小越先 | priority 默认 100 | 免重启扩容 |
| update | `<id> <键=值...>` | 必填 | 只写要改的键：model/base_url/key/group/tags/effort/priority | — | 换 key/改档位，可覆盖 .env 同名条目 |
| priority | id＋n | 必填 | n 整数 1..N 唯一槽位（移动一个其余顺移；0 兼容=移到首位） | — | 调故障转移顺序（控成本） |
| effort | id＋档位 | 必填 | off/low/medium/high/xhigh/max/default（default/默认/reset=清除覆盖回家族基线） | — | 单模型推理强度 |
| think | 档位 | 留空=清空 | off/low/medium/high/xhigh/max | 留空=清除 | 全局推理开销；复杂任务会临时升档 |
| price | 模型名＋[input=/output=/cache_read=/cache_creation=/per_call=] | 模型名必填 | 元/1M tokens；per_call=元/请求按次计费；数字≥0；不带价格参数=清除 | — | 计费基准；只影响之后的调用 |
| search | on\|off | 必填 | on/off | — | 热控 web_search |
| usage | today\|YYYY-MM-DD | 否 | today/今天/YYYY-MM-DD | 今天 | 日账单（Token 四项+费用+按模型明细） |
| health | 无 | — | — | — | ok/踢出/慢渠道三段（EWMA 平滑延迟） |
| probe | 无 | — | 每渠道一次最小调用（费用极低；与后台巡检互斥） | — | 手动全渠道体检 |
| routes | 模型名 | 必填 | 注册表内模型名 | — | 渠道测速排名（快→慢） |
| vision | list\|add\|update\|priority\|remove + mode relay\|direct | 子函数各异 | 同模型条目参数 | — | 识图模型管理与模式（relay=视觉模型转文字；direct=图片直传主模型） |
| remove | id | 必填 | .env 来源不可删 | — | 删除条目 |
| reset | 无 | — | — | — | 回自动选型 |
| 诊断(/bot llm) | 无 | — | — | — | 当前渠道 provider/model/key 状态+一次短调用（会花钱） |
- 取值范围（档位族）：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high。
- 语义：模型注册表+故障转移+渠道健康+思考强度+计费总控台；/bot model 与 /bot runtime model 等价。
- 示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1｜/bot model priority myapi 1｜/bot 模型 渠道 health
- 错误反馈：key 永不回显；model list 显示候选配置≠上一条实际回答的供应商；/bot llm 会产生新诊断调用（真值源原文）

#### E-46 用量（/bot 模型 用量 [日期] + 价格）
- 四段式：`/bot 模型 用量 [today|YYYY-MM-DD]`｜`/bot 模型 价格 <模型名> [input= output= …]`
- 旧形态：/bot model usage [日期]；/bot model price …；别名 用量/usage/账单/花费/监控。echo.py 927
- 九形态：EN全=usage(既有)｜EN简=—｜EN语=token usage(建议)｜简中=用量/账单/花费/监控(既有)｜繁中=用量(同形)｜中简=—｜拼全=yongliang(建议,未占用)｜拼首=yl(慎:`yl`=娱乐多义,观察)｜组合=—
- 权限：管理员
- 参数：| 日期 | today/今天/YYYY-MM-DD | 否 | 格式错回用法 | 今天 | 查当日账单 |
| 价格参数 | input=/output=/cache_read=/cache_creation=/per_call= | 否 | 元/1M tokens；per_call 元/请求；≥0；不带=清除 | — | 维护价格（同 E-45 price） |
- 取值范围（阈值 .env 键）：BOT_USAGE_ALERT_OUTPUT_TOKENS（默认 5,000,000）、BOT_USAGE_ALERT_INPUT_TOKENS（默认 50,000,000）、BOT_USAGE_ALERT_DAILY_COST_YUAN（默认 10）、BOT_USAGE_REPORT_HOURS（逗号分隔整点，默认 13,18,23）。
- 语义：Token 账单+价格维护+实时阈值提醒+13/18/23 点定时报告（推全部管理员 QQ 私聊，渲染附 Mica 账单卡）。
- 示例：/bot model usage 2026-09-01｜/bot 模型 用量 today
- 错误反馈：每项实时提醒每天最多触发一次；报告时间点持久化（真值源原文）

#### E-47 搜索（/bot 模型 搜索 <问题>）
- 四段式：`/bot 模型 搜索 <问题>`
- 旧形态：/bot search <问题>；别名 搜索/search。echo.py 998
- 九形态：EN全=search(既有)｜EN简=—｜EN语=web search(建议)｜简中=搜索(既有)｜繁中=搜索(同形)｜中简=—｜拼全=sousuo(建议,未占用)｜拼首=ss(慎:`ss`=多义网语,观察)｜组合=—
- 权限：管理员
- 参数：| 问题 | 文本 | 是 | 任意问题 | — | 真实检索一次（Tavily 主链+fallback），至多 BOT_WEB_SEARCH_MAX_RESULTS 条（默认 12） |
- 语义：验证联网检索链路（不走人格链路）。
- 示例：/bot search 守岸人是什么游戏的角色
- 错误反馈：检索源不可达/被反爬/代理未生效→降级说明（真值源原文）

#### E-48 接入（/bot 模型 接入）
- 四段式：`/bot 模型 接入`
- 旧形态：/bot setup llm；别名 接入/setup/llm setup。echo.py 667
- 九形态：EN全=setup(既有)｜EN简=—｜EN语=setup guide(建议)｜简中=接入(既有)｜繁中=接入(同形)｜中简=—｜拼全=jieru(建议,未占用)｜拼首=jr(留作金融领域,见 §4.1 冲突注)｜组合=llm setup(既有)
- 权限：管理员
- 参数：| — | 无 | — | LLM 七键体检：BOT_CHAT_PROVIDER=openai_compatible\|static；MODEL=供应商模型名；KEY=真实密钥或 env:变量名；BASE_URL=http(s):// 开头一般 /v1 结尾；TEMPERATURE=0.0-2.0；MAX_TOKENS=≥0（0=不设上限）；TIMEOUT=>0 秒 | — | 逐键：说明+取值范围+当前值+OK/缺口 |
- 语义：OpenAI 兼容接入清单（Mica 配置卡），密钥只显示 已设置/缺失，只读不写 .env。
- 示例：/bot setup llm
- 错误反馈：改 .env 需重启生效；就绪后用 /bot llm 真实连接诊断（真值源原文）

#### E-49 供应商（/bot 模型 供应商——配置型说明页）
- 四段式：`/bot 模型 供应商`（说明页）
- 旧形态：无命令；.env BOT_MODEL_REGISTRY＋scripts/probe_llm_providers.py；别名 供应商/provider/providers/模型供应商/包台。echo.py 1461
- 九形态：EN全=provider(既有)/providers(既有)｜EN简=—｜EN语=model provider(既有)｜简中=供应商/模型供应商/包台(既有)｜繁中=供應商(建议,未收录)｜中简=—｜拼全=gongyingshang(建议,未占用)｜拼首=gys(建议,未占用)｜组合=包台(既有口语)
- 权限：管理员
- 参数（配置面）：| BOT_MODEL_REGISTRY | JSON 对象 | .env | 每项 model/base_url/api_key/group/priority；priority 整数 1-999（越小越优先） | — | 静态渠道底表（改后重启） |
| BOT_CHAT_FAST_MAX_CANDIDATES | 整数 | .env | 0=不限制，1-100=最多尝试数 | — | 快速模式候选裁剪 |
| probe_llm_providers.py --max-tokens | CLI 参数 | — | 1-4096 | 32 | 命令行脱敏探测 |
- 语义：.env 静态注册表+运行时动态注册（/bot model add）合并统一视图。
- 示例：BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}
- 错误反馈：registry 改 .env 后重启生效；运行时条目热生效（真值源原文）

## 十三、领域：系统（system）

#### E-50 状态（/bot 系统 状态）
- 四段式：`/bot 系统 状态`。旧形态：/bot status；别名 状态/狀態/status。echo.py 470
- 九形态：EN全=status(既有)｜EN简=—｜EN语=bot status(建议)｜简中=状态(既有)｜繁中=狀態(既有)｜中简=—｜拼全=zhuangtai(建议,未占用)｜拼首=zt(慎,与 zhibo 弱冲突,观察)｜组合=—
- 权限：管理员。参数：无。
- 语义：运行状态摘要（软暂停/角色计数/人格知识文件/各存储 sqlite or memory/限速安静时间/LLM 就绪），脱敏输出。
- 示例：/bot status。错误反馈：无记录类失败（纯只读）

#### E-51 为什么（/bot 系统 为什么 [id]）
- 四段式：`/bot 系统 为什么 [id]`。旧形态：/bot why [id]；别名 为什么/为啥/why。echo.py 522
- 九形态：EN全=why(既有)｜EN简=—｜EN语=why this reply(建议)｜简中=为什么/为啥(既有)｜繁中=為什麼(建议,未收录)｜中简=—｜拼全=weishenme(建议,未占用)｜拼首=wsm(慎:`wsm`=为什么网络惯用缩写,恰好语义一致,建议可启但观察)｜组合=—
- 权限：管理员。参数：| id | request_id/debug_id | 否 | 来自回执/审计输出 | 最近一次 | 解释指定请求决策 |
- 语义：决策解释器（走了哪条路由/命中什么策略/在哪一步失败）。示例：/bot why｜/bot why help_8f2a1b3c
- 错误反馈：没有可解释记录→提示先和机器人说一句话（真值源原文）

#### E-52 回执（/bot 系统 回执 <id>）
- 四段式：`/bot 系统 回执 <id>`。旧形态：/bot receipt <id>；别名 回执/receipt。echo.py 543
- 九形态：EN全=receipt(既有)｜EN简=—｜EN语=delivery receipt(建议)｜简中=回执(既有)｜繁中=回執(建议)｜中简=—｜拼全=huizhi(建议,未占用)｜拼首=hz(慎,弱冲突,观察)｜组合=—
- 权限：管理员。参数：| id | request_id/debug_id | 是 | /bot recent 输出可取 | — | 区分「没生成」vs「生成了没发出去」 |
- 语义：发送回执查询（BOT_RECEIPTS_ENABLED=true 落库跨重启，默认内存态）。
- 示例：/bot receipt 7c9f…。错误反馈：查不到回显脱敏 id（真值源原文）

#### E-53 审计（/bot 系统 审计 <request_id>）
- 四段式：`/bot 系统 审计 <request_id>`。旧形态：/bot audit <request_id>；别名 审计/audit。echo.py 563
- 九形态：EN全=audit(既有)｜EN简=—｜EN语=audit trail(建议)｜简中=审计(既有)｜繁中=審計(建议)｜中简=—｜拼全=shenji(建议,未占用)｜拼首=sj(慎:`sj`=时间/事故多义,观察；既有建议 shj 更稳)｜组合=—
- 权限：管理员。参数：| request_id | 请求编号 | 是 | 任意已发生请求 | — | 按时间排序事件列表（stage/event/severity，敏感字段脱敏） |
- 语义：审计事件查询（BOT_AUDIT_ENABLED=true 落库；入站/路由/出站/异常留痕）。
- 示例：/bot audit music_9a3bb2。错误反馈：未找到回显脱敏编号（真值源原文）

#### E-54 最近（/bot 系统 最近 [数量]）
- 四段式：`/bot 系统 最近 [数量]`。旧形态：/bot recent [数量]；别名 最近/recent。echo.py 583
- 九形态：EN全=recent(既有)｜EN简=—｜EN语=latest events(建议)｜简中=最近(既有)｜繁中=最近(同形)｜中简=—｜拼全=zuijin(建议,未占用)｜拼首=zj(慎:`zj`=转账/中介多义,观察)｜组合=—
- 权限：管理员。参数：| 数量 | 整数 | 否 | 1-20 | 5 | 合并摘要条数（越界自动收敛边界） |
- 语义：诊断+回执+审计合并视图；输出 id 可直接喂 /bot why、/bot receipt、/bot audit。
- 示例：/bot recent 10

#### E-55 队列（/bot 系统 队列）
- 四段式：`/bot 系统 队列`。旧形态：/bot queue；别名 队列/queue。echo.py 604
- 九形态：EN全=queue(既有)｜EN简=—｜EN语=send queue(建议)｜简中=队列(既有)｜繁中=隊列(建议)｜中简=—｜拼全=duilie(建议,未占用)｜拼首=dl(**冲突**：dl 已建议给下载 EN简，跨域撞车→本格 `—（被下载域 dl 占用）`)｜组合=—
- 权限：管理员。参数：无。
- 语义：发送队列状态（各状态计数+max_items/max_attempts/retry 参数）。
- 示例：/bot queue

#### E-56 日志（/bot 系统 日志 [级别] [数量]）
- 四段式：`/bot 系统 日志 [级别] [数量]`。旧形态：/bot logs [级别] [数量]；别名 日志/logs。echo.py 1124
- 九形态：EN全=logs(既有)｜EN简=—｜EN语=runtime logs(建议)｜简中=日志(既有)｜繁中=日誌(建议)｜中简=—｜拼全=rizhi(建议,未占用)｜拼首=rz(慎,弱冲突,观察)｜组合=—
- 权限：管理员。参数：| 级别 | 枚举 | 否 | debug/info/warning/error（其他词回退 info） | info | 过滤级别 |
| 数量 | 整数 | 否 | 1-200（越界收敛；非数字回退 50） | 50 | 条数 |
- 语义：运行时事件日志查询。示例：/bot logs error 20
- 错误反馈：未启用→提示运行时事件日志未启用（真值源原文）

#### E-57 解析（/bot 系统 解析 [数量]）
- 四段式：`/bot 系统 解析 [数量]`。旧形态：/bot parse [数量]；别名 解析/parse。echo.py 1018
- 九形态：EN全=parse(既有)｜EN简=—｜EN语=parse history(建议)｜简中=解析(既有)｜繁中=解析(同形)｜中简=—｜拼全=jiexi(建议,未占用)｜拼首=jx(慎,弱冲突,观察)｜组合=—
- 权限：管理员（M24 收紧：链接自带 token 等于二次扩散）
- 参数：| 数量 | 整数 | 否 | 1-100 | 10 | 全局解析历史条数 |
- 语义：全局（跨群/跨私聊）解析历史。示例：/bot parse 20

#### E-58 设置·运行时（/bot 系统 设置 set|get|list|reset|nickname|persona|instance）
- 四段式：`/bot 系统 设置 <函数> [参数…]`（--instance <名称> 可加于各子命令）
- 旧形态：/bot runtime set|get|list|reset|nickname add/remove/list|persona list/switch/probability；别名 设置/runtime/参数/設置/參數/运行时。echo.py 957
- 九形态：EN全=runtime(既有)｜EN简=—｜EN语=runtime config(建议)｜简中=设置/参数/运行时(既有)｜繁中=設置/參數(既有)｜中简=—｜拼全=shezhi(既有别名 设置)/yunxing(建议,未占用)｜拼首=yx(慎:`yx`=游戏/优先多义,观察)｜组合=—
- 权限：管理员（runtime set/reset、模型写操作、核心人格 switch/probability 仅超管）
- 参数（逐函数）：| set | KEY VALUE | 双必填 | KEY∈SETTABLE_KEYS 白名单（发错键列出可用键）；VALUE 按键类型校验非法拒绝 | — | 热改主入口（写入即持久化+热更通知；个别装配期键需重启并单独标注） |
| get | KEY | 必填 | 白名单键 | — | 查实际生效值+来源（覆盖 or .env 默认） |
| list | 无 | — | — | — | 覆盖清单 |
| reset | KEY | 否 | 省略=清空全部覆盖 | 全部 | 回滚热改 |
| persona | list\|switch <id\|default>\|probability <id> <0-1> | 子函数各异 | switch 取值 id 或 default；probability 0..1 | — | 运行期人格管理 |
| nickname | add\|remove\|list [昵称] | add/remove 需昵称 | 昵称非空 | — | 昵称触发词维护 |
- 常用可写键举例：BOT_MODEL_SCHEDULE（JSON，{"23:00-07:00":"luna"} 支持跨零点）、BOT_MODEL_PRIORITY_GROUPS（JSON 数组，days 1..7/windows HH:MM 对/order 模型id 列表，缺省=兜底组）、BOT_MODEL_PRICES、BOT_CHAT_REASONING_EFFORT（off|low|medium|high|xhigh|max|留空）、BOT_REPLY_DETAIL、BOT_CHAT_MAX_TOKENS、BOT_CHAT_FAST_MODE、BOT_VISION_ENABLED、BOT_QUIET_HOURS_*（6 键）、BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR。
- 语义：运行时参数热改层（覆盖优先于 .env）。示例：/bot runtime set BOT_QUIET_HOURS_ENABLED true｜/bot runtime get BOT_REPLY_DETAIL
- 错误反馈：白名单外键→列出可用键；类型非法→拒绝（真值源原文）

#### E-59 上下文（/bot 系统 上下文 [文本]）
- 四段式：`/bot 系统 上下文 [文本]`。旧形态：/bot context [文本]；别名 上下文/context。echo.py 624
- 九形态：EN全=context(既有)｜EN简=—｜EN语=prompt context(建议)｜简中=上下文(既有)｜繁中=上下文(同形)｜中简=—｜拼全=shangxiawen(建议,未占用)｜拼首=sxw(建议,未占用)｜组合=—
- 权限：管理员。参数：| 文本 | 文本 | 否 | 任意内容（先过注入检查） | 默认文本 | 全程只读装配：注入检查→预算→人格+向量+记忆+对话→prompt |
- 语义：看「如果现在说这句话，模型会看到什么」（数字摘要，不回显知识库原文）。
- 示例：/bot context 鸣潮的守岸人是谁。错误反馈：失败只报错误类型不泄露堆栈（真值源原文）

#### E-60 对话（/bot 系统 对话 [文本]）
- 四段式：`/bot 系统 对话 [文本]`。旧形态：/bot dialogue [文本]；别名 对话/dialogue/对话测试。echo.py 646
- 九形态：EN全=dialogue(既有)｜EN简=—｜EN语=diag chat(建议)｜简中=对话/对话测试(既有)｜繁中=對話(建议)｜中简=—｜拼全=duihua(建议,未占用)｜拼首=dh(慎:`dh`=电话/刻画多义,观察)｜组合=对话测试(既有)
- 权限：管理员。参数：| 文本 | 文本 | 否 | 任意 | 默认文本 | 真的走完一轮 LLM 调用（可能产生费用），不写入线上会话历史 |
- 语义：整链路验收（区别 context=只装配不调用）。示例：/bot dialogue 今天状态怎么样

#### E-61 配置（/bot 系统 配置）
- 四段式：`/bot 系统 配置`。旧形态：/bot config；别名 配置/config。echo.py 690
- 九形态：EN全=config(既有)｜EN简=—｜EN语=config check(建议)｜简中=配置(既有)｜繁中=配置(同形)｜中简=—｜拼全=peizhi(建议,未占用)｜拼首=pz(慎:`pz`=拼字多义,观察)｜组合=—
- 权限：管理员。参数：无。
- 语义：config smoke 全量体检（LLM 接入/路径/模板；区别 setup llm=只聚焦七键）。
- 示例：/bot config

#### E-62 就绪（/bot 系统 就绪）
- 四段式：`/bot 系统 就绪`。旧形态：/bot readiness；别名 就绪/readiness。echo.py 710
- 九形态：EN全=readiness(既有)｜EN简=—｜EN语=ready check(建议)｜简中=就绪(既有)｜繁中=就緒(建议)｜中简=—｜拼全=jiuxu(建议,未占用)｜拼首=jx2(撞 E-57 建议 jx→本格 `—（被解析域 jx 占用）`)｜组合=—
- 权限：管理员。参数：无。
- 语义：readiness smoke 聚合报告（环境/配置/上下文/对话链路 ok/blocked+软暂停状态）。
- 示例：/bot readiness

#### E-63 角色（/bot 系统 角色）
- 四段式：`/bot 系统 角色`。旧形态：/bot roles；别名 角色/roles。echo.py 730
- 九形态：EN全=roles(既有)｜EN简=—｜EN语=role counts(建议)｜简中=角色(既有)｜繁中=角色(同形)｜中简=—｜拼全=juese(建议,未占用)｜拼首=js(慎:`js`=JavaScript/技术多义,观察)｜组合=—
- 权限：管理员。参数：无。
- 语义：角色计数摘要（user/trusted/enterprise/admin+blocked；管理员由 BOT_ADMIN_USER_IDS/BOT_TELEGRAM_ADMIN_USER_IDS 确定；只给数量不泄露名单）。
- 示例：/bot roles

#### E-64 历史（/bot 系统 历史 clear）
- 四段式：`/bot 系统 历史 clear`。旧形态：/bot history clear；别名 历史/history/清理历史。echo.py 796
- 九形态：EN全=history(既有)｜EN简=—｜EN语=clear history(既有 清理历史)｜简中=历史/清理历史(既有)｜繁中=歷史(建议)｜中简=—｜拼全=lishi(建议,未占用；liushi=六十四卦属占卜不同词)｜拼首=ls(慎:`ls`=列目录/累死多义,观察)｜组合=清理历史(既有)
- 权限：管理员。参数：| clear | 子命令 | 是（写成别的回用法） | 仅 clear | — | 清理范围=平台×适配器×机器人×会话×发送者 |
- 语义：清理本会话最近对话（prompt 短期上下文软重置；别人的对话与长期记忆不受影响）。
- 示例：/bot history clear。错误反馈：失败只报类型不泄露库路径（真值源原文）

#### E-65 暂停/恢复（/bot 系统 暂停｜恢复）
- 四段式：`/bot 系统 暂停`｜`/bot 系统 恢复`。旧形态：/bot pause｜/bot resume；别名 暂停/暫停/pause/resume/恢复/继续/繼續。echo.py 816
- 九形态：EN全=pause(既有)/resume(既有)｜EN简=—｜EN语=resume bot(既有 resume)｜简中=暂停/恢复/继续(既有)｜繁中=暫停/繼續(既有)｜中简=—｜拼全=zanting(建议,未占用)/huifu(慎,huifu 与回复 huifu 同音撞拼全——**拼全槽按声调不可区分，建议不启，用 pause/resume 区分**)｜拼首=zt(被状态域建议占用→`—`)｜组合=继续(既有)
- 权限：管理员。参数：无。
- 语义：软暂停=运行时状态不写 .env 不重启；暂停期间消息仍接收留审计，只是不生成人格回复。
- 示例：/bot pause → 维护 → /bot resume。错误反馈：状态记入 /bot status 软暂停行（真值源原文）

#### E-66 回复（/bot 系统 回复 [模式]）
- 四段式：`/bot 系统 回复 [详细|科普|详尽|精简|简洁|默认|自动]`
- 旧形态：/bot reply [模式]；别名 回复/reply/详略。echo.py 838
- 九形态：EN全=reply(既有)｜EN简=—｜EN语=detail level(建议)｜简中=回复/详略(既有)｜繁中=回復(建议)｜中简=—｜拼全=huifu(**同音撞车见 E-65 注**，建议不启)｜拼首=hf(慎,弱冲突,观察)｜组合=—
- 权限：管理员。参数：| 模式 | 枚举 | 否 | 详细/科普/详尽→detail；精简/简洁→concise；默认/自动→auto；其他输入→用法提示（不静默当默认） | 省略=查当前 | 输出风格；写入运行时覆盖持久化立即生效 |
- 语义：回复详略档位（详细=先结论再展开不凑字数；精简=短句直给；默认=按复杂度自动）。
- 示例：/bot reply 详细｜/bot reply 精简。相关键：BOT_CHAT_MAX_TOKENS（上限非强制长度）、BOT_CHAT_FAST_MODE。

#### E-67 凭据（/bot 系统 凭据 check|status|import|login|check|expiry）
- 四段式：`/bot 系统 凭据 check [--probe]`｜`status`｜`import <平台> <Cookie头>`｜`login <平台>`｜`check <平台>`｜`expiry`
- 旧形态：/bot alert check [--probe]；/bot cookie status|import|login|check|expiry；别名 凭据/凭证/憑據/憑證/登录凭证/登錄憑證/alert/cookie。echo.py 1038
- 九形态：EN全=cookie(既有)/alert(既有)｜EN简=—｜EN语=cookie health(建议)｜简中=凭据/凭证/登录凭证(既有)｜繁中=憑據/憑證/登錄憑證(既有)｜中简=—｜拼全=pingju(建议,未占用)｜拼首=pj(慎:`pj`=评审/破产多义,观察)｜组合=登录凭证(既有)
- 权限：管理员（命令匹配层就拦）。每天 10:00 定时巡检可关（bot_cookie_expiry_reminder_enabled）
- 参数：| --probe | 开关 | 否 | — | — | 主动探测各引用 |
| 平台 | 枚举 | import/login/check 必填 | 18 平台小写（import）；login/check 当前仅 bilibili 扫码 | — | 定位平台凭证 |
| Cookie头 | 文本 | import 必填 | 整行原文粘贴；同名不覆盖、热生效 | — | 导入登录态 |
- 语义：凭据健康与 cookie 导入（统一 cookies.txt，值永不回显；过期私聊推送第一位在线管理员）。
- 示例：/bot cookie import bilibili SESSDATA=...; bili_jct=...｜/bot alert check --probe

#### E-68 群文件（/bot 系统 群文件）
- 四段式：`/bot 系统 群文件`。旧形态：/bot 群文件；别名 群文件/群文件统计。echo.py 1103
- 九形态：EN全=group files(建议)｜EN简=—｜EN语=—｜简中=群文件/群文件统计(既有)｜繁中=群文件(同形)｜中简=—｜拼全=qunwenjian(建议,未占用)｜拼首=qwj(建议,未占用)｜组合=—
- 权限：管理员，仅群聊（私聊提示不可用）。参数：无。
- 语义：群上传统计（OneBot group_upload 事件入 SQLite；「整理」=记录+统计+提醒，OneBot 无移动文件夹 API 不假装能移）。
- 示例：/bot 群文件

#### E-69 文件（文件 <格式> <主题>）
- 四段式：`/bot 系统 文件 <格式> <主题>`
- 旧形态：`文件 <格式> <主题>`（无 /bot 前缀，matcher:admin_file_export）；别名 文件/文件导出/导出。echo.py 1148
- 九形态：EN全=export(既有 导出)｜EN简=—｜EN语=export file(建议)｜简中=文件/文件导出/导出(既有)｜繁中=檔案/導出(建议,未收录)｜中简=—｜拼全=wenjian(建议,未占用)/daochu(建议,未占用)｜拼首=wj(慎,与维基 wj 建议撞→观察；daochu 首选 dc 弱冲突观察)｜组合=—
- 权限：管理员（命令匹配层拦截）
- 参数：| 格式 | 枚举 | 是 | md/markdown/docx/pptx/xlsx/pdf（markdown 归一为 md） | — | 目标文档格式 |
| 主题 | 文本 | 是 | 任意主题（截 40 字作标题） | — | LLM 生成 600-1200 字结构化 Markdown |
- 语义：生成文档→本地转换→群文件上传（数十秒级后台线程；产出落 data/downloads/export/）。
- 示例：文件 docx 鸣潮 2.0 版本角色梯度整理。错误反馈：LLM/转换/上传失败均回文本报错（真值源原文）

#### E-70 限流（/bot 系统 限流——配置型说明页）
- 四段式：`/bot 系统 限流`（说明页；实际经 /bot runtime set）。旧别名：限流/句数帽/安静时间/情绪豁免/自动接话。echo.py 1243
- 九形态：EN全=rate limit(建议)｜EN简=—｜EN语=quiet hours(建议)｜简中=限流/句数帽/安静时间/情绪豁免/自动接话(既有)｜繁中=限流(同形)｜中简=—｜拼全=xianliu(建议,未占用)｜拼首=xl(慎:`xl`=哈利/心理多义,观察)｜组合=—
- 权限：管理员。参数（11 键配置面，全经 runtime set）：BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR/MAX_PER_MINUTE（≥0 整数，0=帽不生效；用户口径建议 60/小时、3/分钟）、BOT_RATE_LIMIT_EMOTION_EXEMPT（true/false 默认 true，安抚类绕帽）、BOT_GROUP_CHAT_AUTO_REPLY_ENABLED（默认 false）+PROBABILITY（0..1 默认 0.004，与心情系数相乘封顶 1.0）、安静时间 6 键（ENABLED bool；START/END HH:MM 支持跨零点默认 00:00-06:00；TIMEZONE IANA 名；SESSION_TYPES group|private|email 逗号分隔默认 group；BYPASS_ROLES 默认 admin）。
- 语义：群回复频率与时机控制。点名/显式命令永远不受安静时间与概率影响；自动接话确定性哈希抽签同消息稳定（真值源原文）。
- 示例：/bot runtime set BOT_QUIET_HOURS_START 01:00

#### E-71 合并转发（/bot 系统 合并转发——配置型说明页）
- 四段式：`/bot 系统 合并转发`（说明页）。旧别名：合并转发/转发合并。echo.py 1276
- 九形态：EN全=merge forward(建议)｜EN简=—｜EN语=forward merge(建议)｜简中=合并转发/转发合并(既有)｜繁中=合併轉發(建议)｜中简=—｜拼全=hebingzhuanfa(建议,未占用)｜拼首=hbzf(不建议,过生僻→—)｜组合=—
- 权限：管理员。参数（4 键）：BOT_RENDER_FORWARD_MIN_NODES（≥0 默认 4，0=不按条数）、_MIN_CHARS（≥0 默认 1500）、_MAX_NODES（≥0 默认 0=不限）、_NODE_CHARS（≥200 默认 900）。条数达 MIN_NODES 或字数达 MIN_CHARS 即合并；消费在装配期，改动需重启。
- 示例：/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3

#### E-72 视频理解（/bot 系统 视频理解——配置型说明页）
- 四段式：`/bot 系统 视频理解`（说明页）。旧别名：视频理解/识图/vision/视频。echo.py 1338
- 九形态：EN全=video understanding(建议)｜EN简=—｜EN语=—｜简中=视频理解/识图/视频(既有)｜繁中=視頻理解(建议)｜中简=—｜拼全=shipinlijie(建议,未占用)｜拼首=splj(不建议,过生僻→—)｜组合=—
- 权限：管理员。参数（9 键）：BOT_VISION_ENABLED（默认 false）、BOT_VISION_MODE（relay|direct 默认 direct）、BOT_VISION_REPLY_PROBABILITY（0..1 默认 1.0）、BOT_VIDEO_UNDERSTANDING_ENABLED（默认 false）、BOT_VIDEO_MAX_FRAMES（正整数默认 6，0 视同 1）、BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE（默认 true）、BOT_VIDEO_FUZZY_FOLLOWUP（默认 true）、BOT_VIDEO_DEEP_ENABLED（默认 true）、BOT_VIDEO_PROGRESS_ACK_ENABLED（同会话 60 秒节流）。全部可 runtime set 热改。
- 示例：/bot runtime set BOT_VISION_MODE relay

#### E-73 运行开关（.env 五键，无命令）
- 四段式：无（配置型，.env 改后重启）。旧别名：运行开关/诊断开关/持久化开关。echo.py 1370
- 九形态：EN全=persistence switches(建议)｜EN简=—｜EN语=—｜简中=运行开关/诊断开关/持久化开关(既有)｜繁中=運行開關(建议)｜中简=—｜拼全=yunxingkaiguan(建议,未占用)｜拼首=yxkg(不建议→—)｜组合=—
- 权限：管理员。参数（5 键 bool，全默认 false）：BOT_SEND_QUEUE_ENABLED（队列落 sqlite）、BOT_SEND_QUEUE_WORKER_ENABLED（后台投递线程）、BOT_AUDIT_ENABLED（审计跨重启）、BOT_RECEIPTS_ENABLED（回执跨重启）、BOT_DIAGNOSTICS_ENABLED（诊断汇总）。路径由对应 BOT_*_DB_PATH 配置（留空=内存态）。
- 示例：.env 里 BOT_AUDIT_ENABLED=true 后重启

#### E-74 决策（/bot 系统 决策 [N]）
- 四段式：`/bot 系统 决策 [N]`。旧形态：/bot decision [N]；别名 决策/决策引擎/decision。echo.py 2423
- 九形态：EN全=decision(既有)｜EN简=—｜EN语=shadow decision(建议)｜简中=决策/决策引擎(既有)｜繁中=決策(建议)｜中简=—｜拼全=juece(建议,未占用)｜拼首=jc(慎:`jc`=检测/ judiciary 多义,观察)｜组合=—
- 权限：管理员。参数：| N | 整数 | 否 | 1-100 | 20 | 影子痕迹条数 |
- 语义：影子决策引擎（BOT_DECISION_ENGINE_MODE=shadow，只算不发）路由分歧痕迹查询（时间/路由类别/引擎判定/现行判定/一致·分歧·不可比/耗时，脱敏截断；SQLite 落盘重启可查）。
- 示例：/bot decision｜/bot decision 50。错误反馈：legacy_only 默认下查到「暂无记录」属预期不是故障（真值源原文）

#### E-75 路由（/bot 系统 路由 <文本>｜routes）
- 四段式：`/bot 系统 路由 <文本>`｜`/bot 系统 路由 表`
- 旧形态：/bot route <文本>｜/bot routes；别名 路由/route/routes。echo.py 770
- 九形态：EN全=route(既有)/routes(既有)｜EN简=—｜EN语=route table(建议)｜简中=路由(既有)｜繁中=路由(同形)｜中简=—｜拼全=luyou(建议,未占用)｜拼首=ly(慎:`ly`=旅游/留言多义,观察)｜组合=—
- 权限：**全员**（只读，不真的执行命中命令）
- 参数：| 文本 | 文本 | route 必填 | 任意文本 | — | 单句判定：kind/capability_id/优先级/理由（含归一化结果） |
- 语义：基层路由判定/路由表审计视图（33 规则按 priority 排序）。已登记漂移：帮助文本写「二次元问句(44)」，代码实值 46（主规格 §7）。
- 示例：/bot route 点歌 晴天 → MUSIC｜/bot route 天气真好 → CHAT

#### E-76 忽略（/bot 系统 忽略——排障语义说明页）
- 四段式：无专属命令（说明页）。旧别名：忽略/ignore。echo.py 2396
- 九形态：EN全=ignore(既有)｜EN简=—｜EN语=silence reason(建议)｜简中=忽略(既有)｜繁中=忽略(同形)｜中简=—｜拼全=hulue(建议,未占用)｜拼首=hl(**冲突**：hl 已建议给汇率拼首→本格 `—（被汇率域占用）`)｜组合=—
- 权限：管理员（排障语义）。参数：无。
- 语义：静默路由语义解释——机器人不回≠故障；唯一例外=命令形态（/ 开头）未命中任何能力时回一句 /bot help 引导（60 秒/会话节流）。
- 示例：/bot route 今天天气不错 → 显示 chat 路由（正常回复场景）

#### E-77 邮件（/mail status|accounts|use|send|pause|resume）
- 四段式：`/bot 系统 邮件 <函数>…`（正形提案；现行前缀 `/mail` 独立保留）
- 旧形态：/mail status|accounts|use|send|pause|resume；别名 邮件/电子邮件/mail/email/邮箱。echo.py 1401
- 九形态：EN全=mail(既有)/email(既有)｜EN简=—｜EN语=mail box(建议)｜简中=邮件/电子邮件/邮箱(既有)｜繁中=郵件/電子郵件(建议)｜中简=—｜拼全=youjian(建议,未占用)｜拼首=yj(被商品域建议占用→`—`)｜组合=—
- 权限：管理员（**仅 Telegram 管理端**：BOT_TELEGRAM_ADMIN_USER_IDS/CHAT_IDS；QQ 侧不受理）
- 参数：| use | 发件邮箱 | 必填 | 须已连接或已映射 | — | 设默认发件身份 |
| send | 三段/四段 | 必填 | `<收件邮箱> | <主题> | <正文>`（主题/正文非空）；--from 版四段缺一不可 | — | 发信 |
| pause/resume | 无 | — | — | — | 暂停/恢复自动回复（收件提醒继续） |
- 语义：Gmail/QQ IMAP/SMTP 桥（新邮件提醒/AI 自动回复/人工发信）。
- 示例：/mail send someone@example.com | 测试 | 这是一封测试邮件
- 错误反馈：非管理端执行→「仅允许从 Telegram 管理端执行」；SMTP/适配器错误只报类型（真值源原文）

#### E-78 Telegram（.env 配置型，无命令）
- 四段式：无（说明页）。旧别名：telegram/tg/电报/纸飞机/飞机。echo.py 1435
- 九形态：EN全=telegram(既有)｜EN简=tg(既有)｜EN语=—｜简中=电报/纸飞机/飞机(既有)｜繁中=電報(建议)｜中简=—｜拼全=—（专名不设拼音形）｜拼首=—（tg 既有即英文简）｜组合=—
- 权限：管理员配置。参数（3 键 .env，改后重启）：TELEGRAM_BOTS（JSON 数组，BotFather Token 列表，≥1 才连接）、BOT_TELEGRAM_ADMIN_USER_IDS（JSON 字符串数组）、BOT_TELEGRAM_ADMIN_CHAT_IDS（同）。/bot status、/bot pause|resume 可在 TG 侧远程执行。
- 示例：TELEGRAM_BOTS=["123456:ABC-DEF..."]

#### E-79 功能管理（/bot 系统 功能管理 list|get|enable|disable|reset|preview）
- 四段式：`/bot 系统 功能管理 <函数> <ID> [目标状态]`
- 旧形态：/bot feature list/get/enable/disable/reset/preview；别名 功能管理/feature。echo.py 448
- 九形态：EN全=feature(既有)｜EN简=—｜EN语=feature gate(建议)｜简中=功能管理(既有)｜繁中=功能管理(同形)｜中简=—｜拼全=gongnengguanli(既有别名)｜拼首=gngl(不建议,过生僻→—)｜组合=/bot 功能管理 归一入口(既有)
- 权限：管理员只读；**enable/disable/reset/preview 仅超管**（CAS 写入+审计；受保护核心能力不可关闭）
- 参数：| ID | 稳定功能ID | 函数必填 | 如 bot.plugin.weather、bot.ingress.file_read（完整目录 /bot feature list） | — | 能力树节点 |
| 目标状态 | 枚举 | preview 必填 | on/off/reset | — | 预览影响节点不写入 |
- 语义：能力树状态与版本管理（父级关闭不能被子级 enable 突破；修改影响后续事件不强杀运行中处理；与控制面共用 ConfigControlService）。
- 示例：/bot feature get bot.plugin.weather｜/bot feature disable bot.ingress.file_read
- 错误反馈：未接入资源重载的键明确拒绝热改，不假称更新成功（真值源原文）

## 十四、领域：帮助（help）

#### E-80 帮助（/bot 帮助 [模块]）
- 四段式：`/bot 帮助`｜`/bot 帮助 <模块名|别名>`｜`/bot 帮助 目录`（=旧 /bot commands）
- 旧形态：/bot help｜/bot help <模块>｜/bot commands；别名 帮助/help/菜单。echo.py 2280
- 九形态：EN全=help(既有)｜EN简=—｜EN语=show help(建议)｜简中=帮助/菜单(既有)｜繁中=幫助(建议)/菜單(建议)｜中简=—｜拼全=bangzhu(建议,未占用)｜拼首=**bz=永不启用（台账 #27）**——设计内永久缺位｜组合=菜单(既有)
- 权限：全员（可见范围按角色：非管理员查管理员模块回「没有找到」）
- 参数：| 模块 | 主题名/别名 | 否 | 77 主题任一（含别名，如 /bot help music） | 省略=分类总览 | 深度页（逐参数说明） |
- 语义：帮助系统自指——总览管「有什么」、深度页管「怎么用」、/bot commands 管机器对账；与 command-catalog.md 同源。
- 示例：/bot help｜/bot help 点歌｜/bot help help

#### E-81 昵称（/bot 帮助 昵称 + /bot 昵称 set）
- 四段式：`/bot 帮助 昵称`（说明页）｜`/bot 昵称 set <QQ号> <小名>`（管理员）
- 旧形态：<昵称><命令> [参数]（/岸宝帮助、守岸人 天气 上海、/岸宝点歌 晴天）；别名 昵称/alias。路由 ALIAS @10 → bot.alias；echo.py 1959
- 九形态：EN全=alias(既有)｜EN简=—｜EN语=nickname trigger(建议)｜简中=昵称(既有)｜繁中=暱稱(建议)｜中简=—｜拼全=nicheng(建议,未占用)｜拼首=nc(**不建议**：`nc`=脏话缩写，按 §5.2 精神禁用倾向)｜组合=守岸人/岸宝 前缀(既有昵称表)
- 权限：触发本身全员（各命令自身权限照旧）；/bot 昵称 set=管理员
- 参数：| QQ号 | 数字 | set 必填 | 5-11 位数字 | — | 记小名对象 |
| 小名 | 文本 | set 必填 | 1-32 字 | — | 好感度与称呼个性化 |
- 语义：昵称命令层（存 BOT_PERSONA_NICKNAMES/runtime nickname，未配置时别名层关闭；标准 /bot 前缀不受影响）。
- 示例：/岸宝帮助｜守岸人 天气 上海｜/bot 昵称 set 123456789 小澜

---

## Part 3 收尾核对

- 本部分条目：E-45~E-81（37 条），覆盖 模型 5 主题 + 系统 30 主题 + 帮助 2 主题。
- 全三部合计 **81 条目覆盖 77 主题**（点歌拆 点歌/点歌模式 2 条目、天气拆 查询/区县 2 条目、菜谱拆 推荐/做法 2 条目、暂停与恢复合 1 条目）。
- 跨域形态冲突登记（§5.2 规则执行记录）：dl（下载 EN简 vs 队列拼首——队列让位）；hl（汇率拼首 vs 忽略拼首——忽略让位）；jx（解析拼首 vs 就绪拼首——就绪让位）；huifu（恢复/回复同音——双双建议不启，用 pause/resume 与 reply 区分）；bz（帮助拼首=永不启用）；sm（算命缩写=永不启用）；zt（状态/暂停拼首撞——暂停让位）；wj（文件拼首 vs 维基拼首建议——待评审裁决）。
