"""S-T-ACGFUSE：二游事实问句的「实体 → 竖源条目 → 融合 → 进提示词」全链核对。

只测一件事：**有没有把 A 的说法安到 B 头上**。这类融合最常见的错不是检索不到，
而是两条各自正确的条目在拼装时串了味——标题是甲的、正文是乙的、日期是丙的，
或者同名异条目（一部作品的漫画版与动画版）被折叠成一条。

做法：每道题给每个来源写一条**自带唯一指纹**的合成条目（正文只放属于它自己的话），
跑完整链（含 `chat._web_search_lines` 的实际渲染形态），再逐行核对
「这一行的标题 ↔ 这一行的正文/日期/条目号是不是同一族的」。全程 `tmp_path`
与 monkeypatch 夹具，零真实网络。
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.core.contracts.character import WebSearchHit
from plugins.bot_unified_runtime.domains.core.search import acg_search
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_acg_intent,
)

TODAY = date(2026, 9, 25)


def _patch_verticals(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bangumi: list[acg_search.AcgResult] | None = None,
    moegirl: list[acg_search.AcgResult] | None = None,
    bilibili: list[acg_search.AcgResult] | None = None,
) -> None:
    """把三枚取数口换成合成夹具（与 `tests/test_v21r2_acg_search.py` 同一手法）。"""
    monkeypatch.setattr(
        acg_search, "bangumi_search", lambda q, **k: list(bangumi or [])
    )
    monkeypatch.setattr(
        acg_search, "moegirl_lookup", lambda q, **k: list(moegirl or [])
    )
    monkeypatch.setattr(
        acg_search, "bilibili_search", lambda q, **k: list(bilibili or [])
    )


def _prompt_lines(question: str, monkeypatch: pytest.MonkeyPatch, **fixtures: object) -> list[str]:
    """全链跑一次，返回**实际进提示词**的那些行（含区块头，便于人工核对）。"""
    _patch_verticals(monkeypatch, **fixtures)  # type: ignore[arg-type]
    intent = detect_acg_intent(question)
    assert intent.is_acg, f"该问句今天进不了 ACG 分支：{question}"
    results, _errors = acg_search.search_acg_verticals(question, intent)
    fused = acg_search.fuse_into_web_hits(intent, [], results, today=TODAY)
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    context = SimpleNamespace(
        web_search_context=SimpleNamespace(hits=fused)
    )
    rendered = chat._web_search_lines(context)  # type: ignore[arg-type]
    return [line for line in rendered.splitlines() if line.startswith("- [")]


# ---------------------------------------------------------------------------
# ①《葬送的芙莉莲》：三源各说一件事，谁的话留在谁的行上
# ---------------------------------------------------------------------------


def test_frieren_three_sources_keep_their_own_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = _prompt_lines(
        "葬送的芙莉莲动画第三季出了吗",
        monkeypatch,
        bangumi=[
            acg_search.AcgResult(
                source="bangumi",
                title="葬送的芙莉莲",
                snippet="电视动画·制作号 BG-430415",
                url="https://bgm.tv/subject/430415",
                date="2026-07-05",
                item_id="430415",
            )
        ],
        moegirl=[
            acg_search.AcgResult(
                source="moegirl",
                title="葬送的芙莉莲",
                snippet="萌百释义号 MG-505050",
                url="https://zh.moegirl.org.cn/葬送的芙莉莲",
                item_id="505050",
            )
        ],
        bilibili=[
            acg_search.AcgResult(
                source="bilibili",
                title="芙莉莲 第三季 PV",
                snippet="视频简介号 BL-BV1",
                url="https://www.bilibili.com/video/BV1xx",
                date="2026-09-12",
                item_id="BV1xx",
            )
        ],
    )
    assert len(lines) == 3
    for line in lines:
        tokens = [t for t in ("BG-430415", "MG-505050", "BL-BV1") if t in line]
        assert len(tokens) == 1, f"一行里出现了两个来源的正文：{line}"
    assert any("BG-430415" in line and "2026-07-05" in line for line in lines)
    assert any("BL-BV1" in line and "2026-09-12" in line for line in lines)
    # 萌百这条没有日期字段：最新档要如实标「日期未知」，不能被别的源的日期冒充。
    assert any("MG-505050" in line and "日期未知" in line for line in lines)


# ---------------------------------------------------------------------------
# ②同名异条目（漫画版 / 动画版）：不许折叠成一条，也不许共用日期
# ---------------------------------------------------------------------------


def test_same_title_different_subjects_are_not_collapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lines = _prompt_lines(
        "咒术回战漫画连载到哪了",
        monkeypatch,
        bangumi=[
            acg_search.AcgResult(
                source="bangumi",
                title="咒术回战",
                snippet="漫画条目 MG-BOOK-111",
                url="https://bgm.tv/subject/111",
                date="2012-03-05",
                item_id="111",
            ),
            acg_search.AcgResult(
                source="bangumi",
                title="咒术回战",
                snippet="动画条目 AN-TV-222",
                url="https://bgm.tv/subject/222",
                date="2020-10-03",
                item_id="222",
            ),
        ],
        moegirl=[
            acg_search.AcgResult(
                source="moegirl",
                title="咒术回战",
                snippet="萌百同名条目 MG-333",
                url="https://zh.moegirl.org.cn/咒术回战",
                item_id="333",
            )
        ],
    )
    assert len(lines) == 3, "同名不同 id 的条目被折叠了：漫画版与动画版是两条事实"
    assert any("MG-BOOK-111" in line and "2012-03-05" in line for line in lines)
    assert any("AN-TV-222" in line and "2020-10-03" in line for line in lines)
    for line in lines:
        own = [t for t in ("MG-BOOK-111", "AN-TV-222", "MG-333") if t in line]
        assert len(own) == 1, f"两条同名条目的正文串行成一条：{line}"


# ---------------------------------------------------------------------------
# ③相邻同类实体（初音未来 / 巡音流歌）：串味最典型的一格
# ---------------------------------------------------------------------------


def test_adjacent_similar_entities_do_not_swap_descriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 问句里带「虚拟偶像」不是随手写的：`detect_acg_intent` 今天**认不出**光说
    # 「初音未来的代表作品有哪些」——词表里没有这枚条目名（现算见
    # `tests/test_search_intent_acg.py` 的探针与挂账用例）。这里要测的是融合层
    # 不串味，所以用一条今天真能进分支的问法，把门禁那一层的洞单独记账。
    lines = _prompt_lines(
        "虚拟偶像初音未来和巡音流歌分别是谁",
        monkeypatch,
        moegirl=[
            acg_search.AcgResult(
                source="moegirl",
                title="初音未来",
                snippet="只有初音才有的那句话 MIKU-ONLY",
                url="https://zh.moegirl.org.cn/初音未来",
                item_id="1001",
            ),
            acg_search.AcgResult(
                source="moegirl",
                title="巡音流歌",
                snippet="只有巡音才有的那句话 LUKA-ONLY",
                url="https://zh.moegirl.org.cn/巡音流歌",
                item_id="1002",
            ),
        ],
    )
    miku = next(line for line in lines if "初音未来" in line)
    luka = next(line for line in lines if "巡音流歌" in line)
    assert "MIKU-ONLY" in miku and "LUKA-ONLY" not in miku
    assert "LUKA-ONLY" in luka and "MIKU-ONLY" not in luka
    assert "id=1001" in miku and "id=1002" not in miku, "条目号串行＝把甲的身份安到乙头上"


# ---------------------------------------------------------------------------
# ④同一视频的多个转载 / 同一条目两现：不许被读成"两源互证"
# ---------------------------------------------------------------------------


def test_duplicate_item_never_becomes_second_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dup = acg_search.AcgResult(
        source="bilibili",
        title="硬控 名场面",
        snippet="BV777 的第一次出现",
        url="https://www.bilibili.com/video/BV777",
        date="2026-09-20",
        item_id="BV777",
    )
    lines = _prompt_lines(
        "硬控是什么梗",
        monkeypatch,
        bilibili=[
            dup,
            acg_search.AcgResult(
                source="bilibili",
                title="硬控 名场面（同一支视频的另一个入口）",
                snippet="BV777 的第二次出现",
                url="https://www.bilibili.com/video/BV777",
                date="2026-09-20",
                item_id="BV777",
            ),
        ],
        moegirl=[
            acg_search.AcgResult(
                source="moegirl",
                title="硬控",
                snippet="萌百释义 MG-77",
                url="https://zh.moegirl.org.cn/硬控",
                item_id="77",
            )
        ],
    )
    joined = "\n".join(lines)
    assert "BV777 的第一次出现" in joined
    assert "第二次出现" not in joined, "同一条目重复出现＝凭空多出一条独立佐证"
    assert sum("BV777" in line for line in lines) == 1


# ---------------------------------------------------------------------------
# ⑤越站链接：说 B站 却指向别处的条目不许顶在前面
# ---------------------------------------------------------------------------


def test_offsite_item_crowds_out_nothing_and_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        acg_search.AcgResult(
            source="bilibili",
            title="农场转载条",
            snippet="脏链接 BL-BAD",
            url="https://seo-farm.example/video/BV999",
            date="2026-09-24",
            item_id="BV999",
        ),
        acg_search.AcgResult(
            source="bilibili",
            title="站内真条目",
            snippet="干净链接 BL-GOOD",
            url="https://www.bilibili.com/video/BV888",
            date="2026-09-20",
            item_id="BV888",
        ),
    ]
    _patch_verticals(monkeypatch, bilibili=items)
    intent = detect_acg_intent("硬控是什么梗")
    results, errors = acg_search.search_acg_verticals("硬控", intent)
    assert [item.item_id for item in results] == ["BV888"]
    assert any("link_offsite" in kind for kind in errors), "筛掉了却没人知道＝静默丢内容"
    assert "BL-BAD" not in "\n".join(_prompt_lines("硬控是什么梗", monkeypatch, bilibili=items))


# ---------------------------------------------------------------------------
# 区块头那句「时效诚实声明」必须和实际渲染对得上
# ---------------------------------------------------------------------------


def test_honesty_line_matches_what_is_actually_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧口径写「以下条目自带来源与日期」——可通用网页那几行根本没有日期字段
    （`WebSearchHit` 只有四个字段），这句话对它们是假话，而模型会把提示词里的
    假话当事实写进回答。现在两半各自说清。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    intent = detect_acg_intent("原神卡池复刻")
    fused = acg_search.fuse_into_web_hits(
        intent,
        [WebSearchHit(title="通用网页条", snippet="s", url="https://example.com/x", source_domain="example.com")],
        [
            acg_search.AcgResult(
                source="bilibili",
                title="有日期的竖源条",
                snippet="x",
                url="https://www.bilibili.com/video/BV1",
                date="2026-09-24",
                item_id="BV1",
            )
        ],
        today=TODAY,
    )
    rendered = chat._web_search_lines(  # type: ignore[arg-type]
        SimpleNamespace(web_search_context=SimpleNamespace(hits=fused))
    )
    web_line = next(line for line in rendered.splitlines() if "通用网页条" in line)
    vertical_line = next(line for line in rendered.splitlines() if "有日期的竖源条" in line)
    assert "自带来源与日期" not in acg_search.TIMELINESS_HONESTY_LINE
    assert "新鲜度未知" in acg_search.TIMELINESS_HONESTY_LINE
    # 声明与实际互证：竖源行确实带日期，通用行确实不带——反过来才叫说谎。
    assert "2026-09-24" in vertical_line
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", web_line), "通用网页行凭空有了日期＝声明又变假话"
