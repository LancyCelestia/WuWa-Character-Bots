"""B1 池子守卫波（2026-09-28）：随机图**扫描面**内容守卫的离线回归。

锁五件事（每条都对应 ``_scan_dir`` 里一层真实筛子，判据唯一真身
``domains/media/image_guard.py``）：

1. **0 字节空件无条件拒**（``images_empty``）——不随守卫开关，空文件扩展名再对也发不出去；
2. **魔数验真**（``images_bad_magic``）——「扩展名对但内容坏」（HTML 改名 .png）被挡；
3. **字节下限**（``images_below_min_bytes``，键 ``bot_randpic_min_file_kb``）；
4. **像素短边下限**（``images_below_min_side``，键 ``bot_randpic_min_side``，先例 eat.py 300）；
5. **缩略图/缓存风格子目录剪枝**（``_should_prune_dir``）——`.`/`_` 前缀、
   thumbs/cache/preview 整名、回收站目录不进树；``Random pics`` 这类正常目录照走。

外加两枚口径锁：守卫全 0（读不到配置键的调用口）= B1 前逐字节同形；
新拒绝档进 ``gallery_empty`` 审计标签集与降级句（措辞由事实派生，P15 口径）。

⚠ 2026-09-29 用户裁定：``bot_randpic_min_file_kb`` / ``bot_randpic_min_side`` 的
**Config 缺省归零**——Picture 目录他自己手动整理，不由 bot 硬筛。本件因此分两半：
1-6 组测的是**参数面**（显式传下限时三层闸的判据与分账，也是把任一键调回 > 0 的
逃生口行为），第 7 组测的是**缺省面**（今天生产＝关态）。两半都不许被改写成
「守卫常开」：关态那半红的時候，就是有人把 ``guard_enabled`` 短路动了。
判据真身仍在 ``randpic._scan_dir``，本件只锁行为不改判据。

全离线：图字节在 tmp_path 现造（PIL 真 PNG 控尺寸/控字节数），零网络、零真实图库。
"""

from __future__ import annotations

import io
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _isolate_randpic_state(monkeypatch):
    monkeypatch.setattr(randpic, "_SCAN_CACHE", OrderedDict())
    monkeypatch.setattr(randpic, "_IDENTITY_CACHE", OrderedDict())
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _png(side: int, *, pad_to: int = 0) -> bytes:
    """PIL 真 PNG（短边 ``side`` 像素）；``pad_to`` 把字节数垫到 ≥ 该值（尾部填充不影响解码）。"""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (side % 251, 7, 11)).save(buffer, format="PNG")
    data = buffer.getvalue()
    if pad_to > len(data):
        data += b"\x00" * (pad_to - len(data))
    return data


def _write(root: Path, name: str, payload: bytes) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(payload)
    return path


def _facts(root: Path, **guard: int) -> randpic.GalleryFacts:
    return randpic.gallery_facts([str(root)], **guard)


# ============================================================================
# 1. 空件：无条件拒
# ============================================================================


def test_zero_byte_image_is_rejected_even_with_guards_off(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    _write(root, "empty.png", b"")
    good = _write(root, "good.png", PNG_MAGIC + b"solid-bytes")
    listing = randpic.list_gallery_images([str(root)])
    assert listing == [good], "0 字节空件不许进候选（守卫关着也拒）"
    facts = _facts(root)
    assert facts.images_empty == 1
    assert facts.images_seen == 2 and facts.usable == 1


# ============================================================================
# 2. 魔数验真
# ============================================================================


def test_fake_png_with_html_body_is_counted_as_bad_magic(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    _write(root, "tricky.png", b"<!DOCTYPE html><html><body>404</body></html>" * 4)
    facts = _facts(root, min_bytes=10)
    assert facts.usable == 0
    assert facts.images_bad_magic == 1
    assert facts.verdict == "bad_magic"


def test_magic_gate_stays_off_when_all_floors_off(tmp_path: Path) -> None:
    """守卫全 0（读不到配置键的调用口）＝B1 前逐字节同形：假 .png 仍进清单。"""
    root = tmp_path / "gallery"
    fake = _write(root, "tricky.png", b"<!DOCTYPE html><html>old</html>")
    assert randpic.list_gallery_images([str(root)]) == [fake]


def test_truncation_beyond_magic_is_undecodable_bad_magic(tmp_path: Path) -> None:
    """魔数对得上但 PIL 解不开（截断坏件）⇒ 计入 images_bad_magic，不发糊件。"""
    root = tmp_path / "gallery"
    _write(root, "cut.png", PNG_MAGIC + b"\x0d\x0a\x1a\x0aPARTIAL")
    facts = _facts(root, min_bytes=4, min_side=1)
    assert facts.usable == 0 and facts.images_bad_magic == 1


# ============================================================================
# 3. 字节下限
# ============================================================================


def test_below_min_bytes_rejected_and_verdict_names_it(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    tiny = _png(320)  # 真 PNG，但字节数远小于下面设的下限
    assert len(tiny) < 60_000
    _write(root, "small.png", tiny)
    facts = _facts(root, min_bytes=60_000)
    assert facts.usable == 0
    assert facts.images_below_min_bytes == 1
    assert facts.verdict == "below_min_bytes"
    line = randpic.gallery_degradation_line(facts, [str(root)], min_bytes=60_000)
    assert "BOT_RANDPIC_MIN_FILE_KB" in line
    assert "gallery_empty" in randpic.gallery_audit_tags("gallery_below_min_bytes", facts)


# ============================================================================
# 4. 像素短边下限
# ============================================================================


def test_below_min_side_rejected_verdict_and_line(tmp_path: Path) -> None:
    root = tmp_path / "gallery"
    _write(root, "icon.png", _png(16, pad_to=2_000))
    _write(root, "real.png", _png(320, pad_to=2_000))
    facts = _facts(root, min_side=300, min_bytes=1_000)
    assert facts.usable == 1  # 只放行短边达标那张
    assert facts.images_below_min_side == 1
    assert facts.verdict == "usable"  # 池里还有一张合用，不许外推成「整池都是缩略图」
    all_icon = tmp_path / "only-icons"
    _write(all_icon, "icon-a.png", _png(16, pad_to=2_000))
    _write(all_icon, "icon-b.png", _png(24, pad_to=2_000))
    icon_facts = _facts(all_icon, min_side=300, min_bytes=1_000)
    assert icon_facts.usable == 0 and icon_facts.verdict == "below_min_side"
    line = randpic.gallery_degradation_line(icon_facts, [str(all_icon)], min_side=300)
    assert "BOT_RANDPIC_MIN_SIDE" in line and "糊图" in line
    assert "gallery_empty" in randpic.gallery_audit_tags("gallery_below_min_side", icon_facts)


def test_min_side_skips_pixel_read_when_byte_floor_already_rejects(tmp_path: Path) -> None:
    """字节闸在前、像素闸在后：小文件不付 PIL 解图头的代价（惰性判定链的顺序承诺）。"""
    root = tmp_path / "gallery"
    _write(root, "dust.png", PNG_MAGIC + b"x" * 8)
    facts = _facts(root, min_bytes=10_000, min_side=300)
    assert facts.images_below_min_bytes == 1
    assert facts.images_below_min_side == 0 and facts.images_bad_magic == 0


# ============================================================================
# 5. 目录剪枝
# ============================================================================


PRUNED_DIR_NAMES = (".hidden", "_thumbs", "Thumbnails", "thumbs", "thumb", "Cache",
                    "cache", "preview", "previews", "#RecycleBin", "$RECYCLE.BIN", "@eaDir")
KEPT_DIR_NAMES = ("Random pics", "pics", "wallpapers", "2026_旅行", "Caches-Lite")


@pytest.mark.parametrize("name", PRUNED_DIR_NAMES)
def test_pruned_style_dirs_are_not_descended(tmp_path: Path, name: str) -> None:
    root = tmp_path / "gallery"
    _write(root, "root.png", PNG_MAGIC + b"root")
    _write(root / name, "inside.png", PNG_MAGIC + b"inside")
    listing = randpic.list_gallery_images([str(root)])
    assert [p.name for p in listing] == ["root.png"], f"{name} 里的图不该被扫到"


@pytest.mark.parametrize("name", KEPT_DIR_NAMES)
def test_normal_style_dirs_still_descended(tmp_path: Path, name: str) -> None:
    root = tmp_path / "gallery"
    _write(root / name, "inside.png", PNG_MAGIC + b"inside")
    listing = randpic.list_gallery_images([str(root)])
    assert [p.name for p in listing] == ["inside.png"], f"{name} 是正常目录，不许误剪"


# ============================================================================
# 6. 全闸合流：usable 反映每一层筛子的净结果
# ============================================================================


def test_usable_count_reflects_every_gate_at_once(tmp_path: Path) -> None:
    """一池混件同时踩满六层筛子：``usable`` 只等于放行那张，其余各归各的账。

    这条是「分账不串账」的合流锁：单独测每一层都绿、合起来把某本账漏记或重复记
    （比如超限件被顺手记成空件）的写法，只有混池实跑才抓得住。
    ``files_seen`` 数「列出来的所有文件」（含非图片扩展名），``images_seen`` 数
    「命中图片扩展名的」（含超限的），``usable`` 数「真进候选清单的」。
    尺子（都在 ``_scan_dir`` 的参数面，不经 Config）：单张上限 20 KB、字节下限 10 KB、
    短边下限 300 px ⇒ 放行件必须落在 10 KB < 字节 ≤ 20 KB 且短边 ≥ 300 px。
    """
    root = tmp_path / "gallery"
    _write(root / ".hidden", "cache-thumb.png", _png(64, pad_to=15_000))  # 剪枝：不进树
    _write(root / "Thumbnails", "thumb.png", _png(64, pad_to=15_000))  # 剪枝：不进树
    good = _write(root, "photo.png", _png(800, pad_to=15_000))  # 唯一放行
    _write(root, "empty.png", b"")  # 0 字节：无条件拒
    _write(root, "fake.png", b"<html><body>nope</body></html>" * 400)  # 11,200 B：魔数拒
    _write(root, "icon.png", _png(64, pad_to=15_000))  # 短边拒
    _write(root, "dust.png", PNG_MAGIC + b"x" * 8)  # 16 B：字节下限拒（闸在魔数之前）
    _write(root, "huge.png", _png(800, pad_to=40_000))  # 体积上限拒
    _write(root, "notes.txt", b"not an image at all")  # 扩展名不命中

    facts = randpic.gallery_facts(
        [str(root)], max_bytes=20_000, min_bytes=10_000, min_side=300
    )
    assert facts.dirs_configured == 1 and facts.dirs_read == 1
    # 剪枝掉的子树两张都不计（既不进 files_seen 也不进 images_seen）。
    assert facts.files_seen == 7  # 六个图片扩展名 + notes.txt
    assert facts.images_seen == 6
    assert facts.images_empty == 1
    assert facts.images_below_min_bytes == 1
    assert facts.images_bad_magic == 1
    assert facts.images_below_min_side == 1
    assert facts.images_over_limit == 1
    assert facts.usable == 1
    assert facts.images_seen == (
        facts.usable
        + facts.images_empty
        + facts.images_below_min_bytes
        + facts.images_bad_magic
        + facts.images_below_min_side
        + facts.images_over_limit
        + facts.images_stat_failed
    ), "六本账必须刚好铺满 images_seen：不许有被静默吞掉的一张"
    assert facts.verdict == "usable"
    listing = randpic.list_gallery_images(
        [str(root)], max_bytes=20_000, min_bytes=10_000, min_side=300
    )
    assert listing == [good], "候选清单必须只剩放行那张（六层筛子没有漏网的）"
    # 同一批混件换一把尺（两枚下限归 0 = 生产缺省态）⇒ 内容三层全部退出，
    # 只剩「剪枝 + 空件 + 体积上限」还在挡：闸由开关驱动，不是只对单件夹具成立。
    # ⚠ 缓存键只有目录（TTL 内不同下限会命中上一次扫出的清单，见 _collect_gallery
    # 文档串），所以这一腿必须先清 TTL——生产一进程一把尺，不存在这个交叉读法。
    randpic._SCAN_CACHE.clear()
    floors_off = randpic.list_gallery_images([str(root)], max_bytes=20_000)
    assert {p.name for p in floors_off} == {
        "photo.png",
        "fake.png",
        "icon.png",
        "dust.png",
    }, "下限归零后内容三层一张都不许再挡（空件与超限件仍归无条件那两层管）"


# ============================================================================
# 7. 配置接线：真 Config 缺省已归零（2026-09-29 裁定）；读不到键同样 = 关
# ============================================================================


def test_config_floor_helpers_map_kb_to_bytes_and_default_off() -> None:
    assert randpic._min_bytes_for(SimpleNamespace(bot_randpic_min_file_kb=100)) == 102_400
    assert randpic._min_bytes_for(SimpleNamespace(bot_randpic_min_file_kb=0)) == 0
    assert randpic._min_bytes_for(SimpleNamespace()) == 0
    assert randpic._min_side_for(SimpleNamespace(bot_randpic_min_side=300)) == 300
    assert randpic._min_side_for(SimpleNamespace(bot_randpic_min_side=-5)) == 0
    assert randpic._min_side_for(SimpleNamespace()) == 0


def test_real_config_defaults_put_both_floors_off() -> None:
    """真身 Config 的两枚下限缺省 = 0（2026-09-29 用户裁定：Picture 目录自己管）。

    这条锁的是**缺省态**，不是判据：键与参数面全部保留作逃生口（任一键调回 > 0
    ⇒ 字节闸/魔数闸/短边闸三层重新生效，见上面 1-4 组用例），但今天生产不硬筛。
    读缺省不读 env（防现网值误红）。⚠ 与 ``_scan_dir`` 的 ``guard_enabled`` 短路
    连读：两键同 0 ⇒ 文件头魔数验真也一并停用，池子只剩「剪枝 + 空件 + 体积上限」
    三层（这一条是裁定的**直接后果**，不是缺陷；要恢复魔数闸请把任一键调回 > 0）。
    """
    from plugins.bot_unified_runtime.config import Config

    min_kb = int(Config.model_fields["bot_randpic_min_file_kb"].default)
    min_side = int(Config.model_fields["bot_randpic_min_side"].default)
    assert min_kb == 0
    assert min_side == 0
    # 缺省派生的两把尺都回 0 ⇒ 守卫整体不启动（_scan_dir 的 guard_enabled 短路为假）。
    as_config = SimpleNamespace(
        bot_randpic_min_file_kb=min_kb, bot_randpic_min_side=min_side
    )
    assert randpic._min_bytes_for(as_config) == 0
    assert randpic._min_side_for(as_config) == 0


def test_default_config_scans_a_thumbnail_like_pool_without_filtering(tmp_path: Path) -> None:
    """缺省态（两把尺都 0）的行为自证：缩略图尺寸的图照进候选，守卫不参与。

    与上一条成对：上面钉「配置是 0」，这里钉「0 真的等于不筛内容」——
    否则谁把 ``guard_enabled`` 改成常开，只有这条会红。
    """
    root = tmp_path / "gallery"
    _write(root, "thumb.png", _png(32, pad_to=2_000))  # 短边 32 px（开闸时必被挡）
    _write(root, "photo.png", _png(1_200, pad_to=2_000))
    listing = randpic.list_gallery_images([str(root)])
    assert {p.name for p in listing} == {"thumb.png", "photo.png"}
    facts = _facts(root)
    assert facts.usable == 2
    assert facts.images_below_min_bytes == 0 and facts.images_below_min_side == 0
    assert facts.images_bad_magic == 0
    assert facts.verdict == "usable"
    # 同一枚下限调回 > 0 ⇒ 三层闸立刻回来（逃生口真的还通，不是删干净的死键）。
    # ⚠ 缓存键只有目录、TTL 内不同下限会命中上一次扫出的清单（_collect_gallery 的
    # 既定口径），所以这一腿先清 TTL 再读；生产一进程一把尺，不存在这种交叉读法。
    randpic._SCAN_CACHE.clear()
    reopened = _facts(root, min_side=300, min_bytes=1_000)
    assert reopened.usable == 1 and reopened.images_below_min_side == 1


def test_capability_degrades_honestly_when_whole_pool_is_fake(tmp_path: Path) -> None:
    """指令路：整池都是假图 ⇒ 降级句点名「文件头对不上签名」，绝不冒充「已发出」。"""
    root = tmp_path / "gallery"
    # 垫到 > 1 KB（min_file_kb=1 ⇒ 字节闸放行），让**魔数闸**成为唯一的拒绝原因。
    _write(root, "a.png", (b"<html>" + b"not an image" * 30).ljust(1200, b" "))
    _write(root, "b.png", (b"GIMP2" + b"also not an image" * 30).ljust(1200, b" "))  # 头不对（非 GIF8）
    config = SimpleNamespace(
        bot_randpic_enabled=True,
        bot_randpic_dirs=[str(root)],
        bot_randpic_trigger_words=[],
        bot_randpic_max_file_mb=25,
        bot_randpic_no_repeat_window_seconds=0.0,
        bot_randpic_min_file_kb=1,
        bot_randpic_min_side=0,
    )
    message = SimpleNamespace(
        plain_text="随机图", session_id="private_7", message_id="m-1", request_id="r-1"
    )
    result = randpic.build_randpic_capability(config)(message, None)
    assert result.images == []
    assert "文件头" in result.body
    assert "gallery_bad_magic" in result.audit_tags
