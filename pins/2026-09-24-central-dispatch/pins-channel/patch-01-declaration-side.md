# patch-01 —— 仓内声明源侧增量（适配轴三面意图：策略／例外／豁免）

**落点文件（落地时）**：`plugins/bot_unified_runtime/domains/core/workspace_manifest.py`
——即 S594 设计、S612 实跑过十条锁、S715 按 D-2甲 改形、S727 件1 给出可粘贴全文的那枚**已指名真身**。
本增量＝在其上**加**三面声明，不新建第二件声明源。
（若三件套最终尚未入库而先落本增量 ⇒ 视为「四件同笔」清单的一部分，见报告 §四 前置 A1。）

**家规对齐（逐条）**
- 只声明**不可派生**的新事实：区间策略、pair 级例外、显式豁免。边集本身与逐对 min/max 由
  生成器现算＋派生——**逐对行手抄进真身＝门红**（S715 在册：`import-ast` 边手填即红；
  本仓「一册一轴」「册只存投影」两门在先例）。
- 只声明数据、纯函数，禁 import 包内模块（board_taxonomy / capability_manifest / S727 件1 同族哲学）。
- 文法四处同批（S715 §1.2-④-①）：`SLUG_RE` 认连字符（S727 件1 已改）；名册、生成器、门同批改，
  不同批＝收集期即红。

## 可粘贴块（接在 S727 件1 `PROTOCOL_EDGES` 之后）

```python
# —— 适配轴（S764）：库↔库「依赖谁的哪个区间」的唯一可编面 ——
# 教义：这里只写 ①区间策略 ②pair 级例外 ③显式豁免 三面。
#      边集（哪 52 对）与逐对缺省区间**都不在此手抄**——生成器按 AST 现算＋策略派生，
#      手抄＝第二真身＝门红（p_adapt_ledger_matches_ast 的 STALE/MISS 双向差集执法）。

#: 区间策略：键 "consumer->provider" 或 "*"（缺省）；值表外＝生成期拒（同 S727 RANGE_POLICY 教义）。
#: same-major := [提供方①现版, 下一 major)   ——现算今值＝52 对全部落这一策略，例外零枚。
EDGE_RANGE_POLICY: Final[dict[str, str]] = {"*": "same-major"}

#: pair 级例外：偏离缺省才写，逐枚必带 why（无 why＝ADAPT-OVERRIDE-NOWHY 红，S612 N-H 同族）；
#: 指向不存在的边＝ADAPT-OVERRIDE-ORPHAN 红。首拍＝空。
REQUIRE_OVERRIDES: Final[tuple[dict[str, str], ...]] = ()

#: 显式「这枚边今天不钉」＝带到期日的豁免（why+expires 必填；approvals 通道同型：
#: 带证据与到期日重录，只准降不准升）。首拍＝空。
ADAPT_WAIVERS: Final[tuple[dict[str, str], ...]] = ()
```

## 求值口唯一真身（落地时收进本件，门与生成器都 import 它）

`pins-channel/patch-03-gate-legs.py::expected_range` 是可运行规格；落仓时该函数**搬家到声明源**，
门件与生成器各自 import——**同一份语义、一份代码**，禁三处各写一份算法（那才是第二真身）。
门件侧保留的独立物只有：②↔真身的复算腿、AST 现算尺（独立实现，与普查尺**两把读数分家**
才抓得到尺瞎——cross_validate 先例；这不是第二真身，是第二把**验证尺**）。

## 谁读这三面（无读点即不写）

| 面 | 运行期读者 | 门禁期读者 | 治理期读者 |
|---|---|---|---|
| `EDGE_RANGE_POLICY` | 无（治理元数据，见报告 §五 诚实边界） | `scripts/workspace_manifest_sync.py`（填②逐行区间）＋门复算 | 库工厂（经②投影写① `depends`） |
| `REQUIRE_OVERRIDES` | 同上 | 门 OVERRIDE-* 两腿＋生成器 | 同上 |
| `ADAPT_WAIVERS` | 同上 | 门 MISS 豁免项＋WAIVED-EXPIRED＋恒等式 | 审计板「断开度」行（S759 第 59 行方向） |

## 落地差异与同批跟随

1. 四件同批：真身＋生成器＋门＋②投影件（S612 §3.2 P1–P5 清单原样适用；P6 两枚未跟踪接缝测试
   只在并入 S594 候选 full-form 时才是前置，S727 mini 形不吃 interfaces 表——本增量为 S727 形）。
2. `@schema` 维持 `chatbot.workspace-manifest/1`（S727 件1 三同体；加 cross_library_edges 已是
   该 schema 在册字段——S715 §2.2 新增件，本增量只加行的区间列，不升代）。
3. `chatbot-tasks.json` 的 `sync` 列须收 `workspace_manifest_sync.py --write/--check` 两式
   （S612 P4：`command_catalog --check` 同款不对称先例，别再复刻）。
