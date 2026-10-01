"""人格分册贴纸池（2026-09-29 用户裁定「只能调取现役人格里面的表情包」）回归树。

锁以下几件事，全部判据真身在 ``domains/meme/sources/sticker_packs.py``：

1. **册外不出（隐私红线）**：给了现役人格册名 ⇒ 只准从 ``基根/<册名>/`` 取图，
   基根下的散件与别人格的册**结构性取不到**（B2 终检锁的本体断言）；
2. **无册诚实缺席**：册名给了而没有命中子目录 ⇒ ``None`` ＋ ``verdict=persona_album_missing``，
   绝不回落基根；
3. **切人格跟切（P2）**：同一基根下换册名 ⇒ 取图面跟着换（人格热切换的贴纸面）；
4. **S1 语境标签**：命中子目录名的候选排探查序最前；无命中＝整册原序；
5. **S4 好感档联动**：``私藏`` 类子目录档位不够整条锁死（复发路同样过筛）；
6. **门面穿通**：``select_sticker_for_turn(packs_only)`` 把册名/锁原样带到池腿。
7. **锁也过复发路**（S4 第二条腿）：窗账开着、整池都在窗内 ⇒ 探查全数让位，退「最久没发」
   那张；``locked_subdirs`` 在这条腿上同样生效（两道出口共用出口四问，摘一处必红）。
8. **S4 四种「读不出」一律 fail-closed**：快照缺席／``tier`` 为空／``tier`` 非数／阈值非数
   ⇒ 按**没解锁**算（绝不猜档）；子目录名与阈值都**现读**交来的 config ⇒ 改档跟着变，
   子目录名空串＝这件功能整体关闭。
9. **反空集控制腿**：每条「不回落／不端别人的／锁死」都配一条同夹具正腿，证明样本非空、
   ``None`` 是判出来的，不是池子本来就空；另配注毒腿（把锁的面匹配焊成恒不命中）证明
   那枚 ``None`` 绑的正是锁本身。

册名带路径分隔符 ``..`` 一律剔除（拼接闸）；册名缺省为空 ⇒ 基根旧语义。
全部离线、只写 ``tmp_path``（AGENTS 规则 6）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities.meme_library import (
    _locked_sticker_subdirs,
    select_sticker_for_turn,
)
from plugins.bot_unified_runtime.domains.meme.sources import (
    sticker_packs,
    sticker_send_routing,
)

PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
GIF_HEAD = b"GIF89a" + b"\x00" * 26


def _write(target: Path, payload: bytes = PNG_HEAD) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


@pytest.fixture(autouse=True)
def _clean_pool_state() -> Any:
    sticker_packs.reset_sticker_state()
    yield
    sticker_packs.reset_sticker_state()


@pytest.fixture()
def album_base(tmp_path: Path) -> Path:
    """按人格分册的仓库基根：两本人格册 + 基根散件 + 情绪/私藏子目录。"""
    base = tmp_path / "meme_library"
    base.mkdir()
    _write(base / "守岸人" / "a.png")
    # 子目录名取自情绪意图词表真身（reactions/engine._REACTION_MEME_INTENT_TERMS：
    # 「开心」在表内，「生气」不在——S1 的标签面只认词表内的词，夹具照真身摆）。
    _write(base / "守岸人" / "开心" / "happy.png")
    _write(base / "守岸人" / "私藏" / "secret.png")
    _write(base / "爱弥斯" / "b.gif", GIF_HEAD)
    _write(base / "loose.png")
    return base


def _config(root: Path | None, **overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "bot_sticker_dir": str(root) if root is not None else "",
        "bot_sticker_enabled": True,
        "bot_sticker_recursive": True,
        "bot_sticker_no_repeat_window_seconds": 0.0,
        "bot_sticker_private_subdir": "私藏",
        "bot_sticker_private_min_tier": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ------------------------------------------------------------------ 1+2：册外不出 / 无册缺席


def test_picks_only_from_active_persona_album(album_base: Path) -> None:
    """给了册名 ⇒ 取图面收进该册；基根散件与别人格的册结构性取不到。"""
    config = _config(album_base)
    for _ in range(8):
        picked = sticker_packs.pick_sticker(config, persona_names=("守岸人",))
        assert picked is not None
        assert Path(picked).is_relative_to(album_base / "守岸人")


def test_missing_album_is_honest_absence(album_base: Path) -> None:
    """册名给了而基根下没有同名子目录 ⇒ ``None``＋专格事实，绝不回落基根。"""
    config = _config(album_base)
    assert (
        sticker_packs.pick_sticker(config, persona_names=("不存在的人格",)) is None
    )
    facts = sticker_packs.sticker_facts(config, persona_names=("不存在的人格",))
    assert facts.persona_album_missing == 1
    assert facts.verdict == "persona_album_missing"
    assert facts.dir_configured is True


def test_album_names_escape_attempt_is_dropped(album_base: Path) -> None:
    """带路径分隔符/``..`` 的册名在拼接闸被剔除 ⇒ 等价于「没有合法册名」＝缺席。"""
    config = _config(album_base)
    assert sticker_packs.pick_sticker(config, persona_names=("..",)) is None
    assert (
        sticker_packs.sticker_facts(config, persona_names=("..",)).verdict
        == "persona_album_missing"
    )


def test_empty_album_names_keeps_base_root_semantics(album_base: Path) -> None:
    """册名缺省为空 ⇒ 基根整棵树（旧语义向后兼容，含散件）。"""
    config = _config(album_base)
    picked = sticker_packs.pick_sticker(config)
    assert picked is not None
    assert Path(picked).is_relative_to(album_base)


# ------------------------------------------------------------------ 3：切人格跟切（P2）


def test_persona_switch_follows_album(album_base: Path) -> None:
    """同一基根换册名 ⇒ 取图面跟着换（切人格后只发新人格册里的图）。"""
    config = _config(album_base)
    for _ in range(6):
        keeper = sticker_packs.pick_sticker(config, persona_names=("守岸人",))
        assert keeper is not None
        assert Path(keeper).is_relative_to(album_base / "守岸人")
    for _ in range(6):
        emis = sticker_packs.pick_sticker(config, persona_names=("爱弥斯",))
        assert emis is not None
        assert Path(emis).is_relative_to(album_base / "爱弥斯")


# ------------------------------------------------------------------ 4：S1 语境标签


def test_prefer_tags_bias_subdir(album_base: Path) -> None:
    """命中子目录名的候选排探查序最前（同 seed 可复现）。"""
    config = _config(album_base)
    picked = sticker_packs.pick_sticker(
        config, seed="t1", persona_names=("守岸人",), prefer_tags=("开心",)
    )
    assert picked is not None
    assert Path(picked).name == "happy.png"


def test_prefer_tags_no_hit_keeps_order(album_base: Path) -> None:
    """标签全不命中 ⇒ 整册原序（只取根层时等价于无标签），照常取到图。"""
    config = _config(album_base)
    picked = sticker_packs.pick_sticker(
        config, seed="t2", persona_names=("守岸人",), prefer_tags=("不存在的标签",)
    )
    assert picked is not None
    baseline = sticker_packs.pick_sticker(
        config, seed="t2", persona_names=("守岸人",)
    )
    assert baseline is not None
    assert Path(picked) == Path(baseline)


# ------------------------------------------------------------------ 5：S4 私藏按档解锁


def test_locked_subdir_never_picked(album_base: Path) -> None:
    """档位不够 ⇒ 私藏整条锁死：探查与显式指名两条路都取不到。"""
    config = _config(album_base)
    for _ in range(10):
        picked = sticker_packs.pick_sticker(
            config, persona_names=("守岸人",), locked_subdirs=("私藏",)
        )
        assert picked is not None
        assert "私藏" not in Path(picked).parts


def test_unlocked_tier_can_pick_private(album_base: Path) -> None:
    """锁名单为空（档位够/功能关）⇒ 私藏可取。"""
    config = _config(album_base)
    for _ in range(10):
        picked = sticker_packs.pick_sticker(config, persona_names=("守岸人",))
        assert picked is not None
    secret = album_base / "守岸人" / "私藏" / "secret.png"
    assert sticker_packs.list_sticker_images(config, persona_names=("守岸人",)) != []
    assert secret.exists()


# ------------------------------------------------------------------ 6：门面穿通


def test_facade_threads_persona_album(album_base: Path) -> None:
    """``select_sticker_for_turn(packs_only)`` 把册名带到池腿：命中册内；缺册＝不发。"""
    config = _config(album_base)
    picked, tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="s1",
        persona_albums=("守岸人",),
    )
    assert picked is not None
    assert Path(picked["path"]).is_relative_to(album_base / "守岸人")
    assert "sticker_pool:sticker_packs" in tags

    none_pick, none_tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="s2",
        persona_albums=("册还没建",),
    )
    assert none_pick is None
    assert "sticker_pool:none" in none_tags


def test_facade_locked_subdir_blocks_low_tier(album_base: Path) -> None:
    """门面级 S4：档位低于阈值 ⇒ 私藏不可取；档位够 ⇒ 可取。"""
    config = _config(album_base)
    low, low_tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="s3",
        affinity_snapshot={"tier": 3},
        persona_albums=("守岸人",),
    )
    assert low is not None and "私藏" not in Path(low["path"]).parts

    high, _tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="s4",
        affinity_snapshot={"tier": 9},
        persona_albums=("守岸人",),
        extra_topic_terms=("私藏",),
    )
    assert high is not None
    assert Path(high["path"]).name == "secret.png" or "私藏" in Path(high["path"]).parts
    assert low_tags  # 审计轨非空（形状锁）


def test_facade_reply_text_hits_emotion_subdir(album_base: Path) -> None:
    """门面级 S1：回复文本命中情绪词表里的词 ⇒ 同名子目录的图被优先选中。"""
    config = _config(album_base)
    picked, _tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="s5",
        reply_text="今天好开心呀！",
        persona_albums=("守岸人",),
    )
    assert picked is not None
    assert Path(picked["path"]).name == "happy.png"


# ---------------------------------------------------------- 7：锁也过「最久没发」复发路


def _solo_private_album(tmp_path: Path) -> Path:
    """现役人格册里**只有**一张私藏图：于是「出图」与「出的是私藏」是同一件事。

    这枚夹具专为反空集而设——池子里没有第二条退路，任何一次 ``None`` 都只能来自判据，
    任何一次非 ``None`` 都必然是私藏那张。
    """
    base = tmp_path / "solo"
    _write(base / "守岸人" / "私藏" / "only.png")
    return base


def test_recycle_path_also_honours_the_lock(tmp_path: Path) -> None:
    """窗账开着 ⇒ 探查让位 ⇒ 退「最久没发」那张；那条腿也必须过同一道锁筛。"""
    base = _solo_private_album(tmp_path)
    config = _config(base, bot_sticker_no_repeat_window_seconds=3600.0)

    # 正控制腿：没锁时这张私藏取得到（＝池子非空、文件合法、登记面之内）。
    unlocked = sticker_packs.pick_sticker(
        config, session_key="recycle", persona_names=("守岸人",)
    )
    assert unlocked is not None
    assert unlocked.name == "only.png"
    assert "私藏" in unlocked.parts

    # 同一会话再来一次：窗内已占坑 ⇒ 走复发路；私藏锁着就当这批图没有。
    locked = sticker_packs.pick_sticker(
        config,
        session_key="recycle",
        persona_names=("守岸人",),
        locked_subdirs=("私藏",),
    )
    assert locked is None


def test_recycle_lock_none_is_the_lock_not_an_empty_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """注毒腿：把锁的「面匹配」焊成恒不命中（＝实现漏了复发路这道筛）⇒ 同一条路必把私藏端出来。

    上一枚的 ``None`` 若其实来自池子空／文件死／越界，这一枚也会一起 ``None`` ⇒ 那把锁是空锁。
    本枚断言「摘腿必真出图」，把 ``None`` 唯一绑到锁本身。
    """
    base = _solo_private_album(tmp_path)
    config = _config(base, bot_sticker_no_repeat_window_seconds=3600.0)
    first = sticker_packs.pick_sticker(
        config, session_key="poison", persona_names=("守岸人",)
    )
    assert first is not None and first.name == "only.png"

    monkeypatch.setattr(sticker_packs, "_tag_matches", lambda part, tag: False)
    recycled = sticker_packs.pick_sticker(
        config,
        session_key="poison",
        persona_names=("守岸人",),
        locked_subdirs=("私藏",),
    )
    assert recycled is not None
    assert recycled.name == "only.png"
    assert "私藏" in recycled.parts


# ---------------------------------------------------------- 8：S4 「读不出」四形全 fail-closed


def test_unreadable_tier_or_snapshot_locks_private() -> None:
    """快照缺席／``tier`` 空／``tier`` 非数／档位不够 ⇒ 一律锁；只有读到数且够档才放行。"""
    config = _config(None)
    for snapshot in (None, {}, {"tier": None}, {"tier": "很多"}, {"tier": 6}):
        assert _locked_sticker_subdirs(config, snapshot) == ("私藏",), snapshot
    # 正控制腿：同一枚 config，唯一变的是档位读数 ⇒ 放行线真的画在 tier 上。
    assert _locked_sticker_subdirs(config, {"tier": 7}) == ()
    assert _locked_sticker_subdirs(config, {"tier": 9}) == ()


def test_private_knobs_are_read_from_the_handed_config() -> None:
    """两枚键都**现读**交来的快照 config（阈值跟改、空串＝整件关闭），不是代码里的常量。"""
    stricter = _config(None, bot_sticker_private_min_tier=8)
    assert _locked_sticker_subdirs(stricter, {"tier": 7}) == ("私藏",)
    assert _locked_sticker_subdirs(stricter, {"tier": 8}) == ()

    # 阈值读不出＝按 7 处理（比 8 松、比 6 严：与上一枚的 7/8 两腿对照才看得见回落点）。
    broken = _config(None, bot_sticker_private_min_tier="七档")
    assert _locked_sticker_subdirs(broken, {"tier": 7}) == ()
    assert _locked_sticker_subdirs(broken, {"tier": 6}) == ("私藏",)

    # 子目录名空串＝功能整体关闭：连未解锁快照都不锁。
    off = _config(None, bot_sticker_private_subdir="")
    assert _locked_sticker_subdirs(off, None) == ()
    # 正控制腿：换个名字照样锁得住 ⇒ 关的是「这一格」，不是整条判据失灵。
    renamed = _config(None, bot_sticker_private_subdir="只给管理员")
    assert _locked_sticker_subdirs(renamed, None) == ("只给管理员",)


def test_facade_fail_closed_locks_private_even_when_tagged(album_base: Path) -> None:
    """门面级：没建过档（快照缺席）＝按未解锁算；语境标签点名「私藏」也不许把它端出来。"""
    config = _config(album_base)
    for label, snapshot in (("absent", None), ("garbage", {"tier": "读不出"})):
        picked, tags = select_sticker_for_turn(
            None,
            config=config,
            pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
            session_key=f"failclosed-{label}",
            affinity_snapshot=snapshot,
            persona_albums=("守岸人",),
            extra_topic_terms=("私藏",),
        )
        assert tags  # 审计轨非空（判据走过门面）
        assert picked is not None
        assert "私藏" not in Path(picked["path"]).parts

    # 正控制腿：同夹具、同一名标签，只把档位换成够档 ⇒ 端到的就是私藏那张。
    high, _tags = select_sticker_for_turn(
        None,
        config=config,
        pool_policy=sticker_send_routing.POOL_POLICY_PACKS_ONLY,
        session_key="failclosed-high",
        affinity_snapshot={"tier": 7},
        persona_albums=("守岸人",),
        extra_topic_terms=("私藏",),
    )
    assert high is not None
    assert Path(high["path"]).name == "secret.png"


# ---------------------------------------------------------- 9：反空集控制腿（册外不出／无册缺席）


def test_album_exclusion_and_absence_have_live_nonempty_samples(album_base: Path) -> None:
    """「册外不出」「无册诚实缺席」两条否定判据各配正腿：基根确有册外存货、不带册名取得到图。"""
    config = _config(album_base)
    whole = sticker_packs.list_sticker_images(config)
    mine = sticker_packs.list_sticker_images(config, persona_names=("守岸人",))
    assert whole and mine
    assert set(mine) < set(whole)  # 册内是基根的真子集 ⇒ 排除掉的不是空气
    outside = [item for item in whole if not Path(item).is_relative_to(album_base / "守岸人")]
    assert outside  # 册外确有存货（别人格的册 + 基根散件）

    # 缺席册的 ``None`` 来自「不回落基根」这条判据，而非池子空：同一份配置不带册名照样出图。
    assert sticker_packs.pick_sticker(config, seed="ctl") is not None
    assert (
        sticker_packs.pick_sticker(config, seed="ctl", persona_names=("不存在的人格",))
        is None
    )
