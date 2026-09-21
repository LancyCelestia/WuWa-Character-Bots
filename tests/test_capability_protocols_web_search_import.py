"""F1 席回归锁：``runtime/capability_protocols.py`` 的 web_search 延迟导入必须指现役真身。

缺陷（audit-20260920-unify-U2-proto §二 U2-P0-1 / audit-20260920-unify-U5-arch §12 F-02，
两席同坐标独立实锤）：``_WebChainAsSearchProvider.search()`` 体内仍 from-import 已于
v21r4-B 退役删除的垫片 ``sources/web_search.py``，注释却谎称「垫片挂起」。运行期
ImportError 被 ``search_service.search_provider`` 的 ``except Exception`` 分类成
per-source「未预期异常」，整链降级成 DEGRADED/NOT_CONFIGURED 静默——表面无异常、实际链路断。
同文件 ``_web_provider_or_none``（P0-2 那轮修的第一处）已是正确写法，本锁盯第二处。

锁的三层：
- 可达性：模块可导入、适配器可调用、canonical 符号在盘且可调用（不许 try/except 吞、不许造第三层包装）；
- 端到端：走 ``search.unified`` 真链路（不注入 providers），断言 OK 且命中带 web_chain 检索模式，
  并钉死「不得出现 ImportError 字样」——即不得再以降级伪装断链；
- 反证（AST）：本文件内每一条 ``from plugins.bot_unified_runtime…`` 引用的符号必须在盘上可解析，
  且旧垫片路径永久为死（防同类「函数体内 deferred import」再漏网）。

全离线：搜索引擎用 fake，零真实网络、零消息发送。
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.core.search import search_service, web_search
from plugins.bot_unified_runtime.runtime import capability_protocols
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    InvocationStatus,
    _web_provider_or_none,
    _WebChainAsSearchProvider,
    default_invoker,
)

_PROTOCOLS_PATH = Path(capability_protocols.__file__).resolve()
_PACKAGE_NAME = capability_protocols.__package__ or "plugins.bot_unified_runtime.runtime"
_ROOT = _PROTOCOLS_PATH.parents[3]  # …/ChatBot（含 plugins/）
_RETIRED_SHIM = _ROOT / "plugins" / "bot_unified_runtime" / "sources" / "web_search.py"
_CANONICAL = _ROOT / "plugins" / "bot_unified_runtime" / "domains" / "core" / "search" / "web_search.py"


class _FakeEngineHit:
    def __init__(self, title: str, url: str, snippet: str) -> None:
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source_domain = "example.com"


class _FakeWebEngine:
    """假引擎链（真身 provider 的同形替身）：``search(query, max_results=…)``。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int = 8) -> list[_FakeEngineHit]:
        self.calls.append((query, max_results))
        return [_FakeEngineHit("守岸人设定", "https://example.com/a", "泰缇斯系统第二实例")]


def _query(**overrides: Any) -> search_service.ProviderQuery:
    args: dict[str, Any] = {"source_id": "general", "query": "守岸人", "limit": 3}
    args.update(overrides)
    return search_service.ProviderQuery(**args)


# ---------------------------------------------------------------------------
# ① 事实基线：旧垫片确实已删、canonical 真身确实在盘
# ---------------------------------------------------------------------------


def test_retired_shim_is_still_gone() -> None:
    """退役决议不可逆：``sources/web_search.py`` 必须继续不存在（否则本锁失去前提）。"""
    assert not _RETIRED_SHIM.exists(), f"垫片又出现了：{_RETIRED_SHIM}"
    with pytest.raises(ImportError) as excinfo:
        from plugins.bot_unified_runtime.sources import web_search  # noqa: F401

    assert "web_search" in str(excinfo.value)


def test_canonical_web_search_symbols_exist_and_callable() -> None:
    """现役真身 = domains/core/search/web_search.py；被引用符号必须在盘、可解析、可调用。"""
    assert _CANONICAL.exists()
    assert web_search.__name__ == "plugins.bot_unified_runtime.domains.core.search.web_search"
    assert callable(web_search.build_web_search_provider)
    assert isinstance(web_search.NullWebSearchProvider, type)
    # 关闭开关 → Null（诚实 not_configured 语义，不是 ImportError）
    provider, usable = _web_provider_or_none(SimpleNamespace(bot_web_search_enabled=False))
    assert usable is False
    assert isinstance(provider, web_search.NullWebSearchProvider)


# ---------------------------------------------------------------------------
# ② 可达性 + 端到端：不得再有 ImportError 伪装成降级
# ---------------------------------------------------------------------------


def test_protocols_module_imports_without_error() -> None:
    """断言 (a)：契约层模块可成功 import（不抛 ImportError）。"""
    module = importlib.import_module("plugins.bot_unified_runtime.runtime.capability_protocols")
    assert callable(module._WebChainAsSearchProvider)
    assert callable(module._handle_search_unified)


def test_web_chain_adapter_search_returns_hits() -> None:
    """RED→GREEN 主证据：适配器 ``search()`` 体内 import 必须成功并产出命中。"""
    engine = _FakeWebEngine()
    hits = _WebChainAsSearchProvider(engine).search(_query())

    assert engine.calls == [("守岸人", 3)]
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, search_service.ProviderRawHit)
    assert hit.url == "https://example.com/a"
    assert hit.retrieval_mode.startswith("web_chain:")
    # 反证：检索模式串必须指现役真身模块，不是已退役垫片路径
    assert "sources" not in hit.retrieval_mode
    assert hit.retrieval_mode.endswith("domains.core.search.web_search")


def test_unified_search_over_web_chain_is_ok_not_silent_degrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """端到端：不注入 providers 时走 web 引擎链，必须真出命中，不得降级静默。"""
    monkeypatch.setattr(
        web_search,
        "build_web_search_provider",
        lambda config=None: _FakeWebEngine(),
    )
    result = default_invoker().invoke(
        capability_protocols.CapabilityRequest(
            capability_id="search.unified",
            payload={"query": "守岸人", "source_ids": ["general"], "limit": 3},
            principal="tester",
            roles=("user",),
            context={"config": SimpleNamespace(bot_web_search_enabled=True)},
        )
    )
    blob = json.dumps(
        {
            "status": result.status.value,
            "detail": result.detail,
            "data": result.data,
        },
        ensure_ascii=False,
        default=str,
    )
    assert "ImportError" not in blob, f"链路仍被 ImportError 伪装成降级：{blob}"
    assert result.status is InvocationStatus.OK, blob
    assert result.data["hits"][0]["title"] == "守岸人设定"
    assert result.data["hits"][0]["retrieval_mode"].startswith("web_chain:")
    assert result.data["per_source"][0]["status"] == "ok"


# ---------------------------------------------------------------------------
# ③ 反证锁：本文件内所有 plugins 级 import 符号必须在盘可解析
# ---------------------------------------------------------------------------


def _resolve(module_name: str, attr: str) -> bool:
    """``from <module_name> import <attr>`` 是否可解析（子模块在盘 或 父模块属性存在）。"""
    try:
        if importlib.util.find_spec(f"{module_name}.{attr}") is not None:
            return True
    except (ImportError, ValueError, ModuleNotFoundError):
        pass
    try:
        parent = importlib.import_module(module_name)
    except ImportError:
        return False
    return hasattr(parent, attr)


def _dead_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """本文件内所有 plugins 级 import 中不可解析的 ``(行号, 引用串)``。"""
    dead: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("plugins.") and importlib.util.find_spec(alias.name) is None:
                    dead.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith("plugins."):
                continue
            module = node.module
            if node.level:  # 相对导入：以本文件所在包为锚
                module = _PACKAGE_NAME + "." + module
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not _resolve(module, alias.name):
                    dead.append((node.lineno, f"from {module} import {alias.name}"))
    return sorted(dead)


def test_no_dead_from_import_of_retired_shim_in_protocols() -> None:
    """结构性反证：函数体内 deferred import 也在扫描范围内（漏改第 5 处的根因）。"""
    tree = ast.parse(_PROTOCOLS_PATH.read_text(encoding="utf-8"))
    dead = _dead_imports(tree)
    assert not dead, f"capability_protocols.py 存在不可解析 import（死垫片引用？）：{dead}"


def test_lying_shim_comment_is_gone() -> None:
    """注释诚实门：垫片已退役，不得再声称「挂起/维持旧路径」。"""
    source = _PROTOCOLS_PATH.read_text(encoding="utf-8")
    assert "垫片挂起" not in source
    assert "sources import web_search" not in source
    assert 'from plugins.bot_unified_runtime.sources import (\n            web_search' not in source
