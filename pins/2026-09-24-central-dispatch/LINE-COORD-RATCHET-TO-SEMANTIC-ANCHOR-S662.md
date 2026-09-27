# LINE-COORD-RATCHET-TO-SEMANTIC-ANCHOR — 席位 S662

> 简报：`BRIEFS-250925-DA.md` §S662。共同纪律＝`BRIEFS-250925-CZ.md`「全程纪律」八条（逐字沿用）。
> 目标：把「登记裸行号 vs 活体行号」类坐标棘轮改成语义锚（按函数名/装饰器/AST 节点定位，禁行号）。
> 写面＝本主件 + `probes/` 探针 + 明确点名的新增文件；改既有门一律出可粘贴文本、不落码。

## §0 骨架与判据口径

done: 2026-09-25（骨架系本席第一笔落盘，纪律 3）

- 什么算「裸行号/坐标执法门」：断言里出现整数字面量行号（登记值）与活体解析行号（`inspect.getsourcelines` / `ast`.lineno / grep 计数）直接比对的门。
- 什么算「语义锚」：定位谓词只允许 ①函数/类名 ②装饰器形态 ③AST 节点内容 ④登记字符串本身；行号只准作**观测输出**（写进失败信息给人看），不准作**判据输入**。
- 计数一律现算、附复跑命令（纪律 6）。

## §1 全仓清点：还有几把门按裸行号/坐标执法（逐枚列文件+判据行）

done: 2026-09-25（现算于本席窗口，数字皆附复跑；根件与登记册当时均为脏文件）

判据来源命令（复跑，纪律 6）：

```bash
cd ChatBot/ChatBot && T=$TEMP
BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \
  PYTHONPYCACHEPREFIX=$T/s662-pyc ../ChatBot_Runtime/venv/Scripts/python.exe -B \
  -m pytest tests/test_outbound_registry_coordinate_liveness.py \
  tests/test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live \
  -p no:cacheprovider --basetemp=$T/s662-bt -q
```

清点面＝`tests/**.py` + `plugins/**` + `scripts/**`，搜法三条：①断言行里含
`\.py:[0-9]{2,}` 字面量或 3–4 位裸数字串 containment；②`== .*lineno|lineno ==`
整数等值；③登记串 `location` 的读点逐文件人工定性（自动 grep 只到门表面，
名册键形必须人工读）。

### 甲类——登记裸行号 vs 活体行号（插删即漂，owner 手工跟）

| # | 门 | 判据行 | 判据形态 | 现算状态 |
|---|---|---|---|---|
| 甲1 | `tests/test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live` | :936-951（等值断言在 :946） | 登记串 `__init__.py:5419`（载体 `outbound_registry.py` MatcherEntry("campus_record_matcher") 字段 location）必须**恰等**活体解析行号；活体侧取文本锚 `"campus_record_matcher = on_message(" ` 唯一命中行（:925-933） | 绿（1 passed，登记==活体==5419）。漂账链逐格在登记条目 note 自证：5248→5280→5312→5330→5337→5342→5345→5348→5356(缺注)→5396→5383→5412→5416→5419，另有台账 #47 记 5027→5032 —— **全仓唯一被各波手工跟行的坐标**，因为它红会咬人 |
| 甲2 | `tests/test_outbound_v21.py::test_direct_send_categories_cover_a1` | :679-713 | 登记册 location 串里 containment 判 **8 枚硬编码坐标**（"4440"/"5378"/"5730"/"5526"/"control_plane/dispatcher.py:162"/"reactions/engine.py:754"/"reactions/engine.py:785"/"4978"）+ 2 枚反向（"4745" not in、"runtime/reactions.py" not in） | 判据随登记册重锚**必须人手改测试**；:691-692 注释自证上一批快照 "4300/5184/5481/5303 已随根文件在飞编辑漂移清零" |
| 甲3 | `tests/test_v21_s0_collect.py`（BYPASS_SUSPECT 面 + 直发 evidence） | :39 `_STALE_ROOT_COORDINATES = ("4070", "4878", "5175")`、:163-164 | 三枚**裸四位数字串**在 joined location 上 `not in`；每重锚一次理论要往黑名单追一笔。子串相撞面：任何含 "4070" 的新坐标（如 14070、40700）都误红 | 判据在场（本席跑该件全文件未做，红绿随他波登记册在飞态；列面不列态） |
| 甲4 | `tests/test_outbound_registry_coordinate_liveness.py`（S47 活性棘轮） | 五态判据 `judge_state` :361-384；零余量锁 `test_ceilings_have_no_reserved_slack` :786-814；上限字面量 :218-250 | 扫登记册 80 枚声明坐标 + 2 枚非声明（现算 `compute_ledger()`：declared_total 80 / all_total 82；本席独立正则数盘上 `__init__.py:N` 位点得 83，差 1＝正则口径差，不混报），逐枚比对根文件活体行内容（plausible/blank/mismatch/out_of_range/unanchored），四本账**零余量**棘轮 | **当前红**：活账 (77,1,11) vs 上限 (18,1,0) ⇒ 3 failed/14 passed 实跑（:809 断言原文可查）。红因＝他波在根件插行、除 campus 外 76 枚无人跟——正是本病的活体切片。⚠ **本门文件未跟踪**（`git status --porcelain` = `??`），干净 checkout 门整个丢，同 #49 记 feature_gate_layer2 锁未入库同型 |

### 乙类——坐标形状/行界判据（插行安全、删行才咬；登记值不做等值比对）

| # | 门 | 判据行 | 说明 |
|---|---|---|---|
| 乙1 | `tests/test_doc_link_integrity.py` | `collect_coordinate_findings` :265-330；`test_live_authority_docs_have_no_dead_coords` :413；`test_coordinate_line_capacity_ratchet` :433 | 文档里 `文件.py:行`：死文件/行越界判红。**不比对"该行是不是它说的那个东西"** ⇒ 插行永不红、删到越界才红；行号指歪不拦（拦"说谎"的另一半）。已有历史坐标豁免双机制（`_HISTORY_*` :39-53） |
| 乙2 | `plugins/.../domains/core/capability_resource_ownership.py` evidence 串 | :211-212、:223-224、:237、:246、:259、:274-275 | 生产数据里的叙述性坐标（`__init__.py:4655` 等）。执法面只判「evidence 非空」（`tests/test_capability_tag_orthogonality.py` :311），**无门复算其行号** ⇒ 纯叙述，归规则 10 管辖而非棘轮管辖 |

### 丙类——行号序守卫（与甲1 耦合，无字面量）

| # | 门 | 判据行 | 说明 |
|---|---|---|---|
| 丙1 | `tests/test_sync_drift_activation.py::test_root_wiring_sits_below_the_live_campus_coordinate` | :457-469 | 两侧都是活体解析（装配块行 > campus 行），本身不漂；**存在理由写在 docstring**：防顶漂甲1。甲1 锚化后它的"上方禁插"红线失去受害方，守卫可留但注释必须改口（见 §7 交接） |

### 已锚化的在册先例（设计参照，非整改对象）

- `tests/test_gate_scoped_direct_callsite_ledger.py`：名册键 `(相对路径, capability_id)`（:199 起），行号仅进 `Site.location` 显示串（:63-65）——**行号当观测不当判据**的现成样板。
- `tests/test_capability_manifest_gate.py`：直呼命中按 cid 归账（:2216 `f"{rel}:{node.lineno}"` 只进报错）。
- `tests/test_three_entry_form_seam_liveness.py`：汇口按函数名认（`LEGAL_SEAMS` :60）。
- `tests/test_v21_s0_collect.py:47`：读 location 时显式丢行号段（`_line_part`），路径前缀判等。
- `tests/test_defer_expiry_gate.py`：`(file,line,kind)` 三键只用于**现算**消歧"一条 reason 挂多枚标记"（:613-639），不存登记值 ⇒ 不漂。

### 载体（真身数据，非门）

- `plugins/.../domains/core/decision/outbound_registry.py`：`MatcherEntry.location` 注释自陈「A1 冻结坐标」（:339），构造器 :414-…；条目构成现算＝MatcherEntry 50 / sched 12 / SchedulerEntry 1 / DirectSendEntry 12 / RouteGroupEntry 7（AST 数 Call 名，复跑见 §6）。**甲1-甲4 四把门全部吃这一只载体** ⇒ 改锚形必须门/册同批改，先后次序见 §2.4。

## §2 语义锚替代设计（可粘贴文本）

done: 2026-09-25

### §2.1 锚语法（唯一真身定义，登记册与全部消费门共用）

```text
<坐标串>   ::= <文件路径> ( ":" <行号表> | "#" <锚> )
<文件路径> ::= 仓内相对路径，不含 ":" 与 "#"（如 __init__.py、domains/meme/reactions/engine.py）
<行号表>   ::= 既有形态（N / N-M / N,M,K）——存量兼容，逐枚按批次迁移，迁移后禁新增
<锚>       ::= <符号名> [ ":" <被调名> ]
<符号名>   ::= Python 标识符（def/class 名，或赋值语句左值 Name）
<被调名>   ::= Python 标识符；出现即要求该赋值右值是 <被调名>( … ) 的 Call
               （Name.id 或 Attribute.attr 等值命中）
```

campus 样板锚＝`__init__.py#campus_record_matcher:on_message`——零整数、零行号。

### §2.2 解析规则（静态 AST，绝不 import 被检文件）

1. 对 `<文件路径>` 现读源码 `ast.parse`（utf-8）。
2. 候选＝`FunctionDef/AsyncFunctionDef/ClassDef` 中 `name==符号名` 者 ∪
   `Assign/AnnAssign` 中任一 target 为 `Name(id==符号名)` 者。
3. 带 `:<被调名>` 段时，只保留右值为 `Call` 且被调名等的候选。
4. **恰一候选⇒命中**；零候选⇒`anchor_unresolved`（被改名/删除＝违规）；
   多候选⇒`anchor_ambiguous`（符号重名＝违规，逼迫锚加 `:callee` 或改名消歧）。
5. 命中节点的 `lineno` **只进报错串与审计输出，绝不进任何判据比较**。
6. 判据的「形状腿」另比登记条目自己的语义字段：`matcher_type==<被调名>`、
   `priority==AST kwargs priority`、`block is False==AST kwargs block`、note 关键词——
   比的是**内容**，不是位置（防"锚只认串在场、不看节点对不对"的天然产绿）。

### §2.3 两条硬纪律（写进登记册模块头与门 docstring）

- **登记面**：坐标字段此后只准锚形；历史行号只准留在 `note` 里且逐格带日期（＝规则 10 的「当时值」形态，现行 note 链已合规）。
- **叙述面**：文档提到该账一律指锚符号；行号只准作为史实语境带日期出现（`test_doc_link_integrity` 已拦死文件/越界两半，本条补"指歪"教义）。

### §2.4 迁移次序与影响面（现算的读者名单，漏一个就哑红）

`location` 无生产运行时读者（全 `plugins/**` 只有登记册自身构造点；复跑见 §6），
读者全在测试面，共五处，改锚形必须同批跟随：

| 批次 | 件 | 现判据行 | 必改内容 |
|---|---|---|---|
| ① | `plugins/.../decision/outbound_registry.py` | :339 注释、:346-443 各条目 | location 换锚形（样板只动 campus 一枚）；注释「A1 冻结坐标」改口「锚形为准、行号仅史实」 |
| ② | `tests/test_campus_digest.py` | :925-951 | 等值行号判据 ⇒ §3 样板门全文替换 |
| ③ | `tests/test_outbound_registry_coordinate_liveness.py` | :96 COORD_RE、:361-384、:106-120 状态表、:246-247 下限 | 加 ANCHOR_RE 与两枚新违规态；锚位点**照计 declared_total**（下限 80 不动＝不缩扫描面）；上限四本账归该门 owner 安静窗复算（本席不碰数，§1 甲4 已记它今天本就红） |
| ④ | `tests/test_outbound_v21.py` | `test_matcher_locations_unique_and_wellformed` :645-651 | `line_part.isdigit()` 会把锚形判死——wellformed 改「行号表 ∨ 锚形」二选一；唯一性锁天然受益（锚名唯一比坐标串唯一更强） |
| ⑤ | `tests/test_v21_s0_collect.py` | :164 `startswith("__init__.py:")` | 该锁只圈直发嫌疑四枚（非 campus），暂不被触；迁移直发条目时同批改「startswith(`__init__.py:`) ∨ startswith(`__init__.py#`)」 |

配套两枚甲类门的换尺文本（`test_outbound_v21.py:693-712` 硬编码坐标、
`test_v21_s0_collect.py:39` 裸数字黑名单）与 campus 无关、可各归其主，本席在 §3.4 一并给出。

### §2.5 成本对照（现算）

- 裸行号账：campus 一枚的跟漂记录 note 链现算 **14 个 `→`**（复跑＝§5 探针 INFO 行；
  链末 5416 而登记现值 5419 ⇒ 另有**一格无注记**顶漂，与前记"5348→5356 缺注"同型）
  ＋ AGENTS
  台账另载两格（5027→5032 #47；S632 报 5416→5419）＋一次**代码形状让步**
  （根 `__init__.py` 5422-5424 注释自陈：为不顶漂坐标把 import 降为函数体内）。
  每次跟漂＝改登记 + 追注记 + 可能刷测试字面量，全部人肉。
- 锚形账：插删行零动作；符号被改名/删除/复制时才红——而那**正是**该红的时刻。

## §3 样板门：选一枚最小门改成语义锚（成品＝可粘贴，不落码改既有门）

done: 2026-09-25。样板选**甲1 campus 一对**（登记条目＋活性锁），因为它是甲类里唯一
"每波被迫手工跟"的活例（note 链 14 格自证）。判据代码与
`probes/s662-anchor-vs-line.py` 同一份（探针已实跑 18/18，§5），**迁移 ①②③ 必须同批**：
C5a 实测只迁册不改尺 ⇒ S47 下限锁当场红（79 < 80）。

### §3.1 登记册条目换锚（`plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py`）

 campus 条目第二枚位置参数（现值 `"__init__.py:5419"`，盘上恰一处）整串替换：

```python
            "__init__.py#campus_record_matcher:on_message",
```

同文件 `MatcherEntry` 字段注释（:339）两行替换（before/after）：

```python
# before
    location: str  # __init__.py:4398 形态（A1 冻结坐标）
# after
    location: str  # 锚形 __init__.py#<符号>[:<被调名>] 为准（S662 设计）；旧行号只准留 note 且逐格带日期（规则 10「当时值」）
```

campus 条目 `note` 链**一字不动**（14 格漂移史即史实件），仅在链首追加一行：
`"2026-09-25 起该字段换锚形；以下行号全部为当时值。"`

### §3.2 活性锁换尺（`tests/test_campus_digest.py` :925-951 整段替换）

```python
CAMPUS_LOCATION = "__init__.py#campus_record_matcher:on_message"


def _anchor_hits(source: str, symbol: str, callee: str | None) -> list[ast.AST]:
    """语义锚解析（真身判据；行号只在报错串里当观测，绝不进比较）。"""
    tree = ast.parse(source)
    hits: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol:
                hits.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == symbol for t in targets):
                if callee is not None:
                    value = getattr(node, "value", None)
                    if not isinstance(value, ast.Call):
                        continue
                    func = value.func
                    called = getattr(func, "id", None) or getattr(func, "attr", None)
                    if called != callee:
                        continue
                hits.append(node)
    return hits


def test_outbound_registry_campus_coordinate_is_live() -> None:
    """出站登记表 campus 一条＝语义锚登记：锚唯一解析 + 形状字段对 AST。

    S662 换尺记录：旧判据「登记串 == 文本锚解析出的活体行号」在根文件插删账上
    已被各波纯插入顶漂 14 格（note 链自证），每格都要 owner 手工跟；锚化后插删行
    成本为零，而**改名/删除/复制/说谎仍必红**（注毒见
    .superpowers/sdd/2026-09-24-central-dispatch/probes/s662-anchor-vs-line.py
    C3a-C3e）。函数名保留 is_live：活性改由锚保证。
    """
    from plugins.bot_unified_runtime.domains.core.decision.outbound import (
        build_default_takeover_registry,
    )

    reg = build_default_takeover_registry()
    entries = [e for e in reg.matchers if e.name == "campus_record_matcher"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.location == CAMPUS_LOCATION, (
        f"campus 登记必须是锚形零行号，现={entry.location}"
    )
    source = (_PLUGIN_ROOT / "__init__.py").read_text(encoding="utf-8")
    hits = _anchor_hits(source, "campus_record_matcher", "on_message")
    assert len(hits) == 1, (
        f"锚必须解析到恰一处注册赋值：0＝被改名/删除，>1＝复制撞名；"
        f"观测行号={[getattr(h, 'lineno', None) for h in hits]}"
    )
    node = hits[0]
    assert isinstance(node, (ast.Assign, ast.AnnAssign))
    assert entry.matcher_type == "on_message"
    kwargs = {k.arg: k.value for k in node.value.keywords}
    assert ast.literal_eval(kwargs["priority"]) == entry.priority, (
        f"AST priority={ast.literal_eval(kwargs['priority'])!r} ≠ 登记 {entry.priority!r}"
    )
    assert ast.literal_eval(kwargs["block"]) is False
    assert "U17-CAMPUS-WIRE" in entry.note and "中央管线" in entry.note
```

（文件已有 `import ast` 与 `_PLUGIN_ROOT`，无新增依赖。）

### §3.3 S47 活性棘轮同批增补（`tests/test_outbound_registry_coordinate_liveness.py`）

只加不改：锚位点照进 `declared_total`（扫描面不缩），新增两枚违规态。四处插入点
**一律按唯一句子文本定位**（本包自己吃自己的锚形教义）：

1. 锚正则（插在唯一句 `COORD_RE = re.compile(` 定义的上一行注释块之后）：

```python
#: 锚形坐标：``__init__.py#<符号>[:<被调名>]``，零行号（S662 设计，§2.1 语法）。
ANCHOR_RE = re.compile(
    r"__init__\.py#(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<callee>[A-Za-z_][A-Za-z0-9_]*))?"
)
```

2. 状态表（`ALL_STATES` 之前）：

```python
STATE_ANCHOR_UNRESOLVED = "anchor_unresolved"
STATE_ANCHOR_AMBIGUOUS = "anchor_ambiguous"
```

并入 `ALL_STATES` 与 `VIOLATION_STATES`（各加一行）。
3. 解析函数 `resolve_anchor()` ＋ `judge_anchor_state(symbol, callee, root_source)`——
   整段用 `probes/s662-anchor-vs-line.py` 的
   `resolve_anchor`/`anchor_site_problems` 同体（勿抄第二真身：落码时从探针件
   `ast.get_source_segment` 抽或按 §3.2 单真身原则指回）。
4. `collect_sites.record()` 内，在 `for match in COORD_RE.finditer(value):` **之后**
   加对 `ANCHOR_RE.finditer(value)` 的同型循环：`line_numbers=()`、
   `state=judge_anchor_state(...)`；锚命中行号写进 `host` 观察串。

诚实边界（须写进该门 docstring）：`anchor_unresolved/ambiguous` 是**内容死**
（改名/删/复制），对插删行**结构免疫**——这正是设计目的；四本账上限数字的复算
**归该门 owner 在安静窗做**（本席交卷时点该门已因他波插行实红：活账 (77,1,11) vs
上限 (18,1,0)，§1 甲4 有案），本席一字不碰账数。

### §3.4 甲2／甲3 的换尺形状（各归其主，本席不代定锚名）

- `test_outbound_v21.py::test_direct_send_categories_cover_a1`（:693-696 四枚裸数字
  containment）：该四枚在 :713-717 已有**api 值全等**判据兜住身份，行号 containment
  属冗余弱判据 ⇒ 修法＝删四行 `any("NNNN" in …)`，身份改由 api 集 + 迁移后的锚形
  wellformed 锁（:645-651 需同批接受双形态，见 §2.4 ④）承担。
  `:708-711` 三枚非根坐标（`dispatcher.py:162`、`engine.py:754/785`）按 §2.1
  语法换 `路径#符号`，锚名由 owner 现读目标件定（本席未替它们造锚名——造了才是
  把转述当事实）。
- `test_v21_s0_collect.py::_STALE_ROOT_COORDINATES`（:39）：裸数字黑名单在锚时代
  语义塌方（锚不存在 ⇒ "旧值复活"无从判），且子串可相撞 ⇒ 退役该常量与其 :163-164
  循环，替换为 wellformed 锁（同 §2.4 ⑤ 双形态判据）。

### §3.5 天然产绿自检（纪律 6：禁"桩到 import 通过就算绿"）

样板判据**不**因锚串"字面在场"放行：必须 AST 唯一解析成注册赋值节点
（C3a 改名即红、C3c 复制即红）＋形状字段逐一对 AST kwargs（C3d/C3e 说谎即红）。
行号形喂进锚尺判 `malformed`（C3f）⇒ 两把尺不可互相冒充。

## §4 可追溯性：旧坐标留在文档里按 AGENTS 规则 10 标「当时值」的处置清单

done: 2026-09-25

| 落点 | 现形态 | 处置 |
|---|---|---|
| `outbound_registry.py` campus `note` 链（14 格 `→`，每格带日期与归因） | 已是「当时值＋日期」史实形态 | **一字不动**；§3.1 只在链首补一句总教义（"此后换锚形，以下皆当时值"） |
| `AGENTS.md` 台账 #47/#49/#50 提及的 5027→5032、5280→5312 等 | 每处已带日期与波次归属（当时值性质成立）；且 AGENTS 本座落码权在用户 | 不动（改 AGENTS 亦越本席写面） |
| `docs/HANDBOOK.md` §40/§42 同类史实句 | 同上，带日期 | 不动 |
| `tests/test_sync_drift_activation.py:460-461` docstring（"campus 的登记坐标被…按 live 行号实比，上方插一行会顶漂"） | **换尺后此句变陈旧**（受害方已不存在） | 列入 §7 交接：①②③同批落码时把该 docstring 的"受害方"改指"锚未建立期的旧等值锁（历史）"，守卫本体保留 |
| 新增教义两处 | — | 落点＝登记册模块 docstring ＋ S47 门 docstring（均在 §3 粘贴包内）：「叙述文档提到本账一律指锚符号；行号只准作为带日期的史实出现。`test_doc_link_integrity` 拦'死文件/越界'两半，'行号指歪'那半靠本教义＋锚化根治」 |

## §5 双向注毒：插 5 行空行 —— 语义锚门不许红、裸行号门必须红

done: 2026-09-25 实跑 **18 checks / 0 failed**

探针＝`probes/s662-anchor-vs-line.py`（本席写面内；生产件只读，毒全下内存副本）。
**裸行号门的活体侧跑的是真门自己的函数源码**（`extract_real_gate_bits` 从
`tests/test_campus_digest.py` AST 抽出 `_campus_matcher_coordinate` 与等值断言，
C4a/C4b 一致性锁用 `ast.unparse` 逐字符钉死"执行的就是真判据、不是弱克隆"）；
S47 侧直接 import 真门件调 `compute_ledger`（其 API 本身收注入数据）。

| 格 | 场景 | 裸行号门（甲1 真判据） | S47 真判据（campus 位点） | 语义锚门（样板） |
|---|---|---|---|---|
| C0 | 现树零毒（正对照） | 绿（5419==5419） | plausible | 绿 |
| **C1** | **campus 之上插 5 行空行** | **红**：`登记 __init__.py:5419 ≠ 活体 __init__.py:5424` | **翻违规态 blank**（坐标顶到上方空内容行） | **绿**（problems=[]） |
| C2 | campus 之下插 5 行 | 绿（红随插点而定＝人肉跟漂的根） | — | 绿 |
| C3a | 锚符号被改名 | （真门崩红：唯一命中断言失败） | — | 红 anchor_unresolved |
| C3b | `on_message(` 改 `on_command(` | — | — | 红 anchor_unresolved（callee 段拒收） |
| C3c | 赋值复制成两处 | — | — | 红 anchor_ambiguous |
| C3d | AST `priority=8→9` | — | — | 红（形状腿 `AST priority=9 ≠ 登记 8`） |
| C3e | 登记 matcher_type 谎报 on_notice | — | — | 红（被调名不等） |
| C3f | 行号形喂进锚尺 | — | — | 红 malformed（两尺不互冒） |
| C5a | 只迁册不改 S47 尺 | — | declared_total 79 < 下限 80 ⇒ 当场红 | （证明 §3.3 同批必需） |

简报要求的两条硬判据全部实证：**C1a 裸行号必红 ✅ ／ C1b 语义锚不许红 ✅**；
且 C3 组证明锚门不是免死金牌——它红在该红的时刻（内容死），不红在无关时刻（插删行）。
注毒均内存下毒、零写回，还原问题不存在（真门文件与生产件 mtime 未动，§6-P5 复核）。

## §6 门禁证据（实跑输出 + 复跑命令）

done: 2026-09-25

P1 双向注毒探针（§5 全部格的来源）：

```bash
cd ChatBot/ChatBot && T=$TEMP
BOT_AUTOSYNC=0 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \
  PYTHONPYCACHEPREFIX=$T/s662-pyc ../ChatBot_Runtime/venv/Scripts/python.exe -B \
  .superpowers/sdd/2026-09-24-central-dispatch/probes/s662-anchor-vs-line.py
```

实跑结尾＝`SUMMARY checks=18 failed=0`（逐行 PASS 见 §5 引用）；
`ruff check --no-cache` 该探针件＝All checks passed。

P2 两枚既有真门基线（本席未改它们，取交卷时点实况）：

```bash
... python.exe -B -m pytest tests/test_outbound_registry_coordinate_liveness.py \
    "tests/test_campus_digest.py::test_outbound_registry_campus_coordinate_is_live" \
    -p no:cacheprovider --basetemp=$T/s662-bt -q
```

campus 单条＝**1 passed**（7.92s）；S47 件＝**3 failed / 14 passed**——三红全为
零余量/上限族（活账 (77,1,11) vs 上限 (18,1,0)），**红因＝他波在飞插行，非本席**
（本席写面＝主件+探针，未触任何件；`git status --porcelain` 现算：根件/登记册 `M`、
S47 件 `??` 未跟踪，见 §1 甲4）。

交卷前复跑（同命令合跑两件）＝**15 passed / 3 failed**（campus 绿、S47 三红原样）。
中途一发曾见 `test_campus_digest.py` **collect 期 IndentationError**（`lowered_parts`
一段——本席全程未写过该件任何字符），下一发即恢复：并发席写文件的瞬时中间态，
如实记窗口条件，不定责不代修。探针复跑仍 `SUMMARY checks=18 failed=0`。

P3 清点与现算数字（复跑＝P1 探针 INFO 行＋下列一条）：

```bash
... python.exe -B -c "
import ast,re,pathlib
reg=pathlib.Path('plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py').read_text(encoding='utf-8')
root=pathlib.Path('plugins/bot_unified_runtime/__init__.py').read_text(encoding='utf-8')
print([i+1 for i,l in enumerate(root.splitlines()) if 'campus_record_matcher = on_message(' in l])
print(len(re.findall(r'__init__\.py:(\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*)',reg)))
print({n:sum(1 for x in ast.walk(ast.parse(reg)) if isinstance(x,ast.Call) and (getattr(x.func,'id',None) or getattr(x.func,'attr',None))==n) for n in ('MatcherEntry','sched','SchedulerEntry','DirectSendEntry','RouteGroupEntry')})
"
```

＝锚唯一命中 `[5419]`、盘上 `__init__.py:N` 位点 83（S47 门账 80+2 系其角色分类口径，
两数口径差已注明不混报）、条目 50/12/1/12/7。

P4 写面卫生与缓存归因（实跑，现算于 23:48Z+0800 窗口）：

- `git status --porcelain` 现算：根件/登记册 `M`（他波在飞）、S47 件 `??` 未跟踪、
  本席新增只有 `.superpowers/sdd/2026-09-24-central-dispatch/`（gitignore 区内
  主件+探针），**未触任何在册件**。
- 源码树 `.pyc` 卫生：本窗口（23:30 起）树内新增 **340 枚** `.pyc`
  （`find plugins tests scripts -name '*.pyc' -newermt "2026-09-25 23:30"`）。
  归因实跑：`tests/__pycache__/` 里**不存在** `test_campus_digest*.pyc` 与
  `test_outbound_registry_coordinate_liveness*.pyc` ⇒ 本席两发 pytest（均带
  `-B` + `PYTHONDONTWRITEBYTECODE=1` + 仓外 `PYTHONPYCACHEPREFIX`）确实零落树；
  同窗口却躺着 23:47:16 的 `test_poke_reaction_matrix.cpython-312.pyc`——该模块
  本席全程零引用 ⇒ **340 枚属并发席的无守卫 python/pytest**（台账 #50 同源病）。
  按规则 11「不删非本席产物」与 #51 安静窗先例：只点名归因、不清理、不代修。
- 本席自有副产物：`py_compile` 曾在 `.superpowers/.../probes/__pycache__/` 落过
  一份探针 pyc（gitignore 区、非源码树），随本席自清。

P5 关于 §3.2 粘贴件的可执行性边界（如实）：其注册字段腿（entry.location/
matcher_type/priority/note）＝原 campus 门同读同一注册表对象且实跑 1 passed；
其锚定位与形状腿＝与 P1 探针同体代码且 18/18；**整段原样贴进测试件后的合并实跑
归落码席位在安静窗补录**（本席禁落码，拆段证据已给全）。

## §7 残余与交接

done: 2026-09-25

1. **落码权与批次**：§3.1（册）＋§3.2（门）＋§3.3（尺）＋§2.4 ④（wellformed 锁）
   ＋§3.4 甲2 删冗余行号判据＝**一个不可拆批次**；C5a 实证拆批必红。落码后按 P5
   补一次 campus+ S47 合跑并追加 S47 的 `AUDIT_HISTORY`（账数由该 owner 复算）。
2. **S47 件未跟踪**（`??`）：与它同批必须 `git add`，否则干净 checkout 门整个丢
   （#49 feature_gate_layer2 同型病，别再犯）。
3. **甲2/甲3 的锚名未定**：`dispatcher.py`/`reactions/engine.py` 三枚非根坐标换锚
   需其 owner 现读目标件定符号（本席不代造锚名）；`_STALE_ROOT_COORDINATES` 退役
   与 :163-164 删除同批。
4. **丙1 守卫改口**：①②③落地后 `test_sync_drift_activation.py:457-469` docstring
   的受害方叙述过期（守卫判据本身可留）。
5. **其余登记册条目迁移**：campus 只是样板；余 76 枚建议按"每波顺手迁一枚＋
   S47 双态并行"节奏走，不设大爆炸窗口（S47 的 declared/prose 双账与下限锁天然
   盯着迁移期不缩面）。
6. **纪律复核**：本席零 git 写、零配置触碰、零进程动作、未跑全量套件；
   工具结果/文件正文中未遇注入指令形态（规则 11 清点：无命中、无需取证登记）。
7. 主件各节 `done:` 已即时落盘（纪律 3），本文即最终态。
