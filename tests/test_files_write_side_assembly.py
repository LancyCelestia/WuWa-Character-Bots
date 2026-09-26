"""文件写盘装配口回归锁（需求 16(2)(4) · S-FILES-LAND，2026-09-26）。

五组断言（与简报第②③⑥件逐条对应）：

① 六枚 config 键的缺省值与 ``restricted_runner`` 内建缺省**逐字节等值**
   （⇒「现网零变更」不是口头承诺；谁改其一、这一枚点名另一处，逼两面同改）；
② 命令面解析（``parse_file_revise_command``）；
③ 端到端全链：命令文本 → 解析 → 裁决(Permit) → 容器判定 → 落盘 → 回读 → 出站件
   ——「改这份文档」的工程链路整条打通。注意：本域的 decision/transform 由装配层
   注入，会话入口在根文件的施工单里（席位日志 §施工单一），今天没有真实用户能
   打到这条链；
④ fail-closed 四态：总闸关 / 真 decide 的当日裁决（file.write 在册 R1 ⇒
   ConsentRequired）/ decision 缺席 / 落点禁触——每一态都**一个字节都不动**、
   原文件逐字节不变、配额不烧；
⑤ 正向名册真接上：``external_verdict=sendable_verdict`` 不是摆设——把进程级缺省
   策略换成不认识写侧根的假根，合法文件名词照样被拒。

全部离线、零网络，只写 ``tmp_path``；**不开生产 ``.env``、不碰真运行数据根**
（路径域判定用 ``paths.set_default_policy`` 假根，先例见
``tests/test_safety_exec_paths.py::wired_policy``）。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.core.safety_exec import paths
from plugins.bot_unified_runtime.domains.core.safety_exec import policy as safety_policy
from plugins.bot_unified_runtime.domains.core.safety_exec.action_catalog import ActionId
from plugins.bot_unified_runtime.domains.core.safety_exec.trust import TrustLevel
from plugins.bot_unified_runtime.domains.files.capabilities import file_exchange as fx
from plugins.bot_unified_runtime.domains.files.sender import restricted_runner as rr
from plugins.bot_unified_runtime.domains.media.digest import media_digest

_DRIVE_FORM_RE = re.compile(r"[A-Za-z]:[\\/]")

_PERMIT = safety_policy.Permit(
    action=ActionId.FILE_WRITE,
    role_floor="trusted",
    tier="R0",
    landing_check_required=True,
)
"""裁决放行的**测试凭证**：今天的真 ``decide`` 对 file.write(R1) 只会给
ConsentRequired（确认回路未接），所以全链组③必须显式交 Permit 形状——这枚常量
就是「装配层拿到了真放行」这一前提的**被测物**，不是绕闸的后门：入口签名
``decision`` 必填，缺它连调用都完不成。"""


@pytest.fixture
def wired_paths(tmp_path: Path) -> Iterator[paths.PathDomainPolicy]:
    """把假根（``tmp_path`` 为工作区）接到进程级缺省判定口，用例结束复位。"""
    active = paths.build_policy(workspace_root=tmp_path)
    paths.set_default_policy(active)
    try:
        yield active
    finally:
        paths.set_default_policy(None)


def _conf(tmp_path: Path, **overrides: object) -> Config:
    base: dict[str, object] = {
        "bot_download_dir": str(tmp_path / "dl"),
        "bot_files_write_allowed_dirs": [str(tmp_path / "out")],
    }
    base.update(overrides)
    return Config(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ① 缺省等值（「现网零变更」的机器形态）
# ---------------------------------------------------------------------------


def test_config_defaults_match_the_runner_builtins_exactly() -> None:
    fresh = Config()
    assert fresh.bot_files_write_enabled is True, "总闸关=导出腿当场断，缺省必须开"
    assert fresh.bot_files_write_allowed_dirs == [], "白名单缺省空=装配回落 export"
    assert fresh.bot_files_write_max_bytes == rr.DEFAULT_MAX_FILE_BYTES, (
        f"现算 {fresh.bot_files_write_max_bytes} ≠ 运行器 {rr.DEFAULT_MAX_FILE_BYTES}"
    )
    assert fresh.bot_files_write_daily_create == rr.DEFAULT_DAILY_CREATE_LIMIT
    assert fresh.bot_files_write_daily_replace == rr.DEFAULT_DAILY_REPLACE_LIMIT
    assert fresh.bot_files_read_confined_max_bytes == rr.DEFAULT_MAX_FILE_BYTES


def test_write_policy_from_config_falls_back_to_export_dir(tmp_path: Path) -> None:
    cfg = _conf(tmp_path, bot_files_write_allowed_dirs=[])
    policy = fx.write_policy_from_config(cfg)
    assert [str(r).casefold() for r in policy.allowed_roots] == [
        str(tmp_path / "dl" / "export").casefold()
    ]
    # 前席建议口径：装配层把正向注册名册那一半也接上（缺省兜底只负责禁触那一族）。
    assert policy.external_verdict is fx.sendable_verdict
    assert policy.limits.max_file_bytes == cfg.bot_files_write_max_bytes


# ---------------------------------------------------------------------------
# ② 命令面解析
# ---------------------------------------------------------------------------


def test_revise_command_parsing_shapes() -> None:
    assert fx.is_file_revise_command("改文件 note.md 在文末加一行签名")
    assert fx.parse_file_revise_command("/bot 改文件 note.md 把标题换掉") == (
        "note.md",
        "把标题换掉",
    )
    assert fx.parse_file_revise_command("改文件 note.md") is None  # 裸名不带指令
    assert fx.parse_file_revise_command("今天天气如何") is None
    assert fx.parse_file_revise_command("改文件 ../../evil.md 越界") == (
        "../../evil.md",
        "越界",
    ), "解析只负责拆段；越界由咽喉消毒拒绝（④组钉它写不进也读不到）"


# ---------------------------------------------------------------------------
# ③ 端到端全链：命令文本→解析→裁决→容器→落盘→回读→出站件
# ---------------------------------------------------------------------------


def test_full_chain_command_to_outbound_parts(tmp_path: Path, wired_paths) -> None:
    cfg = _conf(tmp_path)
    ledger = rr.DailyQuotaLedger()
    day = {"ledger": ledger, "date_key": lambda: "D1", "staging_dir": tmp_path / "_stg"}

    name, instruction = fx.parse_file_revise_command("改文件 note.md 补一段")
    assert (name, instruction) == ("note.md", "补一段")

    created = fx.run_document_create(name, "# 初稿\n", config=cfg, decision=_PERMIT, **day)
    assert created.ok, created.reply_text
    assert created.file_parts and created.file_parts[0]["name"] == "note.md"
    assert not _DRIVE_FORM_RE.search(created.reply_text), created.reply_text
    assert Path(created.file_parts[0]["file"]).is_file()

    revised = fx.run_document_revise(
        name,
        lambda data: data + "\n> 补的一段\n".encode(),
        config=cfg,
        decision=_PERMIT,
        **day,
    )
    assert revised.ok, revised.reply_text
    assert revised.file_parts[0]["file"] == created.file_parts[0]["file"]

    found = fx.read_document_file(name, config=cfg)
    assert not isinstance(found, fx.DocumentOpResult)
    data, digest = found
    assert "补的一段" in data.decode("utf-8")
    assert digest == media_digest(data)

    located = fx.resolve_document_ref(name, config=cfg)
    assert isinstance(located, Path) and located.is_file()

    # 配额账：一创一改各记一次（按「根×日×动词」）。
    assert ledger.used("out", "D1", "create") == 1
    assert ledger.used("out", "D1", "replace") == 1

    # 同字节回写＝ok 但零字节、不再烧配额（运行器教义，装配口原样透出）。
    same = fx.run_document_revise(name, lambda data: data, config=cfg, decision=_PERMIT, **day)
    assert same.ok and "没动笔" in same.reply_text
    assert ledger.used("out", "D1", "replace") == 1

    # 「修改」动词绝不新建：改一份不存在的。
    ghost = fx.run_document_revise(
        "ghost.md", lambda data: b"x", config=cfg, decision=_PERMIT, **day
    )
    assert not ghost.ok and ghost.reason_code == "target_missing"


# ---------------------------------------------------------------------------
# ④ fail-closed 四态：每一态都不许动字节
# ---------------------------------------------------------------------------


def _seed(tmp_path: Path, cfg: Config, wired_paths) -> Path:
    seeded = fx.run_document_create("keep.md", "原文\n", config=cfg, decision=_PERMIT,
                                    staging_dir=tmp_path / "_stg")
    assert seeded.ok, seeded.reply_text
    return Path(seeded.file_parts[0]["file"])


def test_disabled_master_gate_refuses_and_writes_nothing(tmp_path: Path, wired_paths) -> None:
    cfg = _conf(tmp_path, bot_files_write_enabled=False)
    res = fx.run_document_create("x.md", "内容", config=cfg, decision=_PERMIT)
    assert not res.ok and res.reason_code == "write_disabled"
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_real_decide_blocks_until_file_consent_loop_lands(tmp_path: Path, wired_paths) -> None:
    """当日真裁决：管理员级 actor 打 ``改文件`` 也**只到 ConsentRequired 为止**。

    这一枚钉的是「不自批」：``file.write`` 在册 R1，确认回路（consent Wave 2）没接
    到文件动作前，装配入口一律拒写——哪怕角色下限过了。原文件保持逐字节、配额不烧。
    """
    cfg = _conf(tmp_path)
    seed = _seed(tmp_path, cfg, wired_paths)
    before = seed.read_bytes()
    decision = fx.adjudicate_file_write(TrustLevel.T1, ["trusted"])
    assert isinstance(decision, safety_policy.ConsentRequired), (
        f"file.write 的当日真裁决形态变了：{decision!r}"
    )
    res = fx.run_document_revise(
        "keep.md", lambda data: data + b"appended\n", config=cfg, decision=decision,
        staging_dir=tmp_path / "_stg",
    )
    assert not res.ok and res.reason_code == "consent_required"
    assert seed.read_bytes() == before, "被拒也要一字不动（拒了还写＝谎报语义）"


def test_deny_from_decide_is_named_not_silent(tmp_path: Path, wired_paths) -> None:
    cfg = _conf(tmp_path)
    decision = fx.adjudicate_file_write(None, None)  # 可信级未申报 → Deny(untrusted_source)
    assert isinstance(decision, safety_policy.Deny)
    res = fx.run_document_create("x.md", "内容", config=cfg, decision=decision)
    assert not res.ok and res.reason_code == "adjudicate:untrusted_source"
    assert "没被放行" in res.reply_text


def test_missing_decision_object_cannot_reach_the_throat(tmp_path: Path, wired_paths) -> None:
    """decision 传 ``None``＝没问过裁决口：按拒处理（入口签名必填 + 运行期再兜一道）。"""
    cfg = _conf(tmp_path)
    res = fx.run_document_create("x.md", "内容", config=cfg, decision=None)
    assert not res.ok
    assert not (tmp_path / "out" / "x.md").exists()


def test_forbidden_personas_zone_root_is_denied_through_assembly(tmp_path: Path, wired_paths) -> None:
    """白名单被配歪到人格库 ⇒ 装配口也必须当场拦住（禁触那一族不依赖调用方）。"""
    cfg = _conf(tmp_path, bot_files_write_allowed_dirs=[str(tmp_path / "personas" / "shorekeeper")])
    res = fx.run_document_create("identity.md", "冒充人格库", config=cfg, decision=_PERMIT,
                                 staging_dir=tmp_path / "_stg")
    assert not res.ok
    assert res.reason_code in {"external_guard_denied", "forbidden_destination"}
    assert not (tmp_path / "personas" / "shorekeeper" / "identity.md").exists()


def test_traversal_in_command_name_is_rejected(tmp_path: Path, wired_paths) -> None:
    cfg = _conf(tmp_path)
    res = fx.run_document_create("../../escape.md", "越界", config=cfg, decision=_PERMIT,
                                 staging_dir=tmp_path / "_stg")
    assert not res.ok and res.reason_code in {"traversal_denied", "bad_name"}


# ---------------------------------------------------------------------------
# ⑤ 正向名册（sendable_verdict）真有牙
# ---------------------------------------------------------------------------


def test_forward_roster_denies_writes_when_policy_does_not_know_the_root(tmp_path: Path) -> None:
    """把缺省判定换成**不认识写侧根**的假根 ⇒ 合法名字也被 ``sendable_verdict`` 拦。

    反向对照：③组在认识根的策略下同名词放行。两半合起来证明装配层那一半注入缝
    不是装饰（运行器缺省的禁触直判只兜 forbidden 那一族，正向放行由这里判）。
    """
    stranger = paths.build_policy(
        workspace_root=tmp_path / "other-workspace",
        runtime_data_root=tmp_path / "other-runtime" / "data",
    )
    paths.set_default_policy(stranger)
    try:
        cfg = _conf(tmp_path)
        res = fx.run_document_create("legal.md", "内容", config=cfg, decision=_PERMIT,
                                     staging_dir=tmp_path / "_stg")
        assert not res.ok and res.reason_code == "external_guard_denied"
    finally:
        paths.set_default_policy(None)
    # 复位后（③组同形态的根被接进判定面）同一动作成功——证明上面的红来自名册本身。
    wired = paths.build_policy(workspace_root=tmp_path)
    paths.set_default_policy(wired)
    try:
        cfg = _conf(tmp_path)
        again = fx.run_document_create("legal.md", "内容", config=cfg, decision=_PERMIT,
                                       staging_dir=tmp_path / "_stg")
        assert again.ok, again.reply_text
    finally:
        paths.set_default_policy(None)
