"""A-8「改落点 + 登记根和守卫补完善」的活性锁（S-A8-IMPL-b，2026-09-27）。

对账依据 = 只读审计 ``SEAT-A8-OUTROOT``（.superpowers/sdd/2026-09-27-fullload/logs/）。
守卫逻辑本体的表格锁在 ``tests/test_safety_exec_paths.py``；本件锁的是**四条生产
写/发通道真的在写盘/取字节之前问了守卫**这一活性面：

① ``paths.check_staged_target`` 单位语义（一因一码：正常在根内放行、逃逸/相对/
   空引用/设备命名空间逐格拒绝）；
② file_gateway bytes 腿与 url 腿——判定排在 mkdir/写字节**之前**：异常拼装从
   「照写不误」变成 ``staging_target_denied``，且根外一个字节都不落、下载器一次
   都不叫（bytes/url 腿历史上是守卫盲区，OUTROOT §1-E/§2-2）；
③ ``restricted_runner.stage_write`` 暂存腿同补——deny ⇒ ``staging_unavailable``
   且暂存目录**不建**（OUTROOT §2-3）；
④ daily_assist ``_assist_dir`` 每次装配问一次 ``check_sendable``：OUT ⇒ 抛
   ``DailyAssistPathDenied`` 且不建目录（fail-closed，绝不回退到别的目录继续写）；
   所有者裁定根（corpus:daily_assist）⇒ 放行；runtime_home 未注册子树 ⇒
   记账放行 + 告警（与出站闸三态口径逐字同源，判定零副本）。

反向锁（红线判据）：允许根之外的绝对路径 ⇒ path 腿拒收、零读字节、票据不签发
（三族外发的全矩阵在 ``tests/test_file_send_receive_parity.py::
test_outside_roots_refused_on_all_three_outbound_legs``，本件带一条精简版，
保证**离开那件也照样有牙**）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.assistant.daily.store import daily_assist as da
from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr
from plugins.bot_unified_runtime.domains.transport.sender import file_gateway as fg_mod
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FileSource,
    FileTransferError,
    FileTransferGateway,
)

_DA_LOGGER = "plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist"


@pytest.fixture(autouse=True)
def _reset_path_domain_policy():
    """进程级缺省策略逐测复位（daily_assist 夹具同型义务，见 test_daily_assist）。"""
    paths.set_default_policy(None)
    yield
    paths.set_default_policy(None)


def _denied_decision(reason_code: str = "traversal_escape") -> paths.PathDecision:
    return paths.PathDecision(
        verdict=paths.VERDICT_DENIED,
        reason_code=reason_code,
        domain=paths.DOMAIN_OUTSIDE,
        target_name="x",
        relative_ref="",
        masked_path="masked",
    )


# ---------------------------------------------------------------------------
# ① check_staged_target 单位语义（一因一码，禁塌兜底）
# ---------------------------------------------------------------------------


def test_check_staged_target_form_table(tmp_path: Path) -> None:
    root = tmp_path / "stg"
    ok = paths.check_staged_target(str(root / "ft_abc_report.pdf"), str(root))
    assert ok.allowed, ok.audit_line()

    escaped = paths.check_staged_target(str(root / ".." / ".." / "victim.bin"), str(root))
    assert escaped.denied and escaped.reason_code == paths.DenyReason.TRAVERSAL_ESCAPE

    far = paths.check_staged_target(str(tmp_path / "outside.bin"), str(root))
    assert far.denied and far.reason_code == paths.DenyReason.TRAVERSAL_ESCAPE

    relative = paths.check_staged_target("stg/x.bin", str(root))
    assert relative.denied and relative.reason_code == paths.DenyReason.RELATIVE_AMBIGUOUS

    empty_target = paths.check_staged_target("", str(root))
    assert empty_target.denied and empty_target.reason_code == paths.DenyReason.EMPTY_PATH

    none_target = paths.check_staged_target(None, str(root))
    assert none_target.denied and none_target.reason_code == paths.DenyReason.EMPTY_PATH

    no_root = paths.check_staged_target(str(root / "x.bin"), "")
    assert no_root.denied and no_root.reason_code == paths.DenyReason.ROOT_UNRESOLVED

    none_root = paths.check_staged_target(str(root / "x.bin"), None)
    assert none_root.denied and none_root.reason_code == paths.DenyReason.ROOT_UNRESOLVED

    device = paths.check_staged_target("\\\\?\\C:\\Windows\\win.ini", str(root))
    assert device.denied and device.reason_code == paths.DenyReason.UNC_OR_DEVICE_PATH


def test_check_staged_target_allows_target_in_absent_root(tmp_path: Path) -> None:
    """正常流：暂存根**尚未 mkdir** 也必须放行——判定排在创建之前而不误杀首写。"""
    root = tmp_path / "not-yet" / "stg"
    verdict = paths.check_staged_target(str(root / "ft_1_x.bin"), str(root))
    assert verdict.allowed, verdict.audit_line()
    assert not root.exists(), "判定本身不得建目录（守卫不落盘）"


# ---------------------------------------------------------------------------
# ② file_gateway bytes/url 腿：写前判定、零落盘、零外呼
# ---------------------------------------------------------------------------


def test_bytes_leg_normal_flow_writes_inside_staging(tmp_path: Path) -> None:
    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging)
    ticket = gateway.stage(
        FileSource(source_kind="bytes", data=b"payload-1", name="报告.pdf")
    )
    assert ticket.local_path is not None
    assert ticket.local_path.resolve().is_relative_to(staging.resolve())
    assert ticket.local_path.read_bytes() == b"payload-1"
    assert ticket.source == "bytes"


def test_bytes_leg_escape_name_is_double_defended(tmp_path: Path) -> None:
    """name 越界写法的**深度防御**锁（诚实口径）：

    ``FileSource.__post_init__`` 对 name 过 ``sanitize_file_name``（取 basename），
    正斜杠/反斜杠逃逸写法在源头即被中和 ⇒ bytes 腿 deny 分支经正常公共 API
    不可达，属第二层防御。本锁把「第一层中和 + 第二层落点仍在暂存根内」都钉死，
    任何一层被摘都会打红。
    """
    src = FileSource(source_kind="bytes", data=b"payload-2", name="../../../victim.bin")
    assert src.name == "victim.bin"  # 第一层：源头 sanitize 锁

    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging)
    ticket = gateway.stage(src)
    assert ticket.local_path is not None
    assert ticket.local_path.resolve().is_relative_to(staging.resolve())
    assert not (tmp_path / "victim.bin").exists()


def test_bytes_leg_guard_denies_before_mkdir(tmp_path: Path, monkeypatch) -> None:
    """守卫活性注入锁：注入 deny 裁决 ⇒ ``staging_target_denied``，暂存目录**不建**。

    与注毒自证配对——摘掉 ``_stage_bytes`` 的判定行，本件必打红。
    """
    monkeypatch.setattr(fg_mod, "check_staged_target", lambda target, root: _denied_decision())
    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging)
    with pytest.raises(FileTransferError) as exc_info:
        gateway.stage(FileSource(source_kind="bytes", data=b"payload-3", name="ok.bin"))
    assert exc_info.value.kind == "staging_target_denied"
    assert not staging.exists(), "守卫拒绝后不得留下暂存目录（判定排在 mkdir 之前）"


def test_url_leg_escape_name_refuses_before_downloader_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """url 腿第①判的真逃逸腿：name 留空 ⇒ 兜底名取自 URL 串**不过 sanitize**。

    兜底名里的反斜杠在 Windows 上是分隔符，拼装后可越出暂存根——这条**真实到达**
    暂存守卫，不靠注入。SSRF 入口闸（check_download_url）另有 downloader 家族的
    既有锁；本件聚焦暂存腿，故把 SSRF 判为放行（monkeypatch），不构成对 SSRF
    面的放宽断言。
    """
    import plugins.bot_unified_runtime.domains.files.sources.downloader as dl_mod

    monkeypatch.setattr(dl_mod, "check_download_url", lambda url: None)
    calls: list[tuple[str, str]] = []

    def _downloader(url: str, target: Path) -> Path:
        calls.append((url, str(target)))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"should-never-happen")
        return target

    bs = chr(92)  # 反斜杠：不经转义地狱，逐字构造
    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging, url_downloader=_downloader)
    with pytest.raises(FileTransferError) as exc_info:
        gateway.stage(
            FileSource(
                source_kind="url",
                url=f"https://example.invalid/p{bs}..{bs}..{bs}victim.bin",
            )
        )
    assert exc_info.value.kind == "staging_target_denied"
    assert calls == [], "第①判必须排在交给下载器之前"
    assert not (tmp_path / "victim.bin").exists()
    assert not staging.exists()


def test_url_leg_landing_outside_staging_refuses_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """url 腿第②判：注入式下载器把件落到暂存根外 ⇒ 票据不认（不发外部）。"""
    import plugins.bot_unified_runtime.domains.files.sources.downloader as dl_mod

    monkeypatch.setattr(dl_mod, "check_download_url", lambda url: None)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stolen = elsewhere / "stolen.bin"

    def _sneaky(url: str, target: Path) -> Path:
        stolen.write_bytes(b"sneaky")
        return stolen

    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging, url_downloader=_sneaky)
    with pytest.raises(FileTransferError) as exc_info:
        gateway.stage(
            FileSource(source_kind="url", url="https://example.invalid/b.bin", name="b.bin")
        )
    assert exc_info.value.kind == "staging_target_denied"
    assert stolen.exists(), "本锁判的是票据不认——下载器乱写的残留正说明第②判必要"


def test_url_leg_normal_flow_returns_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import plugins.bot_unified_runtime.domains.files.sources.downloader as dl_mod

    monkeypatch.setattr(dl_mod, "check_download_url", lambda url: None)

    def _downloader(url: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ok")
        return target

    staging = tmp_path / "gwstg"
    gateway = FileTransferGateway(staging_dir=staging, url_downloader=_downloader)
    ticket = gateway.stage(
        FileSource(source_kind="url", url="https://example.invalid/c.bin", name="c.bin")
    )
    assert ticket.local_path is not None
    assert ticket.local_path.read_bytes() == b"ok"


# ---------------------------------------------------------------------------
# ③ restricted_runner.stage_write：守卫排在 mkdir 之前
# ---------------------------------------------------------------------------


def test_stage_write_normal_flow(tmp_path: Path) -> None:
    staging = tmp_path / "rs"
    staged = rr.stage_write("reports/note.md", staging_dir=str(staging))
    assert isinstance(staged, rr.StagedWrite)
    assert staged.path is not None
    assert staged.path.resolve().is_relative_to(staging.resolve())


def test_stage_write_guard_denies_before_mkdir(tmp_path: Path, monkeypatch) -> None:
    """把守卫判歪（注入 deny）⇒ ``staging_unavailable`` + detail 带原因码 + 目录不建。

    这正是「摘一行守卫必打红」的镜像面：deny 分支在生产路径上正常流不可达
    （名字层已被 ``sanitize_write_segments`` 拦下 ``..``/盘符/设备名），所以本锁
    用注入裁决验**调用位与顺序**，配合注毒自证（见席位日志）构成活性证据。
    """
    staging = tmp_path / "rs"
    monkeypatch.setattr(
        paths, "check_staged_target", lambda target, root: _denied_decision()
    )
    outcome = rr.stage_write("note.md", staging_dir=str(staging))
    assert isinstance(outcome, rr.WriteOutcome)
    assert outcome.ok is False
    assert outcome.reason_code == rr.DenyCode.STAGING_UNAVAILABLE
    assert outcome.detail == "traversal_escape", outcome.detail
    assert not staging.exists(), "守卫拒绝后不得建暂存目录（判定排在 mkdir 之前）"


# ---------------------------------------------------------------------------
# ④ daily_assist._assist_dir：装配即问守卫，OUT ⇒ 断写、不回退
# ---------------------------------------------------------------------------


def _da_config(dir_value: str) -> SimpleNamespace:
    return SimpleNamespace(bot_daily_assist_dir=dir_value)


def test_assist_dir_outside_root_raises_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    paths.set_default_policy(None)
    # 反向锁本体：允许根之外的绝对落点 ⇒ 拒（不建目录、不写一个字节的语料）。
    victim = tmp_path.parents[1] / "a8-outside-corpus"
    with pytest.raises(da.DailyAssistPathDenied) as exc_info:
        da._assist_dir(_da_config(str(victim)))
    assert exc_info.value.reason_code == paths.DenyReason.OUTSIDE_ALLOWED_ROOTS
    assert not victim.exists(), "fail-closed：拒了就必须什么都没发生"


def test_assist_dir_default_relative_resolves_inside_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    paths.set_default_policy(None)
    base = da._assist_dir(_da_config("data/daily_assist"))
    assert Path(str(base)).resolve().is_relative_to(tmp_path.resolve())


def test_assist_dir_corpus_root_allowed_via_default_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """所有者裁定根（corpus:daily_assist）在缺省策略在册 ⇒ 其下子目录放行。

    名册本身恰一枚 + 逐字符的锁在 ``test_safety_exec_paths.py``；本锁验「登记
    ⇒ 真放行」的活性腿——两边缺一条，登记根就只是散文。
    """
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    paths.set_default_policy(None)
    corpus = [
        root for label, root in paths.default_policy().readable_roots
        if label == "corpus:daily_assist"
    ]
    assert len(corpus) == 1, f"裁定根名册走样：{corpus}"
    base = da._assist_dir(_da_config(str(corpus[0] / "bot-sub")))
    assert Path(str(base)).resolve() == (corpus[0] / "bot-sub").resolve()


def test_assist_dir_needs_review_logs_and_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """runtime_home 之下、登记名册之外 ⇒ 记账放行（与出站闸三态同源，不私设第四态）。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    paths.set_default_policy(None)
    zone = tmp_path.parent / "a8-review-zone"  # runtime_home 内、data 根外
    with caplog.at_level(logging.WARNING, logger=_DA_LOGGER):
        base = da._assist_dir(_da_config(str(zone)))
    assert Path(str(base)).resolve() == zone.resolve()
    assert any("待评审" in record.getMessage() for record in caplog.records), (
        "needs_review 必须留一行账（否则第 4 态被读成 allowed）"
    )


# ---------------------------------------------------------------------------
# ⑤ path 腿反向锁（精简版，判「根外绝对路径 ⇒ 拒收、不读字节、不签票据」）
# ---------------------------------------------------------------------------


def test_path_leg_outside_root_refused_without_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = paths.default_policy()
    active = paths.build_policy(
        workspace_root=real.workspace_root,
        runtime_data_root=real.runtime_data_root,
        extra_readable_roots=(("pytest-tmp", tmp_path),),
    )
    paths.set_default_policy(active)
    try:
        gateway = FileTransferGateway(staging_dir=tmp_path / "gwstg")
        victim = tmp_path.parent / "a8-victim.txt"
        victim.write_bytes(b"TOP-SECRET-BYTES")
        reads: list[str] = []

        def _probe_sha(resolved: object) -> str:
            reads.append(str(resolved))
            return ""

        monkeypatch.setattr(fg_mod, "_sha256_of_file", _probe_sha)
        with pytest.raises(FileTransferError) as exc_info:
            gateway.stage(FileSource(source_kind="path", path=str(victim)))
        assert exc_info.value.kind == "path_domain_denied"
        assert reads == [], "取字节前判定：拒绝路径上 _sha256_of_file 一次都不许被叫"
        assert victim.read_bytes() == b"TOP-SECRET-BYTES"
    finally:
        paths.set_default_policy(None)
