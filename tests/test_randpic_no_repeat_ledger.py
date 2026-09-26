"""S-RANDPIC-LEDGER2（2026-09-26）「随机发图不重复账」的机器锁（ITEM 15 + ITEM 12 半）。

用户口径两条：
- ITEM 15：bot 回复完用户消息 / 用户戳 bot / 特定指令，三个触发点从指定文件夹
  随机发一张图；
- ITEM 12（一半）：**禁止重复发送同一张**——表情（meme/sticker）与随机图
  （randpic）是两个族，**各自的账分别验**（本件 A–D 组验 randpic 族，
  E 组验贴纸族的咽喉账）。

分组：

* **A 唯一账与唯一嘴**：生产只构造一枚窗账实例；三个触发面（指令能力 / 回复后
  腿 / 被戳 randpic 臂）行为学证明读写同一本账；会话内生效、跨会话不串账。
* **B 判据与淘汰**：超窗即复开（淘汰由可控时钟驱动）；「大小加速道撒谎」在
  占坑终判面前不再能造成重发（S-RANDPIC-2 的纵深防御上移，J5 牙齿因此
  作废的证物就写在这里）。
* **C 并发同图竞态**：``try_claim`` 单胜者（8 线程）；两条腿同时盯上同一张
  新鲜候选时**绝不各发一次**（2 线程 + 汇合点，旧「快照→无条件 record」写法
  在这里必红）；单图库并发时输家诚实 ``held_*`` 不发。
* **D 退化态诚实**：图库没打开过 ⇒ 不发也不记账；整库发完 ⇒ 主动腿持有不发、
  指令腿退「最久没发」且代号可判别（recycled 不冒充首发）；绝不造图。
* **E 贴纸族账（ITEM 12 半）**：三条贴纸腿共同的咽喉 ``weighted_pick`` 不重发、
  耗尽回 ``None``（不回退成「挑一张发过的发」）、全局作用域跨会话生效、
  并发两条腿在占坑下各拿一张。

全离线：图片是 ``tmp_path`` 里的假字节，SQLite 只写 ``tmp_path``（铁律 6 源码树
零写入），零网络、零真实协议端。模块级三处缓存逐例清空（先例
``tests/test_randpic_identity_window_v4.py`` 的 autouse 夹具）。
"""

from __future__ import annotations

import ast
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.contracts import SendPolicy
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    build_randpic_capability,
)
from plugins.bot_unified_runtime.domains.meme.sources.meme_library import (
    MemeLibraryStore,
)
from plugins.bot_unified_runtime.domains.meme.sources.send_history import (
    MemeSendHistoryStore,
    content_sha256_of_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/bot_unified_runtime"
RANDPIC_PY = PLUGIN_ROOT / "domains/meme/capabilities/randpic.py"
ROOT_INIT = PLUGIN_ROOT / "__init__.py"

_PNG = b"\x89PNG\r\n\x1a\n"
_WINDOW_KEY = "group_1_2"


@pytest.fixture(autouse=True)
def _clean_caches():
    """三处模块级状态逐例清空——它们全是跨例状态，不清就会互相污染。"""
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()


# ------------------------------------------------------------------ 小工具


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _gallery(tmp_path: Path, count: int) -> list[Path]:
    root = tmp_path / "gallery"
    made = []
    for index in range(count):
        made.append(_write(root / f"pic-{index}.png", _PNG + f"payload-{index}".encode()))
    return made


def _config(gallery_dir: Path, *, window_seconds: float = 3600.0) -> SimpleNamespace:
    return SimpleNamespace(
        bot_randpic_dirs=[str(gallery_dir)],
        bot_randpic_trigger_words=[],
        bot_randpic_max_file_mb=25,
        bot_randpic_no_repeat_window_seconds=window_seconds,
    )


def _message(text: str, *, session_id: str = _WINDOW_KEY) -> SimpleNamespace:
    # 能力体只 getattr(session_id/plain_text/message_id/request_id)，SimpleNamespace
    # 足够且不把契约必填字段抄进测试（抄了就叫测夹具）。
    return SimpleNamespace(
        session_id=session_id,
        plain_text=text,
        message_id=f"msg-{hashlib.sha256(text.encode()).hexdigest()[:8]}",
        request_id="req-1",
    )


def _outcome(window, dirs: list[str], *, seed: str, session: str = _WINDOW_KEY, **kw):
    return randpic.pick_fresh_outcome(
        dirs,
        session_key=session,
        window=window,
        window_seconds=kw.pop("window_seconds", 3600.0),
        seed=seed,
        allow_exhausted=kw.pop("allow_exhausted", False),
        **kw,
    )


def _identity(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ============================================================ A 唯一账与唯一嘴


def test_production_constructs_exactly_one_ledger_instance() -> None:
    """randpic.py 模块级只许构造**一枚**窗账；根装配文件不另起炉灶、不注入私账。

    「一条唯一账」最容易死在第二种形态上：不是写了第二本，而是某个装配点
    顺手 new 了一个新窗口传进去——账就断成两本。这里把两种形态都钉住。
    """
    module_tree = ast.parse(RANDPIC_PY.read_text(encoding="utf-8"))
    module_level = [
        node
        for node in module_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_DEFAULT_RECENT_WINDOW"
            for target in node.targets
        )
    ]
    assert len(module_level) == 1, "缺省窗账被赋值了不止一次 ⇒ 第一真身不唯一"

    root_tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(root_tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if func_name == "RecentImageWindow":
            offenders.append(f"根装配文件第 {node.lineno} 行自建了第二枚窗账")
        elif func_name in {
            "pick_gallery_image",
            "pick_gallery_image_outcome",
            "pick_fresh_outcome",
            "pick_fresh_image",
        } and any(keyword.arg == "window" for keyword in node.keywords):
            offenders.append(
                f"取图口在根文件第 {node.lineno} 行被注入了私有窗口（绕开唯一账）"
            )
    assert not offenders, "；".join(offenders)


def test_three_trigger_surfaces_share_the_one_ledger(tmp_path: Path) -> None:
    """指令能力、回复后腿、被戳臂三个面读写同一本账（行为学证明，不是注释担保）。

    场景是生产形状：同一个群会话（session 键形状一致：group_<gid>_<uid>）。
    ① 用户说「随机图」⇒ 能力发 X 并记账；
    ② 回复后腿（主动口径 allow_exhausted=False）必须跳过 X、发另一张；
    ③ 被戳 randpic 臂（同一主动口径）此时整库已发完 ⇒ 诚实不发；
    ④ 用户再喊「随机图」⇒ 照发但代号记 recycled（同一张的第二次不冒充首发）。
    """
    made = _gallery(tmp_path, 2)
    config = _config(made[0].parent)

    capability = build_randpic_capability(config)
    first = capability(_message("随机图"), None)
    assert first.images, "指令腿第一次就该发图"
    first_path = Path(str(first.images[0]["file"]))
    assert first_path in made

    dispatch_path = randpic.pick_gallery_image(
        config, session_key=_WINDOW_KEY, seed="randpic-dispatch:1", allow_exhausted=False
    )
    assert dispatch_path is not None and dispatch_path != first_path, (
        "回复后腿把指令腿刚发过那张又发了一遍 ⇒ 两面没共用同一本账"
    )

    poke_path = randpic.pick_gallery_image(
        config, session_key=_WINDOW_KEY, seed="poke-randpic:1:2", allow_exhausted=False
    )
    assert poke_path is None, "整库都在窗内时被戳臂必须不发（宁缺不刷屏）"

    second = capability(_message("随机图"), None)
    assert second.images, "用户开口要图，整库在窗内也照发（裁定：拒不发更糟）"
    assert "recycled_in_window" in (second.audit_tags or []), (
        "第二次发同一张必须记 recycled 代号，不许混在 sent 里冒充首发"
    )


def test_ledger_is_per_session_not_cross_session(tmp_path: Path) -> None:
    """去重范围按现有代码事实钉死为**单会话桶**：A 会话发过不拦 B 会话。

    这是记账层的既有设计（窗账以会话键分桶；跨会话去重会让群里两张不同人
    同时要的图互相饿死），本例把「范围」从实现细节升格为有锁的口径。
    """
    made = _gallery(tmp_path, 1)
    config = _config(made[0].parent)
    capability = build_randpic_capability(config)
    assert capability(_message("随机图", session_id="group_1_2"), None).images
    other = randpic.pick_gallery_image(
        config, session_key="group_8_9", seed="dispatch:other", allow_exhausted=False
    )
    assert other == made[0], "别的会话第一次拿图被别的会话的账拦下 ⇒ 桶串了"


# ========================================================== B 判据与淘汰策略


def test_window_expiry_reopens_the_same_image(tmp_path: Path) -> None:
    """淘汰=按时间窗惰性过期（不是计数、不是永久）：超窗后同一张可再占。

    这枚用例同时是注毒②的靶子：把「过期即放还」改成「永不淘汰」，
    第三发会永远是 None ⇒ 当场红。
    """
    made = _gallery(tmp_path, 1)
    clock = {"t": 0.0}
    window = randpic.RecentImageWindow(clock=lambda: clock["t"])
    dirs = [str(made[0].parent)]

    first = _outcome(window, dirs, seed="e1", window_seconds=60.0)
    assert first.path == made[0]
    second = _outcome(window, dirs, seed="e2", window_seconds=60.0)
    assert second.path is None and second.reason == "held_pool_exhausted"
    clock["t"] = 61.0  # 超窗：这张图应当复开
    third = _outcome(window, dirs, seed="e3", window_seconds=60.0)
    assert third.path == made[0], "窗都过了还不放还 ⇒ 淘汰策略被改成了永不淘汰"


class _LyingSizesWindow(randpic.RecentImageWindow):
    """``recent_sizes`` 谎报「每条账的大小我都知道」（实为全未知）。

    这是 test_randpic_mutation_teeth 的 J5 毒形——旧实现里它必造成重发；
    占坑（``try_claim``）成为终判后，谎言只剩「多读一次字节」的代价。
    """

    def recent_sizes(self, session_key, *, window_seconds, now=None):  # type: ignore[no-untyped-def]
        return frozenset(), False


def test_size_shortcut_lie_cannot_resend_because_claim_decides(tmp_path: Path) -> None:
    """大小加速道撒谎也发不出第二次：摘要占坑是唯一终判（纵深防御上移的证物）。

    与 J5 的分工：那条牙齿断言「撒谎必被旧判据抓住」，本件断言「撒谎已造不成
    重发」。两条不可能同时绿——占坑版里后者替代前者，J5 的重锚建议见本席报告
    §8 PARKED（那是牙齿件 owner 的账，本席不代改）。
    """
    made = _gallery(tmp_path, 1)
    dirs = [str(made[0].parent)]
    window = _LyingSizesWindow()
    identity = _identity(made[0])
    window.record(_WINDOW_KEY, identity, window_seconds=3600.0)  # 故意不带大小
    outcome = _outcome(window, dirs, seed="fc")
    assert outcome.path is None, "同图又被放行 ⇒ 占坑终判被绕开了"
    assert outcome.reason in {"held_pool_exhausted", "held_pool_unproven"}


# ============================================================== C 并发同图竞态


def test_try_claim_admits_exactly_one_winner() -> None:
    """8 线程抢同一张的坑：恰好一个 True，其余全 False（且窗账里只有一行）。"""
    window = randpic.RecentImageWindow()
    barrier = threading.Barrier(8)
    results: list[bool] = []
    results_lock = threading.Lock()

    def _worker() -> None:
        barrier.wait(timeout=30)
        won = window.try_claim("group_1_2", "sha-contested", window_seconds=3600.0)
        with results_lock:
            results.append(won)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert results.count(True) == 1, f"占坑不是原子的：{results}"
    assert window.recent_keys("group_1_2", window_seconds=3600.0) == frozenset(
        {"sha-contested"}
    )


def _run_two_racing_picks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pool: int, allow_exhausted: bool
):
    """两线程 + 摘要汇合点：把「都拿着旧快照、同时盯上同一张」钉成确定性事件。

    汇合点选在 ``image_identity`` 的**第一次**调用：两条腿都必须先越过快照读取
    （发生在摘要之前），才可能走到这里 ⇒ 两边手里的窗账快照都还是旧的。
    这正是回复后腿（asyncio.to_thread）与指令腿（pipeline 线程池）共用的真窗口。
    """
    made = _gallery(tmp_path, pool)
    randpic.list_gallery_images([str(made[0].parent)])  # 预热线程安全的清单缓存
    real_identity = randpic.image_identity
    barrier = threading.Barrier(2)
    met = {"n": 0}
    met_lock = threading.Lock()

    def _rendezvous(path):  # type: ignore[no-untyped-def]
        with met_lock:
            met["n"] += 1
            first_round = met["n"] <= 2
        if first_round:
            try:
                barrier.wait(timeout=30)
            except threading.BrokenBarrierError:
                pass
        return real_identity(path)

    monkeypatch.setattr(randpic, "image_identity", _rendezvous)
    outcomes: dict[str, randpic.PickOutcome] = {}
    outcomes_lock = threading.Lock()

    def _worker(name: str) -> None:
        outcome = randpic.pick_fresh_outcome(
            [str(made[0].parent)],
            session_key=_WINDOW_KEY,
            window_seconds=3600.0,
            seed="same-seed-same-order",  # 两腿同 seed ⇒ 探查序一致，必撞同一候选
            allow_exhausted=allow_exhausted,
        )
        with outcomes_lock:
            outcomes[name] = outcome

    threads = [
        threading.Thread(target=_worker, args=(label,), name=label)
        for label in ("leg-a", "leg-b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert set(outcomes) == {"leg-a", "leg-b"}, "有腿没跑完（竞态把线程弄丢了）"
    return outcomes


def test_two_concurrent_legs_never_return_the_same_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两腿并发取图（2 张池）：各自发出去的两张内容身份必须不同。

    旧「快照→无条件 record」写法在此必红：两腿都从空快照出发、探到同一张、
    各 record 一次、各发一次——正是 ITEM 15(b) 要拦的那一发。
    """
    outcomes = _run_two_racing_picks(tmp_path, monkeypatch, pool=2, allow_exhausted=False)
    paths = [outcomes["leg-a"].path, outcomes["leg-b"].path]
    assert all(path is not None for path in paths), f"两张新鲜图并发却有人空手：{paths}"
    assert _identity(paths[0]) != _identity(paths[1]), (
        "并发两条腿把同一张各发了一次 ⇒ 不重复账在竞态下失守"
    )


def test_concurrent_single_image_pool_losers_hold_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 张池并发（主动口径）：恰好一腿发出去，另一腿诚实 held_* 不发、不报错。"""
    outcomes = _run_two_racing_picks(tmp_path, monkeypatch, pool=1, allow_exhausted=False)
    sent = [name for name, outcome in outcomes.items() if outcome.path is not None]
    assert len(sent) == 1, f"单图库并发发出了 {len(sent)} 次"
    loser = next(name for name, outcome in outcomes.items() if outcome.path is None)
    assert outcomes[loser].reason.startswith("held_"), (
        f"输家代号必须可判别（实际 {outcomes[loser].reason}）：不许静默空手"
    )


# ============================================================ D 退化态诚实性


def test_unreadable_gallery_sends_nothing_and_records_nothing(tmp_path: Path) -> None:
    """路径不存在：不发、不记，而且**不对没打开过的目录断言内容**。"""
    ghost = tmp_path / "never-created"
    config = _config(ghost)
    capability = build_randpic_capability(config)
    result = capability(_message("随机图"), None)
    assert not result.images, "图库没打开过却交出去一张图"
    assert result.send_policy != SendPolicy.SILENT_AUDIT, "降级话术必须能到用户手上"
    assert result.body
    assert randpic._DEFAULT_RECENT_WINDOW.recent_keys(
        _WINDOW_KEY, window_seconds=3600.0
    ) == frozenset(), "什么都没发出去，账上却记了一笔"


def test_exhausted_pool_active_holds_and_command_recycles_least_recent(
    tmp_path: Path,
) -> None:
    """整库发完（3 张全在窗内）：主动腿 None；指令腿按「最久没发」次序回收。

    回收顺序可审计：第 4 发退第 1 发那张、第 5 发退第 2 发那张（占坑序=插入序），
    不是凭 seed 任取——「退最久没发」这句话自 S-T-RANDPIC-1 起是判据不是修辞。
    """
    made = _gallery(tmp_path, 3)
    dirs = [str(made[0].parent)]
    window = randpic.RecentImageWindow()
    order: list[Path] = []
    for index in range(3):
        outcome = _outcome(window, dirs, seed=f"walk-{index}")
        assert outcome.path is not None
        order.append(outcome.path)
    assert len({path.name for path in order}) == 3

    held = _outcome(window, dirs, seed="walk-3")
    assert held.path is None and held.reason == "held_pool_exhausted"

    for recycle_index, expected in enumerate(order):
        recycled = randpic.pick_fresh_outcome(
            dirs,
            session_key=_WINDOW_KEY,
            window=window,
            window_seconds=3600.0,
            seed=f"cmd-{recycle_index}",
            allow_exhausted=True,
        )
        assert recycled.path == expected, (
            f"回收第 {recycle_index + 1} 发不是「最久没发」那张："
            f"期望 {expected.name} 实得 {recycled.path and recycled.path.name}"
        )
        assert recycled.reason == "recycled_least_recent", recycled.reason


def test_single_image_command_never_fakes_a_second_picture(tmp_path: Path) -> None:
    """只有 1 张：指令腿每次照发**同一张**并记 recycled，绝不静默不发、也绝不造图。"""
    made = _gallery(tmp_path, 1)
    config = _config(made[0].parent)
    capability = build_randpic_capability(config)
    for index in range(3):
        result = capability(_message("随机图"), None)
        assert result.images and Path(str(result.images[0]["file"])) == made[0]
        if index:
            assert "recycled_in_window" in (result.audit_tags or [])


# ================================================= E 贴纸族账（ITEM 12 半，另一本账）


def _sticker_library(tmp_path: Path, names: dict[str, str]) -> MemeLibraryStore:
    store = MemeLibraryStore(tmp_path / "meme_library.sqlite3", prefer=[])
    for md5, emotion in names.items():
        image = _write(tmp_path / f"{md5}.png", _PNG + emotion.encode())
        digest = content_sha256_of_bytes(image.read_bytes())
        store.add(md5=md5, path=str(image), ext="png", group_id="g1", content_sha256=digest)
        store.apply_tags(
            md5,
            is_meme=True,
            description=emotion,
            emotion_tags=[emotion],
            scene_tags=[],
            persona_hint="common",
            nsfw_score=0.0,
        )
    return store


def test_sticker_throat_never_resends_across_scopes(tmp_path: Path) -> None:
    """三条贴纸腿共同的咽喉 ``weighted_pick``：同作用域不重样、换会话也不重样。

    「换会话也不重样」来自保留作用域 ``GLOBAL_SCOPE``——这正是 ITEM 12
    「同一张贴纸绝不发第二次」的字面口径（randpic 族是**每会话**桶，两族
    口径不同是有意的，各自有账有锁；不许拿一族的尺去量另一族）。
    """
    store = _sticker_library(
        tmp_path, {"m1": "开心", "m2": "难过"}
    )
    first = store.weighted_pick(scope="group_1_2")
    second = store.weighted_pick(scope="group_1_2")
    assert first is not None and second is not None
    assert first["content_sha256"] != second["content_sha256"]
    assert store.weighted_pick(scope="group_1_2") is None, "整库发完必须回 None"
    assert store.weighted_pick(scope="group_9_9") is None, (
        "全局账没兜住 ⇒ 换个会话同一张贴纸又被发了第二次"
    )


def test_sticker_empty_library_returns_none(tmp_path: Path) -> None:
    store = _sticker_library(tmp_path, {})
    assert store.weighted_pick(scope="group_1_2") is None


def test_sticker_weighted_pick_concurrent_legs_split_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """贴纸咽喉的并发竞态：两腿同时过了「已发集合」快照 ⇒ 占坑必须把它们分开。

    汇合点选在 ``sent_hashes``（咽喉的读账口，只被调用一次/发）：两边拿到同样的
    空快照后各自走 ``try_claim``。单贴库 ⇒ 两腿的候选只有同一张 ⇒ 恰一真一 None；
    若哪天有人把占坑退回成「查过了就发」，这里当场双发变红。
    """
    store = _sticker_library(tmp_path, {"only": "微笑"})
    real = MemeSendHistoryStore.sent_hashes
    barrier = threading.Barrier(2)

    def _racing_sent_hashes(self, **kwargs):  # type: ignore[no-untyped-def]
        try:
            barrier.wait(timeout=30)
        except threading.BrokenBarrierError:
            pass
        return real(self, **kwargs)

    monkeypatch.setattr(MemeSendHistoryStore, "sent_hashes", _racing_sent_hashes)
    results: list[object] = []
    results_lock = threading.Lock()

    def _worker() -> None:
        picked = store.weighted_pick(scope="group_1_2")
        with results_lock:
            results.append(picked)

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len([item for item in results if item is not None]) == 1, (
        f"单贴库并发被发了 {len([item for item in results if item])} 次 ⇒ 占坑不是终判"
    )


# ------------------------------------------------------------------ 自证：尺子有牙


def test_two_threads_without_claim_would_collide_poison_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反向自证：把占坑终判摘掉（退回「查过了就发」），同图竞态用例必红。

    摘法=让 ``try_claim`` 无条件记账放行（等价于旧「快照→record」的语义）。
    如果这条注毒探针不再让 C 组红，说明竞态锁是空跑——所以它必须红。
    """

    def _always_allow(self, session_key, identity, **kwargs):  # type: ignore[no-untyped-def]
        self._legacy_record_and_admit(session_key, identity, **kwargs)
        return True

    monkeypatch.setattr(
        randpic.RecentImageWindow, "_legacy_record_and_admit",
        randpic.RecentImageWindow.record, raising=False,
    )
    monkeypatch.setattr(randpic.RecentImageWindow, "try_claim", _always_allow)
    with pytest.raises(AssertionError):
        outcomes = _run_two_racing_picks(
            tmp_path, monkeypatch, pool=2, allow_exhausted=False
        )
        paths = [outcomes["leg-a"].path, outcomes["leg-b"].path]
        assert all(path is not None for path in paths)
        assert _identity(paths[0]) != _identity(paths[1])
