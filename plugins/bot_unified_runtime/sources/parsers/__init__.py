"""Compat shim: 注册表聚合真身迁 domains/link_parse/parsers/__init__.py（v21r2 W1b）。

公开函数经 import * 再导出；基建/平台子模块对象经包属性继续可用
（http_util/wbi/cookies/platforms_* 等，W1a 垫片期顺序纪律双向安全）。
"""

from plugins.bot_unified_runtime.domains.link_parse.parsers import *
from plugins.bot_unified_runtime.domains.link_parse.parsers import (  # noqa: F401
    build_content_parser_registry,
    build_cookie_provider,
    build_source_input,
    context,
    cookies,
    extract_http_urls,
    http_util,
    image_stitch,
    music_candidate_providers,
    music_search_providers,
    platform_login,
    ssrf_guard,
    types,
    wbi,
)
