"""SAFE-EXEC Wave 1 · 路径域判定与出站口接线（席 S-T-SAFE-1，2026-09-25）。

规格：`docs/design/safety-execution-engine-spec.md` §3（落点域三条硬规则）、
§9 攻击面 #3（路径穿越）、§11 Wave 1（``paths.check_sendable()`` 收口
``file_gateway._stage_path`` 的任意路径外发）、§12 G-5。裁定来源：用户第 16(4) 项
「必须在可控的容器内进行操作」+ 第 17 项「违规删除重要文件、非工作区文件要拦住」。

判据五腿（少一条本席不算交付）：

① 穿越/形态/名册样本表**逐条**被拒，原因码按表点名且铺开到 10 枚以上
   （防「全部塌成一枚兜底码」）；
② 正向样本放行（防「一律拒」假绿——真图库/卡片/生成物/暂存面都是既有功能）；
③ ``.env`` / ``*.sqlite3`` / ``settings/*.json`` 各一条必拒；
④ 活性锁：``file_gateway.py`` 取字节前**只有一处**判定调用（AST 数），生产全树
   不得出现第二份路径域判定（扫描器是纯函数，另有内存注毒一发证明它有牙）；
⑤ 注毒自证：摘掉 ``resolve()`` ⇒ 表内样本成批翻转；摘掉 ``casefold`` ⇒ 大小写样本
   翻转；清空禁触子串名册 ⇒ Cookie 文件被放行（证明拦它的确实是名册）。

全部用例只在 ``tmp_path`` 里造假冒根：**不读她的 ``.env``、不开任何 SQLite 库、
不依赖真实仓库目录结构**（禁触面用 tmp_path 里造的同名假文件证明被拒）。
"""

from __future__ import annotations

import ast
import io
import os
import re
import tokenize
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.core.safety_exec.paths import (
    DENY_REASONS,
    DOMAIN_FORBIDDEN,
    DOMAIN_OUTSIDE,
    DOMAIN_RUNTIME,
    DOMAIN_WORKSPACE,
    REVIEW_REASONS,
    VERDICT_ALLOWED,
    VERDICT_DENIED,
    VERDICT_NEEDS_REVIEW,
    PathDomainPolicy,
    build_policy,
)
from plugins.bot_unified_runtime.domains.transport.sender import file_gateway
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FileSource,
    FileTransferError,
    FileTransferGateway,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
GATEWAY_PY = PKG_ROOT / "domains" / "transport" / "sender" / "file_gateway.py"
PATHS_PY = PKG_ROOT / "domains" / "core" / "safety_exec" / "paths.py"
SAFETY_INIT_PY = PKG_ROOT / "domains" / "core" / "safety_exec" / "__init__.py"

#: 审计行里绝对不许出现的形态：盘符 + 任一分隔符。
DRIVE_FORM_RE = re.compile(r"[A-Za-z]:[\\/]")

#: 允许 import 路径域真身的消费点（新增即「第二通路」，要过主代理）。
#: 2026-09-26 主代理授权补登第二枚（S-16 收编波第①件）：``restricted_runner`` 是
#: **真消费**而非抄口径——写侧发布（``_forbidden_destination_reason``）与寻址/回读侧
#: （``resolve_existing``）各向 ``check_sendable()`` 问一次「禁触那一族」，判定零副本；
#: 活性锁见 ``tests/test_restricted_runner_live.py::test_runner_consumes_the_roster_in_two_places``。
ALLOWED_CONSUMERS = frozenset(
    {
        "plugins/bot_unified_runtime/domains/core/safety_exec/paths.py",
        "plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py",
        "plugins/bot_unified_runtime/domains/files/sender/restricted_runner.py",
    }
)


# ---------------------------------------------------------------------------
# 假根夹具：一棵与真身同形态的树
# （目录名按 docs/db-owners.md 与 config.py path_fields 取，不自己编）
# ---------------------------------------------------------------------------


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    workspace = tmp_path / "workspace"
    runtime_home = tmp_path / "ChatBot_Runtime"
    runtime_data = runtime_home / "data"
    for leaf in (
        workspace / "plugins",
        workspace / "docs",
        workspace / "personas" / "shorekeeper",
        runtime_data / "generated_files",
        runtime_data / "cards",
        runtime_data / "settings",
        runtime_data / "persona",
        runtime_data / "media_archive" / "照片",
        runtime_data / "downloads" / "incoming",
        runtime_home / "cache" / "pytest_x" / "basetemp",
        runtime_home / "scratch",
        runtime_home / "venv" / "Scripts",
        tmp_path / "outside" / "deep",
    ):
        leaf.mkdir(parents=True, exist_ok=True)

    (workspace / "docs" / "note.md").write_text("工作区里的普通文档", encoding="utf-8")
    (workspace / ".env").write_text("BOT_API_KEY=sk-not-a-real-key", encoding="utf-8")
    (workspace / "personas" / "shorekeeper" / "identity.md").write_text("人格源", encoding="utf-8")
    (runtime_data / "generated_files" / "media_ok.png").write_bytes(b"\x89PNG fake")
    (runtime_data / "generated_files" / "note.txt").write_text("生成物", encoding="utf-8")
    (runtime_data / "cards" / "usage_card.png").write_bytes(b"\x89PNG card")
    (runtime_data / "user_affinity.sqlite3").write_bytes(b"SQLite format 3\x00fake")
    (runtime_data / "user_affinity.sqlite3-wal").write_bytes(b"wal")
    (runtime_data / "settings" / "runtime_settings_shorekeeper.json").write_text(
        "{}", encoding="utf-8"
    )
    (runtime_data / "runtime_settings.json").write_text("{}", encoding="utf-8")
    (runtime_data / "platform_cookies.txt").write_text("fake cookie jar", encoding="utf-8")
    (runtime_data / "persona" / "守岸人_核心人格.md").write_text("人格副本", encoding="utf-8")
    (runtime_data / "media_archive" / "照片" / "IMG_0001.jpg").write_bytes(b"\xff\xd8\xff jpeg")
    (runtime_data / "knowledge_faiss.index").write_bytes(b"faiss index")
    (runtime_data / "downloads" / "incoming" / "clip.mp4").write_bytes(b"clip")
    (runtime_home / "cache" / "pytest_x" / "basetemp" / "report.txt").write_text(
        "暂存产物", encoding="utf-8"
    )
    (runtime_home / "scratch" / "draft.md").write_text("未登记子树", encoding="utf-8")
    (runtime_home / "venv" / "Scripts" / "python.exe").write_bytes(b"MZ")
    (tmp_path / "outside" / "win.ini").write_text("[fonts]", encoding="utf-8")
    (tmp_path / "outside" / "deep" / "important.txt").write_text("非工作区文件", encoding="utf-8")
    return {
        "tmp": tmp_path,
        "workspace": workspace,
        "runtime_home": runtime_home,
        "runtime_data": runtime_data,
        "outside": tmp_path / "outside",
    }


def _policy(roots: dict[str, Path]) -> PathDomainPolicy:
    return build_policy(
        workspace_root=roots["workspace"],
        runtime_data_root=roots["runtime_data"],
    )


@pytest.fixture
def policy(roots: dict[str, Path]) -> PathDomainPolicy:
    return _policy(roots)


@pytest.fixture
def wired_policy(roots: dict[str, Path]) -> Iterable[PathDomainPolicy]:
    """把假根接到**进程级缺省口**（``file_gateway`` 吃的就是这个口）。

    不替换判定函数本身（那样测的是替身）：只换根坐标，判定链
    ``check_sendable → default_policy() → PathDomainPolicy.check_sendable`` 全走生产路径。
    """
    active = _policy(roots)
    paths.set_default_policy(active)
    try:
        yield active
    finally:
        paths.set_default_policy(None)


# ---------------------------------------------------------------------------
# 样本表：① 拒绝面
# ---------------------------------------------------------------------------


def _denied_samples(roots: dict[str, Path]) -> list[tuple[str, str, str]]:
    rd = roots["runtime_data"]
    rh = roots["runtime_home"]
    ws = roots["workspace"]
    out = roots["outside"]
    gf = rd / "generated_files"
    gf_text = str(gf)
    return [
        # ---- 空引用 / 相对歧义（fail-closed：不猜锚点）----
        ("", paths.DenyReason.EMPTY_PATH, paths.DOMAIN_UNDETERMINED),
        ("   ", paths.DenyReason.EMPTY_PATH, paths.DOMAIN_UNDETERMINED),
        ("..\\..\\Windows\\win.ini", paths.DenyReason.RELATIVE_AMBIGUOUS, DOMAIN_UNDET),
        ("report.txt", paths.DenyReason.RELATIVE_AMBIGUOUS, DOMAIN_UNDET),
        ("docs/note.md", paths.DenyReason.RELATIVE_AMBIGUOUS, DOMAIN_UNDET),
        # ---- 工作区与运行数据域之外的绝对路径 ----
        ("C:/Windows/win.ini", paths.DenyReason.OUTSIDE_ALLOWED_ROOTS, DOMAIN_OUTSIDE),
        (str(out / "win.ini"), paths.DenyReason.OUTSIDE_ALLOWED_ROOTS, DOMAIN_OUTSIDE),
        (str(out / "deep" / "important.txt"), paths.DenyReason.OUTSIDE_ALLOWED_ROOTS, DOMAIN_OUTSIDE),
        # ---- `..` 穿越（绝对 / 混合分隔符 / 多余点）----
        (
            str(gf / ".." / ".." / ".." / "Windows" / "win.ini"),
            paths.DenyReason.TRAVERSAL_ESCAPE,
            DOMAIN_OUTSIDE,
        ),
        (
            str(ws / "docs" / ".." / ".." / ".." / ".." / "Windows" / "System32" / "config" / "SAM"),
            paths.DenyReason.TRAVERSAL_ESCAPE,
            DOMAIN_OUTSIDE,
        ),
        (
            gf_text + "/../../../../Windows/win.ini",
            paths.DenyReason.TRAVERSAL_ESCAPE,
            DOMAIN_OUTSIDE,
        ),
        (
            gf_text + "\\..\\..\\..\\..\\Windows\\win.ini",
            paths.DenyReason.TRAVERSAL_ESCAPE,
            DOMAIN_OUTSIDE,
        ),
        # ---- 纯点别名段（`...` 在 Win32 里等价 `..`，实测 Python 的 resolve()
        #      不折它 ⇒ 两侧解果不一致，一律按规避形态拒）----
        (
            gf_text + "/....//....//Windows/win.ini",
            paths.DenyReason.TRAILING_DOT_OR_SPACE,
            paths.DOMAIN_UNDETERMINED,
        ),
        (
            gf_text + "/.../.../Windows/win.ini",
            paths.DenyReason.TRAILING_DOT_OR_SPACE,
            paths.DOMAIN_UNDETERMINED,
        ),
        # ---- 百分号编码的分隔符与点 ----
        (
            "..%5c..%5cwindows%5cwin.ini",
            paths.DenyReason.ENCODED_SEPARATOR,
            paths.DOMAIN_UNDETERMINED,
        ),
        (str(gf / "%2e%2e%5cwindows"), paths.DenyReason.ENCODED_SEPARATOR, paths.DOMAIN_UNDETERMINED),
        (str(gf / "sub%2f..%2f..%2fwindows"), paths.DenyReason.ENCODED_SEPARATOR, paths.DOMAIN_UNDETERMINED),
        # ---- UNC 与设备命名空间 ----
        ("\\\\server\\share\\a.docx", paths.DenyReason.UNC_OR_DEVICE_PATH, DOMAIN_OUTSIDE),
        ("//server/share/a.docx", paths.DenyReason.UNC_OR_DEVICE_PATH, DOMAIN_OUTSIDE),
        ("\\\\?\\C:\\Windows\\win.ini", paths.DenyReason.UNC_OR_DEVICE_PATH, paths.DOMAIN_UNDETERMINED),
        ("\\\\.\\PhysicalDrive0", paths.DenyReason.UNC_OR_DEVICE_PATH, paths.DOMAIN_UNDETERMINED),
        # ---- NTFS 备用数据流 ----
        (str(gf / "note.txt:hidden"), paths.DenyReason.ALTERNATE_DATA_STREAM, paths.DOMAIN_UNDETERMINED),
        (
            str(rd / ".." / ".." / "somewhere:x"),
            paths.DenyReason.ALTERNATE_DATA_STREAM,
            paths.DOMAIN_UNDETERMINED,
        ),
        # ---- 8.3 短名形态（在登记根之下的相对尾段上判，理由见 paths._relative_tail）----
        (
            str(rd / "DATA~1" / "generated_files" / "media_ok.png"),
            paths.DenyReason.SHORT_NAME_FORM,
            paths.DOMAIN_UNDETERMINED,
        ),
        (
            str(ws / "PERSON~1" / "docs" / "note.md"),
            paths.DenyReason.SHORT_NAME_FORM,
            paths.DOMAIN_UNDETERMINED,
        ),
        # ---- 尾点 / 尾空格等价写法（目标不存在时 resolve() 折不平）----
        (str(gf / "ghost.png."), paths.DenyReason.TRAILING_DOT_OR_SPACE, paths.DOMAIN_UNDETERMINED),
        (str(gf / "ghost.txt "), paths.DenyReason.TRAILING_DOT_OR_SPACE, paths.DOMAIN_UNDETERMINED),
        # ---- ③ 三枚点名禁触类别 + 名册其余面 ----
        (str(ws / ".env"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rh / ".env.prod"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(gf / ".env"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rd / "user_affinity.sqlite3"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rd / "user_affinity.sqlite3-wal"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(gf / "dump.sqlite3"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (
            str(rd / "settings" / "runtime_settings_shorekeeper.json"),
            paths.DenyReason.FORBIDDEN_ZONE,
            DOMAIN_FORBIDDEN,
        ),
        (str(rd / "runtime_settings.json"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rd / "platform_cookies.txt"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rd / "knowledge_faiss.index"), paths.DenyReason.FORBIDDEN_FILE_CLASS, DOMAIN_FORBIDDEN),
        (str(rd / "persona" / "守岸人_核心人格.md"), paths.DenyReason.FORBIDDEN_ZONE, DOMAIN_FORBIDDEN),
        (str(ws / "personas" / "shorekeeper" / "identity.md"), paths.DenyReason.FORBIDDEN_ZONE, DOMAIN_FORBIDDEN),
        (str(rh / "venv" / "Scripts" / "python.exe"), paths.DenyReason.FORBIDDEN_ZONE, DOMAIN_FORBIDDEN),
    ]


DOMAIN_UNDET = paths.DOMAIN_UNDETERMINED


def _allowed_samples(roots: dict[str, Path]) -> list[tuple[str, str]]:
    rd = roots["runtime_data"]
    ws = roots["workspace"]
    rh = roots["runtime_home"]
    return [
        (str(ws / "docs" / "note.md"), DOMAIN_WORKSPACE),
        (str(rd / "generated_files" / "media_ok.png"), DOMAIN_RUNTIME),
        (str(rd / "cards" / "usage_card.png"), DOMAIN_RUNTIME),
        (str(rd / "downloads" / "incoming" / "clip.mp4"), DOMAIN_RUNTIME),
        # 中文目录名（真图库与归档树长这样）
        (str(rd / "media_archive" / "照片" / "IMG_0001.jpg"), DOMAIN_RUNTIME),
        # 运行数据暂存面：pytest basetemp / 渲染样张落点，既有功能不许断
        (str(rh / "cache" / "pytest_x" / "basetemp" / "report.txt"), DOMAIN_RUNTIME),
        # 大小写混写（Windows 不区分大小写，判定在 casefold 之后比）
        (str(rd / "GENERATED_FILES" / "MEDIA_OK.PNG"), DOMAIN_RUNTIME),
        (str(ws / "DOCS" / "NOTE.MD"), DOMAIN_WORKSPACE),
        # 根内的 `..` 折回：规范化后仍在根内 ⇒ 不许当穿越拒
        (str(rd / "generated_files" / ".." / "cards" / "usage_card.png"), DOMAIN_RUNTIME),
        (str(ws / "docs" / ".." / "docs" / "note.md"), DOMAIN_WORKSPACE),
        # 混合分隔符（正斜杠写的根内路径）
        (str(rd / "generated_files").replace("\\", "/") + "/media_ok.png", DOMAIN_RUNTIME),
        # 规范相对写法 `data/...`：与 scripts/runtime_paths.py 同口径
        ("data/generated_files/media_ok.png", DOMAIN_RUNTIME),
        ("./data/cards/usage_card.png", DOMAIN_RUNTIME),
    ]


# ---------------------------------------------------------------------------
# ① 拒绝面
# ---------------------------------------------------------------------------


def test_denied_samples_are_all_denied_with_expected_codes(policy: PathDomainPolicy, roots: dict[str, Path]) -> None:
    """穿越/形态/名册样本逐条被拒，原因码与落点域按表点名。"""
    rows = _denied_samples(roots)
    assert rows, "样本表不能为空（空表 = 本判据假绿）"
    seen_codes: set[str] = set()
    for sample, expected_code, expected_domain in rows:
        decision = policy.check_sendable(sample)
        assert decision.verdict == VERDICT_DENIED, (
            f"该拒未拒：{sample!r} → {decision.verdict}/{decision.reason_code}"
        )
        assert decision.reason_code == expected_code, (
            f"原因码不符：{sample!r} 期望 {expected_code} 实得 {decision.reason_code}"
        )
        assert decision.domain == expected_domain, f"落点域不符：{sample!r}"
        assert decision.reason_code in DENY_REASONS
        seen_codes.add(decision.reason_code)
    # 「原因码不同源」的可机检口径：这批样本至少铺开到 10 枚不同码。
    assert len(seen_codes) >= 10, f"原因码塌陷成兜底码了：{sorted(seen_codes)}"


def test_denied_audit_lines_carry_no_drive_letter(policy: PathDomainPolicy, roots: dict[str, Path]) -> None:
    """审计行只准出现打码形态与根相对尾段，不许出现盘符明文与真实根目录。"""
    workspace_text = str(roots["workspace"])
    data_text = str(roots["runtime_data"])
    for sample, _code, _domain in _denied_samples(roots):
        decision = policy.check_sendable(sample)
        line = decision.audit_line()
        assert not DRIVE_FORM_RE.search(line), f"审计行漏盘符：{line}"
        assert workspace_text not in line, f"审计行带出真实工作区根：{line}"
        assert data_text not in line, f"审计行带出真实运行数据根：{line}"
        assert decision.reason_code, "拒绝必须带原因码"
        text = paths.plain_reason(decision.reason_code)
        assert text and not text.startswith("未登记的路径域原因码"), f"原因码没人话说明：{decision}"


def root_unresolved_reason() -> str:
    """根取不到 ⇒ 相对写法必须报 root_unresolved（不是「猜一个根」）。"""
    bare = build_policy(workspace_root=None, runtime_data_root=None)
    decision = bare.check_sendable("data/generated_files/media_ok.png")
    assert decision.verdict == VERDICT_DENIED
    assert decision.reason_code == paths.DenyReason.ROOT_UNRESOLVED
    return decision.reason_code


def resolve_failure_reason(roots: dict[str, Path]) -> str:
    """``resolve()`` 拿不到结果时的原因码（假解析器，不碰真实文件系统）。"""
    original = paths._resolve_strict
    paths._resolve_strict = lambda _path: None  # type: ignore[assignment]
    try:
        decision = _policy(roots).check_sendable(
            str(roots["runtime_data"] / "generated_files" / "media_ok.png")
        )
    finally:
        paths._resolve_strict = original  # type: ignore[assignment]
    assert decision.verdict == VERDICT_DENIED
    assert decision.reason_code == paths.DenyReason.RESOLVE_FAILED, decision.reason_code
    return decision.reason_code


def test_every_registered_deny_reason_is_reachable(roots: dict[str, Path]) -> None:
    """每枚在册拒绝码都得有用例打到（防「码在册、判据空转」）。"""
    covered = {code for _sample, code, _domain in _denied_samples(roots)}
    covered |= {root_unresolved_reason(), resolve_failure_reason(roots)}
    assert covered == set(DENY_REASONS), (
        f"在册未测：{sorted(set(DENY_REASONS) - covered)}；"
        f"测了未在册：{sorted(covered - set(DENY_REASONS))}"
    )


def test_root_unresolved_policy_denies_everything(roots: dict[str, Path]) -> None:
    """三张根都给不出来 ⇒ 一律拒（fail-closed，不猜落点）。"""
    bare = build_policy(workspace_root=None, runtime_data_root=None)
    for sample in (
        str(roots["workspace"] / "docs" / "note.md"),
        "C:/Windows/win.ini",
        "data/x.png",
        "",
    ):
        assert bare.check_sendable(sample).verdict == VERDICT_DENIED, f"空根策略放行了 {sample!r}"


def test_resolve_landing_in_device_namespace_is_denied_with_honest_reason(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``resolve()`` 输出自己带 ``\\?\\`` 前缀 ⇒ 拒，且报设备码而非「根外」。

    本机 2026-09-26 实测（S-T-SAFE-1b 差分探针）：纯点段会让 GetFullPathName 把
    **根内**路径解成 ``\\\\?\\C:\\…`` 形态。这一串拿去做 containment，
    ``\\\\?\\c:\\`` 与 ``c:\\`` 前缀对不上，只会得到「结论是拒、理由说谎」的
    ``outside_allowed_roots``；而 ``\\?\\`` 命名空间停用 ``.``/``..``/尾点归一化，
    剥前缀重解又**会改落点** ⇒ 唯一诚实处置 = 拒 + ``unc_or_device_path``。
    用假解析器钉形态，不赌宿主当天的点号折叠行为。
    """
    sample = str(roots["runtime_data"] / "generated_files" / "media_ok.png")
    device_form = Path("\\\\?\\" + sample)
    assert str(device_form).startswith("\\\\?\\")
    active = _policy(roots)  # 先按真解析器建根，再把解析器换成设备形态（build_policy
    # 的 _as_root 同吃 _resolve_strict，先换会把根自己污染成设备串）。
    monkeypatch.setattr(paths, "_resolve_strict", lambda _value: device_form)
    decision = active.check_sendable(sample)
    assert decision.verdict == VERDICT_DENIED
    assert decision.reason_code == paths.DenyReason.UNC_OR_DEVICE_PATH, decision.reason_code
    assert not DRIVE_FORM_RE.search(decision.audit_line()), decision.audit_line()


# ---------------------------------------------------------------------------
# ② 放行面（正向锁：没这条，上面的红可以是「一律拒」换来的）
# ---------------------------------------------------------------------------


def test_allowed_samples_pass_and_keep_existing_media_working(
    policy: PathDomainPolicy, roots: dict[str, Path]
) -> None:
    rows = _allowed_samples(roots)
    assert rows
    for sample, expected_domain in rows:
        decision = policy.check_sendable(sample)
        assert decision.verdict == VERDICT_ALLOWED, (
            f"该放未放（把既有功能一并拒掉的反向坑）：{sample!r} → "
            f"{decision.verdict}/{decision.reason_code}"
        )
        assert decision.domain == expected_domain
        assert decision.reason_code == ""
        assert decision.target_name


def test_host_side_short_name_in_root_prefix_is_not_a_deny_reason(tmp_path: Path) -> None:
    """宿主把根前缀写成 8.3 形态时不许误杀（本机 %TEMP% 实测就是 ``LANCYC~1``）。

    并行席 S-T-FILE-2 于 23:38 现算到的那条误判即此：形态判据只看**登记根之下**的
    相对尾段；根前缀以内的写法归宿主，由 resolve() 折平后按真实落点裁决。
    """
    odd_workspace = tmp_path / "LANCYC~1" / "workspace"
    (odd_workspace / "docs").mkdir(parents=True)
    note = odd_workspace / "docs" / "note.md"
    note.write_text("宿主短名前缀下的普通文档", encoding="utf-8")
    odd_data = tmp_path / "PROGRA~1" / "ChatBot_Runtime" / "data"
    media = odd_data / "generated_files"
    media.mkdir(parents=True)
    (media / "ok.png").write_bytes(b"png")
    active = build_policy(workspace_root=odd_workspace, runtime_data_root=odd_data)
    assert active.check_sendable(str(note)).verdict == VERDICT_ALLOWED
    assert active.check_sendable(str(media / "ok.png")).verdict == VERDICT_ALLOWED


def test_alias_forms_are_denied_even_when_they_fold_to_an_allowed_target(
    policy: PathDomainPolicy, roots: dict[str, Path]
) -> None:
    """钉住「别名形态一律拒」：即使 ``resolve()`` 今天会把它折成一个允许文件。

    实测本机：``<存在的文件>.`` 会被 resolve() 折回真身、``<名字> `` （尾空格）也是
    ⇒ 若只按解析结果判，同一份规避写法今天允许、明天（目标不存在时）拒绝，
    而协议端/杀软/备份那侧的解析器不一定跟着折。判定面一律按**给进来的写法**拒。
    """
    real = roots["runtime_data"] / "generated_files" / "media_ok.png"
    for alias in (f"{real}.", f"{real} ", f"{real}.."):
        decision = policy.check_sendable(alias)
        assert decision.verdict == VERDICT_DENIED, f"别名写法被放行：{alias!r} → {decision}"
        assert decision.reason_code == paths.DenyReason.TRAILING_DOT_OR_SPACE, decision
    # 对照组：同一文件的正规写法必须放行（否则就成了「一律拒」）。
    assert policy.check_sendable(str(real)).verdict == VERDICT_ALLOWED


# ---------------------------------------------------------------------------
# 第三态：needs_review（今天记账放行，Wave 2 有同意回路后收紧）
# ---------------------------------------------------------------------------


def test_unregistered_runtime_subtree_is_needs_review_not_silently_allowed(
    policy: PathDomainPolicy, roots: dict[str, Path]
) -> None:
    decision = policy.check_sendable(str(roots["runtime_home"] / "scratch" / "draft.md"))
    assert decision.verdict == VERDICT_NEEDS_REVIEW
    assert decision.reason_code == paths.ReviewReason.UNREGISTERED_RUNTIME_SUBTREE
    assert decision.reason_code in REVIEW_REASONS


def test_needs_review_reasons_never_escape_the_registry() -> None:
    assert set(REVIEW_REASONS) == {
        paths.ReviewReason.UNREGISTERED_RUNTIME_SUBTREE,
        paths.ReviewReason.LINK_IN_PATH,
    }
    for code in REVIEW_REASONS:
        text = paths.plain_reason(code)
        assert text and not text.startswith("未登记的路径域原因码")


def test_three_states_are_mutually_exclusive(policy: PathDomainPolicy, roots: dict[str, Path]) -> None:
    """三态互斥且必带（或不带）原因码，不许出现脏返回值。"""
    seen: set[str] = set()
    for sample, _code, _domain in _denied_samples(roots):
        seen.add(policy.check_sendable(sample).verdict)
    for sample, _domain in _allowed_samples(roots):
        seen.add(policy.check_sendable(sample).verdict)
    seen.add(policy.check_sendable(str(roots["runtime_home"] / "scratch" / "draft.md")).verdict)
    assert seen == {VERDICT_DENIED, VERDICT_ALLOWED, VERDICT_NEEDS_REVIEW}
    for sample, _code, _domain in _denied_samples(roots):
        decision = policy.check_sendable(sample)
        assert (decision.reason_code == "") is (decision.verdict != VERDICT_DENIED)


# ---------------------------------------------------------------------------
# ⑤ 注毒自证（三发，逐发还原由 monkeypatch 负责）
# ---------------------------------------------------------------------------

_POISON_PROBES = (
    "RT|generated_files|..|..|..|Windows|win.ini",
    "RT|GENERATED_FILES|MEDIA_OK.PNG",
    "RT|generated_files|..|cards|usage_card.png",
    "RT|DATA~1|generated_files|media_ok.png",
)


def _probe_paths(roots: dict[str, Path]) -> list[str]:
    return [
    sample.replace("RT|", str(roots["runtime_data"]) + os.sep).replace("|", os.sep)
    for sample in _POISON_PROBES
    ]


def test_poisoning_resolve_flips_the_containment_locks(
    policy: PathDomainPolicy, roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """摘掉 ``resolve()`` ⇒ 至少一枚 `..` 穿越样本从「拒」翻成「放行」。

    这条是本席的命门判据：它证明拒绝**来自规范化后的落点**，不是字符串里恰好有
    `..`。翻转方向必须点名 denied→allowed（反方向翻转变红只是判据换法，不算杀到）。
    """
    probes = _probe_paths(roots)
    before = [(sample, policy.check_sendable(sample)) for sample in probes]
    assert any(row[1].verdict == VERDICT_DENIED for row in before)
    monkeypatch.setattr(paths, "_resolve_strict", lambda value: Path(str(value)))
    flipped: list[str] = []
    for sample, first in before:
        after = policy.check_sendable(sample)
        if (first.verdict, first.reason_code) != (after.verdict, after.reason_code):
            flipped.append(
                f"{sample}: {first.verdict}/{first.reason_code} → {after.verdict}/{after.reason_code}"
            )
    assert flipped, "摘掉 resolve() 后无任何行为翻转 ⇒ 判据不吃规范化"
    escapes = [row for row in flipped if "denied/traversal_escape → allowed" in row]
    assert escapes, f"摘掉 resolve() 未放走穿越样本（锁没牙）：{flipped}"


def test_casefold_lock_has_teeth(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """大小写这条腿有牙：**假设**解析器不折大小写时，比对的 casefold 必须顶上。

    Windows 的 ``resolve()`` 实测会把**已存在**的段折成真实大小写（第一层保护），
    所以这里先把解析器换成恒等（模拟不折大小写的宿主/未来重构），再把根前缀写成
    大小写变体：有 casefold ⇒ 仍认得是同一个根；无 casefold ⇒ 认不出、当成根外拒。
    差异存在 ⇒ 第二层保护不是空锁。
    """
    monkeypatch.setattr(paths, "_resolve_strict", lambda value: Path(str(value)))
    data = str(roots["runtime_data"])
    sample = data.upper() + str(Path(data) / "generated_files" / "media_ok.png")[len(data) :]
    active = _policy(roots)
    assert active.check_sendable(sample).verdict == VERDICT_ALLOWED, "casefold 未生效（正向丢功能）"
    monkeypatch.setattr(paths, "_norm_key", lambda path: tuple(map(str, path.parts)))
    assert active.check_sendable(sample).verdict == VERDICT_DENIED, "摘掉 casefold 仍放行 ⇒ 大小写判据是空锁"


def test_roster_substring_lock_has_teeth(roots: dict[str, Path]) -> None:
    """清空禁触子串名册 ⇒ Cookie 文件被放行 ⇒ 证明拦它的确实是那张名册。"""
    cookie = str(roots["runtime_data"] / "platform_cookies.txt")
    assert _policy(roots).check_sendable(cookie).reason_code == paths.DenyReason.FORBIDDEN_FILE_CLASS
    base = _policy(roots)
    gutted = PathDomainPolicy(
        workspace_root=base.workspace_root,
        runtime_data_root=base.runtime_data_root,
        runtime_home=base.runtime_home,
        readable_roots=base.readable_roots,
        forbidden_name_substrings=frozenset(),
    )
    assert gutted.check_sendable(cookie).verdict != VERDICT_DENIED


# ---------------------------------------------------------------------------
# 出站口接线：file_gateway 取字节前的那一处判定
# ---------------------------------------------------------------------------


def _gateway(roots: dict[str, Path]) -> FileTransferGateway:
    return FileTransferGateway(staging_dir=roots["tmp"] / "staging")


def test_gateway_sends_allowed_media_and_blocks_outside(
    roots: dict[str, Path], wired_policy: PathDomainPolicy
) -> None:
    gateway = _gateway(roots)
    ok = roots["runtime_data"] / "generated_files" / "media_ok.png"
    ticket = gateway.stage(FileSource(source_kind="path", path=str(ok)), request_id="r1")
    assert ticket.local_path is not None and ticket.size == ok.stat().st_size

    cases = [
        ("宿主绝对路径", "C:/Windows/win.ini"),
        # 样本必须指向**真实存在**的文件：既有语义里 is_file() 在前，不存在的落点
        # 先报 missing_file（另一条测试钉住），本判据要测的是「存在也不许发」。
        # 穿越的终点也必须在两张根之外——落到工作区里就不算逃逸（对照组见下方）。
        (
            "根外穿越到非工作区文件",
            str(
                roots["runtime_data"]
                / "generated_files"
                / ".."
                / ".."
                / ".."
                / "outside"
                / "deep"
                / "important.txt"
            ),
        ),
        (
            "混合分隔符穿越到非工作区文件",
            str(roots["runtime_data"] / "generated_files")
            + "\\..\\..\\..\\outside\\win.ini",
        ),
        ("工作区 .env", str(roots["workspace"] / ".env")),
        ("库文件", str(roots["runtime_data"] / "user_affinity.sqlite3")),
        ("运行期设置 json", str(roots["runtime_data"] / "settings" / "runtime_settings_shorekeeper.json")),
        ("Cookie 罐", str(roots["runtime_data"] / "platform_cookies.txt")),
        ("人格副本", str(roots["runtime_data"] / "persona" / "守岸人_核心人格.md")),
        ("非工作区文件", str(roots["outside"] / "deep" / "important.txt")),
    ]
    for label, sample in cases:
        with pytest.raises(FileTransferError) as caught:
            gateway.stage(FileSource(source_kind="path", path=sample), request_id=label)
        assert caught.value.kind == "path_domain_denied", f"{label} 未拦或误分类：{caught.value.kind}"


def test_gateway_needs_review_is_logged_not_swallowed(
    roots: dict[str, Path],
    wired_policy: PathDomainPolicy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """第三态今天放行，但必须留账（无账 ⇒ Wave 2 无从收紧）。"""
    scratch = roots["runtime_home"] / "scratch" / "draft.md"
    with caplog.at_level("WARNING", logger=file_gateway.__name__):
        ticket = _gateway(roots).stage(FileSource(source_kind="path", path=str(scratch)), request_id="r5")
    assert ticket.local_path is not None
    lines = [rec.getMessage() for rec in caplog.records if "needs_review" in rec.getMessage()]
    assert lines, "第三态没记账"
    assert not DRIVE_FORM_RE.search(lines[0]), lines[0]


def test_gateway_denied_line_is_masked(
    roots: dict[str, Path],
    wired_policy: PathDomainPolicy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """拒绝也必须留痕，且痕里无盘符、无真实根目录。"""
    with (
        caplog.at_level("WARNING", logger=file_gateway.__name__),
        pytest.raises(FileTransferError),
    ):
        _gateway(roots).stage(
            FileSource(source_kind="path", path=str(roots["workspace"] / ".env")),
            request_id="r7",
        )
    lines = [rec.getMessage() for rec in caplog.records if "denied" in rec.getMessage()]
    assert lines, "拒绝没留痕"
    assert not DRIVE_FORM_RE.search(lines[0]), lines[0]
    assert str(roots["workspace"]) not in lines[0]


def test_gateway_missing_file_classification_is_unchanged(
    roots: dict[str, Path], wired_policy: PathDomainPolicy
) -> None:
    """既有语义不许被我改动：不存在的文件仍报 missing_file。"""
    with pytest.raises(FileTransferError) as caught:
        _gateway(roots).stage(
            FileSource(source_kind="path", path=str(roots["outside"] / "ghost.bin")),
            request_id="r6",
        )
    assert caught.value.kind == "missing_file"


def test_bytes_and_url_legs_are_untouched_by_the_path_gate(
    roots: dict[str, Path], wired_policy: PathDomainPolicy
) -> None:
    """判定只加在 path 腿（最小改动）：bytes 腿仍照常落 staging。"""
    ticket = _gateway(roots).stage(FileSource(source_kind="bytes", data=b"\x00\x01", name="b.bin"))
    assert ticket.local_path is not None
    assert ticket.local_path.read_bytes() == b"\x00\x01"


# ---------------------------------------------------------------------------
# ④ 活性锁：一处判定 + 全树第二真身
# ---------------------------------------------------------------------------


def _call_names(node: ast.AST) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            func = item.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if isinstance(name, str):
                found.append((name, item.lineno))
    return found


def _stage_path_function(tree: ast.AST) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_stage_path":
            return node
    raise AssertionError("找不到 _stage_path（改名要同步本判据）")


def test_file_gateway_has_exactly_one_sendable_check() -> None:
    tree = ast.parse(GATEWAY_PY.read_text(encoding="utf-8"))
    calls = [(name, line) for name, line in _call_names(tree) if name == "check_sendable"]
    assert len(calls) == 1, f"出站判定必须只有一处，实得 {calls}"
    stage = _stage_path_function(tree)
    inner = [name for name, _line in _call_names(stage) if name == "check_sendable"]
    assert inner == ["check_sendable"], "唯一那处判定必须落在 _stage_path 内"
    order = {
        name: line
        for name, line in _call_names(stage)
        if name in {"check_sendable", "_sha256_of_file"}
    }
    assert order["check_sendable"] < order.get("_sha256_of_file", 1 << 30), (
        f"判定必须早于取字节（sha 摘要即第一次读）：{order}"
    )


def _code_only(text: str) -> str:
    """剥掉注释与字符串字面量，只留代码骨架（不把「提到」当「实现」）。"""
    out: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(token.string)
    except (tokenize.TokenError, IndentationError):  # pragma: no cover
        return text
    return " ".join(out)


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


SECOND_TRUTH_RE = re.compile(r"^\s*(?:async\s+)?def\s+check_sendable\b", re.MULTILINE)
#: 原因码字面量：出现第二处＝有人自己抄了一份判定口径。
SECOND_TRUTH_CODES = (
    "traversal_escape",
    "outside_allowed_roots",
    "forbidden_file_class",
    "forbidden_zone",
    "unregistered_runtime_subtree",
)
#: 名册哨兵常量名：出现第二处＝第二张禁触名册。
SECOND_TRUTH_NAMES = ("_FORBIDDEN_DIR_NAMES", "_RUNTIME_READABLE_SUBTREES")


def _non_docstring_strings(tree: ast.AST) -> list[str]:
    """收集代码里的字符串常量，但**跳过各处 docstring**（说明文字不算实现）。"""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def _truth_source_imports(tree: ast.AST) -> bool:
    """这份代码有没有真的把判定真身 import 进来（`from … import X` 的模块名要精确）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.endswith("safety_exec.paths") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("safety_exec.paths"):
                return True
            if module.endswith("safety_exec") and any(
                alias.name == "paths" for alias in node.names
            ):
                return True
    return False


def _second_truth_scan(sources: Iterable[tuple[str, str]]) -> list[str]:
    """纯函数扫描器：找出 ``safety_exec.paths`` 之外的第二真身/第二张名册。

    三条判据（宁可窄、不可假阴）：① 只准一处 ``def check_sendable``；② 原因码
    字面量（非 docstring 位置）与名册哨兵常量只能住在真身里；③ 真 import 判定
    入口的只准是登记消费点。注释与文档串里**提**到这些名字不算副本（并行席就是
    在文档串里留接线说明的，把它们当违规会误伤）。
    """
    offenders: list[str] = []
    for rel, text in sources:
        norm = rel.replace("\\", "/")
        if norm.endswith("domains/core/safety_exec/paths.py"):
            continue
        tree = ast.parse(text)
        skeleton = _code_only(text)
        literals = _non_docstring_strings(tree)
        problems: list[str] = []
        if SECOND_TRUTH_RE.search(skeleton):
            problems.append("def check_sendable")
        problems.extend(code for code in SECOND_TRUTH_CODES if any(code in item for item in literals))
        problems.extend(name for name in SECOND_TRUTH_NAMES if name in skeleton)
        if _truth_source_imports(tree) and norm not in ALLOWED_CONSUMERS:
            problems.append("import safety_exec.paths")
        if problems:
            offenders.append(f"{norm}: {sorted(set(problems))}")
    return offenders


def test_no_second_path_domain_implementation_in_production() -> None:
    sources = [(str(p.relative_to(REPO_ROOT)), p.read_text(encoding="utf-8")) for p in PKG_ROOT.rglob("*.py")]
    assert sources, "扫描面为空 = 本判据假绿"
    offenders = _second_truth_scan(sources)
    assert offenders == [], "路径域判定出现第二真身/第二张名册：" + "; ".join(offenders)


def test_second_implementation_scan_has_teeth() -> None:
    """注毒自证：内存里造四发毒件，该抓的三个抓住、该放过的放过（否则判据是空锁
    或误伤）。第五发是「只在文档串与注释里提到」的并行席形态，必须**不算**副本。"""
    poisoned = [
        (
            "plugins/x/domains/core/safety_exec/paths.py",
            "def check_sendable(p):\n    return 'outside_allowed_roots'\n",
        ),
        (
            "plugins/x/domains/files/capabilities/evil.py",
            (
                "REASONS = {'traversal_escape', 'outside_allowed_roots'}\n"
                "from plugins.bot_unified_runtime.domains.core.safety_exec.paths import check_sendable\n"
                "_NAMES = _FORBIDDEN_DIR_NAMES\n"
            ),
        ),
        (
            "plugins/x/domains/transport/sender/copycat.py",
            "def check_sendable(p):\n    return True\n",
        ),
        (
            "plugins/x/domains/files/sender/alias_import.py",
            (
                "from plugins.bot_unified_runtime.domains.core.safety_exec import paths\n\n\n"
                "def f(p):\n    return paths.check_sendable(p)\n"
            ),
        ),
        (
            # 文档串 + 注释里提到 ⇒ 不算副本
            "plugins/x/domains/files/sender/restricted_runner.py",
            (
                '"""提到 paths.check_sendable() 与 traversal_escape 的接线说明"""\n'
                "# outside_allowed_roots\nx = 1\n"
            ),
        ),
    ]
    offenders = _second_truth_scan(poisoned)
    assert offenders == [
        (
            "plugins/x/domains/files/capabilities/evil.py: ['_FORBIDDEN_DIR_NAMES', "
            "'import safety_exec.paths', 'outside_allowed_roots', 'traversal_escape']"
        ),
        "plugins/x/domains/transport/sender/copycat.py: ['def check_sendable']",
        "plugins/x/domains/files/sender/alias_import.py: ['import safety_exec.paths']",
    ], offenders


def test_only_the_registered_consumer_imports_the_truth_source() -> None:
    consumers: list[str] = []
    for path in PKG_ROOT.rglob("*.py"):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if rel.endswith("domains/core/safety_exec/paths.py"):
            continue
        try:
            modules = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:  # pragma: no cover
            continue
        if any(module.endswith("safety_exec.paths") for module in modules):
            consumers.append(rel)
    assert consumers == [
        "plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py"
    ], f"路径域真身的 import 消费点必须唯一，实得 {consumers}"


def test_package_init_does_not_import_siblings() -> None:
    """``safety_exec/__init__.py`` 不许 import 兄弟件：并行席位落地前会整包炸。"""
    tree = ast.parse(SAFETY_INIT_PY.read_text(encoding="utf-8"))
    nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert nodes == [], f"包 __init__ 里出现了 import：{_imported_modules(tree)}"


def test_truth_source_never_touches_bytes_or_deletes() -> None:
    """判定件只判不读、绝不删：``paths.py`` 里不许出现读字节/写/删除/改名的调用。"""
    tree = ast.parse(PATHS_PY.read_text(encoding="utf-8"))
    forbidden_calls = {
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "open",
        "unlink",
        "rmtree",
        "remove",
        "rename",
        "mkdir",
        "removedirs",
        "truncate",
    }
    hits = sorted({name for name, _line in _call_names(tree) if name in forbidden_calls})
    assert hits == [], f"路径域判定不该触碰字节或删除：{hits}"
    text = PATHS_PY.read_text(encoding="utf-8")
    assert "redact_local_secrets" in text, "打码必须走中央件，不自建第二套"


# ---------------------------------------------------------------------------
# 缺省根登记（真身来源核对）与打码
# ---------------------------------------------------------------------------


def test_default_policy_roots_are_derived_from_runtime_paths() -> None:
    """缺省根必须来自 scripts/runtime_paths.py，不许在这里编目录名。"""
    from scripts.runtime_paths import runtime_data_dir

    active = paths.build_default_policy()
    assert active.runtime_data_root == Path(str(runtime_data_dir())).resolve()
    assert active.runtime_home == active.runtime_data_root.parent
    assert active.workspace_root is not None and active.workspace_root.is_dir()
    labels = [label for label, _root in active.readable_roots]
    assert "workspace" in labels and "runtime" in labels
    assert "runtimewrap:cache" in labels, "运行数据根的暂存面必须在册（样张/basetemp 落点）"
    assert "runtime:generated_files" in labels and "runtime:media_archive" in labels


def test_default_policy_denies_host_files_and_allows_repo_text() -> None:
    """用真身根跑一遍：宿主系统文件拒、仓库内普通文件放行。

    她机器上的真 ``.env`` 与真库文件在这里**只被判定、从不被读**（上一条测试即锁）。
    """
    active = paths.build_default_policy()
    outside = active.check_sendable("C:/Windows/win.ini")
    assert outside.verdict == VERDICT_DENIED
    assert outside.reason_code == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS
    inside = active.check_sendable(str(PKG_ROOT / "__init__.py"))
    assert inside.verdict == VERDICT_ALLOWED, inside
    ws = active.workspace_root
    assert ws is not None
    blocked = active.check_sendable(str(ws / ".env"))
    assert blocked.verdict == VERDICT_DENIED
    assert blocked.reason_code == paths.DenyReason.FORBIDDEN_FILE_CLASS


def test_masking_falls_back_to_opaque_when_central_piece_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中央打码件取不到时整串丢弃，绝不退回「原文照写」。"""
    import builtins

    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.endswith("plain_text"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert paths._mask_path_text("C:/Windows/win.ini") == paths._OPAQUE_PATH_MASK


def test_masking_drops_forms_the_central_piece_leaves_alone() -> None:
    """中央件只认盘符形态；UNC 与家目录波浪号由本件的后置断言打掉（实测补漏）。"""
    unc = paths._mask_path_text("\\\\server\\share\\x")
    assert unc and "server" not in unc
    assert paths._mask_path_text("~/secrets/id_rsa") == paths._OPAQUE_PATH_MASK
    assert "win.ini" not in paths._mask_path_text("C:/Windows/win.ini")


def test_policy_roots_report_is_masked(roots: dict[str, Path]) -> None:
    """观测口只出打码值与标签，不出盘符（诊断卡可直接吃这一份）。"""
    report = paths.policy_roots(_policy(roots))
    assert not DRIVE_FORM_RE.search(str(report))
    assert "workspace" in report["readable_root_labels"]


# ---------------------------------------------------------------------------
# 链接与 junction
# ---------------------------------------------------------------------------


def _make_link(link: Path, target: Path) -> bool:
    """尽力建真链接（junction 优先，退到 symlink）；宿主拒绝时返回 False。"""
    try:
        import _winapi

        factory = getattr(_winapi, "CreateJunction", None)
        if callable(factory):
            factory(str(target), str(link))
            return True
    except (ImportError, OSError):
        pass
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except OSError:
        return False


def _link_components_hit(policy: PathDomainPolicy, path: Path) -> bool:
    return paths._has_link_component(path)


def test_link_escaping_allowed_root_is_denied(
    policy: PathDomainPolicy, roots: dict[str, Path]
) -> None:
    """链接/junction 指向根外 ⇒ 拒。两条腿：真件（能建就建）+ 模拟解析（永远跑）。

    本机实测：普通进程 ``os.symlink`` 被 ``WinError 1314`` 拒，junction 视机器状态而定
    ⇒ 模拟腿保证判据不吃宿主权限，真件腿在有权限的机器上补一次实证。
    """
    outside_target = roots["outside"] / "deep"
    link = roots["runtime_data"] / "generated_files" / "jn"
    made = _make_link(link, outside_target)
    try:
        if made:
            decision = policy.check_sendable(str(link / "important.txt"))
            assert decision.verdict == VERDICT_DENIED, f"真链接逃逸被放行：{decision}"
            assert _link_components_hit(policy, link) is True
    finally:
        if made:
            os.rmdir(link)
            assert outside_target.exists(), "删链接不许碰到指向的真实目录"
    escaping = outside_target / "important.txt"
    original = paths._resolve_strict
    paths._resolve_strict = lambda _value: escaping  # type: ignore[assignment]
    try:
        decision = policy.check_sendable(str(link / "important.txt"))
    finally:
        paths._resolve_strict = original  # type: ignore[assignment]
    assert decision.verdict == VERDICT_DENIED, f"模拟链接逃逸被放行：{decision}"
    assert decision.reason_code == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS


def test_link_staying_inside_allowed_root_is_needs_review(
    policy: PathDomainPolicy, roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """链接指向根内 ⇒ 第三态：今天记账放行，Wave 2 有同意回路后收紧。"""
    target = roots["runtime_data"] / "cards" / "usage_card.png"
    candidate = roots["runtime_data"] / "generated_files" / "jn2" / "usage_card.png"
    monkeypatch.setattr(paths, "_has_link_component", lambda _path: True)
    original = paths._resolve_strict
    paths._resolve_strict = lambda _value: target  # type: ignore[assignment]
    try:
        decision = policy.check_sendable(str(candidate))
    finally:
        paths._resolve_strict = original  # type: ignore[assignment]
    assert decision.verdict == VERDICT_NEEDS_REVIEW, decision
    assert decision.reason_code == paths.ReviewReason.LINK_IN_PATH


def test_link_component_probe_is_fail_closed(
    policy: PathDomainPolicy, roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """链接探测本身抛异常 ⇒ 当可疑（needs_review），不当「没有链接」。"""
    ok = str(roots["runtime_data"] / "generated_files" / "media_ok.png")
    assert policy.check_sendable(ok).verdict == VERDICT_ALLOWED

    def _raise(_self: Path) -> bool:
        raise OSError("probe refused")

    monkeypatch.setattr(Path, "is_symlink", _raise)
    decision = policy.check_sendable(ok)
    assert decision.verdict == VERDICT_NEEDS_REVIEW
    assert decision.reason_code == paths.ReviewReason.LINK_IN_PATH


def test_plain_reason_never_invents_an_explanation_for_unknown_codes() -> None:
    """认不出的代号只点名、不编解释（与运行时告警同一口径）。"""
    assert paths.plain_reason("totally_unknown_code") == "未登记的路径域原因码 totally_unknown_code"
    assert paths.plain_reason("") == "未给出原因码"
    for code in DENY_REASONS:
        text = paths.plain_reason(code)
        assert text and not text.startswith("未登记")


def test_registry_and_reason_table_stay_in_step() -> None:
    """原因码登记表与码集不许漂移（加码不写人话 = 诊断卡上要出空说明）。"""
    assert set(paths.REASON_PLAIN_TEXT) == set(DENY_REASONS) | set(REVIEW_REASONS)
