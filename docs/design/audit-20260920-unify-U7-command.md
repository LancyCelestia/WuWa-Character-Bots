# 席位 U7-COMMAND：统一参数/命令面取证审计（2026-09-20）

> **性质**：只读审计席位。零代码/配置改动、零 git 写、零子代理、零真实发送、零重启。`capabilities/echo.py` 属在飞禁改面：全程只读，生成器只跑 `--check`。
> **对象**：命令面统一性——「命令语法、别名、参数解析、能力 handler 入参各有统一规格，中央解析后分发」。
> **方法**：门禁实跑 + 自建 AST/实测探针脚本（产物全部在 `%TEMP%/u7tmp/`，源码树零残留，自查见 §9）+ 全树 grep 实证 + scoped 测试实跑。禁推测措辞。
> **快照口径**：行号 = 2026-09-20 本席位取证时刻。每条发现附**锚点字符串**，行号漂移时以锚点重定位。
> **前席关系**：`docs/design/v21r4-command-format-review.md`（B4 评审材料，本席任务=把它变成实证台账，见 §6）；`docs/design/audit-20260919-unify-wave.md`（对象=渲染/WebUI，与本席零重叠）。

---

## §0 取证计划与进度（滚动更新）

| 项 | 范围 | 状态 |
|---|---|---|
| 1 | topics/别名/路由/文档 四方一致性（catalog --check + 交叉表） | ✅ 完成（§1） |
| 2 | 触发词冲突与劫持复测（探针实跑 + 台账 #27 复验） | ✅ 完成（§2） |
| 3 | handler 入参签名统一（全树 AST 扫描） | ✅ 完成（§3） |
| 4 | 参数解析散点实现清点 | ✅ 完成（§4） |
| 5 | 帮助页 vs 真实参数（抽 15+ topic 逐条比对） | ✅ 完成（§5） |
| 6 | v21r4 命令格式评审落地性复核 | ✅ 完成（§6） |
| 7 | /bot 子命令面逐个实读（权限门/参数校验/health 口径） | ✅ 完成（§7） |
| 8 | 破坏性操作二次确认与角色门清点 | ✅ 完成（§8） |
| 9 | 源码树零残留自查 | ✅ 收尾执行（§9） |

## §1 机器门与四方一致性（实证）

### 1.1 门禁实跑

- `python scripts/command_catalog.py --check` → **`command catalog is current (77 topics)`，EXIT=0**（2026-09-20 本席实跑，未用 `--write`）。
- scoped 回归合跑（`tests/test_trigger_spec.py test_trigger_bidirectional_gate.py test_capability_registry.py test_help_entries_coverage.py test_route_order_semantics.py test_market_exclusion_guard.py test_stocks_hijack_guard.py`）→ **926 passed / 2 skipped / 1 xfailed in 3.60s**（`--basetemp=$TEMP/u7-audit-scoped1 -p no:cacheprovider`）。唯一 xfail=`群主是谁` 跨能力冲突登记位（见 §1.4）。
- 上一波登记的漂移一处**已修复**：echo.py 原「二次元问句(44)」现字面为 46（`plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py:787` 锚点 `→二次元问句(46)`），与 base_router.py:453/capability_registry.py:165 的 46 对齐；v21r4-command-format-review §1.4 该条可核销。

### 1.2 四方基数（全部实跑提取，脚本=`%TEMP%/u7tmp/cross_table.py`）

| 方 | 基数 | 真值源 |
|---|---|---|
| 帮助 topics | **77**（重名 0） | echo.py `_HELP_ENTRIES`（AST）= docs/auto-facts.md:11 口径一致 |
| 帮助别名 | **501** | docs/command-catalog.md 头部（生成物，与 --check 同刻一致） |
| RouteRule 注册表 | **33** 条 + IGNORE 兜底席（has_rule=False） | base_router.py `build_route_rules`；`RouteKind` 枚举成员实值 **34** |
| route-matrix.md 问法矩阵行覆盖 | **34** kind 值（33 规则 ∪ ignore）**全覆盖、零缺失、零多余** | docs/route-matrix.md §2 |
| NoneBot matcher 注册（根 `__init__.py`） | on_message×40 / on_command×2 / on_notice×8（含条件装配 campus） | `grep -n "on_message(\|on_command(\|on_notice("` 实数 |
| 昵称动词表 | **106** 词条 | aliases.py `DEFAULT_VERB_MAP`（flat_verb_map 实跑） |

### 1.3 四方差集（词级，双向机械门台账实值）

`scripts/extract_trigger_words.py` 双向门实跑（`--full` 全量 JSON 已存 `%TEMP%/u7-extract-full.json`，143KB），与 `tests/test_trigger_bidirectional_gate.py` 台账**严格相等**（棘轮门绿）：

| 差集 | 数量 | 形态分布 |
|---|---|---|
| 路由有、help 无（LEDGER_ROUTE_TO_HELP） | **106** 条 | A 拼音词族（affinity/meme/meme_library/news/music_mode 等约 60 条）、B 繁體孪生（菜譜/兌換/維基/點歌模式/大盤/幫助/歷史上的今天等 12 条）、C 自然语言句式族（group_info 口语 9 条、reminder 做完族 10 条）、D 动词表词无 help 落点（天气预报/查询天气/hexagrams/markets 等） |
| help 有、路由坠兜底（LEDGER_HELP_TO_ROUTE） | **113** 条 | D 类为主：管理子命令 topic 未配昵称动词（模型/用量/解析/搜索/身份/怪癖/接入/队列/回复/回执/审计/最近/群策略/群文件/凭据 全族）、`/bot <名>` 族无自然入口、NL 文档句式（叫我/记得叫/看笔记N/是谁族） |
| 有路由无实现 | **0** | 33 规则全部有行为检测器且可调用（test_trigger_spec `test_all_behavioral_detectors_callable` 绿）；结构性 kind（alias/admin/natural/content/chat）由 `_STRUCTURAL_KINDS` 豁免登记 |
| 有实现无帮助 | **0** | `route_caps_without_help_topic` 实跑 = `[]`（33 规则能力全部有 topic 或 INTERNAL_CAPABILITY_NOTES 登记） |
| 无 verified 触发词的能力 | 7 | bot.alias/auto_send/chat/content/natural_command/status/tts（前 6=结构性豁免；**tts=真缺口**，见 U7-F6） |

**判定**：词级双向 diff 的机制门（棘轮+变异测试锁可红性）**是本项目命令面最强的一道统一门**，106+113=219 条缺口全部台账制受控、零暗雷。本席不重复开缺口条目；U7 新增发现全部是**这道门管不到的轴**（§3-§8）。

### 1.4 跨能力冲突（extractor 实跑）

- 唯一在册冲突：探针 `群主是谁` 同时命中 `bot.group_info` + `bot.moegirl`（MOEGIRL_QUESTION 让路链），`test_trigger_spec.py:188` 台账 xfail 管理（本次合跑唯一 xfail 即此条）。
- ASCII 词边界违规：**0**（`ascii_boundary_violations: []`，台账 #27 的 `\b` 门保持绿）。

## §2 触发冲突与劫持复测（台账 #27「劫持清零」复验）

### 2.1 `scripts/probe_trigger_hijack.py --markdown` 实跑（45 样例）

**41 OK / 4 HIJACKED**，4 条全属 ③market 族：`今天油价行情怎么样 / 金价行情如何 / 看看油价行情 / 今天金价多少` 预期 chat 实际 commodities。

🔴 **U7-F1｜P2｜探针工具与常驻测试口径互斥（证据工具失真）**
- **坐标**：`scripts/probe_trigger_hijack.py:104-107`（样例区）｜`tests/test_market_exclusion_guard.py:104-109`。
- **锚点**：probe 端 `("今天金价多少", RouteKind.CHAT, _RISK_3)`；test 端 `"今天金价多少",  # 商品卡上线后：金价是显式触发词，落商品卡而非 chat。`。
- **根因**：2026-09-13 六域批把商品触发词的 L2 落点从 CHAT 迁到 COMMODITIES（test 文件 docstring 自认「语义迁移」），常驻测试同步改锁为 `assert kind is COMMODITIES`，但**取证探针的期望表未同步**——同一字符串，探针判 HIJACKED、测试判预期。探针从此**永久 4 红**。
- **证据**：本席双跑互证：probe 输出 `③market：4`；`pytest tests/test_market_exclusion_guard.py` 全绿（926 passed 合跑内含）。docs/route-matrix.md §2 commodities 行也站测试侧（「金价」列显式触发词）。
- **改法**：before=probe `_RISK_3` 三例+裸金价例预期 `RouteKind.CHAT` → after=`RouteKind.COMMODITIES`（或把归类从 HIJACKED 判定改为「已裁决迁移」通道），并在 probe docstring 把「HEAD 36b373e 推断」更新为「2026-09-13 裁决后基线」。
- **验证**：`../ChatBot_Runtime/venv/Scripts/python.exe scripts/probe_trigger_hijack.py | tail -3` 应 `HIJACKED 合计：0`。
- **危害定级理由**：不炸生产（纯取证面），但「劫持清零」的唯一日常复跑工具失真=新劫持会被 4 条假红淹没——审计证据链断裂，P2。

### 2.2 台账 #27 关键承诺逐条实测（classify 真判定序，默认配置）

| 样例 | 预期 | 实测 | 判定 |
|---|---|---|---|
| 求籤 / 求签 | divination | divination / divination | ✅ 双正则保持 |
| zb / bz / sz / sm | 永不启用→chat | chat×4 | ✅ 四词红线保持 |
| pp / mp / yg / lssg | divination（30 词闭合族） | divination×4 | ✅ |
| 黄金股行情 | market（股词让路） | market | ✅ |
| 金价行情 / 英伟达市值 / 美元兑人民币 | commodities / stocks / fx | 一致 | ✅ 金融让路族保持 |
| 快報 / 隨機圖 / 親密度 / 點唱+参数 / 天氣預報+参数 / 匯率 / 兌換 美元 / 換匯 | 各自能力 | 全一致 | ✅ 繁體波保持 |
| tianqi/tq/diange/dg/lzt +参数 | 各自能力 | weather×2 / music×2 / randpic | ✅ 拼音波保持 |
| 我说算命都是骗人的 / 股票被套了怎么办 | chat | chat | ✅ 语境守卫保持 |
| 语音/tts/说/念 +正文 | TTS | **chat**（`bot_tts_enabled` 缺省 False，config.py:296 实证） | ⚠️ 见 U7-F6 |
| 随机表情/表情库统计/steal | meme_library | **chat**（`bot_meme_library_enabled` 缺省 False，config.py:523） | ⚠️ 缺省关所致，文档未标「默认关」——并入 U7-F6 |
| `/help` `/帮助` | IGNORE→引导语 | ignore（C-07 闭环在位，__init__.py:8039 `ignore_guide` priority 60） | ✅ |
| **`bot 状态`（无斜杠）** | — | **admin(11) 但无 matcher 消费 → 全链静默** | 🔴 U7-F2 |
| **`/Bot status`（大写）** | 与 `/bot status` 等价 | classify=**ignore**；NoneBot matcher 别名含 `/Bot` 可执行；群门禁按 classify 判非命令 | ⚠️ U7-F2 同族（判定/消费在大小写层口径倒挂） |

### 2.3 🔴 U7-F2｜P1（现网可复现的用户可见黑洞）｜「bot 」无斜杠形态 = 分类器判 ADMIN、全 NoneBot 链无人消费的静默黑洞

- **坐标**：`plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py:194-196`（`_admin_command_match`）；消费侧 `plugins/bot_unified_runtime/__init__.py:4765-4771`（`status = on_command("bot", …)`）。
- **锚点**：`return stripped == "/bot" or stripped.startswith(("/bot ", "bot "))`；`force_whitespace=True,` `priority=11,`。
- **根因**：ADMIN 判定**双实现且口径不同**——classify 层接受裸 `bot <x>`（无斜杠），NoneBot 层命令前缀取全局配置 `command_start={"/"}`（NoneBot 缺省，本仓 `bot.py:255 nonebot.init(_env_file=…)` 未覆写 COMMAND_START、`.env.example` 零命中，实测 `inspect(nonebot.config)` 确认缺省 `{"/"}`）。裸形态 classify 返回 ADMIN(11) 后：`on_command("bot")` 不匹配（无 `/`）、全部 `_is_*_event` 谓词按 kind 相等判定全 False、`ignore_guide` 只消费 IGNORE → **消息无人应答**（连引导语都没有）。而群门禁 `looks_like_command_text`（__init__.py:3801 注入）按 classify 判它是「命令」→ 群里免 @ 放行 → 放行进黑洞。
- **证据**：`%TEMP%/u7tmp/route_probe2.py` 实跑：`{"input":"bot 状态","kind":"admin","prio":11}`、`{"input":"bot help","kind":"admin"}`；全 matcher 清单枚举（§7.1）确认无 ADMIN 兜底消费点。
- **改法**：before=`startswith(("/bot ", "bot "))` → after=只认 `"/bot "`∪`"/bot"`（与 NoneBot command_start 对齐），或（更统）在 `__init__.py` 增一个 priority 11 的 `on_message(rule=_is_admin_event)` 兜底消费 ADMIN kind（两处选一，**推荐前者**：判定与消费同一口径，零新 matcher）。
- **验证**：route_probe2 重跑 `bot 状态` 应落 chat（人格自然回应）或 ignore→引导语（命令形态），不再落无消费 ADMIN；新增回归锁样例入 `tests/test_route_order_semantics.py`。
- **同类项（一并修）**：`//bot status`→ignore（有引导语，良性）；`/bot帮助`（无空格）→ignore（`force_whitespace=True` 语义，有引导语兜底，可接受）。

## §3 handler 入参签名统一（全树扫描）

### 3.1 能力协议现状（AST 普查，脚本=`%TEMP%/u7tmp/sig_scan.py` 变体）

- 能力闭包标准形 `(message: IncomingMessage, _decision: Any) -> CapabilityResult`：domains/**/capabilities/ 下 **31 处同名 `def capability`**，形态一致（decision 全为 `Any`，**零类型约束**——协议靠惯例不靠签名，统一规格的机读锚缺失）。
- 同协议不同签名的真实分歧不在这 31 个闭包（它们只是壳），而在**参数从哪来、传了什么**：见 3.2 三套角色口径。
- 「漏传 session_type 同类病」全树扫描：`assess_public_content` 调用点 3 处（__init__.py:7362、chat.py:2106、content_safety.py:104）**全部带 session_type+explicit_allowed**——台账 #36 修后现状干净；`AddressingPreferenceStore.get/set/clear(session_type=…)` 实际消费点（providers.py:369、echo.py:3714 区）键位一致。**本轴无新漏传**（诚实记录：初扫 58 命中全为 dict `.get/.set` 同名噪声，逐一排除）。

### 3.2 🔴 U7-F4｜P1（越权可达=安全缺陷，任务令明定级）｜`/bot why` 无任何角色门——与帮助页 `admin_only=True` 直接矛盾，且 `<id>` 形态为全局检索

- **坐标**：`plugins/bot_unified_runtime/__init__.py:6525-6535`（why 分支）；`plugins/bot_unified_runtime/domains/ops/smoke/diagnostics.py:673-700`（`build_why_result` 签名 `(store, *, request_id, session_id, query="")`——**无 actor_roles 形参**）；`diagnostics.py:113-120/269`（`find(token)` 按 `request_id=? OR debug_id=?` **全库无会话过滤**）；声明侧 `capability_registry.py:455` `HelpTopicDecl(topic="为什么", admin_only=True, capability="bot.why")`。
- **锚点**：`diagnostic = store.find(token) if token else store.latest(session_id=session_id)`。
- **根因**：全 admin 系 builder AST 扫描（`_is_admin/denied/ADMIN_GATE` 探针，脚本=`%TEMP%/u7tmp/scan_admin_builders.py`，全量输出下附）中，**唯一**一个「帮助页标 admin_only、实现零角色参数」的即 `build_why_result`；同目录 `build_receipt/audit/recent/queue/roles/persona/control/context/config/readiness/dialogue/llm/setup/history-clear` 全部带 actor_roles+denied 路径（27 个 builder 逐一核对）。dispatch 分支（__init__.py:6529）也不设内联门（search/parse/reply/group 都有内联门——唯独 why 没有）。

**AST 角色门扫描表**（`Y/N`=签名含角色参数；`[...]`=体内拒绝字面）：

```
status(echo.py:57) Y[_is_admin,拒绝]      decision(echo.py:160) Y[_is_admin,denied]      receipt(debug.py:78) Y[_is_admin,denied]
audit(debug.py:120) Y[_is_admin,denied]   recent(debug.py:162) Y[_is_admin,denied]       queue(debug.py:200) Y[_is_admin,denied]
roles(debug.py:225) Y[_is_admin,denied]   persona(debug.py:249) Y[_is_admin,denied]      control(debug.py:280) Y[_is_admin,denied]
history-clear(debug.py:332) Y[_is_admin,denied]  context(debug.py:387) Y[_is_admin,denied]  config(debug.py:493) Y[_is_admin,denied]
readiness(debug.py:522) Y[_is_admin,denied]  dialogue(debug.py:564) Y[_is_admin,denied]  llm(debug.py:601) Y[_is_admin,denied]
setup-llm(debug.py:887) Y[_is_admin,denied]  identity(runtime_admin.py:1694) Y[admin_only]  quirk(:1787) Y[admin_only]
runtime(:1864) Y[admin_only,super_admin]  alert(:1904) Y[admin_only]                    logs(runtime_logs.py:22) Y[_is_admin,ADMIN_GATE]
feature(feature_control.py:17) Y[super_admin]  help(echo.py:3560) Y(is_admin=可见性过滤非拒绝门)  download(files/download.py:87) N[]=H6 产品裁定全员（__init__.py:6918+route-matrix:33 三处同口径，设计内）
build_why_result(diagnostics.py:673) N []  ← 🔴 全表唯一「admin_only=True ∧ 零角色参数」
```
- **证据**：①AST 扫描表：`build_why_result … roles_param=N denial_tokens=[]`（全表唯一）；②`tests/` 全树 `grep "bot.why"` 零命中——**没有任何测试锁它的权限**；③管道无中央角色门（pipeline.py 仅透传 `actor_roles=policy.actor_roles`，判定都在 builder 内）；④群消息裸 `/bot why` 经 on_command 直达（ADMIN kind 在群门禁是「命令」免 @）。
- **后果**：任意成员（群聊免 @）：a) `/bot why` 读到**本会话最近一次**处理消息的路由判定/策略理由/角色/回复预算/LLM 终因/audit_tags（含他人消息的诊断——群里上一条通常是别人的）；b) `/bot why <id>` 读**任意会话**诊断（含私聊），`request_id=prefix_uuid4hex12`（envelope.py:36，48bit 不可爆破，但 debug_id 会出现在回执/审计/告警等展示面，凡泄露过一枚即跨会话读取一条完整诊断）。信息面=路由/策略/预算/标签，不含正文原文（`_format_why_body` 只出预算数字与标签——正文泄露有限，**定 P1 不定 P0 的理由**）。
- **改法**：before=`def build_why_result(store, *, request_id, session_id, query="")` → after=`…, actor_roles: list[str], …`+首行 `if not _is_admin(actor_roles): return _debug_result(denied)`（与 receipt 同构，拒绝话术入 user_copy 池）；dispatch 分支同步传 `_decision.actor_roles`；裸形态保留「限本会话 latest」，`<id>` 形态加会话归属校验（`diagnostic.session_id == session_id or "super_admin" in roles`）。
- **验证**：新增 `tests/test_debug_who_gate.py`（负例：user 角色 `/bot why` 与 `/bot why <id>` 均 denied；正例：admin 可读）；`../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_debug_who_gate.py tests/test_documentation_consistency.py -p no:cacheprovider --basetemp=$TEMP/u7-who -q`。
- **附带面**：`docs/route-matrix.md:33` 管理员名单（`status/parse/reply/群文件/cookie/logs/search/group 等`）漏列 why——修码后同批把 why 补进该行明单，消灭双口径。

### 3.3 🔴 U7-F3｜P2｜角色判定三套并行：六级 actor_roles / 裸 config.bot_admin_user_ids 名单 / Telegram 名单——同一「管理员」三种口径

- **坐标与三形态**：
  1. **六级角色（权威）**：`domains/chat_reply/policy/roles.py:25-41`（`resolve_roles`，**超管自动叠加 admin**，admin_user_ids = `bot_admin_user_ids ∪ bot_telegram_admin_user_ids`，roles.py:53-61）→ `_decision.actor_roles` → builder 内 `_is_admin(actor_roles)`。
  2. **裸名单（旁路 matcher 族）**：`__init__.py:4938-4943` `_is_admin_origin(event) → user_id in config.bot_admin_user_ids`——**无超管叠加、无 TG 管理端并入、无 blocked 语义**；消费方=cookie_admin(5641)/file_export(5459)/nickname_set(5645)/file_notice(5031) 与 handler 内版 group_file_stats(5679)。
  3. **TG 专属名单**：`_handle_mail_control`（__init__.py:5868-5875）用 `bot_telegram_admin_user_ids + chat_ids` 判 `/mail`。
- **实锤分歧场景**：①仅列入 `BOT_SUPER_ADMIN_USER_IDS` 的超管：`/bot status/receipt/logs`（actor_roles 路，超管叠 admin→放行）✅，但 `/bot cookie`、`/bot 群文件`、`/bot 昵称 set`、文件导出（_is_admin_origin 路）→ **被拒**；②TG 管理端用户：roles.py 已并入 admin（QQ+TG 全域 id 空间混用的风险另账），`_is_admin_origin` 不认——`/mail` 可用而 `/bot cookie` 不可用；③`runtime_settings` 热改 `BOT_ADMIN_USER_IDS`（若键在 SETTABLE）只影响 roles.py 消费面，不影响名单快照路——**同一名词两处读**。
- **锚点**：`return user_id in {str(item).strip() for item in config.bot_admin_user_ids}`。
- **改法**：before=matcher 谓词各自 `await _is_admin_origin(event)` → after=统一 `role_settings.resolve_roles(message)` 产 roles 集合后判 `"admin" in roles`（把 bypass 族 5 个 matcher 的角色判定收敛到 roles.py 单一事实源；`_is_admin_origin` 改为薄封装或直接删除）。
- **验证**：新增参数化测试：仅超管 id 过 `/bot cookie` 谓词应 True（现状 False=复现）；`python -m pytest tests/test_admin_roster_and_roles.py tests/test_identity_preference_commands.py -q` 族回归。
- **定级**：P2（功能不一致+权限模型双口径；无越权放大方向——裸名单只可能更严或相等，`bot_admin_user_ids` 是 roles 并集子集；但对「超管不可侵犯」设定（AGENTS 铁律/管理团队分区）构成实弹违例）。

### 3.4 🔴 U7-F5｜P2（统一 mandate 正面撞击）｜第二套分发系统：6 个阻断式文本命令 matcher 不走 base_router 路由表，/bot 内部 again 一条 33 分支 if/elif 手写分发

- **坐标**：bypass 阻断族（priority<50、block=True、谓词与路由表无关）：`__init__.py:4773 mail_control(on_command "mail")`、`5464 file_export(p=8)`、`5562 image_search(p=46，谓词=函数体内联正则 ^[/!！]?(?:搜图|搜圖))`、`5641 cookie_admin(p=8)`、`5648 nickname_set(p=8，内联 _NICKNAME_RE)`、`5674 group_file_stats(p=8，内联 ^/bot\s+群文件)`；被动旁路族（block=False，合法监听）：meme_absorb(4805)/dirty_guard(4974)/campus(4997)/各类 on_notice。**同一文本 `/bot 群文件` 在 classify 记 admin/bot.status(11)，实际执行者是 p=8 旁路 matcher**——审计轨迹与真实执行者两套账。
- **第二级散落**：`/bot` 正主 `_handle_status`（4765→6487）内部又是 **33 个 elif 的手写分发链**（memory/好感度/why/receipt/audit/recent/queue/history clear/context/llm/setup llm/config/readiness/dialogue/roles/persona/pause|resume/feature/runtime/model/quirk/identity/route/routes/search/parse/download/reply/alert/subscribe/logs/group/else→help/else→status），每个分支**自带参数解析**（removeprefix/split/mode_map/digit 检查各写各的），与 §4 散点完全同构。
- **证据**：matcher 全清单实数（§1.2）；分支链读源于 6487-7211 逐支；「谁先消费」由 priority 实排（8<10<11…46）。
- **改法（方向，给迁移顺序见 §10）**：路由表扩 `ADMIN_SUB` 子命令声明（kind=ADMIN + verb 列）→ 一个中央 `/bot` 解析器（剥前缀→查声明表→产 (capability, verb, argv, roles) 结构化载荷）→ 6 个 bypass matcher 改为「注册进声明表的 kind + 谓词=_cached_route_decision」或至少把角色判定并入 roles.py（§3.3）；image_search 内联正则升为 `is_image_search_command()` 入 `runtime/base_router` 消费面（对齐其它能力的检测器函数惯例）。
- **验证**：改后 `list_route_rules_for_audit()`/`/bot routes` 应能看到子命令面；`test_documentation_consistency` 全绿。

## §4 参数解析散点清点（「同一语法两套语义 / 一处支持一处不支持」实证）

### 4.1 同族解析的实现份数（每族至少两处独立实现，全带精确行号）

| 参数语法族 | 实现份数与坐标 | 口径差异（实测/实读） |
|---|---|---|
| `键=值`（中文键） | 1 份：media_archive `_parse_directives`（`domains/media/capabilities/media_archive.py:120`，值取到空白、支持 分类=/IP=/作品=/角色=/子路径=） | **全树仅此一家用 `X=Y` 中文键**；help 例 `收藏 分类=cosplay IP=鸣潮`（echo.py:2069/2993）与实现一致 ✅ |
| `--flag=值`（双横线） | 2 份：memory `--sensitivity=`（help echo.py:502；解析在 `route_memory_command`）；runtime `--instance <名称>`（runtime_admin.py:106 起 `_extract_instance`） | 同用 `--` 前缀但一个 `=` 连接一个空格连接；**两种键法无中央约定** |
| 数量/分页参数 | **≥5 份互不相同**：①recent `_parse_limit`（debug.py:1809-1812，`min(20,max(1,int))`，非法→ValueError 兜默认 5）；②logs（__init__.py:7025-7031，`arg_parts[1].isdigit() else 50`——**非数字静默取默认、无上钳**，帮助页写 1-200（echo 日志条目）钳制在 builder 内与否待 §5-3 复核）；③`点歌 候选数`、④`塔罗 三张`（中文数字在 divination 另一套）、⑤divination/notes 的 `N` 序号（notes mark_done 与 reminder cancel 各拆各的） | 同一「[数量]」词位：有的中文数字可、有的只 digit；有的 clamp 有的不 clamp；有的非法回用法有的静默默认 |
| 开关 开/关 词族 | ≥6 套词表：reply mode_map（__init__.py:6932-6936，中文+英文双轨）；feature `on|off|reset`（echo.py:457 帮助口径）+`enable|disable|reset`（**同一功能页内两种动词并存**）；`亲密模式 开/关`（content_route L4，只中文）；pause/resume（只英文，roles 判 admin）；meme 库/订阅 `添加|移除` 中英混合；runtime `set|reset`（英文） | 「重置」一个语义四五个词：`默认/auto`、`reset`、`恢复`（LEDGER 登记「暂停|恢复」不可达）、`unset-*`（identity） |
| 时间词 | 1 主份：reminders `_DAY_OFFSETS/_ABS_TIME_RE/_PERIOD_ONLY_RE`（`domains/schedule/store/reminders.py:52-58,301-367`，REM-DAWN/EVE 双修后含 明早/明晚）；但 daily_assist 的推送时刻、today_history 推送、subscribe 的 cron 时点各用配置字符串，**不共用语义词表** | 「明晚8点」只在提醒面有语义；`8点提醒` 与 `每天8点` 分属两套解析 |
| 城市/地点 | weather `is_weather_command`+查询变体链（domains/weather/capabilities/weather.py:167 起）；market 市场词过滤（`_NON_STOCK_RE`/`_STOCK_HINT_RE`，market.py:57-63）；media_archive `子路径=` 消毒——三个域各自维护「词表+守卫正则」，**词界判定同源惯例仅靠自觉** | 「商品↔行情股词让路」正则在 base_router.py:323 `_FIN_STOCK_HINT_RE` **又抄了一份**（注释自认「market.py 本席只读，故正则在此地持有」——两份同义正则双点维护） |
| cookie/凭据位 | platform_credentials `parse_cookie_command`（domains/core/credentials/platform_credentials.py:54-95，手写 split+前缀判定，未知功能词**兜底当 import**——注释自认「交给 import 分支按缺平台报错」，即非法参数不报错只错位） | 与 runtime（白名单键）/reply（未知值回用法）的「非法输入回用法」惯例相反 |

### 4.2 「一处支持另一处不支持」案例（词级实证，均可复跑）

- `守岸人 帮助` / `守岸人 状态`（空格+管理动词）→ **chat**；`守岸人帮助` → alias✅；`守岸人 天气 上海` → natural_command✅；`守岸人 点唱 晴天` → **chat**；`守岸人点唱` → alias✅（`%TEMP%/u7tmp/route_probe4.py` 实跑）。**三套词表不同步**：DEFAULT_VERB_MAP(106) ≠ natural_command 意图词表 ≠ 各 `is_*` 触发词表，同一「昵称+空格+命令」形态的支持面按词碰运气。command-catalog.md 使用入口节宣称「`守岸人 <命令>`…等价于对应自然语言入口」——对没有自然语言入口的管理动词族为**幻影承诺**（此条一半在 LEDGER_HELP_TO_ROUTE D 类已登记，新增量=空格形态的三分表漂移无门管）。
- 🔴 **U7-F6｜P3｜TTS/meme_library 帮助页与触发面未标「默认关」**：route-matrix tts 行与帮助「语音」topic 把 `说/语音/念/tts/say` 登记为可用触发，但 `bot_tts_enabled`/`bot_meme_library_enabled` config 缺省 False（config.py:296/523 实证）→ 默认部署下发 `说 你好` 落 chat 零反馈。extractor 亦实跑 `capabilities_without_verified_triggers` 含 bot.tts。帮助文案「失败兜底」未写「未启用时不响应」——文档与缺省行为双口径。

（§5 起为逐项比对与清点，发现编号 U7-F7~F10 在 §5/§7 定义，§11 汇总。）

## §5 帮助页四要素 vs 真实 handler 参数（16 topic 逐条比对表）

比对法：`_HELP_ENTRIES` 教程行（AST dump=`%TEMP%/u7tmp/help_dump.json`）↔ 实际解析点实读/实测（探针 `%TEMP%/u7tmp/route_probe5.py`）。图例：✅=吻合；🔴=幻影/隐藏参数实锤。

| topic | 帮助宣称 | 代码实况（证据） | 判定 |
|---|---|---|---|
| 状态 | `参数=无` | `/bot status foo` → 坠 help 兜底（dispatch 精确等值 `"status"`，__init__.py:7180） | ✅ |
| 最近 | `[数量]` 1-20 默认 5 越界收敛 | `_parse_limit` `min(20,max(1,int))`（debug.py:1809-1812） | ✅ |
| 回执 | id 必填，缺省回用法 | debug.py:93-99 usage 分支 | ✅ |
| 日志 | `[级别] [数量]` 1-200 默认 50「先级别后数量」 | builder 钳 1-200（runtime_logs.py 实读 ✅）；但 ①级别非法 token **静默按 info**（`__init__.py:7026-7029`），②`/bot logs 20`（数量放首槽位）=level 判非级别→limit 缺失→50，与 recent 的裸数量槽位互换不互通（实测 kind 全 admin，行为差异在参数位） | ⚠️ U7-F10b |
| 上下文 | `[文本]` 可选、只出数字摘要 | actor_roles 门在 builder（AST 扫描 roles_param=Y） | ✅ |
| 回复 | 未知值回用法「不再静默当默认」 | mode_map + `normalized_mode is None` 回用法（__init__.py:6932-6958） | ✅ 文案与代码罕见地完全对齐（09-17 修痕） |
| 群策略 | add/del/set/clear/list + 黑1白1 别名 + 数字群号 | 分支逐条核对（__init__.py:7040-7158）：action_aliases 词表含 加/加入/删/刪/移除/设/设置/清/清空/reset/查/查看，`part.isdigit()` 校验、档位非法回用法 | ✅（唯一 ⚠=clear 零确认，入 §8） |
| 凭据 | 六功能词 status/import/login/check/expiry/（--probe 归 alert） | `parse_cookie_command`：**未知功能词静默按 import 拆**（platform_credentials.py:93-94 注释自认「交给 import 分支按缺平台报错」），非法输入不「回用法列可选项」而「错位报错」 | ⚠️ U7-F10a |
| 个股行情 | 「股价 / **市值** / stocks：参数=无（不点名公司）→ 九家面板」 | 实测 `市值` → **chat**（`英伟达市值`→stocks ✅、`股价`→stocks ✅、`stocks`→stocks ✅）；`docs/route-matrix.md:56` 明写「`市值` 需与公司别名共现触发（裸词不触发）」 | 🔴 **U7-F9 幻影参数**（帮助页与路由文档同词两口径） |
| 汇率 | 面板/货币对/带金额换算三行 + 「金额可省，省略按 1 计」 | 实测 `汇率`/`美元兑人民币`/`100日元换多少人民币`/`999 美元换人民币`/`兌換 美元` 全落 fx | ✅ |
| 身份 | show/set/tag/clear 管理员 + set-name/set-gender/unset-* 自助（≤32 字、非法值列出可接受值） | echo.py:3685-3780 实读：子命令白名单、控制字符消毒、≤32 钳、管理员门前拦截自助——文案与实现一致 | ✅ |
| 昵称 | 「部分管理命令会要求回落 /bot 形式」+ `/bot 昵称 set <5-11位QQ> <≤32字>` | `_NICKNAME_RE = r"^/bot\s+(?:昵称\|暱稱\|nickname)\s+set\s+(\d{5,11})\s+(\S{1,32})$"`（__init__.py:5643）逐字符吻合 | ✅ |
| 笔记 | 记/列表/看N/做完N/删笔记N + 自然语言「X做完了」 | 实测 `看笔记 3`/`做完 3`/`笔记列表` 全落 reminder 复用路由 ✅ | ✅ |
| 下载 | 全员开放（H6 定案）+ SSRF 边界 downloader 侧 | dispatch 分支注释同口径（__init__.py:6917-6921） | ✅ |
| 帮助 | 权限分层/查无回相近 | `_visible_help_entries(is_admin)` + `_help_unknown_body` | ✅ |
| 语音 | 「触发词后必须跟正文」+ `说/语音/念/tts/say` 族 | 实测 `语音 你好`/`说 今天潮汐很安静`/`tts 你好` → **chat**（`bot_tts_enabled=False` 缺省，config.py:296）；帮助/矩阵行均未标「默认关」 | 🔴 U7-F6（§2.2 已定案） |

**小结**：16 抽 1 实锤幻影（市值）、1 默认关未标注（语音）、2 参数校验惯例分叉（cookie/logs）、其余吻合。帮助页整体质量高（回复/身份/昵称三页逐字符级对齐），**缺陷集中在「词表间无机器门」的缝上**——正是统一规格要焊死的位置。

## §6 v21r4-command-format-review 落地性复核（把评审材料变成实证）

1. **基线数字全部仍然成立**（本席实跑/实算）：77 topics（重名 0）/501 别名/37 公开+40 管理员/33 规则+IGNORE/106 昵称动词（评审时未提动词表基数，补登）。§1.4 两条漂移均已修复（echo 44→46；AGENTS/auto-facts 77 口径），**可核销**。
2. 🔴 **落码波及清单的坐标性错误**（评审材料 §3.3 第 3 行）：「仅 ADMIN 路由内加四段式解析升级点」——**实证 ADMIN 路由规则在 production 消费链上是零消费者的空转位**：`admin_match` 产物 kind=ADMIN 只被 ①群门禁 `looks_like_command_text` ②影子决策对照 消费；真正的 /bot 执行链走 NoneBot `on_command("bot")`（§3 已证「bot 无斜杠形态」即这条分叉的实弹后果）。**四段式解析器若按材料落在 base_router ADMIN 分支，重启后现网行为零变化**（没有东西经过它）。正确落点=替换 `_handle_status` 33 分支 if/elif + `_handle_alias` 16 分支 if/elif 两张手写表（本席 U7-F5 坐标），ADMIN kind 侧只需同步谓词口径。
3. **兼容期「只加不改不删」与三张词表现状兼容性**：四段式新形态本身不冲突；冲突在**新解析器的词表来源必须同时收编** DEFAULT_VERB_MAP(106)+MODULE_ALIASES(15)+`_COMMAND_ACTION_ALIASES(12)`+各 `is_*` 内嵌词表+6 个 bypass matcher 私有正则（`_NICKNAME_RE`/`^/bot\s+群文件`/搜图内联式/`is_cookie_command`/`is_file_export_command`/`parse_mail_command`）——评审材料的落码清单**没把后五处列进波及面**，属实施期必漏项，本席补账。
4. **§2.2 方案 A/B（14 领域 vs 20 域）分歧本席不裁**；仅补一条实施侧事实：`domains/` 20 域中 render/transport/core 三域无 topic 归属冲突风险（§3.1 表已把合并转发挂 render、队列挂 transport），真正悬而未决的是资讯族 5+群信息+语音 8 行（与材料 §五.2/3 一致，无新增）。
5. 迁移顺序建议：并入 §10 规格册（含不破坏现网触发的六步序）。

## §7 /bot 子命令面总账（逐个实读结论）

**分发拓扑**：`on_command("bot", aliases={"/bot","Bot","BOT","/Bot","/BOT"}, p=11)` → `_handle_status`（__init__.py:6487-7211）33 路 if/elif。优先级 8 的 4 个旁路 matcher（cookie/nickname_set/群文件/文件导出）先截胡自己的子形态。

| 子命令 | 角色门位置 | 判定 |
|---|---|---|
| status/receipt/audit/recent/queue/context/config/llm/setup llm/readiness/dialogue/roles/persona/pause/resume/history clear | builder 内 `_is_admin(actor_roles)`（AST 全表 ✅） | ✅ |
| search/parse/reply/group | dispatch 内联 roles 集判定 | ✅ |
| runtime/model/feature | `_is_admin` ∧ set/reset/persona写/model写/nickname写 再上 **super_admin**（runtime_admin.py:1878-1887；feature enable/disable 亦 super-only，help:457 同口径） | ✅ |
| identity/quirk | builder `admin_only`（自助子命令在管理员门前拦截，echo.py:3685 区） | ✅ |
| download | 无门=**H6 产品裁定全员**，SSRF 在 downloader（__init__.py:6917-6921 注释+route-matrix:33 三处同口径） | ✅（设计内） |
| alert/subscribe/model usage/route(s)/帮助族 | alert→builder 门；route/routes 公开只读（topic admin_only=False 一致）；subscribe 能力内门 | ✅ |
| **why** | **无——见 U7-F4（P1）** | 🔴 |
| **decision** | builder 有门（echo.py:175）但**全树无消费者**——见 U7-F7（P2） | 🔴 |
| **cookie/昵称set/群文件/文件导出** | `_is_admin_origin` 裸名单——见 U7-F3（P2） | 🔴 |

- **AGENTS「无顶层 health 子命令」口径**：✅ 成立——dispatch 无 `health` 分支（`/bot health` 坠 help 兜底），健康信息实在 `/bot status` + 嵌套 `/bot model health`（runtime_admin.py:446 渠道健康报告，嵌套形态不违口径）。COMMANDS.md↔执行面逐词对照：除下列两类外全部有真实落点——①**唯一死词 `/bot decision`**（COMMANDS.md:23 登记「`/bot decision [N]`（别名 决策/决策引擎/decision，昵称形式等价）」，两形态均死，见 U7-F7）；②4 词由 priority-8 旁路 matcher 消费而非 dispatch（群文件/cookie/昵称 set/文件导出——**可用**，但属 U7-F5 第二分发系统）。`/bot action`、`/bot workspace` 系 COMMANDS.md:149 文中自否「不要把 API 路径当聊天命令」，非登记命令，不计差。
- 🔴 **U7-F7｜P2｜`/bot decision` 幻影命令：帮助 topic、COMMANDS.md、DEFAULT_VERB_MAP(`决策→bot.decision`)、实现体+权限门+回归测试 四层齐备，生产分发链零接线**。实测链：`/bot decision 20`→dispatch 无分支→help 兜底=弹「决策」说明页；`守岸人决策 20`→alias 解析成功→elif 链无 `bot.decision`→else 兜底回「请在 /bot 形式下使用：/bot 决策 …」→**把用户指向另一个死形态**（`/bot 决策` 同样只出说明页）。`grep '"decision"' __init__.py`=0 命中；`build_decision_query_result` 全树消费者=tests/e2e 脚本 only。根因：双向门判定「可达」的标准是**词表解析层**（verb 命中即绿），不验执行层落点——门的口径盲区。改法：dispatch 增 `elif command_text in {"decision","决策"}` → `build_decision_query_result(actor_roles=…, query=…)`（一行分支）+ 把「verb→存在消费者」升格为常驻门（扫 DEFAULT_VERB_MAP 值 ∈ alias-elif 链 capability 集 ∪ dispatch 分支 capability 集，缺口即红——本席验算当前缺口集={bot.decision, bot.memory, bot.config, bot.readiness, bot.persona, bot.roles, bot.history, bot.control}，其中后 7 个在 /bot 英文链有真消费者、属「回落提示可用」半存活，唯 bot.decision 两头全死）。验证：`/bot decision` 走通+棘轮门新增样例。
- 🔴 **U7-F8｜P3｜/bot 中文动词面三分残缺+aliases 字段一肩双职**（实测三层，脚本=`%TEMP%/u7tmp/route_probe4.py`+dispatch 逐支）：①`/bot` 中文形**真执行**的只有 MODULE_ALIASES 15 词条映射面（帮助/模型/设置/参数/功能管理/维基/百科+繁體幫助/設置/參數 等，aliases.py:27-43）；②**只在昵称形真执行**（`守岸人状态`→status ✅ 实跑；`/bot 状态`→help 页非执行）：状态/为什么/日志/天气/点歌/吃什么/快报/好感度/订阅/偷表情 等 alias-elif 链 15 能力词——`is_memory_command_text` 只认 `startswith("memory")`（memory.py 实读），`/bot 记忆` 亦死；③**两形全死且回落话术指向死形态**（`守岸人记忆`→else 提示「请在 /bot 形式下使用：/bot 记忆 …」→该 /bot 中文形又坠 help 页）：记忆/配置/就绪/人格/角色/清理历史/暂停/继续/决策 共 9 词。同一 topic `aliases` 字段在 user topic=触发词、在 admin topic=检索键+动词表键，三用途两语义无标注。定 P3：有 help 页兜底不静默、语义可猜，但 COMMANDS.md:13「`/bot 帮助`（等昵称形式等价）」式话术与用户直觉（别名=命令）冲突。改法=MODULE_ALIASES 补齐 admin 中文动词（纯加法，零现网触发变化）或 help/COMMANDS 明写「中文别名仅检索/仅昵称命令」，配合 §10 声明表 subverbs 列根治。

## §8 破坏性操作确认语义清点（角色门 ✅ / 二次确认 ❌ 全景）

全命令层 `grep 确认|confirm|二次|再发一次` **零确认闸实现**（「确认」字样全是回执文案）。逐操作判定：

| 操作 | 角色门 | 幂等/范围限制 | 即时副作用 | 判定 |
|---|---|---|---|---|
| `/bot group clear <档位>`/`set`（整表覆盖） | admin ✅ | 无 | 立即持久覆盖名单 | 🔴 无确认；档位打错=全群静默/全群放行，建议 set/clear 要求尾词 `确认` 或 preview-first |
| `/bot runtime reset`（**省略 KEY=清空全部覆盖**） | super_admin ✅ | 版本化可回滚（config_backend CAS；非 backend 路径 JSON 快照不可回滚） | 立即 | ⚠️ 高危零确认；feature 子系统已有 `preview` 先例（echo.py:457）——建议同构补 `reset --preview` |
| `/bot history clear` | admin ✅ | 范围=本会话×本发送者×本实例（debug.py:332 实读） | 清历史 | ✅ 范围自限，可接受 |
| `/bot pause` / `resume` | admin ✅ | 状态幂等 | 全局软暂停 | ⚠️ 可接受（影响可见、可逆一行恢复） |
| `/bot feature disable <ID>` | super ✅ | **preview 在位**（enable/disable 前可 preview 看影响面）+审计+版本 | 生产功能门即时生效 | ✅ 本仓唯一「预检-变更」样板，建议成为统一规格模板 |
| `/bot model remove/reset/price 清除` | super ✅ | 注册表 JSON 可回写 | 计费/选型即时变化 | ⚠️ price 清除=该模型记 0 元/未计价（#37 账见面）——建议清除前列旧值 |
| `/bot 昵称 set` / `runtime nickname remove` | 正则+admin/super ✅ | 覆盖式 | 称呼变化 | ✅ 低危 |
| `/bot cookie import` | 名单门（⚠️U7-F3） | 「同名不覆盖」帮助口径 | 平台解析凭据热替换 | ⚠️ 修 F3 时一并复验「同名不覆盖」是否代码实真 |
| 媒体归档/收藏 | min_role super_admin ✅ | sha256 去重+限额 | 落盘写 | ✅ |
| `/bot memory delete <fact_id>` | 本人作用域 | 幂等（未找到明说） | 单条删 | ✅ 被遗忘权方向不设门=正确取舍 |

**清单结论**：无确认即可产生副作用且值得立项加门的=**group clear/set、runtime reset（全清）、model price 清除** 三处；其余或范围自限、或已有 preview 先例、或方向性豁免合理（隐私删除权）。

## §9 树卫生自查（席位纪律）

- 全部脚本产物：`%TEMP%/u7tmp/{scan_admin_builders.py,cross_table.py,route_probe2-5.py,sig_scan.py,dump_help.py,pick_topics.py,ledger_counts.py}`、`%TEMP%/u7-extract-full.json`、pytest basetemp=`%TEMP%/u7-audit-scoped1`——零落源码树。
- 收口实跑（2026-09-20 席位末）：`find plugins tests scripts -name "__pycache__" | wc -l` = **0**；`*.pyc` 0；`data/` 源码树根不存在；`domains/weather/assets/qx.json` 完好在位（**362,774B** 实测，铁律 6 否定规则件）。全程直跑 python 均带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest 均带 `-p no:cacheprovider --basetemp=$TEMP/…`。
- **如实登记非本席存量**：树根 `.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/` 三目录 mtime=当日 12:30-12:47（**均早于本席首跑**，且本席未调用 ruff/mypy、pytest 全带 no:cacheprovider）——并行席直跑残留，非本席产物；按「共享树只动自己面」纪律**不删除**，移交收尾合流波按台账#1 规程处置（先例：0919 审计 §6.3 pycache 处置法）。另树根 `.tmp-test/`（V21R5 §L 在案「被并发测试进程锁定待清」）、字面目录 `%TEMP%/`（多席共用环境产物）、`.cp-test-output.txt` 均系并行席存量，本席零触碰、只登记。
- echo.py 零触碰：只读 + `--check`；未跑任何 `--write` 类命令；未做 git 写操作。本席在树内唯一新增文件=本审计报告。

## §10 命令与参数统一规格建议（含迁移顺序）

**目标形态**（对齐 mandate「中央解析后分发」，全部兼容现网 501 触发词零变化）：

1. **一张声明表**：`ROUTE_CAPABILITY_DECLARATIONS` 增 `subverbs`（/bot 子命令+中文形）与 `matchers`（现旁路 5+1 族收编进 kind 声明，`image_search/cookie/export/nickname_set/群文件/mail` 各归 kind）；`HELP_TOPIC_DECLARATIONS` 已具同哲学——两表并成每能力一行全集。
2. **一个解析器**：`runtime/command_parser.py` 纯函数 `(text, roles) -> ParsedCommand{scope, capability, verb, argv[], raw}`；词表**全部 import 声明表派生**（禁手写）；把 `_handle_status` 33 elif、`_handle_alias` 16 elif、6 bypass 谓词、`parse_cookie_command`/`_extract_instance`/`mode_map`/`action_aliases` 六类手写解析逐个替换为查表+通用 `K=V`（两种键法统一为一：英文键 `key=value`，中文键做别名映射；数量/级别/分页走通用 typed-arg：`int 槽位+min/max clamp+非法回用法`，消灭 recent/logs 位差与 cookie 兜底 import）。
3. **一道角色门**：唯一 `require_role(parsed, roles, spec)`——每个子命令在声明表登记最低角色，旁路 `_is_admin_origin` 与 builder 内散 `_is_admin` 保留为薄委托；超管叠加/TG 并入只此一处。
4. **一条确认约定**：声明表加 `destructive: bool` + `preview: bool`；destructive 命令统一支持 feature 式 preview，`clear/全量reset` 强制二次口令尾词。
5. **门的门**：把本席三处缝补成常驻锁——①verb/别名→执行链真消费者可达（修 U7-F7 类）；②help 四要素中出现的裸触发词逐词 classify 实测落点=自能力（修 U7-F9 类，探针化，复用 route_probe 方法）；③「admin_only topic ⇒ builder/dispatch 必含角色参数」AST 门（修 U7-F4 类，本席扫描脚本即雏形）。

**迁移顺序（不破坏现网触发的六步）**：
① 纯加法安全波：修 U7-F4（why 加门）/F7（decision 接线）/F9（市值文案）/F10（cookie/logs 校验惯例）+ probe 期望表对齐（F1）——零触发面变化；
② 声明表扩列（subverbs/matchers/destructive/role）+ 常驻锁 ①②③ 上线（红点即台账棘轮起步，参照 bidirectional gate 成熟做法）；
③ 中央解析器落地但**缺省关**（`bot_command_parser_enabled=False`，双跑影子对照，复用 decision shadow 基建）；
④ 旁路 matcher 族逐族收编（cookie→export→nickname→群文件→搜图→mail），每族一 gate 一回归，角色判定同步换血（修 F3 分歧面）；
⑤ `_handle_status`/`_handle_alias` 两链切解析器，ADMIN 谓词与 NoneBot command_start 对齐（修 F2 黑洞），MODULE_ALIASES 中文动词补齐（F8）；
⑥ 观察期后回收兼容层与否由用户单裁（继承评审材料 §2.6「不做默认裁定」）。

## §11 发现汇总表（severity 分布）

| # | 严重度 | 一句话 |
|---|---|---|
| U7-F2 | **P1** | 无斜杠 `bot X` 被分类器判 ADMIN 而全链无人消费=用户可见静默黑洞（判定/消费双实现漂移） |
| U7-F4 | **P1** | `/bot why` 越权可达：帮助页 admin_only=True、实现零角色参数，裸形态泄露本会话内部诊断、`<id>` 形态全局无会话过滤 |
| U7-F3 | P2 | 「管理员」三套口径：六级 actor_roles / 裸 config 名单 `_is_admin_origin` / TG 专属名单——超管在 cookie/群文件/昵称set/导出 四面被拒 |
| U7-F5 | P2 | 第二套分发系统并存：6 阻断旁路 matcher + /bot 33 elif + alias 16 elif，`/bot 群文件` 审计记账与实际执行者两套账 |
| U7-F7 | P2 | `/bot decision` 四层登记齐备、生产分发链零接线的幻影命令，且 alias 回落话术指向另一死形态 |
| U7-F1 | P2 | 劫持取证探针与常驻测试对同串互斥判红（探针永久 4 假红=新劫持被淹没） |
| U7-F6 | P3 | 语音（及 meme_library）帮助/矩阵面未标「默认关」，默认部署触发即坠 chat 零反馈 |
| U7-F8 | P3 | /bot 中文动词面三分残缺（9 词两形全死，含 alias 回落话术指向死形态）+ aliases 字段一肩双职无标注 |
| U7-F9 | P3 | 个股行情帮助页裸词「市值」=幻影参数，与 route-matrix 同词自否 |
| U7-F10 | P3 | 参数校验惯例分叉：cookie 未知词静默转 import；logs 非法级别静默 info、数量槽位与 recent 不互通 |
| — | 正面 | 词级双向棘轮门（106+113 台账全受控）+变异测试锁可红性=全仓最强统一门；reply/identity/昵称三页帮助逐字符对齐；feature preview=确认语义现成模板 |

*席位 U7-COMMAND 完。所有「已修复/现状」判定均附实跑输出或 AST/grep 坐标；离线证据≠生产生效。*
