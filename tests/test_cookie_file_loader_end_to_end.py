"""Cookie 文件通路端到端回归（2026-09-25 S-T-COOKIE-1）。

要证的三件事，都是管理员真实会撞上的：

1. **文件路径真的通**：真实 ``Config`` 的 ``data/platform_cookies.txt`` 经
   path_fields 重映射到 Runtime 根；读取侧拿到的绝对路径，与
   ``/bot cookie import`` 写入侧落在同一个文件上。
2. **不认识的域名不会被冒充成某个平台**：浏览器导出的淘宝/闲鱼（本次真实
   误传形态）域名不在册 ⇒ 任何平台都不该拿到它；同时它必须**说得出话**
   （未认领账目：域名 + 计数，绝不含值）。
3. **改了文件不必重启**：mtime 变化 ⇒ 注册表缓存重建，且新 cookie 值真的
   进到重建时递给注册表的那个 provider 里。兄弟件
   ``tests/test_cookie_import_hot_reload.py`` 把 provider 整个打桩掉了，
   因此它只证明「重建发生了」，证不到「新值到了」——本文件补这一格。

离线：零网络；凭证全是 ``fake-`` 开头的假值；文件只落 ``tmp_path``。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import pytest

from plugins.bot_unified_runtime import (
    _CONTENT_REGISTRY_CACHE,
    _cached_content_parser_registry,
)
from plugins.bot_unified_runtime.domains.link_parse import parsers as parsers_module
from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
    _REPORTED_IDENTITIES,
    PLATFORM_COOKIE_DOMAINS,
    UNCLAIMED_REPORT_TOKEN,
    PlatformCookieProvider,
    build_platform_cookie_provider,
    cookie_file_report_lines,
    near_miss_platform,
    parse_netscape_cookie_file,
)

# 假凭证值：兼作「值绝不出现在报告/日志里」的探针。
FAKE_SESSDATA = "fake-session-value"
FAKE_TAOBAO = "fake-taobao-probe-value"
FAKE_GOOFISH = "fake-goofish-probe-value"

# 真实误传样例的域名（Netscape 导出原文形态，淘宝/闲鱼都不在册）。
TAOBAO_DOMAIN = "h5api.m.taobao.com"
FUTURE = 1893456000  # 2030-01-01：确保「未认领」不会被「已过期」串台。


class _StubRegistry:
    """替身注册表：只给缓存层一个可比身份的返回值，不含任何真实解析器。"""

    def __init__(self, marker: int) -> None:
        self.marker = marker


class _LogCatcher(logging.Handler):
    """挂在模块 logger 上的真实抓取器（不打桩 ``logger.warning``，走真出口）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(record.getMessage() for record in self.records)


def _row(domain: str, name: str, value: str, *, expires: int = 0) -> str:
    return f"{domain}\tTRUE\t/\tFALSE\t{expires}\t{name}\t{value}"


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _bump_mtime(path: Path, *, offset_ns: int = 2_000_000) -> None:
    stamp = path.stat().st_mtime_ns + offset_ns
    os.utime(path, ns=(stamp, stamp))


def _config(tmp_path: Path):
    """真身 Config：cookies 文件走 data/ 相对值，由校验器重映射到 tmp 根。"""
    from plugins.bot_unified_runtime.config import Config

    return Config(bot_runtime_data_dir=str(tmp_path), bot_cookies_file="data/platform_cookies.txt")


@pytest.fixture
def log_catcher():
    logger = logging.getLogger(
        "plugins.bot_unified_runtime.domains.link_parse.parsers.cookies"
    )
    handler = _LogCatcher()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.fixture(autouse=True)
def _reset_report_dedupe():
    """报告按内容身份去重：用例间必须清账，否则「该报的没报」会假绿。"""
    _REPORTED_IDENTITIES.clear()
    _CONTENT_REGISTRY_CACHE.clear()
    yield
    _REPORTED_IDENTITIES.clear()
    _CONTENT_REGISTRY_CACHE.clear()


# ---------- ① 真实配置下的文件通路 ----------


def test_real_config_path_is_remediated_and_actually_read(tmp_path, monkeypatch):
    """Config 的 data/ 相对值 ⇒ 绝对路径落在 Runtime 根，读取侧真的吃到。"""
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    config = _config(tmp_path)
    cookies_file = Path(str(config.bot_cookies_file))
    assert cookies_file.is_absolute(), f"配置值未被重映射：{cookies_file}"
    assert cookies_file == tmp_path / "platform_cookies.txt"

    _write(cookies_file, [_row(".bilibili.com", "SESSDATA", FAKE_SESSDATA)])

    provider = build_platform_cookie_provider(str(config.bot_cookies_file))
    assert provider.has_cookie("bilibili")
    assert provider.cookie_header("bilibili") == f"SESSDATA={FAKE_SESSDATA}"
    # 报告里的文件身份 = 真正被读的那个绝对路径（不是 CWD 相对值）。
    assert provider.source_path == str(cookies_file)
    assert provider.entry_total == 1
    assert provider.has_unclaimed() is False, "全部在册且未过期 ⇒ 不该有未认领账目"


def test_httponly_prefixed_row_is_claimed_and_needs_no_report(tmp_path, log_catcher):
    """``#HttpOnly_`` 是合法 Netscape 行：吃到登录态，且不被记成未认领。"""
    path = _write(
        tmp_path / "cookies.txt",
        [
            "# Netscape HTTP Cookie File",
            "#HttpOnly_" + _row(".bilibili.com", "SESSDATA", FAKE_SESSDATA),
        ],
    )
    provider = build_platform_cookie_provider(path)
    assert provider.cookie_header("bilibili") == f"SESSDATA={FAKE_SESSDATA}"
    assert provider.unclaimed_domains == {}
    assert log_catcher.text == "", "干净文件不该刷报告"


# ---------- ② 不认的域名：绝不冒充 + 必须说话 ----------


def test_taobao_and_goofish_export_is_not_claimed_but_is_reported(tmp_path, log_catcher):
    """真实误传形态（淘宝/闲鱼登录态）：谁都不许拿到，而且必须说清楚。"""
    path = _write(
        tmp_path / "cookies.txt",
        [
            "# Netscape HTTP Cookie File",
            _row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE),
            _row(".h5api.m.taobao.com", "_nk_", FAKE_TAOBAO, expires=FUTURE),
            _row(".goofish.com", "unf", FAKE_GOOFISH, expires=FUTURE),
        ],
    )
    provider = build_platform_cookie_provider(path)

    # (a) 绝不冒充成任何平台：一个 cookie 头都不许有。
    assert provider.headers == {}, f"未认领域名不得产出 cookie 头：{list(provider.headers)}"
    assert "taobao" not in PLATFORM_COOKIE_DOMAINS
    assert "goofish" not in PLATFORM_COOKIE_DOMAINS
    assert provider.has_cookie("taobao") is False
    assert provider.has_cookie("bilibili") is False

    # (b) 未认领账目：域名 + 计数，条数对得上。
    assert provider.entry_total == 3
    assert sum(provider.unclaimed_domains.values()) == 3
    assert set(provider.unclaimed_domains) == {TAOBAO_DOMAIN, ".h5api.m.taobao.com", ".goofish.com"}
    assert provider.unclaimed_domains[TAOBAO_DOMAIN] == 1
    assert provider.expired_dropped == {}, "未在册 ≠ 已过期，两本账不许混"
    assert near_miss_platform(TAOBAO_DOMAIN) == "", "淘宝不该被猜成任何在册平台"

    # (c) 报告说得清「这份文件对 bot 没用」，值/cookie 名/本机路径都不出现。
    report = "\n".join(cookie_file_report_lines(provider))
    assert "未认领" in report and "3" in report
    assert TAOBAO_DOMAIN in report and "goofish.com" in report
    assert FAKE_TAOBAO not in report and FAKE_GOOFISH not in report
    assert "cookie2" not in report and "unf" not in report, "报告只给域名与计数，不给 cookie 名"
    assert "<本机路径已隐藏>" in report, f"绝对路径必须打码：{report}"

    # (d) 日志：固定检索词（**字面量**，改用常量引用会锁成自证空跑）+ 同样消毒口径。
    text = log_catcher.text
    assert "cookie_unclaimed_domains" in text
    assert UNCLAIMED_REPORT_TOKEN == "cookie_unclaimed_domains"
    assert FAKE_TAOBAO not in text and FAKE_GOOFISH not in text
    assert str(path) not in text, f"日志不得出现未打码的盘符路径：{text}"
    assert "<本机路径已隐藏>" in text
    assert [record.levelno for record in log_catcher.records] == [logging.WARNING]


def test_mixed_export_keeps_known_platforms_and_names_the_rest(tmp_path):
    """浏览器「一键导出全部」：认得的照常生效，不认得的点名，互不牵连。"""
    path = _write(
        tmp_path / "cookies.txt",
        [
            _row(".bilibili.com", "SESSDATA", FAKE_SESSDATA),
            _row(".kugou.com", "userid", "fake-kugou-probe"),
            _row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE),
        ],
    )
    provider = build_platform_cookie_provider(path)
    assert set(provider.headers) == {"bilibili", "kugou"}
    assert list(provider.unclaimed_domains) == [TAOBAO_DOMAIN]
    report = "\n".join(cookie_file_report_lines(provider))
    assert "命中 2 个平台" in report and "未认领 1 条" in report


def test_host_only_domain_is_named_as_near_miss_not_silently_dropped(tmp_path):
    """host-only 写法吃不中精确成员判定 ⇒ 至少要点名「疑似本该命中」。"""
    path = _write(tmp_path / "cookies.txt", [_row("www.bilibili.com", "SESSDATA", FAKE_SESSDATA)])
    provider = build_platform_cookie_provider(path)

    # 现状：精确成员判定 ⇒ 确实没吃到（本文件不擅自放宽匹配）。
    assert provider.has_cookie("bilibili") is False
    assert provider.unclaimed_domains == {"www.bilibili.com": 1}
    assert provider.near_miss_domains == {"www.bilibili.com": "bilibili"}
    report = "\n".join(cookie_file_report_lines(provider))
    assert "疑似本该命中" in report and "www.bilibili.com→bilibili" in report
    # 反向：在册形态本身是直接命中，不进 near miss 账。
    assert near_miss_platform(".bilibili.com") == "bilibili"


def test_longest_registered_suffix_wins_for_multi_level_domains():
    """多级在册后缀归属取最长匹配，防 ``.qq.com`` 抢走 ``y.qq.com`` 的账。"""
    assert near_miss_platform("y.qq.com") == "qqmusic"
    assert near_miss_platform("music.163.com") == "netease"
    assert near_miss_platform("example.com") == ""
    assert near_miss_platform("") == ""


def test_expired_credentials_are_reported_as_their_own_bucket(tmp_path, log_catcher):
    """域名认得但已过期：另一类「我明明导入了」，与未认领分账。"""
    path = _write(
        tmp_path / "cookies.txt",
        [
            _row(".bilibili.com", "SESSDATA", FAKE_SESSDATA, expires=int(time.time()) - 3600),
            _row(".kugou.com", "userid", "fake-kugou-probe-2"),
        ],
    )
    provider = build_platform_cookie_provider(path)
    assert provider.has_cookie("bilibili") is False
    assert provider.has_cookie("kugou")
    assert provider.unclaimed_domains == {}
    assert provider.expired_dropped == {".bilibili.com": 1}
    report = "\n".join(cookie_file_report_lines(provider))
    assert "已过期" in report and ".bilibili.com" in report
    assert FAKE_SESSDATA not in report
    assert UNCLAIMED_REPORT_TOKEN in log_catcher.text


def test_space_separated_export_says_it_parsed_nothing(tmp_path, log_catcher):
    """伪 Netscape（空格分隔/列数不足）：整份文件白导，过去零声响。"""
    path = _write(
        tmp_path / "cookies.txt",
        [
            "# Netscape HTTP Cookie File",
            f".bilibili.com TRUE / FALSE 0 SESSDATA {FAKE_SESSDATA}",
            ".kugou.com TRUE / FALSE 0 userid",
        ],
    )
    provider = build_platform_cookie_provider(path)
    assert provider.headers == {}
    assert provider.entry_total == 0
    assert provider.unparsable_lines == 2, "两行正文都解析不出条目 ⇒ 必须数出来"
    report = "\n".join(cookie_file_report_lines(provider))
    assert "解析不出条目" in report and "TAB" in report
    assert FAKE_SESSDATA not in report
    assert UNCLAIMED_REPORT_TOKEN in log_catcher.text


def test_report_fires_once_per_file_identity_then_again_on_change(tmp_path, log_catcher):
    """去重：同一份内容反复重建不刷屏；文件真变了要再报一次。"""
    path = _write(tmp_path / "cookies.txt", [_row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE)])
    for _ in range(5):
        build_platform_cookie_provider(path)
    assert len(log_catcher.records) == 1, "点歌/解析每次重建 provider，报告不得跟着刷 5 条"

    _write(
        path,
        [
            _row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE),
            _row(".goofish.com", "unf", FAKE_GOOFISH, expires=FUTURE),
        ],
    )
    build_platform_cookie_provider(path)
    assert len(log_catcher.records) == 2
    assert "goofish.com" in log_catcher.records[1].getMessage()


def test_clean_file_emits_no_report_and_no_log_line(tmp_path, log_catcher):
    """全在册 ⇒ 零报告（不造噪声，也不平白多一份指纹）。"""
    path = _write(tmp_path / "cookies.txt", [_row(".weibo.com", "SUB", "fake-weibo-probe")])
    provider = build_platform_cookie_provider(path)
    assert provider.has_cookie("weibo")
    assert cookie_file_report_lines(provider) == []
    assert log_catcher.text == ""


def test_report_redaction_survives_a_missing_redactor(tmp_path, monkeypatch):
    """打码件**导入不到**时宁可丢路径也不裸奔（AGENTS 规则 3 的兜底腿①）。"""
    path = _write(tmp_path / "cookies.txt", [_row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE)])
    build_platform_cookie_provider(path)
    # 把「导入打码件」这一步弄成必然失败，模拟最坏环境。
    monkeypatch.setitem(
        sys.modules, "plugins.bot_unified_runtime.domains.render.plain_text", None
    )
    joined = "\n".join(cookie_file_report_lines(build_platform_cookie_provider(path)))
    assert "未认领" in joined
    assert str(path) not in joined, "打码不可用时也不得输出绝对路径"
    assert "文件路径已隐藏" in joined


def test_report_redaction_survives_a_throwing_redactor(tmp_path, monkeypatch):
    """打码件**自己抛异常**时同样不裸奔（兜底腿②，与腿①各锁各的）。"""
    path = _write(tmp_path / "cookies.txt", [_row(TAOBAO_DOMAIN, "cookie2", FAKE_TAOBAO, expires=FUTURE)])
    provider = build_platform_cookie_provider(path)
    from plugins.bot_unified_runtime.domains.render import plain_text

    def _boom(_text: str) -> str:
        raise RuntimeError("redactor down")

    monkeypatch.setattr(plain_text, "redact_local_secrets", _boom)
    joined = "\n".join(cookie_file_report_lines(provider))
    assert "未认领" in joined and TAOBAO_DOMAIN in joined
    assert str(path) not in joined, f"打码抛错时也不得输出绝对路径：{joined}"
    assert "文件路径已隐藏" in joined


# ---------- ③ 改了文件不重启就生效（端到端，含新值） ----------


def test_provider_reads_current_bytes_of_the_same_path_without_cache(tmp_path):
    """读取侧自身无缓存：同一路径改写后立即读到新值（import 追加的场景）。"""
    path = _write(tmp_path / "cookies.txt", [_row(".bilibili.com", "SESSDATA", "fake-old-value")])
    assert build_platform_cookie_provider(path).cookie_header("bilibili") == "SESSDATA=fake-old-value"

    _write(
        path,
        [
            _row(".bilibili.com", "SESSDATA", "fake-old-value"),
            _row(".bilibili.com", "bili_jct", "fake-new-value"),
        ],
    )
    _bump_mtime(path)
    header = build_platform_cookie_provider(path).cookie_header("bilibili")
    assert "SESSDATA=fake-old-value" in header and "bili_jct=fake-new-value" in header
    assert len(parse_netscape_cookie_file(path)) == 2


def test_registry_cache_rebuilds_and_carries_the_new_cookie_value(tmp_path, monkeypatch):
    """热生效端到端：缓存键吃的 mtime 与读取侧是同一个文件，新值真进了重建。

    只把 ``build_content_parser_registry``（注册表本体，构造要 Playwright）
    打桩；mtime 缓存判定与 ``build_cookie_provider`` 全走真身。
    """
    config = _config(tmp_path)
    path = Path(str(config.bot_cookies_file))
    _write(path, [_row(".bilibili.com", "SESSDATA", "fake-first-value")])

    seen: list[PlatformCookieProvider] = []

    def fake_build(platforms, cookie_provider=None, proxy="", playwright_backend=None):
        assert isinstance(cookie_provider, PlatformCookieProvider)
        seen.append(cookie_provider)
        return _StubRegistry(marker=len(seen))

    monkeypatch.setattr(parsers_module, "build_content_parser_registry", fake_build)

    first = _cached_content_parser_registry(config, playwright_backend=None)
    assert len(seen) == 1
    assert seen[0].cookie_header("bilibili") == "SESSDATA=fake-first-value"

    # 文件没动：反复取用必须命中缓存（每条消息重建=纯浪费，也是旧口径的痛）。
    assert _cached_content_parser_registry(config, playwright_backend=None) is first
    assert len(seen) == 1

    # 模拟 /bot cookie import 追加：mtime 变 ⇒ 重建，且**新值在重建时的 provider 上**。
    _write(
        path,
        [
            _row(".bilibili.com", "SESSDATA", "fake-first-value"),
            _row(".bilibili.com", "DedeUserID", "fake-second-value"),
        ],
    )
    _bump_mtime(path)
    second = _cached_content_parser_registry(config, playwright_backend=None)
    assert second is not first
    assert len(seen) == 2
    assert "DedeUserID=fake-second-value" in seen[1].cookie_header("bilibili")

    # 重建后重新稳定命中。
    assert _cached_content_parser_registry(config, playwright_backend=None) is second
    assert len(seen) == 2


def test_missing_cookie_file_is_quiet_and_yields_anonymous_provider(tmp_path):
    """文件还没建（首次部署）：不报错、不刷报告，解析走匿名。"""
    config = _config(tmp_path)
    provider = build_platform_cookie_provider(str(config.bot_cookies_file))
    assert provider.headers == {}
    assert provider.has_unclaimed() is False
    assert cookie_file_report_lines(provider) == []


def test_empty_config_value_means_anonymous_and_never_reads_cwd(tmp_path, monkeypatch):
    """留空 = 匿名解析（缺省语义），绝不退化成「读当前目录的 data/」。"""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / "data" / "platform_cookies.txt", [_row(".bilibili.com", "SESSDATA", FAKE_SESSDATA)])
    provider = build_platform_cookie_provider("")
    assert provider.headers == {}
    assert provider.source_path == ""


# ---------- ④ 命令面（import/status）与文件通路对齐 ----------


def test_import_then_read_round_trip_lands_on_one_file(tmp_path, monkeypatch):
    """写入侧（``/bot cookie import`` 落码）与读取侧必须落在同一个文件上。"""
    from plugins.bot_unified_runtime.domains.core.credentials.platform_credentials import (
        cookie_status_text,
        import_cookie_header,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    config = _config(tmp_path)
    text = import_cookie_header(config, "bilibili", f"SESSDATA={FAKE_SESSDATA}; buvid3=fake-buvid")
    assert "bilibili" in text and "2 项" in text

    written = Path(str(config.bot_cookies_file))
    assert written.exists(), "写入侧与读取侧路径不一致：import 落到了别处"
    provider = build_platform_cookie_provider(str(config.bot_cookies_file))
    assert provider.key_names["bilibili"] == ["SESSDATA", "buvid3"]
    assert provider.cookie_header("bilibili") == f"SESSDATA={FAKE_SESSDATA}; buvid3=fake-buvid"

    status = cookie_status_text(config)
    assert "bilibili" in status and FAKE_SESSDATA not in status, "状态页只给名字，不给值"
    # 同名不覆盖（帮助页承诺的一条）。
    again = import_cookie_header(config, "bilibili", "SESSDATA=other-value; buvid3=fake-buvid")
    assert "已存在" in again and "同名不覆盖" in again
    assert build_platform_cookie_provider(str(config.bot_cookies_file)).cookie_header(
        "bilibili"
    ) == f"SESSDATA={FAKE_SESSDATA}; buvid3=fake-buvid"


def test_quoted_header_keeps_the_quote_inside_the_first_name(tmp_path):
    """现状刻画：QQ 消息不经 shell 拆词 ⇒ 给 Cookie 头加引号会把引号粘进名字。

    帮助页的例子（``echo.py:1072``）本来就不带引号，本席 runbook 因此写
    「不要加引号」。此锁的意义是让「谁顺手把引号剥掉」这件事必须显式发生：
    真去支持引号 = 行为变更 = 本用例转红 = 改的人得知道自己改了语义。
    """
    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.core.credentials.platform_credentials import (
        import_cookie_header,
    )

    config = Config(bot_runtime_data_dir=str(tmp_path), bot_cookies_file="data/platform_cookies.txt")
    quoted = f'"SESSDATA={FAKE_SESSDATA}; bili_jct=fake-jct"'
    import_cookie_header(config, "bilibili", quoted)
    names = build_platform_cookie_provider(str(config.bot_cookies_file)).key_names.get("bilibili")
    assert names is not None
    assert names[0] == '"SESSDATA', f"引号被当作名字的一部分（现状）：{names}"
    assert names[1] == "bili_jct", f"分号后的名字不受引号影响：{names}"

    plain = f"SESSDATA={FAKE_SESSDATA}; bili_jct=fake-jct"
    other = Config(bot_runtime_data_dir=str(tmp_path / "plain"), bot_cookies_file="data/platform_cookies.txt")
    import_cookie_header(other, "bilibili", plain)
    plain_names = build_platform_cookie_provider(str(other.bot_cookies_file)).key_names.get("bilibili")
    assert plain_names == ["SESSDATA", "bili_jct"], "不带引号才是这份名单该有的样子"


def test_unknown_platform_import_is_refused_and_lists_the_real_roster(tmp_path):
    """她想导的淘宝/闲鱼在命令面就被拒，并给出**完整**在册名单。"""
    from plugins.bot_unified_runtime.domains.core.credentials.platform_credentials import (
        import_cookie_header,
    )

    config = _config(tmp_path)
    refused = import_cookie_header(config, "taobao", f"cookie2={FAKE_TAOBAO}")
    assert "未知平台" in refused
    for platform in PLATFORM_COOKIE_DOMAINS:
        assert platform in refused, f"拒绝文案应列出全部 {len(PLATFORM_COOKIE_DOMAINS)} 个在册平台"
    assert FAKE_TAOBAO not in refused
    assert not Path(str(config.bot_cookies_file)).exists(), "拒绝就不该落盘"
