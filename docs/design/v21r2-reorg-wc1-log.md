# v21r2 重组 RWC1 席执行日志（W15a = chat_reply 子波 1/5：character 人格侧 23 件）

> 席位：RWC1（板块重组执行·chat_reply 热区·子波 1/5）。开工 2026-09-18。
> 方案锚：docs/design/v21r2-reorg-plan.md §2.3 character/（23 件→domains/chat_reply/character/）+ §5 W15 拆分子波表第 1 子波。
> 纪律：零 git 写操作（文件系统 mv）；固定解释器 ChatBot_Runtime/venv；PYTHONDONTWRITEBYTECODE=1 + basetemp=%TEMP%/v21r2-rwc1 + -p no:cacheprovider；禁 dev.ps1。

## 一、波前取证（实跑）

1. **占域冲突核对**：COORDINATION 实时占域——RW12(subscribe)/RW14(render)/RW16(location)/S9(control_plane) 在飞，全部零触碰；RW13(assistant)/RW5/RW9/RW10/RW11 已收官。W15 其余子波（llm_engine/policy+security/runtime 核心/capabilities）未开工，本席只做 character/。
2. **真身/垫片清点**（head -1 全量实证）：character/ 34 py 中，reminders/notes_store/daily_assist/draw_store/media_registry/kb_wiki 6 件已是前波垫片（零触碰）；knowledge_service/memory_service/memory_store_v21/teaching_service 4 件为 S8 交付真身（**SKIP 登记：归属待 S8 收官波统一**，V2 席 09-17 刚修 memory_service 四 bug，在飞面让位）；其余 23 件真身 = 本波移动对象（含 V1 席新落 persona_service/worldbook_service，按方案书归属落 character/ 子包，不另立 persona/）。
3. **affinity.py 归属裁决**：方案 §2.3/§5 列入 15a character 23 件，§4.1 又标 W15c 协调——冲突以 §2.3 映射表+brief「以方案书映射表为准」裁决**纳入本波**；取证 R4 席（v6 平滑层）已于 09-17 收官、无在飞编辑者，mv 为内容中性操作（WIP 随迁零内容改动，git status M 态保留）。
4. **消费面全量扫描**（rg + AST 双轨）：74 文件 152 处 AST import 命中（root __init__.py 20 处含大量**调用期惰性导入**、capabilities 族 9 文件、policy/runtime/backend_unit/console_chat/config_readiness/smoke、他域 canonical 8 文件、scripts/knowledge_bench、tests 50 文件）。
5. **monkeypatch 清单**（字符串式+对象式+logger 名锚三轨）：
   - 字符串式：test_memory_router_reuse ×4（memory.SQLiteMemoryRepository×2 + memory_extract.extract_memory_texts×1 于多行 setattr 中，初扫正则漏网、AST 补网）；test_moegirl_question_fix ×2（vector_knowledge.build_vector_knowledge_provider，多行 setattr 漏网、AST 补网）。
   - 对象式（模块别名 setattr）：test_affinity_numerical/v21_budget/v21/v6_smoothing/perf_p3（affinity_module ×6 处）、test_perf_p1（vk.httpx + vector_knowledge._ANN_BUILD_BATCH_SIZE）、test_knowledge_mtime_cache/test_prfix_eat（vk/providers.load_character_document）、test_quirks_scope/perf_hotpath/sdd7_n4/identity_preference_commands（providers.build_runtime_data_path/build_addressing_preference_store）、test_creator_dualname（addressing.CREATOR_ALIASES/CREATOR_NOTE ×6）、test_trend_write（trend_mod.os，读经垫片已同对象、仍归一 canonical）。
   - logger 名锚：test_reflection:481 caplog logger=character.reflection → 随真身 __name__ 改 canonical。
   - **正则三盲区教训（AST 终验价值实证）**：①多行 setattr 字符串参数（正则单行漏 4 处）②函数级缩进 `import X as Y`（`^` 锚漏全部缩进对象式）③`from package import submodule` 绑定子模块形态（AST oldmod 函数对裸包名不报，二轮专项补扫抓出 12 文件）。
6. **文本路径锚**：tests/test_copy_redline_gate.py 为唯一 slash 形路径锚文件（addressing.py 豁免标签 ×2 处）；verify_hashes/auto-facts/runtime_layout_smoke/capability_registry/base_router 零 character 路径锚（rg 实证）。

## 二、移动与垫片

- **建包**：domains/chat_reply/__init__.py + domains/chat_reply/character/__init__.py（纯 docstring 零导入，防环）。
- **mv 23 件**（文件系统 mv）：addressing/affinity/documents/emotion/glossary/history/memory/memory_extract/mood/persona_service/persona_set/providers/quirks/reflection/relationship/session_identity/shared_export/shared_group/source_summary/temporal/trend/vector_knowledge/worldbook_service → domains/chat_reply/character/。
- **真身随迁修正**：相对导入→绝对 canonical（sed 全量：providers 13 头部+1 惰性、reflection 4 惰性、source_summary/vector_knowledge/memory_extract/worldbook_service 各 1）；旧绝对 sibling 路径同切 canonical；providers.py:909 与 glossary.py:53 **parents[3]→[5] 深度锚修正**（方法⑩预判命中，见 §三）+ glossary 深度注释同步。
- **垫片 23 张**：PEP 562 活转发形态（`__getattr__`+`__dir__` 实时解析 canonical，RW11/W16 先例）——治「root __init__.py 调用期函数级 import×测试 canonical 补丁」快照时序分裂，**root __init__.py 零改动**（20 处惰性导入经活转发天然见 canonical 补丁，RW13 双跳陷阱根修无需重演）。旧 character/__init__.py 原样保留（经垫片链同对象，尾声波才退役）。
- **同一性冒烟**：23 模块全量公开 callable/class 名 `is` 断言 402 名全同对象；包 init 链（character.CharacterContextProvider is canonical providers 同名类）同对象。

## 三、波内红与根因（10 红逐一，全部本波归因、当波清零）

首轮关键词扫 10 failed，根因两类：
1. **parents[3] 深度锚失效 ×6**（glossary_seed ×3+glossary_recall ×1 直接红；quirks_scope×2 间接红=proposer 经 build_runtime_data_path 落错根后 tmp 注入断言空集）——providers.py:909（build_runtime_data_path sys.path 注入根）与 glossary.py:53（SEED_GLOSSARY_PATH 随包种子）原指向仓库根，迁移后 parents[3]=bot_unified_runtime → 种子/脚本全 miss。修=parents[5]+注释同步。**教训：§2.3 移动文件的 Path(__file__) parents 锚必须在移动同波 rg `parents\[` 全量核查——rg 相对导入清单抓不到这类锚。**
2. **垫片子模块绑定 patch 陷阱 ×4**（knowledge_mtime_cache ×2+prfix_eat ×2）——`from …character import vector_knowledge/providers` 绑定的是**垫片模块对象**，setattr 落垫片 dict 而 canonical 真身 globals 不动 → load 计数 0。修=12 文件子模块绑定导入全量切 canonical（含关键词扫未选中但同形态的 creator_dualname/perf_hotpath/sdd7_n4/trend_write/identity_preference_commands/glossary 两文件——**-k 关键词不命中≠无陷阱，按形态全量清**）。

## 四、终验与回归（全部实跑）

| 门 | 命令 | 结果 |
|---|---|---|
| AST 名字级终验 | ast.walk 全树（tests+plugins+scripts+bot.py）三轨扫描 | 字符串常量旧路径点形式 0；slash 形 2 处=copy_redline_gate 旧标签 LEGAL 保留（豁免集双路径+测试断言双覆盖） |
| 域关键词扫 | pytest tests -k "affinity or persona or addressing or mood or quirks or reflection or glossary or memory or temporal or trend or shared_group or session_identity or emotion or relationship or vector or knowledge or worldbook or nickname or identity" | **755 passed** 0 failed 0 error（三轮：首轮 10 failed→修复；二轮撞他席瞬态 240 收集错→单文件复跑 24 passed 自愈；三轮 745+10=755 全绿。插播一轮 9 ERROR=test_control_plane_metrics fixture 交互，standalone 95 passed+复跑未现=flaky 非本波归因） |
| 消费方补扫 | 关键词未覆盖的 17 文件（chat_and_sources/detail_priority/kb_wiki_sync/reactions/soak/phase0_3/prompt_injection/capability_registry/daily_assist/reminder_tone 等） | 289 passed 2 xfailed |
| 门禁族 | verify_hashes --check + doc_sync + no_data_writes + user_copy 门 + copy_redline_gate（gate_scope 已扩 domains/chat_reply/\*\*/\*，canonical addressing.py 入豁免集+sanity 断言） | verify_hashes exit0 + **46 passed** |
| 全库收集 | pytest tests --collect-only -q | **7820 collected 0 error**（垫片断链在此现形，零断链） |
| 插件冒烟 | import 插件+mail_adapter+23 垫片同一性 | OK；402 名 `is` 同对象 |
| ruff | 波面 43 文件 | 18 错全 I001（canonical 长行触发 import 排序）--fix 归零，All checked |
| mypy | dev.ps1 权威口径复刻：--explicit-package-bases --ignore-missing-imports plugins（cache 外置 Runtime） | 604 文件 4 错**全外部归因**：control_plane/api/platform.py ×2（#36 A12 既有台账）+ domains/creation/tts/contracts.py ×2（并行 W-PA1 席在飞新件）；chat_reply 面 0 |
| runtime-layout | scripts/runtime_layout_smoke.py | 2 FAIL=BOT_KNOWLEDGE_FILES 用户外部目录两 .md 缺失（RW5/RW10/RW11/RW13 四席同证环境面，非本波引入） |
| 树卫生 | find 缓存/缓存目录 | 本波面 0 残留；全树 10 处 __pycache__ 全在 domains/creation/（并行席产物，未代清） |
| qx.json | sha256 | e8285e77… 完好（W3 canonical 位 domains/weather/assets/） |

## 五、SKIP 与移交登记

1. **S8 收官波统一归属**：memory_service.py / memory_store_v21.py / knowledge_service.py / teaching_service.py 留守 character/ 旧位（S8 交付+V2 席在飞修复面）；其 import 旧路径 character.memory 经垫片活转发同对象，收编时再切。
2. **affinity.py §4.1/W15c 归属冲突**已按 §2.3 裁决纳入本波（§一.3）；若 W15c 席对 affinity 有增量动作，以 canonical 路径为准。
3. **树卫生移交**：domains/creation/ 10 处 __pycache__ 属并行 W-PA1 席，请该席自清（PYTHONDONTWRITEBYTECODE 纪律）。
4. layout 环境面 2 FAIL 需用户归位 `AI智能体有关材料` 目录或改 .env BOT_KNOWLEDGE_FILES（四席同证，非代码问题）。

## 六、未做与偏差

- 未跑 dev.ps1 全量门（席位禁令）；未触 capabilities/chat.py、runtime/pipeline.py、runtime/ingress.py、root __init__.py、sources/、output/、llm/、policy/、security/（后续子波+热区禁触面，零越域）。
- 未 commit（禁 git 写）；工作树呈现 = 旧位 23 文件内容替换为垫片 + 新域 25 文件（23 真身+2 包 init）+ 20 个测试文件改写 + 本日志/COORDINATION。
- 并行瞬态如实登记：二轮扫描撞 240 收集错（他席中间态，单文件取证 24 passed 自愈）；control_plane_metrics 9 ERROR 一轮未再现（flaky）。
