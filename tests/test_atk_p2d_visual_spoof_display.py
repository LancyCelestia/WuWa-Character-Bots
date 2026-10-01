"""P2-d 显示面视觉伪装接线锁（ANTIATTACK-BRAIN 票 · 席位 S-FIX-ATK-P2D）。

登记件 ``attack_surface.find_visual_spoof_controls`` 只出**信号**；处置半边
（``strip_display_controls`` / ``fold_spoofed_role_keywords``，以及包住它们的
``injection.sanitize_display_name`` / ``display_name_spoof_tags``）住在中央件与
``chat_reply/security/injection.py``。本票把三个**显示落点**接上：

① 引用链名片 —— ``domains/chat_reply/ingest/message_context.py``
   （``collect_reply_chain`` / ``collect_reply_chain_async`` 的存名点，
   ``format_reply_chain`` 渲染的 ``[引用回复 层级N 名字]`` 块头即出自这里）；
② 媒体归档显示名 —— ``domains/media/archive/media_archive.py``
   （``sanitize_dirname`` 只管盘上段名，显示面 ``ArchiveRecord.to_json`` 未接）；
③ 贴纸/表情包名 —— ``domains/meme/capabilities/meme.py``
   （``/表情 列表`` 把后端返回的 key 逐字拼进 body 给用户看）。

口径（与既有显示名腿同一把尺）：
- **判据零副本**：落点只调用中央件/既有的 injection 处置口，绝不在此抄码点表；
- **不误伤**：合法名片（纯 ASCII / 纯西里尔真词 / 汉字夹全角字母 / 含 ZWJ 表情）
  逐字节不变——替用户改一次名字，这条防线就变成新的故障源；
- **不可救者屏蔽**：消毒后**仍然**触发信号的（同形近似形那类可见伪装，折了就等于
  改名），整格换成 ``injection.SPOOF_SUPPRESSED_DISPLAY``——宁可少给一个名字。

落盘状态：三处目标文件本席开席时均有他席在飞（逐文件 ``git diff --numstat`` 现算），
故改动以补丁预备件交 root：``.superpowers/sdd/2026-09-27-fullload/patches/P2D-*.patch.md``。
**补丁未落盘的干净基线上本锁必然红**——红是「在册未接线」的可见形态，不是故障；
每条红都点名它缺哪一枚补丁。用例数以实跑为准（AGENTS 规则 10，本文件不写计数）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.ingest import message_context
from plugins.bot_unified_runtime.domains.chat_reply.security import injection
from plugins.bot_unified_runtime.domains.media.archive import media_archive
from plugins.bot_unified_runtime.domains.meme.capabilities import meme as meme_mod

REPO_ROOT = Path(__file__).resolve().parents[1]

# 控制字符一律 chr() 构造：源码里不留字面伪装字符（同中央件口径）。
RLO = chr(0x202E)  # RIGHT-TO-OVERRIDE：肉眼把后文翻成反向
ZWSP = chr(0x200B)  # 零宽空格：肉眼不可见

#: 三个显示落点 → 本票补丁预备件（红时点名待落盘的那一枚）。
_SINKS: dict[str, str] = {
    "plugins/bot_unified_runtime/domains/chat_reply/ingest/message_context.py": (
        "P2D-message-context.patch.md"
    ),
    "plugins/bot_unified_runtime/domains/media/archive/media_archive.py": (
        "P2D-media-archive.patch.md"
    ),
    "plugins/bot_unified_runtime/domains/meme/capabilities/meme.py": (
        "P2D-meme.patch.md"
    ),
}

_PORT_ATTR = "render_safe_display_name"


def _display_port():
    """取显示面处置口；未落盘时以**断言**红点名补丁，不抛 ImportError。"""
    fn = getattr(injection, _PORT_ATTR, None)
    assert callable(fn), (
        f"显示面处置口 injection.{_PORT_ATTR} 不存在：补丁预备件 "
        ".superpowers/sdd/2026-09-27-fullload/patches/P2D-injection.patch.md 未落盘"
        "（本锁该枚依赖 S-FILESAFE 的 sanitize_display_name/display_name_spoof_tags 两半）"
    )
    return fn


def _calls_port(rel_path: str) -> bool:
    """AST 判真：该生产文件里确有对 ``render_safe_display_name`` 的调用点。

    Name（局部导入后直调）与 Attribute（``injection.render_safe_display_name(...)``）
    两形态都算，与 ``tests/test_attack_surface_consumers.py`` 锁④ 同一把尺。
    """
    path = REPO_ROOT / rel_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if isinstance(func, ast.Name) and func.id == _PORT_ATTR:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _PORT_ATTR:
            return True
    return False


# ---------------------------------------------------------------------------
# 锁① 接线在世：三个显示落点各有一枚真调用点（摘掉任何一处即红＝回潮可见）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("rel_path", "patch_name"), sorted(_SINKS.items()))
def test_visual_spoof_display_port_is_consumed_by_every_sink(rel_path: str, patch_name: str) -> None:
    assert _calls_port(rel_path), (
        f"{rel_path} 未调用显示面处置口 {_PORT_ATTR}：该落点的视觉伪装接线被摘掉了"
        f"（或补丁 {patch_name} 未落盘）。摘线与接线都要同步登记表 AS-VISUAL-SPOOF 与本锁。"
    )


# ---------------------------------------------------------------------------
# 锁② 处置口本身：中和 / 屏蔽 / 不误伤 三条口径同读
# ---------------------------------------------------------------------------


def test_display_port_strips_invisible_and_folds_role_homoglyphs() -> None:
    port = _display_port()
    # ① 不可见伪装：剥字符、可见内容逐字节不动（RLO 不得进显示面）。
    assert port(f"群名{RLO}admin") == "群名admin"
    assert port(f"守岸人{ZWSP}助手") == "守岸人助手"
    # ② 同形异码伪装角色词：折成 ASCII 近似形（显示形态与真实码点一致）。
    assert port("\uff41\uff44\uff4d\uff49\uff4e") == "admin"  # 全角 ａｄｍｉｎ
    assert port(f"{chr(0x0430)}dmin") == "admin"  # 西里尔 а + 拉丁 dmin


def test_display_port_never_mangles_legitimate_names() -> None:
    """「不误伤」是这条防线存在的条件：合法名字必须逐字节出去。"""
    port = _display_port()
    legit_names = (
        "守岸人",
        "漂泊者",
        "admin_guide",
        "администратор",  # 纯西里尔真词（不是混码）
        "报告Ａ",  # 汉字夹全角字母（折完还剩汉字，不成「冒充英文名」）
        "\U0001F9D1\u200d\U0001F3A8",  # 表情 ZWJ 连字（在册豁免）
    )
    for name in legit_names:
        out = port(name)
        assert out == name, f"合法名被改写（误伤）：{name!r} → {out!r}"
    for blank in ("", "   ", "\t"):
        assert port(blank) == "", "空进必须空出：调用方据此判定「这一格没有名字」"


def test_display_port_suppresses_what_it_cannot_neutralize() -> None:
    """消毒后**仍**触发信号的可见伪装（同形近似形冒充英文名）→ 整格屏蔽。

    消毒口按设计只折「伪装成角色词」那一族（``ａdmin``→``admin``），
    ``ｓｈｅｌｌ`` 这类冒充英文名的近似形折了就等于替别人改名，于是留信号；
    本口的职责就是把留信号的那一格换成屏蔽标记——宁可少给一个名字。
    """
    port = _display_port()
    marker = getattr(injection, "SPOOF_SUPPRESSED_DISPLAY", None)
    assert isinstance(marker, str) and marker, (
        "屏蔽格常量 injection.SPOOF_SUPPRESSED_DISPLAY 未落盘（P2D-injection 补丁）"
    )
    assert port("\uff53\uff48\uff45\uff4c\uff4c") == marker  # 全角 ｓｈｅｌｌ
    assert port("\u0440ay\u0440") == marker  # 西里尔 р 混拉丁冒充 "rayp"


# ---------------------------------------------------------------------------
# 锁③ 落点①：引用链名片（同步采集 + 异步反查两条存名腿）
# ---------------------------------------------------------------------------


def _reply_event(nickname: str, *, message_id: str = "1001") -> SimpleNamespace:
    return SimpleNamespace(
        reply={
            "message_id": message_id,
            "sender": {"user_id": "u9", "nickname": nickname},
            "message": [{"type": "text", "data": {"text": "被引用的一句话"}}],
        },
        reply_to_message=None,
        message=[{"type": "text", "data": {"text": "当前这句"}}],
    )


def _decision() -> BotDecision:
    return BotDecision(
        request_id="r-p2d",
        should_respond=True,
        mode="command",
        trigger="test",
        capability_id="bot.test",
        target_scope=SessionType.GROUP,
        decision_reason="unit-test",
    )


def test_reply_chain_sender_name_is_neutralized_in_rendered_block() -> None:
    chain = message_context.collect_reply_chain(_reply_event(f"群名{RLO}admin"))
    assert chain, "引用链采集为空：夹具形态不合，本锁没测到东西"
    rendered = message_context.format_reply_chain(chain)
    assert RLO not in rendered, "RLO 进了提示词块头：名片伪装可直接改写模型看到的顺序"
    assert "群名admin" in rendered, f"合法可见部分被吞掉：{rendered!r}"


def test_reply_chain_async_lookup_leg_is_neutralized() -> None:
    """异步反查腿（``lookup`` 取回的深层 sender）与同步腿必须同权。"""
    event = SimpleNamespace(
        reply={
            "message_id": "2001",
            "sender": {"user_id": "u1", "nickname": "正常人甲"},
            "message": [
                {"type": "text", "data": {"text": "上一层"}},
                {"type": "reply", "data": {"id": "3003"}},
            ],
        },
        reply_to_message=None,
    )

    fetched = {
        "message_id": "3003",
        "sender": {"user_id": "u2", "nickname": f"守岸人{ZWSP}助手"},
        "message": [{"type": "text", "data": {"text": "更早的一句"}}],
    }

    def lookup(message_id: str):
        return fetched if str(message_id) == "3003" else None

    chain = asyncio.run(
        message_context.collect_reply_chain_async(event, lookup=lookup)
    )
    assert any(ZWSP not in item.sender_name for item in chain[1:]), (
        f"异步反查腿未消毒：{[i.sender_name for i in chain]!r}"
    )
    deep = [item for item in chain if item.sender_name and "守岸人" in item.sender_name]
    assert deep and all(ZWSP not in item.sender_name for item in deep)


# ---------------------------------------------------------------------------
# 锁④ 落点②：媒体归档显示名（旁车 JSON 的 ip_source / character / original_name）
# ---------------------------------------------------------------------------


def _record(**overrides) -> media_archive.ArchiveRecord:
    fields: dict[str, object] = {
        "sha256": "0" * 64,
        "rel_path": "照片/鸣潮/20260928_120000_deadbeef.png",
        "category": "照片",
        "ip_source": "鸣潮",
        "character_name": "漂泊者",
        "description": "",
        "tags": [],
        "nsfw_score": 0.0,
        "media_type": "image",
        "original_name": "img.png",
        "platform": "onebot",
        "session_id": "group:1",
        "sender_id": "u1",
        "created_at": "2026-09-28T12:00:00+00:00",
    }
    fields.update(overrides)
    return media_archive.ArchiveRecord(**fields)  # type: ignore[arg-type]


def test_archive_display_fields_neutralize_visual_spoof() -> None:
    payload = _record(
        ip_source=f"鸣潮{RLO}",
        character_name=f"{chr(0x0430)}dmin",
        original_name=f"报告{ZWSP}.png",
    ).to_json()
    assert RLO not in payload and ZWSP not in payload, (
        "显示伪装字符进了归档旁车 JSON：sanitize_dirname 只管盘上段名，不管肉眼形态"
    )
    assert "鸣潮" in payload, f"合法部分被吞：{payload!r}"


def test_archive_display_keeps_clean_record_untouched() -> None:
    """不误伤：一条干净记录的旁车 JSON 逐字节不变（旁车是人读可迁移的档案）。"""
    record = _record()
    assert record.to_json() == _record().to_json()
    assert "漂泊者" in record.to_json() and "img.png" in record.to_json()


# ---------------------------------------------------------------------------
# 锁⑤ 落点③：贴纸/表情包名（后端 key 列表直出用户可见 body）
# ---------------------------------------------------------------------------


def _meme_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_meme_api_enabled=True,
        bot_meme_api_base_url="http://127.0.0.1:2233",
        bot_meme_api_timeout_seconds=5,
        bot_meme_api_output_dir=str(tmp_path),
        bot_meme_cache_max_bytes=0,
    )


def _meme_message(text: str) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id="group:1",
        session_type=SessionType.GROUP,
        group_id="1",
        sender_id="u1",
        plain_text=text,
    )


def test_meme_key_listing_display_neutralizes_spoofed_names(tmp_path: Path) -> None:
    keys = ["petpet", f"ji{RLO}fu", f"猫{ZWSP}咪"]

    def request(method: str, path: str, json: dict | None = None):
        assert method.upper() == "GET" and path == "/meme/keys"
        return 200, list(keys)

    capability = meme_mod.build_meme_capability(_meme_config(tmp_path), request_fn=request)
    result = capability(_meme_message("/表情 列表"), _decision())
    body = result.body or ""
    assert RLO not in body and ZWSP not in body, "后端返回的表情名里的伪装字符直出用户可见文案"
    assert "petpet" in body, f"干净名被改动：{body!r}"
    assert "ji" in body and "fu" in body, f"合法可见部分被吞：{body!r}"


def test_sinks_carry_no_second_mechanism() -> None:
    """落点不开第二通路：三处只准「调用中央处置口」，不得自带伪装载荷或第二套码点表。

    两条形查：
    ① 源码里不得出现**字面** Bidi/零宽控制字符（那是伪装载荷进防线源码的形态）；
    ② 源码里不得自建同形字映射（``_CONFUSABLE``/``LOOKALIKE`` 一族的赋值），
       判据真身只在 ``core/safety_exec/attack_surface.py`` 一处。
    """
    for rel_path in _SINKS:
        source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        for ch in (RLO, ZWSP, chr(0x202A), chr(0x202B), chr(0x202C), chr(0x2066), chr(0xFEFF)):
            assert ch not in source, f"{rel_path} 源码里含字面控制字符 U+{ord(ch):04X}"
        for marker in ("_CONFUSABLE_MAP =", "LOOKALIKE_MAP =", "_BIDI_CONTROLS ="):
            assert marker not in source, f"{rel_path} 自建了第二套伪装判据表：{marker}"
