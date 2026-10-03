from __future__ import annotations

from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.core.contracts.media import (
    ParsedContent,
)
from plugins.bot_unified_runtime.domains.link_parse.parsers import (
    build_content_parser_registry,
)


def _annotation_violations(parsers: dict) -> list[str]:
    """返回注解扫描判据（纯函数：现网与合成注毒共用同一把尺，禁第二副本）。

    口径（与原 `if annotation is not None` 逐字等价，只收紧为「返回违规清单」而非直接
    assert，好让注毒腿喂合成样本）：注册解析函数**若**声明返回注解，必须是 ParsedContent。
    未声明返回注解的 callable（``functools.partial`` 包裹态＝现网默认注册表里的常态）
    一律放行——这是刻意容错，不是漏判，摘掉它会把合法 partial 误判成违约。
    """
    problems: list[str] = []
    for parser_id, parser in parsers.items():
        annotation = getattr(parser, "__annotations__", {}).get("return")
        if annotation is not None and not (
            annotation is ParsedContent or annotation == "ParsedContent"
        ):
            problems.append(f"{parser_id}: 返回注解 {annotation!r} 非 ParsedContent")
    return problems


def test_registered_parser_functions_use_parsed_content_return_contract() -> None:
    built = build_content_parser_registry()
    assert built["parsers"]
    problems = _annotation_violations(built["parsers"])
    assert not problems, "注册解析函数返回注解越出 ParsedContent 合同：" + "；".join(problems)


def test_parser_contract_predicate_catches_synthetic_bad_return_annotation() -> None:
    """注毒自证（W-G-02）：旧文件只断现网态、无任何注入样本——把判据摘成恒放行仍全绿＝空跑。
    本腿用合成 callable 喂三形，证明返回注解扫描真会咬：

    - 违约形（返回 ``dict`` 类对象 / ``"Dict[str, Any]"`` 字符串）必须被点名；
    - 合规形（``ParsedContent`` 类对象 / ``"ParsedContent"`` 字符串）必须放行（防恒红）；
    - 无返回注解形（partial 常态）必须放行（容错口径不许被误当成违约）。
    类对象形与字符串形各测一次，因本仓有 ``from __future__ import annotations``，
    真身里返回注解既可能是字符串（本模块）也可能是类对象（不带 future 的解析件模块）。
    """
    bad_obj = SimpleNamespace(__annotations__={"return": dict})
    bad_str = SimpleNamespace(__annotations__={"return": "Dict[str, Any]"})
    good_obj = SimpleNamespace(__annotations__={"return": ParsedContent})
    good_str = SimpleNamespace(__annotations__={"return": "ParsedContent"})
    unannotated = SimpleNamespace(__annotations__={})

    # 注毒：两枚违规必被各自点名。
    hits = _annotation_violations({"bad_obj": bad_obj, "bad_str": bad_str})
    assert {h.split(":", 1)[0] for h in hits} == {"bad_obj", "bad_str"}, hits

    # 反向：合规 + 无注解不得被误咬（判据不是恒红门）。
    assert (
        _annotation_violations(
            {"good_obj": good_obj, "good_str": good_str, "unannotated": unannotated}
        )
        == []
    )


def test_platform_parse_symbol_is_not_exported_from_runtime_parser_types() -> None:
    import plugins.bot_unified_runtime.domains.link_parse.parsers.types as parser_types

    assert not hasattr(parser_types, "PlatformParse")
