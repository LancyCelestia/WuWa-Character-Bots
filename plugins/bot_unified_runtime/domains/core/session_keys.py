"""会话键形态中央件（FIX5 收编，全仓唯一权威，2026-09-20 spec-audit）。

病根（台账 #33 群摘要读零行、#29 同类，第三次咬人）：会话键在**同一棵代码树里
有两种书写形态**，而判据各自只认一种——

- 生产摄取层的会话键 = NoneBot ``event.get_session_id()``（根 ``__init__.py:1288``
  → ``IncomingMessage.session_id``，pipeline 全程直传）。**OneBot V11 逐字实测**：
  群事件 ``f"group_{group_id}_{user_id}"``、私聊 ``str(user_id)``；Telegram 群
  ``group_{chat.id}_{from.id}``（含 thread 形 ``group_<cid>_thread<t>_<uid>``）、
  私聊 ``private_<chat.id>``、频道 ``channel_<chat.id>``。
- 冒号形 ``group:<gid>`` 只存在于**另一命名空间**（出站 ``SendRequest.session_id``）
  与合成/开发态消息（历史上的今天推送 ``__init__.py:1838``、``ops/smoke/*``）。

两处注释把冒号形写成「ingress 约定」（根 ``__init__.py:454``、
``content_route.py:169``），是这一族 bug 的**误导源**：拿它当真相写的判据
（旧 ``chat_reply/capabilities/memory.py``）落在真实群键上恒 False，静默零报错。

本件是三件事的唯一入口：**键形态解析**（``parse_session_key``）、
**是否群会话**（``is_group_session_key``）、**键构造**（``build_session_key`` /
``private_session_key`` / ``group_session_prefix``；人物级跨会话归属另有
``person_scope_key``——(平台域, 用户号) 身份键的唯一构造，S-FIX-ATK-SCHED2 票1）。构造侧的逐字形态与历史实现
（``meme/reactions/engine.py:session_key_from_ids``、
``chat_reply/character/shared_group.py:_group_prefix``）**字节等价**，
读侧与写侧因此不可能再各说各话。

判据口径（钉死，见 ``tests/test_session_keys_central.py``）：

1. **下划线形**（权威）：``group_<gid>_<sender>`` —— 必须有群号**且**有发送者段，
   两段都不含内部空白（缺发送者段的 ``group_123456``、夹换行的 ``group_\\n1_2``
   都不判群，fail-closed：真实适配器不发这种形，宁可少判也不让半截/拼脏的键
   获得群身份）。
2. **冒号形**（历史/合成/出站）：``group:<gid>`` —— 该形按构造即「整群」语义，
   判群、无发送者段。
3. 前缀识别**大小写不敏感**、两端空白先剥。⚠️ 这是相对旧 engine 判据
   （``startswith("group_")``，区分大小写、不剥空白）的**有意放宽**：没有任何
   适配器产出大写或带空白的键，故对全部真实输入逐字节等价；放宽的价值是让两个
   消费方共用同一份判据、从此无从分叉。
4. **不覆盖的形态（诚实登记，勿当漏洞惊喜）**：官方 QQ 适配器 ``guild_<g>_channel_<c>_<u>``
   与 ``friend_<openid>``、console 的 ``<channel>_<user>`` 不判群（与旧两处判据
   行为一致）。手上有 ``IncomingMessage`` 时，**契约字段路**才是正解
   （``message.session_type`` / ``message.group_id``，见
   ``chat_reply/policy/rate_limit.py:is_group_session``）；本件只管「拿到的是
   一个字符串键」的场景。

全件零 I/O、零网络、零 config 依赖：纯函数，可被任意域离线复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# 权威群前缀（NoneBot ``get_session_id()`` 群事件形态）。
GROUP_SESSION_PREFIX: Final[str] = "group_"
# 历史/合成/出站形态前缀（SendRequest.session_id、推送与 smoke 合成消息）。
LEGACY_GROUP_SCHEME: Final[str] = "group:"
# 缺发送者段时的兜底值（与历史 session_key_from_ids 逐字一致）。
UNKNOWN_SENDER: Final[str] = "unknown"

# 形态标识（parse 结果字段，勿与「会话类型」SessionType 混淆）。
FORM_UNDERSCORE: Final[str] = "group_underscore"
FORM_COLON: Final[str] = "group_colon"
FORM_PRIVATE_SCHEME: Final[str] = "private_scheme"
FORM_BARE: Final[str] = "bare"
FORM_EMPTY: Final[str] = "empty"
FORM_OTHER: Final[str] = "other"

# 会话种类标识。
KIND_GROUP: Final[str] = "group"
KIND_PRIVATE: Final[str] = "private"
KIND_UNKNOWN: Final[str] = "unknown"

_PRIVATE_SCHEMES: Final[tuple[str, ...]] = ("private_", "private:")


def normalize_session_key(value: Any) -> str:
    """键的归一形式：字符串化 + 两端去空白（None/空值 → ``""``）。"""
    return str(value if value is not None else "").strip()


def _has_internal_whitespace(segment: str) -> bool:
    """段内是否夹换行/制表等空白（两端已在 ``normalize_session_key`` 去过）。"""
    return any(char.isspace() for char in segment)


@dataclass(frozen=True)
class SessionKey:
    """解析结果（不猜测、不改写：原始串留在 ``raw``，归一串在 ``normalized``）。"""

    raw: str
    normalized: str
    kind: str  # KIND_GROUP / KIND_PRIVATE / KIND_UNKNOWN
    form: str  # FORM_*
    group_id: str  # 非群键为 ""
    user_id: str  # 无发送者段时为 ""（如冒号形群键）

    @property
    def is_group(self) -> bool:
        return self.kind == KIND_GROUP


def parse_session_key(value: Any) -> SessionKey:
    """会话键 → 结构化形态（唯一判据入口，其余函数都从这里派生）。"""
    raw = "" if value is None else str(value)
    normalized = normalize_session_key(value)
    lowered = normalized.casefold()

    def _result(
        kind: str,
        form: str,
        *,
        group_id: str = "",
        user_id: str = "",
    ) -> SessionKey:
        return SessionKey(
            raw=raw,
            normalized=normalized,
            kind=kind,
            form=form,
            group_id=group_id,
            user_id=user_id,
        )

    if not normalized:
        return _result(KIND_UNKNOWN, FORM_EMPTY)

    if lowered.startswith(GROUP_SESSION_PREFIX):
        remainder = normalized[len(GROUP_SESSION_PREFIX) :]
        group_id, separator, sender = remainder.partition("_")
        if not separator or not group_id:
            # 半截键（"group_123456" / "group__111"）不配获得群身份。
            return _result(KIND_UNKNOWN, FORM_OTHER)
        if _has_internal_whitespace(group_id) or _has_internal_whitespace(sender):
            # 段内夹换行/制表 = 拼出来的脏串，不给群身份（真实适配器键无内部空白）。
            return _result(KIND_UNKNOWN, FORM_OTHER)
        return _result(
            KIND_GROUP,
            FORM_UNDERSCORE,
            group_id=group_id,
            user_id=sender,
        )

    if lowered.startswith(LEGACY_GROUP_SCHEME):
        group_id = normalized[len(LEGACY_GROUP_SCHEME) :].strip()
        if not group_id:
            return _result(KIND_UNKNOWN, FORM_OTHER)
        return _result(KIND_GROUP, FORM_COLON, group_id=group_id)

    for scheme in _PRIVATE_SCHEMES:
        if lowered.startswith(scheme):
            return _result(
                KIND_PRIVATE,
                FORM_PRIVATE_SCHEME,
                user_id=normalized[len(scheme) :].strip(),
            )

    # 其余一律私聊裸键（OneBot 私聊 ``str(user_id)``、mail 发件人 id、
    # console 频道键、channel_/guild_/friend_ 等非群形态）。
    return _result(KIND_PRIVATE, FORM_BARE, user_id=normalized)


def is_group_session_key(value: Any) -> bool:
    """该会话键是否群聊形态（下划线权威形 ∪ 冒号历史/合成形，判据唯一在此）。"""
    return parse_session_key(value).kind == KIND_GROUP


def group_id_of_session_key(value: Any) -> str:
    """群键的群号；非群键返回 ``""``（调用方据此判无数据，绝不退化成全表扫）。"""
    parsed = parse_session_key(value)
    return parsed.group_id if parsed.kind == KIND_GROUP else ""


def _clean_identifier(value: Any) -> str:
    """标识符（群号/用户号）规范形：字符串化去空白（int/str 混型历史实锤）。

    falsy（``None`` / ``0`` / ``False`` / 空集合）一律视作「无该段」，与历史实现
    ``session_key_from_ids`` 的 ``str(x or "")`` 逐字同构——群号 0 不是合法 QQ 群号，
    该口径不改变任何真实输入的结果（见 ``tests/test_session_keys_central.py`` 的
    falsy 钉死用例）。
    """
    return str(value or "").strip()


def build_session_key(group_id: Any, user_id: Any) -> str:
    """会话键唯一构造器，**逐字镜像** OneBot V11 ``get_session_id()``。

    群=``group_<gid>_<uid>``（uid 空→ ``unknown``）；私聊=``<uid>``（空→ ``unknown``）。
    与历史实现 ``meme/reactions/engine.py:session_key_from_ids`` 字节等价。
    """
    group = _clean_identifier(group_id)
    user = _clean_identifier(user_id)
    if group:
        return f"{GROUP_SESSION_PREFIX}{group}_{user or UNKNOWN_SENDER}"
    return user or UNKNOWN_SENDER


def private_session_key(user_id: Any) -> str:
    """私聊键构造（裸 uid，空值兜底 ``unknown``）。"""
    return _clean_identifier(user_id) or UNKNOWN_SENDER


def group_session_prefix(group_id: Any) -> str:
    """群级聚合前缀 ``group_<gid>_``（读侧 LIKE 用，与构造器逐字同构）。

    None/空群号返回 ``""``——``str(None)="None"`` 会造出假前缀 ``group_None_``，
    故 None 单独拦。与历史实现 ``shared_group.py:_group_prefix`` 字节等价。
    """
    normalized = _clean_identifier(group_id)
    if not normalized:
        return ""
    return f"{GROUP_SESSION_PREFIX}{normalized}_"


def group_scope_key(value: Any) -> str:
    """整群共享作用域键（群级状态/群级钉落键的**唯一构造处**，2026-09-27 T-1）。

    病根（台账同族第四次）：群消息的权威会话键 = ``event.get_session_id()`` 是
    **逐成员**下划线形 ``group_<gid>_<uid>``（每人一把）。"全群生效"的状态若落在
    任意一把逐成员键上，其余成员的键段永远拼不出那把键——写侧以为拨了群开关，
    读侧无人收到（fail-safe 方向的静默失效）。本函数把任意群形态键收拢到同一把
    全群共享键，写侧（管理员上钉）与读侧（成员裁决查钉）只准经此构造：

    - 下划线形 ``group_123_456`` → ``group:123``（逐成员键 → 整群作用域键）
    - 冒号形   ``group:123``     → ``group:123``（该形按构造即整群，幂等）
    - 非群键 / 空键 / 半截脏键    → ``""``（调用方自行回落，绝不造出无主群键）

    落键取冒号形是本件钉死的历史语义（「``group:<gid>`` 按构造即整群」，见
    模块 docstring 判据口径第 2 条）：QQ 数字 uid/gid 使逐成员下划线键在字节层
    不可能等于 ``group:<gid>``，成员个人桶与群作用域桶天然不碰撞；合成/开发态
    直接以 ``group:<gid>`` 作会话键时其读写同桶——那正是"整群"的设计语义。
    """
    parsed = parse_session_key(value)
    if parsed.kind != KIND_GROUP:
        return ""
    return f"{LEGACY_GROUP_SCHEME}{parsed.group_id}"


def sanitize_key_segment(value: Any, *, forbidden: str) -> str:
    """组合键段消毒（构造侧共用，2026-09-27 T-2）：清洗 + 剔除段内分隔符。

    先走 ``_clean_identifier`` 的既有清洗口径（字符串化、去两端空白、falsy→
    ``""``），再把 ``forbidden`` 子串的所有出现整体删掉、循环至不动点（删后
    拼接可能再生成新的分隔符）。返回值保证不再含 ``forbidden`` ⇒ 由它拼出的
    组合键拆回几段就是几段：用户可控输入（如 sender_id）无法借分隔符伪造
    嵌套/歧义键。``forbidden`` 为空串时等价 ``_clean_identifier``。
    拆键侧（``rpartition`` 之类）不另立清洗判据——消毒只在构造点这一处发生。
    """
    text = _clean_identifier(value)
    if not forbidden:
        return text
    while forbidden in text:
        text = text.replace(forbidden, "")
    return text


# 人物身份键的分隔符：沿用仓内既有的**冒号限定**形态（policy/roles.py
# ENTRY_SEPARATOR、``email:<id>`` 会话键、出站 ``group:<gid>`` 同族），不新造记号。
PERSON_SCOPE_SEP: Final[str] = ":"


def person_scope_key(platform_domain: Any, user_id: Any) -> str:
    """(平台域, 用户号) → 人物级跨会话归属的**唯一**身份键构造（S-FIX-ATK-SCHED2 票1，2026-09-28）。

    病根（ATK-SCHED 票1/ATKAFF-1 同族）：把「这个人」的存储主键裸建成
    ``str(sender_id)`` 时，**跨平台同号即同号接管**——QQ 号可自选、TG uid
    对群成员公开可见，两侧任一同号者零角色即可读写他人按裸号建键的全部数据。
    在册裁定「跨会话归属按 (平台域, sender_id)」（policy/roles.platform_domain_of
    的 K1B 判据）第一次有了构造侧真身：本函数是该裁定落键的唯一入口，
    读侧/写侧只准从这里取键形，禁在任何域内自拼 ``f"{domain}:{uid}"`` 第二形
    （T-1 键形缺陷教训：判据与构造各自书写，必然再咬一次）。

    - 键形 ``<域>:<用户号>``，与管理员名单的限定条目（``telegram:2002``）逐字
      同构；裸号条目按名单原生域（QQ）归一后的键形同样由本件产出。
    - 两段先过 ``sanitize_key_segment``（T-2）剔除分隔符 ⇒ 用户可控的
      sender_id 塞 ``:`` 也伪不出嵌套/歧义键（拆不回去的键不配存在）。
    - 平台域取不到（未知平台/合成消息）就是空域段 ``":<uid>"``——与 ``"qq:<uid>"``
      天然不同桶，**fail-closed：不认识的平台不继承任何已知平台的归属数据**。
    - 用户号为空返回 ``""``（调用方自行兜底，绝不造出 ``"qq:"`` 这种无主键）。
    """
    uid = sanitize_key_segment(user_id, forbidden=PERSON_SCOPE_SEP)
    if not uid:
        return ""
    domain = sanitize_key_segment(platform_domain, forbidden=PERSON_SCOPE_SEP)
    return f"{domain}{PERSON_SCOPE_SEP}{uid}"
