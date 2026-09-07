"""知识库检索性能与复杂度基准：python scripts/knowledge_bench.py

测量：
1) HNSW 热路径延迟（多次，p50/p95，含 Ollama 查询编码）
2) 暴力 O(N*D) 在不同 N 下的耗时（验证线性增长）
3) HNSW 在不同 N 下的搜索耗时（验证近对数增长）
4) 进程 RSS 与 CPU 占用
"""
import statistics
import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import faiss
    import numpy as np
except Exception as exc:  # noqa: BLE001
    print(f"缺少依赖：{exc}")
    sys.exit(2)

from runtime_paths import runtime_path

from plugins.bot_unified_runtime.character.vector_knowledge import (
    OpenAICompatibleEmbeddingProvider,
    SqliteVectorKnowledgeStore,
)

DB = runtime_path('data/knowledge_embeddings.sqlite3')
SIG = "http://127.0.0.1:11434/v1|bge-m3;https://dashscope.aliyuncs.com/compatible-mode/v1|qwen3.7-text-embedding,text-embedding-v4"
QUERY = "鸣潮 今州是什么地方"


def _provider():
    return OpenAICompatibleEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen3.7-text-embedding,text-embedding-v4",
        api_key="x",
        local_base_url="http://127.0.0.1:11434/v1",
        local_models="bge-m3",
        local_enabled=True,
        dimensions=1024,
        timeout_seconds=5,
        local_timeout_seconds=10,
    )


def main() -> int:
    store = SqliteVectorKnowledgeStore(DB, _provider(), chunk_chars=600, top_k=5, signature=SIG, auto_reset=False)
    proc = psutil.Process()

    print("== 1) HNSW 热路径延迟 ==")
    store.retrieve(QUERY, embed_backlog=False)  # 预热
    lat = []
    for _ in range(5):
        t = time.perf_counter()
        store.retrieve(QUERY, embed_backlog=False)
        lat.append(time.perf_counter() - t)
    print(f"p50={statistics.median(lat)*1000:.0f}ms p95={max(lat)*1000:.0f}ms")
    print(f"rss={proc.memory_info().rss // 1048576}MB cpu={proc.cpu_percent(interval=0.5):.1f}%")

    print("== 2) 暴力 O(N*D) 随 N 增长 ==")
    matrix, _ids = store._load_vector_cache()
    q = np.asarray(store._embed([QUERY])[0], dtype=np.float32)
    for n in (1000, 5000, 15000, 30802):
        sub = matrix[:n]
        t = time.perf_counter()
        for _ in range(3):
            _ = sub @ q
        print(f"N={n:>6}  matmul={(time.perf_counter()-t)/3*1000:6.2f}ms")

    print("== 3) HNSW 搜索随 N 增长（每档建小索引） ==")
    norms = np.linalg.norm(matrix, axis=1)
    m = matrix / np.maximum(norms, 1e-9)[:, None]
    for n in (1000, 5000, 15000, 30802):
        idx = faiss.IndexHNSWFlat(int(matrix.shape[1]), 32, faiss.METRIC_INNER_PRODUCT)
        idx.hnsw.efConstruction = 40  # 基准用低 ef 快速建
        idx.add(m[:n].astype(np.float32))
        idx.hnsw.efSearch = 64
        t = time.perf_counter()
        for _ in range(20):
            _scores, _indices = idx.search(q.reshape(1, -1), 5)
        print(f"N={n:>6}  hnsw={(time.perf_counter()-t)/20*1000:6.2f}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
