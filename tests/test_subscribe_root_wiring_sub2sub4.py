"""SUB 根腿：订阅推送正文过二手咽喉 ＋ 投递交回逐目的地结果 ＋ sink 接上。

三条都住根 `_deliver_v2_event` / 其装配调用点，来源＝`logs/SEAT-ATK-SUBSCRIBE.md`
ATK-SUB-4 腿②（远端 title/body/vision 输出裸拼以 bot 名义出群，可开伪造内部标记形态，
被后续引用腿的读侧当结构解析）与 ATK-SUB-1 根半（`return sent_any and all_success`
让部分失败没有台账 ⇒ 已成功群最多重投 5 遍）。域半已随 `de39afc` 落，本锁盯根。

根件禁 import（会跑装配并在 `data/` 落 sqlite），故三腿全走 AST 现算：
 ① `_deliver_v2_event` 体内必出现 `guard_secondhand_text(` 调用（真身
    `chat_reply/security/injection.py`，不许手拼包裹字面量）；
 ② 该函数的 return 不得再是 `sent_any and all_success` 那枚 BoolOp（＝交回逐目的地形状）；
 ③ 装配调用点必须把 `dead_letter_sink` 递给 register（否则死信仍只有一行 WARNING）。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
FUNC = "_deliver_v2_event"


def _root_text() -> str:
    return ROOT_INIT.read_text(encoding="utf-8-sig")


def _func(text: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    fn = next(
        (
            n
            for n in ast.walk(ast.parse(text))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == FUNC
        ),
        None,
    )
    assert fn is not None, f"根文件里找不到 {FUNC}＝坐标已漂，本锁失明"
    return fn


def test_subscription_body_passes_secondhand_throat() -> None:
    calls = {
        node.func.id
        for node in ast.walk(_func(_root_text()))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "guard_secondhand_text" in calls, (
        f"{FUNC} 没过二手咽喉（现有调用：{sorted(calls)[:8]}）＝ATK-SUB-4 腿②复发"
    )


def test_delivery_returns_per_destination_shape() -> None:
    """return 不能再是 `sent_any and all_success`——必须交回逐目的地结果。"""
    returns = [n for n in ast.walk(_func(_root_text())) if isinstance(n, ast.Return)]
    assert returns, f"{FUNC} 没有 return＝锁在空跑"
    legacy = [
        n
        for n in returns
        if isinstance(n.value, ast.BoolOp)
        and "sent_any" in ast.unparse(n.value)
        and "all_success" in ast.unparse(n.value)
    ]
    assert not legacy, (
        f"{FUNC} 仍 return 单个 bool（{ast.unparse(legacy[0].value)}）"
        "⇒ 部分失败无台账，已成功群会被重投至多 5 遍"
    )


def test_assembly_wires_dead_letter_sink() -> None:
    """根不直接 call register，而是把它交给 `defer_optional_subscription_registration`
    （可选装配失败不得挡启动）——defer 壳以 **kwargs 原样转发，故 sink 必须挂在这层。"""
    text = _root_text()
    hits = [
        node
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "defer_optional_subscription_registration"
        and any(
            isinstance(a, ast.Name) and a.id == "register_subscription_runtime_v2"
            for a in node.args
        )
    ]
    assert hits, "根文件里找不到把 register_subscription_runtime_v2 交给 defer 壳的调用＝坐标已漂"
    wired = any(any(kw.arg == "dead_letter_sink" for kw in call.keywords) for call in hits)
    assert wired, "装配点没把 dead_letter_sink 递给 register ⇒ 死信仍只有 WARNING 一行"


def test_locks_bite_on_poisoned_copy(tmp_path: Path) -> None:
    """注毒打在 tmp 副本：三处各抹一次，三条判据必须各红一次。"""
    text = _root_text()
    for needle, expect_absent in (
        ("guard_secondhand_text(", "①"),
        ("dead_letter_sink", "③"),
    ):
        if needle not in text:
            continue  # 该腿尚未落地：本锁此刻本就红，注毒无意义
        # 注毒只改标识符、**保留括号**——把 "(" 一起吃掉会让副本语法不过，
        # 那就成了"崩溃冒充判红"（本仓纪律：信 FAILED，不信 ERROR）。
        ident = needle.rstrip("(")
        replacement = ident + "_POISONED" + ("(" if needle.endswith("(") else "")
        # 一次打掉**全部**真身调用：函数里有多处 guard 调用，只毒一枚的话判据
        # 依然绿（那不是锁瞎，是我这发毒没覆盖到判据的射程）。
        poisoned = text.replace(needle, replacement)
        assert poisoned != text
        compile(poisoned, "root_poisoned.py", "exec")  # 语法必过，否则这发毒无效
        copy = tmp_path / "root_poisoned.py"
        copy.write_text(poisoned, encoding="utf-8")
        reparsed = copy.read_text(encoding="utf-8-sig")
        if expect_absent == "①":
            calls = {
                node.func.id
                for node in ast.walk(_func(reparsed))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            assert "guard_secondhand_text" not in calls, "注毒后①仍认得出＝量具空跑"
            assert "guard_secondhand_text_POISONED" in calls, "注毒没打在真身调用上＝毒无效"
        else:
            calls = [
                n
                for n in ast.walk(ast.parse(reparsed))
                if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "defer_optional_subscription_registration"
                and any(
                    isinstance(a, ast.Name)
                    and a.id == "register_subscription_runtime_v2"
                    for a in n.args
                )
            ]
            assert calls and all(
                all(kw.arg != "dead_letter_sink" for kw in c.keywords) for c in calls
            ), "注毒后③仍认得出＝量具空跑"
