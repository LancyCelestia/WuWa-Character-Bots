> 出处＝2026-10-02 修复波的取证席 HB-A 产出（原写于 gitignore 的 `.superpowers/sdd/2026-10-02-fixwave/HB-A-architecture-EVIDENCE.md`，该目录不受版本控制；本文件是**入库副本**，防下一次整树还原再吃掉一次）。
> 该席最终被**当日额度墙**打断（43-54 次调用即断，非 150 顶死法），末节可能不完整；引用前请按文中命令现算复核。
> 出处＝2026-10-02 修复波的取证席 HB-# HB-A · 架构与功能篇（写给完全没看过这个项目的下一个 AI）

> 席位 HB-A，波次 `2026-10-02-fixwave`。入口是 `AGENTS.md`，但**本文不照抄它**——凡是 AGENTS 的字面与代码不一致处，本文以**代码真身 + file:line** 为准并标出分歧（本项目自认「叙述≠真身」有先例，台账 #48★）。
> 🔴 落笔现场＝**断电后未经核验的工作树**，见文末「断电后现场未核验」。
> 叙述性文档一律**不手写会漂移的计数**（AGENTS 规则 10）；本文所有计数只写「以机器册 / 实跑为准」。

---

## 1. 两棵树：代码仓 ≠ 运行数据根

| 树 | 绝对路径 | 内容 | 规矩 |
|---|---|---|---|
| 代码仓（唯一代码区） | `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot` | git 跟踪的源码、测试、文档、`personas/` | 只有这里可以读写代码 |
| 运行数据根 | `...\ChatBot\ChatBot_Runtime\` | `venv\Scripts\python.exe`、SQLite、FAISS/嵌入、聊天记忆、cookie、日志、媒体缓存、`card_render_assets/`、**运行时覆盖册** | **一律只读**（AGENTS 规则 1/2/9）：禁写禁删禁改 `journal_mode`/VACUUM |
| 归档 / 语料 / 库 | `ChatBot_Archive\`、`ChatBot_Libs\`、`语料库\` | 历史与素材 | 不扫描不索引不设为工作区 |

### 1.1 `data/` 重映射的唯一实现：`scripts/runtime_paths.py`

配置里写的 `data/xxx` 是**相对声明**，真落点在 Runtime。换算全仓只有一处实现：

- `PROJECT_ROOT` = 仓库根（`runtime_paths.py:28`）。
- `runtime_path(value)`（**`:280`**）＝唯一重映射入口：绝对路径原样 resolve；相对路径剥 `./`、对 `data/` 前缀**大小写不敏感**改写 → `runtime_data_dir()/去掉 data/ 的余下部分`；非 `data` 开头的相对路径则按仓库根拼（`:295`）。口径与 `config.py` 的路径解析器对齐（注释 `:285-287`）。
- `runtime_data_dir()`（`:276`）＝ `guard_test_runtime_root(_as_root(_effective_data_root_text()))`。
- `_effective_data_root_text()`（`:189`）＝ 三级读数：**进程 env `BOT_RUNTIME_DATA_DIR` → 盘上 `.env` / `.env.prod` 声明 → 缺省字面量 `data`（源码树）**。生产 `.env` 把它指向 `ChatBot_Runtime/data`，所以生产写盘全在 Runtime。
- 读盘上声明用 `_dotenv_file_value()`（`:74`）——**故意不看 `os.environ`**：测试进程的 env 已被装配层挪过，「什么叫生产根」只能问盘上声明（docstring `:75-79`）。`.env` 值形如 `[`/`{` 的按 JSON 解码。
- 触发重映射的配置键要加进 `config.py` 的 `path_fields` 元组，否则相对路径不会被搬出源码树。

### 1.2 测试进程的 Runtime 根隔离缝（本波最容易造成静默生产污染的地方）

`.env` 的 `BOT_RUNTIME_DATA_DIR` **直指生产根**，而 `tests/conftest.py` 的 G1 守卫**只快照源码树 `data/`**。于是任何「构造即 mkdir + connect + WAL」的 store（例：`ReplyPolicyStore`）在测试进程里会**直接打开生产库**。三件真身：

- `isolate_test_runtime_environment()`（`:231`）＝装配入口，conftest 模块级**赋值式**调用；注释 `:239-241` 记着「本仓已两次实测 `setdefault` 对已启动解释器无效」——写成 `setdefault` 生产值会原样活着。非 pytest 进程调用直接抛（`:250`，缝不得在生产进程里挪根）。
- `guard_test_runtime_root()`（`:203`）＝判定，两态：标记（`BOT_TEST_PROCESS`）缺席 ⇒ 原样放行（生产 bot 零行为变化）；标记在且落点命中生产根 ⇒ **缺省抛** `refuse`；只有显式 `BOT_TEST_RUNTIME_GUARD_MODE=redirect` 才挪进隔离根（`redirect` 只给在册只读对照用例）。不认识的模式值按 `refuse` 处理（fail-closed）。
- `RuntimeIsolationViolation`（`:46`）**故意继承 `BaseException` 而不是 `Exception`**——真身链路上 `ReplyPolicyStore.__post_init__` 与 `shared_reply_policy_store` 的解析段全裹 `except Exception`，用 Exception 族只会被降级成两声日志，形成「全树绿、库被写了、她的偏好静默失效」的静默绿形态。这是本仓判据设计的一条通用教训：**要保证某件事不能被兜底吞掉，就抛在兜底捕获的类之外**。
- 判据锁：`tests/test_datafix_runtime_paths.py`（下半部 A/B/C 三组）。

### 1.3 为什么源码树里出现 `data/` 或任何缓存就是事故（不是洁癖）

1. **正确性**：源码树里的 `data/` 意味着重映射没生效 ⇒ 生产读的那棵树和测试写的那棵树不是同一棵，数据看着「掉了」其实是落错了地方。根治判据＝`tests/test_datafix_runtime_paths.py`。
2. **门禁会真的炸**：`runtime-layout` 门检查源码树 `python_bytecode=absent` 等零缓存不变量；`__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache` 任意一枚出现即 FAIL。台账 #50★ 那次教训是「直跑 python 没带 `PYTHONDONTWRITEBYTECODE=1`，三席门禁复跑往 `plugins/**` 落了 **433 枚 `.pyc`**，`runtime-layout` 打成 FAIL，别人花一整窗清理」。
3. **本波实锤（新踩的坑，机制值得单独记）**：SEATS.md `:215` 在册——一枚 **空的、gitignored 的 `Bot_Character_Bots.egg-info/` 目录**落在源码树，让 **`importlib.metadata` 认领到一个没有 `Version` 的 distribution**，直接吃掉三枚 `test_error_report`。要点有二：① 失效面在**元数据发现层**，不在 import 层，报错长相与被测功能无关，极易误归因为「他席在飞改动」；② 它**永远不出现在 `git status`**——共享工作树里 `git status` 干净 **≠** 源码树干净。⇒ 判「这枚红是不是我造成的」时，除了 `git archive HEAD` 拉仓库外复跑（#68★ 正道），还要**单独扫 ignored 残留**（`git status --ignored` 或直接扫目录），别只看未忽略改动。
4. **唯一合法例外**：`plugins/bot_unified_runtime/domains/weather/assets/qx.json`（NMC 码表，`.gitignore` 有否定规则）。它被清理波误删过一次，直接导致天气整体塌向 open-meteo——**删除前必须看这条例外**。

### 1.4 Runtime 里的「覆盖册」= 会赢掉 `.env` 的那一层

运行时注册表文件（模型优先组 / 渠道表等）落在 Runtime，**覆盖优先级高于 `.env`**（见 §4）。这一层是本项目「叙述≠真身」最集中的地方：源码里的缺省值、`.env.example` 的字面值，都可能被 Runtime 里的覆盖册在运行时改写。**判断线上行为只能看 Runtime 现值 + 实跑输出，不能看源码缺省。**

---

## 2. 消息主链路逐段实名单（每段给 file:line 真身）

路径缩写：`PKG = plugins/bot_unified_runtime`。**下文所有行号是本波（2026-10-02）现算读数——行号会漂（台账 #50★），认函数名与注释锚点，别认行号。**

### 2.0 入口

`bot.py`（NoneBot 启动 + 崩溃守卫）→ driver：webhook `8080`，SnowLuma(NapCat) **forward-WS `3001`**；另有 Telegram / Mail / Console adapter。进程常呈**双层**（venv `python.exe bot.py` 父 → 基础解释器子进程实际监听 8080/连 3001），重启时两枚都要停；生产进程管理员权限启动。

### 2.1 摄取段（`PKG/__init__.py` —— 一万一以上行的巨型模块，别怕，只认这几处）

| 动作 | 真身 |
|---|---|
| 事件 → `IncomingMessage` | `_incoming_from_nonebot_event` **`:1370`** → 构造 `IncomingMessage(...)` **`:1592`** |
| 段归一 | `_extract_onebot_raw_segments` `:615`、`_onebot_segments_from_message_payload` `:551`、`_urls_from_message_segments` `:772`；存在性判定 `contains_visual_message_segments :728` / `contains_forward_message_segments :752` / `contains_audio_message_segments :760` |
| **引用链反查（5 层）** | `REPLY_CHAIN_MAX_DEPTH = 5` → `PKG/domains/chat_reply/ingest/message_context.py:116`；异步反查 `collect_reply_chain_async :411`、同步 `collect_reply_chain :486`、渲染 `format_reply_chain :592`；`_flatten` 另有 `depth > 5` 递归闸（**`message_context.py:21`**）——两层闸都在，缺一层就会顺着超长引用链打爆 |
| 合并转发消息展开 | `_forward_message_text`（async）`:1085` / `_forward_message_text_sync` `:967` / `_collect_nested_forward_ids` `:1047`；嵌套上限 `_FORWARD_NESTED_MAX_DEPTH = 3` `:952`、总量 `12` `:953`、API 超时 `10.0s` `:942` |
| 语音预转码 | `_transcode_record_segments` **`:1190`**，可转后缀表 `_RECORD_CONVERTIBLE_SUFFIXES` `:1187`（`.mp3 .wav .m4a .aac .flac .ogg .amr`） |
| TG `file_id` → 字节 | `PKG/domains/media/ingest/telegram_media.py`（`_segment_file_id :356`） |
| @ 判定三路 | `_detect_onebot_direct_mention :1174`（硬 mention）/ `_detect_text_at_mention :700`（文本 `@` + 软边界词表 `_AT_MENTION_SOFT_BOUNDARY :697`）/ `_mentioned_by_affinity_nickname :640`（好感度昵称，`_refresh_affinity_nicknames :665` 带节流载入戳 `_AFFINITY_NICKNAMES_LOADED_AT :655`） |
| **路由判定缓存（必读）** | `_cached_route_decision` **`:878`**，缓存在事件 state 键 `_bot_unified_route_decision` `:875`。原因写在 docstring `:888-891`：**一条消息会被十几个 `on_message` 规则依次检查**，每条规则都全量跑一遍路由太重；state 随事件回收，所以缓存自动失效。**改 matcher 面必须记得这个缓存的存在**（否则你会以为 matcher 只跑了一次）。 |
| 路由取文口径 | `_effective_route_text :862` |

### 2.2 路由段（`PKG/domains/chat_reply/runtime/base_router.py`）

🔴 **第一个「叙述≠真身」硬分歧**：AGENTS.md 写「路由 base_router」，而顶层 `PKG/runtime/` 里**没有** `base_router.py`（那里只有 `capability_protocols / content_route / db_backup / pipeline / pricing / settings`）。真身在 **`domains/chat_reply/runtime/base_router.py`**；`PKG/runtime/pipeline.py` 与 `content_route.py` 只是 `SHIM_ROWS` 在册垫片（见 §2.9）。连本机 onboarding 技能里写的 `from ...runtime.base_router import build_route_rules` 也是**过时路径**，照抄会 `ModuleNotFoundError`。

| 物件 | 真身 | 坑 |
|---|---|---|
| `RouteKind(str, Enum)` | `:140` | 成员清单**以 `capability_registry.py` 为准**，本文不抄（规则 10） |
| `RouteDecision` | `:181` | 字段是 `kind / capability_id / priority / reason / audit_tags`（+可选 `target_capability_id / normalized_text`）——**是 `capability_id` 不是 `capability`** |
| `RouteRule` | `:227` | `matcher: Callable[[str, Any, Any], RouteDecision | None]`，`None`＝不命中、继续下一规则 |
| `build_route_rules()` | `:258` | 🔴 **判定闭包在函数体内，不是模块级函数**——`base_router.tts_match` 会 `AttributeError`。测试里必须 `next(r for r in build_route_rules() if r.capability_id == "bot.xxx").matcher(文本, config, None)` |
| `build_interface_manifest()` | `:729` → `InterfaceEntry :209` | 审计元数据规则：**`active` 接口必须指向一个 `capabilities/echo.py` 的 help topic 或登记为内部功能；`reserved` 必须登记说明** |

**Keystone 单一声明源（这是本项目最重的一条结构纪律，`base_router.py:132-139` 自述）**：成员清单权威在 `domains/chat_reply/runtime/capability_registry.py` 的 `ROUTE_CAPABILITY_DECLARATIONS`（每能力一行 `kind/capability_id/priority/label/reason/tags/command/matcher/note`）；`base_router.py` 的枚举、`RouteRule` 注册表、接口清单、`INTERNAL_CAPABILITY_NOTES` 只是**字面投影**，服务对象是四个**离线静态解析器**（`scripts/doc_sync.py`、`scripts/command_catalog.py`、`tests/test_doc_sync_gates.py`、`scripts/extract_trigger_words.py`）——它们不做 import，只做字面解析。两向逐字段一致性由 `tests/test_capability_registry.py` 常驻锁定。⇒ **增删一个能力必须两处同步，且该测试里有一批硬编码计数要逐个 +1**。

**影子决策引擎**（`PKG/domains/core/decision/`：`engine dispatcher ingress outbound outbound_contracts outbound_registry shadow trace`）：迁移模式键 `bot_decision_engine_mode`，**默认 `legacy_only`＝引擎完全不参与、对外行为逐字节不变**（`shadow.py:34 LEGACY_MODE`）。`normalize_decision_mode :50` 对非法/未启用值**一律回落 `legacy_only`（fail-closed，仅告警一次）**；`resolve_decision_mode :66` 解析链＝nonebot driver config → 进程 env → 缺省。`engine_only` 阶段 0 **一律回落** `legacy_only`（`shadow.py:10`）。`decision/__init__.py:5,17` 用**函数内惰性导入**，保证 `legacy_only` 热路径不拉起 base_router/能力链。影子对照的三条硬禁（`pipeline.py:890` 注释）：**绝不发送、绝不改回执、绝不 claim 幂等**。

### 2.3 门禁段 `_prepare`（`domains/chat_reply/runtime/pipeline.py:1059`）——**顺序即判据**

实测顺序（每拦一次都 `stage="policy"` 审计 + `_record_receipt_safely`）：

1. `feature_gate` `:1065` —— 状态读取抛错时 **fail-closed**：`access = FeatureAccess(False, "feature_state_unavailable")` `:1069`
2. `runtime_enabled` `:1082`（「统一运行时已暂停。」）
3. 角色解析 `:1103-1106`：`message.model_copy(update={"sender_roles": self.role_settings.resolve_roles(message)})` —— **在门禁里改写 message**，角色来自 `policy/roles.py` 六级角色（超管叠加 admin）
4. `runtime_control.allows(capability_id)` `:1107`
5. `policy_evaluator` `:1128`（黑白名单 + 搭话好感门；文案「该场景下未启用主动回复。」）
6. `quiet_hours_checker` `:1151` —— **静默拦截**：`public_message=""` `:1159`（注释 `:1153-1154`：无人 @ 也回提示语＝无接触刷屏）
7. `decide_reply_budget` `:1179` → `max_messages` + `context_budget`
8. `rate_limiter.check_and_record` `:1192`（带 `interactive/proactive` 分池，判据 `:1184-1191`）——**同样静默** `:1199-1202`（2026-09-12 实弹反馈：把「已临时降频」发进群只会刷屏）；随后 `_schedule_rate_limit_redrive` `:1212`＝2026-09-25 用户裁定第 2 项「明确找 bot 却被『太密』拦下的，解禁那一刻补跑一次」，补不上维持静默
9. 🔴 **`_claim_event` 幂等 claim 必须排最后 `:1250`**——判据原文就写在 `:1243-1249`（审查 **A-18**）：旧序 `handle` 先 claim 再 `_prepare`，**被拦事件也消耗幂等键** ⇒ 同一条被拦消息的用户重发会被当 duplicate 吞掉、**永远得不到回复**；现在只有全门禁放行者才占键。claim 失败时**立刻回滚刚记的限流账** `:1251-1256`（`_rollback_rate_limit_record`），使重复投递与旧 claim-first 行为一致、不消耗任何额度；`:1248-1249` 特别注明 A-04 修复不受影响（限流器调用点与入参保持原样，R3 最小间隔在限流器内部先于 interactive 早退的次序不动）。⇒ **谁要是把 claim 提回门禁前面，就是复发 A-18**。幂等真身 `runtime/event_idempotency.py:187 / :265`（两实现），幂等键**段禁 `:`** ⇒ 走 `is_legal_segment`（台账 #46★）。
10. `BotDecision(...)` `:1258`（`mode="command"`、`SendPolicy.IMMEDIATE`、`persona_profile_id`、`audit_tags` 三级合并 `:1273-1277`）→ `_PreparedRuntime :1279`

### 2.4 能力正文下放（同文件）

`RuntimePipeline` **`:906`**；线程池 `_chat_pool :264` / `_get_chat_pool() :531`（`max_workers` 读数含 `driver_config.bot_pipeline_max_workers :281`）+ **`_BoundedSubmissionGate`**＝超载快败，产 `pipeline_busy` issue（该形态在群内通知方法里**豁免**，见 §2.5）。能力正文在 `PKG/domains/<域>/capabilities/*.py`。🔴 **阻塞调用（HTTP 等）必须经 offload 线程池，绝不能跑在事件循环线程上**；`RuntimePipeline` 跑在池里、返回 `CapabilityResult`、再过 Review。

### 2.5 `_complete`（`pipeline.py:1287`）——输出半程，顺序同样冻结

1. **同轮不连发两条**账（`:1294-1304`，2026-09-29 用户裁定需求项 6）：`post_ack_failure = 有 operational_issue 且不在 `kb_grounded_fallback` 且 `_take_ack_emitted(request_id)` 命中`——回执晚于阈值先落了一句、能力随后才失败时，**旧形态用户会收到「我在想」+「再发一次」两气泡**。🔴 **红线**：`:1298-1299`「**带接地内容的兜底不压**（kb_grounded_fallback 兜底里有真资料，吞掉它就是吞回复）」。
2. 群/频道失败：A-19 `:1309-1318` 正文压空 + `SILENT_AUDIT`（错误细节不回群、走管理员告警链），但**群聊不再零反馈**——节流窗内 `_maybe_submit_group_failure_notice :1313` 补一句池内降级文案。
3. `SILENT_AUDIT` 早退 `:1323-1344`（`ReceiptState.SKIPPED`）。
4. `review_capability_result(result, decision)` **`:1345`** → 未批准 `:1346` → `ReceiptState.BLOCKED, transport="reviewer" :1348-1351`。
5. 🔴 **TTS 钩子（配音出站）`outbound_voice_enricher` 在 `:1374-1375`**——**G-3（T54 规格 §4.2）冻结插入点**：review 批准后、render 前**恰调一次**；取文口径＝review 批准后的 body（M-10 三害根修）；失败挂 `OperationalIssue`（M-13 自动半）；钩子期挂 issue 在该分支**之后** ⇒ 不触发上面 A-19 压空正文，群内正文照发、降级文案仍归中央（R-16②，**本域不自拼**）。
6. `render_reviewed_output(result, review)` `:1377`（出图见 §5）。
7. **合并转发** `:1383-1407`：`content_type=="text"` 且〔（`capability_id != "bot.chat"` **且** `should_forward_by_node_count :1386`）**或** `should_forward_long_text :1393`〕→ `build_forward_output :1398`。判据原文 `:1379-1382`：切分后 **>3 条（即 ≥4）** 才合并；**`bot.chat` 整条直发**（实弹反馈：chat 四段话被切成四条又触发合并，整段被折叠成聊天记录）；转发内发送者名用 **bot 自己的名字**（调用方传入 `forward_sender_name`），**不再署用户昵称**。
8. 群 scope 缺 `group_id` → `BLOCKED :1408-1413`。
9. `self.send_queue.submit(send_request)` **`:1460`**（旁路推送另一处 `:1509`）→ `DeliveryReceipt`。🔴 `:948` 与 `:1829` 两条同族纪律：**投递必须走主动投递唯一中央出口，不在这里直调 `send_queue.submit`；未注入中央出口时一律不发——「回执不许绕闸直调」**（台账 #49★ 未执法的两项之一就是出站闸）。

### 2.6 SendQueue 真身（`PKG/domains/transport/sender/queue.py`）

`submit` 三处 `:266 / :289 / :579`。**part 级幂等 + UNKNOWN 确认 + PARTIAL 断点续发**是本链路最硬的一段：

- part 状态机 `PENDING/SENT/UNKNOWN/FAILED_FINAL` `:39-42`；`PARTIAL_ROW_STATE="partial"` `:38` 是**请求行终态**——注释 `:34` 写明「`contracts/` 本轮禁改，无法新增状态」，所以断点被建模成行终态而非新状态。
- `claim_due` 的补偿扫描续发 PARTIAL `:787-791`（`claimed_from_state` 取值受限）；重投退避 `_PARTIAL_RESUME_BACKOFF_SECONDS = 90.0` `:46`，**与 `bot_unavailable` 挂起的 90s 对齐**（慢速重探）。
- Q-G7 休眠 PARTIAL 永久停摆收口三件 `:105-115`，`_DORMANT_PARTIAL_SWEEP_SECONDS = 7*86400`。
- `mark_unknown` `:1685`：**结果未知（超时/断连/无法判定）记 UNKNOWN，绝不静默当失败盲重发**；`:1206` 与 `:1341` 同调——有已送达 part 就改置 PARTIAL 断点续发，**绝不整封盲重发已送达内容**。
- 运维视图 `:1620`（含休眠行，供人工确认排查）。

### 2.7 worker 排空 + 传输发送

- 周期 worker（`PKG/__init__.py`）：开关 `config.bot_send_queue_worker_enabled :1747` → `_send_queue_is_drainable :1628`（判据 `:1749` 不达标返回 `queue_not_drainable`）→ `_queue_worker_job :1755` → **`drain_send_queue_once :1779`** → 注册为周期任务 `id="bot_send_queue_worker" :1793`；节奏 `bot_send_queue_worker_interval_seconds :1752`、批量 `bot_send_queue_worker_batch_size :1753`（各自 `max(1, int(...))` 兜底）。
- `_deliver_transport_send_request` **`__init__.py:2772`**：内部构造 **`UnifiedDeliveryGateway :2789`**（`onebot_sender=send_onebot_v11`、`nonebot_sender=send_nonebot_message`、`record_receipt=_record`）→ `gateway.deliver(bot, event, send_request)` → `_register_bot_sent_video_assets`。`_find_sent_request :2276` 是各异步推送口回捞 `SendRequest` 的入口（订阅/提醒/媒体族调用点：`:2887 :3340 :3400`（默认 `deliver_fn`）`:4309 :5155`；`decision/outbound_registry.py:909` 把这条链写成了字面登记：`pipeline.handle_async → _find_sent_request → _deliver_transport_send_request`）。
- 媒体出段：`CapabilityResult` 已内置 `audio/images/files/video`，`renderer` → `{"type":"record"}` → `sender/onebot.py` 的 `_segment_from_mixed_part`，**原生打通、别造第二通路**。发媒体**必须把 `title`/`body` 留空**只填 `audio=[{"file":...}]`，否则 renderer 的 `body → summary → title` 兜底链会把标题当文案一起发出去（对照 `randpic` 口径）。
- 出站前文本闸：`domains/render/plain_text.py` 的 `redact_local_secrets`（盘符路径 / `BOT_XXX=` / `sk-` 形态打码）——**不认嵌词 `sk-`**（台账 #55★），别指望它兜住一切。

### 2.8 失败与兜底形态（链路级，别当细节）

私聊失败走**五池话术游标轮换**、群聊走降级池、告警带轨迹；统一错误报告卡是**两段式异步**（文本先行、卡图后补、fail-open），中央超时抛 `CapabilityTimeout`（**禁第二族**）逃逸进 pipeline `_internal_error` 旁路钩子 ⇒ 出卡，锁 `tests/test_pipeline_hard_timeout.py`（台账 #49★「不抛异常所以不出卡」销账仍有效）。

### 2.9 垫片地图（`PKG/domains/core/board_shim_ledger.py:22 SHIM_ROWS`）——**AGENTS 路径的一半是旧道**

`SHIM_ROWS` 每条 = `(垫片 path, 真身 path, 引用方数上限)`，字段顺序即契约。**这是本项目「叙述≠真身」最系统的一处**：AGENTS.md 与旧文档里写的顶层路径多数只是再导出垫片（PEP 562 `__getattr__` 活再导出，所以**在任一侧 monkeypatch 都一致**，但读代码要读真身）：

| AGENTS/旧道（垫片） | 真身 |
|---|---|
| `capabilities/chat.py` | `domains/chat_reply/capabilities/chat.py` |
| `character/providers.py` | `domains/chat_reply/character/providers.py` |
| `llm/model_router.py` | `domains/chat_reply/llm_engine/model_router.py` |
| `message_context.py` | `domains/chat_reply/ingest/message_context.py` |
| `output/plain_text.py` / `renderer.py` / `reviewer.py` / `roleplay.py` | `domains/render/` 同名 |
| `policy/__init__.py` | `domains/chat_reply/policy/__init__.py` |
| `runtime/content_route.py` / `runtime/pipeline.py` | `domains/chat_reply/runtime/` 同名 |
| `runtime/pricing.py` | `domains/chat_reply/llm_engine/pricing.py` |
| `sources/parsers/__init__.py` / `sources/registry.py` | `domains/link_parse/parsers/` · `domains/link_parse/support/registry.py` |
| `capabilities/content_parser.py` | `domains/link_parse/capabilities/content_parser.py` |

同文件 `:75-81` 还有四枚**单调下降棘轮基线**（`SHIM_RETIRE_BASELINE` / `RELOCATE_BASELINE` / `UNLANDED_SUM_BASELINE` / `OUTSIDE_BASELINE`，手写字面量「只准降」）。🔴 **退役一个垫片＝文件 + `SHIM_ROWS` 行 + 牵动的地板/链接/只读面登记「同批」动，只动一边必红另一边**（台账 #68★）。而 2026-09-28 那次主树还原把已退役垫片 `capabilities/auto_send/__init__.py` **连文件带账本行写回**（`:23-26` 注释在册）⇒ 「还原会把已退役的 tracked 件写回」是这条纪律的成因。

---

## 3. 能力清单（按域分组 · 计数一律指向真身，不手抄）

🔴 **计数与成员清单的唯一口径**（规则 10）：
- 机器册 `docs/auto-facts.md`（由 `scripts/doc_sync.py --write` 整册重生成，`--check` 漂移即红，常驻门在 `tests/test_cross_validation_gates.py`）——RouteKind 成员、帮助 topic 数、config `bot_*` 字段数、模板清单、哈希清单范围、**能力真身册在册枚数与维清单**都在这里现算。
- 命令面字面清单：`docs/command-catalog.md`（`scripts/command_catalog.py --write`）+ `COMMANDS.md`；触发词与逐参数真身＝`domains/chat_reply/capabilities/echo.py` 的 `_HELP_ENTRIES` / `_HELP_ENTRY_META`。
- **能力真身册（在册枚数/维清单的唯一声明源）＝`PKG/domains/core/capability_manifest.py`**（`scripts/doc_sync.py:38` 钉死；doc_sync 只用 AST 读它、**绝不 import 插件包**）。
- 路由矩阵：`docs/route-matrix.md`（手改，门 `test_route_matrix_rows_match_base_router` + `test_route_matrix_covers_every_route_kind`）。
- 代码地图：`docs/CODE-MAP.md`；板块投影页：`docs/boards/`（一功能一目录，清单看该目录自身）。

| 域（`PKG/domains/<域>/capabilities/`） | 能力载体文件 | 备注 / 红线 |
|---|---|---|
| `chat_reply` | `chat.py`（人格对话正文，巨型）· `echo.py`（帮助/命令目录真身）· `affinity.py` · `memory.py` · `group_info.py` · `poke.py` + `poke_routing.py` · `user_copy.py` | 分区注入 + 反注入包裹；称谓走 `AddressingContext`（性别不推断、用户偏好最优先）；好感度**算法说明一律定性、不展示固定加减数值**（用户裁定）；`echo.py` 动一下必过触发词双向门 + 哈希门（§7.4） |
| `finance` | `market.py` · `stocks.py` · `fx.py` | 东财 kline **必须带 `end` 参数**（#锁）；**非上市公司结构性无价格字段**，估值只准官方公告或注明口径的公开报道；北向**只报成交额/笔数**（净买入早已停止披露，绝不编数）；无源币种诚实标注 |
| `weather` | `weather.py`（数据层 `data/nmc_weather.py` + `data/open_meteo.py`） | NMC 主 + Open-Meteo 兜底；地名必须带码表有效 `stationid`（#9）；变体逐级拆行政区；`assets/qx.json` 是**源码树唯一合法资产例外** |
| `meme` | `meme.py` · `meme_library.py` · `randpic.py` · `randpic_timing.py` | 表情册四动作 + 贴纸联动（#72）：`store.media_container()`（`BOT_MEME_LIBRARY_DIR`）与贴纸池 `BOT_STICKER_DIR` **两键两片目录，混用＝入册永远 escape**；主动贴表情**只发群、私聊一律不派发**（QQ 侧本无该通道 #35★）；randpic 只读 `BOT_RANDPIC_DIRS`，不重复账＝原子占坑 |
| `media` | `media_archive.py` · `tts.py` · `image_search.py`（+ 同级 `voice_enricher.py`） | 归档＝SSRF + magic bytes + 限额 + 目录消毒，缺省 super_admin；TTS 钩子插入点冻结在 `_complete`（§2.5 步 5） |
| `schedule` | `reminder.py` · `schedule_board.py`（+ `store/reminders.py`、`llm_draft.py`、`timetable.py`） | 迟到/过期治理与 **UTC 混用老坑**（#29★） |
| `notes` | `notes.py`（`chat_reply/character/notes_store.py` + `runtime/timesync.py`） | 图片落盘走 SSRF 入口 + 落点双查；并列候选要问；NTP 被拦时回退系统钟**属预期** |
| `subscribe` | `subscribe.py` · `subscribe_v2.py` · `news.py` · `today_history.py` · `epic.py` | 紧急信息订阅面（#46）：**只认事件自带群号/本人号**；幂等键**段禁 `:`** ⇒ 走 `is_legal_segment` |
| `divination` | `divination.py` | 真身已合并（#47）：**禁第二份牌堆算法与第二颗 `DrawError`** |
| `music` | `music.py`（数据 `data/music_charts.py`） | 同名先问（#18） |
| `location` | `wiki.py` · `moegirl.py` | 维基概述/标签 |
| `files` | `download.py` · `file_exchange.py` · `group_files.py` | 出站文件走 `transport/sender/file_gateway.py`（Phase-1），**取字节前统一判定、禁第二通路** |
| `food` | `eat.py` | 吃啥 |
| `link_parse` | `content_parser.py`（+ `parsers/`、`support/registry.py`） | 引用/语音/转发/TG 媒体解析；YTB live consent、xhs:live degraded 属已知边界（#7） |
| `emergency_info` | `emergency_info.py`（+ `service/review.py`，其 `submit :146` 是急报入册口） | 紧急信息只认事件自带来源号（#46） |
| `ops` | `host_state.py` · `consent_admin.py`（+ `admin/debug.py`、`admin/runtime_admin.py`，后两枚在哈希册在册） | 运维告警：抑制窗 + 台账 TTL；人话化与出卡（#55） |
| `vision` | `modality_preprocessing.py` | VLM 开关真值见 #72/#58 |
| `assistant` / `creation` / `render` / `transport` / `core` | **无 `capabilities/` 目录**——正文在域内其他层（`creation/image/engine_provider.py` 的 `submit`、`core/*` 是基础设施：`board_shim_ledger`、`capability_manifest`、`safety_exec`、`decision`） | 别在 `core/` 里找"能力"，那里是地基 |

**每日通讯总结**不在这张表里：它挂在 `PKG/__init__.py` 的 `_register_digest_push_scheduler`，dedupe 按日期，非白名单零推送，会话键坑见 #33★。**校园自动转发**＝`capabilities/campus.py` + `sources/campus_store.py` + `__init__.py` 被动 matcher（`priority=8, block=False`）+ config 六键：🔴 **纯监听绝不向学校群发**，三重来源门任一空＝整链关闭（#33）。

### 3.1 「关着的、但必须一开即通」——这是本项目最重要的一类面

现算 `config.py` 缺省为 `False` 的功能开关（**线上是否已开＝以 `.env` 现值 + Runtime `runtime_settings.json` 为准，源码缺省不能当线上结论**，§1.4）：

`bot_control_plane_enabled :199`、`bot_event_idempotency_enabled :181`、`bot_memory_enabled :332`、`bot_history_enabled :378`、`bot_memory_bus_enabled :345`、`bot_affinity_v7_enabled :359`、`bot_embedding_enabled :276`、`bot_kb_wiki_enabled :294`、`bot_knowledge_service_enabled :326`、`bot_worldbook_enabled :324`、`bot_v21_service_wiring_enabled :322`、`bot_share_enabled :191`、`bot_shared_export_enabled :217`、`bot_gscore_enabled :220`、`bot_mail_bridge_enabled :237`、`bot_mail_auto_reply_enabled :238`、`bot_disconnect_notice_enabled :245`、`bot_dirty_guard_enabled :254`、`bot_diagnostics_enabled :383`。
另三族「默认关」不是布尔开关：**决策引擎**缺省 `legacy_only`（影子对照不接管）、**LLM 计费账本** M1 默认关、**LLM 记忆抽取**——注意 `bot_memory_extract_enabled` 源码缺省是 **`True`**（`config.py:337`）而台账 #47 记「默认关」⇒ **二者必有一处是旧账，动它前先现算线上读数，别按任一侧的字面改**。

规矩：**开关关着不等于链路可以烂掉**——这些面都要求「一开即通」，所以判据普遍写成「本波域净新增红 0」而**不许签「全绿」**（HEAD 基线自身有既存红，#72★）；三格现网哑面「在盘不在码」的成因就是缺省 False / 键未登记 / 数据为空（#72★）。

<!-- APPEND-HERE -->

---

## 一、两棵树：代码仓 vs `ChatBot_Runtime/`

**取证状态**：本节所引 `scripts/runtime_paths.py` / `scripts/runtime_layout_smoke.py` / `plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py` / `plugins/bot_unified_runtime/config.py` 四件 `git status --porcelain` **无输出＝盘上即 HEAD 态**（现算命令见本节末）。

### 1.1 分工（一句话一格）

| 树 | 内容 | 谁写 |
|---|---|---|
| 代码仓（本工作区） | 源码、文档、人格源 `personas/`、测试、`.env`（gitignored） | 人 / 席位 |
| `../ChatBot_Runtime/` | venv、**全部 SQLite**、FAISS/ANN 索引、cookie、日志、缓存、媒体、**运行期配置覆盖册** | **只有 bot 进程** |

判据：`scripts/runtime_paths.py:1-5`（模块 docstring 首三行）——"The source tree is the AI workspace; mutable databases, media and plugin state live in the sibling `ChatBot_Runtime` directory."

### 1.2 `data/` 重映射机制（真身 `scripts/runtime_paths.py:280-295`）

```
runtime_path(value)                                  # :280
  ├ 绝对路径 → Path(value).expanduser().resolve()     # :283-284 原样，不挪
  ├ 剥前导 "./"（while 循环，多条也剥）               # :288-289
  ├ normalized.lower() == "data"      → data_root     # :291-292
  ├ normalized.lower().startswith("data/") → (data_root / 余下).resolve()   # :293-294
  └ 其余相对路径 → (PROJECT_ROOT / path).resolve()    # :295  ← 仍留在源码树
```
- `data_root` 来自 `runtime_data_dir()`（`:276-277`）= `guard_test_runtime_root(_as_root(_effective_data_root_text()))`。
- 大小写不敏感（`.lower()`）：`./DATA/x` 与 `data/x` 得同一结果——这条**注释在 `:285-286` 明写"与 config.py 的路径解析器对齐"**，即**两把尺必须同语义**；改一侧不改另一侧会被 `tests/test_datafix_runtime_paths.py::test_config_resolver_covers_all_runtime_data_fields`（`:102`）咬。
- 🔑 **第三行兜底是坑**：不在 `data/` 前缀下的相对路径**解析进源码树**（`:295`）。所以源码树里冒出 `data/` 残留之外，还会有"本该在 Runtime 却落进仓库"的散件——`_SOURCE_TREE_FALLBACK: str = "data"`（`:43`）是**没配根时的缺省**，即"env/dotenv 全空 → 落源码树 `data/`"（`:189-200` `_effective_data_root_text`，`:200` 返回 `raw or _SOURCE_TREE_FALLBACK`）。

### 1.3 读序：env 优先，其次 dotenv 文件，最后源码树缺省

`_dotenv_value(key)` = `os.environ.get(key, _dotenv_file_value(key)).strip()`（`:96-98`）；`_dotenv_file_value`（`:74-75`）注释明确"**不看** `os.environ`"，只读盘上 `.env` → `.env.prod`（文件名册 `_DOTENV_FILENAMES`，`:42`）。环境变量键名本身即契约：`BOT_RUNTIME_DATA_DIR`（`:31`）。

### 1.4 测试进程隔离缝（新人必踩，两态语义）

`.env` 把 `BOT_RUNTIME_DATA_DIR` 指向**生产根**，而 `tests/conftest.py` 的 G1 守卫只快照源码树 `data/` ⇒ "构造即 mkdir + connect + WAL" 的件（`ReplyPolicyStore` 一类）会在测试进程里**直接打开生产库**（docstring `:7-11`）。

- `guard_test_runtime_root`（`:203-228`）三态：标记缺席→**原样放行**（生产零行为变化，`:213-214`）；标记在但未命中生产根→放行（`:216-217`）；命中生产根→缺省抛（`:222-228`）。
- 模式缺省 `refuse`＝**fail-closed**（`:37-40`）；`redirect` 是显式 opt-in 且只在在册只读对照用例里设（`:220-221`）；**不认识的模式读数一律按 refuse**（`:210`）。
- `isolate_test_runtime_environment`（`:231-273`）必须**赋值式**而不是 `setdefault`——`:239-240` 注："本仓已两次实测 `setdefault` 对已启动解释器无效"。非 pytest 进程直接抛（`:250-253`）＝缝不得在生产进程里挪根。
- 🔑 `RuntimeIsolationViolation(BaseException)`（`:46-53`）**故意住 BaseException 族**：真身链路 `ReplyPolicyStore.__post_init__` 与 `shared_reply_policy_store` 解析段全裹 `except Exception` ⇒ 用 Exception 只会被降级成两声日志＝"全树绿、库被写了、她的偏好静默失效"的静默绿形态。
- 复现 AGENTS 规则 8/台账口径的实证：`.env` 指向生产根 ⇒ **凡走 `/bot reply` 命令面的测试必须 monkeypatch `shared_reply_policy_store`**（conftest 只守源码树，见 AGENTS 台账 #66★）。

### 1.5 "源码树禁出现 `data/`"的执法门（两把，别只认一把）

| 门 | 真身 | 判什么 |
|---|---|---|
| pytest 门 | `tests/test_datafix_runtime_paths.py`（上半 `:71-185` 重映射语义 / 下半 `:267-526` 隔离缝 A/B/C 三组） | 路径解析与隔离缝**行为** |
| 布局门 | `scripts/runtime_layout_smoke.py`，经 `scripts/dev.ps1 -Task runtime-layout`（任务表 `scripts/chatbot-tasks.json:215-222`，`runner: external`） | 源码树里**实际存在**的生成态 |

布局门要点（现算行号）：`scan_generated_residue()`（`:212`）；`__pycache__` 判定（`:242`）；空目录 `_is_empty_dir`（`:170`）；**半具身 venv** `_looks_like_venv`（`:177`）；**distribution metadata**（即 `*.egg-info`，`:187`/`:203`）；`--basetemp` 子目录 `_basetemp_children`（`:208`）。
`:77` 注释＝"旧扫面只有 `rglob('*.pyc')` + `*.pyo` + `__pycache__`，对以下两类全盲"——这就是台账 #59 P9「runtime-layout 扫面扩四类」（入库笔 `2995b0a`）的落点：**四类＝`__pycache__`/pyc 之外 + 空目录 + `.venv` 骨架 + `*.egg-info`**。
🔴 `:26` 注：脚本自身曾把 `scripts/__pycache__` 记成红（裸跑路线必现，已实证）——写门时先排除自家产物。

实跑取证（本席执行，只读）：
```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <Runtime>/venv/Scripts/python.exe scripts/runtime_layout_smoke.py
```
**为什么绕开 dev.ps1 才是污染源**：dev.ps1 自己 pin 了 `PYTHONDONTWRITEBYTECODE=1` 与 `PYTHONPYCACHEPREFIX`（见 `docs/HANDOFF-FIXWAVE-20261002.md` 第六节 + `scripts/dev.ps1` 头部），裸跑 python 会往源码树撒 `__pycache__`，然后被布局门报红——**红是你自己造的，不是别人的洞**。

### 1.6 覆盖册为什么**赢过 `.env`**（新人最常踩的一条）

三层，逐层给真身：

1. **`.env` 只喂 pydantic `Config` 原件**（装配期快照，`plugins/bot_unified_runtime/config.py`，现算 2257 行；`bot_*` 字段数以机器册为准）。装配期冻结＝热改当轮不生效＝**台账 #3★**。
2. **覆盖册真身**＝`domains/chat_reply/runtime/settings.py`（现算 1829 行；顶层 `runtime/settings.py` 只是 18 行 PEP 562 再导出垫片，`__getattr__` 转发到 `_CANONICAL`，垫片头 1-6 行——**别在垫片上 monkeypatch**，要打在规范路径）。存储落点：`build_runtime_settings_store`（`:1802`）→ `getattr(config,"bot_runtime_settings_dir","data/settings")`（`:1816`）→ 经 §1.2 重映射进 **Runtime 根**；文件名形 `runtime_settings_{instance}.json`（`:1750`，glob 在 `:1784`）。
   - ⚠ SQLite backend 接入后**SQL 为唯一覆盖源，旧 JSON 幂等导入后不再回落**（模块 docstring `:3-5`）——读错源会误判"覆盖册是空的"。
   - ⚠ 读 `control_plane_config.sqlite3` 时**列名是 `value_json` 不是 `value`**（真身 `control_plane/config_store.py:184` 建表、`:212-213` 取数），读错会全判空（`docs/HANDOFF-FIXWAVE-20261002.md` 第三节已实锤一次）。
3. **合并层在根汇口**：`__init__.py:831 def _config_with_runtime_overrides(config, runtime_settings)`——每次求值时把覆盖值盖到 Config 上，所以**覆盖册读数 > Config 读数 > `.env` 盘上读数**。这就是"覆盖册赢 `.env`"的机制。

**为什么这条最坑**：`.env` 改了、bot 也重启了、行为照旧 ⇒ 十有八九是覆盖册里有一枚**同键旧覆盖**在压着。反查＝`/bot runtime` 看热改态（实现即 `settings.py` 的 SETTABLE 名册 + `capabilities/echo.py` 帮助面 `:965`/`:1024`）。

**白名单与死开关治理（审查 C-09）**——这是本项目特有的一条硬规矩：
- `SETTABLE_KEYS: dict[str, Callable[[str],Any]]`（`:1026`）＝可热改白名单；`set` 不在册的键直接拒（`:1510-1513`，并把可用键名打出来）。
- `RESTART_REQUIRED_KEYS: dict[str,str]`（`:358`）＝装配期冻结键，`set` **明确拒绝并提示"改 .env + 重启"**（docstring `:6-8`），绝不允许"写入成功但行为不变"的死开关骗人（`:1504-1507` 抛出处）。
- 🔑 `:343` 与 `:356` 记录了换代过程：**28 个"写成功但行为不变"的残项从 SETTABLE 移入 RESTART**，判据＝"合并层 `_config_with_runtime_overrides` 对该键覆盖零传播"。逐键的**机制**理由写在册内注释里（例：`:901`"未过 `_config_with_runtime_overrides` ⇒ store 覆盖不可达，改 .env 需重启"；`:528`/`:531` 检索供应商链由装配期 config 构建；`:563` 起一批 `bot.tts` 键读装配期 config）。`:972` 定口径："档位取向＝一律 RESTART，逐枚给出不可热改的**机制**理由，不做「看着能热改」的猜测"。
- 反面：`:1014-1015` 说明哪两枚键**能**进 SETTABLE——"它们有合并层实时读点：`capabilities/chat.py` 每消息经 `runtime_settings.get_or(...)` 现读"。
- 🔴 台账 #56★ 的坑就在这一跳：**`get_or` 不读 Config**。所以"每消息 `get_or` 现读"只覆盖那两枚键，别把它当成通用热改通路。

### 1.7 本节取证命令（可复跑）
```
cd <仓库> && git status --porcelain scripts/runtime_paths.py scripts/runtime_layout_smoke.py \
  plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py plugins/bot_unified_runtime/config.py
# 本席实跑输出：空（四件全干净＝盘上即 HEAD）
wc -l scripts/runtime_paths.py plugins/bot_unified_runtime/config.py \
  plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py
# 本席实跑：295 / 2257 / 1829
``` 产出（原写于 gitignore 的 `.superpowers/sdd/2026-10-02-fixwave/HB---EVIDENCE.md`，该目录不受版本控制；本文件是**入库副本**，防下一次整树还原再吃掉一次）。
> 该席最终被**当日额度墙**打断（43-54 次调用即断，非 150 顶死法），末节可能不完整；引用前请按文中命令现算复核。
