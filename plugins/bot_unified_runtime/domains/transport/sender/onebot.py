from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from plugins.bot_unified_runtime.contracts import (
    DeliveryReceipt,
    OperationalIssue,
    ReceiptState,
    SendRequest,
    SessionType,
    new_debug_id,
)
from plugins.bot_unified_runtime.domains.transport.sender.file_gateway import (
    FileSource,
    FileTransferError,
    get_default_file_gateway,
)
from plugins.bot_unified_runtime.domains.transport.sender.timeout import (
    resolve_transport_timeout,
)
from plugins.bot_unified_runtime.runtime.deadline import (
    DeadlineExceeded,
    apply_request_deadline,
)

ONEBOT_V11_TRANSPORT = "onebot.v11"
logger = logging.getLogger(__name__)
# 网络抖动 / SnowLuma 重连窗口内的瞬时异常：短退避内联重试，3 次尝试后才报发送失败。
_ONEBOT_SEND_RETRY_DELAYS = (0.8, 1.6)
# B-7（管线检视 #10）：分片超时均分的每段下限。纯均分在段数多时会把每段压到
# 秒级以下（6 段 × 15s = 每段 2.5s），SnowLuma 单段瞬时变慢即整封误判
# result_unknown；每段至少给到单条消息标准超时。
_MIN_CHUNK_WAIT_SECONDS = 10.0
OneBotMessageSegment = dict[str, Any]
_FORWARD_API_UNAVAILABLE = object()
# §9.3：chunk 级 part 观测回报值（与 queue.py 的 PART_STATE_SENT/UNKNOWN 同值；
# worker 是唯一的桥接方，字符串契约由测试固定）。
PART_REPORT_SENT = "sent"
PART_REPORT_UNKNOWN = "unknown"
# part 观测回调：(part_index, state) -> None；state ∈ {PART_REPORT_SENT,
# PART_REPORT_UNKNOWN}。仅 chunks 分片路径回报；同一请求整体重试时会重复
# 回报（消费方按 part 键幂等落库）。
PartSink = Callable[[int, str], None]

# ---- B4b Tier1（2026-09-20）：送达核验开关（本地观测面）----
# 注入风格同 timeout.py：sender 层不 import config，装配期注入 getter。
# 配置键 bot_outbound_verify_enabled 归属 B4a/合流席（本席不改 config.py），
# 「provider ← config」的接线一行登记在 B4b-report §落地请求；未注入=关闭，
# 现状行为字节级不动。摘段观测**日志**不受本开关控制（纯观测零行为变更）。
_outbound_verify_provider: Callable[[], bool] | None = None


def set_outbound_verify_provider(provider: Callable[[], bool] | None) -> None:
    global _outbound_verify_provider
    _outbound_verify_provider = provider


def _outbound_verify_enabled() -> bool:
    if _outbound_verify_provider is None:
        return False
    try:
        return bool(_outbound_verify_provider())
    except Exception:  # noqa: BLE001 - 观测开关不得炸发送主链路：读不到=按关闭。
        return False


class OneBotV11SendBot(Protocol):
    """发送路径实际消费的最小能力面（仅两个 send 口）。

    B4b 分层说明：可选只读 get_msg 声明只进 OneBotV11Bot（核验对象的收窄
    面），本模块所有发送函数签名一律钉在本协议上——否则「声明只读查询口」
    这一零行为变更动作会把树上仅实现 send 口的 bot 替身（ops/smoke 自检
    FakeOneBot 等）在 mypy 结构检查里打成不兼容（typecheck 实跑抓到 5 处；
    规格瑕疵登记 B4b-report Concerns#2）。
    """

    async def send_private_msg(
        self,
        *,
        user_id: int | str,
        message: list[OneBotMessageSegment],
    ) -> Any: ...

    async def send_group_msg(
        self,
        *,
        group_id: int | str,
        message: list[OneBotMessageSegment],
    ) -> Any: ...


class OneBotV11Bot(OneBotV11SendBot, Protocol):
    """B4b Tier2-a（规格 §3.2 T2-a）：发送面 + 可选只读 ``get_msg`` 声明。

    仅声明、发送路径永不调用；消费侧（build_unknown_part_confirmer）一律鸭
    子探测 ``getattr(bot, "get_msg", None)``，实现端缺能力=静默不核验（与本
    模块 _call_optional_onebot_api 同风格），声明本身对发送行为零变更。
    SnowLuma 侧返回 schema/「不存在」形态未经真机回读，「明确不存在→False」
    判定被 _ONEBOT_GET_MSG_NOT_FOUND_PROVEN 取证锁死（B4b-report §待取证）。
    """

    async def get_msg(self, *, message_id: int | str) -> Any: ...


def _coerce_onebot_id(value: str) -> int | str:
    stripped = value.strip()
    if stripped.isdecimal():
        return int(stripped)
    return stripped


def _extract_message_id(result: Any) -> str | None:
    if isinstance(result, dict):
        message_id = result.get("message_id")
        if message_id is not None:
            return str(message_id)
        data = result.get("data")
        if isinstance(data, dict):
            nested_message_id = data.get("message_id")
            if nested_message_id is not None:
                return str(nested_message_id)
    message_id = getattr(result, "message_id", None)
    if message_id is not None:
        return str(message_id)
    return None


def _extract_onebot_retcode(result: Any) -> int | None:
    if isinstance(result, dict):
        raw_retcode = result.get("retcode")
    else:
        raw_retcode = getattr(result, "retcode", None)
    if isinstance(raw_retcode, int):
        return raw_retcode
    if isinstance(raw_retcode, str) and raw_retcode.strip().lstrip("-").isdigit():
        return int(raw_retcode)
    return None


def _extract_onebot_status(result: Any) -> str:
    if isinstance(result, dict):
        raw_status = result.get("status")
    else:
        raw_status = getattr(result, "status", None)
    return _string_value(raw_status).strip().lower()


def _onebot_result_is_success(result: Any) -> bool:
    status = _extract_onebot_status(result)
    retcode = _extract_onebot_retcode(result)
    if status in {"failed", "fail", "error"}:
        return False
    return retcode is None or retcode == 0


def _is_final_failure_retcode(retcode: int | None) -> bool:
    """「平台明确拒绝且重发必同败」白名单（T46-N1，2026-09-20 扩码）。

    SnowLuma 实回码（config-GJCFWjtq.js:907-910 枚举，report-T46 §3.5 /
    report-T55 §二.1）：1400=BAD_REQUEST（段校验失败/参数缺，重发必同败）、
    100=ACTION_FAILED（record 转码/上传失败重抛的兜底码）。两码入 final：
    确定性失败烧 3 轮重试纯属盲耗，且第 1 轮终态才能让 worker 的 W1 文本
    降级（_send_media_text_fallback_once）立即接住混排文字部件。
    已披露取舍：100 词面通用、可能裹暂态上游错——接受理由=SnowLuma 为
    唯一在役协议端、重发同败概率占优、W1 保文字兜底；若真机实证 100 高频
    裹暂态，回滚点=从集合摘除 100（1400 无此顾虑）。
    """
    if retcode is None:
        return False
    return retcode in {403, 404, 100, 1003, 1200, 1201, 1400, 1401, 1403, 1404}


def _exception_platform_rejection(exc: Exception) -> int | None:
    """探测「平台明确拒绝」形态的异常；返回 retcode，非拒绝形态返回 None。

    NoneBot 对平台失败回执（status=failed / retcode!=0）以 ActionFailed
    异常上抛，retcode 藏在 ``.info`` dict（生产 nonebot 2.5.0 实证：无
    .retcode 属性）。这类拒绝是**确定性**结果——同一请求重发同结果，内联
    0.8/1.6s 短退避对其无意义。2026-09-15 实弹事故：NapCat 时期
    ``retcode=-1 rich media transfer failed`` 被本层当瞬时异常内联重试 3 次，
    与队列级 3 次尝试相乘成 9 发/人的重试风暴（审计库三轮 3 连发实证）。
    鸭子类型探测，sender 层不引入 nonebot 依赖；NetworkError/超时/断连等
    瞬时异常无 ``.info.retcode`` 形态，返回 None 维持既有内联重试语义。
    """
    info = getattr(exc, "info", None)
    if not isinstance(info, dict):
        return None
    retcode = info.get("retcode")
    if isinstance(retcode, bool):
        return None
    if isinstance(retcode, int):
        return retcode
    if isinstance(retcode, str) and retcode.strip().lstrip("-").isdigit():
        return int(retcode)
    return None


def _onebot_issue(
    kind: str,
    *,
    retryable: bool,
    debug_id: str,
    attempts: int = 1,
) -> OperationalIssue:
    return OperationalIssue(
        stage="onebot",
        kind=kind,
        retryable=retryable,
        debug_id=debug_id,
        safe_summary=kind,
        attempts=max(1, attempts),
    )


# T46-N1 连带裁决（T78 席，2026-09-20）：retcode=1200 **终态化**，废除 R2
# （2026-09-17）的「1200=适配器无连接 → bot_unavailable 挂起 30 分钟」语义。
# 依据：SnowLuma 的 1200 只在「stream action dispatched without a sink」发射
# （INTERNAL_ERROR，config-GJCFWjtq.js:1440，report-T46 §3.5 / report-T55
# §二.1 实复核），与「适配器无连接」旧 NapCat 语义已漂移（该常量历史由来
# =unknown，零 git 历史可溯，report-T55 §二.2）；SnowLuma 下真断线由
# NoneBot ApiNotAvailable/NetworkError（无 .info.retcode）走瞬时异常内联
# 重试，不经过本码。对确定性的内部错误挂起 30 分钟（年龄上限兜底）比按
# 失败处理慢三个数量级，且终态化后 worker 的 W1 文本降级可立即接住混排
# 文字。曾在此定义的 _ONEBOT_API_UNAVAILABLE_RETCODE=1200 与
# _bot_unavailable_receipt 已随裁决删除；回滚点=恢复两者及下方三处拦截
# 分支（本提交前的 git 历史）。队列侧 bot_unavailable 挂起机制
# （queue._defer_for_bot_unavailable）保留作防御性基建，不随本裁决删除。



def build_onebot_message_segments(send_request: SendRequest) -> list[OneBotMessageSegment]:
    content = send_request.content
    segments = _segments_from_rendered_output(
        content_type=content.content_type,
        content_ref=content.content_ref,
        text_fallback=content.text_fallback,
        request_id=send_request.request_id,
    )
    return segments or [_text_segment(content.text_fallback)]


def _forward_messages(send_request: SendRequest) -> list[OneBotMessageSegment]:
    if send_request.content.content_type.strip().lower() != "forward":
        return []
    if not send_request.allow_forward:
        return []
    raw_messages = send_request.content.content_ref.get("messages")
    if raw_messages is None:
        raw_messages = send_request.content.content_ref.get("nodes")
    if not isinstance(raw_messages, list):
        return []
    return [message for message in raw_messages if isinstance(message, dict)]


def _segments_from_rendered_output(
    *,
    content_type: str,
    content_ref: dict[str, Any],
    text_fallback: str,
    request_id: str = "",
) -> list[OneBotMessageSegment]:
    normalized_type = content_type.strip().lower()
    if normalized_type == "text":
        return [_text_segment(_string_value(content_ref.get("text")) or text_fallback)]
    if normalized_type == "image":
        image_segment = _image_segment(content_ref)
        return [image_segment] if image_segment else [_text_segment(text_fallback)]
    if normalized_type == "card":
        card_segment = _json_card_segment(content_ref)
        return [card_segment] if card_segment else [_text_segment(text_fallback)]
    if normalized_type == "mixed":
        return _mixed_segments(content_ref, text_fallback=text_fallback, request_id=request_id)
    return [_text_segment(text_fallback)]


def _mixed_segment_plan(
    content_ref: dict[str, Any],
) -> tuple[int, list[OneBotMessageSegment], list[str]]:
    """mixed 构段唯一事实源：(计划 dict 项数, 构出的段, 被丢段类型名列表)。

    planned<0 表示 parts 非列表（不可观测形态，调用方直接文本回落）。
    非 dict 项不计入 planned 也不算丢段（与既有跳过语义一致，防误报）。
    丢段只记类型名——正文不进本函数返回值，观测链路（日志/审计）因此
    零正文外泄。构造失败判定只覆盖**本地**丢段；上游（协议端）摘段不在
    本层可见范围，见 B4b-report §待取证。
    """
    parts = content_ref.get("parts")
    if not isinstance(parts, list):
        return -1, [], []
    segments: list[OneBotMessageSegment] = []
    dropped_types: list[str] = []
    planned = 0
    for part in parts:
        if not isinstance(part, dict):
            continue
        planned += 1
        segment = _segment_from_mixed_part(part)
        if segment is not None:
            segments.append(segment)
        else:
            dropped_types.append(_string_value(part.get("type")).strip().lower() or "unknown")
    return planned, segments, dropped_types


def _mixed_segments(
    content_ref: dict[str, Any],
    *,
    text_fallback: str,
    request_id: str = "",
) -> list[OneBotMessageSegment]:
    """B4b Tier1-a/c：构段行为逐字节保持现状，只追加发前摘段可感知观测。

    返回值语义与改造前一致（``segments or [_text_segment(text_fallback)]``，
    parts 非列表直接回落）；新增的只有两条 warning 观测行（丢段明细/纯文本
    回落原因），日志本体无条件常开——纯观测零行为变更。
    """
    planned, segments, dropped_types = _mixed_segment_plan(content_ref)
    if planned < 0:
        return [_text_segment(text_fallback)]
    if dropped_types:
        logger.warning(
            "onebot mixed segment dropped request_id=%s debug_id=%s planned=%d sent=%d dropped_types=%s sent_types=%s",
            request_id,
            new_debug_id(),
            planned,
            len(segments),
            dropped_types,
            [str(segment.get("type")) for segment in segments],
        )
    if not segments:
        logger.warning(
            "onebot mixed segment build fell back to text request_id=%s reason=segment_build_fallback_text planned=%d",
            request_id,
            planned,
        )
    return segments or [_text_segment(text_fallback)]


def _segment_from_mixed_part(part: dict[str, Any]) -> OneBotMessageSegment | None:
    part_type = _string_value(part.get("type")).strip().lower()
    if part_type == "at":
        # OneBot V11 at 段：{"type":"at","data":{"qq":<qq>}}；qq=all 全体。
        qq = _string_value(part.get("qq")) or _string_value(
            (part.get("data") or {}).get("qq")
            if isinstance(part.get("data"), dict)
            else ""
        )
        return {"type": "at", "data": {"qq": qq}} if qq else None
    if part_type == "text":
        text = _string_value(part.get("text")) or _string_value(part.get("content"))
        return _text_segment(text) if text else None
    if part_type == "image":
        return _image_segment(part)
    if part_type == "card":
        return _json_card_segment(part)
    if part_type == "record":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        resolved = _resolve_local_file_ref(file_ref)
        if resolved is None:
            # M-38 闭合：死引用不出站（构段期跳过，进 dropped_types 观测）。
            return None
        return {"type": "record", "data": {"file": resolved}}
    if part_type == "video":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        resolved = _resolve_local_file_ref(file_ref)
        if resolved is None:
            return None
        data: dict[str, Any] = {"file": resolved}
        for key in ("cover", "thumb"):
            if part.get(key):
                data[key] = _string_value(part.get(key))
        return {"type": "video", "data": data}
    if part_type == "file":
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref:
            return None
        resolved = _resolve_local_file_ref(file_ref)
        if resolved is None:
            return None
        return {"type": "file", "data": {"file": resolved}}
    if part_type == "music":
        # CQ:music 卡片：{"type":"qq","id":"..."} 或 {"type":"163","id":"..."}
        music_type = _string_value(part.get("music_type"))
        music_id = _string_value(part.get("music_id"))
        if music_type and music_id:
            return {"type": "music", "data": {"type": music_type, "id": music_id}}
        return None
    return None


def _text_segment(text: str) -> OneBotMessageSegment:
    return {"type": "text", "data": {"text": text}}


# ---- M-38 闭合（T100，2026-09-20）：本地文件引用死活判定 ----
# 非本地文件引用前缀：协议端自取或内联载荷，本地存在性判定不适用。
_NON_LOCAL_REF_PREFIXES = ("http://", "https://", "file://", "base64://", "data:")


def _local_path_alive(path: Path) -> bool:
    """绝对路径死活判定：存在、是常规文件、非空（M-38 存在性+非空双门）。"""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _resolve_local_file_ref(file_ref: str) -> str | None:
    """本地文件引用解析；死引用返回 None（调用方跳过该部件，绝不出站）。

    M-38 闭合（T100）：不存在的绝对路径（含 0 字节空文件）原样透传会把
    死路径送上协议端——NapCat 时期静默摘段谎报 SENT、SnowLuma 整条拒发
    拖垮同消息文字部件（report-T97 M-38 残半判定）。现契约：
    - 方案前缀引用（http/https/file:// 等）→ 原样透传（协议端自取）；
    - 绝对路径：存活（存在 ∧ 是文件 ∧ 非空）→ resolve()；死 → None；
    - 相对路径：保持既有透传（CWD 依赖的不完整引用交平台侧裁决；T85
      冻结棘轮 R6 毒件机制依赖此口，范围边界见 report-T100 §偏差）；
    - 空串：原样返回（调用方门前已拦）。
    消费方：record/video/file 部件 None=构段期跳过；image 维持既有透传
    （09-15 W1 事故回归件以不存在的绝对路径构造「媒体在、平台拒」前提，
    闭合面不含 image，``_image_segment`` 内显式回退，见该处注释）。
    """
    if not file_ref:
        return file_ref
    if file_ref.startswith(_NON_LOCAL_REF_PREFIXES):
        return file_ref
    path = Path(file_ref)
    if path.is_absolute():
        if not _local_path_alive(path):
            return None
        return str(path.resolve())
    if path.exists():
        return str(path.resolve())
    return file_ref


def _image_segment(content_ref: dict[str, Any]) -> OneBotMessageSegment | None:
    file_ref = (
        _string_value(content_ref.get("file"))
        or _string_value(content_ref.get("url"))
        or _string_value(content_ref.get("path"))
    )
    if not file_ref:
        return None
    resolved = _resolve_local_file_ref(file_ref)
    if resolved is None:
        # M-38 闭合面=record/video/file 媒体附件族；image 维持既有透传：
        # 09-15 W1 事故回归件（test_media_rejection_retry_and_fallback）
        # 以不存在的绝对路径构造「媒体在、平台拒」前提，image 死引用闭合
        # 需连带重构该回归件前提，留待专席（report-T100 §偏差登记）。
        resolved = file_ref
    data: dict[str, Any] = {"file": resolved}
    for key in ("cache", "proxy", "timeout"):
        if key in content_ref and isinstance(content_ref[key], (bool, int, str)):
            data[key] = content_ref[key]
    return {"type": "image", "data": data}


def _json_card_segment(content_ref: dict[str, Any]) -> OneBotMessageSegment | None:
    raw_payload = (
        content_ref.get("onebot_json")
        if "onebot_json" in content_ref
        else content_ref.get("json")
    )
    if raw_payload is None:
        raw_payload = content_ref.get("data")
    if isinstance(raw_payload, (dict, list)):
        payload = json.dumps(raw_payload, ensure_ascii=False)
    else:
        payload = _string_value(raw_payload)
    if not payload:
        return None
    return {"type": "json", "data": {"data": payload}}


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


class _NonRetryableActionError(Exception):
    pass


class _ChunkRejectedError(Exception):
    """平台对某个 chunk 返回明确失败 retcode：该段**未送达**。

    与超时/断连的「结果未知」不同，retcode 拒绝是明确的失败——重发该段
    是安全的（规格 §9.3 验收场景 2）。多段整体路径下若此前段已送达，
    仍沿用「有副作用即不整体重投」→ result_unknown，由 send_onebot_v11
    统一裁决。
    """

    def __init__(self, retcode: int | None) -> None:
        super().__init__(f"chunk rejected retcode={retcode}")
        self.retcode = retcode


class _SendSideEffects:
    """记录本次发送已产生的对外副作用（已成功发出的 chunk/文件数）。

    供 send_onebot_v11 判断"整体重试是否安全"：一旦有副作用，从头重试
    会把已送达内容重发一遍。§9.3 起另记分片级 delivered/unknown 索引，
    供 part 级幂等恢复与观测使用。
    """

    __slots__ = ("count", "delivered_parts", "unknown_parts")

    def __init__(self) -> None:
        self.count = 0
        self.delivered_parts: list[int] = []
        self.unknown_parts: list[int] = []


class _TimeoutBudget:
    """把单次发送总超时按段数切分：每段独立 wait_for，总耗时受外层护栏约束。

    B-7（管线检视 #10）：每段下限钳到 _MIN_CHUNK_WAIT_SECONDS（单条消息
    标准超时）；外层整体 wait_for（send_onebot_v11）不变，继续兜住总
    预算——剩余预算低于下限时取剩余，极端全慢时仍按 result_unknown 终态。
    """

    __slots__ = ("_started", "_total")

    def __init__(self, total_seconds: float) -> None:
        self._total = max(0.001, float(total_seconds))
        self._started = time.monotonic()

    def slice_for(self, calls: int) -> float:
        remaining = self._total - (time.monotonic() - self._started)
        if remaining <= 0:
            raise asyncio.TimeoutError()
        per_call = self._total / max(1, int(calls))
        return min(max(per_call, _MIN_CHUNK_WAIT_SECONDS), remaining)


async def _send_file_parts(
    bot: OneBotV11SendBot,
    request: SendRequest,
    parts: list[dict[str, Any]],
    *,
    budget: _TimeoutBudget,
    progress: _SendSideEffects,
) -> Any:
    """Files require upload APIs, not unsupported CQ:file. Never retry a bundle
    after any side effect: a later failure must not resend a delivered file.

    B3 阶段 1：文件部件统一经 FileTransferGateway（stage → deliver）投递；
    上传参数、超时切片、副作用计数与失败分类（missing_file / upload_rejected /
    upload_failed_or_unknown / unsupported_file_target / upload_api_unavailable）
    自 ``FileTransferGateway._deliver_onebot`` 等价搬运，对外行为不变。
    """
    upload_parts = [part for part in parts if part.get("type") == "file"]
    # M17：mixed 内容里除 file 外的部件（图片/语音/视频）此前被**静默丢弃**，
    # 用户只收到附件与文案，媒体凭空消失。这里把它们按既有 CQ 组装路径单独
    # 发一轮（一次 API 调用），保持「有副作用即不再整体重试」的契约不变。
    extra_parts = [
        part
        for part in parts
        if isinstance(part, dict) and part.get("type") not in {"file", "text"}
    ]
    text = request.content.text_fallback
    calls = len(upload_parts) + (1 if text else 0) + (1 if extra_parts else 0)
    gateway = get_default_file_gateway()
    result: Any = None
    for part_index, part in enumerate(upload_parts):
        source = FileSource(
            source_kind="path",
            path=str(part.get("file") or ""),
            name=str(part.get("name") or ""),
        )
        try:
            ticket = gateway.stage(source, request_id=request.request_id)
            # 与旧实现一致：每个上传调用前按 (段数) 切一次超时预算。
            file_receipt = await gateway.deliver(
                bot,
                ticket,
                target=request,
                part_index=part_index,
                budget=budget.slice_for(calls),
            )
        except asyncio.TimeoutError:
            raise
        except FileTransferError as exc:
            # 失败分类字符串与既有 _NonRetryableActionError 逐字一致。
            raise _NonRetryableActionError(str(exc.kind)) from exc
        result = file_receipt.provider_result
        progress.count += 1
    # The short caption is sent only after every upload succeeded.
    if text:
        try:
            if request.target_scope is SessionType.GROUP:
                result = await asyncio.wait_for(
                    bot.send_group_msg(group_id=_coerce_onebot_id(request.target_id), message=[_text_segment(text)]),
                    timeout=budget.slice_for(calls),
                )
            else:
                result = await asyncio.wait_for(
                    bot.send_private_msg(user_id=_coerce_onebot_id(request.target_id), message=[_text_segment(text)]),
                    timeout=budget.slice_for(calls),
                )
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            raise _NonRetryableActionError("caption_failed_after_upload") from exc
        progress.count += 1
    # M17：上传与文案之后，再发一轮除 file/text 外的媒体部件（图片/语音/视频）。
    # 这些部件此前被丢弃；沿用 build_onebot_message_segments 的既有组装逻辑，
    # 避免与 CQ 转义/本地文件内联等规则重复实现。
    if extra_parts:
        media_only = request.content.model_copy(update={"content_ref": {"parts": extra_parts}})
        segments = build_onebot_message_segments(
            request.model_copy(update={"content": media_only})
        )
        if segments:
            try:
                if request.target_scope is SessionType.GROUP:
                    result = await asyncio.wait_for(
                        bot.send_group_msg(
                            group_id=_coerce_onebot_id(request.target_id),
                            message=segments,
                        ),
                        timeout=budget.slice_for(calls),
                    )
                else:
                    result = await asyncio.wait_for(
                        bot.send_private_msg(
                            user_id=_coerce_onebot_id(request.target_id),
                            message=segments,
                        ),
                        timeout=budget.slice_for(calls),
                    )
            except asyncio.TimeoutError:
                raise
            except Exception as exc:
                logger.warning(
                    "onebot mixed media parts failed after upload type=%s request_id=%s",
                    type(exc).__name__,
                    request.request_id,
                )
                raise _NonRetryableActionError("media_parts_failed_after_upload") from exc
            if not _onebot_result_is_success(result):
                # 与下面的 retcode 契约一致：已有副作用 → 不得整体重投。
                raise _NonRetryableActionError("media_parts_rejected_after_upload")
            progress.count += 1
    return result


async def _dispatch_onebot_send(
    bot: OneBotV11SendBot,
    send_request: SendRequest,
    *,
    budget: _TimeoutBudget,
    progress: _SendSideEffects,
    part_sink: PartSink | None = None,
) -> Any | DeliveryReceipt:
    """执行一次发送：返回 OneBot API 结果，或不可重试的 BLOCKED 回执。

    多段/多文件发送按段数切分超时预算，每段独立 wait_for；每成功发出
    一段就在 progress 记一次副作用，供上层判断能否安全整体重试。
    §9.3：chunks 路径每段成功/结果未知时经 part_sink 回报 part 观测，
    供上层做 part 级幂等落库；回报异常绝不影响发送主链路。
    """
    parts = send_request.content.content_ref.get("parts", [])
    if isinstance(parts, list) and any(isinstance(p, dict) and p.get("type") == "file" for p in parts):
        return await _send_file_parts(bot, send_request, parts, budget=budget, progress=progress)
    if send_request.content.content_type.strip().lower() == "chunks":
        raw_chunks = send_request.content.content_ref.get("chunks")
        chunks = (
            [str(item).strip() for item in raw_chunks if str(item).strip()]
            if isinstance(raw_chunks, list)
            else []
        )
        if not chunks:
            chunks = [send_request.content.text_fallback]
        if send_request.target_scope not in (SessionType.PRIVATE, SessionType.GROUP):
            debug_id = new_debug_id()
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.BLOCKED,
                transport=ONEBOT_V11_TRANSPORT,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "unsupported_target",
                    retryable=False,
                    debug_id=debug_id,
                ),
            )
        result = None
        for part_index, chunk in enumerate(chunks):
            segment = _text_segment(chunk)
            try:
                if send_request.target_scope is SessionType.PRIVATE:
                    result = await asyncio.wait_for(
                        bot.send_private_msg(
                            user_id=_coerce_onebot_id(send_request.target_id),
                            message=[segment],
                        ),
                        timeout=budget.slice_for(len(chunks)),
                    )
                else:
                    result = await asyncio.wait_for(
                        bot.send_group_msg(
                            group_id=_coerce_onebot_id(send_request.target_id),
                            message=[segment],
                        ),
                        timeout=budget.slice_for(len(chunks)),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # 结果未知（超时/断连/异常）：该 part 记 UNKNOWN 后按原样
                # 抛出，由上层沿用既有 result_unknown 语义终态化。
                progress.unknown_parts.append(part_index)
                if part_sink is not None:
                    _report_part_safely(part_sink, part_index, PART_REPORT_UNKNOWN)
                raise
            if not _onebot_result_is_success(result):
                # 平台明确拒绝该段：未送达，不计副作用（重发安全）。
                raise _ChunkRejectedError(_extract_onebot_retcode(result))
            progress.count += 1
            progress.delivered_parts.append(part_index)
            if part_sink is not None:
                _report_part_safely(part_sink, part_index, PART_REPORT_SENT)
        if result is None:
            raise RuntimeError("chunk transport returned no result")
    else:
        forward_result = await _try_send_forward_message(bot, send_request)
        if forward_result is not _FORWARD_API_UNAVAILABLE:
            result = forward_result
        elif send_request.target_scope not in (SessionType.PRIVATE, SessionType.GROUP):
            debug_id = new_debug_id()
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.BLOCKED,
                transport=ONEBOT_V11_TRANSPORT,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "unsupported_target",
                    retryable=False,
                    debug_id=debug_id,
                ),
            )
        else:
            segments = build_onebot_message_segments(send_request)
            # M-38 闭合（T100）：死引用部件已在构段期跳过。这里只处理两种
            # 残留形态：①死件是唯一内容（纯语音 `说 X` 无文字可保）→ 零
            # 派发直接终态失败，不靠平台退码、不凑空消息假成功（诚实边界，
            # R-16② 零自拼文案）；②混排尚有存活部件 → 照发，SENT 回执由
            # send_onebot_v11 挂 missing_file 留痕。
            dead_types = _mixed_dead_local_file_types(send_request)
            if dead_types and _segments_all_empty_text(segments):
                debug_id = new_debug_id()
                logger.warning(
                    "onebot send skipped dead local file only content types=%s request_id=%s debug_id=%s",
                    dead_types,
                    send_request.request_id,
                    debug_id,
                )
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "missing_file",
                        retryable=False,
                        debug_id=debug_id,
                    ),
                )
            if dead_types:
                logger.warning(
                    "onebot mixed dead local file part skipped types=%s request_id=%s",
                    dead_types,
                    send_request.request_id,
                )
            if send_request.target_scope is SessionType.PRIVATE:
                result = await bot.send_private_msg(
                    user_id=_coerce_onebot_id(send_request.target_id),
                    message=segments,
                )
            else:
                result = await bot.send_group_msg(
                    group_id=_coerce_onebot_id(send_request.target_id),
                    message=segments,
                )
        # M-63 A 案（G2-R1，2026-09-20）：mixed 整发分支补真副作用计数与
        # part 观测回报。mixed 语音此前零 count 零回报 ⇒「count==0 ⇒ 零副
        # 作用 ⇒ 可安全整发重投」恒真式 → 超时/断连盲重投（P0 根因，T55
        # §一③⑤）。成功后 count+=1 使前提变真；part_sink（纯观测钩子，
        # 生产现无消费方）对 mixed 各 part 回报 SENT。text/image/card/forward
        # 走同一分支：count 在单次调用形态下仅成功后有值（失败分类读不到），
        # 行为不变；_mixed_part_indexes 对非 mixed 内容返回空，零开销。
        progress.count += 1
        for part_index in _mixed_part_indexes(send_request):
            if part_sink is not None:
                _report_part_safely(part_sink, part_index, PART_REPORT_SENT)
    return result


def _report_part_safely(part_sink: PartSink, part_index: int, state: str) -> None:
    """part 观测回报：消费方异常绝不能反噬发送主链路。"""
    try:
        part_sink(part_index, state)
    except Exception:  # noqa: BLE001 - 观测是旁路，失败仅降级为无回报。
        logger.debug(
            "onebot part sink failed part_index=%s state=%s", part_index, state
        )


def _mixed_part_indexes(send_request: SendRequest) -> list[int]:
    """mixed 请求的 part 索引全集（worker 段级计划的键位对齐面）。

    仅 content_type="mixed" 且 content_ref["parts"] 为列表时返回
    0..len(parts)-1（含构段会被跳过的非 dict 项——计划键位=原始 parts
    位置，见 worker._chunk_part_plan mixed 分支）；其余内容返回空。
    """
    if send_request.content.content_type.strip().lower() != "mixed":
        return []
    parts = send_request.content.content_ref.get("parts")
    if not isinstance(parts, list):
        return []
    return list(range(len(parts)))


def _mixed_dead_local_file_types(send_request: SendRequest) -> list[str]:
    """mixed 部件中「绝对路径死引用」的类型名列表（M-38 观测/终败判定面）。

    与 ``_resolve_local_file_ref`` 同一判定（``_local_path_alive``），仅
    覆盖闭合面 record/video/file（image 维持既有透传，见
    ``_image_segment`` 注释）；非 mixed 恒空。用途：① 混排死件跳过后
    SENT 回执的 missing_file 留痕；② 「死件唯一内容、无文字可保」终败
    门。与构段判定同源，不会两说。
    """
    if send_request.content.content_type.strip().lower() != "mixed":
        return []
    parts = send_request.content.content_ref.get("parts")
    if not isinstance(parts, list):
        return []
    dead: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = _string_value(part.get("type")).strip().lower()
        if part_type not in {"record", "video", "file"}:
            continue
        file_ref = _string_value(part.get("file")) or _string_value(part.get("url"))
        if not file_ref or file_ref.startswith(_NON_LOCAL_REF_PREFIXES):
            continue
        path = Path(file_ref)
        if path.is_absolute() and not _local_path_alive(path):
            dead.append(part_type)
    return dead


def _segments_all_empty_text(segments: list[OneBotMessageSegment]) -> bool:
    """「死件跳过后已无任何可发内容」：空集或全为空文本段。

    纯语音 `说 X`（无 text part、text_fallback 空）死件形态下
    ``_mixed_segments`` 的空段文本兜底产出 [text ""]——按既有
    「segments or 文本兜底」契约不产空集，本判定把该形态拦成终态失败
    而非空消息假成功（诚实边界；R-16② 零自拼文案）。
    """
    if not segments:
        return True
    return all(
        str(segment.get("type")) == "text"
        and not str((segment.get("data") or {}).get("text") or "").strip()
        for segment in segments
    )


async def send_onebot_v11(
    bot: OneBotV11SendBot,
    send_request: SendRequest,
    *,
    timeout_seconds: float | None = None,
    part_sink: PartSink | None = None,
) -> DeliveryReceipt:
    result: Any = None
    last_error: Exception | None = None
    timeout = resolve_transport_timeout(timeout_seconds)
    try:
        timeout = apply_request_deadline(
            timeout, getattr(send_request, "deadline_monotonic", None)
        )
    except DeadlineExceeded:
        debug_id = new_debug_id()
        logger.warning(
            "onebot send skipped after request deadline request_id=%s debug_id=%s",
            send_request.request_id,
            debug_id,
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_FINAL,
            transport=ONEBOT_V11_TRANSPORT,
            public_message="",
            debug_id=debug_id,
            operational_issue=_onebot_issue(
                "deadline_exceeded",
                retryable=False,
                debug_id=debug_id,
            ),
        )
    for attempt in range(len(_ONEBOT_SEND_RETRY_DELAYS) + 1):
        progress = _SendSideEffects()
        budget = _TimeoutBudget(timeout)
        try:
            dispatch = _dispatch_onebot_send(
                bot,
                send_request,
                budget=budget,
                progress=progress,
                part_sink=part_sink,
            )
            dispatched = await asyncio.wait_for(dispatch, timeout=timeout)
            if isinstance(dispatched, DeliveryReceipt):
                return dispatched
            result = dispatched
            last_error = None
            break
        except asyncio.CancelledError:
            raise
        except _NonRetryableActionError as exc:
            debug_id = new_debug_id()
            logger.warning("onebot file delivery stopped kind=%s request_id=%s", str(exc), send_request.request_id)
            return DeliveryReceipt(request_id=send_request.request_id, state=ReceiptState.FAILED_FINAL,
                transport=ONEBOT_V11_TRANSPORT, public_message="", debug_id=debug_id,
                operational_issue=_onebot_issue(str(exc)[:48] or "file_delivery_failed_or_unknown", retryable=False, debug_id=debug_id))
        except _ChunkRejectedError as exc:
            # §9.3：被拒段未送达（明确失败）。若此前段已送达（多段整体路径），
            # 整体重试会重发已送达内容 → 沿用 result_unknown 终态；否则与既有
            # retcode_failure 分类一致（可重试，重发安全）。
            if progress.count > 0:
                debug_id = new_debug_id()
                logger.warning(
                    "onebot chunk rejected after partial delivery retcode=%s request_id=%s debug_id=%s",
                    exc.retcode,
                    send_request.request_id,
                    debug_id,
                )
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "result_unknown",
                        retryable=False,
                        debug_id=debug_id,
                        attempts=attempt + 1,
                    ),
                )
            debug_id = new_debug_id()
            state = (
                ReceiptState.FAILED_FINAL
                if _is_final_failure_retcode(exc.retcode)
                else ReceiptState.FAILED_RETRYABLE
            )
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=state,
                transport=ONEBOT_V11_TRANSPORT,
                provider_message_id=None,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "retcode_failure",
                    retryable=state is ReceiptState.FAILED_RETRYABLE,
                    debug_id=debug_id,
                ),
            )
        except asyncio.TimeoutError:
            # 审查 A-03：超时不再一刀切终态化。progress.count 是本次尝试
            # 已确认送达的 chunk/文件数——count==0 表示零内容送达，整发重试
            # 无重复投递风险，交回队列按既有重试/断点续发机制走（与下方
            # except Exception 分支的 count==0 语义对齐）；count>0 表示部分
            # 已送达，从头重发会重复投递，维持 result_unknown 终态不变。
            # public_message 保持为空：群聊失败静默是产品裁定，不随重试语义
            # 改变；运维可见性走 operational_issue → 队列 alerts 链
            # （runtime/alerts.notify_operational_issue，300s 抑制键含
            # stage/kind）。
            # M-63 A 案：mixed 超时=结果未知，part 观测按 UNKNOWN 回报
            # （纯观测；UNKNOWN 记账由 worker 段级分支按回执落库）。
            for part_index in _mixed_part_indexes(send_request):
                if part_sink is not None:
                    _report_part_safely(part_sink, part_index, PART_REPORT_UNKNOWN)
            if progress.count > 0:
                debug_id = new_debug_id()
                logger.warning(
                    "onebot send timed out after partial delivery side_effects=%d request_id=%s debug_id=%s",
                    progress.count,
                    send_request.request_id,
                    debug_id,
                )
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "result_unknown",
                        retryable=False,
                        debug_id=debug_id,
                        attempts=attempt + 1,
                    ),
                )
            debug_id = new_debug_id()
            logger.warning(
                "onebot send timed out zero_part_delivered=true will_retry=true request_id=%s debug_id=%s",
                send_request.request_id,
                debug_id,
            )
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.FAILED_RETRYABLE,
                transport=ONEBOT_V11_TRANSPORT,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "timeout_zero_part_delivered",
                    retryable=True,
                    debug_id=debug_id,
                    attempts=attempt + 1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 重试耗尽后统一转为可重试失败回执。
            # M-63 A 案：mixed 断连/异常=结果未知，part 观测按 UNKNOWN
            # 回报（同超时分支；chunks 路径已在 _dispatch_onebot_send 内
            # 逐段回报，本助手对非 mixed 内容为空操作）。
            for part_index in _mixed_part_indexes(send_request):
                if part_sink is not None:
                    _report_part_safely(part_sink, part_index, PART_REPORT_UNKNOWN)
            if progress.count > 0:
                # 部分内容已送达：从头重试会把已投递内容重发一遍，只能按
                # 结果未知终态处理（对齐超时路径的 result_unknown 语义）。
                debug_id = new_debug_id()
                logger.warning(
                    "onebot send aborted after partial delivery side_effects=%d type=%s request_id=%s debug_id=%s",
                    progress.count,
                    type(exc).__name__,
                    send_request.request_id,
                    debug_id,
                )
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=ReceiptState.FAILED_FINAL,
                    transport=ONEBOT_V11_TRANSPORT,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "result_unknown",
                        retryable=False,
                        debug_id=debug_id,
                        attempts=attempt + 1,
                    ),
                )
            rejection_retcode = _exception_platform_rejection(exc)
            if rejection_retcode is not None:
                # 平台明确拒绝（ActionFailed 形态，零副作用）：立即按
                # retcode_failure 回执交还队列级真退避（30s×2^n），不在本层
                # 内联 3 连发（2026-09-15 重试风暴根修，见
                # _exception_platform_rejection docstring）。与下方
                # 「返回 failed dict」分支同分类，两条失败形态语义归一。
                # （R2 的 retcode=1200 挂起例外已随 T46-N1 终态化裁决删除。）
                debug_id = new_debug_id()
                state = (
                    ReceiptState.FAILED_FINAL
                    if _is_final_failure_retcode(rejection_retcode)
                    else ReceiptState.FAILED_RETRYABLE
                )
                logger.warning(
                    "onebot send rejected by platform retcode=%s inline_retry_skipped=true request_id=%s debug_id=%s",
                    rejection_retcode,
                    send_request.request_id,
                    debug_id,
                )
                return DeliveryReceipt(
                    request_id=send_request.request_id,
                    state=state,
                    transport=ONEBOT_V11_TRANSPORT,
                    provider_message_id=None,
                    public_message="",
                    debug_id=debug_id,
                    operational_issue=_onebot_issue(
                        "retcode_failure",
                        retryable=state is ReceiptState.FAILED_RETRYABLE,
                        debug_id=debug_id,
                        attempts=attempt + 1,
                    ),
                )
            last_error = exc
            if attempt < len(_ONEBOT_SEND_RETRY_DELAYS):
                await asyncio.sleep(_ONEBOT_SEND_RETRY_DELAYS[attempt])
    if last_error is not None:
        debug_id = new_debug_id()
        logger.warning(
            "onebot send failed after retries type=%s debug_id=%s",
            type(last_error).__name__,
            debug_id,
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.FAILED_RETRYABLE,
            transport=ONEBOT_V11_TRANSPORT,
            public_message="",
            debug_id=debug_id,
            provider_message_id=None,
            operational_issue=_onebot_issue(
                "send_exception",
                retryable=True,
                debug_id=debug_id,
                attempts=len(_ONEBOT_SEND_RETRY_DELAYS) + 1,
            ),
        )

    if not _onebot_result_is_success(result):
        debug_id = new_debug_id()
        retcode = _extract_onebot_retcode(result)
        # （R2 的 retcode=1200 挂起例外已随 T46-N1 终态化裁决删除：1200 在
        # SnowLuma 下=INTERNAL_ERROR，按白名单走终态，见模块注释。）
        # M10：retcode 分支此前**无视 progress.count**，与异常分支
        # （见上方 `if progress.count > 0` 守卫）语义不一致。文件类投递里
        # 上传可能已经成功、只有 caption 的 retcode 失败，此时整条链路回到
        # 队列重试会**重新上传同一个文件**（max_attempts=3 → 最多 3 份）。
        # 只要本次尝试已产生副作用且不是明确的永久失败码，就按 result_unknown
        # 终态化——与 `_send_file_parts` 文档声明的「有副作用后绝不重投」一致。
        if progress.count > 0 and not _is_final_failure_retcode(retcode):
            logger.warning(
                "onebot send retcode failure after partial delivery side_effects=%d retcode=%s request_id=%s debug_id=%s",
                progress.count,
                retcode,
                send_request.request_id,
                debug_id,
            )
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.FAILED_FINAL,
                transport=ONEBOT_V11_TRANSPORT,
                provider_message_id=None,
                public_message="",
                debug_id=debug_id,
                operational_issue=_onebot_issue(
                    "result_unknown",
                    retryable=False,
                    debug_id=debug_id,
                    attempts=attempt + 1,
                ),
            )
        state = (
            ReceiptState.FAILED_FINAL
            if _is_final_failure_retcode(retcode)
            else ReceiptState.FAILED_RETRYABLE
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=state,
            transport=ONEBOT_V11_TRANSPORT,
            provider_message_id=None,
            public_message="",
            debug_id=debug_id,
            operational_issue=_onebot_issue(
                "retcode_failure",
                retryable=state is ReceiptState.FAILED_RETRYABLE,
                debug_id=debug_id,
            ),
        )

    # M-38 闭合（T100）：混排死引用部件已在构段期跳过、其余部件随本次
    # 派发送达——SENT 但挂 missing_file 留痕（复用 file_gateway 既有 kind
    # 族），运维面可见「语音缺席」而非无痕假全量。纯语音终败形态在
    # dispatch 门已零派发直接 FAILED_FINAL，不进本分支。
    dead_types = _mixed_dead_local_file_types(send_request)
    if dead_types:
        issue = _onebot_issue(
            "missing_file",
            retryable=False,
            debug_id=new_debug_id(),
        )
        return DeliveryReceipt(
            request_id=send_request.request_id,
            state=ReceiptState.SENT,
            transport=ONEBOT_V11_TRANSPORT,
            provider_message_id=_extract_message_id(result),
            public_message="sent",
            debug_id=issue.debug_id,
            operational_issue=issue,
        )

    # B4b Tier1-b（核验开关开 + mixed 本地丢段时）：SENT 回执追加观测性注记。
    # 只加 operational_issue，绝不改判 ReceiptState——本地丢段是既成事实
    # （段没了就是没了，重发不会更多），改判会触发重投风暴（worker「防重复
    # 投递优先于防漏发」裁定）。上层文案据 kind=segment_dropped_local 决定
    # 「语音可能未包含」类诚实措辞（D-7 最低满足面）。开关缺省关 ⇒ 走下方
    # 与现状逐字节一致的成功回执。
    if _outbound_verify_enabled():
        dropped_types = _mixed_dropped_types(send_request)
        if dropped_types:
            issue = _onebot_issue(
                "segment_dropped_local",
                retryable=False,
                debug_id=new_debug_id(),
            )
            return DeliveryReceipt(
                request_id=send_request.request_id,
                state=ReceiptState.SENT,
                transport=ONEBOT_V11_TRANSPORT,
                provider_message_id=_extract_message_id(result),
                public_message="sent",
                debug_id=issue.debug_id,
                operational_issue=issue,
            )

    return DeliveryReceipt(
        request_id=send_request.request_id,
        state=ReceiptState.SENT,
        transport=ONEBOT_V11_TRANSPORT,
        provider_message_id=_extract_message_id(result),
        public_message="sent",
    )


def _mixed_dropped_types(send_request: SendRequest) -> list[str]:
    """重算 mixed 请求的本地丢段类型列表（核验指纹，与构段共享同一纯函数）。

    仅在核验开关开启的成功路径上调用（默认关闭=零额外开销）；判定与
    ``_mixed_segments`` 日志同源（``_mixed_segment_plan``），不会两说。
    """
    if send_request.content.content_type.strip().lower() != "mixed":
        return []
    planned, _segments, dropped_types = _mixed_segment_plan(send_request.content.content_ref)
    if planned < 0:
        return []
    return dropped_types


async def _try_send_forward_message(
    bot: OneBotV11SendBot,
    send_request: SendRequest,
) -> Any:
    messages = _forward_messages(send_request)
    if not messages:
        return _FORWARD_API_UNAVAILABLE

    if send_request.target_scope is SessionType.GROUP:
        payload = {
            "group_id": _coerce_onebot_id(send_request.target_id),
            "messages": messages,
        }
        return await _call_optional_onebot_api(
            bot,
            "send_group_forward_msg",
            payload,
        )
    if send_request.target_scope is SessionType.PRIVATE:
        payload = {
            "user_id": _coerce_onebot_id(send_request.target_id),
            "messages": messages,
        }
        return await _call_optional_onebot_api(
            bot,
            "send_private_forward_msg",
            payload,
        )
    return _FORWARD_API_UNAVAILABLE


async def _call_optional_onebot_api(
    bot: OneBotV11SendBot,
    api_name: str,
    payload: dict[str, Any],
) -> Any:
    """调用「可选」的 OneBot API；不可用或被实现端拒绝时返回哨兵值。

    M18：实现端（NapCat 时期）对 forward API 的拒绝是以**异常**形式抛出的
    （ActionFailed / 4xx）。此前只有「方法不存在」才返回哨兵，异常会穿透到
    重试循环，三次重试后整条消息 FAILED_RETRYABLE，而 `_mixed_segments` 里
    准备好的文本降级永不生效。这里把异常也收敛成哨兵，让调用方落到降级分支。
    """
    direct_method = getattr(bot, api_name, None)
    try:
        if callable(direct_method):
            return await direct_method(**payload)
        call_api = getattr(bot, "call_api", None)
        if callable(call_api):
            return await call_api(api_name, **payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 可选 API：任何失败都应降级而非中断投递。
        logger.warning(
            "optional onebot api unavailable api=%s error=%s detail=%s",
            api_name,
            type(exc).__name__,
            str(exc)[:120],
        )
        return _FORWARD_API_UNAVAILABLE
    return _FORWARD_API_UNAVAILABLE



# ---- B4b Tier2-b：UNKNOWN part 确认器骨架（接线缺省关，False 判定取证锁）----
# worker §9.3 对「无段级回执的 UNKNOWN part」询问确认器（worker.py 判定协议
# 先查 part.provider_message_id → 再问确认器 → None 保持 UNKNOWN）。三值语义：
#   True  = 平台确认已送达（get_msg 命中）→ part 标 SENT，跳过；
#   False = 平台明确「消息不存在」→ part 回 PENDING，重发安全；
#   None  = 无法确认 → 保持 UNKNOWN，绝不盲发（防重复投递优先于防漏发）。
# 「不存在→False」被 _ONEBOT_GET_MSG_NOT_FOUND_PROVEN 取证锁死：SnowLuma 的
# get_msg 返回 schema / not-found retcode 形态未经真机回读（NapCat 侧同构性
# 也只是旁证），把「查询失败」误判成「未送达」=重投双发事故面。取证清单与
# 判定候选形态登记在 B4b-report §待取证；翻真前本函数生产恒 True/None 二值。
_ONEBOT_GET_MSG_NOT_FOUND_RETCODE = 1400  # 候选值（OneBot v11 未统一编码），取证前不生效
_ONEBOT_GET_MSG_NOT_FOUND_PROVEN = False  # 真机取证证实 schema 后置 True，False 判定才可达


def _resolve_part_message_id(send_request: SendRequest, part_index: int) -> str | None:
    """取 part 的 get_msg 查询把手：content_ref["part_message_ids"][part_index]。

    规格矛盾在此收口（B4b-report Concerns#1）：worker 只在 part 记录**无**
    provider_message_id 时才询问确认器，故确认器需要自备把手。现行生产无人
    写 part_message_ids 字段 ⇒ 恒 None=确认器安全空转（UNKNOWN 保持原状）。
    id 供给链（发送成功路径顺手回填 content_ref 或改 worker 查询序）属后续
    波次的跨席改动，本席不越面。
    """
    raw = send_request.content.content_ref.get("part_message_ids")
    if not isinstance(raw, list) or part_index < 0 or part_index >= len(raw):
        return None
    value = raw[part_index]
    if isinstance(value, (int, str)) and str(value).strip():
        return str(value).strip()
    return None


def _classify_get_msg_result(result: Any) -> bool | None:
    """get_msg 回执三值分类；除取证后的「明确不存在」外一律 None（保守）。"""
    data = result.get("data") if isinstance(result, dict) else getattr(result, "data", None)
    if isinstance(data, dict) and data:
        return True
    if (
        data is None
        and _ONEBOT_GET_MSG_NOT_FOUND_PROVEN
        and _extract_onebot_retcode(result) == _ONEBOT_GET_MSG_NOT_FOUND_RETCODE
    ):
        return False
    return None


def build_unknown_part_confirmer(
    bot_for_request: Callable[[SendRequest], Any],
) -> Callable[[SendRequest, int], Awaitable[bool | None]]:
    """构造基于 get_msg 的 UNKNOWN part 确认器（T2-a 鸭子探测同语义）。

    bot_for_request: (SendRequest)->在线 bot|None（生产接线传 _select_queue_bot
    的选择闭包）。任何一环缺能力/异常 → None=不确认=保持 UNKNOWN，
    与 worker 侧 _confirm_unknown_part_safely 的兜底方向一致。
    """

    async def confirm(send_request: SendRequest, part_index: int) -> bool | None:
        message_id = _resolve_part_message_id(send_request, part_index)
        if message_id is None:
            return None
        bot = bot_for_request(send_request)
        get_msg = getattr(bot, "get_msg", None)
        if not callable(get_msg):
            return None
        try:
            result = await get_msg(message_id=message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 确认是旁路：异常=无法确认，绝不重发。
            logger.warning(
                "onebot get_msg confirm query failed treat_as_unknown type=%s request_id=%s part_index=%d",
                type(exc).__name__,
                send_request.request_id,
                part_index,
            )
            return None
        verdict = _classify_get_msg_result(result)
        logger.info(
            "onebot unknown part confirm request_id=%s part_index=%d verdict=%s",
            send_request.request_id,
            part_index,
            verdict,
        )
        return verdict

    return confirm
