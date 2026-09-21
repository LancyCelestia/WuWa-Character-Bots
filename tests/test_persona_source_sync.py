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
    src.write_bytes(before + "\n# 源与副本内容不同\n".encode("utf-8"))
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
