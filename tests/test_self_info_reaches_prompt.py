"""自我信息进提示词的活性锁（S-T-SELFINFO-3，需求 10）。

本文件只管一件事：**「取数口存在」不等于「模型看得见」**。

前席 S-T-DOC-2 的教训原话是「不能只测分区渲染器——要测 ``build_chat_result``
真的把上下文 provider 喂进去了」。所以这里三族锁：

1. **分区面**（``build_chat_prompt_with_diagnostics``）：四把钟里缺的三面
   （UTC 绝对时刻 / 历法取日 / 系统本地钟）与「更新历史（叙述文档台账）」确实进了
   system 文本，且与取数口给的行**逐字同值**（测试不抄第二份文案）。
2. **生产调用点**（``build_chat_result``）：一个只会截获 messages 然后抛错的
   provider —— 断言发生在**发给模型的那条 messages** 上，不是发生在渲染器上。
   装配段哪天忘了把 section 传进去，第 1 族全绿而这一族必红。
3. **反第二措辞 / 杀伤力**：【当前时间】里每条历法只准出现一次；把取数口摘掉
   或把 import 删掉，锁必须红（空跑的锁比没有锁更危险）。

被试件：``domains/chat_reply/capabilities/chat.py`` 的上下文分区装配段 +
``domains/ops/self_calendar/{report,facts_leg,moments}.py``。
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    ContextBundle,
    ConversationHistoryResult,
    IncomingMessage,
    MemoryRetrievalResult,
    PersonaProfile,
    PrivacyLevel,
    RetrievalResult,
    RiskLevel,
    SendPolicy,
    SessionType,
    TemporalContext,
    ToneProfile,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat as chatmod
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (
    build_chat_prompt_with_diagnostics,
    build_chat_result,
)
from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.providers import (
    LLMProviderError,
)
from plugins.bot_unified_runtime.domains.ops import self_calendar as self_calendar_pkg
from plugins.bot_unified_runtime.domains.ops.self_calendar import moments as moments_mod
from plugins.bot_unified_runtime.domains.ops.self_calendar import report as report_mod

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHAT_PY = (
    _REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "capabilities"
    / "chat.py"
)

#: 钉死在测试里的「所报时刻」：Asia/Shanghai 2026-09-25 21:00。
#: UTC = 2026-09-25 13:00，与东八区同日 ⇒ 历法取日 2026-09-25。
_DATE_LOCAL = "2026-09-25"
_NOW_LOCAL = "21:00"
_TZ = "Asia/Shanghai"


def _context() -> ContextBundle:
    return ContextBundle(
        request_id="req-selfinfo",
        persona=PersonaProfile(
            profile_id="shorekeeper",
            version="1",
            display_name="守岸人",
            identity="守岸人",
            raw_text="# 角色\n你就是守岸人。",
        ),
        tone=ToneProfile(profile_id="shorekeeper", mode="default"),
        memory_results=MemoryRetrievalResult(request_id="req-selfinfo"),
        conversation_history=ConversationHistoryResult(request_id="req-selfinfo"),
        knowledge_results=RetrievalResult(request_id="req-selfinfo"),
        current_message="现在几点了？ UTC 那边是哪天？",
        sender_id="user-1",
        session_id="private:user-1",
        # 预算给足：本文件验的是「进没进」，不能被裁剪噪声假红。
        context_budget=60000,
        temporal_context=TemporalContext(
            request_id="req-selfinfo",
            now_local=_NOW_LOCAL,
            date_local=_DATE_LOCAL,
            weekday="星期五",
            timezone=_TZ,
        ),
    )


def _system_prompt(**kwargs: str) -> str:
    messages, _ = build_chat_prompt_with_diagnostics(_context(), **kwargs)
    return messages[0]["content"]


def _time_block(prompt: str) -> str:
    return "【当前时间】" + prompt.split("【当前时间】", 1)[1].split("【", 1)[0]


# ---------------------------------------------------------------------------
# ① 分区面：三面钟与台账更新历史确实进了 system 文本，且与取数口逐字同值
# ---------------------------------------------------------------------------


def test_clock_increment_lines_match_the_producer_verbatim() -> None:
    """分区里的时刻增补行 == ``report.clock_comparison_lines`` 现算给的行。

    比对「出现的行」而不是「出现的子串」：抄一份文案进测试就测不出两套措辞并存。
    """
    snapshot = moments_mod.resolve_moments_from_context_text(
        date_local=_DATE_LOCAL, now_local=_NOW_LOCAL, timezone_name=_TZ
    )
    assert snapshot is not None
    expected = report_mod.clock_comparison_lines(snapshot)
    assert expected, "取数口给了空表 ⇒ 下面全部断言会空跑"
    block = _time_block(_system_prompt())
    for line in expected:
        assert line in block, f"{line!r} 没进【当前时间】分区"


def test_clock_increment_carries_utc_instant_and_calendar_day() -> None:
    """三面钟的名字逐面点名：UTC 绝对时刻、历法取日（东八区日界）、系统本地钟。"""
    block = _time_block(_system_prompt())
    assert "UTC 时刻：2026-09-25 13:00:00" in block, block
    assert "历法日界（东八区）：2026-09-25" in block, block
    # 系统钟：钉死的历史上下文与真实系统钟必然不是同一次读数 ⇒ 必须说「未探测」，
    # 绝不许拿今天的系统钟硬凑一行看起来对的日期（moments 的写死口径）。
    assert "系统本地时区：未探测" in block, block


def test_ledger_update_history_is_in_system_readout_partition() -> None:
    """【系统自述】带出「在册叙述文档台账」那条更新历史（不是 git 提交那条）。

    读的是**真仓库**（``project_root()`` 上溯锚点），所以这一条同时也是
    「facts_leg 在真盘上读得到东西」的活性证明——首版按 ``parents[4]`` 数层数错
    一层就会恒回 None 而单测照样绿。
    """
    section = chatmod._system_readout_section_text(is_admin=False)
    assert "更新历史（在册叙述文档台账" in section, section[:400]
    prompt = _system_prompt(system_readout_section=section)
    readout = "【系统自述】" + prompt.split("【系统自述】", 1)[1].split("【", 1)[0]
    assert "更新历史（在册叙述文档台账" in readout
    # 两条历史各自的来源标注都在，且互不冒充。
    assert "台账 #" in readout or "§" in readout, readout[:600]
    assert "我能做的事" in readout, "功能清单被增补行挤掉了"


def test_empty_ledger_history_degrades_to_honest_absence(tmp_path: Path) -> None:
    """叙述文档读不到 ⇒ 那一块诚实缺席，不产一行「暂无更新」骗模型。"""
    lines = chatmod._update_history_ledger_lines(root=tmp_path)
    body = "\n".join(lines)
    assert "未接入" in body, body
    assert "暂无更新" not in body


# ---------------------------------------------------------------------------
# ② 生产调用点：断言发生在发给模型的 messages 上
# ---------------------------------------------------------------------------


class _CapturingProvider:
    """截获最终 messages 后立刻抛错：短路回复面，但已经拿到发送前的那一手证据。"""

    captured: ClassVar[list[list[dict[str, str]]]] = []

    def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        type(self).captured.append(list(messages))
        raise LLMProviderError("selfinfo liveness probe", error_kind="server")


def _message() -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot_v11",
        bot_id="bot-1",
        session_id="private_user-1",
        session_type=SessionType.PRIVATE,
        sender_id="user-1",
        plain_text="现在几点了",
    )


def _decision(message: IncomingMessage) -> BotDecision:
    return BotDecision(
        request_id=message.request_id,
        should_respond=True,
        mode="chat",
        trigger="mention",
        capability_id="bot.chat",
        target_scope=SessionType.PRIVATE,
        privacy_level=PrivacyLevel.PERSONAL,
        risk_level=RiskLevel.LOW,
        send_policy=SendPolicy.IMMEDIATE,
        decision_reason="test",
    )


def _captured_system_prompt() -> str:
    _CapturingProvider.captured.clear()
    message = _message()
    build_chat_result(
        message,
        _decision(message),
        _context(),
        llm_provider=_CapturingProvider(),  # type: ignore[arg-type]
        model_router=_CapturingProvider(),  # type: ignore[arg-type]
    )
    assert _CapturingProvider.captured, "provider 压根没被调到 ⇒ 这条锁在空跑"
    messages = _CapturingProvider.captured[-1]
    system = [item for item in messages if item.get("role") == "system"]
    assert system, messages
    return str(system[0]["content"])


def test_build_chat_result_feeds_self_knowledge_into_the_outgoing_messages() -> None:
    """**本席的核心交付**：越过渲染器，直接看发出去的那条 messages。

    装配段（``build_chat_result`` 里 ``if safety.action == "allow"`` 那一块）哪天
    漏传一个形参，第 ① 族锁全部照绿而模型一个字都收不到——这条是唯一的揭穿者。
    """
    prompt = _captured_system_prompt()
    assert "【当前时间】" in prompt
    block = _time_block(prompt)
    assert "UTC 时刻：" in block, block
    assert "历法日界（东八区）：" in block, block
    assert "【系统自述】" in prompt
    assert "更新历史（在册叙述文档台账" in prompt, prompt[-1500:]


def test_poison_clock_producer_empties_the_partition(monkeypatch: pytest.MonkeyPatch) -> None:
    """摘掉取数口 ⇒ 分区里那三面必须一起消失（证明分区真的在调它，不是自说自话）。

    注毒下在**包属性**上：装配层是 ``from ...self_calendar import clock_comparison_lines``
    ——`__init__` 在导入期就把函数对象搬走了，所以抹子模块的属性抹不动，
    抹包属性才打得中真实调用边（第一版抹 ``report_mod`` 直接空跑，被自己抓到）。
    """
    monkeypatch.setattr(self_calendar_pkg, "clock_comparison_lines", lambda _snapshot: [])
    block = _time_block(_system_prompt())
    assert "UTC 时刻：" not in block, "取数口已被摘掉而分区还有这行 ⇒ 分区里藏了第二份"
    # 既有面不受株连：首行与历法行照旧（fail-open 只丢增补的那三面）。
    assert block.startswith("【当前时间】2026-09-25 星期五 21:00"), block
    assert "农历：" in block


def test_poison_assembly_call_site_kills_production_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """装配点交空串 ⇒ 生产 messages 里整块消失，而渲染器显式传参时照出。

    这条测的是 ``build_chat_result`` 那一手**传参**：第 ① 族锁只喂渲染器、
    自己把 section 当形参传进去，所以装配段哪天漏传一个 kwarg 它一个字都不会红。
    红点在装配、不在渲染，两族的差集就是 DOC-2 说的那一格。
    """
    monkeypatch.setattr(chatmod, "_system_readout_section_text", lambda **_kw: "")
    prompt = _captured_system_prompt()
    assert "【系统自述】" not in prompt, "装配段被摘掉而生产 messages 里还有这块"
    assert "更新历史（在册叙述文档台账" not in prompt
    # 同一时刻显式传参的渲染器面照出 ⇒ 消失的原因只能是装配没喂，不是渲染器坏了。
    assert "【系统自述】" in _system_prompt(system_readout_section="哨兵正文")


def test_ledger_history_produced_by_assembly_reaches_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整条链（取数口 → 装配 → 渲染 → 发出去的 messages）用一行哨兵走通。

    只验 facts_leg 这一族，因为它**只**经装配段进 prompt（时刻那三面经渲染器，
    上面两条已经分头钉过）。哨兵不打真盘，所以这条快。
    """
    sentinel = "- 哨兵台账行 #000 只用于证明链路"
    monkeypatch.setattr(
        chatmod, "_update_history_ledger_lines", lambda *_a, **_k: [sentinel]
    )
    prompt = _captured_system_prompt()
    assert sentinel in prompt, "装配段产出的行没到模型眼前"
    assert chatmod._LEDGER_HISTORY_HEADER in prompt



# ---------------------------------------------------------------------------
# ③ 反第二措辞 / 锁的杀伤力
# ---------------------------------------------------------------------------


def test_current_time_partition_keeps_one_wording_per_calendar_face() -> None:
    """历法行只有 temporal 那一套措辞；时刻增补行不得再念一遍历法。

    ``tests/test_time_partition_day_divergence.py:176`` 已经把 ``temporal.py``
    那侧锁成「只借四把钟、不借历法行」。本条补上装配层这一侧：同一个「今天」在
    一个分区里出现两种措辞，模型就会挑错的那一套回答。
    """
    block = _time_block(_system_prompt())
    for face in ("农历：", "伊斯兰历", "藏历", "东正教历"):
        assert block.count(face) == 1, f"{face} 在【当前时间】里出现了 {block.count(face)} 次"
    assert block.count("UTC 时刻：") == 1


def test_chat_py_borrows_exactly_the_self_calendar_legs() -> None:
    """chat.py 从 self_calendar 借的名字是**精确集合**，多借一个就红。

    借多了 = 把历法行/更新历史的第二套措辞请进装配层。缺了 = 本席接的两条腿
    又退回「无消费者」。判据走 AST，不看注释也不跑代码。
    """
    names = _self_calendar_borrowed_names(_CHAT_PY.read_text(encoding="utf-8"))
    assert names == {
        "clock_comparison_lines",
        "resolve_moments_from_context_text",
        "system_clock_now",
        "update_history_lines",
    }, names


def test_borrow_set_lock_has_teeth(tmp_path: Path) -> None:
    """注毒：把历法行也借进来，上一条必须红（否则那把精确集合锁是空跑的）。"""
    poisoned = (
        "from plugins.bot_unified_runtime.domains.ops.self_calendar import (\n"
        "    calendar_compact_lines,\n"
        "    clock_comparison_lines,\n"
        "    resolve_moments_from_context_text,\n"
        "    system_clock_now,\n"
        "    update_history_lines,\n"
        ")\n"
    )
    fake = tmp_path / "chat_poison.py"
    fake.write_text(poisoned, encoding="utf-8")
    names = _self_calendar_borrowed_names(fake.read_text(encoding="utf-8"))
    assert "calendar_compact_lines" in names
    assert names != {
        "clock_comparison_lines",
        "resolve_moments_from_context_text",
        "system_clock_now",
        "update_history_lines",
    }


def _self_calendar_borrowed_names(source: str) -> set[str]:
    borrowed: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("self_calendar") or isinstance(node, ast.ImportFrom) and ".self_calendar." in (node.module or ""):
            borrowed |= {alias.name for alias in node.names}
    return borrowed


# ---------------------------------------------------------------------------
# ④ UTC 偏移 label 两处生产者必须同值（真合并前的止血带，见日志 §5 第 1 条）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone_name",
    ["Asia/Shanghai", "UTC", "Asia/Kolkata", "America/New_York", "Pacific/Kiritimati"],
)
def test_offset_label_two_faces_agree_for_sample_zones(zone_name: str) -> None:
    """``temporal.utc_offset_label`` 与 ``moments`` 的 ``offset_label`` 不许各说一套。

    本席没改 ``temporal.py``（非本席可写面），所以留一把等值锁：任一侧漂了
    （比如有人把分钟偏移算错、或加了 ``+08:30`` 形态）当场红，而不是让
    【当前时间】首行与时刻分区各报一个偏移。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.character import (
        temporal as tmod,
    )

    moment = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    snapshot = moments_mod.resolve_moments(moment, timezone_name=zone_name)
    assert tmod.utc_offset_label(zone_name) == snapshot.local.offset_label, (
        zone_name,
        tmod.utc_offset_label(zone_name),
        snapshot.local.offset_label,
    )


def test_context_text_reconstruction_refuses_to_guess() -> None:
    """坏输入 ⇒ None，不猜一个看起来对的瞬间（naive 钟是本包唯一的硬拒面）。"""
    assert moments_mod.resolve_moments_from_context_text(
        date_local="not-a-date", now_local=_NOW_LOCAL, timezone_name=_TZ
    ) is None
    assert moments_mod.resolve_moments_from_context_text(
        date_local=_DATE_LOCAL, now_local="", timezone_name=_TZ
    ) is None


def test_same_reading_window_constant_is_shared_not_copied() -> None:
    """「同一次取数」窗口在本包与装配层只有一份数值。

    本席刻意让 chat.py **借用** ``temporal._MOMENTS_SAME_READING_SECONDS``
    （同 ``temporal.py:643`` 复用 ``host_status._runtime_versions`` 的先例），
    而不是再写一个 600——数值一分为二就是下一次跨日假话的产地。
    """
    source = _CHAT_PY.read_text(encoding="utf-8")
    assert "_MOMENTS_SAME_READING_SECONDS" in source
    assert "SAME_READING_SECONDS = " not in source, "装配层自己又定义了一枚窗口常量"
    assert moments_mod.resolve_moments_from_context_text(
        date_local=_DATE_LOCAL,
        now_local=_NOW_LOCAL,
        timezone_name=_TZ,
        system_now=datetime(2026, 9, 25, 21, 0, 30, tzinfo=moments_mod.CST),
        same_reading_seconds=moments_mod.SAME_READING_SECONDS,
    ).system is not None, "窗口内的系统钟应当被采纳"
