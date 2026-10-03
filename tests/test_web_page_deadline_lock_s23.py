"""S23 锁：联网腿「页面正文富化」一跳必须受既有请求预算截止（S8-1 v2 补丁）。

判据口径（用户裁定）：压延迟只删无用功、**不动任何天花板**。本锁钉三头：

① 行为面（假时钟，零真请求）：摘出源码里**那枚真比较表达式**（不重写判据），用真
   `DeadlineBudget` 喂两把假时钟——剩得不够一跳 ⇒ 跳过富化；够 ⇒ 照旧等。
② 形状面：跳过分支只准记 `page:deadline_skipped` 进既有 `web_error_kinds`（遥测
   `web_error_kind` 列在册），**绝不改写 `web_hits`**（＝命中照送、不丢结果）；富化的
   `chat-web-page` 线程池必须整体落进 `else` 腿（＝预算够时才等）。
③ 天花板面：截止表达式里不许出现任何字面量数值、不许另读超时配置键（＝没夹带新钳子）。

注毒自证：`git apply -R` 摘掉补丁后本文件必红（席报告留痕）。
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

CHAT_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)

_MARKER = "page:deadline_skipped"
_POOL_PREFIX = "chat-web-page"


def _tree() -> ast.Module:
    return ast.parse(CHAT_PATH.read_text(encoding="utf-8"), filename=str(CHAT_PATH))


def _deadline_compare() -> ast.Compare:
    """摘出 `_page_leg_too_late = (<剩余> <= float(web_page_timeout_seconds))`。

    只认比较表达式那一枚赋值（同名的 `_page_leg_too_late = False` 是预置初值，跳过）。
    """
    found: list[ast.Compare] = []
    seen_init = False
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "_page_leg_too_late" for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant):
            seen_init = True
            continue
        if isinstance(node.value, ast.Compare):
            found.append(node.value)
    if not found:
        raise AssertionError(
            "未找到富化一跳的预算截止判据（补丁 S8-1 v2 未落地？摘掉后此处必红）"
            f"；只见到初值赋值={seen_init}"
        )
    assert len(found) == 1, f"截止判据应恰一枚，实得 {len(found)}"
    value = found[0]
    left = value.left
    assert isinstance(left, ast.Call), "剩余秒数必须来自 remaining_seconds() 调用"
    assert (
        isinstance(left.func, ast.Attribute)
        and left.func.attr == "remaining_seconds"
        and isinstance(left.func.value, ast.Name)
        and left.func.value.id == "request_budget"
    ), "截止判据必须读既有 request_budget（DeadlineBudget），禁第二本账"
    assert len(value.ops) == 1 and isinstance(value.ops[0], ast.LtE), "判据应为 <="
    assert len(value.comparators) == 1
    rhs = value.comparators[0]
    assert (
        isinstance(rhs, ast.Call)
        and isinstance(rhs.func, ast.Name)
        and rhs.func.id == "float"
        and any(
            isinstance(a, ast.Name) and a.id == "web_page_timeout_seconds" for a in rhs.args
        )
    ), "一跳的尺必须复用既有 web_page_timeout_seconds，不许另立数值"
    assert not any(
        isinstance(inner, ast.Constant) and isinstance(inner.value, (int, float))
        for inner in ast.walk(value)
    ), "🔴 截止表达式里出现字面量数值＝动了天花板，违裁定"
    return value


def _guard_ifs() -> tuple[ast.If, ast.If]:
    """返回 (预算启用外层 If, `_page_leg_too_late` 分支 If)。"""
    tree = _tree()
    outer = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "request_budget" in ast.unparse(node.test)
        and "enabled" in ast.unparse(node.test)
        and any(
            isinstance(x, ast.Name) and x.id == "_page_leg_too_late"
            for sub in ast.walk(node)
            if isinstance(sub, ast.Assign)
            for x in sub.targets
        )
    ]
    branch = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "_page_leg_too_late"
    ]
    assert outer, "缺 `request_budget is not None and request_budget.enabled` 外门"
    assert branch, "缺 `_page_leg_too_late` 分支"
    return outer[0], branch[0]


def test_budget_exhausted_skips_enrichment_but_keeps_hits() -> None:
    """跳过腿：只记留痕、不改写 web_hits（＝命中照送）；富化线程池在 else 腿里。"""
    _outer, branch = _guard_ifs()

    body_src = "\n".join(ast.unparse(stmt) for stmt in branch.body)
    assert _MARKER in body_src, f"跳过腿必须留痕 {_MARKER}：{body_src[:200]}"
    assert "web_error_kinds" in body_src, f"留痕只准进既有 web_error_kinds：{body_src[:200]}"
    assert "web_hits" not in body_src, f"🔴 跳过腿不许改写 web_hits（命中照送）：{body_src[:240]}"
    assert _POOL_PREFIX not in body_src, f"🔴 预算不足时不许再起富化线程池：{body_src[:240]}"

    orelse_src = "\n".join(ast.unparse(stmt) for stmt in branch.orelse)
    assert _POOL_PREFIX in orelse_src, "富化一跳（chat-web-page）必须落在预算够用的 else 腿"
    assert "web_hits" in orelse_src, "else 腿才是把正文并入 web_hits 的地方"


def test_only_one_page_enrichment_pool_no_second_route() -> None:
    """零新通路：全文件里富化线程池前缀与留痕标记各只出现一次。"""
    src = CHAT_PATH.read_text(encoding="utf-8")
    assert src.count(_POOL_PREFIX) == 1, f"富化通路出现 {src.count(_POOL_PREFIX)} 次，应恰 1"
    assert src.count(_MARKER) == 1, f"{_MARKER} 应恰一处留痕点"


def test_shipped_predicate_with_fake_clock() -> None:
    """假时钟跑**那枚真表达式**：不够一跳 ⇒ True（跳过）；够 ⇒ False（照等）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.deadline import (
        DeadlineBudget,
    )

    expr = compile(ast.unparse(_deadline_compare()), "<s8-1>", "eval")
    # 尺取 2.0 只为把两把假时钟拉开（真缺省 web_page_timeout_seconds=6.0 一字未动，
    # 由 test_guard_reads_no_new_ceiling 与本文件的「无字面量」断言共同守住）。
    timeout = 2.0

    def budget_with_remaining(seconds: float) -> DeadlineBudget:
        total = seconds + 40.0
        return DeadlineBudget(total, started_at=time.monotonic() - (total - seconds))

    tight = eval(
        expr, {}, {"request_budget": budget_with_remaining(1.5), "web_page_timeout_seconds": timeout}
    )
    assert tight is True, "剩 1.5s < 一跳 2.0s 必须判为「不再等富化」"

    enough = eval(
        expr, {}, {"request_budget": budget_with_remaining(5.0), "web_page_timeout_seconds": timeout}
    )
    assert enough is False, "剩 5.0s > 一跳 2.0s 必须照旧等（行为不变）"

    assert DeadlineBudget(0).enabled is False, "预算=0 视为未启用 ⇒ 外门放行、行为与改前一致"


def test_guard_reads_no_new_ceiling() -> None:
    """🔴 不动天花板：两道门（外门 + 分支判据）里零字面量数值、零新超时配置键。"""
    outer, branch = _guard_ifs()
    for node in (outer.test, branch.test):
        src = ast.unparse(node)
        assert not any(
            isinstance(c, ast.Constant) and isinstance(c.value, (int, float))
            for c in ast.walk(node)
        ), f"门条件出现字面量数值，疑似新钳子：{src[:200]}"
    guard_src = ast.unparse(outer.test)
    for name in ("bot_chat_timeout_seconds", "bot_request_budget_seconds", "timeout"):
        assert name not in guard_src, f"外门不该另读 {name}（本函数在册件已够）：{guard_src[:200]}"
