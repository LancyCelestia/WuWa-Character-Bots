# 代码质量与结构审计发现台账（2026-09-21）

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

只读扫描：`plugins/bot_unified_runtime/` 全树 651 个 `.py`，其中非垫片真身 490 个
（判据=文件头 2500 字符内不含 `Compat shim|re-export|兼容再导出|再导出`）；AST 扫
公开符号碰撞（48 组同名异构）、模块级可变全局、吞异常、缺 docstring；`tests/`
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
- **能杀行为的验收判据**：新增 `tests/test_outbound_redaction_choke.py`——
  造一条 `text_fallback` 含 `C:\Users\LancyCelestia\x.png`、`BOT_OPENAI_API_KEY=sk-abc`
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
  `gate` 经 `runtime/service_wiring.py` 注入（`__init__.py` 的四处由主会话串行改）；
  ②`build_outbound_gate_settings` 的读点登记进 `_RUNTIME_HOT_OVERRIDE_FIELDS`
  （或维持重启口径、把注释里的「可热改」措辞按 #47 先例改口）；
  ③缺省值 `False→True` **不在本波做**，进表③交用户裁。
- **能杀行为的验收判据**：扩展 `tests/test_outbound_gate.py`：参数化六个 producer，
  在安静时间窗内跑一轮，断言回执为 DEFERRED（`deliver_after` 指向窗口结束）且
  `send_requests` 表里不出现窗口内的发送记录；同一主体连投 3 条断言第 3 条 SKIPPED。
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

## P1-1 根 `__init__.py` = 9163 行、`_register_nonebot_handlers` 单函数 5390 行（B02）

- **现象**：装配层上帝文件，所有域的 matcher、调度器、旁路（错误卡、校园、摘要、
  称谓）集中一处；函数级 `>200 行` 三处（`_register_nonebot_handlers` 5390、
  `_incoming_from_nonebot_event` 229、`_register_emergency_info_scheduler` 205）。
  并且被**行号棘轮**锁死：`test_outbound_registry_campus_coordinate_is_live` 现为全量
  唯一红（登记 5027 ≠ 活体 5032），任何人改根文件都会撞红。
- **根因**：NoneBot matcher 必须在插件顶层注册 + 历次波次为「不顶漂坐标」刻意用
  纯插入写法（#47 第⑩项、U17 均如此声明），把行号当契约。
- **最小修法**：分域外迁到 `domains/<域>/service/wiring.py`（每域一个
  `register_x(matcherRegistrar, deps)`），根文件只留一张调用表（≤200 行）；
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

- **现象**：`domains/chat_reply/llm_engine/usage_service.py`（1634 行）自带
  `ChargeLine / Settlement / PriceRevision / UsageQuote / UsageAttempt / money_str /
  normalize_channel / resolve_price / quote_usage`，与同目录 `billing_entities.py` +
  `billing_pricing.py` + `billing_service.py` + `pricing.py` 共 5 件、同名但 AST 不等价
  （`quote_usage` 27441 vs 40859）；两者互不 import，各有测试
  （`test_billing_service_v21.py` / `tests/test_usage_billing_v2`（拟建）→ 实为 `test_usage_billing_v21.py`），
  且**包外零 import 消费者**（全仓 grep 仅命中彼此、注释、两个测试）。生产账单真身
  是 `llm_engine/ledger.py`。
- **根因**：V2.1 计费 M1 规格由两波各自实现，未接线也未删；`creation/_common/contracts.py`
  注释里把 `llm/billing_entities.py` 写成「计费权威实现」→ 文档与代码互相指认。
- **最小修法**：定 `billing_*` 为唯一真身，`usage_service` 复用其 DTO（删除重复定义）；
  若 M1 仍未上线，则整族在板块卡上诚实标 `reserved` + 零消费者，并把 5 件并成
  `entities/pricing/service` 3 件。
- **验收判据**：新门 `tests/test_llm_billing_symbol_uniqueness`（拟建）（AST 扫
  `domains/chat_reply/llm_engine/` 与 `domains/creation/*/contracts.py` 顶层同名
  class/function 命中数 == 1）；注毒：把任一 DTO 复制进另一文件 → 红。
- **涉集中面**：否（不碰 config/生成物）。

## P1-4 事件存储两套真身，异常各一颗（B09）

- **现象**：`control_plane/events.py:RuntimeEventBus`（472 行，自开 sqlite、
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

- **现象**：`scripts/runtime_layout_smoke.py` 的 14 条检查全在 runtime 数据/资产/
  字节码面，**没有一条**管代码落点。实测漂移：真身落在旧根层
  `sources/acg_search.py`（473 行）、`sources/search_intent.py`（314 行）；17 个
  域根裸 `.py`（`render/reviewer.py`、`schedule/delivery.py`、`media/digest.py` 等）；
  21 个未在规范 §一.2 登记的层名（`pipeline` `llm_engine` `api` `projection`
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
- **验收判据**：门上线首跑即红 ⇒ 按现况写白名单（把 2 个真身 + 17 裸文件 + 21 层名
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

- **现象**：`tests/test_kb_wiki_retriever_wiring.py` 三条用例合计 0 条行为断言——
  只查 `providers.py` 文本里有没有 kb_wiki 字样、模块符号 callable、导入路径可解析。
  同一链路真身 `domains/chat_reply/character/vector_knowledge.py`（3098 行）含 12 处
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

- **现象**：`build_wbi_signed_url` 在 `platforms_bilibili.py`(2598) 与 `parsers/wbi.py`(1654)
  各一份且不等价；`build_request_headers` 在 `parsers/context.py`(1264) 与
  `parsers/http_util.py`(2478) 各一份（两者互 import，即 WP1 凭证咽喉与旧 headers
  并存）；6 个 `parse_<平台>`（kurobbs/miyoushe/skland/xiaoheihe/mihuashi/huajia）在
  `platforms_generic.py` 与专属平台文件同名并存。
- **根因**：专属解析器逐批改、generic 兜底未回收；WP1 的
  `scrub_credentials_for_target` 落在 http_util 但旧 context 侧未退役。
- **最小修法**：wbi 单真身（generic/bilibili 改调用）；`context.build_request_headers`
  降为再导出并让 `credentials_allowed_for_target` 成为唯一判据；generic 侧 6 个
  同名函数改名 `_*_fallback` 或按现有分发删除。
- **验收判据**：parsers 回归族（`test_parsers_batch_a/a2` + WP1 凭证门）+ 新 AST
  唯一性门（同名 `build_*`/`parse_*` 顶层命中数 == 1，`parse_*_fallback` 白名单）；
  注毒：删 wbi 真身的 UA 头 ⇒ bilibili 403 用例红（当前若走的是第二份则不会红 =
  正证哪份活着）。
- **涉集中面**：否。

## P1-10 中央调度信封与业务 handler 混写一处（WP8 Wave 1–4 挂账，B02）

- **现象**：`runtime/capability_protocols.py` 1984 行同时承载契约
  （`InvocationResult/CapabilityRequest/枚举`）、三颗注册表、共享线程池全局
  `_EXECUTOR`，以及 media/link_parse/search 各域的**具体 handler**
  （`_handle_media_vision_image`、`_handle_media_ocr`、`_handle_media_anime_ip`、
  `_make_asr_handler`、`_handle_media_video_recognize`、`_handle_media_video_subtitle`）。
  这正是用户所说「所有东西全混在一起」的最痛点。handler 本身是转调域真身
  （非第二真身），但落点错位。
- **根因**：#47 WP8 只做了 Wave 0（两个 `CapabilityResult` 分层归并），Wave 1–4 挂账。
- **最小修法**：契约 → `domains/core/contracts/dispatch`（拟建）；注册表+invoker →
  `domains/core/dispatch/`；各 `_handle_*` 迁回所属域 `capabilities/`，中央件只按
  descriptor 查表。旧路径 `runtime/capability_protocols.py` 留垫片。
- **验收判据**：`tests/test_capability_result_unique.py` 扩为「dispatch 契约件内
  零域专属 handler 符号」AST 门；新文件行数上限门（>800 行须注释理由，规范 §七.1）；
  注毒：在中央件里再加一个 `_handle_xxx` → 门红。
- **涉集中面**：部分（Wave 1–4 属用户已挂账的裁定波）。

## P1-11 import 期跨文件改写同一个全局 dict + 墓碑常量（B06/B07）

- **现象**：`domains/subscribe/adapters/{bilibili_adapter,social_v2,xiaohongshu_adapter,music_v2}.py`
  四个模块在 import 期各自 `ADAPTERS[...] = ...`，注册表分散、依赖 import 顺序、
  无锁；`adapters/music_v2.py` 还留 `_REMOVED_PLATFORM_LABELS`（规范 §七.5
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
  确需可变异步写者包一层 `domains/core/caches.py:TtlCache`（内部持锁）。
- **验收判据**：并发锁测试（8 线程 × 200 次读写同 key：无异常、无半条记录、
  `len(cache)` 单调）；注毒：去掉锁改裸 dict ⇒ flaky 必现红；AST 门禁止
  模块级 `NAME = {}` 被同文件函数写入且文件内无 `Lock()`（存量白名单只减不增）。
- **涉集中面**：否。
