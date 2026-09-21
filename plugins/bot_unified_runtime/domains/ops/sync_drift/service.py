"""一致性漂移巡检：扫描 → 组告警 → 三通道投递超管（IALERT 席）。

三态与三道闸（用户裁定的架构第 1/2/4 条）：

* **运行期周期巡检**，不住 ``tests/``——形态照抄仓内调度器族（装配期门控
  ``scheduler.add_job``，与 ``_register_digest_push_scheduler`` /
  ``_register_reminder_scheduler`` 同款）；缺省 ``bot_sync_drift_alert_enabled=False``
  ⇒ **整链不注册**（零 job、零读盘、零副作用）。
* **收件人只有一个名单**：QQ 超管 ``bot_super_admin_user_ids``；名单为空 ⇒ 不注册，
  绝不猜人（``_daily_assist_targets`` 同纪律）。TG/邮件用的是仓内**既有**运维告警
  渠道配置，本席不新增第二份收件人配置。
* **fail-open**：检测、组包、投递任一环异常只落一行日志，主链路零影响
  （抄 ``alerts.build_alert_content_sink`` 的「failure must not recurse」纪律）。

出站**全部复用中央件**，本席零新发送路径：
QQ → ``alerts.send_admin_alert_requests`` / ``build_alert_content_sink``（管道→SendQueue）；
Telegram → ``mail_bridge.notify_telegram_admins``；Mail → ``mail_bridge.send_mail_from_account``
（后两枚正是 ``domains/ops/monitor/disconnect_notice.py`` 现用的多渠道运维通知面）。
抑制 → ``alerts.AdminAlertSuppression``（面级窗口，缺省 6h）。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .registry import (
    UNVERIFIABLE_PREFIX,
    DriftCheck,
    DriftFinding,
    checks_for,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
JOB_ID = "bot_sync_drift_patrol"

# 守岸人语气外层短句池（铁律 8：去 AI 味、别像模板；技术正文另段保持精确可执行）。
# 只影响第一行，不参与任何判定，也不进卡片。
_DRIFT_OPENERS: tuple[str, ...] = (
    "有几处对不上了，我看了很久，还是得来说一声：{title}",
    "这份账目我又核了一遍，{title}，这次没对上。",
    "{title}——我把复算的活儿都备好了，您照着走就行。",
    "翻到一处旧账没结清：{title}。教程我写在这条里了。",
    "不着急，但这件事得让您知道：{title}。",
    "我把仓里的镜像都对了一遍，{title}，剩下的是改文档的活。",
)


def _opener(title: str) -> str:
    try:
        from plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist import (
            pick_variant,
        )

        return pick_variant("sync_drift_open", _DRIFT_OPENERS, title=title)
    except Exception:  # noqa: BLE001 - 文案池取数失败退回朴素首句，绝不抛给告警链。
        return f"{title}"


@dataclass(frozen=True)
class DriftAlert:
    """一条巡检告警的可投递形态（三通道共享同一份载荷）。"""

    surface: str
    severity: str
    title: str
    body: str
    alert_content: Any  # alerts.AlertContent（QQ 通道中央件入参）

    @property
    def text(self) -> str:
        return self.body


def scan_drift(
    root: Path | None = None,
    config: Any = None,
    checks: Sequence[DriftCheck] | None = None,
) -> list[DriftFinding]:
    """跑一轮登记表巡检；逐面 fail-open（单面异常=记为不可核验，不中断其余面）。

    ``checks`` 的 **None 与空表不是一回事**：``None``=调用方没筛选=扫全部；空表=筛选后
    一个都不剩（例如 ``bot_sync_drift_surfaces`` 里的面名全部拼错）⇒ 扫零面。写成
    ``checks or checks_for()`` 会把后者悄悄放宽成前者，运维把一个名字打错反而收到比
    配置更多的告警（WP10 实测该缺陷：拼错面名 ⇒ 整表全扫并照常投递）。
    """
    base = Path(root) if root is not None else REPO_ROOT
    findings: list[DriftFinding] = []
    selected = checks_for() if checks is None else checks
    for check in selected:
        try:
            evidence = list(check.detector(base, config) or [])
        except Exception as exc:  # noqa: BLE001 - 一个面崩了不能带走整轮巡检。
            evidence = [f"{UNVERIFIABLE_PREFIX}检测器异常 {type(exc).__name__}"]
        if not evidence:
            findings.append(DriftFinding(check=check, status=DriftFinding.STATUS_SYNC, evidence=()))
            continue
        if check.is_verifiable(evidence):
            findings.append(
                DriftFinding(check=check, status=DriftFinding.STATUS_DRIFT, evidence=tuple(evidence))
            )
        else:
            findings.append(
                DriftFinding(check=check, status=DriftFinding.STATUS_UNKNOWN, evidence=tuple(evidence))
            )
    return findings


def drift_findings(findings: Sequence[DriftFinding]) -> list[DriftFinding]:
    return [item for item in findings if item.status == DriftFinding.STATUS_DRIFT]


def build_drift_alert(
    finding: DriftFinding,
    *,
    root: Path | None = None,
    config: Any = None,
    max_evidence_lines: int = 12,
    now: datetime | None = None,
) -> DriftAlert:
    """把一条漂移拼成「细致入微」的教程告警（①-⑦ 逐条落地，见 _render_body）。"""
    base = Path(root) if root is not None else REPO_ROOT
    check = finding.check
    body = _render_body(finding, base, config, max_evidence_lines, now)
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
        AlertContent,
    )

    content = AlertContent(
        title=check.title,
        what_happened=_evidence_block(finding.evidence, max_evidence_lines),
        impact=f"严重度 {check.severity}｜不改的代价：{check.consequence}",
        fix_suggestion=_steps_block(check, base, finding.evidence, config, include_recompute=True),
        location=f"{check.truth_source} → {', '.join(check.copies)}",
        level=check.severity,
    )
    return DriftAlert(surface=check.surface, severity=check.severity, title=check.title, body=body, alert_content=content)


def _evidence_block(evidence: Sequence[str], limit: int) -> str:
    lines = [str(item) for item in evidence if str(item).strip()]
    shown = lines[: max(1, int(limit))]
    tail = f"\n……另 {len(lines) - len(shown)} 条未展开，用下方复算命令看全量。" if len(lines) > len(shown) else ""
    return "\n".join(shown) + tail


def _steps_block(
    check: DriftCheck, root: Path, evidence: Sequence[str], config: Any, *, include_recompute: bool = False
) -> str:
    steps = check.fix_steps(root, evidence, config)
    lines: list[str] = []
    if include_recompute:
        lines.extend(["【复算命令（可直接复制执行）】", check.recompute_command, ""])
    lines.append("【修法步骤】")
    lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    lines.extend(["", "【改完验这个门】", check.verification_gate, "【预期输出】同步/全绿，复算命令回「已同步」。"])
    return "\n".join(lines)


def _render_body(
    finding: DriftFinding,
    root: Path,
    config: Any,
    max_evidence_lines: int,
    now: datetime | None,
) -> str:
    """告警正文：① 面名 ② 真相源+副本逐个列全 ③ 复算命令 ④ 编号修法 ⑤ 严重度与代价 ⑥ 语气外层。"""
    check = finding.check
    moment = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        _opener(check.title),
        f"① 漂移面：{check.surface}——{check.title}",
        f"② 真相源：{check.truth_source}\n   受影响副本（逐个列全）：\n"
        + "\n".join(f"   - {copy}" for copy in check.copies),
        f"③ 复算命令：{check.recompute_command}",
        f"④ 修法步骤：\n{_steps_block(check, root, finding.evidence, config)}",
        f"⑤ 严重度：{check.severity}｜不改会怎样：{check.consequence}",
        f"⑥ 漂移证据：\n{_evidence_block(finding.evidence, max_evidence_lines)}",
        f"⑦ 时间与范围：{moment}｜仓根 {root.name}｜本条由运行期巡检产出，只读、未改任何文件",
    ]
    return "\n".join(parts)


@dataclass
class SyncDriftService:
    """巡检 + 三通道投递的服务壳（装配期由 install() 造，job 回调持有它）。"""

    config: Any
    root: Path
    pipeline: Any = None
    online_bots: Callable[[], Any] | Any = None
    log: Any = None
    qq_sink: Callable[[Any], None] | None = None
    suppression: Any = None
    last_result: dict[str, Any] | None = None

    # -- 通道 ---------------------------------------------------------------

    def _bots(self) -> dict[str, Any]:
        try:
            source = self.online_bots
            bots = source() if callable(source) else (source or {})
            return dict(bots or {})
        except Exception:  # noqa: BLE001 - 在线注册表读不到时按「无在线 bot」处理。
            return {}

    def _qq_admins(self) -> list[str]:
        return [
            str(item).strip()
            for item in (_config_get(self.config, "bot_super_admin_user_ids", []) or [])
            if str(item).strip()
        ]

    def dispatch(self, alert: DriftAlert) -> dict[str, Any]:
        """同步便利口（脚本/离线复核用）：自建临时循环跑一遍异步投递。"""
        return asyncio.run(self.dispatch_async(alert))

    async def dispatch_async(self, alert: DriftAlert) -> dict[str, Any]:
        """三通道同一份载荷；任一通道离线/异常只影响该通道自己的结果，绝不抛出。"""
        outcome: dict[str, Any] = {"surface": alert.surface}
        if self.qq_sink is not None:
            try:
                self.qq_sink(alert.alert_content)
                outcome["qq"] = "submitted"
            except Exception as exc:  # noqa: BLE001 - 单通道失败不带走其余通道。
                outcome["qq"] = f"failed:{type(exc).__name__}"
        else:
            outcome["qq"] = "disabled:no_pipeline"
        try:
            outcome.update(await _deliver_telegram_and_mail(self, alert))
        except Exception as exc:  # noqa: BLE001 - 兜底：异步投递面任何逃逸都吞成一行日志。
            self._warn(f"sync drift async delivery failed: {type(exc).__name__}")
            outcome.setdefault("telegram", f"failed:{type(exc).__name__}")
            outcome.setdefault("mail", f"failed:{type(exc).__name__}")
        for channel in ("qq", "telegram", "mail"):
            self._warn_once(outcome, str(channel))
        return outcome

    def _warn_once(self, outcome: dict[str, Any], channel: str) -> None:
        state = str(outcome.get(channel, ""))
        if state.startswith(("disabled", "failed", "empty")):
            self._warn(f"sync drift {channel} channel not delivered: {state}")

    def _warn(self, message: str) -> None:
        logger = self.log or _nonebot_logger()
        if logger is None:
            return
        try:
            logger.warning(message)
        except Exception:  # noqa: S110, BLE001 - 日志器异常时静默。
            pass

    # -- 一轮巡检 -----------------------------------------------------------

    def run_patrol(self) -> list[dict[str, Any]]:
        """同步便利口（脚本/离线复核用）。"""
        return asyncio.run(self.run_patrol_async())

    async def run_patrol_async(self) -> list[dict[str, Any]]:
        """扫描 → 命中漂移 → 面级抑制 → 三通道投递；整链 fail-open。

        读盘扫描丢 ``asyncio.to_thread``（不阻塞事件循环），投递留在 bot 的循环里
        await 既有适配面（与 ``_register_reminder_scheduler`` 的 async job 同形态）。
        """
        results: list[dict[str, Any]] = []
        try:
            checks = checks_for(_config_get(self.config, "bot_sync_drift_surfaces", []) or [])
            findings = drift_findings(await asyncio.to_thread(scan_drift, self.root, self.config, checks))
        except Exception as exc:  # noqa: BLE001 - 巡检失败只记日志，不影响主链路。
            self._warn(f"sync drift patrol failed: {type(exc).__name__}")
            self.last_result = {"status": "failed", "error": type(exc).__name__}
            return results
        for finding in findings:
            surface = finding.check.surface
            if self.suppression is not None:
                try:
                    allowed, suppressed_count = self.suppression.allow((surface, finding.check.severity, "sync_drift"))
                except Exception:  # noqa: BLE001 - 抑制器坏了照常投递（宁可重复不可漏报）。
                    allowed, suppressed_count = True, 0
                if not allowed:
                    results.append({"surface": surface, "status": "suppressed", "suppressed_count": suppressed_count})
                    continue
            try:
                alert = build_drift_alert(
                    finding,
                    root=self.root,
                    config=self.config,
                    max_evidence_lines=int(_config_get(self.config, "bot_sync_drift_max_evidence_lines", 12) or 12),
                )
            except Exception as exc:  # noqa: BLE001 - 组包失败的面跳过。
                self._warn(f"sync drift alert build failed for {surface}: {type(exc).__name__}")
                results.append({"surface": surface, "status": "build_failed"})
                continue
            results.append({"surface": surface, "status": "dispatched", **await self.dispatch_async(alert)})
        self.last_result = {"status": "ok", "drift": len(results), "surfaces": len(checks)}
        return results


async def _deliver_telegram_and_mail(service: SyncDriftService, alert: DriftAlert) -> dict[str, Any]:
    """Telegram + Mail 两支既有适配面；配置缺失=诚实「该通道未启用」，不猜收件人。"""
    outcome: dict[str, Any] = {}
    config = service.config
    bots = service._bots()
    telegram_ids = [
        str(item).strip()
        for item in (_config_get(config, "bot_telegram_admin_user_ids", []) or [])
        if str(item).strip()
    ]
    if not telegram_ids:
        outcome["telegram"] = "disabled:no_recipients"
    else:
        try:
            from plugins.bot_unified_runtime.mail_bridge import (
                notify_telegram_admins,
            )

            sent = await notify_telegram_admins(bots, telegram_ids, alert.body)
            outcome["telegram"] = f"sent:{sent}" if sent else "disabled:no_online_telegram_bot"
        except Exception as exc:  # noqa: BLE001 - TG 离线不得阻塞邮件与主链路。
            outcome["telegram"] = f"failed:{type(exc).__name__}"
    account = str(_config_get(config, "bot_disconnect_notice_mail_account", "") or "").strip()
    recipients = [
        str(item).strip()
        for item in (_config_get(config, "bot_disconnect_notice_mail_recipients", []) or [])
        if str(item).strip()
    ]
    if not (bool(_config_get(config, "bot_mail_bridge_enabled", False)) and account and recipients):
        outcome["mail"] = "disabled:bridge_or_recipients_unconfigured"
        return outcome
    delivered = 0
    try:
        from plugins.bot_unified_runtime.mail_bridge import (
            send_mail_from_account,
        )

        aliases = _config_get(config, "bot_mail_sender_aliases", {}) or {}
        for recipient in recipients:
            try:
                await send_mail_from_account(
                    bots,
                    account=account,
                    recipient=recipient,
                    subject=f"[一致性漂移] {alert.title}",
                    body=alert.body,
                    aliases=aliases if isinstance(aliases, dict) else None,
                )
                delivered += 1
            except Exception:  # noqa: S112, BLE001 - 单收件人失败继续其余。
                continue
        outcome["mail"] = f"sent:{delivered}" if delivered else "failed:all_recipients"
    except Exception as exc:  # noqa: BLE001 - 邮件面异常不影响其余通道。
        outcome["mail"] = f"failed:{type(exc).__name__}"
    return outcome


def _config_get(config: Any, name: str, default: Any) -> Any:
    value = getattr(config, name, None) if config is not None else None
    return default if value is None else value


def _nonebot_logger() -> Any:
    try:
        from nonebot.log import logger

        return logger
    except Exception:  # noqa: BLE001 - 离线/无 nonebot 环境（测试）下无日志器。
        return None


def build_service(
    *,
    config: Any,
    root: Path | None = None,
    pipeline: Any = None,
    online_bots: Any = None,
    log: Any = None,
) -> SyncDriftService:
    """造服务壳：QQ sink 与面级抑制器都复用 alerts 中央件的现成工厂。"""
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
        AdminAlertSuppression,
        build_alert_content_sink,
    )

    admins = [
        str(item).strip()
        for item in (_config_get(config, "bot_super_admin_user_ids", []) or [])
        if str(item).strip()
    ]
    sink = None
    if pipeline is not None and admins:
        sink = build_alert_content_sink(
            pipeline,
            admins,
            qq_bot_id=str(_config_get(config, "bot_sync_drift_qq_bot_id", "") or "queued-onebot"),
            window_seconds=float(_config_get(config, "bot_sync_drift_suppression_seconds", 21600) or 21600),
            log=log or _nonebot_logger(),
        )
    return SyncDriftService(
        config=config,
        root=Path(root) if root is not None else REPO_ROOT,
        pipeline=pipeline,
        online_bots=online_bots,
        log=log,
        qq_sink=sink,
        suppression=AdminAlertSuppression(
            window_seconds=float(_config_get(config, "bot_sync_drift_suppression_seconds", 21600) or 21600)
        ),
    )


def install(
    *,
    scheduler: Any,
    config: Any,
    pipeline: Any = None,
    online_bots: Any = None,
    log: Any = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """装配入口：三道闸任一不过 ⇒ **不注册任何 job**，返回 skipped 原因。

    根 ``__init__.py`` 属他会话在飞区，本函数是留给用户裁决的那一行接线：
    ``install(scheduler=scheduler, config=config, pipeline=pipeline, online_bots=_all_online_bots)``
    """
    if not bool(_config_get(config, "bot_sync_drift_alert_enabled", False)):
        return {"registered": False, "reason": "disabled"}
    admins = [
        str(item).strip()
        for item in (_config_get(config, "bot_super_admin_user_ids", []) or [])
        if str(item).strip()
    ]
    if not admins:
        return {"registered": False, "reason": "no_super_admins"}
    if scheduler is None:
        return {"registered": False, "reason": "no_scheduler"}
    service = build_service(config=config, root=root, pipeline=pipeline, online_bots=online_bots, log=log)

    async def _patrol_job() -> None:
        await service.run_patrol_async()

    interval_minutes = max(1, int(_config_get(config, "bot_sync_drift_interval_minutes", 60) or 60))
    delay = max(0, int(_config_get(config, "bot_sync_drift_startup_delay_seconds", 65) or 65))
    try:
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception:  # noqa: BLE001 - apscheduler 缺失不崩装配（与 today_history 同款）
        return {"registered": False, "reason": "apscheduler_unavailable"}
    scheduler.add_job(
        _patrol_job,
        trigger=IntervalTrigger(seconds=interval_minutes * 60),
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=interval_minutes * 60,
        next_run_time=datetime.now(UTC) + timedelta(seconds=delay),
    )
    return {
        "registered": True,
        "job_id": JOB_ID,
        "interval_minutes": interval_minutes,
        "startup_delay_seconds": delay,
        "surfaces": [check.surface for check in checks_for(_config_get(config, "bot_sync_drift_surfaces", []) or [])],
    }


def scan_surface(surface: str, root: Path | None = None, config: Any = None) -> str:
    """登记表中单面复算的**可复制入口**（教程里的复算命令就调它）。

    离线可用：不依赖 nonebot；能读到 ``scripts/load_runtime_config`` 就按生产配置判，
    读不到退回 ``Config`` 代码默认并在输出里如实标注（不谎报、不猜）。
    """
    base = Path(root) if root is not None else REPO_ROOT
    check = checks_for([surface])
    if not check:
        return f"未知漂移面：{surface}（登记表现有面：{', '.join(sorted(_known_surfaces()))}）"
    config_obj, note = _load_config_for_recompute()
    findings = scan_drift(base, config_obj, check)
    if not findings:
        return "已同步"
    finding = findings[0]
    if finding.status == DriftFinding.STATUS_UNKNOWN:
        return f"无法核验：{'; '.join(finding.evidence)}{note}"
    return (
        f"漂移 {len(finding.evidence)} 处：{_evidence_block(finding.evidence, 20)}"
        f"\n修法：见告警正文或 registry.DriftCheck.fix_steps{note}"
    )


def _load_config_for_recompute() -> tuple[Any, str]:
    try:
        from scripts.load_runtime_config import load_runtime_config

        return load_runtime_config(), ""
    except Exception:  # noqa: BLE001 - 离线兜底：脚本包不可用时退回代码默认，属预期降级。
        # 原先是 `except: pass`（S110）——降级本身正确，但一声不响会让人以为
        # 复算读的是生产 .env。留一行 debug 把口径写明，控制流一字不变。
        logger = _nonebot_logger()
        if logger is not None:
            logger.debug("sync drift 复算取不到 load_runtime_config，退回 config.py 代码默认口径")
    try:
        from plugins.bot_unified_runtime.config import Config

        return Config(), "（注：按 config.py 代码默认复核，未读 .env）"
    except Exception:  # noqa: BLE001 - Config 本身装不起来=无法核验
        return None, ""


def _known_surfaces() -> set[str]:
    return {check.surface for check in checks_for()}


def registered_surfaces() -> list[str]:
    return [check.surface for check in checks_for()]


__all__ = [
    "JOB_ID",
    "REPO_ROOT",
    "DriftAlert",
    "SyncDriftService",
    "build_drift_alert",
    "build_service",
    "checks_for",
    "drift_findings",
    "install",
    "registered_surfaces",
    "scan_drift",
    "scan_surface",
]
