# v21r4-B RWC6-b 席位日志 — policy/security 迁移 domains/chat_reply

- 席位：RWC6-b（续收 HANDOFF-V21R4-20260918.md §6.1 挂账 RWC6 零动手项）
- 开工：2026-09-18
- 认领：已追加 v21r4-b-coordination.md 表尾；与 RET3（epic/steam+仅测试消费 44 张垫片退役）无清单冲突——policy/security 顶层真身不在其退役清单。

## 实盘勘误

- 交接书写「security/ 4 件」，实盘 `plugins/bot_unified_runtime/security/` 真身模块为 **3 件**：content_safety.py / injection.py / memory_sanitize.py（+ `__init__.py` 聚合转发，仅 re-export injection）。按「以实盘为准」执行，迁移总数 **8 件真身 + 2 个包 `__init__`**。
- policy/ 实盘 5 件：gate / quiet_hours / rate_limit / reply_budget / roles（+ `__init__.py` 聚合转发）。

## 消费方全量清单（开工前 grep 实测）

旧路径（`plugins.bot_unified_runtime.policy|security`）直连消费方，除根 `__init__.py`（相对导入 `from .policy import` / `from .policy.gate import` / `from .security.content_safety import`，RWC5-b 独占域不动，由垫片保活）外共 14 个插件内文件 + 26 个测试文件 + 1 个脚本：

- 插件内：domains/chat_reply/capabilities/chat.py、echo.py；character/persona_injection.py、persona_service.py、worldbook_service.py；pipeline/backend_unit.py；runtime/pipeline.py；domains/divination/api/facet.py；domains/ops/admin/debug.py；domains/ops/smoke/{route_demo,diagnostics,smoke,console_chat}.py；runtime/capability_protocols.py
- scripts/e2e_acceptance.py
- tests/ 26 个（见各批次记录）
- `from x import *` 形式：零。`importlib.import_module` 字符串形式：零。control_plane/bot.py：零引用。

## 方法

沿用 v21r2 media/link_parse 波垫片先例（PEP 562 `__getattr__` 活转发，模板取自 `plugins/bot_unified_runtime/console_chat.py`）。每件：真身整体移动（内容不改语义，包内相对导入随目录整体平移自洽）→ 旧路径留 PEP 562 活转发垫片 → 同波改写全部消费方 import 到新路径（含 tests）→ AST 验证旧路径零残余直连（垫片除外）→ 域测试实跑。

分批：批次1 gate+quiet_hours+rate_limit；批次2 reply_budget+roles+policy/__init__；批次3 security 3件+security/__init__。

## 批次1：gate / quiet_hours / rate_limit

（进行中）

### 批次1 记录（gate / quiet_hours / rate_limit）

- 真身移动：`plugins/bot_unified_runtime/policy/{gate,quiet_hours,rate_limit}.py` → `plugins/bot_unified_runtime/domains/chat_reply/policy/`（内容零语义改动；gate.py 内 `from .roles import …` 相对导入随目录整体平移，见下方依赖说明）。
- 垫片（旧路径，PEP 562 `__getattr__` 活转发，模板=console_chat.py 先例）：`policy/gate.py`、`policy/quiet_hours.py`、`policy/rate_limit.py`。
- 中途依赖踩坑记录：gate.py 依赖 `.roles`，roles 尚未迁移时 canonical 包暂不可导入（`ModuleNotFoundError: …chat_reply.policy.roles`）→ 立即续推批次2 恢复自洽，最终态无此问题。
- 消费方改写（同波，16 文件）：route_demo.py（gate）+ 15 个测试（gate 8 / quiet_hours 3 / rate_limit 5，含 test_sdd7_n4.py 两处：点路径+`import gate as gate_module` 空格形）。

### 批次2 记录（reply_budget / roles / policy 包 __init__）

- 真身移动：`policy/{reply_budget,roles}.py` → canonical；canonical `policy/__init__.py` = 旧聚合器逐字搬运（5 子模块 + 原 __all__）。
- 旧 `policy/__init__.py` → 包级 PEP 562 活转发垫片（保根 `__init__.py` 的 `from .policy import …` / `from .policy.gate import …` 零改动；根 __init__ 属 RWC5-b 独占域，本席未动）。
- 垫片新增：`policy/reply_budget.py`、`policy/roles.py`。
- 消费方改写（同波，17 文件）：插件 12（echo / persona_injection / persona_service / worldbook_service / backend_unit / chat_reply runtime pipeline / divination facet / ops admin debug×2 处 / ops smoke console_chat·diagnostics·smoke / runtime capability_protocols）+ scripts/e2e_acceptance.py + 测试 4（admin_roster_and_roles / operational_failures / persona_injection_v21 / auditfix_runtime_policy）。

### 批次1+2 域测试实跑（offline）

命令：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <19 个域测试文件> --basetemp="$TEMP/rwc6b-batch12" -p no:cacheprovider -q`
输出：**294 passed in 10.47s**（全绿）。

### 并发在飞观察（非本席改动，留痕）

- `tests/test_sdd7_n4.py` 工作树含他席在飞增补（2026-09-18 实弹反馈 promo-text 3 例 + `character → domains.chat_reply.character` 改写）；本席仅动其 policy.gate 两行 import，实跑 294 passed 已含该在飞态。

### 批次3 记录（security：content_safety / injection / memory_sanitize + 包 __init__）

- 实盘勘误落实：交接书「security 4 件」，实盘真身 3 件（content_safety / injection / memory_sanitize；`security/__init__.py` 仅聚合转发 injection，无第 4 真身）。按实盘执行。
- 真身移动：`security/{content_safety,injection,memory_sanitize}.py` → `domains/chat_reply/security/`（memory_sanitize 内 `from .content_safety import …` 相对导入随目录整体平移）；canonical `security/__init__.py` = 旧聚合器逐字搬运。
- 垫片（旧路径，PEP 562 活转发）：`security/__init__.py`（包级）+ content_safety.py / injection.py / memory_sanitize.py（模块级）。
- 消费方改写（同波，10 文件）：chat_reply/capabilities/chat.py（3 处）、ops/admin/debug.py（1 处）、ops/smoke/smoke.py（1 处）+ 测试 7（affinity_query×2 / auditfix_main_character×2 / content_safety_v2 / memory_sanitize / phase0_3_features×6 / prompt_injection / reaudit_20260911）。

## 验收证据（全部实跑）

1. **迁移清单**：8 件真身 + 2 个包 `__init__` → `domains/chat_reply/{policy,security}/`；旧路径垫片 10 个（policy 6 + security 4），全部 PEP 562 活转发（v21r2 media 波先例模板）。根 `__init__.py` 零改动（RWC5-b 独占域），由垫片保活。
2. **垫片同一性实跑**（python -c，venv 解释器）：old_pkg.evaluate_policy is new_pkg.evaluate_policy、security.check_prompt_injection is 新模块同一对象、两侧 `__all__` 全等、`gate._resolve_probability` / `gate._proactive_affinity_checker` 活转发同源 —— **7 项全 OK**。
3. **AST 零残余直连**：自写扫描器（绝对 import + 相对 import 按 level 解析到目标包；覆盖 plugins/tests/scripts/control_plane/bot.py 全量 .py）。首跑曾误报 0——扫描器 bug（`relative_to('plugins')` 吞掉 'plugins' 前缀致相对解析缺前缀），修正后终跑：**非豁免残余 = 0**；豁免面=根 `__init__.py` 4 处（`from .policy import` ×1、`from .policy.gate import` ×2、`from .security.content_safety import` ×1，设计内由垫片保活）；垫片文件自身对旧路径引用 0（只引 canonical）。
4. **域测试全绿**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest <26 个域测试文件：policy 19 + security 7> --basetemp="$TEMP/rwc6b-final" -p no:cacheprovider -q` → **394 passed, 2 xfailed in 13.86s**（批次1+2 中间态曾实跑 294 passed）。
5. **ruff（本席 18 文件：canonical 10 + 垫片 8）**：`python -m ruff check <四目录>` → **All checks passed!**（全树现存红属他席在飞，不属本席管）。
6. **doc_sync --check**：exit=0，通过（本席未增删测试文件，无测试文件数变化）。
7. **command_catalog --check**：`command catalog is current (77 topics)`，通过。
8. **verify_hashes --check**：**红，且为预在飞红、非本席引起**——13 项漂移中 11 项全在 render 域/设计文档（theme_tokens.py、bridge.py、templates、rendering-contract.md、DESIGN-SPEC.md 等，本席禁改域）；另 2 项（ops/admin/debug.py、chat_reply/capabilities/echo.py）虽属本席同波改写文件，但**反演实证漂移先于本席**：把本席 import 改写字符串反演回旧值后重算 sha256（LF 归一口径同 verify_hashes），两文件反演哈希仍 ≠ 清单记录值（debug.py 反演=3d5677d8…≠记录 1299033c…；echo.py 反演=3fe9002b…≠记录 b4f08863…），即清单录制后他席在飞改动已使其漂移。按指令**不自行 --write**，留波次整合席在波收敛后统一重录（此刻 --write 会把他席未确认字节一并烤进清单）。

## 席位终态

- 迁移：policy 5 件 + security 3 件（实盘）+ 2 包 `__init__`，全部完成；旧路径 10 垫片全活。
- 全库旧路径直连消费方（除根 `__init__.py` 设计豁免）已同波清零。
- 禁改域（theme_tokens/render/acceptance-matrix 等）零触碰；无 git 写操作；无子代理；无真实 LLM/发送/重启。
- 已知并留痕：test_sdd7_n4.py 工作树含他席在飞增补（promo-text 3 例等），本席仅动其 2 行 policy import，实跑全绿含该在飞态。
