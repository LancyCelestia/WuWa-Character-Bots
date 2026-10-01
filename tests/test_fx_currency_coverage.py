"""汇率覆盖面三态名册与「绝不编数」回归锁（席位 F1，2026-10-02，全离线）。

需求书：``.superpowers/sdd/2026-10-02-fixwave/SEATS.md`` §6。用户点名 11 币
（``REQUIRED_CURRENCIES``），现盘只重合 7；本锁管的是**补齐过程中的诚实性**，
不是「四个币今天就有报价了」——RUB/CHF/CAD/AUD 至今没有任何已核实的报价腿
（``patches/S02-FINANCE-COVERAGE.md`` §2.1 记为「待验」，本席同样未做真机外发），
所以它们在名册里的合法状态只有 ``pending``，不许被写成有源、也不许被写成查无。

五把门（每把都配注毒腿＝做错必须红，与反向不误伤腿＝做对必须绿）：

① 有源必带凭据：宇宙表每一枚 secid 在 ``_FX_SOURCED_EVIDENCE`` 里有
   (实测日期, 实测方式)；``FX_UNAVAILABLE_PAIRS`` 每一枚在 ``_FX_ABSENT_EVIDENCE``
   里有凭据。⇒ 把待验/无源编成有源 ⇒ 门① 红（「为了齐全而编源」的代码级防线）。
② 三态封闭：点名清单每一枚恰好落在 sourced / pending / unavailable 之一，
   两处都不在＝静默消失 ⇒ 红。
③ 缺席必须可见：卡面行、纯文本面板、定向拒答三处都点名每一枚缺席币。
④ 币种名册单一真身：别名表值集＝展示名键集＝ISO 码识别正则，包内不许出现
   第二份硬抄的码清单。
⑤ 换算不编数：USD 三角只吃本轮在盘的**现货**腿，缺腿即 None，
   绝不落到常量/估算；待验币的拒答里不许出现任何「≈ 数字」。

网络出口全部 monkeypatch（``_fetch_payload`` / ``_fetch_fx_payload``），零外呼。
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.contracts.finance import FxRate
from plugins.bot_unified_runtime.domains.finance.capabilities import fx as fx_cap
from plugins.bot_unified_runtime.domains.finance.data import fx_data

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATES = ("sourced", "pending", "unavailable")
_UNQUOTABLE = ("RUB", "CHF", "CAD", "AUD")  # 席位 F1 待验四枚（用户点名清单里的缺口）


@pytest.fixture(autouse=True)
def _clean_fx_cache() -> Iterator[None]:
    fx_data.reset_fx_cache()
    yield
    fx_data.reset_fx_cache()


def _spot(pair: str, rate: float, stamp: str = "2026-10-02 10:00:00") -> FxRate:
    base, quote = pair.split("/", 1)
    return FxRate(
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        timestamp=stamp,
        rate_type="spot",
    )


def _live_rates() -> list[FxRate]:
    """一轮「上游全量返回」的在盘快照（数值取自本域既有夹具形状）。"""
    return [
        _spot("USD/CNY", 6.7081),
        _spot("USD/JPY", 155.2),
        _spot("EUR/USD", 1.0842),
        _spot("GBP/USD", 1.312),
        _spot("USD/KRW", 1445.5),
        _spot("USD/HKD", 7.7812),
        _spot("USD/SGD", 1.2905),
    ]


def _make_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        request_id="req-fx-coverage",
        platform="qq",
        adapter="onebot",
        bot_id="10000",
        session_id="group:g1",
        session_type=SessionType.GROUP,
        sender_id="u1",
        plain_text=text,
    )


def _make_decision() -> BotDecision:
    return BotDecision(
        request_id="req-fx-coverage",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id="bot.fx",
        target_scope=SessionType.GROUP,
        decision_reason="test",
    )


# ---------------------------------------------------------------------------
# 判据函数（三门共用；返回违规清单，空清单＝绿）
# ---------------------------------------------------------------------------


def _evidence_findings(
    universe: tuple[Any, ...], evidence: dict[str, tuple[str, str]]
) -> list[str]:
    """门①：宇宙表里每一枚 secid 必须有 (合法日期, 非空方式) 的实测凭据。"""
    findings: list[str] = []
    for pair, secid, *_rest in universe:
        entry = evidence.get(str(secid))
        if entry is None:
            findings.append(f"{pair}: secid {secid} 无实测凭据（不得进宇宙表）")
            continue
        day, method = entry
        if not _DATE_RE.match(str(day)):
            findings.append(f"{pair}: 凭据日期形态非法 {day!r}")
        if not str(method).strip():
            findings.append(f"{pair}: 凭据方式为空")
    return findings


def _state_findings(required: tuple[str, ...], availability: dict[str, str]) -> list[str]:
    """门②：每一枚点名币恰好一态；两处都不在＝静默消失。"""
    findings: list[str] = []
    for code in required:
        state = availability.get(code, "")
        head = state.split(":", 1)[0]
        if head not in _STATES:
            findings.append(f"{code}: 状态缺失或非法 {state!r}")
    return findings


def _absence_findings(carrier: str, codes: tuple[str, ...], where: str) -> list[str]:
    """门③：缺席币必须在载体里被点名（用 ISO 码认，中文展示名单列校验）。"""
    return [f"{where}: 缺席币 {code} 未被点名" for code in codes if code not in carrier]


# ---------------------------------------------------------------------------
# 门① · 有源必带凭据
# ---------------------------------------------------------------------------


class TestSourceEvidenceRoster:
    def test_every_universe_secid_has_evidence(self) -> None:
        assert _evidence_findings(
            fx_data._FX_PAIR_UNIVERSE, fx_data._FX_SOURCED_EVIDENCE
        ) == []

    def test_absent_pairs_have_their_own_evidence(self) -> None:
        for pair in fx_data.FX_UNAVAILABLE_PAIRS:
            entry = fx_data._FX_ABSENT_EVIDENCE.get(pair)
            assert entry is not None, f"{pair} 被写成查无却没有查无凭据"
            assert _DATE_RE.match(entry[0]) and entry[1].strip()

    def test_pending_candidates_are_never_sourced_or_absent(self) -> None:
        """待验候选同时出现在有源/查任何一处＝拿未证的事写成了结论。"""
        universe_secids = {secid for _p, secid, *_r in fx_data._FX_PAIR_UNIVERSE}
        universe_codes = {
            code for pair, *_r in fx_data._FX_PAIR_UNIVERSE for code in pair.split("/")
        }
        for code, candidates in fx_data.FX_PENDING_CANDIDATE_SECIDS.items():
            assert code in fx_data.SUPPORTED_CURRENCIES, f"{code} 未在册却挂了候选"
            assert code not in universe_codes, f"{code} 既算待验又算有源"
            for secid in candidates:
                assert secid not in universe_secids, f"{secid} 未核实却已进宇宙表"
            for pair in (f"USD/{code}", f"{code}/CNY"):
                assert pair not in fx_data.FX_UNAVAILABLE_PAIRS

    def test_poison_unverified_secid_in_universe_goes_red(self, monkeypatch) -> None:
        """注毒腿：把没凭据的 119.USDRUB 塞进宇宙表 ⇒ 门① 必须红。"""
        poisoned = fx_data._FX_PAIR_UNIVERSE + (
            ("USD/RUB", "119.USDRUB", "spot", 1.0, "美元兑俄罗斯卢布"),
        )
        findings = _evidence_findings(poisoned, fx_data._FX_SOURCED_EVIDENCE)
        assert any("119.USDRUB" in line for line in findings)
        # 反证：真往模块上打这个桩，覆盖表立即把该对子报成有源（正是危险形态）。
        monkeypatch.setattr(fx_data, "_FX_PAIR_UNIVERSE", poisoned)
        assert fx_data.fx_pair_availability()["USD/RUB"].startswith("eastmoney:")

    def test_poison_erase_evidence_goes_red(self, monkeypatch) -> None:
        """注毒腿（同门的另一侧）：抹掉一枚既有凭据 ⇒ 门① 红。"""
        thinned = dict(fx_data._FX_SOURCED_EVIDENCE)
        thinned.pop("119.USDSGD")
        assert _evidence_findings(fx_data._FX_PAIR_UNIVERSE, thinned)
        monkeypatch.setattr(fx_data, "_FX_SOURCED_EVIDENCE", thinned)
        assert any(
            "119.USDSGD" in line
            for line in _evidence_findings(
                fx_data._FX_PAIR_UNIVERSE, fx_data._FX_SOURCED_EVIDENCE
            )
        )


# ---------------------------------------------------------------------------
# 门② · 三态封闭（点名清单逐枚有票）
# ---------------------------------------------------------------------------


class TestCurrencyStateClosure:
    def test_required_currencies_are_all_declared(self) -> None:
        assert set(fx_data.REQUIRED_CURRENCIES) <= set(fx_data.SUPPORTED_CURRENCIES)

    def test_every_required_currency_lands_in_exactly_one_state(self) -> None:
        availability = fx_data.fx_currency_availability()
        assert _state_findings(fx_data.REQUIRED_CURRENCIES, availability) == []

    def test_states_are_mutually_exclusive(self) -> None:
        sourced = set()
        for pair, *_rest in fx_data._FX_PAIR_UNIVERSE:
            sourced |= set(pair.split("/"))
        for code in fx_data.SUPPORTED_CURRENCIES:
            state = fx_data.fx_currency_availability()[code]
            if code in sourced:
                assert state.startswith("sourced"), f"{code} 有实测源却领了别的票"
            if code in fx_data.FX_PENDING_CANDIDATE_SECIDS:
                assert code not in sourced, f"{code} 既算有源又算待验"

    def test_the_four_gap_currencies_are_pending_not_sourced(self) -> None:
        """需求书本体：RUB/CHF/CAD/AUD 今天只能是 pending——
        写成有源＝编源，写成查无＝替东财作了未做过的证。"""
        availability = fx_data.fx_currency_availability()
        for code in _UNQUOTABLE:
            state = availability[code]
            assert state.startswith("pending"), f"{code} 状态应为 pending，实为 {state!r}"
            assert "119." in state or "120." in state, f"{code} 的待验票没写候选腿"

    def test_poison_currency_without_any_state_goes_red(self, monkeypatch) -> None:
        """注毒腿：把 CHF 从三处名册同时摘掉 ⇒ 门② 必须红（不许静默消失）。"""
        thinned = {k: v for k, v in fx_data.FX_PENDING_CANDIDATE_SECIDS.items() if k != "CHF"}
        monkeypatch.setattr(fx_data, "FX_PENDING_CANDIDATE_SECIDS", thinned)
        findings = _state_findings(fx_data.REQUIRED_CURRENCIES, fx_data.fx_currency_availability())
        assert any("CHF" in line for line in findings), findings

    def test_poison_pending_written_as_sourced_goes_red(self, monkeypatch) -> None:
        """注毒腿：待验币被编成有源 ⇒ 门①（凭据）与门②（互斥）同时红。"""
        poisoned = fx_data._FX_PAIR_UNIVERSE + (
            ("USD/CHF", "119.USDCHF", "spot", 1.0, "美元兑瑞郎"),
        )
        assert _evidence_findings(poisoned, fx_data._FX_SOURCED_EVIDENCE), (
            "119.USDCHF 没有凭据，门① 必须先把这条行判红"
        )
        monkeypatch.setattr(fx_data, "_FX_PAIR_UNIVERSE", poisoned)
        # 一旦被写进宇宙表，币种状态立刻从 pending 翻成 sourced（这就是要拦的形态：
        # 名册自己不会拒绝，凭册才是唯一拦得住的东西）。
        assert fx_data.fx_currency_availability()["CHF"].startswith("sourced")


# ---------------------------------------------------------------------------
# 门③ · 缺席必须可见（三处载体同点名）
# ---------------------------------------------------------------------------


class TestAbsenceIsVisible:
    def test_card_row_names_every_unquoted_required_currency(self) -> None:
        rates = _live_rates()
        note = fx_data.fx_missing_note(rates)
        payload = fx_cap.build_fx_card_payload(rates, note, missing_sub=fx_data.fx_missing_sub(rates))
        rows = payload["sections"][0]["rows"]
        missing = next(row for row in rows if row["label"] == "暂无数据")
        assert _absence_findings(missing["value"], _UNQUOTABLE, "卡面") == []
        # 副标题不许再把「待验」说成「上游无行情」。
        assert "待真机核实" in missing["sub"] or "不给数字" in missing["sub"]

    def test_plain_text_panel_names_them_too(self) -> None:
        rates = _live_rates()
        text = fx_data.format_fx_brief(rates, fx_data.fx_missing_note(rates))
        assert _absence_findings(text, _UNQUOTABLE, "纯文本面板") == []

    def test_directed_question_about_pending_coin_answers_with_reason(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            fx_data, "fetch_fx_rates", lambda *a, **k: _live_rates()
        )
        capability = fx_cap.build_fx_capability()
        for text, code in (
            ("卢布汇率", "RUB"),
            ("瑞士法郎兑人民币", "CHF"),
            ("加元汇率", "CAD"),
            ("澳元换人民币", "AUD"),
        ):
            result = capability(_make_message(text), _make_decision())
            assert "暂无数据" in result.body, (text, result.body)
            assert code in result.body, (text, result.body)
            assert "待真机核实" in result.body, (text, result.body)
            # 绝不编数：拒答里不许出现任何换算结果。
            assert "≈" not in result.body, (text, result.body)
            assert "fx:pair_unavailable" in result.audit_tags

    def test_pending_note_and_absent_note_are_different_sentences(self) -> None:
        """「查无」与「还没探」必须两样话，混一句就是把未证写成结论。"""
        assert fx_data.fx_no_quote_reason("USD", "TWD") == "东财无该货币对行情"
        reason = fx_data.fx_no_quote_reason("RUB", "CNY")
        assert "尚未接入已核实报价源" in reason and "待真机核实" in reason
        assert "无该货币对行情" not in reason

    def test_poison_drop_absence_line_goes_red(self) -> None:
        """注毒腿：缺席说明被摘空 ⇒ 门③ 必红（回到「静默消失」形态）。"""
        rates = _live_rates()
        assert _absence_findings("", _UNQUOTABLE, "卡面")
        payload = fx_cap.build_fx_card_payload(rates, "")
        assert all(row["label"] != "暂无数据" for row in payload["sections"][0]["rows"])

    def test_runtime_dropped_row_is_named_not_silently_missing(self) -> None:
        """有实测源、本轮上游没回该行 ⇒ 也必须点名（限流空响应不掩成「没这币」）。"""
        rates = [_spot("USD/CNY", 6.7081)]
        note = fx_data.fx_missing_note(rates)
        assert "本轮上游未返回该行" in note
        for code in ("KRW", "SGD", "EUR"):
            assert code in note
        # 反向不误伤：全量在盘时不该出现「本轮缺行」这一句。
        assert "本轮上游未返回该行" not in fx_data.fx_missing_note(_live_rates())


# ---------------------------------------------------------------------------
# 门④ · 币种名册单一真身
# ---------------------------------------------------------------------------


class TestSingleSourceCurrencyRoster:
    def test_display_keys_equal_alias_values(self) -> None:
        assert set(fx_data._CURRENCY_DISPLAY) == set(fx_data._VALID_CODES)

    def test_iso_regex_covers_every_declared_code(self) -> None:
        pattern = fx_data._ISO_CODE_RE.pattern
        for code in fx_data._VALID_CODES:
            assert code in pattern, f"{code} 不在 ISO 识别正则里（触发面会与名册分裂）"

    def test_no_second_hardcoded_iso_list_in_has_currency_term(self) -> None:
        """注毒锁：``has_currency_term`` 里再出现硬抄的 ISO 码字面量即红。

        反向不误伤腿＝今天这条函数体只读 ``_ISO_CODE_RE``，必绿。"""
        source = inspect.getsource(fx_data.has_currency_term)
        strays = [
            code
            for code in fx_data._VALID_CODES
            if f'"{code}"' in source or f"'{code}'" in source
        ]
        assert strays == [], f"has_currency_term 又抄了第二份码清单：{strays}"
        assert "_ISO_CODE_RE" in source

    def test_new_currency_aliases_resolve_to_codes(self) -> None:
        for name, code in (
            ("卢布", "RUB"),
            ("俄罗斯卢布", "RUB"),
            ("盧布", "RUB"),
            ("瑞郎", "CHF"),
            ("瑞士法郎", "CHF"),
            ("加元", "CAD"),
            ("加拿大元", "CAD"),
            ("澳元", "AUD"),
            ("澳大利亚元", "AUD"),
            ("澳洲元", "AUD"),
            ("澳大利亞元", "AUD"),
        ):
            assert fx_data._CURRENCY_ALIASES[name] == code

    def test_ambiguous_colloquial_names_are_deliberately_not_aliases(self) -> None:
        """「澳币」也常指澳门元、「加币」撞加密语境——顶替币种＝报错数。"""
        for name in ("澳币", "加币", "法郎"):
            assert name not in fx_data._CURRENCY_ALIASES


# ---------------------------------------------------------------------------
# 门⑤ · USD 三角换算不编数
# ---------------------------------------------------------------------------


class TestUsdBridgeNeverFabricates:
    def test_bridge_only_uses_spot_legs_and_honours_unit_base(self) -> None:
        bridge = fx_data.fx_usd_bridge(_live_rates())
        assert set(bridge) == {"CNY", "JPY", "KRW", "HKD", "SGD", "EUR", "GBP"}
        assert fx_data.fx_per_usd(bridge["GBP"]) == pytest.approx(1 / 1.312)
        assert fx_data.fx_per_usd(bridge["CNY"]) == pytest.approx(6.7081)
        # 中间价行（100 日元口径的 parity）不参与换算桥：一格数字不许混两种口径。
        parity = FxRate(
            base_currency="JPY", quote_currency="CNY", rate=4.3614,
            unit_base=100.0, rate_type="parity",
        )
        assert fx_data.fx_per_usd(parity) is None
        assert fx_data.fx_usd_bridge([parity]) == {}

    def test_derived_rate_equals_cross_of_two_live_quotes(self) -> None:
        rates = _live_rates()
        derived, note = fx_data.fx_derived_quote(rates, "GBP", "CNY")
        table = {"USD": 1.0, "CNY": 6.7081, "GBP": 1 / 1.312}
        assert derived.rate == pytest.approx(fx_data.cross_rate_from_usd(table, "GBP", "CNY"))
        assert derived.rate == pytest.approx(6.7081 * 1.312)
        assert derived.rate_type == "derived"
        assert derived.unit_base == 1.0
        assert derived.delayed is True
        assert derived.history == ()
        for needle in ("GBP/USD", "USD/CNY", "非中间价", "非可成交价"):
            assert needle in note

    def test_missing_leg_returns_none_never_a_guess(self) -> None:
        # 待验币没有任何在盘腿 ⇒ 换不出来（None≠0，走诚实拒答通道）。
        assert fx_data.fx_derived_quote(_live_rates(), "RUB", "CNY") is None
        assert fx_data.fx_derived_quote([], "GBP", "CNY") is None
        assert fx_data.fx_derived_quote(_live_rates(), "GBP", "GBP") is None
        assert fx_data.fx_derived_quote(_live_rates(), "", "CNY") is None

    def test_non_finite_leg_is_refused(self) -> None:
        """注毒腿：把 Infinity 喂进桥里（json 默认接受该字面量）⇒ 仍不得出数。"""
        poisoned = [
            _spot("USD/CNY", 6.7081),
            FxRate(base_currency="GBP", quote_currency="USD", rate=float("inf"), rate_type="spot"),
        ]
        assert fx_data.fx_derived_quote(poisoned, "GBP", "CNY") is None

    def test_poison_fabricated_leg_flips_the_gate(self, monkeypatch) -> None:
        """注毒自证（证明本门不是永真）：真编一条不存在的腿，判据必须当场翻红。

        现算两条腿：① 未注毒时缺腿＝``None``（诚实拒答）；② 注毒（桥里冒出一条
        ``USD/RUB`` 假行）后同一调用出了数，本文件那条端到端判据
        ``test_directed_question_about_pending_coin_answers_with_reason`` 的断言
        全部翻红——「用估算冒充报价」在这里不是口号，是有闸门的。"""
        assert fx_data.fx_derived_quote(_live_rates(), "RUB", "CNY") is None

        real_bridge = fx_data.fx_usd_bridge

        def _fabricating_bridge(_rates: Any) -> dict[str, FxRate]:
            bridge = dict(real_bridge(_live_rates()))
            bridge["RUB"] = _spot("USD/RUB", 1.0)  # 编一条上游没给的腿
            return bridge

        monkeypatch.setattr(fx_data, "fx_usd_bridge", _fabricating_bridge)
        poisoned = fx_data.fx_derived_quote(_live_rates(), "RUB", "CNY")
        assert poisoned is not None, "注毒没生效，本自证腿失去意义"
        assert poisoned[0].rate > 0
        # 端到端：能力层会把这条编出来的数当报价发给用户 ⇒ 端到端判据必红。
        monkeypatch.setattr(
            fx_data, "fetch_fx_rates", lambda *a, **k: _live_rates()
        )
        result = fx_cap.build_fx_capability()(_make_message("卢布汇率"), _make_decision())
        assert "≈" in result.body and "暂无数据" not in result.body
        assert "fx:pair_unavailable" not in result.audit_tags

    def test_directed_query_uses_cross_and_says_so(self, monkeypatch) -> None:
        """反向不误伤腿：有两条实测现货腿时（英镑/韩元/新加坡元兑人民币），
        必须给数并标交叉换算口径，而不是一句「东财无该货币对行情」。"""
        monkeypatch.setattr(
            fx_data, "fetch_fx_rates", lambda *a, **k: _live_rates()
        )
        capability = fx_cap.build_fx_capability()
        for text, code in (("英镑汇率", "GBP"), ("韩元汇率", "KRW"), ("新加坡元汇率", "SGD")):
            result = capability(_make_message(text), _make_decision())
            assert "≈" in result.body, (text, result.body)
            assert f"fx:cross:{code}/CNY" in result.audit_tags, result.audit_tags
            assert "非中间价" in result.body
            assert "无该货币对行情" not in result.body

    def test_derived_rows_stay_out_of_the_panel(self, monkeypatch) -> None:
        """面板卡只列实测源行：derived 不进面板，避免与中间价同格混口径。"""
        rates = _live_rates()
        payload = fx_cap.build_fx_card_payload(rates, fx_data.fx_missing_note(rates))
        labels = [row["label"] for row in payload["sections"][0]["rows"]]
        assert all("/CNY" not in label for label in labels if label.startswith(("GBP", "KRW", "SGD")))

    def test_direct_source_always_wins_over_cross(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fx_data, "fetch_fx_rates", lambda *a, **k: _live_rates()
        )
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑人民币"), _make_decision())
        assert "fx:pair:USD/CNY" in result.audit_tags
        assert "交叉换算" not in result.body and "三角换算" not in result.body


# ---------------------------------------------------------------------------
# 促升演练：候选核实后「加一行」是否真能端到端接通
# ---------------------------------------------------------------------------


class TestPromotionIsOneLineDeep:
    """需求书要的「补齐」＝核实之后一推即通；本类用桩模拟那一天。"""

    _PROMOTED = ("USD/RUB", "119.USDRUB", "spot", 1.0, "美元兑俄罗斯卢布")

    @pytest.fixture()
    def _promoted_rub(self, monkeypatch) -> None:
        universe = fx_data._FX_PAIR_UNIVERSE + (self._PROMOTED,)
        monkeypatch.setattr(fx_data, "_FX_PAIR_UNIVERSE", universe)
        monkeypatch.setattr(
            fx_data,
            "_PAIRS_BY_KEY",
            {
                pair: (secid, rate_type, unit_base, display)
                for pair, secid, rate_type, unit_base, display in universe
            },
        )
        evidence = dict(fx_data._FX_SOURCED_EVIDENCE)
        evidence["119.USDRUB"] = ("2026-10-02", "单元测试模拟的真机命中（促升演练）")
        monkeypatch.setattr(fx_data, "_FX_SOURCED_EVIDENCE", evidence)
        rates = _live_rates() + [_spot("USD/RUB", 92.4, "2026-10-02 10:00:05")]
        monkeypatch.setattr(fx_data, "fetch_fx_rates", lambda *a, **k: rates)

    def test_promotion_keeps_every_gate_green(self, _promoted_rub: None) -> None:
        assert _evidence_findings(
            fx_data._FX_PAIR_UNIVERSE, fx_data._FX_SOURCED_EVIDENCE
        ) == []
        assert _state_findings(
            fx_data.REQUIRED_CURRENCIES, fx_data.fx_currency_availability()
        ) == []
        assert fx_data.fx_currency_availability()["RUB"].startswith("sourced")

    def test_promoted_coin_answers_directly_and_by_cross(self, _promoted_rub: None) -> None:
        capability = fx_cap.build_fx_capability()
        direct = capability(_make_message("美元兑卢布"), _make_decision())
        assert "fx:pair:USD/RUB" in direct.audit_tags
        assert "≈" in direct.body
        cross = capability(_make_message("卢布汇率"), _make_decision())
        assert "fx:cross:RUB/CNY" in cross.audit_tags
        assert "暂无数据" not in cross.body
        assert "非中间价" in cross.body

    def test_promoted_coin_leaves_the_absence_note(self, _promoted_rub: None) -> None:
        rates = fx_data.fetch_fx_rates()
        note = fx_data.fx_missing_note(rates)
        assert "RUB" not in note  # 有源且本轮在盘 ⇒ 不再点名缺席
        assert "CHF" in note and "CAD" in note and "AUD" in note

    def test_promoted_pair_loses_its_pending_ticket(self, _promoted_rub: None) -> None:
        table = fx_data.fx_pair_availability()
        assert table["USD/RUB"] == "eastmoney:119.USDRUB spot"
        assert table["RUB/CNY"] == "cross: USD/RUB+USD/CNY"

    def test_poison_promotion_without_key_index_goes_red(self, monkeypatch) -> None:
        """注毒腿：只加宇宙表、忘了 ``_PAIRS_BY_KEY``（真跑时它由导入期派生，
        桩里手动派生漏掉就会「有源却报不出直盘」）——直盘判定必须仍然成立才算通。"""
        monkeypatch.setattr(fx_data, "_FX_PAIR_UNIVERSE", fx_data._FX_PAIR_UNIVERSE + (self._PROMOTED,))
        rates = _live_rates() + [_spot("USD/RUB", 92.4)]
        monkeypatch.setattr(fx_data, "fetch_fx_rates", lambda *a, **k: rates)
        assert fx_data.resolve_fx_pair("USD", "RUB") is None  # 名册没重建的形态
        capability = fx_cap.build_fx_capability()
        result = capability(_make_message("美元兑卢布"), _make_decision())
        # 名册没重建时只能走三角换算，绝不允许假装成实测直盘行。
        assert "fx:cross:USD/RUB" in result.audit_tags


# ---------------------------------------------------------------------------
# 可达性探针：只读取证、生产链路不调用
# ---------------------------------------------------------------------------


class TestCandidateProbeIsReadOnly:
    def test_probe_reports_hit_no_row_and_bad_value(self, monkeypatch) -> None:
        payload = {
            "data": {
                "diff": [
                    {"f12": "USDRUB", "f2": 92.4, "f14": "美元兑俄罗斯卢布"},
                    {"f12": "USDCHF", "f2": "-", "f14": "美元兑瑞士法郎"},
                ]
            }
        }
        calls: list[str] = []

        def _fake(secids: str, timeout: float) -> dict:
            calls.append(secids)
            return payload

        monkeypatch.setattr(fx_data, "_fetch_payload", _fake)
        report = fx_data.probe_fx_candidates()
        assert len(calls) == 1  # 一次批量外呼，不逐币循环。
        assert report["RUB"]["quoted"] is True
        assert report["RUB"]["hit"][0]["secid"] == "119.USDRUB"
        assert "119.USDCHF" in report["CHF"]["bad_value"]
        assert "119.CHFUSD" in report["CHF"]["no_row"]
        assert report["AUD"]["quoted"] is False
        # 探针不污染进程内汇率缓存（否则待验源的数字会溜进面板）。
        assert fx_data._FX_RATE_CACHE is None

    def test_probe_swallows_network_errors(self, monkeypatch) -> None:
        def _boom(secids: str, timeout: float) -> dict:
            raise OSError("no route")

        monkeypatch.setattr(fx_data, "_fetch_payload", _boom)
        report = fx_data.probe_fx_candidates()
        assert all(entry.get("error") == "OSError" for entry in report.values())

    def test_probe_is_not_called_by_production_path(self) -> None:
        """候选腿在核实前绝不被生产链路静默使用：AST 扫调用点，只准有定义。"""
        call_sites: list[str] = []
        for module in (fx_data, fx_cap):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name == "probe_fx_candidates":
                    call_sites.append(f"{module.__name__}:{node.lineno}")
        assert call_sites == [], f"探针被接线了：{call_sites}"

    def test_poison_probe_wired_into_capability_goes_red(self) -> None:
        """注毒腿：AST 锁不是永真——真接一次就必须抓得到。"""
        poisoned_source = (
            "def capability():\n"
            "    return probe_fx_candidates()\n"
        )
        tree = ast.parse(poisoned_source)
        sites = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
            == "probe_fx_candidates"
        ]
        assert sites == [2]


# ---------------------------------------------------------------------------
# 触发面：新币名要认得，但不许劫持日常话
# ---------------------------------------------------------------------------


class TestTriggerSurfaceForNewCurrencies:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("卢布汇率", ("RUB", "CNY", 1.0)),
            ("俄罗斯卢布兑人民币", ("RUB", "CNY", 1.0)),
            ("盧布汇率", ("RUB", "CNY", 1.0)),
            ("瑞郎汇率", ("CHF", "CNY", 1.0)),
            ("100瑞士法郎换多少人民币", ("CHF", "CNY", 100.0)),
            ("加元汇率", ("CAD", "CNY", 1.0)),
            ("加拿大元兑美元", ("CAD", "USD", 1.0)),
            ("澳元汇率", ("AUD", "CNY", 1.0)),
            ("澳元兑美元", ("AUD", "USD", 1.0)),
            ("USD/RUB", ("USD", "RUB", 1.0)),
            ("美元兑卢布", ("USD", "RUB", 1.0)),
        ],
    )
    def test_parse_matrix(self, text: str, expected: tuple[str, str, float]) -> None:
        assert fx_data.parse_fx_query(text) == expected

    @pytest.mark.parametrize("text", ["卢布汇率", "澳元换算", "加元汇率", "USD/RUB"])
    def test_triggers(self, text: str) -> None:
        assert fx_cap.is_fx_command(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "把间距增加元素换算一下",  # 「加元」是「增加元素」的子串
            "audio换算",  # 「aud」被单词胶合
            "decade 换算",  # 「cad」同上
            "单位换算",
            "今天天气怎么样",
        ],
    )
    def test_does_not_hijack_daily_chat(self, text: str) -> None:
        assert fx_cap.is_fx_command(text) is False

    def test_poison_iso_regex_loose_goes_red(self) -> None:
        """注毒腿：如果哪天码识别退回「裸子串」，audio/decade 会被劫持。"""
        assert re.search(r"(?<![A-Za-z])(?:CAD)(?![A-Za-z])", "audio") is None
        assert re.search(r"(?<![A-Za-z])(?:CAD)(?![A-Za-z])", "decade") is None
        assert re.search(r"(?<![A-Za-z])(?:CAD)(?![A-Za-z])", "美元换算 CAD") is not None
