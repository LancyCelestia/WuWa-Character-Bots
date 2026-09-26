"""受限写盘运行器的「容器实底」审计锁（席位 S-T-FILES-AUDIT，需求 16(4)）。

与存量的两件怎么分工（避免同一件事两处真身）：

- ``tests/test_file_exchange_restricted_runner.py``＝判据全家（消毒/限额/指纹/
  动词/配额/注入缝/AST 三锁）与三通道附件形状；
- ``tests/test_restricted_runner_live.py``＝真身 ``paths.check_sendable`` 经
  ``external_verdict`` **注入缝**端到端跑一次；
- 本件只管两格：**缺省策略下禁触名册还在不在执法**（不靠调用方接缝），以及
  「**修改已有文件**」这条腿的回读/寻址半边（``resolve_existing`` /
  ``read_confined_bytes`` / ``revise_in_place``）——这两格此前全树零枚锁，
  前者是「唯一咽喉」成立与否的实底，后者是需求 16(2) 那条腿的落点。

全部离线、零网络、落点只在 ``tmp_path``。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FILES_DOMAIN = (
    _REPO_ROOT / "plugins" / "bot_unified_runtime" / "domains" / "files"
)
_RUNNER = _FILES_DOMAIN / "sender" / "restricted_runner.py"

def _attribute_and_name_calls(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def _policy(root: Path) -> rr.WritePolicy:
    return rr.policy_for_roots([root])


def _staging_dir(tmp_path: Path) -> Path:
    """暂存位收进 ``tmp_path``：不污染系统临时目录，也不给 mypy 留 **解包歧义。"""
    staging = tmp_path / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    return staging


# ---------------------------------------------------------------------------
# ① 缺省就执法：白名单根被配歪到禁触区时，不靠调用方接缝也拦
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["settings/note.md", "personas/核心知识.md"])
def test_forbidden_zone_denied_with_the_default_policy(
    tmp_path: Path, ref: str
) -> None:
    """缺省策略（``external_verdict=None``）也必须拦下禁触名册里的落点。

    这一格是「唯一咽喉成立吗」的实底：此前咽喉只认调用方给的根，名册要靠
    ``external_verdict`` 才说话——把导出目录配到人格库/运行期设置目录旁边，
    整条判据就只剩「白名单」二字。
    """
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    outcome = rr.create_bytes(ref, "# 内容\n".encode(), policy=_policy(root), staging_dir=_staging_dir(tmp_path))
    assert outcome.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION
    assert not (root / "settings").exists()
    assert not (root / "personas").exists()
    assert outcome.error_message()
    assert ":" not in outcome.error_message().replace("：", "")  # 不回显盘符形态


def test_injected_external_verdict_still_speaks_first(tmp_path: Path) -> None:
    """调用方接了缝＝它先说话（代号仍是 ``external_guard_denied``）。

    存量件 ``test_restricted_runner_live.py`` 钉的就是这个次序；本锁防的是
    日后有人把缺省兜底挪到注入缝**之前**，把「调用方拒了」的真实原因洗成一条
    笼统的 forbidden_destination。
    """
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    policy = rr.WritePolicy(
        allowed_roots=(root,),
        external_verdict=lambda _candidate: "caller_said_no",
    )
    outcome = rr.create_bytes(
        "settings/note.md", b"# x\n", policy=policy, staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.reason_code == rr.DenyCode.EXTERNAL_GUARD_DENIED


def test_legal_write_inside_whitelist_still_succeeds_by_default(
    tmp_path: Path,
) -> None:
    """反向锁：缺省兜底**不得**把合法落点一并拦死（只认 forbidden 那一族）。"""
    root = tmp_path / "vault"
    outcome = rr.create_bytes(
        "note.md", "# 合法\n".encode(), policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.ok, outcome.error_message()
    assert (root / "note.md").read_bytes() == "# 合法\n".encode()


def test_default_policy_never_gates_on_registered_roots(tmp_path: Path) -> None:
    """正向注册名册**仍走注入缝**：``tmp_path`` 不在 paths 登记根内也照样能写。

    这条是「为什么不把 check_sendable 整张脸缺省接上」的证据；哪天有人顺手
    接全，本锁当场红（症状＝所有合法写变 forbidden/outside）。
    """
    root = tmp_path / "vault"
    decision = paths.check_sendable(str(root / "note.md"))
    assert decision.verdict != paths.VERDICT_ALLOWED, "前提：tmp 根本不在登记名册里"
    outcome = rr.create_bytes("note.md", b"ok\n", policy=_policy(root), staging_dir=_staging_dir(tmp_path))
    assert outcome.ok, outcome.error_message()


def test_poison_removing_the_default_guard_lets_the_forbidden_write_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒自证：把缺省兜底摘掉，同一发禁触落点就真的写进去了。

    没有这一枚，① 那把锁可能只是在读一条别的判据（本波点名的「存在性糊过
    活性判据」形态）。摘守卫后必须写成功，装回后必须拒——两半都断言。
    """
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rr, "_forbidden_destination_reason", lambda _target: "")
    outcome = rr.create_bytes(
        "settings/note.md", b"# smuggled\n", policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.ok, "守卫摘掉后仍被拦＝①那把锁没在执法，是别处在拦"
    assert (root / "settings" / "note.md").is_file()
    monkeypatch.undo()
    again = rr.create_bytes(
        "settings/second.md", b"# x\n", policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert again.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION


def test_forbidden_guard_fails_closed_when_the_roster_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判定件抛异常＝拦（与本件注入缝同一条纪律，不反转为 fail-open）。"""

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("名册不可用")

    monkeypatch.setattr(paths, "check_sendable", _boom)
    root = tmp_path / "vault"
    outcome = rr.create_bytes(
        "note.md", b"# x\n", policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION
    assert not (root / "note.md").exists()


# ---------------------------------------------------------------------------
# ② 「修改已有文件」腿：寻址 + 受限回读 + 读改写单口
# ---------------------------------------------------------------------------


def test_resolve_existing_addresses_only_inside_the_whitelist(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "a.md").write_text("# a\n", encoding="utf-8")
    located = rr.resolve_existing("docs/a.md", policy=_policy(root))
    assert isinstance(located, Path)
    assert located.name == "a.md"


@pytest.mark.parametrize(
    ("ref", "code"),
    [
        ("../outside.md", rr.DenyCode.TRAVERSAL_DENIED),
        ("missing.md", rr.DenyCode.TARGET_MISSING),
        ("settings/a.md", rr.DenyCode.FORBIDDEN_DESTINATION),
        ("sub/../a.md", rr.DenyCode.TRAVERSAL_DENIED),
    ],
)
def test_resolve_existing_denies_the_four_shapes(
    tmp_path: Path, ref: str, code: str
) -> None:
    """回读口与写口**同一套判据**：想「只读一下」也不许从咽喉边上绕。"""
    root = tmp_path / "vault"
    (root / "settings").mkdir(parents=True, exist_ok=True)
    (root / "settings" / "a.md").write_text("# s\n", encoding="utf-8")
    (root / "a.md").write_text("# a\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# o\n", encoding="utf-8")
    result = rr.resolve_existing(ref, policy=_policy(root))
    assert isinstance(result, rr.WriteOutcome)
    assert result.reason_code == code
    assert not result.ok
    assert outside.read_text(encoding="utf-8") == "# o\n"


def test_forbidden_ref_is_denied_before_existence_is_revealed(
    tmp_path: Path,
) -> None:
    """禁触落点不给出「存不存在」的 oracle：先点名册，再谈在不在。"""
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    result = rr.resolve_existing("settings/nope.md", policy=_policy(root))
    assert isinstance(result, rr.WriteOutcome)
    assert result.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION


def test_read_confined_bytes_returns_bytes_and_digest(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_bytes(b"# \xe4\xb8\xad\xe6\x96\x87\n")
    result = rr.read_confined_bytes("a.md", policy=_policy(root))
    assert not isinstance(result, rr.WriteOutcome)
    data, digest = result
    assert data == "# 中文\n".encode()
    assert len(digest) == 64


def test_read_confined_bytes_respects_the_size_cap(tmp_path: Path) -> None:
    """回读也吃 ``max_file_bytes``：否则限额等于给写侧单独设的、读侧能绕过。"""
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "big.md").write_bytes(b"x" * 4096)
    policy = rr.WritePolicy(
        allowed_roots=(root,),
        limits=rr.WriteLimits(max_file_bytes=64),
    )
    result = rr.read_confined_bytes("big.md", policy=policy)
    assert isinstance(result, rr.WriteOutcome)
    assert result.reason_code == rr.DenyCode.TOO_LARGE


def test_revise_in_place_never_creates_a_missing_target(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    outcome = rr.revise_in_place(
        "ghost.md", lambda data: data + b"!", policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.reason_code == rr.DenyCode.TARGET_MISSING
    assert not (root / "ghost.md").exists()


def test_revise_in_place_rewrites_only_after_a_real_change(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_text("# 一\n", encoding="utf-8")
    outcome = rr.revise_in_place(
        "a.md",
        lambda data: data.replace("一".encode(), "二".encode()),
        policy=_policy(root),
        staging_dir=_staging_dir(tmp_path),
    )
    assert outcome.ok, outcome.error_message()
    assert outcome.verb == rr.VERB_REPLACE
    assert (root / "a.md").read_text(encoding="utf-8") == "# 二\n"


def test_revise_in_place_noop_writes_nothing_and_burns_no_quota(
    tmp_path: Path,
) -> None:
    """同字节回写＝不写：不刷 mtime、不占日配额（否则「改了什么」被配额说谎）。"""
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_text("# same\n", encoding="utf-8")
    ledger = rr.DailyQuotaLedger()
    outcome = rr.revise_in_place(
        "a.md",
        lambda data: data,
        policy=_policy(root),
        ledger=ledger,
        date_key=lambda: "2026-09-26",
        staging_dir=_staging_dir(tmp_path),
    )
    assert outcome.ok and outcome.written_bytes == 0
    assert "未变化" in outcome.detail
    assert ledger.used("vault", "2026-09-26", rr.VERB_REPLACE) == 0


@pytest.mark.parametrize(
    "produced",
    [None, 123, b""],
)
def test_revise_in_place_rejects_unusable_transform_results(
    tmp_path: Path, produced: object
) -> None:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_text("# keep\n", encoding="utf-8")
    outcome = rr.revise_in_place(
        "a.md", lambda _data: produced, policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    )
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert (root / "a.md").read_text(encoding="utf-8") == "# keep\n"


def test_revise_in_place_transform_failure_leaves_original_intact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_text("# keep\n", encoding="utf-8")

    def _boom(_data: bytes) -> bytes:
        raise ValueError("改写失败")

    outcome = rr.revise_in_place("a.md", _boom, policy=_policy(root), staging_dir=_staging_dir(tmp_path))
    assert outcome.reason_code == rr.DenyCode.TRANSFORM_FAILED
    assert "ValueError" in outcome.error_message()
    assert (root / "a.md").read_text(encoding="utf-8") == "# keep\n"


def test_transform_sees_bytes_only_and_no_path(tmp_path: Path) -> None:
    """改写函数只收字节：它拿不到路径、拿不到 policy，也就无法自行落盘。"""
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.md").write_text("# x\n", encoding="utf-8")
    seen: list[object] = []

    def _spy(data: bytes) -> bytes:
        seen.append(data)
        return data + b"y\n"

    assert rr.revise_in_place(
        "a.md", _spy, policy=_policy(root), staging_dir=_staging_dir(tmp_path)
    ).ok
    assert len(seen) == 1 and isinstance(seen[0], bytes)


# ---------------------------------------------------------------------------
# ③ 咽喉的账：写盘原语只准在运行器一侧；本域不得有第二条投递腿
# ---------------------------------------------------------------------------


#: 落盘方法的判据**按效果不按名字**：``copy.copy(cookie)`` 与 ``str.replace``
#: 都长得像写盘动作（本席第一版就被这两枚骗过一次，见席位报告 §叁-3），
#: 故 ``copy``/``replace``/``move`` 只在明确是 ``os.*``/``shutil.*`` 时才记账。
_WRITE_METHOD_NAMES = frozenset(
    {
        "write_text",
        "write_bytes",
        "mkdir",
        "makedirs",
        "removedirs",
        "rmdir",
        "unlink",
        "rmtree",
        "copyfile",
        "copytree",
        "mkdtemp",
        "truncate",
    }
)
_OS_OR_SHUTIL = frozenset({"os", "shutil"})


def _base_name(node: ast.expr) -> str:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ""


def _opens_for_writing(call: ast.Call) -> bool:
    """``path.open("x")`` / ``open(p, "wb")`` / ``open(p, mode="a")`` 之类算写。

    mode 的位置按调用形态定：``Path.open(mode, ...)`` 的第 0 位、内置
    ``open(file, mode, ...)`` 的第 1 位、或 ``mode=`` 关键字。判不出就不记，
    绝不「凡是 open 都算写」（那会把只读用法记成欠账、把账本变成噪音）。
    """
    for keyword in call.keywords:
        value = keyword.value
        if (
            keyword.arg == "mode"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return value.value[:1] in {"w", "a", "x", "+"}
    is_method = isinstance(call.func, ast.Attribute) and call.func.attr == "open"
    mode_index = 0 if is_method else 1
    if len(call.args) > mode_index:
        candidate = call.args[mode_index]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value[:1] in {"w", "a", "x", "+"}
    return False


def _write_calls(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            if isinstance(func, ast.Name) and func.id == "open" and _opens_for_writing(node):
                found.add("open:write")
            continue
        if func.attr in _WRITE_METHOD_NAMES:
            found.add(func.attr)
        elif func.attr == "open" and _opens_for_writing(node):
            found.add("open:write")
        elif func.attr in {"replace", "rename", "move", "copyfile", "copy"}:
            base = _base_name(func.value)
            if base in _OS_OR_SHUTIL:
                found.add(f"{base}.{func.attr}")
            elif func.attr == "replace" and len(node.args) == 1:
                # ``Path.replace(dst)`` 只带一枚参数，``str.replace(a, b)`` 带两枚——
                # 按参数个数分家，才不把「改字符串」记成落盘（本席第一版按名字判，
                # 当场被 ``copy.copy``/``str.replace`` 骗出三枚假欠账）。
                found.add("path.replace")
    return found


#: 已登记的「运行器之外落盘」欠账（**逐枚带理由与坐标；这本账只准降不准升**）。
#: 新增一枚＝本锁红 ⇒ 要么改走运行器，要么由主代理带裁定把它记进来并写明为什么。
#: 修掉一枚而不删这行＝同样红（防「账比现场旧」）。
#: 2026-09-26 S-FILES-LAND 摘一枚：``file_reader.build_generated_file``（W3 第二条
#: 创建腿，mkdir + open("x") 直写）已收编进运行器（create_bytes + 单根策略 + 禁触
#: 名册缺省执法 + 2MiB 上限保持），其登记行连同「本窗由 S-T-PDF-3 在写故只登记不修」
#: 的旧前提一起出账——该件早已交付、现算无人在写。回滚点＝把 build_generated_file
#: 改回直写并把本注释换回原条目（原文见 .superpowers/sdd/2026-09-25-goal18-wave/
#: logs/S-FILES-LAND.md §伍）。
OUTSIDE_RUNNER_WRITE_DEBT: dict[str, set[str]] = {
    # 动词是「把平台/远端取回的东西存下来」，不是「按用户需求创建/修改文档」：
    # 落点由配置目录决定，这里只做目录 bootstrap。收编它要先给「入站落盘」
    # 定义一个白名单根，属装配线的活（主代理），见席位报告 §伍 交清单。
    "plugins/bot_unified_runtime/domains/files/capabilities/group_files.py": {"mkdir"},
    "plugins/bot_unified_runtime/domains/files/sources/downloader.py": {"mkdir"},
}


def test_the_write_detector_itself_sees_and_ignores_the_right_shapes() -> None:
    """判据自证：探测器必须认得真写盘、且不被同名方法骗。

    没有这一枚，②/③ 那两把棘轮可能只是「一把瞎尺」（本仓点名过的假绿形态：
    判据按名字不按效果）。正例四形态、负例四形态，逐枚断言。
    """
    positives: dict[str, set[str]] = {
        'p.write_bytes(b"x")': {"write_bytes"},
        'p.write_text("x")': {"write_text"},
        'd.mkdir(parents=True)': {"mkdir"},
        'with p.open("x", encoding="utf-8") as s:\n    pass': {"open:write"},
        'with open(p, "wb") as s:\n    pass': {"open:write"},
        'with open(p, mode="a") as s:\n    pass': {"open:write"},
        "os.replace(a, b)": {"os.replace"},
        "shutil.copytree(a, b)": {"copytree"},
        "tmp.replace(final)": {"path.replace"},
    }
    for source, expected in positives.items():
        assert _write_calls(source) == expected, source
    negatives: dict[str, set[str]] = {
        "copy.copy(cookie)": set(),  # 标准库 copy：与落盘无关
        'name.replace("@", "")': set(),  # str.replace 两枚参数
        'text.split("x")': set(),
        "p.read_bytes()": set(),
        'p.open("r")': set(),
        "log.warning('x')": set(),
    }
    for source, expected in negatives.items():
        assert _write_calls(source) == expected, source


def test_files_domain_writes_only_through_the_runner() -> None:
    """``domains/files/**`` 除运行器外的落盘原语＝**恰好登记的那几枚**，一枚不许多。

    存量件那枚 AST 锁只扫能力层一个文件；本锁把同一判据铺到整个域并按效果判定，
    这样「唯一咽喉」是对目录说话、不是对一个文件说话——并且**当场揭穿**
    「创建文件」其实有两条腿（见 ``OUTSIDE_RUNNER_WRITE_DEBT`` 第三条）。
    """
    scanned = 0
    ledger_keys = set(OUTSIDE_RUNNER_WRITE_DEBT)
    for path in sorted(_FILES_DOMAIN.rglob("*.py")):
        if path == _RUNNER:
            continue
        scanned += 1
        relative = path.relative_to(_REPO_ROOT).as_posix()
        hits = _write_calls(path.read_text(encoding="utf-8"))
        expected = OUTSIDE_RUNNER_WRITE_DEBT.get(relative, set())
        assert hits == expected, (
            f"{relative} 落盘原语与登记账不符：现场 {sorted(hits)} ≠ 账上 {sorted(expected)}"
        )
        ledger_keys.discard(relative)
    assert scanned >= 8, f"扫描面异常（只扫到 {scanned} 个文件）＝本判据假绿"
    assert not ledger_keys, f"登记账里有现场不存在的文件（账比现场旧）：{sorted(ledger_keys)}"


def test_runner_never_delivers_by_itself() -> None:
    """运行器只写不投：``call_api`` / ``send`` 一族不许出现在这一侧。

    三通道投递的真身在 ``domains/transport/``（``file_gateway._deliver_mail`` /
    ``_deliver_telegram_document`` + ``sender/nonebot.py`` 装配口）。这一枚锁把
    「别在文件域里长出第二条投递腿」变成可机检的判据。
    """
    source = _RUNNER.read_text(encoding="utf-8")
    calls = _attribute_and_name_calls(source)
    for banned in ("call_api", "send_msg", "send_file", "send_group_file", "upload"):
        assert banned not in calls, f"运行器出现投递动作 {banned}＝第二条腿"


def test_runner_consumes_the_roster_in_two_places() -> None:
    """``paths`` 在运行器里被**用到**（不是只 import 着）：写侧与回读侧各一处。

    这枚锁同时是给主代理的入库依据——``tests/test_safety_exec_paths.py`` 的
    ``ALLOWED_CONSUMERS`` 需要登记本件，而登记理由必须是「真消费」，
    不是「挂了个没人调的适配器」。
    """
    source = _RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    call_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "check_sendable"
    ]
    assert len(call_sites) >= 1, "运行器没真调用 paths.check_sendable"
    helper_sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_forbidden_destination_reason"
    ]
    assert len(helper_sites) >= 2, "禁触兜底只接了一侧（写或读），另一侧仍可绕"


# ---------------------------------------------------------------------------
# ④ 三枚新公共口的注毒自证（每口一发：把那一腿的守卫摘掉 ⇒ 本文件上面那批断言必红）
#
# 为什么单独立这一节，而不是"上面已经断过行为"就算完：
# ② 那一节证明的是「守卫在场时行为正确」，它**自身不构成检测力证据**——
# 一条恒真的判据（比如 containment 其实没人走、上面的 ``outside_whitelist``
# 其实来自别的分支）也能把那批断言跑得全绿。本仓点名的形态叫
# 「存在性糊过活性判据」，文末那枚 AST 锁（``helper_sites >= 2``）恰好就是这种
# 名字级尺：数得出两处在，看不出某一处其实不执法。所以每一枚公共口各摘一枚
# 守卫、要求**坏结果真的发生**，再 ``monkeypatch.undo()`` 要求同一发被拦住。
#
# 三发摘的东西与各自的可观察量（如实：A/C 摘同一枚守卫函数，但**腿不同、
# 危害不同**——只读腿泄的是「在不在」，写腿泄的是「字节被改了」；只有 B 摘的是
# 另一枚函数。三发若摘成同一可观察量就等于只打了一发）：
#   A ``resolve_existing``  摘 ``_forbidden_destination_reason`` ⇒ 存在性 oracle 开；
#   B ``read_confined_bytes`` 摘 ``_read_confined_target``（含限额）⇒ 超限件整份进内存；
#   C ``revise_in_place``    摘 ``_forbidden_destination_reason`` ⇒ 禁触区文件真被改写。
# ``_match_root`` 的 containment 腿**今天拿不到检测力证据**（本机无符号链接特权），
# 逐字原因与登记见 A 的 docstring 与席位日志 §柒-2。
# ---------------------------------------------------------------------------


def test_poison_roster_removal_opens_the_existence_oracle_on_the_addressing_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒 A（``resolve_existing``）：摘掉禁触兜底 ⇒ 寻址口对禁触区**吐出存在性**。

    这一口独有的危害不是「写坏东西」（它不写），而是**回答在不在**：禁触区里
    哪个文件存在、路径长什么样，全可以从这条只读腿上问出来。所以判据不是
    「有没有落盘」，而是**代号本身**——守卫在场时无论存在与否一律
    ``forbidden_destination``，摘掉后一枚变 ``target_missing``（=不存在）、
    另一枚直接交回 ``Path``（=存在）。这正是
    ``test_forbidden_ref_is_denied_before_existence_is_revealed`` 那把锁的检测力证据。

    ⚠ 本发摘的是禁触那一腿，不是 containment 那一腿——**containment 在本机拿不到
    检测力证据**：Windows 建符号链接要 ``SeCreateSymbolicLinkPrivilege``，本会话实测
    ``os.symlink`` 抛 ``WinError 1312/1314``（客户端没有所需的特权），而
    ``_match_root`` 的越界分支只在「解析后跑出根外」时才开口（段里含 ``..`` 早在
    ``sanitize_write_segments`` 就被拦，走不到这一腿）。故 containment 半边今天只有
    ``test_resolve_existing_denies_the_four_shapes`` 的 ``traversal_denied`` 一格有牙，
    「链接外指」那一格登记为**未证**（见席位日志 §柒-2），不假称已验。
    """
    root = tmp_path / "vault"
    (root / "settings").mkdir(parents=True, exist_ok=True)
    (root / "settings" / "there.md").write_text("# 在\n", encoding="utf-8")

    monkeypatch.setattr(rr, "_forbidden_destination_reason", lambda _target: "")
    missing_answer = rr.resolve_existing("settings/absent.md", policy=_policy(root))
    present_answer = rr.resolve_existing("settings/there.md", policy=_policy(root))
    assert isinstance(missing_answer, rr.WriteOutcome)
    assert missing_answer.reason_code == rr.DenyCode.TARGET_MISSING, (
        "摘掉守卫后仍不回答存在性＝这一腿的拦点不在禁触兜底上，本发空跑"
    )
    assert isinstance(present_answer, Path), "同上：存在的那枚必须真的被定出来"
    assert present_answer.read_text(encoding="utf-8") == "# 在\n"

    monkeypatch.undo()
    for ref in ("settings/absent.md", "settings/there.md"):
        again = rr.resolve_existing(ref, policy=_policy(root))
        assert isinstance(again, rr.WriteOutcome)
        assert again.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION, (
            f"{ref}：还原后仍给出存在性答案＝oracle 没被堵住"
        )


def test_poison_read_cap_removal_pulls_an_over_limit_file_into_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒 B（``read_confined_bytes``）：摘掉回读限额 ⇒ 超限文件整份进内存。

    回读限额是这一口**独有**的守卫（写侧那一份在 ``publish`` 里，两回事）：
    「给写侧限额开个只读后门」正是这一格要防的。摘掉后必须真读到 4096 字节，
    还原后必须 ``too_large``——两半都断，才不是一发空跑。
    """
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "big.md").write_bytes(b"x" * 4096)
    policy = rr.WritePolicy(allowed_roots=(root,), limits=rr.WriteLimits(max_file_bytes=64))

    monkeypatch.setattr(
        rr,
        "_read_confined_target",
        lambda target, _policy: (target.read_bytes(), "poisoned-digest"),
    )
    smuggled = rr.read_confined_bytes("big.md", policy=policy)
    assert not isinstance(smuggled, rr.WriteOutcome), (
        "守卫摘掉后仍拒＝回读限额不是这一口的拦点，本发空跑"
    )
    data, _digest = smuggled
    assert len(data) == 4096 and len(_digest) != 64  # 确实绕过了咽喉的摘要

    monkeypatch.undo()
    again = rr.read_confined_bytes("big.md", policy=policy)
    assert isinstance(again, rr.WriteOutcome)
    assert again.reason_code == rr.DenyCode.TOO_LARGE


def test_poison_forbidden_roster_removal_lets_revise_in_place_rewrite_a_persona_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注毒 C（``revise_in_place``）：摘掉禁触名册 ⇒ 读-改-写真的改到人格库里。

    这一发摘的是**整条腿**的守卫（寻址与发布两处都吃它），因此它证的不是
    「某一处有判断」，而是「读-改-写这条腿今天确实靠这枚兜底才进不去禁触区」。
    与 ① 那发（``create_bytes`` 侧）的区别：那边新建、这边改写既有件，
    改写的目标在动手前就已存在，少一层「新建才被拦」的运气。
    """
    root = tmp_path / "vault"
    forbidden = root / "personas"
    forbidden.mkdir(parents=True, exist_ok=True)
    target = forbidden / "核心知识.md"
    target.write_text("# 原样\n", encoding="utf-8")
    before = target.read_bytes()

    monkeypatch.setattr(rr, "_forbidden_destination_reason", lambda _target: "")
    outcome = rr.revise_in_place(
        "personas/核心知识.md",
        lambda data: data.replace("原样".encode(), "改写".encode()),
        policy=_policy(root),
        staging_dir=_staging_dir(tmp_path),
    )
    assert outcome.ok, f"守卫摘掉后仍被拦（{outcome.reason_code}）＝本发空跑，C 格没有牙"
    assert target.read_bytes() != before, "摘了守卫却没改到东西＝改写腿压根没走到落盘"
    assert "改写".encode() in target.read_bytes()

    monkeypatch.undo()
    target.write_bytes(before)
    again = rr.revise_in_place(
        "personas/核心知识.md",
        lambda data: data.replace("原样".encode(), "再改".encode()),
        policy=_policy(root),
        staging_dir=_staging_dir(tmp_path),
    )
    assert again.reason_code == rr.DenyCode.FORBIDDEN_DESTINATION
    assert target.read_bytes() == before, "还原后仍被改动＝上一发不是注毒造成的"
