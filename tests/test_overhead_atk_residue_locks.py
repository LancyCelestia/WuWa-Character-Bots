"""攻击者复查波残票收口席（S-FIX-ATK-OVERHEAD，2026-09-27）结构锁。

锁两票（均出自 SEAT-ATK-LINKPARSE，真身清点见该席报告）：

- F-5（双重真身陷阱）：``link_parse/parsers/context.py`` 曾有同名
  ``build_request_headers`` 直写 ``Cookie`` 头、绕开 WP1 凭证咽喉
  （``credentials_allowed_for_target``/``_apply_cookie_guard``/跨 host 剥除），
  全树零生产调用方——误 import 即静默复活 F-CRED 类外流。本席已将真身
  从源件移除；本锁断言全 plugins 树 ``build_request_headers`` 的定义点
  只剩 ``http_util.py`` 一枚（注毒自证：往 context.py 重新加一份定义 ⇒ 必红）。

- F-6（窄域归因在字符串重组处丢失）：``platforms_weibo._weibo_merge_cookies``
  的 strip/join 重组曾把 ``PlatformCookie``（str 子类、携 ``cookie_domains``
  窄域真身）拍平成普通 str，归因丢失后咽喉只能回退联合域。本锁断言：
  PlatformCookie 输入合并后仍是 PlatformCookie、窄域归因与 platform 原样
  透传、登录 cookie 优先语义不变；普通 str 输入零行为变化（注毒自证：
  把重建段删掉 ⇒ 第一例必红）。

卫生：本件全离线，不触网、不落 data/（visitor 腿经 monkeypatch 替换）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    platforms_weibo,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    PlatformCookie,
)

_PLUGIN_ROOT = (
    Path(__file__).resolve().parent.parent
    / "plugins"
    / "bot_unified_runtime"
)


def _definitions_of(func_name: str) -> set[str]:
    """全 plugins 树 AST 扫描：返回定义了该函数名的文件（相对 posix 路径）。"""
    found: set[str] = set()
    for py in _PLUGIN_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 树内不应出现
            raise AssertionError(f"unparsable plugin file: {py}")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    found.add(py.relative_to(_PLUGIN_ROOT.parent).as_posix())
    return found


def test_f5_build_request_headers_has_single_truth_source() -> None:
    """F-5：``build_request_headers`` 真身唯一＝http_util（context 副本已移除）。"""
    defs = _definitions_of("build_request_headers")
    assert defs == {
        "bot_unified_runtime/domains/link_parse/parsers/http_util.py"
    }, f"第二真身回潮：{sorted(defs)}"


def test_f5_context_module_no_longer_exposes_the_dead_twin() -> None:
    """F-5：context 模块面上不再有可误 import 的 build_request_headers。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers import context

    assert not hasattr(context, "build_request_headers")


def test_f6_weibo_merge_preserves_platform_cookie_attribution(
    monkeypatch,
) -> None:
    """F-6：窄域输入合并后归因不丢，且登录 cookie 优先语义不变。"""
    monkeypatch.setattr(
        platforms_weibo,
        "_weibo_visitor_cookie",
        lambda: "SUB=visitor; SUBP=v2; tid=v3",
    )
    owned = PlatformCookie(
        "SUB=login; SSOLoginState=1",
        cookie_platform="weibo",
        cookie_domains=(".weibo.com", ".weibo.cn"),
    )
    merged = platforms_weibo._weibo_merge_cookies(owned)
    assert isinstance(merged, PlatformCookie)
    assert merged.cookie_domains == (".weibo.com", ".weibo.cn")
    assert merged.cookie_platform == "weibo"
    # 登录值优先：visitor 的 SUB 不得覆盖登录 SUB；其余键并入。
    assert merged.startswith("SUB=login; SSOLoginState=1")
    assert "SUB=visitor" not in merged
    assert "SUBP=v2" in merged and "tid=v3" in merged


def test_f6_plain_str_input_behavior_unchanged(monkeypatch) -> None:
    """F-6：普通 str（无归属）输入零行为变化，也不得被误升为窄域凭证。"""
    monkeypatch.setattr(
        platforms_weibo,
        "_weibo_visitor_cookie",
        lambda: "SUB=visitor; SUBP=v2; tid=v3",
    )
    merged = platforms_weibo._weibo_merge_cookies("SUB=login;")
    assert type(merged) is str
    assert merged == "SUB=login; SUBP=v2; tid=v3"
    # 空输入：仍是空串语义（visitor 单独成串）。
    empty = platforms_weibo._weibo_merge_cookies("")
    assert type(empty) is str
    assert empty == "SUB=visitor; SUBP=v2; tid=v3"
