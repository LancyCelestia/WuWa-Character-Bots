"""V2.1 §2.2 score_relationship_signal 解耦回归（A4 续跑席）。

规格：docs/design/backend-v2-product-extensions.md §2.2——
「score_relationship_signal 与 classify_content_topic/review_content/
preview_route 分离；refusal/provider_error/format_error/medical_question/
quoted_abuse/product_criticism/authorized_test 默认关系 delta=0；主题路由
不自动扣分；不确定则 neutral」。

服务边界契约：score_relationship_signal(text, *, safety_category,
safety_action, reason_code) -> (behavior, reason_code)：
- 非关系 reason_code 一律零计分行为，且优先于正文启发式——引用辱骂
  「你就是个废物」带 quoted_abuse 时不得扣分（§2.4 验收「引用辱骂保持
  neutral」）；
- 未知 reason_code = 信号不确定 → neutral（reason_code=uncertain_reason_code）；
- 无 reason_code 时委托既有 classify_behavior：对人直接类别证据照罚
  （direct_abuse_evidence），refuse 且无类别证据 → refusal（W1 ① 语义原样）；
- 落库口径：零计分行为经 DynamicAffinityStore.observe 分毫不动（§2.4
  「相同 100 条路由测试/拒答不扣分」的抽样形态）。

全部离线 tmp_path + 注入时钟；不触碰生产库。
"""

from __future__ import annotations

import sqlite3

import pytest

from plugins.bot_unified_runtime.character.affinity import (
    _BEHAVIOR_DELTA,
    _NON_RELATIONSHIP_REASON_CODES,
    DynamicAffinityStore,
    score_relationship_signal,
)


class _Clock:
    """可手动推进的注入时钟（秒）。"""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


_SPEC_REASON_CODES = (
    "refusal",
    "provider_error",
    "format_error",
    "medical_question",
    "quoted_abuse",
    "product_criticism",
    "authorized_test",
)


# ---------------------------------------------------------------------------
# A. reason_code 注册面：规格 §2.2 七族，缺一不可、不多收
# ---------------------------------------------------------------------------

def test_non_relationship_reason_codes_match_spec_set() -> None:
    assert _NON_RELATIONSHIP_REASON_CODES == frozenset(_SPEC_REASON_CODES)


# ---------------------------------------------------------------------------
# B. 非关系 reason_code → 零计分行为，且优先于正文启发式
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", _SPEC_REASON_CODES)
def test_reason_code_yields_zero_delta_behavior_even_with_abuse_text(code) -> None:
    # 正文含直接辱骂词（「你就是个废物」「闭嘴」必中 insult 启发式），
    # 但上游 reason_code 表明事件与关系无关（引用辱骂/产品批评/授权测试…）：
    # 关系 delta 必须 0——内容主题与模型拒答不参与关系评价。
    behavior, returned = score_relationship_signal(
        "你就是个废物，闭嘴",
        safety_category="harassment",
        safety_action="refuse",
        reason_code=code,
    )
    assert behavior in {"neutral", "refusal"}, "非关系事件不得落 insult/negative"
    assert _BEHAVIOR_DELTA.get(behavior, 0.0) == 0.0, "关系 delta 必须 0"
    assert returned == code, "reason_code 原样透传（供上游 AffinityEvent 记账）"


def test_quoted_abuse_keeps_neutral_despite_insult_words() -> None:
    # §2.4 验收原文「引用辱骂……保持 neutral」：转述他人骂语不是对 bot 的攻击。
    behavior, returned = score_relationship_signal(
        "有人骂我傻瓜，你说气不气", reason_code="quoted_abuse"
    )
    assert behavior == "neutral"
    assert returned == "quoted_abuse"


def test_product_criticism_and_authorized_test_never_score() -> None:
    # 产品批评（对 bot 功能的差评）与授权测试身份（可信 AcceptanceRun 绑定）
    # 都不是关系负信号；「这是测试」文本本身不自行取得权限，但正常询问
    # 无论是否测试都不应被误罚（§2.2）。
    assert score_relationship_signal("你这功能真难用", reason_code="product_criticism") == (
        "neutral",
        "product_criticism",
    )
    assert score_relationship_signal("跑回归呢", reason_code="authorized_test") == (
        "neutral",
        "authorized_test",
    )


# ---------------------------------------------------------------------------
# C. 不确定一律 neutral
# ---------------------------------------------------------------------------

def test_unknown_reason_code_is_uncertain_neutral() -> None:
    behavior, returned = score_relationship_signal(
        "随便什么", safety_category="harassment", reason_code="model_hallucinated"
    )
    assert behavior == "neutral"
    assert returned == "uncertain_reason_code"


# ---------------------------------------------------------------------------
# D. 无 reason_code：委托既有 classify_behavior（W1 ① 语义原样）
# ---------------------------------------------------------------------------

def test_direct_abuse_category_evidence_still_scores() -> None:
    # 对人直接类别证据是关系负事件的唯一准入通道（§2.2「确属对人直接辱骂/
    # 反复骚扰才提交有证据的 negative 事件」）。
    assert score_relationship_signal("x", safety_category="harassment") == (
        "insult",
        "direct_abuse_evidence",
    )
    assert score_relationship_signal(
        "x", safety_category="insult_nickname", safety_action="reframe"
    ) == ("insult", "direct_abuse_evidence")


def test_refusal_action_without_reason_maps_to_refusal() -> None:
    # W1 ①：refuse 且无类别证据 → refusal（拒答≠辱骂），reason 同名可对账。
    assert score_relationship_signal(
        "讲个露骨的故事", safety_category="sexual", safety_action="refuse"
    ) == ("refusal", "refusal")


def test_topic_question_without_safety_hit_stays_neutral() -> None:
    # 主题路由不自动扣分：性健康/医疗话题正文无安全命中 → 正文启发式 neutral。
    behavior, returned = score_relationship_signal("性健康应该注意什么")
    assert behavior == "neutral"
    assert returned == "text_heuristic"


def test_intimacy_boundary_category_maps_to_tease_with_reason() -> None:
    behavior, returned = score_relationship_signal(
        "做我老婆吧", safety_category="excessive_intimacy", safety_action="reframe"
    )
    assert behavior == "tease"
    assert returned == "intimacy_boundary"


# ---------------------------------------------------------------------------
# E. 落库口径：非关系事件分毫不动（§2.4「拒答不扣分」抽样形态）
# ---------------------------------------------------------------------------

def test_non_relationship_events_leave_affinity_and_counters_untouched(tmp_path) -> None:
    clock = _Clock()
    db = tmp_path / "affinity.sqlite3"
    store = DynamicAffinityStore(db, clock=clock)
    base = store.snapshot("u1")["affinity"]
    for code in _SPEC_REASON_CODES:
        behavior, _reason = score_relationship_signal(
            "你就是个废物，闭嘴", safety_category="harassment", reason_code=code
        )
        store.observe("u1", behavior)
    assert store.snapshot("u1")["affinity"] == pytest.approx(base, abs=1e-9), (
        "全部非关系 reason_code 走完后好感分毫不动"
    )
    with sqlite3.connect(str(db)) as connection:
        row = connection.execute(
            "SELECT insult_count, negative_count FROM user_affinity WHERE sender_id = 'u1'"
        ).fetchone()
    assert tuple(row) == (0, 0), "非关系事件不得计入 insult/negative 计数"
