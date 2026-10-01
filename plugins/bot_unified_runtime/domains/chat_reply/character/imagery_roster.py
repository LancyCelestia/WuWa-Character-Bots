"""意象族名册的读取与轮换选族（T8 续批，2026-09-28 用户裁定「意象跟着人格走」）。

她的口径分两刀，本件只接第一刀：

* **意象、说话风格、语气、世界观与经历 ⇒ 跟着人格走** ⇒ 名册住
  ``personas/<人格档>/imagery_families.txt``（人格侧真身），本模块**只读**它，
  代码里一个族名都不写死。换人格档＝自动换一套取材面，不需要改代码。
* **回复策略 ⇒ 跟着用户走**（不分私聊与群）⇒ 那半边住在
  :mod:`reply_policy`，本模块不碰键、不碰库，只做纯函数。

为什么要有轮换：她要「更多样化」。只在指令里写一句「别重复」是**不可验证的**——
下一轮模型照样端同一句比喻上桌。所以这里给出可测的判据：名册是池，用量账记
「这个人最近用过哪些族」，选族时避开窗口内的族；池被用满时回退成整池按最久未用补，
绝不回空（回空＝提示里那一行凭空消失，她看到的是"又开始重复"，而日志上一切正常）。

失败面全静默：文件缺失、人格档为空、编码坏了 ⇒ 返回空池，调用方据此**不派意象**，
绝不因为一份附属名册读不出来就把一轮聊天弄没。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: 名册文件名（人格档目录下）。与 ``personas/<profile>/aliases.txt`` 同一家规：
#: 一条能力对应一份人格侧附属文件，代码只消费、不复制内容。
ROSTER_FILE_NAME: Final[str] = "imagery_families.txt"

#: 族名与取材提示的分隔符（全角竖线优先，半角兜底——手写的表容易混）。
_SEPARATORS: Final[tuple[str, ...]] = ("｜", "|")


@dataclass(frozen=True)
class ImageryFamily:
    """一族意象：``name`` 进提示词当标签，``cue`` 是往哪儿看的取材提示。"""

    name: str
    cue: str = ""


def _repo_root() -> Path:
    # 本件位于 .../domains/chat_reply/character/imagery_roster.py，parents[5]＝仓库根。
    return Path(__file__).resolve().parents[5]


def parse_roster_text(raw: str) -> tuple[ImageryFamily, ...]:
    """文本 → 族表：跳过空行与 ``#`` 注释；无分隔符的裸行按族名收。

    解析口径只在这里写一次（文件读取与任何测试夹具共用它），免得长出第二份切行逻辑。
    """
    families: list[ImageryFamily] = []
    seen: set[str] = set()
    for line in str(raw or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        name, cue = text, ""
        for separator in _SEPARATORS:
            if separator in text:
                name, _, cue = text.partition(separator)
                break
        family_name = name.strip()
        if not family_name or family_name in seen:
            continue
        seen.add(family_name)
        families.append(ImageryFamily(name=family_name, cue=cue.strip()))
    return tuple(families)


#: 人格档名的合法形状（当路径分量用之前先夹形）。
#: 为什么必须夹：档名来自 config、也来自主格每轮选出的现役人格，一旦被塞进 ``../..``
#: 或 NUL 就成了「拿别人的文本当路径」的口子（同 ``runtime/aliases.py`` 的 D1-6 教训、
#: ``domains/media`` 的目录消毒口径）。判据只认字母数字与 ``-_.``，其余一律当读不到。
_PROFILE_ID_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def load_imagery_families(
    profile_id: object, *, root: Path | None = None
) -> tuple[ImageryFamily, ...]:
    """读 ``personas/<profile>/imagery_families.txt``；认不出人格档或读不到 ⇒ 空池。

    失败面一律**吞掉不抛**（``OSError``／``UnicodeDecodeError``／值形状不合法／任何
    意料外的异常）：名册塌了只该塌意象这一条加法腿，不该带走一轮聊天。
    """
    profile = str(profile_id or "").strip()
    if not profile or not _PROFILE_ID_RE.fullmatch(profile):
        if profile:
            logger.warning("imagery roster ignored (bad profile shape)")
        return ()
    base = Path(root) if root is not None else _repo_root()
    candidate = base / "personas" / profile / ROSTER_FILE_NAME
    try:
        raw = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        # 缺文件在切换人格/新装人格档时是正常态，只留一行 debug，不刷警告级别。
        logger.debug(
            "imagery roster unreadable profile=%s type=%s", profile, type(exc).__name__
        )
        return ()
    except Exception as exc:  # noqa: BLE001 - 名册这条腿不许把异常递给聊天主链路。
        logger.warning("imagery roster skipped profile=%s type=%s", profile, type(exc).__name__)
        return ()
    return parse_roster_text(raw)


def choose_imagery_families(
    families: list[ImageryFamily] | tuple[ImageryFamily, ...],
    *,
    recent: list[str] | tuple[str, ...] = (),
    count: int = 2,
) -> tuple[str, ...]:
    """从池里挑 ``count`` 个族名，优先挑 ``recent``（新→旧）里**没有**的。

    池被窗口吃满时回退：按最久未用（``recent`` 倒序）补齐，再按名册顺序补齐 ⇒
    只要池非空就一定有产出，绝不让提示行静默消失。
    """
    names = [str(getattr(family, "name", "") or "").strip() for family in (families or ())]
    names = [name for name in names if name]
    if not names or count <= 0:
        return ()
    used = {str(item or "").strip() for item in (recent or ()) if str(item or "").strip()}
    picked = [name for name in names if name not in used][:count]
    if len(picked) < count:
        for name in reversed([str(item or "").strip() for item in (recent or ())]):
            if len(picked) >= count:
                break
            if name and name in names and name not in picked:
                picked.append(name)
    if len(picked) < count:
        for name in names:
            if len(picked) >= count:
                break
            if name not in picked:
                picked.append(name)
    return tuple(picked)


__all__ = [
    "ROSTER_FILE_NAME",
    "ImageryFamily",
    "choose_imagery_families",
    "load_imagery_families",
    "parse_roster_text",
]
