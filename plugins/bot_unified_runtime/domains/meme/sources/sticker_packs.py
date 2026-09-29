"""bot **自有**表情私库的唯一读路径（STICKER-POOL 波，2026-09-29）。

**为什么要有本件**：她给守岸人挑了一包贴纸放在登记目录里，而此前全仓没有任何一条
读路径吃这个目录——三条想发贴纸的腿（P3 情绪时刻 / 戳一戳 / 偷表情）要么没得发，
要么各写一份 ``os.walk``（＝第二、第三读点，本仓「禁第二真身」点名的形态）。本件是
**唯一**读路径：要发 bot 自己的贴纸，只能从这里取。

**与另外两处贴纸账分家**（各有各的来路与闸门，不许互相顶）：

* ``domains/meme/capabilities/meme_library.py`` + ``sources/meme_library*.py`` ——
  **别人发到群里的图**（跨会话材料），读它要有收库门、SQLite 行、权重与 NSFW 降权；
* ``domains/meme/sources/sticker_pool.py`` —— 上面那库的**扫池入库腿**（写库）；
* 本件 —— **管理员自己放进登记目录**的守岸人贴纸。只读、不落盘、不建库、不打标。

**筛子只有四道**（刻意不搬 randpic 的两把体积/像素下限）：
① 扩展名白名单 ② 文件头魔数验真 ③ 0 字节拒 ④ 越出登记根拒。
贴纸本来就小、GIF 预览分辨率天然低——把 ``bot_randpic_min_side`` 那把尺搬过来，
会把她精心挑的包裁成空池。像素下限在这儿不是「更严」，是**判据错**。

**诚实缺席**（本仓「我不知道 ≠ 它没有」口径，同 ``randpic.GalleryFacts``）：目录没配 /
不存在 / 是文件不是目录 / 打不开 / 里面没东西 / 有东西但都不合用——这些事实分开记账
（``StickerFacts``），措辞由账派生。``list_sticker_images`` 回空清单**不等于**「里面没有
能发的贴纸」，除非 ``facts.opened`` 那一格为真。

**绝不自建目录**（先例 ``randpic._scan_dir``）：全件零 ``mkdir``、零写入、零 SQLite。
运行数据面只做 ``os.walk`` + 偷读文件头 + 取一张时算一次摘要。

**并发**：三条腿都跑在 ``RuntimePipeline`` 的线程池里，所以扫池缓存上锁，且
「窗内不重发」直接复用 ``randpic.RecentImageWindow``——那本窗账的 ``try_claim``
把「查 + 插」收进同一把锁，两腿盯上同一张时只有一边拿得到。本件不另立第二本窗口。
"""

from __future__ import annotations

import logging
import os
import random
import stat as _stat
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.media import image_guard, path_gate
from plugins.bot_unified_runtime.domains.meme.capabilities.randpic import (
    RecentImageWindow,
    _should_prune_dir,
    image_identity,
)

logger = logging.getLogger(__name__)

# 扩展名白名单。**与 image_guard.IMAGE_EXTENSIONS 刻意不等**，两边都不是笔误：
#   + .apng —— 动画 PNG 是贴纸的常见形态，容器签名就是 PNG 头，魔数验真照样成立；
#   - .bmp  —— 无损位图动辄几十 MB，发出去就是坏件（randpic 那侧有体积上限兜着，
#              本库不打算再搬一把体积尺，所以从源头不收）。
# 「真图还是改名件」由 ``image_guard`` 判，扩展名只是第一道筛。
_STICKER_EXTENSIONS = frozenset({".gif", ".apng", ".png", ".webp", ".jpg", ".jpeg"})

#: 扫池结果的过程内 TTL（与 ``randpic._SCAN_CACHE_TTL_SECONDS`` 同口径：她往目录里
#: 丢一包，半分钟内就该被读到，不必重启 bot——「改代码要重启」是铁律，改图库不是）。
_SCAN_CACHE_TTL_SECONDS = 30.0
#: 键数封顶（生产只有一枚登记根，余量留给测试里并存的多个 tmp 目录）。
_SCAN_CACHE_LRU_CAP = 16
#: 一轮取图最多真读几张的字节。贴纸包量级在几十到几百张，取到新鲜即止；这枚上限只
#: 防「整包都在窗内时把全库摘要一遍」，到点就按「这一轮没翻出没发过的」诚实退让。
_PROBE_CEILING = 256
#: 打散探查顺序用的盐（防不同用途的 seed 互相撞出同一串顺序）。
_PROBE_SALT = "bot-sticker-pool"


# ------------------------------------------------------------------ 观察事实


@dataclass(frozen=True)
class StickerFacts:
    """一次读池的**观察事实**（不是结论；结论在 ``verdict`` 里按优先级派生）。

    带 ``dirs_`` 前缀的格子沿用 ``randpic.GalleryFacts`` 的词，即便本库只有一枚目录：
    两族事实同名，消费侧与审计侧才不必记两套话。``dir_path`` 只进日志与审计，
    **绝不进用户可见文案**（出站打码那一道照样吃它，别赌）。
    """

    send_enabled: bool = True     # bot_sticker_enabled：发送侧总闸
    dir_configured: bool = False  # bot_sticker_dir 有值（配了，不管存不存在）
    dir_path: str = ""            # 解析后的登记根
    dirs_missing: int = 0         # 路径不存在（连存在性都不成立）
    dirs_not_directory: int = 0   # 存在但不是目录（配成文件了）
    dirs_unreadable: int = 0      # 是目录但 os.walk 当场报错（权限/卷离线/被占用）
    dirs_read: int = 0            # 真的打开并列出过（措辞能不能提内容，全看这一格）
    dirs_pruned: int = 0          # 被剪掉的子目录（缩略图/缓存/回收站/重解析点）
    files_seen: int = 0           # 列出的文件总数（「空目录」与「有东西但不是贴纸」靠它分开）
    images_seen: int = 0          # 命中扩展名白名单的张数（含后面被拒的）
    images_empty: int = 0         # 0 字节空件（无条件拒）
    images_bad_magic: int = 0     # 文件头对不上登记签名（改名 .png 的 HTML/文本）
    images_read_failed: int = 0   # 读不到文件头＝不知道，不折成「它不是图」
    images_reparse_rejected: int = 0   # 文件自身是 junction/符号链接 ⇒ 真身在登记面之外
    images_outside_root: int = 0       # resolve 后落在登记根之外
    usable: int = 0               # 真进了候选清单的张数

    @property
    def opened(self) -> bool:
        """有没有**真的打开并列出过**登记目录（决定措辞能不能提「里面没有」）。"""
        return self.dirs_read > 0

    @property
    def verdict(self) -> str:
        """把事实折成一个**可审计的原因代号**（消费侧拿它落审计标签，别自己猜）。

        优先级是刻意的：先说「闸关着 / 我打不开」（对内容一无所知），再说「打开了
        但里面没贴纸」，最后才是「有贴纸但都不合用」。反过来的话，一条写错的路径
        就会被说成「她的贴纸库是空的」——那正是本仓要拦的形态。
        """
        if not self.send_enabled:
            return "send_disabled"
        if not self.dir_configured:
            return "unconfigured"
        if self.usable > 0:
            return "usable"
        if self.dirs_missing:
            return "missing"
        if self.dirs_not_directory:
            return "not_directory"
        if self.dirs_unreadable:
            return "unreadable"
        if self.images_read_failed and self.images_read_failed >= self.images_seen:
            return "header_unreadable"
        if self.images_outside_root:
            return "outside_registered_root"
        if self.images_bad_magic:
            return "bad_magic"
        if self.images_empty:
            return "empty_images"
        if self.images_seen:
            return "all_rejected"
        if not self.files_seen:
            return "empty"
        return "no_sticker_extension"


_EMPTY_FACTS = StickerFacts()


@dataclass(frozen=True)
class _ScanResult:
    """单个登记根的扫描产出（清单 + 该根自己的观察事实）。"""

    paths: tuple[Path, ...] = ()
    facts: StickerFacts = _EMPTY_FACTS


# ------------------------------------------------------------------ 配置读取
#
# 四枚键的按名读点全在本件（配置键登记总账门据此给活性）：消费方一律走公开口，
# 别再各自 getattr —— 那会长出第二批读点、把「唯一读路径」这句写成谎话。


def configured_sticker_dir(config: Any) -> Path | None:
    """登记根（装载期已折成绝对路径的那枚值）；没配 ⇒ ``None``＝未配置，不是「空的」。"""
    raw = str(getattr(config, "bot_sticker_dir", "") or "").strip()
    if not raw:
        return None
    # 刻意不 ``resolve()``：缓存键由这条路径的 ``str()`` 决定，Windows 上解析会改写
    # 键形（大小写/短名），把「同一目录两次读命中同一份缓存」这件事打歪（同 randpic）。
    # 越界判定另有真身（``path_gate``），在真需要它的两处各判一次。
    return Path(raw).expanduser()


def sticker_send_enabled(config: Any) -> bool:
    """发送侧总闸。读不到字段按**开**算（与 ``config.py`` 缺省一致：不把「没配」当「关掉」）。"""
    return bool(getattr(config, "bot_sticker_enabled", True))


def sticker_window_seconds(config: Any) -> float:
    """窗内不重发的窗长（秒）。≤0 或非数 ⇒ 0＝关（纯随机，可重样）。"""
    try:
        value = float(getattr(config, "bot_sticker_no_repeat_window_seconds", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


def sticker_is_recursive(config: Any) -> bool:
    """``os.walk`` 递归还是只扫单层（缺省递归，同 ``config.py`` 那枚 True）。"""
    return bool(getattr(config, "bot_sticker_recursive", True))


# ------------------------------------------------------------------ 内容守卫


def guard_sticker_path(path: Path | None) -> Path | None:
    """这张**此刻**真能当图发吗？不合用返回 ``None``，**绝不抛异常**。

    两道判据，都只读到文件头这一量级（不读全量字节）：

    1. 0 字节 / stat 拿不到 / 不是常规文件 ⇒ 拒（空件扩展名再对也发不出去）；
    2. ``image_guard.read_header`` + ``header_is_image`` 魔数验真 ⇒ 把 ``x.html``
       改名 ``x.png`` 这类假扩展名在这一步拦下。

    「读不到文件头」在这里按**拒**处理，与扫描侧记 ``images_read_failed`` 不同：
    这里是**交出去之前**的最后一问，拿不准就不交（fail-closed 到「不发」）；
    扫描侧那一格要保留「我不知道」，才不会把人家目录说成是空的。

    ⚠ 本函数**不**判「在不在登记面之内」——它手上没有 ``config`` 可问。那道判据在
    :func:`pick_sticker` 的出口上做（那里既有根也有值），两闸各防一侧，别混成一处。
    """
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    try:
        info = os.stat(text)
    except OSError:
        return None
    if not _stat.S_ISREG(info.st_mode) or info.st_size <= 0:
        return None
    header = image_guard.read_header(text)
    if header is None or not image_guard.header_is_image(header):
        return None
    return path


# ------------------------------------------------------------------ 扫池


_CACHE_LOCK = threading.Lock()
#: 值 = (扫的单调时钟戳, 该目录的候选清单, 该目录的观察事实)。同 randpic 的形状。
_SCAN_CACHE: OrderedDict[str, tuple[float, tuple[Path, ...], StickerFacts]] = OrderedDict()


def _missing_scan(root: Path) -> _ScanResult:
    return _ScanResult(
        facts=StickerFacts(dir_configured=True, dirs_missing=1, dir_path=str(root))
    )


def _not_directory_scan(root: Path) -> _ScanResult:
    return _ScanResult(
        facts=StickerFacts(
            dir_configured=True, dirs_not_directory=1, dir_path=str(root)
        )
    )


def _scan_root(root: Path, *, recursive: bool) -> _ScanResult:
    """扫描登记根一趟，**把「为什么没贴纸」的事实一起带回来**（只读，绝不自建）。

    ``recursive`` 落在 ``os.walk`` 的层数上：真则整棵树，假则只看根那一层
    （``dirs.clear()`` 是 ``os.walk`` 的官方「别下潜」口，不另写深度计数）。

    重解析点（Windows junction / 符号链接）一律**不进树、不当候选**：登记面之外的一张
    都不列，这是隐私红线而不是洁癖。``os.walk(followlinks=False)`` 只挡得住 POSIX 符号
    链接，Windows 的 junction 得看 ``FILE_ATTRIBUTE_REPARSE_POINT``（判据真身
    ``path_gate.reparse_point``，本件不持第二把尺）。
    """
    if not root.exists():
        return _missing_scan(root)
    if not root.is_dir():
        return _not_directory_scan(root)

    found: list[Path] = []
    unreadable = pruned = 0
    files_seen = images_seen = empty = bad_magic = read_failed = 0
    reparse_rejected = outside_root = 0

    def _note_walk_error(_error: OSError) -> None:
        nonlocal unreadable
        unreadable += 1

    try:
        for current, dirs, files in os.walk(
            root, onerror=_note_walk_error, followlinks=False
        ):
            here = Path(current)
            if not recursive:
                dirs.clear()  # 只取根这一层；下潜与否交给 os.walk
            kept: list[str] = []
            for name in dirs:
                if _should_prune_dir(name) or path_gate.reparse_point(here / name):
                    pruned += 1
                    continue
                kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                files_seen += 1
                path = here / name
                if path.suffix.lower() not in _STICKER_EXTENSIONS:
                    continue
                images_seen += 1
                if path_gate.reparse_point(path):
                    reparse_rejected += 1
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    read_failed += 1
                    continue
                if size <= 0:
                    empty += 1
                    continue
                header = image_guard.read_header(path)
                if header is None:
                    read_failed += 1
                    continue
                if not image_guard.header_is_image(header):
                    bad_magic += 1
                    continue
                if not path_gate.is_within_registered(path, [root]):
                    outside_root += 1
                    continue
                found.append(path)
    except OSError:
        # os.walk 自己炸了（根被拔掉 / 权限中途变化）：如实记 unreadable，不假装扫过。
        unreadable += 1

    return _ScanResult(
        tuple(found),
        StickerFacts(
            dir_configured=True,
            dir_path=str(root),
            dirs_unreadable=unreadable,
            dirs_read=1,
            dirs_pruned=pruned,
            files_seen=files_seen,
            images_seen=images_seen,
            images_empty=empty,
            images_bad_magic=bad_magic,
            images_read_failed=read_failed,
            images_reparse_rejected=reparse_rejected,
            images_outside_root=outside_root,
            usable=len(found),
        ),
    )


def _collect(config: Any) -> tuple[list[Path], StickerFacts]:
    """**唯一**的池子读数口：清单与事实出自同一次扫描、同一份缓存（绝不各扫一遍）。

    ⚠ 缓存键只有「登记根 + 是否递归」两格：窗闸与开关**不进键**，读出来时按当次
    ``config`` 覆写 ``send_enabled``。生产一个进程一把尺，这个前提成立；测试里跨配置
    复用同一目录要自担（同 randpic 那侧关于阈值的注意事项一字同义）。
    """
    enabled = sticker_send_enabled(config)
    root = configured_sticker_dir(config)
    if root is None:
        return [], StickerFacts(send_enabled=enabled, dir_configured=False)
    recursive = sticker_is_recursive(config)
    key = f"{root}|{int(recursive)}"
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _SCAN_CACHE.get(key)
        if cached is not None and now - cached[0] <= _SCAN_CACHE_TTL_SECONDS:
            _SCAN_CACHE.move_to_end(key)
            return list(cached[1]), replace(cached[2], send_enabled=enabled)
        # 过期键在读取路径上惰性清除（覆盖写无法收缩字典占位），随后重扫自然回填。
        _SCAN_CACHE.pop(key, None)
    result = _scan_root(root, recursive=recursive)
    facts = replace(result.facts, send_enabled=enabled, dir_path=str(root))
    with _CACHE_LOCK:
        _SCAN_CACHE[key] = (now, tuple(result.paths), facts)
        while len(_SCAN_CACHE) > _SCAN_CACHE_LRU_CAP:
            _SCAN_CACHE.popitem(last=False)
    return list(result.paths), facts


def list_sticker_images(config: Any) -> list[Path]:
    """登记目录里**当前可用**的贴纸（30 秒 TTL 缓存；未配置/不存在 ⇒ 空清单）。

    清单按路径去重后以 ``str().lower()`` 稳定排序 ⇒ 同一批输入两次读数逐条相同。
    想知道「为什么是空的」走 :func:`sticker_facts`（同一次扫描、同一份缓存，不多扫一遍）。
    """
    images, _seen = _collect(config)
    return sorted(dict.fromkeys(images), key=lambda item: str(item).lower())


def sticker_facts(config: Any) -> StickerFacts:
    """读池子的**观察事实**版：``dirs_missing`` / ``files_seen`` / ``images_seen`` /
    ``usable`` 逐格分开，外加发送闸与登记根。降级措辞只能由这些格子派生。"""
    _images, facts = _collect(config)
    return facts


def _drop_from_listing(path: Path) -> None:
    """把一条**已不在原位**的路径从 TTL 清单里摘掉（她整理图库是真会发生的）。

    清单有 30 秒滞后：期间被删/被移走的文件仍在册，不摘就会在 TTL 内被反复挑中
    （每次都撞同一堵墙）。⚠ **观察事实那格刻意原样留着**：摘掉一条路径不等于重扫了
    整个目录，把 ``usable`` 就地减一反而会让 verdict 滑成我们没证据的说法。事实过期
    ⇒ 措辞走「刚扫到的那批已经不在了」那一档，它说的才是真知道的事。
    """
    with _CACHE_LOCK:
        for key, (stamp, listing, cached_facts) in list(_SCAN_CACHE.items()):
            if path not in listing:
                continue
            remaining = tuple(item for item in listing if item != path)
            _SCAN_CACHE[key] = (stamp, remaining, cached_facts)
            _SCAN_CACHE.move_to_end(key)
            return


# ------------------------------------------------------------------ 取一张


#: 本库**专用**的窗账实例（会话键与 randpic 同族，但两本账各记各的：_randpic 记的是
#: 图库，本账记的是私库。同一张在两边各发过一次是两码事，不许并账）。
_DEFAULT_STICKER_WINDOW = RecentImageWindow()


def _probe_order(
    images: list[Path], seed: str, *, rng: random.Random | None = None
) -> list[Path]:
    """探查顺序：带 seed ⇒ 按 seed 打散（同 seed 同序，可复现可审计）；无 seed ⇒ 洗牌。

    打散用 ``random.Random(f"{盐}|{seed}")`` 而不是自己 ``sha256`` 折模：本仓「媒体字节
    → 摘要」的唯一真身在 ``domains/media/digest.py``，字符串定序不该去蹭那把尺；stdlib
    的按种子洗牌本身就是确定性的（同 seed 同序 ⇒ 复现与审计两件事都成立）。
    """
    ordered = list(images)
    if seed:
        return random.Random(f"{_PROBE_SALT}|{seed}").sample(ordered, k=len(ordered))
    picker = rng or random
    picked = list(ordered)
    picker.shuffle(picked)
    return picked


def pick_sticker(
    config: Any,
    *,
    session_key: str = "",
    seed: str = "",
    window: RecentImageWindow | None = None,
    rng: random.Random | None = None,
    allow_exhausted: bool = True,
) -> Path | None:
    """按「窗内不重发」从 bot 自己的贴纸库里取一张；取不出 ⇒ ``None``（诚实不发）。

    参数（后三枚都带缺省，简报给的调用形 ``pick_sticker(config, session_key=…, seed=…)``
    逐字可用）：

    * ``session_key`` —— 窗账记账的会话键。``group_{G}_{U}`` 会被窗账自己收敛成
      ``group_{G}``（同 randpic 的口径：群里两个人先后要图，记的是同一本群账）；
    * ``seed`` —— 非空 ⇒ 探查顺序确定可复现（主动腿要「同样情形同样结果」）；空 ⇒ 洗牌；
    * ``window`` —— 换一本窗账（测试隔离用）；缺省走本件那枚进程级实例；
    * ``allow_exhausted`` —— 整库都在窗内时怎么办：``True``（指令路，如「偷表情」）退
      「最久没发」那张并**明确记成第二次**；``False``（主动路，如 P3 情绪时刻）本轮不发。
      主动动作宁可不发也不刷屏，用户开口要的东西不该拿「怕重复」当拒因。

    三道出口判据，逐张过（任何一道不过就换下一张，绝不把不合格的路径交给出站链）：
    :func:`guard_sticker_path`（0 字节 / 魔数）→ 登记面复核（越界不发）→
    ``RecentImageWindow.try_claim``（原子占坑，并发对手抢到了就让开）。
    """
    if not sticker_send_enabled(config):
        return None
    pool = list_sticker_images(config)
    if not pool:
        return None
    root = configured_sticker_dir(config)
    seconds = sticker_window_seconds(config)
    store = window if window is not None else _DEFAULT_STICKER_WINDOW

    def _alive(candidate: Path) -> Path | None:
        """出口三问：还在不在、是不是真图、在不在登记面之内。"""
        if guard_sticker_path(candidate) is None:
            _drop_from_listing(candidate)  # 死引用/坏件：别让它下次再占一个坑
            return None
        if root is not None and not path_gate.is_within_registered(candidate, [root]):
            logger.warning("sticker pool candidate outside registered root, held")
            return None
        return candidate

    ordered = _probe_order(pool, seed, rng=rng)

    if seconds <= 0:
        # 窗关掉＝不做不重发判定（纯随机，可重样）。仍要验活，仍受登记面约束。
        for candidate in ordered:
            checked = _alive(candidate)
            if checked is not None:
                return checked
        return None

    attempts = 0
    for candidate in ordered:
        if attempts >= _PROBE_CEILING:
            break
        attempts += 1
        checked = _alive(candidate)
        if checked is None:
            continue
        if store.try_claim(
            session_key,
            image_identity(checked),
            window_seconds=seconds,
            path=checked,
        ):
            return checked
        # 坑被抢：这张在「快照→占坑」之间被另一条腿占走并发出去了 ⇒ 让开继续探。

    if not allow_exhausted:
        return None

    # 退「最久没发」那张：有依据的复发，比凭 seed 任取一张诚实。
    oldest = store.least_recent_key(session_key, window_seconds=seconds)
    if not oldest:
        return None
    hint = store.path_hint_for(session_key, oldest, window_seconds=seconds)
    recycled: Path | None = _alive(Path(hint)) if hint else None
    if recycled is None:
        # 账本里的路径提示已失效（她把它移走了）：退到本轮第一个还活着的候选，
        # 仍按「窗内复发」记账，不冒充第一次发。
        recycled = next((item for item in (_alive(x) for x in ordered) if item), None)
    if recycled is None:
        return None
    store.record(
        session_key,
        image_identity(recycled),
        window_seconds=seconds,
        path=recycled,
    )
    return recycled


def reset_sticker_state() -> None:
    """测试复位口：清扫池缓存 + 清进程级窗账。生产代码不该调它。"""
    with _CACHE_LOCK:
        _SCAN_CACHE.clear()
    _DEFAULT_STICKER_WINDOW.clear()


__all__ = [
    "StickerFacts",
    "configured_sticker_dir",
    "guard_sticker_path",
    "list_sticker_images",
    "pick_sticker",
    "reset_sticker_state",
    "sticker_facts",
    "sticker_is_recursive",
    "sticker_send_enabled",
    "sticker_window_seconds",
]
