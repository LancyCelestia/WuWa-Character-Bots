"""#51 批×超时的边缘配比：嵌入批大小必须能自己收缩，而不是一夜归零。

现场（2026-09-20 23:48 无人值守同步，kb_wiki 库 knowledge_meta 权威记录）：
    added=574 chunks=5943 embedded=0 embed_pending=5943
    ok=false error_kind=partial
端点随后三层链全可用（batch 1/8/64 均 OK），#50 的冷启动预热也已在岗——
真正的账要算配比：
    生产 .env  BOT_KB_WIKI_EMBED_BATCH=128 × BOT_EMBEDDING_LOCAL_TIMEOUT_SECONDS=5
    实测吞吐   本地 Ollama 约 19 块/s ⇒ 128 块 ≈ 6.7s **必然**超过 5s
⇒ 不是偶发冷启动，是**每一批都超时**，预热与"同尺寸重试一次"都救不了（#50 不充分）。
第二个真实形态：本地链退掉后落远程链，远程单批上限 10 条会直接拒 128 条
（provider 返回 [] → 长度不符 → _embed 判 None），同样整轮归零。

修法（本文件锁的行为）：拿不到向量时把当前批**折半重试**，下限
`_EMBED_BATCH_SIZE`（=10，恰好也是远程单批上限），并把收缩后的尺寸**记住**给
后续批次——不每批重新撞一次同一堵墙。端点真死时仍然快速退出：折半链有界，
到底仍失败即 break。全程离线：替身 provider，零网络。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    _EMBED_BATCH_SIZE,
    SqliteVectorKnowledgeStore,
)

_DIM = 8
_CONFIGURED_BATCH = 128      # 生产 .env 的实际值
_EFFECTIVE_LIMIT = 50        # 5s 超时折算成块数的替身阈值（128 必超、64 以内可过）


class _SizeSensitiveProvider:
    """条数超过 max_ok 就"超时"（返回 []，与真实 httpx 超时后 provider 的口径一致）。"""

    def __init__(self, *, max_ok: int | None = _EFFECTIVE_LIMIT, always_fail: bool = False):
        self.max_ok = max_ok
        self.always_fail = always_fail
        self.calls: list[int] = []
        self.signature = "stub|dim=8"

    def embed_texts(self, texts):
        self.calls.append(len(texts))
        if self.always_fail:
            return []
        if self.max_ok is not None and len(texts) > self.max_ok:
            return []
        return [[0.1] * _DIM for _ in texts]


def _store(tmp_path, provider):
    return SqliteVectorKnowledgeStore(
        db_path=str(tmp_path / "kb.sqlite3"),
        embed_provider=provider,
        chunk_chars=180,
        top_k=4,
        signature=provider.signature,
        auto_reset=False,
    )


def _seed_many(tmp_path, store, paragraphs: int):
    """造出足够多的待嵌行（必须 > 配置批大小，否则"首批就超限"这一前提不成立）。"""
    body = "\n\n".join(
        f"第{i}段：" + "内容样本" * 60 for i in range(1, paragraphs + 1)
    )
    path = Path(tmp_path) / "corpus.md"
    path.write_text(body, encoding="utf-8")
    store.sync_chunks([path])
    return path


def test_oversized_batch_self_halves_instead_of_zeroing_the_run(tmp_path):
    """128 批在 5s 超时下必挂：整轮必须靠折半跑完，而不是 embedded=0。"""
    provider = _SizeSensitiveProvider()
    store = _store(tmp_path, provider)
    files = [_seed_many(tmp_path, store, paragraphs=180)]

    done, pending = store.embed_pending(files, batch_size=_CONFIGURED_BATCH)

    assert pending > _CONFIGURED_BATCH, f"pending={pending}，前提（首批就超限）不成立"
    assert done == pending, f"折半后应全部完成：done={done} pending={pending}"
    stats = store.stats()
    assert stats["embedded"] == stats["total"]


def _first_working_call(real_calls: list[int], limit: int) -> tuple[int, int]:
    """返回 (首个能过批的下标, 该批大小)。收缩链 128→64→32 里的中间失败点不算回归。"""
    for index, size in enumerate(real_calls):
        if size <= limit:
            return index, size
    raise AssertionError(f"从未出现可过批：calls={real_calls}")


def test_reduced_size_is_remembered_so_later_batches_do_not_rehit_the_wall(tmp_path):
    """收缩后的尺寸要留给后续批次：每批都先用 128 撞一次 = 每晚白烧 N 个超时。"""
    provider = _SizeSensitiveProvider()
    store = _store(tmp_path, provider)
    files = [_seed_many(tmp_path, store, paragraphs=180)]

    done, pending = store.embed_pending(files, batch_size=_CONFIGURED_BATCH)

    real_calls = provider.calls[1:]  # 首点是预热
    assert done == pending > 0
    first_ok, working_size = _first_working_call(real_calls, _EFFECTIVE_LIMIT)
    assert first_ok < len(real_calls) - 2, f"批次太少不足以检验'后续'：{provider.calls}"
    tail = real_calls[first_ok:]
    assert max(tail) == working_size, (
        f"首过后批大小应钉在收缩值 {working_size}，不得回头重试超限批：{tail}"
    )


def test_remote_single_batch_limit_also_lands_on_the_floor(tmp_path):
    """退到远程链时单批上限 10：折半下限恰是 _EMBED_BATCH_SIZE，能自动接住。"""
    provider = _SizeSensitiveProvider(max_ok=_EMBED_BATCH_SIZE)
    store = _store(tmp_path, provider)
    files = [_seed_many(tmp_path, store, paragraphs=180)]

    done, pending = store.embed_pending(files, batch_size=_CONFIGURED_BATCH)

    assert done == pending > 0
    real_calls = provider.calls[1:]
    first_ok, working_size = _first_working_call(real_calls, _EMBED_BATCH_SIZE)
    assert max(real_calls[first_ok:]) == working_size <= _EMBED_BATCH_SIZE, (
        f"最终生效批大小必须钉在远程上限内：{real_calls}"
    )


def test_dead_endpoint_still_exits_fast_after_a_bounded_halving_chain(tmp_path):
    """端点真死了仍要有界退出：折半链走完到底就 break，不许把同步拖成长任务。"""
    provider = _SizeSensitiveProvider(always_fail=True)
    store = _store(tmp_path, provider)
    files = [_seed_many(tmp_path, store, paragraphs=180)]

    done, pending = store.embed_pending(files, batch_size=_CONFIGURED_BATCH)

    assert done == 0 and pending > 0
    # 预热 1 + 128 失败 + 同尺寸重试 1 + 64/32/16/10 折半链 = 有界
    assert len(provider.calls) <= 8, f"重试必须有界，实际 {provider.calls}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
