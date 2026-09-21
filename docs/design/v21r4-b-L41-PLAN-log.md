# L41-PLAN 席位日志（v21r4-B，2026-09-18）

> 断点续跑依据。本席=只读取证+一份执行预案文档，零代码改动、零 git 写操作、零子代理、零真实 LLM 调用。

## 进度

- [x] 2026-09-18 开工：coordination 表追加席位行（`docs/design/v21r4-b-coordination.md` 末尾「L41-PLAN | L41 执行预案 | docs/design/v21r4-l41-exec-runbook.md（只读+文档）」）。
- [x] 只读取证完成（全部实读核实，非转述）：
  - memo：`docs/design/v21r4-L41-decision-memo.md` 全文；
  - 装配先例：`runtime/service_wiring.py` 全文 185 行（:53-58 ids / :64-77 gates / :80-87 build 签名 / :96-106 fail-open / :136-161 teaching 模板 / :158-159 memory 刻意不传挂点 / :165-184 注册表三件）；
  - 根装配段：`plugins/bot_unified_runtime/__init__.py:4124-4144`（:4126 主门 / :4132 register / :4139-4144 整段 fail-open）；
  - 门控测试范式：`tests/test_v21_wire_svc_assembly.py` 全文 312 行（L41 常驻锁 :226-228、gates 整 dict 断言 :98-103、teaching 注入模板 :186-196、fail-open :269-283、根静态断言 :305-311）；
  - 直构实证：`tests/test_memory_service_v21.py:60-63`（make_service）+ :27/:40 垫片导入；
  - 实现真身：`domains/chat_reply/character/memory_store_v21.py:88-114`（path 必填/WAL/busy_timeout/急切建表）、`memory_service.py:27-32/:55/:183-185/:204-214/:235/:286`；
  - config：:165-178（teaching 先例+主门+两分门）、:184-189（旧 memory 键）、:1053-1116（path_fields+重映射循环，teaching 行=:1110）；
  - 重映射：`scripts/runtime_paths.py:52-75`；
  - B 案风险锚点：`memory.py:202/:205-217/:237-240/:243-248`、根 `__init__.py:317-319/:363-382/:6237-6245`、`chat.py:779-783/:1478/:1509/:1528/:1567-1568`、`admin/debug.py:1175`、`smoke/diagnostics.py:59/:160/:205/:320`；
  - 登记面：`docs/db-owners.md:19/:54/:55`、`docs/config-catalog-full.md:824-825`、`.env.example:675-688`、`tests/test_doc_sync_gates.py:321/:329`；
  - 前置：`docs/design/v21r4-b-wave-snapshot.md`（§二=:45，组2=§2.2 :82-96，实读原文）、`HANDOFF-V21R4-B-20260918.md:158`（实读原文）。
- [x] 勘误三处（memo 坐标 vs 实读）：`__init__.py:361-382`→def 在 :363；`/bot memory` 路由 :6240→:6237-6245（门 :6242）；`chat.py:2414` 处无 memory 内容→实为 :779-783/:1478/:1509/:1528/:1567-1568。已写入预案 §四。
- [x] 预案落盘：`docs/design/v21r4-l41-exec-runbook.md`（A 案 12 步施工坐标+代码草图+测试计划+B1 差异点与风险四条+B2 存目+共同项 id/fail-open/回滚+前置授权边界+unknown 清单）。

## 交付清单（完成标准对账）

| 项 | 状态 |
|---|---|
| `docs/design/v21r4-l41-exec-runbook.md`（执行预案） | 已落盘（本席唯一交付物） |
| `docs/design/v21r4-b-coordination.md` 席位行 | 已追加 |
| 本日志（断点+交付清单） | 已写（本文件） |
| 代码改动 | **零**（L41 一行未动；config.py/service_wiring.py/根 `__init__.py`/全部 .py 零触碰） |
| 禁改文件 | 未触碰：theme_tokens.py / tests/render_hashes.json / domains/render/** / backend-v2-acceptance-matrix.md |

## 状态红线

预案≠授权≠裁决：L41 仍 **not_wired**，两案均待用户在 wave-snapshot §二组2（:82-96）勾选后方可由装配席按预案施工；全文假设语态，不得读作已生效。

## 遗留（超出本席范围，未做）

- 无本席遗留。下游依赖：用户裁决 → 装配席按预案 §2（A）或 §3.1（B1）施工；B2 须另立迁移设计席。
