"""S-T-RANDPIC-1（2026-09-26）随机发图**出站链**离线回归：能力结果 → 审核 → 渲染 → OneBot 段。

为什么要有这个件（ITEM 15 的第 4 交付）：既有 randpic 测试全停在 ``pick()`` 与
``CapabilityResult`` 形状（``tests/test_randpic_dispatch.py::test_command_result_shape_is_unchanged``
只断到 ``result.images`` 有东西），**没有任何一条锁走过 renderer 与协议段**——
而这条能力最要命的两条口径恰恰长在出站侧：

① 「图本身即表达」⇒ ``title``/``body``/``summary`` 必须留空。渲染层那句
   ``text = safe_text or body or summary or title``（``domains/render/renderer.py:319``）
   是兜底链：只要三格里有字，就会跟图一起变成一条文本段发出去（F5 实弹反馈的原事故）。
② 发出去的路径**此刻必须还在**。``domains/transport/sender/onebot.py`` 的 image 面
   刻意保留死引用透传（``_image_segment``:447-466 —— M-38 收编只给 record/video/file
   三面加了 ``_resolve_local_file_ref`` 闸），所以拦死引用是我们这一层的责任，
   协议端不会替我们拦。

三触发的出站面各锁一次：指令路（``build_randpic_capability``）、被戳 randpic 臂
（``poke.resolve_poke_reply`` → 纯图无文）、回复后主动派发（根装配
``_send_parts_through_unified_pipeline`` 的 ``images=[{"file": image}]`` 形态）。

全离线：图库在 ``tmp_path`` 下造合法 PNG 魔数的小文件；零网络、零真实协议端、
零源码树写入。段构造直接调 ``_segments_from_rendered_output``（出站唯一入口），
不经任何真实 bot。
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    resolve_poke_reply,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _image_segment,
    _segments_from_rendered_output,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _isolate_randpic_state(monkeypatch):
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    monkeypatch.setattr(randpic, "_IDENTITY_CACHE", OrderedDict())
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _gallery(root: Path, count: int) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for index in range(count):
        path = root / f"pic-{index:04d}.png"
        path.write_bytes(PNG_MAGIC + bytes([index % 251]) * (index + 1))
        made.append(path)
    return made


def _config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [],
        "bot_randpic_trigger_words": [],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_no_repeat_window_seconds": 0.0,  # 现网缺省态
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(
    text: str = "随机图", *, session_id: str = "private_7", message_id: str = "m-out-1"
) -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="10000",
        session_id=session_id,
        session_type=SessionType.GROUP if session_id.startswith("group_") else SessionType.PRIVATE,
        sender_id="7",
        plain_text=text,
        message_id=message_id,
    )


def _decision(message: IncomingMessage, scope: SessionType) -> SimpleNamespace:
    """``review_capability_result`` 只认 ``should_respond/target_scope/capability_id`` 三件。"""
    return SimpleNamespace(
        request_id=message.request_id,
        should_respond=True,
        mode="command",
        trigger="随机图",
        capability_id="bot.randpic",
        target_scope=scope,
        decision_reason="test",
    )


def _chain(result: CapabilityResult, scope: SessionType = SessionType.PRIVATE):
    """跑完整出站链：审核 → 渲染 → OneBot 段（与生产同一个入口函数）。"""
    message = _message()
    review = review_capability_result(result, _decision(message, scope))
    rendered = render_reviewed_output(result, review)
    segments = _segments_from_rendered_output(
        content_type=rendered.content_type,
        content_ref=rendered.content_ref,
        text_fallback=rendered.text_fallback,
        request_id=result.request_id,
    )
    return review, rendered, segments


def _types(segments: list[dict]) -> list[str]:
    return [str(segment.get("type")) for segment in segments]


# ============================================================================
# 指令路：图 + 零文案
# ============================================================================


def test_command_path_ships_exactly_one_image_segment_and_no_text(tmp_path: Path) -> None:
    made = _gallery(tmp_path / "gallery", 3)
    config = _config(bot_randpic_dirs=[str(made[0].parent)])
    result = randpic.build_randpic_capability(config)(_message(), None)

    review, rendered, segments = _chain(result)
    assert review.approved is True
    assert _types(segments) == ["image"], f"出站段里混进了别的东西：{segments}"
    assert Path(segments[0]["data"]["file"]) in made
    assert rendered.content_type == "mixed"
    assert rendered.text_fallback == "", "text_fallback 有字＝transport 降级时会把文案单独发一条"


def test_sent_result_leaves_the_whole_caption_chain_empty(tmp_path: Path) -> None:
    """renderer 的兜底链是 ``safe_text or body or summary or title``——四格都得空。

    旧实现只盯着 title/body；``summary`` 一旦被人顺手填了，图就会带一条
    「随机图片」话术出门（F5 实弹反馈的原始形态）。
    """
    made = _gallery(tmp_path / "gallery", 2)
    result = randpic.build_randpic_capability(
        _config(bot_randpic_dirs=[str(made[0].parent)])
    )(_message(), None)
    assert result.title == "" and result.body == "" and result.summary == ""
    assert result.images and len(result.images) == 1


def test_caption_regression_is_caught_by_this_chain(tmp_path: Path) -> None:
    """反向自证：谁把标题填回去，本件的判据必须当场看见多出来的一条文本段。"""
    made = _gallery(tmp_path / "gallery", 1)
    result = randpic.build_randpic_capability(
        _config(bot_randpic_dirs=[str(made[0].parent)])
    )(_message(), None)
    poisoned = result.model_copy(update={"title": "随机图片"})
    _review, _rendered, segments = _chain(poisoned)
    assert _types(segments) == ["image", "text"], (
        "填了标题却没多出文本段 ⇒ 上面那条『无文案』锁是空跑"
    )


# ============================================================================
# 三条触发各自的出站面
# ============================================================================


def test_poke_randpic_arm_ships_image_without_any_text(tmp_path: Path) -> None:
    """被戳臂：``resolve_poke_reply`` 回 ("", path) ⇒ 出站只有一张图。"""
    made = _gallery(tmp_path / "gallery", 1)
    text, image = resolve_poke_reply(
        "randpic", fixed_text="固定话术", randpic_path=str(made[0])
    )
    assert (text, image) == ("", str(made[0]))
    result = CapabilityResult(
        request_id="r-poke",
        capability_id="bot.poke",
        kind="mixed" if image else "text",
        body=text,
        images=[{"file": image}] if image else [],
    )
    _review, _rendered, segments = _chain(result)
    assert _types(segments) == ["image"]


def test_poke_arm_falls_back_to_text_when_the_pool_is_exhausted(tmp_path: Path) -> None:
    """图库空/整库在窗内 ⇒ 臂回退固定话术，不出空件也不静默空回。"""
    text, image = resolve_poke_reply("randpic", fixed_text="固定话术", randpic_path=None)
    assert image is None and text == "固定话术"
    _review, _rendered, segments = _chain(
        CapabilityResult(
            request_id="r-poke-2",
            capability_id="bot.poke",
            kind="text",
            body=text,
        )
    )
    assert _types(segments) == ["text"]


def test_after_reply_dispatch_shape_ships_image_only(tmp_path: Path) -> None:
    """回复后主动派发那条腿的**根侧形态**逐字节复刻（``__init__.py:5275-5285``）。

    本席禁写根文件，所以这里按那段闭包构造同形结果过链；两侧一致性由
    ``test_root_dispatch_shape_still_builds_images_file_only`` 的 AST 锁钉住——
    根侧改了形态，本用例的复刻前提就当场失效（而不是继续绿着测一份假形态）。
    """
    made = _gallery(tmp_path / "gallery", 1)
    image = str(made[0])

    def root_shaped_capability(message: IncomingMessage) -> CapabilityResult:
        text, prefix_parts, audit_tags = "", [], ["randpic", "dispatch", "trigger:after_reply"]
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.randpic",
            kind="mixed" if (image) else "text",
            body=str(text or ""),
            images=[{"file": image}] if image else [],
            audio=[],
            prefix_parts=list(prefix_parts or []),
            audit_tags=list(audit_tags),
        )

    result = root_shaped_capability(_message(session_id="group_42_7"))
    _review, _rendered, segments = _chain(result, SessionType.GROUP)
    assert _types(segments) == ["image"]


def test_group_at_prefix_and_image_coexist_without_caption(tmp_path: Path) -> None:
    """群聊 @ 段（戳一戳 v2 那套 prefix_parts）与图同发，仍不该多出文案段。"""
    made = _gallery(tmp_path / "gallery", 1)
    result = CapabilityResult(
        request_id="r-at",
        capability_id="bot.poke",
        kind="mixed",
        body="",
        images=[{"file": str(made[0])}],
        prefix_parts=[{"type": "at", "qq": "7"}],
    )
    _review, _rendered, segments = _chain(result, SessionType.GROUP)
    assert _types(segments) == ["at", "image"]


# ============================================================================
# 死引用：协议端不替我们拦，必须在这一层拦
# ============================================================================


def test_image_segment_would_pass_a_dead_path_through(tmp_path: Path) -> None:
    """**前提自证**（不是缺陷断言）：出站段构造对 image 面刻意不拦死引用。

    ``onebot._resolve_local_file_ref`` 的 record/video/file 三面有闸，image 面按
    09-15 W1 事故回滚的前提留着透传（report-T100 已登记的偏差）。这条锁的意义是：
    一旦哪天 image 面也装了闸，本用例当场红 ⇒ 逼着下面那条「我们这层拦」的锁重新对账。
    """
    ghost = str(tmp_path / "gallery" / "already-moved.png")
    segment = _image_segment({"type": "image", "file": ghost})
    assert segment == {"type": "image", "data": {"file": ghost}}


def test_capability_never_hands_the_chain_a_dead_path(tmp_path: Path) -> None:
    """TTL 清单里的图被移走 ⇒ 能力必须回诚实降级，而不是把死路径交出去。"""
    made = _gallery(tmp_path / "gallery", 2)
    config = _config(bot_randpic_dirs=[str(made[0].parent)])
    capability = randpic.build_randpic_capability(config)
    assert capability(_message(), None).images  # 先把清单灌进 TTL 缓存
    for path in made:
        path.unlink()
    result = capability(_message(text="来张图", message_id="m-2"), None)
    assert result.images == [], "死引用被交给出站链（image 面不拦，见上一条）"
    assert result.body.strip()
    assert result.send_policy is not SendPolicy.SILENT_AUDIT
    _review, rendered, segments = _chain(result)
    assert _types(segments) == ["text"], f"没货时出站形态不该还是图：{segments}"
    assert rendered.text_fallback.strip(), "降级那句话必须真在 fallback 里（transport 降级也说得清）"


# ============================================================================
# 降级那句话的出站面：它得真能到用户手上
# ============================================================================


def test_degradation_text_reaches_the_user(tmp_path: Path) -> None:
    """旧写法把这句标 ``SILENT_AUDIT``，管线判 SKIPPED ⇒ 文案只存在于源码里。"""
    config = _config(bot_randpic_dirs=[str(tmp_path / "ghost-gallery")])
    result = randpic.build_randpic_capability(config)(_message(), None)
    assert result.send_policy is not SendPolicy.SILENT_AUDIT
    _review, rendered, segments = _chain(result)
    assert _types(segments) == ["text"]
    shipped = str(segments[0]["data"]["text"])
    assert shipped == result.body and "BOT_RANDPIC_DIRS" in shipped


def test_group_degradation_text_is_not_blocked_by_the_reviewer(tmp_path: Path) -> None:
    """降级句里带了本机路径形态 ⇒ 审核面（密钥/路径打码）不该把整条拦死。"""
    config = _config(bot_randpic_dirs=[str(tmp_path / "ghost")])
    result = randpic.build_randpic_capability(config)(
        _message(session_id="group_42_7"), None
    )
    review, _rendered, segments = _chain(result, SessionType.GROUP)
    assert review.approved is True, f"群内降级句被审核拦了：{review.reasons}"
    assert _types(segments) == ["text"]


# ============================================================================
# 根侧形态一致性（只读 AST，禁写根文件）
# ============================================================================


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"


def test_root_dispatch_shape_still_builds_images_file_only() -> None:
    """本件那条「派发腿出站形态」复刻的前提锁：根侧构造仍是 image 单格、body 空。

    根 ``__init__.py`` 属本席禁写面，所以这里只读 AST 确认形态没漂；漂了就红，
    提醒把本件那条复刻用例一起改（「一处变更处处跟随」）。
    """
    import ast

    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    holders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_send_parts_through_unified_pipeline"
    ]
    assert holders, "找不到 _send_parts_through_unified_pipeline ⇒ 出站形态的唯一出处没了"
    body = holders[0]
    images_kw = [
        node
        for node in ast.walk(body)
        if isinstance(node, ast.keyword) and node.arg == "images"
    ]
    assert images_kw, "派发口不再交 images ⇒ 本件的出站复刻用例要一起改"
    rendered = ast.dump(images_kw[0].value)
    assert "'file'" in rendered or '"file"' in rendered, rendered
    closure = next(
        (
            node
            for node in ast.walk(body)
            if isinstance(node, ast.FunctionDef) and node.name == "_capability"
        ),
        None,
    )
    assert closure is not None, "派发口的能力闭包形态变了 ⇒ 复刻前提失效，请同步本件"
    body_kw = [
        node
        for node in ast.walk(closure)
        if isinstance(node, ast.keyword) and node.arg == "body"
    ]
    assert body_kw, "能力闭包不再显式交 body ⇒ 出站文案来源变了，请重新对账"
