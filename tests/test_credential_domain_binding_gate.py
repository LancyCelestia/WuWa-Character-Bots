"""WP1 ④：凭证咽喉再生门（AST + 文本双扫，显式豁免表 + 负样本）。

禁止在 ``domains/link_parse`` / ``domains/music`` / ``domains/media`` 里出现
「带 Cookie/凭证的出站请求而不经统一咽喉」。统一咽喉 =
``domains/link_parse/parsers/http_util`` 的 ``http_get*/http_post*``（内部已对
cookie 做目标域 + 跨 host 重定向剥离）或显式调用 ``scrub_credentials_for_target``
/ ``credentials_allowed_for_target``。

判据形态照 tests/test_ssrf_throat_coverage.py（AST 计数 + 负样本注毒）。
本门自身不联网，纯静态读盘。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 统一咽喉（内部对 cookie 施目标域校验 + 跨 host 剥凭证）——经此出站即合规。
CHOKEPOINT_FUNCS = frozenset(
    {"http_get", "http_get_text", "http_get_json", "http_post_json", "http_post_form"}
)
# 咽喉显式助手：被调用即视为该作用域把凭证收进了咽喉。
SCRUB_HELPERS = frozenset(
    {"scrub_credentials_for_target", "credentials_allowed_for_target"}
)
# 可携带凭证的出站调用形态。
OUTBOUND_NAMES = frozenset(
    {
        "get",
        "post",
        "request",
        "stream",
        "urlopen",
        "build_opener",
        "open",
        "Request",
        "Client",
        "AsyncClient",
    }
)
# 凭证头/参数名（大小写不敏感，子串匹配）。
CRED_TOKENS = (
    "cookie",
    "authorization",
    "proxy-authorization",
    "user_token",
    "token",
    "x-auth",
    "api-key",
    "apikey",
    "auth",
)

# 显式豁免表：(相对 domains/ 的文件路径) → 理由。登记制，不写理由不得豁免。
EXEMPTIONS: dict[str, str] = {
    # 咽喉本体：它自己就是「校验后写 Cookie 头」的地方。
    "link_parse/parsers/http_util.py": "统一咽喉实现点，凭证剥离逻辑本体",
    # 常量 API host（非用户可控候选 URL）→ 无跨域凭证外泄面。
    "link_parse/parsers/platforms_kurobbs.py": "token 只发模块常量 _KURO_DETAIL_API host，候选 URL 不参与",
    "link_parse/parsers/platforms_weibo.py": "visitor cookie jar 只发模块常量 _VISITOR_GEN_API host",
    # ASR 服务密钥（Authorization: Bearer）只发配置面 base_url（open.bigmodel.cn
    # 等，非任意用户 URL、非平台登录 Cookie），不在 WP1 平台 Cookie 外泄咽喉覆盖面内。
    "media/ingest/transcribe.py": "ASR Bearer 密钥发配置 provider base_url，非用户可控 URL、非平台 Cookie",
}

SCANNED_DOMAINS = ("link_parse", "music", "media")


def _cred_in_keys(keys: list[str]) -> bool:
    return any(any(tok in str(k).lower() for tok in CRED_TOKENS) for k in keys)


def _dict_literal_keys(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Dict):
        return [
            str(k.value)
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
    return []


def _call_carries_credential(call: ast.Call) -> bool:
    # keyword 形如 cookie= / authorization=
    for kw in call.keywords:
        if kw.arg and any(tok in kw.arg.lower() for tok in CRED_TOKENS):
            return True
        # headers={"Cookie": ...} / headers={**creds}
        if kw.arg == "headers" and _cred_in_keys(_dict_literal_keys(kw.value)):
            return True
        # cookie 值本身是变量名（含 cookie/token 字样）也计入
        if isinstance(kw.value, ast.Name) and any(
            tok in kw.value.id.lower() for tok in ("cookie", "token", "auth")
        ):
            return True
    for arg in call.args:
        if _cred_in_keys(_dict_literal_keys(arg)):
            return True
    return False


def _call_func_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _functions_with_scrub(tree: ast.AST) -> set[int]:
    """返回「函数体内调用了咽喉助手」的 FunctionDef 的 id() 集合（含模块级 0）。"""
    marked: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and _call_func_name(sub) in SCRUB_HELPERS
                ):
                    marked.add(id(node))
                    break
    return marked


def _enclosing_functions(node: ast.AST) -> dict[int, ast.AST]:
    parent: dict[int, ast.AST] = {}
    for cur in ast.walk(node):
        for child in ast.iter_child_nodes(cur):
            parent[id(child)] = cur
    return parent


def _nearest_function(obj_id: int, parent: dict[int, ast.AST]) -> int | None:
    cur = obj_id
    while cur in parent:
        cur_node = parent[cur]
        if isinstance(cur_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return id(cur_node)
        cur = id(cur_node)
    return None


def scan_source(source: str, filename: str) -> list[str]:
    """扫描一段源码，返回违规描述列表（空=合规）。"""
    tree = ast.parse(source)
    parent = _enclosing_functions(tree)
    scrubbed_funcs = _functions_with_scrub(tree)
    violations: list[str] = []
    module = Path(filename)
    rel = module.name
    # 归一到 domains/ 下的相对路径形如 link_parse/parsers/xxx.py
    parts = module.parts
    if "domains" in parts:
        rel = "/".join(parts[parts.index("domains") + 1 :])
    if rel in EXEMPTIONS:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_func_name(node)
        if name in CHOKEPOINT_FUNCS:
            continue  # 经咽喉，合规
        if name not in OUTBOUND_NAMES:
            continue
        if not _call_carries_credential(node):
            continue
        fn = _nearest_function(id(node), parent)
        if fn is not None and fn in scrubbed_funcs:
            continue  # 该函数已把凭证收进咽喉助手
        if fn is None and 0 in scrubbed_funcs:
            continue
        violations.append(f"{rel}:{node.lineno}: 凭证出站未经统一咽喉（{name}）")
    return violations


def _iter_domain_files() -> list[Path]:
    base = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
    )
    files: list[Path] = []
    for dom in SCANNED_DOMAINS:
        files.extend(p for p in (base / dom).rglob("*.py"))
    return files


def test_no_unthroated_credential_outbound_across_domains() -> None:
    """正门：三个域内不得有绕过咽喉的凭证出站；豁免表逐条登记理由。"""
    offenders: list[str] = []
    for path in _iter_domain_files():
        source = path.read_text(encoding="utf-8")
        offenders.extend(scan_source(source, str(path)))
    assert not offenders, "凭证未经统一咽喉出站：\n" + "\n".join(offenders)


def test_exemption_table_entries_are_real_and_reasoned() -> None:
    """豁免登记制：每条必须有文件真身 + 非空理由，禁止空转豁免。"""
    base = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
    )
    for rel, reason in EXEMPTIONS.items():
        assert (base / rel).exists(), f"豁免指向不存在文件：{rel}"
        assert reason.strip(), f"豁免缺理由：{rel}"


def test_negative_sample_violation_is_detected() -> None:
    """门有牙：注毒一条绕过咽喉的凭证出站，必须被扫出（否则门形同虚设）。"""
    bad_music = '''
import httpx

def download(url, cookie_header):
    return httpx.get(url, headers={"user-agent": "x", "cookie": cookie_header},
                     follow_redirects=True)
'''
    violations = scan_source(bad_music, "domains/music/capabilities/evil_bad.py")
    assert violations, "注毒的绕过咽喉出站必须报红"

    bad_urllib = '''
from urllib import request as urlrequest

def fetch(url, cookie):
    req = urlrequest.Request(url, headers={"Cookie": cookie})
    return urlrequest.build_opener().open(req)
'''
    assert scan_source(bad_urllib, "domains/media/ingest/evil_bad.py")

    # 合规样本：走了咽喉 http_get（内部剥凭证）→ 不报。
    good = '''
from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import http_get

def parse(url, cookie_header):
    return http_get(url, cookie=cookie_header)
'''
    assert not scan_source(good, "domains/link_parse/parsers/evil_good.py")


def test_chokepoint_functions_are_actually_scrubbing() -> None:
    """结构锁：咽喉本体确实在构造请求时过滤 cookie（防止咽喉被掏空后门化）。"""
    http_util = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "link_parse"
        / "parsers"
        / "http_util.py"
    )
    src = http_util.read_text(encoding="utf-8")
    assert "def _apply_cookie_guard" in src
    assert "def scrub_credentials_for_target" in src
    assert "class _CredentialScrubbingRedirectHandler" in src
    # 三处请求构造（GET / POST json / POST form）都必须经 _apply_cookie_guard。
    assert src.count("_apply_cookie_guard(") >= 3, "每个出站咽喉点都要过滤 cookie"
    # 跨 host 剥凭证头必须显式删除三类头。
    for head in ("cookie", "authorization", "proxy-authorization"):
        assert head in src


def test_music_audio_download_uses_scrub_and_ssrf_guard() -> None:
    """音乐 httpx 入口必须既过 SSRF 又把凭证收进咽喉（等价保护，②）。"""
    music = (
        Path(__file__).resolve().parent.parent
        / "plugins"
        / "bot_unified_runtime"
        / "domains"
        / "music"
        / "capabilities"
        / "music.py"
    )
    src = music.read_text(encoding="utf-8")
    assert "scrub_credentials_for_target" in src
    assert "credentials_allowed_for_target" in src
    assert "check_download_url" in src
