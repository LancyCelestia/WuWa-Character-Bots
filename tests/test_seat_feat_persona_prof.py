"""S-FEAT-PERSONA-PROF 人格册三把补锁（2026-09-27 席位波）。

本票的 profile 册（``personas/registry/<persona_id>.json``）与热读加载器
``persona_profile.py`` 已由同波人格线落盘（H-5乙：一号一册、``(mtime_ns,size)``
签名热读、``.env`` 的兼容位只兜未在册人格）；热读/回执/头像闸等锁已在
``test_persona_hot_switch.py`` / ``test_seat_fix_persona_r2.py`` /
``test_seat_impl_persona_qqleg.py`` / ``test_seat_kblist_hot_lock.py`` /
``test_persona_wiring_lock.py`` 立住。本件只补三把**当时缺失**的锁，不建第二真身：

① 等值锁：守岸人册与 ``.env`` ``BOT_PERSONA_DISPLAY_NAME``（经
   ``current_bot_nickname`` 现读口）逐字段等值——防「改了 .env 忘改册」的漂移；
   个性签名今天无第二真身（册即唯一事实源），故只锁昵称面，照实在下方注记。
② ``tts_refs`` 只声明不消费锁（H-3）：生产树（``plugins/`` + ``scripts/``）
   对 ``record.tts_refs`` 属性读取必须恒为 0 枚；在册 profile 的
   ``voice.tts_refs`` 必须为空且携带「未接线」注记——先把值填进册子而不接线，
   本锁当场红。
③ 坏册 fail-closed 锁：单册 JSON 损坏 ⇒ 装载 warning **点名文件名**、该册被跳过
   不炸整册目录、主人格昵称回落兼容位（守岸人等值缺省），绝不塌成空自称。

注毒自证：①②均带参数化毒用例（合成目录/合成值下毒，产根文件零触碰），
③本身即对坏数据的杀伤力正例。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO_ROOT / ".env"


# ---------------------------------------------------------------------------
# ① 守岸人册 ⇄ .env 兼容显示名 等值锁
# ---------------------------------------------------------------------------

def _parity_violations(
    register_nickname: str,
    register_display_name: str,
    env_display_name: str,
) -> list[str]:
    """纯函数：返回不一致点名列表。等值判据＝去空白后逐字相等。"""
    problems: list[str] = []
    nickname = register_nickname.strip()
    display = register_display_name.strip()
    env_name = env_display_name.strip()
    if not nickname:
        problems.append("register qq.nickname is empty")
    if nickname != display:
        problems.append(
            f"register nickname {nickname!r} != display_name {display!r}"
        )
    if env_name and nickname != env_name:
        problems.append(
            f"register nickname {nickname!r} != .env BOT_PERSONA_DISPLAY_NAME {env_name!r}"
        )
    return problems


def _env_display_name() -> str:
    """离线现读 .env 的兼容显示名（无 .env 的干净检出返回空串⇒等值面自动缩为册内自洽）。"""
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover - 本仓依赖 dotenv，缺装即跳过比对面
        return ""
    if not _ENV_PATH.is_file():
        return ""
    values = dotenv_values(_ENV_PATH)
    return str(values.get("BOT_PERSONA_DISPLAY_NAME") or "")


def test_shorekeeper_register_parity_with_env_display_name() -> None:
    """活体锁：守岸人在册昵称 == .env 兼容显示名（经真实加载器现读）。"""
    registry = pp.PersonaProfileRegistry()  # 缺省目录＝真身 personas/registry/
    record = registry.get("shorekeeper")
    assert record is not None, "shorekeeper 人格册缺失（本锁的前提是同波落盘的主人格册）"
    assert record.is_main is True
    problems = _parity_violations(
        record.qq_nickname, record.display_name, _env_display_name()
    )
    assert not problems, "守岸人册与兼容位漂移：" + "；".join(problems)
    # 现读口一致性：current_bot_nickname（先册后兼容）必须回同一值
    stub = _StubConfig(record.display_name)
    assert pp.current_bot_nickname("shorekeeper", registry=registry, config=stub) == (
        record.qq_nickname.strip()
    )
    # 签名面注记：个性签名今天没有第二真身（册即唯一事实源，无 .env 键可比），
    # 故本锁不假装比签名，只要求主人格签名在册且非空（H-1 一次性切换需要它在场）。
    assert record.qq_signature.strip(), "shorekeeper 在册个性签名为空"


class _StubConfig:
    """只提供 bot_persona_display_name 一枚字段的兼容位替身（测试夹具）。"""

    def __init__(self, display_name: str) -> None:
        self.bot_persona_display_name = display_name


def test_parity_helper_catches_poisoned_drift() -> None:
    """注毒自证①：伪造「改了 .env 没改册」的漂移，等值判据必须点名。"""
    assert _parity_violations("守岸人", "守岸人", "达妮娅"), "漂移未被捕获"
    assert _parity_violations("", "守岸人", "守岸人"), "空昵称未被捕获"
    assert _parity_violations("守岸人", "漂泊者", "守岸人"), "册内不自洽未被捕获"
    # 反向锁：无 .env（干净检出）时册内自洽即放行，不误伤 CI 形态。
    assert _parity_violations("守岸人", "守岸人", "") == []


# ---------------------------------------------------------------------------
# ② tts_refs 只声明不消费锁（H-3）
# ---------------------------------------------------------------------------

_TTS_REFS_ATTR_READ = re.compile(r"\w\.tts_refs\b")
# persona_profile.py 是字段真身：dataclass 定义与构造点合法（无属性读形态，
# 但保留白名单防「把消费写进真身文件本身也算」被本锁漏放时说不清账）。
_TTS_REFS_ALLOWED_FILES = {"persona_profile.py"}


def _tts_refs_consumption_hits(root: Path) -> list[str]:
    """扫描一棵树里对 ``<obj>.tts_refs`` 的属性读取，返回 文件:行号 点名列表。"""
    hits: list[str] = []
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _TTS_REFS_ATTR_READ.search(line) and py.name not in _TTS_REFS_ALLOWED_FILES:
                hits.append(f"{py.relative_to(root)}:{lineno}")
    return hits


def test_tts_refs_has_zero_production_consumers_today() -> None:
    """H-3 在册未接线：全生产树对 record.tts_refs 的属性读取恒为 0 枚。"""
    hits: list[str] = []
    for sub in ("plugins", "scripts"):
        root = _REPO_ROOT / sub
        if root.is_dir():
            hits.extend(_tts_refs_consumption_hits(root))
    assert hits == [], f"tts_refs 出现消费点（H-3 接线批未在册声明即回潮）：{hits}"


def test_registered_profiles_keep_tts_refs_empty_with_unwired_note() -> None:
    """在册 profile 的 voice.tts_refs 必须为空数组且带「未接线」注记。

    把音色值填进册子而不先落下发腿＝登记「已可用」的假账，本锁当场红。
    """
    registry_dir = pp.DEFAULT_REGISTRY_DIR
    files = sorted(registry_dir.glob("*.json")) if registry_dir.is_dir() else []
    assert files, "人格册目录为空：本锁前提（同波落盘的在册 profile）不成立"
    for path in files:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        voice = payload.get("voice")
        assert isinstance(voice, dict), f"{path.name}: voice 节必须是对象"
        refs = voice.get("tts_refs", [])
        assert list(refs) == [], (
            f"{path.name}: tts_refs 填了值却无下发腿（H-3 只声明未接线）：{refs}"
        )
        status = str(voice.get("_status", ""))
        assert "未接线" in status, (
            f"{path.name}: voice 节缺「未接线」注记，接线批落地前先补账再清本注记"
        )


def test_tts_refs_scan_catches_poisoned_consumer(tmp_path: Path) -> None:
    """注毒自证②：合成树里放一个消费文件，扫描器必须点名；私有副本下毒，产根零触碰。"""
    pkg = tmp_path / "plugins" / "fake"
    pkg.mkdir(parents=True)
    (pkg / "wired_bad.py").write_text(
        "def consume(record):\n    return [record.tts_refs]\n", encoding="utf-8"
    )
    (pkg / "clean_ok.py").write_text(
        "def use_cfg(config):\n    return config.bot_tts_ref_audios\n", encoding="utf-8"
    )
    hits = _tts_refs_consumption_hits(tmp_path)
    assert any("wired_bad.py" in hit for hit in hits), "毒消费点未被扫出（锁是空跑）"
    assert not any("clean_ok.py" in hit for hit in hits), "无关近名误报"


# ---------------------------------------------------------------------------
# ③ 坏册 fail-closed + 兼容位回落 + 点名留痕
# ---------------------------------------------------------------------------


def test_corrupt_shorekeeper_register_falls_back_to_compat_and_names_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """主人格册 JSON 损坏 ⇒ warning 点名文件、该册被跳过、昵称回落兼容位。

    fail-closed 语义：坏册不得把自称塌成空串（卡片页脚/status 会拿兼容显示名兜底），
    也不得炸掉整个目录扫描（旁册正常在册）。
    """
    (tmp_path / "shorekeeper.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "danya.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "persona_id": "danya",
                "display_name": "达妮娅",
                "is_main": False,
                "qq": {"nickname": "达妮娅", "signature": "", "avatar_path": "", "sex": ""},
                "files": {"settings": [], "knowledge": []},
                "voice": {"tts_refs": [], "_status": "只声明未接线（H-3）"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stub = _StubConfig("守岸人（兼容位）")
    registry = pp.PersonaProfileRegistry(tmp_path)
    with caplog.at_level("WARNING"):
        assert registry.get("shorekeeper") is None, "坏册被误当可用记录"
        # 旁册不受连坐（fail-closed 是拒该册，不是拒整目录）
        assert registry.get("danya") is not None
        nickname = pp.current_bot_nickname(
            "shorekeeper", registry=registry, config=stub
        )
    assert nickname == "守岸人（兼容位）", "坏册未回落兼容位（自称塌空）"
    assert "shorekeeper.json" in caplog.text, "坏册未被 warning 点名到文件名"


def test_non_object_register_payload_is_skipped_with_note(tmp_path: Path) -> None:
    """册体不是 JSON 对象（如数组/裸字符串）⇒ 同样点名跳过，不产生半成品记录。"""
    (tmp_path / "broken.json").write_text('["not", "an", "object"]', encoding="utf-8")
    registry = pp.PersonaProfileRegistry(tmp_path)
    assert registry.all() == {}
