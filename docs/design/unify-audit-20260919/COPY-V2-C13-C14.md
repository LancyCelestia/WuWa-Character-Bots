# COPY-V2-C13 / C14 — Mail 渠道文案 + 运营告警可见字段（文案稿）

Status: DONE（2026-09-21，COPY-V2 C13/C14 席；纯文案 + 只读源码，零代码改动、零 git 写）

> 交付量：**C13 新增 50 条**（命令回执 7 池 ×6=42 条，各点现状均为单点、已逐点标注坐标；新邮件通知模板 8 变体）；
> **C14 不扩池**：12 项逐条核对，**建议改动 2 处**（`建议处理→处理建议`、掉线通知去"尽快"压强）、**保持不动 9 处**、**登记待裁 1 处**。
> 机械自查全绿（原文见 §5）：禁用族 0 / 禁口语 0；通知 8/8 含 `{sender}{subject}{preview}`、异名占位符 0；
> 同型（池内两两 LCS≥9，占位符折叠后）违规 0；起手式重复 0；句长 min 20 / max 46 / 均值 32.5（n=50）；
> 档案意象 grep **HIT 4（回音/岸/潮水/鸟鸣）/ MISS 0**（另有 11 个日常比喻词单列登记，不冒称档案物件）；C14 机器腔抒情化 **0 处**。

## 0. 开工核实（读码记录）

**批次单路径前缀核实**：`COPY-V2-wave-plan.md` 表中落点写 `transport/mail/mail_bridge.py`、`ops/monitor/alerts.py`，
系 `plugins/bot_unified_runtime/domains/` 之下简写；正身实际为
`plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py`（下引 `mail_bridge.py`）与
`plugins/bot_unified_runtime/domains/ops/monitor/alerts.py`（下引 `alerts.py`）。**前缀修正**：C7 行 `schedule/store/reminders.py`
与本两族无涉，不展开。

**C13 触发场景与真实行为（逐条对码）**：
1. **新邮件通知发给谁**：`mail_notice` matcher（根 `__init__.py:4810`，`priority=9, block=False`）→
   `_handle_mail_notice`（`:5890-5966`）。条件 = `bot_mail_bridge_enabled` ∧ `bot_mail_notify_telegram_enabled`（`config.py:125/127`，
   后者缺省 True）∧ 发件人 ≠ bot 自身号 ∧ `claim_notification` 去重通过（`mail_bridge.py:184`，键=账户+Message-ID，缺 ID 时
   内容指纹兜底 `:240-268`）。投递面 = `notify_telegram_admins(get_bots(), config.bot_telegram_admin_chat_ids, …)`
   （`:5937-5942`；`mail_bridge.py:351-366`）——**只发 Telegram 管理员 chat 名单，QQ 用户永远看不到这条**。
   无 Telegram bot 时静默返回 0、审计记「未配置可用的 Telegram 提醒目标。」（`:5948`）。**暂停/自动回复开关不影响通知**：
   `/mail pause` 文案「收信提醒仍可继续」与码一致（自动回复门在 `_is_plain_chat_event`，`:4771` 查
   `bot_mail_auto_reply_enabled ∨ mail_bridge_state.paused`，通知支路不看这两者）。
2. **有没有 HTML 版**：通知本体**无 HTML**——`build_mail_notification`（`mail_bridge.py:369-392`）返回五行纯文本；
   唯一有 HTML 的 Mail 出站是**自动回信正文**：`domains/transport/sender/nonebot.py:494` → `_build_mail_reply_message`（`:308-327`）
   构造 `multipart/alternative`——纯文本 `set_content`（`:324`）+ `_mail_html_body`（`:289-306`，手写内联样式、转义后 `\n→<br>`、
   无外链资源）。掉线通知邮件（`domains/ops/monitor/disconnect_notice.py:185-197`）走 `send_mail_from_account`，**只有纯文本**（`:341-348`）。
3. **主题怎么拼**：自动回信主题 = `f"Re: {subject}"`，原主题为空时裸 `Re:`（`nonebot.py:320`）；并挂 `In-Reply-To`/`References`
   线程头（`:321-323`，原事件有 Message-ID 才挂）。命令面 `--from`/主题/正文均为用户原文直发（`mail_bridge.py:339-348`），不经人格改写。
4. **有没有 `build_mail_body` 之类**：没有。正文拼装唯一入口即上述 `build_mail_notification`（通知）与 `_mail_html_body`（回信 HTML 投影）。
5. **命令回执形态**：`/mail` **仅 Telegram 管理端可执行**（`__init__.py:5973-5983` 两道单点拒绝句），回执经统一管线
   （`bot.mail.control`，PERSONAL/IMMEDIATE，`:6016-6046`）；`execute_mail_command`（`mail_bridge.py:404-461`）返回单点字符串；
   解析期 ValueError 句（`:28/:44/:52/:59/:65/:69/:71/:443/:449`）原样回显（教语法用）。

**C14 核实要点（逐条对码）**：
1. **告警会不会流到用户眼前**：不会到普通用户。`AlertContent` → `send_admin_alert_requests`（`alerts.py:516-566`）只投
   `config.bot_admin_user_ids` 私聊（QQ）；`notify_operational_issue`（`:365-428`）逐 `AdminTarget` 投递，目标由
   `build_typed_admin_targets`（`:119-152`）从管理员 QQ/TG 名单与 TG 群 chat id 构造——**管理员 QQ 私聊 + Telegram 管理端/管理群，不见普通会话**。
   唯一用户可见的「预警」是**天气预警卡**：`domains/weather/capabilities/weather.py:243-256`，内容是 NMC 原文（类型/颜色/发布时间/标题），
   属数据面板非自写措辞。`result_unknown`/队列台账无用户可见句子（`OUTBOUND-COPY-AUDIT.md` :1047 同口径）。
2. **300s 抑制语义**（`AdminAlertSuppression`，`alerts.py:155-266`）：缺省窗口 300s；抑制键 =（stage, kind 槽, source_adapter, source_bot, 目标五元组）。
   窗口内重复**不再投递**、只在计数里累加；窗口结束后下一条放行告警以 `suppressed_count=N` 带出「上一窗口被压掉的条数」，
   **不是**「本条被压了 N 次」。llm stage 特殊：kind 槽折叠为 `*folded*`（`:183-184`），不同失败 kind 共用一个槽，窗口内每目标最多一条；
   窗口内累积的多枚 kind 以 `llm_kinds=[a|b|…]`（>1 枚才出现，`:352`）随放行条带出。sink 侧同复用（`:589`，键=location+level+管理员，
   「同一故障每晚一轮也只打扰一次」——`:585` 注释与实现一致）。
3. **`source_bot=unknown` 现值口径**：字段照原样输出 `source_bot={…[:80]}`（`:359-360`），调用方取不到 bot 标识时才会填 `unknown`；
   台账 #20 早已定性（历史批次终态 + 300s 抑制聚合，**非现行缺陷**）。文案稿不得把它写成新事实，也不得藏值。
4. **掉线通知冷却**：`DisconnectNoticeOptions.cooldown_seconds` 缺省 600s/每（adapter:bot_id）键（`disconnect_notice.py:27/:129-136`），
   与告警 300s 抑制是**两套独立机制**，措辞里不混称。
5. **C14 行数核实**：批次单写 `alerts.py:63-68`，实况 `format_message` 六行在 `:61-70`（`:63-68` 是其主体六条 f-string），坐标无漂移。

**意象可 grep 性（本席实测，三档案 = `守岸人档案.md`/`守岸人人格设定.md`/`守岸人人格档案.md`）**：
HIT（词频>0）：潮汐21 海潮6 涨3 潮起潮落3 岸（黑海岸115） 浪10 船7 港2 礁1 雾1 星空7 星图7 灯火4 花房9 钢琴19
鲸歌6 鸟鸣6 锚点6 回音32 回声2 茧状4 碎裂晶体3 拾4 椿4 安可4 秋水11 泰缇斯63 调律大厅5 调律者40 旋律15 海风1 水母1。
MISS（0 频，**本稿不用**）：**退潮、记录本、贝壳、珊瑚、藤、苔、莲、苇、琴弦、夜晚、黎明、邮票、信封、书信、信件、寄、捎、邮、
靠岸、停泊、航线、帆、窗、茶、风铃、落款、展信**——其中「退潮/记录本/贝壳/珊瑚/藤/苔/莲/苇」voice-brief §一 列为可用，
档案 grep 不过（与 C8/C9 席登记一致，本席再证）；**书信族全部 grep 不到**，邮件文案因此只借潮/岸/灯火/回音/锚点等黑海岸既有物象，
不造「寄信/邮票/信箱」一类档案没有的意象。

## 1. C13-A Mail 命令回执池（现状单点 → 每池 6 条）

正身：`mail_bridge.py:404-461`（`execute_mail_command` 各分支返回值）+ 根 `__init__.py:5975/:5982/:6001`（两道门与兜底失败句）。
接收方恒为 **Telegram 管理端的管理员**（`/mail` 只认 TG，见 §0），故口味规则照常适用但不写卡片腔、不堆长；
**每个回执点现状都是单点**，按交付要求逐池给足 ≥6。

**保持机器腔、不入池的（登记说明，不给变体）**：
- `/mail help` 七行命令清单（`:414-423`）、`/mail status` 三行面板（`:428-432`）、`/mail accounts` 一行清单（`:434`）——
  数据面板，改措辞只会伤可检索性；
- 解析/校验期 ValueError 族（`:28 {field}必须是完整邮箱地址。`、`:44/:52`、`:59/:65` 格式示范、`:69/:71` 空主题/空正文、
  `:443/:449` 未连接/未选择提示）——**教语法的句子**，原样最好；
- `:174 管理员用户 ID 不能为空。`——装配期内部异常，不落人眼。

**变量口径说明**：现状回执是内嵌 f-string（`{account}`/`{recipient}` 直接取自 `command.account`/`command.recipient`/选账结果），
源码里没有命名字符串占位符；本稿提出的 `{account}`（发件账户邮箱串）、`{recipient}`（收件邮箱串）两枚槽为**建议模板槽名**，
实现批映射到上述字段即可，与批次单点名的 `{sender}{subject}{preview}` 不冲突（那三枚用于 §2 通知模板）。

### R1 发送成功（现单点 `mail_bridge.py:460 邮件发送成功：{account} → {command.recipient}`）

事实边界：SMTP 提交成功才走到这句（`await send_mail_from_account` 未抛异常）；**不得写"对方已收到/已送达"**，只写"已发出"。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 信已经从 {account} 交出去了，收信人是 {recipient}，我这边取到的回执是发送成功。 | 无（纯说人话） | 受事主语句 | 是（建议槽 `{account}` `{recipient}`，下同） |
| 2 | 这一趟由 {account} 走得顺利，写给 {recipient} 的那封已经原样寄出。 | 无 | 指示代词起 | 是 |
| 3 | 发件 {account}、收件 {recipient}，送出这一段没有在半路松手。 | 无 | 双字段并列起 | 是 |
| 4 | 交由 {account} 寄往 {recipient} 的那一封，此刻已经离开我这边的发件台了。 | 无（日常器物词：发件台） | 介宾起 | 是 |
| 5 | 与 {recipient} 之间的那一段已经由 {account} 走完，主题与正文都照你给的样子，一字未动地交了出去。 | 无 | 介词短语起 | 是 |
| 6 | 刚那封信顺着 {account} 出了门，往 {recipient} 去的路上不用再经过我什么操作了。 | 无（日常说法：出门/路） | 时间状语起 | 是 |

（R1 共 6 条新增；现单点已在上文标注坐标。）

### R2 选账成功（现单点 `mail_bridge.py:445 当前发件账户已切换为：{command.account}`）

事实边界：只落盘选账状态（`select_account`，`:171-178`）；不带 `--from` 的后续 send 才用到它（`:447`）；别名→认证账户解析在
`send_mail_from_account:322-327`，与选账本身无关，措辞别把两件事混成一件。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 这一步落定了：往后不带 `--from` 的信，都从 {account} 这一格寄出去。 | 无（纯说人话） | 结论起 + 规则展开 | 是 |
| 2 | 发件口已经换成 {account}，这件事我记进桥的状态里了。 | 无（"记进状态"= `MailBridgeState._save` 落盘，非承诺记忆） | 事物主语句 | 是 |
| 3 | {account} 从现在起担任默认发件账户，想换回来的话，再递一次 use 就好。 | 无 | 账户主语句 | 是 |
| 4 | 选定的是 {account}——下一次你说 /mail send 却忘了带来源，用的就是它。 | 无 | 判断句起 + 补一个场景 | 是 |
| 5 | 默认出口挪到 {account} 了，之前的那一格就此让位。 | 无（日常说法：出口/挪位） | 空间比喻起 | 是 |
| 6 | 记下了，本轮之后的发件署名归 {account}；带 `--from` 指名时仍以指名为准。 | 无 | 动词谓语句起 | 是 |

（R2 共 6 条新增。第 6 条把 `--from` 覆盖语义说清（`:458-459` 连选账都会被 `--from` 改写），管理员省一次试错。）

### R3 暂停成功（现单点 `mail_bridge.py:437 邮件自动回复已暂停；收信提醒仍可继续。`）

事实边界：暂停只掐自动回信（门在 `__init__.py:4771`），新邮件通知支路不受影响（§0 已证）；**不得写"暂停期间来的信会攒着回"**——
恢复后不补处理（信在收件箱已被标 seen，适配器只搜 UNSEEN，`mail_adapter.py:268-283`）。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 自动回信这一侧已经按下了，新邮件到了仍会照常提醒你，只是我不再替你回任何一封。 | 无（纯说人话） | 两事对照起 | 否 |
| 2 | 暂停好了——从现在起到你说 resume 之前，来信只会递提醒给你，不会再自动得到回音。 | 回音（档案） | 动作完成起 | 否 |
| 3 | 回信停下来了；提醒那条线没有动，信到了还是会在 Telegram 那头说一声。 | 无（日常说法：线） | 短句领起 + 分述 | 否 |
| 4 | 这一段先停在这里：之后来的信我只提醒、不回信，等你一句 resume 再继续。 | 无 | 指示代词起 | 否 |
| 5 | 已经暂停。要说明的是，这期间落进来的信不会被攒着补回，恢复之后处理的是往后的新信。 | 无（纯说人话，防误解句） | 状态确认起 + 澄清 | 否 |
| 6 | 潮水照旧把新邮件推到提醒这一岸，只是自动回信那一侧歇下了，门先掩上一半。 | 潮水/岸（档案；另有日常词"门"） | 意象领起 + 收束 | 否 |

（R3 共 6 条新增；第 5 条专门堵住"暂停=攒起来回头一起回"的误读，与码一致。）

### R4 恢复成功（现单点 `mail_bridge.py:440 邮件自动回复已恢复。`）

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 接上了，回信这一侧又走动起来；提醒那条线自始至终没有停过。 | 无（纯说人话） | 单字领起 + 分述 | 否 |
| 2 | 自动回复重新就位，从下一封新信起照旧会被回应，暂停期间落下的那些不补。 | 无（防误解句） | 状态陈述起 | 否 |
| 3 | 恢复完成——往后的来信会继续得到自动回信，这一句就是全部的变动。 | 无 | 动作完成起 | 否 |
| 4 | 掩上的那道门开了，潮水照常往还：信进来，回音出去，提醒一路都没缺席。 | 潮水/回音（档案；日常词"门"承接 R3） | 空间动作起 | 否 |
| 5 | 这一段重新放行，信到了我照旧读、照旧回，你不用再做什么。 | 无 | 指示代词起 | 否 |
| 6 | resume 已执行，自动回复回到在岗状态；想验证的话，随时递一封测试信进来都算正常用法。 | 无 | 命令词起手（管理员语域） | 否 |

（R4 共 6 条新增。第 6 条的"随时递测试信"只是陈述通道可用，不构成 bot 的额外承诺。）

### R5 操作失败兜底（现单点 `__init__.py:6001 邮件操作失败，请查看脱敏运行日志后重试。`）

事实边界：非 ValueError 的一切异常（SMTP/适配器侧）都收敛成这一句，细节**刻意不回显**（`:5998` 注释）；
系统不会自己重投，"重试"只能由管理员再敲一次命令——措辞里保住这两点，不写"我稍后再试一次"。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 这一次没有发出去，具体原因我只留在脱敏后的运行日志里，你方便时翻一眼，再决定要不要重发。 | 无（纯说人话） | 结果陈述起 | 否 |
| 2 | 邮件操作在半路断了，细节不在这里复述，完整形状去脱敏日志里看。 | 无（日常说法：半路） | 主谓起 | 否 |
| 3 | 半路没有走通——能安稳落字的部分都写进这条了，其余的留在日志那边，查过之后命令可以再递一次。 | 无 | 状态短语起 | 否 |
| 4 | 出错了，信没有寄出去。为避免把内网地址和键值形态念出来，详情一律只落进打码后的日志。 | 无（技术诚实句） | 短陈述领起 + 解释 | 否 |
| 5 | 发送停在了半路，我这边没有更多可以安全展示的细节；日志看过之后，这条命令原样再走一遍就行。 | 无（日常说法：半路） | 动词谓语句起 | 否 |
| 6 | 刚才那一单没有办成，SMTP 交接处出了岔子；它具体卡在哪儿，脱敏日志里那一行说得比我清楚。 | 无 | 时间状语起 | 否 |

（R5 共 6 条新增。第 6 条点出失败发生在"交接处"，与 `send_mail_from_account` 抛点一致，仍不复现异常原文。）

### R6 渠道门拒绝（现单点 `__init__.py:5975 邮件控制命令仅允许从 Telegram 管理端执行。`）

场景：有人（多半是 QQ 侧）敲了 `/mail`。不指责发送者"发错了"，只陈述通道归属；给出可行去处。
**待裁点**：这两句门拒绝与 C3 管理员门禁池（`user_copy.py:36-49`）同族异身，统一模板层落地时是并入 C3 池还是留 Mail 域，见 §3。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 邮件控制这条通道只挂在 Telegram 管理端，从这边递过来是走不通的，去那边说同一句就可以。 | 无（纯说人话） | 通道主语句 | 否 |
| 2 | /mail 只认从 Telegram 那头来的指令，这一侧的执行路本来就是空着的。 | 无 | 命令词起手 | 否 |
| 3 | 这扇门只从 Telegram 管理端那一侧开得动，在这边它不为任何指令让开。 | 无（日常词：门） | 指示代词起 | 否 |
| 4 | 收到是收到了，只是这个命令要在 Telegram 管理端说才会生效，这边我不动它。 | 无 | 让步起 | 否 |
| 5 | 这条通道在这边是关着的：/mail 的入口只留在 Telegram 管理端，想去掉这份限制，把指令挪个端再说一遍。 | 无 | 状态判词起 | 否 |
| 6 | 不在那一端的话，这条命令到我这里只会原样停下，不会有任何账户或邮件被碰到。 | 无（安全边界陈述） | 条件句起 | 否 |

（R6 共 6 条新增。第 6 条顺带向 QQ 侧围观者保证"什么都没发生"，防止误以为信被代发。）

### R7 角色门拒绝（现单点 `__init__.py:5982 你没有邮件控制权限。`）

事实边界：管理员名单 = `bot_telegram_admin_user_ids` + `bot_telegram_admin_chat_ids`（`:5977-5980`，`is_telegram_admin` 同时比 user_id 与 chat_id，
`mail_bridge.py:395-402`）。禁"你发错了/请正确使用"式指责；归因于名单与门，不评价人。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 1 | 这一族的命令要先对着管理员名单核一遍，核不过，我就只能停在门口。 | 无（日常词：门口） | 流程陈述起 | 否 |
| 2 | 名单里没给这一号留下位置，所以这条 /mail 我不能执行。 | 无（纯说人话） | 否定陈述起 | 否 |
| 3 | 权限这一关没有过，命令到这里就止步了；要开通的话，得由名单另一头的人来说。 | 无（纯说人话） | 名词短语领起 | 否 |
| 4 | 这条得是管理员的口令我才执行，与消息本身说的是什么无关。 | 无 | 条件判词起 | 否 |
| 5 | 我核了一下，这个位置不在 Telegram 管理员名单里，/mail 在你这里是不生效的。 | 无 | 自述动作起 | 否 |
| 6 | 开关只接在管理员名单那一侧，你递过来的这条我原样奉还，不代按。 | 无（日常词：开关） | 归属陈述起 | 否 |

（R7 共 6 条新增。**回执七池合计 42 条**，均 ≥6，达标。）

## 2. C13-B 新邮件通知模板 8 变体（{sender}{subject}{preview}）

正身（现单点模板）：`mail_bridge.py:386-392`——
```
📧 收到新邮件
收件账户：{account 值}
发件人：{sender_label 值}
主题：{subject 值}
摘要：{preview 值}
```
**变量与源码逐字口径**：批次单点名 `{sender}{subject}{preview}` 三枚；现模板还含"收件账户"一行（值即 `account` 参数，`mail_bridge.py:373/388`），
统一模板若不保留会丢掉"多账户各自到信"的分辨力，故本稿变体统一使用 **`{account}` 第四枚**（映射 `account` 参数，非自创字段）。
三枚点名变量的码内真相：`{sender}` = `sender_label`（有显示名时 `名字 <地址>`、无名时裸地址，`:376-378`）；
`{subject}` = 主题（空主题在进模板**之前**已被码内回退为 `(无主题)`，`:379`）；`{preview}` = 摘要（空白折叠后按
`max_preview_chars`（生产键 `bot_mail_notify_preview_chars`，`config.py:130` 缺省 280）截断、超限以 `…` 收尾；
纯文本正文为空时码内回退 `(无纯文本正文)`，`:380-391`）。**模板里不需要写这三处回退分支**，值送进模板时已非空。

**事实边界（通知面红线）**：只报"到了什么"，**不得写"我已替你回信/已归档/已转发"**——自动回信是另一条 matcher 支路，
可被 `bot_mail_auto_reply_enabled=false` 或 `/mail pause` 关掉（§0），通知文案若宣称回信即失实；也不得写"替你盯着/攒了多少事"式评价
（任务明令）；提醒对象恒为 Telegram 管理员名单（`bot_telegram_admin_chat_ids`），措辞按"报给管事的人"的语域写，克制优先。

| # | 变体原文 | 意象用了哪个档案物件 | 起手式类型 | 是否含变量 |
|---|---|---|---|---|
| 0 | （现单点原句，见上方代码块，实现期留作快照对照） | 无 | 图标 + 四字判断 | 是（现值插值 `{account}`/`{sender_label}`/`{subject}`/`{preview}` 语义位） |
| 1 | 📧 有新的信到了。/收件账户：{account}/来信人：{sender}/主题：{subject}/开头先看一眼：{preview} | 无（换标签不换事实） | 图标 + 判断句 | 是（四枚全，下同） |
| 2 | 📧 {account} 收到了一封新邮件，寄件的是 {sender}，主题叫 {subject}。/我摘到的正文开头：{preview} | 无（叙述体） | 账户主语句 | 是（四枚全） |
| 3 | 📧 新邮件，正文开头先递上：{preview}/——寄给 {account}，来自 {sender}，题目是 {subject}。 | 无（倒装结构） | 提示词 + 倒装 | 是（四枚全） |
| 4 | 📧 潮水刚把一封信推上岸。/{sender} 寄给 {account}，题目挂着 {subject}/开头是这样的：{preview} | 潮水/岸（档案） | 意象领起 + 两行分述 | 是（四枚全） |
| 5 | 📧 要紧的四样都报在下面。/账户 {account}｜寄件 {sender}｜主题 {subject}/开头一段：{preview} | 无（纯说人话） | 判断句 + 竖线并排 | 是（四枚全） |
| 6 | 📧 {account} 这一格落进了一封新信。/递进来的人是 {sender}，主题写着 {subject}，/先把个开头读给你：{preview} | 无（日常词：格） | 处所主语句 | 是（四枚全） |
| 7 | 📧 有信到了，鸟鸣把它捎过来，先把形状报清楚。/主题 {subject}，出自 {sender}/落在账户 {account}，节选如下：{preview} | 鸟鸣（档案） | 短语领起 + 另序三行 | 是（四枚全） |
| 8 | 📧 又一封往 {account} 去的信到了岸边。/From：{sender}/主题行：{subject}/正文开头节选：{preview} | 岸（档案·黑海岸系） | 数量短语起 | 是（四枚全） |

（C13-B 共 **8 个新变体**（第 1-8 行）+ 现单点留档（第 0 行），达标线 8；表内 `/` 为换行示意，落地时每枚变体是多行模板串。
纯说人话无档案意象的有第 1/2/3/5/6 行五条，意象条第 4（潮水/岸）、7（鸟鸣）、8（岸）各只挂一处——
通知是"报给管事的人"的面，密度按任务口径压在半池以下，符合"每 4-5 条至少一条无意象"与克制语域。）

## 3. C13-C 统一模板层规格材料（供 `docs/design/outbound-template-unification-spec.md` 当输入）

> 用户裁定（题面转述）：**邮件需要新增纯文本模板与 HTML 图片渲染模板，并与 QQ/Telegram 统一成模板文件、任何平台不得自写一次性模板。**
> 本节只给规格材料，不实现。

### 3.1 Mail 出站文本现状形态盘点（几种形态、写死在哪）

| 形态 | 内容 | 现状实现坐标 | 模板性质 |
|---|---|---|---|
| F1 管理员新邮件通知 | 五行纯文本面板（§2 现单点） | `domains/transport/mail/mail_bridge.py:386-392` | **Mail 域自写一次性模板**，无 HTML 投影 |
| F2 自动回信·主题 | `Re: {原主题}`；原主题空则裸 `Re:` | `domains/transport/sender/nonebot.py:320` | 主题**信封规则**（非人格文案），线程头 `In-Reply-To/References` 在 `:321-323` |
| F3 自动回信·正文纯文本 | 管线成品 `remaining` 原文 | `nonebot.py:324`（`set_content`） | 无自写文案，内容即聊天产出 |
| F4 自动回信·正文 HTML | 手写内联样式壳：转义 + `\n→<br>`、系统字体栈、守岸人配色 | `nonebot.py:289-306`（`_mail_html_body`） | **Sender 层自写一次性 HTML 模板**——正是裁定要收编的那类 |
| F5 /mail 命令回执 | 单点串 ×7 池 + 结构化面板 + ValueError 族 | `mail_bridge.py:414-461` + 根 `__init__.py:5975/:5982/:6001` | §1 已池化；面板/语法句保持机器腔 |
| F6 运维邮件（掉线通知） | 主题 `【机器人掉线通知】`（`disconnect_notice.py:192`）+ 与 TG 端同一块纯文本面板（`mail_bridge` 侧 `send_mail_from_account:312-348` 仅 `set_content`，**无 HTML**） | `domains/ops/monitor/disconnect_notice.py:75-83/:185-197` | ops 域自写一次性模板；同一文本被 TG/Server酱/PushPlus/邮件四渠道复用 |

结论：**Mail 出站共 6 种文本形态、3 处"平台自写一次性模板"（F1 面板、F4 HTML 壳、F6 跨渠道共用面板）**，HTML 渲染目前只有 F4 一处、
且样式硬编码在 sender 传输层（`multipart/alternative` 的纯文本兜底语义 F4 已天然具备）。

### 3.2 若统一成"逻辑消息键 → 模板文件 → 按渠道投影"，Mail 一路需要的字段

建议逻辑键（命名从简，最终以规格主笔定）：`mail.notify.new_mail`（F1，接 §2 八变体）、`mail.receipt.<action>`（F5 七池）、
`mail.alert.disconnect`（F6，与 `tg.alert.disconnect` 同源不同投影）、回信正文 `chat.reply.body`（F3 内容不模板化，仅投影）。
Mail 投影需要的字段面（每枚键的渲染上下文）：
- `account`（收件/发件账户串）、`sender`（`名字 <地址>` 或裸地址的既有合流值）、`subject`（已回退非空）、`preview`（已截断非空）；
- 回信信封字段：`reply_subject`（`Re:` 规则产物，**归信封层不归文案层**——主题模板是 RFC 语义不该进人格池）、`in_reply_to`、`references`、`from_format`（`名字 <地址>` formataddr，`nonebot.py:319`）；
- 投影开关：`html_available`（渠道能力位），以及既有的 `max_preview_chars`（生产键 `BOT_MAIL_NOTIFY_PREVIEW_CHARS`）。

### 3.3 按渠道投影与降级路径（HTML 不可用 → 纯文本）

1. **投影**：同一逻辑键产出两棵渲染树——`text`（TG/QQ 复用）与 `html`（Mail 专用）。HTML 应是**中央模板 + 主题 token**的产物，
   `nonebot.py:289-306` 的内联样式壳迁为模板文件；Mail 客户端剥 `<style>`/外链的既有约束（`:291-295` docstring）写成模板层硬规则（只许内联、零外链）。
2. **降级**：HTML 投影**失败或不可用**时回纯文本——现状 `multipart/alternative`（`:324-325`）本就允许任一客户端退回 text 部分，
   统一层只需保证"text 恒在、html 尽力而为"，投影异常时**丢 html 不丢信**（fail-open，对齐渲染管线"失败→纯文本兜底契约零破坏"的既有铁律）。
3. **脱敏前置**：Mail 旁路现状不经 Review/`redact_local_secrets`（审计已钉：`OUTBOUND-COPY-AUDIT`/U3 :305-311、U23-07——
   `send_mail_from_account` 与 `notify_telegram_admins` 直取 bot 出站）。统一模板层落地时**脱敏必须挂在投影之前**，
   文本与 HTML 两棵树同源同一次打码，不得 HTML 树漏打。
4. **变体择一的位置**：§1/§2 的池在逻辑键层做会话级游标（对齐 C2-C5 既有 `pick_variant` 族），Mail 只消费结果，不再自持文案。
5. **待裁点**：(a) F6 掉线面板四渠道复用同一文本——统一后是"一键多投影"还是各渠道一键；(b) `Re:` 裸前缀（原主题为空时）是否加占位主题如
   `(无主题)`——现状裸 `Re:` 合法但难看，属信封层决定；(c) HTML 模板是否复用卡片渲染（playwright 出图作 `cid` 内嵌）——
   **现状代码零路径**，题面"HTML 图片渲染"若指卡片图内嵌邮件，需单列功能裁定，本稿按"HTML 文本投影"规格。

## 4. C14 运营告警可见字段（现措辞 → 建议措辞 → 为什么 → 动不动）

> 语域钉死：读者是管理员（QQ 私聊 + Telegram 管理端/管理群，**不流到普通用户眼前**，证据见 §0-C14.1）；
> **克制优先于抒情，不扩池、不写变体**——只把"露给人看的措辞"校一轮。共 12 项：**建议改动 2 处**、**明确保持不动 9 处**、**登记待裁 1 处**。

| # | 串（坐标） | 现措辞 | 建议措辞 | 为什么 | 判定 |
|---|---|---|---|---|---|
| 1 | 面板字段标签（`alerts.py:68`） | `建议处理：{fix_suggestion}` | `处理建议：{fix_suggestion}` | "建议处理"初读易解作动宾（"建议（你去）处理"），与同行其余四枚名词性标签（时间/位置/发生了什么/影响）不齐；"处理建议"是名词短语，扫读时与标签行同构 | **改动** |
| 2 | 掉线收尾祈使（`disconnect_notice.py:82`） | `请尽快检查 SnowLuma 与网络状态。` | `可先查看 SnowLuma 与网络状态。` | "尽快"是无增益的压强词——冷却 600s/键（`:27/:130-136`），抖动期每轮都催一遍尤其扰人；操作指引保留、催促副词摘除，与"不指责、不施压"口径一致 | **改动** |
| 3 | 面板前缀（`alerts.py:63`） | `[预警] {title}` | 原样 | 行首结构化标记，管理员按前缀分拣；套人格语气反而降低辨识度 | 保持不动 |
| 4 | 其余五枚面板标签（`alerts.py:64-67`） | `时间：/位置：/发生了什么：/影响：` | 原样 | 五要素契约在模块 docstring（`:3-10`）明文钉死，测试与人工排障都按这套行序读 | 保持不动 |
| 5 | 运行时告警行（`alerts.py:356-362`） | `[运行时告警] stage=… kind=… detail=… retryable=… attempts=… debug_id=… source_adapter=… source_bot=… session_type=… suppressed_count=…` | 原样，**一个字母不动** | 这是 grep 面不是话术面：kind 标签/阈值性字段（attempts、elapsed_ms）/轨迹串（debug_id、source_*）是机器腔本体；`suppressed_count=N` 的语义是"上一 300s 窗口内被压掉的同键条数"（`:196-245`），字段名已是这个意思，改写只会引入歧义。`source_bot=unknown` 为调用方取不到标识时的原样透传（台账 #20 早已定性为历史形态非现行缺陷），**不藏、不注脚、不渲染情绪** | 保持不动 |
| 6 | llm 链宽压缩词（`alerts.py:326`） | `chain={n}跳全败` | 原样 | docstring（`:311-315`）已论证语义诚实（告警只在整条 failover 链耗尽后触发）；换"多处不顺"一类软化语反而丢诊断精度 | 保持不动 |
| 7 | 折叠 kind 清单（`alerts.py:352`） | ` llm_kinds=[a|b|…]` | 原样 | 上一窗口累积 kind 的带出通道（`fold_kind_stages` 折叠去噪，`:165-168`），竖线分隔是数据不是文案 | 保持不动 |
| 8 | 告警私信署名（`alerts.py:543`） | `sender_display_name="运行时预警"` | 原样 | 管理员侧来源标识；改成第一人称会让"这条是系统投递"与"这条是守岸人说话"混线——克制优先 | 保持不动 |
| 9 | 掉线通知面板（`disconnect_notice.py:79-81`）+ 推送标题（`:154`）+ 邮件主题（`:192`） | `🔌 机器人掉线通知/适配器：/账号：/原因：`；`机器人掉线：{adapter} {bot}`；`【机器人掉线通知】` | 原样 | 四渠道（Server酱/PushPlus/TG/邮件）共用同一体的字段面板与标题，主题行还承担邮件端检索；此处抒情=事故现场加戏 | 保持不动 |
| 10 | 装配期异常句（`alerts.py:85/:87`） | `admin target adapter, bot_id, and target_id are required` 等英文 ValueError | 原样 | 构造期异常不落人眼（抛在装配/开发面），保留英文与栈同构 | 保持不动 |
| 11 | 天气预警卡（`domains/weather/capabilities/weather.py:248-255`） | `⚠️ 气象预警（NMC 当前在报 {n} 条）`、`• {色}{型}预警｜发布 {时间}`、`时间未知`、`（其余 {n} 条略）` | 原样 | 用户可见但**内容全是 NMC 原文与数据字段**，自写部分只有面板骨架；`时间未知`/`（其余 N 条略）`是诚实空值与截断口径（对齐 R-2"未知码原样上屏、不顺手藏"的挂起裁定精神），不应被文案化 | 保持不动 |
| 12 | 双标记不统一 | 面板用 `[预警]`、告警行用 `[运行时告警]`、sink 注释又称"告警" | —— | 三套叫法分属 AlertContent 投递与 OperationalIssue 投递两条独立链，语义确有区分（五要素面板 vs 单行字段串），**是否统一归统一模板层规格裁决**，本席不并 | **登记待裁** |

**应始终保持机器腔的字段类别（明文登记，供实现期门禁引用）**：kind 标签全集、`stage=`/`retryable=`/`attempts=`/`elapsed_ms=`/
`debug_id=`/`source_adapter=`/`source_bot=`/`session_type=`/`suppressed_count=`/`llm_kinds=` 全部 key=value 字段、
`chain=N跳全败`、`detail=` 截断（60 字，`:346`）、阈值数值与货币串（usage_monitor 侧）、天气预警的 NMC 原文与 `时间未知`。
本表对以上任何一项均未提出抒情化改写——自查项"机器腔改抒情 = 0 处"由此成立（另见 §5 机械自查）。
另抽查三处 AlertContent caller 正文（凭据过期 `__init__.py:1753-1763`、kb-sync `kb_wiki.py:779-812`、用量 `usage_monitor.py:117/:421`）：
均为"发生了什么 + 后果 + 可执行指令"结构，克制达标，**不改**；其修复指引出现的 `/bot alert check`、`/bot model usage` 等命令名与
WebUI 页面名属他域事实，若漂移归 echo/命令目录批次，本席仅在 §6 登记观察。

## 5. 机械自查输出（脚本落 %TEMP%，原文粘贴）

复跑命令（脚本本体 `C:/Users/LancyCelestia/AppData/Local/Temp/copy_c1314_check2.py`，只读本文档与三份人格档案）：
```
cd ChatBot\ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 python "$TEMP/copy_c1314_check2.py"
```
判据口径：同型=池内两两**最长公共子串 ≥9 字**（占位符折叠为单字符、Telegram/SMTP 等技术词折叠，剔除结构性共用词后再比）；起手式=折叠后前 2 字符（📧 图标为渠道标记不计）；句长=去空白、占位符记 1 字。

```
=== pool parsing ===
R1 6
R2 6
R3 6
R4 6
R5 6
R6 6
R7 6
NOTIF 9

=== banned-family scan (variant bodies) ===
hits: 0 []

=== placeholders per pool ===
NOTIF ['{account}', '{preview}', '{sender}', '{subject}']
R1 ['{account}', '{recipient}']
R2 ['{account}']
R3 []
R4 []
R5 []
R6 []
R7 []
NOTIF variants lacking {sender}{subject}{preview}: none (8/8 ok)
alien placeholders in variant lines: none

=== same-type check (pairwise LCS >= 9 chars, within pool, placeholders folded) ===
same-type violations: 0

=== opener (first 2 non-marker chars) duplicates within pool ===
R1 dup: none
R2 dup: none
R3 dup: none
R4 dup: none
R5 dup: none
R6 dup: none
R7 dup: none
NOTIF dup: none

=== sentence length per pool (placeholders folded to 1 char) ===
R1 min 21 max 38 avg 27.8 [30, 23, 21, 26, 38, 29]
R2 min 20 max 31 avg 25.7 [24, 22, 31, 30, 20, 27]
R3 min 30 max 41 avg 35.8 [39, 37, 30, 32, 41, 36]
R4 min 28 max 39 avg 32.8 [29, 35, 32, 34, 28, 39]
R5 min 31 max 46 avg 41.7 [44, 31, 46, 42, 45, 42]
R6 min 27 max 43 avg 34.5 [39, 27, 29, 32, 43, 37]
R7 min 24 max 37 avg 30.5 [32, 24, 37, 28, 31, 31]
NOTIF min 29 max 41 avg 32.8 [31, 32, 29, 30, 29, 37, 41, 33]
ALL new lines: min 20 max 46 avg 32.7 n = 50

=== imagery grep (only words tagged 档案 in col-3; annotations excluded) ===
HIT  回音 32
HIT  岸 544
HIT  潮水 1
HIT  鸟鸣 6
HIT 4 MISS 0
daily-metaphor register (not scored, not claimed as archive objects): ['出口', '出门', '半路', '发件台', '开关', '挪位', '格', '线', '路', '门', '门口']

=== C14 machine-tone check (suggestion column must not add imagery words) ===
machine-tone-to-lyrical changes: 0

=== count conclusions ===
NOTIF new variants >= 8: True
each receipt pool >= 6: True
```

## 6. 登记（不改）／不可写清单／待裁点

**登记（发现问题，一律不改，属他席/后续批）**：
1. **Mail 出站旁路**：`send_mail_from_account`（`mail_bridge.py:312-348`）与 `notify_telegram_admins`（`:351-366`）直取 bot 对象发信，
   不经 SendQueue/Review/`redact_local_secrets`——U3 审计 :305-311 与 U23-07 已钉死，本批仅提醒统一模板层落地时
   **脱敏必须挂在投影之前**（§3.3-3），施工权在模板批。
2. `tests/test_mail_bridge.py` 现锁状态机语义（claim/dedupe），不锁文案串；实现批迁移 §1/§2 时旧句按批次单要求留快照对照。
3. C14 的 `[预警]`（AlertContent）与 `[运行时告警]`（OperationalIssue）双标记分属两链，本席不并（§4-12）。
4. 天气预警卡的 `时间未知`/`（其余 N 条略）` 空值与截断口径**不得在实现期被"顺手美化"**（对齐 R-2 未知码挂起裁定精神）。
5. AlertContent caller 文案里的命令名（`/bot alert check`、`/bot model usage`/`price`）与 WebUI 页面名属 echo/命令目录域事实，
   本席未逐一核命令在册性，若有漂移归 command_catalog/doc_sync 批。

**不可写清单（本席逐码核实，全部未入稿）**：
- 通知/回执**不得宣称"已自动回复/替你回了信"**——自动回信是独立支路，可被 `bot_mail_auto_reply_enabled=false` 或 `/mail pause` 关闭；
- **不得写"暂停期间的信会攒着以后补回"**——恢复后只处理新 UNSEEN，旧信已标 seen 不再扫（`mail_adapter.py:268-291`）；
- **不得写"已送达/对方已收到"**——现状只有提交级成功（SMTP 送出未抛异常）；
- **不得写"我会重试/稍后再发/自动补发"**——零路径；R5 池只引导管理员手动再递一次；
- **不得写"替你归档/保管邮件正文"**——Mail 域无归档路径（`MailBridgeState` 只存去重 ID 与选账，`:81-222`）；
- **不得用信箱/邮票/信封/书信/寄递系意象**——三档案 grep 全 0（§0 实测），全稿只取可 grep 物件与日常词。

**待裁点（给收席/用户）**：
1. R6/R7 两道邮件门拒答是否并入 C3 管理员门禁池（同族语义、不同身文件），还是留 Mail 域独立池；
2. 统一模板层中 `[预警]`/`[运行时告警]` 标记是否归一（§4-12）；
3. 用户裁定"HTML 图片渲染模板"语义：按本稿 §3.3-c 走"中央 HTML 文本投影"，还是另立"卡片图 cid 内嵌邮件"功能项（现状代码零路径）；
4. 空主题回信裸 `Re:` 是否补占位主题（信封层决定，§3.3 待裁 b）。

**PASS**：禁用族零命中 / 通知 ≥8 / 回执每池 ≥6（各点单点已说明）/ 变量与批次单点名逐字一致 / 新增条彼此与对基线均不同型 /
句长有起伏 / 意象全部档案可 grep / C14 零抒情化。

