"""受限写盘运行器（需求 16(2)(3) / 17）的回归锁。

四组判据（简报§3 逐条对应）：

① 白名单外落点被拒（含 ``..`` 穿越样本）→ 本件第二、三组；
② 超限被拒且不半途写（目的地连临时件都不出现）→ 第四组；
③④（三通道对齐出站助手那两组）已随 ``build_aligned_file_outbound`` **删优于接**
   出账（2026-09-26 S-FILES-LAND，判据与回滚点见本文件第⑧节墓碑）；邮件/TG/QQ
   三腿行为的现役锁在 ``tests/test_file_outbound_channels.py`` 与
   ``tests/test_file_gateway_phase1.py``；
⑤ 「创建成功 + 未发生任何执行」→ 第七组；
⑥ 能力层零直写原语、运行器零执行原语（AST 面）→ 第八组。

全部离线、零网络、零真实目录：落点只出现在 pytest 的 ``tmp_path`` 里。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.files.capabilities import file_exchange as fx
from plugins.bot_unified_runtime.domains.files.capabilities.file_exchange import (
    _CODE_EXECUTION_ENABLED,
    create_document_file,
    export_document,
    revise_document_file,
    run_code_debug,
)
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr
from plugins.bot_unified_runtime.domains.media.digest import media_digest

_DRIVE_FORM_RE = re.compile(r"[A-Za-z]:[\\/]")
_MARKDOWN = "# 报告\n\n## 数据\n\n- 要点\n\n正文一段。\n"


# ---------------------------------------------------------------------------
# 夹具与助手


def _policy(root: Path, **kwargs: object) -> rr.WritePolicy:
    return rr.policy_for_roots([root], **kwargs)  # type: ignore[arg-type]


def _staging(tmp_path: Path) -> dict[str, Path]:
    """把暂存位收进 tmp_path：测试绝不在源码树留中间件。"""
    staging = tmp_path / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    return {"staging_dir": staging}


def _create(tmp_path: Path, root: Path, ref: str, data: bytes, **kwargs: object):
    """``create_bytes`` 的测试便捷口（策略根 = ``root``，暂存位 = ``tmp_path``）。"""
    return rr.create_bytes(
        ref,
        data,
        policy=_policy(root, **kwargs),
        **_staging(tmp_path),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# ① fail-closed：拿不到白名单＝一律不写


@pytest.mark.parametrize(
    ("verb", "call"),
    [
        (
            "create",
            lambda ref, data, policy, sd: rr.create_bytes(
                ref, data, policy=policy, staging_dir=sd
            ),
        ),
        (
            "replace",
            lambda ref, data, policy, sd: rr.replace_bytes(
                ref, data, policy=policy, staging_dir=sd
            ),
        ),
        (
            "create_or_replace",
            lambda ref, data, policy, sd: rr.write_document(
                ref, data, policy=policy, staging_dir=sd
            ),
        ),
    ],
)
def test_no_whitelist_denies_every_verb_with_its_own_code(tmp_path, verb, call) -> None:
    """空根 ⇒ 三个动词全部 **恰好** 拿到 ``no_whitelist``。

    断言精确代号而非「只要被拒」：把白名单判据拆掉时这里会换成别的代号（或干脆
    写成功），注毒必红——简报要求的「去掉白名单判据」那一发就落在这条上。
    """
    root = tmp_path / "somewhere"
    outcome = call("note.md", b"# hi\n", rr.WritePolicy(), tmp_path / "_staging")
    assert outcome.ok is False
    assert outcome.reason_code == rr.DenyCode.NO_WHITELIST, verb
    assert outcome.path is None
    assert not root.exists()
    assert "不落盘" in outcome.error_message()


def test_export_document_without_whitelist_reports_plain_reason(tmp_path) -> None:
    path, error = export_document(
        _MARKDOWN, "md", tmp_path / "out", title="主题", policy=rr.WritePolicy()
    )
    assert path == Path()
    assert error == rr.plain_reason(rr.DenyCode.NO_WHITELIST)
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# ② 白名单外落点 / 穿越样本


@pytest.mark.parametrize(
    ("ref", "expected_codes"),
    [
        ("../escape.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("notes/../../escape.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("..\\escape.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("/etc/passwd.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        # 绝对盘符写法不属「相对落点」词汇（本件只认「根 + 段序列」）。
        ("C:\\Windows\\evil.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("C:/Windows/evil.md", {rr.DenyCode.TRAVERSAL_DENIED}),
        # 编码分隔符形态（``%2f`` 过不了段形态复查）。
        ("a%2fb.md", {rr.DenyCode.BAD_NAME}),
        # 三点串按「含 .. 的规避形态」拦；纯分隔符与空白＝消毒后什么都不剩。
        ("...", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("///", {rr.DenyCode.TRAVERSAL_DENIED}),
        ("   ", {rr.DenyCode.BAD_NAME}),
    ],
)
def test_traversal_and_absolute_refs_are_denied(tmp_path, ref, expected_codes) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outcome = _create(tmp_path, root, ref, b"x\n")
    assert outcome.ok is False
    assert outcome.reason_code in expected_codes
    # 目的地与它的父级都不许被写脏。
    assert list(root.iterdir()) == []
    assert not (tmp_path / "escape.md").exists()
    assert not (tmp_path.parent / "escape.md").exists()


def test_write_lands_exactly_inside_the_whitelisted_root(tmp_path) -> None:
    inside = tmp_path / "in"
    outside = tmp_path / "out"
    outside.mkdir()
    outcome = _create(tmp_path, inside, "报告-v1.md", "# 报告\n".encode())
    assert outcome.ok, outcome.error_message()
    assert outcome.path is not None
    assert inside in outcome.path.parents
    assert list(outside.iterdir()) == []
    assert outcome.verb == rr.VERB_CREATE
    assert outcome.written_bytes == len("# 报告\n".encode())
    assert outcome.sha256 == media_digest("# 报告\n".encode())


def test_nested_ref_creates_subdirs_inside_whitelist_only(tmp_path) -> None:
    root = tmp_path / "vault"
    outcome = _create(tmp_path, root, "sub/dir/deep.md", "# 深\n".encode())
    assert outcome.ok, outcome.error_message()
    assert outcome.path == root / "sub" / "dir" / "deep.md"
    assert outcome.path.read_bytes() == "# 深\n".encode()


# ---------------------------------------------------------------------------
# ③ 限额：超限被拒不半途写


def test_oversize_denied_and_destination_stays_pristine(tmp_path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    payload = b"%PDF-1.4\n" + b"x" * 4096
    outcome = _create(
        tmp_path, root, "big.pdf", payload, limits=rr.WriteLimits(max_file_bytes=1024)
    )
    assert outcome.reason_code == rr.DenyCode.TOO_LARGE
    # 「不半途写」＝目的地目录里连临时件/部分写都没有。
    assert list(root.iterdir()) == []
    assert not list(root.rglob("*.part"))


def test_oversize_payload_never_enters_staging(tmp_path) -> None:
    staging = tmp_path / "_staging"
    root = tmp_path / "vault"
    outcome = rr.create_bytes(
        "big.md",
        b"x" * 4096,
        policy=_policy(root, limits=rr.WriteLimits(max_file_bytes=1024)),
        staging_dir=staging,
    )
    assert outcome.reason_code == rr.DenyCode.TOO_LARGE
    assert not staging.exists() or list(staging.iterdir()) == []


def test_replace_of_oversize_keeps_original_bytes(tmp_path) -> None:
    root = tmp_path / "vault"
    outcome = _create(tmp_path, root, "doc.md", "# 原版\n".encode())
    assert outcome.ok
    strict = _policy(root, limits=rr.WriteLimits(max_file_bytes=8))
    failed = rr.replace_bytes(
        "doc.md", "# 新版的超长内容\n".encode() * 10, policy=strict, **_staging(tmp_path)
    )
    assert failed.reason_code == rr.DenyCode.TOO_LARGE
    assert outcome.path.read_bytes() == "# 原版\n".encode()
    assert not list(root.rglob("*.part"))


def test_empty_payload_is_refused(tmp_path) -> None:
    root = tmp_path / "vault"
    outcome = _create(tmp_path, root, "empty.md", b"")
    assert outcome.reason_code == rr.DenyCode.EMPTY_PAYLOAD
    assert not root.exists() or list(root.iterdir()) == []


def test_daily_quota_counts_only_successes(tmp_path) -> None:
    root = tmp_path / "vault"
    ledger = rr.DailyQuotaLedger()
    policy = _policy(
        root,
        limits=rr.WriteLimits(
            max_file_bytes=64, daily_create_limit=2, daily_replace_limit=-1
        ),
    )
    # 先塞一发必拒的（超限），它**不得**占用配额。
    denied = rr.create_bytes(
        "nope.md", b"x" * 200, policy=policy, ledger=ledger, date_key=lambda: "2026-09-25"
    )
    assert denied.reason_code == rr.DenyCode.TOO_LARGE
    first = rr.create_bytes(
        "a.md", b"# a\n", policy=policy, ledger=ledger, date_key=lambda: "2026-09-25"
    )
    second = rr.create_bytes(
        "b.md", b"# b\n", policy=policy, ledger=ledger, date_key=lambda: "2026-09-25"
    )
    third = rr.create_bytes(
        "c.md", b"# c\n", policy=policy, ledger=ledger, date_key=lambda: "2026-09-25"
    )
    assert first.ok and second.ok
    assert third.reason_code == rr.DenyCode.DAILY_QUOTA
    assert ledger.used(first.root_label, "2026-09-25", rr.VERB_CREATE) == 2
    # 换一天就重新计（配额按日，不按进程 lifetime）。
    next_day = rr.create_bytes(
        "d.md", b"# d\n", policy=policy, ledger=ledger, date_key=lambda: "2026-09-26"
    )
    assert next_day.ok


# ---------------------------------------------------------------------------
# ④ 扩展名与字节指纹双查


@pytest.mark.parametrize(
    ("ref", "payload", "expected"),
    [
        # 二进制内容冒充文本扩展名。
        ("fake.md", b"\x89PNG\r\n\x1a\n\x00\x01rest", rr.DenyCode.MAGIC_MISMATCH),
        ("fake.txt", b"%PDF-1.4 not really text", rr.DenyCode.MAGIC_MISMATCH),
        # 文本内容冒充容器格式。
        ("fake.pdf", "# 只是 Markdown\n".encode(), rr.DenyCode.MAGIC_MISMATCH),
        ("fake.docx", b"PK\x03\x05 wrong zip header", rr.DenyCode.MAGIC_MISMATCH),
        # 非 UTF-8 文本。
        ("broken.md", "# 坏编码\n".encode("gbk"), rr.DenyCode.MAGIC_MISMATCH),
    ],
)
def test_magic_bytes_and_extension_must_agree(tmp_path, ref, payload, expected) -> None:
    root = tmp_path / "vault"
    outcome = _create(tmp_path, root, ref, payload)
    assert outcome.ok is False
    assert outcome.reason_code == expected
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.parametrize("ref", ["payload.exe", "installer.ps1", "hook.vbs", "tool.js"])
def test_executables_are_denied_even_when_extensions_are_wide_open(tmp_path, ref) -> None:
    """即便策略把扩展名全放开（``*``），可执行形态也永远写不进去。"""
    root = tmp_path / "vault"
    outcome = _create(
        tmp_path, root, ref, b"whatever bytes\n", allowed_extensions=frozenset({"*"})
    )
    assert outcome.ok is False
    assert outcome.reason_code == rr.DenyCode.EXECUTABLE_DENIED
    assert not root.exists() or list(root.iterdir()) == []


def test_image_extensions_are_outside_the_document_writer_default_policy(tmp_path) -> None:
    """图片/音频有自己的落盘口（媒体归档、渲染侧），文档写盘口不收。"""
    root = tmp_path / "vault"
    outcome = _create(
        tmp_path, root, "shot.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16
    )
    assert outcome.reason_code == rr.DenyCode.EXTENSION_DENIED
    assert not root.exists() or list(root.iterdir()) == []
    # 同一段字节改成登记的图片扩展名 + 显式放宽策略，就能通过指纹这一关。
    allowed = rr.DEFAULT_ALLOWED_EXTENSIONS | {".png"}
    again = _create(
        tmp_path,
        root,
        "shot.png",
        b"\x89PNG\r\n\x1a\n" + b"0" * 16,
        allowed_extensions=allowed,
    )
    assert again.ok, again.error_message()


def test_genuine_binaries_pass_the_signature_check(tmp_path) -> None:
    root = tmp_path / "vault"
    pdf = b"%PDF-1.7\n% bogus body for the writer lock\n"
    docx = b"PK\x03\x04" + b"\x00" * 32
    exts = rr.DEFAULT_ALLOWED_EXTENSIONS
    assert rr.create_bytes("a.pdf", pdf, policy=_policy(root), **_staging(tmp_path)).ok
    outcome = rr.create_bytes(
        "b.docx", docx, policy=_policy(root, allowed_extensions=exts), **_staging(tmp_path)
    )
    assert outcome.ok, outcome.error_message()


# ---------------------------------------------------------------------------
# ⑤ 动词语义：创建不覆盖、修改不新建


def test_create_refuses_to_overwrite_and_replace_refuses_to_create(tmp_path) -> None:
    root = tmp_path / "vault"
    first = _create(tmp_path, root, "doc.md", "# 一版\n".encode())
    assert first.ok
    again = _create(tmp_path, root, "doc.md", "# 二版\n".encode())
    assert again.reason_code == rr.DenyCode.ALREADY_EXISTS
    assert first.path.read_bytes() == "# 一版\n".encode()

    missing = rr.replace_bytes("ghost.md", "# 无\n".encode(), policy=_policy(root), **_staging(tmp_path))
    assert missing.reason_code == rr.DenyCode.TARGET_MISSING
    assert not (root / "ghost.md").exists()

    updated = rr.write_document(
        "doc.md", "# 二版\n".encode(), policy=_policy(root), **_staging(tmp_path)
    )
    assert updated.ok
    assert updated.verb == rr.VERB_REPLACE
    assert first.path.read_bytes() == "# 二版\n".encode()


def test_external_verdict_seam_denies_and_never_echoes_the_path(tmp_path) -> None:
    """禁触名册的注入口（缺省不接；接的是 ``safety_exec/paths.py`` 那张名册）。"""
    root = tmp_path / "vault"
    seen: list[str] = []

    def denying_guard(candidate: str) -> str:
        seen.append(candidate)
        return "forbidden_zone"

    outcome = rr.create_bytes(
        "doc.md",
        "# 内容\n".encode(),
        policy=_policy(root, external_verdict=denying_guard),
        **_staging(tmp_path),
    )
    assert outcome.reason_code == rr.DenyCode.EXTERNAL_GUARD_DENIED
    assert len(seen) == 1
    assert not root.exists() or list(root.iterdir()) == []
    # 拒绝说明里绝不带落点原文（那是本机路径明文）。
    assert not _DRIVE_FORM_RE.search(outcome.error_message())
    assert "forbidden_zone" not in outcome.error_message()

    def raising_guard(_candidate: str) -> str:
        raise RuntimeError("判定件炸了")

    broken = rr.create_bytes(
        "doc.md",
        "# 内容\n".encode(),
        policy=_policy(root, external_verdict=raising_guard),
        **_staging(tmp_path),
    )
    assert broken.reason_code == rr.DenyCode.EXTERNAL_GUARD_DENIED

    root2 = tmp_path / "vault2"
    ok = rr.create_bytes(
        "doc.md",
        "# 内容\n".encode(),
        policy=_policy(root2, external_verdict=lambda _candidate: ""),
        **_staging(tmp_path),
    )
    assert ok.ok


# ---------------------------------------------------------------------------
# ⑥ 能力层：导出与两个动词都只经运行器


def test_export_document_writes_only_where_the_policy_allows(tmp_path) -> None:
    """能力层「自己拼 out_dir 直接写盘」那条第二通路必须已经死了。

    手法：``out_dir`` 给 A、策略根给 B。若能力层还自己往 A 写，A 就会出现文件。
    """
    out_dir = tmp_path / "declared_out"
    allowed = tmp_path / "runner_root"
    path, error = export_document(
        _MARKDOWN,
        "md",
        out_dir,
        title="测试报告",
        policy=_policy(allowed),
        **_staging(tmp_path),
    )
    assert error == ""
    assert path.exists()
    assert allowed in path.parents
    assert not out_dir.exists() or list(out_dir.iterdir()) == []


def test_export_all_formats_land_through_the_runner(tmp_path) -> None:
    root = tmp_path / "export"
    for fmt in ("md", "docx", "xlsx", "pptx", "pdf"):
        path, error = export_document(_MARKDOWN, fmt, root, title="多格式", **_staging(tmp_path))
        assert error == "", f"{fmt}: {error}"
        assert path.exists() and path.stat().st_size > 0
        assert root in path.parents
    assert not list(root.rglob("*.part"))


def test_export_rejects_unsupported_format_before_touching_disk(tmp_path) -> None:
    root = tmp_path / "export"
    path, error = export_document(_MARKDOWN, "exe", root, title="主题")
    assert path == Path()
    assert "不支持的格式" in error
    assert not root.exists()


def test_capability_create_and_revise_are_runner_verbs(tmp_path) -> None:
    root = tmp_path / "vault"
    policy = _policy(root)
    created = create_document_file("笔记.md", "# 新建\n", policy=policy)
    assert created.ok and created.verb == rr.VERB_CREATE
    revised = revise_document_file("笔记.md", "# 改过\n", policy=policy)
    assert revised.ok and revised.verb == rr.VERB_REPLACE
    assert created.path.read_text(encoding="utf-8") == "# 改过\n"
    assert (
        revise_document_file("不存在.md", "x", policy=policy).reason_code
        == rr.DenyCode.TARGET_MISSING
    )
    assert (
        create_document_file("笔记.md", "x", policy=policy).reason_code
        == rr.DenyCode.ALREADY_EXISTS
    )
    # 能力层入口也一样 fail-closed。
    assert (
        create_document_file("笔记.md", "x", policy=rr.WritePolicy()).reason_code
        == rr.DenyCode.NO_WHITELIST
    )


# ---------------------------------------------------------------------------
# ⑦ 「创建成功 + 未发生任何执行」


def test_code_files_are_created_but_never_executed(tmp_path, monkeypatch) -> None:
    """需求 16(2)(c)：``_CODE_EXECUTION_ENABLED=False`` 下代码**能创建**、绝不执行。"""
    assert _CODE_EXECUTION_ENABLED is False
    root = tmp_path / "vault"
    marker = tmp_path / "did_run.marker"
    source = f"open(r'{marker}', 'w').write('ran')\nprint('hello')\n"
    outcome = create_document_file("probe.py", source, policy=_policy(root))
    assert outcome.ok, outcome.error_message()  # 创建这一步是成功的
    assert outcome.path is not None and outcome.path.suffix == ".py"
    assert not marker.exists(), "创建路径就把上传代码跑了"

    calls: list[object] = []

    def counting_run(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("生产装配路径不得起跑子进程")

    monkeypatch.setattr(fx.subprocess, "run", counting_run)
    report = run_code_debug(outcome.path)
    assert calls == [], "创建后的读码流程调起了 subprocess"
    assert "语法检查通过" in report and "本轮未执行" in report
    assert "运行成功" not in report
    assert not marker.exists()


# ---------------------------------------------------------------------------
# ⑧（已出账）三通道对齐出站助手：删优于接（2026-09-26 S-FILES-LAND，需求 16(3)）
#
# ``restricted_runner.build_aligned_file_outbound`` 全仓**零生产调用点**，而它做的
# 「一条票三条腿」在 domains/transport 早已真通：QQ 腿 file_gateway._deliver_onebot、
# TG 腿 _deliver_telegram_document、邮件腿 build_mail_attachment_message / 
# attach_bytes_to_mail_message（装配口 sender/nonebot.py:420-470，S-T-TGSEND 复核）。
# 留着它＝同一件事两处真身 + 一次性把三份字节读进内存且不过单文件限额。
# 原六例（邮件腿真附件/拒时必抛/真网关金丝雀/三腿同源/正文不泄盘符/后置断言整段隐去）
# 随件删除；三腿行为的现役锁见 tests/test_file_outbound_channels.py 与
# tests/test_file_gateway_phase1.py。**回滚点**：从 %TEMP% 备份恢复
# restricted_runner.py 与被删六例（备份位置见席位日志 S-FILES-LAND.md §伍），
# 并把 tests/test_files_domain_audit.py 的 S-16-ALIGNED-OUTBOUND 出账注释改回 xfail。


# ---------------------------------------------------------------------------
# ⑨ AST 面：能力层零直写、运行器零执行


_DIRECT_WRITE_NAMES = frozenset(
    {
        "write_text",
        "write_bytes",
        "mkdir",
        "makedirs",
        "removedirs",
        "rmdir",
        "touch",
        "unlink",
        "open",
    }
)


def _called_attribute_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def test_capability_layer_has_no_direct_write_primitive() -> None:
    """能力层不得自己写盘（第二通路），也不得 ``mkdir``。"""
    source = Path(fx.__file__).read_text(encoding="utf-8")
    offenders = _called_attribute_names(source) & _DIRECT_WRITE_NAMES
    assert not offenders, f"能力层出现直写/直读原语：{sorted(offenders)}"
    # 并且必须真的在调运行器（判据不是「不写」而是「只经一个口写」）。
    assert {"stage_write", "create_bytes", "replace_bytes"} <= _called_attribute_names(source)


def test_capability_layer_never_composes_a_destination_path() -> None:
    """``out_dir`` 只许作为**白名单根**进策略，不许被拼成目标路径。"""
    tree = ast.parse(Path(fx.__file__).read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            for side in (node.left, node.right):
                if isinstance(side, ast.Name) and "out_dir" in side.id:
                    offenders.append(node.lineno)
                    break
    assert not offenders, f"能力层自己拼落点：行 {offenders}"


def test_runner_has_no_execution_primitive() -> None:
    """运行器只写不跑（教义 4）：执行原语一枚都不许出现。

    ``compile`` 只禁**内置**那一枚（``re.compile`` 是合法属性调用，不能误伤）；
    子进程族按属性名拦（``subprocess.run`` / ``os.system`` / ``Popen`` …）。
    """
    source = Path(rr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    builtin_calls: set[str] = set()
    attribute_calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            builtin_calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            attribute_calls.add(node.func.attr)
    forbidden_builtins = {"exec", "eval", "compile", "__import__"}
    forbidden_attributes = {
        "run",
        "Popen",
        "call",
        "check_output",
        "check_call",
        "system",
        "spawn",
        "execv",
        "execve",
        "kill",
        "waitpid",
    }
    assert not (builtin_calls & forbidden_builtins), sorted(
        builtin_calls & forbidden_builtins
    )
    assert not (attribute_calls & forbidden_attributes), sorted(
        attribute_calls & forbidden_attributes
    )
    assert re.search(r"^\s*(?:import|from)\s+subprocess\b", source, re.MULTILINE) is None
    assert re.search(r"^\s*(?:import|from)\s+asyncio\b", source, re.MULTILINE) is None


def test_runner_defines_no_second_forbidden_roster() -> None:
    """禁触名册唯一真身是 ``safety_exec/paths.py``；这里不许抄第二份（教义 3）。"""
    source = Path(rr.__file__).read_text(encoding="utf-8")
    for token in (
        "_FORBIDDEN_DIR_NAMES",
        "_FORBIDDEN_FILE_SUFFIXES",
        "cookie",
        ".sqlite3",
        "prompt_audit",
        "%2e",
    ):
        assert token not in source, f"运行器里出现了第二张名册的成分：{token}"


def test_deny_codes_are_registered_and_have_plain_text() -> None:
    """一码一人话（认不出不编解释的规矩反过来也要求登记齐全）。"""
    for code in rr.DENY_CODES:
        assert code in rr.DENY_PLAIN_TEXT
        assert not _DRIVE_FORM_RE.search(rr.DENY_PLAIN_TEXT[code])
    assert rr.plain_reason("没这个代号") == "未登记的写盘拒绝代号 没这个代号"
    assert rr.plain_reason("") == "未给出拒绝代号"


def test_staging_files_are_cleaned_up_after_publish(tmp_path) -> None:
    staging = tmp_path / "_staging"
    root = tmp_path / "vault"
    staged = rr.stage_write("doc.md", staging_dir=staging)
    assert isinstance(staged, rr.StagedWrite)
    staged.accept_text("# 交给运行器\n")
    outcome = staged.publish(_policy(root), mode=rr.MODE_CREATE)
    assert outcome.ok
    assert not staged.path.exists(), "暂存位发布后必须回收"
    assert outcome.path.read_text(encoding="utf-8") == "# 交给运行器\n"


def test_control_characters_are_washed_out_of_the_name(tmp_path) -> None:
    """控制字符经 ``sanitize_file_name`` 剥掉 ⇒ 到盘上的名字里绝不残留 NUL。"""
    root = tmp_path / "vault"
    assert rr.sanitize_write_segments("doc\x00.md") == ("doc.md",)
    with pytest.raises(rr._Rejected):
        rr.sanitize_write_segments("")
    outcome = _create(tmp_path, root, "doc\x00.md", b"# x\n")
    assert outcome.ok, outcome.error_message()
    assert "\x00" not in outcome.name
    assert (root / "doc.md").read_bytes() == b"# x\n"


def test_sanitized_name_is_what_reaches_the_disk(tmp_path) -> None:
    """段名里能剥的剥掉（控制字符/多余分隔符），剥完仍是合法件名 ⇒ 放行。"""
    root = tmp_path / "vault"
    outcome = _create(tmp_path, root, "sub/月度 报告 v2.md", b"# ok\n")
    assert outcome.ok, outcome.error_message()
    assert outcome.name == "月度 报告 v2.md"
    assert (root / "sub" / "月度 报告 v2.md").read_bytes() == b"# ok\n"
