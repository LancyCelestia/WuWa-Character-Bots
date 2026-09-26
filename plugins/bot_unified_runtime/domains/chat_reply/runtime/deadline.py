"""请求级单调时钟预算（handover 9.2）。

同一用户请求从 LLM、工具循环到发送共用一个单调时钟 deadline；各阶段只能
消费剩余预算，不能各自重新计时。只记录固定阶段名与耗时，不记录用户正文。
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Sequence


class DeadlineExceeded(RuntimeError):
    """请求总预算耗尽；对应稳定错误 kind=``deadline_exceeded``，不可自动重试。"""


class DeadlineBudget:
    """单调时钟预算：started_at + 绝对 deadline + 剩余时间 + 阶段耗时。

    total_seconds<=0 表示未启用（所有门控退化为无操作，保持旧调用方行为）。
    """

    def __init__(self, total_seconds: float, *, started_at: float | None = None) -> None:
        number = float(total_seconds)
        if math.isnan(number) or number <= 0:
            number = 0.0
        self.total_seconds = number
        self.started_at = (
            float(started_at) if started_at is not None else time.monotonic()
        )
        self.phases_ms: dict[str, float] = {}
        # 在飞相位名（供 deadline 回执回答"预算到期那一刻哪一段正跑到一半"）。
        # 只认 _safe_phase_name 通过的固定字面量；未标注恒为空串 ⇒ 视图诚实降级
        # 为「未记账」，绝不编数。record_phase 归账同一相位时自动清除。
        self.in_flight_stage: str = ""

    @property
    def enabled(self) -> bool:
        return self.total_seconds > 0

    @property
    def deadline(self) -> float | None:
        """绝对单调时钟 deadline；未启用返回 None（调用方保持自身默认）。"""
        if not self.enabled:
            return None
        return self.started_at + self.total_seconds

    def remaining_seconds(self) -> float:
        deadline = self.deadline
        if deadline is None:
            return math.inf
        return deadline - time.monotonic()

    def expired(self) -> bool:
        return self.enabled and self.remaining_seconds() <= 0.0

    def ensure_available(self, stage: str = "") -> None:
        """预算耗尽后不允许再启动新的网络调用。"""
        if self.expired():
            raise DeadlineExceeded(stage or "deadline_exceeded")

    def timeout_for(self, default_seconds: float | None) -> float | None:
        """调用方超时与剩余预算取最小值；未启用返回 None 保持调用方默认。"""
        if not self.enabled:
            return None
        remaining = self.remaining_seconds()
        if remaining <= 0.0:
            raise DeadlineExceeded("timeout_for")
        default = float(default_seconds) if default_seconds else remaining
        return max(0.0, min(default, remaining))

    def mark_in_flight(self, stage: str) -> None:
        """标注「此刻在跑哪一段」（供预算耗尽时回执点名在飞相位）。

        只接受固定阶段名形态；非法名（含用户正文/换行）静默丢弃，**不覆盖**已
        有合法标注——卫生优先于记账，与 phase_tags 的消毒同一口径。
        """
        name = _safe_phase_name(stage)
        if name:
            self.in_flight_stage = name

    def record_phase(self, stage: str, started_at: float) -> None:
        """累计阶段耗时（毫秒）；stage 只允许固定阶段名，不含用户内容。"""
        elapsed_ms = max(0.0, (time.monotonic() - started_at) * 1000.0)
        self.phases_ms[stage] = self.phases_ms.get(stage, 0.0) + elapsed_ms
        # 该相位已归账 ⇒ 不再是「在飞」（避免成功路径上留下过期的在飞标注，
        # 也避免它在后续 deadline 回执里被当成"到期那一刻正跑到一半"）。
        if stage == self.in_flight_stage:
            self.in_flight_stage = ""

_PHASE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

#: 派生量（合计）的去重方向与固定相位**相反**，见 ``merge_phase_tags``。
_DERIVED_PHASE_KEYS: frozenset[str] = frozenset({"phase_total_ms"})


def merge_phase_tags(
    posted_tags: Sequence[str], late_tags: Sequence[str]
) -> tuple[list[str], list[str]]:
    """把"晚到的相位快照"并进已贴好的标签，返回 ``(保留的旧标签, 需要追加的新标签)``。

    存在理由：``phase_tags()`` 在同一轮里会被取两次——一次在 ``build_chat_result``
    内（早于 LLM 归账），一次在 LLM 归账之后。固定相位按"已贴过为准"去重是对的
    （同一轮里 ``phase_vision_ms`` 不该出现两枚），但 ``phase_total_ms`` 是**派生量**：
    早快照只加了当时已归账的相位，晚到的才是真值。沿用同一套去重会把合计永久
    钉死在 0，产出自相矛盾的一行（2026-09-26 实锤：``phase_total_ms:0`` 与
    ``phase_llm_ms:3284`` 同挂一条回执，复盘时看起来像"记账说这轮没花时间"）。
    """
    late_keys = {str(tag).split(":", 1)[0] for tag in late_tags}
    superseded = late_keys & _DERIVED_PHASE_KEYS
    kept = [
        tag
        for tag in posted_tags
        if str(tag).split(":", 1)[0] not in superseded
    ]
    posted_keys = {str(tag).split(":", 1)[0] for tag in kept}
    added = [
        tag for tag in late_tags if str(tag).split(":", 1)[0] not in posted_keys
    ]
    return kept, added



def _safe_phase_name(stage: object) -> str:
    """相位名消毒：只放行固定字面量形态，其余一律回空串。"""
    text = str(stage or "")
    return text if _PHASE_NAME_RE.match(text) else ""


def phase_tags(budget: DeadlineBudget | None) -> list[str]:
    """相位耗时 → 诊断标签（``phase_<stage>_ms:<整数>`` + 合计）。

    存在理由：``phases_ms`` 一直在累计却无人落盘，导致 2026-09-23 那次
    "每条消息 140-395 秒"只能靠回复总时长 + CPU 占用反推，连续三天没人能
    指认是哪一段慢。阶段名只接受固定字面量形态，异常值（含用户正文或换行）
    直接丢弃，绝不进入诊断标签。
    """
    if budget is None:
        return []
    tags: list[str] = []
    total = 0.0
    for stage in sorted(budget.phases_ms):
        if not _PHASE_NAME_RE.match(str(stage)):
            continue
        elapsed = float(budget.phases_ms[stage])
        total += elapsed
        tags.append(f"phase_{stage}_ms:{round(elapsed)}")
    if not tags:
        return []
    tags.append(f"phase_total_ms:{round(total)}")
    return tags


# ============================================================================
# deadline_exceeded 回执自解释化（S-T-DEADLOG-1/2，2026-09-26）
# ============================================================================
# 生产实弹（2026-09-26 01:12 私聊，超管反馈「回复错误」）：
#
#   event=pipeline_result capability_id=bot.chat receipt_state=queued
#     transport=sqlite_queue duration_ms=333254.0 error_kind=deadline_exceeded
#
# 同族 00:53 的行带 ``route_attempts=...``，这一行什么都没有——300 秒总预算花在
# 哪一跳、哪个阶段，事后完全不可归因。相位记账（``record_phase``）与逐跳轨迹
# （``llm_route_attempt:<模型>:<死因>``）本来就在手里，缺的是**一个把它们组装进
# 回执、并在归因不到时如实写「未记账」的出口**。下面两个函数就是那个出口，
# 而且是唯一出口：调用方（chat.py 的两条 deadline 断点、根 __init__ 的回执行
# 提取口）只许调用，不许另拼一份字符串——第二真身是本仓反复点名过的形态。
#
# 🔴 本段只负责「看得见」，不负责「跑得快」：不读不写任何超时/预算数值，
#    bot_chat_failover_max_seconds / bot_request_budget_seconds / connect·read
#    timeout / 冷却时长一律原样（2026-09-23 那笔 300→60 已被用户实弹否掉）。

#: 「这一行是预算耗尽的回执，且诊断要素已按下面的字段集给全」的稳定记号。
#: 行内形态 ``deadline_diag=1``，与 ``route_attempts=``/``error_kind=`` 同风格，
#: 便于 grep 与事后统计「有回执 vs 无回执」的占比。
DEADLINE_DIAG_TAG = "deadline_diag:1"
DEADLINE_DIAG_PREFIX = "deadline_diag:"

#: 归因不到时写什么。**绝不用 0、也绝不用空列表**糊过去——「没查到」与「没有」
#: 是两件事（本仓铁律；同型事故见紧急域 09-20 的 ``nmc:A1`` 那发 Critical）。
UNRECORDED_MARK = "未记账"

#: 逐跳轨迹复用既有前缀：根 __init__ 的 ``_runtime_tag_values`` 早已按这个前缀
#: 拼 ``route_attempts=``，本波换载体不换钥匙，诊断卡与 /bot dialogue 的读法
#: （domains/ops/smoke/diagnostics.py::infer_llm_route_hops）也一并继续生效。
LLM_ROUTE_ATTEMPT_TAG_PREFIX = "llm_route_attempt:"

#: 单跳串长度上限：与根提取口既有的 ``[:120]``、chat.py 建标签时的 ``[:120]``
#: 同值，避免同一枚 hop 在两个环节被截成两种长度。
_MAX_HOP_CHARS = 120

#: ``ensure_available()`` 无守卫名时的兜底 args[0]——它是**错误代号**不是阶段名，
#: 拿它当「在飞相位」会把每条裸断都报成同一个假相位，所以显式排除。
_DEADLINE_SENTINEL_NAMES = frozenset({"deadline_exceeded"})

_WHITESPACE_RE = re.compile(r"\s+")

#: deadline 回执的字段全集（提取口缺哪补哪，一律写「未记账」而不是省略）。
DEADLINE_RECEIPT_FIELDS = (
    "deadline_diag",
    "deadline_in_flight",
    "deadline_attempts",
    "deadline_remaining_ms",
    "deadline_elapsed_ms",
    "deadline_unaccounted_ms",
)


def _safe_hop(value: object) -> str:
    """单跳轨迹消毒：去掉不可打印字符、折叠空白、截断，**不改写内容**。

    为什么不用「非法就整枚丢弃」：``deadline_attempts`` 的计数与发出的 hop 标签
    数必须严格一致——悄悄吃掉一枚再报「少了的那枚不存在」就是谎报。所以这里只做
    形态消毒（用户正文/换行进不来，对齐 ``_safe_phase_name`` 的卫生口径），
    消毒后仍非空的一律算数。
    """
    text = "".join(char if char.isprintable() else " " for char in str(value or ""))
    return _WHITESPACE_RE.sub(" ", text).strip()[:_MAX_HOP_CHARS]


def _guard_name_from_exception(exc: BaseException | None) -> str:
    """从异常携带的守卫名还原「预算在检查哪一段时到期」（消毒后，宁缺毋滥）。"""
    if exc is None:
        return ""
    args = getattr(exc, "args", ()) or ()
    if not args:
        return ""
    name = str(args[0] or "")
    if name in _DEADLINE_SENTINEL_NAMES:
        return ""
    return _safe_phase_name(name)


def _budget_remaining_ms(budget: DeadlineBudget | None) -> float | None:
    """当时的剩余预算（毫秒，可为负=已超支）；未启用/无限 ⇒ None（不可知）。"""
    if budget is None or not budget.enabled:
        return None
    remaining = budget.remaining_seconds()
    if not math.isfinite(remaining):
        return None
    return remaining * 1000.0


def _budget_elapsed_ms(budget: DeadlineBudget | None) -> float | None:
    """回执组装那一刻已走过的墙钟（毫秒）；与预算是否启用无关，故 None 仅在无预算。"""
    if budget is None:
        return None
    return max(0.0, (time.monotonic() - budget.started_at) * 1000.0)


def _ms_or_unrecorded(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return UNRECORDED_MARK
    return str(round(value))


def _tag_value(tags: Sequence[str], prefix: str) -> str:
    """取该前缀标签的值（首枚命中）；没有则空串。"""
    for tag in tags:
        text = str(tag)
        if text.startswith(prefix):
            return text[len(prefix):]
    return ""


def deadline_receipt_tags(
    budget: DeadlineBudget | None,
    *,
    attempts: Sequence[str] | None = None,
    in_flight: str = "",
    exc: BaseException | None = None,
) -> list[str]:
    """预算耗尽回执的**唯一组装口**：相位拆分 + 逐跳轨迹 + 在飞相位 + 剩余预算。

    四条要素各自独立降级，缺哪记哪（写「未记账」），绝不省略字段：

    * ``deadline_in_flight`` 取值优先级 = 显式参数 > 预算上的在飞标注
      （``mark_in_flight``，语义是「哪一段跑到一半没归账」）> 异常携带的守卫名
      （``ensure_available(stage=…)`` 的 stage，语义是「在哪一处闸门发现到期」）
      > 未记账。前者优先：回答「时间花在哪」要看没归账的那段。
    * ``attempts=None``（调用方没交轨迹）⇒ 计数写未记账；交来的是**空列表**⇒
      计数如实写 0——这两种形态的分别正是本次要区分的东西，不能都塌成 0。
    * 相位拆分逐字节复用 ``phase_tags()``（禁第二套格式化器）；一枚都没记到时
      另发 ``deadline_phases:未记账``，并把已走过的时间整体记成
      ``deadline_unaccounted_ms``——「这 N 毫秒不属于任何记账阶段」本身就是结论。
    """
    tags: list[str] = [DEADLINE_DIAG_TAG]

    stage = _safe_phase_name(in_flight)
    if not stage and budget is not None:
        stage = budget.in_flight_stage
    if not stage:
        stage = _guard_name_from_exception(exc)
    tags.append(f"deadline_in_flight:{stage or UNRECORDED_MARK}")

    tags.append(f"deadline_remaining_ms:{_ms_or_unrecorded(_budget_remaining_ms(budget))}")
    elapsed_ms = _budget_elapsed_ms(budget)
    tags.append(f"deadline_elapsed_ms:{_ms_or_unrecorded(elapsed_ms)}")

    hop_tags = [
        f"{LLM_ROUTE_ATTEMPT_TAG_PREFIX}{hop}"
        for hop in (_safe_hop(item) for item in (attempts or []))
        if hop
    ]
    tags.append(
        f"deadline_attempts:{str(len(hop_tags)) if attempts is not None else UNRECORDED_MARK}"
    )
    tags.extend(hop_tags)

    phase_list = phase_tags(budget)
    if phase_list:
        tags.extend(phase_list)
        recorded_ms = float(_tag_value(phase_list, "phase_total_ms:") or 0.0)
        unaccounted_ms = (
            _ms_or_unrecorded(max(0.0, (elapsed_ms or 0.0) - recorded_ms))
            if elapsed_ms is not None
            else None
        )
        tags.append(f"deadline_unaccounted_ms:{unaccounted_ms or UNRECORDED_MARK}")
    else:
        tags.append(f"deadline_phases:{UNRECORDED_MARK}")
        # 没有任何相位记账 ⇒ 走过的时间整段都是未归账的（不是 0，也不是省略）。
        tags.append(f"deadline_unaccounted_ms:{_ms_or_unrecorded(elapsed_ms)}")
    return tags


def deadline_receipt_view(audit_tags: Iterable[str] | None) -> dict[str, str]:
    """回执行提取口：把 deadline 回执标签摊成可 ``**`` 展开的日志字段。

    只在**这张回执确实是预算耗尽**时返回内容，其余一律空 dict——非 deadline 行
    （如 00:53 那类 ``error_kind=server`` 且自带 route_attempts 的行）的既有形状
    一个字节都不变。接线点唯一：根 ``__init__.py::_runtime_tag_values``。

    字段集恒定（``DEADLINE_RECEIPT_FIELDS`` + 逐相位 ``phase_<段>_ms``）：读不到
    的写「未记账」，只有 ``deadline_exceeded:before_llm`` 这一枚既有事实可以推出
    「一条 LLM 尝试都没发过」⇒ 计数 0；``during_llm`` 无从推断时**不许**写 0。
    """
    tags = [str(tag) for tag in (audit_tags or [])]
    is_deadline = any(
        tag == DEADLINE_DIAG_TAG or tag.startswith(DEADLINE_DIAG_PREFIX)
        for tag in tags
    ) or any(
        tag in {"deadline_exceeded:before_llm", "deadline_exceeded:during_llm"}
        or tag == "llm_error:deadline_exceeded"
        for tag in tags
    )
    if not is_deadline:
        return {}

    view: dict[str, str] = {
        "deadline_diag": _tag_value(tags, DEADLINE_DIAG_PREFIX) or "1",
    }

    in_flight = _tag_value(tags, "deadline_in_flight:")
    if not in_flight:
        if "deadline_exceeded:before_llm" in tags:
            in_flight = "before_llm"
        elif "deadline_exceeded:during_llm" in tags:
            in_flight = "during_llm"
    view["deadline_in_flight"] = in_flight or UNRECORDED_MARK

    hops = [tag for tag in tags if tag.startswith(LLM_ROUTE_ATTEMPT_TAG_PREFIX)]
    attempts = _tag_value(tags, "deadline_attempts:")
    if not attempts and hops:
        attempts = str(len(hops))
    if not attempts and "deadline_exceeded:before_llm" in tags:
        attempts = "0"  # 闸前断＝一条都没发过，这是既有事实不是猜测
    view["deadline_attempts"] = attempts or UNRECORDED_MARK

    for key, prefix in (
        ("deadline_remaining_ms", "deadline_remaining_ms:"),
        ("deadline_elapsed_ms", "deadline_elapsed_ms:"),
        ("deadline_unaccounted_ms", "deadline_unaccounted_ms:"),
    ):
        view[key] = _tag_value(tags, prefix) or UNRECORDED_MARK

    phases: dict[str, str] = {}
    for tag in tags:
        if not tag.startswith("phase_") or ":" not in tag:
            continue
        key, _, value = tag.partition(":")
        # 只放行 `phase_<合法段名>_ms:<整数>` 这一形态：回执行是 **kwargs 展开，
        # 键必须是标识符；值只收整数毫秒，别把脏标签当相位贴到行上。
        stage = key.removeprefix("phase_").removesuffix("_ms")
        if not key.isidentifier() or not _PHASE_NAME_RE.match(stage):
            continue
        if value.isdigit():
            phases[key] = value
    view.update(phases)
    if not phases:
        view["deadline_phases"] = _tag_value(tags, "deadline_phases:") or UNRECORDED_MARK
    # 字段全集兜底：`DEADLINE_RECEIPT_FIELDS` 里 declared 的每一枚都必须出现在行上，
    # 读不到就写「未记账」。「这条回执干脆没有这个字段」正是本波要根除的形态——
    # 缺席会被读成「没有」，而事实是「没记到」。
    for field in DEADLINE_RECEIPT_FIELDS:
        view.setdefault(field, UNRECORDED_MARK)
    return view


def apply_request_deadline(
    timeout_seconds: float, deadline_monotonic: float | None
) -> float:
    """发送层超时与请求 deadline 取最小值。

    预算耗尽时不抛异常：回复已生成、LLM 成本已花掉，因总预算到点而丢弃
    消息只会表现为"机器人不回话"（用户侧无任何反馈）。发送是最后一段
    里程，给足传输层自身超时（transport_grace_seconds），超时仍走
    result-unknown 账本兜底。
    """
    if deadline_monotonic is None:
        return timeout_seconds
    deadline = float(deadline_monotonic)
    if not math.isfinite(deadline) or deadline <= 0:
        return timeout_seconds
    remaining = deadline - time.monotonic()
    if remaining <= 0.0:
        return float(timeout_seconds)
    return min(float(timeout_seconds), remaining)
