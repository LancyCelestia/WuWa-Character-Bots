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
    "active_push_key_shape_ok",
    "build_emergency_dedupe_key",
    "date_key_of",
    "is_emergency_dedupe_key",
    "is_legal_date_key",
    "is_legal_segment",
    "is_within_validity",
]
