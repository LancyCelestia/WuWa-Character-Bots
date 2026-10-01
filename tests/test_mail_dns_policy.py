"""``mail_dns_policy`` 的门禁测试：护栏必须只改邮件主机，其余一律透传。

不发真 DNS —— ``_ORIGINAL`` 被换成假解析器，判据全部离线可复算。
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.transport.mail import mail_dns_policy as policy

_FAKE_RECORDS: dict[str, list[tuple[int, str]]] = {
    "imap.qq.com": [(socket.AF_INET6, "2409:8c54:871:2000::16"), (socket.AF_INET, "120.232.69.34")],
    "smtp.qq.com": [(socket.AF_INET6, "2409:8c54:871:2000::20"), (socket.AF_INET, "120.232.69.34")],
    "v6only.example.com": [(socket.AF_INET6, "2001:db8::1")],
    "www.baidu.com": [(socket.AF_INET6, "2400:3200::1"), (socket.AF_INET, "223.109.82.16")],
}


def _fake_getaddrinfo(
    host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0
) -> list[tuple[int, int, int, str, tuple[Any, ...]]]:
    records = _FAKE_RECORDS.get(str(host).lower(), [])
    out = []
    for rec_family, address in records:
        if family not in (0, rec_family):
            continue
        out.append((rec_family, socket.SOCK_STREAM, 0, "", (address, int(port or 0))))
    if not out:
        raise socket.gaierror(8, f"no records for {host}")
    # 真 getaddrinfo 会把系统返回顺序原样给出；这里保留"v6 在前"的形状，
    # 因为要复现的正是在她机器上观测到的顺序。
    return out


@pytest.fixture(autouse=True)
def _hermetic_resolver() -> Iterator[None]:
    """把假解析器**装进 socket 那一格**，而不是改模块私有变量。

    护栏现在是在 `guard_mail_hosts` 那一刻才抓"我下面是谁"，所以替身必须提前挂在
    `socket.getaddrinfo` 上 —— 这样 `_PREVIOUS` 抓到的就是假解析器，判据全程离线。
    收尾也**不再无条件写回**：只有当那一格还是我们自己的东西时才还原，
    否则把外层（conftest 或前序文件）的替身**交还**，别吃掉它。
    """
    policy.reset_for_tests()
    original_real = socket.getaddrinfo
    socket.getaddrinfo = _fake_getaddrinfo  # type: ignore[method-assign]
    try:
        yield
    finally:
        # 顺序要紧：reset 是把 `_PREVIOUS` 写回 socket 的那一步。
        policy.reset_for_tests()
        current = socket.getaddrinfo
        # 判断"那一格上挂的是不是我们家的东西"，两种都要摘：
        #   - 带 `_mail_dns_guard` 标记的壳 —— 含 **reload 之前那一代**的 `_wrapped`
        #     （`importlib.reload` 会换掉模块里的对象，所以不能只比对 `policy._wrapped`，
        #      这样才抓得住"旧壳还挂在 socket 上"这种跨代泄漏）；
        #   - 我们塞进去的假解析器本身。
        if getattr(current, "_mail_dns_guard", False) or current is _fake_getaddrinfo:
            socket.getaddrinfo = original_real  # type: ignore[method-assign]
        # 走到这里还不对 ⇒ 那一格是**别人**的 patch，交还、不覆盖（覆盖 = 吃掉它的替身）。
        if socket.getaddrinfo is not original_real:
            assert not getattr(socket.getaddrinfo, "_mail_dns_guard", False), (
                "socket.getaddrinfo 上还挂着我们的壳，会毒化后续测试文件"
            )
            assert socket.getaddrinfo is not _fake_getaddrinfo, (
                "假解析器泄漏到进程级，会毒化后续测试文件"
            )


def _families(host: str) -> list[int]:
    return [entry[0] for entry in socket.getaddrinfo(host, 993)]


def test_guarded_host_drops_ipv6() -> None:
    """没装护栏时 v6 排在前面（就是它把连接拖 12s）；装完只剩 v4。"""
    # 先自证量具：假解析器复现的是 2026-09-28 在她机器上实测到的顺序，
    # 不拿真 DNS 当前值当判据（否则这条测试会随网络抖动变红/变绿）。
    assert [entry[0] for entry in _fake_getaddrinfo("imap.qq.com", 993)] == [
        socket.AF_INET6,
        socket.AF_INET,
    ]
    policy.guard_mail_hosts(["imap.qq.com", "smtp.qq.com"])
    assert _families("imap.qq.com") == [socket.AF_INET]
    assert _families("smtp.qq.com") == [socket.AF_INET]


def test_non_mail_host_passes_through_untouched() -> None:
    """🔴 反向锁：护栏的作用面必须只有邮件主机。

    非邮件主机若也被改成 v4，这条测试就红 —— 防的是"顺手全局限 IPv4"把别的
    v6-only 服务（或以后别的解析）一起弄坏。
    """
    policy.guard_mail_hosts(["imap.qq.com"])
    assert _families("www.baidu.com") == [socket.AF_INET6, socket.AF_INET]


def test_suffix_registration_covers_subdomains() -> None:
    policy.guard_mail_hosts(["qq.com"])
    assert _families("imap.qq.com") == [socket.AF_INET]


def test_v4_empty_falls_back_instead_of_failing() -> None:
    """这台只有 AAAA：不能因为护栏把它判成"解析不出"。"""
    policy.guard_mail_hosts(["v6only.example.com"])
    assert _families("v6only.example.com") == [socket.AF_INET6]


def test_explicit_family_is_not_rewritten() -> None:
    """显式要 v6 的调用是调用方的决定，护栏不覆盖它。"""
    policy.guard_mail_hosts(["imap.qq.com"])
    got = socket.getaddrinfo("imap.qq.com", 993, socket.AF_INET6)
    assert [entry[0] for entry in got] == [socket.AF_INET6]


def test_install_is_idempotent() -> None:
    """重复登记不能把 getaddrinfo 套成洋葱（还原会漏一层）。"""
    policy.guard_mail_hosts(["imap.qq.com"])
    wrapped_once = socket.getaddrinfo
    policy.guard_mail_hosts(["imap.qq.com", "smtp.qq.com"])
    assert socket.getaddrinfo is wrapped_once
    assert policy.is_installed() is True


def test_reset_restores_original_resolver() -> None:
    """还原必须真的把 socket.getaddrinfo 写回安装前那一格。

    这条以前是空断言（只看假解析器自己的输出），删掉 ``socket.getaddrinfo = _ORIGINAL``
    照样全绿。现在删掉它，下面的 ``is policy._ORIGINAL`` 就红。
    """
    policy.guard_mail_hosts(["imap.qq.com"])
    assert policy.is_installed() is True
    policy.reset_for_tests()
    assert socket.getaddrinfo is policy._ORIGINAL
    assert socket.getaddrinfo is _fake_getaddrinfo
    assert policy.is_installed() is False


def test_asyncio_positional_shape_is_guarded() -> None:
    """生产实形：asyncio 经 loop.getaddrinfo 发的是 6 个位置参数。

    只测 (host, port) 两参形状的话，把 family 读成第 4 个位置参数（type）这类错位
    不会被发现 —— 护栏会对生产空转而测试全绿。这里按 asyncio 的真实调用形状打。
    """
    policy.guard_mail_hosts(["imap.qq.com"])
    got = socket.getaddrinfo("imap.qq.com", 993, 0, socket.SOCK_STREAM, 0, 0)
    assert [entry[0] for entry in got] == [socket.AF_INET]


def test_keyword_family_does_not_raise() -> None:
    """调用方用关键字写 family 时不能炸成 TypeError。

    护栏把 AF_INET 塞进第 3 个位置参数的同时必须把 kwargs 里的 family 摘掉，
    否则 "multiple values for argument 'family'"。yt_dlp/socks.py 就是这个写法。
    """
    policy.guard_mail_hosts(["imap.qq.com"])
    got = socket.getaddrinfo("imap.qq.com", 993, family=0)
    assert [entry[0] for entry in got] == [socket.AF_INET]
    # 显式要 v6 的调用仍然原样放行。
    got6 = socket.getaddrinfo("imap.qq.com", 993, family=socket.AF_INET6)
    assert [entry[0] for entry in got6] == [socket.AF_INET6]


def test_other_patch_on_top_is_not_eaten() -> None:
    """别人把 patch 压在我们上面时：is_installed() 要说假，reset 不能把别人的壳吃掉。"""
    policy.guard_mail_hosts(["imap.qq.com"])

    def _someone_elses(host: Any, port: Any, *a: Any, **kw: Any) -> list[Any]:
        return []

    socket.getaddrinfo = _someone_elses  # type: ignore[method-assign]
    assert policy.is_installed() is False
    policy.reset_for_tests()
    assert socket.getaddrinfo is _someone_elses


def test_reload_does_not_create_onion() -> None:
    """模块热重载后，_ORIGINAL 必须穿过旧壳拿到真解析器，不能把旧壳当原始函数存下来。"""
    import importlib

    policy.guard_mail_hosts(["imap.qq.com"])
    assert socket.getaddrinfo is policy._wrapped
    reloaded = importlib.reload(policy)
    try:
        assert reloaded._ORIGINAL is _fake_getaddrinfo
        assert getattr(reloaded._ORIGINAL, "_mail_dns_guard", False) is False
    finally:
        importlib.reload(policy)


def test_hosts_from_bot_infos_skips_missing_fields() -> None:
    class _Leg:
        def __init__(self, host: str) -> None:
            self.host = host

    class _Bot:
        def __init__(self, imap_host: str, smtp_host: str) -> None:
            self.imap = _Leg(imap_host)
            self.smtp = _Leg(smtp_host)

    bots = [_Bot("imap.qq.com", "smtp.qq.com"), _Bot("  ", "smtp.gmail.com")]

    class _Broken:
        pass

    hosts = policy.mail_hosts_from_bot_infos([*bots, _Broken()])
    assert hosts == {"imap.qq.com", "smtp.qq.com", "smtp.gmail.com"}
