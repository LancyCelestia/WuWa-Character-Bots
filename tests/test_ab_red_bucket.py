"""A/B 红集分桶器自证锁（修复波 2026-10-02，席 BKT）。

四发必锁：①三桶正常划分 ②折行 node ID 归并 ③NEW_ONLY 非空 ⇒ rc 1
④参数化尾巴两档归一；另附 --json 出口、裸计数行、CRLF/重复、函数级归一
与含空格参数尾巴（SPC 回归）各发。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 中置 import 有意：被测件在 scripts/ 包内，先把仓库根插进 sys.path 再导入。
from scripts import ab_red_bucket as arb


def _summary(*failed_lines: str, count: str = "1 failed, 9 passed in 0.01s") -> str:
    """合成一段最小 pytest ``-q --tb=no -rf`` 输出（含分节横幅与裸计数行）。"""
    banner = "=" * 27 + " short test summary info " + "=" * 27
    body = "".join(line + "\n" for line in failed_lines)
    return f"{banner}\n{body}{count}\n"


def test_three_bucket_partition():
    """① 三桶正常划分：新增红逐枚点名、转绿、既存红各归其位。"""
    a_text = _summary(
        "FAILED tests/test_a.py::test_common - assert 1 == 2",
        "FAILED tests/test_a.py::test_gone - boom",
        "FAILED tests/test_b.py::test_other - boom",
        count="3 failed, 40 passed in 1.02s",
    )
    b_text = _summary(
        "FAILED tests/test_a.py::test_common - assert 1 == 2",
        "FAILED tests/test_a.py::test_fresh[case1] - boom",
        "FAILED tests/test_b.py::test_other - boom",
        "FAILED tests/test_b.py::test_other2 - boom",
        count="4 failed, 39 passed in 1.02s",
    )
    res = arb.bucket(a_text, b_text)
    assert [e.function for e in res.new_only] == [
        "tests/test_a.py::test_fresh",
        "tests/test_b.py::test_other2",
    ]
    assert res.new_only[0].params == ("tests/test_a.py::test_fresh[case1]",)
    assert [e.function for e in res.gone_only] == ["tests/test_a.py::test_gone"]
    assert {e.function for e in res.common} == {
        "tests/test_a.py::test_common",
        "tests/test_b.py::test_other",
    }


def test_wrapped_nodeid_continuation_merged():
    """② 折行归并：长 node ID 折到下一行的连续段要拼回原 token。"""
    full = (
        "tests/test_media_archive.py::test_vlm_gate"
        "[media_archive.vlm_param_value_that_is_deliberately_long]"
    )
    wrapped = (
        "FAILED tests/test_media_archive.py::test_vlm_gate"
        "[media_archive.vlm_param_value_that_is_deliberat\n"
        "ely_long] - AssertionError: assert not admitted"
    )
    assert arb.extract_failed_nodeids(wrapped) == [full]
    # 变体 A：折点恰在 FAILED 关键字之后
    split_after_keyword = "FAILED\ntests/test_wrap2.py::test_split - boom"
    assert arb.extract_failed_nodeids(split_after_keyword) == [
        "tests/test_wrap2.py::test_split"
    ]
    # 变体 B：折点在 " - " 分隔符之前，续行以 "- " 开头
    dash_wrapped = "FAILED tests/test_wrap3.py::test_dash\n- assert False"
    assert arb.extract_failed_nodeids(dash_wrapped) == [
        "tests/test_wrap3.py::test_dash"
    ]
    # 桶级：B 折行形态与 A 全量形态必须认成同一条既存红
    res = arb.bucket(_summary("FAILED " + full + " - boom"), _summary(wrapped))
    assert res.new_only == () and res.gone_only == ()
    assert res.common[0].params == (full,)


def test_new_only_nonempty_exit_code_1(tmp_path, capsys):
    """③ 终门机读口：NEW_ONLY 非空 ⇒ rc 1；空 ⇒ rc 0。"""
    a = tmp_path / "a_head.txt"
    b = tmp_path / "b_worktree.txt"
    a.write_text(
        _summary("FAILED tests/test_a.py::test_old - boom"), encoding="utf-8"
    )
    b.write_text(
        _summary(
            "FAILED tests/test_a.py::test_old - boom",
            "FAILED tests/test_new.py::test_net_new - boom",
        ),
        encoding="utf-8",
    )
    assert arb.main([str(a), str(b)]) == 1
    assert "NEW_ONLY" in capsys.readouterr().out
    assert arb.main([str(b), str(b)]) == 0


def test_param_tail_two_tier_unification():
    """④ 两档归一：``test_x[media_archive.vlm]`` 与 ``test_x`` 认同一条红。"""
    a_text = _summary("FAILED tests/test_x.py::test_x - boom")
    b_text = _summary("FAILED tests/test_x.py::test_x[media_archive.vlm] - boom")
    res = arb.bucket(a_text, b_text)
    assert res.new_only == () and res.gone_only == ()
    assert [e.function for e in res.common] == ["tests/test_x.py::test_x"]
    # params＝两侧参数级原貌并集（B 参数形态在前，A 函数形态补后）
    assert res.common[0].params == (
        "tests/test_x.py::test_x[media_archive.vlm]",
        "tests/test_x.py::test_x",
    )
    res_rev = arb.bucket(b_text, a_text)
    assert res_rev.new_only == () and res_rev.gone_only == ()
    assert [e.function for e in res_rev.common] == ["tests/test_x.py::test_x"]


def test_json_output_and_bare_count_line(tmp_path, capsys):
    """--json 出口可解析且与 rc 自洽；裸计数行（-q 无横幅包边）不是条目。"""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    out = tmp_path / "ab.json"
    a.write_text(_summary("FAILED tests/test_a.py::test_old - boom"), encoding="utf-8")
    b.write_text(
        _summary(
            "FAILED tests/test_a.py::test_old - boom",
            "FAILED tests/test_a.py::test_fresh - boom",
        ),
        encoding="utf-8",
    )
    rc = arb.main([str(a), str(b), "--json", str(out)])
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert rc == (1 if payload["new_only"] else 0)
    assert set(payload["counts"]) == {"new_only", "gone_only", "common"}
    assert payload["counts"]["new_only"] == len(payload["new_only"]) == 1
    assert payload["new_only"][0]["function"] == "tests/test_a.py::test_fresh"
    # 无分节横幅的裸输出（直接 grep 存下来的行）也要能吃
    bare = "FAILED tests/test_bare.py::test_bare - boom\n2 failed in 0.01s\n"
    assert arb.extract_failed_nodeids(bare) == ["tests/test_bare.py::test_bare"]


def test_crlf_and_dupe_tolerant():
    """Windows 重定向的 CRLF 行尾与重复 FAILED 行都不扰分桶。"""
    text = (
        "======= short test summary info =======\r\n"
        "FAILED tests/test_crlf.py::test_dup - boom\r\n"
        "FAILED tests/test_crlf.py::test_dup - boom\r\n"
        "2 failed in 0.01s\r\n"
    )
    assert arb.extract_failed_nodeids(text) == ["tests/test_crlf.py::test_dup"]
    assert arb.function_level("tests/t.py::test_x[a][b]") == "tests/t.py::test_x"


@pytest.mark.parametrize(
    ("nodeid", "want"),
    [
        ("tests/test_x.py::test_x", "tests/test_x.py::test_x"),
        ("tests/test_x.py::test_x[media_archive.vlm]", "tests/test_x.py::test_x"),
        ("tests/test_x.py::Class::test_y[p1]", "tests/test_x.py::Class::test_y"),
    ],
)
def test_function_level_normalization(nodeid, want):
    """两档归一的纯函数面：剥尾规则逐形态锁定。"""
    assert arb.function_level(nodeid) == want


def test_space_inside_param_tail_is_not_truncated():
    """SPC 回归：参数化尾巴含空格的 node ID 不许在首个空格处腰斩。

    HEAD 红集实测形态（BASE-2 第 129 行）＝
    ``FAILED …::test_poison_breaks_the_lock_and_the_real_body_passes[J9 gallery_empty 乱贴] - …``。
    旧实现取第 2 个空白 token ⇒ ID 断成 ``…[J9``（桶位碰巧不坏、原貌破，
    且同前缀异参数塌假 COMMON 吞真红——SPC 三失效形态实跑证实）。
    """
    spid = (
        "tests/test_ledger.py::test_poison_breaks_the_lock_and_the_real_body_passes"
        "[J9 gallery_empty 乱贴]"
    )
    # 带消息形态：ID＝FAILED 与首个 " - " 之间整段
    assert arb.extract_failed_nodeids(
        f"FAILED {spid} - AssertionError: DID NOT RAISE"
    ) == [spid]
    # 裸形态（消息缺席）：整段即 ID
    assert arb.extract_failed_nodeids(f"FAILED {spid}") == [spid]
    # 折行 + 含空格复合：折点在 " - " 分隔符前
    wrapped = f"FAILED {spid}\n- AssertionError: DID NOT RAISE"
    assert arb.extract_failed_nodeids(wrapped) == [spid]
    # 桶级：异函数同形各归各桶，点名用全 ID；同函数异参数塌 COMMON 是
    # 函数级归一的既有语义（params 并集保两枚原貌，不吞）。
    twin = (
        "tests/test_ledger.py::test_poison_breaks_the_lock_and_the_real_body_passes"
        "[J9 other_case]"
    )
    res = arb.bucket(_summary(f"FAILED {spid} - boom"), _summary(f"FAILED {twin} - boom"))
    assert res.new_only == () and res.gone_only == ()
    assert res.common[0].function == (
        "tests/test_ledger.py::test_poison_breaks_the_lock_and_the_real_body_passes"
    )
    assert res.common[0].params == (twin, spid)
    fresh = "tests/test_fresh.py::test_space_case[J9 gallery_empty 乱贴]"
    res2 = arb.bucket(_summary(f"FAILED {spid} - boom"), _summary(f"FAILED {fresh} - boom"))
    assert [e.function for e in res2.new_only] == [
        "tests/test_fresh.py::test_space_case"
    ]
    assert res2.new_only[0].params == (fresh,)
