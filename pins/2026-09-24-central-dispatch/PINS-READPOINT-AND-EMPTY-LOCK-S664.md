# PINS-READPOINT-AND-EMPTY-LOCK-S664 — pins 取数口与「空名册自锁」合流件

席位：**S664** ｜ 简报：`BRIEFS-250925-DA.md` §S664 ｜ 共同纪律＝`BRIEFS-250925-CZ.md`「全程纪律」八条（逐字沿用）
工作根：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
席目录（写面只在此，`.superpowers/` 已 gitignore）：`.superpowers\sdd\2026-09-24-central-dispatch\`
主件：本文件 ｜ 探针：`probes/s664-1-pins-readpoint.py`（§0/§3 读点与取值路径现算）
性质：**只读生产件、只出成品文本、不落码**；不建库、不动 git（含不建 tag）、不读 `.env`、不装包、不重启/杀进程、禁跑全量 `dev.ps1 -Task test`。
开窗（本席第一次 `date -u`）：`2026-09-25T15:29:47Z` ｜ HEAD 现算 `5cc6832` ｜ 交卷时刻 UTC `2026-09-25T15:49:05Z`（末次实跑/复核时刻）
完成度：**7/7 节已交并实跑**（§0–§6 全填；§4.2 三发注毒与全量门禁按 §6.4 P-S664-2/P-S664-7 明确记为**未实跑**，不混称）｜ 剩余一句：**无本席待填格**；下游缺她两句见 §6.4 P-S664-3/P-S664-4

> **本节由 S694 补完（2026-09-25T18:0xZ ｜ 出处：`BRIEFS-250925-DD.md`「续做批」S694 行 ＋ 同件「取数取证三条」T1–T3；三条新事实的原始出处＝`E9B-VERSION-FILE-LANDING-S652.md`、`S639-BLOCKS-DISPOSED-S656.md` §2、`SEAT-MAIN.md` 15:4xZ 段「我一发裁定（tag 命名空间两席打架）」）**
>
> 本席按简报口径**只动那四处**（＝全件 `待填` 字面所在的 4 行：本行、§0 表 0-D 行、§3.1 末段总答、§6.4 表 P-S664-6 行），**纯追加、原有 461 行正文一字未删未改**（写后回读现算＝**481 行／CRLF 481／LF-only 0**，与原文件同种行尾、无混合；追加 **20** 行全在本席四处之内（本句所在块的末行亦本席追加，行数随每次回读再 +1 属预期，交卷现算以 §6.4 P-S664-6 行末的复跑命令为准）；`.superpowers/` 已 gitignore（`.gitignore:42`）且不在 `verify_hashes` 在册面 ⇒ 不触任何门）。**账面向舰队看护报备一句**：本件 `grep -c` 该字面从 **4 涨到 5**——多出的一行就是本句（点名判据口径），另两处在 0-D／P-S664-6 里**引用他席的占位符字面**（"那包今为骨架、尚有 12 处未填"）；**本席自己这四处追加里没有一格是未填**，按"含该字面即算未填"的粗尺会把本件误判成没交卷，请以本行为准。三句要点：
> 1. **命名空间已裁 `slug`**（`refs/tags/<slug>/v<纯三段 semver>`，出处见上；`lib:BNN` 与 `lib/BNN` 两形**一并作废**，禁再用）⇒ 本件 §2.2 判据本体里那句"拿 `library_id` 直造 tag 名"的写法**从今天起会把尺自己弄瞎**：本席按原语义复跑，16 行名册报 `blind`、**16 枚红**，其中一枚来自**永远不该有 tag 的伪库 `lib:workspace-dev`**（S659 定稿第 16 行，不发版本）——它不是"没发布"，是判据把"不入 tag 宇宙"读成了"瞎"。修法与注毒见 P-S664-6 行末补注 ＋ `probes/s694-1-denominator-lock.py`。
> 2. **`0.0.1-beta.1` 的拦路闸不止 `SEM_RE`**：本席独立复跑 S652 实测（同值）——严尺下 `ValueError: bad semver`，**把正则放宽到收预发布段之后**，取数体 `_sem()` 那句 `a, b, c = s.split(".")` 改抛 **`ValueError: too many values to unpack (expected 3)`** ⇒ "出路①＝只改一把尺"是半改，**崩点更晚也更凶**。本件 §0-C／§3.3／§4.1 里"撞第一道闸"的说法须按此加一句。
> 3. **等值门须逐字比**（S652 G-V3：`literal` 形＝`VERSION.strip()` 与投影**逐字恒等、含前导 `v`**；推荐的 `dynamic` 形则**判结构不判值**——投影里出现 `version` 字面量即红）。⇒ 本件 §3.3 处置第 2 行「`pyproject` 投影＝去 v 形」与 G-V3 **不能同真**，本席只登记撞车、不代裁（归她与落码席定形）。
>
> 另：本件 §2.2 那枚"空名册必须响亮"的自锁**新补一条硬性质**——**分母为 0 时判据不得恒真**。实测洞在 P-S664-6 行末（只含幽灵命名空间的仓，V1 读成 `released`／0 红）。
> **卫生账（本席 18:14Z 现算，交舰队看护归因用）**：本席写面＝本件四处追加 ＋ `probes/s694-1-denominator-lock.py` ＋ 同名 `.txt` 产物 ＋ `s694-1-err.txt`（0 字节＝全程无 stderr）；**未改** 任何 `plugins/`、`scripts/`、`tests/`、`docs/`、`config.py`、`pyproject.toml`、`.env` 字节，零 git 写（真仓 `refs/tags` 仍 1 行、HEAD 仍 `5cc6832`、分支不变），零装包、零重启、未跑全量套件。源码树 `*.pyc` 在本席窗内新增 **15 枚**（18:11:47Z–18:13:30Z，模块集是**装配根 import 图**：`bot_unified_runtime/__init__`、`chat`、`providers`、`capability_protocols`、`deadline`、`memory_bus_v2`、`vector_knowledge`、`cookies`、`web_search`、`file_reader`、`group_info`、`group_cache`、`participant_memory`、`randpic`、`news`）——**不是本席产物**：本席全程 `-B` ＋ `PYTHONDONTWRITEBYTECODE=1` ＋ 盘外 `PYTHONPYCACHEPREFIX`，探针从不 `import plugins.*`（唯一装载的 `board_taxonomy` 亦未落字节码，且其 `.pyc` 不在这 15 枚里），且最后两枚时间戳**晚于本席最后一次 python 执行**；按台账 #50 口径**只登记、不清理、不代搬**。本席自有足迹＝**零**（席目录 `__pycache__` 现算 0 枚）。


**一句话总结**：三件合流之后，pins 面**不是"没人填"而是三闸互斥**——本席把它做成一个七步可落序列（S0–S6，逐行给前置与"单独入库树干不干净"的判定），把「空名册」拆成**四态**（unavailable／blind／unreleased／released）并给出可粘贴判据（复用 CM-P-9 塌陷锁，不另立第二把尺），真跑五发注毒坐实：今天该响的恰是一枚 `EMPTY-RELEASE-ROSTER`（P1），**而一旦按 S646 建议把十张库 id 写成 `lib:B0x`，态就从 `unreleased` 变成 `blind`——打再多 tag 也修不好**（P2 实测 10 枚红，`git check-ref-format` 逐枚 REJECT）；关腿一发（P3）证明这条响亮今天**完全挂在新增的那一条腿上**，删掉即全场静默绿。取值路径逐枚数出九口，今值取得到值的只有 3 口、**没有一口给出她裁的 `v0.0.1-beta.1`**（S652/S656 两包经本席逐节读确认＝阵亡骨架 ⇒ E-9 在盘上是"一句意图、零处真身"），并钉住两条新雷：**巧合等值可掩盖取值宿主漂移**（现网外来发行 `WuWa-Character-Bots` 版本恰等 `pyproject` 现值，本席实测）与**投影化之后 bot 一致性腿会退化成自己比自己**（⇒ 被比侧必须换成独立读点）。

> 勘误（S702，2026-09-25T18:12Z）：本句「S652/S656 两包经本席逐节读确认＝阵亡骨架」为读数窗旧值（本席开窗 15:29:47Z、交卷 15:49:05Z），**今已过时**——现盘 `E9B-VERSION-FILE-LANDING-S652.md`＝**57,652 B／495 行／`grep -c '待填'` 0／sha256[:16] `8e610d37bda15c27`**、`S639-BLOCKS-DISPOSED-S656.md`＝**27,398 B／242 行／待填 0／`2934773c6f19ccac`**（本席 18:11Z 现算，逐值坐实 S694 所引指纹），两包均已交卷成文；S694 已把 §0-D、§6.4 两格改为「两包今均交卷」，但未随本句与 §3.1 总答。⚠ 本条**只纠「两包阵亡骨架」一处**；同句「⇒ E-9 在盘上是一句意图、零处真身」的结论经 S694 独立复算（`VERSION` ABSENT／`pyproject` 0.1.0／tag 1 行）**仍成立、不随此改**。原句照此限定、不删。详见 `ERRATUM-SWEEP-S702.md` 第④条。

## §0 置顶：对简报／前席前提的现算（坐实／推翻）
done: 本节已交（2026-09-25T15:3xZ 实跑，探针 `probes/s664-1-pins-readpoint.py`，读数全表在 §5）。

本席开窗 UTC `2026-09-25T15:29:47Z`｜HEAD `5cc6832`｜全程只读。**凡枚数只在该尺戳＋窗内成立，跨窗只传 Δ 不比大小。**

| # | 简报／前席前提 | 本席现算 | 判定 |
|---|---|---|---|
| 0-A | 简报「S604 证 pins 分母九词全 0 ⇒ 今天没有一条漂移判据能配成断言」 | 同一把尺（`grep -rnE --include=*.py "\b词\b" plugins scripts tests`）本席重跑：`workspace_manifest`／`library_id`／`requires_min`／`requires_max_exclusive`／`pinned_version`／`breaking_events`／`bot_version`／`pins`／`_CONTRACT_VERSION` = **9/9 各 0**；另加两词 `NEVER_PIN`、`release_tags_by_library` 亦各 **0** | **坐实**（且扩到十一词全 0） |
| 0-B | 简报「S643 交 NEVER_PIN 门成品」 | 主件在盘、自述 §0–§6 填毕；但其 §1 判据头部两行 `from plugins.bot_unified_runtime.domains.core import workspace_manifest as wsm` ＋ `wsm.SEM_RE`／`wsm.NEVER_PIN` ⇒ **吃声明源**。本席现算声明源 `plugins/.../domains/core/workspace_manifest.py` = **ABSENT**（四件全 ABSENT） | **坐实并补一条硬前置**：这件「成品」今天**不可单飞**，理由不是它不好，是它的 import 口指向一枚不在盘的件 ⇒ §1.4 给切分法 |
| 0-C | 简报「S646 证 `0.1.0` 起步与 NEVER_PIN 含 `0.1.0` 互斥」 | 复算两半：`0.1.0` **确在** S643 §1／S612 §4.3 的三枚名册；且 `pyproject.toml:3` 现值逐字符 = `0.1.0` ⇒ 互斥成立。🔴 **但本席新增一格**：E-9 裁值去 v 后的 `0.0.1-beta.1` **不在**名册、**却不过**本仓 `SEM_RE`（探针 `grammar_rulers`）⇒ 对撞没消失，只是**换了拦路的闸**（从第三闸挪到第一闸） | **坐实＋改判位置**（详见 §4） |
| 0-D | 简报「起点值按她 E-9 裁的 `v0.0.1-beta.1`」 | 盘上现算：仓根 `VERSION` **ABSENT**、`pyproject.toml` 仍 `0.1.0`、tag 仍 `v0.0.1-alpha.2` ⇒ **裁定未落盘**；落地席 `E9B-VERSION-FILE-LANDING-S652.md` §0–§6 全为 `done: <待填>`（阵亡骨架），`S639-BLOCKS-DISPOSED-S656.md` 同（31 行、tag 命名空间实跑表未填） | **报备**：本席序列**不得**把 E-9 当既成事实，只能把它当**显式前置**（§1.2 步骤 S0），并点出 S652/S656 两包缺席会卡住哪两步。<br>**本节（§0 表）由 S694 补完（2026-09-25T18:0xZ ｜ 出处：`BRIEFS-250925-DD.md` §S694 行 ＋ 盘上四件 `E9B-VERSION-FILE-LANDING-S652.md`／`S639-BLOCKS-DISPOSED-S656.md`／`E9B-PATCH-REALRUN-S685.md`／`FIRST-LIBRARY-ROSTER-FINAL-S659.md`；指纹逐件随文给出 ＋ 本席现算，T1 树身份＝`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`，`Path.cwd().resolve()` 前缀已自证）**：①**核心判定照旧成立**——`VERSION` 仍 ABSENT、`pyproject.toml:3` 现值仍逐字 `version = "0.1.0"`、`git for-each-ref refs/tags` 仍 **1 行**（第二尺 `git tag --list` 亦 **1**，两尺同值）、HEAD 仍 `5cc6832`、分支仍 `v0.0.1-alpha.2` ⇒ **裁定仍未落盘**。②**但「两包缺席」这半句已过期**：`E9B-VERSION-FILE-LANDING-S652.md` 今 **495 行／57,652 B／sha256[:16] `8e610d37bda15c27`**、`S639-BLOCKS-DISPOSED-S656.md` 今 **242 行／27,398 B／`2934773c6f19ccac`**，两包均已交卷 ⇒ **S0 的施工文本现在有**（S652 §1.2 读点补丁 before/after 逐字＋§2.1 投影两形＋§2.2 等值门 G-V1…G-V5＋§3.1 逐尺表；S656 §2 命名空间选定与 §3 八格跟随面）。③**卡点换了位置，没消失**：验收席 `E9B-PATCH-REALRUN-S685.md`（"在 `%TEMP%` 整份副本上真打一次"那包）今为骨架——本席现算 **12 处 `待填`** ⇒ "§1.2 那 19 行 diff 逐字可用"至今**没有被第二人真打过**。所以 0-D 只能升到「**有文本、未复打**」这一档，**禁**叙述成"E-9 已落地"。④**给 S0 新增两格前置**（本席现算出处）：根版本若要打 tag，撞的是 S656 §3h 点名的「预发布串不过 `SEM_RE`」（＝本席第 2 条新事实：严尺拦一次、放宽后取数体再崩一次，见 §3.1 行末补注），与命名空间无关；命名空间那一格**今天已裁**（`slug`），故 §1.2 的 S5 前置①「两式并存」风险关掉一半——**剩那一半更阴**：裁完之后 `library_id` 与 tag token 是**两个不同形状**（`lib:B01` ∥ `ingress-protocol`），联表必须走派生函数，见 P-S664-6 行末补注与本席探针。 |
| 0-E | 「唯一那枚 annotated tag 可作发布锚」 | `git for-each-ref refs/tags` 现算 **1 行**：`refs/tags/v0.0.1-alpha.2 tag`（objecttype=**tag** ⇒ 确是 annotated）；但 S643 的 `split_release_tag()` 对它返回 **None**（无 `<library_id>/` 段）⇒ 不进名册；`git rev-parse v0.0.1-alpha.2` 本席实跑仍报 **`warning: refname ... is ambiguous`**（分支 `refs/heads/v0.0.1-alpha.2` 同串） | **坐实 S646 §0-8**（既不能作证、也不能无歧义寻址） |
| 0-F | 简报「推 pins 的 `bot_version` 取值路径」（单数） | pins 面上**有两处** bot 格：投影件顶层 `doc["bot_version"]` 与每行 `pins[i]["bot_version"]`，一致性腿（S594 门件 `:216` `got["bot_version"] != doc["bot_version"]`）**只在这两格都有值时才开火**；今值 pin 行数 **0** ⇒ 该腿今天**零靶**。取值路径本席逐枚数出 **9 条候选**（§3.1），**今值只有 3 条真取得到值**，且取得到的三条**没有一条等于她裁的号** | **补充**（简报的"路径"是单数，实为两格九口，且一致性腿今天结构性失明） |
| 0-G | 🔴 新发现（前席未记）：**巧合等值可以造第二真身的假绿** | `_plugin_version()`（`domains/ops/monitor/error_report.py:582`）的候选发行名是 `("bot-character-bots", "bot_character_bots")`，本席实测**两名都 `PackageNotFoundError`** ⇒ 今天退 `pyproject` 取到 `0.1.0`。但现网 venv 里装着**外来发行 `WuWa-Character-Bots`，版本恰为 `0.1.0`**（本席实测；S657 交付②已证该 venv 的 `pyvenv.cfg` 指向他项目）⇒ 谁把它当"本项目改过名的旧发行名"补进候选元组，取值口就会**悄悄换宿主**，而"顶层 == pyproject"这类等值门**仍绿**（两值逐字符相同） | **新增失效形态**（进 §3.1 V-3 那行与 §5 复跑；这条与"名字尺当语义尺"同族，但更阴：它靠**巧合等值**躲过等值腿） |
| 0-H | 「门件里 `from scripts import workspace_manifest_sync` 是新造路数吗」 | 现役同形 **15 枚**测试件（本席现算 `tests/*.py` 内含 `from scripts import` 的文件数／`tests` 顶层共 683 件）；`scripts/__init__.py` **不存在**（靠 PEP 420 命名空间包 + conftest 的 sys.path）；`[tool.pytest.ini_options] testpaths = ["tests"]` | **坐实**：S643 §1 的 import 形与仓内惯例一致，**不是**新造；但也因此它的**收集失败半径是全树**（见 §1.3 机制段） |
| 0-I | 「空名册必须响亮」需不需要新造一把尺 | **不需要，本仓已有真身**：`scripts/channel_capability_declaration.py::load_declaration()` 的**塌陷锁**（`:223` 起，注释逐字：「空表与『声明被抹光』同形 ⇒ 停手报，不出视图」）＋ `scripts/configure_axonhub_registry.py:DeclarationBlindError`（`:136` 「抛而不是返回空问题列表：循环对空声明面**恒零问题**」）＋ 三腿锁件 `tests/test_declaration_readers_no_silent_empty.py`（CM-P-9，每支三腿＝真身现读非空／合成再导出壳仍解析得出／**空表必抛**） | **采用为交付②的骨架**（复用判据结构、换数据源；本席**不另立第二把「空表」尺**——那正是 §2 要防的病） |
| 0-J | 延账门能不能兜住「把空名册表达成条件 skip」这种绕行 | **兜不住**：`tests/test_defer_expiry_gate.py:13–16` 自述射程——`skipif`／`importorskip`／**守卫内**（`if`/`except`）的 `pytest.skip()` ＝「条件自解，**不要求日历**」，只有 `xfail` 与**裸** skip 才要三件。⇒ 绕行道是门**自己写在注释里的**，不是本席推演 | **坐实并据此立法**（§2.4 禁四条天然产绿表达，其中两条正是这条免检口） |
| 0-K | 根装配件体量（§1.4 的「门别挂装配根」论据） | `plugins/bot_unified_runtime/__init__.py` 本席现算 **9,979 行**（S646 窗内记 9,860 ⇒ 他窗插行，只传 Δ 不比大小） | **窗漂报备**（凡本文行号/枚数均为本席窗快照） |

**三句结论先行**：①**序列本身今天不欠"她的裁"**——§1.2 的 S1–S4 四步全部零配置键、零生产行为改动，唯一卡她的是 S5（打 tag）与 S0（E-9 落盘）；②**pins 面的"0"不是没料可填，是三道闸互斥**（`SEM_RE` 只认三段数字／主判据要有库命名空间的 annotated tag／名册兜底含 `0.1.0`）——她裁的 `v0.0.1-beta.1` 恰好又撞第一道（§4.1）；③**空名册今天必须显式成一枚红**，而"响亮"的正确落点是**已有的塌陷锁族**（CM-P-9 形），不是再写一把 `if not released: skip()`。

## §1 交付①：三件合流后的**可落门序列**（声明源 → 唯一供给点 → 生成器 → 投影 → 门）
done: 本节已交（§1.1–§1.4）。

### 1.1 序列成立前先钉的四处现算（本席新读数，全部指到盘上真身）

- **(a) 声明源可独立落盘**：`%TEMP%\s594-mirror\plugins\bot_unified_runtime\domains\core\workspace_manifest.py` 头部 import 只有 `from __future__ import annotations` / `re` / `dataclasses` / `typing`（本席逐行读）⇒ **零包内依赖、零第三方依赖**，单独进树不触装配根。其 docstring 还写死两条禁条：**「装配层不读本件」**（manifest 是发布账不是运行配置）与**「巡检不覆盖本件」**。⇒ 直接推出一条对本序列很值钱的性质：**五步全程零改根 `__init__.py` ⇒ 坐标棘轮一族（`test_outbound_registry_campus_coordinate_is_live`，本窗已两度顶漂）零跟随**。这也是「运行时读 manifest」被否、只能走「投影件＋常驻门」的硬理由。
- **(b) 失败半径只在 `tests/` 一侧**：`pyproject.toml:54` `testpaths = ["tests"]`（本席现算）⇒ `plugins/`、`scripts/` 的新件**不被 pytest 收集**。生成器对声明源的依赖方向是**按文件路径读**（`DECL_PY` 常量），不是 `import`；而门件对二者是 `import`。⇒ 「锁先于真身＝整树收集红」的机制**精确地**是：**一枚 `tests/*.py` import 到盘外件 ⇒ 收集期 `ImportError` ⇒ 这一次 `-Task test` 整体以收集错误终止**（不是「那一件红」）。任何分笔方案都按这条判生死，别按"应该只影响那个文件"的感觉。
- **(c) 投影件的根版本今天来自第三处**：`scripts/workspace_manifest_sync_fixed.py:82`（镜像候选件）逐字是 `"bot_version": w.BOT_VERSION`，而 `workspace_manifest.py:48` 是 `BOT_VERSION: Final[str] = "0.0.0"`（本席读镜像件现算）⇒ 投影的根版本**不住 E-9 的真身**，而是声明源里另一枚字面量。这正是 S612 §2.4 判的"造第二真身"，且本席补一句它没写的：**E-9 乙案落地时，这一行必须同批改指 `VERSION`**，否则「唯一真身」只到文件层、投影仍从别处取值，等值门反倒替第二真身作了保。
- **(d) `sync` 列的不对称今值仍在**：本席现算 `scripts/chatbot-tasks.json` 的 `sync` 块 = **4 枚 `--write`**（`:431 command_catalog` / `:433 doc_sync` / `:435 verify_hashes` / `:437 board_doc_sync`）＋ **3 枚 `--check`**（`:439 doc_sync` / `:440 verify_hashes` / `:441 board_doc_sync`）⇒ **独缺 `command_catalog --check`**（与 S612 P4 两条独立实现相等）。⇒ 新投影件进表时**必须同笔**把 `workspace_manifest_sync.py --check` 写进 check 列（否则新件天生复刻这条不对称，且会把它的对称性比在一条残缺基线上）。

### 1.2 七步序（S0–S6）、每步前置、以及「这一步单独入库树干不干净」

| 步 | 落什么（文件级坐标） | 前置（逐枚点名，缺一条即不许做这步） | 单独入库收集干净？ | 谁的手 | 做完解锁哪条判据 |
|---|---|---|---|---|---|
| **S0** | E-9 乙落盘：新建仓根 `VERSION`（真身）＋ `pyproject`/文档由生成器投影＋`_plugin_version()` 改指＋（若她要打根 tag）命名空间定稿 | ①她裁的号已给（`v0.0.1-beta.1`，见 §3 三形问题）②S652 交付①的改读点表落地（那件今为**骨架**）③S656 的 tag 命名空间表落地（那件今为**骨架**，本席已在下一行 S5 给出 `git check-ref-format` 实测补它的缺） | ✅（只加文件；但 `verify_hashes`/`doc_sync` 若在册则须 `--write`） | 落码席＋她 | 只解 `pins.bot_version` 的**取值口**；**不**解库命名空间 tag（那是两本账，见 §3.2） |
| **S1** | `plugins/bot_unified_runtime/domains/core/workspace_manifest.py` ＋ **同笔**一枚只吃它的门 `tests/test_workspace_manifest_declaration.py`（§1.4 的甲件） | ①镜像候选件在盘（本席现算四件全在 `%TEMP%`，**无 git 回滚位**＝S612 P-S612-1 仍 OPEN）②🔴 **若照 S646 §5.4 第②条把 6 张点形库名换成 10 张 `lib:B0x`，必须同批改 tag 命名空间的派生法**——`refs/tags/lib:B01/v…` 实测被 `git check-ref-format` **REJECT** ⇒ 不换派生法就是把主判据永久弄瞎（§2.3 P2 实测 `blind`／10 枚红；可派生形如 `B01`、`lib_B01`、`chatbot-repo-<slug>`，本席实测三形皆 OK）。这一格**归 S659 名册定稿**，本席不代裁（P-S664-3）③`NEVER_PIN` 名册三枚的在仓证据逐枚成立（§4.1 跟随表） | ✅ 甲件 import 的真身在**同笔**在场；`testpaths` 不含 `scripts`/`plugins` ⇒ 无别处受害者 | 落码席 | L-1 文法／名册单点供给／判序（主判据先行）三把腿今天起有牙 |
| **S2** | `scripts/workspace_manifest_sync.py`（含 S612 §3.1 那一行 `sys.modules[spec.name] = mod`，位置＝`mod = module_from_spec(spec)` 之后、`exec_module` 之前） | ①S1 在盘（`DECL_PY` 指它）②`scripts/board_doc_sync.py::load_taxonomy` 在场（本席现算：生成器 `from board_doc_sync import load_taxonomy`，唯一板块解析口）③**手工插那一行**、`git diff --numstat` 自证 `1 0`（镜像两文件全 CRLF，`git apply` 会把整件 166 行重写成改动＝S612 §3.1 施工告诫） | ⚠ 收集干净但**不可单飞**：此刻它是「在场无人读」——正是 S612 §5 定罪的形态，且第一次 `-Task sync` 就会因无 `--check` 项而漏检 ⇒ **S2/S3/S4 视为同一笔** | 落码席 | 投影能力（不产生断言） |
| **S3** | `docs/workspace-manifest.json`（`--write` 产物；手编＝L-9 红） | S2 已入库（幂等 `--write` 产出） | ✅（纯 JSON，不被收集） | 落码席跑生成器，不手写 | L-9/L-10（投影确定性＋三同体）——本席现算投影件今值 **ABSENT** ⇒ 这两条今天**结构上无法跑**（S612 §1.3 同判） |
| **S4** | 常驻门：`tests/test_workspace_manifest_gate.py`（L-1…L-11 ＋ N-E/N-F/N-G/N-H）＋ **本席 §2.2 的空名册自锁** ＋ **S643 §1 的乙件**（真册常驻断言）；跟随面：`chatbot-tasks.json` 的 check 列（§1.1-d）、`doc_sync --write` 重录机器册（新增 `.py` ⇒ 测试文件数漂）、`verify_hashes` 若在册须重录 | S1＋S2＋S3 全在 HEAD；🔴 另加 S612 §3.2 **P6** 那两枚未跟踪接缝测试件（`tests/test_feature_gate_layer2.py`、`tests/test_creation_image_protocol.py`）——本席现算门件 L-4 的「在盘」腿在**干净 checkout** 里对它们必红，不处理掉就是往全量里放一枚定时红 | ✅（同笔齐全） | 落码席 | M0 全量：DR-3 三腿＋DR-2b 限定面（S612 §2.2 今值 **7/10 条边**）＋名册腿＋投影腿 |
| **S5** | 发布动作：给若干库打**带库命名空间**的 annotated tag `refs/tags/<library_id>/v<纯 semver>` | ①S1 的 `library_id` 文法与本步**同一支**（点形 `core.dispatch` 与板形 `lib:B01` 不可两式并存）②命名空间过 `git check-ref-format`：本席实测 `refs/tags/core.dispatch/v1.0.0` = **OK**、`refs/tags/lib:B01/v1.0.0` = **REJECT**、`refs/tags/B01/v1.0.0`／`lib_B01/v1.0.0`／`chatbot-repo-core.dispatch/v1.0.0` = OK ⇒ **S639 若按 `lib:B01` 当 tag 段是非法的**，S656 未填的那张实跑表按本席读数补 | n/a（git 写面，归她） | **她的手**（本席不 tag、不动 git 写） | **主判据的分母**——这一步之前 NEVER_PIN 门恒缺料、pins 恒空是**设计内终态**，且 §2 那条响亮红会持续开火（这是**对的**：它就是要一直响） |
| **S6** | `PIN_ROWS` 首批行（每枚带非空 `why`）＋ `breaking_events` 账先立（S604 §2.3 步骤 4）→ DR-1／DR-1b／DR-2a／DR-4 逐条升断言 | S5 已发生（否则 `never_pin_reason` 第一/第二闸必红）；`requires_min/max` 两格排 in pins **之后**（S612 §1.2：区间腿只在被钉目标存在时开火，实测注毒 5b 双绿＝对无钉库完全失明） | ✅ | 落码席＋她（`breaking_events` 的每行要有票根） | S604 §1 四类漂移里剩下的三类 |

**跳步的代价逐格点名**（防"看起来差不多先落一半"）：只 S1 不 S4 ⇒ 声明源成**没人读的账**（L-11 那族病，且它还是可编的）；只 S2＋S3 不 S4 ⇒ 投影件漂了无人报（＝第二枚 `dep_sync` 病：命令在册、脚本缺席的镜像形态）；S4 先于 S1 ⇒ **整树收集红**（本表唯一"红"不是"缺一格"的形态）；S5 先于 S1 ⇒ tag 命名空间无文法可依，反向锁（S643 §1 末段）会拿一堆"没人认领的库的假"红给她看。

### 1.3 「锁先于真身＝整树收集红」的三条绕法（各挡一种分笔形态）

**先说死机制**（(b) 的推论）：pytest 的收集是**全量一次**的行为——任何一枚被收集的 `tests/*.py` 顶层 import 失败，这次跑就整体以收集错误告终。所以绕法只有两类真解：**（甲）锁与它 import 的真身同笔**；**（乙）锁根本不 import 盘外件**（改吃文件路径／AST／dict）。第三条是补救形态、不是免死牌：

1. **绕法一＝按输入面把门件切开**（挡「S1 想先落、四件想后落」）：S643 §1 那份成品里，**反例腿与注毒腿只吃 (doc, tag 集) 两个 dict**、真册那条才吃 S2/S3 ⇒ 天然可切成甲/乙两件（§1.4）。切完 S1 落地当天就有一把有牙的常驻门，不必等齐四件才见第一把锁——**这正是要争取的东西**：S604 §2.2 已经证明"拦得最狠的那道（同树收集）恰恰是拆库时最先失效的那道"，所以早一天有独立的锁、就早一天不必依赖那堵正在变薄的墙。
2. **绕法二＝统一装载口、禁包形 import**（挡「门件把 9,979 行装配根卷进收集期」）：S643 §1 原样写 `from plugins.bot_unified_runtime.domains.core import workspace_manifest as wsm`——包形 import 会**执行**装配根（本席现算 `root_init_lines = 9979`），使一枚"发布账"的门挂上 NoneBot／运行时路径初始化这一整个不相关面，且声明源缺席时报的是 `ImportError`（连带半树的连带效应）而不是人话。改法：**门与生成器共用同一个 `load_declaration()`**（按文件路径、只标准库、崩点已由 S612 §3.1 那一行修好），声明源缺失时抛 `FileNotFoundError` 并点名"缺哪件、哪步该带它"。⚠ **装载口只能有一份**：门吃 `scripts.workspace_manifest_sync.load_declaration`，**禁**在门里再写一遍 `spec_from_file_location`（那是第二真身，也是崩点复发处）。
3. **绕法三＝缺料不许伪装成绿**（挡「先落门、料后到」这段必然的空窗）：三态里 `missing_inputs` 非空 ⇒ 门**必须显式红并点名缺哪一格**，或该判据**根本不得配进门禁**（S604 §1.0 K2 原教义，本席沿用不改字）。今天注定缺料的三条（主判据分母空、pins 空、DR-4 无上一发布态）用**同一支延账口径**落：`xfail(strict=False)` ＋ `〔expiry=YYYY-MM-DD owner=SEAT-* 摘牌=<条件>〕` 三件齐——**owner 必须是能动手的人/席**，写工单号会被延账门自己的 `RE_TICKET_POINTER` 拒（`tests/test_defer_expiry_gate.py:26–27`；S661 正在复核这一条，本席不重开）。**到期即红是这条规矩的全部意义**：空窗有期限，不会静默变常驻债。

### 1.4 S643 那份门件必须**切成两件**落地的理由与可粘贴 import 头

现算依据三条：①它的 §1 顶部 `wsm.SEM_RE`/`wsm.NEVER_PIN` 吃 S1，而 `test_never_pin_leg_is_green_on_real_book` 吃 S2（`render_manifest_dict()`）与 S3（投影）；②S643 自己 §5 已经把这条写成待办——「**须与声明源/生成器/投影件同笔；单跑门件先 import wsm.NEVER_PIN ⇒ 今天必 ImportError**」，也就是说**它本席已经判过自己不可单飞**，但交付面仍是一整件 ⇒ 落码席照抄就会在 S1 那一步卡死；③它 §1 真册那条用 `from scripts import workspace_manifest_sync as syncmod`——`scripts/__init__.py` 不存在（本席现算），全靠 PEP 420 ＋ conftest 的 sys.path；现役同形 15 枚测试件坐实这形在本仓可用（§0-H），**但它把 S2 拖进了本可只依赖 S1 的那半**。

**甲件（随 S1 落）**：`tests/test_workspace_manifest_declaration.py` —— 收 S643 §1 的 `_split_release_tag`／`never_pin_reason`／`p_never_pin` 三个纯函数＋`test_fake_denominator_is_caught`＋四发注毒＋`test_split_release_tag_never_lstrips` 参数表＋**本席 §2.2 的空名册自锁（名册侧）**＋**§4.2 的名册在仓证据成对锁**。头部只准出现：

```python
# 只吃两样：装载口（人话报错）＋纯 dict。禁 from plugins... import（会执行装配根，见 S664 §1.3 绕法二）
import pytest

from scripts.workspace_manifest_sync import load_declaration

_DECL = load_declaration(REPO_ROOT)          # 缺声明源 ⇒ FileNotFoundError 并点名 S1
_SEM = re.compile(_DECL.SEM_RE)              # 文法唯一真身：由声明源供给，门里禁第二份字符集
NEVER_PIN: frozenset[str] = _DECL.NEVER_PIN  # K1：名册也只住声明源
```

**乙件（随 S2＋S3＋S4 落）**：`tests/test_never_pin_gate.py` —— 只收 S643 §1 最后那条真册常驻断言（`p_never_pin(syncmod.render_manifest_dict(), release_tags_by_library(REPO_ROOT)) == []`）**＋ 本席 §2.2 的分母侧（真仓名册为空 ⇒ 这条不得报绿）**。两条必须同件，否则乙件自己就是 §2.4 要禁的那枚"空转即绿"。

🔴 **切分时最容易丢的一格（本席点名为施工红线）**：`release_tags_by_library()` 与 `_split_release_tag()` 是**同一支尺的两半**，切到两件里＝造第二真身。唯一解法：**两支都住甲件**（它们只吃 `git for-each-ref` 输出与字符串，零 S2/S3 依赖），乙件 `from tests.test_never_pin_gate import ...` 之类反向 import 测试件是禁的 ⇒ 乙件改为**复用同一模块对象**：把尺子沉到 `scripts/` 一侧（建议 `scripts/workspace_manifest_release_tags.py`，stdlib＋git 只读），甲/乙两件与生成器三处**同取一支**。这一格 S643 未涉（它整件一起落，不存在切分问题），是**本席因"分笔"新引入的**，故必须写在序列里而不是留给临场判断。

## §2 交付②：「空名册必须响亮」——`release_tags_by_library` 为空时的自锁判据原文
done: 本节已交（§2.1–§2.5）；判据本体已在 `probes/s664-2-empty-roster-lock.py` **逐字实现并真跑**（五发结果在 §2.3），未落 `tests/`（红线）。

### 2.1 先把「空」拆成四态（否则判据会把尺瞎读成未发布）

S643 §3 已经把今天那枚 0 定性为**空转绿、非已合规**，并说「要让它非空转地绿，缺的是发布动作，不是改判据」。这句话**只对了一半**——本席现算出一个它没覆盖的形态：**「缺发布动作」与「发布动作永远不可能被记到」在两值函数 `release_tags_by_library() -> dict` 上长得一模一样**（都返回 `{}`）。这正是 CM-P-9 塌陷锁处理过的那类病：`scripts/channel_capability_declaration.py:226` 的原话是「空表与『能力标签被整批抹光』不可分辨（S28 事故形），拒绝产出空视图」。所以先按**能不能分辨**把「空」拆四态，判据按态分报法：

| 态 | 触发形态 | 今值（本席实跑） | 正确报法 | 为什么不能当绿 |
|---|---|---|---|---|
| **unavailable** | `git for-each-ref` 退出码非 0／不可达目录／编码炸 | 探针 `unavailable_probe` ⇒ 态＝`unavailable`（本席用不存在的路径造） | `missing_inputs`：`RELEASE-ROSTER-UNAVAILABLE` 点名 stderr | 它是「眼睛坏了」，与「没货」是两个动作主体（运维 vs 发布），混了就永远等不到人 |
| **blind** 🔴 | **在册 `library_id` 造不出合法 tag 名**，或造出来洗不回来（切分尺与 id 文法不匹配），或命名空间被一枚裸 tag 占了位（D/F 冲突） | 真仓＋点形六库 ⇒ 不触发；真仓＋**S646 建议的十张 `lib:B0x`** ⇒ 态＝**`blind`、10 枚红**（§2.3 P2） | `violations`：`RELEASE-ROSTER-BLIND` 逐枚点名是哪个 id、哪一环不通 | 这一态**打再多 tag 也不会自愈**——把它报成「未发布」就等于告诉她「你去打标吧」，而她打完发现还是空，**这条路径上没有任何人会回来改文法** |
| **unreleased** | 文法通、命令可达，但带命名空间的 annotated tag 今值 **0 枚** | **这就是今天真仓的点形态**：态＝`unreleased`、响亮红 **1 枚**（§2.3 P1） | `violations`：`EMPTY-RELEASE-ROSTER`，并同批落**一枚带日历的延账**（§2.2 末段） | 今天的 `{}` 是**结构洞**（S612 F-4）而非「没人有空填」。S643 已经拒绝把这个 0 报成通过；本席把它从"席位的克制"升成**门里的一个分支** |
| **released** | 名册非空（至少一枚带命名空间 annotated tag） | 合成仓 `core.dispatch/v1.2.3` + `lib.render/v0.4.0`（+ 一枚 lightweight 干扰项）⇒ 态＝`released`、**0 红**、名册解析出 2 库 2 版 | 正常放行，且此时才轮到 S643 的主判据逐枚判 pin | 只有这一态下的绿才叫绿 |

**四态只有一态可以说「绿」**，其余三态各有一句人话要点名——这就是本件对「响亮」的定义：**不 skip、不静默、不 return []，且报的是"缺谁的哪一个动作"**（unavailable→运维/门禁环境，blind→S1 的文法，unreleased→她的 S5 发布）。这条口径与 #54 的 `attribution_status`（matched/miss/unavailable）同族：**「没查到」永远不许被读成「没有」**。

### 2.2 可粘贴判据全文（复用 CM-P-9 塌陷锁的形，禁第二真身）

**落地位置与同笔约束**：判据本体进**甲件**（`tests/test_workspace_manifest_declaration.py`，随 §1.2 步骤 S1）；`p_release_roster_*` 的两枚真册调用进**乙件**（随 S2＋S3＋S4）。尺子（`raw_refs`/`split_release_tag`/`release_tags_by_library`/两枚自证）**必须沉到 `scripts/workspace_manifest_release_tags.py`**（只 stdlib＋git 只读），甲件/乙件/生成器三处同取一支——**禁**在两件里各抄一份（§1.4 末段那格是本席因"分笔"新引入的坑，不写死就会长出来）。

```python
r"""pins 主判据分母自锁（S664）：空名册必须响亮，且「空」要分四态。

判据骨架沿用 CM-P-9 塌陷锁（scripts/channel_capability_declaration.py:226 与
configure_axonhub_registry.py:DeclarationBlindError 同一族）：
「读成空」与「眼睛瞎了」不可分辨时，一律拒绝产出空视图。
数据源只有两样：在册库行（吃 load_declaration()）＋ git refs（只读 for-each-ref）。
K1：本件不写任何库名/版本号/枚数，只写词表与判序。
"""
from __future__ import annotations

from pathlib import Path

from scripts.workspace_manifest_release_tags import (        # 唯一一支尺（禁在门里重写）
    df_conflict_problems, namespace_roundtrip_problems, raw_refs, release_tags_by_library)
from scripts.workspace_manifest_sync import load_declaration

RELEASE_ROSTER_STATES: frozenset[str] = frozenset(
    {"unavailable", "blind", "unreleased", "released"})


def read_release_roster(doc: dict, repo_root: Path) -> dict:
    """四态判定（纯读、零写）。返回 {"state", "released", "problems", "stderr"}。"""
    ok, rows, stderr = raw_refs(repo_root)                       # 不可达 ⇒ unavailable，不是 unreleased
    if not ok:
        return {"state": "unavailable", "released": {}, "problems": [], "stderr": stderr}
    ids = [lib["library_id"] for lib in doc["libraries"]]
    problems = namespace_roundtrip_problems(ids, repo_root)      # L-E2：id 造不出合法 tag / 洗不回来
    problems += df_conflict_problems(ids, repo_root)             # L-E2b：命名空间被裸 tag 占位
    if problems:
        return {"state": "blind", "released": {}, "problems": problems, "stderr": stderr}
    released = release_tags_by_library(repo_root)
    state = "released" if released else "unreleased"
    return {"state": state, "released": released, "problems": [], "stderr": stderr}


def p_release_roster_is_loud(doc: dict, repo_root: Path) -> dict:
    """主判据分母格。三态不可混（S604 §1.0 K2 原教义）：
    blind/unreleased 出 violations（响亮），unavailable 出 missing_inputs（点名环境），
    released 才两栏皆空。**任何一栏都不许因为「没东西可判」而空着返回。**"""
    verdict = read_release_roster(doc, repo_root)
    out: dict[str, list[str]] = {"violations": [], "missing_inputs": []}
    state = verdict["state"]
    if state not in RELEASE_ROSTER_STATES:                       # 态自己也要有牙：新态没人接 ⇒ 红
        out["violations"].append(f"ROSTER-STATE-UNKNOWN: 未知态 {state!r}，判据未接（防加态漏接）")
        return out
    libs = len(doc["libraries"])
    pins = len(doc["pins"])
    if state == "unavailable":
        out["missing_inputs"].append(
            "RELEASE-ROSTER-UNAVAILABLE: git for-each-ref 读不动"
            f"（stderr={verdict['stderr'][:160] or '空'}）——这是环境/门禁可达性问题，"
            "禁读成『本仓从未发布』")
    elif state == "blind":
        out["violations"].extend(
            f"RELEASE-ROSTER-BLIND: {p}" for p in verdict["problems"])
        out["violations"].append(
            f"RELEASE-ROSTER-BLIND 合计：在册 {libs} 库全部或部分的 tag 命名空间不可构造 ⇒ "
            "主判据恒收不到证据；打标是**打不上的**。缺的是 S1 的 id 文法与 tag 命名空间同批定稿")
    elif state == "unreleased":
        out["violations"].append(
            f"EMPTY-RELEASE-ROSTER: 带库命名空间的 annotated tag 为 0 枚（在册 {libs} 库、pins {pins} 行）"
            " ⇒ NEVER_PIN 门的主判据分母为空，今天**任何**版本都钉不进（S612 F-4 的门件级复现）。"
            "本条按延账口径落账（带到期日＋owner＋摘牌条件），**禁**改写成 skip")
    return out
```

**乙件里的两枚真册调用**（同件、互为自证，缺一就是半只眼）：

```python
def test_release_roster_state_is_announced():
    """今天的态必须是 unreleased 并响亮；将来态漂到 blind 也要当场点名。"""
    doc = render_manifest_dict_via_loader()
    verdict = read_release_roster(doc, REPO_ROOT)
    assert verdict["state"] in RELEASE_ROSTER_STATES
    out = p_release_roster_is_loud(doc, REPO_ROOT)
    if verdict["state"] != "released":
        assert out["violations"] or out["missing_inputs"], "非 released 态却两栏皆空＝静默放行（本门要禁的形）"
    else:
        assert out["violations"] == [] and out["missing_inputs"] == []


@pytest.mark.xfail(                                        # ← 延账三件齐（缺任一被延账门自己拒）
    reason="S664 空名册自锁：待 S5 发布动作（带库命名空间的 annotated tag）落地后删本标记转正。"
           "〔expiry=2026-12-24 owner=SEAT-S664 摘牌=git for-each-ref refs/tags 里出现任一 "
           "<library_id>/v<semver> 且 objecttype==tag〕",
    strict=False,
)
def test_empty_release_roster_is_still_red_today():
    doc = render_manifest_dict_via_loader()
    assert p_release_roster_is_loud(doc, REPO_ROOT)["violations"], "名册已非空 ⇒ 该摘牌了"
```

**owner 的写法（照 S661 正在复核的那条硬判据）**：延账门 `tests/test_defer_expiry_gate.py:26–27` 明写「**owner 必须是能动手的人/席**（`SEAT-*`／姓名／`@工号`）；工单号不是 owner」，并有 `RE_TICKET_POINTER`/`RE_OWNER_PLACEHOLDER` 两枚拒收（占位如「待点名」也拒）。⇒ 上面那行 `owner=SEAT-S664` 是能过判据的值；**不许**写成 `owner=F-4`／`owner=G11`／`owner=台账 #49` 一类指针（本席不重开这条，只按已定口径写）。

**与 S643 的分工（防两把尺互相顶包）**：本件只判**分母**（名册有没有、尺瞎不瞎），逐枚「这库这版发布过没有」仍由 S643 的 `never_pin_reason` 三闸判；幽灵命名空间（有人给不存在的库打了 tag）仍由 S643 §1 的反向锁判——本席探针 `R5_ghost_namespace_repo_state` 实测：**幽灵态下本件报 `released`/0 红，反向锁才是它该红的地方** ⇒ 两条**必须同时在件**，少一条就留一个空当（这正是 S643 §4 末段「一浅一深两把尺，缺一留另一把的空当」的同型）。

### 2.3 注毒自证五发（全部**实跑**，探针 `probes/s664-2-empty-roster-lock.py`）

注毒做在**输入侧**（换 id 文法／换仓的 tag 集／关一条腿），判据源码零改动 ⇒ 还原即指纹不变（§6.2）。

| 发 | 注法（输入侧） | 实测战果 | 对照（应绿/应另一种响的一半） |
|---|---|---|---|
| **P1 真仓现状** | 真仓 ＋ 点形六库 ＋ 0 pin | 态＝`unreleased`、violations **= 1 枚**（`EMPTY-RELEASE-ROSTER`，人话点名） | 未注毒即今天真值 ⇒ 这一枚就是本件存在的全部理由 |
| **P2 十张 `lib:B0x`** | 只把在册 id 换成 S646 §5.4② 建议的 `lib:B01…B10`，仓不变 | 态＝**`blind`**、violations **= 10 枚**（逐枚 `git check-ref-format REJECT refs/tags/lib:B0x/v0.0.0`） | 同仓同 tag 集下点形六库只报 `unreleased` ⇒ **证明这一态不是噪声**：换了 id 文法，主判据从「没发布」升级为「永远收不到发布的证据」 |
| **P3 关腿** | `drop_the_leg=True`（等价于删掉 `unreleased` 那半个分支） | violations **= 0** ⇒ **整门静默绿** | 反证 P1 那枚红**只由这一条腿产出**——即本件的自证腿：腿一掉，今天就没有任何件在响 |
| **P4 认真钉一次** | 真仓现状 ＋ 6 行 pin（每行 `why` 都填，即 S643 §3 的「诚实尝试」） | 态＝`unreleased`、本件 violations **仍 = 1 枚**（不随 pin 数翻倍） | 逐枚「钉不进」由 S643 主判据各报一次（S643 §3 实测 6 红）⇒ 两把尺相加 = 1＋6，**不重复计数**：本件一句"分母为空"，那件六句"这版没发布" |
| **P5 合成非空名册** | `%TEMP%` 合成仓：`core.dispatch/v1.2.3`、`lib.render/v0.4.0` 两枚 annotated ＋ `core.transport/v2.0.0` 一枚 **lightweight** | 态＝`released`、violations **= 0**；名册解析＝`{core.dispatch:[1.2.3], lib.render:[0.4.0]}`（lightweight 被 F-1 正确排除，`total_tag_objects=3`） | **正对照**（纪律 7）：证明 P1 的红不是尺瞎——同一支尺喂到有命名空间的 annotated tag 就会闭嘴 |

**五发全部实跑，无一条预测**；P3 那一发是本件最要紧的一发：**它证明"响亮"这件事今天完全挂在这一条腿上**，删掉就全场静默（S643 的六枚红要等有人真的去钉才响，而没人能钉进去）。

### 2.4 禁用的四种「天然产绿」表达（逐条给为什么今天会绿）

纪律 6 禁「天然产绿的判据」；本窗延账门自己（§0-J）又恰好对其中两类**免检**，所以必须写死名单而不是留给自觉：

| # | 形态 | 今天为什么会绿 | 替代 |
|---|---|---|---|
| 1 | `pytest.importorskip("plugins...workspace_manifest")` | 声明源不在盘 ⇒ 整件跳过、**退出码 0**；且延账门注释自述 `importorskip` ＝「条件自解，不要求日历」⇒ **全仓没有任何一件会报它** | 装载口抛 `FileNotFoundError` 并点名「缺 S1 那一步的哪件」（绕法二） |
| 2 | `if not released: return []`（或 `if not pins: return []`） | 直接把这枚门变成 S604 §2 表第一行判过罪的**空遍历绿**：遍历 0 次、报 `1 passed`，还额外把"分母为空"这句话吞掉 | `unreleased` 分支必出一句 `EMPTY-RELEASE-ROSTER`（§2.2） |
| 3 | `@pytest.mark.skipif(not PIN_ROWS, ...)` | pins 恒空是**设计内终态**（声明源 docstring 自述），这条 skip 于是永久有效；且裸 skipif 同样不要求日历 | `xfail(strict=False)` ＋ 延账三件 ⇒ 到期日当天必红（`test_defer_expiry_gate` 的射程之内） |
| 4 | 「violations 数量 ≤ 上限」型棘轮当主断言 | 今天真值是 **0 枚红**（空转），棘轮会把"0"记成合规，还把基线锁死在空转态——S643 §3 已把这种 0 定性为「空转、非合规」 | 棘轮只准用于**存量面只降不升**（AGENTS #49 的 legacy 路径基线那一族），**分母可为零**的判据一律走三态，不走棘轮 |

### 2.5 新增失效形态（本席现算）：命名空间被裸 tag 占位 ⇒ 发布动作物理打不上

L-E2b 的实跑证据（专门造的 D/F 反例仓 `%TEMP%\s664-df`，先打裸 tag `core.dispatch` 再打 `core.dispatch/v1.0.0`）：

```
fatal: cannot lock ref 'refs/tags/core.dispatch/v1.0.0': 'refs/tags/core.dispatch' exists;
cannot create 'refs/tags/core.dispatch/v1.0.0'
```

- **真仓今值**：`df_conflict_problems(六库, 真仓)` ＝ **`[]`**（本席实跑；唯一那枚 `v0.0.1-alpha.2` 不与任何库 id 同名）⇒ 这一腿今天不红，属**在册未执法**，须按 #49 口径叙述，不许写进"已防住"。
- **为什么它值得占一条腿**：它和 §0-E 那枚「tag 与分支同名 ⇒ `rev-parse` ambiguous」是**同一族病**（ref 名字空间被复用），区别是那条只让锚**不可无歧义引用**，这一条让锚**根本创建不出来**。今天撞不上，一旦哪枚库 id 起名撞了历史裸 tag（或有人反过来拿库 id 当随手 tag 名），S5 那一步会当场失败，而**失败点在 git 命令行、不在任何门里** ⇒ 若不预先内建 L-E2b，她看到的将是「我打了 tag，门还是说 unreleased」，而不是「这枚 tag 名与你的库名撞了、其实没打上」。
- **给序列的硬约束**：S656（今为骨架）那张 `check-ref-format` 表必须把「**与既有裸 tag/分支不冲突**」一并列入判据，只判 ref 文法合不合法是不够的。

## §3 交付③：起点值 `v0.0.1-beta.1` → pins 的 `bot_version` 取值路径（逐枚给今值能否取到）
done: 本节已交（§3.1–§3.3）。全部读数出自 `probes/s664-1-pins-readpoint.py`（真跑，命令在 §5）。

**先把"pins 的 `bot_version`"这句说准**（简报写的是单数，盘上是**两格三口**）：投影件顶层 `doc["bot_version"]`（S594 门件 `:216` 的被比侧）＋ 每行 `pins[i]["bot_version"]`（同一腿的比较侧）＋ 运行期读值 `_plugin_version()`（今天唯一在码的指定读点）。**这条腿只在两格都有值时才开火**（pins 今值 0 行 ⇒ 零靶，本席实跑）。

### 3.1 九条候选取数口逐枚现算

| # | 取数口 | 今值（本席实跑） | 取得到？ | 是她裁的号吗 | 落地后该怎么办 | 本席位点名的风险 |
|---|---|---|---|---|---|---|
| **V-1** | 仓根 `VERSION`（E-9 乙案真身） | 文件 **ABSENT** | ❌ | — | 由她/S652 落第一枚值 | 真身今天不存在 ⇒ 任何"读 VERSION"的读点今天一律 fail-open 到旧口 |
| **V-2** | `pyproject.toml [project].version` | **`0.1.0`** | ✅ | ❌ 不是 | 改为**投影**（生成器写、人禁手编） | `0.1.0` **恰在 `NEVER_PIN` 名册里**（S612 §4.3 的在册理由就是它）⇒ 若 E-9 不改这行，根版本自己进不了 pins |
| **V-3** | 运行期 `_plugin_version()`（`domains/ops/monitor/error_report.py:582`） | **`0.1.0`**（候选发行名 `bot-character-bots`/`bot_character_bots` 实测**双双 `PackageNotFoundError`** ⇒ 落到 pyproject 分支） | ✅ | ❌ 不是 | **与 E-9 同批改指 `VERSION`**（S652 交付①；连带 S633 那批 `parents[5]` 深度耦合） | 🔴 **巧合等值**（V-3b）：现网 venv 里有外来发行 **`WuWa-Character-Bots`，版本恰 `0.1.0`**（本席实测；S657 交付②已证该 venv `pyvenv.cfg` 指向他项目）。谁把它当"本项目旧发行名"补进候选元组，取值口就**悄悄换宿主**，而"顶层 == 运行期读值"这类等值门**仍绿**（两值逐字符相同）⇒ 新失效形态：**巧合等值掩盖宿主漂移**。防线＝等值腿必须**同时**断言宿主名（不是只断言值），见 §3.2 最后一行 |
| **V-4** | annotated tag 去 v 后的串 | `v0.0.1-alpha.2` → `split_release_tag()` 现算 **`None`** | ❌（进不了任何判据） | ❌ 不是 | 永不参与判定（S612 丁案：留史） | 它过**官方 semver**、**不过**本仓 `SEM_RE`，且在名册 ⇒ 三重排除；别把它"救活"，一救就伪造发布史 |
| **V-5** | 分支名 | `v0.0.1-alpha.2`（与 tag **同串**）；`git rev-parse` 实测仍报 `warning: refname ... is ambiguous` | ⚠ 取到但是**歧义串** | ❌ 不是 | 禁作任何取数口 | 连"可寻址的发布锚"都不是（坐实 S646 §0-8） |
| **V-6** | `domains/core/board_taxonomy.py:31 TAXONOMY_VERSION` | **`"1.0"`** | ✅ | ❌ 不是（内部代际） | 不入 pins 面 | **禁当发行号**（S646 §1.3 明令：内部规则号不当契约）；它出现在本表只是为了点名"仓里有四套互不相同的版本串" |
| **V-7** 🔴 | 声明源草稿 `BOT_VERSION: Final[str] = "0.0.0"`（`%TEMP%\s594-mirror\...:48`），**生成器 `:82` 正在读它** | 草稿态 `0.0.0`（**盘外**，仓内 ABSENT） | ⚠ 只取到草稿 | ❌ 不是 | **必须改**：生成器不读 `BOT_VERSION`，改从 E-9 真身投影（S612 §2.4 甲案，本席支持并补一条：留 `BOT_VERSION` 就是留第二真身） | 三件合一的坑在这里：`0.0.0` ∈ 名册 ⇒ **S4 落地当天，若不改这一行，等值腿（顶层 vs 运行期）直配即红**（`0.0.0` ≠ `0.1.0`，S612 §2.4 同判）——这不是 bug，是门该做的响；但如果有人为了让它绿而把 `BOT_VERSION` 手改成 `0.1.0`，就同时犯了「手编投影」与「把禁用字面量填进根版本」两样 |
| **V-8** | 每行 `pins[i]["bot_version"]` | **0 行**（`PIN_ROWS=()`） | ❌ | — | S6 才谈 | 一致性腿今天**结构上零靶** ⇒ 叙述面禁写"bot 格一致性已执法"（#49 的在册未执法口径） |
| **V-9** | 投影件顶层 `bot_version` | `docs/workspace-manifest.json` **ABSENT** | ❌ | — | S3 才谈 | L-9/L-10（投影确定性/三同体）今天**无法跑**（S612 §1.3 同判，本席复算四件全 ABSENT） |

**一句话总答（禁美化）**：九口里今天**取得到值的只有 3 口（V-2/V-3/V-7）**，V-7 还在盘外；**没有一口给出 `v0.0.1-beta.1`**。⇒ 她的 E-9 裁定在盘上的现状是**一句意图、零处真身**（S652 主件 §0–§6 全为 `done: <待填>`＝阵亡骨架，本席逐节读确认），所以 pins 面按 §1.2 只能走到 S4，S6（首批 pin 行）在 S0 之前**根本不许起念**。

> 勘误（S702，2026-09-25T18:12Z）：本总答括号内「S652 主件 §0–§6 全为 `done: <待填>`＝阵亡骨架，本席逐节读确认」为读数窗旧值，**今已过时**——现盘 S652＝495 行／57,652 B／`done: <待填>` 计数 **0**／`8e610d37bda15c27`、S656＝242 行／27,398 B／待填 **0**／`2934773c6f19ccac`，两包均已交卷（与紧随其下 S694 注「今值未变」并不矛盾：S694 复述的是 `VERSION`/`pyproject`/门件四格未落，未触及此处「两包是否骨架」的措辞，亦未随 §0-D/§6.4 已改的两格回改本句）。⚠ 只纠「两包阵亡骨架」；「E-9 裁定未落盘（VERSION ABSENT）」这一 S694 复认成立的结论**不随此改**。原句照此限定、不删。详见 `ERRATUM-SWEEP-S702.md` 第④条。

> **本节由 S694 补完（2026-09-25T18:0xZ ｜ 出处：`E9B-VERSION-FILE-LANDING-S652.md` §0-C／§2.1／§2.2／§3.1（495 行／57,652 B／sha256[:16] `8e610d37bda15c27`）＋ 本席自己复跑 `probes/s694-1-denominator-lock.py`（279 行／13,023 B／sha256[:16] `0c52ea965372d7ab`；产物 `s694-1-denominator-lock.txt` `202ebf68256f2748`，二次跑逐字节同值）；尺的字面量读自**盘外草稿** `%TEMP%\s594-mirror\plugins\bot_unified_runtime\domains\core\workspace_manifest.py:28／:394-399`（398 行／19,021 B／`512be52282f8dd1f`，T1 标注＝**副本／盘外，非本仓树**，本仓该件仍 ABSENT））**
>
> 上句总答**今值未变**（本席 18:0xZ 现算复述：`VERSION` ABSENT ⇒ V-1 仍取不到；`pyproject.toml:3` 仍 `0.1.0` ⇒ V-2 同值；`_plugin_version()` 读点未被改指 ⇒ V-3 同值；四件门件与尺子真身 `scripts/workspace_manifest_release_tags.py` 本席现算**全 ABSENT** ⇒ S1–S4 一步都没走）。要补的是**下面三格**，前两格是简报点名的两条新事实，第三格是本席现算撞出来的：
>
> 1. **「撞第一道闸」这句要加一条：闸不止一道**。本席把两把尺与两个取数体并跑（同一枚串各跑一次，产物见 `probes/s694-1-denominator-lock.txt` 的 `version_rulers_own_rerun`）：`0.0.1-beta.1` 过严尺 `SEM_RE`＝**False**（`_sem()` 抛 `ValueError: bad semver '0.0.1-beta.1'`）；把正则**换成收预发布段的放宽形**之后正则判 True，但 `_sem()` 函数体那句 `a, b, c = s.split(".")` **原样**跑同一枚串 ⇒ **`ValueError: too many values to unpack (expected 3)`**——与 S652 §0-C／§3.1「放宽形」行**逐字同值**（两席两把尺独立复现）。⇒ 结论：`SEM_RE` 与 `_sem()` **是一把尺的两半**，只放宽正则＝**把崩点从"文法红"挪成"取数期抛异常"**，更晚、更凶、且不再由判据点名。**禁**把"放宽 `SEM_RE`"当出路①的全部；同批必须连 `_sem()` 的返回形状与 L-10 三同体一起改（S652 §0 末段已点名该射程跨 S549/S612/S643 三席）。这条对本件 §0-C／§3.3 第 3 点／§4.1 附行都成立——那三处只说了"不过 `SEM_RE`"，没说"就算过了也不过取数体"。
> 2. **等值门须逐字比（禁归一化后比）**。S652 G-V3 已把这条定成尺：`literal` 形＝`VERSION.strip() == tomllib["project"]["version"]`，**含前导 `v` 逐字恒等**；推荐的 `dynamic` 形（`[project].dynamic = ["version"]` ＋ `[tool.setuptools.dynamic] version = {file = ["VERSION"]}`）**判结构不判值**——投影里还留 `version` 字面量即红（＝第二真身），`dynamic` 缺 `version` 亦红。为什么必须逐字：`packaging.Version("v0.0.1-beta.1")` 的 canonical 是 **`0.0.1b1`**，归一化一比就把 `0.0.1b1`／`v0.0.1-beta.1`／`0.0.1-BETA.1` **三串判同**，占位族与"手滑改格式"一起漏过（S652 §2.2 末段原话）。本席复算同一枚规范化：`0.0.1b1` 在**两把版本尺上都 False** ⇒ 归一化形连自家文法都不过，拿它当比较基准等于把裁定改写成机器友好的形状。
> 3. 🔴 **本席现算撞出一处不能同真的对撞（只登记、不代裁）**：本件 §3.3 第 2 点给的三行等值门里，第 2 行写的是「`pyproject[project].version == strip_release_tag_prefix(VERSION 文本)`」＝**投影去 `v`**；而 S652 G-V3 的 `literal` 形要的是**含 `v` 逐字恒等**、`dynamic` 形**根本不留值可比**。⇒ 两套写法对同一枚 `0.0.1-beta.1` 会一个判绿一个判红，**二者不可并存**。本席倾向按已定尺走（S652 是 E-9 落点 owner、其门件已真跑），但**裁定面在她与落码席**：定 `dynamic` ⇒ §3.3 第 2 行作废（改判结构）；定 `literal` ⇒ 第 2 行须改成"逐字含 v"、并把 §3.3 里那句"`pyproject` 投影去前导 `v`"一并跟随。**在两形定死之前，§3.3 那三行不得照抄落码。** 顺带一格：S652 改后的 `_plugin_version()` 明确写「`importlib.metadata` 绝不当显示值」⇒ 本席 §3.2 前置四 提的那条交叉腿 `doc["bot_version"] == _plugin_version()` **在新读点下仍然成立且更硬**（两侧都逐字含 `v`，不再隔一层 PEP 440 归一化），但被比侧必须换成"读 VERSION 的那一路"，**禁**换回 metadata 那一路。


### 3.2 E-9 乙案落地后这条链应该长成什么样（每步标前置）

```
VERSION（唯一真身，仓根一枚文件）
   ├─投影→ pyproject.toml [project].version        （生成器写；手编＝常驻门红）
   ├─投影→ docs/workspace-manifest.json 顶层 bot_version  （workspace_manifest_sync 同一支生成器）
   ├─投影→ 每行 pins[i]["bot_version"]              （生成器从同一真身填，禁手抄）
   └─改指→ _plugin_version()                        （同批；连带 S633 那批 parents[5]）
```

- **前置一（不改就造两真身）**：`workspace_manifest_sync.py:82` 那行 `"bot_version": w.BOT_VERSION` **必须改指 VERSION**（V-7）。只新建 VERSION、不改读点＝**三真身**（VERSION／pyproject／声明源常量）。
- **前置二（同批跟随）**：`_plugin_version()` 的读点与 `parents[5]` 深度耦合（S652 交付①逐处给文本；S633 那 27 枚里版本相关那几枚）；漏改则诊断卡上的版本号与账上的版本号各说各话——**而诊断卡是她唯一会在事故现场看的那一面**。
- **前置三（零改装配根）**：以上四处全在 `plugins/…/domains/ops/monitor/`、`scripts/`、仓根文件，**不碰根 `__init__.py`** ⇒ 坐标棘轮零跟随（§1.1-a 的性质在这里第二次生效）。
- 🔴 **前置四（本席新提的一条，否则等值腿会退化成自己比自己）**：改完之后，顶层 `bot_version`、每行 `pins[i]["bot_version"]` 都出自**同一个真身**，那么 S594 门件 `:216` 那条 `got["bot_version"] != doc["bot_version"]` 就成了**投影自比 ⇒ 恒真 ⇒ 天然产绿**（纪律 6 禁）。修法＝把这条腿的**被比侧换成独立读点**：`doc["bot_version"] == _plugin_version()`（V-3 那一路，走 tomllib／metadata，不经生成器），并**同时断言宿主**（读到的值来自 `VERSION` 文件这一路，不是来自某个外来发行名），两半都在才算数。这条是 §3.1 V-3b「巧合等值」的直接防线。

### 3.3 🔴 三形并存陷阱：`v0.0.1-beta.1` / `0.0.1-beta.1` / `0.0.1b1`（等值门必须说死比哪一形）

本席用三把尺并测同一批串（探针 `grammar_rulers`，实跑）：

| 串 | 官方 semver | 本仓 `SEM_RE` | PEP 440（`packaging` 实跑） | `in NEVER_PIN` |
|---|---|---|---|---|
| `v0.0.1-beta.1`（她的字面） | ❌（前导 `v`） | ❌ | ✅ 可解析 ⇒ 规范化 `0.0.1b1` | ❌ |
| `0.0.1-beta.1`（去 v） | ✅ | **❌** | ✅ ⇒ `0.0.1b1` | ❌ |
| `0.0.1b1`（规范化形） | ❌ | ❌ | ✅ ⇒ `0.0.1b1` | ❌ |
| `0.1.0`（`pyproject` 现值） | ✅ | ✅ | ✅ ⇒ `0.1.0` | **✅** |
| `0.0.1-alpha.2`（tag 去 v） | ✅ | ❌ | ✅ ⇒ `0.0.1a2` | **✅** |
| `0.2.0`（S646 推荐的每库起点） | ✅ | ✅ | ✅ ⇒ `0.2.0` | ❌ |

**三条读数的分量都在"门"上**：

1. **她这一号的字面形态三把尺互不重合**：`v0.0.1-beta.1` 过不了 semver 文法（前导 `v`），`0.0.1-beta.1` 过不了本仓 `SEM_RE`（只认三段数字），`0.0.1b1` 两个都过不了。**⇒ 等值门若不明确"比哪一形"，就会有三种各自成立、彼此不等的绿法**，其中「拿 `str(Version(x))` 规范化后再比」这一种最坏：它把她的字面 `beta.1` 悄悄洗成 `b1`，于是**任何一次想按字符串 grep 她那个号的尝试都会查无**——这是把裁定改写成机器友好的形状，属纪律 6 禁的"改了她裁定的字面"。
2. **本席给的处置（不改她的字，只加一条归一函数）**：`VERSION` 文件**存她的字面**（`v0.0.1-beta.1`）；`pyproject` 投影**去前导 `v`**（`0.0.1-beta.1`，PEP 440 合法且保留 `beta` 拼写）；投影件顶层 `bot_version` **与 `VERSION` 逐字节相等**（含 `v`）；等值门写成**一条显式的去 v 函数**并把它自己的往返锁死：

```python
def strip_release_tag_prefix(value: str) -> str:
    """只剥前导 'v'/'V' 一次，**不做** PEP 440 规范化（禁 Version()/str(Version()) 上账）。
    规范化会把她裁的 'beta.1' 洗成 'b1' ⇒ 叙述面与盘面对不上，属改字面。"""
    return value[1:] if value[:1] in ("v", "V") else value

# 等值门三行（缺一行就是留一条自比绿路）：
#   VERSION 文本 == doc["bot_version"]                       （真身 == 投影，逐字节）
#   pyproject[project].version == strip_release_tag_prefix(VERSION 文本)   （投影 == 去 v 形）
#   doc["bot_version"] == _plugin_version()                   （独立读点交叉，见 §3.2 前置四）
```

3. **`0.0.1-beta.1` 不该、也不能当任何一枚库的起点**：它过不了 `SEM_RE` ⇒ 一进 `pins`/`libraries[].version` 就在**第一道闸**红（这正是 §4 要说死的"对撞换了位置"）。根版本与库版本**两本账不同轴**（S646 §5.1 已判，本席沿用），所以她的 `v0.0.1-beta.1` 只喂 V-1/V-2/V-3 这条链，逐库起点仍走 §4 的 `0.2.0`/`0.0.0` 判定。

## §4 三件对撞在 E-9 之后的合账（S646 的 `0.1.0` 互斥是否已被她这一裁解掉）
done: 本节已交（§4.1–§4.2）。

**正面回答简报那问**：**没有解掉，而且它换了位置。** 三条理由，逐条带本席现算：

1. **不同轴**：E-9 只管**仓根**那枚版本住哪与 `pins.bot_version` 的取值（§3），逐库起点住在 `libraries[].version`（S646 §5.1 同一判，本席沿用不重证）。⇒ 她这一裁**碰不到**「库起点写 `0.1.0` 还是 `0.2.0`」那一问，S646 P-S646-1 那格仍 OPEN。
2. **换位置**：`0.1.0` 撞的是**第三闸**（字面量名册，S643 §2 P5 实测：给它造合法 tag 前两闸放行、第三闸仍红）；而她裁的 `0.0.1-beta.1` 撞的是**第一闸**（`SEM_RE` 只认三段数字，本席实跑 `grammar_rulers`）。⇒ 若有人为"配合 E-9"把库起点也写成 `0.0.1-beta.1`，它会**在更早的一道闸上红**，且红文案长得像"文法错"而不是"值被禁"——**归因会跑偏**，这条要写进 §4.2 的锁与注毒里。
3. **名册的在册证据被 E-9 抽走一枚**：S612 §4.3／S643 §1 的三枚名册**每枚都靠一条"盘上现读得到"的证据**立着，其中 `0.1.0` 那条证据逐字是「`pyproject.toml:3` 现值恰为它」（本席现算：今天确实成立）。E-9 乙落地＝那行被投影成新号 ⇒ **该枚名册的在册理由当场蒸发**。⇒ 结论：**E-9 落地那一笔必须同批重审名册**，否则名册里就留下一枚"凭空的字面量"——而一枚没有证据的字面量，正是"加了名字就算防住"那种错觉的滋生处（S612 §4.3 原话针对的形态）。

### 4.1 `NEVER_PIN` 三枚名册的在仓证据逐枚跟随表

| 名册字面量 | 今天的在册证据（本席现算） | E-9 乙落地后该证据 | 处置（推荐） |
|---|---|---|---|
| `0.0.0` | 声明源 `LIBRARY_ROWS.version` 的缺省（S604 §1.5 补条一：6/6 库全它） | **不依赖 E-9**，仍成立 | **保留**，证据锚＝声明源自身（`self:`） |
| `0.1.0` | `pyproject.toml:3` 现值逐字符 `0.1.0`（成立） | **消失**：该行被投影成新号 | **由 §4.2 那条锁逼出来、必须在 E-9 那一笔删除**：不硬留（留＝无证据的字面量），也不「以后再删」（＝把裁定改期）；也**不许**把这条换成新号——新号过不了第一闸，入册只是多一枚无判据字面量（见下一行） |
| `0.0.1-alpha.2` | 唯一 annotated tag 去 v 后的串（`git for-each-ref` 实测 `refs/tags/v0.0.1-alpha.2 tag`） | **不依赖 E-9**，仍成立 | **保留**，证据锚＝`git:refs-tags-deprefixed` |
| （附）`0.0.1-beta.1`（她裁的新号，若她顺手打成根 tag） | 今天**不成立**（VERSION 与根 tag 都还没有） | 出现后也**不过 `SEM_RE`** ⇒ 结构上进不了 pins | **禁入册**。它被第一闸永久拦下，入册只会多一枚无判据字面量 |

### 4.2 「名册条目 ↔ 在仓证据」成对锁（可粘贴，防名册退化成第二本账）

**为什么必须有这一条**：S643 §1 把名册降为第三闸（对）；S612 §4.3 给名册逐枚附了在仓证据（对）；但**证据只写在注释里**——注释不会漂、门不会红。⇒ 今天这套东西的**唯一失效方式**就是"名册改了、世界没改"或"世界改了、名册没改"，而后者恰恰是 E-9 落地那一笔的形状。所以把证据从注释升成**数据 + 腿**（AGENTS #48 的四条硬门里"登记"那一半的同一族做法）：

```python
#: 真身＝domains/core/workspace_manifest.py。每条证据是一个**可现读**的锚，不是散文。
#: 前缀语义：self:=本件内可现读的缺省族；file:=仓内某文件某键的现值；git:=refs 里去 v 后的现串。
NEVER_PIN_EVIDENCE: Final[dict[str, str]] = {
    "0.0.0": "self:LIBRARY_ROWS.version",
    "0.1.0": "file:pyproject.toml::project.version",
    "0.0.1-alpha.2": "git:v0.0.1-alpha.2",
}


def p_never_pin_evidence_live(decl, repo_root: Path) -> list[str]:
    """名册与证据表**双向差集**为空，且每条证据现读得到、值逐字相等。
    这一条同时是「E-9 落地时必须同批改名册」的自动跟随器：改了 pyproject 不改这里 ⇒ 当场红。"""
    bad: list[str] = []
    roster, evidence = set(decl.NEVER_PIN), set(decl.NEVER_PIN_EVIDENCE)
    for missing in sorted(roster - evidence):
        bad.append(f"NEVER_PIN-EVIDENCE-MISSING {missing}: 名册里有、证据表里无 ⇒ 凭空的字面量")
    for extra in sorted(evidence - roster):
        bad.append(f"NEVER_PIN-EVIDENCE-ORPHAN {extra}: 证据表里有、名册里无 ⇒ 死锚")
    for value, anchor in sorted(decl.NEVER_PIN_EVIDENCE.items()):
        kind, _, target = anchor.partition(":")
        live = _read_evidence_anchor(kind, target, decl, repo_root)   # 三形各有其取法，禁猜
        if live is None:
            bad.append(f"NEVER_PIN-EVIDENCE-DEAD {value}: 锚 {anchor} 现读无值 ⇒ 该枚该删")
        elif live != value:
            bad.append(f"NEVER_PIN-EVIDENCE-DRIFT {value}: 锚 {anchor} 现读 {live!r} ⇒ "
                       "世界已改、名册未改（同批跟随：改名册或删该枚，不许留以后再删）")
    return bad
```

**注毒三发（各杀一腿，落码席照抄即可）**：①名册塞一枚 `"9.9.9"`（无证据）⇒ 杀 `EVIDENCE-MISSING`；②把 `pyproject.toml` 现值改成 `0.0.1-beta.1` 而名册不动 ⇒ 杀 `EVIDENCE-DRIFT`（**这一发就是 E-9 落地那一笔的预演，必红**）；③删掉 `git:v0.0.1-alpha.2` 那枚 tag 的锚行（或改锚指向不存在的 ref）⇒ 杀 `EVIDENCE-DEAD`。

**判序红线（沿用 S643，不重开）**：这条锁只管**第三闸的字面量与世界的成对性**；它**绝不得**升成主判据——主判据永远是「该库该版有没有带命名空间的 annotated tag」（§2.2 分母 ＋ S643 三闸）。把这条锁当主判据，就退回了 S612 §4.1 F-2/F-3 关过的那两道门。

## §5 复跑命令簿
done: 本节已交（本席全部读数都出自下面这些命令，逐条实跑；无一条是推定）。

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
export PYTHONPYCACHEPREFIX="C:\\Users\\LancyCelestia\\AppData\\Local\\Temp\\s664-pyc"   # 必 Windows 形态
PY=../ChatBot_Runtime/venv/Scripts/python.exe
S=.superpowers/sdd/2026-09-24-central-dispatch

# ① §0/§3 全部读数（四件在位性、收集面事实、九口取值、三把文法尺、check-ref-format、正对照）
$PY -B $S/probes/s664-1-pins-readpoint.py            # 输出 JSON；本席关键读数抄录如下
#   presence：五件（三件套＋投影＋VERSION）全 false；mirror 四件全 true
#   release_tags_by_library_real = {}   ／  total_tag_objects = 1
#   positive_control_selftest = ["__selftest__","9.9.9"]  ／  positive_control_old_root_tag = null
#   pytest_testpaths_line = ['testpaths = ["tests"]'] ／ scripts_has_init = false ／ root_init_lines = 9979
#   tests_using_from_scripts_import = 15（tests 顶层 683 件）
#   bot_version_paths：V2=0.1.0 ／ V3.effective_today=0.1.0（两名 PackageNotFoundError）
#                      V3b.WuWa-Character-Bots=0.1.0 且 equals_pyproject_today=true   ← §0-G 的证据
#                      V5b_rev_parse_ambiguous=true ／ V6=1.0 ／ V7=0.0.0（盘外草稿）／ V8=0 ／ V9=null
#   grammar_rulers：0.0.1-beta.1 official=True project_SEM_RE=False in_NEVER_PIN=False；
#                  0.0.1b1 三尺全 False；0.1.0/0.0.1-alpha.2/0.0.0 在名册
#   check_ref_format：core.dispatch/v1.0.0=OK、lib:B01/v1.0.0=REJECT、B01、lib_B01、chatbot-repo-*、
#                    v0.0.1-beta.1、bot/v0.0.1-beta.1 全 OK

# ② §2 判据本体真跑（四态 + 五发注毒，全部实跑；合成仓只建在 %TEMP%）
$PY -B $S/probes/s664-2-empty-roster-lock.py
#   R0 真仓点形六库    => state=unreleased, violations=1     ← 今天该响的那一枚
#   R1 真仓十张 lib:B0x => state=blind,     violations=10     ← §2.3 P2 的 headline
#   R3 关腿            => violations=0                       ← §2.3 P3：腿一掉全场静默
#   R4 合成带命名空间仓 => state=released,  violations=0, 名册={core.dispatch:[1.2.3], lib.render:[0.4.0]}
#   R5 幽灵命名空间     => state=released（本件不报，该红的是 S643 反向锁）
#   unavailable_probe  => state=unavailable（WinError 267，禁当未发布）
#   LE2b 真仓=[]（今天不响）；LE2b 反例仓=1 枚（D/F 冲突实测成立）

# ③ 九词（＋两词）分母：本席窗复跑，全部 0
for w in workspace_manifest library_id requires_min requires_max_exclusive pinned_version \
         breaking_events bot_version pins _CONTRACT_VERSION NEVER_PIN release_tags_by_library; do
  printf "%-26s %s\n" "$w" "$(grep -rnE --include=*.py "\b${w}\b" plugins scripts tests | wc -l)"; done

# ④ 发布面与三形对照（只读）
git for-each-ref refs/tags --format='%(refname) %(objecttype)'      # 1 行：refs/tags/v0.0.1-alpha.2 tag
git rev-parse v0.0.1-alpha.2                                        # warning: refname … is ambiguous
grep -nE '^\s*version\s*=' pyproject.toml | head -1                  # 3:version = "0.1.0"
test -f VERSION && echo EXISTS || echo ABSENT                       # ABSENT

# ⑤ D/F 冲突反例（§2.5，本席实跑；仓在 %TEMP%，不碰真仓）
cd "$TEMP/s664-df" && git init -q . && git commit -q --allow-empty -m seed \
  && git tag -a core.dispatch -m one \
  && git tag -a core.dispatch/v1.0.0 -m two
#   fatal: cannot lock ref 'refs/tags/core.dispatch/v1.0.0':
#          'refs/tags/core.dispatch' exists; cannot create 'refs/tags/core.dispatch/v1.0.0'

# ⑥ PEP 440 规范化对照（§3.3，实测非推定；packaging 在场）
$PY -B -c "from packaging.version import Version; \
print([str(Version(s)) for s in ('v0.0.1-beta.1','0.0.1-beta.1','0.0.1b1')])"     # 全部 -> 0.0.1b1
```

**读数成立条件**：HEAD `5cc6832`、脏项 `git status --porcelain` 本席窗末现算 **913** 枚（S646 窗为 886 ⇒ 只传 Δ）、本席窗 UTC **15:29:47Z–15:49:05Z**。⚠ **跨窗只传 Δ 不比大小**；`dev.ps1`/根件行数在他窗与本席之间仍在漂（`root_init_lines` 本席读 9,979）。

**复跑一致性（本席自己二次跑，15:49—15:50Z）**：两探针二次执行 ⇒ 关键读数**逐条同值**（五件 presence 全 false、`release_tags_by_library_real={}`、V-3 有效值 `0.1.0`、`0.0.1-beta.1` 三把尺 True/False/`0.0.1b1`、R0=`unreleased`／R1=`blind`／R3＝0 红／R4=`released`、L-E2b 真仓 `[]` 与反例仓 1 枚），探针文件 sha256[:16] 不变（`13efa60e7922c896`／`524e39b70aaf0c19`）——注毒全做在输入侧，故"还原等值"这件事在这里由指纹不变自动成立（与 S643 §6.3 同一自证式）。

**未跑清单（诚实边界）**：①**全量 `dev.ps1 -Task test` 未跑**（并发写入窗未关＋本机两次 OOM 史，纪律 2）；②`lint`/`typecheck`/`runtime-layout` 三门禁未跑（同上，且本席零改生产件、无门禁跟随面）；③§2.2/§4.2 的判据**只作为纯函数与合成仓实跑**，未作为 pytest 件执行（落 `tests/` 须与 §1.2 的 S1/S4 同笔，本席红线不落码）；④§4.2 的三发注毒**未实跑**——它需要一个读盘版 `_read_evidence_anchor()`（三形取法），本席只交文本，与之分开记（P-S664-2）。

## §6 卫生账 / 红线自证 / PARKED / 安全登记（规则 11）
done: 本节已交。

### 6.1 写面（全在席目录，`.superpowers/` 已 gitignore）
`PINS-READPOINT-AND-EMPTY-LOCK-S664.md`（本件）＋ `probes/s664-1-pins-readpoint.py`（sha256[:16] **`13efa60e7922c896`**，8,905 B）＋ `probes/s664-2-empty-roster-lock.py`（**`524e39b70aaf0c19`**，8,580 B）。临时件全在 `%TEMP%`：`s664-pyc`、`s664-syn-*`（三枚合成仓）、`s664-df`（D/F 反例仓）、`s664-probe{1,2}.json/.err`。
**未改** `plugins/`、`scripts/`、`tests/`、`docs/`、`config.py`、`pyproject.toml`、根 `__init__.py`、`chatbot-tasks.json` 任一字节（全程只用 Read/Grep 与只读 python＋只读 git）。

### 6.2 红线逐条自证
- **未动真仓 git 状态**：`git tag`／`commit` 的 cwd 一律 `%TEMP%\s664-syn-*`／`s664-df`；席终复核真仓 `git for-each-ref refs/tags` 仍**只有 1 行**、`git branch --show-current` 仍 `v0.0.1-alpha.2`、HEAD 仍 `5cc6832`。
- **未读 `.env`**；**未**拨闸／改配置／装包／重启或杀进程／`git` 写／删垫片／派新席／外部上传；**未跑**全量套件。
- **直跑 python 一律** `-B` ＋ `PYTHONDONTWRITEBYTECODE=1` ＋ 仓外 `PYTHONPYCACHEPREFIX`（Windows 形态）＋ `BOT_AUTOSYNC=0`；**探针从不 `import plugins.*`／`import scripts.*`**（§3.1 的 V-2/V-3/V-6 全按文件文本读或按发行元数据查，避免触装配根与树内落字节码）。
- 判据注毒做在**输入侧**（换 id 文法／换仓 tag 集／关一条腿），判据源码零改动 ⇒ 探针指纹全程不变（复跑 §5-①②＋`sha256sum` 两行即可核对）。

### 6.3 树卫生自查（含本席自己踩到的两次旧坑，照实记）
1. **现算全树 `.pyc` ＝ 340 枚**（`os.walk`，排除 `.git`/`.superpowers`），其中 `scripts/__pycache__/` **4 枚 mtime 15:35:12Z 落本席窗内**——模块集恰为 `board_doc_sync`/`doc_sync`/`doc_template_sync`/`physical_placement_census`，**与 S612 §6.7、S643 §6.5、S646 §7.2 三度记录的并发 census 指纹逐字同名**。本席探针的 import 图只有标准库＋`subprocess`（＋一次 `packaging`，装在 venv site-packages、不在仓树），**结构上不可能是这四枚** ⇒ 归属＝并发写入窗（另一台带全树 doc_sync/census 的进程）。
   **席终复跑又添一条硬证据（照实记，不改判）**：全树计数从 340 涨到 **341**，而**最新的四枚**mtime 为 `15:45:26Z`/`15:47:16Z`（正落本席两次复跑之间），文件是 `plugins/.../domains/files/sender/restricted_runner`、`plugins/.../domains/chat_reply/capabilities/poke` 一类——**本席全程从未 import 过任何 `plugins.*`**，这两枚模块也不在本席任何判据的射程内 ⇒ 计数在动、动脚不是本席的。按台账 #50 口径**只登记、不清理、不代搬**（搬运会撞在飞写者、且非本席产物；安静窗按铁律 6 处置）。本席自有足迹＝**零**：`probes/` 目录 `rglob('__pycache__')` 现算 **`[]`**，两探针全程 `-B`。
2. **本席自己踩到 S604 那条坑一次**：一次 `$PY -B -c` 里用 `pathlib.Path('$TEMP/…')` —— bash 把 `$TEMP` 展开成 POSIX 形态 `/tmp/...`，Windows 解释器读成 `\tmp\...` ⇒ `FileNotFoundError`。⇒ 与 S604 §5「`PYTHONPYCACHEPREFIX` 应写死 `cygpath -w` 且紧跟一次自证」同族，**这条教训第三次被不同席位踩到**：凡"把 shell 变量喂给 Windows 解释器"都要显式 `cygpath -w` 或干脆写死 Windows 绝对路径（本席 §5 命令簿已按后者写死）。
3. **本席还踩到一次 GBK 崩**：`print(repr(含 emoji 的行))` 在未钉 `PYTHONIOENCODING` 时抛 `UnicodeEncodeError: 'gbk' codec can't encode '\u2705'` ——正是台账 #47 记的那族「未钉 encoding 只要按铁律 `export PYTHONIOENCODING=utf-8` 就必现」的镜像形态（那次是 subprocess 解码、这次是本进程编码）。**改法＝带该变量跑**（§5 已带），**不改任何生产件**。

### 6.4 PARKED（未做／做不了／等她，逐条带坐标）
| # | 事项 | 停在这里的原因 |
|---|---|---|
| P-S664-1 | §2.2 判据**未落 `tests/`**、尺子**未沉 `scripts/workspace_manifest_release_tags.py`** | 红线（不落码）；且它必须与声明源同笔（§1.4 甲件），单独进 `tests/` 就是 §1.3 机制段那枚整树收集红 |
| P-S664-2 | §4.2 的 `_read_evidence_anchor()` 三形取法（`self:`/`file:`/`git:`）**未实现**，其三发注毒因此**未实跑** | 需要读盘版取法才有靶；本件与 §2.3 的实跑注毒**分开记账**，不混称"全部实跑" |
| P-S664-3 | 🔴 **库 id 文法与 tag 命名空间谁迁就谁**（本席 §2.3 P2 实测十张 `lib:B0x` ⇒ `blind`） | 命名法是她的裁定面（E-7/E-9/S659 名册定稿）。本席只交判据与实测，**不替她定 id 形状**；但这条必须在 S659 定稿**之前**入册，否则 S5 那一步是白工 |
| P-S664-4 | 每库起点 `0.2.0` vs `0.1.0` 仍未裁（S646 P-S646-1 不撤） | E-9 裁的是**仓根**（§4 三句），碰不到这一问；本席不并入、不宣布已解 |
| P-S664-5 | 三件套唯一落盘处仍是 `%TEMP%\s594-mirror`（本席复核四件在盘），**无 git 回滚位** | S612 P-S612-1 至今未解。搬进仓＝落码（越本席红线）；建议主代理/她立刻备份进 `probes/` |
| P-S664-6 | S0（E-9 乙落盘）与 S5（命名空间定稿）两包的**施工文本缺席**：`E9B-VERSION-FILE-LANDING-S652.md`、`S639-BLOCKS-DISPOSED-S656.md` 均为 `done: <待填>` 骨架（本席逐节读确认） | 本席因此**只能给序列与前置**，给不出"改哪一行 VERSION 读点"的文件级补丁文本（那是 S652 交付①/②的射程）；`git check-ref-format` 与 D/F 两格本席已代补实跑数据（§1.2 的 S5 行、§2.5），可直接贴进 S656 §1。<br>**本节由 S694 补完（2026-09-25T18:1xZ ｜ 出处：`BRIEFS-250925-DD.md` §S694 行；三件在册件 `S639-BLOCKS-DISPOSED-S656.md` `2934773c6f19ccac`／`FIRST-LIBRARY-ROSTER-FINAL-S659.md` `58e02fb5110b2b13`／`E9B-VERSION-FILE-LANDING-S652.md` `8e610d37bda15c27`；本席探针 `probes/s694-1-denominator-lock.py` `0c52ea965372d7ab`；T1 树身份＝本仓根，读数无一条来自他树或副本，唯一盘外件已就地标明）**：①**本条停摆原因已过期**——两包今均交卷（S652 495 行、S656 242 行），S0 的施工文本与 S5 的命名空间实跑表都在盘上（本席 0-D 行末已代补跟随）。②**但不摘牌**，剩下的三格是真格：🔴 验收席 `E9B-PATCH-REALRUN-S685.md` 今仍骨架（本席现算 **12 处 `待填`**）⇒ S652 那 19 行 diff **至今没人在副本上真打过一次**；三件套唯一落盘处仍是 `%TEMP%\s594-mirror`（本席现算 mirror `workspace_manifest.py` 在盘＝`512be52282f8dd1f`，仓内 `plugins/.../domains/core/workspace_manifest.py`／`scripts/workspace_manifest_sync.py`／`docs/workspace-manifest.json`／`VERSION` **四件全 ABSENT**）；尺子真身 `scripts/workspace_manifest_release_tags.py` 与甲件／乙件／门件三件测试件本席现算**全 ABSENT** ⇒ §1.2 的 S1–S4 一步未走。③🔴 **命名空间裁定（`slug`，出处 `SEAT-MAIN.md` 15:4xZ 段，件指纹 `0d00dd721043ee07`）落地后，本件 §2.2 那把锁自己变成新病，两格必须跟随**：<br>**(a) `blind` 腿今天会咬到自己**。§2.2 的 `namespace_roundtrip_problems()` 拿 **`library_id` 直造 tag 名**（`refs/tags/{library_id}/v0.0.0`），而裁定之后 `library_id` 是**账本身份**（`lib:B01`…`lib:workspace-dev`）、tag token 是 **`slug`**（`ingress-protocol`…）＝两个不同形状，中间隔一支派生函数（S656 §2 唯一那支，禁手抄对照表）。本席按原语义把 16 行名册喂进去 ⇒ **`state=blind`、16 枚红**（双尺同判：逐枚 `git check-ref-format` 16 REJECT ∥ 独立实现的规则尺 16 REJECT，`agree=true`；15 枚 slug token 两尺全 OK）。**最要紧那一枚是 `lib:workspace-dev`**：S659 §2 第 16 行标「**伪库，不发版本、不建 tag**」⇒ 它**永远**不会有 tag，被这条腿判成"尺瞎"就是把**设计内的不入宇宙**读成**设计外的病**；她哪怕把 15 枚 slug tag 全打对，本件仍常年红 1 枚，而真正该响的那一枚被噪声掩掉。**修法**：判据输入换 `tag_namespace(library_id)` 的**派生 token**，且"这行进不进 tag 宇宙"必须是**名册里的声明字段**（如 `releases_version` 或 `namespace is None`），**禁**从 id 的形状猜（`startswith("lib:")` 那种写法＝本席 §0-G 点名的"名字尺当语义尺"换了个马甲）；派生不出来才叫真 `blind`。<br>**(b) 🔴 分母为 0 ⇒ 判据恒真（本席实测到的洞，正是简报点名要挡的那条）**。§2.2 的判序是 `released = release_tags_by_library(repo_root)` 之后 `state = "released" if released else "unreleased"`——`released` 是**全仓 tag 的解析结果**，与在册名册**没有交集约束**。本席喂一枚幽灵命名空间 tag（`refs/tags/not-in-roster/v9.9.9`）⇒ **`state=released`、violations = 0**，而此刻**真分母（可联表行数）＝ 0**：主判据逐枚判 pin 时遍历 0 行，"全部合规"绿得一句真话没说。乙件那条 `else: assert out["violations"] == [] and out["missing_inputs"] == []` 在这种输入下**当场判绿**（本席实跑）。⇒ §2.1 把「空」拆四态时**漏了第五态**：名册非空、tag 非空，但**两者交集为空**。本席 §2.3 的 P5 与 §5 复跑簿的 `R5 幽灵命名空间` 一行当时摸到了它，却把处置**交给 S643 的反向锁**——那等于把**本件分母的生死挂在别人的判据上**；今天那件未与 S4 同笔落地（现算 ABSENT），本件就恒绿。**修法三腿（可粘贴执行体＝本席探针里的 `judgement_v2()`）**：腿一 `len(roster) == 0` ⇒ 新态 **`denominator_zero`** 并响亮（**禁并入 `unreleased`**：那是把"声明源被抹光"读成"没发布"，正是本席 §0-I 引的 CM-P-9 原病）；腿二 `joinable = {名册派生 token} ∩ {tag 解析键}`，**`state == released` 只在 `len(joinable) >= 1` 时被允许**，交集外的 tag 逐枚点名成 `RELEASE-ROSTER-GHOST-NAMESPACE`；腿三 不入 tag 宇宙的行**必须显式声明**，且"声明不发版本却带 namespace"⇒ 红（两本账打架）。**实测战果**：名册抹光／幽灵 only／lightweight-only（`objecttype=commit` 被 F-1 正确排除）三形**各 1 枚红**；喂一枚真 `ingress-protocol/v0.2.0` ⇒ `released`、`joinable=1`、**0 红**（正对照，纪律 7）。<br>**(c) 配套断言禁令（给 §2.4 那张表追加第 5 行）**：本族任何判据**禁**以 `all(...)`／`violations == []`／`len(红) <= 上限` 作**唯一**断言；同一测试体内必须先有一条**存在性正断言**（`assert len(denominator) >= 1`，写成 `assert` 而非 `if`），否则它就是恒真式。§2.2 末尾那枚 `xfail(strict=False)` 只兜"今天分母为 0"，**不兜**"将来分母又变 0 却被判绿" ⇒ 摘牌条件那句须补「**且 `joinable` 非空**」才闭合。<br>④**本席自己的一记假尺照实记**：首版把 `git check-ref-format --stdin` 当第二把尺，实核对全合法输入也回 **rc=129（usage error）**——该形在本 git 版本（`2.52.0.windows.1`）根本不被支持 ⇒ 那把尺对任何输入都"非 0"，**能把"全合法"读成"有非法"**。已整段删除、换成独立实现的规则尺并自带正负对照（`legal_control=true`／`colon_control=false`，与 git 同判）。教训＝**第二把尺必须先对已知输入各跑一发才准叫互证**，与 T3 的"两把独立尺"是同一条规矩的前半句。⑤**复跑**（只读，零 git 写、零生产写）：`cd 本仓根` ＋ `export BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=<Windows 形态盘外目录>` ＋ `../ChatBot_Runtime/venv/Scripts/python.exe -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s694-1-denominator-lock.py`（产物同名 `.txt`，本席两次跑逐字节同值）。 |
| P-S664-7 | 全量四门禁与真机验收未做 | 并发写入窗未关（脏项 913）＋须她提权重启；本席零生产改动，无重启面 |

### 6.5 安全登记（规则 11）
本席全程在工具结果、在册件正文（S604/S612/S643/S646 四件主件、简报 CZ/DA、`A3-EXPIRY-PASTE-PACKAGE.md`、`E9B-…S652.md`/`S639-…S656.md` 两骨架、声明源与生成器镜像正文、`scripts/*.py` 生产件正文、合成仓 git 输出、`MEMORY.md` 索引行）里**未遇到**任何要求执行动作的祈使句载荷（读到的都是**关于**注入的报告文字，如台账 #53 席 C 那条 OPEN 与 AGENTS 规则 11 本体）——一律当**数据**处置：未执行、未换工具、未重做已生效的写、未停手。**命中数 0**，故无消毒载荷需入册。**P-56 与 #53 两案 OPEN，本席不撤、不并案、不静默结案。** 环境侧唯一异常是 §6.3 第 2/3 条（`$TEMP` 形态与 GBK 编码），已定位为**工具语义**、非注入，且**本席自己的读数被它挡过一次**（那次 `FileNotFoundError` 发生在读探针 JSON 输出上，未污染任何判据读数——重跑用 Windows 绝对路径后取数一致）。
