"""平台 Cookie 键形制与接线覆盖锁（COOKIE-KEYMAP 四缺口）。

四把尺各拦一类"cookie 在盘上却用不上／报不准"：

- ① 凡解析器签名收 `cookie_header`、且它的宿主域已在 cookie 注册表里 ⇒ 必须真被绑定；
  不绑的必须落在**显式豁免表**里并写理由（steam/epic 自读兜底；ds163/buff/huajia/qsmusic
  域虽借在别家平台域内，但那张票不是它的——借票＝把网易云音乐/B站的登录态发去游戏饰品站，
  要修得先给它们注册自己的平台键，本波不借）。
- ② 全仓 `cookie_header("字面量")` 的字面量必须是**注册表平台键**（`netease_music` 是 parser_id，
  provider 按平台键存头，传 parser_id＝恒空串）。
- ③ 注册表"登录主证键"名单里不许出现**不可寻址形制**（含空格/空串）——真实 cookie 名不含空格，
  写进去的判据永远不成立。
- ④ 那份主证键名单必须有**真消费者**：`/bot cookie status` 要能报"某家有凭据但缺哪个登录主证键"。
  此前八个消费点全把第二元素写成 `_key_names` 丢弃＝死数据，骗读代码的人（本波就被骗过一次）。

全离线：只读盘＋tmp_path 造 jar，绝不碰 `ChatBot_Runtime` 生产凭据件，不发任何真实请求。
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.core.credentials.platform_credentials import (
    cookie_status_text,
)
from plugins.bot_unified_runtime.domains.link_parse import parsers as P
from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    PLATFORM_COOKIE_DOMAINS,
    build_platform_cookie_provider,
)

PKG_ROOT = Path(P.__file__).resolve().parents[1].parent.parent.parent.parent

# 自读兜底：这两家不接 provider 的绑定，自己按后缀匹配读同一份 Netscape 件。
SELF_READ_PARSERS = {"steam", "epic"}
# 票不是它们的：域借在别家注册域内，绑定＝把别家登录态发去无关站点。要修得先注册自己的平台键。
NEEDS_OWN_PLATFORM_KEY = {"ds163", "buff", "huajia", "qsmusic"}

_HOST_IN_PATTERN = re.compile(r"([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})")


def _registered_platform_for(host: str) -> list[str]:
    host = host.lower().strip(".")
    hits = []
    for plat, (domains, _req) in PLATFORM_COOKIE_DOMAINS.items():
        for dom in domains:
            suffix = dom.lower().lstrip(".")
            if host == suffix or host.endswith("." + suffix):
                hits.append(plat)
    return sorted(set(hits))


def _cookie_aware_unbound() -> set[str]:
    """收 cookie_header、宿主域已在注册表、却没进绑定表的 parser_id。"""
    out = set()
    for parser_id, _disp, patterns, parse_fn, _prio in P._PLATFORM_RULES:
        if parser_id in P._PARSER_COOKIE_PLATFORM:
            continue
        if "cookie_header" not in inspect.signature(parse_fn).parameters:
            continue
        hosts = set(P._RULE_ALLOWED_HOSTS.get(parser_id, []))
        for pat in patterns:
            found = _HOST_IN_PATTERN.search(pat.replace(r"\.", "."))
            if found:
                hosts.add(found.group(1))
        if any(_registered_platform_for(h) for h in hosts):
            out.add(parser_id)
    return out


def test_cookie_aware_parsers_are_bound_or_declared_exempt() -> None:
    unbound = _cookie_aware_unbound()
    assert unbound <= SELF_READ_PARSERS | NEEDS_OWN_PLATFORM_KEY, (
        "这些解析器收 cookie_header 且宿主域已注册，却没绑定＝凭据导了也不生效；"
        "要么进 _PARSER_COOKIE_PLATFORM，要么写进豁免表并说明理由：" + str(sorted(unbound))
    )


def test_self_read_exemptions_really_read_the_cookie_file() -> None:
    """豁免不是空口的：steam/epic 必须真的自备 Netscape 读取腿（否则豁免＝漏绑）。"""
    for module_name in ("platforms_steam", "platforms_epic"):
        path = PKG_ROOT / f"plugins/bot_unified_runtime/domains/link_parse/parsers/{module_name}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        loaders = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and "cookie" in n.name.lower()
        ]
        assert loaders, f"{module_name} 声明为自读兜底，却找不到任何 cookie 读取函数"


@pytest.mark.parametrize(
    "parser_id,platform_key",
    [("zhihu", "zhihu"), ("bilibili_show", "bilibili"), ("kugou_mixsong", "kugou")],
)
def test_the_three_proven_miswired_parsers_get_their_own_platform_key(parser_id: str, platform_key: str) -> None:
    assert P._PARSER_COOKIE_PLATFORM.get(parser_id) == platform_key


def test_cookie_header_call_literals_are_registered_platform_keys() -> None:
    """`.cookie_header("X")` 的 X 必须是注册表平台键（传 parser_id 会静默恒空）。"""
    offenders = []
    for path in PKG_ROOT.rglob("plugins/bot_unified_runtime/**/*.py"):
        if ".pytest_cache" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "cookie_header"):
                continue
            args = [a for a in node.args if isinstance(a, ast.Constant)]
            args += [
                kw.value
                for kw in node.keywords
                if kw.arg in {"platform", "name"} and isinstance(kw.value, ast.Constant)
            ]
            for arg in args:
                if isinstance(arg.value, str) and arg.value not in PLATFORM_COOKIE_DOMAINS:
                    offenders.append(f"{path.name}:{node.lineno} {arg.value!r}")
    assert offenders == [], f"这些调用点传的不是平台键，拿到的永远是空串：{offenders}"


def test_required_login_key_names_are_addressable() -> None:
    bad = [
        f"{plat}: {name!r}"
        for plat, (_domains, required) in PLATFORM_COOKIE_DOMAINS.items()
        for name in required
        if not name or name != name.strip() or " " in name
    ]
    assert bad == [], f"这些「登录主证键」写法不可能被任何真实 cookie 名命中：{bad}"


def _row(domain: str, name: str, value: str, *, expires: int = 2 ** 31) -> str:
    return "\t".join([domain, "TRUE", "/", "FALSE", str(expires), name, value])


def _provider_with(tmp_path: Path, rows: list[str]):
    jar = tmp_path / "cookies.txt"
    jar.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return build_platform_cookie_provider(str(jar))


def test_provider_reports_missing_required_login_keys(tmp_path: Path) -> None:
    """有凭据但缺登录主证＝必须被点名，而不是默默发一张没登录的票。"""
    provider = _provider_with(
        tmp_path,
        [
            _row(".kugou.com", "kg_mid", "device-only"),
            _row(".bilibili.com", "SESSDATA", "s"),
            _row(".bilibili.com", "bili_jct", "j"),
            _row(".bilibili.com", "DedeUserID", "u"),
        ],
    )
    missing = provider.missing_required
    assert missing.get("kugou"), "酷狗只有设备号没登录票，却不被点名"
    assert set(missing["kugou"]) == {"userid", "token", "dfid"}
    assert "bilibili" not in missing, "B站三件套齐了还报缺＝假红"


def test_status_text_surfaces_missing_required_login_keys(tmp_path: Path) -> None:
    jar = tmp_path / "platform_cookies.txt"
    jar.write_text(_row(".kugou.com", "kg_mid", "device-only") + "\n", encoding="utf-8")
    config = SimpleNamespace(bot_cookies_file=str(jar))
    text = cookie_status_text(config)
    assert "kugou" in text
    assert "缺主证键" in text, "状态页从不报缺哪个登录主证键＝必需键名单仍是死数据"
