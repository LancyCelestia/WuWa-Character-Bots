"""路径域判定唯一真身（SAFE-EXEC Wave 1 · 规格 §3「落点域」）。

它只回答一个问题：**这个路径，bot 能不能读它的字节并发出去**。返回三态
（``allowed`` / ``denied`` / ``needs_review``）+ 稳定原因码，供审计与诊断卡消费。

三条不变式（改本文件前先读，都要有测试撑着）：

1. **判定一律在规范化之后做**。`Path.resolve()` 会把 `..`、`.`、8.3 短名
   （实测 `C:/PROGRA~1` → `C:\\Program Files`）、尾点/尾空格（实测
   `C:/Windows/win.ini.` → `C:\\Windows\\win.ini`）、符号链接与 junction 全部折成
   真实落点， containment 只对真实落点执法 ⇒ 「换一种写法」不构成逃逸。
   注毒验证：把 `resolve()` 摘掉，`tests/test_safety_exec_paths.py` 的穿越样本表
   与 junction 用例当场红（AGENTS 规则「活性判据」）。
2. **禁触域优先于允许根**。允许根之内再压一层名册黑名单（SQLite / Cookie /
   人格库 / `.env` / `settings/*.json` / venv / `.git` / 日志），命中即拒，
   绝不因为「它在你自己的数据目录里」而放行。名册按 `docs/db-owners.md` 与
   `scripts/runtime_paths.py` 的真身取，不自己编目录名。
3. **fail-closed**。空路径、取不到根目录、解析抛异常、解析结果自带设备命名空间
   前缀（实测纯点段会诱发）、相对写法歧义、UNC/设备命名空间、
   Alternate Data Stream —— 一律拒，不猜、不「先放行再看」。

出站口只有一处判定（规格 §3 硬规则 1 点名的就是 `file_gateway._stage_path`）：
第二份路径消毒、第二张名册由本波 grep 门拦下，见 `tests/test_safety_exec_paths.py`。
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Final

# ---------------------------------------------------------------------------
# 三态与落点域（值即原因码口径，进审计与诊断卡，改名要同步测试）
# ---------------------------------------------------------------------------

VERDICT_ALLOWED: Final[str] = "allowed"
VERDICT_DENIED: Final[str] = "denied"
VERDICT_NEEDS_REVIEW: Final[str] = "needs_review"

DOMAIN_WORKSPACE: Final[str] = "workspace_read"
DOMAIN_RUNTIME: Final[str] = "runtime_data"
DOMAIN_FORBIDDEN: Final[str] = "forbidden"
DOMAIN_OUTSIDE: Final[str] = "outside"
DOMAIN_UNDETERMINED: Final[str] = "undetermined"


class DenyReason:
    """``denied`` 的稳定原因码（一码一因，禁止全部塌成一枚兜底码）。"""

    EMPTY_PATH: Final[str] = "empty_path"
    ROOT_UNRESOLVED: Final[str] = "root_unresolved"
    RESOLVE_FAILED: Final[str] = "resolve_failed"
    RELATIVE_AMBIGUOUS: Final[str] = "relative_ambiguous"
    ENCODED_SEPARATOR: Final[str] = "encoded_separator"
    SHORT_NAME_FORM: Final[str] = "short_name_form"
    TRAILING_DOT_OR_SPACE: Final[str] = "trailing_dot_or_space"
    UNC_OR_DEVICE_PATH: Final[str] = "unc_or_device_path"
    ALTERNATE_DATA_STREAM: Final[str] = "alternate_data_stream"
    TRAVERSAL_ESCAPE: Final[str] = "traversal_escape"
    FORBIDDEN_ZONE: Final[str] = "forbidden_zone"
    FORBIDDEN_FILE_CLASS: Final[str] = "forbidden_file_class"
    OUTSIDE_ALLOWED_ROOTS: Final[str] = "outside_allowed_roots"


DENY_REASONS: Final[frozenset[str]] = frozenset(
    {
        DenyReason.EMPTY_PATH,
        DenyReason.ROOT_UNRESOLVED,
        DenyReason.RESOLVE_FAILED,
        DenyReason.RELATIVE_AMBIGUOUS,
        DenyReason.ENCODED_SEPARATOR,
        DenyReason.SHORT_NAME_FORM,
        DenyReason.TRAILING_DOT_OR_SPACE,
        DenyReason.UNC_OR_DEVICE_PATH,
        DenyReason.ALTERNATE_DATA_STREAM,
        DenyReason.TRAVERSAL_ESCAPE,
        DenyReason.FORBIDDEN_ZONE,
        DenyReason.FORBIDDEN_FILE_CLASS,
        DenyReason.OUTSIDE_ALLOWED_ROOTS,
    }
)


class ReviewReason:
    """``needs_review`` 的稳定原因码（Wave 1 无同意回路 ⇒ 记账放行，见 §消费口）。"""

    UNREGISTERED_RUNTIME_SUBTREE: Final[str] = "unregistered_runtime_subtree"
    LINK_IN_PATH: Final[str] = "link_in_path"


REVIEW_REASONS: Final[frozenset[str]] = frozenset(
    {ReviewReason.UNREGISTERED_RUNTIME_SUBTREE, ReviewReason.LINK_IN_PATH}
)

# 人话说明：进审计行与诊断卡（规格 §1 表「诊断与告警＝复用」）。不得含盘符。
REASON_PLAIN_TEXT: Final[dict[str, str]] = {
    DenyReason.EMPTY_PATH: "没有给出路径，空引用不放行",
    DenyReason.ROOT_UNRESOLVED: "取不到工作区/运行数据根目录，按最保守口径拒绝",
    DenyReason.RESOLVE_FAILED: "路径规范化失败（不可解析或文件系统报错）",
    DenyReason.RELATIVE_AMBIGUOUS: "相对路径依赖当前工作目录，语义有歧义",
    DenyReason.ENCODED_SEPARATOR: "路径含百分号编码的分隔符或点（编码写法不放行）",
    DenyReason.SHORT_NAME_FORM: "路径含 8.3 短名形态（要用完整名重试）",
    DenyReason.TRAILING_DOT_OR_SPACE: "路径段是点号别名或尾点/尾空格形态（规避写法不放行）",
    DenyReason.UNC_OR_DEVICE_PATH: "网络共享路径或设备命名空间前缀一律拒绝",
    DenyReason.ALTERNATE_DATA_STREAM: "路径带 NTFS 备用数据流冒号后缀",
    DenyReason.TRAVERSAL_ESCAPE: "规范化后逃出了允许根目录（含 .. 变体）",
    DenyReason.FORBIDDEN_ZONE: "落点在禁触目录名册内（配置/凭据/人格库/虚拟环境）",
    DenyReason.FORBIDDEN_FILE_CLASS: "落点文件属于禁触类别（数据库/Cookie/日志/密钥/.env）",
    DenyReason.OUTSIDE_ALLOWED_ROOTS: "落点在工作区与运行数据域之外",
    ReviewReason.UNREGISTERED_RUNTIME_SUBTREE: "落在运行数据根之下、可读名册之外的子树",
    ReviewReason.LINK_IN_PATH: "路径含符号链接或 junction，落点以规范化结果为准",
}

# ---------------------------------------------------------------------------
# 禁触名册（真身来源：docs/db-owners.md 与 scripts/runtime_paths.py 的路径口径）
# ---------------------------------------------------------------------------

# 目录名黑名单（解析后逐段比对，casefold）。运行数据域/工作区都在允许根里，
# 但这些子树里的东西不属于「可外发媒体」：
#   settings/            ← config.py:bot_runtime_settings_dir（运行期覆盖，含令牌散列）
#   persona/ personas/   ← 人格库源与运行副本（AGENTS 规则 8 人格资产）
#   cookies/             ← 平台 Cookie 落盘目录形态
#   venv/                ← ChatBot_Runtime/venv 解释器与第三方包
#   .git/                ← 版本库对象与钩子
#   .ssh/                ← 私钥
#   prompt_audit/        ← 提示词审计留痕（含用户内容）
_FORBIDDEN_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "settings",
        "persona",
        "personas",
        "cookies",
        "cookie",
        "venv",
        ".git",
        ".ssh",
        "prompt_audit",
    }
)

# 文件名/后缀黑名单（SQLite 全家与可再生伴生文件、日志、密钥、向量索引）。
# 依据 docs/db-owners.md：库文件一律 *.sqlite3，WAL 伴生 -wal/-shm 与库同权重。
_FORBIDDEN_FILE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".sqlite3",
        ".sqlite",
        ".db",
        ".db-wal",
        ".db-shm",
        ".wal",
        ".shm",
        ".log",
        ".env",
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        ".faiss",
        ".kdbx",
    }
)

# 名称子串黑名单（casefold 后 contains）：Cookie 文件名、密钥形态、向量索引旁车。
# 生产 Cookie 件真身 = config.py:bot_cookies_file（例 data/platform_cookies.txt），
# 名字带 cookie 即可命中，不必猜目录。
_FORBIDDEN_NAME_SUBSTRINGS: Final[frozenset[str]] = frozenset(
    {
        "cookie",
        "credential",
        "secret",
        "token",
        "passw",
        "apikey",
        "api_key",
        "id_rsa",
        "id_ed25519",
        "faiss",
        "_settings",
    }
)

_EXACT_DENY_NAMES: Final[frozenset[str]] = frozenset(
    {".env", ".env.local", ".env.prod", ".netrc", ".npmrc", ".git-credentials"}
)

_PCT_ENCODED_RE: Final[re.Pattern[str]] = re.compile(r"%(?:2e|2f|5c|00|255c)", re.IGNORECASE)
_SHORT_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^[^.~\\/:*?\"<>|]{1,6}~\d{1,3}(?:\.[^~]{1,6})?$")
_STREAM_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:", re.IGNORECASE)
# 设备命名空间前缀（`\\?\…` 扩展长度 / `\\.\…` 物理设备，含 `\\?\UNC\`、
# `\\.\GLOBALROOT\`）：它**长得像 UNC**，但语义完全不同——UNC 那腿给 DOMAIN_OUTSIDE
# （是「别人机器的路径」），设备前缀给 DOMAIN_UNDETERMINED（是「换命名空间说话」，
# 规范化器根本不该接手）。故必须排在 UNC 分支之前判（消费点见 check_sendable ①）。
# 只匹配这两枚前缀：`\\server\share` 一类普通 UNC **不许**命中它（要留给下游腿）。
_DEVICE_NAMESPACE_RE: Final[re.Pattern[str]] = re.compile(r"^\\\\[?.]\\")

# 解析失败时的整串替身（绝不把原文写进回执）。
_OPAQUE_PATH_MASK: Final[str] = "<路径已隐藏>"
_LEAKY_FORM_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]:|^\\\\|^//|^~")


def _mask_path_text(value: str) -> str:
    """被拒路径的打码形态：走 `redact_local_secrets`，并再加一道「仍带盘符就整串丢弃」。

    第二道不是第二套打码实现，而是**后置断言**：中央件认得的形态（盘符绝对路径、
    `sk-`、`BOT_…=` 等）之外还剩 UNC/设备前缀/家目录波浪号时，宁可一个字符都不留。
    """
    try:
        from plugins.bot_unified_runtime.domains.render.plain_text import (
            redact_local_secrets,
        )
    except ImportError:  # pragma: no cover - 中央件缺失时走保守分支
        return _OPAQUE_PATH_MASK
    masked = redact_local_secrets(value)
    if _LEAKY_FORM_RE.search(masked):
        return _OPAQUE_PATH_MASK
    return masked


def _norm_key(path: Path) -> tuple[str, ...]:
    """可比较的规范化键：逐段 casefold（Windows 大小写不敏感）+ 剥尾点/尾空格。"""
    return tuple(
        part.casefold().rstrip(". ") if index else part.casefold()
        for index, part in enumerate(map(str, path.parts))
    )


def _is_within(candidate: Path, root: Path | None) -> bool:
    if root is None:
        return False
    left = _norm_key(candidate)
    right = _norm_key(root)
    if not left or not right:
        return False
    return left == right or left[: len(right)] == right


def _lexical_parts(raw: str) -> tuple[str, ...]:
    """按 Windows 语义拆段（生产是 Windows；判定不随宿主 OS 漂移）。"""
    return tuple(part for part in PureWindowsPath(raw).parts)


def _has_dotdot(parts: tuple[str, ...]) -> bool:
    return any(part == ".." for part in parts)


def _has_link_component(path: Path) -> bool:
    """逐段查链接（symlink/junction）。查不动当可疑，不当中性。"""
    collected: list[str] = []
    for part in map(str, path.parts):
        collected.append(part)
        probe = Path(*collected)
        try:
            if probe.is_symlink() or probe.is_junction():
                return True
        except OSError:
            return True
    return False


def _resolve_strict(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


@dataclass(frozen=True)
class PathDecision:
    """一次路径域判定的完整结论（可直接进审计行/诊断卡）。"""

    verdict: str
    reason_code: str
    domain: str
    target_name: str
    relative_ref: str
    masked_path: str

    @property
    def allowed(self) -> bool:
        return self.verdict == VERDICT_ALLOWED

    @property
    def denied(self) -> bool:
        return self.verdict == VERDICT_DENIED

    def audit_line(self) -> str:
        """一行可 grep 的人话（无盘符明文）。"""
        return (
            f"path_domain={self.verdict} reason_code={self.reason_code}"
            f" domain={self.domain} target={self.target_name or '-'}"
            f" ref={self.relative_ref or '-'} path={self.masked_path}"
        )


@dataclass(frozen=True)
class PathDomainPolicy:
    """三张登记（可读根 / 禁触名册 / 根坐标）+ 判定函数。

    根目录**全部可注入**：测试用 `tmp_path` 造假根，不依赖真实仓库结构；生产
    走 `build_default_policy()`（经 `scripts/runtime_paths.py` 取真身）。
    """

    workspace_root: Path | None
    runtime_data_root: Path | None
    runtime_home: Path | None
    readable_roots: tuple[tuple[str, Path], ...]
    forbidden_dir_names: frozenset[str] = _FORBIDDEN_DIR_NAMES
    forbidden_file_suffixes: frozenset[str] = _FORBIDDEN_FILE_SUFFIXES
    forbidden_name_substrings: frozenset[str] = _FORBIDDEN_NAME_SUBSTRINGS
    forbidden_exact_names: frozenset[str] = _EXACT_DENY_NAMES

    # -------------------- 判定 --------------------

    def check_sendable(self, candidate: str | os.PathLike[str] | None) -> PathDecision:
        """这个路径能不能读字节并发出站（出站口唯一判定，规格 §3 硬规则 1）。"""
        raw = "" if candidate is None else str(candidate)
        # 只在「整串是空白」时当空引用；**不 strip 正文**——尾空格本身就是本件要
        # 认的规避形态之一（strip 掉等于替攻击者把写法规范化了一遍）。
        if not raw.strip():
            return self._deny(DenyReason.EMPTY_PATH, DOMAIN_UNDETERMINED, "")

        parts = _lexical_parts(raw)
        backslashed = raw.replace("/", "\\")

        # ① 形态类判定（与落点无关、先拒）：编码分隔符 / UNC 与设备命名空间 / ADS。
        if _PCT_ENCODED_RE.search(raw):
            return self._deny(DenyReason.ENCODED_SEPARATOR, DOMAIN_UNDETERMINED, raw)
        if _DEVICE_NAMESPACE_RE.match(backslashed):
            return self._deny(DenyReason.UNC_OR_DEVICE_PATH, DOMAIN_UNDETERMINED, raw)
        if backslashed.startswith("\\\\") or raw.startswith("//"):
            return self._deny(DenyReason.UNC_OR_DEVICE_PATH, DOMAIN_OUTSIDE, raw)
        for part in parts:
            # ADS（`报告.txt:坏数据`）：除驱动器段外，段内冒号一律拒。
            if ":" in part and not _STREAM_TOKEN_RE.match(part):
                return self._deny(DenyReason.ALTERNATE_DATA_STREAM, DOMAIN_UNDETERMINED, raw)
            # 纯点别名段（`...` / `....`）：Win32 归一化会把 `...` 当 `..` 用
            # （实测 `Path('a/.../b').resolve()` **不**折，而协议端侧的解法折 ⇒
            # 两侧对同一字符串给出不同落点＝典型穿越缝隙），一律拒，不赌谁先解。
            if len(part) >= 3 and set(part) == {"."}:
                return self._deny(DenyReason.TRAILING_DOT_OR_SPACE, DOMAIN_UNDETERMINED, raw)

        # ② 锚定：绝对路径直接用；相对路径只认 `data/...` 这一种规范写法。
        anchored = self._anchor(raw, parts)
        if isinstance(anchored, PathDecision):
            return anchored
        lexical = anchored

        # ③ 规范化（链接/短名/尾点/.. 全在这一步折平）；解析失败即拒。
        resolved = _resolve_strict(lexical)
        if resolved is None:
            return self._deny(DenyReason.RESOLVE_FAILED, DOMAIN_UNDETERMINED, raw)

        # ③b 解析结果**自己**落进设备命名空间（本机 2026-09-26 实测：纯点段会让
        #    GetFullPathName 返回 `\\?\C:\…` 形态，超长不可解析路径同形）——这一串
        #    本件已读不懂它指向的真实落点：`\\?\` 命名空间停用 `.`/`..`/尾点归一化，
        #    剥掉前缀再解一遍会改落点；留着它去做 containment，`\\?\c:\` 与 `c:\`
        #    前缀对不上，只会产出一枚「结论对、理由说谎」的 outside_allowed_roots。
        #    fail-closed：拒，且给诚实原因码（这条必须在禁触名册**之前**——名字
        #    比对同样不可信一个自己都认不出的落点串）。
        resolved_text = str(resolved)
        if resolved_text.startswith(("\\\\?\\", "\\\\.\\")):
            return self._deny(DenyReason.UNC_OR_DEVICE_PATH, DOMAIN_UNDETERMINED, resolved_text)

        # ④ 禁触名册压在最外一层：在允许根内也拦。
        forbidden = self._forbidden_decision(resolved)
        if forbidden is not None:
            return forbidden

        # ⑤ 别名形态：只在**登记根之下的相对尾段**上判（根前缀本身可能就是 8.3
        #    形态——本机 `%TEMP%` 实测就是 `LANCYC~1`，那属宿主写法，不是逃逸手段）。
        form = self._form_violation(lexical, resolved)
        if form:
            return self._deny(form, DOMAIN_UNDETERMINED, str(resolved))
        escaped = _has_dotdot(parts)
        for label, root in self.readable_roots:
            if _is_within(resolved, root):
                domain = DOMAIN_WORKSPACE if label == "workspace" else DOMAIN_RUNTIME
                if _has_link_component(lexical):
                    # 链接本身不神秘，但「今天指向根内、明天被改指向别处」是事实：
                    # 记账待评审（Wave 2 有同意回路后收紧为拦）。
                    return self._decision(
                        VERDICT_NEEDS_REVIEW, ReviewReason.LINK_IN_PATH, domain, resolved
                    )
                return self._decision(VERDICT_ALLOWED, "", domain, resolved)
        if escaped:
            return self._deny(DenyReason.TRAVERSAL_ESCAPE, DOMAIN_OUTSIDE, str(resolved))
        if _is_within(resolved, self.runtime_home):
            # 运行数据根之下、登记名册之外：记账放行 + 等同意回路（Wave 2 收紧）。
            return self._decision(
                VERDICT_NEEDS_REVIEW,
                ReviewReason.UNREGISTERED_RUNTIME_SUBTREE,
                DOMAIN_RUNTIME,
                resolved,
            )
        return self._deny(DenyReason.OUTSIDE_ALLOWED_ROOTS, DOMAIN_OUTSIDE, str(resolved))

    # -------------------- 内部件 --------------------

    def _anchor(
        self, raw: str, parts: tuple[str, ...]
    ) -> Path | PathDecision:
        path = Path(raw)
        if path.is_absolute():
            return path
        normalized = raw.replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if _has_dotdot(parts):
            # 相对 + `..` ＝依赖 CWD 的歧义写法，不解释、直接拒。
            return self._deny(DenyReason.RELATIVE_AMBIGUOUS, DOMAIN_UNDETERMINED, raw)
        root = self.runtime_data_root
        if root is None:
            return self._deny(DenyReason.ROOT_UNRESOLVED, DOMAIN_UNDETERMINED, raw)
        if normalized.lower() == "data":
            return root
        if normalized.lower().startswith("data/"):
            return root / normalized[5:]
        # 其余相对写法（裸文件名、docs/x.md）没有登记锚点 ⇒ 歧义。
        return self._deny(DenyReason.RELATIVE_AMBIGUOUS, DOMAIN_UNDETERMINED, raw)

    def _prefix_roots(self) -> list[Path]:
        """所有登记根（可读根 + 三张坐标根），用于「尾段」切分。"""
        roots: list[Path] = [root for _label, root in self.readable_roots]
        roots.extend(
            root
            for root in (self.workspace_root, self.runtime_data_root, self.runtime_home)
            if root is not None
        )
        return [root for root in roots if str(root).strip()]

    def _relative_tail(self, resolved: Path) -> tuple[str, ...]:
        """取路径相对**最长匹配根前缀**的尾段（无匹配则给整串）。

        为什么要尾段而不是整串：本机 `%TEMP%` 实测就是 8.3 形态
        （`C:\\Users\\LANCYC~1\\AppData\\Local\\Temp\\…`），把宿主给的前缀写法当
        逃逸手段，会把所有暂存面一起误杀（并行席 S-T-FILE-2 23:38 现算到的那条
        `short_name_form` 误判即此）。根前缀以内的写法归宿主，根以下的别名形态
        才是本件要拦的东西。
        """
        best: tuple[str, ...] | None = None
        best_len = -1
        resolved_key = _norm_key(resolved)
        for root in self._prefix_roots():
            root_key = _norm_key(root)
            if not root_key or resolved_key[: len(root_key)] != root_key:
                continue
            if len(root_key) > best_len:
                best_len = len(root_key)
                best = resolved.parts[len(root_key) :]
        return best if best is not None else resolved.parts

    def _lexical_tail_if_under_root(self, lexical: Path) -> tuple[str, ...] | None:
        """写法未换空间时（前缀逐段对得上登记根）给出词法尾段；换了写法返回 None。

        需要它是因为 ``resolve()`` 对尾点/尾空格的折平**随目标是否存在而变**（本机
        实测 ``report.txt `` 被折成 ``report.txt``、``report.txt.`` 原样保留）⇒
        只按解析结果判，会把同一类规避写法判出两种结论。别名形态一律按**给进来的
        写法**拒，不去赌宿主解析器当天怎么解。
        前缀对不上（例如宿主把根写成 8.3）时不给尾段 ⇒ 交给解析后那条腿判，
        避免把宿主给的前缀写法误判成逃逸。
        """
        key = _norm_key(lexical)
        for root in self._prefix_roots():
            root_key = _norm_key(root)
            if root_key and key[: len(root_key)] == root_key:
                return lexical.parts[len(root_key) :]
        return None

    def _form_violation(self, lexical: Path, resolved: Path) -> str | None:
        """根以下相对尾段里的别名形态：8.3 短名 / 纯点别名 / 尾点 / 尾空格。

        这些形态在**存在的目标**上会被 `resolve()` 折平（实测
        `C:/Windows/win.ini.` → `C:\\Windows\\win.ini`），所以它们真正剩下的风险面
        是「解析器之间不一致」：bot 规范化后看着在根内，别的组件（协议端侧、
        杀软、备份）按另一种规则再解一次 ⇒ 一律拒，不赌谁先解。
        """
        tails: list[tuple[str, ...]] = [self._relative_tail(resolved)]
        lexical_tail = self._lexical_tail_if_under_root(lexical)
        if lexical_tail is not None:
            tails.append(lexical_tail)
        for parts in tails:
            for part in map(str, parts):
                if _SHORT_NAME_RE.match(part):
                    return DenyReason.SHORT_NAME_FORM
                if len(part) >= 3 and set(part) == {"."}:
                    return DenyReason.TRAILING_DOT_OR_SPACE
                if len(part) > 1 and part.strip(".") and part.endswith((".", " ")):
                    return DenyReason.TRAILING_DOT_OR_SPACE
        return None

    def _forbidden_decision(self, resolved: Path) -> PathDecision | None:
        lowered_parts = [part.casefold() for part in map(str, resolved.parts)]
        name = lowered_parts[-1] if lowered_parts else ""
        dirs = lowered_parts[:-1]
        if any(part in self.forbidden_dir_names for part in dirs):
            return self._deny(DenyReason.FORBIDDEN_ZONE, DOMAIN_FORBIDDEN, str(resolved))
        if name in self.forbidden_exact_names or name.startswith(".env"):
            return self._deny(DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN, str(resolved))
        if set(Path(name).suffixes) & self.forbidden_file_suffixes:
            return self._deny(DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN, str(resolved))
        # WAL 伴生件的真名带库名前缀（实测 `user_affinity.sqlite3-wal` 的 suffix 是
        # `.sqlite3-wal`，枚举不全）⇒ 按 `-wal`/`-shm` 结尾兜底。依据 docs/db-owners.md：
        # 「删文件 = 删同目录的 -wal / -shm 伴生文件」，它们与库同权重。
        if name.endswith(("-wal", "-shm", "-journal")):
            return self._deny(DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN, str(resolved))
        if any(token in name for token in self.forbidden_name_substrings):
            return self._deny(DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN, str(resolved))
        return None

    def _deny(self, reason_code: str, domain: str, display: str) -> PathDecision:
        return self._decision(VERDICT_DENIED, reason_code, domain, _as_path(display))

    def _decision(
        self,
        verdict: str,
        reason_code: str,
        domain: str,
        display: Path | None,
    ) -> PathDecision:
        """组装结论。``relative_ref`` 是**根相对尾段**（如 ``runtime:cards/x.png``）：
        管理员看得懂「哪个根下的哪个文件」，而这一行里不会出现盘符。"""
        text = "" if display is None else str(display)
        name = display.name if display is not None and display.name else ""
        relative_ref = ""
        if display is not None:
            for root_label, root in self.readable_roots:
                if _is_within(display, root):
                    try:
                        tail = display.relative_to(root)
                    except ValueError:  # pragma: no cover - 上面的包含判据已保证
                        tail = Path(display.name)
                    relative_ref = f"{root_label}/{tail}".replace("\\", "/")
                    break
        return PathDecision(
            verdict=verdict,
            reason_code=reason_code,
            domain=domain,
            target_name=name,
            relative_ref=relative_ref,
            masked_path=_mask_path_text(text) if text else _OPAQUE_PATH_MASK,
        )


def _as_path(value: str) -> Path | None:
    if not value:
        return None
    try:
        return Path(value)
    except (TypeError, ValueError):  # pragma: no cover - 极端畸形输入兜底（判定仍为 denied）
        return None


# ---------------------------------------------------------------------------
# 缺省登记（真身来源 scripts/runtime_paths.py，不在这里编目录名）
# ---------------------------------------------------------------------------

# 规格 §3「可读根」名册里属于运行数据域的子树；其余按 config.py path_fields 真身取。
_RUNTIME_READABLE_SUBTREES: Final[tuple[str, ...]] = (
    "downloads",
    "generated_files",
    "file_workspace",
    "media_archive",
    "notes",
    "avatar",
    "cards",
    "memes",
    "meme_library",
    "music",
    "tts_output",
    "food_images",
    "daily_assist",
)
_RUNTIME_HOME_READABLE_SUBTREES: Final[tuple[str, ...]] = ("cache",)


def _resolve_default_roots() -> tuple[Path | None, Path | None, Path | None]:
    """(工作区根, 运行数据根, 运行数据家目录) —— 取不到就是 None（判定 fail-closed）。"""
    workspace_root: Path | None = None
    try:
        # <ws>/plugins/bot_unified_runtime/domains/core/safety_exec/paths.py
        workspace_root = Path(__file__).resolve().parents[5]
    except (OSError, ValueError, IndexError):  # pragma: no cover
        workspace_root = None
    runtime_data_root: Path | None = None
    try:
        from scripts.runtime_paths import runtime_data_dir  # 唯一重映射真身

        runtime_data_root = Path(str(runtime_data_dir())).resolve()
    except (ImportError, OSError, ValueError, KeyError):
        runtime_data_root = None
    if runtime_data_root is None and workspace_root is not None:
        # .env.example 口径（BOT_RUNTIME_DATA_DIR=../ChatBot_Runtime/data）仅作兜底，
        # 且只有目录真存在时才认，避免把猜测当事实。
        guess = workspace_root.parent / "ChatBot_Runtime" / "data"
        runtime_data_root = guess if guess.is_dir() else None
    runtime_home = runtime_data_root.parent if runtime_data_root is not None else None
    return workspace_root, runtime_data_root, runtime_home


def build_policy(
    *,
    workspace_root: str | os.PathLike[str] | None = None,
    runtime_data_root: str | os.PathLike[str] | None = None,
    extra_readable_roots: tuple[tuple[str, str | os.PathLike[str]], ...] = (),
) -> PathDomainPolicy:
    """按注入的根目录构造判定策略（测试用假根，生产用 `build_default_policy`）。"""

    def _as_root(value: str | os.PathLike[str] | None) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        resolved = _resolve_strict(Path(str(value)))
        return resolved or Path(str(value))

    workspace = _as_root(workspace_root)
    data_root = _as_root(runtime_data_root)
    home = data_root.parent if data_root is not None else None

    readable: list[tuple[str, Path]] = []
    if workspace is not None:
        readable.append(("workspace", workspace))
    if data_root is not None:
        # 运行数据域整体可读（媒体缓存/生成物/卡片图＝既有功能），禁触类别由名册拦。
        readable.append(("runtime", data_root))
        for sub in _RUNTIME_READABLE_SUBTREES:
            readable.append((f"runtime:{sub}", data_root / sub))
    if home is not None:
        for sub in _RUNTIME_HOME_READABLE_SUBTREES:
            readable.append((f"runtimewrap:{sub}", home / sub))
    for label, root in extra_readable_roots:
        resolved = _as_root(root)
        if resolved is not None:
            readable.append((label, resolved))

    return PathDomainPolicy(
        workspace_root=workspace,
        runtime_data_root=data_root,
        runtime_home=home,
        readable_roots=tuple(readable),
    )


def build_default_policy() -> PathDomainPolicy:
    workspace, data_root, _home = _resolve_default_roots()
    return build_policy(workspace_root=workspace, runtime_data_root=data_root)


_default_policy: PathDomainPolicy | None = None
_default_policy_lock = threading.Lock()


def default_policy() -> PathDomainPolicy:
    """进程级缺省策略（第一次取用时按真身解析，之后固定）。"""
    global _default_policy
    policy = _default_policy
    if policy is None:
        with _default_policy_lock:
            if _default_policy is None:
                _default_policy = build_default_policy()
            policy = _default_policy
    return policy


def set_default_policy(policy: PathDomainPolicy | None) -> None:
    """测试/装配注入口（传 None 复位为惰性重建）。"""
    global _default_policy
    with _default_policy_lock:
        _default_policy = policy


def check_sendable(
    candidate: str | os.PathLike[str] | None,
    *,
    policy: PathDomainPolicy | None = None,
) -> PathDecision:
    """出站口唯一判定（规格 §3 点名的 `paths.check_sendable()`）。"""
    return (policy or default_policy()).check_sendable(candidate)


def plain_reason(reason_code: str) -> str:
    """原因码 → 人话（诊断卡/回执用）。认不出只点名代号，绝不编解释。"""
    text = REASON_PLAIN_TEXT.get(reason_code)
    if text:
        return text
    return f"未登记的路径域原因码 {reason_code}" if reason_code else "未给出原因码"


def registered_denial_reasons() -> frozenset[str]:
    return DENY_REASONS


def registered_review_reasons() -> frozenset[str]:
    return REVIEW_REASONS


def policy_roots(policy: PathDomainPolicy | None = None) -> dict[str, Any]:
    """当前登记的根（观测用；不含文件内容）。"""
    active = policy or default_policy()
    return {
        "workspace_root_masked": (
            _mask_path_text(str(active.workspace_root)) if active.workspace_root else ""
        ),
        "runtime_data_root_masked": (
            _mask_path_text(str(active.runtime_data_root)) if active.runtime_data_root else ""
        ),
        "readable_root_labels": [label for label, _root in active.readable_roots],
    }
