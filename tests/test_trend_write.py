"""时梗层写入接口回归（审查 O-05：默认关 + 无写入路径 → 补显式写入 API）。

覆盖：keep-newest 覆盖、上限 FIFO 淘汰、原子写（无 .tmp 残留）、
默认关语义不变（build_trend_provider 行为零变化）、既有内容保全。
注入面（load/FileTrendProvider/build_trend_provider）不允许有任何行为变化。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import trend as trend_mod
from plugins.bot_unified_runtime.domains.chat_reply.character.trend import (
    MAX_TREND_ENTRIES,
    FileTrendProvider,
    NullTrendProvider,
    add_trend_entry,
    build_trend_provider,
)


class _TrendCfg:
    """最小配置桩：只暴露 build_trend_provider 读取的键。"""

    def __init__(self, enabled: bool, files: list[str]) -> None:
        self.bot_trend_enabled = enabled
        self.bot_trend_files = files


def test_add_creates_file_and_roundtrips_through_load(tmp_path: Path) -> None:
    """写入形态必须能被既有 load 原样解析：topic=term、note=解释、带日期。"""
    notes = tmp_path / "trend.md"
    assert (
        add_trend_entry(notes, "考公搭子", "指一起备考公务员的互相监督的伙伴") is False
    )
    ctx = FileTrendProvider([notes], max_notes=10).load("req-1")
    assert len(ctx.notes) == 1
    note = ctx.notes[0]
    assert note.topic == "考公搭子"
    assert note.note == "指一起备考公务员的互相监督的伙伴"
    # 写入默认补当天 UTC 日期（YYYY-MM-DD），让 max_age_days 过滤链路可用。
    assert len(note.observed_on) == 10 and note.observed_on[4] == "-"


def test_add_explicit_date_passthrough(tmp_path: Path) -> None:
    notes = tmp_path / "trend.md"
    add_trend_entry(notes, "old梗", "旧事", observed_on="2026-01-02")
    # 日期久远会被 max_age_days 新鲜度门滤掉（既有语义），此处关掉只验透传。
    ctx = FileTrendProvider([notes], max_age_days=0).load("r")
    assert ctx.notes[0].observed_on == "2026-01-02"


def test_add_same_term_overwrites_keep_newest(tmp_path: Path) -> None:
    """同名词条覆盖解释（含 strip+casefold 归一），旧解释不残留。"""
    notes = tmp_path / "trend.md"
    add_trend_entry(notes, "绝绝子", "旧解释")
    assert add_trend_entry(notes, "绝绝子", "新解释") is True
    # 大小写/首尾空白差异视作同名。
    add_trend_entry(notes, "  MEME  ", "英文梗旧解")
    add_trend_entry(notes, "meme", "英文梗新解")
    text = notes.read_text(encoding="utf-8")
    assert text.count("## 绝绝子") == 1
    assert "新解释" in text and "旧解释" not in text
    assert "## MEME" not in text  # 被后续小写同名条目覆盖
    ctx = FileTrendProvider([notes], max_notes=10).load("r")
    by_topic = {n.topic.casefold(): n.note for n in ctx.notes}
    assert by_topic["绝绝子"] == "新解释"
    assert by_topic["meme"] == "英文梗新解"


def test_add_evicts_oldest_beyond_cap(tmp_path: Path) -> None:
    """新词条使条目数超过上限时，按文件顺序淘汰最旧（最前）小节。"""
    notes = tmp_path / "trend.md"
    for i in range(4):
        add_trend_entry(notes, f"词条{i}", f"解释{i}", max_entries=3)
    ctx = FileTrendProvider([notes], max_notes=10).load("r")
    assert [n.topic for n in ctx.notes] == ["词条1", "词条2", "词条3"]
    # 覆盖已有词条不受上限影响（不增条目）。
    add_trend_entry(notes, "词条3", "词条3更新", max_entries=3)
    ctx2 = FileTrendProvider([notes], max_notes=10).load("r")
    assert len(ctx2.notes) == 3
    assert ctx2.notes[-1].note == "词条3更新"


def test_max_trend_entries_constant_is_bounded() -> None:
    """上限常量锁定：防后续有人改成无界。"""
    assert MAX_TREND_ENTRIES == 200


def test_atomic_write_leaves_no_tmp_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功与失败路径都不留 .tmp；失败时原文件内容不受影响。"""
    notes = tmp_path / "trend.md"
    add_trend_entry(notes, "首条", "首条解释")
    assert list(tmp_path.glob("*.tmp")) == []

    # 非法日期在落盘前即抛错。
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        add_trend_entry(notes, "坏日期", "不该落盘", observed_on="2026/09/14")
    # 空/纯空白词条同样前置拒绝。
    with pytest.raises(ValueError, match="不能为空"):
        add_trend_entry(notes, "   ", "空白词条")
    assert list(tmp_path.glob("*.tmp")) == []
    text = notes.read_text(encoding="utf-8")
    assert "不该落盘" not in text and "空白词条" not in text
    assert "首条解释" in text

    # 模拟 os.replace 阶段失败：tmp 已写出，必须被清理、原文件不动。
    def _boom(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(trend_mod.os, "replace", _boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        add_trend_entry(notes, "第二条", "第二条解释")
    monkeypatch.undo()
    assert list(tmp_path.glob("*.tmp")) == []
    assert "第二条" not in notes.read_text(encoding="utf-8")
    assert "首条解释" in notes.read_text(encoding="utf-8")


def test_add_preserves_existing_manual_content(tmp_path: Path) -> None:
    """写入不破坏既有手写小节与前导内容（手写文件与积累词条共存）。"""
    notes = tmp_path / "trend.md"
    notes.write_text(
        "内部备注，手写维护。\n\n"
        "# 手写小节 (2020-01-01)\n- 陈年旧梗\n\n"
        "## 老梗 (2020-06-01)\n- 旧内容\n",
        encoding="utf-8",
    )
    add_trend_entry(notes, "新梗", "新内容")
    # 手写小节日期久远，会被 max_age_days 新鲜度门滤掉（既有语义），此处关闭。
    ctx = FileTrendProvider([notes], max_notes=10, max_age_days=0).load("r")
    topics = {n.topic: n.note for n in ctx.notes}
    assert topics["手写小节"] == "陈年旧梗"
    assert topics["老梗"] == "旧内容"
    assert topics["新梗"] == "新内容"
    # 前导内容（首个标题之前的行）原样保留在文件头。
    assert notes.read_text(encoding="utf-8").startswith("内部备注，手写维护。")


def test_build_trend_provider_default_off_semantics_unchanged() -> None:
    """默认关语义零变化：未启用→Null；启用但无文件→Null；启用且有文件→File。"""
    assert isinstance(
        build_trend_provider(_TrendCfg(False, ["x.md"])), NullTrendProvider
    )
    assert isinstance(build_trend_provider(_TrendCfg(True, [])), NullTrendProvider)
    assert isinstance(
        build_trend_provider(_TrendCfg(True, ["x.md"])), FileTrendProvider
    )


def test_source_line_never_enters_injection_surface(tmp_path: Path) -> None:
    """非 manual 的 source 留痕行（#### 开头）不得出现在注入面。"""
    notes = tmp_path / "trend.md"
    add_trend_entry(notes, "梗A", "解释A", source="reflection-draft")
    ctx = FileTrendProvider([notes], max_notes=10).load("r")
    assert len(ctx.notes) == 1
    assert ctx.notes[0].note == "解释A"
    assert "reflection-draft" not in ctx.notes[0].note
