"""WebUI 端点 HTTP 契约：信封/认证语义/静态挂载（TestClient，离线）。

- /api/v1/stats/*、/api/v1/affinity/board 走与既有 v1 相同的统一信封、
  Bearer 双令牌认证、未配置令牌 503 not_provisioned、参数非法 422；
- /ui 入口：产物存在 → 307 跳 /ui/；缺失 → 404 诚实体 ui_not_built；
- /ui/ 返回 index（text/html、no-store）；/ui/assets/* 由应用层挂载真实
  服务 JS/CSS（正确 MIME、带哈希资源可缓存、未知资产 404 不回 index、
  不暴露产物根其他文件、路径遍历不越根）；
- UI 响应头边界（CSP script-src 'self' / frame-ancestors 'none' /
  X-Frame-Options DENY / nosniff）只作用于 /ui 子树，/api 认证与 CORS 不变
  （host 白名单等既有中间件语义不变，静态壳不含数据，数据面全部经认证端点）。
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane import create_control_plane_app
from plugins.bot_unified_runtime.control_plane.audit import ControlPlaneAuditStore
from plugins.bot_unified_runtime.control_plane.auth import hash_token
from plugins.bot_unified_runtime.control_plane.metrics import LedgerMetricsService
from plugins.bot_unified_runtime.control_plane.webui_stats import (
    AffinityBoardService,
    AuditCallStatsService,
    WebUIStatsBundle,
)


def _config(tmp_path: Path, *, admin: str, super_admin: str) -> SimpleNamespace:
    return SimpleNamespace(
        bot_control_plane_enabled=True,
        # 空令牌=未配置（sha256 设置串本身为空串，而非空串的哈希）。
        bot_control_plane_token_sha256=hash_token(admin) if admin else "",
        bot_control_plane_super_admin_token_sha256=hash_token(super_admin) if super_admin else "",
        bot_runtime_settings_dir=str(tmp_path / "settings"),
        bot_control_plane_config_db=str(tmp_path / "config.sqlite3"),
        bot_runtime_settings_file=str(tmp_path / "settings.json"),
        bot_control_plane_features_file=str(tmp_path / "features.json"),
        bot_timezone="UTC",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _audit_table(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE audit_records (audit_id TEXT PRIMARY KEY, request_id TEXT,"
            " session_id TEXT, capability_id TEXT, stage TEXT, event TEXT,"
            " severity TEXT, public_message TEXT, private_debug TEXT, created_at TEXT)"
        )
        # 种子时间必须动态取近期：stats/calls 按 now-24h 相对窗口过滤，
        # 硬编码日期会在次日滑出窗口（2026-09-19 时间炸弹事故）。
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        connection.execute(
            "INSERT INTO audit_records VALUES ('a1','r1','private_777','bot.chat',"
            f"'invoke','done','low','ok','','{recent}')"
        )


def _affinity_table(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE user_affinity (sender_id TEXT PRIMARY KEY,"
            " affinity REAL NOT NULL DEFAULT 0.1, interaction_count INTEGER"
            " NOT NULL DEFAULT 0, nickname TEXT NOT NULL DEFAULT '',"
            " updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_affinity (sender_id, affinity, nickname,"
            " interaction_count, updated_at) VALUES ('777', 0.5, '岸宝', 9, 'x')"
        )


def _app(tmp_path: Path, **overrides):
    calls_db = tmp_path / "audit.sqlite3"
    affinity_db = tmp_path / "affinity.sqlite3"
    ledger_db = tmp_path / "ledger.sqlite3"
    _audit_table(calls_db)
    _affinity_table(affinity_db)
    kwargs: dict[str, object] = {
        "stats_service": WebUIStatsBundle(
            calls=AuditCallStatsService(calls_db),
            affinity=AffinityBoardService(affinity_db),
        ),
        "metrics_service": LedgerMetricsService(ledger_db),
        "webui_dist_dir": str(tmp_path / "dist"),
    }
    kwargs.update(overrides)
    return create_control_plane_app(
        _config(tmp_path, admin="admin-token", super_admin="root-token"),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        channel_health_store=object(),
        **kwargs,
    )


READ_PATHS = (
    "/api/v1/stats/calls",
    "/api/v1/stats/tokens",
    "/api/v1/stats/latency",
    "/api/v1/affinity/board",
)

# 模拟 vite 多文件产物（base '/ui/'）：index 外链带哈希的 JS/CSS，另有
# 无哈希资源与产物根散件（后者不得被服务）。
_INDEX_HTML = (
    "<!doctype html><html><head>"
    '<link rel="stylesheet" href="/ui/assets/index-a1b2c3d4.css" />'
    '</head><body><div id="root">shorekeeper-ui</div>'
    '<script type="module" src="/ui/assets/index-a1b2c3d4.js"></script>'
    "</body></html>"
)
_JS_BODY = "export const shorekeeper = 1;\n"
_CSS_BODY = ".root { color: #fff; }\n"


def _write_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    # 资产按字节落盘：静态服务是字节级回放，避免 Windows 文本模式的 CRLF 转写
    # 把断言变成换行符比对（测量假象，不是被测行为）。
    (assets / "index-a1b2c3d4.js").write_bytes(_JS_BODY.encode("utf-8"))
    (assets / "index-a1b2c3d4.css").write_bytes(_CSS_BODY.encode("utf-8"))
    (assets / "logo.svg").write_bytes(b"<svg/>\n")
    (dist / "secret.txt").write_text("do-not-serve\n", encoding="utf-8")
    return dist


def test_stats_endpoints_require_bearer_and_use_common_envelope(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path in READ_PATHS:
            assert client.get(path).status_code == 401, path
        response = client.get("/api/v1/stats/calls", headers=_headers("admin-token"))
        assert response.status_code == 200
        assert response.headers["x-request-id"]
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["error"] is None
        assert payload["meta"]["schema_version"] == "v1"
        assert payload["data"]["status"] == "ok"
        assert payload["data"]["data"]["total_calls"] == 1


def test_stats_invalid_query_maps_to_422(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path, query in (
            ("/api/v1/stats/calls", "window=99w"),
            ("/api/v1/stats/tokens", "window=week"),
            ("/api/v1/affinity/board", "order=sideways"),
            ("/api/v1/stats/calls", "limit=0"),
        ):
            response = client.get(
                f"{path}?{query}", headers=_headers("admin-token")
            )
            assert response.status_code == 422, (path, query, response.status_code)
            assert response.json()["error"]["code"] == "stats_invalid_query"


def test_stats_endpoints_return_503_when_unprovisioned(tmp_path: Path) -> None:
    app = create_control_plane_app(
        _config(tmp_path, admin="", super_admin=""),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        stats_service=WebUIStatsBundle(
            calls=AuditCallStatsService(tmp_path / "a.sqlite3"),
            affinity=AffinityBoardService(tmp_path / "b.sqlite3"),
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        for path in READ_PATHS:
            response = client.get(path)
            assert response.status_code == 503, path
            assert response.json()["error"]["code"] == "control_plane_not_provisioned"


def test_latency_and_tokens_degraded_sources_still_envelope_ok(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        latency = client.get("/api/v1/stats/latency", headers=_headers("admin-token"))
        assert latency.status_code == 200
        body = latency.json()["data"]
        # channel_health_store=object()：无 report 接口 → 如实降级不炸 500。
        assert body["status"] == "source_unavailable"

        tokens = client.get("/api/v1/stats/tokens", headers=_headers("admin-token"))
        assert tokens.status_code == 200
        assert tokens.json()["data"]["status"] == "source_unavailable"  # 账本库缺失=诚实降级


def test_ui_entry_redirects_to_ui_root_and_index_is_no_store(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        missing = client.get("/ui", follow_redirects=False)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "ui_not_built"

    _write_dist(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        entry = client.get("/ui", follow_redirects=False)
        assert entry.status_code == 307, entry.status_code
        assert entry.headers["location"] == "/ui/"

        served = client.get("/ui/")
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("text/html")
        assert served.headers["cache-control"] == "no-store"
        assert "shorekeeper-ui" in served.text


def test_ui_assets_served_with_real_mime_cache_and_security_headers(
    tmp_path: Path,
) -> None:
    _write_dist(tmp_path)
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        index = client.get("/ui/")
        refs = re.findall(r'(?:src|href)="([^"]+)"', index.text)
        # 从 index 的 src/href 推导实际资产 URL（相对 /ui/ 解析）。
        urls = [urljoin("/ui/", ref) for ref in refs]
        js_url = next(url for url in urls if url.endswith(".js"))
        css_url = next(url for url in urls if url.endswith(".css"))

        js = client.get(js_url)
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert js.text == _JS_BODY
        assert js.headers["cache-control"] == "public, max-age=31536000, immutable"

        css = client.get(css_url)
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
        assert css.text == _CSS_BODY

        # 无哈希资源（logo.svg）：如实不缓存，不与全局 no-store 冲突。
        plain = client.get("/ui/assets/logo.svg")
        assert plain.status_code == 200
        assert plain.headers["cache-control"] == "no-store"

        for response in (index, js, css, plain):
            csp = response.headers["content-security-policy"]
            assert "script-src 'self'" in csp
            assert "style-src 'self' 'unsafe-inline'" in csp
            assert "frame-ancestors 'none'" in csp
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["x-content-type-options"] == "nosniff"


def test_ui_assets_unknown_and_root_files_are_not_served(tmp_path: Path) -> None:
    _write_dist(tmp_path)
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        known = client.get("/ui/assets/logo.svg")
        assert known.status_code == 200

        # 未知资产 404，绝不回 index；且 404 不得带一年缓存。
        missing = client.get("/ui/assets/nope-12345678.js")
        assert missing.status_code == 404
        assert "shorekeeper-ui" not in missing.text
        assert missing.headers["cache-control"] == "no-store"

        # 产物根其他文件不因挂载而暴露。
        for path in (
            "/ui/secret.txt",
            "/ui/assets/../secret.txt",
            "/ui/assets/%2e%2e%2fsecret.txt",
        ):
            escaped = client.get(path)
            assert escaped.status_code == 404, path
            assert "do-not-serve" not in escaped.text, path


def test_ui_security_headers_do_not_leak_onto_api_or_add_cors(tmp_path: Path) -> None:
    _write_dist(tmp_path)
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        ui = client.get("/ui/")
        assert ui.headers.get("access-control-allow-origin") is None

        api = client.get("/api/v1/stats/calls")
        assert api.status_code == 401
        assert api.headers.get("access-control-allow-origin") is None
        assert api.headers.get("content-security-policy") is None
        assert api.headers.get("x-frame-options") is None


def test_ui_assets_missing_directory_is_404_without_leaking_path(tmp_path: Path) -> None:
    """产物未构建（webui/dist/assets 不存在）时 /ui/assets/* 必须如实 404。

    Starlette ``StaticFiles.__call__`` 首个请求仍会 ``check_config()``，目录缺失时
    抛 RuntimeError（check_dir=False 只免构造期检查）⇒ 不修就会把「构建缺席」
    升成 500，并把目录路径写进服务端日志。这里锁 404 + 不泄露路径 + no-store。
    """
    app = _app(tmp_path)  # 不写 dist：assets 目录整个不存在
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        response = client.get("/ui/assets/missing.js")
        assert response.status_code == 404
        assert str(tmp_path) not in response.text
        assert "assets" not in response.json()["error"]["message"]
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("case", ["outside", "equal"])
def test_ui_assets_root_not_a_strict_subdir_is_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """资产根必须是产物根的**严格子目录**：越界（outside）与等值（assets→dist
    本身，等于把产物根散件一起纳入服务面）都不得服务（404）。

    StaticFiles 把 directory ``realpath`` 后当作合法根，故越界根只能由本层自查。
    本机不保证能建 symlink/junction，故用**严格 Path.resolve 替身**只改
    ``dist/assets`` 这一枚的解析结果（其余走真身）；不 skip、不写目录。
    ⚠ 替身只改 ``Path.resolve``（不改 Starlette 内部用的 ``os.path.realpath``），
    故本腿量的是**本层自查判据**：根越界/等值就一枚都不服务（请求的这枚在真
    dist/assets 里是实存的，旧实现会 200 送出 ⇒ 该断言正是红点）。
    """
    dist = _write_dist(tmp_path)
    assets_root = dist / "assets"
    if case == "outside":
        target_root = tmp_path / "outside-assets"
        target_root.mkdir()
        (target_root / "index-a1b2c3d4.js").write_text("EXTERNAL-LEAK", encoding="utf-8")
    else:
        target_root = dist
    real_resolve = Path.resolve

    def fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self == assets_root:
            return real_resolve(target_root)
        return real_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    app = _app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        response = client.get("/ui/assets/index-a1b2c3d4.js")
        assert response.status_code == 404
        assert "EXTERNAL-LEAK" not in response.text
        assert _JS_BODY not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_ui_static_shell_served_even_when_tokens_unprovisioned(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    app = create_control_plane_app(
        _config(tmp_path, admin="", super_admin=""),
        audit_store=ControlPlaneAuditStore(str(tmp_path / "cp-audit.sqlite3")),
        webui_dist_dir=str(dist),
    )
    with TestClient(app, base_url="http://127.0.0.1:8742") as client:
        # 静态壳无数据（healthz 同级）；数据端点此刻 503 not_provisioned。
        assert client.get("/ui/").status_code == 200
        assert client.get("/api/v1/stats/calls").status_code == 503
