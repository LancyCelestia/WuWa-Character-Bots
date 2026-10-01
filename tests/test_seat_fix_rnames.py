"""S-FIX-RNAMES（2026-09-27）：Win32 保留设备名中央名册补全锁（攻击审计 F-G2 根修）。

背景：``restricted_runner._RESERVED_WIN32_BASENAMES`` 旧表只收 con/prn/aux/nul +
com1-9 + lpt1-9，缺 ``com0``/``lpt0``/``CLOCK$``/``CONIN$``/``CONOUT$``（微软
「Naming Files, Paths, and Namespaces」保留名全集含这三族边角）。这类名带任意
后缀都被 Win32 当设备：media_archive 的 ``sanitize_dirname`` 直接调用中央判据，
放行后 ``mkdir`` 抛误导性 OSError，把「一因一码」破坏成通用「写入失败」。

判据语义（本件锁死、不许反向放宽）：
- 比对**主名段**（点号前首段、casefold 整词），不是全文件名子串 ⇒
  ``backup_com1_notes.txt`` 一类合法名不误伤；
- 带任意后缀同样命中（``com1.md``/``CLOCK$.log``）；
- ``restricted_runner.sanitize_write_segments`` 里含 ``$`` 的名字会先被
  ``_LEGAL_SEGMENT_RE``（字符集不含 ``$``）拦成 ``bad_name``——纵深防御，两码
  皆拒，本件把这一格现状也钉死（改判必须先改本锁，不许静默漂移）。

单源在场：保留名账只有 ``_RESERVED_WIN32_BASENAMES`` 一枚生产真身
（``safety_exec/paths.py`` 现算零 reserved 账目——它管落点域禁触名册，不管段名形态；
media_archive/today_history/meme 都是调用方）。本件⑤用结构锁防第三副本。
"""

from __future__ import annotations

import inspect
import re

import pytest

from plugins.bot_unified_runtime.domains.files.sender import (
    restricted_runner as rr,
)
from plugins.bot_unified_runtime.domains.media.archive import (
    media_archive as ma,
)

# ---------------------------------------------------------------------------
# 期望真值表（由微软保留名清单派生的完整形态，本件的「唯一尺」）
# ---------------------------------------------------------------------------

_EXPECTED_RESERVED: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    | {f"com{i}" for i in range(10)}
    | {f"lpt{i}" for i in range(10)}
)

_NEW_MEMBERS = (
    # 本波补入的三族边角（旧表盲区＝F-G2 实锤格）
    [f"com{i}" for i in range(10)]
    + [f"lpt{i}" for i in range(10)]
    + ["clock$", "conin$", "conout$"]
)
_LEGACY_MEMBERS = ["con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"]


# ---------------------------------------------------------------------------
# ① 中央判据：逐名正样本（裸名 / 大小写混排 / 带任意后缀）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _NEW_MEMBERS + _LEGACY_MEMBERS)
def test_is_reserved_device_name_accepts_every_rostered_name(name: str) -> None:
    assert rr._is_reserved_device_name(name) is True, f"{name!r} 应命中保留名"
    assert rr._is_reserved_device_name(name.upper()) is True
    assert rr._is_reserved_device_name(f"{name}.md") is True, "换扩展名不构成绕行"
    assert rr._is_reserved_device_name(f"{name}.tar.gz") is True


def test_c_zero_devices_and_dollar_family_are_now_rostered() -> None:
    """F-G2 点名的五枚边角逐一现点名（防「补了个大概」）。"""
    for name in ("com0", "lpt0", "CLOCK$", "CONIN$", "CONOUT$"):
        assert rr._is_reserved_device_name(name) is True, f"{name} 仍被放行"
        assert rr._is_reserved_device_name(name.lower() + ".txt") is True


# ---------------------------------------------------------------------------
# ② 负样本：主名段整词比对 ⇒ 子串命中不许误伤（现算现行语义定期望值）
# ---------------------------------------------------------------------------

_NEGATIVE_NAMES = [
    "com10",  # Windows 保留只到 COM9（审计席确认为正当放行）
    "com10.md",
    "lpt10.md",
    "my_com1_bak.txt",  # com1 在中间段，不是主名段
    "backup_com1_notes.txt",  # 简报点名格：整名不是设备，放行
    "concise.md",
    "null-point.md",
    "notes.md",
    "clockworks.md",  # clock 是主名段前缀而非整词
    "conin.txt",  # 无 $ 的 conin 不是设备名
    "conio.txt",
    "auxiliary.dat",
    "prn1.md",
    "",  # 空段不是设备名（由 bad_name 另行执法）
]


@pytest.mark.parametrize("name", _NEGATIVE_NAMES)
def test_is_reserved_device_name_does_not_overmatch_substrings(name: str) -> None:
    assert rr._is_reserved_device_name(name) is False, f"{name!r} 被误伤"


# ---------------------------------------------------------------------------
# ③ 端到端 A：media_archive.sanitize_dirname（F-G2 的实际咬人路径）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dirname", ["CLOCK$", "CONIN$", "CONOUT$", "com0", "lpt0", "nul", "COM1.md"]
)
def test_sanitize_dirname_raises_reserved_for_rostered_names(dirname: str) -> None:
    with pytest.raises(ma.ArchiveReservedNameError):
        ma.sanitize_dirname(dirname)


@pytest.mark.parametrize("dirname", ["backup_com1_notes", "com10", "clockworks"])
def test_sanitize_dirname_keeps_legal_lookalikes(dirname: str) -> None:
    assert ma.sanitize_dirname(dirname) == dirname


# ---------------------------------------------------------------------------
# ④ 端到端 B：sanitize_write_segments 的码归属（含 $ 名字先被字符集拦＝现状钉死）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["com0.md", "lpt0.txt", "com1.md", "lpt9", "nul.md"])
def test_write_segments_denies_with_reserved_name_code(ref: str) -> None:
    with pytest.raises(rr._Rejected) as exc:
        rr.sanitize_write_segments(ref)
    assert exc.value.code == rr.DenyCode.RESERVED_NAME


@pytest.mark.parametrize("ref", ["CLOCK$", "CONIN$.md"])
def test_write_segments_dollar_names_denied_earlier_by_segment_charset(
    ref: str,
) -> None:
    """含 ``$`` 段先撞 ``_LEGAL_SEGMENT_RE``（字符集不含 $）＝bad_name。

    两码皆拒、纵深成立；保留名账仍在 ``_is_reserved_device_name`` 一侧兜住
    media_archive 那条不经字符集的腿（③格）。本锁钉「现状」：若哪天字符集
    放宽收 ``$``，这格必须同步改判 reserved_name——改判要有意识，不许静默。
    """
    with pytest.raises(rr._Rejected) as exc:
        rr.sanitize_write_segments(ref)
    assert exc.value.code == rr.DenyCode.BAD_NAME


# ---------------------------------------------------------------------------
# ⑤ 单源结构锁：名册恰等于期望真值表；消费方禁第三副本
# ---------------------------------------------------------------------------


def test_roster_equals_expected_truth_table_exactly() -> None:
    """注毒自证靶：从表里摘一行 com1 ⇒ 本格与①格同时红。"""
    assert rr._RESERVED_WIN32_BASENAMES == _EXPECTED_RESERVED


def test_consumers_delegate_to_central_roster_without_second_copy() -> None:
    """media_archive 与 today_history 必须调中央判据、不自持设备名表。"""
    src_archive = re.search(
        r"def sanitize_dirname.*?(?=\ndef )",
        inspect.getsource(ma),
        re.DOTALL,
    )
    assert src_archive is not None
    body = src_archive.group(0)
    assert "_is_reserved_device_name" in body, "归档腿未接中央判据"
    # 消费侧可引用拒绝代号/异常名，但不许自持第二张设备名表或复刻点号切分。
    assert "_RESERVED_WIN32_BASENAMES" not in body, "归档腿复刻了第二本名册"
    assert 'split(".", 1)' not in body and "split('.', 1)" not in body
