# INV 工单 · 下午窗（15:00 起）写面终清单（2026-10-02，本席全程只读，唯一写面＝本工单）

## ① 快照命令与计数

- `git status --porcelain=v1`：**102 枚**（60 ` M` + 42 `??`）。
- 逐面 `stat -c '%y'` 切桶：**≥2026-10-02 15:00 ＝ 本窗 41 枚**（9 ` M` + 32 `??`）；**<15:00 ＝ 前窗遗产 61 枚**。
- 注意：`docs/db-owners.md` mtime＝10-01 19:41（跨日遗留）；`.zcodeignore` 14:55（本窗红线前 5 分钟，归前窗）。

## ② 本窗桶认领表（41 枚，全部有主）

### 生产件（9）

| 面 | mtime(+0800) | 认领席 | 依据 |
|---|---|---|---|
| `plugins/.../domains/ops/db_backup.py`（新，自 runtime/ 挪家） | 15:49:05 | 挪家批 A（主会话/X1b） | CM 工单 §批A「挪家(3)」；DRAFT §73 任务0 |
| `plugins/.../domains/ops/admin/runtime_admin.py` | 15:49:26 | 同上（X1b）：:244 import 改新家 + backup 命令面 | CM「runtime_admin.py diff 实读＝…本窗净改，X1b 一席位」 |
| `plugins/.../domains/media/capabilities/tts.py` | 16:06:44 | INT（:1554 补传 sender 第四参）＋B1 在飞混面（`_quota_bound` 配额闸，同文件不可拆，随批 B 走） | INT/IVF 工单；DRAFT §73 批B |
| `plugins/.../domains/chat_reply/runtime/content_route.py` | 16:09:26 | INT：群分支四步人腿（:931-968） | INT 工单；REV/IVF 复核；DRAFT §73 |
| `plugins/.../domains/core/write_trace.py`（新） | 16:42:26 | L2：lint 3 枚（F401/S110/RUF022） | L2 工单独占写面声明 |
| `plugins/.../llm_engine/prompt_template.py`（新） | 16:42:47 | L2：lint 1 枚（UP035） | 同上 |
| `plugins/.../runtime/capability_protocols.py` | 16:43:11 | L2：RUF100 摘除 | 同上 |
| `plugins/.../domains/transport/sender/nonebot.py` | 16:43:11 | L2：RUF023；⚠ 主 hunk 属 F3 邮件重投在飞面（CM 已剔出批 D） | L2 工单＋CM 禁入/暂缓批注记 |
| `tests/test_db_owners_coverage.py` | 16:43:11 | L2：PIE810 一行 | L2 工单批 3「10 passed」 |

### 测试件（9）

| 面 | mtime | 认领席 | 依据 |
|---|---|---|---|
| `tests/test_migration_status_assignment_gate.py`（新，15 腿） | 16:21:37 | MIG（顺带修 1 lint） | MIG 工单；DRAFT「lint 27→0 分账」 |
| `tests/test_claims_subset_implementation_gate.py`（新） | 16:23:22 | L1（6 枚 lint） | L1 分账 claims6 |
| `tests/test_prompt_template_layer_w1.py`（新） | 16:24:24 | L1（3 lint＋修门真 bug：Expr 包装节点） | L1 分账 w1 3 |
| `tests/test_seat_t1_persona_contract_20261002.py`（新） | 16:24:24 | L1（1 枚 SIM102） | L1 分账 seat_t1 1 |
| `tests/test_store_write_trace_d2.py`（新，17 腿） | 16:47:31 | D2F（注毒双腿同批抹净根修） | D2F 工单「17 passed」 |
| `tests/test_ab_red_bucket.py`（新，9 腿） | 16:56:58 | BKT | BKT 工单「9 passed」 |
| `tests/test_db_backup.py`（新，28 腿） | 17:01:38 | DBT（接手 X1c 阵亡半成品重写） | DBT 工单「六腿 28 枚」 |
| `tests/test_intimate_group_switch_delivery.py`（新，18 腿） | 17:07:34 | INT 16 腿＋REV 补 2 腿（只 append） | INT/REV 工单「18 passed」 |
| `tests/test_config_key_registration_ledger.py` | 17:09:47 | 主会话：地板按现算复录 (784,1612,3,688)（CHK 锁7 四红销案） | DRAFT §73「CHK 锁族普查」节 |

### 脚本（1）

| `scripts/ab_red_bucket.py`（新，纯标准库） | 16:47:31 | BKT（与 test_store_write_trace_d2 mtime 同纳秒＝AUD 已注记的同批拷贝痕迹，内容不受影响） | BKT 工单＋AUD §异常注记 |

### 生成物（2）

| `docs/auto-facts.md` | 17:24:03 | 主会话 `doc_sync --write` 重录（测试文件数 980→982，+2＝DBT/BKT 两新件；DER 复检备 expected 件） | DRAFT §73「派生册重录」 |
| `docs/command-catalog.md` | 17:28:25 | 主会话派生册再生成批（`command_catalog --check` 83 topics 同批；列 CM 禁入批） | DRAFT §73 同节＋CM 禁入批清单 |

### patches 工单（20，各自即席自物）

DOC-DBBACKUP-REFS(16:06) / INT-INTIMATE-PERSON-GATE(16:11) / L1-TESTLINT(16:27) / MIG-STATUS-GATE-PREDICATE(16:34) / L2-PRODLINT(16:45) / D2F-WRITETRACE-POISON(16:48) / FULL-WTAXIS(16:50) / CHK-LOCKFAMILY(16:58) / BKT-AB-BUCKET(16:59) / IMG-IMAGERY-AUDIT(17:00) / DBT-DBBACKUP-TESTS(17:03) / GATE-TYPECHECK-LINT(17:07) / REV-INTIMATE-ADVERSARIAL(17:10) / CM-COMMIT-PLAN(17:21) / DER-DERIVED-LEDGER(17:22) / IVF-INTIMATE-BLAST-RADIUS(17:23) / AUD-TICKET-RECON(17:27) / PENDING-DECISIONS-20261002b(17:27) / DRAFT-HANDBOOK-MERGE(17:30) / BASE-HEADAXIS-BUCKET(17:30)。

## ③ 无主面点名

**零枚。** 41/41 全部有主（工单独占写面声明或主会话在盘动作双证）。唯一注记＝tts.py 一文件双主（INT＋B1 在飞混面）、nonebot.py 一文件双主（L2 lint＋F3 邮件重投主 hunk）——CM 工单已给出随批归属，非遗漏。

## ④ 前窗遗产桶（<15:00，61 枚，只计数＋前 10 枚点名）

前 10（按 mtime 序）：`docs/db-owners.md`(10-01 19:41) / `domains/files/capabilities/download.py`(01:13) / `tests/test_reply_policy_preset_command.py`(01:17) / `tests/test_reply_policy_permanent.py`(01:17) / `tests/test_reply_style_imagery_default.py`(01:17) / `domains/chat_reply/capabilities/chat.py`(01:28) / `tests/test_download_artifact_container_gate.py`(01:29) / `tests/test_tts_cache_quota_shape_guard.py`(01:31) / `patches/B1-CONFIG-REQUEST.md`(01:44) / `tests/test_nonebot_sender.py`(01:44)。其余 51 枚不展开（含 HANDBOOK 13:26、AGENTS 13:31、HANDOFF 13:22、echo/meme_library 14:10、render_hashes 两枚 14:27、`.zcodeignore` 14:55 等，归属见上午窗各工单与 HANDOFF §十七）。

## ⑤ 与上午窗（HANDOFF §十七，在飞 51→74 枚）对照

本窗收编了 §十七 在飞清单中的：`runtime/db_backup.py`（挪家为 `domains/ops/db_backup.py` 收编进批 A）、`write_trace.py`／`prompt_template.py`（L2 lint 收编）、六枚在飞新测试锁中的五族收编为终态（intimate 18 腿／claims／migration／d2 17 腿／w1＋seat_t1）并新增 db_backup 28 腿、ab_red_bucket 9 腿、ledger 地板复录；§十七三枚热写面中 `auto-facts.md` 本窗由 doc_sync --write 重录收编（`test_prompt_injection_order.py` 05:34 与 `HANDBOOK.md` 13:26 两枚仍在前窗桶，HANDBOOK 合并稿在 DRAFT 工单待落）。其余未收编在飞面＝本单 §④ 的 61 枚前窗桶。

## 结论

本窗（15:00 起）净写 **41 枚**（9 生产＋9 测试＋1 脚本＋2 生成物＋20 工单），**全部有主、零无主**；前窗遗产 61 枚未动、未混桶。本席全程只读，唯一写面＝本工单。
