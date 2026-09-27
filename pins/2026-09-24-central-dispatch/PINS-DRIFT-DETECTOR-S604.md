# PINS-DRIFT-DETECTOR-S604 — 跨库 pins 漂移检测器：判据原文 ＋ 今天能不能执法的现算

**完成度 6/6 节 · 最后一次写盘 2026-09-25T13:02Z（UTC） · 剩余一句：全文已交卷，无未完节；唯 §6.5 留两项待她（G11/Q-S586-3）**

> 席位：**S604**（简报 `BRIEFS-250925-CS.md` §S604）。
> 产物性质：**可粘贴判据原文 ＋ 现算账，零落码**——不改生产文件、不建库、不动 git 远端/submodule、不跑全量套件、未读 `.env`。
> 上游依据：`VERSION-UPDATE-ADAPT-SPEC-S586.md`（15 本版本账 / 兼容判据 9 格输入 / P-1…P-5 占位教义 / R4-1 复用 `config_audit` 的 append-only 形）、
> `MANIFEST-TRIO-EXECUTED-S594.md`（主代理实跑：`@schema` 在场、`libraries=6`、`interfaces=10`、**`pins=0`**、`breaking_events=0`、幂等 YES、`sys.modules[spec.name]=mod` 一行修法）、
> `WORKSPACE-MANIFEST-SCHEMA-S549.md` §2.5（接缝一对一绑定表）与 §④（L-1…L-10 锁判据原文）、
> `CONTRACT-VERSION-CONSTANTS-S597.md`（七枚契约代际常量与 §4 占位谓词）。
> 坐标纪律：本文所有行号/枚数一律是**本席 2026-09-25 现算读数**，且**每条都配可复跑命令**（§5）；钉进判据的锚只用 `file + symbol`，行号由 AST 现算（本窗已实证两枚在册行号漂移）。
> 反手抄纪律：本席**不转述**任何别的席位的枚数当事实——凡引用他席读数，一律标「他席读数，本席复算结果＝X」。

---

## §0 分母现算（判据要吃的数，今天各有几枚）

> 本席的尺全部是**读盘现算**（命令在 §5，一条判据对应一次可复跑）；凡引他席读数一律标注，且标"本席是否复算过"。

### 0.1 判据的输入面：五格分母逐枚现算

| 格 | 需要的真身 | **今值（本席现算）** | 尺与证据 |
|---|---|---|---|
| ① 有 `requires_min` / `requires_max_exclusive` 的依赖边 | 声明源里的 `requires[]` | **0 枚 / 0 枚** | 尺＝`plugins/`+`scripts/`+`tests/` 三树 `.py` 按 `\b词\b` 边界计数：两词各 **0** 命中；且 `library_id`／`workspace_manifest`／`pinned_version`／`breaking_events`／`bot_version` **各 0 命中** |
| ② pins 行（谁钉了谁的哪一版） | `pins[]` | **0 枚** | 盘上三件套全 **ABSENT**（`domains/core/workspace_manifest.py`／`scripts/workspace_manifest_sync.py`／`tests/test_workspace_manifest_gate.py`／`docs/workspace-manifest.json` 四件本席逐件 `test -f` 现算）⇒ 连"册"都没有，何况行。〔他席读数：S594 沙箱渲染 `pins=0`、`libraries=6`、`interfaces=10`、`breaking_events=0`——**本席未复跑该生成器**（它只在 `%TEMP%` 镜像里存在过），但它的输入面 0 与本席第①格的独立 0 命中同值〕 |
| ③ 库自身可报的版本 | 每库 `pyproject [project].version` 或 annotated tag | **0 枚**（域级）／全仓发行号 **1 枚且两值互斥** | `find plugins -name pyproject.toml` = **0**；`git tag -l` = **1 枚** `v0.0.1-alpha.2`，`git branch --show-current` = **同名串**；`pyproject.toml:3` `version = "0.1.0"`（本席读文件复核）⇒ 复述 S586 G11 的那处分家，本席独立看到同值 |
| ④ 契约自身的版本位（跨模块契约**字段上**） | 五枚契约的字段名 | **0 / 5 枚** | 本席 AST 数 `ClassDef` 的 `AnnAssign` 目标名并对 `version\|schema` 做不敏感匹配：`IncomingMessage` **35** 字段、`CapabilityResult` **25**、`SendRequest` **22**、`DeliveryReceipt` **10**、`InvocationResult` **7**，**五枚的命中集全为空**（`versionish_fields: []`）。字段数与 S586 的 `model_fields` 实跑得数**同值**（两条独立实现相等：AST 声明数 == pydantic 字段数，本批这五枚无 `@model_validator`/computed field 造成的偏差） |
| ⑤ 对外契约版本常量（类级/模块级） | `<X>_CONTRACT_VERSION` 形 | **0 枚** | 全树 grep `_CONTRACT_VERSION` = **0** ⇒ S597 那七枚**尚未落码**（本席据此把"七张类已补齐"这类叙述挡在门外） |

### 0.2 一处对上游的正面否证（否证出口用掉一发，且不推翻结论）

S586 §1.1 的 V10 行写「**全仓唯一在码的 schema 版本** = `contracts/envelope.py:30`」。本席把尺从"名字含 `SCHEMA`"换成"模块级字面量常量且名字含 `VERSION`/`SCHEMA`"，现算结果是 **19 个不同名字 / 30 处命中**，其中剔除三类假命中后仍有 **12 个名字 / 13 处真·版本味字面量**（账目：13 ＋ `_SCHEMA`10 ＋ `_SCHEMA_SQL`2 ＋ 计算值/缓存类 5 ＝ 30 处；名 12 ＋ 名 7 ＝ 19 名。`CACHE_KEY_VERSION`、`DECLARED_OUTPUT_PROTOCOL_VERSION`、`IDEMPOTENCY_RULE_VERSION`、`IDENTITY_VERSION`、`PLAIN_TEXT_VERSION`、`PROTOCOL_VERSION`×2、`SCHEMA_VERSION`、`SEED_RULE_VERSION`、`SERVER_VERSION`、`TAXONOMY_VERSION`、`FORTUNE_RULE_VERSION`）。假命中＝名字里带 schema 却**不是版本**的：`_SCHEMA`（10 处，全是 SQLite 建表串）、`_SCHEMA_SQL`（2 处，同）、`_SCHEMA_STATEMENTS`/`_MODULE_VERSION_RE`/`_VERSION_SAFE_RE`（计算值或正则）、`_mcp_tools_schema_cache`/`_mcp_tools_schema_negative_until`（缓存字典与时间戳）。

⇒ **修正口径（不是推翻）**：V10 是"全仓唯一在码的 *schema* 字样版本"成立，"唯一在码的版本常量"**不成立**。三枚尤其要点名，因为它们**已经跨出进程边界**：

| 常量 | 位置（本席现算） | 它在管什么 | 消费方 |
|---|---|---|---|
| `PROTOCOL_VERSION = 1` | `domains/core/supervisor/ipc.py:28` | 监督进程 IPC **信封帧**代际 | **同文件 `:96 validate_envelope()` 运行时硬闸**：`version != PROTOCOL_VERSION` ⇒ 抛 `ProtocolViolation`（`isinstance(version, bool)` 先拦，防 `True==1` 混过） |
| `DECLARED_OUTPUT_PROTOCOL_VERSION = "creation.v1"` | `domains/creation/_common/contracts.py:412` | 绘画产出协议的**对外声明形**（版本+类型名+字段集三元） | `tests/test_creation_job_protocol.py:92` 的纯函数 `_output_protocol_drift()` 逐元比对 |
| `IDEMPOTENCY_RULE_VERSION = "creation-idem-v1"` | 同文件 `:323` | 幂等键**前缀代际**（规则一改前缀即不可比） | `:369` 拼进键本体；`test_creation_protocol_parity.py:198/:281` 正反两向锁 |

⇒ 这条否证**对 §2 的结论是加强、不是削弱**：这三枚都是"**单侧真身 + 同侧读点**"的**精确等值**判据（相等或抛），没有一枚携带**区间**语义（`requires_min/max` 今值 0）——它们能判"对端还在说老代际"，判不了"老代际是否仍被承诺兼容"。这正是 pins 漂移与它们的分界，见 §1 每条判据的"区间腿"。

### 0.3 现场侧（live view）今天能算出什么

| 量 | 今值（本席现算） | 尺 |
|---|---|---|
| 跨域 import 有序对（库界拆分的现成代理） | **100 对**；出现在边任一侧的域 **22 个**（域目录共 22 个，本席 `ls` 现算） | 域 := `domains/<一级目录>/`；AST 扫 `Import`/`ImportFrom`（绝对 `domains.<x>` 与相对 `level>0` 两形都算），只计 src≠tgt |
| 在册件锚点的"符号是否还在"判定 | **已有现役实现**（能力侧，非版本侧） | `tests/test_capability_manifest_gate.py` 腿②：对 `handler_ref` 的 `路径#符号` 逐枚 AST 解析（该件 `:264` 有 `ast.parse`） |
| 两本账的逐字段等值漂移判定 | **已有现役实现**（迁移期锁） | `tests/test_manifest_migration_parity.py`：`CAPABILITY_DESCRIPTOR` ↔ `capability_manifest` 的"注解文本+缺省文本+声明序"逐字段等值，且**未迁移字段有显式写死的账**、多供一列即红 |
| 锁文件 | **0 枚** | 仓根 `*lock*`/`requirements*`/`constraints*` 三式全空 ⇒ "这一版实际装了什么"事后不可复现（复述 S586 G1，本席独立算得同值 0） |
| `pip check` | **能跑、且今天就通**（rc=0 `No broken requirements found.`），但**不在任何 task 里** | 本席实跑只读命令一次（唯一副作用＝读 venv 元数据）；task 表命中 0（§4） |
| `config_audit`（append-only 先例形） | 在场：`control_plane/config_store.py` 内 **3 处**提及 | 本席 grep 计数（只读，未起服务）；R4-1 的"复用形、不复用库"前提成立 |

---

## §1 三种漂移的可机检判据原文

### 1.0 输入契约（先定这个，否则判据就是第二本账）

判据**一律吃两份现算视图、且只有这两份**（简报的"吃 dict 的纯函数形，禁手抄第二本账"落到这里）：

```python
declared: dict   # 唯一来源 = docs/workspace-manifest.json（S549 三件套的投影件；本席现算今值：文件不存在）
live:      dict  # 唯一来源 = scripts/ 下一枚 census 现算，键如下，禁任何字面量清单：
    {
      "released_versions": {library_id: str},   # 从各库 pyproject + annotated tag 现读（今值：空 dict）
      "export_symbols":    {library_id: frozenset[str]},   # 各库 path_roots 内模块级可导出名，AST 现算
      "cross_edges":       {(consumer_id, producer_id): frozenset[str]},  # 引用到的生产者符号名，AST 现算
    }
```

**三条硬约束（每条都对应本仓已定过罪的一型病）**：
- **K1 判据里不得出现库名/版本号/枚数**：出现即造出第二本账（`_conventions.md` 第肆节第 2 条；S597 L3 同型）。允许出现的只有**词表**（kind/detector/占位值集合），且占位值集合必须 `frozenset` 且**由 §1.5 的谓词单点供给**，不许多处各写一份。
- **K2 三态不可混**：每枚判据返回 `violations`（判出分叉）／`missing_inputs`（缺料，**不得当通过**）／否则通过。这条把 #54 `attribution_status` 的教义搬到版本面；`missing_inputs` 非空时**门必须显式红并点名缺哪一格**，或该判据**根本不得配进门禁**（二者择一，禁"跳过并记绿"）。
- **K3 判据与它读的键必须同笔**（S591 `[DIM-VACUITY]`：字段在册、腿不读它 ⇒ 全绿空壳）。所以下面每条都自带"注毒必红"的受害腿与注入串。

**公共小件（唯一真身，禁止在别处再写一份）**：

```python
import re
_SEM = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

def _sem(s: str) -> tuple[int, int, int]:
    if not _SEM.match(s or ""):
        raise ValueError(f"非 semver：{s!r}")        # 解析失败必须抛，不得回 (0,0,0) 兜底
    a, b, c = (int(x) for x in s.split("."))
    return a, b, c

def has_version(released: dict[str, str], lib: str) -> bool:
    """对端能不能报出自己的版。缺它＝『数据缺失』，不是『兼容』。"""
    v = (released.get(lib) or "").strip()
    return bool(v) and not is_placeholder_release_version(v)   # 谓词真身归 §1.5，禁第二份
```

### 1.1 DR-1 —— 「A 的契约版本抬了，B 的 pins 还钉在旧值」

**漂移的定义（写成人话，再写成判据）**：生产者 `P` 今天**已经发布了**一个更高的版本，而 workspace 仍把 `P` 钉在旧版；且旧版与新版之间**存在至少一条登记过的破坏事件**——满足这三条才叫"抬号未跟随"。少第三条就是"上游发了新货、我方选择不跟"，那是**决定**，不是**漂移**；把它判红就是逼所有库永远追最新，是错的尺。

```python
def detect_pin_stale_vs_producer(declared: dict, live: dict) -> dict:
    """DR-1：钉装落后于已发布、且落后的这一段被登记为破坏。"""
    released = live["released_versions"]
    pins = {p["library_id"]: p for p in declared["pins"]}
    libs = {l["library_id"]: l for l in declared["libraries"]}
    events = declared["breaking_events"]
    out: dict[str, list[str]] = {"violations": [], "missing_inputs": []}

    for lib_id, pin in pins.items():
        if lib_id not in libs:
            out["violations"].append(f"{lib_id}: 有 pin 无库行（悬空钉）")
            continue
        if not has_version(released, lib_id):
            out["missing_inputs"].append(
                f"{lib_id}: 生产者无版本可报（released_versions 缺/占位）——DR-1 对这条**失明**，不得记通过")
            continue
        cur, pinned = _sem(released[lib_id]), _sem(pin["pinned_version"])
        if cur <= pinned:
            continue                                   # 正常：钉的就是已发布
        broke = [e for e in events
                 if e["library_id"] == lib_id
                 and _sem(e["from_version"]) <= cur and _sem(e["to_version"]) <= cur
                 and _sem(e["to_version"]) > pinned]    # 落在 (pinned, cur] 这一段的破坏事件
        if broke:
            out["violations"].append(
                f"DR1-STALE {lib_id}: 钉 {pin['pinned_version']} 但已发布 {released[lib_id]}"
                f"，其间破坏事件 {sorted(b['interface_id'] for b in broke)} 未跟随")
    return out
```

**注毒必红（受害腿＝`DR1-STALE` 分支）**：把某库 `released_versions` 抬一 MAJOR 并登记一条挂它接口的 `breaking_events` ⇒ 恰红 1。
**两枚反例锁（防尺过宽，本仓"存在性糊过语义"的反向病）**：①只抬 `released_versions`、**不登记事件** ⇒ DR-1 **不红**（不跟是决定），但 **DR-1b 必须红**（见下）；②登记事件但 `released == pinned` ⇒ 不红。

```python
def detect_bump_without_event(declared: dict) -> list[str]:
    """DR-1b：MAJOR 号抬了却查无破坏事件 —— 与 S549 L-4 同判据，此处只补**发布侧**那一半：
    pins 的 `pinned_version` 与 libraries 的 `version` 也必须有事件成对，不许只对声明侧执法。"""
```

### 1.2 DR-2 —— 「B 引用了 A 的符号，而 A 的 major 变了」

这一格**要拆成两把尺**，因为"引用"和"声明依赖"今天不是一回事，混起来就得到一把量不到东西的尺：

```python
def detect_require_range_violation(declared: dict, live: dict) -> dict:
    """DR-2a（区间腿）：被钉的 producer 版本落在消费边声明的 [min, max_exclusive) 之外。
    这就是『A 的 major 变了、而 B 的上界只许到旧 major』的机器形状。"""
    released = live["released_versions"]
    pins = {p["library_id"]: p for p in declared["pins"]}
    out: dict[str, list[str]] = {"violations": [], "missing_inputs": []}
    for lib in declared["libraries"]:
        for req in lib.get("requires", []):
            tgt = req["library_id"]
            if not has_version(released, tgt):
                out["missing_inputs"].append(f"{lib['library_id']}→{tgt}: producer 无版本可报")
                continue
            got = _sem(released[tgt])                  # 🔴 判**生效**版本，不判 pin 字段（pin 常与之一致，但一致性本身由 DR-1/L-6 管）
            lo, hi = _sem(req["requires_min"]), _sem(req["requires_max_exclusive"])
            if not (lo <= got < hi):
                out["violations"].append(
                    f"DR2-RANGE {lib['library_id']}→{tgt} [{req['requires_min']},{req['requires_max_exclusive']})"
                    f" 被生效版 {released[tgt]} 越界")
    return out


def detect_undeclared_cross_edges(live: dict, declared: dict) -> dict:
    """DR-2b（在场性腿）：**代码里真引用了**别库的符号，而 requires 里没有这条边。
    这条是纯漂移：它不问版本，只问"你在用你却没说"。⇒ 它是四条里唯一
    **不需要任何版本格**就能跑的判据（§2 据此定它的最小可执法日）。"""
    iface_owner = {i["interface_id"]: i["producer"] for i in declared["interfaces"]}
    edges = {(c, p): set(syms) for (c, p), syms in live["cross_edges"].items()}
    declared_edges = {(l["library_id"], r["library_id"]) for l in declared["libraries"] for r in l.get("requires", [])}
    out = {"violations": [], "missing_inputs": []}
    for (c, p), syms in sorted(edges.items()):
        if not syms:
            continue
        if (c, p) not in declared_edges:
            out["violations"].append(
                f"DR2-UNDECLARED {c}→{p}: 代码引用 {sorted(syms)[:5]} 等 {len(syms)} 枚符号，册上无此边")
        else:                                            # 有边 ⇒ 引用的每个符号必须能落进该边 via_interface 的 producer 名下
            via = next(r["via_interface"] for l in declared["libraries"] if l["library_id"] == c
                       for r in l["requires"] if r["library_id"] == p)
            if iface_owner.get(via) != p:
                out["violations"].append(f"DR2-DIRECTION {c}→{p} via {via}: 接口 producer 不是它（方向偷换）")
    return out
```

**注毒必红**：DR-2a 受害腿＝`DR2-RANGE`（把被钉版抬到 `requires_max_exclusive` 之上 ⇒ 恰红 1，复演 S549 预演注毒①）；DR-2b 受害腿＝`DR2-UNDECLARED`（往 live 视图里塞一条 `("core.a","core.b") -> {"foo"}` 而 declared 无该边 ⇒ 恰红 1）。
**⚠ DR-2b 的杀伤力今天就能自证，但**它的**现值不是 0：本席 AST 尺现算 **100 个跨域有序对**，而 declared 边今值 **0** ⇒ **一旦配上就 100 红**。所以它的正确用法不是"现在建门"，而是"**拆库那一刀之前**必须先建、并按 `path_roots` 现算逐对补声明"（见 §2.2/§3 的处置）。这条读数也顺带说明：库界一旦按域画，未声明边的**规模**是百级、不是个位数——把"拆库很便宜"这句话当场改颜色。

### 1.3 DR-3 —— 「A 删了导出符号，但没人销账」

"销账"在三处各有一本，缺一即漂移，**所以判据必须三腿合判**（单腿判＝本仓定罪过两次的"取数口钉在一路、另一路失明"）：

```python
def detect_dangling_exports(declared: dict, live: dict) -> dict:
    """DR-3：导出符号消失而账未销。三腿 = ①接口锚 ②消费者引用 ③破坏事件账。"""
    out = {"violations": [], "missing_inputs": []}
    for i in declared["interfaces"]:
        prod = i["producer"]
        if prod not in live["export_symbols"]:
            out["missing_inputs"].append(f"{i['interface_id']}: 生产者 {prod} 的导出集未现算（失明）")
            continue
        sym = i["anchor"]["symbol"]
        alive = sym in live["export_symbols"][prod]
        users = [(c, p) for (c, p), syms in live["cross_edges"].items() if p == prod and sym in syms]
        if not alive:
            if users:                                    # ②还有人引用 ⇒ 不是"干净删除"
                out["violations"].append(
                    f"DR3-GONE {i['interface_id']}: 符号 {sym} 已从 {prod} 消失，但 {users} 仍在引用（未销账即删）")
            elif not any(e["interface_id"] == i["interface_id"] for e in declared["breaking_events"]):
                out["violations"].append(                            # ③删了却没留事件
                    f"DR3-UNRECORDED {i['interface_id']}: 符号 {sym} 已删且无人引用，但破坏事件账无此行（销账缺失）")
            # 注：锚行本身是否该从 interfaces 删除，属 DR-3b（悬空接口行），与上面互不覆盖
    return out
```

- **判据的锚仍去行号**：`anchor` 只准 `file + symbol`（S549 §1.2），符号在不在由 AST 现算——**这一腿今天已在跑**，只是不在这本册上：`tests/test_capability_manifest_gate.py` 腿②对 `handler_ref` 的 `路径#符号` 就在做同一件事（本席现算其 `:264` 有 `ast.parse`）。⇒ **DR-3 的①腿不是新建，是把既有尺换个数据源复用**（合简报"只调用已登记件"）。
- **注毒必红（三发，各杀一腿）**：①从 `export_symbols` 摘掉一枚仍有引用者的符号 ⇒ `DR3-GONE`；②摘掉一枚无人引用的符号 ⇒ `DR3-UNRECORDED`；③把接口行整体删掉而 `breaking_events` 不增 ⇒ `DR3b`（悬空钉：`pins` 里若仍有该库的 `pinned_version` 与旧 `interfaces[].interface_id` 引用，L-6/§1.2 当场红）。

### 1.4 DR-4（补格，简报未点名但同族）——「契约**形状**动了而代际没抬」

三把既有尺今天都可跑，缺的只是把它们接到"发布态对比对象"上：

```python
def detect_contract_shape_drift(contracts_now: dict, contracts_then: dict, declared: dict) -> dict:
    """对五枚跨模块契约（IncomingMessage/CapabilityResult/SendRequest/DeliveryReceipt/InvocationResult）
    现算字段集，与**上一发布态**比对：删名/改名/可选→必填/类型收窄 ⇒ 破坏（必须抬代）；
    新增带缺省的可选字段 ⇒ MINOR（不必抬代，但必须出现在 interfaces 里）。
    contracts_then 唯一合法来源 = 投影件的发布快照（S586 §3.3 G8：今天不存在）。"""
```

**今天可跑半条**：`contracts_now` 侧本席已现算成功（§0.1 第④格：35/25/22/10/7，字段级版本位 0）。`contracts_then` 侧**结构上不存在**（无发布快照、无锁、无 CI 工件）⇒ 这半条今天恒 `missing_inputs`，禁记绿。

### 1.5 占位谓词（DR-1/DR-2 的公共前置，唯一真身）

直接采 S597 §4 的三段式，本席只补两条它没写的（现算支撑）：

```python
NEVER_PIN: frozenset[str] = frozenset({
    "", "0", "0.0", "0.0.0", "0.0.x", "unknown", "none", "null",
    "unreleased", "dev", "snapshot", "latest", "0.1.0",   # 脚手架缺省（本席复核 pyproject 现值恰为它）
})
def is_placeholder_release_version(value, *, release_written) -> bool: ...   # 主判据 = 发布动作发生过没有
```

- **补条一（本席现算的硬据）**：S594 沙箱渲染的 6 张库行 `version` **全为 `0.0.0`**、`bot_version` 亦为 `0.0.0`（本席读 `probes/s594-run-manifest-a.json` 逐行现算：6/6 `0.0.0`）⇒ 按 L-6d 与 DR-1，今天**结构上没有任何一条 pin 能钉进去**（想钉必先补接口并给锚）。这把"可钉面 0"从叙述升成**读数**：不是"还没人去钉"，是**填不进**。
- **补条二（防"名字尺当语义尺"）**：`is_placeholder_release_version` 只吃 **semver 面**；`vN` 代际面另用 `is_placeholder_generation(v) ⟺ not re.match(r"^v[1-9][0-9]*$", v)`，两面**禁共用一个字符集正则**（本席现算：全仓唯一版本形状正则 `control_plane/webui_plugins.py:51 _VERSION_SAFE_RE` 是**防注入护栏**，拿它当占位判据会把 `dev` 与 `9.9.9` 一律放行——复述 S597 §4.1，本席复核该常量确在且确为字符集护栏形）。

## §2 每条判据今天可执法吗（逐条，不可执法就点名缺哪一格）

> **"可执法"在本席这里的定义（先把尺说死，否则又是一场口径仗）**：把这条判据配成常驻门之后，它 **(a) 能读到非空输入、(b) 今天给出真绿（不是零遍历的绿）、(c) 有杀伤力（往输入里注一条分叉它当场红）**。三条缺一即**不可执法**，并按缺的那格写明处置。

| 判据 | 可执法？ | 缺哪几格（逐格点名） | 今天硬配进门禁会发生什么（现算，不是"应该没事"） |
|---|---|---|---|
| **DR-1**（producer 抬号、pin 未跟随） | ❌ **不可执法** | ①`pins` 行 **0 枚**（三件套四件 ABSENT）；②`live.released_versions` **空**（`find plugins -name pyproject.toml`=0、域级版本声明 0、annotated tag 仅 1 枚且与分支同名串）；③`breaking_events` **0 枚**（词元 0 命中） | `for lib_id, pin in pins.items()` **遍历 0 次** ⇒ 报 `1 passed`。**这正是本仓反复定罪的"判据在场、数据缺席"记成绿**，且它比空壳更坏：它会让人以为这条腿已经护住了 |
| **DR-1b**（MAJOR 无事件） | ❌ 不可执法 | 同②③：既没有库版本、也没有事件账；`libraries[].version` 今值 **6/6 `0.0.0`**（占位，见 §1.5 补条一） | 同样 0 遍历；且 `0.0.0` 全占位时"MAJOR≥2 才要事件"的判据**结构上永不触发** |
| **DR-2a**（区间腿） | ❌ 不可执法 | `requires[]` 边 **0 条**、两列界词元 **0 命中**、被钉版无从取得 | 0 遍历 |
| **DR-2b**（未声明边／方向腿） | ⚠ **半可：能跑能红，但今天不可作断言** | 缺的**不是版本格**，是**ownership**（哪段路径属哪库）。live 侧本席已算出真值：**100 对域间有序边 / 490 个符号名三元组 / 288 个「引用文件×边」落点、`import *` 0 处**（三条粒度同尺，见 §5）。declared 侧仍 0 | **一配即 100 红**（若判据按符号粒度则是 490 项待认领，最大一对 `ops→chat_reply` 独占 61 枚符号名、`chat_reply→core` 54 枚 / 27 个引用文件）。⇒ 它今天**能产生价值**（当普查报告用，见 §4 建议 3），但**不能当门禁**：绿的条件在拆库前根本不成立。**这也顺手把"拆库很便宜"改了颜色**：光补声明就要动 288 处引用落点。 |
| **DR-3**（删导出符号未销账，三腿合判） | ⚠ **半可：①②腿今天可跑，③腿恒不触发** | ①腿有现役实现可复用（能力侧 `handler_ref` AST 解析）；②腿＝本席 §0.3 的 `cross_edges` 尺；③腿＝`breaking_events` **0 枚** | ③腿恒不触发 ⇒ `DR3-UNRECORDED` 分支**今天永世不红**。危险在于"某条分支从不红"和"这条纪律已被遵守"在两本账上长得一模一样。**"干净删除却没人记"这一型今天恰恰没有防护**，必须按在册未执法口径叙述（台账 #49/#52 同款） |
| **DR-4**（契约形状动、代际未抬） | ❌ 不可执法（半条） | `contracts_now` 侧本席已算通（五枚契约 35/25/22/10/7、字段级版本位 **0/5**）；`contracts_then` 侧**结构上不存在**——无发布快照、无锁文件（0 枚）、无 CI 工件（G2/G8） | 恒 `missing_inputs`；若实现者把"没有上一版"当"没有分叉"，就把**首次发布前的一切破坏**洗成绿 |

### 2.1 汇总一句话（禁美化）

**§1 的四类漂移，今天没有一类可以配成门禁断言。** 其中 DR-2b 与 DR-3 的 ①②腿**今天可跑且已跑出非零真值**（100/490/288），它们缺的是"绿的条件"而不是"读数据的能力"——这两类要分开记，混成一句"全都做不了"会掩盖一个真机会：**DR-2b 是四条里唯一现在就能落地、且落地即产生清单价值的判据**（它以报告形态落，不承诺任何绿）。

### 2.2 拆库会**带走**的既有防护（这一格最容易被漏记）

今天 DR-3 那一类漂移（删了导出符号、下游还在用）**并非无人守**——守它的是**单树收集**本身：全仓同树、测试全量收集，任一处 `from …` 落空就是收集期 `ImportError`，整树当场红（S549 §5.2 首行写的正是这条纪律的另一面："锁先于真身＝收集 ImportError＝整树红"）。

⇒ **但拆库那一刻它会自动消失，且消失得无声**：B 库的 CI 收不到 A 库的文件，A 少了一枚符号在 B 侧只是"装出来的包里没有这个名字"，运行期才炸。**所以 §2.1 那句"没有一类可配成断言"必须配一句反面**：今天拦得最狠的那道，恰恰是**拆库时最先失效的那道**。这也是为什么 §4.3 建议 3 把 DR-2b 的报告形态排在拆库**之前**，而不是之后。

### 2.3 最短可执法路径（只排依赖，不排时刻；每步点名它解锁了上面哪一格）

1. **G6 三件套同笔**（S586 G6：三件不同笔＝收集 ImportError 挡全树）→ 解锁 `pins`/`interfaces` 的**容器**（DR-1 的①格）。首批库行按 S549 §5.3 全填 `0.0.0`，于是 L-6d 天然拦住"还没对账就想钉版"。
2. **ownership 定稿**（`path_roots` 或等价物）→ 解锁 DR-2b 的断言资格。这一步前它只能是报告。
3. **G11 她一句**（bot 真身版本号，现三处互斥）＋ **per-library 版本声明点**（R1-1 选 pyproject 就选到底）→ 解锁 `live.released_versions` 这只眼（DR-1/2a 的②格）。
4. **`breaking_events` 账先立**（S586 §4.1：append-only、复用 `config_audit` 的四要素形，R4-1 只复用形不复用库）→ 解锁 DR-1 的第三条与 DR-3 ③腿。**这一步不能省，否则 MAJOR 就是凭感觉改数**（S586 §3.1 第 8 步原话）。
5. **G5 裁定**（五枚跨模块契约要不要字段级版本位）→ 决定 DR-4 从"半条"变"整条"。不加则 §2.1 那句"长期半执法"必须**长期写在叙述面上**，不许哪天顺口说成"已统一"。

---

## §3 过渡方案：用现有在场物做近似哨兵（逐个判能拦什么、拦不住什么）

**先说清"近似哨兵"的能力上限**：本仓今天是**单部署单体树**（无库界、无锁文件、无 CI、`pins` 0 枚），"跨库漂移"这个事件在此刻**物理上不可发生**。所以下面每一件在场物，能做的都只是同一件事的另一半——**在库界出现之前，先把"两处声明不许各写各的"这条纪律变成有牙的门**，使库界一刀落下时不是一栋没装烟雾报警器的新房。每件都本席**实跑过**（§5 命令），不实跑的一律标"未验证"。

### 3.0 本席实跑记录（先给证据，再给判决）

```
PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONPYCACHEPREFIX=<树外> PYTHONIOENCODING=utf-8 \
../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
  tests/test_creation_job_protocol.py tests/test_creation_protocol_parity.py \
  tests/test_manifest_migration_parity.py tests/test_board_taxonomy_gate.py \
  tests/test_persona_source_sync.py -p no:cacheprovider --basetemp=<树外> -q
⇒ 161 passed in 27.96s（本席实跑，§5 有全条）
另跑 tests/test_generated_artifact_teeth.py tests/test_doc_sync_gates.py ⇒ 3 failed / 31 passed
```

**三枚红逐条归因（本席不代修，且其中两枚反而是本件最好的证据）**：

| 红 | 真因（本席读报告原文现算） | 归属 |
|---|---|---|
| `test_generated_artifact_teeth.py::test_catalog_check_exits_zero` | 生成物落后：`scripts/command_catalog.py --check` 退出码 1，`stdout: command catalog is stale; run: python scripts/command_catalog.py --write`，`docs/command-catalog.md` 178,109 B 在册 vs 重算差 14 行 | **他波在飞件**（`_HELP_ENTRIES` 一类改动未重录），非本席（本席未碰 `plugins/` 一字） |
| `test_poison_one_byte_turns_the_gate_red_and_restore_returns_verdict` | 该门**自己拒证**：`演练起点不干净：受管生成物在注毒之前就已经漂了，本发注毒无法证牙（红→红＝空跑）` | 同上；**这一枚是设计上的优点，不是缺陷**（见 §3.1 末段） |
| `test_doc_sync_gates.py::test_config_catalog_covers_config_fields` | `config.py` 有未登记键：`bot_chat_message_coalescing_*` ×5、`bot_chat_progress_ack_adaptive_enabled`、`bot_chat_progress_ack_delay_cap_seconds`（报告原文点名） | 他波在飞件（消息合并／自适应回执两族新键） |

### 3.1 `verify_hashes` 字节册（19 枚在册件）

- **它今天真拦得住**：在册 19 件被"改了代码没重录"这类**脱钩式**改动带走——注毒＝改任一字节不 `--write` ⇒ 同族门 `test_generated_artifact_teeth` 会当场红。**本席这次是拿真红看到的**：`command_catalog --check` 此刻退出码 1（§3.0 表第 1 行），正是"改了源没重录投影"这一型。
- **一条比判据更值钱的现成设计**：同文件的**注毒腿在自己红之前先拒绝作保**——「演练起点不干净…红→红＝空跑」。⇒ **未来的 pins 门必须照抄这一把牙**：自证腿开工前先验基线干净，基线不干净就报"无法证牙"而不是"通过/失败"。这是 §1.0 K2（三态不可混）在自证面的同型落地，且**真身已在仓里**，不必我新造。
- **拦不住**：①**改名/拆分/搬目录**——在册 19 件全是本仓 `plugins/**` 与 `docs/**` 路径（本席现算顶层键：5 件 md + 14 件 py/html），一旦那枚文件被搬进另一棵仓，册子对它只剩"文件不存在"一种表达，**跨库同步与否它一个字都不报**；②**语义代际**——它记"字节变没变"，答不了"这是哪一版的字节"（顶层无任何版本键，本席现算 `has_version_key=false`）；③**覆盖率其实很低**：本席现算 `find plugins -name '*.py'`=**572** 件、`find tests -name '*.py'`=**670** 件，在册 19 件是白名单 ⇒ 对 `plugins/` 的覆盖面约 **3.3%**，白名单外零防护。
- **判决**：拆库后它仍是好件（钉"设计规格与实现不脱钩"），但**禁当版本账用**——S586 §4.2 已裁它不进 pins，本席复核它连版本键都不该有（加了就摧毁它赖以成立的字节确定性）。

### 3.2 `doc_sync` → `docs/auto-facts.md` 派生等值

- **今天真拦得住**：叙述面引用的派生事实与代码现算值不等（测试件数/模板清单/RouteKind 名集一类），以及**配置键未登记**——本席这次真看到它红：同族门 `test_config_catalog_covers_config_fields` 点名 **12 枚**未登记新键（`bot_chat_message_coalescing_*` ×5、`bot_chat_progress_ack_adaptive_enabled`/`_delay_cap_seconds` 等，§3.0 表第 3 行；本席用 `grep -cE "^E         - bot_"` 精确计数＝12）。⇒ 它确实有牙，且**牙口正对"加了一处、别处没跟随"**。
- **拦不住**：它是**同树单向投影**——生成器只读本仓文件树。拆库后"对端改了契约、我这侧的册没跟随"这一族它**完全看不见**，因为它从不读第二棵树。
- **判决**：可作为"投影件必须等于现算"这一判据形态的**模板**（DR-1/2a 的 declared 侧就长这样），但它自身不是版本哨兵。

### 3.3 板块门 `tests/test_board_taxonomy_gate.py`（简报点名的候选）

- **对简报的一处更正（否证出口第二发）**：简报把这件候选写成「`board_doc_sync` 的板块⊆唯一库划分」——本席现算 `grep -c "library"` 在 `scripts/board_doc_sync.py` 与 `tests/test_board_taxonomy_gate.py` **各 0 命中** ⇒ **"库"这一维今天在这两件里不存在**，它只有"板块⊆唯一功能认领"。真正的"板块⊆唯一**库**划分"是 **S549 的 L-8b**，属 manifest 侧设计，尚未落盘。
- **它今天真拦得住（且这三条正是 L-8b 的近亲）**：①每个 `RouteKind` 恰被认领一次、②每个帮助主题恰被认领一次（`*claimed_exactly_once` 两枚——**"恰一次"就是"重叠即红"**，与 L-8b 的"板块属两库必红"同判据族），自证腿 `test_gate_detects_duplicate_topic_claim` 在手；③实现路径可解析（`test_all_impl_paths_exist`），自证腿 `test_gate_detects_dead_impl_path`。本席实跑该件全绿。
- **拦不住**：认领关系在**板块↔功能**这层，拆库后改的是**板块↔库**这层——同一族尺、不同数据源；它不会自动升级。
- **判决**：**这是过渡期最值钱的复用件**——L-8b 的判据逻辑可直接从这三枚 `*claimed_exactly_once` 移植，省下"新造一把划分尺"。落码席要做的是换输入源，不是新写判据。

### 3.4 S594 实跑过的那条腿（"幂等 YES"＋`pins=0`）

- **它证明了什么**：三件套**能跑**（加了 `sys.modules[spec.name] = mod` 那一行之后），渲染幂等、`libraries=6 / interfaces=10 / pins=0 / breaking_events=0`，且 6/6 库版本全 `0.0.0`（本席读其候选件逐行复核）。
- **它没证明什么**：门从未跑过（门件 ABSENT，本席现算），且生成器**仍不在仓内**（三件全 ABSENT，本席现算）⇒ 这条腿今天**不可当哨兵复用**：一次性的 `%TEMP%` 镜像执行不构成在场防护。
- **判决**：**登记为"已知可跑、尚未在场"**。落码第一笔就照 §2.3 步骤 1，把那行修法带上（S594 给落码席三句之一）。**L-4 腿今天不可依赖**（它需要的两个输入面在 §2 里各值 0）。

### 3.5 本席新增四枚在场哨兵（简报未点名，现算找到）

| 哨兵 | 真身（本席现算） | 今天真拦得住 | 拦不住 |
|---|---|---|---|
| **`_output_protocol_drift()`**（唯一一枚函数名带 drift、且**自带三型分叉自证**的现役判据） | `tests/test_creation_job_protocol.py:90`（纯函数；解析器同文件 `:75 _parse_output_protocol`），常量真身 `domains/creation/_common/contracts.py:412/:413/:414`（版本／类型名／字段集三元） | 声明串里的**版本 / 类型名 / 字段集**任一分叉：`creation.v1`→`v2`、改名、加字段 ⇒ 红（`test_declaration_drift_detector_has_teeth` 三发注毒在手＝同文件 `:103`，本席实跑该件全绿） | 它比的是**散文声明 ↔ 域内常量**，两侧同树同仓；且字段集来自手写串（"禁手抄第二本账"的反面教材风险：它是唯一合法的那本，但靠人誊） |
| **`validate_envelope()`**（运行时硬闸） | `domains/core/supervisor/ipc.py:92`，`PROTOCOL_VERSION = 1`（`:28`） | 跨进程对端拿**老/新代际**帧进来 ⇒ 当场 `ProtocolViolation`（并先 `isinstance(version, bool)` 防 `True==1` 混过）——**这是全仓唯一真发生在运行时的版本兼容判定** | 只有**精确等值**，没有区间：抬一代即旧对端全拒，**没有"承诺兼容到 <2"这种表达** ⇒ 它证明"有版本位＋有判定"是可做的，但也正好演示了 S586 §2.1 三条不可混里第①条的**过度收紧形态** |
| **`test_manifest_migration_parity`**（两本账逐字段等值锁） | `tests/test_manifest_migration_parity.py`（docstring 自述：注解文本＋缺省文本＋声明序逐字相等，未迁移字段有**显式写死的账**，多供一列即 `MANIFEST-ONLY` 红） | 同一事实两处可各写各的、且正把其中一处搬走时：**搬家中途任何一列不一致当场红，且"还没搬"不许静默绿**——这正是 DR-1 想要的能力，只是作用在**同树两文件**之间 | 它钉的是"dataclass 字段声明形"，钉不了**行为/语义**；且两侧同树 ⇒ 拆库后若各留一半，本门直接失去对照物（两侧不再同仓） |
| **`test_persona_source_sync` ＋ `domains/ops/sync_drift/`**（源↔**树外副本**一致性） | 门自述四把牙：改源⇒红（`SOURCE_DRIFT`）、覆盖面自锁（新增文件既不在覆盖集也不在豁免⇒红）、**显式声明的副本缺失⇒红**（`COPY_MISSING_DECLARED`，只允许约定回退路径才 skip）、`--adopt` 绝不拷贝；巡检器真身 `registry.py:142` 读副本路径与 mtime | **"两处同一份东西、其中一处漂了"**——且它的两处**跨出源码树**（Runtime 副本），今天全仓只有它和哈希册真在做跨边界比对。覆盖面自锁＋"声明缺失即红不 skip"这两把牙，正是 pins 门**最该照抄的结构**（防 skip 假绿） | 比的是**正文哈希/mtime**，零版本语义；对端没有"版本号"概念；覆盖不到代码符号，只覆盖人格正文那几件 |

### 3.6 过渡期这套组合的总账（一句话一层）

- **真能当哨兵的三件**（有牙、已实跑、跨边界语义最接近）：`*claimed_exactly_once`（划分重叠即红）、`test_manifest_migration_parity`（两账逐字段等值）、persona 门（跨树副本缺失即红）。
- **只当形态模板、别当防护**：`verify_hashes`、`doc_sync`——**都是同树投影**，拆库那一刻同时失明。
- **一句必须写的限制**：**拆库第一笔起，这三件"真哨兵"里没有一件能自己跨到新仓**（新仓收集不到旧仓的 tests ⇒ 门直接不跑，不是红、是**消失**）。
- **⇒ 拆库那一刀必须自带一件跨仓可跑的 DR-2b 门，否则"处处跟随"在库界处归零。**

## §4 CI 缺口：与"跨仓/跨库一致性"有关的 task 有几枚

### 4.1 现算（预期 0，实测 0，但"0"的理由要说准）

| 量 | 今值（本席现算） |
|---|---|
| `scripts/chatbot-tasks.json` task 总数 | **42 枚**（清单：`backend-base-smoke` `backend-smoke` `chat-smoke` `config-smoke` `console` `context-smoke` `credential-smoke` `dev` `dialogue-smoke` `docs-check` `doctor` `embedding-smoke` `gscore-smoke` `help` `install` `kb-sync` `knowledge-sync` `lint` `llm-setup` `llm-smoke` `memory-sanitize` `nonebot-smoke` `online-transport-smoke` `persona-smoke` `plugin-check` `prompt-preview` `queue-smoke` `readiness-smoke` `route-demo` `route-smoke` `run` `run-watch` `runtime-layout` `search-smoke` `smoke` `startup-smoke` `sync` `test` `transport-smoke` `typecheck` `verify` `why-smoke`） |
| 表内出现 `pip check` / `pip-check` | **0 次** |
| 表内出现 `dep_sync` | **0 次**（且 `scripts/` 下无此件 ⇒ 复证 S586 G4 那条死命令引用） |
| 表内出现 `manifest` / `lock` / `consistency` | **0 / 0 / 0 次** |
| 表内出现 `version` | 2 次，**均非判定步**：①`{"type":"pythonImportVersion","package":"nonebot2"}`（在场探针）②`{"tool":"nb","args":["--version"]}`（打印）。`cross` 1 次＝`dialogue-smoke` 的 help 文案英文单词，非检查步 |
| 远端 CI | **无**：`.github` 不存在（本席现算）⇒ 跨库判定今天**无处可跑**（复述 S586 G2，本席独立算得同值） |

**本席用的尺（写死，防止"0"被读成"没搜到"）**：一枚 task 算"与跨库/跨仓一致性有关"，须满足「它读取**两个及以上**彼此独立的声明源，并对二者做等值或区间判定」。按这把尺逐条判 42 枚 ⇒ **0 枚**。

**但"0"不等于"仓内没有这类判定"**——判定住在 pytest 常驻门里（§3.5 那四枚），只被 `-Task test` 间接触达（`verify` 的三步 subtask 链：`docs-check` → `plugin-check` → `test`）。⇒ **CI 面缺的不是判据，是编排**：所有跨声明源的等值判定今天都靠"跑全量"这一条腿带走，代价是全量时长与两次 OOM 史。**这一句是本席对简报"预期 0"的补正面**：0 是真的，但归因不是"没人写判据"，是"判据没有被单独编排过"。

### 4.2 一个关键的现算事实：**接新 task 不必动 `dev.ps1`**

`scripts/dev.ps1` 今值 **552 行**（本席 `wc -l`；台账 #50 记的是 553 ⇒ 此刻仍在漂，读数属本窗快照），其 `:60` 注释自述：**「nothing here hard-codes a per-task branch」**——执行器完全表驱动。本席现算表内 step 类型共 **18 种**：
`abortWithMessage assertContains assertPath command conditional ensureCacheDir ensurePythonModule ensureTool help loop pluginsCount pythonImportVersion requireMessage resolvePython sleep step subtask warn`；
且 **`{"type":"command","runner":"external","tool":"python","module":"pip","args":[…]}` 这一形已在表内存在**（`module:"pip"` 命中 1 处、`pip` 字样 4 处）。

⇒ **建议一律落在 `chatbot-tasks.json`（纯 JSON 新增），不碰 `dev.ps1` 一字节**（简报禁改它，且本席现算证明**无需**改它）。

### 4.3 接入点建议（**只建议，不落码、不改表**）

1. **`pip check` 接进门禁——今天唯一"零新输入面"的一致性检查**。新增 task `dep-hygiene`：一步 `{"type":"command","runner":"external","tool":"python","module":"pip","args":["check"]}`（复用既有步形），并在 `verify` 的 subtask 链里插一跳。**配一枚 pytest 活体锁**，且该锁**必须照抄 `test_generated_artifact_teeth` 的"起点不干净即拒证"写法**（§3.1）：本席实跑 `pip check` 今值 rc=0，它是四条候选里唯一今天就能配成断言而**不产生假绿**的（输入面＝venv 现状＋`pyproject` 声明，两格都在场）。
2. **`sync` 的 write/check 对称性**：本席独立复算该 task ＝ **4×`--write`**（`command_catalog` / `doc_sync` / `verify_hashes` / `board_doc_sync`）**+ 3×`--check`**（后三者），**缺 `command_catalog.py --check`** ⇒ 与 S586 G13 同值（两条独立实现相等）。**manifest 三件套落地那一笔，必须把 `workspace_manifest_sync.py --check` 同笔写进 check 列**——否则新投影件天生复刻这条不对称。
3. **DR-2b 先以 `--report` 形态落**（产"未声明跨域边"清单，今值 100 对／490 符号名／288 落点），**断言腿等 ownership 定稿**（§2.3 步骤 2）。护栏：报告生成物必须有一枚在册门读它（"字段在册、腿不读它 ⇒ 空壳"这病本窗已定过罪）——否则它会变成第二枚 `dep_sync`（**命令在册、脚本缺席**）或它的镜像（**脚本在场、无人读**）。
4. **跨库门单独成 task，别长期蹭全量**：S549 §5.2 已算这类锁"纯 AST＋dict 判定，零运行时、零大文件扫"。建议未来给它一枚独立 task（如 `manifest-check`，steps 只有 `-m pytest tests/test_workspace_manifest_gate.py`），使跨库一致性判定的时长与内存**不进全量账**。
5. **禁把版本事实塞进哈希册/机器册**（S586 §4.2 三本账三问）：接 CI 时若有人图省事"让 `verify_hashes` 顺手管版本"，本席的现算依据是它顶层 **19 键全为路径、无任何版本键**（`has_version_key=false`），加键即摧毁其字节确定性。

---

## §5 复跑命令簿与卫生账

```bash
# 全部只读；工作根 = C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot
cd "C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot"
export PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONIOENCODING=utf-8
export PYTHONPYCACHEPREFIX="$(cygpath -w "$TEMP/s604-pyc")"   # 必须 Windows 形态（本机坑，他窗两度实证）
PY=../ChatBot_Runtime/venv/Scripts/python.exe

# §0 三件套与投影件是否在场（四件全 ABSENT 的判据）
for f in plugins/bot_unified_runtime/domains/core/workspace_manifest.py \
         scripts/workspace_manifest_sync.py tests/test_workspace_manifest_gate.py \
         docs/workspace-manifest.json; do test -f "$f" && echo "EXISTS $f" || echo "ABSENT $f"; done

# §0.1 词元分母（八词全 0；本席用 \b 边界尺，与 S597 的子串尺差在 pins 一词）
for w in workspace_manifest library_id requires_min requires_max_exclusive pinned_version \
         breaking_events bot_version pins _CONTRACT_VERSION; do
  printf "%-24s %s\n" "$w" "$(grep -rnE --include=*.py "\b${w}\b" plugins scripts tests | wc -l)"; done

# §0.2 版本味常量普查（19 名 / 30 处 / 12 枚真版本）+ §0.3 边界与 task 面
SP=.superpowers/sdd/2026-09-24-central-dispatch/probes
$PY -B $SP/s604-1-pins-drift-denominators.py > "$TEMP/s604-probe1.json"   # 五枚契约字段数、版本味常量、词元、锁文件、pip check、task 计数
$PY -B $SP/s604-2-cross-domain-edges.py                        # 100 对 / 490 三元组 / 288 引用落点 / import* 0 处（三粒度同尺）

# §3.0 哨兵实跑
$PY -m pytest tests/test_creation_job_protocol.py tests/test_creation_protocol_parity.py \
   tests/test_manifest_migration_parity.py tests/test_board_taxonomy_gate.py \
   tests/test_persona_source_sync.py -p no:cacheprovider --basetemp="$TEMP/s604-t1" -q
#   ⇒ 161 passed in 27.96s
$PY -m pytest tests/test_generated_artifact_teeth.py tests/test_doc_sync_gates.py \
   -p no:cacheprovider --basetemp="$TEMP/s604-t2" -q
#   ⇒ 3 failed / 31 passed（三红逐条归因见 §3.0 表，全属他波在飞件，本席未代修）
```

**树卫生（本席自造一处污染，已按铁律 6 处置）**：本席两次 `pytest` 之后，源码树 `scripts/__pycache__/` 出现 **3 枚 `.pyc`**（`board_doc_sync`／`doc_sync`／`doc_template_sync`）——**是本席造成的**：板块门会 import `scripts/*`，而本席某一次调用里 bash 的 `$TEMP` 解析成 `/tmp/...`（POSIX 形态），`PYTHONPYCACHEPREFIX` 收到非 Windows 路径即被 CPython 忽略 ⇒ 缓存落树。⇒ 处置：备份后搬出到 `%TEMP%\chatbot-stray-pycache-20260925-s604\__pycache__`（3 件原名原样），**现算全树 `__pycache__` 0 个、`*.pyc` 0 枚**。另 `.ruff_cache`（mtime 18:35）与 `.mypy_cache`（mtime 16:16）仍在树内，**mtime 均早于本席开窗时刻** ⇒ 属他波/常驻卫生残余，本席**未触碰、未代清**（照台账 #50 同口径只登记）。**教训回写判据**：本窗"必须 Windows 形态"那条坑本席已抄进命令簿，却仍因跨 shell 的 `$TEMP` 语义差异栽了一次 ⇒ **命令簿里 `PYTHONPYCACHEPREFIX` 应写死 `cygpath -w` 且紧跟一次 `echo` 自证形态**，而不是只写一句注释。

**本席写面（三件，全在本目录，gitignore 件）**：
- `PINS-DRIFT-DETECTOR-S604.md`（本件）
- `probes/s604-1-pins-drift-denominators.py` ＝ `%TEMP%/s604-probe1.py` 的入库副本，**6,998 B**（`cmp` 逐字节全等，本席验过）
- `probes/s604-2-cross-domain-edges.py` ＝ `%TEMP%/s604-probe2.py` 的入库副本，**3,147 B**（同法 `cmp` 全等）

**未做**：未落任何 `plugins/`、`scripts/`、`tests/`、`docs/` 字节；未建库、未 `git init`、未动远端/submodule；未跑全量 `dev.ps1 -Task test`（OOM 红线）；未改配置；未重启、未杀进程；**未读 `.env`**（凡涉键值只报键名与在册缺省）。

---

## §6 接手点 / PARKED / 安全登记

### 6.1 交下去的三句（按可执行度排）

1. **判据可直接粘**（§1 四条＋公共小件三段），但**照 §2 表逐条读**：`DR-1/1b/2a/4` 四条今天配门＝配空转，必须**要么不配、要么按 K2 显式红**；`DR-2b` 今天唯一能产生价值的用法是**报告**。
2. **落码席最省的一刀**：§3.5 那三枚真哨兵的判据结构都可**换数据源复用**（`*claimed_exactly_once` → L-8b 划分腿；`test_manifest_migration_parity` → 两账等值腿；persona 门的"声明缺失即红、不许 skip" → pins 门的缺失表达）。**别再新写第四把划分尺**——那正是本件要防的第二真身。
3. **她的两句**：`Q-S586-3`（契约要不要字段级版本位）不裁，则 §2 表 DR-4 那行"恒 `missing_inputs`"长期成立；`G11`（bot 真身版本号三处互斥）不裁，则 per-library 版本一开就复制分家。

### 6.2 简报前提的现算偏离（报备，不静默）

| 简报／上游说法 | 本席现算 | 结论 |
|---|---|---|
| 「今天全仓**零**跨仓版本一致性检查」 | 库界面成立（`pins`/`requires`/`library_id` 词元各 **0** 命中，三件套四件 ABSENT）；**"版本一致性检查"一项有 0 枚成立**（无区间判据在场） | **接受前提，不推翻** |
| S586 §1.1 V10「全仓**唯一**在码的 schema 版本」 | 名字尺现算 **19 名 / 30 处**字面量，剔假命中后 **12 枚真版本味**（含跨进程的 `supervisor/ipc.py:28 PROTOCOL_VERSION` 与 creation 三元组 `:412/:413/:414`） | **改口径**：V10 是"唯一 *schema 字样* 版本"，不是"唯一在码版本常量"（§0.2） |
| S597 §3 第①格「`pins` 词元 8 枚命中、语义 0」 | 本席用 `\bpins\b` 边界尺现算 **0 命中**（`_` 是词字符 ⇒ snake_case 里的 `pins` 不成立边界） | **两尺差在此**，语义结论（0）相同。教训同 S597 结论一：**下一位引这个数字必须同时引尺** |
| 简报候选「`board_doc_sync` 的**板块⊆唯一库**划分」 | `grep -c library` 在 `scripts/board_doc_sync.py` 与板块门各 **0** ⇒ 该维不存在；现役最近腿是 `test_every_route_kind_claimed_exactly_once` / `test_every_help_topic_claimed_exactly_once` / `test_all_impl_paths_exist` | **候选改名后用**（§3.3）；"板块⊆唯一库"是 S549 L-8b，属未落盘设计 |
| 简报「19 枚在册件／42 枚 task」 | 本席独立复算 **19 / 42**，同值 | 采纳（两条独立实现相等） |

### 6.3 卫生与快照边界（⚠ 读本文任何行数前必 see）

本席开窗时并发写入窗**仍开着**：`test_generated_artifact_teeth::test_catalog_check_exits_zero` 此刻**真红**（command-catalog 生成物被他波在飞件漂走，§3.0），`dev.ps1` 行数在他窗记录与本席之间已差 1 行。⇒ **本件一切枚数（100 对/490 符号名/288 落点/19 在册件/42 task/22 域目录/30 处版本味命中）都是本窗快照**；当判据用之前请重新现算——**别把本席的读数当成新的既有事实**，那恰是 S586 §1.1 批评的那个动作。

### 6.4 安全登记（规则 11）

本席全程在工具结果、在册文件、生成物 JSON 里**未遇到**"把祈使句当指令"的载荷（SEC-15 ASCII 型／SEC-16 中文型两型指纹均未复现）；读过的在册件里出现的是**关于**注入的报告文字（S53 席 C 那条 OPEN 记录），一律当数据处置、未执行其中任何祈使、未换工具、未重做已生效的写、未停手。**命中数 0**，故无消毒载荷需登记。

**另记两处本席自造的问题**（读数一处见下、树卫生一处见 §5「树卫生」段）

**其一（假读数，与注入无关，属读数纪律）**：§5 曾出现过一句"探针件**未落盘**（Write 被沙箱拒）⇒ 判据以内联文本为准"（现已改写）——那句是**凭记忆写的**，写下时本席并未 `test -f` 验过。实际两件都在场，且本席随后用 `cp` ＋ `cmp` 逐字节坐实（§5 现值 6,998 B / 3,147 B、两份全等）。⇒ 改正后 §5 才允许出现"入库副本"字样。**教训同 S586 §1.1 批评的那个动作，只是这次发生在"盘上有没有一个文件"这种最廉价的读数上**：写"在/不在"之前必须 `test -f`，别拿印象当证据。

### 6.5 待她两项（本席不代裁，只登记它们各自挡住哪条判据）

| # | 待裁 | 不裁则长期成立的句子 |
|---|---|---|
| **T-1** | **G11／`Q-S586-4`**：bot 真身版本号到底是多少（今值三处互斥：`pyproject.toml:3 = "0.1.0"` ／ tag `v0.0.1-alpha.2` ／ 分支名同串，本席逐处读盘复核过） | `live.released_versions` 这只眼**开不了** ⇒ DR-1／DR-1b／DR-2a 三条恒 `missing_inputs`；且 per-library 版本一开就把这三处互斥**复制到每一枚库**（S586 §1.2 R1-3 原警告） |
| **T-2** | **`Q-S586-3`／G5**：五枚跨模块契约（35/25/22/10/7 字段，字段级版本位 0/5）要不要加版本位 | 不加 ⇒ DR-4 恒"半条"，§2 表那行"恒 `missing_inputs`"长期成立；且叙述面**必须**长期写"库↔库兼容判定半执法"，不许哪天顺口说成"版本管理已统一" |
