# B02 路由与中央调度

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02 路由与中央调度

> 决定一条消息归谁处理、能不能处理、由哪一个能力入口处理。

职责：

- RouteKind 判定与优先级拆位（唯一路由真身）
- 能力声明源与中央调度信封（InvocationResult）
- 决策引擎影子对照与接管
- 门禁：角色、黑白名单、安静时间、限流、幂等

### 二级功能

| 二级功能 | 一句话 | 三级入口 |
|---|---|---|
| [路由表与判定序](route-table/README.md) | base_router 的 RouteKind 枚举、RouteRule 注册表与优先级判定序。 | [昵称命令](route-table/alias.md)、[自然语言命令](route-table/natural-command.md)、[IGNORE](route-table/ignore.md)、[matcher 族与谓词](route-table/matcher-family.md)、[优先级判定序与拆位](route-table/priority-order.md)、[命令路由成员资格](route-table/command-route-membership.md) |
| [能力注册表与调度壳](capability-registry/README.md) | 每能力一行的 keystone 声明源，与中央调度信封的收编进度。 | [声明源与投影表一致性](capability-registry/keystone-declarations.md)、[调度信封与呈现契约分层](capability-registry/invocation-envelope.md)、[新增能力登记流程（先建模块与函数）](capability-registry/new-capability-checklist.md) |
| [决策引擎](decision-engine/README.md) | 影子对照记录分歧，接管进度由配置模式控制。 | [影子对照与分歧记账](decision-engine/shadow-mode.md) |
| [门禁与限流](policy-gate/README.md) | 角色/黑白名单/安静时间/限流/幂等，全能力共用的准入面。 | [管理员命令](policy-gate/admin.md)、[六级角色与权限叠加](policy-gate/role-model.md)、[安静时间与主动搭话门](policy-gate/quiet-hours.md)、[双实现限流与回滚](policy-gate/rate-limiter.md)、[入站幂等](policy-gate/idempotency.md) |
<!-- BOARD-AUTO:END -->

## 板块职责

B02 回答三个彼此独立的问题，因此切成四个二级功能：

- 这条消息**归谁**：`route-table`——确定性路由表，把文本判成一个 `RouteKind`，只判断、不执行、不发消息。
- 这个人/这个场景**能不能干**：`policy-gate`——角色、群黑白名单、安静时间、限流、回复预算、入站幂等，全能力共用一张准入面。
- 由**哪一个入口**干、怎么被调用：`capability-registry`——每能力一行的 keystone 声明源，加上中央调度信封。
- **将来**由谁判：`decision-engine`——影子对照，缺省不接管。

为什么切在这里而不切在别处：门禁与路由都在同一条 `RuntimePipeline._prepare` 里顺序执行，但它们的**变更原因不同**（路由随能力增减而变，门禁随骚扰/隐私策略而变），所以分功能而不分文件。执行门（feature gate）的**开关来源与 API** 属 B09 控制面，B02 承担它在链路上的两次拦截动作：层 1 是 `RuntimePipeline._prepare` 那一次；层 2 是绕过 pipeline 直呼中央门面时 `runtime/capability_protocols.py::CapabilityInvoker.invoke` 里的那一次（2026-09-23/24 起执法；三条边界＝只对 `gate_feature_bindings()` 在册受门者执法、未受门 pass-through、读不到状态 fail-closed，口径以 `docs/design/control-plane-registry.md` 与 `docs/boards/B09-control-plane-observability/feature-switches/feature-gate.md` 为准，本页不重抄判定）。

### 现役进度：中央调度层（必须先读）

用户裁定的中央调度层那一条：「所有内容都要接入中央能力调度层，TTS 也不例外」。规格与分波施工在 `docs/design/capability-orchestration-adoption-spec.md`。现状如实：

| 波次 | 内容 | 状态 |
|---|---|---|
| Wave 0 | 两个同名 `CapabilityResult` 分层归并：contracts 版保名做呈现契约，壳版**改名 `InvocationResult`** 做执行信封 | 已落，门 `tests/test_capability_result_unique.py` 在位 |
| Wave 1 | 已包装的 media/files/search 描述符改经 `CapabilityInvoker` 通电 | **整批未做**；部分例外：配音腿的产出与结果变换两步自 S91 起真经中央 `invoke`（字面调用点住哪个文件由缺口账与直呼面普查门现算，本页不点名） |
| Wave 2 | 中央描述符注册表升为唯一真源（并 `CONTROLLED_INTERNAL_CAPABILITIES` 等表收拢） | **已落**：唯一在册表真身＝`runtime/capability_protocols.py::CAPABILITY_DESCRIPTOR`，常驻门 `tests/test_capability_single_registration.py` 执法 D-a「同一 id 不得在第二处 authoring 表另立注册」与 D-f「feature gate 读同一处」；旧表降为派生视图的收拢程度以该门现算为准 |
| Wave 3 | 逐域接入（爆炸半径升序，`chat_reply` 垫后） | **进行中**（已接入者与未接入残余都由缺口账 `tests/test_descriptor_wiredness_ledger.py` 现算分桶点名，本页不抄第二份清单） |
| Wave 4 | 根 `__init__.py` 的 handler 外迁、pipeline 旁路收编、主动投递族收编 | **拆档算**（编号取规格 §五的子波）：4.1 命令形接缝 + 中央执行审计 sink 已落；4.2/4.3 主动投递族改走唯一出口 `submit_active_push` 已落（裁定件 `.superpowers/sdd/2026-09-21-unify-wave/decisions/WAVE42-active-push-central-exit.md`，2026-09-24 裁定 R-4 进一步删掉根里四条 `call_api` 直发分支）——**但"已落"只到码面**：`config.py` 的 `bot_outbound_gate_enabled` 缺省 `False`，闸关态＝与裸 `submit` 同形的 passthrough，键形与限额那半执法线上不生效（"已通电≠已生效"，开闸权与实况以 `config.py` 该字段＋控制面投影为准，见 `AGENTS.md` 台账「在册但未执法」条与 [B08.outbound-copy](../B08-render-outbound/outbound-copy/README.md) 的同口径句）；4.4 prepared 形施工中（在册条数以唯一表执行形为准）；**根 handler 外迁与 pipeline 旁路收编未做** |

〔⚠ 2026-09-25 席 S288D 三格跟随（"一处变更未处处跟随"账）：上表原把 Wave 2 / Wave 3 / Wave 4 三格一律记「未做」，
与 `docs/boards/B08-render-outbound/outbound-copy/README.md` 的「Wave 1–2 已落地」互斥。现算判定＝**各错一半**：
Wave 2 已落（本席亲跑 `tests/test_capability_single_registration.py` 全绿）、Wave 1 未落（缺口账今日仍点名 media/files/search
那批未通电 ⇒ 规格 §五「Wave 1 已落」那一格不许搬到本页）。另存一层**同名两义**：本页与规格件用五波编号，B08 那页把
「Wave 1–2」当一个复合标签、内容其实只等于 Wave 2，却又混用子编号 4.1——两页现各按自己那套编号写清所指、**未强行合并**，
是否统一重命名归用户裁定。〕

因此**不得拿本表当"已接入"的凭据，也不得拿它当"一律没接入"的凭据**：中央缝是否真被生产
调用、还剩多少没走，唯一准绳是 `tests/test_descriptor_wiredness_ledger.py` 的活体缺口账
（另配入口侧的 `tests/test_five_entry_seam_lock.py`），本页不抄第二份会漂移的清单。
`runtime/capability_protocols.py` 「生产路径零 import」是 2026-09-21 审计 V1-1 的**当时值**，
此后不再成立——配音腿与 creation 两面对接点的执行体都经中央 `default_invoker()` 走信封，
`/bot status` 的健康行也现读该件。反过来，多数在册能力仍在根 `__init__.py` 的内联闭包里
执行：中央收编走 Tier-B 的裁定（Tier-A 判为假绿、禁叙述为「已走中央」）见
`docs/HANDBOOK.md` §46.1，那批根改动今天未落。两句都别说过头：「中央层已是现役执行面」
失实，「中央层在生产里没被碰过」同样失实。

## 上下游

```mermaid
flowchart LR
  B01.message-normalization --> route[B02.route-table]
  route --> fs[B02.capability-registry]
  fs --> gate[B02.policy-gate]
  gate --> cap[能力实现 B03–B07]
  cap --> B08.review-gate
```

主链路十六段的完整口径以 `docs/boards/_conventions.md` §五为准，本卡只画 B02 所辖那一段（各卡不复绘全链，那是漂移之源）。

## 退役与并入记录

按 `docs/boards/_meta/doc-classification-20260921.md` 的判决：

- `docs/route-matrix.md`：全问法路由矩阵并入 `route-table` 正文；该文件继续作为与代码对齐的对照表存在，覆盖门在 `tests/test_doc_sync_gates.py`（AST 双向比对 priority 与能力 id；触发词列属明文免责，见 `docs/audit-20260921.md` 门 F 判决）。
- `COMMANDS.md`：命令索引并入本板块；`docs/command-catalog.md` 是生成物，保留原地、禁止移树，板块只引用不复制。
- `docs/design/capability-orchestration-adoption-spec.md`：并入本板块调度层正文，未做的 Wave 1–4 在本页明示挂账，不许写成已完成。
- `docs/design/central-decision-engine.md`：状态自述「规格稿未实现」，`decision/` 仅有 shadow 面 ⇒ 归 `decision-engine`，原文件标注未实现或归档。
- `docs/design/backend-v2-implementation-guide.md`（实施合同）与 `docs/design/v21r4-b2-direct-collect-plan.md`（S0 直连点收编设计）：结论并入本板块，母本保留在 `docs/design/`。
- `HANDOFF-V21R5-20260920.md`：其中「四服务生产装配 / 垫片退役 / policy 迁移」段拆并入本板块与 B01，原文件归历史证据。
- 旧路径 `plugins/bot_unified_runtime/policy/`、`decision/`、`runtime/base_router.py`、`runtime/capability_registry.py`、`runtime/pipeline.py` 等均为再导出垫片，真身在 `domains/chat_reply/policy/`、`domains/core/decision/`、`domains/chat_reply/runtime/`。引用一律写真身。
