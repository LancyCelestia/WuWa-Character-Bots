"""S-PATCH-WEBCFG-FIX / 缺口 E-3：明示「要最新」的查询应带**请求级**时效窗出网。

审计病根（reports/WEBCFG-AUDIT.md E-3「欠账」）：检索链没有请求级日期过滤——
`bot_web_search_tavily_time_range` 只在**装配期**烘进 provider options
（test_search_api_providers:192-214 锁死该腿，本件不改动它），链尾免 key
引擎连日期参数都没有；于是「美联储 最新 消息」和「2019年 票房 冠军」带的
新鲜度约束一模一样。本格补的是**按请求叠加层**：仅当查询被
`detect_query_recency` 认出**明示时效词**（explicit_latest，不含裸年份——
历史年题被 time_range 挡掉旧档是错的）、且该 provider 是声明了
`accepts_extra_body` 的 Tavily 形态时，才在该次请求 body 里追加
`{"time_range": <配置值>}`；缺省（配置面值为空）⇒ 整层不通电，链行为与
改前逐字节一致（keyfree_fallback_enabled 同款 getattr 缺省即关的先例）。

口径红线（用户口径＝AGENTS 第三部分 + 台账 #50/#56）：开关值读的是
**运行时注册表覆盖面**（runtime_settings 覆盖 > 装配期 config），本补丁
**不建议改 `.env`**；把该 key 接入 SETTABLE 热更面的腿触碰 config.py 绝对
禁写面，已在 patches/WEBCFG-E-3.patch.md 单列「待主代理落盘」。

补丁真身＝`patches/WEBCFG-E-3.patch.md`（search_intent `QueryRecency.explicit_latest`
+ search_api `_JsonSearchProvider` extra_body 通道 + web_search 链注入与
`resolve_latest_time_range` 读点）。

两态预期（规则 5：判据依赖未入库补丁件，如实标注）：
* **HEAD 基线（5bb67b3）**：所有使用 `latest_time_range=` / `extra_body=`
  关键字的腿、`resolve_latest_time_range` 腿、`explicit_latest` 腿为**红**
  （TypeError / 属性缺失 / None≠期望）——这是注毒自证红腿；
  「现状保真」反锁腿（装配期 options 烘档、无新 kwarg 的链不注入、
  config=None 免 key 分支不变）**两态皆绿**，钉住补丁不越界。
* **叠补丁后**：全绿。

注毒自证（退化实现必被抓红）：
* 注入不看 explicit_latest → 历史年题腿红（2019 票房被挂上周窗）；
* 注入不分 provider 形态（无 name/accepts 闸）→ 错闸腿红；
* 请求级值不最后合并 → 优先级腿红（装配值吃掉请求值）；
* 配置为空仍注入 → 现状保真腿红；
* 完全不实现 → 全部锁腿红、反锁腿绿（判据非空转的镜像证明）。

全离线：HTTP 面全部经可注入 `client` 替身与进程内 stub provider，零真实网络。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from plugins.bot_unified_runtime.domains.core.search import web_search
from plugins.bot_unified_runtime.domains.core.search.search_api import (
    TavilyWebSearchProvider,
)
from plugins.bot_unified_runtime.domains.core.search.search_intent import (
    detect_query_recency,
)

_ENDPOINT = "https://tavily.invalid/search"

# --------------------------------------------------------------------------- #
# 离线 HTTP 替身：只记录 body，回应空结果（与 _JsonSearchProvider 的
# client 注入口、test_web_search_keyfree_fallback 的替身先例同形）。
# --------------------------------------------------------------------------- #


class _OkResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"results": []}


class _CapturingClient:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def request(self, method, url, *, headers=None, params=None, json=None):
        self.bodies.append(dict(json or {}))
        return _OkResponse()


def _tavily(client: _CapturingClient, options: dict | None = None) -> TavilyWebSearchProvider:
    return TavilyWebSearchProvider(
        api_key="k", endpoint=_ENDPOINT, client=client, options=options or {}
    )


# --------------------------------------------------------------------------- #
# 链层 stub provider
# --------------------------------------------------------------------------- #


class _StubTavily:
    """Tavily 形态替身：记录每次 search 收到的 extra_body（未传则记 None）。"""

    name = "tavily"
    accepts_extra_body = True

    def __init__(self) -> None:
        self.calls: list[dict | None] = []

    def search(self, query: str, *, max_results: int = 3, extra_body=None):
        self.calls.append(extra_body)
        return []


class _StubKeyFreeEngine(_StubTavily):
    """非 Tavily 形态替身：链绝不许对它开 extra_body 通道。"""

    name = "you"
    accepts_extra_body = False


def _chain(providers: list, **kwargs) -> web_search.ChainedWebSearchProvider:
    return web_search.ChainedWebSearchProvider(list(providers), **kwargs)


# --------------------------------------------------------------------------- #
# 锁腿 1：provider 层 extra_body → 请求 JSON body
# （HEAD 红：TypeError unexpected keyword；叠补丁绿）
# --------------------------------------------------------------------------- #


def test_tavily_search_forwards_extra_body_into_request_json() -> None:
    client = _CapturingClient()
    _tavily(client).search("美联储 最新 消息", max_results=3, extra_body={"time_range": "day"})
    assert client.bodies, "替身没收到任何请求体"
    assert client.bodies[0].get("time_range") == "day"


# --------------------------------------------------------------------------- #
# 锁腿 2：请求级值**最后合并**，盖过装配期烘档值；装配期腿本身不动
# （优先级腿 HEAD 红；现状 pin 腿两态皆绿）
# --------------------------------------------------------------------------- #


def test_per_request_time_range_overrides_assembly_first_class_value() -> None:
    client = _CapturingClient()
    provider = _tavily(client, options={"time_range": "year"})
    provider.search("美联储 最新 消息", max_results=3, extra_body={"time_range": "day"})
    assert client.bodies[0].get("time_range") == "day"


def test_assembly_first_class_time_range_stays_effective_when_no_override() -> None:
    # 现状 pin：装配期 options 烘档仍生效（test_search_api_providers:192-214
    # 锁的是同一条装配腿——本件保留它，不删不改）。
    client = _CapturingClient()
    _tavily(client, options={"time_range": "year"}).search("美联储 最新 消息", max_results=3)
    assert client.bodies[0].get("time_range") == "year"


# --------------------------------------------------------------------------- #
# 锁腿 3：链层注入判据（Tavily 形态 × 明示时效词 × 配置开态）
# （HEAD 红：ChainedWebSearchProvider.__init__ 无 latest_time_range kwarg）
# --------------------------------------------------------------------------- #

LATEST_QUERY = "美联储 最新 消息"          # 装饰后形态：命中 _RECENCY_MARKER_RE
HISTORICAL_QUERY = "2019年 票房 冠军"      # 只有裸年份：wants_latest 但不明示


def test_chain_injects_latest_window_for_explicit_latest_query() -> None:
    stub = _StubTavily()
    _chain([stub], latest_time_range="week").search(LATEST_QUERY, max_results=3)
    assert stub.calls == [{"time_range": "week"}]


def test_chain_does_not_inject_for_bare_year_historical_query() -> None:
    """注毒负例：把 wants_latest 当 explicit_latest 的实现会把历史年题锁进新档窗。"""
    stub = _StubTavily()
    _chain([stub], latest_time_range="week").search(HISTORICAL_QUERY, max_results=3)
    assert stub.calls == [None]


def test_chain_never_opens_extra_body_channel_for_non_tavily_providers() -> None:
    stub = _StubKeyFreeEngine()
    _chain([stub], latest_time_range="week").search(LATEST_QUERY, max_results=3)
    assert stub.calls == [None]


def test_chain_async_path_gets_the_same_injection() -> None:
    """异步链与同步链同一不变量（旧半程形：一处执法一处不执法）。"""
    stub = _StubTavily()
    asyncio.run(_chain([stub], latest_time_range="week").search_async(LATEST_QUERY, max_results=3))
    assert stub.calls == [{"time_range": "week"}]


# --------------------------------------------------------------------------- #
# 锁腿 4：explicit_latest 判据真身在 search_intent（HEAD 红：属性不存在）
# --------------------------------------------------------------------------- #


def test_detect_recency_marks_explicit_latest_on_marker_words() -> None:
    recency = detect_query_recency(LATEST_QUERY)
    assert getattr(recency, "explicit_latest", None) is True
    assert recency.wants_latest is True


def test_detect_recency_keeps_bare_year_not_explicit() -> None:
    recency = detect_query_recency(HISTORICAL_QUERY)
    assert getattr(recency, "explicit_latest", None) is False
    # 裸年份仍要新鲜度参与其它判据——这条是现状语义，不许被本格顺手改掉：
    assert recency.wants_latest is True
    assert recency.years == (2019,)


# --------------------------------------------------------------------------- #
# 锁腿 5：配置读点 resolve_latest_time_range（唯一真身；HEAD 红：函数不存在）
# --------------------------------------------------------------------------- #


def _resolver():
    resolver = getattr(web_search, "resolve_latest_time_range", None)
    assert callable(resolver), (
        "resolve_latest_time_range 不存在：时效窗开关缺唯一读点（补丁 E-3 未叠）"
    )
    return resolver


def test_resolver_default_off_forms() -> None:
    resolver = _resolver()
    assert resolver(None) == ""
    assert resolver(SimpleNamespace()) == ""  # 配置面尚无该字段
    assert resolver(SimpleNamespace(bot_web_search_tavily_time_range="")) == ""


def test_resolver_passes_through_configured_value() -> None:
    resolver = _resolver()
    assert resolver(SimpleNamespace(bot_web_search_tavily_time_range="month")) == "month"


# --------------------------------------------------------------------------- #
# 反锁腿（两态皆绿）：现状保真——装配接线缺省不通电
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
    # 生产 Config 的 HEAD 缺省值：字段在、值为空 ⇒ 功能必须仍不通电。
    "bot_web_search_tavily_time_range": "",
}


def _cfg(**overrides: object) -> SimpleNamespace:
    return SimpleNamespace(**{**_BASE_CONFIG, **overrides})


def test_default_configured_chain_carries_no_latest_window() -> None:
    chain = web_search._build_chained_provider(3.0, "", config=_cfg())
    assert getattr(chain, "_latest_time_range", "") == ""


def test_configured_chain_with_value_wires_latest_window() -> None:
    # HEAD 红（无该属性接线）；叠补丁绿：值从唯一读点接进链。
    chain = web_search._build_chained_provider(
        3.0, "", config=_cfg(bot_web_search_tavily_time_range="week")
    )
    assert getattr(chain, "_latest_time_range", None) == "week"


def test_keyfree_default_branch_stays_byte_faithful() -> None:
    # config=None 的免 key 兜底链不接该层（DDG/Bing 日期参数属待裁 W-5）。
    chain = web_search._build_chained_provider(3.0, "")
    assert getattr(chain, "_latest_time_range", "") == ""


def test_chain_without_latest_kwarg_never_injects() -> None:
    # 现状保真反锁：不传 latest_time_range 的旧构造 ⇒ 逐字节现状（两态皆绿）。
    stub = _StubTavily()
    _chain([stub]).search(LATEST_QUERY, max_results=3)
    assert stub.calls == [None]
