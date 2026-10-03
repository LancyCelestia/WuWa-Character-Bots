"""rebuild_ann_index — FAISS ANN 索引运维重建入口（签名翻车时的未来入口）.

背景：知识库载入端（vector_knowledge.load_ann_index）要求
``ann_signature == embedding_signature``，两者一旦错位，每条消息都回落暴力
扫描（慢而全）。2026-09 真库曾因两签名错位翻车、已在库级修好；本脚本是
**未来再翻车时的运维入口**：调库内既有 build/checkpoint/resume 机件做一次
干净全量重建，让发布点（``_publish_ann_pair``）把 ``ann_signature`` 重新
盖回 ``embedding_signature``，绝不自造第二套构建/检查点逻辑。

三种形态：
  dry-run（缺省安全）: 只读 URI 打开真库，报告两签名对齐状态、chunk 总数、
                       索引对/checkpoint/代际证明状态、空闲内存与重建预估
                       内存。零数据写入（WAL 旁车 -shm/-wal 可能在缺席时被
                       SQLite 只读连接创建，属连接机制、非数据写入）。
  实跑（不带 --dry-run）: 三道门全过才动第一根手指——
                       ① 幂等门：签名已对齐且索引对 mtime 新于库 mtime
                         ⇒ no-op（--force 才强制重建）；
                       ② 内存入口门：空闲物理内存 < 8.5 GiB 拒绝启动
                         （历史内存门 8.44 GiB → 取整 8.5；库内需求式门
                         会在 build_ann_index 里再判一次，双保险）；
                       ③ 写前备份：旧索引对改名 ``<名>.bak-<UTC 时刻>``，
                         重建失败自动改名回滚（恢复原状）。
  --force             越过幂等门；内存门不随之越（越内存门走 kb-sync 的
                       --ann-force-low-memory，本脚本不设第二根旁路笔）。

重建本体＝``SqliteVectorKnowledgeStore.build_ann_index``：分批流式读向量、
SQ8 量化、断点续跑三件套（``.wip-`` 半成品 + knowledge_meta 检查点行）、
跨进程建锁、原子成对发布——全部复用库内真身，本脚本零自造尺。

用法：
  venv python scripts/rebuild_ann_index.py --dry-run
  venv python scripts/rebuild_ann_index.py --dry-run --db <绝对路径>
  venv python scripts/rebuild_ann_index.py            # 实跑（受幂等门约束）
  venv python scripts/rebuild_ann_index.py --force    # 强制重建

退出码：0 = 成功/无害 no-op；2 = 前置不可用（库打不开 / embedding_signature
为空等）；3 = 内存门拒绝；4 = 重建未发布（原因见输出，已回滚旧索引对）；
5 = 异常（已尽力回滚）。

边界（诚实面）：
  * 本脚本对齐的是**库内** embedding_signature 这一枚。若模型/端点指纹本身
    已换而库未重嵌（运行时指纹 ≠ 库内 embedding_signature），正解是
    knowledge-sync 全链重嵌，重建索引救不了那个形态。
  * 实跑期间 bot 若持有索引 mmap，备份改名会报"文件被占用"并拒绝动工
    （fail-closed）——先停 bot 再实跑；dry-run 不受影响。
  * .bak 文件名以线上名开头（.bak- 后缀），按线上名**前缀**展开的宽 glob
    （如 ``kb_wiki_faiss*``）会把它算进家属；按完整线上名查找的读者不受影响。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT), str(ROOT / "scripts")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

try:  # 测试树以 `scripts.rebuild_ann_index` 导入；直跑形态回落兄弟模块名。
    from scripts.runtime_paths import runtime_path
except ImportError:  # pragma: no cover - 直跑形态
    from runtime_paths import runtime_path  # type: ignore[no-redef]

#: 库内 knowledge_meta 的两枚签名键（vector_knowledge 以字面量 SQL 在册，
#: 无常量可导；pre_restart_check 同款字面量，不另立第三处定义面）。
EMBED_SIG_KEY = "embedding_signature"
ANN_SIG_KEY = "ann_signature"
VECTOR_DIM_KEY = "vector_dim"

#: 实跑入口内存门（简报 2026-10-03：空闲 < 8.5 GiB 拒绝启动）。依据＝历史
#: 内存门实测 8.44 GiB（ANN 重建 OOM 夜的最低安全水位）取整；它只是**入口
#: 地板**，库内需求式门（_ann_build_demand_bytes，按规模/维数计价）随后在
#: build_ann_index 内照常再判，两道门同 fail-closed。
MIN_FREE_BYTES = int(8.5 * 1024**3)

#: 缺省目标库＝wiki 知识库（ANN 翻车事故的主角、对文件最大的那个库）；
#: 人格知识库等其它库用 --db 指名。路径经 runtime_paths 唯一实现重映射
#: data/ → ChatBot_Runtime/data（不在这里拼第二把路径尺）。
DEFAULT_DB_REL = "data/kb_wiki_embeddings.sqlite3"
DEFAULT_DB_ENV = "BOT_KB_WIKI_DB_PATH"

#: 备份后缀时刻格式：UTC（本仓纪律：文件名时刻一律 UTC，本地要换算）。
_BAK_STAMP_FMT = "%Y%m%dT%H%M%SZ"


def _load_vk():
    """懒加载 vector_knowledge 真身（ dry-run 也要用它的内存探针/需求式，
    保持全仓单一实现；直接 import 失败给出可执行的人话指引）。
    失败抛 RuntimeError，由 main 统一按退出码 2（前置不可用）收口。"""
    global _VK_CACHE
    if _VK_CACHE is not None:
        return _VK_CACHE
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.character import (
            vector_knowledge as vk_module,
        )
    except Exception as exc:  # 导入失败要给指路，不给裸栈
        raise RuntimeError(
            f"无法导入 vector_knowledge 真身：{exc}\n"
            "请在仓库根用运行 venv 执行本脚本（venv python scripts/rebuild_ann_index.py）"
        ) from exc
    _VK_CACHE = vk_module
    return vk_module


_VK_CACHE = None


def _dotenv_default_db() -> Path:
    """缺省库路径：--db > env/.env 的 BOT_KB_WIKI_DB_PATH > data/ 缺省相对名，
    统一经 runtime_path 重映射（读 env 用 runtime_paths 的既有读数口，
    不复制第二份 .env 解析器）。"""
    try:
        from scripts.runtime_paths import _dotenv_value
    except ImportError:  # pragma: no cover - 直跑形态
        from runtime_paths import _dotenv_value  # type: ignore[no-redef]
    declared = _dotenv_value(DEFAULT_DB_ENV)
    return runtime_path(declared or DEFAULT_DB_REL)


def default_pair_paths(db_path: Path) -> tuple[Path, Path]:
    """随库名派生 ANN 对缺省名（对齐两处在册构造点，不自造第四份口径）：

    * ``<stem>_embeddings`` → ``<stem>_faiss``（kb_wiki.py :705 硬编码
      ``kb_wiki_faiss.*``；vector_knowledge 缺省 ``knowledge_faiss.*`` 同格）；
    * 其余库名按 store 通用缺省 ``knowledge_faiss.*``；非标布置用
      --index/--order 显式指名。
    """
    stem = db_path.stem
    if stem.endswith("_embeddings"):
        stem = stem[: -len("_embeddings")] + "_faiss"
    else:
        stem = "knowledge_faiss"
    return db_path.with_name(f"{stem}.index"), db_path.with_name(f"{stem}.order.json")


# ---------------------------------------------------------------------------
# 只读体检（dry-run 与实跑前置共用；绝不构造 store——store 构造即写库）
# ---------------------------------------------------------------------------


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """只读 URI 打开（pre_restart_check._ann_meta_rows 同款；WAL 库旁车在
    场时读得到最新已提交态，旁车缺席时 SQLite 可能创建空 -shm/-wal——连接
    机制，非数据写入）。"""
    return sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5.0)


def _read_meta_map(db_path: Path, keys: tuple[str, ...]) -> dict[str, str] | None:
    """按主键点查 knowledge_meta 若干行；库/表打不开 ⇒ None（无从判定，
    绝不猜默认值——猜会把"读不到"洗成"读到了空"）。"""
    try:
        con = _connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        placeholders = ",".join("?" for _ in keys)
        rows = con.execute(
            f"SELECT key, value FROM knowledge_meta WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {str(k): "" if v is None else str(v) for k, v in rows}


def _read_signature_pair(db_path: Path) -> tuple[str, str] | None:
    """一次取回 (ann_signature, embedding_signature)；库/表读不出 ⇒ None。"""
    meta = _read_meta_map(db_path, (ANN_SIG_KEY, EMBED_SIG_KEY))
    if meta is None:
        return None
    return meta.get(ANN_SIG_KEY, "").strip(), meta.get(EMBED_SIG_KEY, "").strip()


def _count_chunks(db_path: Path) -> int | None:
    """knowledge_chunks 全表行数（离线维护口径；表缺席 ⇒ None）。"""
    try:
        con = _connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        return int(con.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        con.close()


def _max_rowid(db_path: Path) -> int | None:
    """rowid 上界（O(1) B-tree 最右叶；_estimate_rebuild_scale 的第二级口径）。"""
    try:
        con = _connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT MAX(rowid) FROM knowledge_chunks").fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if row is None or row[0] is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _blob_probe_dim(db_path: Path) -> int | None:
    """维数探测第二级：任取一条已嵌行按 float32 字节数折算
    （rebuild_ann_kb_wiki.ps1 的 gate 探针同款）。"""
    try:
        con = _connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        row = con.execute(
            "SELECT length(vector_blob) FROM knowledge_chunks "
            "WHERE vector_blob IS NOT NULL LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if row and row[0]:
        return int(row[0]) // 4
    return None


def _file_fact(path: Path) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "path": path,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "mtime": stat.st_mtime,
    }


@dataclass
class AnnState:
    """一次只读体检的全部事实（dry-run 报告与实跑三道门共用同一份读数）。"""

    db_path: Path
    index_path: Path
    order_path: Path
    meta: dict[str, str] = field(default_factory=dict)
    meta_ok: bool = True
    chunk_count: int | None = None
    free_bytes: int | None = None
    dim: int = 0
    scale: int | None = None  # 需求估算用的规模上界（戳 → MAX(rowid)）
    demand_bytes: int = 0

    @property
    def ann_sig(self) -> str:
        return self.meta.get(ANN_SIG_KEY, "").strip()

    @property
    def embed_sig(self) -> str:
        return self.meta.get(EMBED_SIG_KEY, "").strip()

    @property
    def signatures_aligned(self) -> bool:
        return bool(self.ann_sig) and self.ann_sig == self.embed_sig

    def index_fresher_than_db(self) -> bool | None:
        """索引对 mtime 是否整体新于库（main 库文件与 -wal 取大者；两枚索引
        文件取旧者）。索引对或库文件任一缺席 ⇒ None（判不了 ⇒ 不算 no-op）。"""
        idx = _file_fact(self.index_path)
        order = _file_fact(self.order_path)
        db = _file_fact(self.db_path)
        if idx is None or order is None or db is None:
            return None
        wal = _file_fact(Path(f"{self.db_path}-wal"))
        db_mtime_ns = max(db["mtime_ns"], wal["mtime_ns"] if wal else 0)
        pair_oldest_ns = min(idx["mtime_ns"], order["mtime_ns"])
        return pair_oldest_ns > db_mtime_ns


def collect_state(db_path: Path, index_path: Path, order_path: Path) -> AnnState:
    """只读收集全部体检事实。读数口全部是主键点查 / O(1) / 单行探测，
    不构造 store（store 构造即 _ensure_schema 写库，dry-run 绝不走）。"""
    vk = _load_vk()
    keys = (
        ANN_SIG_KEY,
        EMBED_SIG_KEY,
        VECTOR_DIM_KEY,
        vk._EMBEDDED_COUNT_KEY,
        vk._EMBED_GENERATION_KEY,
        vk._ANN_ATTESTATION_KEY,
        vk._ANN_BUILD_CHECKPOINT_KEY,
        vk._ANN_MEMORY_SKIP_META_KEY,
    )
    state = AnnState(db_path=db_path, index_path=index_path, order_path=order_path)
    meta = _read_meta_map(db_path, keys)
    state.meta_ok = meta is not None
    state.meta = meta or {}
    state.chunk_count = _count_chunks(db_path)
    state.free_bytes = vk._available_physical_memory_bytes()
    # 维数三级：库内 vector_dim 行 → blob 长度探测 → 保守假设（bge-m3=1024）。
    dim = _safe_int(state.meta.get(VECTOR_DIM_KEY))
    if not dim:
        dim = _blob_probe_dim(db_path) or 0
    state.dim = dim or vk._ANN_BUILD_ASSUME_DIM
    # 规模上界两级：完备性计数戳 → MAX(rowid)（_estimate_rebuild_scale 同序）。
    state.scale = _safe_int(state.meta.get(vk._EMBEDDED_COUNT_KEY)) or _max_rowid(db_path)
    state.demand_bytes = vk._ann_build_demand_bytes(state.scale, state.dim)
    return state


def _safe_int(raw: str | None) -> int | None:
    try:
        return int(str(raw or "").strip())
    except (TypeError, ValueError):
        return None


def _json_row(raw: str | None) -> dict | None:
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _sig_head(value: str) -> str:
    """长签名（端点+模型名拼接）压短上屏；空值显式点名，不冒充对齐。"""
    trimmed = (value or "").strip()
    if not trimmed:
        return "（空）"
    return trimmed if len(trimmed) <= 40 else f"{trimmed[:36]}…（{len(trimmed)} 字）"


def _gib(value: int | None) -> str:
    return "无法测量" if value is None else f"{value / 1024**3:.2f}GiB"


def print_report(state: AnnState) -> None:
    """人话报告：结论一句 + 每个事实单独一行中文标签（pre_restart_check 口径）。"""
    vk = _load_vk()
    print(f"库: {state.db_path}")
    print(f"ANN 对: {state.index_path.name} + {state.order_path.name}")
    if not state.meta_ok:
        print("knowledge_meta: 读不出（库缺席或表未建）——无从判定，绝不猜")
    print(f"embedding_signature: {_sig_head(state.embed_sig)}")
    print(f"ann_signature:       {_sig_head(state.ann_sig)}")
    if state.signatures_aligned:
        print("签名判定: 已对齐（ann == embedding）")
    else:
        print("签名判定: 未对齐（载入端将拒用 ANN ⇒ 每问回落暴力扫描）")
    print(f"chunk 总数（COUNT(*)）: {state.chunk_count if state.chunk_count is not None else '读不出'}")
    stamp = _safe_int(state.meta.get(vk._EMBEDDED_COUNT_KEY))
    print(f"完备性计数戳（{vk._EMBEDDED_COUNT_KEY}）: {stamp if stamp is not None else '无'}")
    generation = _safe_int(state.meta.get(vk._EMBED_GENERATION_KEY))
    print(f"嵌入代次（{vk._EMBED_GENERATION_KEY}）: {generation if generation is not None else '无（按 0 判）'}")
    for label, name in (("索引", state.index_path), ("序列表", state.order_path)):
        fact = _file_fact(name)
        if fact is None:
            print(f"{label}文件: 缺席（{name.name}）")
        else:
            print(
                f"{label}文件: {fact['size']:,} B, mtime={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(fact['mtime']))}"
            )
    attestation = _json_row(state.meta.get(vk._ANN_ATTESTATION_KEY))
    if attestation is None:
        print("代际证明（ann_pair_attestation）: 无（旧版存量产物形态）")
    else:
        print(
            "代际证明: ntotal={ntotal} count={count} signature={signature} "
            "embed_generation={eg}".format(
                ntotal=attestation.get("ntotal"),
                count=attestation.get("count"),
                signature=_sig_head(str(attestation.get("signature") or "")),
                eg=attestation.get(vk._ATTEST_EMBED_GENERATION_FIELD),
            )
        )
    checkpoint = _json_row(state.meta.get(vk._ANN_BUILD_CHECKPOINT_KEY))
    wip_index, wip_order = (
        state.index_path.with_name(f".wip-{state.index_path.name}"),
        state.order_path.with_name(f".wip-{state.order_path.name}"),
    )
    if checkpoint is None and not wip_index.exists() and not wip_order.exists():
        print("断点续传检查点: 无（干净态）")
    else:
        if checkpoint is None:
            print("断点续传检查点: meta 行缺席")
        else:
            print(
                "断点续传检查点: 已装 {wip_vectors} 条, last_rowid={last_rowid}, "
                "embed_generation={eg}, at_unix={at}".format(
                    wip_vectors=checkpoint.get("wip_vectors"),
                    last_rowid=checkpoint.get("last_rowid"),
                    eg=checkpoint.get("embed_generation"),
                    at=checkpoint.get("at_unix"),
                )
            )
        for wip in (wip_index, wip_order):
            print(f"半成品: {'在场 ' + wip.name if wip.exists() else '缺席 ' + wip.name}")
        print("（下次实跑将按库内六道判据自动续跑或丢弃重跑）")
    skip = _json_row(state.meta.get(vk._ANN_MEMORY_SKIP_META_KEY))
    if skip is not None:
        print(
            "内存门留痕: 连续被挡 {cs} 次 / 累计 {ts} 次（上次 available={av} required={rq}）".format(
                cs=skip.get("consecutive_skips"),
                ts=skip.get("total_skips"),
                av=skip.get("available"),
                rq=skip.get("required"),
            )
        )
    fresher = state.index_fresher_than_db()
    if fresher is None:
        print("幂等门预判: 索引对缺席，判不了（不构成 no-op）")
    else:
        print(f"幂等门预判: 索引对 {'新于' if fresher else '不新于'}库 mtime")
    print(f"空闲物理内存: {_gib(state.free_bytes)}")
    print(
        f"重建预估内存: {_gib(state.demand_bytes)}"
        f"（规模上界 {state.scale if state.scale is not None else '未知'} 条 × dim={state.dim}，"
        "库内需求式现算；入口另有 8.5GiB 地板门）"
    )
    print(
        "附注: 本脚本对齐的是库内 embedding_signature；若模型/端点指纹本身已换而库未重嵌，"
        "正解是 knowledge-sync 全链重嵌。"
    )


# ---------------------------------------------------------------------------
# 实跑（三道门 + 库内机件重建 + 失败回滚）
# ---------------------------------------------------------------------------


def _probe_available_bytes() -> int | None:
    """内存探针的软缝：测试从这里注入读数；生产直通库内单一探针实现。"""
    return _load_vk()._available_physical_memory_bytes()


def _backup_live_pair(state: AnnState) -> list[tuple[Path, Path]]:
    """写前把旧索引对改名 ``.bak-<UTC 时刻>`` 并登记（返回旧→新映射）。
    任一枚改名失败（典型：bot 正 mmap 持有）⇒ 先回滚已改的那枚再拒绝。"""
    stamp = time.strftime(_BAK_STAMP_FMT, time.gmtime())
    moved: list[tuple[Path, Path]] = []
    for path in (state.index_path, state.order_path):
        if not path.exists():
            continue
        target = path.with_name(f"{path.name}.bak-{stamp}")
        try:
            path.rename(target)
        except OSError as exc:
            print(f"[备份失败] {path} → {target}：{exc}", file=sys.stderr)
            print("（典型原因：bot 进程正持有索引 mmap——先停 bot 再实跑）", file=sys.stderr)
            _restore_backups(moved, live_absent_guard=False)
            raise SystemExit(2) from exc  # 前置不可用（文件被占用），非内存门
        moved.append((path, target))
        print(f"[备份登记] {path.name} → {target.name}（{target.stat().st_size:,} B，旧索引保留未删）")
    return moved


def _restore_backups(moved: list[tuple[Path, Path]], *, live_absent_guard: bool = True) -> None:
    """失败回滚：.bak 改名回线上名。live_absent_guard=True 时只在线上名
    空缺时才回（绝不顶掉重建刚发布的新代）；回滚自身失败就地大声报错。"""
    for live, bak in reversed(moved):
        if live_absent_guard and live.exists():
            print(f"[回滚跳过] {live.name} 已被新代占用，.bak 保留在原处（人工处置）")
            continue
        try:
            bak.rename(live)
            print(f"[回滚完成] {bak.name} → {live.name}")
        except OSError as exc:
            print(f"[回滚失败·需人工] {bak.name} → {live.name}：{exc}", file=sys.stderr)


class _RebuildOnlyProvider:
    """重建专用占位 provider：只声明维数（供需求估算），绝不执行嵌入——
    重建只消费库内已有向量，谁要在重建链上嵌新文本就该当场炸（fail-closed，
    不许静默走网络）。"""

    def __init__(self, dimensions: int) -> None:
        self.dimensions = int(dimensions)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(
            "rebuild_ann_index 只重建既有向量的索引，不做任何嵌入调用"
            "（补嵌请走 knowledge-sync 全链）"
        )


def run_rebuild(db_path: Path, index_path: Path, order_path: Path, *, force: bool) -> int:
    """实跑：三道门 → 备份 → 库内机件全量重建 → 报告/回滚。"""
    vk = _load_vk()
    state = collect_state(db_path, index_path, order_path)
    print_report(state)
    print("=== 实跑开始（三道门） ===")

    # 门①幂等门：签名已对齐且索引比库新 ⇒ no-op（先判最便宜、零风险的一门）。
    if not force and state.signatures_aligned and state.index_fresher_than_db():
        print(
            "no-op：签名已对齐且索引对 mtime 新于库 mtime（缺省不重建；确要强制重建加 --force）"
        )
        return 0

    # 门②前置可用性：embedding_signature 为空 ⇒ 无从对齐（重建会把空串盖上
    # ann_signature，制造新的错位），fail-closed。
    if not state.embed_sig:
        print(
            f"[拒绝] 库内 {EMBED_SIG_KEY} 为空：没有可对齐的指纹。"
            "新库首轮请走 knowledge-sync 全链（补嵌 + 建索引 + 落签名）。",
            file=sys.stderr,
        )
        return 2

    # 门③内存入口门：8.5 GiB 地板（fail-closed：探针取不到同样拒），
    # 另按库内需求式预检一次——两道都过才动备份的手。
    free = _probe_available_bytes()
    if free is None:
        print(
            f"[拒绝] 可用物理内存无法测量（探针不可判定）：按 fail-closed 不开火。"
            f"入口地板 {_gib(MIN_FREE_BYTES)}，需求式预估 {_gib(state.demand_bytes)}。",
            file=sys.stderr,
        )
        return 3
    if free < MIN_FREE_BYTES:
        print(
            f"[拒绝] 空闲物理内存 {_gib(free)} < 入口地板 {_gib(MIN_FREE_BYTES)}"
            f"（历史内存门 8.44GiB 取整）；需求式预估 {_gib(state.demand_bytes)}。"
            "等空闲内存回到门槛之上再跑；什么都没动。",
            file=sys.stderr,
        )
        return 3
    if free < state.demand_bytes:
        print(
            f"[拒绝] 空闲物理内存 {_gib(free)} < 需求式预估 {_gib(state.demand_bytes)}"
            f"（{state.scale if state.scale is not None else '未知'} 条 × dim={state.dim}）；"
            "什么都没动。",
            file=sys.stderr,
        )
        return 3

    moved = _backup_live_pair(state)

    # 重建本体＝库内既有机件：签名取库内 embedding_signature（发布点据此把
    # ann_signature 盖回对齐值）；auto_reset=False（运维脚本永不因指纹清空
    # 向量）；进度按节流打印。
    expected = state.scale
    step = max(8192, expected // 20) if expected else 32768
    next_mark = {"at": step}

    def _on_progress(done: int) -> None:
        if done >= next_mark["at"]:
            print(f"  … 已装 {done}/{expected if expected else '?'} 条")
            next_mark["at"] = done + step

    store = vk.SqliteVectorKnowledgeStore(
        db_path=str(db_path),
        embed_provider=_RebuildOnlyProvider(state.dim),
        signature=state.embed_sig,
        auto_reset=False,
        ann_index_path=str(index_path),
        ann_order_path=str(order_path),
    )
    try:
        result = store.build_ann_index(on_progress=_on_progress)
    except Exception as exc:  # noqa: BLE001 - 异常也要先回滚再上报
        print(f"[重建异常] {type(exc).__name__}: {exc}", file=sys.stderr)
        _restore_backups(moved)
        return 5
    if not result.get("built"):
        print(
            f"[未发布] reason={result.get('reason')} resumed_from={result.get('resumed_from', 0)} "
            f"checkpoint_dropped={result.get('checkpoint_dropped_reason', '')!r}——旧索引对已回滚复原。",
            file=sys.stderr,
        )
        _restore_backups(moved)
        return 4

    # 成功收尾：现读回新签名对 + 文件清单（含 .bak 家属）。
    pair = _read_signature_pair(db_path)
    new_ann = pair[0] if pair else ""
    new_embed = pair[1] if pair else ""
    print(f"[完成] vectors={result.get('vectors')} dim={result.get('dim')} "
          f"resumed_from={result.get('resumed_from', 0)}")
    print(f"旧签名对: ann={_sig_head(state.ann_sig)} | embedding={_sig_head(state.embed_sig)}")
    print(f"新签名对: ann={_sig_head(new_ann)} | embedding={_sig_head(new_embed)}")
    if new_ann and new_ann == new_embed:
        print("对齐判定: 已对齐（ann == embedding）")
    else:
        print("[异常] 重建已发布但两签名仍不对齐——请把这段输出原样上报，不要静默重跑。")
    print("索引文件清单:")
    for fact_path in (index_path, order_path):
        fact = _file_fact(fact_path)
        print(f"  {fact_path.name}: {fact['size']:,} B" if fact else f"  {fact_path.name}: 缺席！")
    for _, bak in moved:
        bak_fact = _file_fact(bak)
        if bak_fact is not None:
            print(f"  {bak.name}: {bak_fact['size']:,} B（旧代备份）")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rebuild_ann_index",
        description="FAISS ANN 知识索引运维重建入口（dry-run 体检 / 三道门实跑 / 失败自动回滚）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "退出码：0 成功或无害 no-op；2 前置不可用；3 内存门拒绝；"
            "4 重建未发布（已回滚）；5 异常（已尽力回滚）。\n"
            "实跑建议在停 bot 后执行：bot 持有索引 mmap 时备份改名会被拒（fail-closed）。\n"
            "断点续跑：中途收火/异常后重跑同一命令，自动从库内检查点续装（复用 S201 机件）。"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只读体检：打印签名对齐状态/chunk 总数/索引与检查点状态/空闲内存/重建预估内存，零数据写入",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="越过幂等门（签名已对齐且索引比库新时也强制重建）；内存门不随之越",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="",
        metavar="PATH",
        help=f"知识库 SQLite 路径（缺省：env/.env 的 {DEFAULT_DB_ENV}，"
        f"再缺省 {DEFAULT_DB_REL} 经 runtime_paths 重映射到运行数据根）",
    )
    parser.add_argument(
        "--index",
        type=str,
        default="",
        metavar="PATH",
        help="FAISS 索引文件路径（缺省随库名派生：<stem>_embeddings→<stem>_faiss.index）",
    )
    parser.add_argument(
        "--order",
        type=str,
        default="",
        metavar="PATH",
        help="序列表 order.json 路径（缺省随库名派生：<stem>_faiss.order.json）",
    )
    args = parser.parse_args(argv)

    try:  # 中文输出在 GBK 控制台的兜底：编码换 UTF-8、不可编码字符替换不炸。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001, S110 - reconfigure 不可用不影响主流程（GBK 控制台兜底）
        pass

    db_path = Path(args.db).expanduser().resolve() if args.db else _dotenv_default_db()
    if not db_path.is_file():
        print(f"[拒绝] 知识库不存在：{db_path}（用 --db 指名，或先跑 knowledge-sync 建库）", file=sys.stderr)
        return 2
    index_path, order_path = default_pair_paths(db_path)
    if args.index:
        index_path = Path(args.index).expanduser().resolve()
    if args.order:
        order_path = Path(args.order).expanduser().resolve()

    try:
        if args.dry_run:
            state = collect_state(db_path, index_path, order_path)
            print_report(state)
            return 0
        return run_rebuild(db_path, index_path, order_path, force=args.force)
    except RuntimeError as exc:  # _load_vk 导入失败等前置不可用（退出码 2）
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
