"""锁死「只写不读」这一族缺陷：装配期被 except 吞掉的导入错误。

2026-09-19 取证：providers.py 从 `domains.chat_reply.character.kb_wiki` 导入检索器，
而 kb_wiki 真身在 `domains/location/knowledge/`（v21r2 板块重组时 providers.py 迁了家、
引用没跟着迁）。那条路径不存在 → ModuleNotFoundError 被 `except Exception:
kb_retriever = None` 静默吞掉 → 5.7GB / 23.8 万块的 Crawl Wiki 知识库**从来没有读者**，
而同步侧每晚照常爬、照常嵌、照常报成功。

本测试故意不依赖 Ollama / 不依赖真实配置：只验「providers.py 写的那个模块路径，
今天到底存不存在、那两个符号到底拿不拿得到」。这类断言便宜，但它拦住的是
一整条花钱的静默死通道。
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROVIDERS = (
    REPO / "plugins" / "bot_unified_runtime" / "domains" / "chat_reply" / "character" / "providers.py"
)

_IMPORT_RE = re.compile(
    r"from\s+(plugins\.bot_unified_runtime[\w.]*kb_wiki)\s+import\s+\(\s?([^)]*?)\)",
    re.S,
)


def test_providers_references_kb_wiki_at_all():
    """若哪天 wiki 检索器改走别的装配口，本文件必须被人注意到并更新。"""
    assert _IMPORT_RE.findall(PROVIDERS.read_text(encoding="utf-8")), (
        "providers.py 里找不到 kb_wiki 导入了——装配口已变，"
        "请同步更新本回归锁（别删掉，改成新装配口的等价断言）"
    )


@pytest.mark.parametrize(
    ("module_path", "names"),
    [
        (
            "plugins.bot_unified_runtime.domains.location.knowledge.kb_wiki",
            ("build_kb_wiki_retriever", "MergedKnowledgeRetriever"),
        ),
    ],
)
def test_canonical_kb_wiki_exports_the_assembly_symbols(module_path, names):
    module = importlib.import_module(module_path)
    for name in names:
        assert callable(getattr(module, name)), f"{module_path}:{name} 不可调用"


def test_every_kb_wiki_import_path_in_providers_resolves():
    """providers.py 写的每一条 kb_wiki 导入路径，都必须真的能 import。

    这是本席存在意义：路径写错时运行时不会崩，只会静默 kb_retriever=None。
    """
    text = PROVIDERS.read_text(encoding="utf-8")
    found = _IMPORT_RE.findall(text)
    assert found, "没解析到任何 kb_wiki 导入"
    broken: list[str] = []
    for module_path, names_blob in found:
        names = [n.strip() for n in names_blob.replace("\n", " ").split(",") if n.strip()]
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001 - 正是要把被吞掉的异常摊到测试失败面上
            broken.append(f"{module_path} -> {type(exc).__name__}: {exc}")
            continue
        missing = [n for n in names if not hasattr(module, n)]
        if missing:
            broken.append(f"{module_path} 缺符号 {missing}")
    assert not broken, "providers.py 存在死导入路径（会被 except 静默吞掉）：" + "; ".join(broken)
