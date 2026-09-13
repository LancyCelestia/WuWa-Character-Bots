# 守岸人命令与教程目录

> 本文件由 `scripts/command_catalog.py` 从 `capabilities/echo.py` 的帮助注册表与
> `runtime/base_router.py` 的路由/接口清单自动生成。不要手工修改；
> 修改帮助页数据后运行 `python scripts/command_catalog.py --write`。
> `/bot help`、`/bot help <模块>` 与本目录共享同一数据源。

- 模块数：67
- 别名数：412
- 普通用户可用模块：30；仅管理员模块：37
- 路由规则数：26；其中登记为内部能力：2

## 使用入口

- `/bot help`：查看当前用户有权限看到的模块总览。
- `/bot help <模块>`：查看一个模块的参数、效果、权限和示例。
- `/bot commands`：输出机器可读命令目录。
- `守岸人 <命令>`、`岸宝 <命令>`：在昵称触发已配置时等价于对应自然语言入口。

## 新用户教程

### 这个机器人能做什么

- 全部 67 个模块都列在本文件「模块详情」里；普通用户可直接使用其中 30 个公开模块，其余 37 个为管理员诊断与配置模块。
- 能力横跨人格闲聊、链接解析、点歌、天气、行情、占卜、提醒、订阅推送、表情包、下载与一整套管理员运维命令；全部 67 个模块逐个列在下方「模块详情」，公开模块名单以 /bot help 为准。

### 怎么开始聊天

- 群聊：@机器人，或直接用昵称点名（如「守岸人」「岸宝」）后说话；自然语言不用记命令，例如「天气 上海」「点歌 晴天」「12点提醒我写作业」。
- 私聊：在白名单内可直接发消息；机器人主动搭话受好感度门控（好感达到亲近档才会主动开口）。
- 想被称呼特定名字：请管理员用 `/bot identity set <昵称>` 设定本会话称呼（只影响称呼与语气，人格不变）。

### 怎么查看所有功能 / 单个模块

- `/bot help`：按权限返回模块总览（管理员会多看到诊断与配置模块）。
- `/bot help <模块>`：看单个模块的参数、取值范围、权限与示例，如 `/bot help 点歌`（别名同样可用，如 `/bot help music`）。
- `/bot commands`：机器可读目录（路由表 + 命令清单），脚本与文档也以它对账。
- 本文件：离线可读的全部模块教程，与帮助页同源生成。

### 怎么修改运行时参数

- `/bot runtime get <KEY>`：看参数实际生效值（标注来自运行时覆盖还是 .env 默认）。
- `/bot runtime set <KEY> <VALUE>`：热改参数，立即生效、持久保存、重启保留；只接受 SETTABLE_KEYS 白名单内的键，发错键会列出可用键。
- `/bot runtime reset [KEY]`：撤销热改（省略 KEY = 清空全部覆盖）。
- 注意：白名单外的键（如部分持久化开关）只能改 .env 后重启生效；个别装配期读取的键热改后也要重启。

### 哪些命令只有管理员能用

- 仅管理员模块共 37 个，全部走 `/bot` 前缀（例如 `/bot status`、`/bot runtime`、`/bot model`），普通成员发送会收到拒绝提示；权限由六级角色体系（user/trusted/enterprise/admin/super_admin/blocked）判定。
- 排障第一入口是 `/bot status`，追问原因用 `/bot why`。

### 群聊和私聊有什么差别

- 群聊有门禁（黑白名单、安静时间、限流句数帽、好感门）；私聊在白名单内直接对话。
- 标注「群聊/私聊差异」的模块在详情里有具体行为（例如记忆：私聊=全部个人记忆，群聊=仅公开/群组两级）。
- 大模型调用失败时：私聊会收到守岸人话术的失败提示，群聊保持静默不刷屏。

### 哪些功能会发图片？失败怎么办？

- 帮助页、行情、点歌候选等场景会渲染「釉瑚云母」卡片图；渲染失败会自动回退纯文本，功能不中断。
- 当前列为图片输出的模块：接入、用量、点歌、行情、个股行情、汇率、Epic、帮助。
- 下载/文件类模块输出文件段；所有命令失败时都会给出可读原因，不抛堆栈。

### 哪些功能依赖网络？

- 需要联网的模块：上下文、对话、模型、搜索、凭据、文件、群摘要、视频理解、邮件、Telegram、订阅、点歌、搜图、天气、行情、个股行情、汇率、快报、维基、萌娘百科、历史上的今天、下载、链接、Epic、聊天、表情收库。
- 纯本地模块：记忆、接入、配置、就绪、角色、人格、路由、历史、暂停、回复、用量、解析、群文件、日志、身份、怪癖、合并转发、运行开关、供应商、表情、占卜、随机图、帮助、戳一戳。
- 联网模块自带重试与兜底（各模块的「失败兜底」行写明具体行为）；外部源不可用时给可读失败原因。

### 高频入口速查

- `/bot help` / `/bot help <模块>`：帮助总览 / 单模块教程。
- `/bot commands`：机器可读命令目录。
- `/bot runtime get|set|reset`：参数查询 / 热改 / 回滚。
- `/bot identity set <昵称>`：设定本会话称呼（管理员）。
- 昵称触发：`守岸人 天气 上海`、`/岸宝点歌 晴天`（昵称清单可用 `/bot runtime nickname list` 查看）。

## 模块详情

## 状态

- 权限：仅管理员
- 触发别名：状态；狀態；status
- 能力入口：bot.status
- 可复制示例：/bot status
- 关联回归测试：tests/test_bot_commands_catalog_b10.py
- 总览：【状态】查看运行状态摘要：/bot status
- 标题：【状态】查看运行状态摘要

### 教程

【板块介绍】
  一条命令看清机器人此刻的整体姿态：运行时开关、软暂停、权限角色数量、
  人格/知识/记忆等文件的在位情况、各持久化存储落在 sqlite 还是内存、
  LLM 供应商与密钥是否就绪。所有信息脱敏输出，不显示密钥与会话原文。
【指令与参数】
/bot status：作用=查看运行状态摘要；参数=无；内容=多行状态清单（详见下方效果）；意义=排障第一入口，先看状态再 /bot why 追原因。
【权限与效果】
  权限=仅管理员（普通成员发送会收到拒绝提示）。
  内容逐段对应：运行时硬开关/软暂停与原因→权限角色计数（admin/enterprise/trusted/blocked）→
  人格档案与人格文件缺失数→知识文件缺失数→记忆/最近对话/诊断/审计/回执/发送队列的
  enabled 与 db 状态→情绪感知→回复限速（窗口/各层上限/绕过角色）→安静时间→LLM 配置与就绪原因。
【示例】/bot status

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 状态` 为准。

## 记忆

- 权限：普通用户可用
- 触发别名：记忆；memory
- 能力入口：bot.memory
- 群聊/私聊差异：私聊=全部个人记忆；群聊=仅 public/group 两级，防止个人私事被围观
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_MEMORY_ENABLED；BOT_MEMORY_DB_PATH
- 可复制示例：/bot memory add 我对芒果过敏 --sensitivity=group
- 关联回归测试：tests/test_memory_router_reuse.py；tests/test_memory_sanitize.py
- 总览：【记忆】管理我的长期记忆：/bot memory add|list|delete
- 标题：【记忆】管理我交给机器人的长期记忆

### 教程

【板块介绍】
  长期记忆是你主动交给机器人的事实卡片（区别于自动抽取的印象）。
  每条记忆归属“写入它的那个人＋所在会话”，互相隔离。
【指令与参数】
/bot memory add <内容>：作用=新增记忆；参数=内容（必填，任意文本，建议 ≤1200 字）；--sensitivity=（可选开关，取值 personal|group|public|credentialed，默认 personal）；内容=回显正文、fact_id（形如 fact_xxxxxxxxxxxx）与 sensitivity；意义=把“我对芒果过敏”这类事实固定下来，之后对话会被参考。
/bot memory list：作用=列出记忆；参数=无；内容=fact_id（sensitivity=…）：正文 逐行清单；意义=盘点与拿 fact_id。群聊里只显示 public/group 两级，防止个人私事被围观；私聊显示全部。
/bot memory delete <fact_id>：作用=删除记忆；参数=fact_id（必填，从 add/list 输出复制）；内容=已删除 或 未找到；意义=被遗忘权，删掉不想被记住的内容。
【取值范围】
  sensitivity 四级：personal（仅自己）/ group（本群可见）/ public（可公开）/ credentialed（敏感凭据类，谨慎使用）。
【权限与效果】
  权限=全员，无需管理员；只能操作自己作为主体的记忆。
  前置条件：BOT_MEMORY_ENABLED=true 且 BOT_MEMORY_DB_PATH 已配置，否则提示先配置。
【示例】/bot memory add 我对芒果过敏 --sensitivity=group → /bot memory list → /bot memory delete fact_xxxxxxxxxxxx

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 记忆` 为准。

## 为什么

- 权限：仅管理员
- 触发别名：为什么；为啥；why
- 能力入口：bot.why
- 可复制示例：/bot why｜/bot why help_8f2a1b3c
- 总览：【为什么】解释最近决策：/bot why [id]
- 标题：【为什么】解释最近一次回复的决策与错误

### 教程

【板块介绍】
  决策解释器：把某次请求“走了哪条路由、命中什么策略、在哪一步失败”
  翻译成人话。诊断链路的第二步（第一步是 /bot status）。
【指令与参数】
/bot why：作用=解释最近一次回复；参数=无；内容=最近一次请求的决策解释；意义=最快的“刚才怎么回事”。
/bot why <id>：作用=解释指定请求；参数=id（可选填，request_id 或 debug_id，来自回执/审计输出）；内容=该请求的决策解释；意义=追溯历史某一条。
【权限与效果】
  权限=仅管理员。没有可解释的记录时会提示先和机器人说一句话。
【示例】/bot why｜/bot why help_8f2a1b3c

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 为什么` 为准。

## 回执

- 权限：仅管理员
- 触发别名：回执；receipt
- 能力入口：/bot receipt
- 输出形式：文本
- 配置变量：BOT_RECEIPTS_ENABLED
- 可复制示例：/bot receipt 7c9f…（用 /bot recent 里出现的 id）
- 总览：【回执】查询发送回执：/bot receipt <request_id|debug_id>
- 标题：【回执】查询发送回执

### 教程

【板块介绍】
  发送回执记录每条出站消息的投递过程。BOT_RECEIPTS_ENABLED=true 时
  落库可跨重启查询，默认内存态（重启即清）。
【指令与参数】
/bot receipt <id>：作用=查询发送回执；参数=id（必填，request_id 或 debug_id，可从 /bot recent 输出拿）；内容=回执状态与关键时间点；意义=区分“没生成”和“生成了但没发出去”。
【权限与效果】
  权限=仅管理员。查不到时回显脱敏后的 id。
【示例】/bot receipt 7c9f…（用 /bot recent 里出现的 id）

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 回执` 为准。

## 审计

- 权限：仅管理员
- 触发别名：审计；audit
- 能力入口：/bot audit
- 输出形式：文本
- 配置变量：BOT_AUDIT_ENABLED
- 可复制示例：/bot audit music_9a3bb2
- 总览：【审计】查询审计记录：/bot audit <request_id>
- 标题：【审计】查询审计记录

### 教程

【板块介绍】
  审计记录由 BOT_AUDIT_ENABLED=true 时落库（默认内存态）。
  每个请求的关键节点（入站/路由/出站/异常）都会留事件。
【指令与参数】
/bot audit <request_id>：作用=查询审计记录；参数=request_id（必填，请求编号）；内容=按时间排序的事件列表（stage/event/severity，敏感字段脱敏）；意义=事后追因与合规留痕的官方入口。
【权限与效果】
  权限=仅管理员。未找到时回显脱敏后的编号。
【示例】/bot audit music_9a3bb2

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 审计` 为准。

## 最近

- 权限：仅管理员
- 触发别名：最近；recent
- 能力入口：/bot recent
- 输出形式：文本
- 可复制示例：/bot recent 10
- 总览：【最近】最近诊断摘要：/bot recent [数量]
- 标题：【最近】查看最近排障摘要

### 教程

【板块介绍】
  /bot recent ＝ 诊断（diagnostics）＋发送回执（receipts）＋审计（audits）
  三个查询的合并视图，按各自动态截取最近 N 条。
【指令与参数】
/bot recent：作用=看最近排障摘要；参数=无；内容=默认各 5 条的合并摘要；意义=快速扫一眼。
/bot recent <数量>：作用=控制条数；参数=数量（可选，1-20 整数，默认 5，越界自动收敛到边界）；内容=对应条数的摘要；意义=想多看几条时用。
【权限与效果】
  权限=仅管理员。输出里的 id 可直接喂给 /bot why、/bot receipt、/bot audit。
【示例】/bot recent 10

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 最近` 为准。

## 队列

- 权限：仅管理员
- 触发别名：队列；queue
- 能力入口：/bot queue
- 输出形式：文本
- 配置变量：BOT_SEND_QUEUE_ENABLED
- 可复制示例：/bot queue
- 关联回归测试：tests/test_part_idempotent_resume.py；tests/test_queue_poison_row.py；tests/test_auditfix_sender_queue.py
- 总览：【队列】发送队列状态：/bot queue
- 标题：【队列】查看发送队列状态

### 教程

【板块介绍】
  所有出站消息统一经发送队列收口。BOT_SEND_QUEUE_ENABLED=true 时
  队列持久化到 sqlite，重启不丢。
【指令与参数】
/bot queue：作用=查看队列状态；参数=无；内容=各状态计数与 max_items/max_attempts/retry 等参数；意义=判断发送瓶颈位置。
【权限与效果】
  权限=仅管理员。
【示例】/bot queue

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 队列` 为准。

## 上下文

- 权限：仅管理员
- 触发别名：上下文；context
- 能力入口：/bot context
- 网络依赖：需要联网
- 输出形式：文本
- 可复制示例：/bot context 鸣潮的守岸人是谁
- 总览：【上下文】测试上下文：/bot context [测试文本]
- 标题：【上下文】测试注入给模型的上下文

### 教程

【板块介绍】
  把“如果现在说这句话，模型会看到什么”完整走一遍：注入检查→回复预算→
  人格+向量知识+记忆+最近对话装配→prompt 构造，全程只读。
【指令与参数】
/bot context：作用=用默认文本做上下文诊断；参数=无；内容=注入摘要与预算；意义=开箱自检。
/bot context <文本>：作用=用指定文本诊断；参数=文本（可选，任意内容，会先过注入检查）；内容=同上，按你的文本装配；意义=复现特定说法下的上下文。
【权限与效果】
  权限=仅管理员。输出为数字摘要（条数/字数/预算），不回显知识库原文。
  失败时只报错误类型，不泄露堆栈。
【示例】/bot context 鸣潮的守岸人是谁

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 上下文` 为准。

## 对话

- 权限：仅管理员
- 触发别名：对话；dialogue；对话测试
- 能力入口：bot.dialogue
- 网络依赖：需要联网
- 输出形式：文本诊断
- 可复制示例：/bot dialogue 今天状态怎么样
- 总览：【对话】对话诊断：/bot dialogue [测试文本]
- 标题：【对话】本地跑一轮对话诊断

### 教程

【板块介绍】
  与 /bot context 的区别：dialogue 会真的走完 LLM 调用（配置了真实模型时
  会产生一次真实调用费用），用于验收整条链路。
【指令与参数】
/bot dialogue：作用=默认文本跑一轮；参数=无；内容=各阶段诊断结果；意义=部署后第一轮验收。
/bot dialogue <文本>：作用=指定输入跑一轮；参数=文本（可选）；内容=该输入的完整对话诊断；意义=复现特定问题的处理链路。
【权限与效果】
  权限=仅管理员。可能产生一次 LLM 调用费用；不写入线上会话历史。
【示例】/bot dialogue 今天状态怎么样

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 对话` 为准。

## 接入

- 权限：仅管理员
- 触发别名：接入；setup；llm setup
- 能力入口：/bot setup llm
- 网络依赖：纯本地
- 输出形式：Mica 配置卡
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 配置变量：BOT_CHAT_PROVIDER
- 可复制示例：/bot setup llm
- 总览：【接入】LLM 接入清单：/bot setup llm
- 标题：【接入】LLM 接入清单

### 教程

【板块介绍】
  把接入 OpenAI 兼容模型要动的七个键逐项体检。渲染可用时输出 Mica
  配置卡；密钥永远只显示 已设置/缺失，不回显值。只读，不写 .env。
【指令与参数】
/bot setup llm：作用=输出接入清单；参数=无；内容=逐键：说明＋取值范围＋当前值＋OK/缺口，加下一步动作提示；意义=新部署接入或换供应商时照单抓药。
【取值范围】
  BOT_CHAT_PROVIDER=openai_compatible|static；MODEL=供应商模型名；KEY=真实密钥或 env:变量名；
  BASE_URL=http(s):// 开头一般以 /v1 结尾；TEMPERATURE=0.0-2.0；MAX_TOKENS=≥0（0=不设上限）；TIMEOUT=>0 秒。
【权限与效果】
  权限=仅管理员。改完 .env 重启生效；就绪后可用 /bot llm 做真实连接诊断。
【示例】/bot setup llm

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 接入` 为准。

## 配置

- 权限：仅管理员
- 触发别名：配置；config
- 能力入口：bot.config
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot config
- 总览：【配置】配置检查：/bot config
- 标题：【配置】配置就绪检查

### 教程

【板块介绍】
  运行 config smoke：检查 LLM 接入、路径、模板等配置就绪度。
  与 /bot setup llm 的区别：config 是全量体检，setup llm 只聚焦 LLM 七键。
【指令与参数】
/bot config：作用=配置体检；参数=无；内容=各项检查结果与原因（脱敏）；意义=定位配置错误的第一站。
【权限与效果】
  权限=仅管理员。
【示例】/bot config

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 配置` 为准。

## 就绪

- 权限：仅管理员
- 触发别名：就绪；readiness
- 能力入口：bot.readiness
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot readiness
- 总览：【就绪】聚合就绪状态：/bot readiness
- 标题：【就绪】聚合就绪状态

### 教程

【板块介绍】
  readiness smoke 的聊天入口：把环境依赖、配置、上下文装配、对话链路
  的就绪状态聚合成一份报告，附带运行时软暂停状态。
【指令与参数】
/bot readiness：作用=看聚合就绪；参数=无；内容=各链路 ok/blocked 与原因；意义=部署验收与健康巡检。
【权限与效果】
  权限=仅管理员。
【示例】/bot readiness

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 就绪` 为准。

## 角色

- 权限：仅管理员
- 触发别名：角色；roles
- 能力入口：bot.roles
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_ADMIN_USER_IDS；BOT_TELEGRAM_ADMIN_USER_IDS
- 可复制示例：/bot roles
- 关联回归测试：tests/test_admin_roster_and_roles.py
- 总览：【角色】权限角色摘要：/bot roles
- 标题：【角色】权限角色摘要

### 教程

【板块介绍】
  角色体系：user < trusted < enterprise < admin（另有 blocked 屏蔽）。
  管理员由 BOT_ADMIN_USER_IDS（QQ）与 BOT_TELEGRAM_ADMIN_USER_IDS（TG）确定。
【指令与参数】
/bot roles：作用=角色计数摘要；参数=无；内容=各角色数量；意义=权限问题排查（只给数量，不泄露名单）。
【权限与效果】
  权限=仅管理员。
【示例】/bot roles

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 角色` 为准。

## 人格

- 权限：仅管理员
- 触发别名：人格；persona
- 能力入口：bot.persona
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot persona
- 总览：【人格】人格自检：/bot persona
- 标题：【人格】守岸人人格材料自检

### 教程

【板块介绍】
  运行 persona smoke：检查人格档案文件、语气规则与安全边界材料。
  运行期人格切换用 /bot runtime persona（见「设置」模块）。
【指令与参数】
/bot persona：作用=人格自检；参数=无；内容=自检 ok/error 与缺项；意义=人格“变了/淡了”类问题的第一排查点。
【权限与效果】
  权限=仅管理员。
【示例】/bot persona

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 人格` 为准。

## 路由

- 权限：普通用户可用
- 触发别名：路由；route；routes
- 能力入口：/bot route
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot route 点歌 晴天
- 总览：【路由】查看消息会走哪条路：/bot route <文本>｜/bot routes
- 标题：【路由】查看文本命中的路由

### 教程

【板块介绍】
  基层路由是确定性注册表：昵称命令(10)→管理员命令(11)→订阅(12)→自动发送(13)→
  表情(20)→偷表情(22)→点歌模式(40)→点歌/历史上的今天/维基/萌百/Epic/天气/行情/吃什么/
  好感度/占卜/快报/随机图/提醒(41)→二次元问句(44)→自然语言命令(45)→链接解析(46)→聊天(50)。
  数字越小越先命中。
【指令与参数】
/bot route <文本>：作用=单句路由判定；参数=文本（必填，任意文本）；内容=命中的 kind/capability_id/优先级/理由（含归一化结果）；意义=解释路由行为、验证触发词写法。
/bot routes：作用=列出路由表；参数=无；内容=全部规则的审计视图；意义=宏观理解与排错。
【权限与效果】
  权限=全员（只读，不真的执行命中命令）。
【示例】/bot route 点歌 晴天 → 会显示 MUSIC 路由；/bot route 天气真好 → 落到 CHAT。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 路由` 为准。

## 历史

- 权限：仅管理员
- 触发别名：历史；history；清理历史
- 能力入口：bot.history
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot history clear
- 总览：【历史】清理会话历史：/bot history clear
- 标题：【历史】清理本会话最近对话历史

### 教程

【板块介绍】
  最近对话历史是拼进 prompt 的短期上下文。清理范围精确到
  平台×适配器×机器人×会话×发送者，别人的对话和长期记忆不受影响。
【指令与参数】
/bot history clear：作用=清理最近对话；参数=无（写成别的子命令回用法）；内容=cleared_turns=N；意义=上下文污染后的软重置。
【权限与效果】
  权限=仅管理员。清理失败只报类型不泄露库路径。
【示例】/bot history clear

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 历史` 为准。

## 暂停

- 权限：仅管理员
- 触发别名：暂停；暫停；pause；resume；恢复；继续；繼續
- 能力入口：bot.control
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot pause → 维护 → /bot resume
- 总览：【暂停】软暂停/恢复：/bot pause|resume
- 标题：【暂停】软暂停/恢复机器人回复

### 教程

【板块介绍】
  软暂停是运行时状态不是配置：不写 .env、不重启，暂停期间消息仍会接收
  并留审计，只是不生成人格回复。
【指令与参数】
/bot pause：作用=软暂停；参数=无；内容=已暂停＋当前状态（reason/updated_by）；意义=紧急静音。
/bot resume：作用=恢复；参数=无；内容=已恢复＋当前状态；意义=恢复服务。
【权限与效果】
  权限=仅管理员。状态记入 /bot status 的「运行时软暂停」一行。
【示例】/bot pause → 维护 → /bot resume

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 暂停` 为准。

## 回复

- 权限：仅管理员
- 触发别名：回复；reply；详略
- 能力入口：/bot reply
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_REPLY_DETAIL；BOT_CHAT_MAX_TOKENS；BOT_CHAT_FAST_MODE
- 可复制示例：/bot reply 详细
- 总览：【回复】回复详略：/bot reply <详细|精简|默认>
- 标题：【回复】调整回复详略档位

### 教程

【板块介绍】
  回复详略影响聊天链路的输出风格：详细=先结论再展开身份/关系/关键经历
  与资料缺口（不凑字数）；精简=短句直给；默认=按问题复杂度自动取舍。
【指令与参数】
/bot reply：作用=查档位；参数=无；内容=当前 BOT_REPLY_DETAIL 值；意义=查看现状。
/bot reply <模式>：作用=设档位；参数=模式（必填：详细/科普/详尽→detail；精简/简洁→concise；默认/自动→auto）；内容=回复详略已设为 X；意义=全员体感最直接的输出风格开关。
【取值范围】
  仅接受上表模式词；其他输入会得到用法提示（不会被静默当成默认）。
【权限与效果】
  权限=仅管理员。写入运行时覆盖，持久保存，立即生效。
  相关键：BOT_CHAT_MAX_TOKENS（输出上限）、BOT_CHAT_FAST_MODE（快速模式）。
【示例】/bot reply 详细｜/bot reply 精简｜/bot reply 默认
/bot reply 详细：先说明结论、身份、关系、关键经历和资料缺口，不强制凑字数。
/bot runtime set BOT_CHAT_MAX_TOKENS 8192：输出上限，不是必须生成的长度。
/bot runtime set BOT_CHAT_FAST_MODE false：知识验收阶段关闭快速模式。
BOT_CHAT_MAX_TOKENS=65538 是最大上限，不是每次强制生成 64K。
文件生成：明确说“生成/保存/导出文件”，机器人会先写文件，再走上传接口。
戳一戳：默认响应有冷却；BOT_POKE_ENABLED、BOT_POKE_*_COOLDOWN_SECONDS、BOT_POKE_PROBABILITY 可调。
/bot runtime set BOT_CHAT_FAST_MAX_TOKENS 8192：重新启用快速模式时的输出上限。
运行时覆盖优先于 .env；用 runtime get 查看实际设置。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 回复` 为准。

## 模型

- 权限：仅管理员
- 触发别名：模型；model；llm；渠道；切换模型
- 能力入口：/bot model
- 网络依赖：需要联网
- 配置变量：BOT_MODEL_SCHEDULE；BOT_MODEL_PRIORITY_GROUPS
- 可复制示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1
- 关联回归测试：tests/test_model_admin_and_schedule.py；tests/test_model_router_failover.py
- 总览：【模型】/bot model list | set | add | update | priority | effort | think | price | search | usage | health | probe | routes | vision | remove | reset
- 标题：【模型】模型与供应商管理（管理员，改动即时生效）

### 教程

【板块介绍】
  模型注册表＋故障转移＋渠道健康＋思考强度＋计费的总控台。
  /bot model 与 /bot runtime model 等价。改动即时生效、无需重启；
  运行时覆盖优先于 .env。
【指令与参数】
/bot llm：作用=诊断当前渠道；参数=无；内容=provider/model/key 状态与一次短调用结果；意义=真实连通性验证（会花钱）。
/bot model list：作用=看底表；参数=无；内容=候选模型/档位/顺序/时段分组/健康/价格；意义=一切模型操作的起点。
/bot model health：作用=健康报告；参数=无；内容=ok/踢出/慢渠道三段（评级用平滑延迟 EWMA）；意义=解释渠道为什么被跳过。
/bot model probe：作用=手动巡检；参数=无；内容=受理提示；意义=立刻体检全部渠道（每渠道一次最小调用，费用极低；与后台巡检互斥）。
/bot model routes <模型名>：作用=渠道测速排名；参数=模型名（必填）；内容=快→慢列表；意义=挑最快渠道。
/bot model set <id|auto>：作用=手动指定；参数=id|auto（必填）；内容=确认信息；意义=钉死模型；auto 撤销。手动指定 > 时段组 order > 基础 priority。
/bot model add <id> model= base_url= key= [tags=] [effort=] [group=] [priority=]：作用=新增；参数逐个：id=你起的名字（之后 set/update/remove 用它）；model=供应商模型名原样填；base_url=OpenAI 兼容接口，http(s):// 开头一般 /v1 结尾；key=sk-xxx 或 env:变量名；tags=档位列表逗号分隔；effort=单模型覆盖；group=令牌分组；priority=整数越小越先（默认 100）；内容=注册即进路由；意义=免重启扩容。
/bot model update <id> <键=值...>：作用=改条目；参数=只写要改的键（model base_url key group tags effort priority）；内容=更新确认；意义=换 key/改档位；可覆盖 .env 同名条目。
/bot model priority <id> <n>：作用=调转移顺序；参数=n 整数，1..N 唯一槽位（移动一个其余顺移，0 兼容为移到首位）；内容=新顺序；意义=控成本（贵的放后）。
/bot model effort <id> <档位>：作用=单模型强度；参数=off|low|medium|high|xhigh|max|default（default/默认/reset=清除覆盖回家族基线）；内容=确认信息；意义=单点微调。
/bot model think <档位>：作用=全局强度；参数=off|low|medium|high|xhigh|max 或留空（留空=清空覆盖）；内容=确认信息；意义=全局控制推理开销；复杂任务会临时升档。
/bot model price <模型名> [input= output=]：作用=维护价格；参数=模型名必填；input/output=元/每百万 token，数字≥0；不带价格参数=清除；内容=设置/清除确认；意义=账单准确性；调价只影响之后的调用。
/bot model usage [today|YYYY-MM-DD]：作用=日账单；参数=日期可选；内容=Token/费用/按模型分组/未计价次数；意义=成本可见。
/bot model search <on|off>：作用=联网搜索开关；参数=on|off 必填；内容=开关确认；意义=热控 web_search。
/bot model vision list|add|update|priority|remove：作用=识图模型管理；参数=同模型条目；内容=注册表变化；意义=识图选型。
/bot model vision mode <relay|direct>：作用=识图模式；参数=relay（视觉模型转文字）|direct（图片直传主模型）；内容=模式确认；意义=多模态质量与成本取舍。
/bot model remove <id>：作用=删除；参数=id 必填（.env 来源不可删）；内容=删除确认；意义=清理。
/bot model reset：作用=回自动选型；参数=无；内容=确认信息；意义=撤销手动 set。
【取值范围】
  档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high。
  时段分组：/bot runtime set BOT_MODEL_PRIORITY_GROUPS <JSON 数组>，每组
  {"name":"工作日高峰","days":[1..7],"windows":[["09:00","12:00"]],"order":[模型id...]}；
  days 缺省=每天，windows 缺省=全天，都缺省=兜底组；按列表顺序取第一个命中组。
  分时段切换：/bot runtime set BOT_MODEL_SCHEDULE {"23:00-07:00":"luna"}（支持跨零点）。
【权限与效果】
  权限=仅管理员。全部子命令热更立即生效、持久保存；key 永不回显；
  不要在群聊发送真实 Key，用 key=env:变量名。
【示例】/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1
priority 是 1..N 唯一槽位：移动一个模型，其他模型自动顺移；0 兼容为移到首位。
手动指定 > 时段组 order > 基础 priority。时段组启用时基础排序不覆盖组内顺序。
model list 显示候选配置，不等于上一条实际回答的供应商；/bot llm 会产生新的诊断调用。
不要在群聊发送真实 Key；使用 key=env:变量名，在本地安全配置凭据。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 模型` 为准。

## 用量

- 权限：仅管理员
- 触发别名：用量；usage；账单；花费；监控
- 能力入口：/bot model usage
- 网络依赖：纯本地
- 输出形式：文本＋Mica 账单卡
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 配置变量：BOT_USAGE_ALERT_INPUT_TOKENS；BOT_USAGE_ALERT_OUTPUT_TOKENS；BOT_USAGE_ALERT_DAILY_COST_YUAN；BOT_USAGE_REPORT_HOURS
- 可复制示例：/bot model usage 2026-09-01
- 关联回归测试：tests/test_llm_ledger.py；tests/test_model_effort_groups_and_pricing.py
- 总览：【用量】Token 统计、费用记账与监控提醒：/bot model usage | /bot model price
- 标题：【用量】Token 统计、费用记账与监控提醒

### 教程

【板块介绍】
  用量监控三件套：账单查询（usage）、价格维护（price）、主动提醒
  （实时阈值＋定时报告）。提醒与报告推给全部管理员（QQ 私聊，统一预警
  管线），渲染可用时附 Mica 账单卡，失败回退纯文本。
【指令与参数】
/bot model usage [today|YYYY-MM-DD]：作用=查账单；参数=日期（可选，today/今天/YYYY-MM-DD，省略=今天，格式错回用法）；内容=Token 四项＋调用次数＋费用＋按模型明细；意义=成本审计。
/bot model price <模型名> [input= output=]：作用=维护价格；参数=见「模型」模块；内容=确认信息；意义=计费基准。
【取值范围】
  阈值 .env 键：BOT_USAGE_ALERT_OUTPUT_TOKENS（默认 5,000,000）、
  BOT_USAGE_ALERT_INPUT_TOKENS（默认 50,000,000）、BOT_USAGE_ALERT_DAILY_COST_YUAN（默认 10）。
  报告时间：BOT_USAGE_REPORT_HOURS（逗号分隔整点，默认 13,18,23）。
【权限与效果】
  权限=仅管理员。每项实时提醒每天最多触发一次；报告时间点持久化，重启不丢。
【示例】/bot model usage 2026-09-01

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 用量` 为准。

## 设置

- 权限：仅管理员
- 触发别名：设置；runtime；参数；設置；參數；运行时
- 能力入口：/bot runtime
- 配置变量：BOT_REPLY_DETAIL；BOT_CHAT_MAX_TOKENS；BOT_CHAT_FAST_MODE；BOT_CHAT_REASONING_EFFORT；BOT_MODEL_PRICES；BOT_MODEL_SCHEDULE；BOT_MODEL_PRIORITY_GROUPS；BOT_VISION_ENABLED；BOT_QUIET_HOURS_ENABLED；BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR；BOT_GROUP_CHAT_AUTO_REPLY_ENABLED
- 可复制示例：/bot runtime set BOT_QUIET_HOURS_ENABLED true
- 关联回归测试：tests/test_help_entries_coverage.py
- 总览：【设置】运行时参数：/bot runtime set|get|list|reset|nickname|persona|instance
- 标题：【设置】运行时参数管理（管理员）

### 教程

【板块介绍】
  运行时参数层：SETTABLE_KEYS 白名单内的键可热改并持久化（运行时覆盖
  优先于 .env）；不在白名单的键（如五个持久化开关）只能改 .env 重启。
  所有子命令都可加 --instance <名称> 操作指定实例。
【指令与参数】
/bot runtime set <KEY> <VALUE>：作用=设置；参数=KEY 必填（白名单键，发错会列出可用键）、VALUE 必填（按键的类型校验，非法值拒绝）；内容=设置确认；意义=热改主入口。
/bot runtime get <KEY>：作用=读取；参数=KEY 必填；内容=值＋来源；意义=查实际生效值。
/bot runtime list：作用=列覆盖；参数=无；内容=覆盖清单；意义=盘点。
/bot runtime reset [KEY]：作用=清覆盖；参数=KEY 可选（省略=全部）；内容=清除计数；意义=回滚热改。
/bot runtime persona list：作用=列人格；参数=无；内容=可选人格与当前项；意义=选型。
/bot runtime persona switch <id|default>：作用=切人格；参数=id 或 default（default=回默认）；内容=切换确认；意义=运行期换人格。
/bot runtime persona probability <id> <0-1>：作用=设人格触发概率；参数=id＋概率（0..1）；内容=确认信息；意义=多人格混投。
/bot runtime nickname add|remove|list [昵称]：作用=昵称管理；参数=add/remove 需昵称参数；内容=昵称表；意义=昵称命令的触发词维护。
【常用可写键举例】
  BOT_MODEL_SCHEDULE（分时段切换，JSON）、BOT_MODEL_PRIORITY_GROUPS（峰谷分组，JSON 数组）、
  BOT_MODEL_PRICES（价格表 JSON）、BOT_CHAT_REASONING_EFFORT（off|low|medium|high|xhigh|max|留空）、
  BOT_REPLY_DETAIL、BOT_CHAT_MAX_TOKENS、BOT_CHAT_FAST_MODE、BOT_VISION_ENABLED、
  BOT_QUIET_HOURS_*（6 键）、BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 等（完整清单：/bot runtime get 随便发一个错键）。
【权限与效果】
  权限=仅管理员。写入即持久化并通知热更；个别装配期读取的键（如
  BOT_GROUP_CHAT_AUTO_REPLY_ENABLED）需重启，帮助各模块会单独标注。
【示例】/bot runtime set BOT_QUIET_HOURS_ENABLED true
/bot runtime get BOT_REPLY_DETAIL：查看实际详略模式及覆盖来源。
/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false：暂停自动抽取，不删除已有记忆。
/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15：抽取总预算（秒）。
/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200：抽取输出上限（1..4096）。
/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300：抽取失败后冷却。
记忆抽取复用聊天路由配置，采用独立调用状态；不使用另一枚基础 key 绕开模型注册表。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 设置` 为准。

## 搜索

- 权限：仅管理员
- 触发别名：搜索；search
- 能力入口：/bot search
- 网络依赖：需要联网
- 输出形式：文本（标题/摘要/链接列表）
- 配置变量：BOT_WEB_SEARCH_MAX_RESULTS
- 可复制示例：/bot search 守岸人是什么游戏的角色
- 关联回归测试：tests/test_search_api_providers.py
- 总览：【搜索】验证联网检索：/bot search <问题>
- 标题：【搜索】管理员验证联网检索

### 教程

【板块介绍】
  直接调用检索供应商（Tavily 主链＋fallback）做一次真实搜索，
  不走人格链路，用于验证搜索配置。
【指令与参数】
/bot search <问题>：作用=真实检索一次；参数=问题（必填）；内容=至多 BOT_WEB_SEARCH_MAX_RESULTS 条结果（默认 12）；意义=排障检索链路。
【权限与效果】
  权限=仅管理员。检索源不可达/被反爬/代理未生效时给出降级说明。
【示例】/bot search 守岸人是什么游戏的角色

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 搜索` 为准。

## 解析

- 权限：仅管理员
- 触发别名：解析；parse
- 能力入口：/bot parse
- 群聊/私聊差异：解析历史是全局范围（跨群/跨私聊），因此仅管理员可见
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot parse 20
- 关联回归测试：tests/test_parse_presentation_v2.py
- 总览：【解析】解析历史：/bot parse [数量]
- 标题：【解析】查看最近解析历史

### 教程

【板块介绍】
  解析历史是全局范围（跨群/跨私聊），因此收紧为管理员可见。
【指令与参数】
/bot parse：作用=看最近 10 条；参数=无；内容=URL/标题/时间；意义=快速回查。
/bot parse <数量>：作用=控制条数；参数=数量（可选，1-100，默认 10）；内容=对应条数；意义=深挖。
【权限与效果】
  权限=仅管理员（M24 收紧：链接自带 token 时等于二次扩散，不对普通成员开放）。
【示例】/bot parse 20

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 解析` 为准。

## 凭据

- 权限：仅管理员
- 触发别名：凭据；凭证；憑據；憑證；登录凭证；登錄憑證；alert；cookie
- 能力入口：/bot cookie
- 群聊/私聊差异：cookie 过期会私聊推送管理员告警
- 网络依赖：需要联网
- 输出形式：文本；cookie login 另含二维码图
- 可复制示例：/bot cookie import bilibili SESSDATA=...; bili_jct=...
- 关联回归测试：tests/test_cookie_import_hot_reload.py；tests/test_platform_credentials.py
- 总览：【凭据】凭据健康与 cookie 导入：/bot alert check｜/bot cookie status|import|login|check|expiry
- 标题：【凭据】检查 cookie/凭据健康

### 教程

【板块介绍】
  平台 cookie 是解析/下载/订阅的登录态。统一存在 cookies.txt，
  值永不回显；每天 10:00 定时巡检（bot_cookie_expiry_reminder_enabled
  可关），过期会私聊推送第一位在线管理员。
【指令与参数】
/bot alert check：作用=凭据体检；参数=--probe 可选开关；内容=各引用状态＋是否需重登；意义=被动巡检的手动版。
/bot cookie status：作用=查已录凭证；参数=无；内容=共 N/18 个平台已有凭证＋各平台明细；意义=核对。
/bot cookie import <平台> <Cookie头>：作用=导入；参数=平台（18 选 1，小写）＋Cookie 头（整行原文粘贴）；内容=accepted/normalized/skipped 统计；意义=同名不覆盖、热生效。
/bot cookie login <平台>：作用=扫码；参数=平台（当前 bilibili）；内容=二维码；意义=便捷登录。
/bot cookie check <平台>：作用=扫码结果；参数=平台；内容=登录状态；意义=确认。
/bot cookie expiry：作用=过期报告；参数=无；内容=全平台有效期；意义=批量巡检。
【权限与效果】
  权限=仅管理员（命令匹配层就拦，非管理员无感）。
【示例】/bot cookie import bilibili SESSDATA=...; bili_jct=...

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 凭据` 为准。

## 群策略

- 权限：仅管理员
- 触发别名：群策略；group；群
- 能力入口：/bot group
- 群聊/私聊差异：作用于群聊门禁：black1=完全静默只收不发；black2=只回「@且带指令」
- 配置变量：BOT_GROUP_BLACK1
- 可复制示例：/bot group add white1 123456789 987654321
- 关联回归测试：tests/test_group_policy.py
- 总览：【群策略】群回复策略档位：/bot group list|add|del|set|clear
- 标题：【群策略】群聊回复策略档位（管理员）

### 教程

【板块介绍】
  四档群聊策略：black1=完全静默只收不发；black2=只回“@且带指令”；
  white1=正常回复并可参与主动接话；white2=只回“@或显式命令”。
  不在任何名单=默认档（正常回复）。
【指令与参数】
/bot group list：作用=查看各档位名单；参数=无或 list；内容=四档群号清单；意义=盘点现状。
/bot group add <档位> <群号...>：作用=加群入档；参数=档位（必填，black1|black2|white1|white2）＋群号（必填，数字可多个）；内容=更新后名单；意义=批量管理。
/bot group del <档位> <群号...>：作用=移出档位；参数=同 add；内容=更新后名单；意义=解除。
/bot group set <档位> <群号...>：作用=覆盖档位名单；参数=同 add；内容=更新后名单；意义=整表重置。
/bot group clear <档位>：作用=清空档位；参数=档位（必填）；内容=空名单；意义=一键清空。
  动作词可用中文别名：加/加入=add，删/移除/remove=del，设/设置=set，清/清空/reset=clear，查/查看=list。
  群号必须纯数字，可一次给多个；档位写错会提示四档取值。
【权限与效果】
  权限=仅管理员。写入运行时覆盖（BOT_GROUP_BLACK1/BLACK2/WHITE1/WHITE2），
  热改立即生效。
【示例】/bot group add white1 123456789 987654321

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 群策略` 为准。

## 群文件

- 权限：仅管理员
- 触发别名：群文件；群文件统计
- 能力入口：/bot 群文件
- 群聊/私聊差异：仅群聊可用（统计当前群；私聊提示不可用）
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot 群文件
- 总览：【群文件】群上传统计：/bot 群文件（仅群聊）
- 标题：【群文件】群上传记录与整理建议（管理员）

### 教程

【板块介绍】
  群文件上传事件（OneBot group_upload）实时入 SQLite，按群/文件名/大小/
  时间/上传者记录。OneBot 不提供移动文件夹 API，所以“整理”落地为
  记录＋统计＋提醒，不假装能移动文件。
【指令与参数】
/bot 群文件：作用=统计当前群；参数=无；内容=最近上传与类型分布；意义=摸底。
【权限与效果】
  权限=仅管理员；仅群聊可用（私聊提示不可用）。
【示例】/bot 群文件

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 群文件` 为准。

## 日志

- 权限：仅管理员
- 触发别名：日志；logs
- 能力入口：bot.logs
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot logs error 20
- 总览：【日志】运行时日志：/bot logs [级别] [数量]
- 标题：【日志】查看运行时事件日志

### 教程

【板块介绍】
  运行时事件日志（runtime_event_log）的查询口：统一记录各能力的关键
  事件（WARNING/ERROR 等），按级别过滤、按条数截取。
【指令与参数】
/bot logs：作用=默认查询；参数=无；内容=info 级最近 50 条；意义=日常快查。
/bot logs <级别>：作用=按级别过滤；参数=级别（debug|info|warning|error，其他词回退 info）；内容=对应级别日志；意义=聚焦错误。
/bot logs <级别> <数量>：作用=级别＋条数；参数=数量（1-200，越界自动收敛；非数字回退 50）；内容=对应日志；意义=多看几条。
【权限与效果】
  权限=仅管理员。日志未启用时提示运行时事件日志未启用。
【示例】/bot logs error 20

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 日志` 为准。

## 文件

- 权限：仅管理员
- 触发别名：文件；文件导出；导出
- 能力入口：matcher:admin_file_export（文件导出）
- 网络依赖：需要联网
- 输出形式：文件
- 失败兜底：LLM 失败/转换失败/上传失败均回文本报错
- 可复制示例：文件 docx 鸣潮 2.0 版本角色梯度整理
- 关联回归测试：tests/test_file_exchange.py；tests/test_file_gateway_phase1.py
- 总览：【文件】生成文档并上传：文件 <md|markdown|docx|pptx|xlsx|pdf> <主题>
- 标题：【文件】主题生成文档并群文件上传（管理员）

### 教程

【板块介绍】
  LLM 按文档撰写提示词生成结构化 Markdown（分级标题/列表/表格，
  600-1200 字），再本地转换成目标格式，经平台上传接口发出。
【指令与参数】
文件 <格式> <主题>：作用=生成并上传文档；参数=格式（md/markdown/docx/pptx/xlsx/pdf，markdown 归一为 md）＋主题（必填，截 40 字作标题）；内容=上传确认或失败类型；意义=文件交付。
【权限与效果】
  权限=仅管理员（命令匹配层拦截）。生成与转换在后台线程执行（数十秒级），
  产出落 data/downloads/export/ 后上传；LLM 失败只报错误类型。
【示例】文件 docx 鸣潮 2.0 版本角色梯度整理

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 文件` 为准。

## 身份

- 权限：仅管理员
- 触发别名：身份；identity；会话身份
- 能力入口：/bot identity
- 群聊/私聊差异：在哪个群/私聊执行就对哪个会话生效，各会话互不影响
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_SESSION_IDENTITY_DB_PATH
- 可复制示例：/bot identity set 岸宝｜/bot identity tag 早起,秃头,干饭人
- 总览：【身份】会话身份记忆：/bot identity show|set|tag|clear｜自助称谓偏好：set-name|set-gender|unset-name|unset-gender
- 标题：【身份】会话级身份记忆（管理员）＋用户自助称谓偏好

### 教程

【板块介绍】
  给单个会话（群或私聊）设置独立的身份记忆：机器人怎么称呼你、带哪些
  标签。在哪个会话执行就只对那个会话生效。数据存
  data/session_identity.sqlite3（.env 可用 BOT_SESSION_IDENTITY_DB_PATH 改路径）。
  另有无需管理员的用户自助称谓偏好（set-name/set-gender/unset-name/
  unset-gender）：存 data/addressing_preferences.sqlite3，聊天人格上下文
  会优先采用你显式声明的称谓与性别。
【指令与参数】
/bot identity show：作用=查看；参数=无；内容=称呼「…」＋标签＋设置人＋更新时间；意义=核对。
/bot identity set <昵称>：作用=设称呼；参数=昵称必填（非空文本，可含中文/英文，建议 ≤16 字）；内容=已设定确认；意义=个性化称呼。
/bot identity tag <标签1,标签2>：作用=设标签；参数=逗号分隔标签串（最多保留 8 个，超出截断）；内容=已设定确认；意义=补充语气线索。
/bot identity clear：作用=清除；参数=无；内容=清除确认；意义=重置。
/bot identity set-name <称呼>：作用=自助设称谓；参数=称呼必填（非空，≤32 字）；内容=已记下确认；意义=无需管理员，自己定称呼。
/bot identity set-gender <值>：作用=自助登记性别自述；参数=male|female|nonbinary|custom|unknown（大小写不敏感）；内容=已记下确认；意义=语气分寸更合适，非法值不落库。
/bot identity unset-name：作用=清除称谓偏好；参数=无；内容=已清除/本就没有；意义=恢复自动称呼。
/bot identity unset-gender：作用=清除性别自述；参数=无；内容=已清除/本就没有；意义=恢复 unknown。
【权限与效果】
  权限=仅管理员。只调整该会话内的称呼与语气，不改变守岸人核心人格；
  防止会话身份被用来推翻人格设定（防 OOC 护栏内建于渲染层）。
  例外：set-name/set-gender/unset-name/unset-gender 四个自助子命令
  所有用户可用，且只能操作自己的偏好。
【示例】/bot identity set 岸宝｜/bot identity tag 早起,秃头,干饭人｜/bot identity set-name 岸友

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 身份` 为准。

## 怪癖

- 权限：仅管理员
- 触发别名：怪癖；quirk；人格怪癖
- 能力入口：/bot quirk
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_QUIRKS_ENABLED
- 可复制示例：/bot quirk list pending → /bot quirk approve 3fa2
- 关联回归测试：tests/test_quirks.py
- 总览：【怪癖】人格怪癖审核：/bot quirk list|approve|retire|add
- 标题：【怪癖】人格怪癖演化区（管理员，审核制）

### 教程

【板块介绍】
  L4 人格演化区：一小批可选的说话习惯/怪癖，生效后由人格装配渲染进
  上下文。审核制红线：自动来源只进待审队列；管理员 add 直添是唯一
  免审通道。数据存 data/persona_quirks.sqlite3。
【指令与参数】
/bot quirk list [状态]：作用=列出；参数=状态过滤可选（pending|active|retired，其他值回用法），limit=20；内容=清单；意义=审核前置。
/bot quirk approve <id前缀>：作用=放行；参数=id 前缀（唯一命中）；内容=已通过；意义=待审→生效，之后渲染进人格上下文。
/bot quirk retire <id前缀>：作用=退役；参数=id 前缀（唯一命中）；内容=已退役；意义=生效→退役，记录保留不再渲染。
/bot quirk add <习惯描述>：作用=直添；参数=描述必填；内容=已直接生效；意义=管理员特权通道。
【取值范围】
  状态只有三种：待审 pending(pending_review)/生效 active/退役 retired；
  前缀必须唯一命中；BOT_QUIRKS_ENABLED=false 时命令只返回停用提示。
【权限与效果】
  权限=仅管理员。approve 后的 active 项渲染进人格上下文；待审项在
  approve 前对回复没有任何影响。
【示例】/bot quirk list pending → /bot quirk approve 3fa2

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 怪癖` 为准。

## 限流

- 权限：仅管理员
- 触发别名：限流；句数帽；安静时间；情绪豁免；自动接话
- 能力入口：/bot runtime set（配置型模块，无独立命令）
- 群聊/私聊差异：群聊门禁：安静时间、句数帽、情绪豁免、自动接话
- 输出形式：无直接输出（配置型模块）
- 配置变量：BOT_QUIET_HOURS_ENABLED；BOT_QUIET_HOURS_START；BOT_QUIET_HOURS_END；BOT_QUIET_HOURS_TIMEZONE；BOT_QUIET_HOURS_SESSION_TYPES；BOT_QUIET_HOURS_BYPASS_ROLES；BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR；BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE；BOT_RATE_LIMIT_EMOTION_EXEMPT；BOT_GROUP_CHAT_AUTO_REPLY_ENABLED；BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY
- 可复制示例：/bot runtime set BOT_QUIET_HOURS_START 01:00
- 关联回归测试：tests/test_group_rate_limit.py；tests/test_sqlite_rate_limit_group.py；tests/test_policy_sender_interval.py
- 总览：【限流】群句数帽/情绪豁免/安静时间/自动接话：BOT_RATE_LIMIT_*、BOT_QUIET_HOURS_*
- 标题：【限流】群聊句数帽、情绪豁免、安静时间与自动接话（管理员）

### 教程

【板块介绍】
  控制机器人在群里的回复频率与时机：句数帽封顶、情绪豁免保安抚、
  安静时间定时闭嘴、自动接话按概率抽签。全部经 /bot runtime set 修改。
【指令与参数】
BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR：作用=每小时句数帽；参数=≥0 整数（0=该帽不生效）；内容=超帽静默；意义=小时级封顶。
BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE：作用=每分钟句数帽；参数=同上；内容=同上；意义=脉冲防护；用户口径建议 60/小时、3/分钟。
BOT_RATE_LIMIT_EMOTION_EXEMPT：作用=情绪豁免；参数=true/false（默认 true）；内容=安抚类回复绕过句数帽；意义=该安慰的时候不被限流卡住。
BOT_GROUP_CHAT_AUTO_REPLY_ENABLED：作用=自动接话总开关；参数=true/false（默认 false）；内容=开/关；意义=接话前提。
BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY：作用=接话概率；参数=0..1（默认 0.004，与心情系数相乘后封顶 1.0）；内容=每次抽签现算；意义=频率。
安静时间 6 键：作用=安静时间窗；参数=ENABLED（true/false）、START/END（HH:MM，支持跨零点，默认 00:00-06:00）、TIMEZONE（IANA 名）、SESSION_TYPES（group|private|email 逗号分隔，默认 group）、BYPASS_ROLES（默认 admin）；内容=窗口内只拦未点名普通聊天/解析；意义=作息。
【权限与效果】
  权限=仅管理员。热改立即生效；点名/显式命令永远不受安静时间与概率影响；
  自动接话用确定性哈希抽签，同一消息结果稳定。
【示例】/bot runtime set BOT_QUIET_HOURS_START 01:00

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 限流` 为准。

## 合并转发

- 权限：仅管理员
- 触发别名：合并转发；转发合并
- 能力入口：/bot runtime set（配置型模块，无独立命令）
- 网络依赖：纯本地
- 输出形式：无直接输出（配置型模块）
- 配置变量：BOT_RENDER_FORWARD_MIN_NODES；BOT_RENDER_FORWARD_MIN_CHARS；BOT_RENDER_FORWARD_MAX_NODES；BOT_RENDER_FORWARD_NODE_CHARS
- 可复制示例：/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3
- 总览：【合并转发】长回复合并阈值：/bot runtime set BOT_RENDER_FORWARD_*
- 标题：【合并转发】长回复合并为转发消息的阈值（管理员）

### 教程

【板块介绍】
  长回复按字数/条数切成多个节点并合并成一条 QQ 合并转发消息，
  四个键分别控制条数触发、字数触发、节点上限与单节点字数。
【指令与参数】
BOT_RENDER_FORWARD_MIN_NODES：作用=按条数触发合并；参数=≥0 整数（默认 4，0=不按条数）；内容=达标即合并；意义=超过 3 条就打包。
BOT_RENDER_FORWARD_MIN_CHARS：作用=按字数触发合并；参数=≥0 整数（默认 1500）；内容=达标也合并；意义=长文兜底。
BOT_RENDER_FORWARD_MAX_NODES：作用=节点数上限；参数=≥0 整数（默认 0=不限制）；内容=块数尽量压到上限；意义=防刷屏。
BOT_RENDER_FORWARD_NODE_CHARS：作用=单节点目标字数；参数=≥200 整数（默认 900）；内容=单节点体积；意义=阅读体验。
  四键均经 /bot runtime set 热改。
【权限与效果】
  权限=仅管理员。条数达 MIN_NODES 或字数达 MIN_CHARS 即合并；
  消费点在装配期读取，改动需重启生效。
【示例】/bot runtime set BOT_RENDER_FORWARD_MIN_NODES 3

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 合并转发` 为准。

## 群摘要

- 权限：仅管理员
- 触发别名：群摘要；群聊摘要；群概要
- 能力入口：/bot runtime set（配置型模块，无独立命令）
- 群聊/私聊差异：面向群聊：每日定时向摘要白名单群推送（非白名单零推送）
- 网络依赖：需要联网
- 输出形式：每日定时推送文本摘要
- 配置变量：BOT_GROUP_DIGEST_LIST_MODE；BOT_GROUP_DIGEST_WHITELIST；BOT_GROUP_DIGEST_BLACKLIST；BOT_GROUP_DIGEST_LLM_ENABLED；BOT_GROUP_DIGEST_MAX_CHARS；BOT_GROUP_DIGEST_MAX_TURNS；BOT_GROUP_DIGEST_PUSH_ENABLED；BOT_GROUP_DIGEST_PUSH_TIME；BOT_SHARED_GROUP_CONTEXT_ENABLED
- 可复制示例：/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist
- 关联回归测试：tests/test_group_digest_push.py；tests/test_shared_group_digest_list.py
- 总览：【群摘要】群聊摘要与名单：BOT_SHARED_GROUP_CONTEXT_ENABLED、BOT_GROUP_DIGEST_*、每日通讯总结推送
- 标题：【群摘要】群聊上下文摘要、群名单与每日通讯总结推送（管理员）

### 教程

【板块介绍】
  群聊上下文摘要（shared_group）：把群内近期对话浓缩成摘要供人格参考；
  名单模式决定哪些群参与；每日通讯总结推送（G-DIGEST）在每天固定时刻
  把当日摘要主动推回白名单群。
【指令与参数】
BOT_SHARED_GROUP_CONTEXT_ENABLED：作用=总开关；参数=true/false（默认 false）；内容=关=完全不生成；意义=前提。
BOT_GROUP_DIGEST_LIST_MODE：作用=名单模式；参数=whitelist|blacklist|off|all；内容=筛选规则；意义=圈群。
BOT_GROUP_DIGEST_WHITELIST/BLACKLIST：作用=名单；参数=群号列表（多分隔符/JSON，去重）；内容=名单；意义=白/黑名单内容。
BOT_GROUP_DIGEST_PUSH_ENABLED：作用=每日推送开关；参数=true/false（.env 键，默认 true，不进 runtime set 白名单）；内容=开/关夜间推送；意义=日报总闸。
BOT_GROUP_DIGEST_PUSH_TIME：作用=推送时刻；参数=HH:MM（时 0-23 分 0-59，默认 21:30，非法值启动即报错）；内容=调度时刻；意义=错峰推送。
【权限与效果】
  权限=仅管理员。总开关/名单/模式可 runtime set 热改；推送两键为 .env 键，
  改后重启生效。推送正文=一句守岸人引子＋当日摘要；同群同天不重发。
【示例】/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 群摘要` 为准。

## 视频理解

- 权限：仅管理员
- 触发别名：视频理解；识图；vision；视频
- 能力入口：/bot runtime set（配置型模块，无独立命令）
- 网络依赖：需要联网
- 输出形式：随回复注入理解结果
- 配置变量：BOT_VISION_ENABLED；BOT_VISION_MODE；BOT_VIDEO_UNDERSTANDING_ENABLED；BOT_VIDEO_DEEP_ENABLED；BOT_VIDEO_MAX_FRAMES；BOT_VIDEO_FUZZY_FOLLOWUP；BOT_VIDEO_PROGRESS_ACK_ENABLED；BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE；BOT_VISION_REPLY_PROBABILITY
- 可复制示例：/bot runtime set BOT_VISION_MODE relay
- 关联回归测试：tests/test_video_understanding.py；tests/test_video_seam.py
- 总览：【视频理解】识图与视频理解开关：BOT_VISION_ENABLED、BOT_VIDEO_UNDERSTANDING_ENABLED
- 标题：【视频理解】图片/表情包识别与视频理解（管理员）

### 教程

【板块介绍】
  识图（vision）：群图片/表情包内容识别；视频理解：视频抽帧＋音轨/字幕
  生成感知简报，支持后续追问。两者各有总开关与模型注册表。
【指令与参数】
BOT_VISION_ENABLED：作用=识图总闸；参数=true/false（默认 false）；内容=开/关；意义=前提。
BOT_VISION_MODE：作用=模式；参数=relay|direct（默认 direct）；内容=管线；意义=取舍。
BOT_VISION_REPLY_PROBABILITY：作用=回应概率；参数=0..1（默认 1.0）；内容=触发率；意义=降噪。
BOT_VIDEO_UNDERSTANDING_ENABLED：作用=视频理解总闸；参数=true/false（默认 false）；内容=开/关；意义=前提。
BOT_VIDEO_MAX_FRAMES：作用=抽帧数；参数=正整数（默认 6，0 视同 1）；内容=分析密度；意义=成本。
BOT_VIDEO_SKIP_ASR_WITH_SUBTITLE：作用=有 CC 字幕时跳过音轨转写；参数=true/false（默认 true）；内容=管线加速；意义=省时省钱。
BOT_VIDEO_FUZZY_FOLLOWUP：作用=模糊追问（“刚才那个讲了什么”）；参数=true/false（默认 true）；内容=追问能力；意义=体验。
BOT_VIDEO_DEEP_ENABLED：作用=深挖重分析（“再仔细看看”）；参数=true/false（默认 true）；内容=更多帧＋强制 ASR；意义=深读，耗时更长。
【权限与效果】
  权限=仅管理员。全部可 /bot runtime set 热改；进度提示（“视频我看一下，
  稍等…”）默认开，同会话 60 秒节流（BOT_VIDEO_PROGRESS_ACK_ENABLED）。
【示例】/bot runtime set BOT_VISION_MODE relay

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 视频理解` 为准。

## 运行开关

- 权限：仅管理员
- 触发别名：运行开关；诊断开关；持久化开关
- 能力入口：.env（持久化开关，改后重启生效，无运行时命令）
- 网络依赖：纯本地
- 输出形式：无直接输出（.env 开关）
- 配置变量：BOT_SEND_QUEUE_ENABLED；BOT_SEND_QUEUE_WORKER_ENABLED；BOT_AUDIT_ENABLED；BOT_RECEIPTS_ENABLED；BOT_DIAGNOSTICS_ENABLED；BOT_SEND_QUEUE_MAX_ITEMS
- 可复制示例：.env 里 BOT_AUDIT_ENABLED=true 后重启。
- 总览：【运行开关】发送队列/审计/回执/诊断持久化：BOT_SEND_QUEUE_ENABLED 等 5 键
- 标题：【运行开关】发送队列、审计、回执、诊断持久化开关（管理员）

### 教程

【板块介绍】
  五个持久化开关：发送队列、队列后台 worker、审计记录、发送回执、
  运行诊断。全部默认关闭；关闭时对应记录仅内存态，重启不保留。
【指令与参数】
BOT_SEND_QUEUE_ENABLED：作用=发送队列持久化；参数=true/false（默认 false）；内容=队列落 sqlite；意义=可靠投递。
BOT_SEND_QUEUE_WORKER_ENABLED：作用=队列后台投递线程；参数=true/false（默认 false）；内容=后台按批投递；意义=投递自动化。
BOT_AUDIT_ENABLED：作用=审计落库；参数=true/false（默认 false）；内容=/bot audit 跨重启可查；意义=合规。
BOT_RECEIPTS_ENABLED：作用=回执落库；参数=true/false（默认 false）；内容=/bot receipt 跨重启可查；意义=投递追踪。
BOT_DIAGNOSTICS_ENABLED：作用=运行诊断落库；参数=true/false（默认 false）；内容=/bot recent 汇总有料；意义=排障。
  五键均为 true/false 布尔 .env 键；落库路径由对应 BOT_*_DB_PATH 配置
  （留空=内存态）。队列参数另有 BOT_SEND_QUEUE_MAX_ITEMS/MAX_ATTEMPTS/RETRY_* 等键。
【权限与效果】
  权限=仅管理员。开启后 /bot status 会显示各开关与 store=sqlite/memory 状态。
【示例】.env 里 BOT_AUDIT_ENABLED=true 后重启。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 运行开关` 为准。

## 邮件

- 权限：仅管理员
- 触发别名：邮件；电子邮件；mail；email；邮箱
- 能力入口：on_command:mail
- 网络依赖：需要联网
- 输出形式：文本确认
- 可复制示例：/mail send someone@example.com | 测试 | 这是一封测试邮件
- 关联回归测试：tests/test_mail_bridge.py；tests/test_mail_adapter_resilience.py
- 总览：【邮件】Gmail/QQ 收发与发件账户控制（Telegram 管理端）：/mail status|accounts|use|send|pause|resume
- 标题：【邮件】Gmail/QQ IMAP/SMTP 收发与 Telegram 控制

### 教程

【板块介绍】
  邮件桥把 Gmail/QQ 邮箱（IMAP/SMTP）接进统一运行时：新邮件提醒、
  AI 自动回复、人工发信。控制面在 Telegram 管理端，QQ 侧不受理。
【指令与参数】
/mail status：作用=看桥接状态；参数=无；内容=开关/账户/发件身份；意义=总览。
/mail accounts：作用=列可用账户；参数=无；内容=认证账户与别名；意义=选型。
/mail use <发件邮箱>：作用=设默认发件身份；参数=邮箱（必填，须已连接或已映射）；内容=切换确认；意义=免每次 --from。
/mail send <收件邮箱> | <主题> | <正文>：作用=发信；参数=三段必填（| 分隔，主题/正文非空）；内容=发送结果；意义=快速发信。
/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>：作用=临时身份发信；参数=四段缺一不可；内容=发送结果；意义=借身份。
/mail pause：作用=暂停自动回复；参数=无；内容=确认（收件提醒继续）；意义=只收不回。
/mail resume：作用=恢复自动回复；参数=无；内容=确认；意义=恢复。
【权限与效果】
  权限=仅管理员（Telegram 管理端：BOT_TELEGRAM_ADMIN_USER_IDS/CHAT_IDS），
  且只能从 Telegram 适配器发送；非管理端执行会收到“仅允许从 Telegram
  管理端执行”提示。SMTP/适配器错误只回报类型不回显细节。
【示例】/mail send someone@example.com | 测试 | 这是一封测试邮件

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 邮件` 为准。

## Telegram

- 权限：仅管理员
- 触发别名：telegram；tg；电报；纸飞机；飞机
- 能力入口：.env（Telegram 适配器配置）
- 网络依赖：需要联网
- 输出形式：跨平台消息/提醒
- 配置变量：BOT_TELEGRAM_ADMIN_USER_IDS；BOT_TELEGRAM_ADMIN_CHAT_IDS
- 可复制示例：TELEGRAM_BOTS=["123456:ABC-DEF..."]
- 关联回归测试：tests/test_telegram_parser_v2.py；tests/test_telegram_media.py
- 总览：【Telegram】提醒与远程控制配置：TELEGRAM_BOTS、BOT_TELEGRAM_ADMIN_*
- 标题：【Telegram】新邮件提醒与 Bot 远程控制

### 教程

【板块介绍】
  Telegram 通道的三大用途：新邮件提醒推送、/mail 邮件控制的管理端、
  运行时远程控制（状态/暂停/恢复）。三个 .env 键决定它是否生效。
【指令与参数】
TELEGRAM_BOTS：作用=注册 Telegram Bot；参数=JSON 数组（BotFather Token 列表，至少 1 个才连接）；内容=TG 侧 bot 上线；意义=远程控制入口。
BOT_TELEGRAM_ADMIN_USER_IDS：作用=指定管理员；参数=JSON 字符串数组（user id）；内容=允许执行 /mail 控制的用户；意义=权限边界。
BOT_TELEGRAM_ADMIN_CHAT_IDS：作用=指定提醒接收会话；参数=JSON 字符串数组（chat id）；内容=新邮件提醒推送目标；意义=收提醒。
  三键均为 .env 键，改后重启生效；/bot status、/bot pause|resume 可在 TG 侧远程执行。
【权限与效果】
  权限=仅管理员配置可用。
【示例】TELEGRAM_BOTS=["123456:ABC-DEF..."]

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help Telegram` 为准。

## 供应商

- 权限：仅管理员
- 触发别名：供应商；provider；providers；模型供应商；包台
- 能力入口：.env（模型注册表；/bot model 亦可视图）
- 网络依赖：纯本地
- 输出形式：配置视图（.env/模型注册表）
- 配置变量：BOT_MODEL_REGISTRY；BOT_CHAT_FAST_MAX_CANDIDATES
- 可复制示例：BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}
- 关联回归测试：tests/test_chat_provider_chain.py
- 总览：【供应商】模型分组、优先级与健康检查：BOT_MODEL_REGISTRY、probe_llm_providers.py
- 标题：【供应商】LLM 分组、路由优先级与健康检查

### 教程

【板块介绍】
  供应商层：.env 静态注册表（BOT_MODEL_REGISTRY）＋运行时动态注册
  （/bot model add）合并成统一视图；探测脚本用于离线验收。
【指令与参数】
BOT_MODEL_REGISTRY：作用=登记中转供应商；参数=JSON 对象（每项 model/base_url/api_key/group/priority）；内容=注册表底表；意义=静态渠道来源。
priority：作用=全局尝试顺序；参数=整数 1-999（越小越优先）；内容=故障转移次序；意义=控成本，HCN 保底放最后。
BOT_CHAT_FAST_MAX_CANDIDATES：作用=快速模式候选上限；参数=0=不限制，1-100=最多尝试数；内容=候选裁剪；意义=控开销。
scripts/probe_llm_providers.py：作用=命令行脱敏探测；参数=--max-tokens（可选，1-4096，默认 32）；内容=每模型一次探测，不删除配置；意义=批量验收。
  运行期管理走 /bot model（见「模型」模块）。
【权限与效果】
  权限=仅管理员。registry 改 .env 后重启生效；运行时条目热生效。
【示例】BOT_MODEL_REGISTRY={"myapi":{"model":"deepseek-v4-pro","base_url":"https://api.xxx.com/v1","api_key":"env:MY_KEY","group":"g1","priority":1}}

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 供应商` 为准。

## 订阅

- 权限：普通用户可用
- 触发别名：订阅；訂閱；subscribe
- 能力入口：bot.subscribe
- 群聊/私聊差异：群内 add/list 需管理员且推往本群，pause/resume/remove 群内需管理员；私聊添加=推给自己
- 网络依赖：需要联网
- 可复制示例：/订阅 add https://space.bilibili.com/123456
- 关联回归测试：tests/test_subscribe_capability_v2.py；tests/test_subscription_delivery_v2.py
- 总览：【订阅】平台新内容推送：/订阅 add|list|pause|resume|remove
- 标题：【订阅】订阅平台新内容推送

### 教程

【板块介绍】
  订阅运行时按目标平台轮询新内容（视频/动态/直播开播/新歌），经统一
  发送管线推送。订阅目的地绑定“添加时的会话”：群里添加=推本群，
  私聊添加=推给你本人。
【指令与参数】
/订阅 add <公开目标>：作用=添加；参数=目标必填（链接或 类型:id；目的地/日报等附加参数暂不支持，写了会被拒绝并提示）；内容=添加确认；意义=订阅入口。
/订阅 list：作用=列表；参数=无；内容=订阅清单；意义=管理前置。
/订阅 pause <id>：作用=暂停；参数=id 必填；内容=暂停确认（只暂停本会话目的地）；意义=临时静默。
/订阅 resume <id>：作用=恢复；参数=id 必填；内容=恢复确认；意义=复播。
/订阅 remove <id>：作用=删除；参数=id 必填；内容=删除确认；意义=退订；重加已存在订阅不会把管理员暂停的订阅悄悄重启。
【权限与效果】
  权限=全员自助；群内 add/list 需要管理员（add 会向全群推送外部内容，无门槛=投毒面）；
  私聊自助。pause/resume/remove 的目的地粒度：只影响本群/本人，别的群
  订同一条不受影响。
【示例】/订阅 add https://space.bilibili.com/123456

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 订阅` 为准。

## 点歌

- 权限：普通用户可用
- 触发别名：点歌；music；點歌；点唱；點唱；song；diange；dg；diangemoshi；dgms
- 能力入口：bot.music / bot.music_mode
- 自然语言触发：点歌 <歌名>；来一首；来首；放一首；播放 <歌名>；唱一首歌
- 群聊/私聊差异：群聊/私聊行为一致（会话仅用作统计 scope/候选键）
- 网络依赖：需要联网
- 输出形式：卡片图/文本/语音（按点歌模式组合）
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 配置变量：BOT_MUSIC_MODE；BOT_MUSIC_CANDIDATES_ENABLED；BOT_MUSIC_CANDIDATES_LIMIT；BOT_MUSIC_CANDIDATES_TTL_SECONDS
- 可复制示例：点歌 晴天｜点歌 2｜点歌模式 卡片+语音
- 关联回归测试：tests/test_music_capability_analytics_v2.py；tests/test_music_candidates_card.py；tests/test_music_charts_real_sources_v2.py
- 总览：【点歌】搜索并发送歌曲：点歌 <歌名>｜点歌 <编号>｜点歌模式 <部件组合>
- 标题：【点歌】搜索并发送歌曲

### 教程

【板块介绍】
  纯接口搜索不调 LLM；输出部件可拆可组：card=平台音乐卡片（默认）、
  voice=语音、file=音频文件、link=文本链接。多候选交互需开启
  BOT_MUSIC_CANDIDATES_ENABLED（默认关）：同名歧义返回编号列表，
  有效期 BOT_MUSIC_CANDIDATES_TTL_SECONDS（默认 300 秒，下限 30），
  候选数 BOT_MUSIC_CANDIDATES_LIMIT（默认 5，下限 2）。
【指令与参数】
点歌 <歌名>：作用=搜索发送；参数=歌名必填；内容=按当前模式的部件组合；意义=核心玩法。查询词与模式别名同名（如「点歌 link」）会得到冲突提示与转义用法，不再静默丢弃。
点歌 <编号>：作用=候选选择；参数=编号必填；内容=歌曲；意义=选版本；过期/无效编号会明确提示重新点歌，不会拿数字当歌名再搜一遍。
点歌模式 [模式]：作用=查/设输出方式；参数=模式（卡片|语音|音频|链接|全部，支持 +/和/与 组合词；省略=查当前模式）；内容=当前或新模式的部件清单；意义=输出定制。
【权限与效果】
  点歌=全员；点歌模式=仅管理员（写入 BOT_MUSIC_MODE 持久化）。
【常见错误】编号只在候选列表有效期内有效；直接拿数字当歌名搜索不是有效歌名。
【示例】点歌 晴天｜点歌 2｜点歌模式 卡片+语音

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 点歌` 为准。

## 表情

- 权限：普通用户可用
- 触发别名：表情；meme；表情包；表情生成；表情制作；表情包制作；表情产生；表情包产生；表情製作；表情包製作；表情產生；表情包產生；biaoqing；biaoqingbao；bqb；biaoqingshengcheng；bqsc
- 能力入口：bot.meme
- 自然语言触发：表情 <模板> <文字>；表情帮助
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：纯本地
- 输出形式：图片
- 配置变量：BOT_MEME_COMMAND_ENABLED
- 可复制示例：表情 petpet 可爱｜表情 文字表情 早上好
- 关联回归测试：tests/test_meme_domain_fixes.py
- 总览：【表情】生成文字表情：表情 <模板> <文字>｜表情 列表
- 标题：【表情】生成文字表情

### 教程

【板块介绍】
  对接本地 meme-generator-rs HTTP API（默认 http://127.0.0.1:2233）。
  未安装/未启动服务时能力不可用。总开关 BOT_MEME_COMMAND_ENABLED；
  功能开关 BOT_MEME_API_ENABLED=true（管理员在 .env 配置，需本地 meme-generator-rs 服务）。
【指令与参数】
表情 <模板> [文字]：作用=生成；参数=模板 key 必填；文字按模板 min_texts/max_texts 要求，多段用全角 ｜ 分隔；内容=表情图；意义=梗图。纯 key 无文字时按模板的最少文字数判断是零文字模板还是打错 key。
表情 列表：作用=列模板；参数=无；内容=模板清单；意义=发现。
表情帮助：作用=说明；参数=无；内容=用法；意义=自助。
【权限与效果】
  权限=全员。
【示例】表情 petpet 可爱｜表情 文字表情 早上好｜晚上好

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 表情` 为准。

## 偷表情

- 权限：普通用户可用
- 触发别名：偷表情；偷表情包；偷圖；偷图；表情隨機；隨機表情；隨機表情包；表情抽籤；steal；toubiaoqing；tbq；toubiaoqingbao；tbqb
- 能力入口：bot.meme_library
- 自然语言触发：偷表情；偷张表情包；随机来张表情
- 群聊/私聊差异：写「私聊/私聊我」等同不填关键词，但改为私聊发送
- 输出形式：图片
- 配置变量：BOT_MEME_LIBRARY_ENABLED；BOT_MEME_LIBRARY_COOLDOWN_SECONDS
- 可复制示例：偷表情｜偷表情 猫猫
- 关联回归测试：tests/test_meme_domain_fixes.py
- 总览：【偷表情】表情库随机：偷表情 [关键词]｜表情库统计
- 标题：【偷表情】从表情库随机抽取

### 教程

【板块介绍】
  表情库由群图片自动吸收（VLM 打标、NSFW≥0.2 降权、≥0.8 永不发送）。
  权重：守岸人/岸宝最优先，其次鸣潮/战双/库洛，再次 ACG，最后普通。
  冷却 BOT_MEME_LIBRARY_COOLDOWN_SECONDS（默认 20 秒）防刷屏；总开关
  BOT_MEME_LIBRARY_ENABLED（默认 false，需开启）。
【指令与参数】
偷表情 [关键词]：作用=随机抽取；参数=关键词可选；内容=表情图；意义=氛围担当。bot 心情低落时对“吵闹”标签候选有限重抽（软偏置，不硬开关）。
表情库统计：作用=统计；参数=无；内容=库存概览；意义=盘点。
【权限与效果】
  权限=全员。
【示例】偷表情｜偷表情 猫猫

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 偷表情` 为准。

## 搜图

- 权限：普通用户可用
- 触发别名：搜图；搜圖；以图搜图
- 能力入口：on_message:搜图
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：文本（相似度/标题/URL 列表）
- 可复制示例：（发一张图＋文字）搜图
- 总览：【搜图】图片反搜来源：搜图 ＋图片/@图片
- 标题：【搜图】SauceNAO 图片反搜

### 教程

【板块介绍】
  调 SauceNAO 对图片做来源反搜。图片 URL 从消息图片段提取；
  引用消息里的原图链接拿不到时会提示把图片和「搜图」发在同一条消息。
【指令与参数】
搜图 [图片]：作用=反搜；参数=图片段（必传，命令后不带参数，图片在同一条消息里）；内容=匹配结果；意义=溯源。
【权限与效果】
  权限=全员。未配 SauceNAO key 或无结果时有降级提示。
【示例】（发一张图＋文字）搜图

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 搜图` 为准。

## 天气

- 权限：普通用户可用
- 触发别名：天气；weather；天氣；查天氣；天氣預報；tianqi；tq；chatianqi；ctq
- 能力入口：bot.weather
- 自然语言触发：天气 <城市>；帮我查<城市>天气；<城市>天气怎么样
- 群聊/私聊差异：查不到城市：群聊静默不回，私聊回明确报错文本（weather.py 会话分支）
- 网络依赖：需要联网
- 可复制示例：天气 上海｜天气 河北-大城｜支持区县 浙江
- 关联回归测试：tests/test_weather_alerts_b10.py；tests/test_weather_nmc_retry_nmcflix.py
- 总览：【天气】查询城市/区县天气：天气 <城市>｜支持区县 <省>
- 标题：【天气】查询城市与区县天气

### 教程

【板块介绍】
  数据源：中国气象局 NMC（免 key，内置 2527 个区县码表），失败时
  Open-Meteo 兜底；渲染可用时输出 Mica 天气卡。触发收窄：查询词需像
  地名——长度受限、不以「今天/真好/怎么样」等口语词开头、不以语气词
  收尾，所以「天气真好」不会误触发。
【指令与参数】
天气 <城市>：作用=查询；参数=城市或 省-市/省-县（必填，≤20 字）；内容=天气报告卡；意义=日常查询。
支持区县 <省>（别名 查询区县/可查区县）：作用=列区县；参数=省名必填；内容=区县列表；意义=发现可查的县级地名。
【权限与效果】
  权限=全员。自然语言「帮我查杭州天气」经意图归一化同样命中。
【示例】天气 上海｜天气 河北-大城｜支持区县 浙江

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 天气` 为准。

## 行情

- 权限：普通用户可用
- 触发别名：行情；market；stock market；股指；大盘；美股行情；港股行情；A股行情；hangqing；hq；gushi；gs；dapan；dp；guzhi
- 能力入口：bot.market
- 自然语言触发：行情；A股行情；全球股市；大盘；market；stock market
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚折线卡（MOEX 无东财 kline 时卡上无折线）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 可复制示例：行情｜A股行情｜B股行情｜莫斯科行情
- 关联回归测试：tests/test_market_github.py
- 总览：【行情】全球股指：行情 或 美股行情/港股行情/A股行情/B股行情/莫斯科行情…
- 标题：【行情】全球主要股指行情

### 教程

【板块介绍】
  数据来自东方财富 push2 免费接口（免 key），进程内 60 秒缓存，
  失败降级为「晚点再试」。触发收窄：≤32 字、不带链接（带链接走解析）、
  房价/基金/币圈/显卡/期货/汇率等非股市“行情”自动让路。
【指令与参数】
行情 [市场词…]：作用=查指数；参数=市场词可选（A股/B股/上证B/深证B/美股/港股/恒生/日经/纳斯达克/纳指/道琼斯/道指/标普/韩/新加坡/印度/台湾/台股/英国/富时/法国/德国/莫斯科/俄罗斯，多词取并集）；内容=指数清单；意义=盘面速览。
【权限与效果】
  权限=全员。B 股与莫斯科（IMOEX）指数已上线。
【示例】行情｜A股行情｜B股行情｜莫斯科行情

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 行情` 为准。

## 个股行情

- 权限：普通用户可用
- 触发别名：个股行情；股价；股票价格；市值；股價；個股；英伟达股价；AMD 股价；英特尔股价；美股股价；stocks；stock；gujia；gj；gupiao
- 能力入口：bot.stocks
- 自然语言触发：英伟达股价；AMD 股价；英特尔股价；股价；市值；股價；個股；美股股价；stocks；stock
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚金融卡（现价/日 K/KDJ/市值/走势折线/箱形图）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：行情拉不到回「美股行情暂时拉不到，晚点再试试？」；渲染失败回退纯文本
- 配置变量：BOT_CARD_RENDER_DIR
- 可复制示例：英伟达股价｜AMD 股价｜英特尔股价｜股价｜市值｜美股股价｜stocks
- 关联回归测试：tests/test_stock_data.py；tests/test_finance_data.py；tests/test_finance_routing.py
- 总览：【个股行情】科技公司股价：英伟达股价/AMD 股价/英特尔股价 或 股价/市值/stocks
- 标题：【个股行情】上市科技公司股价与市值

### 教程

【板块介绍】
  数据来自东方财富免费接口（免 key），进程内 60 秒缓存，免费源为
  延迟口径、卡上如实标注。当前支持：英伟达（NVDA）、AMD、英特尔
  （INTC）、苹果（AAPL）、微软（MSFT）、谷歌（GOOGL）、亚马逊（AMZN）、
  Meta（META）、台积电（TSM）；OpenAI/Anthropic/字节跳动未上市，只给
  有来源的估值说明、不接行情。触发收窄：≤32 字、不带链接；裸「行情」
  仍归全球股指，两者互不抢路由。
【指令与参数】
股价 [公司名]：作用=查股价/市值；参数=公司名或 ticker 可选（英伟达/AMD/英特尔/苹果/微软/谷歌/亚马逊/Meta/台积电，繁体 股價/個股 与英文 stock/stocks 同样可触发；不点名=九家面板）；内容=金融卡或纯文本速览；意义=个股速览。
【权限与效果】
  权限=全员，群聊/私聊行为一致。走势折线为近 30 个交易日收盘；
  箱形图只画多日分布，单日 K 线不成箱（不把 K 线冒充分布）。
【失败兜底】行情拉不到回「美股行情暂时拉不到，晚点再试试？」；
  卡片渲染失败自动回退纯文本。
【示例】英伟达股价｜AMD 股价｜英特尔股价｜股价｜市值｜美股股价｜stocks

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 个股行情` 为准。

## 汇率

- 权限：普通用户可用
- 触发别名：汇率；匯率；主要货币；美元兑人民币；100日元换多少人民币；USD/CNY；fx；forex；exchange rate；huilv；换算；換算
- 能力入口：bot.fx
- 自然语言触发：汇率；匯率；美元兑人民币；100日元换多少人民币；美元汇率；换算；換算；USD/CNY；fx；forex；exchange rate
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚金融卡（货币面板/换算行）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：汇率拉不到回「汇率数据暂时拉不到，稍后再试。」；渲染失败回退纯文本
- 配置变量：BOT_CARD_RENDER_DIR
- 可复制示例：汇率｜美元兑人民币｜100日元换多少人民币｜USD/CNY｜匯率
- 关联回归测试：tests/test_fx_data.py；tests/test_finance_routing.py
- 总览：【汇率】主要货币汇率：汇率 或 美元兑人民币/100日元换多少人民币/USD/CNY
- 标题：【汇率】主要货币汇率速览与换算

### 教程

【板块介绍】
  数据来自东方财富快查（免 key），进程内 60 秒缓存；中间价/参考价
  口径、延迟行情与非可成交价提示都标在卡上。覆盖 11 币种（USD/EUR/
  GBP/JPY/KRW/TWD/CNY/HKD/SGD/MOP/AED）；USD/TWD、USD/MOP、USD/AED
  东财暂无行情，会诚实说「暂无数据」，绝不补 0。汇率无可用日 K，
  卡上走势一栏如实标注，不伪造走势。
【指令与参数】
汇率 [币种]：作用=面板或单查；参数=币种可选（美元/人民币/日元/韩元/港币/欧元/英镑/新台币/新加坡元/澳门币/迪拉姆 或 ISO 代码；「美元汇率」这类单查默认兑人民币）；内容=汇率速览或换算行；意义=日常查询。
【权限与效果】
  权限=全员，群聊/私聊行为一致。繁体（匯率/兌換/換匯）与英文
  （fx/forex/exchange rate）同样可触发；股价/股指等股票语境词会
  自动让路给行情模块，不会误触汇率。
【失败兜底】汇率拉不到回「汇率数据暂时拉不到，稍后再试。」；
  卡片渲染失败自动回退纯文本。
【示例】汇率｜美元兑人民币｜100日元换多少人民币｜USD/CNY｜匯率

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 汇率` 为准。

## 占卜

- 权限：普通用户可用
- 触发别名：占卜；塔罗；八字；算命；算卦；起卦；塔羅；排盤；排盘；命盤；命盘；搖卦；摇卦；今日塔羅；今日塔罗；今天塔羅；今天塔罗；塔羅三張；塔罗三张；divination；tarot；bazi；iching；zhanbu；taluo；tl；suanming；suangua；sg；qigua；qg；求籤；求签；六十四卦；金錢卦；金钱卦；生辰八字；算一卦；起一卦；摇一卦；搖一卦；掷一卦；擲一卦；占一卦；一卦；每日一签；每日一簽；每日一抽；paipan；sizhu；mingpan；pp；mp；yaogua；yg；liushisigua；lssg；jinqiangua；hexagram
- 能力入口：bot.divination
- 自然语言触发：占卜；塔罗；塔羅；八字；算命；起卦；排盘；排盤；命盘；命盤；摇卦；搖卦；求签；求籤；今日塔罗；今日塔羅；今天塔罗；今天塔羅；塔罗三张；塔羅三張；tarot；bazi；iching；divination
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：纯本地
- 可复制示例：占卜｜塔罗 三张｜八字 1998年3月2日早上7点
- 关联回归测试：tests/test_divination.py
- 总览：【占卜】八字排盘/塔罗/金钱卦（含地支藏干）：占卜 | 塔罗 三张 | 八字 1998年3月2日早上7点
- 标题：【占卜】玄学娱乐三件套

### 教程

【板块介绍】
  玄学娱乐三件套：金钱卦（六十四卦）、塔罗（单张/三张/每日一抽）、
  八字排盘（含地支藏干）。纯本地计算无网络；输出为娱乐向文本并附
  免责尾注，不含医疗/投资等严肃建议。
【指令与参数】
占卜|起卦|算卦|摇卦|六十四卦|金钱卦：作用=起卦；参数=无；内容=卦象＋变卦；意义=卜问。
塔罗 [玩法]：作用=抽牌；参数=无=单张｜三张/牌阵=三张牌阵｜每日一抽/今日塔罗=日签（按 日期+用户 哈希同日固定）；内容=牌面与解读；意义=指引娱乐。
八字|排盘|四柱|命盘|算命|生辰 [生日时间]：作用=排盘；参数=生日时间可选（日期三种写法；时辰词归一化：下午/晚上/夜里/深夜 +12、凌晨12点=0点、中午=12 点；默认午时；缺省当前时点并附提示）；内容=四柱＋藏干（本气/中气/余干与通行子平权重，单支合计 100）＋藏干五行加权汇总＋尾注；意义=深度排盘。
【取值范围】
  可排盘区间 1900-2100 年；超出会优雅提示换时间。日期解析失败会给出
  可读错误与示例，不静默忽略。
【权限与效果】
  权限=全员，纯娱乐。
【示例】占卜｜塔罗 三张｜塔罗 每日一抽｜八字 1998年3月2日早上7点

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 占卜` 为准。

## 快报

- 权限：普通用户可用
- 触发别名：快报；快報；今日快报；早报；早報；晚报；晚報；今日热点；今日熱點；科技新闻；科技新聞；AI新闻；AI新聞；AI快報；财经快报；財經快報；财经新闻；財經新聞；国际新闻；國際新聞；news；kuaibao；kb；jinrikuaibao；jrkb
- 能力入口：bot.news
- 自然语言触发：快报；快報；今日热点；今日熱點；科技新闻；科技新聞；AI新闻；AI新聞；财经快报；財經快報；国际新闻；國際新聞
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 可复制示例：快报｜科技新闻｜财经快报｜国际新闻
- 关联回归测试：tests/test_news.py
- 总览：【快报】今日新闻快报：快报 或 科技新闻/AI新闻/财经快报/国际新闻
- 标题：【快报】今日新闻快报

### 教程

【板块介绍】
  国内可达 RSS 聚合（IT之家/少数派/华尔街见闻/BBC 中文），进程内
  10 分钟缓存，单源失败静默跳过；抓取为空给降级文案不阻塞会话。
【指令与参数】
快报 [类目词]：作用=取快报；参数=类目词写在同一句话里：财经→finance、国际→world、科技/AI/人工智能→tech、其余→mix 轮转；内容=8 条标题＋来源＋链接；意义=资讯。
【取值范围】
  只认显式触发词（快报/早报/晚报/今日热点/类目词×新闻|快报/AI快报），
  ≤32 字、不带链接；裸「新闻」不触发（留给联网搜索链路），句子带
  搜索/搜一下/查一下/找新闻/联网/上网 时让路。
【权限与效果】
  权限=全员。
【示例】快报｜科技新闻｜财经快报｜国际新闻

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 快报` 为准。

## 维基

- 权限：普通用户可用
- 触发别名：维基；wiki；百科；weiji；wjbk
- 能力入口：bot.wiki
- 自然语言触发：维基 <词条>；wiki <词条>
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：文本
- 失败兜底：区分「独立页缺失/列表缺失/网络失败」的文本提示
- 配置变量：BOT_WIKI_LANG；BOT_WIKI_ENTRY_PAGES
- 可复制示例：维基 量子力学｜维基 鸣潮守岸人
- 总览：【维基】查询百科词条：维基 <词条>
- 标题：【维基】查询百科词条

### 教程

【板块介绍】
  纯 MediaWiki 公开 API（免 key），默认中文维基（BOT_WIKI_LANG 可切），
  支持独立页缺失时的精确列表条目提取（BOT_WIKI_ENTRY_PAGES，默认
  鳴潮角色列表，最多优先 3 页）。
【指令与参数】
维基 <词条>：作用=查询；参数=词条名必填；内容=摘要或未找到提示（含可能原因）；意义=知识速查。
【权限与效果】
  权限=全员。查不到时会说明是独立页缺失、列表条目缺失还是网络失败。
【示例】维基 量子力学｜维基 鸣潮守岸人

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 维基` 为准。

## 萌娘百科

- 权限：普通用户可用
- 触发别名：萌娘百科；萌百；moegirl；mengbai；mb；是誰；是什麼；介紹一下；是谁；是什么；介绍一下
- 能力入口：bot.moegirl（二次元问句路由同归此能力）
- 自然语言触发：萌娘百科 <词条>；<角色名>是谁？；是谁；是誰；是什么；是什麼；介绍一下；介紹一下
- 群聊/私聊差异：二次元问句自动查询在群聊不 @ 不抢答（与聊天同门控）
- 网络依赖：需要联网
- 配置变量：BOT_MOEGIRL_QUESTION_ENABLED
- 可复制示例：萌娘百科 初音未来｜初音未来是谁？
- 关联回归测试：tests/test_moegirl_search.py；tests/test_moegirl_question_fix.py
- 总览：【萌娘百科】查询萌娘百科：萌娘百科 <词条>｜直接问 XX是谁
- 标题：【萌娘百科】查询萌娘百科词条

### 教程

【板块介绍】
  萌百 MediaWiki 公开 API。两条路径：显式指令；以及二次元实体问句
  自动查询（群聊不 @ 不抢答，与聊天同门控；BOT_MOEGIRL_QUESTION_ENABLED
  可关）。问句剥离后剩人称代词（你/我/谁…）、过短/过长、含链接的
  一律不查，交给聊天链路。
【指令与参数】
萌娘百科 <词条>：作用=显式查询；参数=词条名必填；内容=摘要；意义=定向。
「XX是谁？」式问句：作用=自动查询；参数=实体名（从问句剥离，2-30 字）；内容=命中=萌百摘要，未命中=人格聊天兜底；意义=无门槛问询。
【权限与效果】
  权限=全员。
【示例】萌娘百科 初音未来｜初音未来是谁？

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 萌娘百科` 为准。

## 历史上的今天

- 权限：普通用户可用
- 触发别名：历史上的今天；today；today in history；今日；lssd；jinrilishi；jrls
- 能力入口：bot.today_history
- 群聊/私聊差异：设置每日推送时间：群内需管理员（影响全群），私聊自助
- 网络依赖：需要联网
- 可复制示例：历史上的今天 设置 08:30
- 关联回归测试：tests/test_today_history_robustness.py
- 总览：【历史上的今天】每日历史推送：立即查 | 设置 HH:MM | 状态 | 取消
- 标题：【历史上的今天】每天定时推送历史

### 教程

【板块介绍】
  数据源百度百科公开接口（带缓存与代理支持）。推送订阅按会话存
  data/today_history_push.json（私聊 f_<user_id>、群聊 g_<group_id>），
  由调度器按表注册每日任务。
【指令与参数】
历史上的今天：作用=查询；参数=无；内容=当天历史；意义=即时消费。
历史上的今天 设置 <HH:MM>：作用=设每日推送；参数=HH:MM（24 小时制，冒号可用：）；内容=确认；意义=定时触达。
历史上的今天 状态：作用=查状态；参数=无；内容=推送时间；意义=核对。
历史上的今天 取消：作用=退订；参数=无；内容=确认；意义=退订。
【权限与效果】
  权限=全员查询；设置/取消在群聊需要管理员（推送时间影响全群），
  私聊自助。订阅表损坏时会拒绝改写以保护其他会话的订阅。
【示例】历史上的今天 设置 08:30

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 历史上的今天` 为准。

## 下载

- 权限：普通用户可用
- 触发别名：下载；download
- 能力入口：/bot download
- 网络依赖：需要联网
- 输出形式：文件＋文字摘要
- 失败兜底：失败优雅降级为文字（只说原因类型，不泄露堆栈与 cookie）
- 配置变量：BOT_DOWNLOAD_MAX_BYTES；BOT_DOWNLOAD_MAX_HEIGHT；BOT_DOWNLOAD_TIMEOUT_SECONDS；BOT_DOWNLOAD_PROXY
- 可复制示例：/bot download https://www.bilibili.com/video/BVxxxxxxxx
- 关联回归测试：tests/test_file_gateway_phase1.py；tests/test_unified_gateways.py
- 总览：【下载】下载视频/音频：/bot download <链接>
- 标题：【下载】下载视频/音频

### 教程

【板块介绍】
  yt-dlp 下载到 data/downloads/ 并做媒体分析，经发送管线回传文件段。
  cookies（/bot cookie import）与代理（BOT_DOWNLOAD_PROXY）对下载同样生效。
【指令与参数】
/bot download <链接>：作用=下载；参数=URL 必填（http(s) 开头）；内容=摘要＋文件；意义=核心功能。裸发「下载 …」当前不走路由，请使用 /bot 前缀。
【取值范围】
  大小上限 BOT_DOWNLOAD_MAX_BYTES（默认 1073741824=1GB）；最大高度
  BOT_DOWNLOAD_MAX_HEIGHT（默认 0=不限制，超限自动降级）；超时
  BOT_DOWNLOAD_TIMEOUT_SECONDS（默认 120 秒，发送侧最长 300 秒）。
【权限与效果】
  权限=全员。失败优雅降级为文字（只说原因类型，不泄露堆栈与 cookie）。
【示例】/bot download https://www.bilibili.com/video/BVxxxxxxxx

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 下载` 为准。

## 昵称

- 权限：普通用户可用
- 触发别名：昵称；alias
- 能力入口：bot.alias
- 配置变量：BOT_PERSONA_NICKNAMES
- 可复制示例：/岸宝帮助｜守岸人 天气 上海｜/岸宝点歌 晴天
- 关联回归测试：tests/test_nickname_default_seed.py；tests/test_nickname_learning.py
- 总览：【昵称】角色昵称触发命令：守岸人/岸宝 <命令>
- 标题：【昵称】用角色昵称触发命令

### 教程

【板块介绍】
  昵称命令层：把「/岸宝帮助」「守岸人 状态」解析成对应能力。昵称清单
  存运行时设置（BOT_PERSONA_NICKNAMES / runtime nickname 维护），
  未配置时别名层关闭；标准 /bot 前缀不受影响。
【指令与参数】
/<昵称><命令> [参数]：作用=触发；参数=命令动词（帮助/help、状态/status、为什么/why、记忆/memory、配置/config、就绪/readiness、人格/persona、对话验收/dialogue、角色/roles、清理历史/历史、暂停/pause、继续/resume、天气、点歌、点歌模式、epic、吃什么/菜谱、历史上的今天、好感度、订阅、日志、偷表情、表情库统计、维基…）；内容=对应命令的输出；意义=顺口。
/bot 昵称 set <QQ号> <小名>：作用=记小名；参数=QQ 号（5-11 位数字）＋小名（1-32 字）；内容=确认；意义=好感度与称呼个性化（仅管理员）。
【权限与效果】
  权限=触发本身全员；各命令自身的权限照旧生效。
【示例】/岸宝帮助｜守岸人 天气 上海｜/岸宝点歌 晴天

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 昵称` 为准。

## 链接

- 权限：普通用户可用
- 触发别名：链接；links
- 能力入口：bot.content
- 自然语言触发：直接粘贴平台链接
- 群聊/私聊差异：群聊/私聊行为一致（解析按链接触发）
- 网络依赖：需要联网
- 可复制示例：直接粘贴 https://www.bilibili.com/video/BVxxxx
- 关联回归测试：tests/test_parser_v2_boundary.py
- 总览：【链接】自动解析：直接发平台链接即可
- 标题：【链接】平台链接自动解析信息卡

### 教程

【板块介绍】
  链接解析在路由优先级 46：只要文本含 http(s) 链接且未命中更高优先级
  命令（如 /bot download、订阅），就走解析器组出信息卡。
【指令与参数】
发链接（无命令词）：作用=解析；参数=URL（1 条或多条，取第一个）；内容=信息卡/摘要；意义=内容预览。
【权限与效果】
  权限=全员。相关平台需要登录态时用 /bot cookie import 补 cookie。
【示例】直接粘贴 https://www.bilibili.com/video/BVxxxx

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 链接` 为准。

## 草稿

- 权限：普通用户可用
- 触发别名：草稿；autosend；自动发送；报存；報存
- 能力入口：bot.auto_send
- 自然语言触发：报存；報存；报存 给 <收件人> 发邮件；報存 給 <收件人> 發郵件
- 群聊/私聊差异：群聊/私聊行为一致（仅预览不实发）
- 可复制示例：报存 给小明、小红 发邮件，主题：周末聚餐，内容：周六晚上六点老地方见
- 关联回归测试：tests/test_content_video_auto_send.py
- 总览：【草稿】自然语言起草自动发送：报存 给 <收件人> 发消息|邮件，内容…
- 标题：【草稿】自然语言起草自动发送

### 教程

【板块介绍】
  自动发送子系统的入口：解析成结构化意图（通道/收件人/主题/正文）并
  输出预览。当前版本只做预览（confirm_required），不真实发送。
【指令与参数】
报存 给 <收件人> 发消息|邮件 [，内容要求]：作用=起草；参数=收件人必填（多个用 、,， 分隔）；「主题：」段作为邮件主题；「内容」后的文本作为正文要求；内容=草稿预览卡；意义=规划待发内容。
【权限与效果】
  权限=全员（预览无副作用）。邮件通道风险级高于普通消息。
【示例】报存 给小明、小红 发邮件，主题：周末聚餐，内容：周六晚上六点老地方见

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 草稿` 为准。

## 吃什么

- 权限：普通用户可用
- 触发别名：吃什么；吃啥；菜谱；eat；food；recipe；chishenme；csm；caipu；cp；zenmezuo；zmz
- 能力入口：bot.eat
- 自然语言触发：吃什么；吃啥；菜谱 <菜名>；怎么做
- 群聊/私聊差异：群聊/私聊行为一致（会话仅用作去重缓存键）
- 可复制示例：吃什么｜吃什么 三选一｜菜谱 番茄炒蛋
- 关联回归测试：tests/test_eat_capability.py
- 总览：【吃什么】随机推荐家常菜/查菜谱：吃什么 | 吃什么 三选一 | 菜谱 番茄炒蛋
- 标题：【吃什么】解决选择困难

### 教程

【板块介绍】
  本地菜品库随机推荐＋AI 约束生成双层：命中修饰/约束词表走过滤或 AI，
  否则纯随机。推荐与菜谱渲染 Mica 卡图（含本地封面），失败回退文本。
【指令与参数】
吃什么 [修饰/约束]：作用=推荐；参数=修饰词（三选一/来三道/再来一道/再来/辣的/不辣/微辣/中辣/特辣）或约束描述（不吃/不要/忌口/过敏/有/加/N人/清淡/减脂…）；内容=菜品卡；意义=选菜。
菜谱 <菜名>（别名 怎么做/如何做）：作用=查做法；参数=菜名必填；内容=食材与步骤；意义=烹饪指引。
【权限与效果】
  权限=全员。普通闲聊（吃了吗/吃火锅）不会被误判成点菜。
【示例】吃什么｜吃什么 三选一｜吃什么 不辣 有鸡蛋｜菜谱 番茄炒蛋

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 吃什么` 为准。

## 好感度

- 权限：普通用户可用
- 触发别名：好感度；好感查看；查询好感；查詢好感；親密度；affinity；haogandu；hgd；haoganchakan；hgck；chaxunhaogan；cxhg
- 能力入口：bot.affinity
- 自然语言触发：好感度；查询好感；查詢好感；亲密度；親密度；affinity
- 群聊/私聊差异：私聊=双向好感卡；群聊=本群好感榜（自己高亮，展示前 12/上限 60）
- 可复制示例：好感度｜好感度 我｜好感度 算法
- 关联回归测试：tests/test_affinity.py；tests/test_affinity_query.py；tests/test_affinity_numerical.py
- 总览：【好感度】双向好感与算法：好感度｜好感度 我｜好感度 算法
- 标题：【好感度】守岸人与你的双向好感

### 教程

【板块介绍】
  双向好感体系：守岸人对你=印象好感度（-100~+100）；你对守岸人=你
  表达中友好成分的加权占比（估算）。好感档位只影响语气与距离感，
  不改变安全边界。
【指令与参数】
好感度：作用=查好感；参数=无；内容=双向卡或群榜；意义=关系可视化。
好感度 我|自己|me：作用=只看自己；参数=任选其一；内容=双向分值；意义=隐私。
好感度 算法|说明|规则|help：作用=算法说明；参数=任选其一；内容=规则＋档位态度对照＋你与守岸人之间的氛围画像（定性描述，不展示具体加减数值）；意义=透明。
【权限与效果】
  权限=全员。好感度功能总开关 bot_affinity_enabled。
【示例】好感度｜好感度 我｜好感度 算法

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 好感度` 为准。

## Epic

- 权限：普通用户可用
- 触发别名：epic；epic free；epic 免费；免费游戏；免費遊戲；遊戲免費；steam免費；游戏免费；steam免费；steam 免费
- 能力入口：bot.epic
- 自然语言触发：epic；免费游戏；免費遊戲
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：卡片图＋文本（mixed）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：单源挂文本尾注；双源全挂回文本「拉取失败，稍后再试」
- 可复制示例：epic
- 总览：【Epic】每周免费游戏：epic 或 Epic 免费
- 标题：【Epic】查询每周免费游戏

### 教程

【板块介绍】
  聚合 Epic 公开接口与 Steam 限免，渲染可用时输出 Mica 信息卡，
  文本作兜底。
【指令与参数】
epic（别名 epicfree/epic free/epic 免费/免费游戏/游戏免费/steam免费/steam free/steamfree）：作用=查询；参数=无；内容=本周免费游戏清单；意义=情报。
【权限与效果】
  权限=全员。
【示例】epic

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help Epic` 为准。

## 随机图

- 权限：普通用户可用
- 触发别名：随机图；来张图；隨機圖；來張圖；randpic；suijitu；sjt；laizhangtu；lzt
- 能力入口：bot.randpic
- 自然语言触发：随机图；来张图；隨機圖；來張圖
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：纯本地
- 输出形式：图片
- 配置变量：BOT_RANDPIC_DIRS；BOT_RANDPIC_TRIGGER_WORDS
- 可复制示例：随机图｜来张图
- 关联回归测试：tests/test_randpic_identity.py
- 总览：【随机图】从图库随机发一张：随机图 / 来张图
- 标题：【随机图】图库随机发图

### 教程

【板块介绍】
  借鉴 nonebot-plugin-randpic 的“指令→随机图”玩法但只吸收思路：
  不建目录、不建数据库、不做上传，一把随机梭哈。目录清单 30 秒 TTL
  缓存，改文件夹半分钟内生效。
【指令与参数】
随机图|来张图：作用=发图；参数=无（触发词后跟标点/语气词也可命中；「随机图片库」这类包含关系词不误触发）；内容=图片或图库为空的配置提示；意义=娱乐。
【取值范围】
  BOT_RANDPIC_DIRS：文件夹路径列表；扩展名 jpg/jpeg/png/gif/webp/bmp；
  单文件 ≤20MB；目录不存在/为空时给友好提示不报错。
【权限与效果】
  权限=全员（bot_randpic_enabled 可关）。
【示例】随机图｜来张图

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 随机图` 为准。

## 提醒

- 权限：普通用户可用
- 触发别名：提醒；reminder；叫我；记得叫；記得叫；定时提醒；tixingliebiao；txlb；wodetixing；wdtx；kankantixing；kktx；younaxietixing；ynxt
- 能力入口：bot.reminder
- 自然语言触发：<时间>提醒我…；<时间>叫我…；记得叫；記得叫；提醒列表；取消提醒 <id>
- 群聊/私聊差异：投递目标：群聊=原群，私聊=本人（target_scope=会话类型）
- 可复制示例：12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2
- 关联回归测试：tests/test_reminder.py
- 总览：【提醒】到点督促：12点提醒我写作业｜提醒列表｜取消提醒 <id前几位>
- 标题：【提醒】时间点记忆与主动督促

### 教程

【板块介绍】
  时间点记忆：把“几点做什么”存库，每分钟调度任务到点以守岸人语气
  主动督促。触发方式是自然语言（含 提醒/叫我/记得叫 信号词且能解析出
  时间），或列表/取消查询。
【指令与参数】
<时间>提醒我 [事项]（别名 叫我）：作用=建提醒；参数=时间（自然语言：X点/X点半/X:MM/下午X点/N分钟后/半小时后/明天早上8点…）＋事项可选（≤120 字）；内容=记下确认；意义=核心玩法。
提醒列表|我的提醒|看看提醒|有哪些提醒：作用=列待办；参数=无；内容=清单；意义=盘点。
取消提醒 [id前缀]：作用=取消；参数=4-12 位十六进制前缀（唯一命中才取消；不带前缀会提示先看列表）；内容=取消确认；意义=反悔。
【权限与效果】
  权限=全员（bot_reminder_enabled 可关）。投递按会话作用域（群=群内，
  私聊=本人），发送走队列。
【示例】12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 提醒` 为准。

## 帮助

- 权限：普通用户可用
- 触发别名：帮助；help；菜单
- 能力入口：bot.help
- 群聊/私聊差异：普通用户只见公开模块；查管理员模块回「没有找到」
- 网络依赖：纯本地
- 输出形式：Mica 卡/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 可复制示例：/bot help｜/bot help 点歌｜/bot help help
- 关联回归测试：tests/test_bot_commands_catalog_b10.py；tests/test_help_entries_coverage.py；tests/test_documentation_consistency.py
- 总览：【帮助】查看功能总览与模块教程：/bot help｜/bot help <模块>
- 标题：【帮助】功能总览与模块教程

### 教程

【板块介绍】
  帮助系统自己也是一条命令：总览管「有什么」，深度页管「怎么用」，
  机器可读目录 /bot commands 管「程序对账」。三者和 docs/command-catalog.md
  共享同一份注册数据，改一处全端生效。
【指令与参数】
/bot help：作用=总览；参数=无；内容=分类清单；意义=发现功能。
/bot help <模块>：作用=深度页；参数=模块名/别名；内容=逐参数说明；意义=自助排障。
/bot commands：作用=机器可读目录；参数=无；内容=路由表＋命令清单；意义=脚本对账。
【权限与效果】
  权限=全员；可见范围按角色切换（非管理员查管理员模块会得到「没有找到」）。
【示例】/bot help｜/bot help 点歌｜/bot help help

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 帮助` 为准。

## 聊天

- 权限：普通用户可用
- 触发别名：聊天；chat；闲聊
- 能力入口：bot.chat
- 群聊/私聊差异：群聊=@点名/昵称点名/接话抽签（好感门）；私聊=白名单直说
- 网络依赖：需要联网
- 输出形式：文本
- 失败兜底：私聊回守岸人话术提示，群聊保持静默不刷屏
- 总览：【聊天】和守岸人自然对话：群里 @点名，私聊直接说
- 标题：【聊天】人格对话（不可显式调用，靠触发）

### 教程

【板块介绍】
  聊天是兜底能力：没有任何「/bot chat」式命令，命中不了其他路由的
  文本最终落到这里。它承载人格档案、向量知识库、世界观与好感语气。
【指令与参数】
  无指令：作用=承接所有未命中路由的自然对话；参数=无；内容=人格化回复；意义=产品主体验。触发方式=@点名 / 昵称点名 / 私聊直说。
【权限与效果】
  权限=全员（受群聊门禁与好感门约束）。回复经统一审查与渲染管线。
【示例】（群里 @守岸人）今天状态怎么样？

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 聊天` 为准。

## 戳一戳

- 权限：普通用户可用
- 触发别名：戳一戳；poke
- 能力入口：on_notice:戳一戳
- 网络依赖：纯本地
- 输出形式：文本回应
- 配置变量：BOT_POKE_ENABLED；BOT_POKE_PROBABILITY
- 总览：【戳一戳】戳机器人有概率收到回应（有冷却）
- 标题：【戳一戳】戳一戳互动回应

### 教程

【板块介绍】
  戳一戳是轻量互动：群友戳机器人头像，机器人按概率回一句话。
  冷却与概率防止连戳刷屏。
【指令与参数】
  无指令：作用=头像互动回应；参数=无；内容=概率性一句回应；意义=轻互动。配置经 .env 或 /bot runtime set（可写键以 runtime 白名单为准）。
【权限与效果】
  权限=全员。开关关闭时戳一戳无任何回应。
【示例】戳一戳守岸人的头像 → 有概率收到回应

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 戳一戳` 为准。

## 表情收库

- 权限：普通用户可用
- 触发别名：表情收库；表情库；biaoqingku；bqk
- 能力入口：meme_absorb（群图自动收库，无命令）
- 网络依赖：需要联网
- 输出形式：无直接输出（图片异步入库）
- 总览：【表情收库】群聊图片自动入库，成为「偷表情」的弹药库
- 标题：【表情收库】表情包自动收集（监听生效，无命令）

### 教程

【板块介绍】
  表情收库是「偷表情」的后勤：群友发的图自动攒成表情库，机器人
  心情低时还会偏向发吵闹梗。工程上有冷却、群黑白名单与 LRU 上限。
【指令与参数】
  本模块无命令：作用=自动收库；参数=无；内容=群图异步入库（不直接回复）；意义=偷表情的弹药库。库存操作入口：偷表情｜表情库统计（见「偷表情」模块）。
【权限与效果】
  权限=全员（被动机制）。下载绝不阻塞消息主链路。
【示例】群里发一张表情图 → 自动入库 → 之后「偷表情」可能抽到它

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 表情收库` 为准。

## 自然语言

- 权限：普通用户可用
- 触发别名：自然语言；自然语言命令
- 能力入口：bot.natural_command
- 输出形式：归一化后转目标模块执行
- 总览：【自然语言】不用记命令，直接说话：帮我查杭州天气/来首晴天/今天有什么免费游戏
- 标题：【自然语言】一句话归一成命令

### 教程

【板块介绍】
  自然语言层（priority 45）把口语说法归一成标准命令再进对应模块，
  带城市黑名单与禁词保护，避免把「天气真好」当成天气查询。
【指令与参数】
  无固定指令：作用=把口语归一成标准命令；参数=自然语言本身；内容=命中后按目标模块回复；意义=零记忆成本。查询类动词：帮我/麻烦/请/查一下/看看/告诉我…
【权限与效果】
  权限=全员。命中后按目标模块的权限与门禁执行。
【示例】帮我查杭州天气｜来首晴天｜今天有什么免费游戏

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 自然语言` 为准。

## 忽略

- 权限：仅管理员
- 触发别名：忽略；ignore
- 能力入口：matcher:IGNORE（空消息兜底，不回复）
- 输出形式：无回复（按设计静默）
- 总览：【忽略】哪些消息会被静默不回（排障「为什么不回我」）
- 标题：【忽略】静默路由与沉默原因

### 教程

【板块介绍】
  「忽略」是路由兜底语义：机器人不回 ≠ 出故障，多数沉默是门禁与
  策略按设计工作。本模块帮助管理员区分「按设计沉默」与「真异常」。
【指令与参数】
  无专属命令：作用=解释沉默；参数=无；内容=不回复（按设计）；意义=区分按设计沉默与真异常。相关诊断：/bot status、/bot why、/bot route <文本>（route 会直接告诉你这段文本命中哪条路由）。
【权限与效果】
  权限=仅管理员（排障语义）。
【示例】/bot route 今天天气不错 → 显示 chat 路由（正常回复场景）

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 忽略` 为准。

## 路由覆盖与内部接口

### 路由规则 → 帮助模块

- 路由 kind | 能力 id | 归属：

  - subscribe | bot.subscribe | 订阅
  - alias | bot.alias | 昵称
  - admin | bot.status | 状态
  - auto_send | bot.auto_send | 草稿
  - meme | bot.meme | 表情
  - meme_library | bot.meme_library | 偷表情
  - music_mode | bot.music_mode | 点歌
  - music | bot.music | 点歌
  - today_history | bot.today_history | 历史上的今天
  - wiki | bot.wiki | 维基
  - moegirl | bot.moegirl | 萌娘百科
  - epic | bot.epic | Epic
  - weather | bot.weather | 天气
  - market | bot.market | 行情
  - fx | bot.fx | 汇率
  - stocks | bot.stocks | 个股行情
  - eat | bot.eat | 吃什么
  - divination | bot.divination | 占卜
  - news | bot.news | 快报
  - randpic | bot.randpic | 随机图
  - reminder | bot.reminder | 提醒
  - affinity | bot.affinity | 好感度
  - moegirl_question | bot.moegirl | 萌娘百科
  - natural_command | bot.natural_command | 自然语言
  - content | bot.content | 链接
  - chat | bot.chat | 聊天

### 接口清单（manifest）

- interface_id | 状态 | 归属/说明：

  - transport.onebot | active | 内部：传输层，无用户命令
  - core.gscore | active | 内部：桥接层，接收游戏侧消息，无用户命令
  - parser.content | active | 链接
  - persona.chat | active | 聊天
  - capability.weather | active | 天气
  - capability.music | active | 点歌
  - capability.wiki | active | 维基
  - capability.moegirl | active | 萌娘百科
  - capability.epic | active | Epic
  - capability.today_history | active | 历史上的今天
  - capability.subscribe | active | 订阅
  - capability.meme | active | 表情
  - capability.auto_send | active | 草稿
  - capability.game_live | reserved | 预留：游戏直播事件接入，尚未实现
  - capability.meme_absorb | active | 表情收库
  - capability.emotion | active | 内部：心情引擎，经上下文注入，不占文本路由
  - capability.gscore | reserved | 预留：GsCore 侧指令统一进入基层路由，尚未实现

### 内部路由能力（无独立帮助模块）

- `bot.stocks`：个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）
- `bot.fx`：汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）
