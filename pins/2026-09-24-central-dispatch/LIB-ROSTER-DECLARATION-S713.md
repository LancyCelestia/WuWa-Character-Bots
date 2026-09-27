# S713 · 契约库与四座适配器库的名册申报形状（LIB-ROSTER-DECLARATION）

Status: DONE

## §一 结论速览

1. **形状**：契约库＋四座适配器库**不是板块**，得走第二根轴——新建与 `BoardNode` 平级的 `ReleaseLibNode` ＋ 一张 `LIBRARY_TAXONOMY`，**写进既有声明源 `board_taxonomy.py`**（扩写既有件、零新文件）。`FeatureNode` 特殊 fid 前缀那一形被**现算否掉**：板块数锁 10、`fid` 前缀锁、以及进 `impl_paths` 后 contain_pairs 15→**17**（上限 15、零余量）＋库工厂双认领 0→**1**（FATAL）＋`--check` 漂移 0→**3**（反证跑在 `%TEMP%` 副本上，数字可复跑，见 §4.4/§5.3）。
2. **落点改判（与 E10B §6 件 1 分歧，三条实测）**：名册落 `board_placement.py` 会被现役取数口**逐字忽略**（`sees_release_libs=false`），而扩它的 `names` 又会把常驻门那条合成源自证打红（`AssertionError: 缺声明 ['RELEASE_LIBS']`）；落 `board_taxonomy.py` 则**所有现役读者一字不动**（板块投影器 problems 2→2、漂移 0→0；归属门五腿与 counts `equal=true`；工厂派生结果深等值）。
3. **成员现算**（我复算过 E10B，逐枚取今值）：地基库 `contracts`＝**12 枚**（11 枚在 `domains/core/contracts/` ＋包根再导出垫片 `plugins/bot_unified_runtime/contracts/__init__.py` 20 行），**逐枚零 fid 认领、且不在任何一支已建板块库里**＝唯一一枚剪下去零重叠的；简报里「顶层 `runtime/contracts` 类件」这一句要改口——**`plugins/bot_unified_runtime/runtime/contracts.py` 不存在**。适配器侧：A1 只有 1 枚候选（`sender/onebot.py` 1405 行）**但它已随 `render-outbound` 发版**（B08 的目录认领罩住整个 `sender/`，10 枚全在里面）；A2 的唯一真身 `scripts/telegram_resilience.py` 在库工厂成员宇宙**之外**；A3 两枚（`mail_adapter.py` 301／`mail_bridge.py` 461）**无主且不在任何库**＝干净；A4 **零成员**（生产 `register_adapter` 恰 3 处、`nonebot.adapters.console` 生产代码零 import，实测语句在 §3.3）。⇒ **五座里今天能有货的只有两座**（contracts ＋ adapter-mail），A1 等 B08 让位、A2 等搬家、A4 等 §1.3 三案。
4. **守恒账不受影响（这是本包最重要的一条交付）**：现役十库派生＝已认领 **498** ＋ 无主 **128** ＋ 双认领 **5** ＝ **631**（`plugins/**.py` 工作树尺；HEAD 尺只有 584，只按 HEAD 会系统性偏小 47 枚）；真跑工厂 `--tie-break` ⇒ `库=10 成员合计=503 无主=128` RC 0，真跑漂移检查器 ⇒ `SAME=463 DRIFT=0 MISSING=32 ONLY=5` ⇒ **CLEAN**。贴入增量（V1）后的预测：库轴并入 14 枚 ⇒ `498＋14＋114＋5＝631` 仍闭合。
5. **待她一句话的四点**：V1 还是 V2（同一字节能不能进两支仓）；装配根 `__init__.py`（今值 10050 行，实测已在 `schedule-automation` 快照里 443 KB）归不归库；A4 三案；跨路两件（`sender/nonebot.py` 694 行、`sender/file_gateway.py` 795 行）的拆法。**未裁之前本包只交文本，不动主仓一字节。**

## §二 声明源真身与命名权威尺的对账

**证据头（T1 树身份 + T2 指纹，现算于 2026-09-25T20:08Z 与 20:2xZ 两次，同值）**

| 件 | sha256 前 16 | 行 |
|---|---|---|
| HEAD | `5cc6832` | — |
| `plugins/bot_unified_runtime/domains/core/board_taxonomy.py` | `636804ba2d40ace9` | 1021 |
| `plugins/bot_unified_runtime/domains/core/board_placement.py` | `02741a3bcfbbfd3d` | 67 |
| `scripts/board_doc_sync.py`（投影器） | `a59118f6c6e4ec67` | 857 |
| `tests/test_board_taxonomy_gate.py`（板块门） | `a88ff21cad19852a` | 959 |
| `tests/test_physical_placement_gate.py`（归属门，五腿宿主） | `02e28e3db1af7d3f` | 746 |
| `probes/s0-main-lib-factory.py` / `probes/s0-main-lib-drift-checker.py` | `e96c9b276599288d` / `bc057f8ec5ce93bf` | 287 / 130 |

成员宇宙两把尺（本席现算，两值不可混）：`plugins/**.py` 按 git HEAD＝**584** 枚、按工作树（tracked ∪ untracked ∪ 盘上）＝**631** 枚；归属门的 `py_universe()`（盘扫 `plugins/**` + 仓库根，剔 SKIP 目录）＝**600** 枚。简报点名的「只按 HEAD 会系统性偏小」在这一窗实测就是 47 枚。

### 2.1 现役声明源只有一根轴，且那根轴被三枚硬锁钉死

`board_taxonomy.py` 只有两级节点：`BoardNode`（一级板块）与 `FeatureNode`（二级功能，`impl_paths` 是它唯一的成员面）。把「契约库/适配器库」塞进这根轴的三条常见路都被现算否掉：

1. **板块数守恒 10**：`tests/test_board_taxonomy_gate.py:31` `EXPECTED_BOARD_COUNT = 10`，`:73` 还要求 `ids == B01..B10`。⇒ 新建第 11/12/…枚 `BoardNode` 当场红，且 `contracts` 与 A1–A4 本来就不是「一级分类」，把它们升成板块等于改她的分类学。
2. **`fid` 前缀锁**：`:82` 要求每枚 `fid` 以所属板块 `bid` 为前缀 ⇒ 「特殊 fid 前缀」这一形只能挂在某个 BNN 之下，也就是**必然进 `impl_paths`**。
3. **进 `impl_paths` 的代价是现算出来的**（本席反证腿，见 §4.4）：归属门的「目录套文件」记进 `contain_pairs`，今值 **15＝上限 15（零余量）**；库工厂把同一形状记成 `DUAL`（FATAL L2）。反证形一贴，`contain_pairs` 15→**17**、工厂双认领 0→**1**、板块生成物漂移 0→**3** 项。⇒ fid 前缀形不是「暂时红一下」，是**贴上去当天三把门一起红**。

### 2.2 本席判定：新建一枚与 `BoardNode` 平级的 `ReleaseLibNode`，表住 `board_taxonomy.py` 同一件内

不是新建第二份认领表——是**扩写既有声明源**，理由逐条可查：

- **一根轴管一件事**：板块轴回答「这枚文件归谁」，库轴回答「这支仓装哪些文件」。E10B §2.2(c) 已经裁死方向＝一本账（板块）＋一张投影（发行库），投影**不写进 `impl_paths`**。本席沿用该裁定，只把「投影表住哪一件」这一格改判（§2.3）。
- **库轴进 `board_taxonomy.py` 后对全部现役读者是惰性的**（本席实测，不是推演）：`board_doc_sync.load_taxonomy()` 喂增量副本 ⇒ 仍 `boards=10 / features=57`（探针 `s713-host-choice.py` L3）；板块投影器体检 2→2、漂移 0→0、`facts` 与 live 页数逐字等值；归属门 `compute()` 的 claims/features/scanned_py/五枚 g_p1 计数/两枚 g_p2 **全部 equal=true**（`s713-roster-census.py` F2/F3）。
- **只声明数据**：节点值全部 `ast.literal_eval` 认得的字面量（`capability_manifest_projection_check.py:1211` 那条「board_taxonomy 家规要求」正是这条），`release_name` 与 `has_seeds()` 是派生属性——与 `FeatureNode.bid` 由 `fid` 派生同一个家法，**杜绝第二枚手抄字符串**。

### 2.3 与 E10B §6 第 1 件的分歧（本席复算过，改判落点）

`E10B-ADAPTER-LIBS-S653.md` §6 件 1 建议把名册落 `board_placement.py`。我复算了它的成员表（§三）与它的两条锁，落点这一格改判，三条实测理由：

| 腿 | 实测 | 含义 |
|---|---|---|
| L1 | 往 `board_placement.py` 追加 `RELEASE_LIBS` 后，`physical_placement_census.load_placement()` 照读不误、返回的 `names` **里没有它** | 现役取数口只按五枚名字取数 ⇒ 名册落那儿＝**无读者即无执法**，第一天生成装饰件 |
| L2 | 把取数口的 `names` 扩一枚（`%TEMP%` 副本上改，真身一字未动），喂常驻门自带的合成声明源 `_OK_SRC` ⇒ `AssertionError: 缺声明 ['RELEASE_LIBS']` | 扩 names 必先把 `tests/test_physical_placement_gate.py::test_normal_state_reads_all_five_and_keeps_nested_counts` 打红 ⇒ 落 board_placement 要**连改门文件**，而门文件是主仓写面（本席禁改） |
| L3 | `board_taxonomy.py` 加 `LIBRARY_TAXONOMY` 后投影器读数不变（§2.2） | 落 board_taxonomy 不需要动任何现役读者 |

另两条辅助事实：`board_placement.py` 的自述职责是「G-P1/G-P2 的**豁免清单**，只放清单不放判据」——把成员账塞进豁免件会把两种语义混在一件里；库工厂与漂移检查器**只读 `board_taxonomy.py` 一件**（`TAXONOMY_REL` 写死），名册放同件＝一次读文件两把尺，放别件＝多开一个读点。

### 2.4 命名权威尺的对账

`_KEBAB = ^[a-z0-9]+(-[a-z0-9]+)*$`（`tests/test_board_taxonomy_gate.py:32`）今天只作用于板块 slug、二级 slug、三级 slug。库轴要复用它，两处必须显式：

- 五枚库 slug `contracts` / `adapter-qq` / `adapter-telegram` / `adapter-mail` / `adapter-console` **逐枚过尺 = true**，且与十枚板块 slug **交集为空**（现算 `slug_free_of_board=[]`）⇒ 仓外 `ChatBot_Libs/<slug>` 目录命名空间不撞车，tag 命名空间（她已裁死用 slug）也不撞车。
- 发行名 `lib:contracts` 这类**带冒号的串不许当 slug**——冒号过不了 `_KEBAB`，也过不了 `git check-ref-format` 的 tag 段。本席把发行名做成派生属性 `f"lib:{slug}"`，表里只写 slug。
- 库代号 `lid`（`L0`/`A1`…）是**大写短码**，同样不过 `_KEBAB` ⇒ 判据必须写明「kebab 只量 slug，lid 走唯一性锁」，否则新腿一上就把自己的合法值判红（本仓「判据吞掉自己的样本」的老形状）。
- 板块轴里另有两枚地板与本席无关但会被读到：`MIN_FEATURES = 50`、`MIN_CLAIMS = 90`（今值 57 / 93）——库轴不进 `impl_paths` ⇒ 这两枚一动不动；而 `tests/test_declaration_readers_no_silent_empty.py:245` 的 `board_taxonomy` 导出面地板是 **7**（今值＝`__all__` 恰 7 枚），增量把 `__all__` 涨到 9 ⇒ 地板方向（只准降）安全。


## §三 成员表现算（contracts 一线 + A1–A4 四通道）

取数口：`board_doc_sync.load_taxonomy` + `physical_placement_census.feature_impl_paths/claiming_fids`（语义 A＝目录前缀、语义 B＝字面）+ 库工厂的 `git_tracked/git_untracked/longest_prefix_owner`。**本席没有复制任何判定逻辑**，全部走既有真身。

### 3.1 先给守恒账（十库现状，本席现算）

| 尺 | 读数 |
|---|---|
| 库工厂 `--tie-break` 实跑（`--out` 指 `%TEMP%/s713-libs`，零写 ChatBot_Libs） | `OK 库=10 成员合计=503 无主=128`（RC=0） |
| 本席同原语、不做消序的分解 | 已认领 **498** ＋ 无主 **128** ＋ 双认领 **5** ＝ **631**（恒等式成立） |
| 漂移检查器对**现役 ChatBot_Libs** 实跑 | `SAME=463 DRIFT=0 CONCURRENT=0 MISSING=32 ONLY=5` ⇒ `VERDICT: CLEAN`（RC=0；②属主仓 B-0 删除账、③属归属门） |
| 漂移检查器对**刚生成的 %TEMP% 快照**实跑 | `SAME=465 … ONLY=5` ⇒ CLEAN（差 2 枚＝现役快照比现派生少 B03/B07 各一枚，属并发窗内新增件） |

十库派生成员（worktree 尺）：`ingress-protocol 13 / routing-dispatch 53 / persona-chat-safety 34 / memory-knowledge-notes 13 / external-data-services 122 / media-entertainment 91 / schedule-automation 32 / render-outbound 47 / control-plane-observability 86 / engineering-governance 7`。

### 3.2 contracts 一线＝**12 枚**（我复算过；简报的「`domains/core/contracts/` 与顶层 `runtime/contracts` 类件」这一句要改口）

现算有一处必须先纠偏：**`plugins/bot_unified_runtime/runtime/contracts.py` 不存在**（`runtime/` 目录里是 `aliases / capability_protocols / pipeline / settings …` 12 枚，无一叫 contracts）。顶层那枚「contracts 类件」真身是**包根再导出垫片 `plugins/bot_unified_runtime/contracts/__init__.py`（20 行）**——它同时也是 `G_P2_EXEMPT` 在册的命名空间占位。

| 成员（仓库根相对） | 行 | 板块认领（语义 A/B 皆列） | 已在某支板块库？ |
|---|---|---|---|
| `…/domains/core/contracts/__init__.py` | 163 | 无主（G-P2 已豁免） | 否 |
| `…/domains/core/contracts/auto_send.py` | 96 | 无主 | 否 |
| `…/domains/core/contracts/character.py` | 277 | 无主 | 否 |
| `…/domains/core/contracts/envelope.py` | 155 | 无主（全仓唯一模块级 `SCHEMA_VERSION`） | 否 |
| `…/domains/core/contracts/errors.py` | 201 | 无主 | 否 |
| `…/domains/core/contracts/finance.py` | 343 | 无主 | 否 |
| `…/domains/core/contracts/media.py` | 862 | 无主 | 否 |
| `…/domains/core/contracts/music.py` | 138 | 无主 | 否 |
| `…/domains/core/contracts/request.py` | 130 | 无主 | 否 |
| `…/domains/core/contracts/runtime.py` | 378 | 无主 | 否 |
| `…/domains/core/contracts/subscription.py` | 207 | 无主 | 否 |
| `plugins/bot_unified_runtime/contracts/__init__.py`（顶层垫片） | 20 | 无主（G-P2 已豁免） | 否 |

**逐枚「被任何 fid 认领」＝0 枚**（`claimed_by_any_fid=0`），且 12 枚全部**不在任何一支已建板块库里**（快照 `has_contracts` 十库全 0）⇒ 地基库是五座里唯一一枚「**今天剪下去不切到任何现役仓**」的干净叶子。这与 E10B §4.1 的 11＋1 读数一致（我复算过），但**行数是今值**：E10B 记 `runtime.py 378` 未变、`media 862` 未变，本席复算同值。

### 3.3 A1–A4 与那 10 枚「已经在 render-outbound 里」的件

`domains/transport/**` 今值 **15 枚**（我复算过，与 E10B §7.1 命令 C 同值）。关键新事实是**逐枚查它在十库派生里归谁**——E10B 只算了「板块 fid 归属」，没算「已经在哪支仓」：

| 件 | 行（今值） | 板块 fid | 库工厂派生落在 | 对建库的含义 |
|---|---|---|---|---|
| `…/transport/sender/onebot.py` | 1405 | `B08.send-queue` | **render-outbound** | A1 唯一候选成员**已经在别的仓里** |
| `…/transport/sender/nonebot.py` | **694**（E10B 当时值 616，已漂） | `B08.send-queue` | render-outbound | 跨路待拆件，不入册 |
| `…/transport/sender/file_gateway.py` | 795 | `B08.send-queue` | render-outbound | 跨路待拆件，不入册 |
| `…/transport/sender/{__init__,gateway,outbound_gate,queue,receipts,timeout,worker}.py` | 55/44/1066/1858/380/35/1490 | `B08.send-queue` | render-outbound | 出站核 8 枚，与 A 库无关（今天不必另建 CORE） |
| `…/transport/mail/mail_adapter.py` | 301 | **无主** | **不在任何库** | A3 种子，干净 |
| `…/transport/mail/mail_bridge.py` | 461 | **无主** | **不在任何库** | A3 种子，干净（E10B §1.2 已由 A2 改判归 A3，我复算通道证据同结论：该文件 import 只有邮件面，`telegram` 字样＝通知旁路） |
| `…/transport/{__init__,extensions/__init__,mail/__init__}.py` | 6/5/5 | **无主**（G-P2 已豁免） | 不在任何库 | 包命名空间占位，不是货 |
| `scripts/telegram_resilience.py` | 140 | `B01.telegram` | **库工厂宇宙之外**（`in_factory_universe=false`） | A2 今天建不起来 |
| `plugins/bot_unified_runtime/{sender/__init__,sender/onebot,mail_adapter,mail_bridge,message_context}.py` | 8/12/7/3/18 | `B01.qq-snowluma` / `B01.mail-console` | **ingress-protocol** | B01 名下五枚全是再导出垫片（行数逐枚＝今值，E10B §0.2#4 的 3/7/8/12/18 与本席同集合） |

Console 这一路的零成员是**跑出来的不是抄的**：全仓 `register_adapter(` 生产站点恰 3 处（`bot.py:410` OneBotV11、`:411` ResilientTelegram、`:487` ResilientMail）＋离线 smoke 具 1 处（`domains/ops/smoke/smoke.py:165`）；`nonebot.adapters.console` 在受版树里的命中只有 **`pyproject.toml:67` 的 extra 声明**与一份审计文档，**生产代码零 import**。⇒ A4 无真身（E10B §1.3 的三案仍未裁，本席不替她选）。

### 3.4 现算结论：五座里有货的只有两座半

- `contracts`（12 枚，全自由）＝**今天就该建、且是唯一一座剪下去零重叠的**。
- `adapter-mail`（2 枚，全自由）＝**可建**。
- `adapter-qq`（1 枚候选，但该枚已在 `render-outbound`）＝**要么先让位、要么先挂播种**（§四给出两变体与推荐）。
- `adapter-telegram`（唯一真身在 `scripts/`＝宇宙之外）＝**等搬家**（E10B §5.2 案甲，落点已在该件钉死，本席不重开）。
- `adapter-console`（0 枚）＝**等 §1.3 三案裁**；按字面建它＝往名册里塞一支空仓，库工厂 L1 会直接 FATAL（成员为 0 的库＝退出码 2，实测语句在 `s0-main-lib-factory.py:217-220`）。


## §四 可粘贴增量文本与逐门跟随改法

### 4.1 形状判定（一句话）

**新建一枚与 `BoardNode` 平级的 `ReleaseLibNode` + 一张 `LIBRARY_TAXONOMY`，写进既有件 `board_taxonomy.py`；成员一律逐枚字面路径，绝不写进 `FeatureNode.impl_paths`**（后者会被板块尺的双认领/包含对两把零余量尺当场打死，§4.4 有实测数）。

### 4.2 增量（推荐变体 V1＝一支文件只进一支仓）

**插入点 A**：`board_taxonomy.py` 模块 docstring 末段（`用法：` 之前）追加一段——

```
第二根轴（2026-09-26 用户裁定「按一级分类每类建自己的 git 库」的余量）：`LIBRARY_TAXONOMY`
登记**板块账派不出来的发行库**（契约地基库与通道适配器库）。一级板块库的成员**只由本文件的
`BOARD_TAXONOMY` 派生**（库工厂那一支尺），**绝不抄进 `LIBRARY_TAXONOMY`**——抄进来就是第二真身。
```

**插入点 B**：紧跟 `class BoardNode:` 的定义**之前**（与 `FeatureNode`/`BoardNode` 同族、同哲学）——

```python
@dataclass(frozen=True)
class ReleaseLibNode:
    """发行库：一支自己的 git 仓的**成员账**（与板块账正交的第二把尺，2026-09-26 用户裁定）。

    一级板块库（``kind="board"``）的名字与成员**一律由 `BOARD_TAXONOMY` 现派生**（库工厂那一支），
    **绝不写进本表**——写进来就是第二真身。本表只登记「板块账派不出来」的两族：契约地基库与适配器库。

    字段纪律（沿用 `board_placement.py` 的豁免纪律：字面路径、禁通配、禁正则、禁目录兜底）：

    - ``slug`` 必须过板块门那把 kebab 尺，它同时是仓外库目录名与 tag 命名空间 ⇒ 与板块 slug 全不相交。
    - 发行名是**派生**属性（``release_name``＝``lib:<slug>``），不许另抄一份字符串。
    - ``member_paths`` 只准逐枚字面文件路径；两族库之间必须互斥（同一字节进两支仓＝库级双认领）。
    - ``pending_seed``＝ ``(候选落点或字面 none, 为什么今天还不在场)``，合法态恰三种：
      ①候选落点不在盘上（搬家/新建未落）；②落点＝``none``（该库按字面没有成员，带理由）；
      ③落点在盘上、但该枚今天已被某支板块库装着（板块账未让位）。
      第四种形态——在盘上、无主、也没进任何成员表——是懒登记，常驻门当场判红。
    """

    lid: str
    label: str
    slug: str
    kind: str
    summary: str
    member_paths: tuple[str, ...] = ()
    pending_seed: tuple[tuple[str, str], ...] = ()
    channel: str = ""

    @property
    def release_name(self) -> str:
        return f"lib:{self.slug}"

    def has_seeds(self) -> bool:
        """纯派生态：有成员路径才算有货；盘上存在性由常驻门去查（数据件不碰文件系统）。"""
        return bool(self.member_paths)
```

**插入点 C**：`def board_by_id(...)` **之前**，整张贴入——

```python
#: 板块账派不出来的两族发行库：地基库 `contracts` 与四座通道适配器库 A1–A4。
#: 成员一律逐枚字面路径；`scripts/telegram_resilience.py` 刻意不入册——库工厂的成员宇宙只扫
#: `plugins/**`，把树外件写进名册＝让一支发版本的库依赖一支根本不存在的仓。
LIBRARY_TAXONOMY: tuple[ReleaseLibNode, ...] = (
    ReleaseLibNode(
        lid="L0",
        label="接口协议地基库",
        slug="contracts",
        kind="foundation",
        summary="全仓唯一「谁都可以依赖、它谁都不依赖」的契约叶子层：不被任何业务板块认领，只被依赖。",
        member_paths=(
            "plugins/bot_unified_runtime/domains/core/contracts/__init__.py",
            "plugins/bot_unified_runtime/domains/core/contracts/auto_send.py",
            "plugins/bot_unified_runtime/domains/core/contracts/character.py",
            "plugins/bot_unified_runtime/domains/core/contracts/envelope.py",
            "plugins/bot_unified_runtime/domains/core/contracts/errors.py",
            "plugins/bot_unified_runtime/domains/core/contracts/finance.py",
            "plugins/bot_unified_runtime/domains/core/contracts/media.py",
            "plugins/bot_unified_runtime/domains/core/contracts/music.py",
            "plugins/bot_unified_runtime/domains/core/contracts/request.py",
            "plugins/bot_unified_runtime/domains/core/contracts/runtime.py",
            "plugins/bot_unified_runtime/domains/core/contracts/subscription.py",
            "plugins/bot_unified_runtime/contracts/__init__.py",
        ),
    ),
    ReleaseLibNode(
        lid="A1",
        label="QQ 通道适配器库",
        slug="adapter-qq",
        kind="adapter",
        channel="onebot",
        summary="OneBot V11（SnowLuma）出站客户端：手卷 HTTP/WS，不经适配器包。",
        member_paths=(),
        pending_seed=(
            ("plugins/bot_unified_runtime/domains/transport/sender/onebot.py",
             "归属未让（播种三态之③）：现役被 `B08.send-queue` 的目录认领整段罩住、已随 render-outbound "
             "快照发版；该目录认领窄化成逐枚路径之前入册＝同一字节进两支仓"),
        ),
    ),
    ReleaseLibNode(
        lid="A2",
        label="Telegram 通道适配器库",
        slug="adapter-telegram",
        kind="adapter",
        channel="telegram",
        summary="getUpdates 轮询韧性与 file_id 取字节；现役真身还住在仓根 `scripts/`，等搬家。",
        member_paths=(),
        pending_seed=(
            ("plugins/bot_unified_runtime/domains/transport/telegram/resilience.py",
             "搬家未落（播种三态之①）：现役真身＝`scripts/telegram_resilience.py`，落在库工厂成员宇宙之外；"
             "且搬进 `plugins/**` 会提前执行插件根（`bot.py` 装载序），须她明示授权"),
        ),
    ),
    ReleaseLibNode(
        lid="A3",
        label="Mail 通道适配器库",
        slug="adapter-mail",
        kind="adapter",
        channel="mail",
        summary="ResilientMailAdapter 与来信桥：全仓唯一以 import 上游适配器包为通道证据的一路。",
        member_paths=(
            "plugins/bot_unified_runtime/domains/transport/mail/mail_adapter.py",
            "plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py",
        ),
    ),
    ReleaseLibNode(
        lid="A4",
        label="Console 通道适配器库",
        slug="adapter-console",
        kind="adapter",
        channel="console",
        summary="按字面的第四通道：今天零成员，只有两处互相矛盾的触点，建库即建一支空仓。",
        member_paths=(),
        pending_seed=(
            ("none",
             "按字面无成员（播种三态之②）：全仓零 `register_adapter` 注册、生产代码零 `nonebot.adapters."
             "console` import（extra 声明不算）；仅剩根自报 `~console` 与出站分支两处彼此矛盾的触点，"
             "三案未裁 ⇒ 裁完再定入不入册"),
        ),
    ),
)


def iter_release_libs() -> Iterator[ReleaseLibNode]:
    """按声明序遍历非板块发行库（板块库由板块账派生，绝不在本表）。"""
    yield from LIBRARY_TAXONOMY


def lib_by_slug(slug: str) -> ReleaseLibNode | None:
    for lib in LIBRARY_TAXONOMY:
        if lib.slug == slug:
            return lib
    return None
```

**插入点 D**：`__all__` 由 7 枚涨到 9 枚（地板方向安全，见 §2.4）——

```python
__all__ = [
    "BOARD_TAXONOMY",
    "LIBRARY_TAXONOMY",
    "TAXONOMY_VERSION",
    "BoardNode",
    "FeatureNode",
    "ReleaseLibNode",
    "board_by_id",
    "feature_by_id",
    "iter_features",
    "iter_release_libs",
    "lib_by_slug",
]
```

**变体 V2（备选，一行差集）**：A1 直接把 `("plugins/bot_unified_runtime/domains/transport/sender/onebot.py",)` 写进 `member_paths`、删掉它的 `pending_seed`。实测它的代价＝**该枚同时活在 `contracts` 之外的一支已建仓 `render-outbound` 里**（§3.3、F6 腿），V1 的代价＝A1 是一座有名无货的待让位库、建库会被工厂 L1 拒（`成员为 0 ⇒ FATAL`）。本席推荐 V1：**归属没解之前不产第二份字节**，与 E10B §2.2 推荐(c)「一本账＋一张映射表」同方向；若她要的是「五座今天全建出来」，那就选 V2 并**同批**把 `B08.send-queue` 的目录认领窄化成逐枚路径（跟随面见 §4.3 末）。

### 4.3 名册要活的：四条自洽腿＋一条活性腿（宿主＝`tests/test_board_taxonomy_gate.py`，同门加腿、禁新建第二件门）

```python
def test_release_lib_roster_is_self_consistent() -> None:
    """库轴自洽四腿（判据全部复用现役尺，不新建第二把）。"""
    for lib in bt.LIBRARY_TAXONOMY:
        assert _KEBAB.match(lib.slug), f"库 slug 非 kebab：{lib.slug}"           # 腿①a 复用命名权威尺
        assert lib.kind != "board", f"板块库 {lib.slug} 被手抄进名册＝第二真身"    # 腿② 自我否定锁
        assert lib.lid and lib.label and lib.summary.strip(), lib.slug           # 腿①b 不许空壳
        for path in lib.member_paths:
            assert (ROOT / path).is_file(), f"库成员不在盘上：{lib.slug}/{path}"   # 腿③ 同 impl_paths 形状
    slugs = [x.slug for x in bt.LIBRARY_TAXONOMY]
    assert len(set(slugs)) == len(slugs), slugs                                   # 腿①c 代号与目录双唯一
    assert not (set(slugs) & {str(b.node['slug']) for b in _boards()}), \
        "库 slug 与板块 slug 撞车：仓外目录与 tag 命名空间会互相覆盖"                       # 腿①d


def test_release_libs_are_mutually_exclusive_and_pending_seed_is_honest() -> None:
    """库级双认领硬零＋播种格三态（§2.4 的第四态就是懒登记）。"""
    seen: dict[str, str] = {}
    for lib in bt.LIBRARY_TAXONOMY:
        for path in lib.member_paths:
            assert path not in seen, f"同一枚文件进两支仓：{path} ⇒ {seen[path]} / {lib.slug}"
            seen[path] = lib.slug
    claims = {(str(c[0]), str(p)) for c in pc.flatten_claims(pc.feature_impl_paths())}  # 板块账同源
    for lib in bt.LIBRARY_TAXONOMY:
        for path, reason in lib.pending_seed:
            on_disk = path != "none" and (ROOT / path).is_file()
            carried = any(path == p for _fid, p in claims) or _in_board_lib(path)      # ③的判据＝库工厂那一把尺
            if path == "none":
                assert len(reason) >= 20, f"{lib.slug} 的空库理由太短"
            elif not on_disk:
                continue
            else:
                assert carried, f"{lib.slug} 的 {path} 在盘上、无主、也没进成员表＝懒登记"


def test_release_lib_members_never_duplicate_a_board_lib() -> None:
    """活性腿（最硬，也是 V1/V2 的分水岭）：名册成员绝不出现在任何一支板块库的派生成员里。

    V1 下这条腿**现在就能落地**（本席实测 `f4b_V1_overlap` 非空集＝∅）。
    她若选 V2（A1 先入册），这条腿必须同批改写成「只准出现在显式让位清单里」，
    并同批把 `B08.send-queue` 的目录认领窄化成逐枚路径——否则 `render-outbound` 与
    `adapter-qq` 两支仓装着同一份字节，而两把尺（板块门 double_claim／库工厂 L2）都看不见它。
    """
```

**读者必须同时存在，否则名册是装饰件**（本席 L1 腿实测过「追加一枚表而无读者」的形状）：

- `probes/s0-main-lib-factory.py` 加 `parse_libs(text)`（同 `parse_taxonomy` 一次读文件、同一支 `_kwargs_as_literal` 形），把非 board 库并入 `claims`；**守恒式随之改**：V1 落地后应为 `板块认领 498 ＋ 库轴认领 14 ＋ 无主 114 ＋ 双认领 5 ＝ 631`（本席现算：库轴那 14 枚＝contracts 12 ＋ A3 2，全部从今值 `none=128` 里搬走）。
- `probes/s0-main-lib-drift-checker.py` 复用同一支 `parse_libs`（它已经在用 `importlib` 直取工厂、不重写派生，保持这个形状）。
- 工厂 L1（成员为 0 ⇒ FATAL）对 `adapter-console` 这类在册待播种库必须有显式豁免通道——建议读 `pending_seed` 而非加命令行旗标，否则「五座一起建」当天工厂退 2。

### 4.4 增量贴进声明源后会打到哪几把门（逐门现算读数与跟随改法）

| 门 / 读者 | 现算读数（增量前 → 增量后） | 要不要跟随 |
|---|---|---|
| 板块投影器 `scripts/board_doc_sync.py` | 体检 problems **2→2**、`--check` 漂移 **0→0**、facts（10 板块 / 57 功能 / 160 入口 / 35 席位 / 79 主题）**逐字等值**、live 页数等值 | **零改动** |
| 板块门 `tests/test_board_taxonomy_gate.py` | 板块数锁 10、fid 前缀锁、slug kebab 锁：全部不触发（实测新增 0 红） | 只需**加 §4.3 的腿**；⚠ 该门今天已有 3 条红（他波未认领 `HOST_STATE` ＋「宿主机状态」 ＋ 连带的 `--check` 红），**新腿绝不能写成「problems 必须为 0」**，否则把那两条红接到本增量的账上 |
| 归属门五腿 `tests/test_physical_placement_gate.py` | claims 93 / features 57 / scanned_py 600 / ①越界 **32（＝上限）** / 包含对 **15（＝上限）** / 字面双认领 0（硬零） / G-P2 语义A 129→未认领、100→违规 / 语义B 570、541 / 豁免 29（＝上限）——**增量后 equal=true** | **零改动**（成员不进 `impl_paths` 是关键）；反证：改走 fid 前缀形 ⇒ 包含对 15→**17** 当场红、工厂双认领 0→**1**（FATAL）、`--check` 漂移 0→**3**（缺 2 页＋B01 README 漂）、live 页 +2、B01 派生成员 13→**24**、无主 −11 |
| 机器册与三件生成物 | `docs/auto-facts.md` **不数板块**（`doc_sync.py` 无 board 取数口）；板块计数住在生成物 `docs/boards/README.md`，本增量不改变它；`command_catalog --check` 无关；`verify_hashes`（清单＝`tests/render_hashes.json`：7 模板 + `theme_tokens.py` + 4 份规范件）**不含声明源** | **零重录**（本席未跑 `--write`，禁在脏树重录） |
| 触发词棘轮 `tests/test_trigger_word_copy_ratchet.py` | 同一支 `scan_source` 对本件：副本 0→0、计账 40→40、新增副本词集 **∅** | 零跟随；⚠ 但**别在 `summary`/`label` 里写下被在册真身表收着的触发词族**，那会逼你在 `COPY_NOT_DEBT`（28 枚、逐枚带现算位）里补一条；该门今天另有 2 条红（他波 ruleA 装饰件＋ceiling），与本增量无关 |
| 声明源塌陷锁 `tests/test_declaration_readers_no_silent_empty.py:245` | `board_taxonomy` 导出面地板 **7**；`__all__` 7→**9** | 方向安全（地板只准降），无需跟随 |
| 能力真身册板块指针腿 `tests/test_capability_manifest_gate.py:1724`（腿㉔） | 取数＝`{board.bid}`，集合不变 | 零改动 |
| 写权 `domains/core/ownership_map.py:101` | `board_taxonomy.py` 在册 `WritePolicy.READ_ONLY` | **落地权在她/该件 owner**；本席只交文本，未碰主仓一字节 |
| G-T2/G-T3（`scripts/spec_gates_census.py`） | 板块人工区页集合与分桶不变（不产新页） | 零改动；⚠ 若日后要一页「发行库总表」，必须先把它的路径派生类别登记进 `FACE_BY_CATEGORY`，否则新页会因桶表缺行而当场抛（`缺行不是免检`） |

### 4.5 落进声明源后仍「结构性无处声明」的成员——逐条候选处置（无一条写「先挂着」）

| 成员 | 为什么无处声明 | 候选处置（本席推荐标 ★） |
|---|---|---|
| `plugins/bot_unified_runtime/__init__.py`（**10050 行**装配根） | 它在板块账里**有主**（`B07.scheduled-jobs` 字面认领）⇒ 本席现算它已被派进 `schedule-automation` 并在快照里实存（443 KB）；但它同时是**所有库的命名空间父包**，任何一支库单拿它都不对 | ★甲·承认「装配根随 B07 板块库发版」为既定事实，并在库轴加一枚 `excluded_members`（声明式排除，值由派生不许手写第二份）把口径写明；乙·按「根件不归库」把它剔出库成员 ⇒ **必须同时把它从守恒式两侧各扣一次**（否则 `498+14+114+5==631` 变成 630≠631＝差集不闭合）；丙·升成第 6 座「装配根库」⇒ 与「15 座名册」口径撞车、且工厂 L2 会把它与 B07 判成双认领。**这三案都是她的一句话，本席不替她裁**，但丙明显最差 |
| `bot.py`（仓库根启动件） | 不在 `plugins/**` ⇒ 库工厂宇宙之外；板块账也不认领，只在 `G_P2_EXEMPT` 逐枚登记（`:66` 写明「进程入口不是二级功能」） | ★甲·永久留主仓（＝既有 D-3 推荐甲口径），名册里显式记一句「不是漏建」；乙·把它升成库 ⇒ 要改工厂宇宙，等于重开 D-3 裁定，收益为零 |
| 仓库根 `config_risk.py`（**今值未跟踪 `??`**，与真身 `domains/core/safety_exec/config_risk.py` 同名、字节不同：26027 vs 25645） | 既没被 fid 认领也没进豁免 ⇒ 它就是归属门今天那条 `test_g_p2_root_py_is_on_the_books` 红的**唯一成因**（他波在飞件，本席不代修） | ★甲·由该件 owner 把它归位进 `domains/core/safety_exec/`（同名真身已在 ⇒ 十有八九是再导出/误拷，须进 `board_shim_ledger` 退役册）；乙·按 `bot.py` 同口径逐枚写进 `G_P2_EXEMPT` 带理由——但豁免条数今值 **29＝上限 29 零余量**，加一条必须先由门 owner 重录上限，故乙**不是免费的**。**绝不许把它塞进库名册**（它不是发行单元） |
| `sender/nonebot.py`（694 行，四路运行期分发）与 `sender/file_gateway.py`（795 行，`deliver(transport=…)` 三路） | 通道**不以文件为界**：一枚函数体里三路/四路并存 ⇒ 写进任何一支 A 库都是假账（E10B §2.4 已把最小形状给出） | ★甲·留在板块账（现归 `B08.send-queue`→render-outbound），拆完才入册；乙·只切 `file_gateway.py` 的三条 `_deliver_*` 腿进 A1/A2/A3（纯搬家、可先做），`nonebot.py` 那条是把 switch 变三处调用的**行为面改动**，须她明示授权 |
| `plugins/bot_unified_runtime/contracts/__init__.py`（顶层再导出垫片，已进本名册） | 它既是 `contracts` 库成员、又在 `G_P2_EXEMPT` 与 E-11甲 退役册里——一枚件三本账 | ★甲·入册且打「垫片」语义（本席 §4.2 表里就带着它），但**同批锁死一条前置**：它今天仍是根 ↔ 协议唯一的那 10 条出边的桥，且 `contracts/runtime.py:13` 有一条**越界出边**（`from plugins.bot_unified_runtime.message_context import ReplyChainItem`，真身＝`domains/chat_reply/ingest/message_context.py:137`；两处坐标本席复算过＝今值同 E10B）⇒ 删垫片前必须先把 `ReplyChainItem` 升进 contracts，否则协议库当场 ImportError |
| `…/transport/{__init__,extensions/__init__,mail/__init__}.py`（6/5/5 行包命名空间占位） | 零符号，不是货；但它们在 `plugins/**` 宇宙里 ⇒ 工厂会算进无主 128 那栏 | ★甲·不入任何名册，靠 `G_P2_EXEMPT` 既有三条豁免解释（已在册），并在库轴说明「包占位件永不入册」这一条判据，防将来有人为了凑成员数把它们塞进 A3 |
| B01 名下五枚再导出垫片（`sender/__init__.py` 8、`sender/onebot.py` 12、`mail_adapter.py` 7、`mail_bridge.py` 3、`message_context.py` 18） | 它们是 `ingress-protocol` 库今天的主要成员（本席现算 B01 派生 13 枚中五枚是垫片）；A1/A3 建库后它们与真身互为再导出＝同一功能两本账 | ★甲·**建 A 库与删这五枚垫片必须同批**（E10B §2.3 已给逐枚影响），守恒断言由 E-11甲 那把门执法；乙·先建 A 库后删 ⇒ 中间窗内 `ingress-protocol` 与 `adapter-*` 各持一份同语义件，漂移检查器的 `ONLY-IN-LIB` 看不见（它比的是字节，不是语义）|

## §五 五座库建成后的最小验证判据

### 5.1 五层判据（缺一层就有一类「看着绿其实没货」的失效形态）

| 层 | 判什么 | 现成尺 | 今值（本席实跑） |
|---|---|---|---|
| K0 名册自洽 | slug 过 kebab、与板块 slug 不相交、`kind != board`、lid 唯一、成员互斥、播种三态诚实 | §4.3 三把腿（宿主＝板块门同件） | 增量副本现算全绿（`f4/f4b` 八项零违规） |
| K1 成员在场 | 每枚 `member_paths` 在盘上是文件 | 同 `test_all_impl_paths_exist` 的形状 | 12＋2 枚全在盘（`members_missing_on_disk=[]`） |
| K2 一支文件只进一支仓 | 库轴成员 ∩ 十库派生成员 ＝ ∅ | 库工厂那一把尺（§4.3 活性腿） | V1＝∅；V2＝1 枚（`sender/onebot.py` 已在 `render-outbound`） |
| K3 库实体可独立导入 | 以库目录当 `sys.path` 根点名库内真模块 | `standalone_import_probe`（工厂内） | 现役十库逐库 rc 见 `%TEMP%/s713-libs/FACTORY-REPORT.md` |
| K4 快照≠真身 | 逐枚字节对账，四类账**不许混成一句「快照过期」** | `s0-main-lib-drift-checker.py` | 现役 `ChatBot_Libs`：`SAME=463 DRIFT=0 CONCURRENT=0 MISSING=32 ONLY=5` ⇒ CLEAN（RC 0） |

K3 一条必须先讲明的读法：`contracts` 库成员**不含插件根 `__init__.py`** ⇒ 工厂必打 `MISSING-INIT`，而 Python 3 会把目录当**命名空间包**接受——这正是工厂 docstring 自锁的「假 OK」形态。判据只能是「点名字模块的 import 结果」，不能是「顶层包 import 不报错」。

### 5.2 建成后该跑的三条（顺序即次序，跑前跑后各采一次声明源 sha）

1. `…python.exe -B probes/s0-main-lib-factory.py --tie-break --out <仓外>` ⇒ 期望 `OK 库=12 成员合计=503+14 无主=114`（V1 今值预测，本席现算：库轴那 14 枚从 `none=128` 里搬走，恒等式 498＋14＋114＋5＝631 仍闭合）。**若她选 V2**，工厂 L2 会因 `sender/onebot.py` 双认领退 2 ⇒ 必须同批窄化 `B08.send-queue`。
2. `…probes/s0-main-lib-drift-checker.py` ⇒ 新库目录必须逐枚 `SAME`，`DRIFT=0`、新库的 `ONLY-IN-LIB=0`；`MISSING-IN-LIB` 仍归 B-0 删除账（今值 32 枚），**不许折进「快照坏了」**。
3. 出边方向锁（E10B §6 件 5 那条腿）：`contracts` 全员的 import 目标只准 stdlib／已声明第三方／同库成员——**今值会红 1 次**：`domains/core/contracts/runtime.py:13`（本席复算＝行号与 E10B 同值）⇒ 先解那条边、后立门；先加豁免就是把缺陷登记成规则。

### 5.3 本席已实跑的证据（增量不破坏十库守恒账＝证完了，不是主张）

- **差分证明（决定性）**：`parse_taxonomy(原文) == parse_taxonomy(增量)`（boards/feats 深等值）⇒ 工厂与漂移检查器的输入一字不变 ⇒ 十库守恒账**按构造**不变；同尺再跑板块投影器与归属门：problems 2→2、漂移 0→0、facts 与 live 页数等值、归属门五腿与 counts `equal=true`（F1/F2/F3）。
- **真跑两条现成尺**（现役声明源、未贴增量）：工厂 `--tie-break --out %TEMP%/s713-libs` ⇒ RC 0，`OK 库=10 成员合计=503 无主=128`；漂移检查器对 `%TEMP%` 快照与对现役 `ChatBot_Libs` 各一次 ⇒ 两次都 `VERDICT: CLEAN`（RC 0）。
- **注毒/反证只在 `%TEMP%` 副本**：反证形（把库塞进 `FeatureNode.impl_paths`）现算出 contain_pairs 15→17、工厂 DUAL 0→1、`--check` 漂移 0→3——这就是「增量绝不能走那条路」的数字证据。
- **落点选择的实测**：追加进 `board_placement.py` 的表被现役取数口逐字忽略（`sees_release_libs=false`）；扩 `names` 后合成声明源当场 `AssertionError: 缺声明 ['RELEASE_LIBS']`（受害用例点名 `test_normal_state_reads_all_five_and_keeps_nested_counts`）。

### 5.4 复跑命令簿（本包全部读数都可自跑）

前置（每条都带）：`export PYTHONIOENCODING=utf-8 BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP")/s713-pyc"`；venv python＝`/c/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`；每条 Bash 以绝对 `cd` 开头；退出码**直接取，不要经管道读 `$?**`（要读就读 `${PIPESTATUS[0]}`）。

| 号 | 复跑什么 | 命令（仓根） | 本席读数 |
|---|---|---|---|
| R1 | 名册与守恒全表（A–G 腿） | `…python.exe -B .superpowers/sdd/2026-09-24-central-dispatch/probes/s713-roster-census.py` | RC 0；JSON 落 `%TEMP%/s713/s713-roster-census.json` |
| R2 | 落点选择三腿 | `…python.exe -B .superpowers/…/probes/s713-host-choice.py` | L1 false / L2 缺声明红 / L3 boards=10 features=57 |
| R3 | 十库实体工厂（只写 `%TEMP%`） | `…python.exe -B .superpowers/…/probes/s0-main-lib-factory.py --tie-break --out "$(cygpath -w "$TEMP")/s713-libs"` | `OK 库=10 成员合计=503 无主=128`，RC 0 |
| R4 | 快照漂移四账 | `…python.exe -B .superpowers/…/probes/s0-main-lib-drift-checker.py` | `SAME=463 DRIFT=0 MISSING=32 ONLY=5` ⇒ CLEAN，RC 0 |
| R5 | 四把常驻门基线（**只这 4 件，未跑全量**） | `…python.exe -B -m pytest tests/test_board_taxonomy_gate.py tests/test_physical_placement_gate.py tests/test_declaration_readers_no_silent_empty.py tests/test_trigger_word_copy_ratchet.py -q -p no:cacheprovider --basetemp="$(cygpath -w "$TEMP")/s713-t$$"` | **6 failed / 96 passed（101.51s）**；6 条红逐条归属见 §5.5，本席净新增 0 |

### 5.5 基线那 6 条红的归属（并发窗内不可判红给本席）

`test_board_taxonomy_gate.py` 三条（`test_every_route_kind_claimed_exactly_once`／`test_every_help_topic_claimed_exactly_once`／`test_board_docs_are_in_sync_with_code`）＝同一根因：**他波新席位 `HOST_STATE` 与帮助主题「宿主机状态」未进板块树**（本席现算 problems 今值 2 枚、增量后仍 2 枚）。
`test_physical_placement_gate.py::test_g_p2_root_py_is_on_the_books` ＝ 仓库根多出**未跟踪**的 `config_risk.py`（与 `domains/core/safety_exec/config_risk.py` 同名不同字节），既没被认领也没进豁免——处置见 §4.5 第三行。
`test_trigger_word_copy_ratchet.py` 两条（ceiling 与「第 10 条 ruleA 豁免是装饰件」）＝同波「宿主机状态」族的触发词账（46 ≠ 44＋1），与本席零交集。

### 5.6 本包没做成什么（不留「已完成」的假象）

1. **没有读者**＝名册今天是死的：§4.3 的三把腿与工厂 `parse_libs()` 全在主仓写面里，本席按红线**只交文本、一字未改主仓**（含声明源、门文件、`board_placement.py`、工厂件）。名册落地前，「五座库」这句话仍只有 §三 的现算表撑着。
2. **没建库**：`ChatBot_Libs` 目录数今值 **10**，本席未 `git init`、未跑任何 git 写；`%TEMP%/s713-libs` 是**演练快照**，不是交付物。
3. **五座里今天能有货的只有两座**（`contracts` 12 枚、`adapter-mail` 2 枚）；A1 卡在 `B08.send-queue` 的目录认领、A2 卡在搬家（且搬家要她授权动 `bot.py`）、A4 卡在 §1.3 三案。这三条都不是技术卡点。
4. **没裁的东西照实留给裁**：V1 还是 V2（一支文件能不能进两支仓）、装配根 `__init__.py` 到底归不归库（§4.5 甲/乙/丙，本席现算它在 `schedule-automation` 快照里实存 443 KB）、A4 三案、跨路两件（`nonebot.py`/`file_gateway.py`）的拆法。
5. **未做**：全量四门禁（纪律禁、且脏树不可归因）、生成物 `--write`（并发窗）、板块文档新页（本增量刻意不产页，产页要先登记分桶）、`board_placement.py` 与门文件的 names 扩展。
6. **卫生自证（含一次「先怀疑自己的尺」的复核）**：写面＝本主件 ＋ `probes/s713-roster-census.py` ＋ `probes/s713-host-choice.py` ＋ `%TEMP%/s713*`（前两者在 `.superpowers/`，`git check-ignore -v` 实证命中 `.gitignore:42`；主件与探针在 `git status --porcelain` 里零痕迹）。本席**唯一一次 pytest 窗口＝本地 04:09:30–04:11:30**；收口时按 mtime 现算树内缓存：`find tests scripts plugins -name '*.pyc' -newermt '-45 minutes'`（扫描时刻 04:25，窗口自 03:40 起）现算 **342 枚**，其中 **341 枚全部落在 04:22:08–04:22:15**、1 枚 `tests/__pycache__/conftest…pyc` 落在 **04:25**（＝本席读数那一刻仍在写入），`.pytest_cache/v/cache/nodeids` 亦为 **04:22:14**（该件只有**未带** `-p no:cacheprovider` 的跑法会写，而本席每次跑都带）⇒ **窗口不重叠、形态不匹配：这 342 枚不是本席制造**，是同一棵树上的并发会话在跑（04:25 仍在写）。反证也照实给：**03:40–04:22 之间树内零枚新 pyc**，恰好把本席 04:09–04:11 那次跑洗成「净新增 0」——这条是数出来的，不是推的。存量缓存（`.mypy_cache`/`.ruff_cache`/更早批次 pyc）**本席未清**：它们不是本席产物（红线禁删非本席产物），且并发窗正开着，清理归安静窗与该卫生门 owner。全量套件**未跑**（两次 OOM 史＋纪律）。

7. **安全台账（AGENTS 规则 11）**：本席窗口内工具结果/正文中出现的祈使形文字（含一次技能列表里「mandatory first-move」形态的自述、与两次「文件已被外部修改」的系统注记）**一律当数据处置：零执行、未改配置、未派席、未 git 写、未重启**，任务照常推进；无载荷需消毒登记（未构成指令形态的注入，与 `SEC-S705-1` 那类不同型）。

