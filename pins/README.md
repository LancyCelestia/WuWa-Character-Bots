# pins/ —— 完成审计板钉册存放地（受追踪真身）

> 本 README 由席位 S-PINS-README-DRAFT 于 2026-09-27 起草，是**新建文件、不触碰任何已钉文件**（不破外锚）。
> 依据（均在 `.superpowers/sdd/2026-09-27-fullload/reports/`）：`PINS-TIDY-AUDIT.md` §贰2.4（大纲与"新建不破锚"判定）、`PINS-ADD-PREP-20260927.md` §肆（钉册操作细则）。
> 计数口径：本文不手写易过期计数；凡标"（当时值）"者为起草时点记录，现值一律以目录现算为准（§7 给命令）。

## 1. 是什么

- 本目录是**完成审计板的钉册（哈希锚的 pinned 快照）及其判据记录件的受 git 追踪真身**。板件本体住在 `.superpowers/sdd/2026-09-24-central-dispatch/probes/s0-main-goal-audit.py`（gitignore 内，本机件），其读点已按 R7 裁定指向本目录（板 :24 `REGISTRY = REPO / "pins" / "2026-09-24-central-dispatch"`）。
- 钉册本体 `PINNED_GAUGES`（量具文件名 → sha256 全值的字典，枚数现读＝各条重钉日志末尾"在册共 N"的 N）**住在板文件里**（板 :66），不在本目录。本目录装的是板读写的三份活锚件：
  - `GAUGE-PIN-LOG.md` —— 量具钉册重录日志（板写完钉册后续记于此，板 :154）；
  - `GOAL-AUDIT-CELLS.roster` —— 格名册（分母的外锚物，板直读此路径）；
  - `GOAL-AUDIT-SEALED-BY-USER.md` —— 用户签核件（双哈希五行外锚：板 sha256 ∧ 板 md5 ∧ 裁定号 ∧ 名册 sha12 ∧ 名册 md5）。
- 其余为各施工席的记录件/判据出处，文件名与席位编号对应。实例：`NEVER-PIN-GATE-S643.md`（席 S643 的 NEVER_PIN 判据成品门件）、`PINS-READPOINT-AND-EMPTY-LOCK-S664.md`（席 S664）、`pins-channel/` 包的全案叙述在本目录 `PINS-CHANNEL-S764.md`（席 S764，包内 README 首行点名此指向）。
- `.superpowers/sdd/2026-09-24-central-dispatch/` 下的同名旧副本为**迁移前历史留档（gitignore，只读，不再续写）**——R7 迁面注原文见 `2026-09-24-central-dispatch/pins-channel/README.md` 末节。

## 2. 目录结构与一眼分类表

- `2026-09-24-central-dispatch/` —— 三件套 + 看板现渲染落点 `GOAL-STATUS-BOARD.md`（尺 s625 渲染面已迁此）+ 各席记录件（当时值 39 枚）。
- `2026-09-24-central-dispatch/pins-channel/` —— 适配轴「库↔库版本区间」声明通道件包（当时值 5 枚：README + patch-01/02/03 + rows-52.expected.md）。消费读点 `s764-teeth`/`s853`/`s869`/`s889` 已指此受追踪副本。
- 全目录枚数与清单现算：见 §7。
- 名目澄清（读册不混）：本目录的「钉册」＝哈希锚机制（钉住尺不被偷换）；记录件里出现的「pins」多指**跨库版本 pin**（semver 依赖声明），是另一层含义——只有 C3/B 两行讲后者。

全册 44 枚（不含本 README）按实际形态分三大类；C 类再按主线分五摊（枚数为 2026-09-27 现算当时值，现值用 §7 命令）：

| 大类 | 语义一句话 | 枚数（当时值） | 枚名 |
|---|---|---|---|
| **A 活锚**（板/消费读点在运行时读写） | 钉册机制的全部活件：签核外锚、重钉账链、格名册、看板渲染落点 | 4 | `GOAL-AUDIT-SEALED-BY-USER.md`（用户签核件·五行双哈希）／`GAUGE-PIN-LOG.md`（量具重录账链，逐枚旧→新）／`GOAL-AUDIT-CELLS.roster`（格名册＝分母外锚）／`GOAL-STATUS-BOARD.md`（看板现渲染快照） |
| **B 通道件包**（适配轴「库↔库版本区间」） | 从无到有的声明通道交付：文件地图＋两枚可粘贴增量＋一枚可执行判据原文＋一张期望投影对照快照 | 5 | `pins-channel/README.md`／`patch-01-declaration-side.md`／`patch-02-manifest-side.md`／`patch-03-gate-legs.py`（机器判据原文，尚未并入门件）／`rows-52.expected.md`（期望投影行对照快照，重生成即覆盖、禁手改） |
| **C 波次记录件**（判据原文/战果账，无运行时读点，供人查阅溯源） | 各施工席交卷成品：判据谁出的、钉在哪个板版本、攻防怎么落的——§1 说的「判据出处」全文在此 | 35 | 见下表五摊 |

| C 类主线 | 这条主线立了什么 | 枚数（当时值） | 枚名 |
|---|---|---|---|
| C1 板攻防 | 审计板假绿面：恶毒自攻、三轮复攻、固化成常驻台架 | 5 | `AUDIT-BOARD-ADVERSARY-S760`／`BOARD-REATTACK-S777`／`BOARD-REATTACK2-S798`／`BOARD-REATTACK3-S831`／`CELL-BY-CELL-FORCE-GREEN-S852` |
| C2 格真判化 | 把板上手写 PART/NO 的格换成可现算的尺 | 6 | `ADAPTATION-CELL-RULER-S805`／`BOARD-LEVEL-PRODUCTION-READER-RULER-S663`／`BUILDLIB-CELL-RULER-S809`／`CROSS-EDGE-CELL-RULER-S811`／`EXHAUSTIVENESS-CELL-RULER-S806`／`OUTSIDE-PLACEMENT-CELL-S784` |
| C3 版本 pin（适配轴） | 跨库 semver pins 的分母、漂移检测、NEVER_PIN 判据、取数口、钉册去自钉与外移彩排 | 9 | `PINS-DRIFT-DETECTOR-S604`／`PINS-DENOMINATOR-BUILD-S612`／`NEVER-PIN-GATE-S643`／`MAIN-DEP-PIN-FACE`／`PINS-READPOINT-AND-EMPTY-LOCK-S664`／`PINS-CHANNEL-S764`（B 包全案叙述）／`ROSTER-PIN-LOCK-S821`／`PIN-OUT-OF-BAND-S824`／`PIN-MIGRATION-REHEARSAL-S832` |
| C4 名册（分母） | 一级库名册定稿/V2/申报/落地、表外差集消化、名册与工厂/板/门腿的取数对齐 | 11 | `FIRST-LIBRARY-ROSTER-FINAL-S659`／`FIRST-LIBRARY-ROSTER-V2-S684`／`E11A-RETIRE-BINDS-ROSTER-S654`／`LIB-ROSTER-DECLARATION-S713`／`LIB-ROSTER-LANDED-S741`／`FACTORY-READS-ROSTER-S769`／`ROUTED-36-INTO-ROSTER-S762`／`ROSTER-SOURCE-MAP-S143`／`GATE-LEG-24-ROSTER-S840`／`OFFROSTER-43-DIGEST-S845`／`ROSTER15-CONFLICTS-S888` |
| C5 锚·坐标·漂移归因 | 裸行号棘轮改语义锚、版本真身多面、锚账独立复核、板块生成物漂移逐页归因 | 4 | `LINE-COORD-RATCHET-TO-SEMANTIC-ANCHOR-S662`／`MAIN-PATHDEPTH-AND-VERSION-ANCHORS`／`ANCHOR-8TO7-VERIFY`／`BOARD-DRIFT-14` |

- 命名规矩：C 类文件名＝主题名 + `-S\d+` 席号（`ROSTER-SOURCE-MAP-S143` 为短席号形）；不带席后缀的四枚（`ANCHOR-8TO7-VERIFY`/`BOARD-DRIFT-14`/`MAIN-DEP-PIN-FACE`/`MAIN-PATHDEPTH-AND-VERSION-ANCHORS`）首行各记其席号或「主代理亲跑」身份。

## 3. 判读规则（钉册 = 冻结时刻的真值快照）

- 每枚钉值是被钉量具**钉入（或重钉）那一刻**的 sha256 快照，用途是判"尺没被偷换或篡改"：板对不上钉值即 `FATAL …与钉册不符（换件或篡改 ⇒ 不可判）`，合法改版必须走 `--repin`（板 :168 附近的判据文字）。
- **任何 repin 会破坏外部锚**：钉册住在板文件里 ⇒ 改钉即换板字节 ⇒ 签核件里板 sha256/md5 两行**当场失效，须重签**。签核件的"重签历史"小节即此链的实录（含 2026-09-26 16:4xZ R7 迁面重封一条）。
- 对账链：`GAUGE-PIN-LOG.md` 逐枚记 `旧值 → 新值`，每条旧值 = 上一条新值（链断 = 账断）；PINS-TIDY-AUDIT §贰2.3(c) 实跑结论为断链 0、终值 12/12 合盘上现算。
- 改钉必须走上述登记流程，**不许原地改内容**：直接编辑板内 `PINNED_GAUGES` 或日志旧行，等于伪造快照现场。

## 4. 更新规程与新增钉的规矩

- **新建文件允许**：新文件不改任何既有被钉件字节 ⇒ 不破已有锚（本 README 即此型操作；审计判定见 PINS-TIDY-AUDIT §伍）。
- **修改既有钉文件 = repin，必须同批披露**：改了哪个件、为什么、签核外锚是否已失效须重签。
- 量具合法改版（改量具本体代码）走板 `--repin`，三条硬要求（板 :113–123）：
  - `--reason` ≥8 字（为什么换尺）；
  - 必须逐枚 `--only <件名>`——全量重录会把他人未验改动一并合法化（日志 2026-09-26 08:16:40Z 的局部撤销条款就是实案）；
  - `--evidence` ≥12 字且逐字含「直跑」「读数」。
  顺序为**先册后板**：板改钉册后向 `GAUGE-PIN-LOG.md` 续记旧→新对与理由。
- 拆/加审计格：必须**同批**改板 `CELLS` 与 `GOAL-AUDIT-CELLS.roster`——名册与板不合 ⇒ 整板拒判（板内 F12 注，:488 起）。

## 5. 何物入 pins/、何物不入

- **入**：被门禁/板/名册或消费读点引用的活锚、签核件，及其判据出处的受追踪记录件（判据全文见 PINS-TIDY-AUDIT §叁）；新增件须同批进一份 §肆 型逐枚清单并过敏感形态扫。
- **不入**：席报、探针源码、台架件、渲染中间值——留在 `.superpowers/sdd/` 各批次；gitignore 内历史副本勿顺带塞入（PINS-ADD-PREP §伍末段：根锚定 ignore 行不影响 pins/，但也无一行是为 pins 开的口子）。

## 6. 与 docs/ 及审计板的关系（谁引用谁）

- **板读 pins/**：`s0-main-goal-audit.py` 经 `REGISTRY` 直读本目录的日志（:154）、格名册（:490 附近）、签核件（:500 附近）。行号为 2026-09-27 现读值，板件不在 git 追踪内、可能漂移，指认以符号名 grep 为准。
- **钉与门的对应关系（2026-09-27 现算）**：全仓 grep 实跑，`tests/` 对 `pins/` 路径**零引用**——没有任何 pytest 门直接消费本目录字节；执法面就三处：①审计板运行时判据（板对不上钉值即 FATAL 不可判，吃 A 类三件套），②通道包消费读点（`pins-channel/` 五枚，台架件在 `.superpowers` 内非仓门），③归属账 `doc_ownership_sync`（管辖 glob `("pins","**/*.md")`，`--check` 现跑 CLEAN）。既有在册哈希钉门 `tests/verify_hashes.py` 只管 docs 哈希账、不读本目录；S824「钉册入 `tests/gauge_hashes.json` 并进门禁」是**未落地方案**（该文件与 `tests/test_workspace_manifest_gate.py` 盘上均不存在，patch-03 判据仍是待粘贴态）。
- **文档归属面**：`scripts/doc_ownership_sync.py` 已把本目录登记为 B10 过程件（:43 管辖 glob + :76 归属行，依据 R7 裁定 2026-09-27）。
- **narrative 面**：`docs/` 侧叙述（HANDBOOK/台账）引用本波时指向 `.superpowers/sdd/2026-09-27-fullload/reports/PINS-*.md` 两份审计件；本目录自身不以 docs/ 为读点——除 §肆 清单外，没有机制是 docs/ 读 pins/ 的，此点只写实读到的。
- **钉册引用的不在盘面件（已知挂账，非笔误）**：多数钉册正文引用 `.superpowers/.../probes|patches|disk-hashes.txt` 等 gitignore/不存在目标（PINS-TIDY-AUDIT §肆4 登记）；台架 `probes/s832-bench.py:468` 仍写旧面路径，重跑会与真身分叉（§肆2，待主代理裁）。

## 7. 复跑验证（全部只读）

```bash
cd <仓库根>
find pins -type f | wc -l                # 枚数现算（本 README 落盘后含本文件）
find pins -type f | sort                 # 逐枚清单
grep -n 'GAUGE-PIN-LOG\|CELLS.roster\|SEALED-BY-USER\|REGISTRY' \
  .superpowers/sdd/2026-09-24-central-dispatch/probes/s0-main-goal-audit.py   # 板读点现算
# 逐枚 sha256[:16] 现算（venv python，带仓库卫生前缀 PYTHONDONTWRITEBYTECODE=1）：
# ../ChatBot_Runtime/venv/Scripts/python.exe -B -c "import hashlib,pathlib;[print(hashlib.sha256(p.read_bytes()).hexdigest()[:16],p.name) for p in sorted(pathlib.Path('pins').rglob('*')) if p.is_file()]"
```

> **敏感内容边界（入库时已裁）**：既有钉册中 20 枚内嵌本机绝对路径（含登录名），PINS-ADD-PREP §陆定性为"本地路径披露、非凭证"并按处置 (A) 原样入库。本文件遵该裁定不改历史文本；**新增钉册件请不要再内嵌本机绝对路径**。
