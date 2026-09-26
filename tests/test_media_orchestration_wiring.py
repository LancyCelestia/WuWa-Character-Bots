"""V1 席（媒体/TTS 全链接入中央调度层）· 媒体反搜经 invoker 的端到端等值 + 诚实锁。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1（D-b/D-d/D-e）、
§4 Wave 1「已包装能力通电」、§7 禁第三套。波约束见
``.superpowers/sdd/2026-09-21-unify-wave/master-plan.md``。

一句话——**接入的验收线是"行为逐字段等值"，不是"代码改了"**。本件把
``bot.image_search`` 的反搜执行从直呼真身 ``search_saucenao_ex`` 改为经
``CapabilityInvoker``（descriptor ``media.vision.anime_ip``），并用一份**冻结的旧行为快照**
（旧直呼 + 旧渲染器，逐字照抄迁移前实现）作对照，四种终态逐一比对呈现字段。

另含三条**诚实锁**：
- 未接线/中央拒绝 ⇒ 绝不产出"看起来成功"的命中卡（伪装成功即本件红）；
- descriptor 被摘 ⇒ invoke 回落 UNAVAILABLE、能力层不崩且真身**没有被偷偷直呼**（禁第二通路）；
- blocked 角色 ⇒ 中央权限门当场拒（证明接入门是活的，不是装饰）。

全离线：真身 ``search_saucenao_ex`` 全程 monkeypatch，零网络、零消息发送。
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.media.capabilities import image_search
from plugins.bot_unified_runtime.domains.media.search import sauce_search
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    InvocationResult,
    InvocationStatus,
)

#: 公网 IP 字面量（非 private/reserved）：中央 SSRF 门放行且**零 DNS**。
#: 实测教训（本席首跑）：`192.0.2.1` 看着是"文档地址"，但 Python
#: `ipaddress.IPv4Address("192.0.2.1").is_private` 为 **True**（IANA 特殊用途段），
#: 于是 `_guard_http_url` 在触达真身**之前**就拒 ⇒ 5 条等值用例同时红。
#: 这条红本身即"接入带来的新行为"的证据：SSRF 复核前移到 handler 门口。
_IMAGE_URL = "http://104.16.0.1/aa.png"


class _FakeHit:
    def __init__(self, similarity: float, title: str, member: str, url: str) -> None:
        self.similarity = similarity
        self.title = title
        self.member = member
        self.source = "danbooru"
        self.url = url


def _message(**overrides: Any) -> IncomingMessage:
    fields: dict[str, Any] = {
        "platform": "qq",
        "adapter": "onebot",
        "bot_id": "bot",
        "session_id": "session_1",
        "session_type": SessionType.PRIVATE,
        "sender_id": "10000",
        "sender_roles": ["user"],
        "plain_text": "搜图",
        "raw_segments": [{"type": "image", "data": {"url": _IMAGE_URL}}],
    }
    fields.update(overrides)
    return IncomingMessage(**fields)


class _Recorder:
    """真身替身：记录被调用次数（证明迁移后**没有**第二通路直呼它）。"""

    def __init__(self, hits: list[_FakeHit], error_kind: str) -> None:
        self._hits = hits
        self._error_kind = error_kind
        self.calls: list[str] = []

    def __call__(self, image_url: str, *, api_key: str = "", config: object | None = None):
        self.calls.append(image_url)
        return self._hits, self._error_kind


def _run_capability(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> CapabilityResult:
    monkeypatch.setattr(sauce_search, "search_saucenao_ex", recorder)
    # 旧实现此分支用 random.choice 抽池内模板：两侧共用同一确定性选择器，
    # 否则"等值"会被随机性污染（这里锁池内第一条，不是放宽判据）。
    monkeypatch.setattr(random, "choice", lambda seq: next(iter(seq)))
    capability = image_search.build_image_search_capability(config=None)
    return capability(_message(), None)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 冻结的旧行为快照（迁移前 __init__ 之前的实现逐字照抄，只作对照，不参与生产）
# ---------------------------------------------------------------------------
def _legacy_expected(message: IncomingMessage, recorder: _Recorder) -> dict[str, Any]:
    del message  # 旧直呼渲染器不读 message（只读真身返回），保留形参以对照旧调用形状
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import user_copy

    hits, error_kind = recorder(_IMAGE_URL)
    if error_kind == "no_key":
        return {
            "kind": "text",
            "body": "反搜服务还没配置 API key（SAUCENAO_API_KEY），暂时搜不了。",
            "url": None,
            "audit": ["image_search", "no_key"],
        }
    if error_kind == "http_error":
        return {
            "kind": "text",
            # 池内首条 == 被测侧被 patch 成 `lambda seq: next(iter(seq))` 的 random.choice 结果，
            # 这样"等值"才不被随机性污染（判据没放宽，只是把两侧选择器钉成同一个）。
            "body": next(iter(user_copy.DATASOURCE_FAILURE_TEMPLATES)).format(
                reason="反搜服务暂时连不上（SauceNAO 超时/拒绝）"
            ),
            "url": None,
            "audit": ["image_search", "service_error"],
        }
    if not hits:
        return {
            "kind": "text",
            "body": (
                "没有找到相似图源（图源站点未收录，或 QQ 图床链接被图源拒绝抓取；"
                "可以试试直接发原图文件再搜）。"
            ),
            "url": None,
            "audit": ["image_search", "not_found"],
        }
    lines = ["反搜结果（按相似度）："]
    for index, hit in enumerate(hits, start=1):
        line = f"{index}. {hit.similarity:.1f}%"
        if hit.title:
            line += f" {hit.title[:40]}"
        if hit.member:
            line += f"｜作者：{hit.member[:24]}"
        if hit.url:
            line += f"\n   {hit.url}"
        lines.append(line)
    return {
        "kind": "text",
        "body": "\n".join(lines),
        "url": hits[0].url or None,
        "audit": ["image_search", "saucenao"],
    }


@pytest.mark.parametrize(
    ("hits", "error_kind"),
    [
        ([_FakeHit(97.4, "守岸人 立绘", "artist_k", "https://ex/1.jpg")], ""),
        (
            [
                _FakeHit(88.0, "", "", ""),
                _FakeHit(61.25, "长标题" * 30, "作者名" * 20, "https://ex/2.jpg"),
            ],
            "",
        ),
        ([], ""),
        ([], "no_key"),
        ([], "http_error"),
    ],
    ids=["one-hit", "multi-hit-edge", "empty", "no-key", "http-error"],
)
def test_e2e_image_search_via_invoker_equals_legacy_direct(
    monkeypatch: pytest.MonkeyPatch, hits: list[_FakeHit], error_kind: str
) -> None:
    """经 invoker 的产出 == 直呼真身 + 旧渲染器（逐字段），且真身恰被调用一次。"""
    recorder = _Recorder(hits, error_kind)
    expected = _legacy_expected(_message(), recorder)
    recorder.calls.clear()

    result = _run_capability(monkeypatch, recorder)

    assert recorder.calls == [_IMAGE_URL], "真身调用次数/入参不等值（多调=走了第二通路，少调=没执行）"
    assert result.kind == expected["kind"]
    assert result.body == expected["body"]
    assert result.url == expected["url"]
    assert result.capability_id == "bot.image_search"
    # 审计：旧标签一条不少（新实现只能追加 orchestration:* 归因，不能丢旧口径）
    assert set(expected["audit"]) <= set(result.audit_tags)


# ---------------------------------------------------------------------------
# 诚实锁
# ---------------------------------------------------------------------------
def test_censored_status_never_fabricates_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒自证（伪装成功⇒本条红）：任何非 ok 终态都不得产出命中卡/带 url。"""

    def _fake_invoke(request: Any, *, config: Any = None) -> InvocationResult:
        return InvocationResult(
            capability_id=request.capability_id,
            status=InvocationStatus.DEGRADED,
            data={"hits": [{"similarity": 99.9, "title": "伪造", "url": "https://fake"}]},
            detail="degraded",
            via="sauce_search",
        )

    from plugins.bot_unified_runtime.runtime import capability_protocols

    class _FakeInvoker:
        invoke = staticmethod(_fake_invoke)

    monkeypatch.setattr(capability_protocols, "default_invoker", lambda: _FakeInvoker())
    recorder = _Recorder([], "")
    monkeypatch.setattr(sauce_search, "search_saucenao_ex", recorder)

    result = image_search.build_image_search_capability(config=None)(_message(), None)  # type: ignore[call-arg]

    assert recorder.calls == [], "非 ok 终态下真身仍被直呼 = 第二通路"
    assert "反搜结果" not in result.body, "降级态被伪装成命中卡"
    assert result.url is None
    assert "orchestration:degraded" in result.audit_tags


def test_descriptor_absent_falls_back_without_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """descriptor/handler 被摘（回落旧路未接）⇒ 能力层诚实不可用、不崩、不假称成功。"""
    from plugins.bot_unified_runtime.runtime import capability_protocols

    class _NoHandlerInvoker:
        def invoke(self, request: Any, *, config: Any = None) -> InvocationResult:
            # 中央信封不变量：非成功终态必须带诚实说明（缺 detail 会被 pydantic 当场拒）。
            return InvocationResult(
                capability_id=request.capability_id,
                status=InvocationStatus.UNAVAILABLE,
                detail="descriptor/handler 未在册（替身模拟回落未接）",
            )

    monkeypatch.setattr(capability_protocols, "default_invoker", lambda: _NoHandlerInvoker())
    recorder = _Recorder([], "")
    monkeypatch.setattr(sauce_search, "search_saucenao_ex", recorder)

    result = image_search.build_image_search_capability(config=None)(_message(), None)  # type: ignore[call-arg]

    assert recorder.calls == []
    assert "反搜结果" not in result.body
    assert "orchestration:unavailable" in result.audit_tags


def test_blocked_sender_is_denied_by_central_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """接入带来的中央权限门（旧直呼没有）：blocked 无条件拒，且真身一步未走。"""
    recorder = _Recorder([_FakeHit(90.0, "t", "m", "https://ex/1.jpg")], "")
    monkeypatch.setattr(sauce_search, "search_saucenao_ex", recorder)
    monkeypatch.setattr(random, "choice", lambda seq: next(iter(seq)))
    capability = image_search.build_image_search_capability(config=None)

    result = capability(_message(sender_roles=["blocked"]), None)  # type: ignore[call-arg]

    assert recorder.calls == [], "blocked 仍执行 = 中央权限门是装饰"
    assert "orchestration:denied" in result.audit_tags
    assert "反搜结果" not in result.body


# ---------------------------------------------------------------------------
# 在册事实锁（防"我域已包装能力"的口径被悄悄改写）
# ---------------------------------------------------------------------------
def test_media_descriptor_family_is_what_the_shell_says() -> None:
    """内容契约 8 枚 = 识图/OCR/反搜/ASR×2/视频×3（简报当年把 TTS 混进 media8 不成立，
    本条把实况钉住）；TTS 侧只准 `media.tts.autodub` 一枚在册——它是 VOICE-V12
    （2026-09-22）「自动配音产出步收编中央调度层」的交付：中央注册 + voice_enricher
    唯一 invoke 点 + `tests/test_descriptor_wiredness_ledger.py` 记 WIRED。
    再多一枚 TTS/voice descriptor 未经同规格接线即红（本锁仍是「哪句不准」的哨兵）。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CAPABILITY_DESCRIPTOR,
        CapabilityFamily,
        default_invoker,
    )

    registry = default_invoker().registry
    expected = {
        "media.vision.image",
        "media.vision.ocr",
        "media.vision.anime_ip",
        "media.asr.speech",
        "media.asr.audio_file",
        "media.video.recognize",
        "media.video.subtitle",
        "media.video.frame_extract",
    }
    live = {cid for cid in expected if registry.get(cid) is not None}
    assert live == expected, f"编排侧 media 族在册面漂移：缺 {sorted(expected - live)}"
    for cid in expected:
        assert registry.get(cid).family is CapabilityFamily.MEDIA  # type: ignore[union-attr]
    # 哨兵改判「只准这两枚 TTS descriptor，且必须真接线」：SEAT-V1 §柒 当年登记的
    # 「TTS 候选、未接线」状态已随 VOICE-V12 撤销——handler 在册、层 1 唯一 invoke 点在
    # domains/media/voice_enricher.py（现算：`media.tts.autodub` 的 handler 与描述符同源）。
    # S91（中央调度收编波）并入第二枚 `media.tts.autodub_transform`（结果变换形，S36 落件通电）：
    # 中央注册 descriptor+handler + 唯一 invoke 点同在 voice_enricher（按本哨兵"同规格完成接线
    # 并同步本锁"的明文指令更新名单，不是放宽判据）。
    tts_family = {
        cid for cid in CAPABILITY_DESCRIPTOR if cid.startswith(("media.tts", "media.voice"))
    }
    assert tts_family == {"media.tts.autodub", "media.tts.autodub_transform"}, (
        f"TTS/voice descriptor 面漂移（实得 {sorted(tts_family)}）——"
        "新增者须按 VOICE-V12 同规格完成接线并同步本锁，否则不许在册"
    )
    assert registry.get("media.tts.autodub").family is CapabilityFamily.MEDIA  # type: ignore[union-attr]
    assert (
        registry.get("media.tts.autodub_transform").family is CapabilityFamily.MEDIA  # type: ignore[union-attr]
    )
    assert default_invoker().handlers.get("media.tts.autodub_transform") is not None, (
        "第三形在册却无 handler＝在册未执法"
    )
    assert "search_saucenao_ex" in registry.get("media.vision.anime_ip").implementation_ref  # type: ignore[union-attr]
