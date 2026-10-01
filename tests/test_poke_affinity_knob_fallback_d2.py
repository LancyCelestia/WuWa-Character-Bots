"""D-2：根装配面读好感兜底数，必须与 ``config.py`` 真身缺省逐枚等值。

来源＝`logs/AUDIT-POKEHOST.md:134`（Minor·D-2）。根 `_record_poke_affinity` 里
`getattr(config, "bot_poke_affinity_delta", 0.5) or 0.5` 与 `..._daily_max", 5.0) or 5.0`
两枚兜底，真身 `config.py` 的字段缺省是 **0.1 / 0.5**——字面量与真身不一致。
生产行为今日不变（Config 真字段 getattr 永不落兜底），但这是「兜底值≠真身」的一致性债：
哪天字段没装载，静默按错的数走。poke.py 同款坑已由 `test_poke_five_way_matrix.py`
用 AST 锁修过，本件把同一把尺伸到根读点（**零手抄数字**：两侧都从源码现读）。

为什么不直接扩那件的读点表：`_knob_fallbacks` 只认 `PokeDispatcher._knobs` 里
`getattr(config, k, 兜底)` 单形，根这两枚多一个 `or 兜底` 二段形、且在另一个文件，
硬塞会改到别人在册的锁。本件同形另立，注毒自证照抄。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
CONFIG_SRC = REPO_ROOT / "plugins/bot_unified_runtime/config.py"
FUNC = "_record_poke_affinity"


def _config_defaults(source: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        init = node.value
        if (
            isinstance(init, ast.Call)
            and getattr(init.func, "attr", "") == "Field"
            and init.args
        ):
            out[node.target.id] = ast.literal_eval(init.args[0])
        elif init is not None:
            try:
                out[node.target.id] = ast.literal_eval(init)
            except (ValueError, SyntaxError):
                pass
    return out


def _root_fallbacks(source: str) -> dict[str, object]:
    """现读根 `_record_poke_affinity` 里的 ``getattr(cfg, "<键>", 兜底) [or 兜底]``。"""
    tree = ast.parse(source)
    fn = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == FUNC
        ),
        None,
    )
    assert fn is not None, f"根文件里找不到 {FUNC}＝坐标已漂，本锁失明"
    out: dict[str, object] = {}
    for node in ast.walk(fn):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 3
            and isinstance(node.args[1], ast.Constant)
            and str(node.args[1].value).startswith("bot_poke_affinity")
        ):
            continue
        out[str(node.args[1].value)] = ast.literal_eval(node.args[2])
    return out


def test_root_poke_affinity_fallbacks_match_config_defaults() -> None:
    fallbacks = _root_fallbacks(ROOT_INIT.read_text(encoding="utf-8-sig"))
    assert len(fallbacks) >= 2, f"根读点现算只有 {fallbacks}＝锁在空跑"
    defaults = _config_defaults(CONFIG_SRC.read_text(encoding="utf-8-sig"))
    bad = [
        f"{key}: 根兜底 {fallbacks[key]!r} ≠ config.py 缺省 {defaults.get(key)!r}"
        for key in fallbacks
        if key in defaults and defaults[key] != fallbacks[key]
    ]
    assert not bad, "根装配面兜底数与真身缺省不一致：" + "；".join(bad)


def test_root_poke_affinity_lock_bites_on_poisoned_copy(tmp_path: Path) -> None:
    """注毒打在内存副本：把 delta 兜底改回旧错值，锁必须点名它。"""
    src = ROOT_INIT.read_text(encoding="utf-8-sig")
    assert '"bot_poke_affinity_delta"' in src, "锚点不在＝注毒会空跑"
    poisoned = re.sub(
        r'(getattr\(config, "bot_poke_affinity_delta", )([0-9.]+)',
        lambda m: f"{m.group(1)}{float(m.group(2)) + 1.0}",
        src,
        count=1,
    )
    assert poisoned != src, "注毒未落到真身文本＝空跑"
    bad = tmp_path / "root_poisoned.py"
    bad.write_text(poisoned, encoding="utf-8")
    fallbacks = _root_fallbacks(bad.read_text(encoding="utf-8-sig"))
    defaults = _config_defaults(CONFIG_SRC.read_text(encoding="utf-8-sig"))
    assert fallbacks and any(
        defaults.get(k) != v for k, v in fallbacks.items() if k in defaults
    ), "注毒后锁仍判绿＝它看不见这件事"
