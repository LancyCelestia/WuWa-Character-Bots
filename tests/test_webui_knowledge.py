"""WebUI 知识目录端点（/api/v1/knowledge/*）服务层契约：tmp 库、离线、只读。

- /api/v1/knowledge/collections：集合目录（community_terms / kb_docs /
  meme_tags / acg_sources），用户点名但无独立库的条目如实 not_available；
- /api/v1/knowledge/terms：集合内词条（q 子串过滤 + 分页 ≤100）。

数据源（全部只读，URI mode=ro + query_only，缺源 = 信封内
source_unavailable 固定 reason，绝不创建文件、绝不造数）：
- community_terms ← 世界观术语表文件（bot_glossary_files，空配置回退
  personas 种子；解析与 FileGlossaryProvider 同规）；
- kb_docs ← 向量知识库 sqlite（bot_knowledge_db_path：knowledge_chunks /
  knowledge_docs，文档级聚合）；
- meme_tags ← 表情库 sqlite（bot_meme_library_db_path：memes 的
  emotion_tags/scene_tags JSON 标签聚合 counts）；
- acg_sources ← 配置态（bot_search_acg_* 开关），未启用=enabled:false。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.control_plane.webui_knowledge import (
    KnowledgeCatalogService,
    build_default_knowledge_service,
)

_MEMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS memes (
    md5 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    ext TEXT NOT NULL,
    group_id TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL,
    used_count INTEGER NOT NULL DEFAULT 0,
    is_meme INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    emotion_tags TEXT NOT NULL DEFAULT '[]',
    scene_tags TEXT NOT NULL DEFAULT '[]',
    persona_hint TEXT NOT NULL DEFAULT 'common',
    nsfw_score REAL NOT NULL DEFAULT 0.0,
    weight REAL NOT NULL DEFAULT 1.0
)
"""


@pytest.fixture
def glossary_file(tmp_path: Path) -> Path:
    path = tmp_path / "worldview_glossary.md"
    path.write_text(
        "# 术语表\n"
        "**漂泊者（Rover）**：今洲来客，失忆的旅人。\n"
        "忌炎：夜归军将军，青龙化身。\n"
        "椿|黑崖船团所属，大傻椿梗的出处。\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def knowledge_db(tmp_path: Path) -> Path:
    path = tmp_path / "knowledge_embeddings.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE knowledge_chunks (
                chunk_id TEXT PRIMARY KEY, source_id TEXT, title TEXT,
                content TEXT, content_hash TEXT, vector_json TEXT, vector_blob BLOB
            );
            CREATE TABLE knowledge_docs (
                doc_id TEXT PRIMARY KEY, topic TEXT, source TEXT,
                title TEXT, hash TEXT
            );
            CREATE TABLE knowledge_meta (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO knowledge_chunks (chunk_id, source_id, title, content)"
            " VALUES (?, ?, ?, ?)",
            [
                ("c1", "wiki-jinhsi", "今汐", "今汐是黑崖船团的首领。"),
                ("c2", "wiki-jinhsi", "今汐", "今汐的时间能力。"),
                ("c3", "wiki-shorekeeper", "守岸人", "守岸人是泰缇斯系统的第二实例。"),
                ("c4", "manual-notes", "manual-notes", "运营手记片段。"),
            ],
        )
        connection.execute(
            "INSERT INTO knowledge_docs (doc_id, topic, source, title, hash)"
            " VALUES ('doc-x', 'wuthering-waves', 'crawl', '外部文档X', 'h1')"
        )
        connection.executemany(
            "INSERT INTO knowledge_chunks (chunk_id, source_id, title, content)"
            " VALUES (?, 'doc-x', '外部文档X', ?)",
            [("d1", "片段一"), ("d2", "片段二")],
        )
    return path


@pytest.fixture
def meme_db(tmp_path: Path) -> Path:
    path = tmp_path / "meme_library.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(_MEMES_SCHEMA)
        connection.executemany(
            "INSERT INTO memes (md5, path, ext, added_at, emotion_tags, scene_tags)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("m1", "p/1.jpg", "jpg", 1.0, '["开心","惊讶"]', '["鸣潮"]'),
                ("m2", "p/2.gif", "gif", 2.0, '["开心"]', '["鸣潮","战双帕弥什"]'),
                ("m3", "p/3.png", "png", 3.0, "[]", "not-json"),
            ],
        )
    return path


def _service(
    tmp_path: Path,
    *,
    glossary: Path | None = None,
    knowledge: Path | None = None,
    meme: Path | None = None,
    acg_enabled: bool = True,
) -> KnowledgeCatalogService:
    return KnowledgeCatalogService(
        glossary_files=[glossary] if glossary else [],
        knowledge_db_path=knowledge or "",
        meme_db_path=meme or "",
        acg_sources=(
            {"bangumi": acg_enabled, "moegirl": acg_enabled, "bilibili": False}
        ),
    )


# ---------------------------------------------------------------------------
# collections —— 集合目录（含诚实 not_available）
# ---------------------------------------------------------------------------


def test_collections_maps_real_stores(
    tmp_path: Path, glossary_file: Path, knowledge_db: Path, meme_db: Path
) -> None:
    result = _service(
        tmp_path, glossary=glossary_file, knowledge=knowledge_db, meme=meme_db
    ).collections()
    assert result["status"] == "ok"
    assert result["source"] == "knowledge_collections"
    items = {row["id"]: row for row in result["data"]["items"]}
    # 四个真实集合齐全 + 用户点名但无库的条目如实 not_available。
    assert {"community_terms", "kb_docs", "meme_tags", "acg_sources"} <= set(items)
    assert items["community_terms"]["enabled"] is True
    assert items["community_terms"]["count"] == 3
    assert items["kb_docs"]["enabled"] is True
    assert items["kb_docs"]["count"] == 4  # 3 个 chunk 源 + 1 个外部文档台账
    assert items["meme_tags"]["enabled"] is True
    assert items["meme_tags"]["count"] == 4  # 开心/惊讶/鸣潮/战双帕弥什
    assert items["acg_sources"]["enabled"] is True
    for key in ("community_terms", "kb_docs", "meme_tags", "acg_sources"):
        assert items[key]["reason"] is None


def test_collections_user_named_missing_stores_are_not_available(
    tmp_path: Path, glossary_file: Path
) -> None:
    result = _service(tmp_path, glossary=glossary_file).collections()
    items = {row["id"]: row for row in result["data"]["items"]}
    bili = items["bili_hot_memes"]
    assert bili["enabled"] is False
    assert bili["reason"] == "no_dedicated_store"
    assert bili["count"] is None
    pgr = items["pgr"]
    assert pgr["enabled"] is False
    assert pgr["reason"] == "no_dedicated_store"


def test_collections_missing_stores_are_honest(tmp_path: Path) -> None:
    result = _service(tmp_path).collections()
    items = {row["id"]: row for row in result["data"]["items"]}
    assert items["community_terms"]["enabled"] is False
    assert items["community_terms"]["count"] == 0
    assert items["kb_docs"]["enabled"] is False
    assert items["meme_tags"]["enabled"] is False
    # acg_sources 是配置态：与文件/库存在性无关，仍按配置如实报。
    assert items["acg_sources"]["enabled"] is True
    dumped = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in dumped


# ---------------------------------------------------------------------------
# terms —— 词条查询（q 过滤 + 分页）
# ---------------------------------------------------------------------------


def test_terms_community_reads_glossary_with_aliases(
    tmp_path: Path, glossary_file: Path
) -> None:
    data = _service(tmp_path, glossary=glossary_file).terms("community_terms")["data"]
    assert data["collection"] == "community_terms"
    assert data["total"] == 3
    by_term = {row["term"]: row for row in data["items"]}
    rover = by_term["漂泊者（Rover）"]
    assert "Rover" in rover["aliases"]
    assert rover["definition"] == "今洲来客，失忆的旅人。"
    assert rover["source"] == "worldview_glossary"
    assert by_term["忌炎"]["aliases"] == []


def test_terms_community_q_matches_term_and_alias(
    tmp_path: Path, glossary_file: Path
) -> None:
    service = _service(tmp_path, glossary=glossary_file)
    hit_alias = service.terms("community_terms", q="rover")["data"]
    assert hit_alias["total"] == 1
    assert hit_alias["items"][0]["term"] == "漂泊者（Rover）"
    hit_term = service.terms("community_terms", q="忌炎")["data"]
    assert hit_term["total"] == 1
    miss = service.terms("community_terms", q="不存在词")["data"]
    assert miss["total"] == 0 and miss["items"] == []


def test_terms_kb_docs_lists_document_metadata(
    tmp_path: Path, knowledge_db: Path
) -> None:
    data = _service(tmp_path, knowledge=knowledge_db).terms("kb_docs")["data"]
    assert data["total"] == 4
    by_term = {row["term"]: row for row in data["items"]}
    assert by_term["wiki-jinhsi"]["chunk_count"] == 2
    assert by_term["wiki-jinhsi"]["updated_at"] is None  # 无时间戳=如实 null
    assert by_term["doc-x"]["chunk_count"] == 2
    assert by_term["doc-x"]["definition"] == "外部文档X"
    assert by_term["manual-notes"]["chunk_count"] == 1
    # 排序确定性：term 升序。
    terms = [row["term"] for row in data["items"]]
    assert terms == sorted(terms)


def test_terms_kb_docs_q_filters(tmp_path: Path, knowledge_db: Path) -> None:
    data = _service(tmp_path, knowledge=knowledge_db).terms("kb_docs", q="今汐")["data"]
    assert data["total"] == 1
    assert data["items"][0]["term"] == "wiki-jinhsi"


def test_terms_meme_tags_aggregates_counts(
    tmp_path: Path, meme_db: Path
) -> None:
    data = _service(tmp_path, meme=meme_db).terms("meme_tags")["data"]
    assert data["total"] == 4
    by_tag = {row["term"]: row for row in data["items"]}
    assert by_tag["开心"]["count"] == 2
    assert set(by_tag["开心"]["scope"]) == {"emotion_tags"}
    assert by_tag["鸣潮"]["count"] == 2
    assert set(by_tag["鸣潮"]["scope"]) == {"scene_tags"}
    # 坏 JSON 行：跳过不炸（诚实聚合可得部分）。
    assert by_tag["开心"]["count"] == 2
    # 排序确定性：count 降序、同数按 tag 升序。
    ranked = [(row["count"], row["term"]) for row in data["items"]]
    assert ranked == sorted(ranked, key=lambda pair: (-pair[0], pair[1]))


def test_terms_acg_sources_reads_config_state(tmp_path: Path) -> None:
    data = _service(tmp_path).terms("acg_sources")["data"]
    by_term = {row["term"]: row for row in data["items"]}
    assert by_term["bangumi"]["enabled"] is True
    assert by_term["bilibili"]["enabled"] is False
    assert by_term["moegirl"]["enabled"] is True


def test_terms_pagination(tmp_path: Path, glossary_file: Path) -> None:
    service = _service(tmp_path, glossary=glossary_file)
    page1 = service.terms("community_terms", page=1, page_size=2)["data"]
    page2 = service.terms("community_terms", page=2, page_size=2)["data"]
    assert page1["total"] == 3 and page2["total"] == 3
    assert len(page1["items"]) == 2 and len(page2["items"]) == 1
    first = {row["term"] for row in page1["items"]}
    second = {row["term"] for row in page2["items"]}
    assert first.isdisjoint(second)


# ---------------------------------------------------------------------------
# BACKEND3 增补：terms total ↔ collections count 自洽（C2/C8b 分页前提）
# ---------------------------------------------------------------------------


def test_terms_total_matches_collections_count(
    tmp_path: Path, glossary_file: Path, knowledge_db: Path, meme_db: Path
) -> None:
    service = _service(
        tmp_path, glossary=glossary_file, knowledge=knowledge_db, meme=meme_db
    )
    collections = {
        row["id"]: row for row in service.collections()["data"]["items"]
    }
    for cid in ("community_terms", "kb_docs", "meme_tags"):
        single = service.terms(cid, q="", page=1, page_size=100)["data"]
        # 同一底层数据：collections.count == 未过滤 terms.total（自洽）。
        assert single["total"] == collections[cid]["count"] > 0
        assert len(single["items"]) == single["total"]


def test_terms_total_stable_across_pages_and_shrinks_with_q(
    tmp_path: Path, glossary_file: Path
) -> None:
    service = _service(tmp_path, glossary=glossary_file)
    beyond = service.terms("community_terms", page=9, page_size=2)["data"]
    # 翻页不改变 total：越界页 items 空、total 仍为全量（Pager 数字页码前提）。
    assert beyond["items"] == []
    assert beyond["total"] == 3
    filtered = service.terms("community_terms", q="漂泊者", page=1, page_size=2)[
        "data"
    ]
    assert filtered["total"] == 1
    assert len(filtered["items"]) == 1


def test_terms_acg_directory_semantics_total_vs_count(tmp_path: Path) -> None:
    # acg_sources 是目录式集合：terms total=全源清单数（含未启用），
    # collections count=启用数——两者口径不同但各自如实，不强行拉平。
    service = _service(tmp_path)  # bangumi/moegirl 启用，bilibili 关
    acg = service.terms("acg_sources", q="", page=1, page_size=100)["data"]
    collections = {
        row["id"]: row for row in service.collections()["data"]["items"]
    }
    assert acg["total"] == len(acg["items"]) == 3
    assert collections["acg_sources"]["count"] == 2


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"collection": "nope"}, "invalid_collection"),
        ({"collection": ""}, "invalid_collection"),
        ({"collection": None}, "invalid_collection"),
        ({"collection": "community_terms", "page": 0}, "invalid_page"),
        ({"collection": "community_terms", "page": "1"}, "invalid_page"),
        ({"collection": "community_terms", "page_size": 0}, "invalid_page_size"),
        ({"collection": "community_terms", "page_size": 101}, "invalid_page_size"),
        ({"collection": "community_terms", "page_size": 2.5}, "invalid_page_size"),
        ({"collection": "community_terms", "q": "x" * 201}, "invalid_query"),
    ],
)
def test_terms_invalid_params_rejected_without_io(
    tmp_path: Path, monkeypatch, kwargs, reason: str
) -> None:
    kwargs = dict(kwargs)
    collection = kwargs.pop("collection", "community_terms")

    def no_connect(*args, **kwargs2):
        pytest.fail("invalid request opened database")

    monkeypatch.setattr(
        "plugins.bot_unified_runtime.control_plane.webui_knowledge.sqlite3.connect",
        no_connect,
    )
    result = _service(tmp_path, glossary=None).terms(collection, **kwargs)
    assert result == {"status": "invalid_request", "reason": reason, "data": None}


def test_terms_not_available_collection_is_honest(tmp_path: Path) -> None:
    for collection in ("bili_hot_memes", "pgr"):
        result = _service(tmp_path).terms(collection)
        assert result["status"] == "source_unavailable"
        assert result["reason"] == "collection_not_available"


def test_terms_missing_sources_honest_and_read_only(
    tmp_path: Path, knowledge_db: Path, meme_db: Path
) -> None:
    for collection in ("kb_docs", "meme_tags"):
        result = _service(tmp_path).terms(collection)
        assert result["status"] == "source_unavailable"
        assert result["reason"] == "missing_source"
    # 有库但表缺失 → incomplete_schema；绝不创建文件。
    path = tmp_path / "empty.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE other (id INTEGER)")
    assert _service(tmp_path, knowledge=path).terms("kb_docs")["reason"] == (
        "incomplete_schema"
    )
    assert not (tmp_path / "missing.sqlite3").exists()


def test_kb_and_meme_reads_never_mutate(
    tmp_path: Path, knowledge_db: Path, meme_db: Path
) -> None:
    before_kb = knowledge_db.read_bytes()
    before_meme = meme_db.read_bytes()
    _service(tmp_path, knowledge=knowledge_db, meme=meme_db).terms("kb_docs")
    _service(tmp_path, knowledge=knowledge_db, meme=meme_db).terms("meme_tags")
    assert knowledge_db.read_bytes() == before_kb
    assert meme_db.read_bytes() == before_meme


# ---------------------------------------------------------------------------
# 默认装配：config → 服务
# ---------------------------------------------------------------------------


def test_build_default_service_from_config(tmp_path: Path) -> None:
    config = SimpleNamespace(
        bot_glossary_files=[],
        bot_knowledge_db_path=str(tmp_path / "kb.sqlite3"),
        bot_meme_library_db_path=str(tmp_path / "meme.sqlite3"),
        bot_search_acg_enabled=True,
        bot_search_acg_bangumi_enabled=True,
        bot_search_acg_moegirl_enabled=True,
        bot_search_acg_bilibili_enabled=True,
    )
    service = build_default_knowledge_service(config)
    assert service.collections()["status"] == "ok"


# ---------------------------------------------------------------------------
# HTTP 投影：统一信封 / 认证 / 422 映射（挂 _app 装配）
# ---------------------------------------------------------------------------


def _http_config(tmp_path: Path, glossary: Path, knowledge: Path, meme: Path):
    from plugins.bot_unified_runtime.control_plane.auth import hash_token

    return SimpleNamespace(
        bot_control_plane_enabled=True,
        bot_control_plane_token_sha256=hash_token("admin-token"),
        bot_control_plane_super_admin_token_sha256=hash_token("root-token"),
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
        bot_glossary_files=[str(glossary)],
        bot_knowledge_db_path=str(knowledge),
        bot_meme_library_db_path=str(meme),
        bot_search_acg_enabled=True,
        bot_search_acg_bangumi_enabled=True,
        bot_search_acg_moegirl_enabled=True,
        bot_search_acg_bilibili_enabled=True,
    )


def test_knowledge_http_envelope_auth_and_422(
    tmp_path: Path, glossary_file: Path, knowledge_db: Path, meme_db: Path
) -> None:
    from fastapi.testclient import TestClient

    from plugins.bot_unified_runtime.control_plane import create_control_plane_app
    from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore

    app = create_control_plane_app(
        _http_config(tmp_path, glossary_file, knowledge_db, meme_db),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        channel_health_store=object(),
        webui_dist_dir=str(tmp_path / "dist"),
    )
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        assert client.get("/api/v1/knowledge/collections").status_code == 401
        response = client.get("/api/v1/knowledge/collections", headers=headers)
        assert response.status_code == 200
        assert response.headers["x-request-id"]
        payload = response.json()
        assert payload["error"] is None
        assert payload["meta"]["schema_version"] == "v1"
        assert payload["data"]["status"] == "ok"

        terms = client.get(
            "/api/v1/knowledge/terms?collection=community_terms&q=rover",
            headers=headers,
        )
        assert terms.status_code == 200
        assert terms.json()["data"]["data"]["total"] == 1

        invalid = client.get(
            "/api/v1/knowledge/terms?collection=nope", headers=headers
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "knowledge_invalid_query"
