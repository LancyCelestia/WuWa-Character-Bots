"""下载件落点门回归（席 B1，2026-10-02 · P3.9「yt-dlp 落盘名未消毒」消费侧半程）。

被检对象：``plugins/bot_unified_runtime/domains/files/capabilities/download.py``。
判据真身：``domains/media/path_gate.contain_within``（容器门唯一判据）——本件与本席
改动的生产代码**都不带第二把尺**，本格的一条腿就是钉住这件事。

为什么消费侧也要一道门（现状核实见工单 §1）：``MediaDownloader`` 把
``%(id)s.%(ext)s`` 直进文件名（``domains/files/sources/downloader.py:944``），又在
:959-961 拿**未经任何消毒的** ``info['id']``/``info['ext']`` 就地拼出一枚路径，
:984 再拿同一枚 ``id`` 当 ``glob`` 的**模式串**。这两个串随后既进正文回显、又进
``video.file`` 交协议端**读字节**，字幕那枚还被 ``_subtitle_plain_text`` 读成文本进
meta ⇒ 一把没消毒的落点名就是一枚「任意文件读 + 外发」原语（同族事故账＝E02 席的
本地路径域门，见 ``tests/test_vision_local_path_domain_gate.py``）。装配点那枚文件
属别席（本席禁写），**本件只钉两格**：① 消费侧确实在问真身、拒得下来；② 装配侧的
存量违规枚数按现算入棘轮，主会话照工单 §2 提案落地后基线必须随之缩小（只降不升）。

全离线：零网络、零真下载，落盘只写 ``tmp_path``。
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.contracts import IncomingMessage
from plugins.bot_unified_runtime.domains.files.capabilities import (
    download as download_mod,
)
from plugins.bot_unified_runtime.domains.files.sources.downloader import DownloadOutcome
from plugins.bot_unified_runtime.domains.media import path_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
DOWNLOAD_PY = (
    PKG_ROOT / "domains" / "files" / "capabilities" / "download.py"
).relative_to(REPO_ROOT)

_URL = "https://example.com/video/abc123"


# ---------------------------------------------------------------------------
# 夹具：一枚「已经按下发回来的元数据拼好名字」的下载器替身
# ---------------------------------------------------------------------------


class _StubDownloader:
    """只替 ``download()`` 这一步；``download_dir`` 与真身 MediaDownloader 同形。"""

    def __init__(self, outcome: DownloadOutcome, *, download_dir: str | None) -> None:
        self._outcome = outcome
        if download_dir is not None:
            self.download_dir = Path(download_dir)

    def available(self) -> bool:
        return True

    def download(self, url: str) -> DownloadOutcome:
        return self._outcome


def _msg(text: str = f"下载 {_URL}") -> IncomingMessage:
    return IncomingMessage(
        platform="qq",
        adapter="onebot",
        bot_id="bot-1",
        session_id="private:10001",
        session_type="private",
        sender_id="10001",
        plain_text=text,
        mentions_bot=True,
    )


def _run(outcome: DownloadOutcome, *, container: Path | None) -> Any:
    downloader = _StubDownloader(
        outcome, download_dir=str(container) if container is not None else None
    )
    return download_mod.build_download_capability(downloader=downloader)(_msg(), None)


def _derived(container: Path, video_id: str, ext: str) -> str:
    """复刻 downloader.py:959-961 的拼名形态（那里没消毒，本处也不消毒——就是要它翻车）。"""
    return str(Path(container) / f"{video_id}.{ext}")


# ---------------------------------------------------------------------------
# ① 注毒腿：畸形 ext / 带路径分隔符的 id / 保留名 / ADS / NUL / 编码穿越 ⇒ 必须被拒
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("video_id", "ext", "expected_code"),
    [
        # 目录分隔符 + 上跳：拼出来落在容器外（Windows 反斜杠形与 POSIX 斜杠形各一枚）。
        ("../../outside/secret", "mp4", "outside_root"),
        ("..\\..\\outside\\secret", "mp4", "outside_root"),
        # 畸形 ext：扩展名自带分隔符与上跳，把落点搬到容器外。
        ("BV153bE6SEWq", "/../../outside/ini", "outside_root"),
        # Win32 保留设备名（落在容器内也照样拒：那枚名字根本不能当文件用）。
        ("nul", "mp4", "reserved_device_name"),
        # NTFS 备用数据流形态（冒号后缀）。
        ("report", "mp4:evil", "illegal_segment"),
        # NUL 注入。
        ("vid\x00eo", "mp4", "illegal_segment"),
        # URL 编码的穿越写法。
        ("%2e%2e%2fsecret", "mp4", "encoded_traversal"),
    ],
)
def test_hostile_derived_name_is_refused_before_any_byte_is_read(
    tmp_path: Path, video_id: str, ext: str, expected_code: str
) -> None:
    container = tmp_path / "downloads"
    container.mkdir()
    outcome = DownloadOutcome(path=_derived(container, video_id, ext), error="")

    result = _run(outcome, container=container)

    assert result.kind == "text", f"畸形落盘名被当成功回传：{video_id!r}/{ext!r}"
    assert not getattr(result, "video", None), "被拒的落点仍然带着 video 部件"
    assert "artifact_refused_by_container_gate" in result.audit_tags
    assert f"gate_code={expected_code}" in result.audit_tags, result.audit_tags
    # 拒的那一格里不许有路径原文（泄露面不许借「拒绝理由」回潮）。
    assert video_id not in result.body and ext not in result.body


def test_absolute_path_outside_container_is_refused(tmp_path: Path) -> None:
    """协议端正则之外的一条：元数据直接给出**容器外绝对路径**形态的 id。"""
    container = tmp_path / "downloads"
    container.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    victim = private / "diary.txt"
    victim.write_text("不该被念出来的内容", encoding="utf-8")

    result = _run(DownloadOutcome(path=str(victim), error=""), container=container)

    assert result.kind == "text"
    assert str(victim) not in result.body
    assert not getattr(result, "video", None)


def test_subtitle_outside_container_refuses_the_whole_artifact(tmp_path: Path) -> None:
    """字幕那枚同样来路不正：``glob`` 的模式串吃远端 ``id``，可以摸到容器外。

    刻意整件拒（而不是「留视频、扔字幕」）：字幕文本会进 meta 被模型引用，
    与 ``video.file`` 属同一次交付的信任面，拆开放行等于给外读留一条缝。
    """
    container = tmp_path / "downloads"
    container.mkdir()
    media = container / "BV153bE6SEWq.mp4"
    media.write_bytes(b"fake-video-bytes")
    outside_srt = tmp_path / "outside.srt"
    outside_srt.write_text("00:00:00,000 --> 00:00:01,000\n偷来的字幕\n", encoding="utf-8")

    result = _run(
        DownloadOutcome(path=str(media), subtitle_path=str(outside_srt), error=""),
        container=container,
    )

    assert result.kind == "text"
    assert "偷来的字幕" not in str(result.model_dump())
    assert not getattr(result, "video", None)


def test_unreadable_container_root_fails_closed(tmp_path: Path) -> None:
    """读不出容器根＝零登记根，真身自己判「越界」，不许退成「那就放行」。"""
    media = tmp_path / "downloads" / "a.mp4"
    media.parent.mkdir()
    media.write_bytes(b"x")

    result = _run(DownloadOutcome(path=str(media), error=""), container=None)

    assert result.kind == "text"
    assert "artifact_refused_by_container_gate" in result.audit_tags


# ---------------------------------------------------------------------------
# ② 反向不误伤腿：正常下载件照常回传，且交出去的是**折算后的真身形态**
# ---------------------------------------------------------------------------


def test_ordinary_artifact_is_gated_and_returned_resolved(tmp_path: Path) -> None:
    container = tmp_path / "downloads"
    container.mkdir()
    media = container / "BV153bE6SEWq.mp4"
    media.write_bytes(b"fake-video-bytes")
    srt = container / "BV153bE6SEWq.zh-Hans.srt"
    srt.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n正经字幕一行\n",
        encoding="utf-8",
    )

    result = _run(
        DownloadOutcome(path=str(media), subtitle_path=str(srt), error=""),
        container=container,
    )

    assert result.kind == "mixed"
    parts = result.video or []
    assert len(parts) == 1
    sent_file = parts[0]["file"]
    assert Path(sent_file) == media.resolve()
    assert Path(sent_file).is_file() and str(Path(sent_file).resolve()) == sent_file
    assert "正经字幕一行" in parts[0]["meta"]["subtitle_text"]
    assert parts[0]["meta"]["subtitle_file"] == str(srt.resolve())
    assert str(media.resolve()) in result.body


def test_nested_but_inside_name_is_contained_not_rejected(tmp_path: Path) -> None:
    """诚实边界（不许把这一格当「已拦下」记账）：分隔符**没逃出容器**时真身放行。

    ``id="sub/x"`` 拼出的落点仍在 ``downloads/`` 之内 ⇒ 容器门的判据（折算后还在根内）
    说的是「没越界」，它不管「名字该不该只有一段」。真正把「带路径分隔符的 id」判成
    拒的是**装配侧**的消毒腿（``file_gateway.sanitize_file_name`` 取 basename），那枚
    文件属别席 ⇒ 改法与验收口径写在工单 §2，本格只把「消费侧门管得到什么、管不到什么」
    钉成账，免得下一席把这半程当全修好了。
    """
    container = tmp_path / "downloads"
    (container / "sub").mkdir(parents=True)
    nested = container / "sub" / "a.mp4"
    nested.write_bytes(b"x")

    result = _run(DownloadOutcome(path=_derived(container, "sub/a", "mp4"), error=""), container=container)

    assert result.kind == "mixed", "容器内的嵌套名被消费侧误杀＝判据被偷偷加严（越权改语义）"
    assert Path(result.video[0]["file"]) == nested.resolve()


def test_empty_subtitle_ref_is_not_invented_into_a_rejection(tmp_path: Path) -> None:
    """「没有字幕」与「字幕想去外面」是两件事：空串原样为空，不触发拒门。"""
    container = tmp_path / "downloads"
    container.mkdir()
    media = container / "a.mp4"
    media.write_bytes(b"x")

    result = _run(DownloadOutcome(path=str(media), error=""), container=container)

    assert result.kind == "mixed"
    assert result.video[0]["meta"]["subtitle_file"] == ""
    assert "字幕已保存" not in result.body


def test_failure_leg_is_untouched(tmp_path: Path) -> None:
    """下载失败那条腿逐字不变（本席只在成功路径上加门，不许顺手改降级文案）。"""
    result = _run(DownloadOutcome(error="yt-dlp 未安装，无法下载", path=""), container=tmp_path)
    assert result.kind == "text"
    assert "download_failed" in result.audit_tags


# ---------------------------------------------------------------------------
# ③ 判据身份锁：消费侧只准转调真身，不许自带第二把尺
# ---------------------------------------------------------------------------


def _first_call_lines(source: str, fn_name: str, call_name: str) -> int:
    """``fn_name`` 体内第一次出现 ``call_name(...)`` 的行号（找不到即抛）。"""
    tree = ast.parse(source)
    target = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == fn_name),
        None,
    )
    assert target is not None, f"锚失效：找不到函数 {fn_name}"
    lines = [
        node.lineno
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == call_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == call_name)
        )
    ]
    assert lines, f"锚失效：{fn_name} 体内没有 {call_name} 的调用点"
    return min(lines)


def test_consumer_welds_the_truth_source_and_keeps_no_second_ruler() -> None:
    text = (REPO_ROOT / DOWNLOAD_PY).read_text(encoding="utf-8")
    assert "path_gate.contain_within" in text, "落点门没接容器门唯一真身"
    for second_ruler in (
        "is_relative_to",
        "def contain_within",
        "os.path.commonpath",
        "safety_exec.paths",
    ):
        assert second_ruler not in text, f"消费侧出现第二把尺／第二通路：{second_ruler}"
    # 门必须排在「读字节」之前：能力体内先过门、后读字幕（判定与执行不许两说）。
    assert _first_call_lines(text, "capability", "_gate_artifact") < _first_call_lines(
        text, "capability", "_subtitle_plain_text"
    ), "字幕在过门之前就被读进内存"


def test_weld_order_lock_has_teeth() -> None:
    """注毒自证：把「先读字幕、后过门」写回去，上一格立刻红（否则那是一条空转腿）。"""
    wrong = """
def capability(message):
    text = _subtitle_plain_text(subtitle_file)
    media = _gate_artifact(outcome.path, container)
    return text, media
"""
    assert _first_call_lines(wrong, "capability", "_gate_artifact") > _first_call_lines(
        wrong, "capability", "_subtitle_plain_text"
    )
    right = """
def capability(message):
    media = _gate_artifact(outcome.path, container)
    text = _subtitle_plain_text(subtitle_file)
    return text, media
"""
    assert _first_call_lines(right, "capability", "_gate_artifact") < _first_call_lines(
        right, "capability", "_subtitle_plain_text"
    )


def test_containment_judgement_is_the_real_one(tmp_path: Path) -> None:
    """行为面复核：门给出的结论与真身逐字同形（本席没有偷换判据）。"""
    container = tmp_path / "downloads"
    container.mkdir()
    inside = container / "a.mp4"
    inside.write_bytes(b"x")

    assert path_gate.contain_within(str(inside), [container]) == inside.resolve()
    with pytest.raises(path_gate.PathEscapeError) as refused:
        path_gate.contain_within(str(container / ".." / ".." / "x.mp4"), [container])
    assert refused.value.code == "outside_root"


# ---------------------------------------------------------------------------
# ④ 装配侧存量棘轮：远端元数据直进文件名的那一族，枚数只降不升
# ---------------------------------------------------------------------------

#: 存量账（2026-10-02 席 B1 现算复录）。三枚全住在
#: ``domains/files/sources/downloader.py`` ——**本席禁写面**，故按存量登记，
#: 逐枚改法与判据见 ``patches/B1-TTS-CACHE-OUTTMPL-20261002.md`` §2。
#: 键＝(文件, 函数, 形态代号)——**不写行号**（台账 #50★：行号会漂）。
DERIVED_NAME_BASELINE: frozenset[tuple[str, str, str]] = frozenset(
    {
        (
            "plugins/bot_unified_runtime/domains/files/sources/downloader.py",
            "_download_once",
            "outtmpl-literal",
        ),
        (
            "plugins/bot_unified_runtime/domains/files/sources/downloader.py",
            "_download_once",
            "derived-name-literal",
        ),
        (
            "plugins/bot_unified_runtime/domains/files/sources/downloader.py",
            "_locate_subtitle_file",
            "derived-name-var",
        ),
    }
)

_PATH_CALL_ATTRS = frozenset(
    {
        "glob",
        "rglob",
        "open",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "unlink",
    }
)
_METADATA_KEYS = frozenset({"id", "ext"})
_METADATA_SOURCES = frozenset({"info", "ydl_info", "probe_info", "entry"})
_GATE_ATTRS = frozenset({"contain_within", "sanitize_file_name", "sanitize_write_segments"})


def _derived_tokens(node: ast.AST) -> set[str]:
    """这一子树里有没有「远端元数据直进名字」的形态（含 yt-dlp 模板字面量）。

    归一成三种**形态代号**（不是逐枚 token 名）：存量账按代号记账，改法也只按代号
    验收，避免「换个字段名就看不见洞」那一类假绿。
    """
    found: set[str] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "get"
            and sub.args
            and isinstance(sub.args[0], ast.Constant)
            and sub.args[0].value in _METADATA_KEYS
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id in _METADATA_SOURCES
        ):
            found.add("derived-name-literal")
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and (
            "%(id)s" in sub.value or "%(ext)s" in sub.value
        ):
            found.add("outtmpl-literal")
    return found


def _path_nodes(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    out: list[ast.AST] = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div) or (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in _PATH_CALL_ATTRS
        ):
            out.append(sub)
    return out


def _scan_derived_name_sites(source: str, label: str) -> set[tuple[str, str, str]]:
    """一个文件的源码 → 违规格集合（``label`` 只作记账身份，不参与判据）。

    放行条件只有一个且**必须是真身**：该函数体内出现 ``contain_within`` /
    ``sanitize_file_name`` / ``sanitize_write_segments`` 之一（消毒口与容器门各自
    都在中央，转调即算接线）。
    """
    try:
        with warnings.catch_warnings():
            # 生产文件里的非 raw 正则会随 ast.parse 报 SyntaxWarning——那是那一枚文件
            # 自己的 lint 账，本件只扫结构，不替它响铃。
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - 生产树不该出现，出现由别的门红
        return set()
    hits: set[tuple[str, str, str]] = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        dumped = ast.dump(fn)
        if any(gate in dumped for gate in _GATE_ATTRS):
            continue  # 整函数豁免：这一族已经问过真身（转调即算接线）
        tainted: dict[str, str] = {}
        for stmt in ast.walk(fn):
            if isinstance(stmt, ast.Assign):
                tokens = _derived_tokens(stmt)
                if tokens:
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            tainted[target.id] = min(tokens)
        for node in _path_nodes(fn):
            hits |= {(label, fn.name, token) for token in _derived_tokens(node)}
            if any(
                isinstance(sub, ast.Name) and sub.id in tainted for sub in ast.walk(node)
            ):
                hits.add((label, fn.name, "derived-name-var"))
    return hits


def measure_derived_name_sites() -> set[tuple[str, str, str]]:
    """现算全生产面的「远端元数据直进文件名」违规格（棘轮的分母）。"""
    hits: set[tuple[str, str, str]] = set()
    for path in sorted(PKG_ROOT.rglob("*.py")):
        label = path.relative_to(REPO_ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        hits |= _scan_derived_name_sites(source, label)
    return hits


def test_derived_name_sites_match_the_baseline_exactly() -> None:
    """零余量棘轮：违规集合必须**逐枚等于**存量账。

    多一枚＝新长的洞；少一枚＝主会话照工单落地了消毒 ⇒ 本账必须同批缩小
    （台账 #68★：退役要「文件 + 账本行」同批动，只动一边必红另一边）。
    """
    now = measure_derived_name_sites()
    assert now == set(DERIVED_NAME_BASELINE), (
        "远端元数据直进文件名的存量账与现算不符 ⇒ "
        f"新增={sorted(now - set(DERIVED_NAME_BASELINE))} "
        f"已消={sorted(set(DERIVED_NAME_BASELINE) - now)}"
    )


def test_derived_name_scan_has_teeth() -> None:
    """注毒自证：三枚形态各写回去一次，尺必须当场认出来。"""
    poison = """
from pathlib import Path


class Box:
    def __init__(self):
        self.download_dir = Path(".")

    def _download_once(self, info, opts):
        opts.update({"outtmpl": str(self.download_dir / "%(id)s.%(ext)s")})
        path = str(Path(self.download_dir) / f"{info.get('id', 'video')}.{info.get('ext')}")
        return path

    def _locate_subtitle_file(self, info):
        stem = str(info.get("id") or "")
        return sorted(self.download_dir.glob(f"{stem}*"))

    def _plain_text_leg(self, info):
        return str(info.get("title") or "")
"""
    hits = _scan_derived_name_sites(poison, "poison.py")
    assert {
        ("poison.py", "_download_once", "outtmpl-literal"),
        ("poison.py", "_download_once", "derived-name-literal"),
        ("poison.py", "_locate_subtitle_file", "derived-name-var"),
    } == hits, hits
    # 反向不误伤腿：同一枚元数据只进正文（不进路径）⇒ 不算这一族的罪。
    assert "_plain_text_leg" not in {item[1] for item in hits}


def test_derived_name_scan_does_not_flag_gated_code() -> None:
    """反向不误伤腿（判据身份）：转调真身之后，同样的写法必须放行。"""

    gated = """
from pathlib import Path
from plugins.bot_unified_runtime.domains.media import path_gate


class Box:
    def __init__(self):
        self.download_dir = Path(".")

    def _download_once(self, info):
        name = f"{info.get('id')}.{info.get('ext')}"
        return str(path_gate.contain_within(name, [self.download_dir], base=self.download_dir))
"""
    assert _scan_derived_name_sites(gated, "gated.py") == set()


def test_baseline_entries_are_still_live_and_named_by_symbol() -> None:
    """存量账不许写成死坐标：每格的 (文件, 函数) 必须此刻仍在树上且真含该形态。"""
    measured = measure_derived_name_sites()
    for label, func, token in sorted(DERIVED_NAME_BASELINE):
        source = (REPO_ROOT / label).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func
            for node in ast.walk(tree)
        ), f"存量账里的函数已不存在（该删这一格并同批改工单）：{label}::{func}"
        assert (label, func, token) in measured, f"存量账与现算脱钩：{label}::{func}::{token}"
