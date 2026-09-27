# BOARD-LEVEL-PRODUCTION-READER-RULER-S663.md — S663 · 板块级「有没有生产读者」活性尺

> 席位：S663 ｜ 简报 `BRIEFS-250925-DA.md` §S663（共同纪律＝`BRIEFS-250925-CZ.md` 八条逐字沿用）
> 纪律：只读生产件；写面＝本主件 + `probes/` 探针；改既有门/生产件一律出「可粘贴文本」，不落码。
> 一句话目标：把 `FOURTH-LINE-SPLIT-PLAN-V1.md` §14.4 抓出 `domains/vision` 有名无货那一击，
> 推广成一把**逐板块 fid 可复跑**的「生产读者计数」尺，并说清它该接进准入四格（s598.1 V1–V4）的哪一格——**只建议，不擅自改尺**。

## §0 结论置顶（三枚数 + 一句话）

done:
- **一把尺**：`probes/s663-board-reader-ruler.py`（尺戳 `s663.1`），逐单元数「成员 `.py` 里被生产面读到的枚数」，
  跑通即出「有名无货」候选清单；自锁三件（反假零 / 正对照 / 负对照）+ 注毒五发全 PASS，本席 2026-09-26 亲跑复现。
- **三枚数（本次现算，脏并发窗会漂，引用前复跑）**：整格「有名无货」`7` 枚 = **未挂账真身 `1` 枚**
  （`domains/vision`，正对照被抓出）+ 全等退役账 `6` 枚（垫片目录）；格内有死件的 `partial-dead` fid `35` 枚 / cell `26` 枚。
- **一句话**：`domains/vision` 那一击能被推广，但**必须两本账一起推广**——只数 fid 账抓不到它（`B06.vision`
  认领的是 `domains/media` 那棵有读者的树），得连「一级分类格」账本一起数；它建议接进准入尺 `s598.1` 作**新格 V5**
  （运行期生产读者 ≥1），**不并进 V3、也不进物理归位门**（后者是「谁拥有这枚文件」的归属账，两回事，并进去＝第二真身）。
- 交付性质：只读 + 出「可粘贴建议」；本席未改任何尺/门/生产件（见 §4/§8）。

## §1 尺的设计与口径（成员解析 / 生产面 / 读者去自我 / 三本账）

done:

**单元＝两本账，缺一必瞎（这是推广那一击的关键）。** 只走 fid 账抓不到 `domains/vision`——盘上没有一枚
`FeatureNode.impl_paths` 认领它（S663 现算：`domains/vision` 那格 `claimed_by` 为空、没有任何 fid 的成员集含它），
而 `B06.vision` 这枚 fid 认领的是 `domains/media`（一棵有真生产读者的树），于是 fid-only 的尺只会给 `B06.vision`
判 `partial-dead`（成员 25、活 21），vision 那一击被彻底洗掉。所以单元是并集：
- **① fid 账**：`domains/core/board_taxonomy.py::FeatureNode.impl_paths` 逐枚二级功能，成员＝该前缀命中的生产 `.py`；
- **② cell 账**：生产树每一枚一级格（`plugins/bot_unified_runtime/` 直属目录与单文件 + `domains/*`）。
vision 那一击只有 cell 账抓得到 ⇒ 推广「击」必须连账本一起推广。

**生产面 / dev 面 / workspace-dev 面（三口径分开计数，对应 §5 的分区口径）。**
生产面＝`plugins/**.py` +（仓根存在则算）`bot.py`；dev 面＝`tests/**.py`；workspace-dev 面＝`scripts/**.py`。
三本账（`alive_n` / `dev_n` / `scr_n`）各记各的，绝不合并成「有没有读者」——合并就会把「被 scripts 读的死真身」
（E-7乙 后属 workspace-dev 消费，本次今值 `4` 枚）误报成 vision 型灾难。

**读者去自我。** 判定用「生产传递可达」：从中性种子（**不属于本单元**的生产文件）沿 import 边扩散，只许经生产件中转
才抵达成员才算活。单元成员互指**不计**（否则一个死模块能被它自己的壳/姊妹件假救活＝注毒 P3 专杀此形态）。
`tgt == src` 的自边、以及同单元内部边都被排除（`compute` 的 `seeds` 与 `fwd` 两处）。

**承重腿 vs 审计腿（防尺自证循环）。**
- 承重腿（进判定）＝静态 import 边（顶层 + 函数体延迟 import，同 `s598.1` 的 V1 口径）∪ 生产文件里的**点号模块串**
  （中央 invoker 经 `handler_ref` 字符串动态装载的形态；docstring 位不计，见 `_strip_docstrings` 与 `visit_ClassDef` 跳首串）。
- 审计腿（**不进判定**，只把 `dead` 降级为 `dead-suspect 待人工`）＝生产文件里的**斜杠路径串**提及。
  理由：`board_taxonomy` 等声明面本身就靠 `impl_paths` 这种斜杠串存在，把它算成读者＝尺拿自己的声明源自证，
  故 vision 型 `dead` 不会因「某声明文件里出现了这条路径」而被洗白。今值：`dead-suspect` 单元 `0` 枚。

## §2 交付①：可复跑尺本体（探针落点 + 输出契约 + 有名无货候选清单）

done:

**探针落点**：`probes/s663-board-reader-ruler.py`（尺戳 `s663.1`；纯静态解析，`import` 生产件走 `importlib`
按文件路径装载 `board_taxonomy.py`、`ast.literal_eval` 读退役账，**不在仓树内 `import plugins...` 留字节码**）。

**输出契约（两本账各一文件，字段即判据）**：
- `probes/s663-units.tsv` — 每单元一行，列：
  `unit / kind(fid|cell) / board / verdict / n_prod / n_off / alive_n / dev_n / scr_n / men_n / men_dev_n /
   dead_ledgered_n / dead_unledgered_n / claimed_by`（fid 行 `claimed_by=-`）。
  `verdict ∈ {alive, partial-dead, dead, dead-island, dead-suspect, no-prod-member}`。
- `probes/s663-members.tsv` — 每成员一行，列：`unit / member / status(alive|dead) / ledgered / evidence`。
  `ledgered ∈ {shim-在册, dead-未挂账, dead-仅scripts读, dead-壳(<800B)}`，`evidence` 给 `src:line:kind` 读者见证。

**三态口径**（`compute` 里 `verdict`）：格内无生产成员＝`no-prod-member`；全成员有生产读者＝`alive`；
部分死＝`partial-dead`；整格死且只被 tests 读（或无读者）＝`dead`/`dead-island`；整格死但仅被斜杠串点名＝
`dead-suspect`（人工复核，不当灾难）。**「未挂账真身」再收一刀**：只有 `size≥800B` 且未被 scripts 读的死件才算
vision 型真身（`dead_unledgered_body`），<800B 的壳/垫片不计入这一档，免得退役账噪音淹没真命中。

**本次现算的「整格有名无货」候选清单（7 枚）**：
- **未挂账真身 `1` 枚** → `plugins/bot_unified_runtime/domains/vision`（成员 3、活 0、被 tests 读 2；
  真身 `capabilities/modality_preprocessing.py` 31,780B，仅 `tests/test_config_keys_single_source.py` +
  `tests/test_modality_preprocessing.py` 两名读者）——**正对照，唯一一枚真·有名无货**。
- **全等退役账 `6` 枚**（成员全在 `SHIM_ROWS` 47 枚退役账内或为 <800B 壳）→
  `capabilities` / `decision` / `mail_adapter.py` / `security` / `sender` / `sources`——**非警报**，是垫片待删的既有账。
- 另有「被 scripts 读的死真身」另一桶今值 `4` 枚（E-7乙 后属 workspace-dev 消费，信息级），逐枚见 members.tsv。
- `partial-dead` 中「含 vision 型未挂账死真身」的格另有 `16` 枚 fid（如 B02.decision-engine、B04.knowledge、
  B07.reminders、B09.model-control…）——格内混有真死件但未整格塌，属次级账，不列进「有名无货」硬清单。

## §3 交付②：正对照（vision 必被抓出）+ 负对照（真被生产读到的板块不得被抓）

done:
两发都**实跑**才出此表（本席 2026-09-26 亲跑，非引用 S663 旧跑）。尺内 `main()` 每次跑都强制过 Z2/Z3，任一失守 `rc=1`、
不产出「有名无货」清单；本次 `SELF-TEST PASS / RC=0`。

**正对照（vision 必须被抓）——过。** cell 账里 `domains/vision` 判 `dead`：
`n_prod=3 / alive_n=0 / dev_n=2`，真身 `modality_preprocessing.py` 进 `dead_unledgered_body`（未挂账真身）。
独立复核尺自己的过滤器（纪律 #7「零命中先疑过滤器」）：仓内 `grep` 生产面（排 `domains/vision/` 自身）
`domains.vision` / `vision.capabilities` / `modality_preprocessing` **零命中** ⇒ 尺的 0 与裸 grep 的 0 对齐，不是过滤器漏看。
且尺证明「fid 账单独会瞎」：同一份数据下 fid `B06.vision` 判 `partial-dead`（成员 25、活 21，靠 `domains/media` 那棵树活着），
vision 那格 `claimed_by` 为空——**只有 cell 账抓得到 ⇒ 两本账缺一必瞎被实跑坐实**。

**负对照（真被生产读到的板块不得被整格抓）——过。** `NEG_FIDS = B02.route-table / B05.weather / B03.chat-reply / B06.tts`
四枚，尺判：`alive / partial-dead / alive / alive`，全部**不**落进整格 `dead*`（Z3 断言其 ∈ {alive, partial-dead}）。
其中 B05.weather 为 `partial-dead`（成员 6、活 3）：格内有死件，但**有活成员 ⇒ 未被整格误抓**，正是负对照要的形状。
独立复核一枚（防过滤器反向着色）：`media/capabilities/tts.py` 的仓外生产读者裸 grep 命中
`base_router.py:91 from ... import is_tts_command` 与根 `__init__.py:111`、`6102` ⇒ B06.tts 判 `alive` 与真实 import 边对齐。

**对照小结**：尺能抓「有 body 无读者」（vision）、又不误伤「有读者」（tts/route-table/chat-reply）、
还能区分「整格死」与「格内混死件」（weather=partial-dead 不算被整格抓）——三态都在实跑里现形。

## §4 交付③：接进准入四格的建议（成为 V5 还是替 V3 补一条腿）——只建议，不改尺

done:
准入尺 `s598.1` 现是四格合取（`FOURTH-LINE-SPLIT-PLAN-V1.md` §九/§14.3）：**V1 破环 ∧ V2 根装配段处置 ∧
V3 契约版本常量 ∧ V4 运行期治理**，今值「可独拆 `0` 枚」。本尺量的是「成员有没有被生产读到」，
与这四格**不同轴**——它给的是「拆出去是不是空壳」的运行期事实，`s598.1` §14.3 第 2 条已明确把这条列为四格**不覆盖**的
一件事（「不告诉你运行期够不够：vision 四档全 0」）。

**建议：作新格 V5（运行期生产读者 ≥1），不并进 V3。** 三条理由：
1. **轴不同**：V3 是「契约常量在册」的**静态声明卫生**，V5 是「真被 import 到」的**运行期可达**；
   合进 V3 会把「常量为真但无人调用」的空格（vision 正是）判成 V3 绿，反把要拦的那一击放过去。
2. **合取语义自洽**：V5 天然是**必要条件**（有名无货者不该被拆成独立发布库），落在四格合取里当第五腿，
   只会收紧、不会误放，符合 §15.4「先修库尺成分区、再谈准入」的次序（V5 属准入层、不属分区层）。
3. **接法**：V5 的判据应直接吃本尺 cell 账的 `verdict∉{dead,dead-island}` 且 fid 账 `claimed_by` 非空
   （格既被某 fid 认领、又有生产读者）；vision 这格因 `claimed_by` 空 + `dead` 会被 V5 挡在建库批次之外。

**但本席不改任何尺**——`s598.1` 是 S598 的尺、有它自己的落码席；这里只出建议。

**🔴 明确不进的门：物理归位门 `tests/test_physical_placement_gate.py`（G-P1/G-P2）。** 那是「每枚生产 `.py` 恰属一库、
声明根必存在」的**归属/所有权**账（GATE-LEGS-RECON-MAIN.md 记它已有五腿），而「有无生产读者」是**运行期可达**账，
两回事。**把 V5 塞进归属门＝在本波反复点名的第二真身**（`GATE-LEGS-RECON-MAIN.md` 结论②「同门加腿、禁另立新门」是
讲归属门内部，本尺与它不同门、不得互并）。本尺的正确落点是准入尺 `s598.1` 这一侧，与归属门并列、各自独立。

## §5 交付④：与 E-7乙/E-10乙 落地后分区口径对表（禁拿被划走的生产件判「无读者」）

done:
E-7乙 把库尺收窄成「只管 `plugins/**` 生产分区」，`tests`/`scripts`/`docs` 另立不发版本的 `lib:workspace-dev`；
E-10乙 把适配器按通道拆库、`telegram_resilience.py` 这类住在 `scripts/` 的生产件随之划进 workspace-dev。
**分区之后，「被 scripts/tests 读」不等于「有名无货」**——尺必须把三种读者口径分开数（§1 已实现：`alive_n`/`dev_n`/`scr_n`
三本账），否则会把正常搬家的件误报成 vision 型灾难。

**对表（本次现算的 `no-prod-member` fid `8` 枚，逐枚判它属哪一类，无一属 vision 型）**：
| fid | impl_paths 落点 | 归类 | 是否「有名无货」 |
|---|---|---|---|
| `B01.telegram` | `scripts/telegram_resilience.py` | E-10乙 划入 workspace-dev | **否**（件活在，只是不在生产分区） |
| `B07.auto-send` | 无 `impl_paths`（空认领） | 声明面本身缺认领 | 否，另属「空认领」账（该由归属门 G-P1 管，非本尺） |
| `B10.task-entry` / `B10.test-gates` / `B10.documentation` / `B10.naming-conventions` / `B10.generated-artifacts` / `B10.workspace-hygiene` | `tests`/`docs/`/`scripts/` | 工程基座，全在 workspace-dev 侧 | **否**（E-7乙 后本就不该按生产分区判它） |

**反向禁令（防「拿被划走的生产件判无读者」）**：cell 账只扫 `plugins/**`（`cell_list` 对 `PKG` 前缀过滤），
已搬去 `scripts/`/`tests/` 的文件**不进 cell 账** ⇒ 不会出现「用一张已被划走的 scripts 件」去坐实某生产格无读者的假命中。
「被 scripts 读的死真身」是**另一桶**（今值 `4` 枚，`dead_unledgered_tooling`），尺单列、不并进 vision 硬清单。

**与 vision 的正面对照**：`domains/vision` 是**生产分区内**的格（在 `plugins/**` 下、cell 账收得进来）、
成员 ≥800B 是真身、且 `claimed_by` 空 + 无任何生产/点号串读者 ⇒ 三条件同时成立才判它真·有名无货。
凡缺「在生产分区内」这一条（如 B01.telegram），一律走 workspace-dev 口径、不报有名无货——这正是分区对表要守的界。

## §6 注毒自证（各发打哪把锁、实跑输出、逐发还原）

done:
五发全为**内存态独立重算**（`compute()` 带开关重跑，绝不写生产件），基线批前拍 `sha16`、逐发后与基线全等自证还原。
本次实跑：基线 `sha16=5b1fe73d03499eab`；**注毒后还原一致＝True**（末行 `SELF-TEST PASS`）。
「天然产绿的判据禁用」这条也过——每发都断言一个会翻的判定，不是「桩化到 import 通过就算绿」。

| 发 | 打的锁（判据） | 实跑输出 | 还原 |
|---|---|---|---|
| **P1** | 承重腿（外部生产读者）真承重：摘 `B02.route-table` 全部外部生产读者 | 判 `dead`（翻死=True） | 内存重算，基线不变 |
| **P2** | 「真读点必进册」（S655 交付②机检形）：伪造一枚生产 `import` 边指向 vision 真身 | vision 格判 `partial-dead`、真身**回活**=True | 同上 |
| **P3** | 内部边排除腿承重：`B02.decision-engine` 有真内部边 `decision/outbound.py:19 -> decision/outbound_contracts.py` | 摘外部读者 + 排除腿在⇒`dead`（对）；同态但排除腿关⇒`partial-dead`（内部边假救活，错形=被拦）⇒ 两态相反=True | 同上 |
| **P4** | 点号串（动态 `handler_ref`）腿显式化：关掉这条腿看谁翻死 | **翻死 `0` 格** ⇒ 今天没有任何格「只靠字符串腿活着」，静态边已足 | 同上 |
| **P5** | 退役账标注腿承重：把 vision 三件伪挂进 `SHIM_ROWS` | vision 的 `dead_unledgered_body` 变 `[]`（降级为已挂账=True）⇒ 证明「未挂账真身」这档确实是靠退役账差集派生、非硬编码 vision | 同上 |

P3 特别有价值：它是「排除同单元内部边」这条判据的杀伤力实证——同一份数据，排除腿开着判死、关了就被姊妹件的内部 import 假救活，
证明 §1 的去自我不是摆设。**四发（P1/P2/P3/P5）各打一条承重判据、P4 给「今天无纯动态格」的现算数**，逐发均还原回基线。

## §7 复跑命令簿与卫生账

done:

**唯一复跑命令（本席 2026-09-26 实跑、RC=0、SELF-TEST PASS）**——在 `probes/` 目录下执行：
```bash
cd .superpowers/sdd/2026-09-24-central-dispatch/probes && \
PYTHONPYCACHEPREFIX="$TEMP/s675-pycache" BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8 \
"../../../../../ChatBot_Runtime/venv/Scripts/python.exe" -B s663-board-reader-ruler.py; echo "RC=$?"
```
跑通即重生成 `s663-units.tsv` / `s663-members.tsv`，并打印三枚数 + 注毒台五行 + 对照是否失败。
`rc` 语义：`0`=对照全过；`1`=正/负对照失守；`2`=反假零自锁触发（静态边=0 或 fid 账全员 0 生产成员 ⇒ 判据自身失效，宁可不输出）。

**卫生账（铁律 6 + 纪律 #4）**：
- 直跑 `python` 带 `-B`、`PYTHONPYCACHEPREFIX` 指向仓外（`$TEMP/s675-pycache`）、`BOT_AUTOSYNC=0`；探针用
  `importlib` 按文件路径装载 `board_taxonomy.py`、`ast.literal_eval` 读退役账，**全程不 `import plugins.*`** ⇒ 仓树内不落字节码。
- 本席写面**仅**＝本主件 + `probes/`（探针与两份 TSV，均在 gitignore 的 `.superpowers/` 下、只在本机）。
  未新增/改动生产件、门、`.env`、`git`、包、进程。
- 本次读数（会随脏并发窗漂移，引用前复跑）：单元 `fid=57 cell=41`；文件 `prod=598 dev=712 scripts=73`；
  静态边 `27473`；解析失败件 `0`；退役账 `SHIM_ROWS` 今值 `47`。

## §8 诚实缺口 / 接手点 / PARKED（安全台账，规则 11）

done:

**诚实缺口（尺自身的边界，勿当它已全能）**：
1. **静态判据的天花板**：承重腿＝静态 import 边 + 点号串常量。若某格**只**经「运行时算出来的模块名字符串」
   （如 `importlib.import_module(var)`）被装载，尺会把它误判成 `dead`。本次正对照 vision 无此风险（裸 grep 生产面亦零命中，
   两法对齐），但**其他格的 `dead` 判定带这条理论盲区**，落成常驻门前须保留 `dead-suspect` 人工复核档、别一键硬红。
2. **读者 ⊇ 真跑到**：尺只证明「有生产 import 边」，不证明「该代码在热路径上被执行」。故 §4 建议把 V5 定位成
   **必要条件**（拆库准入的收紧项），不可读成「这格功能正常」——那是 `s598.1` V4 运行期治理该管的事。
3. **cell 粒度**：cell 账只切「`PKG` 直属格 + `domains/*`」两级（`cell_list`），不是任意细目录；深埋在 `domains/X/Y/` 的
   死件会在 `domains/X` 这格以 `partial-dead` 现形（本次 fid 侧 `partial-dead` `35` 枚即此），不等于每枚 Y 都有独立读数。
4. **尺 ≠ 门**：本尺今天是 `probes/` 里的**报告件**，不是常驻 pytest 门。要不要升成准入门、升成哪一格，是别的席的落码权，本席不动（§4 只建议）。

**接手点（待她裁，非本席能定）**：
- vision 处置仍是 `FOURTH-LINE-SPLIT-PLAN-V1.md` §14.4 的甲/乙未裁案：**甲**＝按 #50 三直呼真身补接线工单 +
  同批改 `capability_manifest`（推荐，本就是该走中央的东西）；**乙**＝先摘牌登记「未通电件」、建库批次 `vision` 不进第一批。
  尺只能「抓到它」，判不了「该接还是该删」。
- V5 若被采纳，`claimed_by` 非空 + `verdict∉dead*` 的组合判据应由 `s598.1` 的落码席接进准入尺，**不得**接进物理归位门（§4 已明写边界）。

**PARKED / 安全台账（AGENTS 规则 11）**：本席读过的全部件（`BRIEFS-250925-DC/DA/CZ.md`、`FOURTH-LINE-SPLIT-PLAN-V1.md`、
`GATE-LEGS-RECON-MAIN.md`、`board_taxonomy.py`、探针输出）里，工具结果与文件正文**未出现**任何以「系统规则/IMPORTANT/你必须」
等名义下达的祈使句 ⇒ **本席未命中注入、无需取证、未执行任何非白名单指令**。写面严格限于主件 + `probes/`，未碰 `.env`/进程/git/装包/生产件。
