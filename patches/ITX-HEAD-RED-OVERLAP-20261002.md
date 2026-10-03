# ITX 工单：本窗写面 × HEAD 轴 184 红交叠分析（2026-10-02 下午窗 · 交叠分析席 · 只读）

席 ITX｜使命＝回答「本窗写过的生产件里有没有藏着 HEAD 轴既存红」（BASE 184 红集 ∩ 本窗 41 面写面）。全程只读（本工单除外）。零 git 写、零进程动作、零配置改、零再派。

## ① 红集出处

- `%TEMP%/qoder-BASE/b2/head-axis-reds-B2.txt`＝**184 枚 node ID、103 件测试文件**，与同目录 `head-axis-pytest-B2.txt` 的 184 FAILED 同源核对一致（该输出仅 summary 无 traceback，腿级同因判定靠腿名逐一比对＋红因原文现读）。
- 两维提取：**a) 红测试文件本身 ∈ 本窗写面 → 零枚**（`test_db_owners_coverage.py`、`test_config_key_registration_ledger.py`、六新测试件均不在红集）；**b) 红测试源码 import/路径引用本窗生产件 → 命中三族＋两邻**（下表）。

## ② 交叠表

| HEAD 红（枚） | 被测对象 | 本窗触及 | 现状（③实跑） |
|---|---|---|---|
| `test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync`（1） | `docs/auto-facts.md` 同步态 | **是**（17:24 `doc_sync --write` 重录 980→982） | ✅ **修绿** |
| `test_mail_ingress_locks.py::test_f3_redrive_text_leg…`＋`…surrogate…`（2） | `domains/transport/sender/nonebot.py` | **是**（F3 邮件重投在飞主 hunk，INV §②已注记） | ✅ **修绿**（修复件未入库） |
| `test_detail_and_priority`(1)＋`test_runtime_feature_gate`(1)＋`test_model_admin_and_schedule`(2)＋`test_model_effort_groups_and_pricing`(2)＋`test_capability_declaration_parity`(2)＝**8 枚** | `domains/ops/admin/runtime_admin.py`（直接 import；parity 另在 ：161 frozenset 按路径点名） | **是**（X1b：:244 import 换新家＋backup 命令面） | ❌ **8 枚同腿原样红**，零新增零消失；红因＝能力注册/模型命令集/admin_only 覆盖判据，非 X1b 改动位 |
| `test_voice_central_entry_gate.py::test_gate1_scan_set_is_exhaustive_over_plugins_tree`（1） | `capabilities/tts.py`＋`sender/nonebot.py` 源形态门（:116/:187） | **是** | ❌ 原样红；红因位点＝**`__init__.py`** 未归类音频出站点（非本窗 41 面） |
| `test_voice_hook_error_card_leg.py` 两腿（2） | `runtime/capability_protocols.py`（import） | **是**（L2 RUF100；⚠同文件混 V1 计时伞 +197 前窗遗产） | ❌ 同腿原样红；红因＝测试桩返回 tuple 无 `handle_async`（:393 桩/产签名错配），非注释腿 |
| `test_operational_failures.py::test_inline_mixed_timeout_then_worker_round_never_redispatches`（1） | 仅 import sender.nonebot；被测对象＝中央调度超时重排 | 邻（import 触及） | ❌ 原样红 |

**相邻不算交叠（按使命判例）**：
- `test_trigger_word_single_source` 2 红：扫描面含 tts.py（:129/:785），但 **TW8 工单已逐枚证明**红因构成＝8 枚债全在 affinity/schedule_board/randpic_timing/person_profile/poke_routing/reply_policy/gate——无一本窗面 → 同 echo 判例，不算。
- `test_datafix_runtime_paths` 5 红：对 content_route 仅 kwargs 字符串 `content_route_config` 提及，被测对象＝runtime_paths 接缝 → **已转绿**（绿因在本窗面外，见⑤-1）。
- capability_protocols 其余引用族（orchestration×7、manifest_gate 3、tag_orth 3、creation 1、file_ingress 1、ownership 1、prepared 1、v21r2 1、s10 2）：被测对象＝声明册/调用点普查非本窗件；且 L2 腿＝RUF100 注释摘除（行为惰性）。SNP 工单已扫本窗生产件相邻结构锁全绿。

## ③ 补跑读数（venv＝`ChatBot_Runtime/venv/Scripts/python.exe`，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/itx-btN`，2026-10-02 实跑）

| 批 | 件 | 读数 |
|---|---|---|
| 1 | cross_validation＋mail_ingress_locks＋operational_failures | **1 failed, 63 passed**（唯一红＝operational_failures 同腿；auto-facts 与 F3 两红腿全绿） |
| 2 | runtime_admin 导入族五件 | **8 failed, 52 passed**——腿名与 HEAD 红集逐一相同 |
| 3 | voice_central＋v21_s10＋voice_hook＋datafix | **3 failed, 129 passed** |
| 3a | voice_gate1 单腿 | 红因原文：`出现未归类的音频出站点（自建 audio 或中央呈现漏斗）：['__init__.py']` |
| 3b | v21_s10＋datafix 精确复跑 | **82 passed, 0 failed**（s10 两红腿＋datafix 五红腿全绿） |

已有读数引证：TW8（trigger_word 16p/2f＋红因构成表）、NB4（HEAD 抽取同尺 38p/0f 口径、venv 路径、环境性红警告）、M17（tts:1556 补传 sender_id 外溢面：判定真身在 content_route:931-968，四重关断下零实害）、IVF（101 件波及面全绿：content_route_v3 41p、tts 族 22 件、intimate 16p→本窗 REV 补 2 腿后 18p）、SNP（本窗生产件相邻结构契约锁全绿）。

## ④ 结论

1. **本窗写面上未闭既存红＝11 枚，全部「原样」、零恶化**：runtime_admin 族 8＋voice_hook 2（capability_protocols 混面）＋voice_gate1（tts/nonebot 源形态门，红因位点在 `__init__.py`）。这 11 枚与 HEAD 红态逐一相同，均非本窗改动造成、也非本窗改动所能修——**runtime_admin 8 枚建议由能力注册/模型命令集债主波收账，本窗无须动作**。
2. 本窗/在飞面**顺手修绿 HEAD 红 3 枚**（auto-facts 重录 1＋nonebot.py F3 hunk 2；后者未入库，入库后账才算铁）。另有 7 枚（s10 2＋datafix 5）现也转绿，绿因不在本窗 41 面内（前窗/他席在飞工作树态，未归因，见⑤-1）。
3. 对使命问句的直接回答：**有既存红穿过本窗写面（11 枚），但没有一枚是本窗改动引入或恶化的；本窗改动净效应＝闭红 3 枚、原样 11 枚、恶化 0 枚。**

## ⑤ 未尽

1. s10 两腿与 datafix 五腿转绿的归因未做（超出本席使命：只答写面交叠）；终局净新增红对账若需铁账，建议按 NB4 同法 `git archive HEAD` 抽仓外同尺复跑分桶。
2. `capability_protocols.py` 为**混面**（本窗桶只认领 L2 RUF100 腿；V1 计时伞 +197 系前窗/他席在飞遗产同文件）——V1 伞的责任面红学未查，HEAD 红集中无其点名件。
3. db_backup 挪家：HEAD 红集零引用＝零交叠；但 NB4 已账晨窗新件带**净新增红 3 枚**（HEAD 轴外），终局账需并读。
4. 环境注记：global python 有 pydantic/pydantic-core 版本失配（NB4 环境性红），本席全部读数取 venv；`BOT_AUTOSYNC=0` 与生产验收口径一致（台账 #72★）。
