"""S-STICKER-LEAK-AUDIT M1/M2「表情册」指令面离线回归（席位 W2R2）。

契约（HANDOFF-STICKER-LEAK-AUDIT-20260929.md §四.1）：
- store 四法（sources/meme_library.py）：
  ``match_md5_prefix(key,*,limit=50)->list[str]``／
  ``relink_path(md5,new_path,*,persona_hint="",persona_owned=True)->bool``／
  ``missing_path_rows(limit=500)->list[dict]``（只报不删）／
  ``admit_into_album(md5,album_dir,*,persona_hint="")->str``
  （moved/no_row/no_file/escape/duplicate_name/error）。
- 指令（capabilities/meme_library.py）：``_ALBUM_RE`` 行首「表情册|表情相冊」+
  动作词 统计/重扫/查重/入册（裸＝统计）；``parse_meme_library_command`` 返
  ("album","<action> <payload>") action∈{stats,rescan,dedupe,admit}，album 分支先于
  stats/review；``handle_meme_album_command(store,config,message,arg)->CapabilityResult``
  admin 门照抄 is_admin_message；audit_tags 含 denied/no_store/unconfigured/not_found/
  ambiguous/need_key。

实现（W1R store / W3R handler）此刻未必落盘：本文件按**契约**写断言，缺失符号经
``_require`` 交回可读的红（归谁一目了然），落盘后自动跑真逻辑。全部离线：tmp_path
构造 store（library_dir 收在容器内）、鸭子 config，零生产库（conftest L1 已挤根）。
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self

import pytest

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import persona_profile
from plugins.bot_unified_runtime.domains.meme.capabilities import (
    meme_library as meme_lib,
)
from plugins.bot_unified_runtime.domains.meme.sources import persona_review
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MD5_PREFIX_ACCEPTED,
    MD5_PREFIX_EMPTY,
    MD5_PREFIX_MIN_LENGTH,
    MD5_PREFIX_NOT_HEX,
    MD5_PREFIX_REJECTIONS,
    MD5_PREFIX_TOO_SHORT,
    MemeLibraryStore,
    _like_prefix_pattern,
    md5_prefix_gate,
)
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    content_sha256_of_bytes,
)

# ------------------------------------------------------------------ 小工具


def _require(obj: Any, name: str, owner: str) -> Any:
    """取一个可能尚未落盘的成员；缺席 ⇒ 交回点名 owner 的红（不放宽断言）。"""
    member = getattr(obj, name, None)
    if member is None:
        pytest.fail(f"{name} 未落盘（归 {owner}）")
    return member


def _png_bytes(side: int = 512, seed: int = 7) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (side, side), (seed % 251, 3, 9)).save(buffer, format="PNG")
    return buffer.getvalue()


def _message(
    text: str, *, sender_id: str = "u1", session_id: str = "group:1"
) -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP,
        group_id=session_id.split(":", 1)[-1],
        sender_id=sender_id,
        plain_text=text,
    )


def _admin_config(sticker_dir: str | Path | None = None) -> SimpleNamespace:
    """鸭子 config：管理员＝900（与审批面夹具同口径），非管理员＝666。

    ``bot_sticker_dir``＝表情册基根（sticker_packs.configured_sticker_dir 读它）；
    传空串＝未配置（测 unconfigured）。
    """
    return SimpleNamespace(
        bot_admin_user_ids=["900"],
        bot_super_admin_user_ids=["900"],
        bot_sticker_dir=str(sticker_dir) if sticker_dir is not None else "",
        bot_meme_library_nsfw_max=0.2,
        bot_meme_library_cooldown_seconds=20,
        bot_meme_relevance_min=0.35,
        bot_meme_sticker_scope_mode="global",
        bot_meme_library_prefer=["守岸人"],
        bot_reactions_sentiment_enabled=False,
        active_persona_id="shorekeeper",
        current_bot_nickname="守岸人",
    )


def _make_store(tmp_path: Path, *, name: str = "lib.sqlite3") -> MemeLibraryStore:
    """直接构造 store；library_dir 收在 tmp_path 下＝media_container 的容器根。"""
    library_dir = tmp_path / "library"
    library_dir.mkdir(parents=True, exist_ok=True)
    return MemeLibraryStore(
        tmp_path / name,
        prefer=[],
        library_dir=library_dir,
    )


def _seed(
    store: MemeLibraryStore,
    md5: str,
    *,
    path: Path,
    ext: str = "png",
    body: bytes | None = None,
    persona_hint: str | None = None,
    persona_owned: bool = False,
    group_id: str = "",
) -> str:
    """把一张图落盘并入一行；persona_hint 非 None 时补标（apply_tags）。

    ``group_id`` 只有第 15 节的泄露面锁要用（判的是「这行有没有第三方出处」），
    缺省空串＝其余夹具逐字照旧。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = body if body is not None else _png_bytes(seed=abs(hash(md5)) % 250)
    path.write_bytes(data)
    store.add(
        md5=md5,
        path=str(path),
        ext=ext,
        group_id=group_id,
        content_sha256=content_sha256_of_bytes(data),
        persona_owned=persona_owned,
    )
    if persona_hint is not None:
        store.apply_tags(md5, persona_hint=persona_hint)
    return content_sha256_of_bytes(data)


def _row(store: MemeLibraryStore, md5: str) -> dict[str, Any] | None:
    with store._connect() as connection:
        cur = connection.execute(
            "SELECT md5, path, ext, persona_hint, persona_owned FROM memes WHERE md5=?",
            (md5,),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None


def _total(store: MemeLibraryStore) -> int:
    with store._connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM memes").fetchone()[0])


# ============================================================ 1. 解析面


def test_parse_album_actions_nine_forms() -> None:
    parse = meme_lib.parse_meme_library_command
    # 裸命令＝统计（stats）
    assert parse("表情册") == ("album", "stats")
    assert parse("/表情册") == ("album", "stats")
    # 四个动作词 → 英文 action，入册带 payload
    assert parse("表情册 统计") == ("album", "stats")
    assert parse("表情册 重扫") == ("album", "rescan")
    assert parse("表情册 查重") == ("album", "dedupe")
    assert parse("表情册 入册 abcd1234") == ("album", "admit abcd1234")
    # 繁形「表情相冊」同认
    assert parse("表情相冊 查重") == ("album", "dedupe")
    # is_meme_library_command 认表情册
    assert meme_lib.is_meme_library_command("表情册") is True
    # 非命令抛 ValueError
    with pytest.raises(ValueError):
        parse("今天天气不错")


def test_album_branch_order_does_not_grab_library_or_pick() -> None:
    """album 分支不得抢走既有 库/统计/偷表情 三形（分支次序 album→review→stats→pick）。"""
    parse = meme_lib.parse_meme_library_command
    # 「表情库统计」「表情库」用「库」字，绝不进 album；仍走 stats 腿。
    assert parse("表情库统计") == ("stats", "")
    assert parse("表情库") == ("stats", "")
    # 「偷表情」仍走 pick 腿。
    assert parse("偷表情") == ("pick", "")


# ============================================================ 2. admin / 配置门


def test_album_denied_for_non_admin_and_untouched(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    base = tmp_path / "base"
    (base / "守岸人").mkdir(parents=True)
    store = _make_store(tmp_path)
    seed_path = store.media_container() / "x1.png"
    _seed(store, "deadbeef0001", path=seed_path, persona_hint="守岸人")
    before = _total(store)
    seed_mtime = seed_path.stat().st_mtime_ns
    result = handler(store, _admin_config(base), _message("表情册 查重", sender_id="666"), "dedupe")
    assert "denied" in result.audit_tags
    # 非管理员：库一个字节都不许动、盘也不动
    assert _total(store) == before
    assert seed_path.exists() and seed_path.stat().st_mtime_ns == seed_mtime


def test_album_unconfigured_zero_scan(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # 册基根＝store 的登记容器（F1 甲案）。未配置的真形是「容器读出来是空」，
    # 而不是 bot_sticker_dir 空——后者是贴纸池那枚键，拿它顶数就是两册混一册。
    decoy = tmp_path / "should_not_scan" / "a.png"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(_png_bytes())
    blank = SimpleNamespace(media_container=lambda: "")
    result = handler(blank, _admin_config(None), _message("表情册 统计", sender_id="900"), "stats")
    assert "unconfigured" in result.audit_tags
    assert str(decoy.parent.name) not in result.body
    # 控制腿：同一枚门只在容器读数上翻，给得出容器就照常扫盘（证明上面不是空转）
    with_base = SimpleNamespace(media_container=lambda: decoy.parent)
    scan = handler(with_base, _admin_config(None), _message("表情册 统计", sender_id="900"), "stats")
    assert "unconfigured" not in scan.audit_tags


def test_album_base_ignores_sticker_dir(tmp_path: Path) -> None:
    """F1 回归锁：贴纸池键指向别处时，册账仍以 store 容器为准，不去池子里扫。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    container = tmp_path / "library"
    album = container / "册甲"
    album.mkdir(parents=True)
    (album / "one.png").write_bytes(_png_bytes(seed=3))
    elsewhere = tmp_path / "sticker_pool"
    (elsewhere / "册乙").mkdir(parents=True)
    result = handler(
        _make_store(tmp_path),
        _admin_config(elsewhere),
        _message("表情册 统计", sender_id="900"),
        "stats",
    )
    assert "册甲" in result.body
    assert "册乙" not in result.body


# ============================================================ 3. 统计


def test_album_stats_counts_and_prunes_dot_underscore(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # 册落在 store 的登记容器里（生产同形：BOT_MEME_LIBRARY_DIR 就是册根）。
    base = tmp_path / "library"
    album_a = base / "册A"
    album_b = base / "册B"
    (album_a / "标签1").mkdir(parents=True)
    album_b.mkdir(parents=True)
    # 剪枝对象：点/下划线前缀目录（即便有图也不该被当册）
    pruned = base / ".hidden"
    pruned.mkdir(parents=True)
    for index in range(2):
        (album_a / f"a{index}.png").write_bytes(_png_bytes(seed=index))
    (album_a / "标签1" / "t.png").write_bytes(_png_bytes(seed=20))
    (album_b / "b0.png").write_bytes(_png_bytes(seed=30))
    (pruned / "h.png").write_bytes(_png_bytes(seed=40))
    (base / "_internal").mkdir()
    result = handler(store=_make_store(tmp_path), config=_admin_config(base), message=_message("表情册 统计", sender_id="900"), arg="stats")
    body = result.body
    assert "册A" in body and "册B" in body
    assert ".hidden" not in body and "_internal" not in body


# ============================================================ 4. 查重


def test_album_dedupe_cross_album_cap20_no_abspath(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # S1 修根（2026-10-01 变异复查）：册树一度建在 ``tmp_path/base``，而产品读的登记根
    # 是 ``store.media_container()``（＝``tmp_path/library``）⇒ 查重腿压根没被走到，
    # 「命中数 ≤20」跑在空集上自证（把 ``_ALBUM_DUPE_LIMIT`` 整条摘掉也全绿）。
    # 现在册树就建在登记根里，判据才咬得住。
    store = _make_store(tmp_path)
    base = store.media_container()
    a = base / "册A"
    b = base / "册B"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    # 造 22 对跨册同 stem（>20 ⇒ 应被上限截到 20）
    for index in range(22):
        stem = f"dup{index:04d}"
        (a / f"{stem}.png").write_bytes(_png_bytes(seed=index))
        (b / f"{stem}.png").write_bytes(_png_bytes(seed=100 + index))
    result = handler(store, _admin_config(base), _message("表情册 查重", sender_id="900"), "dedupe")
    body = result.body
    # 先自证这枚判据跑在非空集上：真扫到了 44 张、真报了 22 对
    assert "clean" not in result.audit_tags, f"两册 22 对同编号竟被判成干净：{result.audit_tags}"
    assert "pairs:22" in result.audit_tags, result.audit_tags
    # 不出现绝对路径（基根串/驱动器符号都不许露，只报册名对）
    assert str(base) not in body
    assert ":\\" not in body and str(tmp_path) not in body
    # 上限：命中的同 stem 对不多于 20（dupNNNN 至多 20 个）
    hits = [f"dup{index:04d}" for index in range(22) if f"dup{index:04d}" in body]
    assert len(hits) <= 20
    # 截断必须恰好截到 20，且**当场公告**没列出的那 2 对（不许静吃）
    assert len(hits) == 20, f"查重上限没截到位：实得 {len(hits)} 对"
    assert "dup0020" not in body and "dup0021" not in body, "被截断的那两对不许露出来"
    assert "另有 2 对没列出" in body, f"截断没公告＝静吃：{body!r}"
    # 控制腿：两对时一张不截、也不许冒出「另有」那句（证明上面那条公告不是恒常噪音）
    other_root = tmp_path / "other_library"
    other_root.mkdir(parents=True)
    other = MemeLibraryStore(tmp_path / "lib2.sqlite3", prefer=[], library_dir=other_root)
    for stem in ("aa000001", "aa000002"):
        for pack in ("册甲", "册乙"):
            leaf = other_root / pack
            leaf.mkdir(parents=True, exist_ok=True)
            (leaf / f"{stem}.png").write_bytes(_png_bytes(seed=6))
    control = handler(
        other, _admin_config(other_root), _message("表情册 查重", sender_id="900"), "dedupe"
    )
    assert "pairs:2" in control.audit_tags and "另有" not in control.body, control.audit_tags


# ============================================================ 5. 入册三岔（handler）


def _seed_for_admit(tmp_path: Path, md5: str) -> tuple[MemeLibraryStore, Path, Path]:
    """容器＝登记根本身（生产同形：sticker dir 就是库目录）。

    admit_into_album 用 store.media_container() 判越界，册必须落在容器内，
    否则真身会诚实地报 ``escape``（不是「moved」）。
    """
    base = tmp_path / "sticker"
    base.mkdir(parents=True, exist_ok=True)
    store = MemeLibraryStore(tmp_path / "lib.sqlite3", prefer=[], library_dir=base)
    target_album = base / "守岸人"
    target_album.mkdir(parents=True, exist_ok=True)
    source = base / f"{md5}.png"
    _seed(store, md5, path=source, persona_hint="守岸人")
    # 入册有出处门：没过审的行真身会诚实回 ``not_admitted``。要验「搬动」这条正面路径，
    # 先把行批准 —— 这是补齐夹具，不是迁就实现。
    store.set_review_state(md5, persona_review.ADMIT)
    return store, base, target_album


def test_admit_into_album_refuses_unapproved_row(tmp_path: Path) -> None:
    """出处门：没过审的行不许被搬进人格册（贴纸腿纯走文件、不过 DB 判据）。"""
    store, _base, album = _seed_for_admit(tmp_path, "gate0001")
    source = store.media_container() / "gate0001.png"
    store.set_review_state("gate0001", "")
    admit = _require(store, "admit_into_album", "W1R")
    assert admit("gate0001", str(album), persona_hint="Shorekeeper") == "not_admitted"
    assert source.is_file(), "拒绝时原文件必须仍在原位"
    assert not list(album.glob("*.png")), "拒绝时册内不得多出文件"
    assert _row(store, "gate0001")["path"] == str(source)
    store.set_review_state("gate0001", persona_review.ADMIT)
    assert admit("gate0001", str(album), persona_hint="Shorekeeper") == "moved"


def test_album_admit_not_found_when_zero(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store, base, _ = _seed_for_admit(tmp_path, "aaaa1111")
    result = handler(store, _admin_config(base), _message("表情册 入册 zzzz", sender_id="900"), "admit zzzz")
    assert "not_found" in result.audit_tags
    assert "need_key" in handler(store, _admin_config(base), _message("表情册 入册", sender_id="900"), "admit").audit_tags


def test_album_admit_executes_when_unique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # match_md5_prefix 按契约交回**裸 md5 串**（list[str]），行上的人格提示读不出来
    # ⇒ 目标册回落到「现役人格展示名」。生产里 persona_profile 已配好；测试把它钉成
    # 「守岸人」（与 base 下那本同名册对上），这是**补齐夹具**不是迁就实现。
    monkeypatch.setattr(persona_profile, "active_persona_id", lambda *a, **k: "shorekeeper")
    monkeypatch.setattr(
        persona_profile, "current_bot_nickname", lambda *a, **k: "守岸人"
    )
    store, base, target_album = _seed_for_admit(tmp_path, "abcd1234ef56")
    source = store.media_container() / "abcd1234ef56.png"
    result = handler(store, _admin_config(base), _message("表情册 入册 abcd", sender_id="900"), "admit abcd")
    assert "ambiguous" not in result.audit_tags and "not_found" not in result.audit_tags
    assert "moved" in result.audit_tags
    # 文件真搬进册、原文件不在容器散件区、DB path 指册内且 persona_owned=1
    assert not source.exists()
    moved = list(target_album.glob("*.png"))
    assert moved, "入册后目标册内应有该图"
    row = _row(store, "abcd1234ef56")
    assert row is not None
    assert Path(row["path"]).resolve() == moved[0].resolve()
    assert int(row["persona_owned"]) == 1


def test_album_admit_ambiguous_lists_md5_prefixes(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # 前缀须 ≥4 且全十六进制（MD5_PREFIX_MIN_LENGTH=4），两行共享「abcd」前缀 ⇒ 命中 2 张
    store, base, _ = _seed_for_admit(tmp_path, "abcd1111")
    second = store.media_container() / "abcd2222.png"
    _seed(store, "abcd2222", path=second, persona_hint="守岸人")
    result = handler(store, _admin_config(base), _message("表情册 入册 abcd", sender_id="900"), "admit abcd")
    assert "ambiguous" in result.audit_tags
    assert "abcd1111" in result.body and "abcd2222" in result.body


# ============================================================ 6. admit_into_album 六状态码（store）


def test_admit_into_album_moved(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    source = store.media_container() / "mv001122.png"
    _seed(store, "mv001122", path=source, persona_hint="common")
    store.set_review_state("mv001122", persona_review.ADMIT)
    album_dir = store.media_container() / "守岸人册"
    status = admit("mv001122", album_dir, persona_hint="守岸人")
    assert status == "moved"
    assert not source.exists()
    moved = list(album_dir.glob("mv001122*"))
    assert moved
    row = _row(store, "mv001122")
    assert Path(row["path"]).resolve() == moved[0].resolve()
    assert int(row["persona_owned"]) == 1
    assert row["persona_hint"] == "守岸人"


def test_admit_into_album_no_row(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    album_dir = store.media_container() / "册"
    status = admit("ghost000", album_dir, persona_hint="守岸人")
    assert status == "no_row"


def test_admit_into_album_no_file(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    source = store.media_container() / "nofile99.png"
    _seed(store, "nofile99", path=source)
    store.set_review_state("nofile99", persona_review.ADMIT)
    source.unlink()  # 行在、盘上文件没了
    album_dir = store.media_container() / "册"
    status = admit("nofile99", album_dir, persona_hint="守岸人")
    assert status == "no_file"
    assert _row(store, "nofile99") is not None  # 绝不因缺文件删行


def test_admit_into_album_escape(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    source = store.media_container() / "esc11223.png"
    _seed(store, "esc11223", path=source)
    store.set_review_state("esc11223", persona_review.ADMIT)
    before = _row(store, "esc11223")
    outside = tmp_path / "outside_album"  # 容器之外
    outside.mkdir(parents=True)
    status = admit("esc11223", outside, persona_hint="守岸人")
    assert status == "escape"
    # 原文件原位、DB 未变
    assert source.exists()
    after = _row(store, "esc11223")
    assert after["path"] == before["path"] and int(after["persona_owned"]) == int(before["persona_owned"])


def test_admit_into_album_duplicate_name(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    source = store.media_container() / "dupname.png"
    _seed(store, "dupname", path=source, body=_png_bytes(seed=1))
    store.set_review_state("dupname", persona_review.ADMIT)
    album_dir = store.media_container() / "册"
    album_dir.mkdir(parents=True, exist_ok=True)
    clash = album_dir / "dupname.png"
    clash.write_bytes(_png_bytes(seed=250))  # 册内已有同名
    status = admit("dupname", album_dir, persona_hint="守岸人")
    assert status == "duplicate_name"
    # 不覆盖（同名文件字节不变）、不删源（源仍在）
    assert source.exists()
    assert clash.read_bytes() == _png_bytes(seed=250)


def test_admit_into_album_error(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    admit = _require(store, "admit_into_album", "W1R")
    source = store.media_container() / "boom.png"
    _seed(store, "boom", path=source)
    store.set_review_state("boom", persona_review.ADMIT)
    before = _total(store)
    # album_dir 指到一个**普通文件** ⇒ shutil.move 必抛 ⇒ 应被兜住返回 error，行不消失
    blocker = store.media_container() / "blocker.txt"
    blocker.write_text("not a dir")
    status = admit("boom", blocker / "impossible", persona_hint="守岸人")
    assert status == "error"
    assert _total(store) == before


# ============================================================ 7. missing_path_rows


def test_missing_path_rows_reports_only_and_respects_limit(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    missing_fn = _require(store, "missing_path_rows", "W1R")
    present = store.media_container() / "present.png"
    _seed(store, "present", path=present, persona_hint="守岸人")
    # 造 3 行「盘上文件缺失」
    gone_paths: list[Path] = []
    for index in range(3):
        md5 = f"gone{index:06d}"
        path = store.media_container() / f"{md5}.png"
        _seed(store, md5, path=path, persona_hint="common")
        path.unlink()
        gone_paths.append(path)
    before = _total(store)
    rows = missing_fn(limit=500)
    # 只报不删
    assert _total(store) == before
    # 键齐 & 报出缺失行
    if rows:
        for key in ("md5", "path", "persona_hint", "ext"):
            assert key in rows[0]
    reported = {str(row["md5"]) for row in rows}
    assert {"gone000000", "gone000001", "gone000002"} <= reported
    assert "present" not in reported
    # limit 生效：3 行缺失时 limit=2 ⇒ 至多 2
    assert len(missing_fn(limit=2)) <= 2


# ============================================================ 8. relink_path


def test_relink_path_escape_returns_false_and_db_unchanged(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    relink = _require(store, "relink_path", "W1R")
    source = store.media_container() / "rl.png"
    _seed(store, "rl", path=source, persona_hint="common")
    before = _row(store, "rl")
    outside = tmp_path / "elsewhere" / "rl.png"
    assert relink("rl", str(outside), persona_hint="守岸人") is False
    after = _row(store, "rl")
    assert after["path"] == before["path"]
    assert after["persona_hint"] == before["persona_hint"]


def test_relink_path_updates_path_and_only_nonempty_hint(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    relink = _require(store, "relink_path", "W1R")
    source = store.media_container() / "rl2.png"
    _seed(store, "rl2", path=source, persona_hint="common")
    new_in_container = store.media_container() / "moved" / "rl2.png"
    new_in_container.parent.mkdir(parents=True, exist_ok=True)
    new_in_container.write_bytes(_png_bytes(seed=9))
    # 空 hint ⇒ 只改 path，persona_hint 保持原值
    assert relink("rl2", str(new_in_container)) is True
    row = _row(store, "rl2")
    assert Path(row["path"]).resolve() == new_in_container.resolve()
    assert row["persona_hint"] == "common"
    # 非空 hint ⇒ 才写 persona_hint
    assert relink("rl2", str(new_in_container), persona_hint="守岸人") is True
    assert _row(store, "rl2")["persona_hint"] == "守岸人"


# ============================================================ 9. match_md5_prefix


def test_match_md5_prefix_empty_and_illegal_returns_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    match = _require(store, "match_md5_prefix", "W1R")
    _seed(store, "cafe0001", path=store.media_container() / "c.png")
    assert match("") == []
    assert match("   ") == []
    assert match("非十六进制xx") == []


def test_match_md5_prefix_wildcards_do_not_widen_hits(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    match = _require(store, "match_md5_prefix", "W1R")
    # 种子必须是**真十六进制**且共享 ≥4 位前缀：否则查询会被「非十六进制/太短」
    # 那道闸先挡成 []，断言就跑在空集上自证（本机踩过的假绿形态）。
    shared = "73616d"  # "same" 的十六进制编码形态，五枚种子共享这 6 位
    for index in range(5):
        md5 = f"{shared}{index:026d}"
        _seed(store, md5, path=store.media_container() / f"{md5}.png")
    # 控制腿：同一前缀不带通配符**必须**有货，否则下面两条空集判据毫无意义。
    assert len(match(shared)) == 5
    # SQL LIKE 通配符不得被当字面量前缀放大命中集
    assert match(f"{shared}%") == []
    assert match(f"{shared}_") == []


def test_match_md5_prefix_respects_limit(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    match = _require(store, "match_md5_prefix", "W1R")
    shared = "73616d"
    for index in range(5):
        md5 = f"{shared}{index:026d}"
        _seed(store, md5, path=store.media_container() / f"{md5}.png")
    def _of(item: Any) -> str:
        # 兼容两种返回形（裸 md5 串 / 行字典）：F2 在改返回形，断言不该因此各改一遍。
        return str(item["md5"]) if isinstance(item, dict) else str(item)

    # 不带上限＝5 枚（控制腿，保证下面的截断是真截断不是空集）
    assert len(match(shared)) == 5
    hits = [_of(item) for item in match(shared, limit=2)]
    assert len(hits) == 2, f"limit=2 必须恰好截到 2 枚，实得 {hits}"
    assert all(h.startswith(shared) for h in hits)


# ============================================================ 10. 隐私锁


def test_album_never_reads_outside_base(tmp_path: Path) -> None:
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    # S1 修根（2026-10-01 变异复查）：原先把「基根」写成 ``tmp_path/base``，而产品读的
    # 是 ``store.media_container()``（＝``tmp_path/library``）⇒ 扫描面是空目录，三条判据
    # 全部跑在空集上（把 ``_album_stats`` 改成扫 ``base.parent`` 也全绿）。
    # 现在基根＝登记根本人，登记根**之外**的诱饵改成一册「目录」（册名会被端进回执），
    # 越界扫描当场红。
    store = _make_store(tmp_path)
    base = store.media_container()
    inside = base / "守岸人"
    inside.mkdir(parents=True)
    (inside / "在册.png").write_bytes(_png_bytes(seed=120))
    # 基根**之外**放一本同名形状的诱饵册（目录名会出现在统计回执里）
    decoy_dir = tmp_path / "other_persona"
    decoy_album = decoy_dir / "秘密册"
    decoy_album.mkdir(parents=True)
    decoy = decoy_album / "秘密.png"
    decoy.write_bytes(_png_bytes(seed=200))
    decoy_mtime = decoy.stat().st_mtime_ns
    result = handler(store, _admin_config(base), _message("表情册 统计", sender_id="900"), "stats")
    # 基根外诱饵未被触碰、也未出现在回执里（三形各判一次：册名 / 文件名字面 / 根串）
    assert decoy.exists() and decoy.stat().st_mtime_ns == decoy_mtime
    assert "秘密" not in result.body
    assert "other_persona" not in result.body and "秘密册" not in result.body
    assert "《守岸人》" in result.body  # 自证：在册那一本真的被端出来了（不是空集判据）
    assert "albums:1" in result.audit_tags, (
        f"只登记了一册，回执却数出别的册＝扫到基根外了：{result.audit_tags}"
    )
    lowered = result.body.lower()
    for leak in (str(tmp_path), str(base), ":\\"):
        assert leak.lower() not in lowered, f"统计回执漏出绝对路径形态：{leak!r}"


# ==================================== 11. 判据覆盖度补齐（席位 T20，2026-10-01）
#
# 补的格子（母格＝四道门 × 四动作 × admit 三岔；本族原先只跑过
# denied×dedupe、unconfigured×stats、admit 三岔无 abspath 判据，rescan 整条腿零锁）：
#   ① 门 × 动作**全矩阵**：denied / no_store / unconfigured / root_absent 各跑遍四动作；
#   ② 简繁两形 × 裸命令 × 四动作词的解析（含全角空格、`!` `！` `/` 前导、尾随空白）；
#   ③ 未知动作词一律落回只读腿（写面不因同义词扩大）；
#   ④ album 分支先于 review/stats（拿带「待审/审批」词面的册面串当探针）；
#   ⑤ 重扫：回执「本轮待对」＝库报出的失配行数、重链＋仍失配＝待对、零候选与多候选
#      原样不动、回执不含绝对路径；
#   ⑥ 入册 ≥2 命中：只回显编号前缀、不搬任何一张、不给绝对路径。
# 判据分母一律从 `_ALBUM_ACTION_WORDS` / `_REVIEW_KEY_DIGITS` 派生，不手写计数（规则 10）。


_ALBUM_PREFIXES: tuple[str, ...] = ("表情册", "表情相冊")  # _ALBUM_RE 的两形（简繁成对）


def _album_action_words() -> dict[str, str]:
    """动作词表真身（派生分母，不许在断言里抄一份）。"""
    table = getattr(meme_lib, "_ALBUM_ACTION_WORDS", None)
    if not isinstance(table, dict):
        pytest.fail("_ALBUM_ACTION_WORDS 未落盘（归 W3R）")
    assert table, "动作词表为空 ⇒ 下面的派生矩阵会在空集上自证"
    return table


def _album_action_codes() -> list[str]:
    codes = sorted({str(value) for value in _album_action_words().values()})
    assert codes, "动作码集合为空 ⇒ 矩阵腿空转"
    assert {"stats", "rescan", "dedupe", "admit"} <= set(codes), codes
    return codes


def _album_arg_for(code: str) -> str:
    """配一句合法 arg：只有 admit 需要编号前缀，其余动作带前缀也只当尾巴忽略。"""
    return f"{code} abcd1111" if code == "admit" else code


def _album_disk_files(root: Path) -> dict[str, tuple[int, int]]:
    """登记根快照（相对名 → 字节数+mtime_ns）：零盘动作就靠它比对。"""
    return {
        str(item.relative_to(root)): (item.stat().st_size, item.stat().st_mtime_ns)
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


def test_album_alias_and_bare_forms_parse_for_every_action_word() -> None:
    """②简繁两形都认，裸命令＝统计（误触零代价），四动作词两形都能折成动作码。"""
    parse = meme_lib.parse_meme_library_command
    codes = set(_album_action_codes())
    table = _album_action_words()
    admit_word = next(word for word, code in table.items() if code == "admit")
    assert codes and admit_word
    for prefix in _ALBUM_PREFIXES:
        assert meme_lib.is_meme_library_command(prefix) is True
        for bare in (prefix, f"/{prefix}", f"!{prefix}", f"！{prefix}", f"{prefix} \t "):
            assert parse(bare) == ("album", "stats"), f"裸命令必须＝统计：{bare!r}"
        for word, code in sorted(table.items()):
            assert parse(f"{prefix} {word}") == ("album", code), f"{prefix} {word}"
            assert parse(f"{prefix}　{word}") == ("album", code), f"全角空格：{prefix} {word}"
            assert parse(f"!{prefix}  {word} ") == ("album", code), f"前后缀噪声：{word}"
        assert parse(f"{prefix} {admit_word} abcd1234") == ("album", "admit abcd1234")


def test_album_unknown_action_word_falls_back_to_readonly_stats() -> None:
    """③首词不在动作词表 ⇒ 一律落回只读腿：读侧加词面永远不扩写面。"""
    parse = meme_lib.parse_meme_library_command
    table = _album_action_words()
    write_side = set(_album_action_codes()) - {"stats"}
    assert write_side, "写面动作码为空 ⇒ 这条落回判据毫无意义"
    for word in ("删除", "清空", "审批", "待审", "列表", "list", "导出"):
        assert word not in table, f"夹具前提破了：{word} 已成了动作词"
        for prefix in _ALBUM_PREFIXES:
            parsed = parse(f"{prefix} {word}")
            assert parsed == ("album", "stats"), f"{prefix} {word} ⇒ {parsed!r}（未知首词必须落只读腿）"


def test_album_branch_precedes_review_and_stats_branches() -> None:
    """④分支次序 album→review→stats→pick：册面串带审批/统计词面时仍须归 album。"""
    parse = meme_lib.parse_meme_library_command
    for prefix in _ALBUM_PREFIXES:
        assert parse(f"{prefix} 待审") == ("album", "stats"), prefix
        assert parse(f"{prefix} 审批 通过 abcd1234") == ("album", "stats 通过 abcd1234"), prefix
        assert parse(f"{prefix} 统计 查重") == ("album", "stats 查重"), prefix
    # 控制腿：review / stats 两条腿本身活着（不是把 album 排前面就把它们整族吃了）
    assert parse("表情库 待审")[0] == "review"
    assert parse("表情库统计") == ("stats", "")
    assert parse("偷表情") == ("pick", "")


def test_album_non_admin_denied_for_every_action_and_zero_disk(tmp_path: Path) -> None:
    """⑤非管理员 × 四动作一律 denied，且库里盘上零动作（门在动作分派之前）。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store = _make_store(tmp_path)
    base = store.media_container()
    album = base / "守岸人"
    album.mkdir(parents=True, exist_ok=True)
    (album / "in.png").write_bytes(_png_bytes(seed=13))
    loose: dict[str, Path] = {}
    for index, md5 in enumerate(("deadbeef0001", "deadbeef0002")):
        path = base / f"loose{index}.png"
        _seed(store, md5, path=path, persona_hint="守岸人")
        loose[md5] = path
    disk_before = _album_disk_files(base)
    assert disk_before, "登记根里必须有文件，否则『零盘动作』是空话"
    rows_before = {md5: _row(store, md5) for md5 in loose}
    total_before = _total(store)
    for code in _album_action_codes():
        result = handler(
            store, _admin_config(base), _message("表情册", sender_id="666"), _album_arg_for(code)
        )
        assert "denied" in result.audit_tags, code
        extra = [t for t in result.audit_tags if t not in ("meme_library", "album", "denied")]
        assert extra == [], f"非管理员 {code} 竟跑到了动作腿：{extra}"
    assert _total(store) == total_before
    assert _album_disk_files(base) == disk_before
    for md5, path in loose.items():
        assert path.is_file(), md5
        assert _row(store, md5) == rows_before[md5], md5
    # 控制腿：同一枚门只在 sender_id 上翻，管理员拿同一串不吃 denied
    admin = handler(store, _admin_config(base), _message("表情册", sender_id="900"), "stats")
    assert "denied" not in admin.audit_tags and "stats" in admin.audit_tags


def test_album_no_store_gate_for_every_action(tmp_path: Path) -> None:
    """门②store 缺席 × 四动作：一律 no_store，且不往登记根里造任何东西。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store = _make_store(tmp_path)
    base = store.media_container()
    for code in _album_action_codes():
        result = handler(
            None, _admin_config(base), _message("表情册", sender_id="900"), _album_arg_for(code)
        )
        assert "no_store" in result.audit_tags, code
        assert "moved" not in result.audit_tags, code
    assert _album_disk_files(base) == {}, "没有 store 也不许在登记根里造文件"
    assert "no_store" not in handler(
        store, _admin_config(base), _message("表情册", sender_id="900"), "stats"
    ).audit_tags


def test_album_unconfigured_gate_for_every_action(tmp_path: Path) -> None:
    """门③容器读数空 × 四动作：一律 unconfigured；贴纸池那枚键绝不顶数、也不去别处扫。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    decoy_dir = tmp_path / "somewhere_else"
    decoy_dir.mkdir(parents=True)
    (decoy_dir / "a.png").write_bytes(_png_bytes(seed=21))
    blank = SimpleNamespace(media_container=lambda: "")
    for code in _album_action_codes():
        result = handler(
            blank,
            _admin_config(decoy_dir),
            _message("表情册", sender_id="900"),
            _album_arg_for(code),
        )
        assert "unconfigured" in result.audit_tags, code
        assert str(decoy_dir) not in result.body and decoy_dir.name not in result.body
    assert "unconfigured" not in handler(
        SimpleNamespace(media_container=lambda: decoy_dir),
        _admin_config(None),
        _message("表情册", sender_id="900"),
        "stats",
    ).audit_tags


def test_album_root_absent_gate_for_every_action_never_creates(tmp_path: Path) -> None:
    """门④登记根不在盘上 × 四动作：一律 root_absent，且**绝不自动造目录**（诚实缺席）。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    absent = tmp_path / "library_absent"
    duck = SimpleNamespace(media_container=lambda: absent)
    for code in _album_action_codes():
        result = handler(
            duck, _admin_config(None), _message("表情册", sender_id="900"), _album_arg_for(code)
        )
        assert "root_absent" in result.audit_tags, code
    assert not absent.exists(), "登记根缺席时绝不 mkdir 造一本册出来"
    # 控制腿：目录一旦出现，同一枚门就放行到动作腿
    absent.mkdir(parents=True)
    back = handler(duck, _admin_config(None), _message("表情册", sender_id="900"), "stats")
    assert "root_absent" not in back.audit_tags and "stats" in back.audit_tags


def test_album_rescan_counts_match_reported_rows_and_no_abspath(tmp_path: Path) -> None:
    """⑤重扫：待对数＝库报出的失配行数、重链+仍失配＝待对、多/零候选原样不动、无绝对路径。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store = _make_store(tmp_path)
    base = store.media_container()
    album_a = base / "册A"
    album_b = base / "册B"
    album_a.mkdir(parents=True)
    album_b.mkdir(parents=True)
    gone = base / "gone"
    gone.mkdir(parents=True)
    uniq, clash, orphan = "rescan01aa", "rescan02bb", "rescan03cc"
    # 夹具表：每行原先的 path 都指向已删掉的文件；册树里放的候选张数决定这一行落哪一岔
    fixture: dict[str, list[Path]] = {
        uniq: [album_a / f"{uniq}.png"],
        clash: [album_a / f"{clash}.png", album_b / f"{clash}.png"],
        orphan: [],
    }
    original: dict[str, Path] = {}
    for index, md5 in enumerate(sorted(fixture)):
        old = gone / f"{md5}.png"
        _seed(store, md5, path=old)  # persona_hint 留空 ⇒ 重扫不靠提示收窄候选
        # 出处门：没过审的行重扫不认（并发波给 rescan 新加的腿），要验重链这条正路必须先过审
        store.set_review_state(md5, persona_review.ADMIT)
        old.unlink()
        original[md5] = old
        for hit in fixture[md5]:
            hit.write_bytes(_png_bytes(seed=11 + index))
    expected_relinked = sum(1 for hits in fixture.values() if len(hits) == 1)
    expected_unmatched = sum(1 for hits in fixture.values() if len(hits) != 1)
    assert expected_relinked and expected_unmatched, "两岔都得有货，否则下面的一致性判据空转"

    missing_fn = _require(store, "missing_path_rows", "W1R")
    reported_rows = list(missing_fn(limit=500))
    assert {str(row["md5"]) for row in reported_rows} == set(fixture), reported_rows

    result = handler(
        store, _admin_config(base), _message("表情册 重扫", sender_id="900"), "rescan"
    )
    body = result.body
    tags = {t.split(":", 1)[0]: t.split(":", 1)[1] for t in result.audit_tags if ":" in t}
    relinked, unmatched = int(tags["relinked"]), int(tags["missing"])
    # 「另有 N 行…」＝第三岔（在册里但没过审一类）；本轮不该有它，有了就是分账口径变了
    disclosed = 0
    if "另有 " in body:
        digits = "".join(ch for ch in body.split("另有 ", 1)[1].split("行", 1)[0] if ch.isdigit())
        disclosed = int(digits or 0)
    assert disclosed == 0, f"本轮冒出第三岔，两岔分账判据要重算：{body!r}"
    assert relinked == expected_relinked and unmatched == expected_unmatched, body
    marker = "本轮待对"
    assert marker in body, f"回执必须公告本轮对了几行，实得：{body!r}"
    reported = int("".join(ch for ch in body.split(marker, 1)[1].split("行", 1)[0] if ch.isdigit()))
    assert reported == len(reported_rows), f"待对数 ≠ 库报出的失配行数：{reported} vs {len(reported_rows)}"
    assert relinked + unmatched == reported, f"重链+仍失配 ≠ 待对，有行被静吃：{body!r}"
    # 拿库自己的再读数当第二把尺：失配面减少量必须恰好等于「重链」报出的行号数
    rows_after = {str(row["md5"]) for row in missing_fn(limit=500)}
    assert uniq not in rows_after, f"已过审且唯一候选的行必须被重链掉：{rows_after}"
    assert {clash, orphan} <= rows_after, f"多候选／零候选的行不许被猜着改：{rows_after}"
    assert len(rows_after) == reported - relinked, (
        f"失配面减少量 ≠ 重链数：{len(rows_after)} vs {reported}-{relinked}"
    )
    # 唯一候选那行才改路径；多张/零张一律原样不动（猜＝替库写一条没人核对过的路径）
    assert _row(store, uniq)["path"] == str(fixture[uniq][0])
    # 夹具这批发过审了（上面 set_review_state），所以身份可以由重链认领。
    # 「没过审 ⇒ 只认路径不认身份」那半边住在 test_album_rescan_claims_persona_only_for_admitted_row。
    assert int(_row(store, uniq)["persona_owned"]) == 1
    for md5 in (clash, orphan):
        assert _row(store, md5)["path"] == str(original[md5]), f"{md5} 不该被重链"
        assert not (base / "册A" / f"{md5}.relinked").exists()
    for hits in fixture.values():
        for hit in hits:
            assert hit.is_file(), f"重扫绝不删盘上文件：{hit}"
    for leak in (str(tmp_path), str(base), str(gone), ":\\"):
        assert leak not in body, f"重扫回执漏出绝对路径形态：{leak!r}"


def test_album_admit_ambiguous_echoes_prefix_only_and_moves_nothing(tmp_path: Path) -> None:
    """③入册 ≥2 命中：回显编号前缀、不给绝对路径、一张都不搬、行一律不动。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store, base, album = _seed_for_admit(tmp_path, "abcd1111")
    first = store.media_container() / "abcd1111.png"
    second = store.media_container() / "abcd2222.png"
    _seed(store, "abcd2222", path=second, persona_hint="守岸人")
    rows_before = {md5: _row(store, md5) for md5 in ("abcd1111", "abcd2222")}
    digits = int(meme_lib._REVIEW_KEY_DIGITS)
    assert digits > 0

    result = handler(
        store, _admin_config(base), _message("表情册 入册 abcd", sender_id="900"), "admit abcd"
    )
    assert "ambiguous" in result.audit_tags and "moved" not in result.audit_tags
    for md5 in rows_before:
        assert md5[:digits] in result.body, f"回执要回显编号前缀 {md5[:digits]}：{result.body!r}"
    for leak in (str(tmp_path), str(base), ":\\"):
        assert leak not in result.body, f"歧义回执漏出绝对路径：{leak!r}"
    assert first.is_file() and second.is_file()
    assert not list(album.glob("*.png")), f"歧义时一张都不许搬进册：{list(album.glob('*'))}"
    for md5, row in rows_before.items():
        assert _row(store, md5) == row, md5
    assert _total(store) == len(rows_before)
    # 控制腿：把前缀说长到唯一一枚 ⇒ 同一串就真落子（证明上面不是靠门坏掉的红）
    from plugins.bot_unified_runtime.domains.chat_reply.character import persona_profile

    single = handler(
        store, _admin_config(base), _message("表情册 入册 abcd2222", sender_id="900"), "admit abcd2222"
    )
    assert "ambiguous" not in single.audit_tags
    assert "moved" in single.audit_tags or "not_admitted" in single.audit_tags, single.audit_tags
    assert persona_profile is not None


# ==================================== 12. 出处门 ↔ 审批面 通路锁（席位 J1，2026-10-01）

#: 一枚真实形态的 32 位十六进制编号（前 8 位＝回执上露出的那段）。
_LEGACY_MD5 = "cafe0000" + "0" * 24
#: 第二枚空串行，只用来钉「拒绝那条腿的范围没放宽」。
_OTHER_LEGACY_MD5 = "b00b0000" + "0" * 24
#: 比老行更新的行数：刻意大过 ``_REVIEW_MATCH_LIMIT``（50），否则下面这把自己不咬。
_ROWS_BEYOND_WINDOW = 60


def _age_row(store: MemeLibraryStore, md5: str) -> None:
    """把一行改旧，使其落在「按 added_at 取最新 N 行」的窗口之外。

    夹具手段、不是产品旁手：断头路的形状正是「候选池先被 SQL 的 LIMIT 截断、再去
    python 侧筛前缀」。被批的那一行必须是老行，否则这条锁只会假绿。
    """
    with store._connect() as connection:
        connection.execute("UPDATE memes SET added_at=added_at-100000 WHERE md5=?", (md5,))


def _review_state_of(store: MemeLibraryStore, md5: str) -> str:
    with store._connect() as connection:
        row = connection.execute("SELECT review_state FROM memes WHERE md5=?", (md5,)).fetchone()
    return "" if row is None else str(row["review_state"])


def _seed_legacy_pair(tmp_path: Path) -> tuple[MemeLibraryStore, Path, Path, Path]:
    """一库两枚**空串状态**的老行 + 一叠更新的新行（生产 2961/2971 的形状）。

    刻意不走 ``_seed_for_admit``：那枚夹具在 ``:310`` 用 ``store.set_review_state(md5,
    ADMIT)`` 直接写库绕过指令面，正好把「指令面自己批不批得动」这件事测没了。
    """
    base = tmp_path / "sticker"
    base.mkdir(parents=True, exist_ok=True)
    store = MemeLibraryStore(tmp_path / "legacy.sqlite3", prefer=[], library_dir=base)
    album = base / "守岸人"
    album.mkdir(parents=True, exist_ok=True)
    for md5 in (_LEGACY_MD5, _OTHER_LEGACY_MD5):
        _seed(
            store,
            md5,
            path=base / f"{md5}.png",
            persona_hint="守岸人",
            body=_png_bytes(side=8, seed=abs(hash(md5)) % 250),
        )
        _age_row(store, md5)
    for index in range(_ROWS_BEYOND_WINDOW):
        filler = f"{index:032x}"
        _seed(
            store,
            filler,
            path=base / f"{filler}.png",
            persona_hint="路人",
            body=_png_bytes(side=8, seed=index),
        )
    return store, base, album, base / f"{_LEGACY_MD5}.png"


def test_empty_state_row_is_approvable_by_command_face_then_admitted(tmp_path: Path) -> None:
    """``review_state=''``（全部存量行的形状）要能被**指令面**批准，批完即刻入册。

    出处门在 ``not_admitted`` 回执里承诺「先去审批」。若可批集合被焊死在 ``pending``
    上，生产库那 2961 枚空串行照回执去做只会落到 ``review/not_found``——断头路。
    本件走完整通路，**全程不调 ``store.set_review_state``**（旁手一用，测的就不是
    指令面了），也不碰判据：入册第一趟必须仍被拦成 ``not_admitted``。
    """
    review = _require(meme_lib, "handle_meme_review_command", "J1")
    admit_handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store, base, album, source = _seed_legacy_pair(tmp_path)
    short = _LEGACY_MD5[:8]

    assert _review_state_of(store, _LEGACY_MD5) == "", "夹具走形：这一行不再是存量行的形状"

    # ① 出处门照旧拦：判据一字未动
    blocked = admit_handler(
        store, _admin_config(base), _message("表情册 入册 " + short, sender_id="900"), f"admit {short}"
    )
    assert "not_admitted" in blocked.audit_tags, blocked.audit_tags
    assert short in blocked.body and "表情库 审批" in blocked.body, blocked.body
    assert source.is_file(), "被拦时原文件必须仍在原位"
    assert not list(album.glob("*.png")), "被拦时册内不得多出文件"

    # ② 指令面把空串行批下来（这条就是断头路的本体）
    approved = review(
        store, _admin_config(base), _message("/表情库 审批 通过 " + short, sender_id="900"), f"通过 {short}"
    )
    assert "approved" in approved.audit_tags, (
        f"指令面批不动 review_state='' 的老行＝断头路未修（回执让人去审批，"
        f"可批集合却只认 pending）：{approved.audit_tags} / {approved.body!r}"
    )
    assert _review_state_of(store, _LEGACY_MD5) == persona_review.ADMIT
    assert int(_row(store, _LEGACY_MD5)["persona_owned"]) == 1

    # ③ 再报一次入册 ⇒ 文件真搬进册、行跟着改道
    moved = admit_handler(
        store, _admin_config(base), _message("表情册 入册 " + short, sender_id="900"), f"admit {short}"
    )
    assert "moved" in moved.audit_tags, moved.audit_tags
    assert not source.exists()
    in_album = list(album.glob("*.png"))
    assert len(in_album) == 1, in_album
    assert Path(str(_row(store, _LEGACY_MD5)["path"])).resolve() == in_album[0].resolve()


def test_reject_leg_still_only_reaches_the_pending_queue(tmp_path: Path) -> None:
    """拒绝那条腿的范围**一寸没放宽**：删行删文件加立墓碑＝不可逆，照旧只认 pending。

    与上一枚配对才说明放开的是「批准」这一条腿，而不是把整库变成可删集合。
    """
    review = _require(meme_lib, "handle_meme_review_command", "J1")
    store, base, _album, _source = _seed_legacy_pair(tmp_path)
    short = _OTHER_LEGACY_MD5[:8]
    result = review(
        store,
        _admin_config(base),
        _message("/表情库 审批 拒绝 " + short, sender_id="900"),
        f"拒绝 {short}",
    )
    assert "not_found" in result.audit_tags, result.audit_tags
    assert "rejected" not in result.audit_tags
    assert store.exists(_OTHER_LEGACY_MD5), "空串行不得被拒绝那条腿删掉"
    assert _review_state_of(store, _OTHER_LEGACY_MD5) == ""


# ================== 13. 前缀两腿换代锁（席位 J3，2026-10-01）
#
# 对抗复查席把 12 节那批的三格定死了，本节的格子一一对着它们：
#   🔴 甲：拒绝腿仍是「先 ``LIMIT`` 截断、再在 python 侧筛前缀」——实测 60 枚新
#          pending 把 1 枚老 pending 挤出窗口 ⇒ 拒绝落 ``not_found`` 而**行仍在**。
#          锁＝``test_reject_leg_finds_the_pending_row_beyond_the_window``。
#   🔴 乙：``ESCAPE`` 这条防线全树零锁（三种变异全绿）。锁拆三枚：SQL 文本与绑定
#          （``..._binds_escape_and_narrows_before_the_limit``）、转义器自身的契约
#          （``test_like_prefix_pattern_locks_its_own_contract``）、含 ``!`` 的编号
#          在盘上仍可被真前缀够着且通配形态不许放大命中集（``..._bang_...``）。
#   🟠 丙：``match_review_key`` 的 docstring 讲了一件没发生的事（上游原样透传）。
#          选了「变严」那一侧：闸门落在库侧本函数，命令面读同一把尺措辞回执。
#          锁＝不发 SQL（``..._gate_rejects_query_nothing``）＋ 回执措辞
#          （``..._receipts_say_the_prefix_was_too_short``）。
# 每枚都配了变异腿（把改动摘回／退化后必红），读数见席位报告。


def _all_md5s(store: MemeLibraryStore) -> list[str]:
    with store._connect() as connection:
        rows = connection.execute("SELECT md5 FROM memes ORDER BY added_at DESC, md5 ASC")
        return [str(row["md5"]) for row in rows.fetchall()]


class _SpyConnection:
    """``store._connect()`` 的透明壳：记下每条 ``(sql, params)``，其余逐字转发。

    只包这只鸭子、不碰产品件。``with conn:`` 的提交语义照走内层 ``__exit__``。
    """

    def __init__(self, inner: Any, sink: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._inner = inner
        self._sink = sink

    def execute(self, sql: Any, params: Any = ()) -> Any:
        self._sink.append((str(sql), tuple(params or ())))
        return self._inner.execute(sql, params)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> Any:
        return self._inner.__exit__(*exc_info)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _spy_selects(sink: list[tuple[str, tuple[Any, ...]]]) -> list[tuple[str, tuple[Any, ...]]]:
    """只留「读 memes 的 SELECT」——落子/夹具写行的语句不算进这一格账。"""
    reads: list[tuple[str, tuple[Any, ...]]] = []
    for sql, params in sink:
        uppered = sql.upper()
        if uppered.startswith("SELECT") and "FROM MEMES" in uppered:
            reads.append((sql, params))
    return reads


def test_reject_leg_finds_the_pending_row_beyond_the_window(tmp_path: Path) -> None:
    """甲：拒绝腿的前缀收窄必须在 ``LIMIT`` **之前**（SQL 侧），否则老行永远拒不动。

    夹具把 12 节那副翻成「队列里 61 枚 pending、目标是最老那一枚」：窗口只有
    ``_REVIEW_MATCH_LIMIT`` 格，所以「先截断再筛」的写法必然看不见它。可删集合的
    **宽度**（只认 pending）一寸没动——见函数末段那三条。
    """
    review = _require(meme_lib, "handle_meme_review_command", "J1")
    store, base, _album, _source = _seed_legacy_pair(tmp_path)
    for md5 in _all_md5s(store):
        if md5 != _OTHER_LEGACY_MD5:  # 这一枚留作「空串行照样拒不动」的对照
            assert store.set_review_state(md5, persona_review.PENDING) is True
    window = int(meme_lib._REVIEW_MATCH_LIMIT)

    # 夹具自证（不成立则本件整枚假绿）：目标行确实躺在窗口之外。
    queue_head = [str(row["md5"]) for row in store.list_review(persona_review.PENDING, limit=window)]
    assert len(queue_head) == window, f"队列窗口没填满 ⇒ 挤爆窗口这条前提没成立：{len(queue_head)}"
    assert _LEGACY_MD5 not in queue_head, "目标行没被挤出窗口 ⇒ 夹具走形，本件测不到断头路"

    short = _LEGACY_MD5[:8]
    result = review(
        store,
        _admin_config(base),
        _message("/表情库 审批 拒绝 " + short, sender_id="900"),
        f"拒绝 {short}",
    )
    assert "rejected" in result.audit_tags, (
        f"拒绝腿又落回「先截断后筛」＝老 pending 拒不动而**行仍在**："
        f"{result.audit_tags} / {result.body!r}"
    )
    assert not store.exists(_LEGACY_MD5), "回执说拒了，行就必须真的没了"

    # 宽度三条：被挤开窗口的只有目标那一枚，其余 pending 与那枚空串行一个都不许被删。
    assert store.exists(_OTHER_LEGACY_MD5) and _review_state_of(store, _OTHER_LEGACY_MD5) == ""
    for md5 in _all_md5s(store):
        assert md5 != _LEGACY_MD5
        if md5 == _OTHER_LEGACY_MD5:
            continue
        assert _review_state_of(store, md5) == persona_review.PENDING


def test_both_prefix_legs_bind_escape_and_narrow_before_the_limit(tmp_path: Path) -> None:
    """乙①：三条前缀查询腿的 SQL 文本里 ``ESCAPE`` 必在、绑定第二元必是转义符、
    且 ``LIKE`` 必在 ``LIMIT`` **之前**；拒绝腿那支还额外钉着 ``review_state=?`` 在场
    （可删集合宽度被拆了也要当场红）。
    """
    store = _make_store(tmp_path)
    _seed(store, "cafe0000" + "0" * 24, path=store.media_container() / "e.png")
    sink: list[tuple[str, tuple[Any, ...]]] = []
    real_connect = store._connect
    store._connect = lambda: _SpyConnection(real_connect(), sink)  # type: ignore[method-assign]

    store.match_md5_prefix("cafe0000", limit=7)
    store.match_review_key("cafe0000", state=None, limit=9)
    store.match_review_key("cafe0000", state=persona_review.PENDING, limit=11)

    prefix_legs = [entry for entry in _spy_selects(sink) if "LIKE" in entry[0].upper()]
    assert len(prefix_legs) == 3, f"三条前缀腿只看到 {len(prefix_legs)} 条：{prefix_legs}"
    for sql, params in prefix_legs:
        assert "ESCAPE ?" in sql, f"这一腿的 ESCAPE 被摘了（值就不再按字面比对了）：{sql!r}"
        assert sql.index("LIKE") < sql.index("LIMIT"), (
            f"前缀收窄排在截断之后＝只对最新 N 行有效：{sql!r}"
        )
        assert sql.rstrip().endswith("LIMIT ?"), f"LIMIT 后面不该再挂别的槽：{sql!r}"
    # 绑定形状：LIKE 模式在第一元、转义符在第二元；值一律走参数、SQL 文本里不拼值。
    for sql, params in prefix_legs:
        assert params[0] == _like_prefix_pattern("cafe0000"), (sql, params)
        assert params[1] == "!", f"ESCAPE 绑定的转义符不是那枚：{params!r}"
        assert "cafe0000" not in sql, f"用户输入被拼进了 SQL 文本：{sql!r}"
    album_leg, approve_leg, reject_leg = prefix_legs
    assert "review_state=?" not in album_leg[0] and "review_state=?" not in approve_leg[0]
    assert "review_state=?" in reject_leg[0], f"拒绝腿丢了队列位＝可删集合被放宽：{reject_leg}"
    assert reject_leg[1] == (_like_prefix_pattern("cafe0000"), "!", persona_review.PENDING, 11)
    assert approve_leg[1] == (_like_prefix_pattern("cafe0000"), "!", 9)


def test_prefix_gate_rejects_query_nothing_at_all(tmp_path: Path) -> None:
    """丙：形状闸门落在库侧本函数，**不合格连一次 SELECT 都不发**（旧 docstring
    把这件事记成「上游已只放行十六进制」，那是件没发生的事）。
    """
    store = _make_store(tmp_path)
    _seed(store, "cafe0000" + "0" * 24, path=store.media_container() / "g.png")
    sink: list[tuple[str, tuple[Any, ...]]] = []
    real_connect = store._connect
    store._connect = lambda: _SpyConnection(real_connect(), sink)  # type: ignore[method-assign]

    rejected: list[tuple[str, str]] = [
        ("a", MD5_PREFIX_TOO_SHORT),
        ("caf", MD5_PREFIX_TOO_SHORT),
        ("zzzz", MD5_PREFIX_NOT_HEX),
        ("cafe%", MD5_PREFIX_NOT_HEX),
        ("cafe_", MD5_PREFIX_NOT_HEX),
        ("cafe!", MD5_PREFIX_NOT_HEX),
        ("café0000", MD5_PREFIX_NOT_HEX),
        ("   ", MD5_PREFIX_EMPTY),
    ]
    for key, reason in rejected:
        assert md5_prefix_gate(key) == reason, f"闸门读数走形：{key!r}→{md5_prefix_gate(key)!r}"
        assert store.match_review_key(key, state=None) == []
        assert store.match_review_key(key, state=persona_review.PENDING) == []
        assert store.match_md5_prefix(key) == []
    assert _spy_selects(sink) == [], f"不合格的前缀仍然查了库：{_spy_selects(sink)}"
    assert MD5_PREFIX_ACCEPTED == "" and md5_prefix_gate("CAFE0000") == MD5_PREFIX_ACCEPTED
    # 闸门的原因集本体：多一格就得在这儿多钉一行，少一格本件当场红（防「原因被吃掉」）。
    assert set(MD5_PREFIX_REJECTIONS) == {MD5_PREFIX_EMPTY, MD5_PREFIX_TOO_SHORT, MD5_PREFIX_NOT_HEX}
    assert {reason for _, reason in rejected} >= set(MD5_PREFIX_REJECTIONS)

    # 控制腿：闸门没焊死在「一律拒」上——合格前缀照样发一条 SELECT 且捞得到行。
    assert store.match_review_key("cafe0000", state=None) != []
    assert len(_spy_selects(sink)) == 1, _spy_selects(sink)
    assert store.match_md5_prefix("cafe0000") != []


def test_like_prefix_pattern_locks_its_own_contract() -> None:
    """乙③：转义器自身的契约（``!`` 翻倍、``%``/``_`` 各自被压成字面、尾部补一个
    真通配）。退化成 ``key + "%"`` 的写法在这枚面前当场红——它是唯一还能**行为上**
    抓到「helper 退化」的那格：两道十六进制闸门之后，带通配符的 key 根本进不了 SQL。
    """
    assert _like_prefix_pattern("cafe") == "cafe%"
    assert _like_prefix_pattern("cafe%") == "cafe!%%"
    assert _like_prefix_pattern("cafe_") == "cafe!_%"
    assert _like_prefix_pattern("cafe!") == "cafe!!%"
    assert _like_prefix_pattern("a!%_") == "a!!!%!_%"


def test_stored_bang_in_md5_is_reachable_but_not_a_wildcard(tmp_path: Path) -> None:
    """乙②：编号里真躺着一枚 ``!``（``add`` 不筛形态 ⇒ 生产上就可能有这种行）时，

    - 真前缀必须**够得着**它（控制腿：下面第一条不成立，后面几条就是空集自证）；
    - ``%`` / ``_`` / ``!`` 形态的前缀一律不得把它当通配命中。
    """
    store = _make_store(tmp_path)
    bang = "cafe0000!deadbeef00000000000000"
    twin = "cafe0001" + "f" * 24
    _seed(store, bang, path=store.media_container() / "bang.png")
    _seed(store, twin, path=store.media_container() / "twin.png")
    store.set_review_state(bang, persona_review.PENDING)

    assert [str(r["md5"]) for r in store.match_review_key("cafe0000", state=None)] == [bang]
    assert [str(r["md5"]) for r in store.match_md5_prefix("cafe0000")] == [bang]
    # 通配形态：一条都不许多（不许把两枚、也不许把那枚 twin 捞进来）。
    for key in ("cafe0000%", "cafe0000_", "cafe0000!", "cafe000%", "cafe000!"):
        assert store.match_review_key(key, state=None) == [], key
        assert store.match_review_key(key, state=persona_review.PENDING) == [], key
        assert store.match_md5_prefix(key) == [], key
    # 控制腿二：同一族里 7 位的合格前缀该把两枚都捞出来（证明上面的 [] 是闸门判的，
    # 不是「这批行本来就查不到」——那是本机踩过的空集自证）。
    assert {str(r["md5"]) for r in store.match_review_key("cafe000", state=None)} == {bang, twin}


def test_review_receipts_say_the_prefix_was_too_short(tmp_path: Path) -> None:
    """丙（回执侧）：太短／形状不对都不能说成「库里没有」，且一次落子都不许发生。

    ``test_ambiguous_prefix_asks_instead_of_guessing``（另一件，非本席写面）拿单字符
    前缀钉着「先问不落子」；本席把那条判据措辞成「太短」而不是「没图」，两支审计标签
    同族（``ambiguous`` + ``prefix_too_short``），那一件照旧绿。
    """
    review = _require(meme_lib, "handle_meme_review_command", "J1")
    store, base, _album, _source = _seed_legacy_pair(tmp_path)
    store.set_review_state(_LEGACY_MD5, persona_review.PENDING)

    too_short = review(
        store,
        _admin_config(base),
        _message("/表情库 审批 拒绝 caf", sender_id="900"),
        "拒绝 caf",
    )
    assert "prefix_too_short" in too_short.audit_tags, too_short.audit_tags
    assert "ambiguous" in too_short.audit_tags, too_short.audit_tags
    assert "没有" not in too_short.body, f"回执把「你没说清」讲成了「库里没图」：{too_short.body!r}"
    assert str(MD5_PREFIX_MIN_LENGTH) in too_short.body, too_short.body

    malformed = review(
        store,
        _admin_config(base),
        _message("/表情库 审批 通过 cafe000%", sender_id="900"),
        "通过 cafe000%",
    )
    assert "prefix_not_hex" in malformed.audit_tags, malformed.audit_tags
    assert "没有" not in malformed.body, malformed.body

    assert store.exists(_LEGACY_MD5), "闸门拒收的两次里，行一个字节都不许动"
    assert _review_state_of(store, _LEGACY_MD5) == persona_review.PENDING
    assert _row(store, _LEGACY_MD5) is not None


# ================== 14. 空转格补锁（席位 S1，2026-10-01 仓外变异复查）
#
# 母格＝「把产品腿摘掉／退化后，本文件必须红」。四枚变异在补锁前**全绿**（读数见
# ``%TEMP%\cb-s1\REPORT.md``），逐枚对应本节一格：
#   S37/S49 ``_album_rescan`` 的出处门第二条腿（未过审 ⇒ 只认路径不认身份）整条摘掉 ⇒
#     全绿。8 节那枚判词写着「那半边住在
#     ``test_album_rescan_claims_persona_only_for_admitted_row``」——**该用例全树不存**
#     （死指针），于是「重扫替没过审的行宣身份」这条真洞没人咬。
#   S38 重扫零失配那支（``nothing_missing``）改成死路 ⇒ 全绿（11 节⑤自称覆盖了）。
#   S47 入册「行上没提示才登记册名」那一支永远交空串 ⇒ 全绿（F2 的登记面）。
#   S48 目标册缺席时回落到现役人格那本（把图塞进别的册） ⇒ 全绿。
#   S44 ``_REVIEW_RE`` 词面并进「表情册」后本族零红：分支次序本身无串可证伪（三族词面
#     天然互斥），要钉的其实是**互斥前提**，本节末一枚钉它。
# 只补不放宽：12/13 两节既有判据一字未动。


def test_album_rescan_claims_persona_only_for_admitted_row(tmp_path: Path) -> None:
    """重扫的出处门第二条腿：未过审那行**只认路径、不认身份**；过审那行照认（控制腿）。

    文件躺在人格册目录里 ≠ 它被批准进册。发送面纯走文件遍历、不过 DB，所以机器一旦
    替没过审的行宣了 ``persona_owned``／册名，那本册子就凭空多出一张没人点头的册图。
    """
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store = _make_store(tmp_path)
    base = store.media_container()
    album = base / "守岸人"
    album.mkdir(parents=True)
    gone = base / "旧位置"
    gone.mkdir(parents=True)
    unapproved_md5, approved_md5 = "rescan00aa", "rescan00bb"
    for md5 in (unapproved_md5, approved_md5):
        old = gone / f"{md5}.png"
        _seed(store, md5, path=old)  # persona_hint 走缺省 'common' ⇒ 不收窄候选
        old.unlink()
        (album / f"{md5}.png").write_bytes(_png_bytes(seed=31))
    store.set_review_state(approved_md5, persona_review.ADMIT)

    result = handler(
        store, _admin_config(base), _message("表情册 重扫", sender_id="900"), "rescan"
    )
    tags = {t.split(":", 1)[0]: t.split(":", 1)[1] for t in result.audit_tags if ":" in t}
    assert tags["relinked"] == "2" and tags["missing"] == "0", result.audit_tags
    assert tags.get("unapproved") == "1", f"没过审那行必须被单独记一笔：{result.audit_tags}"
    assert "另有 1 行" in result.body, f"第三岔没在回执里讲出来：{result.body!r}"

    un_row = _row(store, unapproved_md5)
    assert un_row["path"] == str(album / f"{unapproved_md5}.png"), "路径照认（否则账永远修不了）"
    assert int(un_row["persona_owned"]) == 0, "没过审：身份一个都不替它宣"
    assert un_row["persona_hint"] == "common", "没过审：册名也不替它写"
    ap_row = _row(store, approved_md5)
    assert ap_row["path"] == str(album / f"{approved_md5}.png")
    assert int(ap_row["persona_owned"]) == 1, "控制腿：过了审的那枚照认身份"
    assert ap_row["persona_hint"] == "守岸人", "控制腿：过了审的那枚照记册名"
    assert (album / f"{unapproved_md5}.png").is_file(), "重扫绝不删盘上文件"


def test_album_rescan_with_fully_consistent_library_reports_nothing_to_do(
    tmp_path: Path,
) -> None:
    """零失配那支：说「都对得上」，不端对账数字、不落一个字节（11 节⑤的下划线格）。"""
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    store = _make_store(tmp_path)
    base = store.media_container()
    album = base / "守岸人"
    album.mkdir(parents=True)
    md5 = "consistent1"
    path = album / f"{md5}.png"
    _seed(store, md5, path=path, persona_hint="守岸人")
    missing_fn = _require(store, "missing_path_rows", "W1R")
    assert missing_fn(limit=500) == [], "夹具前提破了：这一行本该对得上"
    before = _row(store, md5)

    result = handler(
        store, _admin_config(base), _message("表情册 重扫", sender_id="900"), "rescan"
    )
    assert "nothing_missing" in result.audit_tags, result.audit_tags
    assert "relinked" not in " ".join(result.audit_tags)
    assert "仍失配" not in result.body and "本轮待对" not in result.body, result.body
    assert _row(store, md5) == before and path.is_file()


def test_album_admit_target_album_from_row_hint_fallback_and_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """入册目标册三岔：行上提示优先 → 空提示才回落现役人格**并登记** → 册缺席就说缺席。

    现役人格名被钉成「守岸人」，而行上提示是「客册」——两枚不同名才分得出「按行落子」
    与「一律落现役人格那本」。第三枚钉的是那条最像好心的退化：目标册不在就拿现役人格
    那本凑数（那是把图塞进别人家的册）。
    """
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    monkeypatch.setattr(persona_profile, "active_persona_id", lambda *a, **k: "shorekeeper")
    monkeypatch.setattr(
        persona_profile, "current_bot_nickname", lambda *a, **k: "守岸人"
    )
    store = _make_store(tmp_path)
    base = store.media_container()
    (base / "客册").mkdir(parents=True)
    (base / "守岸人").mkdir(parents=True)
    hinted, blank, absent = "a100" + "0" * 28, "b200" + "0" * 28, "c300" + "0" * 28
    for md5, hint in ((hinted, "客册"), (blank, ""), (absent, "没开的册")):
        _seed(store, md5, path=base / f"{md5}.png", persona_hint=hint)
        store.set_review_state(md5, persona_review.ADMIT)

    # ① 行上提示优先：落进《客册》，且不拿本轮册名去覆写这一列（F2）
    first = handler(
        store, _admin_config(base), _message("表情册 入册 a100", sender_id="900"), "admit a100"
    )
    assert "moved" in first.audit_tags, first.audit_tags
    assert (base / "客册" / f"{hinted}.png").is_file(), first.body
    assert not (base / "守岸人" / f"{hinted}.png").exists(), "行上有提示就不许落现役人格那本"
    assert _row(store, hinted)["persona_hint"] == "客册"

    # ② 行上没提示 ⇒ 回落现役人格名，并把这一枚**登记**进 persona_hint
    second = handler(
        store, _admin_config(base), _message("表情册 入册 b200", sender_id="900"), "admit b200"
    )
    assert "moved" in second.audit_tags, second.audit_tags
    assert (base / "守岸人" / f"{blank}.png").is_file(), second.body
    assert _row(store, blank)["persona_hint"] == "守岸人", "回落时要把册名登记进行（F2 另一半）"

    # ③ 提示指向不在登记根里的册 ⇒ album_absent：一张不搬、一行不改、也不拿别的册顶
    third = handler(
        store, _admin_config(base), _message("表情册 入册 c300", sender_id="900"), "admit c300"
    )
    assert "album_absent" in third.audit_tags, third.audit_tags
    assert (base / f"{absent}.png").is_file(), "册缺席时原文件必须仍在原位"
    assert _row(store, absent)["path"] == str(base / f"{absent}.png")
    assert not (base / "守岸人" / f"{absent}.png").exists(), "绝不拿现役人格那本顶数"


def test_album_word_forms_stay_disjoint_from_other_branches() -> None:
    """「album 分支先判」无串可证伪（三族词面天然互斥）⇒ 就把**互斥前提**钉住。

    ``_ALBUM_RE`` 独占「表情册／表情相冊」行首，另三族的正则对这些串必须**判不出**。
    哪天有人往 ``_REVIEW_RE``/``_STATS_RE``/``_COMMAND_RE`` 的词面里并进一个「表情册」，
    分支次序就不再是免费保险了——本枚当场红。
    """
    probes = ("待审", "审批 通过 abcd1234", "统计", "统计 查重", "拒收 abcd")
    for prefix in _ALBUM_PREFIXES:
        assert meme_lib._ALBUM_RE.match(prefix) is not None, prefix
        for probe in (prefix, *(f"{prefix} {tail}" for tail in probes)):
            assert meme_lib._REVIEW_RE.match(probe) is None, probe
            assert meme_lib._STATS_RE.match(probe) is None, probe
            assert meme_lib._COMMAND_RE.match(probe) is None, probe
            assert meme_lib.parse_meme_library_command(probe)[0] == "album", probe


# ================== 15. 泄露面探测锁：册目录内不许躺带群号的来源图（席位 T1，2026-10-01）
#
# 判据：库行 ``group_id`` 非空＝这张图是从**别的群**收来的（出处＝第三方会话）。人格册目录
# 是「主动对外发」的池——池腿 ``sources/sticker_packs.py`` 纯文件遍历、一行 DB 都不读，
# 一张图一旦落进册目录就等着被不发问地贴出去。出处门拦的是「没过审的别搬进册」，
# 拦不到「已经躺在册里的」；本锁补的正是这一格：**册目录 ∩ 带群号 ＝ 空集**。
#
# 🔴 必须两脸同判，只写脸 A 会对着现网形状**假绿**（现算：行指向册内文件的行数＝0，
# 而册内文件里带群号来源的有货——真形是「文件被手工搬进别家册、行 path 仍写容器根、
# 根上文件已不存在」）：
#   脸 A「账上改道」``relinked``——行的 ``path`` 解析后落在基根第一层册目录内；
#   脸 B「盘上搬册」``moved``——文件躺在册目录内，其编号（文件名去后缀＝库里的 md5）
#                             对应的那一行 ``group_id`` 非空，而那一行的 ``path`` 还写着别处。
# 两脸分开记、绝不并成一格：并了就看不出是谁动的手（改账 or 搬盘），修法也就无从对表。
# 边界（越界＝长出第二本账）：躺基根散件位的带群号行**不报**（那是吸收池原样）；册内那行
# 没有群号**不报**（出处门的事）；册内文件名根本不是编号、库里查不到行**诚实跳过**。
#
# 尺不自备：行→盘用 ``store.media_path_for_row``（含容器门），盘→册名用
# ``capabilities/meme_library._album_name_for``（基根第一层），遍历形状直引
# ``_walk_album_tree``（与统计/重扫同一棵树，不开第二条 walk）。只读口的生产落点归在飞的
# S-STICKER-ALBUM（禁双头改，本波零写入不落码），消费点＝``表情册 统计``／``重扫`` 回执。

#: 注毒开关：只改**世界**（把带群号那一枚搬进／改道进册目录），绝不开断言的分支——
#: 分支一开，锁就成了跟着开关走的假锁。
_POISON_FACE_ENV = "CB_ALBUM_GUARD_POISON"

#: 一颗真实形态的 32 位十六进制编号（前 8 位＝回执露出的那段，口径同 ``_LEGACY_MD5``）。
_GROUP_SOURCED_MD5 = "feedf00d" + "1" * 24
#: 来源群号用**合成值**：锁只判「非空」，真实群号不进夹具也不进回执（规则 3）。
_GROUP_SOURCE_ID = "2000000001"
#: 用来藏东西的那本册＝别人的册（守岸人册实测为空，形状与归属无关，判据只看「在册里」）。
_ALBUM_WITH_PLANT = "客册"

#: 锁本体唯一断言＝两脸皆空。
_EMPTY_ALBUM_GUARD: dict[str, list[str]] = {"relinked": [], "moved": []}


def _poison_face() -> str:
    """读注毒开关：``relink``＝脸 A，``move``＝脸 B，其余（含未设）＝不注毒。"""
    raw = (os.environ.get(_POISON_FACE_ENV) or "").strip().lower()
    return raw if raw in {"relink", "move"} else ""


def _album_guard_rows(store: MemeLibraryStore) -> dict[str, tuple[str, str]]:
    """全表只读一遍，交回 ``{md5: (path, group_id)}``（编号一律折成小写）。"""
    with store._connect() as connection:
        rows = connection.execute("SELECT md5, path, group_id FROM memes").fetchall()
    return {
        str(row["md5"]).lower(): (str(row["path"] or ""), str(row["group_id"] or ""))
        for row in rows
    }


def _group_sourced_media_in_albums(store: MemeLibraryStore) -> dict[str, list[str]]:
    """现算两脸 ``{'relinked': 脸 A, 'moved': 脸 B}``，各自排序、只露编号前缀。

    回执形态守本族隐私口径（同统计/查重/入册那三把锁）：**没有绝对路径**、
    md5 只露 ``_REVIEW_KEY_DIGITS`` 位；判据要能被人照抄进回执也不泄露出处。
    """
    container = store.media_container()
    rows = _album_guard_rows(store)
    digits = int(meme_lib._REVIEW_KEY_DIGITS)
    hits: dict[str, list[str]] = {"relinked": [], "moved": []}
    accounted: set[str] = set()  # 脸 A 已记过的编号，脸 B 不许再记一遍
    for md5, (path, group_id) in rows.items():
        if not group_id:
            continue
        resolved = store.media_path_for_row(path, where="album_guard_lock")
        if resolved is not None and meme_lib._album_name_for(resolved, container):
            accounted.add(md5)
            hits["relinked"].append(md5[:digits])
    for image in meme_lib._walk_album_tree(container)[0]:
        if not meme_lib._album_name_for(image, container):
            continue  # 基根散件位＝吸收池原样，不归这枚尺
        md5 = image.stem.lower()
        entry = rows.get(md5)
        if entry is None:
            continue  # 无行可查＝这本账管不着，交「散件/未入库」那把尺
        if not entry[1] or md5 in accounted:
            continue
        hits["moved"].append(md5[:digits])
    return {face: sorted(tokens) for face, tokens in hits.items()}


def _seed_album_guard_world(tmp_path: Path, *, face: str) -> tuple[MemeLibraryStore, str, Path]:
    """一颗带群号来源的图 + 一本客册；``face`` 决定它走哪一脸（``''``＝干净世界）。

    ``''``＝图躺基根散件位、账实相符（现网 269 张的形状）；
    ``'move'``＝只把文件搬进册目录、一行不改（＝现网那几枚潜伏的形状，脸 B）；
    ``'relink'``＝文件在册目录**且**行被改道跟进去（＝``表情册`` 重扫之后的形状，脸 A）。
    """
    store = _make_store(tmp_path)
    base = store.media_container()
    album = base / _ALBUM_WITH_PLANT
    album.mkdir(parents=True, exist_ok=True)
    root_file = base / f"{_GROUP_SOURCED_MD5}.png"
    _seed(store, _GROUP_SOURCED_MD5, path=root_file, group_id=_GROUP_SOURCE_ID)
    if face:
        (album / f"{_GROUP_SOURCED_MD5}.png").write_bytes(root_file.read_bytes())
        root_file.unlink()  # 账上 path 仍指根位、根上已无文件
    if face == "relink":
        relink = _require(store, "relink_path", "W1R")
        assert relink(
            _GROUP_SOURCED_MD5,
            str(album / f"{_GROUP_SOURCED_MD5}.png"),
            persona_hint=_ALBUM_WITH_PLANT,
        )
    return store, _GROUP_SOURCED_MD5, album


def test_persona_albums_hold_no_group_sourced_media(tmp_path: Path) -> None:
    """锁本体：断言恒为「两脸皆空」。

    默认夹具＝干净世界 ⇒ 绿；``CB_ALBUM_GUARD_POISON=relink|move`` 只把世界改成两脸之形，
    这一行断言一字不动 ⇒ **必红**（注毒自证的可复跑形态，两脸各一发见下面两枚）。
    """
    store, _md5, _album = _seed_album_guard_world(tmp_path, face=_poison_face())
    assert _group_sourced_media_in_albums(store) == _EMPTY_ALBUM_GUARD


def test_album_guard_poison_face_a_relink_turns_the_lock_red(tmp_path: Path) -> None:
    """注毒脸 A：``relink_path`` 把带群号那行改道进册 ⇒ 锁本体那一行当场必红。"""
    store, md5, album = _seed_album_guard_world(tmp_path, face="relink")
    short = md5[: int(meme_lib._REVIEW_KEY_DIGITS)]
    hits = _group_sourced_media_in_albums(store)
    assert hits == {"relinked": [short], "moved": []}, hits
    assert hits != _EMPTY_ALBUM_GUARD, "行改道进册没被抓＝锁是假锁"
    # 账实两头各自核一遍：改道真发生了（不是夹具糊出来的形状）
    in_album = album / f"{md5}.png"
    assert in_album.is_file()
    assert not (store.media_container() / f"{md5}.png").exists()
    assert Path(str(_row(store, md5)["path"])).resolve() == in_album.resolve()


def test_album_guard_poison_face_b_hand_move_turns_the_lock_red(tmp_path: Path) -> None:
    """注毒脸 B（＝现网形状）：文件被手工搬进别家册、行 path 仍写根位且根上已无文件。

    🔴 只断「行所指向的文件不得落在册内」（脸 A）对这格**假绿**——行 path 解析出来是个
    不存在的根位路径，压根不在册目录里。这枚就是「为什么必须两脸」的那一发。
    """
    store, md5, album = _seed_album_guard_world(tmp_path, face="move")
    short = md5[: int(meme_lib._REVIEW_KEY_DIGITS)]
    hits = _group_sourced_media_in_albums(store)
    assert hits == {"relinked": [], "moved": [short]}, hits
    assert hits != _EMPTY_ALBUM_GUARD, "搬盘没改账没被抓＝只认改道的假绿"
    root_file = store.media_container() / f"{md5}.png"
    assert _row(store, md5)["path"] == str(root_file), "行 path 必须一字未动"
    assert not root_file.exists() and (album / f"{md5}.png").is_file()
    assert int(_row(store, md5)["persona_owned"]) == 0, "潜伏那批的 persona_owned 形状"


def test_album_guard_two_faces_stay_apart_and_do_not_overreach(tmp_path: Path) -> None:
    """两脸分账 + 边界：同一颗世界里 A/B 各一枚，三格对照一律不许被端进来。

    对照三格＝这枚尺的边界（越界＝长出第二本账）：① 带群号但躺基根散件位（现网那批）
    不报；② 在册里但那行没有群号（出处门的事）不报；③ 在册里但文件名不是编号
    （库里查无此行）诚实跳过。
    """
    store = _make_store(tmp_path)
    base = store.media_container()
    album = base / _ALBUM_WITH_PLANT
    album.mkdir(parents=True)
    digits = int(meme_lib._REVIEW_KEY_DIGITS)
    face_a, face_b = "a11ce000" + "1" * 24, "b22ce000" + "2" * 24
    loose, groupless, untracked = "c33ce000" + "3" * 24, "d44ce000" + "4" * 24, "随便起的名字"
    _seed(store, loose, path=base / f"{loose}.png", group_id=_GROUP_SOURCE_ID)
    _seed(store, groupless, path=album / f"{groupless}.png")
    (album / f"{untracked}.png").write_bytes(_png_bytes(seed=3))
    for md5 in (face_a, face_b):
        _seed(store, md5, path=base / f"{md5}.png", group_id=_GROUP_SOURCE_ID)
        (album / f"{md5}.png").write_bytes((base / f"{md5}.png").read_bytes())
        (base / f"{md5}.png").unlink()
    relink = _require(store, "relink_path", "W1R")
    assert relink(face_a, str(album / f"{face_a}.png")) is True  # 只有 A 动了账

    hits = _group_sourced_media_in_albums(store)
    assert hits == {"relinked": [face_a[:digits]], "moved": [face_b[:digits]]}, hits
    assert face_a[:digits] not in hits["moved"], "同一枚记两脸＝两本账"
    echoed = hits["relinked"] + hits["moved"]
    assert {loose[:digits], groupless[:digits], untracked}.isdisjoint(echoed), echoed


def test_album_guard_echo_shape_leaks_no_abspath(tmp_path: Path) -> None:
    """探测口自己的隐私腿：交回的只有两脸编号前缀，没有任何路径形态、也没有全编号。"""
    store, md5, _album = _seed_album_guard_world(tmp_path, face="move")
    hits = _group_sourced_media_in_albums(store)
    echoed = [token for face in hits.values() for token in face]
    assert echoed, "夹具走形：这一格本该有货，空集判据等于没测"
    assert set(hits) == set(_EMPTY_ALBUM_GUARD), "只准交回两脸，多一格就可能夹带路径"
    digits = int(meme_lib._REVIEW_KEY_DIGITS)
    for token in echoed:
        assert len(token) == digits, token
        assert all(char in "0123456789abcdef" for char in token), token
    joined = " ".join(echoed).lower()
    for leak in (str(tmp_path).lower(), str(store.media_container()).lower(), ":", "\\"):
        assert leak not in joined, f"探测口漏出路径形态：{leak!r}"
    assert md5.lower() not in joined, "全编号不许进回执（只露前缀）"


# ================== 16. 文案照做能走通锁（席位 X1，2026-10-01）
#
# 母格＝回执/文案承诺的动作必须照做能走通（台账 #72「回执承诺的前置动作要现算走
# 一遍」；§58.9 断头路同形）。对抗对账席现算抓到本波自己的一格不同向：
#   echo「表情册」帮助正文把「待审／审批」列成**表情册**的命令词，可
#   ``parse_meme_library_command`` 让「表情册」行首独占册面、**未知首词一律静默折回
#   ``stats``**（``_ALBUM_ACTION_WORDS`` 只四枚），真正的待审/审批住在「表情库」族下
#   （``_REVIEW_RE``）⇒ 用户照文案打字走进的是册面统计、不是待审队列。
# 现算读数（本波实跑）：``表情册 待审`` / ``表情册 审批`` → ``('album','stats')``；
# ``表情库 待审`` → ``('review','')``；``表情库 审批 通过 abcd`` → ``('review','通过 abcd')``。
# 🔴 破绽只在**分派层**看得见：handler 拿到被折回的 ``stats`` 会照常跑统计腿、
# 一声不吭——所以这枚锁判的是「帮助正文写的册面动词，是否真在 ``_ALBUM_ACTION_WORDS``
# 里认得」，再拿 handler 腿把「词→码→handler 真跑那一动作」这条闭环也钉住（表里登记了、
# handler 却没实现那一支，同样红）。注毒：正文塞一句不存在的命令词，判据必红。
# 判据分母从 ``_ALBUM_ACTION_WORDS`` 派生，不手写计数（规则 10）。

_ALBUM_HELP_TOPIC = "表情册"


def _album_help_stems() -> list[str]:
    """从 echo「表情册」条目的 lines[] 抽出逐行命令串（冒号「：作用=」之前那一段）。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities.echo import (
        HELP_ENTRIES,
    )

    entry = next(
        (item for item in HELP_ENTRIES if str(item.get("topic")) == _ALBUM_HELP_TOPIC),
        None,
    )
    if entry is None:
        pytest.fail(f"帮助册里没有 {_ALBUM_HELP_TOPIC} 条目（本锁失去被测面）")
    stems = [str(line).split("：", 1)[0].strip() for line in (entry.get("lines") or ())]
    stems = [stem for stem in stems if stem]
    assert stems, f"{_ALBUM_HELP_TOPIC} 的 lines 为空 ⇒ 本锁空转"
    return stems


def _normalize_help_command(stem: str) -> str:
    """把文案里的占位/或形态折成一句真能打的命令：
    ``<编号前缀>`` / ``[编号前缀]`` → 合法十六进制前缀；``通过|拒绝`` → 取「通过」一支。
    只折占位符，**不动动词词面**——动词正是本锁要验的东西。
    """
    out = stem.replace("<编号前缀>", "abcd1234").replace("[编号前缀]", "abcd1234")
    return out.replace("通过|拒绝", "通过")


def _album_verb_word(command: str) -> str:
    """取册面前缀之后的第一个词（帮助正文里写的那个动词）；裸命令 ⇒ 空串。"""
    for prefix in _ALBUM_PREFIXES:
        if command.startswith(prefix):
            return command[len(prefix):].strip().split(" ", 1)[0] if command[
                len(prefix):
            ].strip() else ""
    return ""


def _help_command_dead_reason(stem: str) -> str:
    """照做走一遍分派：返回 ``''``＝走得通；否则返回「为什么走不通」的人话（不落码）。"""
    parse = meme_lib.parse_meme_library_command
    command = _normalize_help_command(stem)
    try:
        action, _ = parse(command)
    except ValueError:
        return f"整串不被任何腿收下（parse 抛 ValueError）：{command!r}"
    # 册面专属：动词必须在动作词表里认得。查不到＝parse 会静默折回 stats（用户以为在看
    # 待审队列、实则在看册面统计）——断头路只有在这一层才拦得住。
    if action == "album":
        verb = _album_verb_word(command)
        if verb and verb not in _album_action_words():
            return (
                f"册面动词 {verb!r} 不在 `_ALBUM_ACTION_WORDS`"
                f"（{sorted(_album_action_words())}）——照文案打字会折回册面统计腿："
                f"{command!r}"
            )
    return ""


def test_album_help_commands_all_dispatchable(tmp_path: Path) -> None:
    """锁本体：帮助正文逐枚「表情X <动词>」都照做能走通，不落未知/默认支。"""
    stems = _album_help_stems()
    offenders = [
        (stem, reason)
        for stem, reason in ((s, _help_command_dead_reason(s)) for s in stems)
        if reason
    ]
    assert not offenders, "帮助正文里有照做走不通的命令词：" + "；".join(
        f"{stem!r}→{reason}" for stem, reason in offenders
    )

    # handler 腿：册面命令 parse 出的动作码必须真被 handler 跑起来（admin 门不得拦、
    # 且回执审计里带着那一支的动作码）——「表里登记了但 handler 没实现」也照样红。
    handler = _require(meme_lib, "handle_meme_album_command", "W3R")
    review = _require(meme_lib, "handle_meme_review_command", "J1")
    store = _make_store(tmp_path)
    base = store.media_container()
    actions_seen: set[str] = set()
    for stem in stems:
        command = _normalize_help_command(stem)
        action, arg = meme_lib.parse_meme_library_command(command)
        actions_seen.add(action)
        if action == "album":
            result = handler(store, _admin_config(base), _message(command, sender_id="900"), arg)
            code = arg.split(" ")[0] if arg else "stats"
            assert code in result.audit_tags, f"{command!r} 的 handler 没跑 {code} 那一支：{result.audit_tags}"
        elif action == "review":
            result = review(store, _admin_config(base), _message(command, sender_id="900"), arg)
            assert "review" in result.audit_tags, f"{command!r} 没落进审批面：{result.audit_tags}"
        assert "denied" not in getattr(result, "audit_tags", []), f"管理员被拒：{command!r}"
    # 非空转判据：被测面里既要有册面命令、也要有审批面命令（改回单族本锁就退化成摆设）。
    assert {"album", "review"} <= actions_seen, actions_seen


def test_album_help_lock_flags_nonexistent_command_word() -> None:
    """注毒自证（不靠改 echo 文件）：往分派判据里塞不存在的册面动词、或把待审/审批
    打回表情册面，本锁的分派腿必判死；真动词与裸命令判活——证明这枚锁不是永真摆设。
    """
    for bogus in ("表情册 飞天", "表情册 待审", "表情相冊 审批", "表情册 清空"):
        assert _help_command_dead_reason(bogus), f"注毒未红：{bogus!r} 本该判死"
    # 反向对照：同一判据对合法册面动词、裸命令、以及「表情库 待审」都判活。
    for alive in ("表情册", "表情册 统计", "表情册 入册 abcd1234", "表情库 待审", "表情库 审批 通过 abcd1234"):
        assert _help_command_dead_reason(alive) == "", f"合法命令被误判死：{alive!r}"


