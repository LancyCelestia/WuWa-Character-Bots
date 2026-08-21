from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path

from plugins.bot_unified_runtime.contracts.character import ContextBundle, KnowledgeChunk

from .documents import load_character_document


def build_safe_context_source_summary(
    config: object,
    context: ContextBundle,
) -> dict[str, str]:
    return {
        "persona_source_refs": _join_refs(
            _file_source_refs(
                getattr(config, "bot_persona_files", []),
                prefix="persona",
            )
        ),
        "knowledge_source_refs": _join_refs(
            _knowledge_source_refs(context.knowledge_results.chunks)
        ),
    }


def _file_source_refs(paths: object, *, prefix: str) -> list[str]:
    if not isinstance(paths, list):
        return []
    refs: list[str] = []
    for index, raw_path in enumerate(paths, start=1):
        path = Path(str(raw_path)).expanduser()
        basis = _file_digest_basis(path)
        refs.append(f"{prefix}{index}:{_digest(basis)}")
    return refs


def _file_digest_basis(path: Path) -> str:
    try:
        text = load_character_document(path)
    except Exception as exc:  # noqa: BLE001 - source refs must not leak parser details.
        return f"unreadable:{path.suffix.lower()}:{type(exc).__name__}"
    content_digest = _digest(text)
    return f"readable:{path.suffix.lower()}:{len(text)}:{content_digest}"


def _knowledge_source_refs(chunks: list[KnowledgeChunk]) -> list[str]:
    grouped: OrderedDict[str, list[KnowledgeChunk]] = OrderedDict()
    for chunk in chunks:
        grouped.setdefault(chunk.source_id, []).append(chunk)

    refs: list[str] = []
    for index, source_chunks in enumerate(grouped.values(), start=1):
        basis = "|".join(
            f"{chunk.chunk_id}:{len(chunk.content)}" for chunk in source_chunks
        )
        refs.append(f"knowledge{index}:{_digest(basis)}")
    return refs


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _join_refs(refs: list[str]) -> str:
    return ",".join(refs) if refs else "-"
