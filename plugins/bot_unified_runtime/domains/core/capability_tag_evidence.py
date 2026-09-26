"""capability_tag_evidence — 能力侧「原生标签」实测票根册（中央调度收编波 S68）。

## 为什么另起一件（防第二真身）
标签册 `capability_manifest.py` 的教义第 6 腿要求「声明了 `native-*` 的能力必须有
实测票根」，但它把票根读在自身的 `EVIDENCE` 里，而今天 `EVIDENCE` 只有一条**非原生**
（`media.tts.autodub/TTS`）、`FACETS` 里又**没有任何** `native-*` 声明 ⇒ 那条判据
分母恒为空、清空 `EVIDENCE` 也不红（S68 现算，见 SEAT-S68 §0/§1）。本件把这半条
判据的**数据面**独立出来，配一把**有扫描面地板**的门，使其不再真空。本件与 keystone
/ `capability_manifest.py` / `channel_capability_tags.py` 同哲学：**只声明数据、
不 import 任何包内模块**、零 I/O、零网络、模块级常量保持字面可 `ast.literal_eval`。

## 判据口径（钉死）
- 只有 `native-*` 标签需要票根；`tts` / `vision` / `image` / `media-read` 等非原生
  内容档不进本册（它们由别处真身执法，本册不越界）。
- 一条票根 = 一个 **(能力, 原生标签)** 对的一次**真跑过**的实测。判据来自用户
  2026-09-23 `/goal` 第 1 条第 6 腿：**HTTP 200 不算票根**——本仓实证 grok 对视频
  回 200 却自陈「没有附带任何视频」（`tests/test_native_av_input.py` 模块 docstring、
  AGENTS 台账 #50）。因此每条记录必须带**可复核字段**（请求线形 / 响应里可观测的
  理解证据 / 判定日期 / 判据来源），不得只填 "PASS" 或一个状态码。
- **宁可少声明，不可无票根声明**：至今没有能力侧实测凭据的原生标签一律不进本册
  （例 `native-vision`：聊天侧识图今天走 VLM 转译口、非主模型原生解码，无票根 ⇒
  不声明），并写进降级清单点名。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class NativeTagTicket:
    """一枚原生标签实测票根：所有字段都是给人复核用的、不得留空的硬事实。"""

    capability_id: str
    native_tag: str
    measured_channel: str
    request_shape: str
    response_evidence: str
    judged_at_utc: str
    criterion_source: str
    reproduced_command: str


#: 已知原生标签值（与 `capability_manifest.CapabilityTag` 的 `native-*` 成员同集合，
#: 由门交叉比对，禁在此抄一份会漂移的枚举）。
KNOWN_NATIVE_TAG_VALUES: Final[tuple[str, ...]] = (
    "native-animation",
    "native-audio",
    "native-video",
    "native-vision",
)

#: 消费原生输入（音频/视频/动图直接进模型）的能力单一落点。聊天链路是唯一把
#: `input_audio` / `video_url` / 动图 `image_url` 原样挂上请求体的消费者
#: （`build_direct_vision_messages` + `supports_native_media` 逐跳裁件）。
NATIVE_CONSUMER_CAPABILITY: Final[str] = "bot.chat"

#: 一条票根的"理解证据"字段最短可信长度；短于此即视为薄票根（只写 PASS 那一类）。
MIN_RESPONSE_EVIDENCE_LEN: Final[int] = 12

#: 代理式达标值黑名单（casefold 精确命中即红）：这些不是"实测"，是"我觉得能用"。
PROXY_ONLY_VALUES: Final[frozenset[str]] = frozenset(
    {
        "pass",
        "passed",
        "ok",
        "200",
        "http 200",
        "http200",
        "返回 200",
        "works",
        "supported",
        "支持",
        "可用",
        "能读",
        "看文档",
        "doc says yes",
    }
)

#: 票根册必填字段（任一为空 ⇒ 薄票根，门红）。
REVIEWABLE_FIELDS: Final[tuple[str, ...]] = (
    "capability_id",
    "native_tag",
    "measured_channel",
    "request_shape",
    "response_evidence",
    "judged_at_utc",
    "criterion_source",
    "reproduced_command",
)


def _t(
    capability_id: str,
    native_tag: str,
    measured_channel: str,
    request_shape: str,
    response_evidence: str,
    judged_at_utc: str,
    criterion_source: str,
    reproduced_command: str,
) -> NativeTagTicket:
    return NativeTagTicket(
        capability_id=capability_id,
        native_tag=native_tag,
        measured_channel=measured_channel,
        request_shape=request_shape,
        response_evidence=response_evidence,
        judged_at_utc=judged_at_utc,
        criterion_source=criterion_source,
        reproduced_command=reproduced_command,
    )


# 首批票根：三枚**真跑过**的原生输入实测（渠道 axon-gemini-38-flash，2026-09-23 实测，
# 记录落在 tests/test_native_av_input.py 模块 docstring + AGENTS 台账 #50）。判据
# "response_evidence" 写的是响应里可观测的理解证据，不是状态码。逐条对应
# `channel_capability_tags.CHANNEL_CAPABILITY_KINDS` 声明的三种 kind，不多不少。
_TICKETS: tuple[NativeTagTicket, ...] = (
    _t(
        NATIVE_CONSUMER_CAPABILITY,
        "native-audio",
        "axon-gemini-38-flash",
        "input_audio{format,data} base64（build_native_audio_part 产线形）",
        "响应正文逐字转写与源音频内容一致（模型确已收到并理解了音频）",
        "2026-09-23",
        "tests/test_native_av_input.py#(module docstring; 2026-09-23 实测)",
        "见 test_native_av_input 逐跳重放组 + AGENTS #50 实测记录（理解证据为"
        "当日主会话直连网关观测，非本仓离线用例可复算）",
    ),
    _t(
        NATIVE_CONSUMER_CAPABILITY,
        "native-video",
        "axon-gemini-38-flash",
        "video_url{url=data:video/mp4;base64}（build_native_video_part 产线形）",
        "响应正文准确描述了视频画面内容（模型确已看到视频）",
        "2026-09-23",
        "tests/test_native_av_input.py#(module docstring; 2026-09-23 实测)",
        "反面对照即本裁定的由来：grok 对 video_url 回 HTTP 200 却自陈没附带任何"
        "视频（薄票根形态），故状态码不得单独算票根",
    ),
    _t(
        NATIVE_CONSUMER_CAPABILITY,
        "native-animation",
        "axon-gemini-38-flash",
        "image_url{url=data:image/gif 或 http .mp4 动图容器}（keep_animation_raw）",
        "动图被原生接收而非只读首帧（响应覆盖到动画内容）",
        "2026-09-23",
        "tests/test_native_av_input.py#(S2/S40 用例; 2026-09-23/24 实测)",
        "反面对照：grok 收 image/gif 的 image_url 直接 400（not a valid JPG/PNG/"
        "WebP/ICO），故动图原生只在声明过的渠道上算数",
    ),
)

#: (capability_id, native_tag) -> 票根。键去重由构造保证（同键后写覆盖，禁重复申报）。
TICKETS: MappingProxyType[tuple[str, str], NativeTagTicket] = MappingProxyType(
    {(row.capability_id, row.native_tag): row for row in _TICKETS}
)

#: 扫描面地板（只准升）：此刻真跑过的原生票根枚数。**清空票根册 ⇒ 跌破地板 ⇒ 门红**，
#: 这是把"标签需票根"从真空接成真的那枚牙——它拦的是"把票根册清成空、判据分母归零、
#: 看起来合规"这一手（与 `test_capability_manifest_gate.py` 的 REGISTERED_FLOOR 同型）。
#: 手写 3（非派生表达式，守"反失明锁 基线必须手写字面量"）；增删一枚票根须同批复算改此值。
TICKETS_FLOOR: Final[int] = 3


def ticket_for(capability_id: str, native_tag: str) -> NativeTagTicket | None:
    return TICKETS.get((capability_id, native_tag))


def ticket_count() -> int:
    return len(TICKETS)


def native_kinds_with_tickets(capability_id: str = NATIVE_CONSUMER_CAPABILITY) -> frozenset[str]:
    """某能力已握有票根的原生 kind 集合（去 `native-` 前缀）。"""
    return frozenset(
        tag[len("native-") :]
        for (cid, tag) in TICKETS
        if cid == capability_id and tag.startswith("native-")
    )


def missing_reviewable_fields(ticket: NativeTagTicket) -> list[str]:
    """票根里为空的必填字段（正常应为空表；非空即薄票根）。"""
    return [name for name in REVIEWABLE_FIELDS if not str(getattr(ticket, name, "")).strip()]


def is_thin_response_evidence(response_evidence: str) -> bool:
    """响应证据是否薄到不能算票根：空白 / 代理式达标值 / 短于最短可信长度。"""
    text = str(response_evidence or "").strip()
    if not text:
        return True
    if text.casefold() in PROXY_ONLY_VALUES:
        return True
    return len(text) < MIN_RESPONSE_EVIDENCE_LEN


def declared_native_without_ticket(
    facets_tags: MappingProxyType[str, tuple[str, ...]],
    tickets: MappingProxyType[tuple[str, str], NativeTagTicket],
) -> list[str]:
    """纯谓词（供注毒直接打靶）：给定 {capability_id: (tag,...)}，返回
    「声明了 native-* 却无票根」的行。真数据下 `FACETS` 无原生声明 ⇒ 恒空，
    但门另有扫描面地板 + kind 覆盖两把真牙（见测试件）。"""
    return sorted(
        f"{cid}:{tag}"
        for cid, tags in facets_tags.items()
        for tag in tags
        if str(tag).startswith("native-") and (cid, tag) not in tickets
    )
