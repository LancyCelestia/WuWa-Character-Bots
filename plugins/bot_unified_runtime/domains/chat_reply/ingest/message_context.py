"""Platform-neutral message segment normalization for chat context."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NormalizedMessage:
    plain_text: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    quoted_text: str = ""
    forwarded_text: str = ""
    # 频道拼格专辑（席位 S18）：本条消息所属专辑的聚合形态；非专辑＝None。
    # 一等字段而**不是**新增一种段 ``type``——理由见 ALBUM_MEMBER_SEGMENT_TYPES 注释。
    album: AlbumSummary | None = None

def _data(segment: dict[str, Any]) -> dict[str, Any]:
    value = segment.get("data")
    return value if isinstance(value, dict) else {}

# ---------------------------------------------------------------------------
# 频道拼格专辑（Telegram ``media_group_id``）——席位 S18，2026-10-02
#
# 平台事实（离线读适配器源码所得，非推测）：``nonebot-adapter-telegram`` 0.1.0b20
# 把 ``media_group_id`` 挂在**事件**上（``telegram/event.py`` MessageEvent:140 /
# ChannelPostEvent:289 一带），**段里没有**；一条 N 图拼格是 N 个独立 update、
# N 个独立事件，每个事件只带 1 个媒体段。于是缺口是两层叠加：
# ① 我方全包对 ``media_group_id`` 零命中（连读都没读）→ 每张图各自折成一句
#    孤立的 ``[图片]``，文本面看不出"这三句其实是同一张专辑"；
# ② Bot API 不宣告专辑总张数 → 单个事件永远数不出"这一共几张"。
# 解法因此分两半：本件维护一枚按 ``(会话, 专辑号)`` 累计的**短窗计数桶**（治②，
# 与 ``telegram_media._FILE_PATH_CACHE`` 同一枚范式——模块级 dict + TTL + 容量帽，
# 不引第三方；摄取跑在线程池上，桶的读改写下到 dict 单步即够用，与先例同取舍），
# 并让 ``_flatten`` 把**同一专辑的媒体标签折成一条**带计数的摘要（治①）。
# 🔴 段面一张都不丢：每条媒体段照常留在 ``segments`` 里（就地盖章 ``data.
# media_group_id`` / ``album_position`` / ``album_member_count``），所以富化腿
# ``enrich_telegram_file_segments``、识图腿 ``vision_describe.extract_image_urls``
# 与 ``_remember_session_images`` 吃到的仍是 N 张原图——**折叠只发生在文本面**。
# 刻意不造 ``type="album"`` 这种新段形态：段类型的既有消费者（渲染、视觉、门禁
# ``contains_visual_message_segments``）各按在册集合判定，凭空加一种形态等于让
# N 处判据各表一次态，与"禁第二真身"同口径冲突；聚合结构改由
# ``NormalizedMessage.album`` 承载，消费者要么读文本标签、要么读这个字段。
# 措辞沿用既有标签族（``[图片]``/``[转发/聊天记录]``）的行首方括号形态，不破既有
# 形态锁；新标记一律同批登记进 ``INTERNAL_MARKER_PATTERN``（台账 #67★"给判定行
# 加字段必须同批补门票与消毒"），令引用/转发正文无法伪造专辑计数。
# ---------------------------------------------------------------------------

# 可作拼格成员的段类型。TG 的专辑只装 photo/video/document/audio 四类；
# ``image`` 一并纳入是防适配器再归一（OneBot 形态），``animation`` 是 TG 动图。
# ``document`` 与 ``file`` 两形都列：富化腿成功会把 document 段改成根入站认得的
# ``file`` 段（``telegram_media._DOCUMENT_TARGET_SEGMENT_TYPE``），若只认 document
# 就会在"富化在前、归一在后"的时序下漏聚合最后一张。
ALBUM_MEMBER_SEGMENT_TYPES = frozenset(
    {"photo", "image", "video", "animation", "document", "file"}
)
ALBUM_MEMBER_KIND_LABELS = {
    "photo": "图",
    "image": "图",
    "video": "视频",
    "animation": "动图",
    "document": "文件",
    "file": "文件",
}
# 计数桶 TTL：Telegram 拼格的 N 个 update 在同一批 getUpdates 里秒级到达，
# 120s 是宽松上限；过期即当"这串专辑号不再活跃"，不留永久状态。
ALBUM_BUCKET_TTL_SECONDS = 120.0
ALBUM_BUCKET_CAP = 256
# Telegram 官方拼格上限 10 张；累计值钉在此，防畸形重复投递把计数吹大。
ALBUM_MAX_MEMBERS = 10
_ALBUM_BUCKETS: dict[str, tuple[float, int]] = {}
# 同册开门登记（席位 P9）：``(会话, 专辑号)`` → (册主到达时刻, 已到达张数, 册主 message_id)。
# 与计数桶**分家**：桶记"这串专辑号累计见过几张"（文本面计数），本表记"这一册已经有人
# 回过了"（能力调用次数）。两个生命周期不同（120s vs 折句窗），并成一张表会让其一失真。
_ALBUM_TURN_CLAIMS: dict[str, tuple[float, int, str]] = {}
# 专辑号形状闸：真实 media_group_id 是平台生成的不透明短串（字母数字）。
# 越形一律不当专辑处理——它会被拼进文本面标签，放进任意串等于让平台字段
# 自己挑怎么被读（同「意象名词禁抄进代码」那类形状闸口径）。
_ALBUM_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
# 话题/评论区 id 形状闸：平台侧恒为正整数（adapter model.py message_thread_id）。
# 非纯数字直接不带上，杜绝"thread id 里塞 ] 提前闭合标记"这条路。
_TOPIC_ID_PATTERN = re.compile(r"\d{1,20}")


@dataclass(frozen=True)
class AlbumContext:
    """本条消息所属拼格专辑的归一上下文（``None``＝本条不属于任何专辑）。

    ``member_count``＝该 ``(会话, 专辑号)`` 桶**累计已见**张数（含本条），
    不是平台宣告的总数（平台不宣告，见上）。
    """

    media_group_id: str
    member_count: int


@dataclass(frozen=True)
class AlbumSummary:
    """专辑聚合形态（随 ``NormalizedMessage.album`` 交给下游与 prompt）。"""

    media_group_id: str
    member_count: int
    member_types: tuple[str, ...]


def reset_telegram_album_state() -> None:
    """清空专辑状态（测试隔离用；生产靠 TTL／窗口过期与容量帽自然淘汰）。

    两本账一起清：计数桶（文本面张数）与同册开门登记（能力调用次数，见
    ``telegram_album_turn_decision``）——只清一本会让另一本跨用例串状态。
    """
    _ALBUM_BUCKETS.clear()
    _ALBUM_TURN_CLAIMS.clear()


def _album_group_of(data: dict[str, Any]) -> str:
    return str(data.get("media_group_id") or "").strip()


def _record_album_members(session_id: str, media_group_id: str, seen_here: int, now: float) -> int:
    """累计本专辑已见张数并回写桶；返回累计值（含本条）。"""
    key = f"{session_id}|{media_group_id}"
    previous = _ALBUM_BUCKETS.get(key)
    base = 0
    if previous is not None and now - previous[0] <= ALBUM_BUCKET_TTL_SECONDS:
        base = previous[1]
    total = min(base + max(1, int(seen_here)), ALBUM_MAX_MEMBERS)
    # 先 pop 再 set：让该键落到 dict 末尾，尾部＝最近 touched，
    # 于是容量帽淘汰的是 dict 序意义上的最久未用键。
    _ALBUM_BUCKETS.pop(key, None)
    _ALBUM_BUCKETS[key] = (now, total)
    while len(_ALBUM_BUCKETS) > ALBUM_BUCKET_CAP:
        _ALBUM_BUCKETS.pop(next(iter(_ALBUM_BUCKETS)), None)
    return total


def telegram_album_context(
    event: Any,
    segments: list[dict[str, Any]] | None,
    normalized_adapter: str,
    *,
    session_id: str = "",
    now: float | None = None,
) -> AlbumContext | None:
    """TG 拼格专辑盖章 + 计数：读事件的 ``media_group_id``，就地标进媒体段。

    三道结构性收窄（任一不过＝返回 None＝既有"逐张 ``[图片]``"行为逐字节不变）：
    ① 仅 ``normalized_adapter == "telegram"``（QQ 路径零扰动的判据来源）；
    ② 事件真带合法形状的 ``media_group_id``（Bot API 只在拼格成员上给这个字段）；
    ③ 本条段列表里真有可作拼格成员的媒体段。
    """
    if (normalized_adapter or "").strip().lower() != "telegram":
        return None
    media_group_id = str(getattr(event, "media_group_id", "") or "").strip()
    if not media_group_id or not _ALBUM_ID_PATTERN.fullmatch(media_group_id):
        return None
    members: list[dict[str, Any]] = []
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).strip().lower() not in ALBUM_MEMBER_SEGMENT_TYPES:
            continue
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        members.append(data)
    if not members:
        return None
    stamp = time.monotonic() if now is None else float(now)
    total = _record_album_members(session_id, media_group_id, len(members), stamp)
    # 累计值里本条之前已有多少，据此编位序（专辑内第几张），让下游能把
    # "跨事件到达的 N 条" 串回同一张专辑。
    base = max(0, total - len(members))
    for offset, data in enumerate(members, start=1):
        data["media_group_id"] = media_group_id
        data["album_position"] = base + offset
        data["album_member_count"] = total
    return AlbumContext(media_group_id=media_group_id, member_count=total)


# ---------------------------------------------------------------------------
# 同册只回一次（席位 P9，2026-10-02）：跨事件的**册级合并判据**。
#
# 上一段治的是"文本面别出现 N 句孤立 ``[图片]``"；这一段治"能力调用别跑 N 次"——
# 拼格的 N 个成员事件各走一遍摄取 ⇒ 各进一次管道 ⇒ 用户看到 N 条回复。
# 判据：按 ``(会话, 专辑号)`` 记一枚**开门登记**，窗口内第一条＝册主（照常回一句），
# 后到的纯媒体成员＝已折进那一轮，调用方必须就此返回、不再触发第二次能力调用。
#
# 窗口用哪枚既有常量：``runtime/message_merge.MERGE_WINDOW_SECONDS``（用户 2026-09-27
# 裁定的 3s 折句等待窗）。本席**不加第三个计时参数**，也不取本文件的
# ``ALBUM_BUCKET_TTL_SECONDS``（120s）——那是"这串专辑号还算活跃"的计数桶过期，
# 拿它当抑制窗等于让 60 秒后姗姗来迟的那张图永远没人回；3s 才是"同一批连发算一轮"
# 的既有语义，而 TG 拼格的 N 个 update 本就同一批 getUpdates 里秒级到达。
#
# 有界性（"末张图不到不许卡死"）来自结构本身：本判据**不开等待窗、不 await、不占
# 协程**——册主当场放行，后来者当场判定；登记只在窗口内算数，过期即视同新册主重新
# 回一句。最坏情形是"多回一句"，绝不存在"整轮挂住"。
#
# 🔴 三道"绝不吞消息"的闸（任一命中＝ ``merged=False``，走既有链路照常回）：
#   ① 非 telegram 适配器——读 ``IncomingMessage.adapter``／``platform`` 这两枚中央字段，
#      不按文本内容猜（QQ 侧本无拼格语义，零扰动）；
#   ② 本条段里没有合法形状的专辑号（未被上一段盖章＝不是拼格成员）；
#   ③ 本条带**用户键入正文**（拼格成员自己的配文）——把它折掉等于吞了这句话，
#      宁多回一句不误吞正文（与 ``message_merge`` 静默腿同一 fail-open 口径）。
#   另加同轮重投闸：登记的册主 ``message_id`` 与本条相同 ⇒ 这是**同一轮**被重放
#   （TG 连接期重投，台账 #65），不是册内第二张，不得静默吞。
#
# 本判据只读上一段的盖章结果与中央字段，**不产任何新的文本面标记** ⇒
# ``INTERNAL_MARKER_PATTERN`` 无需新门票（台账 #67★ 的"同批补门票"义务在此为空腿）。
# ---------------------------------------------------------------------------

# 判定理由（可点名审计，与 message_coalescing 的 ``signals`` 同一口径：不黑箱）。
ALBUM_TURN_OWNER = "owner"  # 册主：本条负责回一句
ALBUM_TURN_MERGED = "merged"  # 已折进同册册主那一轮：调用方就此返回
ALBUM_TURN_NOT_ALBUM = "not_album"  # 非 TG／无合法专辑号：既有行为逐字节不变
ALBUM_TURN_CAPTION = "caption_member"  # 带用户正文：不折（绝不吞正文）
ALBUM_TURN_SAME_TURN = "same_turn"  # 与册主同 message_id：同一轮被重放，不静默吞


@dataclass(frozen=True)
class AlbumTurnDecision:
    """这一条拼格成员该不该自己触发一轮能力调用。

    ``merged`` 为真 ⇒ 本条已被折进同册册主那一轮，调用方必须就此返回（禁第二次
    能力调用）；为假 ⇒ 照常走既有链路，``reason`` 说明为什么没折（含 ``owner``
    这一路，"没折"不等于"不是专辑"）。
    """

    merged: bool
    media_group_id: str = ""
    arrival: int = 0  # 本条是该桶第几次到达（1＝册主）
    owner_message_id: str = ""  # 册主的 message_id（对账与"同一轮重放"判定用）
    reason: str = ALBUM_TURN_NOT_ALBUM


def _album_group_of_message(message: Any) -> str:
    """从消息段读专辑号：只认上一段盖章的 ``data.media_group_id``（唯一真身）。

    再过一次 ``_ALBUM_ID_PATTERN``：段上的章可能被别的来源写脏，形状闸不重复信任。
    """
    for segment in getattr(message, "raw_segments", None) or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).strip().lower() not in ALBUM_MEMBER_SEGMENT_TYPES:
            continue
        group_id = _album_group_of(_data(segment))
        if group_id and _ALBUM_ID_PATTERN.fullmatch(group_id):
            return group_id
    return ""


def _message_carries_user_text(message: Any) -> bool:
    """本条是否带用户键入的正文（拼格成员的配文）。

    两腿任一命中即算带正文，只收紧不放宽（宁可多回一句）：
    ① 段面有实值 ``text`` 段；② ``plain_text`` 过 ``INTERNAL_MARKER_PATTERN``
    剥掉内部标记（``[相册 共N图]``／``[图片]`` 一类标签）之后仍非空。
    """
    for segment in getattr(message, "raw_segments", None) or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).strip().lower() != "text":
            continue
        if str(_data(segment).get("text", "")).strip():
            return True
    stripped = INTERNAL_MARKER_PATTERN.sub(" ", str(getattr(message, "plain_text", "") or ""))
    return bool(stripped.strip())


def _telegram_adapter_of(message: Any) -> bool:
    """平台判定：只读中央字段 ``adapter``／``platform``，不按消息文本猜。"""
    for name in ("adapter", "platform"):
        if str(getattr(message, name, "") or "").strip().lower() == "telegram":
            return True
    return False


def album_turn_state() -> dict[str, tuple[float, int, str]]:
    """同册开门登记的只读视图（观测与巡检用；写入点只有本件那两枚函数）。"""
    return dict(_ALBUM_TURN_CLAIMS)


def telegram_album_turn_decision(
    message: Any,
    *,
    now: float | None = None,
) -> AlbumTurnDecision:
    """同一 ``media_group_id`` 只回一次——跨事件的册级合并判据（无等待、有上界）。

    用法（唯一调用点＝根装配段，进管道之前）：返回 ``merged=True``  ⇒ 记账并
    ``return``，本条不再触发能力调用；返回 ``merged=False`` ⇒ 拿着原消息继续走链路。
    非 TG／非专辑一律 ``merged=False``，既有行为逐字节不变（三闸见上注释块）。
    """
    group_id = _album_group_of_message(message)
    if not _telegram_adapter_of(message) or not group_id:
        return AlbumTurnDecision(merged=False, media_group_id=group_id, reason=ALBUM_TURN_NOT_ALBUM)

    # 窗口真身＝折句等待窗（用户裁定 3s），局部导入避开 runtime/__init__ 的 pipeline 依赖
    # （同 message_coalescing.fold_inbound_turn 里 import message_merge 的先例）。
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.message_merge import (
        MERGE_WINDOW_SECONDS,
    )

    stamp = time.monotonic() if now is None else float(now)
    session_id = str(getattr(message, "session_id", "") or "")
    key = f"{session_id}|{group_id}"
    message_id = str(getattr(message, "message_id", "") or "").strip()
    claim = _ALBUM_TURN_CLAIMS.get(key)

    if claim is not None and stamp - claim[0] <= MERGE_WINDOW_SECONDS:
        first_at, arrivals, owner_id = claim
        if message_id and message_id == owner_id:
            # 同一轮被重投/重放：既不该再回一次，也不该被当"册内第二张"静默吞掉——
            # 交回调用方按既有链路走（幂等腿另有其账，本判据不越权替代）。
            return AlbumTurnDecision(
                merged=False,
                media_group_id=group_id,
                arrival=arrivals,
                owner_message_id=owner_id,
                reason=ALBUM_TURN_SAME_TURN,
            )
        if _message_carries_user_text(message):
            return AlbumTurnDecision(
                merged=False,
                media_group_id=group_id,
                arrival=arrivals,
                owner_message_id=owner_id,
                reason=ALBUM_TURN_CAPTION,
            )
        _ALBUM_TURN_CLAIMS[key] = (first_at, arrivals + 1, owner_id)
        return AlbumTurnDecision(
            merged=True,
            media_group_id=group_id,
            arrival=arrivals + 1,
            owner_message_id=owner_id,
            reason=ALBUM_TURN_MERGED,
        )

    # 无登记（本册第一条）或窗口已过期（末张图迟迟不来 / 迟到到窗口外）⇒ 本条当册主。
    _ALBUM_TURN_CLAIMS.pop(key, None)
    _ALBUM_TURN_CLAIMS[key] = (stamp, 1, message_id)
    while len(_ALBUM_TURN_CLAIMS) > ALBUM_BUCKET_CAP:
        _ALBUM_TURN_CLAIMS.pop(next(iter(_ALBUM_TURN_CLAIMS)), None)
    return AlbumTurnDecision(
        merged=False,
        media_group_id=group_id,
        arrival=1,
        owner_message_id=message_id,
        reason=ALBUM_TURN_OWNER,
    )


def telegram_topic_context_note(event: Any, normalized_adapter: str) -> str:
    """评论区/群话题上下文（``message_thread_id`` + ``is_topic_message`` 的消费者）。

    现状定性（实测与源码核对）：这两个字段平台**会送**，而我方全树零消费者——
    ``message_thread_id`` 只在摄取处读进 ``IncomingMessage.thread_id``
    （``contracts/runtime.py`` 的 ``thread_id``），那个字段本身也没人读。
    本函数给它一个真消费者：**复用 ``.thread_id`` 这一枚字段**（不新建第二套），
    把"这条消息出自评论区/话题 #id"做成一条结构化说明文本，供下游与 prompt 用。

    🔴 结构性上限（照实说明，不假称能读）：Telegram Bot API **不提供**任意
    评论历史读取——``getChatHistory`` 一类方法对 Bot 不可用，评论区消息只能
    作为独立 update 逐条到达。所以本腿是"知道自己在哪"，不是"读完整串评论"；
    真要读整串评论，需要 bot 本身是该讨论组的成员且评论逐条流经摄取链，
    属平台侧限制，改配置解决不了。
    """
    if (normalized_adapter or "").strip().lower() != "telegram":
        return ""
    thread_id = str(getattr(event, "message_thread_id", "") or "").strip()
    if not _TOPIC_ID_PATTERN.fullmatch(thread_id):
        return ""
    if getattr(event, "is_topic_message", None) is True:
        return f"[话题 群话题 #{thread_id}]（本条来自群话题，非整串评论历史）"
    return f"[评论区 话题 #{thread_id}]（本条来自频道文章的评论区，非整串评论历史）"


def _album_label_text(member_kinds: list[str], total: int) -> str:
    """专辑文本面摘要：**一条**带成员计数的标签（同族多图时按类型分项）。"""
    counts: dict[str, int] = {}
    for kind in member_kinds:
        name = ALBUM_MEMBER_KIND_LABELS.get(kind, "媒体")
        counts[name] = counts.get(name, 0) + 1
    if list(counts) == ["图"]:
        return f"[相册 共{total}图]"
    detail = "·".join(f"{count}{name}" for name, count in counts.items())
    return f"[相册 共{total}项（{detail}）]"


def _flatten(
    items: Any,
    *,
    depth: int = 0,
    album: AlbumContext | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    if depth > 5 or not isinstance(items, list):
        return [], [], [], []
    normalized: list[dict[str, Any]] = []
    texts: list[str] = []
    quotes: list[str] = []
    forwards: list[str] = []
    # 专辑标签折叠游标：首张成员"本该放标签"的位置与已见成员类型。
    # 计数不下钻进转发子层（转发记录里的那串图是另一码事，不混同一张专辑）。
    album_text_index: int | None = None
    album_member_kinds: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).strip().lower()
        data = _data(raw)
        if kind == "text":
            value = str(data.get("text", ""))
            if value:
                texts.append(value)
            normalized.append({"type": "text", "data": {"text": value}})
        elif kind == "quote":
            value = str(data.get("text") or data.get("content") or "").strip()
            if value:
                quotes.append(value)
                # P2-d：被引用正文是**他人可控**串，进 plain_text 前过同一把尺
                # （`_display_safe_text` 内含 `_neutralize_markers` 的同一枚真身，
                # 不再叠第二遍）。裸 text 段（用户自己键入那格）不在此动——
                # 它由入站话术门 `check_prompt_injection` 逐条处置，两腿不互替。
                texts.append(f"\n[引用内容]\n{_display_safe_text(value)}\n[/引用内容]")
            normalized.append({"type": "quote", "data": {**data, "text": value}})
        elif kind in {"forward", "chat_history", "messages"}:
            children = data.get("messages") or data.get("content") or data.get("nodes")
            child_segments, child_texts, child_quotes, child_forwards = _flatten(children, depth=depth + 1)
            joined = "\n".join(child_texts).strip()
            if joined:
                forwards.append(joined)
                # P2-d：合并转发整块都是他人内容，同走文本咽喉（同上注释）。
                texts.append(
                    f"\n[转发/聊天记录]\n{_display_safe_text(joined)}\n[/转发/聊天记录]"
                )
            normalized.append({"type": "forward", "data": {"messages": child_segments, **data}})
            normalized.extend(child_segments)
            quotes.extend(child_quotes); forwards.extend(child_forwards)
        elif kind in {"face", "mface", "marketface", "emoji"}:
            label = str(data.get("raw") or data.get("text") or data.get("name") or "表情")
            texts.append(f"[Emoji:{label}]")
            normalized.append({"type": "emoji", "data": data})
        elif kind in {
            "image",
            "photo",
            "sticker",
            "animation",
            "video_note",
            "file",
            "record",
            "voice",
            "audio",
            "video",
        }:
            # 跨适配器归一：OneBot 的 image/record/video vs Telegram 的
            # photo/sticker/animation/video_note/voice/audio 都要有可读标签，
            # 否则纯媒体消息在提示词里连"有张图/有段语音"都体现不出来。
            if (
                album is not None
                and kind in ALBUM_MEMBER_SEGMENT_TYPES
                and _album_group_of(data) == album.media_group_id
            ):
                # 拼格成员：段**照旧留下**（富化/识图腿一张都不能少），
                # 只是不再逐张发标签——改在循环末尾发一条带计数的专辑摘要。
                if album_text_index is None:
                    album_text_index = len(texts)
                album_member_kinds.append(kind)
                normalized.append({"type": kind, "data": data})
                continue
            label = {
                "image": "图片",
                "photo": "图片",
                "sticker": "表情包",
                "animation": "动图",
                "video_note": "圆形视频",
                "file": "文件",
                "record": "语音",
                "voice": "语音",
                "audio": "音频",
                "video": "视频",
            }[kind]
            texts.append(f"[{label}]")
            normalized.append({"type": kind, "data": data})
        elif kind:
            normalized.append({"type": kind, "data": data})
    if album_member_kinds and album_text_index is not None and album is not None:
        total = max(album.member_count, len(album_member_kinds))
        texts.insert(album_text_index, _album_label_text(album_member_kinds, total))
    return normalized, texts, quotes, forwards

def _album_summary(
    segments: list[dict[str, Any]], album: AlbumContext | None
) -> AlbumSummary | None:
    """段面 → 聚合形态（与文本面标签同一枚来源，不另起一套判据）。"""
    if album is None:
        return None
    member_types = tuple(
        str(segment.get("type", "")).strip().lower()
        for segment in segments
        if str(segment.get("type", "")).strip().lower() in ALBUM_MEMBER_SEGMENT_TYPES
        and _album_group_of(_data(segment)) == album.media_group_id
    )
    if not member_types:
        return None
    return AlbumSummary(
        media_group_id=album.media_group_id,
        member_count=max(album.member_count, len(member_types)),
        member_types=member_types,
    )


def normalize_message_segments(
    raw_segments: list[dict[str, Any]] | None,
    *,
    album: AlbumContext | None = None,
) -> NormalizedMessage:
    segments, texts, quotes, forwards = _flatten(raw_segments or [], album=album)
    return NormalizedMessage(" ".join(part for part in texts if part).strip(), segments, "\n".join(quotes), "\n".join(forwards), _album_summary(segments, album))


# --------------------------------------------------------------------------
# 引用链（评审：需求「综合解析回复消息 / 递归解析嵌套引用」）
#
# 背景：QQ 侧引用此前**完全读不到**——旧代码对 `event.reply` 取
# `get_plaintext()`/`.text`，而 OneBot V11 的 `Reply` 模型只有
# time/message_type/message_id/real_id/sender/message，两个属性都不存在，
# 于是 `reply_to_text` 恒为空、`[引用回复]` 块永不拼接（实测复现）。
# Telegram 侧只读第一层，而适配器其实递归解析了 `reply_to_message`。
#
# 这里把引用链做成一等结构：逐层采集 → 逐层预算 → 统一消毒 → 单点渲染。
# --------------------------------------------------------------------------

# 层数上限：QQ/Telegram 客户端实际展示深度约 2-3 层。用户指示放宽到 5 层，
# 以便较长的引用链也能被完整读取。
REPLY_CHAIN_MAX_DEPTH = 5
# 单层字符预算：**放宽后的上限**，不是目标值。正常引用（一两句话）只会用到
# 几十字；该值只用于拦住"被引用一条公告/小说"这类极端长文，避免撑大 prompt。
REPLY_CHAIN_PER_LEVEL_CHARS = 500
# 整链字符预算：同样是上限。实际注入量取决于引用链的真实内容，
# 由 format_reply_chain 的"有多少写多少"语义决定，不会为了凑预算而填充。
REPLY_CHAIN_TOTAL_CHARS = 2000
# 链条在"真实需要时"才展开：层数上限虽为 5，但只有确实存在更深引用时才会去取，
# 避免为了凑层数而做多余的反查请求或注入空层。
_ELLIPSIS = "…"
# 引用图媒体预算（席位 MM-VIS-1，2026-09-29，治审计缺陷 2「引用图只有 [图片] 三字」）：
# 被引用那条消息里的图，此前在 `_segments_to_text` 被折成 `[图片]` 标签就完事了——
# 模型知道"那里有过一张图"，但对图上写了什么一无所知。现在把图源指针一并带出来，
# 交给聊天腿的识图咽喉（`chat.py` 图片识别那一段）当**额外图片**描述。
# 上限两枚都刻意与主消息同一量级，不放宽：
# - 张数＝2，与 `BOT_VISION_MAX_IMAGES` 缺省同值（多的图进不了模型，白排队）；
# - 总字节＝8MB，兜住"两条各一张 4K 截图 data URL"这种把请求体撑爆的形状。
REPLY_CHAIN_MAX_MEDIA_REFS = 2
REPLY_CHAIN_MEDIA_TOTAL_BYTES = 8_000_000
# 内部标记统一正则（审查 F-13 同族收口：全项目唯一一份）。
# security/injection.py 与 capabilities/chat.py 的同用途正则一律从本模块导入，
# 禁止再复制第二份——三处各自维护曾导致 chat 侧漏收引用族标记。
# 覆盖运行时真实产出/易被伪造的全部包裹标记：
#   [引用回复 层级N(+发送者名)] / [引用内容] / [转发/聊天记录]
#   [UNTRUSTED_USER_TEXT] / [TRUSTED_SYSTEM]
#   [相册 共N图/项] / [话题 群话题 #id] / [评论区 话题 #id]（S18 新增，同批登记）
# 及同族变体（引用消息/转发消息/转发的消息）。标记名到闭括号之间的任意尾巴
# （如 `` 层级1 澜汐``）一并命中：format_reply_chain 产出的开标记就带发送者名，
# 旧正则 ``(?: 层级\d+)?\]`` 漏掉该形态，被引用正文可伪造真实开标记提前闭合。
# 刻意不收录裸「引用」「转发」（无后缀复合词）：正常文本含「引用」二字不误剥。
# 🔴 台账 #67★ 在册令：给判定行/文本面加新标记必须**同批**把门票补进这里——
# 专辑标签带计数，不登记就等于让引用/转发正文能自己写"[相册 共9图]"冒充拼图规模。
INTERNAL_MARKER_PATTERN = re.compile(
    r"\[(/?)(引用回复|引用内容|引用消息|转发消息|转发的消息|转发/聊天记录"
    r"|UNTRUSTED_USER_TEXT|TRUSTED_SYSTEM|相册|话题|评论区)[^\]]*\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReplyChainItem:
    """引用链的一层（自近及远：layer=1 是直接回复的那条）。

    ``text`` 与 ``sender_name`` 由两个采集入口（``collect_reply_chain`` /
    ``collect_reply_chain_async``）在**存入前**统一过 ``_neutralize_markers``；
    绕过采集入口手工构造的实例没有这层保证，不要新增第二个构造点。

    ``media_refs``＝被引用那条消息里**图片段**的源指针（本机路径 / http URL /
    ``data:`` URL 三态都可能，顺序即段顺序，上限见
    ``REPLY_CHAIN_MAX_MEDIA_REFS``）。它**不是**已经编码好的 data URL——
    下载与编解码只在识图咽喉那一次发生（``vision_describe.prepare_vision_image_urls``），
    摄取层不碰网络、也不做第二次编码（字段旧名 ``media_data_urls`` 会让人以为
    这里已经编码过，实为误导，故按真形态命名）。
    音频/视频段不进这里：视频另有 ``reply_video_path`` 那条已通的专用腿。
    """

    layer: int
    message_id: str = ""
    sender_id: str = ""
    sender_name: str = ""
    text: str = ""
    media_labels: tuple[str, ...] = ()
    media_refs: tuple[str, ...] = ()


def _neutralize_markers(value: str) -> str:
    """把内部标记全角化，令被引用正文无法伪造块闭合（同 injection 层策略）。

    必须同时覆盖**带层级后缀**的形态：渲染出来的是
    ``[引用回复 层级1] … [/引用回复 层级1]``，被引用正文里只要出现
    ``[/引用回复 层级1]`` 就能提前闭合。只替换无后缀的裸标记会漏（实测）。

    只命中内部关键字，不碰用户正常书写的方括号（早期版本整段全角化 `[`/`]`，
    会篡改被引用正文里的代码、数组、`[图片]` 之类正常文本）。
    """
    return INTERNAL_MARKER_PATTERN.sub(
        lambda match: match.group(0).replace("[", "［").replace("]", "］"),
        value,
    )


def _display_safe_name(value: str) -> str:
    """名片**显示形态**的视觉伪装处置（ANTIATTACK P2-d · 需求 17）。

    与 `_neutralize_markers` 各管一段、互不替代：那枚管「块边界能不能被伪造」，
    本枚管「肉眼看到的形态与真实码点是否一致」——RLO（U+202E）会把名片后半段
    翻成反向、零宽字符能把 `admin` 藏进一串看似无害的字符里，而这两类字符
    **都不是**方括号，`INTERNAL_MARKER_PATTERN` 一个都不命中。群名片是攻击者
    可控输入，伪装名进提示词块头 `[引用回复 层级N 名字]` 等于让它自己挑怎么被读。

    判据零副本：真身住 `core/safety_exec/attack_surface`，处置口住
    `chat_reply/security/injection::render_safe_display_name`。
    **局部导入**——`security/injection.py` 顶层从本件取 `INTERNAL_MARKER_PATTERN`，
    模块级反向导入会成环（局部导入先例：notes / vision_describe / sentiment_selector）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
        render_safe_display_name,
    )

    return render_safe_display_name(value, surface="reply_chain_sender_name")


def _display_safe_text(value: str) -> str:
    """被引用/转发**正文**的显示伪装处置（P2-d 文本腿，进 prompt 前）。

    名片只骗眼睛，正文还能骗「这一块的边界在哪」——所以文本腿既要不腐化可见形态
    （剥 Bidi/零宽、逐词折同形角色词、压空白填充），又要保住块边界（内部标记
    全角化）。两半各归各位：伪装半借 `display_guard.neutralize_visual_spoof`
    （判据仍住 attack_surface，本件一张表都不抄），边界半仍用本件自己的
    `_neutralize_markers`——它在册口径是**保留尾巴**的全角形（`［/引用回复 层级1］`），
    换成 injection 那形会把层级与发送者名抹掉，属另一条已登记漂移（另案）。
    顺序固定：先伪装后边界（反了会把 `［］` 当正文的一部分喂给谓词）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.security.display_guard import (
        neutralize_visual_spoof,
    )

    return _neutralize_markers(neutralize_visual_spoof(value, surface="reply_chain_body"))


def _clip(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + _ELLIPSIS


def _as_segment_dict(item: Any) -> dict[str, Any] | None:
    """把适配器的 MessageSegment / dict 统一成 ``{"type":…, "data":…}``。

    OneBot 的 ``Reply.message`` 是 ``Message``（元素为 pydantic ``MessageSegment``
    对象，不是 dict）——直接丢给按 dict 写的 `_flatten` 会**静默产出空文本**，
    这正是第一版补丁的 bug（实测 `_segments_to_text(rep.message) == ('', ())`）。
    """
    if isinstance(item, dict):
        return item
    seg_type = getattr(item, "type", None)
    if seg_type is None:
        return None
    data = getattr(item, "data", None)
    return {"type": str(seg_type), "data": data if isinstance(data, dict) else {}}


def _image_segment_types() -> set[str]:
    """「可看的图」段类型集合——判据借 ``vision_describe.IMAGE_GROUPS``，此处不抄表。

    为什么不能在这里自己写一份 ``{"image", "photo", ...}``：那套字面量的真身住在
    视觉侧（按 photo/sticker/animation 三组分家，2026-09-23 用户多模态矩阵裁定），
    引用腿再手写一份就是第二真身——两处早晚打架（QQ 的 ``face/mface/marketface``
    在归一层已被改写成 ``emoji`` 段，只写 mface 的那份副本就漏过一整列，
    视觉侧 09-23 就踩过这个坑）。局部导入＝避免与视觉侧的模块级循环，
    先例见 ``_display_safe_name`` 的在册注释。
    """
    from plugins.bot_unified_runtime.domains.media.ingest import vision_describe

    types: set[str] = set()
    for group in vision_describe.DEFAULT_IMAGE_GROUPS:
        types |= set(vision_describe.IMAGE_GROUPS.get(group, ()))
    return types


def _segments_media_refs(segments: Any) -> tuple[str, ...]:
    """段列表 → 图片源指针（至多 ``REPLY_CHAIN_MAX_MEDIA_REFS`` 张、总字节封顶）。

    只指针、不下载不编码（理由见 ``ReplyChainItem.media_refs`` 文档串）。

    **取哪一个指针是有讲究的**：一个段可能同时挂 ``url``(http) 与 ``file``(本机)
    两键，而调用侧的识图咽喉 ``vision_describe.extract_image_urls`` 的既有口径是
    「本机优先、http 兜底」（``resolved = local_url or http_url``）。本函数刻意
    抄不动、只用同一个偏好：两条腿对**同一张图**选出的必须是**同一个字符串**，
    聊天腿那句"按编码结果去重"才成立。去重一旦失效，同一张图会进两次 VLM 请求——
    缺陷 2 修完反而把账单翻倍，那是比读不到图更坏的"修出 regression"。
    """
    try:
        wanted = _image_segment_types()
    except Exception:  # noqa: BLE001 - 判据取不到就当"本轮没有引用图"，绝不让摄取崩。
        return ()
    refs: list[str] = []
    total = 0
    for item in segments or ():
        seg = _as_segment_dict(item)
        if seg is None:
            continue
        if str(seg.get("type", "")).strip().lower() not in wanted:
            continue
        data = seg.get("data")
        data = data if isinstance(data, dict) else {}
        candidates = [
            str(data.get(key) or "").strip() for key in ("url", "file", "path")
        ]
        local_ref = next(
            (part for part in candidates if part and not part.startswith("http")), ""
        )
        http_ref = next((part for part in candidates if part.startswith("http")), "")
        ref = local_ref or http_ref
        if not ref or ref in refs:
            continue
        if len(refs) >= REPLY_CHAIN_MAX_MEDIA_REFS:
            break
        if total + len(ref) > REPLY_CHAIN_MEDIA_TOTAL_BYTES:
            break
        refs.append(ref)
        total += len(ref)
    return tuple(refs)


def _segments_to_text(segments: Any) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """段列表 → (文本, 媒体标签, 图片源指针)。

    OneBot 侧的 `Reply.message` 是完整段列表（实测含 image/record/video 段），
    媒体此前被 `extract_plain_text()` 整段丢弃；这里显式产出 `[图片]` 之类标签，
    让模型至少知道"被引用的那条里有张图/有段语音"。第三个返回值把**图**的源
    指针也带出来（MM-VIS-1 缺陷 2）——只给标签等于让模型猜图里写了什么。
    """
    items = [_as_segment_dict(item) for item in (segments or [])]
    _normalized, texts, _quotes, _forwards = _flatten(
        [item for item in items if item is not None]
    )
    media = tuple(
        part
        for part in texts
        if part.startswith("[") and part.endswith("]") and len(part) <= 8
    )
    joined = " ".join(part for part in texts if part and not part.startswith("[")).strip()
    if not joined:
        joined = " ".join(part for part in texts if part).strip()
    return joined, media, _segments_media_refs(segments)


def _plain_of(node: Any) -> str:
    """尽最大努力取一个节点的纯文本（适配器差异全部收敛在这里）。

    先试适配器自己的 ``get_plaintext()``；失败或为空时再退回 ``message`` 段列表
    （OneBot 的 ``Reply`` 就是这种形态），最后才看 ``text`` 属性。
    注意顺序：Telegram 事件即使没解析出内容也带一个**空的** ``message`` 字段，
    若先看 message 会得到空串并掩盖真正的 text，故必须先试 get_plaintext。
    """
    if node is None:
        return ""
    getter = getattr(node, "get_plaintext", None)
    if callable(getter):
        try:
            value = str(getter() or "").strip()
        except Exception:  # noqa: BLE001 - 适配器实现差异，读不到按空处理。
            value = ""
        if value:
            return value
    message = getattr(node, "message", None)
    if message is not None:
        extract = getattr(message, "extract_plain_text", None)
        if callable(extract):
            try:
                value = str(extract() or "").strip()
            except Exception:  # noqa: BLE001 - 同上。
                value = ""
            if value:
                return value
    text = getattr(node, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    # Telegram 的 caption 承载媒体消息的说明文字。
    caption = getattr(node, "caption", None)
    return caption.strip() if isinstance(caption, str) else ""


def _sender_of(node: Any) -> tuple[str, str]:
    sender = getattr(node, "sender", None)
    if sender is None:
        return "", ""
    user_id = str(getattr(sender, "user_id", "") or "")
    name = str(
        getattr(sender, "card", "")
        or getattr(sender, "nickname", "")
        or getattr(sender, "first_name", "")
        or ""
    )
    return user_id, name


def _replied_id_in_segments(segments: Any) -> str:
    """从段列表里取 ``reply`` 段指向的 message_id（QQ 的第二层线索）。

    QQ 的引用链是"逐段内嵌"的：本条消息的 reply 段给出被引用的 id，被引用消息
    自己的段列表里又可能带一个 reply 段指向更早的一条——这是继续下钻的唯一线索。
    """
    for item in segments or ():
        seg = _as_segment_dict(item)
        if seg is None:
            continue
        if str(seg.get("type", "")).lower() != "reply":
            continue
        data = seg.get("data") or {}
        value = data.get("id") or data.get("message_id")
        if value:
            return str(value)
    return ""


async def collect_reply_chain_async(
    event: Any,
    *,
    lookup: Any = None,
    max_depth: int = REPLY_CHAIN_MAX_DEPTH,
    per_level_chars: int = REPLY_CHAIN_PER_LEVEL_CHARS,
) -> list[ReplyChainItem]:
    """``collect_reply_chain`` 的异步版：能用 ``lookup`` 按 id 反查更深层引用。

    QQ 的 ``reply`` 段只带 id，"引用的引用"不随事件下发；``lookup(message_id)``
    由调用方注入（通常接 OneBot ``get_msg``），返回形如
    ``{"message_id":…, "message":[段…], "sender":{…}}`` 的映射。
    **只在确实存在更深 reply 段时才反查**——没有更深引用就不产生额外网络调用。
    反查失败/超时一律按链条结束处理，绝不阻断消息处理。
    """
    chain = collect_reply_chain(
        event, max_depth=max_depth, per_level_chars=per_level_chars
    )
    if not chain:
        return chain
    # 同步版在没有反查能力时会补一层 "[引用层级未展开]" 占位；这里既然能反查，
    # 就把该占位摘掉后用真实内容替换（否则会重复一层）。
    # 2026-09-18：去掉多余的 `chain[-1] and`——chain 非空已在上方保证，而
    # ReplyChainItem 是 dataclass 实例恒为真值，该判断永不起作用。
    if chain[-1].text == "[引用层级未展开]":
        chain.pop()
    if not callable(lookup):
        return chain
    seen = {item.message_id for item in chain if item.message_id}
    node: Any = getattr(event, "reply", None) or getattr(event, "reply_to_message", None)
    # 沿链条往下走：第一层来自事件，更深层靠反查。
    while node is not None and len(chain) < max_depth:
        segments = node.get("message") if isinstance(node, dict) else getattr(node, "message", None)
        nested_id = _replied_id_in_segments(segments)
        if not nested_id or nested_id in seen:
            break
        seen.add(nested_id)
        fetched = await _maybe_await(lookup(nested_id))
        if not isinstance(fetched, dict):
            break
        text, media, media_refs = _segments_to_text(fetched.get("message"))
        sender_raw = fetched.get("sender")
        sender = sender_raw if isinstance(sender_raw, dict) else {}
        chain.append(
            ReplyChainItem(
                layer=len(chain) + 1,
                message_id=str(fetched.get("message_id") or nested_id),
                sender_id=str(sender.get("user_id") or ""),
                # INJ-G1：名字与正文同口径消毒——引用族标记刻意不在检测面，
                # 未消毒的名格自己就是伪造器（群名片塞 `x] ［/引用回复…` 即裂块）。
                # P2-d：先过显示伪装处置、再过块边界消毒（顺序不可倒：处置可能
                # 整格换成屏蔽占位，占位里没有方括号，后过 `_neutralize_markers`
                # 是恒等；反过来先全角化再判伪装，会把 `［］` 当成名字的一部分
                # 喂给谓词）。反查腿与同步腿同权，存名点仍每腿一枚（禁第二处）。
                sender_name=_neutralize_markers(
                    _display_safe_name(
                        str(sender.get("nickname") or sender.get("card") or "")
                    )
                ).strip(),
                text=_clip(_display_safe_text(text), per_level_chars),
                media_labels=media,
                media_refs=media_refs,
            )
        )
        node = fetched
    return chain


async def _maybe_await(value: Any) -> Any:
    """lookup 允许同步或异步实现。"""
    if hasattr(value, "__await__"):
        return await value
    return value


def collect_reply_chain(
    event: Any,
    *,
    max_depth: int = REPLY_CHAIN_MAX_DEPTH,
    per_level_chars: int = REPLY_CHAIN_PER_LEVEL_CHARS,
    nested_lookup: Any = None,
) -> list[ReplyChainItem]:
    """采集引用链（自近及远），跨 OneBot V11 与 Telegram。

    实现要点：
    - OneBot V11：``event.reply`` 是 ``Reply`` 模型，正文在 ``reply.message``
      （段列表），**必须读段列表而不是 get_plaintext()**——后者在 Reply 上根本
      不存在（这也是修复前引用恒为空的根因）。更深一层优先取非标的
      ``reply.reply``（``Reply`` 的 model_config 是 extra=allow，网关给出即保留）；
      否则读该层 ``message`` 里的 ``reply`` 段 id，并用 ``nested_lookup``
      （注入式，通常接 SnowLuma ``get_msg``）继续下钻。
    - Telegram：``event.reply_to_message`` 本身就是递归的 ``MessageEvent``，沿
      ``reply_to_message`` 逐层下行。
    - 每层记 message_id 并去重，防 A↔B 互引形成死循环。
    """
    if event is None or max_depth <= 0:
        return []
    chain: list[ReplyChainItem] = []
    seen: set[str] = set()
    node: Any = getattr(event, "reply", None) or getattr(event, "reply_to_message", None)
    layer = 1
    while node is not None and layer <= max_depth:
        # OneBot 的非标 `Reply.reply`（extra=allow）是**原始 dict**，而
        # `event.reply` / Telegram 的 `reply_to_message` 是模型对象；
        # 两种形态统一在这里取值。
        if isinstance(node, dict):
            message_id = str(node.get("message_id") or node.get("real_id") or "")
            sender_raw = node.get("sender")
            if isinstance(sender_raw, dict):
                sender_id = str(sender_raw.get("user_id") or "")
                sender_name = str(
                    sender_raw.get("card") or sender_raw.get("nickname") or ""
                )
            else:
                sender_id, sender_name = "", ""
            segments = node.get("message")
        else:
            message_id = str(
                getattr(node, "message_id", "") or getattr(node, "real_id", "") or ""
            )
            sender_id, sender_name = _sender_of(node)
            segments = getattr(node, "message", None)
        if message_id and message_id in seen:
            break
        if message_id:
            seen.add(message_id)
        text, media, media_refs = (
            _segments_to_text(segments)
            if segments is not None
            else ("", (), ())
        )
        if not text:
            text = _plain_of(node)
        chain.append(
            ReplyChainItem(
                layer=layer,
                message_id=message_id,
                sender_id=sender_id,
                # INJ-G1：两条取数腿（dict 分支与 _sender_of）都汇到这一个
                # 存名点，消毒放这里=单点两腿同权；format_reply_chain 不再
                # 二次过（禁双过变三处）。对照先例=合并转发腿昵称由
                # _neutralize_forward_body 在源头收口（root A-ING-1 波）。
                # P2-d：存名点包一层显示伪装处置（顺序：处置→块消毒），
                # 与反查腿同一把尺；正文走 `_display_safe_text`（内含同一枚
                # 内部标记真身，不再叠第二遍 `_neutralize_markers`）。
                sender_name=_neutralize_markers(_display_safe_name(sender_name)).strip(),
                text=_clip(_display_safe_text(text), per_level_chars),
                media_labels=media,
                media_refs=media_refs,
            )
        )
        # 下一层：OneBot 走非标 reply.reply；Telegram 走递归的 reply_to_message。
        if isinstance(node, dict):
            next_node = node.get("reply") or node.get("reply_to_message")
        else:
            next_node = getattr(node, "reply", None) or getattr(
                node, "reply_to_message", None
            )
        if next_node is None:
            # QQ 常态：本层 message 里带 reply 段（只有 id），需要反查才能下钻。
            nested_id = _replied_id_in_segments(segments)
            if nested_id and nested_id not in seen and callable(nested_lookup):
                try:
                    next_node = nested_lookup(nested_id)
                except Exception:  # noqa: BLE001 - 反查失败按链条结束处理。
                    next_node = None
            if next_node is None and nested_id and nested_id not in seen:
                # 无反查能力时至少记录一层占位，明确告知模型"还有更深一层"。
                chain.append(
                    ReplyChainItem(
                        layer=layer + 1,
                        message_id=nested_id,
                        text="[引用层级未展开]",
                    )
                )
                break
        node = next_node
        layer += 1
    return chain


def format_reply_chain(
    chain: list[ReplyChainItem] | None,
    *,
    total_chars: int = REPLY_CHAIN_TOTAL_CHARS,
) -> str:
    """把引用链渲染成逐层闭合的提示词块（预算在本函数，消毒在采集处）。

    准确口径（INJ-G1 修正，旧 docstring 写「已消毒」曾为半真）：正文与发送者
    名都已在 ``collect_reply_chain`` / ``collect_reply_chain_async`` 存入
    ``ReplyChainItem`` 前过 ``_neutralize_markers``，本函数才敢把名字原样拼进
    块头 ``[引用回复 层级N 名字]``；本函数自身不做任何消毒，只做逐层闭合渲染
    与整链总预算。多层逐层输出，便于模型区分"当前这话"与"被引用的旧话"，
    并在信息不足时显式给出层级达上限的提示。
    """
    items = list(chain or [])
    if not items:
        return ""
    blocks: list[str] = []
    for item in items:
        body = item.text.strip()
        extra = (" " + " ".join(item.media_labels)) if item.media_labels else ""
        who = f" {item.sender_name}" if item.sender_name else ""
        if not body and not extra:
            continue
        blocks.append(
            f"[引用回复 层级{item.layer}{who}] {body}{extra} [/引用回复 层级{item.layer}]"
        )
    if not blocks:
        return ""
    joined = "\n".join(blocks)
    if len(joined) > total_chars:
        joined = joined[: max(0, total_chars - 1)].rstrip() + _ELLIPSIS
    elif len(items) >= REPLY_CHAIN_MAX_DEPTH:
        joined = f"{joined}\n[引用层级已达上限]"
    return joined



# ---------------------------------------------------------------------------
# 发件人展示名读取（需求 4 · 2026-09-28 S-META）
# ---------------------------------------------------------------------------
# 病根：摄取层只读 OneBot V11 的 ``event.sender.card / .nickname``
# （``__init__.py`` 的 ``_incoming_from_nonebot_event``），而 Telegram 的事件形态是
# ``event.message.from_user``（User：first_name/last_name/username）、邮件是
# ``event.mail_date_envelopes``/``message`` 上的 From 显示名——两通道在**这一段代码里
# 根本没有对应的读取分支**，于是 ``IncomingMessage.sender_display_name`` 对 TG/Mail
# 恒为 None，每轮提示词的身份面（``chat.py`` 的 ``sender_profile_note``）长期空转。
# 本段是**读件**：只做「从事件里把该通道在册的字段取出来」这一件事，消毒与
# 装配都不在这里（装配点在根摄取函数，属 hub 补丁；名字进提示词前仍走既有
# ``_neutralize_markers``/出站打码，不在读件里另开一条）。
#
# 铁律：取不到就回 None，**绝不**用 sender_id（用户号）冒充名字——与
# ``participant_memory`` 那条「绝不拿用户号顶上」的在册禁令同口径。


def _clean(value: Any) -> str:
    return str(value or "").strip()


def telegram_sender_display_name(event: Any) -> str | None:
    """TG 发件人展示名：``<first_name> <last_name>``，两者皆空时退 ``@username``。

    源＝``event.message.from_user``（适配器解析出的 User 对象）；私聊里事件顶层
    也可能直接挂 ``from_user``，两处都试，取第一个非空。全空 ⇒ None（不猜）。
    """
    for holder in (
        getattr(event, "message", None),
        event,
    ):
        user = getattr(holder, "from_user", None) if holder is not None else None
        if user is None:
            continue
        full = " ".join(
            part
            for part in (_clean(getattr(user, "first_name", "")), _clean(getattr(user, "last_name", "")))
            if part
        )
        if full:
            return full
        username = _clean(getattr(user, "username", "")).lstrip("@")
        if username:
            return f"@{username}"
    return None


def mail_sender_display_name(event: Any) -> str | None:
    """邮件发件人展示名：From 头的显示名（``李雷 <lee@example.com>`` 里的「李雷」）。

    真身在适配器：``nonebot/adapters/mail/utils.py`` 的 ``parse_byte_mail`` 逐封解出
    ``recipients_to/recipients_cc/reply_to``，From 显示名挂在 ``event.mail_from``
    （Mail-Adapter 的 Address 对象：``name`` + ``email``）或 ``message.from_`` 上。
    这里按「有 name 用 name；只有 email 就回 None」判定——地址本身已经在
    ``sender_id`` 里了，拿它当昵称是冒充。
    """
    for holder in (getattr(event, "mail_from", None), getattr(event, "message", None), event):
        if holder is None:
            continue
        for attr in ("name", "display_name"):
            label = _clean(getattr(holder, attr, ""))
            if label:
                return label
    return None


def sender_display_name_for_event(event: Any, normalized_adapter: str) -> str | None:
    """按通道取展示名；QQ 走既有 card/nickname 优先级，此处不插手（返回 None）。

    ``normalized_adapter`` 用摄取层已归一好的小写适配器名（``telegram`` /
    ``mail`` / 其余＝OneBot）。返回 None 的含义是「本读件对该通道没有补充」，
    调用方保留自己算出的值——QQ 侧的 card/nickname 优先级是既有行为，
    本函数刻意不复制一份第二判据（两处判据早晚打架）。
    """
    name = (normalized_adapter or "").strip().lower()
    if name == "telegram":
        return telegram_sender_display_name(event)
    if name == "mail":
        return mail_sender_display_name(event)
    return None
