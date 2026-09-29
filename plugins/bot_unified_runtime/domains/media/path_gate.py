"""媒体读图路的**容器门唯一真身**（席 PIC，2026-09-29，需求 15 + 容器逃逸根治）。

一句话：任何「去磁盘上取一张图」的请求，先把路径**折算**（``resolve``）再问一句
「还在登记的这几根里吗」。判据只有这一处；随机图（登记图库根）与表情库（贴纸容器）
两侧各自抄一把尺会漂成两说——这正是本仓「禁第二真身」点名的形态。

为什么必须折算、词法归一不够（2026-09-29 本机取证）：登记目录里放一枚 junction
指向别处时，``os.walk`` 会照进（Windows 下 junction 的 ``os.path.islink`` 为**假**，
只有 ``st_file_attributes`` 的 ``FILE_ATTRIBUTE_REPARSE_POINT`` 认得它），于是私人相册
整个被吸进候选清单；``os.path.normpath`` 那侧判它「还在根里」，``resolve()`` 之后
真身在外面。拦得住的只有折算，所以本件的包含判定永远对**折算后**的段元组执法。

八格形态逐条（简报点名的清单，一格一条锁在 ``tests/test_media_path_gate.py``）：

===========  ================================
形态          处置
===========  ================================
``..`` 上跳    折算后按段元组前缀判，天然出局
绝对路径在外    同上
符号链接/junction  折算 ⇒ ``outside_root``；扫描侧另有 :func:`reparse_point` 不进树
UNC           容器是本机盘时前缀必不相交 ⇒ 拒；用户**自己登记**的 UNC 根照读
盘符/相对驱动器  折算锚到当前驱动器后再判；``C:`` 这类非法段名单独拦
8.3 短名       ``resolve()`` 走 ``GetFinalPathNameByHandle`` 折回长名 ⇒ 不误伤真件
大小写         段元组 ``casefold`` 后比对（Windows 不区分，Linux 区分的是真两个名字）
URL 编码       ``%2e%2e%2f`` 这类解出分隔符/``..`` 的直接拒：贴纸名里不该有它
NFC/NFD        两侧统一 NFC 再比对（``café`` 这类目录名不许被整库判越界）
===========  ================================

另两格顺带拦掉（``domains/files/sender/restricted_runner.py`` 同族口径，读写两侧
不许一把尺松一把尺紧）：Win32 保留设备名（``nul``/``con``/``com1``…）、``\\?\\`` 与
``\\.\\`` 设备前缀（Win32 命名空间里 **不做** 词法归一，``\\?\\C:\\..\\`` 能绕过一切
字符串检查）、段内 NUL 与冒号。

**异常文本只带代号、不带路径**：越界面是「这条记录想让 bot 去容器外面读/删文件」，
把完整路径原文塞进异常，就等于让一次拒绝变成新的泄露面（``redact_local_secrets``
是出站兜底，不是本件免检的理由）。
"""

from __future__ import annotations

import os
import re
import stat as _stat
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import unquote

__all__ = [
    "PathEscapeError",
    "contain_within",
    "is_within_registered",
    "reparse_point",
    "resolve_roots",
]

#: Win32 重解析点属性位（目录 junction、过滤程序、符号链接都带这一位）。
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400

#: Win32 保留设备名：点号前首段命中即拒（``nulls.png``/``compete.png`` 这类真名不伤）。
_RESERVED_RE = re.compile(r"^(?:con|prn|aux|nul|com[0-9]+|lpt[0-9]+)(?:\.|$)", re.IGNORECASE)

#: 折算前就能判掉的设备前缀：``\\?\`` 与 ``\\.\``（含 POSIX 斜杠写法）。
_DEVICE_PREFIXES = ("\\\\?\\", "\\\\.", "//?/", "//./", "\\??\\")

_EMPTY_CODE = "empty_value"
_NUL_CODE = "illegal_segment"
_DRIVE_CODE = "illegal_segment"
_RESERVED_CODE = "reserved_device_name"
_DEVICE_CODE = "device_namespace_prefix"
_ENCODED_CODE = "encoded_traversal"
_OUTSIDE_CODE = "outside_root"
_ROOT_CODE = "root_is_not_a_file"
_UNRESOLVED_CODE = "unresolvable"


class PathEscapeError(ValueError):
    """路径折算后落在登记根之外（或形态本身不许读）。

    只携带**代号**：调用侧按代号分账（哪本账、哪句人话），审计按代号 grep。
    刻意不继承 ``OSError``——这不是「文件不见了」，而是「这条记录想去外面做事」，
    两件事必须能被分开记账，悄悄退回容器内的替身路径等于把洞换个形状留下。
    """

    def __init__(self, code: str) -> None:
        self.code = str(code or _UNRESOLVED_CODE)
        super().__init__(f"media path refused by container gate code={self.code}")


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text))


def _fold(text: str) -> str:
    """比对用形态：NFC + casefold（Windows 大小写不敏感，两形同判）。"""
    return _nfc(text).casefold()


def _segment_form(value: str) -> str:
    """段名 → 比对形态（``C:\\`` 这类锚点也走这里，故不做任何路径解析）。"""
    return _fold(value)


def _parts(path: Path) -> tuple[str, ...]:
    return tuple(_segment_form(part) for part in Path(_nfc(str(path))).parts)


def _is_encoded_traversal(raw: str) -> bool:
    """URL 编码的穿越形态（``%2e%2e%2f``、``%2f..%2f``）：解出来含分隔符或 ``..`` 即拒。

    ``%`` 在 Windows 文件名里合法，所以「带 %」本身不是罪；判的是**解码后变成路径分隔
    符**——那种形态出现在读图请求里，只可能是想穿过容器，不可能是用户真实的贴纸文件名。
    """
    if "%" not in raw:
        return False
    decoded = unquote(unquote(raw))  # 两趟：套一层 %25xx 编码也算。
    lowered = decoded.lower().replace("\\", "/")
    return "/" in lowered or ".." in lowered


def _lexical_guard(raw: str | Path) -> str:
    """折算**之前**的形态检查：这些判据与真身无关，越早拦越省一次 IO。

    ``raw`` 收 ``str | Path`` 只放宽**签名精度**，六道工序一道不减：空串 / NUL /
    设备前缀 / URL 编码穿越 / 冒号 ADS / 保留名，判据本体不变。函数体第一句本就是
    ``text = str(raw).strip()``，两种入参在这一句后折成同一个 ``text``，其后逐字节
    同路；与 :func:`_anchor`（早已收 ``str | Path``）口径对齐。上游 :func:`contain_within`
    的形参本就是 ``str | Path``，把守卫单独钉成 ``str`` 会在 ``Path`` 形态上留出一条
    「判定走一套、执行走另一套」的空档——容器门不许有这种两说。
    """
    text = str(raw).strip()
    if not text:
        return _EMPTY_CODE
    if "\x00" in text:
        return _NUL_CODE
    if text.startswith(_DEVICE_PREFIXES):
        return _DEVICE_CODE
    if _is_encoded_traversal(text):
        return _ENCODED_CODE
    for segment in Path(_nfc(text)).parts:
        clean = segment.rstrip(".")  # Win32 会剥掉尾点，判形要跟着剥
        if ":" in clean and not clean.lower().endswith(":\\"):
            # 驱动器锚点（``C:\\``）之外不许任何段带冒号：ADS（``a.png::$DATA``）
            # 与「相对驱动器」形态（``C:Windows/win.ini``）都在这格出局。
            return _DRIVE_CODE
        if _RESERVED_RE.match(clean):
            return _RESERVED_CODE
    return ""


def _anchor(raw: str | Path, base: Path) -> Path:
    path = Path(_nfc(str(raw).strip())).expanduser()
    if path.is_absolute():
        return path
    return base / path


def _resolve_quietly(path: Path) -> Path | None:
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def resolve_roots(roots: Iterable[str | Path]) -> list[Path]:
    """登记根 → 折算后的真身列表（符号链接/junction 折平，后续比对都用这形态）。"""
    out: list[Path] = []
    for raw in roots or ():
        text = str(raw).strip()
        if not text:
            continue
        resolved = _resolve_quietly(_anchor(text, Path.cwd()))
        if resolved is None:
            continue
        folded = resolved
        if folded not in out:
            out.append(folded)
    return out


def _within(child: tuple[str, ...], root: tuple[str, ...]) -> bool:
    """段元组前缀比对（不是字符串 ``startswith``）：同族目录名 ``root``/``root_evil`` 分得开。"""
    return bool(root) and child[: len(root)] == root


def contain_within(
    candidate: str | Path,
    roots: Sequence[str | Path],
    *,
    base: str | Path | None = None,
    allow_root: bool = False,
) -> Path:
    """容器门唯一判据：折算后必须仍在 ``roots`` 之一内，否则 :class:`PathEscapeError`。

    - ``base``：相对形态的锚点（表情库那种「旧库行按数据根解析」的老口径用它）；
      缺省按进程 CWD，与 :class:`pathlib.Path` 一致；
    - ``allow_root=False``：等于根本身也算越界——那是目录，``read_bytes()`` 会把
      别人的目录当图发，``unlink()`` 会炸；
    - 返回**折算后**的路径：调用侧拿它去做 IO，才不会出现「判定走 A、执行走 B」两说。
    """
    code = _lexical_guard(candidate)
    if code:
        raise PathEscapeError(code)
    resolved_roots = list(resolve_roots(roots))
    if not resolved_roots:
        # 没有可用登记根＝零来源。判「越界」而不是「放行」：拿不准时 fail-closed。
        raise PathEscapeError(_OUTSIDE_CODE)
    resolved = _resolve_quietly(_anchor(candidate, Path(base) if base is not None else Path.cwd()))
    if resolved is None:
        raise PathEscapeError(_UNRESOLVED_CODE)
    child = _parts(resolved)
    for root in resolved_roots:
        root_parts = _parts(root)
        if child == root_parts:
            if allow_root:
                return resolved
            raise PathEscapeError(_ROOT_CODE)
        if _within(child, root_parts):
            return resolved
    raise PathEscapeError(_OUTSIDE_CODE)


def is_within_registered(candidate: str | Path, roots: Sequence[str | Path]) -> bool:
    """不抛异常版（判定面语义与 :func:`contain_within` 逐字节相同，包括「根不算」）。"""
    try:
        contain_within(candidate, roots)
    except PathEscapeError:
        return False
    return bool(str(candidate).strip())


def reparse_point(path: str | Path) -> bool:
    """这条路径自己是不是重解析点（junction / 符号链接 / 过滤程序）。

    扫描侧用它**不进树**（一目录一次 ``lstat``，比逐文件 resolve 便宜得多）：
    Windows 下 ``os.path.islink`` 对 junction 返回假，照它剪枝等于没剪——本件的存在
    理由就是这一格。POSIX 侧退回 ``S_ISLNK``。
    """
    try:
        info = os.lstat(str(path))
    except OSError:
        return False
    if sys.platform == "win32":
        return bool(getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)
    return _stat.S_ISLNK(info.st_mode)
