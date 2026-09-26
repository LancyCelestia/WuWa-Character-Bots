"""免 key 搜索兜底接进 config 那条链的六把锁（席 W23，2026-09-24）。

被锁的行为
    `search_api.build_api_search_provider` 对**缺 key 的供应商静默跳过**
    （`search_api.py:478` 的 `if api_key and endpoint`），于是经 config 构造的
    检索链最坏情形是「开关开着、链是空的」：Tavily/You/LangSearch 任一配额耗尽
    或网络故障时，链上没有第二层落点。本格把免 key 的 DDG → Bing 作为**尾部兜底**
    接进那条链，且：

    ① 缺省关——配置面尚无该字段时，链的构造结果与改前逐字节一致（反向锁 1/2）；
    ② 只追加在 key 家**之后**，不抢跑、不改序（锁 3、顺序锁 7）；
    ③ 兜底自身失败 ⇒ 诚实返回空表、绝不向上抛（锁 4）；
    ④ URL 判据**复用**席 W18 那条中央咽喉（入口 `_ssrf_rejection_for_fetch` +
      逐跳 `_ssrf_request_guard`），不新建第二套真身（锁 5/6/8 + 结构锁 9）。

全离线纪律：零真实网络——所有引擎请求都经 monkeypatch 掉的 `_fetch` /
`_build_sync_client`；内网与整型混淆 IP 走字面量判定不触 DNS；公网面用公网 IP
字面量（93.184.216.34）避免解析；注毒一律进程内 `monkeypatch`（禁编辑磁盘）。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.config import Config, translate_env_keys
from plugins.bot_unified_runtime.domains.core.search import web_search
from plugins.bot_unified_runtime.domains.core.search.search_api import (
    _JsonSearchProvider,
)

_KEYFREE_FIELD = web_search._KEYFREE_TAIL_CONFIG_FIELD

# --------------------------------------------------------------------------- #
# 配置替身（SimpleNamespace 形与生产 Config 同构：只按字段名 getattr）
# --------------------------------------------------------------------------- #
_BASE_CONFIG: dict[str, object] = {
    "bot_web_search_enabled": True,
    "bot_web_search_provider": "tavily",
    "bot_web_search_fallback_providers": ["you", "langsearch"],
    "bot_web_search_timeout_seconds": 3.0,
    "bot_download_proxy": "",
    "bot_web_search_tavily_api_key": "tavily-key",
    "bot_web_search_you_api_key": "you-key",
    "bot_web_search_langsearch_api_key": "lang-key",
    "bot_web_search_provider_options": {},
}

_NO_KEYS = {
    "bot_web_search_tavily_api_key": "",
    "bot_web_search_you_api_key": "",
    "bot_web_search_langsearch_api_key": "",
}


def _cfg(**overrides: object) -> SimpleNamespace:
    """缺省形态＝**没有** `_KEYFREE_FIELD` 这一枚属性（今天的生产 Config 实况）。"""
    return SimpleNamespace(**{**_BASE_CONFIG, **overrides})


def _cfg_tail_on(**overrides: object) -> SimpleNamespace:
    """模拟主会话把配置键落地（缺省 True）之后的形态。"""
    return _cfg(**{_KEYFREE_FIELD: True, **overrides})


def _names(provider: object) -> list[str]:
    return [str(getattr(item, "name", "")) for item in getattr(provider, "providers", [])]


# --------------------------------------------------------------------------- #
# 离线夹具
# --------------------------------------------------------------------------- #
class _StubClient:
    """替身 httpx 客户端（`is_closed` 供惰性重建判据读取）。"""

    is_closed = False

    def get(self, url: str) -> object:  # pragma: no cover - 永不被真调用
        raise AssertionError(f"真实网络被发起：{url}")

    def close(self) -> None:
        return None


class _FetchSpy:
    """替换 `web_search._fetch`：记录 URL 与 kwargs，返回可控正文。"""

    def __init__(self, text: str | None = None) -> None:
        self.urls: list[str] = []
        self.calls: list[dict] = []
        self._text = text

    def __call__(self, url, **kwargs):
        self.urls.append(str(url))
        self.calls.append(dict(kwargs, url=url))
        return self._text

    @property
    def count(self) -> int:
        return len(self.urls)


class _RecordingKeyProvider:
    """key 类提供器替身：可给定命中或让每次检索抛错。"""

    def __init__(self, name: str, *, hits=None, error: Exception | None = None) -> None:
        self.name = name
        self.hits = list(hits or [])
        self.error = error
        self.calls = 0

    def search(self, query: str, *, max_results: int = 3) -> list[web_search.WebSearchHit]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.hits)

    def close(self) -> None:
        return None


def _hit(url: str, title: str = "结果") -> web_search.WebSearchHit:
    return web_search.WebSearchHit(title=title, snippet="一段够长的摘要内容。", url=url)


def _install_offline_http(monkeypatch, *, text: str | None = None) -> _FetchSpy:
    spy = _FetchSpy(text)
    monkeypatch.setattr(web_search, "_fetch", spy)
    monkeypatch.setattr(
        web_search, "_build_sync_client", lambda *a, **k: _StubClient()
    )
    return spy


def _ddg_html(urls: list[str], *, term: str = "守岸人") -> str:
    """按 `_extract_ddg_hits` 的解析形态造结果页（绝对 https/http 链接形态）。"""
    blocks = "".join(
        '<div class="result">'
        f'<a class="result__a" href="{url}">{term} 标题 {index}</a>'
        f'<div class="result__snippet">{term}是鸣潮中的治疗角色，'
        f"这段摘要足够长可以过 relevance 与摘要长度两道线 {index}。</div>"
        "</div>"
        for index, url in enumerate(urls)
    )
    return f"<html><body>{blocks}</body></html>"


METADATA_URL = "http://169.254.169.254/latest/meta-data/"
DECIMAL_URL = "http://2130706433/x"  # 十进制混淆 = 127.0.0.1
PUBLIC_URL = "https://93.184.216.34/guide"


# --------------------------------------------------------------------------- #
# 锁 1（反向锁，本格最重要）：缺省配置 ⇒ 兜底构造器一次都不被调用、链逐字节现状
# --------------------------------------------------------------------------- #
def test_default_config_chain_is_byte_identical_and_tail_builder_never_called(
    monkeypatch,
) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("缺省配置下建了免 key 尾部兜底＝生产行为被改了")

    monkeypatch.setattr(web_search, "_build_keyfree_fallback_providers", _boom)
    config = _cfg()  # 没有 _KEYFREE_FIELD 这一枚属性

    assert web_search.keyfree_fallback_enabled(config) is False
    chain = web_search.build_web_search_provider(config)
    assert _names(chain) == ["tavily", "you", "langsearch"]
    assert all(isinstance(item, _JsonSearchProvider) for item in chain.providers)
    # 链上其余可观测面也一并对齐（不只名字）。
    assert chain.timeout_seconds == 3.0
    assert chain.proxy == ""
    assert chain.page_fetcher is None
    assert isinstance(chain, web_search.ChainedWebSearchProvider)


def test_production_config_declares_keyfree_field_defaulting_off() -> None:
    """键已按「四处同生」落进 `Config`，缺省 False ⇒ 线上链构造与落地前逐字节一致。

    前身是 `test_production_config_class_has_no_keyfree_field_yet`（在册证明"键未落地"）。
    2026-09-24 主会话补字段后按该条 docstring 的约定改为断言缺省值与环境装载。
    """
    config = Config.model_validate(
        translate_env_keys(
            {
                "BOT_WEB_SEARCH_ENABLED": "true",
                "BOT_WEB_SEARCH_TAVILY_API_KEY": "tavily-key",
                "BOT_WEB_SEARCH_YOU_API_KEY": "you-key",
                "BOT_WEB_SEARCH_LANGSEARCH_API_KEY": "lang-key",
            }
        )
    )
    assert hasattr(config, _KEYFREE_FIELD) is True
    assert getattr(config, _KEYFREE_FIELD) is False
    assert web_search.keyfree_fallback_enabled(config) is False
    chain = web_search.build_web_search_provider(config)
    assert _names(chain) == ["tavily", "you", "langsearch"]

    enabled = Config.model_validate(
        translate_env_keys(
            {
                "BOT_WEB_SEARCH_ENABLED": "true",
                "BOT_WEB_SEARCH_TAVILY_API_KEY": "tavily-key",
                "BOT_WEB_SEARCH_YOU_API_KEY": "you-key",
                "BOT_WEB_SEARCH_LANGSEARCH_API_KEY": "lang-key",
                "BOT_WEB_SEARCH_KEYFREE_FALLBACK_ENABLED": "true",
            }
        )
    )
    assert getattr(enabled, _KEYFREE_FIELD) is True
    assert _names(web_search.build_web_search_provider(enabled)) == [
        "tavily",
        "you",
        "langsearch",
        "ddg",
        "bing",
    ]


# --------------------------------------------------------------------------- #
# 锁 2：key 家全缺 ⇒ 免 key 家接手（真身 build_api_search_provider 的跳过路径）
# --------------------------------------------------------------------------- #
def test_missing_all_keys_hands_over_to_keyfree_tail(monkeypatch) -> None:
    _install_offline_http(monkeypatch, text=_ddg_html([PUBLIC_URL]))
    config = _cfg_tail_on(**_NO_KEYS)

    chain = web_search.build_web_search_provider(config)
    assert _names(chain) == ["ddg", "bing"]
    hits = chain.search("守岸人", max_results=3)
    assert [hit.url for hit in hits] == [PUBLIC_URL]
    assert chain.last_provider_name == "ddg"


def test_empty_chain_without_tail_is_named_in_logs(monkeypatch, caplog) -> None:
    """兜底关态 + key 家全缺＝今天的真实现状：空链必须点名，不再静默黑洞。"""
    _install_offline_http(monkeypatch, text=None)
    with caplog.at_level("WARNING"):
        chain = web_search.build_web_search_provider(_cfg(**_NO_KEYS))
    assert _names(chain) == []
    assert chain.search("守岸人") == []
    assert "web search chain is empty" in caplog.text


# --------------------------------------------------------------------------- #
# 锁 3：免 key 家**永不抢跑** key 家（三家齐备时兜底进链但不被调用）
# --------------------------------------------------------------------------- #
def test_keyfree_never_preempts_configured_key_providers(monkeypatch) -> None:
    """二选一取「进链但永不被调用」这支。

    理由：兜底的存在意义就是"在前序全灭之后还在" ⇒ 它必须在链里；
    真正要钉死的不变量是**位置**（尾）与**不被优先走到**，这两件分别由
    本条（ddg/bing 的 search 调用数为 0）与锁 7（下标恒在 key 家之后）执法。
    """
    tavily = _RecordingKeyProvider(
        "tavily", hits=[_hit("https://t.example/a", "守岸人 结果")]
    )
    you = _RecordingKeyProvider("you")
    lang = _RecordingKeyProvider("langsearch")
    monkeypatch.setattr(
        web_search,
        "build_api_search_provider",
        lambda config, *, timeout_seconds, proxy: ([tavily, you, lang], None),
    )
    ddg_calls: list[str] = []
    bing_calls: list[str] = []

    def _spy(bucket: list[str]):
        def _search(self, query, *, max_results=3):
            bucket.append(query)
            return []

        return _search

    monkeypatch.setattr(web_search.DuckDuckGoWebSearchProvider, "search", _spy(ddg_calls))
    monkeypatch.setattr(web_search.BingWebSearchProvider, "search", _spy(bing_calls))

    chain = web_search._build_chained_provider(3.0, "", _cfg_tail_on())
    assert _names(chain) == ["tavily", "you", "langsearch", "ddg", "bing"]
    assert chain.search("守岸人", max_results=3)
    assert tavily.calls == 1
    assert (ddg_calls, bing_calls) == ([], [])


def test_keyfree_used_only_after_every_key_provider_is_exhausted(monkeypatch) -> None:
    """三家依次空返回/抛错后，兜底才被走到（顺序即降级序）。"""
    _install_offline_http(monkeypatch, text=_ddg_html([PUBLIC_URL]))
    a = _RecordingKeyProvider("tavily", hits=[])
    b = _RecordingKeyProvider("you", error=RuntimeError("quota"))
    c = _RecordingKeyProvider("langsearch", hits=[])
    monkeypatch.setattr(
        web_search,
        "build_api_search_provider",
        lambda config, *, timeout_seconds, proxy: ([a, b, c], None),
    )
    chain = web_search._build_chained_provider(3.0, "", _cfg_tail_on())
    hits = chain.search("守岸人", max_results=3)
    assert [hit.url for hit in hits] == [PUBLIC_URL]
    assert chain.last_provider_name == "ddg"
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


# --------------------------------------------------------------------------- #
# 锁 4：免 key 家自己失败 ⇒ 链诚实降级（空表、不抛、不冒充命中）
# --------------------------------------------------------------------------- #
def test_keyfree_failures_degrade_to_empty_without_raising(monkeypatch) -> None:
    def _raise(self, query, *, max_results=3):
        raise RuntimeError("engine down")

    monkeypatch.setattr(web_search.DuckDuckGoWebSearchProvider, "search", _raise)
    monkeypatch.setattr(web_search.BingWebSearchProvider, "search", _raise)
    chain = web_search.build_web_search_provider(_cfg_tail_on(**_NO_KEYS))

    assert chain.search("守岸人", max_results=3) == []
    assert chain.last_provider_name == ""


def test_keyfree_engine_timeout_error_stays_silent_inside_provider(monkeypatch) -> None:
    """引擎侧网络异常被内层吞成空结果（不穿透包装层、不带上异常文本）。"""
    spy = _install_offline_http(monkeypatch, text=None)
    spy._text = None
    provider = web_search.GuardedKeyFreeWebSearchProvider(
        web_search.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")
    )
    assert provider.search("守岸人", max_results=3) == []


# --------------------------------------------------------------------------- #
# 锁 5/6/8：W18 那条 SSRF 护栏在免 key 路径上**同样生效**
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("blocked", [METADATA_URL, DECIMAL_URL])
def test_keyfree_result_urls_pass_the_central_throat(monkeypatch, blocked) -> None:
    """元数据地址与十进制混淆 IP 当"结果 URL" ⇒ 被拒，不作为可抓取目标发布。"""
    spy = _install_offline_http(
        monkeypatch, text=_ddg_html([blocked, PUBLIC_URL, "http://127.0.0.9/y"])
    )
    provider = web_search.GuardedKeyFreeWebSearchProvider(
        web_search.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")
    )
    hits = provider.search("守岸人", max_results=5)
    assert [hit.url for hit in hits] == [PUBLIC_URL]
    assert spy.count == 1  # 只打引擎域一次，被拒的结果 URL 从未被抓


def test_poison_central_throat_short_circuit_leaks_blocked_result_url(monkeypatch) -> None:
    """注毒（咽喉短路）⇒ 上一把锁必穿：证明它真有牙、判定确实流经中央真身。"""
    _install_offline_http(monkeypatch, text=_ddg_html([METADATA_URL, PUBLIC_URL]))
    monkeypatch.setattr(web_search, "_ssrf_rejection_for_fetch", lambda url: None)
    provider = web_search.GuardedKeyFreeWebSearchProvider(
        web_search.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")
    )
    urls = [hit.url for hit in provider.search("守岸人", max_results=5)]
    assert METADATA_URL in urls, "咽喉短路后仍拦住 = 锁 5 是假的"


@pytest.mark.parametrize("blocked", [METADATA_URL, DECIMAL_URL])
def test_chain_page_fetch_of_keyfree_result_is_guarded(monkeypatch, blocked) -> None:
    """链的正文抓取腿（结果 URL 的真正消费点）同样过咽喉：内网地址根本不发请求。"""
    spy = _install_offline_http(monkeypatch, text=None)
    chain = web_search.build_web_search_provider(_cfg_tail_on(**_NO_KEYS))
    assert chain.fetch_page_text(blocked, max_chars=100) == ""
    assert spy.count == 0


def test_keyfree_tail_engine_client_is_built_with_the_hop_guard(monkeypatch) -> None:
    """兜底提供器的引擎客户端必须请求逐跳钩子（复用 `_build_sync_client` 的 kwarg）。"""
    built: list[bool] = []

    def _capture(proxy, timeout_seconds, *, ssrf_guard=False):
        built.append(bool(ssrf_guard))
        return _StubClient()

    monkeypatch.setattr(web_search, "_build_sync_client", _capture)
    tail = web_search._build_keyfree_fallback_providers(3.0, "")
    for item in tail:
        inner = item._inner
        inner._get_client()
    assert built == [True, True]
    assert all(isinstance(item, web_search.GuardedKeyFreeWebSearchProvider) for item in tail)
    assert _names(SimpleNamespace(providers=tail)) == ["ddg", "bing"]


def test_default_construction_of_keyfree_providers_stays_unguarded(monkeypatch) -> None:
    """既有构造点（MCP 直调/`config is None` 分支/`search_async`）逐字节现状。"""
    built: list[bool] = []
    monkeypatch.setattr(
        web_search,
        "_build_sync_client",
        lambda proxy, timeout_seconds, ssrf_guard=False: (
            built.append(bool(ssrf_guard)) or _StubClient()
        ),
    )
    web_search.DuckDuckGoWebSearchProvider(timeout_seconds=3.0, proxy="")._get_client()
    web_search.BingWebSearchProvider(timeout_seconds=4.0, proxy="")._get_client()
    assert built == [False, False]
    provider = web_search._build_chained_provider(3.0, "")  # config=None ⇒ 旧形态
    assert _names(provider) == ["ddg", "bing"]
    assert all(
        not isinstance(item, web_search.GuardedKeyFreeWebSearchProvider)
        for item in provider.providers
    )


def test_guard_delegates_to_central_throat_without_a_second_predicate() -> None:
    """结构锁（与 W18 同型）：兜底护身只做委托，不得出现第二套 URL 判据。"""
    targets = (
        web_search._drop_ssrf_rejected_hits,
        web_search.GuardedKeyFreeWebSearchProvider,
    )
    for func in targets:
        src = inspect.getsource(func)
        assert "_ssrf_rejection_for_fetch" in src, "未委托中央咽喉包装"
        assert 'startswith("http' not in src, "回到弱 scheme 前缀自判（第二套判据）"
        for banned in ("ipaddress.", "socket.getaddrinfo", "re.compile"):
            assert banned not in src, f"自造 URL 判据：{banned}"


# --------------------------------------------------------------------------- #
# 锁 7：顺序锁——免 key 家永远排在三家之后，内部恒为 ddg → bing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("primary", "fallback"),
    [
        ("tavily", ["you", "langsearch"]),
        ("langsearch", ["tavily", "you"]),
        ("you", ["langsearch", "tavily"]),
    ],
)
def test_keyfree_tail_always_sits_after_every_key_provider(
    primary, fallback, monkeypatch
) -> None:
    monkeypatch.setattr(
        web_search,
        "_build_keyfree_fallback_providers",
        lambda timeout, proxy: [
            web_search.GuardedKeyFreeWebSearchProvider(
                web_search.DuckDuckGoWebSearchProvider(timeout_seconds=timeout)
            ),
            web_search.GuardedKeyFreeWebSearchProvider(
                web_search.BingWebSearchProvider(timeout_seconds=timeout)
            ),
        ],
    )
    names = _names(
        web_search._build_chained_provider(
            3.0, "", _cfg_tail_on(bot_web_search_provider=primary, bot_web_search_fallback_providers=fallback)
        )
    )
    key_count = len(names) - 2
    assert names[key_count:] == ["ddg", "bing"]
    assert set(names[:key_count]) == {"tavily", "you", "langsearch"}
    assert names.index("ddg") == key_count
    assert names.index("bing") == key_count + 1


def test_poison_tail_before_keys_breaks_the_order_lock(monkeypatch) -> None:
    """注毒（把兜底插到链首）⇒ 顺序锁必红：证明它读的是真拼接结果，不是手抄表。"""

    def _tail_first(key_providers, config, timeout_seconds, proxy):
        tail = web_search._build_keyfree_fallback_providers(timeout_seconds, proxy)
        return [*tail, *list(key_providers)]

    monkeypatch.setattr(web_search, "_compose_chain_providers", _tail_first)
    names = _names(
        web_search._build_chained_provider(3.0, "", _cfg_tail_on())
    )
    assert names[0] == "ddg", "注毒（兜底插到链首）没能穿进位置 = 顺序锁读的不是真拼接结果"


# --------------------------------------------------------------------------- #
# 注毒 3 发：开关短路 / 位置注毒 / 咽喉注毒（第 2、3 发见上两条 poison 用例）
# ---------------------------------------------------------------------------
def test_poison_switch_stuck_on_rebuilds_default_chain(monkeypatch) -> None:
    """注毒（`keyfree_fallback_enabled` 恒真）⇒ 反向锁 1 的那一记必红。"""
    monkeypatch.setattr(web_search, "keyfree_fallback_enabled", lambda config: True)
    called: list[bool] = []
    monkeypatch.setattr(
        web_search,
        "_build_keyfree_fallback_providers",
        lambda timeout, proxy: called.append(True) or [],
    )
    web_search.build_web_search_provider(_cfg())  # 缺省配置
    assert called, "注毒后仍不建兜底 = 锁 1 是空的"


def test_poison_switch_stuck_off_loses_the_safety_net(monkeypatch) -> None:
    """注毒（恒假）⇒ 锁 2「key 家全缺时免 key 接手」必红。"""
    monkeypatch.setattr(web_search, "keyfree_fallback_enabled", lambda config: False)
    _install_offline_http(monkeypatch, text=_ddg_html([PUBLIC_URL]))
    chain = web_search.build_web_search_provider(_cfg_tail_on(**_NO_KEYS))
    assert _names(chain) == [], "注毒后仍接手 = 锁 2 没读开关"
