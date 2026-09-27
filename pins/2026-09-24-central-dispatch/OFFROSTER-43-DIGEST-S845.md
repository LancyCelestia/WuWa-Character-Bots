# OFFROSTER-43-DIGEST-S845 · 表外差集 43 枚逐桶消化账 + 「三前置②」格语义判定（批次 250926I）

席：**S845** ｜ 交卷 2026-09-26 09:5xZ（UTC）｜ 仓根 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot`
写面（本席全部落盘物）：`probes/s845-offroster-digest.py` ＋ `probes/s845-invariants.py` ＋ 本件。零落地、零 commit、零动基线、零改生产件、零拨闸、零重启。
在飞标记：本席两次尺跑于 09:47–09:54Z（census 快照 `generated_at_utc=2026-09-26T09:50:26Z`），席已交卷即撤。

---

## §0 一句话总账（先给读的人）

**43 枚不是一坨，是三坨：36 枚 routed＝s762 那包逐枚同名同形、今天一枚都没落（不是落了没降，是根本没贴）；
7 枚 record_only＝全仓任何声明清单都不认识它们的「真表外」，其中 5 枚与 S200 署名桶判据同形（有既有合法通道可收）、
2 枚是执行链结果上的呈现签名（该走登记或改署，不该进桶）；「脚本与测试件」「垃圾残骸」两桶现算皆 0——空桶是结论不是漏填。**
差集轴**不是假死的尺**：`unknown==0` 在现有通道下可诚实达成；真正假死的是同一格里的 offseam 轴（K-26，属 S836 面）。
格建议见 §5——保留差集硬零，不删判据，只把「消化通道」钉成派生判据＋手写上限＋注毒牙三件套。

---

## §1 复算与漂移（自己跑尺，禁抄数）

复跑（卫生四件套；两条都是本席实跑过的原命令）：

```bash
cd /c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPYCACHEPREFIX="$TEMP/s845-pyc"
V=../ChatBot_Runtime/venv/Scripts/python.exe
$V -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s845-offroster-digest.py   # 逐枚账
$V -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s845-invariants.py         # 九判据自锁（本席实跑 ALL-PASS rc=0）
```

| 格 | 简报派单值（当时值） | 本席 09:50Z 现算 | 漂移 |
|---|---:|---:|---|
| declared | 54 | **54** | 无 |
| universe | 102 | **102** | 无 |
| seam（缝上站点） | 53 | **53** | 无 |
| offseam（缝外明细） | 26 | **26** | 无（K-26 口径不变：其中 14 枚是量具放行的装配步） |
| second（第二通路违规） | 12 | **12** | 无（S836 施工单未落，`patches/s836-*` 今不在盘） |
| unknown（表外差集） | 43 | **43** | 无 |

`covers_exactly=True`；`files_scanned=373`（S807 当时值 372，+1 枚归因＝两波之间并发落件，如实记不追）。
差集分区：**routed 36 ／ record_only 7 ／ 署名桶 5（已在 43 之外：raw 48 − 5）**；`signature_claimed_not_derived=[]`（桶的反向锁今日空＝无"谎称落款"）。

---

## §2 分桶表（逐枚路径与归因依据）

桶定义（机读判据在 `probes/s845-offroster-digest.py` 头注，全部现算）：
T1 routed-未入册 ｜ T2 已在册仅署名/字段（册A∩record_only）｜ T3 真表外（册A 静态超集也不含）｜ T4 脚本与测试件 ｜ T5 垃圾残骸 ｜ T0 署名桶（差集外缘，单列不混计）。

### T0 署名桶（差集**外**的 5 枚，边界登记）

`bot.cookie_expiry_notice / bot.credential_check / bot.group_digest_push / bot.mail.notify / bot.send_queue_worker`
——S200 裁定 2.A 已摘出（claimed∩derived），不计 43、不隐身（roster＋signature_label_sites 逐枚留明细）。
简报桶目里「已在册只是署名桶」这一格在 43 **之内**的现算值＝**0 枚**（V3a：桶 ∩ 差集＝∅）。

### T1 routed-未入册 —— **36 枚**（＝s762 那本账逐枚同名，见 §4）

全部满足「尺A 在册（经 `CONTROLLED_INTERNAL_CAPABILITIES`，V4a：36 ⊆ CIC 越界 0）∧ 尺B 字面 authoring 缺 ∧ 至少一处被交给执行点」。
归因列先给堆归属（s762 §2 分堆，枚数 1+14+4+2+15=36）：

**甲堆 · 管线管理形 1 枚（零根改动可入册）**

| cid | 根落点（现算） | 点数 | 形 | state | 归因依据 |
|---|---|---:|---|---|---|
| bot.image_search | `__init__.py:6609`→`handle_async`；6627→诊断落款；`domains/media/capabilities/image_search.py:72`→结果签名 等 | 10 | 字面量 | generic | 与 bot.chat/subscribe/campus_forward 三先例同型（`PIPELINE_MANAGED` 表今仍 3 枚＝B1a 未落） |

**乙堆 · debug 族 K-合成 14 枚（必须改生产根）**

`bot.receipt, bot.audit, bot.recent, bot.queue, bot.history, bot.context, bot.llm, bot.setup.llm, bot.config, bot.readiness, bot.dialogue, bot.roles, bot.persona, bot.control`
——逐枚根落点＝`__init__.py:7517–7690` 区间 `capability_id = "bot.<sub>"` **赋值形**（变量携带→`_run_capability_through_pipeline`，消费点 :8218/:8228 共享链尾；行号 09:50Z 现算与 s762 §1 表逐枚一致）＋ `domains/ops/admin/debug.py` 各 builder 的结果签名。state 全 =none。

**丙堆 · 出站壳 4 枚（必须改根，或她裁 `_SEAM_FUNNELS` 改判）**

| cid | 根落点 | 形 | state |
|---|---|---|---|
| bot.poke | `__init__.py:6296`→`_send_parts_through_unified_pipeline` | 字面量 | wired |
| bot.group_welcome | `:6389`→`_send_text_through_unified_pipeline` | 字面量 | wired |
| bot.file | `:6536`＋`:6548`（一枚两形） | 字面量 | wired |
| bot.cookie_login | `:6716`→`_send_parts…` | 字面量 | wired |

——wired 却差集＝「包缝认得、字面量没进⑤两缝」的形态账（`_send_*` 不在 `_SEAM_FUNNELS`）。

**丁堆 · U-1 两枚（登记文本齐，必与 S761 根改写并批）**

| cid | 根落点 | state | 附账 |
|---|---|---|---|
| bot.mail.control | `:6907`→`_run_capability_through_pipeline`（真缝）＋6882/6895 落款 | wired | 登记即 violations+1 的雷在 s762 §2b 有实算 |
| bot.auto_send.preview | `:8257`→真缝＋`domains/schedule/auto_send/parser.py:135` 结果签名 | wired | 同上（`test_offseam_wired_contradiction_gate` 三本棘轮同批） |

**戊堆 · 派发表臂 15 枚（必须改生产根）**

`bot.memory, bot.why, bot.download, bot.parse, bot.reply, bot.alert, bot.logs, bot.group_policy, bot.identity, bot.quirk, bot.runtime, bot.route, bot.routes, bot.search, bot.help`
——逐枚根落点＝`__init__.py:7484–8213` 赋值形（现算与 s762 §1 表 22–36 号逐枚等值）；四枚带附加条件：`bot.group_policy`（8072–8149 五处 handler 层直返呈现件）、`bot.runtime`（一 id 三赋值点 7707/7718/7736）、`bot.help`（两入口两宿主 7146+8186）、`bot.alert/download/why`（域内 `domains/ops/smoke/diagnostics.py`、`domains/ops/admin/runtime_logs.py` 等结果签名与同步 handle 落点属 S584-E5 口径裁定面）。state 全 =none。

### T2 已在册仅署名/字段（册A∩record_only）—— **0 枚**

结构必然：满足「CIC 在册 ∧ 纯落款」的恰好就是 T0 那 5 枚（已在 43 外）。V4b 证 今日 record_only 7 枚全不在册A。空桶是结论。

### T3 真表外（record_only ∧ 静态册A超集不含）—— **7 枚**（本席主菜）

逐枚：落点、对象语义、下游消费方（全部本席 grep 现算）、建议处置。

| cid | 落点（file:line → 对象） | 语义 | 仓内消费方旁证 | 建议处置 |
|---|---|---|---|---|
| bot.admin_alert | `domains/ops/monitor/alerts.py:307`→`SendRequest` | 管理员告警投递落款 | `error_report.py:1431` 取作配置快照默认标签；`tests/test_orchestration_callsite_wave3_c.py:413` 明文登记 `MISSING_FROM_CAPABILITY_DESCRIPTOR={admin_alert,error_report}` | 入署名桶（带证据抬上限），或按该登记注释补册（它自写"补齐前锁现状"） |
| bot.error_report | `alerts.py:645` ＋ `domains/ops/monitor/error_report.py:1719`→`SendRequest`×2 | 诊断卡文本回执/卡图投递落款 | `tests/test_error_report.py`、`test_alert_error_card.py` 断言 `request.capability_id=="bot.error_report"`（消费＝断言字段，非寻址） | 同上（与桶内 `bot.group_digest_push` 完全同形） |
| bot.group_failure_notice | `domains/chat_reply/runtime/pipeline.py:1121`→`SendRequest`；`:1176`→`AuditRecord` | 群聊失败降级池 ack 投递＋审计落款 | `test_a19_group_failure_notice.py` 等 3 件断言字段；`scripts/e2e_acceptance.py:865` 按字段过滤（=观测，非调度） | 入署名桶（带证据） |
| bot.notice | `domains/core/decision/engine.py:229`→`ActionPlan` | 决策引擎（Phase-1 shadow，缺省不接管）计划域里的通知动作占位标签 | 全仓 grep **零**消费方（本席现算） | 入署名桶；B2 阶段 2 若真建「通知能力」，派生判据自动把它踢回差集＝天然出口 |
| bot.control_plane | `control_plane/features.py:109/119`→`FeatureDescriptor`×2 | 控制面功能目录里 gate 特性 id 写进 `capability_id` 字段（跨命名空间自指） | `test_feature_store_integrity.py:64` 把它当**门特性 id** 断言（不是能力） | 入署名桶；或该字段改空/改名（属控制面件 owner） |
| bot.commands | `domains/chat_reply/capabilities/echo.py:3795`→`CapabilityResult` | `/bot commands` 分支与 `/bot help` **同一真身** `build_help_result` 盖的第二枚呈现 id | `test_orchestration_callsite_wave3_c.py:366` 钉死 `stamped=={bot.help,bot.commands}` 且注释写明出路＝「先拆第二个具名真身再立独立 descriptor」 | **不入桶**（它跟在跑的执行链上，S200 教义"桶不一键抹 record_only"点名的就是这形）；处置＝登记批（拆真身）或随 s762 派发表批同落 |
| bot.decision | `echo.py:249/288`→`CapabilityResult`×2；别名表 `runtime/aliases.py:187-188`「决策/decision」→此 id | 决策影子状态展示分支的结果签名；别名在册、能力无真身 | `test_trigger_matcher_ratchet.py:66` 已把它登记进 `DANGLING_VERB_CAPABILITIES_BASELINE`（悬空动词既有账）；S200 docstring 点名 `bot.decision`「不因此被摘」 | 不入桶；处置＝补 descriptor（把展示支拆成具名真身）或收别名——沿用悬空动词账的既有通道，谁落谁现算 |

7 枚全 =record 形、零执行点（V5 注毒实证：这类 id 若无人 claim **不会**自动隐身）；无一有"垃圾"特征（每枚宿主、语义、消费方俱全）⇒ **T5＝0**。

### T4 脚本与测试件 —— **0 枚（结构性为空）**

尺⑦只记 production 面（`plugins/**`＋`--poison`），`tests/**` 只进 tests_evidence 不改差集；`scripts/**` 根本不在扫描面 ⇒ 43 枚逐枚落点全在 `plugins/`（本席现算，唯一非 plugins 前缀落点＝0）。冒烟件（`domains/ops/smoke/console_chat.py`/`route_demo.py`）虽在 plugins 内、且 `bot.why` 有 2 处冒烟面结果签名，但"全落点都在冒烟面"的 id 现算 0 枚（T4 判据跑遍 43）。**登记此格为空的原因，防后人把 K-26 账上 SM1–7（那属 offseam/second 账）混进这本账。**

---

## §3 逐桶动作与前置（她的授权面只出包、不落码）

### T1-36（动作＝执行 s762 现成包；本席不另造文本）

| 子桶 | 枚数 | 改什么 | 前置（缺任一条不许贴） |
|---|---:|---|---|
| 甲 image_search | 1 | **只改声明源**：`capability_registry.py` 落 B1a hunk ＋ `test_pipeline_managed_adapter.py` 的 `PIPELINE_MANAGED_IDS` 三→四枚同批 | 她/落码席批贴；落后 unknown 43→42、routed 36→35（影子值 S1＝54/102→55/102 已在包 §4 实算） |
| 丁 mail.control＋preview | 2 | 声明源（RouteKind 扩容＋两行 RouteCapabilityDecl）**且生产根**（S761 闭包改写）——**必并批** | 单贴登记面 ⇒ violations 12→13 当场红（包 §2b 实算）；与 S836 十二枚施工单同窗消化 |
| 乙 debug 族 | 14 | **必须改生产根**（并支+字面量进⑤缝）＋`debug.py` 37 处改指＋CIC 摘 14＋DESCRIPTOR_BUILDERS 加 builder＋尺C 行形臂安全形 | 五面同批缺一面即假账（包 §2 现算「只落名册腿＝账不动」）；**地板门重锚前置**：K-合成后 universe→89 < `ROSTER_SCAN_FLOOR=100`（现值本席复核仍 100），`REGISTERED_FLOOR=121`→107 同批复算——该两枚是门 owner 的账，禁顺手改小判据 |
| 丙 出站壳 | 4 | 二选一：改根把字面量抬进⑤两缝，**或她裁** `_SEAM_FUNNELS` 扩容（判据改判） | 出路 (b) 不由任何席单方面做（包 B3b 原文）；裁 (a) 则带尺C 行＋NOT_WIRED 摘牌跟随 |
| 戊 派发表臂 | 15 | **必须改生产根**（赋值形→字面量进缝，S241R 锚块在盘） | 先决四件：group_policy 直返五处并缝／runtime 三支面拆名或并条／同步 handle 算不算执行点的裁定（S584-E5，不裁则 alert/download/search/help 按现口径）／help 两宿主同批翻面（禁碰面：多入口活性锁与申报锁同时成立才许降账） |

全批落完：routed→0，差集只剩 record_only 7。**每一枚的"改根"格都在她的授权面**——本席只把工单与前置钉死，不代落。

### T3-7（全部不碰生产根）

- **入署名桶批（5 枚：admin_alert/error_report/group_failure_notice/notice/control_plane）**：改的是量具件 `scripts/central_seam_census.py` 登记处＋`tests/test_signature_label_bucket.py` 两处手写面（成员清单＋`SIGNATURE_LABEL_COUNT_CEILING=5→10`），**逐枚附"零执行点＋全落款形"证据**（派生判据现算本席已验：这 5 枚全部通过 `claimed∩derived` 的 derived 侧，V5.2 证明不 claim 不自动进）。前置＝桶 owner 与她点头——"只准缩不许涨"的正解是「涨＝owner 带证据改两处手写面」（该测试 docstring 原文），不是永冻。
- **登记/改署批（2 枚：commands/decision）**：域文件（echo.py）与 descriptor 面，有既有账通道（wave3-C stamped 锁、悬空动词棘轮）；**拒绝入桶**——它们是执行链结果的呈现签名，进了桶桶就成了包 §2 早警告过的第二免检册。
- 两批落完：**unknown=0 诚实可达**。

### T0/T2/T4/T5：无动作（T0 维持现状即正确；其余空桶维持为空由 V1/V3/V5 每跑自证）。

---

## §4 与 s762 对账（"两把尺不换算"的雷，逐条拆）

**①「36 枚还剩几枚未落」＝36 全未落；落了没降的情况不存在。** 现算三证：
今日 routed 集与包 §1 表 36 枚**逐枚相等**（V2a 差集双侧空）；36 枚 ∩ 今日尺B declared＝∅（V2b）；`PIPELINE_MANAGED` 表现值仍 3 枚（chat/subscribe/campus_forward，本席 grep）＝B1a 未贴。包本来就是「只出文本不落码」件，账自洽。

**② 但两把尺不换算的雷真实存在，共三枚，逐条拆：**

- **雷 A——"43 vs 43"同名不同集。** `CONTROLLED_INTERNAL_CAPABILITIES` 今值恰 43 枚（本席 AST 现算），差集今值恰 43 枚——读数的人极易把「CIC 43＝差集 43」当成同一批。实际交集只有 36（＝routed 全体）；CIC 另外 7 枚＝署名桶 5 ＋ 尺B 已 declared 的 campus_forward/emergency_info_push；差集另外 7 枚＝record_only（CIC 全无，V4b）。**换算式（现算成立）：`CIC(43) = routed(36) + 署名桶(5) + declared两枚(2)`；`unknown(43) = routed(36) + 真表外(7)`。**
- **雷 B——"尺A 在册"会吞掉债。** 36 枚在尺A（registered_capability_ids，s762 当时值 121）口径下**早已"全在册"**；谁拿尺A 汇报进度，这 36 枚债就隐形。尺B（普查差集）只认字面 authoring。⇒ 板行与任何进度叙述必须点名**哪把尺的几枚**；本席建议把 `unknown_ids_routed/record_only/signature` 三分区直接进板行（§5）。
- **雷 C——消化动作会反向顶红别的尺。** s762 §4 实测：贴 B1a ⇒ 尺B 降 1 而尺A 纹丝不动（image_search 本就在 CIC）；落 K-合成 ⇒ universe 102→89 撞 `ROSTER_SCAN_FLOOR=100` 地板（现值仍 100，本席复核）＋REGISTERED_FLOOR 121→107 复算；贴丁堆 ⇒ second 12→13。⇒ "差集降"与"地板/棘轮"必须**同批换算**，换算义务在每批的批跟随清单里（s762 §2 批跟随已备，本席不重抄）。

---

## §5 「三前置②」格语义建议（写面归板 owner；本席只给可粘贴判据草案）

现格（`probes/s0-main-goal-audit.py:444` 现读）：`YES ⇔ offseam==0 ∧ second==0 ∧ unknown==0 ∧ rc==0`，备注已写 K-26。

**先回答题面：差集不清零时那一格能不能翻绿？——按现行写法：不能，而且不该能；但"不能"不是假死，因为 unknown 轴每枚都有合法出路（§3）：36 枚走她的根批、7 枚走桶/登记批。真会假死只发生在一种前提下：有人把某一桶判成"结构性不收录"**且不建立可封存容器**——那时 `unknown==0` 才是永远 NO。**

**推荐版（不删差集判据、不冻绿）——把第三腿从裸计数改成分区判据：**

```
第三腿（差集轴）YES ⇔ rc==0 ∧
   routed == 0                       ← 收编债硬零（只走根批/声明源批，尺可验）
 ∧ record_only_unsealed == 0         ← 未处置的表外字段落款硬零
 ∧ sealed 逐枚过派生判据重算           ← claimed∩derived，落款判据每跑现算
 ∧ 板行明文输出 routed/record_only/sealed 三分区枚数与 sealed 逐枚指针（不许隐身）
第一腿（缝轴）按 K-26 改判钉 `second==0`＋offseam 拆账明细在场（S836 面，本席不越界代书）。
```

**为什么推荐这一版而不是把 unknown 从判据里删掉、或写死一个白名单：**

1. **不是放水**：`unknown==0` 没被删，只是"sealed"的定义沿用 S200 已裁的机器形状——成员**必须**同时过 authoring claim 与**从同一次 AST 证据现算的派生判据**（零执行点∧全 record 形）；`test_ceiling_is_a_handwritten_int_literal` 钉死上限是手写字面量（写成派生式＝棘轮结构性不红，该锁直接拦）；反向锁 `claimed_not_derived` 今日为空、任一 sealed 将来长出执行点即自动回债（本席注毒 V5.2 实证：新落款不 claim 不隐身）。删判据＝门槛下降；本版门槛不变，变的是"什么算处置完"的**记账口径**，且每次重算。
2. **不是自证绿**：绿的必要条件里有两样本席造不了假的东西——36 枚的根批落地（AST 直接看得见字面量进没进⑤缝）与 7 枚的逐枚处置（入桶要 owner 抬两处手写面、登记要 declared 现算+1）。注毒台（`probes/s845-invariants.py` V5）证明**新债永远进得了 debt 列**：塞一条 `handle_async(capability_id="s845.poison_routed")` 就 routed+1；塞一条落款就 record_only+1 且**不**自动 sealed。一把能被抓到新债的尺，不是一枚会自证的章。
3. **不是假死**：每一枚都有 §3 的既有通道（桶有"owner 带证据抬上限"的正门，登记有 declared 正门，根批有 s762 现成 hunk），不存在"无论做什么都非零"的构造——与 offseam-26 形成对照（那个才是 K-26 判据层面的结构性不可达，所以它的处置是**改判据钉 second**，同样需她裁，两轴处置方式不同恰说明不能一把 "全部硬零" 笼统写死）。

给板 owner 的一句话版：**第三腿现写法可以不动字面（unknown 已是去桶后口径），只要把 (i) 板行改吐三分区、(ii) 桶的 5→10 证据批走完 owner 程序，这一格就能从"永远差 7"变成"可判定趋零"；若 owner 拒走 (ii)，再把第三腿换成上面的推荐版——两版都禁止把 unknown 整个从判据里删。**

---

## §6 零污染自证（现算，非声明）

1. **写面**：本席全部落盘＝`probes/s845-offroster-digest.py`、`probes/s845-invariants.py`、本件，全在席位目录（`.superpowers/` 已 gitignore，只在本机）。`git status --porcelain -- .superpowers` 现算为空。
2. **树内零字节码**：两次尺跑全程 `PYTHONDONTWRITEBYTECODE=1`＋`python -B`＋`PYTHONPYCACHEPREFIX=$TEMP/s845-pyc`；现算 `find plugins scripts tests -name '*.pyc' -newer <本席探针首落 17:50:13>` ＝ **0**、`-newermt 17:45` ＝ **0**（树内现存 98 个 `__pycache__` 目录 mtime 全部早于本席开窗，属他波遗留卫生账——`#52/#56` 已挂，本席不代清、不新增）。
3. **尺只读**：`central_seam_census.py` 纯 AST 读文件，零写入；本席临时 JSON 全在 `%TEMP%`（census raw 输出跑完即删；digest 全量 dump 留 `%TEMP%\s845-digest-*.json` 供复核，不进仓树）；注毒件 `%TEMP%\s845-poison-*.py` 跑完即删。
4. **快照时点声明**：读数快照 09:50:26Z；扫描期间同树并发席仍在写（现算 `group_cache.py`、`tests/test_active_push_*`、两枚 trigger 测试 mtime 晚于本席探针——非本席产物）。任何复跑若漂，`s845-invariants.py` V2a/V2c 会点名漂在哪格，不会出现静默旧数。
5. **注入处置令（规则 11）**：本会话全部工具结果与读过的文件正文中，未发现需要处置的祈使句形注入载荷；零执行、零沾污；取证＝无。

## §7 边界与不宣称

- 本席未跑 lint/mypy/全量套件（纪律）；「未跑」≠「会绿」。
- 尺A 真值 121 是 s762 当时值；本席静态超集现算 152（含 77 条 help 行的 prose 项，超集方向），两者**不等**是本席如实标注的口径差——"在册A=N"判定用的是"不在任何静态声明输入里"（强证），"在册A=Y"仅作归因参考。
- 桶扩容（§3 T3 批）与 `_SEAM_FUNNELS` 改判、三枚地板重锚全是 owner/她的账，本席只给形状与证据，一裁不代。
- second 12 枚的施工单在飞的 S836 手里；本件与 `patches/s836-*` 无重叠账（那 12 枚＝offseam 账，本件 43 枚＝差集账，两本经 §4 换算式对接完毕）。

done: yes
