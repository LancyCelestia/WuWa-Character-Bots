"""日常助理存储与文案（bot.daily_assist 的 character 面）。

收件箱/菜单/任务清单都是纯文本文件（``bot_daily_assist_dir`` 目录下），
设计成 ZCode、手机端与机器人都能直接编辑的共享格式：

- ``inbox.md``：``## 待处理`` 段逐行累积；早报读取后整段归档到 ``daily/YYYY-MM-DD.md``
- ``food.md``：按 ``## 分节`` 组织；``## 备注`` 段不参与随机；``# ``, ``> ``, ``- `` 前缀剥除
- ``tasks.md``：``## 进行中`` / ``## 已计划`` / ``## 想法池`` 三段；晚报读这三段
- ``daily/meal_history.jsonl``：吃什么推荐历史（同一道菜 7 天内不重复）

并发模型与项目惯例一致：进程内 ``threading.Lock`` 包住「检查 → mkdir → 追加」
（APScheduler 线程池与能力面可能同时写）；不做跨进程保障（无此先例）。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

_INBOX_PENDING_HEADER = "## 待处理"
_FOOD_EXCLUDED_SECTIONS = {"备注", "備註"}
_INBOX_APPEND_LOCK = threading.Lock()

_MEAL_HISTORY_FILE = "daily/meal_history.jsonl"
_FOOD_FILE = "food.md"
_INBOX_FILE = "inbox.md"
_TASKS_FILE = "tasks.md"
_MEAL_REPEAT_DAYS = 7


def _assist_dir(config: Any) -> Path:
    from plugins.bot_unified_runtime.character.providers import build_runtime_data_path

    raw = str(getattr(config, "bot_daily_assist_dir", "") or "data/daily_assist")
    return Path(build_runtime_data_path(config, raw))


def food_path(config: Any) -> Path:
    return _assist_dir(config) / _FOOD_FILE


def inbox_path(config: Any) -> Path:
    return _assist_dir(config) / _INBOX_FILE


def tasks_path(config: Any) -> Path:
    return _assist_dir(config) / _TASKS_FILE


def meal_history_path(config: Any) -> Path:
    return _assist_dir(config) / _MEAL_HISTORY_FILE


def daily_archive_dir(config: Any) -> Path:
    """收件箱归档目录（``<dir>/daily``，按日期一文件）。"""
    return _assist_dir(config) / "daily"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _strip_bullet(line: str) -> str:
    return re.sub(r"^[-*]\s+", "", line.strip())


def parse_food_choices(text: str) -> list[str]:
    """从菜单文本取可推荐条目：跳过备注分节、标题、引用与空行。"""
    choices: list[str] = []
    section = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if line.startswith(">"):
            continue
        if section in _FOOD_EXCLUDED_SECTIONS:
            continue
        item = _strip_bullet(line)
        if not item or item.startswith("<"):
            continue
        choices.append(item)
    return choices


def meal_display_name(item: str) -> str:
    """「麻辣香锅（不想太辣的日子跳过）」→「麻辣香锅」。"""
    return item.split("（")[0].split("(")[0].strip() or item


def _read_meal_history(path: Path) -> list[tuple[date, str]]:
    entries: list[tuple[date, str]] = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            entries.append(
                (
                    date.fromisoformat(str(record.get("date", ""))),
                    str(record.get("name", "")),
                )
            )
        except (ValueError, TypeError):
            continue
    return entries


def _record_meal_pick(path: Path, name: str, today: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"date": today.isoformat(), "name": name}, ensure_ascii=False))
        handle.write("\n")


def choose_meal(
    config: Any,
    *,
    now: datetime | None = None,
    rng: Any = None,
    custom_choices: list[str] | None = None,
) -> str:
    """到点择菜：自定义菜单优先、内置菜库兜底；7 天内吃过的靠后。

    全部候选都在 7 天排除名单里时回退全量池（宁可重复，不出不了菜）。
    每次选择即落历史（jsonl 一行一条）。
    """
    import random

    picker = rng if rng is not None else random
    moment = (now or datetime.now().astimezone()).date()
    choices = custom_choices
    if choices is None:
        choices = parse_food_choices(_read_text(food_path(config)))
    if not choices:
        from plugins.bot_unified_runtime.domains.food.data.food_data import DISHES

        choices = [dish.name for dish in DISHES]
    named = [(meal_display_name(item), item) for item in choices]
    recent = {
        name
        for picked_on, name in _read_meal_history(meal_history_path(config))
        if (moment - picked_on).days < _MEAL_REPEAT_DAYS
    }
    fresh = [pair for pair in named if pair[0] not in recent]
    pool = fresh or named
    _, picked = picker.choice(pool)
    _record_meal_pick(meal_history_path(config), meal_display_name(picked), moment)
    return picked


def append_inbox_line(path: Path, text: str, *, now: datetime | None = None) -> str:
    """往收件箱 ``## 待处理`` 段追加一条；文件缺失时按模板创建。"""
    moment = now or datetime.now().astimezone()
    line = f"- [{moment.strftime('%Y-%m-%d %H:%M')}] {text.strip()}"
    with _INBOX_APPEND_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _read_text(path)
        if not content.strip():
            content = f"# 收件箱（Inbox）\n\n{_INBOX_PENDING_HEADER}\n\n"
        if _INBOX_PENDING_HEADER not in content:
            content = content.rstrip("\n") + f"\n\n{_INBOX_PENDING_HEADER}\n\n"
        updated = content.rstrip("\n") + "\n" + line + "\n"
        path.write_text(updated, encoding="utf-8")
    return line


def read_pending_inbox(path: Path) -> list[str]:
    """读收件箱 ``## 待处理`` 段的条目行（剥除空行，保留原文）。"""
    pending: list[str] = []
    in_pending = False
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_pending = line == _INBOX_PENDING_HEADER
            continue
        if not in_pending or not line:
            continue
        if line.startswith("#") or line == "（空）":
            continue
        pending.append(_strip_bullet(line))
    return pending


def archive_inbox(path: Path, archive_dir: Path, *, now: datetime | None = None) -> list[str]:
    """把待处理段整体搬进 ``archive_dir/YYYY-MM-DD.md`` 并清空待处理段。

    返回被归档的条目；待处理段本就为空时不写盘、返回空表。
    """
    moment = now or datetime.now().astimezone()
    pending = read_pending_inbox(path)
    if not pending:
        return []
    archive_dir.mkdir(parents=True, exist_ok=True)
    daily_file = archive_dir / f"{moment.date().isoformat()}.md"
    with daily_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## 收件箱归档 {moment.strftime('%H:%M')}\n")
        for item in pending:
            handle.write(f"{item}\n")
    _rewrite_without_pending(path)
    return pending


def _rewrite_without_pending(path: Path) -> None:
    with _INBOX_APPEND_LOCK:
        lines = _read_text(path).splitlines()
        kept: list[str] = []
        in_pending = False
        wrote_placeholder = False
        for raw in lines:
            stripped = raw.strip()
            if stripped.startswith("## "):
                if in_pending and not wrote_placeholder:
                    kept.append("（空）")
                    wrote_placeholder = True
                in_pending = stripped == _INBOX_PENDING_HEADER
                kept.append(raw)
                continue
            if in_pending:
                if not stripped or stripped == "（空）":
                    continue
                continue
            kept.append(raw)
        if in_pending and not wrote_placeholder:
            kept.append("（空）")
        path.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")


def read_task_sections(path: Path) -> dict[str, list[str]]:
    """读任务清单的 ``## 分节 → 条目``（进行中/已计划/想法池）。"""
    sections: dict[str, list[str]] = {}
    section = ""
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line.lstrip("#").strip()
            sections.setdefault(section, [])
            continue
        if not section or not line or line.startswith("#"):
            continue
        item = _strip_bullet(line)
        if not item or item == "（空）":
            continue
        sections[section].append(item)
    return sections


# ---------------------------------------------------------------------------
# 文案池（守岸人语气）：与 chat.py 五池话术同构的确定性轮换，规模收小——
# 全局游标按序循环，同池连发不重复；文案只动措辞，不动简报结构。
# ---------------------------------------------------------------------------

_VARIANT_CURSOR_LOCK = threading.Lock()
_VARIANT_CURSORS: dict[str, int] = {}

_MORNING_EMPTY_OPENERS: tuple[str, ...] = (
    "早。收件箱和清单都干干净净的，今天轻装上阵。",
    "早上好。守岸人看过了，没有攒着的事，也没有挂着的事，安心过今天。",
    "早。今天没有待办压着，时间都是你自己的。",
    "新的一天。守岸人这边什么都没攒着，你可以慢慢来。",
    "醒来了就好。收件箱干净、清单干净，守岸人没什么要催你的。",
    "早。两边都空着，守岸人陪你轻轻松松过今天。",
)

_MORNING_OPENERS: tuple[str, ...] = (
    "早。守岸人把今天要注意的理出来了：",
    "早上好。今天手上有这些事，守岸人给你排好了：",
    "早。新的一天，守岸人先把挂着的事摆出来：",
    "醒了就好。守岸人把今天的事都列在这儿了：",
    "早安。守岸人记着的都在下面，过一遍再开始今天：",
    "早。不着急，守岸人陪你对一遍今天的安排：",
)

_MORNING_IDEA_NOTES: tuple[str, ...] = (
    "（想法池还有 {n} 条，守岸人先替你收着）",
    "（想法池里躺着 {n} 条，先不吵它们）",
    "（另外，想法池攒了 {n} 条，先不动）",
    "（想法池还有 {n} 条，等你哪天想捡起来）",
    "（想法池里存着 {n} 条，都好好的）",
    "（想法池 {n} 条，守岸人看着呢，不急）",
)

_EVENING_OPENERS: tuple[str, ...] = (
    "今天辛苦了。守岸人把这一天的账理了理，睡前看两眼就好。",
    "忙完就早点歇着。守岸人把今天记下的事拢了一遍，放在下面了。",
    "晚上好。一天到头了，守岸人替你把小事都记着呢。",
    "今天也走到晚上了。守岸人在，慢慢看，不着急。",
    "夜深了，别撑着。守岸人把今天的事替你收了个尾。",
    "今天辛苦了。守岸人守着这些小事，你安心休息就好。",
    "到歇下的点了。守岸人把一天的事理了一份，你过目就好。",
)

_EVENING_INBOX_EMPTY_LINES: tuple[str, ...] = (
    "收件箱今天很安静，没有新记下的事。",
    "今天没有人往收件箱里放事情，它也歇了一天。",
    "守岸人看过了，收件箱今天零新增。",
    "收件箱空空的，今天没攒下什么。",
    "收件箱今天没进新东西，干干净净的。",
    "守岸人这边也是空的，你今天没往里丢事，这样也挺好。",
)

_EVENING_INBOX_COUNTED_LINES: tuple[str, ...] = (
    "收件箱今天进了 {n} 条，都归好档了。",
    "今天记下的 {n} 条，守岸人都替你收好了。",
    "{n} 条新的进了收件箱，已经放进归档里了。",
    "守岸人把今天进来的 {n} 条都理好了，归了档。",
    "收件箱今天添了 {n} 条，都放得妥妥的。",
    "今天攒下 {n} 条，守岸人已经替你理进档案了。",
)

_EVENING_IDEA_NUDGES: tuple[str, ...] = (
    "有空的时候，挑一条让它转正？",
    "想法不急着动，哪条熟了就把它请进「已计划」。",
    "有看对眼的，就提拔成正经任务吧。",
    "这些先放着想，哪天想落地了再挪不迟。",
    "守岸人先替你收着，想捡起哪条随时说。",
    "别有压力，放着也是一种安排。",
)


def pick_variant(key: str, variants: tuple[str, ...], **fields: Any) -> str:
    """按池确定性轮换取文案（chat.py 五池游标纪律的小型同构）。

    同 key 按调用序循环取用，连发不重复；用户内容只作格式化参数传入，
    不参与模板解析。调度/dedupe/落盘等行为面零改动，只有措辞在换。
    """
    with _VARIANT_CURSOR_LOCK:
        offset = _VARIANT_CURSORS.get(key, 0)
        _VARIANT_CURSORS[key] = (offset + 1) % len(variants)
    template = variants[offset % len(variants)]
    return template.format(**fields) if fields else template


def summarize_with_llm(config: Any, body: str, *, instruction: str) -> str:
    """主聊天模型路由出一小段总结/建议；失败返回空串（调用方回退原文）。"""
    stripped = (body or "").strip()
    if not stripped:
        return ""
    try:
        from plugins.bot_unified_runtime.llm.model_router import build_model_router

        router = build_model_router(config)
        reply = router.generate(
            [{"role": "user", "content": f"{instruction}\n\n{stripped[:4000]}"}],
            message_text=stripped[:200],
        )
        return str(getattr(reply, "text", "") or "").strip()
    except Exception:  # noqa: BLE001 - LLM 缺席时定时简报照发，只是少了划重点。
        return ""


def build_morning_brief(
    pending: list[str],
    task_sections: dict[str, list[str]],
    llm_summary: str = "",
) -> str:
    """早报正文（守岸人语气）：一句开场 + 收件箱条目 + 今日挂账 + 划重点。"""
    active = task_sections.get("进行中", [])
    planned = task_sections.get("已计划", [])
    ideas = task_sections.get("想法池", [])
    if not pending and not active and not planned:
        return pick_variant("morning_empty", _MORNING_EMPTY_OPENERS)
    lines: list[str] = [pick_variant("morning_open", _MORNING_OPENERS)]
    if pending:
        lines.append("【收件箱】")
        lines.extend(f"{index}. {item}" for index, item in enumerate(pending, 1))
    if active:
        lines.append("【进行中】")
        lines.extend(f"- {item}" for item in active)
    if planned:
        lines.append("【已计划】")
        lines.extend(f"- {item}" for item in planned)
    if ideas:
        lines.append(pick_variant("morning_ideas", _MORNING_IDEA_NOTES, n=len(ideas)))
    if llm_summary:
        lines.append("【划重点】")
        lines.append(llm_summary)
    return "\n".join(lines)


def build_evening_brief(
    task_sections: dict[str, list[str]],
    archived_today: list[str],
    llm_suggestion: str = "",
) -> str:
    """晚报正文：今天收了多少、清单还挂什么、主动想到的琐事建议。"""
    active = task_sections.get("进行中", [])
    planned = task_sections.get("已计划", [])
    ideas = task_sections.get("想法池", [])
    lines: list[str] = [pick_variant("evening_open", _EVENING_OPENERS)]
    lines.append(
        pick_variant("evening_counted", _EVENING_INBOX_COUNTED_LINES, n=len(archived_today))
        if archived_today
        else pick_variant("evening_empty", _EVENING_INBOX_EMPTY_LINES)
    )
    if active:
        lines.append("【还挂着的】")
        lines.extend(f"- {item}" for item in active)
    if planned:
        lines.append("【之后的安排】")
        lines.extend(f"- {item}" for item in planned)
    if ideas:
        lines.append("【想法池】")
        lines.extend(f"- {item}" for item in ideas)
        lines.append(pick_variant("evening_nudge", _EVENING_IDEA_NUDGES))
    if llm_suggestion:
        lines.append("【替你想了想】")
        lines.append(llm_suggestion)
    return "\n".join(lines)


def load_daily_archive(archive_dir: Path, *, now: datetime | None = None) -> list[str]:
    """读当天已归档的收件箱条目（晚报账目用）。"""
    moment = now or datetime.now().astimezone()
    daily_file = archive_dir / f"{moment.date().isoformat()}.md"
    items: list[str] = []
    for raw in _read_text(daily_file).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(_strip_bullet(line))
    return items


__all__ = [
    "append_inbox_line",
    "archive_inbox",
    "build_evening_brief",
    "build_morning_brief",
    "choose_meal",
    "daily_archive_dir",
    "food_path",
    "inbox_path",
    "load_daily_archive",
    "meal_display_name",
    "meal_history_path",
    "parse_food_choices",
    "pick_variant",
    "read_pending_inbox",
    "read_task_sections",
    "summarize_with_llm",
    "tasks_path",
]
