"""S1 无界资源收口（P5.8）机械门：指定面的模块级「只 append 从不淘汰」容器即红。

背景（席 S1 简报 §8 / 台账 #71★）
--------------------------------
本波收口四处无界资源——① http client 连接池 ② 知识文本缓存 ③ 只涨不清的内存
计数账 ④ `request_id` 贯穿不足。前两类落在我（S1）的独占面上：
- `domains/chat_reply/llm_engine/providers.py::_HTTP_CLIENTS`
  （进程级 httpx.Client 连接桶，按代理值分桶；键空间由 config 约束但仍需有界淘汰，
  代理值热改换代次会堆积已关闭的旧 Client）
- `domains/chat_reply/character/vector_knowledge.py::_QUERY_EMBED_MEMO`
  （单文本查询嵌入 memo，键 = (signature, **任意用户 query**)＝无界键空间）

这两枚旧腿都是「只 set 不淘汰」的形态：前者从不 pop，后者溢出走 `.clear()`
一把全清（thundering herd）。本波把它们改成带 LRU 逐条淘汰的有界容器。

本门的职责（一句话）
--------------------
对上述**指定面**里的每一枚模块级可变容器：若它被运行时**增长**（下标赋值 /
`.append`/`.setdefault`/`.add`/`.update`/`+=`）却在全模块**找不到任何淘汰动作**
（`.pop`/`.popitem`/`.clear`/`.discard`/`.remove`/`del x[k]`），即判**无界 ⇒ 红**。
下一位再往这两枚文件塞「只涨不清」的模块级 dict/list/set，当场红，不用等人肉审计。

设计取舍（写清楚门的网眼，别让下一个人误判）
--------------------------------------------
- 只扫**模块顶层赋值**的容器：函数体内的局部 dict 生命周期随栈回收，不属本门。
- 只认**同模块内可见的淘汰**：淘汰可能发生在别处，但那样可读性更差；本仓把
  「有界」和「淘汰」写在一起是既有纪律（见 `_QUERY_EMBED_MEMO`）。跨模块淘汰
  的需求若真出现，改本文件的 ALLOW_RECLAIM 显式登记，不得静默放宽判据。
- 常量字典（如 `_LLM_ERROR_PUBLIC_MESSAGES`）只在模块顶层以字面量赋值、运行时
  不增长 → 不在增长集 → 不误伤。
- 空集合不得恒真：若指定面解析出 0 枚受管容器（文件被改名/搬走），下限断言
  直接红，逼着同步更新本门清单。

自证三件套（本仓常驻做法）
--------------------------
正向：真身两面全绿（test_designated_faces_clean）；
注毒：合成一段「只 set 不淘汰」源码必须被标记（test_poison_unbounded_flagged）；
反向不误伤：同一段源码补一枚 `.popitem` 必须转绿（test_eviction_recognized）；
下限：指定面若一枚受管容器都解析不到，直接红（test_roster_not_empty）。
本文件**不改动任何生产源码**，注毒全在内存字符串里跑。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 指定面：S1 独占的两枚收口文件。要扩面＝先把那枚文件修到有界淘汰，再登记到这里。
_DESIGNATED_FACES: tuple[str, ...] = (
    "plugins/bot_unified_runtime/domains/chat_reply/llm_engine/providers.py",
    "plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py",
)

# 增长形态：属性方法名（对容器调用即视为可能无界增长）。
_GROW_METHODS = frozenset({"append", "setdefault", "add", "update", "insert", "extend"})
# 淘汰形态：任一出现即视为该容器有回收点。
_RECLAIM_METHODS = frozenset({"pop", "popitem", "clear", "discard", "remove"})


def _is_bounded_container_value(node: ast.AST) -> bool:
    """模块顶层赋值右侧是否为可变容器（dict/list/set 及其工厂调用）。"""
    if isinstance(node, ast.Dict):
        return True
    if isinstance(node, ast.List):
        return True
    if isinstance(node, ast.Set):
        return True
    if isinstance(node, ast.Call):
        factory = node.func
        if isinstance(factory, ast.Attribute):
            factory = factory.value
        # OrderedDict() / defaultdict(...) / collections.Counter()
        name = getattr(factory, "id", None) or getattr(factory, "attr", None)
        return name in {"dict", "list", "set", "OrderedDict", "defaultdict", "Counter"}
    return False


def _module_level_containers(tree: ast.Module) -> set[str]:
    """收集模块顶层被赋值为容器的名字（含 AnnAssign）。"""
    found: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if _is_bounded_container_value(value):
            for target in targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
    return found


def _scan_source(source: str) -> tuple[set[str], set[str], set[str]]:
    """返回 (模块级容器名, 运行时增长名集合, 有淘汰动作名集合)。"""
    tree = ast.parse(source)
    containers = _module_level_containers(tree)
    grown: set[str] = set()
    reclaimed: set[str] = set()

    for node in ast.walk(tree):
        # 下标赋值：x[k] = v / x[k][...] = v（取最外层 Name 作为被增长对象）
        if isinstance(node, ast.Assign):
            for target in node.targets:
                base = _subscript_base_name(target)
                if base is not None:
                    grown.add(base)
        elif isinstance(node, ast.AugAssign):
            base = _subscript_base_name(node.target)
            if base is not None:
                grown.add(base)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                base = _subscript_base_name(target)
                if base is not None:
                    reclaimed.add(base)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = _plain_receiver_name(node.func.value)
            if recv is None:
                continue
            method = node.func.attr
            if method in _GROW_METHODS:
                grown.add(recv)
            if method in _RECLAIM_METHODS:
                reclaimed.add(recv)

    return containers, grown, reclaimed


def _plain_receiver_name(node: ast.AST) -> str | None:
    """`x.foo()` 里的 x（仅裸 Name）。"""
    if isinstance(node, ast.Name):
        return node.id
    return None


def _subscript_base_name(target: ast.AST) -> str | None:
    """`x[k] = ...` / `x[k][j] = ...` 里的根名 x。"""
    seen = False
    while isinstance(target, ast.Subscript):
        target = target.value
        seen = True
    if seen and isinstance(target, ast.Name):
        return target.id
    return None


def _unbounded_names(source: str) -> set[str]:
    containers, grown, reclaimed = _scan_source(source)
    return {name for name in containers if name in grown and name not in reclaimed}


def test_designated_faces_clean() -> None:
    """指定面真身两面：不得存在「只增长不淘汰」的模块级容器。"""
    offenders: list[str] = []
    for rel in _DESIGNATED_FACES:
        path = _ROOT / rel
        assert path.exists(), f"指定面文件缺席：{rel}"
        bad = _unbounded_names(path.read_text(encoding="utf-8"))
        for name in sorted(bad):
            offenders.append(f"{rel}::{name}")
    assert not offenders, "无界容器（只 append 从不淘汰）：" + ", ".join(offenders)


def test_poison_unbounded_flagged() -> None:
    """注毒腿：模块级 dict 只下标赋值、无淘汰 ⇒ 必须被判无界。"""
    poison = "from collections import OrderedDict\n" "_ACC: dict[str, int] = OrderedDict()\n" "_ACC['k'] = 1\n"
    assert "_ACC" in _unbounded_names(poison), "注毒未命中＝门失效（假绿）"


def test_eviction_recognized() -> None:
    """反向不误伤腿：同一段源码补一枚淘汰动作 ⇒ 必须转绿。"""
    fixed = (
        "from collections import OrderedDict\n"
        "_ACC: dict[str, int] = OrderedDict()\n"
        "_ACC['k'] = 1\n"
        "while len(_ACC) > 8:\n"
        "    _ACC.popitem(last=False)\n"
    )
    assert "_ACC" not in _unbounded_names(fixed), "补了淘汰仍被误判＝门过严"


def test_roster_not_empty() -> None:
    """下限断言：指定面必须真解析到受管容器（缺席＝文件被搬走，直接红）。"""
    total = 0
    for rel in _DESIGNATED_FACES:
        path = _ROOT / rel
        containers, _, _ = _scan_source(path.read_text(encoding="utf-8"))
        # 两面各自至少要有一枚受管容器（_HTTP_CLIENTS / _QUERY_EMBED_MEMO）。
        assert containers, f"{rel} 解析出 0 枚模块级容器——指定面清单已失真"
        total += len(containers)
    assert total >= 2, "受管容器总数异常偏低，门可能已被架空"
