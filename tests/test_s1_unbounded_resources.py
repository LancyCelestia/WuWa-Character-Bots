"""S1 无界资源收口（P5.8）功能回归：两处有界淘汰的实跑证据。

配对机械门 `test_s1_unbounded_containers_gate.py`（静态扫指定面）之外，本文件
证明两枚容器的**运行时淘汰语义真的成立**（不是只改了个数字）：

① `providers._HTTP_CLIENTS` —— 进程级 httpx.Client 连接桶，超出上界按 LRU
   关最旧、且绝不关「本次在用的那枚」。
② `vector_knowledge._QUERY_EMBED_MEMO` —— 单文本查询嵌入 memo，键含任意用户
   query（无界键空间），溢出逐条踢最久未用、命中挪队尾；旧腿是 `.clear()` 一把
   全清（热键连带被丢、集体回源重嵌）。本文件断言旧腿不回潮。

全部离线、纯内存：不建真实连接、不碰生产 store（这两枚都是进程内容器）。
判据纪律＝双向自测：溢出必须淘汰（注毒向）+ 未溢出/在用键绝不误伤（反向）。
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge as vk
import plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers as providers_module
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    _enforce_http_client_bound,
)


class _FakeClient:
    """只带 `is_closed` / `close()` 的假连接桶客户端（不开真 socket）。"""

    def __init__(self) -> None:
        self.is_closed = False
        self.closed_count = 0

    def close(self) -> None:
        self.closed_count += 1
        self.is_closed = True


# ------------------------------------------------------------------ ① 连接桶上界


def test_http_client_buckets_bounded_and_lru(monkeypatch: pytest.MonkeyPatch) -> None:
    pool: OrderedDict[str, _FakeClient] = OrderedDict()
    for index in range(3):
        pool[f"proxy-{index}"] = _FakeClient()
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS", pool)
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS_MAX_BUCKETS", 3)

    # 新增一枚并挪到队尾 ⇒ 共 4 桶超上界 3，只应关掉最旧的 proxy-0。
    pool["proxy-new"] = _FakeClient()
    pool.move_to_end("proxy-new", last=True)
    _enforce_http_client_bound(current_key="proxy-new")

    assert len(pool) <= 3, "连接桶必须收进上界内"
    assert "proxy-0" not in pool and pool.get("proxy-1") is not None
    assert "proxy-new" in pool, "刚入队尾的在用键不得被淘汰"


def test_http_client_bound_never_closes_in_use_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反向不误伤：上界未超 ⇒ 一枚都不该被关。"""
    pool: OrderedDict[str, _FakeClient] = OrderedDict(
        {"": _FakeClient(), "loopback:direct": _FakeClient()}
    )
    for client in pool.values():
        client.closed_count = 0
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS", pool)
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS_MAX_BUCKETS", 8)

    _enforce_http_client_bound(current_key="loopback:direct")
    assert len(pool) == 2
    assert all(client.closed_count == 0 for client in pool.values())


def test_http_client_bound_keeps_current_when_would_evict_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """在用键（刚挪到队尾）绝不被关：淘汰只踢队首的其他桶。"""
    current = _FakeClient()
    old = _FakeClient()
    pool: OrderedDict[str, _FakeClient] = OrderedDict([("old", old), ("current", current)])
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS", pool)
    monkeypatch.setattr(providers_module, "_HTTP_CLIENTS_MAX_BUCKETS", 1)

    # 生产路径里 current_key 总是先 move_to_end(last=True) 再进本函数。
    pool.move_to_end("current", last=True)
    _enforce_http_client_bound(current_key="current")
    assert current.closed_count == 0, "在用连接桶被关了＝误伤"
    assert "current" in pool
    assert old.closed_count == 1, "最久未用的旧桶应被关闭释放"


# ------------------------------------------------------------------ ② 嵌入 memo LRU


@pytest.fixture()
def _reset_embed_memo():
    vk.reset_query_embed_memo()
    yield
    vk.reset_query_embed_memo()


def test_memo_overflow_evicts_lru_not_clear_all(
    monkeypatch: pytest.MonkeyPatch, _reset_embed_memo
) -> None:
    monkeypatch.setattr(vk, "_QUERY_EMBED_MEMO_MAX_ENTRIES", 3)
    vec = [[0.1, 0.2]]

    for name in ("q1", "q2", "q3"):
        vk._query_embed_memo_put(("sig", name), vec)
    # 命中 q1 把它挪到队尾（变热键），此时最久未用是 q2。
    assert vk._query_embed_memo_get(("sig", "q1")) is not None
    vk._query_embed_memo_put(("sig", "q4"), vec)

    # 注毒向：溢出只踢最久未用的 q2，热键 q1 必须活着（旧腿 .clear() 会全清）。
    assert vk._query_embed_memo_get(("sig", "q1")) is not None, "热键被误清＝旧腿回潮"
    assert vk._query_embed_memo_get(("sig", "q2")) is None, "最久未用者应被淘汰"
    assert vk._query_embed_memo_get(("sig", "q4")) is not None
    assert len(vk._QUERY_EMBED_MEMO) <= 3


def test_memo_ttl_expiry_on_read(_reset_embed_memo, monkeypatch: pytest.MonkeyPatch) -> None:
    """过期键读取即删，不占 LRU 名额（读侧顺手清）。"""
    vk._query_embed_memo_put(("sig", "exp"), [[0.5]])
    monkeypatch.setattr(vk, "_QUERY_EMBED_MEMO_TTL_SECONDS", -1.0)
    assert vk._query_embed_memo_get(("sig", "exp")) is None
    assert ("sig", "exp") not in vk._QUERY_EMBED_MEMO


def test_memo_hit_reuses_value(_reset_embed_memo) -> None:
    vec = [[0.3, 0.4]]
    vk._query_embed_memo_put(("sig", "same"), vec)
    assert vk._query_embed_memo_get(("sig", "same")) == vec
