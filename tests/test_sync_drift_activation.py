"""WP10 自证门：一致性漂移巡检（``domains/ops/sync_drift``）真的活着，且缺省零行为变更。

这个域在 2026-09-21 之前是「代码全在、机器门全绿、却永不运行」——**全仓一份测试都没有**
（``grep -rln sync_drift tests/`` 零命中），所以连 ``registry.py`` 里一个会抛 ``TypeError``
的调用都能安然入库。本件按「活性优先」立六组锁：

① **键面自证**：七枚 ``bot_sync_drift_*`` 真在 ``Config`` 上、类型/缺省正确（根因是
   ``extra=ignore`` 把 ``.env`` 里的未知键静默丢掉 ⇒ 闸恒关）。
② **三道闸行为**：``install()`` 的 disabled / no_super_admins / no_scheduler 与放行。
③ ** surfaces 语义**：键名拼错的面静默不扫（既有语义，本轮首次立锁）。
④ **装配点活性**：从根 ``__init__.py`` 按哨兵**抽出真身文本**、注入假 scheduler 后
   ``exec`` 执行——不是「grep 到就算」的存在性锁（WIRE-SUB 波教训：静态可达性全绿
   照样零投递）。缺省 ⇒ 一个 job 都不注册；开闸 + 有超管 ⇒ 恰好注册一枚。
⑤ **落点纪律**：装配块必须在 campus matcher 之下、且直挂启动装配函数体，不嵌在别人的
   条件分支里；也不引入其他常驻门禁止的字样。
⑥ **三通道投递**：QQ 走 ``build_alert_content_sink``、TG/Mail 走 ``mail_bridge``
   **真身函数**（只喂假 bot，不打桩被测函数本身），不许「注册了但投递是死代码」。
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.ops import sync_drift
from plugins.bot_unified_runtime.domains.ops.sync_drift import (
    registry,
    service,
    tutorial,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

WIRING_BEGIN = "# >>> WP10-SYNC-DRIFT-WIRING BEGIN"
WIRING_END = "# <<< WP10-SYNC-DRIFT-WIRING END"

CAMPUS_MATCHER_TEXT = "campus_record_matcher = on_message("

#: 七键的「类型 + 缺省」契约——与 config.py 逐字对齐；写错一处本文件即红。
SYNC_DRIFT_KEYS: dict[str, tuple[object, object]] = {
    "bot_sync_drift_alert_enabled": (bool, False),
    "bot_sync_drift_surfaces": (list[str], []),
    "bot_sync_drift_interval_minutes": (int, 60),
    "bot_sync_drift_startup_delay_seconds": (int, 65),
    "bot_sync_drift_suppression_seconds": (int, 21600),
    "bot_sync_drift_qq_bot_id": (str, ""),
    "bot_sync_drift_max_evidence_lines": (int, 12),
}


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 替身（只替「外部世界」，被断言的真身函数一律不替）
# ---------------------------------------------------------------------------


class FakeScheduler:
    """只记录 ``add_job`` 的最小 APScheduler 替身。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def add_job(self, func: Any, **kwargs: Any) -> None:
        self.calls.append((func, kwargs))

    @property
    def job_ids(self) -> list[Any]:
        return [kwargs.get("id") for _func, kwargs in self.calls]


class FakeReceipt:
    """``pipeline.handle`` 的返回形态（中央件只读 ``state.value`` 与 ``request_id``）。"""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.state = types.SimpleNamespace(value="queued")


class FakePipeline:
    """QQ 通道替身：记录 ``handle`` 入参，形态对齐真身 ``send_admin_alert_requests``。"""

    def __init__(self) -> None:
        self.handled: list[tuple[Any, str]] = []

    def handle(self, message: Any, capability: Any, *, capability_id: str = "") -> FakeReceipt:
        self.handled.append((message, capability_id))
        return FakeReceipt(getattr(message, "request_id", "req-1"))


class FakeAdapter:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_name(self) -> str:
        return self._name


class FakeTelegramBot:
    def __init__(self, self_id: str = "tg-ops") -> None:
        self.adapter = FakeAdapter("telegram")
        self.self_id = self_id
        self.sent: list[tuple[str, str]] = []

    async def send_to(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeMailBot:
    def __init__(self, self_id: str) -> None:
        self.adapter = FakeAdapter("mail")
        self.self_id = self_id
        self.sent: list[tuple[str, str, str]] = []

    async def send_to(self, recipient: str, body: str, *, subject: str = "") -> None:
        self.sent.append((recipient, body, subject))


def _enabled_config(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "bot_sync_drift_alert_enabled": True,
        "bot_super_admin_user_ids": ["10001"],
    }
    values.update(overrides)
    return Config(**values)


# ---------------------------------------------------------------------------
# ① 键面自证：根因是「键不存在」，那就把「键存在」钉成门
# ---------------------------------------------------------------------------


def test_seven_sync_drift_keys_exist_on_config_with_exact_types() -> None:
    """七键必须真在 ``Config.model_fields`` 上且注解逐一对齐。

    审计定罪根因：巡检读的键在 ``Config`` 上根本不存在，而 ``Config`` 是
    ``extra="ignore"`` ⇒ ``.env`` 填了也被静默丢掉 ⇒ ``alert_enabled`` 恒 False。
    「已修好」这件事以前只活在转述里，这里钉死。
    """
    fields = Config.model_fields
    missing = [name for name in SYNC_DRIFT_KEYS if name not in fields]
    assert not missing, f"config.py 缺键：{missing}"
    for name, (annotation, _default) in SYNC_DRIFT_KEYS.items():
        assert fields[name].annotation == annotation, f"{name} 注解漂移：{fields[name].annotation}"


def test_sync_drift_key_defaults_match_documented_values() -> None:
    """缺省必须是「关」——其余六枚与主会话登记的现值逐字一致。"""
    instance = Config()
    assert instance.bot_sync_drift_alert_enabled is False, "缺省必须关，否则现网白拿一条周期 job"
    assert instance.bot_sync_drift_surfaces == []
    assert instance.bot_sync_drift_interval_minutes == 60
    assert instance.bot_sync_drift_startup_delay_seconds == 65
    assert instance.bot_sync_drift_suppression_seconds == 21600
    assert instance.bot_sync_drift_qq_bot_id == ""
    assert instance.bot_sync_drift_max_evidence_lines == 12


def test_config_extra_ignore_is_the_root_cause_mechanism() -> None:
    """把病根钉成门：``extra=ignore`` 会吞掉 .env 里的未知键。

    若哪天有人把 ``Config`` 改成 ``extra="forbid"``，本例即红——那时键面拼错会在装载期
    炸出来（比现在更好），请连同本注释一起改写判据，别只删断言。
    """
    extra = Config.model_config.get("extra", "ignore")
    assert extra == "ignore", f"Config.extra 已变为 {extra!r}，本门与根因叙述需同步改写"


def test_env_example_declares_the_seven_keys() -> None:
    """样例面必须声明这七键，否则新机器照抄 .env.example 又会回到「恒关」老路。

    （键面归主会话所有，本例只做**只读**自证：漂了就点名，不代改。）
    """
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    declared = {line.split("=", 1)[0].strip().lower() for line in text.splitlines() if "=" in line and not line.lstrip().startswith("#")}
    missing = [f"BOT_{name.upper()}" for name in SYNC_DRIFT_KEYS if name not in declared]
    assert not missing, f".env.example 未声明：{missing}"


# ---------------------------------------------------------------------------
# ② install() 三道闸行为
# ---------------------------------------------------------------------------


def test_install_returns_disabled_and_registers_nothing_by_default() -> None:
    """缺省 Config ⇒ ``{"registered": False, "reason": "disabled"}`` 且 scheduler 零调用。"""
    scheduler = FakeScheduler()
    outcome = service.install(scheduler=scheduler, config=Config(), pipeline=FakePipeline())
    assert outcome == {"registered": False, "reason": "disabled"}
    assert scheduler.calls == [], "disabled 却注册了 job = 现网白拿一条周期任务"


def test_install_requires_super_admins_and_never_guesses_recipients() -> None:
    scheduler = FakeScheduler()
    outcome = service.install(scheduler=scheduler, config=_enabled_config(bot_super_admin_user_ids=[]))
    assert outcome == {"registered": False, "reason": "no_super_admins"}
    assert scheduler.calls == []


def test_install_requires_scheduler() -> None:
    outcome = service.install(scheduler=None, config=_enabled_config())
    assert outcome == {"registered": False, "reason": "no_scheduler"}


def test_install_registers_exactly_one_job_when_gates_pass() -> None:
    scheduler = FakeScheduler()
    outcome = service.install(
        scheduler=scheduler,
        config=_enabled_config(bot_sync_drift_interval_minutes=7, bot_sync_drift_startup_delay_seconds=3),
        pipeline=FakePipeline(),
    )
    assert outcome["registered"] is True
    assert outcome["job_id"] == service.JOB_ID
    assert len(scheduler.calls) == 1
    _func, kwargs = scheduler.calls[0]
    assert kwargs["id"] == service.JOB_ID
    assert kwargs["replace_existing"] is True
    assert kwargs["max_instances"] == 1
    assert kwargs["coalesce"] is True
    assert kwargs["trigger"].interval.seconds == 7 * 60
    assert kwargs["next_run_time"] is not None


def test_install_interval_is_clamped_to_positive() -> None:
    """0/负间隔不能变成「每 0 秒扫一次」的打盘风暴。"""
    scheduler = FakeScheduler()
    service.install(scheduler=scheduler, config=_enabled_config(bot_sync_drift_interval_minutes=0))
    _func, kwargs = scheduler.calls[0]
    assert kwargs["trigger"].interval.seconds >= 60


def test_registered_surfaces_are_all_real_surface_names() -> None:
    """面名清单与登记表同源（install 返回值里的 surfaces 也来自它）。"""
    surfaces = sync_drift.registered_surfaces()
    assert surfaces, "登记表不能为空，否则巡检开了也是空转"
    assert len(surfaces) == len(set(surfaces))
    outcome = service.install(
        scheduler=FakeScheduler(),
        config=_enabled_config(bot_sync_drift_surfaces=[surfaces[0]]),
    )
    assert outcome["surfaces"] == [surfaces[0]]


# ---------------------------------------------------------------------------
# ③ surfaces 键名拼错 ⇒ 静默不扫（既有语义，本轮首次立锁）
# ---------------------------------------------------------------------------


def test_misspelled_surface_is_silently_ignored_not_raised() -> None:
    assert registry.checks_for(["no_such_drift_surface"]) == ()
    assert registry.checks_for(["trigger_words_vs_route_matrix", "typo_here"]) == (
        registry.DRIFT_CHECKS_BY_SURFACE["trigger_words_vs_route_matrix"],
    )


def test_misspelled_surface_scans_nothing_and_alerts_nothing() -> None:
    """拼错键名 ⇒ 扫描集为空 ⇒ 一轮巡检零投递（既不崩也不误报）。"""
    svc = service.SyncDriftService(
        config=_enabled_config(bot_sync_drift_surfaces=["totally_wrong_name"]),
        root=REPO_ROOT,
        qq_sink=lambda _content: pytest.fail("拼错面名却投递了告警"),
    )
    assert _run_async(svc.run_patrol_async()) == []


def test_install_reports_empty_surface_list_for_typo_only_config() -> None:
    scheduler = FakeScheduler()
    outcome = service.install(
        scheduler=scheduler,
        config=_enabled_config(bot_sync_drift_surfaces=["no_such_drift_surface"]),
    )
    assert outcome["registered"] is True, "静默不扫 ≠ 不注册（缺省空表=全扫，写错只丢那一面）"
    assert outcome["surfaces"] == []


def test_unknown_surface_recompute_entry_point_is_honest() -> None:
    """``scan_surface`` 是教程里的复算命令入口：未知面必须点名「未知」而不是崩。"""
    assert "未知漂移面" in service.scan_surface("no_such_drift_surface", root=REPO_ROOT)


# ---------------------------------------------------------------------------
# ④⑤ 根装配点：抽真身文本执行 + 落点纪律
# ---------------------------------------------------------------------------


def _root_lines() -> list[str]:
    return ROOT_INIT.read_text(encoding="utf-8").splitlines()


def _wiring_span() -> tuple[int, int]:
    lines = _root_lines()
    starts = [index for index, line in enumerate(lines) if line.strip().startswith(WIRING_BEGIN)]
    ends = [index for index, line in enumerate(lines) if line.strip().startswith(WIRING_END)]
    assert len(starts) == 1, f"装配哨兵必须恰一处，现={starts}（未接线=本波 RED 证据）"
    assert len(ends) == 1, f"装配收尾哨兵必须恰一处，现={ends}"
    assert ends[0] > starts[0], "哨兵顺序反了"
    return starts[0], ends[0]


def _wiring_block_source() -> str:
    start, end = _wiring_span()
    return textwrap.dedent("\n".join(_root_lines()[start : end + 1]))


def _exec_wiring(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: Any,
    scheduler: FakeScheduler,
    pipeline: Any = None,
    online_bots: Any = None,
) -> dict[str, Any]:
    """在注入的命名空间里执行根文件里的**真实装配文本**。"""
    stub = types.ModuleType("nonebot_plugin_apscheduler")
    stub.scheduler = scheduler
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", stub)
    namespace: dict[str, Any] = {
        "__name__": "plugins.bot_unified_runtime.__init__",
        "config": config,
        "pipeline": pipeline if pipeline is not None else FakePipeline(),
        "_all_online_bots": online_bots if online_bots is not None else dict,
    }
    exec(compile(_wiring_block_source(), "<root-wiring>", "exec"), namespace)  # noqa: S102
    return namespace


def _assembly_function() -> ast.FunctionDef:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    host = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_register_nonebot_handlers"
        ),
        None,
    )
    assert host is not None, "找不到启动装配函数 _register_nonebot_handlers"
    return host


def test_root_wiring_calls_install_with_the_four_promised_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """install() 的调用形状必须与它 docstring 承诺的那一行一致。"""
    captured: dict[str, Any] = {}

    def _spy(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"registered": False, "reason": "disabled"}

    monkeypatch.setattr(sync_drift, "install", _spy)
    scheduler = FakeScheduler()
    bots = {"k": object()}
    _exec_wiring(
        monkeypatch,
        config=_enabled_config(),
        scheduler=scheduler,
        pipeline=FakePipeline(),
        online_bots=lambda: bots,
    )
    assert set(captured) == {"scheduler", "config", "pipeline", "online_bots"}
    assert captured["scheduler"] is scheduler
    assert captured["online_bots"]() == bots


def test_root_wiring_default_registers_no_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """**缺省零行为变更锁**（真身执行）：默认 Config 下不得注册任何 job。

    变异注毒点：摘掉 install() 的 ``bot_sync_drift_alert_enabled`` 判据 ⇒ 本例必红。
    """
    scheduler = FakeScheduler()
    _exec_wiring(monkeypatch, config=Config(), scheduler=scheduler)
    assert scheduler.calls == [], "缺省配置下装配块注册了 job ⇒ 现网白拿周期任务"


def test_root_wiring_registers_no_job_when_disabled_even_with_admins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**装配级零行为变更锁**：有超管但 alert 总闸关 ⇒ 仍然一条 job 都不挂。

    单看 ``Config()`` 会被下一道闸（no_super_admins）兜住，摘掉 enabled 判据也测不出来；
    这条把「有收件人」这个变量固定住，让 enabled 闸单独暴露在本锁下。
    """
    scheduler = FakeScheduler()
    _exec_wiring(
        monkeypatch,
        config=Config(bot_super_admin_user_ids=["10001"]),
        scheduler=scheduler,
    )
    assert scheduler.calls == [], "只关总闸却注册了 job ⇒ enabled 闸被架空"


def test_root_wiring_enabled_registers_the_patrol_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """活性锁：开闸 + 有超管 ⇒ 根文件真身那一行确实把 job 挂上了。"""
    scheduler = FakeScheduler()
    _exec_wiring(monkeypatch, config=_enabled_config(), scheduler=scheduler)
    assert scheduler.job_ids == [service.JOB_ID]


def test_root_wiring_is_fail_open_when_install_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配抛异常只能落日志，绝不炸插件加载（异常不得逃逸出装配块）。"""

    def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("巡检装配自爆")

    monkeypatch.setattr(sync_drift, "install", _boom)
    scheduler = FakeScheduler()
    _exec_wiring(monkeypatch, config=_enabled_config(), scheduler=scheduler)  # 不抛即通过
    assert scheduler.calls == []


def test_root_wiring_survives_missing_apscheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """apscheduler 不可用 ⇒ 不巡检，但也不炸。"""
    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "nonebot_plugin_apscheduler":
            raise ImportError("apscheduler plugin unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "nonebot_plugin_apscheduler", raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocked)
    scheduler = FakeScheduler()
    _exec_wiring(monkeypatch, config=_enabled_config(), scheduler=scheduler)
    assert scheduler.calls == []


def test_root_wiring_is_direct_child_of_assembly_function_body() -> None:
    """落点纪律之二：装配块必须**直挂**函数体，不能嵌在别人的 if/try 分支里。

    否则它会被上文某个域的条件门连带关掉（例如紧急域那串 if），enabled 也白开。
    """
    host = _assembly_function()
    hits = [
        statement
        for statement in host.body
        if "_install_sync_drift_patrol" in ast.dump(statement) and isinstance(statement, (ast.Try, ast.TryStar))
    ]
    assert len(hits) == 1, (
        f"装配块应为函数体的直接语句（恰一处 Try），现命中 {len(hits)} 处 ⇒ 可能被嵌进他人分支"
    )


def test_root_wiring_sits_below_the_live_campus_coordinate() -> None:
    """落点纪律之一：必须在 campus matcher **之下**。

    campus 的登记坐标被 ``tests/test_campus_digest.py`` 按 live 行号实比，在它上方插任意
    一行都会顶漂该坐标、打断别人的常驻门（同 WIRE-B3 落点注释）。
    """
    lines = _root_lines()
    campus = [index for index, line in enumerate(lines) if CAMPUS_MATCHER_TEXT in line]
    assert len(campus) == 1, f"campus matcher 应恰一处，现={campus}"
    assert _wiring_span()[0] > campus[0], (
        f"装配块（行 {_wiring_span()[0] + 1}）落在 campus matcher（行 {campus[0] + 1}）之上，"
        "会顶漂 test_outbound_registry_campus_coordinate_is_live 实比的 live 坐标"
    )


def test_root_wiring_does_not_introduce_banned_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """本波插入不得踩别人常驻门的红线（根文件禁直调中央出站/禁旁路字样）。"""
    block = _wiring_block_source()
    for banned in ("submit_active_push", "send_private_msg", "call_api"):
        assert banned not in block, f"装配块引入了被常驻门点名的 {banned}"
    assert "sync_drift" in block


def test_root_file_still_parses_and_host_runs_after_insertion() -> None:
    """插入后根文件仍是合法 AST（语法级不炸插件加载的最低保障）。"""
    ast.parse(ROOT_INIT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# ⑥ 三通道投递活性（不许「注册了但投递是死代码」）
# ---------------------------------------------------------------------------


def _alert() -> sync_drift.DriftAlert:
    finding = sync_drift.DriftFinding(
        check=registry.DRIFT_CHECKS[0],
        status=sync_drift.DriftFinding.STATUS_DRIFT,
        evidence=("证据一：副本落后一步", "证据二：另一处副本"),
    )
    return sync_drift.build_drift_alert(finding, root=REPO_ROOT, config=Config(), max_evidence_lines=12)


def test_build_service_wires_qq_sink_only_with_pipeline_and_admins() -> None:
    with_sink = service.build_service(config=_enabled_config(), pipeline=FakePipeline())
    assert with_sink.qq_sink is not None, "有 pipeline + 有超管 ⇒ QQ 通道必须接上中央件 sink"
    assert service.build_service(config=_enabled_config(), pipeline=None).qq_sink is None
    no_admins = service.build_service(
        config=_enabled_config(bot_super_admin_user_ids=[]), pipeline=FakePipeline()
    )
    assert no_admins.qq_sink is None


def test_qq_sink_actually_reaches_the_pipeline() -> None:
    """真跑中央件 sink：它必须把超管告警落成 pipeline 可消费的请求（不是空闭包）。"""
    pipeline = FakePipeline()
    svc = service.build_service(config=_enabled_config(), pipeline=pipeline, root=REPO_ROOT)
    assert svc.qq_sink is not None
    svc.dispatch(_alert())
    assert pipeline.handled, "sink 未向 pipeline 投递任何请求 ⇒ QQ 通道是死代码"
    message, capability_id = pipeline.handled[0]
    assert capability_id == "bot.alert"
    assert message.session_id == "private:10001", "告警必须落在超管私聊会话上"
    assert message.adapter == "onebot"


def test_qq_channel_reports_submitted_and_disabled_states() -> None:
    seen: list[Any] = []
    svc = service.SyncDriftService(config=_enabled_config(), root=REPO_ROOT, qq_sink=seen.append)
    assert svc.dispatch(_alert())["qq"] == "submitted"
    assert len(seen) == 1
    assert seen[0].level == registry.DRIFT_CHECKS[0].severity
    bare = service.SyncDriftService(config=_enabled_config(), root=REPO_ROOT, qq_sink=None)
    assert bare.dispatch(_alert())["qq"] == "disabled:no_pipeline"


def test_telegram_channel_delivers_via_real_mail_bridge_path() -> None:
    """TG 支路走 ``mail_bridge.notify_telegram_admins`` 真身（只喂假 bot，不打桩被测函数）。"""
    bot = FakeTelegramBot()
    svc = service.SyncDriftService(
        config=_enabled_config(bot_telegram_admin_user_ids=["777"]),
        root=REPO_ROOT,
        online_bots={"tg": bot},
    )
    assert svc.dispatch(_alert())["telegram"] == "sent:1"
    assert bot.sent and bot.sent[0][0] == "777"
    assert "① 漂移面" in bot.sent[0][1], "TG 正文必须是完整教程，不是标题一句"


def test_telegram_channel_disabled_without_recipients() -> None:
    bot = FakeTelegramBot()
    svc = service.SyncDriftService(
        config=_enabled_config(bot_telegram_admin_user_ids=[]),
        root=REPO_ROOT,
        online_bots={"tg": bot},
    )
    assert svc.dispatch(_alert())["telegram"] == "disabled:no_recipients"
    assert bot.sent == []


def test_mail_channel_delivers_via_real_mail_bridge_path() -> None:
    account = "ops@example.test"
    bot = FakeMailBot(account)
    svc = service.SyncDriftService(
        config=_enabled_config(
            bot_mail_bridge_enabled=True,
            bot_disconnect_notice_mail_account=account,
            bot_disconnect_notice_mail_recipients=["boss@example.test"],
        ),
        root=REPO_ROOT,
        online_bots={"mail": bot},
    )
    assert svc.dispatch(_alert())["mail"] == "sent:1"
    assert bot.sent[0][0] == "boss@example.test"
    assert bot.sent[0][2].startswith("[一致性漂移]")


def test_mail_channel_disabled_when_bridge_off_or_unconfigured() -> None:
    bot = FakeMailBot("ops@example.test")
    svc = service.SyncDriftService(
        config=_enabled_config(
            bot_mail_bridge_enabled=False,
            bot_disconnect_notice_mail_account="ops@example.test",
            bot_disconnect_notice_mail_recipients=["boss@example.test"],
        ),
        root=REPO_ROOT,
        online_bots={"mail": bot},
    )
    assert svc.dispatch(_alert())["mail"] == "disabled:bridge_or_recipients_unconfigured"
    assert bot.sent == []


def test_one_channel_failure_does_not_swallow_the_others() -> None:
    """TG 炸了不能带走 Mail 与 QQ（三通道各自记账）。"""

    class ExplodingTelegram(FakeTelegramBot):
        async def send_to(self, chat_id: str, text: str) -> None:
            raise RuntimeError("TG 掉线")

    account = "ops@example.test"
    mail_bot = FakeMailBot(account)
    seen: list[Any] = []
    svc = service.SyncDriftService(
        config=_enabled_config(
            bot_mail_bridge_enabled=True,
            bot_disconnect_notice_mail_account=account,
            bot_disconnect_notice_mail_recipients=["boss@example.test"],
            bot_telegram_admin_user_ids=["777"],
        ),
        root=REPO_ROOT,
        online_bots={"tg": ExplodingTelegram(), "mail": mail_bot},
        qq_sink=seen.append,
    )
    outcome = svc.dispatch(_alert())
    assert outcome["qq"] == "submitted"
    assert outcome["telegram"].startswith("failed:")
    assert outcome["mail"] == "sent:1"


def test_suppression_window_holds_repeats_but_not_the_first() -> None:
    """面级抑制：同（面, 严重度）窗口内首放行、后续抑制并如实带计数（抑制在巡检层）。"""
    suppression = _make_suppression(3600)
    key = (registry.DRIFT_CHECKS[1].surface, registry.DRIFT_CHECKS[1].severity, "sync_drift")
    assert suppression.allow(key) == (True, 0)
    allowed, count = suppression.allow(key)
    assert allowed is False and count >= 1

    async def _second_round_is_suppressed() -> list[dict[str, Any]]:
        seen: list[Any] = []
        svc = service.SyncDriftService(
            config=_enabled_config(bot_sync_drift_surfaces=[registry.DRIFT_CHECKS[1].surface]),
            root=REPO_ROOT,
            qq_sink=seen.append,
            suppression=_make_suppression(3600),
        )
        svc.suppression.allow(key)  # 先吃掉首轮额度
        results = await svc.run_patrol_async()
        assert all(item.get("status") != "dispatched" for item in results if item.get("surface"))
        assert seen == [], "被抑制的面仍投了出去 = 抑制器形同虚设"
        return results

    _run_async(_second_round_is_suppressed())


def _make_suppression(window_seconds: float) -> Any:
    from plugins.bot_unified_runtime.domains.ops.monitor.alerts import (
        AdminAlertSuppression,
    )

    return AdminAlertSuppression(window_seconds=window_seconds)


# ---------------------------------------------------------------------------
# ⑦ 本域被 mypy 抓出的两处真错的行为回归
# ---------------------------------------------------------------------------


def test_persona_detector_reports_honestly_when_copy_missing(tmp_path: Path) -> None:
    """``registry.py`` 曾给 ``_relative_display`` 多传一参 ⇒ 命中即抛 TypeError。

    修法前：这条分支一命中就抛，整面被压成「检测器异常」；修法后：给出人话「生产人格
    副本不存在」。本例钉住这条路径（只在副本缺失时走，故生产零影响）。
    """
    source_dir = tmp_path / "personas" / "shorekeeper"
    source_dir.mkdir(parents=True)
    (source_dir / "identity.md").write_text("# 源\n", encoding="utf-8")
    config = Config(bot_persona_files=["not/exists/persona_copy.md"])
    evidence = registry.detect_persona_source_vs_runtime_copy(tmp_path, config)
    assert evidence, "副本缺失必须留下证据行"
    assert all(not str(line).startswith("无法核验检测器异常") for line in evidence), evidence
    assert any("生产人格副本不存在" in str(line) for line in evidence), evidence


def test_tutorial_audio_mib_rendering_does_not_raise() -> None:
    """教程取数不能因 ``bot_tts_max_audio_bytes`` 类型问题抛（mypy call-overload 现场）。"""
    steps = registry.DRIFT_CHECKS_BY_SURFACE["tts_spec_numbers_vs_code"].fix_steps(
        REPO_ROOT, ("示例证据",), Config()
    )
    assert steps
    assert any("MiB" in step for step in steps)


# ---------------------------------------------------------------------------
# ⑧ 文档指针自证：域内 docstring 声称的测试文件必须真的存在
# ---------------------------------------------------------------------------


def test_tutorial_body_reuses_registry_command_verbatim() -> None:
    """兑现 tutorial.py 头注一直承诺、却从未存在过的那条锁。

    「教程里的复算命令」必须与 ``DriftCheck.recompute_command`` **逐字同一枚字符串**，
    否则教程与登记表会各说各话（这正是本域要防的那类漂移）。
    """
    check = registry.DRIFT_CHECKS_BY_SURFACE["db_owners_vs_config_dbs"]
    finding = sync_drift.DriftFinding(
        check=check,
        status=sync_drift.DriftFinding.STATUS_DRIFT,
        evidence=("某库未登记",),
    )
    alert = sync_drift.build_drift_alert(finding, root=REPO_ROOT, config=Config())
    assert check.recompute_command in alert.body, "教程正文里的复算命令与登记表不同源"
    assert alert.alert_content.fix_suggestion is not None
    assert check.verification_gate in alert.alert_content.fix_suggestion


def test_domain_docstrings_do_not_point_at_nonexistent_tests() -> None:
    """IALERT 席在 docstring 里引用过一份从未交付的测试件——那是「已完成」的假象。"""
    offenders: list[str] = []
    for module in (service, registry, tutorial, sync_drift):
        source = inspect.getsource(module)
        for index, line in enumerate(source.splitlines(), start=1):
            for name in ("test_sync_drift_alert.py",):
                if name in line:
                    offenders.append(f"{module.__name__}:{index} 引用不存在的 {name}")
    assert not offenders, "；".join(offenders)
