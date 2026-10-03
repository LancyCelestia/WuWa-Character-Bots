"""Wave 1 剩余通电点判定锚（SEAT-S-W1B 席）：search.web「不等值不硬翻」证明 + files.read 我方零直呼证明。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §4 Wave1；
判定全录 ``.superpowers/sdd/2026-09-21-unify-wave/logs/SEAT-S-W1B.md`` §贰。
复用 U2 席 v1 门函数（组合复用，不复制第二套扫描器）。

性质=「现状钉」：backend_unit 若改走 invoker 适配器，现 descriptor 下必丢
``web_search_provider:<name>`` 审计（锚 1）、每次 invoke 冷启动重建 provider 废掉
600s TTL 查询缓存（锚 2）、provider.fetch_page_text 无中央对位能力（锚 3）。
将来主会话补齐缺件并推翻本判定时，相关用例红→先读 SEAT-S-W1B 再动判据，
不许静默放宽。files.read 面：domains/files/** 实测零执行直呼（锚 4），
brief 所指靶全在 root/control_plane——本件同时钉住该事实防再次考古。

全离线：检索真身全部 monkeypatch 为确定性替身，零网络、零消息发送。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 复用 v1 门的扫描器与真树索引（同目录顶层导入，pytest 已把 tests/ 放上 sys.path）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestration_callsite_single as v1gate


def _hit(title: str = "守岸人设定", snippet: str = "泰缇斯第二实例", url: str = "https://example.com/a"):
    return SimpleNamespace(title=title, snippet=snippet, url=url, source_domain="example.com")


class _FakeProvider:
    """非 Null 的检索替身：记录调用、返回固定单命中。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_results: int = 8):
        self.calls.append((query, max_results))
        return [_hit()]


# ---------------------------------------------------------------------------
# 锚 0：前提核实——search/files 族 descriptor 确在册（简报「已在册」属实才继续谈翻点）
# ---------------------------------------------------------------------------
def test_family_descriptors_are_registered() -> None:
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CAPABILITY_DESCRIPTOR,
    )

    ids = set(CAPABILITY_DESCRIPTOR)
    assert "search.web" in ids
    assert {
        "files.read.word",
        "files.read.ppt",
        "files.read.excel",
        "files.read.pdf",
        "files.read.code",
        "files.read.markdown",
        "files.read.latex",
    } <= ids, "files.read 族成员缺登——壳与 ledger 的前提塌了"


# ---------------------------------------------------------------------------
# 锚 1：OK data 无引擎归因面 ⇒ chat.py:3538 的 web_search_provider:<name> 审计必丢
# ---------------------------------------------------------------------------
def test_search_web_ok_payload_carries_no_provider_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.core.search import web_search
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    monkeypatch.setattr(web_search, "build_web_search_provider", lambda config=None: _FakeProvider())
    result = default_invoker().invoke(
        CapabilityRequest(
            capability_id="search.web",
            payload={"query": "守岸人", "max_results": 8},
            principal="u",
            roles=("user",),
            context={"config": SimpleNamespace(bot_web_search_enabled=True)},
        )
    )
    assert result.status is InvocationStatus.OK
    # 归因键若存在（provider_name / last_provider_name），backend_unit 的适配器翻点就有救；
    # 现状=不存在 ⇒ §贰-1 判「不等值」的唯一豁免通道是主会话给 descriptor 补件。
    assert set(result.data) == {"hits"}, f"壳 data 键面漂移（判定锚前提）：{sorted(result.data)}"
    assert all(set(hit) == {"title", "snippet", "url", "source_domain"} for hit in result.data["hits"])


# ---------------------------------------------------------------------------
# 锚 2：壳每次 invoke 当场重建 provider ⇒ 真身实例级 600s TTL 缓存（web_search.py:461）永冷
# ---------------------------------------------------------------------------
def test_search_web_shell_rebuilds_provider_every_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.core.search import web_search
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        default_invoker,
    )

    built: list[_FakeProvider] = []

    def _counting_build(config: object | None = None) -> _FakeProvider:
        prov = _FakeProvider()
        built.append(prov)
        return prov

    monkeypatch.setattr(web_search, "build_web_search_provider", _counting_build)
    req = CapabilityRequest(
        capability_id="search.web",
        payload={"query": "同一问题", "max_results": 8},
        principal="u",
        roles=("user",),
        context={"config": SimpleNamespace(bot_web_search_enabled=True)},
    )
    invoker = default_invoker()
    invoker.invoke(req)
    invoker.invoke(req)  # 同 query 同 max_results：直呼路径第二次吃 TTL 缓存零引擎消耗
    assert len(built) == 2, (
        "壳的『每调重建』被改掉——§贰-2 差异面收窄，可重评 backend_unit 翻点（先读 SEAT-S-W1B 再动）"
    )
    assert [len(p.calls) for p in built] == [1, 1]


# ---------------------------------------------------------------------------
# 锚 3：真身 provider 带 fetch_page_text（chat.py:3301 优先用），中央无任何能力覆盖该契约
# ---------------------------------------------------------------------------
def test_search_family_has_no_page_fetch_counterpart_for_provider_fetch() -> None:
    from plugins.bot_unified_runtime.domains.core.search import web_search
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CAPABILITY_DESCRIPTOR,
    )

    assert hasattr(web_search.ChainedWebSearchProvider, "fetch_page_text"), "真身契约面变了，重读 SEAT-S-W1B §贰-3"
    refs = {
        cid: reg.handler_ref
        for cid, reg in CAPABILITY_DESCRIPTOR.items()
        if cid.startswith("search.")
    }
    # search.reference.fetch 走 citation_id 白名单语义（search_service#fetch_reference），
    # 不是 provider.fetch_page_text（任意 URL + proxy/timeout/max_chars）的对位中央件。
    assert not any("fetch_page_text" in ref for ref in refs.values()), (
        f"中央出现 fetch_page_text 对位件——§贰-3 差异解除，重评翻点：{refs}"
    )


# ---------------------------------------------------------------------------
# 锚 4：domains/files/** 生产执行直呼=零（简报「files.read 族直呼在 domains/files 内」被实测推翻）
# ---------------------------------------------------------------------------
def test_files_domain_has_zero_execution_direct_sites() -> None:
    direct, _invoker = v1gate.scan(v1gate._load_real_index())
    in_files_domain = {m for m in direct["files.read"] if m.startswith("domains/files/")}
    assert in_files_domain == set(), f"files 域内出现新执行直呼点（清点表 A 失效，重跑 §一）：{in_files_domain}"
    # ledger 现行 files.read 直呼面＝root、控制面两端点 + 邮件附件取字
    # （mail_ingress_files.py `_read_one`，2026-10-03 S31 评审登记：与 QQ/TG 同一颗
    # file_reader 咽喉的有意直读），三处均非本席可翻面。
    assert direct["files.read"] == v1gate.KNOWN_DIRECT_ALLOWLIST["files.read"]
