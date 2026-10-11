"""查看向量知识库嵌入进度：python scripts/knowledge_progress.py

两个库分别报：``memory`` 是角色长期记忆向量库，``wiki`` 是百科语料接货库
（23:40 那轮 kb-sync 写的是后者）。只读打开（``mode=ro``）——一轮同步要跑数小时，
看进度时绝不跟它抢写锁。

wiki 侧把 kb-sync 写在 ``knowledge_meta`` 的收工摘要一并打出来，因为**行数不是收工判据**：
同步在投料阶段就把台账行与块行全落库了，块表"100% 有 vector_json"既可能意味着投完、
也可能意味着本轮还没开始嵌。摘要里 ``embed_pending`` 是**本轮投料数（分母）**、
``embedded`` 是本轮实嵌（分子），别把它当"还剩多少"读。

🔴 **索引实数腿**（2026-10-08 补牙）：``ann_expected_vector_count == 库内已嵌`` 只证明
**账对得上**，不证明**盘上那枚 ``.index`` 真把向量装下了**——短装的索引照样让两条账面数相等，
后果是载入路径拒用 ANN、每条消息回落暴力扫描，而屏幕上仍是一排 ``[ok]``。本脚本因此在同一轮里
**现算索引实数 ntotal** 并与应嵌数比，人读那一行三个数并列（应嵌／库内已嵌／索引 ntotal）
加一枚带符号差。取数三级：①只读序列化头 16 字节（**绝不整本载入**：线上 ``.index`` 是 GB 量级、
bot 常驻数 GiB，``faiss.read_index`` 一发就能把她压死；体积现算看 ``os.stat``，本文件不抄数）
→②``.index`` 在位但头部读不出时，退用 ann_pair 那把尺的代际证明戳（**来源必须上屏**：
那是发布时点盖进去的数，不是此刻盘上的数）→③都不行 ⇒ 明写 ``UNDECIDABLE:<原因>`` 且该行判
``[!!]``、``settled`` 不成立。**"取不到"绝不折成 ok、绝不折成 0**（本仓栽过两次：取不到样本
即放行＝当场瞎掉）。文件缺席时**不**走第②级——拿戳去替一枚不在盘的索引，正是 ann_pair 在册
点名过的"证明自洽而磁盘没东西"假绿形。语义锁在宿主件
``tests/test_knowledge_progress_settled_gate.py``（含真 faiss 序列化接地的头部锁 + 两发注毒）。
"""

import json
import sqlite3
import struct
import sys
from pathlib import Path
from typing import Any

from runtime_paths import runtime_path

STORES = {
    "memory": "data/knowledge_embeddings.sqlite3",
    "wiki": "data/kb_wiki_embeddings.sqlite3",
}
SUMMARY_KEY = "kb_sync_last_summary"
ANN_EXPECTED_KEY = "ann_expected_vector_count"

#: FAISS 序列化头里 ntotal 的字节位置：fourcc(4 B) + int32 维数(4 B) + int64 ntotal(8 B)。
#: 本机 faiss 1.15.0 现算坐实（自建小索引换 d 换 n 三组 + 线上两枚 ``.index`` 的头读数
#: 与当日三把独立尺的实开 ntotal 逐字相等）。执法锁＝宿主件的
#: ``test_header_ntotal_matches_real_faiss_serialization``（真 faiss 写、本尺读，两侧必须相等）
#: 与 ``test_leg_never_loads_the_whole_index``（AST 锁：不调 faiss、不调 read_index、只读
#: ``ANN_HEADER_BYTES``）——夹具本身也只有 16 字节，读得出来即结构自证。
ANN_HEADER_BYTES = 16
#: 本仓 ANN 只可能是这两枚类标：现役 ``vector_knowledge._make_ann_index`` 造
#: ``IndexHNSWSQ``（``IHNs``），S181 换存储之前的旧代是 ``IndexHNSWFlat``（``IHNf``）。
#: 不在册的 fourcc ⇒ 判「取不到」，不许照猜偏移：猜错就是把短装洗成 ok。
ANN_HNSW_FOURCC: tuple[bytes, ...] = (b"IHNs", b"IHNf")
NTOTAL_SOURCE_HEADER = "索引头实读"
NTOTAL_SOURCE_ATTESTED = "代际证明戳·发布时点(未实读盘上件)"
UNDECIDABLE_PREFIX = "UNDECIDABLE:"
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


def _read_index_ntotal(index_path: Path) -> tuple[int | None, str]:
    """只读 FAISS 序列化头的前 ``ANN_HEADER_BYTES`` 字节取索引实数 ntotal。

    返回 ``(ntotal, "")`` 或 ``(None, 原因)``。取不到的一律原因上屏，**不折成 0**
    （0 是合法测得值：真·空索引的头就读出 0，锁＝宿主件
    ``test_zero_ntotal_is_a_measured_value_not_undecidable``）。
    四形取不到：文件不在盘／头不足 16 字节（半写或被截）／fourcc 不在本仓可造的两枚
    （⇒ 偏移无从认定，猜就是把短装洗成 ok）／头里的维数或 ntotal 非法（负数、
    int64 溢出形态）。
    """
    if not index_path.is_file():
        return None, "index_absent"
    try:
        with open(index_path, "rb") as handle:
            head = handle.read(ANN_HEADER_BYTES)
    except OSError as exc:
        return None, f"index_open_failed({type(exc).__name__})"
    if len(head) < ANN_HEADER_BYTES:
        return None, f"index_header_short({len(head)}B<{ANN_HEADER_BYTES}B)"
    fourcc = head[:4]
    if fourcc not in ANN_HNSW_FOURCC:
        return None, f"index_fourcc_unlisted({fourcc!r})"
    dim = int(struct.unpack_from("<i", head, 4)[0])
    ntotal = int(struct.unpack_from("<q", head, 8)[0])
    if dim <= 0 or ntotal < 0:
        return None, f"index_header_implausible(dim={dim},ntotal={ntotal})"
    return ntotal, ""


def _ann_pair_ruler() -> Any:
    """把 ann_pair 那把尺（``scripts/pre_restart_check.py``）的取数原语引进来；取不到 ⇒ None。

    只借它的**键名与整型口径**，不借它的路径判定：它按 ``.env`` 的
    ``BOT_KB_WIKI_DB_PATH`` 解析库，本脚本按 ``runtime_path`` 逐库报，注入测试里两者
    不同源；拿它的路径会把生产库读数混进tmp夹具。直跑形态（``python scripts/x.py``）
    仓库根不在 ``sys.path``，故补一次根再重导。
    """
    try:
        import pre_restart_check as ruler

        return ruler
    except ImportError:
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import pre_restart_check as ruler

            return ruler
        except ImportError:
            return None


def _attested_index_ntotal(meta: dict[str, str]) -> tuple[int | None, str]:
    """第②级：代际证明 ``ann_pair_attestation`` 里的 ntotal（发布时点盖进去的数）。

    键名、JSON 解析与整型口径全部走 ann_pair 那把尺自己的函数，本文件不另立第二份。
    """
    ruler = _ann_pair_ruler()
    if ruler is None:
        return None, "ann_pair_ruler_unimportable"
    attestation = ruler._ann_json_row(meta.get(ruler.ANN_ATTESTATION_META_KEY, ""))
    if attestation is None:
        return None, "attestation_absent"
    ntotal = ruler._ann_int(attestation.get("ntotal"))
    if ntotal is None:
        return None, "attestation_ntotal_unparseable"
    return ntotal, ""


def _resolve_index_ntotal(db_path: Path, meta: dict[str, str]) -> tuple[int | None, str, str]:
    """索引实数 ntotal 的三级取数：①头部实读 → ②代际证明戳 → ③UNDECIDABLE（明写原因）。

    返回 ``(ntotal, 来源标签, 取不到的原因)``。第②级只在**盘上确有 ``.index``** 时启用：
    文件缺席却拿戳来宣称"装下了"，正是 ann_pair 在册点名的"证明自洽而磁盘没东西"假绿形。
    """
    reasons: list[str] = []
    index_path: Path | None = None
    try:
        from rebuild_ann_index import default_pair_paths

        index_path, _order_path = default_pair_paths(db_path)
    except ImportError as exc:
        reasons.append(f"pair_path_ruler_failed({type(exc).__name__})")

    if index_path is None:
        # 路径派生尺装不上：连"盘上有没有"都判不了，只能退回戳，并把来源如实标成戳。
        attested, attested_reason = _attested_index_ntotal(meta)
        if attested is not None:
            return attested, NTOTAL_SOURCE_ATTESTED, ""
        reasons.append(attested_reason)
        return None, "", ";".join(reasons)

    ntotal, header_reason = _read_index_ntotal(index_path)
    if ntotal is not None:
        return ntotal, NTOTAL_SOURCE_HEADER, ""
    reasons.append(f"{index_path.name}:{header_reason}")
    if index_path.is_file():
        attested, attested_reason = _attested_index_ntotal(meta)
        if attested is not None:
            return attested, NTOTAL_SOURCE_ATTESTED, ""
        reasons.append(attested_reason)
    return None, "", ";".join(reasons)


def _completeness_max_missing() -> int:
    """短装容差的真身＝ann_pair 那把尺的 ``ANN_COMPLETENESS_MAX_MISSING``。

    取不到尺时按 0 判（**只严不松**：真身现值就是 0，任何放宽都不会在这里发生）。
    """
    ruler = _ann_pair_ruler()
    if ruler is None:
        return 0
    return int(ruler.ANN_COMPLETENESS_MAX_MISSING)


def _index_leg_line(
    ann_expected: int, embedded_after_text: str, ntotal: int | None, source: str, reason: str
) -> tuple[str, bool]:
    """人读那一行：应嵌／库内已嵌／索引实数 三个数并列 + 带符号差（正数＝短装）。"""
    triple = f"［应嵌({ann_expected})／库内已嵌({embedded_after_text})／"
    if ntotal is None:
        undecidable = (
            f"ANN 索引实数 {UNDECIDABLE_PREFIX}{reason}"
            f"{triple}索引ntotal(取不到)］⇒ 装没装下无从判定，本行不构成收工证据"
        )
        return undecidable, False
    signed_gap = ann_expected - ntotal
    measured = (
        f"ANN 索引实数 ntotal={ntotal}（源={source}）"
        f"{triple}索引ntotal({ntotal})／差(应嵌-索引)={signed_gap:+d}，正数＝短装］"
    )
    return measured, signed_gap <= _completeness_max_missing()


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
            _report_wiki_settled(con, total, since, runtime_path(rel_path))


def _report_wiki_settled(
    con: sqlite3.Connection, total: int, since: str = "", db_path: Path | None = None
) -> None:
    """收工判据只在「摘要 + ANN 应嵌数 + 库内行数 + 索引实数 ntotal」四者对得上时才成立。"""
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
            value = summary[key]
            # after 三件在失败轮落 null（本轮未测得，2026-09-27 汇总修复）：
            # 打「未测得」而不是 None/0——0 是合法测得值，三态不许塌回 0。
            label = "未测得" if value is None else value
            print(f"  {key}={label}")

    started = str(summary.get("started_at") or "")
    if since and started < since:
        print(f"  [!!] 摘要 started_at={started} 早于基线 {since} ⇒ 这一档还没开跑")
        print("=> 本轮未开始（上面的判据描述的是上一轮，别拿它当今晚已投完）")
        return

    def num(key: str) -> int:
        return int(summary.get(key) or 0)

    def after_num(key: str, label: str) -> tuple[int, str]:
        """after 三态取数：null（失败轮未测）→ 判据按不成立走、展示为「未测得」。

        用 -1 哨兵而不是把 None 折成 0：0 会被读成"测得 0 行"，正是本脚本
        要避免的伪装（与 kb_wiki._sync_summary 的三态口径同一）。
        """
        raw = summary.get(key)
        if raw is None:
            return -1, label
        return int(raw or 0), str(int(raw or 0))

    pending = num("embed_pending")
    done = num("embedded")
    embedded_after, embedded_after_text = after_num("embedded_after", "未测得")
    ann_expected = int(meta.get(ANN_EXPECTED_KEY) or 0)
    checks = [
        ("本轮 ok 且无 error_kind", bool(summary.get("ok")) and summary.get("error_kind") in (None, "none")),
        (f"本轮队列清空 embedded({done})>=embed_pending({pending})", done >= pending),
        (f"库内已嵌({embedded_after_text})>=块行数({total})", embedded_after >= total),
        (f"ANN 应嵌数({ann_expected})==库内已嵌({embedded_after_text})", ann_expected == embedded_after),
    ]
    # 索引实数腿（补牙的那一条）：账面数对上不等于盘上装下——现算 ntotal 再比一次。
    if db_path is None:
        ntotal, ntotal_source, leg_reason = None, "", "db_path_not_supplied"
    else:
        ntotal, ntotal_source, leg_reason = _resolve_index_ntotal(db_path, meta)
    leg_line, leg_passed = _index_leg_line(
        ann_expected, embedded_after_text, ntotal, ntotal_source, leg_reason
    )
    checks.append((leg_line, leg_passed))
    for name, passed in checks:
        print(f"  {'[ok]' if passed else '[!!]'} {name}")
    if not leg_passed:
        print(
            "  ↳ 索引实数腿短装/取不到 ⇒ 载入路径拒用 ANN、每条消息回落暴力扫描；"
            "重建走 scripts/rebuild_ann_index.py（内存门按 vector_knowledge."
            "_ann_build_demand_bytes 现算，本脚本只看不建）"
        )
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
