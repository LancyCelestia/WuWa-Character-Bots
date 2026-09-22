# 中央能力调度层全面接入 · 施工规格（capability-orchestration-adoption-spec）

> 席位：WP8D（只出文档，本轮零代码改动）。日期 2026-09-21。
> 权威依据：**用户裁定第 10 项**——「需要把所有内容都接入中央能力调度层，不仅仅是 AI 绘画」。
> ⚠ 本裁定**推翻** `docs/audit-20260921.md` §9.5 决策点 **D15 的建议 A（退役壳）**。
> 本规格的方向是**反向**：把 `plugins/bot_unified_runtime/runtime/capability_protocols.py` 的中央调度能力当作**目标架构**，
> 让**全部能力逐域接入**。审计里的「退役」判语在本规格内一律失效，只保留其**取证事实**。
> 取证等级（沿用 §9.0）：`实证`＝行级源码/席位通读背书；`推演`＝结构判定未实跑。凡结论标级。

## 0 一页结论（先给可执行判定）

1. **"接入"不是"重写返回体"**，而是"换调用点 + 挂治理元数据"。能力现有的 `CapabilityResult(...)`
   构造（全树 208 处）**一字不改**；变的是①谁调用 handler（改由中央 `CapabilityInvoker` 统一调用）
   ②该能力在中央描述符表里有一条 `capability_id → handler_ref + 健康探测 + 降级链 + feature-gate id`。
   这样 B 案「契约重设计」的假命题被消解（见 §2）。
2. **两个同名 `CapabilityResult` 分层归并**（地基，Wave 0 必做）：
   `domains/core/contracts/runtime.py:226`（25 字段，呈现契约）= **唯一对外契约、保名**；
   `plugins/bot_unified_runtime/runtime/capability_protocols.py:151`（7 字段，执行信封）= **改名 `InvocationResult`**，由 invoker 产出，
   把 handler 返回的呈现 `CapabilityResult` 装进 `data`。**不合并成超集**（合并会逼 208 处填执行字段即崩，见 §2）。
3. **分 5 波**：Wave0 契约地基 → Wave1 已包装能力（media/files/search 22 描述符）经 invoker 通电 →
   Wave2 中央描述符注册表升为唯一真源 → Wave3 逐域接入（按爆炸半径升序）→ Wave4 三硬骨头（根 `__init__.py` /
   pipeline 旁路 / 主动投递族）。顺序一句话：**小面域先行、chat_reply(25) 与根 `__init__.py`(30) 垫后。**
4. **需要用户裁 7 条**（§8，O1–O7，可回 `O1.A O2.A O3.B …`）。

---

## 1 "已接入中央能力调度层"的验收定义（7 维 · 可机器判定）

一个能力 `X` 判为"已接入"，当且仅当同时满足下列 7 维。每维给机器判据与"现在有没有门"。

| # | 维度 | 可机器判据（写进门/测试即可判定） | 现有的门 | 缺的门（本规格新建） |
|---|---|---|---|---|
| D-a | **id 在中央注册表在册** | `X ∈ CAPABILITY_DESCRIPTOR`（§2/Wave2 的唯一描述符表），且 feature_gate 有 X 条目 | **部分**：壳有 5 张注册表但生产零 import；`CONTROLLED_INTERNAL_CAPABILITIES`(43) 在册 | 描述符表通电后 `validate_registry`（`capability_protocols.py:642`，真回读磁盘核 implementation_ref 文件存在）接进 pre_restart 门 |
| D-b | **调用经统一 invoker** | 全树 grep：除 invoker 内部，生产路径**不再直呼 handler 真身**（如 `describe_images`/`build_web_search_provider`/`read_supported_file`…）；每能力命中记 `via` | **无**（现散装直调） | 新增 AST/grep 门 `test_orchestration_callsite_single`（禁第二调用点） |
| D-c | **出入参唯一契约** | handler 只 `from ...core.contracts import CapabilityResult`；全树**恰一处** `class CapabilityResult`；invoker 只产 `InvocationResult` | **部分**：chat_reply 8 能力件已统一从 contracts 导入（D2 §6 实证） | 新增门 `test_capability_result_unique`（AST 扫类定义计数=1，壳定义已改名即满足） |
| D-d | **健康探测/降级链在中央层** | 描述符含注册的非空 `HealthProbeFn` + ≥1 条 `fallbacks`（末位 `honest_degrade`）；`search_source_status` 能读出 X 健康 | **无**（机制在壳、无生产执法） | 复用壳既有 `CapabilityInvoker`（:412）健康/降级链，接生产读点 |
| D-e | **可观测（审计/错误卡/回执归因同源）** | invoker 写 `AuditRecord(capability_id, request_id, via, status)`；错误卡 `request_id`/回执 capability 归因取自 `InvocationResult` 而非 handler 自拼 | **部分**：pipeline 已 emit audit/receipt（`pipeline.py:498/524`）；invoker 侧未接 | invoker 出口对齐既有 audit/receipt sink（不新建观测栈） |
| D-f | **feature gate 可关** | 关 X → 过 pipeline 的消息得 `BLOCKED`「这项功能暂时不可用」；旁路族则 invoker 直接返 `InvocationStatus` 拒绝态 | **有**：`pipeline.py:532-548` fail-closed 真执法 + `CONTROLLED_INTERNAL_CAPABILITIES` | 无（Wave2 把 CONTROLLED 并入唯一描述符表，读同一处） |
| D-g | **文档/帮助/能力清单三处由注册表派生** | `HELP_TOPIC_DECLARATIONS`(78)/`ROUTE_CAPABILITY_DECLARATIONS`(35) + `command_catalog --check` + `doc_sync` 全 CLEAN | **有**：HELP-1 单源、command_catalog/render_hashes/doc_sync、test_capability_registry 三元组锁（D2 §3 实证 0 死引用） | 无（X 接入即补三处声明，走既有生成物 `--check`，**本席禁 `--write`**） |

**判据小结**：D-f / D-g 已有硬门；D-c 半（仅 chat_reply 覆盖）；D-a/D-d/D-e 机制存在但未通电；**D-b 完全没有**——
"换调用点"正是接入的核心动作，也是唯一需要新增"禁第二调用点"机器门的维度。

---

## 2 两个同名 `CapabilityResult` 的归并（地基 · 先于一切接入动作）

**事实（实证）**：
- A：`domains/core/contracts/runtime.py:226` `CapabilityResult(StrictBaseModel)`，`extra=forbid`，25 字段
  （request_id/kind/title/summary/body/images/audio/video/files/actions/prefix_parts/text_parts/
  confidence/risk_level/privacy_level/send_policy/debug_id/audit_tags/operational_issue/deadline_monotonic…）。
  **全树真实能力都返回它**（D2 §6：chat_reply 8 件统一 import contracts；S10 另一 def 在本目录无消费点）。
- B：`plugins/bot_unified_runtime/runtime/capability_protocols.py:151` `CapabilityResult(_StrictModel)`，`extra=forbid, strict, frozen`，7 字段
  （capability_id/status/data/detail/via/elapsed_ms/attempts）。**生产 import 数=0**，只被壳的 `_result()`/测试用。
- 交集恰=1（`capability_id`，且缺省语义相反）。双向 `extra=forbid` ⇒ 一侧 `model_dump()` 喂另一侧构造必 `ValidationError`。

**为什么不能"合并成超集"**（否定 B 案朴素读法）：208 处构造绝大多数**填呈现字段**（body/summary/media），
壳版连 `body` 槽都没有；强行合一份，则每处都要填 `status/via/elapsed_ms`——invoker 才有这些信息，
handler 构造点无从填 ⇒ 构造期即崩。这是审计报告"实为契约重设计"的源码级真相。

**归并设计（Wave 0，分层，不搬家）**：
1. **A 升为唯一"对外/呈现契约"，保名 `CapabilityResult`，零字段改动**。它是 handler 的返回类型、
   review/render/投递的消费类型——维持现状，接入过程 208 构造**不动**。
2. **B 改名 `InvocationResult`**（报告 R3-7 已提此名），语义=**执行信封**：
   `InvocationResult{capability_id, status:InvocationStatus(9 终态), data: dict, detail, via, elapsed_ms, attempts}`。
   新增一条不变量：`data` 在成功态下**内嵌 handler 返回的呈现 `CapabilityResult` 的 model_dump**
   （或引用），失败/降级态下 `data` 装诚实降级说明。**呈现契约与执行信封是正交两层，不是同一抽象**
   （D6 §2(a) 判定：一"给用户看什么"、一"这次调用执行得怎样"）。
3. **`CapabilityInvoker.invoke(request) -> InvocationResult` 成为唯一调用点**：
   它做 descriptor 驱动 → 权限门 → 载荷限额 → 超时 → 健康/降级链（`honest_degrade`）→ 审计，
   内部调 handler 拿呈现 `CapabilityResult` 再包成信封。pipeline 的"能力执行步"改为委托 invoker（§5）。
4. **兼容策略（extra=forbid 下）**：改名是纯符号级（壳内部 + 6 测试件 + conftest 重挂），
   生产零行为变更（prod import=0）；不动 contracts 即不触发 208 构造的 ValidationError。
5. **反应链契约 vs S10 调用壳是否同一抽象？—— 否**。反应链契约=A（每消息要发什么），
   S10 调用壳=B+invoker（每次能力调用怎么执行/健康/降级）。二者经"invoker 把 A 包进 B.data"组合，
   永不合并为一个类。**这是全篇地基**：没有这个分层，"中央"就退化成第 N 套。

**Wave 0 完成判据**：全树 `grep 'class CapabilityResult'`=1（contracts 版）；`grep 'class InvocationResult'`=1（壳版）；
`test_capability_result_unique` 新门绿；6 测试件+conftest 重挂全绿；`ruff/mypy` 本域零错；prod 行为零变更（实证：import 计数不变）。

---

## 3 现状盘点表（21 域 · 76 能力 id 面 · 逐域）

> 76 id 的**逐条枚举**以 `capability_registry.py` 四张声明表为准（本席只读、不改生成物）；
> 本表用 D6 §2(b) 的 **208 处 `CapabilityResult` 构造按域分布**作"能力面大小"代理，叠加路由事实。
> 列：路径=现走哪条路（invoker=中央 / 直调=直呼 handler / 根内联=`__init__.py` 装配 / 旁路=绕 review+render）；
> 契约=出入参（A=contracts 呈现契约，B=壳执行信封，—=无）。22 描述符（media8/files8/search4/creation2）
> 已在壳内 descriptor（`implementation_ref` 指既有生产实现）。

| 域 | 构造数 | 能力 id（代表） | 现走路径 | 契约 | 健康面 | 迁移难度 | 爆炸半径 |
|---|---|---|---|---|---|---|---|
| 根 `__init__.py` | 30 | 各 matcher 装配/群欢迎/随机图/cookie 兜底 | 根内联 + **旁路**（B 类 call_api :5607；A 类直 submit :2954/3065/3223/3372） | A | 无 | **最高**（9千行） | 全链 |
| chat_reply | 25 | bot.chat/affinity/memory/poke/group_info/status/help… | invoker 候选（pipeline 已统调），但 handler 直调散点 | A | 部分(LLM 链) | 高 | 主反应链 |
| subscribe | 22 | today_history/subscribe_v2/news/epic… | 直调 handler + 投递经队列 | A | 部分 | 中 | 订阅投递面 |
| media | 22 | tts/media_archive/image_search/vision… | **已有壳 descriptor**（media8）；生产直调 ingest 真身 | A(生产)/B(壳) | 壳内 | 中 | 识图/归档 |
| meme | 17 | randpic/meme_library/meme… | 直调 + **旁路**（随机图主动发 :5959/:5965） | A | 无 | 中 | 表情/图 |
| finance | 16 | stocks/market/fx/commodities/bond/northbound | 直调 handler | A | 部分(重试) | 低 | 行情卡 |
| divination | 14 | 八字/塔罗/金钱卦 | 直调 handler | A | 无 | 低 | 占卜卡 |
| music | 11 | 点歌/榜单 | 直调 handler + 试听直链旁路(D5/E2) | A | 部分 | 低 | 点歌 |
| ops | 11 | diagnostics/feature_control/runtime_logs/runtime_admin/debug/alerts | 管理面直调（部分经 pipeline gate） | A | 有(自省) | 中 | 运维/告警 |
| location | 9 | wiki/moegirl | 直调 handler | A | 无 | 低 | 百科 |
| food | 7 | eat/吃什么 | 直调 handler | A | 无 | 低 | 菜谱 |
| link_parse | 7 | parse/content_parser | 直调 handler | A | 部分 | 低 | 链接解析 |
| weather | 6 | 天气/预警 | 直调 handler | A | 有(NMC 重试) | 低 | 天气 |
| files | 4 | download/file_reader | **已有壳 descriptor**（files8）；生产走 file_gateway | A(生产)/B(壳) | 壳内 | 中 | 文件出站 |
| schedule | 2 | reminder/parser（+delivery.py:233 旁路） | 直调 + **旁路**（提醒投递 :2954/233） | A | 无 | 中 | 提醒 |
| assistant | 2 | daily_assist/campus_forward | 装配门控 + **旁路/收编**（campus U17 经 outbound_gate） | A | 无 | 中 | 助理/校园 |
| emergency_info | 1 | bot.emergency_info / emergency_info_push | 装配三重门 + 唯一触点 `submit_active_push` | A | 有 | 中 | 应急投递 |
| notes | 1 | 笔记 | 直调 handler | A | 无 | 低 | 笔记 |
| render | — | renderer/theme_tokens/bridge | 出站渲染层（非能力 id） | — | 有 | 中 | 卡片 |
| transport | — | queue/worker/outbound_gate/onebot/nonebot/mail | 出站车道（旁路根在此） | — | 有 | **高** | 全出站 |
| creation | 0（全 reserved） | creation.tts/creation.image | **已有壳 descriptor**（2，handler 不注册、invoke 恒 unavailable）；域自带 contracts 契约 | B(壳指针) | 诚实 unavailable | 低（§6） | 绘画/TTS 预留 |
| core | 0（仅类定义） | contracts/decision/search_service/supervisor | 多套未通电中央（D6-5） | A | 有(search) | 中 | 地基 |

**22 描述符分布补全（D6 §2(b) top3 之外）**：壳 descriptor 覆盖 media(8)+files(8)+search(4)+creation(2)；
**其余域（finance/divination/music/location/food/link_parse/weather/schedule/assistant/emergency/notes/meme/subscribe
/ops 的能力）当前壳内无描述符** = Wave3 逐域"补描述符"的对象。core/decision、search_service 九源、supervisor 沙箱
= D6-5 的"多套未通电中央"，接入时须与 invoker 归一，不得并存第二 orchestrator（见 §7）。

---

## 4 分波施工图（低风险先行 · 每波可独立验收）

> **回滚粒度总则**：全树未 commit（共享工作树），回滚=对**本波触碰的确切文件路径** `git checkout --` 还原工作树，
> 波内新增件删除；跑 python 一律 `PYTHONDONTWRITEBYTECODE=1`，先 `export PYTHONIOENCODING=utf-8`。
> 每波"接入完成判据"= 该波所辖能力满足 §1 七维 + 波内新门绿。

### Wave 0 · 契约地基（§2，前置一切）
- **动文件**：`plugins/bot_unified_runtime/runtime/capability_protocols.py`（B 类改名 `InvocationResult`、`_result()` 返回类型、`data` 内嵌呈现契约不变量）；
  6 测试件 + `conftest`（重挂新名）。**不碰** contracts、208 构造、root。
- **新增中央件**：`test_capability_result_unique`（AST：全树 `class CapabilityResult` 计数=1）。
- **回滚点**：仅 2 文件 + 测试重挂；prod import=0 ⇒ 运行时零变更，git checkout 即净回退。
- **门禁影响**：`tests/` 内引用壳 `CapabilityResult` 处全红（改名所致，**该红**）；重挂后归零。doc_sync/catalog 不受影响。
- **完成判据**：§2 判据四条全绿。

### Wave 1 · 已包装能力通电（media/files/search 22 描述符 → 经 invoker）
- **动文件**：各 handler 真身消费点（识图/转写/搜图/文件读/搜索）改为经 `CapabilityInvoker.invoke`；
  壳的 `_handle_*`（懒 import 既有实现）**保留**，只把"谁调 invoker"接进生产装配（root `__init__.py` 对应 build 段）。
- **新增中央件**：`test_orchestration_callsite_single`（grep/AST：禁第二调用点）。
- **回滚点**：逐能力 descriptor，一能力一提交点；任一能力回退不影响其他（invoker 未接则回落旧直调）。
- **门禁影响**：media/files/search 域回归、渲染契约（返回体不变故应零红）；调用点门新红（该红）。
- **完成判据**：22 能力满足 §1 D-b/D-c/D-d（走 invoker、契约分层、健康面在中央）；其余维随 Wave2/3。

### Wave 2 · 中央描述符注册表升为唯一真源
- **动文件**：`capability_protocols.py` 的 5 张注册表 + `capability_registry.py` 的
  `CONTROLLED_INTERNAL_CAPABILITIES`/`ROUTE_CAPABILITY_DECLARATIONS` 合并派生出
  **`CAPABILITY_DESCRIPTOR`（唯一表）**；feature_gate(`domains/ops/admin/feature_gate.py`)、help、command_catalog 改读同一处。
  **这是 D6-5"多套并行未收敛"的收口波**（不新建第三 orchestrator）。
- **新增中央件**：`validate_registry`（磁盘回读）接 `scripts/pre_restart_check.py`。
- **回滚点**：注册表合并按"缺省=并集、行为等价"迁移；每源表保留指针注释，可逐项回退。
- **门禁影响**：`test_capability_registry` 三快照 + 5 写死数会红（表结构变，**该红**，随迁移更新）；doc_sync/catalog 需 `--check` CLEAN（**本席不写**，实现席收敛后重录）。
- **完成判据**：D-a（唯一在册）+ D-f（gate 读同一处）；"同能力 id 只有一处注册" AST 门绿。

### Wave 3 · 逐域接入（爆炸半径升序）
顺序（每域一子波，独立验收）：
`notes(1) → emergency_info(1) → assistant(2) → schedule(2) → files 剩余(4) → weather(6) → link_parse(7) → food(7) →
location(9) → ops(11) → music(11) → divination(14) → finance(16) → meme(17) → subscribe(22) → media 剩余(22) → chat_reply(25)`。
- 每子波动作：在该域 `capability_registry` 补/接 descriptor（id→handler_ref+健康+降级+gate id），
  把该域 handler 的调用点收进 invoker，补 D-g 三处声明（走 `--check` 不 `--write`）。
- 回滚点：一域一提交面；descriptor 未接则该域走旧路（invoker 未包 = 行为不变）。
- 门禁影响：被迁域回归 + 调用点门 + registry 快照（该红随迁更新）。
- 完成判据：被迁域满足 §1 全七维。

### Wave 4 · 三硬骨头（专章见 §4.1–4.3，放最后因半径最大）

#### 4.1 根 `__init__.py`（≈9 千行 matcher 装配面，30 构造）
- **只外迁 handler 体，matcher 注册留根文件**（报告 R1-1 A 案具体化）：30 构造随 handler 体下沉到各域，
  根文件保留 `on_message/on_command/on_notice` 注册与 `classify_message_route` 委派。
- **新增中央件**：`test_same_capability_one_registration`（AST：同 capability id 全树仅一处注册）。
- 回滚点：**逐 matcher 块**（53 处 `on_*` 注册分域），一块一提交；registry 冻结快照 `outbound_registry` 坐标随迁刷新（§6 已证 49/50 行号漂，接入时刷新而非信任）。
- 门禁影响：route-matrix 覆盖门、feature_gate/feature_gate 装配、campus live 坐标（`__init__.py` 顶置 import 会顶漂 campus 坐标，见 #45 教训：降为函数体内 import）。
- 完成判据：根文件不再持有业务 handler 体；B 类旁路清零（§4.2）。

#### 4.2 pipeline 的 17 条旁路（A 类绕 review+render / B 类直 call_api）
**取证清点（audit §4.1/§4.3 + D6 §5.2/§8，实证）**：
- A 类（有队列、绕 review/render）：群失败 ack `pipeline.py:943`、提醒 `__init__.py:2954`+`domains/schedule/delivery.py:233`、
  错误卡 `domains/ops/monitor/error_report.py:1037`、告警 `alerts.py`、每日摘要、邮件/TG 通知 `transport/mail/mail_bridge.py:312/351/369`。
- B 类（直 `call_api`、三重旁路）：入群欢迎 `__init__.py:5607`（正文手写字面量 `:1163`）、随机图主动发 `:5959/:5965`、cookie 兜底 `:4472`。
- **收编**（报告 R3-3/R3-4，本规格定为必做，非"可选例外"）：
  - A 类 → **2026-09-21 S-W42 席实证更正：不新建函数**。原计划抽 `render_reviewed_output`/`deliver_via_pipeline`
    经逐签名核读判定为**造第二出口**——三处现役件已把这些职责占满：投递出口 `submit_active_push`
    （`domains/transport/sender/outbound_gate.py:658`，含 `dedupe_family`/`deliver_after`）、审核
    `review_capability_result`（`domains/render/reviewer.py:156`，纯函数）、渲染+提交全链
    `_send_text_through_unified_pipeline`/`_send_parts_through_unified_pipeline`（根 `__init__.py:4842/:4873`）。
    ⇒ Wave 4.2 的正确交付 = 把 **8 处/4 文件**（实测，非规格旧称"六类"）A 类散构**改调上述现役件**；
    过渡期"旁路计数"观测告警照旧。改道必答题：提醒 `store.mark_done` 须从"内联同步 receipt"改读 worker
    持久回执（`worker.py:285-287 record(receipt)` + `receipts.latest(request_id)`），闸顺延不得误判已投。
  - B 类 → 文案入 `user_copy` 池 + 经 outbound_gate/SendQueue；**随机图 :5959/:5965 若属"有意镜像"，登记为显式例外并说明理由**（决策点 O5）。
  - **禁止式门**：根文件与 `domains/**`（sender 漏斗最底除外）出现 `call_api("send_*` / `send_group_msg` / `send_private_msg` 即红。
- 门禁影响：错误卡两段式异步有 `deliver_after≥3s` 下限（时序敏感，须单独回归）；旁路计数告警为新增面。

#### 4.3 主动投递族（唯一触点 + outbound_gate）
- 各域唯一触点（实证）：emergency=`submit_active_push`（`domains/emergency_info/service/push.py:267`，域内静态门锁死）；
  campus=U17 收编经 outbound_gate；reminder/assistant/subscribe=各自 delivery/push 现**直 submit**（Wave4 收编为经 invoker 产文本 + outbound_gate 投递）。
- 结论：接入 = 在描述符表登记这些 id + 让"生成投递内容"经 invoker（D-d/D-e），
  **投递动作仍走 outbound_gate**（静默窗/限流/键规范），与 §5 执行门边界互不重叠。

---

### 4.4 落地进度（2026-09-22 统一波实况 · 逐波对账，防止下一个 AI 重做已做的）

| 波 | 状态 | 实况与证据 |
|---|---|---|
| Wave 0 | ✅ 已落 | 两层同名归并：壳侧执行信封改名 `InvocationResult`、呈现契约保名，`PRESENTATION_DATA_KEY` 为唯一跨层通道；执法 `tests/test_capability_result_unique.py` |
| Wave 1 | ✅ 已落 | media/files/search 描述符经 invoker；D-b 单执行点位门 `tests/test_orchestration_callsite_single.py` |
| Wave 2 | ✅ 已落 | `CAPABILITY_DESCRIPTOR` 升为唯一在册表；`tests/test_capability_single_registration.py` 禁第二处 authoring |
| Wave 3 | 🟡 进行中 | 逐域接入（爆炸半径升序）——**在册通电条数以唯一表执行形为准**（本行写时已含命令形与 prepared 两批，远超当初"8 枚"），未接入残余由 `tests/test_descriptor_wiredness_ledger.py` 分四桶点名（interface_only / controlled_no_callsite / orchestration_unwired / route_capability_unmigrated）|
| Wave 4.1 | ✅ 已落 | 命令形接缝 `orchestrated_command()`（层 2 治理、执行体用调用方交来的成品）+ 命令形通电（首批 wiki/news/randpic/moegirl/meme/reminder/daily_assist/tts；**现役条数以唯一表执行形为准，本行名单=当时值**）；缺口只准降由 `test_descriptor_wiredness_ledger.py` 手写 `GAP_CEILING` 执法 |
| Wave 4.2/4.3 | ✅ 已落 | 四条主动投递族（群摘要/日常助理/提醒/cookie 到期）改走中央出口 `submit_active_push`；提醒两族用"闸判定 + 保留内联投递"形态 ⇒ 闸关态零行为变更。裁定件 `decisions/WAVE42-active-push-central-exit.md`（含 B4-spec「只登记不迁移」旧口径的过期依据） |
| 观测面 | ✅ 已落 | 中央执行审计 sink 生产注册（`attach_default_audit_sink`）+ 审计记录带 `request_id/session_key`；此前**emit 全树零注册**＝"走中央但没人知道" |
| 崩溃保真 | ✅ 已落 | 能力真崩 ⇒ 原始异常经 `INVOKER_ERROR_DATA_KEY` 交回层 1 ⇒ `_internal_error`→诊断卡旁路保持；被拒/超限仍走诚实短句 |
| 权限门 | ✅ 已落 | 层级门槛 `roles_satisfy`（修管理员被拒）+ 空角色=系统主体豁免**只做在 invoker 门上**（修定时任务被拒，且不把 `/bot why` 从"过拒"翻成"过放"） |
| Wave 4.4 prepared | 🟡 施工中 | **地基已落 + 三批已通电**（2026-09-22）：`adapter="prepared"` 进 `_KNOWN_ADAPTERS`、`_make_prepared_handler()` 只认调用方经 `context["capability"]` 交来的成品（拿不到 ⇒ `UNAVAILABLE`，**绝不按 ref 自建**＝不造丢注入的第二通路），派生分派三分支。金丝雀 `bot.weather` + B1 十枚（market/stocks/fx/commodities/bond/northbound/epic/eat/divination/emergency_info）+ B2 一枚 `bot.affinity` + B3 一枚 `bot.ignore`；**在册条数以唯一表执行形为准，本行名单=当时值**。执法 `tests/test_prepared_adapter_canary.py` 与按批分文件的 `tests/test_prepared_adapter_batch1.py`、`tests/test_prepared_adapter_batch2.py`、`tests/test_prepared_adapter_batch3.py`，外加**逐 id 行为矩阵** `tests/test_central_dispatch_matrix.py`（参数化源=在册执行形现算，含非空转守卫）。**⚠ 本行旧口径已被 B3 席实读推翻并就地更正**：原文写"剩余=root 内联闭包那批（须先提具名 builder）"——`prepared` 形的 `implementation_ref` 只作 provenance、**不参与执行**，所以内联闭包**不需要**先提具名工厂就能如实登记"成品由调用方交来"。剩余因此缩成两类各自卡点不同的：**六枚**（content/music/today_history/media_archive/meme_library/group_info）AST 实证**不经根的两个汇合函数**（裸 `pipeline.handle_async`），要接**必须改生产根文件**；**四枚**（music_mode/subscribe/mail.control/auto_send.preview）**已汇缝却无执行面**，其中 `mail.control`/`auto_send.preview` 注册册无宿主行＝结构上无处填 `execution`。另有 `bot.image_search`/`bot.campus_forward`（同样无宿主行）与 chat provider 注入墙（异形态）。施工图 `decisions/PREPARED-ADAPTER-PLAN-20260922.md`（其 B6 段的旧前置已过期，以本行为准） |
| 记账口径 R8→R9 | ✅ 已并入（并二次收紧） | 经接缝通电的能力在字面量扫描下不可见；口径件 `decisions/R8-seam-wiring-accounting.md`，取数口 `seam_registered_cids()`（原名 `seam_registered_command_cids`，prepared 落地后已扩到全部已知 adapter 并改名）。**R9 收紧**（R-PREP C-1）：取数口只证"声明了执行形"，"每一条分发入口都汇到缝"另由 `tests/test_prepared_adapter_canary.py` 的多入口活性锁执法——别名/自然语言两条入口历史上绕过层 2，只有前者时 WIRED 会是假账 |

> 本表只记"做到哪"。**"已接入中央调度层"的唯一判据仍是 §1 七维**，不因本表某行打勾而自动成立；
> 剩余未接面总账见 `logs/SEAT-S-GAPMAP.md`。

## 5 中央调度层 vs 执行门 vs feature gate：同一层还是两层？（结论）

**实证边界（D4-5）**：执行门真实存在、fail-closed（`pipeline.py:532-548`，异常态也拒），
控制面 HTTP 与门共享同一 service 实例、SQLite 持久化在位；AGENTS"未接执行门/未迁 SQLite"旧口径已被推翻。
**精确边界**：门只拦"经 pipeline 的能力执行"，**不卸载插件、不停 worker/调度器；旁路直 submit 不经它**。

**结论：两层 + 一个正交开关，不是同一层，也不是平行第三层。**
- **层 1 `RuntimePipeline`**＝请求级反应链编排（每消息：门禁→幂等→限流→**能力执行步**→review→render→submit）。
- **层 2 `CapabilityInvoker` + `CAPABILITY_DESCRIPTOR`**＝能力级执行治理（descriptor→权限→限额→超时→健康→降级→审计）。
  层 2 是**嵌在层 1 "能力执行步"里的一个缝**：pipeline 在 gate/幂等通过后，把"调哪个能力"委托给 invoker，
  invoker 回 `InvocationResult`（含呈现 `CapabilityResult`）。二者共用同一描述符表读 gate id ⇒ 单一真源、无重复执法。
- **feature gate**＝正交的"能力开/关"位，读 Wave2 唯一描述符表；pipeline（层 1）在入口执法，invoker（层 2）对**不经 pipeline 的主动投递族**在自己的 descriptor 门执法。
- **主动投递族 / worker / 调度器不经 pipeline**（D4-5 边界），它们的"接入"= 层 2 descriptor（健康/降级/审计）+ outbound_gate（投递节流）；
  执行门对它们**不执法是既定语义**（非缺陷），规格不试图让 pipeline 去管旁路。

---

## 6 AI 绘画（creation 域）在谱里的位置（吸收 · 不开特例）

**实证**：creation 域**自带契约**——`domains/creation/_common/contracts.py`（CreationJobState/UsageLine/AssetRef，严格 Pydantic DTO）、
`domains/creation/tts/contracts.py`、`domains/creation/image/contracts.py`；壳内两条 `creation` descriptor 只是 `implementation_ref` 元数据指针，
handler 不注册、invoke 恒 `unavailable`（`_probe_creation_reserved:1410`）。D6 §2(c) + E3 判：creation 落地
**不依赖壳存在**，只依赖"creation 域契约被某调用点接上"。用户裁定第 10 项既然要"全部接入中央层"，creation 就**不再单独留对接点**，
而是按 §1 七维作为普通能力接入：
1. creation.tts / creation.image 在 `CAPABILITY_DESCRIPTOR` 各有一条 descriptor（id、handler_ref 指 creation 域真身、健康探测=provider 配置探测）。
2. 未配置 provider 时 handler 诚实返回 `unavailable`（保留既有诚实语义），**不为其开 orchestrator 特例**——与任何"未接线能力"同形态。
3. **消除 E3-4 契约漂移（尺子②直接违规）**：`domains/creation/tts/contracts.py` 现值
   `TTS_MAX_TEXT_CHARS=3000 / TTS_MAX_DURATION_SECONDS=60.0 / TTS_MAX_ASSET_BYTES=20MiB / TTS_SPEED_MIN=0.75 / MAX=1.25`
   与 Wave G 中央 TTS 契约现役 `2000 / 131s / 8MiB / 0.6–1.65` **四组全互斥**，且 60s 是 Wave G 明文作废的旧判据。
   **接入即收敛**：creation 的 TTS 数值改为**引用 Wave G 中央 TTS 契约单一来源**（`bot_tts_*` / contract-layer 规格件），
   creation 不再持有第二套数值（决策点 O7）。绘图侧同理对齐 `bot_creation_*`（未来键，随接入落地）。
4. creation 域 DTO 作为 `InvocationResult.data` 里的呈现载荷流转，不新增第三种结果类型。

---

## 7 收敛铁律：禁止第三套（每新增件写明取代谁 · 何时退役）

审计反复定罪"再拷一份同构实现"。本规格**唯一允许的新增件**与其取代关系：

| 新增件 | 取代/收编的既有件 | 既有件退役时点 |
|---|---|---|
| `InvocationResult`（改名，非新建类） | 壳的第二份 `CapabilityResult` 名 | Wave 0（改名即退役旧名） |
| `CAPABILITY_DESCRIPTOR` 唯一描述符表 | 壳 5 张注册表 + `CONTROLLED_INTERNAL_CAPABILITIES` + `ROUTE_CAPABILITY_DECLARATIONS` 的**分散真源** | Wave 2 合并后，旧表改为派生视图/注释指针，**同波退役为"派生"** |
| ~~`render_reviewed_output`/`deliver_via_pipeline` 统一出口函数~~ **已作废（2026-09-21 S-W42 实证）**：不新建，改为 A 类 8 处散构改调现役 `submit_active_push` + `review_capability_result` + `_send_*_through_unified_pipeline` | A 类旁路的 8 处散构 `SendRequest`（root 提醒/cookie 到期门/每日摘要/早晚报 + pipeline ack + 错误卡 + 未通电干跑件） | 逐处改调当笔退役该处散构 |
| `test_capability_result_unique` / `test_orchestration_callsite_single` / `test_same_capability_one_registration` / call_api 禁止式门 | （纯新增门，无取代对象） | 常驻 |

**明确不做**：不把 pipeline 重写为 invoker；不把 208 处构造改签名；不为 creation 建平行 orchestrator；
不复活 D6-5 点名的"多套未通电中央"（decision 影子引擎 / search_service 九源 / supervisor 沙箱）为并列 orchestrator——
它们若接入须**经同一 invoker**（search_service 九源本就与 S10 同源，Wave1/3 并线，不留第二调用面）。

---

## 8 需要用户裁决的点（编号 + 推荐 + 判错代价 + 回滚面 · 可回 `O1.A O2.A …`）

> 本规格把审计 D15（建议退役）**翻为建议全面接入**，但地基与幅度仍须她点一次。

- **O1｜契约归并方式**：
  A＝**分层双契约 + 改名**（contracts 保名做唯一呈现契约、壳改名 `InvocationResult` 做执行信封，invoker 包 handler 返回；零改 208 构造，Wave0，推荐）
  ／B＝合并成超集单契约（逼 208 处填执行字段，构造期 ValidationError 大改，代价最高）。
  **推荐 A**。判错代价（选 B）＝全树 43 文件返工 + 呈现/执行关注点强耦合；回滚面＝Wave0 整体 revert。

- **O2｜中央调度层与 pipeline 的关系**：
  A＝**两层嵌套**（invoker 作 pipeline 能力执行步的缝，主动投递族走 invoker+outbound_gate，执行门边界不动，推荐）
  ／B＝pipeline 与 invoker 合成一层（重写主链，半径全链）。**推荐 A**。判错代价（选 B）＝§5 全推倒重做。

- **O3｜creation 接线幅度（本轮）**：
  A＝登记 descriptor + handler 仍诚实 `unavailable`（只补契约收敛 O7，不实现 provider，推荐）
  ／B＝本轮连 provider 一起实现（超本波范围）。**推荐 A**。回滚面＝descriptor 一条。

- **O4｜根 `__init__.py` 外迁幅度**：
  A＝**只外迁 handler 体、matcher 注册留根文件**（半径可控，推荐）／B＝连注册一起搬（顶漂 campus 坐标，#45 教训）。**推荐 A**。

- **O5｜B 类旁路"有意镜像"（随机图 :5959/:5965）**：
  A＝收编进统一出口（口径纯净）／B＝登记为**显式例外**并注理由（保留镜像注释语义）。**推荐 A**，例外须写进禁止式门白名单表让她过目。

- **O6｜已包装 22 能力是否本轮就通电经 invoker**：
  A＝通电（Wave1，prod 从 import=0 转为真承载流量，行为变更面最大但一次到位，推荐）
  ／B＝保持"仅 descriptor 在册"下一波再通电。**推荐 A**（否则"接入"名不副实）。判错代价＝媒体/文件/搜索链回归窗口。

- **O7｜TTS 数值单一来源（消 E3-4）**：
  A＝creation TTS 数值改引 Wave G 中央契约（2000/131s/8MiB/0.6-1.65，creation 弃自持 3000/60s/20MiB/0.75-1.25，推荐）
  ／B＝反向（Wave G 采 creation 值）——但 60s 系 Wave G 明文作废旧判据，选 B=复活废值。**推荐 A**。

---

## 附录 A · 证据坐标索引（供实现席 30 秒复核）

- 两契约：`domains/core/contracts/runtime.py:226`（25 字段呈现）· `plugins/bot_unified_runtime/runtime/capability_protocols.py:151`（7 字段执行）· `_result:171`·`CapabilityInvoker:412`·`validate_registry:642/695-699`·`_probe_creation_reserved:1410`。逐字段对照见 `deep-D6-log.md §3`。
- 中央注册表：`domains/chat_reply/runtime/capability_registry.py` `ROUTE_CAPABILITY_DECLARATIONS:97`(35)·`INTERFACE_DECLARATIONS:317`(20)·`HELP_TOPIC_DECLARATIONS:457`(78)·`CONTROLLED_INTERNAL_CAPABILITIES:550`(43)。
- 执行门：`domains/chat_reply/runtime/pipeline.py:532-548`（fail-closed，BLOCKED「这项功能暂时不可用」）· `domains/ops/admin/feature_gate.py:89-99` · 装配 `__init__.py:3742-3746/4123`。边界与"AGENTS 旧口径推翻"见 `deep-D4-log.md §2`。
- 208 构造分布：`deep-D6-log.md §2(b)`（域代理表见 §3）。旁路清单：audit §4.1/§4.3 + `deep-D6-log.md §5.2/§8`；直 submit ≥7 触点（root 2954/3065/3223/3372、pipeline 894/943、error_report 1037、schedule/delivery 233）。
- 入群欢迎手写字面量：`__init__.py:1163 _group_welcome_text` + `:5607 call_api("send_group_msg")`。
- creation 契约漂移：`domains/creation/tts/contracts.py:39-46`（3000/60s/20MiB/0.75-1.25）vs Wave G 中央（2000/131s/8MiB/0.6-1.65），`docs/audit-20260921.md §9.6.2 E3-4`。
- 壳 descriptor 分布：media8/files8/search4/creation2（D6 §9.1）；chat_reply 能力件统一 import contracts（`deep-D2-log.md §6`）。
- 多套未通电中央（须归一、禁并列）：`deep-D6-log.md §D6-5`（decision/search_service 九源/supervisor/outbound_registry）。
