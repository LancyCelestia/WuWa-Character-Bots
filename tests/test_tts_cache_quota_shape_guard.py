"""TTS 合成缓存的缺省面与配额形态闸（席 B1，2026-10-02 · P3.8）.

三件事，各有一腿：

① **缺省面钉成机器账**（简报写的是「缓存开关缺省为 `0`（关）」——现算**不是**）：
   ``bot_tts_cache_enabled`` 缺省 ``True``（默认就缓存合成产物），住在 ``0`` 的是
   **配额**两枚 ``bot_tts_cache_max_bytes`` / ``bot_tts_cache_max_age_days``
   （``enforce_quota`` 的 ``<=0`` 语义＝不限制）⇒ 现网形态＝**默认在缓存、默认不收盘**。
   改这一格要动 ``config.py``（本席禁写面）⇒ 精确需求见 ``patches/B1-CONFIG-REQUEST.md``，
   四面同批（台账 #68★）。

② **形态闸**（本席真正改了的代码）：``synthesize`` 的配额入参只认非负整数。
   ``int(True) == 1`` ⇒ 一枚布尔值会把「字节上限」执行成「把 ``data/tts_output`` 清空」，
   而且一路删到**刚写下的那一枚**为止（调用方拿到的路径当场成死引用，发送侧 M-38
   摘段＝整段语音消失）。同族判据＝``music.py::_music_cache_quota_bytes``（W7 核限额
   度）；本处只收「形态」这一维，不收「读不出键即回落 Config 缺省」那一维——后者要动
   6 枚字面 ``getattr`` 读点（直读维台账在别席手里），改法登记在工单 §5。

③ **接线锁**：``synthesize`` / ``synth_fn`` 的每一枚生产调用点都必须把
   ``cache_enabled`` + 两枚配额键交出去（新增调用点漏交＝那条路径的产物永远没人回收，
   而全树测试照绿）。

全离线：零网络（HTTP 一律 monkeypatch），落盘只写 ``tmp_path``；
**绝不读也绝不写** ``ChatBot_Runtime/data/tts_output``（那份现算取证在工单 §1，用命令行做）。
"""

from __future__ import annotations

import ast
import io
import warnings
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.media.capabilities import tts as tts_mod
from plugins.bot_unified_runtime.domains.media.capabilities.tts import (
    RefAudio,
    TtsParams,
    synthesize,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "plugins" / "bot_unified_runtime"
_API = "http://127.0.0.1:9880"

#: 每枚生产调用点必须交出的旋钮（按符号名认；行号会漂 ⇒ 台账 #50★）。
REQUIRED_KNOBS = ("output_dir", "cache_enabled", "quota_max_bytes", "quota_max_age_days")
#: 现算调用点账（2026-10-02 席 B1 复录）：命令路 / 自动配音频路 / 富化钩子路各一枚。
SYNTHESIZE_CALLSITES = frozenset(
    {
        ("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "capability"),
        ("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "synthesize_autodub"),
        ("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "maybe_attach_voice"),
    }
)


def _params() -> TtsParams:
    return TtsParams(  # type: ignore[arg-type]
        text_lang="zh",
        speed_factor=0.85,
        temperature=0.9,
        top_k=15,
        top_p=1.0,
        text_split_method="cut5",
    )


def _ref(tmp_path: Path) -> RefAudio:
    path = tmp_path / "ref.wav"
    path.write_bytes(b"RIFF....WAVEfmt ")
    return RefAudio(path=str(path), text="你好", lang="zh")


def _wav_bytes(*, seconds: float = 0.2, rate: int = 32000) -> bytes:
    """非静音 PCM16 单声道 wav（``\x01\x00`` 样本＝过得了体检闸的最小真件）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return buf.getvalue()


def _arm(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """引擎与清理器都换替身；清理器的**调用记录**交回调用侧断言（不靠抛异常）。

    为什么不用「替身里 raise」：``synthesize`` 那一腿外面是 ``except Exception``
    （配额清理失败不影响主链路），``AssertionError`` 会被静默吃掉 ⇒ 注毒腿当场变
    空转（同族教训见工单 §5 记的别席无牙锁）。
    """
    seen: list[dict[str, Any]] = []

    def _fake_quota(directory: object, *, max_bytes: int = 0, max_age_days: int = 0) -> dict[str, int]:
        seen.append({"dir": directory, "max_bytes": max_bytes, "max_age_days": max_age_days})
        return {"files_removed": 0, "bytes_removed": 0}

    monkeypatch.setattr(tts_mod, "enforce_quota", _fake_quota)
    monkeypatch.setattr(tts_mod, "_request_tts", lambda **_k: (_wav_bytes(), ""))
    return seen


def _synth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **quota: object
) -> tuple[Path | None, str, list[dict[str, Any]]]:
    seen = _arm(monkeypatch)
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tts-older.wav").write_bytes(_wav_bytes())
    path, reason = synthesize(
        api_url=_API,
        text="正文",
        ref=_ref(tmp_path),
        params=_params(),
        output_dir=out_dir,
        **quota,  # type: ignore[arg-type]
    )
    return path, reason, seen


# ---------------------------------------------------------------------------
# ② 形态闸：单元面 + 行为面（注毒腿 + 反向不误伤腿）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (1024, 1024),
        (256 * 1024 * 1024, 256 * 1024 * 1024),
        (True, 0),  # int(True)==1 ⇒ 「上限 1 字节」＝清空目录，必须当未设
        (False, 0),
        (-5, 0),
        ("1024", 0),  # dotenv 直送的字符串不是数字上限
        (None, 0),
        (1.5, 0),
    ],
)
def test_quota_bound_accepts_only_non_negative_ints(value: object, expected: int) -> None:
    assert tts_mod._quota_bound(value) == expected


def test_bool_quota_never_reaches_the_sweeper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒腿：``quota_max_bytes=True``（等价 1 字节）不得触达清理器，目录一枚不少。"""
    path, reason, seen = _synth(tmp_path, monkeypatch, quota_max_bytes=True, quota_max_age_days=True)

    assert path is not None and reason == ""
    assert seen == [], f"布尔配额仍然触达了清理器：{seen}"
    assert path.is_file() and (tmp_path / "out" / "tts-older.wav").is_file()


@pytest.mark.parametrize("value", ["1024", -5, None, 1.5])
def test_other_non_int_quotas_never_reach_the_sweeper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    path, _reason, seen = _synth(tmp_path, monkeypatch, quota_max_bytes=value)
    assert seen == [], f"{value!r} 触达了清理器"
    assert path is not None


def test_int_quota_is_forwarded_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反向不误伤腿：正常整数配额照旧原样交给中央清理器（U-04 语义一字未动）。"""
    path, reason, seen = _synth(tmp_path, monkeypatch, quota_max_bytes=1024, quota_max_age_days=7)

    assert path is not None and reason == ""
    assert len(seen) == 1
    assert seen[0]["max_bytes"] == 1024 and seen[0]["max_age_days"] == 7
    assert Path(str(seen[0]["dir"])) == (tmp_path / "out").resolve()


def test_one_byte_quota_really_does_empty_the_directory(tmp_path: Path) -> None:
    """事故重现（用**真**中央件）：``max_bytes=1`` 就是把目录清空——「布尔→1」不是理论风险。

    这一腿不为门服务，只为把前提写成证据：哪天它不红了，说明 ``enforce_quota`` 的
    语义变了，本席这枚形态闸就得重判（不许悄悄留着一条已失效的账）。
    """
    from plugins.bot_unified_runtime.domains.chat_reply.runtime.cache_policy import (
        enforce_quota,
    )

    root = tmp_path / "tts_output"
    root.mkdir()
    for index in range(3):
        (root / f"tts-{index}.wav").write_bytes(b"x" * 4096)

    report = enforce_quota(root, max_bytes=1, max_age_days=0)

    assert report["files_removed"] == 3, report
    assert not list(root.glob("*.wav"))


# ---------------------------------------------------------------------------
# ① 现状债账：缺省不收盘 + LRU 只封顶内存（记的是债，不是成绩）
# ---------------------------------------------------------------------------


def test_default_quota_leaves_every_artifact_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺省 0/0 ⇒ 四句四枚文件全留在盘上，清理器一次没被问。

    配额两键被主会话按 ``B1-CONFIG-REQUEST`` 改成非 0 缺省时，这一腿必须随之改写——
    它存在的目的就是把「继续按现状记账」变成一次显式改动。
    """
    seen = _arm(monkeypatch)
    root = tmp_path / "out"
    root.mkdir()
    for index in range(4):
        path, reason = synthesize(
            api_url=_API,
            text=f"第 {index} 句",
            ref=_ref(tmp_path),
            params=_params(),
            output_dir=root,
        )
        assert path is not None and reason == ""

    assert seen == [], "缺省 0/0 触达了清理器"
    assert len(list(root.glob("tts-*.wav"))) == 4


def test_lru_eviction_bounds_memory_only_not_the_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一格债的第二面：LRU 封顶**索引**，被踢掉的产物留在盘上没人管。

    刻意不在这里加「淘汰即删盘」：发送队列的 part 级幂等 / UNKNOWN 确认 / PARTIAL
    断点续发都可能还引用着那枚路径（M-38 死引用摘段在册），淘汰时删盘会把「可续发」
    变成「发不出去」。正解是配额那一格（见 CONFIG-REQUEST），不是另起一把尺。
    """
    index: OrderedDict[str, tuple[Path, float]] = OrderedDict()
    monkeypatch.setattr(tts_mod, "_CACHE", index)
    files: list[Path] = []
    for slot in range(tts_mod._CACHE_LRU_CAP + 3):
        item = tmp_path / f"tts-{slot}.wav"
        item.write_bytes(b"RIFF")
        files.append(item)
        tts_mod._store_cache(f"key-{slot}", item)

    assert len(index) == tts_mod._CACHE_LRU_CAP, "LRU 封顶失效＝内存无界"
    assert all(item.is_file() for item in files), "本格前提变了（淘汰开始删盘）"


def test_cache_is_on_by_default_while_the_quota_is_off() -> None:
    """缺省三枚一次读齐：缓存开、两枚配额 0（＝不限制）。数字真身仍只住 ``config.py``。"""
    from plugins.bot_unified_runtime.config import Config

    fields = Config.model_fields
    assert fields["bot_tts_cache_enabled"].default is True
    assert fields["bot_tts_cache_max_bytes"].default == 0
    assert fields["bot_tts_cache_max_age_days"].default == 0


# ---------------------------------------------------------------------------
# ③ 接线锁：每枚 synthesize 调用点都交出旋钮
# ---------------------------------------------------------------------------


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    mapping: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            mapping[child] = node
    return mapping


def _holder_of(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _callsites_in(source: str) -> list[tuple[str, tuple[str, ...]]]:
    """[(所在函数, 漏交的旋钮)]——只认 ``synthesize(...)`` / ``synth_fn(...)`` 直呼形。

    不可解析的源码返回空表并跳过（**并发在飞**：别的席正写着某枚文件时它可能瞬时
    不语法，本格不该替那一枚记账——语法红归 pytest collection 与 lint 门管）。
    """
    try:
        with warnings.catch_warnings():
            # 生产文件里正则有非 raw 的 ``\S`` ⇒ ast.parse 会报 SyntaxWarning。
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source)
    except SyntaxError:
        return []
    parents = _parent_map(tree)
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name not in {"synthesize", "synth_fn"}:
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg}
        found.append((_holder_of(node, parents), tuple(k for k in REQUIRED_KNOBS if k not in kwargs)))
    return found


def measure_synthesize_callsites() -> set[tuple[str, str]]:
    """现算全生产面的调用点集合（棘轮的分母）。"""
    hits: set[tuple[str, str]] = set()
    for path in PKG_ROOT.rglob("*.py"):
        label = path.relative_to(REPO_ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        try:
            hits |= {(label, holder) for holder, _missing in _callsites_in(source)}
        except SyntaxError:  # pragma: no cover
            continue
    return hits


def test_every_synthesize_callsite_forwards_cache_and_quota_knobs() -> None:
    """三枚路必须逐枚交齐旋钮：漏一枚＝那条路径的产物永远没人回收而全树照绿。"""
    offenders: list[str] = []
    for path in PKG_ROOT.rglob("*.py"):
        label = path.relative_to(REPO_ROOT).as_posix()
        for holder, missing in _callsites_in(path.read_text(encoding="utf-8")):
            if missing:
                offenders.append(f"{label}::{holder} 缺 {missing}")
    assert offenders == [], "synthesize 调用点漏交旋钮：\n" + "\n".join(offenders)


def test_synthesize_callsite_roster_matches_the_tree_exactly() -> None:
    """零余量：调用点集合（文件, 函数）逐枚等于现算账——多一路少一路都红。"""
    assert measure_synthesize_callsites() == set(SYNTHESIZE_CALLSITES)


def test_callsite_scan_has_teeth() -> None:
    """注毒自证：新写一枚漏交配额的调用点，尺必须认出来；补齐后必须放行。"""
    poison = """
def new_voice_leg(config):
    path, reason = synthesize(api_url="u", text="t", ref=r, params=p, output_dir=d)
    return path
"""
    found = _callsites_in(poison)
    assert len(found) == 1, found
    holder, missing = found[0]
    assert holder == "new_voice_leg"
    assert set(missing) == {"cache_enabled", "quota_max_bytes", "quota_max_age_days"}

    clean = """
def new_voice_leg(config):
    path, reason = synthesize(
        api_url="u", text="t", ref=r, params=p, output_dir=d,
        cache_enabled=True, quota_max_bytes=1, quota_max_age_days=1,
    )
    return path
"""
    assert _callsites_in(clean) == [("new_voice_leg", ())]
