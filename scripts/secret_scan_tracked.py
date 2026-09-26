"""只读尺：扫「git 已跟踪源文件里硬编码的凭据」（席位 S100，2026-09-24 安全面）。

为什么要有这把尺
----------------
AGENTS 铁律 3 规定真 key 只在 ``.env``、配置里一律写 ``env:变量名``。但 2026-09-24
主代理在**已跟踪**的 ``scripts/configure_axonhub_registry.py`` 里发现一枚真实网关凭据
被硬编码，且该脚本会把它**反写回** ``.env``——方向正好和铁律相反。这说明「tracked 源里
硬编码凭据」不是孤例假设，需要一把全树尺把它变成可复查的账。

两族判据**分开报**（本尺的核心设计，绝不混成一个数）
----------------------------------------------------
* **F1 形态命中**：长度 / 字符集 / 前缀符合真凭据形态（``ah-``/``sk-``/``ghp_``/``xox*``
  /PEM 头/``Authorization: Bearer <字面量>``/``api_key=<字面量>`` 等）。这是欠账。
* **F2 占位/引用形（放行）**：``env:变量名``、``<你的key>``、``EXAMPLE``、``CHANGE_ME``、
  测试夹具里显式命名的假值、指向变量/配置字段的引用、已被打码的星号形态。这是合规形态，
  计数只为「尺确实看得见这一面」提供证据，不算债。

泄漏面纪律（最高优先）
----------------------
本尺**任何情况下都不把命中原文完整打进 stdout、报告或测试输出**——那会变成第二处泄漏面。
每条命中只输出：``件:行号 + 掩码形态（前 3 后 2 字符、中间星号）+ sha256[:16]``。
指纹口径 = 对**匹配到的凭据字面量本身**做 sha256，取十六进制前 16 位。

只读保证
--------
零写入：不创建、不修改、不删除任何文件；只 ``git ls-files`` 取清单 + 读文件 + 打印。
本尺今天**只报不修**。

用法
----
    python scripts/secret_scan_tracked.py --report          # 人类可读（掩码）
    python scripts/secret_scan_tracked.py --json            # 机器可读（仍全掩码）
    python scripts/secret_scan_tracked.py --files-from f    # 自定义清单（评审/自测用）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 扫描面口径
# 清单口径写死为 `git ls-files`（只认索引里的件，未跟踪件天然不进面）。
# 下面这些前缀/文件名即便出现在清单里也一律排除——它们要么是运行数据（铁律 1/2：
# 不扫描不索引），要么是本尺明令不碰的密钥落点（`.env` 是**该**放真 key 的地方）。
EXCLUDE_PREFIXES: tuple[str, ...] = (
    "ChatBot_Runtime/",
    "ChatBot_Archive/",
    ".git/",
    "node_modules/",
    "webui/node_modules/",
    ".superpowers/",
)
EXCLUDE_BASENAMES: frozenset[str] = frozenset({".env", "nul"})
EXCLUDE_NAME_PREFIXES: tuple[str, ...] = (".env.",)
MAX_FILE_BYTES = 4_000_000

# ------------------------------------------------------------------ F1 家族
# ⚠ 本文件禁止出现任何真实凭据字面量（包括被点名的那枚）——正则只写**形态**。
_PREFIXED_KEY = re.compile(
    r"(?<![A-Za-z0-9_\-])"
    r"(?P<val>"
    r"ah-[A-Za-z0-9]{24,}"
    r"|sk-(?:proj-|live-|test-|local-)?[A-Za-z0-9_\-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_\-]{15,}"
    r"|xox[abprs]-[A-Za-z0-9\-]{18,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ASIA[0-9A-Z]{16}"
    r"|AIza[0-9A-Za-z_\-]{30,}"
    r"|ya29\.[A-Za-z0-9_\-]{24,}"
    r"|SG\.[A-Za-z0-9_\-]{20,}"
    r"|npm_[A-Za-z0-9]{24,}"
    r"|pypi-[A-Za-z0-9_\-]{24,}"
    r"|hf_[A-Za-z0-9]{24,}"
    r"|dop_v1_[a-f0-9]{24,}"
    r"|dckr_pat_[A-Za-z0-9_\-]{16,}"
    r"|xapp-[A-Za-z0-9\-]{20,}"
    r")"
    r"(?![A-Za-z0-9_\-])"
)
_PEM_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_BEARER = re.compile(
    r"(?i)(?P<head>authorization\s*[:=]\s*|[?&]access_token=|\bbearer\s+|\bbasic\s+)"
    r"(?P<q>[\"']?)(?P<val>[^\s\"'&,;)\]}]{8,})"
)
_URL_CRED = re.compile(
    r"(?i)\b(?P<scheme>[a-z][a-z0-9+.\-]{1,16})://(?P<user>[^\s/:@]{1,64}):"
    r"(?P<val>[^\s/@]{4,64})@"
)
# 赋值形分两条独立正则（带引号 / 裸值），不塞进同一个 alternation——Python 3.12
# 禁止 `(?i)` 这类全局标志出现在表达式非起始位置（照抄会在 import 期 re.error）。
_ASSIGNMENT_QUOTED = re.compile(
    r"(?i)(?P<name>[A-Za-z0-9_.\-]{2,72})"
    r"\s*(?P<sep>:=|::|[:=])\s*"
    r"(?P<q>[\"'])(?P<val>[^\"'\n]{4,}?)(?P=q)"
)
_ASSIGNMENT_BARE = re.compile(
    r"(?i)(?P<name>[A-Za-z0-9_.\-]{2,72})"
    r"\s*(?P<sep>:=|::|[:=])\s*"
    r"(?P<val>[^\s\"',;)\]}<]{6,})"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
_TELEGRAM_TOKEN = re.compile(r"\b(?P<val>[0-9]{8,10}:[A-Za-z0-9_\-]{30,})")
_SLACK_WEBHOOK = re.compile(
    r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{10,}"
)
_DISCORD = re.compile(
    r"(?:https://discord(?:app)?\.com/api/webhooks/\d+/|(?P<dt>[MW][A-Za-z0-9_\-]{22,34}\.[A-Za-z0-9_\-]{20,}))"
)

# 名字里带这些后缀/整词的赋值，才算「在赋一个凭据」而不是在赋一个普通值。
_SECRET_NAME_WORDS: tuple[str, ...] = (
    "apikey",
    "api_secret",
    "api_token",
    "access_key",
    "secret_key",
    "client_secret",
    "client_key",
    "auth_key",
    "auth_token",
    "authorization",
    "bearer",
    "access_token",
    "refresh_token",
    "id_token",
    "session_token",
    "private_key",
    "signing_key",
    "encryption_key",
    "app_secret",
    "bot_token",
    "webhook_token",
    "cookie",
    "credentials",
    "credential",
    "passwd",
    "password",
    "psk",
    "secret",
    "token",
)

# ------------------------------------------------------------------ F2 形态
_ENV_REF = re.compile(r"(?i)\benv:[A-Za-z_][A-Za-z0-9_]*")
_TEMPLATE_REF = re.compile(r"(\$[({][^)}]*[)}])|(%\()?[sdf]\b|\{\{[^{}]*\}\}|\{\s*\}")
_MASKED = re.compile(r"\*{2,}|…|\.{3}")
_PLACEHOLDER_WORDS: tuple[str, ...] = (
    "your_",
    "your-",
    "yourkey",
    "your_token",
    "example",
    "sample",
    "changeme",
    "change_me",
    "change-me",
    "replaceme",
    "replace_me",
    "insert_",
    "placeholder",
    "dummy",
    "fake",
    "mock",
    "fixture",
    "notreal",
    "not_real",
    "not-a-real",
    "invalid",
    "redact",
    "masked",
    "scrub",
    "todo",
    "fixme",
    "xxxx",
    "yyyy",
    "zzzz",
    "abcdefg",
    "abcdefgh",
    "lorem",
    "dummyvalue",
    "goeshere",
    "goes_here",
    "testonly",
    "test_only",
    "test-key",
    "test_token",
    "demo",
    "populated",
    "none",
    "null",
    "empty",
    "default",
)
_IDENTIFIER_REF = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*[A-Za-z_][A-Za-z0-9_]*$"
)
_ALL_CAPS_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_OSPATH_OR_URL = re.compile(r"^(?:https?://|ftp://|file://|[A-Za-z]:[\\/]|/|\.{1,2}/)")
_LOCAL_ONLY_URL = re.compile(
    r"(?i)^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d+)?(?:/\S*)?$"
)

# 散文形：真凭据是高熵随机串；`sk-test-value` / `wrong-token` / `admin-secret-token`
# 这类由若干小写字母词拼出来的值，是测试夹具里显式命名的假值 ⇒ 归 F2 不算债。
# 判据要「两枚以上纯字母小写词」且**全串无大写**，避免把混合大小写的真 key 洗掉
# （被点名的 `ah-<64hex>` 只有一个纯字母词 `ah`（2 字符），不会被误降）。
_PROSE_WORD = re.compile(r"[a-z]{4,}")


def _is_prose_shaped(value: str) -> bool:
    if any(ch.isupper() for ch in value):
        return False
    words = [tok for tok in re.split(r"[^A-Za-z0-9]+", value) if tok]
    prose = [tok for tok in words if _PROSE_WORD.fullmatch(tok)]
    return len(prose) >= 2


F1 = "F1"
F2 = "F2"


@dataclass(frozen=True)
class Finding:
    """一条命中（已脱敏）：只带位置、族名、掩码与指纹，绝不带原文。"""

    kind: str
    family: str
    path: str
    line_no: int
    masked: str
    digest: str
    length: int

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "family": self.family,
            "path": self.path,
            "line": self.line_no,
            "masked": self.masked,
            "sha256_16": self.digest,
            "length": self.length,
        }

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line_no}"


class CoverageError(RuntimeError):
    """扫描件数塌了——尺变短了，不允许 silently 放行。"""


def mask_secret(value: str) -> str:
    """前 3 + 星号 + 后 2；过短则整枚打码（宁可少给信息）。"""
    if len(value) <= 6:
        return "*" * max(3, len(value))
    return f"{value[:3]}{'*' * 8}{value[-2:]}"


def fingerprint(value: str) -> str:
    """凭据字面量的 sha256 前 16 位（稳定身份，可用于对账而不暴露原文）。"""
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    total = len(value)
    return -sum(
        (n / total) * math.log2(n / total) for n in counts.values() if n > 0
    )


def _looks_credential_shaped(value: str, *, min_len: int = 12) -> bool:
    """F1 的通用「像真凭据」判据：够长、字符集对、熵够高。"""
    if len(value) < min_len:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-\.+/=:@~%]+", value):
        return False
    if len(set(value)) < 5:
        return False
    return _shannon_entropy(value) >= 3.0


def classify_placeholder(value: str) -> str | None:
    """命中 F2 形态则返回该形态名，否则 None。判定顺序即优先级。"""
    if _ENV_REF.search(value):
        return "f2:env-ref"
    if value.startswith("<") or ("<" in value and ">" in value):
        return "f2:angle-bracket"
    if _TEMPLATE_REF.search(value):
        return "f2:template-ref"
    if _MASKED.search(value):
        return "f2:masked-shape"
    lowered = value.lower()
    for word in _PLACEHOLDER_WORDS:
        if word in lowered:
            return f"f2:placeholder-word:{word}"
    if _LOCAL_ONLY_URL.match(value):
        return "f2:loopback-url"
    if _ALL_CAPS_NAME.match(value):
        # `API_KEY=BOT_API_KEY_AXONHUB` 这类是「指向环境变量名」，不是值本身。
        return "f2:env-var-name-ref"
    if _is_prose_shaped(value):
        # 夹具里的显式假值（多枚小写词拼出来、无大写、非高熵）。
        return "f2:prose-token"
    if _IDENTIFIER_REF.match(value) and ("." in value or not _OSPATH_OR_URL.match(value)):
        # config.api_key / os.environ.X / settings.token —— 引用，不是字面量。
        return "f2:identifier-ref"
    if not _looks_credential_shaped(value, min_len=10):
        return "f2:low-entropy-or-shape"
    return None


def _name_is_secret_bearing(name: str) -> bool:
    lowered = re.sub(r"[^a-z0-9]", "", name.lower())
    if not lowered:
        return False
    if any(word in lowered for word in _SECRET_NAME_WORDS):
        return True
    compact_words = tuple(w.replace("_", "") for w in _SECRET_NAME_WORDS)
    return any(word in lowered for word in compact_words)


def _emit(
    sink: dict[tuple[str, int, str], Finding],
    *,
    path: str,
    line_no: int,
    family: str,
    value: str,
) -> None:
    placeholder = classify_placeholder(value)
    if placeholder is not None:
        kind, fam = F2, placeholder
    else:
        kind, fam = F1, family
    key = (path, line_no, fingerprint(value))
    existing = sink.get(key)
    if existing is not None:
        # 同一行同一枚值被多个家族抓到：F1 优先，族名并列记录，绝不新增一条计数。
        if kind == F1 and existing.kind == F2:
            sink[key] = Finding(
                kind=kind,
                family=f"{existing.family}+{fam}",
                path=path,
                line_no=line_no,
                masked=mask_secret(value),
                digest=fingerprint(value),
                length=len(value),
            )
        elif kind == F1 and existing.kind == F1 and fam not in existing.family:
            sink[key] = Finding(
                kind=F1,
                family=f"{existing.family}+{fam}",
                path=path,
                line_no=line_no,
                masked=mask_secret(value),
                digest=existing.digest,
                length=existing.length,
            )
        return
    sink[key] = Finding(
        kind=kind,
        family=fam,
        path=path,
        line_no=line_no,
        masked=mask_secret(value),
        digest=fingerprint(value),
        length=len(value),
    )


def scan_text(text: str, *, path: str) -> list[Finding]:
    """扫一份文本内容（不落盘、不写任何东西），返回去重后的命中列表。"""
    sink: dict[tuple[str, int, str], Finding] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for match in _PREFIXED_KEY.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:prefixed-key",
                  value=match.group("val"))
        for match in _PEM_KEY.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:pem-private-key",
                  value=match.group(0))
        for match in _BEARER.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:bearer-literal",
                  value=match.group("val"))
        for match in _URL_CRED.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:url-credentials",
                  value=match.group("val"))
        for match in _JWT.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:jwt",
                  value=match.group(0))
        for match in _TELEGRAM_TOKEN.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:telegram-bot-token",
                  value=match.group("val"))
        for match in _SLACK_WEBHOOK.finditer(line):
            _emit(sink, path=path, line_no=line_no, family="f1:slack-webhook",
                  value=match.group(0))
        for match in _DISCORD.finditer(line):
            value = match.group("dt") or match.group(0)
            _emit(sink, path=path, line_no=line_no, family="f1:discord", value=value)
        for pattern in (_ASSIGNMENT_QUOTED, _ASSIGNMENT_BARE):
            for match in pattern.finditer(line):
                name = match.group("name")
                value = match.group("val")
                if not name or not value:
                    continue
                if not _name_is_secret_bearing(name):
                    continue
                if not _looks_credential_shaped(value, min_len=8):
                    continue
                _emit(sink, path=path, line_no=line_no,
                      family="f1:assignment-literal", value=value)
    return sorted(sink.values(), key=lambda f: (f.path, f.line_no, f.kind, f.family))


# ---------------------------------------------------------------- 扫描面取数
def _run_git_ls_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files 失败：" + proc.stderr.decode("utf-8", "replace")[:200]
        )
    raw = proc.stdout.decode("utf-8", "replace").split("\0")
    return [p for p in (seg.strip().lstrip("./") for seg in raw) if p]


def is_in_scope(rel_path: str) -> bool:
    """本尺的扫描面口径（唯一真身，测试也用它，禁第二份副本）。"""
    posix = rel_path.replace("\\", "/")
    if any(posix.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return False
    base = posix.rsplit("/", 1)[-1]
    if base in EXCLUDE_BASENAMES:
        return False
    return not (
        base.startswith(EXCLUDE_NAME_PREFIXES) and base != ".env.example"
    )


def tracked_text_files(
    root: Path = REPO_ROOT,
) -> tuple[list[str], list[str], list[str]]:
    """返回 (可扫文本件, 二进制跳过, 面外排除)。清单口径 = `git ls-files`。"""
    scannable: list[str] = []
    binary: list[str] = []
    excluded: list[str] = []
    for rel in _run_git_ls_files(root):
        if not is_in_scope(rel):
            excluded.append(rel)
            continue
        target = root / rel
        try:
            size = target.stat().st_size
        except OSError:
            excluded.append(rel)
            continue
        if size > MAX_FILE_BYTES:
            excluded.append(rel)
            continue
        try:
            data = target.read_bytes()
        except OSError:
            excluded.append(rel)
            continue
        if b"\x00" in data[:8192]:
            binary.append(rel)
            continue
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            binary.append(rel)
            continue
        scannable.append(rel)
    return scannable, binary, excluded


def scan_paths(root: Path, rel_paths: Iterable[str]) -> list[Finding]:
    """对给定清单逐个读取并扫描（只读）。"""
    findings: list[Finding] = []
    for rel in rel_paths:
        target = root / rel
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(scan_text(text, path=rel.replace("\\", "/")))
    return findings


def f1_findings(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.kind == F1]


def f2_findings(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if f.kind == F2]


def enforce_coverage(scanned_count: int, *, floor: int) -> None:
    """反缩面地板：扫描件数低于地板即抛。尺变短必须当场响，不许静默放行。"""
    if scanned_count < floor:
        raise CoverageError(
            f"扫描件数 {scanned_count} < 地板 {floor}；"
            "清单口径 = git ls-files（见 is_in_scope），面被缩小了。"
        )


# ------------------------------------------------------------------ CLI 出口
def render_report(
    findings: Sequence[Finding],
    *,
    scanned: int,
    binary_skipped: int,
    excluded: int,
) -> str:
    f1 = f1_findings(findings)
    f2 = f2_findings(findings)
    lines: list[str] = [
        "已跟踪源硬编码凭据扫描（掩码输出；原文任何情况不回显）",
        (
            f"清单口径：git ls-files + is_in_scope 排除；可扫文本件={scanned} "
            f"二进制跳过={binary_skipped} 面外排除={excluded}"
        ),
        "",
        f"== F1 形态命中（欠账）：{len(f1)} 条 ==" if f1
        else "== F1 形态命中（欠账）：0 条 ==",
    ]
    for f in f1:
        lines.append(
            f"  F1  {f.location:<62} {f.family:<26} {f.masked:<16} "
            f"sha256[:16]={f.digest} len={f.length}"
        )
    lines.append("")
    lines.append(f"== F2 占位/引用形（放行，不算债）：{len(f2)} 条 ==")
    by_family = Counter(f.family for f in f2)
    for family, count in sorted(by_family.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  F2  {family:<40} {count}")
    lines.append("")
    lines.append(f"合计：F1={len(f1)}  F2={len(f2)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="只读扫描 git 已跟踪源文件中的硬编码凭据（掩码输出）。"
    )
    parser.add_argument("--report", action="store_true", help="人类可读报告（默认）")
    parser.add_argument("--json", action="store_true", help="机器可读（仍全掩码）")
    parser.add_argument("--root", default=str(REPO_ROOT), help="仓库根（默认脚本上级）")
    parser.add_argument(
        "--files-from",
        default=None,
        help="改从文件（或 '-'=stdin）按行读清单，用于评审/自测；仍过 is_in_scope",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.files_from:
        if args.files_from == "-":
            rel_paths = [
                line.strip().lstrip("./")
                for line in sys.stdin.read().splitlines()
                if line.strip()
            ]
        else:
            rel_paths = [
                line.strip().lstrip("./")
                for line in Path(args.files_from).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if line.strip()
            ]
        rel_paths = [p for p in rel_paths if is_in_scope(p)]
        binary_skipped = 0
        excluded = 0
        scanned = len(rel_paths)
        findings = scan_paths(root, rel_paths)
    else:
        scannable, binary, excluded_paths = tracked_text_files(root)
        rel_paths = scannable
        binary_skipped = len(binary)
        excluded = len(excluded_paths)
        scanned = len(scannable)
        findings = scan_paths(root, rel_paths)

    if args.json:
        payload = {
            "caliber": "git ls-files + is_in_scope",
            "scanned_text_files": scanned,
            "binary_skipped": binary_skipped,
            "out_of_scope": excluded,
            "f1_count": len(f1_findings(findings)),
            "f2_count": len(f2_findings(findings)),
            "findings": [f.as_dict() for f in findings],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            render_report(
                findings,
                scanned=scanned,
                binary_skipped=binary_skipped,
                excluded=excluded,
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
