"""S-META 需求 14/15「开了要对」开态锁（2026-09-28）。

她今晚裁定「一把全开」。既有绿锁大量覆盖的是**关态**（缺省＝逐字节旧行为）
与门身本身的语义；本文件只补开态那一层：**把键真打开之后，行为是不是她要的**。
四条链各自成环，任何一环单独看都可能是绿的：

① 反戳（poke 臂）的可达性判定链：`bot_poke_poke_back` 缺省就是 True，
   但 `can_poke_back = poke_back and poke_back_available and mode == "poke"`，
   而 ``poke`` 只在 **extended** 池里 ⇒ 关态下「回戳键开着却永远不反戳」。
   开态必须真能反戳，且**每戳恰一臂**（回戳绝不叠在话术/图/语音之上）。
   对照半条也要红：把 ``extra_arms`` 打回 False ⇒ 反戳当场不可达。
② 防刷屏三层的「拒绝不扣额度」：冷却/群冷却/概率任一层拒绝时，
   不许在冷却账本上留痕——否则「这次没发」会把下一次本可发的那帧挡在窗外，
   门自己把额度烧光（本仓反复踩过的「拦不住的门反咬后续动作」同族）。
③ 随机发图的反重复窗语义：窗缺省 0＝**整条不重复逻辑不参与**（纯随机、可重发）。
   本文件把「只开派发、不开窗」这个组合的**真实后果**量出来：同一会话
   连续两发可以是同一张图。她要的是「禁止重复发送同一表情包」⇒ 二者必须同开。
④ 开态下贴纸臂仍不得冒头（`sticker_reaction` 是池外行——2026-10-03 已接线、
   但不在 mix 轮换池里），别把「五臂全开」读成「六臂都出来了」。

全部离线：手造图库到 tmp_path、假时钟、SimpleNamespace 配置，零网络零真实目录。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities.poke import (
    PokeDispatcher,
    PokeEvent,
    PokeLimiter,
    poke_mix_pool_arms,
    resolve_poke_reply,
    resolve_poke_reply_mode,
)
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

#: 她点名的五臂（反戳 / LLM 话术 / 语音+文本 / 表情包 / 随机图）。
#: 与 ``tests/test_poke_randpic_behavior.py`` 的 ``FIVE_NAMED_ARMS`` 同一集，
#: 这里独立声明以便本文件单独可跑（两文件互不依赖）。
FIVE_ARMS_FOR_HER_REQUEST: tuple[str, ...] = ("poke", "llm", "voice", "meme", "randpic")

# ---------------------------------------------------------------------------
# 假件
# ---------------------------------------------------------------------------


def _clock(start: float = 1000.0):
    state = {"now": start}

    def tick() -> float:
        return state["now"]

    tick.advance = lambda delta: state.__setitem__("now", state["now"] + delta)  # type: ignore[attr-defined]
    return tick


def _open_config(**overrides):
    """她裁定后的开态配置（三枚键全 True；其余取 config.py 的真身缺省）。"""
    base = {
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
        "bot_poke_affinity_enabled": False,
        "bot_poke_follow_enabled": True,
        "bot_poke_after_reply_enabled": True,
        "bot_quiet_hours_enabled": False,
        "bot_blocked_user_ids": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _event(*, group="42", user="7", target="10000") -> PokeEvent:
    return PokeEvent(target_id=target, user_id=user, group_id=group, sub_type="poke")


# ---------------------------------------------------------------------------
# ① 反戳可达性判定链（开态真能反戳，且恰一臂）
# ---------------------------------------------------------------------------


def test_poke_back_arm_is_reachable_only_in_the_open_state() -> None:
    """关态＝回戳键恒 True 也永不反戳；开态＝真反戳。两半都必须被量出来。

    这条把「判定链」写实，而不是留一句注释：`can_poke_back` 是三个条件的与，
    中间那个 `mode == "poke"` 只有扩臂档才轮得到 ⇒
    「键开了但对不上」的形态恰好藏在两个键的**交叉**处，单键测试看不见。
    """
    closed_modes = {
        PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(user=str(2000 + i)), bot_id="10000", config=_open_config(bot_poke_extra_arms_enabled=False)
        ).mode
        for i in range(400)
    }
    assert "poke" not in closed_modes, "关态居然轮到了 poke 臂＝旧三臂逐字节性被破"

    backs: list[bool] = []
    for i in range(400):
        # 每发一台新分发器：共用一台会命中群冷却（10s 窗）， limiter 直接返回 None，
        # 那样量到的就不是臂而是冷却。
        reaction = PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(user=str(3000 + i)), bot_id="10000", config=_open_config()
        )
        assert reaction is not None
        backs.append(reaction.poke_back)
        # 恰一臂：反戳为真的那一发，正文两腿必须全空。
        if reaction.poke_back:
            assert reaction.mode == "poke"
            text, image = resolve_poke_reply(reaction.mode, fixed_text=reaction.reply)
            assert text == "" and image is None, "反戳叠了第二臂"
    assert any(backs), "键全开后 poke_back 依然恒 False＝反戳这条臂根本没接上"
    assert sum(1 for flag in backs if flag) / len(backs) == pytest.approx(
        1 / len(poke_mix_pool_arms("extended")), abs=0.06
    ), "反戳臂占比明显偏离 1/六臂 ⇒ 池或取模被改写了"


def test_poke_back_needs_the_caller_availability_flag_too() -> None:
    """`poke_back_available=False` 时 poke 臂温和退 fixed，绝不静默空回。"""
    for i in range(400):
        reaction = PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(user=str(4000 + i)),
            bot_id="10000",
            config=_open_config(bot_poke_reply_mode="poke"),
            poke_back_available=False,
        )
        assert reaction is not None
        assert reaction.poke_back is False
        assert reaction.mode == "fixed", reaction.audit_tags
        assert "poke_arm_fallback_no_poke_back" in reaction.audit_tags


def test_the_five_arms_she_named_are_all_reachable_when_keys_are_open() -> None:
    """她点名的五臂（反戳/LLM话术/语音/表情包/随机图）开态全部轮得到。"""
    seen = {
        PokeDispatcher(clock=_clock()).build_poke_reaction(
            _event(user=str(5000 + i)), bot_id="10000", config=_open_config()
        ).mode
        for i in range(1200)
    }
    assert set(FIVE_ARMS_FOR_HER_REQUEST) <= seen, sorted(set(FIVE_ARMS_FOR_HER_REQUEST) - seen)
    # 贴纸臂是池外行（已接线但不经池轮换）⇒ 五臂全开也不许冒头（④）。
    assert "sticker_reaction" not in seen


def test_open_state_pool_prefix_is_ordered_and_stable_where_it_can_be() -> None:
    """扩臂档只在旧三臂**之后追加**：池序前缀逐字节等于关态池。

    写成前缀判据而不是「同桶同值」判据，是因为后者只在 extended 落回前三个
    下标时成立：取模是 ``digest % len(pool)``，3 桶换 6 桶必然重洗一部分桶位
    ——那是扩臂的固有代价，不是缺陷。真正的不变量是**声明序**：旧三臂在前、
    新三臂续后，所以 extended 命中前三位时与 legacy 同值（下面逐桶验）。
    把这一条写歪（例如判「开臂后所有桶都不动」）会当场红，反而掩盖真语义。
    """
    legacy = poke_mix_pool_arms("legacy")
    extended = poke_mix_pool_arms("extended")
    assert extended[: len(legacy)] == legacy, (
        f"扩臂档的前缀被改了：{extended[:len(legacy)]} != {legacy}（追加序＝现网稳定性的全部依据）"
    )
    assert set(extended) - set(legacy) == {"voice", "randpic", "poke"}

    for bucket in range(200):
        closed = resolve_poke_reply_mode(
            configured="mix", group="g", sender="u", bucket=bucket, extra_arms_enabled=False
        )
        opened = resolve_poke_reply_mode(
            configured="mix", group="g", sender="u", bucket=bucket, extra_arms_enabled=True
        )
        if extended.index(opened) < len(legacy):
            assert opened == closed, f"桶 {bucket}：落在旧三臂位上却变了值 {closed}->{opened}"


# ---------------------------------------------------------------------------
# ② 防刷屏三层：任一层拒绝都不许在冷却账本留痕
# ---------------------------------------------------------------------------


def _limiter_event(**fields):
    base = {"notice_type": "notify", "sub_type": "poke", "target_id": 10, "user_id": 20, "group_id": 30}
    base.update(fields)
    return SimpleNamespace(**base)


def test_each_rejection_layer_leaves_the_cooldown_ledger_clean() -> None:
    """目标不符 / 总开关关 / 概率未中 ⇒ 冷却账本必须是空的。

    若哪一层在拒绝时就登记冷却，那「这一发被概率骰子挡下」会把下一发本可放行
    的那帧也一起挡掉——门反咬后续动作，且现象上看起来像「冷却调得太长」。
    """
    clock = _clock()
    event = _limiter_event()

    limiter = PokeLimiter(clock=clock)
    assert limiter.accept(event, "10", enabled=False, cooldown=60, group_cooldown=10) is False
    assert limiter._last == {}, "总开关拒绝却登记了冷却"

    limiter = PokeLimiter(clock=clock)
    other_target = _limiter_event(target_id=99)
    assert limiter.accept(other_target, "10", enabled=True, cooldown=60, group_cooldown=10) is False
    assert limiter._last == {}, "戳的不是我，却登记了冷却"

    # 概率恒不中（0.0 ⇒ digest > 0 恒真；digest==0 的极端指纹除外，故逐层验证）
    limiter = PokeLimiter(clock=clock)
    rejected = [
        limiter.accept(
            _limiter_event(user=user, group_id=group),
            "10",
            enabled=True,
            cooldown=60,
            group_cooldown=10,
            probability=0.0,
        )
        for group in range(40)
        for user in range(40)
    ]
    assert not any(rejected), "概率 0 却放行了"
    assert limiter._last == {}, "概率层拒绝却登记了冷却/滑窗"


def test_passing_layer_is_the_only_one_that_stamps_the_ledger() -> None:
    """放行才登记：第一发放行后同窗第二发被冷却挡住（正向对照，防上面那条空跑）。"""
    clock = _clock()
    limiter = PokeLimiter(clock=clock)
    event = _limiter_event()
    assert limiter.accept(event, "10", enabled=True, cooldown=60, group_cooldown=10) is True
    assert limiter._last, "放行了却没登记＝上面的「拒绝不登记」是空跑"
    assert limiter.accept(event, "10", enabled=True, cooldown=60, group_cooldown=10) is False
    clock.advance(61)
    assert limiter.accept(event, "10", enabled=True, cooldown=60, group_cooldown=10) is True


# ---------------------------------------------------------------------------
# ③ 随机发图反重复窗：只开派发不开窗 ⇒ 同图可重发（这就是缺省 0 的代价）
# ---------------------------------------------------------------------------


def _gallery(root: Path, count: int) -> Path:
    gallery = root / "gallery"
    gallery.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (gallery / f"{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes([index]) * 32)
    return gallery


def _randpic_config(gallery: Path, **overrides):
    base = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [str(gallery)],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_dispatch_enabled": True,  # 开态：她要把主动派发腿打开
        "bot_randpic_no_repeat_window_seconds": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_dispatch_on_with_window_off_can_reissue_the_same_image(
    tmp_path: Path, monkeypatch
) -> None:
    """**开态自检**：派发开了、窗还是 0 ⇒ 同一会话可以连发同一张图。

    图库只有 1 张时最直白：纯随机路每次都只能抽中它，连发五次就是五张同一图。
    这条不是「实现有 bug」，而是把**缺省 0 的真实语义**量成可见事实——
    她要的是「禁止重复发送同一表情包」，只翻 dispatch 不翻窗**达不到她的诉求**。
    """
    gallery = _gallery(tmp_path, 1)
    config = _randpic_config(gallery)
    assert randpic.no_repeat_window_seconds(config) == 0.0
    picks = [
        randpic.pick_gallery_image(config, session_key="group_42_7", seed=f"s{i}")
        for i in range(5)
    ]
    assert all(pick is not None for pick in picks)
    assert len({str(pick) for pick in picks}) == 1, "窗关态居然不重发了"

    # 对照半条：同库同键，把窗翻成正值 ⇒ 第二发必须换张或明确取不出。
    windowed = _randpic_config(gallery, bot_randpic_no_repeat_window_seconds=3600.0)
    fresh = randpic.pick_gallery_image(windowed, session_key="group_42_7", seed="s0")
    assert fresh is not None
    assert randpic._DEFAULT_RECENT_WINDOW.recent_keys(
        "group_42_7", window_seconds=3600.0
    ), "窗开态却没记账 ⇒ 反重复根本没生效"


def test_poke_randpic_arm_and_dispatch_leg_share_one_window(tmp_path: Path) -> None:
    """被戳的 randpic 臂与回复后派发腿**共用同一本窗账**（同会话不各记各的）。

    分账的后果是「刚回复完发过这张，被戳时又发一遍」——她那句话里的「重复」
    不区分触发点，所以三处触发点必须落进同一会话键。
    """
    gallery = _gallery(tmp_path, 6)
    config = _randpic_config(gallery, bot_randpic_no_repeat_window_seconds=3600.0)
    first = randpic.pick_gallery_image_outcome(
        config, session_key="group_42_7", seed="poke:notice:1"
    )
    second = randpic.pick_gallery_image_outcome(
        config, session_key="group_42_7", seed="dispatch:reply:2"
    )
    assert first.path is not None and second.path is not None
    assert str(first.path) != str(second.path), "两条腿各自记账＝同一会话能连发同图"


def test_window_zero_is_by_design_but_must_be_paired_when_dispatch_opens() -> None:
    """结论落盘：缺省 0＝「关＝逐字节旧行为」的**有意设计**，不是遗漏；
    但 ``dispatch=true`` 与「窗留 0」不同开，就等于没满足需求 15(b)。

    两截判据分开锁：

    A. **声明缺省**——派发 False、窗 0.0，按字段名从 ``Config.model_fields`` 读。
       「新行为缺省不发生」这条契约只跟声明走；``.env`` 的合并在根件的
       ``merged_config`` 里做，不该把配置事实混进这把尺。
    B. **配对语义**——``no_repeat_window_seconds`` 只认窗这一枚键、不认派发键，
       所以「只开派发、窗留 0」在代码层**永远不会被自动纠正**：配对只能是配置面
       的钉值，见 _hub 补丁申请。缺省 0 因此是刻意的关态、不是遗漏——但它必须和
       ``dispatch`` 成对出现才达不到她的诉求（上一用例已把「窗 0 可重发」量出来）。
       另给反向半条：窗给正值时取口读到正值，证明 A/B 的红都落在配对上、
       不是取值口坏了。
    """
    from plugins.bot_unified_runtime.config import Config

    assert Config.model_fields["bot_randpic_dispatch_enabled"].default is False, (
        "派发腿的声明缺省被改成 True＝「新行为缺省不发生」这条契约破了"
    )
    assert Config.model_fields["bot_randpic_no_repeat_window_seconds"].default == 0.0, (
        "窗的声明缺省被改＝关态旧行为不再逐字节可证"
    )
    # 把派发翻成开、窗留 0 ⇒ 关态旧语义仍在（纯随机、可重发）：必须被看见的组合。
    # 顺带锁住「取窗口只认窗这一枚键、不认派发键」——正因如此，配对是**配置面**的
    # 责任，代码里没有第二处会替她把窗自动打开（别指望开派发就自动不重发）。
    opened = SimpleNamespace(
        bot_randpic_dispatch_enabled=True, bot_randpic_no_repeat_window_seconds=0.0
    )
    assert randpic.no_repeat_window_seconds(opened) == 0.0, (
        "取窗口读成了别的键＝上面 A/B 两截判据失去同一把尺"
    )

    live = Config().model_copy(update={"bot_randpic_dispatch_enabled": True})
    assert live.bot_randpic_dispatch_enabled is True
    assert randpic.no_repeat_window_seconds(live) == 0.0, (
        "本仓 Config 只带**声明缺省**（.env 合并在根件的 merged_config 里做），"
        "所以「派发开 + 窗 0」这组合在代码层永远不被自动纠正——"
        "配对只能在配置面钉：见 _hub 补丁申请里的 BOT_RANDPIC_NO_REPEAT_WINDOW_SECONDS。"
    )
    # 反向半条：把窗也给正值 ⇒ 组合成立，取口读到的就是正值（证明上面那句红在
    # 「缺省没配对」这件事本身，而不是红在取值口坏了）。
    paired = Config().model_copy(
        update={
            "bot_randpic_dispatch_enabled": True,
            "bot_randpic_no_repeat_window_seconds": 21600.0,
        }
    )
    assert randpic.no_repeat_window_seconds(paired) == 21600.0


# ---------------------------------------------------------------------------
# 内容 sha256 反重复：改名不重算、同字节两张算一张
# ---------------------------------------------------------------------------


def test_content_identity_survives_rename_and_merges_identical_bytes(
    tmp_path: Path,
) -> None:
    """「同一张图」的判据是**内容**，不是路径：改名仍算发过、同字节两路径算一张。"""
    a = tmp_path / "a.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"seed" * 16)
    b = tmp_path / "b.png"
    b.write_bytes(a.read_bytes())
    assert randpic.image_identity(a) == randpic.image_identity(b)
    renamed = tmp_path / "renamed.png"
    a.rename(renamed)
    assert randpic.image_identity(renamed) == randpic.image_identity(b)
    different = tmp_path / "c.png"
    different.write_bytes(b"\x89PNG\r\n\x1a\n" + b"other" * 16)
    assert randpic.image_identity(different) != randpic.image_identity(renamed)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
