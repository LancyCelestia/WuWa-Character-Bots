"""F-1 作用域锁（SEAT-FIX-ATK-CP，2026-09-28）：/api/v1/files/read 只认登记根。

背景（SEAT-ATK-CP F-1）：旧实现以 ``Path.cwd()`` 为读取根 ⇒ 持**只读令牌**的主体可
枚举整棵进程工作树（含 ``.log``/``.json``/``.py``）。守卫形态本来就对
（resolve+按段判成员），病根在**根的选择**。修法：根＝显式配置
``bot_control_plane_files_roots``（逗号分隔白名单，缺省空 ⇒ 端点 503 诚实拒绝，
绝不回落 cwd）+ ``data/``/``logs/``/``webui/node_modules/`` 敏感子树与 ``.log``/
``.env*`` 形态 denylist（即便误落登记根内也拒且可归因）。

F-3 收编：守卫唯一执法体＝ ``control_plane/file_access.py::FileReadGateway``
（原零消费者死码，现挂为 F-1 的唯一读取实现口）。本件的 AST 活性锁双向钉死：
api 层必须走网关（收编活性），且 api 层不得自存第二套路径判据（禁第二真身；
审计建议的「HTTP 面不得 import file_access」出册锁在正式收编后由本锁接替）。

判据纪律（既有在册教训，本件逐发验证）：路径成员两侧 ``resolve()`` 后**按段**判成员，
``startswith`` 形态会被 Windows 8.3 短名与兄弟目录前缀撞静默穿透——前缀撞、
``..`` 穿越、短名三族反例各给一枪。全部离线：``tmp_path`` + ``monkeypatch.chdir``，
不碰真实工作树。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from plugins.bot_unified_runtime.control_plane.api import ControlPlaneError
from plugins.bot_unified_runtime.control_plane.api.platform import build_platform_router
from plugins.bot_unified_runtime.control_plane.auth import Principal
from plugins.bot_unified_runtime.control_plane.file_access import (
    FileGatewayError,
    FileReadGateway,
    parse_roots,
)
from plugins.bot_unified_runtime.control_plane.platform import PlatformStore

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "plugins" / "bot_unified_runtime" / "control_plane" / "api"
PLATFORM_PY = API_DIR / "platform.py"
FILE_ACCESS_PY = (
    REPO_ROOT / "plugins" / "bot_unified_runtime" / "control_plane" / "file_access.py"
)

_FILEREADER_MODULE = (
    "plugins.bot_unified_runtime.domains.files.sources.file_reader"
)


async def _read_dep() -> Principal:
    return Principal("test-read", ("admin",))


async def _write_dep() -> Principal:
    return Principal("test-root", ("super_admin", "admin"))


def _harness(roots: Any) -> FastAPI:
    """真实 build_platform_router 挂最小 app；config 交装配期同型快照。"""
    app = FastAPI()
    config = None if roots is None else SimpleNamespace(bot_control_plane_files_roots=roots)
    app.include_router(
        build_platform_router(
            store=PlatformStore(":memory:"),
            read_dependency=_read_dep,
            write_dependency=_write_dep,
            prefix="/api/v1",
            config=config,
        )
    )

    @app.exception_handler(ControlPlaneError)
    async def _handle(request: Request, exc: ControlPlaneError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": exc.code}}
        )

    return app


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """私有哨兵树：cwd 下住敏感物，登记根 srvroot 下住产物，另有前缀撞兄弟目录。"""
    (tmp_path / "secret.log").write_text("top-secret", encoding="utf-8")
    (tmp_path / "x.json").write_text('{"leak": true}', encoding="utf-8")
    (tmp_path / ".env").write_text("BOT_API_KEY_X=leak", encoding="utf-8")
    (tmp_path / "data" / "settings").mkdir(parents=True)
    (tmp_path / "data" / "settings" / "quirks.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "a.log").write_text("noisy", encoding="utf-8")
    (tmp_path / "srvroot").mkdir()
    (tmp_path / "srvroot" / "ok.txt").write_text("artifact", encoding="utf-8")
    (tmp_path / "srvroot_evil").mkdir()
    (tmp_path / "srvroot_evil" / "ok.txt").write_text("not-mine", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _code(client: TestClient, path: str) -> tuple[int, str]:
    resp = client.post("/api/v1/files/read", json={"path": path})
    return resp.status_code, resp.json().get("error", {}).get("code", "")


# ---------------------------------------------------------------------------
# 诚实位：无配置 ⇒ 503，绝不回落 cwd
# ---------------------------------------------------------------------------
def test_unconfigured_roots_is_honest_503(tree: Path) -> None:
    for client in (
        TestClient(_harness("")),
        TestClient(_harness(None)),
        TestClient(_harness([])),
    ):
        status, code = _code(client, "secret.log")
        assert (status, code) == (503, "files_config_unavailable"), (status, code)


def test_default_config_field_is_empty(tree: Path) -> None:
    """缺省即关态：Config 字段默认空串 ⇒ 端点 503 ⇒ 默认配置下读取面逐字节收窄
    （控制面本身默认关，本锁钉的是「一旦开面，未配置=不提供」）。"""
    from plugins.bot_unified_runtime.config import Config

    assert Config().bot_control_plane_files_roots == ""
    from plugins.bot_unified_runtime.control_plane import control_plane_enabled

    assert control_plane_enabled(Config()) is False


# ---------------------------------------------------------------------------
# 作用域主锁：roots 外一律拒且可归因；roots 内产物可 200
# ---------------------------------------------------------------------------
def test_cwd_sentinels_refused_outside_roots(tree: Path) -> None:
    client = TestClient(_harness(str(tree / "srvroot")))
    for sentinel, expect in (("secret.log", 403), ("x.json", 403), (".env", 403)):
        status, code = _code(client, sentinel)
        assert status == expect, f"{sentinel} 逃逸：{status} {code}"
        assert code in {"file_read_rejected", "file_read_denied"}


def test_registered_root_artifact_is_readable(tree: Path) -> None:
    client = TestClient(_harness(str(tree / "srvroot")))
    resp = client.post("/api/v1/files/read", json={"path": "srvroot/ok.txt"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["path"] == "ok.txt"
    assert data["text"] == "artifact"


def test_refusal_happens_before_parse_body(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """守卫排在任何解析/读取之前：roots 外请求必须**不触达** read_supported_file。"""
    import importlib

    calls: list[Path] = []
    filereader = importlib.import_module(_FILEREADER_MODULE)
    real = filereader.read_supported_file

    def _spy(path: Path, **kw: Any):
        calls.append(Path(path))
        return real(path, **kw)

    monkeypatch.setattr(filereader, "read_supported_file", _spy)
    client = TestClient(_harness(str(tree / "srvroot")))
    snapshot_before = sorted(p.name for p in tree.iterdir())
    status, _ = _code(client, "secret.log")
    assert status == 403
    assert calls == [], f"作用域外的请求竟然触达了解析体：{calls}"
    # 守卫零写面：不 mkdir、不落任何新文件。
    assert sorted(p.name for p in tree.iterdir()) == snapshot_before
    assert client.post("/api/v1/files/read", json={"path": "srvroot/ok.txt"}).status_code == 200
    assert len(calls) == 1, "收编后解析体仍必须经网关放行被调用（活性自证）"


# ---------------------------------------------------------------------------
# 反例锁：判据不是 startswith（短名/前缀撞/`..` 穿越三族）
# ---------------------------------------------------------------------------
def test_sibling_prefix_collision_refused(tree: Path) -> None:
    """startswith 形态会把 ``srvroot_evil/...`` 当 ``srvroot`` 的子路放行——必拒。"""
    client = TestClient(_harness(str(tree / "srvroot")))
    status, code = _code(client, "srvroot_evil/ok.txt")
    assert status == 403, f"前缀撞逃逸：{status} {code}"
    status, code = _code(client, "sub/../srvroot_evil/ok.txt")
    assert status == 403, f"穿越+前缀撞逃逸：{status} {code}"


def test_traversal_into_registered_root_is_consistent(tree: Path) -> None:
    """``..`` 在 resolve 后现形：折回登记根内的路径按实况放行（判据是真实集合，
    不是字符串洁癖——与「穿越出根必拒」同一把尺的两面）。"""
    client = TestClient(_harness(str(tree / "srvroot")))
    assert client.post(
        "/api/v1/files/read", json={"path": "sub/../srvroot/ok.txt"}
    ).status_code == 200
    status, _ = _code(client, "srvroot/../secret.log")
    assert status == 403, "穿越出根必拒"


def test_absolute_paths_are_422(tree: Path) -> None:
    client = TestClient(_harness(str(tree / "srvroot")))
    # POSIX 形态在 NT 上 `is_absolute()` 为 False（无盘符）——两种形态都必须被拒，
    # 拒的出口（422 绝对拒 / 403 作用域拒）都是 fail-closed，不放宽到 200/404-放行面。
    for path, expect in (
        ("C:/Windows/win.ini", {422}),
        ("/etc/passwd", {422, 403}),
        (str(tree / "secret.log"), {422}),
    ):
        status, code = _code(client, path)
        assert status in expect and code == "file_read_rejected", (path, status, code)


def _short_form(target: Path, anchor: Path) -> str | None:
    """取 Windows 8.3 短名相对形态；不可用（非 NT / 8.3 关闭 / 与长名同形）返回 None。"""
    if os.name != "nt":
        return None
    import ctypes

    def _short(path: Path) -> str:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 260)
        if 0 < size < 260:
            return "".join(ch for ch in buf if ch != "\0")
        return str(path)

    short_target, short_anchor = _short(target), _short(anchor)
    prefix = short_anchor + "\\"
    if not short_target.upper().startswith(prefix.upper()):
        return None
    rel = short_target[len(prefix):]
    if rel.lower() == target.name.lower():
        return None  # 短名与长形同 ⇒ 本机注入不了这一族反例
    return rel


@pytest.mark.parametrize("probe_dir", ["logs", "srvroot"])
def test_83_short_name_follows_resolved_membership(tree: Path, probe_dir: str) -> None:
    """在册教训反例：短名两侧 resolve 后必须折叠成同一真实路径——
    禁区内短名仍拒（denied/rejected 皆属拒），登记根内短名仍 200。"""
    rel_dir = _short_form(tree / probe_dir, tree)
    if rel_dir is None or rel_dir.lower() == probe_dir.lower():
        pytest.skip("本机 8.3 短名不可用或与长名同形，注入不了这一族反例")
    client = TestClient(_harness(str(tree)))  # 覆盖全 cwd 的根 ⇒ 剩 denylist 在守
    status, code = _code(client, f"{rel_dir}/a.log")
    if probe_dir == "logs":
        assert status == 403, f"短名绕过禁区：{status} {code}"
    else:  # srvroot 内短名形态必须仍能读到（resolve 折叠的正面）
        status, code = _code(client, f"{rel_dir}/ok.txt")
        assert status == 200, f"短名没被折叠回真实路径：{status} {code}"


# ---------------------------------------------------------------------------
# denylist：误配大盘根时敏感子树/后缀/名字仍然拒，且可归因
# ---------------------------------------------------------------------------
def test_denylist_beats_overbroad_root(tree: Path) -> None:
    client = TestClient(_harness(str(tree)))  # 根＝整棵 cwd（运维误配形态）
    for path in (
        "logs/a.log",
        "data/settings/quirks.json",
        ".env",
        "secret.log",
    ):
        status, code = _code(client, path)
        assert status == 403, f"{path} 逃逸：{status} {code}"
        assert code == "file_read_denied", f"{path} 拒绝不可归因：{code}"
    # denylist 不误伤登记根内产物（否则修法过头）。
    assert client.post(
        "/api/v1/files/read", json={"path": "srvroot/ok.txt"}
    ).status_code == 200


def test_missing_file_inside_root_is_404(tree: Path) -> None:
    client = TestClient(_harness(str(tree / "srvroot")))
    status, code = _code(client, "srvroot/missing.txt")
    assert (status, code) == (404, "file_not_supported")


# ---------------------------------------------------------------------------
# 网关单元锁（含注毒自证：判据喂合成输入必须按预期拒/放）
# ---------------------------------------------------------------------------
def test_parse_roots_shape() -> None:
    assert parse_roots(None) == ()
    assert parse_roots("") == ()
    assert parse_roots(" , , ") == ()
    parsed = parse_roots("a, b/")
    assert [p.name for p in parsed] == ["a", "b"] or len(parsed) == 2
    assert parse_roots(["a", "", " b "]) and all(p.is_absolute() for p in parse_roots(["a"]))


def test_gateway_empty_roots_refuses_everything(tree: Path) -> None:
    gateway = FileReadGateway(())
    with pytest.raises(FileGatewayError, match="path_not_allowed"):
        gateway.authorize("srvroot/ok.txt")


def test_gateway_predicate_poison_selfproof(tree: Path) -> None:
    """注毒自证（单元面）：同一网关，喂 startswith 会放行的三种形态都必须拒；
    喂真实成员必须放（证明不是「全拒装样」）。"""
    gateway = FileReadGateway((tree / "srvroot",))
    # (a) 兄弟前缀撞
    with pytest.raises(FileGatewayError, match="path_not_allowed"):
        gateway.authorize("srvroot_evil/ok.txt")
    # (b) 绝对路径
    with pytest.raises(FileGatewayError, match="absolute_path_forbidden"):
        gateway.authorize(str(tree / "srvroot" / "ok.txt"))
    # (c) 空路径
    with pytest.raises(FileGatewayError, match="absolute_path_forbidden"):
        gateway.authorize("")
    # 正面：登记根内成员放行
    candidate, matched = gateway.authorize("srvroot/ok.txt")
    assert candidate == (tree / "srvroot" / "ok.txt").resolve()
    assert matched == (tree / "srvroot").resolve()
    # 误配大盘根下 denylist 执法（守卫先于任何读取）：
    wide = FileReadGateway((tree,))
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.authorize("logs/a.log")
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.authorize("data/settings/quirks.json")
    with pytest.raises(FileGatewayError, match="denied_location"):
        wide.authorize(".env")
    # 禁后缀：登记根内的 .log 也走 deny（即便前缀不在子树）。
    (tree / "srvroot" / "sneaky.log").write_text("x", encoding="utf-8")
    with pytest.raises(FileGatewayError, match="denied_location"):
        FileReadGateway((tree / "srvroot",)).authorize("srvroot/sneaky.log")


# ---------------------------------------------------------------------------
# F-3 收编活性锁（AST）：api 面必须走网关，且不得自存第二套路径判据
# ---------------------------------------------------------------------------
def _attribute_names(source: str) -> set[str]:
    tree = ast.parse(source)
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def api_surface_violations(sources: dict[str, str]) -> list[str]:
    """纯谓词（注毒打同一靶）：control_plane/api 面源码里
    ① 出现 ``Path.cwd`` 形态（`cwd` 属性访问）＝把根选回进程目录的复发形状；
    ② 出现 ``.parents`` 段判成员＝第二套路径判据住在 HTTP 层（禁第二真身）；
    ③ files/read 读取端点不走 ``FileReadGateway``＝收编失效/旁路预备役。
    """
    violations: list[str] = []
    for name, source in sorted(sources.items()):
        attrs = _attribute_names(source)
        if "cwd" in attrs:
            violations.append(f"{name}: Path.cwd 复发（根必须是登记白名单）")
        if "parents" in attrs:
            violations.append(f"{name}: HTTP 层自存 .parents 第二判据（守卫唯一真身=网关）")
    platform_src = sources.get("platform.py", "")
    if "FileReadGateway" not in platform_src or ".authorize(" not in platform_src:
        violations.append("platform.py: /files/read 未走 FileReadGateway（F-3 收编脱钩）")
    return violations


def test_api_surface_routes_through_gateway_no_second_predicate() -> None:
    sources = {p.name: p.read_text(encoding="utf-8") for p in sorted(API_DIR.glob("*.py"))}
    assert sources, "api 目录读空＝尺失明"
    assert api_surface_violations(sources) == []


def test_file_access_is_live_and_guards_reside_once() -> None:
    """收编活性：file_access 的守卫在网关内**恰好一处**，且 platform 源码 import 它。"""
    gateway_src = FILE_ACCESS_PY.read_text(encoding="utf-8")
    assert gateway_src.count("def authorize") == 1, "守卫出现第二本＝执法点分叉"
    platform_src = PLATFORM_PY.read_text(encoding="utf-8")
    assert "from ..file_access import" in platform_src
    assert "Path.cwd" not in platform_src


def test_poison_ast_lock_has_teeth() -> None:
    """注毒自证（AST 锁）：旧 cwd 形态、startswith 旁支、收编脱钩三种毒都必须被
    同一个谓词点名；干净合成源必须放行（防锁松到恒过、也防紧到误伤）。"""
    legacy_cwd = (
        "from pathlib import Path\n"
        "def read_file(payload):\n"
        "    candidate = (Path.cwd() / payload['path']).resolve()\n"
        "    root = Path.cwd().resolve()\n"
        "    if root != candidate and root not in candidate.parents:\n"
        "        raise ValueError\n"
    )
    assert any("Path.cwd" in v for v in api_surface_violations({"platform.py": legacy_cwd}))
    # startswith 旁支形态：AST 尺今天只点名 cwd 复发与 .parents 第二判据两种形状，
    # 这一形**不在**该尺射程（照实写）——它的杀伤力由行为锁
    # `test_sibling_prefix_collision_refused`（前缀撞必拒）与
    # `test_gateway_predicate_poison_selfproof` 共同接住，不假称这把尺能抓。
    side_by_side = (
        "from ..file_access import FileReadGateway\n"
        "def read_file(gateway, payload):\n"
        "    gateway.authorize(payload['path'])\n"
        "    return payload['path'].startswith('/srv')\n"
    )
    assert api_surface_violations({"platform.py": side_by_side}) == []
    detached = "def read_file(payload):\n    return None\n"
    assert any("未走 FileReadGateway" in v for v in api_surface_violations({"platform.py": detached}))
    second_predicate = (
        "from ..file_access import FileReadGateway\n"
        "def read_file(candidate):\n"
        "    FileReadGateway(())\n"
        "    return candidate.parents\n"
    )
    assert any("第二判据" in v for v in api_surface_violations({"platform.py": second_predicate}))
    clean = (
        "from ..file_access import FileReadGateway\n"
        "def read_file(gateway, relative):\n"
        "    return gateway.authorize(relative)\n"
    )
    assert api_surface_violations({"platform.py": clean}) == []


# ---------------------------------------------------------------------------
# 四处同生登记锁（缺一个面当场点名）
# ---------------------------------------------------------------------------
def test_key_registered_across_all_faces() -> None:
    """新键登记＝config.py 字段 / settings.py RESTART 清单 / .env.example 激活行 /
    catalog 收录，四面缺一即「在册未执法」预备役。"""
    config_src = (REPO_ROOT / "plugins/bot_unified_runtime/config.py").read_text(
        encoding="utf-8"
    )
    assert "bot_control_plane_files_roots" in config_src
    settings_src = (
        REPO_ROOT
        / "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py"
    ).read_text(encoding="utf-8")
    assert '"BOT_CONTROL_PLANE_FILES_ROOTS"' in settings_src, (
        "装配期快照键未登 RESTART_REQUIRED_KEYS＝做成『看着能热改』假象（C-09）"
    )
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "BOT_CONTROL_PLANE_FILES_ROOTS=" in env_example, (
        "只认列 0 激活键行，注释形态不算（env_example_gate 同口径）"
    )
    catalog = (REPO_ROOT / "docs/config-catalog-full.md").read_text(encoding="utf-8")
    assert "BOT_CONTROL_PLANE_FILES_ROOTS" in catalog
