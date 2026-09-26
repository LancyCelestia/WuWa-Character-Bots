#!/usr/bin/env python
"""出站闸「开闸会发生什么」只读探针（席位 S222）。

一句话：它**绝不开闸、绝不写任何文件、绝不改任何配置**，只做一件事——把「把
`bot_outbound_gate_enabled` 翻成 True 之后」的三件后果**现算**成人话，并给一个退出码：

1. **会不会丢消息** —— 逐族把现役主动投递的幂等键按生产拼法拼出来，走一遍中央出口
   的洗段（`dedupe.py:wash_active_push_key`）再过一遍闸真正用的那把形门谓词，数「洗完
   仍会被判 `skip`（静默丢）」的条数。
2. **会被限到几条** —— 报 60s / 3600s 双滑窗上限、连击风暴阈值，以及「此刻是否落在
   安静窗内、窗尾到几点」。
3. **键形是否合法** —— 报段合法集正则、逐段体检真实目标 id（哪几枚是构造侧脏、上线
   会打 WARNING 并依赖出口洗段）。

真值纪律（席位硬规矩）：
- 「线上今天闸关着 ⇒ 顺延/限流/键形/闸审计都不生效」这一条**照实写进结论**，不许叙述成已执法。
- 判据只**调用** `domains/emergency_info/service/dedupe.py` 的公开谓词（键形唯一真身），
  不在本件重定义任何正则；安静窗判定只是**镜像** `outbound_gate.OutboundGate._quiet_verdict`
  的读法（本件不是执法点，权威结论永远是闸的 `decide`）。
- 退出码只在**判得出**时给结论：核心谓词导入失败 ⇒ 退出码 2（不可判），绝不落 0/3 蒙人。
- **不读 `enabled` 来决定要不要分析**：无论闸今天开没开，本件一律按「开闸态」模拟。
  这是刻意的——否则会犯「关着就跳过检查、报一切安好」的代理指标型假绿。
- 自带**正对照（positive control）**：拿两枚已知脏键喂进分析，验证「洗完过形 / 不洗
  就不过形」两半都成立。正对照跑不通 ⇒ 说明探针自身失灵，退出码 3，绝不让它「绿着漏」。

用法::

    python scripts/probe_outbound_gate_opening.py            # 人话结论
    python scripts/probe_outbound_gate_opening.py --json     # 机器可读
    python scripts/probe_outbound_gate_opening.py --selftest # 只跑正对照（CI 用）

退出码：0 干净 / 4 咨询（有构造侧脏键或漏报 namespace，但不真丢）/ 3 硬警（洗完仍会被丢
或正对照失灵＝出口洗段失效）/ 2 不可判（核心件导不进来）。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# 唯一规则真身（只读调用，禁复制判据）——键形住在 emergency_info/service/dedupe.py
# ---------------------------------------------------------------------------
_PREDICATE_IMPORT_ERROR: str | None = None
try:
    from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
        EMERGENCY_DEDUPE_PREFIX,
        active_push_key_shape_ok,
        is_emergency_dedupe_key,
        is_legal_segment,
        wash_active_push_key,
    )
except Exception as exc:  # noqa: BLE001 - 环境缺依赖时的诚实降级（见 _PREDICATE_IMPORT_ERROR）
    _PREDICATE_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO_ROOT / ".env"

# 现役六族（简报口径：提醒 / 群摘要 / 日常助理 / cookie 到期 / 紧急信息 / 等待回执）。
# 这里只放**能离线坐实**的族（键构造式镜像生产拼法）；机器生 id 或构造即抛的族在
# verdict 里以「结构免动」如实标注，不谎报为「已验通过」。
_DAILY = "daily"
_ONCE = "once"

EXIT_CLEAN = 0
EXIT_ADVISORY = 4
EXIT_HARD_ALARM = 3
EXIT_UNDECIDABLE = 2


# =========================================================================
# 闸侧参数读取（缺省值与 config.py:307-312 / QuietHoursSettings 逐字对齐；
# 能读到生产 Config 就读 Config，读不到退回缺省，并在结论里点名用的是缺省）
# =========================================================================
@dataclass
class GateNumbers:
    enabled_today: bool = False
    enabled_from_config: bool = False
    env_sets_enabled: bool = False
    quiet_defer_enabled: bool = True
    urgent_severities: tuple[str, ...] = ("P0", "P1")
    max_per_target_per_minute: int = 2
    max_per_target_per_hour: int = 6
    quiet_enabled: bool = False
    quiet_start: str = "00:00"
    quiet_end: str = "06:00"
    quiet_timezone: str = "Asia/Hong_Kong"
    quiet_session_types: tuple[str, ...] = ("group",)
    config_available: bool = False
    notes: list[str] = field(default_factory=list)


def _load_prod_config() -> Any:
    """用生产同构只读入口拿真实 Config（读 .env，不向 os.environ 注入、零进程副作用）。

    注意：`Config` 是裸 pydantic BaseModel（config.py:76），**不自动读 .env**——
    `Config()` 只给代码缺省。真实目标名单（如 .env 的 BOT_DAILY_ASSIST_PUSH_USER_IDS）
    必须走仓库唯一只读装载口 `scripts.load_runtime_config.load_runtime_config` 才看得见。
    """
    from scripts.load_runtime_config import load_runtime_config  # type: ignore

    return load_runtime_config(required=False)


def load_gate_numbers() -> GateNumbers:
    """读取闸与安静窗的有效数值（缺省=关闭；读到生产 Config 就按生产值覆盖）。"""
    g = GateNumbers()
    g.env_sets_enabled = _env_sets_gate_enabled()
    try:
        cfg: Any = _load_prod_config()
    except Exception as exc:  # noqa: BLE001 - Config 读不到不致命：退回缺省 + 点名
        g.notes.append(f"读生产 Config 失败，用代码缺省（关闭态）：{type(exc).__name__}: {exc}")
        return g
    g.config_available = True
    g.enabled_from_config = bool(getattr(cfg, "bot_outbound_gate_enabled", False))
    g.enabled_today = g.enabled_from_config or g.env_sets_enabled
    g.quiet_defer_enabled = bool(getattr(cfg, "bot_outbound_gate_quiet_defer_enabled", True))
    g.urgent_severities = tuple(
        str(s) for s in getattr(cfg, "bot_outbound_gate_urgent_severities", ["P0", "P1"])
    )
    g.max_per_target_per_minute = int(
        getattr(cfg, "bot_outbound_gate_max_per_target_per_minute", 2)
    )
    g.max_per_target_per_hour = int(getattr(cfg, "bot_outbound_gate_max_per_target_per_hour", 6))
    # 安静窗：闸复用 bot_quiet_hours_*（唯一事实源 policy/quiet_hours）
    g.quiet_enabled = bool(getattr(cfg, "bot_quiet_hours_enabled", True))
    g.quiet_start = str(getattr(cfg, "bot_quiet_hours_start", "00:00"))
    g.quiet_end = str(getattr(cfg, "bot_quiet_hours_end", "06:00"))
    g.quiet_timezone = str(getattr(cfg, "bot_quiet_hours_timezone", "Asia/Hong_Kong"))
    g.quiet_session_types = tuple(
        str(s) for s in getattr(cfg, "bot_quiet_hours_session_types", ["group"])
    )
    return g


def _env_sets_gate_enabled() -> bool:
    """生产 .env 里 `BOT_OUTBOUND_GATE_ENABLED=true` 是否在场（只读，不打印其它行）。"""
    try:
        text = _ENV_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip().upper() == "BOT_OUTBOUND_GATE_ENABLED":
            return value.strip().strip("'\"").lower() in {"1", "true", "yes", "on"}
    return False


# =========================================================================
# 键形判定（只调用中央谓词，不重定义）
# =========================================================================
def _shape_ok(key: str, *, namespace: str, family: str) -> bool:
    require_date = family == _DAILY
    if namespace == EMERGENCY_DEDUPE_PREFIX:
        return is_emergency_dedupe_key(key, require_date_key=require_date)
    return active_push_key_shape_ok(
        key, namespace=namespace, require_date_key=require_date
    )


def _first_illegal_segment(key: str) -> str | None:
    for segment in str(key).split(":"):
        if not is_legal_segment(segment):
            return segment
    return None


# ---- 键构造式镜像（逐字照抄 __init__.py / push.py 的 f-string 拼法）----
def digest_push_key(group_id: str, today: str) -> str:
    return f"digest_push:{group_id}:{today}"


def daily_assist_key(tag: str, user_id: str, today: str) -> str:
    return f"daily_assist:{tag}:{user_id}:{today}"


def cookie_expiry_key(admin_id: str, today: str) -> str:
    return f"cookie-expiry:{admin_id}:{today}"


def reminder_key(reminder_id: str) -> str:
    return f"reminder:{reminder_id}"


def ack_key(session_id: str, origin: str, digest: str) -> str:
    # 真身在 progress_ack.py 里对 session_id/origin 先过 ack_key_segment（委托中央洗段）
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.progress_ack import (
        ACK_DEDUPE_NAMESPACE,
        ack_key_segment,
    )

    return (
        f"{ACK_DEDUPE_NAMESPACE}:chat:"
        f"{ack_key_segment(session_id)}:{ack_key_segment(origin)}:{digest}"
    )


@dataclass
class FamilyProbe:
    family: str
    namespace: str
    verifiable: bool  # False = 离线拿不到真实目标 id（机生/构造即抛），如实标「未证」
    raw_key: str = ""
    would_drop: bool = False  # 经出口洗段后仍被闸 skip（＝真会丢）
    construction_dirty: bool = False  # 构造侧脏（依赖出口洗段 + 上线打 WARNING）
    namespace_matches_first_segment: bool = True


def probe_family_raw(
    *, family: str, namespace: str, raw_key: str, verifiable: bool = True
) -> FamilyProbe:
    """对一枚具体键跑「开闸态会不会丢」：先按出口洗一次，再过闸真正用的形门。"""
    washed = wash_active_push_key(raw_key)
    still_fails = not _shape_ok(washed, namespace=namespace, family=_family_from_ns(family))
    dirty_at_build = _first_illegal_segment(raw_key) is not None
    first_seg = raw_key.split(":", 1)[0]
    ns_ok = first_seg == namespace
    return FamilyProbe(
        family=family,
        namespace=namespace,
        verifiable=verifiable,
        raw_key=raw_key,
        would_drop=still_fails,
        construction_dirty=dirty_at_build,
        namespace_matches_first_segment=ns_ok,
    )


def _family_from_ns(family: str) -> str:
    # 现役 daily 族：digest_push / daily_assist / cookie-expiry / emg；once 族：reminder / ack。
    return _DAILY if family in {"digest_push", "daily_assist", "cookie-expiry", "emg", "emergency"} else _ONCE


# =========================================================================
# 安静窗镜像（照抄 outbound_gate._quiet_verdict 的窗口比较，仅只读预测）
# =========================================================================
def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("quiet hours time must use HH:MM")
    return time(int(parts[0]), int(parts[1]))


def quiet_window_state(g: GateNumbers, now: datetime) -> dict[str, Any]:
    """返回「此刻是否落在安静窗、窗尾到几点（UTC）」，镜像闸的第一道门。"""
    out: dict[str, Any] = {
        "enabled": bool(g.quiet_enabled and g.quiet_defer_enabled),
        "in_window_now": False,
        "window": f"{g.quiet_start}-{g.quiet_end}",
        "timezone": g.quiet_timezone,
        "session_types": list(g.quiet_session_types),
        "defer_until_utc": None,
        "note": "",
    }
    if not out["enabled"]:
        out["note"] = "安静窗未启用（或 quiet_defer 关闭）⇒ 开闸后不会因静默窗顺延"
        return out
    try:
        zone = ZoneInfo(g.quiet_timezone)
        start = _parse_hhmm(g.quiet_start)
        end = _parse_hhmm(g.quiet_end)
    except Exception as exc:  # noqa: BLE001 - 镜像闸：读不通=按不在窗内，不误拦
        out["note"] = f"安静窗参数读不通（按不在窗内，不误拦）：{type(exc).__name__}"
        return out
    local_now = now.astimezone(zone)
    lt = local_now.time()
    if start == end:
        in_window = True
    elif start < end:
        in_window = start <= lt < end
    else:
        in_window = lt >= start or lt < end
    out["in_window_now"] = in_window
    if in_window:
        quiet_end_local = local_now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        if quiet_end_local <= local_now:
            quiet_end_local += timedelta(days=1)
        out["defer_until_utc"] = quiet_end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        out["note"] = (
            f"此刻在安静窗内（{g.quiet_timezone} 本地 {local_now:%H:%M}）："
            "开闸后**非紧急、且目标是窗内会话类型**的主动投递会顺延到 "
            f"{out['defer_until_utc']}；P0/P1 穿窗、其余会话类型不受静默窗影响。"
        )
    else:
        out["note"] = f"此刻不在安静窗内（{g.quiet_timezone} 本地 {local_now:%H:%M}）"
    return out


# =========================================================================
# 总分析
# =========================================================================
@dataclass
class OpenStateVerdict:
    gate: GateNumbers
    quiet: dict[str, Any]
    now_utc: str
    families: list[FamilyProbe]
    positive_control_ok: bool
    positive_control_detail: str
    undecidable: bool = False
    undecidable_reason: str = ""

    @property
    def would_drop_count(self) -> int:
        return sum(1 for f in self.families if f.would_drop)

    @property
    def construction_dirty_count(self) -> int:
        return sum(1 for f in self.families if f.construction_dirty)

    @property
    def namespace_undeclared_count(self) -> int:
        return sum(
            1
            for f in self.families
            if f.verifiable and not f.namespace_matches_first_segment
        )

    @property
    def unverified_families(self) -> list[str]:
        return [f.family for f in self.families if not f.verifiable]

    def exit_code(self) -> int:
        if self.undecidable:
            return EXIT_UNDECIDABLE
        if self.would_drop_count > 0 or not self.positive_control_ok:
            return EXIT_HARD_ALARM
        if self.construction_dirty_count > 0 or self.namespace_undeclared_count > 0:
            return EXIT_ADVISORY
        return EXIT_CLEAN


def run_positive_control(g: GateNumbers) -> tuple[bool, str]:
    """正对照：一枚已知构造脏的键，洗完必过形；不洗必不过形。两半缺一即探针失灵。"""
    dirty = digest_push_key("湘潭示例群", "2026-09-24")  # 中文段 → 构造侧脏
    washed = wash_active_push_key(dirty)
    dirty_at_build = _first_illegal_segment(dirty) is not None
    passes_after_wash = _shape_ok(washed, namespace="digest_push", family=_DAILY)
    fails_without_wash = not _shape_ok(dirty, namespace="digest_push", family=_DAILY)
    ok = dirty_at_build and passes_after_wash and fails_without_wash
    detail = (
        f"构造脏={dirty_at_build} 洗完过形={passes_after_wash} "
        f"不洗不过形={fails_without_wash}（洗后键={washed!r}）"
    )
    return ok, detail


def _real_targets_from_config() -> tuple[list[str], list[str], list[str]]:
    """读现役真实目标名单（群摘要白名单 / 日常助理收件人 / cookie 管理员），拿不到给空。"""
    digest_ids: list[str] = []
    assist_ids: list[str] = []
    admin_ids: list[str] = []
    with contextlib.suppress(Exception):  # 生产 Config 读不到时按"无目标"处理，主分析另有正对照兜底
        cfg: Any = _load_prod_config()
        if str(getattr(cfg, "bot_group_digest_list_mode", "") or "").strip().lower() == "whitelist":
            digest_ids = [str(x) for x in (getattr(cfg, "bot_group_digest_whitelist", []) or [])]
        if bool(getattr(cfg, "bot_daily_assist_enabled", True)):
            assist_ids = [str(x) for x in (getattr(cfg, "bot_daily_assist_push_user_ids", []) or [])]
    return digest_ids, assist_ids, admin_ids


def assess_open_state(
    g: GateNumbers,
    *,
    now: datetime | None = None,
    digest_ids: list[str] | None = None,
    assist_ids: list[str] | None = None,
    today: str | None = None,
) -> OpenStateVerdict:
    current = now or datetime.now(timezone.utc)
    if _PREDICATE_IMPORT_ERROR is not None:
        # 核心谓词导不进来 ⇒ 无法回答任何"会不会丢"的问题，只能落不可判，绝不蒙 0。
        return OpenStateVerdict(
            gate=g,
            quiet={"enabled": False, "note": "不可判（谓词未导入）", "in_window_now": False,
                   "window": "", "timezone": "", "session_types": [], "defer_until_utc": None},
            now_utc=current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            families=[],
            positive_control_ok=False,
            positive_control_detail="未执行（谓词未导入）",
            undecidable=True,
            undecidable_reason=_PREDICATE_IMPORT_ERROR,
        )
    date_key = today or current.astimezone().date().isoformat()
    families: list[FamilyProbe] = []

    if digest_ids is None or assist_ids is None:
        cfg_digest, cfg_assist, _ = _real_targets_from_config()
        digest_ids = digest_ids if digest_ids is not None else cfg_digest
        assist_ids = assist_ids if assist_ids is not None else cfg_assist

    # —— 能离线坐实的两族：拿真实目标逐个体检；没目标就放一枚代表值证明机制 ——
    if digest_ids:
        for gid in digest_ids:
            families.append(
                probe_family_raw(
                    family="digest_push", namespace="digest_push",
                    raw_key=digest_push_key(gid, date_key),
                )
            )
    else:
        families.append(
            probe_family_raw(
                family="digest_push", namespace="digest_push",
                raw_key=digest_push_key("000000000", date_key), verifiable=False,
            )
        )
    if assist_ids:
        for uid in assist_ids:
            for tag in ("morning", "evening"):
                families.append(
                    probe_family_raw(
                        family="daily_assist", namespace="daily_assist",
                        raw_key=daily_assist_key(tag, uid, date_key),
                    )
                )
    else:
        families.append(
            probe_family_raw(
                family="daily_assist", namespace="daily_assist",
                raw_key=daily_assist_key("morning", "000000000", date_key), verifiable=False,
            )
        )

    # —— 结构免动三族：机生 id / 构造即校验，离线拿不到真实目标，如实标未证 ——
    families.append(
        probe_family_raw(
            family="reminder", namespace="reminder",
            raw_key=reminder_key("a1b2c3d4e5f6"), verifiable=False,
        )
    )
    families.append(
        probe_family_raw(
            family="cookie-expiry", namespace="cookie-expiry",
            raw_key=cookie_expiry_key("000000000", date_key), verifiable=False,
        )
    )
    families.append(
        probe_family_raw(
            family="ack", namespace="ack",
            raw_key=ack_key("group_000_000", "1000000000000", "abcd1234"), verifiable=False,
        )
    )
    families.append(
        probe_family_raw(
            family="emergency", namespace=EMERGENCY_DEDUPE_PREFIX,
            raw_key=f"{EMERGENCY_DEDUPE_PREFIX}:qq:A1-0001:000000000:{date_key}", verifiable=False,
        )
    )

    control_ok, control_detail = run_positive_control(g)
    quiet = quiet_window_state(g, current)

    undecidable = _PREDICATE_IMPORT_ERROR is not None
    return OpenStateVerdict(
        gate=g,
        quiet=quiet,
        now_utc=current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        families=families,
        positive_control_ok=control_ok,
        positive_control_detail=control_detail,
        undecidable=undecidable,
        undecidable_reason=_PREDICATE_IMPORT_ERROR or "",
    )


# =========================================================================
# 人话渲染
# =========================================================================
def render_human(v: OpenStateVerdict) -> str:
    lines: list[str] = []
    lines.append("=" * 68)
    lines.append("出站闸「打开会发生什么」只读探针（S222）——本件不开闸、不改任何配置")
    lines.append(f"分析时刻（UTC）：{v.now_utc}")
    if v.undecidable:
        lines.append(f"⚠ 不可判：核心键形谓词导不进来（{v.undecidable_reason}）")
        lines.append("  ⇒ 无法回答「会不会丢」，退出码 2。请检查运行环境与 PYTHONPATH。")
        lines.append("=" * 68)
        return "\n".join(lines)

    g = v.gate
    # §0 今天关到什么程度（必须照写）
    lines.append("")
    lines.append("〔今天真实状态〕")
    state = "开" if g.enabled_today else "关"
    lines.append(f"  出站闸：{state}（Config.bot_outbound_gate_enabled={g.enabled_from_config}，"
                 f".env 设 enabled={g.env_sets_enabled}）")
    lines.append("  ⇒ 关闭态下闸直接 passthrough 裸 submit：**顺延 / 每主体限流 / 键形核验 / 闸审计"
                 "线上今天都不生效**。本探针以下全部是「若翻成开」的预测，不代表现状已执法。")
    if g.notes:
        for n in g.notes:
            lines.append(f"  · 备注：{n}")

    # §1 开闸后开始生效的数值
    lines.append("")
    lines.append("〔开闸后会开始生效的数值〕")
    lines.append(f"  每主体 60 秒窗上限：{g.max_per_target_per_minute} 条（0=该窗不生效）")
    lines.append(f"  每主体 3600 秒窗上限：{g.max_per_target_per_hour} 条（0=该窗不生效）")
    lines.append("  连击风暴：同一主体连续被顺延 3 次 ⇒ 报一次 outbound_gate_storm")
    lines.append("  顺延用队列原生 deliver_after：分钟窗 +60s、小时窗 +3600s、安静窗顺延到窗尾")
    lines.append("  ⚠ 这六枚 bot_outbound_gate_* 键不在运行时热改名单里 ⇒ 改数值/开闸＝改 .env 后重启")
    lines.append("  （安静窗那组 bot_quiet_hours_* 在热改名单里，可在开闸后单独调，但开闸本身要重启）")

    # 安静窗
    q = v.quiet
    lines.append("")
    lines.append("〔安静窗（开闸后第一道门会生效）〕")
    lines.append(f"  启用={q['enabled']}  窗 {q['window']} 时区 {q['timezone']} 生效会话 {q['session_types']}")
    lines.append(f"  穿窗等级：{list(g.urgent_severities)}")
    lines.append(f"  {q['note']}")

    # §3 三洞复核 + §2 命中面
    lines.append("")
    lines.append("〔六族主动投递：开闸态逐族体检〕")
    for f in v.families:
        tag = "结构免动·未证" if not f.verifiable else ("构造侧脏(依赖出口洗段)" if f.construction_dirty else "构造侧干净")
        if not f.verifiable:
            drop = "未证"
        else:
            drop = "会丢" if f.would_drop else "不丢"
        lines.append(f"  - {f.family:<14} ns={f.namespace:<14} {drop:<3} [{tag}]")
    lines.append("")
    lines.append(f"  洗完仍会被闸 skip（真丢消息）的条数：**{v.would_drop_count}**")
    lines.append(f"  构造侧脏、上线会触发一行 WARNING 的条数：{v.construction_dirty_count}")
    lines.append(f"  namespace 未申报/与首段不符（会回落 emg 被丢）：{v.namespace_undeclared_count}")
    lines.append(f"  离线拿不到真实目标、只能标「未证」的族：{v.unverified_families}")

    # 正对照（防探针自己假绿）
    lines.append("")
    lines.append("〔探针自检（正对照，证明这把尺有牙）〕")
    lines.append(f"  正对照通过={v.positive_control_ok}  {v.positive_control_detail}")
    if not v.positive_control_ok:
        lines.append("  ⚠ 正对照失灵＝出口洗段可能没覆盖 / 谓词漂移 ⇒ 结论不可信，退出码 3")

    lines.append("")
    code = v.exit_code()
    meaning = {
        EXIT_CLEAN: "0 干净：键形经出口规范后不丢（仍不代表闸已执法——今天它关着）",
        EXIT_ADVISORY: "4 咨询：有构造侧脏键或漏报 namespace，但都不真丢；上线会打 WARNING",
        EXIT_HARD_ALARM: "3 硬警：有键洗完仍会被丢 / 或探针自检失灵——开闸前必须修",
        EXIT_UNDECIDABLE: "2 不可判：核心件导不进来",
    }[code]
    lines.append(f"〔结论〕退出码 {code} —— {meaning}")
    lines.append("〔再次声明〕以上为「若开闸」的离线预测；真实执法须提权重启并置 enabled=true 后才成立。")
    lines.append("=" * 68)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="出站闸开闸只读探针（不开闸、不改配置）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--selftest", action="store_true", help="只跑正对照并打印结果")
    args = parser.parse_args(argv)

    g = load_gate_numbers()
    v = assess_open_state(g)

    if args.selftest:
        print(f"positive_control_ok={v.positive_control_ok}  {v.positive_control_detail}")
        return EXIT_CLEAN if v.positive_control_ok else EXIT_HARD_ALARM

    if args.json:
        payload = asdict(v)
        payload["exit_code"] = v.exit_code()
        payload["would_drop_count"] = v.would_drop_count
        payload["construction_dirty_count"] = v.construction_dirty_count
        payload["namespace_undeclared_count"] = v.namespace_undeclared_count
        payload["unverified_families"] = v.unverified_families
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_human(v))
    return v.exit_code()


if __name__ == "__main__":
    sys.exit(main())
