"""「修改已有文件」受限入口的**接线形态锁**（席6 供件，给席1 的对接面）。

背景：``restricted_runner.read_confined_bytes`` / ``revise_in_place`` 在册但全树
没有对话触发面——会话入口（chat.py artifact_request 一族）由席1 接线。本件锁的
是席1 实际要消费的**组合形态**，全部照抄现有装配真身：

- 策略＝``file_exchange.write_policy_from_config``（六键 → 白名单根 + 限额 +
  ``external_verdict=sendable_verdict``）与 ``_read_policy_from_config``（回读
  换 ``bot_files_read_confined_max_bytes`` 那一枚键）——owner 判定不另立；
- 入口＝运行器两口的**直调签名**（席1 拿到手就能调的形状）；
- 错误路径＝``target_missing`` / ``traversal_denied`` / ``transform_failed`` 三态
  逐枚验形（``WriteOutcome.error_message()`` 人话、不带路径明文）。

端到端「命令文本 → 裁决 → 落盘 → 回读 → 出站件」全链已由
``tests/test_files_write_side_assembly.py`` 锁死，本件不重复；容器实底
（禁触名册/注毒自证）在 ``tests/test_restricted_runner_confinement.py``，
同样不重复。全部离线、零网络、落点只在 ``tmp_path``。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.files.capabilities import file_exchange as fx
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr
from plugins.bot_unified_runtime.domains.media.digest import media_digest


@pytest.fixture
def wired_paths(tmp_path: Path) -> Iterator[paths.PathDomainPolicy]:
    """把假根（``tmp_path`` 为工作区）接到进程级缺省判定口，用例结束复位。"""
    active = paths.build_policy(workspace_root=tmp_path)
    paths.set_default_policy(active)
    try:
        yield active
    finally:
        paths.set_default_policy(None)


def _conf(tmp_path: Path, **overrides: object) -> Config:
    base: dict[str, object] = {
        "bot_download_dir": str(tmp_path / "dl"),
        "bot_files_write_allowed_dirs": [str(tmp_path / "out")],
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


def _isolated(tmp_path: Path) -> dict[str, object]:
    """隔离配额账与暂存位（不与全局缺省账串数）。"""
    return {
        "ledger": rr.DailyQuotaLedger(),
        "date_key": (lambda: "D1"),
        "staging_dir": tmp_path / "_stg",
    }


def _create(
    root: Path, name: str, data: bytes, tmp_path: Path, policy: rr.WritePolicy
) -> rr.WriteOutcome:
    outcome = rr.create_bytes(name, data, policy=policy, **_isolated(tmp_path))  # type: ignore[arg-type]
    assert outcome.ok, outcome.error_message()
    return outcome


# ---------------------------------------------------------------------------
# ① read_confined_bytes：config 策略直调（席1 的「先看现状」半边）
# ---------------------------------------------------------------------------


def test_read_confined_bytes_via_config_policy_returns_bytes_and_digest(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    cfg = _conf(tmp_path)
    policy = fx.write_policy_from_config(cfg)
    payload = b"version one\n"
    created = _create(policy.allowed_roots[0].parent, "note.md", payload, tmp_path, policy)
    # create_bytes 的落点在白名单根内；用相对名寻址（咽喉只认相对落点）。
    name = Path(created.path or Path()).name
    found = rr.read_confined_bytes(name, policy=policy)
    assert not isinstance(found, rr.WriteOutcome)
    data, digest = found
    assert data == payload
    assert digest == media_digest(payload)


def test_read_confined_bytes_uses_the_read_side_cap_key(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    cfg = _conf(tmp_path, bot_files_read_confined_max_bytes=16)
    write_policy = fx.write_policy_from_config(cfg)
    read_policy = fx._read_policy_from_config(cfg)
    created = _create(
        write_policy.allowed_roots[0].parent,
        "big.md",
        b"x" * 32,
        tmp_path,
        write_policy,
    )
    name = Path(created.path or Path()).name
    denied = rr.read_confined_bytes(name, policy=read_policy)
    assert isinstance(denied, rr.WriteOutcome)
    assert denied.reason_code == rr.DenyCode.TOO_LARGE
    assert denied.error_message(), "人话失败说明必须在场"
    # 同一枚文件在写侧缺省限额下创建成功＝读写两枚键各管各的（写宽读窄可配）。


# ---------------------------------------------------------------------------
# ② revise_in_place：config 策略直调（席1 的「读-改-写」单口）
# ---------------------------------------------------------------------------


def test_revise_in_place_via_config_policy_rewrites_on_real_change(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    cfg = _conf(tmp_path)
    policy = fx.write_policy_from_config(cfg)
    created = _create(
        policy.allowed_roots[0].parent,
        "note.md",
        b"hello\n",
        tmp_path,
        policy,
    )
    name = Path(created.path or Path()).name
    outcome = rr.revise_in_place(
        name,
        lambda data: data + b"appended\n",
        policy=policy,
        **_isolated(tmp_path),  # type: ignore[arg-type]
    )
    assert outcome.ok, outcome.error_message()
    assert outcome.verb == rr.VERB_REPLACE
    assert outcome.path is not None and outcome.path.read_bytes() == b"hello\nappended\n"


def test_revise_in_place_identity_change_writes_nothing(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    cfg = _conf(tmp_path)
    policy = fx.write_policy_from_config(cfg)
    created = _create(
        policy.allowed_roots[0].parent, "note.md", b"same\n", tmp_path, policy
    )
    name = Path(created.path or Path()).name
    ledger = rr.DailyQuotaLedger()
    outcome = rr.revise_in_place(
        name,
        lambda data: bytes(data),
        policy=policy,
        ledger=ledger,
        date_key=lambda: "D1",
        staging_dir=tmp_path / "_stg",
    )
    assert outcome.ok and outcome.written_bytes == 0
    assert ledger.used(outcome.root_label or "x", "D1", rr.VERB_REPLACE) == 0, (
        "同字节不写不烧配额"
    )


# ---------------------------------------------------------------------------
# ③ 错误路径三态（席1 的会话面措辞直接吃 error_message()）
# ---------------------------------------------------------------------------


def test_revise_in_place_missing_target_is_target_missing(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    policy = fx.write_policy_from_config(_conf(tmp_path))
    outcome = rr.revise_in_place(
        "ghost.md", lambda data: data, policy=policy, **_isolated(tmp_path)  # type: ignore[arg-type]
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TARGET_MISSING
    message = outcome.error_message()
    assert message and "[A-Za-z]:" not in message and "\\\\" not in message, (
        f"人话失败说明不许带盘符/路径明文：{message!r}"
    )


def test_revise_in_place_traversal_ref_is_denied(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    policy = fx.write_policy_from_config(_conf(tmp_path))
    outcome = rr.revise_in_place(
        "../escape.md", lambda data: data, policy=policy, **_isolated(tmp_path)  # type: ignore[arg-type]
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TRAVERSAL_DENIED


def test_revise_in_place_transform_failure_leaves_original_intact(
    tmp_path: Path, wired_paths: paths.PathDomainPolicy
) -> None:
    policy = fx.write_policy_from_config(_conf(tmp_path))
    created = _create(
        policy.allowed_roots[0].parent, "note.md", b"original\n", tmp_path, policy
    )
    name = Path(created.path or Path()).name

    def boom(_data: bytes) -> object:
        raise RuntimeError("注毒：改写函数炸了")

    outcome = rr.revise_in_place(
        name, boom, policy=policy, **_isolated(tmp_path)  # type: ignore[arg-type]
    )
    assert outcome.denied
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert "RuntimeError" in (outcome.detail or ""), "detail 点名异常类型（不回显内容）"
    assert created.path is not None and created.path.read_bytes() == b"original\n"
