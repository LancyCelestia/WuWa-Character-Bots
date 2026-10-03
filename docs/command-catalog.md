# 守岸人命令与教程目录

> 本文件由 `scripts/command_catalog.py` 从 `domains/chat_reply/capabilities/echo.py` 的帮助注册表与
> `runtime/base_router.py` 的路由/接口清单自动生成。不要手工修改；
> 修改帮助页数据后运行 `python scripts/command_catalog.py --write`。
> `/bot help`、`/bot help <模块>` 与本目录共享同一数据源。

- 模块数：83
- 别名数：575
- 普通用户可用模块：39；仅管理员模块：44
- 路由规则数：36；其中登记为内部能力：5

## 使用入口

- `/bot help`：查看当前用户有权限看到的模块总览。
- `/bot help <模块>`：查看一个模块的参数、效果、权限和示例。
- `/bot commands`：输出机器可读命令目录。
- `守岸人 <命令>`、`岸宝 <命令>`：在昵称触发已配置时等价于对应自然语言入口。

## 新用户教程

### 这个机器人能做什么

- 全部 83 个模块都列在本文件「模块详情」里；普通用户可直接使用其中 39 个公开模块，其余 44 个为管理员诊断与配置模块。
- 能力横跨人格闲聊、链接解析、点歌、天气、行情、占卜、提醒、订阅推送、表情包、下载与一整套管理员运维命令；全部 83 个模块逐个列在下方「模块详情」，公开模块名单以 /bot help 为准。

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

- 仅管理员模块共 44 个，全部走 `/bot` 前缀（例如 `/bot status`、`/bot runtime`、`/bot model`），普通成员发送会收到拒绝提示；权限由六级角色体系（user/trusted/enterprise/admin/super_admin/blocked）判定。
- 排障第一入口是 `/bot status`，追问原因用 `/bot why`。

### 群聊和私聊有什么差别

- 群聊有门禁（黑白名单、安静时间、限流句数帽、好感门）；私聊在白名单内直接对话。
- 标注「群聊/私聊差异」的模块在详情里有具体行为（例如记忆：私聊=全部个人记忆，群聊=仅公开/群组两级）。
- 大模型调用失败时：私聊会收到守岸人话术的失败提示，群聊保持静默不刷屏。

### 哪些功能会发图片？失败怎么办？

- 帮助页、行情、点歌候选等场景会渲染「釉瑚云母」卡片图；渲染失败会自动回退纯文本，功能不中断。
- 当前列为图片输出的模块：接入、用量、点歌、行情、个股行情、商品行情、国债收益率、北向资金、汇率、Epic、帮助。
- 下载/文件类模块输出文件段；所有命令失败时都会给出可读原因，不抛堆栈。

### 哪些功能依赖网络？

- 需要联网的模块：上下文、对话、模型、搜索、凭据、文件、群摘要、视频理解、邮件、Telegram、订阅、点歌、搜图、天气、行情、个股行情、商品行情、国债收益率、北向资金、汇率、快报、维基、萌娘百科、历史上的今天、下载、链接、媒体归档、群信息、Epic、聊天、表情收库、紧急信息。
- 纯本地模块：功能管理、记忆、接入、配置、就绪、角色、人格、路由、历史、暂停、回复、用量、解析、群文件、日志、身份、怪癖、合并转发、运行开关、供应商、表情、占卜、宿主机状态、书面同意、随机图、笔记、日程、收件箱、语音、帮助、戳一戳、表情册、决策、亲密模式。
- 联网模块自带重试与兜底（各模块的「失败兜底」行写明具体行为）；外部源不可用时给可读失败原因。

### 高频入口速查

- `/bot help` / `/bot help <模块>`：帮助总览 / 单模块教程。
- `/bot commands`：机器可读命令目录。
- `/bot runtime get|set|reset`：参数查询 / 热改 / 回滚。
- `/bot identity set <昵称>`：设定本会话称呼（管理员）。
- 昵称触发：`守岸人 天气 上海`、`/岸宝点歌 晴天`（昵称清单可用 `/bot runtime nickname list` 查看）。

## 模块详情

## 功能管理

- 权限：仅管理员
- 触发别名：功能管理；feature
- 能力入口：bot.runtime（/bot feature）
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_CONTROL_PLANE_FEATURES_DB
- 可复制示例：/bot feature get bot.plugin.weather
- 关联回归测试：tests/test_runtime_feature_gate.py
- 总览：【功能管理】查询和控制能力树：/bot feature
- 标题：【功能管理】能力树状态与版本

### 教程

【指令与参数】
/bot feature list：作用=列出能力节点；参数=无；内容=稳定ID和有效状态；意义=定位待管理功能。
/bot feature get <ID>：作用=查询状态；参数=稳定ID；内容=有效状态、版本和图修订；意义=确认父级与依赖影响。
/bot feature enable|disable|reset <ID>：作用=启用、禁用或恢复默认；参数=稳定ID；内容=新版本和审计ID；意义=受控调整功能，修改仅限超管，已运行任务不强杀。
/bot feature preview <ID> on|off|reset：作用=预览变更；参数=稳定ID与目标状态；内容=影响节点；意义=写入前核对，不修改数据。
【权限与效果】
权限=仅管理员（含超管）；管理员只读，修改仅限超管，预览仅限超管；受保护核心能力不可关闭。命令与控制面共用服务。当前仅覆盖已登记并接入主Pipeline的能力，入站媒体和直接平台副作用仍在迁移。

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 功能管理` 为准。

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
/bot status：作用=查看运行状态摘要；参数=无；内容=软暂停状态/原因、角色计数、人格与知识文件缺失数、记忆/历史/诊断/审计/回执/队列的开关与存储（sqlite/memory）、限速与安静时间、LLM provider/model/key 状态与就绪下一步；超管另附宿主机快照行（处理器/显卡/内存/磁盘/占用/版本）与状态卡图片；意义=排障第一入口，出问题先看状态再 /bot why。
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
/bot memory add <内容>：作用=记住一句话；参数=内容（必填，建议 ≤1200 字），或加 --sensitivity=（可选，personal|group|public|credentialed，默认 personal）；内容=回显已记住的正文与 fact_id、sensitivity；意义=让机器人长期记住你的偏好与事实。
/bot memory list：作用=列出我的记忆；参数=无；内容=fact_id＋sensitivity＋正文的清单（私聊=全部个人记忆，群聊=仅 public/group 两级）；意义=核对机器人到底记住了什么。
/bot memory delete <fact_id>：作用=删除一条记忆；参数=fact_id（必填，来自 add/list 输出）；内容=成功回显已删除，找不到会明说；意义=撤回不想被记住的内容。
权限=全员（只增删查“你本人”的记忆，别人的看不到也删不掉）。
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
/bot why [id]：作用=解释一次回复的路由/策略/错误；参数=id（可选，request_id 或 debug_id，可从 /bot recent 或回执/审计输出里取；省略=最近一次）；内容=该请求的路由判定、策略命中、失败类型与线索；意义=回答“它刚才为什么这么回/为什么没回”。
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
/bot receipt <id>：作用=查询一条消息的发送回执；参数=id（必填，request_id 或 debug_id，可从 /bot recent 的输出里取）；内容=该消息的投递状态（待发/已发/失败）与关键时间点；意义=区分“没生成”和“生成了但没发出去”，确认“我发的命令到底发出去没有”。
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
/bot audit <request_id>：作用=查询一次请求的审计事件；参数=request_id（必填，请求编号）；内容=该请求全链路的审计事件列表（脱敏）；意义=合规排查与事后追因。
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
/bot recent [数量]：作用=汇总最近诊断＋回执＋审计；参数=数量（可选，1-20 整数，默认 5）；内容=三个板块的最近记录摘要；意义=不用分别调三个查询，一屏看完最近发生了什么。
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
/bot queue：作用=查看发送队列健康；参数=无；内容=待发/处理中/重试/失败计数与队列参数；意义=消息发不出去时判断是队列堆积还是投递失败。
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
/bot context [文本]：作用=看一段话会被注入什么上下文；参数=文本（可选，省略用「你好，守岸人。」）；内容=人格/知识/记忆/最近对话的注入摘要与预算（只出数字摘要不泄露原文）；意义=验证人格与知识装配是否生效，不动线上状态。
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
/bot dialogue [文本]：作用=完整跑一轮对话链路验收；参数=文本（可选，省略用「你好，守岸人。」）；内容=对话各阶段结果（配置/上下文/LLM 调用/回复）；意义=端到端验证聊天链路，不影响线上会话状态。
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
/bot setup llm：作用=看接真实 LLM 还缺哪些配置；参数=无；内容=七个必配键（provider/model/key/base_url/temperature/max_tokens/timeout）的当前值、合法取值与标红缺口，附下一步指引；意义=接入向导，照着补 .env 就能通。
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
/bot config：作用=配置体检；参数=无；内容=配置冒烟结果（缺什么、什么不合法，全部脱敏）；意义=改完配置后的快速自检。
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
/bot readiness：作用=聚合各链路就绪度；参数=无；内容=环境/配置/上下文/对话链路的就绪判定与软暂停状态；意义=开机后一眼判断能不能正常接客。
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
/bot roles：作用=看权限角色分布；参数=无；内容=admin/enterprise/trusted/blocked 的数量摘要（不含具体 ID）；意义=核对 BOT_ADMIN_USER_IDS 等名单是否被正确加载。
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
/bot persona：作用=人格材料自检；参数=无；内容=人格强度/语气规则/边界的自检结果；意义=确认人格档案完整、语气与边界规则生效。
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
  好感度/占卜/快报/随机图/提醒(41)→自然语言命令(45)→二次元问句(46)→链接解析(46)→聊天(50)。
  数字越小越先命中。
【指令与参数】
/bot route <文本>：作用=判定一段文本会命中哪条路由；参数=文本（必填，任意文本，省略回用法）；内容=路由类型/能力/优先级/理由，自然语言意图还会给出归一化后的命令；意义=搞清“这句话为什么被当成点歌/天气/闲聊”。
/bot routes：作用=查看全部路由注册表；参数=无；内容=按优先级排序的全部路由规则（kind/能力/说明）；意义=了解路由优先级全貌。
权限=全员（只读诊断，不执行命令本身）。
示例：/bot route 帮我解析这个 https://www.bilibili.com/video/BVxxxx
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
/bot history clear：作用=清空本会话最近对话；参数=无；内容=清理的轮次数（cleared_turns）；意义=对话被带偏后一键重置上下文；只清“当前会话×当前发送者×当前实例”，不动长期记忆。
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
/bot pause：作用=软暂停回复；参数=无；内容=暂停后的运行时状态与原因；意义=维护/救火时让机器人闭嘴，不改任何配置。
/bot resume：作用=恢复回复；参数=无；内容=恢复后的运行时状态；意义=解除软暂停。
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
- 配置变量：BOT_REPLY_DETAIL；BOT_CHAT_MAX_TOKENS；BOT_CHAT_FAST_MODE；BOT_REPLY_POLICY_ENABLED；BOT_REPLY_POLICY_DB_PATH
- 可复制示例：/bot reply 详细；/bot reply set 1000000001 适中 说人话
- 关联回归测试：tests/test_reply_policy_permanent.py；tests/test_reply_policy_preset_command.py；tests/test_reply_length_tier.py
- 总览：【回复】回复详略：/bot reply <详细|精简|默认>｜按人 /bot reply set|show|clear
- 标题：【回复】调整回复详略档位

### 教程

【板块介绍】
  回复详略影响聊天链路的输出风格：详细=先结论再展开身份/关系/关键经历
  与资料缺口（不凑字数）；精简=短句直给；默认=按问题复杂度自动取舍。
【指令与参数】
/bot reply：作用=查看当前详略档位；参数=无；内容=当前 BOT_REPLY_DETAIL 值与用法提示；意义=确认现状再决定改不改。
/bot reply <模式>：作用=设置详略档位；参数=模式（必填，详细|精简|默认；别名 科普/详尽=详细，简洁=精简，自动=默认；未知值会回用法不再静默当默认）；内容=已设为 detail/concise/auto；意义=控制回答是展开讲还是短平快，持久保存。
/bot reply set <QQ号> <默认|简洁|适中|讲全|详尽> [文学化|说人话] [讲具体|铺意象|换意象]：作用=替某个号钉**永久**回复策略；参数=目标 QQ 号（必填）＋ 长度档（必填其一）＋ 文风（可省，两枚互斥、后说顶掉先说）＋ 讲法（可省，多枚并存：讲具体／铺意象／换意象，换意象会按人轮换意象族）；内容=已为该号设定的长度与讲法；意义=策略按人存，跨群跨私聊、切换人格都跟着这个人走。
/bot reply show <QQ号>：作用=复查该号当前的策略与最近变更时间；参数=目标 QQ 号（必填）；内容=长度档、文风/讲法、来源（本人说的 explicit／模型推断 inferred）；意义=先看现状再决定改不改，不写任何东西。
/bot reply clear <QQ号>：作用=撤销该号的策略、回到全局档；参数=目标 QQ 号（必填）；内容=已撤销确认；意义=只删这一行，绝不批量清（别人的策略不受牵连）。
/bot reply 详细：先说明结论、身份、关系、关键经历和资料缺口，不强制凑字数。
/bot runtime set BOT_CHAT_MAX_TOKENS 8192：输出上限，不是必须生成的长度。
/bot runtime set BOT_CHAT_FAST_MODE false：知识验收阶段关闭快速模式。
BOT_CHAT_MAX_TOKENS=65538 是最大上限，不是每次强制生成 64K。
文件生成：明确说“生成/保存/导出文件”，机器人会先写文件，再走上传接口。
戳一戳：默认响应有冷却；BOT_POKE_ENABLED、BOT_POKE_*_COOLDOWN_SECONDS、BOT_POKE_PROBABILITY 可调。
/bot runtime set BOT_CHAT_FAST_MAX_TOKENS 8192：重新启用快速模式时的输出上限。
运行时覆盖优先于 .env；用 runtime get 查看实际设置。
【取值范围】
  仅接受上表模式词；其他输入会得到用法提示（不会被静默当成默认）。
【权限与效果】
  权限=仅管理员。写入运行时覆盖，持久保存，立即生效。
  相关键：BOT_CHAT_MAX_TOKENS（输出上限）、BOT_CHAT_FAST_MODE（快速模式）。
【按人永久策略（与上面的全局档分开）】
  set/show/clear 三个子命令动的是 user_reply_policy 里那一个人的
  一行（库＝BOT_REPLY_POLICY_DB_PATH），不是全局档：跨群跨私聊同一个键，
  切换人格也照样跟着这个人走。长度值与全局档共用 chat 的同一张分档表，
  所以不会长出第二把长度尺；文风两枚（文学化／说人话）互斥，只改怎么讲，
  不授予任何描写维度——动作与神态能不能写仍由内容政策与场景档决定。
  被设目标是超管时，只有超管能改（普通管理员不许横跨提权面）。
  本人在聊天里说一句「以后回我短一点／详细点／文学一点」会自动落同一行，
  反悔说一句即可覆盖；全局档则用 /bot runtime set BOT_REPLY_DETAIL=…。
【示例】/bot reply 详细｜/bot reply 精简｜/bot reply 默认
  按人：/bot reply set 1000000001 适中 说人话｜/bot reply show 1000000001｜/bot reply clear 1000000001

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
/bot llm：作用=诊断当前 provider/model/key 并做一次短调用；参数=无；内容=诊断报告（会产生一次真实调用的费用）；意义=验证当前渠道真能通。
/bot model list：作用=查看全部模型与顺序；参数=无；内容=各模型思考强度档位、故障转移顺序（priority 越小越先）、当前时段分组、渠道健康标注与价格；意义=选型与排障的底表。
/bot model health：作用=渠道健康报告；参数=无；内容=正常/连续失败踢出/慢渠道三类清单（慢渠道按平滑延迟 EWMA 判定，踢出渠道 30 分钟半开重探自动回队）；意义=回答“为什么没用 A 渠道”。
/bot model probe：作用=手动全渠道巡检；参数=无；内容=巡检受理提示（结果用 health 看）；意义=不等到后台周期主动体检，与后台巡检互斥。
/bot model routes <模型名>：作用=按实测速度列渠道；参数=模型名（必填）；内容=快→慢的渠道排序（未实测排后）；意义=选最快渠道做手动 set。
/bot model set <id|auto>：作用=切换当前模型；参数=id 或 auto（必填；id=已注册模型名/预设名/完整模型名，auto=回到自动选型）；内容=已手动指定 X 或已切自动；意义=手动钉死模型，失败仍自动转移。
/bot model add <id> model=<模型名> base_url=<接口地址> key=<密钥> [tags=档位] [effort=档位] [group=<分组>] [priority=<n>]：作用=新增供应商；参数=id（必填，自定义名，之后 set/update/remove 用它）＋model（必填，供应商模型名原样填）＋base_url（必填，OpenAI 兼容接口，一般 /v1 结尾）＋key（必填，sk-xxx 或 env:变量名）＋其余可选（tags 逗号分隔档位、group 令牌分组、priority 整数越小越先，缺省 100）；内容=注册即生效并进路由；意义=零重启接入新渠道。
/bot model update <id> <键=值...>：作用=改任意参数；参数=id（必填）＋要改的键=值（model/base_url/key/group/tags/effort/priority 任选）；内容=更新后的注册表；意义=换 key/调档位不用删了重建，可覆盖 .env 同名条目。
/bot model priority <id> <n>：作用=只改故障转移顺序；参数=id（必填）＋n（必填，整数，越小越先，1..N 唯一槽位其余自动顺移）；内容=新顺序；意义=峰谷调序。
/bot model effort <id> <档位>：作用=单模型思考强度覆盖；参数=id＋档位（必填，off|low|medium|high|xhigh|max|default，default=清除覆盖）；内容=确认信息；意义=给某个模型单独钉思考档。
/bot model think <档位>：作用=全局思考强度；参数=档位（必填，off|low|medium|high|xhigh|max|留空；留空=清空回家族基线）；内容=确认信息；意义=一刀切控制 reasoning_effort 开销（复杂任务仍会在家族最高档内临时升档）。
/bot model price <模型名> [input=<元/1M> output=<元/1M> cache_read=<元/1M> cache_creation=<元/1M> per_call=<元/请求>]：作用=维护价格表；参数=模型名（必填）＋价键（不带即清除该模型价格，数字≥0；cache_read/cache_creation=缓存读/缓存创建单价，per_call=按次计费渠道的元/请求）；内容=新价格确认；意义=账单计费依据，按调用时刻价格记账。
/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，today/今天 或 YYYY-MM-DD，省略=今天）；内容=输入/输出/缓存命中（含占输入比例）/缓存创建 Token、调用次数、按模型分组（含逐模型缓存读与缓存建）的费用；意义=看清钱花在哪、缓存有没有起作用。
/bot model search <on|off>：作用=热切换联网搜索；参数=on|off（必填）；内容=开/关确认；意义=不用重启控制 web_search。
/bot model vision list|add|update|priority|remove：作用=图片识别模型（VLM）注册表管理；参数=子命令＋各自参数（add 同 /bot model add：id/model/base_url/key/[priority]；update/remove 用同一 id；priority <id> <槽位> 调识别顺序）；内容=识别候选清单、优先级与开关状态，或写回确认；意义=给「图转文字」这条支路选型与排序，多候选按优先级轮询、单路失败自动降级到下一路。
/bot model vision mode <relay|direct>：作用=切换图片进入对话的方式；参数=relay|direct（省略=只查询当前模式；relay=先由识别模型把图转成文字描述，再作为不可信上下文并给主模型；direct=图片直传给支持视觉的主模型、不再过识别模型）；内容=当前视觉模式；意义=主模型不带视觉（或想省一跳）时走 relay，能直传时细节不丢。
/bot model remove <id>：作用=删除自定义模型；参数=id（必填；.env 来源条目不可删只能 update 覆盖）；内容=删除确认；意义=清理废弃渠道。
/bot model reset：作用=清除手动指定；参数=无；内容=回到自动选型确认；意义=撤销 set。
思考强度档位：DeepSeek/GLM/Kimi/MiniMax=low,high,max｜GPT/Grok=low,medium,high,xhigh｜Gemini=low,medium,high；默认=家族基线档，复杂任务自动升家族最高档。
示例：/bot model add myapi model=deepseek-v4-pro base_url=https://api.xxx.com/v1 key=sk-xxx tags=low,high,max priority=1
注意：key 不回显；等号两边不要加空格；新增/修改/价格/分组全部热更立即生效，重启保留。
priority 是 1..N 唯一槽位：移动一个模型，其他模型自动顺移；0 兼容为移到首位。
手动指定 > 时段组 order > 基础 priority。时段组启用时基础排序不覆盖组内顺序。
model list 显示候选配置，不等于上一条实际回答的供应商；/bot llm 会产生新的诊断调用。
不要在群聊发送真实 Key；使用 key=env:变量名，在本地安全配置凭据。
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
/bot model usage [today|YYYY-MM-DD]：作用=每日用量账单；参数=日期（可选，省略=今天）；内容=输入/缓存命中（含占输入比例）/缓存创建/输出 Token、调用次数、按模型分组费用与逐模型缓存读建、未计价次数；意义=每天钱花在哪、缓存有没有起作用一目了然。
/bot model price <模型名> [input=<元/1M> output=<元/1M> cache_read=<元/1M> cache_creation=<元/1M> per_call=<元/请求>]：作用=维护价格表；参数=模型名（必填）＋价键（数字≥0；不带价格=清除；cache_read/cache_creation=缓存单价，per_call=按次计费）；内容=确认信息；意义=账单计费依据。
实时提醒：单模型当日输出>500万或输入>5000万 token、当日账单>10元 → 自动推送管理员（阈值可在 .env 调）。
定时报告：北京时间 13:00/18:00/23:00 推送自上个报告点至今的金额与 Token；13:00 附过去 24 小时总花费。
口径：费用按每次调用时刻的价格记账，调价不影响历史账单；未配价格的模型不计费并在账单标注。
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
/bot runtime set <KEY> <VALUE>：作用=热改一个参数；参数=KEY（必填，可写键见 get 列表）＋VALUE（必填，按键校验），或加 --instance <名称>（可选，定位实例）；内容=已设置 KEY = 值（已持久化）；意义=不改 .env 立即生效，重启保留。
/bot runtime get <KEY>：作用=读参数实际生效值；参数=KEY（必填）；内容=值＋（覆盖值）/（.env 默认值）来源标注；意义=确认运行时覆盖与 .env 谁在生效。
/bot runtime list：作用=列出全部覆盖项；参数=无；内容=KEY=VALUE 清单；意义=盘点改过哪些。
/bot runtime reset [KEY]：作用=恢复默认；参数=KEY（可选，省略=清空全部覆盖）；内容=清除项数；意义=撤销热改。
/bot runtime persona <action>：作用=人格运行期管理；参数=action（list｜switch <id|default>｜probability <id> <0-1>）；内容=人格清单/切换确认/触发概率确认；意义=不重启换人格。
/bot runtime nickname add|remove|list [昵称]：作用=角色昵称管理；参数=action（必填）＋昵称（add/remove 必填）；内容=昵称表；意义=控制哪些称呼能触发昵称命令。
/bot runtime model <子命令>：作用=模型管理（=/bot model）；参数=见「模型」模块；内容=同 /bot model；意义=同义入口。
/bot runtime instance list：作用=列出实例设置；参数=无；内容=已有实例名单；意义=多实例部署核对。
/bot runtime get BOT_REPLY_DETAIL：查看实际详略模式及覆盖来源。
/bot runtime set BOT_MEMORY_EXTRACT_ENABLED false：暂停自动抽取，不删除已有记忆。
/bot runtime set BOT_MEMORY_EXTRACT_TIMEOUT_SECONDS 15：抽取总预算（秒）。
/bot runtime set BOT_MEMORY_EXTRACT_MAX_TOKENS 200：抽取输出上限（1..4096）。
/bot runtime set BOT_MEMORY_EXTRACT_ERROR_COOLDOWN_SECONDS 300：抽取失败后冷却。
记忆抽取复用聊天路由配置，采用独立调用状态；不使用另一枚基础 key 绕开模型注册表。
【常用可写键举例】
  BOT_MODEL_SCHEDULE（分时段切换，JSON）、BOT_MODEL_PRIORITY_GROUPS（峰谷分组，JSON 数组）、
  BOT_MODEL_PRICES（价格表 JSON）、BOT_CHAT_REASONING_EFFORT（off|low|medium|high|xhigh|max|留空）、
  BOT_REPLY_DETAIL、BOT_CHAT_MAX_TOKENS、BOT_CHAT_FAST_MODE、BOT_VISION_ENABLED、
  BOT_QUIET_HOURS_*（6 键）、BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 等（完整清单：/bot runtime get 随便发一个错键）。
【权限与效果】
  权限=仅管理员。写入即持久化并通知热更；个别装配期读取的键（如
  BOT_GROUP_CHAT_AUTO_REPLY_ENABLED）需重启，帮助各模块会单独标注。
【示例】/bot runtime set BOT_QUIET_HOURS_ENABLED true

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
/bot search <问题>：作用=验证联网检索链路；参数=问题（必填，省略回用法）；内容=至多 BOT_WEB_SEARCH_MAX_RESULTS 条检索结果（标题/摘要/链接，缺省上限 20）或失败原因；意义=区分“模型不知道”和“搜索没通”。
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
/bot parse [数量]：作用=查看最近链接解析历史；参数=数量（可选，1-100，默认 10）；内容=跨会话的 URL＋标题＋时间清单（全局范围）；意义=排查“刚才那条链接解析出了什么”。
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
/bot alert check：作用=凭据体检；参数=无；--probe（可选开关，追加在线探测，401/403=需重登）；内容=各凭据引用的状态清单；意义=解析突然 403 时的第一排查。
/bot cookie status：作用=看各平台已录 cookie；参数=无；内容=平台×cookie 名×到期日（永不回显值）；意义=核对导入是否生效。
/bot cookie import <平台> <Cookie头>：作用=热写入平台 cookie；参数=平台（必填，小写平台名，在收录名单内选 1，名单以 /bot cookie status 输出为准）＋Cookie头（必填，浏览器复制的 名=值; … 整行原文粘贴）；内容=accepted/normalized/skipped 三项统计与导入结果；意义=同名不覆盖、下一次解析即生效无需重启。
/bot cookie login <平台>：作用=扫码登录；参数=平台（必填，当前仅 bilibili 支持扫码）；内容=二维码图＋登录指引；意义=免手动导 cookie。
/bot cookie check <平台>：作用=查扫码结果；参数=平台（必填）；内容=最近一次扫码登录状态；意义=扫码后确认。
/bot cookie expiry：作用=全平台过期报告；参数=无；内容=各平台凭证有效期报告；意义=批量核对到期情况。
平台（18）：bilibili/xiaohongshu/douyin/qqmusic/netease/kuwo/kugou/twitter/youtube/kurobbs/weibo/kuaishou/acfun/moegirl/xiaoheihe/skland/miyoushe/zhihu
权限=仅管理员；每天 10:00 自动巡检一次并向在线管理员推送过期预警。
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
/bot group [list]：作用=查看各档位群名单；参数=无或 list；内容=黑1/黑2/白1/白2 四档的群号清单；意义=盘点现状。
/bot group add <档位> <群号...>：作用=把群加入档位；参数=档位（必填，black1|black2|white1|white2，可用 黑1/黑2/白1/白2）＋群号（必填，数字，可多个）；内容=更新后的名单；意义=批量拉黑/拉白。
/bot group del <档位> <群号...>：作用=移出档位；参数=同 add；内容=更新后的名单；意义=解除。
/bot group set <档位> <群号...>：作用=覆盖档位名单；参数=同 add；内容=更新后的名单；意义=整表重置。
/bot group clear <档位>：作用=清空档位；参数=档位（必填）；内容=空名单确认；意义=一键清空。
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
/bot 群文件：作用=看本群文件上传统计；参数=无（仅群聊可用，统计当前群）；内容=最近上传清单＋扩展名分布（文档/压缩包/图片/视频/音频/其他）＋整理建议；意义=群盘整理前的摸底。
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
/bot logs [级别] [数量]：作用=查看运行时事件日志；参数=级别（可选，debug|info|warning|error，默认 info）＋数量（可选，1-200 整数，默认 50），两个参数按「先级别后数量」顺序写；内容=最近 N 条对应级别以上的日志；意义=看运行时到底发生了什么。
权限=仅管理员（别名「日志」经昵称命令层同样需要 /bot 形式执行）。
示例：/bot logs error 20
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
文件 <格式> <主题>：作用=围绕主题生成文档并以群文件形式上传；参数=格式（必填，md|markdown|docx|pptx|xlsx|pdf，大小写不敏感）＋主题（必填，非空文本，作为文档标题与大纲素材）；内容=已生成并上传 <格式>：文件名（KB）或失败原因；意义=长文/表格/幻灯一键落盘成文件，不刷屏。
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
- 总览：【身份】会话身份记忆：/bot identity show|set|tag|clear｜自助称谓偏好：set-name|set-gender|unset-name|unset-gender｜自助关系档：set-relation|unset-relation|show-relation
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
/bot identity show：作用=查看本会话身份；参数=无；内容=称呼/标签/设置人/更新时间（未设置会明说）；意义=核对当前会话的身份设定。
/bot identity set <昵称>：作用=设定本会话称呼；参数=昵称（必填，非空文本，如 set 岸宝）；内容=已设定称呼确认；意义=让机器人在这群/这个私聊里只这么叫你。
/bot identity tag <标签1,标签2>：作用=设定标签；参数=标签串（必填，逗号分隔，最多保留 8 个）；内容=已设定标签确认；意义=给语气调整提供更多线索。
/bot identity clear：作用=清除本会话身份；参数=无；内容=已清除/本就没有；意义=恢复默认。
权限=仅管理员；在哪个群/私聊执行就对哪个会话生效，各会话互不影响；只影响称呼与语气，人格不变（渲染层内建防 OOC 护栏）。
/bot identity set-name <称呼>：作用=设置机器人对你的称谓偏好；参数=称呼（必填，非空，≤32 字）；内容=已记下确认；意义=无需管理员，你自己决定机器人怎么叫你（群里按「这个群+你」生效，私聊按你生效）。
/bot identity set-gender <male|female|nonbinary|custom|unknown>：作用=登记你的性别自述；参数=五个值之一（大小写不敏感）；内容=已记下确认；意义=让语气分寸更合适；非法值不记录并列出可接受值。
/bot identity unset-name：作用=清除称谓偏好；参数=无；内容=已清除/本就没有；意义=恢复自动称呼。
/bot identity unset-gender：作用=清除性别自述；参数=无；内容=已清除/本就没有；意义=恢复 unknown。
自助子命令权限=所有用户（只能操作自己的偏好，无他人参数）；unset-name/unset-gender 为整条记录清除（称谓与性别自述一并移除），unset-relation 只清关系档那一列；称谓偏好与上方管理员会话身份是两套数据，自助偏好优先级更高；关系档的开关语义与词表口径见「亲密模式」模块（/bot help 亲密模式）。
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
/bot quirk list [pending|active|retired]：作用=列出怪癖；参数=状态过滤（可选，pending=待审|active=生效|retired=退役，省略=全部，最多 20 条）；内容=id 前 8 位＋状态＋文本＋来源＋范围（global=全员渲染，user:名字=仅该用户）；意义=先拿 id 再审核，范围标注是审核依据之一。
/bot quirk approve <id前缀>：作用=待审转生效；参数=id 前缀（必填，需唯一命中，0 条或多条都拒绝）；内容=已通过＋文本；意义=审核制放行，approve 前对回复零影响。
/bot quirk retire <id前缀>：作用=退役生效项；参数=id 前缀（必填，唯一命中）；内容=已退役＋文本；意义=不再渲染但保留记录。
/bot quirk add <习惯描述>：作用=管理员直添；参数=习惯描述（必填）；内容=已直接生效；意义=跳过审核立即影响 prompt。
审核制红线：自动来源（反思回路等 propose）只进待审（pending_review），绝不直接影响 prompt；BOT_QUIRKS_ENABLED=false 时整个演化区停用。
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
BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR：作用=每小时群聊句数帽；参数=≥0 整数（默认 0=该帽不生效）；内容=超帽后普通回复被静默拦截；意义=防刷屏。
BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE：作用=每分钟群聊句数帽；参数=≥0 整数（默认 0=该帽不生效）；内容=超帽即拦，管住脉冲连发；意义=小时帽的补充。
BOT_RATE_LIMIT_EMOTION_EXEMPT：作用=情绪豁免；参数=true/false（默认 true）；内容=安抚类回复不被句数帽拦截；意义=该安慰的时候不被限流卡住。
BOT_GROUP_CHAT_AUTO_REPLY_ENABLED：作用=自动接话总开关；参数=true/false（默认 false）；内容=开启后未点名群消息按概率抽签接话，点名/命令不受影响；意义=群活跃度调节。
BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY：作用=接话概率；参数=0..1（默认 0.004，与心情系数相乘后封顶 1.0）；内容=每次抽签现算，低落时少插话、兴奋时更活跃；意义=心情联动的活跃度旋钮。
BOT_QUIET_HOURS_*：作用=安静时间窗；参数=BOT_QUIET_HOURS_ENABLED（true/false）/BOT_QUIET_HOURS_START·END（HH:MM，支持跨零点，默认 00:00-06:00）/BOT_QUIET_HOURS_TIMEZONE（IANA 名）/BOT_QUIET_HOURS_SESSION_TYPES（group|private|email 逗号分隔，默认 group）/BOT_QUIET_HOURS_BYPASS_ROLES（默认 admin）；内容=窗口内只拦截未点名的普通聊天/解析；意义=定时闭嘴。
修改方式：以上全部支持 /bot runtime set 热改，立即生效（接话总开关 ENABLED 装配期读取，改后需重启）。
示例：/bot runtime set BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR 60
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
BOT_RENDER_FORWARD_MIN_NODES：作用=按条数触发合并；参数=≥0 整数，默认 4（0=不按条数只看字数）；内容=切分后达到该条数即合并成 QQ 合并转发；意义=超过 3 条就打包。
BOT_RENDER_FORWARD_MIN_CHARS：作用=按字数触发合并；参数=≥0 整数，默认 1500；内容=达到字数也触发；意义=长文兜底。
BOT_RENDER_FORWARD_MAX_NODES：作用=节点数上限；参数=≥0 整数，默认 0=不限制；内容=切分块数尽量压到该上限（硬长度边界优先）；意义=防刷屏。
BOT_RENDER_FORWARD_NODE_CHARS：作用=单节点目标字数；参数=≥200 整数，默认 900；内容=每个转发节点的目标字数；意义=控制单条体积。
四键（BOT_RENDER_FORWARD_MIN_NODES/MIN_CHARS/MAX_NODES/NODE_CHARS）是 .env+重启键：装配期烘进策略快照（settings.py:355-364 列在需重启名单），/bot runtime set 会拒绝并提示重启。
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
BOT_SHARED_GROUP_CONTEXT_ENABLED：作用=群摘要总开关；参数=true/false（默认 false）；内容=开启才把群内近期对话浓缩成摘要供人格参考，关闭则完全不生成；意义=群上下文感知的前提。
BOT_GROUP_DIGEST_LIST_MODE：作用=名单模式；参数=whitelist|blacklist|off|all（默认空=不过滤）；内容=whitelist 仅名单内群参与摘要/blacklist 排除名单内群；意义=控制哪些群参与。
BOT_GROUP_DIGEST_WHITELIST / BOT_GROUP_DIGEST_BLACKLIST：作用=摘要白/黑名单；参数=数字群号列表（逗号/分号/顿号/空白分隔或 JSON 数组，自动去重，非数字拒绝）；内容=名单生效，精确圈定参与群；意义=该收的收、该避的避。
BOT_GROUP_DIGEST_PUSH_ENABLED：作用=每日通讯总结推送开关；参数=true/false（.env 键，默认 true，不进 runtime set 白名单）；内容=开/关每日定时推送；意义=夜间日报总闸。
BOT_GROUP_DIGEST_PUSH_TIME：作用=推送时刻；参数=HH:MM（时 0-23 分 0-59，默认 21:30，非法值启动即报错）；内容=每天这个时刻把当日群摘要推给白名单群各一遍（list_mode 非 whitelist 时零推送，绝不猜群）；意义=错峰推送。
BOT_GROUP_DIGEST_MAX_TURNS：作用=摘要收录轮数上限；参数=正整数（默认 150）；内容=摘要最多回看最近 150 轮对话；意义=控制上下文窗口。
BOT_GROUP_DIGEST_MAX_CHARS：作用=摘要字数预算；参数=≥100 整数（默认 800）；内容=摘要文本按字数预算截取；意义=控制注入长度。
BOT_GROUP_DIGEST_LLM_ENABLED：作用=LLM 润色摘要；参数=true/false（默认 false）；内容=开启后用 LLM 把对话浓缩成更顺的摘要（结果缓存 1 小时）；意义=默认关闭零额外开销。
示例：/bot runtime set BOT_GROUP_DIGEST_LIST_MODE whitelist → /bot runtime set BOT_GROUP_DIGEST_WHITELIST 1108838060,1076073471
BOT_GROUP_DIGEST_WHITELIST/BLACKLIST：作用=名单；参数=群号列表（多分隔符/JSON，去重）；内容=名单；意义=白/黑名单内容。
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
BOT_VISION_ENABLED：作用=识图总闸；参数=true/false（默认 false）；内容=开启且注册表有可用模型才调用视觉模型；意义=群里发图能被看懂的前提。
BOT_VISION_MODE：作用=识别管线选择；参数=relay|direct（默认 direct）；内容=relay=视觉模型转文字，direct=图片直传主模型；意义=质量与成本取舍。
BOT_VISION_REPLY_PROBABILITY：作用=识图回应概率；参数=0..1（默认 1.0，0=仅 @ 时看图）；内容=识别触发频率；意义=控制打扰与开销。
BOT_VIDEO_UNDERSTANDING_ENABLED：作用=视频理解总闸；参数=true/false（默认 false）；内容=开启后视频抽帧＋音轨/字幕生成感知简报，支持追问与深挖，关闭走旧抽帧摘要零额外开销；意义=视频消息的深度理解。
识别模型管理：/bot model vision list|add|update|priority|remove（详见 /bot help 模型）。
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
BOT_SEND_QUEUE_ENABLED：作用=发送队列持久化；参数=true/false，默认 false；内容=队列落 sqlite 重启不丢；意义=可靠投递的基础。
BOT_SEND_QUEUE_WORKER_ENABLED：作用=队列后台投递线程；参数=true/false，默认 false；内容=后台按批投递待发消息；意义=不依赖事件触发投递。
BOT_AUDIT_ENABLED：作用=审计落库；参数=true/false，默认 false；内容=/bot audit 可跨重启查询；意义=合规。
BOT_RECEIPTS_ENABLED：作用=回执落库；参数=true/false，默认 false；内容=/bot receipt 跨重启可查；意义=投递追踪。
BOT_DIAGNOSTICS_ENABLED：作用=运行诊断落库；参数=true/false，默认 false；内容=/bot recent 汇总有料；意义=排障。
说明：5 键均为 .env 配置（不在 /bot runtime set 可写集合），改后重启生效。
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
/mail status：作用=看邮件桥接状态；参数=无；内容=桥接开关、已连接账户、当前发件账户；意义=邮件链路总览。
/mail accounts：作用=列可用账户；参数=无；内容=认证账户与发件别名；意义=选发件身份前先看有什么。
/mail use <发件邮箱>：作用=设默认发件身份；参数=发件邮箱（必填，完整地址且必须已连接或已映射）；内容=切换确认；意义=后续 send 不用每次 --from。
/mail send <收件邮箱> | <主题> | <正文>：作用=发信；参数=收件邮箱（必填，完整地址）＋主题（必填非空）＋正文（必填非空），用 | 分隔三段；内容=发送结果；意义=快速发邮件。
/mail send --from <发件邮箱> | <收件邮箱> | <主题> | <正文>：作用=临时指定发件身份发信；参数=四段（缺一不可）；内容=发送结果；意义=一次借用别的身份。
/mail pause：作用=暂停邮件 AI 自动回复；参数=无；内容=暂停确认（收件提醒继续）；意义=只收不回。
/mail resume：作用=恢复自动回复；参数=无；内容=恢复确认；意义=恢复。
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
/bot status、/bot pause|resume：作用=在 TG 侧查看/控制运行时；参数=无；内容=同 QQ 侧；意义=出门在外远程运维。
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
BOT_MODEL_REGISTRY：作用=.env 里登记 AI API 中转供应商；参数=JSON 对象，每项含 model/base_url/api_key/group/priority；内容=模型注册表底表；意义=静态渠道来源（运行时 add 的条目会与它合并）。
priority：作用=全局尝试顺序；参数=整数 1-999，越小越优先；内容=故障转移次序；意义=便宜稳定的放前面，HCN 保底项放最后。
BOT_CHAT_FAST_MAX_CANDIDATES：作用=快速模式候选上限；参数=0=不限制，1-100=最多尝试数量；内容=候选裁剪；意义=控制快速模式开销。
scripts/probe_llm_providers.py：作用=命令行脱敏探测全部渠道；参数=--max-tokens（可选，1-4096，默认 32）；内容=每模型一次探测结果，不删除配置；意义=批量验收供应商。
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
/订阅 add <公开目标>：作用=添加订阅并推送到当前会话；参数=公开目标（必填，主页链接或 类型:id 字符串，多余参数会被显式拒绝）；内容=订阅已添加：<id>；意义=新内容/开播自动播报；群内 add 需管理员；重加已存在的订阅只增目的地，不会改动暂停状态（管理员暂停的订阅不会被悄悄恢复）。
/订阅 list：作用=列出订阅；参数=无；内容=本会话目的地下的订阅（id｜平台｜名字｜启用/暂停）；意义=拿 id、看状态；群内仅管理员可看本群订阅。
/订阅 pause|resume <id>：作用=暂停/恢复订阅；参数=id（必填，来自 list）；内容=已暂停/已恢复（仅本目的地）；意义=临时静默不删订阅。
/订阅 remove <id>：作用=删除订阅；参数=id（必填）；内容=已删除（其他群的目的地不受牵连，最后一个目的地移除才整条删）；意义=退订。
权限=全员自助；群内 add/list 需管理员，pause/resume/remove 群内需管理员且订阅推往本群，私聊需推给自己。
目标示例：https://space.bilibili.com/123456｜bilibili:up:123456｜youtube:live:<频道ID或@handle>｜xiaohongshu:column:<用户ID>｜music.163.com/playlist?id=xxx
支持范围：B站（UP主/直播间/番剧/收藏夹/合集）、小红书（图文/专栏/直播）、YouTube（频道/播放列表/直播）、微博、推特、Pixiv、Telegram 频道、音乐平台（网易云/QQ/酷狗/酷我/Apple/Spotify 的歌手/专辑/歌单）；建议直接粘贴主页或链接。
/订阅 与 /bot subscribe 等价。
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
点歌 <歌名>：作用=按平台顺序搜索并发送；参数=歌名或关键词（必填，中英文均可；#歌名=强制按歌名搜索的转义写法）；内容=平台音乐卡片（无卡则封面图）等部件；意义=群内点播。
点歌 <编号>：作用=同名多候选时二次选择；参数=编号（必填，来自候选列表，默认最多 5 个）；内容=选中歌曲；意义=精确选版本；仅紧随候选列表、默认 300 秒内有效，过期会提示重新点歌。
点歌模式 <模式>：作用=设置输出方式；参数=模式（卡片|语音|音频|链接|全部，可组合如 卡片+语音，中英文别名均可）；内容=模式持久化确认；意义=控制输出形态；仅管理员，持久保存。
平台：网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 顺序尝试，单平台取第一名，失败自动换下一个。
示例：点歌 晴天｜候选出来后回复「点歌 2」｜点歌模式 卡片+语音
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
表情 <模板> <文字>：作用=套模板生成表情图；参数=模板名（必填）＋文字（按模板要求，多段用 ｜ 分隔）；内容=生成的表情图；意义=玩梗输出；需要图片的模板发图或 @ 群友后输命令，不带图用你的头像。
表情 列表：作用=列出全部模板；参数=无；内容=可用模板 key 清单；意义=先查再玩。
表情帮助：作用=用法说明；参数=无；内容=完整用法；意义=入门。
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
偷表情 [关键词]：作用=按权重随机发一张入库表情；参数=关键词/情绪标签（可选，命中描述/情绪/场景标签）；内容=表情图；意义=表情包补给；写「私聊/私聊我」等同不填关键词但改为私聊发送。
表情库统计：作用=看库存；参数=无；内容=数量与来源分布；意义=摸底。
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
搜图 ＋图片：作用=反搜图片来源；参数=图片（同一条消息带图或 @ 一张图；引用消息拿不到原图会明确提示）；内容=SauceNAO 匹配结果（相似度/来源链接）；意义=找画师/找出处。
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
天气 <城市>：作用=查天气；参数=城市名（必填，≤20 字且要像地名；同名城市用 省-市 区分，如 浙江-杭州）；内容=当前天气＋预报卡（中国气象局 NMC 免 key，Open-Meteo 兜底）；意义=出行参考。
支持区县 <省>：作用=列出可查区县；参数=省名（必填）；内容=该省区县码表清单；意义=查县级精细天气前的发现入口。
【权限与效果】
  权限=全员。自然语言「帮我查杭州天气」经意图归一化同样命中。
【示例】天气 上海｜天气 河北-大城｜支持区县 浙江

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 天气` 为准。

## 行情

- 权限：普通用户可用
- 触发别名：行情；market；stock market；股指；股市；大盘；美股行情；港股行情；A股行情；B股行情；莫斯科股指；莫斯科行情；hangqing；hq；gushi；gs；dapan；dp；guzhi
- 能力入口：bot.market
- 自然语言触发：行情；A股行情；B股行情；莫斯科股指；莫斯科行情；全球股市；股市；大盘；market；stock market
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚折线卡（MOEX 无东财 kline 时卡上无折线）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：渲染失败回退纯文本
- 可复制示例：行情｜股市｜A股行情｜B股行情｜莫斯科行情
- 关联回归测试：tests/test_market_github.py
- 总览：【行情】全球股指：行情 或 美股行情/港股行情/A股行情/B股行情/莫斯科行情…
- 标题：【行情】全球主要股指行情

### 教程

【板块介绍】
  数据来自东方财富 push2 免费接口（免 key），进程内 60 秒缓存，
  失败降级为「晚点再试」。触发收窄：≤32 字、不带链接（带链接走解析）、
  房价/基金/币圈/显卡/期货/汇率等非股市“行情”自动让路。
【指令与参数】
行情：作用=全球主要指数一览；参数=无；内容=中国区/亚太/欧美指数一览（点位/涨跌幅）；意义=一眼看盘。
行情 + 市场词：作用=只看指定市场；参数=市场词（写在同一句话里，可多个取并集）：A股/B股/上证B/深证B/美股/港股/恒生/日经/纳斯达克/纳指/道琼斯/道指/标普/韩/新加坡/印度/台湾/台股/英国/富时/法国/德国/莫斯科/俄罗斯；内容=对应指数；意义=聚焦关注的市场。过滤词没命中任何指数时回退全部。
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
股价 / 市值 / stocks：作用=九家科技巨头面板；参数=无（不点名公司）；内容=九家美股科技公司一行一价（现价/涨跌幅/近 30 个交易日走势折线＋日收益分布箱形图）；意义=一图看盘。
公司名 + 股价：作用=查单家公司行情；参数=公司名或 ticker（必填）；内容=现价/涨跌幅/日 K/KDJ/总市值金融卡＋延迟标注；意义=聚焦关注的股票。
OpenAI / Anthropic / 字节跳动：作用=问估值；参数=无；内容=有来源的估值口径说明（官方公告/公开报道）；意义=未上市不给股价，只给可信估值。
股价 [公司名]：作用=查股价/市值；参数=公司名或 ticker 可选（英伟达/AMD/英特尔/苹果/微软/谷歌/亚马逊/Meta/台积电，繁体 股價/個股 与英文 stock/stocks 同样可触发；不点名=九家面板）；内容=金融卡或纯文本速览；意义=个股速览。
【权限与效果】
  权限=全员，群聊/私聊行为一致。走势折线为近 30 个交易日收盘；
  箱形图只画多日分布，单日 K 线不成箱（不把 K 线冒充分布）。
【失败兜底】行情拉不到回「美股行情暂时拉不到，晚点再试试？」；
  卡片渲染失败自动回退纯文本。
【示例】英伟达股价｜AMD 股价｜英特尔股价｜股价｜市值｜美股股价｜stocks

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 个股行情` 为准。

## 商品行情

- 权限：普通用户可用
- 触发别名：商品行情；黄金；金价；白银；银价；原油；油价；铜价；大宗商品；黃金；金價；白銀；銀價；油價；銅價；gold；silver；oil；commodity；huangjin；jinjia；youjia；yuanyou；baiyin
- 能力入口：bot.commodities
- 自然语言触发：黄金；金价；白银；银价；原油；油价；铜价；大宗商品；黃金；金價；白銀；油價；銅價；gold；silver；oil；commodity
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚金融卡（商品分组现价/30日走势折线）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：行情拉不到如实标注；渲染失败回退纯文本
- 配置变量：BOT_CARD_RENDER_DIR
- 可复制示例：黄金｜金价｜原油｜铜价｜大宗商品｜gold
- 关联回归测试：tests/test_finance_data.py；tests/test_finance_route_wiring.py；tests/test_market_exclusion_guard.py
- 总览：【商品行情】黄金/白银/原油/铜现价：黄金 或 金价/油价/大宗商品/gold
- 标题：【商品行情】国际大宗商品现价与走势

### 教程

【板块介绍】
  数据来自东方财富外盘主力连续（免 key），进程内缓存；LME 无源
  品种以 COMEX 铜承接，缺数据如实标注、绝不补 0。触发收窄：
  ≤32 字、不带链接；「黄金股行情」这类股市语境自动让路给个股/股指，
  不会误触商品卡。
【指令与参数】
黄金 / 金价：作用=查贵金属现价；参数=品种词可选（黄金/白银/银价…，不带品种=全品种面板）；内容=现价/涨跌幅＋30 日走势折线；意义=一眼看金市。
原油 / 油价：作用=查能源现价；参数=品种词（原油/油价/铜价…）；内容=外盘主力连续报价＋涨跌；意义=盘面速览。
大宗商品：作用=全品种面板；参数=无；内容=贵金属/能源/工业金属分组报价（东财外盘主力连续，LME 无源品种用 COMEX 铜承接）；意义=商品市场一览。
黄金|金价|白银|原油|油价|铜价|大宗商品：作用=查商品现价；参数=品种词写在同一句话里即可（繁体 黃金/金價/白銀/油價/銅價 与英文 gold/silver/oil 同样可触发）；内容=分组报价卡或纯文本速览；意义=商品行情速览。
【权限与效果】
  权限=全员，群聊/私聊行为一致。30 日走势为真实收盘折线。
【失败兜底】行情拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。
【示例】黄金｜金价｜原油｜铜价｜大宗商品｜gold

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 商品行情` 为准。

## 国债收益率

- 权限：普通用户可用
- 触发别名：国债收益率；国债；债券收益率；期限利差；收益率曲线；中美国债；國債；債券收益率；guozhai；xianqilicha
- 能力入口：bot.bond
- 自然语言触发：国债；国债收益率；期限利差；收益率曲线；中美国债；國債；債券收益率
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚金融卡（各期限收益率/10Y−2Y 利差）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：数据拉不到如实标注（1Y 无源诚实不接）；渲染失败回退纯文本
- 配置变量：BOT_CARD_RENDER_DIR
- 可复制示例：国债｜国债收益率｜期限利差｜收益率曲线｜中美国债
- 关联回归测试：tests/test_finance_data.py；tests/test_finance_route_wiring.py
- 总览：【国债收益率】主要期限国债收益率与利差：国债 或 国债收益率/期限利差/收益率曲线
- 标题：【国债收益率】国债收益率与期限利差速览

### 教程

【板块介绍】
  数据来自东方财富 datacenter 国债收益率接口（免 key），进程内
  缓存；1Y 期限暂无稳定公开源，诚实不接、卡上如实标注，绝不补 0。
  利差为上游直供的 10Y−2Y 口径，不做本地二次计算伪造。
【指令与参数】
国债 / 国债收益率：作用=看各期限收益率；参数=期限词可选（不带期限=全期限面板）；内容=2Y/5Y/10Y 等主要期限收益率＋变动；意义=债市一览。
期限利差 / 收益率曲线：作用=看利差与曲线形态；参数=无；内容=10Y−2Y 利差（上游直供口径）＋曲线速览；意义=衰退信号/资金面参考。
国债|国债收益率|期限利差|收益率曲线：作用=查收益率与利差；参数=无（繁体 國債/債券收益率 同样可触发；「中美国债」给中美两侧对比）；内容=收益率面板或利差行；意义=债市与利差速览。
【权限与效果】
  权限=全员，群聊/私聊行为一致。
【失败兜底】数据拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。
【示例】国债｜国债收益率｜期限利差｜收益率曲线｜中美国债

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 国债收益率` 为准。

## 北向资金

- 权限：普通用户可用
- 触发别名：北向资金；北上资金；北向；沪股通；深股通；北向資金；北上資金；滬股通；beixiang；hugutong；shengutong
- 能力入口：bot.northbound
- 自然语言触发：北向资金；北上资金；北向；沪股通；深股通；北向資金；北上資金；滬股通
- 群聊/私聊差异：群聊/私聊行为一致（无会话分支）
- 网络依赖：需要联网
- 输出形式：釉瑚金融卡（成交总额等仍在披露字段）/文本
- 会渲染卡片图：是（失败自动回退纯文本）
- 失败兜底：数据拉不到如实标注（2024-08 起无净买入口径，不推算不伪造）；渲染失败回退纯文本
- 配置变量：BOT_CARD_RENDER_DIR
- 可复制示例：北向资金｜沪股通｜深股通｜北上资金
- 关联回归测试：tests/test_finance_data.py；tests/test_finance_route_wiring.py
- 总览：【北向资金】沪股通/深股通成交动向：北向资金 或 沪股通/深股通
- 标题：【北向资金】北向成交动向速览

### 教程

【板块介绍】
  数据来自东方财富（免 key），进程内缓存。诚实口径：2024-08 起
  交易所不再披露北向净买入额，本模块只报仍在披露的成交总额等
  字段，绝不推算、不伪造净买入。
【指令与参数】
北向资金 / 北上资金：作用=看北向整体动向；参数=无；内容=沪股通/深股通成交总额等仍在披露的字段；意义=外资参与度参考。
沪股通 / 深股通：作用=分通道看；参数=通道词可选；内容=对应通道成交数据；意义=分市场观察。
北向资金|北上资金|沪股通|深股通：作用=查北向成交动向；参数=无（繁体 北向資金/滬股通/深股通 同样可触发）；内容=成交面板或纯文本速览；意义=外资动向参考。
【权限与效果】
  权限=全员，群聊/私聊行为一致。
【失败兜底】数据拉不到会如实说暂拉不到；卡片渲染失败自动回退纯文本。
【示例】北向资金｜沪股通｜深股通｜北上资金

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 北向资金` 为准。

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
汇率：作用=主要货币面板；参数=无；内容=USD 基准的主要货币对速览（中间价/参考价口径）＋无源货币对诚实标注；意义=一眼看汇市。
美元兑人民币 / USD/CNY：作用=查指定货币对；参数=两种币名或 ISO 代码（中文、英文大小写均可）；内容=单行换算与口径/延迟标注；意义=定点查询。
100日元换多少人民币：作用=带金额换算；参数=金额+币名（金额可省，省略按 1 计）；内容=按中间价折算的结果；意义=换钱参考。
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
- 触发别名：占卜；塔罗；八字；算命；算卦；起卦；塔羅；排盤；排盘；命盤；命盘；四柱；搖卦；摇卦；今日塔羅；今日塔罗；今天塔羅；今天塔罗；塔羅三張；塔罗三张；divination；tarot；bazi；iching；zhanbu；taluo；tl；suanming；suangua；sg；qigua；qg；求籤；求签；六十四卦；金錢卦；金钱卦；生辰八字；算一卦；起一卦；摇一卦；搖一卦；掷一卦；擲一卦；占一卦；一卦；每日一签；每日一簽；每日一抽；paipan；sizhu；mingpan；pp；mp；yaogua；yg；liushisigua；lssg；jinqiangua；hexagram
- 能力入口：bot.divination
- 自然语言触发：占卜；塔罗；塔羅；八字；算命；起卦；排盘；排盤；命盘；命盤；四柱；摇卦；搖卦；求签；求籤；今日塔罗；今日塔羅；今天塔罗；今天塔羅；塔罗三张；塔羅三張；tarot；bazi；iching；divination
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
占卜 / 起卦 / 算卦 / 摇卦：作用=金钱卦六掷成卦；参数=无；内容=本卦＋变卦（老爻自动变）；意义=一事一问的娱乐向卜卦。
塔罗：作用=单张指引；参数=无；内容=单张牌＋解读；意义=快问快答。
塔罗 三张：作用=牌阵；参数=无（触发词：三张/过去现在未来/牌阵）；内容=过去/现在/未来三张牌阵；意义=看脉络。
塔罗 每日一抽：作用=今日牌；参数=无（触发词：每日一抽/今日塔罗/今天塔罗）；内容=今日固定牌（同一天同一人不变）；意义=日签。
八字 / 排盘 <生日时间>：作用=四柱排盘；参数=生日时间（可选，如「八字 1998年3月2日早上7点」；日期支持 1998年3月2日/1998-03-02/1998/3/2；时辰支持 早上7点/晚上9点05分/21:51/早上7点半 等，只给日期按午时 12:00 排，不给日期按当前时点排）；内容=四柱排盘＋地支藏干（逐柱本气/中气/余干与权重）＋藏干五行加权统计＋免责尾注；意义=传统命理娱乐；支持 1900-2100 年。
占卜|起卦|算卦|摇卦|六十四卦|金钱卦：作用=起卦；参数=无；内容=卦象＋变卦；意义=卜问。
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
快报 / 早报 / 晚报 / 今日热点：作用=综合快报；参数=无；内容=8 条混合头条（科技/财经/国际轮转）；意义=每日资讯入口。
科技新闻 / AI新闻 / AI快报：作用=科技类目；参数=无；内容=科技/AI 类头条；意义=技术动向。
财经新闻 / 财经快报：作用=财经类目；参数=无；内容=财经头条；意义=市场动向。
国际新闻：作用=国际类目；参数=无；内容=国际头条；意义=世界动向。
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
- 总览：【维基】查通用百科（MediaWiki）：维基 <词条>
- 标题：【维基】查询百科词条

### 教程

【板块介绍】
  纯 MediaWiki 公开 API（免 key），默认中文维基（BOT_WIKI_LANG 可切），
  支持独立页缺失时的精确列表条目提取（BOT_WIKI_ENTRY_PAGES，默认
  鳴潮角色列表，最多优先 3 页）。
【指令与参数】
维基 <词条>：作用=查 MediaWiki 百科；参数=词条名（必填，省略回用法）；内容=词条摘要（游戏类词条自动精简）；意义=快速百科查询。
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
- 关联回归测试：tests/test_moegirl_search.py；tests/test_moegirl_question_fix.py；tests/test_kb_grounding_chat.py
- 总览：【萌娘百科】查 ACG 向百科：萌娘百科 <词条>｜直接问 XX是谁
- 标题：【萌娘百科】查询萌娘百科词条

### 教程

【板块介绍】
  萌百 MediaWiki 公开 API + 本地知识库优先。两条路径：显式指令；以及
  二次元实体问句自动查询（群聊不 @ 不抢答，与聊天同门控；BOT_MOEGIRL_
  QUESTION_ENABLED 可关）。命中不再回「摘要+链接」——条目正文只作
  接地块进入本轮唯一一次生成，用守岸人的世界观和语气说出来，输出全文
  无 URL；命令面只保留用法/候选/无条目/网络失败四类输出。
  问句剥离后剩人称代词（你/我/谁…）、过短/过长、含链接的
  一律不查，交给聊天链路。
【指令与参数】
萌娘百科 <词条>：作用=查萌百词条；参数=词条名（必填）；内容=命中条目正文作接地块，由守岸人重述讲给你（不附链接）；意义=二次元知识库。
直接问「XX是谁/是什么/介绍一下」：作用=实体问句自动查萌百；参数=实体名（2-30 字，剥掉问句后）；内容=本地知识库优先、未命中才查萌百，命中后同一份资料交聊天链用她的语气说出来、全文无链接；意义=自然问法直达；查不到时无感转人格聊天回答。
「XX是谁？」式问句：作用=自动查询；参数=实体名（从问句剥离，2-30 字）；内容=命中=接地重述（无链接），未命中=人格聊天兜底；意义=无门槛问询。
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
历史上的今天：作用=立即查询当天历史；参数=无；内容=当天历史事件清单；意义=即查即看。
历史上的今天 设置 <HH:MM>：作用=设置每日推送时间；参数=时间（必填，HH:MM 24 小时制，取值 00:00-23:59）；内容=设置确认；意义=每天定时收到；群内需管理员（影响全群），私聊自助。
历史上的今天 状态：作用=查看推送状态；参数=无；内容=当前推送时间或未设置；意义=核对。
历史上的今天 取消：作用=取消每日推送；参数=无；内容=取消确认；意义=退订；群内需管理员。
短别名：/历史、/今日历史（带斜杠，避免把聊天里的“历史”误触发）。
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
/bot download <链接>：作用=下载媒体并回传文件；参数=链接（必填，http(s) 开头；B站/油管/推特/小红书/抖音等）；内容=文字摘要（标题/大小/分辨率/时长/画质标注）＋视频文件段；意义=把在线视频搬进群。
限制：单文件 ≤1GB（超限自动降清晰度至最高 8K 上限内）；拒绝非 http(s) 与内网/保留地址（含 DNS 解析后的私网 IP）；依赖 yt-dlp。
权限=全员（H6 定案：产品开放给普通用户，安全边界由 downloader 侧承担）。
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
/<昵称><命令>：作用=用昵称代替 /bot 前缀触发命令；参数=命令名（必填，如 帮助/状态/为什么/天气/点歌/订阅/日志/清理历史/暂停/继续，斜杠可省略）；内容=同对应命令；意义=角色扮演的日常用法。可用昵称经 /bot runtime nickname 维护。
模块/动作词归一：模型=model、设置=runtime、帮助=help、维基=wiki；查看/列表=list、切换=set、用量=usage、思考=think 等动词自动映射。
昵称命令受限：部分管理命令（如日志/记忆）会要求回落到 /bot 形式执行。
管理员另可用 /bot 昵称 set <QQ号> <小名>（5-11 位数字＋1-32 字小名）为群友记小名，用于好感度称呼。
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
直接发链接：作用=自动解析成信息卡；参数=URL（消息里含 http(s) 链接即触发，无需命令词）；内容=平台信息卡（标题/作者/数据/封面，GitHub 仓库出星标/Fork/简介/README 摘要）；意义=不用打开 App 就知道链接里是什么。
支持平台：B站/抖音/小红书/油管/推特/小黑盒/米游社/森空岛/库街区/Lofter/Pixiv/GitHub/音乐平台等；长视频走视频理解可追问。
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
报存 给 <收件人> 发消息，内容…：作用=起草聊天消息草稿；参数=收件人（必填，可用 、,， 分隔多个）＋内容要求（可选，支持 主题：… 内容：… 结构）；内容=草稿预览（通道/收件人/主题/内容要求）；意义=把“要发什么”先落成结构化草稿。
报存 给 <收件人> 发邮件，主题：<主题>，内容：<正文>：作用=起草邮件；参数=收件人（必填）＋主题（可选）＋内容（可选）；内容=草稿预览（M0 仅预览不真实发送）；意义=邮件起草。
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
吃什么：作用=随机推荐 1 道家常菜；参数=无；内容=Mica 菜品卡（名字/口味/食材/做法，本地图包有图上卡）；意义=治今天吃什么。
吃什么 三选一 / 来三道 / 再来一道：作用=控制数量与换一批；参数=修饰词（三选一|来三道|再来一道|再来）；内容=3 道不同菜或补一道；意义=选择困难加倍版。
吃什么 辣的 / 不辣 / 微辣 / 中辣 / 特辣：作用=按辣度过滤；参数=辣度词；内容=过滤后的推荐；意义=口味适配。
菜谱 <菜名> / 怎么做 <菜名> / 如何做 <菜名>：作用=查做法；参数=菜名（必填）；内容=食材＋步骤卡；意义=照着做。
带忌口/食材/人数约束（如「不吃香菜 有鸡蛋 两人吃」）自动走 AI 生成菜谱；菜品图片放 Runtime data/food_images/<菜名>.jpg|.png|.webp 即可上卡。
菜谱 <菜名>（别名 怎么做/如何做）：作用=查做法；参数=菜名必填；内容=食材与步骤；意义=烹饪指引。
【权限与效果】
  权限=全员。普通闲聊（吃了吗/吃火锅）不会被误判成点菜。
【示例】吃什么｜吃什么 三选一｜吃什么 不辣 有鸡蛋｜菜谱 番茄炒蛋

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 吃什么` 为准。

## 媒体归档

- 权限：仅管理员
- 触发别名：收藏；归档；存图；收图；存聊天记录；存记录；archive；shoucang；guidang
- 能力入口：bot.media_archive
- 自然语言触发：收藏；归档；存图；存聊天记录；archive
- 群聊/私聊差异：私聊/群聊行为一致（回复媒体或媒体+指令同条触发）
- 网络依赖：需要联网
- 可复制示例：[图片] 收藏 分类=cosplay IP=鸣潮｜（回复转发）存聊天记录
- 关联回归测试：tests/test_media_archive.py
- 总览：【媒体归档】媒体按 类别/作品 归档：收藏｜归档 IP=原神｜存聊天记录
- 标题：【媒体归档】把媒体按 类别×作品 归档到本机

### 教程

【板块介绍】
  把发到 bot 的图片/动图/视频/聊天记录分析内容并按 类别×作品 双层
  目录归档到本机 data/media_archive（VLM 判定，指令可覆盖）。
【指令与参数】
收藏：作用=归档媒体；参数=可选 分类= IP= 角色=（管理员另可 子路径=）；内容=与图片/动图/视频同条发送，或回复那条媒体；意义=自动分类存档。
归档：作用=同收藏；参数=同上；内容=VLM 判类别与作品来源（cosplay/二次元插图/表情包/截图/照片/风景/人物/动图），判不出落「未识别」；意义=双层目录管理。
存聊天记录：作用=归档聊天记录；参数=无（回复合并转发触发）；内容=展开为 Markdown（含一句话摘要）；意义=永久留档。
安全=SSRF 护栏+magic bytes 质检+sha256 去重+单文件/每日限额；权限=仅管理员（bot_media_archive_min_role，默认超管）。
收藏|归档 [分类=x] [IP=x] [角色=x]：作用=归档；参数=可选；内容=自动/指定分类；意义=整理。
【权限与效果】
  权限=仅管理员（bot_media_archive_min_role，默认 super_admin；改 user 开放全员+限额）。
【示例】[图片] 收藏｜[图片] 收藏 分类=cosplay IP=鸣潮｜（回复图片）收藏｜（回复转发）存聊天记录

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 媒体归档` 为准。

## 群信息

- 权限：普通用户可用
- 触发别名：群信息；本群信息；群资料；群主是谁；谁是群主；群人数；群公告；群精华；精华消息；本群多大了；群相册；本群相册；群相册列表；群待办；本群待办；群待办列表；群里都有谁；本群都有谁；群里谁说过话；本群谁说过话；群参与者；本群参与者；都有谁说过话；我都跟谁聊过；跟谁聊过
- 能力入口：bot.group_info
- 群聊/私聊差异：仅群聊生效（私聊回守岸人提示）；群资料/人数/相册/待办/参与者全员，公告与精华仅管理员；成员名单不整列（隐私+防刷屏），参与者族读记忆里的说话人而非协议名单
- 网络依赖：需要联网
- 输出形式：文本
- 可复制示例：群信息｜群主是谁｜群人数｜群公告｜群精华｜本群多大了
- 关联回归测试：tests/test_group_info.py
- 总览：【群信息】查本群资料：群信息｜群主是谁｜群人数｜群公告｜群相册｜群里都有谁
- 标题：【群信息】本群资料、群主、人数、公告、精华、相册、待办与参与者

### 教程

【板块介绍】
  在群里直接问「群信息 / 群主是谁 / 群人数 / 群公告 / 群精华 / 群相册 / 群待办 / 群里都有谁」，
  守岸人走协议端群接口现查现答：QQ 侧 OneBot V11（群资料/成员列表/公告/精华/相册/待办），
  Telegram 侧按 Bot API 对等回答（群名/介绍/人数/群主与管理员/置顶当公告位/我的身份与头衔；
  全量成员名单与精华/相册/待办没有对应接口，缺的逐条直说不猜），
  邮件里没有「群」这个对象，只答本会话元信息与参与者；
  资料带进程内缓存（资料 600s/成员 900s/公告 600s/相册 600s/待办 120s），
  待办缓存刻意给得短——刚设好的待办不该被旧表盖住。
【指令与参数】
群信息：作用=查本群小档案；参数=无；内容=群名/群主/人数/上限/管理员数，管理员另附公告首段与精华条数；意义=一问就知道群概况。
群主是谁｜群人数｜本群多大了：作用=单点直问；参数=无；内容=只答问的那一项（建群时长依赖协议字段，没有就直说）；意义=口语直问直答。
群公告｜群精华：作用=看公告首段/精华条数；参数=无；内容=仅管理员，其余成员收到权限提示；意义=群务信息分级可见。
群相册｜群待办：作用=看本群相册概览与挂着的待办；参数=无；内容=相册只到「哪个相册多少张」这一层、不列单张照片，待办最多列 5 条并显式说另有几条；意义=群务一眼看全。
群里都有谁｜群参与者｜谁说过话：作用=说清这个群里都有谁在说话；参数=无；内容=按记忆里的说话人给名字（不是协议成员名单），人多的群给前若干名并显式说还有多少，读过记录却一条都没取到时直说「没读到记录」而不是「没人说过话」；意义=知道自己在跟谁聊。
边界（诚实降级）：群链接/群分享、群等级/群标签仍无对应动作，不做不假装；相册与待办的字段名认不出时只报条数、不编名字；接口失败如实说拿不到（≠本群没有）；成员名单不整列（隐私+防刷屏）；参与者来自记忆而非协议名单，两者不是一回事；仅群聊生效。
【参与者这一项】
  「群里都有谁 / 群参与者 / 谁说过话」这一族不查协议名单，答的是记忆里真的说过话的人；
  同一份判据在群聊与私聊各自成腿，看的范围就是当前这个会话；没读到记录时如实说没读到。
【权限与效果】
  权限=群资料/人数/相册/待办/参与者全员；公告与精华仅管理员。仅群聊生效，私聊回提示。
【示例】群信息｜群主是谁｜群人数｜本群多大了｜群公告｜群精华｜群里都有谁

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 群信息` 为准。

## 宿主机状态

- 权限：仅管理员
- 触发别名：宿主机状态；机器状态；机器配置；宿主状态；宿主機狀態；機器狀態；hoststate；jiqizhuangtai；jizhuangtai；jiqipeizhi
- 能力入口：bot.host_state
- 群聊/私聊差异：仅超级管理员（其余角色得到一句温和拒绝）；群聊与私聊同面可问；读数本机现算、逐行打码，只读不改任何设置
- 网络依赖：纯本地
- 输出形式：文本；图片
- 可复制示例：机器状态｜机器配置｜宿主状态｜hoststate
- 关联回归测试：tests/test_host_state_card.py；tests/test_host_metrics.py；tests/test_host_status.py
- 总览：【宿主机状态】超管看本机：机器状态｜机器配置｜版本与占用
- 标题：【宿主机状态】这台机器的配置、占用与运行版本（仅管理员）

### 教程

【板块介绍】
  说「机器状态 / 机器配置 / 宿主机状态」，守岸人现读本机事实：
  版本族（NoneBot、OneBot 适配器、协议端、插件、Python）走包元数据，
  硬件与占用走系统计数器，两路都汇到 domains/ops/host_metrics.py 这一个取数口。
【指令与参数】
机器状态：作用=报本机实况；参数=无；内容=CPU/内存/磁盘占用、显卡与显存、系统版本，附守岸人自己的运行版本族；意义=一句话知道机器现在累不累。
机器配置：作用=报硬件；参数=无；内容=型号/核心数/总内存/磁盘分区容量；意义=区分「配置」与「此刻占用」两件事。
读数来源：全部本机现算（版本走包元数据，占用走系统计数器），不是背下来的一段话；拿不到的项直说拿不到，绝不补一个看起来合理的数。
出图：能出图时发一张超管视图卡片（属性名与属性值各自左对齐）；渲染后端不可用时退成纯文本，并把「卡未出图」那句话说明白。
边界：这是超管专属视图，非超管问到只会得到一句温和的「这台机器我不对外报」，不会泄露盘符路径或任何密钥形态；本能力只读，不碰任何设置与文件。
【权限与效果】
  权限=仅超级管理员（其余角色得到一句温和的拒绝，不报错、不泄露）。
  效果=一张 Mica 卡片图 + 一份纯文本台账；渲染后端缺席时只剩文本，且卡上那行「未出图」会直说。
  读数 90 秒内复用缓存，连续追问不重复扫机器；每行出卡前过打码口。
【示例】机器状态｜机器配置｜宿主状态｜hoststate

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 宿主机状态` 为准。

## 书面同意

- 权限：仅管理员
- 触发别名：同意卡；书面同意；同意單；書面同意；consentcard；yijika；shumiantongyi
- 能力入口：bot.consent
- 群聊/私聊差异：仅管理员及其以上；看单不分群聊私聊，批一张具体的卡按同意账的阶梯判（R2=超管私聊亲批）；发起人不批自己发起的卡；只回显账上事实，本命令面自己绝不改参数
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：同意卡 待批｜同意卡 看 3f2a1b｜同意卡 批 3f2a1b 8c1d4e7a｜书面同意 驳 3f2a1b 8c1d4e7a
- 关联回归测试：tests/test_consent_command_surface.py；tests/test_safety_exec_throat_wire.py
- 总览：【书面同意】危险参数的批准入口：同意卡 待批｜看｜批｜驳（仅管理员）
- 标题：【书面同意】哪些参数改动在等谁点头，以及怎么点这个头（仅管理员）

### 教程

【板块介绍】
  需要书面同意的参数被改动时，设置咽喉不落笔，先签一张同意卡；这一族命令就是把那张卡批掉或驳回的那句话。
  分级表唯一住 domains/core/safety_exec/config_risk.py，同意账唯一住 domains/core/safety_exec/consent.py，
  执法点唯一住 domains/core/safety_exec/settings_gate.py——本命令面零判定、零第二本账，只把一句入站消息交给它。
【指令与参数】
同意卡 待批：作用=列出还没人批的工单；参数=无；内容=每张卡的工单号、短码、要改哪枚参数、旧值→新值、风险档、申请人、签出与过期时刻；意义=点头之前先把要改的东西看完整，不靠别人转述。
同意卡 看 <工单号>：作用=单看一张卡的全文；参数=工单号（卡面上那一串，必填）；内容=与待批页同一套字段，多一个「状态」；意义=群里传话传了一半时，以账上的原文为准。
同意卡 批 <工单号> <短码>：作用=照卡面批准这一件；参数=工单号 + 卡上短码（两个都必填，短码必须逐字对上）；内容=批语已记下，并说清接下来该谁做什么；意义=危险的参数改动要的是有权限的人亲手的一句话，不是模型顺手的一个字。
同意卡 驳 <工单号> <短码>：作用=驳回并作废这张卡；参数=工单号 + 短码；内容=已驳回，这张卡不再有效；意义=不想改就明说不改，别让它挂到过期还占着待办。
认不下的句子一律不当命令：触发词后面跟了我看不懂的东西，我就当没听见，绝不「大概像」就把它读成一次批准。
【档位是什么】
  R0 不问就改（每次照记一行流水）；R1 由管理员在原会话里确认（超管本人发起的 R1 免卡直改）；R2 要超级管理员在私聊里亲口批；
  R3 连批都不给，只允许出待审补丁，部署由主人亲手做。
【权限与效果】
  权限=管理员可看单；一张具体的卡够不够格批，由账上的阶梯判：可信级、私聊门、原会话门、
  发起人不得批自己发起的那张（超管例外）、一次性、到点作废（不可续）。判据只有一处，这里不复制。
  效果=改动的真身在批之前一个字节都不动；短码对不上不算批也不算驳，那张卡照旧待批，但这次尝试会落一条流水。
【批了之后】
  批准即当场落地：核销那一刻我照卡上冻结的那件事直接落笔，不用再发一遍；凭证一次有效。
  账本装不上、值与当初批的对不上、没有热改路径的，一律不改并退回同参重发，明说为什么——不做「看起来改了」那种回显。
【示例】同意卡 待批｜同意卡 看 3f2a1b｜同意卡 批 3f2a1b 8c1d4e7a｜书面同意 驳 3f2a1b 8c1d4e7a

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 书面同意` 为准。

## 好感度

- 权限：普通用户可用
- 触发别名：好感度；好感；好感查看；查询好感；查詢好感；親密度；affinity；haogandu；hgd；haoganchakan；hgck；chaxunhaogan；cxhg
- 能力入口：bot.affinity
- 自然语言触发：好感度；好感；查询好感；查詢好感；亲密度；親密度；affinity
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
好感度：作用=查好感；参数=无；内容=私聊=双向好感卡；群聊=本群好感榜（有印象成员，自己高亮，展示前 12/上限 60）；意义=关系可视化。
好感度 我：作用=只看自己；参数=我（别名 自己/me）；内容=双向分值；意义=群里不想看榜时用。
好感度 算法：作用=说明规则；参数=算法（别名 说明/规则/help）；内容=图文算法卡＋你与守岸人之间的氛围画像；意义=透明化。
计分（v5 定性版）：好感随言行连续累积——综合说话的温度、相处的时间、第一印象、当天状态平滑变化，没有固定加几减几；同一天同类言行影响递减；久不联系慢慢回到基准；难听的记忆随时间淡去。
档位：初识/生疏/微凉/稍淡/友善（基准）/亲近/挚友/独一份 共八档，连续过渡、不在门槛上生硬跳变；任何档位都不强硬、不辱骂、不弃聊。
好感度 我|自己|me：作用=只看自己；参数=任选其一；内容=双向分值；意义=隐私。
好感度 算法|说明|规则|help：作用=算法说明；参数=任选其一；内容=规则＋档位态度对照＋你与守岸人之间的氛围画像（定性描述，不展示具体加减数值）；意义=透明。
【权限与效果】
  权限=全员。好感度功能总开关 bot_affinity_enabled。
【示例】好感度｜好感度 我｜好感度 算法

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 好感度` 为准。

## Epic

- 权限：普通用户可用
- 触发别名：epic；epic free；epic 免费；免费游戏；免費遊戲；遊戲免費；steam免費；steam 免費；游戏免费；steam免费；steam 免费
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
epic / epicfree / Epic 免费 / 免费游戏 / steam免费：作用=查本周限免；参数=无；内容=Epic 每周限免＋Steam 100% 折扣限免合并清单（标题/截止/链接，Mica 卡图）；意义=白嫖情报。
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
- 配置变量：BOT_RANDPIC_DIRS；BOT_RANDPIC_TRIGGER_WORDS；BOT_RANDPIC_ENABLED；BOT_RANDPIC_MAX_FILE_MB；BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS；BOT_RANDPIC_DISPATCH_ENABLED；BOT_RANDPIC_DISPATCH_PROBABILITY；BOT_RANDPIC_DISPATCH_COOLDOWN_SECONDS；BOT_RANDPIC_DISPATCH_MAX_PER_HOUR
- 可复制示例：随机图｜来张图
- 关联回归测试：tests/test_randpic_identity.py；tests/test_randpic_dispatch.py
- 总览：【随机图】从图库随机发一张：随机图 / 来张图（也可回复后主动发）
- 标题：【随机图】图库随机发图

### 教程

【板块介绍】
  借鉴 nonebot-plugin-randpic 的“指令→随机图”玩法但只吸收思路：
  不建目录、不建数据库、不做上传，一把随机梭哈。目录清单 30 秒 TTL
  缓存，改文件夹半分钟内生效。P14 波把「谁开口要图才发」扩成
  三触发：指令 / 回复完用户消息后 / 用户戳 bot 后（后两条缺省关）。
【指令与参数】
随机图 / 来张图：作用=从你配置的图库文件夹随机发一张图；参数=无；内容=一张图片（jpg/jpeg/png/gif/webp/bmp，单张 ≤20MB）；意义=自建图库的抽卡玩法。
回复后主动发图（P14）：bot 答完一句就有概率补一张图；BOT_RANDPIC_DISPATCH_ENABLED、BOT_RANDPIC_DISPATCH_PROBABILITY、BOT_RANDPIC_DISPATCH_COOLDOWN_SECONDS、BOT_RANDPIC_DISPATCH_MAX_PER_HOUR（缺省关）。戳 bot 那条走戳一戳的 randpic 臂（见「戳一戳」页），三触发共用同一条读目录路径与同一本窗账。
窗内不重发：BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS（按会话记账，0=关=旧行为可重样）；开态下指令路整库都在窗内时退「最久没发」那张（不拒不发），主动路宁可不发也不刷屏。
配置：图库目录写在 BOT_RANDPIC_DIRS（可多个、递归扫描、只读绝不自建目录）；触发词可用 BOT_RANDPIC_TRIGGER_WORDS 换成自己的（默认 随机图/来张图）。
随机图|来张图：作用=发图；参数=无（触发词后跟标点/语气词也可命中；「随机图片库」这类包含关系词不误触发）；内容=图片或图库为空的配置提示；意义=娱乐。
【取值范围】
  BOT_RANDPIC_DIRS：文件夹路径列表；扩展名 jpg/jpeg/png/gif/webp/bmp；
  单文件 ≤20MB；目录不存在/为空/图被移走时给友好提示不报错、不发死引用。
  BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS：≥0 秒，0=不记账按纯随机。
【权限与效果】
  权限=全员（bot_randpic_enabled 可关）。主动发图那条腿同样吃安静时间
  窗与 blocked 名单两道硬门，拨开概率也越不过。
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
<时间>提醒我 <事项>：作用=到点主动督促；参数=时间（必填，支持绝对「12点/明天早上8点/下午三点半」与相对「半小时后/N分钟后/N小时后」）＋事项（可选，截取 ≤120 字，省略给默认文案）；内容=记下确认＋取消用的 id 前缀；意义=守岸人版闹钟。
提醒列表 / 我的提醒：作用=查看待办；参数=无；内容=本会话待办提醒（id 前 6 位＋时刻＋事项）；意义=盘点。
取消提醒 <id前缀>：作用=取消某条；参数=id 前缀（必填，4-12 位十六进制，需唯一命中，多条命中会要求换更长前缀）；内容=取消确认；意义=反悔。
规则：只提醒“当前会话”；无明确日词且时刻已过自动顺延明天；时间必须晚于当前，否则视为没解析到。
提醒列表|我的提醒|看看提醒|有哪些提醒：作用=列待办；参数=无；内容=清单；意义=盘点。
【权限与效果】
  权限=全员（bot_reminder_enabled 可关）。投递按会话作用域（群=群内，
  私聊=本人），发送走队列。
【示例】12点提醒我写作业｜明天早上8点叫我起床｜半小时后提醒我去看汤｜提醒列表｜取消提醒 a3f2

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 提醒` 为准。

## 笔记

- 权限：普通用户可用
- 触发别名：笔记；筆記；biji；note；笔记列表；bijiliebiao；bjlb
- 能力入口：bot.reminder
- 自然语言触发：笔记 记 <内容>；笔记列表；笔记 看 N；看笔记 N；做完 N；完成 N；办完 N；删笔记 N；<事项>做完了
- 群聊/私聊差异：笔记按会话隔离（A 群看不到 B 群）；配图落 data/notes_images
- 网络依赖：纯本地
- 输出形式：文本；图片（回看补发）
- 配置变量：BOT_NOTES_ENABLED；BOT_NOTES_DB_PATH；BOT_NOTES_MAX_PER_CHAT
- 可复制示例：笔记 记 周三要交总结｜笔记列表｜笔记 看 1｜做完 1｜完成 1｜删笔记 1
- 关联回归测试：tests/test_notes.py；tests/test_todo_checkoff.py；tests/test_reminder_tone.py
- 总览：【笔记】Markdown 笔记与待办：笔记 记 <内容>｜笔记列表｜笔记 看 N｜做完 N｜删笔记 N
- 标题：【笔记】Markdown 笔记与待办勾选

### 教程

【板块介绍】
  Markdown 笔记本：内容原样存储（#/## 三级标题、列表、勾选框），
  按会话隔离（A 群看不到 B 群）；含「- [ ]」的笔记自动成为待办，
  可被「做完 N」或自然语言勾选了结。
【指令与参数】
笔记 记 <内容>：作用=记一条笔记；参数=内容（必填，Markdown 原样存，#/## 三级标题可用；写「- [ ] 待办」的行按待办看待；可配图一起发，最多 4 张自动落盘）；内容=记下确认＋编号；意义=把事情交给我保管。
笔记列表 / bijiliebiao：作用=列出本会话笔记；参数=无；内容=编号＋待办状态（□/☑）＋首行摘要；意义=盘点。
笔记 看 N：作用=翻开第 N 条；参数=编号（必填）；内容=纯文本正文（标题保留 #，图片显示 [图片N]），配图原样补发；意义=回看。
做完 N：作用=勾选第 N 条待办；参数=编号（必填）；内容=完成确认；自然语言也行——「作业做完了」会模糊匹配未完成提醒与笔记待办，命中即勾。
删笔记 N：作用=删除第 N 条；参数=编号（必填）；内容=删除确认（配图一并清理）；意义=放下。
笔记列表（筆記列表/bijiliebiao/bjlb）：作用=清单；参数=无；内容=编号＋状态＋摘要；意义=盘点。
【权限与效果】
  权限=全员（bot_notes_enabled 可关）。单会话上限 bot_notes_max_per_chat
  （默认 200），满了会提示先清理；数据库与图片经 runtime 路径落盘。
【示例】笔记 记 周三要交总结（换行）- [ ] 写初稿｜笔记列表｜笔记 看 1｜做完 1｜删笔记 1｜作业做完了

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 笔记` 为准。

## 日程

- 权限：普通用户可用
- 触发别名：日程；日程板；日程列表；我的日程；看看日程；日程清单；日程表；日程导入；课表导入；课表；課表；她在干嘛；她在忙什么；主人在干嘛；主人去哪了；她出去了吗；richeng；richengliebiao；rclb；schedule；kebiao
- 能力入口：bot.reminder
- 自然语言触发：日程 <时间> <活动>；日程表；日程列表；我的日程；日程 删 <N>；日程 删课 <N>；日程 公开 <N>；日程 隐私 <N>；日程 导入 <多行文本>；课表 导入 <多行文本>；课表；她在干嘛；她在忙什么；主人在干嘛；主人去哪了；她出去了吗；明天8点有课
- 群聊/私聊差异：日程板按用户归属（board-<owner>，与提醒/笔记共库不共表义）；代答按可见性分级投影
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_SCHEDULE_ENABLED；BOT_SCHEDULE_DB_PATH；BOT_SCHEDULE_STATUS_REPLY_ENABLED；BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED
- 可复制示例：日程 明天8点到9点半 高数｜日程 每周三14:00 组会 公开｜日程表｜日程 公开 2｜日程 删 3｜她在干嘛
- 关联回归测试：tests/test_schedule_board.py
- 总览：【日程】她的日程表与智能代答：日程 <时间> <活动>｜日程表｜日程 删 N｜日程 公开 N｜课表 导入
- 标题：【日程】日程记录、课表导入与按分级表代答

### 教程

【板块介绍】
  日程板复用 V2.1 日程引擎（与提醒共用车间不共表义）：一条日程=
  活动＋起止时刻＋可见性（公开/隐私，缺省隐私）。信息来源只有你
  亲口说过的话与发来的课表——不查设备、不读定位、不做任何本机监控。
【指令与参数】
日程 <时间> <活动>：作用=往你的日程板记一条；参数=时间（必填，支持「明天8点/8点到9点半/每周三」，单双周要带「学期 2026-09-07」）＋活动正文（可带「公开」二字）；内容=编号式确认；意义=把安排交给我排好。缺省隐私。
日程表 / 日程列表 / 我的日程：作用=看未来 30 天安排；参数=无；内容=编号＋时刻＋[公]/[密]；意义=盘点。
日程 删 N：作用=放下第 N 条最近那次；参数=编号（日程表里的号）；内容=确认；「日程 删课 N」整条安排不再出现。
日程 公开 N / 日程 隐私 N：作用=切换第 N 条对别人的可答面；参数=编号；内容=确认；公开也只说「在做什么＋几点到几点」。
日程 导入 / 课表 导入：<多行文本>：作用=课表/计划整批记（一行一条「周X 8:00-9:40 名称 地点 单/双」）；也可以直接发课表图片（图只在你发来的这一刻读，不存不扫）。
她在干嘛 / 主人在忙什么：作用=别人替你问一声；内容=按分级表回：公开条目普通用户只听得到类别与时刻，熟人（trusted/管理员）听得到活动名；隐私与敏感细节永不出口。
【权限与效果】
  记录腿全员可用（BOT_SCHEDULE_ENABLED 总闸，缺省关，改后重启）。
  代答腿另有总闸 BOT_SCHEDULE_STATUS_REPLY_ENABLED（缺省关）；
  自然语言顺手记（「明天8点有课」不带「日程」二字）另受
  BOT_SCHEDULE_NATURAL_CAPTURE_ENABLED 控制（缺省关）。
  隐私判定发生在出站前：代答由确定性投影成句，不经大模型，
  地点/健康/饮食/作息细节对非本人永不外给（分级表见设计文档）。
【示例】日程 明天8点到9点半 高数｜日程 每周三14:00 组会 公开｜日程表｜日程 公开 2｜日程 删 3｜日程 导入 周一8:00-9:40 高数 一教101｜她在干嘛

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 日程` 为准。

## 收件箱

- 权限：普通用户可用
- 触发别名：收件箱；inbox；shoujianxiang
- 能力入口：bot.daily_assist
- 自然语言触发：收件箱 <内容>；收件箱
- 群聊/私聊差异：收件箱是全局一份纯文本文件（bot_daily_assist_dir），不分会话；定时简报仅私聊推送名单
- 网络依赖：纯本地
- 输出形式：文本
- 配置变量：BOT_DAILY_ASSIST_ENABLED；BOT_DAILY_ASSIST_DIR；BOT_DAILY_ASSIST_PUSH_USER_IDS；BOT_DAILY_ASSIST_MEAL_TIMES；BOT_DAILY_ASSIST_MORNING_TIME；BOT_DAILY_ASSIST_EVENING_TIME
- 可复制示例：收件箱 周五前还信用卡｜收件箱 买猫粮｜收件箱
- 关联回归测试：tests/test_daily_assist.py
- 总览：【收件箱】随手把事情丢进来：收件箱 <内容>｜收件箱
- 标题：【收件箱】随手速记与早晚简报

### 教程

【板块介绍】
  收件箱是一份纯文本文件（bot_daily_assist_dir 下 inbox.md），
  手机/电脑都能直接编辑；早报读取后归档到 daily/ 按日期存放。
【指令与参数】
收件箱 <内容>：作用=把待办/杂事记进收件箱文件；参数=内容（必填，≤2000 字）；内容=收录确认；意义=想到就丢，不用惦记。
收件箱：作用=看当前攒着的事；参数=无；内容=编号清单；意义=盘点。
定时：每天 09:00 早报整理收件箱并归档，21:00 晚报对账；到饭点还会随机推荐吃什么（BOT_DAILY_ASSIST_* 可调）。
【权限与效果】
  权限=全员（bot_daily_assist_enabled 可关）。定时推送目标只取
  BOT_DAILY_ASSIST_PUSH_USER_IDS 名单，名单为空则只记不推。
【示例】收件箱 周五前还信用卡｜收件箱 买猫粮｜收件箱

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 收件箱` 为准。

## 语音

- 权限：普通用户可用
- 触发别名：语音；tts；yuyin；语音合成；說；語音；唸；朗讀；語音合成
- 能力入口：bot.tts
- 自然语言触发：说 <文本>；语音 <文本>；念 <文本>；朗读 <文本>；语音合成 <文本>；tts <文本>；say <文本>；說 <文本>；語音 <文本>；唸 <文本>；朗讀 <文本>；語音合成 <文本>
- 群聊/私聊差异：全员可用；对话自动配音范围由 BOT_TTS_AUTO_REPLY_SCOPE 决定（private/group/all）
- 网络依赖：纯本地
- 输出形式：语音
- 配置变量：BOT_TTS_ENABLED；BOT_TTS_API_URL；BOT_TTS_GPTSOVITS_DIR；BOT_TTS_REF_AUDIOS；BOT_TTS_TRIGGER_WORDS；BOT_TTS_OUTPUT_DIR；BOT_TTS_PRESET；BOT_TTS_MAX_CHARS；BOT_TTS_HARD_MAX_CHARS；BOT_TTS_MAX_AUDIO_BYTES；BOT_TTS_TIMEOUT_SECONDS；BOT_TTS_SPEED_FACTOR；BOT_TTS_TEMPERATURE；BOT_TTS_TOP_K；BOT_TTS_TOP_P；BOT_TTS_TEXT_LANG；BOT_TTS_TEXT_SPLIT_METHOD；BOT_TTS_CACHE_ENABLED；BOT_TTS_CACHE_MAX_BYTES；BOT_TTS_CACHE_MAX_AGE_DAYS；BOT_TTS_AUTO_REPLY_ENABLED；BOT_TTS_AUTO_REPLY_SCOPE；BOT_TTS_AUTO_REPLY_MAX_CHARS；BOT_TTS_AUTO_REPLY_SPLIT_MAX_CHARS；BOT_TTS_AUTO_REPLY_PROBABILITY；BOT_TTS_AUTO_REPLY_ALWAYS；BOT_TTS_VOICE_HOOK_ENABLED
- 可复制示例：说 今天的潮汐很安静｜语音 我在这里｜tts hello
- 关联回归测试：tests/test_tts.py；tests/test_tts_outbound_chain.py；tests/test_tts_hijack_guard.py；tests/test_tts_speech_gate.py；tests/test_tts_failure_visibility.py；tests/test_tts_audio_gate.py
- 总览：【语音】让我用声音念一段话：说 <文本>
- 标题：【语音】用守岸人的声音念出来

### 教程

【板块介绍】
  语音能力对接本机 GPT-SoVITS v2ProPlus 的 HTTP 接口（api_v2.py，默认 9880），
  用你训练好的守岸人权重合成；文本不出本机，合成结果落运行时目录。
【指令与参数】
说 <文本>：作用=把文本合成为守岸人音色的语音消息；参数=文本（必填，默认上限 200 字，BOT_TTS_MAX_CHARS=0 为不限）；内容=一段声音连同它所读的那串字（声音在前、文字在后，同一条消息里一起发出）；意义=让回复带上声音。
语音 <文本>｜念 <文本>｜朗读 <文本>｜tts <文本>：触发词等价，繁體 說/語音/唸/朗讀/語音合成 同（正文保留繁體用字）；BOT_TTS_TRIGGER_WORDS 可自定义。
对话自动配音：两闸串联才会发声——总闸 BOT_TTS_ENABLED 与自动配音闸 BOT_TTS_AUTO_REPLY_ENABLED 都得开着，人格回复才连同语音一起发出；范围由 BOT_TTS_AUTO_REPLY_SCOPE 决定（private/group/all）。
配音走哪条腿：BOT_TTS_VOICE_HOOK_ENABLED 只选路、不是开关。开=新链，正文先过审再拿去合成，合成失败会留一条运营故障（进中央告警与诊断卡）；关=旧包装路径，失败就不带语音、正文照发，只在结果上留机读留痕。该键装配期读死，改后要重启。
配音概率：默认有 10% 的回复会带语音（BOT_TTS_AUTO_REPLY_PROBABILITY）；BOT_TTS_AUTO_REPLY_ALWAYS=true 可临时改成条条都配，方便验收听音。
长句拆条：BOT_TTS_AUTO_REPLY_SPLIT_MAX_CHARS>0 时，超字数自动按句末标点切成多条语音随同一条消息发出（0=不拆；语速 0.85 时 60 秒≈150~180 字）。
预设与硬顶：合成参数以中央预设表为唯一缺省源（BOT_TTS_PRESET，其余数值键=管理员覆盖）；单次文本硬顶 2000 字、产物 8 MiB（BOT_TTS_HARD_MAX_CHARS / BOT_TTS_MAX_AUDIO_BYTES，超限拒绝并留痕）；群聊自动配音另受内容群白名单安全门约束（黑名单永远赢，白名单空=群面不配音绝不猜群）。
【权限与效果】
  权限=全员，前提是 BOT_TTS_ENABLED=true 且 9880 服务在跑。参考音频未配置、
  服务未启动或超时，都会得到一句可读的降级文案而不是报错；引擎不可达时
  会进入短暂退避冷却快速失败，不挂起消息。合成结果按内容+引擎身份缓存，
  同一句话不重复合成（同句恒同音色）。
  对话自动配音按概率触发（默认 5%），判定用确定性哈希——同一条消息结果
  恒定，不会一会儿配一会儿不配。
【示例】说 今天的潮汐很安静｜语音 我在这里｜tts hello

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 语音` 为准。

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
/bot help：作用=按权限输出分类总览；参数=无；内容=管理员/大模型/子功能三类清单，每行附「/bot help <模块>」展开引导；意义=一切入口的入口。渲染成功发 Mica 卡，失败回纯文本。
/bot help <模块>：作用=单模块深度页；参数=模块名或别名（如 /bot help 点歌、/bot help music）；内容=作用/参数/取值/权限四要素＋示例＋详细教程；意义=逐参数自助。
权限=普通用户只见公开模块，管理员另见诊断与配置模块；查无此模块回「没有找到」并提示相近分类。
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
群聊：@机器人、昵称点名或直接写名字才会回；其余消息默认静默观察，自动接话开启时按概率抽签，且主动接话受好感门（好感档 ≥ 亲近）。
私聊：白名单内直接发消息即可对话。
边界：现实问题会联网检索（仅管理员可见 🔎 调试标记）；世界观问题走人格档案＋向量知识库。
失败：私聊回守岸人话术提示，群聊保持静默不刷屏。
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
- 输出形式：文本回应；语音+文本；表情包图片；随机图片；回戳
- 配置变量：BOT_POKE_ENABLED；BOT_POKE_PROBABILITY；BOT_POKE_REPLY_ENABLED；BOT_POKE_REPLY_MODE；BOT_POKE_POKE_BACK；BOT_POKE_EXTRA_ARMS_ENABLED；BOT_POKE_PRIVATE_COOLDOWN_SECONDS；BOT_POKE_GROUP_COOLDOWN_SECONDS；BOT_POKE_GROUP_TEXT；BOT_POKE_PRIVATE_TEXT；BOT_POKE_FOLLOW_ENABLED；BOT_POKE_FOLLOW_PROBABILITY；BOT_POKE_FOLLOW_COOLDOWN_SECONDS；BOT_POKE_FOLLOW_MAX_PER_HOUR；BOT_POKE_AFTER_REPLY_ENABLED；BOT_POKE_AFTER_REPLY_PROBABILITY；BOT_POKE_AFTER_REPLY_COOLDOWN_SECONDS；BOT_POKE_AFTER_REPLY_MAX_PER_HOUR；BOT_POKE_AFFINITY_ENABLED；BOT_POKE_AFFINITY_DELTA；BOT_POKE_AFFINITY_DAILY_MAX
- 关联回归测试：tests/test_poke_v2.py；tests/test_poke_arms_v3.py
- 总览：【戳一戳】被戳回一个（六臂轮换）+ 跟戳 + 说完顺手戳（都有冷却）
- 标题：【戳一戳】戳一戳互动回应

### 教程

【板块介绍】
  戳一戳是轻量互动：群友戳机器人头像，机器人按概率回应一个表达。
  冷却与概率防止连戳刷屏。P14 波把「回应」扩成六臂矩阵，并补了
  跟戳（A 戳 B 时跟着戳）与「说完话顺手戳一下」两条主动腿。
【指令与参数】
触发=QQ「戳一戳」头像互动；行为=按概率回应，默认有冷却防骚扰。
被戳回一个（六臂确定性轮换，只出一个）：反戳 / 自然语言回复 / 语音+文本 / 表情包 / 随机图 / 固定话术；BOT_POKE_REPLY_MODE 显式指名任一臂，mix=轮换（扩臂要 BOT_POKE_EXTRA_ARMS_ENABLED=true，缺省停在旧三臂=旧行为）。
跟戳：群里 A 戳 B 时按概率跟着戳 B；BOT_POKE_FOLLOW_ENABLED、BOT_POKE_FOLLOW_PROBABILITY、BOT_POKE_FOLLOW_COOLDOWN_SECONDS、BOT_POKE_FOLLOW_MAX_PER_HOUR（缺省关；独立于回戳的冷却与每小时账）。
说完顺手戳：bot 回复完、群内主动接话、入群欢迎之后按概率戳一下对方；BOT_POKE_AFTER_REPLY_ENABLED、_PROBABILITY、_COOLDOWN_SECONDS、_MAX_PER_HOUR（缺省关）。
硬门：安静时间窗内、blocked 名单里的人一律不戳也不主动发图——拨开概率开关也越不过这两道。
语音臂复用 bot.tts 那条「文本+语音」能力（BOT_TTS_ENABLED 且引擎在线才有声，合成不成只留文本腿）；随机图臂吃 BOT_RANDPIC_DIRS（图库空则温和回退固定话术，绝不静默空回）。
可调：BOT_POKE_ENABLED（开关）、BOT_POKE_*_COOLDOWN_SECONDS（冷却）、BOT_POKE_PROBABILITY（概率）。
权限=全员；无文字命令，属互动事件。
无指令：作用=头像互动回应与轻量主动接触；参数=无；内容=六臂之一（一句回应 / 语音+文本 / 一张图 / 回戳）；意义=轻互动。配置经 .env 或 /bot runtime set（可写键以 runtime 白名单为准，本族多为改 .env+重启）。
【取值范围】
  BOT_POKE_REPLY_MODE：fixed/llm/meme/voice/randpic/poke 六值显式指名，
  或 mix=按 (会话,戳者,时间桶) 的 SHA-256 摘要确定性轮换（同戳同果，
  不用随机数）；轮换池缺省三臂，BOT_POKE_EXTRA_ARMS_ENABLED=true 才扩到六臂。
  概率类键取值 0..1；冷却与每小时上限各自独立记账。
【权限与效果】
  权限=全员。开关关闭时戳一戳无任何回应；安静时间窗与 blocked 名单
  是硬门，主动腿（跟戳/说完顺手戳/主动发图）全部缺省关。
【示例】戳一戳守岸人的头像 → 有概率收到回应（话术 / 语音 / 一张图 / 被戳回来）

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
行为：监听群聊图片，自动异步下载、MD5 去重、≤5MB 入库，SQLite 记元数据。
筛选：权重打分（守岸人×8 → 鸣潮/战双/库洛×4 → ACG×1.5 → 普通×1；非表情×0.25）；NSFW≥0.2 降权、≥0.8 永不发送；可选 VLM 自动打标。
消费：用「偷表情 [关键词]」加权随机抽取，用「表情库统计」看库存；本模块自身无命令、靠监听生效。
本模块无命令：作用=自动收库；参数=无；内容=群图异步入库（不直接回复）；意义=偷表情的弹药库。库存操作入口：偷表情｜表情库统计（见「偷表情」模块）。
【权限与效果】
  权限=全员（被动机制）。下载绝不阻塞消息主链路。
【示例】群里发一张表情图 → 自动入库 → 之后「偷表情」可能抽到它

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 表情收库` 为准。

## 表情册

- 权限：仅管理员
- 触发别名：表情册；表情相冊；biaoqingce
- 能力入口：bot.meme_library
- 自然语言触发：审批；待审
- 网络依赖：纯本地
- 输出形式：文本（册账 / 待选清单 / 落地回执）
- 配置变量：BOT_MEME_LIBRARY_ENABLED；BOT_MEME_LIBRARY_DIR；BOT_MEME_LIBRARY_DB_PATH
- 可复制示例：表情册；表情册 查重；表情册 入册 3f2a
- 关联回归测试：tests/test_meme_domain_fixes.py
- 总览：【表情册】表情库的册账：表情册 [统计|重扫|查重|入册 <编号前缀>]（待审／审批在「表情库」那面，别在表情册上打）
- 标题：【表情册】数图、认路径、查同名，再挑一行落进人格册

### 教程

【板块介绍】
  表情册是表情库的册账：数图、认路径、查同名，再把挑中的那一行落进
  人格册目录。我只读登记好的册根——册根没配或不在，我就明说缺，不去
  别处翻图，也不自己造目录。总开关 BOT_MEME_LIBRARY_ENABLED；册根与库位
  在 BOT_MEME_LIBRARY_DIR、BOT_MEME_LIBRARY_DB_PATH（管理员写进 .env，改完要重启）。
  册根走的是表情库那枚键，和贴纸池 BOT_STICKER_DIR 是两键两片目录，拿后者顶不了数。
  随机讨一张还是归「偷表情」，本模块管的是册子本身。
【指令与参数】
表情册：作用=摊开册账；参数=无（裸命令走统计那条腿，误触不亏）；内容=册根在不在、每册多少张；意义=先看清家底。
表情册 统计：作用=逐册数图；参数=无；内容=各册张数，以及对不上文件的行；意义=摸底，只读不动盘。
表情册 重扫：作用=把认不出路径的行再认一遍；参数=无；内容=重认的结果；意义=图挪过窝时把它认回来；文件一张都不搬。
表情册 查重：作用=跨册认同名；参数=无；内容=同名不同处、同图不同名的候选；意义=攒重了心里有数，它自己不落地。
表情册 入册 <编号前缀>：作用=把库里那一行落到人格册目录；参数=编号前缀（必填，指库里那一行）；内容=落进哪一册、成没成；意义=这条要动盘——文件会移动，库也跟着改，不点名不落地。
表情库 待审：作用=端出证据不齐、卡在待审档的清单（待审／审批这族命令归「表情库」面，把动词打在表情册上只会折回册面统计）；参数=无；内容=待审队列；意义=只读，一张都不改库。
表情库 审批 通过|拒绝 <编号前缀>：作用=把待审那一行放行入册或驳回（同属「表情库」面）；参数=编号前缀（必填，须唯一命中，0 条或多条都不落子）；内容=落子回执；意义=审核制的唯一写口，没点名就不替管理员决定。
【权限与效果】
  权限=仅管理员。统计、重扫、查重站在读的一侧；入册站在动盘的一侧，
  它会移动文件并改库，所以非点名不落地。待审队列同属读的一侧，
  审批（通过／拒绝）是这一面唯一的写口，同样要指名编号前缀。
【示例】表情册｜表情册 查重｜表情册 入册 3f2a

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 表情册` 为准。

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
天气：帮我查一下杭州天气｜杭州天气怎么样 → 「天气 杭州」。
点歌：来首晴天｜放首歌 晴天｜帮我放一首周杰伦的歌 → 「点歌 …」。
维基：帮我查维基 鸣潮 → 「wiki 鸣潮」；Epic：今天有什么免费游戏 → 「epic」。
历史上的今天：今天历史上发生了什么 → 「历史上的今天」；偷表情：来张表情包 → 「偷表情」。
未命中自然语言意图的文本会正常落入人格聊天，不会报错。
无固定指令：作用=把口语归一成标准命令；参数=自然语言本身；内容=命中后按目标模块回复；意义=零记忆成本。查询类动词：帮我/麻烦/请/查一下/看看/告诉我…
【权限与效果】
  权限=全员。命中后按目标模块的权限与门禁执行。
【示例】帮我查杭州天气｜来首晴天｜今天有什么免费游戏

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 自然语言` 为准。

## 忽略

- 权限：仅管理员
- 触发别名：忽略；ignore
- 能力入口：matcher:IGNORE（空消息静默；未知命令形态回引导）
- 输出形式：按设计静默；未知命令形态回一句 /bot help 引导（60 秒/会话节流）
- 总览：【忽略】哪些消息静默不回、未知命令会引导（排障「为什么不回我」）
- 标题：【忽略】静默路由、沉默原因与未知指令引导

### 教程

【板块介绍】
  「忽略」是路由兜底语义：机器人不回 ≠ 出故障，多数沉默是门禁与
  策略按设计工作。唯一例外：命令形态（/ 开头等）没命中任何能力时，
  会回一句守岸人引导指路 /bot help（60 秒/会话节流）。本模块帮助
  管理员区分「按设计沉默」与「真异常」。
【指令与参数】
空消息/无有效文本 → IGNORE，不回复。
命令形态（/ 开头等）但没命中任何能力 → 回一句守岸人引导，指路 /bot help；同一会话 60 秒内只提醒一次，防刷屏。普通闲聊不受影响。
群聊非命令、非 @点名、非昵称点名 → passive 静默观察；自动接话开启时按概率抽签，且受好感门（≥ 亲近）。
安静时间窗内、限流句数帽超帽、群策略 black1 → 静默拦截（黑名单完全只收不发）。
排障路径：/bot status 看姿态 → /bot why <id> 看单条决策 → 本模块理解沉默语义。
无专属命令：作用=解释沉默与引导；参数=无；内容=空消息静默（按设计），未知命令形态回一句引导；意义=区分按设计沉默与真异常。相关诊断：/bot status、/bot why、/bot route <文本>（route 会直接告诉你这段文本命中哪条路由）。
【权限与效果】
  权限=仅管理员（排障语义）。
【示例】/bot route 今天天气不错 → 显示 chat 路由（正常回复场景）

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 忽略` 为准。

## 决策

- 权限：仅管理员
- 触发别名：决策；决策引擎；decision
- 能力入口：/bot decision
- 网络依赖：纯本地
- 输出形式：文本
- 可复制示例：/bot decision；/bot decision 50
- 关联回归测试：tests/test_decision_trace_persistence.py
- 总览：【决策】影子决策引擎痕迹查询：/bot decision [N]
- 标题：【决策】查看影子决策引擎的路由分歧痕迹

### 教程

【板块介绍】
  影子决策引擎（BOT_DECISION_ENGINE_MODE=shadow）对每条经过管线
  的事件只算不发，与现行 matcher 的裁决做比对。本页把比对痕迹
  读出来给管理员看：分歧集中在哪类路由、引擎与现行差在哪，是
  接管评估（阶段 1+）的核心依据。痕迹经 SQLite 落盘，热缓冲只
  是短程补充，重启后仍可查询历史。
【指令与参数】
/bot decision [N]：作用=查看影子决策引擎最近 N 条痕迹；参数=N（缺省 20，范围 1-100）；内容=时间/路由类别/引擎判定与现行判定/一致或分歧/耗时，自由文本字段打码截断，不含消息原文；意义=评估中央决策引擎接管前的分歧率（痕迹已落盘，重启可查历史）。
【权限与效果】
  权限=仅管理员（普通成员发送会收到拒绝提示）。
  影子模式默认关闭（legacy_only）：模式下无痕迹属预期，不是故障。
【示例】/bot decision ｜ /bot decision 50

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 决策` 为准。

## 紧急信息

- 权限：仅管理员
- 触发别名：紧急信息；预警；地震；震情；待审；emergency；緊急信息；預警
- 能力入口：bot.emergency_info
- 自然语言触发：紧急信息；预警；地震；震情；待审；emergency
- 群聊/私聊差异：查询与审核=管理员；设/退订阅=超级管理员·管理员·本群群主（仅 QQ 侧）；群聊只读已批准条目
- 网络依赖：需要联网
- 输出形式：文本
- 失败兜底：源不可达时明确说拿不到，绝不把「取不到」说成「无预警」
- 配置变量：BOT_EMERGENCY_INFO_ENABLED；BOT_EMERGENCY_INFO_MIN_LEVEL；BOT_EMERGENCY_INFO_SOURCES；BOT_EMERGENCY_INFO_AUTO_APPROVE_SOURCES；BOT_EMERGENCY_INFO_REVIEWER_IDS
- 可复制示例：紧急信息；紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上；紧急信息 订阅 看；紧急信息 退订；紧急信息 待审；紧急信息 审核 <id> 通过
- 关联回归测试：tests/test_emergency_info_core.py；tests/test_emergency_info_sources.py；tests/test_emergency_info_subscriptions.py；tests/test_emergency_info_reachability.py
- 总览：【紧急信息】外部紧急信息聚合（仅管理员）：紧急信息｜紧急信息 订阅 <条件>｜紧急信息 待审｜紧急信息 审核 <id> 通过
- 标题：【紧急信息】外部紧急信息的采集、定级、人工审核与按群订阅投递

### 教程

【板块介绍】
  外部紧急信息（NMC 预警 / GDACS / 公开震情等来源）采集→定级→去重→
  人工审核批准后，才经中央投递闸投出去；查询面只见已批准条目。
  投递目标由「紧急信息 订阅 …」在群里/私聊里现场设立并现读生效，
  条件（地点·警情·等级·半径）不落 .env；.env 的两个名单降级为可选硬推腿。
  作用=聚合外部紧急信息；意义=漏报比误报贵，所以先审再投、再按订阅筛。
【指令与参数】
紧急信息：作用=查看当前已批准的紧急信息与等级；参数=可选 城市/等级；内容=红橙黄蓝四档 + 来源与时效标注（无源不编数）；意义=一眼分清哪些是真在报。
紧急信息 订阅 area=<地名> kinds=<警情词> levels=<P0,P1 或 橙色以上> radius=<km>：作用=给本群（或私聊给自己）设一条投递条件，只推对得上的条目；参数=四项都可选，缺省即不筛该维，半径缺省 200km、只对带坐标的条目（震情类）生效；内容=一个目标只留一条规则，再说一句即改口，写完当轮生效不重启，地名不在气象码表里会当场点名并给相近候选；意义=推什么由群里说了算，不必经 .env 预填名单。
紧急信息 订阅 看：作用=查本目标当前的条件与累计命中次数；参数=无；内容=从没命中过会直说，不让你猜是不是配错了；意义=「配了不生效」这件事必须自己开口。
紧急信息 退订：作用=撤掉本目标这条订阅；参数=无；内容=退订后一条都不再推，重设即恢复；意义=退出只要一句话。
紧急信息 待审：作用=列人工报料的待审队列；参数=可选 条数；内容=仅管理员，pending 条目不参与投递也不参与定级；意义=报料先审后发。
紧急信息 审核 <id> 通过|驳回：作用=裁决一条报料；参数=item id + 通过/驳回；内容=只改 pending，二次裁决直说已被别人裁过；意义=审核留痕可追。
边界（诚实降级）：中央投递闸未装配=照采照查但一条都不投；源未给失效时间就不假装知道有效期；未定级条目不冒充任何颜色、也一律不投；只有地名没有坐标的条目不拿半径硬凑命中（宁漏不误投）；等级≠卡片色值（色走 theme_tokens）。
【权限与效果】查询与审核=管理员（审核人名单 BOT_EMERGENCY_INFO_REVIEWER_IDS，名单空=审核面关闭，缺省拒绝）；
  设/退订阅=超级管理员、管理员或本群群主（仅 QQ 侧；别的平台的号存下来会送错地方，故不收）。
【示例】紧急信息｜紧急信息 订阅 area=湘潭 kinds=暴雨 橙色以上｜紧急信息 订阅 看｜紧急信息 退订｜紧急信息 待审

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 紧急信息` 为准。

## 亲密模式

- 权限：普通用户可用
- 触发别名：亲密模式；亲密档位；intimate；qinmimoshi
- 能力入口：bot.chat（整句「亲密模式 开/深开/关」；关系档子命令见 /bot identity）
- 自然语言触发：亲密模式 开；亲密模式 深开；亲密模式 关
- 群聊/私聊差异：私聊按本人；群聊成员说的只对自己（个人档），管理员拨上去的才是整群钉
- 网络依赖：纯本地
- 输出形式：文本确认（语气与首跳资格的变化，不改内容放行面）
- 配置变量：BOT_CONTENT_ROUTE_ENABLED；BOT_CONTENT_ROUTE_INTIMATE_TTL_MINUTES；BOT_CONTENT_ROUTE_L1_AUTO_ENABLED；BOT_CONTENT_ROUTE_L1_AUTO_MIN_TIER；BOT_CONTENT_ROUTE_GROUP_PER_USER_ENABLED；BOT_CONTENT_ROUTE_GROUP_WHITELIST；BOT_CONTENT_ROUTE_GROUP_BLACKLIST；BOT_CONTENT_ROUTE_PRIVATE_WHITELIST；BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST
- 可复制示例：亲密模式 开；亲密模式 深开；亲密模式 关；/bot identity set-relation 恋人；/bot identity show-relation
- 关联回归测试：tests/test_intimate_tiers_v4.py
- 总览：【亲密模式】整句开关：亲密模式 开|深开|关｜命令开关：/bot intimate on|deep|off|show（不带子命令＝用法＋当前档）｜关系档自助设定：/bot identity set-relation|unset-relation|show-relation
- 标题：【亲密模式】这一阵用什么语气相处，你们自己说（整句开关＋关系档）

### 教程

【板块介绍】
  亲密档=「这一阵用什么语气相处」的会话状态，分深浅两档：浅档只改称呼、
  语气与投入度；深档才允许把首跳换到在册的成人内容通道。档**为什么**成立只
  记一处（runtime/content_route.py 的 pin_source）：本人显式开关、管理员钉、
  内容信号三类有权换模型，Master Love 与好感度自动腿属于「给档不换模型」。
  同一处来源还答第二件事——**这一轮铺不铺开写**：语言／动作／神态／心理／外貌
  五维只授予那三支**人亲手推动**的来源（同文件的 grants_intimate_narration），
  名单派生与好感度自动腿回落到「只用说话回应」那一段。「换模型」「免 TTL 上限」
  「给描写」各立一集，谁也不许拿谁顶数。关系档（恋人/情侣/夫妻/长辈/晚辈/
  家人/挚友/master…）给这一档具体的形状。
【指令与参数】
亲密模式 开（同义：亲密模式开／开启亲密模式／打开亲密模式／亲密模式 on）：作用=把当前会话上到亲密档的**浅档**（只给关系语气，不改默认模型）；参数=无（整句才算命令，句子中间带这几个字不算）；内容=一句守岸人语气的确认；意义=想被更柔软地对待就说一句，不必念名单。
亲密模式 深开（同义：亲密模式 开 深／亲密模式 开 二档／亲密模式 开 grok／二档／深档）：作用=浅档之上再允许把首跳换到在册的成人内容通道（grok 优先）；参数=无（整句才算命令，三条深档判据先于浅档匹配）；内容=深档确认一句；意义=「档成立」与「该换模型」自此分家——要哪种自己说。
亲密模式 关（同义：亲密模式关闭／解除亲密模式／亲密模式 off）：作用=深浅两档一起解除；参数=无；内容=回到平时语气的确认；意义=说完就撤，不粘着。
自动退出：作用=亲密档从**激活那一刻**起 60 分钟后自然退出；参数=BOT_CONTENT_ROUTE_INTIMATE_TTL_MINUTES（.env+重启）；内容=会话活跃不续期、再说一次「开」即重置；意义=不会有哪句话把你永久钉在亲密档上。
好感度自动进浅档：作用=相处到某一档的人不必开口也拿到浅档语气；参数=BOT_CONTENT_ROUTE_L1_AUTO_ENABLED（总闸）/ BOT_CONTENT_ROUTE_L1_AUTO_MIN_TIER（门槛档号，真身 character/affinity.py 的 _ATTITUDE_TIERS）；内容=只给关系语气与放行——不换模型，也不给五维展开描写，与 Master Love 同类；意义=亲密语气不该只发给名单里那两位。两枚改 .env 后要重启（合并层未登记，/bot runtime set 明确拒绝）。
五维展开描写给谁：作用=决定这一轮把场景铺开写，还是只用说话回应；参数=无——不看名单、不看好感度深浅，只看这枚亲密档**是被谁推上去的**；内容=语言／动作／神态／心理／外貌五维（连同呼吸、触感与周遭）只授予人亲手推动的三支：本人显式那句「亲密模式 开／深开」、管理员替全群钉上的那枚、内容信号自己跨了阈；Master Love 名单派生与好感度达档自动只给语气与放行，写的仍是日常那段「只说话」；意义=「进了亲密档」与「有权铺开写」是两件事，判据真身＝content_route 的 grants_intimate_narration，本册不抄第二份成员表。
写多长这一维：作用=说清长度的真身在哪一处、亲密档不另立第二把尺；参数=无；内容=两段场景指令里都没有任何长度口径，唯一那一行长度分档指令仍按你的详略档与本轮问题取值（真身＝chat 能力的 intimate_reply_length_tier 与 REPLY_LENGTH_TIERS），只有拿到展开描写的那一轮才把生效档按秩升一格、封顶详尽，钉过「短一点」的人也至少落在适中；意义=换档只换描写维度，不会一换成亲密档就把你自己钉过的讲法整段盖掉。
/bot identity set-relation <关系>：作用=告诉守岸人你们是什么关系，让这一档有具体的形状；参数=受控词表内的关系或其口语别名（词表与每档语气指令的真身=character/relationships.py，本册零抄录）；内容=已记下的档号；意义=同一句「亲密模式 开」，关系不同语气就该不同；词表外的值不落档也不清档，并把整张词表回给你。
/bot identity unset-relation：作用=只清关系档那一列；参数=无；内容=已清除（带原先记的档号）；意义=称谓偏好与性别自述不受牵连——这与 unset-name 的整行删除是两件事。
/bot identity show-relation：作用=看自己当前的关系档；参数=无；内容=档号，或明说「没设定过，按相处深浅自然来」；意义=先核对再改，不靠猜。
权限=全员：任何人对自己说一句就生效，无需管理员。群聊里成员说的只对自己（个人档），要把整群钉上得管理员；群聊整面还受黑白名单约束（白名单为空=整群关闭，绝不猜群；黑名单永远赢）。
群聊里看不看得见：作用=诚实交代出站那一道闸；参数=无；内容=群聊出站比私聊多一道审查（domains/render/reviewer.py 的 _PUBLIC_OUTPUT_UNSAFE，只在群聊那一支跑），正文里一旦出现内容分级词或类别标签名就**整条拦下不发**，亲密段因此自带一句「别替这段文字贴类别标签」的护栏；意义=本册不承诺铺开写的场景在群里一定出得来，要让它被看见，私聊说一句更稳。
/bot intimate on（同义：open／l1）：作用=用命令面把当前会话上到亲密档的**浅档**，与整句「亲密模式 开」同效、只给关系语气不改默认模型；参数=子命令（三词同义，大小写不敏感、首尾空白容忍；认不出的一律不受理，绝不拿错字悄悄顶成"开"）；内容=一句守岸人语气的确认；意义=习惯敲命令的人不必迁就整句说法，两条路各说各的、档位口径一致。
/bot intimate deep（同义：deeper／l2）：作用=浅档之上再允许把首跳换到在册的成人内容通道，与整句「亲密模式 深开」同效；参数=子命令（三词同义，大小写不敏感）；内容=深档确认一句；意义=「档成立」与「该换通道」分家这件事，命令面与整句面同判据。
/bot intimate off（同义：close／unset）：作用=把浅深两档一起放下、回到平时语气，与整句「亲密模式 关」同效；参数=子命令（三词同义）；内容=回到平时这样聊的确认；意义=撤档一句话就撤干净，不粘着。
/bot intimate show：作用=只看现在是什么档、什么都不改（只读查询，既不上钉也不解钉）；参数=子命令 show；内容=档位、由谁拨上、五维细节描写开没开、当前生效的详略档名、作用域、这一处准不准入六格读数；意义=先核对再决定要不要改，不靠猜。这一支不回内部来源串、不回模型名、也不回字数——那几样本就不该从这页漏出去。
/bot intimate（不带子命令）：作用=自己交出这份用法并附当前档位读数，末尾指路「/bot help 亲密模式」；参数=无；内容=用法清单加当前档，不撞帮助兜底；意义=裸敲一条命令既不会被静默当成"开"，也不会掉进无关的帮助页。
硬线：内容放行面不因关系档而改变，仍由会话门 explicit_allowed_for_session 判；六条硬线任何关系、任何开关、任何设定都压不过（security/content_safety.py）。
开关不受理时：总闸关／本会话没准入／群里普通成员但个人档总闸关——命令面没有正文可落回，仍会老实说一句"这一处还没放开"，不静默、不假装生效。
【取值范围】
  档位=浅(l1)/深(l2)；退出=一句「亲密模式 关」或 60 分钟 TTL 自然退出（按
  激活时刻起算、活跃不续期、重开即重置）；显式钉与管理员钉不再被第二道
  max_ttl 悄悄截掉（2026-09-24 裁定 R4 A）。关系档取值由受控词表决定，
  词表外一律不落档；同时命中两档按歧义不记录，不替谁编一个方向。
  描写维度=拿到授予的那一轮五维齐，没拿到的轮次与日常同样只说话；长度这一维
  不由本档表态——唯一真身＝那一行长度分档指令（由详略档与本轮问题共同取值）。
【权限与效果】
  权限=全员（任何人对自己拨）。会话准入门链：总闸 BOT_CONTENT_ROUTE_ENABLED
  → 私聊/群聊黑白名单（私聊白名单空=放开、群聊白名单空=整群关闭，刻意不对称；
  黑名单永远赢）→ 群内成员个人档总闸 BOT_CONTENT_ROUTE_GROUP_PER_USER_ENABLED。
  只改变称呼与投入度，不推翻任何既有的身份与称谓事实；六条硬线压不过。
  出站面：群聊比私聊多一道审查（只在群聊那一支跑），命中内容标签词即整条不发，
  故本册不承诺铺开写的场景在群里一定出得来；私聊不走这一支。
【示例】亲密模式 开｜亲密模式 深开｜亲密模式 关｜/bot identity set-relation 恋人

### 帮助页一致性要求

- 本模块的实时帮助以 `/bot help 亲密模式` 为准。

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
  - commodities | bot.commodities | 商品行情
  - bond | bot.bond | 国债收益率
  - northbound | bot.northbound | 北向资金
  - market | bot.market | 行情
  - fx | bot.fx | 汇率
  - stocks | bot.stocks | 个股行情
  - eat | bot.eat | 吃什么
  - divination | bot.divination | 占卜
  - news | bot.news | 快报
  - randpic | bot.randpic | 随机图
  - reminder | bot.reminder | 提醒
  - affinity | bot.affinity | 好感度
  - tts | bot.tts | 语音
  - moegirl_question | bot.moegirl | 萌娘百科
  - natural_command | bot.natural_command | 自然语言
  - content | bot.content | 链接
  - chat | bot.chat | 聊天
  - media_archive | bot.media_archive | 媒体归档
  - host_state | bot.host_state | 宿主机状态
  - consent | bot.consent | 书面同意
  - daily_assist | bot.daily_assist | 收件箱
  - emergency_info | bot.emergency_info | 紧急信息
  - group_info | bot.group_info | 群信息

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
  - capability.group_info | active | 群信息
  - capability.host_state | active | 宿主机状态
  - capability.consent | active | 书面同意
  - capability.daily_assist | active | 收件箱
  - capability.tts | active | 语音
  - capability.emotion | active | 内部：心情引擎，经上下文注入，不占文本路由
  - capability.gscore | reserved | 预留：GsCore 侧指令统一进入基层路由，尚未实现

### 内部路由能力（无独立帮助模块）

- `bot.stocks`：个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）
- `bot.fx`：汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）
- `bot.commodities`：商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 domains/finance/capabilities/market.py；帮助页 topic=商品行情）
- `bot.bond`：国债收益率（国债/期限利差/收益率曲线，触发词见 domains/finance/capabilities/market.py；帮助页 topic=国债收益率）
- `bot.northbound`：北向资金（北向资金/沪股通/深股通成交总额，触发词见 domains/finance/capabilities/market.py；帮助页 topic=北向资金）
