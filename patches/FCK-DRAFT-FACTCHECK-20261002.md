# 工单 FCK — MER 并账稿逐条事实核对（2026-10-02 下午窗 · 只读核对席）

- 对象＝`patches/DRAFT-HANDBOOK-MERGE-20261002.md`（mtime 17:30:18）。方法＝逐句对出处工单原句；关键读数抽 1/3 实跑复核（venv＋卫生前缀＋仓外 basetemp，预建目录避 AUD 披露的字节码坑）。零 git 写／零配置改／零进程动作（判据实跑除外）。
- 结论先行：**稿修后可用**。四格（census 74/74、地板 (784,1612,3,688)、轴口径、可签/不可签）全部核实成立；硬伤 1 处（IVF 红数）＋过时 2 处（BASE-2 复证、三席交卷）须改，另 6 处措辞级。

## ① 逐条核对表（稿句→出处→判定）

| 稿句（缩） | 出处 | 判定 |
|---|---|---|
| census 现值 74/74 OK，输出行逐字 | DER①＋本席实跑 | **一致（实跑复核：`硬锁·三态之和(域外全量) 74/基线 74 (OK)`，对账五项全 0）** |
| 挪家 domains/ops/db_backup.py＋runtime_admin.py:244 唯一 import＋5 lint | DOC／CM批A／§71（`runtime/db_backup.py 5`）／AUD | 一致 |
| DOC 零 live 指针；ledger:289 历史账可留 | DOC②＋AUD 复核（新增发现 test_db_backup 注毒串＝夹具非 live） | 一致 |
| 亲密门四步顺序／tts 第四参／空 sender 等价 | INT①②＋AUD 读码（:893-968、:1556-1561） | 一致（稿用改前行号 :1554，建议统一改后 :1556-1561） |
| 18 passed＝16 INT＋2 REV；注毒 3 failed 还原；邻域 97=97 | INT④＋REV③（18 passed in 5.79s）＋本席实跑 | **一致（实跑复核 18 passed in 2.95s）** |
| IVF「101 件全跑」＋红 breakdown 十件 | IVF①②③ | 一致（逐件数字与 IVF②逐字对上）；**但总数「16 件翻红」错，见 E1** |
| ledger >300s「被驱动器杀未判」 | IVF③终跑定论 | 偏差（E4）：IVF 600s 窗终跑有判＝39 passed 绿 |
| 「同节点全数复红」 | IVF④ | 小偏差（E5）：error_report 为 HEAD 红集**子集**非全同（IVF 自记 9 件逐一相同＋1 件子集） |
| ANN 三病因：744,371 条／巡检／SQ8≈2.04 GiB／「下一轮检索即感知」 | 主会话窗账（无工单） | 存疑（E8）：重建事实有旁证（PEND Y3：kb_wiki_faiss.index 964MB，mtime 16:24）；数值与「即感知」无在盘出处，建议标证据等级 |
| lint 27→0＝14＋7＋5＋1；GATE 差 6＝漏计末两项；w1 门 bug | §71 分账（27 枚逐枚可点）＋L1/L2/GATE/MIG | **一致（算术闭合：6+4+3+1＋3+1+1+1+1＋5+1＝27）**；typecheck 609／HEAD 606 ✓ GATE／BASE |
| d2 17 passed（改前 1F16P）；两腿同抹 | D2F＋L1/L2 基线互证＋本席实跑 | **一致（实跑复核 17 passed in 2.87s）** |
| X1c 六腿 28 枚；HALF-WRITTEN 死因；常驻注毒 5＋临时 2；docstring rmtree | DBT 全文＋本席实跑 | **一致（实跑复核 28 passed in 2.99s）** |
| MIG 15 passed；封闭集；代写披露 | MIG＋AUD 复跑（15 passed） | 一致 |
| CHK 11 把＝10 绿＋锁7 4 红（637.92s）；地板复录 (784,1612,3,688)；差数＝INT 两 getattr＋DBT 件；SLACK 未动；D-28 OPEN | CHK③＋本席静态核 | **一致（实核：ledger:289 元组逐字；SLACK=(0,200,0,50)；content_route 人腿两枚 getattr 读点 :958/:963 在场；test_db_backup.py 在盘）**；AUD 抽验四 poison 腿复绿闭环 |
| DER：980→982 已重录；83 topics；哈希 rc0；五把 26/10/20/31/23；layout rc0 | DER①②＋CMV（auto-facts 1 hunk 2+/2−）＋本席实跑 | **一致（实跑 doc_sync --check RC=0；顶层 test_*.py 计数恰 982）**；「+2＝DBT/BKT」DER 原文不判归属，但 DBT/BKT 两工单均有「写前自检目标件不存在」存在性证明，判一致（建议稿留出处） |
| BKT 9 腿；三代归属；两轴在飞 | BKT＋AUD 复跑（9 passed） | 一致；**「前席 184 旁证不可采信」已过时，见 E2** |
| 「163 基线差属 HD-only 同因」 | BASE⑤.2 明言无法分解；§71 HD-only＝不可归因 | 偏差（E7）：建议降格（163 全值＝163 failed, 21209 passed，§71 在册） |
| IMG：12 族／T1①可闭／tts_refs 已裁未接线／23 passed／#66★ 两边界 | IMG 全文＋AUD 复跑（23 passed 合跑） | 一致 |
| CM 五批 A3/B6/D12/C23行/E9＋顺序理由＋禁入/暂缓＋口诀六条＋nonebot 剔出 | CM 全文 | 一致（批C「21 枚」标题 vs 23 行＝CM 自注口径，稿用「23 行」正确）；增量＝CMV 勘误工单在盘未并入（见⑤） |
| 席面账：弹回重派／MIG 代写／BASE 覆写披露／零注入 | INT/IVF/BKT/CHK 自述＋MIG＋BASE§⑥.5＋INJ⑤ | 一致（INJ：本窗 20 张全净、执法门 17 passed、零新增投放）；**「在盘工单 17 份」「AUD/PEND/TRG 未在盘」过时，见 E3** |
| 可签/不可签口径 | #72★/#10★ 原句比对＋各席证据 | **一致（无轴混写：INT 段＝邻域 A/B 轴、IVF 段＝HEAD 对照轴、可签行＝本波域＋盘面限定，三分清楚）**；可签九项全部有实跑证据（本席复核 5 项）；「ANN 例外」见 E8 |
| 落点 §73 | 实核 HANDBOOK 末节＝§72（:5851） | 一致（§73 空号） |
| 遗留⑤「AUD/PEND/TRG 未在盘＝在飞」 | 盘面 mtime | **偏差（E3）：三席现均已在盘交卷**（AUD 17:27／PEND 17:27／TRG 17:37，稿 17:30 落笔） |

## ② 偏差勘误（改正文案）

- **E1（硬数字）**：IVF 段「16 件翻红」→「**10 件翻红（红腿 18 枚）**」。稿内枚举自身合计 3+2+2+3+1+1+1+2+1+2＝18，与 IVF②逐件表一致；IVF④ 口径＝90 绿＋10 红＋1 慢跑。「16」疑为 16:54 在飞中途截断面读数（AUD/INJ 记 IVF 当时未完卷），非终稿值。
- **E2（过时·必改）**：BKT 段「前席 HEAD 轴旁证 184 failed, 21188 passed（17:11 完）不可采信」→ 补：**BASE §⑥（BASE-2，17:51/17:56 收工）已用独立 b2 纯 HEAD 副本复跑同读数（184 failed, 21188 passed, 26 skipped, 16 xfailed, 3 errors in 3319.28s）且两 run FAILED 集 diff 全同（183+1 修正）⇒ 184 红清单双 run 独立确认，「可安心作 A 轴分桶输入」**；16:27 run 的 cwd 更正（实为工作树）只撤「副本方法」证据资格，数据经 b2 复证不受影响。BASE-2 另警示：带空格 node ID（`[J9 gallery_empty …]`）分桶须按 ` - ` 切、禁按空白切。
- **E3（过时·必改）**：「在盘工单 17 份」与遗留⑤「AUD/PEND/TRG 三席未在盘＝在飞」→ 现盘 **AUD（17:27，十单账面↔盘面全一致＋锁7 四 poison 腿复绿闭环＋venv 字节码坑披露）、PEND（17:27，R1-R3 须裁＋Y1-Y4 建议）、TRG（17:37，六红全 HEAD 级既存）均已在盘交卷**；其后另有 INV/CMV/M17/INJ/HLP/RESTART/SNP（17:39-17:55）及 18:00+ 波 WLF/FLR/WCH/IDX 落盘。稿应改「收卷时点快照」口径或把三席结论并入正文（TRG 红可充实「不可签全绿」括注）。
- **E4（措辞）**：「test_config_key_registration_ledger.py >300s 被驱动器杀未判」→ IVF③终跑定论有判（工作区 600s 窗 `39 passed in 593.81s` 绿；HEAD 副本 36 passed，36→39＝在飞新增键测试）；CHK 4 红属地板落后在飞红，复录后 AUD 抽验四 poison 腿 `4 passed` 闭环。
- **E5（措辞）**：「逐件 git archive HEAD 同尺对照＝同节点全数复红」→「9 件同节点逐一复红；error_report 为 HEAD 红集子集（HEAD 另 1 枚工作树已绿＝在飞修复）」（IVF④原话）。
- **E6（措辞）**：不可签括注「IVF/CHK 各点名一批 HEAD 级既存红」→「IVF/TRG 各点名＋BASE 184 全清单」（CHK 四红＝地板落后在飞红，复录已闭，非 HEAD 级）。
- **E7（措辞）**：「读数与 §71 的 163 基线差属 §71 HD-only 同因（缺 .env/文档面即漂）」→ BASE⑤.2 明言「差数成分无法分解（诚实缺席）」，且 HEAD 已前移（#71/#72 入库）。建议改「成分未分解；§71 先例示 HD-only 类对 .env/文档面敏感，分桶按 node ID 不按总数」。
- **E8（轻）**：ANN 段数值（744,371／SQ8≈2.04 GiB／「下一轮检索即感知」）无在盘工单，建议标注「主会话窗账」证据等级（unknown；重建事实旁证＝PEND Y3）。
- **E9（轻）**：tts.py 消费者行号统一改后坐标 :1556-1561（稿/INT① 的 :1554 为改前值）。

## ③ 实跑抽验读数（本席实跑末行原样；venv＋卫生前缀＋仓外 basetemp 预建）

1. `scripts/shim_retirement_census.py --check` → `硬锁·三态之和(域外全量) 74/基线 74 (OK)`（另：对账五项全 0／垫片 23／盲区 3／G-P2 28）
2. `pytest tests/test_db_backup.py -q` → `28 passed in 2.99s`
3. `pytest tests/test_store_write_trace_d2.py -q` → `17 passed in 2.87s`
4. `pytest tests/test_intimate_group_switch_delivery.py -q` → `18 passed in 2.95s`
5. `python scripts/doc_sync.py --check` → RC=0；`ls tests/test_*.py | wc -l`＝**982**（与册一致，旁证 +2＝DBT/BKT 两件后态）
6. 静态核：`CORPUS_FLOOR_BASELINE = (784, 1612, 3, 688)`（ledger:289）、`CORPUS_FLOOR_SLACK = (0, 200, 0, 50)` 未动；content_route.py 人腿两枚字面 getattr 读点 :958/:963 在场；HANDBOOK 末节＝§72
（抽验≈1/3 关键读数，全部命中稿值；四格①②④实锤、③轴口径书面核对无混写）

## ④ 总评

**修后可用**。骨架与四格全部核实：census 74/74（实跑）、地板 (784,1612,3,688) 与差数归因（实核）、净新增红 0 三轴口径无混写、可签/不可签与 #72★/#10★ 一致且九项可签均有实跑证据（本席复核 5 项全中）。必改三处＝E1（红数 16→10 件/18 腿）＋E2（BASE-2 双 run 复证推翻「不可采信」）＋E3（三席已交卷）；其余六处措辞级可随手带上。

## ⑤ 未尽事项

1. FULL B 轴首跑 09:51Z 被 SIGKILL（82% 处，exit 137，非本窗任何席操作），同命令重跑在飞、§③仍待填 ⇒ 终门 `ab_red_bucket` 分桶未定，稿「两轴输入在飞」现状对 FULL 仍成立、对 BASE 已不成立（E2）。
2. CMV 增量勘误（17:41 在盘）未并入稿 CM 段：现树 102 行；`test_config_key_registration_ledger.py` 当前 diff＝**混两席**（主会话地板行＋席 Z1 `assert_floor_two_sided` 约 132 行追加，自称 10-01）；后落盘工单（AUD/PEND/DER/DRAFT 等）未入 CM 五批——收卷人须按「CM 原单＋CMV 勘误」合卷。
3. Z1 追加腿为并发在飞件、无本窗工单认领，稿未提；其入库批次与判据归属待主会话裁。
4. `.wip` 两枚：PEND Y3 实扫 `ChatBot_Runtime/`（除 cache/venv）零命中＝账面滞后（稿遗留②「待裁」宜引 Y3 两案）。
5. ANN 数值与「下一轮检索即感知」无工单可对（E8）；ann_pair 巡检复跑本席未执行（命令在 §50 在册，非本席抽验档）。
6. 本席零 git 写、零配置改、零源码/测试写入；唯一写面＝本工单。
