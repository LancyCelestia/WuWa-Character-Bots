# v21r5 U17-REVIEW-3 席工作日志（U17-CAMPUS-WIRE runbook + 规约测试 事前对抗评审）

> 席位：U17-REVIEW-3（重派第三任；前两任死于平台故障零进度）。只读席：零代码编辑，唯一写面=本 log。
> 对象：`docs/design/v21r5-u17-implementation-runbook.md`、`docs/design/audit-20260920-unify-U17-campus-wire.md`、
> `tests/test_campus_digest.py`、`docs/design/v21r5-CAMPUS-log.md`、root `__init__.py` 旁路、
> `domains/assistant/campus/campus.py`。
> **现场说明**：实施席（U17-CAMPUS-WIRE）在本席评审期间并行施工且中途收口——本席实跑目击其
> 2 failed 中间态→29/29 全绿全过程。评审产出=计划面判定 + 中间态缺陷目击 + 终态机制核实。
> 本席实跑证据（全部离线，`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 --basetemp=$TEMP/u17rev3-tmp* -p no:cacheprovider`）：
> ① campus 全文件终态 **29 passed**（4.89s）；② 棘轮五套件合跑（campus+outbound_v21+F3+feature_gate+subfeatures）**127 passed**（19.90s）；
> ③ reviewer 泄漏面 python 探针 8 样例；④ AST 提取 handler 双探针（NameError 定性）；⑤ ruff 三文件 **All checks passed**。

---

## 攻击面逐条判定

### 1. 纯监听红线 —— **判定：零削弱（verified）**

- 目标推导结构性安全：`_complete` 取 `target_id=message.group_id or message.sender_id`（`domains/chat_reply/runtime/pipeline.py:828` 实读）；
  builder 恒 `group_id=None`（campus.py 实读）→ 即使 session_id 写错，target 也恒为 notify_qq 私聊。
- review 负锁真实存在：PERSONAL 正文+GROUP 会话 → `approved=False`（`domains/render/reviewer.py:197-203`），
  管线对一切 `not review.approved` 一律回 `ReceiptState.BLOCKED`（`pipeline.py:741-748`）——review 的
  `action=MOVE_PRIVATE`（非 BLOCK）**只进审计字段，不影响回执态**。`test_no_outbound_request_ever_targets_school_group`
  半 (a) 的断言机制成立（本席实读核实，非臆断）。
- handler 与域文件零平台发送面：结构锁绿 + campus.py 六禁词 grep **零命中**（exit=1 实证，含 docstring——
  该锁是子串级，实施席已把 `CampusForwardService` 旧 docstring 里的 "SendRequest" 一并清掉）。
- A-19 边角（设计语义，见 D1）：`_maybe_submit_group_failure_notice` 对 GROUP 消息+能力失败**绕过 review 直接入队**、
  目标=message.group_id（`pipeline.py:893-924` 实读）。若未来有人误把 GROUP 会话喂给 campus 能力且能力失败，
  会向学校群发降级文案。**当前不可达**：消息恒 PRIVATE + 能力闭包纯格式化不可失败。记录为负锁未覆盖角。

### 2. review 门 fail-closed —— **判定：行为已核实；规约测试零覆盖（缺口 I1）；runbook「路径」声称与实现不符（D2）**

- **拦截面实测**（python 探针实跑 `_unsafe_output_reasons`）：
  - 命中即 BLOCK：`token=值`、`api_key=值`、`cookie=值`、`authkey=值`、`authorization: Bearer …`、`bearer sk-…`、
    裸 `sk-`（≥9 字符）、4 个注入标记（`[UNTRUSTED_USER_TEXT]` 等）。
  - **不命中**：`BOT_WEATHER_KEY=abc123`（无 `api` 前缀）、`C:\Users\…` 盘符路径——**reviewer 无路径模式**。
  - `redact_local_secrets` 全树调用点 grep：campus 收编链路（能力→review→render→queue→sender）**无一处**经过它
    （chat.py:2439/download.py/tts 等各自调用，campus 不在其列）。
- **结论**：runbook 反复声称「密钥/**路径**形态命中即 BLOCK」（§1.4 表 #1、§1.5 裁定点①、audit §0.4 review 行）的
  「路径」半句与实现不符。含盘符路径或 `BOT_XXX=` 形态的教务通知收编后**仍原样直达主人**（与旁路同）；
  收编真正补上的缺口=api_key/token/cookie/authkey/sk- 五类形态。
- **BLOCK 后果**（`pipeline.py:741-761` 实读）：回执 BLOCKED transport=reviewer、
  `public_message="输出未通过安全或隐私检查。"`——该 public_message 只存回执/审计，**handler 忽略回执返回值 →
  主人零接收（静默）**；无告警、无降级文案、无管理员通知。审计留痕 stage=review + private_debug=reasons。
  且该条**永久丢失**：store 已在 record() 记账，同 message_id 重放 record()=None 永不再进管线。
- **规约测试覆盖**：29 例中**无一**覆盖「campus 正文含泄漏形态 → BLOCK + 零入队 + 主人静默」。裁定①用户若选 A，
  应明确接受「命中即静默丢」语义。→ 缺口 I1。

### 3. 幂等双保险 —— **判定：并存无冲突，顺序假设已被测试锁定（verified）**

- 层序（实读）：`store.record_message`（record() 内，最前）→ 中央 claim（`_prepare` 尾、全部门禁后，A-18 注释 :654-661）
  → 队列 dedupe（dedupe_key 公式 `bot.campus_forward:private:<owner>:<mid>`，`pipeline.py:835-838`，与测试断言一致）。
- claim 键=`adapter|bot_id|message_id` 且**按 capability_id 隔离**（`event_idempotency.py` 模块 docstring+`claim()` 实读）。
  合成消息 bot_id=push_bot_id 与源消息 id 是「混合身份键」，但同键不同能力互不影响 → 与主人真实私聊事件无跨污染面。
- 门禁 BLOCK 不占中央键（claim 在门禁后），但 store 已记账 → 重放不再转（与 #5 永久丢失同源）。
- 测试：`test_handler_duplicate_message_id_forwards_once`（store 先行）+ `test_central_claim_adds_second_idempotency_layer`
  （真 EventIdempotencyTable，second=BLOCKED+零入队）→ 双层都锁住了。无缺口。

### 4. 1501 字边缘 —— **判定：verbatim 契约在任何降级路径都不破坏（verified）**

- forward 触发：`should_forward_long_text`: `len(text.strip()) >= min_chars`（`renderer.py:480-489`），min_chars 缺省 1500
  → 1501 字满额正文在缺省下确会转合并转发（`pipeline.py:781-798` 实读；条数规则 1501/900=2 节点 <4 不触发）。
- **fallback 实证链**（`domains/transport/sender/onebot.py` 实读）：forward API 任何失败（含 NapCat 异常拒绝，M18）
  → `_call_optional_onebot_api` 收敛为 `_FORWARD_API_UNAVAILABLE` 哨兵（:1150-1168）→ 落 `build_onebot_message_segments`
  → `segments or [_text_segment(content.text_fallback)]`（:237-245）→ **单条 1501 字原文**，与旁路逐字节同形。
  chunks 拆分路径仅 `content_type=="chunks"` 触发（:636），campus fallback 不经此路。
- 结论：runbook 裁定②选项 A 安全；唯一形态差=forward 成功时 2 节点折叠（生产 `BOT_RENDER_FORWARD_MIN_CHARS`
  现值 unknown——本席禁读 .env，VERIFY 需用户确认或双形态都接受）。

### 5. 三态行为差 —— **判定：8 项清单逐项核对完毕；2 项无测试（I1/I2），1 项已被实现偏差消解**

| # | runbook 清单项 | 核对结果（实读坐标） | 测试覆盖 |
|---|---|---|---|
| 1 | review 门 | 拦截面比文档窄（见 2）；BLOCK=静默永久丢 | **无**（I1） |
| 2 | 1501→合并转发 | 机制成立；fallback 无契约破坏（见 4） | 无（unknown 生产值，可接受） |
| 3 | runtime 暂停拦截 | BLOCKED "统一运行时已暂停。"（`pipeline.py:514-546`）；**runbook 只写「被拦」未写该条永久丢失**（store 先记+重放不再转） | **无**（I2） |
| 4 | offload 池饱和 SKIPPED | **已消解**：实施席改用 handler 内 `_offload` 本地 async 包装、不走聊天池（代码注释自述「绝不因池饱和吞转发」）→ busy 分支对 campus 结构性不可达；runbook 行为差 #4 与其片段（`offload_capability(...)`）双双过时 | 不再适用 |
| 5 | QUEUED→IMMEDIATE | `decision.send_policy=IMMEDIATE`（`pipeline.py:677`）确认；队列 worker 投递语义不变 | 端到端例隐式覆盖（SENT） |
| 6 | dedupe 公式 | `pipeline.py:835-838` 与测试断言逐字一致 | 有 ✓ |
| 7 | cooldown 惰性 | 非 chat 限流恒 bypass（audit §0.4，限流器 non_chat 路径） | 无（no-op，可接受） |
| 8 | adapter 字段 | message.adapter 带出（`pipeline.py:848`） | 无（装饰性） |

- 控制面停用面：feature_gate BLOCK → BLOCKED transport=policy "这项功能暂时不可用。"（`pipeline.py:495-512`）；
  `test_campus_forward_registered_for_feature_gate` 只测 ALLOW 面，disabled 面 campus 无定向用例（通用门代码，M6）。
- quiet_hours/限流不吞：checker `capability_id not in {"bot.chat","bot.content"}` → `direct_request_bypass` 恒放行
  （`quiet_hours.py:116-121` 实读）；测试对 `pipeline.quiet_hours_checker._settings_source` 的补丁**有效**
  （构造器属性名实读 :76 + property callable 分支实读 :80-89）→ 该负锁是真绊网，非 vacuous。

### 6. 坐标漂移与作用域 —— **判定：风险真实兑现过一次，被内容锚+实施席临场修正救回；留一个脆弱耦合（M1）**

- runbook 全部行号已过期（实测漂 +15）：matcher 5012→**5027**、handler 尾 5034-5044→**5045-5059**、submit 5044→**5059**。
  outbound_registry campus 条目已被同波审计刷到 5027（note 自述），runbook 文字仍写 5012。内容锚（`request = await
  asyncio.to_thread(...)` 等）全部仍准确——实施席按内容锚施工未踩坑。
- 「import 原地扩展零增行」已兑现：`:36` 现为单行三名字导入（实读）。
- **runbook 缺陷（本席实跑目击引爆）**：§2.2 片段让 handler 引用 `offload_capability` 全局名——生产作用域确实存在
  （`_register_nonebot_handlers` 顶部内联 import，约 :3585-3590，runbook「:3588 同函数作用域」属实）；但**测试注入
  env（`_campus_handler_env`）无此名、runbook 亦未要求注入** → AST 提取执行必 NameError。本席在实施中途实跑目击
  `test_handler_dispatches_through_central_pipeline` + `test_handler_duplicate_message_id_forwards_once` **2 failed**
  （此期间另 9 个原 xfail 例因不执行转发路径而 vacuously 通过）。实施席最终以 handler 内 `_offload` 本地包装绕开。
- **M1 脆弱耦合（本席双探针实证）**：`_offload` 注解引用 `IncomingMessage/CapabilityResult`，测试 env 不注入这两个
  名字，测试能过**全靠** tests 文件自身的 `from __future__ import annotations` + `_extract_handler` 的 `compile()` 未传
  `dont_inherit`（默认继承调用方 future flags → 注解存字符串不求值）。探针 A（caller 无 future import）→
  `NameError: name 'IncomingMessage' is not defined`；探针 B（caller 有）→ 正常跑通。生产无恙（root 有 future import，
  注解恒字符串）。任何人给 `compile()` 加 `dont_inherit=True` 或删测试模块 future import → 4 个 handler 例全炸。
- S0 四条注册门 FAIL 警示**已过时**：`bot.file/bot.group_welcome/bot.cookie_login/bot.cookie_expiry_notice` 已由
  F3/U3 波补登（`capability_registry.py:533-548` 实读），本席五套件合跑 127 passed 含 feature_gate 全绿——
  runbook §2.5.2「存量基线 FAIL 勿扩权代修」的警示对象已不存在，照文档核对会困惑。

### 7. 11 例规约测试质检 —— **判定：无恒真、无实现复述；夹具缺陷仅 c4 一处（前席已修）；其余为覆盖缺口非缺陷**

- **oracle 链健全**：`_legacy_forward_text`（独立复写）↔ `build_campus_forward_text` ↔ `record()` 产出三方互证，
  非同义反复；1501 断言钉死截断预算。
- **两例重写已按 runbook 落地**（实读 :137-158/:197-205 现为 payload 级断言：message_id/group_id/sender_name/text/body）。
- **无同类夹具缺陷**：逐一核对了全部用例的群号/白名单搭配（"333" 故意门外、"222" 白名单内、e2e 用 "111"），
  c4 之后再无「夹具自身不在被测门内」问题。
- **逐例弱点**：
  - dispatch 例 `call["entry"] in {"handle","handle_async"}` 偏弱，未钉死 handle_async（M3）；
  - `test_forward_message_expresses_owner_private_target` 未断言 `plain_text/platform/adapter/raw_segments`——
    builder 若把 plain_text 写成未截断原文，29 例无一能抓（出站正文取 capability body，用户可见形态不受影响，
    但审计/幂等 fallback 面 `message.message_id or message.request_id` 之外的 plain_text 失真无哨兵）（M2）；
  - handler `except Exception` 吞异常路径（转发失败不影响监听主链路）零测试（M4）；
  - `test_no_outbound...` 半 (a) 依赖 review 规则，机制已核实成立；A-19 边角见 D1。
- **中途 2 failed 的根因定性**：即 M1 类（env 缺名/注解求值），非规约本身错误；最终态 29/29。

### 8. 自由发现

- 【现场】实施席并行施工全程目击：开场时树为 18P/11xF（log 记载态）→ 本席首轮全文件实跑 **2 failed/27 passed**
  （实施中间态）→ 数分钟后 **29 passed** + 棘轮五套件 **127 passed** + ruff 三文件 All checks passed。实施席实际
  施工面=runbook §2.1+§2.2+§2.4 全量（payload/双 builder/handler 改造/11 处摘牌），并有两处 runbook 外自主决策：
  ①`_offload` 本地包装替代 `offload_capability`（消解行为差 #4，注释留痕）；②`_offload` 注解 `decision: Any`
  （规避 BotDecision 缺名）。两处均合理，但 **runbook 已与终态实现出现两处偏差**（#4 行为差、§2.2 片段），
  文档未回写。
- 【Minor】`build_campus_forward_capability` 返回注解 `Any`（cosmetic，先例 `build_subscription_push_capability` 同款）。
- 【设计语义】控制面停用 campus → 转发静默停、QQ 侧主人无感知——这是收编本意（§1.2 列为收益），但「静默」属性
  应让用户在裁定/验收时知情。
- 【已核实无恙】`_record_receipt_safely` 对 PRIVATE 会话不清空 public_message，但 receipt 仅持久化不投递 →
  不产生意外出站；`InMemorySendQueue.sent_requests`/`ReceiptState.SENT` 属性实读存在，测试 spy 面无夹具缺陷；
  `ProductFeatureGate.__call__(message, capability_id)` 签名实读一致（`feature_gate.py:89`）。

---

## 发现分级汇总

**Critical：0**

**Important：2**
- **I1** review 门 fail-closed 行为零测试覆盖 + 静默永久丢失语义未成文：命中泄漏面的源群文本 → 主人零接收、
  无告警、store 已记永久不可重放。runbook「密钥/路径形态命中即 BLOCK」的「路径」半句与实现不符（实测不拦路径、
  不拦 `BOT_XXX=`）——泄漏面比文档窄，用户裁定①时基于的是偏大的拦截面画像。
- **I2** 门禁 BLOCK（控制面停用/runtime 暂停）=该条消息**永久丢失**（store 先记账 + 同 id 重放不再进管线）。
  runbook 行为差表 #3 只写「转发被拦」，未写永久性；零测试。暂停窗口内的教务通知不可恢复——需用户显式接受。

**Minor：6**
- M1 测试 harness 脆弱耦合：handler 内嵌注解不求值依赖「测试模块 future-annotations + compile() 继承调用方 flags」，
  env 未注入 IncomingMessage/CapabilityResult；破坏任一前提 → 4 个 handler 例 NameError（本席双探针实证）。
  生产无恙。
- M2 builder 测试未钉 `plain_text/platform/adapter/raw_segments`。
- M3 dispatch 例 entry 断言弱（accepts handle 或 handle_async）。
- M4 handler 吞异常路径（转发失败不炸监听）零测试。
- M5 runbook 文档债：行号三处过期、5012→5027、S0 FAIL 警示过时、行为差 #4 与 §2.2 片段已与终态实现偏差、
  `offload_capability` 测试 env 注入要求缺失。
- M6 feature gate disabled 面 campus 无定向用例（仅测 ALLOW 面）。

**设计语义：2**
- D1 A-19 群失败通知绕 review 直入队、目标=消息群——负锁未覆盖角；当前不可达（消息恒 PRIVATE + 能力不可失败），
  若未来有人改 builder 会话形态需重估。
- D2 泄漏面窄于文档：含盘符路径/`BOT_XXX=` 形态的教务通知收编后仍原样直达主人（与旁路一致，非收编引入，
  但与「密钥不入聊天」铁律的差距应留档知情）。

---

## U17-VERIFY 重点检查清单（移交）

1. **全量四门禁实跑**（dev.ps1 test/lint/typecheck/runtime-layout，计数以实跑为准）——本席只跑了 campus 定向
   （29 passed）+ 棘轮五套件（127 passed）+ ruff 三文件；**mypy 本席未跑**。
2. **共享树在飞核对**：本席评审期间树持续被实施席推进；VERIFY 开工时先 `git diff --stat` 三文件
   （campus.py / root `__init__.py` / test_campus_digest.py）+ outbound_registry.py（note 已于前置批刷新）
   确认实施席无后续追加改动；commit 逐文件显式 add 清单需含上述四文件。
3. **mypy 项目口径**（630 文件基线）对实施席改动面零新增错误。
4. **真机验收新增三项**（重启后，acceptance-manual §6.6 校园段基础上）：
   ① 控制面停用 `bot.plugin.campus_forward` → 学校群来消息不再转发，且审计可查 stage=policy（验 fail-closed 改善项）；
   ② 构造含 `token=xxx` 形态的群消息 → 主人零接收 + 审计 stage=review 有痕——**该静默丢失行为须向用户显式确认
   为已接受语义**（I1）；
   ③ 1501 字满额消息形态观察：合并转发（2 节点）or 单条，取决于生产 `BOT_RENDER_FORWARD_MIN_CHARS` 现值
   （本席禁读 .env，unknown）——请用户确认现值或声明双形态都可接受。
5. **测试补齐建议**（可立独立小席位，不阻塞验收）：review-BLOCK 行为 1 例（真管线+泄漏 body → BLOCKED+零入队）、
   暂停 BLOCK 永久丢失语义 1 例、builder `plain_text==payload.body` 断言 1 行、dispatch entry 钉死 handle_async。
6. **摘牌完整性**：全文件 `grep xfail` 应为 0（本席已验=0）；29/29 应复现。
7. **坐标门**：已绿；若后续根文件 campus matcher 上方再有增删行，按 runbook §2.2 处置——**registry 现值 5027**
   （非 runbook 文字所写 5012），刷新时以 `_campus_matcher_coordinate()` 动态值为准。
8. **S0 警示过时**：feature_gate 门现全绿（四条已由 F3/U3 补登），runbook §2.5.2 的「存量基线 FAIL 勿扩权」
   无需再执行，也不应据旧文档误报基线 FAIL。
9. **生产 await 链终极证据**：`_offload`（async）→ `handle_async` await 之 → 返回 CapabilityResult，本席 code-read
   核实无 TypeError 面；真机一条真实【校园转发】私聊到达=终极验收。
10. **回滚面确认**：campus.sqlite3 store 结构未变、队列无 schema 迁移（runbook §2.6 声称，本席未见反证）；
    回滚需恢复四文件并重挂 11 xfail（reason 唯一形态见 CAMPUS-XFAIL log）。

**U17REVIEW-SEAT DONE** — 2026-09-20，U17-REVIEW-3（第三派；评审全程只读，唯一写面=本 log）。
