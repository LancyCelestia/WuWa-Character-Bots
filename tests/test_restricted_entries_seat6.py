"""受限入口（``read_confined_bytes`` / ``revise_in_place``）供件确认锁——文件链路波席6。

波次简报要求：给席1 的接线前提是这两个入口**可用且判据完整**。本件锁的是接线方
依赖的行为面（全部离线、落点只在 ``tmp_path``）：

- ``read_confined_bytes``：白名单根内回读 ``(bytes, sha256)``；出根/缺白名单/
  可执行形态/超限额/目标不在各有独立拒绝码（fail-closed，owner 判定不缺腿）；
- ``revise_in_place``：读-改-写单口——目标必须在（绝不借改之名新建）、同字节
  不写盘、transform 拿不到写权限（只收字节）、失败不残改原文件。

owner 判定口径（席1 报告用）：两入口都不收 owner/角色参数——归属与角色门在
装配层（``file_exchange.adjudicate_file_write`` 问 ``safety_exec``），运行器只认
``WritePolicy.allowed_roots``（白名单 containment + ``resolve()`` 复核）与
``paths.py`` 禁触名册直判，两层任一不放行即拒。
"""

from __future__ import annotations

from pathlib import Path

from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr
from plugins.bot_unified_runtime.domains.media.digest import media_digest


def _policy(root: Path, **kwargs: object) -> rr.WritePolicy:
    return rr.policy_for_roots([root], **kwargs)  # type: ignore[arg-type]


def _staging(tmp_path: Path) -> dict[str, Path]:
    staging = tmp_path / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    return {"staging_dir": staging}


# ---------------------------------------------------------------------------
# read_confined_bytes：受限回读半边
# ---------------------------------------------------------------------------


def test_read_confined_returns_bytes_and_digest(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"hello")
    found = rr.read_confined_bytes("a.txt", policy=_policy(root))
    assert not isinstance(found, rr.WriteOutcome)
    data, digest = found
    assert data == b"hello"
    assert digest == media_digest(b"hello")


def test_read_outside_whitelist_denied(tmp_path: Path):
    """白名单外的落点不许回读：绝对路径引用按穿越形态拦（fail-closed）。"""
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    (outside / "b.txt").write_bytes(b"secret")
    found = rr.read_confined_bytes(outside / "b.txt", policy=_policy(inside))
    assert isinstance(found, rr.WriteOutcome)
    assert found.reason_code == rr.DenyCode.TRAVERSAL_DENIED


def test_read_without_whitelist_fails_closed(tmp_path: Path):
    (tmp_path / "c.txt").write_bytes(b"x")
    found = rr.read_confined_bytes("c.txt", policy=rr.WritePolicy())
    assert isinstance(found, rr.WriteOutcome)
    assert found.reason_code == rr.DenyCode.NO_WHITELIST


def test_read_missing_target_denied(tmp_path: Path):
    found = rr.read_confined_bytes("ghost.txt", policy=_policy(tmp_path))
    assert isinstance(found, rr.WriteOutcome)
    assert found.reason_code == rr.DenyCode.TARGET_MISSING


def test_read_over_limit_denied(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "big.txt").write_bytes(b"0123456789")
    policy = _policy(root, limits=rr.WriteLimits(max_file_bytes=4))
    found = rr.read_confined_bytes("big.txt", policy=policy)
    assert isinstance(found, rr.WriteOutcome)
    assert found.reason_code == rr.DenyCode.TOO_LARGE


def test_read_executable_form_denied(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "run.exe").write_bytes(b"MZ")
    found = rr.read_confined_bytes("run.exe", policy=_policy(root))
    assert isinstance(found, rr.WriteOutcome)
    assert found.reason_code == rr.DenyCode.EXECUTABLE_DENIED


# ---------------------------------------------------------------------------
# revise_in_place：读-改-写单口
# ---------------------------------------------------------------------------


def test_revise_replaces_content_atomically(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "doc.txt").write_bytes(b"v1")
    outcome = rr.revise_in_place(
        "doc.txt",
        lambda data: data + b"-v2",
        policy=_policy(root),
        **_staging(tmp_path),
    )
    assert outcome.ok, outcome.error_message()
    assert outcome.verb == rr.VERB_REPLACE
    assert outcome.written_bytes == len(b"v1-v2")
    assert (root / "doc.txt").read_bytes() == b"v1-v2"


def test_revise_unchanged_content_writes_nothing(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "doc.txt").write_bytes(b"same")
    before = (root / "doc.txt").stat().st_mtime_ns
    outcome = rr.revise_in_place(
        "doc.txt",
        lambda data: bytes(data),
        policy=_policy(root),
        **_staging(tmp_path),
    )
    assert outcome.ok
    assert outcome.written_bytes == 0
    assert "未变化" in outcome.detail
    assert (root / "doc.txt").read_bytes() == b"same"
    assert (root / "doc.txt").stat().st_mtime_ns == before, "同字节回写不该刷 mtime"


def test_revise_transform_none_is_denied_and_file_untouched(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "doc.txt").write_bytes(b"keep")
    outcome = rr.revise_in_place(
        "doc.txt",
        lambda data: None,  # type: ignore[arg-type,return-value]
        policy=_policy(root),
        **_staging(tmp_path),
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert (root / "doc.txt").read_bytes() == b"keep"


def test_revise_transform_exception_is_contained(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "doc.txt").write_bytes(b"keep")

    def boom(data: bytes) -> bytes:
        raise ValueError("no")

    outcome = rr.revise_in_place(
        "doc.txt", boom, policy=_policy(root), **_staging(tmp_path)
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert (root / "doc.txt").read_bytes() == b"keep"
    assert outcome.detail == "改写函数抛出 ValueError，原文件未改动。", (
        "detail 只带异常类型名，不带路径明文与文件内容"
    )
    assert str(root) not in outcome.detail


def test_revise_empty_product_is_denied(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "doc.txt").write_bytes(b"keep")
    outcome = rr.revise_in_place(
        "doc.txt", lambda data: b"", policy=_policy(root), **_staging(tmp_path)
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert (root / "doc.txt").read_bytes() == b"keep"


def test_revise_missing_target_never_creates(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outcome = rr.revise_in_place(
        "ghost.txt",
        lambda data: data + b"x",
        policy=_policy(root),
        **_staging(tmp_path),
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TARGET_MISSING
    assert not (root / "ghost.txt").exists(), "「改」不许借机新建"


def test_revise_without_whitelist_fails_closed(tmp_path: Path):
    (tmp_path / "doc.txt").write_bytes(b"x")
    outcome = rr.revise_in_place(
        "doc.txt", lambda data: data + b"y", policy=rr.WritePolicy()
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.NO_WHITELIST
