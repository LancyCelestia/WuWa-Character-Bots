"""紧急域一切主动投递的唯一出口（施工图 §4-面11，§5-钉死③ 的落点）。

三条结构约束（改本文件前先读完，都是方向性后果而非风格偏好）：

1. **投递只经中央闸 `submit_active_push`**：域内任何地方（含本文件）出现裸
   `send_queue.submit(...)` 即绕过安静时间窗、每主体限流与键规范核验。
   现役六个推送族（提醒/cookie 到期/群摘要/日常助理/错误卡/管理员告警）今天根本
   不过闸，本域是第一个走通这个口子的（`tests/test_emergency_info_core.py`
   锁 B、`tests/test_outbound_gate.py` T6/T6b 三侧同钉）。
2. **`priority=str(item.level.value)` 是唯一 severity 载体**（施工图 §5-钉死①）：
   闸侧 `_severity_of`→`_is_urgent`→`_quiet_verdict` 只读这一个字段。漏传或传
   `"normal"` ⇒ 安静时间窗（00:00–06:00）内 P0 被当非紧急顺延到窗尾 = **漏报**，
   且**不抛异常、不记 degraded、不进告警**，离线测试还全绿（闸缺省关闭走裸 submit）。
   等级塞进 `audit_tags` / 新建字段 = 造第二载体，施工图 §5-钉死① 明令禁止；
   `content.risk_level` 是审计用的公共告警档，按契约层唯一映射口 `to_risk_level()`
   填，不参与紧急判定（两者用途不同，不构成第二载体）。
3. **未定级不投递、不冒充等级**（D-1）：`item.level is None` ⇒
   `deliver_emergency` 直接返回 `"skip_ungraded"`；`build_emergency_send_request`
   抛 `ValueError`。定级的唯一出口是 `service/review.py`
   `ReviewGate.publishable_level(item, now=...)`（权威源自动过审按 D-8(a)），
   没经它判过的条目身上 `level` 就是 None，本文件不得替它补一个档位。

键形规范唯一出处 = `service/dedupe.py:build_emergency_dedupe_key`（核验口
`is_emergency_dedupe_key`，前缀常量 `EMERGENCY_DEDUPE_PREFIX="emg"`）。本文件
**禁止**再拼一套 `emergency:`/`emg_push:` 形态——脏键与干净键在队列里各存一行，
幂等失效＝**重发**（LOCK-AUDIT GAP-1）。

时效腿（F-1，SEAT-ATK-EMERGENCY-SUB）：判据唯一真身在 `service/dedupe.py:is_within_validity`
（三条按序、fail-closed），本文件只在 `deliver_emergency` 里调**一处**、且必须在触闸之前。
理由不是风格：按日重投的幂等键**日期段每天换新**，`ON CONFLICT` 天生拦不住跨天，
所以「已到期／发生在未来／超龄」的条目在保留期（缺省 90 天）内会**每天再推一次给同一个群**
——台账 #46 裁定的反面。NMC 源根本不填 `expires_at`，超龄腿是唯一拦阻，它一旦没接，
整条链就没有任何人挡陈旧预警。执法留在唯一出口、不交调用方（AST 活性锁
`tests/test_emergency_info_push.py::test_validity_predicate_is_enforced_at_the_single_touchpoint`
判「恰一处调用且行号先于触闸」）。丢弃不是静默丢：经**闸自己的** `note_issue`
申报 `OperationalIssue`，走装配期已接好的中央告警口（折叠抑制 + 台账 TTL 同一条链），
本文件不 import config、不新建 logger、不开第二条直发腿。

按日重投族：本域对「同一条预警每天仍可再投一回」的语义走 `dedupe_family="daily"`
⇒ 键必须五段（带 `date_key`）。家族值写的是字面量 `"daily"` 而非闸侧常量
`DEDUPE_FAMILY_DAILY`，因为 `tests/test_emergency_info_core.py`
锁 D 用 AST 静态判定 family↔date_key 同真同假，非字面量会被判「静态判不出」当场
要求补形态；两者相等由 `tests/test_emergency_info_push.py` 钉住，漂移即红。

时钟一律注入（本层 D-6 口径），本文件不读墙钟、不 import config、不读 .env。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from pydantic import field_validator, model_validator

from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    OperationalIssue,
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
    StrictBaseModel,
)
from plugins.bot_unified_runtime.domains.emergency_info.contracts import (
    EmergencyItem,
    to_risk_level,
)

# 告警 stage 词唯一真身在采集侧（`collector.ISSUE_STAGE`，注释原话「不新建第二套
# stage 词」）；投递侧只引用同一枚，不在本文件再抄一遍字符串。collector 不 import
# 本文件，无环。
from plugins.bot_unified_runtime.domains.emergency_info.service.collector import (
    ISSUE_STAGE,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    build_emergency_dedupe_key,
    date_key_of,
    is_within_validity,
)
from plugins.bot_unified_runtime.domains.emergency_info.service.grading import (
    may_breach_quiet_window_intersects_floor,
)

# 闸侧唯一入口（施工图 §5-钉死③.1：真身签名
# `submit_active_push(send_queue, send_request, gate, *, now=None,
# dedupe_family="once")`，**没有** `settings=`/`quiet_settings=` 形参）。
from plugins.bot_unified_runtime.domains.transport.sender.outbound_gate import (
    submit_active_push,
)

#: 未定级条目的投递结论（唯一口径，消费方不得自造 `"skip"`/`"none"` 同义词）。
SKIP_UNGRADED = "skip_ungraded"

#: 静默窗内、按族规则**不够格叫醒人**的条目结论（WP3 交付②的新增第四态）。
#: 语义必须与 `skip_ungraded` 分开：那一态是「没判过所以不能投」，这一态是
#: 「判过了、但这一档不值得在 00:00–06:00 打断睡眠」——条目仍留在库里，
#: 出窗后的下一轮照常投（按日幂等键此前没被占用），**不是丢弃**。
SKIP_QUIET_HOURS = "skip_quiet_hours"

#: 时效窗外的条目结论（F-1 的第四态）：已到期／发生在未来／超龄 ⇒ **不投**，与
#: `skip_quiet_hours` 不同——那一态是「本轮先压住、出窗后照常投」，这一态是
#: 「这条永远不该再出板」，条目留在库里只等保留期把它清掉，不承诺下一轮。
SKIP_EXPIRED = "skip_expired"

#: 投递侧的超龄窗：与「按日重投」同宽（幂等键按日换新 ⇒ 超过一天就是旧事重提）。
#: 缺省值写成模块常量而不是 config 键：改根装配文件属另一工作包，想按环境改数请由
#: 调用方传 `max_age=`（`None` 只摘超龄腿③，①未来②已到期保持无条件 fail-closed）。
PUSH_MAX_AGE = timedelta(days=1)

#: 时效丢弃的告警 kind（stage 用采集侧同一枚词；折叠键由中央抑制器按 stage+kind+目标算）。
ISSUE_KIND_PUSH_EXPIRED = "push_expired"

#: 本域 capability_id（路由面/闸审计面同源）。
EMERGENCY_CAPABILITY_ID = "bot.emergency_info"

#: 投递正文长度上限（与既有推送族同口径：告警文本 [:4000]）。
MAX_PUSH_TEXT_CHARS = 4000


class EmergencyTarget(StrictBaseModel):
    """一条紧急条目的投递目标（纯数据，零 IO）。

    `channel` 是去重键的第二段，必须是 `dedupe.py:_SEGMENT_RE` 允许的字符集
    （`[A-Za-z0-9_.-]`，禁空白与 `:`）——写成 `"qq group"` 之类会在建键时抛
    ValueError，这是刻意的：宁可炸，不要拼出一条核验口判 False 的键（那样
    闸会返回 `skip, reason="dedupe_key_shape"`＝静默不发＝漏报）。
    """

    target_id: str
    target_scope: SessionType = SessionType.PRIVATE
    session_id: str = ""
    channel: str = "qq"
    adapter: str = ""
    bot_id: str = ""
    persona_profile_id: str = "default"

    @field_validator("target_id", "channel")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("emergency target field must be non-blank")
        return normalized

    @model_validator(mode="after")
    def default_session_id(self) -> EmergencyTarget:
        """会话键缺省按现役推送族形态 `private:<id>` / `group:<id>` 生成。"""
        if not str(self.session_id or "").strip():
            object.__setattr__(
                self, "session_id", f"{self.target_scope.value}:{self.target_id}"
            )
        else:
            object.__setattr__(self, "session_id", str(self.session_id).strip())
        return self


def build_emergency_push_text(item: EmergencyItem) -> str:
    """投递正文唯一拼法：颜色档 + 标题 + 正文 + 来源链接（缺什么就不写什么）。

    未定级条目 `color_text` 是空串（契约层已锁），因此这里不会替它编一个颜色。
    """
    head = item.title
    if item.color_text:
        head = f"【{item.color_text}预警】{item.title}"
    lines = [head]
    if item.body:
        lines.append(item.body)
    if item.url:
        lines.append(f"来源：{item.url}")
    text = "\n".join(lines)
    if len(text) > MAX_PUSH_TEXT_CHARS:
        text = text[:MAX_PUSH_TEXT_CHARS]
    return text


def build_emergency_send_request(
    item: EmergencyItem,
    target: EmergencyTarget | None = None,
    *,
    now: datetime,
    priority: str | None = None,
    dedupe_key: str | None = None,
    channel: str | None = None,
    target_id: str | None = None,
    session_id: str | None = None,
    date_key: str | None = None,
) -> SendRequest:
    """构造紧急投递请求：`priority` 缺省即等级字面量（`"P0".."P3"`）。

    `target` 是正规入参；只给 `channel`/`target_id`/`session_id` 的退化形态服务
    「装配面手里只有裸 QQ 号」（配置里的 `bot_emergency_info_push_user_ids` 就是
    `list[str]`），此时目标按私聊档处理——群投递请显式构造 `EmergencyTarget`
    （`target_scope=SessionType.GROUP`），别靠猜。退化形态只在 `target is None`
    时生效，两者同时给出时以 `target` 为准（不静默覆盖任何一格）。

    `dedupe_family="daily"` 与「键带 date_key」必须同真：本函数缺省按五段键建，
    调用方另传 `dedupe_key` 时由调用方负责同真同假（`deliver_emergency` 已按
    本口径建键）。
    """
    if item.level is None:
        raise ValueError(
            "ungraded emergency item must not produce a send request (D-1)"
        )
    resolved = _resolve_target(target, channel, target_id, session_id)
    effective_date_key = date_key_of(now) if date_key is None else str(date_key)
    key = dedupe_key or build_emergency_dedupe_key(
        resolved.channel,
        item.item_id,
        resolved.target_id,
        date_key=effective_date_key,
    )
    request_id = f"emergency-{item.item_id}-{resolved.target_id}-{effective_date_key}"
    privacy = (
        PrivacyLevel.GROUP
        if resolved.target_scope is SessionType.GROUP
        else PrivacyLevel.PERSONAL
    )
    text = build_emergency_push_text(item)
    cooldown_key = build_emergency_dedupe_key(
        resolved.channel,
        item.item_id,
        resolved.target_id,
    )
    return SendRequest(
        request_id=request_id,
        session_id=resolved.session_id,
        target_scope=resolved.target_scope,
        target_id=resolved.target_id,
        capability_id=EMERGENCY_CAPABILITY_ID,
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={"text": text},
            text_fallback=text,
            risk_level=to_risk_level(item.level),
            privacy_level=privacy,
        ),
        # 投递节奏由中央闸决定（安静窗顺延/限流），队列侧只按排队走。
        send_policy=SendPolicy.QUEUED,
        priority=priority or str(item.level.value),
        max_messages=1,
        dedupe_key=key,
        # 冷却键=去重键去掉日期段（同现役族「按目标冷却、按日重投」的分工）；
        # 同样出自 `build_emergency_dedupe_key`，不另拼一套形态。
        cooldown_key=cooldown_key,
        privacy_level=privacy,
        persona_profile_id=resolved.persona_profile_id,
        adapter=resolved.adapter,
        bot_id=resolved.bot_id,
        audit_tags=["emergency_info", "daily"],
    )


def _resolve_target(
    target: EmergencyTarget | None,
    channel: str | None,
    target_id: str | None,
    session_id: str | None,
) -> EmergencyTarget:
    if target is not None:
        return target
    resolved_target_id = str(target_id or "").strip()
    if not resolved_target_id:
        raise ValueError(
            "build_emergency_send_request needs an EmergencyTarget or a target_id"
        )
    return EmergencyTarget(
        target_id=resolved_target_id,
        channel=str(channel or "qq").strip() or "qq",
        session_id=str(session_id or "").strip(),
    )


def _gate_urgent_levels(gate: Any) -> frozenset[str]:
    """闸认为「够格穿窗」的等级集合（唯一事实源＝闸自己的 `settings.urgent_severities`）。

    闸未装配/未启用/读不到 ⇒ 空集：本域这层抑制**只在闸会真的穿窗时才有意义**，
    闸关着的时候静默窗根本不存在，多事反而改变既有行为。
    """
    settings = getattr(gate, "settings", None)
    if settings is None or not bool(getattr(settings, "enabled", False)):
        return frozenset()
    return frozenset(
        str(value or "").strip().upper()
        for value in (getattr(settings, "urgent_severities", ()) or ())
        if str(value or "").strip()
    )


def _quiet_window_active(gate: Any, now: datetime, scope: str) -> bool:
    """这个目标此刻是否在静默窗内。

    窗口事实与判定式**一律不自建**：设置取自闸的公开 `quiet` 属性
    （其唯一真身是 `domains/chat_reply/policy/quiet_hours.py`），
    判定直接调 `QuietHoursChecker._is_in_quiet_hours(clock=注入 now)`——
    与本仓其他地方「双向对齐、不抄第二份」的做法同型；`session_types` 那一腿
    也照闸侧同样先判（群才受窗约束，私聊不受），任何一环读不到都**按不在窗内**处理
    （读不通就拦人＝把观测面的故障变成漏报，方向错了）。
    """
    quiet = getattr(gate, "quiet", None)
    if quiet is None or not bool(getattr(quiet, "enabled", False)):
        return False
    session_types = {
        str(value or "").strip().lower() for value in (getattr(quiet, "session_types", ()) or ())
    }
    if scope.lower() not in session_types:
        return False
    try:
        from plugins.bot_unified_runtime.domains.chat_reply.policy.quiet_hours import (
            QuietHoursChecker,
        )

        checker = QuietHoursChecker(quiet, clock=lambda: now)
        return bool(checker._is_in_quiet_hours())
    except Exception:  # noqa: BLE001 - 读不通按不在窗内（与闸侧同一方向）
        return False


def should_hold_for_quiet_window(
    item: EmergencyItem,
    gate: Any,
    *,
    now: datetime,
    target_scope: str = "group",
    breach_levels: Sequence[str] | None = None,
) -> bool:
    """WP3 交付②的落地判据：这条够不够格在静默窗内叫醒这个目标。

    True＝本轮先压住（出窗后下一轮照常投）。成立条件三腿全真：
    ① 闸确实会为本条穿窗（等级在闸的 `settings.urgent_severities` 里）；
    ② 按「源级表 ∩ 族级地板」**不够格**穿窗（
       `grading.may_breach_quiet_window_intersects_floor` 判否——族级地板如
       `global_disaster` 只认红档，装配侧搬来的 `quiet_breach_levels` 只能收窄、
       不能把地板抬宽）；
    ③ 此刻这个目标确实在静默窗内。
    任何一腿读不到都返回 False（保守交回闸判定，与 D-1「不猜」同向）。
    """
    level = item.level
    if level is None:
        return False
    if str(level.value).upper() not in _gate_urgent_levels(gate):
        return False
    if may_breach_quiet_window_intersects_floor(item, level, source_levels=breach_levels):
        return False
    return _quiet_window_active(gate, now, str(target_scope or "").strip() or "group")


def _note_expired_drop(
    gate: Any, item: EmergencyItem, target: EmergencyTarget, *, max_age: timedelta | None
) -> None:
    """把一次时效丢弃冒到运维面：**复用闸自己的告警口**，不另造 logger／直发腿。

    `gate.note_issue` 在装配期接的是根侧唯一中央告警出口（`_push_probe_issue` ⇒
    管理员告警 + 300s 折叠抑制 + 台账 TTL 那一条链，QG9① 的先例），本域只申报
    自己的 stage/kind——「消息没了但没人知道」是这个缺陷的原形态，所以丢弃必须出声。

    观测口任何形式的病都不带走投递结论（与闸侧 `note_issue` 的「观测不得炸投递链路」
    同纪律）：闸替身／装配前的对象读不到 `note_issue` 就只放弃这一笔观测。
    摘要里只放条目 id 与 channel（照闸侧 `_issue` 的先例：零正文、目标身份不进告警文本）。
    """
    note = getattr(gate, "note_issue", None)
    if not callable(note):
        return
    try:
        note(
            OperationalIssue(
                stage=ISSUE_STAGE,
                kind=ISSUE_KIND_PUSH_EXPIRED,
                retryable=False,
                safe_summary=(
                    f"reason=outside_validity_window item={item.item_id} "
                    f"channel={target.channel} max_age={max_age}"
                )[:200],
            )
        )
    except Exception:  # noqa: BLE001 - 告警口生病只放弃观测，不改投递结论。
        return


def deliver_emergency(
    send_queue: Any,
    gate: Any,
    item: EmergencyItem,
    target: EmergencyTarget,
    *,
    now: datetime,
    breach_levels: Sequence[str] | None = None,
    max_age: timedelta | None = PUSH_MAX_AGE,
) -> str:
    """域内唯一投递触点：过闸，返回闸的结论（`allow`/`defer`/`skip`），
    或本域自己的三态前置结论（`skip_ungraded`/`skip_quiet_hours`/`skip_expired`）。

    返回的是 `outcome.verdict.action` 原文，**不是**队列回执状态；调用方据此区分
    「已投出/被顺延/被拒」。回执里的 `operational_issue`（degraded/storm）在
    `issue_sink` 接线前只能落日志，不得宣称「已告警」（施工图 §5-钉死③.4）。

    未定级 ⇒ `"skip_ungraded"`，不碰队列、不碰闸（D-1）。
    键形非法（`item_id`/`channel`/`target_id` 含空白或冒号等）⇒ 由
    `build_emergency_dedupe_key` 抛 ValueError，本函数**不吞**：宁可炸给调用方看，
    也不要退化成裸 submit 或静默不发。

    `breach_levels`（WP3 交付②）＝装配侧从快照
    `EmergencyInfoSource.quiet_breach_levels` 搬运的「允许击穿静默窗等级」名单；
    缺省 None＝用族级规则单独决定（缺省族级＝红/橙＝与今天一致）。
    根装配目前按位置/关键字都不传这一参（改根文件属另一工作包），因此**主会话落键后
    须把 `breach_levels=source.quiet_breach_levels` 加进那一次调用**——见 WP3 交接段。

    `max_age`（F-1 时效腿）＝超龄窗，缺省 `PUSH_MAX_AGE`（一天，与按日重投同窗）；
    传 `None` **只**摘掉③超龄腿，①「发生在未来」与②「`expires_at` 已到期」保持无条件
    fail-closed——这条分工是中央判据 `dedupe.is_within_validity` 现成的形状，调用方
    一律不得在本地重做（本函数体内该判定的调用点恰一处，AST 锁执法）。
    """
    if item.level is None:
        return SKIP_UNGRADED
    if should_hold_for_quiet_window(
        item,
        gate,
        now=now,
        target_scope=str(
            getattr(target.target_scope, "value", None) or target.target_scope
        ),
        breach_levels=breach_levels,
    ):
        return SKIP_QUIET_HOURS
    if not is_within_validity(item, now=now, max_age=max_age):
        # 判序：定级门 → 静默窗 → 时效。放在静默窗**之后**是刻意的：既让时效结论仍然
        # 先于任何入队动作（安全面等价），又不改动 `skip_quiet_hours` 那一态今天的
        # 出口形态（本席无权改它）；这类「窗内且已过时效」的条目出窗后的下一轮
        # 照样会落到本判定被拦下，不存在漏放。
        _note_expired_drop(gate, item, target, max_age=max_age)
        return SKIP_EXPIRED
    dedupe_date_key = date_key_of(now)
    dedupe_key = build_emergency_dedupe_key(
        target.channel,
        item.item_id,
        target.target_id,
        date_key=dedupe_date_key,
    )
    request = build_emergency_send_request(
        item,
        target,
        now=now,
        priority=str(item.level.value),
        dedupe_key=dedupe_key,
    )
    outcome = submit_active_push(
        send_queue,
        request,
        gate,
        now=now,
        dedupe_family="daily",
    )
    return str(outcome.verdict.action)


__all__ = [
    "EMERGENCY_CAPABILITY_ID",
    "ISSUE_KIND_PUSH_EXPIRED",
    "PUSH_MAX_AGE",
    "SKIP_EXPIRED",
    "SKIP_QUIET_HOURS",
    "SKIP_UNGRADED",
    "EmergencyTarget",
    "build_emergency_push_text",
    "build_emergency_send_request",
    "deliver_emergency",
    "should_hold_for_quiet_window",
]
