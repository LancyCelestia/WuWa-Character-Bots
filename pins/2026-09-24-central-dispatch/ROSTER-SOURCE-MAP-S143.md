# ROSTER-SOURCE-MAP —— 板内 20 把量具各自从哪儿拿「库座名册」（主代理现算，2026-09-26 13:3xZ）

现算尺：`python -B -c` 逐件读 `probes/s0-main-goal-audit.py:1-95` 抽 `alias -> file` 20 条，
再对每把尺的正文查三个标记：`parse_libs|LIBRARY_TAXONOMY|iter_release_libs`（＝**声明源真身**，
2026-09-26 ③ 落码后唯一的库轴真身）／`NONBOARD_ROOTS`（＝**根形第二册**，住在 `probes/s715-deps.py`，
S865 那一形）／两册皆无。三态判据是文本在场，不是"跑起来读到"——所以下表是**嫌疑清单**，
每一格要改之前得先把那把尺直跑一次看它自己打印几个库座。

| 量具 alias | 文件 | 读声明源真身 | 读根形第二册 | 判 |
|---|---|---|---|---|
| surface | s0-main-lib-api-surface.py | 是 | 否 | 单一真身 |
| census | s0-main-unowned-edge-ranker.py | 是 | 否 | 单一真身（#130 今日修完） |
| kinds | s0-main-mandate-kinds-coverage.py | 是 | 否 | 单一真身 |
| adapt | s805-adaptation-cell.py | 是 | 否 | 单一真身 |
| drift | s0-main-lib-drift-checker.py | 是 | 否 | 单一真身 |
| syncverify | s0-main-lib-sync-verify.py | 是 | 否 | 单一真身 |
| severance | s759-severance.py | 是 | **是** | 两册并读 ⇒ 必须自带互证（它有 roster_fp 互锁） |
| decls | s759-decl-sources.py | 是 | **是** | 两册并读（同上，#121 的 pin 腿在此） |
| crossedge | s811-cross-edge-ruler.py | 是 | **是** | 两册并读 |
| **rangepol** | s833-range-policy.py | **否** | 是 | 🔴 只读第二册 ⇒ 板上那格「显式 0/15」的分母来自根形册 |
| **buildlib** | s809-buildlib-per-lib.py | **否** | 是 | 🔴 同上（逐座建库腿） |
| **noncode** | s759-noncode.py | 否 | 否 | 🔴 两册都不读（板块轴 alone） |
| outside | s784-outside-placement.py | 否 | 否 | 板块轴 alone（物理归位面，可能本就不该按库座分母） |
| exhaust | s806-exhaustiveness-cell.py | 否 | 否 | 板块轴 alone |
| ready | s0-main-lib-readiness.py | 否 | 否 | 它数的是**盘上 git 库**（`--expect` 由板喂名册数）⇒ 有外部输入腿，可接受 |
| version / behind / tamper / seam / spec | 四件＋版本轴 | 否 | 否 | 按盘上库目录遍历，名册由外部旗标约束（`--expect`／板内 built 派生） |

## 三条结论（可直接引用）

1. **20 把里 8 把读今天的唯一真身；2 把只读根形第二册（`rangepol`／`buildlib`）；3 把两册并读
   （`severance`／`decls`／`crossedge`，这三把带 `roster_fp` 互锁）；1 把两册都不读且无外接（`noncode`）；
   余 6 把按盘上库目录遍历、名册由板用 `--expect`/built 外接。**
   名册 15 座这件事在板内**不是全局事实**，只是部分尺的事实。
2. **两册并读的三把（severance／decls／crossedge）自带 `roster_fp` 互锁**——它们能在两册不一致时报出来；
   只读第二册的两把（`rangepol`／`buildlib`）**没有任何东西会发现根形册与声明源漂移**。
   S888 的 O1（根形）vs O2（成员形）实测就是两个世界：双认领 15 vs 5、TIE 10 vs 0。
3. 板对"盘上遍历型"尺（ready／version／behind／tamper）用 `--expect`/built 派生喂分母，这类**不是盲区、是外接**；
   区别要写清，否则下次有人拿"它不读名册"当缺陷报。

## 待办（#131，分两类，别混一刀）

- **A 类（真缺陷）**：`s833-range-policy.py`、`s809-buildlib-per-lib.py` 的分母改吃声明源真身（`parse_libs`），
  根形册降为交叉核对并打印 `divergent=`；`s759-noncode.py` 先直跑确认它该不该有库座分母，再决定改或写"不适用"。
- **B 类（写明即可）**：盘上遍历型 5 把，各补一行"名册由外部 `--expect` 喂"的注释，免得反复被当漏读报。
- 每改一把都要：直跑取前后读数 → `--repin` → 复跑板；外锚在 H-2 一次处理，不逐把偷偷重签。

## 追记〔13:4xZ〕直跑核过：**今天两本册的座数相等，我上文那句"分母错"说过头了**

`python -B probes/s833-range-policy.py` ⇒ `per=15 declared=0 missing=15`；
`python -B probes/s809-buildlib-per-lib.py` ⇒ `per=15`。
⇒ 这两把**今天的分母是对的 15**（根形册 `NONBOARD_ROOTS` 恰有 5 键，10＋5＝15，与声明源巧合相等）。
所以缺陷不是"现在读数错"，而是**没有任何东西会在两本册漂开时发现**——
`③名册`落码之前根形册就是唯一账，落码之后它变成"可能过期但不报错的第二真身"。
下文 A 类那一格据此降级：**改吃声明源真身的理由＝消第二真身＋加漂移腿，不是修一个错数**。
`s759-noncode.py` 本次未取到分母读数（grep 无命中），**本 tick 不判它**，留给直跑取证。

诚实边界同上：这次是"跑起来读到几个库座"，与上文的"文本里读没读"是两条判据，各管各的。

## 追记二〔13:5xZ〕`s759-noncode` 直跑过了：**它不该有库座分母，A 类从 3 项缩到 2 项**

`python -B probes/s759-noncode.py` ⇒ `非代码面覆盖＝794/1446（类目有认领 5/5；类目有直接声明 4/5；幽灵合计 0）`、
`BOARD NC covered=794 universe=1446 cats_nonzero=5 cats_total=5 cats_direct=4`、`VERDICT: COVERED-PARTIAL`、rc=0。
⇒ 它的宇宙是**非代码面 1446 枚／5 个类目**，与"库座"无关：两册都不读是**设计如此**，不是漏读。
本项改判 B 类（写明即可：给它补一行"分母＝非代码类目，不随库轴名册变化"的注释，免下次又被当缺陷报）。
A 类剩两项＝`s833-range-policy`、`s809-buildlib-per-lib`，且按追记一的降级——**修因是消第二真身，不是修错数**。
