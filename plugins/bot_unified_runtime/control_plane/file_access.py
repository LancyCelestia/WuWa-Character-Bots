"""受控文件读取与代码文件网关。

F-3 收编（SEAT-FIX-ATK-CP，2026-09-28）：本网关曾是零消费者死码（SEAT-ATK-CP F-3）。
F-1 根修时按「改中央入口禁建旁支」口径把它**正式收编**为控制面
``POST /api/v1/files/read``（``api/platform.py``）的唯一读取实现体——路径成员判定、
敏感子树/后缀 denylist、绝对路径拒等守卫全部只在本文件执法一次，HTTP 层不再
自存第二套判据。收编前的「HTTP 面不得 import file_access」出册锁随之失效，由
``tests/test_control_plane_files_read_scope.py`` 的活性锁接替（锁「必须走网关、
且 api 层不得复刻判定」）。

判据纪律（既有在册教训）：路径成员一律**两侧 ``resolve()`` 后按段判成员**
（``root in candidate.parents``），绝不用 ``startswith``——本机 Windows 8.3 短名
会让字符串前缀比较静默失效；`..` 穿越也在 resolve 后现形。守卫排在任何
stat/读取之前，命中 denylist 即拒且拒绝原因可归因（错误码区分作用域/禁区/格式）。

F-01 扩口（SEAT-FIX-WEBUIMA，2026-09-27 攻击者复查修复批）：``media/analyze``
曾把三源里的本机路径原样直喂 ingest 真身（转写/描述文本回显＝任意本机媒体读
旁路，SEAT-ATK-WEBUI F-01）。修法走同一中央件：新增 ``admit_media_source`` 口，
成员判定/禁区与 ``authorize`` 同族（两侧 resolve 后按段判成员、禁 startswith），
只把后缀许可集换成媒体容器集并增加 file:// 归一腿——守卫真身仍恰好一处，
HTTP 层只折叠回执码、不自存判据。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ALLOWED = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".tex",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cc",
    ".cxx",
    ".cs",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
}

#: 敏感子树 denylist（相对进程 cwd）：即便落在登记根之内也一律拒读并归因。
#: 这些树里住的是运行时数据/日志/依赖树，不属于「产物/素材」读取面（F-1 修法）。
SENSITIVE_SUBTREES: tuple[str, ...] = ("data", "logs", "webui/node_modules")

#: 敏感后缀 denylist（小写）：日志类后缀即便在登记根内也不从 HTTP 面出口。
SENSITIVE_SUFFIXES: frozenset[str] = frozenset({".log"})

#: 敏感文件名前缀（小写比较）：.env / .env.local 等配置秘密——此前"读不到"纯属
#: pathlib 点后缀为空名的运气，现在改为设计判据（F-1：运气不收编，判据在册）。
SENSITIVE_NAME_PREFIXES: tuple[str, ...] = (".env",)

#: 媒体腿容器后缀许可集（F-01）：只收 ingest 真身（vision_describe / transcribe）
#: 实际会解码的族——图＝``_SUFFIX_MIME`` 键 + gif；音视频＝管线常遇的 ffmpeg 容器。
#: 集外后缀在媒体面一律拒（最小收口：读文档是 /files/read 的语义，媒体腿不代读）。
MEDIA_ALLOWED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".gif",
        ".mp3",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".opus",
        ".flac",
        ".amr",
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".flv",
    }
)


class FileGatewayError(Exception):
    pass


def _media_local_candidate(text: str) -> Path | None:
    """file:// URI / 裸路径 → 未定性的 ``Path``；其余 scheme 返回 None（拒收）。

    形态归一与 ingest 真身 ``_local_path_from_value`` 同形（file:// 百分号解码 +
    Windows 盘符前斜杠剥离），但**不做 is_file**——存在性判定排在成员/禁区
    判定之后，否则"先 stat 再判根"本身就成了回执时序上的预言机。
    """
    if text[:5].lower() == "file:":
        parsed = urlparse(text)
        path = unquote(parsed.path or "")
        if not path:
            return None
        candidate = Path(path)
        if candidate.drive == "" and re.match(r"^/[A-Za-z]:[/\\]", path):
            candidate = Path(path[1:])
        return candidate
    if "://" in text:
        return None
    return Path(text)


def parse_roots(raw: list[str] | str | None) -> tuple[Path, ...]:
    """把配置值（逗号分隔串或列表）解析成**已 resolve** 的读取根元组。

    空项/纯空白剔除；解析失败（异常类型/权限）一律回空表——调用方按
    「无根 ⇒ 端点 503 诚实拒绝」处理，绝不回落到 cwd 或任何隐式根。
    """
    if raw is None:
        return ()
    if isinstance(raw, str):
        entries = raw.split(",")
    else:
        try:
            entries = [str(item) for item in raw]
        except TypeError:
            return ()
    roots: list[Path] = []
    for entry in entries:
        text = entry.strip()
        if not text:
            continue
        try:
            roots.append(Path(text).expanduser().resolve())
        except (OSError, ValueError):
            continue
    return tuple(roots)


class FileReadGateway:
    def __init__(
        self,
        roots: tuple[str | Path, ...],
        max_bytes: int = 20 * 1024 * 1024,
        *,
        denied_subtrees: tuple[str, ...] = SENSITIVE_SUBTREES,
        denied_suffixes: frozenset[str] = SENSITIVE_SUFFIXES,
        denied_name_prefixes: tuple[str, ...] = SENSITIVE_NAME_PREFIXES,
    ) -> None:
        self.roots = tuple(Path(x).resolve() for x in roots)
        self.max_bytes = max_bytes
        # deny 子树以 cwd 为基准 resolve 一次；两侧都折成真实路径后再按段比对，
        # 短名/`..`/junction 都在 resolve 后现形（禁 startswith，见模块头纪律）。
        cwd = Path.cwd().resolve()
        self._denied_roots = tuple((cwd / sub).resolve() for sub in denied_subtrees)
        self._denied_suffixes = frozenset(s.lower() for s in denied_suffixes)
        self._denied_name_prefixes = tuple(p.lower() for p in denied_name_prefixes)

    def _denied(self, candidate: Path) -> bool:
        if candidate.suffix.lower() in self._denied_suffixes:
            return True
        name = candidate.name.lower()
        if any(name.startswith(prefix) for prefix in self._denied_name_prefixes):
            return True
        return any(
            candidate == denied or denied in candidate.parents
            for denied in self._denied_roots
        )

    def authorize(self, relative: str) -> tuple[Path, Path]:
        """守卫总入口：**任何 stat/读取之前**执行，返回 (候选文件, 命中的根)。

        错误码即归因（供 HTTP 层映射）：
        - ``absolute_path_forbidden`` 绝对路径直接拒；
        - ``path_not_allowed`` 不在登记根内（resolve 后按段判成员，非 startswith）；
        - ``denied_location`` 命中敏感子树/后缀/文件名禁区（即便在登记根内）；
        - ``format_not_supported`` 后缀不在放行集；
        - ``file_unavailable`` 不是文件、不存在或超限。
        """
        if not relative or Path(relative).is_absolute():
            raise FileGatewayError("absolute_path_forbidden")
        candidate = Path(relative).resolve()
        matched: Path | None = None
        for root in self.roots:
            if candidate == root or root in candidate.parents:
                matched = root
                break
        if matched is None:
            raise FileGatewayError("path_not_allowed")
        if self._denied(candidate):
            raise FileGatewayError("denied_location")
        if candidate.suffix.lower() not in ALLOWED:
            raise FileGatewayError("format_not_supported")
        if not candidate.is_file() or candidate.stat().st_size > self.max_bytes:
            raise FileGatewayError("file_unavailable")
        return candidate, matched

    def resolve(self, relative: str) -> Path:
        return self.authorize(relative)[0]

    def admit_media_source(self, value: str) -> Path | str:
        """媒体源准入闸（F-01）：``/api/v1/media/analyze`` 三腿的唯一守卫真身。

        分类：空串与 http(s)/data 形态**原串返回**——远程取物咽喉是 ingest 下游的
        ``check_download_url``（SEAT-ATK-WEBUI F-03 另票），本口不建第二颗咽喉，
        也不许把远程腿一起闸死（v21-risk4 契约位）。其余一切（绝对路径、相对
        路径、file:// URI、未知 scheme）按本地形态定性：过"登记根按段判成员 +
        敏感禁区 + 媒体容器后缀 + 在场/限额"四道后返回 resolve 后的真实路径，
        判据与 ``authorize`` 同族（两侧 resolve、禁 startswith、守卫先于 stat）。
        拒因内部可归因（单元面与日志用）；HTTP 层把全部本地拒因折叠成单一码，
        "存在但越界"与"不存在"回执同形——不留存在性探测通道。
        """
        text = str(value or "").strip()
        if not text:
            return text
        if text.lower().startswith(("http://", "https://", "data:")):
            return text
        candidate = _media_local_candidate(text)
        if candidate is None:
            raise FileGatewayError("source_denied")
        try:
            candidate = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            raise FileGatewayError("source_denied") from None
        matched: Path | None = None
        for root in self.roots:
            if candidate == root or root in candidate.parents:
                matched = root
                break
        if matched is None:
            raise FileGatewayError("path_not_allowed")
        if self._denied(candidate):
            raise FileGatewayError("denied_location")
        if candidate.suffix.lower() not in MEDIA_ALLOWED_SUFFIXES:
            raise FileGatewayError("format_not_supported")
        if not candidate.is_file() or candidate.stat().st_size > self.max_bytes:
            raise FileGatewayError("file_unavailable")
        return candidate

    def read(self, relative: str) -> dict[str, Any]:
        path, _root = self.authorize(relative)
        suffix = path.suffix.lower()
        if suffix in {
            ".txt",
            ".md",
            ".markdown",
            ".rst",
            ".tex",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cc",
            ".cxx",
            ".cs",
            ".py",
            ".js",
            ".ts",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".csv",
        }:
            return {
                "name": path.name,
                "format": suffix[1:],
                "text": path.read_text(encoding="utf-8", errors="replace"),
                "size": path.stat().st_size,
            }
        return {
            "name": path.name,
            "format": suffix[1:],
            "text": None,
            "status": "parser_required",
            "size": path.stat().st_size,
        }
