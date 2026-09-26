"""受限写盘运行器「活性锁」——需求 16(2)(3) 收尾（席位 S-T-RUNNER-FIX）。

补 ``tests/test_file_exchange_restricted_runner.py`` 留的那一格：那件把
``external_verdict`` 注入缝**只用假守卫**跑过（拒 / 抛 / 空放行各一枚），证明的是
「缝的机制在」；它从没让**真身** ``safety_exec.paths.check_sendable()`` 从这条缝里
真跑过一次。本件专职跑真身，堵住本波反复点名的「注册了 ≠ 能跑」那一格。

三组判据（对应简报§2 (a)(c)(d)）：

① **推翻旧判据 + 防它复活**（(a) 的反证钉成锁）：``paths.check_sendable(str)``
   今天返回 ``PathDecision``、不抛 ``TypeError``；真身适配器 ``sendable_verdict``
   把三种判定（``allowed``/``denied``/``needs_review``）与异常各翻译成契约字符串。
② **活性**（(c)）：真守卫接上、真跑到 ``publish``——白名单内的合法写**放行**
   （缝没被自我关闭），白名单内但撞禁触名册（``settings/`` 目录）的落点被真身
   **当场拦下**（缝真的在执法，不是挂着不接）。
③ **三条反模式门**（(d)）：册外落点被拒（``..`` 逃出手形态＝``TRAVERSAL_DENIED``，
   在消毒层先拦）；超限不半途写
   （目的地连目录都不建）；判定件抛异常＝诚实拦（``EXTERNAL_GUARD_DENIED``），
   绝不静默放行。

全部离线、零网络、落点只在 ``tmp_path``；每次注入 ``default_policy`` 都用
``set_default_policy(None)`` 收尾，绝不把假根留给下一个用例。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr

_DRIVE_FORM_RE = re.compile(r"[A-Za-z]:[\\/]")


def _policy(root: Path, **kwargs: object) -> rr.WritePolicy:
    return rr.policy_for_roots([root], **kwargs)  # type: ignore[arg-type]


def _staging(tmp_path: Path) -> dict[str, Path]:
    staging = tmp_path / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    return {"staging_dir": staging}


class _Decision:
    """最小 PathDecision 替身（只带适配器消费的 ``verdict``/``reason_code``）。"""

    def __init__(self, verdict: str, reason_code: str = "") -> None:
        self.verdict = verdict
        self.reason_code = reason_code


# ---------------------------------------------------------------------------
# ① 推翻旧判据：真身不抛 TypeError；适配器翻译三态（含 fail-closed）
# ---------------------------------------------------------------------------


def test_check_sendable_returns_a_decision_and_never_raises_today(
    tmp_path: Path,
) -> None:
    """钉死「旧句：每次调用都抛 TypeError」已被实测推翻，并防它复活成回归。

    真身 ``check_sendable(str)`` 单参调用返回 ``PathDecision``——不抛。撞名册的落点
    给 ``denied`` 判定，而不是异常：这正是「接了会当场失败」那句旧结论要改写的根据
    （失败形态是「被判定拦下」，可归因、可放行合法件，不是 TypeError 崩溃）。
    """
    try:
        paths.set_default_policy(
            paths.build_policy(workspace_root=tmp_path, runtime_data_root=tmp_path)
        )
        decision = paths.check_sendable(str(tmp_path / "note.md"))
        assert isinstance(decision, paths.PathDecision)
        assert decision.verdict == paths.VERDICT_ALLOWED

        denied = paths.check_sendable(str(tmp_path / "settings" / "note.md"))
        assert isinstance(denied, paths.PathDecision)
        assert denied.verdict == paths.VERDICT_DENIED
    finally:
        paths.set_default_policy(None)


@pytest.mark.parametrize(
    ("verdict", "expect_pass"),
    [(paths.VERDICT_ALLOWED, True), (paths.VERDICT_DENIED, False),
     (paths.VERDICT_NEEDS_REVIEW, False)],
)
def test_sendable_verdict_translates_three_verdicts(
    monkeypatch: pytest.MonkeyPatch, verdict: str, expect_pass: bool
) -> None:
    """真身判定 → 契约字符串：只 ``allowed`` 放行，其余（含 ``needs_review``）拦。"""
    monkeypatch.setattr(
        paths, "check_sendable", lambda *_a, **_k: _Decision(verdict, "some_reason")
    )
    result = rr.sendable_verdict("C:/somewhere/note.md")
    assert (result == "") is expect_pass
    if not expect_pass:
        assert result, "非放行判定必须回非空代号（否则等于静默放行）"


def test_sendable_verdict_names_an_unavailable_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """判定件抛异常（缺依赖/崩了）＝明说代号，绝不回空串蒙混放行。"""

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("判定件不可用")

    monkeypatch.setattr(paths, "check_sendable", _boom)
    result = rr.sendable_verdict("C:/somewhere/note.md")
    assert result == "sendable_guard_unavailable"


# ---------------------------------------------------------------------------
# ② 活性：真守卫接上、真跑到 publish（放行合法件 + 拦下名册落点）
# ---------------------------------------------------------------------------


def test_live_guard_gates_inside_the_whitelist(tmp_path: Path) -> None:
    """真身守卫接进 ``external_verdict``，端到端跑到落盘决策。

    两格一起证「注册了≠能跑」被堵：
      - 合法件（``note.md``）→ 真守卫放行 → 写成功（缝**没有**把一切自我关闭）；
      - 白名单内但撞禁触名册（``settings/`` 目录）→ 真守卫当场拦下 →
        ``EXTERNAL_GUARD_DENIED``，目的地连目录都没建（运行器自身那几层全放行，
        只有真名册这一层拦得住＝执法确实发生在这一格）。
    """
    root = tmp_path / "vault"
    guard = rr.sendable_verdict
    try:
        paths.set_default_policy(
            paths.build_policy(workspace_root=root, runtime_data_root=root)
        )
        policy = _policy(root, external_verdict=guard)

        ok = rr.create_bytes(
            "note.md", "# 合法\n".encode(), policy=policy, **_staging(tmp_path)
        )
        assert ok.ok, ok.error_message()
        assert (root / "note.md").read_bytes() == "# 合法\n".encode()

        blocked = rr.create_bytes(
            "settings/note.md",
            "# 撞名册\n".encode(),
            policy=policy,
            **_staging(tmp_path),
        )
        assert blocked.reason_code == rr.DenyCode.EXTERNAL_GUARD_DENIED
        assert not (root / "settings").exists(), "被拦的落点不该在目的地留下目录"
        assert not _DRIVE_FORM_RE.search(blocked.error_message())
    finally:
        paths.set_default_policy(None)


# ---------------------------------------------------------------------------
# ③ 三条反模式门：册外拒 / 超限不半途写 / 缺依赖诚实拦
# ---------------------------------------------------------------------------


def test_anti_pattern_off_whitelist_is_rejected(tmp_path: Path) -> None:
    """反模式门 1：白名单外的落点（``..`` 逃出手形态）被拒，别处不落盘。

    真身运行器在段消毒层就把 ``..`` 拦成 ``TRAVERSAL_DENIED``（比 containment
    更早、更硬）；白名单整体是缺省 fail-closed（``allowed_roots=()`` ⇒
    ``NO_WHITELIST``），那一格由存量件执法，本锁钉的是「想从缝里溜出去」这条。
    """
    root = tmp_path / "vault"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(parents=True, exist_ok=True)
    outcome = rr.create_bytes(
        "../elsewhere/smuggle.md",
        b"# nope\n",
        policy=_policy(root),
        **_staging(tmp_path),
    )
    assert outcome.reason_code == rr.DenyCode.TRAVERSAL_DENIED
    assert not (elsewhere / "smuggle.md").exists()


def test_anti_pattern_over_limit_writes_nothing(tmp_path: Path) -> None:
    """反模式门 2：超限连暂存都不进，目的地不出现任何中间件（含 ``.part``）。"""
    root = tmp_path / "vault"
    limits = rr.WriteLimits(max_file_bytes=8)
    policy = rr.WritePolicy(allowed_roots=(root,), limits=limits)
    outcome = rr.create_bytes(
        "big.md", b"x" * 4096, policy=policy, **_staging(tmp_path)
    )
    assert outcome.reason_code == rr.DenyCode.TOO_LARGE
    assert not root.exists(), "超限时目的地必须空空如也"


def test_anti_pattern_missing_guard_fails_closed_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反模式门 3：判定件抛异常时，接了守卫的写盘＝诚实拦下，不静默放行。

    旧句「缺省不接」把这条坑填成了「看起来安全、其实整条腿挂着不执法」。本锁要求：
    一旦真守卫被接上，它抛异常时**必须**拒（``EXTERNAL_GUARD_DENIED``），而不是
    因判不出就放过（那等于把 fail-closed 反转为 fail-open）。
    """
    root = tmp_path / "vault"

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("判定件不可用")

    monkeypatch.setattr(paths, "check_sendable", _boom)
    outcome = rr.create_bytes(
        "note.md",
        b"# x\n",
        policy=_policy(root, external_verdict=rr.sendable_verdict),
        **_staging(tmp_path),
    )
    assert outcome.reason_code == rr.DenyCode.EXTERNAL_GUARD_DENIED
    assert not (root / "note.md").exists()
