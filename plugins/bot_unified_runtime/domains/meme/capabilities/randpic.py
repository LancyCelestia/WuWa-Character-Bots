"""随机图片能力（bot.randpic）：触发指令时从**用户自定义文件夹**随机发一张图。

设计（借鉴 nonebot-plugin-randpic 的"指令→随机图"玩法，MIT，仅吸收思路）：
- **只读取用户配置的目录**（BOT_RANDPIC_DIRS），绝不自建 randpic 文件夹、
  不建数据库、不做上传——那是原插件的存储层，本能力一把随机梭哈即可。
- 递归扫描目录下图片扩展名，进程内 TTL 缓存文件清单（改文件夹 30 秒内生效）。
- 目录未配置/为空/全部不可读 → 友好降级文案，绝不报错、绝不落新文件。

P14 波（2026-09-25「完善随机发图系统」）加的半边：**同一个取图口**也服务
主动发图（回复完用户消息后、以及用户戳完 bot 后由臂矩阵触发）。三触发共用
``list_gallery_images`` / ``pick_fresh_image`` 这一条读图路径，绝不另起第二份
目录扫描器；「窗内不重发」由 ``RecentImageWindow`` 承载（缺省窗 0 秒=关，
关态与旧实现逐字节同形）。发图的**门链**（概率/冷却/安静时间/blocked 名单）
不在本件，唯一真身见 ``domains/chat_reply/capabilities/poke.py`` 的
``proactive_action_allowed``（社交主动接触共用一门身，避免第二真身）。

P15 波（2026-09-25 S-T-RANDPIC-1）补的是**池子那一侧**，四条：

1. **观察事实与措辞分开**：``GalleryFacts`` 记下「配了几条目录 / 哪条根本不存在 /
   哪条不是目录 / 哪条读不动 / 列出了多少文件 / 多少张是图片格式 / 多少张超过单张
   上限」，``gallery_degradation_line`` 只按这些事实说话。旧写法六种事实压成一个
   ``[]``，然后对着没打开过的目录断言「里面没有能发的图片」——那是「我不知道」被
   写成「它没有」。
2. **降级那句话真能发出去**：旧分支同时标 ``SendPolicy.SILENT_AUDIT``，而管线对它的
   处置是 ``ReceiptState.SKIPPED`` + 空正文 ⇒ 文案永远只在源码里。
3. **取图只读要读的那几张**：同图判据仍是内容 SHA-256（唯一真身 ``media_digest_file``），
   但「这张在不在窗内」先用**文件大小**做超集排除（内容相同 ⇒ 大小必相同），只在大小
   撞车时才真读字节；整库都在窗内时按账本里的路径提示 O(1) 还原「最久没发」那一张。
   现网图库实测 23,353 张 / 89,982 MB，旧写法每次取图要把全库摘要一遍（≈127s，而记忆化
   上限 1024 远小于库容量 ⇒ 每次都重来）。
4. **交出去的路径必须此刻还活着**：TTL 清单里的死引用在挑中时就地摘掉。这不是洁癖——
   ``domains/transport/sender/onebot.py`` 的 image 面闸到本波为止仍是留白（record/video/file
   三面才有闸），死路径会一路走到协议端；2026-09-28 B1 波把 image 面闸也装上了，
   本层的验活仍是**第一道**（两闸各防一侧：这里防死引用被挑中，出站闸防上游任何
   能力把死路径直接塞进部件）。

B1 池子守卫波（2026-09-28）把「扫进来的是不是真图」也记进账：扫描跳过缩略图/缓存
风格的子目录；0 字节空文件永不进候选；字节下限（``bot_randpic_min_file_kb``）与像素
短边下限（``bot_randpic_min_side``，现值以 ``config.py`` 该字段为真身）在配置里开着时，
逐张做文件头魔数验真与图头短边判定（内容质检唯一真身 ``domains/media/image_guard.py``），
被挡原因按 ``images_empty`` / ``images_below_min_bytes`` / ``images_bad_magic`` /
``images_below_min_side`` 分账——措辞仍由事实派生。两枚下限都不设（读不到配置键的
调用口缺省 0）时扫描行为与 B1 之前逐字节同形。

⚠ 2026-09-29 用户裁定把 Config 那两枚下限的**缺省归零**（图库是他自己管的 Picture
目录，人工整理，不由 bot 硬筛），所以生产今天走的就是上面那句「逐字节同形」的关态；
键与参数面全部保留作逃生口，任一键调回 > 0 即三层内容筛（字节闸 → 魔数闸 → 短边闸，
顺序即代价序）重新生效。关态下**仍然生效**的只有本件另外几层：``_should_prune_dir``
子目录剪枝、0 字节空件拒收、重解析点不进树（下面 PIC 段）、单张体积上限，
以及出口的登记面收口与 ``transport/sender/onebot.py`` 的 image 面死引用闸。

PIC 容器面（2026-09-29，需求 15 的隐私红线 + 容器逃逸根治）补的是**「扫进来的东西
到底在不在登记面里」**这一格，三条：

1. **重解析点不进树**：登记目录里放一枚 junction（或符号链接）指向别处时，
   ``os.walk`` 原本照进不误——Windows 下 junction 的 ``os.path.islink`` 为**假**，
   只有 ``FILE_ATTRIBUTE_REPARSE_POINT`` 认得它（本机取证见 ``tests/test_media_path_gate.py``
   的「纯词法归一必判它能穿」那格牙齿）。修前实测：私人相册整摞进候选清单，
   ``pick_random_image`` 交出 ``resolve()`` 后根本不在登记根里的那张。
2. **出口再判一次**：``pick_gallery_image_outcome`` 交路径前问一句
   :func:`read_is_registered`（判据唯一真身 ``domains/media/path_gate.py``）——
   TTL 清单被旧口径残留或被别处塞进登记面之外的路径时也必须 hold，
   代号 ``out_of_registered_root``，绝不把越界路径交给出站链。
3. **入站附件面永不得当图库**：``BOT_RANDPIC_DIRS`` 里若有人把「别人发来的图」的
   落点（下载目录 / 媒体归档 / 表情库）登记成图库，那是跨会话泄露的通路——
   整条拒读，代号 ``denied_root``（这一格只在传了 ``config`` 的调用口生效，
   纯 dirs 调用口行为与 PIC 波之前逐字节同形）。
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import stat as _stat
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger
from plugins.bot_unified_runtime.domains.media import image_guard, path_gate

# 拼音全拼/缩写（T-Spec T1.5/T1.6）：suijitu/laizhangtu 同覆盖繁体同音
# （隨機圖/來張圖）；sjt/lzt 查重无冲突。前缀+标点边界逻辑天然防
# suijituqq 类字母胶合（tail 首字符不在标点集即拒绝）。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "随机图", "来张图", "隨機圖", "來張圖", "randpic",
    "suijitu", "laizhangtu", "sjt", "lzt",
)
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
# HEIC/HEIF/AVIF **刻意不进**扩展名集合：QQ 客户端侧不保证解码，发出去就是坏件。
# 内容是否真是图由 image_guard 的魔数/像素守卫按文件头判定，扩展名只是第一道筛。
_SCAN_CACHE_TTL_SECONDS = 30.0
_MAX_FILE_BYTES = 20 * 1024 * 1024
# ⚠ 与 config ``bot_randpic_max_file_mb``（现值以 config.py 该字段为真身）存在历史
# 漂移：模块常量只在「拿不到配置键」时兜底。统一两把尺属配置面改动，B1 波不做，
# 已按简报记入待裁（改哪把尺要用户点头，本件不自作主张）。

#: 池子扫描跳过的目录名（B1 守卫波）。**只拦这三形**，其余目录一律照走——
#: 用户真实图库里有 ``Random pics`` 这类带空格目录，绝不多裁：
#: ① 名字以 ``.`` 或 ``_`` 开头（资源叉/.thumbnails/__pycache__ 之类）；
#: ② 整名（不分大小写）命中 thumbs?/thumbnails?/cache(s)/preview(s)，可带 ``_数字`` 后缀；
#: ③ 回收站目录字面量（#RecycleBin、$RECYCLE.BIN、群晖 @eaDir）。
_PRUNE_DIR_RE = re.compile(r"^(?:thumbs?|thumbnails?|caches?|previews?)(?:_\d+)?$", re.IGNORECASE)
_PRUNE_DIR_EXACT = frozenset({"#recyclebin", "$recycle.bin", "@eadir"})


def _is_reparse_point(path: str | Path) -> bool:
    """这条路径自己是不是重解析点（junction / 符号链接）——判据真身在 ``path_gate``。

    本件留一枚**薄壳**而不是就地直呼 ``path_gate.reparse_point``：扫描侧要能在没有
    真链接的机器上被测试桩掉（``tests/test_randpic_registered_root.py`` 的替身腿），
    这一格就是可桩点。壳里不持第二把尺。
    """
    return path_gate.reparse_point(path)


def _should_prune_dir(name: str) -> bool:
    """目录名是否命中上面的登记集（命中则 os.walk 不进这个子树）。"""
    text = str(name)
    if text.startswith((".", "_")):
        return True
    if text.lower() in _PRUNE_DIR_EXACT:
        return True
    return bool(_PRUNE_DIR_RE.match(text))

# 审查 L-10：_SCAN_CACHE 原本只有 30s TTL，过期键不删、键数无上限——
# 长跑进程按目录键无界增长。对齐项目 LRU 惯例（先例：runtime/reactions.py
# 的 _REACTION_LRU_CAP 批次）：键数封顶 _SCAN_CACHE_LRU_CAP、触达即
# move_to_end、超界淘汰最久未用键；过期键在读取路径惰性清除后重扫回填。
# 扫描结果本身的语义（键→清单映射、TTL 内复用）零变化。
_SCAN_CACHE_LRU_CAP = 512
# 值 = (扫的单调时钟戳, 该目录的候选清单, 该目录的观察事实)。
# 第三格是 P15 加的；读取侧 ``_cached_facts`` 容忍旧的二元组形态（测试里会手塞
# ``(ts, [])`` 这种形状测缓存治理，别让它们把读数口打崩）。
_SCAN_CACHE: OrderedDict[str, tuple[float, list[Path], GalleryFacts]] = OrderedDict()


# 词尾边界字（Wave G T66 收编）：判定循环上收 domains/core/text_boundary.py
# 的 is_trigger，本文件只剩取值登记。逐字节=现行手抄串（比中央权威集
# TRIGGER_BOUNDARY_CHARS 少 　\t、比 PARTICLE_BOUNDARY_CHARS 少 哦嘛咯哇——
# 统一加宽属行为变更，本波不做，diff 见
# .superpowers/sdd/2026-09-19-unify-audit/report-T66.md 披露表）。
_BOUNDARY_CHARS = "，,。！？!?：:、 的了呢吗呀啊哈～~"


def is_randpic_command(text: str, trigger_words: list[str] | tuple[str, ...] | None = None) -> bool:
    """触发词判定：整句等于触发词，或触发词后跟标点/空白边界。

    保守边界与 mentions 同哲学：避免「随机图片库」这类包含关系词误触发。
    判定逻辑收编中央件（Wave G T66）；大小写敏感/裸词命中/现行字符集经
    显式传参逐字节保持。
    """
    triggers = tuple(trigger_words) if trigger_words else DEFAULT_TRIGGER_WORDS
    return is_trigger(
        text,
        triggers,
        case_insensitive=False,
        bare_word=True,
        newline_as_space=False,
        boundary_chars=_BOUNDARY_CHARS,
        extra_boundary_chars="",
    )


# ------------------------------------------------------------------ 池子那侧的「我们究竟看见了什么」
#
# S-T-RANDPIC-1（ITEM 15 池子半边）。旧实现把「路径不存在 / 存在但不是目录 /
# 目录读不动（权限、盘没挂上、被占用）/ 目录里根本没有图片扩展名 / 有图但全部
# 超过单张体积上限 / stat 拿不到」六种事实统统压成一个空清单（``_scan_dir`` 只
# 往外吐 list[Path]，``root.is_dir()`` 为假时静默 ``[]``），于是能力层只能猜一句
# 降级话术——而它猜的那句恰好是最不诚实的一种：对着**从未打开过**的目录断言
# 「里面没有能发的图片」。本仓的禁令是「我不知道 ≠ 它没有」（见 ``cd0068c`` /
# ``21bdabf`` 同族），故这里把六种事实分开记账，措辞由事实派生，不由模板派生。
#
# 判据口径（重要）：只有**真的列出过目录**并且没命中图片扩展名，才可以说
# 「里面没有能发的图片格式」；目录打不开时只能说「我没能打开它」，绝不外推内容。


@dataclass(frozen=True)
class GalleryFacts:
    """一次池子读数的**观察事实**（不是结论；结论在 ``verdict`` 里按优先级派生）。"""

    dirs_configured: int = 0
    dirs_missing: int = 0          # 路径不存在（连存在性都不成立）
    dirs_not_directory: int = 0    # 存在，但不是目录（配成文件了）
    dirs_unreadable: int = 0       # 是目录，但 os.walk 当场报错（权限/卷离线/被占用）
    dirs_read: int = 0             # 成功列出的目录数
    files_seen: int = 0            # 列出来的文件总数（不分扩展名）——「空的」与「有东西但没有图」靠它区分
    images_seen: int = 0           # 命中图片扩展名的文件数（含超限的）
    images_over_limit: int = 0     # 其中因超过单张体积上限被排除的
    images_stat_failed: int = 0    # 其中 stat 拿不到、无法判定的（不猜大小）
    # ---- B1 池子守卫波（2026-09-28）新增的四本内容账 ----
    images_empty: int = 0          # 0 字节空文件（无条件拒，扩展名再对也发不出去）
    images_below_min_bytes: int = 0  # 低于字节下限（bot_randpic_min_file_kb）被挡的
    images_bad_magic: int = 0      # 文件头对不上登记签名 / 魔数对上却解不开的坏件
    images_below_min_side: int = 0   # 短边低于像素下限（bot_randpic_min_side）被挡的
    # ---- PIC 容器面（2026-09-29）新增的三本账 ----
    dirs_refused_denied: int = 0   # 登记项落在「别人发来的图」落点上 ⇒ 整条拒读（跨会话红线）
    dirs_pruned_links: int = 0     # 登记根里的重解析点子树（junction/符号链接）没进树
    images_reparse_rejected: int = 0  # 文件本身是重解析点（真身在登记面之外）被拒的
    usable: int = 0                # 真正进了候选清单的张数

    @property
    def verdict(self) -> str:
        """把事实折成一个**可审计的原因代号**（措辞由它派生，不再靠模板猜）。

        优先级是刻意的：先说「我打不开」（我们对内容**一无所知**），再说「我打开了但
        里面没有图片」，最后才是「有图但都不合用」。反过来的话，一条写错的路径就会被
        说成「你的图库是空的」——那正是「我不知道 ≠ 它没有」要禁的形态。
        """
        if self.dirs_configured == 0:
            return "unconfigured"
        if self.usable > 0:
            return "usable"
        if self.dirs_refused_denied:
            # 优先级排在 missing 之前：这一格说的是「有一条登记项我不肯读」，
            # 而不是「那条路打不开」。混成后者会把用户自己的配置说成坏的。
            return "denied_root"
        if self.dirs_missing:
            # 代号必须是 missing：措辞表与 ``gallery_audit_tags`` 的排除规则都按
            # 「missing ≠ 打开过」写好了，这里回 "empty" 会让一条写错的路径被说成
            # 「你的图库是空的」——正是上面那条禁令要拦的形态。
            return "missing"
        if self.dirs_not_directory:
            return "not_directory"
        if self.dirs_unreadable:
            return "unreadable"
        if self.images_stat_failed and not self.images_seen:
            return "stat_failed"
        if self.images_seen and self.images_seen == self.images_over_limit:
            return "over_limit"
        if self.images_seen and not self.usable:
            # 打开过、有图片扩展名的文件、却没一张进候选：先报**有证据**的拒绝原因
            # （B1 守卫波的四本账 + PIC 容器面的一本），摊不到任何一本才回 stat_failed
            # （旧兜底口径不动）。优先级按「对内容的了解程度」排：链接外指 > 验出假图
            # > 糊图 > 小图 > 空文件。
            if self.images_reparse_rejected:
                return "linked_outside_root"
            if self.images_bad_magic:
                return "bad_magic"
            if self.images_below_min_side:
                return "below_min_side"
            if self.images_below_min_bytes:
                return "below_min_bytes"
            if self.images_empty:
                return "empty_images"
            # 以上都不命中 ⇒ 只剩 stat 失败这一种可能。
            return "stat_failed"
        if self.images_seen:
            return "over_limit"
        if not self.files_seen:
            return "empty"
        return "no_image_extension"

    @property
    def opened(self) -> bool:
        """有没有至少一个目录是**真的被打开并列出过**的（决定措辞能不能提内容）。"""
        return self.dirs_read > 0


_EMPTY_FACTS = GalleryFacts()

#: 单次取图最多「读字节」几张。现网图库实测 23,353 张 / 89,982 MB ⇒ 整库摘要一趟
#: ≈127 秒（本机 sha256 实测 707 MB/s，抽样 3,234 MB/4.58s 标定），旧写法每次取图
#: 都这么扫一遍全库；见 .superpowers/sdd/2026-09-25-goal18-wave/logs/S-T-RANDPIC-1.md。
#: 池子大于这个上限时**不再声称**「整库都在窗内」，只说「这一轮没翻出没发过的」——
#: 主动腿照旧不发，指令腿退「最久没发」那张，两种情形分代号记账（不把没证明的说成证明了）。
_FRESH_PROBE_CEILING = 512


def _gallery_root(raw: str) -> Path:
    """配置项 → 目录。语义与旧实现逐字节相同，只多一枚 ``expanduser``。

    - 绝对路径原样；相对路径按**进程 CWD** 拼接（这枚键不在 ``config.py`` 的
      ``path_fields`` 里 ⇒ 不走 ``scripts/runtime_paths.py`` 的 ``data/`` 重映射，
      口径见 ``docs/boards/B06-media-entertainment/meme/randpic.md``「相对目录按
      进程工作目录解析」；把键接进 path_fields 属配置面改动＝另裁，本件不动）。
    - 刻意**不做** ``resolve()``：``_SCAN_CACHE`` 的键由这条路径的 ``str()`` 决定，
      解析会改写键形（Windows 大小写/短名），把缓存卫生锁
      ``tests/test_randpic_scan_cache_l10.py`` 的复刻尺打歪。
    - ``~`` 展开是新加的：旧写法 ``Path("~/Pictures")`` 不报错，会安静地变成
      ``<CWD>/~/Pictures`` ⇒ 池子永远「为空」，正是本波要修的「把读不到说成没有」。
    """
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


@dataclass(frozen=True)
class _ScanResult:
    """单个目录的扫描产出（清单 + 该目录自己的观察事实）。"""

    paths: tuple[Path, ...] = ()
    facts: GalleryFacts = _EMPTY_FACTS


def _scan_dir(
    root: Path, max_bytes: int, *, min_bytes: int = 0, min_side: int = 0
) -> _ScanResult:
    """递归扫描一个目录，**把「为什么没图」的事实带回来**（旧实现只带回顾清单）。

    只读：绝不创建目录/文件（``tests/test_randpic_identity.py`` 与
    ``tests/test_randpic_dispatch.py`` 各有一条「绝不自建」锁执法这一点）。

    B1 守卫波（2026-09-28）加的三层筛子，逐层分账（登记判据见模块头部与
    ``_should_prune_dir``）：

    - **子目录剪枝**：缩略图/缓存风格目录（``.``/``_`` 前缀、thumbs/cache/preview
      整名、回收站目录）不进树——那里挖出来的多半是糊图或系统件；
    - **重解析点不进树、不当候选**（PIC 容器面）：目录 junction 记 ``dirs_pruned_links``、
      文件链接记 ``images_reparse_rejected``——登记面之外的一张都不列；
    - **0 字节无条件拒**（``images_empty``）：空文件扩展名再对也发不出去；
    - **内容守卫**（``min_bytes``/``min_side`` 任一 > 0 才启用，0 = 关 = B1 之前
      逐字节同形）：字节下限挡占位小图，文件头魔数验真挡假扩展名（HTML/文本改名
      .png 这类），像素短边下限挡缩略图/图标（PIL 只解图头、惰性 import）。
      魔数对上却解不开的按坏件记 ``images_bad_magic``；图头都读不到的记
      ``images_stat_failed``——**不知道 ≠ 它没有**，不折成拒绝。
    """
    found: list[Path] = []
    missing = not root.exists()
    not_directory = False
    unreadable = 0
    walked_files = 0
    seen = over_limit = stat_failed = 0
    empty = below_min_bytes = bad_magic = below_min_side = 0
    pruned_links = reparse_rejected = 0
    guard_enabled = min_bytes > 0 or min_side > 0
    if not missing:
        if not root.is_dir():
            not_directory = True
        else:

            def _note_walk_error(_error: OSError) -> None:
                nonlocal unreadable
                unreadable += 1

            for current, dirs, files in os.walk(root, onerror=_note_walk_error):
                # 就地改写 dirs 是 os.walk 的官方剪枝口：下一层不会再进这些子树。
                kept: list[str] = []
                for name in dirs:
                    if _should_prune_dir(name):
                        continue
                    # PIC 容器面：登记根里的重解析点（junction/符号链接）**不进树**。
                    # Windows 下 junction 的 os.path.islink 为假，照 islink 剪等于没剪，
                    # 私人相册会整摞被吸进候选（判据真身 path_gate.reparse_point）。
                    if _is_reparse_point(Path(current) / name):
                        pruned_links += 1
                        continue
                    kept.append(name)
                dirs[:] = kept
                for name in files:
                    walked_files += 1
                    path = Path(current) / name
                    if path.suffix.lower() not in _IMAGE_EXTENSIONS:
                        continue
                    seen += 1
                    try:
                        size = path.stat().st_size
                    except OSError:
                        # stat 拿不到＝不知道；既不记成「它没有」也不记成「它超限」。
                        stat_failed += 1
                        continue
                    if _is_reparse_point(path):
                        # 文件自己是链接：真身在登记面之外（或别处），一条都不发。
                        reparse_rejected += 1
                        continue
                    if size <= 0:
                        # 0 字节文件永远发不出去，扩展名再对也拦（无条件，与守卫开关无关）。
                        empty += 1
                        continue
                    if size > max_bytes:
                        over_limit += 1
                        continue
                    if guard_enabled:
                        if min_bytes > 0 and size < min_bytes:
                            below_min_bytes += 1
                            continue
                        header = image_guard.read_header(path)
                        if header is None:
                            stat_failed += 1
                            continue
                        if not image_guard.header_is_image(header):
                            bad_magic += 1
                            continue
                        if min_side > 0:
                            side = image_guard.min_side_of_file(path)
                            if side is None:
                                # 魔数对上了却解不开＝截断/损坏的坏件（诚实拒，不猜能发）。
                                bad_magic += 1
                                continue
                            if side < min_side:
                                below_min_side += 1
                                continue
                    found.append(path)
    return _ScanResult(
        tuple(found),
        GalleryFacts(
            dirs_configured=1,
            dirs_missing=1 if missing else 0,
            dirs_not_directory=1 if not_directory else 0,
            dirs_unreadable=unreadable,
            dirs_read=0 if (missing or not_directory) else 1,
            files_seen=walked_files,
            images_seen=seen,
            images_over_limit=over_limit,
            images_stat_failed=stat_failed,
            images_empty=empty,
            images_below_min_bytes=below_min_bytes,
            images_bad_magic=bad_magic,
            images_below_min_side=below_min_side,
            dirs_pruned_links=pruned_links,
            images_reparse_rejected=reparse_rejected,
            usable=len(found),
        ),
    )


def _cached_facts(cached: tuple[Any, ...]) -> GalleryFacts:
    """缓存值的容错读取（既有测试会往里塞 ``(ts, [])`` 这类 2 元组形态，不能打崩读数口）。"""
    if len(cached) > 2 and isinstance(cached[2], GalleryFacts):
        return cached[2]
    return _EMPTY_FACTS


def _merge_facts(left: GalleryFacts, right: GalleryFacts) -> GalleryFacts:
    """逐目录事实相加（``dirs_configured`` 由调用侧按配置项数统一派生）。"""
    return GalleryFacts(
        dirs_configured=max(left.dirs_configured, right.dirs_configured),
        dirs_missing=left.dirs_missing + right.dirs_missing,
        dirs_not_directory=left.dirs_not_directory + right.dirs_not_directory,
        dirs_unreadable=left.dirs_unreadable + right.dirs_unreadable,
        dirs_read=left.dirs_read + right.dirs_read,
        files_seen=left.files_seen + right.files_seen,
        images_seen=left.images_seen + right.images_seen,
        images_over_limit=left.images_over_limit + right.images_over_limit,
        images_stat_failed=left.images_stat_failed + right.images_stat_failed,
        images_empty=left.images_empty + right.images_empty,
        images_below_min_bytes=left.images_below_min_bytes + right.images_below_min_bytes,
        images_bad_magic=left.images_bad_magic + right.images_bad_magic,
        images_below_min_side=left.images_below_min_side + right.images_below_min_side,
        dirs_refused_denied=left.dirs_refused_denied + right.dirs_refused_denied,
        dirs_pruned_links=left.dirs_pruned_links + right.dirs_pruned_links,
        images_reparse_rejected=left.images_reparse_rejected + right.images_reparse_rejected,
        usable=left.usable + right.usable,
    )


def _collect_gallery(
    dirs: list[str] | tuple[str, ...],
    *,
    max_bytes: int,
    min_bytes: int = 0,
    min_side: int = 0,
    config: Any | None = None,
) -> tuple[list[Path], GalleryFacts]:
    """**唯一的池子读数口**：清单与事实出自同一次扫描、同一份缓存（绝不各扫一遍）。

    ⚠ 缓存键只有目录路径（既有口径）：同一目录在 TTL 内用**不同下限**再读，会命中
    上一次阈值扫出的清单。生产读法里阈值恒来自同一份 Config（一个进程一把尺），
    这个前提成立；测试里跨阈值复用缓存要自担（同 max_bytes 的历史注意事项一致）。

    ``config`` 只在 PIC 容器面用一次：传了才判「这条登记项是不是别人发来的图的落点」
    （:func:`gallery_root_denial`），没传＝纯 dirs 调用口，行为与本波之前逐字节同形。
    """
    now = time.monotonic()
    images: list[Path] = []
    facts = GalleryFacts()
    configured = 0
    refused = 0
    for raw in dirs:
        text = str(raw)
        if not text.strip():
            # 空白写位不当目录用：旧写法 ``Path("").cwd()`` 会把**整个工作目录**
            # 当图库扫（本仓实测 44,146 个文件、56 张图），一条手滑的空串就能让 bot
            # 从源码树里抽图发出去。跳过去，并且不记进 dirs_configured。
            continue
        root = _gallery_root(text)
        key = str(root)
        if not key:
            continue
        configured += 1
        if config is not None and gallery_root_denial(root, config):
            # 入站附件面（别人发来的图）登记成图库 ⇒ 整条不读、不进缓存、不列一张。
            refused += 1
            continue
        cached = _SCAN_CACHE.get(key)
        if cached is not None and now - cached[0] <= _SCAN_CACHE_TTL_SECONDS:
            # 审查 L-10：命中即触达，维持 LRU 新近序。
            _SCAN_CACHE.move_to_end(key)
            images.extend(cached[1])
            facts = _merge_facts(facts, _cached_facts(cached))
            continue
        # 审查 L-10：过期键读取时惰性清除（覆盖写入无法收缩字典占位，
        # 显式 pop 保证键数有界），随后走重扫路径自然回填。
        _SCAN_CACHE.pop(key, None)
        result = _scan_dir(root, max_bytes, min_bytes=min_bytes, min_side=min_side)
        _SCAN_CACHE[key] = (now, list(result.paths), result.facts)
        # 审查 L-10：键数封顶，超界淘汰最久未用键（popitem(last=False)）。
        while len(_SCAN_CACHE) > _SCAN_CACHE_LRU_CAP:
            _SCAN_CACHE.popitem(last=False)
        images.extend(result.paths)
        facts = _merge_facts(facts, result.facts)
    return images, replace(
        facts, dirs_configured=configured, dirs_refused_denied=refused
    )


def list_gallery_images(
    dirs: list[str] | tuple[str, ...],
    *,
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    config: Any | None = None,
) -> list[Path]:
    """汇总所有配置目录下的图片（带 30s TTL 缓存；目录不存在 → 忽略）。

    返回形状与旧实现一致（``list[Path]``，同一目录被写两遍时仍会出现重复路径）；
    想知道「为什么是空的」走 ``gallery_facts``（同一份缓存，不多扫一遍）。
    ``min_bytes``/``min_side`` 是 B1 内容守卫下限，0 = 关（旧行为逐字节同形）。
    ``config`` 是 PIC 容器面的入站附件面判定（见 :func:`gallery_root_denial`）。
    """
    images, _facts = _collect_gallery(
        dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
    )
    return images


def gallery_facts(
    dirs: list[str] | tuple[str, ...],
    *,
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    config: Any | None = None,
) -> GalleryFacts:
    """池子读数（观察事实版）：与 ``list_gallery_images`` 共用同一次扫描与同一份缓存。"""
    _images, facts = _collect_gallery(
        dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
    )
    return facts


def _drop_from_cached_listing(path: Path) -> None:
    """把一条**已经不在原位**的路径从 TTL 清单里摘掉（用户整理图库是真会发生的）。

    清单有 30 秒 TTL：期间被删/被移走的文件仍留在缓存里，不摘就会在 TTL 内被反复
    挑中（每次都撞同一堵墙）。⚠ **观察事实那格刻意原样留着**：摘掉一条路径不等于
    重扫了整个目录，把 ``usable`` 就地减一反而会让 verdict 从「有货」滑成
    「超限/读不出」那类我们没证据的说法。事实过期 ⇒ 措辞走 ``pool_vanished`` 那一档
    （「刚扫到的那批已经不在了」），它说的正是我们真正知道的事。
    """
    key = str(path.parent)
    for cache_key, cached in list(_SCAN_CACHE.items()):
        if not (key == cache_key or key.startswith(cache_key + os.sep)):
            continue
        listing = cached[1]
        if path not in listing:
            continue
        remaining = [item for item in listing if item != path]
        _SCAN_CACHE[cache_key] = (cached[0], remaining, _cached_facts(cached))
        return


def _pick_alive(
    images: Sequence[Path], *, chooser: Callable[[Sequence[Path]], Path]
) -> tuple[Path | None, int]:
    """抽签 + **就地验活**：挑中的那张必须此刻还在，才交给出站链。

    为什么必须在**这一层**拦：TTL 清单有 30 秒滞后，期间被移走的文件仍在册；
    ``domains/transport/sender/onebot.py`` 的 image 面闸到 2026-09-28 B1 波才装上
    （此前 M-38 收编只给 record/video/file 三面加闸，image 面留白＝report-T100
    已登记偏差，本波闭合），两闸各防一侧：这里防死引用被挑中，出站闸防上游任何
    能力把死路径直接塞进部件。

    返回 ``(挑中的路径或 None, 尝试次数)``。上限 = 清单长度，但逐条摘除死引用，
    所以最坏情况是把这份 TTL 清单走空（之后自然按「图库空」同一口径降级）。
    """
    remaining = list(images)
    attempts = 0
    while remaining:
        attempts += 1
        candidate = chooser(remaining)
        if _file_size(candidate) is not None:
            return candidate, attempts
        _drop_from_cached_listing(candidate)
        remaining = [item for item in remaining if item != candidate]
    return None, attempts


def pick_random_image(
    dirs: list[str] | tuple[str, ...],
    *,
    rng: random.Random | None = None,
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    config: Any | None = None,
) -> Path | None:
    images = list_gallery_images(
        dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
    )
    if not images:
        return None
    picker = (rng or random).choice
    picked, _attempts = _pick_alive(images, chooser=lambda pool: picker(pool))
    return picked


# ------------------------------------------------------------------ 图片内容身份
#
# 「同一张图」的唯一判据=**文件字节 SHA-256 前 16 位**，不是路径：用户整理图库
# 时改名/换目录是常态，按路径记账等于把「窗内不重发」清零（ITEM 15(b) 裁定）。
# 摘要按 (路径, mtime_ns, size) 记忆化——图库几百张时不会每次派发都重读全量字节，
# 文件被改动（mtime/size 变）自然失效重算。读不到字节时**退化成路径身份**
# 并照发：宁可少记一次账，也不因为一次 stat/read 失败把整条发图腿打死。

_IDENTITY_CACHE_CAP = 1024
_IDENTITY_PREFIX_LEN = 16
_IDENTITY_CACHE: OrderedDict[str, tuple[int, int, str]] = OrderedDict()


def image_identity(path: str | Path) -> str:
    """图片身份串：内容 SHA-256[:16]；读不出内容时退化为路径（不抛异常）。

    **摘要算法不在本件里**：全仓「媒体字节 → 内容摘要」的唯一真身是
    ``domains/media/digest.py::media_digest_file``（蓝图 §3.1 钉死「单一入口」，
    截短是消费侧决定 ⇒ 这里只截 ``[:16]``）。本件曾自己 ``open(...)+hashlib.sha256``
    流式手抄一遍——同一条规则的第二实现，正是本仓「禁第二真身」点名的形态；
    现在只保留**记忆化**这一件本件特有的事。
    """
    key = str(path)
    try:
        info = os.stat(key)
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        return key
    cached = _IDENTITY_CACHE.get(key)
    if cached is not None and cached[0] == stamp[0] and cached[1] == stamp[1]:
        _IDENTITY_CACHE.move_to_end(key)
        return cached[2]
    from plugins.bot_unified_runtime.domains.media.digest import media_digest_file

    digest = media_digest_file(key)
    if digest is None:
        # 读不到字节：退化成路径身份（宁可少记一次账，也不因一次 IO 失败打死发图腿）。
        return key
    identity = digest[:_IDENTITY_PREFIX_LEN]
    _IDENTITY_CACHE[key] = (stamp[0], stamp[1], identity)
    _IDENTITY_CACHE.move_to_end(key)
    while len(_IDENTITY_CACHE) > _IDENTITY_CACHE_CAP:
        _IDENTITY_CACHE.popitem(last=False)
    return identity


# ------------------------------------------------------------------ 不重复窗口
#
# 「窗内不重发同一张」这件事在本仓已有两处先例（reaction 环形缓冲 / 到点吃
# 什么 7 天历史），但都不在图库这一层，故此处按同一形状落一份**图库专用**的
# 窗口：每会话一条有界环形 + 时间戳，超窗即惰性过期，键数封顶防长跑泄漏。
# 记账的键=``image_identity``（内容摘要），不是路径。
# 同一目的的另一本账在表情侧（``domains/meme/`` 下的贴纸防重史，另一席在建）：
# 两本账形状相同、键域不同（图片内容摘要），后续应合并为一枚中央件——
# 合并只换这里的 store 实现，本件调用面不变（详见本轮 NEEDS-MAIN）。


# 群桶键归一（S-FIX-ATK-DIVRNG 票②）：被戳臂旧写法用 ``group_{G}_{U}`` 记「窗内
# 不重发」账，指令/自动后腿用 ``group_{G}``（``event.get_session_id()`` 的群键不含
# 发送者）。同群同图因此分裂成两本账，窗内不重发与并发防双发在群内互相看不见。
# 本函数把「带发送者后缀」的群账键收敛回群键，使窗账形状单源。root 装配文件的 poke
# 臂应同时在 caller 侧改传 ``group_{G}``（见报告 §待主代理落盘）；此处是账本入口的
# 兜底收口——两侧无论哪边先落，群内记的都是同一本账。
_GROUP_SENDER_SUFFIX = re.compile(r"^(group_\d+)_\d+$")


def canonical_bucket_key(session_key: str) -> str:
    """把 ``group_{G}_{U}`` 收敛为 ``group_{G}``；其余账键原样返回。

    只改写「群键 + 发送者数字后缀」这一形状。``private_{U}``、裸 ``group_{G}``、
    空串与其它任何键都原样透传——私聊会话键本身就带用户、语义上不可并桶。
    """
    raw = str(session_key or "")
    match = _GROUP_SENDER_SUFFIX.match(raw)
    return match.group(1) if match else raw


class RecentImageWindow:
    """按会话记「最近发过的图片身份」的有界窗口（时间窗 + LRU 双上限）。

    记账与占坑裁决（``record``/``try_claim``）在这里，「发不发、发哪张」的
    决策在 ``pick_fresh_image``。会话键数封顶
    ``_SESSION_CAP``、每会话窗内条目封顶 ``_PER_SESSION_CAP``（图库只有几张
    时不至于把内存吃穿），超出即淘汰最旧。

    S-T-RANDPIC-1 给每条账另存一枚**可选的文件大小**（``record(size=…)``）：
    「这张是不是窗内那张」原本只能靠读全库字节回答，而**内容相同 ⇒ 大小必然相同**
    ⇒ 大小是摘要的下界超集过滤器。它只是省 IO 的加速道，**不是判据**：任何一条账
    没带大小（旧记录、外部直接 ``record`` 的测试、stat 失败）都会退回「照常读字节」，
    所以这条道放宽不了也不收紧「同图不重发」的语义。
    """

    _SESSION_CAP = 2048
    _PER_SESSION_CAP = 512

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        # 三元组：(发放时刻, 字节大小或 None, 上次那条路径的提示串)。第三枚是 P15
        # 「最久没发」加速道补的，注解若仍写两枚，mypy 会把下面所有 ``entry[2]``
        # 判成 Tuple index out of range——静态红会把整棵树的 typecheck 门打住。
        self._recent: OrderedDict[str, OrderedDict[str, tuple[float, int | None, str]]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def record(
        self,
        session_key: str,
        identity: str | Path,
        *,
        window_seconds: float,
        now: float | None = None,
        size: int | None = None,
        path: str | Path | None = None,
    ) -> None:
        key = canonical_bucket_key(session_key)
        value = str(identity or "").strip()
        if not key or not value:
            return
        current = self.clock() if now is None else float(now)
        hint = str(path).strip() if path is not None else ""
        with self._lock:
            bucket = self._recent.get(key)
            if bucket is None:
                bucket = OrderedDict()
                self._recent[key] = bucket
            self._recent.move_to_end(key)
            bucket[value] = (current, size, hint)
            bucket.move_to_end(value)
            self._prune(bucket, window_seconds=window_seconds, now=current)
            while len(self._recent) > self._SESSION_CAP:
                self._recent.popitem(last=False)

    def try_claim(
        self,
        session_key: str,
        identity: str | Path,
        *,
        window_seconds: float,
        now: float | None = None,
        size: int | None = None,
        path: str | Path | None = None,
    ) -> bool:
        """``record`` 的原子占坑版：这张若已在窗内被占（含并发对手），返回 False 且不动账。

        补的是「快照→记档」之间的竞态窗：回复后腿、被戳 randpic 臂、指令腿全在
        线程池里跑（根装配文件的 ``asyncio.to_thread`` / RuntimePipeline 的
        offload 线程），``pick_fresh_outcome`` 先读窗账快照再无条件 ``record``，
        两个线程同时盯上同一张最新鲜候选时**各自都判它新鲜、各发一次**——
        ITEM 15(b)「同一张图不得重复发」在并发下就只剩一半。「查 + 插」收进
        同一把 ``self._lock``，同一时刻只有一边拿到 True，另一边必须让开继续探查。
        与表情侧 ``MemeSendHistoryStore.try_claim`` 同哲学同语义（两族各一本账，
        形状一致、键域不同；合并成中央件在案待裁，见本文件上方注释）。

        口径与 ``recent_keys`` 的惰性过期一致：窗满超期的旧行算**可占**（覆写并
        返回 True）；空会话键 / 空身份返回 False——判据拿不准时 fail-closed 到
        「不发」，宁可不发也不发一张记不进账的图（那等于给重复开门）。
        """
        key = canonical_bucket_key(session_key)
        value = str(identity or "").strip()
        if not key or not value:
            return False
        current = self.clock() if now is None else float(now)
        hint = str(path).strip() if path is not None else ""
        with self._lock:
            bucket = self._recent.get(key)
            if bucket is None:
                bucket = OrderedDict()
                self._recent[key] = bucket
            self._recent.move_to_end(key)
            entry = bucket.get(value)
            if entry is not None and not (
                window_seconds > 0 and current - entry[0] > window_seconds
            ):
                return False
            bucket[value] = (current, size, hint)
            bucket.move_to_end(value)
            self._prune(bucket, window_seconds=window_seconds, now=current)
            while len(self._recent) > self._SESSION_CAP:
                self._recent.popitem(last=False)
        return True

    def recent_keys(
        self,
        session_key: str,
        *,
        window_seconds: float,
        now: float | None = None,
    ) -> frozenset[str]:
        """本会话窗内已发过的身份集合（惰性过期后取，全空即空集）。

        存的东西对窗口是** opaque 的身份串**——是路径还是内容摘要由调用方决定。
        P14 之后调用方交的是 ``image_identity``（内容 SHA-256），因为文件名一
        改、图还在，路径身份等于没记过账。
        """
        current = self.clock() if now is None else float(now)
        with self._lock:
            bucket = self._recent.get(canonical_bucket_key(session_key))
            if not bucket:
                return frozenset()
            self._prune(bucket, window_seconds=window_seconds, now=current)
            return frozenset(bucket)

    def recent_sizes(
        self,
        session_key: str,
        *,
        window_seconds: float,
        now: float | None = None,
    ) -> tuple[frozenset[int], bool]:
        """窗内账目的 ``(已知大小集合, 是否存在未知大小的账)``（超集过滤器用）。

        第二腿为真时调用方**必须**照旧读字节——「有一条不知道大小」就等于「筛不掉任何
        候选」，这时候省 IO 会省成漏放同图。
        """
        current = self.clock() if now is None else float(now)
        with self._lock:
            bucket = self._recent.get(canonical_bucket_key(session_key))
            if not bucket:
                return frozenset(), False
            self._prune(bucket, window_seconds=window_seconds, now=current)
            sizes: set[int] = set()
            unknown = False
            for entry in bucket.values():
                size = entry[1]
                if size is None:
                    unknown = True
                else:
                    sizes.add(int(size))
            return frozenset(sizes), unknown

    def path_hint_for(
        self, session_key: str, identity: str, *, window_seconds: float,
        now: float | None = None,
    ) -> str:
        """这条身份上次是从**哪条路径**发出去的（只作加速道，判据仍是摘要）。

        库大到探查上限时，「最久没发」不能靠重扫全库来找（那正是要省掉的 IO）；
        账本顺手记过路径，就 O(1) 拿回来。拿到后调用方仍会用摘要复核一次。
        """
        current = self.clock() if now is None else float(now)
        with self._lock:
            bucket = self._recent.get(canonical_bucket_key(session_key))
            if not bucket:
                return ""
            self._prune(bucket, window_seconds=window_seconds, now=current)
            entry = bucket.get(str(identity or "").strip())
            if entry is None:
                return ""
            return str(entry[2] or "")

    def newest_path(
        self, session_key: str, *, window_seconds: float, now: float | None = None
    ) -> str:
        """窗内**最近**发过的那张当时的路径（终极兜底时用它避开连续重复）。"""
        current = self.clock() if now is None else float(now)
        with self._lock:
            bucket = self._recent.get(canonical_bucket_key(session_key))
            if not bucket:
                return ""
            self._prune(bucket, window_seconds=window_seconds, now=current)
            for name in reversed(list(bucket)):
                return str(bucket[name][2] or "")
        return ""

    def least_recent_key(
        self, session_key: str, *, window_seconds: float, now: float | None = None
    ) -> str:
        """窗内「最久没发」那一枚身份（窗账按插入序排，故首个即最旧）。

        只给指令路兜底用：整库都在窗内时总得发一张，发谁有依据（最久没发）
        比凭 seed 任取一张更诚实——本件 docstring 一直写的是「退最久没发」，
        旧实现却按摘要取模任取，这次把两者对齐。
        """
        current = self.clock() if now is None else float(now)
        with self._lock:
            bucket = self._recent.get(canonical_bucket_key(session_key))
            if not bucket:
                return ""
            self._prune(bucket, window_seconds=window_seconds, now=current)
            for name in bucket:
                return str(name)
        return ""

    def _prune(
        self,
        bucket: OrderedDict[str, tuple[float, int | None, str]],
        *,
        window_seconds: float,
        now: float,
    ) -> None:
        if window_seconds > 0:
            for name in [k for k, entry in bucket.items() if now - entry[0] > window_seconds]:
                bucket.pop(name, None)
        while len(bucket) > self._PER_SESSION_CAP:
            bucket.popitem(last=False)

    def clear(self) -> None:  # 测试复位用（与既有环形缓冲同口径）
        with self._lock:
            self._recent.clear()


_DEFAULT_RECENT_WINDOW = RecentImageWindow()


def pool_is_exhausted(
    *, pool_identities: Sequence[str], recent: frozenset[str]
) -> bool:
    """「整库都在窗内」的**纯谓词**（判据＝池子身份全集 ⊆ 窗账）。

    为什么不就地用 ``all(item in recent ...)`` 手写第二遍：这句是「池子被发完了」
    这件事在本件里的唯一定义，主动腿要据此诚实地「不发并说明原因」，指令腿要据此
    退「最久没发」。写成两处就会漂成一处真一处假。
    """
    if not pool_identities:
        return False
    return all(identity in recent for identity in pool_identities)


def deterministic_choice(items: Sequence[Path], seed: str) -> Path:
    """确定性取一张：SHA-256 摘要取模（与 gate/tts/poke 三处同一族做法）。

    主动发图那条腿要「可复现、可审计、测试不 flaky」，所以不跟 ``random``。
    """
    digest = int(hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:8], 16)
    return items[digest % len(items)]


def _probe_rank(seed: str, path: Path) -> str:
    """把 (seed, 路径) 折成一个可排序的短串 ⇒ 一次「按 seed 打散」的**探查顺序**。

    只哈希路径字符串，零文件 IO —— 这条是探查顺序的地基，别顺手改成读字节。
    """
    return hashlib.sha256(f"{seed}|{path}".encode()).hexdigest()


def _probe_order(
    images: Sequence[Path], seed: str, *, rng: random.Random | None = None
) -> list[Path]:
    """探查顺序：带 seed ⇒ 确定性打散（同 seed 同序，可复现可审计）；无 seed ⇒ 洗牌。"""
    if seed:
        return sorted(images, key=lambda item: _probe_rank(seed, item))
    ordered = list(images)
    (rng or random).shuffle(ordered)
    return ordered


def _file_size(path: Path) -> int | None:
    """常规文件的大小；读不到 / 不是常规文件 ⇒ ``None``（＝不知道，绝不猜）。"""
    try:
        info = os.stat(str(path))
    except OSError:
        return None
    if not _stat.S_ISREG(info.st_mode):
        return None
    return int(info.st_size)


@dataclass(frozen=True)
class PickOutcome:
    """一次取图的**结论 + 依据**（旧实现只回 ``Path|None``，「为什么没发」全丢在半路）。"""

    path: Path | None = None
    #: 取值：``picked`` / ``recycled_least_recent`` / ``recycled_unproven`` /
    #: ``held_pool_exhausted`` / ``held_pool_unproven`` / ``pool_vanished`` /
    #: ``gallery_<verdict>``（verdict 见 ``GalleryFacts``）。
    reason: str = "picked"
    #: 本次真读了多少张文件的字节（省 IO 那条腿的自证口径；0＝一次都没读）。
    reads: int = 0
    #: 本次 stat 过几个候选（含被就地摘掉的死引用）。
    probes: int = 0
    facts: GalleryFacts = _EMPTY_FACTS

    @property
    def sent(self) -> bool:
        return self.path is not None


def _gallery_reason(facts: GalleryFacts) -> str:
    return f"gallery_{facts.verdict}"


def pick_fresh_image(
    dirs: list[str] | tuple[str, ...],
    *,
    session_key: str,
    window: RecentImageWindow | None = None,
    window_seconds: float,
    seed: str = "",
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    allow_exhausted: bool = True,
    rng: random.Random | None = None,
) -> Path | None:
    """按「窗内不重发」挑一张；挑不出按 ``allow_exhausted`` 决定回退还是作罢。

    - ``allow_exhausted=True``（指令路）：整库都在窗内时退「最久没发」那张——
      用户开口要图，绝不因防重复而拒不发。
    - ``allow_exhausted=False``（主动发图路）：整库都在窗内=本轮不发（主动动作
      宁可不发也不刷屏）。
    取图即占坑（S-RANDPIC-2，2026-09-26）：新鲜候选在探查循环里就走
    ``RecentImageWindow.try_claim`` 原子记账，返回非 None 即代表这张图归这次调用
    且窗账已同步落账——并发两腿盯上同一张时只有一边拿得到，输的那边继续探查、
    绝不重发（旧写法「快照→挑→无条件 record」在回复后腿与被戳臂同线程池并发时
    会各发一次同一张）。整库都在窗内时的回收路（指令腿）仍走无条件 ``record``：
    那是**刻意复发**，账与审计代号都写明 recycled。

    S-T-RANDPIC-1 把「读全库字节」换成「按大小做超集预筛 + 惰性探查」：语义逐条不变
    （同图判据仍是内容 SHA-256，``tests/test_poke_randpic_behavior.py`` C 组原样在跑），
    代价从「每次发图先扫完 90 GB」压成「每次只读中的那一张」。旧写法实测：现网图库
    23,353 张 / 89,982 MB ⇒ 整库摘要一趟 ≈127s，而记忆化上限 1024 远小于库容量 ⇒
    **每一次**取图都要重读近乎全库。原因代号见 ``PickOutcome``——旧实现整库都在窗内时
    是**静默**退「最久没发」，用户与审计都不知道那是同一张图的第二次。
    """
    return pick_fresh_outcome(
        dirs,
        session_key=session_key,
        window=window,
        window_seconds=window_seconds,
        seed=seed,
        max_bytes=max_bytes,
        min_bytes=min_bytes,
        min_side=min_side,
        allow_exhausted=allow_exhausted,
        rng=rng,
    ).path


def pick_fresh_outcome(
    dirs: list[str] | tuple[str, ...],
    *,
    session_key: str,
    window: RecentImageWindow | None = None,
    window_seconds: float,
    seed: str = "",
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    allow_exhausted: bool = True,
    rng: random.Random | None = None,
    config: Any | None = None,
) -> PickOutcome:
    """``pick_fresh_image`` 的带依据版；取图口只有这一条，上面那枚是它的投影。"""
    store = window if window is not None else _DEFAULT_RECENT_WINDOW
    images, facts = _collect_gallery(
        dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
    )
    # 同一个目录被写两遍 ⇒ 同一张图进候选两次：先按路径去重，别让它占两次概率。
    pool: list[Path] = list(dict.fromkeys(images))
    if not pool:
        return PickOutcome(None, _gallery_reason(facts), facts=facts)

    recent = store.recent_keys(session_key, window_seconds=window_seconds)
    known_sizes, sizes_unknown = store.recent_sizes(
        session_key, window_seconds=window_seconds
    )
    state = {"reads": 0, "probes": 0}
    identities: dict[Path, str] = {}

    def _identity_of(item: Path) -> str:
        cached = identities.get(item)
        if cached is not None:
            return cached
        state["reads"] += 1
        value = image_identity(item)
        identities[item] = value
        return value

    ceiling = min(len(pool), _FRESH_PROBE_CEILING)
    scanned = 0
    alive_seen = False
    identified: list[str] = []  # 本轮**真读过字节并确认在窗内**的那些张的身份
    for item in _probe_order(pool, seed, rng=rng):
        if scanned >= ceiling:
            break
        scanned += 1
        state["probes"] += 1
        size = _file_size(item)
        if size is None:
            # 读不到大小＝这张已不在原位（被删/被改名/换成目录了）：就地从 TTL
            # 清单里摘掉，别让它在下一次探查里再占一个坑。
            _drop_from_cached_listing(item)
            continue
        alive_seen = True
        if recent and (sizes_unknown or size in known_sizes):
            # 大小筛不掉 ⇒ 读字节、按摘要（唯一判据）复核。
            identity = _identity_of(item)
            if identity in recent:
                identified.append(identity)
                continue
        else:
            # 窗账为空、或大小与窗内任一张都不同 ⇒ 「多半新鲜」；摘要照算一枚用来
            # 占坑——try_claim 才是终判：并发对手若已抢先把这张记进窗账，这一占
            # 返回 False，本腿让开继续探查，绝不「反正筛过了就照发」。
            identity = _identity_of(item)
        if store.try_claim(
            session_key, identity, window_seconds=window_seconds, size=size, path=item
        ):
            return PickOutcome(
                item, "picked", reads=state["reads"], probes=state["probes"], facts=facts
            )
        # 坑被抢：这张在「快照→占坑」窗口里被另一条腿占走并发出去了。回填进本地
        # 判据再继续探查——**不许照发**（照发＝同一张的第二次）。
        recent = recent | {identity}
        identified.append(identity)
        if not sizes_unknown:
            known_sizes = known_sizes | {size}
    exhausted_proven = scanned >= len(pool) and pool_is_exhausted(
        pool_identities=identified, recent=recent
    )

    if alive_seen is False and scanned >= len(pool):
        # 清单整份失效（用户把图库搬空了）：按「图库空」同一口径诚实降级。
        return PickOutcome(
            None, "pool_vanished", reads=state["reads"], probes=state["probes"], facts=facts
        )

    if not allow_exhausted:
        # 主动腿：宁可不发。但「整库确实发完了」与「没翻完所以不知道」是两件事。
        return PickOutcome(
            None,
            "held_pool_exhausted" if exhausted_proven else "held_pool_unproven",
            reads=state["reads"],
            probes=state["probes"],
            facts=facts,
        )

    # 指令路：退「最久没发」那张——**明确记成 recycled**，不冒充第一次发。
    fallback_identity = store.least_recent_key(
        session_key, window_seconds=window_seconds
    )
    recycled: Path | None = None
    if fallback_identity:
        recycled = _resolve_identity_path(
            store,
            session_key=session_key,
            identity=fallback_identity,
            pool=pool,
            identities=identities,
            window_seconds=window_seconds,
            read_identity=_identity_of,
            ceiling=ceiling,
            state=state,
            rng=rng,
        )
    if recycled is None:
        # 账本为空 / 身份怎么都对不上（图被改名后重扫、窗口刚过期等）：退全库挑一张还在的，
        # 不至于拒不发——但**绝不退到刚发过那一张**（连续重复正是 ITEM 15(b) 的字面禁令）。
        newest_path = store.newest_path(session_key, window_seconds=window_seconds)
        alive = [
            item for item in _probe_order(pool, seed, rng=rng)
            if _file_size(item) is not None
        ]
        if not alive:
            return PickOutcome(
                None, "pool_vanished", reads=state["reads"], probes=state["probes"], facts=facts
            )
        recycled = next(
            (item for item in alive if str(item) != newest_path),
            alive[0],  # 库里只剩刚发过的那张：照发（用户开口要图），但代号会记 recycled_unproven
        )
    store.record(
        session_key,
        _identity_of(recycled),
        window_seconds=window_seconds,
        size=_file_size(recycled),
        path=recycled,
    )
    return PickOutcome(
        recycled,
        "recycled_least_recent" if exhausted_proven else "recycled_unproven",
        reads=state["reads"],
        probes=state["probes"],
        facts=facts,
    )


def _resolve_identity_path(
    store: RecentImageWindow,
    *,
    session_key: str,
    identity: str,
    pool: Sequence[Path],
    identities: dict[Path, str],
    window_seconds: float,
    read_identity: Callable[[Path], str],
    ceiling: int,
    state: dict[str, int],
    rng: random.Random | None = None,
) -> Path | None:
    """把「最久没发」那枚**身份**还原成一条此刻还在的路径。

    三级次序按代价排：①本轮已经算过的身份表（零 IO）→ ②窗账里的路径提示
    （零 IO 命中，但仍要用摘要**验一次**才敢认，改名/被替换的文件不能靠提示蒙过去）
    → ③按剩余预算扫库找摘要。**摘要永远是唯一判据**，路径提示只是省 IO 的加速道。
    """
    for item, value in identities.items():
        if value == identity:
            return item
    hint = store.path_hint_for(session_key, identity, window_seconds=window_seconds)
    if hint:
        hinted = next((item for item in pool if str(item) == hint), None)
        if hinted is not None and _file_size(hinted) is not None:
            state["probes"] += 1
            if read_identity(hinted) == identity:
                return hinted
    for item in _probe_order(pool, f"least-recent|{identity}", rng=rng):
        if item in identities:
            continue  # 第①级已经查过一遍，别白走
        if state["reads"] >= ceiling:
            break
        state["probes"] += 1
        if _file_size(item) is None:
            _drop_from_cached_listing(item)
            continue
        if read_identity(item) == identity:
            return item
    return None


def no_repeat_window_seconds(config: Any) -> float:
    """不重复窗（秒）：读 ``bot_randpic_no_repeat_window_seconds``，≤0=关。

    关态整条不重复逻辑不参与（指令路与旧实现逐字节同形），所以「新行为
    缺省不发生」这条在这件里是可证的，不是叙述。
    """
    try:
        return max(0.0, float(getattr(config, "bot_randpic_no_repeat_window_seconds", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def configured_gallery_dirs(config: Any) -> list[str]:
    """配置里的图库目录（唯一读点；能力层与取图口都从这里取，不各抄一遍）。

    空白写位在这里就剔掉：留着会把 ``Path('')`` 指到进程工作目录，等于让 bot
    从源码树里抽图发出去（本仓实测那条路能扫到 44,146 个文件）。
    """
    return [
        str(item)
        for item in (getattr(config, "bot_randpic_dirs", []) or [])
        if str(item).strip()
    ]


#: 入站附件落点（别人发来的图存哪儿）：这些目录**永不得**当随机图图库登记项。
#: 用户明令「不得把别人发的图转给第三者」——把附件落点登记成图库，等于开一条
#: 跨会话搬运的通路（A 群发的图被抽出来发到 B 群），所以这一格在**读之前**就拒，
#: 不等清单、不等出站闸。键名以 ``config.py`` 那几个字段为真身，本件不抄路径值。
_GALLERY_DENIED_CONFIG_KEYS: tuple[str, ...] = (
    "bot_download_dir",
    "bot_media_archive_dir",
    "bot_meme_library_dir",
)


def gallery_root_denial(root: Path, config: Any) -> str:
    """这条登记根是不是入站附件面（含它自己）？是 ⇒ 拒因代号，否 ⇒ 空串。"""
    for key in _GALLERY_DENIED_CONFIG_KEYS:
        raw = str(getattr(config, key, "") or "").strip()
        if not raw:
            continue
        blocked = _gallery_root(raw)
        try:
            # ``allow_root=True``：登记项**就是**那处落点本身时同样要拦（等号不算越界）。
            path_gate.contain_within(root, [blocked], allow_root=True)
        except path_gate.PathEscapeError:
            continue
        return "inbound_attachment_store"
    return ""


def registered_gallery_roots(config: Any) -> list[Path]:
    """登记且**允许读**的图库根（折算后的真身，junction 折平）。

    判据只在此处派生一次：禁目录、空白写位都进不了这个列表，所以
    :func:`read_is_registered` 与池子扫描看的永远是同一份来源。
    """
    roots: list[Path] = []
    for raw in configured_gallery_dirs(config):
        if gallery_root_denial(_gallery_root(raw), config):
            continue
        for item in path_gate.resolve_roots([_gallery_root(raw)]):
            if item not in roots:
                roots.append(item)
    return roots


def read_is_registered(path: str | Path | None, config: Any) -> bool:
    """「这张图在登记面之内吗」——任何读图请求出口都过这一问（用户明令新增的那条锁）。

    目录本身回否（那是容器、不是可发的图）；空值、登记面之外、被禁目录之下统统回否。
    判据真身在 ``domains/media/path_gate.py``，本件不持第二把尺。
    """
    if path is None:
        return False
    text = str(path).strip()
    if not text:
        return False
    try:
        path_gate.contain_within(text, registered_gallery_roots(config))
    except path_gate.PathEscapeError:
        return False
    return True


def pick_gallery_image_outcome(
    config: Any,
    *,
    session_key: str,
    seed: str = "",
    allow_exhausted: bool = True,
) -> PickOutcome:
    """**唯一的取图口**（带依据版）：指令路与两条主动路都走这里。

    窗关（缺省）时退化成旧的 ``pick_random_image`` 一步，不引入任何新排序；
    窗开时按会话排除窗内已发过的张。

    PIC 容器面（2026-09-29）在这一处收口两格：① 读数带 ``config``，入站附件面的
    登记项整条不读；② 交路径前问一次 :func:`read_is_registered`——TTL 清单里混进
    登记面之外的路径（旧口径残留、缓存被别处塞）时**必须 hold**，代号
    ``out_of_registered_root``，并把那条死引用从清单里摘掉，绝不交给出站链。
    """
    dirs = configured_gallery_dirs(config)
    max_bytes = _max_bytes_for(config)
    min_bytes = _min_bytes_for(config)
    min_side = _min_side_for(config)
    window_seconds = no_repeat_window_seconds(config)
    if window_seconds <= 0:
        picked = pick_random_image(
            dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
        )
        if picked is not None:
            return _contain_outcome(
                PickOutcome(picked, "picked"), config
            )
        facts = gallery_facts(
            dirs, max_bytes=max_bytes, min_bytes=min_bytes, min_side=min_side, config=config
        )
        reason = _gallery_reason(facts)
        if reason == "gallery_usable":
            # 清单有货却一张都没挑中＝挑到的都被移走了（旧纯随机路只查被抽中的那张）。
            reason = "pool_vanished"
        return PickOutcome(None, reason, facts=facts)
    outcome = pick_fresh_outcome(
        dirs,
        session_key=session_key,
        window_seconds=window_seconds,
        seed=seed,
        max_bytes=max_bytes,
        min_bytes=min_bytes,
        min_side=min_side,
        allow_exhausted=allow_exhausted,
        config=config,
    )
    return _contain_outcome(outcome, config)


def _contain_outcome(outcome: PickOutcome, config: Any) -> PickOutcome:
    """取图口的出口门：交出去的那张必须此刻仍在登记面之内（判据唯一真身 path_gate）。"""
    picked = outcome.path
    if picked is None or read_is_registered(picked, config):
        return outcome
    _drop_from_cached_listing(picked)
    return PickOutcome(
        None,
        "out_of_registered_root",
        reads=outcome.reads,
        probes=outcome.probes,
        facts=outcome.facts,
    )


def pick_gallery_image(
    config: Any,
    *,
    session_key: str,
    seed: str = "",
    allow_exhausted: bool = True,
) -> Path | None:
    """``pick_gallery_image_outcome`` 的投影（签名与返回形状对根装配逐字节不变）。"""
    return pick_gallery_image_outcome(
        config,
        session_key=session_key,
        seed=seed,
        allow_exhausted=allow_exhausted,
    ).path


def _max_bytes_for(config: Any) -> int:
    """单张体积上限（既有键 ``bot_randpic_max_file_mb``，缺省沿用模块常量）。"""
    try:
        max_mb = int(getattr(config, "bot_randpic_max_file_mb", 0) or 0)
    except (TypeError, ValueError):
        return _MAX_FILE_BYTES
    return max_mb * 1024 * 1024 if max_mb > 0 else _MAX_FILE_BYTES


def _min_bytes_for(config: Any) -> int:
    """单张体积下限（B1 守卫键 ``bot_randpic_min_file_kb``）；≤0 或读不到 = 关。

    Config 现值以 ``config.py`` 该字段为真身（2026-09-29 用户裁定归零 ⇒ 生产关态，
    键保留作逃生口）；**读不到键**（装配期外的裸调用、旧测试的 SimpleNamespace）
    同样回 0 = 关，与 B1 之前逐字节同形。
    """
    try:
        min_kb = int(getattr(config, "bot_randpic_min_file_kb", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return min_kb * 1024 if min_kb > 0 else 0


def _min_side_for(config: Any) -> int:
    """像素短边下限（B1 守卫键 ``bot_randpic_min_side``，先例 eat.py ``_IMG_MIN_SIDE``）；≤0 或读不到 = 关。"""
    try:
        return max(0, int(getattr(config, "bot_randpic_min_side", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _pick_for_command(config: Any, message: IncomingMessage) -> Path | None:
    """指令路：窗开则按会话排重、窗关则纯随机（逐字节旧行为）。

    ⚠ seed 必须**留在本函数里写成 f-string 字面量**：
    ``tests/test_poke_randpic_behavior.py::test_randpic_command_path_passes_a_non_empty_seed``
    是按 AST 认这条形状的（把它抽成 ``command_seed(message)`` 会让那条锁当场红——
    那条锁要锁的是「seed 恒非空且带会话+消息两维」这件事写在这一处，不是写在我这处）。
    """
    return pick_gallery_image(
        config,
        session_key=str(getattr(message, "session_id", "") or ""),
        seed=f"randpic:{getattr(message, 'session_id', '')}:{getattr(message, 'message_id', '') or getattr(message, 'request_id', '')}",
        allow_exhausted=True,
    )


# ------------------------------------------------------------------ 降级话术（按事实派生）
#
# 三条硬口径，逐条有锁（``tests/test_randpic_pool_side.py``）：
# ① **没打开过的目录，绝不评论它的内容**：路径不存在/读不动 ⇒ 只说「我没能打开它」，
#    绝不说「里面没有图」（本仓「我不知道 ≠ 它没有」禁令，同 ``cd0068c``/``21bdabf``）；
# ② 真打开过才可以说内容：「一张文件都没有」/「有文件但没有能发的图片格式」/
#    「有 N 张图但都超过单张上限」三种是三种事实，各说各的；
# ③ 这句话**必须真能到用户手上**。旧实现把它写进 ``body`` 却同时标
#    ``SendPolicy.SILENT_AUDIT``，而 ``pipeline._complete`` 对 SILENT_AUDIT 的处置是
#    ``ReceiptState.SKIPPED`` + ``public_message=""`` ⇒ 文案一条都发不出去，
#    「友好降级」只存在于源码注释里（``docs/boards/.../randpic.md``「失败时看到什么」
#    那节承诺的正是用户能看见）。指令路是用户主动开口 ⇒ 一句人话回清楚。

_GALLERY_UNCONFIGURED_LINE = (
    "我还没拿到图库目录呢——把 BOT_RANDPIC_DIRS 指到你自己的图片文件夹"
    "（我只原样读取，绝不自建文件夹），之后再说一次呀。"
)

#: ``GalleryFacts.verdict`` → 措辞模板；``{sample}`` 由调用侧按实况填。
_GALLERY_DEGRADATION_LINES: dict[str, str] = {
    "missing": (
        "BOT_RANDPIC_DIRS 里那个路径我没能打开（此刻那儿没有这个文件夹）：{sample}。"
        "我看过的只有这些，里面到底有没有图我不知道。"
    ),
    "not_directory": (
        "BOT_RANDPIC_DIRS 里 {sample} 不是个文件夹（大概是指到文件上了），"
        "所以我没能从里面读到图。"
    ),
    "unreadable": (
        "BOT_RANDPIC_DIRS 里 {sample} 这个文件夹我打不开（没权限、盘没挂上、"
        "或正被占用）——看不见内容，我就不说它没有图。"
    ),
    "empty": (
        "BOT_RANDPIC_DIRS 里 {sample} 我打开看了，里面一张文件都没有；"
        "放几张图进去再叫我呀。"
    ),
    "no_image_extension": (
        "BOT_RANDPIC_DIRS 里 {sample} 我打开看了，有 {files} 个文件，"
        "但没有我能发的图片格式（jpg/jpeg/png/gif/webp/bmp）。"
    ),
    "over_limit": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {images} 张图片，可都超过单张上限 "
        "{mb} MB（BOT_RANDPIC_MAX_FILE_MB）——太大的我就不往群里甩了。"
    ),
    "stat_failed": (
        "BOT_RANDPIC_DIRS 里 {sample} 我列出了文件，但大小一个个都读不出来，"
        "就没敢往外发。"
    ),
    # ---- B1 池子守卫波（2026-09-28）新增的四种拒绝，各说各的事实 ----
    "empty_images": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {empty} 个图片扩展名的文件是 0 字节空件"
        "——空的发出去就是坏件，我跳过了。"
    ),
    "below_min_bytes": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {below_bytes} 张图低于体积下限 "
        "{min_kb} KB（BOT_RANDPIC_MIN_FILE_KB）——占位小图我就不发给你了。"
    ),
    "bad_magic": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {bad_magic} 个文件扩展名像图片，可文件头"
        "对不上 jpg/png/gif/webp/bmp 任一签名（或解不开）——假图/坏件我不往外发。"
    ),
    "below_min_side": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {below_side} 张图短边不到 {min_side} 像素"
        "（BOT_RANDPIC_MIN_SIDE）——多半是缩略图/图标，糊图我不发。"
    ),
    # ---- PIC 容器面（2026-09-29）的三种拒绝，各说各的事实与下一步 ----
    "denied_root": (
        "BOT_RANDPIC_DIRS 里 {sample} 是别人发来的图存放的地方（下载/媒体归档/表情库"
        "那一类），不是你自己的图库——我不从那儿抽图往外发，跨会话搬人家的图这条线"
        "我不碰。把你自己的图片文件夹写进 BOT_RANDPIC_DIRS，再叫我一次呀。"
    ),
    "linked_outside_root": (
        "BOT_RANDPIC_DIRS 里 {sample} 有 {links} 个文件是链接（junction/符号链接），"
        "真身落在我没被登记的地方——那种图我不发。确实要发的话，把那个文件夹本身"
        "写进 BOT_RANDPIC_DIRS（我只读登记过的这几根）。"
    ),
    "out_of_registered_root": (
        "我刚要发的那张图，路径已经不在你登记的图库里了（多半是链接、或者被人移过）——"
        "越出登记面的东西我一张都不发，顺手把这条死引用从清单里摘了。你再叫一次，"
        "或者看看那个文件夹现在长什么样。"
    ),
    "pool_vanished": (
        "我刚扫到的那批图现在一张都不在了（正被整理或移开吧）——"
        "这条腿我不发空件，你稍后再叫我一次。"
    ),
}


def gallery_degradation_line(
    facts: GalleryFacts,
    dirs: Sequence[str],
    *,
    max_bytes: int = _MAX_FILE_BYTES,
    min_bytes: int = 0,
    min_side: int = 0,
    reason: str = "",
) -> str:
    """把池子事实折成**一行**人话（认不出的事实回一句不带断言的兜底）。

    ``reason`` 是取图口的结论代号（PIC 容器面）：``out_of_registered_root`` 那一档
    「事实账说有货、出口却拦下」只在结论里看得见（我们真打开过目录、也确实有货），
    所以它取自己的措辞，不套 ``pool_vanished`` 那句。
    """
    verdict = facts.verdict
    if reason == "out_of_registered_root":
        verdict = "out_of_registered_root"
    if verdict == "unconfigured":
        return _GALLERY_UNCONFIGURED_LINE
    if verdict == "usable":
        # 清单说有货，可一张都没挑中 ⇒ 只能是「挑中时已经不在了」那一类。
        verdict = "pool_vanished"
    template = _GALLERY_DEGRADATION_LINES.get(verdict)
    if template is None:
        return (
            "这次我没能从 BOT_RANDPIC_DIRS 里发出图来（原因："
            f"{verdict}）——路径与图库还在原处，我没自作主张改它。"
        )
    sample = str(dirs[0]).strip() if dirs and str(dirs[0]).strip() else "（空配置）"
    if verdict in ("denied_root", "out_of_registered_root"):
        # 这两档谈的是登记项与链接，不是内容：不带 files/images/mb 那些我们没证据的断言。
        return template.format(
            sample=sample, links=max(facts.images_reparse_rejected, 1)
        )
    return template.format(
        sample=sample,
        files=max(facts.files_seen, 1),
        images=max(facts.images_seen, 1),
        mb=max(int(max_bytes) // (1024 * 1024), 1),
        empty=max(facts.images_empty, 1),
        below_bytes=max(facts.images_below_min_bytes, 1),
        bad_magic=max(facts.images_bad_magic, 1),
        below_side=max(facts.images_below_min_side, 1),
        links=max(facts.images_reparse_rejected, 1),
        min_kb=max(int(min_bytes) // 1024, 1) if min_bytes > 0 else 0,
        min_side=max(int(min_side), 1) if min_side > 0 else 0,
    )


#: 「打开过、确实没货」的 verdict 集（gallery_empty 这枚标签只许在这些档位出现）。
#: B1 守卫波把四种内容拒绝（empty_images/below_min_bytes/bad_magic/below_min_side）
#: 并进来：对用户而言都是「这一轮图库没有能发的图」，与旧口径兼容；路径不存在/
#: 读不动那两档**永远不进此集**（没看见内容就不许断言没有）。
_GALLERY_EMPTY_OK_VERDICTS = frozenset(
    {
        "empty",
        "no_image_extension",
        "over_limit",
        "stat_failed",
        "empty_images",
        "below_min_bytes",
        "bad_magic",
        "below_min_side",
    }
)


def gallery_audit_tags(reason: str, facts: GalleryFacts) -> list[str]:
    """降级时的审计标签：``gallery_empty`` 这枚**只**在真打开过目录且确实没货时才给。

    给错的代价很具体：``gallery_empty`` 读起来就是「图库是空的」这个断言，
    而路径不存在/读不动那两种情形我们压根没看见图库的内容。
    """
    verdict = facts.verdict
    tags = ["randpic", "gallery_unavailable", f"gallery_{verdict}", f"reason_{reason}"]
    if verdict in _GALLERY_EMPTY_OK_VERDICTS:  # 打开过、确实没货：与旧标签口径兼容
        tags.append("gallery_empty")
    return tags


def build_randpic_capability(config: Any | None = None) -> Any:
    """构建随机图片能力：与 eat 等能力一致，返回 (message, decision) -> 结果。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        dirs = configured_gallery_dirs(config)
        triggers = list(getattr(config, "bot_randpic_trigger_words", []) or [])
        if not is_randpic_command(message.plain_text or "", triggers or None):
            # 没命中触发词： matcher 抢跑/别名误路由那一类，**该静默**（旧口径不变）。
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.randpic",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["randpic", "skip_no_trigger"],
            )
        outcome = pick_gallery_image_outcome(
            config,
            session_key=str(getattr(message, "session_id", "") or ""),
            seed=f"randpic:{getattr(message, 'session_id', '')}:{getattr(message, 'message_id', '') or getattr(message, 'request_id', '')}",
            allow_exhausted=True,
        )
        picked = outcome.path
        if picked is None:
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.randpic",
                kind="text",
                title="随机图片",
                body=gallery_degradation_line(
                    outcome.facts,
                    dirs,
                    max_bytes=_max_bytes_for(config),
                    min_bytes=_min_bytes_for(config),
                    min_side=_min_side_for(config),
                    reason=outcome.reason,
                ),
                # 刻意**不再**标 SILENT_AUDIT：这句是给用户看的（见上方口径③）。
                audit_tags=gallery_audit_tags(outcome.reason, outcome.facts),
            )
        # F5（2026-09-12 实弹反馈⑤）：不标注「随机图片/随机发送」话术——
        # title 留空，否则 renderer 的 body→summary→title 兜底链会把标题
        # 当文案跟图一起发；图片本体 file:// 原字节直发，无重编码（原图）。
        tags = ["randpic", "sent", f"reason_{outcome.reason}"]
        if outcome.reason.startswith("recycled"):
            # 整库都在窗内时指令路仍照发（裁定：用户开口要图，拒不发更糟），但这一发
            # 是**同一张图的第二次**，账上必须写明，不再混在 "sent" 里冒充首发。
            tags.append("recycled_in_window")
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.randpic",
            kind="text",
            title="",
            body="",
            summary="",
            images=[{"file": str(picked)}],
            audit_tags=tags,
        )

    return capability
