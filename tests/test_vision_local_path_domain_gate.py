"""本地媒体路径**域门**的行为锁（INCIDENT-20260930-TREEWIPE-RECOVERY §5 P0 行）。

洞的形态（事故卷宗原话）：`vision_describe._local_path_from_value` 只问
``is_file()``，而 `_encode_image_bytes` / `_image_file_to_data_url` 把字节
base64 之后发给**外部 VLM** ⇒ 组合＝「任意本地文件读 + 外传」。共用这把无门
判据的消费方还有 `transcribe`（语音→ASR 接口上传）、
`video_understanding.build_native_video_part`（视频→VLM）、
`vision_caption_cache.image_ref_digest`（任意文件内容→哈希）与 ffmpeg 直喂腿
（`_extract_video_frames` / `_extract_audio_clip`）。

修法（**不造第三套判据**，只把两枚在册守门件接上）：
- 容器归属＝`domains/media/path_gate.contain_within`（折算后按段元组判前缀，
  `..` / 编码穿越 / 设备前缀 / ADS / 保留名 / junction 全在它那一侧出局，且返回
  **折算后**路径 ⇒ 「判定走 A、执行走 B」两说不存在）；
- 登记根＝`path_gate.media_read_roots()` 那枚**唯一名册**（W5 第 2 条：正门
  `safety_exec.paths.readable_roots` + 媒体侧声明的暂存根 + 协议端锚点派生，三段
  只住 `path_gate.py` 一处；`vision_describe` 不再自己列目录。测试经
  `safety_paths._default_policy` 注假根、经 `path_gate.media_temp_root` 注假暂存根）；
- 禁触名册＝同一件 `check_sendable` 的 `forbidden_zone` / `forbidden_file_class`
  两枚判据（`.env` / `*.sqlite3` / cookie / persona / venv / `.git` / `.ssh` /
  日志 / key-token-secret 类）——**任何位置**都拒，登记根内也拒。
  ⚠ 刻意**不取**它的形态类判据（`short_name_form` 等）：本机 `%TEMP%` 实测就是
  `LANCYC~1` 短名形态，拿它判暂存面会整族误杀（S-T-FILE-2 在册教训）；形态这一格
  归 `path_gate`，两把尺各管一段，既不重复也不留空档。
- ffmpeg 直喂腿（W5 第 4 条）：放行后下发的是**判定折算后的真身**
  （`_local_media_execution_source`），不再吃原串——本波把它从「作者注释自陈的
  另一侧」改成判与执同形，锁在文件末尾那两格折算格。

门强度按**取证**定（卷宗要求「先取证再定松紧」）——段 `data.file` 的写入方实测三类：
① bot 自己产的（下载器 `bot_download_dir`、邮件附件、NoneBot localstore、
   ffmpeg/ASR/TG 临时件）⇒ 登记根或系统暂存根内；
② 协议端（NTQQ/SnowLuma/NapCat）落盘的 ``…\\nt_qq\\nt_data\\…``（取证：归档日志
   ``nonebot.out.log.bak-20260912`` 的 Ptt 行）⇒ 既不在工作区也不在运行数据根内，
   而 `BOT_ASR_ENABLED` 生产在岗、record 段入站契约就吃这一格
   （docs/snowluma-setup.md §6「record 段入站只消费 file/url/path/media 四者之一」）
   ⇒ 整块闸死会把语音转写静默打死，故把锚点**折算成容器根**放行（锚点之外一律不算根内）；
③ 控制面 `POST /api/v1/media/analyze` 那支另由 `file_access.admit_media_source`
   守（在册 `test_control_plane_media_analyze_scope`），本件不重复闸也不放宽它。

全部离线：`tmp_path` + 假登记根 + 假暂存根打桩，不碰真实仓库与生产 Runtime。
"""

from __future__ import annotations

import ast
import base64
import subprocess
from pathlib import Path
from typing import Any

import pytest

import plugins.bot_unified_runtime.domains.media.ingest.transcribe as transcribe_mod
import plugins.bot_unified_runtime.domains.media.ingest.video_understanding as video_mod
import plugins.bot_unified_runtime.domains.media.ingest.vision_describe as vision_mod
import plugins.bot_unified_runtime.domains.media.video.video_pipeline as pipeline_mod
from plugins.bot_unified_runtime.domains.core.safety_exec import paths as safety_paths
from plugins.bot_unified_runtime.domains.media import path_gate
from plugins.bot_unified_runtime.domains.media.ingest.vision_describe import (
    _local_path_from_value,
)
from plugins.bot_unified_runtime.domains.media.registry import vision_caption_cache

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_FAKE = b"\x00\x00\x00\x18ftypmp42"  # 容器头形态，内容无意义

REPO = Path(__file__).resolve().parents[1]


class _Arena:
    """四格容器：登记根 / bot 暂存根 / 域外私人区 / 协议端落盘锚。"""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.registered = base / "runtime"
        self.temp = base / "temp"
        self.private = base / "private"
        self.protocol = (
            base
            / "Documents"
            / "Tencent Files"
            / "12345678"
            / "nt_qq"
            / "nt_data"
            / "Ptt"
            / "2026-09"
            / "Ori"
        )
        for directory in (self.registered, self.temp, self.private, self.protocol):
            directory.mkdir(parents=True, exist_ok=True)

    def write(self, directory: Path, name: str, payload: bytes = _PNG) -> Path:
        path = directory / name
        path.write_bytes(payload)
        return path


@pytest.fixture()
def arena(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Arena:
    """假登记根 + 假暂存根注入：判定面与真实机器目录彻底脱钩。

    暂存根那一枚缝现在住在**名册真身**（``path_gate.media_temp_root``）而不是消费侧——
    注它一处，所有转调 ``media_read_roots`` 的腿一起换掉（注两枚＝又把名册写散）。
    """
    grid = _Arena(tmp_path)
    monkeypatch.setattr(
        safety_paths,
        "_default_policy",
        safety_paths.build_policy(workspace_root=grid.registered),
    )
    monkeypatch.setattr(path_gate, "media_temp_root", lambda: grid.temp)
    return grid


# ---------------------------------------------------------------------------
# 正面：三条合法 producer 腿一个都不许打死（门不是把功能焊死）
# ---------------------------------------------------------------------------

def test_media_inside_registered_root_still_reads(arena: _Arena) -> None:
    png = arena.write(arena.registered, "ok.png")
    resolved = _local_path_from_value(str(png))
    assert resolved is not None and resolved == png.resolve()
    urls = vision_mod.extract_image_urls(
        [{"type": "image", "data": {"file": str(png)}}]
    )
    assert urls and urls[0].startswith("data:image/png;base64,")


def test_media_under_temp_producer_root_still_reads(arena: _Arena) -> None:
    """TG file_id 落临时件 / ffmpeg 抽帧 / ASR work_dir 这一族必须照读。"""
    png = arena.write(arena.temp, "tg_photo.png")
    assert _local_path_from_value(png.as_uri()) is not None


def test_protocol_adapter_media_leg_still_reads(arena: _Arena) -> None:
    """语音转写腿：协议端 nt_data 落盘的 mp3 不许被域门静默打死。"""
    clip = arena.write(arena.protocol, "voice.mp3", _FAKE)
    source = transcribe_mod.extract_audio_source(
        [{"type": "record", "data": {"file": str(clip)}}]
    )
    assert source == str(clip.resolve())


def test_file_uri_of_registered_media_still_reads(arena: _Arena) -> None:
    png = arena.write(arena.registered, "uri.png")
    assert _local_path_from_value(png.as_uri()) == png.resolve()


# ---------------------------------------------------------------------------
# 负面：任意本地文件读+外传那一格（本票的主锁）
# ---------------------------------------------------------------------------

def test_private_media_outside_every_root_is_refused(arena: _Arena) -> None:
    leak = arena.write(arena.private, "private_album.png")
    assert _local_path_from_value(str(leak)) is None
    assert _local_path_from_value(leak.as_uri()) is None
    assert (
        vision_mod.extract_image_urls([{"type": "image", "data": {"file": str(leak)}}])
        == []
    )
    assert vision_mod._image_file_to_data_url(str(leak)) is None
    assert transcribe_mod.build_native_audio_part(str(leak), max_mb=20) is None
    assert video_mod.build_native_video_part(str(leak), 20) is None


def test_traversal_out_of_the_root_is_refused(arena: _Arena) -> None:
    leak = arena.write(arena.private, "escaped.png")
    relative_form = str(arena.registered / ".." / "private" / leak.name)
    assert _local_path_from_value(relative_form) is None
    assert _local_path_from_value(f"file://{leak.as_posix()}") is None


def test_traversal_back_into_a_registered_root_is_allowed(arena: _Arena) -> None:
    """`..` 折回登记根内按实况放行——与容器门同一把尺的两面。"""
    png = arena.write(arena.registered, "back_inside.png")
    weird = arena.temp / ".." / "runtime" / png.name
    assert _local_path_from_value(str(weird)) == png.resolve()


@pytest.mark.parametrize(
    "name",
    [
        "user_affinity.sqlite3.png",   # 库伴生形态（suffixes 命中 .sqlite3）
        "app.env.png",                 # .env 形态
        "platform_cookies.png",        # cookie 子串
        "chat_api_key.png",            # api_key 子串
        "session_token.png",           # token 子串
        "run.log.png",                 # 日志后缀
    ],
)
def test_forbidden_roster_refused_inside_registered_root(
    arena: _Arena, name: str
) -> None:
    """禁触名册压在最外一层：登记根内也不许把凭据类字节交给外部模型。"""
    secret = arena.write(arena.registered, name)
    assert _local_path_from_value(str(secret)) is None


def test_plain_media_inside_registered_root_is_not_collateral(arena: _Arena) -> None:
    """上一枚负例的对照：同目录同尺寸的普通文件名必须仍可读（拒的是名册不是全部）。"""
    assert _local_path_from_value(str(arena.write(arena.registered, "clean.png")))


# ---------------------------------------------------------------------------
# 协议端锚点：只宽到那一格，且锚点外折回来一律不算根内
# ---------------------------------------------------------------------------

def test_protocol_anchor_is_not_a_wide_root(arena: _Arena) -> None:
    leak = arena.write(arena.private, "not_really_media_data.png")
    sneaky = arena.protocol / ".." / ".." / ".." / ".." / ".." / "private" / leak.name
    assert _local_path_from_value(str(sneaky)) is None


def test_forbidden_roster_applies_inside_protocol_anchor(arena: _Arena) -> None:
    decoy = arena.write(arena.protocol, "memory.sqlite3.png")
    assert _local_path_from_value(str(decoy)) is None


def test_directory_above_the_anchor_is_refused(arena: _Arena) -> None:
    """锚点的**父级**（nt_qq 那一格）不在锚点根内——宽只宽到 nt_data。"""
    near = arena.write(arena.protocol.parents[3], "nearby.png")
    assert _local_path_from_value(str(near)) is None


def _junction(link: Path, target: Path) -> bool:
    """造目录 junction（无需管理员）。成功 True、平台不支持 False——不谎称已拦。"""
    import sys

    if sys.platform != "win32":
        return False
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        encoding="utf-8",  # 台账 #47★：未钉 encoding 在 GBK 机器上必崩（errors 只兜残字节）
        errors="replace",
        check=False,
    )
    return completed.returncode == 0 and link.exists()


def test_junction_named_like_the_anchor_does_not_widen_the_root(arena: _Arena) -> None:
    """登记根里一枚**名叫 nt_data** 的 junction 指向私人区 ⇒ 锚点判据看的是折算后
    的真身（折完已经没有 nt_data 这一段）⇒ 必须拒，锚点那一格不许被链接撑大。"""
    if not _junction(arena.registered / "nt_data", arena.private):
        pytest.skip("本机建不出 junction（未验，不谎称已拦）")
    leak = arena.write(arena.private, "via_junction.png")
    assert _local_path_from_value(str(arena.registered / "nt_data" / leak.name)) is None


# ---------------------------------------------------------------------------
# 零登记根 / 判定失灵 ⇒ fail-closed
# ---------------------------------------------------------------------------

def test_gate_fails_closed_without_any_root(
    arena: _Arena, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = arena.write(arena.registered, "orphan.png")
    monkeypatch.setattr(safety_paths, "_default_policy", safety_paths.build_policy())
    monkeypatch.setattr(path_gate, "media_temp_root", lambda: Path(""))
    assert _local_path_from_value(str(png)) is None
    # 名册空 ⇒ media_read_roots 也给空表，判定侧不许退成「取不到根就当放行」。
    assert path_gate.media_read_roots(png) == []


# ---------------------------------------------------------------------------
# 单一判据：第二份同名 def 不许存在；caption cache 走同一条带门判据
# ---------------------------------------------------------------------------

def test_caption_cache_shares_the_gated_judgement(arena: _Arena) -> None:
    inside = arena.write(arena.registered, "digest_ok.png")
    outside = arena.write(arena.private, "digest_leak.png")
    assert len(vision_caption_cache.image_ref_digest(str(inside))) == 64
    assert vision_caption_cache.image_ref_digest(str(outside)) == ""


MEDIA_ROOT = REPO / "plugins/bot_unified_runtime/domains/media"
CONSUMERS = (
    "ingest/transcribe.py",
    "ingest/video_understanding.py",
    "video/video_pipeline.py",
    "registry/vision_caption_cache.py",
)


def _media_texts() -> dict[str, str]:
    return {
        path.relative_to(MEDIA_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in MEDIA_ROOT.rglob("*.py")
    }


def _is_file_sites(source: str) -> list[tuple[int, str]]:
    """AST 取 ``X.is_file()`` 调用：(行号, 接收者的源码形态)。

    为什么走 AST 不 grep 字面量：``is_file()`` 这四个字**在散文里也出现**（模块头与
    各处记账注释都要提那枚旧判据），字面量禁词会把说明文当罪证、或逼作者把说明删掉
    ——两种结局都是把账抹了。AST 只认**真调用**，说明文自然出局；而
    ``Path(x).is_file()`` 这种「拿外来串就地判在场」的第二把尺形态，接收者是
    ``ast.Call``，正是本格要钉死的那一格。
    """
    tree = ast.parse(source)
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"is_file", "isfile"}:
            sites.append((node.lineno, ast.unparse(func.value)))
    return sites


def _anchor_literal_sites(source: str) -> bool:
    """这份源码里有没有「值恰好是锚点目录名」的字符串常量（散文提它不算）。"""
    return any(
        isinstance(node, ast.Constant) and node.value == path_gate.PROTOCOL_MEDIA_ANCHOR_NAME
        for node in ast.walk(ast.parse(source))
    )


def _tempdir_call_sites(source: str) -> bool:
    """这份源码里有没有真去 ``tempfile.gettempdir()``（提它的名词不算）。"""
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "gettempdir"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tempfile"
        ):
            return True
    return False


def test_single_gated_local_path_definition() -> None:
    """带门判据只许一处真身；消费方一律转调（AGENTS「禁第二真身」口径）。"""
    definitions = [
        name
        for name, text in _media_texts().items()
        if "def _local_path_from_value" in text
    ]
    assert definitions == ["ingest/vision_describe.py"], definitions


def test_root_roster_lives_in_exactly_one_file() -> None:
    """W5 第 2 条「两个真相源」的正锁：**哪些目录算合法**只许住 ``path_gate.py``。

    上一波的形态＝正门（``safety_exec.paths``）那份名册之外，消费侧 ``vision_describe``
    就地 ``roots.append(...)`` 追加两枚新根（``%TEMP%`` 与协议端 ``nt_data`` 锚）⇒
    名册分家、收紧正门时这两枚静默漏网。本格按 **AST** 认这两枚根的**写法**
    （值恰为 ``"nt_data"`` 的常量 / ``tempfile.gettempdir()`` 调用），说明文提它们不算罪。
    """
    texts = _media_texts()
    anchors = sorted(name for name, text in texts.items() if _anchor_literal_sites(text))
    tempdirs = sorted(name for name, text in texts.items() if _tempdir_call_sites(text))
    roster = sorted({name for name in texts if "def media_read_roots" in texts[name]})
    assert anchors == ["path_gate.py"], f"协议端锚点名被抄进多处：{anchors}"
    assert tempdirs == ["path_gate.py"], f"暂存根被就地重算：{tempdirs}"
    assert roster == ["path_gate.py"], f"「哪些根」出现第二份名册定义：{roster}"
    # 名册只此一处：消费侧一律转调带门判据，不许自己 append 根。
    assert "path_gate.media_read_roots" in texts["ingest/vision_describe.py"]
    for relative in CONSUMERS:
        assert "_local_path_from_value" in texts[relative], f"{relative} 没转调唯一判据"
        assert "media_read_roots" not in texts[relative], f"{relative} 绕开判据直取名册"


def test_root_roster_detectors_have_teeth() -> None:
    """注毒自证：把两枚新根写回消费侧，上面那格必须立刻红（探测器不是空跑）。"""
    poison_anchor = 'X = "nt_data"\n'
    poison_temp = "import tempfile\nY = tempfile.gettempdir()\n"
    assert _anchor_literal_sites(poison_anchor)
    assert _tempdir_call_sites(poison_temp)
    # 说明文形态不许当罪证（否则大家会去删注释＝把账抹了）。
    assert not _anchor_literal_sites('"""协议端锚点叫 nt_data，只此一格。"""\n')
    assert not _tempdir_call_sites('"""暂存根真身＝tempfile.gettempdir() 一处。"""\n')


def test_media_ingest_holds_no_second_containment_ruler() -> None:
    """容器归属只许转调 path_gate / safety_exec，不许自带第二把尺。"""
    gate_file = (MEDIA_ROOT / "ingest/vision_describe.py").read_text(encoding="utf-8")
    path_gate_file = (MEDIA_ROOT / "path_gate.py").read_text(encoding="utf-8")
    assert "path_gate.contain_within" in gate_file, "带门判据没接到容器门唯一真身"
    assert "path_gate.media_read_roots" in gate_file, "带门判据没接唯一根名册"
    assert "path_gate.forbidden_roster_refused" in gate_file, "带门判据没接禁触名册那一问"
    assert "def contain_within" in path_gate_file, "容器门本体不在唯一真身里"
    assert "readable_roots" in path_gate_file, "唯一名册没接正门那份在册根"
    assert "check_sendable" in path_gate_file, "禁触名册那一问没接 safety_exec 真身"
    for relative in CONSUMERS:
        text = (MEDIA_ROOT / relative).read_text(encoding="utf-8")
        for forbidden in ("is_relative_to", "def _local_path_from_value"):
            assert forbidden not in text, f"{relative} 里出现第二把尺：{forbidden}"


def test_bare_existence_ruler_is_gone_from_consumers() -> None:
    """W5 第 3 条：``video_pipeline`` 那把裸 ``Path(path).is_file()`` 必须收敛掉。

    三格判据（全按 AST，散文提 ``is_file()`` 不算）：
    ① ``video/video_pipeline.py`` 里**一枚**在场判定都不许有——它只许转调带门判据；
    ② 消费侧（transcribe / video_understanding / vision_caption_cache）剩下的在场复查
       只许打在**自产暂存件**的变量名上（``out_mp3`` / ``candidate`` 这种），接收者
       一旦出现 ``Path(...)`` 这类「拿外来串就地判」形态就是第二把尺；
    ③ 带门判据内部（vision_describe）这种复查只许**一枚**——它就是第四问「在场」本体。
    """
    texts = _media_texts()
    pipeline_sites = _is_file_sites(texts["video/video_pipeline.py"])
    assert pipeline_sites == [], f"档案腿留了第二把裸尺：{pipeline_sites}"
    for relative in ("ingest/transcribe.py", "ingest/video_understanding.py"):
        for line, receiver in _is_file_sites(texts[relative]):
            assert "(" not in receiver and "." not in receiver, (
                f"{relative}:{line} 对外来串就地判在场（第二把尺）：{receiver}.is_file()"
            )
    verdict_sites = _is_file_sites(texts["ingest/vision_describe.py"])
    assert len(verdict_sites) == 1, f"带门判据的「在场」那一问不止一处或干脆没有：{verdict_sites}"


def test_bare_ruler_detector_has_teeth() -> None:
    """注毒自证：把 W5 第 3 条收掉的那把尺写回去，上一格立刻红。"""
    poison = "from pathlib import Path\n\n\ndef f(p):\n    return Path(p).is_file()\n"
    sites = _is_file_sites(poison)
    assert len(sites) == 1 and "(" in sites[0][1], sites
    # 对照腿：自产暂存件形态必须放行，否则判据把正解也误杀＝空转假守卫。
    ok = "def f(out):\n    return out.is_file()\n"
    assert _is_file_sites(ok) == [(2, "out")], _is_file_sites(ok)


def test_video_pipeline_usability_follows_the_gate(arena: _Arena) -> None:
    """行为面：档案 ``local_path`` 在域外＝不可用，在域内＝可用（布尔与带门判据同形）。"""
    inside = arena.write(arena.registered, "usable.mp4", _FAKE)
    outside = arena.write(arena.private, "unusable.mp4", _FAKE)
    assert pipeline_mod._local_file_usable(str(inside)) is True
    assert pipeline_mod._local_file_usable(str(outside)) is False
    assert pipeline_mod._local_file_usable("") is False
    # 在场但**在域外**——旧裸尺会报 True 的那一格，正是本条收的账。
    assert Path(outside).is_file() is True


# ---------------------------------------------------------------------------
# ffmpeg 直喂腿：越界本地源绝不进 ffmpeg 命令行（卷宗点名的第二支）
# ---------------------------------------------------------------------------


class _RunRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, command: Any, *_args: Any, **_kwargs: Any) -> Any:
        self.calls.append([str(item) for item in command])

        class _Done:
            returncode = 0
            stderr = b"Duration: 00:00:03.00\n"
            stdout = b""

        return _Done()


@pytest.fixture()
def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> _RunRecorder:
    recorder = _RunRecorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.setattr(vision_mod, "_find_ffmpeg_locate", lambda: "ffmpeg")
    monkeypatch.setattr(video_mod, "_find_ffmpeg_locate", lambda: "ffmpeg")
    return recorder


def test_frame_leg_never_fed_out_of_domain_source(
    arena: _Arena, fake_ffmpeg: _RunRecorder, tmp_path: Path
) -> None:
    private = arena.write(arena.private, "private.mp4", _FAKE)
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    assert vision_mod._extract_video_frames(str(private), 2, str(out_dir)) == []
    assert fake_ffmpeg.calls == [], f"越界本地源竟然下发了 ffmpeg：{fake_ffmpeg.calls}"


def test_frame_leg_still_feds_in_domain_source(
    arena: _Arena, fake_ffmpeg: _RunRecorder, tmp_path: Path
) -> None:
    clip = arena.write(arena.registered, "in_domain.mp4", _FAKE)
    out_dir = tmp_path / "frames2"
    out_dir.mkdir()
    vision_mod._extract_video_frames(str(clip), 2, str(out_dir))
    assert fake_ffmpeg.calls, "登记根内的正常视频被域门误杀"


def test_audio_clip_leg_never_fed_out_of_domain_source(
    arena: _Arena, fake_ffmpeg: _RunRecorder, tmp_path: Path
) -> None:
    private = arena.write(arena.private, "private_video.mp4", _FAKE)
    assert video_mod._extract_audio_clip(str(private), str(tmp_path), 5.0) is None
    assert fake_ffmpeg.calls == []


def test_remote_video_source_is_not_treated_as_local(arena: _Arena) -> None:
    """http 源归 SSRF 咽喉那一侧管，路径门不许把它一起闸死。"""
    assert vision_mod._local_media_source_allowed("https://v.example/a.mp4") is True
    assert vision_mod._local_media_source_allowed("") is False


def test_execution_source_is_the_folded_form_not_the_original_string(
    arena: _Arena,
) -> None:
    """W5 第 4 条本体：本地腿的**执行形态＝判定折算后的真身**（判 A 吃 B 那一侧销账）。

    夹具用「登记根内一枚不存在的子目录 + ``..`` 折回来」——旧写法判的是这条串、
    下发的也是这条串，ffmpeg 侧的解析器与门用的不是同一套归一规则；现在下发的
    必须是折完的真身，原串一律不进命令行。
    """
    clip = arena.write(arena.registered, "clip.mp4", _FAKE)
    weird = str(arena.registered / "no_such_dir" / ".." / clip.name)
    assert vision_mod._local_media_execution_source(weird) == str(clip.resolve())
    assert vision_mod._local_media_execution_source(clip.as_uri()) == str(clip.resolve())
    # 远程腿不动形态（咽喉在另一侧），过不了门的一律 None。
    assert (
        vision_mod._local_media_execution_source("https://v.example/a.mp4")
        == "https://v.example/a.mp4"
    )
    assert vision_mod._local_media_execution_source(str(arena.private / "x.mp4")) is None
    assert vision_mod._local_media_execution_source("") is None
    # 布尔投影与执行形态同口径，不许两说。
    assert vision_mod._local_media_source_allowed(weird) is True
    assert vision_mod._local_media_source_allowed(str(arena.private / "x.mp4")) is False


def test_frame_leg_feds_the_folded_path(
    arena: _Arena, fake_ffmpeg: _RunRecorder, tmp_path: Path
) -> None:
    """抽帧腿：ffmpeg 命令行里只许出现折算真身，原串（带 ``..``）必须消失。"""
    clip = arena.write(arena.registered, "in_domain.mp4", _FAKE)
    weird = arena.registered / "no_such_dir" / ".." / clip.name
    out_dir = tmp_path / "frames3"
    out_dir.mkdir()
    vision_mod._extract_video_frames(str(weird), 2, str(out_dir))
    tokens = [token for call in fake_ffmpeg.calls for token in call]
    assert fake_ffmpeg.calls, "登记根内的正常视频被域门误杀"
    assert str(clip.resolve()) in tokens, f"下发的不是折算真身：{tokens}"
    assert str(weird) not in tokens, f"原串照旧下发（判 A 吃 B）：{tokens}"


def test_audio_clip_leg_feds_the_folded_path(
    arena: _Arena, fake_ffmpeg: _RunRecorder, tmp_path: Path
) -> None:
    """音轨腿同一口径（两腿共用同一枚执行形态判据，不许一腿折一腿不折）。"""
    clip = arena.write(arena.registered, "in_domain_audio.mp4", _FAKE)
    weird = str(arena.registered / "no_such_dir" / ".." / clip.name)
    video_mod._extract_audio_clip(weird, str(tmp_path), 5.0)
    tokens = [token for call in fake_ffmpeg.calls for token in call]
    assert fake_ffmpeg.calls, "登记根内的正常视频被域门误杀"
    assert str(clip.resolve()) in tokens, f"下发的不是折算真身：{tokens}"
    assert weird not in tokens, f"原串照旧下发（判 A 吃 B）：{tokens}"


# ---------------------------------------------------------------------------
# 活性反证（注毒自证）：把门摘掉必须红，不是恒绿
# ---------------------------------------------------------------------------

def test_gate_is_live_not_a_stub(arena: _Arena) -> None:
    """摘掉容器归属那一问 ⇒ 域外文件立刻可读（说明上一批负例咬的是门本体）。

    临时打桩走**独立** ``MonkeyPatch`` 实例：``monkeypatch.undo()`` 会把 fixture
    注好的假暂存根一起撤掉，真 ``%TEMP%`` 当场回到根表里，反证就变成假绿。
    """
    leak = arena.write(arena.private, "blind_gate.png")

    def _blind(value: Any, _roots: Any, **_kw: Any) -> Path:
        return Path(str(value))

    temporary = pytest.MonkeyPatch()
    temporary.setattr(vision_mod.path_gate, "contain_within", _blind)
    assert _local_path_from_value(str(leak)) is not None
    temporary.undo()
    assert _local_path_from_value(str(leak)) is None
