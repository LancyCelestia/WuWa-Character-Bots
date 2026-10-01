r"""S-FILES-CONTAINER 容器穿透锁（需求 16(4)「必须在可控的容器内进行操作」做实）。

本件锁的是**受限写盘运行器**（``domains/files/sender/restricted_runner.py``）这一层
容器对七类穿透形态的执法：junction/符号链接、``..``、大小写、8.3 短名、
Win32 保留设备名、UNC、长路径前缀 ``\\?\``。与相邻测试件的分工：

- ``test_file_exchange_restricted_runner.py``：能力侧穿越样本表（``../``/盘符/``%2f``）
  与「一码一人话」登记锁——本件**不复制那张表**，只补它没有的 junction 真件腿、
  短名腿、保留名腿、大小写腿与 UNC/设备前缀腿。
- ``test_safety_exec_paths.py``：出站判定件（``paths.py``）自己的链接双腿——
  本件用**同一双腿哲学**（真件能造就造 + 模拟解析永远跑）测写侧咽喉，两件互不
  替代：paths 判「能不能外发」，runner 判「能不能落盘」。

三条教义级判据（每条都有注毒自证，摘守卫必红）：

1. containment 只对 ``resolve()`` 后的**段元组前缀**执法（``_is_within`` 按
   ``parts`` 比对且 casefold，不做字符串 ``startswith`` ⇒ 大小写与同族目录名
   ``root``/``root_evil`` 两格都结构性成立）；摘掉 ``_resolve`` 换纯词法归一，
   junction 立穿（``test_poison_lexical_resolve_lets_junction_write_through``）。
2. 段名字符集（``_LEGAL_SEGMENT_RE`` 不含 ``~`` 与 ``:``）结构性挡掉 8.3 短名段
   与 ADS 冒号后缀；根目录自身给短名形态由双侧 ``resolve()`` 折平
   （``test_short_name_root_form_still_contained``）。
3. Win32 保留设备名（nul/con/aux/com1… 一族，点号前首段、不区分大小写）在
   **段消毒这一格**就拒，写盘/寻址/回读/读-改-写四条腿同格生效——本机实测
   旧行为是 ``os.replace`` 能把 ``nul.txt`` 造进目录并回报成功（2026-09-26 探针），
   这类件用常规工具删不掉，容器不收挂件（摘守卫注毒＝本文件必红）。

离线纪律：全部落点在 ``tmp_path`` 与仓库外暂存位；真件只建 junction
（``mklink /J`` 无需特权，本机实证；``os.symlink`` 依旧 ``WinError 1314`` 拒——
符号链接腿由 junction 代证并如实记在报告里，不谎称已验）。
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr

# 本件所有产物共用的合法扩展名（.md 在缺省白名单里，纯文本指纹可过）。
_OK = b"container penetration probe\n"


def _policy(root: Path) -> rr.WritePolicy:
    return rr.WritePolicy(allowed_roots=(root,))


def _make_junction(link: Path, target: Path) -> bool:
    """尽力建目录 junction（不需要管理员）；三级退让，宿主全拒返回 False。"""
    try:
        import _winapi

        factory = getattr(_winapi, "CreateJunction", None)
        if callable(factory):
            factory(str(target), str(link))
            return True
    except (ImportError, OSError):
        pass
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0 and link.is_dir()
    except OSError:
        return False


def _drop_junction(link: Path) -> None:
    try:
        os.rmdir(link)  # junction 用 rmdir 摘除，绝不递归进目标。
    except OSError:
        shutil.rmtree(link, ignore_errors=True)


def _lex_resolve(value: Path) -> Path | None:
    """注毒形态：只做词法绝对化（折 ``..``），**不跟随**链接/junction。"""
    try:
        return Path(os.path.abspath(str(value)))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# ① 穿透形态矩阵：段消毒层就拒，目的地连临时件都不该出现
# ---------------------------------------------------------------------------

_SHAPE_MATRIX: list[tuple[str, set[str]]] = [
    # ``..`` 族（与能力侧样本表不重叠的补格：混合分隔符与中段点串）
    ("notes/../../up.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("..\\up.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("a/.../b.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    # 绝对写法与 UNC / 设备命名空间 / 长路径前缀
    ("/etc/hosts.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("//server/share/x.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("\\\\server\\share\\x.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("\\\\?\\C:\\Windows\\x.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("\\\\.\\PhysicalDrive0", {rr.DenyCode.TRAVERSAL_DENIED}),
    # 盘符（含驱动器相对形态）与 ADS 冒号后缀
    ("C:/Windows/win.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("C:relative.md", {rr.DenyCode.TRAVERSAL_DENIED}),
    ("doc.md:secret", {rr.DenyCode.TRAVERSAL_DENIED}),
    # 8.3 短名段（``~`` 不在段字符集内，走 BAD_NAME 格）
    ("FCPROB~1/x.md", {rr.DenyCode.BAD_NAME}),
    ("PROGRA~1\\evil.md", {rr.DenyCode.BAD_NAME}),
]


@pytest.mark.parametrize(("ref", "expected"), _SHAPE_MATRIX)
def test_penetration_shapes_are_denied_before_touching_disk(
    tmp_path: Path, ref: str, expected: set[str]
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outcome = rr.create_bytes(
        ref, _OK, policy=_policy(root), staging_dir=tmp_path / "_stg"
    )
    assert isinstance(outcome, rr.WriteOutcome)
    assert outcome.ok is False
    assert outcome.reason_code in expected, (ref, outcome.reason_code)
    assert list(root.iterdir()) == [], "被拒形态不许在目的地留下任何残件"
    assert not (tmp_path.parent / "up.md").exists()


# ---------------------------------------------------------------------------
# ② junction：真件腿 + 模拟解析腿 + 摘守卫注毒腿（三腿各司其职）
# ---------------------------------------------------------------------------


def _fake_following_links(outside: Path) -> Callable[[Path], Path | None]:
    """模拟「OS 把 junction 折到根外」的解析器：含 ``jn`` 段 ⇒ 映射到 outside。"""

    def _fake(value: Path) -> Path | None:
        parts = [str(part) for part in Path(str(value)).parts]
        if "jn" in parts:
            index = parts.index("jn")
            tail = parts[index + 1 :]
            return outside.joinpath(*tail) if tail else outside
        try:
            return Path(str(value)).resolve()
        except OSError:
            return None

    return _fake


def test_junction_escaping_root_is_denied_resolved_leg_always_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模拟解析腿（不依赖宿主权限、永远跑）：containment 吃到解析后的根外落点 ⇒ 拒。"""
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"TOPSECRET")
    original = rr._resolve
    monkeypatch.setattr(rr, "_resolve", _fake_following_links(outside))
    outcome = rr.create_bytes(
        "jn/evil.md", _OK, policy=_policy(root), staging_dir=tmp_path / "_stg"
    )
    assert outcome.ok is False
    assert outcome.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
    located = rr.resolve_existing("jn/secret.txt", policy=_policy(root))
    assert isinstance(located, rr.WriteOutcome)
    assert located.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
    read_back = rr.read_confined_bytes("jn/secret.txt", policy=_policy(root))
    assert isinstance(read_back, rr.WriteOutcome)
    assert read_back.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
    monkeypatch.undo()
    assert rr._resolve is original
    assert not (outside / "evil.md").exists()


def test_junction_real_artifact_denied_and_poison_flips_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真件腿：普通进程可建的目录 junction 外指 ⇒ 三腿全拒；摘掉 resolve 同一发必穿。

    这一枚就是 S-FILES-LAND §陆-2 拿不到的「containment 腿检测力证据」：
    ``os.symlink`` 在本机被 ``WinError 1314`` 拒（前席与本轮探针两度实测一致），
    而 junction 无需特权可建且 ``Path.resolve()`` 同样折平它，判据走的是同一格。
    宿主连 junction 都拒建时本用例显式 skip（登记未证），**不放行成绿**。
    """
    root = tmp_path / "vault"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"TOPSECRET")
    link = root / "jn"
    made = _make_junction(link, outside)
    if not made:
        pytest.skip("宿主拒绝建 junction——真件注毒腿本机不可证（模拟腿永远跑，见上）")
    try:
        policy = _policy(root)
        outcome = rr.create_bytes("jn/evil.md", _OK, policy=policy, staging_dir=tmp_path / "_stg")
        assert outcome.ok is False
        assert outcome.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
        for leg in (
            lambda: rr.resolve_existing("jn/secret.txt", policy=policy),
            lambda: rr.read_confined_bytes("jn/secret.txt", policy=policy),
            lambda: rr.revise_in_place(
                "jn/secret.txt", lambda _b: b"tampered", policy=policy, staging_dir=tmp_path / "_stg"
            ),
        ):
            verdict = leg()
            assert isinstance(verdict, rr.WriteOutcome)
            assert verdict.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
        assert (outside / "secret.txt").read_bytes() == b"TOPSECRET"
        assert not (outside / "evil.md").exists()

        # ——注毒：词法归一顶掉 resolve ⇒ 同一发输入必须穿（否则上面那枚断言是空锁）——
        monkeypatch.setattr(rr, "_resolve", _lex_resolve)
        try:
            leaked = rr.create_bytes(
                "jn/evil.md", _OK, policy=policy, staging_dir=tmp_path / "_stg"
            )
            assert leaked.ok is True, (
                f"摘除 resolve 后仍被拒（{leaked.reason_code}）⇒ 防穿透另有他人，"
                "本锁判据归属要重查，不许静默当绿"
            )
            assert (outside / "evil.md").read_bytes() == _OK, "注毒必须真的写穿到根外"
            (outside / "evil.md").unlink(missing_ok=True)
        finally:
            monkeypatch.undo()
        assert rr._resolve.__name__ == "_resolve"
        again = rr.create_bytes("jn/evil.md", _OK, policy=policy, staging_dir=tmp_path / "_stg")
        assert again.ok is False
        assert again.reason_code == rr.DenyCode.OUTSIDE_WHITELIST
        assert not (outside / "evil.md").exists()
    finally:
        _drop_junction(link)
        assert outside.exists(), "摘 junction 不许伤到指向的真实目录"
        assert (outside / "secret.txt").read_bytes() == b"TOPSECRET"


# ---------------------------------------------------------------------------
# ③ 大小写与同族目录名：parts 元组前缀（不是字符串 startswith）
# ---------------------------------------------------------------------------


def test_containment_is_parts_prefix_not_string_prefix(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    resolved = root.resolve()
    # 同族前缀目录：字符串 startswith 会把它吞进「根内」，parts 比对不会。
    sibling = resolved.parent / (resolved.name + "_evil")
    assert rr._is_within(sibling, resolved) is False
    assert rr._is_within(sibling / "x.md", resolved) is False
    # 大小写两式在段元组 casefold 下互认（Windows 大小写不敏感的正面格）。
    assert rr._is_within(Path(str(resolved).upper()), resolved) is True
    assert rr._is_within(resolved / "SUB" / "Doc.MD", resolved) is True


def test_case_alias_never_becomes_a_second_file(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    policy = _policy(root)
    first = rr.create_bytes("Doc.md", _OK, policy=policy, staging_dir=tmp_path / "_stg")
    assert first.ok is True
    twin = rr.create_bytes("doc.md", b"x", policy=policy, staging_dir=tmp_path / "_stg")
    assert twin.ok is False
    assert twin.reason_code == rr.DenyCode.ALREADY_EXISTS
    assert sorted(p.name for p in root.iterdir()) == ["Doc.md"]


# ---------------------------------------------------------------------------
# ④ 8.3 短名：根给短形照样containment（双侧 resolve），段给短形被字符集挡
# ---------------------------------------------------------------------------


def test_short_name_root_form_still_contained(tmp_path: Path) -> None:
    root = tmp_path / "vault-dir"
    root.mkdir()
    buf = ctypes.create_unicode_buffer(260)
    got = ctypes.windll.kernel32.GetShortPathNameW(str(root.resolve()), buf, 260)
    short = buf.value if got else ""
    policy = rr.WritePolicy(allowed_roots=(Path(short or str(root)),))
    outcome = rr.create_bytes("note.md", _OK, policy=policy, staging_dir=tmp_path / "_stg")
    assert outcome.ok is True, outcome.error_message()
    landed = root.resolve() / "note.md"
    assert outcome.path == landed
    assert landed.read_bytes() == _OK
    if short and short != str(root.resolve()):
        # 本机实证格：短名根经 resolve 折平成长名——这条断言就是「startswith 型
        # 字符串守卫会在这一格静默失效、而件内守卫不过字符串」的现体证据。
        assert str(outcome.path) != str(Path(short) / "note.md")
    # 段名形态的短名（``~``）永远进不来——矩阵格在这里再点一次名，
    # 因为它是**另一格**判据（字符集），不是 resolve 折平。
    blocked = rr.create_bytes("V AUL~1/x.md", _OK, policy=policy, staging_dir=tmp_path / "_stg")
    assert blocked.ok is False
    assert blocked.reason_code == rr.DenyCode.BAD_NAME


# ---------------------------------------------------------------------------
# ⑤ Win32 保留设备名：写/寻址/回读/改写四腿同格拒 + 摘守卫注毒
# ---------------------------------------------------------------------------

_RESERVED_REFS = [
    "nul",
    "nul.md",
    "nUl.TxT",
    "con.md",
    "COM1.txt",
    "com9.md",
    "aux.md",
    "prn.txt",
    "lpt1.md",
    "lpt9.txt",
    "nul.tar.gz",
    "sub/nul.md",
    "docs/con.md",
]


@pytest.mark.parametrize("ref", _RESERVED_REFS)
def test_reserved_device_names_denied_on_every_leg(tmp_path: Path, ref: str) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    policy = _policy(root)
    staging = tmp_path / "_stg"
    create = rr.create_bytes(ref, _OK, policy=policy, staging_dir=staging)
    assert create.ok is False
    assert create.reason_code == rr.DenyCode.RESERVED_NAME
    located = rr.resolve_existing(ref, policy=policy)
    assert isinstance(located, rr.WriteOutcome)
    assert located.reason_code == rr.DenyCode.RESERVED_NAME
    read_back = rr.read_confined_bytes(ref, policy=policy)
    assert isinstance(read_back, rr.WriteOutcome)
    assert read_back.reason_code == rr.DenyCode.RESERVED_NAME
    revised = rr.revise_in_place(ref, lambda _b: b"zz", policy=policy, staging_dir=staging)
    assert revised.reason_code == rr.DenyCode.RESERVED_NAME
    doc = rr.write_document(ref, _OK, policy=policy, staging_dir=staging)
    assert doc.reason_code == rr.DenyCode.RESERVED_NAME
    assert list(root.iterdir()) == [], "被拒形态不许在目的地留下任何残件"


def test_reserved_name_judgment_is_head_before_first_dot() -> None:
    """判据是「点号前首段、casefold」——换扩展名/换大小写不构成第二格绕行面。"""
    assert rr._is_reserved_device_name("nul") is True
    assert rr._is_reserved_device_name("NuL.md") is True
    assert rr._is_reserved_device_name("aux.tar.gz") is True
    assert rr._is_reserved_device_name("com1") is True
    assert rr._is_reserved_device_name("COM9.txt") is True
    assert rr._is_reserved_device_name("lpt0.md") is True  # 2026-09-27 F-G2：LPT0 亦保留（旧注释「设备号从 1 起」经现算证伪）
    assert rr._is_reserved_device_name("com10.md") is False  # 不是 com1+"0"
    assert rr._is_reserved_device_name("concise.md") is False  # 首段整词比对非前缀
    assert rr._is_reserved_device_name("null-point.md") is False
    assert rr._is_reserved_device_name("notes.md") is False


def test_poison_reserved_name_guard_opens_the_device_name_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒：摘掉保留名判据 ⇒ 段消毒放行、``nul.md`` 走回「回报成功」的旧形态。

    本机实证（2026-09-26 S-FILES-CONTAINER 探针）：旧行为下 ``os.replace`` 能把
    ``nul.md`` 造进目录、``create_bytes`` 返回 ok=True 并烧一格日配额——摘守卫后
    至少要求**拒绝代号不再是 reserved_name**（别的机器若 OS 层自己拒，会以
    io_error 之类出现，那正说明本锁补的是 OS 不管的那格）。还原后必须回拒。
    """
    with pytest.raises(rr._Rejected) as armed:
        rr.sanitize_write_segments("nul.md")
    assert armed.value.code == rr.DenyCode.RESERVED_NAME

    monkeypatch.setattr(rr, "_is_reserved_device_name", lambda _segment: False)
    try:
        segments = rr.sanitize_write_segments("nul.md")
        assert segments == ("nul.md",), "摘守卫后段消毒必须放行该形态（否则本锁是空锁）"
        root = tmp_path / "vault"
        root.mkdir()
        outcome = rr.create_bytes(
            "nul.md", _OK, policy=_policy(root), staging_dir=tmp_path / "_stg"
        )
        assert outcome.reason_code != rr.DenyCode.RESERVED_NAME
    finally:
        monkeypatch.undo()
    with pytest.raises(rr._Rejected) as rearmed:
        rr.sanitize_write_segments("nul.md")
    assert rearmed.value.code == rr.DenyCode.RESERVED_NAME


# ---------------------------------------------------------------------------
# ⑥ 登记面：新代号有句子、句子无路径形态
# ---------------------------------------------------------------------------


def test_reserved_name_code_is_registered_with_plain_text() -> None:
    assert rr.DenyCode.RESERVED_NAME in rr.DENY_CODES
    text = rr.DENY_PLAIN_TEXT[rr.DenyCode.RESERVED_NAME]
    assert "保留设备名" in text
    assert "nul" in text
    assert ":" not in text and "\\" not in text, "人话句里不带路径形态与盘符形态"
    assert rr.plain_reason(rr.DenyCode.RESERVED_NAME) == text
