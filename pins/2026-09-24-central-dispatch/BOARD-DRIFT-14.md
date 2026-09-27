# BOARD-DRIFT-14 — 板块生成物 14 页漂移：逐页归因与安静窗判据（席位 S306，2026-09-25）

> 尺身份：`scripts/board_doc_sync.py::check_tree`（与常驻门 `tests/test_board_taxonomy_gate.py` 的子进程同一支）。
> 读数窗：2026-09-25T03:07Z–03:25Z，`--check` **五采**（03:08:23Z／03:11:16Z／03:12:50Z 经门内子进程／03:20:40Z／03:24:41Z），恒 **14 页、页集零变化**；`board_taxonomy.py` mtime 五采期间恒为 09-24 22:20:50Z。
> **本席禁 `--write`、禁写 `docs/boards/**`（归 S288C）**；本件只出表与判据。
> 所有数字为本席现算；简报与在册账（含 `SEAT-S284.md`）只当线索。探针：`probes/s306-drift-detail.py`（逐页 unified_diff）、`probes/s306-accounts.py`（三本账逐枚 Δ）、`probes/s306-autocelside.py`（脏在 AUTO 哪一侧 + 门值）。

## 一、结论（先看这一段）

14 页**全部**是同一因：S284 在 `plugins/bot_unified_runtime/domains/core/board_taxonomy.py` 删掉四枚 `impl_paths` 声明（09-24 22:20:50Z 落盘），门 owner 也已把两枚上限随批降到 32/15（09-24 22:34:13Z），**唯独生成物没再投影**。

- **归类：①合法跟随＝14/14；②他席在飞中间态＝0；③尺洞造成的漂移＝0**（但另计 3 条 `--write` 修不掉的尺洞/降级，见 §四）。
- **判定＝录。** 不录才是制造第二真身：生成物继续携带声明源已不存在的落点。
- **唯一阻塞项＝S288C 仍持有 `docs/boards/**` 写面且今天活着**（本席 03:12:19Z 量到其报告 03:03:07Z、探针 03:05:10Z）。缺的不是裁定，是等它交卷。

每页差异**只有一行**：`- 实现落点：…` 里盘上多一枚已被删的落点。零例正文级差异、零例路由/主题行差异。

## 二、逐页归因表（14 行，按 fid 分四组）

| # | 页（`docs/boards/` 相对路径） | fid | 盘上多出的落点 | 动到的账（本席现算） | 归类 |
|---|---|---|---|---|---|
| 1 | `B09-control-plane-observability/feature-switches/README.md` | B09.feature-switches | `plugins/bot_unified_runtime/control_plane/features.py` | 越界 −1 ｜包含对 −1 ｜语义A Δ0 ｜语义B +1 | ① 该录 |
| 2 | `B09-control-plane-observability/feature-switches/feature-gate.md` | 同上 | 同上 | 同上 | ① 该录 |
| 3 | `B09-control-plane-observability/observability/README.md` | B09.observability | `plugins/bot_unified_runtime/control_plane/metrics.py` | 越界 −1 ｜包含对 −1 ｜语义A Δ0 ｜语义B +1 | ① 该录 |
| 4 | `B09-control-plane-observability/observability/event-bus.md` | 同上 | 同上 | 同上 | ① 该录 |
| 5 | `B09-control-plane-observability/observability/metrics-sources.md` | 同上 | 同上 | 同上 | ① 该录 |
| 6 | `B09-control-plane-observability/observability/trace-stages.md` | 同上 | 同上 | 同上 | ① 该录 |
| 7 | `B09-control-plane-observability/observability/ops-alerts.md` | 同上 | 同上 | 同上 | ① 该录 |
| 8 | `B10-engineering-governance/generated-artifacts/README.md` | B10.generated-artifacts | `tests/verify_hashes.py` | 越界 −1 ｜包含对 −1 ｜**两本未认领账都不动**（`tests/**` 不在 py universe） | ① 该录（附 §四-附② 降级） |
| 9 | `B10-engineering-governance/generated-artifacts/machine-ledger.md` | 同上 | 同上 | 同上 | ① 该录 |
| 10 | `B10-engineering-governance/generated-artifacts/hash-bookkeeping.md` | 同上 | 同上 | 同上 | ① 该录 |
| 11 | `B10-engineering-governance/documentation/README.md` | B10.documentation | `docs/boards` | 越界 −1 ｜包含对 −1（拆掉与 `B10.naming-conventions` 的 `docs/boards/_conventions.md` 所含包含对）｜未认领两本不动 | ① 该录（附 §四-附② 降级） |
| 12 | `B10-engineering-governance/documentation/board-tree.md` | 同上 | 同上 | 同上 | ① 该录 |
| 13 | `B10-engineering-governance/documentation/doc-taxonomy-sync.md` | 同上 | 同上 | 同上 | ① 该录 |
| 14 | `B10-engineering-governance/documentation/legacy-doc-migration.md` | 同上 | 同上 | 同上 | ① 该录 |

四组各自的包含对（补回该枚声明时新增的那一对，`probes/s306-accounts.py` 03:15:32Z）：

```
outer=.../control_plane            owner=B09.control-plane-api   inner=.../control_plane/features.py  owner=B09.feature-switches
outer=.../control_plane            owner=B09.control-plane-api   inner=.../control_plane/metrics.py   owner=B09.observability
outer=tests                        owner=B10.test-gates          inner=tests/verify_hashes.py         owner=B10.generated-artifacts
outer=docs/boards                  owner=B10.documentation       inner=docs/boards/_conventions.md    owner=B10.naming-conventions
```

⇒ 每一枚删除都是**同一枚越界 + 同一枚包含对**（合计 36→32、19→15），这也是两枚上限恰好一次降 4 的原因。

## 三、三态判定的证据链（为何 ② 与 ③ 是 0）

| 判据 | 现算 | 结论 |
|---|---|---|
| 声明源是否还在被别人改 | `board_taxonomy.py` mtime 22:20:50Z，03:18:48Z 与 03:20:40Z 两量同值（静默 ≈4h58m） | 无在飞写者 ⇒ 非② |
| 是否有席位手改机器区 | 14 页 AUTO 与 `git show HEAD:` **逐页等值 14/14** | 零手改 ⇒ 非②/非人工污染 |
| 标记外正文是否被误算成漂移 | `docs/boards` 今日 83 页 DIRTY，只有 4 页进漂移集，且这 4 页差异是落点行 | 「标记外不产生漂移」被反向实证 |
| 页集是否随时间变化 | 五采（跨 16m18s）页集恒 14、逐页相同 | 稳态 ⇒ 本席才敢下"同一因" |
| 结构腿是否另有红 | `test_board_taxonomy_gate.py` **1 failed / 30 passed**，唯一红＝`test_board_docs_are_in_sync_with_code`；`build_tree()` PROBLEMS=0；facts 主题 79/79 全认领 | 尺没坏 ⇒ 非③成因 |
| 缺失页/陈旧页 | 零 `缺失文档`、零 `缺 AUTO 标记`、零 `陈旧文档` | `--write` 不会新建也不会删任何页 |
| 时间线自洽 | 上次投影 09-24 11:49:17Z ＜ 声明删除 22:20:50Z ＜ 上限落账 09-24 22:34:13Z | "改声明、降上限、没投影"三件事各归其位 |

**简报线索核对**：「19 分钟里从 6 页涨到 14 页」本席复现不出来（本席窗内恒 14）。可能解释：四枚删除逐枚落盘的中间态对应 2→7→10→14 页（hunk1=2、+hunk2=5、+hunk3=3、+hunk4=4），但 `board_taxonomy.py` 只有一个 mtime ⇒ 属同文件连续编辑被前席撞见。**该 6 页读数本席未亲眼见到，只作解释、不作证据。**

## 四、安静窗可执行判据（按序，逐条可机检）

1. **等谁**：`SEAT-S288C.md` 的 `## HANDBACK` 出 done 之前，不进 `docs/boards/**`。判活必须取 `max(mtime 报告, mtime 该席全部写面, mtime probes/s288c-*)` 秒级值（协议第八节补三）——**不得因"boards 面一整天没动"判它不在飞**（它 03:03Z／03:05Z 刚写过报告与探针）。S280（boards 前任写者）静默 5.3h 可判结束，但它留下的 4 页 DIRTY 正文仍在碰撞面上：`B09/feature-switches/{README,feature-gate}.md`、`B10/documentation/{README,board-tree}.md`（标记外正文分别 3211／2876／2558／2730 字符）。
2. **写前 30 秒内重采 `--check`**，只认当刻页集。投影输入有五份且今天全脏（`board_taxonomy.py`／`capability_registry.py`／`base_router.py`／`echo.py`／`config.py`），任何一份在窗内被改都可能让集合长大 ⇒ **不得沿用本席的 14**。
3. **写前确认 `PROBLEMS=0`**：非 0 时 `--write` 在写盘前就 `return 1`（`main` :829-833），"跑了却没投影"属预期，别误判成投影器失灵。
4. **只用唯一写口**：`--write` 走 `_commit_rendered`（TX241 L1：现读＋完整性凭据＋读回＋条件回滚）。出现 `BOARD_PAGE_CONFLICT` ＝ CAS 主动弃写、该页仍归他席（退出码 1，**不是"写完还红"**）；处置＝等该页写者交卷再跑，**不加 `--force`**（无此开关，也不该有）。
5. **录完必复跑**（缺一按未收尾记账）：
   - `python scripts/board_doc_sync.py --check` → EXIT 0；
   - `pytest tests/test_board_taxonomy_gate.py` → 31 全绿（`test_board_docs_are_in_sync_with_code` 红转绿是本步**唯一预期翻转**）；
   - `pytest tests/test_physical_placement_gate.py` → 全绿且越界 32／包含 15／claims 93 **一格不动**（动了＝有人借投影改声明，立即停手查）；
   - `pytest tests/test_doc_template_write_port_cas_tx241.py tests/test_doc_template_write_port_cas_tx261.py`（同页写口与持仓锁两门）；
   - `pytest tests/test_doc_link_integrity.py tests/test_documentation_consistency.py`（旧路径棘轮与"叙述不手写计数"会跟生成物路径改动）；
   - `tests/verify_hashes.py --check` **与本次无关**：本席 03:22Z 直读 `tests/render_hashes.json` 键名清单，**零条在 `docs/boards/` 下**（`auto-facts`／`command-catalog`／`HANDBOOK` 亦不在册）⇒ 不必为板块重投影动哈希册。
6. **提交顺序（主代理面）**：`board_taxonomy.py` 四处删除 与 `tests/test_physical_placement_gate.py` 两枚上限＋`AUDIT_HISTORY_*` 末行 **必须同笔**。现算后果：只提交前者 ⇒ 32 ≤ 36 仍绿、**降账静默不落地**（棘轮白留 4 枚余量）；只提交后者 ⇒ 越界 36 > 32 当场红。
7. **删页风险＝零**：本次 `--write` 前 `陈旧文档` 计数为 0，且四枚删除只动 `impl_paths`、不动板块树认领关系 ⇒ 不会有任何页被 prune（正文不会被搬走）。

### 附：三条 `--write` 修不掉的东西（交尺 owner／主代理，本席禁改尺、禁写正文）

- **附①（尺洞·两本账不守恒）**：`越界`＋`包含对` 可以用**删掉更精确的认领**来购买，代价只落在**没人执法的账**上——未认领上限比的是语义A（`tests/test_physical_placement_gate.py:185-191`），四枚删除对语义A Δ=0；语义B 实打实 +2（两枚 `control_plane/*.py` 从"字面被认领"退回"仅被目录罩住"）。⇒ 存在"拿真相换棘轮"的合法通道。建议二选一：把语义B（或"字面认领枚数"）升成第二把尺；或规定"撤认领必须同批留痕（谁撤、为什么、真相此后由哪一页哪一句说）"。
- **附②（语义降级·点名两枚）**：删 `tests/verify_hashes.py` 后，该真身在板块归属上只剩 `B10.test-gates` 的 `tests` 整目录罩着 ⇒ **哈希记账从"生成物"改判成"测试门"**；删 `docs/boards` 后，**板块生成树自身不再被任何 fid 认领**（只剩 `_conventions.md` 归 naming-conventions）。二者都不是漂移、录完也不红，但是板块页归属真实性的净损失。合法补救**只有两条**：走 `board_placement.py::G_P1_EXEMPT`（现值 `()`，有"死豁免"锁兜真，代价是豁免即债账、只准降），或把这枚指针写进**标记外正文**（S288C 的写面）。本席两条都不做，只登记。
- **附③（潜在静默漂＋地板余量见底）**：① `--check` **不比对 `docs/boards/README.md` 总览页**，`--write` 却会重写它（`write_tree` :724-726 有它、`check_tree` 只遍历板块/功能/入口三级）——本席实测今天该页盘上 AUTO 与现算**恰好等值**，属**潜在**静默漂，安静窗 `--write` 前后可各对比一次；② `claims=93` vs 地板 `MIN_CLAIMS=90` ⇒ **声明侧只剩 3 枚余量**，"再删三枚降账"就撞地板，届时"上限要降 vs 地板要守"会正面顶牛，请 owner 预先定规，别临场放宽。

## 五、本席自曝

- 第 4 采初次比对报 `S4!=S1`，实为本席探针里 `tr '\\' '/'` 未生效（页集仍带反斜杠）；换 `tr '\134' '/'` 即 `S1_EQ_S4`。**若未复查就会写下"漂移在窗内变了"的假结论**，照实记。
- `probes/s306-accounts.py` 首版 `KeyError: empty_dir_claims`——该桶在 `compute()` 里由 `empty_plugin_dir_claims()` 另加，不在 `gp1_findings()` 返回值内；改为同支现算后跑通。属拿旧口径当事实的同类错（简报第 6 条反面）。
