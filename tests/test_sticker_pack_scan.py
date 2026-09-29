"""S-MEME-POOLSCAN（2026-09-29，需求 12）：本地贴纸分池的运行期扫池锁。

补的洞：``bot_sticker_dir`` 在 ``config.py`` 零命中、红猪包一类**本地登记目录**没有
扫池机制——今天只有「群聊被动吸收」与「手动跑离线脚本」两条腿。本件锁新腿
``domains/meme/sources/sticker_pool.py`` 的六件事：

1. 目录里的真 PNG 能被吸进库（改名/换 md5 都不双份 ⇒ 幂等）；
2. 内容守卫与随机图池/群聊吸收**同一把尺**（假扩展名、0 字节、超上限、缩略图各拦一次）；
3. 本命判定只走 ``shorekeeper_absorb.decide_subject`` 那唯一判据口：**没有白名单角色名
   就不标本命**（绝不把没认出来的图当守岸人塞进本命池＝用户红线）；
4. 隔离墓碑优先——被隔离过的内容一块都不回库；
5. 可复现：同一批输入两次扫描给出同一串候选；有界扫描（``limit_per_root``）；
6. 隐私面：只读登记目录，链接/``..`` 指到目录外的一律不读；本件零 Config 读点
   （新键登记＝配置面改动，归主会话，见席位台账；幽灵按名读点门不许被顶红）。

全离线：图字节在 ``tmp_path`` 现造，零网络、零真实图库。
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.domains.meme.sources import sticker_pool
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    MemeQuarantineLedger,
)

PNG_HEAD = b"\x89PNG\r\n\x1a\n"


def _png(side: int, *, tint: int = 7) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (tint, 3, 9)).save(buffer, format="PNG")
    data = buffer.getvalue()
    return data + b"\x00" * max(0, 4096 - len(data))


@pytest.fixture()
def env(tmp_path: Path):
    """``tmp_path/data/``：db 在根、库在 ``meme_library/``、包在 ``packs/<包名>/``。"""
    data_root = tmp_path / "data"
    library = data_root / "meme_library"
    library.mkdir(parents=True, exist_ok=True)
    store = MemeLibraryStore(str(data_root / "meme_library.sqlite3"), prefer=[])
    return SimpleNamespace(
        data_root=data_root, library=library, store=store, packs=tmp_path / "packs"
    )


def _pack(env, name: str, files: dict[str, bytes]) -> Path:
    root = env.packs / name
    root.mkdir(parents=True, exist_ok=True)
    for filename, payload in files.items():
        target = root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


# ---------------------------------------------------------------- 1. 吸得进来


def test_pack_images_are_absorbed_and_idempotent(env) -> None:
    _pack(env, "红猪包", {"one.png": _png(64, tint=1), "two.png": _png(64, tint=2)})
    first = sticker_pool.absorb_pack_dirs(
        [env.packs / "红猪包"], store=env.store, library_dir=env.library
    )
    assert first["accepted"] == 2, first
    assert len(list(env.library.glob("*.png"))) == 2
    second = sticker_pool.absorb_pack_dirs(
        [env.packs / "红猪包"], store=env.store, library_dir=env.library
    )
    assert second["accepted"] == 0 and second["skipped"].get("duplicate") == 2, second
    assert len(list(env.library.glob("*.png"))) == 2, "重跑一次就多存一份 ⇒ 幂等破了"


def test_no_registered_roots_means_zero_absorb(env) -> None:
    """没登记目录＝零吸收，不报错也不谎称「库已就绪」（没检索禁写「它没有」的反向口径）。"""
    report = sticker_pool.absorb_pack_dirs([], store=env.store, library_dir=env.library)
    assert report["roots"] == 0 and report["candidates"] == 0 and report["accepted"] == 0


# ---------------------------------------------------------------- 2. 同一把尺


@pytest.mark.parametrize(
    ("filename", "payload", "reason"),
    [
        ("note.txt", b"hello", sticker_pool.SKIP_EXT),
        ("fake.png", b"<html><body>not an image</body></html>", sticker_pool.SKIP_BAD_MAGIC),
        ("zero.png", b"", sticker_pool.SKIP_EMPTY),
    ],
)
def test_content_guard_rejects_same_as_the_other_two_legs(env, filename, payload, reason) -> None:
    _pack(env, "脏包", {filename: payload})
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "脏包"], store=env.store, library_dir=env.library
    )
    assert report["accepted"] == 0
    assert report["skipped"].get(reason) == 1, report


def test_min_side_and_size_floors_are_honoured(env) -> None:
    _pack(env, "糊包", {"icon.png": _png(32, tint=5), "big.png": _png(64, tint=6)})
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "糊包"],
        store=env.store,
        library_dir=env.library,
        min_side=60,
        min_file_bytes=1,
    )
    assert report["accepted"] == 1 and report["skipped"].get(sticker_pool.SKIP_BELOW_MIN_SIDE) == 1


def test_oversize_is_refused(env) -> None:
    _pack(env, "重包", {"fat.png": _png(64, tint=9)})
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "重包"], store=env.store, library_dir=env.library, max_file_bytes=64
    )
    assert report["accepted"] == 0 and report["skipped"].get(sticker_pool.SKIP_TOO_LARGE) == 1


# ---------------------------------------------------------------- 3. 本命不猜


def test_persona_mark_requires_a_whitelisted_role_name(env) -> None:
    _pack(env, "守岸人表情包", {"a.png": _png(64, tint=1)})
    _pack(env, "别人家包", {"b.png": _png(64, tint=2)})
    terms = ("守岸人", "岸宝")
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "守岸人表情包", env.packs / "别人家包"],
        store=env.store,
        library_dir=env.library,
        persona_terms=terms,
    )
    assert report["persona_owned"] == 1 and report["accepted"] == 1, report
    owned = [
        str(row["md5"])
        for row in env.store.live_rows_with_sha()
        if env.store.is_persona_owned(str(row["md5"]))
    ] if hasattr(env.store, "is_persona_owned") else []
    if owned:
        assert len(owned) == 1
    # 判据只有一处：本件不自拼主体正则，只喂 decide_subject。
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/meme/sources/sticker_pool.py"
    ).read_text(encoding="utf-8")
    assert "decide_subject" in source and "re.compile" not in source


def test_undetermined_subject_never_enters_persona_pool(env) -> None:
    """VLM 不在场 + 名字里没有白名单角色名 ⇒ 照常入库、**绝不**进本命池。"""
    _pack(env, "路人包", {"cat.png": _png(64, tint=3)})
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "路人包"],
        store=env.store,
        library_dir=env.library,
        persona_terms=("守岸人", "岸宝"),
    )
    assert report["accepted"] == 1 and report["persona_owned"] == 0, report


# ---------------------------------------------------------------- 4. 墓碑优先


def test_quarantined_content_does_not_come_back(env) -> None:
    from plugins.bot_unified_runtime.domains.meme.sources import shorekeeper_absorb

    payload = _png(64, tint=4)
    _pack(env, "脏包", {"bad.png": payload})
    sha = shorekeeper_absorb.content_sha256(payload)
    ledger = MemeQuarantineLedger(env.data_root / "meme_send_history.sqlite3")
    ledger.add(sha, reason="nsfw_delete")
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "脏包"], store=env.store, library_dir=env.library, ledger=ledger
    )
    assert report["accepted"] == 0
    assert report["skipped"].get(sticker_pool.SKIP_QUARANTINED) == 1, report
    assert list(env.library.glob("*.png")) == [], "被隔离的内容还在库目录里落了盘"


# ---------------------------------------------------------------- 5. 可复现/有界


def test_discovery_is_deterministic_and_bounded(env) -> None:
    _pack(env, "B包", {f"p{i}.png": _png(48, tint=i) for i in range(5)})
    root = env.packs / "B包"
    first, _skips = sticker_pool.discover_pack_images([root])
    second, _skips2 = sticker_pool.discover_pack_images([root])
    assert [str(p) for p, _ in first] == [str(p) for p, _ in second], "两次扫描顺序都稳定不了"
    limited, skips = sticker_pool.discover_pack_images([root], limit_per_root=2)
    assert len(limited) == 2 and skips.get(sticker_pool.SKIP_LIMIT) == 3, (limited, skips)


def test_only_registered_root_is_read(env) -> None:
    """隐私红线：登记 A 包就只读 A 包；同级的 B 包一个字节都不碰。"""
    _pack(env, "A包", {"a.png": _png(64, tint=1)})
    _pack(env, "B包", {"b.png": _png(64, tint=2)})
    report = sticker_pool.absorb_pack_dirs(
        [env.packs / "A包"], store=env.store, library_dir=env.library
    )
    assert report["candidates"] == 1 and report["accepted"] == 1, report


def test_escaping_link_is_not_read(env) -> None:
    """目录外引用（符号链接/junction）不读。造不出链接就诚实 skip，不假装测过。"""
    outside = env.data_root.parent / "private-album.png"
    outside.write_bytes(_png(64, tint=8))
    root = env.packs / "带链接包"
    root.mkdir(parents=True, exist_ok=True)
    try:
        (root / "lnk.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("本机不允许建符号链接（Windows 需开发者模式/提权）")
    report = sticker_pool.absorb_pack_dirs(
        [root], store=env.store, library_dir=env.library
    )
    assert report["accepted"] == 0, "链接把登记目录外的私人图吸了进来 ⇒ 隐私红线破了"
    assert outside.exists()


def test_outside_root_branch_has_teeth_without_symlink_privilege(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有建链接的权限时也要证到这一支：桩把解析结果指到登记目录**之外**。

    上面那条 ``symlink_to`` 在 Windows 上常被拒绝（需开发者模式/提权），诚实 skip
    之后分支就成了无人区。这里换成「解析结果伪造」：候选文件确实在包内，但它
    resolve 到盘上别处 ⇒ 同一条 ``is_relative_to(root)`` 判据必须把它拦下来。
    """
    root = _pack(env, "伪链接包", {"a.png": _png(64, tint=1)})
    original = Path.resolve

    def fake_resolve(self: Path, *args: object, **kwargs: object) -> Path:
        if self.name == "a.png" and self.parent == root:
            return env.data_root.parent / "someone-elses-folder.png"
        return original(self, *args, **kwargs)  # type: ignore[arg-return]

    monkeypatch.setattr(Path, "resolve", fake_resolve)
    candidates, skips = sticker_pool.discover_pack_images([root])
    assert candidates == [] and skips.get(sticker_pool.SKIP_OUTSIDE_ROOT) == 1, (
        candidates,
        skips,
    )


def test_pending_review_face_counts_untagged_rows(env) -> None:
    """诚实降级的**可见面**：认不出主体的图留在库里等补标，统计口径数得出、不蒸发。

    口径归属（S-MEME-SEMANTICS，2026-09-29 复核）：本件写于「拿 description 为空当
    待审替身」那一版；S-MEME2-REVIEW 之后队列位是 ``memes.review_state`` 列（判据本体
    在 ``persona_review``），``stats()`` 把「待审」与「从没打过标」拆成两枚数各说各的事
    （见 ``meme_library.stats`` 注释）。所以这里的可见面问 ``untagged``：它与
    ``list_untagged`` 同源（``IFNULL(description,'')=''``），仍是一把尺、没有第二本账。
    旧写法读 ``pending_review`` 在现契约下恒为 0——那才是真「蒸发」。
    """
    _pack(env, "包A", {"a.png": _png(64, tint=1), "b.png": _png(64, tint=2)})
    sticker_pool.absorb_pack_dirs([env.packs / "包A"], store=env.store, library_dir=env.library)
    # 扫池腿会写描述句 ⇒ 没打标的归零；再手工插一行没描述的（模拟 VLM 没打标的存量）。
    assert env.store.stats()["untagged"] == 0
    env.store.add(md5="noundooned000000000000000000000", path="orphan.png", ext="png")
    assert env.store.stats()["untagged"] == 1
    assert [row["md5"] for row in env.store.list_untagged(limit=5)] == [
        "noundooned000000000000000000000"
    ]


# ---------------------------------------------------------------- 6. 零 Config 读点


def test_module_has_no_config_reads() -> None:
    """本件一个 ``getattr(config, ...)`` 都不写：新键登记归主会话串行落。

    为什么这条要成锁：``tests/test_config_key_registration_ledger.py`` 的「幽灵按名
    读点只准降不准升」按现算执法，未登记键的按名读点会当场把它顶红；而扫池能力又
    必须先在盘上活着，才能接线。显式入参 + 台账里的配置键提案是唯一两不相欠的形状。
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "plugins/bot_unified_runtime/domains/meme/sources/sticker_pool.py"
    ).read_text(encoding="utf-8")
    assert "getattr(config" not in source
    assert "bot_sticker_dir" not in source, "键名一旦写进读点就成幽灵；提案只准住台账"
