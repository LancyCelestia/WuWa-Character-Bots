# 能力注册表与调度壳 · 声明源与投影表一致性

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B02.capability-registry · 声明源与投影表一致性

- 层级：一级 B02 → 二级 capability-registry → 三级 `keystone-declarations`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/service_wiring.py`、`plugins/bot_unified_runtime/capabilities`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

一个能力一行、一行含它全部登记属性的权威声明表。它不执行任何东西，只回答「这个 bot 在册哪些路由能力、各自叫什么 id、多少优先级、算不算命令、绑哪个 matcher」，并作为 `base_router` 字面注册表、接口清单、内部说明三处投影的唯一上游。

## 怎么调用

真身是 `plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py::ROUTE_CAPABILITY_DECLARATIONS`，每行一个 `RouteCapabilityDecl`。字段语义写在 `capability_registry.py::RouteCapabilityDecl` 的 docstring：`kind`/`value` 与 `base_router.py::RouteKind` 成员一一对应；`has_rule=False` 表示该 kind 不在 `build_route_rules` 注册规则（当前仅 `IGNORE` 兜底席）；`command=True` 表示属于命令席位（群门禁按确定性命令处理）；`matcher_name` 是注册表里绑定的判定函数名。`execution` 可空：填了＝这条能力已在册且可经中央 invoker 执行，没填＝只在册未接入。

### 一致性怎么保证（投影表三方对齐）

同一能力的 kind/capability_id/priority/label/reason/tags/matcher 名在三处各写一份：`capability_registry.py` 声明表、`base_router.py::build_route_rules` 字面表、`echo.py` 帮助表。`tests/test_capability_registry.py` 把声明表与注册表逐行逐字段比对，并附写死快照，漏改任一处即红。新增一个能力的完整登记流程见同板块 `new-capability-checklist`。

## 开关与参数

本表是纯声明数据，不读配置、无运行时开关。它描述的每个能力是否真的生效，取决于能力自身代码与配置门，与这张表无关。

## 失败时看到什么

表与代码不一致时不是运行时故障，而是 `tests/test_capability_registry.py` 直接红。若某能力在表里 `execution=None` 却在文档被写成「已接中央调度层」，那属叙述失实——中央调度层的接入进度以板块 README 的 Wave 表为准，Wave 1–4 尚未做。

## 测试与验收

`tests/test_capability_registry.py`（一致性锁）、`tests/test_capability_result_unique.py`（两个同名 `CapabilityResult` 分层归并唯一性门）。在册答案与「登记但未接入」的缺口账见 `plugins/bot_unified_runtime/runtime/capability_protocols.py` 与 `tests/test_descriptor_wiredness_ledger.py`。
