# ROSTER15-CONFLICTS-S888 —— 名册并到 15 座后的全量双认领账（席位 S888，批 250926N，接替 S868）

时刻：2026-09-26 19:3xZ（开窗现取）。席＝S888（只读主仓与声明源，写面＝`probes/s888-*.py`＋本件＋`patches/s888-prefix-ruler-fix.md`）。

## §〇 接替登记（纪律 12：先读前席残件，只补空缺）

| 前席说法 | 盘上实况（本席现算） | 我沿用 | 我推翻 |
|---|---|---|---|
| 简报称残件＝`probes/s868-{count-double,plan-narrow,crosscheck}.py` 三件 | **只有 `probes/s868-union-conflicts.py` 一件**；`ROSTER15-CONFLICTS-S868.md` 从未建 ⇒ 本件＝该面第一份。本席把前席那件**原样复跑**（`$PY -B probes/s868-union-conflicts.py` rc=0）与自己的尺二逐叠对账 | 沿用它的叠法命名 O0–O4 与宇宙两口径 U-main/U-wide；另补 O5/O6 两形并贴 | 残件清单（三枚→一枚） |
| 全量双认领 **46 枚** | **裁 46 过期**：46＝18＋28 两叠相加，而这两叠的枚集**嵌套**（O3 ⊂ O4：交 18、并 28）⇒ 同一枚点了两次。去重并集＝**34 枚**；最大单叠＝28（U-main O4）／34（U-wide O4）。前席留在盘上那把尺自己最大的读数也只有 **21**（U-wide O1）——46 与它自己的尺不自洽 | — | 推翻（证据 `probes/s888-recon-46.py`，§二 头） |
| 「真 10 枚是 `render-outbound` ∩ `adapter-qq`」（推翻"10 枚属 sender"旧说法） | **成立且两句其实同一批**：10 枚全在 `domains/transport/sender/` 目录内，两座＝板轴 `render-outbound` ∩ 库轴根形 `adapter-qq`；旧说法错在把库轴座说成"板块归属" | 沿用结论 | — |
| `adapter-onebot`／`adapter-telegram`／`adapter-console` 三座空壳 | **座数成立、枚名错一枚**：成员形（现役包）下空壳＝`adapter-qq`／`adapter-telegram`／`adapter-console`。名册里没有 `adapter-onebot` 这支 slug（`grep -rn "adapter-onebot" patches/*.md` 零命中；`nonebot-adapter-onebot` 是 pip 发行名不是库名） | 沿用"三座空壳" | 改 slug 名 |
| `contracts` 与 **4 座**板块库目录重叠 | **两处都要改**：①现役包（成员形）下 contracts 12 枚**零相撞**；②相撞发生在「成员形 ⊕ S796 板轴补认领」那一叠，撞 **6 座**（external-data-services／media-entertainment／persona-chat-safety／render-outbound／routing-dispatch／schedule-automation），形态＝**逐枚字面撞逐枚字面**（代号 H7），不是目录撞目录 | 沿用"contracts 会撞"这件事 | 枚数 4→6、形态目录→字面 |
| 尺 bug＝`longest_prefix_owner` 用裸 `startswith` | **机制成立、名字与坐标要改**：四把 `longest_prefix_owner`（工厂 `s0-main-lib-factory.py:161`／`s717-b-matrix.py:424`／`s722-b-ownership.py:85`／`s731-enum.py:59`）判据里都带 `/` 段边界，合成实测**不误配**；裸前缀真住在 **`probes/s715-deps.py:92` 的 `longest_prefix_root` 兜底腿**，且**正反两向都裸** | 沿用"有一把尺会误配" | 点名改到 s715（§三 给同一发合成输入的五把尺点名表） |

## §一 名册 15 座：两种并法与空壳读数（现算）

宇宙（`--caliber worktree` ＝ `ls-files` ∪ `ls-files --others --exclude-standard`）：
`plugins/**.py` **601** 枚（U-main，与库工厂/断开度同尺）；另有 `scripts/**.py` **73** 枚 ⇒ U-wide 674。两口径同屏、不换算。
（`S888-Z universe_main=601 universe_scripts_extra=73 claims796=69 members741=14 roster_seats741=5 nonboard_root_seats=5`）

| 叠 | 并法 | 座 | 空壳座（U-main） | 双主（U-main） | 新造 vs 板轴 | TIE | 双主（U-wide） | 无主 |
|---|---|---|---|---|---|---|---|---|
| O0 | 板轴 alone（现役真值） | 10 | 0 | **5** | 0 | 0 | 5 | 129 |
| O1 | ⊕ `s715-deps.NONBOARD_ROOTS`（**根形**＝S865 那一形） | 15 | 2 | 15 | 10 | 10 | 21 | 115 |
| O2 | ⊕ `patches/s741-roster-increment.md` `member_paths`（**成员形＝现役可贴包**） | 15 | 3 | **5** | **0** | 0 | 5 | 115 |
| O3 | O2 ⊕ S796 板轴补认领（＝S849 的 C5） | 15 | 3 | **18** | **13** | 13 | 18 | 64 |
| O4 | O1 ⊕ S796 | 15 | 2 | 28 | 23 | 10 | 34 | 64 |
| O5 | O1 ⊕ O2（两种写法同时进声明源） | 15 | 2 | 15 | 10 | 10 | 21 | 114 |
| O6 | O5 ⊕ S796 | 15 | 2 | 28 | 23 | 23 | 34 | 63 |

三条必读结论：

1. **把名册并到 15 座这件事本身不造双主。** 现役可贴包（成员形 O2）双主＝5，与板轴 alone **逐枚同集**（新造 0）。
   造双主的是另外两件事：把库轴写成**目录根**（O1 ＋10 枚，全 TIE），以及把 **S796/S834 的板轴逐枚补认领**一起贴（O3 ＋13 枚，全 TIE）。
2. **新增的双主 100% 是"前缀规则判不出"的 TIE**（O1/O3/O6 里 `tie == new_vs_O0`）⇒ 名册补齐不可能靠"最长前缀自动裁决"解决，
   只能靠归属裁定＋窄化落笔。表上判得出来的那 11 枚全是**存量**（O0 就双主，前缀靠"逐枚字面比目录根长"自裁）。
3. `pairs`＝`slots`＝`dual_total` 逐叠相等 ⇒ **没有任何一枚被三座以上认领**，"枚数／多出来的主次数／座次对数"三种单位数值相同——
   前席的 46 不是单位差，是**叠相加**。

## §二 全量双认领逐枚表（本席现算并集＝34 枚，一枚一句裁定）

集合关系实证（`probes/s888-recon-46.py`）：`O3∩O4=18`、`O3∪O4=28`、`18+28=46` ⇒ **46＝把 O3  whole 计进 O4 第二遍**；
`O1∩O4=15`、`O1∪O4=28`；并集（七叠两宇宙去重）＝**34**（U-main 28 ＋ 只在 U-wide 才双主的 `scripts/` 6 枚）。

表读法：`binding 叠`＝这枚最先在**最贴近现役贴法**的那叠里成为双主（优先级 成员形 O2 → O3 → 根形 O1 → O5 → O4 → O6 → O0）；
`腿`＝库工厂今天会由哪条腿拦下（L2 板块内双认领／L7 名册间／L8 库板相撞）；窄化代号见 §二末。

| # | 路径（省略 `plugins/bot_unified_runtime/`） | 双主两座 | binding 叠（w＝U-wide） | 最长前缀判给 | 腿 | 一句裁定 |
|---|---|---|---|---|---|---|
<!--S888-TABLE-->

窄化代号表（尺内只出代号，逐枚裁定已把代号写进上表末列）：

| 代号 | 含义 | 落笔面 |
|---|---|---|
| H1 | 目录根撞目录根 ⇒ 其中一座改逐枚显式 | 板轴 `impl_paths`（`B08.send-queue` 那枚 `"…/domains/transport/sender"`）**或** 库轴 `NONBOARD_ROOTS["adapter-qq"]` |
| H3 | 最长前缀已判给板轴逐枚件根 ⇒ 库轴让位 | 库轴侧剥该枚 |
| H4 | 名册逐枚字面在册更深 ⇒ 板块目录根须剥该枚（S750 同法） | 板轴侧剥该枚 |
| H5 | 库轴目录根罩住板轴 ⇒ 名册侧改逐枚（根形不许贴） | `s715-deps.NONBOARD_ROOTS` |
| H6 | 板轴目录根更深 ⇒ 库轴让位或窄化到子目录 | 库轴侧 |
| H7 | **字面撞字面**（两座各自逐枚在册）⇒ 前缀规则无裁决力，必须人裁 | 归属裁定＋其中一座摘该枚 |


## §三 尺 bug 实证与修法（读数待填）

## §四 与 S834/S849 对账（不另立第二本账；读数待填）

## §五 名册 15 座后 `s759-severance` 的 denom/numer 前后读数 + roster 守卫＝假绿通道复现（读数待填）

## §六 注毒战果（≥2 发；读数待填）

## §七 零污染自证（读数待填）

## §八 复跑命令簿

## §九 本席自错

## §十 安全台账（规则 11）
