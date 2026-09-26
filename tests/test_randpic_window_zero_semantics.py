"""SEAT-RANDPIC-0S（2026-09-27）「不重复窗口 0 秒/0 值语义」的现算证据 + 回归锁。

台账在册疑点（上一窗登记，try_claim 原子化那批之后）：窗口宽度为 **0 / 缺省 /
负值 / 极大值** 时，可能的缺陷形态有四种——

1. 窗口**永不清退**（过期判定短路，旧账赖着不走）；
2. 0 被当成「**不限**」（窗账把关态读成无限窗）；
3. **时钟比较恒假**（now-entry > window 永远不成立）；
4. 旧口径「快照→无条件记档」改原子占坑后的**跟随残留**（某条腿绕过入口闸、
   拿着原始配置值直捅 RecentImageWindow）。

本件**逐分支现算**（缺省 0.0 / 0 / 负值 / NaN / 极大有限值 / inf 各走哪条分支），
并把「今天语义正确」锁成可注毒的回归锁：入口 `no_repeat_window_seconds` 的钳位、
`pick_gallery_image_outcome` 的 `<=0` 短路闸、原语的 `window_seconds > 0` 时间
清退判据、三处生产触发面只能经带闸入口——任何一处被改歪，本件必红。

诚实口径（缺陷**不成立**的那一半也要有证物）：
- 经配置路（唯一生产路），0/负值/NaN/坏值全被钳成 0 并在入口短路成「关态＝纯
  随机、窗账零参与」，四种缺陷形态都到不了用户-visible 行为；
- 但 **RecentImageWindow 原语自身**对 `window_seconds<=0` 的语义确实是
  「不限窗」（`_prune` 跳过时间清退、`try_claim` 对已占条目恒 False）——这是一枚
  *潜伏形状*，今天靠入口闸不可达。本件把该形状按现状锁死（防止「顺手改成
  0=立即过期」这类语义漂移双向发生），并用 AST 可达性锁把「生产不许绕过带闸
  入口直捅原语」钉住。

全离线：图片是 tmp_path 里的假字节，零网络、零真实协议端；三处模块级缓存逐例
清空（先例 tests/test_randpic_no_repeat_ledger.py 的 autouse 夹具）。
"""

from __future__ import annotations

import ast
import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from plugins.bot_unified_runtime.domains.meme.capabilities import randpic
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    RecentImageWindow,
    no_repeat_window_seconds,
    pick_gallery_image,
    pick_gallery_image_outcome,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/bot_unified_runtime"
RANDPIC_PY = PLUGIN_ROOT / "domains/meme/capabilities/randpic.py"

_PNG = b"\x89PNG\r\n\x1a\n"
_SESSION = "group_9_9"


@pytest.fixture(autouse=True)
def _clean_caches():
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    yield
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()


def _gallery(root: Path, count: int) -> list[Path]:
    """每张写入**互异字节**（内容摘要判据 ⇒ 大小也互异，避开大小加速道的搅局）。"""
    root.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for index in range(count):
        path = root / f"image_{index}.png"
        path.write_bytes(_PNG + f"payload-{index}".encode())
        made.append(path)
    return made


def _config(gallery: Path, **overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "bot_randpic_dirs": [str(gallery)],
        "bot_randpic_no_repeat_window_seconds": 3600.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _CountingWindow(RecentImageWindow):
    """记录「窗账有没有被生产路摸过」的探针件——关态下读数必须恒 0。"""

    def __init__(self) -> None:
        super().__init__()
        self.touches = 0

    def recent_keys(self, *args: Any, **kwargs: Any) -> frozenset[str]:
        self.touches += 1
        return super().recent_keys(*args, **kwargs)

    def recent_sizes(self, *args: Any, **kwargs: Any) -> tuple[frozenset[int], bool]:
        self.touches += 1
        return super().recent_sizes(*args, **kwargs)

    def try_claim(self, *args: Any, **kwargs: Any) -> bool:
        self.touches += 1
        return super().try_claim(*args, **kwargs)

    def record(self, *args: Any, **kwargs: Any) -> None:
        self.touches += 1
        super().record(*args, **kwargs)


# ------------------------------------------------------------------ ① 钳位件现算：每种取值走哪条分支


def test_clamp_computes_every_value_shape() -> None:
    """缺省(无键)/0/负值/None/坏串/NaN → 0.0（关）；有限大值原样；inf 原样（有意不限）。"""
    assert no_repeat_window_seconds(SimpleNamespace()) == 0.0          # 缺省=键不存在
    assert no_repeat_window_seconds(SimpleNamespace(bot_randpic_no_repeat_window_seconds=0.0)) == 0.0
    assert no_repeat_window_seconds(SimpleNamespace(bot_randpic_no_repeat_window_seconds=-3600.0)) == 0.0
    assert no_repeat_window_seconds(SimpleNamespace(bot_randpic_no_repeat_window_seconds=None)) == 0.0
    assert no_repeat_window_seconds(SimpleNamespace(bot_randpic_no_repeat_window_seconds="abc")) == 0.0
    assert no_repeat_window_seconds(SimpleNamespace(bot_randpic_no_repeat_window_seconds="")) == 0.0
    # NaN：max(0.0, nan) 的比较 nan > 0.0 恒假 ⇒ 保留 0.0 = 关（不是「恒假时钟」那条路）。
    assert no_repeat_window_seconds(
        SimpleNamespace(bot_randpic_no_repeat_window_seconds=float("nan"))
    ) == 0.0
    # 极大有限值/inf 是**用户明示的「尽量不重发」**，钳位不吞它——代价由窗账的
    # LRU 上限（_PER_SESSION_CAP）兜底，见下面 bounded 锁。
    assert no_repeat_window_seconds(
        SimpleNamespace(bot_randpic_no_repeat_window_seconds=3_153_600_000.0)
    ) == 3_153_600_000.0
    assert math.isinf(
        no_repeat_window_seconds(
            SimpleNamespace(bot_randpic_no_repeat_window_seconds=float("inf"))
        )
    )


# ------------------------------------------------------------------ ② 关态短路：0/负值绝不摸窗账


@pytest.mark.parametrize("window_value", [0.0, -3600.0, None, "abc", float("nan")])
def test_disabled_shapes_never_touch_the_ledger(tmp_path: Path, window_value: object) -> None:
    """缺陷形态①②③的配置路证伪：≤0 全钳成关，入口短路走纯随机，窗账**零次参与**。

    注毒向：若有人把入口闸从 `<= 0` 改歪（或删掉），关态就会开始摸窗账——本锁
    当场红。若有人把钳位件的 `max(0.0, …)` 摘了，负值/NaN 会把「不限窗」语义带进
    开态——同样当场红（那条走的是 pick_fresh_outcome，见形态②锁）。
    """
    counter = _CountingWindow()
    randpic._DEFAULT_RECENT_WINDOW = counter  # 入口 store 缺省回落就在这枚模块单例上
    try:
        _gallery(tmp_path / "g", 3)
        config = _config(
            tmp_path / "g", bot_randpic_no_repeat_window_seconds=window_value
        )
        for index in range(6):
            picked = pick_gallery_image(config, session_key=_SESSION, seed=f"s{index}")
            assert picked is not None  # 库里有货，关态必发（旧行为逐字节同形）
        assert counter.touches == 0, (
            f"窗值 {window_value!r} 本该短路成关态，窗账却被摸了 {counter.touches} 次"
        )
    finally:
        randpic._DEFAULT_RECENT_WINDOW = RecentImageWindow()


# ------------------------------------------------------------------ ③ 原语现算：时钟比较非恒假


def test_clock_comparison_is_not_always_false() -> None:
    """窗=60 的账：+50s 仍占坑（同图不发），+100s 超窗**必须复开**（清退判据真能翻）。

    注毒向：把 `_prune`/`try_claim` 的 `window_seconds > 0 and now - entry[0] >
    window_seconds` 改成恒假（形态③），第二跳的 True 断言当场红。
    """
    window = RecentImageWindow()
    assert window.try_claim("s", "id-a", window_seconds=60.0, now=1000.0) is True
    assert window.try_claim("s", "id-a", window_seconds=60.0, now=1050.0) is False
    # 1100-1000=100 > 60 ⇒ 超窗旧行算「可占」（覆写并 True）——与 recent_keys 惰性过期同口径。
    assert window.try_claim("s", "id-a", window_seconds=60.0, now=1100.0) is True


def test_primitive_zero_or_negative_means_unlimited_yet_is_unreachable_by_config() -> None:
    """形态②的**诚实证物**：原语自身确实把 ≤0 读成「不限窗」——但生产拿不到它。

    今天（且今后按本锁）：`try_claim(window_seconds=0.0)` 占坑后哪怕时钟推进 1e12
    秒也不复开；`_prune` 对 ≤0 跳过时间清退。入口 `pick_gallery_image_outcome`
    的 `<=0` 短路 + 钳位件保证配置值到不了这层（上一条参数化锁 + 下一条可达性锁
    钉住），所以「0 被当不限」只在**绕过带闸入口直捅原语**时才成立——而那是不许
    发生的（见 AST 锁）。双向注毒：原语语义漂成「0=立即过期」或入口闸被删，红。
    """
    window = RecentImageWindow()
    assert window.try_claim("s", "id-a", window_seconds=0.0, now=0.0) is True
    assert window.try_claim("s", "id-a", window_seconds=0.0, now=1e12) is False
    assert window.try_claim("s", "id-a", window_seconds=-5.0, now=1e12) is False
    assert "id-a" in window.recent_keys("s", window_seconds=0.0, now=1e12)


# ------------------------------------------------------------------ ④ 极大值分支：不清退但有界


def test_huge_window_never_time_expires_but_stays_bounded(tmp_path: Path) -> None:
    """窗=100 年：库 2 张 —— 前两张各发一次(picked)，第三张起指令腿退最久(recycled)、

    主动腿诚实不发(held)；且窗账条数**有界**（LRU 封顶，「永不清退」不等于「无限吃
    内存」）。这是「极大值」分支的现算结果：时间维确实不expire（用户明示的语义），
    空间维由 _PER_SESSION_CAP 兜底。
    """
    made = _gallery(tmp_path / "g", 2)
    config = _config(
        tmp_path / "g", bot_randpic_no_repeat_window_seconds=3_153_600_000.0
    )
    first = pick_gallery_image_outcome(config, session_key=_SESSION, seed="h1")
    second = pick_gallery_image_outcome(config, session_key=_SESSION, seed="h2")
    assert first.reason == "picked" and second.reason == "picked"
    assert first.path is not None and second.path is not None  # picked ⇒ 必有路径（收窄传参）
    assert {randpic.image_identity(first.path), randpic.image_identity(second.path)} == (
        {randpic.image_identity(made[0]), randpic.image_identity(made[1])}
    ), "两张互异新鲜图被同一本大窗账放行成同一张 ⇒ 占坑终判失效"
    third = pick_gallery_image_outcome(config, session_key=_SESSION, seed="h3")
    assert third.path is not None and third.reason.startswith("recycled"), (
        f"整库在窗内时指令腿应退「最久没发」，实际 reason={third.reason}"
    )
    held = pick_gallery_image_outcome(
        config, session_key=_SESSION, seed="h4", allow_exhausted=False
    )
    assert held.path is None and held.reason == "held_pool_exhausted"
    ledger = randpic._DEFAULT_RECENT_WINDOW.recent_keys(
        _SESSION, window_seconds=3_153_600_000.0
    )
    assert len(ledger) == 2  # 大窗不 expire，但库只有 2 张 ⇒ 账也只有 2 条，不增殖


# ------------------------------------------------------------------ ⑤ 可达性锁：生产不许绕过带闸入口


def _call_names(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else ""
            )
            found.add(name)
    return found


def test_production_reaches_the_window_only_through_the_gated_entry() -> None:
    """形态④（跟随残留）的证伪：全 plugins/ 里直接调原语取图口
    （pick_fresh_image/pick_fresh_outcome）的**唯一文件就是 randpic.py 自己**，
    且其调用者 `pick_gallery_image_outcome` 体内必须留着 `window_seconds <= 0`
    短路闸。三触发面（指令能力/回复后腿/被戳 randpic 臂）经
    test_randpic_no_repeat_ledger.py 的「同一张嘴」锁已钉在带闸入口上——本锁钉住
    的是「别再有第二条不经过闸的嘴」。
    """
    offenders: list[str] = []
    for py in PLUGIN_ROOT.rglob("*.py"):
        if py == RANDPIC_PY:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        names = _call_names(tree)
        if names & {"pick_fresh_image", "pick_fresh_outcome"}:
            offenders.append(str(py.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"绕过带闸入口直捅原语取图口的生产文件出现：{offenders}"
    )

    source = ast.parse(RANDPIC_PY.read_text(encoding="utf-8"))
    entry = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "pick_gallery_image_outcome"
    )
    guarded = False
    for node in ast.walk(entry):
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.LtE):
            left = node.left
            if isinstance(left, ast.Name) and left.id == "window_seconds":
                guarded = True
    assert guarded, "带闸入口的 `window_seconds <= 0` 短路闸没了 ⇒ 关态会开始摸窗账"


# ------------------------------------------------------------------ ⑥ 注毒自证（本仓两判据惯例）


def _exec_module(source: str, name: str) -> types.ModuleType:
    """把一份注毒源码副本当模块跑起来（跑完摘掉，不留影子模块；不落源码树）。"""
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


def test_locks_have_teeth_poisoning_the_entry_guard_turns_them_red(tmp_path: Path) -> None:
    """注毒自证：① 打在注毒副本上必须炸，② 打在在盘真身上必须不炸。

    注毒=把短路闸 `if window_seconds <= 0:` 改成 `if False:`：关态（缺省 0.0）也
    会进原语取图口，而原语对 `window_seconds<=0` 的「占坑永不复开」语义（形态②）
    当场生效——本件的 `touches == 0` 判据必须抓得住它，否则就是空跑。

    诚实附注：单发注毒 `<= 0` → `== 0` **不改变可观察行为**（钳位件
    `max(0.0, …)` 保证进来的值恒 ≥0，`==0` 与 `<=0` 在此同形）——那是纵深防御，
    不是锁的漏洞；要越过双闸得同时坏两处。
    """
    source = RANDPIC_PY.read_text(encoding="utf-8")
    anchor = "    if window_seconds <= 0:"
    assert source.count(anchor) == 1, "锚点脱靶（入口闸那行变了）⇒ 请同步本发注毒，别改松判据"
    poisoned = cast(
        Any,
        _exec_module(source.replace(anchor, "    if False:", 1), "rp_poison_entry_guard"),
    )

    counter = _CountingWindow()
    poisoned._DEFAULT_RECENT_WINDOW = counter
    _gallery(tmp_path / "g", 2)
    config = _config(tmp_path / "g", bot_randpic_no_repeat_window_seconds=0.0)
    for index in range(3):
        poisoned.pick_gallery_image(config, session_key=_SESSION, seed=f"p{index}")
    assert counter.touches > 0, "注毒短路闸后仍 touches==0 ⇒ 本锁空跑，判据写歪了"

    # ② 在盘真身同判据必须绿。
    randpic._SCAN_CACHE.clear()
    randpic._IDENTITY_CACHE.clear()
    randpic._DEFAULT_RECENT_WINDOW.clear()
    real_counter = _CountingWindow()
    randpic._DEFAULT_RECENT_WINDOW = real_counter
    try:
        for index in range(3):
            randpic.pick_gallery_image(config, session_key=_SESSION, seed=f"p{index}")
        assert real_counter.touches == 0
    finally:
        randpic._DEFAULT_RECENT_WINDOW = RecentImageWindow()
