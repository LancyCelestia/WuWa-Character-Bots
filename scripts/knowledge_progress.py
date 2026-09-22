"""查看向量知识库嵌入进度：python scripts/knowledge_progress.py

两个库分别报：``memory`` 是角色长期记忆向量库，``wiki`` 是百科语料接货库
（23:40 那轮 kb-sync 写的是后者）。只读打开（``mode=ro``）——一轮同步要跑数小时，
看进度时绝不跟它抢写锁。

wiki 侧把 kb-sync 写在 ``knowledge_meta`` 的收工摘要一并打出来，因为**行数不是收工判据**：
同步在投料阶段就把台账行与块行全落库了，块表"100% 有 vector_json"既可能意味着投完、
也可能意味着本轮还没开始嵌。摘要里 ``embed_pending`` 是**本轮投料数（分母）**、
``embedded`` 是本轮实嵌（分子），别把它当"还剩多少"读。
"""

import json
import sqlite3
import sys

from runtime_paths import runtime_path

STORES = {
    "memory": "data/knowledge_embeddings.sqlite3",
    "wiki": "data/kb_wiki_embeddings.sqlite3",
}
SUMMARY_KEY = "kb_sync_last_summary"
ANN_EXPECTED_KEY = "ann_expected_vector_count"
SUMMARY_FIELDS = (
    "started_at",
    "finished_at",
    "ok",
    "error_kind",
    "added",
    "changed",
    "removed",
    "chunks",
    "embedded",
    "embed_pending",
    "documents_after",
    "chunks_after",
    "embedded_after",
    "ann_rebuilt",
    "reconcile_status",
)


def _open_readonly(rel_path: str) -> sqlite3.Connection | None:
    db_path = str(runtime_path(rel_path))
    uri = f"file:{db_path.replace(chr(92), '/')}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True, timeout=10)
    except sqlite3.Error as exc:
        print(f"[{rel_path}] 打不开（{type(exc).__name__}: {exc}）")
        return None


def _chunk_counts(con: sqlite3.Connection) -> tuple[int, int]:
    total = int(con.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
    embedded = int(
        con.execute(
            "SELECT COUNT(*) FROM knowledge_chunks "
            "WHERE vector_json IS NOT NULL AND vector_json <> ''"
        ).fetchone()[0]
    )
    return total, embedded


def _report(label: str, rel_path: str, since: str = "") -> None:
    con = _open_readonly(rel_path)
    if con is None:
        return
    with con:
        try:
            total, embedded = _chunk_counts(con)
        except sqlite3.Error as exc:
            print(f"== {label} == 读不到切片表（{type(exc).__name__}: {exc}）")
            return
        percent = embedded * 100 // total if total else 0
        print(f"== {label} ({rel_path}) ==")
        print(f"embedded={embedded} total={total} percent={percent}%")
        if embedded >= total > 0:
            print("库内切片全部带向量（注意：这不代表本轮已收工，见下方摘要）")
        else:
            print(f"库里还有 {total - embedded} 条未向量化")
        if label == "wiki":
            _report_wiki_settled(con, total, since)


def _report_wiki_settled(con: sqlite3.Connection, total: int, since: str = "") -> None:
    """收工判据只在「摘要 + ANN 应嵌数 + 库内行数」三者对得上时才成立。"""
    try:
        docs = int(con.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0])
        meta = {
            str(row[0]): str(row[1])
            for row in con.execute("SELECT key, value FROM knowledge_meta")
        }
    except sqlite3.Error as exc:
        print(f"台账/元数据读不到（{type(exc).__name__}: {exc}）")
        return
    print(f"documents={docs}")
    raw = meta.get(SUMMARY_KEY)
    if not raw:
        print("还没有 kb-sync 收工摘要（这一轮从未跑完过）")
        return
    try:
        summary = json.loads(raw)
    except json.JSONDecodeError:
        print("收工摘要不是合法 JSON，不猜内容")
        return
    for key in SUMMARY_FIELDS:
        if key in summary:
            print(f"  {key}={summary[key]}")

    started = str(summary.get("started_at") or "")
    if since and started < since:
        print(f"  [!!] 摘要 started_at={started} 早于基线 {since} ⇒ 这一档还没开跑")
        print("=> 本轮未开始（上面的判据描述的是上一轮，别拿它当今晚已投完）")
        return

    def num(key: str) -> int:
        return int(summary.get(key) or 0)

    pending = num("embed_pending")
    done = num("embedded")
    embedded_after = num("embedded_after")
    ann_expected = int(meta.get(ANN_EXPECTED_KEY) or 0)
    checks = (
        ("本轮 ok 且无 error_kind", bool(summary.get("ok")) and summary.get("error_kind") in (None, "none")),
        (f"本轮队列清空 embedded({done})>=embed_pending({pending})", done >= pending),
        (f"库内已嵌({embedded_after})>=块行数({total})", embedded_after >= total),
        (f"ANN 应嵌数({ann_expected})==库内已嵌({embedded_after})", ann_expected == embedded_after),
    )
    for name, passed in checks:
        print(f"  {'[ok]' if passed else '[!!]'} {name}")
    settled = all(passed for _, passed in checks)
    print(f"=> {'这一轮已投完收工' if settled else '未收工（在途，或上一轮没投完）'}")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    since = ""
    if "--since" in argv:
        since = str(argv[argv.index("--since") + 1])
    for label, rel_path in STORES.items():
        _report(label, rel_path, since)


if __name__ == "__main__":
    main()
