"""统一会话画像采集层（需求 4 · 2026-09-29 S-META 二批）。

## 这层解决什么

一期（2026-09-25～09-28，逐格对账见
``.superpowers/sdd/2026-09-26-goal18-second/logs/S-META-AUDIT-4.md``，实现见
``capabilities/group_info.py``）把「读得到」逐格接上了：群务八格、QQ 对端账号资料、
TG 群主与管理员腿、邮件的诚实缺失句。但那些读出来的是**文本行**——每加一条腿都要重新判
一次「这格算不算读到了」，权限判断也散在各处 ``if``。本层把同一批事实收成一个
**结构化画像**：每格自带

- ``state``（六态分立，见下）、``source``（当场事实 / 协议端读数 / 我的记录 / 本地账本）、
  ``fetched_at``（采集时刻，新鲜度可算）、``confidence``（**由 source 派生**，不手写第二份）、
  ``reason``（缺数原因）、``visibility``（这一格能给谁看）。

六态分立：``ok`` / ``empty``（回了空值）/ ``missing``（**没回这个字段**）/ ``failed``
（真去问了却问不出来）/ ``unprobed``（这轮压根没去问）/ ``absent``（该平台结构性没有这一格，
带核证理由）/ ``forbidden``（权限或隐私门拦下）。任两态都不许塌成一句万金油降级——一期已
锁过 ``unprobed`` 不得被说成 ``failed``（那等于谎报一次没发生过的请求），本层把这条判据从
「每条腿各写一遍」升成「采集处只写一次」。

## 与一期的关系：一份取数，两处投影

本层**不复制任何取数件**：QQ 对端资料读件（``read_qq_account_meta`` 一族）、载荷归一
（``_as_mapping``）、公告首段（``_first_paragraph``）、字段候选表（相册/待办）、角色秩
（``_role_at_least``）、群号形态判定（``_is_group_scoped_id``）一律**从一期的
``capabilities/group_info.py`` 导入**（``import _x as x`` 形态）。方向刻意是
「画像层 → 一期真身」，``group_info`` 不反向导入本层——它今天正被别席改写（并发在飞），
搬动它的代码会撞面；等它落袋后再谈把两处投影合并成一条腿（见 ledger 待办 ④）。
缓存 kind 沿用 ``group_cache`` 的同一张登记表，所以同一次问话里画像层与命令腿
**命中同一条缓存项**，不会各打一遍协议。

两个投影面：

- ``answer_lines``：显式命令的回答（守岸人口吻，逐格分态说话）；
- ``note_text``：每轮提示词的注入串（``键=值；…``，只收 ``NOTE_KEYS`` 白名单内的格，
  参与者 / 名单 / 群文件概览**刻意不在白名单**——把别人的话事记录长期铺给模型是另一条
  隐私线，与「显式命令才答参与者」的既有口径一致）。

## 门是结构性的，不是每次记得写 if

被拦下或被判缺席的格子，在 ``ProfileField`` 里 **``value`` 恒为空串**，且**取数前就被拦
（一次接口都不打）**——「把别人的签名/在线状态/账号号泄露给第三方」在结构上写不出来。
三条在册红线：

1. **对端账号面**（``VIS_SELF``：账号号 / 个性签名 / 在线状态 / 电量 / 等级）只给本人。
   「本人」判据＝``subject_user_id == message.sender_id``（问话人问自己）；问别人的这几格
   ⇒ ``forbidden``。
2. **群内公开面**（``VIS_SESSION``：群名 / 群号 / 群介绍 / 人数 / 群主与管理员统计 / 相册层
   概览 / 待办概览 / 群文件概览）——但**跨会话拒绝**：``target_group_id`` 不等于本事件所在群
   时整片 ``forbidden`` 且零调用（这是「拿 A 群的号套 B 群资料」的根形态）。
   成员**全量名单**任何情况下都不整列（一期隐私红线，本层以 ``absent`` 明示理由）。
3. **特权面**（``VIS_ADMINS``：公告首段 / 精华条数）沿用一期 bot 侧角色秩（``admin`` 起）。

## 平台事实（逐格判据；取证现算于 2026-09-29，详见 ledger seat-META.md 的可得性表）

- **QQ / SnowLuma**：动作册真身 ``C:\\Software\\SnowLuma\\config-CEQwQxHY.js``（现役
  ``index.mjs`` import 的那份）。本席现算：定义条目 197 处命中；``get_stranger_info`` /
  ``nc_get_user_status`` / ``get_group_honor_info`` / ``get_group_root_files`` **在册**；
  ``lucky`` / 「幸运」**零命中** ⇒ 幸运符号与群幸运符号是 ``absent``（最接近的
  ``get_group_signed_list`` 是「今日打卡」）。对端资料走 ``get_stranger_info``
  （``nickname``/``long_nick``/``level``/``status``/``batteryStatus``）。**电量字段在册、
  但值是否恒 0 属运行时事实 ⇒ 0/空一律 ``missing``**，绝不写成「电量 0%」（一期同口径）。
  群文件协议全量口（``get_group_root_files`` 等）在册未接 ⇒ 本层 ``files`` 只吃本地账本，
  没账本就 ``missing``，不拿未核的动作名去猜。
- **Telegram**（Bot API + 本仓实装适配器双源）：``get_chat``/``get_chat_member_count``/
  ``get_chat_member``/``get_chat_administrators`` 在册 ⇒ 群名/介绍/置顶/人数/群主与管理员/
  本人身份与头衔可得；**在线状态、精华、相册、待办、群文件、成员全量名单**没有对应方法 ⇒
  ``absent``（理由一律写「Bot API」，与「我没去查」分家）。``bio``（签名）只在私聊
  ``getChat`` 回，群内取不到 ⇒ 群档这一格 ``absent``。
- **Mail**：SMTP/IMAP 不经营群务 ⇒ 群族整体 ``absent``；``From`` 显示名 / ``To`` / ``Cc`` /
  主题是「适配器解得出、摄取链未带」⇒ ``missing`` 并留票号 **T-META-INGEST-1**（能拿没接
  ≠ 协议没有）；``Bcc`` 按投递语义在收信侧本就不存在 ⇒ 唯一的真 ``absent``。
- **自身信息**：台账 #60★ 硬红线「禁读 ``get_login_info`` 认自身名」——本层**不碰**该动作，
  bot 自身的名字走人格册与配置真身（别席在办），这里只采集**对端与会话**的事实。

本层**不写任何 Runtime 数据**，也不自己开库：参与者腿只吃调用方传进来的读数结果
（``participant_memory.HistoryParticipantReader`` 的产物），拿不到就是 ``failed``。

诚实原则落点：拿不到按态说；禁止把 ``missing``/``failed`` 说成「没有」，禁止把
``unprobed`` 说成「接口没答上」，禁止把 ``absent`` 说成「还没做」。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import (
    group_info as _gi,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.group_cache import (
    KIND_ADMINS,
    KIND_ALBUM,
    KIND_ESSENCE,
    KIND_MEMBER_COUNT,
    KIND_MEMBERS,
    KIND_NOTICE,
    KIND_PEER_PROFILE,
    KIND_PROFILE,
    KIND_SELF_MEMBER,
    KIND_TODO,
    GroupInfoCache,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime.participant_memory import (
    STATE_EMPTY,
    STATE_OK,
)
from plugins.bot_unified_runtime.domains.core.session_keys import parse_session_key

# 一期真身的再导出（**不在本层重写第二份**：取数件、映射表、角色秩全部指回 group_info）。
as_mapping = _gi._as_mapping
meta_scalar = _gi._meta_scalar
first_paragraph = _gi._first_paragraph
segment_text = _gi._segment_text
first_str = _gi._first_str
first_int = _gi._first_int
role_at_least = _gi._role_at_least
is_group_scoped_id = _gi._is_group_scoped_id
read_qq_account_meta = _gi.read_qq_account_meta
qq_meta_probe_state = _gi.qq_meta_probe_state
format_qq_account_meta_note = _gi.format_qq_account_meta_note
ALBUM_NAME_KEYS = _gi._ALBUM_NAME_KEYS
ALBUM_PIC_COUNT_KEYS = _gi._ALBUM_PIC_COUNT_KEYS
TODO_TITLE_KEYS = _gi._TODO_TITLE_KEYS
SECTION_LINE_LIMIT = _gi._SECTION_LINE_LIMIT
NOTICE_SNIPPET_CHARS = _gi._NOTICE_SNIPPET_CHARS
KIND_QQ_ACCOUNT_META = _gi.KIND_QQ_ACCOUNT_META
QQ_ACCOUNT_META_ACTION = _gi.QQ_ACCOUNT_META_ACTION
QQ_ACCOUNT_META_TTL_SECONDS = _gi.QQ_ACCOUNT_META_TTL_SECONDS
QQ_META_LABELS = _gi._QQ_META_LABELS
QQ_META_PROBE_OK = _gi.QQ_META_PROBE_OK
QQ_META_PROBE_FAILED = _gi.QQ_META_PROBE_FAILED
QQ_META_PROBE_UNPROBED = _gi.QQ_META_PROBE_UNPROBED
QQ_META_UNPROBED_ANSWER = _gi.QQ_META_UNPROBED_ANSWER

__all__ = [
    "FIELD_ABSENT",
    "FIELD_EMPTY",
    "FIELD_FAILED",
    "FIELD_FORBIDDEN",
    "FIELD_MISSING",
    "FIELD_OK",
    "FIELD_UNPROBED",
    "NOTE_KEYS",
    "ConversationProfile",
    "ProfileField",
    "answer_lines",
    "as_mapping",
    "build_profile",
    "fetch_through_cache",
    "format_qq_account_meta_note",
    "make_shared_cache",
    "note_text",
    "qq_meta_probe_state",
    "read_qq_account_meta",
    "role_at_least",
]

# ---------------------------------------------------------------------------
# 六态（+forbidden）、来源、可见级
# ---------------------------------------------------------------------------

FIELD_OK = "ok"
#: 接口/事件**回了值但值是空的**——多半是没设置，也可能没回全，不替对方断言原因。
FIELD_EMPTY = "empty"
#: 载荷里**没有这个字段**。「没回」与「回了空」是两件事（一期已吃过这个混淆）。
FIELD_MISSING = "missing"
#: 真去问了却问不出来（超时、报错、形状读不出）。
FIELD_FAILED = "failed"
#: 这轮压根没去问：桥未接线，或没有可问的对象号。
FIELD_UNPROBED = "unprobed"
#: 该平台结构性没有这一格（理由必须带核证线索）。
FIELD_ABSENT = "absent"
#: 权限或隐私门拦下：值恒空，且取数前就被拦（一次接口都不打）。
FIELD_FORBIDDEN = "forbidden"

SOURCE_EVENT = "event"
SOURCE_PROTOCOL = "protocol"
SOURCE_MEMORY = "memory"
SOURCE_LEDGER = "ledger"

#: 可信度**由来源派生**（规则 10 同族：不手写第二份会漂移的表）。
CONFIDENCE_DIRECT = "当场事实（事件自带）"
CONFIDENCE_PROTOCOL = "协议端读数（受 TTL 约束）"
CONFIDENCE_MEMORY = "我的会话记录（按记忆算，不是名单）"
CONFIDENCE_LEDGER = "本地账本（只覆盖我见过的上传）"
_CONFIDENCE_BY_SOURCE: dict[str, str] = {
    SOURCE_EVENT: CONFIDENCE_DIRECT,
    SOURCE_PROTOCOL: CONFIDENCE_PROTOCOL,
    SOURCE_MEMORY: CONFIDENCE_MEMORY,
    SOURCE_LEDGER: CONFIDENCE_LEDGER,
}

VIS_SELF = "self_only"
VIS_SESSION = "session"
VIS_ADMINS = "admins"

#: 注入白名单：**只有这些格进每轮提示词**。参与者/名单/相册/待办/群文件刻意不在内——
#: 长期把别人的话事记录与群务清单铺给模型是另一条隐私线（一期只在显式命令里答）。
NOTE_KEYS: frozenset[str] = frozenset(
    {
        "account_id",
        "nickname",
        "group_id",
        "group_name",
        "group_card",
        "group_title",
        "group_role",
        "level",
        "signature",
        "online_status",
        "battery",
        "session_id",
        "mailbox",
        "display_name",
    }
)

#: 未探测态的总句（一期 ``QQ_META_UNPROBED_ANSWER`` 的结构版）：**不含任何在线/离线断言**，
#: 也不假托「接口没答上」。
NOTE_UNPROBED_LINE = "这一轮没有可问的协议端（桥未接线），这几格是没去探测，不是查不到。"
#: 被门拦下时的答句：只说「这几格不给」，不透露格子里到底有没有值。
NOTE_FORBIDDEN_LINE = "这几格是别人的账号面或需要管理员身份，我不往外报。"


def clip(value: str, limit: int = NOTICE_SNIPPET_CHARS) -> str:
    """展示侧截断（长签名/长待办标题进提示词要有帽，超了必须点名）。"""
    text = (value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# 画像结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileField:
    """画像里的一格。``state`` 非 ``ok`` 时 ``value`` 恒为空串（结构性防泄露）。"""

    key: str
    label: str
    state: str
    source: str
    visibility: str
    value: str = ""
    reason: str = ""
    fetched_at: float | None = None

    @property
    def confidence(self) -> str:
        return _CONFIDENCE_BY_SOURCE.get(self.source, "未知来源（不替你担保）")

    @property
    def ok(self) -> bool:
        return self.state == FIELD_OK and bool(self.value)


@dataclass(frozen=True)
class ConversationProfile:
    platform: str
    scope: str
    subject_user_id: str
    group_id: str
    built_at: float
    fields: tuple[ProfileField, ...]

    def get(self, key: str) -> ProfileField:
        """按 key 取一格；**取不到就抛**——静默回 ``None`` 会让调用方把「没这格」
        写成「这格是空的」，那是本层最忌的两种混态之一。"""
        for item in self.fields:
            if item.key == key:
                return item
        raise KeyError(key)

    def states(self) -> dict[str, str]:
        return {item.key: item.state for item in self.fields}

    def visible(self, *, is_self: bool, privileged: bool) -> tuple[ProfileField, ...]:
        """展示侧的二次闸：即使构造处漏了门，这里也不会把 ``VIS_SELF`` 格给外人看。"""
        out: list[ProfileField] = []
        for item in self.fields:
            if item.visibility == VIS_SELF and not is_self:
                continue
            if item.visibility == VIS_ADMINS and not privileged:
                continue
            out.append(item)
        return tuple(out)


def make_shared_cache(
    *, clock: Callable[[], float] = time.monotonic, max_entries: int = 512
) -> GroupInfoCache:
    """带 QQ 对端资料 kind 登记的缓存实例。

    一期在 ``group_info._SHARED_CACHE`` 上就地补过同一条登记（``group_cache`` 的缺省表里
    没有这个 kind，未登记＝TTL 0＝永不缓存＝每轮一次 RPC）。本层给同一个补登记做成
    可复用的工厂，别让下一个接手再踩一次这个坑。
    """
    return GroupInfoCache(
        ttl_by_kind={KIND_QQ_ACCOUNT_META: QQ_ACCOUNT_META_TTL_SECONDS},
        clock=clock,
        max_entries=max_entries,
    )


Fetch = Callable[..., tuple[bool, Any]]
ApiLike = Callable[..., Any]


def fetch_through_cache(
    cache: GroupInfoCache,
    api: ApiLike,
    kind: str,
    key: str,
    action: str,
    **params: Any,
) -> tuple[bool, Any]:
    """缓存穿透读口（一期 ``group_info._fetch`` 的同语义，本层给装配点复用的公开形）。

    ``api`` 是一期那座桥的签名 ``api(action, **params) -> payload``（失败回 ``None``，
    也可直接回 ``(ok, payload)`` 二元组）。**只缓存成功载荷**：失败不落缓存，下次可重试
    ——「接口失败」与「接口没数据」都不许被旧值或失败态钉死。
    """
    hit, value = cache.get(kind, key)
    if hit:
        return True, value
    try:
        payload = api(action, **params)
    except Exception:  # noqa: BLE001 - 协议异常按「问不出来」降级，不炸会话。
        return False, None
    if payload is None:
        return False, None
    ok, body = payload if isinstance(payload, tuple) else (True, payload)
    if not ok or body is None:
        return False, None
    cache.put(kind, key, body)
    return True, body


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------


class _Ctx:
    """一次采集的上下文：读口记忆化（同一载荷只打一次），门在取数之前。"""

    def __init__(
        self,
        message: IncomingMessage,
        fetch: Fetch,
        *,
        api_available: bool,
        clock: Callable[[], float],
        subject_user_id: str,
        target_group_id: str,
        participant_memory: Any,
        group_file_summary: str,
    ) -> None:
        self.message = message
        self.fetch = fetch
        self.api_available = api_available
        self.now = float(clock())
        sender = str(message.sender_id or "").strip()
        self.subject = str(subject_user_id or "").strip() or sender
        self.is_self = bool(self.subject) and self.subject == sender
        roles = [str(r) for r in (getattr(message, "sender_roles", ()) or ())]
        self.privileged = role_at_least(roles, "admin")
        self.participant_memory = participant_memory
        self.group_file_summary = group_file_summary
        self.platform = str(message.platform or "").strip().lower()
        self.scope = str(getattr(getattr(message, "session_type", ""), "value", "") or "").strip()
        self.event_group_id = str(message.group_id or "").strip()
        wanted = str(target_group_id or "").strip()
        self.group_id = wanted or self.event_group_id
        # 跨会话判定：问的不是本事件所在群 ⇒ 群域整片拒绝，且一次接口都不打。
        self.group_refused = bool(wanted) and wanted != self.event_group_id
        self._memo: dict[tuple[Any, ...], tuple[bool, Any]] = {}
        self._meta_cache: tuple[dict[str, str], list[str], tuple[bool, Any]] | None = None

    # -- 门 ------------------------------------------------------------------
    def allowed(self, visibility: str) -> bool:
        if visibility == VIS_SELF:
            return self.is_self
        if visibility == VIS_ADMINS:
            return self.privileged
        return True

    # -- 读 ------------------------------------------------------------------
    def event(self, attr: str) -> tuple[str, bool]:
        raw = getattr(self.message, attr, None)
        if raw is None:
            return "", False
        return str(raw).strip(), True

    def payload(self, kind: str, key: str, action: str, **params: Any) -> tuple[bool, Any]:
        memo_key = (kind, key, action, tuple(sorted(params.items())))
        if memo_key in self._memo:
            return self._memo[memo_key]
        if not self.api_available:
            result: tuple[bool, Any] = (False, None)
        else:
            try:
                result = self.fetch(kind, key, action, **params)
            except Exception:  # noqa: BLE001 - 协议异常按「问不出来」处理，不炸会话。
                result = (False, None)
        self._memo[memo_key] = result
        return result

    def read(self) -> Fetch:
        """把一期读件要的 ``(kind, key, action, **params)`` 读口接回本层的记忆化读。"""

        def wrapped(kind: str, key: str, action: str, **params: Any) -> tuple[bool, Any]:
            return self.payload(kind, key, action, **params)

        return wrapped

    def qq_meta(self) -> tuple[dict[str, str], list[str], tuple[bool, Any]]:
        """对端账号资料：一次 ``get_stranger_info``，多格共用（同键去重靠 read 的缓存）。"""
        if self._meta_cache is not None:
            return self._meta_cache
        raw = self.payload(
            KIND_QQ_ACCOUNT_META,
            f"qq:{self.subject}",
            QQ_ACCOUNT_META_ACTION,
            user_id=int(self.subject) if self.subject.isdigit() else self.subject,
        )
        meta, audit = read_qq_account_meta(self.read(), self.subject, probed=self.api_available)
        self._meta_cache = (meta, audit, raw)
        return self._meta_cache

    # -- 群域载荷 ------------------------------------------------------------
    def _gid(self) -> Any:
        return int(self.group_id) if self.group_id.isdigit() else self.group_id

    @staticmethod
    def _uid_of(value: str) -> Any:
        """号形参：纯数字（含前导负号）转 int，其余原样传（TG 的 chat.id 是负数）。"""
        digits = str(value or "").strip().lstrip("-")
        return int(value) if digits.isdigit() else value

    def group_info(self) -> tuple[bool, Any]:
        return self.payload(KIND_PROFILE, self.group_id, "get_group_info", group_id=self._gid())

    def members(self) -> tuple[bool, Any]:
        return self.payload(KIND_MEMBERS, self.group_id, "get_group_member_list", group_id=self._gid())

    def member_row(self) -> dict[str, Any]:
        """主体在本群的那**一行**（成员表投影，绝不整列名单）。"""
        ok, payload = self.members()
        if not ok or not isinstance(payload, list):
            return {}
        for item in payload:
            body = as_mapping(item)
            if str(body.get("user_id") or "").strip() == self.subject:
                return body
        return {}


# ---------------------------------------------------------------------------
# 格子的构造口（非 ok 态强制清值——结构性防泄露，不靠调用方记得）
# ---------------------------------------------------------------------------


def _field(
    ctx: _Ctx,
    key: str,
    label: str,
    *,
    state: str,
    source: str,
    visibility: str,
    value: str = "",
    reason: str = "",
) -> ProfileField:
    return ProfileField(
        key=key,
        label=label,
        state=state,
        source=source,
        visibility=visibility,
        value=value if state == FIELD_OK else "",
        reason=reason if state != FIELD_OK else "",
        fetched_at=ctx.now,
    )


def _forbidden(ctx: _Ctx, key: str, label: str, reason: str = "") -> ProfileField:
    """拒绝格的可见级刻意是 ``VIS_SESSION``：值已被清空，没什么可泄。

    留格而不删格是为了让 bot 能说「这几格我不给」——静默消失会被读成「这个平台没有这一格」，
    那是另一种失实。
    """
    return _field(
        ctx, key, label, state=FIELD_FORBIDDEN, source=SOURCE_EVENT, visibility=VIS_SESSION,
        reason=reason or NOTE_FORBIDDEN_LINE,
    )


def _absent(ctx: _Ctx, key: str, label: str, reason: str) -> ProfileField:
    return _field(ctx, key, label, state=FIELD_ABSENT, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, reason=reason)


def _from_event(
    ctx: _Ctx, key: str, label: str, attr: str, *, visibility: str = VIS_SESSION
) -> ProfileField:
    value, present = ctx.event(attr)
    if not present:
        return _field(
            ctx, key, label, state=FIELD_MISSING, source=SOURCE_EVENT, visibility=visibility,
            reason="事件没带这一格（没回不等于没有，不替你下结论）。",
        )
    if not value:
        return _field(
            ctx, key, label, state=FIELD_EMPTY, source=SOURCE_EVENT, visibility=visibility,
            reason="这一格这会儿是空的。",
        )
    return _field(ctx, key, label, state=FIELD_OK, source=SOURCE_EVENT, visibility=visibility, value=value)


def _from_payload(
    ctx: _Ctx,
    key: str,
    label: str,
    *,
    kind: str,
    action: str,
    field_name: str,
    visibility: str,
    group_scope: bool = False,
    params: Mapping[str, Any] | None = None,
    render: Callable[[Any], str] | None = None,
) -> ProfileField:
    """协议读数格：门 → 未探测 → 失败 → 缺席 → 空 → 成功，六态逐条分开走。"""
    if group_scope and ctx.group_refused:
        return _forbidden(ctx, key, label, "跨会话拒绝：问的不是本事件所在的群。")
    if not ctx.allowed(visibility):
        return _forbidden(ctx, key, label)
    if not ctx.api_available:
        return _field(
            ctx, key, label, state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=visibility,
            reason=NOTE_UNPROBED_LINE,
        )
    call_params = dict(params or {}) or {"group_id": ctx._gid()}
    ok, payload = ctx.payload(kind, ctx.group_id, action, **call_params)
    if not ok:
        return _field(
            ctx, key, label, state=FIELD_FAILED, source=SOURCE_PROTOCOL, visibility=visibility,
            reason="协议端这次没答上，拿不到（不等于没有）。",
        )
    data = as_mapping(payload)
    if field_name not in data:
        return _field(
            ctx, key, label, state=FIELD_MISSING, source=SOURCE_PROTOCOL, visibility=visibility,
            reason=f"接口回了载荷但没带 {field_name} 这一格，读不出，不写「没有」。",
        )
    value = render(data.get(field_name)) if render else meta_scalar(data.get(field_name))
    if not value:
        return _field(
            ctx, key, label, state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=visibility,
            reason="接口回了空值（不替你断言原因）。",
        )
    return _field(ctx, key, label, state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=visibility, value=value)


def _qq_account_cells(ctx: _Ctx) -> list[ProfileField]:
    """账号面（签名 / 在线状态 / 电量，昵称顺带）：一期读件的**同一份实现**。"""
    cells = (("signature", "个性签名"), ("online_status", "在线状态"), ("battery", "电量"))
    if not ctx.allowed(VIS_SELF):
        return [_forbidden(ctx, key, label) for key, label in cells] + [
            _forbidden(ctx, "account_id", "账号")
        ]
    if not ctx.subject:
        return [
            _field(
                ctx, key, label, state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_SELF,
                reason="没有可问的对象号，这一轮是没去探测。",
            )
            for key, label in cells
        ]
    if not ctx.api_available:
        return [
            _field(
                ctx, key, label, state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_SELF,
                reason=NOTE_UNPROBED_LINE,
            )
            for key, label in cells
        ]
    meta, audit, (_ok, payload) = ctx.qq_meta()
    state = qq_meta_probe_state(audit)
    if state != FIELD_OK:
        reason = (
            NOTE_UNPROBED_LINE
            if state == FIELD_UNPROBED
            else "接口这次没答上，拿不到（不等于对方没设置）。"
        )
        return [
            _field(
                ctx, key, label, state=state, source=SOURCE_PROTOCOL, visibility=VIS_SELF, reason=reason
            )
            for key, label in cells
        ]
    data = as_mapping(payload)
    out: list[ProfileField] = []
    for key, label, field_name in (
        ("signature", "个性签名", "long_nick"),
        ("online_status", "在线状态", "status"),
        ("battery", "电量", "batteryStatus"),
    ):
        if field_name not in data:
            out.append(
                _field(
                    ctx, key, label, state=FIELD_MISSING, source=SOURCE_PROTOCOL, visibility=VIS_SELF,
                    reason=f"接口回了载荷但没带 {field_name} 这一格，读不出，不写「没有」。",
                )
            )
            continue
        value = meta.get(label, "")
        if value:
            out.append(
                _field(ctx, key, label, state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SELF, value=value)
            )
        elif key == "battery":
            out.append(
                _field(
                    ctx, key, label, state=FIELD_MISSING, source=SOURCE_PROTOCOL, visibility=VIS_SELF,
                    reason="动作册有 batteryStatus 这个字段，这次没回出有效值——不写成 0%。",
                )
            )
        else:
            out.append(
                _field(
                    ctx, key, label, state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SELF,
                    reason="接口回了空值——多半是没设置，也可能没回全，不替你断言。",
                )
            )
    if "nickname" in data and meta.get("昵称"):
        out.insert(
            0,
            _field(
                ctx, "nickname", "昵称", state=FIELD_OK, source=SOURCE_PROTOCOL,
                visibility=VIS_SESSION, value=meta["昵称"],
            ),
        )
    return out


# ---------------------------------------------------------------------------
# 平台 × 作用域 的格子计划
# ---------------------------------------------------------------------------

_ROLE_LABELS = {"owner": "群主", "admin": "管理员", "member": "群成员"}
_TG_STATUS_LABELS = {
    "creator": "群主",
    "administrator": "管理员",
    "member": "成员",
    "restricted": "受限成员",
    "left": "已离开",
    "kicked": "已被移出",
}

#: 缺席理由（一期的散文结论升成结构化事实；措辞里的核证线索被锁检查）。
_LUCKY_REASON = (
    "动作册结构性没有：全册 ``lucky``/「幸运」零命中（2026-09-29 现算），"
    "最接近的 ``get_group_signed_list`` 是「今日打卡」，不是幸运符号。"
)
_NETWORK_REASON = "动作册无网络制式字段（WiFi/5G 一类没有对应条目），拿不到就不编。"
_TG_NO_PRESENCE_REASON = (
    "Telegram 的 Bot API 不向机器人开放在线/最近活跃——接口层面就没有这个数，"
    "答不了，不是我没去查。"
)
_MAIL_NO_GROUP_REASON = (
    "邮件没有「群」这种对象：群名、群号、公告、精华、群主、成员名单这些格子在这里是空的——"
    "SMTP/IMAP 是消息投递协议，不经营群务，我不拿别的字段硬凑。"
)
_QQ_NO_GROUP_REASON = "私聊没有「群」这种对象，这几格在这里是空的——我不拿别的字段硬凑。"


def _participants_field(ctx: _Ctx) -> ProfileField:
    """参与者腿：只吃调用方传进来的记忆读数，本层不开库、不写盘。"""
    memory = ctx.participant_memory
    label, visibility = "参与者（按记忆算）", VIS_SESSION
    if memory is None:
        return _field(
            ctx, "participants", label, state=FIELD_FAILED, source=SOURCE_MEMORY, visibility=visibility,
            reason="这会儿没拿到记忆读数（没开或一时打不开）——读不出不等于没人说话，我不拿它当「没有」。",
        )
    state = str(getattr(memory, "state", "") or "")
    if state == STATE_OK:
        records = list(getattr(memory, "records", ()) or ())
        total = int(getattr(memory, "total_speakers", len(records)) or 0)
        shown = [
            str(getattr(item, "display_name", "") or "").strip()
            for item in records[:SECTION_LINE_LIMIT]
        ]
        shown = [n for n in shown if n]
        value = f"记到说过话的 {total} 位"
        if shown:
            value += "：" + "、".join(shown)
        omitted = max(0, total - len(shown))
        if omitted:
            value += f"（另有 {omitted} 位未列出）"
        if bool(getattr(memory, "window_exhausted", False)):
            value += f"（只翻了最近 {getattr(memory, 'row_window', 0)} 条记录）"
        return _field(ctx, "participants", label, state=FIELD_OK, source=SOURCE_MEMORY, visibility=visibility, value=value)
    if state == STATE_EMPTY:
        return _field(
            ctx, "participants", label, state=FIELD_EMPTY, source=SOURCE_MEMORY, visibility=visibility,
            reason="我这儿还没有人说过话的记录——这不等于这屋里没人说过话，只是我这边没记下。",
        )
    return _field(
        ctx, "participants", label, state=FIELD_FAILED, source=SOURCE_MEMORY, visibility=visibility,
        reason="这份记录这会儿读不出来（"
        + str(getattr(memory, "reason", "") or "未知")
        + "）——读不出不等于没人说话，我不拿它当「没有」。",
    )


def _files_field(ctx: _Ctx, *, reason_no_group: str = "") -> ProfileField:
    if ctx.group_refused:
        return _forbidden(ctx, "files", "群文件", "跨会话拒绝：问的不是本事件所在的群。")
    if reason_no_group:
        return _absent(ctx, "files", "群文件", reason_no_group)
    summary = str(ctx.group_file_summary or "").strip()
    if not summary:
        return _field(
            ctx, "files", "群文件", state=FIELD_MISSING, source=SOURCE_LEDGER, visibility=VIS_SESSION,
            reason=(
                "本地账本这一程没给概览（缺数＝缺行）；协议端的 ``get_group_root_files`` 全量口"
                "在册但未接，我不拿未核过的动作名谎报「接口没回应」。"
            ),
        )
    return _field(ctx, "files", "群文件", state=FIELD_OK, source=SOURCE_LEDGER, visibility=VIS_SESSION, value=summary)


def _common_absent_cells(ctx: _Ctx) -> list[ProfileField]:
    """结构性缺席格：以 ``absent`` **出现在画像里**并带核证理由（缺席是被看着的状态）。"""
    roster_reason = (
        "成员全量名单按用户裁定不接（参与者改按记忆算）；协议层 ``get_group_member_list`` "
        "虽能整份拿到，但那是隐私与刷屏红线，不是待办优化。"
    )
    if ctx.platform == "telegram":
        roster_reason = (
            "Telegram 的 Bot API 没有列出全部群成员的动作（群主与管理员另有口），"
            "这份名单给不了，也不猜。"
        )
    elif ctx.platform in {"email", "mail"}:
        roster_reason = _MAIL_NO_GROUP_REASON
    return [
        _absent(ctx, "member_roster", "成员全量名单", roster_reason),
        _absent(ctx, "lucky_symbol", "幸运符号", _LUCKY_REASON),
        _absent(ctx, "group_lucky_symbol", "群幸运符号", _LUCKY_REASON + "（群侧亦无对应动作，同上）"),
        _absent(ctx, "network_type", "网络制式", _NETWORK_REASON),
    ]


def _qq_notice(ctx: _Ctx) -> ProfileField:
    """公告首段：SnowLuma 真名 ``_get_group_notice`` 优先，失败退 V11 常见名（一期先例）。"""
    if ctx.group_refused:
        return _forbidden(ctx, "group_notice", "公告", "跨会话拒绝：问的不是本事件所在的群。")
    if not ctx.allowed(VIS_ADMINS):
        return _forbidden(ctx, "group_notice", "公告")
    if not ctx.api_available:
        return _field(ctx, "group_notice", "公告", state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS, reason=NOTE_UNPROBED_LINE)
    ok, payload = ctx.payload(KIND_NOTICE, ctx.group_id, "_get_group_notice", group_id=ctx._gid())
    if not ok:
        ok, payload = ctx.payload(KIND_NOTICE, ctx.group_id, "get_group_notice", group_id=ctx._gid())
    if not ok:
        return _field(
            ctx, "group_notice", "公告", state=FIELD_FAILED, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS,
            reason="公告接口这会儿没回应，拿不到（可能需要我有管理员身份）。",
        )
    rows = payload if isinstance(payload, list) else []
    snippet = first_paragraph(segment_text(rows[0])) if rows else ""
    if not snippet:
        return _field(
            ctx, "group_notice", "公告", state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS,
            reason="接口回了空列表——群里现在没有公告。",
        )
    return _field(ctx, "group_notice", "公告", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS, value=snippet)


def _essence_field(ctx: _Ctx) -> ProfileField:
    if ctx.group_refused:
        return _forbidden(ctx, "essence_count", "精华条数", "跨会话拒绝：问的不是本事件所在的群。")
    if not ctx.allowed(VIS_ADMINS):
        return _forbidden(ctx, "essence_count", "精华条数")
    if not ctx.api_available:
        return _field(ctx, "essence_count", "精华条数", state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS, reason=NOTE_UNPROBED_LINE)
    ok, payload = ctx.payload(KIND_ESSENCE, ctx.group_id, "get_essence_msg_list", group_id=ctx._gid())
    if not ok:
        return _field(
            ctx, "essence_count", "精华条数", state=FIELD_FAILED, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS,
            reason="精华接口这会儿没回应，拿不到（可能需要我有管理员身份）。",
        )
    rows = payload if isinstance(payload, list) else []
    return _field(ctx, "essence_count", "精华条数", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_ADMINS, value=f"一共收了 {len(rows)} 条")


def _album_field(ctx: _Ctx) -> ProfileField:
    if ctx.group_refused:
        return _forbidden(ctx, "album", "群相册", "跨会话拒绝：问的不是本事件所在的群。")
    if not ctx.api_available:
        return _field(ctx, "album", "群相册", state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, reason=NOTE_UNPROBED_LINE)
    ok, payload = ctx.payload(KIND_ALBUM, ctx.group_id, "get_group_album_list", group_id=ctx._gid())
    if not ok:
        ok, payload = ctx.payload(KIND_ALBUM, ctx.group_id, "_get_group_album_list", group_id=ctx._gid())
    if not ok:
        return _field(
            ctx, "album", "群相册", state=FIELD_FAILED, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            reason="协议端这次没答上，拿不到（不是本群没有相册，是我没读到）。",
        )
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return _field(
            ctx, "album", "群相册", state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            reason="接口回了空列表——这个群目前没有相册。",
        )
    parts: list[str] = [f"{len(rows)} 个相册"]
    for album in rows[:SECTION_LINE_LIMIT]:
        name = first_str(album, ALBUM_NAME_KEYS) or "（这个相册名字段读不出）"
        pics = first_int(album, ALBUM_PIC_COUNT_KEYS)
        parts.append(f"{name}（{pics} 张）" if pics is not None else f"{name}（照片数这次没回）")
    if len(rows) > SECTION_LINE_LIMIT:
        parts.append(f"另有 {len(rows) - SECTION_LINE_LIMIT} 个未列出")
    return _field(ctx, "album", "群相册", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value="；".join(parts))


def _todo_field(ctx: _Ctx) -> ProfileField:
    if ctx.group_refused:
        return _forbidden(ctx, "todo", "群待办", "跨会话拒绝：问的不是本事件所在的群。")
    if not ctx.api_available:
        return _field(ctx, "todo", "群待办", state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, reason=NOTE_UNPROBED_LINE)
    ok, payload = ctx.payload(KIND_TODO, ctx.group_id, "get_group_todo_list", group_id=ctx._gid())
    if not ok:
        ok, payload = ctx.payload(KIND_TODO, ctx.group_id, "_get_group_todo_list", group_id=ctx._gid())
    if not ok:
        return _field(
            ctx, "todo", "群待办", state=FIELD_FAILED, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            reason="协议端这次没答上，拿不到（不等于没人设过待办）。",
        )
    rows = payload if isinstance(payload, list) else []
    if not rows:
        return _field(
            ctx, "todo", "群待办", state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            reason="接口回了空列表——现在没有挂着的待办。",
        )
    titles = [
        first_str(item, TODO_TITLE_KEYS) or "（这条待办的标题字段读不出，只能报它还在）"
        for item in rows[:SECTION_LINE_LIMIT]
    ]
    value = f"{len(rows)} 条：" + "；".join(clip(t, 60) for t in titles)
    if len(rows) > SECTION_LINE_LIMIT:
        value += f"（另有 {len(rows) - SECTION_LINE_LIMIT} 条未列出）"
    return _field(ctx, "todo", "群待办", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=value)


def _member_roster_stats(ctx: _Ctx) -> tuple[ProfileField, ProfileField]:
    """群主与管理员：只从成员表投影出「那几行」，名单绝不整列（在册隐私红线）。"""
    if ctx.group_refused:
        return (
            _forbidden(ctx, "owner", "群主", "跨会话拒绝：问的不是本事件所在的群。"),
            _forbidden(ctx, "admins_count", "管理员数", "跨会话拒绝：问的不是本事件所在的群。"),
        )
    ok, rows = ctx.members()
    if not ok:
        state = FIELD_UNPROBED if not ctx.api_available else FIELD_FAILED
        reason = (
            NOTE_UNPROBED_LINE
            if state == FIELD_UNPROBED
            else "成员表这次没答上，拿不到（不等于本群没有群主）。"
        )
        return (
            _field(ctx, "owner", "群主", state=state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, reason=reason),
            _field(ctx, "admins_count", "管理员数", state=state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, reason=reason),
        )
    rows = rows if isinstance(rows, list) else []
    owners = [as_mapping(r) for r in rows if str(as_mapping(r).get("role") or "") == "owner"]
    admins = [as_mapping(r) for r in rows if str(as_mapping(r).get("role") or "") == "admin"]
    if owners:
        body = owners[0]
        display = meta_scalar(body.get("card")) or meta_scalar(body.get("nickname"))
        uid = meta_scalar(body.get("user_id"))
        owner = _field(
            ctx, "owner", "群主", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            value=(display or "群主") + (f"（{uid}）" if uid else ""),
        )
    else:
        owner = _field(
            ctx, "owner", "群主", state=FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
            reason="成员表里没有 role=owner 的一条，先不硬指认啦。",
        )
    count = _field(
        ctx, "admins_count", "管理员数", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
        value=str(len(admins)),
    )
    return owner, count


def _qq_group_cells(ctx: _Ctx) -> list[ProfileField]:
    out: list[ProfileField] = []
    if ctx.is_self:
        out.append(_from_event(ctx, "account_id", "账号（QQ 号）", "sender_id", visibility=VIS_SELF))
        out.append(_from_event(ctx, "nickname", "昵称（事件自带）", "sender_nickname"))
        # 群内名片/头衔/身份/等级：事件自带就是当场事实，不必打接口。
        out.append(_from_event(ctx, "group_card", "群名片", "sender_card"))
        out.append(_from_event(ctx, "group_title", "群头衔", "sender_title"))
        role_value, role_present = ctx.event("sender_platform_role")
        if role_present and role_value:
            out.append(
                _field(
                    ctx, "group_role", "群内身份", state=FIELD_OK, source=SOURCE_EVENT, visibility=VIS_SESSION,
                    value=_ROLE_LABELS.get(role_value.lower(), f"{role_value}（身份码没认出来）"),
                )
            )
        else:
            out.append(_from_event(ctx, "group_role", "群内身份", "sender_platform_role"))
        out.append(_from_event(ctx, "level", "等级", "sender_level", visibility=VIS_SELF))
    else:
        # 问的是别人：名片/头衔仍是群内公开面（成员表里那**一行**）；账号面另走门。
        row = ctx.member_row()
        card = meta_scalar(row.get("card")) or meta_scalar(row.get("nickname"))
        title = meta_scalar(row.get("title"))
        out.append(
            _field(
                ctx, "group_card", "群名片",
                state=FIELD_OK if card else FIELD_MISSING, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                value=card, reason="" if card else "成员表里没找到这一位的那一行，读不出，不写「没有」。",
            )
        )
        out.append(
            _field(
                ctx, "group_title", "群头衔",
                state=FIELD_OK if title else FIELD_MISSING, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                value=title, reason="" if title else "成员表没回 title 这一格（没回≠没有头衔）。",
            )
        )
    out.extend(_qq_account_cells(ctx))
    if ctx.group_refused:
        out.append(_forbidden(ctx, "group_id", "群号", "跨会话拒绝：我只报当前所在群的号。"))
    else:
        out.append(_from_event(ctx, "group_id", "群号", "group_id"))
    out.append(
        _from_payload(ctx, "group_name", "群名", kind=KIND_PROFILE, action="get_group_info", field_name="group_name", visibility=VIS_SESSION, group_scope=True)
    )
    out.append(
        _from_payload(ctx, "group_memo", "群介绍", kind=KIND_PROFILE, action="get_group_info", field_name="group_memo", visibility=VIS_SESSION, group_scope=True)
    )
    out.extend(_qq_group_stats(ctx))
    owner, admins = _member_roster_stats(ctx)
    out.extend([owner, admins])
    out.append(_qq_notice(ctx))
    out.append(_essence_field(ctx))
    out.append(_album_field(ctx))
    out.append(_todo_field(ctx))
    out.append(_files_field(ctx))
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


def _qq_group_stats(ctx: _Ctx) -> list[ProfileField]:
    if ctx.group_refused:
        return [
            _forbidden(ctx, "member_count", "人数", "跨会话拒绝：问的不是本事件所在的群。"),
            _forbidden(ctx, "group_age", "建群时长", "跨会话拒绝：问的不是本事件所在的群。"),
        ]
    ok, payload = ctx.group_info()
    data = as_mapping(payload) if ok else {}
    count = data.get("member_count")
    cap = data.get("max_member_count")
    if not ctx.api_available:
        state, value, reason = FIELD_UNPROBED, "", NOTE_UNPROBED_LINE
    elif not ok:
        state, value, reason = FIELD_FAILED, "", "协议端这次没答上，拿不到（不等于没有）。"
    elif isinstance(count, int):
        state, value, reason = FIELD_OK, (f"{count}/{cap}" if isinstance(cap, int) else str(count)), ""
    else:
        state, value, reason = FIELD_MISSING, "", "接口回了载荷但没带 member_count 这一格。"
    out = [_field(ctx, "member_count", "人数", state=state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=value, reason=reason)]
    created = data.get("group_create_time")
    if ctx.api_available and ok and isinstance(created, (int, float)) and created > 0:
        getter = getattr(ctx.message.timestamp, "timestamp", None)
        now_ts = float(getter()) if callable(getter) else ctx.now
        days = max(0, int((now_ts - float(created)) // 86400))
        out.append(
            _field(ctx, "group_age", "建群时长", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=f"约 {days} 天")
        )
    else:
        age_state = FIELD_UNPROBED if not ctx.api_available else (FIELD_MISSING if ok else FIELD_FAILED)
        out.append(
            _field(
                ctx, "group_age", "建群时长", state=age_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                reason=(
                    NOTE_UNPROBED_LINE
                    if age_state == FIELD_UNPROBED
                    else "``group_create_time`` 是现役协议端登记在 ``get_group_info`` 里的扩展字段"
                    "（不在 V11 规范文本内），没回就说拿不到，不折算。"
                ),
            )
        )
    return out


def _qq_private_cells(ctx: _Ctx) -> list[ProfileField]:
    out = [_from_event(ctx, "account_id", "对方账号（QQ 号）", "sender_id", visibility=VIS_SELF)]
    out.extend(_qq_account_cells(ctx))
    for key, label in (
        ("group_id", "群号"),
        ("group_name", "群名"),
        ("group_memo", "群介绍"),
        ("member_count", "人数"),
        ("group_notice", "公告"),
        ("essence_count", "精华条数"),
        ("album", "群相册"),
        ("todo", "群待办"),
    ):
        out.append(_absent(ctx, key, label, _QQ_NO_GROUP_REASON))
    out.append(_files_field(ctx, reason_no_group="私聊没有群盘；本地账本只记群上传，这一程没有对得上的格。"))
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


def _tg_person_label(entry: Any) -> str:
    body = as_mapping(entry)
    user = as_mapping(body.get("user"))
    name = " ".join(
        p for p in (meta_scalar(user.get("first_name")), meta_scalar(user.get("last_name"))) if p
    )
    username = meta_scalar(user.get("username")).lstrip("@")
    bot_mark = "（机器人）" if user.get("is_bot") is True else ""
    if name and username:
        return f"{name}（@{username}）{bot_mark}"
    if name or username:
        return (name or f"@{username}") + bot_mark
    uid = meta_scalar(user.get("id"))
    return f"（昵称字段没回，账号 {uid}）" if uid else "（这条记录的昵称与账号都没回）"


def _telegram_group_cells(ctx: _Ctx) -> list[ProfileField]:
    out = [
        _from_event(ctx, "account_id", "账号（TG user id）", "sender_id", visibility=VIS_SELF),
        _from_event(ctx, "nickname", "昵称（事件自带）", "sender_display_name"),
    ]
    if ctx.group_refused:
        for key, label in (
            ("group_id", "会话号（chat id）"),
            ("group_name", "群名"),
            ("group_memo", "群介绍"),
            ("group_notice", "置顶（本群公告位）"),
            ("member_count", "人数"),
            ("group_role", "身份（Bot API 口径）"),
            ("group_title", "群头衔"),
            ("owner", "群主"),
            ("admins_count", "管理员数"),
        ):
            out.append(_forbidden(ctx, key, label, "跨会话拒绝：问的不是本事件所在的会话。"))
    else:
        out.append(_from_event(ctx, "group_id", "会话号（chat id）", "group_id"))
        ok_chat, raw_chat = ctx.payload(KIND_PROFILE, ctx.group_id, "get_chat", chat_id=ctx._gid())
        chat = as_mapping(raw_chat)
        for key, label, field_name in (("group_name", "群名", "title"), ("group_memo", "群介绍", "description")):
            if not ctx.api_available:
                state, value, reason = FIELD_UNPROBED, "", NOTE_UNPROBED_LINE
            elif not ok_chat:
                state, value, reason = FIELD_FAILED, "", "Telegram 接口这次没答上，拿不到（不等于本群没有）。"
            elif field_name not in chat:
                state, value, reason = FIELD_MISSING, "", f"get_chat 回了但没带 {field_name} 这一格。"
            else:
                value = meta_scalar(chat.get(field_name))
                state = FIELD_OK if value else FIELD_EMPTY
                reason = "" if value else "接口回了空值（不替你断言原因）。"
            out.append(
                _field(ctx, key, label, state=state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=value, reason=reason)
            )
        if not ctx.api_available:
            pinned_state, pinned_value, pinned_reason = FIELD_UNPROBED, "", NOTE_UNPROBED_LINE
        elif not ok_chat:
            pinned_state, pinned_value, pinned_reason = FIELD_FAILED, "", "Telegram 接口这次没答上，拿不到。"
        elif "pinned_message" not in chat:
            pinned_state, pinned_value, pinned_reason = FIELD_MISSING, "", "get_chat 没带 pinned_message 这一格。"
        else:
            pinned_value = first_paragraph(meta_scalar(as_mapping(chat.get("pinned_message")).get("text")))
            pinned_state = FIELD_OK if pinned_value else FIELD_EMPTY
            pinned_reason = "" if pinned_value else "这个群现在没有置顶消息。"
        out.append(
            _field(ctx, "group_notice", "置顶（本群公告位）", state=pinned_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=pinned_value, reason=pinned_reason)
        )
        ok_count, raw_count = ctx.payload(KIND_MEMBER_COUNT, ctx.group_id, "get_chat_member_count", chat_id=ctx._gid())
        count = raw_count.get("result") if isinstance(raw_count, dict) else raw_count
        if not ctx.api_available:
            count_state, count_value, count_reason = FIELD_UNPROBED, "", NOTE_UNPROBED_LINE
        elif isinstance(count, int):
            count_state, count_value, count_reason = FIELD_OK, str(count), ""
        elif ok_count:
            count_state, count_value, count_reason = FIELD_MISSING, "", "人数这一格没回出整数，不硬报。"
        else:
            count_state, count_value, count_reason = FIELD_FAILED, "", "人数接口这次没答上，拿不到。"
        out.append(
            _field(ctx, "member_count", "人数", state=count_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=count_value, reason=count_reason)
        )
        ok_me, raw_me = ctx.payload(
            KIND_SELF_MEMBER, ctx.group_id, "get_chat_member", chat_id=ctx._gid(), user_id=ctx._uid_of(ctx.subject)
        )
        me = as_mapping(raw_me)
        if ok_me and me:
            label = _TG_STATUS_LABELS.get(str(me.get("status") or "").strip().lower(), "成员")
            out.append(
                _field(ctx, "group_role", "身份（Bot API 口径）", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=label)
            )
            custom = meta_scalar(me.get("custom_title"))
            out.append(
                _field(
                    ctx, "group_title", "群头衔",
                    state=FIELD_OK if custom else FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                    value=custom, reason="" if custom else "custom_title 回了空——没设过或没回全，不替你断言。",
                )
            )
        else:
            me_state = FIELD_UNPROBED if not ctx.api_available else FIELD_FAILED
            out.append(
                _field(
                    ctx, "group_role", "身份（Bot API 口径）", state=me_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                    reason=NOTE_UNPROBED_LINE if me_state == FIELD_UNPROBED else "get_chat_member 这次没答上。",
                )
            )
            out.append(
                _field(
                    ctx, "group_title", "群头衔", state=me_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                    reason=NOTE_UNPROBED_LINE if me_state == FIELD_UNPROBED else "这一格跟着 get_chat_member 一起没答上（缺席≠没有头衔）。",
                )
            )
        ok_adm, raw_adm = ctx.payload(KIND_ADMINS, ctx.group_id, "get_chat_administrators", chat_id=ctx._gid())
        rows = raw_adm if ok_adm and isinstance(raw_adm, list) else []
        owners = [as_mapping(r) for r in rows if str(as_mapping(r).get("status") or "").strip().lower() == "creator"]
        staff = [as_mapping(r) for r in rows if str(as_mapping(r).get("status") or "").strip().lower() == "administrator"]
        if ok_adm:
            out.append(
                _field(
                    ctx, "owner", "群主",
                    state=FIELD_OK if owners else FIELD_EMPTY, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                    value=_tg_person_label(owners[0]) if owners else "",
                    reason="" if owners else "这回列表里没有 creator 身份的一条，先不硬指认啦。",
                )
            )
            out.append(
                _field(ctx, "admins_count", "管理员数", state=FIELD_OK, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=str(len(staff)))
            )
        else:
            adm_state = FIELD_UNPROBED if not ctx.api_available else FIELD_FAILED
            for key, label in (("owner", "群主"), ("admins_count", "管理员数")):
                out.append(
                    _field(
                        ctx, key, label, state=adm_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION,
                        reason=NOTE_UNPROBED_LINE if adm_state == FIELD_UNPROBED else "Telegram 接口这次没答上，拿不到（不等于本群没有群主）。",
                    )
                )
    out.append(_absent(ctx, "signature", "个性签名", "Bot API 的 ``bio`` 只在私聊 ``getChat`` 回，群内取不到这一格。"))
    out.append(_absent(ctx, "online_status", "在线状态", _TG_NO_PRESENCE_REASON))
    for key, label in (
        ("essence_count", "精华条数"),
        ("album", "群相册"),
        ("todo", "群待办"),
    ):
        out.append(_absent(ctx, key, label, f"Telegram 的 Bot API 没有 {label} 的对应接口，答不了（不是我没去查）。"))
    out.append(_files_field(ctx, reason_no_group="Telegram 的 Bot API 没有群文件接口；本仓的群文件账本只收 QQ 群上传。"))
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


def _telegram_private_cells(ctx: _Ctx) -> list[ProfileField]:
    chat_id = parse_session_key(ctx.message.session_id).user_id.strip()
    out = [
        _from_event(ctx, "account_id", "账号（TG user id）", "sender_id", visibility=VIS_SELF),
        _field(
            ctx, "session_id", "会话号（chat id）",
            state=FIELD_OK if chat_id.isdigit() else FIELD_MISSING, source=SOURCE_EVENT, visibility=VIS_SESSION,
            value=chat_id, reason="" if chat_id.isdigit() else "会话键里解析不出 chat id，不猜。",
        ),
    ]
    # 私聊对端昵称与签名共用一次 ``get_chat``（ChatFullInfo：bio 只在私聊回）。
    if not chat_id.isdigit():
        peer_state, peer_reason = FIELD_UNPROBED, "没有会话号就没法查，这一轮是没去探测，不是查不到。"
        peer: dict[str, Any] = {}
    elif not ctx.api_available:
        peer_state, peer_reason = FIELD_UNPROBED, NOTE_UNPROBED_LINE
        peer = {}
    else:
        ok, raw_peer = ctx.payload(KIND_PEER_PROFILE, chat_id, "get_chat", chat_id=int(chat_id))
        peer = as_mapping(raw_peer)
        if not ok:
            peer_state, peer_reason = FIELD_FAILED, "Telegram 接口这次没答上，拿不到（不等于对方没设置）。"
        elif not peer:
            peer_state, peer_reason = FIELD_FAILED, "接口回的形状读不出，先不硬解。"
        else:
            peer_state, peer_reason = FIELD_OK, ""
    name = " ".join(
        p for p in (meta_scalar(peer.get("first_name")), meta_scalar(peer.get("last_name"))) if p
    )
    username = meta_scalar(peer.get("username")).lstrip("@")
    shown = f"{name}（@{username}）" if name and username else (name or (f"@{username}" if username else ""))
    if peer_state != FIELD_OK:
        nick_state, nick_value, nick_reason = peer_state, "", peer_reason
    elif shown:
        nick_state, nick_value, nick_reason = FIELD_OK, shown, ""
    else:
        nick_state, nick_value, nick_reason = FIELD_EMPTY, "", "接口回的名字字段是空的，不替你填。"
    out.append(
        _field(ctx, "nickname", "昵称", state=nick_state, source=SOURCE_PROTOCOL, visibility=VIS_SESSION, value=nick_value, reason=nick_reason)
    )
    if peer_state != FIELD_OK:
        sig_state, sig_value, sig_reason = peer_state, "", peer_reason
    elif "bio" not in peer:
        sig_state, sig_value, sig_reason = FIELD_MISSING, "", "get_chat 没带 bio 这一格，读不出，不写「没有」。"
    else:
        bio = clip(meta_scalar(peer.get("bio")))
        sig_state, sig_value = (FIELD_OK, bio) if bio else (FIELD_EMPTY, "")
        sig_reason = "" if bio else "接口回了空——多半是没设置，也可能没回，不替你断言。"
    out.append(
        _field(ctx, "signature", "个性签名", state=sig_state, source=SOURCE_PROTOCOL, visibility=VIS_SELF, value=sig_value, reason=sig_reason)
    )
    out.append(_absent(ctx, "online_status", "在线状态", _TG_NO_PRESENCE_REASON))
    no_group = "Telegram 私聊没有「群」这种对象，这几格在这里是空的——我不拿别的字段硬凑。"
    for key, label in (("group_id", "群号"), ("group_name", "群名"), ("group_memo", "群介绍")):
        out.append(_absent(ctx, key, label, no_group))
    out.append(_files_field(ctx, reason_no_group="Telegram 私聊没有群盘，Bot API 也没有群文件接口。"))
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


def _mail_cells(ctx: _Ctx) -> list[ProfileField]:
    out = [
        _from_event(ctx, "account_id", "发件人地址", "sender_id", visibility=VIS_SELF),
        _from_event(ctx, "mailbox", "收信账户", "bot_id"),
        _from_event(ctx, "display_name", "发件人昵称（From 显示名）", "sender_display_name"),
        _field(
            ctx, "mail_subject", "邮件主题", state=FIELD_MISSING, source=SOURCE_EVENT, visibility=VIS_SESSION,
            reason="主题在适配器解得出，但契约位今天没带进会话记录——属摄取未接，不猜一个。",
        ),
        _field(
            ctx, "mail_recipients", "收件人（To/Cc）", state=FIELD_MISSING, source=SOURCE_EVENT, visibility=VIS_SESSION,
            reason=(
                "适配器逐封解出 recipients_to/recipients_cc，是这条链还没接到会话记录里"
                "（票 T-META-INGEST-1）——今天答不全是我没接上，不是邮件协议没有。"
            ),
        ),
        _absent(ctx, "mail_bcc", "密送（Bcc）", "按投递语义，Bcc 名单在送出时被剥离，收信人这一侧的信里本来就没有它——这一格是真没有。"),
        _absent(ctx, "signature", "个性签名", "邮件模型没有签名概念这一格（适配器无对应字段），不拿正文硬凑。"),
        _absent(ctx, "online_status", "在线状态", "邮件没有投递语义之外的在线通道，这一格结构性不存在。"),
        _absent(ctx, "level", "等级", "邮件没有等级概念这一格。"),
    ]
    for key, label in (
        ("group_id", "群号"),
        ("group_name", "群名"),
        ("group_memo", "群介绍"),
        ("group_card", "群名片"),
        ("group_title", "群头衔"),
        ("member_count", "人数"),
        ("owner", "群主"),
        ("admins_count", "管理员数"),
        ("group_notice", "公告"),
        ("essence_count", "精华条数"),
        ("album", "群相册"),
        ("todo", "群待办"),
    ):
        out.append(_absent(ctx, key, label, _MAIL_NO_GROUP_REASON))
    out.append(_files_field(ctx, reason_no_group=_MAIL_NO_GROUP_REASON))
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


def _other_cells(ctx: _Ctx) -> list[ProfileField]:
    """未知通道（控制台等）：只说事件自带的那几枚，其余整体未探测——不猜动作名。"""
    out = [
        _from_event(ctx, "account_id", "账号", "sender_id", visibility=VIS_SELF),
        _from_event(ctx, "nickname", "昵称", "sender_display_name"),
        _field(ctx, "signature", "个性签名", state=FIELD_UNPROBED, source=SOURCE_PROTOCOL, visibility=VIS_SELF, reason="这条通道没有已登记的资料口，本层不去猜动作名。"),
        _absent(ctx, "group_name", "群名", "这条通道没有群对象的在册口，不硬凑。"),
    ]
    out.append(_participants_field(ctx))
    out.extend(_common_absent_cells(ctx))
    return out


_PLANS: dict[tuple[str, str], Callable[[_Ctx], list[ProfileField]]] = {
    ("qq", "group"): _qq_group_cells,
    ("qq", "private"): _qq_private_cells,
    ("onebot", "group"): _qq_group_cells,
    ("onebot", "private"): _qq_private_cells,
    ("telegram", "group"): _telegram_group_cells,
    ("telegram", "private"): _telegram_private_cells,
    ("email", "email"): _mail_cells,
    ("mail", "email"): _mail_cells,
}


def build_profile(
    message: IncomingMessage,
    fetch: Fetch,
    *,
    api_available: bool = True,
    clock: Callable[[], float] = time.time,
    subject_user_id: str = "",
    target_group_id: str = "",
    participant_memory: Any = None,
    group_file_summary: str = "",
) -> ConversationProfile:
    """平台 + 会话 + 主体 → 结构化画像（含状态、来源、时间戳、可信度、缺失原因）。

    ``fetch`` 是一期同签名的读口 ``(kind, key, action, **params) -> (ok, payload)``；
    ``api_available=False``＝桥未接线 ⇒ 协议格一律 ``unprobed`` 且**一次都不打**。
    ``subject_user_id`` 缺省＝问话人本人；给出别人的号 ⇒ ``VIS_SELF`` 格 ``forbidden``。
    ``target_group_id`` 给出且不是本事件所在群 ⇒ 群域整片 ``forbidden`` 且零调用。
    ``participant_memory`` / ``group_file_summary`` 由调用方取好再传（本层不开库、不写盘）。
    """
    ctx = _Ctx(
        message,
        fetch,
        api_available=api_available,
        clock=clock,
        subject_user_id=subject_user_id,
        target_group_id=target_group_id,
        participant_memory=participant_memory,
        group_file_summary=group_file_summary,
    )
    plan = _PLANS.get((ctx.platform, ctx.scope))
    if plan is None:
        if ctx.scope == "email":
            plan = _mail_cells
        elif ctx.platform == "telegram":
            plan = _telegram_group_cells if ctx.scope == "group" else _telegram_private_cells
        else:
            plan = _qq_group_cells if ctx.scope == "group" else _qq_private_cells
    return ConversationProfile(
        platform=ctx.platform,
        scope=ctx.scope,
        subject_user_id=ctx.subject,
        group_id=ctx.group_id,
        built_at=ctx.now,
        fields=tuple(plan(ctx)),
    )


# ---------------------------------------------------------------------------
# 两个投影面
# ---------------------------------------------------------------------------

_STATE_FALLBACK: dict[str, str] = {
    FIELD_FAILED: "接口没答上，拿不到（不等于没有）。",
    FIELD_MISSING: "这一格没回，读不出（不写「没有」）。",
    FIELD_EMPTY: "这会儿是空的。",
    FIELD_UNPROBED: NOTE_UNPROBED_LINE,
    FIELD_ABSENT: "这个平台不给这一格（接口层面就没有）。",
    FIELD_FORBIDDEN: NOTE_FORBIDDEN_LINE,
}


def answer_lines(
    profile: ConversationProfile,
    *,
    is_self: bool,
    privileged: bool,
    keys: Sequence[str] | None = None,
) -> list[str]:
    """命令侧回答：逐格分态说话，缺数各自带原因（守岸人口吻：不硬答、不拒人、不编）。"""
    wanted = set(keys) if keys else None
    lines: list[str] = []
    for item in profile.visible(is_self=is_self, privileged=privileged):
        if wanted is not None and item.key not in wanted:
            continue
        if item.ok:
            lines.append(f"{item.label}：{clip(item.value)}")
            continue
        lines.append(f"{item.label}：{item.reason or _STATE_FALLBACK.get(item.state, '这一格这会儿读不出。')}")
    return lines


def note_text(
    profile: ConversationProfile,
    *,
    is_self: bool = True,
    privileged: bool = False,
    exclude: Sequence[str] = (),
) -> str:
    """注入侧的每轮串：只收 ``NOTE_KEYS`` 白名单内、状态 ``ok``、且这一格可给的字段。

    形状对齐 ``chat.py`` 的 ``sender_profile_note``（``键=值；键=值``），空值一律丢弃——
    分区渲染的判据是 ``k=v`` 的 v 非空才留行，所以这里丢掉的格在模型眼里根本不存在。
    """
    skip = set(exclude)
    parts: list[str] = []
    for item in profile.visible(is_self=is_self, privileged=privileged):
        if item.key not in NOTE_KEYS or not item.ok or item.key in skip:
            continue
        parts.append(f"{item.label}={clip(item.value)}")
    return "；".join(parts)
