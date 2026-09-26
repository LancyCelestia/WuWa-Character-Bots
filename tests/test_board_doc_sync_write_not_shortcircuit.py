"""席 S779 复现门：`scripts/board_doc_sync.py --write` 不得被体检早退吃掉写盘。

背景（S770 只读桩证死的缺陷）：`main()` 里 `if problems: return 1` 排在 `if args.write:`
**之前** ⇒ 只要体检有一条问题（今天是他波两枚未登记项 `RouteKind HOST_STATE`／帮助主题
「宿主机状态」压门），`--write` 与 `--check` 一样在门口就返回、`write_tree` 实到调用 **0** 次，
生成物一个字节都不跟随——把"跑了 --write"当成"已重生成"是典型的假账。

本文件用**受控合成声明源**（monkeypatch 只打在叶子取数口上，`build_tree` 仍是生产真身）在
`tmp_path` 合成根上跑，**绝不对 `docs/boards/**` 真仓生成物写一个字节**。断言两件事：

1. `--write` 在体检非空时仍真写盘（写盘发生）。
2. 写完仍把体检问题如实报出来、退出码仍反映问题（门只准变严，不许为凑绿放宽判据）。

两发注毒（另见 `probes/s779-poison-selfcheck.py`，在 `%TEMP%` 副本上）分别打掉这两条断言，
证明它们各有牙、不是空跑。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import board_doc_sync as bds


# --------------------------------------------------------------------------
# 合成声明源：只喂给叶子取数口，build_tree/write_tree/main 全用生产真身
# --------------------------------------------------------------------------
def _synthetic_board() -> list[dict[str, Any]]:
    """一枚板块、一枚二级功能，认领 CHAT；impl_paths 空，避免引入额外体检项。"""
    return [
        {
            "bid": "B99",
            "slug": "synthetic",
            "label": "合成板块",
            "tagline": "席位自检用",
            "responsibilities": ("只用于验证写盘不被体检吃掉",),
            "features": [
                {
                    "slug": "synthetic-feature",
                    "fid": "B99.synthetic",
                    "label": "合成功能",
                    "summary": "只用于验证",
                    "route_kinds": ("CHAT",),
                    "capability_ids": (),
                    "help_topics": (),
                    "extra_l3": (),
                    "impl_paths": (),
                    "config_prefixes": (),
                }
            ],
        }
    ]


def _synthetic_route_index() -> dict[str, dict[str, object]]:
    return {
        "CHAT": {
            "capability_id": "bot.chat",
            "priority": 1,
            "label": "聊天",
            "value": "chat",
            "command": True,
        }
    }


def _install_synthetic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    make_problems: bool,
) -> Path:
    """把叶子取数口与写盘落点换到 tmp；返回 tmp 下的 boards 落点。

    `make_problems=True` 时额外塞一枚未被认领的 RouteKind（HOST_STATE），让**生产 build_tree**
    自己派出一条体检问题——不是测试自说自话，注毒①（清 problems）才拦得住。
    """
    boards_dir = tmp_path / "boards"
    boards_dir.mkdir(parents=True, exist_ok=True)
    members = ["CHAT", "HOST_STATE"] if make_problems else ["CHAT"]
    monkeypatch.setattr(bds, "BOARDS_DIR", boards_dir)
    monkeypatch.setattr(bds, "load_taxonomy", _synthetic_board)
    monkeypatch.setattr(bds, "load_route_index", _synthetic_route_index)
    monkeypatch.setattr(bds, "load_route_kind_members", lambda: list(members))
    monkeypatch.setattr(bds, "load_help_topics", list)
    monkeypatch.setattr(bds, "load_config_fields", list)
    return boards_dir


# --------------------------------------------------------------------------
# 断言 1：体检非空时 --write 仍真写盘
# --------------------------------------------------------------------------
def test_write_projects_to_disk_even_when_health_check_has_problems(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    boards_dir = _install_synthetic(monkeypatch, tmp_path, make_problems=True)

    # 先证明确实有体检问题（否则这条用例什么都没测——注毒①正是从这里下手）
    _, problems = bds.build_tree()
    assert problems, "合成声明源没派生出体检问题，用例前提失效（应造一枚未认领 RouteKind）"

    bds.main(["--write"])

    # 真写盘的硬证据：三级入口页落到了 tmp，且带 AUTO 标记段（空跑则整个目录仍是空的）
    feature_dir = boards_dir / "B99-synthetic" / "synthetic-feature"
    l3_page = feature_dir / "chat.md"
    assert l3_page.is_file(), (
        "--write 未落任何生成物：体检未过把写盘吃掉了（这正是 S779 要根修的空跑缺陷）"
    )
    text = l3_page.read_text(encoding="utf-8")
    assert bds.AUTO_BEGIN in text and bds.AUTO_END in text, "生成的三级页缺 AUTO 标记段，投影未真正完成"
    assert (boards_dir / "README.md").is_file(), "板块索引页也未生成 ⇒ write_tree 根本没跑"


# --------------------------------------------------------------------------
# 断言 2：写完仍报出体检问题、退出码反映问题（门只准变严）
# --------------------------------------------------------------------------
def test_write_still_reports_problems_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_synthetic(monkeypatch, tmp_path, make_problems=True)

    rc = bds.main(["--write"])

    err = capsys.readouterr().err
    assert rc == 1, f"--write 退出码应反映体检问题（非 0），实得 {rc}（放宽判据＝门变松，禁止）"
    assert "PROBLEM" in err and "HOST_STATE" in err, (
        f"写完没把体检问题报出来（问题被吞＝假绿），stderr 摘录：{err[-400:]}"
    )
    assert "板块树体检未过" in err, "缺少体检未过的汇总行"
