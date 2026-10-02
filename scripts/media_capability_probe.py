"""S4 媒体能力实测探针（守岸人 bot 媒体能力实测波）。

三段式离线核账 + 真发前置闸门 + 真发计划（默认 DRY-RUN，零外发零网络下载）。

用法：
    python scripts/media_capability_probe.py            # 离线矩阵 + 闸门 + 计划(DRY)
    python scripts/media_capability_probe.py --execute  # 仅当四条闸门全过才真发

纪律（席位硬约束）：
  * 复用中央出口：QQ 出站＝sender/onebot.build_onebot_message_segments；
    TG 出站＝sender/nonebot（含 send_photo/send_voice/send_audio/send_to）；
    文件判定＝safety_exec/paths.check_sendable（file_gateway 咽喉）。禁第二通路。
  * 真发一次只发一条、逐条核对回执；request_id 一律带 `probe:` 前缀。
  * 下载全 MockTransport：本脚本不发任何网络请求。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
RT = REPO.parent / "ChatBot_Runtime" / "data"
TMP = Path(os.environ.get("TEMP", str(REPO / ".tmp-probe"))) / "cb-s4" / "media_probe"
TMP.mkdir(parents=True, exist_ok=True)

# ---- 复用被测真身（leaf import，不触发 NoneBot 注册）----
from plugins.bot_unified_runtime import (
    contains_audio_message_segments as has_audio,
)
from plugins.bot_unified_runtime import (
    contains_forward_message_segments as has_forward,
)
from plugins.bot_unified_runtime import (
    contains_visual_message_segments as has_visual,
)
from plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context import (
    normalize_message_segments,
)
from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
    PrivacyLevel,
    RenderedOutput,
    SendPolicy,
    SendRequest,
    SessionType,
)
from plugins.bot_unified_runtime.domains.core.safety_exec.paths import check_sendable
from plugins.bot_unified_runtime.domains.files.sources.file_reader import (
    read_supported_file,
)
from plugins.bot_unified_runtime.domains.transport.sender.onebot import (
    build_onebot_message_segments,
)

QQ_IMG = str(RT / "meme_library" / "009fce06939ade133fce1651d7f1f3f1.jpg")
QQ_GIF = str(RT / "meme_library" / "01ec5606f62af3b1c70fc1c80e1997ce.gif")
CARD_PNG = str(RT / "cards" / "affinity_3cb3e4e7e6f9.png")
AUDIO_MP3 = str(RT / "music" / "song_1179d2c54cc7.mp3")
VIDEO_MP4 = str(RT / "downloads" / "BV153bE6SEWq.mp4")
# ---- S4b 补测件（允许根真身＝workspace + RT/data，见 run_outbound_matrix 的 policy 打印）----
ZZ_DIR = RT / "downloads"
ZZ_DOCX = str(ZZ_DIR / "zzprobe_s4b.docx")
ZZ_PDF = str(ZZ_DIR / "zzprobe_s4b.pdf")
REPO_PY = str(REPO / "bot.py")
REPO_JSON = str(REPO / "scripts" / "chatbot-tasks.json")
# TG 私聊 chat id：闸门④现读所得（真发前由 gate_tg_chat_id 覆盖），缺省空＝不发。
TG_CHAT_ID = ""


def hr(title: str) -> None:
    print("\n" + "=" * 12 + " " + title + " " + "=" * 12)


def seg(kind: str, **data) -> dict:
    return {"type": kind, "data": data}


# =========================================================================
# 第 0 段：真发前置闸门
# =========================================================================
def gate_listening_ports() -> tuple[bool, list[str]]:
    """① 8080 与 3001 均在监听。用 socket 直连判活（避开 netstat 子进程页文件坑）。"""
    import socket

    def probe(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                return True
        except OSError:
            return False

    p8080, p3001 = probe(8080), probe(3001)
    ok = p8080 and p3001
    notes = [f"socket connect 127.0.0.1:8080={p8080} 127.0.0.1:3001={p3001}"]
    # 补充取证：netstat 读数（若可用）证明二者 PID 互连（bot↔SnowLuma）。
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10, check=False).stdout
        est = [ln.strip() for ln in out.splitlines() if "ESTABLISHED" in ln and ":3001" in ln and "127.0.0.1" in ln]
        notes.append(f"netstat 3001<->bot ESTABLISHED={len(est)} {est[:1]}")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"netstat 取证跳过(transient): {type(exc).__name__}")
    return ok, notes


def gate_whitelist(qq: str) -> tuple[bool, list[str]]:
    """② qq 落白名单等价（超管）且不在 BLACK 系。私聊天然放行（gate.py:352）。"""
    env = REPO / ".env"
    txt = env.read_text(encoding="utf-8", errors="replace") if env.exists() else ""
    def _list(key: str) -> list[str]:
        m = re.search(rf"^{key}=(.*)$", txt, re.MULTILINE)
        return re.findall(r"\d+", m.group(1)) if m else []
    super_adm = _list("BOT_SUPER_ADMIN_USER_IDS")
    blocked = _list("BOT_BLOCKED_USER_IDS")
    grp_black = _list("BOT_CONTENT_ROUTE_GROUP_BLACKLIST")
    priv_black = _list("BOT_CONTENT_ROUTE_PRIVATE_BLACKLIST")
    is_admin = qq in super_adm
    in_black = qq in blocked or qq in grp_black or qq in priv_black
    ok = is_admin and not in_black
    notes = [
        f"super_admin 命中={is_admin}",
        f"在 blocked/blacklist={in_black} (blocked={blocked} grp_black={grp_black} priv_black={priv_black})",
        "私聊 gate.py:352=有问必回(角色/风险除外)，群白名单不适用",
    ]
    return ok, notes


def gate_tg_chat_id() -> tuple[bool, str, list[str]]:
    """④ delivery_receipts 现读 2026-10-02 两条 transport=telegram/state=sent。"""
    db = RT / "wuwa_receipts.sqlite3"
    notes: list[str] = []
    if not db.exists():
        return False, "", [f"库不存在 {db}"]
    # 关键：不可用 immutable=1，否则跳过 WAL ⇒ 读到假缺席（本席踩点已证）。
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    transports = con.execute(
        "select transport,count(*) from delivery_receipts group by transport"
    ).fetchall()
    notes.append(f"distinct transport={transports}")
    notes.append(f"total rows={con.execute('select count(*) from delivery_receipts').fetchone()[0]} (ring cap=1000, receipts.py:70)")
    tg = con.execute(
        "select request_id,state,substr(created_at,1,10) from delivery_receipts "
        "where transport='telegram' and state='sent' order by created_at desc limit 5"
    ).fetchall()
    con.close()
    notes.append(f"telegram/sent 命中={tg}")
    if not tg:
        # 兜底取证：WAL/主库里 telegram 记录最后停留在哪天（已被 ring 淘汰=读不到）。
        raw = b""
        for part in (db, db.with_name(db.name + "-wal")):
            if part.exists():
                raw += part.read_bytes()
        dates = re.findall(rb"sent\x00?telegram\d*\x00?sent([0-9T:.+-]{10,})", raw)
        notes.append(f"stale telegram/sent 日期痕迹(已淘汰)={sorted({d.decode(errors='replace')[:10] for d in dates})}")
        return False, "", notes
    # delivery_receipts 无 chat 列 ⇒ 经权威 send_requests.target_id 现读（非猜、非改配置）。
    qdb = RT / "wuwa_send_queue.sqlite3"
    chat_id = ""
    if qdb.exists():
        qc = sqlite3.connect(f"file:{qdb}?mode=ro", uri=True)
        for rid, _state, _day in tg:
            jrow = qc.execute("select request_json from send_requests where request_id=?", (rid,)).fetchone()
            if not jrow:
                continue
            j = json.loads(jrow[0])
            notes.append(f"send_requests[{rid}] adapter={j.get('adapter')} scope={j.get('target_scope')} target_id={j.get('target_id')}")
            if j.get("adapter") == "telegram" and j.get("target_scope") == "private":
                chat_id = str(j.get("target_id") or "")
        qc.close()
    notes.append(f"⇒ TG 私聊 chat id 现读={chat_id or '(读不到私聊腿)'}")
    return (bool(chat_id)), chat_id, notes


# =========================================================================
# 第 1 段：入站归一矩阵（离线，零网络）
# =========================================================================
def run_inbound_matrix() -> list[dict]:
    hr("段1 入站归一矩阵（normalize + 准入集合）")
    cases = [
        ("文字", "qq", [seg("text", text="今天天气不错")]),
        ("图文混排", "qq", [seg("text", text="看这张"), seg("image", file=QQ_IMG)]),
        ("静态表情 face", "qq", [seg("face", id="178")]),
        ("mface 商城表情", "qq", [seg("mface", name="点赞")]),
        ("图片 image", "qq", [seg("image", file=QQ_IMG)]),
        ("动图 animation(GIF)", "qq", [seg("animation", file=QQ_GIF)]),
        ("语音 record", "qq", [seg("record", file=AUDIO_MP3)]),
        ("视频 video", "qq", [seg("video", file=VIDEO_MP4)]),
        ("引用 quote", "qq", [seg("quote", text="被引用的那句")]),
        ("合并转发 forward", "qq", [seg("forward", messages=[seg("text", text="转发正文")])]),
        ("纯 file 段", "qq", [seg("file", file=QQ_IMG, name="a.jpg")]),
        ("node 段(合并壳)", "qq", [seg("node", content="x")]),
        ("json 段(卡片)", "qq", [seg("json", data='{"app":"qq"}')]),
        ("xml 段", "qq", [seg("xml", data="<msg/>")]),
        ("music 段(点歌卡)", "qq", [seg("music", type="1", id="123")]),
        ("TG photo", "telegram", [seg("photo", file_id="F1")]),
        ("TG sticker", "telegram", [seg("sticker", file_id="S1")]),
        ("TG voice", "telegram", [seg("voice", file_id="V1")]),
        ("TG audio", "telegram", [seg("audio", file_id="A1")]),
        ("TG video", "telegram", [seg("video", file_id="VI1")]),
        ("TG document", "telegram", [seg("file", file_id="D1", name="doc.pdf")]),
    ]
    rows: list[dict] = []
    for label, plat, raw in cases:
        nm = normalize_message_segments(raw)
        pt = nm.plain_text
        # 文本面是否「读得出这个媒体」：媒体段应产出 [图片]/[语音] 类标签
        readable = bool(pt.strip())
        admission = {
            "visual": has_visual(raw),
            "audio": has_audio(raw),
            "forward": has_forward(raw),
        }
        # 纯媒体(无 text 段)时的准入：只有被 visual/audio/forward 认领才不被路由 IGNORE
        only_media = all(s["type"] not in {"text", "quote"} for s in raw)
        passes_inbound = admission["visual"] or admission["audio"] or admission["forward"] or not only_media
        rows.append({
            "label": label, "plat": plat, "plain_text": pt[:40],
            "text面可读": readable, "准入": admission, "入站可达handler": passes_inbound,
        })
        flag = "OK" if passes_inbound else "IGNORE"
        print(f"  [{flag:6}] {label:22} plain_text='{pt[:24]}' 视觉={admission['visual']} 音频={admission['audio']} 转发={admission['forward']}")
    return rows


def run_doc_parsing() -> list[dict]:
    hr("段1b file_reader 文档解析（真实样本）")
    # 仓库真实文本/代码样本
    py_sample = str(REPO / "bot.py")
    md_sample = str(REPO / "AGENTS.md")
    json_sample = str(REPO / "scripts" / "chatbot-tasks.json")
    # 生成真实 OOXML / PDF 样本到 TMP（不进源码树）
    docx = TMP / "sample.docx"
    xlsx = TMP / "sample.xlsx"
    pptx = TMP / "sample.pptx"
    pdf = TMP / "sample.pdf"
    try:
        import docx  # python-docx
        d = docx.Document()
        d.add_paragraph("守岸人 S4 探针文档样本段落。")
        d.save(docx)
    except Exception as exc:  # noqa: BLE001
        print("  docx 生成失败", exc)
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active["A1"] = "守岸人表格"
        wb.active["B1"] = 42
        wb.save(xlsx)
    except Exception as exc:  # noqa: BLE001
        print("  xlsx 生成失败", exc)
    try:
        from pptx import Presentation
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = "守岸人演示"
        prs.save(pptx)
    except Exception as exc:  # noqa: BLE001
        print("  pptx 生成失败", exc)
    _write_minimal_pdf(pdf, "Shorekeeper S4 pdf sample")

    samples = [
        ("py 代码", py_sample), ("md 文档", md_sample), ("json", json_sample),
        ("docx", str(docx)), ("xlsx", str(xlsx)), ("pptx", str(pptx)), ("pdf", str(pdf)),
        (".xls(旧OLE2)", str(TMP / "nope.xls")),  # 结构性不支持：不存在也演示降级
    ]
    rows = []
    for label, path in samples:
        res = read_supported_file(path)
        excerpt = (res.text or "").strip().replace("\n", " ")[:30]
        meta = res.metadata or {}
        status = meta.get("status", "ok" if res.text else "empty")
        print(f"  {label:14} kind={res.kind:10} textLen={len(res.text or ''):6} status={status} '{excerpt}'")
        rows.append({"label": label, "kind": res.kind, "len": len(res.text or ""), "status": status})
    return rows


def _write_minimal_pdf(path: Path, text: str) -> None:
    """手写最小合法 PDF（venv 无 reportlab，口径同 test_file_reader_parse_safety）。"""
    content = b"BT /F1 12 Tf 20 750 Td (" + text.encode("latin-1", "replace") + b") Tj ET"
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = []
    for o in objs:
        offsets.append(buf.tell())
        buf.write(o)
    xref = buf.tell()
    buf.write(b"xref\n0 6\n0000000000 65535 f \n")
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF")
    path.write_bytes(buf.getvalue())


# =========================================================================
# 第 2 段：TG 专辑 / 评论区 raw 字段证据（读侧硬答案）
# =========================================================================
def run_tg_album_thread_evidence() -> None:
    hr("段2 TG 拼格专辑(media_group_id) / 评论区(message_thread_id) 读侧证据")
    # (a) 平台侧：适配器 Message 模型确实带这三枚字段 => 平台送得出来
    import inspect

    from nonebot.adapters.telegram import model as tgmodel
    msrc = inspect.getsource(tgmodel.Message)
    for f in ("media_group_id", "message_thread_id", "is_topic_message"):
        present = f in msrc
        print(f"  [平台] Message.{f} 在册={present}")

    # (b) 我方消费：整包源码里这几枚字段的读写计数
    pkg = REPO / "plugins" / "bot_unified_runtime"
    py_files = [p for p in pkg.rglob("*.py")]
    reads: dict[str, list[str]] = {"media_group_id": [], "message_thread_id": [], "is_topic_message": [], "thread_id": []}
    for p in py_files:
        if "__pycache__" in str(p):
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        for i, ln in enumerate(body.splitlines(), 1):
            for key, hits in reads.items():
                if re.search(rf"\b{key}\b", ln):
                    hits.append(f"{p.relative_to(REPO)}:{i}: {ln.strip()[:80]}")

    # (c) 归一演示：一条 photo-list（模拟专辑拆成的多张图）落进 normalize => 各自独立 [图片]，无专辑聚合语义
    album_like = [seg("photo", file_id="P1"), seg("photo", file_id="P2"), seg("photo", file_id="P3")]
    nm = normalize_message_segments(album_like)
    print(f"  [归一] 3 张相册图 -> plain_text='{nm.plain_text}' segments={len(nm.segments)}  (无 media_group 聚合)")

    # (d) 结论：字段是否进入 IncomingMessage、是否有消费者
    for key in ("media_group_id", "message_thread_id", "is_topic_message", "thread_id"):
        locs = reads[key]
        print(f"  [消费] {key}: 命中 {len(locs)} 处")
        for l in locs[:6]:
            print(f"        {l}")


# =========================================================================
# 第 3 段：出站构造矩阵（离线，DRY，零发送）
# =========================================================================
def _make_send_request(parts: list[dict], text_fallback: str, *, adapter: str, platform_scope=SessionType.PRIVATE) -> SendRequest:
    return SendRequest(
        request_id="probe:dry", session_id="private:probe", target_scope=platform_scope,
        target_id="1722380002", capability_id="probe.media",
        content=RenderedOutput(request_id="probe:dry", content_type="mixed",
                               content_ref={"parts": parts}, text_fallback=text_fallback,
                               privacy_level=PrivacyLevel.PERSONAL),
        send_policy=SendPolicy.IMMEDIATE, priority="normal", max_messages=1,
        dedupe_key="probe:dry", cooldown_key="probe:dry",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default", adapter=adapter, bot_id="3958874605" if adapter == "onebot" else "8887340775",
    )


def run_outbound_matrix() -> None:
    hr("段3 出站 payload 构造矩阵（QQ=onebot 构造器；TG=nonebot 方法面）")
    # QQ：build_onebot_message_segments（复用中央出口，不发送）
    qq_parts = [
        ("文字", [{"type": "text", "text": "你好"}]),
        ("图片", [{"type": "image", "file": QQ_IMG}]),
        ("动图GIF", [{"type": "image", "file": QQ_GIF}]),
        ("表情包mface", [{"type": "mface", "name": "点赞", "url": "https://x/1.png"}]),
        ("语音record", [{"type": "record", "file": AUDIO_MP3}]),
        ("视频video", [{"type": "video", "file": VIDEO_MP4}]),
        ("文件docx", [{"type": "file", "file": str(TMP / 'sample.docx')}]),
        ("文件pdf", [{"type": "file", "file": str(TMP / 'sample.pdf')}]),
        ("文件py", [{"type": "file", "file": str(REPO / 'bot.py')}]),
        ("music卡", [{"type": "music", "music_type": "1", "music_id": "123"}]),
        ("引用回复at+reply", [{"type": "at", "qq": "1722380002"}, {"type": "text", "text": "回复你"}]),
    ]
    print("  [QQ 出站构造]  (type -> 构造出的段；None=该 part 被丢弃/无通路)")
    for label, parts in qq_parts:
        req = _make_send_request(parts, parts[0].get("text", "") if parts[0]["type"] == "text" else label, adapter="onebot")
        built = build_onebot_message_segments(req)
        types = [s.get("type") for s in built]
        print(f"    {label:16} -> {types}")

    # TG：nonebot 真实调用面（从源码取证据，不伪造 API）
    from plugins.bot_unified_runtime.domains.transport.sender import nonebot as tg
    src = Path(tg.__file__).read_text(encoding="utf-8")
    print("  [TG 出站方法面]  实际在 _send() 里被调用的 send_*：")
    for m in sorted(set(re.findall(r"getattr\(bot, \"(send_[a-z_]+)\"", src))):
        print(f"    {m}: 在册且被 getattr 调用")
    print("  [TG 缺失方法面]  结构性无通路（源码零 getattr）：")
    for m in ("send_video", "send_sticker", "send_animation"):
        same_family = f"send_{m.split('_')[-1]}"
        hit_getattr = f'"{m}"' in src
        print(f"    {m}: 同族名在册={same_family in src} getattr 调用点={hit_getattr}")

    # file_gateway 判定门（check_sendable）：允许根内 vs 仓外
    print("  [文件判定门 check_sendable]  路径域裁决：")
    for label, path in [("允许根内(RT卡片PNG)", CARD_PNG), ("源码树py", str(REPO / 'bot.py')), ("仓外TMP", str(TMP / 'sample.pdf'))]:
        dec = check_sendable(path)
        print(f"    {label:22} verdict={dec.verdict} reason={dec.reason_code}")


# =========================================================================
# 第 4 段：真发计划（默认 DRY；三闸门全过 + --execute 才真发）
# =========================================================================
def _submit_and_wait(queue, req: SendRequest, *, timeout_s: int = 95) -> dict:
    """入队一条 → 轮询三表现读回执（不信返回值）。禁第二通路：只 submit，投递交在线 bot。"""
    submitted = queue.submit(req)
    rid = req.request_id
    rtq = RT / "wuwa_send_queue.sqlite3"
    rtr = RT / "wuwa_receipts.sqlite3"
    start = time.time()
    final = {"request_id": rid, "submit_state": getattr(submitted.state, "value", str(submitted.state)),
             "queue_state": None, "receipt": None, "part_states": None, "elapsed_s": 0}
    while time.time() - start < timeout_s:
        q = sqlite3.connect(f"file:{rtq}?mode=ro", uri=True)
        row = q.execute("select state from send_requests where request_id=?", (rid,)).fetchone()
        parts = q.execute("select part_index,state,last_error_kind from send_request_parts where request_id=? order by part_index", (rid,)).fetchall()
        q.close()
        r = sqlite3.connect(f"file:{rtr}?mode=ro", uri=True)
        rec = r.execute("select state,transport,substr(created_at,1,19) from delivery_receipts where request_id=? order by created_at desc limit 3", (rid,)).fetchall()
        r.close()
        final["queue_state"] = row[0] if row else None
        final["part_states"] = parts
        final["receipt"] = rec
        final["elapsed_s"] = round(time.time() - start, 1)
        if row and row[0] in {"sent", "failed_final"}:
            break
        time.sleep(5)
    return final


def _build_item(platform: str, label: str, parts: list[dict], text_fallback: str, *, idx: int) -> SendRequest:
    # 复用中央出口：request_id/dedupe/cooldown 全带 probe 前缀（回滚 SQL 按前缀删）。
    rid = f"probe:{platform}:{idx:02d}:{label}"
    if platform == "qq":
        adapter, bot_id, target, scope = "nonebot", "3958874605", "1722380002", SessionType.PRIVATE
    else:
        # TG 私聊号＝闸门④现读所得（6393538508），非猜。
        adapter, bot_id, target, scope = "telegram", "8887340775", TG_CHAT_ID, SessionType.PRIVATE
    return SendRequest(
        request_id=rid, session_id=target, target_scope=scope, target_id=target,
        capability_id="probe.media",
        content=RenderedOutput(request_id=rid, content_type="mixed",
                               content_ref={"parts": parts}, text_fallback=text_fallback,
                               privacy_level=PrivacyLevel.PERSONAL),
        send_policy=SendPolicy.IMMEDIATE, priority="high", max_messages=0,
        dedupe_key=rid, cooldown_key=rid,
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default", adapter=adapter, bot_id=bot_id,
        audit_tags=["probe", f"probe:{platform}"],
    )


def execute_real_send_sequence(only: str | None = None) -> None:
    """canary 优先、逐条核回执再发下一条；任一条未被在线 bot 领取即停手不堆。

    only: 'qq' / 'tg' / None(全部)。已 sent 的同 rid 会被队列 dedupe 跳过＝不重复发。
    """
    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        build_send_queue,
    )
    from scripts.e2e_acceptance import load_smoke_config
    cfg = load_smoke_config(None)
    queue = build_send_queue(cfg, audit_logger=InMemoryAuditLogger())
    hr("段4-execute 真发（逐条，canary 优先）")
    qq_items = [
        ("text", [{"type": "text", "text": "[S4 媒体能力实测探针] 澜汐你好，这是一条真发探针文字，收到即证明 QQ 出站通路在线。"}], "探针文字"),
        ("image", [{"type": "image", "file": QQ_IMG}], "图片"),
        ("mface", [{"type": "mface", "name": "点赞", "url": "https://avatars.stickers.qq.com/x.png"}], "表情包mface"),
        ("record", [{"type": "record", "file": AUDIO_MP3}], "语音record"),
        ("video", [{"type": "video", "file": VIDEO_MP4}], "视频video"),
        ("file", [{"type": "file", "file": CARD_PNG, "name": "probe.png"}], "文件file"),
    ]
    tg_items = [
        ("text", [{"type": "text", "text": "[S4 探针] Telegram 侧文字真发核对。"}], "文字"),
        ("photo", [{"type": "image", "file": QQ_IMG}], "图片sendPhoto"),
        ("audio", [{"type": "record", "file": AUDIO_MP3}], "音频sendVoice/Audio"),
        ("file", [{"type": "file", "file": CARD_PNG, "name": "probe.png"}], "文件sendDocument"),
    ]
    plan = [("qq", qq_items), ("tg", tg_items)]
    if only:
        plan = [(plat, items) for plat, items in plan if plat == only]
    for platform, items in plan:
        for idx, (label, parts, name) in enumerate(items, 1):
            req = _build_item(platform, label, parts, name, idx=idx)
            ts = datetime.now(timezone.utc).isoformat()
            print(f"\n  → [{platform}#{idx:02d}] type={label} target={req.target_id} 时刻={ts} rid={req.request_id}")
            res = _submit_and_wait(queue, req, timeout_s=240)
            print(f"     submit_state={res['submit_state']} 队列={res['queue_state']} 用时={res['elapsed_s']}s")
            print(f"     part_states={res['part_states']}")
            print(f"     回执原文={res['receipt']}")
            if res["queue_state"] not in {"sent", "failed_final"}:
                print("     ⚠ 未被在线 bot 领取/未终态 ⇒ 依纪律停后续堆发。")
                return


def _pick_under(max_bytes: int = 2 * 1024 * 1024 - 1) -> str:
    """TG 文档腿 2MiB 结构门（file_gateway.py:72 定义、:738 执法）的对照件：现读一枚在场且 <2MiB 的文档。"""
    for sub in ("cards", "avatar", "food_images", "meme_library"):
        for cand in sorted((RT / sub).glob("*.*")):
            try:
                if cand.is_file() and 0 < cand.stat().st_size < max_bytes:
                    return str(cand)
            except OSError:
                continue
    return ""


def _native_emoji_id() -> str:
    """从表情册现读一枚真 native_emoji_id（mface 段的唯一合法形状，32 位 hex）。

    绝不自己拼 id（onebot.py:_mface_segment 的判尺抄自 SnowLuma bundle）。读不到＝返回空 ⇒ 跳过该腿。
    """
    for db in sorted(RT.glob("*meme*.sqlite3")) + sorted(RT.glob("*.sqlite3")):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            tables = [t[0] for t in con.execute("select name from sqlite_master where type='table'")]
            for t in tables:
                cols = [c[1] for c in con.execute(f"pragma table_info({t})")]
                if not any("emoji" in c for c in cols):
                    continue
                idcol = next(c for c in cols if "emoji" in c)
                sql = f'select "{idcol}" from "{t}" where length("{idcol}") > 2 limit 3'
                rows = con.execute(sql).fetchall()
                if rows:
                    print(f"  [mface 取证] {db.name}.{t}[{idcol}] {rows}")
                    return str(rows[0][0])
        except (sqlite3.Error, StopIteration):
            pass
        finally:
            con.close()
    return ""


def execute_supplement_sequence(only: str | None = None) -> None:
    """S4b 补测三格尾巴：QQ 文件面四类 + GIF 独立腿（image/file/mface 三形）+ TG 文档 2MiB 对照腿。

    rid 前缀一律 probe:，idx 从 20 起 ⇒ 绝不与 S4 已 sent 的 rid 同形（同形也只被 dedupe 跳过，不重复骚扰）。
    """
    from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
    from plugins.bot_unified_runtime.domains.transport.sender.queue import (
        build_send_queue,
    )
    from scripts.e2e_acceptance import load_smoke_config

    cfg = load_smoke_config(None)
    queue = build_send_queue(cfg, audit_logger=InMemoryAuditLogger())
    hr("段4-s4b 补测真发（逐条发、逐条核三表）")
    qq_items: list[tuple[str, list[dict], str]] = [
        ("gif-image", [{"type": "image", "file": QQ_GIF}], "GIF走image段"),
        ("gif-file", [{"type": "file", "file": QQ_GIF, "name": "probe_gif_s4b.gif"}], "GIF走file段"),
        ("docx", [{"type": "file", "file": ZZ_DOCX, "name": "zzprobe_s4b.docx"}], "文档docx"),
        ("pdf", [{"type": "file", "file": ZZ_PDF, "name": "zzprobe_s4b.pdf"}], "文档pdf"),
        ("py", [{"type": "file", "file": REPO_PY, "name": "probe_s4b_bot.py"}], "文档py"),
        ("json", [{"type": "file", "file": REPO_JSON, "name": "probe_s4b_tasks.json"}], "文档json"),
    ]
    emoji_id = _native_emoji_id()
    if emoji_id:
        qq_items.insert(2, ("mface-native", [{"type": "mface", "emoji_id": emoji_id,
                                              "summary": "probe-s4b"}], "mface带原生id"))
    tg_items: list[tuple[str, list[dict], str]] = []
    small = _pick_under()
    if small:
        tg_items.append(("file-small", [{"type": "file", "file": small,
                                         "name": Path(small).name}], "TG文档低于2MiB对照"))
    plan: list[tuple[str, list[tuple[str, list[dict], str]]]] = [("qq", qq_items), ("tg", tg_items)]
    if only:
        plan = [(plat, items) for plat, items in plan if plat == only]
    for platform, items in plan:
        for idx, (label, parts, name) in enumerate(items, 20):
            src = str(parts[0].get("file") or "")
            if src and not Path(src).is_file():
                print(f"     [SKIP] {label} 源件不在场：{src}")
                continue
            req = _build_item(platform, label, parts, name, idx=idx)
            ts = datetime.now(timezone.utc).isoformat()
            print(f"\n  -> [{platform}#{idx:02d}] type={label} target={req.target_id} 时刻={ts} rid={req.request_id}")
            res = _submit_and_wait(queue, req, timeout_s=180)
            print(f"     submit_state={res['submit_state']} 队列={res['queue_state']} 用时={res['elapsed_s']}s")
            print(f"     part_states={res['part_states']}")
            print(f"     回执原文={res['receipt']}")
            if res["queue_state"] not in {"sent", "failed_final"}:
                print("     未终态 => 依纪律停后续堆发。")
                return


def plan_and_maybe_send(execute: bool, only: str | None = None,
                        *, supplement: bool = False) -> None:
    hr("段4 真发前置闸门 + 真发计划")
    g1, n1 = gate_listening_ports()
    g2, n2 = gate_whitelist("1722380002")
    g3 = True  # 本席走独立探针（e2e_acceptance 只吃 --target-group、platform=qq 硬编码:350、无媒体专项）
    n3 = ["platform='qq' 在 e2e_acceptance.py:350 硬编码、只 --target-group、38 项无 record/file/gif/引用 => 本席独立探针承接"]
    g4, chat_id, n4 = gate_tg_chat_id()
    if g4:
        globals()["TG_CHAT_ID"] = chat_id

    for name, ok, notes in [("① 端口8080/3001 LISTENING+互连", g1, n1),
                            ("② 1722380002 白名单(超管)且不在BLACK", g2, n2),
                            ("③ 私聊号=>独立探针承接", g3, n3),
                            ("④ TG chat id 从 delivery_receipts 现读", g4, n4)]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        for nl in notes:
            print(f"         - {nl}")

    all_pass = g1 and g2 and g3 and g4
    print(f"\n  四条闸门整体: {'全过' if all_pass else '存在不过 => 依纪律一条都不发'}")

    qq_seq = ["纯文字", "图片", "动图GIF", "表情包mface", "语音record", "视频",
              "文件docx", "文件pdf", "文件py", "合并转发", "引用回复"]
    tg_seq = ["文字", "图片", "音频sendAudio", "文件(<=2MiB)", "贴纸/视频(结构性无通路=以证据出)"]

    print("\n  [真发计划 probe: 前缀 request_id，DRY 阶段仅登记，不执行]")
    for i, t in enumerate(qq_seq, 1):
        print(f"    QQ#{i:02d} {t:12} request_id=probe:qq:{i:02d}:{t}")
    for i, t in enumerate(tg_seq, 1):
        print(f"    TG#{i:02d} {t:22} request_id=probe:tg:{i:02d}")

    if not execute:
        print("\n  DRY-RUN：未传 --execute，不发送。")
        return
    if not all_pass:
        print("\n  闸门未全过（尤其 ④ 读不到 TG 私聊 chat id），依席位纪律停发。")
        return
    # 真发＝写共享队列交在线 bot 投递（中央出口，不重启 bot、不开第二连接）。
    if supplement:
        execute_supplement_sequence(only=only)
    else:
        execute_real_send_sequence(only=only)


def print_rollback_sql() -> None:
    hr("段4b 污染面回滚 SQL（打印，绝不执行）")
    print("""
-- 全部真发 request_id 带 probe: 前缀 tag。回滚＝按前缀删（仅当确有真发落库）。
-- 队列：
DELETE FROM send_request_parts WHERE request_id LIKE 'probe:%';
DELETE FROM send_requests      WHERE request_id LIKE 'probe:%';
-- 回执：
DELETE FROM delivery_receipts  WHERE request_id LIKE 'probe:%';
-- 会话/记忆/好感/文风/怪癖（真发才会写的旁路面）：
--   conversation_turns / memory_facts / user_affinity / user_reply_policy / persona_quirks
-- 这些表无 request_id 列，按 session_id='1722380002' + 时刻窗（本次 probe 起始时间戳）过滤，
-- 或按 persona_quirks.status='pending_review' 且 created_at>=<probe_start_utc> 删提案。
-- 好感度：affinity 按消息累计，无逐条回滚位 => 需人工把该号档位回调，或按 delta 记录回退。
""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真发（仅当四条闸门全过）")
    ap.add_argument("--supplement", action="store_true",
                    help="S4b 补测三格尾巴：QQ 文件面四类 + GIF 独立腿 + TG 文档 2MiB 对照腿")
    ap.add_argument("--only", choices=["qq", "tg"], default=None, help="只真发该平台")
    args = ap.parse_args()
    print(f"S4 媒体能力实测探针  @ {datetime.now(timezone.utc).isoformat()}")
    print(f"REPO={REPO}  RT={RT}  TMP={TMP}")
    run_inbound_matrix()
    run_doc_parsing()
    run_tg_album_thread_evidence()
    run_outbound_matrix()
    plan_and_maybe_send(args.execute, only=args.only, supplement=args.supplement)
    print_rollback_sql()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
