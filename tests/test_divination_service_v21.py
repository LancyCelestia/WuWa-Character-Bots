"""V2.1 S12 占卜统一服务套件（A15 占卜席，替换前席 W6 草稿）。

覆盖 docs/design/backend-v2-product-extensions.md §3 合同（V21-DIVINATION-001/002）：

- 牌库登记：78 张唯一 card_id（22 大 + 56 小）、DECK_REVISION 确定性；
- 塔罗抽取：k 范围/无重复/位置序列/正逆位分布（置信区间容差）/固定 seed
  逐字节回归（含跨进程子进程复现，证明无 Python hash 依赖）；
- 每日运势：多 seed 频率按样本置信区间（不用不稳定随机门禁）、day_key
  同日跨会话相同/跨日不同/时区边界、重读不限、审计三件套（key_id/
  seed_digest/rule_version）；
- 持久化语义：draw_id/幂等键重试不变、并发创建唯一、重启与密钥轮换不
  刷新当天、先持久化后解读、解释胡编牌面/第 79 张/换版本被拒；
- 契约与门禁：DrawRequest 严格校验（question≤500、extra=forbid、时区可
  加载）、invalid_spread 白名单、feature_disabled、配额（冷却 60s/每日
  20 次/workspace 独立/按本地日计数）；
- 错误码全部取自 contracts/errors.py 注册表（缺码即本测试失败）。

全部离线：tmp_path SQLite + 注入 seed/clock，无网络、无真实 LLM。
八字既有回归集（tests/test_divination.py）不在本文件域，由收尾实跑证明
不破坏（本批对 divination 链只增不改）。

【前席草稿处置】本文件替换了前席 W6 的同名未跟踪草稿（其 capability 集成
半边依赖 sources/draw_store.py + capabilities/divination.py WIP，二者均原样
保留未动；草稿全文备份于 %TEMP%/v21-divination-w6-backup/）。
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from math import sqrt
from pathlib import Path

import pytest
from pydantic import ValidationError

from plugins.bot_unified_runtime.domains.core.contracts.errors import (
    ERROR_REGISTRY,
    error_body,
)
from plugins.bot_unified_runtime.domains.divination.data.tarot import DECK
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    ASSET_IDS_EMPTY,
    DISCLAIMER_ID,
    DISCLAIMER_TEXT,
    DivinationService,
    DrawRequest,
    TrustedDrawContext,
    build_interpretation_context,
)
from plugins.bot_unified_runtime.domains.divination.service.fortune import (
    FORTUNE_ALGORITHM_REVISION,
    FORTUNE_GRADES_V1,
    FORTUNE_RULE_VERSION,
    SeededPrng,
    draw_fortune_grade,
    fortune_day_key,
)
from plugins.bot_unified_runtime.domains.divination.service.tarot_draw import (
    DECK_REVISION,
    POSITION_LABELS,
    SPREADS,
    TAROT_ALGORITHM_REVISION,
    build_card_index,
    card_id_for,
    draw_tarot_cards,
    validate_spread,
)
from plugins.bot_unified_runtime.domains.divination.store.draw_store import (
    DrawError,
    DrawRecord,
    DrawStore,
)

_TEST_SECRET = b"a15-unit-secret"

# 固定时钟：2026-09-17 04:00 UTC（上海本地 2026-09-17 12:00）。
_BASE_NOW = datetime(2026, 9, 17, 4, 0, tzinfo=UTC)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ctx(
    *,
    offset_seconds: float = 0.0,
    principal: str = "user-1",
    bot: str = "bot-1",
) -> TrustedDrawContext:
    return TrustedDrawContext(
        principal_id=principal,
        bot_id=bot,
        now=_BASE_NOW + timedelta(seconds=offset_seconds),
    )


def _req(
    kind: str = "tarot",
    *,
    spread_id: str | None = "single",
    key: str = "key-1",
    workspace: str = "ws-1",
    tz: str = "Asia/Shanghai",
    question: str = "最近运势如何",
) -> DrawRequest:
    return DrawRequest(
        kind=kind,  # type: ignore[arg-type]
        spread_id=spread_id,
        question=question,
        timezone_id=tz,
        workspace_id=workspace,
        idempotency_key=key,
    )


class _SequentialPrngs:
    """确定性注入源：第 n 次抽取用 SeededPrng(base + n)，逐字节可复现。"""

    def __init__(self, base: int = 0) -> None:
        self._counter = itertools.count()
        self._base = base

    def __call__(self) -> SeededPrng:
        return SeededPrng(self._base + next(self._counter))


def _svc(
    store: DrawStore,
    *,
    secret: bytes = _TEST_SECRET,
    prng_base: int = 0,
    enabled: bool = True,
    cooldown: int = 60,
    daily_limit: int = 20,
) -> DivinationService:
    return DivinationService(
        store,
        secret=secret,
        enabled=enabled,
        prng_factory=_SequentialPrngs(prng_base),
        tarot_cooldown_seconds=cooldown,
        tarot_daily_limit=daily_limit,
        trace_factory=lambda: "trace_test_fixed",
    )


# ---------------------------------------------------------------------------
# 牌库登记（合同：78 张唯一 card_id，22 大 56 小）。
# ---------------------------------------------------------------------------


class TestDeckRegistry:
    def test_78_unique_cards_22_major_56_minor(self) -> None:
        index = build_card_index()
        assert len(DECK) == 78
        assert len(index) == 78
        majors = [cid for cid in index if cid.startswith("major-")]
        assert len(majors) == 22
        minors = [cid for cid in index if not cid.startswith("major-")]
        assert len(minors) == 56
        for suit in ("wands", "cups", "swords", "pentacles"):
            suit_ids = [cid for cid in minors if cid.startswith(f"{suit}-")]
            assert len(suit_ids) == 14

    def test_deck_revision_deterministic_hex16(self) -> None:
        from plugins.bot_unified_runtime.domains.divination.service.tarot_draw import (
            _compute_deck_revision,
        )

        assert DECK_REVISION == _compute_deck_revision()
        assert len(DECK_REVISION) == 16
        int(DECK_REVISION, 16)  # 必须是十六进制摘要

    def test_card_id_roundtrip(self) -> None:
        index = build_card_index()
        for card_id in ("major-00", "major-21", "wands-01", "pentacles-14"):
            assert card_id_for(index[card_id]) == card_id

    def test_domain_error_codes_are_registered(self) -> None:
        # 缺码即失败：全局注册表席位无需再补本席错误码。
        for code in (
            "invalid_spread",
            "deck_integrity_mismatch",
            "feature_disabled",
            "rate_limited",
            "idempotency_conflict",
            "resource_not_found",
        ):
            assert code in ERROR_REGISTRY


# ---------------------------------------------------------------------------
# 塔罗抽取算法（k 范围/无重复/朝向分布/固定 seed 回归）。
# ---------------------------------------------------------------------------


class TestTarotDrawAlgorithm:
    def test_spread_whitelist_positions(self) -> None:
        assert validate_spread("single") == (1, ("",))
        assert validate_spread("past_present_future") == (
            3,
            ("past", "present", "future"),
        )
        count, positions = validate_spread("celtic_cross")
        assert count == 10 and len(positions) == 10
        for spread_id in ("", "five_card", "celtic-cross", "任意阵型"):
            with pytest.raises(DrawError) as excinfo:
                validate_spread(spread_id)
            assert excinfo.value.code == "invalid_spread"

    def test_k_range_no_duplicates_exact_positions(self) -> None:
        for n in range(20):
            prng = SeededPrng(10_000 + n)
            for spread_id, (count, positions) in SPREADS.items():
                cards = draw_tarot_cards(spread_id, prng)
                assert len(cards) == count
                card_ids = [card["card_id"] for card in cards]
                assert len(set(card_ids)) == count  # 无放回：无重复
                assert [card["position_id"] for card in cards] == list(positions)
                index = build_card_index()
                assert all(card["card_id"] in index for card in cards)
                assert all(
                    card["orientation"] in {"upright", "reversed"} for card in cards
                )

    def test_orientation_distribution_within_confidence_interval(self) -> None:
        # n=300、p=0.5：4σ 容差 ≈ ±0.115，既无不稳定门禁又能抓方向性偏差。
        reversed_count = 0
        for n in range(300):
            card = draw_tarot_cards("single", SeededPrng(20_000 + n))[0]
            reversed_count += card["orientation"] == "reversed"
        fraction = reversed_count / 300
        assert 0.385 <= fraction <= 0.615
        assert 0 < reversed_count < 300  # 两个朝向都真实出现

    def test_fixed_seed_regression_byte_identical(self) -> None:
        # 黄金值首采于 2026-09-17（SeededPrng 走 random.Random(int)，稳定）；
        # 逐字节一致 = 抽取算法或池序任何变化都会被拦下。
        cards = draw_tarot_cards("past_present_future", SeededPrng(42))
        golden = json.dumps(list(cards), ensure_ascii=False, sort_keys=True)
        assert golden == (
            '[{"card_id": "major-21", "orientation": "upright", '
            '"position_id": "past"}, {"card_id": "cups-04", '
            '"orientation": "reversed", "position_id": "present"}, '
            '{"card_id": "pentacles-10", "orientation": "reversed", '
            '"position_id": "future"}]'
        )
        prng = SeededPrng(20260917)
        assert draw_tarot_cards("single", prng)[0]["card_id"] == "pentacles-10"
        assert (
            draw_tarot_cards("past_present_future", prng)[0]["card_id"]
            == "pentacles-11"
        )
        assert len(draw_tarot_cards("celtic_cross", prng)) == 10
        # day_key 与固定 seed 运势等级同步钉帧。
        assert fortune_day_key(
            "p1", "bot1", "2026-09-17", "v1"
        ).startswith("6388940e6102")
        assert draw_fortune_grade(SeededPrng(7)) == "中吉"

    def test_fixed_seed_regression_across_process(self) -> None:
        # 跨进程复现同一黄金值：证明随机源不经过 Python hash()
        # （PYTHONHASHSEED 不影响结果），满足"禁 Python hash 跨进程重放"。
        snippet = (
            "import json;"
            "from plugins.bot_unified_runtime.domains.divination.service.tarot_draw import draw_tarot_cards;"
            "from plugins.bot_unified_runtime.domains.divination.service.fortune import SeededPrng;"
            "print(json.dumps(list(draw_tarot_cards('past_present_future', "
            "SeededPrng(42))), ensure_ascii=False, sort_keys=True))"
        )
        env = dict(
            os.environ,
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
            BOT_AUTOSYNC="0",
            PYTHONPATH=str(_PROJECT_ROOT),
        )
        completed = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(_PROJECT_ROOT),
            env=env,
            timeout=120,
            check=True,
        )
        cards = draw_tarot_cards("past_present_future", SeededPrng(42))
        assert completed.stdout.strip() == json.dumps(
            list(cards), ensure_ascii=False, sort_keys=True
        )

    def test_multi_seed_fortune_frequency_within_sample_ci(self) -> None:
        # 每 seed 6000 样本 × 5 seed；5σ 容差按样本置信区间设定，
        # 不用"必须出现某个等级"这类不稳定随机门禁。
        n = 6000
        for seed in (11, 22, 33, 44, 55):
            prng = SeededPrng(seed)
            counts = {grade: 0 for grade, _ in FORTUNE_GRADES_V1}
            for _ in range(n):
                counts[draw_fortune_grade(prng)] += 1
            for grade, weight in FORTUNE_GRADES_V1:
                p = weight / 100
                tolerance = 5 * sqrt(p * (1 - p) / n) + 1e-9
                deviation = abs(counts[grade] / n - p)
                assert deviation <= tolerance, (
                    f"seed={seed} grade={grade} 偏差 {deviation:.4f} 超出 5σ"
                )


# ---------------------------------------------------------------------------
# 每日运势服务语义（day_key 唯一 / 时区 / 重启 / 密钥轮换 / 审计）。
# ---------------------------------------------------------------------------


class TestDailyFortuneSemantics:
    def test_same_day_cross_session_same_result(self, tmp_path: Path) -> None:
        path = tmp_path / "draws.sqlite3"
        first = _svc(DrawStore(path)).create_draw(
            _req("fortune", key="f-1"), _ctx()
        )
        # 新会话：新 store + 新服务实例 + 不同幂等键 → 同日不重抽。
        second = _svc(DrawStore(path)).create_draw(
            _req("fortune", key="f-2"), _ctx()
        )
        assert second.fortune_grade == first.fortune_grade
        assert second.draw_id == first.draw_id
        assert fortune_day_key("user-1", "bot-1", "2026-09-17", FORTUNE_RULE_VERSION)

    def test_key_rotation_and_restart_do_not_refresh_today(self, tmp_path: Path) -> None:
        path = tmp_path / "draws.sqlite3"
        first = _svc(DrawStore(path)).create_draw(_req("fortune", key="r-1"), _ctx())
        # 密钥轮换：新 secret 重启后同日必须命中既有行（day_key 不含密钥）。
        rotated = _svc(DrawStore(path), secret=b"rotated-secret")
        second = rotated.create_draw(_req("fortune", key="r-2"), _ctx())
        assert second.fortune_grade == first.fortune_grade
        assert second.draw_id == first.draw_id

    def test_cross_day_creates_new_draw(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        day1 = _svc(store).create_draw(_req("fortune", key="d-1"), _ctx())
        day2 = _svc(store).create_draw(
            _req("fortune", key="d-2"), _ctx(offset_seconds=86_400)
        )
        assert day2.draw_id != day1.draw_id
        row1 = store.get_draw(day1.draw_id)
        row2 = store.get_draw(day2.draw_id)
        assert row1 is not None and row2 is not None
        assert row1.dedupe_key != row2.dedupe_key

    def test_timezone_boundary_same_instant(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        # 上海视角 _BASE_NOW 是 2026-09-17；同一"自然日"由时区决定——
        # UTC 视角 2026-09-16 20:00Z 才是上海 09-17 04:00（日期错位边界）。
        shanghai = _svc(store).create_draw(
            _req("fortune", key="tz-sh", tz="Asia/Shanghai"), _ctx()
        )
        utc_draw = _svc(store).create_draw(
            _req("fortune", key="tz-utc", tz="UTC"),
            _ctx(offset_seconds=-8 * 3600),  # UTC 2026-09-16 20:00
        )
        sh2 = store.get_draw(shanghai.draw_id)
        ut2 = store.get_draw(utc_draw.draw_id)
        assert sh2 is not None and ut2 is not None
        assert sh2.local_day == "2026-09-17"
        assert ut2.local_day == "2026-09-16"
        assert sh2.dedupe_key != ut2.dedupe_key

    def test_fortune_re_read_unlimited(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store)
        first = service.create_draw(_req("fortune", key="rr-0"), _ctx())
        for n in range(5):
            again = service.create_draw(_req("fortune", key=f"rr-{n + 1}"), _ctx())
            assert again.fortune_grade == first.fortune_grade
            assert service.get_draw(first.draw_id).fortune_grade == first.fortune_grade

    def test_fortune_audit_fields(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        result = _svc(store).create_draw(_req("fortune", key="aud-1"), _ctx())
        record = store.get_draw(result.draw_id)
        assert record is not None
        assert record.algorithm_revision == FORTUNE_ALGORITHM_REVISION
        expected_key_id = hashlib.sha256(_TEST_SECRET).hexdigest()[:8]
        assert record.key_id == expected_key_id  # 审计存 key_id（密钥摘要前缀）
        assert len(record.seed_digest) == 16  # 审计存种子摘要（不泄露原值）
        int(record.seed_digest, 16)
        assert record.fortune_grade in {grade for grade, _ in FORTUNE_GRADES_V1}

    def test_fortune_ignores_workspace_scope(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store)
        ws_a = service.create_draw(
            _req("fortune", key="fw-a", workspace="ws-a"), _ctx()
        )
        ws_b = service.create_draw(
            _req("fortune", key="fw-b", workspace="ws-b"), _ctx()
        )
        # day_key 不含 workspace：同日全工作区同一结果（运势非工作区配额面）。
        assert ws_b.fortune_grade == ws_a.fortune_grade
        assert ws_b.draw_id == ws_a.draw_id


# ---------------------------------------------------------------------------
# 塔罗服务语义（先持久化后解读 / 重试不变 / 胡编被拒 / 白名单 / 配额）。
# ---------------------------------------------------------------------------


class TestTarotServiceSemantics:
    def test_persist_before_interpret_and_contract_shape(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        result = _svc(store).create_draw(
            _req("tarot", spread_id="past_present_future", key="t-1"), _ctx()
        )
        record = store.get_draw(result.draw_id)
        assert record is not None  # 解读发生前结果已持久化
        assert result.cards == tuple(dict(c) for c in record.cards)
        assert result.algorithm_revision == TAROT_ALGORITHM_REVISION
        assert result.deck_revision == DECK_REVISION
        assert result.asset_ids == ASSET_IDS_EMPTY == ()
        assert result.disclaimer_id == DISCLAIMER_ID
        assert result.trace_id
        assert result.interpretation_lines[-1] == DISCLAIMER_TEXT
        index = build_card_index()
        for line, card in zip(result.interpretation_lines, result.cards):
            assert index[card["card_id"]].name in line  # 解读只引用持久牌面

    def test_draw_id_and_idempotency_retry_stable(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        first = _svc(store, prng_base=100).create_draw(
            _req("tarot", spread_id="celtic_cross", key="retry-1"), _ctx()
        )
        # 新服务实例（不同 prng 流）+ 同幂等键：必须返回既有抽取，不换牌。
        second = _svc(store, prng_base=999).create_draw(
            _req("tarot", spread_id="celtic_cross", key="retry-1"), _ctx()
        )
        assert second.draw_id == first.draw_id
        assert second.cards == first.cards
        assert second.interpretation_lines == first.interpretation_lines
        assert _svc(store).get_draw(first.draw_id).cards == first.cards

    def test_interpretation_rejects_fabricated_cards(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        result = _svc(store).create_draw(
            _req("tarot", spread_id="celtic_cross", key="fab-1"), _ctx()
        )

        def _tamper(mutate) -> None:  # type: ignore[no-untyped-def]
            record = store.get_draw(result.draw_id)
            assert record is not None
            cards = mutate([dict(card) for card in record.cards])
            connection = sqlite3.connect(str(store.db_path))
            try:
                connection.execute(
                    "UPDATE draws SET cards_json = ? WHERE draw_id = ?",
                    (
                        json.dumps(cards, ensure_ascii=False, sort_keys=True),
                        result.draw_id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

        def _assert_mismatch() -> None:
            with pytest.raises(DrawError) as excinfo:
                build_interpretation_context(store.get_draw(result.draw_id))
            assert excinfo.value.code == "deck_integrity_mismatch"

        # 伪造第 79 张（多出一张）→ 拒绝。
        _tamper(
            lambda cards: cards
            + [
                {
                    "card_id": "major-22",
                    "position_id": "outcome",
                    "orientation": "upright",
                }
            ]
        )
        _assert_mismatch()
        # 恢复后换一张牌库外的牌（数量不变）→ 拒绝。
        _tamper(lambda cards: [*cards[:-1], {**cards[-1], "card_id": "major-22"}])
        _assert_mismatch()
        # 非法朝向 → 拒绝。
        _tamper(lambda cards: [*cards[:-1], {**cards[-1], "orientation": "sideways"}])
        _assert_mismatch()
        # 位置序列被换 → 拒绝。
        _tamper(lambda cards: [*cards[:-1], {**cards[-1], "position_id": "swapped"}])
        _assert_mismatch()
        # 牌库版本漂移 → 拒绝。
        connection = sqlite3.connect(str(store.db_path))
        try:
            connection.execute(
                "UPDATE draws SET deck_revision = 'deadbeef' WHERE draw_id = ?",
                (result.draw_id,),
            )
            connection.commit()
        finally:
            connection.close()
        _assert_mismatch()

    def test_invalid_spread_rejected(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store)
        for spread_id in ("five_card", "Single", ""):
            with pytest.raises(DrawError) as excinfo:
                service.create_draw(
                    _req("tarot", spread_id=spread_id, key=f"inv-{spread_id}"),
                    _ctx(),
                )
            assert excinfo.value.code == "invalid_spread"
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(_req("tarot", spread_id=None, key="inv-none"), _ctx())
        assert excinfo.value.code == "invalid_spread"

    def test_tarot_quota_cooldown_60s(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store, cooldown=60)
        assert service.create_draw(_req(key="q-1"), _ctx(offset_seconds=0))
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(_req(key="q-2"), _ctx(offset_seconds=59))
        assert excinfo.value.code == "rate_limited"
        # 冷却过后：当日第 2 次（<20）放行。
        result = service.create_draw(_req(key="q-3"), _ctx(offset_seconds=61))
        assert len(result.cards) == 1

    def test_tarot_daily_limit_twenty_then_limited(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store, cooldown=0, daily_limit=20)
        for n in range(20):
            service.create_draw(_req(key=f"day-{n}"), _ctx(offset_seconds=n * 0.001))
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(_req(key="day-20"), _ctx(offset_seconds=1))
        assert excinfo.value.code == "rate_limited"

    def test_quota_is_workspace_independent(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store, cooldown=0, daily_limit=2)
        for n in range(2):
            service.create_draw(
                _req(key=f"wsa-{n}", workspace="ws-a"), _ctx(offset_seconds=n)
            )
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(
                _req(key="wsa-2", workspace="ws-a"), _ctx(offset_seconds=2)
            )
        assert excinfo.value.code == "rate_limited"
        # 另一工作区配额独立：首抽放行。
        other = service.create_draw(
            _req(key="wsb-0", workspace="ws-b"), _ctx(offset_seconds=3)
        )
        assert len(other.cards) == 1

    def test_daily_limit_counts_by_local_day(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store, cooldown=0, daily_limit=1)
        # 上海本地 2026-09-17 23:59:58 抽第 1 次（当日配额用尽）。
        edge = TrustedDrawContext(
            principal_id="user-1",
            bot_id="bot-1",
            now=datetime(2026, 9, 17, 15, 59, 58, tzinfo=UTC),
        )
        service.create_draw(_req(key="mid-1", tz="Asia/Shanghai"), edge)
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(_req(key="mid-2", tz="Asia/Shanghai"), edge)
        assert excinfo.value.code == "rate_limited"
        # +3s 已是上海本地 09-18 00:00:01 → 新的本地日，配额重置放行。
        next_day = TrustedDrawContext(
            principal_id="user-1",
            bot_id="bot-1",
            now=datetime(2026, 9, 17, 16, 0, 1, tzinfo=UTC),
        )
        rolled = service.create_draw(_req(key="mid-3", tz="Asia/Shanghai"), next_day)
        assert len(rolled.cards) == 1


# ---------------------------------------------------------------------------
# 契约校验、门禁与错误面。
# ---------------------------------------------------------------------------


class TestContractAndGates:
    def test_draw_request_strict_validation(self) -> None:
        with pytest.raises(ValidationError):
            _req(question="问" * 501)  # question ≤500 字
        with pytest.raises(ValidationError):
            DrawRequest(
                kind="tarot",
                spread_id="single",
                question="x",
                timezone_id="Asia/Shanghai",
                workspace_id="ws-1",
                idempotency_key="k",
                unknown_field="x",  # type: ignore[call-arg]  # extra=forbid
            )
        with pytest.raises(ValidationError):
            _req(key="!!bad key!!")  # 幂等键口径与 §6 协议一致
        with pytest.raises(ValidationError):
            _req(tz="Mars/Olympus_Mons")  # 时区必须可加载
        assert _req(question="  静静  ").question == "静静"

    def test_trusted_context_requires_aware_clock(self) -> None:
        with pytest.raises(ValueError, match="带时区"):
            TrustedDrawContext(
                # naive datetime 是故意的负样本（校验器必须拒收）。
                principal_id="u",
                bot_id="b",
                now=datetime(2026, 9, 17, 12, 0),  # noqa: DTZ001
            )

    def test_feature_disabled_gate(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        keeper = _svc(store)
        existing = keeper.create_draw(_req(key="gate-0"), _ctx())
        disabled = _svc(store, enabled=False)
        for kind in ("tarot", "fortune"):
            with pytest.raises(DrawError) as excinfo:
                disabled.create_draw(
                    _req(kind, key=f"gate-{kind}"),  # type: ignore[arg-type]
                    _ctx(),
                )
            assert excinfo.value.code == "feature_disabled"
        # 门只拦创建，不拦既有结果重读。
        assert keeper.get_draw(existing.draw_id).draw_id == existing.draw_id

    def test_idempotency_key_reuse_conflict(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        service = _svc(store)
        service.create_draw(_req("fortune", key="dup-1"), _ctx())
        # 同键跨日（类别同为 fortune 但 day_key 不同）→ idempotency_conflict。
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(
                _req("fortune", key="dup-1"), _ctx(offset_seconds=86_400)
            )
        assert excinfo.value.code == "idempotency_conflict"
        # 同键跨类别 → 同码。
        with pytest.raises(DrawError) as excinfo:
            service.create_draw(_req("tarot", key="dup-1"), _ctx())
        assert excinfo.value.code == "idempotency_conflict"

    def test_get_draw_unknown_resource(self, tmp_path: Path) -> None:
        service = _svc(DrawStore(tmp_path / "draws.sqlite3"))
        with pytest.raises(DrawError) as excinfo:
            service.get_draw("draw_missing")
        assert excinfo.value.code == "resource_not_found"

    def test_draw_error_maps_to_registered_error_body(self) -> None:
        exc = DrawError("invalid_spread", "不支持的牌阵")
        body = error_body(exc.code, message=exc.message)
        assert body["code"] == "invalid_spread"
        assert body["retryable"] is False
        assert body["message"] == "不支持的牌阵"


# ---------------------------------------------------------------------------
# 并发唯一与重启（真实线程 + BEGIN IMMEDIATE 写锁）。
# ---------------------------------------------------------------------------


class TestConcurrencyAndDurability:
    def test_concurrent_same_idempotency_key_create_once(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")

        def _attempt(n: int) -> tuple[DrawRecord, bool]:
            record = DrawRecord(
                draw_id=f"draw_race_{n}",  # 每个 contender 自带不同 draw_id
                kind="tarot",
                principal_id="user-1",
                bot_id="bot-1",
                workspace_id="ws-1",
                idempotency_key="race-key",
                spread_id="single",
                cards=(
                    {"card_id": "major-00", "position_id": "", "orientation": "upright"},
                ),
                algorithm_revision=TAROT_ALGORITHM_REVISION,
                deck_revision=DECK_REVISION,
                local_day="2026-09-17",
                occurred_at=_BASE_NOW.isoformat(),
                occurred_epoch=_BASE_NOW.timestamp(),
            )
            return store.persist_draw_once(record)

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(_attempt, range(8)))
        assert sum(1 for _, flag in outcomes if flag) == 1  # 并发只建一次
        assert len({row.draw_id for row, _ in outcomes}) == 1  # 全部读回同一行
        connection = sqlite3.connect(str(store.db_path))
        try:
            count = connection.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
        finally:
            connection.close()
        assert count == 1

    def test_concurrent_fortune_same_day_single_grade(self, tmp_path: Path) -> None:
        path = tmp_path / "draws.sqlite3"

        def _create(n: int):  # type: ignore[no-untyped-def]
            return _svc(DrawStore(path)).create_draw(
                _req("fortune", key=f"par-{n}"), _ctx()
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(_create, range(6)))
        assert len({result.draw_id for result in results}) == 1
        assert len({result.fortune_grade for result in results}) == 1

    def test_restart_preserves_tarot_draw(self, tmp_path: Path) -> None:
        path = tmp_path / "draws.sqlite3"
        first = _svc(DrawStore(path)).create_draw(
            _req("tarot", spread_id="single", key="boot-1"), _ctx()
        )
        revived = _svc(DrawStore(path)).create_draw(
            _req("tarot", spread_id="single", key="boot-1"), _ctx()
        )
        assert revived.cards == first.cards
        assert revived.draw_id == first.draw_id

    def test_store_wal_mode_active(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        connection = sqlite3.connect(str(store.db_path))
        try:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# 本地解读（fortune 定性文案与免责声明；LLM 席位消费同一上下文）。
# ---------------------------------------------------------------------------


class TestLocalInterpretation:
    def test_fortune_lines_are_qualitative(self, tmp_path: Path) -> None:
        store = DrawStore(tmp_path / "draws.sqlite3")
        result = _svc(store).create_draw(_req("fortune", key="line-1"), _ctx())
        assert result.interpretation_lines[0].startswith(
            f"今日运势：{result.fortune_grade}。"
        )
        assert result.interpretation_lines[-1] == DISCLAIMER_TEXT
        # 定性文案：等级句不出现权重数字（算法说明一律定性）。
        grade_sentence = result.interpretation_lines[0].split("。")[0]
        assert not any(ch.isdigit() for ch in grade_sentence)

    def test_position_labels_cover_spreads(self) -> None:
        for spread_id, (_, positions) in SPREADS.items():
            labels = POSITION_LABELS[spread_id]
            assert set(labels) == set(positions)
