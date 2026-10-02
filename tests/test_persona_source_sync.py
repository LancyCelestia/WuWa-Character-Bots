"""人格源-运行时副本一致性门测试（同步声明机制 · ISYNC v2）.

ISYNC 根治的洞（旧实现只钉副本哈希、源侧演进纯信息性 → 改 personas/ 源
门照样全绿；副本缺失一律 skip → 部署机生产人格正文丢失也全绿）：

- 源侧快照升格为**判定项**：改源 → 必红（SOURCE_DRIFT）。
- 覆盖面自锁：personas/shorekeeper 下新增文件既不在覆盖集也不在显式豁免 → 必红。
- 显式声明的副本路径缺失 → 必红（COPY_MISSING_DECLARED）；仅约定回退路径才允许 skip。
- --adopt 语义固定为「重录人工审阅凭证」，**绝不做任何拷贝**，且必须带 --note。
- 负样本自检（防「恒绿空转门」）：每条红态都要能用内嵌伪状态/伪键被抓红。

全离线（tmp_path + 把 sync_mod.REPO_ROOT 指到假仓库根），零真实 personas/ 与 Runtime 写入。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.sync_persona_source as sync_mod

_SOURCE_TEXT = "守岸人人格源 v1：清冷而温柔。\n"


# ---------------------------------------------------------------------------
# 假仓库夹具：真实 personas/ 与 Runtime 副本全程只读，零接触
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 REPO_ROOT 指到 tmp 假仓库，并铺好覆盖集内的源文件。"""
    root = tmp_path / "repo"
    for rel in sync_mod.SOURCE_SNAPSHOT_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_SOURCE_TEXT, encoding="utf-8")
    monkeypatch.setattr(sync_mod, "REPO_ROOT", root)
    return root


@pytest.fixture
def copy_path(fake_repo: Path) -> Path:
    copy = fake_repo.parent / "守岸人_核心人格.md"
    copy.write_text("守岸人核心人格 v1\n", encoding="utf-8")
    return copy


@pytest.fixture
def anchor_path(fake_repo: Path) -> Path:
    return fake_repo.parent / "anchor.json"


def _adopt(copy: Path, anchor: Path) -> dict[str, object]:
    return sync_mod.adopt(copy, anchor, note="离线夹具审阅凭证")


# ---------------------------------------------------------------------------
# 1. 核心根治：改源 → 门必红（旧实现此处返回 OK，是本席立项目的）
# ---------------------------------------------------------------------------


def test_source_edit_turns_gate_red(fake_repo: Path, copy_path: Path, anchor_path: Path) -> None:
    _adopt(copy_path, anchor_path)
    assert sync_mod.check(copy_path, anchor_path).status == sync_mod.OK

    # 只改 personas/ 源；副本与锚定一动不动 —— 这就是「改一处、其余静默陈旧」的场景
    target = fake_repo / "personas" / "shorekeeper" / "identity.md"
    target.write_text(_SOURCE_TEXT + "\n## 新增硬红线：绝不可攻击管理员\n", encoding="utf-8")

    result = sync_mod.check(copy_path, anchor_path)
    assert result.status == sync_mod.SOURCE_DRIFT
    assert result.is_red
    assert "personas/shorekeeper/identity.md" in result.message
    assert "--adopt" in result.message


def test_source_edit_red_persists_until_adopted(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    """陈旧副本 → 门持续红；人工对齐 + --adopt 后才复绿（红不是「提示后自消」）。"""
    _adopt(copy_path, anchor_path)
    src = fake_repo / "personas" / "shorekeeper" / "knowledge" / "守岸人_核心知识.md"
    src.write_text(_SOURCE_TEXT + "补充设定。\n", encoding="utf-8")
    assert sync_mod.check(copy_path, anchor_path).is_red
    copy_path.write_text("守岸人核心人格 v2（已把新设定蒸馏进正文）\n", encoding="utf-8")
    # 改副本后源也仍与旧锚不符：两态之一为红即可持续拦住
    assert sync_mod.check(copy_path, anchor_path).is_red
    _adopt(copy_path, anchor_path)
    assert sync_mod.check(copy_path, anchor_path).status == sync_mod.OK


def test_cli_source_drift_exit_code_1(
    fake_repo: Path, copy_path: Path, anchor_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = ["--check", "--copy", str(copy_path), "--anchor", str(anchor_path)]
    assert sync_mod.main([*base, "--adopt", "--note", "cli"]) == 0
    (fake_repo / "personas" / "shorekeeper" / "aliases.txt").write_text(
        "岸宝,守岸人,新增别名\n", encoding="utf-8"
    )
    assert sync_mod.main(base) == 1  # 改源 → 红 → 非零退出
    printed = capsys.readouterr().out
    assert "自锚定后已演进" in printed and "personas/shorekeeper/aliases.txt" in printed


# ---------------------------------------------------------------------------
# 2. 副本侧漂移（既有能力保持）
# ---------------------------------------------------------------------------


def test_drift_after_copy_edit_red(fake_repo: Path, copy_path: Path, anchor_path: Path) -> None:
    _adopt(copy_path, anchor_path)
    copy_path.write_text("守岸人核心人格 v2 被人单方面改了\n", encoding="utf-8")
    result = sync_mod.check(copy_path, anchor_path)
    assert result.status == sync_mod.DRIFT
    assert result.is_red


def test_copy_unreadable_red(fake_repo: Path, anchor_path: Path) -> None:
    copy_dir = fake_repo.parent / "守岸人_核心人格.md"
    copy_dir.mkdir()  # 目录：read_bytes 抛 OSError 子类
    anchor_path.write_text(json.dumps({"copy_sha256": "x" * 64}), encoding="utf-8")
    result = sync_mod.check(copy_dir, anchor_path)
    assert result.status == sync_mod.COPY_UNREADABLE
    assert result.is_red


def test_anchor_missing_red(fake_repo: Path, copy_path: Path) -> None:
    result = sync_mod.check(copy_path, fake_repo.parent / "anchor.json")
    assert result.status == sync_mod.ANCHOR_MISSING
    assert result.is_red


def test_anchor_corrupted_red(fake_repo: Path, copy_path: Path) -> None:
    anchor = fake_repo.parent / "anchor.json"
    anchor.write_text("{ 不是 json", encoding="utf-8")
    result = sync_mod.check(copy_path, anchor)
    assert result.status == sync_mod.ANCHOR_MISSING
    assert result.is_red


# ---------------------------------------------------------------------------
# 3. 副本缺失：声明=红、约定回退=skip，以及两个显式出口
# ---------------------------------------------------------------------------


def test_declared_copy_missing_is_red(fake_repo: Path, anchor_path: Path) -> None:
    missing = fake_repo.parent / "未部署的生产副本.md"
    result = sync_mod.check(missing, anchor_path, declared_copy=True)
    assert result.status == sync_mod.COPY_MISSING_DECLARED
    assert result.is_red
    assert "--allow-missing-copy" in result.message


def test_check_default_is_fail_closed_on_missing_copy(
    fake_repo: Path, anchor_path: Path
) -> None:
    """不传 declared_copy 时必须按「声明」处理（默认红），防调用方漏传导致静默放行。"""
    result = sync_mod.check(fake_repo.parent / "无.md", anchor_path)
    assert result.is_red


def test_undeclared_fallback_copy_missing_is_skip(
    fake_repo: Path, anchor_path: Path
) -> None:
    result = sync_mod.check(
        fake_repo.parent / "无.md", anchor_path, declared_copy=False
    )
    assert result.status == sync_mod.SKIP_COPY_MISSING
    assert result.is_skip and not result.is_red


def test_require_copy_flag_overrides_to_red(fake_repo: Path, anchor_path: Path) -> None:
    missing = fake_repo.parent / "无.md"
    result = sync_mod.check(missing, anchor_path, declared_copy=False, require_copy=True)
    assert result.status == sync_mod.COPY_MISSING_DECLARED
    assert result.is_red


def test_allow_missing_copy_flag_overrides_to_skip(
    fake_repo: Path, anchor_path: Path
) -> None:
    missing = fake_repo.parent / "无.md"
    result = sync_mod.check(missing, anchor_path, declared_copy=True, allow_missing_copy=True)
    assert result.status == sync_mod.SKIP_COPY_MISSING
    assert result.is_skip


def test_cli_missing_copy_exit_codes(
    fake_repo: Path, anchor_path: Path, copy_path: Path
) -> None:
    _adopt(copy_path, anchor_path)
    missing = str(fake_repo.parent / "无.md")
    common = ["--check", "--anchor", str(anchor_path), "--copy", missing]
    assert sync_mod.main([*common]) == 1  # CLI --copy = 显式声明 → 红
    assert sync_mod.main([*common, "--allow-missing-copy"]) == 0  # 显式放行 → 0
    assert sync_mod.main([*common, "--require-copy"]) == 1  # 强制红 → 1


def test_cli_require_and_allow_copy_are_mutually_exclusive(
    fake_repo: Path, anchor_path: Path
) -> None:
    """两个出口同时给出＝放行动作不确定，argparse 直接拒绝（exit 2），不猜优先级。"""
    with pytest.raises(SystemExit) as exc:
        sync_mod.main(
            [
                "--check",
                "--anchor",
                str(anchor_path),
                "--copy",
                str(fake_repo.parent / "无.md"),
                "--require-copy",
                "--allow-missing-copy",
            ]
        )
    assert exc.value.code == 2


def test_resolve_copy_path_reports_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    """路径来源必须可判别：CLI/env/.env=声明，常量回退=未声明（不靠猜）。"""
    monkeypatch.setenv("BOT_PERSONA_FILES", '["C:/nowhere/x.md"]')
    target = sync_mod.resolve_copy_path()
    assert target.declared is True and target.origin == "env"

    monkeypatch.delenv("BOT_PERSONA_FILES")
    monkeypatch.setattr(sync_mod, "ENV_FILE", Path("不存在的.env"))
    fallback = sync_mod.resolve_copy_path()
    assert fallback.declared is False and fallback.origin == "fallback"
    assert fallback.path == sync_mod.DEFAULT_COPY_FALLBACK


# ---------------------------------------------------------------------------
# 4. --adopt 语义：只重录锚定，零拷贝，且强制审阅说明
# ---------------------------------------------------------------------------


def test_adopt_requires_note(fake_repo: Path, copy_path: Path, anchor_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        sync_mod.adopt(copy_path, anchor_path, note="")
    assert "note" in str(exc.value).lower() or "审阅" in str(exc.value)
    assert not anchor_path.exists()  # 拒绝时不留半成品


def test_adopt_never_writes_the_copy(fake_repo: Path, copy_path: Path, anchor_path: Path) -> None:
    """语义锁：--adopt 前后副本字节完全不变（防未来有人把它改成「顺手拷贝」）。"""
    before = copy_path.read_bytes()
    src = fake_repo / "personas" / "shorekeeper" / "identity.md"
    src.write_bytes(before + "\n# 源与副本内容不同\n".encode())
    _adopt(copy_path, anchor_path)
    assert copy_path.read_bytes() == before
    assert hashlib.sha256(copy_path.read_bytes()).hexdigest() == _anchor(anchor_path)["copy_sha256"]


def test_adopt_refuses_when_covered_source_missing(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    """覆盖集内文件缺失时拒绝锚定：否则锚会把 <missing> 当哈希钉住，门永久假绿。"""
    (fake_repo / "personas" / "shorekeeper" / "identity.md").unlink()
    with pytest.raises(SystemExit):
        _adopt(copy_path, anchor_path)
    assert not anchor_path.exists()


def _anchor(anchor_path: Path) -> dict[str, object]:
    return json.loads(anchor_path.read_text(encoding="utf-8"))


def test_anchor_records_all_covered_sources(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    _adopt(copy_path, anchor_path)
    data = _anchor(anchor_path)
    snap = data["source_snapshot"]
    assert isinstance(snap, dict)
    assert set(snap) == set(sync_mod.SOURCE_SNAPSHOT_FILES)
    assert all(len(str(v)) == 64 for v in snap.values())
    assert data["schema"] == sync_mod.ANCHOR_SCHEMA


# ---------------------------------------------------------------------------
# 5. 覆盖面自锁：新增源文件不可能静默漏出门
# ---------------------------------------------------------------------------


def test_new_persona_file_outside_snapshot_is_red(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    _adopt(copy_path, anchor_path)
    stray = fake_repo / "personas" / "shorekeeper" / "knowledge" / "新设定.md"
    stray.write_text("新增的一整节设定\n", encoding="utf-8")
    result = sync_mod.check(copy_path, anchor_path)
    assert result.status == sync_mod.SOURCE_UNCOVERED_FILE
    assert result.is_red
    assert "新设定.md" in result.message


def test_anchor_missing_entry_for_covered_file_is_red(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    """门升级（覆盖集新增一项）后，旧锚缺该文件哈希 → 一次性补锚红，不得静默当一致。"""
    data = _anchor(_adopt(copy_path, anchor_path) and anchor_path)
    assert isinstance(data["source_snapshot"], dict)
    del data["source_snapshot"]["personas/shorekeeper/identity.md"]
    anchor_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    result = sync_mod.check(copy_path, anchor_path)
    assert result.status == sync_mod.SOURCE_UNCOVERED_AT_ANCHOR
    assert result.is_red


def test_snapshot_and_source_dir_stay_in_lockstep() -> None:
    """真仓库常驻门：personas/shorekeeper 磁盘文件 == 覆盖集 ∪ 显式豁免（自锁不失守）。"""
    on_disk = {
        p.relative_to(sync_mod.persona_source_dir()).as_posix()
        for p in sync_mod.persona_source_dir().rglob("*")
        if p.is_file()
    }
    covered = {
        Path(rel).relative_to("personas/shorekeeper").as_posix()
        for rel in sync_mod.SOURCE_SNAPSHOT_FILES
    }
    assert on_disk == covered | set(sync_mod.SOURCE_EXCLUDED), (
        f"人格源覆盖集与磁盘不一致（补 SOURCE_SNAPSHOT_FILES 或补带理由的 SOURCE_EXCLUDED）："
        f"仅磁盘有={sorted(on_disk - covered - set(sync_mod.SOURCE_EXCLUDED))} "
        f"仅覆盖集有={sorted(covered - on_disk)}"
    )


def test_source_excluded_entries_are_valid() -> None:
    """豁免表不得静默增长：每条必须带非空理由，且对应文件确实在磁盘上。"""
    for rel, reason in sync_mod.SOURCE_EXCLUDED.items():
        assert isinstance(reason, str) and reason.strip(), f"豁免 {rel} 缺理由"
        assert (sync_mod.persona_source_dir() / rel).is_file(), f"豁免 {rel} 已不存在，请摘除"


def test_glossary_seed_is_covered_by_snapshot() -> None:
    """实测补捞的第二个洞：worldview_glossary.md 生产被读（glossary.py 随包种子回退），
    旧覆盖集里没有它 → 必须已纳入，否则本席根治不彻底。"""
    assert "personas/shorekeeper/knowledge/worldview_glossary.md" in set(
        sync_mod.SOURCE_SNAPSHOT_FILES
    )


# ---------------------------------------------------------------------------
# 6. 负样本自检：防「恒绿空转门」（解析器/判定表退化时先红在这里）
# ---------------------------------------------------------------------------


def test_gate_has_teeth_negative_probes(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    reds = {
        sync_mod.DRIFT,
        sync_mod.SOURCE_DRIFT,
        sync_mod.SOURCE_UNCOVERED_FILE,
        sync_mod.SOURCE_UNCOVERED_AT_ANCHOR,
        sync_mod.COPY_MISSING_DECLARED,
        sync_mod.COPY_UNREADABLE,
        sync_mod.ANCHOR_MISSING,
    }
    assert reds <= sync_mod.RED_STATUSES, f"红态登记表缺项：{sorted(reds - sync_mod.RED_STATUSES)}"
    assert sync_mod.OK not in sync_mod.RED_STATUSES
    assert sync_mod.SKIP_COPY_MISSING not in sync_mod.RED_STATUSES
    # 判定表非空转：每条红态都真实存在于 check() 可达路径（本文件逐条有正向用例）
    _adopt(copy_path, anchor_path)
    assert sync_mod.check(copy_path, anchor_path).is_red is False
    (fake_repo / "personas" / "shorekeeper" / "identity.md").write_text(
        "改了\n", encoding="utf-8"
    )
    assert sync_mod.check(copy_path, anchor_path).is_red is True


# ---------------------------------------------------------------------------
# 7. 现网常驻门（真实路径，只读；不改任何文件、不写 Runtime）
# ---------------------------------------------------------------------------


def test_live_persona_gate_green() -> None:
    """真实锚定 × 真实源 × 真实副本：整门必须绿（红=人格源/副本已分叉，须人工对齐后 --adopt）。"""
    target = sync_mod.resolve_copy_path()
    if not target.declared and not target.path.exists():
        pytest.skip(f"本机未声明生产人格副本（bot 未部署），门跳过：{target.path}")
    result = sync_mod.check(target.path, sync_mod.ANCHOR_PATH, declared_copy=target.declared)
    assert not result.is_red, result.message
    assert result.status == sync_mod.OK, result.message


def test_anchor_deliverable_schema() -> None:
    data = _anchor(sync_mod.ANCHOR_PATH)
    for key in (
        "schema",
        "copy_path",
        "copy_sha256",
        "adopted_at",
        "source_snapshot",
        "note",
    ):
        assert key in data, f"锚定缺字段 {key}"
    assert len(str(data["copy_sha256"])) == 64
    assert data["schema"] == sync_mod.ANCHOR_SCHEMA
    assert str(data["note"]).strip(), "现网锚定缺人工审阅说明（ISYNC 起 --adopt 强制带 --note）"
    assert isinstance(data["source_snapshot"], dict)
    assert set(data["source_snapshot"]) == set(sync_mod.SOURCE_SNAPSHOT_FILES)


# ---------------------------------------------------------------------------
# 8. 第三人格格（S5c 参数化 · S5d 补锁）：一格一本审阅凭证，绝不端别人家的
#    判据形态沿用上面 1-7 节（正向红态逐条 + CLI 退出码 + 负样本自检），不另起炉灶。
# ---------------------------------------------------------------------------

_THIRD = "seat-s5d-third"
_THIRD_SOURCE_TEXT = "第三人格里格源 v1：与主人格逐字不同。\n"


@pytest.fixture
def third_persona(fake_repo: Path) -> str:
    """假仓库里另铺一格人格源（只备附属三件，绝不铺主人格独有的知识册）。"""
    root = fake_repo / sync_mod.persona_source_root(_THIRD)
    root.mkdir(parents=True)
    for name in sync_mod.PERSONA_ATTACHED_FILES:
        (root / name).write_text(_THIRD_SOURCE_TEXT, encoding="utf-8")
    return _THIRD


@pytest.fixture
def third_copy(fake_repo: Path) -> Path:
    copy = fake_repo.parent / f"{_THIRD}_生产副本.md"
    copy.write_text(f"{_THIRD} 生产人格正文 v1\n", encoding="utf-8")
    return copy


def _third_args(copy: Path, anchor: Path, persona_id: str = _THIRD) -> list[str]:
    return [
        "--check",
        "--persona",
        persona_id,
        "--copy",
        str(copy),
        "--anchor",
        str(anchor),
    ]


def test_missing_persona_root_reports_not_enrolled_not_coverage(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    """根不存在＝「这一格没有可审阅的源」，绝不报成覆盖面漏文件（漏文件的处置是加覆盖集，
    照着做就会把别人的目录认领成自己这一格的源——台账 #66★ 同型）。"""
    ghost = "seat-s5d-ghost"
    result = sync_mod.check(copy_path, anchor_path, persona_id=ghost)
    assert result.status == sync_mod.PERSONA_NOT_ENROLLED
    assert result.is_red and not result.is_skip
    assert ghost in sync_mod.RED_STATUSES or sync_mod.PERSONA_NOT_ENROLLED in sync_mod.RED_STATUSES
    assert f"personas/{ghost}" in result.message
    assert "既不在 SOURCE_SNAPSHOT_FILES" not in result.message
    # 回执递的钥匙必须开同一格（只给 --adopt --note 会去重锚主人格的凭证）
    assert f"--adopt --persona {ghost}" in result.message
    with pytest.raises(SystemExit) as exc:
        sync_mod.adopt(copy_path, anchor_path, note="无源也想锚", persona_id=ghost)
    assert ghost in str(exc.value)
    assert not anchor_path.exists(), "缺席格被锚定写了半成品凭证"


def test_third_persona_face_is_green_after_its_own_adopt(
    fake_repo: Path, third_persona: str, third_copy: Path, anchor_path: Path
) -> None:
    """第三人格格走完整生命周期：未锚定红 → 只重录锚 → 绿，凭证钉的是它自己的源。"""
    assert sync_mod.check(third_copy, anchor_path, persona_id=third_persona).status == (
        sync_mod.ANCHOR_MISSING
    )
    shore_snapshot_before = sync_mod.current_source_snapshot()
    anchor_bytes_before = anchor_path.read_bytes() if anchor_path.exists() else None
    sync_mod.adopt(third_copy, anchor_path, note="S5d 离线夹具第三格凭证", persona_id=third_persona)
    result = sync_mod.check(third_copy, anchor_path, persona_id=third_persona)
    assert result.is_red is False and result.status == sync_mod.OK, result.message
    assert anchor_bytes_before is None and anchor_path.exists()
    assert sync_mod.current_source_snapshot() == shore_snapshot_before, (
        "锚第三格时主人格的源快照读数变了＝两格共用了一本账"
    )
    # 覆盖面自锁在别的人格格同样有牙：这一根里冒出没备料的文件要报它自己的名字
    stray = fake_repo / "personas" / third_persona / "随手放的东西.md"
    stray.write_text("x\n", encoding="utf-8")
    covered_red = sync_mod.check(third_copy, anchor_path, persona_id=third_persona)
    assert covered_red.status == sync_mod.SOURCE_UNCOVERED_FILE and covered_red.is_red
    assert f"personas/{third_persona}/随手放的东西.md" in covered_red.message
    assert "personas/shorekeeper" not in covered_red.message


def test_third_persona_source_edit_reds_only_its_own_face(
    fake_repo: Path, third_persona: str, third_copy: Path, anchor_path: Path
) -> None:
    sync_mod.adopt(third_copy, anchor_path, note="第三格凭证", persona_id=third_persona)
    (fake_repo / "personas" / "shorekeeper" / "identity.md").write_text(
        "主人格被人改了\n", encoding="utf-8"
    )
    assert sync_mod.check(third_copy, anchor_path, persona_id=third_persona).status == (
        sync_mod.OK
    ), "主人格演进被算进第三人格的红＝共用了一本账"
    (fake_repo / "personas" / third_persona / "identity.md").write_text(
        _THIRD_SOURCE_TEXT + "这一格自己演进。\n", encoding="utf-8"
    )
    result = sync_mod.check(third_copy, anchor_path, persona_id=third_persona)
    assert result.status == sync_mod.SOURCE_DRIFT and result.is_red
    assert f"personas/{third_persona}/identity.md" in result.message
    assert "personas/shorekeeper" not in result.message


def test_adopt_for_third_persona_still_never_copies(
    fake_repo: Path, third_persona: str, third_copy: Path, anchor_path: Path
) -> None:
    """语义锁在别的人格格同样成立：--adopt 只写锚定，副本与源一个字节都不动。"""
    copy_before = third_copy.read_bytes()
    src = fake_repo / "personas" / third_persona / "identity.md"
    src_before = src.read_bytes()
    shore_before = (fake_repo / "personas" / "shorekeeper" / "identity.md").read_bytes()
    sync_mod.adopt(third_copy, anchor_path, note="只重录凭证", persona_id=third_persona)
    assert third_copy.read_bytes() == copy_before
    assert src.read_bytes() == src_before
    assert (fake_repo / "personas" / "shorekeeper" / "identity.md").read_bytes() == shore_before
    data = _anchor(anchor_path)
    assert data["persona_id"] == third_persona
    assert set(data["source_snapshot"]) == set(sync_mod.source_snapshot_files(third_persona))
    assert f"personas/{third_persona}" in str(data["source_snapshot"])


def test_anchors_are_one_book_per_persona() -> None:
    """一格一本审阅凭证：缺省＝现网那本逐字不变，别的人格不许与主人格共用凭证。"""
    assert sync_mod.default_anchor_path() == sync_mod.ANCHOR_PATH
    assert sync_mod.default_anchor_path(sync_mod.DEFAULT_PERSONA_ID) == sync_mod.ANCHOR_PATH
    other = sync_mod.default_anchor_path(_THIRD)
    assert other != sync_mod.ANCHOR_PATH and other.name == f"persona_sync_anchor_{_THIRD}.json"


def test_cli_persona_flag_differs_from_default_face(
    third_persona: str,
    third_copy: Path,
    anchor_path: Path,
    copy_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """传与不传 --persona 的输出差异：不传＝主人格那把尺原文，传＝指回同一格。"""
    assert (
        sync_mod.main(
            ["--check", "--copy", str(copy_path), "--anchor", str(anchor_path),
             "--adopt", "--note", "cli 缺省格"]
        )
        == 0
    )
    assert sync_mod.main(["--check", "--copy", str(copy_path), "--anchor", str(anchor_path)]) == 0
    printed_default = capsys.readouterr().out
    assert "[绿] 审阅凭证成立" in printed_default
    assert "--persona" not in printed_default  # 缺省态文案＝参数化之前

    assert sync_mod.main(_third_args(third_copy, anchor_path)) == 1  # 未锚定 → ANCHOR_MISSING 红
    printed = capsys.readouterr().out
    assert f"--adopt --persona {third_persona}" in printed, printed
    assert "python scripts/sync_persona_source.py --adopt --note" not in printed

    assert sync_mod.main([*_third_args(third_copy, anchor_path), "--adopt", "--note", "cli"]) == 0
    assert sync_mod.main(_third_args(third_copy, anchor_path)) == 0
    printed_green = capsys.readouterr().out
    assert f"人格={third_persona}" in printed_green


def test_cli_non_default_persona_must_declare_its_own_copy(
    third_persona: str, fake_repo: Path
) -> None:
    """不带 --copy 的 --persona 会被拒：.env 的 BOT_PERSONA_FILES 声明的是**主人格**的正文，
    拿它判另一格＝端别人家的凭证（argparse exit 2，不猜优先级）。"""
    with pytest.raises(SystemExit) as exc:
        sync_mod.main(["--check", "--persona", third_persona])
    assert exc.value.code == 2


def test_cli_rejects_untrusted_persona_id_shape() -> None:
    """档名来自 CLI：形状不可信（穿越/NUL）一律拒，绝不拿 ../.. 当人格根。"""
    for bogus in ("../shorekeeper", "a/b", ".hidden"):
        with pytest.raises(SystemExit) as exc:
            sync_mod.main(["--check", "--persona", bogus, "--copy", "无.md"])
        assert exc.value.code == 2


def test_default_face_is_the_verbatim_pre_parameterization_text(
    fake_repo: Path, copy_path: Path, anchor_path: Path
) -> None:
    """「缺省态＝参数化之前逐字一致」这条真成立（判据形态＝逐条撞红态比对原文，同 1-6 节）。"""
    assert sync_mod.persona_source_root() == sync_mod.PERSONA_SOURCE_ROOT
    assert sync_mod.source_snapshot_files() == sync_mod.SOURCE_SNAPSHOT_FILES
    assert sync_mod.adopt_cmd() == sync_mod.ADOPT_CMD
    head_adopt_cmd = 'python scripts/sync_persona_source.py --adopt --note "…人工审阅说明…"'
    assert sync_mod.ADOPT_CMD == head_adopt_cmd

    sync_mod.adopt(copy_path, anchor_path, note="缺省格")
    assert sync_mod.check(copy_path, anchor_path).message.startswith("[绿] 审阅凭证成立：")

    (fake_repo / "personas" / "shorekeeper" / "identity.md").write_text("改了\n", encoding="utf-8")
    assert "[红] 人格源 personas/shorekeeper 自锚定后已演进，而生产副本未经重新审阅——" in (
        sync_mod.check(copy_path, anchor_path).message
    )
    stray = fake_repo / "personas" / "shorekeeper" / "另起一格.md"
    stray.write_text("x\n", encoding="utf-8")
    coverage_msg = sync_mod.check(copy_path, anchor_path).message
    assert "[红] 人格源覆盖面自锁：以下文件在 personas/shorekeeper/ 里但门看不见它们——" in (
        coverage_msg
    )
    assert "personas/shorekeeper/另起一格.md 既不在 SOURCE_SNAPSHOT_FILES" in coverage_msg
    assert "一次性 --adopt 补锚" in coverage_msg  # 原文口径：这里递的是处置文案，不是整条命令
    stray.unlink()

    (fake_repo / "personas" / "shorekeeper" / "identity.md").write_text(
        _SOURCE_TEXT, encoding="utf-8"
    )
    sync_mod.adopt(copy_path, anchor_path, note="缺省格重锚")
    copy_path.write_text("副本被单方面改了\n", encoding="utf-8")
    drift_msg = sync_mod.check(copy_path, anchor_path).message
    assert "（或对照 personas/shorekeeper/ 源）后运行 " + head_adopt_cmd in drift_msg
    missing_msg = sync_mod.check(
        fake_repo.parent / "无.md", anchor_path, declared_copy=True
    ).message
    assert "人工核对后如需重锚跑 " + head_adopt_cmd in missing_msg
    for text in (coverage_msg, drift_msg, missing_msg):
        assert "--persona" not in text, "缺省态混进了参数化文案"

