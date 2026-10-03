# CM 工单 — 修复波逐批提交清单（席 CM · 2026-10-02 下午窗 · 只读清单席）

> 使命：为用户「亲手提交」产出逐批清单（本窗所有席零 git 写，提交动作全归用户）。
> 每批＝动机一句话＋显式路径清单＋批内检查点＋提交信息正文（用户复制成
> `patches/CM-COMMIT-MSG-<批号>.txt` 后裸 `git commit -F` 用）。
> 🔴 本仓 pathspec commit 曾静默少提一次（台账 #70★）——每批必过第四节防吞口诀。

## ① 快照

- HEAD＝`143098d`（分支 `v0.0.1-alpha.3`）。
- 初拍 `git status --porcelain`＝**95 行**（2026-10-02T09:05:09Z）；复拍＝**97 行**（09:11:25Z）。
- 🔴 在飞实证：两次快照之间多出 `patches/GATE-TYPECHECK-LINT-20261002.md`、
  `patches/REV-INTIMATE-ADVERSARIAL-20261002.md` 两枚 ??——**别席仍在写盘**。
  本清单只对 09:11:25Z 快照负责；**每批动手前重跑 status 核对**（见第四节）。
- 归属取证方式：本席实读各文件 diff 与在册工单（INT/IVF/REV/L1/L2/D2F/DBT/MIG/DOC/BKT/P3A/B1/IMG/BASE/FULL/CHK/GATE），
  未实跑任何测试（零进程动作）；HEAD 轴自洽性判语按此定性。

## ② 逐批清单

> 建议提交顺序 **A → B → D → C → E**：批 C 的测试件依赖批 A/D 生产件真身在库
> （test_db_backup←A；w1/d2/timeout_umbrella←D），按字母序提交会在 D 之前造出断头 HEAD。

### 批A 挪家批（3 枚）

动机：db_backup 从 runtime/ 挪家 domains/ops（席 X1b P4.1 保命件），唯一生产消费者同批改 import，挪家指针普查随批。

```
plugins/bot_unified_runtime/domains/ops/db_backup.py
plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py
patches/DOC-DBBACKUP-REFS-20261002.md
```

- 旧路径 `runtime/db_backup.py` 本就未跟踪，挪走后 **status 里它的缺位＝正确形态**（复拍已核，勿找补）。
- runtime_admin.py diff 实读＝backup 命令面＋`_BACKUP_WRITE_ACTIONS`＋`from plugins.bot_unified_runtime.domains.ops import db_backup`（本窗净改，X1b 一席位）。
- 检查点：`git show --stat HEAD` 应见 **3 枚**；其中 runtime_admin.py 增行约 +96。

提交信息正文（复制成 patches/CM-COMMIT-MSG-A.txt）：

```
fix(ops): db_backup 挪家 domains/ops＋runtime_admin 唯一消费者同批接线（席 X1b P4.1＋DOC 指针普查）

- runtime/db_backup.py 挪家 domains/ops/db_backup.py；旧路径未跟踪，git 无删除记录，status 缺位即正确形态
- runtime_admin.py 唯一 import 消费者同批改新家；backup 命令面＋_BACKUP_WRITE_ACTIONS 门同批
- 附 DOC 工单：全树残余指针普查（唯一真实 import 已是新路径；docs 侧残余另账）
- 测试件 tests/test_db_backup.py 随批C入库（依赖本批真身）
```

### 批B 亲密人员门批（6 枚）

动机：2026-10-02 用户裁定「人在私聊白名单 ⇒ 任何群都能开」，席 INT 实施＋席 REV 对抗复核落库。

```
plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py
plugins/bot_unified_runtime/domains/media/capabilities/tts.py
tests/test_intimate_group_switch_delivery.py
tests/test_tts_cache_quota_shape_guard.py
patches/INT-INTIMATE-PERSON-GATE-20261002.md
patches/REV-INTIMATE-ADVERSARIAL-20261002.md
```

- content_route.py＝**INT 纯改**（群分支四步顺序＋人腿＋docstring，diff 实读与工单逐字对上）。
- ⚠ tts.py＝**混两席**（IVF 工单实锤）：INT 的 sender_id 第四参＋席 B1 的 `_quota_bound` 配额形态闸。
  两枚 hunk 均本窗交付、同文件不可拆——整文件随本批收；B1 测试件 test_tts_cache_quota_shape_guard.py
  随批同收（该测试钉的缺省态＝config 现值，config.py 本窗未动，自洽）。
- 检查点：`git show --stat HEAD` 应见 **6 枚**；content_route 群分支含「2026-10-02 用户裁定」注释行。

提交信息正文（patches/CM-COMMIT-MSG-B.txt）：

```
fix(content-route): 亲密模式群侧人腿——人在私聊白名单即任何群放行（2026-10-02 用户裁定）

- content_route.py 群分支改四步顺序：群黑名单永远赢、群白名单次之、人腿再次、其余不放行；空 sender_id 与旧版逐字节一致
- tts.py M-17 自动配音消费者补传 sender_id 第四参；同文件另含席 B1 的 _quota_bound 配额形态闸（防布尔混入把配额变清空），一并入库
- 附 INT 实施工单＋REV 对抗复核工单；test_intimate_group_switch_delivery 16 腿、test_tts_cache_quota_shape_guard 同批
```

### 批D 生产件收编批（12 枚；建议先于批C）

动机：本窗各席生产面收编——留痕原语＋W1 模板层＋timeout-umbrella 族＋P3.11 死判据根修＋D1 缺口＋P3.9 消毒。

```
plugins/bot_unified_runtime/domains/core/write_trace.py
plugins/bot_unified_runtime/domains/chat_reply/llm_engine/prompt_template.py
plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py
plugins/bot_unified_runtime/domains/chat_reply/character/quirks.py
plugins/bot_unified_runtime/control_plane/config_store.py
plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py
tests/test_reply_policy_permanent.py
tests/test_reply_policy_preset_command.py
plugins/bot_unified_runtime/domains/chat_reply/runtime/deadline.py
plugins/bot_unified_runtime/runtime/capability_protocols.py
plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py
plugins/bot_unified_runtime/domains/files/capabilities/download.py
```

逐件归属与人工过目标注：
- write_trace.py（新）＝D2 族留痕原语，**reply_policy/quirks/config_store 的 import 依赖，必须在本批**。
- prompt_template.py（新）＋file_exchange.py＝W1 模板层一对（file_exchange diff 实读含 register_prompt_template 接线）。
- quirks.py＝席 D2 留痕接线（D2F 工单认定与 D2 交付一致）。
- config_store.py＝席 D2（diff 席标实读）。
- reply_policy.py＝⚠ **混两席但同族**：席 N1 P3.11 两刀（真身角色名＋超管只认中央角色面）＋席 D2 WriteTrace 接线。
  **两枚伴随测试 test_reply_policy_permanent / test_reply_policy_preset_command 必须同批**
  （旧测试用 "super" 角色名，不随批＝HEAD 轴必红；diff 实读为 N1 翻转）。
- deadline.py＋capability_protocols.py＝席 V1 timeout-umbrella 预算族（配套测试 test_timeout_umbrella_remaining_legs 在批C）。
  ⚠ capability_protocols.py 另含 L2 一枚 RUF100 lint hunk——本窗净改为主，收前人工过一眼 diff。
- chat.py＝D1 缺口单 hunk（manual ack 隐私档 PERSONAL→context.privacy_level，本窗净改）。
- download.py＝席 B1 P3.9 落盘名消毒（配套测试 test_download_artifact_container_gate 在批C）。
- 🔴 **nonebot.py 本批剔除**：主 hunk＝他波 F3 邮件重投（_MailRedriveEvent），L2 只占一枚 RUF023——随邮件波整批走（见③暂缓）。
- 检查点：`git show --stat HEAD` 应见 **12 枚**；write_trace.py 必在（缺它＝三个 store import 断）。

提交信息正文（patches/CM-COMMIT-MSG-D.txt）：

```
fix(core): 写路径留痕原语＋W1 模板层＋timeout-umbrella 族＋P3.11 死判据根修生产面收编

- write_trace.py 新件；reply_policy/quirks/config_store 三 store 留痕接线（席 D2）
- reply_policy.py P3.11 两刀（席 N1）：真身角色名替换死串 super、超管身份只认中央角色面（摘跨平台裸号冒名腿）；两枚伴随测试同批翻转
- capability_protocols＋deadline：timeout-umbrella 预算族（席 V1；capability_protocols 另含 L2 一枚 RUF100 lint）
- prompt_template 新件＋file_exchange W1 接线；chat.py D1 缺口（manual ack 隐私档只认会话档）；download.py P3.9 yt-dlp 落盘名消毒（席 B1）
- nonebot.py 未入库：主 hunk 属他波 F3 邮件重投，随该波整批
```

### 批C 测试件收编批（21 枚；建议在 A/D 之后）

动机：本窗十枚新测试件＋A/B 红集分桶器＋C-D-01 中央调度闭口常驻门及其说明页收编。

```
tests/test_claims_subset_implementation_gate.py
tests/test_store_write_trace_d2.py
tests/test_prompt_template_layer_w1.py
tests/test_seat_t1_persona_contract_20261002.py
tests/test_migration_status_assignment_gate.py
tests/test_db_backup.py
tests/test_command_admin_gate_registration.py
tests/test_timeout_umbrella_remaining_legs.py
tests/test_ab_red_bucket.py
tests/test_central_dispatch_closure_gate.py
tests/test_download_artifact_container_gate.py
tests/test_ssrf_throat_coverage.py
scripts/ab_red_bucket.py
docs/boards/B02-routing-dispatch/README.md
docs/boards/B02-routing-dispatch/capability-registry/README.md
docs/boards/B02-routing-dispatch/decision-engine/README.md
docs/design/capability-orchestration-adoption-spec.md
patches/L1-TESTLINT-20261002.md
patches/D2F-WRITETRACE-POISON-20261002.md
patches/DBT-DBBACKUP-TESTS-20261002.md
patches/MIG-STATUS-GATE-PREDICATE-20261002.md
patches/BKT-AB-BUCKET-20261002.md
patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md
```

（上表 23 行＝测试 12＋脚本 1＋文档 4＋工单 6；枚数以 add 后核对为准。）

逐件标注：
- test_db_backup＝DBT 席六腿，**依赖批A**；test_store_write_trace_d2（D2F 修注毒腿）／test_prompt_template_layer_w1（L1 lint＋门修）／test_timeout_umbrella_remaining_legs＝**依赖批D**。
- test_command_admin_gate_registration＝P3a 提案席唯一代码交付（其余为提案文本）。
- ab_red_bucket.py＋test_ab_red_bucket＝BKT 自证对（9 passed，工单实跑在册）。
- test_central_dispatch_closure_gate＝席 C-D-01 常驻门；B02 三页说明＋orchestration spec 同批（门与说明页互引，文档同批家规）。
  ⚠ 该族与暂缓面 board_doc_ownership/test_doc_ownership_ledger 有账面牵连，收后跑 test_doc_ownership_ledger 核对（本席未实跑）。
- test_ssrf_throat_coverage＝B1 收库守卫（已入库 56e09946）的夹具红修复（字面假字节被魔数守卫拦死）；HEAD 轴应为红转绿，本席未实跑验证。
- 检查点：`git show --stat HEAD` 枚数与上表一致；test_db_backup 在库且批A已先行。

提交信息正文（patches/CM-COMMIT-MSG-C.txt）：

```
test(wave): 本窗测试件收编——db_backup 六腿＋留痕注毒自证＋w1 门＋A/B 分桶器＋中央调度闭口常驻门

- 新测试件十二枚：db_backup（DBT）、store_write_trace_d2 注毒双腿同抹（D2F）、prompt_template_layer_w1＋seat_t1（L1）、migration_status 量具收窄（MIG）、command_admin 门注册（P3a）、timeout_umbrella（V1 族）、download 落点门＋tts 配额形状随批B已收、claims_subset
- ab_red_bucket 分桶器＋9 腿自证（席 BKT）：终门 A/B 红集分桶 NEW_ONLY 空才放行
- 中央调度闭口常驻门（席 C-D-01）＋B02 三页说明＋orchestration spec 同批
- test_ssrf_throat_coverage 夹具改喂真 PNG 魔数（对已入库收库守卫的红修复）
- 依赖批A（db_backup 真身）与批D（write_trace/prompt_template/umbrella 族）先行入库
```

### 批E 工单/文档批（9 枚）

动机：本窗只读席/普查席工单与交接档增量落库。

```
patches/B1-CONFIG-REQUEST.md
patches/B1-TTS-CACHE-OUTTMPL-20261002.md
patches/BASE-HEADAXIS-BUCKET-20261002.md
patches/CHK-LOCKFAMILY-20261002.md
patches/FULL-WTAXIS-20261002.md
patches/GATE-TYPECHECK-LINT-20261002.md
patches/IMG-IMAGERY-AUDIT-20261002.md
patches/R1-RUNTIME-LAYOUT-SCAN-20261002.md
docs/HANDOFF-FIXWAVE-20261002.md
```

- R1 工单＝已跟踪件的增补（M）；HANDOFF＝交接档增量（M）。
- HB-A/HB-C 两份取证副本**已跟踪且无改动**（git ls-files 实核）→ 本批无动作，仅记录。
- 检查点：`git show --stat HEAD` 应见 **9 枚**。

提交信息正文（patches/CM-COMMIT-MSG-E.txt）：

```
docs(wave): 修复波工单与交接档落库（B1/BASE/CHK/FULL/GATE/IMG/R1＋HANDOFF）

- 七枚新工单：B1 配额缺省需求＋TTS 缓存/落盘名、BASE HEAD 轴基线、CHK 锁族普查、FULL 工作树轴全量、GATE 门禁盘点、IMG 意象族取证
- R1 布局扫描工单增补（缓存自报＋注入处置登记）
- HANDOFF-FIXWAVE 交接档增量；HB-A/HB-C 取证副本已在库无改动
```

## ③ 禁入批与暂缓批

### 禁入（本窗一律不收；理由在册）
| 件 | 理由 |
|---|---|
| AGENTS.md | 入口文档＋台账 #62 体积顶，主会话专职收口 |
| docs/HANDBOOK.md | 单一活文档，主会话专职 |
| docs/auto-facts.md | 机器册（规则 10），随主会话收口 |
| docs/command-catalog.md | 生成物（echo.py _HELP_ENTRIES 派生） |
| tests/render_hashes.json／.meta.json | 渲染生成物 |
| tests/test_trigger_word_single_source.py | echo.py 族在飞面 |
| …/chat_reply/capabilities/echo.py | 别会话持有面（P3A 工单点名） |
| …/meme/capabilities/meme_library.py | 台账 #72 表情包波 WT-only 在飞面 |
| .zcodeignore（??） | 来历未明的工具配置件，待用户裁 |
| domains/render/templates.py、.qoder/ | 快照中不存在（无 M 无 ??），无需处置 |

### 暂缓（他波在飞面，无本窗工单认领；等所属波次整批）
- #66 T8 族：memory_extract.py、reflection.py、aliases.py
- V1 族余部：voice_enricher.py（若 V1 整体收编可与批D族合并，用户裁）
- 日程族：llm_draft.py、timetable.py
- media_archive.py
- 文档完整性族：board_doc_ownership.py、board_shim_ledger.py＋test_doc_ownership_ledger / test_shim_retirement_ledger / test_documentation_consistency / test_doc_link_integrity / test_config_key_registration_ledger / test_silent_skip_ratchet / test_legacy_shim_import_ratchet
- X2 波：docs/db-owners.md＋tests/test_db_owners_coverage.py（双向锁死必须同批；内含 L2 一枚 PIE810，不单独追）
- F3 邮件波：nonebot.py＋tests/test_nonebot_sender.py（批D已剔除，理由见上）
- 其余未认领 M 测试：test_e2e_acceptance / test_e2e_help_matrix / test_item9_bypass_retention_ledger / test_mica_builders_contract / test_ops_llm_diagnostic_single_source / test_parser_contract_migration_v2 / test_persona_appearance_role_gate_pg1 / test_prompt_injection_order / test_randpic_mutation_teeth / test_voice_hook_error_card_leg
- 人格资产待裁：personas/shorekeeper/imagery_families.txt（?? 恢复件，规则 8 灵魂资产；建议连同 test_reply_style_imagery_default.py 由用户单独裁一批）

## ④ 防吞口诀（每批必念；pathspec 静默少提在册 #70★）

1. 只准 `git add -- <显式路径逐枚>`；**禁 `git add -A`／`git add .`／`git add -u`／`git commit -a`**。
2. add 后必跑 `git diff --cached --name-only`：**枚数相等＋名字逐字与工单清单一致**，多一枚少一枚都停手。
3. `git diff --cached --stat` 再对一眼增删行数量级（工单各批有预估）。
4. 裸 `git commit -F patches/CM-COMMIT-MSG-<批号>.txt`；**禁 -m 内联、消息里禁反引号**（命令替换事故在册）。
5. 提交后 `git show --stat HEAD` 核对枚数与名单；发现夹带 ⇒ `git reset --soft HEAD~1` 重来（写操作，由用户执行）。
6. **每批动手前重跑 `git status --porcelain`**：别席仍在飞（95→97 实证），清单只对 2026-10-02T09:11:25Z 快照负责；新出现的 ?? 一律先对照本清单③归类，不识的不收。

## ⑤ 未尽事项

- 别席在飞实证与落款：初拍 95 行（09:05:09Z）→ 复拍 97 行（09:11:25Z）；GATE／REV 两工单为窗口内新落盘。
- 本席零进程动作：未实跑任何测试/门/检。各批 HEAD 轴自洽性判语基于 diff 实读＋在册工单实跑读数（工单内均已带末行原样）；
  唯 test_ssrf_throat_coverage、test_central_dispatch_closure_gate 两件的 HEAD 轴读数**未实跑验证**（unknown），收后由用户跑门核对。
- B1-CONFIG-REQUEST 两枚 TTS 配额缺省仍未落 config.py（需求开放中）；将来落缺省须回改 test_tts_cache_quota_shape_guard 的缺省面腿。
- imagery_families.txt＋test_reply_style_imagery_default.py 待用户裁（见③）。
- .zcodeignore 来历未明待裁；HB-A/HB-C 已在库。
