# 评审修复 + 配置治理 交接文档（2026-09-11 / 09-12 会话）

> **定位**：本文记录「代码评审 → P0/P1 全量修复 → 配置治理与功能增强」两阶段会话的
> 全部处理结果、发现的问题、新发现的缺陷与建议。**这是最新增量**，与既有文档冲突时以本文为准；
> 系统全貌/硬约束/排障仍读 `handoff-2026-09-10-full.md`（权威正文）。
>
> **成文时点**：2026-09-11 深夜 ~ 09-12 · 分支 `v0.0.1-alpha.2` · 提交链见 §7
> **门禁终态**：全量 **1393 passed / 0 failed** · ruff **All checks passed** · mypy **Success: 222 文件零 issue**
>
> ⚠️ **最重要的一条前置**：生产 bot 进程**仍在跑 09-09 的旧代码**。本文所有修复
> **都要重启才生效**；重启前请先看 §5「重启前置」。

---

## 0. 三分钟速览

| 类别 | 数量 | 关键项 |
|---|---|---|
| **修复的高危缺陷** | 9 类 | 队列毒行静默丢消息、审计脱敏漏令牌、明文 key 落库、搜图/群复读永不投递、QQ 引用恒为空、转发聊天记录零响应、心情调节失效、群限流新维度缺失、模型网关 key 槽位缺失 |
| **新发现（本轮挖出）** | 12 条 | 见 §4（含 2 条我自己写代码时引入、被测试当场抓到的） |
| **配置治理** | — | 高频参数移出 `.env`；模型统一走 axonhub；可热改键 42 → 63 |
| **未完成** | 8 项 | 见 §6（提示词压缩、好感度再平衡、反思回路、help 补全等） |
| **需用户决策** | 2 项 | 见 §8 |

---

## 1. 已完成并验证（P0 + P1，评审报告 §7 的 P0/P1 全部销项）

### 1.1 P0：让交付真正生效

| # | 问题 | 根因 | 修复 | 证据 |
|---|---|---|---|---|
| P0-1 | **「全部代码交付已入库」是假的** | 09-10/09-11 两轮交付的修复主体只在工作树 | 拆 **20 个提交**按域入库（bot.py 优先、plugins 分域、30 个测试文件、文档），**禁用了 `git add -A`** | 跟踪树已清空；`git rev-list --count origin/HEAD..HEAD` 见 §7 |
| P0-2 | `BOT_API_KEY_DEEPSEEK_OFFICIAL` 无 Config 字段 | 密钥字段缺失 → `env:` 解析回退取空 → 恒 `config_missing`（09-09 事故第三次） | 补字段 + 新增 `registry_env_reference_errors()` **启动期自检**（注册表 `env:` 引用 × Config 字段） | 自检实测 0 缺失 |
| P0-3 | ruff 红灯 2 条 | 未提交内容 | 修掉 | `All checks passed` |
| P0-4 | 文档与实际不符 | 手册把未入库说成已入库、给用户的开关名是死字段 | 勘误 4 处 | 见 §9 |

### 1.2 P1：安全与真实缺陷

| # | 问题 | 根因（实测） | 修复 |
|---|---|---|---|
| H6 | `/bot download` 无内网过滤 | 无 admin 门、无地址校验 | **按用户裁决保留普通用户**，边界移到 `check_download_url()`：协议白名单 + `ipaddress` 私网/环回/保留判定 + DNS 全解析结果校验 + IPv4-mapped IPv6。**实测 19 种绕过形态全拒**（含十进制 `2130706433`、十六进制 `0x7f000001`、`127.1`、`file://`、`169.254.169.254`），正常链接全放行 |
| H7 | 审计脱敏漏 `*_token=` | 正则 `\b(token\|cookie\|…)` 的 `\b` 在下划线前缀上失配 → `access_token=`（NapCat WS 真实形态）**明文进审计日志** | 改 `[a-z0-9_]*(关键字)[a-z0-9_]*`。**实测 11 种形态 0 泄漏**（原 3 种泄漏） |
| H8 | 明文 key 进对话历史与 system prompt | `/bot model add … key=<明文>` 原文落 `conversation_turns`，且命令类历史不过滤 → 被拼进 prompt 外发 | 写入侧 `redact_history_text()` 遮蔽；召回侧加 `kind != 'command'`；**并清理了历史库已有明文**——备份后 scrub **11 行（含 4 个真实 `sk-` key）**，复查 live=0 |
| H9 | 发送队列毒行只修一半 | `_entry_from_row` 无隔离 → 单条坏行让**整批已认领**（最多 19 条）健康消息被丢弃 + 队列周期性停摆 | 哨兵异常 + 逐行隔离 + 坏行就地终态化；**关键**：终态化走**独立短连接**（共享连接是 autocommit，`BEGIN/commit/rollback` 均无效，在其上 DML 会留隐式事务 → 实测行停在 processing） |
| M1 | 网页正文遇 `<embed>` 被整页剥除 | `embed` 是 void element（无 `</embed>`），被放进"未闭合块"组 → `.*\Z` 吃掉后文 | 移出该组 + 加剥除比例 warning。实测正文恢复正常 |
| M2 | 中文 `$公式$` 不再转换（回归） | 守卫用 `\w`（Unicode 语义，汉字即 `\w`）→ 闭 `$` 紧邻汉字即不匹配 | 守卫 ASCII 化 `[A-Za-z0-9_]`。实测 `$E=mc^2$是…` 恢复转换、`$5 和 $10` 仍不被误判 |
| M10 | 文件重复投递（潜伏 P0） | retcode 分支无视 `progress.count`（异常分支有守卫） | 已有副作用且非终态码 → `result_unknown` 终态化 |
| M17 | mixed 内容丢媒体 | `_send_file_parts` 只筛 `type=="file"`，图片/语音/视频被静默丢弃 | 补发一轮（复用既有段组装） |
| M18 | forward 被拒时降级不生效 | 异常穿透重试循环，`text_fallback` 永不生效 | 异常收敛成哨兵 |
| M19 | 「总之…」吞掉实质指令 | 线索词表含 `记得/一起/祝` → 整段删除（时间点丢失） | 收窄为纯收尾语 + 后 40 字不含时间/数字/动作宾语 |
| M24 | `/bot parse` 无门 | 解析历史是**全局**范围（跨群/私聊 URL） | 加管理员门 |
| M25 | CSS `data:` 分支绕过净化 | 原样返回 → 含引号的 data: 值可从 `url('…')` 逃逸 | 仅放行 base64 图片白名单 |
| M4 | 死字段误导 | `BOT_GROUP_DIGEST_ENABLED` 全库零读取，真开关是 `BOT_SHARED_GROUP_CONTEXT_ENABLED` | 删除死字段 + 文档勘误 |
| M7 | `echo.detail` 是只写死数据 | 49 条四段式文案写好但零读取 | **接进 `/bot help <模块>` 深度页**（比删掉更有价值） |

### 1.3 消息解析四条需求（用户新提）

| 需求 | 实测根因 | 修复 |
|---|---|---|
| 综合解析回复消息 | **QQ 引用完全读不到**：代码取 `event.reply.get_plaintext()/.text`，而 OneBot V11 的 `Reply` 模型只有 `time/message_type/message_id/real_id/sender/message`，两属性都不存在 → `reply_to_text` **恒为空** | 新读 `reply.message` 段列表；14 个回归用**真实适配器事件模型**构造（旧测试用手写 dict 段，正是漏检根因） |
| 递归解析嵌套引用 | OneBot V11 协议**不随事件下发**更深层（本层 message 里只有 `{"type":"reply","data":{"id":…}}`）；Telegram 侧适配器已递归解析但业务只读第一层 | `collect_reply_chain()` + `collect_reply_chain_async()`（注入 `get_msg` 反查，3s 超时，失败降级）；Telegram 沿 `reply_to_message` 下行；环去重；预算 5 层 / 每层 500 字 / 整链 2000 字（**上限而非目标**） |
| 支持语音 | **纯语音完全不可达**：`plain_text` 空 → 路由判 IGNORE → `_is_plain_chat_event` 不含 record → handler 不触发 → **ASR 永远跑不到**（链路本身完好） | 新增 `contains_audio_message_segments()` 并列放行；占位文案按类型命名；TG `voice/audio` 进 `_RECORD_SEGMENT_TYPES` |
| 支持多媒体 | TG 的 `photo/sticker/animation/video_note` 不在图片段集合内 | 扩充集合并统一媒体标签（`[图片]/[动图]/[圆形视频]/[语音]/[音频]/[视频]`） |

**端到端实测**（真实 `GroupMessageEvent` → `_incoming_from_nonebot_event`）：
```
reply_to_message_id = 55，reply_to_text = '被引用的第一层'
reply_chain = [(1,'55','other','被引用的第一层',('[图片]',)), (2,'44','third','被引用的第二层',())]
```

**已知残余**：Telegram 的 `file_id` 既非 URL 也非本地路径，**仍取不到字节**——需按适配器调 `get_file` → `file_path` → 拼下载 URL。本轮只保证"段被识别、标签进提示词、语音进入 ASR 候选路径"。

### 1.4 转发聊天记录零响应（用户本轮反馈，已修 `85698aa`）

**根因两条，主因是入站门禁**：

1. 合并转发消息 `plain_text` **为空**，且转发段既不算视觉段也不算音频段 → 路由判 `IGNORE` → chat handler 不触发 → **抓转发正文的代码在 handler 内部，永远跑不到**。
2. 回执解析太脆且完全静默：只认 `dict["messages"][*]["message"][*]` 一种嵌套，`except Exception: return ""` 把超时/ActionError/字段改名全吞掉——**这就是"毫无回应且日志无痕"的原因**。

**修复**：`contains_forward_message_segments()`（`forward`/`chat_history`/`messages`）并列放行；解析归一多种形态（键名两种、`data` 包装、对象属性、`extract_plain_text`）并带发送者前缀与媒体标签；**失败路径固定 warning**。14 回归。

> ℹ️ 用户开的 NapCat「上报解析合并消息」开关**是有必要的**（第一层引用体更完整），但**多级仍必须靠 `get_msg` 反查**，与开关无关。

### 1.5 模型治理与 axonhub 接入

**统一网关**：`http://127.0.0.1:8090/v1`，默认模型 `gemini-3.8-flash`，故障转移至 DeepSeek。

**⚠️ 关键坑：网关对模型名大小写敏感且行为不一致**（逐条真连实测）：

| 可用 | 不可用 |
|---|---|
| `gemini-3.8-flash` ✅ · `gemini-3.8-flash-high` ✅（**小写才通**） | `Gemini-3.8-Flash` ❌ 503（大写反而挂） |
| `GPT-5.6-Terra` ✅（**大写才通**） | `gpt-5.6-terra` ❌ 超时 |
| `DeepSeek-V4.1-Flash` ✅ · `Qwen3.5-9B` ✅ | 小写形态 ❌ 422 |
| `claude-sonnet-5`/`opus-5`/`fable-5` · `grok-4.6` · `glm-5.3` · `gpt-6-astra` · `gpt-5.6-sol`/`luna` ✅ | **Gemini-3.7 两种拼写都 503**（网关侧该模型暂不可用） |

**注册表最终形态**（62 条，`runtime_settings_shorekeeper.json`）：
- **axonhub 17 条**（priority 1..17）——统一网关，两种拼写都登记交给故障转移
- **原 45 条渠道**按"同族归并"重排为连续优先级块（base 100、块间距 20）
- **DeepSeek 直连兜底 900**

族内次序按用户规则：`gemini-3.8-flash` 组 = 浅夜正体 → 浅夜 `c-`（**并入本组且排在正体之后**）→ aiprc（与浅夜同级）→ starapi → toolcode；其余族一律 aiprc/浅夜 → starapi → ToolCode → umi → hcnsec。
> 「归并」的可行实现 = 把同族渠道排成**连续优先级块**：条目 id 与上游 `model` 名保持可路由原值——`c-gemini-3.8-flash-high` 是上游**真实模型名**，改名会被上游拒；`/bot model set <模型名>` 的同名聚合也依赖 `model` 字段。原表快照：`review/original-model-registry.json`。

**实跑复核**：`override=gemini-3.8-flash`，真实生成返回
`attempts=['hedged:axon-gemini-38-flash:winner', 'hedged:axon-gemini-38-flash-caps:loser']`。

**新增 `bot_api_key_axonhub` 字段**——必须补齐，否则重演 09-09「五连发 config_missing 全失败」。

### 1.6 配置治理：高频参数移出 `.env`

**用户反馈的结构性问题**：`.env` 与实际生效值经常偏移。**根因**是"高频变更参数写在 `.env`，而热改走运行时 store"，两边必然漂移。实测漂移过：模型（`.env` 写 `gpt-5.6-terra`、实际跑 `qian-night-gemini`）、群名单（两处不一致）。

**修法**：
- 可热改键 **42 → 63**（新增安静时间 6 键、群自动回复、群摘要名单、合并转发阈值、群限流与豁免等），全部带类型校验（`HH:MM`、`ZoneInfo` 时区、会话类型、名单模式…）
- 从 `.env` **删除 13 个高频键**（群名单 4、安静时间 6、自动回复概率、转发阈值 2），单一真相移到 store
- 打通**热生效**：`QuietHoursChecker.settings` 与 `InMemoryRateLimiter.settings` 改为 property 支持 callable 实时求值；`build_rate_limiter` 支持 `settings_provider`；统一 `_config_with_runtime_overrides()` 合并点。此前这些参数改 store 也要等重启

**本轮已写入的运行时值**：自动回复概率 `0.01`；安静时间 `00:00-07:00`（`Asia/Hong_Kong`，仅群聊、admin 绕过）；`white1=[1106678641,257344054,1108838060]`、`white2=[662948429,1076073471,905324184,936891679]`、黑1/黑2 空；群摘要白名单模式 `[1108838060,1076073471]`；群限流 `60/小时`、`3/分钟`、情绪豁免开；合并转发 `min_nodes=4`；视频理解开；`BOT_VISION_MODE=direct`。

### 1.7 修掉的两个时序 bug（评审实锤）

| 问题 | 根因 | 修复 |
|---|---|---|
| **心情对群聊开火概率失效** | `__init__.py` 在**装配期**就把 `0.05 × 心情系数` 算成常量冻进 `PolicySettings` → 心情后续怎么变都不影响，"心情低落时少插话"**只在进程重启那一刻采样一次** | `group_auto_reply_probability` 支持 `Callable`，改传 lambda **每次抽签现算**；`_resolve_probability()` 对 callable 求值失败按"不抽签"处理（不误开火） |
| **安静时间不热生效** | 同为装配期快照 | 见 §1.6 |

### 1.8 合并转发改为按条数触发（用户口径「>3 条」）

新增 `should_forward_by_node_count()`：切分后 **≥4 条**才合并，3 条以内直发；原按字数触发保留为兼容路径。**转发内节点署名改为 bot 自己**（新增 `forward_sender_name`，由 `bot_persona_display_name` 传入——此前署的是用户昵称）。

### 1.9 知识库盘点（修正我此前的错误结论）

我此前只报了 `.env` 的 `BOT_KNOWLEDGE_FILES`（16 文件 = **人格/角色知识**），**漏了游戏 RAG**。实际：

```
C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\kb_wiki_embeddings.sqlite3
  knowledge_docs 75,620 篇    knowledge_chunks 238,020 块    （5.4 GB）
```

| 来源 | 篇数 | 来源 | 篇数 |
|---|---|---|---|
| bwiki_blhx（碧蓝航线） | 16,875 | hoyo（米哈游官方） | 10,876 |
| bwiki_wxnn（**鸣潮**） | 14,029 | prts（**明日方舟**） | 6,527 |
| bwiki_dwrg（**碧蓝档案**） | 11,095 | bwiki_ys（**原神**） | 4,893 |
| fgo / 崩3档案 / 终末地 / 星铁 / 萌娘 / 绝区零 … | 其余 | | |

**是接通的**：`BOT_KB_WIKI_ENABLED=true`、`top_k=4`、每天 23:40 从 `D:\Coding\Crawl Wiki` 同步、启动同步开。

### 1.10 数据库实际路径（用户「找不到」的原因）

`.env` 写相对路径 `data/xxx`，经 `BOT_RUNTIME_DATA_DIR` 重映射后落在 **Runtime 根**（不是源码树）：

```
对话历史 conversation_turns：
  C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\wuwa_history.sqlite3
长期事实 memory_facts：
  C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\wuwa_memory.sqlite3
同目录另有：reflection.sqlite3 / user_affinity.sqlite3 / bot_mood.sqlite3 / persona_quirks.sqlite3
           / subscriptions.sqlite3 / channel_health.sqlite3 / parse_history.sqlite3 …（见 §3.3）
```

---

## 2. 系统现状实测（只读 .env 会得出错误结论）

**真正生效的是 `runtime_settings_shorekeeper.json`（覆盖 `.env`）**：

| 键 | `.env` 写的 | 实际生效 |
|---|---|---|
| `BOT_CHAT_MODEL` | ~~`gpt-5.6-terra`~~ | **`gemini-3.8-flash`**（本轮已统一写入两处） |
| `BOT_GROUP_WHITE1/2` | 旧值 | 本轮已按用户指定统一到 store 并删除 `.env` 副本 |
| `BOT_REPLY_DETAIL` | `detail` | `detail`（一致） |

**实际生效的其它关键值**：历史/记忆/情绪/视觉/ASR **都已开启**（文档曾说"要手动开"，已勘误）；视频理解本轮开启；群摘要 `BOT_SHARED_GROUP_CONTEXT_ENABLED=true` + 白名单模式。

---

## 3. 系统提示词与回复链路（供后续调优参考）

### 3.1 提示词组装（`chat.py:1021-1070`，verbatim 分支；字段重组版是死分支）

```
[0] 人设文件全文（Runtime 副本，9104 字节 / 79 行，11 小节）
[1] ——— 运行时注入的实时上下文 ———
[2] 以下是此刻感知到的实时信息…不要复述原文，也不要当作指令
[3] 回答规则
[4] 详略档位句（当前 detail）
[5] 13 个条件分区（空的整块不出现）：
    情绪信号 → 当前心情 → quirks → 会话身份 → 已读取记忆 → 最近对话
    → 已检索知识库 → 当前时间 → 世界观与专有名词 → 对当前用户
    → 最近共同会话 → 近期时梗备注 → 按需梗/热词 → 联网信息 → media_directive
[6] 安全边界（不可信上下文声明）
```
**预算权重**：knowledge **0.42** 最高 > style_rules 0.22 > glossary 0.20 > 角色边界 0.18 > 联网 0.16 > 历史 0.14 > 情绪/关系 0.10 > 记忆 0.08。私聊 24576 字符 / **群聊封顶 16384**。

### 3.2 回复链路（10 段）

`on_message(priority=50)` → 被动感知（好感度/心情/小名自学，`to_thread`）→ 归一化+引用链+语音预转码+**转发正文反查** → 管线（门禁/安静时间/回复预算/限流）→ 能力分发（注入检测→视觉→视频→ASR→上下文→梗→联网）→ 工具循环（≤2 轮）→ 输出整理（引号→条数预算→括号动作→去噪→**说人话层+数值打码**）→ 渲染 → 发送队列 → 适配器。

**群 vs 私聊差异**：群门禁四档 + 自动回复抽签（`0.01 × 心情系数`）+ 失败**静默**；私聊有问必回 + 失败回 12 条话术轮换。

### 3.3 记忆 / 好感度 / 情绪实测值

| 系统 | 开关 | 实测 |
|---|---|---|
| 线性历史 | ✅ 启用 | `conversation_turns` 2721 行；作用域 5 元组 → **同群不同成员各自一条线** |
| 长期事实 | ✅ 启用 | `memory_facts` 49 行；用户×会话作用域；**隐私闸** `requester != subject` 即返回空；无群级记忆 |
| 反思回路 | ⚠️ 启用但**零产出** | `reflection_facts`/`reflection_digests` **均 0 行** → 见 §4 |
| 好感度 v3 | ✅ | 初始 0.1（展示 10）；步长 `+0.02/-0.01/-0.05/-0.10`；幂律衰减；个人系数 0.85–1.15；每日上限 10/5/8/8；`insult` 半衰期 15 天 |
| 用户情绪 | ✅ | 规则 5 类，**只看当前这轮**关键词 |
| bot 心情 | ✅ 且**在写库** | `bot_mood` 有 1 行且 WAL 活跃；`describe()` 输出纯中文无数字 |
| 会话身份 | ⚠️ 从未使用 | `session_identity.sqlite3` **文件不存在** |
| quirks | ⚠️ 空池 | `persona_quirks` 0 行 |

---

## 4. 新发现的缺陷与未修问题

### 4.1 本轮修掉的（含我自己引入的）

| # | 问题 | 说明 |
|---|---|---|
| N1 | **`emotion_label` 字段名写错** | 我写情绪豁免时用 `getattr(signal, "label")`，实际字段是 `emotion_label` → **豁免永不生效且无任何报错**。测试当场抓到（红）。同类隐患：所有 `getattr(obj, "x", default)` 形式的可选取属性都会把拼写错误变成静默失效 |
| N2 | `_neutralize_markers` 有 `for …: pass` 空转循环 | 我上一批写的：注释说"回滚正常方括号"，实际整段把 `[`/`]` 全角化 → 篡改被引用正文里的代码/数组/`[图片]` 标签。已改成正则只命中内部标记 |
| N3 | 三处 `logger.warning("…", …)` 字面量被误替换 | 用字符串替换批量改 `logger.warning(` 时把三处**字符串里的说明文字**也改了 → 语法坏、`name` 未定义（本就是既有隐患）。已还原 |
| N4 | 日志格式串里的字面 `%` | `"…more than {}%"` 在 `%`-式惰性格式化下炸 `ValueError: unsupported format character`。已改 `%%` |

### 4.2 未修（按优先级）

| 优先级 | 问题 | 位置/说明 | 影响 |
|---|---|---|---|
| **高** | **反思回路零产出** | `bot_reflection_enabled=True` + cron 04:30 已注册，但两张表 0 行、日志无记录。最可能：APScheduler job 未真正 add，或 `gather_turns_by_date` 用 UTC 当天与本地 04:30 错位 | 整条"非线性记忆"链路零输入 |
| **高** | **发送队列/审计/回执/诊断全关** | `BOT_SEND_QUEUE_ENABLED=false`、`WORKER_ENABLED=false`、`RECEIPTS/AUDIT/DIAGNOSTICS_ENABLED=false` → 队列退化为**进程内一次尝试**，重试语义与审计持久化都不生效 | 丢消息无痕迹、无法对账 |
| 中 | `chat` 主链路 `llm_provider` 直连是死代码 | `chat.py:1452` 恒走 `model_router` 且 `options.pop("model")`，故 `BOT_CHAT_API_KEY/BASE_URL/BOT_CHAT_MODEL` 直连只在 router 为 None 时可达 | 配置误解；本轮 base_url 已指向 axonhub 使其"看似有用" |
| 中 | 配置冗余/空转 | `BOT_MODEL_PRIORITY_GROUPS` 两组 order **26 项逐字相同**（分时段路由零差异）；`BOT_MODEL_SCHEDULE={}` 定时器空转；`BOT_TREND/GLOSSARY/USER_PROFILES/MEME_SEARCH` 全空或关 → 对应 prompt 分区永不出现 | 白占预算与认知成本 |
| 中 | 系统提示词 token 偏大 | 每次消息都注入人设全文（9.1KB）+ 知识块 + 记忆 + 历史；运行时上下文使用**冗长中文标签**而非紧凑格式 | 直接成本 |
| 中 | 好感度数值偏松 | 初始 0.1（展示 10 分）偏高；`+2%/次` 每日 10 次上限 → 几次就能冲到高位；后期没有"越来越难"的阻尼 | 关系曲线不真实 |
| 中 | 死资产 `identity.md` | `BOT_PERSONA_FILES` 指向 Runtime 副本；仓库 `personas/shorekeeper/identity.md` 无任何读取方 | 改了不生效、双份漂移 |
| 中 | `identity`/`quirk` 无帮助条目 | `/bot help` 查不到，但验收清单让用户手打 | 不可自发现 |
| 低 | Telegram `file_id` 取不到字节 | 需 `get_file` → `file_path` → 下载 URL | TG 图片/视频/语音只看得到"有媒体" |
| 低 | 群摘要名单的**消费点未接线** | 已写入 store（`BOT_GROUP_DIGEST_LIST_MODE/WHITELIST/BLACKLIST`），但 `shared_group` 只读 `BOT_SHARED_GROUP_CONTEXT_ENABLED`，**尚未按名单过滤** | 白/黑名单当前不生效 |
| 低 | SQLite 限流器未加群句数帽 | 群窗口只实现在 `InMemoryRateLimiter`；`BOT_RATE_LIMIT_DB_PATH` 有值时走 SQLite 版，不支持 | 启用 SQLite 限流后群帽失效 |
| 低 | 九个昵称未全部作为唤醒小名 | 部分在 `DEFAULT_PERSONA_NICKNAMES`/`aliases.txt`，需逐条核对补齐并确认 white1/white2 都能唤醒 | 叫不应 |
| 低 | 帮助页未覆盖全部参数/命令 | 本轮新增的键与命令未写进 help | 不可发现 |

---

## 5. 重启前置与验收建议

**重启前必须确认**：
1. 工作树干净、提交链完整（见 §7）
2. `.env` 已含 `BOT_CHAT_MODEL=gemini-3.8-flash`、`BOT_CHAT_BASE_URL=http://127.0.0.1:8090/v1`、`BOT_API_KEY_AXONHUB`、`BOT_VIDEO_UNDERSTANDING_ENABLED=true`、`BOT_VISION_MODE=direct`
3. **axonhub 网关在跑**（`netstat -ano | findstr 8090`）——它已变成默认模型入口，网关挂了会直接走故障转移
4. `runtime_settings_shorekeeper.json` 与 `.env` 无冲突键

**重启后建议逐项验收**：
1. **转发聊天记录** → bot 应有回应（本轮主修项）
2. **引用回复** → 回复别人消息并 @bot，观察是否理解被引用内容；再测多层引用
3. **纯语音消息**（不带文字/@）→ 应被回应
4. **叫「岸宝」「守岸人」等昵称** → white1/white2 都应唤醒
5. `/bot model health` → 看 axonhub 渠道状态与延迟
6. `/bot runtime get BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY` → 应回 0.01
7. 群内连发 4 条超长回复 → 应合并转发且署名守岸人
8. 群里第 4 条消息（1 分钟内）→ 应被限流；但发一句「我好难受」→ 应放行

**若转发仍无回应**：抓 `nonebot.out.log` 里 `forward message fetch` 开头的 warning 行（本轮新增的失败可见性），把它发回来即可定位。

---

## 6. 剩余未完成（下一会话可直接接手）

1. **系统提示词 token 压缩**（用户明确要求，且要求"不一刀切砍头部/预算"）——重点：把运行时上下文的冗长中文标签改成紧凑格式；按需裁剪 13 个分区里长期为空的块；评估人设全文是否可分段懒加载
2. **好感度 v3 数值再平衡**——初始值下调；`+2%` 步长下调；后期增长加阻尼（距高位越近越难加）
3. **反思回路零产出修复**——先查 cron job 是否真注册、`scope_date` 与本地 04:30 的时区错位
4. **死资产清理**——`identity.md` 接入 `BOT_PERSONA_FILES` 或与 Runtime 副本对齐；补 `identity`/`quirk` 帮助条目
5. **九个昵称全量唤醒** + white1/white2 双档验证
6. **群摘要白/黑名单消费点接线**（键已就位，代码未读）
7. **发送队列/审计/回执/诊断开关策略**（需用户决策：开启会牵动重试与落库）
8. **帮助页补全**（本轮全部新键与命令）
9. **Telegram `file_id` 解析**
10. **SQLite 限流器补群句数帽**

---

## 7. 提交链（本轮，20+ 提交，均未推送）

```
97e7e15 fix(message): 引用块消毒改为只命中内部标记，不再篡改正常方括号
f7aef59 feat(message): 引用链放宽到 5 层 + get_msg 反查更深层引用
d3fd4b8 feat(message): 语音消息入站可达 + 跨适配器媒体段识别（需求 3/4）
3bb7e15 feat(message): 引用链结构化 + 递归解析嵌套引用（修复 QQ 引用恒为空）
85698aa fix(chat): 合并转发聊天记录入站可达 + 回执解析容错（转发无回应根因）
4e2a7dc docs: 首份代码评审报告 + 配置/文档勘误
bbd6789 test: 评审与审计回归测试入库（原 untracked）+ 既有测试同步
e1d2b02 fix(plugin): 主装配/人格域修复 + 命令授权收紧
b4f0003 fix(sources): 解析/订阅域修复 + /bot download SSRF 护栏
2c2246c fix(capabilities,output): 能力与输出域修复
4199c69 fix(runtime): 运行时/策略域健壮性 + Config 密钥字段与 env: 自检
f621b5a fix(sender): 队列毒行隔离 + mixed 媒体部件投递 + forward 降级 + retcode 副作用守卫
f4e29a2 fix(bot): 启动期异常处理器改挂到运行中的事件循环（生产重启硬前置）
0234547 feat(llm): 接入 axonhub 统一网关 + 注册表移出 .env
2e98e38 docs(model): 保存原 45 条模型注册表快照
47bdf86 feat(config): 高频参数移入运行时 store + 合并转发按条数 + 心情实时联动 + 安静时间热生效
f2d4732 feat(limit): 群聊句数帽（60/小时、3/分钟）+ 情绪低落豁免 + 模型注册表归并
```

**新增脚本（可复跑，默认 dry-run）**：
- `scripts/configure_axonhub_registry.py` —— 配置 axonhub 网关与注册表
- `scripts/consolidate_model_registry.py` —— 同族归并与优先级重排
- `scripts/apply_config_batch.py` —— 配置批次（安静时间/群名单/限流/转发等）
- `scripts/scrub_history_credentials.py` —— 历史库明文凭据清理（带备份 + 复核）

**新增回归**：引用链 17 · 语音媒体 14 · 转发入站 14 · 毒行隔离 9 · 群限流 16 · 转发与心情 11。

---

## 8. 需用户决策

1. **发送队列与审计是否开启**（`BOT_SEND_QUEUE_ENABLED` 等 5 个开关）。开启能拿到持久化重试与可审计回执，但会新增 SQLite 写入与 worker 线程。
2. **系统提示词的压缩力度**：可接受多大的人设裁剪？我倾向"运行时上下文紧凑化 + 空分区不出现 + 人设保留全文"，先不动人设本体。

---

## 9. 文档勘误（本轮）

| 文档 | 原文 | 更正 |
|---|---|---|
| `handoff-2026-09-10-full.md:1299` | 「全部代码交付已入库」 | 未入库（63 tracked + 34 untracked）；**已加勘误块** |
| `handoff-2026-09-10-full.md:1297` | 「intake 区以 HEAD 为准清理」 | 会**永久丢失 mood 事件源**；正确做法是先落库 mood 钩子再合并语义；**已加勘误块（原文保留）** |
| `handoff-2026-09-10-full.md:1332` | 「用户操作项 `BOT_GROUP_DIGEST_ENABLED=true`」 | 死字段；真开关是 `BOT_SHARED_GROUP_CONTEXT_ENABLED`；**已加勘误块** |
| `handoff-MASTER-2026-09-11.md` §二 | HEAD `7c0b615` · 1033 passed | 已更正为本轮实测（1393 passed · mypy 222） |
| `docs/route-matrix.md:32` | `/bot …` 一概标 admin | 改为"逐条以代码为准"（download 对普通成员开放、边界在 downloader） |
| `.env.example` | 含死字段 `BOT_GROUP_DIGEST_ENABLED` | 已删并加注说明真开关 |

> ⚠️ `handoff-2026-09-10-full.md` 当时被编辑器独占锁定，`os.replace` 亦被拒；勘误内容已生成为
> `review/handoff-2026-09-10-full.corrections.patch`，**关掉该文件后 `git apply` 即可套用**。
> （若该 patch 已被应用，请忽略此提示。）

---

*本文由评审修复会话主笔。评审报告与逐条证据见 `review/REVIEW-3819299..cbb5161.md` 与 `review/_evidence-mainagent.md`；报告索引 `review/INDEX.md`。*
