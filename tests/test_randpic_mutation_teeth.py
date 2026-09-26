"""S-T-RANDPIC-1（2026-09-26）注毒自证台：每把我新加的锁，都必须抓得住对应的坏实现。

**为什么写在内存里而不是改生产件**：本机宿主对生产文件的 ``open(path,'wb')`` 报
``OSError[Errno 22]``、``r+b`` 改写后 ``truncate`` 又报 ``PermissionError[13]`` ⇒
「注毒—跑—还原—核 sha」那条盘上路走不通。本仓先例（
``tests/test_poke_randpic_behavior.py::_poisoned_poke_source`` + ``_exec_module``）本来
就是「造一份注毒源码副本，在内存里当模块跑」，注毒样本不落源码树——照此办。

每发注毒跑**两次判据**：
① 打在注毒副本上必须炸（证明这把锁有牙，不是空跑）；
② 打在**在盘真身**上必须不炸（证明判据本身没写歪，不是恒真）。

锚点一律**单行**（仓库里混着 CRLF 件，多行 ``\\n`` 锚点会静默匹配不到 ⇒ 注毒变成空跑）。
"""

from __future__ import annotations

import sys
import types
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.contracts import SendPolicy
from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.render.renderer import render_reviewed_output
from plugins.bot_unified_runtime.domains.render.reviewer import review_capability_result
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    _segments_from_rendered_output,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RANDPIC_PY = (
    REPO_ROOT / "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py"
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

_CONTENT_CLAIM_PHRASES = (
    "没有能发的图片",
    "一张文件都没有",
    "没有我能发的图片格式",
    "都超过单张上限",
)


def _exec_module(source: str, name: str) -> types.ModuleType:
    """把一份源码副本当模块跑起来（跑完从 ``sys.modules`` 摘掉，不留影子模块）。"""
    module = types.ModuleType(name)
    module.__dict__["__name__"] = name
    module.__dict__["__file__"] = f"<{name}>"
    sys.modules[name] = module
    try:
        exec(compile(source, f"<{name}>", "exec"), module.__dict__)  # noqa: S102
    finally:
        if sys.modules.get(name) is module:
            del sys.modules[name]
    return module


def _poisoned(anchor: str, replacement: str, name: str) -> types.ModuleType:
    """单行锚点注毒：锚点在真身里必须**恰好出现一次**，否则本发判为脱靶（当场红）。"""
    source = RANDPIC_PY.read_text(encoding="utf-8")
    lines = source.split("\n")
    occurrences = lines.count(anchor)
    assert occurrences == 1, (
        f"锚点在 randpic.py 里出现 {occurrences} 次（要求恰好 1 次）⇒ 注毒脱靶，"
        "请同步本件的单行锚点，别把判据改松"
    )
    return _exec_module(source.replace(anchor, replacement, 1), name)


# ---------------------------------------------------------------- 夹具与判据共用小件


def _gallery(root: Path, count: int, *, size: int | None = None) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for index in range(count):
        path = root / f"pic-{index:04d}.png"
        body = (bytes([index % 251]) * size) if size else bytes([index % 251]) * (index + 1)
        path.write_bytes(PNG_MAGIC + body)
        made.append(path)
    return made


def _config(module: types.ModuleType, root: Path, **overrides: object):
    from types import SimpleNamespace

    base: dict[str, object] = {
        "bot_randpic_enabled": True,
        "bot_randpic_dirs": [str(root)],
        "bot_randpic_trigger_words": [],
        "bot_randpic_max_file_mb": 25,
        "bot_randpic_no_repeat_window_seconds": 3600.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _message(module: types.ModuleType, text: str = "随机图", message_id: str = "m1"):
    from plugins.bot_unified_runtime.contracts import IncomingMessage, SessionType

    return IncomingMessage(
        platform="qq",
        adapter="nonebot",
        bot_id="10000",
        session_id="private_7",
        session_type=SessionType.PRIVATE,
        sender_id="7",
        plain_text=text,
        message_id=message_id,
    )


def _clear_caches(module: types.ModuleType) -> None:
    module._SCAN_CACHE = OrderedDict()
    module._IDENTITY_CACHE = OrderedDict()
    module._DEFAULT_RECENT_WINDOW.clear()


# ------------------------------------------------------------------ 出站链小尺


def _shipped_segment_types(module: types.ModuleType, result) -> list[str]:
    """能力结果 → 审核 → 渲染 → OneBot 段（生产同一条链，只是喂的是注毒件的结果）。"""
    message = _message(module)
    decision = types.SimpleNamespace(
        request_id=message.request_id,
        should_respond=True,
        mode="command",
        trigger="随机图",
        capability_id="bot.randpic",
        target_scope=message.session_type,
        decision_reason="mutation-probe",
    )
    review = review_capability_result(result, decision)
    rendered = render_reviewed_output(result, review)
    segments = _segments_from_rendered_output(
        content_type=rendered.content_type,
        content_ref=rendered.content_ref,
        text_fallback=rendered.text_fallback,
        request_id=result.request_id,
    )
    return [str(segment.get("type")) for segment in segments]


# ============================================================================
# 十发注毒，逐发对应一把新锁
# ============================================================================

#: ``(编号, 锚点行, 注毒替换行, 判据, 这一发在模拟哪种坏实现)``
CASES: list[tuple[str, str, str, Callable[[types.ModuleType, Path], None], str]] = [
    (
        "J1 空白目录守卫",
        "        if not text.strip():",
        "        if False:",
        lambda module, tmp: (
            _assert_zero(module.gallery_facts(["", "   "]).dirs_configured, "空白写位被当目录"),
        ),
        "BOT_RANDPIC_DIRS 里一条空串 ⇒ 去扫进程工作目录",
    ),
    (
        "J2 missing 档措辞",
        '            return "missing"',
        '            return "empty"',
        lambda module, tmp: _assert_no_content_claim(
            module, module.gallery_facts([str(tmp / "ghost")]), [str(tmp / "ghost")]
        ),
        "把「我没能打开它」折成「它是空的」（我不知道＝它没有）",
    ),
    (
        "J3 降级句发得出去",
        "                # 刻意**不再**标 SILENT_AUDIT：这句是给用户看的（见上方口径③）。",
        "                send_policy=SendPolicy.SILENT_AUDIT,",
        lambda module, tmp: _assert_delivered(module, tmp / "ghost"),
        "文案标 SILENT_AUDIT ⇒ 管线判 SKIPPED，用户一句都收不到",
    ),
    (
        "J4 整库摘要回来了",
        "    pool: list[Path] = list(dict.fromkeys(images))",
        "    pool: list[Path] = list(dict.fromkeys(images))\n    [image_identity(p) for p in pool]",
        lambda module, tmp: _assert_bounded_reads(module, tmp),
        "每次取图先把全库字节读一遍（现网规模 ≈127 秒/次）",
    ),
    (
        "J5 大小谎言不绕占坑终判",
        "                return False",
        "                return True",
        lambda module, tmp: _assert_claim_decides_when_size_lies(module, tmp),
        "占坑终判被改成「窗内也放行」⇒ 大小筛不掉时同图重发（ITEM 15(b)）",
    ),
    (
        "J6 死引用不验活",
        "        if _file_size(candidate) is not None:",
        "        if True:",
        lambda module, tmp: _assert_no_dead_path_from_picker(module, tmp),
        "TTL 清单里的死路径被直接交给出站链",
    ),
    (
        "J7 重发不记账",
        '            tags.append("recycled_in_window")',
        "            pass",
        lambda module, tmp: _assert_recycle_is_labelled(module, tmp),
        "整库在窗内的第二次发图静默冒充首发",
    ),
    (
        "J8 路径提示当判据",
        "            if read_identity(hinted) == identity:",
        "            if True:",
        lambda module, tmp: _assert_hint_must_be_verified(module, tmp),
        "窗账里的路径提示没被摘要复核就照着发",
    ),
    (
        "J9 gallery_empty 乱贴",
        '    if verdict in ("empty", "no_image_extension", "over_limit", "stat_failed"):',
        "    if True:",
        lambda module, tmp: _assert_empty_tag_discipline(module, tmp),
        "路径不存在也被贴上「图库是空的」这个断言",
    ),
    (
        "J10 图卡带回标题",
        '            title="",',
        '            title="随机图片",',
        lambda module, tmp: _assert_image_only_outbound(module, tmp),
        "renderer 兜底链把标题跟图一起发出去（F5 原事故形态）",
    ),
]


# ---------------------------------------------------------------------- 判据本体


def _assert_zero(value: int, note: str) -> None:
    assert value == 0, f"{note}（现算 {value}）"


def _assert_no_content_claim(module, facts, dirs: list[str]) -> None:
    body = module.gallery_degradation_line(facts, dirs)
    for phrase in _CONTENT_CLAIM_PHRASES:
        assert phrase not in body, f"没打开过的目录被说成了『{phrase}』"


def _assert_delivered(module, gallery_dir: Path) -> None:
    result = module.build_randpic_capability(_config(module, gallery_dir))(
        _message(module), None
    )
    assert result.body.strip(), "降级句不能是空的"
    assert result.send_policy is not SendPolicy.SILENT_AUDIT, "SILENT_AUDIT＝不发出去"


def _assert_bounded_reads(module, tmp: Path) -> None:
    """「一次取图读几张字节」= 每次取图**各自**判，不是一趟总数。

    旧写法先把两次取图跑完、才装上 spy——于是 spy 只量到第三发。注毒体
    （每发先把整库 digest 一遍）恰好在前两发就把 120 张全灌进 ``_IDENTITY_CACHE``，
    第三发读的是记忆化命中 ⇒ spy 恒 0、``<=3`` 对毒身与真身**同时成立**。
    实测（2026-09-26，``$TEMP/rp-j4/probe_j4.py``）：毒身 预热后缓存=120/探针读=0，
    真身 预热后缓存=2/探针读=1。量测窗口必须从第一发起就在，且要能自证
    「尺子确实量到了东西」。
    """
    from plugins.bot_unified_runtime.domains.media import digest as digest_module

    root = tmp / "cost"
    _gallery(root, 120)
    _clear_caches(module)
    dirs = [str(root)]
    window = module.RecentImageWindow()
    counter = {"n": 0}
    real = digest_module.media_digest_file

    def _spy(path, *args, **kwargs):
        counter["n"] += 1
        return real(path, *args, **kwargs)

    digest_module.media_digest_file = _spy  # type: ignore[assignment]
    try:
        for index in range(3):
            before = counter["n"]
            outcome = module.pick_fresh_outcome(
                dirs, session_key="private_7", window=window, window_seconds=3600.0,
                seed=f"probe{index}", allow_exhausted=False,
            )
            assert outcome.path is not None
            reads = counter["n"] - before
            assert reads <= 3, (
                f"第 {index + 1} 发取图真读了 {reads} 张字节 ⇒ 全库扫描回来了"
                "（现网规模 ≈127 秒/次）"
            )
        assert counter["n"] > 0, (
            "三发取图 spy 一次都没被叫到 ⇒ 这把尺量的是空气（测量本身坏了，"
            "不是代码好了）"
        )
    finally:
        digest_module.media_digest_file = real


def _assert_claim_decides_when_size_lies(module, tmp: Path) -> None:
    """账本的大小在撒谎（值对不上）⇒ 内容摘要占坑（``try_claim``）仍必须拦住同图。

    **重锚依据（S-J5-REANCHOR，2026-09-26；旧牙判死，非本席拔的）**：旧毒形打在
    ``recent_sizes`` 的 ``return frozenset(sizes), unknown`` 上。S-RANDPIC-2
    （2026-09-26，占坑终判波）之后，``pick_fresh_outcome`` 两个分支都先算内容摘要
    再 ``try_claim``（randpic.py :868-881），谎报 unknown 只改「预筛要不要先查窗账
    快照」这一枚**与终判冗余**的判据，物理上造不成放行 ⇒ DID NOT RAISE 复现属实。
    且「未知大小」一支如今是双层闸（预筛 ``identity in recent`` + ``try_claim``），
    单行粒度注毒杀不动它——那是结构强度，不是锁坏了。今天唯一单行可杀、又真担着
    「同图不重发」的点位是 ``try_claim`` 的窗内拒绝（randpic.py :566）。判据场景
    随之走「大小谎称已知但值对不上」这一支：预筛放行 ⇒ 终判把关。

    库里**只放刚发过那一张**，record 时故意带一个对不上的大小：
    - 真身：``size not in known_sizes`` 走「多半新鲜」捷径，但 ``try_claim`` 认出
      摘要已在窗内 ⇒ False ⇒ 这条腿让开、又没有别的候选 ⇒ 返回 ``None``
      （宁可不发也不重发，ITEM 15(b) 的字面禁令）。
    - 注毒体（窗内也返回 True）：刚发过那张被再占再发 ⇒ ``outcome.path`` 非空，
      判据当场抓得住。

    单候选 ⇒ 与 ``_probe_order`` 的哈希顺序无关。带错大小是「账目撒谎」的最短
    写实形态（文件在记录后被换过、外部直接 ``record`` 都可能落进这个状态）。
    """
    root = tmp / "lying-size"
    made = _gallery(root, 1)
    _clear_caches(module)
    window = module.RecentImageWindow()
    identity_first = module.image_identity(made[0])
    window.record(
        "private_7",
        identity_first,
        window_seconds=3600.0,
        size=made[0].stat().st_size + 4096,  # 故意带错大小：预筛放行，终判把关
    )
    outcome = module.pick_fresh_outcome(
        [str(root)], session_key="private_7", window=window, window_seconds=3600.0,
        seed="fc", allow_exhausted=False,
    )
    assert outcome.path is None, (
        "大小筛不掉这张、占坑终判又放行 ⇒ 刚发过那张又被发了一次"
        f"（现算把 {outcome.path} 又发了一遍）"
    )


def _assert_no_dead_path_from_picker(module, tmp: Path) -> None:
    root = tmp / "dead"
    made = _gallery(root, 2)
    _clear_caches(module)
    config = _config(module, root, bot_randpic_no_repeat_window_seconds=0.0)
    assert module.pick_gallery_image(config, session_key="private_7") in made
    for path in made:
        path.unlink()
    assert module.pick_random_image([str(root)]) is None, "死引用被交给了出站链"


def _assert_recycle_is_labelled(module, tmp: Path) -> None:
    root = tmp / "recycled"
    _gallery(root, 1)
    _clear_caches(module)
    config = _config(module, root)
    capability = module.build_randpic_capability(config)
    first = capability(_message(module, message_id="m-a"), None)
    second = capability(_message(module, message_id="m-b"), None)
    assert first.images and second.images
    assert "recycled_in_window" not in first.audit_tags
    assert "recycled_in_window" in second.audit_tags, (
        "同一张图的第二次发送没记账 ⇒ 用户与审计都看不见"
    )


def _assert_hint_must_be_verified(module, tmp: Path) -> None:
    root = tmp / "hint"
    root.mkdir(parents=True)
    a = root / "a.png"
    b = root / "b.png"
    a.write_bytes(PNG_MAGIC + b"first-picture!")
    b.write_bytes(PNG_MAGIC + b"second-picture")
    _clear_caches(module)
    window = module.RecentImageWindow()
    identity_a = module.image_identity(a)
    window.record("s", identity_a, window_seconds=3600.0,
                  size=b.stat().st_size, path=b)  # 提示故意指到另一张图
    resolved = module._resolve_identity_path(
        window, session_key="s", identity=identity_a, pool=[a, b], identities={},
        window_seconds=3600.0, read_identity=module.image_identity, ceiling=8,
        state={"reads": 0, "probes": 0},
    )
    assert resolved == a, "路径提示没经摘要复核就被当成『那张图』还原了"


def _assert_empty_tag_discipline(module, tmp: Path) -> None:
    _clear_caches(module)
    ghost = tmp / "ghost"
    result = module.build_randpic_capability(_config(module, ghost))(_message(module), None)
    assert "gallery_empty" not in result.audit_tags, (
        "路径没打开过，却被贴上『图库是空的』这个内容断言"
    )


def _assert_image_only_outbound(module, tmp: Path) -> None:
    root = tmp / "outbound"
    _gallery(root, 2)
    _clear_caches(module)
    result = module.build_randpic_capability(_config(module, root))(_message(module), None)
    assert result.images, "这一发本该出图"
    types_in_chain = _shipped_segment_types(module, result)
    assert types_in_chain == ["image"], (
        f"出站段里混进了别的东西（文案泄漏）：{types_in_chain}"
    )


# ------------------------------------------------------------------------ 台架


@pytest.fixture(autouse=True)
def _reset_real_module_caches():
    """真身三本账逐例复位（正例对照组也用它，必须与注毒副本同一出发条件）。"""
    randpic._SCAN_CACHE = OrderedDict()
    randpic._IDENTITY_CACHE = OrderedDict()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._SCAN_CACHE = OrderedDict()
    randpic._IDENTITY_CACHE = OrderedDict()
    randpic._DEFAULT_RECENT_WINDOW.clear()


@pytest.mark.parametrize(
    "case", CASES, ids=[case[0] for case in CASES]
)
def test_poison_breaks_the_lock_and_the_real_body_passes(
    case, tmp_path: Path
) -> None:
    """注毒副本必须炸、在盘真身必须不炸——两头同判，才不是一把恒真的锁。"""
    name, anchor, replacement, judge, _meaning = case
    poisoned = _poisoned(anchor, replacement, f"randpic_poison_{name.replace(' ', '_')}")
    with pytest.raises(AssertionError) as caught:
        judge(poisoned, tmp_path / f"poison-{name}")
    assert str(caught.value), "注毒虽被抓但没给出可读判据（诊断面不合格）"
    judge(randpic, tmp_path / "body")  # 正例：同一把尺打在真身上必须过
