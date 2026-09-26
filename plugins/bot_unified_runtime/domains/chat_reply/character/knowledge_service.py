"""V2.1 S8 知识库服务（V21-KB-001）。

合同来源：docs/design/backend-v2-implementation-guide.md §9 Knowledge 段
「Knowledge复用FTS5 BM25+向量+RRF(k=60)，候选有界，embedding阈值按模型
版本；新索引验证后切换。方法search/chunk_document/reindex/swap_index」+
验收矩阵行 V21-KB-001（真实FTS/向量/RRF检索及原子重建；已知语料召回、
embedding版本变更、半成品不切换）。

复用边界（零平行造轮子）：
- 检索通道、RRF 融合、FTS5/ANN 构建、分块全部复用
  ``character/vector_knowledge.py`` 的 ``SqliteVectorKnowledgeStore``；
  本服务只做三件事——①分数/来源透出（跨库二次融合）②原子重建
  （临时位构建→验证→swap→失败不切换）③脱敏预览。
- 脱敏复用 ``output/plain_text.py::redact_local_secrets``（与出站同一
  打码口径，不另写正则）。
- 零真实网络：embedding 经 ``EmbeddingProvider`` 协议注入，测试用确定性
  fake provider（向量库构建/换版本均不触网）。

原子重建语义（§9「新索引验证后切换」+ 验收行「半成品不切换」）：
1. 全部新索引（SQLite 库 + FAISS + order + FTS）建在临时目录（与线上库
   同卷，保证 os.replace 原子性）；
2. 校验：行数>0、向量覆盖率 100%（半成品=不切换）、FTS 探针、
   embedding 指纹落盘、调用方附加校验器；
3. swap：逐文件 备份→替换→缓存换代，任一步失败回滚备份（线上文件
   回到换前状态）；
4. embedding 指纹（模型版本）变更时同样走临时位全新构建——重建期间旧
   索引照常服务，版本切换在 swap 成功那一刻才发生。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from pydantic import ConfigDict, Field

from plugins.bot_unified_runtime.domains.core.contracts.envelope import V21StrictBase
from plugins.bot_unified_runtime.domains.render.plain_text import redact_local_secrets

from .vector_knowledge import (
    EmbeddingProvider,
    ScoredKnowledgeChunk,
    SqliteVectorKnowledgeStore,
    _chunk_text,
)

__all__ = [
    "KnowledgeSearchHit",
    "KnowledgeSearchReport",
    "KnowledgeService",
    "KnowledgeSourceBinding",
    "ReindexError",
    "ReindexReport",
    "build_knowledge_service",
]


class ReindexError(RuntimeError):
    """原子重建失败（含失败时已回滚的事实与逐源报告）。"""

    def __init__(self, message: str, report: ReindexReport) -> None:
        super().__init__(message)
        self.report = report


class KnowledgeSourceBinding(V21StrictBase):
    """一个知识库源的只读描述（服务构造入参，Pydantic 严格 DTO）。

    populate 是重建时装填语料的钩子（复用各自既有 sync 链路）；为 None
    表示该源不参与重建（reindex 报告里如实标 skipped）。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(min_length=1, max_length=64)
    store: SqliteVectorKnowledgeStore
    populate: Callable[[SqliteVectorKnowledgeStore], None] | None = None
    probe_queries: tuple[str, ...] = Field(default=(), max_length=8)


class KnowledgeSearchHit(V21StrictBase):
    """带来源与分数的检索单条（默认只回脱敏预览，不回全文）。"""

    source: str = Field(min_length=1, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=256)
    title: str = ""
    content_preview: str = ""
    score: float = Field(ge=0.0)
    rank: int = Field(ge=0)
    channels: dict[str, int | None] = Field(default_factory=dict)


class KnowledgeSearchReport(V21StrictBase):
    query: str = Field(min_length=1, max_length=500)
    hits: list[KnowledgeSearchHit] = Field(default_factory=list)
    sources_searched: list[str] = Field(default_factory=list)
    duration_ms: float = Field(ge=0.0)


class ReindexSourceReport(V21StrictBase):
    source: str
    chunks: int = 0
    embedded: int = 0
    ann_built: bool = False
    skipped: str = ""


class ReindexReport(V21StrictBase):
    swapped: bool = False
    rolled_back: bool = False
    old_signature: str = ""
    new_signature: str = ""
    sources: list[ReindexSourceReport] = Field(default_factory=list)
    error: str = ""


@dataclass
class _SwapPlan:
    binding: KnowledgeSourceBinding
    temp_db: Path
    temp_ann_index: Path
    temp_ann_order: Path
    live_db: Path
    live_ann_index: Path
    live_ann_order: Path
    report: ReindexSourceReport


class KnowledgeService:
    """知识检索统一服务：多库 search（分数+来源）+ 原子重建 + 脱敏预览。"""

    def __init__(
        self,
        bindings: list[KnowledgeSourceBinding],
        *,
        default_top_k: int = 5,
        preview_chars: int = 200,
        redact_preview: bool = True,
    ) -> None:
        if not bindings:
            raise ValueError("KnowledgeService 需要至少一个知识库源")
        names = [binding.name for binding in bindings]
        if len(set(names)) != len(names):
            raise ValueError(f"知识库源名重复: {names}")
        self._bindings = list(bindings)
        self._by_name = {binding.name: binding for binding in bindings}
        self.default_top_k = max(1, int(default_top_k))
        self.preview_chars = max(40, int(preview_chars))
        self.redact_preview = bool(redact_preview)

    # ------------------------------------------------------------- 查询面

    def store(self, source_name: str) -> SqliteVectorKnowledgeStore:
        return self._by_name[source_name].store

    def source_names(self) -> list[str]:
        return [binding.name for binding in self._bindings]

    def search(
        self,
        query_text: str,
        *,
        top_k: int | None = None,
        redact: bool | None = None,
    ) -> KnowledgeSearchReport:
        """跨库检索：逐源三通道 RRF → 跨源按融合分二次排序（同刻度可比）。

        各源 RRF 均为 k=60 同式打分，分值刻度一致，可直接跨源排序；
        同分按 (source, chunk_id) 稳定平局。默认只返回脱敏预览
        （redact_local_secrets + 截断），全文属 fetch_reference 面职权。
        """
        started = time.monotonic()
        limit = self.default_top_k if top_k is None else max(1, int(top_k))
        do_redact = self.redact_preview if redact is None else bool(redact)
        query = str(query_text or "").strip()
        if not query:
            return KnowledgeSearchReport(
                query=query or "(empty)",
                sources_searched=[b.name for b in self._bindings],
                duration_ms=0.0,
            )
        fused: list[KnowledgeSearchHit] = []
        searched: list[str] = []
        for binding in self._bindings:
            try:
                scored = binding.store.search_scored(
                    query, top_k=limit, sync_files=False
                )
            except Exception:  # noqa: S112, BLE001 - 单源故障不拖垮其余源（诚实降级）。
                continue
            searched.append(binding.name)
            for item in scored:
                fused.append(
                    self._to_hit(binding.name, item, do_redact=do_redact)
                )
        fused.sort(
            key=lambda hit: (-hit.score, hit.source, hit.chunk_id)
        )
        hits = [
            replace_rank(hit, rank)
            for rank, hit in enumerate(fused[:limit])
        ]
        return KnowledgeSearchReport(
            query=query,
            hits=hits,
            sources_searched=searched,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _to_hit(
        self,
        source_name: str,
        item: ScoredKnowledgeChunk,
        *,
        do_redact: bool,
    ) -> KnowledgeSearchHit:
        content = str(item.chunk.content or "")
        preview = content[: self.preview_chars]
        if do_redact:
            preview = redact_local_secrets(preview)
        return KnowledgeSearchHit(
            source=source_name,
            chunk_id=item.chunk.chunk_id,
            title=str(item.chunk.title or ""),
            content_preview=preview,
            score=max(0.0, float(item.score)),
            rank=0,
            channels=dict(item.channels),
        )

    # ------------------------------------------------------------- 切块面

    def chunk_document(
        self,
        text: str,
        *,
        chunk_chars: int | None = None,
    ) -> list[str]:
        """文档切块：复用存量 _chunk_text 段落语义（与同步链同一实现）。"""
        store = self._bindings[0].store
        return _chunk_text(
            str(text or ""),
            chunk_chars=int(
                chunk_chars if chunk_chars is not None else store.chunk_chars
            ),
        )

    # ------------------------------------------------------------- 原子重建

    def reindex(
        self,
        *,
        signature: str | None = None,
        embed_batch: int | None = None,
        extra_validator: (
            Callable[[KnowledgeSourceBinding, SqliteVectorKnowledgeStore], None] | None
        ) = None,
    ) -> ReindexReport:
        """原子重建：临时位构建 → 校验 → swap；任何失败不切换半成品。

        signature=None 时沿用各源现有 embedding 指纹；显式传入新指纹即
        完成「embedding 版本变更」：全部向量在临时库按新版本重嵌，旧库
        重建期间照常服务，验证通过后 swap 才切换版本。
        """
        report = ReindexReport(
            old_signature=str(self._bindings[0].store.signature or ""),
            new_signature=str(
                signature
                if signature is not None
                else self._bindings[0].store.signature
            ),
        )
        first_store = self._bindings[0].store
        root = Path(first_store.db_path).expanduser().resolve().parent
        temp_root = root / f".reindex-{int(time.time())}-{uuid4().hex[:8]}"
        plans: list[_SwapPlan] = []
        temp_stores: list[SqliteVectorKnowledgeStore] = []
        try:
            temp_root.mkdir(parents=True)
            for binding in self._bindings:
                plan_report = ReindexSourceReport(source=binding.name)
                if binding.populate is None:
                    plan_report.skipped = "no_populate"
                    # 该源本次不参与重建 ⇒ 发布提交点不会经手它，线上库若
                    # 恰缺 #47 完备性戳，就永远没有落戳的人（与 kb-sync 零变更
                    # 夜 unchanged_skip 同型死锁）。维护路径就地自愈：仅当无戳
                    # 时补盖权威 COUNT（活戳归重建线所有，一字不碰）；失败或
                    # 替身 store 无此方法都不拦重建主链。
                    _certify = getattr(
                        binding.store, "certify_expected_vector_count", None
                    )
                    if callable(_certify):
                        try:
                            _certify()
                        except Exception:  # noqa: S110, BLE001 - 自愈失败不拦重建主链。
                            pass
                    report.sources.append(plan_report)
                    continue
                temp_db = temp_root / f"{binding.name}.sqlite3"
                new_store = self._build_temp_store(
                    binding,
                    temp_db,
                    temp_root,
                    signature=report.new_signature,
                )
                temp_stores.append(new_store)
                binding.populate(new_store)
                done, pending = new_store.embed_pending(batch_size=embed_batch)
                plan_report.chunks = pending
                plan_report.embedded = done
                ann = new_store.build_ann_index()
                plan_report.ann_built = bool(ann.get("built"))
                new_store.ensure_fts_index(force=True)
                self._validate_temp_store(
                    binding, new_store, extra_validator=extra_validator
                )
                new_store.close_runtime_handles()
                report.sources.append(plan_report)
                plans.append(
                    _SwapPlan(
                        binding=binding,
                        temp_db=temp_db,
                        temp_ann_index=Path(new_store.ann_index_path),
                        temp_ann_order=Path(new_store.ann_order_path),
                        live_db=Path(binding.store.db_path),
                        live_ann_index=Path(binding.store.ann_index_path),
                        live_ann_order=Path(binding.store.ann_order_path),
                        report=plan_report,
                    )
                )
            if not plans:
                raise ReindexError("没有可重建的源（全部缺 populate）", report)
            self._swap(plans, report)
            report.swapped = True
            return report
        except ReindexError:
            raise
        except Exception as exc:
            report.error = f"{type(exc).__name__}: {exc}"
            raise ReindexError(report.error, report) from exc
        finally:
            # 失败路径的临时库连接也要干净关闭，否则 Windows 上 rmtree
            # 删不掉打开中的 sqlite 文件（半成品目录泄漏）。
            for store_ in temp_stores:
                try:
                    store_.close_runtime_handles()
                except Exception:  # noqa: S110, BLE001 - 清理失败不掩盖原始异常。
                    pass
            shutil.rmtree(temp_root, ignore_errors=True)

    def _build_temp_store(
        self,
        binding: KnowledgeSourceBinding,
        temp_db: Path,
        temp_root: Path,
        *,
        signature: str,
    ) -> SqliteVectorKnowledgeStore:
        live = binding.store
        return SqliteVectorKnowledgeStore(
            db_path=str(temp_db),
            embed_provider=live.embed_provider,
            chunk_chars=live.chunk_chars,
            top_k=live.top_k,
            signature=str(signature or live.signature or ""),
            auto_reset=True,
            ann_index_path=str(temp_root / f"{binding.name}.faiss.index"),
            ann_order_path=str(temp_root / f"{binding.name}.faiss.order.json"),
            min_cosine_threshold=live.min_cosine_threshold,
        )

    def _validate_temp_store(
        self,
        binding: KnowledgeSourceBinding,
        new_store: SqliteVectorKnowledgeStore,
        *,
        extra_validator: Callable[
            [KnowledgeSourceBinding, SqliteVectorKnowledgeStore], None
        ]
        | None,
    ) -> None:
        """半成品检测：任何一项不过即抛异常，swap 永不执行。"""
        stats = new_store.stats()
        if stats["total"] <= 0:
            raise ValueError(f"[{binding.name}] 临时库 0 行（语料装填失败）")
        if stats["embedded"] < stats["total"]:
            raise ValueError(
                f"[{binding.name}] 向量覆盖不全 "
                f"({stats['embedded']}/{stats['total']})，疑似半成品"
            )
        if new_store.signature and not new_store._stored_signature():
            raise ValueError(
                f"[{binding.name}] embedding 指纹未落盘（嵌入链未完成）"
            )
        for probe in binding.probe_queries:
            if not new_store.search_scored(str(probe), sync_files=False):
                raise ValueError(
                    f"[{binding.name}] 探针查询无召回：{probe!r}"
                )
        if extra_validator is not None:
            extra_validator(binding, new_store)

    def _swap(self, plans: list[_SwapPlan], report: ReindexReport) -> None:
        """换装新索引：SQLite 走 backup API 内容原子切换；ANN 文件先移后放。

        为什么不用 os.replace 换 db 文件：Windows 上 sqlite 打开的文件
        （含其他线程的连接）不可改名/删除（WinError 32），且换文件会让
        在途连接指向旧 inode。改用 SQLite backup API：把临时库事务性
        写入线上库同一文件——读方要么旧页要么新页，永不脏读；在途连接
        经页缓存变更检测自动看到新内容。

        ANN（faiss）文件无法 backup：先把旧文件移入回收目录（此时向量
        检索自动回落暴力扫描，**正确性不降**），backup 成功后再放置新
        文件。任何中间态都正确：无 ANN=慢，绝无错配。失败路径：
        backup 失败 → 事务回滚 + ANN 归位，线上回到换前状态。
        """
        trash_root = plans[0].live_db.parent / (
            f".reindex-bak-{int(time.time())}-{uuid4().hex[:8]}"
        )
        moved_ann: list[tuple[Path, Path]] = []  # (live, trash)
        backup_done = False
        try:
            for plan in plans:
                # 1) 先丢弃 live store 的进程内缓存与本线程句柄
                #    （释放 ann mmap，避免 Windows 句柄占用阻塞改名）。
                plan.binding.store.close_runtime_handles()
                trash_root.mkdir(parents=True, exist_ok=True)
                for live_path in (plan.live_ann_index, plan.live_ann_order):
                    if live_path.exists():
                        trash_path = trash_root / (
                            f"{plan.binding.name}-{uuid4().hex[:6]}-{live_path.name}"
                        )
                        os.replace(live_path, trash_path)
                        moved_ann.append((live_path, trash_path))
            for plan in plans:
                # 2) backup API：临时库 → 线上库（事务性整库替换）。
                self._backup_db(plan.temp_db, plan.live_db, timeout_seconds=5.0)
                backup_done = True
                # 版本切换随库内容生效：live store 的指纹属性同步到新版本，
                # 避免后续 embed_pending 因属性/库内指纹不一致误清向量。
                if report.new_signature:
                    plan.binding.store.signature = report.new_signature
                # 3) 放置新 ANN 文件（缺席=暴力检索兜底，不影响正确性）。
                for temp_path, live_path in (
                    (plan.temp_ann_index, plan.live_ann_index),
                    (plan.temp_ann_order, plan.live_ann_order),
                ):
                    if temp_path.exists():
                        live_path.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(temp_path, live_path)
                plan.binding.store.invalidate_runtime_caches()
        except Exception as exc:
            if not backup_done:
                # 库未动：归位 ANN，完整回滚到换前状态。
                for live_path, trash_path in moved_ann:
                    try:
                        os.replace(trash_path, live_path)
                    except OSError:
                        pass
                for plan in plans:
                    plan.binding.store.invalidate_runtime_caches()
                report.rolled_back = True
                report.error = f"swap 失败已回滚: {type(exc).__name__}: {exc}"
            else:
                # 库已切换（内容经校验）：仅 ANN 加速文件缺席/部分就位，
                # 检索自动回落暴力扫描，正确性不受影响——如实报告部分完成。
                for plan in plans:
                    plan.binding.store.invalidate_runtime_caches()
                report.swapped = True
                report.error = (
                    f"库已切换但 ANN 文件未完全就位（已回落暴力检索）: "
                    f"{type(exc).__name__}: {exc}"
                )
            raise ReindexError(report.error, report) from exc
        finally:
            shutil.rmtree(trash_root, ignore_errors=True)

    @staticmethod
    def _backup_db(
        temp_db: Path,
        live_db: Path,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        """SQLite backup API：临时库整库事务性写入线上库文件。

        目标库存在并发读者（WAL/短读事务）时可能 BUSY：有限退避重试，
        重试耗尽抛 sqlite3.OperationalError（由 _swap 回滚）。
        """
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while True:
            source = sqlite3.connect(str(temp_db))
            destination = sqlite3.connect(str(live_db))
            try:
                source.backup(destination)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
            finally:
                source.close()
                destination.close()


def replace_rank(hit: KnowledgeSearchHit, rank: int) -> KnowledgeSearchHit:
    """不可变 DTO 的 rank 重排（跨源排序后赋最终名次）。"""
    return hit.model_copy(update={"rank": int(rank)})


def build_knowledge_service(
    config: object,
    *,
    stores: list[tuple[str, SqliteVectorKnowledgeStore]] | None = None,
) -> KnowledgeService:
    """从配置装配：显式传入 stores 时直接包装（复用既有共享 store 单例）。

    未传入 stores 时按 config 现有人格知识库/kb_wiki 配置构建两个源。
    populate 钩子复用各自既有同步链路（人格库 sync_chunks 文件清单全集、
    wiki 库 sync_kb_wiki hash 幂等协议），重建不另写同步代码。
    """
    bindings: list[KnowledgeSourceBinding] = []
    if stores:
        for name, store in stores:
            bindings.append(KnowledgeSourceBinding(name=name, store=store))
    else:
        from plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki import (  # 真身（v21r2 W16 迁域），函数级惰性防环
            sync_kb_wiki,
        )

        from .vector_knowledge import build_vector_knowledge_provider

        provider = cast(
            EmbeddingProvider, build_vector_knowledge_provider(config)
        )
        signature = str(getattr(provider, "signature", ""))
        persona_files = [
            Path(str(item))
            for item in (getattr(config, "bot_knowledge_files", []) or [])
        ]

        def _populate_persona(store: SqliteVectorKnowledgeStore) -> None:
            store.sync_chunks(persona_files)

        persona_store = SqliteVectorKnowledgeStore(
            db_path=str(
                getattr(config, "bot_knowledge_db_path", "")
                or "data/knowledge_embeddings.sqlite3"
            ),
            embed_provider=provider,
            chunk_chars=max(
                200, int(getattr(config, "bot_knowledge_chunk_chars", 900) or 900)
            ),
            top_k=int(getattr(config, "bot_knowledge_top_k", 4) or 4),
            signature=signature,
            auto_reset=False,
        )
        bindings.append(
            KnowledgeSourceBinding(
                name="persona",
                store=persona_store,
                populate=_populate_persona,
            )
        )
        if bool(getattr(config, "bot_kb_wiki_enabled", False)):

            def _populate_kb(store: SqliteVectorKnowledgeStore) -> None:
                sync_kb_wiki(store, config, full=True)

            kb_db = str(
                getattr(config, "bot_kb_wiki_db_path", "")
                or "data/kb_wiki_embeddings.sqlite3"
            )
            kb_store = SqliteVectorKnowledgeStore(
                db_path=kb_db,
                embed_provider=provider,
                chunk_chars=max(
                    200,
                    int(getattr(config, "bot_kb_wiki_chunk_chars", 800) or 800),
                ),
                top_k=int(getattr(config, "bot_kb_wiki_top_k", 4) or 4),
                signature=signature,
                auto_reset=False,
                ann_index_path=str(Path(kb_db).with_name("kb_wiki_faiss.index")),
                ann_order_path=str(
                    Path(kb_db).with_name("kb_wiki_faiss.order.json")
                ),
                fts_auto_rebuild=False,
            )
            bindings.append(
                KnowledgeSourceBinding(
                    name="kb_wiki",
                    store=kb_store,
                    populate=_populate_kb,
                )
            )
    return KnowledgeService(bindings)
