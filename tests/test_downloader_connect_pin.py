"""解析钉定回归（INCIDENT-20260930 第五节 · 缺口④：DNS「判后即弃」= rebinding 窗口）。

背景：``downloader.check_download_url`` 用 ``socket.getaddrinfo`` 判完内网就把
解析结果扔掉，真正的连接由后面的 ``socket.create_connection`` **再解一次** DNS——
两次解析之间域名可以翻面（rebinding）：判定那一次是公网、连接那一次指进
127.0.0.1/169.254.169.254，咽喉的全部判据当场形同虚设。本文件的锁＝
「判定与连接共用同一次解析」：

①连接层拿到的地址必须是咽喉判定过的那册 IP（域名不再进 socket）；
②连接时刻再解一次若翻到内网 ⇒ 抛 ``RejectedUrlError`` 且 **一个 socket 都不建**；
③代理在场时绝不钉（红线台账 #71★：bot 全链拴 Clash，钉死等于绕过代理）；
④缺省 ``ProxyHandler`` 仍读环境（``trust_env`` 回落语义不许顺手关掉——temporal 天气依赖它）；
⑤IPv6 字面量与 IPv4-mapped（::ffff:127.0.0.1）折算不破；
⑥W4 补：主钉死了要能回退到**同一次解析**的其余地址（多 A 记录兜底不许被钉掉，
   且回退一律只用判定过的地址册、绝不二次解析）；
⑦W4 补：全树装配面必须与在册清单一字不差（「本体存在」不等于「缺口④收口」）。

全离线纪律：``socket.getaddrinfo`` / ``socket.create_connection`` 全部打桩，
``AbstractHTTPHandler.do_open`` 只记账不建连；域名一律走假解析，字面量 IP
本就不触 DNS ⇒ 零真实网络。
"""

from __future__ import annotations

import http.client
import socket
import urllib.request as urlrequest

import pytest

from plugins.bot_unified_runtime.domains.files.sources import downloader as dl
from plugins.bot_unified_runtime.domains.files.sources.downloader import (
    RejectedUrlError,
    build_pinning_handlers,
    check_download_url,
    check_download_url_resolved,
)

_PUBLIC_V4 = "93.184.216.34"
_PUBLIC_V6 = "2606:2800:220:1::2"


def _patch_getaddrinfo(monkeypatch, answers: list[list[str]]) -> list[str]:
    """按调用序吐出解析结果；答案表耗尽即抛（测试不许悄悄多解一次）。"""
    seen: list[str] = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        seen.append(str(host))
        if not answers:
            raise AssertionError(f"意外的额外 DNS 解析：{host}")
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, int(port) + index),
            )
            for index, ip in enumerate(answers.pop(0))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return seen


def _patch_create_connection(monkeypatch) -> list[tuple[str, int]]:
    """记账「连接层实际拿去连的地址」；返回哨兵对象，绝不建真 socket。"""
    used: list[tuple[str, int]] = []
    sentinel = object()

    def fake_create_connection(address, *args, **kwargs):
        used.append((str(address[0]), int(address[1])))
        return sentinel

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return used


def _capture_do_open(monkeypatch) -> dict[str, object]:
    """把 ``do_open`` 换成记账件：只留「交给连接层的 http_class + 连接参数」，不建连。"""
    captured: dict[str, object] = {}

    def fake_do_open(self, http_class, req, **kwargs):  # 替身签名（不注解，账在记账键里）
        captured["http_class"] = http_class
        captured["conn_kwargs"] = kwargs
        return "stubbed-response"

    monkeypatch.setattr(urlrequest.AbstractHTTPHandler, "do_open", fake_do_open)
    return captured


def _patch_flaky_create_connection(
    monkeypatch: pytest.MonkeyPatch, dead: frozenset[str]
) -> list[tuple[str, int]]:
    """连接记账件：``dead`` 里的地址一律按「端口拒绝」失败，其余返回哨兵不建真 socket。

    用于验「主钉 + 同一次解析的其余地址可回退」（W4）：只钉一枚那版会把
    ``socket.create_connection`` 自带的多 A 记录轮询兜底一起钉掉。
    """
    used: list[tuple[str, int]] = []
    sentinel = object()

    def fake_create_connection(address, *args, **kwargs):
        ip, port = str(address[0]), int(address[1])
        used.append((ip, port))
        if ip in dead:
            raise ConnectionRefusedError("simulated dead IP")
        return sentinel

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return used


def _pin_handler_pair() -> tuple[urlrequest.HTTPHandler, urlrequest.HTTPSHandler]:
    handlers = build_pinning_handlers()
    http_handlers = [h for h in handlers if isinstance(h, urlrequest.HTTPHandler)]
    https_handlers = [h for h in handlers if isinstance(h, urlrequest.HTTPSHandler)]
    assert len(http_handlers) == 1 and len(https_handlers) == 1
    return http_handlers[0], https_handlers[0]


# --------------------------------------------------------------------------- #
# ①判定与连接同一次解析：连接层只认判定过的 IP
# --------------------------------------------------------------------------- #
def test_connect_uses_the_validated_ip_not_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主锁：域名解析到公网 ⇒ 连接层拿到的地址必须是那枚 IP（治判后即弃）。

    RED（修复前）：downloader 里没有钉定件，``build_pinning_handlers`` 不存在。
    """
    resolved = _patch_getaddrinfo(monkeypatch, [[_PUBLIC_V4]])
    sockets = _patch_create_connection(monkeypatch)
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    handler.http_open(urlrequest.Request("http://cdn.example.test/cover.png"))

    assert resolved == ["cdn.example.test"], "连接时刻只做这一次解析"
    connection_class = captured["http_class"]
    assert connection_class is not http.client.HTTPConnection, "必须换成钉定连接类"
    connection = connection_class("cdn.example.test", timeout=2)
    connection._create_connection(("cdn.example.test", 8080), 2.0, None)
    # 域名不许出现在 socket 地址里：否则第二次 DNS 又开了 rebinding 窗口。
    assert sockets == [(_PUBLIC_V4, 8080)]


def test_literal_public_ip_needs_no_extra_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """字面量公网 IP：咽喉离线可判 ⇒ 钉定也不许多解一次 DNS（热路径零新增）。"""
    resolved = _patch_getaddrinfo(monkeypatch, [])
    sockets = _patch_create_connection(monkeypatch)
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    handler.http_open(urlrequest.Request(f"http://{_PUBLIC_V4}/x.png"))

    assert resolved == []
    connection = captured["http_class"](_PUBLIC_V4, timeout=2)
    connection._create_connection((_PUBLIC_V4, 80), 2.0, None)
    assert sockets == [(_PUBLIC_V4, 80)]


def test_https_leg_pins_the_same_way(monkeypatch: pytest.MonkeyPatch) -> None:
    """https 腿同样钉：且 ssl context 必须原样透传（不许顺手关掉证书校验）。"""
    _patch_getaddrinfo(monkeypatch, [[_PUBLIC_V4]])
    sockets = _patch_create_connection(monkeypatch)
    captured = _capture_do_open(monkeypatch)
    _http, https_handler = _pin_handler_pair()

    https_handler.https_open(urlrequest.Request("https://cdn.example.test/api"))

    connection = captured["http_class"]("cdn.example.test", timeout=2)
    connection._create_connection(("cdn.example.test", 443), 2.0, None)
    assert sockets == [(_PUBLIC_V4, 443)]
    import ssl

    assert isinstance(captured["conn_kwargs"].get("context"), ssl.SSLContext), (
        "钉定只换 socket 地址，TLS 上下文与证书校验必须原样留着"
    )


# --------------------------------------------------------------------------- #
# ②rebinding 翻面：连接时刻解到内网 ⇒ 拒绝且零 socket
# --------------------------------------------------------------------------- #
def test_dns_flip_to_internal_refuses_before_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """入口判公网、连接判内网（rebinding 本体）⇒ 抛 RejectedUrlError，一个连接都不建。"""
    _patch_getaddrinfo(monkeypatch, [["127.0.0.1"]])
    sockets = _patch_create_connection(monkeypatch)
    _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    with pytest.raises(RejectedUrlError):
        handler.http_open(urlrequest.Request("http://flips.example.test/x"))

    assert sockets == []


@pytest.mark.parametrize(
    "landing",
    [
        "169.254.169.254",
        "10.1.2.3",
        "192.168.1.1",
        "::ffff:127.0.0.1",  # IPv4-mapped 折算：按 v4 判回环
        "fe80::1",
    ],
)
def test_every_blocked_shape_refuses_at_connect(
    monkeypatch: pytest.MonkeyPatch, landing: str
) -> None:
    """私网/链路本地/IPv4-mapped 折算在连接时刻同样拦得住（判据与入口同源）。"""
    _patch_getaddrinfo(monkeypatch, [[landing]])
    sockets = _patch_create_connection(monkeypatch)
    _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    with pytest.raises(RejectedUrlError):
        handler.http_open(urlrequest.Request("http://any.example.test/x"))
    assert sockets == []


# --------------------------------------------------------------------------- #
# ③④代理红线（台账 #71★）
# --------------------------------------------------------------------------- #
def test_proxied_request_is_never_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """代理在场（本机全链拴 Clash 127.0.0.1:7890）⇒ 不钉、不自己解析，交回代理连。

    钉死目标 IP 等于绕过代理——那是 #71 波刚修好的通路，绝不能再破一次。
    """
    resolved = _patch_getaddrinfo(monkeypatch, [])
    _patch_create_connection(monkeypatch)
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    request = urlrequest.Request("http://example.test/x.png")
    request.set_proxy("127.0.0.1:7890", "http")  # 与 ProxyHandler 生效后同形
    handler.http_open(request)

    assert captured["http_class"] is http.client.HTTPConnection, "代理请求必须走原路"
    assert resolved == [], "代理在场时不许自行解析目标域"


def test_proxied_https_tunnel_is_never_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """https over CONNECT 隧道：``req.host`` 是代理、``_tunnel_host`` 是目标 ⇒ 不钉。"""
    _patch_getaddrinfo(monkeypatch, [])
    captured = _capture_do_open(monkeypatch)
    _http, https_handler = _pin_handler_pair()

    request = urlrequest.Request("https://example.test/api")
    request.set_proxy("127.0.0.1:7890", "http")
    https_handler.https_open(request)

    assert captured["http_class"] is http.client.HTTPSConnection


def test_pinned_opener_keeps_default_proxy_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """红线：钉定件不得附带「强制直连」——缺省 ProxyHandler 照旧读环境（trust_env）。"""
    _patch_getaddrinfo(monkeypatch, [])
    _patch_create_connection(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    opener = urlrequest.build_opener(*build_pinning_handlers())
    proxy_handlers = [
        h for h in opener.handlers if isinstance(h, urlrequest.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1, "钉定件不许装第二个 ProxyHandler，也不许摘掉缺省件"
    assert proxy_handlers[0].proxies == urlrequest.getproxies()
    # 缺省 HTTP/HTTPS 处理器被钉定子类顶替（build_opener 按 isinstance 去重），
    # 不许出现两套 http_open 链。
    assert sum(isinstance(h, urlrequest.HTTPHandler) for h in opener.handlers) == 1
    assert sum(isinstance(h, urlrequest.HTTPSHandler) for h in opener.handlers) == 1


# --------------------------------------------------------------------------- #
# ⑤IPv6 / 折算 / 契约不变
# --------------------------------------------------------------------------- #
def test_ipv6_literal_is_allowed_and_pinned() -> None:
    """IPv6 字面量公网：判定放行且交回同一枚（含方括号 URL 的 hostname 剥离）。"""
    assert check_download_url_resolved(f"http://[{_PUBLIC_V6}]/x") == frozenset({_PUBLIC_V6})


def test_ipv6_loopback_literal_is_rejected() -> None:
    with pytest.raises(RejectedUrlError):
        check_download_url_resolved("http://[::1]/x")


def test_ipv4_mapped_literal_is_rejected_by_folding() -> None:
    """``::ffff:127.0.0.1`` 折算成 v4 再判（旧行为不许破）。"""
    with pytest.raises(RejectedUrlError):
        check_download_url_resolved("http://[::ffff:127.0.0.1]/x")


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1:3001/status",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8080/x",
        "file:///C:/Windows/win.ini",
        "",
    ],
)
def test_rejection_verdicts_and_messages_are_unchanged(bad_url: str) -> None:
    """契约锁：咽喉本体（check_download_url）裁决与文案与重构前逐字一致。"""
    with pytest.raises(RejectedUrlError) as throat:
        check_download_url(bad_url)
    with pytest.raises(RejectedUrlError) as resolver:
        check_download_url_resolved(bad_url)
    assert str(throat.value) == str(resolver.value)


def test_resolver_returns_addresses_for_allowed_url(monkeypatch) -> None:
    """放行时交回全部解析结果（多 A 记录不许只给第一个——钉定要按同一册子选）。"""
    _patch_getaddrinfo(monkeypatch, [["93.184.216.34", "93.184.216.35"]])
    assert check_download_url_resolved("http://multi.example.test/x") == frozenset(
        {"93.184.216.34", "93.184.216.35"}
    )


# --------------------------------------------------------------------------- #
# ⑥多地址兜底：主钉死了换同一次解析的下一枚，不许二次解析、不许静默成功
# --------------------------------------------------------------------------- #
def test_dead_primary_ip_falls_back_within_the_same_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CDN 有一枚死 IP：旧版只钉排序后第一枚 ⇒ 硬失败；现在按同册顺序回退。

    RED（修复前）：``_pick_pinned_address`` 只交一枚，第二枚根本没进连接序，
    ``used`` 只有一条且抛 ``ConnectionRefusedError``。
    回退的合法性边界：候选册＝**同一次**已判定的解析结果（``resolved`` 只被点一次），
    换地址不换「判定」，所以 rebinding 窗口仍是零。
    """
    resolved = _patch_getaddrinfo(
        monkeypatch, [["93.184.216.34", "93.184.216.35"]]
    )
    used = _patch_flaky_create_connection(monkeypatch, frozenset({"93.184.216.34"}))
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    handler.http_open(urlrequest.Request("http://cdn.example.test/cover.png"))

    connection = captured["http_class"]("cdn.example.test", timeout=2)
    sock = connection._create_connection(("cdn.example.test", 80), 2.0, None)
    assert sock is not None, "回退到下一枚候选后必须真的连上"
    assert used == [("93.184.216.34", 80), ("93.184.216.35", 80)]
    assert resolved == ["cdn.example.test"], "回退只许吃已判定的册子，不许再解一次 DNS"


def test_ipv4_keeps_the_primary_slot_and_ipv6_stays_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IPv4 优先保留（v6 无路由是常态故障源），但 v6 仍是同册里的合法回退候选。"""
    _patch_getaddrinfo(monkeypatch, [[_PUBLIC_V6, _PUBLIC_V4]])
    used = _patch_flaky_create_connection(monkeypatch, frozenset({_PUBLIC_V4}))
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    handler.http_open(urlrequest.Request("http://dual.example.test/x"))

    connection = captured["http_class"]("dual.example.test", timeout=2)
    connection._create_connection(("dual.example.test", 443), 2.0, None)
    assert used == [(_PUBLIC_V4, 443), (_PUBLIC_V6, 443)]


def test_all_candidates_dead_propagates_the_real_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全册皆败：抛最后一次的真实异常（不伪造原因、不静默返回 None）。"""
    _patch_getaddrinfo(monkeypatch, [["93.184.216.34", "93.184.216.35"]])
    used = _patch_flaky_create_connection(
        monkeypatch, frozenset({"93.184.216.34", "93.184.216.35"})
    )
    captured = _capture_do_open(monkeypatch)
    handler, _https = _pin_handler_pair()

    handler.http_open(urlrequest.Request("http://cdn.example.test/x"))

    connection = captured["http_class"]("cdn.example.test", timeout=2)
    with pytest.raises(ConnectionRefusedError):
        connection._create_connection(("cdn.example.test", 80), 2.0, None)
    assert len(used) == 2, "两枚候选各试一次就收，不许无限打转"


# --------------------------------------------------------------------------- #
# ⑦装配面在册锁：「装了没」是纸面口径的唯一凭据
# --------------------------------------------------------------------------- #
#: 在册清单＝``downloader.build_pinning_handlers`` 装配面段落与
#: ``patches/W4-SSRF-PIN-ASSEMBLY-20260930.md`` 三处同批（改一处必改其余）。
_PINNING_ASSEMBLY_ROSTER = frozenset({"domains/food/capabilities/eat.py"})


def test_pinning_assembly_roster_is_the_recorded_one() -> None:
    """钉定件调用点必须与在册清单一字不差（多装少装都红）。

    为什么必须有这把尺（W4）：钉定「本体」早已存在，但全树只有 ``eat`` 一条腿装上，
    解析链咽喉 ``http_util._build_opener`` 与 ``notes``/``vision_describe``/
    ``media_archive``/meme 监听器一律未装 ⇒ 生产主面的 rebinding 窗口零改善，
    而台账很容易读成「缺口④已收口」。本锁把「谁在装」变成机器可判的事实：
    - 有人**新装**一条腿却不改清单/口径 ⇒ 红（逼着复核该腿的 ``except`` 面与代理态，
      见 ``RejectedUrlError`` 与 ``build_pinning_handlers`` 的装配注意 a/b）；
    - 在册腿被拆掉而清单不动 ⇒ 同样红（假账）。
    现算是本锁的立场：不缓存、不读文档正文，只按 AST 认调用点。
    """
    import ast
    from pathlib import Path

    pkg_root = Path(dl.__file__).resolve().parents[3]
    found: set[str] = set()
    for source in sorted(pkg_root.rglob("*.py")):
        try:
            text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError):  # pragma: no cover - 非 py3 源/坏编码
            continue
        if "build_pinning_handlers(" not in text:
            continue
        tree = ast.parse(text)
        called = any(
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "build_pinning_handlers"
            for node in ast.walk(tree)
        )
        if called:
            found.add(source.relative_to(pkg_root).as_posix())
    assert found == set(_PINNING_ASSEMBLY_ROSTER), (
        "钉定件装配面与在册清单不符 ⇒ 要么有腿未登记，要么账面虚高。"
        f"实算={sorted(found)} 在册={sorted(_PINNING_ASSEMBLY_ROSTER)}"
    )


def test_single_throat_body_stays_single_source() -> None:
    """结构锁：钉定件复用同一个判据本体，downloader 内 ``check_download_url``
    调用点仍唯一（不造第二套 SSRF 判据，见 test_ssrf_throat_coverage 同族锁）。"""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(dl.__file__).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        == "check_download_url"
    ]
    assert len(calls) == 1
    resolver_defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "check_download_url_resolved"
    ]
    assert len(resolver_defs) == 1, "判据本体只有一份（check_download_url 是它的薄封装）"
