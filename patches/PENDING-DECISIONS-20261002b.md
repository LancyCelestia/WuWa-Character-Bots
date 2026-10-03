# PENDING-DECISIONS-20261002b — 修复波下午窗·待用户裁定一页汇编（席 PEND · 只读汇编席）

> 生成：2026-10-02 下午窗收卷前。输入＝本窗 13 工单（IMG/DBT/INT/REV/MIG/L1/L2/D2F/BKT/CHK/DOC/IVF/GATE，均在 `patches/`）＋ `docs/pending-decisions.md` ＋ `docs/HANDOFF-FIXWAVE-20261002.md` ＋ HB-C §2（`.superpowers/sdd/2026-10-02-fixwave/HB-C-taxonomy-decoupling.md`）＋ `half-done/` 残件。主会话已裁的不列。本席全程只读，唯一写面＝本工单。
> 文中 pytest/lint 读数均为各工单**实测当时值**（出处逐行可溯），现值以实跑为准。

## 🔴 须用户拍板（3 项）

| # | 事项 | 现状一句话 | 两案 | 动哪几行 | 谁裁 |
|---|---|---|---|---|---|
| R1 | 人格 `voice.tts_refs` 接线 vs 撤声明（IMG 工单格2） | 在册态＝H-3「只声明未接线」：零生产消费点、三把锁钉死全绿；交接档 §四T1② 的"未闭"实为账面滞后 | **接**＝tts.py:1029 加「现役人格 record.tts_refs 非空则优先」分支＋三把 H-3 锁改语义＋T1 契约腿联动；但 registry 现值全空，逐人格参考音频素材须用户另定（规则 8，代价高）。**撤**＝删字段/解析/docstring＋registry 两 json＋三把锁＋T1 voice 格；代价中，但推翻在册 H-3 前瞻声明，动 `personas/registry/*.json` 须规则 8 授权 | 接：`domains/media/capabilities/tts.py:1029`、`tests/test_seat_feat_persona_prof.py:139/149/171`、`tests/test_seat_t1_persona_contract_20261002.py:389-391`；撤：`character/persona_profile.py:29/188/318`、`personas/registry/shorekeeper.json:18-19`＋`danya.json:18-19`、同上两测试件 | **用户**（不裁＝维持现状零成本；IMG 建议账面改记「已裁未接线」即闭） |
| R2 | D-28：地板/容差结构互斥三案（CHK 锁7 四红现形） | `test_config_key_registration_ledger` poison_11/14/15/16 四发全红：地板落后现算 2/1 格，双向腿判「没变瞎」；该文件 mtime 12:12 未入库在飞，当日归属未判 | **甲**＝容差改 0 并同批废「允许落后」账；**乙**＝双向腿改对地板起算（放弃测盲区段）；**丙**＝保留现形状＋门内加「落后≤容差且逐枚有归属」申报位 | 该测试件 poison_14/15/16 判据形状＋`CORPUS_FLOOR_BASELINE`/容差（在册裁定：复录、容差一字不动是前提） | **用户**（三案在册待裁，HANDBOOK §71/D-28）；四红当日归属＝主会话（等在飞面入库后 A/B 分桶定论） |
| R3 | `.qoder/settings.local.json` 取消跟踪（HB-C §2 在册） | 仍被 git 跟踪且不被 ignore：`.gitignore:79` 注释承诺 "never commit" 但管辖块只列 `.claude/.codex/.grok/`，`.qoder/` 不在名单；`scheduled_tasks.json` 已单独 ignore＝混合跟踪态 | **A**＝`git rm --cached` 一枚＋`.gitignore` 补一行 `.qoder/settings.local.json`（勿整目录 ignore，会吞该留的；HB-C 已核 tests 零引用）；**B**＝维持现状（IDE 本地配置继续入库） | `.gitignore` 一行＋git rm --cached 一枚（git 写＋配置面＝用户专属执行面） | **用户**（HB-C 判定「只出册、绝不动手」） |

## 🟡 建议用户过目（4 项）

| # | 事项 | 现状一句话 | 两案 / 建议 | 动哪几行 | 谁裁 |
|---|---|---|---|---|---|
| Y1 | 亲密人腿改动待审上车（INT＋REV） | 群侧人腿（content_route 群分支四步序）＋tts.py 第四参交付：REV 对抗复核 18 passed、IVF 宽域 7 件全绿，零行为错误；全部未提交未重启＝**未生效**；M-17 语义外溢＝私聊白名单者在任何群自动配音面随之放开 | **上车**＝随本波提交＋重启；**回退**＝只撤 tts.py 第四参（人腿判定保持） | `content_route.py` 群分支:931-968、`tts.py:1556-1561`、`tests/test_intimate_group_switch_delivery.py` | 用户（提交/推送/重启归常令） |
| Y2 | X1c 半成品残件处置 | `half-done/test_db_backup.py.HALF-WRITTEN`（31,813 B，10-02 01:56）在盘；DBT 已重写交付 28 passed，原件按规「只准移不准删」 | **A**＝按规则 9 归档移 `ChatBot_Archive/` 附 manifest；**B**＝留原位待后续波处置 | 该残件一枚 | 用户点名（不裁＝默认留原位，零功能影响） |
| Y3 | `.wip-*` 两枚 09-30 尸块账面滞后（本席新取证） | HANDOFF:301-302 记两枚残件待判归属；本席实扫 `ChatBot_Runtime/`（除 cache/venv）**零命中**——现盘仅 pytest 夹具残件（`cache/*/basetemp/test_midway_abort_*/`），且 `data/kb_wiki_faiss.index` 已被今日重建覆写（964 MB，mtime 16:24） | **A**＝主会话销该账行（记「已被重建覆写」）；**B**＝用户若知另有藏点请点名路径再查 | HANDBOOK/HANDOFF 账行 | 主会话销账；cache 内夹具残件清不清归用户 |
| Y4 | 本窗收卷对账包 | IVF 工单止于"进行中"（已证 10 枚红＝4 件 capability 锁 HEAD 级既存、非 INT 引入）；GATE 记 lint 分账差 1（27−21=6 按账应残 vs 实测 0）；CHK 锁9/10/11 读数即首锚无对照；DOC 边界一枚注释（ledger:289 旧路径补六字）改不改均可 | 收卷终跑四道门＋A/B 分桶定论；分账差 1 不判归属只记 | 主会话收卷；DOC 注释主会话裁量 | 主会话（用户只需看终跑读数） |

## 🟢 本窗已闭存档（无需裁定）

- IMG T1①族数：12 族非空、去重有牙、轮换避开窗生效，T1 锁 23 passed——主会话即可闭账（证据＝IMG 工单＋T1 锁实跑）。
- MIG 量具收窄 15 passed 净新增红 0；L1 四件 lint 14→0；L2 生产面 7 枚清零；GATE 复核 lint/typecheck 双绿 0 枚。
- D2F 注毒腿改两腿同批抹净 17 passed；L1 遗留「d2 预告 2 红 vs 实测 1」由 D2F 定因（注毒构造单腿假设致假绿）闭账。
- BKT A/B 分桶器 9 passed＋BKT-F 采认收尾（三代归属账在工单 §六）；DBT 重写 28 passed＋注毒自证齐；DOC 普查代码面＋在册文档面零 live 指针。

## 在册既存待裁（只登记不展开）

- `docs/pending-decisions.md`（2026-09-14 册）16 条 OPEN：A1–A6／B1–B3／C1–C4／D1–D3；原册标「立即」时机＝A5、B1、B2。
- HANDOFF-FIXWAVE「待用户裁」现状态：①ANN＝已修✓（**大库重建仍在跑，完成前 `kb_drift` 维持 FAIL 属预期**，非新红）②HANDBOOK 合并＝待做 ③D-19–D-26 八条悬账＝原样（HANDBOOK §58.15）；另「取句语义统一（规格 §四.3）」仍在册待裁（该件 :195/:252）。
- 新增待裁格：D-28（见 R2）；D-29＝裸 `Config(...)` 检测器装不装/按哪根轴录基线/棘轮 vs 逐件 119 处钉值（AG-01 基线已备，等用户裁设计）；D-27＝GO＋六条硬条件（§72 在案）。
- 残件：见 Y2。
