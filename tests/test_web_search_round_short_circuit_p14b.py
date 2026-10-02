"""P14b：本轮（批内）空手短路的**接线**锁——判据在 `web_search.py`「本轮短路」段，本件只钉腿。

病根：检索腿把同一枚问题铺成至多 7 条装饰变体、4 worker 并发打**同一枚**链实例
（`chat.py:_search_queries_concurrently`），链每收一条查询都从头走一遍 provider 表、
没有任何早停。前任席把判据（`_RequestRound` / `_RoundScope` / `_question_base_key` /
`_ROUND_MAX_KEYS`）写进了盘却没接消费者＝「declared not enforced」，今天零行为变化。

四腿口径：
* 腿 1：同基形两变体并发（第一变体在飞、批未收兵）⇒ 第二变体不再问已空手那家；
  腿 1b：抛异常那家同样记空、同样被跳过（判据写的是「原始 0 条**或**抛异常」）。
* 腿 2（反证）：被 `gate_chain_hits` 判无关丢掉的那批**不记空** ⇒ 同批第二变体照问。
* 腿 3：两枚不同问题同时在飞 ⇒ 各记各账，互不污染（若把账记成全局「第 0 家空过手」，
  本腿必红）。
* 腿 4：批收兵（链上在飞遍历数归零）⇒ 整本作废，新批照问——证明它不是第二份跨请求
  熔断/冷却（`_note_ddg_challenge` 600s 冷却与 `_CACHE_TTL_SECONDS` 600s TTL 一字未动）。
* 腿 5：并发压一遍（2 问题 × 变体），断言不炸锁、结果不丢、账本基形数不越界。

注毒自证（判据非空转）：把 `_round_is_empty` 的跳过判据改恒 False（＝摘掉接线）⇒ 腿 1
与腿 1b 必红；接回 ⇒ 全绿。

全离线：provider 面全是进程内 stub，零真实网络；不动超时/重试/预算/上限数值，不加配置键。
"""

from __future__ import annotations

import threading

from plugins.bot_unified_runtime.domains.core.search.web_search import (
    ChainedWebSearchProvider,
    WebSearchHit,
    _question_base_key,
)

# 同一枚问题的三条检索变体（尾部装饰逐条不同、问题基形同一枚）。
_V1 = "美联储 利率 决议 最新 消息"
_V2 = "美联储 利率 决议 官方 发布 公告"
_V3 = "美联储 利率 决议 2026 来源 数据"
# 另一枚问题（基形必须与上面三条不相交）。
_O1 = "黄金 价格 走势 分析 最新"
_O2 = "黄金 价格 走势 分析 数据"


class _StubProvider:
    """进程内 provider 替身：记被问次数，返回形态由子类决定。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0
        self._lock = threading.Lock()

    def _tick(self) -> int:
        with self._lock:
            self.calls += 1
            return self.calls

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:  # pragma: no cover
        raise NotImplementedError


class _EmptyProvider(_StubProvider):
    """原始返回 0 条（＝判据里的「空过手」）。"""

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        self._tick()
        return []


class _BoomProvider(_StubProvider):
    """抛异常（＝判据里的第二种「空过手」形态）。"""

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        self._tick()
        raise RuntimeError("stub engine dead")


class _GatedAwayProvider(_StubProvider):
    """原始**非空**、但内容与查询毫无关系 ⇒ 整批被 `gate_chain_hits` 丢掉。"""

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        self._tick()
        return [
            WebSearchHit(
                title="Zebra Granite Podcast",
                snippet="zebra granite podcast episode nine summary notes",
                url="https://zebra.invalid/gp",
            )
        ]


class _HoldingRelevantProvider(_StubProvider):
    """过闸非空的命中；**首枚**可按住（把这一批保持在飞），好让并发次序可判定。"""

    def __init__(self, name: str = "relevant") -> None:
        super().__init__(name)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_first = True

    def search(self, query: str, *, max_results: int = 3) -> list[WebSearchHit]:
        n = self._tick()
        if self.block_first and n == 1:
            self.entered.set()
            assert self.release.wait(timeout=5.0), "stub provider 未被释放"
        return [
            WebSearchHit(
                title=query,
                snippet=f"{query} 的详细报道，含实体说明与出处。",
                url="https://example.invalid/a",
            )
        ]


def _start_batch_with_one_traversal(
    chain: ChainedWebSearchProvider, good: _HoldingRelevantProvider
) -> threading.Thread:
    """起一条在飞遍历（走 `_V1`，第二家会按住），于是「本轮」开着。

    返回时调用方已确认：第一家在这条遍历里被问过了（空手已记账），且批未收兵。
    """
    thread = threading.Thread(target=lambda: chain.search(_V1, max_results=3))
    thread.start()
    assert good.entered.wait(timeout=5.0), "在飞遍历没有走到第二家"
    return thread


def test_base_key_collapses_variants_and_separates_questions():
    """地基：三条变体塌缩到同一枚非空基形，另一枚问题不相交（短路靠它认「同一轮」）。"""
    key1, key2, key3 = (_question_base_key(q) for q in (_V1, _V2, _V3))
    assert key1 and key1 == key2 == key3, (key1, key2, key3)
    assert _question_base_key(_O1) not in ("", key1)
    # 整句都是装饰 ⇒ 空基形＝这一遍不记账也不短路（fail-open）。
    assert _question_base_key("最新 消息 官方 公告 2026") == ""


def test_leg1_same_base_key_second_variant_skips_the_empty_provider():
    """腿 1：同基形第二变体不再问已空手那家（provider 表顺序不动，只是跳过）。"""
    empty, good = _EmptyProvider("empty"), _HoldingRelevantProvider()
    chain = ChainedWebSearchProvider([empty, good])

    thread = _start_batch_with_one_traversal(chain, good)
    assert (empty.calls, good.calls) == (1, 1)

    assert chain.search(_V2, max_results=3)  # 同基形、同批
    assert empty.calls == 1, "同基形第二变体仍问了已空手那家＝接线没牙"
    assert good.calls == 2

    good.release.set()
    thread.join(timeout=5.0)
    assert not thread.is_alive()


def test_leg1b_provider_that_raises_is_also_recorded_empty():
    """腿 1b：抛异常那家同样记空、同批第二变体同样跳过（判据写的是「0 条或抛异常」）。"""
    boom, good = _BoomProvider("boom"), _HoldingRelevantProvider()
    chain = ChainedWebSearchProvider([boom, good])

    thread = _start_batch_with_one_traversal(chain, good)
    assert (boom.calls, good.calls) == (1, 1)

    assert chain.search(_V2, max_results=3)
    assert boom.calls == 1, "抛异常那家没被记账＝异常分支的接线断了"
    assert good.calls == 2

    good.release.set()
    thread.join(timeout=5.0)


def test_leg2_gated_away_empty_is_not_recorded():
    """腿 2（反证）：被相关性闸门丢掉的非空返回**不记空** ⇒ 同批下一变体照问。

    空的是这条查询不是这家——记了空就是把好引擎当死引擎熔断。
    """
    noisy, good = _GatedAwayProvider("noisy"), _HoldingRelevantProvider()
    chain = ChainedWebSearchProvider([noisy, good])

    thread = _start_batch_with_one_traversal(chain, good)
    assert noisy.calls == 1
    base_key = _question_base_key(_V1)
    ledger = chain._round_bucket.empty_by_key
    assert base_key not in ledger or 0 not in ledger[base_key], ledger

    assert chain.search(_V2, max_results=3)
    assert noisy.calls == 2, "闸门判无关的那批被记成空手＝记错了对象"
    assert good.calls == 2

    good.release.set()
    thread.join(timeout=5.0)


def test_leg3_two_questions_in_flight_keep_separate_books():
    """腿 3：两枚不同问题同时在飞 ⇒ 各记各账。第二家按着第一问，令批保持重叠。"""
    empty, good = _EmptyProvider("empty"), _HoldingRelevantProvider()
    chain = ChainedWebSearchProvider([empty, good])

    thread = _start_batch_with_one_traversal(chain, good)
    assert empty.calls == 1, "第一问已把 `_V1` 的空手记进账本"

    # 另一枚问题（不同基形）在同一批里遍历：绝不能沾第一问的账。
    assert chain.search(_O1, max_results=3)
    assert empty.calls == 2, "不同基形共享了同一本账＝并发互相污染"

    good.release.set()
    thread.join(timeout=5.0)


def test_leg4_batch_end_voids_the_book_and_is_not_a_breaker():
    """腿 4：批收兵＝整本作废，新批照问（证明这不是第二份跨请求冷却/熔断）。"""
    empty, good = _EmptyProvider("empty"), _HoldingRelevantProvider()
    chain = ChainedWebSearchProvider([empty, good])

    thread = _start_batch_with_one_traversal(chain, good)
    assert chain.search(_V2, max_results=3)
    assert empty.calls == 1  # 同批：跳过
    good.release.set()
    thread.join(timeout=5.0)

    # 链上再无在飞遍历 ⇒ 上一批收兵。第三变体（新串，TTL 缓存不参与）必须重新问。
    good.block_first = False
    assert chain.search(_V3, max_results=3)
    assert empty.calls == 2, "批收兵后账还在＝长出了第二份跨请求熔断"


def test_leg5_concurrent_multi_question_run_survives_the_lock():
    """腿 5：2 问题 × 各 3 变体真并发打同一枚链实例——不炸锁、每条都拿到结果。"""
    empty = _EmptyProvider("empty")
    fast = _HoldingRelevantProvider("fast")
    fast.block_first = False
    chain = ChainedWebSearchProvider([empty, fast])
    queries = [_V1, _V2, _V3, _O1, _O2, _O1]
    results: list[list[WebSearchHit]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(len(queries))

    def _run(query: str) -> None:
        barrier.wait(timeout=5.0)
        hits = chain.search(query, max_results=3)
        with results_lock:
            results.append(hits)

    threads = [threading.Thread(target=_run, args=(q,)) for q in queries]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)
        assert not t.is_alive(), "并发遍历卡死"

    assert len(results) == len(queries)
    assert all(results)
    assert empty.calls >= 1
    # 批已收兵：账本里不许留跨批状态（基形数也不越 `_ROUND_MAX_KEYS`）。
    assert len(chain._round_bucket.empty_by_key) == 0
