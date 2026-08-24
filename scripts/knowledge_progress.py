"""查看向量知识库嵌入进度：python scripts/knowledge_progress.py"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "knowledge_embeddings.sqlite3"

con = sqlite3.connect(DB, timeout=10)
total = con.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
embedded = con.execute(
    "SELECT COUNT(*) FROM knowledge_chunks WHERE vector_json IS NOT NULL AND vector_json <> ''"
).fetchone()[0]
con.close()
percent = embedded * 100 // total if total else 0
print(f"embedded={embedded} total={total} percent={percent}%")
if embedded >= total > 0:
    print("完成：全部切片已向量化。")
else:
    print(f"进行中：还剩 {total - embedded} 条。")
