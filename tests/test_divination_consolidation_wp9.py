"""WP9 占卜域双实现收编的回归锁（2026-09-21，全面修复波波次 2）。

权威输入：``docs/design/divination-consolidation-20260921.md``（用户裁定 11.C
条件句的判定结果）——算法真身取 ``data/``、存储真身取 ``store/DrawStore``、异常
只留一颗 ``DrawError``。本文件把该方案的验收项逐条钉成测试：

- **唯一真身**（尺子①②）：AST 扫 ``plugins/`` 全树，``build_card_index`` /
  ``card_id_for`` / ``_compute_deck_revision`` / ``draw_tarot_cards`` /
  ``validate_spread`` / ``fortune_day_key`` 与 ``class DrawStore`` /
  ``class DrawError`` / ``class SeededPrng`` / ``class HmacPrng`` /
  ``class DrawRecord`` / ``class QuotaPolicy`` **各只剩一处定义**；三个旧入口
  （``data.draw_store`` / ``service.tarot_draw`` / ``service.fortune``）必须再导出
  同一个对象（``is`` 判定，不是等值副本）。
- **可复现性零退化**：收编前实测两套算法**数值逐字节相同**（DECK_REVISION
  ``ba6c74aeff81d862``、day_key、运势等级、seed 42 牌面三张），此处钉成黄金值；
  并锁「同一天同一人重抽不得变牌」+「seed 材料（day_key/key_id/seed_digest）与
  deck_revision/algorithm_revision 同行落库」。
- **一条记录两个视图**：聊天能力落的那一行，控制面 REST 读得到（收编前读不到：
  两张表两个库路径）。
- **幂等契约** ``(record, created)``：重抽 ``created is False``，聊天侧据此走提示。
- **配额同语义**：60s/20 次两侧同一组缺省；每日一抽不占随机配额。
- **一颗 ``DrawError``**：两条路径抛出的异常互相可捕，REST 投影层吃得下。
- **完整性门一颗**：篡改 spread_id 归 ``deck_integrity_mismatch``，不洗成 422。
- **运行数据一寸不丢**（铁律 2）：新代码不建旧表、不 DROP；给定装着
  ``daily_fortune``/``tarot_draws`` 历史行的库文件，收编后这些行原样存在，
  人数/条数/按 day_key（本地日）分组数三项守恒 + 整行字节等值。

全部离线（tmp_path SQLite、注入时钟、零网络）；绝不触碰 ``ChatBot_Runtime/``。
"""

from __future__ import annotations

import ast
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.capabilities.divination import (
    build_divination_capability,
)
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.domains.core.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.domains.divination.api.dto import DivinationDrawPayload
from plugins.bot_unified_runtime.domains.divination.api.errors import (
    project_draw_error,
)
from plugins.bot_unified_runtime.domains.divination.api.facet import (
    DivinationHttpFacade,
)
from plugins.bot_unified_runtime.domains.divination.data import deck_math, ganzhi
from plugins.bot_unified_runtime.domains.divination.data import draw_store as data_store
from plugins.bot_unified_runtime.domains.divination.data.tarot import daily_card
from plugins.bot_unified_runtime.domains.divination.service import (
    divination_service as service_mod,
)
from plugins.bot_unified_runtime.domains.divination.service import (
    fortune as fortune_mod,
)
from plugins.bot_unified_runtime.domains.divination.service import (
    tarot_draw as tarot_mod,
)
from plugins.bot_unified_runtime.domains.divination.service.divination_service import (
    DivinationService,
    TrustedDrawContext,
)
from plugins.bot_unified_runtime.domains.divination.store import draw_store as store_mod

DrawStore = store_mod.DrawStore
DrawError = store_mod.DrawError
DrawRecord = store_mod.DrawRecord
QuotaPolicy = store_mod.QuotaPolicy

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _PROJECT_ROOT / "plugins"
_DOMAIN = "bot_unified_runtime/domains/divination"

_SECRET = b"wp9-test-secret"
# 黄金值密钥：收编前实测两套算法时用的原始密钥，逐字保留以复现同一组常数。
_GOLDEN_SECRET = b"k"
# 固定时钟：2026-09-17 04:00 UTC（上海本地当日 12:00）。
_BASE_NOW = datetime(2026, 9, 17, 4, 0, tzinfo=UTC)
_LOCAL_DAY = "2026-09-17"
_LOCAL_DATE = datetime(2026, 9, 17, 4, 0, tzinfo=UTC).astimezone(ganzhi.CST).date()

# 收编前实测黄金值（两套算法数值逐字节相同 ⇒ 收编后必须仍等于这些值）。
_GOLDEN_DECK_REVISION = "ba6c74aeff81d862"
_GOLDEN_DAY_KEY = "d287377baa73331dd3ec17c2f6d4f77c"
# 聊天夹具（sender="u1"、bot_id="bot"）当天的 day_key —— 与上面黄金值同派生式。
_CHAT_DAY_KEY = deck_math.fortune_day_key("u1", "bot", _LOCAL_DAY, "v1")
_GOLDEN_FORTUNE = {
    "grade": "小吉",
    "key_id": "8254c329",
    "seed_digest": "7e6c68c50670a258",
}
_GOLDEN_SEED42_CARDS = [
    {"card_id": "major-21", "position_id": "past", "orientation": "upright"},
    {"card_id": "cups-04", "position_id": "present", "orientation": "reversed"},
    {"card_id": "pentacles-10", "position_id": "future", "orientation": "reversed"},
]


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _message(
    text: str,
    *,
    sender_id: str = "u1",
    request_id: str = "req-1",
    timestamp: datetime | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=f"private:{sender_id}",
        session_type=SessionType.PRIVATE,
        sender_id=sender_id,
        plain_text=text,
        request_id=request_id,
        timestamp=timestamp or _BASE_NOW,
    )


def _chat(
    store: DrawStore,
    *,
    secret: bytes = _SECRET,
    moment: datetime | None = None,
) -> Any:
    """聊天能力：注入唯一真身存储 + HMAC 密钥 + 固定时钟。"""
    fixed = moment or _BASE_NOW
    return build_divination_capability(
        None, draw_store=store, fortune_key=secret, clock=lambda: fixed
    )


def _rest(
    store: DrawStore, *, moment: datetime | None = None, bot_id: str | None = None
) -> DivinationHttpFacade:
    """控制面 REST 薄壳：与聊天共用同一个 DrawStore（= 同一条记录的唯一判据）。"""
    fixed = moment or _BASE_NOW
    service = DivinationService(store, secret=_SECRET, trace_factory=lambda: "trace-wp9")
    return DivinationHttpFacade(
        service,
        clock=lambda: fixed,
        fortune_ready=True,
        **({"bot_id": bot_id} if bot_id else {}),
    )


def _rest_draw(
    facade: DivinationHttpFacade,
    kind: str,
    *,
    key: str,
    principal: str = "u1",
    spread_id: str | None = None,
    workspace: str = "default",
) -> Any:
    payload = DivinationDrawPayload(
        kind=kind,  # type: ignore[arg-type]
        spread_id=spread_id,
        question="最近运势如何",
        timezone_id="Asia/Shanghai",
        workspace_id=workspace,
    )
    return facade.draw(kind, payload, principal, key)


def _tables(db_path: Path) -> set[str]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()


def _rows(db_path: Path, table: str) -> list[tuple]:
    connection = sqlite3.connect(str(db_path))
    try:
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
    finally:
        connection.close()


def _count(db_path: Path, sql: str) -> int:
    connection = sqlite3.connect(str(db_path))
    try:
        return int(connection.execute(sql).fetchone()[0])
    finally:
        connection.close()


def _legacy_census(db_path: Path) -> dict[str, Any]:
    """旧表「人数 / 条数 / 按 day_key（本地日）分组数 / 整行字节」四项快照。"""
    return {
        "fortune_people": _count(
            db_path, "SELECT COUNT(DISTINCT principal_id) FROM daily_fortune"
        ),
        "fortune_rows": _count(db_path, "SELECT COUNT(*) FROM daily_fortune"),
        "fortune_day_groups": _count(
            db_path, "SELECT COUNT(DISTINCT day_key) FROM daily_fortune"
        ),
        "fortune_bytes": _rows(db_path, "daily_fortune"),
        "tarot_people": _count(
            db_path, "SELECT COUNT(DISTINCT principal_id) FROM tarot_draws"
        ),
        "tarot_rows": _count(db_path, "SELECT COUNT(*) FROM tarot_draws"),
        "tarot_day_groups": _count(
            db_path, "SELECT COUNT(DISTINCT local_day) FROM tarot_draws"
        ),
        "tarot_bytes": _rows(db_path, "tarot_draws"),
    }


def _record(
    draw_id: str,
    *,
    kind: str = "tarot",
    cards: tuple[dict[str, str], ...] | None = None,
    spread_id: str = "single",
    dedupe_key: str = "",
    workspace: str = "chat",
    principal: str = "u1",
    moment: datetime | None = None,
) -> DrawRecord:
    when = moment or _BASE_NOW
    return DrawRecord(
        draw_id=draw_id,
        kind=kind,
        principal_id=principal,
        bot_id="bot",
        workspace_id=workspace,
        idempotency_key=draw_id,
        dedupe_key=dedupe_key,
        spread_id=spread_id,
        cards=cards
        if cards is not None
        else (
            {
                "card_id": "major-00",
                "position_id": "",
                "orientation": "upright",
            },
        ),
        algorithm_revision=deck_math.TAROT_ALGORITHM_REVISION,
        deck_revision=deck_math.DECK_REVISION,
        local_day=_LOCAL_DAY,
        occurred_at=when.isoformat(),
        occurred_epoch=when.timestamp(),
    )


def _single_card(card_id: str = "major-00") -> tuple[dict[str, str], ...]:
    return (
        {"card_id": card_id, "position_id": "", "orientation": "upright"},
    )


# ---------------------------------------------------------------------------
# 1. 唯一真身（尺子①②：一个事实一份定义）
# ---------------------------------------------------------------------------


def _definition_sites(symbol: str, *, kind: str) -> list[str]:
    """AST 扫 ``plugins/`` 全树，返回 ``symbol`` 的定义位置（相对路径::行号）。"""
    hits: list[str] = []
    for path in sorted(_PLUGIN_ROOT.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if symbol not in source:  # 预筛：只有含该字面量的文件才值得解析
            continue
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if getattr(node, "name", None) != symbol:
                continue
            is_def = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            is_class = isinstance(node, ast.ClassDef)
            if (kind == "def" and is_def) or (kind == "class" and is_class):
                hits.append(
                    f"{path.relative_to(_PROJECT_ROOT).as_posix()}::{node.lineno}"
                )
    return hits


@pytest.mark.parametrize(
    ("symbol", "kind"),
    [
        ("build_card_index", "def"),
        ("card_id_for", "def"),
        ("_compute_deck_revision", "def"),
        ("draw_tarot_cards", "def"),
        ("validate_spread", "def"),
        ("fortune_day_key", "def"),
        ("rejection_sample_below", "def"),
        ("derive_fortune_seed", "def"),
        ("draw_fortune_grade", "def"),
        ("validated_tarot_cards", "def"),
        ("DrawStore", "class"),
        ("DrawError", "class"),
        ("SeededPrng", "class"),
        ("HmacPrng", "class"),
        ("SystemPrng", "class"),
        ("DrawRecord", "class"),
        ("QuotaPolicy", "class"),
    ],
)
def test_every_shared_fact_has_exactly_one_definition(symbol: str, kind: str) -> None:
    sites = _definition_sites(symbol, kind=kind)
    assert len(sites) == 1, f"{symbol} 必须只有一处定义，实际 {sites}"


def test_algorithm_truth_lives_in_deck_math() -> None:
    for symbol in (
        "build_card_index",
        "card_id_for",
        "_compute_deck_revision",
        "draw_tarot_cards",
        "validate_spread",
        "fortune_day_key",
        "validated_tarot_cards",
    ):
        sites = _definition_sites(symbol, kind="def")
        assert sites, symbol
        assert f"{_DOMAIN}/data/deck_math.py::" in sites[0], (symbol, sites)


def test_storage_and_error_truth_live_in_store() -> None:
    assert f"{_DOMAIN}/store/draw_store.py::" in _definition_sites(
        "DrawStore", kind="class"
    )[0]
    assert f"{_DOMAIN}/store/draw_store.py::" in _definition_sites(
        "DrawError", kind="class"
    )[0]


def test_old_entrypoints_reexport_the_same_objects() -> None:
    """三个旧入口必须是再导出垫片（同一对象），而不是第二份实现。"""
    assert tarot_mod.build_card_index is deck_math.build_card_index
    assert tarot_mod.card_id_for is deck_math.card_id_for
    assert tarot_mod.validate_spread is deck_math.validate_spread
    assert tarot_mod.draw_tarot_cards is deck_math.draw_tarot_cards
    assert tarot_mod.SPREADS is deck_math.SPREADS
    assert tarot_mod.POSITION_LABELS is deck_math.POSITION_LABELS
    assert fortune_mod.fortune_day_key is deck_math.fortune_day_key
    assert fortune_mod.SeededPrng is deck_math.SeededPrng
    assert fortune_mod.HmacPrng is deck_math.HmacPrng
    assert fortune_mod.SystemPrng is deck_math.SystemPrng
    assert fortune_mod.derive_fortune_seed is deck_math.derive_fortune_seed
    assert fortune_mod.draw_fortune_grade is deck_math.draw_fortune_grade
    assert fortune_mod.rejection_sample_below is deck_math.rejection_sample_below
    assert fortune_mod.FORTUNE_GRADES_V1 is deck_math.FORTUNE_GRADES_V1
    assert data_store.build_card_index is deck_math.build_card_index
    assert data_store.card_id_for is deck_math.card_id_for
    assert data_store.validate_spread is deck_math.validate_spread
    assert data_store.daily_fortune_day_key is deck_math.fortune_day_key
    assert data_store.SeededPrng is deck_math.SeededPrng
    assert data_store.HmacPrng is deck_math.HmacPrng
    assert data_store.DrawStore is store_mod.DrawStore
    assert data_store.DrawError is store_mod.DrawError


def test_deck_revision_constant_shared_and_golden() -> None:
    assert len({deck_math.DECK_REVISION, data_store.DECK_REVISION, tarot_mod.DECK_REVISION}) == 1
    assert deck_math.DECK_REVISION == _GOLDEN_DECK_REVISION


def test_chat_side_no_longer_defines_its_own_revisions() -> None:
    """配额与算法版本号的字面量不得在能力层留第二份副本（必须引真身）。"""
    from plugins.bot_unified_runtime.domains.divination.capabilities import (
        divination as capability_mod,
    )

    assert capability_mod._TAROT_COOLDOWN_SECONDS == store_mod.DEFAULT_TAROT_COOLDOWN_SECONDS
    assert capability_mod._TAROT_DAILY_LIMIT == store_mod.DEFAULT_TAROT_DAILY_LIMIT
    assert capability_mod._TAROT_ALGO_REVISION == deck_math.TAROT_ALGORITHM_REVISION
    assert (
        capability_mod._TAROT_DAILY_ALGO_REVISION
        == deck_math.TAROT_DAILY_ALGORITHM_REVISION
    )
    assert capability_mod._FORTUNE_ALGO_REVISION == deck_math.FORTUNE_ALGORITHM_REVISION


# ---------------------------------------------------------------------------
# 2. 可复现性零退化
# ---------------------------------------------------------------------------


def test_day_key_two_names_same_golden_value() -> None:
    assert deck_math.fortune_day_key("u", "b", _LOCAL_DAY, "v1") == _GOLDEN_DAY_KEY
    assert data_store.daily_fortune_day_key("u", "b", _LOCAL_DAY, "v1") == _GOLDEN_DAY_KEY


def test_fortune_two_entrypoints_agree_with_golden() -> None:
    outcome = data_store.draw_daily_fortune(
        _GOLDEN_SECRET, "u", "b", _LOCAL_DAY, "v1"
    )
    assert outcome.grade == _GOLDEN_FORTUNE["grade"]
    assert outcome.key_id == _GOLDEN_FORTUNE["key_id"]
    assert outcome.seed_digest == _GOLDEN_FORTUNE["seed_digest"]
    seed = deck_math.derive_fortune_seed(_GOLDEN_SECRET, "u", "b", _LOCAL_DAY)
    assert deck_math.draw_fortune_grade(seed.prng) == outcome.grade
    assert (seed.key_id, seed.seed_digest) == (outcome.key_id, outcome.seed_digest)
    assert seed.day_key == _GOLDEN_DAY_KEY


def test_tarot_two_entrypoints_agree_with_golden() -> None:
    canonical = deck_math.draw_tarot_cards(
        "past_present_future", deck_math.SeededPrng(42)
    )
    assert list(canonical) == _GOLDEN_SEED42_CARDS
    legacy = data_store.draw_tarot("past_present_future", data_store.SeededPrng(42))
    assert legacy == _GOLDEN_SEED42_CARDS  # 兼容名单保持 list 形态、值不变
    assert isinstance(legacy, list)
    assert tarot_mod.draw_tarot_cards("past_present_future", fortune_mod.SeededPrng(42)) == (
        canonical
    )


def test_seed_material_and_revisions_land_in_one_row(tmp_path: Path) -> None:
    """seed 材料（day_key+key_id+seed_digest）与两个 revision 必须同一行齐全。"""
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    _chat(store)(_message("今日运势"), None)
    record = store.find_by_dedupe("fortune", _CHAT_DAY_KEY)
    assert record is not None
    assert record.dedupe_key == _CHAT_DAY_KEY
    assert len(record.key_id) == 8 and len(record.seed_digest) == 16
    assert record.algorithm_revision == deck_math.FORTUNE_ALGORITHM_REVISION
    assert record.local_day == _LOCAL_DAY
    _chat(store)(_message("今日运势", request_id="req-2"), None)
    again = store.find_by_dedupe("fortune", _CHAT_DAY_KEY)
    assert again is not None
    assert (
        again.draw_id,
        again.fortune_grade,
        again.key_id,
        again.seed_digest,
    ) == (record.draw_id, record.fortune_grade, record.key_id, record.seed_digest)


def test_same_day_same_person_redraw_same_cards_created_false(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    capability = _chat(store)
    first = capability(_message("塔罗 每日一抽", request_id="req-a"), None)
    assert "divination:replay" not in first.audit_tags
    second = capability(_message("塔罗 每日一抽", request_id="req-b"), None)
    assert second.body == first.body  # 同一天同一人不得变牌
    assert "divination:replay" in second.audit_tags  # created=False 必须走到提示口径
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='tarot'") == 1


# ---------------------------------------------------------------------------
# 3. 一颗 DrawError
# ---------------------------------------------------------------------------


def test_only_one_error_class_object_in_domain() -> None:
    assert data_store.DrawError is store_mod.DrawError
    assert tarot_mod.DrawError is store_mod.DrawError
    assert service_mod.DrawError is store_mod.DrawError


def test_algorithm_side_raise_caught_by_store_name() -> None:
    with pytest.raises(store_mod.DrawError) as excinfo:
        data_store.validate_spread("not_a_spread")
    assert excinfo.value.code == "invalid_spread"
    assert project_draw_error(excinfo.value).status_code == 422


def test_quota_raise_caught_by_chat_side_name(tmp_path: Path) -> None:
    store = DrawStore(tmp_path / "draws.sqlite3")
    store.persist_draw_once(_record("draw_wp9_q1", cards=_single_card()))
    with pytest.raises(data_store.DrawError) as excinfo:
        store.persist_draw_once(
            _record("draw_wp9_q2", cards=_single_card("major-01")), quota=QuotaPolicy()
        )
    assert excinfo.value.code == "rate_limited"
    # 同一条异常喂 REST 投影层不得炸（旧 data 侧 DrawError 无 .message 会 AttributeError）。
    projection = project_draw_error(excinfo.value)
    assert projection.status_code == 429
    assert projection.code == "rate_limited"


# ---------------------------------------------------------------------------
# 4. 一条记录、两个视图
# ---------------------------------------------------------------------------


def test_chat_tarot_row_visible_to_rest(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    body = _chat(store)(_message("塔罗 每日一抽"), None).body
    via_rest = _rest(store).get_draw(f"tarot-daily:bot:u1:{_LOCAL_DAY}")
    assert via_rest.draw_id == f"tarot-daily:bot:u1:{_LOCAL_DAY}"
    assert via_rest.kind == "tarot"
    index = deck_math.build_card_index()
    card = index[via_rest.cards[0]["card_id"]]
    assert via_rest.deck_revision == _GOLDEN_DECK_REVISION
    assert via_rest.algorithm_revision == deck_math.TAROT_DAILY_ALGORITHM_REVISION
    assert card.name in body  # 聊天正文与 REST 投影同一行、同一张牌
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='tarot'") == 1


def test_chat_random_tarot_visible_to_rest(tmp_path: Path) -> None:
    store = DrawStore(tmp_path / "draws.sqlite3")
    _chat(store)(_message("塔罗 三张", request_id="rq-3"), None)
    record = store.find_by_idempotency_key("tarot:rq-3")
    assert record is not None
    assert record.algorithm_revision == deck_math.TAROT_ALGORITHM_REVISION
    assert len(record.cards) == 3
    via_rest = _rest(store).get_draw(record.draw_id)
    assert via_rest.cards == tuple(dict(card) for card in record.cards)


def test_chat_fortune_row_visible_to_rest(tmp_path: Path) -> None:
    store = DrawStore(tmp_path / "draws.sqlite3")
    _chat(store)(_message("今日运势"), None)
    record = store.find_by_dedupe("fortune", _CHAT_DAY_KEY)
    assert record is not None
    via_rest = _rest(store).get_draw(record.draw_id)
    assert via_rest.fortune_grade == record.fortune_grade


def test_rest_written_row_visible_to_chat_read_face(tmp_path: Path) -> None:
    store = DrawStore(tmp_path / "draws.sqlite3")
    made = _rest_draw(_rest(store), "tarot", key="wp9-rest-1", spread_id="single")
    assert store.find_by_idempotency_key("wp9-rest-1") is not None
    assert _rest(store).get_draw(made.draw_id).cards == made.cards
    # 同一幂等键再抽一次：命中既有行、不新建（两侧同一幂等语义）。
    again = _rest_draw(_rest(store), "tarot", key="wp9-rest-1", spread_id="single")
    assert again.draw_id == made.draw_id


def test_legacy_tables_are_not_created_by_new_code(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    _chat(store)(_message("塔罗 每日一抽"), None)
    _chat(store)(_message("今日运势"), None)
    tables = _tables(path)
    assert "draws" in tables
    assert "daily_fortune" not in tables
    assert "tarot_draws" not in tables


# ---------------------------------------------------------------------------
# 5. 配额两侧同语义
# ---------------------------------------------------------------------------


def test_chat_tarot_cooldown_then_rest_same_verdict(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    first = _chat(store)(_message("塔罗", request_id="rq-1"), None)
    assert "divination:persisted" in first.audit_tags
    second = _chat(store)(_message("塔罗", request_id="rq-2"), None)
    assert "divination:rate_limited" in second.audit_tags  # 收编前聊天侧根本没有配额
    # 同一配额池（principal+bot+workspace 三项与聊天侧同形）的 REST 抽取必须给出
    # 同一条拒绝 ⇒ 配额语义两侧同一颗判据、同一组缺省值。
    with pytest.raises(DrawError) as excinfo:
        _rest_draw(
            _rest(store, bot_id="bot"),
            "tarot",
            key="wp9-rest-quota",
            spread_id="single",
            workspace="chat",
        )
    assert excinfo.value.code == "rate_limited"
    # REST 面默认 bot_id=control_plane，与聊天面天然分池（这是收编前就在册的设计
    # 语义，收编只统一判据、不改分池）。
    other = _rest_draw(
        _rest(store), "tarot", key="wp9-rest-pool", spread_id="single"
    )
    assert len(other.cards) == 1
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='tarot'") == 2


def test_chat_daily_draw_does_not_consume_random_quota(tmp_path: Path) -> None:
    """每日一抽是幂等重读类（dedupe_key 非空），不吃随机抽取的计数与冷却。"""
    store = DrawStore(tmp_path / "draws.sqlite3")
    _chat(store)(_message("塔罗 每日一抽", request_id="d-1"), None)
    result = _chat(store)(_message("塔罗", request_id="r-1"), None)
    assert "divination:persisted" in result.audit_tags
    assert "divination:rate_limited" not in result.audit_tags


def test_chat_random_draws_capped_by_daily_limit(tmp_path: Path) -> None:
    """配额上限两侧同一个数：聊天侧抽满 20 次后第 21 次必拒。

    冷却缺省 60s ⇒ 每次抽取间隔 61 秒（不新增配置键，只用注入时钟），
    20 次共约 21 分钟，仍落在同一个本地日内。
    """
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    for n in range(20):
        moment = _BASE_NOW + timedelta(seconds=61 * n)
        outcome = _chat(store, moment=moment)(
            _message("塔罗", request_id=f"cap-{n}"), None
        )
        assert "divination:persisted" in outcome.audit_tags, n
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='tarot'") == 20
    blocked = _chat(store, moment=_BASE_NOW + timedelta(seconds=61 * 20))(
        _message("塔罗", request_id="cap-20"), None
    )
    assert "divination:rate_limited" in blocked.audit_tags
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='tarot'") == 20


# ---------------------------------------------------------------------------
# 6. 幂等契约 (record, created)
# ---------------------------------------------------------------------------


def test_persist_returns_created_flag(tmp_path: Path) -> None:
    store = DrawStore(tmp_path / "draws.sqlite3")
    record = _record("draw_wp9_flag")
    stored, created = store.persist_draw_once(record)
    assert created is True
    again, created_again = store.persist_draw_once(stored)
    assert created_again is False
    assert again.draw_id == record.draw_id


def test_chat_random_retry_same_request_id_marks_replay(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    capability = _chat(store)
    first = capability(_message("塔罗", request_id="same-req"), None)
    second = capability(_message("塔罗", request_id="same-req"), None)
    assert second.body == first.body
    assert "divination:replay" in second.audit_tags
    assert _count(path, "SELECT COUNT(*) FROM draws") == 1


# ---------------------------------------------------------------------------
# 7. 完整性门一颗（两侧共用）
# ---------------------------------------------------------------------------


def test_tamper_rejected_identically_from_both_sides(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    _rest_draw(_rest(store), "tarot", key="wp9-tamper", spread_id="past_present_future")
    draw_id = store.find_by_idempotency_key("wp9-tamper").draw_id
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            "UPDATE draws SET cards_json = ? WHERE draw_id = ?",
            (
                '[{"card_id":"major-99","orientation":"upright","position_id":"past"}]',
                draw_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    record = store.get_draw(draw_id)
    with pytest.raises(DrawError) as first:
        service_mod.build_interpretation_context(record)
    assert first.value.code == "deck_integrity_mismatch"
    with pytest.raises(data_store.DrawError) as second:
        data_store.rebuild_drawn_cards(record)
    assert second.value.code == "deck_integrity_mismatch"


def test_tampered_spread_reports_integrity_not_validation(tmp_path: Path) -> None:
    """持久行的 spread_id 被改 = 篡改，归 deck_integrity_mismatch（不得洗成 422）。"""
    store = DrawStore(tmp_path / "draws.sqlite3")
    store.persist_draw_once(_record("draw_wp9_spread", spread_id="bogus"))
    with pytest.raises(DrawError) as excinfo:
        service_mod.build_interpretation_context(store.get_draw("draw_wp9_spread"))
    assert excinfo.value.code == "deck_integrity_mismatch"


# ---------------------------------------------------------------------------
# 8. 运行数据守恒（铁律 2）
# ---------------------------------------------------------------------------


def _seed_legacy_db(path: Path) -> None:
    """按收编前两套表形态灌入历史行，模拟「用户曾经抽过牌」的库文件。"""
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(
            """
            CREATE TABLE daily_fortune (
                day_key TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
                bot_id TEXT NOT NULL, local_date TEXT NOT NULL,
                rule_version TEXT NOT NULL, grade TEXT NOT NULL,
                key_id TEXT NOT NULL, seed_digest TEXT NOT NULL,
                occurred_at TEXT NOT NULL);
            CREATE TABLE tarot_draws (
                draw_id TEXT PRIMARY KEY, principal_id TEXT NOT NULL,
                bot_id TEXT NOT NULL, spread_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'random', cards_json TEXT NOT NULL,
                expected_count INTEGER NOT NULL, algorithm_revision TEXT NOT NULL,
                deck_revision TEXT NOT NULL, occurred_at TEXT NOT NULL,
                local_day TEXT NOT NULL);
            """
        )
        history = [("alice", "2026-09-15", "大吉"), ("bob", "2026-09-16", "平"),
                   ("alice", "2026-09-16", "小吉")]
        for n, (sender, day, grade) in enumerate(history):
            connection.execute(
                "INSERT INTO daily_fortune VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    deck_math.fortune_day_key(sender, "bot", day, "v1"),
                    sender, "bot", day, "v1", grade,
                    "8254c329", "7e6c68c50670a258", _BASE_NOW.isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO tarot_draws VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"tarot:{sender}:{day}",
                    sender,
                    "bot",
                    "single",
                    "daily",
                    (
                        f'[{{"card_id":"major-0n_{n}","position_id":"",'
                        f'"orientation":"upright"}}]'
                    ),
                    1,
                    "tarot-daily-v1",
                    _GOLDEN_DECK_REVISION,
                    _BASE_NOW.isoformat(),
                    day,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def test_legacy_history_survives_consolidation(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    _seed_legacy_db(path)
    before = _legacy_census(path)
    assert before["fortune_rows"] == 3 and before["tarot_rows"] == 3

    store = DrawStore(path)
    _chat(store)(_message("今日运势", sender_id="carol"), None)
    _rest_draw(_rest(store), "tarot", key="wp9-post", principal="dave", spread_id="single")

    after = _legacy_census(path)
    for key in (
        "fortune_people", "fortune_rows", "fortune_day_groups",
        "tarot_people", "tarot_rows", "tarot_day_groups",
    ):
        assert after[key] == before[key], key
    assert after["fortune_bytes"] == before["fortune_bytes"]
    assert after["tarot_bytes"] == before["tarot_bytes"]
    assert _count(path, "SELECT COUNT(*) FROM draws") == 2  # 新真身照常写入


def test_data_draw_store_no_longer_opens_a_database() -> None:
    """聊天侧不得再有第二个「开库建表」的地方（数据面单一真身的结构锁）。"""
    source = (_PLUGIN_ROOT / f"{_DOMAIN}/data/draw_store.py").read_text(encoding="utf-8")
    assert "import sqlite3" not in source
    assert "sqlite3.connect" not in source
    assert "CREATE TABLE" not in source


# ---------------------------------------------------------------------------
# 9. 既有行为面不得因收编而漂移
# ---------------------------------------------------------------------------


def test_capability_without_store_keeps_legacy_behaviour(tmp_path: Path) -> None:
    capability = build_divination_capability(None)
    result = capability(_message("塔罗"), None)
    assert "（正位）" in result.body or "（逆位）" in result.body
    fortune = capability(_message("今日运势"), None)
    assert "divination:fortune_disabled" in fortune.audit_tags
    # 未注入存储 ⇒ 一个库文件都不许被创建（绝不猜默认路径写源码树）。
    assert list(tmp_path.iterdir()) == []


def test_chat_daily_card_matches_pure_daily_hash(tmp_path: Path) -> None:
    """持久路径的每日一抽必须与非持久路径同牌（算法面未被收编改动）。"""
    plain = build_divination_capability(None)(
        _message("塔罗 每日一抽", timestamp=_BASE_NOW), None
    )
    drawn = daily_card(_LOCAL_DATE, "u1")
    assert drawn.card.name in plain.body
    store = DrawStore(tmp_path / "draws.sqlite3")
    persisted = _chat(store)(_message("塔罗 每日一抽", timestamp=_BASE_NOW), None)
    assert drawn.card.name in persisted.body
    assert drawn.card.name in _rest(store).get_draw(
        f"tarot-daily:bot:u1:{_LOCAL_DAY}"
    ).interpretation_lines[0]


def test_rule_version_recoverable_from_canonical_row(tmp_path: Path) -> None:
    """rule_version 是 day_key 的派生输入，收编后仍须能从行上复原。"""
    store = DrawStore(tmp_path / "draws.sqlite3")
    _chat(store)(_message("今日运势"), None)
    record = store.find_by_dedupe("fortune", _CHAT_DAY_KEY)
    assert record is not None
    assert record.algorithm_revision == (
        f"fortune-rules-{deck_math.FORTUNE_RULE_VERSION}"
    )
    assert (
        deck_math.fortune_rule_version_of(record.algorithm_revision)
        == deck_math.FORTUNE_RULE_VERSION
    )


def test_next_local_day_creates_a_new_row(tmp_path: Path) -> None:
    path = tmp_path / "draws.sqlite3"
    store = DrawStore(path)
    _chat(store)(_message("今日运势"), None)
    _chat(store, moment=_BASE_NOW + timedelta(days=1))(
        _message("今日运势", request_id="req-tomorrow"), None
    )
    assert _count(path, "SELECT COUNT(*) FROM draws WHERE kind='fortune'") == 2
    assert _count(path, "SELECT COUNT(DISTINCT local_day) FROM draws") == 2


def test_service_read_face_still_uses_trusted_context(tmp_path: Path) -> None:
    """收编不动 REST 服务半边语义：可信上下文缺时区仍拒。"""
    with pytest.raises(ValueError, match="带时区"):
        TrustedDrawContext(principal_id="u", bot_id="b", now=datetime(2026, 9, 17, 12, 0))  # noqa: DTZ001
