# CMD 总表 — 终局报告判据 × 可复跑命令 × 本窗实跑末行（2026-10-02 下午窗）

> 席 CMD·总表席，只读，唯一写面＝本表。cwd＝仓库根；解释器＝ChatBot_Runtime/venv/Scripts/python.exe；直跑一律带卫生前缀 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0，pytest 另加 -p no:cacheprovider --basetemp=<仓外>（合称卫生前缀）。
> 「CMD 实跑」＝本席 2026-10-02 傍晚六条抽验（产物只落 %TEMP%\qoder-CMD*）；其余行引出处工单已录末行原样。全程零 git 写／零进程动作／零配置改。
> 🔴 偏差一处＝行 4 runtime-layout FAIL（.ruff_cache，成因已定性见行注，非他席在飞写入）。

| # | 判据 | 命令（cwd＝仓库根） | 末行原样（RC） | 出处 |
|---|---|---|---|---|
| 1 | census 垫片退役账 | python scripts/shim_retirement_census.py --check | 对账问题: ①漏记 0 \| ②非垫片登记 0 \| ②b已退役被回引 0 \| ③真身不存在 0 \| ④引用超上限 0 \| ⑤手抄真身不符 0（RC=0；次行＝硬锁·三态之和(域外全量) 74/基线 74 (OK)；垫片 23、读点盲区 3、G-P2 豁免 28/上限 29） | CMD 实跑②；同 DER①#1（17:22 同读数） |
| 2 | lint 门 | powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task lint | All checks passed!（exit 0） | GATE①（17:07 中期探针）；BASE§④ 双证（ruff 直跑同读数） |
| 3 | typecheck 门 | powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task typecheck | Success: no issues found in 609 source files（exit 0） | GATE①；BASE§④ 双证（mypy 直跑 plugins 口径 606 文件同绿） |
| 4 | runtime-layout 门 | powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Task runtime-layout | runtime-layout: FAIL ＋ generated residue [tool-cache] x1: .ruff_cache/ -- attribution: scripts/dev.ps1 hands ruff/mypy a --cache-dir inside ChatBot_Runtime/cache and pytest runs with -p no:cacheprovider, so a cache dir in the source tree comes from a raw ruff/mypy/pytest call outside dev.ps1（RC=1） | CMD 实跑⑤。行注：pre_restart_check.py:467 ruff 腿为裸 ruff check .（无 --no-cache）⇒ 每跑一次 pre_restart 必落 .ruff_cache（本枚 mtime 18:51:49＝CMD 实跑⑥的 ruff 腿；18:09 主会话终验同型必落）；非他席在飞写入，属脚本与规则 6 卫生口径潜在缺陷，处置归主会话（本席未删）。对照＝DER①#6 直跑 smoke 当时 RC=0（17:2x，在该 ruff 腿落缓存之前） |
| 5 | pre_restart 一道门 | python scripts/pre_restart_check.py | 汇总: PASS 9 / SKIP 4 / FAIL 0 → 全绿，可以重启（先 SnowLuma 后 bot.py）（RC=0） | CMD 实跑⑥；同 RST 收卷更正（傍窗同读数） |
| 6 | 六波锁合并 | 卫生前缀＋pytest tests/test_intimate_group_switch_delivery.py tests/test_migration_status_assignment_gate.py tests/test_db_backup.py tests/test_ab_red_bucket.py tests/test_prompt_template_layer_w1.py tests/test_store_write_trace_d2.py -q | 115 passed in 13.42s（六件＝18+15+28+9+28+17） | WLF②（17:58；WLF③ 单跑 admin 门 9P／umbrella 20P 亦绿） |
| 7 | ledger 全件（地板复录后） | 卫生前缀＋pytest tests/test_config_key_registration_ledger.py -q | 39 passed in 616.13s (0:10:16) | FLR②（17:5x；改前 4 failed, 35 passed，净减 4 红 0 新红） |
| 8 | 终门 A/B 红集分桶 | python scripts/ab_red_bucket.py %TEMP%\qoder-BASE\b2\head-axis-reds-B2.txt %TEMP%\qoder-FULL\wt-axis-reds.txt | == NEW_ONLY（只在 B＝净新增红）n=5 == ／ == GONE_ONLY（只在 A＝转绿）n=58 == ／ == COMMON（两边共有＝既存红）n=122 == ／ == 判定：NEW_ONLY=5 ⇒ 退出码 1 ==（RC=1）。五枚点名：tests/test_config_read_points_declared.py::test_ghost_read_points_exactly_match_registry；tests/test_host_metrics_single_source.py::test_only_the_registered_true_source_reads_the_machine；tests/test_secret_scan_tracked.py::test_f1_findings_are_exactly_known_debt_roster；tests/test_single_entry_gates.py::test_gate2_multi_reader_facts_do_not_grow；tests/test_single_entry_gates.py::test_gate2_no_module_reads_host_metrics_beyond_the_ledger | CMD 实跑①（A 轴＝BASE-2 纯 HEAD 副本 184 红，B 轴＝FULL WT 轴 131 红：FULL③ 末行 131 failed, 21533 passed, 15 skipped, 18 xfailed in 3038.33s (0:50:38)） |
| 9 | 分桶器自证 | 卫生前缀＋pytest tests/test_ab_red_bucket.py -q | 10 passed in 3.14s | CMD 实跑④；同 BKT§七（SPC 修后主会话 10 passed；修前 BKT-F 9 passed） |
| 10a | 派生册·auto-facts | python scripts/doc_sync.py --check | （无输出，RC=0） | CMD 实跑③；DER①#2 曾 RC=1 漂一行 980→982 → 主会话 17:24 --write 重录（TLN 行），cross_validation 门随转绿 |
| 10b | 派生册·命令册 | python scripts/command_catalog.py --check | command catalog is current (83 topics)（RC=0） | DER①#3 |
| 10c | 派生册·哈希 | python tests/verify_hashes.py | （stdout+stderr 合计 0 字节，RC=0） | DER①#4 |
| 11a | 邻域·INT 爆炸半径 | 卫生前缀＋pytest <101 件逐件 -q>（清单＝IVF 工单§①） | 全轴 101 件：90 绿＋10 红＋1 慢跑（终跑绿）；10 红全在 git archive HEAD 仓外副本同尺复红 ⇒ 全部 HEAD 级既存，净新增红＝0 枚 | IVF④（17:51；例件 test_capability_manifest_gate＝3 failed, 73 passed in 18.78s） |
| 11b | 邻域·结构契约锁 | 卫生前缀＋pytest <9 件 -q>（清单＝SNP 工单§①） | 零外溢。8/9 件全绿；唯一红件三枚均为 HEAD 既存，不在本窗引入面（例件 test_rendering_contract＝157 passed in 10.60s） | SNP③（17:55） |
| 11c | 邻域·四红定性 | 两环境对照（global python 与 Runtime venv）＋HEAD 抽取件同尺复跑 | global＝4 failed, 34 passed；venv＝3 failed, 35 passed（枚 1 消失）；HEAD 抽取件＝38 passed, 0 failed ⇒ 定性：枚 1 环境性红（global pydantic-core 2.49.0 与 pydantic 失配，import config 即炸），枚 2/3/4 同源 domains/ops/db_backup.py（WT-only 在飞面，与行 8 五枚中三枚同源） | NB4（18:20；与 FLR③ 邻域账互证） |
| 12a | db_backup 六腿 | 卫生前缀＋pytest tests/test_db_backup.py -q | 28 passed in 4.09s（collect-only＝28 tests collected；ruff 单件 All checks passed!） | DBT§五（17:03；并入行 6 合并读数） |
| 12b | 亲密群切换门 | 卫生前缀＋pytest tests/test_intimate_group_switch_delivery.py -q | 18 passed（REV 补 2 对抗腿后 17:10 定格；PRV 脱敏修正后主会话复跑同 18，零判据变化） | INT＋WLF② 分账（18） |
| 12c | migration 状态门 | 卫生前缀＋pytest tests/test_migration_status_assignment_gate.py -q | 15 passed in 3.52s（改前 1 failed, 14 passed） | MIG③（主会话 16:3x 复跑代录；判据归属＝席 MIG） |

## 抽验账与口径
- CMD 六条实跑＝行 8／1／10a／9／4／5，全部与本窗工单在册读数对表：五行一致；行 4 为唯一 FAIL，且成因系 pre_restart ruff 腿裸调用的结构性落缓存（18:09 终验后即在场），非代码红、非他席新残留。
- 两轴输入文件：A＝%TEMP%\qoder-BASE\b2\head-axis-reds-B2.txt（184 行，BASE-2 双 run 互证）、B＝%TEMP%\qoder-FULL\wt-axis-reds.txt（131 行）；TEMP 清理会吃掉，需留存请归档（FULL⑤.2 同警示）。
- 本表只汇编不裁决；「全绿」与「已生效」仍按 DRAFT-HANDBOOK-MERGE 口径不可签（bot 未重启，台账 #10★）。
