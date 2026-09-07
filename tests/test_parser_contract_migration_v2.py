from __future__ import annotations

from plugins.bot_unified_runtime.contracts.media import (
    ParsedContent,
)
from plugins.bot_unified_runtime.sources.parsers import build_content_parser_registry


def test_registered_parser_functions_use_parsed_content_return_contract() -> None:
    built = build_content_parser_registry()
    assert built["parsers"]
    for parser_id, parser in built["parsers"].items():
        annotation = getattr(parser, "__annotations__", {}).get("return")
        if annotation is not None:
            assert annotation is ParsedContent or annotation == "ParsedContent", parser_id


def test_platform_parse_symbol_is_not_exported_from_runtime_parser_types() -> None:
    import plugins.bot_unified_runtime.sources.parsers.types as parser_types

    assert not hasattr(parser_types, "PlatformParse")
