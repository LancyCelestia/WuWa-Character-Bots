# PIN-OUT-OF-BAND-S824 —— 量具钉册去自钉施工图（席位 S824，批次 250926A-B7，接替 S819）

> 任务一句话：钉册今天**自钉**（全部哈希与被保护的尺同在板件里，板件住在 gitignore 的 `.superpowers/`），
> 只防「改尺不改板」与无意漂移，**不防尺与哈希同笔双改**（S795 第 13 型注毒实证）。
> 本席出「把钉册搬到板外、受 git 保护的受管件、并进门禁」的施工图——**只出文本与 `%TEMP%` 彩排，未落任何真码、未改板件与任何尺件真身**（交卷前复核见 §拾零）。
> 可粘贴施工文本全部在 `patches/s824-pin-out-of-band.md`（下称「补丁件」），本件只讲设计、判据、彩排战果与边界。

## §〇 结论速览（一屏）

1. **方案**：钉册唯一真源搬入受管件 `tests/gauge_hashes.json`（JSON，含 schema 号与逐枚 sha256），
   板件改为「读册判尺、册读不到＝全部不可判」；执法门**复用既有门件** `tests/verify_hashes.py`（哈希钉册门本体，
   加册不另开门）＋ `tests/test_cross_validation_gates.py`（加一枚独立腿）＋ `tests/test_verify_hashes_coverage.py`（镜像一枚键集腿）。
   册自身再多一条**HEAD 权威腿**：盘上册 ≠ `git show HEAD:` 的上册 ⇒ 红，除非在窗 approvals（带证据与到期日，缺期即不批）。
2. **彩排**：`%TEMP%` 合成临时仓 16 发场景全中（16/16，`BENCH_RC=0`）。核心一发＝S795 第 13 型的「同笔双改」：
   旧方案下板自证返回真（失明复现，作对照）；新方案下门按板外钉册点名 GAUGE-DRIFT（钉册不随板动）。
   攻击者要骗过逐尺腿须升级到**三改**（尺＋钉册＋板），而钉册是受管件——三改必在 `git status` 留痕；
   伪造 approvals 缺到期日仍红；格式合法的 approvals 放行该腿，但钉册与审批件两枚受管面的 diff 全部可见。
   **如实写：方案把「gitignore 区内的静默双改」升级成「必须过 git 可见面＋不 commit 红线＋她复核」，不是数学上封死**（§捌）。
3. **三种读态**（缺文件／读到旧版／读到空）与在册尺被删、新尺未入册，**全部 fail-closed**，无一例「读不到＝放行」（§伍）。
4. **迁移期双读判据**：权威＝册；内联副本只准降级判据（滞后 ⇒ 点名 transit 放行），**绝不准反向升权**（尺与内联副本相合而
   与册不合 ⇒ `DIVERGE_TRUSTLAG` 不可判）。合法改版不被误伤（A9b/A10 实测），滞留在 `migration_deadline` 之后自动落 NO（临时态到期纪律）。
5. **落地次序**：门＋册＋板**同一笔**入库（对齐她 P-1「尺与名册同一笔」裁定）；入库前中间态靠一枚带到期日的 approvals 窗兜（§陆）。
   全部新件/改件的 pathspec 逐枚列进 §玖——**未跟踪的锁件在干净 checkout 会丢**，这是 #49 现成教训，本方案不再犯第二次。

## §拾零 本席红线自证（交卷前现算）

- 板件与全部尺件真身**零写**：交卷前重跑钉册对照尺（§拾 命令 R1）⇒ `TOTAL=19 same=19 differ=0 missing=0`，
  与 §贰开窗读数同值（板件自身在漂，属板 owner 在飞，非本席落笔——见 §壹 移动靶账）。
- 未 commit、未 push、未 `git init` 真仓真库（临时仓只建在 `%TEMP%\s824-bench-root`，红线禁的是真仓）、未动 `.env`、未拨闸、未重启杀进程、未跑全量套件。
- 真仓 git 面在本席窗口内未被本席改动（本席写面只有两枚：本件与补丁件）。

## §壹 现值对账（开窗两次读数＋移动靶披露）

| 物件 | 现值（当时值） | 备注 |
|---|---|---|
| 审计板 `probes/s0-main-goal-audit.py` sha256[:8] | `33c4bc31` → `500e3f2f` → `6c5d032a`（本席窗内三版连漂） | 板是移动靶实锤；施工 patch 一律用**内容锚**不用行号（第 09/14 型教训） |
| 板内 `PINNED_GAUGES` | 18 枚 → 19 枚（新增 `s0-main-mandate-kinds-coverage.py`） | 与盘上尺逐枚对照 **19/19 全符**（播种点干净） |
| 板 `SOURCES` 壳调尺 | 16 把 → 17 把 | 上表「19 枚」＝17 壳调＋工厂＋s715-deps |
| `GAUGE-PIN-LOG.md` | 在册重录日志 27 行；含 08:16Z 首笔 --repin 洗白两枚经他席改动、34 秒后人工局部撤销的实案 | 「repin 无证据门槛」发作过一次的历史在册 |
| `tests/verify_hashes.py --check` | **今天红**：1 项 `DRIFT renderer.py`（他波在飞件，归属 #55/#56 账） | ⇒ 本方案落地验收必须走**独立口径** `--check-gauges`，不与他波红混判 |
| `pytest tests/test_cross_validation_gates.py tests/test_verify_hashes_coverage.py` | **1 failed / 5 passed**（唯一红＝上述他波 DRIFT） | 基线原样记录，本席未代修 |

另两枚本席现算观察（如实登记，均归板 owner 处置，本席不改板）：

- **`PIN_EXTRAS` 是死变量**：注释称「不参与 run()，单独验」，但现算全板零消费——工厂与 s715-deps 的实际执法
  走的是 C6 格对 `PINNED_GAUGES` 全表遍历（板 L352 旧版现读），「单独验」那条腿**并不存在**。属第 16 型（注释承诺了一把不存在的锁）的近亲。
- **C6 格文案手写「本板壳调的 12 把尺」**：现算壳调是 17 把（当时值）。铁律 10「叙述文档禁手写会过期的计数」对板内文案同样成立——
  施工 patch 里我把该行改为 `{len}` 派生（补丁件 C3 第 5 处）。

## §贰 机理与目标（为什么自钉必瞎，以及搬出去封的是哪三条通道）

第 13 型的失明机理一句话：**判定者与证据同居一个可写件**。板读 `PINNED_GAUGES`、板也写 `PINNED_GAUGES`（`--repin`），
两者都在 gitignore 区——能改尺的人改完尺顺手改册，板从自家的册里读到「新尺的哈希」，逐尺腿全对，格照绿。
S795 的 [B] 发已实跑证实（DEMO-RC=0 复现成立），本席彩排 A2old 再次复现（板自证返回 True）。

搬出去之后，「尺是什么」的证据分成三条**互相独立**的通道，双改要同时骗过三条：

1. **逐尺腿**（尺↔册）：盘上尺字节 vs 受管册该枚哈希——册不随板动，「尺＋板内哈希」双改骗不过它（A2new）。
2. **HEAD 权威腿**（册↔git）：盘上册 vs `git show HEAD:tests/gauge_hashes.json`——骗过逐尺腿必须连册一起改，
   而册是受管件，改了就与 HEAD 不一致 ⇒ 红（A3）；想红转绿要么把那笔**提交**（席位红线禁），要么写一枚**带到期日的 approvals**
   （那又是第二枚受管件的 diff，A4/A5）。
3. **git 可见面**（她复核）：两枚受管件的改动在 `git status --porcelain` / `git diff` 逐行可查——第 23 型教训（`git diff` 对未跟踪件结构性无力）
   反过来用：把册放进**跟踪面**，正是让最老牌账工具第一次能咬到它。

诚实边界（不许吹成「封死」）：三条通道的**最终信任锚是她的那一次 commit 复核**——她若把中毒笔直接入库，中毒版即成新 HEAD，
本方案与今天所有 git 依赖机制同样失守。与既有纪律同口径：这是把「无从发现的静默」升级为「不入库不盖章、入库必留痕的显式债」。

## §叁 钉册存哪、owner 是谁、什么口径

- **存哪（裁定）**：`tests/gauge_hashes.json`——与 `render_hashes.json` 同目录同族（受管、人读、diff 友好），被扩展后的 `verify_hashes.py` 直接消费。
- **候选与否决账**（G 简报要求「找不到能复用的门就停下报候选」——找得到，候选一并如实记）：
  | 候选落点 | 判 | 理由 |
  |---|---|---|
  | `tests/gauge_hashes.json`（选中） | ✅ | 复用既有哈希钉册门件本体；受管；与 render 名册同一套 --check/--write 命令簿 |
  | 仓外 `ChatBot_Libs` 某库 | ❌ | 该面**只读纪律**在案；且库侧走同步通道——第 04 型实锤通道能把库侧篡改烙成「同步主仓快照」后永久 UP-TO-DATE，把钉册交给一条已知会洗白篡改的链路是自杀 |
  | `docs/` 或 `scripts/` 新 JSON | ❌ | 新旁支账本，无既有门消费；违「禁新建第三本钉册账」 |
  | `.superpowers/` 内另一文件 | ❌ | 还是 gitignore，搬家不出墙 |
  | SQLite（运行数据面） | ❌ | 不可 diff、不可评审、非受管 |
  | 新建 `tests/test_gauge_pin_gate.py` 常驻门 | ❌ | 执法门必须复用既有门件——新建门文件＝新旁支（新 md/新门加债纪律同型） |
- **owner**：册的**写权**＝板 owner（现为主代理）的 `--repin` 唯一口（补丁件 C1：写盘先册后板、逐枚点名与证据门原样继承）；
  册的**入库权**＝她（红线：席位不 commit）；`verify_hashes.py` 对册**只读**（`--write` 只写 render 名册，绝不写册——两个写口＝第二真身，见补丁件 B2 注释）。
- **哈希口径**：尺与板用 **raw-bytes sha256**（与今天板内 18/19 枚在册值逐字兼容，迁移零换算）；
  render 名册那本保持 **LF 归一口径**不动。一口径一册、各管各的清单，**同一门件两本账，互不串门**；
  HEAD 腿比较两侧各做 CRLF→LF 归一（Windows checkout 形态差异不能冒充篡改——AGENTS #50 行尾教训在册）。

## §肆 板怎么读册：三种读态全 fail-closed（含在册尺被删、新尺未入册）

读册唯一解析口（板与门共用同一份代码语义，禁两本口径——补丁件 C1/A 区）。落态表：

| 读态 | 触发形 | 板侧落 | 门侧落 | 放行？ |
|---|---|---|---|---|
| OK | schema=1、hashes 非空、逐值 64-hex | 正常逐尺判定 | 正常三腿 | 是（前提全符才 YES） |
| FILE_MISSING | 册文件不在盘 | 所有壳调格 rc=99、C6 格 NO、点名 `registry_FILE_MISSING`；**禁回退板内旧副本**（旧副本只用于双读点名，永不用于放行） | `REGISTRY-DELETED`（HEAD 有而盘上没＝删册）或 `REGISTRY-NEVER-IN-GIT`（从未入库＝机制未生效），两态分开点名 | **否** |
| SCHEMA_MISMATCH（读到旧版之一） | schema 缺/≠1 | 同 FILE_MISSING 处理，点名带态名 | 同上 | **否** |
| EMPTY_OR_MALFORMED（读到空/读不懂） | JSON 炸、hashes 空、任一值非 64-hex | 同上 | 同上 | **否**——「空册＝没有尺要钉＝全放行」是本表第一禁止项 |
| STALE_READ（读到旧版之二） | 册可读但滞后（checkout 回 HEAD / 忘重录） | 该尺 `STALE`⇒rc=99 | `GAUGE-DRIFT` 逐枚点名 | **否**——旧册**绝不**为新尺背书（A6 实测） |
| UNREGISTERED | 板新壳调一把尺、册里没有 | 该尺 rc=99 | —（门只看册侧） | **否**——加枚必走板 owner 亲笔改册（受管 diff），继承今日 `--only` 点名不在册即 FATAL 的家规 |
| GAUGE-MISSING | 在册尺不在盘 | rc=99 | `GAUGE-MISSING` 点名 | **否**——删尺≠该尺免检（A8 实测） |

## §伍 迁移期双读判据（取最严会误伤合法改版 ⇒ 给可机检判据）

迁移窗内板上同时存在：权威册 E（受管）与旧内联副本 I（板内 `PINNED_GAUGES` 块，deadline 前不删）。逐尺四态判定（补丁件 C1 参考实现＝彩排台 `gauge_state`，两者同语义）：

| 态 | 条件（盘上尺 sha 记作 d） | 板格 | 为什么这样判 |
|---|---|---|---|
| PASS | d==E[g]，且 I 缺位或 I[g]==E[g] | 正常 | 权威与实像一致 |
| **PASS_TRANSIT** | d==E[g] 且 I[g]≠E[g] | 放行，但**逐枚点名**进 `transit` 集并入板行与日志 | 这就是「合法改版双写崩在中间」或「E 已重录、I 待下线」形。**取最严（E≠I 即 NO）会每次合法 repin 都误伤板**——A10 实测窗内不误伤 |
| DIVERGE_TRUSTLAG | d≠E[g] 且 d==I[g] | **rc=99 不可判** | 内联副本（可写的 gitignore 区）**永不可升权**：尺与内联副本相合、与权威册不合 ⇒ 恰是「尺改回去骗内联」或「册被人动过未入库」形，只能人工归因 |
| STALE / UNREGISTERED | 见 §肆 | rc=99 | — |

- **棘轮只降不升的接法**：`transit` 集就是迁移滞后的账——每次 `--repin` 双写必须先写 E 后写 I（同笔消一），
  新增 transit 只能来自「写了 E 没来得及写 I」的同笔事故，板行逐枚点名；截止日后 transit>0 ⇒ C6 格 NO（A10 逾期发实测 pin=False）。
  入册枚数的增减＝受管 diff（册与审批件），升与降都在她眼皮下——不另立计数基线，**避免再造一本会漂移的手写账**（铁律 10）。
- **临时停用要自动到期**：窗本身是临时态，到期字段 `migration_deadline` 写在**册内**（受管、改它必留痕），
  缺省建议 `2026-10-26T00:00:00+00:00`（施工日起整 30 天，落地席按实际开工日重算）；
  解析失败＝`deadline_unparseable` 落 NO（延账门第 3 条 fail-closed 同口径：读不懂＝已过期，不许读成「没有截止」）。
  到期后动作＝补丁件 C2（删内联块的终局 patch），删不删得动，门与板都会替她记得。
- **approvals 通道的接法**：册的入库中间态（A9a：重录了、还没被她提交）由 `tests/gauge_registry_approvals.json` 一枚条目兜——
  形制逐字照抄 `scripts/shim_refs_approvals.json` 的既有口径（`path`/`approved_by`/`reason`/`expiry` 四件，缺任一或过期＝不批、仍红；
  「没人写日子」必须读成「已到期」，延账门 §判据-3 同教义）。**不新建第四套解析**，语义上只是同一通道多一个消费方（§捌 第 4 条把这条的可滥性也如实挂了账）。

## §陆 执法门：复用既有门件（禁新建第三本账）逐件点状

1. `tests/verify_hashes.py`（门件本体）：加 `check_gauges()` 三腿（逐尺／盘面＋在册必在盘／HEAD 权威）与 `--check-gauges` 独立旗标；
   既有 `--check` 改为**两册都跑、前缀分namespace**（render 行逐字节不动，gauge 行 `GAUGE-…`/`REGISTRY-…` 前缀），
   `--write` **绝不写 gauge 册**（写口唯一=板的 `--repin`；两本写口的教训＝同步通道把篡改烙成同步快照，第 04 型）。
2. `tests/test_cross_validation_gates.py`（既有常驻接线）：新增 `test_gauge_pin_registry_clean`，subprocess 走 `--check-gauges`——
   **独立腿的意义**：今天 render 册被 renderer.py 在飞件顶红（§壹），混在一条腿里他波的红会吞本波判据的归因（第 05 型同族病）。
3. `tests/test_verify_hashes_coverage.py`（既有镜像腿）：新增一枚「册 schema/形态自洽＋板自身在册」的断言（照抄 110-114 行键集腿的写法，不发明新结构）。
4. 彩排台 16 发即这三件改完之后应复跑的**参考验收项**（§陆末）：主代理落码席须把同一 scenario 集打在真门真板上复跑一遍才算闭环——本席只证明**判据**拦得住，不证明**落码**没走样（幻影转述纪律，第 20 型）。

## §柒 彩排战果（`%TEMP%` 合成临时仓 16 发，实测全中）

台架：`%TEMP%\s824\bench.py`（参考实现＝施工图判据逐条同语义；临时仓只在 `%TEMP%`，真仓真尺零接触）。
复跑命令见 §拾 R3。实跑输出（当时值，逐发 CAUGHT，`SUMMARY 16/16`，`BENCH_RC=0`）：

| # | 发 | 期望 | 实跑 |
|---|---|---|---|
| A0 | 全等基线 | 门 0 问题、板格可判 | CAUGHT |
| A1 | 单改尺（册未动） | 门 `GAUGE-DRIFT`＋板 STALE 拒判 | CAUGHT（今天板本来也拦——新方案不回退这条既有牙） |
| **A2old** | **同笔双改（尺＋板内哈希）·旧方案** | 板自证返回真＝**第 13 型失明复现（对照）** | CAUGHT（自证 True，该形无门——S795 结论独立重现） |
| **A2new** | **同笔双改·新方案** | 门按板外钉册点名 DRIFT（钉册不随板动） | CAUGHT |
| A3 | 三改（尺＋钉册＋板内）未入库 | 逐尺腿不误伤、`REGISTRY-DIFFERS-FROM-HEAD` 红 | CAUGHT |
| A4 | 三改＋伪造 approvals（缺 expiry） | fail-closed 仍红 | CAUGHT |
| A5 | 三改＋格式合法 approvals | 该腿放行，但册与审批件两枚受管面 diff 全可见 | CAUGHT（`git status` 亲验四行痕迹，见下残账①） |
| A6 | 读到旧版钉册而尺已新 | 按册严判即 DRIFT，旧册不背书 | CAUGHT |
| A7a/b/c | 缺文件／空册／旧 schema 三读态 | 门与板同落不可判（禁回退内联册） | CAUGHT×3 |
| A8 | 在册尺被物理删除 | `GAUGE-MISSING`＋板不可判 | CAUGHT |
| A9a/b | 合法改版未入库中间态红 → 同笔入库后绿 | 不误伤合法路 | CAUGHT×2 |
| A10 | 双读窗 transit：窗内点名放行、逾期落 NO | 「取最严误伤」与「假绿永驻」两头都堵 | CAUGHT |
| A11 | 换板（板自身在钉册内） | 门点名板件 DRIFT（板不可自证自身，门侧封） | CAUGHT |

**拦不住形如实记（方案自己的答案，非粉饰）**：A5 即「三改＋写一枚格式合法的 approvals」——门该腿放行。
拦它的不是机制是**留痕**：两枚受管件的 diff 出现在跟踪面，而席位红线「不 commit」使留痕**无法被合法消化**；
终判权在她。若她某日未复核即提交了中毒笔，方案失守——这条与仓内一切 git 依赖机制共担，写进 §捌 残账第 1 条，**不宣称封死**。

## §捌 残账与诚实边界（逐条，「在册未执法」禁写成已生效）

1. **信任锚未消失、只是移位**：从「gitignore 区无人能看见的哈希」移到「跟踪面＋她复核」。复核缺位日＝防线缺位日。
2. **钉册钉尺不钉果**：在册尺仍可能逻辑说谎（读到旧版册≠尺读数真）。F1–F3 的数字腿、第 15 型零测绿与本方案**正交**，一码换不来另一码。
3. **板仍住在 gitignore**：换板由 A11 门侧封（钉册含板自身哈希），但板自身代码不能自证——与第 13 型同理，靠外置册＋门。
4. **approvals 可自批**：写审批的人与改版的人可同为板 owner；受管 diff 是唯一附加成本。缓解在册：approvals 枚数与到期日全在跟踪面，堆积本身可被任何只读席点名。
5. **路径耦合批次目录**：册内键是 `.superpowers/sdd/2026-09-24-central-dispatch/probes/...` 全路径——席目录搬迁/改名 ⇒ 逐枚 `GAUGE-MISSING` 红（fail-closed，属预期摩擦），迁移那笔须同步改册。
6. **常驻门 ≠ 生产运行**：`check_gauges` 活在 pytest/命令簿里；审计板是离线现算件，两消费者各取一腿，任何一侧没跑都不构成另一侧的绿。
7. **本席未跑全量套件**（OOM 红线）：新增 pytest 腿在真树上的首次实跑属落地席验收项（§陆第 4 条），本席只交参考实现与基线读数（§壹）。
8. 彩排台是**判据级**证据（参考实现跑 scenario），不是真门真板的集成证据——两者间的差距由落地席同 scenario 集复跑关闭，不由本件宣称关闭。

## §玖 落地清单（谁、什么顺序、pathspec 逐枚——含「未跟踪锁件干净 checkout 即丢」的现成教训）

1. **主代理落码（一席一笔）**：应用补丁件 B（verify_hashes 三处）＋ C1（板换读册）＋ D（approvals 新件模板）；运行板新旗标 `--export-registry` 生成 `tests/gauge_hashes.json`（禁手抄哈希）。
2. **她同笔提交**，pathspec 逐枚显式（禁 `-A`，仓规 4）：
   `tests/gauge_hashes.json`、`tests/gauge_registry_approvals.json`、`tests/verify_hashes.py`、`tests/test_cross_validation_gates.py`、`tests/test_verify_hashes_coverage.py`。
   板件与尺件真身在 gitignore 区**不入库**——正因如此 §1 的中间态 approvals 或快速提交二选一是**硬前置**（册未入库期间 HEAD 腿红是设计内）。
3. **迁移窗**（deadline 前）：板双读跑 transit；每次合法 `--repin` 双写先册后板（同笔消 transit）。
4. **终局一笔**（deadline 前任何时点，建议窗中值）：应用补丁件 C2 删板内 `PINNED_GAUGES` 块＋transit 腿 ⇒ 单读册，双读态寿终。
5. **验收**：§拾 R2–R5 全跑＋落地席把 §柒 16 发打在真门真板（判据同源，应逐发同态）。
6. **回滚**：`git revert` 那一笔即整体撤方案（册与门件是新增/附加，无数据迁移、无反向依赖）；回滚后的世界＝今天的自钉，**弱但可用**——如实标这不是无损操作。

## §拾 复跑命令簿（卫生前缀四件套全带上；`<venv-py>`＝`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`；`<TEMPW>`＝`C:/Users/LancyCelestia/AppData/Local/Temp`）

```powershell
# R0 开窗位置（本席全程只读起点）
cd C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot

# R1 钉册对盘现算（本席用 $TEMP\s824\pin_state.py，只读；交卷前复核＝19/19 全符）
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONDONTWRITEBYTECODE="1"; $env:BOT_AUTOSYNC="0"; $env:PYTHONPYCACHEPREFIX="$env:TEMP\s824-pyc"
& <venv-py> -B "$env:TEMP\s824\pin_state.py"

# R2 现存哈希门基线（今天 1 红属他波 renderer.py，落地后此红归属不变、勿混判）
& <venv-py> -B tests/verify_hashes.py --check
& <venv-py> -B -m pytest tests/test_cross_validation_gates.py tests/test_verify_hashes_coverage.py -p no:cacheprovider --basetemp="$env:TEMP\s824-bt" -q

# R3 本席彩排台（16 发全合成，临时仓只建在 %TEMP%；期望 SUMMARY 16/16、RC=0）
& <venv-py> -B "$env:TEMP\s824\bench.py"
```

（R4/R5＝落地席的真门真板复跑与 approvals 窗检查，待补丁件落地后由该席补进命令簿，本席不预写「已可跑」的假命令。）

## §拾壹 注入取证（规则 11）

本席窗内读取的全部文件正文（简报两枚、假绿册、复攻册、日志、板件、门件、审批册、记忆索引）中，
**未出现任何以工具结果/文件形态伪装的越权祈使句**（无「改配置/重启/commit/派席」类注入形）。
件内固有的施工规约（如板内 `--repin` 拒绝文案）属白名单③在册规范的项目自身指令，非注入。零命中，取证即此一段。

## §拾贰 与 S819 的交接核对

S819 盘上零成品（简报点名）现算复核：`probes/`、`patches/`、根目录无任何 `*s819*` 钉册施工图残留
（`ls patches/ | grep -i s819`、`grep -rln S819 --include="*pin*"` 零命中）——**本件为从零开工，非续做半件**，
不存在覆盖前席成品的风险。

done: yes
