"""笔记能力（bot.notes，经 bot.reminder 路由面）：Markdown 笔记 + 待办勾选。

触发（全部收在 REMINDER 路由的 is_reminder_command 判定里，不新增
RouteKind——笔记词形已并入 route-matrix §2 reminder 行，A34 终审核验）：
- 「笔记 记 <内容>」/「筆記 記」/「biji 记」：新增（可带图片消息一起发，
  图落 data/notes_images/，content_md 落 ![图片N](文件名) 引用行）；
- 「笔记列表」/「bijiliebiao / bjlb」：本会话清单；
- 「笔记 看 N」/「看笔记 N」：看第 N 条（纯文本化展示，图片补发）；
- 「做完 N」：勾选第 N 条待办；「删笔记 N」：删除。
- 撤销勾选（审查 A-14）：「取消勾选 <事项>」「<事项>还没做」「<事项>
  没做完」→ 在已勾条目里模糊匹配后回写 ``[ ]``（与勾选同一套条目匹配
  与歧义语义；无候选让位，不抢删除/普通聊天）。
- 内容含 ``- [ ]`` 勾选框 → 自动判为待办（kind=todo）。

存储经 domains/notes/store/notes_store（SQLite，runtime_paths 解析，会话隔离）。

归属（W6 2026-09-30，与 store 同批改）：读/列/删/勾四类操作**每次**都把本轮
发言人当归属人交给 store（SQL 谓词随之恒带 `AND user_id = ?`），能力层再比一次
记录自身的归属人——两层照抄记忆硬闸（`character/memory.py` 的
`SQLiteMemoryRepository.retrieve`：`requester_id != subject_user_id` 即拒）。
此前隔离只是"现网 session_id 恰好带 uid"的上游形态，store 自身零判据。
认不出发言人（空白身份）时连"记一条"也拒，绝不写出一条谁也认领不回的笔记。

文案守岸人语气：温柔、简短、不机器腔。

路由接线现状（审查 A-14）：撤销正则已并入 is_notes_command；生产路由
判定 reminder.is_reminder_command/_is_notes_surface 按正则清单显式引用
本模块（域外文件），撤销两组正则待其一行收编后自然语言撤销才在整链
生效——此前能力层单测可离线验证完整行为。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from plugins.bot_unified_runtime.contracts import (
    CapabilityResult,
    IncomingMessage,
    SendPolicy,
)
from plugins.bot_unified_runtime.domains.notes.store.notes_store import (
    Note,
    build_notes_store,
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
# 撤销勾选（审查 A-14，mark_item_done 的对称逆操作）：
# - 显式形态：「取消勾选 X」「撤销勾选/勾掉 X」（含繁體）——用户明确在
#   谈勾选，一律承接；
# - 自然形态：「X 还没做」「X 没做完」「X 还没弄完」等尾缀信号——门槛对齐
#   reminder.extract_checkoff_query（短句、非疑问、剥掉信号词后还剩得出
#   事项名）；能力层再设「无候选让位」护栏（见 capability 内撤销分支），
#   防普通聊天被抢。
# 刻意不收「取消笔记/删笔记/取消提醒」词形：删除/取消提醒是另一个决定，
# 与勾选撤销互不抢路由（_NOTES_DELETE_RE 的 删/删除/刪 与 取消/撤销 无交）。
# 交替项按最长优先排布，防「还没做完」被「还没做」截胡留下尾巴。
_NOTES_UNDO_EXPLICIT_RE = re.compile(
    r"^(?:取消|撤销|撤銷)\s*(?:勾选|勾選|勾掉|勾)\s*[，,：:]?\s*(.+)$"
)
_NOTES_UNDO_NATURAL_RE = re.compile(
    r"^(.+?)\s*(?:还没做完|還沒做完|还没弄完|還沒弄完|还没搞好|還沒搞好"
    r"|还没弄好|還沒弄好|还没做|還沒做|没做完|沒做完)\s*[了吧呢啊]?\s*$"
)
# 与 reminder 侧勾选面同量级的门槛：整句短、事项名短、非疑问。
_NOTES_UNDO_MAX_CHARS = 32
_NOTES_UNDO_QUERY_MAX_CHARS = 20
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

# 会话聚合配额（SEAT-ATK-NOTES 票 T6-5，2026-09-27）：上面两枚都是**按条
# 消息**的限额，历史笔记图全落在同一会话目录里，没有总量闸时最坏
# 200 条笔记/会话 × 4 张 × 20MB ≈ 16GB 无界增长。数值取保守默认：
# - 张数 64：日常带图笔记远用不到（约可铺满六七十条单图笔记），又远小于
#   200×4 的最坏值；目录常驻 ≤64 个条目，列举与清理成本可忽略。
# - 总字节 200MB：按单张上限 20MB 也容得下 10 张顶格图，或约 66 张 3MB
#   常见手机照片；磁盘水位风险与笔记体量诉求之间取「先保守、要放开支会
#   话再配置化」一侧（配置键提案见席位报告 §待主代理落盘，本席禁碰 config.py）。
# 总量现算自会话图片目录本身（唯一真身=磁盘现状），不另立内存账本——
# 重启不丢配额、删笔记清图后额度自然回落。
_MAX_SESSION_IMAGE_FILES = 64
_MAX_SESSION_IMAGE_BYTES = 200 * 1024 * 1024


def _extract_undo_query(text: str) -> str | None:
    """「X 还没做」「取消勾选 X」→ 事项名；不是撤销形态返回 None。

    门槛与 reminder.extract_checkoff_query 同构：短句、非疑问、剥掉信号
    词后还剩得出事项名（裸信号词「取消勾选/还没做」本身不算）。
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _NOTES_UNDO_MAX_CHARS:
        return None
    if any(ch in stripped for ch in "？?"):
        return None
    match = _NOTES_UNDO_EXPLICIT_RE.match(
        stripped
    ) or _NOTES_UNDO_NATURAL_RE.match(stripped)
    if match is None:
        return None
    query = match.group(1).strip().strip("，,。．.！!：:、；; ")
    if not query or len(query) > _NOTES_UNDO_QUERY_MAX_CHARS:
        return None
    return query


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
        or _NOTES_UNDO_EXPLICIT_RE.search(stripped)
        or _NOTES_UNDO_NATURAL_RE.search(stripped)
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
# 红线（AGENTS 第四部分「笔记/备忘录」行）＝SSRF 入口 + 落点双查：
# URL 腿走中央咽喉 + 逐跳护栏（_guarded_image_opener，建连前判定，F-G4），
# 本地腿走路径域门（_read_local_image → safety_exec.paths.check_sendable），
# 写侧落点只能是会话目录内的 uuid 名，读侧引用行只取 basename。
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
    from plugins.bot_unified_runtime.domains.core.safety_exec.paths import (
        check_sendable,
    )

    local = str(raw or "").strip()
    if local.startswith("file://"):
        local = local.removeprefix("file://")
    path = Path(unquote(local))
    # 路径域门（SEAT-ATK-NOTES 票 T6-5，2026-09-27）：消息段的本地路径是
    # 外部可控输入，读它=把这些字节收进笔记并可能日后原样补发出站——正是
    # `safety_exec.paths.check_sendable` 在册管的「能不能读字节并发出去」
    # 那一问（唯一真身判定，含禁触名册+允许根，跨目录复用不另立第二套）。
    # fail-closed：只认 allowed，needs_review/denied/判定件抛异常一律拒读；
    # 拒读只回 None（不落判定细节），出站泄露面另有 redact_local_secrets 中央口。
    try:
        decision = check_sendable(str(path))
    except Exception:  # noqa: BLE001 - 判定件失灵按拒读收（fail-closed）。
        return None
    if not decision.allowed:
        return None
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


def _guarded_image_opener():  # -> urllib.request.OpenerDirector（局部导入，不在模块面）
    """图片取字节的护栏 opener（F-G4 收口，席位 S-FIX-NOTES-SSRF，2026-09-30）。

    为什么必须有它：消息里的图片 URL 是**任意成员可控**的输入，而默认 opener
    会自动跟随 30x、逐跳落点零复查——公网入口一跳指进 127.0.0.1:3001
    （SnowLuma 控制面）或 169.254.169.254（云元数据凭据面）时，内网连接
    **已经建成**，事后复查 `response.geturl()` 只拦得住字节回显、拦不住已发出
    的请求（SSRF + TOCTOU，两次解析之间还有 DNS rebind 窗口）。

    正解＝复用链上**唯一**的逐跳护栏形态
    ``link_parse.parsers.http_util._GuardedShortLinkRedirectHandler``：每一跳
    落点在**建连之前**先过中央 ``ssrf_guard.check_fetch_landing``（判据仍是中央
    ``downloader.check_download_url``，F-04「解析失败=拒绝」），命中内网/整型
    IP/畸形落点即抛 ParseHttpError 中止。本模块不自写第二套 URL 判据，口径与
    先趟过这条路的 ``vision_describe._guarded_image_opener``、
    ``media_archive._fetch_url_media`` 完全同源；跨 host 剥凭证的语义随父类继承。
    """
    import urllib.request

    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        _GuardedShortLinkRedirectHandler,
    )

    return urllib.request.build_opener(_GuardedShortLinkRedirectHandler())


def _fetch_image_bytes(
    url: str, max_bytes: int, *, refusal: list[str] | None = None
) -> bytes | None:
    """下载图片（SSRF 护栏：入口判定 + 逐跳落点**建连前**复查；限长；魔数后验）。

    - 入口先过中央咽喉 ``check_download_url``——拒绝发生在任何 socket 打开之前。
    - 取字节只走 ``_guarded_image_opener``（30x 每一跳先复查落点）。护栏拒绝
      （``RejectedUrlError`` / ``ParseHttpError``）与瞬时失败一样**都不出字节**，
      且绝不退回裸 urlopen 找补——第二条通路就是本函数要禁掉的东西（F-G4）。
    - ``refusal`` 是可选的出站登记册（调用方传空 list）：护栏拒下时按 "entry"
      /"landing" 记一枚，让能力层能把「我过不去的地址」与「一时拿不到的图」
      分开回话——前者要给人的出路，后者按既有语义静默跳过。登记细节不含 URL
      （签名地址不进消息与日志）。
    """
    import urllib.request

    from plugins.bot_unified_runtime.domains.files.sources.downloader import (
        RejectedUrlError,
        check_download_url,
    )
    from plugins.bot_unified_runtime.domains.link_parse.parsers.http_util import (
        ParseHttpError,
    )

    try:
        check_download_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": _IMAGE_UA})
        with _guarded_image_opener().open(request, timeout=10) as response:
            data = response.read(max_bytes + 1)
    except RejectedUrlError:
        if refusal is not None:
            refusal.append("entry")
        return None
    except ParseHttpError:  # 某一跳落点被护栏拒：连接从未朝内网发出。
        if refusal is not None:
            refusal.append("landing")
        return None
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


def _session_image_usage(chat_dir: Path) -> tuple[int, int]:
    """现算会话图片目录总量（张数, 字节数）——配额唯一真身=磁盘现状。"""
    count = 0
    total = 0
    try:
        entries = list(chat_dir.iterdir())
    except OSError:
        return 0, 0
    for entry in entries:
        try:
            if entry.is_file():
                count += 1
                total += entry.stat().st_size
        except OSError:
            continue  # 竞态删除/权限毛刺：不计数，也不炸整条链。
    return count, total


def _save_note_images(
    config: Any | None, message: IncomingMessage
) -> tuple[list[str], list[Path], bool, int]:
    """把消息里的图落盘；返回 (文件名列表, 绝对路径列表, 配额拒绝, 咽喉拒取的图数)。

    单图失败（拿不到字节/魔数不认识/写盘出错）仍按既有语义静默跳过；
    **护栏在建连之前拒下的地址不静默**（第四元，F-G4 收口 2026-09-30）：由能力层
    回一句人话给出路——拒取是安全边界，不是丢给她一句「记下了」瞒过去。
    会话聚合配额（T6-5）触顶是**诚实拒绝**：本次新写的图全部回滚删除、
    一条不收，第三元回 True，由能力层回人话短句——不静默截断半篇。
    """
    from hashlib import sha1

    root = _images_root(config)
    chat_dir = root / sha1(str(message.session_id).encode()).hexdigest()[:12]
    chat_dir.mkdir(parents=True, exist_ok=True)
    # 聚合配额闸（每消息限额之上）：落盘前按会话总量现算，触顶即整单拒绝。
    used_files, used_bytes = _session_image_usage(chat_dir)
    filenames: list[str] = []
    paths: list[Path] = []
    quota_blocked = False
    guard_refused = 0
    for url, local in _extract_image_segments(message):
        data = None
        refusal: list[str] = []
        if url:
            data = _fetch_image_bytes(url, _MAX_IMAGE_BYTES, refusal=refusal)
        if data is None and local:
            data = _read_local_image(local, _MAX_IMAGE_BYTES)
        if data is None:
            if refusal:
                guard_refused += 1  # 咽喉拒取 ≠ 一时拿不到：要给她一句交代。
            continue
        if _sniff_image_ext(data) == "":
            continue  # 拿到了字节但魔数不认识：不当图片收。
        if (
            used_files >= _MAX_SESSION_IMAGE_FILES
            or used_bytes + len(data) > _MAX_SESSION_IMAGE_BYTES
        ):
            quota_blocked = True
            break
        # 落点双查（写侧）：文件名只由 uuid + 魔数表里的扩展名拼成，
        # 拼不出 ../ 也换不出会话目录——URL 路径与消息内容都影响不到它。
        filename = f"{uuid.uuid4().hex[:16]}{_sniff_image_ext(data)}"
        target = (chat_dir / filename).resolve()
        if chat_dir.resolve() not in target.parents:
            continue  # 兜底复核：万一拼出盘外落点，宁可不收也不写出去。
        try:
            target.write_bytes(data)
        except OSError:
            continue
        used_files += 1
        used_bytes += len(data)
        filenames.append(filename)
        paths.append(target)
    if quota_blocked:
        # 回滚本单新图：拒绝就要真拒绝，不留「记了一半」的残篇与孤儿文件。
        for written in paths:
            try:
                written.unlink(missing_ok=True)
            except OSError:
                pass
        return [], [], True, 0
    return filenames, paths, False, guard_refused


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
    "- 「取消勾选 <事项>」或「<事项>还没做」：勾错了就说一声，我把勾拿回来\n"
    "- 「删笔记 N」：放下第 N 条\n"
    "内容里写「- [ ] 待办」的行，会被我当作待办来看。"
)


def _requester(message: IncomingMessage) -> str:
    """本轮归属人＝发言人（规范化去空白）；空串＝认不出是谁在说话。"""
    return str(message.sender_id or "").strip()


def _owned(note: Note | None, owner: str) -> Note | None:
    """判定层归属闸（照记忆硬闸的判定腿：`requester_id != subject_user_id` 即拒）。

    store 侧谓词已按归属人过滤，这里再比一次**记录自身**的 owner：这一层不看
    SQL 形态，防日后有人把谓词摘掉/退回会话域时整链静默敞开。不命中一律当
    「没有这一条」处理——不向请求人确认它是否存在，正文与配图都不外泄。
    """
    if note is None or not owner or str(note.user_id).strip() != owner:
        return None
    return note


_NO_REQUESTER_TEXT = (
    "抱歉，这一回我没认出是哪位在和我说话——笔记是要认人的，"
    "所以先不替你记下，也不给你翻别人的。"
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
            # T1 修复（S-FIX-ATK-NOTES2，2026-09-28）：笔记回执/列表/翻看正文与
            # images 配图都是给用户看的——SILENT_AUDIT 在 pipeline._complete 里
            # 等于不发（SKIPPED + 空正文，matcher 不收口还会落回聊天腿）。
            # 同 randpic 先例改法，IMMEDIATE 后正文与 images 才真到呈现层。
            send_policy=SendPolicy.IMMEDIATE,
            images=[{"file": str(item)} for item in (images or [])],
            audit_tags=["notes", *tags],
        )

    def _handle_undo(
        message: IncomingMessage,
        query: str,
        *,
        store: Any,
        explicit: bool,
        owner: str,
    ) -> CapabilityResult | None:
        """自然语言撤销勾选：在已勾条目里模糊匹配后回写 [ ]。

        匹配与歧义语义与 reminder 侧勾选完全同一套（resolve_todo_match：
        唯一高分=hit、并列=ambiguous 问人、未命中给最接近候选）。返回
        None 表示不承接（自然形态且本会话没有任何已勾条目——让位给后面
        分支/普通聊天；显式「取消勾选」形态则永不落空，给个交代）。

        候选池只扫**本轮归属人自己**的笔记（store 谓词带 owner＋下面的
        ``_owned`` 判定层）：别人的已勾条目不进候选，也就永远不会被
        陌生人的「X 还没做」改写到她的正文里。
        """
        from plugins.bot_unified_runtime.domains.schedule.store.reminders import (
            NEAR_MISS_FLOOR,
            match_todo_candidates,
            resolve_todo_match,
        )

        chat_id = message.session_id  # 会话隔离：只在本会话的笔记里找。
        # 撤销对象=已勾条目：开着的待办（勾了一部分）与整篇已完成的历史
        # 都要扫——「最后一件被勾完」的撤销恰恰发生在 done 笔记里。
        owners: list[tuple[int, int]] = []  # (note_id, 稳定条目号) 与 names 对齐
        names: list[str] = []
        for todo in store.list_notes(chat_id, user_id=owner, limit=50):
            if not _owned(todo, owner) or not todo.is_todo:
                continue
            for item_index, item_text in todo.todo_checked_items():
                owners.append((todo.note_id, item_index))
                names.append(item_text)
        if not names:
            if not explicit:
                return None  # 没有可撤销对象：让位，不抢普通聊天。
            return _result(
                message,
                "这个会话里还没有勾上过的事，先「做完 N」勾起来再说？",
                tags=["undo_no_candidates"],
            )
        outcome, indexes = resolve_todo_match(query, names)
        if outcome == "hit":
            note_id, item_index = owners[indexes[0]]
            before = store.get(note_id, chat_id, user_id=owner)
            was_done = bool(before and before.todo_state == "done")
            updated = store.mark_item_undone(
                note_id, chat_id, item_index, user_id=owner
            )
            if updated is None:
                # 并发窗口内笔记被删/改写：按未命中回话，不编造成功。
                return _result(
                    message,
                    f"这个会话里没有第 {note_id} 条笔记。「笔记列表」里看看？",
                    tags=["undo_miss"],
                )
            body = f"好，「{names[indexes[0]][:24]}」先放回来，不算它完成了。"
            if was_done:
                body += "这一篇也重新打开了。"
            remaining = len(updated.todo_open_items())
            if remaining:
                body += f"\n这篇还剩 {remaining} 件待办，不急，一件一件来。"
            return _result(message, body, tags=["undo_item"])
        if outcome == "ambiguous":
            lines = [f"- {names[index][:24]}" for index in indexes]
            return _result(
                message,
                "有几件事都对得上，要把哪一件改回没做？\n" + "\n".join(lines),
                tags=["undo_ambiguous"],
            )
        # 未命中：给最接近的已勾候选问一句（低于 NEAR_MISS_FLOOR 不打扰）。
        near = match_todo_candidates(query, names, min_score=NEAR_MISS_FLOOR)
        if near:
            best = names[near[0][0]][:24]
            return _result(
                message,
                f"这个会话里勾着的待办，没有能对上「{query}」的。你是指「{best}」吗？\n"
                "是的话再告诉我一声，我把那个勾拿掉。",
                tags=["undo_nearest"],
            )
        return _result(
            message,
            f"现在没有勾着能对上「{query}」的待办——也许还没勾过，或者已经放下了。",
            tags=["undo_no_match"],
        )

    def capability(message: IncomingMessage, _decision: Any) -> CapabilityResult:
        text = (message.plain_text or "").strip()
        chat_id = message.session_id
        store = build_notes_store(config)
        max_per_chat = int(getattr(config, "bot_notes_max_per_chat", 200) or 200)

        if _NOTES_BARE_RE.match(text):
            return _result(message, _USAGE_TEXT, tags=["usage"])

        # 归属闸第一层（判定腿）：认不出发言人就不碰任何一条笔记——读、删之外
        # 也拦住「记一条」，否则会落出一条谁也认领不回的无主行（fail-closed）。
        owner = _requester(message)
        if not owner:
            return _result(message, _NO_REQUESTER_TEXT, tags=["no_requester"])

        delete_match = _NOTES_DELETE_RE.search(text)
        if delete_match:
            note_id = int(next(g for g in delete_match.groups() if g))
            note = store.delete(note_id, chat_id, user_id=owner)
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

        # 撤销勾选（审查 A-14）：排在删除之后（删除词形优先级更高，且与
        # 撤销正则零交集），自然形态在本会话没有任何已勾条目时让位（返回
        # None 继续走后面分支），对齐 reminder 勾选面「无候选不抢话」的设计。
        undo_query = _extract_undo_query(text)
        if undo_query is not None:
            undo_explicit = _NOTES_UNDO_EXPLICIT_RE.search(text) is not None
            undo_result = _handle_undo(
                message, undo_query, store=store, explicit=undo_explicit, owner=owner
            )
            if undo_result is not None:
                return undo_result

        view_match = _NOTES_VIEW_RE.search(text)
        if view_match:
            note_id = int(next(g for g in view_match.groups() if g))
            note = _owned(store.get(note_id, chat_id, user_id=owner), owner)
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
            note = _owned(store.get(note_id, chat_id, user_id=owner), owner)
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
                store.mark_done(note_id, chat_id, user_id=owner)
                return _result(
                    message,
                    f"第 {note_id} 条已经完成过了。安心。",
                    tags=["done_repeat"],
                )
            first_index, first_text = open_items[0]
            updated = store.mark_item_done(
                note_id, chat_id, first_index, user_id=owner
            )
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
            notes = store.list_notes(chat_id, user_id=owner)
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
            if store.count_chat(chat_id, user_id=owner) >= max_per_chat:
                return _result(
                    message,
                    f"这个会话的笔记已经收满 {max_per_chat} 条了。先整理一下——"
                    "「删笔记 N」清掉不需要的，再记新的。",
                    tags=["limit_reached"],
                )
            image_names, _image_paths, quota_blocked, guard_refused = _save_note_images(
                config, message
            )
            if quota_blocked:
                # 聚合配额触顶（T6-5）：诚实拒绝整条带图笔记，不静默丢图谎称
                # 记好；人话短句点名上限与出路，数字与常量同源不手抄。
                return _result(
                    message,
                    f"这个会话的笔记图片存满了（上限 {_MAX_SESSION_IMAGE_FILES} 张 / "
                    f"约 {_MAX_SESSION_IMAGE_BYTES // (1024 * 1024)}MB），这条先没记上。"
                    "「删笔记 N」放下带旧图的，腾个地方再来记；或去掉图再记一次。",
                    tags=["image_quota_blocked"],
                )
            if image_names:
                content_md += "\n" + "\n".join(
                    f"![图片{index}]({name})"
                    for index, name in enumerate(image_names, start=1)
                )
            from plugins.bot_unified_runtime.domains.chat_reply.security.injection import (
                neutralize_internal_markers,
            )

            note = store.add(
                # 归属人＝本轮发言人（规范化后的形态，与谓词比的是同一个串）。
                user_id=owner,
                chat_id=chat_id,
                # T3 修复（S-FIX-ATK-NOTES2，2026-09-28）：入库即净——「笔记 看 N」
                # 会把 content_md 全文以她的名义复读，内部边界标记原样入库=可执行
                # 标记重放面。先消毒后截断：截断只会切短已全角化的安全形态，不可能
                # 从截断残片里重新拼出半枚可执行标记。唯一真身正则，不开第二套。
                content_md=neutralize_internal_markers(content_md)[:4000],
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
            # 咽喉在建连前拒下的地址（F-G4）：笔记照记（文字是她自己的话），
            # 但缺的那张图要如实说清并给出路——不拿「安稳收好」把拒绝瞒过去。
            # 文案不指责任何人，也不复述地址（签名 URL 不进消息）。
            refusal_line = (
                f"\n只是这条里有 {guard_refused} 张图的地址我没去取——"
                "我只能走公网的 http/https 链接，本机与内网那类地址一律不碰。"
                "想把图一起留下：把图片直接发给我，再记一次就好。"
                if guard_refused
                else ""
            )
            tags = ["added", "with_images"] if image_names else ["added"]
            if guard_refused:
                tags.append("image_guard_refused")
            return _result(
                message,
                f"记下了，第 {note.note_id} 条，安稳收好{suffix}。"
                f"要看的时候说「笔记 看 {note.note_id}」。{refusal_line}",
                tags=tags,
            )

        return _result(message, _USAGE_TEXT, tags=["usage"])

    return capability


__all__ = [
    "build_notes_capability",
    "is_notes_command",
    "note_display_text",
    "note_image_files",
]
