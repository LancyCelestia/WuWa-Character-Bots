"""本地贴纸分池的**运行期扫池**腿（S-MEME-POOLSCAN，2026-09-29，需求 12）。

补的是上一波留下的两个洞（席位简报原文）：「分池目录键在 ``config.py``
零命中（未登记，提案键名只准住台账）」+「红猪包无扫池机制」。现状只有两条入库腿——① 群聊被动吸收
（``sources/meme_library_listener.absorb_event_images``）、② 离线批量导入
（``scripts/import_meme_packs.py``，要人手动跑）。管理员把一包贴纸（例如红猪包）
放进登记目录后，运行期没有任何一步会把它吸进库 ⇒ 池子中空空如也，选贴腿只会
「诚实不发」。本件补的就是这第三步。

**本件刻意零 Config 读点**（不写任何按名取 Config 键的读点）：新键登记＝配置面
改动，归主会话串行落（AGENTS 规则 7 + 席位简报的共享文件禁令），而且未登记键的
按名读点会撞 ``tests/test_config_key_registration_ledger.py`` 的「幽灵按名读点只准降
不准升」门。所以本件把目录与限额全部做成**显式入参**，读键发生在接线处，接线块原文
在席位台账「交主会话」节。

不做什么（都是硬约束，不是偷懒）：
- **不立第二套内容判据**：扩展名面取 ``domains/media/image_guard.IMAGE_EXTENSIONS``、
  真伪取 ``header_is_image``、像素下限取 ``min_side_of_bytes``，与随机图池、群聊吸收腿
  同一把尺（配对锁见 ``tests/test_image_guard_extension_parity.py``）；
- **不立第二套目录剪枝规则**：懒引 ``randpic._should_prune_dir``（缩略图/缓存目录名单的
  真身），引不到就**不剪**（不谎称剪过，也不在此另抄一份名单——缩略图那类由像素/字节
  下限两把真身闸照样拦得住）；
- **不另算权重**：入库后走 ``MemeLibraryStore.apply_tags``，权重只由 ``_score_weight``
  决定（本命 8.0 那档在 ``_PRIORITY_HINTS`` 里）；
- **不猜本命**：主体判定只走 ``shorekeeper_absorb.decide_subject`` 那唯一判据口，词表
  来自中央别名口 ``persona_alias_terms``。**没有 VLM 在场时不谎称认出来了**——包名/
  文件名命中白名单角色名才算本命（用户裁定的判据＝「VLM 标签 / 白名单角色名」），
  两处都不命中 ⇒ ``subject_undetermined`` ⇒ 照常入库但**不进本命池**，绝不把没认出来
  的图当守岸人收（红线）；
- **不放宽隔离**：准入判定复用 ``decide_intake``（墓碑优先于内容去重），被隔离过的
  内容一块都不回库。

全离线、纯判定 + 有限 IO：绝不联网、绝不碰 ``BOT_RANDPIC_DIRS`` 之外的会话媒体、
调用方没登记目录 ⇒ 报告恒为「零根、零吸收」。
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from plugins.bot_unified_runtime.domains.media import image_guard
from plugins.bot_unified_runtime.domains.media.digest import media_md5
from plugins.bot_unified_runtime.domains.meme.sources import (
    persona_review,
    shorekeeper_absorb,
)

logger = logging.getLogger(__name__)

#: 单次扫池每个根目录的最大候选数（有界扫描，与 ``meme_library._PICK_SCAN_LIMIT``
#: 同一口径：池子再大也不许把一轮扫描变成无界 IO）。
DEFAULT_LIMIT_PER_ROOT = 200
#: 单张贴纸的字节上限缺省（与 ``bot_meme_library_max_file_bytes`` 现值同量级；
#: 真实上限由调用方按 Config 传入，本常量只是「调用方没表态」时的保守兜底）。
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024

#: 拒收/跳过原因代号（进报告与日志，不进用户可见文案；逐枚都有牙锁）。
SKIP_EXT = "ext"
SKIP_EMPTY = "empty"
SKIP_TOO_LARGE = "too_large"
SKIP_TOO_SMALL = "below_min_bytes"
SKIP_BAD_MAGIC = "bad_magic"
SKIP_BELOW_MIN_SIDE = "below_min_side"
SKIP_READ_FAILED = "read_failed"
SKIP_DUPLICATE = "duplicate"
SKIP_QUARANTINED = "quarantined"
SKIP_LIMIT = "over_limit_per_root"
SKIP_OUTSIDE_ROOT = "outside_root"


def _should_prune_dir(name: str) -> bool:
    """目录剪枝：**懒引真身**，引不到就不剪并留痕（不抄第二份名单）。"""
    try:
        from plugins.bot_unified_runtime.domains.meme.capabilities import randpic

        callable_ = getattr(randpic, "_should_prune_dir", None)
        if callable(callable_):
            return bool(callable_(name))
    except Exception:  # noqa: BLE001, S110 - 能力层不可用不影响扫池，只是少了剪枝（不谎称剪过）。
        pass
    return False


def discover_pack_images(
    roots: Sequence[str | Path],
    *,
    limit_per_root: int = DEFAULT_LIMIT_PER_ROOT,
) -> tuple[list[tuple[Path, str]], dict[str, int]]:
    """登记目录 → 候选清单 ``(有序 (文件, 包名) 列表, 跳过计数)``。

    包名（scene tag）＝根目录名，用于本命判定的**文件名证据面**（只当描述句，
    不当 VLM 结论）。排序稳定：按 ``(包名, 相对路径)`` 字典序，同一批输入两次
    扫描必须给出同一串候选（可复现要求，与随机图侧的 seed 口径同构）。
    """
    collected: list[tuple[Path, str]] = []
    skipped: dict[str, int] = {}

    def _note(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for raw in roots:
        text = str(raw or "").strip()
        if not text:
            continue
        root = Path(text).expanduser()
        if not root.is_absolute():
            root = Path.cwd() / root
        try:
            root = root.resolve()
        except OSError:
            _note(SKIP_READ_FAILED)
            continue
        if not root.is_dir():
            continue
        pack = root.name
        taken = 0
        candidates: list[Path] = []
        for current, dirs, files in os.walk(root, onerror=lambda _e: None):
            dirs[:] = [name for name in dirs if not _should_prune_dir(name)]
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix.lower() not in image_guard.IMAGE_EXTENSIONS:
                    # 非图族（说明文本/视频封面/工程件）如实记一笔，不静默蒸发：
                    # 「这包为什么只吸进 3 张」要能从报告里读出来。
                    _note(SKIP_EXT)
                    continue
                candidates.append(path)
        for path in sorted(candidates, key=lambda item: str(item).lower()):
            try:
                inside = path.resolve().is_relative_to(root)
            except OSError:
                inside = False
            if not inside:
                # 链接/junction 把候选指到登记目录之外 ⇒ 不读（隐私红线：只读登记面）。
                _note(SKIP_OUTSIDE_ROOT)
                continue
            if limit_per_root > 0 and taken >= limit_per_root:
                _note(SKIP_LIMIT)
                continue
            taken += 1
            collected.append((path, pack))
    return collected, skipped


def _pack_evidence_text(path: Path, pack: str) -> str:
    """文件名证据面（喂给唯一判据口的 description 位）：包名 + 文件名主干。"""
    return f"{pack} {path.stem}".strip()


def _write_atomically(target: Path, data: bytes) -> None:
    """先写临时件再 ``os.replace``（先例 ``scripts/import_meme_packs.py`` 的原子性约束）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=str(target.parent), prefix=".pack-", suffix=target.suffix, delete=False
    ) as handle:
        handle.write(data)
        temp_name = handle.name
    try:
        os.replace(temp_name, str(target))
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def absorb_pack_image(
    path: Path,
    *,
    store: Any,
    library_dir: str | Path,
    pack: str = "",
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    min_file_bytes: int = 0,
    min_side: int = 0,
    persona_terms: Sequence[str] = (),
    ledger: Any = None,
) -> str:
    """单张贴纸的准入 ⇒ ``"accepted"`` / ``"persona_owned"`` / 各 ``SKIP_*`` 代号。

    顺序钉死：**大小 → 魔数 → 像素 → 内容哈希 → 墓碑/去重 → 落盘 → 入库 → 打标 → 本命**。
    落盘排在入库之前但用原子换名：半途崩了重跑自愈（库里没有指向空气的行）。
    """
    suffix = path.suffix.lower()
    if suffix not in image_guard.IMAGE_EXTENSIONS:
        return SKIP_EXT
    try:
        size = path.stat().st_size
    except OSError:
        return SKIP_READ_FAILED
    if size <= 0:
        return SKIP_EMPTY
    if max_file_bytes > 0 and size > max_file_bytes:
        return SKIP_TOO_LARGE
    if min_file_bytes > 0 and size < min_file_bytes:
        return SKIP_TOO_SMALL
    header = image_guard.read_header(path)
    if header is None or not image_guard.header_is_image(header):
        return SKIP_BAD_MAGIC
    if min_side > 0:
        side = image_guard.min_side_of_file(path)
        if side is None:
            # 与随机图池同口径：魔数对得上却解不开＝坏件，诚实拒，不猜「它probably能发」。
            return SKIP_BAD_MAGIC
        if side < min_side:
            return SKIP_BELOW_MIN_SIDE
    try:
        data = path.read_bytes()
    except OSError:
        return SKIP_READ_FAILED
    if not data:
        return SKIP_EMPTY
    content_sha = shorekeeper_absorb.content_sha256(data)
    md5 = media_md5(data)
    intake = shorekeeper_absorb.decide_intake(store=store, ledger=ledger, md5=md5, data=data)
    if intake.action == "quarantined":
        return SKIP_QUARANTINED
    if intake.action == "duplicate":
        return SKIP_DUPLICATE
    ext = suffix.lstrip(".")
    target = Path(str(library_dir)) / f"{md5}.{ext}"
    try:
        _write_atomically(target, data)
    except OSError:
        return SKIP_READ_FAILED
    store.add(
        md5=md5,
        path=str(target),
        ext=ext,
        group_id=f"pack:{pack}"[:64],
        content_sha256=content_sha,
    )
    evidence = _pack_evidence_text(path, pack)
    store.apply_tags(
        md5,
        is_meme=True,
        description=evidence[:60],
        scene_tags=[pack][:1] if pack else [],
        persona_hint="common",
        nsfw_score=0.0,
    )
    # 取证纪律（S-MEME2-REVIEW）：这条道上**没有 VLM 产出**，所以模型那一面一律空。
    # 包名/文件名是**管理员自己写下的名字**（登记目录是他放的、包名是他起的），
    # 按人审终裁面计（``FACE_HUMAN``），不算第二份"模型说像"——同一段文字不许既当
    # VLM 结论又当命名线索自我借光，那是双证据门的红线（判据见 persona_review）。
    admission, _evidence = persona_review.admit_evidence(
        tags={},
        terms=persona_terms,
        naming_hints=[evidence],
        human_term=shorekeeper_absorb.subject_hit(evidence, persona_terms),
    )
    if admission.persona_owned:
        store.set_review_state(md5, persona_review.ADMIT)
        store.mark_persona_owned(md5, owned=True)
        logger.info("meme pack absorb persona md5=%s term=%s", md5, admission.subject_term)
        return "persona_owned"
    logger.info("meme pack absorb md5=%s subject=%s", md5, admission.code)
    return "accepted"


def absorb_pack_dirs(
    roots: Sequence[str | Path],
    *,
    store: Any,
    library_dir: str | Path,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    min_file_bytes: int = 0,
    min_side: int = 0,
    persona_terms: Sequence[str] = (),
    ledger: Any = None,
    limit_per_root: int = DEFAULT_LIMIT_PER_ROOT,
) -> dict[str, Any]:
    """扫一批登记目录并吸收（需求 12「自动爬取吸收」的本地腿）。

    返回报告：``roots``（现算根数）/``candidates``/``accepted``/``persona_owned``/
    ``skipped``（逐代号计数）/``elapsed_ms``。**没有根目录就是零吸收**，不报错也不
    谎称「库已就绪」。
    """
    started = time.monotonic()
    candidates, scan_skips = discover_pack_images(roots, limit_per_root=limit_per_root)
    report: dict[str, Any] = {
        "roots": len([item for item in roots if str(item or "").strip()]),
        "candidates": len(candidates),
        "accepted": 0,
        "persona_owned": 0,
        "skipped": dict(scan_skips),
    }
    for path, pack in candidates:
        outcome = absorb_pack_image(
            path,
            store=store,
            library_dir=library_dir,
            pack=pack,
            max_file_bytes=max_file_bytes,
            min_file_bytes=min_file_bytes,
            min_side=min_side,
            persona_terms=persona_terms,
            ledger=ledger,
        )
        if outcome in ("accepted", "persona_owned"):
            report[outcome] += 1
        else:
            report["skipped"][outcome] = report["skipped"].get(outcome, 0) + 1
    report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return report


__all__ = [
    "DEFAULT_LIMIT_PER_ROOT",
    "DEFAULT_MAX_FILE_BYTES",
    "SKIP_BAD_MAGIC",
    "SKIP_BELOW_MIN_SIDE",
    "SKIP_DUPLICATE",
    "SKIP_EMPTY",
    "SKIP_EXT",
    "SKIP_LIMIT",
    "SKIP_OUTSIDE_ROOT",
    "SKIP_QUARANTINED",
    "SKIP_READ_FAILED",
    "SKIP_TOO_LARGE",
    "SKIP_TOO_SMALL",
    "absorb_pack_dirs",
    "absorb_pack_image",
    "discover_pack_images",
]
