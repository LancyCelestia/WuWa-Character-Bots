"""bot 自有表情私库（``domains/meme/sources/sticker_packs.py``）回归树。

覆盖的都是**本件的判据**，不是 randpic 的复读：

1. 四道筛子各自有牙（扩展名白名单 / 魔数验真 / 0 字节拒 / 越出登记面拒）；
2. **刻意没有像素与字节下限**——一枚 1×1 的小贴纸与一张 8KB 的 GIF 必须照样入库
   （这条是设计分歧，不是漏配：搬 randpic 那两把尺会把她挑的包裁成空池）；
3. 递归开关与子目录剪枝；
4. 30 秒 TTL 缓存：一次扫描喂多个读数口，且**绝不自建目录**；
5. 窗内不重发（含并发原子占坑、整库发完时指令路复发 / 主动路不发、窗长 0=关）；
6. ``StickerFacts`` 的诚实缺席：六种「为什么没图」分开记，措辞不得越界。

全部离线、只写 ``tmp_path``（源码树零残留，AGENTS 规则 6）。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.media import image_guard
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    RecentImageWindow,
)
from plugins.bot_unified_runtime.domains.meme.sources import sticker_packs

# 三族**真**签名（前 12 字节够 image_guard 判全），后随填充字节：
# 本件不判像素，所以不需要 PIL、也不造真能渲染的图。
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
GIF_HEAD = b"GIF89a" + b"\x00" * 26
WEBP_HEAD = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 20
# APNG 的容器签名就是 PNG 头 ⇒ 同一串字节，扩展名才是本件的白名单判据。
NOT_AN_IMAGE = "<html><body>改名件</body></html>............".encode()


def _write(root: Path, name: str, payload: bytes) -> Path:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


@pytest.fixture(autouse=True)
def _clean_pool_state() -> Any:
    """每个用例前后都清池缓存与进程级窗账（模块态是进程级的，用例不许互相看）。"""
    sticker_packs.reset_sticker_state()
    yield
    sticker_packs.reset_sticker_state()


@pytest.fixture()
def pool(tmp_path: Path) -> Path:
    """一枚装了三张真贴纸 + 三种该被拦的东西的登记目录。"""
    root = tmp_path / "shorekeeper"
    root.mkdir(parents=True)
    _write(root, "a.png", PNG_HEAD)
    _write(root, "b.gif", GIF_HEAD)
    _write(root / "sub", "c.webp", WEBP_HEAD)
    _write(root, "empty.png", b"")
    _write(root, "fake.png", NOT_AN_IMAGE)
    _write(root, "notes.txt", b"hello")
    _write(root / "thumbnails", "t.png", PNG_HEAD)
    _write(root / "__MACOSX", "u.png", PNG_HEAD)
    return root


def _config(root: Path | str | None, **overrides: Any) -> SimpleNamespace:
    """最小 configish：本件只按名 getattr，不需要真 pydantic 模型。"""
    values: dict[str, Any] = {
        "bot_sticker_dir": str(root) if root is not None else "",
        "bot_sticker_enabled": True,
        "bot_sticker_recursive": True,
        "bot_sticker_no_repeat_window_seconds": 1800.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ------------------------------------------------------------------ 四道筛子


def test_only_the_four_filters_apply_and_pruned_dirs_never_enter(pool: Path) -> None:
    config = _config(pool)
    names = {path.name for path in sticker_packs.list_sticker_images(config)}
    assert names == {"a.png", "b.gif", "c.webp"}
    facts = sticker_packs.sticker_facts(config)
    # 「有 6 个文件、5 个像贴纸、3 张真合用」三格必须分开，不许折成一个空清单。
    assert facts.files_seen == 6
    assert facts.images_seen == 5
    assert facts.images_empty == 1
    assert facts.images_bad_magic == 1
    assert facts.usable == 3
    assert facts.dirs_pruned == 2
    assert facts.verdict == "usable"
    assert facts.opened


def test_zero_byte_and_fake_extension_are_rejected_by_the_guard(pool: Path) -> None:
    assert sticker_packs.guard_sticker_path(pool / "a.png") == pool / "a.png"
    assert sticker_packs.guard_sticker_path(pool / "empty.png") is None
    assert sticker_packs.guard_sticker_path(pool / "fake.png") is None
    assert sticker_packs.guard_sticker_path(pool / "gone.png") is None
    assert sticker_packs.guard_sticker_path(None) is None
    # 目录不是可发的图（``S_ISREG`` 那一格）。
    assert sticker_packs.guard_sticker_path(pool) is None


def test_no_pixel_or_byte_floor_is_applied(tmp_path: Path) -> None:
    """**设计分歧锁**：一枚 31 字节的"小图"必须照旧入库。

    这里刻意不调 ``image_guard.min_side_of_file``——本件与 randpic 的差别就在这一格。
    写死成断言是为了：谁将来「顺手」把像素/字节下限搬过来，当场看到这一发红。
    """
    root = tmp_path / "tiny"
    root.mkdir(parents=True)
    # 31 字节的 PNG：远低于 bot_randpic_min_file_kb(100KB)，也谈不上 min_side(400px)。
    _write(root, "tiny.png", PNG_HEAD)
    config = _config(root)
    assert [p.name for p in sticker_packs.list_sticker_images(config)] == ["tiny.png"]
    assert sticker_packs.sticker_facts(config).usable == 1


def test_apng_is_accepted_because_its_container_signature_is_png(tmp_path: Path) -> None:
    root = tmp_path / "apng"
    root.mkdir(parents=True)
    _write(root, "loop.apng", PNG_HEAD)
    config = _config(root)
    assert [p.name for p in sticker_packs.list_sticker_images(config)] == ["loop.apng"]


def test_bmp_is_not_in_the_sticker_whitelist_even_though_guard_knows_it(
    tmp_path: Path,
) -> None:
    """.bmp 在 image_guard 的五族里（那是「是不是图」），但**不在**本库白名单（那是「收不收」）。"""
    assert ".bmp" in image_guard.IMAGE_EXTENSIONS
    assert ".bmp" not in sticker_packs._STICKER_EXTENSIONS
    assert ".apng" not in image_guard.IMAGE_EXTENSIONS
    assert ".apng" in sticker_packs._STICKER_EXTENSIONS
    root = tmp_path / "bmpcase"
    root.mkdir(parents=True)
    _write(root, "big.bmp", b"BM" + b"\x00" * 40)
    assert sticker_packs.list_sticker_images(_config(root)) == []


def test_cache_is_keyed_by_the_registered_root(pool: Path, tmp_path: Path) -> None:
    """换一枚登记根 ⇒ 读的是新根；切回来仍是那份缓存（键带目录，不许串味）。"""
    other = tmp_path / "other_pack"
    other.mkdir(parents=True)
    _write(other, "solo.png", PNG_HEAD)
    pool_config = _config(pool)
    assert {p.name for p in sticker_packs.list_sticker_images(pool_config)} == {
        "a.png", "b.gif", "c.webp"
    }
    assert [p.name for p in sticker_packs.list_sticker_images(_config(other))] == ["solo.png"]
    assert sorted(p.name for p in sticker_packs.list_sticker_images(pool_config)) == [
        "a.png", "b.gif", "c.webp"
    ]
    assert len(sticker_packs._SCAN_CACHE) == 2  # 两枚根各一条，没互相覆盖


# ------------------------------------------------------------------ 递归与剪枝


def test_recursive_off_reads_only_the_registered_top_level(pool: Path) -> None:
    config = _config(pool, bot_sticker_recursive=False)
    assert [p.name for p in sticker_packs.list_sticker_images(config)] == ["a.png", "b.gif"]
    assert sticker_packs.sticker_facts(config).dirs_read == 1


def test_hidden_and_thumbnail_subdirs_are_pruned_with_the_shared_name_list(
    pool: Path,
) -> None:
    """剪枝名单只有一枚真身（``randpic._should_prune_dir``）：本件不抄第二份。"""
    assert sticker_packs._should_prune_dir is randpic._should_prune_dir
    facts = sticker_packs.sticker_facts(_config(pool))
    assert facts.dirs_pruned == 2  # thumbnails/ 与 __MACOSX/
    assert "t.png" not in {p.name for p in sticker_packs.list_sticker_images(_config(pool))}


# ------------------------------------------------------------------ 缓存与「绝不自建」


def test_three_reading_entrances_share_one_scan_and_a_ttl_cache(pool: Path) -> None:
    config = _config(pool)
    before = dict(sticker_packs._SCAN_CACHE)
    assert not before
    sticker_packs.list_sticker_images(config)
    keys = list(sticker_packs._SCAN_CACHE)
    assert len(keys) == 1
    stamp, listing, facts = sticker_packs._SCAN_CACHE[keys[0]]
    sticker_packs.sticker_facts(config)
    sticker_packs.pick_sticker(config, session_key="private_1", seed="s")
    # 三个读数口之后仍然是**同一份**缓存条目（戳没被换掉 ⇒ 没有重扫、没有二次写盘）。
    assert sticker_packs._SCAN_CACHE[keys[0]][0] == stamp
    assert len(listing) == len(sticker_packs._SCAN_CACHE[keys[0]][1]) == 3
    assert facts.usable == 3


def test_dead_reference_is_dropped_from_the_ttl_listing(pool: Path) -> None:
    """清单里那条路已经不在原位 ⇒ 挑中时就地摘掉，别在 TTL 内反复撞同一堵墙。"""
    config = _config(pool)
    victim = pool / "a.png"
    assert victim in sticker_packs.list_sticker_images(config)
    os.replace(str(victim), str(pool / "a-moved.png"))  # 改名（本仓不真删文件）
    sticker_packs._drop_from_listing(victim)
    remaining = {p.name for p in sticker_packs.list_sticker_images(config)}
    assert "a.png" not in remaining and remaining == {"b.gif", "c.webp"}
    # ⚠ 摘路径**不**改观察事实那格：没重扫就没资格改 ``usable``（那是另一把尺的账）。
    assert sticker_packs.sticker_facts(config).usable == 3
    # 重扫（缓存过期/被清）才会看见改名后的那张。
    sticker_packs.reset_sticker_state()
    assert "a-moved.png" in {p.name for p in sticker_packs.list_sticker_images(config)}


def test_module_never_creates_the_registered_directory(tmp_path: Path) -> None:
    """「绝不自建目录」是硬约束（先例 randpic）：本件全树零 mkdir。"""
    missing = tmp_path / "not_created_yet" / "shorekeeper"
    config = _config(missing)
    assert sticker_packs.list_sticker_images(config) == []
    assert not missing.exists()
    assert not missing.parent.exists()
    assert sticker_packs.pick_sticker(config, session_key="group_1", seed="x") is None
    facts = sticker_packs.sticker_facts(config)
    assert facts.dirs_missing == 1
    assert facts.verdict == "missing"
    # ⚠ 「目录不存在」绝不能被写成「里面没有贴纸」：那格必须为假。
    assert facts.opened is False


# ------------------------------------------------------------------ 诚实缺席的六种说法


def test_unconfigured_is_reported_as_unconfigured_not_empty(tmp_path: Path) -> None:
    facts = sticker_packs.sticker_facts(_config(""))
    assert facts.dir_configured is False
    assert facts.verdict == "unconfigured"
    assert sticker_packs.configured_sticker_dir(_config("")) is None
    assert sticker_packs.pick_sticker(_config(""), session_key="s") is None


def test_path_that_is_a_file_is_not_directory(tmp_path: Path, pool: Path) -> None:
    a_file = pool / "notes.txt"
    facts = sticker_packs.sticker_facts(_config(a_file))
    assert facts.dirs_not_directory == 1
    assert facts.verdict == "not_directory"
    assert facts.opened is False


def test_directory_full_of_non_stickers_says_no_sticker_extension(tmp_path: Path) -> None:
    root = tmp_path / "docs_only"
    root.mkdir(parents=True)
    _write(root, "readme.md", b"# hi")
    _write(root, "data.json", b"{}")
    facts = sticker_packs.sticker_facts(_config(root))
    assert facts.files_seen == 2 and facts.images_seen == 0
    assert facts.verdict == "no_sticker_extension"
    assert facts.opened is True  # 这一句才允许措辞提「里面没有」


def test_empty_directory_says_empty(tmp_path: Path) -> None:
    root = tmp_path / "empty_pack"
    root.mkdir(parents=True)
    facts = sticker_packs.sticker_facts(_config(root))
    assert facts.files_seen == 0 and facts.usable == 0
    assert facts.verdict == "empty" and facts.opened is True


def test_all_rejected_images_report_the_reason_they_were_rejected(tmp_path: Path) -> None:
    root = tmp_path / "bad_magic_pack"
    root.mkdir(parents=True)
    _write(root, "x.png", NOT_AN_IMAGE)
    _write(root, "y.gif", NOT_AN_IMAGE)
    facts = sticker_packs.sticker_facts(_config(root))
    assert facts.usable == 0 and facts.images_seen == 2
    assert facts.verdict == "bad_magic"


def test_send_disabled_reports_send_disabled(pool: Path) -> None:
    config = _config(pool, bot_sticker_enabled=False)
    assert sticker_packs.sticker_facts(config).verdict == "send_disabled"
    assert sticker_packs.pick_sticker(config, session_key="group_1") is None
    # 关掉发送闸**不**影响「库里到底有几张」这一问——库存查询不是发送。
    assert sticker_packs.list_sticker_images(config)


# ------------------------------------------------------------------ 取一张


def test_pick_honours_the_send_switch_and_returns_none_when_pool_empty(pool: Path) -> None:
    assert sticker_packs.pick_sticker(_config(pool), session_key="group_1") is not None
    empty = pool / "sub" / "nothing"
    assert sticker_packs.pick_sticker(_config(empty), session_key="group_1") is None


def test_same_seed_same_sticker_across_a_fresh_window(pool: Path) -> None:
    config = _config(pool)
    first = sticker_packs.pick_sticker(config, session_key="group_7", seed="fixed")
    sticker_packs.reset_sticker_state()
    second = sticker_packs.pick_sticker(config, session_key="group_7", seed="fixed")
    assert first is not None and first == second


def test_no_repeat_window_serves_three_distinct_stickers_then_holds(pool: Path) -> None:
    config = _config(pool)
    window = RecentImageWindow()
    picked = [
        sticker_packs.pick_sticker(
            config, session_key="private_42", seed=f"s{index}", window=window
        )
        for index in range(3)
    ]
    assert all(p is not None for p in picked)
    assert len({p.name for p in picked}) == 3  # type: ignore[union-attr]
    # 整库三张都在窗内了：主动路（allow_exhausted=False）宁可不发。
    assert sticker_packs.pick_sticker(
        config, session_key="private_42", seed="more", window=window, allow_exhausted=False
    ) is None
    # 指令路退「最久没发」那张（a.png 是本轮第一枚被占的）。
    recycled = sticker_packs.pick_sticker(
        config, session_key="private_42", seed="more", window=window, allow_exhausted=True
    )
    assert recycled is not None
    assert window.recent_keys("private_42", window_seconds=1800.0)


def test_group_bucket_keys_share_one_ledger_via_the_shared_window(pool: Path) -> None:
    """群账键 ``group_{G}_{U}`` 与 ``group_{G}`` 记的是同一本账（收敛发生在窗账入口）。

    三张贴纸被两个人各要一次就发完了 ⇒ 第三条腿（换一个键形状）必须看见「整库都在
    窗内」，主动路不发。旧写法各记一本账时这里会照发（同群同图互相看不见）。
    """
    config = _config(pool)
    window = RecentImageWindow()
    assert sticker_packs.pick_sticker(
        config, session_key="group_5_11", seed="a", window=window
    ) is not None
    assert sticker_packs.pick_sticker(
        config, session_key="group_5_22", seed="b", window=window
    ) is not None
    assert sticker_packs.pick_sticker(
        config, session_key="group_5", seed="c", window=window
    ) is not None
    # 三张占满 ⇒ 换一个键形状来问也拿不到（主动路）。
    assert sticker_packs.pick_sticker(
        config, session_key="group_5_33", seed="d", window=window, allow_exhausted=False
    ) is None


def test_window_zero_means_repeats_are_allowed(pool: Path) -> None:
    config = _config(pool, bot_sticker_no_repeat_window_seconds=0.0)
    window = RecentImageWindow()
    picks = [
        sticker_packs.pick_sticker(
            config, session_key="private_7", seed=str(index), window=window
        )
        for index in range(5)
    ]
    assert all(p is not None for p in picks)
    # 窗长 0 ⇒ 窗账一行都不该写（「关」不是「记了但不管用」）。
    assert window.recent_keys("private_7", window_seconds=0.0) == frozenset()


def test_picked_path_always_survives_the_outbound_guard(pool: Path) -> None:
    """交出去的路径必须**此刻**还活着且仍是真图（两闸各防一侧）。"""
    config = _config(pool)
    for index in range(3):
        got = sticker_packs.pick_sticker(config, session_key="group_9", seed=str(index))
        if got is None:
            break
        assert sticker_packs.guard_sticker_path(got) is not None


def test_sticker_pool_and_randpic_keep_separate_window_ledgers(pool: Path) -> None:
    """两本窗账形状相同、实例不同：randpic 记过的图不该让私库误判「发过」。"""
    assert sticker_packs._DEFAULT_STICKER_WINDOW is not randpic._DEFAULT_RECENT_WINDOW
    sticker_packs._DEFAULT_STICKER_WINDOW.record("private_8", "abc", window_seconds=1800.0)
    assert randpic._DEFAULT_RECENT_WINDOW.recent_keys("private_8", window_seconds=1800.0) \
        == frozenset()
    randpic._DEFAULT_RECENT_WINDOW.clear()


# ------------------------------------------------------------------ 配置面三面齐


def test_config_fields_are_registered_and_path_remaps() -> None:
    from plugins.bot_unified_runtime.config import PATH_REMAPPED_FIELDS, Config

    assert "bot_sticker_dir" in PATH_REMAPPED_FIELDS
    config = Config()
    assert config.bot_sticker_enabled is True
    assert config.bot_sticker_recursive is True
    assert config.bot_sticker_no_repeat_window_seconds == 1800.0
    # 重映射生效 ⇒ 拿到的必须是绝对路径（相对写法会按 CWD 漂，那是铁律 6 的漏点）。
    root = sticker_packs.configured_sticker_dir(config)
    assert root is not None and root.is_absolute()
    # 断言"挂在数据根下 + 尾巴逐字是字段缺省那一段"，**不**把数据根长什么形状写死：
    # 根由 ``scripts/runtime_paths`` 定（测试进程＝conftest L1 的隔离根，生产＝``.env`` 那枚）。
    # 旧写法 ``endswith("data/bot_stickers/shorekeeper")`` 把"缺省锚在源码树 ``<仓根>/data``"
    # 那一代落点编进了尺里，中央缝（席 remapseam，台账 P1 H-1／F-10）修好当晚它就红了。
    from plugins.bot_unified_runtime.config import runtime_data_root_of

    assert root == runtime_data_root_of(config) / "bot_stickers" / "shorekeeper"
    # 读一遍库**不**该把目录造出来（她还没放贴纸时也不该有）；源码树零残留。
    existed_before = root.exists()
    sticker_packs.list_sticker_images(config)
    sticker_packs.pick_sticker(config, session_key="private_1")
    assert root.exists() is existed_before
    assert not (Path(__file__).resolve().parents[1] / "data").exists()


def test_hot_tier_ledger_declares_all_four_keys() -> None:
    """配置登记三面齐：config.py 字段 + settings.py 热改态 + .env.example 申报行。"""
    from plugins.bot_unified_runtime.domains.chat_reply.runtime import settings

    upper = {name.upper() for name in (
        "bot_sticker_dir", "bot_sticker_enabled",
        "bot_sticker_recursive", "bot_sticker_no_repeat_window_seconds",
    )}
    listed = set(settings.RESTART_REQUIRED_KEYS) | set(settings.SETTABLE_KEYS)
    assert upper <= listed, f"未对热改面表态的贴纸键：{sorted(upper - listed)}"
    env_example = (
        Path(__file__).resolve().parents[1] / ".env.example"
    ).read_text(encoding="utf-8")
    for name in sorted(upper):
        assert f"{name}=" in env_example, f".env.example 缺 {name} 的激活行"
