"""真机验收面「叙述授予波」六判定的离线回归 + 逐枚注毒（席 e2e2，2026-10-05）。

覆盖 `scripts/e2e_acceptance.py` 新增的六枚谓词（矩阵项 ⑱ 那一族）：全程零网络、
零真实 bot、零生产库——所有会落盘的路径都指 `tmp_path`（AGENTS 规则 2/6）。

为什么每枚判定都要**注一次毒**：本项目最大的假绿形态是「验收项静默通过」
（台账 #72★「三格哑面在盘不在码」、#76★「覆盖册那枚常驻值把永久策略整段静音」）。
只证明谓词现在为真没有价值，必须同时证明**它能变红**——每个下面的 `poison_*` 用例
都在断言「这一枚一旦回退，红线长什么样」。注毒一律走 `monkeypatch`（含把
`module.__file__` 指向 `%TEMP%` 下的坏副本这种只读手法），**仓库文件零字节改动**，
最后一条用例用 sha256 复证这一点。

复跑命令（卫生前缀按规则 6；basetemp 必须在仓库外、且不在 ChatBot_Runtime 根下）::

    PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 python -m pytest \
        tests/test_e2e_acceptance_narration.py -q -p no:cacheprovider \
        --basetemp=<%TEMP>/seat-e2e2-work/bt-1
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import ReceiptState, SessionType
from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    content_route,
    intimate_control,
)
from plugins.bot_unified_runtime.domains.render import reviewer
from plugins.bot_unified_runtime.domains.transport.sender import onebot
from plugins.bot_unified_runtime.domains.transport.sender import queue as send_queue_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "scripts" / "e2e_acceptance.py"
HARNESS_SHA_AT_COLLECT = hashlib.sha256(HARNESS_PATH.read_bytes()).hexdigest()

#: 六枚矩阵项（⑱ 那一族）——key 漂了就报，不静默少测。
NARRATION_KEYS = (
    "narration-grant-source",
    "narration-scene-tier",
    "narration-person-policy",
    "narration-group-scrub",
    "narration-audit-row",
    "narration-action-brackets",
    "narration-failure-reason",
)


def _config(tmp_path, **overrides) -> Config:
    """离线 Config：运行数据根落 `tmp_path`（直呼 ``Config()`` 会把库折进源码树，
    后果链见 `tests/test_e2e_acceptance.py::_runtime_stub` 的记档）。"""
    kwargs: dict[str, object] = {
        "bot_runtime_data_dir": str(tmp_path / "runtime-data"),
        "bot_quiet_hours_enabled": False,
        "bot_affinity_enabled": False,
        "bot_group_white1": ["555"],
        "bot_content_route_enabled": True,
    }
    kwargs.update(overrides)
    return Config(**kwargs)  # type: ignore[arg-type]


def _runtime(tmp_path, **overrides) -> e2e.E2eRuntime:
    return e2e.E2eRuntime(
        config=_config(tmp_path, **overrides),
        runtime_settings=SimpleNamespace(
            get=lambda key, cfg: None, get_persona_override=lambda: ""
        ),
        render_backend=None,
        execute=False,
        city="北京",
        bot_id="",
        sender_id="10000",
    )


# ==================================================== ① 叙述授予按来源


def test_grant_is_source_scoped(tmp_path) -> None:
    assert e2e.check_narration_grant_is_source_scoped() == ""


def test_grant_poison_auto_fallback_source_joins_the_grant(tmp_path) -> None:
    """注毒：把自动回落支塞进授予集 ⇒ 必须红在「自动回落拿到授予」。"""
    poisoned = frozenset(
        set(content_route._INTIMATE_NARRATION_SOURCES)
        | {content_route.INTIMATE_SOURCE_AFFINITY}
    )
    monkey = pytest.MonkeyPatch()
    monkey.setattr(content_route, "_INTIMATE_NARRATION_SOURCES", poisoned)
    reason = e2e.check_narration_grant_is_source_scoped()
    monkey.undo()
    assert "自动回落/未知来源拿到了叙述授予" in reason, reason


def test_grant_poison_manual_source_dropped(tmp_path) -> None:
    """注毒：把显式指令支摘掉 ⇒ 必须红在「人工推动的来源没拿到授予」。"""
    poisoned = frozenset(
        source
        for source in content_route._INTIMATE_NARRATION_SOURCES
        if source != content_route.INTIMATE_SOURCE_MANUAL
    )
    monkey = pytest.MonkeyPatch()
    monkey.setattr(content_route, "_INTIMATE_NARRATION_SOURCES", poisoned)
    reason = e2e.check_narration_grant_is_source_scoped()
    monkey.undo()
    assert "人工推动的来源没拿到叙述授予" in reason, reason


def test_grant_poison_narration_pin_dropped(tmp_path) -> None:
    """注毒（差集 W-1）：把第四枚授予来源（描写档持久钉）摘掉 ⇒ 必须红在点名那一行。

    改前的 must-grant 名册只列三支 ⇒ 这一支被摘掉时 ① 照绿，而「普通模式钉过 scene
    的人」在出口静默拿不到铺写（G-2 把 `narration_pin` 并进的就是这**同一把**尺）。
    """
    poisoned = frozenset(
        source
        for source in content_route._INTIMATE_NARRATION_SOURCES
        if source != content_route.INTIMATE_SOURCE_NARRATION_PIN
    )
    monkey = pytest.MonkeyPatch()
    monkey.setattr(content_route, "_INTIMATE_NARRATION_SOURCES", poisoned)
    reason = e2e.check_narration_grant_is_source_scoped()
    monkey.undo()
    assert "INTIMATE_SOURCE_NARRATION_PIN" in reason, reason


# ==================================================== ② 顶格档只有授予腿走得到


def test_top_tier_reachability(tmp_path) -> None:
    assert e2e.check_top_reply_tier_needs_the_grant(_config(tmp_path), tmp_path) == ""


def test_top_tier_reachability_without_config(tmp_path, monkeypatch) -> None:
    """缺省形参那条路也要跑通：矩阵项 `expect` 之外还有人按零参调用本判定。"""
    monkeypatch.setattr(e2e, "narration_probe_dir", lambda: tmp_path / "probe")
    (tmp_path / "probe").mkdir()
    assert e2e.check_top_reply_tier_needs_the_grant() == ""


def test_top_tier_poison_opening_intimate_still_gives_speech(
    tmp_path, monkeypatch
) -> None:
    """注毒（H-1＝甲的新腿）：把 `manual` 摘出授予表 ⇒ ③那一格不fire ⇒ 必须红在「开亲密仍只说话」。

    这一枚就是差集 W-2：改前的判定**只**证「非授予腿到不了顶格」，所以「开亲密但描写
    轴还给 speech」这种形态（甲没落地）在验收面是全绿的。现在它会红。
    """
    poisoned = frozenset(
        source
        for source in content_route._INTIMATE_NARRATION_SOURCES
        if source != content_route.INTIMATE_SOURCE_MANUAL
    )
    monkeypatch.setattr(content_route, "_INTIMATE_NARRATION_SOURCES", poisoned)
    reason = e2e.check_top_reply_tier_needs_the_grant(_config(tmp_path), tmp_path)
    assert "描写轴读数" in reason and "speech" in reason, reason


def test_top_tier_poison_auto_leg_gets_scene(tmp_path, monkeypatch) -> None:
    """注毒（自动腿负对照）：轴心恒交 `scene` ⇒ (d) 必须红在「自动腿也能铺开写」。

    反证的是「甲被顺手读成凡亲密皆铺写」——Master Love 名单派生与好感度达档都不在
    授予面上，这一格放宽就是第二次放宽，撞她 2026-09-28 原话。
    """
    monkeypatch.setattr(
        chat,
        "resolve_narration_axis",
        lambda _ctx: chat.NarrationAxis(chat.NARRATION_MODE_SCENE, True),
    )
    reason = e2e.check_top_reply_tier_needs_the_grant(_config(tmp_path), tmp_path)
    assert "自动腿" in reason, reason


def test_top_tier_poison_matrix_points_at_it() -> None:
    """注毒：矩阵里指一格向顶格档 ⇒ 红（全局长度被吃进铺写）。"""
    qtype = min(chat.REPLY_TIER_MATRIX)
    mode = min(chat.REPLY_TIER_MATRIX[qtype])
    original = chat.REPLY_TIER_MATRIX[qtype][mode]
    monkey = pytest.MonkeyPatch()
    monkey.setitem(chat.REPLY_TIER_MATRIX[qtype], mode, chat._REPLY_TIER_TOP_ID)
    reason = e2e.check_top_reply_tier_needs_the_grant()
    monkey.undo()
    assert reason and "指向顶格档" in reason, reason
    assert chat.REPLY_TIER_MATRIX[qtype][mode] == original


def test_top_tier_poison_grant_leg_cannot_reach_it() -> None:
    """注毒：授予腿封顶到「详尽」⇒ 红（顶格档成了死档，她 2026-10-04 的原状）。"""
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        chat,
        "intimate_reply_length_tier",
        lambda detail_mode, message_text="": chat.REPLY_TIER_DETAIL_ID,
    )
    reason = e2e.check_top_reply_tier_needs_the_grant()
    monkey.undo()
    assert "到不了顶格档" in reason, reason


# ==================================================== ③ 永久策略压过常驻全局档


def test_person_policy_beats_standing_global_detail(tmp_path) -> None:
    assert e2e.check_person_policy_beats_standing_global_detail(tmp_path) == ""


def test_person_policy_poison_layer_two_blinded(monkeypatch) -> None:
    """注毒：第②层读不出该人钉过的档（＝改前「覆盖册常驻值当本轮明示」）⇒ 必须红。"""
    monkeypatch.setattr(intimate_control, "_person_length_mode", lambda *a, **k: "")
    with pytest.MonkeyPatch.context() as probe:
        probe.setattr(e2e, "narration_probe_dir", lambda: Path(tempfile.mkdtemp()))
        reason = e2e.check_person_policy_beats_standing_global_detail()
    assert "被常驻 BOT_REPLY_DETAIL=detail 静音" in reason, reason


# ==================================================== ④ 群内逐段涂销 + 审计行


def test_group_span_scrub_and_audit_row(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    assert e2e.check_group_span_scrub_is_recorded(runtime) == ""
    outcome = _run_matrix_key(runtime, "narration-group-scrub", tmp_path)
    assert outcome.error == "", outcome.error
    assert e2e.expect_group_span_scrub(outcome) == ""


def _run_matrix_key(runtime, key: str, tmp_path) -> e2e.ItemOutcome:
    from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    item = next(entry for entry in e2e.build_matrix(runtime) if entry.key == key)
    return e2e.execute_item(
        pipeline=e2e.build_pipeline(runtime, queue),
        send_queue=queue,
        item=item,
        runtime=runtime,
        session_type=SessionType.GROUP,
        target_id="555",
        seq=1,
    )


def test_group_scrub_poison_whole_message_swallowed(tmp_path, monkeypatch) -> None:
    """注毒：降级腿退回 None（＝改前「整条吞」）⇒ 正文断言与审计断言双双报红。"""
    monkeypatch.setattr(
        reviewer, "_try_neutralise_group_output", lambda result, output_text: None
    )
    runtime = _runtime(tmp_path)
    outcome = _run_matrix_key(runtime, "narration-group-scrub", tmp_path)
    text_reason = e2e.expect_group_span_scrub(outcome)
    audit_reason = e2e.check_group_span_scrub_is_recorded(runtime)
    assert "整条 BLOCK" in text_reason or "blocked" in text_reason, text_reason
    assert "整条 BLOCK 而非逐段涂销" in audit_reason, audit_reason


def test_group_scrub_poison_audit_row_never_written(tmp_path, monkeypatch) -> None:
    """注毒：审计行不写（＝ 2026-10-04 之前的真实形态）⇒ 必须红在「审计行缺席」。

    这条是任务点名要的那枚：那行今天才被接上，没接上时「已落账」就是假话。
    """
    monkeypatch.setattr(
        InMemoryAuditLogger, "append", lambda self, record: record
    )
    reason = e2e.check_group_span_scrub_is_recorded(_runtime(tmp_path))
    assert "review 审计行缺席" in reason, reason


def test_group_scrub_poison_other_segments_erased(tmp_path, monkeypatch) -> None:
    """注毒：命中那一处在，但**其余正文被顺手吞掉**（＝没做到「逐段」）⇒ 必须红。

    反证对象是「涂销腿只保住半条」这一形态；`_PUBLIC_OUTPUT_SPAN_PLACEHOLDER` 单独改名
    不红，因为判定与代码读同一枚记号（刻意不硬抄字面量，免得记号改名时验收变假红）。
    """
    placeholder = str(reviewer._PUBLIC_OUTPUT_SPAN_PLACEHOLDER)
    monkeypatch.setattr(
        reviewer,
        "_try_neutralise_group_output",
        lambda result, output_text: (
            f"{e2e._GROUP_SCRUB_CLEAN_HEAD}{placeholder}",
            ["public output span neutralised: poison"],
        ),
    )
    runtime = _runtime(tmp_path)
    outcome = _run_matrix_key(runtime, "narration-group-scrub", tmp_path)
    reason = e2e.expect_group_span_scrub(outcome)
    assert "其余正文被吞" in reason, reason


# ==================================================== ⑤ 授予轮保住（…）动作


def test_action_brackets_follow_grant(tmp_path) -> None:
    assert e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path) == ""


def test_action_brackets_poison_strip_is_unconditional(tmp_path, monkeypatch) -> None:
    """注毒：剥动作的调用点回到裸调用（＝改前「不分档位硬剥」）⇒ 形腿报红。"""
    monkeypatch.setattr(e2e, "_roleplay_strip_mouths", lambda path: (1, ["4885"]))
    reason = e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path)
    assert "不在 action_brackets 判据里" in reason, reason


def test_action_brackets_poison_grant_denied(tmp_path, monkeypatch) -> None:
    """注毒：授予判据恒假 ⇒ 实腿报红（钉了深开也拿不到叙述授权）。"""
    monkeypatch.setattr(content_route, "grants_intimate_narration", lambda source: False)
    reason = e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path)
    assert "不在授予集里" in reason or "仍被剥光" in reason, reason


def test_action_brackets_poison_speech_turn_is_not_forced_to_have_brackets(
    tmp_path, monkeypatch
) -> None:
    """注毒（差集 W-3 的拆轴）：轴恒交 `speech` ⇒ 本腿必须**报红而不是代判通过**。

    2026-10-05 之后样式段按 (描写档 × 亲密态) 选：只说话那一轮**刻意**没有 `（…）`。
    把「动作段一定在场」当所有授予轮的通式去扩＝假红；所以判定先坐实这一轮是 scene 轮
    再判括号。这一枚注毒证明那道前置门真的在（红在「本腿只判 scene 轮的交付面」）。
    """
    monkeypatch.setattr(
        chat,
        "resolve_narration_axis",
        lambda _ctx: chat.NarrationAxis(chat.NARRATION_MODE_SPEECH, True),
    )
    reason = e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path)
    assert "本腿只判 scene 轮的交付面" in reason, reason


def test_action_brackets_poison_style_blocks_collapse(tmp_path, monkeypatch) -> None:
    """注毒：样式段不再按轴选（两格同文）⇒ 必须红在「描写档轴只剩读数、不选文风」。"""
    monkeypatch.setattr(
        chat, "resolve_rp_style_block", lambda _mode, **_kw: "同一句话"
    )
    reason = e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path)
    assert "选出同一段样式" in reason, reason


def test_action_brackets_poison_unknown_axis_mode_not_collapsed(tmp_path, monkeypatch) -> None:
    """注毒：认不出的轴值不收回 `speech`（fail-closed 反向）⇒ 红在「漂走的轴值在放大描写面」。"""
    monkeypatch.setattr(
        chat,
        "resolve_rp_style_block",
        lambda mode, **_kw: (
            "铺开写"
            if str(mode) in (chat.NARRATION_MODE_SCENE, "e2e-unknown-axis-mode")
            else "只说话"
        ),
    )
    reason = e2e.check_action_brackets_follow_narration_grant(_config(tmp_path), tmp_path)
    assert "没 fail-closed 收回 speech" in reason, reason


# ==================================================== ⑥ 投递失败原因可查


def test_delivery_failure_reason_readable(tmp_path) -> None:
    assert e2e.check_delivery_failure_reason_is_readable(tmp_path) == ""


def _poisoned_onebot_source(tmp_path, *, text: str) -> Path:
    """把 onebot.py 抄进 `tmp_path` 并改坏，只动副本（生产件零字节）。"""
    target = tmp_path / "onebot_poisoned.py"
    target.write_text(text, encoding="utf-8")
    return target


def test_delivery_reason_poison_mouth4_bypass_returns(tmp_path, monkeypatch) -> None:
    """注毒：第 4 枚嘴的守卫重新混进白名单判据（改前原形）⇒ 红在「混进了白名单判据」。"""
    source = Path(onebot.__file__).read_text(encoding="utf-8")
    assert "if progress.count > 0:" in source
    poisoned = source.replace(
        "if progress.count > 0:",
        "if progress.count > 0 and not _is_final_failure_retcode(retcode):",
    )
    monkeypatch.setattr(onebot, "__file__", str(_poisoned_onebot_source(tmp_path, text=poisoned)))
    reason = e2e.check_delivery_failure_reason_is_readable(tmp_path)
    assert "混进了白名单判据" in reason, reason


def test_delivery_reason_poison_detail_dropped(tmp_path, monkeypatch) -> None:
    """注毒：判死那枚数字又不肯进账（删掉 detail=）⇒ 红在原因/枚数那一行。"""
    source = Path(onebot.__file__).read_text(encoding="utf-8").replace(
        "detail=_onebot_failure_detail", "reason_hint=_onebot_failure_detail"
    )
    monkeypatch.setattr(onebot, "__file__", str(_poisoned_onebot_source(tmp_path, text=source)))
    reason = e2e.check_delivery_failure_reason_is_readable(tmp_path)
    assert "retcode" in reason and reason, reason


def test_delivery_reason_poison_ledger_column_blind(tmp_path, monkeypatch) -> None:
    """注毒：落账腿吃了 `last_error_detail` ⇒ 红在「原因不可读」；
    同时证明判定读的是库里的真值而不是自己传进去的参。"""
    original = send_queue_mod.SQLiteSendRequestQueue._update_part_row

    def blind(self, request_id, part_index, **kwargs):
        kwargs["last_error_detail"] = None
        return original(self, request_id, part_index, **kwargs)

    monkeypatch.setattr(
        send_queue_mod.SQLiteSendRequestQueue, "_update_part_row", blind
    )
    reason = e2e.check_delivery_failure_reason_is_readable(tmp_path)
    assert "原因不可读" in reason, reason


def test_delivery_poison_sent_row_gets_erased(tmp_path, monkeypatch) -> None:
    """注毒：终态改写连带把已送达那行一起擦（＝部分投递被抹掉的原形）⇒ 红。"""
    original = send_queue_mod.SQLiteSendRequestQueue._update_part_row

    def erase(self, request_id, part_index, **kwargs):
        if str(kwargs.get("state")) == send_queue_mod.PART_STATE_FAILED_FINAL:
            for sibling in (0, 1):
                original(self, request_id, sibling, **kwargs)
            return True
        return original(self, request_id, part_index, **kwargs)

    monkeypatch.setattr(
        send_queue_mod.SQLiteSendRequestQueue, "_update_part_row", erase
    )
    reason = e2e.check_delivery_failure_reason_is_readable(tmp_path)
    assert "部分投递被擦成终态" in reason, reason


# ==================================================== 矩阵接线（六项都在盘上）


def test_matrix_registers_all_six_with_expectations(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    by_key = {item.key: item for item in e2e.build_matrix(runtime)}
    missing = [key for key in NARRATION_KEYS if key not in by_key]
    assert not missing, f"验收矩阵缺 ⑱ 那一族: {missing}"
    for key in NARRATION_KEYS:
        item = by_key[key]
        assert item.expect is not None, f"{key} 没有 expect＝哑面（本项目第一假绿形态）"
        assert item.capability_id
        assert item.trigger_text(runtime).strip()
        assert item.note.strip(), f"{key} 缺现网边界说明（requires restart/--execute 写在哪）"
        assert callable(item.build(runtime))


def test_dry_run_of_six_cases_sends_nothing_real(tmp_path) -> None:
    """DRY-RUN 六项：InMemory 队列、零 transport；判定红就是红，不静默跳过。"""
    runtime = _runtime(tmp_path)
    from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger())
    pipeline = e2e.build_pipeline(runtime, queue)
    for index, key in enumerate(NARRATION_KEYS, 1):
        item = next(entry for entry in e2e.build_matrix(runtime) if entry.key == key)
        outcome = e2e.execute_item(
            pipeline=pipeline,
            send_queue=queue,
            item=item,
            runtime=runtime,
            session_type=SessionType.GROUP,
            target_id="555",
            seq=index,
        )
        assert outcome.error == "", outcome.error
        assert outcome.receipt is not None
        assert outcome.receipt.state == ReceiptState.SENT
        assert outcome.receipt.transport == "memory"
        reason = item.expect(outcome) if item.expect is not None else "no expect"
        assert reason == "", f"{key} DRY-RUN 报红：{reason}"
    assert queue.safe_summary()["sent"] == len(NARRATION_KEYS)


def test_harness_file_untouched_by_poisons() -> None:
    """注毒全程只动内存与 %TEMP% 副本：仓库里的验收件逐字节未变。"""
    assert (
        hashlib.sha256(HARNESS_PATH.read_bytes()).hexdigest()
        == HARNESS_SHA_AT_COLLECT
    )
