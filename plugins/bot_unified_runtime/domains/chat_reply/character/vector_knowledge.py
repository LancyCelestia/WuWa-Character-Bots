from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import struct
import time

try:
    import numpy as np
except Exception:  # noqa: BLE001 - numpy 可选，缺失回退纯 Python 余弦。
    np = None  # type: ignore[assignment]

try:
    import faiss
except Exception:  # noqa: BLE001 - faiss 可选，缺失回退 numpy 暴力检索。
    faiss = None  # type: ignore[assignment]
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from math import isnan, sqrt
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from plugins.bot_unified_runtime.contracts import KnowledgeChunk
from plugins.bot_unified_runtime.domains.chat_reply.character.documents import (
    load_character_document,
)

_EMBED_BATCH_SIZE = 10  # 百炼 qwen3.7 上限 20 条、v4 上限 10 条，取 10 两者都兼容。
_MIN_CHUNK_CHARS = 120

# --- BM25 关键词通道 + RRF 混合融合参数 ---------------------------------------
# FTS5 trigram 只能匹配 >=3 字符的 MATCH 词；1~2 字符词退化为 title LIKE。
_FTS_TABLE_NAME = "knowledge_chunks_fts"
_FTS_SIGNATURE_KEY = "fts_signature"
_FTS_CREATE_SQL = (
    f"CREATE VIRTUAL TABLE {_FTS_TABLE_NAME} USING fts5("
    "chunk_id UNINDEXED, title, content, tokenize='trigram'"
    ")"
)
_FTS_MIN_MATCH_CHARS = 3
_RRF_K = 60.0  # RRF 平滑常数：k 越大排名越平滑，越不容易被单一通道霸榜。
_VECTOR_CANDIDATE_FACTOR = 4
_VECTOR_CANDIDATE_FLOOR = 20
_KEYWORD_CANDIDATE_FACTOR = 2

_SHORT_TERM_STOP_CHARS = frozenset("的是在了和与或吗呢么什么有没有只让被把从对向给将")
_MAX_PHRASE_TERMS = 16
_CJK_RE = re.compile(r"[一-鿿]+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9_]{3,}")
# 无任何关键词命中且向量最高余弦低于该阈值 -> 判定未命中（可经构造参数覆盖）。
_MISS_COSINE_THRESHOLD = 0.30

# --- 源族配额（per-source quota，2026-09-20）-----------------------------------
# 生产实测：人格库 knowledge_chunks 共 35479 块，其中人格本体两个 md 仅 373 块
# （1.05%），战双/鸣潮库街区百科两份转储 30802 块（86.8%），「历史上的今天」
# th-01…th-12 是 12 个独立 source_id（单源 327~387 块）。补嵌完成后向量通道全量
# 参战，RRF 融合的每轮槽位（BOT_KNOWLEDGE_TOP_K，生产=5）都可能被百科源洗掉，
# 人格向问题召不回人格设定。修法=选择层「归族 + 族上限 + 人格保留位」：
#   * 归族粒度必须族级而非 source_id 级——12 个 th-* 各自限量时合并仍可占满
#     全部槽位（实测陷阱），故 th-* 并为一个族；人格本体两文件并为 persona 族。
#   * 非 persona 族每族至多 cap 槽（软顶：全族 cap 内候选填不满时按融合序溢出
#     回填，纯百科查询的槽位收益零损失——回归锁见 tests/test_knowledge_source_quota.py）。
#   * persona 保留位仅当候选池中存在 persona 块时生效（选择层保证，不扩池：
#     池外召回是候选生成问题，超出本配额职责）。
_ON_THIS_DAY_SOURCE_RE = re.compile(r"^th-\d{1,2}$")
_ON_THIS_DAY_FAMILY = "on-this-day"
# 人格本体文件名 stem 前缀（守岸人_核心知识 / 守岸人_人格与表达规范）。
_PERSONA_SOURCE_PREFIX = "守岸人"
_PERSONA_FAMILY = "persona"
# 溢出回填也不越 cap 的族：on-this-day（th-01…th-12 并族）。12 源同族是
# 本域实测陷阱正主，软顶（拿满槽优先）对它反向——语料级锁
# test_th_family_cap_holds_in_corpus。
_QUOTA_HARD_CAP_FAMILIES = frozenset({_ON_THIS_DAY_FAMILY})


def _quota_family_cap(limit: int) -> int:
    """非 persona 族上限：ceil(top_k/2)（5→3，8→4）。"""
    return max(1, (int(limit) + 1) // 2)


def _quota_persona_reserved(limit: int) -> int:
    """persona 保留槽：min(2, max(1, top_k//2))（5→2，4→2，8→2）。"""
    return min(2, max(1, int(limit) // 2))


def _source_family(source_id: str) -> str:
    """source_id → 族名：th-* 并族、守岸人* 归 persona、其余源各自一族。"""
    sid = str(source_id or "")
    if sid.startswith(_PERSONA_SOURCE_PREFIX):
        return _PERSONA_FAMILY
    if _ON_THIS_DAY_SOURCE_RE.match(sid):
        return _ON_THIS_DAY_FAMILY
    return sid


def _select_within_source_quota(
    ranked_ids: list[str],
    family_of: dict[str, str],
    limit: int,
    promotable_persona: set[str] | None = None,
    hard_cap_families: frozenset[str] = frozenset(),
) -> list[str]:
    """在融合排序上做族配额选择，返回仍按融合序排列的选中 id。

    三段式：A) 按融合序填槽，persona 族不封顶、其余族受 cap；
    B) persona 选中数不足保留位时，从队尾淘汰最弱的非 persona 块逐个补位——
      仅提升 ``promotable_persona`` 内的块（有相关性证据：关键词/词条通道
      命中，或向量余弦过本库低置信阈值），防止 35k 级池子里偶然的零相关
      persona 块被硬塞进每个查询；None=不筛（纯函数单测用）；
    C) 仍不足 limit 时（族候选稀少的单源查询）对余量溢出回填，cap 让位于
    「拿满槽」——保证纯百科查询零退化。
    """
    limit = max(0, int(limit))
    if limit <= 0:
        return []
    cap = _quota_family_cap(limit)
    reserved = _quota_persona_reserved(limit)
    counts: dict[str, int] = {}
    selected: list[str] = []
    seen: set[str] = set()
    primary: set[str] = set()  # A/B 段选中块（区别于 C 段溢出回填块）
    persona_taken = 0
    for chunk_id in ranked_ids:
        if len(selected) >= limit:
            break
        family = family_of.get(chunk_id, chunk_id)
        if family == _PERSONA_FAMILY:
            persona_taken += 1
        elif counts.get(family, 0) >= cap:
            continue
        counts[family] = counts.get(family, 0) + 1
        selected.append(chunk_id)
        seen.add(chunk_id)
        primary.add(chunk_id)
    persona_pool = [
        chunk_id
        for chunk_id in ranked_ids
        if family_of.get(chunk_id, chunk_id) == _PERSONA_FAMILY
        and (promotable_persona is None or chunk_id in promotable_persona)
    ]
    want = min(reserved, len(persona_pool))
    while persona_taken < want:
        promote = next((cid for cid in persona_pool if cid not in seen), None)
        evict = next(
            (
                cid
                for cid in reversed(selected)
                if family_of.get(cid, cid) != _PERSONA_FAMILY
            ),
            None,
        )
        if promote is None or evict is None:
            break
        selected.remove(evict)
        seen.discard(evict)
        primary.discard(evict)
        counts[family_of.get(evict, evict)] = counts.get(
            family_of.get(evict, evict), 0
        ) - 1
        selected.append(promote)
        seen.add(promote)
        primary.add(promote)
        persona_taken += 1
    if len(selected) < limit:
        for chunk_id in ranked_ids:
            if len(selected) >= limit:
                break
            if chunk_id in seen:
                continue
            family = family_of.get(chunk_id, chunk_id)
            if (
                family in hard_cap_families
                and family != _PERSONA_FAMILY
                and counts.get(family, 0) >= cap
            ):
                # 硬顶族（on-this-day）溢出回填也不越 cap——12 源并族陷阱
                # 的正主；其余族 cap 让位于「拿满槽」。宁缺槽也绝不放行，
                # 「拿满槽优先」的最终兜底属于调用方职责（那里看得见池外
                # 弱证据候选，本函数看不到）。
                continue
            counts[family] = counts.get(family, 0) + 1
            selected.append(chunk_id)
            seen.add(chunk_id)
    rank_of = {chunk_id: index for index, chunk_id in enumerate(ranked_ids)}
    # 输出序三段制（不再是纯融合序）：cap 内主选非 persona → persona 全部
    # （保留位钉在尾部 reserved 区，WEAK persona 排在其弱 rank 上不会沉到
    # 溢出块之后）→ 溢出回填非 persona。纯融合序会把弱证据 persona 排到
    # 被 cap 淘汰的百科块之后，而下游 MergedKnowledgeRetriever 轮转里
    # 流内第 5 位永远进不了提示词前 8——保留位必须在**流内位置**上成立，
    # 不只是在集合上（语料级锁 test_merged_prompt_projection 实锤）。
    def _order_key(chunk_id: str) -> tuple[int, int]:
        family = family_of.get(chunk_id, chunk_id)
        if family == _PERSONA_FAMILY:
            bucket = 1
        elif chunk_id in primary:
            bucket = 0
        else:
            bucket = 2
        return (bucket, rank_of.get(chunk_id, len(rank_of)))

    selected.sort(key=_order_key)
    return selected

# sync_chunks 源级同步台账（knowledge_meta key 前缀）：按 (mtime,size) 精确
# 删除「曾同步过、已移出清单」的源，取代旧的 `NOT IN (清单)` 全集删除。
_SOURCE_SIG_KEY_PREFIX = "sync_source_sig:"

# 删除侧绝对量闸的启用下限（见 sync_chunks 守卫 C）：台账少于这个源数量时
# 「摘掉一个文件」本身就是多数派，属日常操作而非配置漂移，不设闸。
_MASS_DELETE_GATE_MIN_LEDGER = 4

# 文档台账的时间元数据列（列名是与 Crawl Wiki 导出层的契约，不得自创别名）：
# 语料行的 `updated_at`（上游站点最后编辑时间）→ source_updated_at，
# `crawled_at`（本地抓取落盘时间）→ crawl_at。NULL=本库从未写过该文档的
# 时间元数据（首晚回填据此判定），''=上游确实没有可信时间值（非 MediaWiki 系）。
_DOC_METADATA_COLUMNS = ("source_updated_at", "crawl_at")


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把文本批量编码为等长浮点向量；失败可返回空列表或抛异常。"""
        ...


@dataclass(frozen=True)
class _EmbeddingChain:
    """一个 OpenAI-compatible embeddings 服务端 + 其模型回退列表。"""

    base_url: str
    models: tuple[str, ...]
    api_key: str = ""
    dimensions: int | None = None
    timeout_seconds: float = 15.0


def _parse_model_list(model: str | list[str]) -> list[str]:
    if isinstance(model, str):
        parts = [part.strip() for part in model.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in model if str(part).strip()]
    return parts


# 单文本查询嵌入 memo：聊天检索热路径（每条消息至少人格库+kb_wiki 库各一次）
# 对同一 query 的重复嵌入跨库去重；TTL 过后自然失效，不做逐条淘汰。
_QUERY_EMBED_MEMO: dict[tuple[str, str], tuple[float, list[list[float]]]] = {}
_QUERY_EMBED_MEMO_LOCK = threading.Lock()
_QUERY_EMBED_MEMO_TTL_SECONDS = 60.0
_QUERY_EMBED_MEMO_MAX_ENTRIES = 256


def _query_embed_memo_get(key: tuple[str, str]) -> list[list[float]] | None:
    now = time.monotonic()
    with _QUERY_EMBED_MEMO_LOCK:
        hit = _QUERY_EMBED_MEMO.get(key)
    if hit is None or now - hit[0] >= _QUERY_EMBED_MEMO_TTL_SECONDS:
        return None
    return hit[1]


def _query_embed_memo_put(key: tuple[str, str], vectors: list[list[float]]) -> None:
    with _QUERY_EMBED_MEMO_LOCK:
        if len(_QUERY_EMBED_MEMO) >= _QUERY_EMBED_MEMO_MAX_ENTRIES:
            _QUERY_EMBED_MEMO.clear()
        _QUERY_EMBED_MEMO[key] = (
            time.monotonic(),
            [list(vector) for vector in vectors],
        )


def reset_query_embed_memo() -> None:
    """清空查询嵌入 memo（测试用）。"""
    with _QUERY_EMBED_MEMO_LOCK:
        _QUERY_EMBED_MEMO.clear()


# ANN 重建流式读取向量批大小（2048×1024 维 ≈ 8MB/批，替代全量驻留）。
_ANN_BUILD_BATCH_SIZE = 2048
# 检索向量缓存流式读取批大小（R3 停摆批）：旧实现全表 fetchall 会把
# vector_json 文本与 vector_blob 一起物化（kb_wiki 23.8 万块、库文件
# 5.7GB → 进程内存 GB 级尖峰 + 分钟级 JSON 解析，且发生在检索锁内）。
_VECTOR_CACHE_LOAD_BATCH_SIZE = 2048

# --- ANN 原子发布 / 跨进程互斥 -------------------------------------------------
# 见 build_ann_index / _publish_ann_pair：索引与序列表必须成对换入，且写入
# 全程不得让读者看到半写文件。logger 供"检测到外部换代/拒写"结构化告警用。
logger = logging.getLogger(__name__)

# 成对代际证明落在 knowledge_meta（复用 SQLite 自身的跨进程写锁做提交点，
# 不再引入第二个状态文件；键名与既有 ann_signature 同族）。
_ANN_ATTESTATION_KEY = "ann_pair_attestation"
_ANN_LOCK_SUFFIX = ".build.lock"
# 抢锁只做短等待：抢不到即说明另一进程正在重建，本进程让路比硬排队好
# （重建是分钟级任务，串行等待会让 smoke/knowledge-sync 双双挂死）。
_ANN_LOCK_TIMEOUT_SECONDS = 3.0
_ANN_LOCK_POLL_SECONDS = 0.1

# --- ANN 完备性闸（task #47）--------------------------------------------------
# 代际签名只证明「在这个模型指纹下建过索引」，证明不了「索引装得下全部已嵌入
# 行」：embedding_signature 与 ann_signature 存的都是 self.signature（模型/端点
# 指纹），补嵌再多行也不动它俩。2026-09-21 实弹即此——两签名逐字节相等，体检
# 全绿，而磁盘上的 `.index` 停在 09-14 那一代，SQLite 侧 35479 行只嵌了
# 24379 行还没进索引，新内容对向量通道永久隐身。`ntotal == len(order)` 那道
# 成对终检同样救不了：两个文件是同代，一起旧，彼此当然对得上。
# 修法 = 在提交点盖一枚「本代索引实际装了几条向量」的计数戳，唯一写点补嵌时
# 同事务把戳推高，载入时拿 index.ntotal 去比这个戳：短装即判索引不可用，回落
# 既有暴力通道（_vector_candidates → numpy 矩阵 → _brute_candidates_python），
# 并出结构化告警，两个数字同屏点名。
# 戳绝不能用现算的 `SELECT COUNT(*) ... WHERE vector_json IS NOT NULL` 替代：
# 该查询在那张表实测 23.8s（JSON 列扫描），不许进载入路径。
# 戳的精确语义 = 「本代索引至少该装多少条向量」的**上界**：权威值只在提交点落
# （恰等于 ntotal），此后只由唯一写点单向上推。删掉已嵌行不会把戳拉低 ⇒ 戳可能
# 虚高，而虚高只会多拒一次（回落暴力 = 慢而全），绝不会少拒一次——本判据的危险
# 方向（漏拒）在这个形态下结构上不可达。代价：full=True 换代语料到重建之前，
# 告警里的 expected 会把被删的行也算进去，读它当「索引该重建」的讯号即可，
# 不当它是精确行数（要精确数就用 stats()，那是离线口径）。
_EMBEDDED_COUNT_KEY = "ann_expected_vector_count"
# 允许的短装行数：0 = 一条都不许少。短装只可能来自「补嵌之后没重建」，而那
# 正是本闸要治的病，没有值得放行的良性来源。反向多出向量（ntotal > 戳）不算
# 短装——那是发布中途被杀的残态，索引本身是完整的，见 load_ann_index。
_ANN_COMPLETENESS_MAX_MISSING = 0

# --- 嵌入代次守卫（S159，2026-09-26 夜）---------------------------------------
# 上面那句「多出可容忍」在**同轮先删后嵌**时不成立：戳是标量，
# `ntotal >= stamp` 必然成立却不代表覆盖。今晚生产实测（changed=328/removed=714/
# 嵌入 3,798）：戳随删除降到 740,267 < ntotal 740,996，一副**不含这 3,798 条新
# 向量、还留着死 id** 的 02:56 旧索引被当成可用——上一段注释里"危险方向结构上
# 不可达"的断言，被对称记账把戳降下去之后，从删除侧绕进来了。
# 守卫只补最便宜的一种证明：`ann_embed_generation` 数「已提交的嵌入批次数」，
# 与向量**同事务**在唯一写点 `_save_vectors` 推进；这一代"覆盖已证到哪一批"
# 记在代际证明的 `embed_generation` 字段（盖章点只有两处：publish 提交点与
# 集合级自证成立的重建纠偏——certify 补盖新戳**不**盖章，它只证库形真值）。
# 载入判定：当前代次 > 盖章代次 ⇒ 本代索引必然没装下发布后新增的嵌入 ⇒ 拒用，
# 两个数字同屏点名（coverage refused）。
# **删除不推进代次**：纯删除轮的覆盖形状是超集，按上面在册的「多出可容忍」设计
# 语义继续放行；守卫若把纯删除轮杀掉，就是把 `ae096fc` 的对称记账打回原形
# （反向锁 tests/test_kb_pricing_guard_fts_s159.py::
#   test_pure_deletion_round_still_accepted）。
# 也不许反过来拿落戳洗代次：`_stamp_expected_vector_count` 的任何调用都不推进、
# 不盖章（禁区锁 ::test_stamp_raise_cannot_launder_generation 与
# ::test_generation_funnel_structure_locks；ntotal 自我认证陷阱仍是
# test_ann_certify_prewarm 那枚同名锁）。
_EMBED_GENERATION_KEY = "ann_embed_generation"
# 代际证明里记「本代覆盖证到第几批」的字段名。旧代证明缺这个字段按 0 读
# （= 从未证过任何提交批次；配合同样缺 `ann_embed_generation` 行的存量库，
# 两侧都是 0 ⇒ 逐字节现状，无戳自愈链不受扰动）。
_ATTEST_EMBED_GENERATION_FIELD = "embed_generation"

# --- 活戳漂移纠偏（stamp-drift 波，2026-09-26）--------------------------------
# 上面那段「虚高只会多拒一次」的推理，在**零变更夜**是错的：虚高确实只会多拒，
# 可是没有任何一条路会把虚高洗掉——不重建（`unchanged_skip`）、重建线不达、
# `certify` 又被「活戳一字不碰」挡死 ⇒ 「多拒一次」变成「永久多拒」。2026-09-26
# 03:2x 生产实测就是这一格：戳 741,428 / 索引 ntotal 740,996 / 库侧已嵌入也是
# 740,996 ⇒ missing=432 恒红，每问付暴力扫描。
# 纠偏的取证方向与建闸时一致：**SQLite 的库侧真值裁决文件**，ntotal 与序列表只当
# 「这一代确实装满了每一行」的证据，绝不当落戳的数（拿 ntotal 落戳 = 短装索引自我
# 认证，`tests/test_ann_certify_prewarm.py` 的同名陷阱锁就是为此而设）。
# 落点也守住：戳的权威赋值点仍只有 `_publish_ann_pair`；纠偏只在**维护线程 + 显式
# opt-in**（kwarg / CLI）下改写一个已声明代次恒等于库真值的虚高值——不是第二根笔，
# 是把写歪的那一笔描回真值。
#: 集合级自证的内存地板。判据要流式读两份数十万项 id（一份 json、一份 SQLite 游标）
#: 并留一枚 set 做差集。**地板不是按需求定的，是按余量定的**：2026-09-26 在生产
#: 740,996 条上只读实测——库侧 COUNT 一段 327.7 s、集合级比对一段 240.2 s
#: （探针 `cw-ann-reconcile-measure2.py`，走 `_build_store` 同一构造口，零写入）；
#: 驻留峰值**没量到**（`K32GetProcessMemoryInfo` 在本机对这个伪句柄返回 0，读数 nan），
#: 所以这里不能声称"需求是 X MiB"。定到 1.5 GiB 的根据是余量而非需求：本机实测
#: 空闲物理内存跌到 1.6–2.5 GiB 区间时连着死机两次，而这一步再省也不省到那下面去。
#: 与 ANN 重建门同哲学（`_ANN_BUILD_MIN_AVAILABLE_BYTES` 同样是标定，不是需求），
#: 同 fail-closed：不够或不可判定都不动。
_ANN_STAMP_RECONCILE_MIN_AVAILABLE_BYTES = int(1.5 * 1024**3)
#: 集合级自证的项数上限：超过即拒并点名 `too_large_for_set_proof`，绝不"试一把大的"——
#: 把机器按死是这里唯一不可逆的后果，宁可由人显式越门。
_ANN_STAMP_RECONCILE_MAX_ITEMS = 2_000_000
_STAMP_RECONCILE_REASONS = (
    "stamp_matches_db_count",
    "stamp_below_db_count",
    "no_attestation",
    "attestation_self_inconsistent",
    "signature_mismatch",
    "pair_files_inconsistent",
    "index_does_not_cover_embedded_rows",
    "id_set_mismatch",
    "too_large_for_set_proof",
    "insufficient_memory",
    "memory_probe_unavailable",
    "db_error",
)

# --- ANN 重建内存门（S112，2026-09-26）----------------------------------------
# 为什么要有这道门：重建的常驻峰值由 FAISS 自己决定，不由批宽决定。
# `IndexHNSWFlat` 把全部向量另存一份私有 float32 数组（ntotal × dim × 4 B）+
# HNSW 链接表，分批 `add`（见 `_ANN_BUILD_BATCH_SIZE`）早在 R3 停摆批就把
# numpy 侧的一次性全量矩阵削平了，**削不掉这份必然驻留**。2026-09-25/26 夜间
# 实测可用物理内存低水位 1.62 GiB，而按 4,694 B/向量（下述实测常量）算，当前
# 规模的 wiki 库重建单份就要 ≈3.2 GiB；叠上"进程内重建时上一代索引仍在驻留"
# （缓存直到 `_publish_ann_pair` 末尾才 drop），真实峰值形状是"旧+新"两份。
# 在那样的机器上开火 = 把 bot 连人带库一起压死，比 09-22 的停摆更糟。
# 故开火前先量可用物理内存，不足即**不开火**：保留旧索引、留下三处痕迹
# （WARNING 日志 / knowledge_meta 观测行 / 经 kb-sync 既有告警 sink 出五要素卡）。
#
# 三件必须说清的语义（防止后来者把这当"让它绿"的开关）：
# ① 跳过**不**放行完备性闸——`_ANN_COMPLETENESS_MAX_MISSING` 一字未动，
#    闸照样拒用 ANN ⇒ 暴力扫描照旧，本门只是不许它以 OOM 的形态结束。
# ② 阈值是模块常量、不是 config 键（本仓先例：阈值类参数不轻易开新键），
#    要临时越过走 operator CLI 的显式旗标，不改生产配置面。
# ③ 探针取不到数 ⇒ 按「不可判定」处理，同样 fail-closed 不开火。
_ANN_BUILD_MIN_AVAILABLE_BYTES = int(4.5 * 1024**3)
# ^ S85 定的 go/no-go 经验合价（当时 bot 已驻留 3.53 GiB、空闲只剩 2.4–3.0 GiB
#   ⇒ 判"别开火"）——它是"旧代 + 新代 + 余量"在 n≈766k 那个点上的合价，不是
#   物理常数，也**不当需求价用、不是物理下限**：第一版当下限把 24 条向量的测试
#   重建也拒了（自曝账见席位报告 §5）。S118 收线后它只剩一个用途：被复算锁
#   tests/test_ann_memory_gate_s118.py::test_demand_model_reproduces_s85_calibration_at_766k
#   钉成"需求线性式在该标定点上确实落在这枚合价的合理带内"。
_ANN_BUILD_HEADROOM_RATIO = 4
# ^ 安全余量按需求的比例给（1/4；S112 旧名"观察余量"，S159 重定标时定为正式
#   身份）：它的用途是覆盖三件实测在册的事——①"量到"与"用完"之间爬虫还在写
#   同一台机器（S105 实测 10 分钟内可用内存 2.99 → 1.62 GiB），②旧代索引在
#   publish 前一直驻留（mmap 页可回收，但回收滞后于读数），③模型价自身是
#   斜率估计不是账。它的规模与重建本身同阶 ⇒ 必须是比例而不是常数。
_ANN_BUILD_MIN_HEADROOM_BYTES = 128 * 1024 * 1024
# ^ 比例项的下限：小库也要留一点余量，但不许留成一刀切的 1 GiB——
#   第一版正是那枚常数把 24 条向量的测试重建也判成"内存不足"、连带打红
#   tests/test_ann_certify_prewarm.py 一片（见席位报告 §5 自曝账）。
_ANN_BUILD_BATCH_SLACK_COPIES = 4
# ^ 批内 numpy 瞬时副本份数（batch_vectors 列表 / vstack / astype / 归一化除），
#   成本 = `_ANN_BUILD_BATCH_SIZE × dim × 4 B × 份数`，随维数与批宽派生，不写死。
_ANN_BUILD_MEASURED_BYTES_PER_VECTOR = 4694
# ^ 实测单位成本（S85 本机同参数两跑 RSS 斜率；与落盘口径 4,368 B/向量互验，
#   差值即分配器与构建期工作集）。
_ANN_BUILD_MEASURED_DIM = 1024
# ^ 上一条实测的维数基准（bge-m3）。单位成本按 dim 线性外推：
#   `dim × 4 + (4694 − 1024 × 4)`，在 dim=1024 处逐字节复现实测值。
_ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR = 176
# ^ `chunk_ids` 侧（列表 + `json.dumps` 文本 + `.encode()` bytes 同时在场）。
#   实测：从生产 order.json 取 93 条真 id，平均长 40 字符、单条
#   `sys.getsizeof` = 81 B，加列表指针 8 B、JSON 文本与编码 bytes 各 43 B
#   ⇒ 175 B/条，取 176 作上界。
_ANN_INDEX_BYTES_PER_DIM = 1
# ^ **索引存储位宽**（S181，2026-09-26 夜，用户裁定「执行乙」）：SQ8 = 每维 1 字节。
#   改这一枚之前它是 4（`IndexHNSWFlat` 的私有 float32 副本），那才是"740k 条
#   就要 3.2 GiB 常驻"的根源。依据是本轮离线对照实跑（60,400 条**生产真向量**、
#   400 条真查询、K=4、`METRIC_INNER_PRODUCT`、efConstruction=200/efSearch=64、
#   训练样本取 rowid 前 20,000 条）：
#     fp32 262.1 MB → SQ8 77.8 MB = **0.30 倍**，top-4 与 fp32 一致率 **0.9856**，
#     内积分数差均值 0.00029、最大 0.047；同口径 fp16 是 0.53 倍 / 0.9906。
#   交叉验证：262.1 MB ÷ 60,400 = 4,340 B/条，与现役生产索引文件
#   （3,236,774,162 B ÷ 740,996 = 4,368 B/条）互洽 ⇒ 外推到全库 SQ8 ≈ 0.97 GiB
#   （fp32 是 3.24 GiB）。**没量到的**：构建期峰值工作集（本机
#   `GetProcessMemoryInfo` 取数失败，探测里退化成 0）——所以倍增瞬态那一项下面
#   仍按"半份向量数组"的老规则随位宽同比缩放，不拿这次的峰值当依据。
#   代价如实记：1.4% 的 top-4 槽位与 fp32 不同（并列近邻换位）。要更保守就把这枚
#   改回 2（fp16）并同步换 `_ANN_INDEX_QUANTIZER_NAME`，一致率 0.9906。
_ANN_INDEX_QUANTIZER_NAME = "QT_8bit"
# ^ 与上一枚成对：量化器类型按**名字**在册，运行期从 `faiss.ScalarQuantizer` 取
#   （模块导入期 faiss 可能整体缺失 ⇒ 不能在模块级直接引用枚举成员）。两枚必须
#   同改，由 tests/test_ann_sq8_index_s181.py 逐枚钉住（名字与位宽不符即红）。
_ANN_INDEX_HNSW_M = 32
# ^ HNSW 连接数。fp32 时代写死在构造调用里，升格成常量是为了让"只换存储、不换
#   图结构"这件事有唯一落点（图参数一变，上面那份 0.30 倍/0.9856 的实测就作废）。
_ANN_INDEX_TRAIN_SAMPLE_VECTORS = 20_000
# ^ 量化器训练样本条数。`IndexHNSWSQ` 未 train 就 add 会当场抛 `is_trained`
#   （本轮实跑撞过），而 fp32 的 `IndexHNSWFlat` 不需要训练——这是换存储格式的
#   唯一新增硬前提。取数口径 = rowid 升序前 N 条（**与上面那份实测同一口径**，
#   所以 0.9856 这个数字已经含着"样本偏旧"的代价；改成随机抽样要先付一次全表扫）。
_ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM = 2
# ^ 倍增扩容瞬态副本的**每维字节数**（= 半份 `dim × 4` 向量数组：dim=1024 处
#   即 2,048 B/vec）。S118 合成 bench 实测：分批重建的**峰值**边际斜率
#   7,393 B/vec（20k→40k，PeakWorkingSetSize 口径），比稳态线性价
#   4,870 B/vec 高一截——高出的部分正是 `IndexHNSWFlat` 底层向量数组按
#   2 的幂 realloc 时"旧数组 + 新数组"同场的瞬态拷贝（在随机扩容边界上
#   期望值 ≈ 半份向量数组）。按维线性而不是写死 2,048：换维模型时这层
#   成本跟着 `dim × 4` 走。S85 当年用轮询 RSS 量到的 4,694 B/vec 是稳态
#   斜率，轮询会漏掉亚秒级尖峰；门比的是"可用物理内存够不够撑过整场
#   重建"，必须按**峰值**计价。复跑命令见 tests/test_ann_memory_gate_s118.py
#   模块 docstring（S118 报告 §1）。
_ANN_BUILD_SCALE_CALIBRATION_VECTORS = 766_126
# ^ 上面那枚 4.5 GiB 合价的**标定点**：S85 是在 766,126 条（当时 wiki 库的
#   实装向量数）上量出来的，不是通用物理常数。复算锁
#   tests/test_ann_memory_gate_s118.py::test_demand_model_reproduces_s85_calibration_at_766k
#   钉"需求式在这个点上与 S85 经验合价同带"。写死这层关系，是为了防止
#   后来者把 4.5 GiB 当门槛到处套（第一版就套错了）。
_ANN_BUILD_ASSUME_DIM = _ANN_BUILD_MEASURED_DIM
# ^ provider 未声明维数时的保守假设（生产即 bge-m3 的 1024）。
_ANN_BUILD_MEMORY_RECHECK_VECTORS = 32_768
# ^ 批间复检粒度（16 个构建批一次 stat，成本可忽略；重建是分钟级，
#   内存形状在这段时间里真的会变——只查一次的前置检查会被实况击穿）。
_ANN_MEMORY_SKIP_META_KEY = "ann_build_last_memory_skip"
# ^ 跳过留痕（观测面）：只存度量，不存磁盘路径。程序读者现算在两处——
#   ① 重启预检第 13 项 `ann_pair`（scripts/pre_restart_check.py 的
#   `inspect_ann_generation_pair`，只读点查此行并派生 MEMORY_SKIP 状态）；
#   ② kb-sync 告警话术（本模块把 `memory_gate` 度量随行交回，kb_wiki 拼五要素卡）。
#   S126 登记时"无任何程序读者"一格即缺①；①由 S141 补、本行注释跟随（S139）。
_ANN_MEMORY_SKIP_CONSECUTIVE_KEY = "consecutive_skips"
_ANN_MEMORY_SKIP_TOTAL_KEY = "total_skips"
# ^ 累计计数（S139 缺陷 4）：与跳过留痕同一枚 meta、同一批写点，**不另起一行账**
#   （第二枚键=第二本账，读者要跨两行对齐才知道"连续没连续"）。
#   语义：只数**未越门**的被挡轮（pre/midway 各算一轮）；publish 成功即清零
#   连续数（total 只增不减，保留历史总量）。清零写点唯一在 `_publish_ann_pair`
#   尾部（= 计数戳唯一权威赋值点同侧），跳过分支结构锁不许它碰落戳/发布动作。
#   越门轮裁定（S156 条 2 钉死）：**越门那一轮不算「被挡一次」**——人工放行
#   不是门又挡一夜，两枚计数对它**不加也不清**；越门本身照样记痕
#   （forced=True 行留作证据），且越门轮没走到 publish（被取消/建锁挡下）
#   时计数同样原样停在上一轮的值上。行为锁
#   tests/test_kb_ops_parked_three_s156.py::
#   test_forced_round_without_publish_neither_adds_nor_clears
#   （反证腿：越门分支若被注成"清零连续"，该场景判别值必翻转）。
_ANN_MEMORY_SKIP_ESCALATION_ROUNDS = 3
# ^ 「连续被挡 ⇒ 升格告警」阈值。依据不是手感，是三条在册实况：
#   ① 节拍——kb-sync 每日一轮（cron 23:40 + 启动补跑），"轮"≈"夜"；
#   ② 抖动尺度——S105 实测可用内存抖动是**十分钟级**（2.99 → 1.62 GiB），
#      一次被挡属"当夜水位"事件，次夜自愈是常态（今夜被挡、明夜重建成功
#      即清零，见上一条的清零语义）；
#   ③ 反例形态——2026-09-22 停摆的前置形态正是"拒用每轮一致却无人升账"
#      （SEAT-MAIN §1.2：戳 741,428/ntotal 740,996 恒红，每问付暴力扫描）。
#   连续 3 夜被挡已超出 ② 能解释的范围，落入 ③ 的积累形态 ⇒ 该升格；
#   代价上界是"水位真连坏 3 夜时多发一张 critical 卡"，方向是变严不是变松。
#   升格只改**告警面**（level warning→critical + 点名连续数），不改门判据：
#   门永远按当轮实测判定，绝不为"攒够 3 次"而提前放行或提前拒火。

# --- S159 计价重定标（2026-09-26 夜，用户裁定「甲」）--------------------------
# 今晚实况：前置门按上面这套线性价（740,267 条 × 6,918 B + 批副本 + 1/4 余量
# ≈ 6.00 GiB）在 11.55 GiB 可用下**本来放行**；死的是中途腿——
# `_ann_projected_requirement_bytes` 旧式把「首批实吃」按单位斜率线性外推到
# 剩余全部：复检在 32,768 条时 available 已掉 0.62 GiB ⇒ 单位价 20,310 B/vec
# ×剩余 707,499 ⇒ 要价 14.04 GiB，为实测峰值的 3.6 倍、线性价的 2.3 倍。
# 早期吃进为什么不能外推：重建的读链要把全部 vector_json 文本 + blob 过一遍
# SQLite 页缓存（≈24 KB/vec 的流经量），这部分是**可回收的缓存页**、不是私有
# 驻留；首批恰好摊到整场读链的冷缓存成本，单位价被顶到模型边际价的 2.9 倍。
# 新口径一行式：
#     剩余需求 = 已吃实账（available 开跑至今净掉，保守全额认账）
#              + 剩余条数的模型价（本节上方那套实测分解线性式，含 1/4 安全余量）
# 已吃的全认（方向保守，缓存页也认），未来的按模型记——不再外推首批斜率。
# 断路器的牙没摘：真吃超模型价时，每个复检窗（32,768 条）把新账加进要价，
# available 一旦撑不过「已吃 + 剩余模型价」当场收火（活性与反证双锁：
# tests/test_kb_pricing_guard_fts_s159.py::
#   test_midway_breaker_still_bites_when_really_eaten 及其反证腿、
#   test_midway_observed_leg_no_longer_extrapolates_early_slope）。
# 复算口径（要求②，全部可由本节常数重推，锁
# ::test_price_constants_documented_as_calibration）：
#   线性 = n × ( dim×4〔IndexHNSWFlat 私有 float32 副本〕
#               + dim×2〔倍增 realloc 瞬态，S118 bench 峰值边际实测〕
#               + (4,694 − 1024×4) = 598〔S85 实测：HNSW 链接表 + 分配余量〕
#               + 176〔chunk_ids 列表 + JSON 文本 + bytes 同场，实测上界〕)
#   批内副本 = 2048 × dim × 4 × 4
#   安全余量 = max(128 MiB, (线性 + 批副本) ÷ 4)
# 与实测对表：n=740,267、dim=1024 ⇒ 线性 4.77 GiB、总要价 ≈ 6.00 GiB；
# 实测两跑全量重建峰值 3.6–3.9 GiB（09-22 / 09-25 观测，简报输入）——模型价
# **高于**实测峰值，即本次重定标没有"把线性价偷偷调小"，降下去的只有那条
# 外推腿；「32 GiB 机器 10 GiB 空闲必须开火」在总要价 6.00 GiB 与中途 ≈ 5.3
# GiB 下同时成立（行为锁 ::test_gate_allows_fire_on_32gib_machine_at_10gib_free，
# 该锁同时钉「2 GiB 空闲仍拒」——门不许被重定标改成摆设）。
# 本节一切阈值都是**标定不是物理下限**：换模型、换维数、换机器就按同一式子
# 重量一遍；`_ANN_BUILD_MIN_AVAILABLE_BYTES` 只是 766k 标定点的历史合价展示位，
# 不当门用（第一版拿它当全局门槛的自曝账见其注释）。


def _resolve_ann_quantizer() -> Any | None:
    """按在册名字取 faiss 的量化器枚举成员。

    名字住在 `_ANN_INDEX_QUANTIZER_NAME` 而枚举成员**不在模块级取**：faiss 在本仓
    是可选依赖（导入失败时 `faiss is None`，见 `load_ann_index` 早退），模块级引用
    `faiss.ScalarQuantizer.QT_8bit` 会让整个模块导入就崩。取不到 ⇒ None = 不建索引，
    绝不悄悄退回 fp32（那会让位宽与价模型脱钩，是"两把尺"形态）。
    """
    if faiss is None or np is None:
        return None
    scalar_quantizer = getattr(faiss, "ScalarQuantizer", None)
    if scalar_quantizer is None:
        return None
    return getattr(scalar_quantizer, _ANN_INDEX_QUANTIZER_NAME, None)


def _read_vector_train_sample(
    connection: Any, *, dimension: int, limit: int
) -> Any | None:
    """量化器训练样本：rowid 升序前 ``limit`` 条**已嵌入**向量。

    口径与那 0.9856 一致率的实测完全一致（同一取法、同一维数过滤），所以这个数
    不是"理想抽样下的一致率"，它已经含着"样本偏旧"的代价。要改成随机抽样就得先
    扫一遍 4.5 GB 的向量列——那比省的内存还贵，故不做，并把边界写在常量注释里。
    """
    rows = connection.execute(
        "SELECT vector_blob FROM knowledge_chunks "
        "WHERE vector_blob IS NOT NULL LIMIT ?",
        (int(limit),),
    ).fetchall()
    matrices = []
    for row in rows:
        blob = row[0]
        if not blob:
            continue
        vector = np.frombuffer(blob, dtype=np.float32)
        if vector.size == int(dimension):
            matrices.append(vector)
    if not matrices:
        return None
    return np.ascontiguousarray(np.vstack(matrices), dtype=np.float32)


def _make_ann_index(dimension: int, *, connection: Any) -> Any | None:
    """建这一代用的 ANN 索引（S181：SQ8 量化存储，每维 1 字节）。

    换存储格式带来的**唯一新增硬前提**是训练：`IndexHNSWFlat` 不训练就能 add，
    `IndexHNSWSQ` 未训练就 add 当场抛 `is_trained`（本轮实跑撞过一次）。样本取不到
    ⇒ 返回 None，调用方按"本轮不建"收火——线上一字不动，比建一副半训练索引好。
    图参数（M / efConstruction）走 `_ANN_INDEX_HNSW_M`，不许在这里再写死第二份：
    那份 0.30 倍体积 / 0.9856 一致率的实测就钉在这个图形状上。
    """
    quantizer = _resolve_ann_quantizer()
    if quantizer is None:
        return None
    index = faiss.IndexHNSWSQ(
        int(dimension), quantizer, _ANN_INDEX_HNSW_M, faiss.METRIC_INNER_PRODUCT
    )
    if not index.is_trained:
        sample = _read_vector_train_sample(
            connection, dimension=int(dimension), limit=_ANN_INDEX_TRAIN_SAMPLE_VECTORS
        )
        if sample is None:
            return None
        index.train(sample)
    return index


def _available_physical_memory_bytes() -> int | None:
    """本机可用物理内存（字节）；取不到返回 **None = 不可判定**。

    Windows 走 `GlobalMemoryStatusEx`（`ctypes` 标准库，零新依赖）。这里刻意
    **不**走 `platform.freemem()` / `psutil.virtual_memory()`：那两处是宿主机
    遥测取数口，唯一真身在册 `domains/ops/host_metrics.py`，由
    `tests/test_host_metrics_single_source.py` 执法（该门的判据集合里
    `platform`/`psutil`/`winreg` 算读数点，本函数的 `ctypes` 不算）。
    本函数是**一个 go/no-go 判决的输入**，不是"宿主机状态"的第二真身；
    若要把它并进呈现链，正解是给 host_metrics 加一枚数值出口（见席位报告
    §6 第 3 条），而不是在这里第二次伸手摸机器。

    `ullAvailPhys` 是**可用物理内存**（不含页面文件余量）。这里刻意用它而不是
    commit 余量：S84 实测本机提交上限 84 GiB（页面文件很大）⇒ commit 口径永远
    "够"，而真正的代价是换页风暴，那正是今晚要拦的形态。
    """
    if os.name != "nt":
        # `getattr` 形态而非直写 `os.sysconf(...)`：Windows 的 `os` 没有
        # `sysconf`，mypy 按平台 stub 判 attr-defined 红（S112 首版就红在这一发，
        # S118 收线改掉）；运行时语义不变——取不到可调用对象即 None = 不可判定。
        sysconf = getattr(os, "sysconf", None)
        if not callable(sysconf):
            return None
        try:
            page = sysconf("SC_PAGE_SIZE")
            avail = sysconf("SC_AVPHYS_PAGES")
        except (ValueError, OSError, AttributeError):
            return None
        if not page or not avail or page < 0 or avail < 0:
            return None
        return int(page) * int(avail)
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys)
    except Exception:  # noqa: BLE001 - 探针失败=不可判定，由调用方 fail-closed。
        return None


@dataclass(frozen=True)
class _AnnMemoryVerdict:
    """内存门的判决（一次判定的全部可观测要素，日志/告警/meta 三处共用）。"""

    allowed: bool
    available_bytes: int | None
    required_bytes: int
    expected_vectors: int | None
    dim: int
    probe_failed: bool

    def as_meta(self) -> dict[str, Any]:
        """→ 可落 knowledge_meta 的观测字典（GiB 保留两位，不藏路径）。"""

        def _gib(value: int | None) -> str:
            return "unknown" if value is None else f"{value / 1024**3:.2f}GiB"

        return {
            "available": _gib(self.available_bytes),
            "required": _gib(self.required_bytes),
            "floor": _gib(_ANN_BUILD_MIN_AVAILABLE_BYTES),
            "headroom": _gib(_ANN_BUILD_MIN_HEADROOM_BYTES),
            "expected_vectors": self.expected_vectors,
            "dim": self.dim,
            "probe_failed": self.probe_failed,
        }


def _ann_build_batch_slack_bytes(dim: int) -> int:
    """批内 numpy 瞬时副本（派生量，不写死数字）。

    `_ANN_BUILD_BATCH_SIZE` 条 × 每条 `dim × 4 B` × `_ANN_BUILD_BATCH_SLACK_COPIES`
    份同时在场的副本（`batch_vectors` 列表 / `vstack` 输出 / `.astype(float32)`
    无条件拷 / 归一化除）。按维数派生 ⇒ 8 维测试替身不会被算成 1024 维的量。
    """
    return int(_ANN_BUILD_BATCH_SIZE) * max(int(dim), 1) * 4 * _ANN_BUILD_BATCH_SLACK_COPIES


def _estimate_rebuild_scale(store: SqliteVectorKnowledgeStore) -> int | None:
    """重建规模的上界估计（**必须是 O(1) 读数**，绝不上全列扫描）。

    两级来源，取先拿到的那个：
    ① 计数戳 `_stamped_expected_vector_count()`——knowledge_meta 单行主键点查，
       按 `:318-321` 的定义本就是**上界**（只升不降），拿上界估需求只会高估、
       只会多跳一次，方向与本仓「宁可慢而全，不可假绿」一致。
    ② 无戳（从未发布过一代的新库）⇒ `SELECT MAX(rowid)`：InnoDB 式 rowid 是
       单调插入计数，删除不回退 ⇒ 它是行数的上界，且走 B-tree 最右叶，O(1)。
       这一级存在的理由：**无戳 ≠ 免检**——一次全量重爬的首发重建恰是最大的一发
       （S115 实跑：6.87 GiB 语料 / 155,849 条向量在 5.56 GiB 可用下 RSS 触到
       10.24 GiB。S118 层分解已把这一发归因清楚：10.24 GiB ≈ 该库**全量
       JSON 文本 + 全量 Python list** 同场驻留的形状（65 KB/条量级），属
       读链一次性中间物；即便形态存疑，按上界估需求的保守方向不变）。
       缺了这一级，那道最该拦的门对本该拦的场景直接放行。
    两级都拿不到 ⇒ None（真·不可判定），由调用方退到活体下限（前置判一发
    `_ANN_BUILD_MIN_HEADROOM_BYTES + 批副本`，中途仍走 `_ann_live_floor_bytes`
    断路器——S118 接线，无戳不等于跑到一半没人看火）。
    """
    stamped = store._stamped_expected_vector_count()
    if stamped is not None and stamped > 0:
        return stamped
    try:
        with store._connect() as connection:
            row = connection.execute("SELECT MAX(rowid) FROM knowledge_chunks").fetchone()
    except sqlite3.Error:
        return None
    if row is None or row[0] is None:
        return None
    try:
        bound = int(row[0])
    except (TypeError, ValueError):
        return None
    return bound if bound > 0 else None


def _ann_build_demand_bytes(expected_vectors: int | None, dim: int) -> int:
    """本轮重建的内存需求估算（字节）。

    **全比例模型，不设绝对门槛。** 来自实测的形状：
    ① 单位成本 = `dim × 4 B`（`IndexHNSWFlat` 的私有 float32 向量副本，分批
       add 削不掉）+ 598 B/条图与分配余量 + `dim × 2` B/条倍增扩容瞬态副本
       （`_ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM`，S118 bench 峰值斜率实测）
       + 176 B/条 id 表（`chunk_ids` 列表与 `json.dumps` 文本、编码 bytes
       同时在场）。
    ② 安全余量按比例给（线性项的 1/4，见 `_ANN_BUILD_HEADROOM_RATIO` 注释的
       三件在册理由）：它天然与重建本身同阶，所以必须是比例而不是常数。
    ③ `_ANN_BUILD_MIN_AVAILABLE_BYTES`（4.5 GiB）**不当门用**：它是 S85 在
       n≈766,126 那个点上量出的合价，不是物理常数——第一版把它当全局门槛，
       结果 24 条向量的测试重建也被拒、连带打红 `tests/test_ann_certify_prewarm.py`
       一片（席位报告 §5 自曝账）。它与本式的关系由复算锁
       tests/test_ann_memory_gate_s118.py::test_demand_model_reproduces_s85_calibration_at_766k
       钉住：在标定点上两者同带。
    ④ 计价器打架一案已由 S118 实测结案（S112 半成版在此挂了一枚未定义的
       `_ANN_BUILD_UNIT_COST_DISPUTE_BYTES` 补贴，本席收线时移除）：
       S85 的 4,694 B/vec 是**稳态**斜率；S112/S115 apparent 的 ≈54 KB/vec 是
       **一次性全量读链中间物**（JSON 文本 22.7 KB + Python list 42.2 KB/条，
       S118 层分解实跑，whole-chain 77.7 KB/vec）——分批形态下这些中间物只在
       批内出现（O(2048) 条而非 O(n)）。分批重建**峰值**斜率实测 ≈ 7.4 KB/vec
       （bench 20k→40k 边际），已折进 ① 的 realloc 项；中途复检收口已改式为
       「已吃实账 + 剩余模型价」（S159 重定标，`_ann_projected_requirement_bytes`
       docstring 与上方「S159 计价重定标」常量块——旧「首批斜率×剩余全部」外推
       今晚把要价顶到 14.04 GiB = 实测峰值 3.6 倍，推导与复算口径全在那里）。
    """
    batch_slack = _ann_build_batch_slack_bytes(dim)
    if expected_vectors is None or expected_vectors <= 0:
        # 连行数的上界都拿不到（异常库形）⇒ 退到活体下限 + 中途断路器
        # （复检走 `_ann_live_floor_bytes`，S118 接线：无戳不等于免检）。
        return _ANN_BUILD_MIN_HEADROOM_BYTES + batch_slack
    storage = max(int(dim), 1) * _ANN_INDEX_BYTES_PER_DIM
    # 倍增扩容瞬态＝半份向量数组（S118 峰值口径；fp32 时 `_ANN_INDEX_BYTES_PER_DIM`
    # =4 ⇒ storage×2//4 = dim×2 = 2,048 B/条，与改前逐字节等价）。它**随位宽同比
    # 缩放**：SQ8 下 storage=dim×1 ⇒ 瞬态 dim×0.5。写死 2,048 会把量化后的价高估
    # 四倍，正是要避免的那类"门永远不许开火"。
    per_vector = (
        storage
        + storage * _ANN_BUILD_FAISS_REALLOC_BYTES_PER_DIM // 4
        + (_ANN_BUILD_MEASURED_BYTES_PER_VECTOR - _ANN_BUILD_MEASURED_DIM * 4)
    )
    linear = int(expected_vectors) * (per_vector + _ANN_BUILD_ID_TABLE_BYTES_PER_VECTOR)
    headroom = max(
        _ANN_BUILD_MIN_HEADROOM_BYTES,
        (linear + batch_slack) // _ANN_BUILD_HEADROOM_RATIO,
    )
    return int(linear + batch_slack + headroom)


def _ann_projected_requirement_bytes(
    remaining_vectors: int | None,
    dim: int,
    *,
    available_now: int | None,
    available_at_start: int | None,
    built_so_far: int,
) -> int:
    """中途复检的需求 = **已吃实账 + 剩余模型价**（S159 重定标，推导见常量块）。

    来历：S112 手里两把尺打架（S85 稳态 4.7 KB/条 vs S115 实跑 ≈67 KB/条），
    S118 把 67 KB/条归因成一次性全量读链中间物、把分批峰值 7.4 KB/条折进模型价，
    并接线了「实测斜率与模型价取大」的断路器。**但实测斜率不可线性外推**——
    2026-09-26 夜生产要价 14.04 GiB（= 实测峰值 3.9 GiB 的 3.6 倍）正是
    「首批 0.62 GiB ÷ 32,768 条 × 剩余全部」外推出来的：首批吃进以读链页缓存
    为主（可回收、不是未来每条都要重付的私有驻留），拿它当边际价 = 任何机器
    永远不许开火。新式两半各管各的：
    ① 已吃：`available_at_start - available_now` 全额认账（含缓存页，保守方向
       是多要价不是少要价）；
    ② 未吃：按 `_ann_build_demand_bytes` 的模型价记，不外推任何斜率。
    牙还在：真消费超模型价时，每个复检窗把超额并入①，available 撑不过
    ①+② 当场收火（活性+反证锁见 tests/test_kb_pricing_guard_fts_s159.py）。
    读数不可用（探针失败/一条未装）⇒ 退回纯模型价；`built_so_far` 只作
    「实账是否已成形」的判据，不再作外推分母。
    """
    model = _ann_build_demand_bytes(remaining_vectors, dim)
    if (
        remaining_vectors is None
        or available_now is None
        or available_at_start is None
        or built_so_far <= 0
    ):
        return model
    consumed = max(0, int(available_at_start) - int(available_now))
    return int(model + consumed)


def _ann_live_floor_bytes(dim: int) -> int:
    """规模未知时中途复检用的活体下限：低于这条就立刻收火（别把自己跑死）。"""
    return _ANN_BUILD_MIN_HEADROOM_BYTES + _ann_build_batch_slack_bytes(dim)


def _evaluate_ann_build_memory_gate(
    expected_vectors: int | None, dim: int
) -> _AnnMemoryVerdict:
    """开火前的内存门：可用物理内存撑得住本轮重建吗。

    fail-closed：探针取不到 ⇒ 不放行（`probe_failed=True` 会进告警与 meta，
    读的人看得见"是因为量不到才没跑"，而不是以为"内存不够"）。
    """
    available = _available_physical_memory_bytes()
    required = _ann_build_demand_bytes(expected_vectors, dim)
    return _AnnMemoryVerdict(
        allowed=available is not None and available >= required,
        available_bytes=available,
        required_bytes=required,
        expected_vectors=expected_vectors,
        dim=int(dim),
        probe_failed=available is None,
    )


class _AnnBuildGate:
    """ANN 重建/覆写的跨进程互斥闸：OS 文件锁，进程崩溃由内核自动释放。

    仓内既有跨进程互斥手段只有 SQLite 文件锁（BEGIN IMMEDIATE +
    busy_timeout，见 billing_service/usage_service/rate_limit），那是
    *事务期* 锁——ANN 重建是分钟级，持写事务会把运行中 Bot 的知识库写入
    全部憋死。故此处用同目录锁文件：与 SQLite 侧同一语义家族（独占、
    非阻塞退避、拿不到就让路并如实报告），且不新增依赖、不自研锁协议。
    """

    def __init__(self, lock_path: str | Path) -> None:
        self.lock_path = Path(lock_path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self, timeout_seconds: float = _ANN_LOCK_TIMEOUT_SECONDS) -> bool:
        """独占加锁；超时仍拿不到返回 False（调用方必须放弃覆写）。"""
        if self._fd is not None:
            return True
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            # O_CREAT 不截断：截断会踩掉可能正持锁者的文件句柄语义。
            fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o666)
        except OSError:
            return False
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while True:
            if self._try_lock(fd):
                self._fd = fd
                return True
            if time.monotonic() >= deadline:
                break
            time.sleep(_ANN_LOCK_POLL_SECONDS)
        try:
            os.close(fd)
        except OSError:
            pass
        return False

    @staticmethod
    def _try_lock(fd: int) -> bool:
        try:
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except ImportError:
            import fcntl

            try:
                fcntl.flock(  # type: ignore[attr-defined]
                    fd,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
                return True
            except OSError:
                return False
        except OSError:
            return False

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        self._fd = None
        try:
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (ImportError, OSError):
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            except (ImportError, OSError):
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _fsync_path(path: Path) -> None:
    """对已落盘文件补一次 fsync（掉电/击杀瞬间也要把新页留在盘上）。"""
    try:
        with open(path, "rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        pass


def _atomic_replace_from(tmp_path: Path, target: Path) -> None:
    """同卷原子换入（Windows 上 Path.replace/os.replace 同卷原子）。"""
    _fsync_path(tmp_path)
    try:
        os.replace(str(tmp_path), str(target))
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat_stamp(path: Path) -> tuple[int, int] | None:
    """(size, mtime_ns)：只作为"外部是否换过代"的廉价触发器，不作身份。"""
    try:
        info = path.stat()
    except OSError:
        return None
    return (int(info.st_size), int(info.st_mtime_ns))


class OpenAICompatibleEmbeddingProvider:
    """按链顺序请求：本地（如 Ollama bge-m3）优先，远程付费模型兜底。

    每条链内部又可按逗号分隔的模型列表依次回退（如 qwen3.7 配额耗尽换 v4）。
    一旦某条链成功，后续请求优先复用该链（sticky），只有它失败才再切。
    """

    def __init__(
        self,
        base_url: str,
        model: str | list[str],
        api_key: str,
        timeout_seconds: float = 15.0,
        dimensions: int | None = None,
        local_base_url: str = "",
        local_models: str | list[str] = "",
        local_api_key: str = "",
        local_enabled: bool = True,
        local_timeout_seconds: float = 5.0,
        local_dimensions: int | None = None,
    ) -> None:
        chains: list[_EmbeddingChain] = []
        if local_enabled and str(local_base_url).strip():
            local_models_list = _parse_model_list(local_models)
            if local_models_list:
                chains.append(
                    _EmbeddingChain(
                        base_url=str(local_base_url).strip().rstrip("/"),
                        models=tuple(local_models_list),
                        api_key=str(local_api_key),
                        dimensions=int(local_dimensions) if local_dimensions else None,
                        timeout_seconds=float(local_timeout_seconds),
                    )
                )
        remote_models = _parse_model_list(model)
        if remote_models and str(base_url).strip():
            chains.append(
                _EmbeddingChain(
                    base_url=str(base_url).strip().rstrip("/"),
                    models=tuple(remote_models),
                    api_key=str(api_key),
                    dimensions=int(dimensions) if dimensions else None,
                    timeout_seconds=float(timeout_seconds),
                )
            )
        self.chains = chains
        first = chains[0] if chains else None
        self.base_url = first.base_url if first else ""
        self.models = list(first.models) if first else []
        self.model = self.models[0] if self.models else ""
        self.api_key = first.api_key if first else api_key
        self.timeout_seconds = first.timeout_seconds if first else float(timeout_seconds)
        self.dimensions = first.dimensions if first else None
        self._active_index: int | None = None
        self.active_base_url = ""
        self.active_model = ""

    @property
    def signature(self) -> str:
        """配置指纹：base_url 或模型列表变化时触发知识库向量重建。"""
        return ";".join(
            f"{chain.base_url}|{','.join(chain.models)}" for chain in self.chains
        )

    def _chain_order(self) -> list[tuple[int, _EmbeddingChain]]:
        if self._active_index is not None:
            sticky = self.chains[self._active_index]
            rest = [
                (index, chain)
                for index, chain in enumerate(self.chains)
                if index != self._active_index
            ]
            return [(self._active_index, sticky), *rest]
        return list(enumerate(self.chains))

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量编码：本地优先、远程兜底；模型列表内部依次回退。

        单文本查询（聊天链路每次检索一条 query）走进程级 TTL memo：
        人格库与 kb_wiki 库对同一 query 各嵌一次、且 provider 实例不同，
        按 signature+文本为键即可跨库去重；批量文档嵌入不经 memo。
        """
        if not texts:
            return []
        memo_key: tuple[str, str] | None = None
        if len(texts) == 1:
            memo_key = (self.signature, texts[0])
            cached = _query_embed_memo_get(memo_key)
            if cached is not None:
                return [list(vector) for vector in cached]
        result = self._embed_texts_uncached(texts)
        if memo_key is not None and result:
            _query_embed_memo_put(memo_key, result)
        return result

    def _embed_texts_uncached(self, texts: list[str]) -> list[list[float]]:
        for index, chain in self._chain_order():
            for model in chain.models:
                try:
                    body: dict = {"model": model, "input": texts}
                    if chain.dimensions:
                        body["dimensions"] = chain.dimensions
                    headers = (
                        {"Authorization": f"Bearer {chain.api_key}"}
                        if chain.api_key
                        else {}
                    )
                    response = httpx.post(
                        f"{chain.base_url}/embeddings",
                        headers=headers,
                        json=body,
                        timeout=chain.timeout_seconds,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    data = payload["data"]
                    if all("index" in item for item in data):
                        data = sorted(data, key=lambda item: int(item["index"]))
                    self._active_index = index
                    self.active_base_url = chain.base_url
                    self.active_model = model
                    return [list(item["embedding"]) for item in data]
                except Exception:  # noqa: S112, BLE001 - 单个嵌入服务失败时尝试下一个备用服务。
                    continue
        return []


def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
    """与 FileCharacterContextProvider._chunk_text 同语义的段落切块。"""
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        next_value = paragraph if not current else f"{current}\n{paragraph}"
        if len(next_value) <= chunk_chars:
            current = next_value
            continue
        if current:
            chunks.append(current)
        current = paragraph[:chunk_chars]
        while len(paragraph) > chunk_chars:
            paragraph = paragraph[chunk_chars:]
            chunks.append(current)
            current = paragraph[:chunk_chars]
    if current:
        chunks.append(current)
    return chunks


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    try:
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = sqrt(sum(float(a) * float(a) for a in left))
        right_norm = sqrt(sum(float(b) * float(b) for b in right))
    except (TypeError, ValueError):
        return 0.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符，配合 SQL 的 ESCAPE '\' 使用。"""
    return (
        str(term)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# 词条名通道的切分与前缀匹配参数：人格知识库标题即文件名，常用 _/-/空白
# 连接主名与子题（如「纳西妲_背景故事」）；用户提及常只说到词条名前 2~4 字。
_TITLE_SEGMENT_SPLIT_RE = re.compile(r"[_\-\s]+")
_TITLE_PREFIX_MIN_CHARS = 2
_TITLE_PREFIX_MAX_CHARS = 4


def _entry_title_match_len(title: str, text: str) -> int:
    """词条名与查询文本的命中长度；0 = 未命中。

    人格库词条名按 ``_``/``-``/空白切分后逐段匹配：段整体包含于查询即
    命中（包含匹配）；纯中文段再取 2~4 字前缀（从长到宽尝试）出现在
    查询中也算命中（前缀匹配），容忍用户只提到词条名开头几个字。
    wiki 库标题「标题·来源」先剥来源后缀再比对。返回最长命中长度供排序。
    """
    base = title.split("·", 1)[0] if "·" in title else title
    best = 0
    for segment in _TITLE_SEGMENT_SPLIT_RE.split(base):
        if len(segment) < _TITLE_PREFIX_MIN_CHARS:
            continue
        if segment in text:
            best = max(best, len(segment))
            continue
        if not _CJK_RE.fullmatch(segment):
            continue
        for length in range(
            min(_TITLE_PREFIX_MAX_CHARS, len(segment) - 1),
            _TITLE_PREFIX_MIN_CHARS - 1,
            -1,
        ):
            if segment[:length] in text:
                best = max(best, length)
                break
    return best


def _title_exact_hit(title: str, text: str) -> bool:
    """词条标题是否被查询**整段**包含（区别于 2~4 字前缀的部分命中）。

    人格库标题按 ``_``/``-``/空白切分后，任一 >=2 字的段完整出现在查询
    中即为精确命中（如查询「守岸人是谁」整段包含词条《守岸人》）；
    wiki 库标题先剥「·来源」后缀再切分。精确命中供检索置顶（直通第一），
    前缀命中只保留原有的 RRF 加权，不置顶。
    """
    base = title.split("·", 1)[0] if "·" in title else title
    return any(
        len(segment) >= _TITLE_PREFIX_MIN_CHARS and segment in text
        for segment in _TITLE_SEGMENT_SPLIT_RE.split(base)
    )


def _rrf_scores(
    vector_ids: list[str],
    keyword_ids: list[str],
    k: float = _RRF_K,
    bonus_ids: list[str] | None = None,
) -> dict[str, float]:
    """RRF 打分（与 _rrf_fuse 同式），供 search_scored 暴露逐块融合分。"""
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(vector_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, chunk_id in enumerate(keyword_ids):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    for rank, chunk_id in enumerate(bonus_ids or []):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 2.0 / (k + rank + 1)
    return scores


def _rrf_fuse(
    vector_ids: list[str],
    keyword_ids: list[str],
    top_k: int,
    k: float = _RRF_K,
    bonus_ids: list[str] | None = None,
) -> list[str]:
    """Reciprocal Rank Fusion：把多个通道的排序融合成一个稳定排序。

    bonus_ids（词条名命中通道）以双倍权重并入：查询里包含某词条名时
    （如「纳西妲的元素战技叫什么」含词条《纳西妲》），该词条页应优先于
    正文堆满相近词的机制/攻略页。只做排序，不加载正文。
    """
    scores = _rrf_scores(vector_ids, keyword_ids, k=k, bonus_ids=bonus_ids)
    ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return ranked[: max(0, int(top_k))]


def _file_signature(path: Path) -> tuple[int, int] | None:
    """(mtime,size) 内容签名；文件不可达返回 None（调用方不得用它跳过同步）。"""
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _metadata_value(doc: dict, column: str) -> str | None:
    """台账时间元数据取值：键缺失 → None（无从得知，落 NULL 绝不冒充）。

    键存在则规范为去空白字符串：``''`` 是诚实的「上游没有可信时间值」
    （非 MediaWiki 系源没有编辑时间），与 NULL 的「从未回填」严格区分。
    """
    if column not in doc:
        return None
    return str(doc.get(column) or "").strip()


@dataclass(frozen=True)
class ScoredKnowledgeChunk:
    """带通道排名与 RRF 融合分的检索单条（KnowledgeService 供分面用）。

    channels 值为该块在各通道候选中的 0 基排名；None = 未命中该通道。
    """

    chunk: KnowledgeChunk
    score: float
    channels: dict[str, int | None]


class SqliteVectorKnowledgeStore:
    def __init__(
        self,
        db_path: str | Path,
        embed_provider: EmbeddingProvider,
        chunk_chars: int = 900,
        top_k: int = 4,
        signature: str = "",
        auto_reset: bool = True,
        ann_index_path: str = "",
        ann_order_path: str = "",
        min_cosine_threshold: float = _MISS_COSINE_THRESHOLD,
        fts_auto_rebuild: bool = True,
        source_quota_enabled: bool = False,
    ) -> None:
        self.db_path = str(db_path)
        self.embed_provider = embed_provider
        self.chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self.top_k = max(0, int(top_k))
        self.signature = str(signature or "").strip()
        self.ann_index_path = str(ann_index_path or "").strip() or str(
            Path(self.db_path).with_name("knowledge_faiss.index")
        )
        self.ann_order_path = str(ann_order_path or "").strip() or str(
            Path(self.db_path).with_name("knowledge_faiss.order.json")
        )
        self._ann_index: Any | None = None
        self._ann_order: list[str] | None = None
        # 已载入 ANN 代际的文件指纹（见 _ann_stat_pair）：外部换入新索引后
        # 据此发现代际变化，无需重启进程即可收敛；None=尚未载入。
        self._ann_loaded_stamp: tuple | None = None
        # 拒用判定缓存（certify-prewarm 波 P3）：load_ann_index 拒用时记下
        # 「被拒的代际指纹 + 当时导致拒用的计数戳值」，两者都不变就维持拒用，
        # 不再按查询重复昂贵重判（mmap 重开 / order JSON 解析 / 证明 sha）。
        # 失效信号与 _ann_loaded_stamp 同一族：文件换代、_drop_ann_cache /
        # invalidate_runtime_caches 调用；外加戳键取值变化（认证/涨戳）——
        # 这是唯一不碰 ANN 文件的自愈动作，点查一发主键即可感知，无需重启。
        self._ann_refused_stamp: tuple | None = None
        self._ann_refused_expected: int | None = None
        # 本进程当前持有的 ANN 建锁闸（覆写前的持锁凭证，见 _require_ann_lock）。
        self._ann_build_gate: _AnnBuildGate | None = None
        # 运行时应为 False：只有显式 knowledge-sync 才允许因指纹变化清空向量，
        # 避免机器人进程与同步进程并发时互相清空、进度反复回退。
        self.auto_reset = bool(auto_reset)
        self._lock = threading.RLock()
        # 文件代际号：原子换索引（KnowledgeService.reindex → swap）后递增，
        # 各线程 _connect 发现代际不符即关旧连接重开（旧句柄指向旧 inode）。
        self._file_generation: int = 0
        # 维护任务锁：embed_pending/build_ann_index 等分钟级重建相互互斥，
        # 但绝不持 _lock（检索锁）执行——否则一次重建冻结所有会话的检索。
        self._maintenance_lock = threading.Lock()
        # 线程局部连接缓存（见 _connect）；:memory: 库不缓存。
        self._conn_tls = threading.local()
        # (mtime,size) 同步签名缓存：签名未变的知识文件在 sync_chunks 里跳过
        # 重读/分块/哈希（管线检视 #9；每条消息至少进一次 sync_chunks）。
        self._synced_signatures: dict[Path, tuple[int, int]] = {}
        self._vector_cache: Any | None = None
        self._vector_meta: list[dict] | None = None
        # R3 停摆批：向量缓存单飞构建锁——GB 级全表载入（见 _build_vector_cache）
        # 多线程只做一次，其余等同一份结果；构建绝不重复、也绝不互相踩。
        # 只与 _load_vector_cache/_prewarm_vector_cache 配套，是叶子锁：
        # 持有它期间不得再取 _lock（锁序：_lock → 本锁，防环）。
        self._vector_cache_build_lock = threading.Lock()
        # 缓存世代号：_invalidate_vector_cache 递增；锁外预热构建期间若发生
        # 新失效（世代变化）则丢弃本轮结果（防把过期矩阵换入）。
        self._vector_cache_generation: int = 0
        # FTS5 关键词通道状态；None 表示“本进程尚未确认”，
        # False 表示已确认不可用（仅在知识库内容变化后重试）。
        self._fts_valid: bool | None = None
        # 低置信未命中阈值：无关键词命中且向量最高余弦低于该值时返回空结果。
        self.min_cosine_threshold = float(min_cosine_threshold)
        # False 时检索路径发现 FTS 签名缺失不做内联重建（大库重建分钟级，
        # 会卡住消息处理），降级为纯向量通道，重建交给显式同步任务 force=True。
        self.fts_auto_rebuild = bool(fts_auto_rebuild)
        # 源族配额开关：仅人格 provider（build_vector_knowledge_provider）置
        # True；kb_wiki/smoke/KnowledgeService 等其余构造点保持 False=逐字节
        # 现状。动机与族粒度实测见上方「源族配额」参数块。
        self.source_quota_enabled = bool(source_quota_enabled)
        self._ensure_schema()
        # 库内既有向量维度（首次写入时落 knowledge_meta，重启后恢复）：
        # _save_vectors 用它拒绝混合维度语料入库。
        self._vector_dim: int | None = self._stored_vector_dim()

    def _stored_vector_dim(self) -> int | None:
        if self.db_path == ":memory:":
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = 'vector_dim'"
                ).fetchone()
            return int(str(row[0])) if row else None
        except (sqlite3.Error, TypeError, ValueError):
            return None

    def _ensure_schema(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # WAL（持久属性，设一次即可）：与 knowledge-sync/kb-sync 独立进程
            # 并发读写时不再互相阻塞成片 SQLITE_BUSY（affinity/media_registry 同款）。
            try:
                connection.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT,
                    title TEXT,
                    content TEXT,
                    content_hash TEXT,
                    vector_json TEXT,
                    vector_blob BLOB
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(knowledge_chunks)")
            }
            if "vector_blob" not in columns:
                connection.execute(
                    "ALTER TABLE knowledge_chunks ADD COLUMN vector_blob BLOB"
                )
            # sync_documents / sync_chunks 的按源删除与源级统计走这个索引，
            # 大库（十万行级）没有它每次删源都退化为全表扫描。
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source "
                "ON knowledge_chunks(source_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            # 外部知识库文档台账：doc_id → hash，sync_documents 幂等判断的依据。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_docs (
                    doc_id TEXT PRIMARY KEY,
                    topic TEXT,
                    source TEXT,
                    title TEXT,
                    hash TEXT,
                    source_updated_at TEXT,
                    crawl_at TEXT
                )
                """
            )
            # 存量库列迁移（与 knowledge_chunks.vector_blob 同一套幂等做法：
            # PRAGMA table_info 探测 → 缺列才 ALTER）：时间元数据是「只增不改」
            # 的旁路信息，ALTER 只加可空列，既有行取值 NULL（=从未回填），
            # 永不触碰 chunk/向量，因此升级本身零重嵌成本。
            doc_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(knowledge_docs)")
            }
            for column in _DOC_METADATA_COLUMNS:
                if column not in doc_columns:
                    connection.execute(
                        f"ALTER TABLE knowledge_docs ADD COLUMN {column} TEXT"
                    )

    def _stored_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = 'embedding_signature'"
            ).fetchone()
        return str(row[0]) if row else ""

    def _set_stored_signature(self, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_meta (key, value)
                VALUES ('embedding_signature', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (value,),
            )

    def set_meta(self, key: str, value: str) -> None:
        """knowledge_meta 通用写入口（键值均为字符串，供同步摘要等观测项落库）。

        与 embedding_signature/fts_signature 同表同语义：单行 UPSERT，跨进程、
        跨重启可见；不改任何 chunk/向量行，因此写入本身零重嵌成本。
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    def get_meta(self, key: str) -> str:
        """knowledge_meta 通用读入口；键不存在返回空串（不猜默认值）。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = ?", (str(key),)
            ).fetchone()
        return str(row[0]) if row is not None and row[0] is not None else ""

    def _reset_vectors_if_needed(self) -> bool:
        """模型/端点指纹变化时清空旧向量（返回是否执行了重置）。

        首次构建或上一次构建未完成时，stored 为空：不清空，保留已有
        向量并断点续跑剩余行，避免重启同步把已完成进度全部回退。
        """
        if not self.signature:
            return False
        if not self.auto_reset:
            return False
        stored = self._stored_signature()
        if not stored or stored == self.signature:
            return False
        with self._connect() as connection:
            # 走漏斗而不是裸 UPDATE：全库清向量是最猛的一次"行数掉光而戳不动"，
            # 走过这里 ⇒ 戳归 0；没走过这里 ⇒ 库里一行都没嵌，戳却停在历史高位。
            self._clear_all_vectors(connection)
            # 模型指纹变化常伴随维度变化：维度守卫一并复位，允许新维度重新入库。
            connection.execute("DELETE FROM knowledge_meta WHERE key = 'vector_dim'")
        with self._lock:
            self._vector_dim = None
        self._set_stored_signature("")
        self._invalidate_vector_cache()
        return True

    def _embed_all_pending(self, on_progress=None, batch_size: int | None = None) -> tuple[int, int]:
        """把全部待嵌入行编码入库；完成后记录模型指纹，失败可断点续跑。

        on_progress(done, total) 每处理一批调用一次，用于打印进度。
        batch_size 覆盖默认批大小（默认值迁就远程链限额；本地 Ollama
        大批吞吐显著更高，由调用方按需传入）。
        """
        self._reset_vectors_if_needed()
        pending = self._pending_rows()
        size = max(1, int(batch_size)) if batch_size else _EMBED_BATCH_SIZE
        # 折半下限取 _EMBED_BATCH_SIZE：它同时是远程链的单批上限，退到远程不再被拒。
        floor_size = max(1, min(size, _EMBED_BATCH_SIZE))
        # 冷启动防线（2026-09-20 无人值守夜实测 5,943 块嵌了 0 块）：模型首次加载的
        # 成本由这一发预热承担，且批次拿不到向量时再试一次 —— 否则一次超时就让整轮归零。
        # 重试预算全局只有 1 次，端点真不可用时仍然快速退出，不把同步拖成长任务。
        if pending:
            self._embed(["预热"])
        retries_left = 1
        done = 0
        total = len(pending)
        while done < total:
            batch = pending[done : done + size]
            texts = [str(row["content"]) for row in batch]
            vectors = self._embed(texts)
            while vectors is None and retries_left > 0:
                retries_left -= 1
                vectors = self._embed(texts)
            # 批×超时是配比问题不是偶发故障：生产 .env 的 128 批 × 本地 5s 超时
            # （实测约 19 块/s ⇒ 128 块 ≈6.7s）每批必挂，预热与同尺寸重试都救不了。
            # 折半重试并把收缩记住给后续批次；到下限仍拿不到才 break（链长有界）。
            while vectors is None and len(batch) > floor_size:
                size = max(floor_size, len(batch) // 2)
                batch = pending[done : done + size]
                texts = [str(row["content"]) for row in batch]
                vectors = self._embed(texts)
            if vectors is None:
                break
            if not self._save_vectors(batch, vectors):
                break
            done += len(batch)
            if on_progress is not None:
                try:
                    on_progress(done, total)
                except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响嵌入任务。
                    pass
        if self.signature and done == total:
            self._set_stored_signature(self.signature)
        return done, total

    def _invalidate_vector_cache(self) -> None:
        self._vector_cache = None
        self._vector_meta = None
        # R3 停摆批：世代号递增，锁外预热（_prewarm_vector_cache）构建期间
        # 发生新失效时据此丢弃过期结果。部分调用点不持 _lock（sync_documents），
        # 整数自增的竞态最坏是多保留一轮旧缓存，可接受。
        self._vector_cache_generation += 1

    def _prewarm_vector_cache(self) -> None:
        """检索锁外预热向量缓存（R3 停摆批根治项）。

        背景：``retrieve``/``search_scored`` 的向量通道在**持有检索锁**时
        走 ``_vector_candidates`` → ``_load_vector_cache``，缓存失效后的
        首次检索会把全表载入（kb_wiki 23.8 万块库文件 5.7GB）也放进锁内，
        全部会话的检索在锁后排队、聊天线程池堆满 → 消息被 pipeline_busy
        静默吞掉、LLM 请求发不出（22:25 停摆实弹根因之一）。

        本方法在进锁**之前**把缓存烧热：单飞构建锁保证多线程只等一份构建，
        构建完成后世代校验 + 原子换入；进锁后的 ``_load_vector_cache`` 命中
        热缓存即瞬时返回。fail-open：任何异常不影响检索主链路（锁内路径
        自会再试）。
        """
        if self._vector_cache is not None and self._vector_meta is not None:
            return
        try:
            generation = self._vector_cache_generation
            with self._vector_cache_build_lock:
                if self._vector_cache is not None and self._vector_meta is not None:
                    return  # 别的线程刚烧热，直接用。
                matrix, chunk_ids = self._build_vector_cache()
            if generation != self._vector_cache_generation:
                return  # 构建期间发生了新的失效：本轮结果已过期，丢弃。
            if matrix is not None:
                with self._lock:
                    # 只在缓存仍为空时换入（避免覆盖更近一次失效后的重建）。
                    if self._vector_cache is None:
                        self._vector_cache = matrix
                        self._vector_meta = chunk_ids
        except Exception:  # noqa: BLE001 - 预热失败不影响检索（锁内路径兜底）。
            return

    def _connect(self) -> sqlite3.Connection:
        """线程局部连接复用（本机延迟压榨项）：一次检索要开 6~8 个连接
        （sync_chunks/FTS 探查×2/短语 MATCH/词条 MATCH/正文懒加载），人格库
        +wiki 库每条消息合计 12~16 次 sqlite3.connect；Windows 上每次建连
        0.1~0.3ms 且伴随文件句柄开销。按 (store, thread) 缓存后归零。

        安全边界：``check_same_thread=False`` 下并发共享同一连接不安全，
        因此按线程隔离（每线程各一条，互不交叉）；``:memory:`` 库按线程
        缓存会变成各线程一张空库，必须每次新建。连接异常自愈交给上层
        检索器的兜底（_VectorKnowledgeRetriever/KBWikiRetriever 捕获降级）。
        """
        if self.db_path == ":memory:":
            return self._new_connection()
        connection = getattr(self._conn_tls, "connection", None)
        if connection is not None and (
            getattr(self._conn_tls, "generation", -1) != self._file_generation
        ):
            # 代际已切换（原子换索引）：旧连接指向被替换前的旧 inode，作废重开。
            try:
                connection.close()
            except sqlite3.Error:
                pass
            connection = None
        if connection is None:
            connection = self._new_connection()
            self._conn_tls.connection = connection
            self._conn_tls.generation = self._file_generation
        return connection

    def invalidate_runtime_caches(self) -> None:
        """换代后清空进程内缓存并作废线程连接（原子换索引后必须调用）。

        递增文件代际号：各线程 `_connect` 下次取连接时发现代际不符即关
        旧连接重开（旧句柄指向被替换前的旧 inode，不再复用）；向量缓存、
        ANN 索引、FTS 有效性状态、同步签名缓存一并作废。
        """
        with self._lock:
            self._file_generation += 1
            self._invalidate_vector_cache()
            self._ann_index = None
            self._ann_order = None
            self._ann_loaded_stamp = None
            self._ann_refused_stamp = None
            self._ann_refused_expected = None
            self._fts_valid = None
            self._synced_signatures.clear()

    def close_runtime_handles(self) -> None:
        """关闭当前线程的缓存连接并清缓存（重建临时库换文件前必须调用）。

        Windows 上 sqlite 打开的文件无法原子替换，临时库 swap 前必须把
        本线程句柄干净关闭（close 时 WAL 自动 checkpoint 落盘、删旁车）。
        """
        connection = getattr(self._conn_tls, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error:
                pass
            self._conn_tls.connection = None
        self.invalidate_runtime_caches()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_source_ledger(
        self,
        connection: sqlite3.Connection,
        source_id: str,
        signature: tuple[int, int],
        ledger: set[str],
    ) -> None:
        """确保源级台账有记录；首次升级/首次同步时补写一次，之后零写入。"""
        if source_id in ledger:
            return
        connection.execute(
            "INSERT OR IGNORE INTO knowledge_meta (key, value) VALUES (?, ?)",
            (_SOURCE_SIG_KEY_PREFIX + source_id, f"{signature[0]}:{signature[1]}"),
        )
        ledger.add(source_id)

    #: 最近一次被删除侧守卫拦下的动作（None=从未拦过）。结构化字段供告警投喂
    #: 与测试断言：reason / planned_sources / ledger_sources / manifest_paths。
    last_sync_guard: dict[str, object] | None = None

    def _note_wipe_guard(
        self,
        reason: str,
        *,
        planned_sources: int,
        ledger_sources: int,
        manifest_paths: int,
    ) -> None:
        """守卫命中留痕：结构化告警 + 观测位，绝不静默吞掉。

        静默是这场事故的一半成因——删掉 35,479 行时日志里一个字符都没有。
        """
        guard: dict[str, object] = {
            "reason": reason,
            "planned_sources": planned_sources,
            "ledger_sources": ledger_sources,
            "manifest_paths": manifest_paths,
        }
        self.last_sync_guard = guard
        logger.warning(
            "knowledge_sync_wipe_guard reason=%s planned_sources=%s "
            "ledger_sources=%s manifest_paths=%s db_path=%s",
            reason,
            planned_sources,
            ledger_sources,
            manifest_paths,
            self.db_path,
        )

    def sync_chunks(self, files: list[Path]) -> None:
        with self._lock:
            paths = [Path(path).expanduser() for path in files]
            manifest_stems = {path.stem for path in paths}
            changed = False
            with self._connect() as connection:
                # 精确删除（清单过期不得删清单外新块）：旧实现
                # `DELETE ... WHERE source_id NOT IN (当前清单)` 以本次清单为
                # 全集，机器人进程清单过期/偏小时会把 knowledge-sync 等其他
                # 写入方刚落库的清单外新块连同旧块一起清掉。改为按台账精确
                # 删除：只删「本库此前同步过（台账有记录）、且已不在当前清单」
                # 的源；台账 key=sync_source_sig:<source_id> 持久化在
                # knowledge_meta，跨进程、跨重启有效。
                ledger = {
                    str(row["key"])[len(_SOURCE_SIG_KEY_PREFIX) :]
                    for row in connection.execute(
                        "SELECT key FROM knowledge_meta WHERE key LIKE ?",
                        (_SOURCE_SIG_KEY_PREFIX + "%",),
                    )
                }
                # 本轮删除计划：台账里已消失的源 + 清单里路径已不存在的源。
                # 计划先算完再判守卫，守卫必须早于任何 DELETE 落刀。
                stale_sources = sorted(ledger - manifest_stems)
                missing_sources = sorted(
                    {path.stem for path in paths if not path.exists()}
                )
                planned = sorted(set(stale_sources) | set(missing_sources))
                # 守卫 A：空清单不等于「语料被清空」。调用方漏传/配置解析成
                # 空表都是事故形态，不是删除全部的理由——历史教训：
                # retrieve(query, None) 曾以 files=[] 走进这里，把台账里的
                # 全部源逐个 DELETE，整库清零且不报错。
                if not paths:
                    self._note_wipe_guard(
                        "empty_manifest",
                        planned_sources=len(planned),
                        ledger_sources=len(ledger),
                        manifest_paths=0,
                    )
                    return
                # 守卫 B：全部路径都指向不存在的文件（配置迁移、盘符变了、
                # personas/ 被清理）同属「清单不可信」，不当作删除依据。
                if len(missing_sources) == len({path.stem for path in paths}):
                    self._note_wipe_guard(
                        "all_paths_missing",
                        planned_sources=len(planned),
                        ledger_sources=len(ledger),
                        manifest_paths=len(paths),
                    )
                    return
                # 守卫 C（绝对量闸）：单轮要摘掉的源超过台账一半即拒删。
                # 为什么值得装：A/B 只认「空/全缺」两种极端，而配置被改坏更
                # 常见的形态是「17 条里剩 3 条」——那照样是多数误删。
                # 台账 <4 个源时不启用：微型语料里摘掉 1 个文件本就是多数，
                # 那是日常操作而非漂移，把它焊死等于禁止删除。
                # 刻意不做成配置开关：放宽这个闸的唯一后果是不可逆删库。
                delete_allowed = True
                if (
                    len(ledger) >= _MASS_DELETE_GATE_MIN_LEDGER
                    and len(planned) * 2 > len(ledger)
                ):
                    delete_allowed = False
                    self._note_wipe_guard(
                        "mass_delete_gate",
                        planned_sources=len(planned),
                        ledger_sources=len(ledger),
                        manifest_paths=len(paths),
                    )
                if delete_allowed:
                    for stale_source in stale_sources:
                        removed_rows = self._forget_chunks(
                            connection, where="source_id = ?", params=(stale_source,)
                        )
                        changed = changed or removed_rows > 0
                        connection.execute(
                            "DELETE FROM knowledge_meta WHERE key = ?",
                            (_SOURCE_SIG_KEY_PREFIX + stale_source,),
                        )
                        ledger.discard(stale_source)
                else:
                    # 拦截即整轮删除侧冻结：新增/更新照常走下面的循环。
                    stale_sources = []
                for path in paths:
                    # (mtime,size) 签名未变的文件跳过重读：retrieve 每条消息都会进这里，
                    # 向量未命中为常态，无签名缓存时每次都要全量读盘+分块+双 sha1
                    #（管线检视 #9；签名语义与 KeywordKnowledgeRetriever._sync_path 一致）。
                    signature = _file_signature(path)
                    if signature is not None and self._synced_signatures.get(path) == signature:
                        self._ensure_source_ledger(connection, path.stem, signature, ledger)
                        continue
                    if signature is None:
                        if path.exists():
                            # 存在但暂时不可读（占用/权限瞬态）：跳过，下条消息重试。
                            continue
                        if not delete_allowed:
                            # 守卫已冻结本轮删除：留着等下轮（清单修好后自愈）。
                            continue
                        # 文件已被删除：清掉旧块，避免被删知识继续被检索命中；
                        # 台账记录一并移除。
                        removed_rows = self._forget_chunks(
                            connection, where="source_id = ?", params=(path.stem,)
                        )
                        changed = changed or removed_rows > 0
                        connection.execute(
                            "DELETE FROM knowledge_meta WHERE key = ?",
                            (_SOURCE_SIG_KEY_PREFIX + path.stem,),
                        )
                        ledger.discard(path.stem)
                        self._synced_signatures.pop(path, None)
                        continue
                    text = load_character_document(path)
                    source_id = path.stem
                    for index, content in enumerate(
                        _chunk_text(text, chunk_chars=self.chunk_chars),
                        start=1,
                    ):
                        chunk_id = hashlib.sha1(
                            f"{path.as_posix()}:{index}:{content}".encode()
                        ).hexdigest()
                        content_hash = hashlib.sha1(
                            content.encode("utf-8")
                        ).hexdigest()
                        existing = connection.execute(
                            "SELECT content_hash, "
                            "(vector_json IS NOT NULL AND vector_json != '') AS has_vector "
                            "FROM knowledge_chunks WHERE chunk_id = ?",
                            (chunk_id,),
                        ).fetchone()
                        if existing is None:
                            connection.execute(
                                """
                                INSERT INTO knowledge_chunks (
                                    chunk_id, source_id, title, content,
                                    content_hash, vector_json
                                )
                                VALUES (?, ?, ?, ?, ?, ?)
                                """,
                                (chunk_id, source_id, source_id, content, content_hash, None),
                            )
                            changed = True
                        elif str(existing["content_hash"]) != content_hash:
                            # 内容变了 ⇒ 这一行的向量作废。同批把戳拉低，否则
                            # 「重嵌一遍旧行」会让涨点重复计数（今晚 missing 的来源）。
                            self._null_out_chunk_vector(
                                connection,
                                source_id=source_id,
                                content=content,
                                content_hash=content_hash,
                                chunk_id=chunk_id,
                                had_vector=bool(existing["has_vector"]),
                            )
                            changed = True
                    if signature is not None:
                        self._synced_signatures[path] = signature
                        self._ensure_source_ledger(connection, path.stem, signature, ledger)
                # 清单里已移除的文件不再保留签名缓存条目。
                for stale in set(self._synced_signatures) - set(paths):
                    self._synced_signatures.pop(stale, None)

                if changed:
                    # 内容/行集合变化会改变 FTS 索引内容：先删除共享签名，
                    # 让本进程与 knowledge-sync 进程都判定索引过期并在下次查询时重建。
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = 'fts_signature'"
                    )
            if changed:
                self._invalidate_vector_cache()
                self._invalidate_fts()

    def sync_documents(
        self,
        docs: Iterable[dict],
        *,
        removed_ids: Iterable[str] = (),
        full: bool = False,
        batch_size: int = 500,
        on_progress=None,
    ) -> dict[str, int]:
        """按 (doc_id, hash) 幂等同步外部文档集（如 Crawl Wiki 知识库）。

        docs 迭代产出 ``{"id", "hash", "chunks", "topic", "source", "title"}``，
        可带 ``source_updated_at``/``crawl_at`` 时间元数据；分块由调用方完成
        （如按 Markdown 标题分节），本方法只负责台账比对与落库：
        hash 未变的文档跳过（只顺带刷时间元数据，见下），新增/变化的先删旧块再
        插入（向量置空等待 embed），``removed_ids`` 与 full 模式下清单中消失的
        文档连同 chunk 一并删除。
        每 batch_size 个文档提交一次，中断后重跑自动续传。
        返回 ``{"added", "changed", "removed", "skipped", "chunks",
        "metadata_refreshed"}``。
        """
        stats = {
            "added": 0,
            "changed": 0,
            "removed": 0,
            "skipped": 0,
            "chunks": 0,
            "metadata_refreshed": 0,
        }
        changed_any = False
        # 批量同步走一次性新建连接（方法结尾显式 close）：不能复用线程局部
        # 缓存连接，否则 close 会毒化本线程后续所有 _connect() 调用。
        connection = self._new_connection()
        try:
            ledger = {
                str(row["doc_id"]): row
                for row in connection.execute(
                    "SELECT doc_id, hash, source_updated_at, crawl_at FROM knowledge_docs"
                )
            }
            seen: set[str] = set()

            def apply_doc(doc_id: str, doc: dict, doc_hash: str) -> None:
                nonlocal changed_any
                self._forget_chunks(
                    connection, where="source_id = ?", params=(doc_id,)
                )
                chunks = [str(chunk) for chunk in (doc.get("chunks") or []) if str(chunk).strip()]
                connection.executemany(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id, source_id, title, content, content_hash, vector_json
                    )
                    VALUES (?, ?, ?, ?, ?, NULL)
                    """,
                    [
                        (
                            hashlib.sha1(
                                f"doc:{doc_id}:{index}:{content}".encode()
                            ).hexdigest(),
                            doc_id,
                            str(doc.get("title") or doc_id),
                            content,
                            hashlib.sha1(content.encode("utf-8")).hexdigest(),
                        )
                        for index, content in enumerate(chunks, start=1)
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_docs (
                        doc_id, topic, source, title, hash,
                        source_updated_at, crawl_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                        topic = excluded.topic,
                        source = excluded.source,
                        title = excluded.title,
                        hash = excluded.hash,
                        source_updated_at = excluded.source_updated_at,
                        crawl_at = excluded.crawl_at
                    """,
                    (
                        doc_id,
                        str(doc.get("topic") or ""),
                        str(doc.get("source") or ""),
                        str(doc.get("title") or ""),
                        doc_hash,
                        _metadata_value(doc, "source_updated_at"),
                        _metadata_value(doc, "crawl_at"),
                    ),
                )
                stats["chunks"] += len(chunks)
                if doc_id in ledger:
                    stats["changed"] += 1
                else:
                    stats["added"] += 1
                changed_any = True

            def refresh_doc_metadata(doc_id: str, doc: dict) -> None:
                """hash 未变行的时间元数据顺手补齐：只 UPDATE 台账两列。

                不碰 knowledge_chunks、不清 FTS 签名、不失效向量缓存——时间与
                正文同源而 hash 只认正文，因此这条路径的重跑成本是常数次 UPDATE，
                永不引发重嵌（首晚全表回填走 sync_document_metadata 同语义）。
                """
                row = ledger.get(doc_id)
                if row is None:
                    return
                for column in _DOC_METADATA_COLUMNS:
                    want = _metadata_value(doc, column)
                    if want is None or row[column] == want:
                        continue
                    connection.execute(
                        f"UPDATE knowledge_docs SET {column} = ? WHERE doc_id = ?",
                        (want, doc_id),
                    )
                    stats["metadata_refreshed"] += 1

            buffered = 0
            for doc in docs:
                doc_id = str(doc.get("id") or "").strip()
                doc_hash = str(doc.get("hash") or "").strip()
                if not doc_id or not doc_hash:
                    continue
                if full:
                    seen.add(doc_id)
                if ledger.get(doc_id) is not None and str(
                    ledger[doc_id]["hash"] or ""
                ) == doc_hash:
                    refresh_doc_metadata(doc_id, doc)
                    stats["skipped"] += 1
                    continue
                apply_doc(doc_id, doc, doc_hash)
                buffered += 1
                if buffered >= max(1, int(batch_size)):
                    connection.commit()
                    buffered = 0
                    if on_progress is not None:
                        try:
                            on_progress(dict(stats))
                        except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响同步。
                            pass
            connection.commit()

            removed = {str(doc_id) for doc_id in removed_ids if str(doc_id)}
            removed &= set(ledger)
            if full:
                removed |= set(ledger) - seen
            for doc_id in sorted(removed):
                self._forget_chunks(
                    connection, where="source_id = ?", params=(doc_id,)
                )
                connection.execute(
                    "DELETE FROM knowledge_docs WHERE doc_id = ?", (doc_id,)
                )
                stats["removed"] += 1
                changed_any = True
            if changed_any or removed:
                # 行集合/内容变化后 FTS 索引过期：清签名让显式同步任务
                # （或 fts_auto_rebuild 的检索进程）在下次访问时重建。
                # ANN 索引不清签名：同步窗口内继续用旧索引（拿不到新块但
                # 崩溃安全），重建由 embed 完成后的 build_ann_index 负责。
                connection.execute(
                    "DELETE FROM knowledge_meta WHERE key = 'fts_signature'"
                )
            connection.commit()
        finally:
            connection.close()
        if changed_any or removed:
            self._invalidate_vector_cache()
            self._invalidate_fts()
        return stats

    def document_count(self) -> int:
        """台账中的文档数（sync_documents 同步范围），供烟测/调度日志使用。"""
        with self._connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0]
            )

    def document_ledger(self) -> dict[str, str]:
        """台账快照 ``{doc_id: hash}``（对账用：与 manifest.entries 全量比对）。

        十万行级台账一次性载入约数 MB 常驻，只在对账轮调用；行序不保证，
        调用方按 key 取用。
        """
        with self._connect() as connection:
            return {
                str(row["doc_id"]): str(row["hash"] or "")
                for row in connection.execute("SELECT doc_id, hash FROM knowledge_docs")
            }

    def documents_missing_metadata(self) -> int:
        """台账里时间元数据尚未回填的文档数（crawl_at IS NULL）。

        ``crawl_at`` 由导出侧保证 100% 有值，故 NULL 唯一含义是「本库从未写过
        该文档的时间元数据」；``source_updated_at`` 不用于判缺（非 MediaWiki 系
        上游本就没有编辑时间，回填后合理为空串）。
        """
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_docs WHERE crawl_at IS NULL"
                ).fetchone()[0]
            )

    def sync_document_metadata(self, docs: Iterable[dict], *, batch_size: int = 500) -> dict[str, int]:
        """零嵌入成本的全表时间元数据回填：只 UPDATE 台账两列，绝不动正文/向量。

        docs 迭代产出 ``{"id", "hash", "source_updated_at", "crawl_at"}``（不必
        带 chunks）。语义与 sync_documents 的跳过分支完全一致，但省掉读正文、
        分块、算 sha1 的全部开销，用于「语料侧只新增时间字段、正文一字未改」
        这类升级的第一晚回填：

        - 台账里没有的 doc_id → 计 ``missing``（新增文档归同步/对账路径管）；
        - 行 hash 与台账 hash 不一致 → 计 ``stale`` 并跳过：那条时间值描述的
          是**另一个内容版本**，写进本库就是假元数据，留给下一轮正常同步；
        - 只在与已存值不同才 UPDATE（``refreshed`` 计数），重跑幂等；
        - 不清 FTS 签名、不失效向量缓存、不产生待嵌行。

        返回 ``{"matched", "refreshed", "missing", "stale"}``。
        """
        stats = {"matched": 0, "refreshed": 0, "missing": 0, "stale": 0}
        connection = self._new_connection()
        try:
            ledger = {
                str(row["doc_id"]): row
                for row in connection.execute(
                    "SELECT doc_id, hash, source_updated_at, crawl_at FROM knowledge_docs"
                )
            }
            buffered = 0
            for doc in docs:
                doc_id = str(doc.get("id") or "").strip()
                if not doc_id:
                    continue
                row = ledger.get(doc_id)
                if row is None:
                    stats["missing"] += 1
                    continue
                doc_hash = str(doc.get("hash") or "").strip()
                if doc_hash and doc_hash != str(row["hash"] or ""):
                    stats["stale"] += 1
                    continue
                stats["matched"] += 1
                for column in _DOC_METADATA_COLUMNS:
                    want = _metadata_value(doc, column)
                    # NULL 与 '' 是两回事：NULL=从未回填（要写），''=上游确无
                    # 可信时间值（写过就不再动）。
                    if want is None or row[column] == want:
                        continue
                    connection.execute(
                        f"UPDATE knowledge_docs SET {column} = ? WHERE doc_id = ?",
                        (want, doc_id),
                    )
                    stats["refreshed"] += 1
                buffered += 1
                if buffered >= max(1, int(batch_size)):
                    connection.commit()
                    buffered = 0
            connection.commit()
        finally:
            connection.close()
        return stats

    def embed_pending(
        self,
        files: list[Path] | None = None,
        on_progress=None,
        *,
        batch_size: int | None = None,
    ) -> tuple[int, int]:
        """预建库：同步文件切片后把未向量化的行全部嵌入。

        模型/端点指纹变化时自动清空旧向量重嵌；返回
        (本次成功嵌入行数, 处理前待嵌入行数)；中途失败即停止、可断点续跑。
        batch_size 覆盖每批行数（本地大批更快，见 _embed_all_pending）。
        """
        with self._maintenance_lock:
            if files:
                self.sync_chunks(list(files))
            return self._embed_all_pending(on_progress=on_progress, batch_size=batch_size)

    def stats(self) -> dict[str, int]:
        """返回 (总行数, 已向量化行数)，供烟测/后台统计使用。"""
        with self._connect() as connection:
            total = int(
                connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            )
            embedded = int(
                connection.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks "
                    "WHERE vector_json IS NOT NULL AND vector_json != ''"
                ).fetchone()[0]
            )
        return {"total": total, "embedded": embedded}

    def _family_of_chunks(self, chunk_ids: list[str]) -> dict[str, str]:
        """批量取候选块的 source_id → 族名（锁内单条 IN 查询，≤百级 id）。"""
        if not chunk_ids:
            return {}
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT chunk_id, source_id FROM knowledge_chunks "
                f"WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
        found = {
            str(row["chunk_id"]): _source_family(str(row["source_id"] or ""))
            for row in rows
        }
        # 查无行（与并发删除竞态，极小概率）：各自成族——不误并族受 cap，
        # 也进不了 persona 保留位。
        return {
            chunk_id: found.get(chunk_id, f"unknown:{chunk_id}")
            for chunk_id in chunk_ids
        }

    def _fused_ids_for_limit(
        self,
        vector_ranked: list[str],
        keyword_ranked: list[str],
        limit: int,
        *,
        entry_ranked: list[str],
        vector_scores: dict[str, float] | None = None,
    ) -> list[str]:
        """RRF 融合取前 limit：开配额时在融合全序上做源族配额选择。

        配额关闭=与旧路径逐字节同（_rrf_fuse 直接截断）；开启=候选全集按
        **相关性证据分三层**再选择：
        * LEGIT（词汇通道命中，或向量余弦 ≥ min_cosine_threshold）——唯一
          参与族 cap 竞争的层：cap 在 LEGIT 融合序上执行，persona 族不封顶。
        * WEAK（池内、cos 为正但低于地板且无词汇命中）——不抢 cap 槽，只在
          两处出场：persona 保留位（弱证据人格块可入位，空槽直补、满员才
          淘汰队尾非人格）与兜底溢出回填（被 cap 淘汰的 LEGIT 之后）。
        * 零证据（cos=0 且非词汇）——彻底出局（argsort 稳定序带进来的并列
          噪声；哈希词袋下 md5 桶碰撞也会伪装出微小正 cos，故 WEAK 允许这
          类块存在但绝不给 cap 槽）。
        这套分层的动机（本波五条红测试的实测结论）：cap 若直接对全池执行，
        会把百科查询第 4/5 名的 legit 同源块让位给零相关/噪声块（"没把百科
        通道治残"红线，语料级回归锁实锤）；反过来人格保留位若拿 0.30 地板
        当门径，同义改写场景（人格块 cos 0.05~0.15）保留位永锁死、配额形
        同虚设。全池皆 WEAK 时结果与关配额逐 id 相同（溢出回填按融合序）。
        """
        if not self.source_quota_enabled:
            return _rrf_fuse(
                vector_ranked, keyword_ranked, limit, bonus_ids=entry_ranked
            )
        scores = _rrf_scores(
            vector_ranked, keyword_ranked, bonus_ids=entry_ranked
        )
        ranked_all = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        if not ranked_all:
            return []
        lexical = set(keyword_ranked) | set(entry_ranked)
        if vector_scores is None:
            legit: list[str] = list(ranked_all)
            weak: list[str] = []
        else:
            legit = [
                chunk_id
                for chunk_id in ranked_all
                if chunk_id in lexical
                or float(vector_scores.get(chunk_id, 0.0))
                >= self.min_cosine_threshold
            ]
            legit_set = set(legit)
            weak = [
                chunk_id
                for chunk_id in ranked_all
                if chunk_id not in legit_set
                and float(vector_scores.get(chunk_id, 0.0)) > 0.0
            ]
        if not legit:
            # 全无强证据：与关配额同（融合序截断，弱证据原样保序回填）。
            return ranked_all[:limit]
        family_of = self._family_of_chunks(ranked_all)
        weak_persona = [
            chunk_id
            for chunk_id in weak
            if family_of.get(chunk_id, chunk_id) == _PERSONA_FAMILY
        ]
        # 弱证据人格块只追加在选择输入**队尾**：A 段按融合序扫到它时人格
        # 不封顶可入 4/5 槽（这正是保留位的落点——MergedKnowledgeRetriever
        # 轮转下流内前 4 位才进得了提示词前 8，落在队尾重排序反而全丢）。
        selection_input = legit + weak_persona
        promotable = {
            chunk_id
            for chunk_id in selection_input
            if family_of.get(chunk_id, chunk_id) == _PERSONA_FAMILY
        }
        selected = _select_within_source_quota(
            selection_input,
            family_of,
            limit,
            promotable_persona=promotable,
            hard_cap_families=_QUOTA_HARD_CAP_FAMILIES,
        )
        if len(selected) < limit:
            # 兜底回填（融合全序扫）：被 cap 淘汰的 LEGIT 与 WEAK 非人格
            # 同场按序补位；硬顶族补位后仍满 cap 则跳过，末轮放开拿满槽。
            seen = set(selected)
            counts: dict[str, int] = {}
            for chunk_id in selected:
                family = family_of.get(chunk_id, chunk_id)
                counts[family] = counts.get(family, 0) + 1
            cap = _quota_family_cap(limit)
            for enforcing in (True, False):
                for chunk_id in ranked_all:
                    if len(selected) >= limit:
                        break
                    if chunk_id in seen:
                        continue
                    family = family_of.get(chunk_id, chunk_id)
                    if (
                        enforcing
                        and family in _QUOTA_HARD_CAP_FAMILIES
                        and counts.get(family, 0) >= cap
                    ):
                        continue
                    counts[family] = counts.get(family, 0) + 1
                    selected.append(chunk_id)
                    seen.add(chunk_id)
                if len(selected) >= limit:
                    break
        return selected

    def retrieve(
        self,
        query_text: str,
        files: list[Path] | None = None,
        *,
        embed_backlog: bool = False,
    ) -> list[KnowledgeChunk]:
        # R3 停摆批：进锁前把向量缓存烧热（GB 级全表载入绝不持检索锁执行）。
        # certify-prewarm 波 P2：ANN 可用时向量通道走 HNSW、矩阵根本不被消费，
        # 不再为已放行路径白建 ~GB 级常驻（wiki 248k 实测 ~1.02GB）；仅拒用/
        # 无索引路径建兜底矩阵（暴力=慢而全，矩阵正是它的燃料）。冷判定
        # （mmap/解析/sha）发生在进锁之前，稳态此处只 2 stat；锁内
        # _ann_candidates→load_ann_index 复核命中热缓存，不产生锁内全表载入。
        if not self.load_ann_index():
            self._prewarm_vector_cache()
        # 锁分段策略：查询嵌入是同步网络调用（httpx 最长 60s），绝不能持
        # self._lock 执行，否则全会话检索在此串行停摆。锁内只保留
        # sync_chunks / 积压补齐 / 候选索引一致读这些快操作。
        with self._lock:
            # 检索只做「有新文件时的增量同步」：files 缺省/为空时跳过整段
            # 同步，绝不以空清单进 sync_chunks（删侧动作不属于读路径）。
            if files:
                self.sync_chunks(list(files))
            if self.top_k <= 0:
                return []
            if embed_backlog:
                # 只有显式预建/同步路径才补齐积压；请求路径不做全表扫描。
                done, pending = self._embed_all_pending()
                if done < pending:
                    return []
        query_vectors = self._embed([str(query_text)])
        if query_vectors is None or len(query_vectors) != 1:
            return []
        query_vector = query_vectors[0]
        with self._lock:
            # 三通道候选：BM25/FTS 关键词 + 向量（HNSW/暴力）+ 词条名命中，
            # 再 RRF 融合（词条名通道双倍权重）。
            keyword_ranked = self._keyword_candidates(str(query_text))
            # 开配额才收集逐块向量余弦（保留位提升的相关性证据门）。
            vector_scores: dict[str, float] | None = (
                {} if self.source_quota_enabled else None
            )
            vector_ranked, best_cosine = self._vector_candidates(
                query_vector, vector_scores
            )
            try:
                entry_hits = self._entry_title_candidates(str(query_text))
            except Exception:  # noqa: BLE001 - 词条通道失败不阻断其余两通道。
                entry_hits = []
            entry_ranked = [chunk_id for _match_len, _exact, chunk_id in entry_hits]
            # 人格词条置顶（最高优先）：查询**整段包含**某条目标题时，该词条
            # 的块直通结果头部，不再依赖 RRF 相对分数——「守岸人是谁」必须先
            # 命中人格库《守岸人》词条，而不是正文堆满「守岸人」的相邻页。
            pinned_ids = [chunk_id for _match_len, exact, chunk_id in entry_hits if exact]
            fused_ids = self._fused_ids_for_limit(
                vector_ranked,
                keyword_ranked,
                self.top_k,
                entry_ranked=entry_ranked,
                vector_scores=vector_scores,
            )
            if not fused_ids and not pinned_ids:
                return []
            # 低置信未命中：既没有关键词命中、也没有精确词条命中、向量最强
            # 余弦又低于阈值 -> 空结果。
            if (
                not keyword_ranked
                and not pinned_ids
                and best_cosine < self.min_cosine_threshold
            ):
                return []
            if pinned_ids:
                pinned_seen = set(pinned_ids)
                fused_ids = [
                    *pinned_ids,
                    *[chunk_id for chunk_id in fused_ids if chunk_id not in pinned_seen],
                ]
            return self._fetch_chunks(list(fused_ids)[: max(1, self.top_k)])

    def search_scored(
        self,
        query_text: str,
        files: list[Path] | None = None,
        *,
        embed_backlog: bool = False,
        top_k: int | None = None,
        sync_files: bool = True,
    ) -> list[ScoredKnowledgeChunk]:
        """带分数检索：与 retrieve 同一三通道候选链，但不丢弃分数。

        返回按 RRF 融合分降序的 ScoredKnowledgeChunk（含词条置顶直通），
        channels 记录各通道 0 基排名（None=未命中），供 KnowledgeService
        做跨库二次融合与来源/分数透出。sync_files=False 时不做文件同步
        （纯只读检索路径；同步属显式 reindex/预建链路）。
        """
        limit = self.top_k if top_k is None else max(0, int(top_k))
        # R3 停摆批：与 retrieve 同口径——进锁前烧热向量缓存（锁外预热）；
        # certify-prewarm 波 P2：同 retrieve，ANN 可用即不建矩阵（见彼处注释）。
        if not self.load_ann_index():
            self._prewarm_vector_cache()
        with self._lock:
            # 与 retrieve 同口径：sync_files=True 也只在真的拿到清单时才同步，
            # 空清单不进删侧（这是 retrieve 之外的第二条同形态引信）。
            if sync_files and files:
                self.sync_chunks(list(files))
            if limit <= 0:
                return []
            if embed_backlog:
                done, pending = self._embed_all_pending()
                if done < pending:
                    return []
        query_vectors = self._embed([str(query_text)])
        if query_vectors is None or len(query_vectors) != 1:
            return []
        query_vector = query_vectors[0]
        with self._lock:
            keyword_ranked = self._keyword_candidates(str(query_text))
            vector_scores: dict[str, float] | None = (
                {} if self.source_quota_enabled else None
            )
            vector_ranked, best_cosine = self._vector_candidates(
                query_vector, vector_scores
            )
            try:
                entry_hits = self._entry_title_candidates(str(query_text))
            except Exception:  # noqa: BLE001 - 词条通道失败不阻断其余两通道。
                entry_hits = []
            entry_ranked = [chunk_id for _match_len, _exact, chunk_id in entry_hits]
            pinned_ids = [chunk_id for _match_len, exact, chunk_id in entry_hits if exact]
            fused_ids = self._fused_ids_for_limit(
                vector_ranked,
                keyword_ranked,
                limit,
                entry_ranked=entry_ranked,
                vector_scores=vector_scores,
            )
            if not fused_ids and not pinned_ids:
                return []
            if (
                not keyword_ranked
                and not pinned_ids
                and best_cosine < self.min_cosine_threshold
            ):
                return []
            if pinned_ids:
                pinned_seen = set(pinned_ids)
                fused_ids = [
                    *pinned_ids,
                    *[chunk_id for chunk_id in fused_ids if chunk_id not in pinned_seen],
                ]
            fused_ids = list(fused_ids)[: max(1, limit)]
            scores = _rrf_scores(
                vector_ranked, keyword_ranked, bonus_ids=entry_ranked
            )
            vector_rank_map = {cid: i for i, cid in enumerate(vector_ranked)}
            keyword_rank_map = {cid: i for i, cid in enumerate(keyword_ranked)}
            entry_rank_map = {cid: i for i, cid in enumerate(entry_ranked)}
            results: list[ScoredKnowledgeChunk] = []
            for chunk in self._fetch_chunks(list(fused_ids)):
                chunk_id = chunk.chunk_id
                results.append(
                    ScoredKnowledgeChunk(
                        chunk=chunk,
                        score=float(scores.get(chunk_id, 0.0)),
                        channels={
                            "vector": vector_rank_map.get(chunk_id),
                            "keyword": keyword_rank_map.get(chunk_id),
                            "entry": entry_rank_map.get(chunk_id),
                        },
                    )
                )
            return results

    def _entry_title_candidates(self, query_text: str) -> list[tuple[int, bool, str]]:
        """词条名命中通道：查询包含/前缀命中某条目标题（或其切分段）时返回该词条的块。

        例：查询「纳西妲的元素战技叫什么」包含词条《纳西妲》→ 其页面块
        经 RRF 双倍权重优先于正文堆满相近词的机制/攻略页。wiki 库标题存储为
        「标题·来源」，比对时剥掉来源后缀；人格知识库标题即文件名，按
        ``_``/``-``/空白切分后逐段比对（包含命中或 2~4 字中文前缀命中，
        见 ``_entry_title_match_len``）。先走 FTS trigram 标题列取有界
        候选，再在 Python 侧做切分/前缀校验，避免 20 万行级全表扫描
        （实测全表 instr 需 0.6~10 秒）。

        返回 ``(match_len, exact, chunk_id)`` 列表，按命中长度降序；
        ``exact=True`` 表示标题整段出现在查询中（供检索置顶，见 retrieve）。
        """
        text = str(query_text or "").strip()
        if len(text) < 2 or not self.ensure_fts_index():
            return []
        # 全文 3 字滑窗覆盖中英混排边界词（「你知道AI梗…」→ 道AI/AI梗），
        # 再补 3~6 字纯 CJK 短段整段匹配（词条名整体命中）。
        windows = [text[index : index + 3] for index in range(len(text) - 2)]
        for match in _CJK_RE.finditer(text):
            segment = match.group(0)
            if _FTS_MIN_MATCH_CHARS <= len(segment) <= 6:
                windows.append(segment)
        windows = list(dict.fromkeys(windows))[:_MAX_PHRASE_TERMS]
        if not windows:
            return []
        match_query = "{title} : (" + " OR ".join(f'"{w}"' for w in windows) + ")"
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"SELECT chunk_id, title FROM {_FTS_TABLE_NAME} "
                    f"WHERE {_FTS_TABLE_NAME} MATCH ? LIMIT 400",
                    (match_query,),
                ).fetchall()
        except sqlite3.Error:
            return []
        scored: list[tuple[int, bool, str]] = []
        for row in rows:
            title = str(row["title"] or "")
            match_len = _entry_title_match_len(title, text)
            if match_len:
                scored.append((match_len, _title_exact_hit(title, text), str(row["chunk_id"])))
        scored.sort(key=lambda triple: (-triple[0], triple[2]))
        return scored[: max(1, self.top_k) * 3]

    def _brute_candidates_python(
        self,
        query_vector: list[float],
        limit: int,
        scores_out: dict[str, float] | None = None,
    ) -> tuple[list[str], float]:
        """纯 Python 暴力余弦：返回 (按相似度降序的 chunk_id, 最高余弦)。

        scores_out 传入时逐块余弦回填其中（源族配额保留位的证据门用）。
        """
        scored: list[tuple[float, str]] = []
        for row in self._vector_rows():
            try:
                vector = json.loads(str(row["vector_json"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            scored.append(
                (_cosine_similarity(query_vector, vector), str(row["chunk_id"]))
            )
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        scored = scored[: max(0, int(limit))]
        if scores_out is not None:
            scores_out.update((chunk_id, score) for score, chunk_id in scored)
        return (
            [chunk_id for _, chunk_id in scored],
            float(scored[0][0]) if scored else 0.0,
        )

    def _vector_candidates(
        self,
        query_vector: list[float],
        scores_out: dict[str, float] | None = None,
    ) -> tuple[list[str], float]:
        """向量通道候选：HNSW 命中则用近似分数，否则 numpy/纯 Python 暴力。

        返回 (按余弦降序的 chunk_id, 最高余弦)；候选数量为
        max(top_k*4, 20)，只用于 RRF 排序，正文仍由 _fetch_chunks 懒加载。
        scores_out 传入时把逐块候选余弦回填其中。
        """
        limit = max(self.top_k * _VECTOR_CANDIDATE_FACTOR, _VECTOR_CANDIDATE_FLOOR)
        ann_ranked = self._ann_candidates(query_vector, limit)
        if ann_ranked is not None:
            chunk_ids = [chunk_id for chunk_id, _score in ann_ranked]
            if scores_out is not None:
                scores_out.update(
                    (chunk_id, 0.0 if isnan(float(score)) else float(score))
                    for chunk_id, score in ann_ranked
                )
            best = float(ann_ranked[0][1]) if ann_ranked else 0.0
            if isnan(best):
                best = 0.0
            return chunk_ids, best
        if np is None:
            return self._brute_candidates_python(query_vector, limit, scores_out)
        try:
            matrix, chunk_ids = self._load_vector_cache()
            if matrix is None or not chunk_ids:
                return [], 0.0
            query_array = np.asarray(query_vector, dtype=np.float32)
            # 查询向量必须归一化：matrix 已按行归一化，不归一查询时
            # scores = cos * ||q||，得分被查询模长缩放，min_cosine_threshold 失效。
            query_norm = float(np.linalg.norm(query_array))
            if query_norm < 1e-9:
                return [], 0.0
            query_array = (query_array / query_norm).astype(np.float32)
            norms = np.linalg.norm(matrix, axis=1)
            matrix_norm = matrix / np.maximum(norms, 1e-9)[:, None]
            scores = matrix_norm @ query_array
            count = min(int(limit), len(chunk_ids))
            if count <= 0:
                return [], 0.0
            top_indices = np.argsort(-scores)[:count]
            ranked_ids = [chunk_ids[int(index)] for index in top_indices]
            if scores_out is not None:
                scores_out.update(
                    (
                        chunk_ids[int(index)],
                        float(max(0.0, min(1.0, scores[int(index)]))),
                    )
                    for index in top_indices
                )
            best = float(scores[int(top_indices[0])])
            if isnan(best):
                best = 0.0
            return ranked_ids, best
        except Exception:  # noqa: BLE001 - 维度/缓存异常时退回纯 Python 路径。
            return self._brute_candidates_python(query_vector, limit, scores_out)

    def _fetch_chunks(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, source_id, title, content
                FROM knowledge_chunks WHERE chunk_id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
        by_id = {str(row["chunk_id"]): row for row in rows}
        chunks: list[KnowledgeChunk] = []
        for chunk_id in chunk_ids:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            chunks.append(
                KnowledgeChunk(
                    chunk_id=str(row["chunk_id"]),
                    source_id=str(row["source_id"] or ""),
                    title=str(row["title"] or ""),
                    content=str(row["content"] or ""),
                )
            )
        return chunks

    def _ann_files(self) -> tuple[str, str]:
        return self.ann_index_path, self.ann_order_path

    def _ann_lock_path(self) -> Path:
        """跨进程建锁文件：与索引同卷同目录（锁只是互斥凭证，不是数据）。"""
        return Path(self.ann_index_path).with_name(
            f"{Path(self.ann_index_path).name}{_ANN_LOCK_SUFFIX}"
        )

    def _ann_stat_pair(self, index_path: str, order_path: str) -> tuple | None:
        """((index_size, index_mtime_ns), (order_size, order_mtime_ns))。

        任一文件不可 stat（缺席/正被移动）返回 None——调用方按"不可用"处理。
        """
        left = _stat_stamp(Path(index_path))
        right = _stat_stamp(Path(order_path))
        if left is None or right is None:
            return None
        return (left, right)

    def _drop_ann_cache(self) -> None:
        self._ann_index = None
        self._ann_order = None
        self._ann_loaded_stamp = None
        self._ann_refused_stamp = None
        self._ann_refused_expected = None

    def _read_ann_attestation(self) -> dict | None:
        """读 SQLite 里的成对代际证明（提交点）；缺失/畸形返回 None。"""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = ?",
                    (_ANN_ATTESTATION_KEY,),
                ).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        try:
            parsed = json.loads(str(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _write_ann_attestation(self, payload: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (_ANN_ATTESTATION_KEY, json.dumps(payload, ensure_ascii=False)),
            )

    def _ann_pair_consistent(
        self,
        index_path: str,
        order_path: str,
        stamp: tuple,
        *,
        attestation: dict | None,
    ) -> bool:
        """按代际证明校验 .index 与 .order.json 属于同一代。

        无证明（旧版存量产物/证明未写入）时放行，交由 `ntotal == len(order)`
        终检兜底——保持对既有已建索引的向后兼容。

        `attestation` 是必填的**已解析证明**：载入路径那发三键合一查询已经把
        它读出来了，再在这里自己开一发点查就是给请求路径添第二笔账（成本锁见
        tests/test_kb_pricing_guard_fts_s159.py::
        test_load_path_cold_accept_is_two_meta_point_reads）。取数口子只有
        一个，判据才有唯一一个口径；也因此不许把它退回成带缺省值的可选参数。
        """
        if not attestation:
            return True
        (index_size, _), (order_size, _) = stamp
        if int(attestation.get("index_bytes", -1) or -1) != index_size:
            logger.warning(
                "knowledge ANN pair refused (index size %s != attested %s): %s",
                index_size,
                attestation.get("index_bytes"),
                Path(index_path).name,
            )
            return False
        if int(attestation.get("order_bytes", -1) or -1) != order_size:
            logger.warning(
                "knowledge ANN pair refused (order size %s != attested %s): %s",
                order_size,
                attestation.get("order_bytes"),
                Path(order_path).name,
            )
            return False
        expected = str(attestation.get("order_sha256") or "")
        if expected:
            try:
                actual = _sha256_file(Path(order_path))
            except OSError:
                return False
            if actual != expected:
                logger.warning(
                    "knowledge ANN pair refused (order digest drift): %s",
                    Path(order_path).name,
                )
                return False
        return True

    def load_ann_index(self) -> bool:
        """签名匹配时 mmap 加载 HNSW 索引；缺失/过期/不成对/短装返回 False 回退暴力。

        缓存带文件指纹：另一进程（knowledge-sync / smoke）原子换入新索引后，
        本进程下一次检索即感知代际变化并重开，不需要重启 Bot。换入中途或
        `.index` 与 `.order.json` 不同代时拒绝载入（回落暴力扫描：慢，但
        绝不返回错位的邻居 id）。

        完备性闸（task #47，参数块见 _EMBEDDED_COUNT_KEY）：签名相等与成对校验
        都只覆盖「同代」，覆盖不了「同代但不全」——补嵌只涨 SQLite 行数、不动
        签名、也不动 order.json，于是两周前的索引可以一直被判新鲜。故载入末尾
        再用计数戳比一次 `index.ntotal`：短装或无从判定（无戳）一律拒用。
        计数戳是 knowledge_meta 单行主键查询，被拒路径也不去扫 knowledge_chunks。

        代次闸（S159，参数块见 _EMBED_GENERATION_KEY）：计数戳是**标量**，
        「同轮先删后嵌」时删除把它拉低、嵌入再把它推回同一个数 ⇒
        `ntotal >= stamp` 恒成立却根本没装下新那批（2026-09-26 生产实况）。
        故戳判之后再加一发代次判：当前嵌入代次 > 本代索引背书的代次 ⇒ 拒用，
        两个数字同屏点名（`coverage refused`）。判据方向只严不松：删除不推进
        代次（纯删除轮是超集，照旧按在册的「多出可容忍」放行），落戳也不推进
        代次（拿落戳洗代次 = 把今晚这个洞换个位置再开一次）。
        **无代际证明时本判 inert**：那是 `_ann_pair_consistent` 早已在册的向后
        兼容形态（存量产物没有证明），在这里补一刀拒用就是把兼容链改口；
        那道闸的红利（少一发 meta 读）不归本判负责，计数戳仍在拦它。

        拒用判定缓存（certify-prewarm 波 P3）：判定为拒的同一代（文件指纹）且
        同一戳值时，后续调用只 stat 两文件 + 一发主键点查即维持拒用——重判一
        次（mmap 1.09GB 级索引 + 解析 10MB 级 order + sha）≈0.57s 且拒用告警
        会按查询刷屏。戳取值一变（knowledge-sync 认证落戳 / 补嵌涨戳 / 重建后
        重发布）即自动重判，运行中进程无需重启即自愈；文件换代与两处缓存失效
        调用同样重判（_drop_ann_cache / invalidate_runtime_caches 一并清）。
        代次不进缓存键：能改判定输入的三件事里，代次只在「又嵌了一批」时变，
        而那一批必然同时涨计数戳（同事务、同写点）⇒ 戳值那一维已经够用。
        """
        if faiss is None:
            return False
        index_path, order_path = self._ann_files()
        stamp = self._ann_stat_pair(index_path, order_path)
        if self._ann_index is not None and self._ann_order is not None:
            if stamp is not None and stamp == self._ann_loaded_stamp:
                return True
            logger.warning(
                "knowledge ANN generation changed externally, reopening: %s",
                Path(index_path).name,
            )
            self._drop_ann_cache()
        elif (
            stamp is not None
            and stamp == self._ann_refused_stamp
            and self._stamped_expected_vector_count() == self._ann_refused_expected
        ):
            # 同一代 + 同一个导致拒用的戳值：判定不会变，直接维持拒用。
            # 唯一要付的是那一发主键点查——不许省，它是「认证只写 meta、
            # 不动 ANN 文件」这条自愈链在运行中进程里唯一的感知通道。
            return False
        if stamp is None:
            return False
        # `expected` 先置 None 是拒用缓存的记账位：读代次/读戳若在事务里炸了，
        # 缓存里记的就是 None（= 下次取值一变即重判），不会把一个没读到的值
        # 当成读到的值钉住拒用。
        expected: int | None = None
        try:
            # 冷载入放行只付两发 knowledge_meta 点查：签名一发（旧路一字不动）
            # + 守卫三键合一一发（计数戳 / 嵌入代次 / 代际证明）。加一道判定就
            # 加一发 DB 往返的话，请求路径的账是看不见的——成本由锁钉死
            # （tests/test_kb_pricing_guard_fts_s159.py::
            #   test_load_path_cold_accept_is_two_meta_point_reads）。
            stored_ann = self._stored_ann_signature()
            expected, generation, attestation = self._read_ann_guard_meta()
            if not stored_ann or stored_ann != self.signature:
                self._remember_ann_refusal(stamp, expected)
                return False
            if not self._ann_pair_consistent(
                index_path, order_path, stamp, attestation=attestation
            ):
                self._remember_ann_refusal(stamp, expected)
                return False
            index = faiss.read_index(str(index_path), faiss.IO_FLAG_MMAP)
            cast(Any, index).hnsw.efSearch = 64
            order = json.loads(Path(order_path).read_text(encoding="utf-8"))
            if not isinstance(order, list):
                self._drop_ann_cache()
                self._remember_ann_refusal(stamp, expected)
                return False
            order_ids = [str(item) for item in order]
            ntotal = int(index.ntotal)
            if ntotal != len(order_ids):
                # 成对性终检：向量数与序列表长度不齐即混代，拒绝使用。
                logger.warning(
                    "knowledge ANN pair refused (ntotal %s != order %s)",
                    ntotal,
                    len(order_ids),
                )
                self._drop_ann_cache()
                self._remember_ann_refusal(stamp, expected)
                return False
            # 完整性终检：索引装下的向量数必须追得上库里的计数戳。
            # 戳取自上面那一发三键合一查询，不在此重读（重读=第三发点查）。
            if expected is None:
                logger.warning(
                    "knowledge ANN completeness refused "
                    "(ntotal=%d expected=unknown reason=unstamped key=%s) "
                    "-> brute force; run knowledge-sync to certify",
                    ntotal,
                    _EMBEDDED_COUNT_KEY,
                )
                self._drop_ann_cache()
                self._remember_ann_refusal(stamp, expected)
                return False
            missing = expected - ntotal
            if missing > _ANN_COMPLETENESS_MAX_MISSING:
                logger.warning(
                    "knowledge ANN completeness refused "
                    "(ntotal=%d expected=%d missing=%d max_missing=%d) "
                    "-> brute force; newly embedded rows are invisible to ANN, "
                    "run knowledge-sync to rebuild",
                    ntotal,
                    expected,
                    missing,
                    _ANN_COMPLETENESS_MAX_MISSING,
                )
                self._drop_ann_cache()
                self._remember_ann_refusal(stamp, expected)
                return False
            # 代次终检（S159）：计数戳追平了也可能仍没装下新那批——同轮先删后嵌
            # 会把标量戳拉回原值（今晚生产 missing=0 的那副索引就是这一形）。
            # 判据只认「本代索引背书到哪一批」：盖章点在 `_publish_ann_pair`
            # （光标打开时那一值）与集合级自证成立的纠偏，落戳点一律不盖。
            if not attestation:
                # 证明缺席 **不等于** 没有代次。`ann_embed_generation` 行还在而代际
                # 证明被删 ⇒ 这一代索引的覆盖背书已经不存在了，此时放行等于把整道
                # 守卫做成「删一行 meta 就同时关掉计数闸与代次闸」——S163 实测过这
                # 一发：今晚那个假绿态删掉证明后 load 由 False 翻回 True。故按最严
                # 一档判：代次非零即拒。真存量库（本功能上线之前建的）两行俱无
                # ⇒ generation=0，逐字节现状不变，向后兼容那格由
                # tests/test_ann_atomic_publish.py::
                # test_legacy_artifacts_without_attestation_still_load 钉住。
                if generation > 0:
                    logger.warning(
                        "knowledge ANN coverage refused "
                        "(embed_generation=%d attested_generation=absent "
                        "ntotal=%d expected=%d) "
                        "-> brute force; 代际证明缺席而嵌入代次非零：这一代索引的"
                        "覆盖背书不存在（或被删），不许当成已背书，"
                        "run knowledge-sync to rebuild",
                        generation,
                        ntotal,
                        expected,
                    )
                    self._drop_ann_cache()
                    self._remember_ann_refusal(stamp, expected)
                    return False
            else:
                covered = self._generation_covered_by(attestation)
                if generation > covered:
                    logger.warning(
                        "knowledge ANN coverage refused "
                        "(embed_generation=%d attested_generation=%d "
                        "ntotal=%d expected=%d) "
                        "-> brute force; 计数戳追平了，但这一代索引没装下发布点"
                        "之后提交的嵌入批次（删+嵌同轮的假绿形态），"
                        "run knowledge-sync to rebuild",
                        generation,
                        covered,
                        ntotal,
                        expected,
                    )
                    self._drop_ann_cache()
                    self._remember_ann_refusal(stamp, expected)
                    return False
            self._ann_index = index
            self._ann_order = order_ids
            # 记的是"已校验过的那一代"指纹（不是重取一次当前值）：校验之后
            # 若又有外部换入，指纹比对不符→下次自动重开，宁可多读一次也不
            # 把没校验过的代际当成已校验缓存住。
            self._ann_loaded_stamp = stamp
            self._ann_refused_stamp = None
            self._ann_refused_expected = None
            return True
        except Exception:  # noqa: BLE001 - 索引损坏/不可读时回退。
            self._drop_ann_cache()
            self._remember_ann_refusal(stamp, expected)
            return False

    def _remember_ann_refusal(self, stamp: tuple, expected: int | None) -> None:
        """把本次拒用记入代际缓存（见 load_ann_index 拒用判定缓存段）。

        缓存键 = 文件指纹 + 当时的计数戳取值：取值不变则判定不变（拒用的输入
        都来自这一对，外加只随文件走的代际证明与代次）；取值一变即重判。
        `expected` 由载入路径那次三键合一查询直接交来——这里**不再**自己读一
        发（读点只该有一处，成本也只该记一次）；取不到值时交 None，最坏是
        下次多一发点查，不会错放。
        """
        self._ann_refused_stamp = stamp
        self._ann_refused_expected = expected

    def _ann_candidates(
        self, query_vector: list[float], limit: int
    ) -> list[tuple[str, float]] | None:
        """HNSW 近似检索候选：返回 (chunk_id, 内积分数) 降序；不可用返回 None。

        向量已按 L2 归一化 + METRIC_INNER_PRODUCT，因此内积即余弦相似度。
        """
        if not self.load_ann_index():
            return None
        index = self._ann_index
        order = self._ann_order
        if index is None or order is None:
            return None
        try:
            query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
            norm = float(np.linalg.norm(query))
            if norm > 0:
                query = query / norm
            _scores, indices = index.search(query, max(1, int(limit)))
            ranked: list[tuple[str, float]] = []
            for score, index in zip(_scores[0], indices[0]):
                if 0 <= int(index) < len(order):
                    ranked.append((str(order[int(index)]), float(score)))
            return ranked
        except Exception:  # noqa: BLE001
            return None

    def build_ann_index(self, on_progress=None, *, force_low_memory: bool = False) -> dict:
        """由 knowledge-sync 调用：把全部向量归一化写入 faiss HNSW 并落盘。

        向量按批从 SQLite 流式读出、逐批归一化 add 进索引——此前一次性
        fetchall + vstack 全量矩阵，10 万 chunk 级语料会产生数百 MB 内存尖峰。

        跨进程互斥：整场重建（读向量 + 构 HNSW + 覆写文件）持一把同目录锁
        文件闸。FAISS 索引不像 SQLite 那样自带文件锁，两个进程同时重建会
        把同一批文件写成交织的垃圾。抢锁最多试 `_ANN_LOCK_TIMEOUT_SECONDS`
        （3s），仍拿不到即如实返回 `built=False, reason=locked_by_other_process`
        ——不在这里长排队（重建是分钟级，硬等会把 smoke 拖死），更绝不覆写
        别人正在写的文件。调用方 smoke/kb_wiki 已按 reason 记账。

        内存门（S112，参数块见 `_ANN_BUILD_MIN_AVAILABLE_BYTES`）：开火前先量
        可用物理内存，不足本轮重建需求即返回
        `built=False, reason=insufficient_memory`（或探针不可判定时的
        `memory_probe_unavailable`），**旧索引原样保留、不 publish**。
        `force_low_memory=True` 是 operator 的显式越门（CLI 旗标，无 config 键、
        不改生产配置面），越门动作本身照样落 meta 留痕。
        被门挡下不改完备性闸：闸仍按 `_ANN_COMPLETENESS_MAX_MISSING=0` 拒用
        ANN ⇒ 检索回落暴力扫描，本门只保证"不会以 OOM 的形态结束这一夜"。
        """
        if faiss is None:
            # faiss 缺失不影响关键词索引：仍幂等构建 FTS，供关键词/降级检索使用。
            self.ensure_fts_index(force=True)
            return {"built": False, "reason": "faiss_missing"}
        verdict = _evaluate_ann_build_memory_gate(
            _estimate_rebuild_scale(self), self._ann_assumed_dimension()
        )
        if not verdict.allowed:
            reason = (
                "memory_probe_unavailable" if verdict.probe_failed else "insufficient_memory"
            )
            if not force_low_memory:
                gate_meta = self._record_ann_memory_skip(
                    verdict, forced=False, stage="pre"
                )
                logger.warning(
                    "跳过 ANN 重建（内存门）：%s — 实测可用 %s，需要 %s"
                    "（按 %s 条 × dim=%s 估，规模未知时退到活体下限 %s）；"
                    "旧索引保留、完备性闸照常拒用（暴力扫描不因此变快）。"
                    "确要在低内存下硬跑：operator CLI 加 --ann-force-low-memory"
                    "（越门会另行留痕），或等空闲物理内存回到该需求之上。",
                    reason,
                    "无法测量"
                    if verdict.available_bytes is None
                    else f"{verdict.available_bytes / 1024**3:.2f}GiB",
                    f"{verdict.required_bytes / 1024**3:.2f}GiB",
                    verdict.expected_vectors if verdict.expected_vectors else "未知",
                    verdict.dim,
                    f"{_ANN_BUILD_MIN_HEADROOM_BYTES / 1024**2:.0f}MiB",
                )
                return {"built": False, "reason": reason, "memory_gate": gate_meta}
            self._record_ann_memory_skip(verdict, forced=True, stage="pre")
            logger.warning(
                "ANN 重建越门开火（--ann-force-low-memory）：实测可用 %s < 需要 %s，"
                "越门者自担 OOM 风险；本条已写进 knowledge_meta[%s]。",
                "无法测量"
                if verdict.available_bytes is None
                else f"{verdict.available_bytes / 1024**3:.2f}GiB",
                f"{verdict.required_bytes / 1024**3:.2f}GiB",
                _ANN_MEMORY_SKIP_META_KEY,
            )
        # 锁序：先进程内维护锁（同旧语义——同进程并发重建排队，不互相踩），
        # 再跨进程建锁闸。反序会造出 gate→maintenance / maintenance→gate 环。
        with self._maintenance_lock:
            lock_path = self._ann_lock_path()
            gate = _AnnBuildGate(lock_path)
            if not gate.acquire():
                logger.warning("跳过 ANN 重建：另一进程正持有建锁 %s", lock_path)
                return {"built": False, "reason": "locked_by_other_process"}
            previous = self._ann_build_gate
            self._ann_build_gate = gate
            try:
                return self._build_ann_index_locked(
                    on_progress,
                    memory_verdict=None if force_low_memory else verdict,
                )
            finally:
                self._ann_build_gate = previous
                gate.release()

    def _ann_assumed_dimension(self) -> int:
        """重建需求估算用的维数：provider 声明值优先，否则保守常量。

        维数决定 `IndexHNSWFlat` 的私有向量副本大小（dim × 4 B/条），是估算里
        唯一的强敏感项。provider 没声明时不许猜小：按生产实测的 bge-m3=1024 走
        （`_ANN_BUILD_ASSUME_DIM`），宁可高估到多跳一次。
        """
        declared = getattr(self.embed_provider, "dimensions", None)
        try:
            dim = int(declared) if declared else 0
        except (TypeError, ValueError):
            dim = 0
        return dim if dim > 0 else _ANN_BUILD_ASSUME_DIM

    def _record_ann_memory_skip(
        self, verdict: _AnnMemoryVerdict, *, forced: bool, stage: str
    ) -> dict[str, Any]:
        """把内存门的判决写进 knowledge_meta（跳过留痕之二：观测行）。

        返回落盘 payload（含 `_ANN_MEMORY_SKIP_CONSECUTIVE_KEY` /
        `_ANN_MEMORY_SKIP_TOTAL_KEY` 两枚累计计数）——调用方把它原样带进
        结果字典的 `memory_gate`，告警话术与重启预检读的都是这一份，
        **不在别处重算计数**（重算=第二口径）。

        计数语义（S139 缺陷 4，见常量块注释）：未越门的被挡轮 +1；越门记录
        不动计数；publish 成功由 `_publish_ann_pair` 清零连续数。上一行读不出
        （缺行/坏 JSON/旧版无计数）按 0 起步——只影响"从哪格开始数"，不影响门。

        fail-open：观测面自身故障绝不改判、绝不抛出——门已经做完判决了，
        记不上账是"少一条痕迹"，不是"可以开火"。
        """
        prev_consecutive = 0
        prev_total = 0
        try:
            previous = json.loads(str(self.get_meta(_ANN_MEMORY_SKIP_META_KEY) or ""))
            if isinstance(previous, dict):
                prev_consecutive = max(0, int(previous.get(_ANN_MEMORY_SKIP_CONSECUTIVE_KEY) or 0))
                prev_total = max(0, int(previous.get(_ANN_MEMORY_SKIP_TOTAL_KEY) or 0))
        except Exception:  # noqa: S110, BLE001 - 无旧行/畸形旧行都按 0 起步（fail-open）。
            pass
        payload = dict(verdict.as_meta())
        payload["forced"] = forced
        payload["stage"] = stage
        payload["at_unix"] = int(time.time())
        if forced:
            payload[_ANN_MEMORY_SKIP_CONSECUTIVE_KEY] = prev_consecutive
            payload[_ANN_MEMORY_SKIP_TOTAL_KEY] = prev_total
        else:
            payload[_ANN_MEMORY_SKIP_CONSECUTIVE_KEY] = prev_consecutive + 1
            payload[_ANN_MEMORY_SKIP_TOTAL_KEY] = prev_total + 1
        try:
            self.set_meta(_ANN_MEMORY_SKIP_META_KEY, json.dumps(payload, ensure_ascii=False))
        except Exception:  # 记账失败不改变门判决（fail-open，观测面自身故障绝不改判）。
            logger.debug("ANN 内存门记账失败（不影响结论）", exc_info=True)
        return payload

    def _reset_ann_memory_skip_counters(self) -> None:
        """publish 成功后清零连续被挡计数（S139 缺陷 4 的另一半）。

        只改两枚计数、**保留上一轮被挡的全部度量**（available/required/…照旧
        在行里）——"上次被挡的规模与原因"是历史事实，重建成功不把它抹掉；
        清掉的是"连续"这个正在恶化的信号。无行/坏行 ⇒ 什么都不动（没有连续
        可言）。fail-open：清账故障绝不牵连已成功的 publish。
        """
        try:
            previous = json.loads(str(self.get_meta(_ANN_MEMORY_SKIP_META_KEY) or ""))
            if not isinstance(previous, dict):
                return
            previous[_ANN_MEMORY_SKIP_CONSECUTIVE_KEY] = 0
            self.set_meta(
                _ANN_MEMORY_SKIP_META_KEY, json.dumps(previous, ensure_ascii=False)
            )
        except Exception:  # 观测面故障不牵连已完成的发布（fail-open，与记账口同纪律）。
            logger.debug("ANN 内存门计数清零失败（不影响已发布的索引）", exc_info=True)

    def _require_ann_lock(self) -> None:
        """覆写线上 ANN 前的持锁凭证：无锁一律拒绝（不新增旁路写口）。"""
        gate = self._ann_build_gate
        if gate is None or not gate.held:
            raise RuntimeError(
                "拒绝在无跨进程建锁的情况下覆写 ANN 索引文件"
                "（请经 build_ann_index 入口，勿直调 _publish_ann_pair）"
            )

    def _publish_ann_pair(
        self, index: Any, chunk_ids: list[str], *, embed_generation: int | None = None
    ) -> dict:
        """原子成对换入 `.index` + `.order.json`，SQLite 代际证明作提交点。

        三步：①两文件先各自写同目录 `.tmp` 并 fsync（线上文件此刻未动）；
        ②`os.replace` 同卷原子换入（Windows 保证：读者要么看到完整旧版、
        要么看到完整新版，绝看不到半写文件）；③把这一代的指纹写进
        knowledge_meta 作为唯一提交点。第 ②/③ 步之间被击杀 → 线上两文件
        可能一新一旧，但代际证明仍是上一代，读方校验必失败并回落暴力扫描，
        因此"错配"永远不会被用于回答。

        第 ③ 步还落完备性计数戳（`_EMBEDDED_COUNT_KEY` := index.ntotal）：
        这是戳的**唯一权威赋值点**，此后只有补嵌写点能让它上涨。

        `embed_generation` 是这一代覆盖证明的另一半（S159）：**必须由建索引的
        人在打开读光标那一刻取值交进来**，不是本函数现读——重建是分钟级，
        中途另一路又提交了一批嵌入的话，现读会把「这一代索引根本没装的批次」
        给自己背书，守卫当场失效（行为锁
        tests/test_kb_pricing_guard_fts_s159.py::
        test_publish_records_build_start_generation）。缺省 None 按 0 落
        （fail-closed：写了 0 就等于什么都没背书，载入端继续拒用，等下一轮
        干净重建）——生产唯一调用点 `_build_ann_index_locked` 必须显式交值，
        别把它当可选参数省事。
        """
        self._require_ann_lock()
        index_path, order_path = self._ann_files()
        target_index = Path(index_path)
        target_order = Path(order_path)
        target_index.parent.mkdir(parents=True, exist_ok=True)
        suffix = f"{os.getpid()}.{threading.get_ident()}"
        tmp_index = target_index.with_name(f"{target_index.name}.{suffix}.tmp")
        tmp_order = target_order.with_name(f"{target_order.name}.{suffix}.tmp")
        try:
            faiss.write_index(index, str(tmp_index))
            payload = json.dumps(chunk_ids, ensure_ascii=False).encode("utf-8")
            with open(tmp_order, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_replace_from(tmp_index, target_index)
            _atomic_replace_from(tmp_order, target_order)
        except OSError as exc:
            for leftover in (tmp_index, tmp_order):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass
            raise RuntimeError(f"ANN 原子换入失败：{type(exc).__name__}: {exc}") from exc
        try:
            attestation = {
                "index_bytes": int(target_index.stat().st_size),
                "order_bytes": int(target_order.stat().st_size),
                "order_sha256": _sha256_file(target_order),
                "ntotal": int(index.ntotal),
                "count": len(chunk_ids),
                "signature": self.signature,
                # 覆盖证明的另一半（S159）：见本方法 docstring 的取值时机纪律。
                # 这里写字面量键是**必须**的——结构锁
                # ::test_generation_funnel_structure_locks ② 既要求本函数体内
                # 出现这个键名（证明真的盖了），又要求全仓只有
                # `certify_expected_vector_count` 能给它下标赋值（盖章口只有
                # 两处，字典字面量里建键不算第二个盖章口）。
                "embed_generation": int(embed_generation or 0),
            }
        except OSError as exc:
            raise RuntimeError(f"ANN 代际证明读取失败：{exc}") from exc
        # 提交点：先内容版本指纹、再成对代际证明（读方两道都要过才用）。
        self._set_stored_ann_signature(self.signature)
        self._write_ann_attestation(attestation)
        # 完备性计数戳落在这一步之后（权威基线 = 本代索引实装向量数）。
        # 顺序要紧：若在文件换入之后、落戳之前被杀，留下的是上一代的小值 ⇒
        # ntotal >= 戳 ⇒ 判可用——那个新索引本来就装满，判它可用是对的；
        # 反过来先落戳再换文件才会造出「戳新文件旧」的假短装、白回落暴力。
        self._stamp_expected_vector_count(int(index.ntotal))
        # 发布成功 ⇒ 内存门「连续被挡」计数清零（S139 缺陷 4 的清零腿；
        # fail-open，绝不牵连刚成功的 publish）。
        self._reset_ann_memory_skip_counters()
        self._drop_ann_cache()
        return {
            "ann_bytes": attestation["index_bytes"],
            "ann_attested": True,
        }

    def _build_ann_index_locked(
        self, on_progress=None, *, memory_verdict: _AnnMemoryVerdict | None = None
    ) -> dict:
        """重建主体。前置条件：调用方（build_ann_index）已同时持有进程内
        `_maintenance_lock` 与跨进程建锁闸——本方法不得再取维护锁（那是
        非重入 Lock，重取即自锁死）。覆写一律经 `_publish_ann_pair`。

        内存门复检（S112 立形、S118 接线）：传入 `memory_verdict`（= 前置检查
        未被越门跳过时）则每 `_ANN_BUILD_MEMORY_RECHECK_VECTORS` 条复检一次
        **剩余**需求。必要性：前置检查量的是"开火那一刻"，而重建是分钟级、
        同一台机器上爬虫正在写（S105 实测 10 分钟内可用内存 2.99 → 1.62 GiB）
        ——只查一次的门会被实况击穿。中途判定不足即**直接放弃整场重建**：
        此刻尚未走到 `_publish_ann_pair`，线上两文件一字未动、`.tmp` 一个未建，
        代价只是这一轮白跑（旧索引继续在位、闸继续拒用、暴力扫描照旧）。
        两条形态（S118 收线补的半条腿；此前两个辅助函数定义了却没接线，
        "注释承诺了一把不存在的锁"）：
        ① 规模已知 ⇒ 走 `_ann_projected_requirement_bytes`（模型价与**实测
           斜率**取大者自校准）；
        ② 规模未知（无戳且 MAX(rowid) 拿不到）⇒ 不断火，降级为
           `_ann_live_floor_bytes` 活体下限断路器——估不准≠免检，撑不过
           一批 + 观察余量就当场收火。
        越门路径（memory_verdict=None）不设复检：那是显式越门的既有语义，
        越门本身另记痕。
        """
        expected_total = memory_verdict.expected_vectors if memory_verdict else None
        dim = memory_verdict.dim if memory_verdict else self._ann_assumed_dimension()
        available_at_start = (
            memory_verdict.available_bytes if memory_verdict is not None else None
        )
        next_memory_check = (
            _ANN_BUILD_MEMORY_RECHECK_VECTORS if memory_verdict is not None else 0
        )
        generation_at_cursor_open: int | None = None
        with self._connect() as connection:
            # 代次盖章的取值时刻：**读向量的光标打开那一刻**（S159）。这一场重建
            # 装下的向量集合只可能覆盖到此刻为止已提交的嵌入批次；重建跑到一半
            # 另一路又补嵌了一批，那一批不在我读到的光标里，就不许被这一代背书
            # （publish 时现读 = 自己给自己盖章，见 `_publish_ann_pair` docstring）。
            generation_at_cursor_open = self._parse_embed_generation(
                self._read_meta_value_on(connection, _EMBED_GENERATION_KEY)
            )
            cursor = connection.execute(
                """
                SELECT chunk_id,
                       vector_blob,
                       CASE WHEN vector_blob IS NULL OR length(vector_blob) = 0
                            THEN vector_json ELSE NULL END AS vector_json
                FROM knowledge_chunks
                WHERE vector_json IS NOT NULL AND vector_json != ''
                """
            )
            chunk_ids: list[str] = []
            index = None
            while True:
                if next_memory_check and len(chunk_ids) >= next_memory_check:
                    available_now = _available_physical_memory_bytes()
                    if expected_total:
                        remaining = max(int(expected_total) - len(chunk_ids), 0)
                    else:
                        remaining = None
                    if remaining == 0:
                        # 计数戳是上界：装到它即可收尾，剩余量归零后无需再检。
                        next_memory_check = 0
                        recheck = None
                    else:
                        if remaining is not None:
                            required_now = _ann_projected_requirement_bytes(
                                remaining,
                                dim,
                                available_now=available_now,
                                available_at_start=available_at_start,
                                built_so_far=len(chunk_ids),
                            )
                        else:
                            required_now = _ann_live_floor_bytes(dim)
                        recheck = _AnnMemoryVerdict(
                            allowed=available_now is not None
                            and available_now >= required_now,
                            available_bytes=available_now,
                            required_bytes=int(required_now),
                            expected_vectors=remaining,
                            dim=int(dim),
                            probe_failed=available_now is None,
                        )
                        next_memory_check += _ANN_BUILD_MEMORY_RECHECK_VECTORS
                    if recheck is not None and not recheck.allowed:
                        recheck_meta = self._record_ann_memory_skip(
                            recheck, forced=False, stage="midway"
                        )
                        logger.warning(
                            "ANN 重建中途收火（内存门）：已装 %d/%s 条时"
                            "实测可用 %s < 剩余需求 %s（规模未知时按活体下限判）；"
                            "未 publish、线上索引一字未动，本轮等同跳过。",
                            len(chunk_ids),
                            expected_total if expected_total else "未知",
                            "无法测量"
                            if recheck.available_bytes is None
                            else f"{recheck.available_bytes / 1024**3:.2f}GiB",
                            f"{recheck.required_bytes / 1024**3:.2f}GiB",
                        )
                        return {
                            "built": False,
                            "reason": "insufficient_memory_midway",
                            "vectors_built_before_abort": len(chunk_ids),
                            "memory_gate": recheck_meta,
                        }
                rows = cursor.fetchmany(_ANN_BUILD_BATCH_SIZE)
                if not rows:
                    break
                batch_vectors: list = []
                for row in rows:
                    raw_blob = row["vector_blob"]
                    vector = None
                    if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                        try:
                            parsed = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                            if parsed.size > 0:
                                vector = parsed.astype(np.float32)
                        except Exception:  # noqa: BLE001
                            vector = None
                    if vector is None:
                        try:
                            vector = np.asarray(
                                json.loads(str(row["vector_json"])), dtype=np.float32
                            )
                        except (TypeError, ValueError, json.JSONDecodeError):
                            continue
                    batch_vectors.append(vector)
                    chunk_ids.append(str(row["chunk_id"]))
                if not batch_vectors:
                    continue
                matrix = np.vstack(batch_vectors).astype(np.float32)
                norms = np.linalg.norm(matrix, axis=1).astype(np.float32)
                matrix = (matrix / np.maximum(norms, np.float32(1e-9))[:, None]).astype(np.float32)
                if index is None:
                    try:
                        faiss.omp_set_num_threads(1)
                    except Exception:  # noqa: S110, BLE001 - 线程数设置失败按默认继续构建索引。
                        pass
                    dimension = int(matrix.shape[1])
                    index = _make_ann_index(dimension, connection=connection)
                    if index is None:
                        # 量化器取不到或训练样本为空 ⇒ 本轮**不建**。绝不退回
                        # fp32 偷偷建一副：那会让落盘体积与 `_ann_build_demand_bytes`
                        # 的位宽假设脱钩（门按 1 B/维收钱、实物却是 4 B/维）。
                        return {"built": False, "reason": "index_untrainable"}
                    index.hnsw.efConstruction = 200
                index.add(matrix)
                if on_progress is not None:
                    try:
                        on_progress(len(chunk_ids))
                    except Exception:  # noqa: S110, BLE001 - 进度回调失败不影响构建。
                        pass
        if index is None or not chunk_ids:
            self.ensure_fts_index()
            return {"built": False, "reason": "empty"}
        published = self._publish_ann_pair(
            index, chunk_ids, embed_generation=generation_at_cursor_open
        )
        # knowledge-sync 一次性构建：ANN 落盘后顺带幂等构建 FTS 关键词索引。
        self.ensure_fts_index(force=True)
        return {
            "built": True,
            "vectors": len(chunk_ids),
            "dim": int(index.d),
            **published,
        }

    def _stored_ann_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = 'ann_signature'"
            ).fetchone()
        return str(row[0]) if row else ""

    def _set_stored_ann_signature(self, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_meta (key, value) VALUES ('ann_signature', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (value,),
            )

    # ---------- ANN 完备性计数戳（参数块见 _EMBEDDED_COUNT_KEY）----------------

    def _read_ann_signature_pair_on(self, connection: Any) -> tuple[str, str]:
        """在**调用方连接**上一次取回 (stored_ann_signature, embedding_signature)。

        纠偏要在同一写事务里复核签名，不能走 `get_meta`/`_stored_ann_signature()`
        ——它们各自开新连接，而本事务正持着写锁：拿回来的既可能是另一条连接的
        旧快照，又可能把自己撞死在 `SQLITE_BUSY` 上。与 `_read_ann_attestation`
        （自开连接、给请求路径用）的分工就在这里，别混用。
        """
        row = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = 'ann_signature'"
        ).fetchone()
        live = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = 'embedding_signature'"
        ).fetchone()
        return (
            "" if row is None or row[0] is None else str(row[0]),
            "" if live is None or live[0] is None else str(live[0]),
        )

    def _read_meta_value_on(self, connection: Any, key: str) -> str:
        """在调用方连接上读一行 knowledge_meta；缺键/NULL ⇒ 空串。"""
        row = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = ?", (key,)
        ).fetchone()
        return "" if row is None or row[0] is None else str(row[0])

    def _attestation_dict_on(self, connection: Any) -> dict | None:
        """在调用方连接上读出**可改写**的代际证明字典；缺失/畸形 ⇒ None。

        与 `_read_ann_attestation()`（自开连接、给请求路径用）的分工同
        `_read_ann_signature_pair_on`：纠偏正持有 BEGIN IMMEDIATE 写锁，另开一条
        连接去读既是别人的旧快照、又可能把自己撞死在 SQLITE_BUSY 上。交回的是
        刚 `json.loads` 出来的新字典，改它不污染任何缓存。
        """
        raw = self._read_meta_value_on(connection, _ANN_ATTESTATION_KEY)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _stamped_expected_vector_count(self) -> int | None:
        """读「本代索引应覆盖多少条向量」的计数戳（独立读点，自愈链用它）。

        `knowledge_meta.key` 是 PRIMARY KEY，单行定位；这里绝不碰
        knowledge_chunks——那张表上 `COUNT(*) WHERE vector_json IS NOT NULL`
        实测 23.8s，进载入路径就是把每条消息的冷载入变成卡死。

        键缺席/畸形/负数一律返回 None = **不可判定**，而不是 0：按 0 处理会把
        「无从证明完备」洗成「一行都不该有 ⇒ 完美」，正好放行本闸要拦的那类库。
        判据折进 `_parse_expected_vector_count`，与载入路径那次三键合一查询
        共用同一个口径（两处各写一遍解析 = 迟早漂成两把尺）。
        """
        return self._parse_expected_vector_count(self.get_meta(_EMBEDDED_COUNT_KEY))

    @staticmethod
    def _parse_expected_vector_count(raw: str) -> int | None:
        """计数戳取数口径唯一真身：空/畸形/负值 ⇒ None（不可判定）。"""
        if not raw:
            return None
        try:
            stamped = int(str(raw).strip())
        except (TypeError, ValueError):
            return None
        return stamped if stamped >= 0 else None

    @staticmethod
    def _parse_embed_generation(raw: Any) -> int:
        """嵌入代次取数口径唯一真身：缺行/畸形/负值 ⇒ 0。

        取值先 `str()` 再解析，所以 JSON 里的整数正常入账、`True` 这类布尔垃圾
        只会折成 0（`int("True")` 抛错），不会把「写了个布尔」读成「已证过一批」。

        与计数戳**故意不同**：戳按 0 读会把「无从证明」洗成「一行都不该有」，
        所以它缺省是 None（不可判定）；代次按 0 读的含义是「从未证过任何提交
        批次」，方向上是**更严**（任何一批嵌入都会把它顶到 1 以上 ⇒ 守卫开火），
        而存量库两侧同时缺行时两边都是 0 ⇒ 与闸上线前逐字节同形
        （见 _EMBED_GENERATION_KEY 参数块）。
        """
        try:
            parsed = int(str(raw).strip())
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    def _generation_covered_by(self, attestation: dict | None) -> int:
        """本代代际证明背书到第几批（字段缺失/畸形 ⇒ 0 = 从未证过任何一批）。"""
        if not isinstance(attestation, dict):
            return 0
        return self._parse_embed_generation(
            attestation.get(_ATTEST_EMBED_GENERATION_FIELD)
        )

    def _embed_generation_now(self) -> int:
        """当前嵌入代次 = 已提交的向量写入批次数（写点见 `_save_vectors`）。"""
        return self._parse_embed_generation(self.get_meta(_EMBED_GENERATION_KEY))

    def _read_ann_guard_meta(self) -> tuple[int | None, int, dict | None]:
        """一发 IN 查询同取载入守卫的三件输入：计数戳 / 代次 / 代际证明。

        为什么合成一发：`knowledge_meta.key` 是 PRIMARY KEY，三键 IN 仍是主键
        SEARCH（`EXPLAIN QUERY PLAN` 锁在
        tests/test_kb_pricing_guard_fts_s159.py::test_combined_meta_read_uses_pk_search）
        ——拆开就是每次冷载入多两发往返，合起来才是「守卫不给请求路径添账」。
        只读 meta，绝不碰 knowledge_chunks。
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM knowledge_meta WHERE key IN (?, ?, ?)",
                (_EMBEDDED_COUNT_KEY, _EMBED_GENERATION_KEY, _ANN_ATTESTATION_KEY),
            ).fetchall()
        values = {
            str(row[0]): ("" if row[1] is None else str(row[1])) for row in rows
        }
        expected = self._parse_expected_vector_count(
            values.get(_EMBEDDED_COUNT_KEY, "")
        )
        generation = self._parse_embed_generation(
            values.get(_EMBED_GENERATION_KEY, "")
        )
        raw_attestation = values.get(_ANN_ATTESTATION_KEY, "")
        attestation: dict | None = None
        if raw_attestation:
            try:
                parsed = json.loads(raw_attestation)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                attestation = parsed
        return expected, generation, attestation

    def _attested_covered_generation(self) -> int:
        """代际证明里记下的「本代覆盖证到第几批」（独立读点，供告警/纠偏复核）。"""
        return self._generation_covered_by(self._read_ann_attestation())

    def _stamp_expected_vector_count(self, count: int) -> None:
        """把「本代索引该装多少条向量」写成完备性基线。

        调用者两处：`_publish_ann_pair` 的提交点（**唯一权威赋值点**，值 :=
        index.ntotal）与漂移纠偏（值 := SQLite 库侧 COUNT，且必须先把这一代
        证明到恒等——见 `reconcile_ann_completeness`）。名字里不写 publish 是有意的：
        把纠偏也并进"落戳"这个动作，门本身才知道两种来源都在这一个写口上。
        """
        self.set_meta(_EMBEDDED_COUNT_KEY, str(max(0, int(count))))

    def _stamp_reconcile_memory_reason(self) -> str | None:
        """纠偏的内存地板：够 ⇒ None；不够/不可判定 ⇒ 点名原因（fail-closed）。"""
        available = _available_physical_memory_bytes()
        if available is None:
            return "memory_probe_unavailable"
        if available < _ANN_STAMP_RECONCILE_MIN_AVAILABLE_BYTES:
            return "insufficient_memory"
        return None

    def reconcile_ann_completeness(
        self,
        connection: Any,
        *,
        db_embedded_count: int,
        max_items: int = _ANN_STAMP_RECONCILE_MAX_ITEMS,
    ) -> tuple[bool, str]:
        """零成本 + 集合级两道自证：这一代索引是否**正好**装满库里每一行已嵌向量。

        返回 `(是否放行落戳, 原因)`。成立须五件同时为真，缺一即拒并保持原戳：
        ① 代际证明在位且自洽（`ntotal == count`）；② 证明里的签名 == 当前签名，
        且库里两个签名行也一致（`ann_signature` 与 `embedding_signature` 存的都是
        `self.signature`，见常量块上方注释）；③ `.index` 与 `.order.json` 的体积与
        sha 与代际证明逐字相符（就地用同一连接与文件系统比对——不能调
        `_ann_pair_consistent`，它会另开连接来读证明而本事务正持写锁）；
        ④ 实读 faiss 的 ntotal == 库侧 COUNT（faiss 不可用 ⇒ 拒，原因
        `index_does_not_cover_embedded_rows`——判据不许"读不到就放行"）；
        ⑤ **集合级**：序列表与库侧已嵌 chunk_id 两向差集皆空。

        ⑤ 是这道判据的全部价值。光比条数拦不住"删 20 补 20"：库侧条数与 ntotal
        恒等，索引里却装着 20 条已不存在的 id、还缺 20 条新行——计数版会把它判成
        完备并落戳放行，检索继续用错邻居回答且再也不告警。计数相等只是**必要条件**，
        集合相等才是**充分条件**。

        戳的**值**永远只来自 `db_embedded_count`（调用方事务内的 COUNT），本函数
        一个字都不写。取数方向反过来就是掏空这道闸（同 `test_ann_certify_prewarm`
        的陷阱锁）。
        """
        attestation_raw = self._read_meta_value_on(connection, _ANN_ATTESTATION_KEY)
        if not attestation_raw:
            return False, "no_attestation"
        try:
            attestation = json.loads(attestation_raw)
        except (TypeError, ValueError):
            return False, "no_attestation"
        if not isinstance(attestation, dict):
            return False, "no_attestation"
        try:
            attested_ntotal = int(attestation["ntotal"])
            attested_count = int(attestation["count"])
        except (KeyError, TypeError, ValueError):
            return False, "attestation_self_inconsistent"
        if attested_ntotal != attested_count:
            return False, "attestation_self_inconsistent"
        attested_signature = str(attestation.get("signature") or "")
        stored_signature, embedding_signature = self._read_ann_signature_pair_on(connection)
        if (
            not attested_signature
            or attested_signature != self.signature
            or stored_signature != self.signature
            or (embedding_signature and embedding_signature != self.signature)
        ):
            return False, "signature_mismatch"
        index_path, order_path = self._ann_files()
        # 成对性就地复核：这里**不能**调 `_ann_pair_consistent()`——它内部走
        # `_read_ann_attestation()`，会另开一条连接来读 knowledge_meta，而本事务
        # 正持着 BEGIN IMMEDIATE 写锁（要么撞 SQLITE_BUSY、要么读到另一条连接的
        # 旧快照）。判据与那条方法逐字同形，只是取数换成同一连接 + 文件系统。
        try:
            index_size = int(Path(index_path).stat().st_size)
            order_size = int(Path(order_path).stat().st_size)
            attested_sha = str(attestation.get("order_sha256") or "")
            actual_sha = _sha256_file(Path(order_path)) if attested_sha else ""
        except OSError:
            return False, "pair_files_inconsistent"
        if int(attestation.get("index_bytes", -1) or -1) != index_size:
            return False, "pair_files_inconsistent"
        if int(attestation.get("order_bytes", -1) or -1) != order_size:
            return False, "pair_files_inconsistent"
        if attested_sha and actual_sha != attested_sha:
            return False, "pair_files_inconsistent"
        if db_embedded_count > max_items or attested_ntotal > max_items:
            return False, "too_large_for_set_proof"
        try:
            if faiss is None:
                return False, "index_does_not_cover_embedded_rows"
            live_index = faiss.read_index(str(index_path), faiss.IO_FLAG_MMAP)
        except Exception:  # noqa: BLE001 - 读不到 ntotal 就是无从证明，不许放行。
            return False, "index_does_not_cover_embedded_rows"
        if int(live_index.ntotal) != db_embedded_count:
            # 真短装/真多出都从这里出去：闸继续红是**对的**，出路只有重建。
            return False, "index_does_not_cover_embedded_rows"
        try:
            order = json.loads(Path(order_path).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return False, "pair_files_inconsistent"
        if not isinstance(order, list) or len(order) != db_embedded_count:
            return False, "id_set_mismatch"
        outstanding = {str(item) for item in order}
        missing_in_order = 0
        for row in connection.execute(
            "SELECT chunk_id FROM knowledge_chunks "
            "WHERE vector_json IS NOT NULL AND vector_json != ''"
        ):
            chunk_id = str(row[0])
            if chunk_id in outstanding:
                outstanding.discard(chunk_id)
            else:
                missing_in_order += 1
                if missing_in_order > 5:
                    break
        if missing_in_order or outstanding:
            return False, "id_set_mismatch"
        return True, ""

    def certify_expected_vector_count(self, *, drift_correction: bool = False) -> int | None:
        """维护路径专用：给从未认证过的存量库补盖计数戳；返回新落的戳值，
        活戳在位或失败返回 None（活戳归重建线所有，certify 一字不碰）。

        背景（#47 闸的自愈闭环，certify-prewarm 波 P1）：戳的权威赋值点只有
        发布提交点、涨点只有补嵌——而存量生产库既没戳、也再无新嵌入，kb-sync
        零变更夜又跳过重建（unchanged_skip），写点涨戳在无戳库上刻意空转
        ⇒ 该库会被「无戳=不可判定」永远拒用，每条查询付暴力回落的代价
        （wiki 248k 块实测：稳态 +3.6s、首查 33.6s、每问再涨 1GB 驻留）。
        本方法给这一类库一次权威认证：COUNT 已嵌入行数落戳。生产实测该扫描
        persona 13.2s / wiki 33.5s，所以只允许出现在维护线程（同步任务的
        跳过分支、operator CLI、显式重建的跳过源），**绝不上请求路径**。
        〔2026-09-26 冷缓存口径补充：同一发 COUNT 在 WAL 1.5 GB、索引刚发布后的
        生产库上实测 327.7s（集合级比对另加 240.2s）——上面那两个数是热缓存值，
        拿它排夜间窗口会低估十倍。〕

        ⚠ 关键陷阱——戳值只许来自 SQLite 已嵌入行 COUNT，禁止取 index.ntotal：
        拿 ntotal 落戳等于允许任何索引（包括真短装的）自我认证，
        `ntotal >= stamp` 恒成立，完备性闸就此名存实亡。本闸的价值恰恰在
        「库侧行数裁决文件侧索引」，落戳方向一旦反过来，闸就白建。

        原子性：查无活戳与落戳在同一条 BEGIN IMMEDIATE 写事务内完成
        （billing_service 同族手法）——防补嵌恰好在「读到无戳」与「写戳」
        之间提交而涨戳空转（那会造出一个偏低的戳 = 漏拒方向，危险侧）。
        活戳判据与读端 `_stamped_expected_vector_count` 同式：非空且可解析
        且 >=0 即活戳；空/缺键/畸形/负值视为「从未认证成功」，补盖权威值。
        `drift_correction=True` 是**显式 opt-in**（缺省 False ⇒ 与本件诞生前逐字节
        同形，smoke 与 knowledge_service 两条既有调用者行为一字不变；kb-sync 零变更
        夜已改为显式开门，见 `kb_wiki.py` 的 `unchanged_skip` 分支）：
        活戳在位且戳**高于**库侧真值时，先让 `reconcile_ann_completeness` 把这一代
        证明到恒等，成立才把戳描回库真值。不成立的原因一律点名进日志，闭集见
        `_STAMP_RECONCILE_REASONS`；纠偏**只降不升**（戳偏低 = 涨点漏了，那归重建线）。
        """
        if drift_correction:
            probe_reason = self._stamp_reconcile_memory_reason()
            if probe_reason is not None:
                logger.warning(
                    "knowledge ANN completeness stamp reconcile refused "
                    "(reason=%s db=%s) — 集合级自证要流式读两份数十万项 id，"
                    "地板之下不跑；戳保持原样，闸继续拒用 ANN（暴力扫描）。",
                    probe_reason,
                    self.db_path,
                )
                return None
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT value FROM knowledge_meta WHERE key = ?",
                    (_EMBEDDED_COUNT_KEY,),
                ).fetchone()
                raw = "" if row is None or row[0] is None else str(row[0]).strip()
                existing = -1
                if raw:
                    try:
                        existing = int(raw)
                    except (TypeError, ValueError):
                        existing = -1  # 畸形 = 读端本就判不可用，按无戳处理
                    if existing >= 0 and not drift_correction:
                        return None  # 活戳：重建线的所有物，certify 不覆写
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM knowledge_chunks "
                        "WHERE vector_json IS NOT NULL AND vector_json != ''"
                    ).fetchone()[0]
                )
                if existing >= 0:
                    # 漂移纠偏：只降不升，且必须先过集合级自证（见其 docstring）。
                    # 整段在同一 BEGIN IMMEDIATE 事务内完成——「证明」与「落戳」之间
                    # 不许有任何别的写者插进来，否则落下的是一条没复核过的值。
                    if existing == count:
                        reason = "stamp_matches_db_count"
                    elif existing < count:
                        reason = "stamp_below_db_count"
                    else:
                        ok, reason = self.reconcile_ann_completeness(
                            connection, db_embedded_count=count
                        )
                        if ok:
                            self._stamp_expected_vector_count(count)
                            # 盖章点之二（S159）：集合级自证成立 = 这一代索引**逐行**
                            # 覆盖库里每一行已嵌向量，覆盖证明里的代次必须跟到位；
                            # 不跟的话纠偏成功了守卫又不认账，判据自相矛盾、库被永久
                            # 钉在暴力扫描上（行为锁 tests/test_kb_pricing_guard_fts_
                            # s159.py::test_reconcile_success_advances_covered_generation）。
                            # 与落戳同事务、同一把连接：分开写就留下「戳新代旧」的半
                            # 提交态。反面纪律一样要紧——本方法的**无戳补盖**那条路
                            # （下面的缺省分支）一个字都不盖：它只 COUNT 库侧行数、
                            # 没做过任何集合级自证，盖了就是拿落戳洗代次。
                            attested = self._attestation_dict_on(connection)
                            if attested is not None:
                                attested["embed_generation"] = self._parse_embed_generation(
                                    self._read_meta_value_on(
                                        connection, _EMBED_GENERATION_KEY
                                    )
                                )
                                connection.execute(
                                    "INSERT INTO knowledge_meta (key, value) "
                                    "VALUES (?, ?) "
                                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                                    (
                                        _ANN_ATTESTATION_KEY,
                                        json.dumps(attested, ensure_ascii=False),
                                    ),
                                )
                            logger.info(
                                "knowledge ANN completeness stamp reconciled: "
                                "%d -> %d (db=%s) — 本代已证明逐行覆盖 %d 条已嵌向量。",
                                existing,
                                count,
                                self.db_path,
                                count,
                            )
                            return count
                    logger.warning(
                        "knowledge ANN completeness stamp reconcile refused "
                        "(reason=%s existing=%d db_count=%d db=%s) — 戳保持原样；"
                        "该走重建线的走重建线，纠偏不替它作主。",
                        reason,
                        existing,
                        count,
                        self.db_path,
                    )
                    return None
                connection.execute(
                    "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (_EMBEDDED_COUNT_KEY, str(count)),
                )
        except sqlite3.Error as exc:
            logger.warning(
                "knowledge ANN certify skipped (db error %s): %s",
                type(exc).__name__,
                self.db_path,
            )
            if drift_correction:
                logger.warning(
                    "knowledge ANN completeness stamp reconcile refused "
                    "(reason=db_error db=%s) — 事务没走完，戳不动。",
                    self.db_path,
                )
            return None
        logger.info(
            "knowledge ANN completeness certified: expected=%d db=%s",
            count,
            self.db_path,
        )
        return count

    @staticmethod
    def _bump_expected_vector_count(
        connection: sqlite3.Connection, delta: int
    ) -> None:
        """在调用方**同一事务内**把计数戳推进 delta（只供唯一写点调用）。

        同事务是要点：戳与向量必须一起提交或一起回滚，否则回滚后留下虚高的戳
        = 永久假短装。无戳不建戳：缺席代表这块库从未被新代码认证过，从 0 起算
        会造出一个远小于真实向量数的戳（存量库上万行嵌于建戳之前即此坑），反倒
        把短装洗成正常。让它继续缺席 ⇒ 载入端按不可判定拒绝 ⇒ 交给 knowledge-sync
        重建来认证。
        """
        if delta <= 0:
            return
        row = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = ?",
            (_EMBEDDED_COUNT_KEY,),
        ).fetchone()
        if row is None or row[0] is None or str(row[0]).strip() == "":
            return
        try:
            current = int(str(row[0]).strip())
        except (TypeError, ValueError):
            return
        connection.execute(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_EMBEDDED_COUNT_KEY, str(max(0, current) + int(delta))),
        )

    @staticmethod
    def _advance_embed_generation(
        connection: sqlite3.Connection, *, batches: int = 1
    ) -> None:
        """在调用方**同一事务内**把嵌入代次推进 `batches` 批（唯一代次写点）。

        只供 `_save_vectors` 调用（禁区锁 tests/test_kb_pricing_guard_fts_s159.py
        ::test_generation_funnel_structure_locks ① 把它钉成一个点，第二处调用
        当场红）——代次的全部意义就是「有向量落库了」，写点一旦不唯一，它就退化成
        又一个可以被人顺手刷掉的标量。

        与 `_bump_expected_vector_count` 的两处不同，都是故意的：
        ① 按**批**计不按条计：守卫要的是「有没有过新的提交点」，不是行数；
           按条计会把代次顶成一个和 ntotal 同量级的数，与计数戳失去区分度；
        ② **缺行照建**（从 0 起算）：戳不能凭空建（凭空造出的小戳 = 漏拒方向，
           危险侧），代次却相反——凭空建一个 1 只会让守卫更早开火（更严侧），
           而无戳库补嵌时若不涨代次，「删+嵌同轮」这个洞在无戳存量库上就没人拦
           （行为锁 ::test_generation_bump_survives_stamp_absent_store）。
        """
        if batches <= 0:
            return
        row = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = ?",
            (_EMBED_GENERATION_KEY,),
        ).fetchone()
        # 取数走 `_parse_embed_generation` 同一个口径（缺行/畸形/负值都折成 0），
        # 不在这里再写一遍 int() 解析——那是第二把尺。
        current = SqliteVectorKnowledgeStore._parse_embed_generation(
            None if row is None else row[0]
        )
        connection.execute(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_EMBED_GENERATION_KEY, str(current + int(batches))),
        )

    @staticmethod
    def _lower_expected_vector_count(
        connection: sqlite3.Connection, removed: int
    ) -> None:
        """在调用方**同一事务内**把计数戳拉低 removed。

        调用者只有三处漏斗：`_forget_chunks`（按谓词删块）、`_clear_all_vectors`
        （全库清）、`_null_out_chunk_vector`（内容变更清单行）。别在它们外面加第四处
        调用——更要紧的是别在任何删除点裸写 SQL，那正是今晚漂移的出生方式。

        这是 #47 那把闸的**对称半圈**，补的是它自己注释里承认却没治的形态：
        戳原来只由唯一写点单向上推（`_bump_expected_vector_count`），删掉已嵌行、
        内容变更清向量、auto_reset 清全库都不拉低 ⇒ 戳必然虚高。虚高在零变更夜
        是**永久**的（重建线不达、certify 又不碰活戳）——2026-09-26 生产实测的
        missing=432 就是这么来的：02:56 发布之后又涨了 432 条，那 432 行随后被删。

        方向上的取舍要说清：拉低会让 `ntotal > 戳`（索引里可能留着已不存在行的
        向量）——这**不是**本闸要拦的病，常量块注释早已把"多出向量"判为可容忍
        （发布中途被杀的残态就是这个形状）；闸拦的是"索引少装了新行"。所以对称
        记账只收危险侧：戳从此恒等于"库里到底有多少行带向量"，两头都不漂。

        与涨戳同规的 fail-closed：库里没有活戳时**不凭空建戳**（从 0 起算会造出
        一个远小于真实向量数的戳 = 漏拒方向，危险侧），保持缺席交给认证/重建线。
        """
        if removed <= 0:
            return
        row = connection.execute(
            "SELECT value FROM knowledge_meta WHERE key = ?",
            (_EMBEDDED_COUNT_KEY,),
        ).fetchone()
        if row is None or row[0] is None or str(row[0]).strip() == "":
            return
        try:
            current = int(str(row[0]).strip())
        except (TypeError, ValueError):
            return
        connection.execute(
            "INSERT INTO knowledge_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_EMBEDDED_COUNT_KEY, str(max(0, current - int(removed)))),
        )

    def _forget_chunks(
        self,
        connection: sqlite3.Connection,
        *,
        where: str,
        params: tuple = (),
    ) -> int:
        """按谓词删块，并把这次带走的向量数记进计数戳——删除路径的**唯一漏斗**。

        顺序不能反：先删就数不到被删的那批。谓词由调用方显式给（不从 SQL 里拆——
        拆字符串会把「谓词里含 WHERE」这种写法判成两半）。**别把这里读成"数与删同事务"**——
        pysqlite 只在写语句前隐式 BEGIN，那次 COUNT 读其实落在事务外；真正挡住
        "并发嵌入被数漏"的是调用方持有的 `self._lock` 加单写者纪律（kb-sync 全程
        一把进程级互斥）。方向上要说清残留风险有多小：数漏 ⇒ 少降 ⇒ 戳偏高 ⇒ 多拒
        （安全侧）；只有"数多"才危险，而"数多"要另一条连接在 DELETE 之前恰好提交
        一批新向量，且我们**故意**让跨进程并发删除者存在——全仓 grep 除本漏斗外
        零处裸删 chunk，不成立。真要收紧就在这里显式 BEGIN IMMEDIATE，代价是把
        读窗口也锁进写事务。
        """
        removed = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE vector_json IS NOT NULL AND vector_json != '' "
                f"AND ({where})",
                params,
            ).fetchone()[0]
        )
        cursor = connection.execute(
            f"DELETE FROM knowledge_chunks WHERE {where}", params
        )
        self._lower_expected_vector_count(connection, removed)
        return int(cursor.rowcount or 0)

    def _clear_all_vectors(self, connection: sqlite3.Connection) -> int:
        """全库清向量（auto_reset / 换代形态）的记账：清完戳就该是 0。"""
        removed = int(
            connection.execute(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE vector_json IS NOT NULL AND vector_json != ''"
            ).fetchone()[0]
        )
        connection.execute("UPDATE knowledge_chunks SET vector_json = NULL")
        self._lower_expected_vector_count(connection, removed)
        return removed

    def _null_out_chunk_vector(
        self,
        connection: sqlite3.Connection,
        *,
        source_id: str,
        content: str,
        content_hash: str,
        chunk_id: str,
        had_vector: bool,
    ) -> None:
        """单行向量作废的唯一出口（内容变更路径）：置 NULL 与拉低戳同事务、同漏斗。

        `had_vector` 必须由调用方从**已有那次 SELECT** 带进来，这里不再发
        第二条查询——这条路径在每篇文档的每块上都走一遍，多一发查询就是多一倍 I/O。
        """
        connection.execute(
            """
            UPDATE knowledge_chunks
            SET source_id = ?, title = ?, content = ?,
                content_hash = ?, vector_json = NULL
            WHERE chunk_id = ?
            """,
            (source_id, source_id, content, content_hash, chunk_id),
        )
        self._lower_expected_vector_count(connection, 1 if had_vector else 0)

    def _load_vector_cache(self):
        """把全部向量一次性载入 numpy 矩阵并缓存；只保留 chunk_id，正文懒加载。

        R3 停摆批改造：流式 fetchmany + blob 优先 + 单飞构建。
        旧实现全表 fetchall 同时物化 vector_json 文本（kb_wiki 23.8 万行 ×
        ~20KB 文本 + blob ≈ 库文件 5.7GB 全部过 Python 手），首载即 GB 级
        内存尖峰 + 分钟级 JSON 解析；现逐批读取，blob（4 字节/维 float32）
        命中即收，JSON 通道只对 blob 缺失/损坏的残行按批二次查询。
        构建由 _vector_cache_build_lock 单飞互斥（并发首载只做一次），
        热缓存读取路径零锁开销。
        """
        if self._vector_cache is not None and self._vector_meta is not None:
            return self._vector_cache, self._vector_meta
        with self._vector_cache_build_lock:
            if self._vector_cache is not None and self._vector_meta is not None:
                return self._vector_cache, self._vector_meta
            matrix, chunk_ids = self._build_vector_cache()
            # 全库无向量返回 (None, None)：与旧实现一致不驻留"空缓存"标记，
            # 但空表重扫成本趋近于零，不值得引入哨兵对象。
            self._vector_cache = matrix
            self._vector_meta = chunk_ids if matrix is not None else None
            return self._vector_cache, self._vector_meta

    def _build_vector_cache(self):
        """流式全表读取向量，构建 (matrix|None, chunk_ids|None)；不取检索锁。

        锁序约束：调用方持有 _vector_cache_build_lock，本方法内部绝不取
        self._lock（否则锁外预热会与检索路径成环）。行序 = 表序，与旧实现
        一致（chunk_ids 与矩阵行对齐）。
        """
        vectors: list = []
        chunk_ids: list[str] = []
        blob_miss_ids: list[str] = []
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT chunk_id, vector_blob
                FROM knowledge_chunks
                WHERE vector_json IS NOT NULL AND vector_json != ''
                """
            )
            while True:
                rows = cursor.fetchmany(_VECTOR_CACHE_LOAD_BATCH_SIZE)
                if not rows:
                    break
                for row in rows:
                    raw_blob = row["vector_blob"]
                    vector = None
                    if isinstance(raw_blob, (bytes, bytearray, memoryview)):
                        try:
                            parsed = np.frombuffer(bytes(raw_blob), dtype=np.float32)
                            if parsed.size > 0:
                                vector = parsed.astype(np.float32)
                        except Exception:  # noqa: BLE001 - 单行向量解码失败走 JSON 兜底。
                            vector = None
                    if vector is None:
                        blob_miss_ids.append(str(row["chunk_id"]))
                        continue
                    vectors.append(vector)
                    chunk_ids.append(str(row["chunk_id"]))
            # blob 缺失/损坏的残行回退 JSON 通道（有界分批 IN 查询，不整表取文本）。
            for start in range(0, len(blob_miss_ids), 500):
                batch_ids = blob_miss_ids[start : start + 500]
                placeholders = ",".join("?" for _ in batch_ids)
                try:
                    json_rows = connection.execute(
                        "SELECT chunk_id, vector_json FROM knowledge_chunks "
                        f"WHERE chunk_id IN ({placeholders})",
                        batch_ids,
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for row in json_rows:
                    try:
                        vector = json.loads(str(row["vector_json"]))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if vector:
                        vectors.append(np.asarray(vector, dtype=np.float32))
                        chunk_ids.append(str(row["chunk_id"]))
        if not vectors:
            return None, None
        return np.vstack(vectors).astype(np.float32), chunk_ids

    def _pending_rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT chunk_id, content
                    FROM knowledge_chunks
                    WHERE vector_json IS NULL OR vector_json = ''
                    """
                ).fetchall()
            )

    def _vector_rows(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT chunk_id, source_id, title, content, vector_json
                    FROM knowledge_chunks
                    WHERE vector_json IS NOT NULL AND vector_json != ''
                    """
                ).fetchall()
            )

    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        try:
            result = self.embed_provider.embed_texts(list(texts))
        except Exception:  # noqa: BLE001 - 嵌入服务失败时返回 None 表示重试/降级。
            return None
        if not isinstance(result, list) or len(result) != len(texts):
            return None
        return result

    def _save_vectors(
        self,
        rows: list[sqlite3.Row],
        vectors: list[list[float]],
    ) -> bool:
        # 维度一致性守卫：本地/远程嵌入链回退可能产出不同维度，混入后
        # numpy 路径会静默退化成 zip 截断的伪余弦，min_cosine_threshold 失真。
        lengths = {len(vector) for vector in vectors if vector}
        if len(lengths) != 1:
            return False
        with self._lock:
            stored_dim = self._vector_dim
        if stored_dim is not None and lengths and next(iter(lengths)) != stored_dim:
            return False
        try:
            with self._connect() as connection:
                saved = 0
                for row, vector in zip(rows, vectors):
                    connection.execute(
                        "UPDATE knowledge_chunks SET vector_json = ?, vector_blob = ? WHERE chunk_id = ?",
                        (
                            json.dumps(vector),
                            struct.pack(f"<{len(vector)}f", *vector),
                            str(row["chunk_id"]),
                        ),
                    )
                    saved += 1
                if stored_dim is None and lengths:
                    connection.execute(
                        "INSERT INTO knowledge_meta (key, value) VALUES ('vector_dim', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(next(iter(lengths))),),
                    )
                # 完备性计数戳与向量同事务推进（本方法全库唯一写点，见
                # _EMBEDDED_COUNT_KEY 参数块）：落一行向量 = 索引短一行。
                self._bump_expected_vector_count(connection, saved)
                # 嵌入代次与向量**同事务**推进（S159，见 _EMBED_GENERATION_KEY）：
                # 本方法全库唯一向量写点，也是代次唯一推进点。同事务是要点——
                # 回滚留下涨过的代次 = 白拒一轮（安全侧），提交却没涨代次 = 今晚
                # 那个假绿（危险侧），所以两个方向都比戳更值得写在一起。
                # 一批 +1（按批不按条），saved=0 的空调用不推进（否则空转刷代次）。
                if saved > 0:
                    self._advance_embed_generation(connection)
            if stored_dim is None and lengths:
                with self._lock:
                    self._vector_dim = next(iter(lengths))
            self._invalidate_vector_cache()
            return True
        except (TypeError, ValueError, sqlite3.Error):
            return False

    # ---------- FTS5 BM25 关键词通道 -----------------------------------------

    def ensure_fts_index(self, *, force: bool = False) -> bool:
        """幂等地确保 FTS5 trigram 关键词索引可用（返回 True/False）。

        knowledge_meta 中已有非空 fts_signature 时直接复用，避免每条消息
        全量重建或全表扫描；内容刚变化（sync_chunks/sync_documents 会清掉
        该签名）或首次构建时才全量重建一次。签名由 chunk_id + content_hash
        聚合派生。``force=True`` 供显式同步任务绕过 fts_auto_rebuild=False。
        """
        with self._lock:
            # 快路径（本机延迟压榨项）：状态已确认（True 可用 / False 不可用）
            # 时直接返回，不再每条消息重复执行 sqlite_master 探查 + 签名
            # SELECT（关键词 + 词条两通道各调一次，合计 4 次往返/条）。
            # 内容变化由 _invalidate_fts 复位为 None 强制重新探查。
            if self._fts_valid is not None:
                return self._fts_valid
            try:
                self._ensure_fts_table()
                stored = self._stored_fts_signature()
                if stored:
                    # 非空签名说明索引与当前行集合匹配（内容变化时签名已被清空），
                    # 同时兼容 knowledge-sync 进程刚建好、运行期直接复用的情况。
                    self._fts_valid = True
                    return True
                if not force and not self.fts_auto_rebuild:
                    # 大库内联重建分钟级，会卡死消息处理：降级为纯向量通道，
                    # 等显式同步任务 force 重建。不置 _fts_valid=False，
                    # 重建完成后本进程可立即恢复关键词通道。
                    return False
                rebuilt = self._rebuild_fts()
                if rebuilt:
                    self._fts_valid = True
                    return True
                if self._stored_fts_signature():
                    # 本进程重建失败但可能由另一进程完成：信任已落库的签名。
                    self._fts_valid = True
                    return True
                self._fts_valid = False
                return False
            except Exception:  # noqa: BLE001 - FTS5 缺失/损坏时禁用关键词通道。
                self._fts_valid = False
                return False

    def fts_index_status(self) -> dict[str, Any]:
        """关键词通道（FTS5）的真值快照：行数 / 内容签名 / 表是否在位。

        为什么要这一口：ANN 被内存门挡下的那一轮，kb-sync 收尾照样会喂 FTS
        （见 `domains/location/knowledge/kb_wiki.py` 收尾的 ensure），可"喂了"
        与"喂进去多少行"此前没有任何一处报得出来——报不出来就等于没喂。
        取数只有两个来源，都是真身：行数是**真表 `COUNT(*)`**、签名是**真
        meta 行**（走 `_stored_fts_signature()`，不另立第二口径）。绝不读
        `_fts_valid` 缓存——那是本进程判定的快照，拿它冒充"库里现在有多少行"
        就是把观测面接进了猜测面。

        ⚠ 只住维护线程：数十万行的 `COUNT(*)` 是实打实的全表计数，绝不允许
        进 `retrieve` 请求路径（禁区锁 tests/test_kb_pricing_guard_fts_s159.py
        ::test_fts_status_never_on_request_path 钉死）。表缺席时 rows=0、
        signature=""，如实报空、不造数。
        """
        with self._connect() as connection:
            present = (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (_FTS_TABLE_NAME,),
                ).fetchone()
                is not None
            )
            rows = (
                int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {_FTS_TABLE_NAME}"
                    ).fetchone()[0]
                )
                if present
                else 0
            )
        signature = str(self._stored_fts_signature()) if present else ""
        return {"rows": rows, "signature": signature, "table_present": present}

    def _invalidate_fts(self) -> None:
        """内容变化后强制重探 FTS 通道（下一次访问重读签名/必要时重建）。

        必须无条件复位（含 True→None）：共享 store 进程内同步后 FTS 表
        已是旧行集合，若保留 True 快路径会让关键词通道一直命中被删文档
        的过期 chunk_id（_fetch_chunks 静默丢弃 → 召回静默劣化）。探查
        只有两条轻量查询，复位成本低。
        """
        self._fts_valid = None

    def _ensure_fts_table(self) -> None:
        """确保 FTS5 trigram 虚拟表存在；不可用时抛异常由调用方降级。"""
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_FTS_TABLE_NAME,),
            ).fetchone()
            if existing is None:
                connection.execute(_FTS_CREATE_SQL)

    def _stored_fts_signature(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM knowledge_meta WHERE key = ?",
                (_FTS_SIGNATURE_KEY,),
            ).fetchone()
        return str(row[0]) if row else ""

    def _rebuild_fts(self) -> str | None:
        """全量重建 FTS 索引并写入内容签名；失败返回 None。

        只在知识库内容变化或首次构建时调用一次；签名由 chunk_id +
        content_hash 聚合派生（与向量索引同源，反映同一批行）。
        """
        try:
            with self._connect() as connection:
                digest = hashlib.sha1()
                cursor = connection.execute(
                    "SELECT chunk_id, content_hash FROM knowledge_chunks ORDER BY chunk_id"
                )
                for row in cursor:
                    digest.update(
                        f"{row['chunk_id']}:{row['content_hash'] or ''}|".encode()
                    )
                cursor.close()
                signature = digest.hexdigest()

                connection.execute(f"DROP TABLE IF EXISTS {_FTS_TABLE_NAME}")
                connection.execute(_FTS_CREATE_SQL)
                cursor = connection.execute(
                    "SELECT chunk_id, title, content FROM knowledge_chunks ORDER BY chunk_id"
                )
                for row in cursor:
                    connection.execute(
                        f"INSERT INTO {_FTS_TABLE_NAME} (chunk_id, title, content) "
                        "VALUES (?, ?, ?)",
                        (
                            str(row["chunk_id"]),
                            str(row["title"] or ""),
                            str(row["content"] or ""),
                        ),
                    )
                cursor.close()
                connection.execute(
                    """
                    INSERT INTO knowledge_meta (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (_FTS_SIGNATURE_KEY, signature),
                )
            return signature
        except sqlite3.Error:
            return None

    def _match_candidates(self, terms: list[str], limit: int) -> list[str]:
        """FTS5 trigram MATCH + bm25() 排名；只接受 >=3 字符的词。"""
        match_terms = [term for term in terms if len(term) >= _FTS_MIN_MATCH_CHARS]
        if not match_terms or limit <= 0:
            return []
        query = " OR ".join(match_terms)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM {_FTS_TABLE_NAME}
                WHERE {_FTS_TABLE_NAME} MATCH ?
                ORDER BY bm25({_FTS_TABLE_NAME})
                LIMIT ?
                """,
                (query, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _title_like_candidates(self, terms: list[str], limit: int) -> list[str]:
        """1~2 字符词退化为 title LIKE（title 短、扫描成本低），按命中词数排序。"""
        if not terms or limit <= 0:
            return []
        conditions: list[str] = []
        params: list[str] = []
        for term in terms:
            conditions.append("title LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(term)}%")
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT title FROM knowledge_chunks WHERE {' OR '.join(conditions)}",
                params,
            ).fetchall()
            titles = sorted(
                {str(row["title"]) for row in rows},
                key=lambda title: (
                    -sum(1 for term in terms if term in str(title).lower()),
                    str(title),
                ),
            )
        ranked: list[str] = []
        if not titles:
            return ranked
        with self._connect() as connection:
            for title in titles:
                remaining = max(0, int(limit)) - len(ranked)
                if remaining <= 0:
                    break
                rows = connection.execute(
                    "SELECT chunk_id FROM knowledge_chunks "
                    "WHERE title = ? ORDER BY chunk_id LIMIT ?",
                    (title, remaining),
                ).fetchall()
                ranked.extend(str(row["chunk_id"]) for row in rows)
        return ranked

    def _phrase_match_candidates(self, query_text: str, limit: int) -> list[str]:
        """整段中文/英数词直接做 trigram MATCH（中文需 >=3 字才可被 trigram 命中）。

        ``_query_terms`` 只产中文二元组，永远无法触发 >=3 字的 trigram 索引；
        本方法把原始查询里的连续中文片段拆成 3 字滑窗（长片段整体匹配不到时
        仍能靠“守岸人/黑海岸”这类 3 字串命中），加英文数字词，再按 bm25() 排序。
        """
        if limit <= 0:
            return []
        phrases: list[str] = []
        for match in _CJK_RE.finditer(query_text or ""):
            segment = match.group(0)
            if len(segment) >= _FTS_MIN_MATCH_CHARS:
                if len(segment) <= 6:
                    phrases.append(segment)
                for index in range(len(segment) - 2):
                    phrases.append(segment[index : index + 3])
        phrases.extend(match.group(0).lower() for match in _ALNUM_RE.finditer(query_text or ""))
        phrases = list(dict.fromkeys(phrases))[:_MAX_PHRASE_TERMS]
        if not phrases:
            return []
        query = " OR ".join(f'"{phrase}"' for phrase in phrases)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM {_FTS_TABLE_NAME}
                WHERE {_FTS_TABLE_NAME} MATCH ?
                ORDER BY bm25({_FTS_TABLE_NAME})
                LIMIT ?
                """,
                (query, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _content_like_candidates(self, terms: list[str], limit: int) -> list[str]:
        """1~2 字符词退化为 content LIKE，按命中词数降序、有界返回。

        真实知识库每个源只有一个 title（文件名），title LIKE 几乎无法区分
        chunk，因此用正文 LIKE 兜底短词；查询词只含中文/英数（无 ``%``/``_``），
        无需 ESCAPE。常见功能字组成的噪声二元组会被停用字过滤。
        """
        if not terms or limit <= 0:
            return []
        kept = [
            term
            for term in terms
            if not any(char in _SHORT_TERM_STOP_CHARS for char in term)
        ]
        if not kept:
            return []
        conditions = " OR ".join("content LIKE ?" for _ in kept)
        params = [f"%{term}%" for term in kept]
        score_sql = " + ".join("CASE WHEN content LIKE ? THEN 1 ELSE 0 END" for _ in kept)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id
                FROM knowledge_chunks
                WHERE {conditions}
                ORDER BY ({score_sql}) DESC, chunk_id
                LIMIT ?
                """,
                (*params, *params, max(0, int(limit))),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def _keyword_candidates(self, query_text: str) -> list[str]:
        """关键词通道候选（按相关性降序）。

        编排：整段短语 MATCH（中文专名）→ 分词 MATCH（英数词）→
        短词正文 LIKE（中文二元组）→ title LIKE（最后兜底）。
        只有 FTS 虚拟表查询出错才判定索引损坏并清签名；LIKE 兜底出错
        只丢弃该兜底，不连坐索引。
        """
        if not self.ensure_fts_index():
            return []
        terms = _query_terms(query_text)
        if not terms:
            return []
        limit = max(1, self.top_k * _KEYWORD_CANDIDATE_FACTOR)
        ranked: list[str] = []

        def _append(candidates: list[str]) -> None:
            for chunk_id in candidates:
                if chunk_id not in ranked:
                    ranked.append(chunk_id)
                if len(ranked) >= limit:
                    return

        try:
            _append(self._phrase_match_candidates(query_text, limit))
            if len(ranked) < limit:
                _append(self._match_candidates(terms, limit - len(ranked)))
        except sqlite3.Error:
            # 虚拟表可能被并发重建/损坏：清掉签名并标记未知，下次查询重建。
            try:
                with self._connect() as connection:
                    connection.execute(
                        "DELETE FROM knowledge_meta WHERE key = ?",
                        (_FTS_SIGNATURE_KEY,),
                    )
            except sqlite3.Error:
                pass
            self._fts_valid = None
            return []

        like_terms = [
            term for term in terms if len(term) < _FTS_MIN_MATCH_CHARS
        ]
        try:
            if len(ranked) < limit:
                _append(
                    self._content_like_candidates(like_terms, limit - len(ranked))
                )
        except sqlite3.Error:
            pass
        try:
            if len(ranked) < limit:
                _append(
                    self._title_like_candidates(like_terms, limit - len(ranked))
                )
        except sqlite3.Error:
            pass
        return ranked


def _query_terms(text: str) -> list[str]:
    """提取用于关键词检索的英文/数字词与中文二元组。"""
    terms: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9_]+", text or ""):
        terms.append(match.group(0).lower())
    cjk = "".join(re.findall(r"[一-鿿]", text or ""))
    for index in range(max(0, len(cjk) - 1)):
        terms.append(cjk[index : index + 2])
    return list(dict.fromkeys(terms))


class KeywordKnowledgeRetriever:
    """跨文件关键词检索：向量嵌入未启用/不可用时的可用回退。"""

    available = True

    def __init__(
        self,
        files: list[Path],
        top_k: int = 4,
        chunk_chars: int = 900,
    ) -> None:
        self._files = [Path(path).expanduser() for path in files]
        self._top_k = max(0, int(top_k))
        self._chunk_chars = max(_MIN_CHUNK_CHARS, int(chunk_chars))
        self._lock = threading.RLock()
        self._cache: dict[Path, tuple[tuple[int, int], list[tuple[str, str, str]]]] = {}

    def _signature(self, path: Path) -> tuple[int, int] | None:
        return _file_signature(path)

    def _sync_path(self, path: Path) -> None:
        signature = self._signature(path)
        if signature is None:
            return
        cached = self._cache.get(path)
        if cached is not None and cached[0] == signature:
            return
        text = load_character_document(path)
        source_id = path.stem
        rows: list[tuple[str, str, str]] = []
        for index, content in enumerate(_chunk_text(text, chunk_chars=self._chunk_chars), start=1):
            chunk_id = hashlib.sha1(
                f"{path.as_posix()}:{index}:{content}".encode()
            ).hexdigest()
            rows.append((chunk_id, source_id, content))
        self._cache[path] = (signature, rows)

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        terms = _query_terms(query_text)
        if not terms:
            return []
        with self._lock:
            for path in self._files:
                self._sync_path(path)
            scored: list[tuple[int, str, KnowledgeChunk]] = []
            for _signature, rows in self._cache.values():
                for chunk_id, source_id, content in rows:
                    overlap = sum(1 for term in terms if term in content)
                    if overlap <= 0:
                        continue
                    scored.append(
                        (
                            overlap,
                            chunk_id,
                            KnowledgeChunk(
                                chunk_id=chunk_id,
                                source_id=source_id,
                                title=source_id,
                                content=content,
                            ),
                        )
                    )
            scored.sort(key=lambda pair: (-pair[0], pair[1]))
            return [chunk for _, _, chunk in scored[: self._top_k]]


def build_keyword_knowledge_provider(config: object) -> object:
    files = [
        Path(path).expanduser()
        for path in (getattr(config, "bot_knowledge_files", []) or [])
    ]
    if not files:
        return _UnavailableVectorKnowledgeProvider()
    return KeywordKnowledgeRetriever(
        files=files,
        top_k=int(_first_defined(config, "bot_knowledge_top_k", 4)),
        chunk_chars=int(_first_defined(config, "bot_knowledge_chunk_chars", 900)),
    )


class _UnavailableVectorKnowledgeProvider:
    available = False

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        return []


class _VectorKnowledgeRetriever:
    available = True

    def __init__(self, store: SqliteVectorKnowledgeStore, files: list[Path]) -> None:
        self._store = store
        self._files = files

    def retrieve(self, query_text: str) -> list[KnowledgeChunk]:
        try:
            return self._store.retrieve(
                query_text,
                files=self._files,
                embed_backlog=False,
            )
        except Exception:  # noqa: BLE001 - 检索异常按无结果降级，不阻断对话。
            return []


def _first_defined(config: object, name: str, default):
    value = getattr(config, name, None)
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return value


def build_vector_knowledge_provider(
    config: object,
    *,
    timeout_override: float | None = None,
) -> object:
    enabled = bool(getattr(config, "bot_embedding_enabled", False))
    model = str(getattr(config, "bot_embedding_model", "") or "").strip()
    base_url = str(getattr(config, "bot_embedding_base_url", "") or "").strip()
    local_models = str(
        getattr(config, "bot_embedding_local_models", "") or ""
    ).strip()
    local_base_url = str(
        getattr(config, "bot_embedding_local_base_url", "") or ""
    ).strip()
    local_enabled = bool(getattr(config, "bot_embedding_local_enabled", True))
    remote_configured = bool(model and base_url)
    local_configured = bool(local_enabled and local_models and local_base_url)
    if not enabled or not (remote_configured or local_configured):
        return _UnavailableVectorKnowledgeProvider()
    try:
        configured_timeout = float(
            _first_defined(config, "bot_embedding_timeout_seconds", 15.0)
        )
        configured_local_timeout = float(
            _first_defined(config, "bot_embedding_local_timeout_seconds", 60.0)
        )
        effective_timeout = (
            max(0.5, float(timeout_override))
            if timeout_override is not None
            else configured_timeout
        )
        effective_local_timeout = (
            max(0.5, float(timeout_override))
            if timeout_override is not None
            else configured_local_timeout
        )
        embed_provider = OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            model=model,
            api_key=str(getattr(config, "bot_embedding_api_key", "") or ""),
            timeout_seconds=effective_timeout,
            dimensions=int(_first_defined(config, "bot_embedding_dimensions", 1024)),
            local_base_url=local_base_url,
            local_models=local_models,
            local_api_key=str(
                getattr(config, "bot_embedding_local_api_key", "") or ""
            ),
            local_enabled=local_enabled,
            local_timeout_seconds=effective_local_timeout,
        )
        store = SqliteVectorKnowledgeStore(
            db_path=str(
                _first_defined(
                    config,
                    "bot_knowledge_db_path",
                    "data/knowledge_embeddings.sqlite3",
                )
            ),
            embed_provider=embed_provider,
            chunk_chars=int(_first_defined(config, "bot_knowledge_chunk_chars", 900)),
            top_k=int(_first_defined(config, "bot_knowledge_top_k", 4)),
            signature=getattr(embed_provider, "signature", ""),
            auto_reset=False,
            # 与 kb_wiki 同策略：请求路径发现 FTS 签名缺失不做分钟级内联
            # 重建（会持锁卡死全部会话），重建由 knowledge-sync force 负责。
            fts_auto_rebuild=False,
            # 人格库专属：选择层源族配额（族上限+人格保留位），防 30k 级
            # 百科源洗掉 373 块人格本体的每轮槽位。其余库构造点不传=现状。
            source_quota_enabled=True,
        )
        files = [
            Path(path).expanduser()
            for path in (getattr(config, "bot_knowledge_files", []) or [])
        ]
        return _VectorKnowledgeRetriever(store=store, files=files)
    except Exception:  # noqa: BLE001 - 向量库构建失败时降级为不可用提供者。
        return _UnavailableVectorKnowledgeProvider()