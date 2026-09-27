# 代码质量与结构审计发现台账（2026-09-21）

> **计数口径（AGENTS 第一部分规则 10）**：本册「审计范围与方法」段与各级标题里的「N 条 / N 组」是
> **发现当时的时点值**；现役开口项数以本册现算（逐条 P0 / P1 / P2 编号标题，合并原始与追加块）为准。原数字与处置结论一律保留，不改写、不删。

Status: STARTED

> 只读审计产物。判据 = `docs/boards/_conventions.md`。分级 P0/P1/P2 见其第六节。
> 本文件由审计席逐域 append；主会话是唯一修动者。

## 骨架

- [ ] 板块索引与命名（B01..B10）
- [ ] 一、一功能一目录 / 孤儿件
- [ ] 二、第二真身（符号重名/近名）
- [ ] 三、绕过中央件（出站 / 会话键 / 文本边界 / 配置读取）
- [ ] 四、命名规范违规清单
- [ ] 五、docstring 缺计（按文件聚合）
- [ ] 六、清爽度硬伤（吞异常 / 巨型函数 / pass 空壳 / 死代码 / 假导出 / 无锁全局）
- [ ] 七、门禁假绿风险 + xfail/skip 挂账清单
- [ ] 八、重复文档（代码侧相关口径）
- [ ] 九、未覆盖清单
- [ ] 表①按板块 P0/P1/P2 计数
- [ ] 表②建议本波立即自动处理
- [x] 表③须先由用户裁定

---

# 审计范围与方法（可复跑）

只读扫描：`plugins/bot_unified_runtime/` 全树 `.py` 总数与非垫片真身数均以本次扫描现算为准
（判据=文件头首部窗口内不含 `Compat shim|re-export|兼容再导出|再导出`）；AST 扫
公开符号碰撞（48 组同名异构＝当时 AST 普查时点值，现数须重跑该普查，本册不复算）、模块级可变全局、吞异常、缺 docstring；`tests/`
AST 扫 xfail/skip 装饰器与存在性门比率；`scripts/runtime_layout_smoke.py` 逐条读
以确认「放置规范有无执法」。未跑 dev.ps1 全量、未改任何已存在文件。

# 第一部分：P0（立即修，三条）

## P0-1 主动推送全线绕过出站统一打码咽喉（B08）

- **级别**：P0
- **位置**：`plugins/bot_unified_runtime/domains/transport/sender/worker.py:_send_media_text_fallback_once`
  与同文件出站取文本处（`chunks = [content.text_fallback]`）；生产方
  `plugins/bot_unified_runtime/__init__.py:_push_daily_group_digests`、
  `:__deliver_due_reminders`、`:_push_daily_assist_private`、
  `:_deliver_cookie_expiry_report_via_queue`、
  `domains/schedule/delivery.py:_deliver_one`、
  `domains/emergency_info/service/push.py:deliver_emergency`、
  `domains/ops/monitor/error_report.py:_submit_error_request`
- **现象**：`review_capability_result` 全仓唯一调用点是
  `domains/chat_reply/runtime/pipeline.py:RuntimePipeline._complete`（实测：
  grep 只命中 pipeline 一处生产调用 + 两个测试）；`redact_local_secrets` 在
  `domains/transport/` 整层只出现在 `sender/nonebot.py` 的**异常文本**上，
  worker 对 `content.text_fallback` 逐字发出。于是 21:30 群摘要（LLM 生成）、
  提醒正文、收件箱早报、cookie 报告、错误卡人话区、紧急信息正文**全部不经
  review、不经打码**直接出站。AGENTS 铁律 3 与规范 §五「统一产出
  review → renderer → send_queue → sender」在主动推送面上不成立。
- **根因**：主链路的 review/renderer 两段挂在 pipeline 上，调度器族与域内
  producer 自己拼 `SendRequest(RenderedOutput(text_fallback=...))`，没有第二道
  统一咽喉；规范只写了「出站前打码」，没把它钉成不可绕过的落点。
- **最小修法**：把 `redact_local_secrets` 下沉为**出站唯一咽喉**——在
  `domains/transport/sender/worker.py` 组装外发文本处（含 `text_fallback`
  与降级文本两条路径）统一过一遍；producer 侧不动、根 `__init__.py` 不动。
  同时在 `domains/core/contracts/` 的出站契约上写明「worker 是最后一道脱敏点」。
- **能杀行为的验收判据**：拟建·尚不存在（2026-09-21 审计时点计划新增，至今未落地；相邻 `tests/test_campus_digest.py`/`tests/test_error_report.py` 只覆盖各自出站面，非本条咽喉验收）`tests/test_outbound_redaction_choke.py`——
  造一条 `text_fallback` 含一个伪造本机绝对路径与 `BOT_OPENAI_API_KEY=sk-abc`
  的 SendRequest，走 `queue.submit` + worker 真实出站桩，断言落到 adapter 的
  文本里两者均被打码；变异注毒：把咽喉点替换为 `lambda s: s` → 该用例必红。
  现有 `test_reviewer_media_visibility.py` 只测 pipeline 面，杀不到这条。
- **涉集中面**：否（worker.py / sender 层，不碰 config、生成物、根 `__init__.py`）→ 可并行。

## P0-2 中央出站闸默认关 + 六个绕过点：安静时间与每主体限流形同虚设（B08/B07）

- **级别**：P0
- **位置**：`domains/transport/sender/outbound_gate.py:submit_active_push`（唯一中央入口）、
  `config.py:Config.bot_outbound_gate_enabled`（缺省 `False`）、
  绕过点同 P0-1 的六个 producer（`__init__.py` 四处 + `domains/schedule/delivery.py:_deliver_one`
  + `domains/ops/monitor/error_report.py:_submit_error_request`）
- **现象**：`submit_active_push` 的读点实测只有
  `domains/emergency_info/service/push.py` 一处（+ `outbound_gate.py` 自身），
  其余主动投递全走裸 `send_queue.submit` ⇒ 跳过安静时间顺延、每主体 60s/小时
  窗限流、`dedupe_family` 键形校验与闸审计；且该族七键在
  `domains/chat_reply/runtime/settings.py` 的 `MOVED_TO_RESTART_KEYS` 里自述
  「合并层未登记，覆盖不可达」⇒ 即使想热翻也翻不动，缺省又是关。
- **根因**：闸是 B4-spec 后到的中央件，收编波（#45/#46）只把**紧急信息**一个域
  接进去并立了 AST 门（根文件禁 `submit_active_push` 字样，判据反了——禁的是
  字样而不是要求调用）；缺省值按「保守不上线」留 False，与规范 §七.6
  「不得私自把放开改回关闭」的口径相反。
- **最小修法**：①六个 producer 改 `submit_active_push(send_queue, request, gate, dedupe_family=...)`，
  `gate` 经 `domains/chat_reply/runtime/service_wiring.py` 注入（`__init__.py` 的四处由主会话串行改）；
  ②`build_outbound_gate_settings` 的读点登记进 `_RUNTIME_HOT_OVERRIDE_FIELDS`
  （或维持重启口径、把注释里的「可热改」措辞按 #47 先例改口）；
  ③缺省值 `False→True` **不在本波做**，进表③交用户裁。
- **能杀行为的验收判据**：扩展 `tests/test_outbound_gate.py`：参数化六个 producer，
  在安静时间窗内跑一轮，断言回执为 DEFERRED（`deliver_after` 指向窗口结束）且
  `send_requests` 表里不出现窗口内的发送记录；同一主体连投到越出每主体限流阈值（阈值以 `outbound_gate.py` 真身为准）时，断言越界那条被记 SKIPPED。
  变异注毒：把任一 producer 改回 `send_queue.submit(request)` ⇒ 该 producer 用例红
  （当前门杀不到，因为根文件的锁只查字样）。
- **涉集中面**：是（根 `__init__.py`、`config.py` 缺省值、`settings.py` 白名单）→ 主会话串行。

## P0-3 反注入防线两处已知绕过被 xfail(strict) 长期钉住（B03）

- **级别**：P0
- **位置**：`domains/chat_reply/security/injection.py:_RULES` 与转义路径；
  挂账在 `tests/test_prompt_injection.py::test_quote_chain_marker_alone_should_not_pass_unescaped`、
  `::test_trusted_marker_with_hierarchy_suffix_should_be_detected`（均 `xfail(strict=True)`）
- **现象**：引用链标记单独出现不触发包裹/转义（只在「包裹路径」生效）；可信标记
  加「层级N」后缀即绕过 `internal_marker_spoofing` 规则。两条都以 xfail 形式
  常驻全绿套件 ⇒ 门禁绿灯掩盖人格篡改防线缺口，属规范 §六「存在性/挂账糊过活性判据」
  与 §七「不许留以后再说式空壳」双重违反。
- **根因**：规则表按「已知伪装形态」枚举而非「任何带可信标记的文本一律转义」，
  收口波判定改造成本大 ⇒ 以 xfail 记账后无人接。
- **最小修法**：injection 侧改判定顺序——先无条件检测 marker 字样（含后缀变体），
  命中即转义 + 剥指令；把两条 xfail 摘牌转正；词形白名单（如正常引用）用显式表
  而不是靠漏检。
- **能杀行为的验收判据**：两条用例转 `assert`（去 xfail）即绿；新增第三例
  「标记 + 任意后缀（层级3/L3/level-9）」同样被拦；变异注毒：撤掉后缀归一 →
  两用例红。
- **涉集中面**：否。

# 第二部分：P1（本波内修 + 各落一条锁，十二条）

## P1-1 根 `__init__.py` 与 `_register_nonebot_handlers` 单函数体量超标（B02）

- **现象**：装配层上帝文件，所有域的 matcher、调度器、旁路（错误卡、校园、摘要、
  称谓）集中一处；函数级超出 `> 行数上限` 有三处（`_register_nonebot_handlers` 5390、
  `_incoming_from_nonebot_event` 229、`_register_emergency_info_scheduler` 205）。
  并且被**行号棘轮**锁死：`test_outbound_registry_campus_coordinate_is_live` 现为全量
  唯一红（登记 5027 ≠ 活体 5032），任何人改根文件都会撞红。
- **根因**：NoneBot matcher 必须在插件顶层注册 + 历次波次为「不顶漂坐标」刻意用
  纯插入写法（#47 第⑩项、U17 均如此声明），把行号当契约。
- **最小修法**：分域外迁到 `domains/<域>/service/wiring.py`（每域一个
  `register_x(matcherRegistrar, deps)`），根文件只留一张调用表（≤ 行数上限，上限以规范 §七.1 为准）；
  坐标锁改为「符号存在 + 注册语义」（用 `HandlerRegistry` 快照比 priority/谓词），
  禁行号断言。
- **验收判据**：新门 `tests/test_root_wiring_placement`（拟建） 断言根 `__init__.py`
  无 `@app.on_message`/`get_matcher()` 直调且行数 < 800；并把现有坐标棘轮注毒验证
  「把某 matcher 定义挪到同文件另一位置 ⇒ 不该红」（当前必红 = 锁的是行号）。
- **涉集中面**：是（根 `__init__.py`、`tests/test_outbound_*`、campus 坐标棘轮）→ 串行，
  且必须先于任何其它改根文件的条目。

## P1-2 `extract_http_urls` 两份实现，路由与解析各信一份（B01/B05）

- **现象**：`domains/chat_reply/runtime/base_router.py:extract_http_urls`（配 `_URL_RE`）
  与 `domains/link_parse/parsers/__init__.py:extract_http_urls`（配 `_HTTP_URL_RE`）
  AST 近似等长（1692/1691）且互不 import，注释自认「实现与 parsers 注册表一致，
  避免循环依赖」。今天两枚正则等价，**没有任何门**保证下次只改一侧。
- **根因**：怕循环依赖 ⇒ 复制而不是提到 core。
- **最小修法**：唯一实现落 `domains/core/text_boundary.py`（或新
  `domains/core/urls`（拟建）），两处改再导出；`_URL_RE`/`_HTTP_URL_RE` 合一。
- **验收判据**：`test_route_priority_disambiguation.py` 家族加一条：同一句含
  「（https://x.a/b）」的样本，断言 `base_router` 判为链接解析路由 **且** parsers
  侧 `extract_http_urls` 返回同一条 URL；注毒：任一侧加排除字符集 → 该锁红。
  另加 AST 门：全仓 `def extract_http_urls` 命中数 == 1。
- **涉集中面**：否。

## P1-3 计费/账单两套同名异构真身，且生产零消费者（B04）

- **现象**：`domains/chat_reply/llm_engine/usage_service.py`（体量超标）自带
  `ChargeLine / Settlement / PriceRevision / UsageQuote / UsageAttempt / money_str /
  normalize_channel / resolve_price / quote_usage`，与同目录 `billing_entities.py` +
  `billing_pricing.py` + `billing_service.py` + `pricing.py` 共 5 件、同名但 AST 不等价
  （`quote_usage` 27441 vs 40859）；两者互不 import，各有测试
  （`test_billing_service_v21.py` / `tests/test_usage_billing_v2`（拟建）→ 实为 `test_usage_billing_v21.py`），
  且**包外零 import 消费者**（全仓 grep 仅命中彼此、注释、两个测试）。生产账单真身
  是 `domains/chat_reply/llm_engine/ledger.py`。
- **根因**：V2.1 计费 M1 规格由两波各自实现，未接线也未删；`creation/_common/contracts.py`
  注释里把 `domains/chat_reply/llm_engine/billing_entities.py` 写成「计费权威实现」→ 文档与代码互相指认。
- **最小修法**：定 `billing_*` 为唯一真身，`usage_service` 复用其 DTO（删除重复定义）；
  若 M1 仍未上线，则整族在板块卡上诚实标 `reserved` + 零消费者，并把 5 件并成
  `entities/pricing/service` 3 件。
- **验收判据**：新门 `tests/test_llm_billing_symbol_uniqueness`（拟建）（AST 扫
  `domains/chat_reply/llm_engine/` 与 `domains/creation/*/contracts.py` 顶层同名
  class/function 命中数 == 1）；注毒：把任一 DTO 复制进另一文件 → 红。
- **涉集中面**：否（不碰 config/生成物）。

## P1-4 事件存储两套真身，异常各一颗（B09）

- **现象**：`control_plane/events.py:RuntimeEventBus`（体量超标，自开 sqlite、
  `CursorExpired`/`EventStoreUnavailable`、`DETAIL_KEYS`/`EVENT_SOURCES`）与
  `domains/ops/monitor/event_store.py`（同名异常、另一库、由
  `domains/ops/monitor/event_service.py` 独用），零交叉 import。B09 板块只该有一块
  事件账，现在 SSE 与 WebUI 各读一处。
- **根因**：控制面（B4-spec）与 ops 域分别落地同一职责。
- **最小修法**：`control_plane/events.py` 降为 `ops/monitor` 的再导出 + 薄 SSE 适配，
  异常只留一颗；两库合一（`bot_control_plane_events_db` 与 ops 事件库择一）。
- **验收判据**：端到端锁——写一条事件后，`/api/v1/events` SSE 与 WebUI 统计页读到
  **同一条 id**；AST 唯一性门同 P1-3。注毒：让 events 适配器回自库 → 端到端红。
- **涉集中面**：部分（若合并库路径要动 `config.py` 的 `bot_control_plane_events_db`）→ 串行。

## P1-5 会话键第三形态，且 `session_id` 是有行为的列（B01/B08）

- **现象**：`domains/core/session_keys.py` 是唯一构造口（`build_session_key` 产
  `group_<gid>_<uid>`），但 `__init__.py:_push_daily_group_digests` 与
  `:_register_today_history_scheduler` 写 `session_id=f"group:{group_id}"`；
  `domains/meme/reactions/engine.py` 自写「镜像 OneBot get_session_id」的第二构造器；
  `control_plane/webui_stats.py` 与 `webui_memory_graph.py` 各自用 `startswith("group_")`
  /`f"group:{gid}"` 解析。这不是装饰字段：`domains/transport/sender/queue.py` 的
  claim 语句用 `NOT EXISTS(in_flight.session_id = send_requests.session_id)` 做
  **同会话串行** ⇒ 三种形态 ⇒ 同群的推送与聊天回复不会被串行，顺序倒挂与并发连发
  都失去保证。
- **根因**：入站会话键收口了（#29⑤），出站 `SendRequest.session_id` 从没进同一口径。
- **最小修法**：`session_keys.py` 增 `outbound_session_key(scope, target_id)` 唯一构造器，
  六处 producer/engine/webui 解析全改走 `parse_session_key`；AST 门禁 `f"group:`
  字面量（白名单只准 session_keys.py）。
- **验收判据**：新锁 `test_queue_serializes_same_session`：同群两条在飞 ⇒ 第二条不得被
  claim（构造两种 key 形态时现状会「两条同时在飞」= 该锁红）；注毒：把构造器换回
  字面量 → 红。
- **涉集中面**：是（根 `__init__.py` 两处）→ 串行；queue.py/engine.py 侧可并行。

## P1-6 结构规范三条硬门无执法（B10）

- **现象**：`scripts/runtime_layout_smoke.py` 的检查项全在 runtime 数据/资产/
  字节码面，**没有一条**管代码落点。实测漂移：真身落在旧根层
  `domains/core/search/acg_search.py`（体量超标）、`domains/core/search/search_intent.py`（体量超标）；
  域根裸 `.py`（`domains/render/reviewer.py`、`domains/schedule/delivery.py`、`domains/media/digest.py` 等）；
  未在规范 §一.2 登记的层名（数量以门现算为准）（`pipeline` `llm_engine` `api` `projection`
  `adapters` `fetchers` `support` `parsers` `poi` `knowledge` `image` `tts`
  `campus` `daily` `auto_send` `timesync` `mail` `artifacts` `assets`
  `integrations` `reactions`）。
- **根因**：规范 §一 与开发约束 §三.1 写的是「硬门不是倡议」，但落盘时只建了
  文档投影门（board_doc_sync / 路由 / 帮助 / 配置四族）。
- **最小修法**：新增 `tests/test_code_layout_gate`（拟建） 三条断言：①旧根目录
  （capabilities/character/sources/policy/security/sender/output/llm/decision/audit/
  contracts/runtime）除 `__init__` 与白名单外只准是垫片；②`domains/<域>/<文件>.py`
  必须带层目录（白名单：`domains/core` 三件唯一口径 + 各域 `contracts.py`）；
  ③层名集合与 `_conventions.md` §一.2 双向一致（多一个就红，逼着登记或改结构）。
- **验收判据**：门上线首跑即红 ⇒ 按现况写白名单（把真身、裸文件、层名
  显式记账为存量、只减不增）；注毒：在 `domains/finance/` 根新建 `.py` 或在旧根
  写一个新真身 → 该门红。
- **涉集中面**：否（新增测试件 + 规范文档一行）。

## P1-7 B08 出站四段的真身裸在域根，且被跨模块调私有函数（B08/B03）

- **现象**：`domains/render/` 根层裸放 `reviewer.py renderer.py plain_text.py roleplay.py
  templates.py bot_avatar.py render_backends.py`（规范 §一.2 要求 `<域>/<层>/<文件>`）；
  `domains/chat_reply/capabilities/chat.py` 直接
  `from ...output.reviewer import _unsafe_output_reasons` —— 跨模块调用下划线私有件，
  违反规范 §二「私有函数只在同文件内使用」，且走的是旧根再导出路径 `output/`
  而不是真身 `domains/render/reviewer`。
- **根因**：review 层从 pipeline 抽出时只搬文件、没定层目录与公开面。
- **最小修法**：`domains/render/` 下按 `review/ render/ text/` 分层（或把这七个名字
  登记进 §一.2 层名白名单并给一句理由）；reviewer 暴露
  `unsafe_output_reasons()` 公开谓词，chat.py 改走公开面 + 真身路径。
- **验收判据**：AST 门「跨模块 `_x` 调用 = 0」（当前至少 1 处，注毒再加一处即红）+
  路径门「生产 import 不得指 `plugins.bot_unified_runtime.output.*` 旧路径」。
- **涉集中面**：否。

## P1-8 KB 检索门是纯存在性锁（假绿，B04）

- **现象**：`tests/test_kb_wiki_retriever_wiring.py` 三条用例合计无行为断言——
  只查 `providers.py` 文本里有没有 kb_wiki 字样、模块符号 callable、导入路径可解析。
  同一链路真身 `domains/chat_reply/character/vector_knowledge.py`（体量超标）含多处
  静默 `except: pass`（含 `_fsync_path` 吞 OSError 而 docstring 承诺「掉电也要留在
  盘上」、`PRAGMA journal_mode=WAL` 失败静默）。⇒ 「检索已接线」的绿灯完全可能对应
  线上零召回。
- **根因**：接线波以「可达性」代「活性」验收（#46 已为此踩过一次同类 Critical）。
- **最小修法**：补端到端活性锁：tmp_path 建库 → 写两条嵌入 → 一条查询 → 断言
  provider 返回的 context 文本含该事实；`_fsync_path`/WAL 失败改为一次
  `logger.warning`（规范 §七.2 要求记原始异常文本或注释理由）。
- **验收判据**：注毒 provider 返回空串 / 把 embed 调用换成 no-op ⇒ 新锁必须红
  （现门不会红）；`_fsync_path` 吞异常处加 caplog 断言。
- **涉集中面**：否。

## P1-9 链接解析三处平台逻辑各两份实现（B05）

- **现象**：`build_wbi_signed_url` 在 `platforms_bilibili.py`(2598) 与 `domains/link_parse/parsers/wbi.py`(1654)
  各一份且不等价；`build_request_headers` 在 `domains/link_parse/parsers/context.py`(1264) 与
  `domains/link_parse/parsers/http_util.py`(2478) 各一份（两者互 import，即 WP1 凭证咽喉与旧 headers
  并存）；若干 `parse_<平台>`（kurobbs/miyoushe/skland/xiaoheihe/mihuashi/huajia）在
  `platforms_generic.py` 与专属平台文件同名并存。
- **根因**：专属解析器逐批改、generic 兜底未回收；WP1 的
  `scrub_credentials_for_target` 落在 http_util 但旧 context 侧未退役。
- **最小修法**：wbi 单真身（generic/bilibili 改调用）；`context.build_request_headers`
  降为再导出并让 `credentials_allowed_for_target` 成为唯一判据；generic 侧若干
  同名函数改名 `_*_fallback` 或按现有分发删除。
- **验收判据**：parsers 回归族（`test_parsers_batch_a/a2` + WP1 凭证门）+ 新 AST
  唯一性门（同名 `build_*`/`parse_*` 顶层命中数 == 1，`parse_*_fallback` 白名单）；
  注毒：删 wbi 真身的 UA 头 ⇒ 打到 bilibili 的那条用例转红（当前若走的是第二份则不会红 =
  正证哪份活着）。
- **涉集中面**：否。

## P1-10 中央调度信封与业务 handler 混写一处（WP8 Wave 1–4 挂账，B02）

- **现象**：`plugins/bot_unified_runtime/runtime/capability_protocols.py` 体量超标，同时承载契约
  （`InvocationResult/CapabilityRequest/枚举`）、三颗注册表、共享线程池全局
  `_EXECUTOR`，以及 media/link_parse/search 各域的**具体 handler**
  （`_handle_media_vision_image`、`_handle_media_ocr`、`_handle_media_anime_ip`、
  `_make_asr_handler`、`_handle_media_video_recognize`、`_handle_media_video_subtitle`）。
  这正是用户所说「所有东西全混在一起」的最痛点。handler 本身是转调域真身
  （非第二真身），但落点错位。
- **根因**：#47 WP8 只做了 Wave 0（两个 `CapabilityResult` 分层归并），Wave 1–4 挂账。
- **最小修法**：契约 → `domains/core/contracts/dispatch`（拟建）；注册表+invoker →
  `domains/core/dispatch/`；各 `_handle_*` 迁回所属域 `capabilities/`，中央件只按
  descriptor 查表。旧路径 `plugins/bot_unified_runtime/runtime/capability_protocols.py` 留垫片。
- **验收判据**：`tests/test_capability_result_unique.py` 扩为「dispatch 契约件内
  零域专属 handler 符号」AST 门；新文件行数超限须注释理由（阈值以规范 §七.1 为准）；
  注毒：在中央件里再加一个 `_handle_xxx` → 门红。
- **涉集中面**：部分（Wave 1–4 属用户已挂账的裁定波）。

## P1-11 import 期跨文件改写同一个全局 dict + 墓碑常量（B06/B07）

- **现象**：`domains/subscribe/adapters/{bilibili_adapter,social_v2,xiaohongshu_adapter,music_v2}.py`
  四个模块在 import 期各自 `ADAPTERS[...] = ...`，注册表分散、依赖 import 顺序、
  无锁；`domains/subscribe/adapters/music_v2.py` 还留 `_REMOVED_PLATFORM_LABELS`（规范 §七.5
  「删除即删除，不留 `# removed` 注释 / 假导出」）。
- **根因**：adapter 逐平台加装，没有装配期注册口。
- **最小修法**：`ADAPTERS` 改为 `domains/subscribe/registry.py` 内
  `build_adapter_registry()` 显式列举；四文件只导出类；`_REMOVED_PLATFORM_LABELS`
  删除并在板块卡记录该平台已下线。
- **验收判据**：门断言「只 import registry（不 import 任何 adapter 模块）时
  `ADAPTERS` 仍完整」——现状红，改后绿；注毒：从列举里删一个 → 红。
  新门 `test_no_tombstone_literals`：`_REMOVED_|# removed|_unused` 全树命中 == 0。
- **涉集中面**：否。

## P1-12 运行期无锁可变模块级缓存（线程池 offload 竞态，B05/B04/B07）

- **现象**：pipeline 走 offload 线程池（`_EXECUTOR` 并发 4+），而下列
  **运行期被写入**的模块级容器同文件内没有任何 Lock：
  `domains/finance/data/stock_data.py:_HISTORY_CACHE`、
  `domains/schedule/capabilities/reminder.py:_RECENT_BODIES/_CHECKOFF_PENDING`、
  `domains/assistant/daily/capabilities/daily_assist.py:_QUERY_BODIES`、
  `domains/link_parse/parsers/__init__.py` 的规则/URL 进程级缓存（文件内自述
  「缓存为进程级」）、`domains/chat_reply/security/content_safety.py:_BOUNDARY_FALLBACKS`、
  `domains/chat_reply/runtime/natural_language.py:_WEATHER_CITY_BLACKLIST`。
  违反规范 §七.3「跨线程共享必须显式锁或不可变快照」。
- **根因**：性能波（Phase 1/2）就地加缓存，未统一缓存件。
- **最小修法**：读多写少者改 `functools.lru_cache`/`MappingProxyType` 不可变快照；
  确需可变异步写者包一层（拟建·尚不存在，2026-09-21 审计时点：全树无 `caches.py`/`TtlCache`）`domains/core/caches.py:TtlCache`（内部持锁）。
- **验收判据**：并发锁测试（多线程 × 多次读写同 key：无异常、无半条记录、
  `len(cache)` 单调）；注毒：去掉锁改裸 dict ⇒ flaky 必现红；AST 门禁止
  模块级 `NAME = {}` 被同文件函数写入且文件内无 `Lock()`（存量白名单只减不增）。
- **涉集中面**：否。

---

# 追加块：2026-09-21/22 统一波「中央调度层 + 出站闸 + 板块生成器」（S-DOCDEBT 席补记，2026-09-22）

> 来源＝本波各席日志（`.superpowers/sdd/2026-09-21-unify-wave/logs/`，逐条点名到席），
> 现树状态由本席逐条亲验（**不采信席位自述**）；无法复核者一律标「未取证」。
> 分级判据＝`docs/boards/_conventions.md` §六。编号承接上方序段（P1 自 13 起，P2 自 1 起），
> 上方既有条目一字未改、未重编号。
> 计数类一律给指针（`docs/auto-facts.md` 或真身定义处），保留旧数者同行标「当时值」。

## 甲、本波内已闭环（八条，只留判据指针，不作开口项）

写法的价值在**复发时能被同一把锁再抓住**，故每条都点名「哪把锁杀什么」。

1. **主动投递键形命名空间只认 `emg`**（R-CENTRAL C-1，Critical）——闸的键形末腿委托紧急谓词，
   开闸当天提醒 / cookie 到期 / 群摘要 / 日常助理四条现役投递全判 `skip`（提醒更被 24h 作废）。
   根因位置 `domains/emergency_info/service/dedupe.py::active_push_key_shape_ok`（新增非紧急分支）+
   `domains/transport/sender/outbound_gate.py::dedupe_key_shape_ok` + 根 `__init__.py` 四处
   `dedupe_namespace=` 申报。判据：`tests/test_outbound_gate.py::test_dedupe_predicates_share_one_implementation`、
   `::test_root_declares_exactly_the_namespaces_it_builds`、`::test_namespace_declaration_lock_has_teeth`
   （两发注毒：报错族 / 漏报回落 `emg`，按失配**差集**判定，不点名函数名）+
   `tests/test_reminder_delivery.py::test_enabled_central_gate_still_delivers_reminders`（开态真投递活性锁）。
   ⚠ 该开关的**开态**至今未在生产生效 ⇒ 见待裁-1。
2. **执行体身份不进审计**（R-CENTRAL I-1）——`via` 已细化为 `caller_capability:{qualname}`
   （`plugins/bot_unified_runtime/runtime/capability_protocols.py::_make_command_handler` / `_make_prepared_handler`）。
   判据：`tests/test_orchestration_callsite_single.py::test_command_handler_records_which_callable_actually_ran` + canary/batch1/batch2 同判据。
   **残余未收**：全树仍无「matcher 侧 factory ≡ 描述符 `implementation_ref`」的比对锁 ⇒ 漂移只留痕、不点名，登记入 P2-7 红线条。
3. **审计钩子非幂等**（R-CENTRAL M-1）——`plugins/bot_unified_runtime/runtime/capability_protocols.py::AuditHookRegistry.register`
   已按对象身份去重（装配块重放不再「一次 invoke 落 N 行」）。
4. **闸设置读不到即永久静默关闸**（R-CENTRAL I-3）——求值异常路径现冒
   `OperationalIssue`，kind 常量 `domains/transport/sender/outbound_gate.py::KIND_SETTINGS_UNREADABLE`。
   判据：`tests/test_outbound_gate.py` 里以 `_flaky` 桩注入读失败的那把锁 + `test_wrong_typed_gate_settings_announces_like_a_failure`（断言 kind 序列恰为该一枚，注毒「只 log 不发 issue」即红）。
5. **同 `capability_id` 双行 × 双 execution**（R-CENTRAL M-2）——判据：
   `tests/test_capability_single_registration.py::test_no_capability_id_declares_execution_on_two_rows`「双行同 id 的家族只准填其中一行」。
6. **空标签让派生整表红**（R-PREP 侧）——`tests/test_prepared_adapter_canary.py::test_multi_entry_liveness_lock_has_teeth` 与 `::test_row_without_human_label_still_derives_a_title`
   钉住「空标签行必须给出可用 value，否则内部席位永远接不进中央」。
7. **多入口绕过层 2 而账按声明降**（R-PREP C-1 + R-CHOKE C-1，两条 Critical 同根）——
   根 `__init__.py` 的别名入口装配段现取 `resolution.capability_id or "bot.alias"`（此前别名入口把固定 id 交给缝 ⇒
   查不到在册 ⇒ 纯直呼，权限/健康/限额/超时/审计一行不跑），且汇合点 `_run_capability_through_pipeline` 已包缝。
   判据：`tests/test_prepared_adapter_canary.py::_SEAM_FUNNELS` + `::test_multi_entry_liveness_lock_has_teeth`。
   **残余**：见 P1-19/P1-20（收紧谓词与扫描面）。
8. **清点账对别名裸调失明**（S-BYPASS RED1）——`tests/test_outbound_bypass_prohibition_gate.py::_submit_alias_names`
   按作用域把绑到队列 `.submit` 的局部名计入命中；台账总数由该席实测 6 改为 **8（当时值，以该门自身为准）**。
   判据：`::test_live_submit_bypass_total_matches_ledger`、`::test_submit_alias_is_caught_within_scope_only`；
   原「按设计逃逸」自证 `::test_poison_submit_alias_escapes_by_design` 已翻面。
   **异名接收者**（`self.q` / `self._q`）仍是该门自陈局限，未宣称清零 ⇒ P2-12。

另：R-CENTRAL I-5 点名的旧注释「两族**未**改道」与同函数断言互相打脸，本席在 `tests/` 全目录已搜不到该措辞
⇒ 按**已收口**记（口径面，不动代码）。

## 乙、开口项 · P1（结果错误 / 口径分叉 / 门禁假绿——本波内应修并各落一条锁）

### P1-13 完成度自审把两枚亲手挖出的 P0 漏账，并以「已落地」口径叙述（B02/B08）

- **级别**：P1（门禁假绿 + 口径分叉）
- **位置**：`.superpowers/sdd/2026-09-21-unify-wave/COMPLETION-AUDIT` 行 3 / 行 16 / 行 17，
  对照 `docs/design/emergency-info-outbound-gate-spec-20260920.md` §1.2、
  `config.py::Config.bot_outbound_gate_enabled`、`plugins/bot_unified_runtime/runtime/capability_protocols.py::CapabilityDescriptor.gate_feature_id`
- **现象**：审计把「投递经 outbound_gate」标 ✅ 且「还差什么=—」，而它自己参与的普查早已挖出
  ①闸关态＝逐字节直通＝四族主动投递**不受管辖**、②`gate_feature_id` 在册但 `invoke()` 零读点＝**字段不执法**；
  同审计另两处被事实证伪——「至今未 commit / 全部留工作树」在落款日已有 `ebb7130` 基线提交，
  「R-CENTRAL 在飞、中央改动尚未过一次独立攻击」与其自己记录的 §33（裁决=阻断 1C/5I/4M）互相打架。
- **根因**：自审以「机制存在」当「机制生效」，且不复读自家席位日志（陷阱清单第 9/15 型）。
- **影响**：收尾真值被高估 ⇒ 任何人据它判定「统一波已达成」都会把未生效的治理记成功能。
- **现状**：三处失实中的两枚治理缺口由本台账丁组（待裁-1/待裁-2）正式承接为明账；
  **审计文本本身未修订**（本席只写台账，不改他席交付件）⇒ 未修。
- **验收判据**：任何「已走中央出口 / 已受管辖 / 已通电」的表述必须同行带**开态**证据
  （真投递回执 + 闸 verdict=allow 的实跑输出），否则该行不许打 ✅；
  建议 owner 在审计件加一条「✅ 需附开态活性证据」的自锁（注毒：把 ✅ 留给只测到 skip 的锁 ⇒ 红）。
- **涉集中面**：否（文档面，归 COMPLETION-AUDIT owner）。

### P1-14 层 2 执行面不查健康，「通电＝受治理」的叙事压在这个洞上（B02）

- **级别**：P1
- **位置**：`plugins/bot_unified_runtime/runtime/capability_protocols.py::CapabilityInvoker.invoke`（链上只有
  在册→blocked→roles→限额→handler→超时→降级→audit），对照 `HealthProbeRegistry` / `compute_health`
- **现象**：`compute_health` 全树唯一调用者是查询面 `health()`；`invoke()` 不读探针。
  评审席实验坐实：探针报 `DISABLED` 时 `invoke` 终态仍 `OK`、handler 真被执行。
- **根因**：健康面在 Wave 2 只按「可观测」落地，未纳入准入链；B0 的「通电」叙事把治理清单写成含健康。
- **影响**：引擎/上游故障期间中央照样打，用户侧表现为超时或降级短句而非「诚实不可用」；
  `/bot status` 与审计读到的健康值对执行零约束（看着受管、实则只在看）。
- **现状**：未修（**待裁-3 之外**的独立缺口——待裁-3 讲的是 `gate_feature_id`，本条是健康探针，两条别混）。
- **验收判据**：`invoke` 前置健康门 + 注毒锁「探针 `DISABLED` ⇒ 终态必 `DEGRADED/UNAVAILABLE` 且 handler 未被调用」
  （今天这发注毒是绿的 = 正是本条要杀的形态）；`health_probe` 为空的在册项须在账上显式标「不执法」而非默认受管。
- **涉集中面**：是（`plugins/bot_unified_runtime/runtime/capability_protocols.py` 属主会话持有面）→ 串行。

### P1-15 降级链共用同一条超时窗口，兜底腿只剩极短地板（地板值以 `_run_fallbacks` 真身为准，B02/B05）

- **级别**：P1
- **位置**：`plugins/bot_unified_runtime/runtime/capability_protocols.py::_run_fallbacks` 的
  `remaining = max(1.0, min(timeout_seconds, _MAX_TIMEOUT_SECONDS) - (monotonic - started))`；
  现场 `media.vision.anime_ip`（中央 20s，唯一真注册了 fallback 的描述符：
  `FallbackRegistry.register("media.vision.anime_ip", "vlm_candidate", _handle_media_vision_image)`，
  内层 `config.py::bot_vision_timeout_seconds=20.0`）
- **现象**：主腿（SauceNAO）吃掉整个窗口后，VLM 降级腿只分到 1.0s 去跑一个 20s 预算的作业
  ⇒ 诚实降级**结构性不可达**。全树唯一有真 fallback 的描述符恰好就是它。
- **根因**：`remaining` 用「总预算减去已耗」而非「每条 fallback 各自预算 / 预留切片」。
- **影响**：用户拿到温和失败而非可用结果；降级路径写了等于没写，而测试面看不见（它在超时前从不执行）。
- **现状**：未修。同波 S-TIMEOUT 席位已把注册册数值修好（`bot.meme` 60→120、`bot.wiki` 60→75，
  见 `domains/chat_reply/runtime/capability_registry.py` 现值 + 行内算术注释），
  并明确点名**「对 anime_ip 调大数字无效」**——主腿只会吃掉更大的窗口。
- **验收判据**：注毒「主腿恰好耗满窗口」⇒ 断言 fallback handler **确实被调用**且拿到 ≥ 其内层预算的时间片；
  今天这条注毒会得到「fallback 被调用但 1s 内失败」⇒ 判据须含时间片断言，不接受只查调用次数。
- **涉集中面**：是（中央壳文件）→ 串行。

### P1-16 层 2 接管后「双池嵌套 + 排队时间计入中央超时」，峰载即自我判死（B02/B03）

- **级别**：P1
- **位置**：`plugins/bot_unified_runtime/runtime/capability_protocols.py::CapabilityInvoker.invoke`（`future.result(timeout=budget)`
  阻塞在 `_MAX_WORKERS=4` 的 cap-proto 池）×`domains/chat_reply/runtime/pipeline.py::offload_capability`
  （chat-pipeline 池，缺省 worker 8 / 在途 16）
- **现象**：一次重型命令同时占两池各一条线程；chat worker 池的全部线程可以合法地卡在更小的 cap-proto 线程数上（池容量以真身为准）。
  排队等待计入 `budget` ⇒ 并发重型能力在飞时，后到的**尚未开跑即可 TIMEOUT**，被换成温和短句。
  该席实测在册行里有多枚同时在 `OFFLOADED_CAPABILITY_IDS`（重型渲染族），属正常峰载而非理论态；
  另有在册但不在 offload 集的行 ⇒ `future.result` 直接冻住事件循环。
- **根因**：把「能力自己的预算」与「中央队列等待」用同一个数计，且两池无背压/无隔离声明。
- **影响**：越忙越像「bot 说不上话」，且失败面（TIMEOUT）不告警（见 P1-17），线上只能从审计里猜。
- **现状**：未修（评审裁决 I-2，本席未见落地形态）。
- **验收判据**：并发「在册能力数再加一」的确定性测试 ⇒ 断言「排队时长不计入 `budget`」或
  「超员走明确 BUSY 终态」；注毒：把 budget 计算改回含排队 ⇒ 该锁红。
  并把「在册且 `timeout_seconds > 5` 者必在 `OFFLOADED_CAPABILITY_IDS`」做成集合锁（只准降不准升）。
- **涉集中面**：是（中央壳 + pipeline）→ 串行。

### P1-17 中央自己拦下的终态不回 `operational_issue`，告警与错误卡两面全瞎（B02/B07）

- **级别**：P1
- **位置**：`plugins/bot_unified_runtime/runtime/capability_protocols.py`（缝内 DENIED / LIMIT_EXCEEDED / TIMEOUT 短路构造呈现结果处，
  `operational_issue` 写死 `None`）
- **现象**：层 2 治理生效 = 消息被中央丢掉，但运维面零痕迹；只有审计里有 status 行。
- **根因**：早退分支照抄「不贴 issue」的旧约定，未区分「能力失败（该告警）」与「治理主动拒绝（可静默）」。
- **影响**：治理越有效，越接近台账 #29⑪ 之前那种「一行异常日志了事」的黑箱；管理员无法从
  `/bot status` / 告警看出「今天被中央拦了多少、为什么」。
- **现状**：未修。刻意与「超时要不要发卡」（待裁-4）分开：本条要求的是**告警与可观测面**，不是给用户的卡片。
- **验收判据**：三类终态各断言 `result.operational_issue is not None` 且 kind 可枚举（TIMEOUT/DENIED/LIMIT_EXCEEDED）；
  注毒：把任一分支的 issue 改回 `None` ⇒ 该锁红。
  同批补一条聚合计数锁（拦了多少），避免「贴 issue 触发 A-19 群聊吞体」旧坑复现（该约束保留：正文不回用户）。
- **涉集中面**：是（中央壳 + 告警面）→ 串行。

### P1-18 自动配音腿缺「结果变换形」适配器，直连合成旁路层 2，靠两把休眠键掩盖（B06/B07）〔本行标题＝2026-09-21 当时的判词，其中「缺适配器」这半已失效；该腿现状是**已通电，而两把开关键缺省关 ⇒ 关态不可达**，逐条对照见本条「现状」段，不改写也不删除原标题〕

- **级别**：P1（口径分叉 + 门禁只钉现状）
- **位置**：`domains/media/voice_enricher.py`（`enrich(message, decision, result) -> result`，直连
  `domains/creation/**` 合成）× `plugins/bot_unified_runtime/runtime/capability_protocols.py::_make_prepared_handler._handle`
  （本席亲验：执行体调用式仍是 `callable_from_caller(message, decision)`，**无「前序 result」通道**）
- **现象**：`_KNOWN_ADAPTERS` 现含 `{"command","prepared"}`，但 prepared 形的「成品」指**已装配的执行体**，
  不是 review 之后的呈现结果；要把 post-review 变换经中央跑，需要第三种「结果变换形」适配器
  + 对应 descriptor + handler。既有 `creation.tts.synthesize` 有描述符无 handler ⇒ `invoke` 恒 `UNAVAILABLE`，不可复用。〔⚠ 2026-09-25 S261 现算：本句后半已失效——中央调度收编波给该能力注册了 handler（`capability_protocols.py::_handle_creation_tts_synthesize`，同样只薄委派域内真身），当时值按本册「保留不删」规矩留在原文里。〕
- **根因**：执行面 adapter 谱系按「命令形 / 已装配命令形」两形落地，缺变换形这一类真实需求。
- **影响**：mandate「所有内容走中央出口」在这条腿上不成立；生产现被
  `bot_tts_voice_hook_enabled=False` ∧ `bot_tts_auto_reply_enabled=false` 两把独立门**休眠掩盖**——
  两键一翻即旁路复活，而现有门（`tests/test_voice_central_entry_gate.py` A1–A5、
  `test_orchestration_callsite_wave_media.py` 把 `bot.tts.synth` 钉成 `KNOWN_DIRECT_ALLOWLIST_MEDIA`）
  只钉现状、不主张中央可达 ⇒ 绿灯不等于受管。〔2026-09-25 席 S272：**本段整条是 2026-09-21 的
  当时值**——其中「两键一翻即旁路复活」与「`bot.tts.synth` 被钉成直呼 allowlist」两形随后分别被
  收编与摘牌，判今天请读下一条「现状」，本册按规矩不删原文〕
- **现状**：**已落地·收编为中央第三形（S91，2026-09-24；S253B 现算复核、S261 跟随措辞）**——
  第三形 `media.tts.autodub_transform` 有 descriptor + handler（`capability_protocols.py`
  的 `_handle_media_tts_autodub_transform` 只薄委派域内真身
  `plugins/bot_unified_runtime/domains/media/tts/result_transform.py::handle`），
  生产侧唯一消费点＝`domains/media/voice_enricher.py` 那一处字面 `invoke`（"恰一处"是 AST 判据）。
  〔⚠ 2026-09-25 席 S288D 现算：本句是 **S91 当时的拓扑（当时值）**——S270 把产出步归位成单一组合口之后**所指已变**，
  按本册「原文不删、就地改口」规矩在句后跟随。今天全树生产面（`plugins/` + `scripts/`，AST 现算）有**两发**字面
  `invoke`、各在一处：层 1 hook 派发第三形 `media.tts.autodub_transform` 那一发仍在
  `domains/media/voice_enricher.py::_enrich_via_central`；而本句原指的**产出步** `media.tts.autodub` 那一发已搬进
  `domains/media/tts/result_transform.py::dub_via_central`（hook 侧对该 id 的 invoke 数＝0；"组合口恰一处 + 退役旧点位"
  两半同时成立才算归位而非另加一份，由 `tests/test_voice_enricher_central_dispatch.py::test_auto_voice_leg_no_longer_calls_synthesize_directly`
  钉住）。故"唯一消费点"不再成立于单文件：该组合口有两条生产入路（`voice_enricher` 的 `dub` 闭包与
  `domains/creation/tts/engine_provider.py::synthesize_via_engine`），"恰一处"这枚 AST 判据今天量的是
  **invoke 点**、不是**消费点**。点位与逐枚归属一律以缺口账 `tests/test_descriptor_wiredness_ledger.py`
  与直呼面普查门现算为准，本册不抄第二份清单〕
  本条验收判据逐条对照：①「xfail 转正向锁」＝已达成（`tests/test_voice_enricher_central_dispatch.py`
  现为常态化正向锁、无 xfail，活性用例 `test_central_transform_dispatch_reaches_registered_handle`
  真跑到注册体一次并把带音频呈现结果读回）；②「`bot.tts.synth` 摘出直呼登记集」＝已达成
  （`tests/test_orchestration_callsite_wave_media.py` 里 `KNOWN_DIRECT_ALLOWLIST_MEDIA["bot.tts.synth"]`
  现为空集，产出步改走 `media.tts.autodub` 的 invoker 面）。
  **仍要同行读的两条限制**：ⓐ「已通电」≠「已生效」——现网 `bot_tts_voice_hook_enabled` 缺省 False
  且生产 `.env` 未设该行、`bot_tts_auto_reply_enabled=false`，两把休眠键仍在 ⇒ **今天这条腿关态不可达**、
  生产行为逐字节不变；翻键还须重启（装配期读死）。〔2026-09-25 席 S272 复核：同一结论**从合法口也成立**
  ——`config.py` 里 `bot_tts_voice_hook_enabled` 与 `bot_tts_auto_reply_enabled` 两枚字段缺省都是 `False`；
  生产实值不在本册判定范围内（判开关是否关着的合法口只有 config 缺省值、
  `plugins/bot_unified_runtime/domains/core/config/config_readiness.py` 投影、以及让用户看
  `/bot status`），上一句那句 `.env` 读法按当时口径保留、不作为本册的取数方式〕ⓑ形式命题「`_KNOWN_ADAPTERS` 里多一个变换形成员」
  **刻意未做**：`TRANSFORM_SHAPE` 不进 `_KNOWN_ADAPTERS`、不进路由行（现算该集合仍为
  `{"command","prepared"}`），走的是"直接注册执行体"这条与 `media.tts.autodub` 同族的路——
  故本条不得叙述为"适配器谱系已补全"。旧包装（根 `_attach_voice_reply` → `maybe_attach_voice`）
  的退役第二步仍挂 xfail（`tests/test_voice_hook_assembly.py::test_r9_root_init_retires_legacy_wrapper_symbols`），
  双态互斥、与本腿不并存。〔以下为本条 2026-09-21 发现当时的原文，按本册规矩保留不删：未修（该席按禁造
  第四路规则停在规格 + RED 测试，未落生产码）。缺口已由 `tests/test_voice_enricher_central_dispatch.py`
  以「现状钉 PASS + 目标 `xfail(strict=False)`」显式挂账。〕
- **验收判据**：xfail 转 XPASS 即落地信号（目标用例：合成须经 `CapabilityInvoker.invoke`）；
  落地同批必须把 `bot.tts.synth` 从 `KNOWN_DIRECT_ALLOWLIST_MEDIA` 摘进
  `KNOWN_INVOKER_SITES_MEDIA` 并删现状钉——只翻键不摘牌 = 假绿。
- **涉集中面**：是（中央壳 + 注册册两件主会话持有面）→ 串行。

### P1-19 申报锁只扫根文件，清点器扫全树：两把门扫描面不一致（B08/B10）

- **级别**：P1（门禁假绿复发面；现役不可达，故不升 P0）
- **位置**：`tests/test_outbound_gate.py::test_root_declares_exactly_the_namespaces_it_builds`
  （`ast.parse(ROOT_INIT…)` 单文件）vs
  `tests/test_outbound_bypass_prohibition_gate.py::scan_submit_bypasses`（`rglob("*.py")` 全树）
- **现象**：键形申报的活性锁对 `domains/**` 完全失明；若将来 `pipeline.py` / `error_report.py`
  任一处改道 `submit_active_push` 而漏传 `dedupe_namespace`（回落 `emg`），申报锁不红、开闸即整族静默丢
  ＝ C-1 同型复发。该席用两发只读注毒把「含 `ROOT_INIT`、不含 `rglob`」静态坐实（RED2）。
- **根因**：两把门不同波次落地，扫描面从未对齐，也没有「本锁看不见哪片」的显式声明。
- **影响**：唯一能拦 C-1 复发的锁，其覆盖面被高估；豁免裁定（S-BYPASS：两处都不改道）今天替它兜着，
  而裁定是口径、不是代码。
- **现状**：未修（登记）。
- **验收判据**：把申报锁的扫描面从单文件扩为文件列表并配地板（`scanned` 下限随真身数上移，只准升），
  或在该锁显式声明「本锁只盖 root」并在改道前置条件里点名；注毒=在 `domains/` 造一处漏申报的直调 ⇒ 必红。
- **涉集中面**：否（测试件内）。

### P1-20 汇合点判据看得见「汇到缝」、看不见「缝拿到什么 id」；直连入口无门（B02/B03）

- **级别**：P1
- **位置**：`tests/test_prepared_adapter_canary.py::_root_dispatch_comparisons`
  （只认 `Compare(left=Attribute(attr="capability_id"), ops=[Eq])`）；旁路形态清单：`in (...)` 成员判定、
  反向常量比较、局部别名 `cid = resolution.capability_id`、表驱动 `HANDLERS[kind](...)`、
  以及根本不经两汇名的直呼 `pipeline.handle*/handle_async`（该席实测 13 处，**当时值**，
  含 music / meme_library / media_archive / campus_forward 等）
- **现象**：别名入口那一例已被改道修掉（甲-7），但判据形态没变——以上任一形态复现时锁零反应；
  在册集外条目补上 execution 行，就是「一条命令在册、生产零治理」而缺口棘轮照降。
- **根因**：活性锁按「函数是否提到两个汇名」判定，而非按「缝参数实际拿到的 id 是否在册」。
- **影响**：调度层覆盖率的账面可被结构漂移悄悄高估；本波已为此付过一次 Critical。
- **现状**：**未修（未取证是否已在别处收紧）**——本席在全树未搜到「缝参数谓词」或「直连入口白名单」的实现符号
  （如 `KNOWN_DIRECT_PIPELINE` 类件），按未修登记；若 owner 已有落地形态，请以判据指针销账本条而不是删条目。
- **验收判据**：两条谓词各配注毒自证——(a) 在册 id 被换成固定常量交缝 ⇒ 红；
  (b) 新增一处直呼 `pipeline.handle_async` 且不在白名单 ⇒ 红，白名单只准降不准升（与 GAP_CEILING 同哲学）。
- **涉集中面**：否（测试件内）。

## 丙、开口项 · P2（结构 / 口径 / 文档类，整理波批量清）

> 每条同样给「能杀行为的判据」，只是允许留待裁决批量处理（`_conventions.md` §六）。

### P2-1 板块声明源缺 timesync 路径 ⇒ 生成卡指向错落点（B10）
- **级别**：P2 **位置**：`domains/core/board_taxonomy.py` 的 `B04.notes.impl_paths`
  （现值只有 `domains/notes/capabilities/notes.py` 与 `domains/notes/store`，本席亲验）
- **现象**：授时真身 `domains/schedule/timesync/timesync.py::TimeSync` 不在实现落点里，
  投影出的 `B04…/notes/time-sync.md` 生成头与代码不符；正文只能靠「落点勘误」引用块自证（S-BOARD3 F1）。
- **影响**：生成物是「唯一真值」的地方反倒错指；读者按生成头去改代码会改到无关文件。
- **现状**：未修（该席只登记不修；本席亦不改声明源）。
- **判据**：`scripts/board_doc_sync.py --check` 绿且活性覆盖门断言「time-sync 页的实现落点可解析到真身」；
  注毒=从 impl_paths 删掉补上的路径 ⇒ 门红。 **涉集中面**：否（声明源单件，但与 P2-2/P2-3 同文件 ⇒ 同批）。

### P2-2 板块声明源缺向量知识库真身 ⇒ 两张卡不含切块/索引/配额（B10/B04）
- **级别**：P2 **位置**：`domains/core/board_taxonomy.py` 的 `B04.knowledge.impl_paths`
  （只声明 `domains/core/search` 与 `plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`；本席亲验该件全文零 `vector_knowledge` 命中）
- **现象**：真身 `domains/chat_reply/character/vector_knowledge.py`（`sync_chunks`/`embed_pending`/
  `build_ann_index`/配额族选择那一套）不露出在 `kb-indexing`/`kb-quota` 两页；`bot_knowledge_db_path` 的持有者也非生成头所列。
- **影响**：知识库板块的「实现落点」缺一整块真身，一功能一目录的可导航性在最高风险件上失效。
- **现状**：未修（正文里写「真身按本段为准」是止血，不消除双口径）。
- **判据**：补路径后 `--check` 绿 + 门断言两页落点含该真身；注毒=删该路径 ⇒ 红。 **涉集中面**：否（同 P2-1 同文件同批）。

### P2-3 板块声明源把自身 Compat 垫片并列成实现落点（B10）
- **级别**：P2 **位置**：`domains/core/board_taxonomy.py` 的 `B02.policy-gate.impl_paths`
  （同时列 `plugins/bot_unified_runtime/policy` 与 `domains/chat_reply/policy`；前者文件头自证是 Compat shim）
- **现象**：生成卡读起来像「两处真身」，而真身只有一处；正文靠点名垫片身份兜（S-BOARD6 F2）。
- **影响**：直接违反 §三「禁第二真身」的**读感**——比真副本更坏，因为它是官方生成物在指认副本。
- **现状**：未修。
- **判据**：impl_paths 去垫片后 `--check` 绿；建议再加一条门：生成头落点里出现「头注自证为垫片」的文件 ⇒ 红
  （注毒：把任一 shim 路径塞回声明源 ⇒ 红）。 **涉集中面**：否。

### P2-4 锁文件正文写着与生产相反的陈述（B02/B10）
- **级别**：P2 **位置**：`tests/test_prepared_adapter_canary.py` 的 `_SEAM_FUNNELS` 上方注释
  （称「`_run_simple_capability` 内部亦经 `_run_capability_through_pipeline`」）
- **现象**：R-PREP 的 AST 统计给的是 `{_orchestrated:1, handle_async:1, offload_capability:1}`，
  即它直呼 `pipeline.handle_async`，不经那个汇名；本席复核该注释仍在。
- **影响**：这句话同时是收录两枚汇名的**理由**（P1-20 判据的地基），错的解释会喂给下一位改道的人。
- **现状**：未修（注释面）。
- **判据**：注释改正后，把该解释性断言升为锁的一部分（断言两汇名各自的生产形态），注毒=把 `_run_simple_capability`
  改成经另一汇名 ⇒ 判据跟着变而不是注释说谎。 **涉集中面**：否。

### P2-5 每条能力消息重派生整张执行形表（B02/B05）
- **级别**：P2 **位置**：`plugins/bot_unified_runtime/runtime/capability_protocols.py::_route_execution_adapters`（本席亲验：无缓存、
  每次重建并逐行校验）
- **现象**：该席实测 ≈60.5µs/次、每建一轮全表描述符（**当时值**，在册行数以注册册为准）；
  本波把调用它的入口从一处扩到十余处 ⇒ 每条能力消息固定付一次，且多数只为发现「我不在册」。
- **影响**：热路径常数开销 + 与 `default_invoker()` 的 handler 首次代际可能不一致（R-PREP M-3 同根）。
- **现状**：未修。
- **判据**：`tests/test_perf_regression.py` 加一条「单条消息派发层的派生次数 ≤1（模块级 memo，热重载时失效）」；
  注毒=拿掉 memo ⇒ 计数红。今天该件只测路由吞吐与导入时长，测不到这项。 **涉集中面**：是（中央壳）→ 串行。

### P2-6 幂等标记在 offload 出口丢失（B02/B03）
- **级别**：P2 **位置**：`domains/chat_reply/runtime/pipeline.py::offload_capability`（包裹 `_step` 后标记不透传、无 `__wrapped__`）
- **现象**：该席探针实测「`_step` 带标记 ✓、`offload_capability(_step)` MISSING」；今天不可达
  （全部实参是本函数内 `def` 闭包），但配合 P2-4 那句错注释有人改道就会二次包裹。
- **影响**：二次包裹的实际后果不是双跑而是**能力当场坏掉**（外层拿到 async wrapped，`presented.model_dump()`
  抛 AttributeError ⇒ 降级 ⇒ 温和短句）。
- **现状**：未修。
- **判据**：`offload_capability` 出口透传标记 + 一条锁「对已标记可调用对象再包裹必响亮拒绝」。
- **涉集中面**：否（pipeline 单点，但属主会话持有面 ⇒ 建议与 P1-16 同批）。

### P2-7 「只断言一条委托边」的同源锁形态——通用红线（B10）
- **级别**：P2（形态问题，价值最高）
- **位置**：先例 `tests/test_outbound_gate.py::test_dedupe_predicates_share_one_implementation`
  （修复前只断言 `is_emergency_dedupe_key`，新委托边 `active_push_key_shape_ok` 无人点名 ⇒ 内联分叉而锁全绿）；
  同族待补：甲-2 的 `implementation_ref ≡ 实际 callable` 比对仍无锁。
- **现象**：中央件把规则委托出去后，AST 锁只钉住**旧的那条边**；新增/改名的委托边在判据里等于不存在。
- **影响**：「一处实现」变成只在实现侧成立、在执法侧可分叉；这类假绿本波被抓到两次（RCB-1、RC1 I-1）。
- **现状**：本波两例已各自补锁；作为**通用红线**登记待采纳——建议 owner 把它写进
  `docs/boards/_conventions.md` 的代码质量红线（本席不改规范件）。
- **判据**：凡「A 委托 B」的锁必须同时点名**当前全部**委托目标且加一条「函数体内出现内联谓词
  （`re.` / `isalnum` / `strip(` 类形态判定）」即红；注毒=把任一委托边内联 ⇒ 当场红。
- **涉集中面**：否。

### P2-8 叙述与注释里的会漂移计数 / 过期口径（B10）
- **级别**：P2 **位置**：`tests/test_descriptor_wiredness_ledger.py`（多处手写「N 枚 / 109→108」类注释，
  断言侧已改用 `>=` 下限故只红注释不红门，R-PREP M-2）；
  `docs/design/capability-orchestration-adoption-spec.md` 仍写旧函数名
  `seam_registered_command_cids()`（R-PREP M-1）
- **现象**：铁律 10 的执法门覆盖叙述册，不覆盖测试注释与设计规格内的指针式旧口径。
- **影响**：改码者按注释数字自证、按旧函数名抄调用 ⇒ 结构性空转。
- **现状**：**部分未取证**——R-PREP 称代码/门零残余旧名，R-AUDIT 却以该旧名实跑取值，两席口径互斥，
  本席未能判定现役真名 ⇒ 两条都标未取证，由 owner 一名定论。
- **判据**：注释去数字化（改指真身/生成物）；规格内函数名指针与真身同名（注毒：真身改名而规格指针不改 ⇒ 该文档链接门红）。
- **涉集中面**：否。

### P2-9 两条键形/谓词严格度不对称与裸 f-string 键（B08）
- **级别**：P2 **位置**：`domains/emergency_info/service/dedupe.py::active_push_key_shape_ok`
  与 `is_emergency_dedupe_key`；根 `__init__.py` 四族 `dedupe_key=f"…"` 处
- **现象**：紧急侧日期段只过 `\d`（匹 Unicode 数字）、非紧急侧全段先过 `_SEGMENT_RE` ⇒ 严格度分叉
  （生产不可达，日期恒 isoformat）；四族键无「归一一次」构造口，脏输入（配置未 strip）在开闸态＝skip 静默丢
  （有 warning 日志），不是双发（R-CENTRAL-b M-3/M-4）。
- **现状**：登记不修（紧急侧受「逐字节不变」约束冻结）。
- **判据**：若将来统一谓词，注毒=Unicode 数字日期键 ⇒ 两侧结论必须一致；四族若接 `build_*_dedupe_key`
  归一口，加锁禁裸 f-string。 **涉集中面**：否。

### P2-10 creation 幂等 preimage 用类名而非限定名（B04/B06）
- **级别**：P2 **位置**：`domains/creation/_common/contracts.py::idempotency_preimage`
  （以 `type(model).__name__` 起头）
- **现象**：今日各类名互异无碰撞；将来别处再出一个同名 DTO ⇒ 两条不同请求撞同一身份键＝**漏重发**。
- **现状**：未修（改法一行，但会改已定案键形 ⇒ 须同步 `IDEMPOTENCY_RULE_VERSION`）。
- **判据**：注毒「两个不同模块的同名 DTO」⇒ 断言两枚幂等键不同；版本常量未同步时该锁须拒绝放行。
- **涉集中面**：否。

### P2-11 闸实例 `None` 语义两侧不一致（B08）
- **级别**：P2 **位置**：根 `__init__.py::_push_via_central_exit_now`（无条件 `gate.clock()`）vs
  紧急链显式支持 `outbound_gate is None`；提醒侧无 try 包裹而 cookie 侧有
- **现象**：现网装配恒非 None ⇒ 不可达；但两族契约不同写，「闸可缺位」一旦扩散到 A 类站点就炸在 job 里。
- **现状**：未修（登记）。
- **判据**：统一为「缺位即响亮 TypeError」或「缺位即诚实直通」二者之一，并锁「四族对同一 `None` 输入行为同构」。
- **涉集中面**：是（根文件）→ 串行（受行号棘轮牵制，见 P1-1）。

### P2-12 出站旁路门的两处自陈局限（B08）
- **级别**：P2 **位置**：`tests/test_outbound_bypass_prohibition_gate.py`（异名接收者 `self.q`/`self._q`
  不在判据内；`test_poison_divergently_named_receiver_escapes_by_design` 把这条局限钉成常驻事实）
- **现象**：别名面已收编（甲-8），但换个属性名的旁路仍不可见；台账总数「清零」不许宣称。
- **现状**：未修（该席明确「另案，不许顺手宣称清零」）。
- **判据**：扩到接收者名字集合或改判「任何 `*.submit(` 直调非闸出口」+ 白名单只减不增；落地前所有「已清零」表述按违规记。
- **涉集中面**：否。

### P2-13 顺带登记：提醒能力仍从旧垫片路径取笔记存储（B04/B10）
- **级别**：P2 **位置**：`domains/schedule/capabilities/reminder.py` 从
  `plugins.bot_unified_runtime.character.notes_store` 导入 `build_notes_store`
  （真身 `domains/notes/store/notes_store.py`）；坐标为该席实测（**当时值**，本席未复核行号）
- **现象**：垫片退役存量，落在本波刚动过的邻域。
- **现状**：未修（非本席面，仅登记）。
- **判据**：既有旧路径消费边门（`test_v21*` 族）在该文件命中数归零。 **涉集中面**：否。

## 丁、须用户裁定（指针 `decisions/PENDING-RULINGS-20260922.md`「丁」组条目）

> 四条**都不是 bug 现场**，而是「机制已落、生效与否取决于一次授权」的明账。裁定前一律按
> 「未生效」记账，不得写进「已完成」（铁律 5）。

- **待裁-1（`PENDING-RULINGS-20260922.md`「丁」首条）出站防风暴闸缺省关 ⇒ 键形核验 / 安静时间顺延 / 每主体限流 / 闸审计四件事现网一件没发生**。
  位置 `config.py::Config.bot_outbound_gate_enabled`（缺省 False，生产 `.env` 未设该键）。
  影响：甲-1 修好的键形边界与「所有内容走中央出口」的口径都只在关态直通下**不显形**。
  现状＝已登记待裁。判据（开闸前后各一次）：开态真投递成功活性锁 + 静默窗内 `DEFERRED` 回执锁；
  开之前须先定每分钟/每小时限额。**推荐序**：先紧急域、再摘要（该件原话）。
- **待裁-2（`PENDING-RULINGS-20260922.md`「丁」次条）层 2 不执法 feature gate**。位置 `plugins/bot_unified_runtime/runtime/capability_protocols.py::CapabilityInvoker.invoke`
  （`gate_feature_id` 在册、由描述符派生面赋值，**invoke 链零读点**；两席独立同结论）。
  影响：功能开关只在层 1 生效 ⇒ 「能力在册即受治理」不成立。现状＝已登记待裁。
  判据：接与不接都要留痕——接则注毒「gate 关闭 ⇒ 执行前被拒」必红；不接则在册表须显式标「字段不执法」，
  禁止任何文档称其执法。注意它与 P1-14（健康探针）是**两个不同的不执法**。
- **待裁-3（`PENDING-RULINGS-20260922.md`「丁」条目）中央超时不抛 ⇒ 层 1 诊断卡对「能力挂死」完全不触发**。
  位置 `plugins/bot_unified_runtime/runtime/capability_protocols.py`（超时终态不带原始异常、现亦不回 issue，见 P1-17）。
  影响：用户只看到温和短句，管理员只能翻审计。现状＝已登记待裁（选项 A/B/C 已给，推荐 A）。
  判据：无论选哪项，须有一把锁说明「能力挂死」这条路径**在运维面可见**（A＝可观测、B＝发卡、C＝聚合）。
- **待裁-4（`PENDING-RULINGS-20260922.md`「丁」条目）空角色＝系统主体豁免是否收紧**。
  位置 `plugins/bot_unified_runtime/runtime/capability_protocols.py`（invoker 权限门 `getattr(decision,"actor_roles",()) or ()` 视作系统主体，
  越过能力自身角色下限）。实测已坐实方向：对 admin 下限的在册能力投 `roles=()` **确实穿过并执行了 handler**。
  今天不可从真人消息抵达，但那三重保证是**跨模块口头不变量**（入站校验器塞 "user" / `resolve_roles` 恒含 user /
  现役 command 行 roles 全 `("user",)`），无一条是锁。现状＝已登记待裁，作用域锁已在
  `tests/test_orchestration_callsite_single.py::test_system_principal_exemption_is_locked_to_empty_roles_only`。
  判据（若选 B/C）：注毒「command 行 roles 抬到 admin 且 decision 缺位」⇒ 必须 DENIED；
  另要求豁免主体留可归因身份（别用空 tuple 兼差）。

## 本块小结（按分级计数，来源＝上方条目）

已修并留判据若干｜P1 开口（P1-13…P1-20）｜P2 登记（P2-1…P2-13）｜待裁若干，各计数以本文件上方条目现算为准。
标「未取证」的项：P1-20（收紧谓词是否已落地）、P2-8（旧函数名真名）、P2-13（行号坐标）；
P1-13 的两枚治理缺口已转待裁-1/待裁-2 明账，审计文本本身仍未修订。

### 2026-09-22 统一波冻结窗追加（P2 开口追加，均现算取证）

- **P2｜缺门：媒体内容身份可以有第二份实现而无人拦**。中央唯一入口 = `plugins/bot_unified_runtime/domains/media/digest.py`
  （`media_digest` / `media_digest_file`），消费方已覆盖 TTS/归档/渲染/meme/creation，但**没有任何一把门**禁止
  再写一处"对媒体字节做哈希当身份"。已验证可执法的窄判据（不是宽泛 sha256 扫描——那种尺子今天会误报 9 处
  token/salt 类哈希）：**扫描面 = `domains/media/`、`domains/render/`、`domains/meme/`、`domains/creation/`、
  `domains/files/`，参量形为字节形命名（bytes|blob|image|audio|media|payload|data|chunk|buffer）或 `read()/b64decode()/.content`**
  ⇒ 今天恰好命中 2 处：中央件自身 1（授权）+ 下述 1（欠款）。**正样验证过**：判据必须看得见 `digest.py` 自己那两处，
  否则"零命中"只是尺子瞎。
- **P2｜欠款实体：表情图库下载去重用内联 md5 当图像身份**
  `plugins/bot_unified_runtime/domains/meme/sources/meme_library_listener.py::absorb_event_images` 内的下载去重段——
  `md5 = hashlib.md5(image_bytes).hexdigest()` 直接进 `pending` 作去重键。后果：①第二份内容身份实现（与中央件并存即漂移）；
  ②用的是 md5，比中央件的 sha256 弱；③与 `media_archive` 的 sha256 去重**不互通**（同两张图在两个库里判重口径不同）。
  最小修法：改 `media_digest(image_bytes)`；若判重键格式不许变（库里已有 md5 行），则保留旧列、新增 sha256 列并行写，
  按 AGENTS 运行数据保护条款**不清洗存量**。归口：meme 域 owner；上面那把门落地时它必须进登记面（写明 home 与理由），
  迁完摘牌即让上限降一格。

---

# 追加块：2026-09-22 规格统一波（taxonomy wave）机器门与归属机制面（S97 席补记，2026-09-22）

> 来源＝本波席位报告（`.superpowers/sdd/2026-09-22-taxonomy/`：SEAT-S70 / S79 / S80 / S81 / S88 的既有结论，本席不自创新论断）。
> SEAT-S94 交卷时不在盘 ⇒ 该席点名的 `scripts/physical_placement_census.py` 读侧「读不到当缺键」缺陷**不在本块记账**，由持有其结论的席交卷后另录。
> 本席只记账不修码。所引坐标一律按**符号名**锚定（用例名/函数名），不写行号——行号随他人编辑漂移：本块原写的 `__init__.py:6628` 于 2026-09-24 现算已错位到该文件另一函数，S20 席据此把本块全部坐标重锚为符号形。两处例外如实记：S70 旧坐标 `scripts/spec_gates_census.py:334-335`
> 已被 S78 施工覆盖（原缺陷现状见甲-1「已修」），`docs/templates/sdd-ledger.md` 的别名两行仍命中。
> 开口项数以本块编号标题现算为准（AGENTS 铁律 10）；文中一切「N 枚 / 余量 N」均为发现当时值并就地标「当时值」。

## 甲、本块内已闭环（已修·归属，只留判据指针，不作开口项）

1. **`BOARD-AUTO` 页级信任可被第二对标记藏裸事实（P-S70-1，Critical，B10）**——旧判据对板块生成页走**页级**
   `b_ok` 放行 ⇒ 同一枚生成页再嵌一对 `BOARD-AUTO` 注释、第二段里写裸计数，行级面A 与 boards 账两边都不记
   （S70 内存注毒实证，受害面枚数为其当时值、现数以门自身 `UNVERIFIED_AUTO_ZONE` 计数为准）。
   现状＝**已修·归属 S78**（本席现算复核：`scripts/spec_gates_census.py::_auto_zone_verified` 板块分支已为**逐段**
   重渲染比对，段数或内容不符 ⇒ `UNVERIFIED_AUTO_ZONE` 判红；件内 P-41 施工注释自证与 S78 简报「多一段即红」裁定同形）。
   判据指针：`BOT_AUTOSYNC=0 python scripts/spec_gates_census.py --report` 现算。复发型复发时应被同一条腿再抓。
2. **被两任前席点名却无人清零的求助兜底文案（P-S79-1 过程形态，B06）**——简报前提「`default('…CJK…')` 枚数为零」
   被 S79 现算证伪：一枚住 `plugins/bot_unified_runtime/domains/render/card_render/templates/error_card.html`
   （S44R/S61 两席均点名「不碰」＝点名 ≠ 清账）。现状＝**已修·归属 S79**（改参数引用
   `card_text.error_help_fallback`，唯一落点 `domains/render/card_render/bridge.py::_CARD_TEXT`，HTML/PNG 字节等值已证）。
   判据指针：`tests/test_rendering_contract.py::test_card_templates_have_zero_hardcoded_cjk_fallback_literals`
   （注毒⇒红、还原⇒绿，S79 实跑）。
3. **归属投影「声明源不在盘」态走着第二条码路（S88 变异探针逼出的真缺陷）**——拔掉渲染层该态照样点名 ⇒
   七态诊断被旁路。现状＝**已修·归属 S88**（并回唯一出口 `main(["--check"], repo=...)`；行为锁
   `tests/test_doc_ownership_ledger.py::test_s88_state_absent_is_named_and_says_generate`，本席现算确认该席
   `test_s88_` 族用例在盘）。

## 乙、开口项 · P1（门禁假绿 / 静默吞失败——本波内应修并各落一条锁）

### P1-21 `@aliases` 在单一模板内非单射 ⇒ 同义别名可静默吞掉真·distinct 节（B10）

- **级别**：P1（S81 原判 Critical；「缩小扫描面同型」的门禁假绿）
- **位置**：`docs/templates/sdd-ledger.md` 头注 `@aliases` 两行——`清单` 同时是槽位 `账目` 与 `卫生` 的别名
  （本席现算复核：两行声明均命中）；执法侧 `check_sections`/`_match_slot`（S63 实现的三级序认名）
- **现象**：`_match_slot` 按 sections 声明序命中 ⇒ 物理节名「清单」可被两槽位之一吸收，另一槽位判 MISSING、
  或 DUPLICATE 判定随声明序非确定——「被别名吞掉不再报」有机制入口。装载期只校验「缺 `=`／空别名／指向未在册槽位」，
  不校验「一枚别名串在一模板内属 ≤1 槽位」。
- **根因**：别名数据（S21R 侧）与执法守卫（S63/S83 侧）两件套中间无 injectivity 锁。
- **最小修法**：装载 `@aliases` 加单射守卫——同一模板内任一别名串命中 >1 槽位 ⇒ `SchemaError`（与既有
  「指向未在册槽位即红」同源同形）。
- **影响面**：`sdd-ledger` 类全部页的节集合/节序判定——其账面「干净」可能含被别名吞掉的残余。
- **证据命令**：`grep -n "@aliases" docs/templates/sdd-ledger.md`（看 `清单` 出现于两槽位行）。
- **现状**：**未修**（本席交卷时 `docs/templates/**` 为 S83 在飞面，按独占纪律不代改）。归属：S21R（别名数据）
  ＋ S63/S83（`_match_slot` 守卫）。
- **涉集中面**：否。

### P1-22 creation 协议两把奇偶锁把「中央壳不可导入」吞成 `pytest.skip`，迁飞期永不为红（B02）

- **级别**：P1（S80 判 Important；形态正是 `tests/test_prepared_adapter_canary.py` 自己写下并批评过的
  「`pytest.skip` 静默变哑（不是红）」）
- **位置**：`tests/test_creation_job_protocol.py::_cp`、`tests/test_creation_protocol_parity.py::_cp`（中央壳的惰性导入口，两处同名）
- **现象**：跳过理由「中央 capability_protocols 当前不可导入（他席在飞）」——而该文件此刻正被归位批搬迁
  （S14/S87 面）⇒ 搬迁期间这两把「creation 协议 ↔ 中央壳」奇偶锁不报红，协议对齐绿灯与被迁真身无关。
- **根因**：为他席在飞期间保全量绿，选择整把锁 skip，而非「不执法显式挂账＋恢复条件」的明账。
- **最小修法**：skip 收窄为「显式认定在飞面」且必须留账——被跳过的锁输出一行「本腿今日不执法＋理由＋恢复条件」；
  恢复条件满足而未摘 skip ⇒ 红；或改 `xfail(strict=False)` 并配「归位批交卷即摘牌」的坐标锁。
- **影响面**：AI 绘画/语音两枚 `creation.*` 协议的奇偶性——恰是本波 mandate 明言「预留接口协议」的两面。
- **证据命令**：`grep -n "pytest.skip" tests/test_creation_job_protocol.py tests/test_creation_protocol_parity.py`
- **现状**：未修（登记；两测试件非本席面，不代改）。
- **涉集中面**：否（两测试件）。

## 丙、开口项 · P2（结构 / 口径 / 不执法类，整理波批量处理）

### P2-14 `G_P1_EXEMPT` 声明与判据形状不匹配，且无条数上限 / stale 锁（B10）
- **级别**：P2 **位置**：`plugins/bot_unified_runtime/domains/core/board_placement.py`（`G_P1_EXEMPT` 三元组声明）
  × `scripts/physical_placement_census.py`（按 `(fid, path)` 组装查询侧；本席现算两处均在盘）
- **现象**：S70 判「形状不匹配——要么 compute 侧传裸路径集合、要么判据按 `(fid, path)` 查」；同缺 G_P2 豁免所配的
  「条数上限 + stale 锁」⇒ 将来塞错形状的豁免条目会**静默不命中**而非响亮红。本席复核豁免条目数见当席现算输出（当时值：0），
  今日生产不可达（不以「现值为空」当「无洞」）。
- **现状**：未修（登记）。**判据**：与 G_P2 同构补上限 + stale 锁；注毒＝塞一枚错形状豁免 ⇒ census 必响亮判红。
  **涉集中面**：否。

### P2-15 「两语义未认领之差」断言恒真（装饰性锁）（B10）
- **级别**：P2（S70 原话：否则删掉这句、别留装饰） **位置**：`tests/test_physical_placement_gate.py::test_g_p2_exemptions_are_literal_existing_and_still_needed`
  （本席现算确认：`assert 0 <= gap <= len(universe)`）
- **现象**：`gap` 按构造恒 ≥0 且 ≤ 扫描面大小 ⇒ 该断言永不红，给读表人「口径已被检查」的错觉。
- **现状**：未修（门本体属禁写面 ⇒ 交该门 owner；本席不动）。**判据**：换真锁（例 `gap <= 0.8 × universe`
  或与 G-P2 语义B 上限挂钩），注毒＝人为放大两语义分叉 ⇒ 必红。**涉集中面**：否。

### P2-16 G-C1 缺快照龄锁；解析器把「拿不到整数的在飞数」丢行而非记违规（B10）
- **级别**：P2 **位置**：`tests/test_dispatch_saturation_gate.py`（补派日志表解析腿与快照消费腿；门本体禁写 ⇒ 交回 owner）
- **现象**：两条（S70 原案）——①快照 `captured_at` 无「龄 > k × 窗口 ⇒ 红」约束，陈旧快照可过形状腿；
  ②「在飞数」解析不出整数（汉字顶替即触发）时该**行被丢弃**，不计违规；行数地板只防整表删空、防不了逐行免责。
- **现状**：未修。**判据**：①加龄锁；②解析失败改记「违规行」；注毒＝某行在飞数写成汉字 ⇒ 门必红（现静默跳行）。
  **涉集中面**：否。

### P2-17 面A / 面B 缺「扫到 N 行」地板：尺子空扫与零违规同形（B10）
- **级别**：P2（S70 判「登记不施工」） **位置**：`scripts/spec_gates_census.py`（两本账的取数腿）；判据真身
  `scripts/doc_fact_discipline.py`
- **现象**：两腿只报违规数，不报「看过多少页/行」⇒「扫到零行」类输出与「零违规」一模一样（台账 #46
  「存在性糊过活性」同型；S70 要求给分母再谈零）。
- **现状**：未修（登记；取数口为 S78 在飞面，不代改）。**判据**：每腿输出扫描页数/行数并配地板断言
  （地板只准升不准降）；注毒＝把扫描面喂空 ⇒ 地板腿必红。**涉集中面**：否。

### P2-18 `_BASELINE_CARRIER_TRUTH` 地板 × 「只降不升」＝结构性死锁，该腿今日不执法（B10）
- **级别**：P2 **位置**：`tests/test_doc_link_integrity.py`（该常量为 FLOOR，件内注释自陈）
- **现象**：地板（当时值 5）远低于实值（S80 当时现算 34，现役数以该门现算为准），余量（当时值 29）使断言
  永不触边；收紧需抬地板，而「只降不升」常令禁抬 ⇒ S80 判「该腿永不再执法」。本席按铁律 10 不手写现值。
- **现状**：未修（归门 owner：要么把地板**随迁下调**到末次核账值，要么把该腿换成「载体列与注册表现算相等」
  的真判据）。**判据**：随迁后注毒＝抽掉一枚载体命中 ⇒ 必红。**涉集中面**：否。

### P2-19 `compare_projection` 对「同一份文本自比」仍回 `K_FORMAT` 残差标签，契约仅靠用例注释防误用（B10）
- **级别**：P2 **位置**：`scripts/doc_ownership_sync.py::compare_projection`
- **现象**：S88 契约发现——该函数假定「调用方已证字节不等」，条目级全平时同文本入参仍产出一枚 `K_FORMAT`；
  判「是否同步」的唯一落点是 `check_sync`。现把契约原样写进了用例注释并断言残差形态（将来谁把 K_FORMAT 改成
  「真报警」会被该用例点名），但函数签名层无防御。
- **现状**：登记·口径已被用例钉住（S88 自评「非缺陷」；代码面未改）。**判据**：函数改名为「残差标注器」或
  入参相等时显式抛错；注毒＝以同文本直调并期望空列表 ⇒ 必红。**涉集中面**：否。

## 本块小结（按分级计数，来源＝上方条目）

已闭环·归属明确若干（甲组）｜P1 开口（P1-21…P1-22）｜P2 登记（P2-14…P2-19），各枚数以本块上方编号标题现算为准。
未取证项：无（甲-1 与 P1-21/P1-22/P2-14/P2-15 的坐标由本席现算复核；P2-16/P2-17/P2-18 沿 S70/S80 席结论、
其门体判据行未逐行复核，标「席位结论·本席未复核细节」）。SEAT-S94 未交卷 ⇒ 其点名缺陷本块不记，防二手转述失真。
