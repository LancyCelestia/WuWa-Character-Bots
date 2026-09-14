"""笔记能力（bot.notes，经 bot.reminder 路由面）：Markdown 笔记 + 待办勾选。

触发（全部收在 REMINDER 路由的 is_reminder_command 判定里，不新增
RouteKind——笔记词形已并入 route-matrix §2 reminder 行，A34 终审核验）：
- 「笔记 记 <内容>」/「筆記 記」/「biji 记」：新增（可带图片消息一起发，
  图落 data/notes_images/，content_md 落 ![图片N](文件名) 引用行）；
- 「笔记列表」/「bijiliebiao / bjlb」：本会话清单；
- 「笔记 看 N」/「看笔记 N」：看第 N 条（纯文本化展示，图片补发）；
- 「做完 N」：勾选第 N 条待办；「删笔记 N」：删除。
- 内容含 ``- [ ]`` 勾选框 → 自动判为待办（kind=todo）。

存储经 character/notes_store（SQLite，runtime_paths 解析，会话隔离）。
文案守岸人语气：温柔、简短、不机器腔。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from plugins.bot_unified_runtime.character.notes_store import (
    Note,
    build_notes_store,
)
from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)

# ---------------------------------------------------------------------------
# 触发词（T-Spec 风格：中文 + 繁體 + 全拼 + 缩写；ASCII 词双侧边界）。
# 这组正则被 capabilities/reminder.is_reminder_command 直接引用，触发体检
# （extract_trigger_words）在 bot.reminder 名下按行为验证并入棘轮。
# ---------------------------------------------------------------------------

_NOTES_WORD = r"(?:笔记|筆記|biji|note)"
_NOTES_ASCII = r"(?<![A-Za-z0-9])(?:biji|bijiliebiao|bjlb|shanbiji|kanbiji)(?![A-Za-z0-9])"
# 列表：笔记(列表)? / 笔记清单 / bijiliebiao / bjlb。
_NOTES_LIST_RE = re.compile(
    rf"^(?:{_NOTES_WORD})\s*(?:列表|清单|liebiao)?\s*$"
    rf"|{_NOTES_ASCII}",
    re.IGNORECASE,
)
# 删除：删(除)笔记 N / 笔记删 N / shanbiji N。
_NOTES_DELETE_RE = re.compile(
    rf"^(?:删除|刪除|删|刪)\s*(?:{_NOTES_WORD})\s*[，,：:]?\s*(\d+)\s*$"
    rf"|^(?:{_NOTES_WORD})\s*(?:删|刪)\s*(\d+)\s*$"
    rf"|(?<![A-Za-z0-9])shanbiji\s*(\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# 查看：笔记 看 N / 看(查)笔记 N / kanbiji N。
_NOTES_VIEW_RE = re.compile(
    rf"^(?:{_NOTES_WORD})\s*[，,：:]?\s*(?:看|查|翻)\s*(\d+)\s*$"
    rf"|^(?:看|查)(?:{_NOTES_WORD})\s*[，,：:]?\s*(\d+)\s*$"
    rf"|(?<![A-Za-z0-9])kanbiji\s*(\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# 完成：做完 N / 完成 N / 办完 N（显式编号勾选；自然语言勾选走 reminder 侧）。
_NOTES_DONE_RE = re.compile(r"^(?:做完|完成|办完)\s*(\d+)\s*$")
# 新增：笔记 [记] <内容>（内容必填；bare 触发走 usage 提示）。CJK 分支维持
# 「笔记[记]内容」紧贴形态；ASCII 分支（biji/note）后必须跟分隔（空白/
# 标点/记|ji），防 bijiqq/noteqq 粘连词被 (.+) 吞成命令（T-Spec ASCII
# 词边界棘轮，2026-09-13 触发体检抓漏后收口）。
_NOTES_ADD_RE = re.compile(
    r"^(?:笔记|筆記)\s*[，,：:]?\s*(?:记|記|ji)?\s*[，,：:]?\s*(.+)$"
    r"|(?<![A-Za-z0-9])(?:biji|note)\s*(?:[，,：:]\s*|(?:记|記)\s*|\s+)(.+)$",
    re.IGNORECASE | re.DOTALL,
)
# bare 触发（笔记/biji/note…）：给用法提示而非空列表。
_NOTES_BARE_RE = re.compile(rf"^(?:{_NOTES_WORD})\s*[…。.！!？?\s]*$", re.IGNORECASE)

_MAX_COMMAND_CHARS = 4000

# 图片引用行：![图片N](文件名) —— 落库、展示、回发共用这一种形态。
_NOTE_IMAGE_LINE_RE = re.compile(r"^!\[图片(\d+)\]\(([^)]+)\)\s*$", re.MULTILINE)
_INLINE_IMAGE_RE = re.compile(r"!\[图片(\d+)\]\(([^)]+)\)")

_MAX_NOTE_IMAGES = 4
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_IMAGE_UA = "Mozilla/5.0 (compatible; shorekeeper-notes/1.0)"


def is_notes_command(text: str, *, config: Any | None = None) -> bool:
    """笔记指令面判定（含 bare 触发词；bot_notes_enabled 可关整组）。"""
    if config is not None and not getattr(config, "bot_notes_enabled", True):
        return False
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _MAX_COMMAND_CHARS:
        return False
    return bool(
        _NOTES_LIST_RE.search(stripped)
        or _NOTES_DELETE_RE.search(stripped)
        or _NOTES_VIEW_RE.search(stripped)
        or _NOTES_DONE_RE.search(stripped)
        or _NOTES_ADD_RE.search(stripped)
        or _NOTES_BARE_RE.match(stripped)
    )


# ---------------------------------------------------------------------------
# 展示：Markdown → 纯文本（标题保留 #；图片行显示 [图片N]；剥行内强调）。
# ---------------------------------------------------------------------------

_INLINE_EMPHASIS_RE = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|~~([^~]+)~~")
_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_TODO_BOX_PREFIX_RE = re.compile(r"^[-*]?\s*\[[ xX]?\]\s*")


def note_display_text(content_md: str) -> str:
    """纯文本化：图片行 → [图片N]，行内强调剥壳，标题保留 #。"""
    lines: list[str] = []
    for raw_line in str(content_md or "").splitlines():
        line = raw_line.rstrip()
        image_match = _INLINE_IMAGE_RE.fullmatch(line.strip())
        if image_match:
            lines.append(f"[图片{image_match.group(1)}]")
            continue
        line = _INLINE_EMPHASIS_RE.sub(
            lambda m: next(g for g in m.groups() if g is not None), line
        )
        # 链接保留可见文字：[文字](url) → 文字。
        line = _INLINE_LINK_RE.sub(r"\1", line)
        lines.append(line)
    return "\n".join(lines).strip()


def note_image_files(content_md: str, images_root: Path, chat_id: str) -> list[Path]:
    """解析 content_md 里的图片引用 → 绝对路径（存在才返回）。

    文件名只取 basename 再拼回会话目录（防引用行被改成 ../ 穿越）。
    """
    from hashlib import sha1

    chat_dir = images_root / sha1(str(chat_id).encode()).hexdigest()[:12]
    found: list[Path] = []
    for _index, filename in _NOTE_IMAGE_LINE_RE.findall(str(content_md or "")):
        safe = Path(str(filename)).name
        candidate = chat_dir / safe
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


# ---------------------------------------------------------------------------
# 图片落盘：消息段（image/animation，url 或本地 file）→ notes_images 目录。
# ---------------------------------------------------------------------------

_IMAGE_SEGMENT_TYPES = frozenset({"image", "animation"})


def _sniff_image_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def _images_root(config: Any | None) -> Path:
    from plugins.bot_unified_runtime.character.providers import build_runtime_data_path

    return build_runtime_data_path(config, "data/notes_images")


def _read_local_image(raw: str, max_bytes: int) -> bytes | None:
    local = str(raw or "").strip()
    if local.startswith("file://"):
        local = local.removeprefix("file://")
    path = Path(unquote(local))
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data or len(data) > max_bytes:
        return None
    if _sniff_image_ext(data) == "":
        return None
    return data


def _fetch_image_bytes(url: str, max_bytes: int) -> bytes | None:
    """下载图片（SSRF 护栏：入口与最终 URL 双查；限长；魔数后验）。"""
    import urllib.request

    from plugins.bot_unified_runtime.sources.downloader import check_download_url

    try:
        check_download_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": _IMAGE_UA})
        with urllib.request.urlopen(request, timeout=10) as response:
            final_url = str(response.geturl() or url)
            check_download_url(final_url)
            data = response.read(max_bytes + 1)
    except Exception:  # noqa: BLE001 - 单图失败不拖垮笔记本身。
        return None
    if not data or len(data) > max_bytes:
        return None
    return data


def _extract_image_segments(message: IncomingMessage) -> list[tuple[str, str]]:
    """(url, local_path) 列表；只看本消息图片段，去重，截 4 张。"""
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for segment in message.raw_segments or []:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type", "")).lower() not in _IMAGE_SEGMENT_TYPES:
            continue
        data = segment.get("data") or {}
        if not isinstance(data, dict):
            continue
        url = str(data.get("url") or "").strip()
        local = str(data.get("file") or data.get("path") or "").strip()
        if not url and not local:
            continue
        key = f"{url}|{local}"
        if key in seen:
            continue
        seen.add(key)
        items.append((url, local))
        if len(items) >= _MAX_NOTE_IMAGES:
            break
    return items


def _save_note_images(
    config: Any | None, message: IncomingMessage
) -> tuple[list[str], list[Path]]:
    """把消息里的图落盘；返回 (文件名列表, 绝对路径列表)。失败静默跳过。"""
    from hashlib import sha1

    root = _images_root(config)
    chat_dir = root / sha1(str(message.session_id).encode()).hexdigest()[:12]
    chat_dir.mkdir(parents=True, exist_ok=True)
    filenames: list[str] = []
    paths: list[Path] = []
    for url, local in _extract_image_segments(message):
        data = None
        if url:
            data = _fetch_image_bytes(url, _MAX_IMAGE_BYTES)
        if data is None and local:
            data = _read_local_image(local, _MAX_IMAGE_BYTES)
        if data is None or _sniff_image_ext(data) == "":
            continue  # 拿不到字节或魔数不认识：不当图片收。
        filename = f"{uuid.uuid4().hex[:16]}{_sniff_image_ext(data)}"
        target = chat_dir / filename
        try:
            target.write_bytes(data)
        except OSError:
            continue
        filenames.append(filename)
        paths.append(target)
    return filenames, paths


def _cleanup_images(config: Any | None, chat_id: str, note: Note) -> None:
    for path in note_image_files(note.content_md, _images_root(config), chat_id):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 能力主体
# ---------------------------------------------------------------------------

_USAGE_TEXT = (
    "笔记可以这样用：\n"
    "- 「笔记 记 内容」：记一条（可以配图一起发）\n"
    "- 「笔记列表」：看看都记了什么\n"
    "- 「笔记 看 N」：翻开第 N 条（配图会一起补发）\n"
    "- 「做完 N」：把第 N 条里头一件没做的事勾掉（有几件就说几次）\n"
    "- 「删笔记 N」：放下第 N 条\n"
    "内容里写「- [ ] 待办」的行，会被我当作待办来看。"
)


def build_notes_capability(config: Any | None = None) -> Any:
    """构建笔记能力：与 reminder 等能力一致，返回 (message, decision) -> 结果。"""

    def _result(
        message: IncomingMessage,
        body: str,
        *,
        tags: list[str],
        images: list[Path] | None = None,
    ) -> CapabilityResult:
        return CapabilityResult(
            request_id=message.request_id,
            capability_id="bot.reminder",
            kind="text",
            title="",
            body=body,
            send_policy=SendPolicy.SILENT_AUDIT,
            images=[{"file": str(item)} for item in (images or [])],
            audit_tags=["notes", *tags],
        )

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        chat_id = message.session_id
        store = build_notes_store(config)
        max_per_chat = int(getattr(config, "bot_notes_max_per_chat", 200) or 200)

        if _NOTES_BARE_RE.match(text):
            return _result(message, _USAGE_TEXT, tags=["usage"])

        delete_match = _NOTES_DELETE_RE.search(text)
        if delete_match:
            note_id = int(next(g for g in delete_match.groups() if g))
            note = store.delete(note_id, chat_id)
            if note is None:
                return _result(
                    message,
                    f"没有找到第 {note_id} 条笔记。用「笔记列表」对一下编号？",
                    tags=["delete_miss"],
                )
            # 图片文件随笔记一起放下（引用已不在，留着只会积灰）。
            _cleanup_images(config, chat_id, note)
            return _result(
                message,
                # 文案审计②：与提醒域统一用词「放下」（原「放开」孤例）。
                f"第 {note_id} 条笔记已经放下了。需要的时候，再记下来就好。",
                tags=["deleted"],
            )

        view_match = _NOTES_VIEW_RE.search(text)
        if view_match:
            note_id = int(next(g for g in view_match.groups() if g))
            note = store.get(note_id, chat_id)
            if note is None:
                return _result(
                    message,
                    f"这个会话里没有第 {note_id} 条笔记。「笔记列表」里看看？",
                    tags=["view_miss"],
                )
            state_line = ""
            if note.is_todo:
                state_line = "（已完成）" if note.todo_state == "done" else "（待办，还没完成）"
            body = note_display_text(note.content_md)
            images = note_image_files(note.content_md, _images_root(config), chat_id)
            return _result(
                message,
                f"第 {note_id} 条{state_line}：\n{body}",
                tags=["viewed"],
                images=images,
            )

        done_match = _NOTES_DONE_RE.search(text)
        if done_match:
            note_id = int(done_match.group(1))
            note = store.get(note_id, chat_id)
            if note is None:
                return _result(
                    message,
                    f"这个会话里没有第 {note_id} 条笔记。「笔记列表」里看看？",
                    tags=["done_miss"],
                )
            if not note.is_todo:
                return _result(
                    message,
                    f"第 {note_id} 条是一条普通的笔记，不是待办——不标注完成也没关系，它就在那里。",
                    tags=["done_not_todo"],
                )
            if note.todo_state == "done":
                return _result(
                    message,
                    f"第 {note_id} 条已经完成过了。安心。",
                    tags=["done_repeat"],
                )
            # 审查 A-06：勾选粒度=条目而非整篇。编号勾选固定勾掉第一个
            # 未勾条目；要点名具体哪一件，用「<事项>做完了」自然语言勾选
            # （reminder 侧，多命中会列候选问人）。
            open_items = note.todo_open_items()
            if not open_items:
                # kind=todo 却无未勾条目（历史整篇 done 的残余形态，正常
                # 路径到不了这里）：按兼容路径收口状态，不再走条目改写。
                store.mark_done(note_id, chat_id)
                return _result(
                    message,
                    f"第 {note_id} 条已经完成过了。安心。",
                    tags=["done_repeat"],
                )
            first_index, first_text = open_items[0]
            updated = store.mark_item_done(note_id, chat_id, first_index)
            if updated is None:
                # 并发窗口内笔记被删/改写：按未命中回话，不编造成功。
                return _result(
                    message,
                    f"这个会话里没有第 {note_id} 条笔记。「笔记列表」里看看？",
                    tags=["done_miss"],
                )
            if updated.todo_state == "done":
                # 勾掉的正是最后一件：整篇完成，观感与旧版一致。
                return _result(
                    message,
                    f"（轻轻点头）第 {note_id} 条，完成了。「{updated.display_headline(max_chars=16)}」"
                    "——剩下的事不着急，一件一件来。",
                    tags=["done"],
                )
            remaining = len(updated.todo_open_items())
            return _result(
                message,
                f"嗯，那一条勾掉了：「{first_text[:24]}」。"
                f"这篇还剩 {remaining} 件待办，不急，一件一件来。",
                tags=["done_item"],
            )

        if _NOTES_LIST_RE.search(text):
            notes = store.list_notes(chat_id)
            if not notes:
                return _result(
                    message,
                    "还没有为你记下过笔记。想记的话：「笔记 记 内容」，配图也可以。",
                    tags=["list_empty"],
                )
            lines = []
            for note in notes:
                mark = "☑" if note.todo_state == "done" else ("□" if note.is_todo else "·")
                lines.append(f"- {note.note_id} {mark} {note.display_headline()}")
            open_count = sum(1 for note in notes if note.is_open)
            tail = f"\n（待办还开着 {open_count} 件；「笔记 看 N」可翻开，配图会一起补发）"
            return _result(message, "\n".join(lines) + tail, tags=["listed"])

        add_match = _NOTES_ADD_RE.search(text)
        if add_match:
            # 双分支（CJK/ASCII）捕获组二选一，取非空组。
            content_md = next(g for g in add_match.groups() if g).strip()
            if not content_md:
                return _result(message, _USAGE_TEXT, tags=["usage"])
            if store.count_chat(chat_id) >= max_per_chat:
                return _result(
                    message,
                    f"这个会话的笔记已经收满 {max_per_chat} 条了。先整理一下——"
                    "「删笔记 N」清掉不需要的，再记新的。",
                    tags=["limit_reached"],
                )
            image_names, _image_paths = _save_note_images(config, message)
            if image_names:
                content_md += "\n" + "\n".join(
                    f"![图片{index}]({name})"
                    for index, name in enumerate(image_names, start=1)
                )
            note = store.add(
                user_id=message.sender_id,
                chat_id=chat_id,
                content_md=content_md[:4000],
            )
            if note is None:  # 并发兜底（预检后仍可能满）。
                return _result(
                    message,
                    f"这个会话的笔记已经收满 {max_per_chat} 条了。先整理一下——"
                    "「删笔记 N」清掉不需要的，再记新的。",
                    tags=["limit_reached"],
                )
            suffix = (
                f"（附图 {len(image_names)} 张，「笔记 看 {note.note_id}」可回看）"
                if image_names
                else ""
            )
            return _result(
                message,
                f"记下了，第 {note.note_id} 条，安稳收好{suffix}。"
                f"要看的时候说「笔记 看 {note.note_id}」。",
                tags=["added", "with_images"] if image_names else ["added"],
            )

        return _result(message, _USAGE_TEXT, tags=["usage"])

    return capability


__all__ = [
    "build_notes_capability",
    "is_notes_command",
    "note_display_text",
    "note_image_files",
]
