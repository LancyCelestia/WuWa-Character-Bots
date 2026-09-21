"""#50 冷启动防线：嵌入首批失败不该让整轮归零。

现场（2026-09-20 23:48 无人值守同步，实跑读数）：
    added=574 chunks=5943 embedded=0 embed_pending=5943
    ok=false error_kind=partial
    public_message=「嵌入只完成 0/5943 行，请检查 Ollama/嵌入端点后重跑」
端点随后复查三层链全可用（batch 1/8/64 均 OK dim 1024），14:00 那次还能正常嵌 1070 块。
⇒ 根因是**首批承担 Ollama 模型冷加载**，一旦超过 local_timeout_seconds 就返回空，
而 `_embed_all_pending` 见 None 即 break —— 一次冷启动能吃掉一夜的嵌入。

本文件锁三件事：批循环前先预热一次；首个批次拿不到向量时重试一次再放弃；
以及**不许变成无限重试**（端点真死了要快速退出，别把同步拖成长任务）。
全程离线：替身 provider，零网络。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge import (
    SqliteVectorKnowledgeStore,
)

_DIM = 8


class _StubProvider:
    """可控的嵌入替身：前 fail_first 次返回空列表（模拟冷启动超时后返回 []）。"""

    def __init__(self, *, fail_first: int = 0) -> None:
        self.fail_first = fail_first
        self.calls: list[int] = []  # 每次调用收到的文本条数
        self.signature = "stub|dim=8"

    def embed_texts(self, texts):
        self.calls.append(len(texts))
        if len(self.calls) <= self.fail_first:
            return []
        return [[0.1] * _DIM for _ in texts]


def _store(tmp_path, provider):
    return SqliteVectorKnowledgeStore(
        db_path=str(tmp_path / "kb.sqlite3"),
        embed_provider=provider,
        chunk_chars=200,
        top_k=4,
        signature=provider.signature,
        auto_reset=False,
    )


def _seed(store, rows):
    store.sync_chunks(rows)


def _md(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_warms_up_with_one_extra_call_before_the_real_batches(tmp_path):
    """批循环前先打一发廉价预热：模型加载的成本不该由正式批次承担。

    断言「正式批次之外多了一次前置调用」，且条数由实际 pending 推导 ——
    首版把语料写得太短（chunk_chars=200 下只切出 1 块），断言碰巧空过，是假测试。
    """
    provider = _StubProvider()
    store = _store(tmp_path, provider)
    body = "\n\n".join(f"第{i}段：" + "内容" * 160 for i in range(1, 5))
    files = [_md(tmp_path, "a.md", body)]
    _seed(store, files)

    done, pending = store.embed_pending(files, batch_size=1)

    assert done == pending > 1, f"pending={pending} done={done}"
    # 预热 1 次 + 每块一次正式调用；没有预热就少一次。
    assert len(provider.calls) == pending + 1, (
        f"应多出发起预热 1 次：calls={provider.calls} pending={pending}"
    )


def test_first_batch_empty_result_is_retried_instead_of_zeroing_the_run(tmp_path):
    """首批拿不到向量时重试一次；冷启动只该吃掉一次调用，不该吃掉整轮。"""
    provider = _StubProvider(fail_first=2)  # 预热 + 首批各失败一次
    store = _store(tmp_path, provider)
    files = [_md(tmp_path, "b.md", "段落一。\n\n段落二。\n\n段落三。")]
    _seed(store, files)

    done, pending = store.embed_pending(files)

    stats = store.stats()
    assert stats["embedded"] == stats["total"], f"实际嵌入 {stats}，本轮 pending={pending}"
    assert done == pending > 0


def test_permanently_dead_endpoint_stops_promptly_without_endless_retry(tmp_path):
    """端点真死了必须快速退出（别把同步拖成长任务）：重试次数是有界的。"""
    provider = _StubProvider(fail_first=10_000)
    store = _store(tmp_path, provider)
    files = [_md(tmp_path, "c.md", "内容一二三。\n\n内容四五六。")]
    _seed(store, files)

    done, pending = store.embed_pending(files)

    assert done == 0 and pending > 0
    assert len(provider.calls) <= 4, f"重试必须有界，实际调用 {len(provider.calls)} 次：{provider.calls}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
