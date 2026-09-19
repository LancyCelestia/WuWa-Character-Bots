# 出站文本模板全量清单（含触发条件）

> 本席：TPL1-b（研究+文档，只读代码、只写本文件）。生成时点 2026-09-20。
> 本清单**只收「以文本形式发到渠道的消息模板」**（QQ / Telegram / Mail / Console 四渠道）。
> 底稿＝同目录 `OUTBOUND-COPY-AUDIT.md`（1049 行，原文与行号已抽全，但无触发条件）；
> 本文件在其基础上**逐条补「触发条件」**并交叉引用，不重复抄写卡片图内文案。
> ⚠️ 行号＝本席读取时快照，本树多会话并发写，引用前重定位（沿袭底稿口径）。

## 0. 口径与时点 / 统计

**纳入本清单（发给用户的「文本形态」出站消息）**
- QQ / Telegram / Mail / Console 四渠道以**纯文本 / 模板串 / 池轮换句**形式发出的消息正文与回执。
- 能力级一次性中文回复句（回复字面句）——**本席只做五族**：
  `chat_reply` + `render` + `ops/monitor`（含 alerts、error_report）+ `schedule`（reminders）+ `assistant`（digest/meal/daily_assist/campus）。
- 静默门（故意不发文本）——单独成 §10 总表。

**不纳入本清单（并在 §0 说明排除理由）**
- **卡片图内文案**：不重抄。七张 Jinja 模板的短行中文原文见 `OUTBOUND-COPY-AUDIT.md` §十二；渲染口径见 `docs/rendering-contract.md` 与 `DESIGN-SPEC.md`。本清单只在涉及「卡片渲染失败→纯文本兜底」时引用其文本面。
- **人格 / 提示词（发给 LLM 而非发给用户）**：`personas/**`、`domains/chat_reply/character/providers.py` 的 13 分区注入文本、反注入包裹、亲密/管理档案指令等——都是**模型输入**，不是用户可见出站消息，全量排除。仅在 §0 说明。
- **内部语义无用户可见句**：`result_unknown`、SendQueue part 级幂等、`runtime/alerts` 台账条目本身（其「可见投影」在 §9 收录）。
- 其余域（finance / weather / music / notes / media_archive / subscribe / link_parse / divination / meme / food / location / creation / transport 里非 Mail/TG caption 的部分 / files / emergency_info）里散落的**能力级一次性回复句**：§11 只登记入口文件与已定位行，标注「第二批」，由后续席位续做。

**每条目字段（列）**：`触发条件（具体到能复现）| 原文 | 落点 文件:行 | 形态（池N变体/单点/模板串/来自配置/生成物门管辖）| 渠道 | 同一语义的其它副本`

**「触发条件」写法**：写到用户能照着复现——哪条命令 / 哪个自然语言形态 / 什么权限门 / 什么状态 / 几点钟 / 什么失败路径；**「不触发」也记**（限流拦截、安静时间、`pipeline_busy` 快败等**故意的静默**，见 §10）。查实不了的写 `未核实 + 卡在哪`，禁「应该是/大概」。

**统计**（随各节落盘逐节更新，终值见此处）：
- 池（多变体轮换）：待填
- 单点（固定字面句）：待填
- 模板串（f-string/占位符拼接）：待填
- 静默门：待填
- 未核实：待填

---

## 1. 统一话术池 user_copy（含 7 族豁免登记）

真身：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/user_copy.py`（纯常量模块，零 import 防装配环）。
垫片：`plugins/bot_unified_runtime/capabilities/user_copy.py`（PEP-562 `__getattr__` 活重导出，改这里＝改空壳，见底稿 §13.7）。
收编标准（文件头 L3-L4）：跨文件复用或多处同文案才入池；单点留原地。
改前必跑：`tests/test_user_copy_pool.py`（逐字节快照+引用点表达式锁定）、`tests/test_user_copy_unification_gate.py`（池外硬编码负向扫描）。

### 1.1 管理员门禁池 `ADMIN_GATE_TEMPLATES`（池 12 变体）+ 单点 `ADMIN_GATE_REQUIRED`
落点：`user_copy.py:32`（REQUIRED，池首条）、`:37-50`（12 变体元组）。形态：池 N 变体（`random.choice(...).format(action=...)` 取句 + `.format` 填 `<动作>`）。渠道：QQ/TG/Console/Mail 通用（走统一渲染，非渠道专属）。
- 原文（12 条，`{action}` 为占位）：
  ```
  要{action}，找管理员来操作。                          ← ADMIN_GATE_REQUIRED（池首，订阅族等引用点零行为变化）
  {action}需要管理员权限，守岸人做不了主。
  要{action}，得请管理员出面才行。
  {action}……这道门，我替你推不开。它只在管理员的权限里。
  守岸人的守则里，{action}不归我管。请管理员来，他们会处理好。
  钥匙不在我手中。想要{action}……请去找管理员，好吗。
  {action}越过了我的权柄。不是我不愿意……是只有管理员能做到。
  我认真考虑过了——{action}依然需要管理员。这份边界，我不会自己跨过。
  门后的事，我不便代劳。{action}……请让管理员来，我在这边看着。
  {action}需要管理员的印记。潮汐有它的航线，权限也是。
  抱歉，{action}不在我的海岸范围内。管理员那边……会为你做到。
  这件事，我只能说到这里：{action}要等管理员。别的，我都可以陪你。
  ```
- 触发条件（复现）：非 admin/super_admin 角色用户触发一个「仅管理员可执行」的动作时被拒时发；`action` 由调用点决定。**已定位调用点（跨域，池本身属本席，逐域文案属第二批）**：
  - `domains/chat_reply/capabilities/echo.py:73` action="看运行时状态"（`/bot status` 非管理员）、`:178`（另一 admin 子命令）。
  - `domains/ops/admin/runtime_logs.py:39` action="查运行时日志"、`domains/ops/admin/debug.py:75` action="看运行时排障记录"。
  - `domains/music/capabilities/music.py:431` action="改点歌输出模式"。
  - `domains/subscribe/capabilities/today_history.py:265` action="取消群推送时间"、`:323` action="设置群推送时间"。
  - 权限门定义在 `domains/policy/roles.py`（user/trusted/enterprise/admin/super_admin/blocked 六级）。
- 同一语义其它副本：`subscribe_v2.py:219`、`subscribe.py:263/342` 用的是**单点** `ADMIN_GATE_REQUIRED.format(...)`（不是池，固定第一句），action 分别 "看本群订阅"/"把订阅推送到本群"——**同义两处口径不同**（池轮换 vs 单点钉死）。

### 1.2 数据源临时失败池 `DATASOURCE_FAILURE_TEMPLATES`（池 5 变体）+ 单点 `DATASOURCE_TEMP_FAILURE`
落点：`user_copy.py:53`（TEMP，池首）、`:58-64`（5 变体）。形态：池 N 变体（`random.choice(...).format(reason=...)`，reason 传「<对象>暂时拉不到」式短语）。渠道：通用文本。
- 原文（5 条，`{reason}` 占位）：
  ```
  {reason}，稍后再试。                                ← DATASOURCE_TEMP_FAILURE
  {reason}，晚点再试试？
  {reason}，守岸人晚点再帮你看看。
  {reason}，潮水这会儿不顺，稍后再来一趟吧。
  {reason}，先放一放，过阵子再试一次。
  ```
- 触发条件：能力取上游数据源（HTTP/接口）失败且属**临时性**（非「无源→诚实不接」）时回。`reason` 由调用点决定。**已定位调用点（均属第二批域，此处仅登记 reason 短语以证触发面）**：
  - 金融族：`finance/data/stock_data.py:1400` + `finance/capabilities/stocks.py:89`（reason="美股行情暂时拉不到"）、`market_data.py:153` + `capabilities/market.py:70`（"行情数据暂时拉不到"）、`market_data.py:722` / `market.py:324,520`、`fx_data.py:302` + `fx.py:206`（"汇率数据暂时拉不到"）、`commodities_data.py:74`（"大宗商品行情暂时拉不到"）、`bond_data.py:80`（注释：数据源失败**必须**走本池，不得回退硬编码）。
  - 其它域：`location/capabilities/moegirl.py:426`、`media/capabilities/image_search.py:80`、`food/capabilities/eat.py:699`、`subscribe/capabilities/today_history.py:371`、`subscribe/capabilities/news.py:68` + `subscribe/feeds/news_feeds.py:97`（均 reason="快报暂时拉不到"）、`subscribe/capabilities/epic.py:111`、`core/credentials/platform_credentials.py:289,378`（:378 reason="查询失败"）。
- 同一语义其它副本：本池即单一事实源；旧版各域硬编码「…稍后再试」已被 Q-01 批收编，负向门 `test_user_copy_unification_gate.py` 拦再犯。

### 1.3 推送表写盘失败 `PUSH_SAVE_FAILED`（单点）
落点：`user_copy.py:67`。形态：单点固定句（无占位）。渠道：通用文本。
- 原文：`推送时间的改动没保存成功（写盘出错，我已记下原因）。稍后再发一次；还不行就找管理员看运行日志。`
- 触发条件：管理员在群里发「历史上的今天」推送时间设置/取消命令、**权限已过（是管理员）但落盘写文件抛异常**时回。调用点 `subscribe/capabilities/today_history.py:283`（取消分支）、`:341`（设置分支）——**两处同文案**（U9 收编动因）。前置：非管理员走 §1.1 门禁池，不会到这里。

### 1.4 运行环境异常共享尾段 `RUN_ENV_FAILURE_ADVICE`（单点，作尾段拼接）
落点：`user_copy.py:91`。形态：单点固定句，被 f-string 拼在域内首句之后。渠道：通用文本。
- 原文（尾段）：`稍后再试；还不行就找管理员看运行日志。`
- 触发条件：`/bot` 代码运行类动作在本机起不来。调用点（files 域，属第二批，登记以证触发面）：`files/capabilities/file_exchange.py:114`（前拼「语法检查通过 ✓；本机没能启动 Python 跑这段代码，这次运行不了。」）、`:117`（前拼「本机没法准备运行用的临时目录，这次跑不了。」）。

### 1.5 群聊能力失败降级池 `GROUP_FAILURE_ACK_TEMPLATES`（池 12 变体）
> 定义在本文件，但**触发点在 pipeline（A-19）**，正文与复现条件详列于 **§2.2**，此处仅登记归属。落点 `user_copy.py:75-88`。

### 1.6 豁免登记（7 条：故意没进池，`user_copy.py:13-28`）
1. `subscribe_v2.py`「群内添加订阅需要管理员。」——含群推送目的地上下文，非通用门禁；文件属并行禁碰域。
2. `subscribe.py` / `subscribe_v2.py`「没有权限操作该订阅。」——资源属主校验（非管理员门禁）；禁碰域。
3. `media_archive.py`「这个归档功能暂时只对超管开放，这份心意守岸人先记下了。」——超管门槛（`BOT_MEDIA_ARCHIVE_MIN_ROLE`），写「管理员」会失实；卖萌已按 Q-02 去除。
4. `group_info.py`「公告和精华只有管理员能看哦，先不给你翻这份啦。」——禁碰域（Q-02 卖萌体残留，待该域批次收口）。
5. `__init__.py`「只有管理员才能…」族——禁碰域（绝对不碰）。
6. `echo.py` `_HELP_ENTRIES` 内「…晚点再试试？」/「…稍后再试。」——help 文本对兜底行为的**历史引用示例**，非输出本体；改它牵动 command-catalog 同步门。
7. `content_parser.py`「…先把原链接放在这里，晚点我再试试：」——附原文链接的重试承诺（非纯失败告知）+ 第一人称自称，留待专项。

---

## 2. 私聊与群聊失败面（chat.py / pipeline A-19）

真身：`plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py`（私聊池）+ `domains/chat_reply/runtime/pipeline.py`（群聊降级发送）。

### 2.1 私聊人格失败话术池 `_PERSONA_FAILURE_MESSAGES`（池 12 变体，会话内游标轮换）
落点：`chat.py:618-631`（元组）、`chat.py:634-652`（`persona_failure_message()`，D9 修后**纯游标顺序轮换** `(offset)%n`，同会话连发不重复；无 session_id 才退回随机）。`_FAILURE_MESSAGE_CURSOR` LRU 上限 512（`:650`）。形态：池 N 变体。渠道：**仅私聊**（IMMEDIATE 发送）。
- 原文（12 条）：
  ```
  回应生成到一半，链路断了……再发一次，这次我会把它写完。
  超时了。不是不想答，是这一刻没能抵达……稍等，再喊我一次。
  刚才的回应沉进了水里。再来一次，我会把它捞起来给你。
  链路抖了一下，像风掠过琴弦。稍等片刻……再问一次，好吗。
  这一次没能稳定完成。不是你的问题……再试一次，就好。
  嗯……刚才卡住了。让我重整一下，你再发一次。
  回话没能靠岸。原因我记下了……稍后再来一趟。
  这一条没有写完。给我一次重写的机会……再说一次，好吗。
  响应迟到了太久，我先放它走了。再发一次……这次不会。
  刚才断开了。像潮水短暂的退离……再喊我，我就在。
  处理到一半失败了。原因我已经记下……先重试吧。
  这一刻没能接住你的话。缓一缓……再发一次就好。
  ```
- 触发条件（复现，两处 emit）：
  1. **LLM 侧失败** `_llm_error_result`（`chat.py:~2560-2615`，stage="llm"）：私聊发一句要模型生成的话 → 模型路由走完故障转移链仍失败（error kind ∈ `_SAFE_LLM_ERROR_KINDS` L657-676：config_missing/deadline_exceeded/timeout/network/rate_limited/server/provider_error/empty_response/auth/http/schema/model_not_found/… 未知 kind 归一 provider_error）→ 取本池一句。**前提**：`message.session_type` 不是 GROUP/CHANNEL（`is_group_or_channel` 为假，body 才非空，send_policy=IMMEDIATE）。
  2. **上下文装配失败** `_context_error_result`（`chat.py:2625-2661`，stage="context"）：私聊时人格/记忆等上下文装配抛错（kind ∈ `_CONTEXT_ERROR_KINDS`，缺省 provider_failed）→ 取本池一句。
  - 群/频道时**同两处**走 body="" + `SendPolicy.SILENT_AUDIT`，**不发**私聊池，改由 §2.2 群降级池接手。
- 同一语义其它副本：本池为私聊失败唯一事实源；与 §2.2 群池**语义不同**（池头注释明令不合并）。

### 2.2 群聊能力失败降级池 `GROUP_FAILURE_ACK_TEMPLATES`（池 12 变体，A-19，正文在 §1.5 定义）
落点：定义 `user_copy.py:75-88`；**发送实现** `pipeline.py:837-901` `_maybe_submit_group_failure_notice`，取句 `random.choice` 在 `:881`。形态：池 N 变体。渠道：群/频道文本（capability_id=`bot.group_failure_notice`，L891）。
- 原文：见 §1.5（12 条温和短句，全部只说「没走到/再叫我一次」，**不回任何错误细节**——脱敏红线，细节走管理员告警链/错误卡）。
- 触发条件（复现）：群成员 @ 了 bot 或触发某能力，能力执行返回**错误态结果**（`result.operational_issue is not None`）且会话类型为 GROUP/CHANNEL（`pipeline.py:705-708` 的 `_complete`）。此时：失败结果本身压成 body="" + SILENT_AUDIT（`:715-717`），另补一句池内文案。
- **节流门（进程内、会话级）**：`_GROUP_FAILURE_NOTICE_WINDOW_SECONDS = 300.0`（`pipeline.py:99`）——同一 `session_id` 300 秒内只发一次；`_GROUP_FAILURE_NOTICE_TRACK_CAP = 512`（`:101`）——跟踪会话上限，超了先逐过期键、仍超则 clear。fail-open：节流表/提交异常绝不影响主回执（`:879-880`）。
- **故意的静默（不走本池）**：`issue.kind == "pipeline_busy"`（超载快败）**直接 return 不发**（`:851-852`）；限流拦截、安静时间拦截根本不产生 operational_issue（在 policy/gate 阶段就被拒，见 §10），故也不发。
- 同一语义其它副本：无（A-19 批新立）。

### 2.3 `_GENERIC_OPERATIONAL_MESSAGE`（单点，疑似死常量）
落点：`chat.py:615` 原文 `这次暂时没能稳定完成，请稍后再试。`
- 触发条件：**未核实**——全树检索（`_GENERIC_OPERATIONAL_MESSAGE`）仅命中定义行本身，零引用点。疑为早期通用失败句、被 §2.1 人格池取代后遗留的休眠常量。**卡在哪**：无 import 侧字符串常量使用可追；不臆断其触发路径。登记以备用户核对是否可清理。

---

## 3. 错误卡族（error_report）

真身：`plugins/bot_unified_runtime/domains/ops/monitor/error_report.py`。统一入口 `maybe_submit_error_card()`（`:1057`），由 pipeline 的 `_internal_error` 旁路钩子在**能力抛异常**时调用。
开关与冷却：`bot_error_card_enabled`（缺省 True，`:189`）、`bot_error_card_cooldown_seconds`（缺省 60s，`:190/:258/:281`）；`ErrorCardGate.allow()` 进程内会话级滑动窗（`:291-296`）。
**两段式（A-rec）**：第一段本线程内联毫秒级发文本回执；第二段专用单线程池渲染诊断卡、经 `send_queue` worker 以 `deliver_after=now+3s`（`_CARD_DELIVER_DELAY_SECONDS=3.0`，`:129`）补发（≈3–33s）。全程 fail-open，函数自身不抛。
> **卡片图内文案（头部徽标「运行异常」/触发回显/栈摘录/配置快照/版本/IDs/页脚）不重抄**——见 `OUTBOUND-COPY-AUDIT.md` §十二 error_card 段 + `docs/rendering-contract.md`。本清单只收「以文本形式发出」的四组句子。

### 3.1 人话区池 `_HUMAN_TEXTS`（池 4 变体，会话内游标轮换）
落点：`:79-84`（元组）、取句 `_persona_text()`（`:337-348`，游标轮换 `(offset)%n`，同会话连发不重复）。形态：池 N 变体（`{exc}`=异常类型名）。渠道：文本（第一段回执）。
- 原文（4 条，`{exc}` 占位）：
  ```
  这条指令处理的时候出了岔子（{exc}），细节都在卡上了。要重试就再发一次。
  处理到一半卡住了（{exc}）。诊断都在卡上，稍后重试就好。
  这次执行没走通（{exc}）。原因我记下了，卡上有完整线索。
  链路抖了一下没接稳（{exc}）。细节都在卡上，再发一次就行。
  ```
- 触发条件（复现）：`bot_error_card_enabled=true` + 该会话**不在冷却窗内**（`emitted=True`）→ 能力抛异常 → 发「人话区一句 + 尾注 `_ACK_FOLLOWUP_HINT`」合并为文本回执（`:1129-1143`，dedupe `:ack`）。任何能力的 handler 未捕获异常都会进此入口（如某 `/bot` 子命令内部报错、能力取数逻辑抛非受控异常）。

### 3.2 补发尾注 `_ACK_FOLLOWUP_HINT`（单点，拼接用）
落点：`:123` 原文 `详细诊断卡随后补发。`
- 触发条件：与 §3.1 同路径——第一段文本回执末尾固定拼此句（`:1130`），告知卡随后到。冷却期内（§3.3）**不带**此句。

### 3.3 冷却期降级纯文本池 `_COOLDOWN_LINES`（池 12 变体）
落点：`:91-104`（元组）、取句 `cooldown_line()`（`:970-974`，`random.choice(...).format(exc=...)`）。形态：池 N 变体（`{exc}` 占位）。渠道：文本。
- 原文（12 条，`{exc}` 占位）：
  ```
  又一条指令出了岔子（{exc}）。细节都在刚才那张卡上……先看那张，我盯着重试。
  （{exc}）又出现了。诊断我早已写在刚才那张卡里……不必重复，先看它。
  同一个地方，又磕了一下（{exc}）。那张卡是完整的记录……稍等，我会把它理顺。
  （{exc}）还在。刚才那张卡，就是此刻的全部答案……先按它看看，我继续盯着。
  这一条，停在了（{exc}）。不必担心……卡上的细节，我一遍遍核对过。
  （{exc}）仍未退去。诊断卡已经在你那里了……我等的，是它彻底平静。
  又是它（{exc}）。有些错误需要一点时间才能退潮……卡在上方，稍安。
  （{exc}）像反复的潮。刚才那张卡记录了它的样子……按图索骥，很快。
  这条又停在了（{exc}）。细节我不再重复……都在刚才那张卡里。
  （{exc}）的影子还在。我看得到它……你也能，在那张卡上。
  又一次（{exc}）。先看那张卡……我负责把这片海面抚平。
  （{exc}）仍未平息。卡已经发过……等潮水退去，一切会重新可用。
  ```
- 触发条件（复现）：同一会话在冷却窗（缺省 60s，`bot_error_card_cooldown_seconds`）内**再次**触发能力异常 → `emitted=False`（`:1112-1113`）→ **只发**一句本池纯文本、**不重复发卡**（`:1114-1127`，dedupe `text_only`）。语义红线：每句都指回「刚才那张卡」。

### 3.4 求助指引 `_HELP_TEXT`（卡页脚）/ `_FALLBACK_HELP_TEXT`（纯文本版）——**有意双份，勿合并**
落点：`_HELP_TEXT` `:111-115`（仅注入卡片页脚，`:753`）、`_FALLBACK_HELP_TEXT` `:116-120`（无图/渲染失败时的文字版，`build_text_fallback` `:760-792`，`:754/:792`）。形态：单点固定句（两段字符串字面拼接）。渠道：卡内文字 / 纯文本消息。
- `_HELP_TEXT` 原文：`这张图是我自动生成的诊断卡（不是控制台截图），版本、系统、配置快照和 IDs 都在卡上且已脱敏，转给创造者就好；完整栈在 runtime 事件日志里，管理员可以查到。`
- `_FALLBACK_HELP_TEXT` 原文：`这条是自动生成的文字版诊断（本次没带图），版本、系统、配置快照和 IDs 都在上面、同样脱敏，转给创造者就好；完整栈在 runtime 事件日志里，管理员可以查到。`
- 触发条件：
  - `_HELP_TEXT`：诊断卡**成功渲染成图**并投递时，卡在页脚展示此文案（属图内文案，本清单仅登记来源）。
  - `_FALLBACK_HELP_TEXT`：playwright/渲染后端不可用或渲染抛错 → 第二段退化为**全量诊断纯文本**（`build_text_fallback`），末尾用此文案（无图语境「这张图」会悬空，故另写一份，E-11 裁定）。
  - 二者措辞差异是**设计**（见底稿 §13.8），非漂移。

---

## 4. 提醒到点五型（reminders）

真身：`plugins/bot_unified_runtime/domains/schedule/store/reminders.py`（到点文案 + 治理回执）+ `domains/schedule/capabilities/reminder.py`（勾选回话）+ `domains/schedule/delivery.py` / `service/schedule_service.py`（投递调度）。
投递触发总述：`__init__` 注册的**每分钟调度任务**调 `ReminderStore.due()`（`reminders.py:472`）取应投事项 → `build_reminder_text()`（`:718`）出文案 → 走统一发送队列。**「现在」统一经 timesync**（`:598`）。
迟到治理（`reminders.py:64-66`、`:478-485`、`LATE_DELIVERY_GRACE=30min`）：
- 迟到 ≤30 分钟 → 照常投递；
- 迟到 >30 分钟但未超 `grace_hours`（默认 24h）→ **不顺延、原样补投**？否——见 `:480-484` 注释：迟到>30分钟且已过点者**顺延到下一个同一时刻**（多为明天同一刻）；
- 迟到超 24h → 标记 expired 作废；
- 顺延/作废均**不静默**（A-05，见 §4.2 治理回执）。
防风暴门（`delivery.py:6`、`schedule_service.py:527`）：每主体**每分钟 ≤3 条、每小时 ≤20 条**，超限合并摘要（digest）。

### 4.1 到点督促分型模板 `_REMINDER_TEXT_TEMPLATES`（5 型，各 1 变体，A-13 收编为常量表）
落点：`reminders.py:668-704`（dict）、`build_reminder_text()` `:718-733`、`classify_reminder_kind()` `:653-660`、`_pick_template_variant()` `:707-715`（当前各型单变体→恒取首个；多变体时按 (persona,seed) sha1 稳定散列取模，零随机）。形态：模板串（`{text}`=事项复述），**分型选型非轮换池**。渠道：私聊/群（原会话）文本。
- 分型判据（复现，关键词命中即归类，顺序 medicine→appointment→shopping→todo→custom 兜底，`_KIND_KEYWORDS` `:~620-650`）：
  - medicine：含「药/吃药/服药/胶囊/片/剂量/疫苗/复查/体检」等；
  - appointment：含「开会/见面/约/截止/答辩/考试/上课/挂号…」等；
  - shopping：「买/购物/下单/抢购/秒杀/快递/取件/外卖/囤/缴费」；
  - todo：「写/做/复习/预习/背/练/刷/锻炼/运动/跑步/喝水/休息/睡觉/起床/收衣服/晾衣服/洗澡」；
  - custom：以上都不命中（兜底）。
- 原文（5 条，`{text}` 占位）：
  ```
  medicine    ：……到时间了，该吃药了。\n你之前说过的：{text}。\n喝口水，慢慢来。身体的事，不能总交给以后。我陪着你。
  appointment ：（频率轻轻响了一声，像钟摆）时间到了。\n你之前说过的：{text}。\n这一件有时间在前面等着，别让它等太久。去吧，我守在这里。
  shopping    ：到点了。\n你之前说过的：{text}。\n要带走的东西，别落在世界的另一头。回来的时候，海还在这边。
  todo        ：（潮声很轻）到时间了。\n你之前说过的：{text}。\n一步一步来就好，不着急。我守在这里。
  custom      ：（远处的海浪声）……到时间了。\n你之前说过的：{text}。\n我就守在这里。慢一点也没关系，记得去做。
  ```
- 触发条件（复现）：用户先设过提醒（自然语言「12点提醒我吃饭」/`提醒列表`族，`bot_reminder_enabled` 开），到点（±30min 窗内）由每分钟调度任务投出对应型文案。若 `reminder_id` 以 `gov-` 前缀开头（治理回执伪装事项），`build_reminder_text` **原样放行其 text、绝不套分型模板**（`:725-728`，防「吃药」关键词误包装回执）。

### 4.2 治理回执模板 `_GOVERNANCE_RECEIPT_TEMPLATES`（postponed 2/expired 2/mixed 1，A-05）
落点：`reminders.py:169-199`；生成在 `due()`（`:241/:249/:254`），事项串由 `_receipt_items_label`（`:205`）拼（超 3 件折叠「等 N 件」、单件截断 30 字 `_RECEIPT_ITEM_MAX_CHARS/_RECEIPT_MAX_ITEMS` `:201-202`）。形态：模板串（`{items}`/`{dropped}` 占位）+ 池多变体稳定散列选一。渠道：文本。
- 原文：
  ```
  postponed[0]：（潮声轻轻）你不在的时候，「{items}」到了时间，我没能在对的一刻叫你。\n我把它挪到了明天同一个时刻——到点我会再提醒你一次。
  postponed[1]：……「{items}」到点的时候你不在。\n迟到的催促太生硬了，先把它放到明天同一个时间。我记着，到点再来叫你。
  expired[0]  ：（翻了翻清单）「{items}」隔得太久了，大概已经不需要我催。\n我先替你放下——要是还想续上，再跟我说一声就好。
  expired[1]  ：「{items}」等了一天也没等到人，我想它多半已经过去了。\n替你从待办里放下；要是其实还没有，再告诉我一遍时间就好。
  mixed[0]    ：（潮声很轻）你不在的时候，「{items}」错过了时间，我把它挪到了明天同一个时刻。\n另有「{dropped}」隔得太久，我猜已经不用我催，先替你放下。
  ```
- 触发条件：`due()` 巡检时本轮**发生了顺延**（迟到>30min 未超 24h）→ postponed 句；**发生了作废**（>24h）→ expired 句；**两者同时**→ mixed 句（`{items}`=顺延件、`{dropped}`=作废件）。按会话折成至多一句（`gov-` 前缀事项随本轮投递）。治理不再静默是 A-05 的明文要求。

### 4.3 自然语言勾选回话 `_CHECKOFF_*`（8 条单点模板，A-13 收编）
落点：`capabilities/reminder.py:168-196`；引用点 `:415/:418/:436/:448/:458/:468/:546/:563/:714`。形态：模板串（`str.format` 填参，函数体禁 f-string 直拼）。渠道：文本。
- 触发条件（复现）：用户说「<事项>做完了」（自然语言勾选，对象=未完成提醒 + 笔记待办，包含 + 编辑距离模糊匹配 `:738+`）。追问态 TTL 300 秒（`_CHECKOFF_PENDING_TTL_SECONDS` `:159`）、进程内会话上限 256（`:160`）。分支→文案：
  ```
  确认成功           → _CHECKOFF_DONE_TEMPLATE（:168）：（轻轻点头）嗯，「{name}」——已经替你放下了。\n剩下的事不着急，一件一件来。我都在。
  只对上/需确认       → _CHECKOFF_CONFIRM_TEMPLATE（:172）：嗯……你说的是「{label}」这件吗？只对上了一半，我不敢替你做主。\n是的话回个「是」，我替你放下；不是就算了。
  多件并列歧义        → _CHECKOFF_AMBIGUOUS_TEMPLATE（:177）：有几件事都对得上，是哪一件完成了？\n{lines}\n回个编号（比如「1」）就行，我替你放下。
  裸序号需提示        → _CHECKOFF_NEED_NUMBER_TEMPLATE（:181）：嗯，是哪一件呢？回个编号就行：\n{lines}
  单候选只挂一件      → _CHECKOFF_CONFIRM_ONLY_TEMPLATE（:182）：这里只挂着一件——「{label}」。是的话回个「是」，我替你放下。
  编号越界            → _CHECKOFF_OUT_OF_RANGE_TEMPLATE（:185）：这个编号不在刚才的清单里——回 1 到 {max_index} 就行。过了太久的话，再说说「{query}做完了」也可以。
  追问过期(TTL 300s)  → _CHECKOFF_EXPIRED_TEMPLATE（:189）：刚才那件「{query}」的确认过了时效——再说一遍「{query}做完了」，我重新帮你对一对。
  候选已消失          → _CHECKOFF_GONE_TEMPLATE（:193）：（翻了翻清单）「{label}」刚刚已经不在待办里了——也许已经替你放下，或者提醒过你了。
  ```
- 同一语义其它副本：gone 模板原两处逐字重复，A-13 已归一为单点（`:164` 注释）。

---

## 5. 主动推送与日常助理（digest / meal / daily_assist / campus）

真身分布：`__init__.py`（群摘要 + 到点吃什么）、`domains/assistant/daily/capabilities/daily_assist.py`（收件箱命令面）、`domains/assistant/daily/store/daily_assist.py`（早/晚报正文池）、`domains/assistant/campus/campus.py`（校园转发前缀）。全部**纯文本走发送队列，不出卡**。轮换工具 = `pick_variant(tag, POOL, **kw)`（全局游标按序循环，同池连发不重复）。

### 5.1 群每日通讯摘要开场 `_DIGEST_PUSH_INTRO`（单点 + 模板串）
落点：`__init__.py:3135`（引子）、`:3139-3141` `_build_digest_push_text`（`f"{引子}\n{summary.strip()}"`）、默认钟点 `_DIGEST_PUSH_DEFAULT_CLOCK=(21,30)`（`:3136`，解析 `:3148-3155`）。capability_id=`bot.group_digest_push`（`:3206`）。形态：模板串（引子单点 + 摘要生成物）。渠道：群文本。
- 原文（引子）：`今天群里的对话，我都悄悄记下了：`
- 触发条件（复现）：`bot_group_digest_push_enabled`（`:4265` 缺省 True）+ 每日 cron（`bot_group_digest_push_time` 默认 `"21:30"`，`:3257`，注册器 `_register_digest_push_scheduler` `:3228/:4268`）到点 → 向**群摘要白名单群**推送当日群摘要；dedupe 按日期；**非白名单群零推送**（AGENTS #33 亦记：白名单/摘要读零行存量缺陷待修）。摘要正文 = LLM 生成物（不属模板；LLM 失败走既有降级）。

### 5.2 到点吃什么开场池 `_MEAL_OPENERS`（池 6 变体）
落点：`__init__.py:3299-3306`（元组）、`_build_meal_push_text`（`:3309-3318`，`pick_variant("meal_open", …, name=, suffix=)`）。形态：池 N 变体（`{name}` 菜名 + `{suffix}` 后缀）。渠道：私聊文本。
- 原文（6 条，`{name}{suffix}` 占位）：
  ```
  到饭点啦，守岸人替你挑了这个：{name}{suffix}
  饭点到了。今天就吃它吧：{name}{suffix}
  到点了，守岸人翻了很久，选了这个：{name}{suffix}
  开饭啦。今天的答案是：{name}{suffix}
  饭点准时到。守岸人把这个端上来：{name}{suffix}
  到吃饭的点了，今天轮到它：{name}{suffix}
  ```
- 触发条件（复现）：`bot_daily_assist_enabled` + `bot_daily_assist_push_user_ids` 非空 + 到 `bot_daily_assist_meal_times`（AGENTS #32 缺省 11:15/17:15）配置的点。菜 = `food.md` 自定义优先 + 内置库兜底，jsonl 历史 7 天不重复（`meal_display_name`/`pick_variant` 于 `store/daily_assist.py`）。**名单空 → 整链不注册**（`:4272`，绝不猜人）。

### 5.3 收件箱命令面四池（daily_assist capability，各 6 变体）
落点：`domains/assistant/daily/capabilities/daily_assist.py:30-78`。触发前置：`is_daily_assist_command(text)` 命中 `_DAILY_ASSIST_RE`（RouteKind.DAILY_ASSIST，priority 42，帮助 topic=收件箱）。形态：池 N 变体（`pick_variant`）。渠道：私聊/群文本。
- `_HELP_VARIANTS`（`:30`，引用 `:113`）触发：只发「收件箱」不带内容且处于帮助语义时。原文（6）：
  ```
  收件箱的用法：发「收件箱 内容」就把事情记下了，早报守岸人会一并整理；发「收件箱」能看现在攒着的。
  想记事，发「收件箱 内容」，守岸人替你收着；发「收件箱」不带内容，看的就是目前攒下的。
  「收件箱 内容」是记一笔，早报时守岸人会理给你；只发「收件箱」，就把攒着的翻出来看看。
  把想到的交给收件箱：发「收件箱 内容」记下；发「收件箱」，看守岸人目前替你攒着的。
  用法很简单：「收件箱 内容」记事，「收件箱」看清单。记下的事，早报会一并整理。
  随手记用「收件箱 内容」，守岸人会收好，早报再理给你；发「收件箱」不带字，就能翻看攒下的。
  ```
- `_QUERY_EMPTY_VARIANTS`（`:~44`）触发：发「收件箱」（无内容）且收件箱**为空**。原文（6）：
  ```
  收件箱空着呢。想到什么，随时丢进来。
  现在什么都没攒着。守岸人守着收件箱，随时等你。
  收件箱干干净净，一件待办都没有。
  空空的，还没攒下事情。有想记的就说。
  守岸人看过了，收件箱现在是空的。想到随时说。
  这里很安静，还没有事情进来。你开口，守岸人就记。
  ```
- `_QUERY_LISTING_VARIANTS`（`:~52`）触发：发「收件箱」（无内容）且**有攒着的事**。原文（6，`{n}`/`{listing}`）：
  ```
  收件箱里攒着 {n} 件：\n{listing}
  现在攒了 {n} 件事：\n{listing}
  守岸人替你记着 {n} 件：\n{listing}
  攒下的有 {n} 件，都在这儿：\n{listing}
  收件箱里躺着 {n} 件事，逐条给你：\n{listing}
  记着的共 {n} 件，守岸人列给你：\n{listing}
  ```
- `_CAPTURE_VARIANTS`（`:~61`）触发：发「收件箱 <内容>」记一笔成功。原文（6，`{line}`）：
  ```
  守岸人收好了：{line}\n早报的时候一并理给你。
  记下了：{line}\n放进收件箱，早报再细看。
  好，收进去了：{line}\n明早守岸人把它排进早报。
  收到了：{line}\n先攒着，不急。
  这件事守岸人替你记着：{line}\n丢不了。
  收好了：{line}\n等早报一起看。
  ```

### 5.4 早报/晚报正文池 + 小标题（store/daily_assist.py）
落点：池 `store/daily_assist.py:267-330`（游标 `_VARIANT_CURSORS` `:~262`），装配函数 `build_morning_brief`（`:~363-`，引用 `:373/:401`）、`build_evening_brief`。触发：`bot_daily_assist_morning_time`（AGENTS #32 缺省 09:00）/ `bot_daily_assist_evening_time`（缺省 21:00）到点 + push 名单非空 + 走 LLM 划重点（主路由失败回退原文）。形态：开场池 + 固定小标题拼接。渠道：私聊文本。
- 池原文：
  ```
  _MORNING_EMPTY_OPENERS（6，收件箱与清单皆空时）：
    早。收件箱和清单都干干净净的，今天轻装上阵。
    早上好。守岸人看过了，没有攒着的事，也没有挂着的事，安心过今天。
    早。今天没有待办压着，时间都是你自己的。
    新的一天。守岸人这边什么都没攒着，你可以慢慢来。
    醒来了就好。收件箱干净、清单干净，守岸人没什么要催你的。
    早。两边都空着，守岸人陪你轻轻松松过今天。
  _MORNING_OPENERS（6，有事项时）：
    早。守岸人把今天要注意的理出来了：
    早上好。今天手上有这些事，守岸人给你排好了：
    早。新的一天，守岸人先把挂着的事摆出来：
    醒了就好。守岸人把今天的事都列在这儿了：
    早安。守岸人记着的都在下面，过一遍再开始今天：
    早。不着急，守岸人陪你对一遍今天的安排：
  _MORNING_IDEA_NOTES（6，想法池有 N 条）：
    （想法池还有 {n} 条，守岸人先替你收着）
    （想法池里躺着 {n} 条，先不吵它们）
    （另外，想法池攒了 {n} 条，先不动）
    （想法池还有 {n} 条，等你哪天想捡起来）
    （想法池里存着 {n} 条，都好好的）
    （想法池 {n} 条，守岸人看着呢，不急）
  _EVENING_OPENERS（7，晚报开场）：
    今天辛苦了。守岸人把这一天的账理了理，睡前看两眼就好。
    忙完就早点歇着。守岸人把今天记下的事拢了一遍，放在下面了。
    晚上好。一天到头了，守岸人替你把小事都记着呢。
    今天也走到晚上了。守岸人在，慢慢看，不着急。
    夜深了，别撑着。守岸人把今天的事替你收了个尾。
    今天辛苦了。守岸人守着这些小事，你安心休息就好。
    到歇下的点了。守岸人把一天的事理了一份，你过目就好。
  _EVENING_INBOX_EMPTY_LINES（6，当日零新增）：
    收件箱今天很安静，没有新记下的事。
    今天没有人往收件箱里放事情，它也歇了一天。
    守岸人看过了，收件箱今天零新增。
    收件箱空空的，今天没攒下什么。
    收件箱今天没进新东西，干干净净的。
    守岸人这边也是空的，你今天没往里丢事，这样也挺好。
  _EVENING_INBOX_COUNTED_LINES（6，当日进了 N 条）：
    收件箱今天进了 {n} 条，都归好档了。
    今天记下的 {n} 条，守岸人都替你收好了。
    {n} 条新的进了收件箱，已经放进归档里了。
    守岸人把今天进来的 {n} 条都理好了，归了档。
    收件箱今天添了 {n} 条，都放得妥妥的。
    今天攒下 {n} 条，守岸人已经替你理进档案了。
  _EVENING_IDEA_NUDGES（6，想法池提示）：
    有空的时候，挑一条让它转正？
    想法不急着动，哪条熟了就把它请进「已计划」。
    有看对眼的，就提拔成正经任务吧。
    这些先放着想，哪天想落地了再挪不迟。
    守岸人先替你收着，想捡起哪条随时说。
    别有压力，放着也是一种安排。
  ```
- **固定小标题字面**（非池，简报结构骨架，`build_morning_brief`/`build_evening_brief` 逐条 append）：早报 `【收件箱】`/`【进行中】`/`【已计划】`/`【划重点】`；晚报 `【还挂着的】`/`【之后的安排】`/`【想法池】`/`【替你想了想】`。这些是模板串的固定段；`llm_summary`/`llm_suggestion` 段为 LLM 生成物（非模板）。

### 5.5 校园转发前缀 `_CAMPUS_FORWARD_INTRO`（单点 + 模板串）
落点：`domains/assistant/campus/campus.py:32`（前缀字面量 `【校园转发】`）、`build_campus_forward_text()`（`:81-90`，`prefix = f"【校园转发】群{group_id} {sender_name}："` + 原文按剩余预算截断、超预算补 `…`）。垫片重导出 `capabilities/campus.py:10`。形态：模板串。渠道：**仅私聊主人号**（纯监听，绝不向学校群发）。
- 原文（前缀模板）：`【校园转发】群{group_id} {sender_name}：{原文(截断)}`（发言人无名时省略「：」段；`_CAMPUS_FORWARD_MAX_CHARS=1500` AGENTS #33）。
- 触发条件（复现）：三重来源门全通过——`bot_campus_enabled` ∧ `bot_campus_self_ids`（学校号 2300230562）∧ `bot_campus_group_whitelist`（`*` 通配放行全部；**任一空=整链不装配**，AGENTS #33）；学校号所在**群**来**文本消息**（被动 matcher priority=8 block=False）→ message_id 幂等去重（campus.sqlite3，90 天 prune）→ 门内首条构造此转发私聊投递。**门外/空文本/重复 → 不生成**（`:131-132`）。

---

## 6. Mail 渠道（mail_bridge + _mail_html_body + Re: 主题）

_待填。_

---

## 7. Telegram 渠道（caption 策略与截断）

_待填。_

---

## 8. 纯文本变换规则（plain_text / roleplay / renderer 分段）

_待填。_

---

## 9. 运营告警可见文案（alerts）

_待填。_

---

## 10. 静默门总表（故意不发文本的所有情况）

_待填。_

---

## 11. 第二批待做域清单（骨架 + 已定位的入口文件:行）

_待填。_
