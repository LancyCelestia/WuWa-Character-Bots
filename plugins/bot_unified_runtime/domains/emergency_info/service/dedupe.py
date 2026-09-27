"""紧急信息去重键规范 + 时效窗判定（纯函数，D-6 可离线测内核）。

去重键规范唯一出处：`specs/B4-outbound-gate-and-delivery-verification.md` §1.3-3
（`emg:{channel}:{item_id}:{target_id}[:{date_key}]`），命名与签名抄
`reports/E5-report.md` §4.3 的 `build_emergency_dedupe_key`。
**本模块只定「键长什么样」与「这条还在不在有效期」**，不新建第二套去重账——
队列 `SQLiteSendRequestQueue.submit` 的 `ON CONFLICT(dedupe_key) DO NOTHING`
（`domains/transport/sender/queue.py:443-475`）才是幂等唯一执行点。

键规范核验的**实现唯一处**就在本文件：`is_emergency_dedupe_key`（前缀 + 段字符集 +
日期段形态三条规则都在这一份代码里），旁支 `active_push_key_shape_ok` 同处同一套
`_SEGMENT_RE`/`_DATE_KEY_RE`——中央闸服务的族自 2026-09-22 起不止紧急域，但**规则
仍只这一份**，闸侧不得另写。中央闸
`domains/transport/sender/outbound_gate.py:dedupe_key_shape_ok` **委托**到这里——
这句话就是 F-4 要对齐的旧账：原注释如此宣称，而闸 2026-09-20 之前实际上自带一套
只查前缀、段数与空段的宽松谓词（HEAD 实证旧谓词亦查前缀等值；LOCK-AUDIT GAP-1：
不查逐段字符集与日期段形态 ⇒ 脏键一边判合规一边判
违规，过闸后队列按整串存两行＝**重发**）。链接注释双向留痕，改规则只改本处；
`tests/test_outbound_gate.py::test_dedupe_predicates_share_one_implementation`
用 AST 钉住「闸侧不许再写一套正则/前缀字面量」。

日期键口径抄现役推送族：`datetime.now().astimezone().date().isoformat()`
（根 `__init__.py:3010/:3177`，daily_assist dedupe `:3351`/群摘要 `:3205` 同族），
差别只在这里把「现在」换成注入参数，保证离线确定性。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    as_utc,
)

#: 键前缀（唯一，禁止各推送族再造 `emergency:`/`emg_push:` 之类第二前缀）。
#: 闸侧 `DEDUPE_NAMESPACE` 引用本常量，不另写字面量。
EMERGENCY_DEDUPE_PREFIX = "emg"

# 段字符集：显式排除 `:`（分隔符）与空白，防键注入与段数歧义。
# 唯一出处——中央闸不得再写第二份（见本模块头注与闸侧 `dedupe_key_shape_ok`）。
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
_DATE_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_key_of(moment: datetime) -> str:
    """日历日键（YYYY-MM-DD）：本地日口径，与现役按日 dedupe 同族。"""
    return as_utc(moment).astimezone().date().isoformat()


def build_emergency_dedupe_key(
    channel: str,
    item_id: str,
    target_id: str,
    date_key: str | None = None,
) -> str:
    """构造投递幂等键；任一参与量为空或含非法字符 ⇒ 抛 ValueError（D-1 不拼假键）。

    按日重投族必须带 `date_key`；一次性事件（同一 item 对同一目标只投一回）
    省略 `date_key`。

    **归一一次、校验与拼键共用**：三段参与量先 `strip()` 再验段字符集，进键的就是
    那个已验过的归一值。原实现校验用 strip 后的值、拼键却用原始入参 ⇒ 带空白的
    入参（如配置串按逗号切开不 strip 得到的 `" 3865067623"`）过了校验却拼出
    `is_emergency_dedupe_key` 判 False 的键：按本模块口径做键规范核验的调用方会拿到
    `skip, reason="dedupe_key_shape"`（推送静默不发＝漏报），而过宽松校验的一侧则把
    两个形态各存一行队列键（幂等失效＝重发）。两头都是「无异常无告警」的错，故在此
    写明——也正因如此，闸侧的键规范核验从 2026-09-20 起**委托本函数**，两侧一套规则。
    """
    normalized: list[str] = []
    for name, raw in (
        ("channel", channel),
        ("item_id", item_id),
        ("target_id", target_id),
    ):
        value = str(raw or "").strip()
        if not value:
            raise ValueError(f"dedupe key part {name} must be non-blank")
        if not _SEGMENT_RE.match(value):
            raise ValueError(f"dedupe key part {name} has illegal characters")
        normalized.append(value)
    channel_text, item_text, target_text = normalized
    key = f"{EMERGENCY_DEDUPE_PREFIX}:{channel_text}:{item_text}:{target_text}"
    if date_key is None:
        return key
    date_text = str(date_key).strip()
    if not _DATE_KEY_RE.match(date_text):
        raise ValueError("dedupe key date_key must be YYYY-MM-DD")
    return f"{key}:{date_text}"


def is_legal_segment(value: str) -> bool:
    """一个字符串能否当键段（`_SEGMENT_RE` 的公开读侧，供生产者与体检用）。

    为什么单独开口而不是让人 `try: build_...except ValueError`：条目 id 的形态由
    采集侧决定，投递侧需要提前把「注定建不出键的行」点名出来并跳过，而不是让它
    在拼键时抛异常、把**整轮**投递一起带走（2026-09-20 实测：`nmc:xxx` 形态的 id
    正中此雷，一条都投不出去且只有一行 `ValueError` 日志）。
    """
    return _SEGMENT_RE.match(str(value or "").strip()) is not None


def is_legal_date_key(value: str) -> bool:
    """日期段形态（`_DATE_KEY_RE` 的公开读侧，与 `is_legal_segment` 成对）。"""
    return _DATE_KEY_RE.match(str(value or "")) is not None


#: 洗段用：只删「不在合法字符集里的字符」，判据本身仍是 `_SEGMENT_RE` 一份。
_ILLEGAL_KEY_SEGMENT_CHAR_RE = re.compile(r"[^A-Za-z0-9_.\-]")
_KEY_SEGMENT_MAX = 120


def active_push_key_segment(value: object) -> str:
    """把一个外部标识洗成合法键段——**构造侧**唯一的洗段口（读侧谓词是 `is_legal_segment`）。

    为什么需要：闸的键形核验只在**开闸态**执法，脏键整条判 `skip`＝静默丢消息，而关闭态
    passthrough 照样发得出去——于是「本地测通」与「上线能发」不是一回事。本波同型炸过
    三次：紧急域 `nmc:A1`（台账 #46，每条真实条目都抛 ValueError）、等待回执（#50）、
    群摘要与日常助理两族（S177 现算：脏群号 ⇒ 整族静默丢）。参与量的形态由适配器与
    `.env` 决定（OneBot 纯数字，TG 频道/guild 侧会出现冒号与其他符号；群号是自由字符
    串），不由我们决定，故一律在出口洗。

    洗完只剩分隔符（`"中文群"`→`"___"`）会让不同输入撞成同一段，那种退化改走摘要，
    键仍然唯一可寻。

    **洗必须近似单射（S184 实测否掉了本函数第一版）**：只把非法字符换成 `_` 再截 120，
    会让 `11 08838060` 与 `11_08838060`、以及第 121 位与第 122 位不同的两个长 id **折成
    同一段** ⇒ 两条真消息共用一个幂等桶＝换一种形态继续静默丢（QQ 纯数字打不到，
    TG/guild 形态打得到）。故凡「真被洗过」的段一律带原串摘要后缀：同输入恒同输出
    （幂等不受影响），不同输入靠摘要分开。空段与洗完只剩分隔符的退化输入同样走摘要。

    **Q-G8（2026-09-27 攻击审计 SEAT-ATK-QUEUE）：「不 strip 直判，非法才加摘要」**。
    S184 那一版的「早退」是**先 `strip()` 再判** ⇒ `" a"` 与 `"a"` 折成同一段、
    `""`/`None`/`"   "` 三种输入折成同一摘要——这就是上面同一段话禁止的「过洗撞桶」，
    只是它藏在 strip 这一步里：不同身份共用一个幂等桶＝静默吞并。现改为：
    - **原串本身就是合法段**才早退（零改写、零后缀）⇒ 已入生产库的合法键形逐字节不变；
    - 其余形态（含一切带前导/尾随空白的变体）**各是一枚身份**：摘要算在 strip 前的
      原串整段上（非字符串输入再带上类型标记，`''`/`None`/`'   '` 三枚摘要互异），
      可读前缀取 strip+字符替换后的洗串——折叠消失，双洗仍逐字节不动（幂等保住在）；
    - 无前后空白的输入（现役全部可达形态：构造点已各自 strip、OneBot/TG 标识原形）
      改前改后输出**逐字节相同**，由 `tests/test_outbound_gate.py` 的迁移锁钉死。
    """
    raw = str(value or "")
    if _SEGMENT_RE.match(raw):
        return raw
    identity = raw if isinstance(value, str) else f"\u0000{type(value).__name__}:{raw}"
    digest = hashlib.blake2b(identity.encode("utf-8"), digest_size=8).hexdigest()
    suffix = "_h" + digest
    washed = _ILLEGAL_KEY_SEGMENT_CHAR_RE.sub("_", raw.strip())[: _KEY_SEGMENT_MAX - len(suffix)]
    if is_legal_segment(washed) and any(char.isalnum() for char in washed):
        return washed + suffix
    return "h" + digest


def wash_active_push_key(dedupe_key: str) -> str:
    """整条主动投递键的规范形：按段分隔符切开逐段洗，再拼回。

    幂等只认整串（`queue.py` 的 `ON CONFLICT(dedupe_key)`），故「每一段都合法」等价于
    「整串过闸的键形核验」。已合法的键逐字节不变 ⇒ 现役各族行为零变化；只有脏段会被
    改写，调用方须把改写当作**可见**事件（中央出口会打一行 warning），别让它变成
    「消息没了但没人知道」的第三种结局。
    """
    raw = str(dedupe_key or "")
    return ":".join(active_push_key_segment(part) for part in raw.split(":"))


def active_push_key_shape_ok(
    key: str, *, namespace: str, require_date_key: bool = False
) -> bool:
    """非紧急族主动投递键的形态核验（中央闸 `reason="dedupe_key_shape"` 的另一半）。

    为什么需要这一条：`dedupe_key_shape_ok` 原先**只**认 `emg` 前缀——那是闸只服务
    紧急域时的边界（见 `is_emergency_dedupe_key` 头注）。2026-09-22 统一波把提醒 /
    cookie 到期 / 群摘要 / 日常助理四族也接进同一个中央出口（用户 mandate「所有内容
    走中央调度层」），若沿用紧急谓词，这四族在**开闸态**会被逐条判 `skip`＝静默丢消息
    （R-CENTRAL C-1，关态测试全绿所以只有开态活性用例抓得到）。

    规则与紧急谓词同源同严，只把「前缀必须是 emg」换成「前缀必须**等值**于本调用方
    申报的命名空间」：

    - 整串不 `strip()`、逐段 `_SEGMENT_RE` 原样匹配（与 `is_emergency_dedupe_key` 同口径）
      ⇒ 带空白的脏键与干净键在队列里各存一行＝重发，这条不能松；
    - 首段等值 ⇒ 近亲前缀（`reminderx`）与串族（拿 `emg:` 冒充 `reminder`）都出局，
      每族一个独立幂等桶；
    - `require_date_key=True`（按日重投族）⇒ 末段必须是 `YYYY-MM-DD`；
    - 段数下限 2（命名空间 + 至少一个身份段），且命名空间自身也得是合法段。
    """
    if not _SEGMENT_RE.match(str(namespace or "")):
        return False
    segments = str(key or "").split(":")
    if len(segments) < 2 or segments[0] != namespace:
        return False
    for segment in segments[1:]:
        if not _SEGMENT_RE.match(segment):
            return False
    if require_date_key:
        return is_legal_date_key(segments[-1])
    return True


def is_emergency_dedupe_key(key: str, *, require_date_key: bool = False) -> bool:
    """键规范核验（中央闸 `reason="dedupe_key_shape"` 的**唯一实现**，闸侧委托到此）。

    `require_date_key=True` 用于「按日重投族必须带日期段」的强校验；未知前缀、空段、
    段内带冒号或空白、日期段形态不对一律 False。四条规则各对应一种真实损害，缺一
    不可（LOCK-AUDIT GAP-1）：

    - 前缀不等值 ⇒ 现役 `digest_push:`/`daily_assist:` 族的键混进紧急通道，闸失去
      「只服务紧急域」的边界含义（近亲前缀 `emg_push:` 同理，故用**等值**不用 startswith）；
    - 段数与空段 ⇒ 键形歧义，`ON CONFLICT` 幂等错位；
    - 逐段字符集（排除空白与 `:`）⇒ 脏键与干净键各存一行队列＝**重复发送**；
    - 日期段形态 ⇒ 「按日重投」退化成永久不再投，或反之。

    整串带空白的键（`"  emg:qq:a:b  "`）判 False：本函数**不**先行 `strip()` 整串。
    旧实现在这里宽松过（strip 后才判），而闸侧严格过 ⇒ 同一个键两侧结论相反；队列按
    整串相等做幂等，两条形态各存一行就是重发。要清洗参与量请用
    `build_emergency_dedupe_key`（它逐段 `strip()` 后才拼键），别指望核验口替你洗。
    """
    text = str(key or "")
    if not text:
        return False
    segments = text.split(":")
    if segments[0] != EMERGENCY_DEDUPE_PREFIX:
        return False
    if len(segments) not in (4, 5):
        return False
    if require_date_key and len(segments) != 5:
        return False
    for segment in segments[1:4]:
        if not _SEGMENT_RE.match(segment):
            return False
    if len(segments) == 5:
        return _DATE_KEY_RE.match(segments[4]) is not None
    return True


def is_within_validity(
    item: EmergencyItem,
    *,
    now: datetime,
    max_age: timedelta | None = None,
) -> bool:
    """时效窗判定：过期、无有效期信息时按「未到期」处理，但年龄超窗即否。

    三条判定按序：
    ① `occurred_at > now` ⇒ False（时间不可信的条目 fail-closed 不投，与
       「白名单空绝不猜群」同向，裁定 D-2 精神）；
    ② `expires_at` 为 None ⇒ 不因缺失效信息误杀（诚实：源未给就是没有）；
       有值且 `<= now` ⇒ False；
    ③ `max_age` 给定时，发生时刻距今超过该窗 ⇒ False（防陈旧预警重投刷屏）。
    """
    current = as_utc(now)
    if item.occurred_at > current:
        return False
    if item.expires_at is not None and item.expires_at <= current:
        return False
    if max_age is None:
        return True
    return (current - item.occurred_at) <= max_age


__all__ = [
    "EMERGENCY_DEDUPE_PREFIX",
    "active_push_key_segment",
    "active_push_key_shape_ok",
    "build_emergency_dedupe_key",
    "date_key_of",
    "is_emergency_dedupe_key",
    "is_legal_date_key",
    "is_legal_segment",
    "is_within_validity",
    "wash_active_push_key",
]
