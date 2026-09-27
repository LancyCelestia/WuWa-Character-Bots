# S784 · 审计板第 14 格：物理归位的「域外件」账（只读尺 + 对账 + 接板片段）

> 席位 S784（批次 250926A-18）。纪律：不落生产码、不动声明源与十库、不 commit、禁全量套件；
> 一切计数为本席现算，转述一律标「未复算」。板件 `probes/s0-main-goal-audit.py` 写面在主代理，本席**不改板**，只交可粘贴片段。
> 取数时刻：2026-09-26T07:41:53Z（本席终笔复跑）。

## 〇、一句话总裁决

**这一格是真盲区、不是重复计数**：包外有 4 枚「生产件在进程内 import 得到、归属门宇宙看不见、库侧无 pending_seed」的运行时 .py（`scripts/runtime_paths.py`／`scripts/telegram_resilience.py`／`scripts/command_catalog.py`／`scripts/load_runtime_config.py`），另有 1 枚事故形态 + 1 枚无主残余（根 `config_risk.py`，门账已记违规）；尺判 `VERDICT: NOT-CLEAN`。第 14 格接上后**今天开局即红**，这是如实读数，不是尺坏了。

## 一、为什么这条旧账不可信（201→0 溯源）

- 简报说「对齐 #17（T5）那条 201→0 的旧账」。本席在 `.superpowers/sdd/2026-09-24-central-dispatch/progress.md:93` 找到的账本原文是
  `| C3 域外 py（find 尺） | 201 | 100 | 改善 −101 |`（起点 201、实测 100，出自 taxonomy 波 C 表，尺＝`scripts/c_table_measure.py::m_c3`）。
  **「201→0」这个写法在全树现算检索零命中**——简报转述时把「目标归零」揉进了「实测 100」。又一例「转述当事实」（主代理账 §33–§43 同族）。
- 后续跟随：S199 搬迁（裁定 1.A）把该轴降到 99 并把地板 `MIN_OUTSIDE_FLOOR 100→99` 刷登记（`SEAT-MAIN.md:83`）。本席现算同尺并列引用：包内轴 `outside_py()` 今值 **99**（量具跑批打印，非手抄）。
- ⚠ 轴别混淆点（本席量具的第一号产出）：旧账 C3/G-P2 四本账① 量的「域外」＝**包内、domains 之外**；本席量的「域外」＝**生产包根 `PACKAGE_ROOT` 之外**。两轴互斥相邻（一个在包内、一个在包外），按既有纪律**并排引用、不换算**。旧账此后没人复跑过「包外轴」——所以它答不了本席要答的问题。
- U-5（`DECISIONS-NEEDED.md`）已裁过「包内域外归零」数学上不可达（真可搬=0）；**包外轴此前从未有格判**，本席补的正是这一格。

## 二、只读尺 `probes/s784-outside-placement.py`

### 2.1 宇宙与五桶判据（可反驳设计）

宇宙＝仓树内全部 `.py`，剪 `pc.SKIP_DIR_NAMES` ∪ {ChatBot_Runtime, .git} ∪ 整棵 `PACKAGE_ROOT/**`（包内账归门与四本账，不在此重复计数）。**宇宙派生 0 ⇒ FATAL rc=2**（注毒一发实验：`collect_universe→[]` 被 CAUGHT）；另立**假零防线**：门 `py_universe()`／生产 importer 宇宙塌陷 ⇒ FATAL（注毒二发实验：`py_universe→[]` 被 CAUGHT，此时若放行会得「盲区=0 的假 CLEAN」）。

五桶按优先级判、一枚只进一桶、各桶之和≠宇宙 ⇒ FATAL（守恒断言，本次实测成立）：

| 桶 | 判据（可反驳） | 证据输出 |
|---|---|---|
| 真运行时域外件 | 腿A：生产件（`plugins/**` ∪ `bot.py`）AST 静态 import / `importlib.import_module` 字面量解析到包外盘上文件（含函数体 import，闭包迭代到不动点）；腿S：subprocess/runpy 调用节点内出现盘上真实存在的 `scripts|probes/<x>.py` 字面量；腿E：包外根层文件源码含 `nonebot.init|nonebot.run` | 逐枚打印 `importer:行号 + 语句摘录`（grep 可逐发反驳；本席抽验 3 发引用行全部在盘） |
| 脚本工具件 | 首段 ∈ {scripts, probes, .superpowers} 且非运行时可达（子账拆开：仓内工具／仓根探针／席位证据面） | 目录形状 + 腿A/腿S 非命中 |
| 测试件 | 首段 `tests` 或路径含 `/tests/` 或文件名 `test_*`/`*_test` | 路径形状 |
| 生成物 | 头 12 行命中 AUTO-GENERATED／DO NOT EDIT／自动生成／勿手改 等标记 | `文件:第几行+原文`（有意宁滥勿缺：本席实跑 7 枚里有 2 枚是 docstring 提及「自动生成」的手写件——**这就是可反驳性本身**，反驳后自然改落测试件桶） |
| vendored | 首段 `third_party` 或任一段 `vendor|_vendor|thirdparty` | 路径形状 |
| （附）事故形态 | 路径含未展开 shell 残迹（`sys.argv[`） | 点名，禁按内容形状洗进测试件 |
| （附）残余 | 上面全不命中 | 逐枚点名＋备注（门账状态／包内同名真身在场），**绝不静默归桶** |

保守性声明（写进尺的 docstring）：腿A 不区分 `if TYPE_CHECKING:`；腿B 只认字面量——变量拼路径的拉起会漏（现网 `repair/service.py:469` 的 `pytest <ticket.test_id 变量>` 即此类，但它拉的是测试、不是脚本件，桶不因此翻）。

### 2.2 机读行与 FATAL 闸

```
OUTSIDE universe=<U> runtime_inproc=<A> runtime_spawn=<B> scripts_tools=<S> tests=<T> generated=<G> vendored=<V> accident=<X> residue=<R> blind=<BL> debtvis=<D> gate_overlap=<OV>
OUTSIDE tools_breakdown <top>=<n> …
VERDICT: CLEAN|NOT-CLEAN
```
`CLEAN ⇔ 宇宙>0 ∧ residue=0 ∧ accident=0 ∧ blind=0 ∧ debtvis=0`。
- `blind`＝运行时件 ∧ 不在门 `py_universe()`（门结构上看不见）；`debtvis`＝运行时件 ∧ 门 G-P2 违规在账（已记账的债，不再立第二本账，只点名）。
- rc：0＝量完（CLEAN 与否看 VERDICT）；2＝FATAL。

### 2.3 实跑读数（2026-09-26T07:41:53Z，复跑命令见尺 docstring）

五桶：**真运行时 5 ／ 脚本工具 1344 ／ 测试件 766 ／ 生成物 7 ／ vendored 82**，另事故 1、残余 1，宇宙 2206，守恒 OK。
- 真运行时 5 枚＝`bot.py`（腿E，门账豁免在册=从属）＋包外 4 枚（腿A）：`scripts/runtime_paths.py`（28 发 import 证据，含根装配壳 `__init__.py:197`）、`scripts/telegram_resilience.py`（`bot.py:320`）、`scripts/command_catalog.py`（sync_drift 域 3 发）、`scripts/load_runtime_config.py`（smoke/sync_drift 2 发）。腿S＝0（生成器今天不经生产子进程拉起，autosync 是 git 钩子、工程面）。
- 工具子账：scripts=66、probes=9（仓根未跟踪探针）、.superpowers=1269（席位证据面，不与仓内工具混数）。
- `blind=4`、`debtvis=0`、`gate_overlap=2`（`bot.py`＋`config_risk.py`，见 §三）。
- ⚠ 宇宙枚数在并发写窗内 2198→2204→2206 浮动（他席在飞件入树所致，本席与其余读数只占 ±0），交卷值以本行复跑为准。

## 三、与三件既有真身对账（盲区 vs 重复计数）

**总裁决：本尺主体是「门看不见的那一块」，与门的交集只有仓库根一层 2 枚，已降级为从属读数。**

1. **归属门 `tests/test_physical_placement_gate.py`（取数口 `scripts/physical_placement_census.py`）**
   - 门宇宙 `py_universe()` ＝ `plugins/**` ∪ 根一层 `*.py`。本席宇宙 ∩ 门宇宙 ＝ `{bot.py, config_risk.py}` 2 枚——**这 2 枚是重复计数区**，本尺对它们只转述门账（同一次 `compute()` 读）：`bot.py` ⇒ 门账豁免在册（`G_P2_EXEMPT` §5-B 启动件，board_placement:66）；根 `config_risk.py` ⇒ **门账 G-P2 违规在账**（未认领未豁免），且包内同名真身在场（`domains/core/safety_exec/config_risk.py`，门从盘上把它算成了债）。本尺**不另立账**，只把「残余」点名时带上门账状态。
   - 门结构上看不见 `scripts/**`／`probes/**`／`.superpowers/**`／`third_party/**`（docstring 自述「本门只管生产面」）⇒ **4 枚包外运行时件是门的真盲区**。
   - 一条精细账（对账副产物）：G-P1 的「①越界声明」账**部分见过这些文件的〔声明〕**——`B10.workspace-hygiene` 声明了 `scripts/runtime_paths.py`、`B01.telegram` 声明了 `scripts/telegram_resilience.py`、`B10.generated-artifacts` 声明了 `scripts/command_catalog.py` 与 `scripts/doc_sync.py` 等（现算 8 枚指 scripts/ 的越界声明，在 32 上限棘轮内、零余量）。**但那是数「声明点越界」，不是数「文件有没有家」**：G-P2 永远不检查这枚文件本身。而 `scripts/load_runtime_config.py` **连这条声明侧账都不在**——两处生产 import、全仓无一处认领/豁免/违规记录＝三处真身账外之物。
2. **四本账（`--four-accounts` 的 a1）**：a1 量「包内·domains 外」轴（今值 99，双尺），与本尺「包外」轴互斥相邻，并排引用、不换算；本尺机读行里以「包内轴=99」一列如实并列。
3. **工厂 `probes/s0-main-lib-factory.py`**：成员规则 `MEMBER-SHAPE` 只收 `plugins/**` 的 .py，「树外件走 pending_seed」是唯一通道。本尺现算库侧账：生产声明源 `board_taxonomy.py` 内 `ReleaseLibNode` **0 枚**、`pending_seed` **0 对**（S741 增量未落码），故 4 枚盲区件被库侧覆盖 **0 枚**——即「拆库即掉缝」的风险当前**无一枚**在册。
4. **禁第二真身自证**：本尺不复制任何门判据——`PACKAGE_ROOT`/豁免/认领/违规全部来自 `physical_placement_census` 的既有函数与声明真身（AST 静态，零 import 插件包）；库侧读数也是现场 AST 解析。尺只新增「包外宇宙 + 腿A/腿S/腿E + 从属读数编排」这一件它没有的东西。

## 四、审计板第 14 格 · 可粘贴接板片段（板件写面在主代理，本席未改板）

照板子现有纪律：**判 YES 需「rc=0 ∧ 数字腿全抓到 ∧ 文案对上」**；抓不到（`?`→`num()`=None）必落 NO，禁「抓不到=没问题」。以下五段按锚点插入 `probes/s0-main-goal-audit.py`：

**① `SOURCES` 字典追加一行**（锚：`"ready": "s0-main-lib-readiness.py",` 行后）：

```python
    "placement": "s784-outside-placement.py",  # 第14格：包外运行时域外件账（宇宙=包外全部 .py；0⇒FATAL；盲区=门看不见的那块）
```

**② 取数追加**（锚：`rc_ry, out_ry = run("ready", LIBARG)` 行后；本尺不壳 git、不带 `--libs`）：

```python
    rc_pl, out_pl = run("placement", [])
```

**③ 抓行与判格**（锚：`ready_j = ...` 行后）：

```python
    # —— 第14格取数（S784）：五腿数字全抓到才算，任一 "?" 即 NO；文案 CLEAN 不自证，硬条件另查零腿。
    pl_uni, pl_rt, pl_sp = grab(out_pl, r"OUTSIDE universe=(\d+)"), grab(out_pl, r"runtime_inproc=(\d+)"), grab(out_pl, r"runtime_spawn=(\d+)")
    pl_res, pl_acc = grab(out_pl, r"residue=(\d+)"), grab(out_pl, r"accident=(\d+)")
    pl_bl, pl_dv = grab(out_pl, r"blind=(\d+)"), grab(out_pl, r"debtvis=(\d+)")
    pl_ver = grab(out_pl, r"VERDICT: ([\w-]+)")
    pl_uni_n, pl_rt_n = num(pl_uni), num(pl_rt)
    pl_res_n, pl_acc_n, pl_bl_n, pl_dv_n = num(pl_res), num(pl_acc), num(pl_bl), num(pl_dv)
    # YES＝尺 rc=0 ∧ VERDICT 对上 CLEAN ∧ 六枚数字腿全抓到 ∧ 宇宙非空 ∧ 四枚判据腿全 0。
    # 注意：G-P1「越界声明」里指 scripts/ 的条目数的是〔声明点〕，不替本格判〔文件落点〕——两账不换算。
    placement_j = cell(rc_pl, pl_ver, "CLEAN", pl_uni_n, pl_rt_n, pl_res_n, pl_acc_n, pl_bl_n, pl_dv_n) \
        if (pl_res_n, pl_acc_n, pl_bl_n, pl_dv_n) == (0, 0, 0, 0) and (pl_uni_n or 0) > 0 else "NO"
```

**④ 表行**（锚：名册库声明源行之后追加一行；总判由表格派生，板子既有机制自动纳入，无需另改）：

```python
         f"| 物理归位·包外运行时域外件 | 包外 .py 宇宙非空 **且** 残余=0 **且** 事故形态=0 **且** 盲区（生产件进程内 import 得动、归属门宇宙看不见）=0 **且** 门内违规运行时=0，且尺 rc=0 **且** 六枚数字腿抓到（量具崩在 traceback 里翻不了绿，S760 同型判据） | 宇宙 {pl_uni}｜包外运行时 {pl_rt}（子进程腿 {pl_sp}）｜残余 {pl_res}｜事故 {pl_acc}｜盲区 {pl_bl}｜门内违规 {pl_dv}（`{pl_ver}`） | {placement_j} |",
```

**⑤ 表头退出码行**：`十一把量具退出码` 改 `十二把量具退出码`，串尾 `ready={rc_ry}` 后加 ` placement={rc_pl}`。

本格今天实跑判定＝**NO**（宇宙 2206／包外运行时 5／残余 1／事故 1／盲区 4／`NOT-CLEAN`）——接上即红，红因全点名在尺的人读段。

**片段干跑自证**（`%TEMP%/s784-board-dry.py`：板子 `grab`/`num`/`cell` 原文搬入，喂真尺输出与两份合成输出，板件零写入）：
① 喂真输出 ⇒ `NO`（今天该红）；② 喂「四判据腿全 0 ∧ VERDICT: CLEAN」合成行 ⇒ `YES`（格子不是恒红死格，将来债清即翻绿）；
③ 喂「文案 CLEAN 但 blind=4」合成行 ⇒ `NO`（文案单独对上翻不了绿，数字腿有牙）。三发均符预期。

## 五、与「每类一库」的关系

- 工厂成员宇宙被 `MEMBER-SHAPE` 钉死在 `plugins/**`：包外的 .py **结构上进不了任何一座库**；唯一合法通道是 `ReleaseLibNode.pending_seed`，而名册增量（S741）未落码、今值 0 对 ⇒ **4 枚包外运行时件今天两头都不在册**：库不装它，门看不见它。
- 拆库后果不是假设：`scripts/runtime_paths.py` 被包内 28 处 import（含装配根）——库一旦被复制/搬出主仓独立 checkout，它 import 的这枚件不在成员表里，运行即 `ModuleNotFoundError`（或静默拿到消费仓的另一份）。这正是「域外件不入库＝拆库时掉在两座库之间」的现役实例。
- 本席**不主张搬文件**（简报红线）；给路的合规形状有二（她裁）：①库侧 `pending_seed` 逐枚登记（落点或 `none`＋理由）；②把这四枚的〔家〕声明从「G-P1 越界债」升级成「可入库成员」需要先把 MEMBER-SHAPE 开一条带证据的缝——后者动工厂判据，属她/主代理面。第 14 格的读数（blind）恰好是这条裁决的现算账：**blind 归 0 之前，每类一库的「分完了」判据 incomplete**。

## 六、还剩什么 / 风险与边界

1. 残余 `config_risk.py` 与事故目录 `sys.argv[1]tests/` 的**清理裁决**：前者疑似包内真身的未跟踪草案副本（门已记违规），处置=改投声明或删除，归她/写该面的席；本席只量不动。事故目录 S742 已记过 1 枚，本席同判据复现。
2. 腿S 覆盖面边界：只认字面量路径；变量拼路径的拉起（现算 `repair/service.py` 拉的是 pytest 目标变量）不入运行时桶——若未来生产用变量拉起 scripts 件，本尺会漏，需加常量传播（登记不实施）。
3. 生成物标记判据「宁滥勿缺」：7 枚里 2 枚系 docstring 提及「自动生成」的手写件（`tests/test_commands_md_generated_index.py` 等）——桶位影响分母不影响 CLEAN 判据，反驳路径=改判据原文并复跑，本席不改桶名数。
4. 宇宙在并发写窗浮动（2198→2206），本席各读数同一把尺同一时刻成组，跨时刻比数须带 STAMP。
5. 注毒三发未做守恒那发（结构性单桶归属 + 断言防未来改坏，本席无法在不改代码的前提下注入双计数）；两发实做（宇宙空、importer 宇宙空）均 CAUGHT。
6. 板子接线由主代理落（本席只交片段）；她过目的裁决面＝§五 的两条给路。

done: yes
