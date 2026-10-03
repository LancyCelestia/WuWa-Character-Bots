"""P14 二批 ITEM 14/15：戳一戳**反应矩阵**与随机发图**同图不重复**的实弹回归。

与既有四件 poke 测试的分工（避免重复断言＝避免第二真身）：

- ``tests/test_poke_v2.py``（只读）——形态决策与 @ 段渲染的首批用例；
- ``tests/test_poke_arms_v3.py``（只读）——扩臂档的臂选择确定性与降级链；
- ``tests/test_poke_matrix_v4.py``（只读）——恰一臂 / 禁自激 / 跟戳退路 / 场合门；
- ``tests/test_poke_unified_reaction_b10.py``（只读）——统一分发入口的适配器中立性。

**本件只做那四件都没做的一件事：把「被戳 → 什么反应」当一张表来对账。**
表本体在生产侧 ``domains/chat_reply/capabilities/poke.py`` 的
``_POKE_REACTION_CELLS``（``_POKE_MODES`` 与两枚 mix 池都由它派生），本件的职责是
逐格验证「表上写的」就是「代码做的」：

1. **概率和=1**：池内权重由成员数派生（``poke_mix_pool_weights``），每池求和
   ``pytest.approx(1.0)``；再用 4000 个桶的**经验频率**反证「表说 1/3、代码确实
   取 1/3」。（IEEE 下 ``1/3`` 三枚相加凑不满 1，判据必须用近似，不写死 0.999999。）
2. **降级路径逐格**：每行 ``resource_key`` 以 None/空串/纯空白三种形态落空时，
   都必须落到 ``fallback_arm`` 那一行；``degrade_site`` 声明的那一层真兜得住
   （``resolve_poke_reply`` 与分发器两层分别实测）。
3. **私聊绝不派发 ``set_msg_emoji_like``**：走 reactions 引擎真身 + 记账型 FakeBot，
   群消息正例同批跑一次（否则该锁是空跑）。既有守卫一律不放宽。
4. **随机发图同图不重复**：三触发点（指令 / 回复后 / 被戳）共用
   ``pick_gallery_image`` 这一条读图路径与同一本 ``RecentImageWindow`` 窗账；
   连续抽样断言无重复，窗账的过期与双上限 prune 一并实测。

另有两条**现状刻画用例**（``*_characterization``）钉着本席发现、但改法落在禁写面
的两个真缺陷：被戳路 seed 少一维、私聊会话键形与中央件不一致。它们断言的是「今天
确实这样」，修法落地时必须把期望翻过来，不许改成恒真。

全离线：零网络、零源码树写入（图库一律 ``tmp_path``），不碰真实图库与 Runtime。
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import random
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    _POKE_MIX_POOL_EXTENDED,
    _POKE_MIX_POOL_LEGACY,
    _POKE_MODES,
    DEGRADE_SITES,
    MIX_POOL_IDS,
    POKE_REACTION_MATRIX,
    REACTION_CHANNELS,
    PokeDispatcher,
    PokeEvent,
    poke_mix_pool_arms,
    poke_mix_pool_weights,
    poke_reaction_cells,
    resolve_poke_reply,
    resolve_poke_reply_mode,
    validate_poke_reaction_matrix,
)
from plugins.bot_unified_runtime.domains.core.session_keys import build_session_key
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    _DEFAULT_RECENT_WINDOW,
    RecentImageWindow,
    image_identity,
    pick_fresh_image,
    pick_gallery_image,
)
from plugins.bot_unified_runtime.domains.meme.reactions.engine import (
    ProactiveGate,
    maybe_react_on_message,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins/bot_unified_runtime/__init__.py"
POKE_MODULE = REPO_ROOT / "plugins/bot_unified_runtime" / "domains" / "chat_reply" / "capabilities" / "poke.py"

#: 资源「有」时的样本值（``resolve_poke_reply`` 的形参名 → 值）。
_PRESENT = {
    "llm_text": "嗯？潮声刚好。",
    "meme_path": "x:/meme.png",
    "randpic_path": "x:/pic.png",
}
#: 「落空」的全部形态：逐格都试三种，不只试 None（空串与纯空白曾各自放过一次）。
_ABSENT: tuple[str | None, ...] = (None, "", "   ")
_FIXED_TEXT = "我收到你的轻轻一碰了。"
#: 小数／浮点字面量形态（「矩阵段不许手写权重」那条判据用，见对应用例）。
_DECIMAL_RE = re.compile(r"\d+\.\d+|\.\d+")


# ------------------------------------------------------------------ 公共夹具


def _poke_config(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_poke_enabled": True,
        "bot_poke_private_cooldown_seconds": 30.0,
        "bot_poke_group_cooldown_seconds": 10.0,
        "bot_poke_probability": 1.0,
        "bot_poke_reply_enabled": True,
        "bot_poke_poke_back": True,
        "bot_poke_group_text": "",
        "bot_poke_private_text": "",
        "bot_poke_reply_mode": "mix",
        "bot_poke_extra_arms_enabled": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _event(*, group: str = "42", user: str = "7", target: str = "10000") -> PokeEvent:
    return PokeEvent(target_id=target, user_id=user, group_id=group, sub_type="poke")


def _dispatcher(now: float = 1000.0) -> PokeDispatcher:
    return PokeDispatcher(clock=lambda: now)


class FakeBot:
    """记账型假 bot：``call_api`` 被调了几次、调的是什么，全留在 ``calls`` 里。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    async def call_api(self, api: str, **kwargs):
        self.calls.append((api, kwargs))
        if self.fail:
            raise RuntimeError("platform rejected")


class _ReactionCfg:
    bot_reactions_enabled = True
    bot_reactions_probability = 1.0
    bot_reactions_cooldown_seconds = 0
    bot_reactions_max_per_hour = 20


def _react(session_key: str, *, trigger: str, message_id: int, text: str = "谢谢你帮大忙"):
    """驱动 reactions 引擎真身一次，回 (假 bot, 引擎判定)。"""
    bot = FakeBot()
    verdict = asyncio.run(
        maybe_react_on_message(
            bot,
            session_key=session_key,
            user_message_id=message_id,
            text=text,
            config=_ReactionCfg(),
            trigger=trigger,
            gate=ProactiveGate(),
            bot_related=True,
        )
    )
    return bot, verdict


class _WindowClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, delta: float) -> None:
        self.now += delta


def _write_gallery(root: Path, count: int, *, prefix: str = "pic") -> list[Path]:
    """在 ``tmp_path`` 下建 ``count`` 张**内容互异**的假图（绝不碰真实图库）。"""
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for index in range(count):
        path = root / f"{prefix}-{index}.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + f"seat-poke1-{index}".encode())
        made.append(path)
    return made


def _randpic_config(gallery_dir: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_dirs": [str(gallery_dir)],
        "bot_randpic_no_repeat_window_seconds": 3600.0,
        "bot_randpic_max_file_mb": 0,
        "bot_randpic_trigger_words": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _isolate_default_window():
    """进程级单例窗账逐用例复位，否则本件自己污染自己（``clear()`` 是既有测试口）。"""
    _DEFAULT_RECENT_WINDOW.clear()
    yield
    _DEFAULT_RECENT_WINDOW.clear()


# ============================================================================
# 第〇组：表自洽 + 派生序钉死（改序即改行为，先要有一发字面量锁）
# ============================================================================


def test_matrix_self_check_reports_no_problems() -> None:
    assert validate_poke_reaction_matrix() == ()


def test_derived_pools_are_identical_to_the_legacy_literals() -> None:
    """表派生出的三枚常量必须与 P14 一批的手写字面量**逐字符相等**。

    取模选臂看的是 ``len(pool)`` 与成员序：序一变，同一个 (会话, 戳者, 桶) 就换臂
    ⇒ 这条锁挡的是「把表化顺手改成行为改造」。
    """
    assert _POKE_MODES == ("fixed", "llm", "meme", "voice", "randpic", "poke")
    assert _POKE_MIX_POOL_LEGACY == ("fixed", "llm", "meme")
    assert _POKE_MIX_POOL_EXTENDED == ("fixed", "llm", "meme", "voice", "randpic", "poke")
    assert poke_mix_pool_arms("legacy") == _POKE_MIX_POOL_LEGACY
    assert poke_mix_pool_arms("extended") == _POKE_MIX_POOL_EXTENDED
    assert poke_mix_pool_arms("no-such-pool") == ()


def test_table_and_constants_agree_both_directions() -> None:
    """可点名行 ⇔ ``_POKE_MODES``；池成员 ⇔ 真身池元组（双向，不留孤儿）。"""
    nameable = {cell.arm_id for cell in poke_reaction_cells() if cell.explicit_nameable}
    assert nameable == set(_POKE_MODES)
    for pool in MIX_POOL_IDS:
        declared = {cell.arm_id for cell in poke_reaction_cells() if pool in cell.mix_pools}
        assert declared == set(poke_mix_pool_arms(pool)), f"池 {pool} 有孤儿行"
    in_any_pool = {arm for pool in MIX_POOL_IDS for arm in poke_mix_pool_arms(pool)}
    outside = {cell.arm_id for cell in poke_reaction_cells()} - in_any_pool
    # 池外行只许是「贴纸回应」与「静默」两枚，且都可达但不经池（前者 2026-10-03
    # 已接线：被戳且回复送达后经引擎贴表情；后者由门产生）——这条把「表被悄悄
    # 加行而没人对账」挡在门外。
    assert outside == {"sticker_reaction", "silent"}
    # 取行一律走 ``POKE_REACTION_MATRIX[...]``（缺键即 KeyError 当场炸），不用
    # 回 Optional 的 ``poke_reaction_cell``——后者留给「可能没有这行」的生产侧调用。
    assert POKE_REACTION_MATRIX["sticker_reaction"].wired_in_poke_path is True
    assert POKE_REACTION_MATRIX["silent"].wired_in_poke_path is True


def test_every_cell_field_uses_a_controlled_vocabulary_value() -> None:
    for cell in poke_reaction_cells():
        assert cell.channel in REACTION_CHANNELS, cell.arm_id
        assert cell.degrade_site in DEGRADE_SITES, cell.arm_id
        assert set(cell.mix_pools) <= set(MIX_POOL_IDS), cell.arm_id
        assert cell.label_zh, f"{cell.arm_id} 缺中文标签"


@pytest.mark.parametrize(
    "configured",
    [
        "sticker_reaction", "sticker", "reaction", "emoji", "贴纸回应", "贴表情",
        "silent", "silence", "静默", "none", "", "   ", "MIX", "mix-ish", "poke2",
        "random", "fixed ", " FIXED",
    ],
)
def test_out_of_pool_rows_are_never_selectable(configured: str) -> None:
    """池外两行恒不可达；未知/拼错/越权发明的臂名一律退回 mix 池内。"""
    for bucket in range(40):
        for extra in (False, True):
            got = resolve_poke_reply_mode(
                configured=configured, group="42", sender="7", bucket=bucket,
                extra_arms_enabled=extra,
            )
            pool = _POKE_MIX_POOL_EXTENDED if extra else _POKE_MIX_POOL_LEGACY
            assert got in pool, f"{configured!r} 选出了池外臂 {got}"


# ============================================================================
# 第一组·锁①：每池概率和 = 1（声明侧 + 经验侧同时成立）
# ============================================================================


@pytest.mark.parametrize("pool", MIX_POOL_IDS)
def test_mix_pool_weights_sum_to_one(pool: str) -> None:
    weights = poke_mix_pool_weights(pool)
    assert weights, f"池 {pool} 权重表为空 ⇒ 这条锁是空跑"
    # sum([1/3]*3) 在 IEEE 下凑不满 1，所以判据必须是近似；
    # 写 == 1.0 会假红，写 0.999999 之类的魔数会假绿。
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert len(weights) == len(poke_mix_pool_arms(pool))
    for arm, weight in weights.items():
        assert weight == pytest.approx(1.0 / len(weights)), f"{pool}/{arm} 权重非均匀"


@pytest.mark.parametrize(
    "pool,extra", [("legacy", False), ("extended", True)], ids=["legacy", "extended"]
)
def test_declared_weights_match_observed_frequencies(pool: str, extra: bool) -> None:
    """表上写的权重 = 4000 个桶**实测**出来的频率（±2 个百分点）。

    这才是「单一派生表」的活性判据：只断言 ``sum==1`` 的话，一张跟代码无关的
    表也能全绿。
    """
    weights = poke_mix_pool_weights(pool)
    arms = set(poke_mix_pool_arms(pool))
    counts = dict.fromkeys(arms, 0)
    trials = 4000
    for index in range(trials):
        got = resolve_poke_reply_mode(
            configured="mix",
            group=f"g{index % 97}",
            sender=f"u{index % 89}",
            bucket=index,
            extra_arms_enabled=extra,
        )
        assert got in arms, f"实测选出了池外臂 {got}（表与代码脱钩）"
        counts[got] += 1
    assert set(counts) == arms, "有臂一次都没被选中 ⇒ 该臂权重是空的"
    for arm, expected in weights.items():
        observed = counts[arm] / trials
        assert observed == pytest.approx(expected, abs=0.02), (
            f"{pool}/{arm}: 表={expected:.4f} 实测={observed:.4f}"
        )


@pytest.mark.parametrize("pool", MIX_POOL_IDS)
def test_out_of_pool_rows_carry_zero_weight(pool: str) -> None:
    for arm in ("sticker_reaction", "silent"):
        assert arm not in poke_mix_pool_weights(pool)


# ============================================================================
# 第二组·锁②：降级路径逐格（简报 (b) 项）
# ============================================================================


def test_every_resource_arm_falls_back_to_its_declared_row() -> None:
    """逐格：凡声明 ``resource_key`` 的臂，资源以**任一空形态**出现都落到退路行。"""
    checked = 0
    for cell in poke_reaction_cells():
        if not cell.resource_key:
            continue
        assert cell.fallback_arm, f"{cell.arm_id} 有资源却没登记退路"
        target = POKE_REACTION_MATRIX[cell.fallback_arm]
        assert target.channel == "text", f"{cell.arm_id} 的退路不在文本面"
        for absent in _ABSENT:
            # 逐格构造「本臂资源以这一种空形态落空、其余资源齐备」的参数包。
            kwargs: dict[str, str | None] = {
                key: (absent if key == cell.resource_key else _PRESENT[key])
                for key in _PRESENT
            }
            text, image = resolve_poke_reply(cell.arm_id, fixed_text=_FIXED_TEXT, **kwargs)
            assert text == _FIXED_TEXT and image is None, (
                f"{cell.arm_id} 在 {cell.resource_key}={absent!r} 时没退到固定话术："
                f"{text!r}/{image!r}"
            )
        checked += 1
    assert checked >= 4, f"只检查了 {checked} 格，退路锁退化成空跑"


def test_every_resource_arm_uses_its_own_channel_when_resource_present() -> None:
    """逐格正向：资源齐备时走**本行声明的通道**，不许悄悄退回固定话术。"""
    for cell in poke_reaction_cells():
        if not cell.resource_key:
            continue
        kwargs = {key: _PRESENT[key] for key in _PRESENT}
        text, image = resolve_poke_reply(cell.arm_id, fixed_text=_FIXED_TEXT, **kwargs)
        if cell.channel == "text":
            assert text == _PRESENT["llm_text"] and not image, cell.arm_id
        elif cell.channel == "audio_text":
            assert text and not image, f"{cell.arm_id}: 语音臂必须留文本腿"
        elif cell.channel == "image":
            assert image and not text, f"{cell.arm_id}: 图片臂应纯图不叠字"
        else:
            pytest.fail(f"{cell.arm_id} 声明了本件未覆盖的通道 {cell.channel}")


def test_llm_failure_degrades_to_fixed_text() -> None:
    assert resolve_poke_reply("llm", fixed_text=_FIXED_TEXT, llm_text=None) == (
        _FIXED_TEXT,
        None,
    )


def test_empty_meme_library_degrades_to_fixed_text() -> None:
    assert resolve_poke_reply("meme", fixed_text=_FIXED_TEXT, meme_path=None) == (
        _FIXED_TEXT,
        None,
    )


def test_empty_randpic_gallery_degrades_to_fixed_text() -> None:
    assert resolve_poke_reply("randpic", fixed_text=_FIXED_TEXT, randpic_path=None) == (
        _FIXED_TEXT,
        None,
    )


def test_poke_back_arm_degrades_at_the_dispatcher_layer() -> None:
    """``poke`` 行声明 ``degrade_site="dispatcher"``：落空必须在**选臂层**改判，
    不是到投递层才烂掉（否则会话里什么都没发生，却带着「已回复」的标签）。"""
    cell = POKE_REACTION_MATRIX["poke"]
    assert cell.degrade_site == "dispatcher" and cell.resource_key == ""
    degraded = _dispatcher().build_poke_reaction(
        _event(),
        bot_id="10000",
        config=_poke_config(bot_poke_reply_mode="poke"),
        poke_back_available=False,
    )
    assert degraded is not None and degraded.mode == "fixed"
    assert degraded.reply and not degraded.poke_back
    assert "poke_arm_fallback_no_poke_back" in degraded.audit_tags
    ok = _dispatcher().build_poke_reaction(
        _event(),
        bot_id="10000",
        config=_poke_config(bot_poke_reply_mode="poke"),
        poke_back_available=True,
    )
    assert ok is not None and ok.mode == "poke" and ok.poke_back
    assert resolve_poke_reply("poke", fixed_text=_FIXED_TEXT) == ("", None), (
        "只回戳臂还捎带正文 ⇒ 变两臂"
    )


def test_table_driven_fallback_sites_are_actually_where_the_code_degrades() -> None:
    """退路字段必须与代码里真发生降级的层次一致（在册不执法是本仓明令禁止的形态）。"""
    for cell in poke_reaction_cells():
        if not cell.fallback_arm:
            continue
        kwargs = {key: None for key in _PRESENT}
        text, image = resolve_poke_reply(cell.arm_id, fixed_text=_FIXED_TEXT, **kwargs)
        if cell.degrade_site == "resolve_poke_reply":
            assert (text, image) == (_FIXED_TEXT, None), (
                f"{cell.arm_id}: 表说降级在 resolve 层，实测没兜住"
            )
        else:
            assert cell.degrade_site == "dispatcher", cell.arm_id
            assert (text, image) == ("", None) or not cell.resource_key, cell.arm_id


def test_matrix_arm_never_produces_two_expressions_or_zero() -> None:
    """整表扫：任何一行、任何资源组合都不许出现「两臂」；除 poke 臂外不许「零臂」。

    上界（不许两臂）与 ``test_poke_matrix_v4`` 同判据、这里从表侧再走一遍；
    下界（不许零臂）是本件新加的——poke 臂的零正文由分发器保证，故跳过。
    """
    rng = random.Random(20260925)
    for cell in poke_reaction_cells():
        if cell.arm_id in ("sticker_reaction", "silent"):
            continue
        for _ in range(12):
            kwargs = {
                key: (rng.choice(_ABSENT) if rng.random() < 0.5 else _PRESENT[key])
                for key in _PRESENT
            }
            text, image = resolve_poke_reply(cell.arm_id, fixed_text=_FIXED_TEXT, **kwargs)
            assert not (text and image), f"{cell.arm_id} 同时给了字与图＝两臂：{kwargs}"
            if cell.degrade_site == "dispatcher":
                continue
            assert text or image, f"{cell.arm_id} + {kwargs} 静默无输出"


# ============================================================================
# 第三组·锁③：私聊绝不派发 set_msg_emoji_like（既有守卫不许放宽）
# ============================================================================

#: 生产私聊侧可能出现的键形：中央件裸 uid 形 + 被戳路手拼的 private_ 形 + 空键。
_PRIVATE_KEYS = ("9900", "private_9900", "3865067623", "", "   ")


@pytest.mark.parametrize("trigger", ["emotion_signal", "after_reply"])
@pytest.mark.parametrize("session_key", _PRIVATE_KEYS)
def test_private_session_never_dispatches_set_msg_emoji_like(
    trigger: str, session_key: str
) -> None:
    """QQ 侧不存在私聊表情回应通道（SnowLuma 对非群消息直接抛
    ``not supported on private messages``，实测 36 次）⇒ 修法就是不发。

    守卫位置在 ``maybe_react_on_message`` 的 ``enabled/mid`` 之后、五层门之前，
    所以私聊连「占门」（冷却/滑窗/每消息去重）都不该发生 ⇒ 这里断言的是
    假 bot 的 ``call_api`` **一次都没被调**。
    """
    bot, verdict = _react(
        session_key, trigger=trigger, message_id=8800 + len(session_key)
    )
    assert verdict is False
    assert [call for call in bot.calls if call[0] == "set_msg_emoji_like"] == []
    assert bot.calls == [], f"私聊竟然打到了协议端：{bot.calls}"


def test_group_session_does_dispatch_it_exactly_once() -> None:
    """反向对照：群消息同一套参数必须**真发一发**，否则上面八条是空跑锁。"""
    bot, verdict = _react("group_42_7", trigger="after_reply", message_id=8801)
    assert verdict is True
    assert [name for name, _ in bot.calls] == ["set_msg_emoji_like"]
    assert bot.calls[0][1]["message_id"] == 8801


def test_sticker_reaction_cell_is_wired_and_shares_the_chat_gates() -> None:
    """表上那行 ``sticker_reaction`` 必须与生产实况**同真同假**。

    2026-10-03 互动面波接线后本锁从「未接线」翻成「已接线且受同款防刷门」，
    双向执法不变：AST 现算 poke handler 体内是否真调引擎入口——接了线没改表，
    或改了表没接线，两边都红。「同款防刷门」锁两件：调用交的是 chat 链路同一枚
    共享五层门（``_REACTION_PROACTIVE_GATE``）与 ``after_reply`` 触发点；外围守卫
    只认群（``reaction.group``）且回复真送达（``provider_message_id``）——私聊
    根本不进调用，QQ 无私聊表情通道（台账 #35★），行为层私聊拒发另有第三组 +
    ``tests/test_reactions.py`` 双重锁。
    """
    cell = POKE_REACTION_MATRIX["sticker_reaction"]
    assert cell.channel == "emoji_reaction_api"
    assert cell.mix_pools == () and cell.explicit_nameable is False
    assert cell.wired_in_poke_path is True
    assert not cell.not_wired_reason.strip(), "已接线不许再挂未接线理由"

    handler_names = _poke_handler_names()
    engine_entries = {"maybe_react_on_message", "_maybe_react_on_message", "react_to_message"}
    actually_wired = bool(handler_names & engine_entries)
    assert actually_wired == cell.wired_in_poke_path, (
        f"handler 侧 wired={actually_wired} 而表上={cell.wired_in_poke_path} ⇒ "
        "接了线没改表，或改了表没接线，两者必须同笔"
    )
    facts = _poke_handler_wiring_facts()
    assert facts["gates"] == ["_REACTION_PROACTIVE_GATE"], (
        f"贴纸腿必须走 chat 链路同款五层门，实测 {facts['gates']}"
    )
    assert facts["triggers"] == ["after_reply"], facts["triggers"]
    assert facts["guards"] and any(
        "reaction.group" in guard and "provider_message_id" in guard
        for guard in facts["guards"]
    ), f"群守卫/送达守卫缺席：{facts['guards']}"


def _poke_handler_wiring_facts() -> dict[str, list[str]]:
    """AST 现算 poke handler 里引擎调用的门、触发点与外围守卫（不执行）。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    facts: dict[str, list[str]] = {"gates": [], "triggers": [], "guards": []}
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_handle_poke_notice",
            "_maybe_follow_poke",
        }:
            found = True
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and getattr(sub.func, "id", "") == "_maybe_react_on_message"
                ):
                    for kw in sub.keywords:
                        if kw.arg == "gate" and isinstance(kw.value, ast.Name):
                            facts["gates"].append(kw.value.id)
                        if kw.arg == "trigger" and isinstance(kw.value, ast.Constant):
                            facts["triggers"].append(str(kw.value.value))
                if isinstance(sub, ast.If) and "_maybe_react_on_message" in ast.unparse(sub):
                    facts["guards"].append(ast.unparse(sub.test))
    assert found, "根装配文件里找不到 poke handler ⇒ 本用例判据已失效"
    return facts


def _poke_handler_names() -> set[str]:
    """根 ``__init__.py`` 里 poke 相关 handler 函数体内出现过的名字（AST，不执行）。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    found = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "_handle_poke_notice",
            "_maybe_follow_poke",
        }:
            found = True
            names |= {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
    assert found, "根装配文件里找不到 poke handler ⇒ 本用例判据已失效"
    return names


# ============================================================================
# 第四组·锁④：随机发图三触发点共用历史 + 连续抽样无重复（简报 (c) 项）
# ============================================================================

_WINDOW = 3600.0


def test_three_trigger_points_share_one_ledger_in_group_sessions(tmp_path: Path) -> None:
    """群聊：指令 / 回复后 / 被戳三条路都落到 ``group_<gid>_<uid>`` 同一桶 ⇒
    共用一份「近期已发」。连续 6 次抽样互不重复，第 7 次主动腿拒不发。

    三条路的 session_key/seed 形状**照抄根装配文件现值**（指令与回复后取
    ``message.session_id``，被戳路手拼 ``f"group_{gid}_{uid}"``），因此本用例
    同时是「三处键形对齐」的锁。
    """
    _write_gallery(tmp_path / "gallery", 6)
    config = _randpic_config(tmp_path / "gallery")
    session_key = "group_42_7"
    picked: list[str] = []
    for index in range(6):
        if index % 3 == 0:
            seed, exhausted_ok = f"randpic:{session_key}:m{index}", True       # 指令路
        elif index % 3 == 1:
            seed, exhausted_ok = f"randpic-dispatch:{session_key}:m{index}", False  # 回复后
        else:
            seed, exhausted_ok = "poke-randpic:7:42", False                     # 被戳路
        got = pick_gallery_image(
            config,
            session_key=session_key,
            seed=seed,
            allow_exhausted=exhausted_ok,
        )
        assert got is not None, f"第 {index} 次抽样就发不出 ⇒ 窗账没接住三条路"
        picked.append(image_identity(got))
    assert len(set(picked)) == 6, f"同图重复：{picked}"
    assert _DEFAULT_RECENT_WINDOW.recent_keys(session_key, window_seconds=_WINDOW) == (
        frozenset(picked)
    ), "窗账与实发集合不吻合"
    assert (
        pick_gallery_image(
            config, session_key=session_key, seed="poke-randpic:7:42",
            allow_exhausted=False,
        )
        is None
    ), "整库都在窗内时主动腿还在发 ⇒ 会刷屏"
    # 指令路相反：用户开口要图，绝不因防重复而拒 ⇒ 退「最久没发」那张。
    again = pick_gallery_image(
        config, session_key=session_key, seed="randpic:group_42_7:m99",
        allow_exhausted=True,
    )
    assert again is not None and image_identity(again) == picked[0]


def test_three_trigger_points_in_private_diverge_characterization(tmp_path: Path) -> None:
    """**私聊分桶错位（真洞，本席只锁不修）**。

    中央件私聊键＝**裸 uid**（``domains/core/session_keys.py`` 明写），指令路与
    回复后路都取 ``message.session_id`` ⇒ 桶 ``"9900"``；而被戳路手拼
    ``f"private_{poker_id}"``（根 ``__init__.py:6250-6254`` meme 臂、
    ``:6261-6265`` randpic 臂）⇒ 桶 ``"private_9900"``。两本账互不可见 ⇒
    私聊里「刚回完话发过这张图」，紧接着被戳还会**再发同一张**。

    本用例断言的是**现状**（缺陷事实）。修法是一处表达式换成
    ``build_session_key(poker_group, poker_id)``（属根装配文件＝本席禁写面，
    坐标见 S-T-POKE-1 报告）。落地后请把期望**翻过来**（同桶即命中窗账、
    第二发必为 ``None``），别把它改成恒真。
    """
    _write_gallery(tmp_path / "g", 1)  # 库里只有一张：重复与否最灵敏
    config = _randpic_config(tmp_path / "g")
    chat_side = pick_gallery_image(
        config, session_key="9900", seed="randpic:9900:m1", allow_exhausted=False
    )
    assert chat_side is not None
    poke_side = pick_gallery_image(
        config, session_key="private_9900", seed="poke-randpic:9900:",
        allow_exhausted=False,
    )
    assert poke_side is not None and image_identity(poke_side) == image_identity(chat_side), (
        "私聊两桶已共享同一本账 ⇒ 分桶错位已修；此时把本用例改名，"
        "并把期望改成 poke_side is None"
    )
    # 对照：键形一致时（群里那种同形）窗账立刻生效。
    assert (
        pick_gallery_image(
            config, session_key="9900", seed="poke-randpic:9900:", allow_exhausted=False
        )
        is None
    ), "同桶却还能重复发 ⇒ 窗账本身失效，与键形结论无关"


def test_group_and_private_canonical_keys_differ_by_shape() -> None:
    """把上面的键形差直接用中央件钉一次（不靠测试自己拼字符串）。

    首版本席在这里写错过一条：以为 ``build_session_key("9900", "")`` 也回 ``"9900"``
    ——它回的是 ``group_9900_unknown``（**第一段是群号**，空用户号只兜底成
    ``unknown``）。现算修正后照中央件真身写。
    """
    assert build_session_key("42", "7") == "group_42_7"
    assert build_session_key(42, 7) == "group_42_7"          # int/str 混型同形
    assert build_session_key("", "9900") == "9900"           # 空群号 ⇒ 私聊裸 uid
    assert build_session_key(None, "9900") == "9900"
    assert build_session_key("9900", "") == "group_9900_unknown"  # 空发送者兜底
    # 被戳路手拼的 private_ 形，与中央件私聊形**永不相等** ⇒ 两本账必然分桶。
    assert build_session_key("", "9900") != f"private_{'9900'}"


def test_window_expiry_and_both_caps_prune_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune 策略三重实测：时间窗惰性过期 / 每会话条数上限 / 会话键 LRU 上限。

    这里用注入时钟的窗账直接驱动 ``pick_fresh_image``（``pick_gallery_image`` 走
    进程级单例、拿不到时钟），把「过期后允许再发同一张」钉成可复跑判据。
    """
    _write_gallery(tmp_path / "g", 2)
    dirs = [str(tmp_path / "g")]
    clock = _WindowClock()
    window = RecentImageWindow(clock=clock)

    first = pick_fresh_image(
        dirs, session_key="group_9_9", window=window, window_seconds=_WINDOW,
        seed="a", allow_exhausted=False,
    )
    assert first is not None
    second = pick_fresh_image(
        dirs, session_key="group_9_9", window=window, window_seconds=_WINDOW,
        seed="b", allow_exhausted=False,
    )
    assert second is not None and image_identity(second) != image_identity(first)
    assert (
        pick_fresh_image(
            dirs, session_key="group_9_9", window=window, window_seconds=_WINDOW,
            seed="c", allow_exhausted=False,
        )
        is None
    )
    clock.advance(_WINDOW + 1.0)
    assert window.recent_keys("group_9_9", window_seconds=_WINDOW) == frozenset()
    after_expiry = pick_fresh_image(
        dirs, session_key="group_9_9", window=window, window_seconds=_WINDOW,
        seed="d", allow_exhausted=False,
    )
    assert after_expiry is not None, "过期后仍拒不发 ⇒ 时间窗没真的放行"

    # 每会话条数上限：超出即淘汰最旧（图库很小时也不至于把内存吃穿）。
    monkeypatch.setattr(RecentImageWindow, "_PER_SESSION_CAP", 3)
    bucket = _WindowClock(500.0)
    small = RecentImageWindow(clock=bucket)
    for index in range(5):
        small.record("group_1_1", f"id-{index}", window_seconds=_WINDOW, now=bucket.now)
    assert small.recent_keys("group_1_1", window_seconds=_WINDOW) == frozenset(
        {"id-2", "id-3", "id-4"}
    )
    # 会话键上限：整桶按 LRU 淘汰。
    monkeypatch.setattr(RecentImageWindow, "_SESSION_CAP", 2)
    for index in range(4):
        small.record(f"group_{index}_{index}", "same-id", window_seconds=_WINDOW,
                     now=bucket.now)
    kept = [
        key
        for key in ("group_0_0", "group_1_1", "group_2_2", "group_3_3")
        if small.recent_keys(key, window_seconds=_WINDOW)
    ]
    assert kept[-2:] == ["group_2_2", "group_3_3"], kept
    small.clear()
    assert small.recent_keys("group_1_1", window_seconds=_WINDOW) == frozenset()


def test_blank_session_key_records_nothing(tmp_path: Path) -> None:
    """空会话键不记账（窗账按 key 存，空 key 记账=全会话共享一本假账）。"""
    _write_gallery(tmp_path / "g", 2)
    dirs = [str(tmp_path / "g")]
    window = RecentImageWindow()
    for seed in ("a", "b", "c"):
        pick_fresh_image(
            dirs, session_key="", window=window, window_seconds=_WINDOW,
            seed=seed, allow_exhausted=False,
        )
    assert window.recent_keys("", window_seconds=_WINDOW) == frozenset()


def test_window_off_leaves_the_ledger_completely_untouched(tmp_path: Path) -> None:
    """缺省（窗=0 秒）整条不重复逻辑**不参与** ⇒ 「新行为缺省不发生」可证。

    关态走 ``pick_random_image``（``random.choice``，seed 被忽略），所以这里只能
    断言「窗账一行都没记」，不能断言发的是哪张。
    """
    _write_gallery(tmp_path / "g", 6)
    config = _randpic_config(
        tmp_path / "g", bot_randpic_no_repeat_window_seconds=0.0
    )
    for index in range(6):
        assert pick_gallery_image(config, session_key="group_5_5", seed=f"s{index}")
    assert _DEFAULT_RECENT_WINDOW.recent_keys("group_5_5", window_seconds=0.0) == (
        frozenset()
    )


def test_renamed_image_is_still_the_same_picture(tmp_path: Path) -> None:
    """身份＝内容 SHA-256[:16] 而非路径 ⇒ 用户整理图库（改名/换目录）不清零账。"""
    gallery = tmp_path / "g"
    original = _write_gallery(gallery, 1)[0]
    payload = original.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    assert image_identity(original) == digest
    moved = gallery / "sub" / "改了名字还是它.png"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_bytes(payload)
    assert image_identity(moved) == digest
    assert image_identity("x:/读不到的文件.png") == "x:/读不到的文件.png", (
        "读不出字节时必须退化成路径身份（不抛异常、不返回空串）"
    )


# ============================================================================
# 第五组：(d) 游标归属——「无游标」与「桶粒度」都锁住
# ============================================================================


def test_mode_selection_has_no_process_cursor() -> None:
    """选臂是纯哈希、**不存游标** ⇒ 不存在「重启后从头计数」。

    判据三条：同参数反复调恒等；跨两个全新分发器实例（模拟重启）恒等；
    换时间桶才可能换臂。
    """
    firsts = [
        resolve_poke_reply_mode(
            configured="mix", group="42", sender="7", bucket=123, extra_arms_enabled=True
        )
        for _ in range(50)
    ]
    assert len(set(firsts)) == 1, "同参数结果却变了 ⇒ 某处藏了游标"
    restart_modes: set[str] = set()
    for _ in range(3):
        # 每轮都换一个全新分发器（＝模拟进程重启），形态必须一模一样。
        reaction = _dispatcher(now=1230.001).build_poke_reaction(
            _event(user="7", group="42"), bot_id="10000",
            config=_poke_config(bot_poke_reply_mode="mix"),
        )
        assert reaction is not None
        restart_modes.add(reaction.mode)
    assert len(restart_modes) == 1, f"模拟重启后形态漂移：{restart_modes}"


def test_cursor_ownership_is_per_conversation_and_poker_not_global() -> None:
    """轮换粒度＝(会话, 戳者, 时间桶)，**不是全局**：全局游标会让「谁排到哪一臂」
    取决于别人，与「同戳同果」的审计口径冲突，故必须锁住维度在场。"""
    spread = {
        resolve_poke_reply_mode(
            configured="mix", group=f"g{i % 5}", sender=str(i % 7), bucket=i,
            extra_arms_enabled=True,
        )
        for i in range(300)
    }
    assert len(spread) >= 5, f"取值只覆盖 {len(spread)} 臂 ⇒ 哈希键退化"
    fixed = {
        resolve_poke_reply_mode(
            configured="mix", group="42", sender=str(user), bucket=7,
            extra_arms_enabled=True,
        )
        for user in range(40)
    }
    assert len(fixed) >= 2, "同桶不同戳者却恒同一臂 ⇒ 戳者维没进哈希键"


def test_silent_is_a_door_not_an_arm() -> None:
    """``silent`` 行权重恒 0：静默由**门**产生（总闸/冷却/概率），调池子调不出静默。"""
    assert POKE_REACTION_MATRIX["silent"].channel == "none"
    assert (
        _dispatcher().build_poke_reaction(
            _event(), bot_id="10000", config=_poke_config(bot_poke_probability=0.0)
        )
        is None
    ), "概率 0 还在回复 ⇒ 静默这条门失效"
    assert (
        _dispatcher().build_poke_reaction(
            _event(), bot_id="10000", config=_poke_config(bot_poke_enabled=False)
        )
        is None
    )
    assert (
        _dispatcher().build_poke_reaction(
            _event(), bot_id="10000", config=_poke_config()
        )
        is not None
    ), "反向对照缺失：概率 1 也静默 ⇒ 上面两条是空跑"


def _pick_id(
    dirs: list[str],
    *,
    session_key: str,
    window: RecentImageWindow,
    window_seconds: float,
    seed: str,
    allow_exhausted: bool,
) -> str:
    """取一张并回它的内容身份；取不到就直接红（不把 None 喂给 ``image_identity``）。

    ``image_identity(None)`` 会「诚实」地回字符串 ``"None"``（读不出字节时退化成
    路径身份），于是「根本没取到图」在集合里长成一枚合法身份——本席首版就被它骗过
    一次，``len(picks)==1`` 居然真成立。判据必须先确认拿到了图，再谈是不是同一张。
    """
    got = pick_fresh_image(
        dirs,
        session_key=session_key,
        window=window,
        window_seconds=window_seconds,
        seed=seed,
        allow_exhausted=allow_exhausted,
    )
    assert got is not None, f"取图返回 None（seed={seed}）⇒ 本用例的比较对象不存在"
    return image_identity(got)


def test_poke_randpic_seed_has_no_message_dimension_characterization(tmp_path: Path) -> None:
    """**(d) 现状刻画**：被戳路的 seed 只有 (戳者, 群) 两维。

    根 ``__init__.py:6266`` 传的是 ``f"poke-randpic:{poker_id}:{poker_group}"``，
    不含时间桶/消息 id ⇒ 在「整库都新鲜」的起点上，同一个人同一群每次都落在候选序
    同一格；而窗账是**纯进程内**（无落盘）⇒ 重启即清零。两件事叠起来：每次重启后，
    同一人同一群被戳的第一发恒为同一张图。指令路/回复后路 seed 含 message_id，
    无此性质（同批反向对照）。
    """
    _write_gallery(tmp_path / "g", 6)
    dirs = [str(tmp_path / "g")]
    poke_seed = "poke-randpic:7:42"
    picks = {
        _pick_id(
            dirs,
            session_key="group_42_7",
            window=RecentImageWindow(),  # 每次新窗＝模拟重启
            window_seconds=_WINDOW,
            seed=poke_seed,
            allow_exhausted=False,
        )
        for _ in range(4)
    }
    assert len(picks) == 1, f"被戳路 seed 若含消息维，这里该出现多张：{picks}"
    varied = {
        _pick_id(
            dirs,
            session_key="group_42_7",
            window=RecentImageWindow(),
            window_seconds=_WINDOW,
            seed=f"randpic:group_42_7:m{i}",
            allow_exhausted=False,
        )
        for i in range(6)
    }
    assert len(varied) > 1, "seed 带消息维却仍钉死一张 ⇒ deterministic_choice 退化"


# ============================================================================
# 第六组：需求出口对账 + 防「表上写小数」
# ============================================================================


def test_matrix_channels_cover_the_five_outcomes_the_user_named() -> None:
    """简报点名的「五选一」逐条对到表上的行，一条都不许凭空。

    固定话术 / LLM 话术 / 表情包 = 池内三臂；贴纸回应 = 池外已接线（2026-10-03，
    触发点=被戳且回复送达，仍不经 mix 轮换池）；静默 = 池外经门可达。臂数比五枚
    多是 P14 一批扩的语音/随机图/只回戳，不是本席自造——这张对账单就是给评审看的。
    """
    by_label = {cell.label_zh: cell for cell in poke_reaction_cells()}
    assert set(by_label) >= {"固定话术", "LLM 话术", "表情包", "贴纸回应", "静默"}
    assert by_label["固定话术"].mix_pools == ("legacy", "extended")
    assert by_label["LLM 话术"].resource_key == "llm_text"
    assert by_label["表情包"].resource_key == "meme_path"
    assert by_label["贴纸回应"].wired_in_poke_path is True
    assert by_label["静默"].channel == "none"
    assert {cell.arm_id for cell in poke_reaction_cells() if cell.wired_in_poke_path} >= set(
        _POKE_MODES
    )
    for arm in ("voice", "randpic", "poke"):
        assert POKE_REACTION_MATRIX[arm].mix_pools == ("extended",)


def test_module_reloads_with_identical_derivation() -> None:
    """表在**每次 import** 都必须同形（派生写错序时，两进程会各持一套池）。"""
    import importlib

    module = importlib.import_module(
        "plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke"
    )
    assert module._POKE_MODES == _POKE_MODES
    assert module._POKE_MIX_POOL_LEGACY == _POKE_MIX_POOL_LEGACY
    assert module._POKE_MIX_POOL_EXTENDED == _POKE_MIX_POOL_EXTENDED
    assert module.validate_poke_reaction_matrix() == ()


def test_matrix_weights_are_never_hardcoded_in_the_module() -> None:
    """防「表上写 0.33、代码里取模 3」：矩阵段里不该出现任何小数权重字面量。

    权重唯一算法出口是 ``poke_mix_pool_weights``（成员数派生）。这里直接读源文件
    扫小数形态——比「让评审自己看」便宜且不会腐烂。
    """
    source = POKE_MODULE.read_text(encoding="utf-8-sig")
    body = source.split("REACTION_CHANNELS:", 1)[1].split(
        "def resolve_poke_reply_mode", 1
    )[0]
    # 判据用「矩阵段里出现任何非 1.0 的小数字面量即红」，不是一份黑名单：
    # 首版写成黑名单（0.3/0.33/0.166…），注毒 0.4 当场从缝里漏过去——照实记一笔。
    decimals = {token for token in _DECIMAL_RE.findall(body) if token != "1.0"}
    assert not decimals, f"矩阵段里出现手写权重字面量 {sorted(decimals)}"
    assert "1.0 / len(arms)" in body, "权重必须由成员数派生"


def test_sanity_of_the_seat_own_test_tools() -> None:
    """本件多处依赖注入时钟与假图内容互异性，先自证工具体（防「测夹具不测代码」）。"""
    clock = _WindowClock(100.0)
    assert clock() == 100.0
    clock.advance(50.0)
    assert clock() == 150.0
    assert isinstance(RecentImageWindow(clock=clock), RecentImageWindow)
