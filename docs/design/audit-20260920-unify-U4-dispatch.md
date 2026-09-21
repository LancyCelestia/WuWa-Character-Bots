# 统一收尾波次审计报告 — 席位 U4-DISPATCH「中央分发/门禁统一」（2026-09-20）

> **性质**：独立只读审计（非交付席自报）。对象=「所有请求先经中央统一处理（路由→门禁→分发）再交给插件」这一中央 mandate 的真实达成度。凡绕开中央路由/门禁、或门禁在部分通路失效，一律记缺陷（含越权/骚扰风险）。
> **快照口径**：行号=2026-09-20 本席实读工作树快照；每条给「锚点字符串」，行号漂移时用锚点重定位，禁按行号盲改。树正被并行会话改写，本审计只读、不改任何码/配置/文档（除本文件）。
> **方法**：①全树 grep 注册点 + 逐 handler 追分发落点；②读 gate/pipeline/rate_limit/service_wiring/dispatcher/shadow/campus/reactions 真身；③scoped 实跑 `tests/test_decision_engine_shadow.py tests/test_sqlite_rate_limit_group.py tests/test_v21_wire_svc_assembly.py tests/test_a18_gate_idempotency_rollback.py` → **59 passed**（佐证 legacy 缺省、限流双语义、registry 装配、门禁幂等回滚为现行绿态）；④一次性 grep/AST 扫描清点节流实现与阻塞点。**禁跑全量 pytest、禁 git 写、未读 .env 明文、未写 Runtime/**。
> **纪律遵守**：直跑 python 必带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest 带 `--basetemp=$TEMP/u4-audit-*` `-p no:cacheprovider`。结束自查见 §末（源码树零缓存残留）。

---

## §0 总裁决（先读）

「中央统一处理」在**交互式消息主链路（chat / /bot 命令 / 各能力 matcher）上基本成立**：路由有单一大脑（`base_router`→`RouteKind`，经 matcher 规则消费），门禁有单一收口点（`RuntimePipeline._prepare`），能力异常有单一旁路（`_internal_error`→错误卡）。**但存在三套并行分发器 + 十余处旁路门禁的出站面，构成对用户 mandate 的实质破坏**：

1. **调度器族（APScheduler）与校园/cookie/告警等被动 matcher 是「第二/第三分发器」**：它们直接 `SendRequest→send_queue.submit` 或 `bot.call_api` 出站，**完全绕过 `policy/gate`（群黑白名单）、`quiet_hours`（安静时间）、中央 `RateLimiter`（限流）、幂等** ——除 `today_history` 外无一过 `_prepare`。
2. **主动出站旁路**：表情贴纸回应（emotion_signal 触发）在 `policy/gate` **之前**执行、回戳（poke-back）走 `control_plane/dispatcher.py` 自有 `OutboundAdmissionGate`——二者都**不查群黑白名单/安静时间/中央限流**，可在「完全静默」的 black1 群产生可见 bot 活动（骚扰风险）。
3. **门禁收口点 `_prepare` 本身同步跑在事件循环线程**，其下 SQLite 限流器 / SQLite 幂等表若启用即在 loop 上做同步 DB IO；自然语言链路的 `bot.news`（RSS 外呼）未列入 offload 白名单，同步跑冻结事件循环（台账 #8 同类）。

**严重度分布**：Critical 0｜High 3（H-1 表情/回戳旁路、H-2 调度器族整体旁路、H-3 `_prepare` loop 内同步 DB IO + news 阻塞）｜Medium 6｜Low 5。全部为「现网默认行为多数不触发/有自有小门兜底，但对 mandate 与统一可观测性是硬缺口」性质，非「正在炸」。

---

## §1 中央入口清点：实际有几套分发器

### 1.1 唯一路由大脑（成立）
- **坐标**：`domains/chat_reply/runtime/base_router.py`（真身）；消费点 `__init__.py:813 _cached_route_decision`，被各 matcher 的 `rule=_is_*_event` 调用（如 `__init__.py:4761/4784/5953/…`，逐一 `.kind is RouteKind.X`）。
- **结论**：`RouteKind` 分类是单一函数族，NoneBot 的每条 matcher 规则只是「拿同一次 `_cached_route_decision` 判是不是我的档」。**没有第二套路由**——`/bot` 前缀链、昵称/别名命令链、自然语言链都在 NoneBot matcher 集合内，由 base_router 统一分类。白名单抽签/昵称点名/图片回复**不是独立分发器**，是 `evaluate_policy` 内的分支（`proactive_reply_selected`/`vision_reply_selected`，`gate.py:336/359`）。

### 1.2 门禁单一收口点（成立，但覆盖面有洞）
- **坐标**：`domains/chat_reply/runtime/pipeline.py:479 _prepare`。收口顺序（可验证）：`feature_gate`（482）→`runtime_enabled`（501）→`role_settings` 解析角色（522）→`runtime_control` 暂停位（526）→`evaluate_policy`（黑白名单/风险/主动亲和，547）→`quiet_hours`（570）→`reply_budget`+`rate_limiter.check_and_record`（598/611）→幂等 `_claim_event`（652）。**全部门禁在此一处、且限流账在幂等 claim 之前（A-18 序，已实证绿）**。
- **结论**：只要一个请求走进 `pipeline.handle/handle_async`，它就吃满这套门。**问题是哪些请求根本不走进来**（见 1.3）。

### 1.3 实际分发器计数：主链 1 套 + 旁路 3 套

| # | 分发器 | 载体 | 是否过 `policy/gate` | 证据 |
|---|---|---|---|---|
| D1 | **NoneBot matcher→pipeline**（chat/命令/能力） | `__init__.py` 51 个 `.handle()`，其中约 40+ 经 `_run_capability_through_pipeline`（2512）或 `pipeline.handle_async` | **是** | `__init__.py:2544 pipeline.handle` / `7575 pipeline.handle_async` |
| D1' | **NoneBot matcher→直接出站（旁路子集）** | group_welcome/cookie 直连（via_queue=False 默认）、reactions、poke-back、meme 主动 | **否（出站旁路）** | 见 §2 逐格 |
| D2 | **APScheduler 调度器族** | `_register_*_scheduler`（digest/daily_assist/reminder/credential/model/usage/today_history） | **多数否**；仅 today_history 过 pipeline | `__init__.py:3357 submit`、`_push_daily_group_digests` submit、`1849 pipeline.handle_async` |
| D3 | **交互出站门面** | `control_plane/dispatcher.py:223 build_interaction_dispatcher`（poke-back/reaction/meme 副作用） | **否**（自有 `OutboundAdmissionGate`+`PermitLease`，无 policy/quiet/rate） | `dispatcher.py:49 dispatch` 仅 route→review(形态)→send |
| D4 | **控制面 HTTP 面（运维）** | `control_plane/_app.py`+`actions.py` | **否**（运维信任边界，Bearer+loopback，默认关） | `config.py:56 bot_control_plane_enabled=False`；actions 不做用户可见聊天发送 |

> D2/D3 是本席核心缺陷源：它们是「不经过中央门禁的第二/第三分发器」，直接对用户/群产生出站。D4 属运维面、可豁免但需显式声明。

---

## §2 通路 × 门禁 矩阵（本席最重要交付物）

列＝`policy/gate` 各门禁项；行＝§1 分发通路。`✓`=生效（附坐标）｜`✗`=绕过（缺陷，空格）｜`—`=不适用。

| 通路 \ 门禁 | 黑白名单/静默(gate) | 安静时间(quiet) | 限流 Central RateLimiter | 主动亲和门 | 角色/权限门 | 幂等 | feature_gate |
|---|---|---|---|---|---|---|---|
| chat matcher（人格对话，含@/抽签/点名/图片） | ✓`gate.py:215` | ✓`pipeline.py:570` | ✓`pipeline.py:611` | ✓`gate.py:355` | ✓`pipeline.py:522` | ✓(可选)`pipeline.py:652` | ✓`pipeline.py:482` |
| /bot 命令 matcher（status/help/config…） | ✓ 同 _prepare | ✓ | ✓(仅 chat 类计窗，命令 `non_chat` 放行 `rate_limit.py:311`) | — | ✓ | ✓ | ✓ |
| 能力 matcher（weather/market/music/…经 pipeline） | ✓ | ✓ | ✓(命令能力 non_chat 放行) | — | ✓ | ✓ | ✓ |
| **表情贴纸主动回应 emotion_signal** | **✗** | **✗** | **✗** | 自有 ProactiveGate | **✗** | ✗ | ✓(仅外层 plugin 开关) |
| **回戳 poke-back** | **✗**(D3 门面) | **✗** | **✗** | — | ✗ | 自有 PermitLease | ✗ |
| **入群欢迎（via_queue=False 默认）** | **✗** | **✗** | **✗** | — | ✗ | ✗ | ✗ |
| **校园自动转发** | ✗(自有三重来源门) | **✗** | **✗** | — | 自有 min-role | message_id 幂等 | ✗ |
| **每日群摘要推送 digest** | ✗(自有白名单) | **✗** | **✗** | — | ✗ | dedupe by 日 | ✗ |
| **日常助理私聊推送** | —(私聊) | **✗** | **✗** | — | ✗ | dedupe by 日 | ✗ |
| **提醒投递 reminder** | —(私聊) | **✗** | **✗** | — | ✗ | 送达销账 | ✗ |
| **cookie 到期提醒（via_queue=False 默认）** | —(私聊) | **✗** | **✗** | — | 仅管理员 | via_queue=True 才日幂等 | ✗ |
| **运维告警 admin_alert** | —(私聊管理员) | **✗** | ✗(自有 300s 抑制) | — | — | cooldown_key | ✗ |
| **历史上的今天推送** | ✓(过 pipeline) | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| 控制面动作（HTTP） | —(运维面) | — | — | — | Bearer+role | CAS+单次确认 | 白名单 handler |

**读法**：`✗` 集中出现在「主动/定时/notice 触发」的出站面——这些恰好是骚扰风险最高的「无用户当轮请求却发东西」通路，而它们基本不吃中央门禁。唯一「主动推送却过满套门」的正例是 `today_history`（`__init__.py:1849` 走 `pipeline.handle_async`），**证明统一是可实现的，其余只是没收口**。

### 空格（缺陷）逐条七要素

#### 【H-1】表情贴纸主动回应 / 回戳，绕过群黑白名单与安静时间
- **严重度**：High（骚扰/越权可见活动）。
- **坐标**：`__init__.py:7329-7342`（chat 链，pipeline 之前调 `_maybe_react_on_message`）；真身 `domains/meme/reactions/engine.py:828 maybe_react_on_message`；回戳 `__init__.py:5235-5242 _dispatch_poke_back`→`control_plane/dispatcher.py`。
- **锚点**：`switches.enabled("bot.plugin.chat.reactions.emotion")` + `trigger="emotion_signal"`；`_REACTION_PROACTIVE_GATE`。
- **根因**：reactions 在 `evaluate_policy` 之前触发（chat matcher 命中即执行），其五层门是**自有 `ProactiveGate`（开关/每消息去重/概率/冷却/每小时）**，不 import 也不查询 `policy/gate` 的群 black1/black2/white2 名单，也不查 `quiet_hours`。回戳 poke-back 走 D3 门面，`review` 仅判「意图存在+未取消」。
- **证据**：`gate.py` 全文无 reaction/poke 调用；`engine.py:871` `active_gate.allow(...)` 参数全是 `bot_reactions_*`，无 `group_lists`/`quiet`。black1 语义=「完全静默，只接收不发送」（`gate.py:275` 注释），但 `@bot+情绪文本` 在 black1 群可命中 7331→贴表情（可见活动）。
- **改法**：把「是否在群黑名单/安静时间窗」抽成可复用谓词（`policy.is_group_silent(group_id)` / `quiet_hours.is_quiet_now()`），在 `maybe_react_on_message` 与 `_dispatch_poke_back` 入口前置判定；或最小化=chat 链只在 `evaluate_policy` 已 allow 的会话上再跑 emotion_signal（把 7331 挪到 pipeline 之后，与 7662 的 after_reply 触发合并）。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_reactions* tests/test_content_safety_v2.py -p no:cacheprovider --basetemp="$TEMP/u4-h1" -q`；新增负例：black1 群 + `@bot 好难过` → 断言 `react_to_message` 未被调用。

#### 【H-2】调度器族 / 校园 / cookie / 告警 主动出站整体旁路中央门禁
- **严重度**：High（mandate 破坏 + 部分骚扰面）。
- **坐标**：digest `__init__.py:3215`（`_push_daily_group_digests`→`send_queue.submit`，见 `capability_id="bot.group_digest_push"`:3193）；daily_assist `__init__.py:3306/3357`；reminder `_deliver_due_reminders`（submit+inline deliver）；cookie `__init__.py:2980`（via_queue=False 时另路直发）；campus `__init__.py:5029 send_queue.submit`；告警 `domains/ops/monitor/alerts.py:297`。
- **锚点**：`send_queue.submit(request)`（各函数内）；`_register_digest_push_scheduler`。
- **根因**：这些通路是「构造 SendRequest→入队」，从不经过 `pipeline._prepare`，因此中央限流/安静时间/群名单/幂等表全部旁路。各自实现了小门：digest/campus 有**自有白名单**、提醒/助理有**按日 dedupe**、告警有**300s 抑制**、campus 有 message_id 幂等——但语义互不统一、不可被 `/bot status`/审计的中央限流视角观测。
- **证据**：`_prepare`（`pipeline.py:479`）唯一被 `handle/handle_async` 调用；上述函数无一个调用 `pipeline.handle*`（grep 证实 digest/reminder/daily_assist/campus 体内仅 `submit`）。**对比正例**：today_history `_push`（`__init__.py:1819-1862`）用 `pipeline.handle_async` → 吃满门禁。
- **改法（收口方向）**：为「主动出站」增设一个轻量中央前置件 `ProactiveDispatcher.precheck(message, capability_id, *, require_quiet_ok, audience_slot)`——统一读群名单/安静时间/中央 proactive 限流，digest/campus/daily_assist/reminder/cookie 全部改走它（保留各自 dedupe/白名单作 audience 维度，但门禁维度收口到一处）；today_history 的 pipeline 路径作为参考实现。
- **验证**：新增 `tests/test_proactive_dispatch_gate.py`：黑名单群 → digest 不投；安静时间窗 → reminder 顺延或抑制（与 ledger #3 的「待统一改造」同题）。

#### 【M-1】入群欢迎默认直发 `send_group_msg`，绕过一切门禁
- **严重度**：Medium（black1 群被欢迎=违反「完全静默」承诺）。
- **坐标**：`__init__.py:5337-5392 _handle_group_increase`；直发块 `:5384-5389`（`bot_group_welcome_via_queue=False` 默认，`config.py` 门缺省关）。
- **锚点**：`await bot.call_api("send_group_msg", group_id=int(group_id), message=...`。
- **根因**：`bot_group_welcome_enabled` 是唯一开关；无群名单/安静时间/限流。
- **证据**：notice 路径未调 pipeline；S0 收编②（`via_queue=True`）才走 `_send_text_through_unified_pipeline`→`_run_capability_through_pipeline`→gate。
- **附带风险（反向）**：`via_queue=True` 时，group_increase notice 摄取为空文本 GROUP 消息，进 `evaluate_policy` 会落 `passive_group_message` DENY（`gate.py:369`）→ 欢迎被中央门误杀（除白名单群+概率抽签命中）。**两条路径各有一个相反的缺陷**。
- **改法**：欢迎语应「豁免被动观察门但仍受静默名单约束」——在 `evaluate_policy` 加 `capability_id in PROACTIVE_ALLOWED_IDS` 旁路 `passive_group_message` 但仍查 black1；默认直发块至少补 black1/quiet 检查。
- **验证**：`pytest tests/test_campus_digest.py tests/test_policy* -k welcome -p no:cacheprovider --basetemp="$TEMP/u4-m1" -q` + 新增 black1 群欢迎负例。

#### 【M-2】`_prepare` 收口点同步运行在事件循环线程；SQLite 限流/幂等启用即在 loop 做同步 DB IO
- **严重度**：Medium（延迟尖峰/全站卡顿，与台账 #8 同类根）。
- **坐标**：`__init__.py:2544`（`pipeline.handle(...)` 同步、非 await，`offload_sync_capability=False` 时）；`pipeline.py:1096 handle`→`_prepare`；SQLite 同步 IO `rate_limit.py:732/788/961 _connect` + 幂等 `domains/chat_reply/runtime/event_idempotency.py SqliteEventIdempotencyTable.claim`。
- **锚点**：`receipt = pipeline.handle(message, capability, capability_id=capability_id)`。
- **根因**：`offload_capability` 只包裹 **capability 本体**（`pipeline.py:225-239`），`_prepare` 里所有门禁（含 SQLite 限流的 `sqlite3.connect/INSERT/DELETE`、幂等表 claim）在 `await` 之前于 loop 线程同步执行。
- **证据**：`handle` 是同步方法；`handle_async`（`pipeline.py:1127`）先 `prepared = self._prepare(...)`（同步）才 `await capability(...)`。默认 `bot_rate_limit_db_path=""`（`config.py:935`）→ InMemory（快）；但一旦切 SQLite（跨进程一致性诉求）即每消息 loop 内 DB IO。
- **改法**：把 `_prepare` 的 DB 敏感段（rate_limiter、idempotency）用 `asyncio.to_thread` 下放，或整段 `_prepare`+capability 一起在 executor 内跑（新增 `handle_all_offloaded`）；文档化「SQLite 限流=以 loop 卡顿换跨进程一致」。
- **验证**：`pytest tests/test_group_rate_limit.py tests/test_sqlite_rate_limit_group.py tests/test_a18_gate_idempotency_rollback.py -p no:cacheprovider --basetemp="$TEMP/u4-m2" -q`。

#### 【M-3】自然语言链路 `bot.news` 未列入 offload 白名单 → RSS 外呼冻结事件循环
- **严重度**：Medium。
- **坐标**：`__init__.py:8316-8320`（natural 链 bot.news 分支）→ `8376 _run_capability_through_pipeline(..., offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS)`；`OFFLOADED_CAPABILITY_IDS`（`__init__.py:303-338`）不含 `bot.news`。
- **锚点**：`elif capability_id == "bot.news":` + `offload_sync_capability=capability_id in OFFLOADED_CAPABILITY_IDS`。
- **根因**：`news` 专用 matcher（`__init__.py:6114`）走 `_run_simple_capability`（**恒定 offload**，`7928`）；但同一能力经自然语言链时按白名单判，`bot.news` 漏登记→同步跑。
- **证据**：`OFFLOADED_CAPABILITY_IDS` 枚举内无 `bot.news`；matcher 路径与 natural 路径对同能力 offload 决策不一致。
- **改法**：把 `bot.news`（及任何含网络/渲染的能力）补进 `OFFLOADED_CAPABILITY_IDS`；或把「是否 offload」从「id 白名单」改为「能力自声明 `is_blocking`」单源，消除两路径漂移。
- **验证**：`pytest tests/test_trigger_bidirectional_gate.py -k news -p no:cacheprovider --basetemp="$TEMP/u4-m3" -q` + 加静态断言：所有走自然链的 capability_id ⊆ offload 集 ∪ 轻量集。

#### 【L-1】群自动接话「开关」为装配期快照，与「概率/名单」可热改不一致
- **坐标**：`__init__.py:3765 group_auto_reply_enabled=config.bot_group_chat_auto_reply_enabled`（静态 bool）对照 `3769` 概率 lambda、`3783 group_lists_provider` lambda。
- **根因**：概率与名单传 callable（每抽签现算，热生效），唯独总开关冻成装配值。
- **证据**：`PolicySettings.group_auto_reply_enabled` 是 `bool`（`gate.py:47`），无 callable 变体。
- **影响**：`/bot runtime set` 改自动接话开关，当轮进程不生效需重启（台账 #3「调度器装配期快照」同族的命令面实例）。
- **改法**：`group_auto_reply_enabled` 亦收 `bool|Callable[[],bool]`，`_resolve_probability` 同构加 `_resolve_bool`。
- **验证**：`pytest tests/test_bgroup_chat_pipeline.py -p no:cacheprovider --basetemp="$TEMP/u4-l1" -q`。

#### 【L-2】poke 冷却配置未进运行时合并表 → 不可热改
- **坐标**：`domains/chat_reply/runtime/settings.py:411-425`（注释自陈「PokeDispatcher 读合并层 config，但合并表未登记 bot_poke_*」）；消费 `domains/chat_reply/capabilities/poke.py:157-158`。
- **根因/证据**：`bot_poke_private/group_cooldown_seconds`（`config.py:665-666`）缺合并登记；`_config_with_runtime_overrides` 拿不到热值。
- **改法**：把 `bot_poke_*` 补进 settings 合并表；或显式文档化「poke 冷却重启才生效」并加负锁。
- **验证**：`pytest tests/test_policy_sender_interval.py -p no:cacheprovider --basetemp="$TEMP/u4-l2" -q`。

---

## §3 限流双实现 + 「第三/十余处」自实现节流

### 3.1 InMemory vs SQLite 语义一致性（台账 #22 已修，本席实证维持绿）
- **R3 同人点名最小间隔序**：InMemory `rate_limit.py:286-297` 外层门含 `chat_sender_min_interval_seconds>0 and mentions_bot and group`；SQLite `:680-689` 外层只判 `enabled and chat and group`，`interval>0/mentions_bot` 下沉到 `_check_sender_min_interval`（`:725-728`）。**两路生效集合相同**（交集=enabled∧chat∧group∧interval>0∧mentions_bot），且 rollback 共用单一事实源 `_sender_interval_record_applies`（`:125`）。→ **语义一致，实证 59 passed**。
- **interactive 早退**：两实现 R3 检查均**先于** `interactive` 早退（InMemory `:286`<`:298`；SQLite `:680`<`:690`），A-04 修复成立（群点名冷却对 interactive 生效）。

### 3.2 「SQLite 限流不支持热改」（台账 #3）——现况确认
- **坐标**：`rate_limit.py:1255 build_rate_limiter`。`db_path` 非空时 `:268-270` `resolved = settings() if callable(settings) else settings; return SQLiteRateLimiter(db_path, settings=resolved)` —— **把 callable provider 当场求值成静态快照**；`SQLiteRateLimiter.settings` 是普通属性（`:655`），无 `InMemoryRateLimiter.settings` 那样的实时解析 property（`:237-247`）。
- **证据**：`__init__.py:3741` 传入 `settings_provider=lambda: build_rate_limit_settings(_config_with_runtime_overrides(...))`；InMemory 每判实时求值（热生效），SQLite 冻结装配值（不热生效）。
- **定性**：非缺陷而是已知架构取舍（台账 #3），但**代码注释只写「目前不支持」，未写「热改会被静默忽略」**——运维易误以为改了生效。建议：`build_rate_limiter` 选到 SQLite 分支且收到 callable 时 `logger.warning` 显式告警一次。

### 3.3 门禁之外的「自实现节流」清点（同类实现差异表，用户 mandate 的碎片化证据）

| 节流 | 载体坐标 | 键 | 参数 | 可观测(中央限流审计) | 热改 |
|---|---|---|---|---|---|
| 中央 chat/群/proactive | `rate_limit.py` | 多维桶 | window+caps | 是 | InMemory 是/SQLite 否 |
| 表情贴纸主动 | `reactions/engine.py:828 ProactiveGate` | session+msg | prob/30s/20·h⁻¹ (`config.py:635-636`) | 否 | 走合并 config |
| 表情第二层 meme | `config.py:645 reactions_meme_cooldown 120` | — | — | 否 | ? |
| 回戳 | `poke.py:157-158` | 私30s/群10s | (`config.py:665-666`) | 否 | **否**（L-2） |
| 错误卡 | `ops/monitor/error_report.py:189 cooldown_seconds=60` | 会话 | (`config.py:625`) | 否 | 读 driver/env |
| 群失败降级通知 | `pipeline.py:99 _GROUP_FAILURE_NOTICE_WINDOW_SECONDS=300` | session | **硬编码非配置** | 否 | 否 |
| 运维告警 | `ops/monitor/alerts.py:159 window_seconds=300` | key | (`config.py:98 disconnect 600`) | 否 | 部分 |
| 复读吐槽 | `config.py:479 parrot_cooldown 300` | — | — | 否 | ? |
| 视频进度 ack | `config.py:583 60` / chat.py:446 deep 300 | — | — | 否 | ? |
| 记忆抽取错误 | `config.py:192 300` | — | — | 否 | ? |
| 订阅最小间隔 | `config.py:950 1.0` | — | — | 否 | ? |
| meme 库吸收 | `config.py:529 20` | — | — | 否 | ? |

> **≥11 处各自实现的冷却/节流**，各持 `dict + time.monotonic + Lock`，语义（per-session/per-sender/global/hourly-cap）互不相同，**均不汇入中央 `RateLimiter` 的审计与热配置面**。这是「统一中央门禁」在横切面上最系统的欠账。收口建议：抽 `Throttle`（token-bucket 或滑动窗，可注入 clock/store）单一原语，各处实例化共享同一实现与观测面。

---

## §4 RuntimePipeline 统一性

- **offload 池是否共用**：**是**。`pipeline.py:141-198 _get_chat_pool` 懒建**单一**有界 `ThreadPoolExecutor`（worker=config/env/默认8，在途上限 2N，超限 `try_acquire` 失败→`_pipeline_busy_result` 快返 `pipeline_busy`）。所有 `offload_capability` 包裹的能力共用此池；默认 asyncio 线程池留给 `asyncio.to_thread`（reactions 被动感知/文件写/video preprocess，`__init__.py:7430/5443/5456`）。
- **超时/取消语义（缺陷 M-4）**：`loop.run_in_executor` **无 per-task 超时**，pipeline 层不 kill 挂死能力；取消仅在 `_shutdown_chat_pool`（`pipeline.py:174` `cancel_futures=True`）作用于未起步任务。兜底靠：①有界池 busy 快败防雪崩；②能力内部预算（LLM 300s、connect5/read30）；③`deadline_monotonic` 仅在**出站侧**（`_complete`→SendRequest `:827`）。**缺口=「能力执行期」无中央硬超时**，一个未自带超时的阻塞能力会长期占 1 个 worker。
  - **改法**：`offload_capability` 用 `asyncio.wait_for(loop.run_in_executor(...), timeout=capability_budget)` 或在 pipeline 层注入 per-capability 预算；`pipeline_busy` 之外再产 `pipeline_timeout` OperationalIssue。
  - **验证**：`pytest tests/test_pipeline_review_fixes.py tests/test_bgroup_chat_pipeline.py -p no:cacheprovider --basetemp="$TEMP/u4-m4" -q`。
- **异常统一落 `_internal_error`→错误卡**：**是**。`pipeline.py:1096/1127` 三处 catch（能力异常/`_complete` 出站异常/外层兜底）均 `self._rollback_rate_limit(prepared)` + `self._internal_error`；`_internal_error:952`→`_maybe_send_error_card:1005`（fail-open、`bot_error_card_enabled` 缺省 True）。**覆盖 handle 与 handle_async 双路、且 A-18 额度回滚语义一致（2026-09-18 补 `_complete` 出站异常也回滚，实证绿）**。
- **loop 直跑阻塞 IO 违规点**：见 M-2（`_prepare` SQLite）、M-3（news offload 漏登）。台账 #8 G-MERMAID 的「loop 限时等待」——render_backend 经 `offload_capability` 已下放线程池（专用 matcher 路径），残留风险仅在未 offload 的自然链能力（M-3 家族）。

---

## §5 decision 引擎现状（无过度宣称，实证）

- **缺省 legacy_only 属实**：`config.py:236 bot_decision_engine_mode="legacy_only"`；`shadow.py:34 LEGACY_MODE`、`:67` 解析链、`:51` 非法/`engine_only` 一律回落 legacy_only（fail-closed，仅告警一次）。
- **shadow 不接管、只观测**：`pipeline.py:347 _observe_decision_shadow` 在 `handle/handle_async` 首行调用，`is_shadow_active()` 假时一次即返回；真时 `observe_pipeline_event` 只算 plan 写 `decision_trace`，**绝不发送/绝不改回执/绝不 claim 幂等**（`shadow.py:207`）。引擎自身在 `domains/core/decision/engine.py:257/270/295` 明确「全局暂停/幂等/群黑白名单由现行 pipeline 判定，引擎不 claim」——**不存在「决策引擎已接管」的代码事实**。
- **分歧判定可验证性**：`engine.py` 的 plan 与 legacy `capability_id` 差异写 trace（`decision/trace.py` 有界 sink + SQLite 落盘）；本席实跑 `tests/test_decision_engine_shadow.py` 全绿（含在 59 passed 内）。**结论：shadow 语义诚实，legacy_only 缺省真实，无夸大**。收口清单里此项=「维持现状，接管属阶段 2 用户裁决（台账 #4）」。

---

## §6 中央分发→插件级服务装配一致性（WIRE-SVC 注册表）

- **装配收口点**：`runtime/service_wiring.py` 唯一装配模块；根 `__init__.py:4255-4258` 主门 `bot_v21_service_wiring_enabled`（`config.py:174` **缺省 False**）门控下 `register_v21_services(config)`。四门（`service_wiring.py:64 v21_service_gates`）=主门∧分门：worldbook（`config.py:176` False）/knowledge（`:178` False）/database_broker（`:169` True）/teaching（`:165` True）——**主门关时后二者 True 被 ∧ 短路，现网零装配零副作用**（实证 `test_v21_wire_svc_assembly` 门全关=注册表空，绿）。fail-open（`_assemble:96` 单服务异常记 warning 跳过）。
- **缺陷 M-5：注册表在生产侧「只写不读」**。
  - **证据**：`grep get_v21_service plugins/` **零命中**（仅 `service_wiring.py` 自身定义 + `tests/test_v21_wire_svc_assembly.py` 消费）；即四服务装配后**无任何能力/控制面从注册表取用**。
  - **旁证（真消费走旧路）**：chat 人格的知识检索在 `domains/chat_reply/character/providers.py:521-540` 自建 vector/keyword provider + `knowledge_files`，**不经 `get_v21_service("knowledge")`**；控制面 WebUI 知识库另起 `KnowledgeCatalogService`（`control_plane/_app.py:590 build_default_knowledge_service`，是**不同类**、只读管理视图，非注册表的 `KnowledgeService`）。
  - **根因**：WIRE-SVC 设计即「只装配+注册，不制造消费点」（`service_wiring.py:16-17`）——意图如此，但对「单一中央分发」mandate 而言，注册表目前是**并行的未接线抽象**：拨开主门也不会让四服务进入请求处理链。
  - **改法**：要么补消费点（chat/providers 改从 `get_v21_service` 取 knowledge/worldbook，退役自建检索），要么显式标注注册表为「阶段 2 预留、当前惰性」防误读；**禁止**在主门文档写「服务已上线可用」。
  - **验证**：`grep -rn get_v21_service plugins/ | grep -v service_wiring.py` 应命中消费方（收口后）或维持零（则文档需改口径）。

---

## §7 调度器族「装配期 config 快照」清点（台账 #3 全量化）

**读装配期快照（热改当轮不生效）的通路**（证据：closure 捕获装配 `config`，且无 `settings_provider`/lambda/`_config_with_runtime_overrides`）：

| 通路 | 坐标 | 快照内容 | 影响 |
|---|---|---|---|
| digest cron 时刻+正文 config | `__init__.py:3215/3241` | 推送时刻、正文口径、LLM 参数 | `/bot runtime set` 改推送时/文案不生效需重启 |
| daily_assist 三 cron | `__init__.py:3468-3528` | 餐点/早报/晚报时刻、目标名单快照 | 同上 |
| reminder tick | `__init__.py:3080` | 投递用装配 config（LLM/文案） | 同上 |
| today_history push | `__init__.py:1789` | provider/proxy/cache/时刻（虽过 pipeline，但时刻与 provider 快照） | 时刻/代理热改不生效 |
| credential/model_schedule/usage_monitor | `__init__.py:1676/…` | 巡检周期与阈值快照 | 热改不生效 |
| **反例（已热）** | `__init__.py:3741/3748/3769/3783` | 中央限流、安静时间、自动接话概率、群名单 | **这些走 lambda/provider→实时**，证明收口可行 |
| **反例（开关却冻）** | `__init__.py:3765` | 自动接话总开关 bool | 见 L-1 |

- **架构取舍定性**：与台账 #3 一致（「G-DIGEST 等调度器族装配期 config 快照」）。**统一改造方向**：调度 job 内 `cfg = _config_with_runtime_overrides(config, runtime_settings)` 现取现用（poke/reactions 已如此，`__init__.py:5226/7336`），并让 `add_job` 的触发时刻在配置变更回调里 `reschedule`。

---

## §8 控制面 dispatcher / 动作执行门判定级

- **两个「dispatcher」正名**：①`control_plane/dispatcher.py`=**交互出站门面**（D3，非运维 API），执行 poke-back/reaction/meme 平台副作用，链路 `route→review→send`+`OutboundAdmissionGate.admit`+`PermitLease`（`dispatcher.py:49-69/179-193`）。它**有幂等（PermitLease dedupe_key）与准入复验，但无 `policy/gate` 群名单/安静时间/中央限流**→并入 H-1 定级（High，主动可见活动旁路群静默门）。②运维 `actions.py`=白名单 handler，事务受理+CAS+单次确认+幂等+脱敏（`actions.py:1-5`），**不做用户可见聊天发送**，属运维信任边界（Bearer+loopback+`config.py:56` 默认关）→**定级 Low/可豁免**，但需文档声明「控制面动作不受聊天 policy/gate 约束，由 Bearer+白名单 handler 承担门禁」。
- **改法**：D3 门面 `build_interaction_dispatcher(review=…)` 已预留可注入 `review`（`dispatcher.py:227`）——装配时注入「查群黑白名单+安静时间」的 review 谓词即可零改门面收口，最低成本修 H-1 的 poke-back 半。

---

## §9 单一中央分发收口清单（优先级序）

1. **C1｜表情/回戳纳入群静默门**（H-1/§8）：抽 `is_group_silent()`+`is_quiet_now()` 谓词，注入 D3 门面 review 与 reactions 入口；或把 chat 链 emotion_signal 移到 pipeline 之后。
2. **C2｜主动出站统一前置件 `ProactiveDispatcher.precheck`**（H-2）：digest/reminder/daily_assist/cookie/campus/alert 收口到一处读「群名单+安静时间+中央 proactive 限流」，today_history 的 pipeline 路径作参考实现。
3. **C3｜门禁横切节流统一原语 `Throttle`**（§3.3）：11+ 处 dict+monotonic 冷却收敛为可注入 clock/store 的单一实现与观测面。
4. **C4｜`_prepare` DB 段与 news offload 下放**（M-2/M-3）：SQLite 限流/幂等 `to_thread`；offload 决策从「id 白名单」改「能力自声明 blocking」单源。
5. **C5｜pipeline 层 per-capability 超时**（M-4）：`wait_for` 兜底 + `pipeline_timeout` OperationalIssue。
6. **C6｜入群欢迎双缺陷**（M-1）：加 `PROACTIVE_ALLOWED_IDS` 旁路被动观察门但仍查 black1；默认直发块补静默/名单检查。
7. **C7｜WIRE-SVC 注册表口径诚实化**（M-5）：补消费点或标注「阶段 2 惰性」，禁「已上线」宣称。
8. **C8｜调度器装配期快照热化**（§7/L-1/L-2）：job 内现取合并 config + 配置变更 `reschedule`；`bot_poke_*` 与自动接话开关纳入合并/收 callable。
9. **保持现状（勿动）**：decision 引擎 legacy_only（§5，诚实）；InMemory/SQLite R3 语义与 A-18 序（§3.1，实证绿）；错误卡/回滚统一异常面（§4，一致）。

---

## §末 树卫生自查（本席运行后）

- 本席直跑 python/pytest 全程带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0` + `--basetemp=$TEMP/u4-audit-*` + `-p no:cacheprovider`。
- 自查：`find plugins scripts tests -name __pycache__|*.pyc` → **0 / 0**；`test -d data` → **NO**（源码树无 data/ 残留）；root `.pytest_cache/.ruff_cache/.mypy_cache` mtime **12:30–12:47 早于本会话**，非本席产物（本席 pytest 已禁 cacheprovider）。**本席零新增缓存残留**。

*审计完。本文件为唯一事实源；与代码不一致时以代码实测为准并回写本文件。*
