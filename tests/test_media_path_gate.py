"""容器门唯一真身 ``domains/media/path_gate.py`` 的行为锁（席 PIC，需求 15 + 容器逃逸）。

判据来源＝本席简报第 1 条「路径必须解析后校验仍在登记根内（含符号链接/junction、
``..``、UNC、盘符、短路径 8.3、大小写、URL 编码、NFC/NFD），越界一律拒且告警可审计
（不泄露完整路径给用户）」。两条读图路各自持尺会漂成两说（表情库 ``confine_media_path``
与随机图登记根此前各判各的），故判据只住这一件文件，两侧都从这里取。

三格分工：
① **放行面**（修洞不许修没功能）：容器内绝对/旧相对口径/大小写/8.3 短名/NFC↔NFD
   同一枚真件必须照旧解析成功——否则现网图库会被整库判越界（那是第二次事故）；
② **拒绝面**（攻击样例）：``..`` 上跳、容器外绝对、真 junction、UNC、``\\\\?\\``/``\\\\.\\``
   设备前缀、Win32 保留名、NUL 字节、URL 编码的 ``..%2f``；每条都断言「拒绝原因是代号」
   且**异常文本里没有完整路径**（出站打码之外的第二道：根本不带出去）；
③ **牙齿**：同一枚 junction 夹具用「纯词法归一」复刻一遍必须**判它能穿过去**——
   证明 ② 里那条拒绝是真拦下了逃逸，不是夹具本身没造出来。

离线纪律：全部夹具落在 ``tmp_path``；junction 用 ``mklink /J``（无需特权，本机实证），
造不出来时如实 skip 该单格并注明，绝不谎称已验。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.media import path_gate

PNG_HEAD = b"\x89PNG\r\n\x1a\n"


def _file(path: Path, *, tail: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PNG_HEAD + tail.encode())
    return path


def _junction(link: Path, target: Path) -> bool:
    """造一个目录 junction（无需管理员）。成功 True、平台不支持 False。"""
    if sys.platform != "win32":
        return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,  # 调用方按 returncode 自行降级（平台不支持＝跳过，不抛）
    )
    return completed.returncode == 0 and link.exists()


@pytest.fixture()
def arena(tmp_path: Path) -> dict[str, Path]:
    container = tmp_path / "data" / "meme_library"
    inside = _file(container / "a.png", tail="inside")
    private = _file(tmp_path / "someone-else" / "private.png", tail="private")
    return {
        "tmp": tmp_path,
        "container": container,
        "inside": inside,
        "private": private,
    }


# ---------------------------------------------------------------- ① 放行面


def test_in_container_absolute_and_legacy_relative_still_pass(arena) -> None:
    root = arena["container"]
    inside = arena["inside"]
    assert path_gate.contain_within(inside, [root]) == inside.resolve()
    relative = str(inside.relative_to(root))
    assert path_gate.contain_within(relative, [root], base=root) == inside.resolve()


def test_case_and_short_name_forms_are_not_false_rejections(arena) -> None:
    """大小写与 8.3 短名都会被 Windows 折叠到同一枚真件 ⇒ 必须照旧放行。"""
    root = arena["container"]
    inside = arena["inside"]
    assert path_gate.contain_within(str(inside).upper(), [root]) is not None
    if sys.platform != "win32":
        pytest.skip("短名面只在 Windows 存在")
    import ctypes

    buf = ctypes.create_unicode_buffer(300)
    ctypes.windll.kernel32.GetShortPathNameW(str(inside), buf, 300)
    short = buf.value
    if not short or "~" not in short:
        pytest.skip("本机未启用 8.3 短名，该格无从取证")
    assert path_gate.contain_within(short, [root]) == inside.resolve()


def test_nfc_and_nfd_forms_of_the_same_root_agree(arena) -> None:
    """容器名带变音符时，NFC/NFD 两形必须同判（NTFS 上两形是两个名字，但**登记根**
    与**候选**只要规范化后同源就该认，否则现网 ``caf\\u00e9`` 这类目录名会被整库判越界）。"""
    base = arena["tmp"] / "caf\u00e9" / "library"
    real = _file(base / "a.png", tail="nfc")
    nfd_form = unicodedata.normalize("NFD", str(real))
    assert nfd_form != str(real)
    roots_nfc = [unicodedata.normalize("NFC", str(base))]
    assert path_gate.contain_within(nfd_form, roots_nfc) is not None
    assert path_gate.contain_within(str(real), [unicodedata.normalize("NFD", str(base))]) is not None


# ---------------------------------------------------------------- ② 拒绝面

ATTACKS = [
    ("outside-absolute", lambda a: str(a["private"])),
    ("dotdot-up", lambda a: str(a["container"] / ".." / ".." / "outside.png")),
    ("dotdot-inside-string", lambda a: f"{a['container']}/../../someone-else/private.png"),
    ("root-itself", lambda a: str(a["container"])),
    ("win-drive", lambda a: "C:/Windows/win.ini"),
    ("posix-absolute", lambda a: "/etc/passwd"),
    ("unc", lambda a: r"\\localhost\c$\Windows\win.ini"),
    ("device-prefix", lambda a: r"\\?\C:\Windows\win.ini"),
    ("device-dot", lambda a: r"\\.\PhysicalDrive0"),
    ("drive-relative", lambda a: "C:Windows\\win.ini"),
    ("percent-encoded-traversal", lambda a: f"{a['container']}/%2e%2e%2f%2e%2e%2fprivate.png"),
    ("percent-encoded-separator", lambda a: f"{a['container']}/%2f..%2fprivate.png"),
    ("nul-segment", lambda a: str(a["container"] / "nul.png")),
    ("reserved-com1", lambda a: str(a["container"] / "COM10.png")),
    ("embedded-nul", lambda a: str(a["container"] / "a.png") + "\x00"),
    ("empty", lambda a: ""),
    ("bare-dotdot", lambda a: ".."),
    ("own-source-file", lambda a: str(Path(__file__).resolve())),
]

@pytest.mark.parametrize("name", [case[0] for case in ATTACKS])
def test_escaping_forms_are_rejected_with_a_reason_code(arena, name: str) -> None:
    value = dict(ATTACKS)[name](arena)
    with pytest.raises(path_gate.PathEscapeError) as caught:
        path_gate.contain_within(value, [arena["container"]])
    error = caught.value
    assert error.code, "拒绝必须带代号（静默＝把逃逸藏成「这张图没了」）"
    assert str(arena["tmp"]) not in str(error), "异常文本不许把用户目录带出去"
    assert "private.png" not in str(error), "异常文本不许把被盯上的文件名带出去"


def test_reserved_name_rejections_do_not_break_ordinary_names(arena) -> None:
    """保留名只认「点号前首段」，``nulls.png``/``compete.png`` 这类真名不许误伤。"""
    good = _file(arena["container"] / "nulls.png", tail="ok")
    assert path_gate.contain_within(str(good), [arena["container"]]) is not None


@pytest.mark.skipif(sys.platform != "win32", reason="junction 只在 Windows 存在")
def test_real_junction_out_of_the_root_is_rejected(arena) -> None:
    """登记根里放一枚 junction 指向别处 ⇒ 折出的真身在外面 ⇒ 必须拒。"""
    link = arena["container"] / "link"
    if not _junction(link, arena["tmp"] / "someone-else"):
        pytest.skip("本机建不出 junction（未验，不谎称已拦）")
    escaped = link / "private.png"
    with pytest.raises(path_gate.PathEscapeError) as caught:
        path_gate.contain_within(str(escaped), [arena["container"]])
    assert caught.value.code == "outside_root"


@pytest.mark.skipif(sys.platform != "win32", reason="junction 只在 Windows 存在")
def test_lexical_only_normalisation_would_have_let_the_junction_through(arena) -> None:
    """③ 牙齿：同一枚夹具用纯词法归一（``os.path.normpath``）判包含 ⇒ **必须判它能穿**。

    这一格证的不是门，是「洞真的存在」：没有 resolve() 的折叠，junction 里的私人文件
    在词法上仍在登记根内，任何只比字符串前缀的尺都拦不住它。
    """
    link = arena["container"] / "lexonly"
    if not _junction(link, arena["tmp"] / "someone-else"):
        pytest.skip("本机建不出 junction")
    lexical = os.path.normpath(str(link / "private.png"))
    root = os.path.normpath(str(arena["container"]))
    assert lexical.lower().startswith(root.lower()), "夹具没造出可穿形态 ⇒ 上一条拒绝是空跑"
    assert os.path.exists(lexical), "junction 指向的真件不在 ⇒ 牙齿没牙"
    with pytest.raises(path_gate.PathEscapeError):
        path_gate.contain_within(str(link / "private.png"), [arena["container"]])


# ---------------------------------------------------------------- 判定面只许一处


def test_single_containment_judgement_site() -> None:
    """容器判据在媒体层只住 ``path_gate.py``；随机图那侧只准转调、不准持尺。

    （表情库 ``confine_media_path`` 那侧的收编写在 ``patch-PIC.md``，不在本格：
    2026-09-29 00:52 该文件正被别席改写（``review_state`` 在制品），本席不抢面。）
    """
    repo = Path(__file__).resolve().parents[1]
    gate_text = (
        repo / "plugins/bot_unified_runtime/domains/media/path_gate.py"
    ).read_text(encoding="utf-8")
    assert gate_text.count("def contain_within") == 1, "容器门出现第二份定义"

    randpic_text = (
        repo / "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py"
    ).read_text(encoding="utf-8")
    assert "is_relative_to" not in randpic_text, "随机图自己留了第二把尺 ⇒ 与登记根判据会判两说"
    assert "path_gate.contain_within" in randpic_text, "随机图的登记根门没接到唯一真身"
