# ANCHOR-8TO7-VERIFY — 「未 wired 锚账 8→7」独立复核（席位 S333，全程只读）

复核对象：主代理按 S317 结论改动的 `tests/test_capability_manifest_gate.py`
（字面量 8→7、行内 7 枚名册、带 UTC 戳的核账行、"wired≠线上有流量"口径钉）。
结论一句话：**自证成立、未用改判据凑数；但名册的"成员身份"今天没有任何代码在执法，另有两处叙述件未跟随。**

全证据与 traceback 原文在 `SEAT-S333.md` §2–§8；探针 `probes/s333-live-measure.py`、`probes/s333-poison-and-sets.py`。

## 一、四项待查的裁决

| # | 待查 | 裁决 | 尺身份（现算，非转述） |
|---|---|---|---|
| ① | 现算是否仍 7、集是否等 | **成立** | 我自己跑普查件＋自己按 `state≠wired` 派生＝7，与 `declared_unwired_rows()[0]`、与门件 `:136-138` 行内名册**三集逐枚等**；census 自报 `generated_at_utc=2026-09-25T04:18:37Z`；分母 `scanned=20`＝`DECLARED_SCAN_FLOOR`、`blind=[]`、roster 100＝地板 ⇒ 非缩面 |
| ② | 有没有改判据凑数 | **没有**（机械证明） | `creation.image.generate` 行 `execution_declared=False`／`adapter=None`／`seam=0`／`offseam=0`／`generic=0` ⇒ 按 `central_seam_census.py:666/674` 的三来源判据，它的 `wired` **只能**来自 `invoke_sites` 那一条，而该条证据在盘（`domains/creation/image/routes.py:166-174`，mtime `09-24T20:03Z`；挂载 `api/v1.py:245-259`）。采集规则 `:386` 把测试面单独归 `tests_evidence`、**不计 wired**——这恰是"放宽"最容易发生的一格，今天没动 |
| ③ | 四处同批齐不齐／有无第五处 | **四处齐；叙述面两处未跟** | 四处＝门件常量＋行内名册／真身册 `DIRECT_CALLSITES_ZERO_ROSTER`（7 枚，已摘该枚＋`:756` 跟随句）／`test_descriptor_wiredness_ledger.py`（WIRED 有该枚、NOT_WIRED 已摘、`GAP_CEILING=93==len(GENERIC)10+len(NOT_WIRED)83`、四把锁进程内全绿）／注毒用例硬编码集合（`:620-625`）。第五处在代码与生成物面**没有**（两个消费脚本都活读常量，无缓存件带值）；**有**的是 `AGENTS.md:212` 与 `docs/HANDBOOK.md:2685`（见 §三） |
| ④ | 反向毒必红在哪句 | **两把并列红** | 真出现第 8 枚 ⇒ 第一现场 `test_capability_manifest_gate.py:672`（`棘轮 DECLARED_UNWIRED_BASELINE=7（ceiling）现算 8 超过上限…`，经 `:802` 进入）＋ `test_capability_manifest_ratchet_direction.py:361`（`登记 7、此刻现算 8（差 +1）＝账与实况脱钩`）。全部在**进程内内存注入**做，未改任何盘上件 |

## 二、主代理没问、但顺手量出来的两格

1. **置换测得住，但只测得住"零直呼点"那一侧。** 摘一枚＋进一枚（枚数仍 7）时 ③b/②**全绿**，红的是三把成员锁
   `gate:879`／`gate:892`／`gate:1083`。这三把之所以能抓住，是因为**今天**"unwired 集恰＝现算零直呼点集"。
   而这条恒等式本身**没有任何断言在执法**（我全件枚举）。
   残存说谎变体＝进来的那枚带非零直呼点（census `state=="generic"`，即走根泛型执行器）：
   腿③（`gate:781-789`）只禁止 `offseam_sites`，`generic_sites` **没有"必须为空"的腿**。
   ⚠ 这一格我**只做到结构推定、没跑实**（跑实需同时伪造 `cm.FACETS`，越出只读复核边界），别当已证。
2. **名册是散文。** 行内那 7 个名字写在 `#:` 注释里，AST 源码锁（`ratchet:96`）读不到注释，
   ⇒ 只把注释写错，**哪里都不红**。这与 `DIRECT_CALLSITES_ZERO_ROSTER`（真常量＋等值断言）不同型。

## 三、第五处（叙述面，两处；本席零写面，只报不改）

- `AGENTS.md:212`（#49 台账行）：仍写「AI 绘画与语音这两枚 `creation.*` 描述符是**只声明未接线**
  （本席现算：`execution=None`、全仓无 `invoke(capability_id="creation…")` 调用点）」。
  今天**两枚都有**生产调用点（tts 自 09-23 20:3x、image 自 09-25）。该行内已有的两枚
  「2026-09-24 勘误」「2026-09-25 勘误」**都不覆盖这一句**（一枚讲 `*_via_queue`，一枚讲配音第二腿）。
- `docs/HANDBOOK.md:2685`（§40）：现在时断言「`creation.image.generate` **仍没有**生产调用点」，
  被同一份 HANDBOOK 自己的 `:3839-3840`／`:3856-3857` 与盘上事实双重否证。

两处都是"当时值未标当时值"的形态（铁律 10 ＋ 一处变更处处跟随），代码零影响，
但 `AGENTS.md` 是自动加载件——下一个 AI 会把它读成现行事实。

## 四、门禁与卫生（本席亲跑）

- 两门独跑：`104 passed in 18.64s`（exit 0）⇒ 主代理"独跑两门 104 passed"的自证**复现成立**。
- 口径钉三句独立核（**只读 `Config.model_fields[...].default`，未碰 `.env`**）：
  `bot_control_plane_enabled=False`、`bot_creation_image_provider=''`、
  `UNAVAILABLE→(503,"image_not_wired")` 在 `domains/creation/image/routes.py:92`（`tests/test_control_plane_image_api.py:196` 执法）
  ⇒ `gate:142-144` 那句"禁把 8→7 叙述成绘画能出图"与盘上一致，是真纪律不是装饰。
- 源码树新增 `.pyc` **0 枚**（`tests/` 唯一一枚 mtime 11:58:19 早于本席骨架）。未跑全量、未 `--write`、未 git 写、未改任何件。

## 五、给她的一串裁定点（编号＋推荐）

- **N-1 叙述跟随**（推荐：`AGENTS.md:212` 与 `docs/HANDBOOK.md:2685` 各加一句失效指针，形如「〔2026-09-25：两枚均已有生产调用点，见 §42〕」，**不改写历史原句**）。
- **N-2 补成员锁**（推荐：新增 `DECLARED_UNWIRED_ROSTER: frozenset[str]` 常量＋`test_leg3b` 内一条 `set(unwired)==DECLARED_UNWIRED_ROSTER` 等值断言，照 `DIRECT_CALLSITES_ZERO_ROSTER` 同型办，并写明它与②零余量锁的分工＝一把管数、一把管名；代价＝今后置换须同批改两处，那是"故意留痕"，不是放宽）。
- **N-3 若要坐实 generic 态置换**（推荐：另派一席、明确允许进程内同时 patch `cm.FACETS`；本席按只读纪律未做）。
- **N-4 归因限制须知**（不需动作，只需知道）：四个涉事件全是**未跟踪件**，
  ⇒ "主代理刚改了什么"在 git 层**不可取证**（`git diff HEAD -- <未跟踪>` 恒空＝空判据）。
  本文全部结论建立在**盘上现值＋判据源码＋内存毒测**三条上，没有一条建立在"比了 diff"上。
