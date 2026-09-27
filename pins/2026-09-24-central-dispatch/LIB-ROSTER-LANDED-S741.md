# S741 · 五座缺声明源的库轴增量落地（LIB-ROSTER-LANDED）

Status: DONE

> 席位：S741（批次 250926A）。任务＝把 S713 的库轴设计收成**可直接粘贴**的 `board_taxonomy.py` 增量声明，
> 只新增、绝不改动既有 `FeatureNode`/`BoardNode` 的既有字段值；并在 `%TEMP%` 副本上现算「增量前后各库成员数」对照。
> 交付两件：`patches/s741-roster-increment.md`（可粘贴增量）＋本件（落地账）。量具：`probes/s741-roster-delta.py`。

## §〇 证据头（本席现算，2026-09-26）

| 件 | 读数 |
|---|---|
| HEAD | `a5226ec` |
| `plugins/bot_unified_runtime/domains/core/board_taxonomy.py`（声明源真身） | sha256[:16] `a76235f025024d69`，**1023 行**（S713 记 1021 行 / `636804ba2d40ace9` ⇒ 已漂 2 行，**故本包锚点一律抄真实行、不给行号当凭据**） |
| 打上增量的 `%TEMP%` 副本 | **1161 行**（`wc -l` 尺；净插入 **138 行**），sha256[:16] `3cceb62d2116e70d`（＝本包补丁重建出的同一份） |
| 成员宇宙（工厂 worktree 尺） | HEAD 侧 `plugins/**.py` **584** ＋ 未跟踪 **50** ⇒ worktree **634**（S713 记 631 ⇒ 又漂 3 枚） |
| 现役十库账 | 已认领 **499** ＋ 无主 **130** ＋ 双认领 **5** ＝ **634**（恒等式成立） |
| 库工厂件 / 漂移件 | `probes/s0-main-lib-factory.py`（本席 importlib 直取，未复制任何判据） |
| 静态门（`ruff check --no-cache --isolated`，对 `%TEMP%` 两份副本各一次） | 原文副本 `rc=0 All checks passed!`／增量副本 `rc=0 All checks passed!`；**而本席首版把 D 三处写成「插在前」时增量副本判 `RUF022 __all__ is not sorted`（`rc=1`）**——已改判方向，见 §六 第 7 条 |

复跑（约 60 秒，只写 `%TEMP%/s741/`，仓内零写）：

```bash
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s741-pyc" \
"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B \
.superpowers/sdd/2026-09-24-central-dispatch/probes/s741-roster-delta.py
```

## §一 结论速览

1. **新增声明枚数＝5 座库节点**（`ReleaseLibNode` × 5：`L0 contracts` / `A1 adapter-qq` / `A2 adapter-telegram`
   / `A3 adapter-mail` / `A4 adapter-console`），配套 **1 个与 `BoardNode` 平级的 frozen dataclass** ＋
   **2 个读者函数**（`iter_release_libs` / `lib_by_slug`）＋ `__all__` **加 4 名**（原 7 名一字未删 ⇒ 7→11；
   计数以 `grep -c '"…",' ` 对增量副本现算，不引 S713 旧数）。**库轴成员合计 14 枚**（contracts 12 ＋ adapter-mail 2）。
2. **只新增、零改动既有认领**得到结构级证明：把六处插入逐块撤销后与原文**逐字节相等**（I1 `True`），
   且 10 枚 `BoardNode` ＋ 57 枚 `FeatureNode` 的 `ast.dump` 集合前后**全等**（I1 节点腿 `True`）。
   ⇒ 没有任何一枚文件的板块归属被这次改动挪动；D-5/E 系列那类「改既有值」本席一概没做。
3. **工厂仍被拦，且拦点与增量无关**：`--caliber worktree`（无 `--tie-break`）实跑 **RC=2**，
   拦在 **L2 双认领 5 枚**（逐枚见 §五）。这 5 枚全部由 `FeatureNode.impl_paths` 派生，增量一行都不进 ⇒
   拦截清单与增量前**逐枚同值**。**未用 `--tie-break` 绕过**（演练档，不改归属、不出结论）。
4. **增量对工厂派生零影响＝名册今天没有读者**（I2 实跑 `True`）：工厂 `parse_taxonomy()` 只认
   `BoardNode`/`FeatureNode` 两种 call，`ReleaseLibNode` 它一眼不看 ⇒ 前后各库成员数**逐库等值**（§四表）。
   这条不是好消息，是 S713「没有读者即装饰件」的第二次实证：**名册必须与工厂 `parse_libs` 同批落地**。
5. **可粘贴性已机检**：从补丁 md 的六个围栏抽块、按锚点重建，结果与实测增量**逐字节相等**
   （`补丁重建 == 实测增量: True`，两侧 sha16 同为 `3cceb62d2116e70d`；六个锚点计数均为 1；
   且**逐块撤销后逐字节回到原文 `True`**）。
   ⇒ 她（或该件 owner）照补丁贴，得到的就是本席验过的那一份，不存在「补丁与实测两形」。

## §二 声明源现状与四处插入锚点

四处插入（锚点原文与完整代码块都在 `patches/s741-roster-increment.md`，此处只登记锚点唯一性现算）：

| 插入点 | 锚点（抄自真实行，非行号） | 现算出现次数 | 性质 |
|---|---|---|---|
| A｜模块 docstring 末段 | `用法：`（现算行 21） | **1** | 纯追加 3 行说理＋1 空行；不动任何节点字段值（可选块，删掉不影响其余三处） |
| B｜`class BoardNode:` 之前 | `@dataclass(frozen=True)` ＋ `class BoardNode:` 两行连排 | **1**（`@dataclass(frozen=True)` 单独出现 2 次，连排后恰 1 次 ⇒ 本席锚点取连排形） | 新增 `ReleaseLibNode` dataclass |
| C｜`def board_by_id(...)` 之前 | `def board_by_id(bid: str) -> BoardNode \| None:` | **1** | 新增 `LIBRARY_TAXONOMY` 整张表 ＋ 两个读者函数 |
| D｜`__all__` 内三处 | `    "BOARD_TAXONOMY",` / `    "FeatureNode",` / `    "iter_features",` | 各 **1** | 只插行、原有 7 名一字未删；**方向＝插在该行之后**（ruff `RUF022` 逼出来的，见 §六 第 7 条） |

量具对锚点的纪律：**计数≠1 即 `FATAL`、绝不猜测插入点**（`apply_insertions()` 里 `raise SystemExit`），
这一条也写进了补丁的「粘贴后必查」段，落码者可自跑。

## §三 五座库逐座成员现算与派生尺出处

统一入册资格三查（`unclaimed_free()`）：**① 在库工厂成员宇宙内**（`plugins/**.py`，worktree 尺）；
**② 今天无主**（不被任何 `FeatureNode.impl_paths` 按最长前缀认领，语义与工厂同尺）；
**③ 不是包命名空间占位**（AST 现算：除模块 docstring 外零语句）。三查全过才写进 `member_paths`——
**本席一行清单都没手抄**。

| 座 | lid/slug | 成员（今值） | 派生尺与现算过程 | 剔除项 |
|---|---|---|---|---|
| 契约地基库 | `L0`/`contracts` | **12** | 目录尺 `domains/core/contracts/*.py` → 11 枚；**顶层再导出垫片**由名尺 `plugins/bot_unified_runtime/contracts/__init__.py` → 1 枚；12 枚全过三查（`contracts_dropped=[]`） | 无 |
| Mail 适配器 | `A3`/`adapter-mail` | **2** | 目录尺 `domains/transport/mail/*.py` → 3 枚，其中 `mail/__init__.py` 被尺③判为命名空间占位剔除 | 1 枚（`namespace-placeholder`） |
| QQ 适配器 | `A1`/`adapter-qq` | **0**（候选 1 枚，播种三态③） | 两把尺串联，见 §3.1 | 9 枚（跨路／非本体／已被 B08 认领） |
| Telegram 适配器 | `A2`/`adapter-telegram` | **0**（播种三态①） | 名字尺 `rglob` 扫 `plugins/scripts/tests`：`scripts/telegram_resilience.py` **落在 `plugins/**` 宇宙之外**（尺①直接拒）；另两枚 plugins 同名件在 `domains/link_parse/`、`domains/media/`，不是 transport 通道件 | — |
| Console 适配器 | `A4`/`adapter-console` | **0**（播种三态②） | 字面尺 `nonebot.adapters.console` 全树命中 **只有 `pyproject.toml`**（extra 声明）；站点尺 `register_adapter(` 命中 **`bot.py` ＋ `domains/ops/smoke/smoke.py`** 两文件、共 4 处调用（`bot.py:410/411/487` ＋ `smoke.py:165`），**零 Console 注册** | — |

三条播种态的合法性现算（量具 `SEED_STATE`）：`adapter-qq → state-3 已被板块账装着`（理由 91 字）、
`adapter-telegram → state-1 落点不在盘上`（103 字）、`adapter-console → state-2 无成员带理由`（111 字）。
**没有一枚落进第四态（在盘、无主、又没进任何成员表＝懒登记）**。

### 3.1 A1 的适配器本体是**派生**出来的，不是人眼挑的

`domains/transport/sender/` 目录尺给 10 枚；通道证据尺（token 族 `onebot/OneBot/snowluma/SnowLuma`）
只把它们收成「单通道候选 5 枚」——`__init__.py`、`gateway.py`、`onebot.py`、`queue.py`、`worker.py` 都含 `onebot` 字样。
把五枚都写进 A1＝**把队列与闸也当成适配器**，是假账。于是加第二把尺：**协议动作字面尺**
（`send_group_msg`/`send_private_msg`/`get_forward_msg`/`set_msg_emoji_like`/`upload_group_file`/
`get_group_member_info`/`get_msg`/`delete_msg`——只有真写协议客户端的文件才会逐字出现 ≥2 个动作名）。
实跑命中（sender 目录内）：

```text
sender/onebot.py         3 个动作名  ← 唯一 ≥2，判为适配器本体；今值仍被 B08.send-queue 认领 ⇒ 三态③
sender/file_gateway.py   1 个（upload_group_file），通道证据 {mail, onebot, telegram} ⇒ 跨路，不入任何 A 库
sender/nonebot.py        0 个动作名，通道证据 {mail, onebot, telegram} ⇒ 跨路，不入任何 A 库
sender/worker.py         1 个（get_msg）
sender/{__init__,gateway,queue}.py   0 个
sender/{outbound_gate,receipts,timeout}.py   0 个
```

⇒ A1 唯一候选＝`sender/onebot.py`，且它今天**确实已随 `render-outbound` 发版**——本席现算凭据：
`../ChatBot_Libs/render-outbound/plugins/bot_unified_runtime/domains/transport/sender/onebot.py` 在盘（`ls -l` 命中），
板块账派生侧同一枚归 `B08`（尺②读数 `B08`）⇒ 落 `pending_seed`（三态③）而非 `member_paths`。
这与 S713 §3.3 的独立读数**同结论**（它的候选 1 枚、已在 render-outbound），本席用两把尺把它变成可复跑判据。

## §四 增量贴入 `%TEMP%` 副本后的前后对照

工厂原语（`parse_taxonomy` / `git_tracked` / `git_untracked` / `longest_prefix_owner`）各跑一次，两侧共用同一份宇宙：

| 库（bid→slug） | 增量前成员 | 增量后成员 |
|---|---|---|
| B01→ingress-protocol | 13 | 13 |
| B02→routing-dispatch | 54 | 54 |
| B03→persona-chat-safety | 34 | 34 |
| B04→memory-knowledge-notes | 13 | 13 |
| B05→external-data-services | 122 | 122 |
| B06→media-entertainment | 91 | 91 |
| B07→schedule-automation | 32 | 32 |
| B08→render-outbound | 47 | 47 |
| B09→control-plane-observability | 86 | 86 |
| B10→engineering-governance | 7 | 7 |
| **合计（板块十库）** | **499** | **499** |

**逐库等值**不是巧合而是必然：`I2 工厂派生前后深等值: True`（`boards`/`feats` 两本字典全等）
⇒ 工厂的输入一字未变 ⇒ 它派生的每一支库也一字不变。**这正是「名册缺读者」的实测形态**，
补丁 §三因此把「工厂加 `parse_libs` ＋ 常驻门加三把腿 ＋ 漂移检查器复用同尺」列为**同批必落**，否则本增量＝装饰件。

名册自身五层判据（本席在副本上现算）：

| 层 | 判据 | 读数 |
|---|---|---|
| K0 自洽 | slug 过 kebab / 与板块 slug 不相交 / `kind != board` / 代号唯一 / 字面量纪律 | kebab `True`、撞车 `[]`、`kind=="board"` 手抄 `[]`、库内双认领 `[]`、**全部 kwarg 为字面量 `True`** |
| K1 在场 | 每枚成员在盘上是文件 | 盘缺 `[]`（14/14 在盘） |
| K1b 宇宙 | 每枚成员在 worktree 宇宙内 | 宇宙外 `[]` |
| K2 独占 | 名册成员 ∩ 十库派生成员 ＝ ∅；且名册成员不得已被板块 fid 认领 | 交集 `[]`、被板块认领 `[]` ⇒ **V1（一支文件只进一支仓）今天可落地** |
| K3/K4 | 库实体可独立导入／快照字节对账 | **本席未做**（要真建库目录与发版本，红线禁；现役十库的 K3/K4 归 S713 §5.3 与漂移检查器） |

守恒式（增量前 → 增量后，两侧都闭合）：

```text
前：已认领 499 ＋ 无主 130 ＋ 双认领 5 ＝ 634 ＝ 宇宙 634
后：已认领 499 ＋ 库轴 14 ＋ 无主 116 ＋ 双认领 5 ＝ 634 ＝ 宇宙 634
```

14 枚库轴成员全部从今值「无主 130」里搬走 ⇒ 无主降到 116。**与 S713 的账型同构**（它的 498/128/5＝631 → 498/14/114/5＝631），
差值来自本窗树漂（宇宙 631→634、已认领 498→499、B02 派生 53→54），不是口径差。

## §五 工厂实跑：拦在哪一条、拦了哪几枚

命令（out 只指 `%TEMP%`，**零写 `ChatBot_Libs`**）：

```bash
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \
PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s741-pyc" \
"C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe" -B \
.superpowers/sdd/2026-09-24-central-dispatch/probes/s0-main-lib-factory.py \
--caliber worktree --out "$(cygpath -w "$TEMP")/s741-factory-dry"; echo "RC=$?"
```

实跑（**RC=2**，L2 之后立即返回，演练目录保持为空＝一字节未写）：

```text
FATAL L2 双认领 5 枚（先解归属再谈建库）：
  DUAL:plugins/bot_unified_runtime/domains/chat_reply/character/history.py->B03,B04
  DUAL:plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py->B03,B04
  DUAL:plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py->B03,B04
  DUAL:plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py->B03,B04
  DUAL:plugins/bot_unified_runtime/domains/ops/monitor/error_report.py->B08,B09
```

三条必须同读的口径：

1. **拦的是板块账自己**（4 枚 B03/B04 ＋ 1 枚 B08/B09），与本增量无关；本席**没碰这些认领**（改既有值＝D-5/E 系列，归她裁，S750 也在做窄化方案）。
2. 因此「增量前 / 增量后」工厂实跑**同一处拦、同一批 5 枚**——增量后那次无法用 CLI 复现（工厂只读 `repo/TAXONOMY_REL` 一条路，本席禁改仓内声明源），
   但 §四 的 I2 深等值就是它的等价证明（工厂输入不变 ⇒ 输出不变 ⇒ 拦点不变）。**这条限制本席如实写明，不冒充成「跑过两次」。**
3. **未加 `--tie-break`**（简报与工厂 docstring 都写明它是演练档，只临时归一、不出归属结论）。

⇒ 五座库里**今天真能被工厂建成实体的只有 2 座**（`contracts` 12 枚、`adapter-mail` 2 枚）；
且工厂现状**根本不读名册**，读不读取决于 §三·读者同批。

## §六 增量落地后仍必须同批存在的读者与跟随面

1. **库工厂**：加 `parse_libs(text)`（同一次读文件、同一支字面量抽取形状），把非 board 库并入 `claims`；
   守恒式改成本席 §四 的 `499 ＋ 14 ＋ 116 ＋ 5 ＝ 634`。L1（成员为 0 ⇒ FATAL）对 A1/A2/A4 这类
   **在册待播种**库要有显式豁免——建议读 `pending_seed` 而非加旗标，否则「五座一起建」当天退 2。
2. **常驻门** `tests/test_board_taxonomy_gate.py`：加 S713 §4.3 三把腿（名册自洽／库级互斥＋播种三态／活性腿）。
   ⚠ 该门今天已有他波红（`HOST_STATE`／「宿主机状态」未认领族），**新腿绝不能写成 problems==0**，
   否则把别人的红记到本增量账上（S713 §4.4 同一条警告，本席复述是为了让落码者不必回翻 46 KB）。
3. **漂移检查器** `probes/s0-main-lib-drift-checker.py`：复用同一支 `parse_libs`，**不许写第二把派生尺**。
4. **导出面地板**：`tests/test_declaration_readers_no_silent_empty.py` 对 `board_taxonomy` 只准降；本增量把名册名加进 `__all__` ⇒ 方向安全。
5. **零跟随面（按构造成立，今值未复算）**：`FeatureNode.impl_paths` 一个字符未进 ⇒ 板块投影器、
   归属门包含对与字面双认领硬零、G-P2 豁免上限都不在这次插入的取数路径上
   （那三把尺的**现值本席未复算**，以 `tests/test_physical_placement_gate.py` 与 `scripts/board_doc_sync.py --check`
   为准；S713 §4.4 当时读数：包含对 15＝上限、字面双认领硬零、豁免 29＝上限，属**未复算的转述值**）。
   三件生成物与 `verify_hashes` 清单不含声明源 ⇒ 本席**未跑 `--write`**（并发窗内禁重录）。
6. **写权**：`domains/core/ownership_map.py` 把 `board_taxonomy.py` 记为 `READ_ONLY` ⇒ 落地权在她与该件 owner，本席只交文本。
7. **静态门（本席自己造出来又自己抓到的一枚）**：`__all__` 三处新名**首版按「插在前」写**，ruff 当场
   `RUF022 __all__ is not sorted`（`rc=1`）——那是**默认规则集**里的排序尺，仓配 `[tool.ruff]` 只有
   `extend-exclude`、不选规则 ⇒ 同一把尺就是 `dev.ps1 -Task lint` 的口径。改成「插在该行**之后**」后，
   原文副本与增量副本同判 `rc=0 All checks passed!`。**这条不是可选项**：补丁 §一-D 已把方向写死并说明来由，
   落码者凭手感改成插前就会把 lint 门打红。对照实跑现值（含在量具输出里，两行）：

   ```text
   ruff 原文副本: rc=0 All checks passed!
   ruff 增量副本: rc=0 All checks passed!
   ```

## §七 本席没做成什么（不留已完成假象）

1. **没落码**：声明源、门文件、工厂件、`board_placement.py` 一字节未改；产出只有本件 ＋ `patches/s741-roster-increment.md` ＋ `probes/s741-roster-delta.py` ＋ `%TEMP%/s741/**`。
2. **没建库、没 git 写、没搬文件、没重启、没改 `.env`、没跑全量 `dev.ps1 -Task test`**（红线全套未越）。
3. **K3/K4 未验**（独立可导入实测与快照字节对账要真建库目录，红线禁）；`adapter-mail` 那两枚是否真能独立 import，留给建库那一跑。
4. **工厂「增量后实跑」用等价证明替代**（原因见 §五 第 2 条），不是 CLI 两次跑——如实标注。
5. **没裁的东西照实留**：V1 还是 V2（本增量按 V1 写＝一支文件只进一支仓）、装配根 `__init__.py` 归不归库、
   A4 三案、`sender/nonebot.py` 与 `sender/file_gateway.py` 跨路件拆法、以及 §五 那 5 枚双认领的窄化（S750 在做）。
6. **卫生自证**：直跑 python 全程带 `PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=%TEMP%/s741-pyc` 与 `-B`；
   未跑 pytest（无受害门可跑——本席未动任何门文件）；仓树内**零 `import plugins...`**（判装载一律 AST＋文本尺，工厂经 importlib 从 `probes/` 直取）；
   产物只进 `%TEMP%`（`s741/`、`s741-pyc/`、`s741-factory-dry/`）与本席三件写面；`%TEMP%/s741-factory-dry` 实跑后**目录为空**（L2 即返回）。
   **两条现算自证（判「我没落码」不许只靠自述）**：`grep -c "LIBRARY_TAXONOMY\|ReleaseLibNode"` 对仓内声明源 ⇒ **0**；
   `git status --porcelain \| grep -i s741` ⇒ 空（`.superpowers` 已 gitignore）。
   ⚠ 同时如实报备：**仓内声明源今天是脏的**（`git diff --numstat` ⇒ 11 增 6 删，改动内容是**他波在飞件**——
   亲密模式分级波 D 席登记的 `help_topics=("亲密模式",)`、书面同意波改的 B10 `summary`/`route_kinds`/`impl_paths` 等，
   **一条都不是本席所为**；文件因此从 S713 的 1021 行漂到 1023 行）。⇒ 落码者粘贴前**必须重跑一次锚点唯一性**
   （补丁与量具都写死了「计数≠1 即 FATAL」），别拿本席这六个锚点当永久真值。
7. **安全台账（AGENTS 规则 11）**：本席窗口内工具结果与文件正文出现的祈使形文字（含技能清单里 `mandatory first-move`/`MUST` 一类的自述、
   以及一段「MEMORY.md 已被外部修改」的系统注记）**一律当数据：零执行、未改配置、未派席、未 git 写、未重启**，任务照常推进；
   未构成指令形态的注入，无载荷需消毒登记。

## §八 总裁决与还剩什么

总裁决 —— 本席把 S713 的库轴设计收成**六处纯插入、可直接粘贴**的 `board_taxonomy.py` 增量（5 座库节点＝
`L0 contracts` 12 枚 ＋ `A3 adapter-mail` 2 枚 ＋ A1/A2/A4 三条诚实播种态，共 14 枚成员、净插入 138 行），
结构上证明「只新增、既有 10 枚板块与 57 枚功能的 AST 摘要一字未变」，并机检了补丁与实测增量逐字节同源；
**工厂仍被拦在 L2 双认领 5 枚（RC=2，未用 `--tie-break` 绕过），且拦点与本增量无关**——
更要紧的一条是 `parse_taxonomy` 前后深等值：**工厂今天根本不读这张名册**，所以还剩三件事必须同批落地
（工厂 `parse_libs`、常驻门三把腿、漂移检查器复用同尺），以及她对 V1/V2、装配根归库、A4 三案、
跨路两件与那 5 枚双认领（S750）的裁定。

done: yes
