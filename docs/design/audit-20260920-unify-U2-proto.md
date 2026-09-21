# 20260920 统一收尾波 · U2-PROTO 协议契约统一审计（只读席位日志）

> **席位**：U2-PROTO（协议契约统一）。性质=只读审计，零代码/配置改动，零 git 写操作。
> **时点**：2026-09-20 下午（本席全部命令实跑输出贴录于文末附录；行号=本席快照，漂移时用各条「锚点字符串」重定位）。
> **对象**：`plugins/bot_unified_runtime/` 协议契约面——S10 描述符总册、垫片/僵尸引用、CapabilityResult 双契约、RouteKind 事实源、contracts/ 边界、传输适配器协议、控制面信封、版本化位。
> **必读前作**：`docs/design/audit-20260919-unify-wave.md`（P0-2 本席复核见 §二）、`HANDOFF-V21R5-20260920.md` §三 C/D/F。
> **纪律声明**：本席所有 python/pytest/mypy 均带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`、pytest 带 `--basetemp=$TEMP/u2-audit-9f3a1c -p no:cacheprovider`、mypy 带 `--cache-dir $TEMP/mypy-u2-audit`（均在源码树外）。树卫生自查见 §十。

---

## 〇、方法与环境

- 解释器：`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`（Python 3.12.10，实跑确认）。
- 一次性枚举脚本（落 `$TEMP`，树外）：
  - `u2_enum.py`——S10 全表 22 描述符逐条核验 implementation_ref 文件存在 + `#` 锚点符号存在 + handler/fallback/health_probe 注册对称 + `config_keys` 与 config.py（617 字段）交叉比对 + `validate_registry()` 全量执行；全树 83 个 "Compat shim" 垫片 → `_CANONICAL`/星导入真身存在性核验；「垫片挂起/维持旧路径/RET2B」注释锚点全树扫描。
  - `u2_g1.py`——AST 全树 `CapabilityResult(` 构造点 204 处逐字段频次统计；全树同名类定义聚类（双契约候选清单）。
- scoped 测试实跑：`tests/test_v21_s10_protocols.py tests/test_outbound_v21.py tests/test_capability_registry.py` → **136 passed / 1 skipped in 6.49s**（输出见附录 A1）。
- scoped mypy 实跑：`runtime/capability_protocols.py` → **1 error（:1273 attr-defined）**（附录 A2）。

---

## 一、S10 描述符总册全表核验（任务项 1）

**总表清单（22 条，脚本输出原样贴录）**：族分布 creation 2 / files 8 / media 8 / search 4；`validate_registry()` 返回 `[]`（通过）。

| capability_id | ref 文件 | 锚点符号 | handler | probe | fallback |
|---|---|---|---|---|---|
| creation.image.generate | EXISTS | **MISSING**(`#reserved`) | 无(设计) | OK | honest_degrade |
| creation.tts.synthesize | EXISTS | **MISSING**(`#reserved`) | 无(设计) | OK | honest_degrade |
| files.artifact.generate | EXISTS | OK | OK | 无probe | honest_degrade |
| files.read.{word,ppt,excel,pdf,code,markdown,latex} ×7 | EXISTS | OK | OK | 无probe | honest_degrade |
| media.asr.{audio_file,speech} ×2 | EXISTS | OK | OK | OK | honest_degrade |
| media.video.{frame_extract,recognize,subtitle} ×3 | EXISTS | OK | OK | frame_extract/subtitle 无probe | honest_degrade |
| media.vision.{anime_ip,image,ocr} ×3 | EXISTS | OK | OK | OK | anime_ip=fb:OK+honest_degrade |
| search.acg | EXISTS | OK | OK | OK | honest_degrade |
| search.reference.fetch | EXISTS | OK | OK | 无probe | honest_degrade |
| search.unified | EXISTS | OK | OK | OK | honest_degrade |
| search.web | EXISTS | OK | OK | OK | honest_degrade |

**无缺陷项明写**：①implementation_ref 22/22 文件真实存在（含 `search.web→domains/core/search/web_search.py`、`search.acg→sources/acg_search.py`——后者「真身未迁」口径与 descriptor notes 相符）；②无重复注册（`CapabilityRegistry.register` id 唯一即拦 + 全表无撞）；③handler/描述符对称：孤儿 handler=0，无 handler 仅 creation 两席（设计内诚实 unavailable）；④descriptor 的 `config_keys` 全部在 config.py 有对应字段（含 `bot_tts_enabled`），零漏登；⑤`search.unified`/`search.reference.fetch` 的 implementation_ref 已指 canonical（`:1650` 行注释「sources/search_service.py 垫片已退役」与实况相符——该文件确不存在）。

---

## 二、09-19 审计 P0-2 复核：web_search 僵尸引用仍在（任务项 2）——**未修复，且垫片已删后性质升级**

### U2-P0-1｜P0｜`plugins/bot_unified_runtime/runtime/capability_protocols.py:1273-1275`

- **锚点**：`from plugins.bot_unified_runtime.sources import (` + `web_search,  # RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径`（位于 `_WebChainAsSearchProvider.search()`）。
- **根因**：09-19 P0-2 给出方案 A/B 后，v21r4-B 主代理席按「垫片退役+消费方归 canonical」路线执行——`sources/web_search.py` 垫片**已删除**（实测不存在），`_web_provider_or_none`（现 :1128）已改指 `domains.core.search`，**但 `_WebChainAsSearchProvider.search()` 内这一处包级 from-import 漏改**（RET2b-R 日志自认「包级 from-import 盲区：连续串匹配不到」，单列修了 4 处，此处是第 5 处漏网——它在函数体内且带行内注释尾）。注释仍谎称「垫片挂起，维持旧路径」=**僵尸引用+假承诺注释**双重违规。
- **证据**（全部本席实跑）：
  - 文件不存在：`ls sources/` 无 `web_search.py`（目录清单贴附录 A3）。
  - mypy 常驻红：`capability_protocols.py:1273: error: Module "plugins.bot_unified_runtime.sources" has no attribute "web_search" [attr-defined]`（附录 A2）——dev.ps1 typecheck 含此文件，**四门禁之一因此不可能全绿**。
  - 运行期探针（附录 A4）：`from plugins.bot_unified_runtime.sources import web_search` → `ImportError: cannot import name 'web_search' from '…sources'`；`_WebChainAsSearchProvider(_FakeProvider()).search(...)` → **当场同型 ImportError**。
  - 传播路径：`search.unified` invoke（无注入 providers）→ `_handle_search_unified:1230` 构造本适配器 → `service.search()` 回调 `adapter.search()` → ImportError 抛出（`self._provider.search` 的 try 在 import **之后**）→ 被 invoker 捕获 → 走降级链 → **表面「degraded」静默、实际是 ImportError 伪装成功能降级**——正撞 HANDOFF §四.9「字符串/函数内 import 是 AST 扫描盲区」同族第三例。
  - 生产爆炸半径如实：S10 invoker 现无生产消费者（见 U2-P1-2），故为「W7 上车即炸」地雷而非现网事故；门禁红是当下真实代价。
- **改法**（与 :1128 同款，最小改动）：
  ```python
  # before（:1272-1275）
  from plugins.bot_unified_runtime.domains.core.search import search_service
  from plugins.bot_unified_runtime.sources import (
      web_search,  # RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径
  )
  # after（垫片已退役，注释同步销毁；web_search 在此仅用于 :1287 的 __name__ 串，可直接用模块路径字面量）
  from plugins.bot_unified_runtime.domains.core.search import search_service, web_search
  ```
  （或删该 import，把 `:1287` 的 `f"web_chain:{web_search.__name__}"` 改为固定串 `"web_chain"`——后者更短且去除残余依赖。）
- **验证**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m mypy --cache-dir $TEMP/mypy-fix --explicit-package-bases --ignore-missing-imports plugins/bot_unified_runtime/runtime/capability_protocols.py` → 0 error；scoped pytest（§〇 三件）→ 全绿；`grep -rn "sources import web_search\|sources\.web_search" plugins/ tests/ scripts/` → 零命中（本席现状：仅此 1 命中，文档/日志历史件不计）。
- **回归锁现状**：descriptor 完整性门（test_v21_s10_protocols）只查 implementation_ref，**查不到函数体内僵尸 import**——本条即教训；建议加 AST 门（见收口清单第 3 条）。

### 「注释承诺垫片但垫片未落盘」全树扫描：同族**真地雷仅此 1 例**

- 扫描面：全树 `垫片挂起|维持旧路径|RET2B` 注释共 3 处——
  1. `capability_protocols.py:1274`（本条，假承诺）；
  2. `capability_protocols.py:1650`「sources/search_service.py 垫片已退役」——**与实存相符**（文件确已删、ref 已 canonical）＝诚实注记，非缺陷；
  3. `output/card_render/usage_cards.py:6`「theme_tokens 转发——维持旧路径可见面不变」——usage_cards.py 垫片文件**实存在**＝诚实。
- 反向核验（垫片→真身方向）：全树 83 个 "Compat shim" 文件，`_CANONICAL`/星导入目标存在性 **0 坏垫片**（附录 A5）。
- 挂起 4 张垫片实存核对（HANDOFF §D 声明 vs 磁盘）：`contracts/media.py`(615B)✓、`config_readiness.py`(631B)✓、`decision/trace.py`✓、`capabilities/debug.py`(605B)✓——**声明与实存一致**；已退役三张 `contracts/runtime.py`、`decision/outbound.py`、`sources/web_search.py` 确已不在（MISSING=符合退役声明）。

---

## 三、运行期协议 vs 声明期协议（任务项 3）

### U2-P1-5｜P1｜`CapabilityResult` 同名双契约（两套严格 DTO 并行，零桥接）

- **坐标**：`domains/core/contracts/runtime.py:226`（pipeline 契约，25 字段）vs `runtime/capability_protocols.py:151`（S10 契约，7 字段）。
- **根因**：S10 席「协议壳」独立造了一份受控调用结果模型，与基层管线既有同名模型并存；两族字段（status/data/detail/via/attempts vs kind/body/summary/…）零交集语义，仅类名相同。全树 `grep class CapabilityResult` 命中 2 处定义 + 生产 204 构造点**全部**用 contracts 版，S10 版仅 capability_protocols 自身 `_result()` 1 处。
- **证据**：AST 统计（附录 A6）——构造点分布 `__init__.py:30`、today_history:16、divination:14、music:11…；S10 版构造点=1。
- **改法**：before=两同名类并存 → after=①S10 版更名 `InvocationOutcome`（文件内 12 处引用，零外消费者，改名成本极低）；或②并入 contracts 单一信封并保留 status/via 语义。任何一案都要求 `docs/design/backend-v2-implementation-guide.md` §6 同步口径。
- **验证**：`grep -rn "class CapabilityResult" plugins/` 只剩 1 处；scoped 三件测试绿。

### U2-P1-3｜P1｜pipeline 契约字段卫生：死字段 + `kind` 自由串双词表

- **坐标**：`domains/core/contracts/runtime.py:226-255`。
- **证据**（204 构造点逐字段频次，附录 A6）：`capability_id/request_id/kind/audit_tags/body` 构造率 ≥97%；`summary` 1 次、`url` 3、`audio` 3、`video` 2、`source` 2、`files` 3、`prefix_parts` 1、`text_parts` 1；**`actions` 0 次构造、`source_timestamp` 0 次构造且全树零读者（`grep "source_timestamp\|private_recommended"` 除定义外 0 命中）、`private_recommended` 0 构造 0 读**。
- **kind 词表失控**：`kind: str` 无枚举。同一名串承载两种词表——内容形态（text/mixed/post/video/page/music/article/user/live/goods/tarot/wiki/tweet…，附录 A7）与**故障类别**（provider_error:10/config_missing:7/timeout:5/network:4/auth/rate_limited…）；消费侧各自硬编码集合：`__init__.py:474` `kind in {"auth","timeout","network","rate_limited","config_missing"}`、`domains/render/card_render/bridge.py:584/589/920/926/1026` 五处 `kind in {…}` 内容集合——**新增 kind 无门可拦**，两处 allow-list 与生产构造值集零机器比对。
- **上层手工补字段检查（如实反向）**：能力返回后对 CapabilityResult 做 `model_copy(update=…)` 补字段的生产点=**0**（grep 实跑：命中仅 receipt.model_copy 遮 public_message×3、config.model_copy、synthetic `message.model_copy` 若干——均非给结果补契约字段）。**该项无缺陷，明写。**
- **改法**：kind 拆 `kind`（内容形态枚举，renderer 词表为初始集）+ `error_kind`（故障枚举，:474 集合为初始集），或最低限度加常驻门：`{构造点 kind 字面量全集} ⊆ 声明词表`；死字段：删除 `actions/source_timestamp/private_recommended` 或进「契约保留位」登记（附消费路线图），禁裸删不登记。
- **验证**：新门前 `dev.ps1 -Task test` 全量绿；改后 scoped 渲染契约测试 `tests/test_rendering_contract.py`。

---

## 四、RouteKind 单一事实源（任务项 4）

**实证通过项（明写）**：
- 枚举唯一定义：`domains/chat_reply/runtime/base_router.py:99`（34 成员）；旧路径 `runtime/base_router.py`(668B) 为 PEP 562 活转发垫片（真身在位✓）。
- **判定序归一实证成立**：`classify_message_route` 对 `ROUTE_RULES` 每次按 `priority` 稳定排序（:723，T-Spec T2 注释钉死），同值先到先得书写序；根 `__init__.py` 全部生产 matcher 谓词均 `_cached_route_decision(…).kind is RouteKind.X`（6016-6130 族），**同 priority=41 的十余 block=True matcher 因 kind 互斥无注册顺序依赖**——台账 #26「判定序按 priority 归一」现状复核=真。
- Keystone 三源一致有常驻锁：`capability_registry.py`（542 行权威声明表）↔ base_router 字面四表 ↔ echo 帮助主题，`tests/test_capability_registry.py` 本席实跑通过（含于 136P）。
- decision 影子引擎复用同一 RouteKind（`domains/core/decision/engine.py:40` import，无平行枚举）。

### U2-P2-8｜P2｜绕过面一：alias 链 capability_id 字符串分发无机器锁（事故先例在案）

- **坐标**：`__init__.py:6142-6260`（`_handle_alias` 的 `elif resolution.capability_id == "bot.help"/"bot.weather"/…` 字符串 elif 链）+ `domains/chat_reply/runtime/aliases.py:104-` （动词→capability_id 字面量表）。
- **根因**：Keystone 锁覆盖 RouteRule/枚举/help，**不锁** alias 解析值域与 elif 分支集的字面同源；分支持集靠人肉对齐。
- **证据**：`__init__.py:6228-6229` 注释自认历史事故——「F9：别名链此前无 bot.news 分支，『守岸人 AI新闻』坠 help」＝漂移已实际发生一次；本席 grep：`test_capability_registry.py` 中 `bot.news` 仅出现在 RouteRule 锁（:97），无 aliases 值域/elif 分支覆盖断言。
- **改法**：新增门（并入 test_capability_registry 或 route-matrix 族）：`{aliases.py 映射值 ∪ elif 链字符串} ⊆ {ROUTE_CAPABILITY_DECLARATIONS.capability_id} ∪ {bot.help,bot.status,bot.why}`，且对 value 域内每个 id 断言 elif 链存在对应分支（AST 提取字符串比较）。
- **验证**：`pytest tests/test_capability_registry.py`（加锁后）红→补分支→绿。

### U2-P2-8b｜P2（与上条并案）｜绕过面二：`outbound_registry.route_kind_hint: str` 自由文本列

- **坐标**：`domains/core/decision/outbound_registry.py:342`（注释自认「功能名提示；精确 RouteKind 以 base_router ROUTE_RULES 为准」）。登记性质=提示列非契约，但无 `value ∈ RouteKind` 校验器；修法=表加载时一次性断言（hint 非空即须可 `RouteKind(...)`）。低危，随收口清单第 5 条处理。

---

## 五、contracts/ 目录与双类型名案例（任务项 5）

**owner 边界现状（核验合格项明写）**：canonical 契约唯一正源=`domains/core/contracts/`（envelope/errors/character/media/music/request/runtime/auto_send/finance/subscription + `__init__` 全量再导出）；旧 `contracts/` 仅剩包级 `__init__.py` + `media.py` 两张活转发垫片（挂起队列在册、解除条件明确，§二已核验 4 张挂起垫片实存一致）。`sources/__init__.py` 已收敛为纯 re-export（仅 ParserRegistry/ParserRule/SourceInput 三名），不再遮蔽任何真身。

**「同一概念两个类型名」全树 AST 聚类清单**（附录 A8 原样输出）：

| # | 概念 | 两份定义 | 定性 |
|---|---|---|---|
| 1 | 能力调用结果 | `contracts/runtime.py:226 CapabilityResult` vs `capability_protocols.py:151 CapabilityResult` | 缺陷 U2-P1-5（上文） |
| 2 | API 信封 | `control_plane/api/protocol.py:73 ApiEnvelope/:57 ResponseMeta` vs `contracts/envelope.py:113/:72` | 缺陷 U2-P2-7（§七） |
| 3 | 计费实体 12 类 | `llm_engine/usage_service.py` vs `llm_engine/billing_entities.py` | 缺陷 U2-P1-6（下条） |
| 4 | 占卜落库 | `divination/store/draw_store.py` vs `divination/data/draw_store.py`（DrawStore/DrawError/SeededPrng/HmacPrng 各双份；DECK_REVISION/FORTUNE_RULE_VERSION 另散 4 文件） | 缺陷 U2-P1-4（下条） |
| 5 | 搜索命中 | `contracts/character.py:223 WebSearchHit` vs `domains/core/search/web_search.py:63 WebSearchHit` | P3 登记（provider 传输模型 vs 契约，v21r2-search-log 自认有意；但「字段同形」无门——建议加结构等价断言） |
| 6 | SSE 游标异常 | `control_plane/events.py:218/224 CursorExpired/EventStoreUnavailable` vs `domains/ops/monitor/event_store.py:380/388` | P3：两份异常类分属两包，跨层 catch 互认失效风险；建议单源 re-export |
| 7 | Win32 结构/Dispatcher | `supervisor/job_objects.py` vs `windows_sandbox.py`（同名 ctypes 结构×2）；`control_plane/dispatcher.py:39` vs `decision/dispatcher.py:41`（同名异概念） | P3 登记：ctypes 双抄可合并；Dispatcher 属撞名非双契约 |

### U2-P1-4｜P1｜占卜双 DrawStore：生产命令链与 API 面各用一份（且生产不持久化）

- **锚点**：`domains/divination/capabilities/divination.py:40`（`from …divination.data.draw_store import DECK_REVISION, FORTUNE_RULE_VERSION, DrawError, SeededPrng, …`）vs `domains/divination/service/divination_service.py:60`、`api/facet.py:51`、`service/tarot_draw.py:28`、`control_plane/api/divination.py:47`（全部 import `…store.draw_store`）。
- **根因/实况**：两模块各含完整 DrawStore（sqlite 建表/落库）+同名异常与 PRNG；`store/` 版多一个 `_resolve_db_path`（路径解析语义已分叉）。生产接线：根 `__init__.py:4127` `build_divination_capability(config_, render_backend=…)` **不注入 draw_store**（能力文件 :443 自认「不注入=无持久化」）→ 聊天塔罗抽取**永不落库**；控制面 facet API `api/facet.py:338 store.DrawStore(db_path)` 另一份实现读写库——两消费面静默分叉。
- **证据**：构造点 grep 全树仅 facet.py:338 一处 `DrawStore(`；根 init `grep draw_store` 0 命中（附录 A9）。
- **改法**：裁定唯一真身（建议 `store/draw_store.py`=较新含路径解析版）→ `data/draw_store.py` 改纯 re-export 或退役、消费方归一；能力装配点显式注入（或产品裁定「塔罗不落库」并把另一份整个删掉）；两案都必须过 `test_v21_*divination*` 族 + 新加「单一定义」门。
- **验证**：`grep -rln "class DrawStore" plugins/` → 1；`pytest tests/ -k divination -q`（scoped，带基线参数）。

### U2-P1-6｜P1（定性=僵尸双契约，运行风险低但违背 mandate）｜计费 usage_service 12 类双写、生产零消费

- **锚点**：`domains/chat_reply/llm_engine/usage_service.py`（类 `ChargeLine/PriceComponent/PriceRevision/Settlement/UsageAttempt/UsageQuote/UsageSnapshot/…` 12 名与 `billing_entities.py` 逐一同名）；对照 `domains/creation/_common/contracts.py:16` 自述「那边（billing_entities）是 V2.1 计费权威实现」。
- **证据**：全树 grep——usage_service 的 plugin 内引用 0（仅 `llm/__init__.py:4` docstring 提点名，且系 PEP 562 包转发的泛指）；唯一消费者=`tests/test_usage_billing_v21.py`（136P 中不含它，本席未跑该件如实说明）。billing 生产链消费 `billing_entities`（billing_service.py:44 / billing_pricing.py:35）——**测试守着一份生产不用的契约实现**。
- **改法**：usage_service 并入 billing_entities（类型别名/导入替换），或将 test_usage_billing_v21 改打生产件后删 usage_service；决策点交主代理（涉及 S-billing 波归属）。
- **验证**：`grep -c "class " usage_service.py` 归零或文件删除；`pytest tests/test_usage_billing_v21.py tests/test_llm_ledger*.py -q` 绿。

### bridge.py 历史导出面（判读）

- `domains/render/card_render/bridge.py:59/:106`「兼容别名：跨模块历史导入面（templates.py/usage_cards.py/echo.py/debug.py）」+ `:414` `_derive_wash_tokens` 别名再导出——**历史导出面仍在制造双口径**（同一概念经 bridge 别名与 mica_shell 真身两个名字可达），但该域=前端波独占禁改面，本席只登记：**随 contracts.media 垫片退役同波收口**（解除条件已挂 HANDOFF §五：bridge.py:683 前端独占消费）。另 :683 `from plugins.bot_unified_runtime.contracts.media import ParsedContent` 走的正是挂起垫片旧路径——收口时同步改 canonical。

---

## 六、传输/适配器协议统一（任务项 6）

**统一合格面（明写）**：出站请求 schema 单一——`contracts/runtime.py:294 SendRequest`（StrictBaseModel），全树 8 个构造面（pipeline/queue/root init 族/alerts/error_report/smoke/campus/自身工厂）import 同一类，无平行 SendRequest 类；OneBot（`domains/transport/sender/onebot.py`）与 NoneBot 通用通道（`nonebot.py:329 send_nonebot_message(send_request: SendRequest) -> DeliveryReceipt`，状态用 ReceiptState 枚举 FAILED_FINAL/SKIPPED 等）共享同一 schema 与回执模型。TG 经 NoneBot 适配器走同一面。

### U2-P2-6｜P2｜队列三态（UNKNOWN/PARTIAL）游离于回执枚举之外——自认延迟修正在案

- **坐标/锚点**：`domains/transport/sender/queue.py:33-41`——`# §9.3 …（contracts/ 本轮禁改，无法新增 ReceiptState 枚举成员，故以裸字符串落库）`；`PARTIAL_ROW_STATE="partial"`、`PART_STATE_UNKNOWN="unknown"`。`receipts.py` grep UNKNOWN=0。
- **根因**：part 级幂等/断点续发协议在队列层用私有字符串词表实现，`ReceiptState`（ACCEPTED…FAILED_FINAL 9 值）无 UNKNOWN/PARTIAL——**声明期契约与运行期落库词表分叉**，跨层读队列行状态的任何消费者（运维视图/控制面）必须知道影子枚举。
- **改法**：contracts/runtime.py 增 `ReceiptState.UNKNOWN/PARTIAL`（或新 `PartState` 枚举），queue.py 裸串替换为枚举 value 引用；DB 无 schema 变化（本来就存字符串），零迁移风险。
- **验证**：`pytest tests/ -k "outbound or send_queue" -q` + `grep -n "PARTIAL_ROW_STATE" queue.py` 引用枚举化。

### U2-P2-9｜P2（登记性质=显式豁免缺口）｜Mail 通道不在统一出站协议内

- **证据**：`domains/transport/mail/mail_bridge.py:16` 自带 `MailCommand(action,account,recipient,subject,body)` dataclass 命令面（纯 stdlib，无 SendRequest/DeliveryReceipt/queue 引用——grep 0 命中）；根 init 邮件出站走 `MailBridgeState`+直接投递（:3599/:5839 `stage="mail_bridge"`）。→ 幂等/PARTIAL 断点/回执三态协议**只覆盖 OneBot/NoneBot 通道，Mail 零覆盖**。
- **改法**：二选一并留痕——①文档+注释显式豁免（SMTP 点对点即回执语义，入 `docs/design/backend-v2-implementation-guide.md` 协议面）；②邮件出站收编 queue（成本高，非本席裁定）。当前状态=两不沾，属 mandate 缺口。
- **验证**：`grep "SendRequest" domains/transport/mail/` → 命中（②案）或豁免注释在册（①案）。

---

## 七、控制面/WebUI 契约层与内部协议同源（任务项 7）

### U2-P2-7｜P2｜双信封 + 双 ID 格式 + 嵌套信封

- **坐标**：`control_plane/api/protocol.py:24 envelope()`/`:57 ResponseMeta`/`:73 ApiEnvelope` vs `domains/core/contracts/envelope.py:72 ResponseMeta`/`:113 ApiEnvelope`（AST 双定义实锤）。
- **实况修正**（对 envelope.py 文档口径）：protocol.py 已在 v21r2 S9 增补 `meta.trace_id`（:36）——envelope.py:14-19 docstring 仍宣称旧侧「meta 缺 trace_id、错误体缺 trace_id、无错误注册表」，**三项中 meta.trace_id 已失效**＝文档-代码漂移（P3 附随：修注释）。
- **仍真实的双写**：①信封构建器两份（`{data,error,meta}` 形状族）；②ID 生成格式分叉——protocol.py `new_request_id= req_<32hex>`（:17）vs contracts 两文件 `req_<12hex>`——同字段两种长度形态上同一根线；③服务层内信封叠外信封：`webui_stats.py:196/295/332` 返回 `{status,reason,data}`，端点再 `envelope(_stats_payload(result))`（`api/webui.py:59`）→ 线上形态 `data.data.*`（09-19 P0-1 测试断言 `payload["data"]["data"]["total_calls"]` 即其投影）；错误语义双轨：HTTP 422 `ControlPlaneError`（webui.py:37）与体内 `status:"invalid_request"/"source_unavailable"` 并存。④CapabilityResult/审计记录与信封零共享定义（各自 StrictBaseModel 独立演进）——`AuditRecord(contracts/runtime.py:356)` 无版本字段、与 control_plane/audit.py 表列各写一份（本席只列双写点，不强判缺陷）。
- **改法**：协议面收敛三步——(a) protocol.envelope 改为薄封装直调 contracts/envelope 构建器（或 DeprecationWarning 标记）；(b) ID 生成统一引 `contracts.envelope.new_request_id`（12hex 口径）；(c) webui 服务层去内 `{status,data}` 壳：状态入 meta/错误入 error，端点单封。
- **验证**：`pytest tests/test_webui_http.py tests/test_control_plane_v1.py -q`（信封形态测试族，scoped）+ OpenAPI schema 断言唯一 ApiEnvelope import 源。

---

## 七点五、能力注册表三轨并行（任务项 1/4 交叉，mandate 核心违背面）

### U2-P1-2｜P1｜S10 描述符总册 = 生产零消费者的死册；三套能力注册体系互不映射

- **坐标**：`runtime/capability_protocols.py:1838-1905`（default_invoker 装配面）；对照 `domains/chat_reply/runtime/capability_registry.py`（34 RouteKind 能力声明）与 `control_plane/features.py:82-`（FeatureDescriptor 能力树，capability_id 列）。
- **锚点**：`def default_invoker() -> CapabilityInvoker:`；`FeatureDescriptor("bot.plugin.weather", ... capability_id="bot.weather")`。
- **根因**：中央存在**三套平行注册表**且 id Namespace 互不相通：①S10 册 22 条 `family.name` 形态（media./files./search./creation.）；②生产路由册 34 条 `bot.*`（RouteKind 系）；③控制面 feature 树（`bot.plugin.*`，capability_id 指②的 `bot.*`）。生产 29+ 能力（weather/music/…/tts）在①中**零登记**；①的 22 条能力在②③中也无对应行——「中央按契约统一处理后分发」对①完全不成立。
- **证据**：grep 全 plugins/ 仅命中 capability_protocols.py 自引用（`default_invoker|CapabilityInvoker|capability_protocols import` 生产零消费者，附录 A11）；tests 侧消费者=test_v21_s10_protocols.py（册自身门）+ conftest/池卫生件（executor 收口）。矩阵口径佐证：`docs/design/backend-v2-acceptance-matrix.md` 相关行 wiring=not_wired/partial（v21r4-B MAT 席统计 wiring 17 not_wired）。
- **后果**：①册的 timeout/limits/roles/fallback/health 契约全部只在测试里生效；改任何 media/files/search 实现（如 transcribe/vision 签名变更）**不会**触发①册门红——描述符 input/output_protocol 串与实际 handler 形态无机器比对（`input_protocol="media.v1 VisionImageRequest{...}"` 是自由文本，validate 只查非空）。
- **改法**：三步定策（产品裁定先后）——(a) 定位裁决：①升格为唯一能力契约总册（则生产能力逐条迁入、`bot.*` 与 `family.name` 建立映射表并加锁）或降级为「V2.1 预留协议壳」（则在矩阵/指南中明示 not_wired，停止"统一契约"宣称）；(b) 无论何案，加常驻门：三册 capability_id 全集互查（差集须显式豁免登记）；(c) handler 入出参与 descriptor 串的最小结构断言（payload 必需键存在性）。
- **验证**：新门入 `tests/test_v21_s10_protocols.py`（或 test_capability_registry）后 scoped 红→登记豁免→绿。

---

## 八、协议版本化与陈旧字段（任务项 8）

- **有版本位**：`contracts/envelope.py` 与 `protocol.py` 信封 `schema_version:"v1"`（Literal 钉死）；LLM 账本 `raw_usage_schema_version` 列 + `billing_service.py:970 f"ledger_v{row['schema_ver']}"`（唯一实质迁移位）。
- **无版本位**：`CapabilityResult/SendRequest/DeliveryReceipt/AuditRecord/BotDecision/PolicyEvaluation`（contracts/runtime.py 全族）与 S10 `CapabilityResult` 均无 schema_version；版本标记以**自由串 ad-hoc 化**：`audit_tags=["pipeline_busy:v1"]`（pipeline.py:214）、descriptor `input_protocol="media.v1 …"` 前缀字符串（validate 只查非空不查形态）——跨波次加字段全靠 additive 默契（SendRequest.adapter/bot_id、IncomingMessage.reply_chain 均事后追加，无版本声明）。
- **陈旧字段消费方实况**（逐条查证）：`IncomingMessage.reply_to_text`——compat 别名（定义 :150），读方 2：`domains/media/capabilities/image_search.py:48`、写方 `__init__.py:1485`，非僵尸但**无 deprecation 计划位**；`source_timestamp/private_recommended/actions`——见 U2-P1-3（零构造或零读，死字段）；`contracts×8/control_plane×4…` 旧路径 import 22 点=RWC5-b 登记「真身未迁保留集」＝合法现状非缺陷。
- **改法**：contracts/runtime.py 全族加 `SCHEMA_VERSION: ClassVar[str]` + 序列化 meta 内嵌（或 envelope 层统一注入）；死字段/兼容别名进 `docs/design/backend-v2-implementation-guide.md` 的「保留位登记」节，禁未登记裸读旧字段。

---

## 九、结论与严重度分布

| 级别 | 条数 | 条目 |
|---|---|---|
| P0 | 1 | U2-P0-1 web_search 僵尸 import（mypy 常驻红+W7 上车即炸+假承诺注释） |
| P1 | 5 | U2-P1-2 S10 总册零生产消费者（三能力注册表并行）；U2-P1-3 pipeline 契约死字段+kind 双词表；U2-P1-4 占卜双 DrawStore+生产不持久化 vs API 单面 wired；U2-P1-5 双 CapabilityResult 同名；U2-P1-6 计费 usage_service 双模型（测试守僵尸实现） |
| P2 | 5 | U2-P2-6 ReceiptState/队列裸串；U2-P2-7 双信封+ID 格式分叉；U2-P2-8 alias 链无锁（8b route_kind_hint 并案）；U2-P2-9 Mail 协议外；U2-P2-10 contracts.media+bridge 历史面（挂起队列在途，登记性质） |
| P3 | 4 | creation `#reserved` 虚构锚点（门只查文件）；envelope.py 陈旧宣称注释；WebSearchHit/双 events 异常/ctypes 结构双抄登记项 |

**合格面明写（勿重复怀疑）**：S10 全表 22/22 ref 文件在位、validate_registry 空问题、注册对称零孤儿、config_keys 零漏登；RouteKind 单源+priority 判定序归一实证成立+Keystone 锁实测绿；「垫片假承诺」全树仅此 1 例、83 垫片→真身 0 坏、4 挂起垫片实存与声明一致；SendRequest 单 schema 无平行类；能力结果无上层补字段。

### 协议单一事实源收口清单（按解锁序）

1. 【无前提】U2-P0-1 一行改指 canonical（或删 import 改固定串）→ typecheck 归零；配套 AST 门：函数体内 `from …sources import <退役名>` 全树扫描入常驻（防第 6 例）。
2. 【无前提】usage_service↔billing_entities 归一（U2-P1-6）；占卜双 DrawStore 归一+生产注入裁定（U2-P1-4）。
3. 【无前提】S10 契约更名 `InvocationOutcome`；pipeline CapabilityResult 死字段登记或删（U2-P1-3/P1-5）。
4. 【contracts 解锁窗】ReceiptState 增 UNKNOWN/PARTIAL 或独立 PartState（U2-P2-6）；信封/ID 单源化三步（U2-P2-7）。
5. 【随批】alias 值域/elif 分支子集门（U2-P2-8）；route_kind_hint 校验；validate_registry 加锚点符号断言（P3-11）。
6. 【前端合流波】contracts.media 垫片退役 + bridge.py:683 改 canonical + bridge 历史别名面收编（U2-P2-10，HANDOFF 既定条件）。
7. 【产品裁定】Mail 出站收编或显式豁免登记（U2-P2-9）；S10 总册定位（生产接线 or 文档降级为「V2.1 预留协议壳」并在矩阵钉位）（U2-P1-2）。
8. 【常驻】全族 schema_version 位 + 保留位登记节（§八）。

---

## 十、树卫生自查

- 本席产物全部在源码树外：脚本/输出在 Git Bash `/tmp`（=`C:\Users\LANCYC~1\AppData\Local\Temp`），pytest `--basetemp=$TEMP/u2-audit-9f3a1c`，mypy `--cache-dir $TEMP/mypy-u2-audit`，全程 `PYTHONDONTWRITEBYTECODE=1`。
- 终检（`find plugins scripts tests docs bot.py` 多名字命中 0）：`plugins/ scripts/ tests/ docs/ bot.py` 内 `__pycache__|*.pyc|.pytest_cache|.ruff_cache|.mypy_cache` **零命中**；工作区根存在 `.mypy_cache(12:47) .pytest_cache(12:37) .ruff_cache(12:30)` 与 `.tmp-test/`——**mtime 全部早于本席首个命令，且 .tmp-test 内为 `D9-full.log/D9-collect.log/D2/D5/D7` 等并发全量测试产物（16:00-16:04 持续写入），均非本席生成**（本席 basetemp=`$TEMP/u2-audit-9f3a1c`、mypy cache=`$TEMP/mypy-u2-audit` 均实测在树外存在）。本席不删他人产物，只如实登记。`qx.json` 复核在位（`domains/weather/assets/qx.json`）。

---

## 附录：实跑记录索引

- A1 scoped pytest：`…python.exe -m pytest tests/test_v21_s10_protocols.py tests/test_outbound_v21.py tests/test_capability_registry.py -p no:cacheprovider --basetemp=$TEMP/u2-audit-9f3a1c -q` → `136 passed, 1 skipped in 6.49s`。
- A2 scoped mypy → `capability_protocols.py:1273: error: Module "plugins.bot_unified_runtime.sources" has no attribute "web_search" [attr-defined]`（Found 1 error in 1 file）。
- A3 `ls plugins/bot_unified_runtime/sources/` → 25 条目，无 web_search.py/search_service.py；有 acg_search.py（真身未迁）。
- A4 探针：PROBE1 ImportError（包级 from-import）；PROBE2 `_WebChainAsSearchProvider.search` ImportError（附录同次输出）。
- A5 垫片核验：83 垫片/0 坏；三处 RET2B 注释锚点原文贴录。
- A6 CapabilityResult：204 构造点/文件分布/字段频次表（§三）。
- A7 kind 字面量频次（text 164/mixed 32/post 31/…/provider_error 10/config_missing 7/timeout 5/network 4）。
- A8 同名类聚类 29 组（§五表）。
- A9 `DrawStore(` 构造点全树唯一（api/facet.py:338）；`build_divination_capability(` 调用点 __init__.py:4127 无 store 注入。
- A10 树卫生 find 零命中 + 根缓存三件套/`.tmp-test` mtime 早于本席（.tmp-test 系并发全量测试会话在写）。
- A11 S10 死册实锤：`grep -rn "capability_protocols import|from …capability_protocols|runtime import capability_protocols|default_invoker" plugins/` → 命中仅 capability_protocols.py 自身（L-12 注释/__all__）；tests 命中=test_v21_s10_protocols/conftest/test_render_pool_hygiene/test_thread_pool_atexit_hooks/test_v21r2_lifecycle_r2。
- A12 `control_plane/api/platform.py:457` = `from ...domains.core.search.web_search import search_async`（canonical）——sources.web_search 退役后全树唯一残余旧引用=U2-P0-1 一处，坐实。

*U2-PROTO 席位日志完。所有「已修复」字样均未使用——本席零改动；改法列均为建议，执行裁决权在主会话/用户。*
