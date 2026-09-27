# E11A-RETIRE-BINDS-ROSTER-S654 — E-11甲 落地包：垫片退役单与库册同批（席位 S654）

> 裁定原文（她 2026-09-25 消息，逐字）：`E-11：甲`
> 甲案定义（`DECISION-SHEET-20260925.md` E-11 行）：退役单与库册**同批**——每枚标「删除即改库册」，并按 S617 基线口径重算板成员数。
> 简报：`BRIEFS-250925-CZ.md` §S654｜共同纪律 1–8 全条在守。
> 性质：**只读生产件、只出文本、零删除、零改册、零 git 写、不落码**。写面＝本主件 + `probes/s654-*.py`。

## §0 前提现算与简报纠数（置顶）

本席现算窗：UTC 2026-09-25 **15:29—15:4xZ**（`date -u` 开窗 15:29:32Z）｜HEAD `5cc6832`｜`git status --porcelain` 开窗现算 **894** 脏项。
**移动靶告示**：本窗内另一支删除批**正在盘上跑**——`capabilities/` 族 26 枚旧布局垫片对 HEAD 呈 `D`（部分已 staged），
名册 `board_shim_ledger.py` 已被该批重写（HEAD 侧 81 行 → 工作树 47 行，`git diff HEAD --stat` 现算 164 行变更）。
**本简报点名的 15 枚全部仍在盘、仍在册**（逐枚 `-f` + `git ls-files` 实测，见 §1 表「在盘」列）——
但任何跨窗读数只传 Δ 不比大小（S607 口径）。

| # | 简报／前席前提 | 本席现算 | 判定 |
|---|---|---|---|
| 1 | 简报交付③「B01 名下**三枚 4/8/19 行**再导出垫片」 | 盘上 `wc -l` 现算＝**五枚 3/7/8/12/18 行**：`mail_bridge.py` 3／`mail_adapter.py` 7／`sender/__init__.py` 8／`sender/onebot.py` 12／`message_context.py` 18（与 S646 §2.2 纠数逐值一致） | **沿用 S646 纠数，旧「三枚 4/8/19」作废**；枚数与行数两处都不对，本席以盘上现算为准（§5） |
| 2 | 简报交付①「退役单（她手里那 **15 枚**）」 | 「15」= S108 五问后新口径（A 档 17 − `policy/__init__.py` − `sources/subscriptions/__init__.py`），RULINGS-20260924 裁定 15／DELIVERY-20260924 第 15 项同串；`SHIM-DELETION-LIST.md`（S250）另给 **20 枚可删** ⊃ 本批 15（其余 5 枚 = sender×2 + security×2 + sources/subscriptions，**不在裁定 15 的字内**） | 枚数口径坐实；本席 §1 表**只做 15 枚**，其余 5 枚在 §2 尾部划界 |
| 3 | 简报交付②「既有『每枚恰属一库』零容忍腿」 | 盘上现算：**该腿未落地**——`tests/` 全树 grep「恰属一库/分区门」零命中；L-A／L-B 是 `PARTITION-GATES-S620.md` 的**可粘贴草案**（今日 xfail 口径、110/5 枚红在册），落地文本由同批 **S650** 出 | ⚠ 措辞纠正：不是「既有已生效」，是「既有草案文本」。本席守恒腿**不依赖它**也自成闭环（两发注毒实跑 §4），两腿并落才封死「改声明删文件不跟」的板侧半孔 |
| 4 | S250 §〇「三态 47｜46｜域外 99」 | `shim_retirement_census.py --report` 本席实跑复现：域外 **99**、待退役 **47**、待搬迁 **46**、名册 **47**、基线 47/46/93/99——**逐值未动**（在飞批删的是已出账的 capabilities 族，不在 47 行内） | ✅ 坐实 |
| 5 | S250 §五 E「并发窗引用索引 fail-closed」 | 本席两次撞墙：第一次 `reference_index()` 报两枚测试件 SyntaxError（`test_memory_bus_v2_write_leg.py:282`／`test_self_calendar.py:147`，**复读即 PARSE-OK**＝撕裂读实锤）；第二次跑 `test_legacy_shim_import_ratchet` 边账被 **`domains/core/safety_exec/consent.py:1517` 真语法错误**挡住（`detail=f="…"` 形态，复读仍在，mtime 23:42:54 本地＝15:42:54Z 落在本窗） | 🔴 两事分开记：撕裂读属窗噪；**consent.py 那条是在飞批的真实半成品，非本席产物、只点名不代修**（§7 PARKED）。后果：**「引用边 0」的活性复算今天给不出**——15 枚的 refs 读数以名册在册上限（逐枚 0，工作树册现读）＋「删除只会减边不会加边」的单调性代证；删除授权前的引用复算必须落安静窗（S250 同令） |
| 6 | S250 §五 D「test_copy_redline_gate 存量红」 | 该门已被 **S263（09-25）修面**：失效 pin 改指真身（:547 echo 真身等），并新立 `test_gate_scope_coordinates_are_live`（坐标活性锁 :600）——**反而把 auto_send 的 glob 族（:93）从静默缩面升成了当场红** | ⚠ 旧「存量红」口径过期；§1 表按新腿重记（auto_send 跟随面 +2 处） |
| 7 | S108 §4-1「chat.py 判不了（负样本是否依赖 ledger 行）」 | 本席读 `collect_carrier_findings`/`_is_shim`（`tests/test_doc_link_integrity.py:177-184,835-890`）：**垫片档判定＝盘上存在 + 文首 600 字节含 `Compat shim`，不读名册** ⇒ 删文件后 `capabilities/chat.py` 落 `moved` 档 ⇒ `test_negative_sample_carrier_detection`（:947 `assert res["shim"]`）与 `test_negative_sample_coord_detection`（:928 `_is_shim(resolved2)`）**两枚必红** | 🔴 **「判不了」销账：判=依赖文件存在**。同批必须把这两处负样本受害枚换成仍在盘的在册垫片（候选 `capabilities/content_parser.py`，在册 refs 上限 1） |
| 8 | 「15 枚删除触发哪把门的基线」的先验 | 本席逐门现算今值：名册基线 47/46/93/99（全 == 现算，删后走 `--write-ledger` 单调降）；`G_P1_OUTSIDE_CEILING=32`==现算 32（**饱和**，但 15 枚全不落域根外认领面 ⇒ 删除只减不增，不触）；`G_P1_CONTAIN_CEILING=15`==15（同上，不触）；`G_P2_UNCLAIMED_CEILING=160`＞现算 118（删除使未认领 **118→109**，降，合规）；豁免 29==29（fetchers 摘条 →28，降，上限字面量可不随动〔门只断言 `current<=ceiling`〕、门 owner 可顺手降 28）；`_BASELINE_COORD_UNRESOLVED=112`＞现算 **104**（acceptance-manual 改写真减、不触）；carrier 失真面现算 **21==上限 21（饱和）**——删 15 枚后 shim→moved 换位、总数守恒，**唯一例外 `runtime/reactions.py`（真身异名 `engine.py`，改不到 AGENTS.md:146 载体列就落 dead 档撞硬零腿）** | 全表逐枚见 §1；「饱和门不触」是**方向论证**（删除只减不增），不是数值巧合 |

done: 本节成文于 2026-09-25T15:4xZ，全部读数带复跑命令（§6）；表内「现算」二字体探针①②（`probes/s654-1-roster-delta.py`／`probes/s654-2-conservation-poison.py`）。

## §1 退役单总表（逐枚 → 所属库 → 删除后该库成员数 Δ → 触发哪把门的基线）

口径先钉死（三处单位陷阱，S617 同族）：
- **所属库**＝十库尺（S607 库尺＝板块 `impl_paths` 前缀认领并集，`scripts/physical_placement_census.py::claiming_fids` 唯一谓词）。15 枚里只有 5 枚真是库成员（B01×1、B02×3、B09×1），其余 10 枚住**无主面**——「删除即改库册」对它们是**改名册与豁免册、不改板成员数**；把 15 枚一律写成「都会动板账」就是本裁要防的假账。
- **Δ**＝本批单独落完后的板成员数差（探针①内存模拟 `after = universe − 15`，非口算）；「若同批改判挂真身」的净账写在备注。
- **触发基线**＝门文件里的**具名常数/硬零腿**今值与删除后的方向；「不触」＝方向论证（该账只随删除单调降）＋今值现算。

### 1.1 主表（15 枚）

| # | 垫片（省 `plugins/bot_unified_runtime/` 前缀）| 行 | 在盘/tracked | 名册 refs 上限 | 所属库（fid·根形态）| 删后该库成员 Δ | 触发的门与基线（今值→删后）| 删后必须同批改的账 |
|---|---|---:|---|---:|---|---|---|---|
| 1 | `mail_adapter.py` | 7 | ✓/✓ | 0 | **B01.mail-console·字面根**（`board_taxonomy.py:117`）| **8→7（−1）**〔B02/B09 不涉；若同批改挂真身则 B01 净 0〕| `test_all_impl_paths_exist`（字面根悬空⇒红）；`test_board_docs_are_in_sync_with_code`（B01/mail-console 3 页：README+console-driver+mail-inbound）；名册四基线随 `--write-ledger` 降（见 1.2）| 摘 :117 字面根**并补** `domains/transport/mail/mail_adapter.py`（真身现**无主**⇒无新双主；不补则该 fid 只剩 `mail_bridge.py` 一枚不可删件）＋名册行随重录消失＋3 页 `board_doc_sync --write` |
| 2 | `runtime/settings.py` | 18 | ✓/✓ | 0 | **B09.config-and-settings·字面根**（`board_taxonomy.py:823`）| **87→86（−1）**〔真身 `domains/chat_reply/runtime/settings.py` 现无主，补挂则净 0〕| 同上两条门（悬空根⇒红；B09/config-and-settings 4 页：README+config-declaration+env-example-catalog+hot-reload-model）；摘后该 fid 另有 3 条根**不空** | 摘 :823 字面根（可选补挂真身）＋名册重录＋4 页重算 |
| 3 | `capabilities/chat.py` | 18 | ✓/✓ | 0 | B02.capability-registry·**目录根**（`board_taxonomy.py:178` 的 `…/capabilities`）| **26→23（本批 3 枚合 −3）** | **无悬空根**（目录根罩着仍在盘的 `__init__.py`/`content_parser.py`⇒板门全绿、认领数**静默**掉——E-11 原始病灶）；`test_negative_sample_coord_detection`＋`test_negative_sample_carrier_detection`（两枚，判＝盘上存在+`Compat shim` 文首，**不读名册**，§0-7 已判死）；`_redline_allowlist.py` creator_name 条目（指向不存在文件＝假豁免红）| 换两处负样本受害枚（候选 `capabilities/content_parser.py`，在册上限 1）＋摘 `_redline_allowlist.py` 整条豁免（连理由）＋名册重录 |
| 4 | `capabilities/market.py` | 7 | ✓/✓ | 0 | B02.capability-registry·目录根 | 同上 −3 之一 | 同上静默形态；`test_user_copy_unification_gate.py:312` 存在性 pin（`assert (REPO_ROOT/rel).exists()`）| pin 改钉 `domains/finance/capabilities/market.py`（同文件 :313 已有 RET3「改钉 canonical」先例照抄）＋名册重录 |
| 5 | `capabilities/auto_send/__init__.py` | 7 | ✓/✓ | 0 | B02.capability-registry·目录根（子包形）| 同上 −3 之一 | 同上静默形态；`test_copy_redline_gate.py:93` 族 `capabilities/auto_send/**/*.py` 删空目录后匹配 0 → `test_gate_scope_coordinates_are_live`(:600) **当场红**（S263 新腿，§0-6）；:556 存在 pin 同红；`_AUTO_SEND_REL`(:857) 是 rel_path 字符串夹具**不红**；`test_auto_send_scope_expanded_current_tree_green`(:868) `assert≥2`——schedule 域真身恰 2 枚（`__init__.py`+`parser.py`）**仍绿贴边** | 摘 :93 族＋:556 pin 改断言侧「退役断言」族（S263 已有形状可仿）＋目录连子包一起消失后名册重录 |
| 6 | `sources/fetchers/__init__.py` | 7 | ✓/✓ | 0 | **无主面**·被 `G_P2_EXEMPT` 罩（`board_placement.py:63`）| **0**（非板成员）| `gp2_findings.stale_exempts`（豁免指向不在盘件⇒`test_physical_placement_gate` stale 腿红——现算今值 stale 0）；未认领账 118→117、豁免 29→28（`G_P2_EXEMPT_CEILING=29` 只断 `current<=ceiling`，字面量**可不随动**、门 owner 顺手降 28 属卫生非必需）| 摘 `G_P2_EXEMPT` 该行（同批）＋名册重录 |
| 7 | `character/affinity.py` | 20 | ✓/✓ | 0 | **无主面** | **0** | 板门不触（无认领）；测试面仅注释/文档串（`test_copy_single_source.py:145` 注释、`test_physical_placement_gate.py:401` 钉的是**真身**路径）| 仅名册重录 |
| 8 | `character/mood.py` | 20 | ✓/✓ | 0 | 无主面 | 0 | 无 pin（tests/scripts grep 现算零存在断言）| 仅名册重录 |
| 9 | `character/shared_group.py` | 20 | ✓/✓ | 0 | 无主面 | 0 | `test_runtime_settings_restart_required.py:7` 仅 docstring 背景 | 仅名册重录 |
| 10 | `character/memory_service.py` | 18 | ✓/✓ | 0 | 无主面 | 0 | `test_memory_bus_v2_write_leg.py:584` 是 `endswith` 跳过过滤器、**无存在断言**（真身同后缀恰也被跳——语义不因删除变）| 仅名册重录 |
| 11 | `character/memory_store_v21.py` | 18 | ✓/✓ | 0 | 无主面 | 0 | 无 pin | 仅名册重录 |
| 12 | `runtime/capability_registry.py` | 18 | ✓/✓ | 0 | 无主面 | 0 | `test_capability_registry.py:6` 仅 docstring（import 打真身 domains 形）| 仅名册重录 |
| 13 | `runtime/model_schedule.py` | 18 | ✓/✓ | 0 | 无主面 | 0 | 无 pin | 仅名册重录 |
| 14 | `runtime/natural_language.py` | 18 | ✓/✓ | 0 | 无主面 | 0 | 无 pin | 仅名册重录 |
| 15 | `runtime/reactions.py` | 12 | ✓/✓ | 0 | 无主面 | 0 | 🔴 **两枚硬跟**：①`AGENTS.md:146` 载体列所引 `runtime/reactions.py`——真身**异名** `domains/meme/reactions/engine.py`（S250 §一#9 唯一会新增死坐标那枚），不重写载体列则 shim 档→**dead 档**撞 `test_agents_carrier_paths_no_dead_entries`（**硬零、无基线**）；②`docs/acceptance-manual.md:356` 行内码坐标（改指 `engine.py`，死账现算 104≤112、属棘轮非硬跟）；助攻：`test_outbound_v21.py:713` 断言旧路径不在坐标集（删后更易成立）| 改写 AGENTS 载体列 + acceptance-manual 坐标 + 名册重录 |

### 1.2 合批公共账（15 枚同批一次跟随即可，逐枚不重复计）

| 账 | 今值（本席现算）| 15 枚落完后 | 通道 |
|---|---|---|---|
| 名册 `SHIM_ROWS` | 47 行（工作树册）| 32 行 | `scripts/shim_retirement_census.py --write-ledger`（**唯一写账口**，min() 只降不升）|
| `SHIM_RETIRE_BASELINE` | 47 | 32 | 随上 |
| `RELOCATE_BASELINE` | 46 | **46 不变**（15 枚全在退役桶）| — |
| `UNLANDED_SUM_BASELINE` | 93 | 78 | 随上（方向锁：降=合法）|
| `OUTSIDE_BASELINE` | 99 | 84 | 随上；`outside_py` 现算 99→84（15 枚全在 `domains/` 外）|
| 域外三态/在册对账 | ①漏记0 ②非垫片0 ②b0 ③0 ④**2**（`output/card_render/bridge.py`、`output/plain_text.py` 引用超上限——**他波在飞产物、与本批零交集**，批落前该门今日即红）⑤0 | 15 枚自身不新触任何对账腿 | 消 ④ 归 bridge/plain_text 的 owner，**本席不代修** |
| `test_legacy_shim_import_ratchet` 两本账 | 上限 73/202；边今值**本窗复算被 consent.py 撕裂读挡死**（§0-5），S250 旁证 prod/tests 双侧皆 0 | 15 枚引用边皆 0 ⇒ 删除只可能减边，上限**不触** | 安静窗复跑 |
| `live_shim_leaves`（capabilities 目录枚举）| 4 枚（auto_send/chat/content_parser/market，本窗实跑点名）| 1 枚（content_parser）| 无定值 pin；`test_subpackage_shims_are_not_blind` 子集判据自然成立 |
| G-P2 语义A | 未认领 118 / 违规 89 / 豁免 29 | 109 / 80 / 28 | 上限 160 与 29 皆 `current<=ceiling`，降方向合规 |
| G-P1 越界/包含对 | 32/32、15/15（**双饱和**）| 不触（15 枚无一被板认领为越界声明点，删除不改声明点集，§1.1 两枚字面根是**摘**不是增）| 饱和门只数声明、本批声明侧只减 |
| 文档坐标 | unresolved 104≤112；carrier 失真 **21==21（饱和）**；legacy 305≤598 | unresolved 最多 +1（acceptance-manual 若不改写）——改写后不增；carrier 15 处 token 中仅 #15 会换档进 dead，其余 shim→moved 总数守恒 ⇒ **同批改 AGENTS.md:146 后失真 21→21、dead 0→0** | 见 §1.1 #15 |
| 生成物 | `board_doc_sync --check` 现算 CLEAN 前提被在飞波打破（§0 移动靶）| 本批只动 B01 3 页＋B09 4 页机器块；`--write` 后 `--check` 归零 | 安静窗 |
| 哈希册 `verify_hashes` | 15 枚**逐枚 grep 零在册**（§6 命令）| 幂等空操作（本批不触）| — |
| `command_catalog` / `doc_sync` | 本批不涉 `_HELP_ENTRIES`/config 字段 | 不触 | — |

**净读数（一句话）**：15 枚里**改板成员数的只有 4 枚**（B01 −1、B02 −3、B09 −1），**改豁免账的 1 枚**（fetchers），**改测试件 pin/受害枚的 3 枚**（chat/market/auto_send），**硬跟文档的 1 枚**（reactions→AGENTS 载体列），**其余只剩名册重录一项的 9 枚**——「每枚都要动板册」是把 E-11 做过头，「删完只重录名册就完事」是没做 E-11：两头都要按表逐枚对齐。

done: 本节成文于 2026-09-25T15:4xZ；「Δ」列全部来自探针①内存模拟（复跑 §6-2），非手算。

## §2 逐枚跟随账（批归属与同批件）

S250 的四批结构仍成立，本席按 15 枚批（裁定 15 的字）重切：

| 批 | 枚 | 批内依赖边（现算依据）| 本席加判（对 S250 的差量）|
|---|---|---|---|
| **批 1**（9 枚，零板面跟随）| `character/{affinity,mood,shared_group,memory_service,memory_store_v21}.py` + `runtime/{capability_registry,model_schedule,natural_language}.py` | 彼此独立、无目录清盘、无 pin；`reactions.py` **移出本批**（下表）| 同意 S250「批 1＝名册＋文档」；补：本批落完 OUTSIDE/RETIRE 基线一次 `--write-ledger` 即可，不必逐枚重录 |
| **批 1′**（reactions 单列）| `runtime/reactions.py` | `AGENTS.md:146` 载体列改写必须与 `git rm` **同一笔**——dead 档走**硬零腿**（无棘轮），分两步中间态必红且红的是「文档撒谎」不是「数没对」| S250 把它放批 1（判「名册+文档 1 条」）；本席按硬零/棘轮之分**单列**，改写面 = AGENTS 载体列 + acceptance-manual:356 两处 |
| **批 2**（3 枚，测试件 pin 同批）| `capabilities/{chat,market}.py` + `capabilities/auto_send/__init__.py` | ①chat 的两处负样本换腿（§1.1#3）先于删除落笔同笔；②market 的 :312 pin 换钉真身照 :313 RET3 先例；③auto_send 摘 :93 族＋:556 pin——**S263 后这三处从「可缓改」升为「同批必改」**（§0-6）；`capabilities/` 目录本体**不消失**（`__init__.py`+`content_parser.py` 留驻）⇒ B02 目录根不摘、成员数静默 −3 由 §3 腿②兜住记账 | S250 批 2 警示的「第 4 枚 content_parser 一退役 `assert leaves` 与 `SHIM_DIR.iterdir()` 两条同红」**不适用本批**（content_parser 不在 15 内）；但**负样本受害枚候选若选它**，下次它退役时这两处 + doc-link 两处要一起换——本席建议换腿选它正是为了让「最后被删的那枚」届时集中改门 |
| **批 3**（1 枚，豁免账）| `sources/fetchers/__init__.py` | 与 `G_P2_EXEMPT` 摘条同批（stale 腿）；目录清空即消失，无板认领 | S250 把 security×2 与本枚并批——那两枚不在 15 内，本批缩成单枚 |
| **批 4**（2 枚，板认领字面根）| `mail_adapter.py` + `runtime/settings.py` | 两枚各自「摘根＋删文件＋（mail）补真身」同一笔——字面根悬空走 `test_all_impl_paths_exist` 硬腿，**不存在安全中间态**；生成物 B01×3 页＋B09×4 页同批 `--write` | mail_adapter 补挂真身 `domains/transport/mail/mail_adapter.py`（现无主 ⇒ 无 L-B 双主风险，本席现算）；settings 真身 `domains/chat_reply/runtime/settings.py` 现也无主，补不补由 E-10/S653 口径定，**本批只记两案 Δ 都闭合**（−1 或净 0）|
| **批间序** | — | ①#15 的 doc 改写、②批 2 的换腿、③批 4 的摘根都属「删前必改声明侧」，与删除同笔；其余各批彼此无依赖 | 唯一硬序：**所有批之后**才 `--write-ledger` 重录一次（合并降账）＋**所有批之后**才 `board_doc_sync --write`；两生成器只在安静窗跑（S250 §五·C 在飞面点名仍有效）|

**划界（不在裁定 15 的字内、但会被「20 枚可删」转述裹挟的 5 枚）**：
`sender/__init__.py`、`sender/onebot.py`（B01.qq-snowluma **目录根**罩着，删除后目录消失⇒悬空根红——逐枚处置见 §5）；
`security/__init__.py`、`security/memory_sanitize.py`（B10 系目录根 `:952` 罩着；**外加** `tests/test_dev_ps1_no_shim_module_targets.py` 以 `security/memory_sanitize` 作现网取样受害枚，删前必换腿——该门 :35/:37 现算仍钉 `_LEGACY_MEMORY_SANITIZE` 串）；
`sources/subscriptions/__init__.py`（B05.subscription 目录根 `:463`；且 `AGENTS.md:136` 载体列「整目录已垫片化」token 罩它）。
⇒ 这 5 枚属后续批；谁把「15」复述成「20」一起删，会在 `test_dev_ps1_no_shim_module_targets`、B01/B05/B10 三条目录根与三处载体列上**当场红**。

done: 本节成文于 2026-09-25T15:4xZ；所引行号（:93/:556/:600/:312/:117/:823/:178/:63/:89/:463/:952/:146/:356/:35）均为本窗盘上现算直读。

## §3 守恒断言可粘贴文本（两腿：文件侧零容忍 + 声明侧守恒）

### 3.0 与 S650 门①／既有账的关系（先读，免得把三把尺当成一把）

简报交付②原话「既有『每枚恰属一库』零容忍腿 ＋ 本席补的『删声明必同批守恒』腿」——§0-3 已把前半句纠准：
那条腿是 **S650 §3.1 门①（草案，未落地）**。它与本席两腿各测各的，互不替代：

| 尺 | 测什么形态 | 本批 15 枚删除时对它的效果 |
|---|---|---|
| S650 门①（每枚恰属一库） | 「成员」形态：`plugins/**` 每枚 .py 被恰一板块认领 | **不红**——删文件不造孤儿也不造双主，它抓不到「拿真相换棘轮」 |
| 本席腿①（在册⇒在盘） | 「删文件不跟册」：名册每一行盘上必须存在 | S1 注毒当场 15 枚红（§4） |
| 本席腿②（撤声明⇒同批删或真过户） | 「改册不跟文件」：摘名册行／摘板块字面根／摘豁免条，三类各断言 | S2 注毒 18 处红（§4） |
| census 既有 `missing_registration` 腿（`shim_retirement_census.py:42`） | 「盘上有垫片记号却未入账」当场红 | 与腿②是**时段咬合**：腿②的 HEAD-vs-工作树差集形只在**未提交窗**有牙（批内半落地态——恰是拿真相换棘轮发生时段）；批提交后 head==wt、差集自然清空，盘侧终态由本腿接上。两形缺一不可，只落一个就留半孔 |

两腿均**零容忍、无基线常数**——「降账即绿」结构性不可能。且与门①不同：**两腿今日今值 0/0（S654 15:4xZ 与 S687 17:32Z 两窗实跑同值，§4-S0），落地即绿、不需要 xfail**——挂账的不是这把尺。

### 3.1 可粘贴正文（判据函数，与 `probes/s654-2-conservation-poison.py` §legs 区逐字同源）

```python
# ===================== E-11甲 守恒门（S654 落码草案；两腿同文件同批落，禁只落一半） =====================
# 每枚 .py 的退役 = 一次「盘侧删除 × 声明侧撤销」的成对交易；本门执法成对性本身。
# 零容忍、无基线常数、无 xfail（今值 0/0，§4-S0）。宇宙与取数全走唯一口：
#   名册 src.load_ledger_rows ／板块 ppc.feature_impl_paths＋flatten_claims ／豁免 ppc.load_placement
# HEAD 侧同一支解析器喂 `git show` 文本（禁第二 AST 读者）；git show 输出一律 .decode("utf-8")（台账 #50 GBK 坑）。
from typing import Callable

def leg_rows_bind_disk(wt_roster: set[str], exists: Callable[[str], bool]) -> list[str]:
    """守恒腿①（删文件必改册·在册⇒在盘）：名册每一行必须盘上存在。零容忍、无基线常数。"""
    return sorted(p for p in wt_roster if not exists(p))


def leg_withdrawal_binds_deletion(
    *,
    head_roster: set[str],
    wt_roster: set[str],
    head_py_roots: set[str],
    wt_py_roots: set[str],
    head_exempts: set[str],
    wt_exempts: set[str],
    exists: Callable[[str], bool],
    claimed: Callable[[str], bool],
) -> list[str]:
    """守恒腿②（改册必删文件·撤销声明⇒同批消失或真过户）。零容忍、无基线常数。

    ②a 名册行被摘 ⇒ 该路径**必须不在盘**（名册是退役债账，"另有 fid 认领"不构成豁免）。
    ②b 板块字面 .py 根被摘 ⇒ 该路径不在盘，**或**被别的根（字面/目录）覆盖（＝同批改判过户）。
    ②c G_P2_EXEMPT 条目被摘 ⇒ 该路径不在盘，**或**已被板块认领（豁免不再需要）。
    """
    v: list[str] = []
    for p in sorted(head_roster - wt_roster):
        if exists(p):
            v.append(f"②a名册摘行未删文件: {p}")
    for p in sorted(head_py_roots - wt_py_roots):
        if exists(p) and not claimed(p):
            v.append(f"②b字面根摘除未跟: {p}")
    for p in sorted(head_exempts - wt_exempts):
        if exists(p) and not claimed(p):
            v.append(f"②c豁免摘条未跟: {p}")
    return v
```

### 3.2 装配壳（取数与断言；照此落即得完整常驻门）

```python
import subprocess
import pytest
import shim_retirement_census as src
import physical_placement_census as ppc

LEDGER_REL = "plugins/bot_unified_runtime/domains/core/board_shim_ledger.py"
TAXONOMY_REL = "plugins/bot_unified_runtime/domains/core/board_taxonomy.py"
PLACEMENT_REL = "plugins/bot_unified_runtime/domains/core/board_placement.py"

def _git_show_head(rel: str) -> str:
    out = subprocess.run(["git", "show", f"HEAD:{rel}"],
                         cwd=ppc.REPO_ROOT, capture_output=True, check=True)
    return out.stdout.decode("utf-8")  # encoding 必带——缺它整门在 GBK 机器上假红（台账 #50）

def _py_literal_roots(rows: list[tuple[str, tuple[str, ...]]]) -> set[str]:
    return {p for _fid, paths in rows for p in paths if p.endswith(".py") and "/" in p}

def test_shim_retirement_conserves_declarations() -> None:
    """E-11甲：退役单与库册同批守恒（文件侧零容忍腿 + 声明侧守恒腿，两腿并判）。"""
    # 工作树侧（真尺）
    wt_roster = {r["path"] for r in src.load_ledger_rows()}
    wt_fip = ppc.feature_impl_paths()
    wt_claims = ppc.flatten_claims(wt_fip)
    wt_py_roots = _py_literal_roots(wt_fip)
    wt_exempts = {p for p, _r in ppc.load_placement()["G_P2_EXEMPT"]}
    # HEAD 侧（同一支解析器，喂 git show 文本；板块侧照探针② §取数 用 bds.load_taxonomy 换 TAXONOMY_PY 指针，
    # 用完 try/finally 还原——S687 注：三处模块指针替换都必须走在 finally 里，否则注毒窗污染同进程后续用例）
    head_roster = {r["path"] for r in src.load_ledger_rows(ledger_source=_git_show_head(LEDGER_REL))}
    head_fip = _feature_impl_paths_from_text(_git_show_head(TAXONOMY_REL))  # 与探针② §取数 同实现
    head_py_roots = _py_literal_roots(head_fip)
    head_exempts = {p for p, _r in ppc.load_placement(
        source=_git_show_head(PLACEMENT_REL), source_label="HEAD:board_placement")["G_P2_EXEMPT"]}
    exists = lambda p: (ppc.REPO_ROOT / p).is_file()  # noqa: E731（两腿共用一支谓词，禁各写一套）
    claimed = lambda p: bool(ppc.claiming_fids(p, wt_claims, semantic="prefix"))  # noqa: E731
    violations = leg_rows_bind_disk(wt_roster, exists) + leg_withdrawal_binds_deletion(
        head_roster=head_roster, wt_roster=wt_roster,
        head_py_roots=head_py_roots, wt_py_roots=wt_py_roots,
        head_exempts=head_exempts, wt_exempts=wt_exempts,
        exists=exists, claimed=claimed)
    assert not violations, (
        "退役单与库册失守恒（删/改声明必同批，S654 §3）：\n" + "\n".join(violations))
```

落点建议：**独立新文件** `tests/test_shim_retirement_conservation.py`（S650 的门①②推荐落 `test_physical_placement_gate.py` 尾部；三把尺同文件会制造并发争用面，分立可各自独立摘牌、注毒互不牵连）。`_feature_impl_paths_from_text` 即探针② §取数 里「把 `bds.TAXONOMY_PY` 指到 %TEMP% 落盘的 HEAD 版再 `load_taxonomy()`、finally 还原」那段的具名化——**别用第二个 AST 解析器**，与 `ppc.feature_impl_paths` 同一支是硬约束（§2 「禁各算一套」同族）。

done: 本节成文判据全部来自 §3.1 函数在探针②内的两窗实跑（S654 15:4xZ／S687 17:32Z 同值，§4）。
本节由 S687 补完（UTC 2026-09-25T17:32—17:40Z｜判据出处：`probes/s654-2-conservation-poison.py` §legs 逐字同源 ＋ `%TEMP%/s654-work/s654-poison.json` 两窗同值实跑 ＋ `shim_retirement_census.py:42` missing_registration 腿在位性盘上直读；装配壳与 §3.0 时段咬合表为 S687 按简报交付②「可粘贴」要求补形，注记不抹原席口径）。

## §4 注毒两发实跑（只删文件不改册 红 / 只改册不删文件 红）

**形态先钉死**：全程内存视图——探针② `main()` 无任何仓内写路径，只注入谓词（`exists=lambda` 翻转「在盘」答案）
与集合差（册侧摘行），输出仅落 `%TEMP%/s654-work/s654-poison.json`。仓树一个字未动。

| 态 | 注入形 | 腿① 结果 | 腿② 结果 | 判定 |
|---|---|---:|---:|---|
| **S0 今值** | 无（HEAD 册 vs 工作树册 vs 盘 三向对账） | **0** | **0** | 现树自洽，两腿今天可直落不挂 xfail |
| **S1 注毒·只删文件不改册** | 盘上 15 枚「消失」（谓词翻转），名册／板块根／豁免照旧 | **红 15**（逐枚点名＝§1.1 全表 15 行，无一漏网） | 0（无误伤——册侧未动，差集空） | 腿①有牙 |
| **S2 注毒·只改册不删文件** | 名册摘 15 行 ＋ 板块字面根摘 2 枚（`mail_adapter.py`／`runtime/settings.py`）＋ `G_P2_EXEMPT` 摘 1 条（fetchers）；盘原样；**capabilities 目录根刻意不摘** | 0（在册集合变小不失配） | **红 18** ＝ ②a×15 ＋ ②b×2 ＋ ②c×1（全点名，§ JSON） | 腿②有牙 |

**S2 的三个读数各有专司**：
- **②a×15 含 capabilities 目录根罩着的 3 枚**（chat/market/auto_send）——正回答裁甲要堵的形状：
  「另有 fid 认领」不豁免「摘行未删文件」（名册是退役债账不是认领账），目录根罩着挡不住这条腿；
- **②b×2** 只咬被摘的字面根（settings/mail_adapter），不咬未摘的目录根——腿对「过户」留了口：
  摘根但路径仍被别的根覆盖＝放行（同批改判挂真身的合法形态，§1.1 #1/#2 备注列）；
- **②c×1** 豁免摘条未删也未获认领 → 红——fetchers 那枚「改名册与豁免册、不动板账」（§1.1 口径）的豁免册半边有执法。

**正对照（纪律 7：零命中必先怀疑过滤器）**：腿① 点名 known-absent 夹具 `definitely_absent_zz.py` ✅；
HEAD 册比工作树册多 34 行（在飞 capabilities 族已被批侧删净，取样 3 枚：`capabilities/affinity.py`／
`capabilities/campus.py`／`capabilities/daily_assist.py`——34 行全部**盘上已无**，S0_leg2 因此为空而非过滤器瞎）✅；
`controls_ok: true`。

**取数今值**（两窗同）：wt_roster **47**／head_roster **81**（差 34）／字面 .py 根 wt **36** vs head **39**（差 3）／豁免 29 vs 29。

**两窗一致性**：S654 首跑 ≈23:47—23:48 本地（15:4xZ）；S687 于 **17:32:00—17:32:02Z 重跑，输出与首跑逐字段同值**
（counts／六列表／正对照全等，JSON 被同值覆写）。该窗距在飞删除批最近一次落册已过且名册未再动（§6-4 `--report` 复现 47）。

**结论一句话**：两发各红各腿、互不代咬、无一走空——「删声明不跟文件」「删文件不跟声明」两半在内存视图里都当场点名到枚。
落地版门的自证（往真树注毒）由批 owner 在安静窗按同两形复跑（本席禁删禁改册，只能给谓词注入形——如实边界）。

done: 本节成文于 S654 窗设计、S687 窗补完复跑证据。
本节由 S687 补完（UTC 2026-09-25T17:32Z 复跑实值｜判据出处：`probes/s654-2-conservation-poison.py` 两窗实跑输出＋`%TEMP%/s654-work/s654-poison.json`（现盘＝S687 17:32Z 覆写版，内容与 S654 首跑同值）；复跑命令 §6-3）。

## §5 B01 名下再导出垫片逐枚处置（盘上现算为准，旧「三枚 4/8/19 行」作废）

枚数与行数两处纠数已由 §0-1 钉死：**五枚 3/7/8/12/18 行**（`wc -l` 本窗复跑，§6-8），五枚文首 600 字节均含 `Compat shim`
（carrier 判据同源，§0-7）。今值底账（探针① S607 库尺宇宙）：**B01 成员 8 枚＝3 真身＋5 垫片**——真身三枚全在
`B01.message-normalization`（`domains/core/{board_placement,session_keys,text_boundary}.py`）；`B01.telegram` 声明根
`scripts/telegram_resilience.py` 落在库尺宇宙外，成员账不数它（S650 杀点 1 的同一条断层）。逐枚：

| # | 枚（行数）| 在册 refs 上限→活引用（现算）| 被谁认领（`board_taxonomy.py` 行·根形态）| 在裁定 15？| 删除前置 | 删后 B01 账 |
|---|---|---|---|---|---|---|
| 1 | `mail_bridge.py`（3）| 2 → **2（饱和贴边）** | `B01.mail-console` 字面根 :117（与 mail_adapter **同 tuple**）| **否**（也不在 S250「20 枚可删」内——refs 非零）| 引用 2→0 迁移先行，再摘 :117 该行＋名册行＋删文件同批 | −1 |
| 2 | `mail_adapter.py`（7）| 0 → **0** | `B01.mail-console` 字面根 :117 | **是**（§1.1 #1，批 4）| 摘根＋删文件＋（推荐）补挂真身 `domains/transport/mail/mail_adapter.py`——真身在盘**无主**（现算 §6-9），补挂无双主风险 | −1（本批已计 8→7）；补挂则净 0 |
| 3 | `sender/__init__.py`（8）| 0 → **0** | `B01.qq-snowluma` **目录根** :89（`…/sender`，罩两枚）| 否（在「20 枚」界内，属 §2 划界批）| 与 #4 **连体**：目录清空即消失⇒悬空目录根撞 `test_all_impl_paths_exist` 硬腿，不存在安全中间态；**真身已被 `B08.send-queue` 认领（现算 §6-9）⇒ B01 不可补挂**（补挂＝双主即红）| 摘 :89 目录根后 qq-snowluma 仅剩 #5 |
| 4 | `sender/onebot.py`（12）| 0 → **0** | 同上目录根罩 | 否（同上）| 同 #3；归属随 E-10乙（S653）A1–A4 适配器库裁定一并走 | 同 #3 |
| 5 | `message_context.py`（18）| 6 → **6（饱和贴边）** | `B01.qq-snowluma` 字面根 :89（第二 entry）| **否**（也不在「20 枚」内——refs 非零）| 引用 6→0 迁移先行；真身 `domains/chat_reply/ingest/message_context.py` 在盘**无主**⇒过户落点无争用，落 B01 还是 ingest 属 E-10乙 射程 | −1 |

**「20 枚」与本表的界再钉一次**（防转述裹挟）：S250 可删 20 ＝ 裁定 15 ＋ sender×2 ＋ security×2 ＋ sources/subscriptions——
`mail_bridge.py`/`message_context.py` 两枚**因引用非零连 20 都不在**，退役序必晚于本批；把它们随「B01 名下五枚一起删」转述执行＝撞 §2 划界红。

**「有货库」判定怎么变（S646 §1.2 三闸 L-6d 逐支）**：B01 今天 `0.0.0`，落因三条——①能力成员 **0**（S646 §1 表实测，
`bot.group_info` 的 handler_ref 落 domains 真身、不落 B01 成员）②名下 5/8 为再导出垫片（「库内」语义未闭合）③户主未裁（E-7/E-8/E-10 射程）。
- 本批 15 枚落完 ⇒ 8→**7**，②**不清**（余四枚）⇒ 判定原样；
- 五枚全清＋真身过户（mail×2＋message_context 可补挂，sender×2 归 B08 或 A1–A4 裁）⇒ B01＝**5～6 枚全真身**，②清；
  但 ①纹丝不动——**删垫片不产生任何能力成员**；
- 结论：**五枚再导出垫片是「无货」账里最大的一条（5/8），却只是症状不是病因**；B01 升 0.2.0 的第一道闸在 E-10乙
  适配器归属裁定与能力成员落籍，不在本退役批。本批交付只把「症状账」逐枚结清、不留第二真身。

done: 本节成文于 S654 窗设计、S687 窗补完；全部今值为 S687 盘上现算（复跑 §6-8／§6-9／§6-10，窗 UTC 17:2x—17:3xZ）。
本节由 S687 补完（UTC 2026-09-25T17:3xZ｜判据出处：行数与 `Compat shim` 记号＝盘上 `wc -l`＋文首 600 字节直读（§6-8）；认领形态与 taxonomy :89/:117 行号＝`board_taxonomy.py` 现读（§6-10）；refs 上限＝`board_shim_ledger.py` 在册行（§6-10）、活引用＝`shim_retirement_census.reference_index()` 现算（§6-5，mail_bridge 2／message_context 6 贴饱和、裁定 15 内三枚 0）；真身归属（B08.send-queue 已占 sender 两真身、mail×2 与 message_context 真身无主）＝`ppc.flatten_claims` 现算（§6-9）；B01 成员 8＝探针① JSON 同宇宙复算；有货判定口径＝S646 §1.2 L-6d 三闸原文）。

## §6 复跑命令簿

环境前缀（纪律 4，所有直跑 python 一律带；`$V`= `../ChatBot_Runtime/venv/Scripts/python.exe`，仓根执行）：

```bash
env PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
    PYTHONPYCACHEPREFIX="$TEMP/s654-pyc" "$V" -B <…>
```

| # | 复跑什么 | 命令（接前缀）| 谁·何时实跑 → 输出 |
|---|---|---|---|
| 1 | 开窗三件套 | `date -u; git rev-parse --short HEAD; git status --porcelain \| wc -l` | S654 15:29:32Z→HEAD `5cc6832`、脏项 **894**（§0）；S687 开窗 17:25:56Z（脏项数只传 Δ 不比大小，S607 口径） |
| 2 | 探针①：板成员 Δ 与逐枚认领形态（§1 表 Δ 列、§0-8 全表之源） | `$PY -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s654-1-roster-delta.py` | S654 ≈15:3xZ→`%TEMP%/s654-work/s654-roster-delta.json`（B01 8→7／B02 26→23／B09 87→86；`refs_over_ceiling` 2 枚；双主 5 枚点名） |
| 3 | 探针②：两腿三态＋注毒两发＋正对照（§4 全表之源） | `$PY -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s654-2-conservation-poison.py` | S654 ≈15:4xZ 与 **S687 17:32:00—17:32:02Z 两窗输出逐字段同值**→`%TEMP%/s654-work/s654-poison.json` |
| 4 | 名册三态与基线今值（§0-4／§1.2 名册行之源） | `$PY -B scripts/shim_retirement_census.py --report` | S654 15:3xZ 复现 47/46/99/93；**S687 17:36:08Z 复跑逐值仍同**，且点名盲区 **4 枚**（audit/contracts/decision/llm 四 `__init__.py`，`no-canonical-derived`，只读附账）与对账 ④=2 |
| 5 | 15 枚（含界外两枚垫片共 17 路）引用边**活性**复算（§0-5 当窗被撕裂读挡死的那口井，S687 补出） | `$PY -B -c "import sys; sys.path.insert(0,'scripts'); import shim_retirement_census as src; idx=src.reference_index(); [print(src.computed_refs(p,idx), p) for p in (<15 枚清单见探针① FIFTEEN> + ['plugins/bot_unified_runtime/mail_bridge.py','plugins/bot_unified_runtime/message_context.py'])]"` | S687 17:36—17:40Z→**15/15 refs＝0**（与册上限逐枚一致，「删除只会减边」的代证自此升为实测）；界外两枚＝**上限贴边饱和**（mail_bridge 2/2、message_context 6/6） |
| 6 | 全 47 枚超上限点名（§1.2 对账 ④） | 同 `-c` 形，遍历 `load_ledger_rows()` 比 `computed_refs>refs` | S687 17:36Z→**2 枚**：`output/card_render/bridge.py` 15>13、`output/plain_text.py` 18>17（他波在飞，本席不代修） |
| 7 | consent.py 语法复核（§0-5 在飞挡件今态） | `$PY -B -c "import ast; ast.parse(open('plugins/bot_unified_runtime/domains/core/safety_exec/consent.py',encoding='utf-8').read())"` | S687 17:33Z→**PARSE-OK**（在飞批已修好该形态；§7 销账） |
| 8 | 五枚行数＋垫片记号（§0-1／§5） | `wc -l plugins/bot_unified_runtime/{mail_bridge.py,mail_adapter.py,sender/__init__.py,sender/onebot.py,message_context.py}` ＋ `head -c 600 … \| grep -q "Compat shim"` 循环 | S687→**3/7/8/12/18**、五枚记号全 YES（与 S646 §2.2／S654 §0 逐值等） |
| 9 | B01 成员 8 枚构成＋五真身归属（§5 核心现算） | `$PY -B -c "import sys; from pathlib import Path; sys.path.insert(0,'scripts'); import physical_placement_census as ppc; claims=ppc.flatten_claims(ppc.feature_impl_paths()); uni=set(ppc.py_universe(Path('.').resolve())); print(sorted({f for fid,p in claims if fid.startswith('B01') for f in uni if f==p or f.startswith(p+'/')})); [print(c, bool([fid for fid,p in claims if c==p or c.startswith(p+'/')])) for c in ['plugins/bot_unified_runtime/domains/transport/mail/mail_adapter.py','plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py','plugins/bot_unified_runtime/domains/transport/sender/__init__.py','plugins/bot_unified_runtime/domains/transport/sender/onebot.py','plugins/bot_unified_runtime/domains/chat_reply/ingest/message_context.py']]"`（后者打印 真身路径 与 是否已被认领） | S687→8 枚＝3 真身＋5 垫片；真身 sender×2 **已被 B08.send-queue 认领**、mail×2 与 message_context 无主 |
| 10 | 认领根与名册行直读（§5 行号列） | `grep -n "mail_bridge\|mail_adapter\|sender/\|message_context" plugins/bot_unified_runtime/domains/core/board_taxonomy.py plugins/bot_unified_runtime/domains/core/board_shim_ledger.py` | S687→taxonomy :89（qq-snowluma：目录根 sender＋字面 message_context）／:117（mail-console：两字面根同 tuple）；册行 refs 2/0/0/0/6 |
| 11 | 哈希册逐枚在册性（§1.2「零在册」行） | `for p in <15 枚>; do grep -cF "$p" tests/verify_hashes.py; done`（求和） | S687→**Σ0**（15 枚逐枚零命中，幂等空操作判定成立） |
| 12 | capabilities 目录活垫片枚举（§1.2 `live_shim_leaves` 行） | `$PY -B -c "import sys; sys.path[:0]=['tests','scripts']; from test_legacy_shim_import_ratchet import live_shim_leaves; print(sorted(live_shim_leaves()))"` | S687→**4**：auto_send/chat/content_parser/market（删 15 后剩 content_parser×1 的算式底） |
| 13 | 两本边账今值（§1.2「被 consent 挡死」行，S687 补出） | 单件跑 `$PY -B -m pytest tests/test_legacy_shim_import_ratchet.py -q -p no:cacheprovider --basetemp="$TEMP/s687-bt-ratchet"`；再 `-c` 调 `collect_legacy_shim_edges()`／`collect_tests_legacy_shim_edges()` | S687 17:33—17:36Z→**10 passed / 102.30s**；生产侧边 **0**／测试侧边 **0**（S250 旁证自此升为本窗实测） |
| 14 | HEAD 侧三声明源取数（腿②的对照组底料） | `git show HEAD:plugins/bot_unified_runtime/domains/core/{board_shim_ledger,board_taxonomy,board_placement}.py`（只读） | 探针②内置（`git_show` 带 decode）；S687 复跑经探针② 覆盖 |
| 15 | 生成物三件（§1.2 后三行；**批落前必在安静窗**——移动靶告示） | `$PY -B scripts/board_doc_sync.py --check`；`$PY -B scripts/command_catalog.py --check`；`$PY -B scripts/doc_sync.py --check` | S654 窗未跑全（§0 移动靶），S687 亦**不在脏窗补跑**——`--check` 的归零验收属批 owner 的安静窗动作，此处只登记命令 |

done: 本节成文——表中「S687 实跑」条目（#3 复跑、#4—#13、以及 #1 开窗）全部为本窗盘上真值；#2/#15 为 S654 窗产物或安静窗待办，逐格已标明谁在何时跑过什么，未把转述记成本窗实跑。判据出处即各行命令本身可复算。
本节由 S687 补完（UTC 2026-09-25T17:25—17:40Z｜判据出处：#2—#14 各行右列的实跑窗标注——S687 窗命令输出见 §6 各行与 §4／§5／§7 回指；S654 窗两笔（#1 开窗 894 项、#2 探针①）转录自 `%TEMP%/s654-work/` 产物与 §0—§1 原账，不混记）。

## §7 卫生账 / 红线自证 / PARKED / 安全登记（规则 11）

### 7.1 卫生账

- 写面纪律：本席全程写面＝**本主件 ＋ `probes/s654-1`／`s654-2` 两枚探针 ＋ `%TEMP%/s654-work/`（仓外）**；
  探针②重跑覆写了同值 JSON（`s654-poison.json`／`taxonomy_HEAD.py` 均为 %TEMP% 仓外件）。
- 直跑卫生：本席全部直跑 python 带 `-B` ＋ `PYTHONDONTWRITEBYTECODE=1` ＋ `PYTHONPYCACHEPREFIX`（仓外）＋ `BOT_AUTOSYNC=0`；
  单件 pytest 带 `-p no:cacheprovider --basetemp=<仓外>`（§6-13）。
- **树内缓存归因（现算，§6-13 后跑）**：本席窗内（本地 01:10 后）树内新增/新触 `__pycache__` 12 个、`.pyc` 26 枚，
  其中 mtime 落在 01:22:46—01:23:07 的 9 枚新写 .pyc（providers／memory_bus_v2／vector_knowledge／search_intent／
  outbound_registry／web_search／participant_memory／host_status／safety_exec `__init__`）**全部早于本席首笔直跑（≈01:28）
  且与本席 import 面（ppc/src/bds 三件套）零交集** ⇒ 树内缓存本席净新增 **0**，那批属并发在飞批的无防护直跑；
  按台账 #50 同款口径登记归因、清理留安静窗（备份 `%TEMP%` 再搬），本席不代清。
- 声明源三件（`board_shim_ledger.py`／`board_taxonomy.py`／`board_placement.py`）盘上呈 `M` ＝ **在飞批所改**
  （§0 移动靶已预告名册重写），本席只读未写——`git status --porcelain` 该三行是接手窗快照，不属本席账。

### 7.2 红线自证（共同纪律 1–2／本席禁面逐项）

| 红线 | 实况 |
|---|---|
| 删任何文件 | **零**——删除只存在于探针内存谓词（§4 注毒形） |
| 改生产件／落码 | **零**——§3 只出可粘贴文本；三门一册一字未动 |
| 改 `.env`／拨闸 | 零 |
| git 写 | 零（只 `git show`／`git status`／`git rev-parse` 只读） |
| 重启／杀进程 | 零 |
| 派新席 | 零（S687 为补完席，未再派） |
| 跑全量套件 | 零——仅 §6-13 单文件棘轮门（102.30s），非全量 |
| %-格式化长段／CJK 串内嵌 ASCII 双引号 | 正文散文遵守；§3 代码块内为可粘贴原文（与探针逐字同源），不受散文条约束 |

### 7.3 PARKED（本席销两条、留三条、新增一条）

- ✅ **销账 CM-S654-a（consent.py 撕裂挡件）**：`domains/core/safety_exec/consent.py:1517` 的真语法错误
  （S654 窗 15:42:54Z 现算、mtime 落在其窗内）已被在飞批修好——S687 17:33Z `ast.parse` **PARSE-OK**（§6-7）。
  正文 §0-5 不改写（当时值如实），指针立此。
- ✅ **销账 CM-S654-b（「引用边 0」活性复算给不出）**：S687 17:36—17:40Z 补出 **15/15 refs＝0**（§6-5），
  两本边账亦实测 **prod 0／tests 0**（§6-13，S250 旁证升格为今值）。⚠ 这是**单快照**——删除授权前的正式复算仍属
  批 owner 安静窗流程（代证已 unnecessary、但授权流程不因此短路），故 §1.2「安静窗复跑」一行**不撤**。
- 🔓 **挂账 CM-S654-c（对账 ④ 两枚超上限）**：`output/card_render/bridge.py` 15>13、`output/plain_text.py` 18>17
  ——两窗（15:4xZ／17:36Z）复现仍在册，他波在飞产物，归该两枚 owner 收敛；批落前域对账门今日即红，与本批零交集（§1.2 原口径维持）。
- 🔓 **挂账 CM-S654-d（盲区 4 枚新附账）**：`--report` S687 窗点名 `audit/`／`contracts/`／`decision/`／`llm/` 四枚
  `__init__.py` 命中垫片记号却因 `no-canonical-derived` 未进待退役桶——只读附账不改桶，不在裁定 15／可删 20 字内，
  登记处置等 E-11 批 owner（删、补 derived 真身、或去记号），本席不动。
- 🔓 **挂账 CM-S687-e（§3 装配壳未过 pytest 实跑）**：§3.2 的具名壳（`_feature_impl_paths_from_text` 等）是
  探针②取数段的断言化改写，**判据函数本体两窗实跑过**（§4），壳形态未独立进 pytest（落地权在批 owner，
  贴入时须自带一发注毒复跑两腿——探针②即现成夹具）。
- ⏳ **移动靶尾注**：本节全部今值取自 UTC 17:25—17:40Z 单窗；名册 47 行／三态 47-46-99-93 在该窗与 S654 窗之间
  **零漂移**（两窗 `--report` 逐值等），但在飞 capabilities 族 26 枚的 D 态尚未 commit，任何跨窗读数照 S607 口径只传 Δ 不比大小。

### 7.4 安全登记（规则 11）

- S687 窗全量接触面（主件／简报／两探针源码／%TEMP% JSON／taxonomy／名册／placement／verify_hashes／census 脚本与
  `--report` 输出／ratchet 门件）**祈使句形态指令文本命中零**；无载荷需消毒入册。
- S654 原件（§0—§2，本席未动）内无命中登记；其窗所见仅 §0-5 的并发撕裂读，属窗噪不属注入，原判定维持。
- 台账 #53 席 C 三次命中系另一窗另一批事件，不并本席账（防转述混账）。

done: 本节成文判据全部为 S687 窗盘上现算，逐条带 §6 回指。
本节由 S687 补完（UTC 2026-09-25T17:25—17:4xZ｜判据出处：卫生归因＝`find -newermt` 窗内 mtime 现算＋模块交集比对（§7.1 正文形）；声明源 M 态＝`git status --porcelain` 只读快照；销账两条＝§6-5／§6-7／§6-13 实跑输出；盲区 4 枚与 ④=2＝§6-4 `--report` 17:36:08Z 现算；红线各条＝本席工具调用史即证据面，无一处写操作可指）。

---

## 席末总注（S687 补完席自证）

- 接手态：§0—§2 与两探针＋%TEMP% 产物在盘，§3—§7 五节的 done 行当时未填（尖括号占位）——与简报「补完非重做」判定吻合。
  **S701 闭合处**：本行旧文本里那枚尖括号占位是全包最后一处——S687 补完五节时把「接手态」写成引语、漏闭本自证节
  自身的 done，属**引语未闭合**、不属正文缺读数；本席按简报「只填这一处」补在下面，§0—§6 与两探针一字未动。
done: 席末总注（本自证节）成文判据＝补前现算三枚自证数——`## §` 二级标题 **8 枚**（§0—§7）／行首 done 标记 **8 枚**（每节恰一枚）／
S687 的补完标记行（行首形）**5 枚** ⇒ 独缺 done 的一节正是无 § 号的本席末总注，尖括号占位今值 **补前 1 → 补后 0**。
本席只补"占位残留几处／done 几枚"这一族**自证计数**，未复算 §1—§6 的任何门值与探针读数（那些数仍归 S654／S687 两窗账）。
本节由 S701 补完（时刻 UTC 2026-09-25T18:05—18:0xZ｜判据出处＝「取数取证三条」，其真身住 `BRIEFS-250925-DD.md` §取数取证三条，
本席简报记作 `-DC.md`，以 DD 为准、差池照实报备）：
① **T1 树身份**＝`os.getcwd()` = `C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`，目标件 `resolve()` 前缀即该仓根
 （非 `WorkBuddy\Worktrees\…`、非 `%TEMP%` 副本）；开窗三件套 `date -u` **18:05:23Z**／`git rev-parse --short HEAD` **`5cc6832`**／
 `git status --porcelain` **961** 项（对 S654 开窗 894 只传 Δ 不比大小，S607 口径）；本件被 `.gitignore:42` 的 `.superpowers/` 罩住
 ⇒ **未跟踪、不在 HEAD**（`git cat-file -e HEAD:<件>` 实测 NOT in HEAD、`git ls-files --error-unmatch` 报 pathspec 不匹配）
 ⇒ 无 HEAD 侧对照，盘面即唯一底账，指纹只能以盘上现算立。
② **T2 指纹三件套（补前原件）**＝sha256[:16] **`cc1eb0cc558ddcea`**（全串 `cc1eb0cc558ddcea709d12aa505bdd5aff6b37b5f363be532472d2f11508747c`）
 ／**48,981 字节**／**370 行**；CRLF **0** 枚（纯 LF ⇒ 行数无换行符歧义）；补前 mtime 本地 2026-09-26 01:55:38 ＝ **17:55:38Z**，
 晚于 S687 自述窗尾（17:4xZ）约 15 分钟 ⇒ 该次写入的归属本席**不下判断**（可能是 S687 收笔后的最后一笔，也可能是并发窗他席碰过），只登记时刻。
③ **T3 双通道互证**＝sha 三读等值（coreutils `sha256sum` = `certutil -hashfile … SHA256` = 项目 venv `python -B -c hashlib`，py 3.12.10）；
 字节四读等值（`wc -c` = `stat -c%s` = venv `read_bytes()` 长 = PowerShell `(Get-Item).Length`，皆 48981）；行数三读等值
 （`wc -l` = venv `splitlines()` = PS `Get-Content .Count`，皆 370）；枚数两型异引擎尺等值（`grep -cF`／`grep -oF|wc -l`／`awk gsub`
 = venv `str.count` = PS5.1 `[regex]::Matches` ⇒ 占位 **1**、S687 补完标记（行首形）**5**、行首 done 标记 **8**（三枚皆补前值）；
 PS 侧另以「S687 标记串前缀」作控制样本同得 5，坐实该独立读者的 UTF-8 强制生效、非异编码假零）。
写面＝本主件本处一处；本节末尾 S687 自述那条 bullet 里「§0—§2 含『待填』『在飞』原话」一语与盘面不符（§0—§2 现算零命中，占位只在席末总注这一节），
属 S687 自述、本席不代改他席文字，留 **S702 勘误席**按 T2 指纹改口。
复跑判据三条（前两枚取**行首锚定形**，第三枚为何不能取行首形见下条警告）：`grep -c '^done: ' <本件>` 补前 8 → 补后 **9**；`grep -c '^本节由 S' <本件>` 补前 5 → 补后 **6**
（多出那枚即本席 S701）；占位残留以 `grep -cF` 配**全串**测＝补后 **0**（本注故意**不复述**那枚串：写出来就自造命中——本席第一版把判据写成
「done 冒号空格＋尖括号通配」的正则形，自检当场得 1≠0，`grep -n` 点名后唯一命中就是那行判据自身，属「判据自己造出命中」同型坑，照实记于此）。
⚠ 同一原因，裸 `grep -c 待填` **不是**判残留的尺（此刻 **3** 枚：本注两处复述＋本节末 S687 自述一处，**全为引语形、非占位**）——
凡复述该二字此数就涨。残留只认**行内全串**形（`grep -cF` 配全串，前提无人复述该串＝本席刻意不复述）；反过来也警告后来者：
**行首锚定的正则尺对本件不成立**——旧占位本来就在**行内**（旧 367 行形如「- 接手态：…五节『占位』——」），拿 `^` 起手的尺去量会得**假零**、把缺口判成已闭。
**「只动这一处」的机检凭据（不是自证，是复原实验）**：把本席新写的整块换回旧行 367 原文（旧 365—366／368—370 六行照抄），
重算整件得 sha256 `cc1eb0cc558ddcea…1508747c`／370 行／48,981 字节——**与补前实算逐位相等**，故 §0—§7 全区（行 1—364，
其 sha256[:16] `614cf77cd3536ab8`）与本节其余各行确证未动；本件未跟踪 ⇒ 无 HEAD 回滚位，此复原式即唯一可复跑的改动面证明
（脚本 `%TEMP%/s701-work/s701-untouched-proof.py`，仓外件、重启即失，复跑者按脚本内注释的旧文本六行重造即可）。
补后整件指纹不写进本文（自指必失效，每追加一次就变），只登记上面那两枚**不随本节追加而变**的数。
- 本席改动面：**只写本主件五节 ＋ §6-9/#5 行的两处内部指针自纠**；§0—§2 正文一字未动（含其中「待填」「在飞」原话，
  其引用之 §6/§7 现已存在，读到即闭合）。
- S654 席位死因未取证（其窗无尸检件可指），只按成品态推定：轮次上限——与 CZ 批多席同型（简报「席位波」纪律所记）。
