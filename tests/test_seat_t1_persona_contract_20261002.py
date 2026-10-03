"""T1 席（2026-10-02 续批）人格契约锁：切人格要真的换到文本腿与意象腿（SEATS.md §16）。

开工现算的三条现状（全部可复跑，见工单 `patches/T1-PERSONA-CONTRACT-20261002.md`）：

1. **意象腿当日整条死**。`personas/shorekeeper/imagery_families.txt` 不在盘上（未跟踪件被
   主树还原吃掉，`HANDOFF-RESCUE-20260930.md` 点名「25 枚无正文」里就有它一枚），
   `imagery_roster.load_imagery_families("shorekeeper")` 现算读出 **0 族**；因此
   `reply_policy_section_for_turn` 对**任何** persona_id 都不派意象行。连带后果比"少一句提示"
   更坏：在册尺 `test_imagery_family_names_are_not_hardcoded_in_code` 的扫描集来自名册，
   名册空 ⇒ 它扫的是空集 ⇒「意象名词禁抄进代码」当场零执法（该尺自带头带话的
   「名册没读出来 ⇒ 这条尺是空跑的」注毒腿，当日确实为红）。
   本波恢复＝从 `ChatBot_Archive/2026-09-29/wip-snapshot/uncommitted-wip-20260928T235244Z.zip`
   取回**逐字节**正本（sha256 与 `scripts/persona_sync_anchor.json` 的审阅凭证相等，
   见本件 ②），零重写零润色——人格资产按 AGENTS 规则 8 不动一个字。
2. **文本腿（称呼词表）读的根与名册不是一根**。`domains/chat_reply/runtime/aliases.py`
   原先以 `Path("personas") / …` 相对 cwd 取词表，而意象名册 `imagery_roster._repo_root()`、
   人格册 `persona_profile._REPO_ROOT`、术语表 `glossary` 都是包内绝对根。cwd 不等于仓库根
   时词表读空，`DEFAULT_PERSONA_NICKNAMES`（**主人格**的策展昵称）静默顶上来 ⇒
   切了人格、称呼还是原来那套，日志一切正常（台账 #66★ 同型：盘上≠运行时）。
   今天这个洞被"aliases.txt 内容与兜底表逐字相同"掩着（`test_nickname_default_seed.py`
   的 `test_default_seed_matches_persona_file` 锁着两者同齐），所以它只会在下一次词表演进
   或新增人格档时咬人——本件 ③ 把它现算出来。
3. **`voice.tts_refs` 不是幽灵字段**，撤不得也接不得：H-3「只声明未接线」由在册三把锁钉住
   （`test_seat_feat_persona_prof.py` 的 `test_tts_refs_has_zero_production_consumers_today`
   要求生产树消费点恒 0 枚、`test_registered_profiles_keep_tts_refs_empty_with_unwired_note`
   要求在册册值必须为空且带「未接线」注记、`test_tts_refs_scan_catches_poisoned_consumer`
   注毒自证），接线属另一批（下发腿在 TTS 能力面，音色真身目前只跟 `BOT_TTS_REF_AUDIOS`
   这枚 config、不跟人格）。本件不建第二把尺，只在 ⑤
   把三腿读数一次摊开：某一腿既不接也不声明＝当场红。

本件五把锁，每把都配注毒腿与反向不误伤腿：
① 名册真身读出非空（走默认真身根，不喂 root）；② 恢复件与审阅凭证逐字节相等；
③ 人格附属资产同一根 + 词表读侧与 cwd 无关；④ 意象派发行走**现役人格**、在册无册＝诚实
缺席绝不借别人家、占位档才回落 config；⑤ 在册人格三腿（意象名册／设定正文／音色）逐腿
要么实装要么显式声明缺席（danya 走"明写缺席"，理由见在册裁定，席不替新人格编世界观）。
另附 ⑥ 自锁：本件一个字都没抄人格侧族名（红线「意象名词禁抄进代码」对本席同样成立）。

离线纪律：全程不建库连接（`store=None`、`person_key=""`）、不 import 生产 `Config`
（`.env` 的 Runtime 根直指生产库）、不写 `personas/**`、`BOT_AUTOSYNC=0` 下运行。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.character import (
    imagery_roster as ir,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    persona_profile as pp,
)
from plugins.bot_unified_runtime.domains.chat_reply.character import (
    reply_policy as rp,
)
from plugins.bot_unified_runtime.domains.chat_reply.runtime import aliases as al

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOREKEEPER = "shorekeeper"
DANYA = "danya"
ROSTER_REL = f"personas/{SHOREKEEPER}/{ir.ROSTER_FILE_NAME}"
ANCHOR_PATH = REPO_ROOT / "scripts" / "persona_sync_anchor.json"

#: 现役人格派发到提示里的行形态（真身＝reply_policy_section_for_turn 的渲染串）。
_IMAGERY_LINE_RE = re.compile(r"- 本轮意象从「([^」]+)」")


class _StubConfig:
    """只提供名册读侧真正取用的两枚字段；绝不 import 生产 Config（会指向生产 Runtime 根）。"""

    def __init__(self, profile_id: str, defaults: str = "literary_prose") -> None:
        self.bot_persona_profile_id = profile_id
        self.bot_reply_default_directives = defaults


def _varied_policy() -> rp.ReplyPolicy:
    """钉了「换意象」的策略：只有钉了这个名字册才会被派发（在册口径）。"""
    return rp.ReplyPolicy(
        person_key="t1-seat-probe",
        length_mode="verbose",
        content_directives=("varied_imagery",),
    )


def _dispatch(
    persona_id: str,
    configured_profile: str,
    *,
    root: Path | None = None,
    policy: rp.ReplyPolicy | None = None,
) -> str:
    """现算一轮派发正文；store=None ＋ person_key="" ⇒ 结构上不可能写库。"""
    return rp.reply_policy_section_for_turn(
        policy if policy is not None else _varied_policy(),
        config=_StubConfig(configured_profile),
        store=None,
        person_key="",
        persona_id=persona_id,
        root=root,
    )


# ---------------------------------------------------------------------------
# ① 名册真身读出非空（缺席必须被点名，不许静默塌成空池）
# ---------------------------------------------------------------------------

def _roster_violations(root: Path, profile_id: str) -> list[str]:
    """纯函数：名册这条腿的读数。真身根干净时返回空表，缺件/读空/撞名/缺提示都点名。"""
    roster_path = root / "personas" / profile_id / ir.ROSTER_FILE_NAME
    if not roster_path.is_file():
        return [f"名册文件缺席：personas/{profile_id}/{ir.ROSTER_FILE_NAME}"]
    families = ir.load_imagery_families(profile_id, root=root)
    names = [str(f.name).strip() for f in families]
    problems: list[str] = []
    if not names:
        problems.append(f"名册在盘而读出 0 族（解析口径或编码坏了）：{roster_path.name}")
    if len(set(names)) != len(names):
        problems.append(f"族名重复＝轮换必撞名：{names}")
    if any(not name for name in names):
        problems.append("有空族名＝提示行会塌")
    if any(not str(family.cue).strip() for family in families):
        problems.append("有族没有取材提示＝名册自己声明的「族名｜取材提示」格式被破坏")
    return problems


def test_shipped_roster_reads_nonempty_from_the_default_root() -> None:
    """真身根（不喂 root 参数）必须读出非空池，且池子撑得起一轮轮换。

    「非空」是本席头号判据：0 族时那把「意象名词禁抄进代码」的在册尺扫的是空集。
    """
    families = ir.load_imagery_families(SHOREKEEPER)
    assert families, "守岸人意象名册读出为空 ⇒ 意象腿整条死（在册尺同时空跑）"
    names = [f.name for f in families]
    assert len(set(names)) == len(names), names
    assert all(str(name).strip() for name in names), names
    # 轮换判据：至少够派一轮派发数且互不重复（派发数以真身常数为尺，本件不另立数）。
    picked = ir.choose_imagery_families(families, count=rp._IMAGERY_PICK_COUNT)
    assert len(picked) == rp._IMAGERY_PICK_COUNT, (picked, len(families))
    assert len(set(picked)) == len(picked), picked
    assert _roster_violations(REPO_ROOT, SHOREKEEPER) == []


def test_roster_absence_is_reported_not_silent(tmp_path: Path) -> None:
    """注毒腿：把名册换到没有该文件的根 ⇒ 尺必须点名（证明 ① 不是空跑）。"""
    violations = _roster_violations(tmp_path, SHOREKEEPER)
    assert violations, "名册缺席未被报出 ⇒ 这条尺是空跑的"
    assert "缺席" in violations[0]
    # 反向不误伤：文件在而内容只有注释 ⇒ 判「读出 0 族」，不误判成「文件缺席」。
    persona_dir = tmp_path / "personas" / SHOREKEEPER
    persona_dir.mkdir(parents=True)
    (persona_dir / ir.ROSTER_FILE_NAME).write_text("# 只有注释\n\n", encoding="utf-8")
    second = _roster_violations(tmp_path, SHOREKEEPER)
    assert second and "0 族" in second[0], second


# ---------------------------------------------------------------------------
# ② 恢复件逐字节＝审阅凭证（人格资产不许被顺手改写；AGENTS 规则 8）
# ---------------------------------------------------------------------------

def _anchor_hash(anchor: object) -> str:
    if not isinstance(anchor, dict):
        return ""
    snapshot = anchor.get("source_snapshot")
    if not isinstance(snapshot, dict):
        return ""
    return str(snapshot.get(ROSTER_REL, "") or "")


def _sha_drift(live_bytes: bytes, expected: str) -> str:
    """纯函数：实盘字节与锚定哈希不等 ⇒ 返回点名串；相等 ⇒ 空串。"""
    if len(expected) != 64:
        return f"锚定里 {ROSTER_REL} 的哈希不是 64 位十六进制：{expected!r}"
    actual = hashlib.sha256(live_bytes).hexdigest()
    if actual != expected:
        return f"名册被改过：现 sha256={actual[:16]}… ≠ 审阅凭证 {expected[:16]}…"
    return ""


def test_restored_roster_is_byte_exact_against_the_review_anchor() -> None:
    """恢复＝逐字节取回正本：与 `scripts/persona_sync_anchor.json` 的审阅凭证必须相等。

    这条锁同时是「本席没润色人格资产」的证明——名册里任何一个字被改都会红；
    她日后真要改名册，就得按 `sync_persona_source.py --adopt` 重锚，两边一起动。
    """
    anchor = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
    expected = _anchor_hash(anchor)
    live = (REPO_ROOT / Path(*ROSTER_REL.split("/"))).read_bytes()
    assert _sha_drift(live, expected) == "", _sha_drift(live, expected)


def test_byte_exactness_lock_has_teeth() -> None:
    """注毒腿：改一个字节就必须红；反向不误伤：原字节必须放行，锚里没这格也要点名。"""
    anchor = json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))
    expected = _anchor_hash(anchor)
    live = (REPO_ROOT / Path(*ROSTER_REL.split("/"))).read_bytes()
    assert _sha_drift(live, expected) == ""
    assert _sha_drift(live + b"\n# tampered", expected), "改字节未被扫出 ⇒ 尺是空跑"
    assert _sha_drift(live, ""), "锚里缺这一格却放行 ⇒ 尺是空跑"


# ---------------------------------------------------------------------------
# ③ 人格附属资产＝同一根，且词表读侧与 cwd 无关
# ---------------------------------------------------------------------------

def _cwd_relative_persona_reads(tree: Path) -> list[str]:
    """AST 扫「`Path("personas"…)` 相对 cwd 读人格资产」形态；注释与 docstring 不算。"""
    hits: list[str] = []
    for py in sorted(tree.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        try:
            parsed = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError, OSError):  # pragma: no cover - 坏件不参与判定
            continue
        for node in ast.walk(parsed):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Path"
                and node.args
            ):
                continue
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and first.value.split("/")[0] == "personas"
            ):
                hits.append(f"{py.relative_to(tree)}:{node.lineno}")
    return hits


def test_persona_asset_files_share_one_root() -> None:
    """名册根＝人格册根＝词表根（`aliases.py` 原用 cwd 相对路径，本波并进来）。"""
    assert al._REPO_ROOT == REPO_ROOT, al._REPO_ROOT
    assert ir._repo_root() == REPO_ROOT, ir._repo_root()
    assert pp._REPO_ROOT == REPO_ROOT, pp._REPO_ROOT
    assert pp.DEFAULT_REGISTRY_DIR == REPO_ROOT / "personas" / "registry"


def test_alias_read_is_cwd_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """文本腿读数与 cwd 无关：把 cwd 挪到仓库外，词表仍必须从同一根读出来。

    这一格就是「切人格只换外观」的机理现场：读空 ⇒ `DEFAULT_PERSONA_NICKNAMES`
    （主人格策展九名）顶上 ⇒ 换了人格还被旧人格的称呼叫应，而盘上文件一切正常。
    比对口径不在这儿重写一遍（免得长出第二把切尺）：只问「读到的每一枚都在词表正文里」
    与「两次 cwd 的读数逐枚相等」。
    """
    cfg = _StubConfig(SHOREKEEPER)
    raw = (REPO_ROOT / "personas" / SHOREKEEPER / "aliases.txt").read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    outside = al._load_persona_alias_file(cfg)
    monkeypatch.chdir(REPO_ROOT)
    inside = al._load_persona_alias_file(cfg)
    assert outside, "cwd 一出仓库根词表就读空 ⇒ 两根本不是一根（文本腿塌回主人格兜底表）"
    assert outside == inside, (outside, inside)
    assert len(outside) >= 2, outside
    assert all(term in raw for term in outside), "读到的昵称不在词表正文里 ⇒ 读侧串了源"


def test_alias_read_names_the_persona_without_a_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """在册人格没有自己的词表＝缺席（只留 debug），绝不 WARN 刷屏也不许被当成"读到了"。"""
    cfg = _StubConfig(DANYA)
    monkeypatch.chdir(tmp_path)
    with caplog.at_level("DEBUG"):
        assert al._load_persona_alias_file(cfg) == []
    assert not [r for r in caplog.records if r.levelname == "WARNING"], caplog.text


def test_no_cwd_relative_persona_asset_read_survives(tmp_path: Path) -> None:
    """第二根不许留下：生产树里 `Path("personas")` 形态必须为 0 枚。"""
    assert _cwd_relative_persona_reads(REPO_ROOT / "plugins") == []
    # 注毒腿：合成一件相对读法的文件，尺必须点名。
    bad = tmp_path / "bad_read.py"
    bad.write_text(
        'from pathlib import Path\n\n\ndef read(pid):\n'
        '    return (Path("personas") / pid / "aliases.txt").read_text(encoding="utf-8")\n',
        encoding="utf-8",
    )
    hits = _cwd_relative_persona_reads(tmp_path)
    assert any("bad_read.py" in hit for hit in hits), hits
    # 反向不误伤：绝对根写法＋只在注释/docstring 里提到该形态，都不许误报。
    good = tmp_path / "good_read.py"
    good.write_text(
        '"""这里只是散文提到 Path("personas") 的旧写法，不是代码。"""\n'
        "from pathlib import Path\n\n"
        "_REPO_ROOT = Path(__file__).resolve().parents[5]\n\n\n"
        "def read(pid):\n"
        '    return (_REPO_ROOT / "personas" / pid / "aliases.txt").read_text(encoding="utf-8")\n',
        encoding="utf-8",
    )
    assert not any("good_read.py" in hit for hit in _cwd_relative_persona_reads(tmp_path))


# ---------------------------------------------------------------------------
# ④ 意象派发按现役人格走；在册无册＝诚实缺席，绝不借别人家
# ---------------------------------------------------------------------------

def test_imagery_lines_follow_the_active_persona_not_the_configured_one() -> None:
    """现役人格是守岸人、config 出厂档是别格 ⇒ 仍按现役派族（切人格即换取材面）。"""
    section = _dispatch(SHOREKEEPER, DANYA)
    rendered = _IMAGERY_LINE_RE.findall(section)
    pool = [f.name for f in ir.load_imagery_families(SHOREKEEPER, root=REPO_ROOT)]
    assert len(rendered) == rp._IMAGERY_PICK_COUNT, (rendered, section[-200:])
    assert len(set(rendered)) == len(rendered), rendered
    assert all(name in pool for name in rendered), (rendered, pool)


def test_registered_persona_without_a_roster_reports_absent_and_never_borrows() -> None:
    """在册人格自己没名册＝这一轮诚实缺席：绝不回落端别人家的意象（台账 #66★／§54.9）。"""
    assert pp.PersonaProfileRegistry().get(DANYA) is not None, "前提不成立：达妮娅不在册"
    assert ir.load_imagery_families(DANYA, root=REPO_ROOT) == (), "达妮娅有名册 ⇒ 本锁前提变了"
    section = _dispatch(DANYA, SHOREKEEPER)
    assert not _IMAGERY_LINE_RE.findall(section), section[-240:]
    # 策略正文本身不许一起塌掉（缺席只该少意象那一行）。
    assert "varied_imagery" in section or "意象" in section


def test_placeholder_persona_falls_back_to_the_configured_profile() -> None:
    """不在册的占位档名（`default` 一类）才回落 config 档——这条不许被 ④ 上一格误吃。"""
    assert pp.PersonaProfileRegistry().get("default") is None, "default 已在册 ⇒ 回落语义要重裁"
    section = _dispatch("default", SHOREKEEPER)
    assert len(_IMAGERY_LINE_RE.findall(section)) == rp._IMAGERY_PICK_COUNT, section[-240:]


def test_persona_without_directive_gets_no_imagery_lines() -> None:
    """没钉「换意象」的人一条不派也不写账（陌生人零成本，在册口径）。"""
    section = rp.reply_policy_section_for_turn(
        rp.ReplyPolicy(person_key="t1-seat-probe", length_mode="verbose"),
        config=_StubConfig(SHOREKEEPER),
        store=None,
        person_key="",
        persona_id=SHOREKEEPER,
    )
    assert not _IMAGERY_LINE_RE.findall(section), section[-240:]


# ---------------------------------------------------------------------------
# ⑤ 人格契约三腿：要么实装、要么明写缺席（danya 那一格走后者）
# ---------------------------------------------------------------------------

#: 三腿真身：意象取材面（人格侧名册）／文本腿（在册设定正文清单）／音色腿（tts 参考音）。
PERSONA_LEGS: tuple[str, ...] = ("imagery_roster", "settings_text", "voice_tts")

#: 缺席声明表：(人格, 腿) → 理由（必须带在册指针）。席不替新人格编世界观（规则 8），
#: 也不替 §49.9 数据批决定文本腿素材；音色腿按 H-3 在册「只声明未接线」。
DECLARED_ABSENT: dict[tuple[str, str], str] = {
    (DANYA, "imagery_roster"): (
        "达妮娅没有自己的意象名册；补名册＝替新人格编世界观，属人格资产（AGENTS 规则 8），"
        "两选一留给用户（docs/HANDBOOK.md §54.9、台账 #66★：在册人格无意象册＝诚实缺席）"
    ),
    (DANYA, "settings_text"): (
        "达妮娅设定正文材料册外不存在（personas/registry/danya.json 的 _files_note；"
        "HANDBOOK §49.9 只给昵称/签名/头像与六展示格），切换回执须如实报「未落」"
    ),
    (DANYA, "voice_tts"): "H-3 只声明未接线（tests/test_seat_feat_persona_prof.py:139/:149）",
    (SHOREKEEPER, "settings_text"): (
        "主人格文本腿刻意留空：在册 files.settings 非空会压过 .env BOT_PERSONA_FILES 的蒸馏正身，"
        "并劫持 test_persona_injection_v21 的离线锁（personas/registry/shorekeeper.json 的 _files_note）"
    ),
    (SHOREKEEPER, "voice_tts"): "H-3 只声明未接线（tests/test_seat_feat_persona_prof.py:139/:149）",
}


def _registered_persona_registers() -> list[tuple[str, dict]]:
    entries: list[tuple[str, dict]] = []
    for path in sorted(pp.DEFAULT_REGISTRY_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            entries.append((str(payload.get("persona_id") or path.stem), payload))
    return entries


def _leg_wired(profile_id: str, leg: str, register: dict) -> bool:
    """某一腿此刻是否真的实装（读数全部现算，不抄册子里的注记文本）。"""
    if leg == "imagery_roster":
        return bool(ir.load_imagery_families(profile_id, root=REPO_ROOT))
    files = register.get("files")
    files = files if isinstance(files, dict) else {}
    if leg == "settings_text":
        return bool(files.get("settings"))
    voice = register.get("voice")
    voice = voice if isinstance(voice, dict) else {}
    return bool(voice.get("tts_refs"))


def _leg_violations(
    entries: list[tuple[str, dict]], declared: dict[tuple[str, str], str]
) -> list[str]:
    problems: list[str] = []
    for profile_id, register in entries:
        for leg in PERSONA_LEGS:
            reason = str(declared.get((profile_id, leg), "") or "").strip()
            if _leg_wired(profile_id, leg, register):
                if reason:
                    problems.append(f"{profile_id}/{leg} 已实装却仍挂着缺席声明＝假账")
                continue
            if len(reason) < 20:
                problems.append(
                    f"{profile_id}/{leg} 既未实装也未明写缺席（声明要带在册指针、≥20 字）"
                )
    return problems


def test_every_registered_persona_leg_is_wired_or_declared_absent() -> None:
    """人格契约总闸：三腿逐格要么实装要么在册声明，新增人格没决定＝当场红。"""
    entries = _registered_persona_registers()
    assert entries, "人格册目录为空 ⇒ 本锁前提不成立"
    assert {pid for pid, _ in entries} == {SHOREKEEPER, DANYA}, [pid for pid, _ in entries]
    assert _leg_violations(entries, DECLARED_ABSENT) == []
    # 意象腿（本波修的那一格）必须在册人格里至少实装一格，否则整条腿又成静默死。
    assert any(_leg_wired(pid, "imagery_roster", reg) for pid, reg in entries)


def test_contract_gate_has_teeth(tmp_path: Path) -> None:
    """注毒腿：新人格三腿全空又没声明 ⇒ 必须三枚点名；反向不误伤：声明齐了即放行。"""
    ghost = ("ghost", {"files": {"settings": []}, "voice": {"tts_refs": []}})
    violations = _leg_violations([ghost], {})
    assert len(violations) == len(PERSONA_LEGS), violations
    assert all("ghost" in line for line in violations), violations
    declared = {(DANYA, leg): "理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由在册指针" for leg in PERSONA_LEGS}
    assert _leg_violations([(DANYA, {"files": {}, "voice": {}})], declared) == []
    # 反向的第二枚：已实装还挂着声明＝假账，也要红。
    stale = {(SHOREKEEPER, "imagery_roster"): "理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由理由在册指针"}
    assert _leg_violations([(SHOREKEEPER, _shorekeeper_register())], stale), "实装却仍声明缺席未被报出"


def _shorekeeper_register() -> dict:
    path = pp.DEFAULT_REGISTRY_DIR / f"{SHOREKEEPER}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


# ---------------------------------------------------------------------------
# ⑥ 自锁：本件没有把人格侧族名抄进代码
# ---------------------------------------------------------------------------

def test_this_lock_file_does_not_copy_the_roster() -> None:
    """红线「意象名词禁抄进代码」对本席同样成立：名册族名一个字都不许出现在本件里。"""
    source = Path(__file__).read_text(encoding="utf-8")
    pool = [f.name for f in ir.load_imagery_families(SHOREKEEPER, root=REPO_ROOT)]
    assert pool, "名册读空 ⇒ 这条自锁是空跑的（先修 ①）"
    leaked = [name for name in pool if name in source]
    assert not leaked, f"本件抄了人格侧族名：{leaked}"
    # 尺有牙：把任一族名塞进一句散文，必须被同一把尺抓出来。
    poisoned = f"随便一句提到 {pool[0]} 的注释"
    assert [name for name in pool if name in poisoned], "注毒未打红 ⇒ 自锁空跑"


def test_roster_pool_is_traceable_to_the_persona_book() -> None:
    """名册不是无根之水：族名与取材提示都要能在人格正文里找到落点（抽查读数，不判数量）。

    这条锁只证「名册与人格正文同源」这件事可被现算读出来——族名一律取自本波恢复的正本，
    本件因此仍然一个字都没抄（见 ⑥）。
    """
    families = ir.load_imagery_families(SHOREKEEPER, root=REPO_ROOT)
    body = (REPO_ROOT / "personas" / SHOREKEEPER / "identity.md").read_text(encoding="utf-8")
    hits = [f.name for f in families if any(tok and tok in body for tok in re.split(r"[、；，,]", f.cue)[:3])]
    assert hits, "名册取材提示在人格正文里一个落点都找不到 ⇒ 出处链断了"
