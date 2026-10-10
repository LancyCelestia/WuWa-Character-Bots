"""转发聊天记录回归：入站放行 + 回执解析容忍度（评审：转发无回应根因）。

    PYTHONDONTWRITEBYTECODE=1 python -m pytest tests/test_forward_message_ingest.py -q

根因：合并转发消息的 plain_text **为空**，且转发段既不属于视觉段也不属于音频段
→ 路由判 IGNORE → chat handler 不触发 → 抓转发正文的代码（在 handler 内部）
永远跑不到。表现为"转发聊天记录给 bot 毫无回应"，且日志无痕（旧实现把
get_forward_msg 的异常全吞掉）。
"""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from plugins.bot_unified_runtime import (
    _FORWARD_MESSAGE_API_TIMEOUT_SECONDS,
    _FORWARD_NESTED_MAX_DEPTH,
    _FORWARD_NESTED_MAX_TOTAL,
    FORWARD_SEGMENT_TYPES,
    _collect_nested_forward_ids,
    _forward_message_text,
    _forward_message_text_sync,
    _forward_segment_id,
    contains_audio_message_segments,
    contains_forward_message_segments,
    contains_visual_message_segments,
)

# ------------------------------------------------------------------ 入站放行


def test_forward_segment_is_detected() -> None:
    assert contains_forward_message_segments([{"type": "forward", "data": {"id": "x"}}]) is True


def test_forward_segment_aliases_detected() -> None:
    for kind in ("chat_history", "messages"):
        assert contains_forward_message_segments([{"type": kind, "data": {}}]) is True, kind


def test_forward_is_not_visual_or_audio() -> None:
    """转发段必须与视觉/音频区分——否则门禁逻辑会把语义混在一起。"""
    segments = [{"type": "forward", "data": {"id": "x"}}]
    assert contains_visual_message_segments(segments) is False
    assert contains_audio_message_segments(segments) is False


def test_non_forward_segments_not_flagged() -> None:
    for segments in ([], None, [{"type": "text", "data": {"text": "hi"}}]):
        assert contains_forward_message_segments(segments) is False


def test_forward_segment_types_cover_known_forms() -> None:
    assert {"forward", "chat_history", "messages"} <= set(FORWARD_SEGMENT_TYPES)


# --------------------------------------------------------------- 回执解析


def test_parse_canonical_shape() -> None:
    """标准形态：messages[*].message[*].data.text，并带上发送者昵称。"""
    payload = {
        "messages": [
            {
                "sender": {"nickname": "甲"},
                "message": [
                    {"type": "text", "data": {"text": "第一句"}},
                    {"type": "text", "data": {"text": "第二句"}},
                ],
            }
        ]
    }
    text = _forward_message_text_sync(payload)
    assert "甲" in text
    assert "第一句" in text and "第二句" in text


def test_parse_data_wrapper_shape() -> None:
    """有些实现把业务数据包在 data 里。"""
    payload = {"data": {"messages": [{"sender": {"card": "乙"}, "message": [
        {"type": "text", "data": {"text": "在吗"}}]}]}}
    assert "在吗" in _forward_message_text_sync(payload)


def test_parse_sender_card_preferred_over_nickname() -> None:
    payload = {"messages": [{"sender": {"card": "群名片", "nickname": "昵称"},
                             "message": [{"type": "text", "data": {"text": "x"}}]}]}
    assert "群名片" in _forward_message_text_sync(payload)


def test_parse_media_labels_kept() -> None:
    """转发里的图片/语音/视频至少要留下标签，不能整段丢。"""
    payload = {
        "messages": [
            {
                "sender": {"nickname": "丙"},
                "message": [
                    {"type": "image", "data": {}},
                    {"type": "record", "data": {}},
                    {"type": "video", "data": {}},
                ],
            }
        ]
    }
    text = _forward_message_text_sync(payload)
    assert "[图片]" in text and "[语音]" in text and "[视频]" in text


def test_parse_returns_empty_on_unknown_shape() -> None:
    for payload in (None, {}, [], {"messages": "not-a-list"}, {"unexpected": 1}):
        assert _forward_message_text_sync(payload) == ""


# ------------------------------------------------------------- 异步 + 可观测


class _FakeBot:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **payload):
        self.calls.append((api, payload))
        if self.error is not None:
            raise self.error
        return self.result


class _Event:
    def __init__(self, segments) -> None:
        self._segments = segments

    def get_message(self):
        return self._segments


def test_async_fetch_uses_get_forward_msg_with_segment_id() -> None:
    bot = _FakeBot({"messages": [{"sender": {"nickname": "甲"},
                                  "message": [{"type": "text", "data": {"text": "hi"}}]}]})
    event = _Event([{"type": "forward", "data": {"id": "FWD-1"}}])
    text = asyncio.run(_forward_message_text(bot, event))
    assert "hi" in text
    assert bot.calls == [("get_forward_msg", {"message_id": "FWD-1"})]


def test_async_fetch_no_segment_means_no_api_call() -> None:
    """非转发消息不得触发 get_forward_msg（NapCat 时期普通 id 会被拒绝）。"""
    bot = _FakeBot({})
    event = _Event([{"type": "text", "data": {"text": "普通消息"}}])
    assert asyncio.run(_forward_message_text(bot, event)) == ""
    assert bot.calls == []


def test_async_fetch_survives_api_error() -> None:
    """上游报错必须降级为空串（不抛），否则整条消息处理会被打断。"""
    bot = _FakeBot(error=RuntimeError("get_forward_msg rejected"))
    event = _Event([{"type": "forward", "data": {"id": "FWD-2"}}])
    assert asyncio.run(_forward_message_text(bot, event)) == ""


def test_async_fetch_reports_empty_payload(caplog) -> None:
    """回执解析不出正文时要留 warning（旧实现静默无痕，是本次排查困难的根因）。"""
    import logging

    bot = _FakeBot({"unexpected": True})
    event = _Event([{"type": "forward", "data": {"id": "FWD-3"}}])
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(_forward_message_text(bot, event)) == ""
    assert any("no text" in record.message for record in caplog.records)


# ------------------------------------------------- 多层嵌套转发递归展开
# 2026-09-18 核心链路排查：旧实现 `nested_ids[:4]` 只展开**一层**，且对更深层
# 不再递归——"转发里再转发"的聊天记录内容整段丢失（用户实测「递归子记录
# 读不了」）。下列用例锁定新的递归语义：按深度展开 + 环引用终止。


class _RoutedBot:
    """按 message_id 返回不同回执的假 bot（多层嵌套场景专用）。"""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    async def call_api(self, api: str, **payload):
        self.calls.append((api, payload))
        return self.routes.get(str(payload.get("message_id")), {})


def _fwd_message(nested_id: str, text: str = "") -> list[dict]:
    segments: list[dict] = []
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    if nested_id:
        segments.append({"type": "forward", "data": {"id": nested_id}})
    return segments


def test_async_fetch_expands_deeply_nested_forwards() -> None:
    """三层嵌套转发必须逐层展开（旧实现只到第一层，深层内容丢失）。"""
    routes = {
        "L1": {"messages": [{"sender": {"nickname": "甲"}, "message": _fwd_message("L2", "第一层")}]},
        "L2": {"messages": [{"sender": {"nickname": "乙"}, "message": _fwd_message("L3", "第二层")}]},
        "L3": {"messages": [{"sender": {"nickname": "丙"}, "message": _fwd_message("", "第三层")}]},
    }
    bot = _RoutedBot(routes)
    event = _Event([{"type": "forward", "data": {"id": "L1"}}])
    text = asyncio.run(_forward_message_text(bot, event))
    assert "第一层" in text
    assert "第二层" in text, "嵌套第二层必须展开"
    assert "第三层" in text, "嵌套第三层必须展开（旧实现止于第一层）"
    assert [call[1]["message_id"] for call in bot.calls] == ["L1", "L2", "L3"]


def test_async_fetch_terminates_on_forward_cycle() -> None:
    """A→B→A 互引必须被去重拦住，不得无限递归。"""
    routes = {
        "A": {"messages": [{"sender": {}, "message": _fwd_message("B")}]},
        "B": {"messages": [{"sender": {}, "message": _fwd_message("A")}]},
    }
    bot = _RoutedBot(routes)
    event = _Event([{"type": "forward", "data": {"id": "A"}}])
    asyncio.run(_forward_message_text(bot, event))
    # 起点 A + 子节点 B；B 指向的 A 已见，必须终止（不产生第 3 次调用）。
    assert [call[1]["message_id"] for call in bot.calls] == ["A", "B"]


# ============================ 同层并发化（2026-10-11 席位 R，根链摄取段）========
# 待删的无用功：``_forward_message_text._expand`` 对本层 N 枚子转发 id 逐个
# ``await _fetch``。N 枚**同层** id 互不依赖（各自的 id 已躺在本层回执里，那是
# 引用链 5 层反查的形状，不在这里），成本＝N × SnowLuma ``get_forward_msg`` 往返。
# 改法＝**同层并发发起、按原序装配**；三道闸（seen 去重 / expanded_count 递增 /
# deadline）判定前置到发起前的一次同步遍历。
# 🔴 天花板与超时一个都没动：``_FORWARD_NESTED_MAX_DEPTH`` / ``_FORWARD_NESTED_MAX_TOTAL``
# / ``_FORWARD_MESSAGE_API_TIMEOUT_SECONDS`` / ``bot_forward_fetch_timeout_seconds``
# 全部原值（本文件末``test_forward_ceiling_constants_untouched`` 一枚锁钉死）。
#
# 本段四类腿：
#   ① 差分腿：并发版与**改前串行算法**（下方逐字转写的参照实现，勿改）在同一份
#      输入对象上输出**逐字节相等**——拼接次序、``—— 子转发 xxx ——`` 分节头、
#      失败段"保持原样"分支、空正文子转发不加分节头、长 id 截断、四层深度触底。
#   ② 墙钟 A/B：桩把每枚反查钉成固定 RTT（不打真网络），串行 N×RTT → 并发 1×RTT/层。
#   ③ 终止性/预算三枚锁：环引用、超 MAX_TOTAL、deadline 到点各一枚。
#   ④ 量尺自证（注毒）：把"发起前一次性判预算"改成"回调里判"⇒ ③ 的 MAX_TOTAL 锁
#      当场真红（内存内造违规，绝不写盘）。


async def _serial_reference_forward_text(bot: object, event: object, timeout_seconds: float | None = None) -> str:
    """**改前（串行）算法的逐字转写**——差分腿的参照尺，勿改（改了这条尺就废了）。

    转写自 2026-10-11 改动前的 ``_forward_message_text``（同工作区基线副本
    ``$TEMP/seatR-init-baseline.py`` 的 :1167-1246 段），只做了两处无害替换：
    ① 失败分支的 warning 不落日志而是进 ``_serial_reference_logs``（供逐条对序）；
    ② 主反查的 except 合并成一条（原实现分 TimeoutError/Exception 两支、两支都
    返回空串，语义一致）。递归主体（三道闸判定位置、``await _fetch`` 的串行形状、
    分节头拼接式）一字未动。
    """
    global _serial_reference_logs
    _serial_reference_logs = []
    forward_id = _forward_segment_id(event)
    if not forward_id:
        return ""
    call_api = getattr(bot, "call_api", None)
    if not callable(call_api):
        return ""
    per_call_timeout = float(timeout_seconds or _FORWARD_MESSAGE_API_TIMEOUT_SECONDS)
    deadline = time.monotonic() + per_call_timeout * (_FORWARD_NESTED_MAX_DEPTH + 1)
    seen: set[str] = {forward_id}
    expanded_count = 0

    async def _fetch(one_id: str) -> object:
        remaining = deadline - time.monotonic()
        return await asyncio.wait_for(
            call_api("get_forward_msg", message_id=one_id),
            timeout=max(0.5, min(per_call_timeout, remaining)),
        )

    async def _expand(one_id: str, payload: object, depth: int) -> str:
        nonlocal expanded_count
        body = _forward_message_text_sync(payload)
        if depth >= _FORWARD_NESTED_MAX_DEPTH:
            return body
        for nested_id in _collect_nested_forward_ids(payload):
            if expanded_count >= _FORWARD_NESTED_MAX_TOTAL or time.monotonic() >= deadline:
                break
            if nested_id in seen:
                continue  # 环引用/重复引用：同 id 只取一次。
            seen.add(nested_id)
            expanded_count += 1
            try:
                nested_result = await _fetch(nested_id)
            except Exception as exc:  # noqa: BLE001 - 子转发失败不阻断主正文。
                _serial_reference_logs.append(
                    f"nested forward fetch failed id={nested_id} "
                    f"type={type(exc).__name__} detail={str(exc)[:120]}"
                )
                continue
            nested_text = await _expand(nested_id, nested_result, depth + 1)
            if nested_text:
                body = (body + "\n" if body else "") + f"—— 子转发 {nested_id[:8]} ——\n{nested_text}"
        return body

    try:
        result = await _fetch(forward_id)
    except Exception:  # noqa: BLE001 - 主反查失败＝空正文（与真身两支同语义）。
        return ""
    return await _expand(forward_id, result, 0)


_serial_reference_logs: list[str] = []


class _DelayRoutedBot:
    """钉死每枚反查延迟的假 bot（绝不打真网络），并记三本账。

    ``calls``＝发起次序（append 在首个 await 之前 ⇒ 等于发起序）；
    ``max_inflight``＝同时在飞峰值（并发是否**真的**发生的唯一实证）；
    ``errors``＝按 id 注入异常（失败段"保持原样"分支）。
    """

    def __init__(
        self,
        routes: dict[str, object],
        *,
        delay: float = 0.0,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.routes = routes
        self.delay = delay
        self.errors = errors or {}
        self.calls: list[tuple[str, dict]] = []
        self.inflight = 0
        self.max_inflight = 0

    async def call_api(self, api: str, **payload):
        self.calls.append((api, payload))
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self.inflight -= 1
        error = self.errors.get(str(payload.get("message_id")))
        if error is not None:
            raise error
        return self.routes.get(str(payload.get("message_id")), {})

    @property
    def fetched_ids(self) -> list[str]:
        return [str(payload["message_id"]) for _api, payload in self.calls]


def _msg(text: str, nested_ids: list[str] | None = None, nickname: str = "甲") -> dict:
    """造一条转发回执消息：正文 + 若干同层子转发段（顺序＝拼接顺序的尺）。"""
    segments: list[dict] = []
    if text:
        segments.append({"type": "text", "data": {"text": text}})
    for nested_id in nested_ids or []:
        segments.append({"type": "forward", "data": {"id": nested_id}})
    return {"sender": {"nickname": nickname}, "message": segments}


def _leaf(text: str) -> dict:
    return {"messages": [_msg(text, nickname="叶")]}


def _node(text: str, child_ids: list[str]) -> dict:
    return {"messages": [_msg(text, child_ids)]}


# 场景表：每枚返回 (routes, root_id)。全部 ≤ MAX_TOTAL、不触 deadline，
# 故串行/并发两路的**节点集合**必然相同，可比对输出。
def _case_flat5() -> tuple[dict, str]:
    routes = {"ROOT": _node("根", [f"N{i}" for i in range(5)])}
    routes.update({f"N{i}": _leaf(f"叶{i}") for i in range(5)})
    return routes, "ROOT"


def _case_flat8_max_per_layer() -> tuple[dict, str]:
    """同层 8 枚＝``_collect_nested_forward_ids`` 的本层上限（未改），并发满开。"""
    routes = {"ROOT": _node("根", [f"N{i}" for i in range(8)])}
    routes.update({f"N{i}": _leaf(f"叶{i}") for i in range(8)})
    return routes, "ROOT"


def _case_multilayer_depth_cap() -> tuple[dict, str]:
    """四层链：第 4 层必须只剩 ``[合并转发:D]`` 占位符（深度闸原值 3，未动）。"""
    routes = {
        "ROOT": _node("根", ["A"]),
        "A": _node("第二层", ["B"]),
        "B": _node("第三层", ["C"]),
        "C": _node("第四层", ["D"]),
        "D": _leaf("第五层不该出现"),
    }
    return routes, "ROOT"


def _case_wide_multilayer() -> tuple[dict, str]:
    """多层多扇出：3 层、每层 3 枚，含分节头嵌套与跨层顺序。"""
    routes = {"ROOT": _node("根", ["A", "B", "C"])}
    routes.update({x: _node(f"{x}正文", [f"{x}1", f"{x}2", f"{x}3"]) for x in "ABC"})
    for x in "ABC":
        routes.update({f"{x}{i}": _leaf(f"{x}-{i}") for i in (1, 2, 3)})
    return routes, "ROOT"


def _case_empty_child() -> tuple[dict, str]:
    """子转发正文解析为空：不加分节头（两路都必须整段省略）。"""
    routes = {
        "ROOT": _node("根", ["E", "OK"]),
        "E": {"messages": []},
        "OK": _leaf("有正文"),
    }
    return routes, "ROOT"


def _case_same_layer_duplicate() -> tuple[dict, str]:
    """同层两处引用同一枚 id：``_collect_nested_forward_ids`` 保序去重后只 1 次。"""
    routes = {
        "ROOT": _node("根", ["X", "Y", "X"]),
        "X": _leaf("X 正文"),
        "Y": _leaf("Y 正文"),
    }
    return routes, "ROOT"


def _case_long_ids_truncated() -> tuple[dict, str]:
    """分节头按 ``[:8]`` 截断长 id（拼接式未动，逐字符比）。"""
    long_ids = [f"FWD-{i}-abcdefghijklmnop" for i in range(4)]
    routes = {"ROOT": _node("根", long_ids)}
    routes.update({lid: _leaf(f"正文{lid[:8]}") for lid in long_ids})
    return routes, "ROOT"


def _case_mixed_failure() -> tuple[dict, str]:
    """5 枚同层里 2 枚反查抛错：失败段保持原样、其余照拼，warning 逐条对序。"""
    routes = {"ROOT": _node("根", [f"N{i}" for i in range(5)])}
    routes.update({f"N{i}": _leaf(f"叶{i}") for i in range(5)})
    return routes, "ROOT"


_FORWARD_CASES = {
    "flat5": (_case_flat5, []),
    "flat8_max_per_layer": (_case_flat8_max_per_layer, []),
    "multilayer_depth_cap": (_case_multilayer_depth_cap, []),
    "wide_multilayer": (_case_wide_multilayer, []),
    "empty_child": (_case_empty_child, []),
    "same_layer_duplicate": (_case_same_layer_duplicate, []),
    "long_ids_truncated": (_case_long_ids_truncated, []),
    "mixed_failure": (_case_mixed_failure, ["N1", "N3"]),
}


def _nested_failure_logs(records) -> list[str]:
    return [
        r.getMessage()
        for r in records
        if r.getMessage().startswith("nested forward fetch failed")
    ]


@pytest.mark.parametrize("case_name", sorted(_FORWARD_CASES))
def test_concurrent_expand_is_byte_identical_to_serial_reference(case_name: str, caplog) -> None:
    """🔴 核心实证：并发版输出与改前串行版**逐字节相等**，同一份输入对象。

    两路各自跑一次，但喂的是**同一批 routes 对象**（转发展开不改动回执，
    故可安全共享；``_DelayRoutedBot`` 只读它）。比四件事：
    ① 最终 ``plain_text`` 整串全等（含拼接次序与分节头逐字符）；
    ② 实际被反查到的 id **集合**全等（节点选取不变）；
    ③ 失败段 warning 的**文本与先后次序**全等（串行版就地打、并发版装配段
       按原序补打，就是为了这一条）；
    ④ 同层内发起序＝候选列表原序（"并发发起"不等于"乱序发起"）。
    """
    build, failing_ids = _FORWARD_CASES[case_name]
    routes, root_id = build()
    errors = {fid: RuntimeError(f"boom-{fid}") for fid in failing_ids}
    event = _Event([{"type": "forward", "data": {"id": root_id}}])

    serial_bot = _DelayRoutedBot(routes, errors=errors)
    concurrent_bot = _DelayRoutedBot(routes, errors=errors)

    with caplog.at_level(logging.WARNING):
        serial_text = asyncio.run(_serial_reference_forward_text(serial_bot, event))
        serial_logs = list(_serial_reference_logs)
        mark = len(caplog.records)
        concurrent_text = asyncio.run(_forward_message_text(concurrent_bot, event))
        concurrent_logs = _nested_failure_logs(caplog.records[mark:])

    # ① 逐字节
    assert concurrent_text == serial_text, (
        f"{case_name}: 并发输出与串行参照不等\n--- serial ---\n{serial_text}\n--- concurrent ---\n{concurrent_text}"
    )
    # ② 节点集合（顺序两路本就可能不同：串行 DFS、并发按层批量发起）
    assert set(concurrent_bot.fetched_ids) == set(serial_bot.fetched_ids)
    assert len(concurrent_bot.fetched_ids) == len(serial_bot.fetched_ids)
    # ③ 失败段日志：文本与次序
    assert concurrent_logs == serial_logs, f"{case_name}: warning 次序/文本漂移"
    # ④ 同层发起序＝原序（主反查恒在首位）
    assert concurrent_bot.fetched_ids[0] == root_id


def test_concurrent_expand_launches_same_layer_ids_in_original_order() -> None:
    """同层 8 枚的**发起序必须＝回执里的原序**，且真的并发（峰值＝8 同时在飞）。"""
    routes, root_id = _case_flat8_max_per_layer()
    bot = _DelayRoutedBot(routes, delay=0.005)
    asyncio.run(_forward_message_text(bot, _Event([{"type": "forward", "data": {"id": root_id}}])))
    assert bot.fetched_ids == [root_id] + [f"N{i}" for i in range(8)], "发起序被打乱"
    assert bot.max_inflight == 8, f"没有并发：峰值在飞={bot.max_inflight}"


def _case_layer8_plus_three_grandchildren() -> tuple[dict, str]:
    """11 枚节点：本层 8 枚（满开），其中第一枚再带 3 枚孙。

    这是 ``_collect_nested_forward_ids`` 单层 8 枚上限（原值）＋
    ``_FORWARD_NESTED_MAX_TOTAL=12``（原值）两道闸下，"11 枚反查"能落成的形状：
    串行＝12 次往返（含主转发），并发＝3 层 × 1 次往返。
    """
    routes: dict[str, dict] = {"ROOT": _node("根", [f"N{i}" for i in range(8)])}
    routes.update({f"N{i}": _leaf(f"叶{i}") for i in range(8)})
    routes["N0"] = _node("叶0", ["G1", "G2", "G3"])
    routes.update({f"G{i}": _leaf(f"孙{i}") for i in (1, 2, 3)})
    return routes, "ROOT"


def test_concurrent_expand_wall_clock_collapses_n_rtts() -> None:
    """墙钟 A/B：每枚反查钉 25ms，串行 N×RTT vs 并发 1×RTT/层（不打真网络）。

    N=5＝单层 5 枚；N=11＝``_case_layer8_plus_three_grandchildren`` 的 11 枚节点。
    """
    rtt = 0.025
    shapes: dict[str, tuple[tuple[dict, str], int]] = {
        "N=5": (_case_flat5(), 5),
        "N=11": (_case_layer8_plus_three_grandchildren(), 11),
    }
    for shape_name, ((routes, root_id), expected_nodes) in shapes.items():
        event = _Event([{"type": "forward", "data": {"id": root_id}}])
        assert len([i for i in routes if i != root_id]) == expected_nodes

        serial_bot = _DelayRoutedBot(routes, delay=rtt)
        t0 = time.perf_counter()
        serial_text = asyncio.run(_serial_reference_forward_text(serial_bot, event))
        serial_wall = time.perf_counter() - t0

        concurrent_bot = _DelayRoutedBot(routes, delay=rtt)
        t0 = time.perf_counter()
        concurrent_text = asyncio.run(_forward_message_text(concurrent_bot, event))
        concurrent_wall = time.perf_counter() - t0

        assert concurrent_text == serial_text
        assert concurrent_bot.max_inflight > 1, "并发未发生"
        # 串行≈节点数×RTT，并发≈层数×RTT：至少砍到一半，且随 N 拉大。
        ratio = serial_wall / concurrent_wall
        print(
            f"[wallclock {shape_name}] rtt={rtt * 1000:.0f}ms "
            f"serial={serial_wall * 1000:.0f}ms concurrent={concurrent_wall * 1000:.0f}ms "
            f"ratio={ratio:.2f}x inflight={concurrent_bot.max_inflight} "
            f"fetches={len(concurrent_bot.calls)}"
        )
        assert ratio > 1.8, f"{shape_name}: 墙钟没塌下来 ratio={ratio:.2f}"


def test_nested_total_budget_is_not_enlarged_by_concurrency() -> None:
    """终止性/预算锁②：扇出爆表时，实际反查的**子节点数必须 ≤ MAX_TOTAL**。

    形状：根 8 枚，每枚再 8 枚孙（可用节点 8+64=72 枚，远超 12）。并发只改
    "何时发起"，不改"发几枚"——闸口在发起前的同步遍历里一次性判完，
    所以总数与串行版同一个天花板。
    """
    child_ids = [f"C{i}" for i in range(8)]
    routes = {"ROOT": _node("根", child_ids)}
    routes.update({cid: _node(f"{cid}正文", [f"{cid}-G{j}" for j in range(8)]) for cid in child_ids})
    routes.update(
        {
            f"{cid}-G{j}": _leaf(f"{cid}-G{j}")
            for cid in child_ids
            for j in range(8)
        }
    )
    bot = _DelayRoutedBot(routes)
    asyncio.run(_forward_message_text(bot, _Event([{"type": "forward", "data": {"id": "ROOT"}}])))
    nested_fetches = [i for i in bot.fetched_ids if i != "ROOT"]
    assert len(nested_fetches) <= _FORWARD_NESTED_MAX_TOTAL, (
        f"并发放大了预算：{len(nested_fetches)} > {_FORWARD_NESTED_MAX_TOTAL}"
    )
    # 恰好贴满天花板（说明闸在生效，不是"顺手少发"造绿）。
    assert len(nested_fetches) == _FORWARD_NESTED_MAX_TOTAL


def test_nested_deadline_stops_further_launches() -> None:
    """终止性/预算锁③：总预算（deadline）到点⇒ 本层**一枚都不再发起**，正文不塌。

    主转发用 tiny timeout 注入：假 bot 每枚睡 20ms，主反查回来后 deadline
    （timeout×(depth+1)）早已越过 ⇒ 发起前的判定当场 break，零子节点。
    """
    routes = {"ROOT": _node("根", [f"N{i}" for i in range(8)])}
    routes.update({f"N{i}": _leaf(f"叶{i}") for i in range(8)})
    bot = _DelayRoutedBot(routes, delay=0.02)
    event = _Event([{"type": "forward", "data": {"id": "ROOT"}}])
    text = asyncio.run(_forward_message_text(bot, event, timeout_seconds=0.001))
    assert bot.fetched_ids == ["ROOT"], f"deadline 后仍在发起：{bot.fetched_ids}"
    assert "根" in text, "主转发正文不得因预算到点而丢"
    assert "子转发" not in text


def test_nested_cycle_still_terminates_under_concurrency() -> None:
    """终止性/预算锁①：A↔B 互引＋同层重复引用，必须在 seen 去重处收敛。"""
    routes = {
        "A": _node("A", ["B", "B", "C"]),
        "B": _node("B", ["A", "A"]),
        "C": _node("C", ["A", "B"]),
    }
    bot = _DelayRoutedBot(routes)
    asyncio.run(_forward_message_text(bot, _Event([{"type": "forward", "data": {"id": "A"}}])))
    assert bot.fetched_ids == ["A", "B", "C"], f"去重失效/重复反查：{bot.fetched_ids}"
    assert len(set(bot.fetched_ids)) == len(bot.fetched_ids)


async def _poison_budget_check_moved_into_callback(bot: _DelayRoutedBot, root_id: str) -> list[str]:
    """注毒变体：形状照并发版，但把预算/deadline 判定从"发起前"挪进**回调里**。

    这正是本次改法要避开的形状——发起时不判，N 枚全部在飞后才判，天花板拦不住
    已经发出去的那批。本函数只为 ``test_total_budget_lock_has_teeth`` 服务，
    真身里没有这段逻辑（内存内造违规，绝不写盘）。
    """
    seen: set[str] = {root_id}
    fetched: list[str] = []

    async def _expand_layer(payload: object, depth: int) -> None:
        if depth >= _FORWARD_NESTED_MAX_DEPTH:
            return
        candidates = [nid for nid in _collect_nested_forward_ids(payload) if nid not in seen]
        for nid in candidates:
            seen.add(nid)

        async def _one(nested_id: str) -> None:
            # 🔴 判定被挪到回调里：下面这次 _fetch 发起时一行预算都没判。
            result = await bot.call_api("get_forward_msg", message_id=nested_id)
            fetched.append(nested_id)
            if len(fetched) >= _FORWARD_NESTED_MAX_TOTAL:
                return
            await _expand_layer(result, depth + 1)

        await asyncio.gather(*(_one(nid) for nid in candidates))

    root_payload = await bot.call_api("get_forward_msg", message_id=root_id)
    await _expand_layer(root_payload, 0)
    return fetched


def test_total_budget_lock_has_teeth_against_callback_side_poison() -> None:
    """量尺自证：同一份爆表扇出输入上，"回调里判预算"必突破 MAX_TOTAL。

    即：``test_nested_total_budget_is_not_enlarged_by_concurrency`` 不是摆设——
    真身判不过的那格，注毒变体一定判不过。
    """
    child_ids = [f"C{i}" for i in range(8)]
    routes = {"ROOT": _node("根", child_ids)}
    routes.update({cid: _node(f"{cid}正文", [f"{cid}-G{j}" for j in range(8)]) for cid in child_ids})
    routes.update(
        {f"{cid}-G{j}": _leaf(f"{cid}-G{j}") for cid in child_ids for j in range(8)}
    )
    poisoned = _DelayRoutedBot(routes)
    over_budget = asyncio.run(_poison_budget_check_moved_into_callback(poisoned, "ROOT"))
    assert len(over_budget) > _FORWARD_NESTED_MAX_TOTAL, (
        f"注毒未破预算（{len(over_budget)} 枚）⇒ 那把锁是瞎的"
    )

    real = _DelayRoutedBot(routes)
    asyncio.run(_forward_message_text(real, _Event([{"type": "forward", "data": {"id": "ROOT"}}])))
    assert len([i for i in real.fetched_ids if i != "ROOT"]) <= _FORWARD_NESTED_MAX_TOTAL


def test_forward_ceiling_constants_untouched() -> None:
    """天花板/超时原值锁：并发化不许顺手调任何一个上限，也不许新增配置键。"""
    import plugins.bot_unified_runtime as m
    from plugins.bot_unified_runtime.config import Config

    assert m._FORWARD_NESTED_MAX_DEPTH == 3
    assert m._FORWARD_NESTED_MAX_TOTAL == 12
    assert m._FORWARD_MESSAGE_API_TIMEOUT_SECONDS == 10.0
    assert Config().bot_forward_fetch_timeout_seconds == 5.0
    # 本层候选 id 上限 8 也是原值（在 _collect_nested_forward_ids 里）。
    ids = [f"I{i}" for i in range(20)]
    payload = {"messages": [_msg("根", ids)]}
    assert len(_collect_nested_forward_ids(payload)) == 8
