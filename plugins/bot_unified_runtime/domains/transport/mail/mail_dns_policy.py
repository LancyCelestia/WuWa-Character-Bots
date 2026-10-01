"""把邮件主机限定成 IPv4。

为什么要有这张护栏：``imap.qq.com`` / ``smtp.qq.com`` 带 AAAA
（``2409:8c54:871:2000::16`` / ``::20``），而 ``getaddrinfo`` 把 **IPv6 排在前面**：

    #1 IPv6  #2 IPv6  #3 IPv4  #4 IPv4

这条 v6 通路是**抖动的**，不是永久断的（两次实测都取自同一台机器、同一个端口）：

* 2026-09-28 晚与 09-29 01:1x：裸连 ``imap.qq.com:993`` 要 **42 266ms** 才连上（先等 v6
  超时再回退 v4），asyncio 路径直接 ``TimeoutError``（>60s）。
* 2026-09-29 01:31：连测 6 轮，v6 **6/6 全通**，119–144ms；同轮 v4 106–130ms。

护栏下同一发连接是 **37–45ms**（09-29 实测）。也就是说它省的不是 DNS 时间
（同一次测量里 ``getaddrinfo`` 本身只要 11ms，缓存后 0ms），而是"v6 这一发正好不通时"
要付的那 12–60 秒 —— 库内超时 10s 时它会直接表现成 ``worker error: TimeoutError``，
外层指数退避再把整件事放大成"邮箱不可达"。

修在这里而不是把解析出的 IP 直接传给 ``aioimaplib.IMAP4_SSL``：后者会把 SNI/证书校验的
主机名换成 IP，换回 ``CERTIFICATE_VERIFY_FAILED``。本模块只改"解析优先族"，
``host`` 仍是域名 ⇒ SNI 与证书链原样不动。

⚠ 只拦 ``family`` 未指定（``0``，即"双栈自选"）的查询 —— 那正是 ``aioimaplib`` /
``aiosmtplib`` 经 ``loop.create_connection`` 发解析时用的形态（asyncio 实发 6 个位置参数：
``host, port, family, type, proto, flags``）。显式指定族的调用原样放行。
只有落在 ``_GUARDED`` 里的主机（或其后缀）才被改写，其余解析一律透传 —— 这条作用面由
``tests/test_mail_dns_policy.py`` 里"非邮件主机必须逐字节透传"那一条守着。
"""

from __future__ import annotations

import socket
from collections.abc import Iterable
from typing import Any

# 被限定成 IPv4 的邮件主机（小写、去尾点）。按后缀匹配，所以填 "qq.com" 会连
# imap.qq.com / smtp.qq.com 一起管住；填全称就只影响那一个主机。
_GUARDED: set[str] = set()
_INSTALLED = False


def _normalize(host: Any) -> str:
    return str(host or "").strip().rstrip(".").lower()


def _is_guarded(host: Any) -> bool:
    name = _normalize(host)
    if not name:
        return False
    return any(name == guarded or name.endswith("." + guarded) for guarded in _GUARDED)


def _unwrap(func: Any) -> Any:
    """往下剥掉我们自己套过的壳，拿到当时真正在用的解析器。

    模块被二次 import（``importlib.reload``、热重载）时 ``socket.getaddrinfo`` 已经是
    上一版的 ``_wrapped``；直接把它当"原始函数"存下来就会套成洋葱，还原时漏一层。
    """
    seen: set[int] = set()
    current = func
    while getattr(current, "_mail_dns_guard", False) and id(current) not in seen:
        seen.add(id(current))
        current = current._guard_underlying
    return current


# 我们下面那一格是谁。**必须在装的那一刻抓**（见 guard_mail_hosts），不能在 import 期冻结：
# import 期冻结的话，若某个测试文件（或 conftest）在我们之前已经给 socket.getaddrinfo 挂过
# 替身，我们装的时候下面那格是它的壳，而还原时写回的却是 import 期那个真函数 ——
# 等于把别人的 session 级替身永久吃掉（S33 在副本里实测到这一条：后续文件 mock_calls=0）。
# 初值只作兜底（万一有人不经 guard_mail_hosts 直接调 _wrapped）。
_PREVIOUS = _unwrap(socket.getaddrinfo)
# 兼容旧名字：测试与历史文档里用的都是 ``_ORIGINAL``，指向同一个对象。
_ORIGINAL = _PREVIOUS


def _family_of(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int | None:
    """取调用方给的 family；取不出来就返回 None（= 不干涉，原样透传）。

    先判 host 再判 family：``_wrapped`` 只有在主机被登记时才碰这段，
    免得一个畸形 family 参数把异常类型从 ``gaierror`` 漂成 ``ValueError``，
    而那影响的是**全进程**的解析。
    """
    raw = kwargs["family"] if "family" in kwargs else (args[0] if args else 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _wrapped(host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
    if _is_guarded(host):
        family = _family_of(args, kwargs)
        if family == 0:
            tail = list(args[1:])
            forward = dict(kwargs)
            # family 已经以位置参数（第 3 个）传下去了，必须从 kwargs 里摘掉，
            # 否则调用方用关键字写 family 时会撞 "multiple values for argument"。
            forward.pop("family", None)
            try:
                v4 = _PREVIOUS(host, port, socket.AF_INET, *tail, **forward)
            except OSError:
                v4 = []
            # IPv4 一条都没解析出来时退回原查询，不能把"这台只有 AAAA"的主机判成不存在。
            if v4:
                return v4
    return _PREVIOUS(host, port, *args, **kwargs)


_wrapped._mail_dns_guard = True  # type: ignore[attr-defined]


def guard_mail_hosts(hosts: Iterable[str]) -> None:
    """登记邮件主机并（首次）装上解析护栏。重复调用不叠加包装。"""
    global _INSTALLED, _PREVIOUS, _ORIGINAL
    cleaned = {_normalize(h) for h in hosts if _normalize(h)}
    if not cleaned:
        return
    if _INSTALLED and cleaned.issubset(_GUARDED):
        return
    _GUARDED.update(cleaned)
    if not _INSTALLED:
        # **装的那一刻**才抓"我下面是谁"。import 期冻结会留下两份真相：
        # 若某个测试文件/conftest 在我们之前已把 socket.getaddrinfo 换成它的替身，
        # 装的时候下面那格是它的壳，而还原时写回 import 期那个真函数 ——
        # 等于把别人的 session 级替身永久吃掉（S33 副本实测：后续文件 mock_calls=0）。
        _PREVIOUS = _unwrap(socket.getaddrinfo)
        _ORIGINAL = _PREVIOUS  # 兼容旧名字，指向同一个对象
        _wrapped._guard_underlying = _PREVIOUS  # type: ignore[attr-defined]
        socket.getaddrinfo = _wrapped  # type: ignore[method-assign]
        _INSTALLED = True


def mail_hosts_from_bot_infos(bot_infos: Iterable[Any]) -> set[str]:
    """从 mail 适配器的 ``mail_bots`` 里取出 imap/smtp 两个主机名。

    用 ``getattr`` 兜底：这里的 bot_info 来自上游 pydantic 模型（``imap.host`` /
    ``smtp.host``），但测试与降级路径可能喂进缺字段的替身，缺就跳过而不是抛。
    """
    hosts: set[str] = set()
    for info in bot_infos:
        for leg in ("imap", "smtp"):
            leg_obj = getattr(info, leg, None)
            host = _normalize(getattr(leg_obj, "host", ""))
            if host:
                hosts.add(host)
    return hosts


def is_installed() -> bool:
    """护栏是不是此刻的生效层。

    认的是"socket 上挂的到底是不是我这一个壳"，不认安装标志位：别的库（dnspython 一类）
    把 patch 压在我上面时，我的壳已经不在通路上，标志位却还是 True —— 那正是最需要说出来的事。
    """
    return socket.getaddrinfo is _wrapped


def reset_for_tests() -> None:
    """还原全局状态，只给测试收尾用。生产路径不调。"""
    global _INSTALLED
    _GUARDED.clear()
    if _INSTALLED:
        # 只有我们还压在最上面时才接管这一格；别人 patch 在上面时把它的壳一起吃掉，
        # 破坏的是别人的功能，不是我们的。
        if socket.getaddrinfo is _wrapped:
            socket.getaddrinfo = _PREVIOUS  # type: ignore[method-assign]
        _INSTALLED = False
