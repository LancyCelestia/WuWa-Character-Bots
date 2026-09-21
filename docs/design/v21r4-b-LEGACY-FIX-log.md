# v21r4-B LEGACY-FIX-c 席日志（2026-09-19）

> 席位=LEGACY-FIX-c｜工作包=RWC1 SKIP 四件盘点与转正 + echo「(44)」计数漂移｜接替两任平台验证码超时阵亡前任（均零落盘）｜全程离线，零 git 写、零子代理、零真实 LLM/发送/重启。

## 一、任务一：RWC1 SKIP 四件——盘点结论=非 pytest SKIP 标记，系台账登记，且已闭环转正

### 1.1 定性（重要口径修正）

简报预期「4 个测试标 pytest.mark.skip 待恢复」。**盘点实证：tests/ 全树不存在任何带重组注释的 pytest.mark.skip/skipif**（全量 grep：无 `pytestmark` 级 skip；无条件 `pytest.mark.skip` 仅 `tests/test_trigger_spec.py:223/:228` 两处，reason=待 T-Spec 七格触发矩阵终确认，属 T-Spec 域非 RWC1；其余 skipif 全为环境门——playwright/Windows/样本目录/powershell 等）。

「RWC1 SKIP 四件」真实所指=**RWC1 席（v21r2 板块重组 W15a character 人格侧）在 `v21r2-reorg-wc1-log.md` §五.1 的 SKIP 登记**：`memory_service.py / memory_store_v21.py / knowledge_service.py / teaching_service.py` 四个**源码模块**留守 `character/` 旧位、待 S8 收官波统一收编（当时 S8 交付+V2 席在飞修复面让位）。旁证链：`v21r2-legacy-manifest-draft.md` 遗留登记 #10、`HANDOFF-V21R4-20260918.md` §6.2.5 尾声清账条目均以「RWC1 SKIP 四件」指代这四个模块。

### 1.2 逐件实况（四件全部已收编，SKIP 条件消除）

| 模块 | canonical 真身 | 旧位形态 | 判定 |
|---|---|---|---|
| memory_service.py | `domains/chat_reply/character/memory_service.py`（656 行） | `character/memory_service.py`=18 行 PEP 562 活转发垫片 | ✅已收编 |
| memory_store_v21.py | `domains/chat_reply/character/memory_store_v21.py`（390 行） | 同上垫片形 | ✅已收编 |
| knowledge_service.py | `domains/chat_reply/character/knowledge_service.py`（588 行） | 同上垫片形 | ✅已收编 |
| teaching_service.py | `domains/chat_reply/character/teaching_service.py`（705 行） | 同上垫片形 | ✅已收编 |

四张垫片 docstring 均自证「moved to domains/chat_reply/character/ (v21r2 S8 收官波)」；`v21r4-b-WIRE-SVC-log.md` 引用四件全部 canonical 路径（生产调用点=0，装配走 `runtime/service_wiring.py` 主门 `bot_v21_service_wiring_enabled` 缺省关——**not_wired 语义仍有效，转正只关迁移台账，不宣称生产生效**）。

### 1.3 实跑证据（离线）

- **垫片同对象冒烟**：四旧位模块 import 后对 canonical 同名公开符号逐一 `is` 断言，**4/4 True**（memory_service/memory_store_v21/knowledge_service/teaching_service）。
- **四模块测试族 7 文件**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_memory_service_v21.py tests/test_memory_router_reuse.py tests/test_v21_knowledge_service.py tests/test_v21_teaching_service.py tests/test_v21_wire_svc_assembly.py tests/test_webui_knowledge.py tests/test_knowledge_mtime_cache.py --basetemp=$TEMP/lfxc-t1 -p no:cacheprovider -q` → **129 passed in 10.43s，0 failed/0 skipped**。
- **台账转正**：`docs/design/v21r2-legacy-manifest-draft.md` 遗留登记 #10 已加「✅已闭环转正（2026-09-19 LEGACY-FIX-c 实证）」注记（最小改动，原行语义保留）。
- pytest 层无需「删标记」：本就不存在对应 skip 标记；若未来出现，恢复条件=对应模块 canonical 化+测试族实绿（本日志 §1.2/§1.3 即先例证据）。

## 二、任务二：echo「(44)」漂移——echo.py 本体已被在飞席修至 46，残留=生成物 stale，本轮 --write 收敛

### 2.1 漂移实况与正确值

- 台账源：`v21r2-command-spec-inventory.md`/`v21r2-command-spec.md` §295/`v21r2-legacy-manifest-draft.md` #7——「echo.py 帮助文本写『二次元问句(44)』，代码实值 priority=46（capability_registry.py:165、base_router.py:584）」。
- **正确值实核（本席复验）**：`domains/chat_reply/runtime/base_router.py:584` `RouteRule(RouteKind.MOEGIRL_QUESTION, "bot.moegirl", 46, "二次元问句", …)`——priority=**46**。
- **现值实况**：git HEAD 旧位 echo.py:763 确为「二次元问句(44)」（漂移在案实锤）；但当前工作树 canonical `domains/chat_reply/capabilities/echo.py:787` 已是「提醒(41)→自然语言命令(45)→二次元问句(46)→链接解析(46)→聊天(50)」——**数字 44→46 与排序（45 先于 46）均已由在飞席修正**（TTS 席 echo.py 占域窗口内完成；本席零触碰 echo.py，语音条目 :2256-2277/:3069-3098 两区间全程未靠近）。
- **排序语义复核**：`base_router.py:723` `for rule in sorted(ROUTE_RULES, key=priority)`——稳定排序，46 同分按注册序（MOEGIRL_QUESTION :584 先于 CONTENT :586），故「自然语言命令(45)→二次元问句(46)→链接解析(46)」与实际评估序一致，canonical echo.py 现文正确。

### 2.2 最小修正（生成物层）

残留漂移在生成物 `docs/command-catalog.md:509`：仍为中间态「二次元问句(46)→自然语言命令(45)」（46 排 45 前，自相矛盾于同句「数字越小越先命中」）。

- 按 TTS 席协议先在 `docs/design/v21r2-COORDINATION.md` 预告（改前备份 `%TEMP%/command-catalog.before-LEGACYFIXc.md`）；
- `python scripts/command_catalog.py --write` → diff 备份**仅 1 行**（:509 排序纠正），未夹带任何其他漂移；
- `--check` → **command catalog is current (77 topics)**，exit 0。

### 2.3 echo 测试族实跑（离线）

`-m pytest tests/test_bot_commands_catalog_b10.py tests/test_documentation_consistency.py tests/test_capability_registry.py tests/test_detail_and_priority.py tests/test_e2e_help_matrix.py tests/test_help_card_twocol.py tests/test_affinity_query.py tests/test_identity_preference_commands.py tests/test_decision_trace_persistence.py tests/test_finance_route_wiring.py --basetemp=$TEMP/lfxc-t2 -p no:cacheprovider -q` → **206 passed in 12.46s**（含 catalog 文档-注册表一致性门与 help 矩阵门）。

## 三、门禁记录（只读，未 --write 非 -f 件）

| 门 | 结果 | 归属 |
|---|---|---|
| `scripts/doc_sync.py --check` | exit 0，PASS（零漂移） | — |
| `tests/verify_hashes.py --check` | 1 项 DRIFT=`domains/chat_reply/capabilities/echo.py`（字节变更未记录） | **TTS 席占域窗口在飞改动**（本席零触碰 echo.py，不代录，留其窗口收敛） |
| `python -m ruff check .` | 29 错，**零归因本席**（本席改动面=3 份未跟踪 design 文档+command-catalog.md 生成物，无 .py）；29 错全在他席在飞域（tests 七件各 1、sources/__init__、music、content_parser 等）+`.tmp-test/` 遗留散件 8 处 | 在飞席/尾声树卫生 |
| `command_catalog.py --check` | **current (77 topics)** | 本席收敛后 |

**树卫生移交**：源码树存在 `.tmp-test/` 遗留 pytest 散件（full/test_excluded_contexts_not_fla0 等 8 文件，ruff 噪声源），先于本席存在、非本席产物，留尾声树卫生席按台账 #1 规程处置；本席两轮 pytest 均用 `$TEMP/lfxc-t1|t2`，零自产缓存。

## 四、交付清单

1. **任务一**：RWC1 SKIP 四件定性修正（非 pytest skip）+ 四件收编转正实证（垫片同对象 4/4 + 测试族 129 passed）+ manifest 草案 #10 转正注记。
2. **任务二**：「(44)」漂移闭环（echo.py 本体已被 TTS 窗口修至 46+排序正确，本席实核 base_router:584/723 确认；生成物 command-catalog.md --write 单行收敛，--check current 77 topics）+ echo 测试族 206 passed。
3. 本日志 + `v21r2-COORDINATION.md` 预告行 + `v21r4-b-coordination.md` 席位行收口。

**诚实边界**：以上全部为离线测试与静态证据；「转正」=迁移台账闭环，不等于生产接线生效（四服务 not_wired 维持，装配主门缺省关）；bot 未重启，任何改动均未在生产生效。
