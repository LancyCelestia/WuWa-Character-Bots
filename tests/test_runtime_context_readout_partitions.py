"""运行时读出面分区回归（goal18 第 5/10 项：时间/系统自述/宿主机三块接线）。

三族锁各钉一件会真发生的事：

1. **【当前时间】首行字节不变 + 追加行同源**：追加的时区/偏移/校时/历法明细
   必须与 ``character/temporal.time_partition_extras``、
   ``multi_calendar.rich_calendar_lines`` 现算一致——测试不抄第二份文案，
   比对"分区里出现的行 == 取数口给的行"，任何一侧漂了就红。
2. **空分区不渲染**：【系统自述】【宿主机状态】传空串 ⇒ 标签一个字都不出现；
   传非空 ⇒ 恰好出现一次。
3. **超管门是角色判据不是新键**：``_super_admin_host_partition_text`` 只认
   ``message.sender_roles``；非超管恒空串；读数行过
   ``redact_local_secrets``（盘符路径进不了 prompt）。

⑥（S24 复核席，2026-09-29）三把**分区面**的锁，各钉一条复核席实跑抓到的事：
分区一边宣称已校时、一边报没校正的系统钟／系统本地那一面的标签被印两遍／
00:00–08:00 的跨日提示把模型教成历法讲课。三把都走 ``snapshot`` →
``build_chat_prompt_with_diagnostics`` 这条真身口，不测格式化函数然后宣称分区修好了。
全程离线：注入的是真 ``TimeSync``，但取数钟冻在固定历元、偏移直接落账、
后台起跑器换成「只收不跑」的替身 ⇒ 零网络零线程；``_SHARED`` 是进程级全局，
每发用完在 teardown 里 ``reset_shared_for_tests()`` 复原（同树有别席在跑）。
"""

from __future__ import annotations

import time
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from plugins.bot_unified_runtime.contracts import (
    ContextBundle,
    ConversationHistoryResult,
    MemoryRetrievalResult,
    PersonaProfile,
    RetrievalResult,
    TemporalContext,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    _super_admin_host_partition_text,
    build_chat_prompt_with_diagnostics,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import temporal as tmod

DATE_LOCAL = "2026-09-25"


def _context(temporal: TemporalContext | None = None) -> ContextBundle:
    return ContextBundle(
        request_id="req-partition",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text="# 角色\n你就是守岸人。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-partition"),
        conversation_history=ConversationHistoryResult(request_id="req-partition"),
        knowledge_results=RetrievalResult(request_id="req-partition"),
        current_message="今天是什么日子",
        sender_id="user-1",
        session_id="private:user-1",
        # 预算给足：分区裁剪是另一族锁的管辖面，本文件要验的是"取数口给的行
        # 逐行进分区"，不能被缺省预算的截断噪声假红。
        context_budget=60000,
        temporal_context=temporal or TemporalContext(
            request_id="req-partition",
            now_local="21:00",
            date_local=DATE_LOCAL,
            weekday="星期五",
            timezone="Asia/Shanghai",
        ),
    )


def _system_prompt(**kwargs: str) -> str:
    messages, _ = build_chat_prompt_with_diagnostics(_context(), **kwargs)
    return messages[0]["content"]


def _system_prompt_for(temporal: TemporalContext) -> str:
    """同一装配口，只换 ``temporal_context``——第 ⑥ 族要验的是**真分区**里的读数。"""
    messages, _ = build_chat_prompt_with_diagnostics(_context(temporal))
    return messages[0]["content"]


# ---------------------------------------------------------------------------
# ①【当前时间】：首行不变 + 追加行与取数口逐字同值（非手写、恒非空）
# ---------------------------------------------------------------------------


def test_time_partition_first_line_unchanged_and_extras_same_source() -> None:
    prompt = _system_prompt()
    assert "【当前时间】2026-09-25 星期五 21:00" in prompt  # 首行字节口径=旧版
    extras = tmod.time_partition_extras(
        SimpleNamespace(timezone="Asia/Shanghai", date_local=DATE_LOCAL)
    )
    assert extras, "追加行不许为空：为空说明历法/校时取数口整段哑了"
    for line in extras:
        assert line in prompt, f"取数口给的行没进分区：{line}"
    # 五历同堂（第 10 项要求面）：公历/农历/伊斯兰历/藏历/东正教历都在分区里。
    for label in ("农历", "伊斯兰历", "藏历", "东正教历"):
        assert label in prompt
    # 手写计数禁则：分区文案里出现"共/总计 N 项"这类手写统计句式即红——
    # 一切数字只准来自现算行本身。
    block = prompt.split("【当前时间】", 1)[1].split("【", 1)[0]
    assert "共" not in block and "总计" not in block


def test_time_partition_fail_open_when_extras_broken(monkeypatch) -> None:
    def _throw(_temporal: object) -> list[str]:
        raise RuntimeError("历法面炸了")

    monkeypatch.setattr(tmod, "time_partition_extras", _throw)
    prompt = _system_prompt()
    assert "【当前时间】2026-09-25 星期五 21:00" in prompt  # 首行不受追加行株连
    assert "农历" not in prompt  # 追加行整段缺席=诚实少块，不是拿旧文案硬凑


# ---------------------------------------------------------------------------
# ② 空分区不渲染 / 非空恰好一次
# ---------------------------------------------------------------------------


def test_empty_readout_partitions_never_render() -> None:
    prompt = _system_prompt(host_status_section="", system_readout_section="")
    assert "【宿主机状态】" not in prompt
    assert "【系统自述】" not in prompt


def test_readout_partitions_render_once_when_nonempty() -> None:
    prompt = _system_prompt(
        host_status_section="取样 21:00\n处理器：X",
        system_readout_section="NoneBot：2.5.0",
    )
    assert prompt.count("【宿主机状态】") == 1
    assert prompt.count("【系统自述】") == 1
    assert "处理器：X" in prompt and "NoneBot：2.5.0" in prompt


# ---------------------------------------------------------------------------
# ③ 超管门：角色判据 + 脱敏，非超管恒空
# ---------------------------------------------------------------------------


def _message(roles: list[str]) -> SimpleNamespace:
    return SimpleNamespace(sender_roles=roles)


def test_host_partition_empty_for_non_super_admin() -> None:
    assert _super_admin_host_partition_text(_message(["user"])) == ""
    assert _super_admin_host_partition_text(_message(["admin"])) == ""
    assert _super_admin_host_partition_text(_message([])) == ""


def test_host_partition_super_admin_rows_are_redacted(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    monkeypatch.setattr(
        host_status,
        "cached_host_snapshot",
        lambda **_kw: (
            {
                "硬件": [("处理器", "Intel 某型")],
                "占用": [("磁盘 C:\\", "90%")],
                "系统与运行时": [("Python", "3.12.10")],
            },
            "21:00",
        ),
    )
    text = _super_admin_host_partition_text(_message(["super_admin", "admin"]))
    assert "【宿主机状态】" not in text  # 正文不带标签——标签归装配处，防双重出现
    assert "取样 21:00" in text and "处理器：Intel 某型" in text
    # 盘符路径进不了 prompt（redact_local_secrets 打码盘符形态）。
    assert "磁盘 C:\\" not in text


def test_host_partition_empty_rows_render_nothing(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.ops.monitor import host_status

    monkeypatch.setattr(
        host_status,
        "cached_host_snapshot",
        lambda **_kw: ({"硬件": [], "占用": [], "系统与运行时": []}, ""),
    )
    assert _super_admin_host_partition_text(_message(["super_admin"])) == ""


# ---------------------------------------------------------------------------
# ④ 校时/偏移读出：只读公开属性、诚实三态、坏时区回空
# ---------------------------------------------------------------------------


def test_clock_sync_readout_three_states(monkeypatch) -> None:
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync as ts

    monkeypatch.setattr(ts, "_SHARED", None)
    assert "未绑定" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=False, offset_seconds=None))
    assert "未启用" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=True, offset_seconds=None))
    assert "还没成功校准" in tmod.clock_sync_readout()
    monkeypatch.setattr(ts, "_SHARED", SimpleNamespace(enabled=True, offset_seconds=0.021))
    assert "+21" in tmod.clock_sync_readout()


def test_utc_offset_label_known_and_unknown() -> None:
    assert tmod.utc_offset_label("Asia/Shanghai") == "UTC+08:00"
    assert tmod.utc_offset_label("UTC") == "UTC+00:00"
    assert tmod.utc_offset_label("Mars/Phobos") == ""


# ---------------------------------------------------------------------------
# ⑤ 更新历史：git 不可用诚实缺席；成功路径走缓存不重复起子进程
# ---------------------------------------------------------------------------


def test_recent_update_lines_fail_open_without_git(monkeypatch) -> None:
    import subprocess

    tmod.clear_update_history_cache_for_tests()
    monkeypatch.setattr(tmod, "_repo_root", lambda: None)
    assert tmod.recent_update_lines() == []

    calls: list[object] = []

    def _boom(*_args, **_kwargs):
        calls.append(1)
        raise OSError("git 不存在")

    tmod.clear_update_history_cache_for_tests()  # 上一段的"无 git"已回填缓存，须清零再验子进程路径
    monkeypatch.setattr(tmod, "_repo_root", lambda: __import__("pathlib").Path("."))
    monkeypatch.setattr(subprocess, "run", _boom)
    assert tmod.recent_update_lines() == []
    assert len(calls) == 1  # 失败也回填缓存：坏 git 不被每条消息重试一遍
    assert tmod.recent_update_lines() == []
    assert len(calls) == 1
    tmod.clear_update_history_cache_for_tests()


def test_system_readout_lines_on_this_machine_non_empty() -> None:
    tmod.clear_update_history_cache_for_tests()
    lines = tmod.system_readout_lines()
    assert any(line.startswith("NoneBot") for line in lines), lines
    # 分区体不内嵌"共 N 项"式手写计数。
    assert all("共" not in line for line in lines)


def test_build_chat_prompt_entry_keeps_default_no_sections() -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
        build_chat_prompt,
    )

    system_prompt = build_chat_prompt(_context())[0]["content"]
    assert "【宿主机状态】" not in system_prompt
    assert "【系统自述】" not in system_prompt


# ---------------------------------------------------------------------------
# ⑥【当前时间】的墙钟必须跟着共享校时器 / 系统本地那一面不跟着走 / 跨日提示的
#    日常口径。三条都是 S24 复核席实跑抓到的，不是假设。
# ---------------------------------------------------------------------------

_ZONE_NAME = "Asia/Shanghai"
_ZONE = ZoneInfo(_ZONE_NAME)
_TOKYO = "Asia/Tokyo"

#: 冻结历元：配置时区墙钟 2026-09-28 21:00:58.4。
#: 为什么钉在一分钟的尾巴上：``TemporalContext.now_local`` **只到分**（分区首行的
#: 字节口径另有锁罩着），2 秒的位移在「到分」的读数里物理看不见。把历元摆到
#: :58.4，+2 秒必把分钟顶过界 ⇒ 「校时器到底走进来了没有」升格成分区里可断言的
#: 读数差，而不是拿一句"我调过了"当结论。
_EDGE_EPOCH = datetime(2026, 9, 28, 21, 0, 58, 400_000, tzinfo=_ZONE).timestamp()

#: 东京 09-26 08:30 == UTC 09-25 23:30 == 东八区 09-26 07:30 ⇒ UTC 那一把差一天。
_DIVERGENT = datetime(2026, 9, 26, 8, 30, tzinfo=ZoneInfo(_TOKYO))


@pytest.fixture
def shared_timesync(monkeypatch):
    """装一枚**真件** ``TimeSync`` 当进程内共享校时器：零网络零线程，用完必拆。

    ``configure_from`` 只会造出「已启用、本进程还没校准」（偏移恒 ``None``）的实例，
    校准值没法离线注进来，所以按 ``tests/test_timesync.py`` 既有写法直接落
    ``_offset_seconds``——本族量的是「分区读没读这把钟」，不是校时算法本身。
    ``max_drift_ms`` 给到 60 秒只为让 +2.0 是一枚合法量级的读数。
    """
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync as ts

    spawned: list = []
    # 起跑器换成「收下但不跑」：派发是 T2 的设计内行为，测试线程绝不联网。
    monkeypatch.setattr(ts, "_start_daemon_worker", lambda target: spawned.append(target))

    def _install(*, offset_seconds: float | None, freeze_epoch: float | None = _EDGE_EPOCH):
        ts.reset_shared_for_tests()
        shared = ts.configure_from(
            SimpleNamespace(
                bot_time_sync_enabled=True,
                bot_time_sync_servers="ntp.fake.test",
                bot_time_sync_max_drift_ms=60_000,
                bot_time_sync_http_enabled=False,
            )
        )
        if freeze_epoch is not None:
            # 冻住取数钟：本发量的是分区读不读这把钟，不是 SNTP 算法（真件实例、
            # 私有属性直填，与 tests/test_timesync.py 落 `_offset_seconds` 同款写法）。
            shared._clock = lambda: freeze_epoch
        shared._offset_seconds = offset_seconds
        # 「上次成功」推到当下 ⇒ ``_sync_due`` 判缓存新鲜，连派发都不必发生。
        shared._last_success_monotonic = time.monotonic()
        return shared

    _install.spawned = spawned  # type: ignore[attr-defined]
    try:
        yield _install
    finally:
        # 别的席在同一棵树上跑，_SHARED 是进程级全局 ⇒ 绝不留毒。
        ts.reset_shared_for_tests()


def test_wall_clock_partition_follows_the_shared_timesync(shared_timesync) -> None:
    install = shared_timesync
    provider = tmod.RuleBasedTemporalProvider(timezone=_ZONE_NAME)

    uncalibrated_syncer = install(offset_seconds=None)  # 已启用、未校准
    uncalibrated = provider.snapshot("req-uncalibrated")
    install(offset_seconds=2.0)  # 同一枚历元，偏移 +2.0 秒
    calibrated = provider.snapshot("req-calibrated")

    # 对照组（未校准）＝系统钟原样：历元 21:00:58.4 ⇒ 21:00。
    assert uncalibrated.date_local == "2026-09-28"
    assert uncalibrated.now_local == "21:00", uncalibrated.now_local
    # 位移组：晚 2 秒跨过分钟界 ⇒ 21:01。分区里看得见，才算真走进被量路径。
    assert calibrated.now_local == "21:01", (
        "共享校时器带着 +2 秒偏移，【当前时间】的墙钟却没跟着位移"
        "——snapshot 还在直接读系统钟"
    )
    assert calibrated.date_local == uncalibrated.date_local
    assert calibrated.weekday == uncalibrated.weekday
    assert uncalibrated_syncer.offset_seconds is None, (
        "调用线程里跑掉了校时轮——T2 之后 now() 只派发，不许替调用方联网"
    )

    # 真分区腿：这一枚时刻经 build_chat_prompt_with_diagnostics 进【当前时间】首行。
    prompt = _system_prompt_for(calibrated)
    block = prompt.split("【当前时间】", 1)[1].split("【", 1)[0]
    head = block.split("\n", 1)[0]
    expected_weekday = tmod.WEEKDAY_NAMES[date(2026, 9, 28).weekday()]
    assert head == f"2026-09-28 {expected_weekday} 21:01", head
    # 病灶的正面画像：旧写法在同一分区底下印「已校时」、报的却是没校正的钟。
    # 如今首行的位移与校时行点名的偏移必须同源、同一个数。
    assert "授时：SNTP 校时在线（当前偏移 +2000 毫秒）" in block, block


def test_partition_falls_back_to_system_clock_when_timesync_unusable(
    shared_timesync, monkeypatch
) -> None:
    """未绑定 / 抛异常 / 交出 naive 钟 ⇒ 回 ``datetime.now(zone)``，分区照出。

    校时面塌了不许把「现在几点」一起带走——这是 fail-open 的那一半，
    少了它，一次 SNTP 侧的事故就会变成时间分区整块缺席。
    """
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync as ts

    provider = tmod.RuleBasedTemporalProvider(timezone=_ZONE_NAME)

    # ① 未绑定：now() 落一枚禁用态默认实例，如实交回系统钟。
    # （夹具在这里只干一件事：teardown 必把 _SHARED 复位，不给同树别席留毒。）
    ts.reset_shared_for_tests()
    before = datetime.now(_ZONE)
    unbound = provider.snapshot("req-unbound")
    after = datetime.now(_ZONE)
    assert unbound.now_local in {before.strftime("%H:%M"), after.strftime("%H:%M")}
    assert unbound.date_local in {before.strftime("%Y-%m-%d"), after.strftime("%Y-%m-%d")}

    # ② 共享校时器抛异常。
    def _boom() -> datetime:
        raise RuntimeError("校时器塌了")

    monkeypatch.setattr(ts, "now", _boom)
    broken = provider.snapshot("req-broken")
    assert broken.now_local == datetime.now(_ZONE).strftime("%H:%M")

    # ③ 交出 naive 钟（不可信读数）：同样回落，绝不拿它换算。
    naive_moment = datetime.fromtimestamp(_EDGE_EPOCH, tz=_ZONE).replace(tzinfo=None)
    monkeypatch.setattr(ts, "now", lambda: naive_moment)
    naive = provider.snapshot("req-naive")
    assert naive.now_local == datetime.now(_ZONE).strftime("%H:%M")
    assert "【当前时间】" in _system_prompt_for(naive)


def test_system_local_face_stays_raw_and_label_printed_once(shared_timesync) -> None:
    from plugins.bot_unified_runtime.domains.ops.self_calendar import moments as mmod
    from plugins.bot_unified_runtime.domains.ops.self_calendar import report as rmod
    from plugins.bot_unified_runtime.domains.schedule.timesync import timesync as ts

    install = shared_timesync
    # 这一发**不冻钟**：真系统钟 + 2 秒偏移，才量得出系统本地那一面跟没跟着走。
    install(offset_seconds=2.0, freeze_epoch=None)
    # 原始系统钟另取一次**不借 helper**：只拿 ``system_clock_now()`` 的读数当基准，
    # 哪天把那枚 helper 本身接到校时器上，两边一起位移、差值仍是 0，锁当场瞎。
    raw_direct = datetime.now().astimezone()
    face_now = mmod.system_clock_now()
    synced = ts.now()
    assert abs((face_now - raw_direct).total_seconds()) < 1.0, (
        "system_clock_now 自己被接到了校时器上——那一面的身份就是机器自己的钟"
    )
    assert abs((synced - raw_direct).total_seconds() - 2.0) < 0.5, (
        "共享校时器压根没位移 ⇒ 本发成了空跑"
    )

    snapshot = mmod.resolve_moments(synced, timezone_name=_ZONE_NAME, system_now=face_now)
    assert snapshot.system is not None
    # 那一面的读数必须等于**原始**系统钟，不许跟着校时器位移。
    assert abs((snapshot.system.instant - raw_direct).total_seconds()) < 1.0, (
        "系统本地那一面被接到校时器上了——校正了它，这行标签就成了谎话"
    )
    assert abs((snapshot.system.instant - synced).total_seconds()) > 1.0

    lines = rmod.moment_lines(snapshot)
    # 按**行首**挑系统本地那一行：跨日提示（00:00–08:00 那段窗口里它本来就在场）
    # 也写着「系统本地 <日期>」，用子串挑会挑出两行、把锁变成时间炸弹。
    system_lines = [line for line in lines if line.startswith("系统本地时区")]
    assert len(system_lines) == 1, lines
    line = system_lines[0]
    assert line.count("系统本地时区") == 1, f"标签被印了两遍：{line}"
    assert line.startswith("系统本地时区（"), line
    assert f"：{snapshot.system.instant.strftime('%Y-%m-%d %H:%M:%S')}（" in line, line


def test_cross_day_note_gives_a_daily_convention_and_keeps_the_utc_face(
    monkeypatch,
) -> None:
    from plugins.bot_unified_runtime.domains.ops.self_calendar import moments as mmod
    from plugins.bot_unified_runtime.domains.ops.self_calendar import report as rmod

    snapshot = mmod.resolve_moments(
        _DIVERGENT, timezone_name=_TOKYO, system_now=_DIVERGENT
    )
    note = snapshot.day_divergence_note
    assert note.startswith("注意："), note
    # 诚实性一条都没删：跨日事实、逐把点名、历法取日口径全在。
    assert "不是同一天" in note and "东八区日界" in note, note
    assert "UTC 2026-09-25" in note and "配置时区 2026-09-26" in note, note
    # 日常口径（00:00–08:00 那场「几点啦」的历法讲座就是从这一句的缺失里长出来的）：
    # 只按配置时区那一把报，其余面等对方点名才展开，跨日一句带过。
    assert "只按配置时区那一把报" in note, note
    assert "并说清报的是这一把" in note, note
    assert "等对方点名要才展开" in note, note
    assert "不摊成历法汇报" in note, note

    # UTC 面没被删：命令面与对话分区两条读出口都还印 UTC 那一行。
    assert snapshot.utc.day == date(2026, 9, 25)
    assert any(
        line.startswith("UTC 时刻：2026-09-25 23:30:00") for line in rmod.moment_lines(snapshot)
    ), rmod.moment_lines(snapshot)
    assert any(
        line.startswith("UTC 时刻：")
        for line in rmod.clock_comparison_lines(snapshot)
    ), rmod.clock_comparison_lines(snapshot)

    # 分区腿：同一句提示逐字经 time_partition_extras 进【当前时间】（措辞零副本）。
    monkeypatch.setattr(mmod, "system_clock_now", lambda: _DIVERGENT)
    extras = tmod.time_partition_extras(
        SimpleNamespace(timezone=_TOKYO, date_local="2026-09-26", now_local="08:30")
    )
    assert note in extras, extras
