"""随机图片能力（bot.randpic）：触发指令时从**用户自定义文件夹**随机发一张图。

设计（借鉴 nonebot-plugin-randpic 的"指令→随机图"玩法，MIT，仅吸收思路）：
- **只读取用户配置的目录**（BOT_RANDPIC_DIRS），绝不自建 randpic 文件夹、
  不建数据库、不做上传——那是原插件的存储层，本能力一把随机梭哈即可。
- 递归扫描目录下图片扩展名，进程内 TTL 缓存文件清单（改文件夹 30 秒内生效）。
- 目录未配置/为空/全部不可读 → 友好降级文案，绝不报错、绝不落新文件。
"""

from __future__ import annotations

import os
import random
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.core.text_boundary import is_trigger

# 拼音全拼/缩写（T-Spec T1.5/T1.6）：suijitu/laizhangtu 同覆盖繁体同音
# （隨機圖/來張圖）；sjt/lzt 查重无冲突。前缀+标点边界逻辑天然防
# suijituqq 类字母胶合（tail 首字符不在标点集即拒绝）。
DEFAULT_TRIGGER_WORDS: tuple[str, ...] = (
    "随机图", "来张图", "隨機圖", "來張圖", "randpic",
    "suijitu", "laizhangtu", "sjt", "lzt",
)
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
_SCAN_CACHE_TTL_SECONDS = 30.0
_MAX_FILE_BYTES = 20 * 1024 * 1024

# 审查 L-10：_SCAN_CACHE 原本只有 30s TTL，过期键不删、键数无上限——
# 长跑进程按目录键无界增长。对齐项目 LRU 惯例（先例：runtime/reactions.py
# 的 _REACTION_LRU_CAP 批次）：键数封顶 _SCAN_CACHE_LRU_CAP、触达即
# move_to_end、超界淘汰最久未用键；过期键在读取路径惰性清除后重扫回填。
# 扫描结果本身的语义（键→清单映射、TTL 内复用）零变化。
_SCAN_CACHE_LRU_CAP = 512
_SCAN_CACHE: OrderedDict[str, tuple[float, list[Path]]] = OrderedDict()


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


def _scan_dir(root: Path, max_bytes: int) -> list[Path]:
    found: list[Path] = []
    for current, _dirs, files in os.walk(root):
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() not in _IMAGE_EXTENSIONS:
                continue
            try:
                if path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            found.append(path)
    return found


def list_gallery_images(
    dirs: list[str] | tuple[str, ...], *, max_bytes: int = _MAX_FILE_BYTES
) -> list[Path]:
    """汇总所有配置目录下的图片（带 30s TTL 缓存；目录不存在 → 忽略）。"""
    now = time.monotonic()
    images: list[Path] = []
    for raw in dirs:
        root = Path(str(raw).strip())
        if not root.is_absolute():
            root = Path.cwd() / root
        key = str(root)
        cached = _SCAN_CACHE.get(key)
        if cached is not None and now - cached[0] <= _SCAN_CACHE_TTL_SECONDS:
            # 审查 L-10：命中即触达，维持 LRU 新近序。
            _SCAN_CACHE.move_to_end(key)
            images.extend(cached[1])
            continue
        # 审查 L-10：过期键读取时惰性清除（覆盖写入无法收缩字典占位，
        # 显式 pop 保证键数有界），随后走重扫路径自然回填。
        _SCAN_CACHE.pop(key, None)
        found = _scan_dir(root, max_bytes) if root.is_dir() else []
        _SCAN_CACHE[key] = (now, found)
        # 审查 L-10：键数封顶，超界淘汰最久未用键（popitem(last=False)）。
        while len(_SCAN_CACHE) > _SCAN_CACHE_LRU_CAP:
            _SCAN_CACHE.popitem(last=False)
        images.extend(found)
    return images


def pick_random_image(
    dirs: list[str] | tuple[str, ...],
    *,
    rng: random.Random | None = None,
    max_bytes: int = _MAX_FILE_BYTES,
) -> Path | None:
    images = list_gallery_images(dirs, max_bytes=max_bytes)
    if not images:
        return None
    return (rng or random).choice(images)


def build_randpic_capability(config: Any | None = None) -> Any:
    """构建随机图片能力：与 eat 等能力一致，返回 (message, decision) -> 结果。"""

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        dirs = [str(item) for item in (getattr(config, "bot_randpic_dirs", []) or [])]
        triggers = list(getattr(config, "bot_randpic_trigger_words", []) or [])
        if not is_randpic_command(message.plain_text or "", triggers or None):
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.randpic",
                kind="text",
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["randpic", "skip_no_trigger"],
            )
        picked = pick_random_image(dirs)
        if picked is None:
            hint = (
                "图库还是空的……请在 BOT_RANDPIC_DIRS 里配置好你自己的图片文件夹"
                "（我会原样读取，不会自己建文件夹），再叫我一次呀。"
                if not dirs
                else "图库文件夹里暂时没有能发的图片——检查一下 BOT_RANDPIC_DIRS "
                f"里的路径（当前第一个：{dirs[0]}）和图片格式？"
            )
            return CapabilityResult(
                request_id=message.request_id,
                capability_id="bot.randpic",
                kind="text",
                title="随机图片",
                body=hint,
                send_policy=SendPolicy.SILENT_AUDIT,
                audit_tags=["randpic", "gallery_empty"],
            )
        # F5（2026-09-12 实弹反馈⑤）：不标注「随机图片/随机发送」话术——
        # title 留空，否则 renderer 的 body→summary→title 兜底链会把标题
        # 当文案跟图一起发；图片本体 file:// 原字节直发，无重编码（原图）。
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.randpic",
            kind="text",
            title="",
            body="",
            images=[{"file": str(picked)}],
            audit_tags=["randpic", "sent"],
        )

    return capability
