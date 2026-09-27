# 功能开关树 · 父子继承与 blocked_by

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B09.feature-switches · 父子继承与 blocked_by

- 层级：一级 B09 → 二级 feature-switches → 三级 `feature-gate`
- 实现落点：`plugins/bot_unified_runtime/domains/ops/features`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

在能力真正执行前问一句「这个功能现在该不该放行」。它把控制面维护的功能开关图（含父子层级）接进消息流水线：命中开启就放行，命中关闭或被上级/依赖挡住就拒绝，图查询本身故障时不放行。语义是有意保守——不认识的 id 也拒绝，而不是默认放行。

## 怎么调用

执行门 `domains/ops/features/feature_gate.py::ProductFeatureGate` 是**两层消费点、一份真身**：层 1 注入 pipeline（`domains/chat_reply/runtime/pipeline.py` 的 `_prepare`），被以 `ProductFeatureGate.__call__(message, capability_id)` 调用；层 2 注入中央执行门面 `runtime/capability_protocols.py::CapabilityInvoker`（装配经唯一注入口 `attach_default_feature_gate`，构造形参 `feature_gate` 缺省 `None`＝不执法＝该波之前的现网现状）。`__call__` 已降为**纯转发**：历史签名带 message 但真身从不读它，判定全文住在 `check_capability(capability_id)`，层 1/层 2 共用同一份门序、禁第二套。两层都返回 `FeatureAccess(allowed, reason, feature_id, graph_revision)`。它只查询不写状态，状态来自 `plugins/bot_unified_runtime/control_plane/services.py::FeatureControlService`；某能力对应哪个 feature id 由 `feature_catalog.py::capability_feature_bindings` 提供（真源是 `runtime/capability_protocols.CAPABILITY_DESCRIPTOR` 投影，运行时不扫描源码）。`FeatureSwitchSnapshot.enabled(feature_id)` 在图不可用时（`available=False`）一律返回未启用。

父子继承与挡路在 `plugins/bot_unified_runtime/control_plane/features.py`：`FeatureDescriptor` 带 `parent_id`；`dependencies` 与父节点合并为该节点的 prerequisites；装配有效状态时，若父节点未 `effective_enabled`，就把父 id 记入 `blocked_by` 并置 `inherited_from`，子节点随之被挡住。整棵树不重建即可按 `graph_revision` 读快照。

## 开关与参数

放行三态（写死，非遗漏）：登记且开启 → 放行；登记且关闭 → 拒绝（`feature_disabled`）；未登记 → 拒绝（`feature_unregistered`）。不变量「使用即登记」：一个 `capability_id` 一旦被统一管线消费，就必须出现在注册册投影的绑定表里，否则走未登记拒绝分支。「开/关」本身不在 `.env`，而是控制面功能图状态（`FeatureControlService` 持久化的图 + `graph_revision`），改状态属控制面操作、非配置键热改面。

上面那组三态是**层 1（统一管线）**口径，层 2（直呼 `CapabilityInvoker.invoke`）刻意不照抄它的「未登记 → 拒绝」，三条边界缺一不可：**只对在册受门者执法**（受门与否的唯一答案是 `runtime/capability_protocols.py::gate_feature_bindings()`，枚数以该函数现算为准、本页不手写计数）；**未受门 pass-through**（绑定表查不到即放行到后续门——今天绕过 pipeline 直呼 invoker 的在册能力全部未受门，照抄层 1 会把它们当场挡死）；**读不到状态 fail-closed**（谓词抛异常即拒绝，原因码 `feature_state_unavailable`，终态 `DENIED`、`via="feature_gate"`，照常入审计）。恢复类旁路 `RECOVERY_CAPABILITIES` 的集合真身唯一住 `feature_catalog.py`，两层都不另抄一份。因此准确说法是：层 2 的执法**机制**自 2026-09-23/24 起成立，但当前执法面为空（直呼者皆未受门），不得叙述成"已对所有能力执法"。

## 失败时看到什么

拒绝时能力不执行，`FeatureAccess.reason` 带原因码（`feature_disabled` / `feature_unregistered`）。未登记 id 每进程只产出一条 WARNING（`ProductFeatureGate._warn_unregistered` 的进程级去重账），既不刷屏也不静默吞掉出站文案。控制面查询失败即视为不可用，按不放行处理（fail-closed），不会退化成「查不到就放行」。

## 测试与验收

`tests/test_runtime_feature_gate.py`（三态判定、未登记去重告警、图不可用 fail-closed）、`tests/test_feature_gate_layer2.py`（层 2 门序先于角色门、未受门 pass-through 反例锁、谓词异常 fail-closed、拒绝入审计、`__call__` 纯转发、层 2 不抄门与恢复名单、根装配真谓词）、`tests/test_runtime_subfeatures.py` 与 `tests/test_phase0_3_features.py`（父子继承与 blocked_by 传导）、`tests/test_feature_store_integrity.py` / `tests/test_sqlite_feature_store.py`（功能图状态与修订一致性）。真机（重启后）：在控制面关掉一个功能，确认对应命令被温和拒绝且能力不执行；关掉父功能确认子功能一并被挡；构造未登记 id 确认走拒绝并有 WARNING。
