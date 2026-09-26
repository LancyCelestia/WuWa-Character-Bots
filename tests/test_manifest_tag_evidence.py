"""S68 门：能力侧「原生标签→实测票根」从真空接成真（配扫描面地板 + kind 覆盖两把牙）。

被治的病：`test_capability_manifest_gate.py::test_leg6_native_tags_require_evidence`
今天真空——它只扫 `native-*` 声明，而 `FACETS` 一枚原生声明都没有、`EVIDENCE` 唯一一条
还是非原生（TTS），清空票根册它也不红（SEAT-S68 §0/§1 实跑）。本门把票根数据面独立到
`capability_tag_evidence.py`，并用**扫描面地板**（清空票根册 ⇒ 跌破地板 ⇒ 红）+
**渠道 kind 覆盖**（声明了某原生 kind 的渠道，消费能力必须有对应票根）两把真牙接成实。

判据唯一真身＝本文件 + `capability_tag_evidence.py`；只读 `capability_manifest` /
`channel_capability_tags`，**不写盘、不改判据、不碰他席文件**。

复跑（本门单件）：
    cd ChatBot/ChatBot && PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 \\
      PYTHONIOENCODING=utf-8 PYTHONPYCACHEPREFIX=$TEMP/s68-pyc \\
      ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \\
      tests/test_manifest_tag_evidence.py -p no:cacheprovider \\
      --basetemp=$TEMP/s68-t1 -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import MappingProxyType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins.bot_unified_runtime.domains.core import (
    capability_manifest as cm,
)
from plugins.bot_unified_runtime.domains.core import (
    capability_tag_evidence as cte,
)
from plugins.bot_unified_runtime.domains.core import (
    channel_capability_tags as cct,
)


def _facets_tag_values() -> dict[str, tuple[str, ...]]:
    return {cid: tuple(t.value for t in row.tags) for cid, row in cm.FACETS.items()}


def _undeclared_tickets(
    facets_tags: dict[str, tuple[str, ...]],
    tickets,
) -> list[str]:
    """纯谓词（反方向，供注毒打靶）：票根册里每枚 `(cid, native_tag)` 未在册侧申报的清单。

    与 `declared_native_without_ticket`（声明→票根）反向对称，合起来＝"两侧对齐才算唯一答案"。
    """
    return sorted(
        f"{cid}:{tag}" for (cid, tag) in tickets if tag not in facets_tags.get(cid, ())
    )


def _cm_native_values() -> set[str]:
    return {t.value for t in cm.CapabilityTag if t.value.startswith("native-")}


def _channel_declared_native_kinds() -> set[str]:
    kinds: set[str] = set()
    for entry_kinds in cct.CHANNEL_CAPABILITY_KINDS.values():
        kinds.update(str(k).strip().lower() for k in entry_kinds)
    return kinds


# ----------------------------------------------------------- 真数据腿（现状须全绿）
def test_real_declarations_all_have_tickets() -> None:
    """声明→票根：真 `FACETS` 里若有任何原生声明，逐枚必须在票根册有对应记录。"""
    missing = cte.declared_native_without_ticket(
        MappingProxyType(_facets_tag_values()), cte.TICKETS
    )
    assert missing == [], f"原生声明缺票根：{missing}"


def test_every_ticket_has_reviewable_fields() -> None:
    """票根必带可复核字段：任一必填字段留空即红（不是只写 PASS 那种薄票根）。"""
    thin: list[str] = []
    for (cid, tag), ticket in cte.TICKETS.items():
        empties = cte.missing_reviewable_fields(ticket)
        if empties:
            thin.append(f"{cid}/{tag} 缺字段 {empties}")
        if cte.is_thin_response_evidence(ticket.response_evidence):
            thin.append(f"{cid}/{tag} 响应证据过薄/为代理式达标值")
    assert not thin, "存在薄票根：" + "；".join(thin)


def test_ticket_capability_is_declared_in_manifest() -> None:
    """票根的能力必须是本册已申报的 id（禁止给不存在的能力开空头票根＝第二真身）。"""
    declared = cm.declared_ids()
    ghosts = sorted(cid for (cid, _tag) in cte.TICKETS if cid not in declared)
    assert not ghosts, f"票根指向未申报的能力（在册即骗册）：{ghosts}"


def test_tickets_are_declared_in_manifest() -> None:
    """票根→申报（S178 反方向腿）：票根册里每枚 (cid, native_tag) 必须在 `FACETS[cid].tags` 申报。

    `test_real_declarations_all_have_tickets` 判"声明→票根"（不得无票根乱声明）；本腿判"票根→申报"
    （有票根却不申报＝册少报，正是 S178 点名的另一向失真）。两腿合起来才谈得上"两侧对齐＝唯一答案"。
    真数据下 `bot.chat` 三枚票根（audio/video/animation）都已在册侧申报 ⇒ 本腿为空。
    """
    undeclared = _undeclared_tickets(_facets_tag_values(), cte.TICKETS)
    assert undeclared == [], f"有实测票根却未在册侧申报（册少报＝另一向失真）：{undeclared}"


def test_poison_ticket_not_declared_in_manifest_is_red() -> None:
    """注毒（反方向腿有牙）：把某枚真票根对应的 native 声明从册侧抹掉 ⇒ 必被 `票根→申报` 抓到。

    与正向腿互不遮蔽：正向（声明→票根）此时仍绿（声明变少了，没多声明），只有反向腿会红——
    证明"有票根不申报"这一向确实是靠这条新腿才有人管，不是被正向腿顺带盖住。
    """
    real = _facets_tag_values()
    assert _undeclared_tickets(real, cte.TICKETS) == [], "真数据反向腿已红，注毒失去前提"
    # 抹掉 bot.chat 的一枚真票根声明（保留其余），模拟"票根在、册少报"
    (cid, tag), _ticket = min(cte.TICKETS.items())
    stripped = dict(real)
    stripped[cid] = tuple(t for t in real[cid] if t != tag)
    caught = _undeclared_tickets(stripped, cte.TICKETS)
    assert caught == [f"{cid}:{tag}"], f"抹掉一枚真票根的申报未被抓到＝反向腿无牙：{caught}"
    # 正向腿此时应仍绿（少声明不会被"声明→票根"判红）——证明两腿各管各向、不互相遮蔽
    forward = cte.declared_native_without_ticket(MappingProxyType(stripped), cte.TICKETS)
    assert forward == [], f"正向腿不该被少声明触发（两向须分账）：{forward}"


def test_ticket_tag_values_match_manifest_native_enum() -> None:
    """票根的标签值必须落在已知原生标签集合内（防与 `CapabilityTag` 枚举漂移）。"""
    cm_native = _cm_native_values()
    assert cm_native, "原生枚举取空＝尺瞎了，本用例失去意义"
    bad = sorted(
        tag for (_cid, tag) in cte.TICKETS
        if tag not in cte.KNOWN_NATIVE_TAG_VALUES or tag not in cm_native
    )
    assert not bad, f"票根标签不在原生枚举内（抄出第二张表）：{bad}"


def test_channel_declared_native_kinds_are_ticketed() -> None:
    """kind 覆盖：任一渠道在册声明的原生 kind，消费能力必须有票根。

    渠道侧 tag 是"能不能原生送达"的因、能力侧票根是"确实被读懂"的果；两边不
    对齐就是"渠道能吃、能力没验过"，正是裁定要拦的形态。
    """
    kinds = _channel_declared_native_kinds()
    assert kinds, "渠道原生 kind 取空＝尺瞎了（channel_capability_tags 被清空？）"
    have = cte.native_kinds_with_tickets(cte.NATIVE_CONSUMER_CAPABILITY)
    uncovered = sorted(kinds - have)
    assert not uncovered, (
        f"渠道声明了原生 kind 却无消费能力票根（少果验因）：{uncovered}")


def test_ticket_scan_surface_floor_never_shrinks() -> None:
    """扫描面地板（真空杀手）：票根枚数 ≥ 手写字面量地板，清空票根册当场红。

    用 `raise AssertionError` 而非裸 `assert`：`python -O` 会剥 assert，那会让
    这把"清空即红"的牙在 -O 下自动失效，与教义正相反（先例=门件 `_ratchet_check`）。
    """
    measured = cte.ticket_count()
    if measured < cte.TICKETS_FLOOR:
        raise AssertionError(
            f"票根册被清空/缩面：现算 {measured} < 地板 {cte.TICKETS_FLOOR}"
            "（缩面不是合规，是把尺子锯短）")


# --------------------------------------------------------------- 注毒自证（≥3 发）
def test_poison_empty_ticket_book_is_red() -> None:
    """注毒①：清空票根册 ⇒ 地板跌破、有原生声明却无票根的谓词必抓到。"""
    # 真数据先自证非空（否则地板腿空跑）
    assert cte.ticket_count() >= cte.TICKETS_FLOOR, "真票根册已跌破地板，注毒失去意义"
    # 地板腿真身：清空 ⇒ 现算枚数 < 地板，同一条 `test_ticket_scan_surface_floor...`
    # 里的 raise 会触发（这里锁"清空即跌破"这一手成立，不依赖真册大小）
    assert len(MappingProxyType({})) < cte.TICKETS_FLOOR
    # 谓词腿：带原生声明的假名册 + 空票根册 ⇒ 必非空
    poison_facets = {"bot.chat": ("native-audio",)}
    caught = cte.declared_native_without_ticket(
        MappingProxyType(poison_facets), MappingProxyType({})
    )
    assert caught == ["bot.chat:native-audio"], f"清空票根未被抓到＝判据无牙：{caught}"


def test_poison_pass_only_ticket_is_red() -> None:
    """注毒②：伪造一条只写达标值/留空字段的薄票根形状 ⇒ 必被判据点名。"""
    thin = cte.NativeTagTicket(
        capability_id="bot.chat",
        native_tag="native-video",
        measured_channel="x",
        request_shape="",            # 空字段
        response_evidence="PASS",    # 代理式达标值
        judged_at_utc="2026-09-24",
        criterion_source="tests/test_manifest_tag_evidence.py",
        reproduced_command="pytest",
    )
    assert cte.missing_reviewable_fields(thin) == ["request_shape"], "空字段未被抓到"
    assert cte.is_thin_response_evidence("PASS"), "PASS 未被判成薄票根"
    assert cte.is_thin_response_evidence("HTTP 200"), "状态码未被判成薄票根"
    assert not cte.is_thin_response_evidence(
        "响应正文逐字转写与源音频内容一致"), "真观测被误伤（过拦）"


def test_poison_native_declaration_without_ticket_is_red() -> None:
    """注毒③：往名册某能力加一枚**没有对应票根**的原生标签 ⇒ 声明→票根谓词必抓到。

    受害者必须选"没有该 kind 票根"的能力：`bot.chat` 三枚原生 kind 都握有票根，
    给它再加会命中真票根而漏判（本席首版就栽在这，测夹具不测判据）；改用 `bot.tts`
    这类无原生票根的能力，注入的 native-audio 无票根 ⇒ 必被抓。
    """
    real = _facets_tag_values()
    assert cte.declared_native_without_ticket(
        MappingProxyType(real), cte.TICKETS
    ) == [], "真数据已红，注毒样本无法自证"
    victims = [cid for cid in real if (cid, "native-audio") not in cte.TICKETS]
    assert victims, "所有已申报能力都有 native-audio 票根，注毒失去意义"
    victim = min(victims)
    poisoned = dict(real)
    poisoned[victim] = (*real[victim], "native-audio")
    caught = cte.declared_native_without_ticket(
        MappingProxyType(poisoned), cte.TICKETS
    )
    assert caught == [f"{victim}:native-audio"], f"注毒未被抓到＝腿无牙：{caught}"


def test_poison_ghost_capability_ticket_is_red() -> None:
    """注毒④：给未申报能力开票根 ⇒ 在册检查腿必抓到该 id。"""
    declared = cm.declared_ids()
    ghost = "capability.i-do-not-exist"
    assert ghost not in declared
    ghosts = sorted(cid for cid in {ghost, cte.NATIVE_CONSUMER_CAPABILITY} if cid not in declared)
    assert ghosts == [ghost], f"幽灵能力未被抓到：{ghosts}"


def test_poison_unknown_tag_value_is_red() -> None:
    """注毒⑤：票根标签写成枚举外字面量（如 `native-hologram`）⇒ 漂移腿必抓到。"""
    cm_native = _cm_native_values()
    assert "native-hologram" not in cm_native
    assert "native-hologram" not in cte.KNOWN_NATIVE_TAG_VALUES
    bad = [tag for tag in ("native-audio", "native-hologram")
           if tag not in cm_native or tag not in cte.KNOWN_NATIVE_TAG_VALUES]
    assert bad == ["native-hologram"], f"未知标签未被抓到：{bad}"


def test_poison_uncovered_channel_kind_is_red() -> None:
    """注毒⑥：渠道新增一枚原生 kind 而消费票根未跟上 ⇒ kind 覆盖腿必抓到。"""
    poison_channel_kinds = {"audio", "video", "animation", "hologram"}
    have = cte.native_kinds_with_tickets(cte.NATIVE_CONSUMER_CAPABILITY)
    uncovered = sorted(poison_channel_kinds - have)
    assert uncovered == ["hologram"], f"未覆盖 kind 未被抓到：{uncovered}"
