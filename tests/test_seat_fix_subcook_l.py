"""席位 S-FIX-SUBCOOK-L 收口锁（票1-票4）。

对应审计 SEAT-ATK-SUBCOOK 四条遗留票面，全部只锁不放宽：

- 票1（裸开器绕喉）：订阅链不得出现绕过中央咽喉（link_parse/parsers/
  ``http_util``）的出站原语；并锁 ``test_credential_domain_binding_gate`` 已
  把 ``subscribe`` 纳入扫描域（负样本注毒自证门有牙）。
- 票2（Win32 保留设备名）：订阅侧唯一「用户/远端可控目录名」落盘腿
  ``today_history._card_dir_token`` 必须消费中央判据
  ``restricted_runner.sanitize_write_segments``，且不得复刻第二真身点号切分。
- 票3（sqlite ``with self._connect()`` 句柄累积）：订阅域存储是**缓存单例连接**
  （非每调新建），零句柄累积；本锁钉死「单例复用 + close 归 None」不变量，并
  禁止订阅域出现「每调新建再 ``with conn``（只提交不关）」的泄漏形。
- 票4（``max_bytes=0`` 语义）：三值语义单一真身 ``_effective_max_bytes``
  （None=默认上限 / 正=该上限 / 0、负=不限制＝显式退出护栏），行为零翻转；
  全仓零调用方今日显式传 0/负，本锁现算复核该事实。

本门自身不联网、纯静态/受控假响应读盘。
"""

from __future__ import annotations

import ast
import gzip
import inspect
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.link_parse.parsers import http_util
from plugins.bot_unified_runtime.domains.subscribe.capabilities import today_history
from plugins.bot_unified_runtime.domains.subscribe.store import (
    subscription_store as _v1_mod,
)
from plugins.bot_unified_runtime.domains.subscribe.store import (
    subscription_store_v2 as _v2_mod,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "bot_unified_runtime"
_SUBSCRIBE_DIR = _PLUGIN_ROOT / "domains" / "subscribe"
_SOURCES_SUBS_DIR = _PLUGIN_ROOT / "sources" / "subscriptions"


def _iter_py(*dirs: Path) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        if d.exists():
            files.extend(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    return files


# ---------------------------------------------------------------------------
# 票1：订阅链不得绕过中央咽喉直连出站
# ---------------------------------------------------------------------------
_BANNED_HTTP_MODULES = {"requests", "httpx", "aiohttp", "urllib3"}


def _scan_bare_opener(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BANNED_HTTP_MODULES:
                    hits.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _BANNED_HTTP_MODULES:
                hits.append(f"{path}:{node.lineno}: from {node.module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in {"urlopen", "build_opener", "install_opener"}:
                hits.append(f"{path}:{node.lineno}: 裸出站原语 {name}()")
    return hits


def test_subscribe_chain_has_no_bare_opener() -> None:
    """订阅域 + 订阅源里不得有绕喉裸开器（票1：只此一条路，无第二条腿）。"""
    offenders: list[str] = []
    for path in _iter_py(_SUBSCRIBE_DIR, _SOURCES_SUBS_DIR):
        offenders.extend(_scan_bare_opener(path))
    assert not offenders, "订阅链绕过中央咽喉的出站：\n" + "\n".join(offenders)


def test_bare_opener_scanner_has_teeth() -> None:
    """注毒自证：把一条绕喉出站塞进临时文件，扫描器必须报红（否则门形同虚设）。"""
    bad = (
        "import urllib.request as u\n"
        "def fetch(url):\n"
        "    return u.build_opener().open(url)\n"
    )
    tmp = _SUBSCRIBE_DIR / "_seat_subcookl_probe_tmp.py"
    tmp.write_text(bad, encoding="utf-8")
    try:
        hits = _scan_bare_opener(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    assert hits, "注毒的裸开器必须被扫出"


def test_credential_gate_scans_subscribe_domain() -> None:
    """票1：凭证咽喉再生门已把 subscribe 纳入扫描域（防回退）。"""
    gate = _REPO_ROOT / "tests" / "test_credential_domain_binding_gate.py"
    src = gate.read_text(encoding="utf-8")
    m = re.search(r"SCANNED_DOMAINS\s*=\s*\(([^)]*)\)", src)
    assert m and "subscribe" in m.group(1), "credential 门必须扫描 subscribe 域"


# ---------------------------------------------------------------------------
# 票2：订阅侧目录名必须吃中央保留设备名判据
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    ["nul", "nul ", "NUL", "con", "COM1", "aux", "lpt9", "nul/con", "nul?x"],
)
def test_card_dir_token_rejects_reserved_device_names(raw: str) -> None:
    """清洗后仍命中 Win32 保留设备名的目录段必须被拒（回退随机安全名）。"""
    token = today_history._card_dir_token(raw)
    head = token.split(".", 1)[0].casefold()
    reserved = (
        {"con", "prn", "aux", "nul"}
        | {f"com{i}" for i in range(1, 10)}
        | {f"lpt{i}" for i in range(1, 10)}
    )
    assert head not in reserved, f"目录段 {token!r} 命中保留设备名，判据未咬"
    assert re.fullmatch(r"[0-9A-Za-z_-]{1,64}", token)


@pytest.mark.parametrize("raw", ["2026-09-27", "9月27日", "abc_123"])
def test_card_dir_token_keeps_safe_names(raw: str) -> None:
    token = today_history._card_dir_token(raw)
    assert re.fullmatch(r"[0-9A-Za-z_-]{1,64}", token)
    assert token == re.sub(r"[^0-9A-Za-z_-]", "", raw)[:64]


def test_card_dir_token_consumes_central_criteria_not_second_source() -> None:
    """真身单源锁：_card_dir_token 必须经中央 sanitize_write_segments 判定，
    且不得在本模块复刻点号切分/设备名表（避免第二真身漂移）。"""
    src = inspect.getsource(today_history)
    assert "sanitize_write_segments" in src, "票2 未接线：目录名未过中央判据"
    # 本模块内不得另立设备名表 / 点号首段比对。
    assert "_RESERVED_WIN32_BASENAMES" not in src
    assert ".split(\".\", 1)[0]" not in src and ".split('.')[0]" not in src


def test_card_dir_token_denies_nul_end_to_end() -> None:
    """注毒自证：中央判据对裸 ``nul`` 目录段必拒（证明真接线而非静默通过）。"""
    from plugins.bot_unified_runtime.domains.files.sender import restricted_runner

    with pytest.raises(Exception) as exc:
        restricted_runner.sanitize_write_segments("nul")
    assert getattr(exc.value, "code", "") == "reserved_name"
    # 经 _card_dir_token 后不得仍是保留名。
    assert today_history._card_dir_token("nul").casefold() != "nul"


# ---------------------------------------------------------------------------
# 票3：订阅域存储 = 缓存单例连接（零句柄累积），禁泄漏形
# ---------------------------------------------------------------------------
def _counting_sqlite(real_mod):
    state = {"connects": 0}

    class _Proxy:
        def connect(self, *a, **k):
            state["connects"] += 1
            return real_mod.connect(*a, **k)

        def __getattr__(self, name):  # 透传 sqlite3.Row / Error 等
            return getattr(real_mod, name)

    return _Proxy(), state


@pytest.mark.parametrize(
    "module,cls",
    [(_v1_mod, "SubscriptionStore"), (_v2_mod, "SubscriptionStoreV2")],
)
def test_store_connection_is_cached_singleton(tmp_path, monkeypatch, module, cls) -> None:
    """反复读操作只建**一枚**连接（票3：句柄数 O(1)，非每调新建→不累积）。"""
    proxy, state = _counting_sqlite(module.sqlite3)
    monkeypatch.setattr(module, "sqlite3", proxy)
    store = getattr(module, cls)(str(tmp_path / "t.sqlite3"))
    try:
        first = store._get_connection()
        for _ in range(25):
            assert store._get_connection() is first  # 同一对象复用
        assert state["connects"] == 1, "读侧不应反复 sqlite3.connect"
    finally:
        store.close()


@pytest.mark.parametrize(
    "module,cls",
    [(_v1_mod, "SubscriptionStore"), (_v2_mod, "SubscriptionStoreV2")],
)
def test_store_close_resets_connection(tmp_path, module, cls) -> None:
    """close() 归 None：Windows 下删库需先 shutdown（连接随进程存活，非泄漏）。"""
    store = getattr(module, cls)(str(tmp_path / "t.sqlite3"))
    store._get_connection()
    assert store._connection is not None
    store.close()
    assert store._connection is None
    # close 后再取即重建（生命周期语义正确）。
    conn = store._get_connection()
    assert conn is not None
    store.close()


def test_subscribe_domain_forbids_leaky_with_connect_pattern() -> None:
    """结构锁：订阅域不得出现「每调新建连接再 ``with conn:``（只提交不关）」泄漏形。

    先例：紧急信息/媒体/campus 的 ``with self._connect()``（_connect 每次新建）才是
    累积源；订阅域用缓存单例 _get_connection，本锁防的是「将来误改成每调新建」。
    """
    leaky = re.compile(r"with\s+self\._connect\(\)")
    offenders: list[str] = []
    for path in _iter_py(_SUBSCRIBE_DIR):
        text = path.read_text(encoding="utf-8")
        if leaky.search(text):
            offenders.append(str(path.relative_to(_PLUGIN_ROOT)))
        # _connect 若存在，必须是 @contextmanager 出口必关（照 emergency 先例）。
        for m in re.finditer(r"def _connect\(self", text):
            head = text[: m.start()]
            if "@contextmanager" not in head[-400:]:
                offenders.append(f"{path}: _connect 非 @contextmanager 出口必关")
    assert not offenders, "订阅域出现句柄累积形：\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# 票4：max_bytes 三值语义单一真身（0=不限制，零行为翻转）
# ---------------------------------------------------------------------------
def test_effective_max_bytes_single_truth() -> None:
    f = http_util._effective_max_bytes
    assert f(None) == http_util.DEFAULT_MAX_BYTES  # 默认生效（护栏在）
    assert f(1024) == 1024                          # 正上限
    assert f(0) == 0                                # 不限制（显式退出）
    assert f(-1) == 0                               # 负数归一为「不限制」真值 0
    assert f(-100) == 0


class _FakeResponse:
    def __init__(self, body: bytes, *, encoding: str = "") -> None:
        self._body = body
        self._pos = 0
        self.headers = {"Content-Encoding": encoding}

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            chunk = self._body[self._pos:]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def geturl(self) -> str:
        return "https://example.invalid/final"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def open(self, request, timeout=None):
        return self._response


def _patch_opener(monkeypatch, response: _FakeResponse) -> None:
    monkeypatch.setattr(http_util, "_build_opener", lambda *a, **k: _FakeOpener(response))


def test_http_get_default_caps_body(monkeypatch) -> None:
    big = b"x" * (http_util.DEFAULT_MAX_BYTES + 1)
    _patch_opener(monkeypatch, _FakeResponse(big))
    with pytest.raises(http_util.ParseHttpError, match="max_bytes"):
        http_util.http_get("https://example.invalid/late")


def test_http_get_capped_positive_limit(monkeypatch) -> None:
    _patch_opener(monkeypatch, _FakeResponse(b"0123456789"))
    with pytest.raises(http_util.ParseHttpError, match="max_bytes=5"):
        http_util.http_get("https://example.invalid/x", max_bytes=5)


def test_http_get_zero_means_unlimited(monkeypatch) -> None:
    """票4 定版：max_bytes=0 = 不限制（全量读，无护栏），非「拒绝一切」。"""
    body = b"y" * (http_util.DEFAULT_MAX_BYTES + 4096)
    _patch_opener(monkeypatch, _FakeResponse(body))
    final_url, payload = http_util.http_get("https://example.invalid/un", max_bytes=0)
    assert payload == body
    assert final_url == "https://example.invalid/final"


def test_http_get_negative_means_unlimited(monkeypatch) -> None:
    body = b"z" * (http_util.DEFAULT_MAX_BYTES + 10)
    _patch_opener(monkeypatch, _FakeResponse(body))
    _, payload = http_util.http_get("https://example.invalid/n", max_bytes=-5)
    assert payload == body


def test_http_get_capped_gzip_bomb_guard(monkeypatch) -> None:
    """限幅路径：gzip 响应解压输出超限也拒（gzip 炸弹护栏未被票4 重构削弱）。"""
    payload = gzip.compress(b"M" * (64 * 1024))
    _patch_opener(monkeypatch, _FakeResponse(payload, encoding="gzip"))
    with pytest.raises(http_util.ParseHttpError, match="max_bytes"):
        http_util.http_get("https://example.invalid/bomb", max_bytes=1024)


def test_http_post_json_zero_unlimited_and_default_capped(monkeypatch) -> None:
    body = b'{"ok": true}'
    _patch_opener(monkeypatch, _FakeResponse(body))
    assert http_util.http_post_json("https://example.invalid/p", {"a": 1}, max_bytes=0) == {"ok": True}
    big = b'{"k": "' + b"x" * (http_util.DEFAULT_MAX_BYTES) + b'"}'
    _patch_opener(monkeypatch, _FakeResponse(big))
    with pytest.raises(http_util.ParseHttpError, match="max_bytes"):
        http_util.http_post_json("https://example.invalid/p", {"a": 1})


def test_no_caller_sets_http_throat_max_bytes_non_positive() -> None:
    """零行为翻转的事实锁（票4）：全仓插件源码内，对咽喉函数（http_get*/http_post*）

    的调用**无一**显式把 ``max_bytes`` 传成 0/负（＝退出大小护栏）。若将来真有人
    显式写不限制，本锁红 → 强制单独审计，而非默默放行 gzip 炸弹通道。
    """
    throat = {"http_get", "http_get_text", "http_get_json", "http_post_json", "http_post_form"}
    bad: list[str] = []
    for path in _iter_py(_PLUGIN_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            if name not in throat:
                continue
            for kw in node.keywords:
                if kw.arg != "max_bytes":
                    continue
                value: int | None = None
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                    value = kw.value.value
                elif (
                    isinstance(kw.value, ast.UnaryOp)
                    and isinstance(kw.value.op, ast.USub)
                    and isinstance(kw.value.operand, ast.Constant)
                    and isinstance(kw.value.operand.value, int)
                ):
                    value = -kw.value.operand.value
                if value is not None and value <= 0:
                    bad.append(f"{path.relative_to(_PLUGIN_ROOT)}:{node.lineno}: {name}(max_bytes={value})")
    assert not bad, "咽喉调用显式退出大小护栏，需单独审计：\n" + "\n".join(bad)
