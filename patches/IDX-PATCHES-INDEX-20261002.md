# IDX 工单 — 2026-10-02 patches 全量索引（席 IDX · 只读索引席，唯一写面＝本件）

- 范围：`patches/` 下 mtime＝2026-10-02 的全部 41 张（00:00–17:54 +0800）。前日件（E05-CONFIG-REQUEST / W4 / W5 等 10-01 及更早）不入表。
- 状态判据＝工单五段（①现状②改法③读数④净新增红⑤未尽）是否齐；缺⑤或末节截断＝在飞/截断，如实标。
- 顺手账：今日件**无空文件、无半行截断件**（最小 2,328 B＝FULL-WTAXIS，属「待填」未完卷而非中断截断；全部文件结尾干净）。

## 索引表（按 mtime 序）

| # | 文件 | 席 | 主题一句话 | 状态 |
|---|---|---|---|---|
| 1 | X4b-PIPELINE-OFFLOAD-20261002.md | X4b | 管线「能力正文无条件下放线程池」收尾：根汇口 handle/handle_async 统一 `ensure_offloaded`，补 X4 无工单遗产 | 已交卷 |
| 2 | B1-CONFIG-REQUEST.md | B1 | TTS 缓存配额两键缺省 0→256 MiB/30 日 的四面 CONFIG-REQUEST（阈值按真实分布分档） | 已交卷（需求件） |
| 3 | Q1-QUEUE-SUBMIT-SCAN-20261002.md | Q1 | 出站队列每次 submit 全表扫（P5.9）根修：created_at 覆盖索引，EXPLAIN 只读副本实证 | 已交卷 |
| 4 | F1-FX-CURRENCIES-20261002.md | F1 | 汇率卢布/瑞郎/加元/澳元＝三态名册+凭据册+五把门（不编源），顺手接通 USD 三角换算 | 已交卷 |
| 5 | F2-NEWS-WHITELIST-20261002.md | F2 | 快报「源白名单门」+逐源可达性+宣称⊆实装（V2EX/少数派除名，BBC 按采编主体登记） | 已交卷 |
| 6 | P3A-ROUTE-GATE-PROPOSAL-20261002.md | P3a | `/bot route(s)` 零角色门补门提案+全命令面 36 腿门对照表（只出提案+只读静态门） | 已交卷（提案） |
| 7 | S1-UNBOUNDED-RESOURCES-20261002.md | S1 | 无界资源收口：共享 httpx 池关停、嵌入 client 复用（#71 病理腿）、缓存封顶；禁碰面只出清单 | 已交卷 |
| 8 | N1-NOTICE-ROLES-MAIL-20261002.md | N1 | notice 幂等兜底键 + `"super"` 死判据修复 + 邮件四枚悬空 skip 撤除（席 150 轮到顶未交工单） | **主会话代写** |
| 9 | E1-ERROR-COPY-POOLS-20261002.md | E1 | 错误话术 6 池+41 码升每池 15–16 变体并纳机械门（复用五套既有取句机制） | 已交卷 |
| 10 | B1-TTS-CACHE-OUTTMPL-20261002.md | B1 | TTS 缓存缺省面纠偏（开关本就 True，住 0 的是配额）+ yt-dlp 落盘名消毒 | 已交卷 |
| 11 | R1-RUNTIME-LAYOUT-SCAN-20261002.md | R1 | runtime_layout 门扫面扩面（字节码/工具缓存/basetemp 残根分类点名）+同批自测锁 | 已交卷 |
| 12 | W-E05-GATE-GAPS-20260930.md | E05 | 门禁三缺口补丁提案（未落地；09-30 主树空壳事故账+接法清单；名带 0930、mtime 今日入库） | 已交卷（提案件） |
| 13 | HB-A-architecture-EVIDENCE-20261002.md | HB-A | 架构与功能交接取证篇（两棵树/runtime_paths/测试 Runtime 根隔离缝） | **截断**（当日额度墙打断，自declared 末节不完整） |
| 14 | HB-C-taxonomy-EVIDENCE-20261002.md | HB-C | 三篇交接册（物理归类/功能说明耦合/解耦进度）+.qoder 跟踪矛盾取证 | **截断**（当日额度墙打断，自declared 末节不完整） |
| 15 | DOC-DBBACKUP-REFS-20261002.md | DOC | db_backup 挪家残余指针普查（两轴全扫，代码面零 live 指针） | 已交卷 |
| 16 | INT-INTIMATE-PERSON-GATE-20261002.md | INT | 亲密模式群侧人腿（人在私白⇒任何群能开，四步序）+ tts.py:1554 补第四参 | 已交卷 |
| 17 | L1-TESTLINT-20261002.md | L1 | 四测试件 lint 14 枚清零 + w1 门真 bug（Expr 包装节点 id）修 | 已交卷 |
| 18 | MIG-STATUS-GATE-PREDICATE-20261002.md | MIG | MigrationStatus 赋值门量具收窄（TransportEntry 第二状态封闭集；席交卷后被并发墙收走） | **主会话代写** |
| 19 | L2-PRODLINT-20261002.md | L2 | 生产面 7 枚 lint 清零（write_trace 3/prompt_template/protocols/nonebot/db_owners 各 1） | 已交卷 |
| 20 | D2F-WRITETRACE-POISON-20261002.md | D2F | d2 注毒腿假绿根修：retire 两腿同批抹净（except 腿顶账盲区），17 passed | 已交卷 |
| 21 | CHK-LOCKFAMILY-20261002.md | CHK | 锁族 11 把普查实跑（锁 7 四红读数真实→主会话复录地板后闭环） | 已交卷 |
| 22 | BKT-AB-BUCKET-20261002.md | BKT | A/B 红集分桶器 `scripts/ab_red_bucket.py`（三桶+rc 机读口）9 腿自证 | 已交卷 |
| 23 | IMG-IMAGERY-AUDIT-20261002.md | IMG | 意象族 12 族取证 + voice.tts_refs 判「已裁未接线」非幽灵（H-3 账面滞后） | 已交卷 |
| 24 | DBT-DBBACKUP-TESTS-20261002.md | DBT | db_backup 测试件重写 28 枚六腿（逐腿抢救/重写阵亡席 X1c 半成品） | 已交卷 |
| 25 | GATE-TYPECHECK-LINT-20261002.md | GATE | typecheck/lint 双门盘点（双绿 0 枚；lint 分账差 1 留主会话对账） | 已交卷 |
| 26 | REV-INTIMATE-ADVERSARIAL-20261002.md | REV | 亲密人腿对抗复核：私聊黑压人腿+两侧 strip 归一补 2 腿，18 passed 行为错误 0 | 已交卷 |
| 27 | CM-COMMIT-PLAN-20261002.md | CM | 逐批提交清单 A→B→D→C→E（52 枚+防吞口诀；提交动作归用户） | 已交卷（清单席） |
| 28 | DER-DERIVED-LEDGER-20261002.md | DER | 生成册三尺+结构门族复检（auto-facts 漂 980→982 点名，未代写） | 已交卷 |
| 29 | AUD-TICKET-RECON-20261002.md | AUD | 八单账面↔盘面对账（11 单全一致；IVF/FULL/BASE 当时在飞如实标注；venv 字节码坑披露） | 已交卷 |
| 30 | PENDING-DECISIONS-20261002b.md | PEND | 待用户裁定汇编：R1 tts_refs／R2 D-28／R3 .qoder 须拍板 + Y1–Y4 建议过目 | 已交卷 |
| 31 | DRAFT-HANDBOOK-MERGE-20261002.md | MER | HANDBOOK §73 并账节起草稿（ready-to-paste，零改 HANDBOOK 本体） | 已交卷 |
| 32 | BASE-HEADAXIS-BUCKET-20261002.md | BASE/BASE-2 | HEAD 轴既存红基线 184F/21188P；双 run 红集互证+覆写事故披露+出处更正 | 已交卷 |
| 33 | TRG-HOTFACE-LOCKS-20261002.md | TRG | 14:10-14:27 热写面锁族核验（6 红经 HEAD 克隆复跑＝全既存） | 已交卷 |
| 34 | INV-WRITTEN-FACES-20261002.md | INV | 15:00 起写面终清单：本窗 41 枚全部有主（9 生产+9 测试+1 脚本+2 生成物+20 工单） | 已交卷 |
| 35 | CMV-COMMIT-DELTA-20261002.md | CMV | CM 提交清单增量勘误（97→102 行严丝合缝；五批 52→62 枚+新增批 F/G） | 已交卷 |
| 36 | M17-TTS-SPILLOVER-20261002.md | M17 | M-17 自动配音 sender_id 外溢面分析（新放行精确集合+护栏清单；TTS 三闸现态 false） | 已交卷 |
| 37 | INJ-SWEEP-20261002.md | INJ | 注毒形态清扫：下午窗 20 张全净+执法门 17 passed+零宽全树扫 | 已交卷 |
| 38 | HLP-HELP-COUPLING-20261002.md | HLP | 帮助面×人腿耦合核查：人腿宣称在帮助面完全缺席（提案不动手） | 已交卷 |
| 39 | IVF-INTIMATE-BLAST-RADIUS-20261002.md | IVF | INT 改动爆炸半径 101 件全跑：10 红全 HEAD 级既存（git archive 对照），净新增红 0 | 已交卷 |
| 40 | FULL-WTAXIS-20261002.md | FULL | 工作树轴全量 pytest（终门 B 轴输入；首跑被外部 SIGKILL 后重跑） | **在飞**（③④⑤待填，17:51 仍空；AUD 同判「未完卷无虚报」） |
| 41 | RESTART-CHECKLIST-20261002.md | RST | 重启执行清单（按 CM/CMV 提交→TTS 三闸→五枚门 PASS→SnowLuma 先行→重启后验证） | 已交卷 |

## 计数

**今日 41 张：已交卷 36 ／ 主会话代写 2（N1、MIG）／ 在飞·截断 3（FULL-WTAXIS ⑤待填在飞；HB-A、HB-C 额度墙截断末节不完整）。**
空文件/半行文件：0。

## 备注（终局报告取用）

- 代写两件均有席内自declared（N1「本件由主会话代记」、MIG「本工单由主会话代写」），非冒充（INJ-SWEEP 已核）。
- 在飞一件＝终门 B 轴（FULL），A 轴（BASE）已交卷双 run 互证；分桶终值待 FULL 落盘后跑 `scripts/ab_red_bucket.py`。
- W-E05-GATE-GAPS-20260930.md 按工单名为 09-30 波产物、mtime 今日 03:43，计入今日盘面。
- 本席全程只读，唯一写面＝本件；零 git 写、零进程动作、零配置改。
