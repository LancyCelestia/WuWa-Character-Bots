# v21r2 板块重组·RWC3 席施工日志（chat_reply 子波=capabilities/chat.py 本体+capability 侧近邻）

> 席位：RWC3。范围=方案书 §2 L264 七件：`capabilities/{chat,echo,affinity,memory,poke,group_info,user_copy}.py` → `domains/chat_reply/capabilities/`。
> 纪律：文件系统 mv、内容零改动；PEP 562 活转发垫片；monkeypatch 命中波内清零+AST 终验；禁 git 写、禁 dev.ps1、禁触 RWC1（character）/RWC2（llm_engine）/15c/15d 热区。
> 固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；basetemp=`%TEMP%/v21r2-rwc3`。

## §1 波前取证（实跑）

- **规模**：chat.py 155843B（≈3900 行）、echo.py 277886B（全项目最大，帮助注册表 77 topics）、affinity.py 18035B、group_info.py 16296B、poke.py 9011B、memory.py 6621B、user_copy.py 6416B。
- **七件内部零相对导入**（全绝对 `plugins.bot_unified_runtime.*` 旧路径）→ 真身随迁**零内容改动**：character/llm/policy/runtime/output 依赖全部经旧路径（RWC1/RWC2/RW14 已迁域者过垫片，未迁者真身）。
- **零 `__file__`/parents[N] 深度锚**、零 `__all__`（仅 affinity.py L410 一处）、零星号导入消费、零 NoneBot 装配期副作用（无 matcher/driver hook；nonebot 仅函数内惰性探测）。
- **生产消费面（全部 from-import 名字形态，垫片活转发覆盖）**：根 `__init__.py`（模块级 3 处 + 函数级 8 处）、backend_unit/console_chat/smoke/prompt_preview/debug/runtime_admin、runtime/{base_router,pipeline}、scripts/{e2e_acceptance,render_card_samples}、15 个已迁域真身以 `from ...capabilities import user_copy` 持**模块对象**（属性访问经垫片活转发，patch canonical 双向可见）。
- **monkeypatch 命中清单（AST 全量扫描 v3，两次修正扫描器盲区后定稿）**：
  - 对象式 17：test_prfix_chat×5、test_bgroup_chat_pipeline×6（chat_module）；test_video_reply_flow×3（_FUZZY_INJECTION_AT/_DEEP_REANALYSIS_AT/describe_video）；test_detail_and_priority×2（build_chat_result）；test_meme_domain_fixes×1（poke._POKE_LAST_CAP）。
  - 字符串式 2：test_operational_failures:532/542 `...capabilities.chat._mcp_client_modules`（chat.py:1842 模块内全局调用 → 必须改指真身）。
  - 只读模块绑定（垫片覆盖零改动）：test_internal_marker_regex/test_video_seam/test_v21r2_acg_search/test_user_copy_unification_gate:484/test_help_entries_coverage:167/test_user_copy_pool:13。
- **文本/文件路径锚清单**：
  - `tests/verify_hashes.py` TRACKED_FILES 含 `capabilities/echo.py` → 随真身改新路径 + `--write` 重录。
  - `scripts/command_catalog.py:23` ECHO_SOURCE、`scripts/doc_sync.py:50` echo 路径：**静态文本提取 _HELP_ENTRIES**（垫片无表体必炸）→ 改指真身。
  - `tests/test_documentation_consistency.py:365` 四文件 read_text 拼 source 找 capability 入口 → echo 项改真身。
  - `tests/test_user_copy_unification_gate.py`：FILE_WHITELIST user_copy/group_info、UNIT_WHITELIST echo、Q03_SCOPE group_info、Q04 read_text chat/echo 五处锚随真身（真身迁后仍全在 RUNTIME_PKG 扫描面内，白名单不随迁=真身池体句式裸扫必红）。
- **log_collectors._SUBSYSTEMS**：`capabilities.*` 前缀新旧均无子系统分类（旧=`capabilities.chat`→bot，新=`domains.chat_reply.capabilities.chat`→bot）→ 零事件源降级，无需补锚。
- **垫片期纪律复核**：无 `from x import *` 消费方；PEP 562 `__getattr__` 对 `from 垫片 import 名`/hasattr/dir 全部活解析；capability_protocols.py（他席 `??` 在飞 WIP）语法破损致门禁 scan_package SyntaxError=**波前既有红**（与本波零交集，登记归因）。

## §2 波前基线（实跑 2026-09-18）

`pytest test_user_copy_pool + test_user_copy_unification_gate + test_capability_registry + test_prfix_chat + test_bgroup_chat_pipeline + test_video_reply_flow + test_video_seam + test_detail_and_priority + test_meme_domain_fixes` → **85 passed / 5 failed**：
- test_user_copy_pool ×4（fx/moegirl 文本锚仍指旧垫片路径，W7/W16 已迁域遗留的「read_text+旧路径」盲区，RW6 §六已登记同类）→ 本波作为 user_copy 池门禁网随波修复（借修登记，不动 fx/moegirl 真身）。
- test_user_copy_unification_gate::test_current_tree_no_scattered_failure_copy ×1 = scan_package ast.parse 撞 `runtime/capability_protocols.py`（他席在飞未收口 WIP `??`）SyntaxError，非文案违例；**波前既有**，尾波复测归因。
- 插件导入冒烟：chat/echo(77 topics)/user_copy/poke/affinity/memory/group_info 全 OK。

## §3 移动执行

（施工中，随步落盘）

## §3 移动执行（实跑）

- **mv（文件系统 move，内容零改动）**：7 件 → `plugins/bot_unified_runtime/domains/chat_reply/capabilities/`（chat/echo/affinity/memory/poke/group_info/user_copy）+ 新建包 `__init__.py`（域内 docstring）。真身随迁修正=**零处**（波前实证：七件全绝对旧路径导入、零 `__file__` 深度锚、零相对导入、零装配期副作用；character/llm/runtime/output 依赖全部经旧路径垫片或未迁真身解析）。
- **旧位 7 张 PEP 562 活转发垫片**（W11/W16 同款形态，`__getattr__` 实时解析 canonical）：
  - 同一性断言：7/7 模块全命名空间逐名 `is` 同一（chat 214 名/echo 78/affinity 34/memory 20/poke 17/group_info 32/user_copy 7，收波终验复跑）；`_HELP_ENTRIES` 77 topics 经垫片与真身同一；user_copy 池对象同一（15+ 生产模块持垫片模块对象双向可见）。
  - 生产消费面零改动实证：根 `__init__`（模块级 3+函数级 8 处）/backend_unit/console_chat/smoke/prompt_preview/debug/runtime_admin/base_router/pipeline + 15 个已迁域真身的 `from ...capabilities import user_copy` 模块对象——插件根包导入冒烟 OK。
- **生产代码改动=0**（垫片活转发全覆盖；方案「echo 薄壳永久保留」登记入退役条件）。

## §4 测试/门禁同波改写（13 文件 + 3 生成物）

- **monkeypatch 命中波内清零 19 处**（AST 扫描器 v3，修正两代盲区后定稿；终验旧路径补丁目标=0）：
  - 对象式 17 → 改指真身：test_prfix_chat（import 行 1 处，setattr 5）、test_bgroup_chat_pipeline（1/6）、test_video_reply_flow（1/3：_FUZZY_INJECTION_AT/_DEEP_REANALYSIS_AT/describe_video）、test_detail_and_priority（函数级 2/2：build_chat_result）、test_meme_domain_fixes（1/1：poke._POKE_LAST_CAP）。
  - 字符串式 2 → 改指真身：test_operational_failures:532/542（`...capabilities.chat._mcp_client_modules`，chat.py:1842 模块内全局调用必指真身）。
  - 只读模块绑定/名字导入（test_internal_marker_regex/test_video_seam/test_v21r2_acg_search/test_help_entries_coverage:167 等）垫片覆盖零改动（同一性实证）。
- **文本/文件锚随真身**：test_user_copy_unification_gate（FILE_WHITELIST user_copy+group_info、UNIT_WHITELIST echo、Q03_SCOPE group_info、Q04 read_text chat/echo、scan_face exists 锚、5 处合成 rel_path、_chat_mod import）；test_documentation_consistency:365 echo read_text；tests/verify_hashes.py TRACKED_FILES echo 项 + `--write` 重录（19 项，--check exit0）；test_verify_hashes_coverage.py BUILDER_SOURCES echo 项。
- **静态提取器改指真身**（垫片无表体必断供）：scripts/command_catalog.py ECHO_SOURCE + 生成头口径；scripts/doc_sync.py `_help_topics()`。`--write` 再生成 docs/command-catalog.md（如实吸收并行在飞批 help 增量 75→77：功能管理/语音两 topic=他席 WIP，机器派生）与 COMMANDS.md 真相源行口径；docs/auto-facts.md 重生成（echo 路径换新 + 并行 WIP 计数吸收：RouteKind 34 含 TTS/topics77/tests394/config599，W14 先例）。
- **借修登记（user_copy 池门禁网，波前既有 4 红）**：test_user_copy_pool.py `_assert_site` 仍指 fx/moegirl 旧垫片（W7/W16 已迁域「read_text+旧路径」盲区，RW6 §六登记同类）→ 升级为 `_TRUE_SITES` 真身解析表（fx/moegirl/music/subscribe/subscribe_v2/today_history/file_exchange/echo/debug/runtime_logs 逐文件映射）；施工中并行 RWOC ops 波将 debug/runtime_logs 迁 domains/ops/admin/ → 解析表即时跟进（解析器职责=永远指真身）。

## §5 回归（实跑，解释器=Runtime venv，basetemp=%TEMP%/v21r2-rwc3）

- 命中测试批（10 文件）：126 passed（修后即时）。
- **chat 全域 63 文件显式批（rg 引用面穷尽）**：**1241 passed / 2 xfailed / 0 failed**。
- user_copy 门+池：20 passed；help 族+catalog+doc_sync+cross_validation+verify_coverage+autosync：234 passed；门禁合计 46 passed（test_doc_sync_gates 4 + cross_validation + verify_coverage + autosync）。
- verify_hashes --check exit0（19 项）；doc_sync --check 绿；command_catalog --write exit0。
- 全库 collect-only：**7934 collected / 0 收集错误**。
- ruff 本波面（7 真身+7 垫片+域 init+13 改写文件）：All checks passed（--fix 自收 5 处 I001）。
- mypy 权威口径（--explicit-package-bases --ignore-missing-imports plugins，708 文件）：4 错全外部既有（control_plane/dispatcher×2+api/platform×2，台账 #36 级），本波 0 错。
- 树卫生：本席全部命令 PYTHONDONTWRITEBYTECODE=1+-p no:cacheprovider+basetemp 外置，零自产缓存；qx.json e8285e77 完好；`domains/*/data` 为源码包非运行残留。**并行席在飞 pycache 实时再生（90 目录，与他席 pytest 同窗）如实登记，留尾声波静默期统一清理**。
- runtime-layout：唯一 FAIL=BOT_KNOWLEDGE_FILES 两用户外部目录缺失（RW5/RW9/RW10/RW11/RW12/RW15/RW16 同款环境面，非本波）。

## §6 偏差与登记

1. **波前既有红 5**：test_user_copy_pool×4（W7/W16 锚遗留，本波借修复绿）+ user_copy 门 scan_package 撞他席 `runtime/capability_protocols.py` 语法破损 WIP（在飞，随后自愈复绿）——均非本波引入。
2. **并行事件**：RWOC ops 波施工中迁 debug/runtime_logs/feature_control（与七件同目录邻接，零文件交集，唯一涟漪=test_user_copy_pool 解析表即时跟进）；RW6 登记的 reminder/weather/moegirl Q03 旧路径锚遗留未动（非本波文件，扫描面已注明）。
3. **methodology 增补**：①AST 扫描器对 `from pkg import mod as alias` 形态的绑定登记盲区（v2 漏 17 处中 11 处，v3 修复）；②「read_text+旧路径」静态锚门在本波三度现形（command_catalog/doc_sync/doc_consistency/pool 门），垫片期应全库 rg `capabilities/<名>.py` 斜杠形态逐域清点；③同窗多波并行时，真身解析表（_TRUE_SITES 类）优于硬编码路径，波间跟进成本低。
4. 禁触面零触碰：RWC1 character/RWC2 llm_engine/15c policy+security/15d runtime 核心/S10/S11/RWPA1 未动；git 零写操作；未 commit。
