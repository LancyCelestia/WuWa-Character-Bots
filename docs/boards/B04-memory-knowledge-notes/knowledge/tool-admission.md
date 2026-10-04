# 知识库与检索 · 工具注册审批账

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B04.knowledge · 工具注册审批账

- 层级：一级 B04 → 二级 knowledge → 三级 `tool-admission`
- 实现落点：`plugins/bot_unified_runtime/domains/core/search`、`plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/question_intent.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

管「模型能调用哪些工具」的审批账。此前 MCP 腿是「schema 在册即白名单」——服务器交来什么工具名，模型可选面与执行面就照单全收，服务端漂移/供应链污染能让新工具名静默进入执行面。本账补 fail-closed 审批：外来工具名**首次出现** ⇒ 落 pending 审计行并拒执行，管理员经 `approve`/`deny` 显式登记后才放行/拉黑；内置工具以源内显式名册 `NATIVE_TOOL_ROSTER` 为账默认视为已批准（存量兼容、零落盘、零行为变化）。账本＝JSONL append-only（`consent.JsonSafetyLedger` 同族形态）。

生效条件：本模块自身**零接线 ⇒ 今天零行为变化**；接线挂点已点名为 `chat.py::_mcp_tools_schema` 与派发腿，接线属代码面改动、重启生效。

## 怎么调用

真身 `domains/core/search/native_tools.py`（本页账体段）：

- `ToolAdmissionLedger.admit(tool_name, *, source="mcp")`——派发腿唯一准入口：在册工具（grandfathered）直接放行且零落盘；查账 approved 放行、denied 拒（拒绝是终态）、无账/pending ⇒ 先落 pending 审计行再拒（同工具已有 pending 行不重复落账，防调度循环刷爆账本）；畸形工具名（空/超长）判 denied 且不落账。
- `approve(tool_name, *, actor, note)` / `deny(...)`——管理员批准/拒绝唯一入口；拒绝后 `admit` 恒 denied（后写覆盖前写）；写失败原样抛 `ToolAdmitWriteError`（批准必须落得住账）。
- `filter_mcp_tools_schema(tools, ledger)`——MCP schema 面统一过滤口，返回 `(放行 schema 列表, 被拒工具名元组, 审计标签元组)`；调用方拿第一列替换原 schema、第三列落 audit_tags，**禁在调用点自判**（第二真身）。
- `pending_names()` / `status_of(tool_name)`——待批清单与现行审批态只读口（admin 命令面接线面）；pending 回执话术常量 `TOOL_ADMIT_COMMAND_HINT`，审计标签 `TOOL_ADMIT_AUDIT_TAG`（`tool_not_in_admit_ledger`）。
- 账本落点由装配期构造时显式给目录；同文件另有内置工具投影面（`build_native_tool_schemas`/`native_tool_for_name`/`roster_violations`——白名单×`WRITE_OR_PRIVILEGED_DENYLIST` 拒绝清单双查、交集必须为空）与工具结果回注口 `guard_tool_result_text`（真身 `injection.guard_secondhand_text`，延迟 import 避装载环）。

## 开关与参数

审批账自身**无专属配置键**：账本目录是构造参数， approve/deny 行为不设开关。同模块内置工具总开关 `bot_chat_native_tools_enabled`（缺省 False，fail-closed：只认严格 True、键缺席判关），四面同生（config 字段＋`settings.py` 热改档＋`.env.example`＋catalog）由测试件执法，改键重启生效。名册枚数、拒绝清单成员随代码漂移，一律以 `NATIVE_TOOL_ROSTER` / `WRITE_OR_PRIVILEGED_DENYLIST` 现算为准，不在本页抄清单。

## 失败时看到什么

- 账本读不了/写不了 ⇒ `admit` 一律按 pending 拒执行并带 note，**绝不因账本缺席放行**（fail-closed）。
- 未批工具被拒时模型可选面见不到该工具；接线方落审计标签 `tool_not_in_admit_ledger`，管理员侧提示「没批之前我只记账、不执行」（`TOOL_ADMIT_COMMAND_HINT`）。
- 账本里的烂行（半行 JSON）逐行跳过、不报废整本；`pending_names()` 读挂了回空表；`_append` 写失败（目录建不了/盘写失败）抛 `ToolAdmitWriteError`，批准面必须原样抛、不得静默吞。

## 测试与验收

`tests/test_native_tools_admission_ledger.py`（常驻门，锁四判据：存量兼容零落盘、fail-closed 拒执行、拒绝终态、pending 防刷；全离线、账落 tmp_path）、`tests/test_native_tool_admission.py`（账本 API 与话术常量面）。同文件投影面另有 `tests/test_native_tools.py`（AST 字面锁：文件内 `bot.*` 字面量必可反查中央在册表）与 `tests/test_native_tools_config_faces.py`（总开关键四面同生锁）。真机验收无独立条目：接线前零行为变化；接线后以「外来工具名首见被拒入审计、管理员批准后放行」为观察点。
