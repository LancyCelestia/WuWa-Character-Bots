"""群信息能力（bot.group_info）：群资料/群主/人数/公告/精华，一问直答。

来源：审查 B-01/B-04——用户实测问「群主是谁/群人数/群公告」答不上，根因是
OneBot V11/NapCat 明明支持群 API（get_group_info / get_group_member_list /
get_group_notice / get_essence_msg_list）而全仓零调用。本能力补齐这条链路。

权限分级（复用媒体归档的 _role_atLeast 同款角色秩模式）：
- 群名/群主/人数/上限/管理员数：全员；
- 公告首段与精华条数：仅管理员（bot 侧角色门，协议侧再失败即如实降级）。

隐私与刷屏红线：成员名单**不整列**——只给统计数与群主/管理员数，
绝不输出逐个成员的名单。

诚实降级清单（协议无标准 API，不做不假装）：
- 群链接/群分享、群等级/群标签、群相册——查不了就直说查不了，绝不编造；
- 「本群多大了」依赖协议返回的建群时间字段（NapCat 扩展，非 V11 标准）：
  字段在就算天数，字段不在就如实说拿不到；
- API 失败/未接线/无权限：如实口语降级，不编数据、不静默吞掉。

缓存：群资料 600s/成员列表 900s/公告 600s/精华 600s，见
runtime/group_cache.py（只缓存成功载荷）。

接线说明（主会话负责 __init__.py）：能力运行在管线 offload 线程池（同步
调用），而 bot.call_api 是协程——由 ``build_onebot_api_bridge`` 提供
run_coroutine_threadsafe 桥接，构建工厂时以 ``api=`` 注入；``api=None``
时所有查询走诚实降级（不炸、不装）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.runtime.group_cache import (
    KIND_ESSENCE,
    KIND_MEMBERS,
    KIND_NOTICE,
    KIND_PROFILE,
    GroupInfoCache,
)

# ---------------------------------------------------------------------------
# 触发词与意图（T-Spec 口径：CJK 复合词，词界天然安全；刻意不收英文裸词，
# 避免 group/notice 这类英文口语劫持；ASCII 词边界纪律因此不适用）
# ---------------------------------------------------------------------------

_INTENT_OWNER_WORDS: tuple[str, ...] = ("群主是谁", "谁是群主", "群主")
_INTENT_COUNT_WORDS: tuple[str, ...] = ("群人数", "本群人数", "本群多少人")
_INTENT_AGE_WORDS: tuple[str, ...] = ("本群多大了", "群多大了", "本群多大", "群多大")
_INTENT_NOTICE_WORDS: tuple[str, ...] = ("群公告", "本群公告")
_INTENT_ESSENCE_WORDS: tuple[str, ...] = ("群精华", "本群精华", "精华消息")
_INTENT_PROFILE_WORDS: tuple[str, ...] = ("群信息", "本群信息", "群资料", "本群资料")

# 词 → 意图（插入序=分组序；sorted by len 保证最长词优先消歧）。
_INTENT_OF_WORD: dict[str, str] = {
    word: intent
    for intent, words in (
        ("profile", _INTENT_PROFILE_WORDS),
        ("owner", _INTENT_OWNER_WORDS),
        ("count", _INTENT_COUNT_WORDS),
        ("age", _INTENT_AGE_WORDS),
        ("notice", _INTENT_NOTICE_WORDS),
        ("essence", _INTENT_ESSENCE_WORDS),
    )
    for word in words
}

# 全部触发词（is_group_info_command 的判定面；触发体检从此函数字面提取）。
GROUP_INFO_TRIGGER_WORDS: tuple[str, ...] = tuple(_INTENT_OF_WORD)

# 词尾边界字（与 media_archive 同哲学的保守边界：触发词后只能跟标点/语气
# 助词/空白，防「群主管」「群信息表」类包含词误触发）。
_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈～~哦嘛咯哇"

_NOTICE_SNIPPET_CHARS = 100
_PRIVATE_HINT = "群信息要在群里问才行哦，去群里喊我一声，我帮你看本群的资料～"
_UNAVAILABLE_LINE = "群资料接口这会儿没回应，这部分先不答啦——不瞎猜，过会儿再问一次试试？"


def is_group_info_command(text: str) -> bool:
    """触发词判定：整句等于触发词，或触发词后跟标点/语气边界（同媒体归档）。"""
    stripped = (text or "").strip().replace("\r", " ").replace("\n", " ")
    if not stripped:
        return False
    for word in sorted(GROUP_INFO_TRIGGER_WORDS, key=len, reverse=True):
        if stripped == word:
            return True
        if stripped.startswith(word):
            tail = stripped[len(word):]
            if not tail or tail[0] in _BOUNDARY_CHARS:
                return True
    return False


def detect_group_info_intents(text: str) -> frozenset[str]:
    """把触发文本解析成意图集（profile/owner/count/age/notice/essence）。

    命中多个词形时按最长词优先取其一（词形互斥设计，实际至多一个）；
    空集 = 未识别（调用方按全量档案处理或忽略）。
    """
    stripped = (text or "").strip().replace("\r", " ").replace("\n", " ")
    for word in sorted(GROUP_INFO_TRIGGER_WORDS, key=len, reverse=True):
        if stripped == word or (
            stripped.startswith(word)
            and (len(stripped) == len(word) or stripped[len(word)] in _BOUNDARY_CHARS)
        ):
            return frozenset({_INTENT_OF_WORD[word]})
    return frozenset()


def _role_at_least(sender_roles: list[str], min_role: str) -> bool:
    """角色秩判定（与 media_archive 同语义：max(角色) >= 所需档）。"""
    rank: dict[str, int] = {
        "user": 0,
        "trusted": 1,
        "enterprise": 2,
        "admin": 3,
        "super_admin": 4,
    }
    required = rank.get(str(min_role).strip().lower(), 4)
    return max((rank.get(role, -1) for role in sender_roles), default=-1) >= required


def build_onebot_api_bridge(
    bot: Any,
    loop: Any,
    timeout: float = 8.0,
) -> Callable[[str], Any]:
    """把异步 ``bot.call_api`` 桥接成能力线程可用的同步调用。

    能力在管线 offload 线程池执行，OneBot API 是事件循环上的协程；
    用 run_coroutine_threadsafe 跨线程投递并限时等结果（超时抛异常，
    由能力层按「接口没回应」诚实降级）。主会话在 __init__.py 装配：
    ``api=build_onebot_api_bridge(bot, asyncio.get_running_loop())``。
    """

    def call(action: str, **params: Any) -> Any:
        coro = bot.call_api(action, **params)
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout)

    return call


def _first_paragraph(text: str, limit: int = _NOTICE_SNIPPET_CHARS) -> str:
    """取公告首段（首个非空行）并截断；超长以省略号收尾。"""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:limit] + ("…" if len(line) > limit else "")
    return ""


def _segment_text(payload: Any) -> str:
    """从 get_group_notice 的 message 字段提取纯文本（dict/list 双形态兼容）。"""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str):
            return text
        if isinstance(text, list):
            parts: list[str] = []
            for seg in text:
                if isinstance(seg, dict):
                    parts.append(str(seg.get("text") or ""))
                elif isinstance(seg, str):
                    parts.append(seg)
            return "".join(parts)
    return ""


# 进程内共享缓存（同群反复被问不重复打协议；测试注入独立实例）。
_SHARED_CACHE = GroupInfoCache()


def build_group_info_capability(
    config: Any | None = None,
    *,
    api: Callable[[str], Any] | None = None,
    cache: GroupInfoCache | None = None,
) -> Callable[[IncomingMessage, Any], CapabilityResult]:
    """构建群信息能力。

    ``api``：同步群 API 调用器 ``api(action, **params) -> payload``（由
    build_onebot_api_bridge 桥接注入；None=未接线，全部诚实降级）。
    ``cache``：TTL 缓存（None=进程内共享实例；测试注入独立实例）。
    ``config``：预留（本能力暂无配置键，不设开关即无死键——触发面由
    路由表与权限门收口）。
    """
    del config  # 显式不用：避免「看似可配实则无效」的假配置面。
    store = cache or _SHARED_CACHE

    def _call(action: str, **params: Any) -> Any:
        if api is None:
            return None
        try:
            return api(action, **params)
        except Exception:  # noqa: BLE001 - 协议失败一律降级，不编造。
            return None

    def _fetch(kind: str, group_id: str, action: str) -> tuple[bool, Any]:
        """缓存穿透读取；只缓存成功载荷（None=失败，不落缓存可重试）。"""
        hit, value = store.get(kind, group_id)
        if hit:
            return True, value
        payload = _call(action, group_id=int(group_id))
        if payload is None:
            return False, None
        store.put(kind, group_id, payload)
        return True, payload

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = message.plain_text or ""

        def _result(
            body: str, *, audit: list[str], title: str = "群信息"
        ) -> CapabilityResult:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.group_info",
                kind="text",
                title=title,
                body=body,
                send_policy=SendPolicy.IMMEDIATE,
                audit_tags=audit,
            )

        if not is_group_info_command(text):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.group_info",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["group_info", "skip_no_trigger"],
            )

        # 私聊：群 API 无对象可查，回守岸人口语提示（不做不假装）。
        if message.session_type.value != "group":
            return _result(_PRIVATE_HINT, audit=["group_info", "private_hint"])

        group_id = str(message.group_id or "").strip()
        if not group_id.isdigit():
            return _result(
                "这条消息里没拿到群号，本群资料暂时查不了啦。",
                audit=["group_info", "no_group_id"],
            )

        intents = detect_group_info_intents(text)
        if not intents:
            intents = frozenset({"profile"})
        audit = ["group_info"]

        # 权限门：公告与精华仅管理员（全员问资料/人数不设门）。
        wants_privileged = bool({"notice", "essence"} & intents)
        is_admin = _role_at_least(list(message.sender_roles), "admin")
        if wants_privileged and not is_admin:
            return _result(
                "公告和精华只有管理员能看哦，先不给你翻这份啦。",
                audit=[*audit, "denied_role"],
            )

        profile: dict[str, Any] | None = None
        members: list[dict[str, Any]] | None = None
        notices: list[dict[str, Any]] | None = None
        essence: list[dict[str, Any]] | None = None

        if "count" in intents or "profile" in intents or "age" in intents:
            ok, payload = _fetch(KIND_PROFILE, group_id, "get_group_info")
            profile = payload if ok and isinstance(payload, dict) else None
            if ok and not isinstance(payload, dict):
                audit.append("api_shape_profile")
        if "owner" in intents or "profile" in intents:
            ok, payload = _fetch(KIND_MEMBERS, group_id, "get_group_member_list")
            members = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_members")
        if "notice" in intents or ("profile" in intents and is_admin):
            ok, payload = _fetch(KIND_NOTICE, group_id, "get_group_notice")
            notices = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_notice")
        if "essence" in intents or ("profile" in intents and is_admin):
            ok, payload = _fetch(KIND_ESSENCE, group_id, "get_essence_msg_list")
            essence = payload if ok and isinstance(payload, list) else None
            if ok and not isinstance(payload, list):
                audit.append("api_shape_essence")

        lines: list[str] = []

        # ---- 群名 / 人数 / 上限（profile/age/count 共用）----
        if profile is not None:
            name = str(profile.get("group_name") or "").strip()
            if name:
                lines.append(f"群名：{name}")
            count = profile.get("member_count")
            cap = profile.get("max_member_count")
            if isinstance(count, int) and isinstance(cap, int):
                lines.append(f"人数：{count}/{cap}")
            elif isinstance(count, int):
                lines.append(f"人数：{count}")
        elif {"profile", "count", "age"} & intents:
            lines.append(_UNAVAILABLE_LINE)

        # ---- 群主 / 管理员数（成员列表统计，名单绝不整列）----
        if "owner" in intents or "profile" in intents:
            if members is None:
                lines.append("群主：成员名单这会儿拿不到，先不猜是谁啦。")
            else:
                owners = [
                    item
                    for item in members
                    if isinstance(item, dict) and str(item.get("role") or "") == "owner"
                ]
                admins = sum(
                    1
                    for item in members
                    if isinstance(item, dict) and str(item.get("role") or "") == "admin"
                )
                if owners:
                    owner = owners[0]
                    display = str(owner.get("card") or owner.get("nickname") or "").strip()
                    uid = str(owner.get("user_id") or "").strip()
                    label = display or "群主"
                    lines.append(f"群主：{label}" + (f"（{uid}）" if uid else ""))
                else:
                    lines.append("群主：名单里没有 role=owner 的成员，先不硬指认啦。")
                if admins and "profile" in intents:
                    lines.append(f"管理员：{admins} 人")

        # ---- 建群时长（NapCat 扩展字段，非 V11 标准；不在就诚实说）----
        if "age" in intents and profile is not None:
            create_ts = profile.get("group_create_time")
            if isinstance(create_ts, (int, float)) and create_ts > 0:
                days = max(0, int((message.timestamp.timestamp() - create_ts) // 86400))
                lines.append(f"建群：约 {days} 天啦")
            else:
                lines.append("建群时间：协议里没给这个字段，答不了，不瞎猜哦。")

        # ---- 公告首段 / 精华条数（仅管理员可见；失败与为空分开说）----
        if wants_privileged or ("profile" in intents and is_admin):
            if notices is None:
                lines.append("公告：接口这会儿没回应，拿不到（可能需要我有管理员身份）。")
            else:
                snippet = _first_paragraph(_segment_text(notices[0])) if notices else ""
                lines.append("公告：" + (snippet or "群里现在还没有公告。"))
            if essence is None:
                lines.append("精华：接口这会儿没回应，拿不到（可能需要我有管理员身份）。")
            else:
                lines.append(f"精华：一共收了 {len(essence)} 条。")

        return _result("\n".join(lines), audit=audit)

    return capability
