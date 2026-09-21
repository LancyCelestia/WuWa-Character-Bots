"""Wave 1 常驻门：中央调度层「禁第二调用点」+ files/search 通电端到端等值（U2 席）。

权威：``docs/design/capability-orchestration-adoption-spec.md`` §1 D-b / §4 Wave1 / §7。
一句话——接入的核心动作是「换调用点」，而换调用点唯一需要的**新增**机器门就是「同一能力的
生产调用点全树只准一处」。本件即那把门（D-b），并附被包装能力经 ``CapabilityInvoker`` 通电的
端到端离线等值证明（"接入不改变行为"）与"未接线→回落旧直调"的机制自证。

三层执法：
- **活性判据（真树）**：全树 AST 扫 files/search 真身的生产直呼点与 invoker 调用点，钉死当前 ledger；
  漂移（新增未审直呼点 / 第二 invoker 点 / 同模块半迁移）当场红。
- **注毒自证**：喂合成树证明每条不变量真的会红（防"存在性糊过活性判据"式假门）。
- **端到端等值**：files.read.code / search.web 经 invoker 产出 vs 直呼真身，逐字段相等；
  creation.tts.synthesize 未注册 handler → invoke 诚实 UNAVAILABLE（回落旧直调不崩）。

全离线：真身读文件 / 联网搜索全部 monkeypatch 为确定性替身，零真实 I/O、零消息发送。
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

# 真身/壳全部**延迟到用例内 import**：本门的纯扫描/注毒/活性判据不依赖中央模块能否成功 import，
# 以免被在飞波次（Wave2 `_build_capability_descriptor`）的 collection-time 崩连坐；
# 端到端等值用例才需要 invoker（届时 shell 必须可导入）。
_SHELL_REL = "runtime/capability_protocols.py"  # 受控适配器（懒 import 真身），非"直呼"
_PKG_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "bot_unified_runtime"  # …/bot_unified_runtime

# 真身符号 → 所属能力族（Wave1 所辖 files/search 面 + V1 席接入的 media 面）
_TRACKED: dict[str, str] = {
    "read_supported_file": "files.read",
    "build_web_search_provider": "search.web",
    "UnifiedSearchService": "search.unified",
    # media 族（V1 席，2026-09-21）：五条 descriptor 的实现真身。
    "describe_images": "media.vision",
    "search_saucenao_ex": "media.anime_ip",
    "transcribe_audio": "media.asr",
    "build_video_brief": "media.video_brief",
    "_extract_video_frames": "media.frames",
}
# 各真身的定义文件（不计入直呼点）：真身在**自己 module 内**的组合调用属实现细节
# （如 describe_images 内部抽帧、search_saucenao 兼容包装），不是"第二能力执行入口"。
_DEF_FILES: dict[str, set[str]] = {
    "read_supported_file": {"domains/files/sources/file_reader.py"},
    "build_web_search_provider": {"domains/core/search/web_search.py"},
    "UnifiedSearchService": {"domains/core/search/search_service.py"},
    "describe_images": {"domains/media/ingest/vision_describe.py"},
    "search_saucenao_ex": {"domains/media/search/sauce_search.py"},
    "transcribe_audio": {"domains/media/ingest/transcribe.py"},
    "build_video_brief": {"domains/media/ingest/video_understanding.py"},
    "_extract_video_frames": {"domains/media/ingest/vision_describe.py"},
}
# invoker 调用点归属：capability_id → 能力族（同族多成员按族计，全树每族恰一处）。
_FILES_SEARCH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("files.read", "files.read"),
    ("search.web", "search.web"),
    ("search.unified", "search.unified"),
)
#: media 八条 descriptor 的精确 id → 族（写全，不用前缀猜，防新 id 静默落错族）。
_MEDIA_CID_TO_CAP: dict[str, str] = {
    "media.vision.image": "media.vision",
    "media.vision.ocr": "media.vision",
    "media.vision.anime_ip": "media.anime_ip",
    "media.asr.speech": "media.asr",
    "media.asr.audio_file": "media.asr",
    "media.video.recognize": "media.video_brief",
    "media.video.subtitle": "media.video_brief",
    "media.video.frame_extract": "media.frames",
}


def _cid_to_cap(cid: str) -> str | None:
    if cid in _MEDIA_CID_TO_CAP:
        return _MEDIA_CID_TO_CAP[cid]
    for prefix, cap in _FILES_SEARCH_PREFIXES:
        if cid == prefix or cid.startswith(prefix + "."):
            return cap
    return None


# ---------------------------------------------------------------------------
# 纯扫描器（可喂真树或合成树，保证门"真会红"而非自证快照）
# ---------------------------------------------------------------------------
def _calls_symbol(tree: ast.AST, symbol: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == symbol:
            return True
        if isinstance(fn, ast.Attribute) and fn.attr == symbol:
            return True
    return False


# ---------------------------------------------------------------------------
# 直呼＝**能力执行**直呼；provider 注入不算（2026-09-21 Wave 1 主会话精化）
# 判据刻意是结构性的、不是白名单：调用（可穿过一层 lambda）作为「关键字实参」出现，
# 且关键字名以 provider / provider_factory 结尾 ⇒ 装配注入（把供应商交给别人用）。
# 反例（仍算执行直呼）：`provider = build_web_search_provider(cfg)` 再 `provider.search(...)`
# —— 赋给变量即用，是执行路径，绝不因"名字像 provider"而豁免。
# 第二个反例（R1/I-1 收口）：`Runner(web_search_provider=build_web_search_provider(cfg)).go()`
# —— 关键字位置没变，但承载调用被当场链式执行 ⇒ provider 是被执行的那枚对象，不豁免。
# ---------------------------------------------------------------------------
_INJECT_KW_SUFFIXES = ("provider", "provider_factory")


def _is_consumed(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """该表达式造出的对象**当场被成员访问/链式执行**（`X(...).go()`）⇒ 它就是执行路径。"""
    parent = parents.get(node)
    return isinstance(parent, ast.Attribute) and parent.value is node


def _is_injection(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    node: ast.AST = call
    for _ in range(3):  # 允许 Call ← Lambda ← keyword 这一层包装（factory lambda）
        parent = parents.get(node)
        if isinstance(parent, ast.keyword) and (parent.arg or "").endswith(_INJECT_KW_SUFFIXES):
            # 豁免只在「把造出来的整枚对象交出去」时成立。承载该关键字的调用若当场被
            # 链式执行（`Runner(web_search_provider=build_web_search_provider(cfg)).go()`），
            # provider 就是被执行的那枚对象 ⇒ 执行直呼，不豁免（2026-09-21 R1/I-1 收口）。
            return not _is_consumed(parents.get(parent, _MISSING), parents)
        if isinstance(parent, ast.Lambda):
            node = parent
            continue
        return False
    return False


_MISSING: ast.AST = ast.Constant(value=None)  # 「找不到父」的哨兵：无人消费，按注入处理。


def _execution_calls(tree: ast.AST, symbol: str) -> bool:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        hit = (isinstance(fn, ast.Name) and fn.id == symbol) or (
            isinstance(fn, ast.Attribute) and fn.attr == symbol
        )
        if hit and not _is_injection(node, parents):
            return True
    return False


def _injection_calls(tree: ast.AST, symbol: str) -> bool:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == symbol)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == symbol)
        )
        and _is_injection(node, parents)
        for node in ast.walk(tree)
    )


def _invoker_cids(tree: ast.AST) -> set[str]:
    """``….invoke(CapabilityRequest(capability_id="x", …))`` 中的能力 id 字面量。"""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "invoke":
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.keyword)
                    and sub.arg == "capability_id"
                    and isinstance(sub.value, ast.Constant)
                    and isinstance(sub.value.value, str)
                ):
                    found.add(sub.value.value)
    return found


def _rel(path: Path) -> str:
    return path.relative_to(_PKG_ROOT).as_posix()


def scan(index: dict[str, str]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """index = {相对包根路径: 源码}。返回 (直呼点 by 能力, invoker 点 by 能力)。"""
    direct: dict[str, set[str]] = {cap: set() for cap in _TRACKED.values()}
    invoker: dict[str, set[str]] = {cap: set() for cap in _TRACKED.values()}
    for rel, src in index.items():
        if rel == _SHELL_REL:
            continue  # 受控适配器不算直呼
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for symbol, cap in _TRACKED.items():
            if rel not in _DEF_FILES[symbol] and symbol in src and _execution_calls(tree, symbol):
                direct[cap].add(rel)
        for cid in _invoker_cids(tree):
            cap = _cid_to_cap(cid)
            if cap is not None:
                invoker[cap].add(rel)
    return direct, invoker


def check_invariants(
    direct: dict[str, set[str]],
    invoker: dict[str, set[str]],
    *,
    wired: set[str],
    allowlist: dict[str, set[str]],
) -> list[str]:
    """返回违规清单（空=满足 D-b）。三条不变量 + 通电后归零直呼。"""
    v: list[str] = []
    for cap in sorted(direct):
        if len(invoker[cap]) > 1:
            v.append(f"[{cap}] 第二调用点：invoker 调用模块 {len(invoker[cap])} 处（全树只准 1）：{sorted(invoker[cap])}")
        overlap = direct[cap] & invoker[cap]
        if overlap:
            v.append(f"[{cap}] 半迁移：同模块既直呼真身又走 invoker：{sorted(overlap)}")
        unreviewed = direct[cap] - allowlist.get(cap, set())
        if unreviewed:
            v.append(f"[{cap}] 未登记直呼点（须先评审入 allowlist 或改走 invoker）：{sorted(unreviewed)}")
        if cap in wired:
            if direct[cap]:
                v.append(f"[{cap}] 已通电却仍直呼真身（禁第二路）：{sorted(direct[cap])}")
            if len(invoker[cap]) != 1:
                v.append(f"[{cap}] 已通电但 invoker 调用点非恰好一处（实 {len(invoker[cap])}）")
    return v


def _load_real_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for path in _PKG_ROOT.rglob("*.py"):
        rel = _rel(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # 廉价预筛：只把可能引用被追踪符号的源文件交给 AST 解析
        if any(sym in text for sym in _TRACKED) or "capability_id=" in text:
            index[rel] = text
    return index


# ---------------------------------------------------------------------------
# ① 活性判据：真树 = 当前 ledger（U2 未翻任何调用点；root 直呼面为 Wave-1 grandfathered）
# ---------------------------------------------------------------------------
# U2 独占面（domains/files/**、domains/core/search/**）内**无**直呼点可翻；
# 全部生产直呼点落在 root(U4)/control_plane/chat_reply/ops（见 SEAT-U2.md §0/§6）。
KNOWN_DIRECT_ALLOWLIST: dict[str, set[str]] = {
    "files.read": {"__init__.py", "control_plane/api/platform.py"},
    # 2026-09-21 Wave 1 + 分类精化：root 的 `/bot search` 已改走 invoker，root 与
    # ops/smoke/console_chat 剩下的都是 `web_search_provider=` / `..._factory=lambda:` 形式的
    # **供应商注入**（把 provider 交给别人用），按结构判据不再计为执行直呼。
    # ⇒ search.web 的执行直呼面从 3 缩到 1（backend_unit），登记随真值收紧，非豁免。
    "search.web": {"domains/chat_reply/pipeline/backend_unit.py"},
    "search.unified": set(),
    # ---- media 族（V1 席登记）-------------------------------------------------
    # 识图/转写/视频理解三条：真身直呼全在 **root 消费方 chat.py** 与 **control_plane**，
    # 两者都不在 V1 独占面（chat_reply 属 Wave3 末席、control_plane 属控制面席）⇒
    # 逐条评审登记为待翻面，V1 不越界代改（交接段 SEAT-V1 §柒）。
    "media.vision": {"domains/chat_reply/capabilities/chat.py", "control_plane/api/platform.py"},
    "media.asr": {"domains/chat_reply/capabilities/chat.py", "control_plane/api/platform.py"},
    "media.video_brief": {"domains/chat_reply/capabilities/chat.py"},
    # 反搜：V1 已翻面 ⇒ 直呼清零（见 WIRED）。
    "media.anime_ip": set(),
    # 抽帧两处直呼**故意保留**（V1 逐条核过＝切换不等值，证据见 SEAT-V1 §伍-2）：
    # media_archive 要自持落盘目录并整树 rmtree、且传自己的 vision_timeout，
    # 而壳 handler 硬编码 mkdtemp + 30s 且不清理 ⇒ 切换＝换行为，按铁律 2 不迁，
    # 已作为 descriptor 缺件候选写进交接段等主会话补 out_dir/timeout 透传。
    "media.frames": {
        "domains/media/capabilities/media_archive.py",
        "domains/media/ingest/video_understanding.py",
    },
}
#: 「通电」的定义＝该能力直呼清零 + invoker 调用点恰一处。
WIRED: set[str] = {"media.anime_ip"}

# 已登记的 invoker 调用点（Wave 1 首个=root `/bot search`；media 首个=V1 反搜）。
# 新增未登记点⇒红；登记点消失⇒也红。
KNOWN_INVOKER_SITES: dict[str, set[str]] = {
    "search.web": {"__init__.py"},
    "media.anime_ip": {"domains/media/capabilities/image_search.py"},
}


# ---------------------------------------------------------------------------
# 分类判据自证：注入≠执行，但"赋给变量再用"必须仍算执行（防分类变成新豁免洞）
# ---------------------------------------------------------------------------
_SRC_KWARG_INJECT = """
def _f(cfg):
    return build_pipeline(web_search_provider=build_web_search_provider(cfg))
"""

_SRC_FACTORY_INJECT = """
def _f(cfg):
    return build_pipeline(web_search_provider_factory=lambda: build_web_search_provider(cfg))
"""

_SRC_ASSIGN_THEN_USE = """
def _f(cfg):
    provider = build_web_search_provider(cfg)
    return provider.search("x")
"""

_SRC_BARE_CALL = """
def _f(cfg):
    return build_web_search_provider(cfg).search("x")
"""

# 逃逸形态（2026-09-21 R1/I-1 实测抓到的真洞）：provider 是关键字**直值**，
# 但承载它的调用当场被链式执行 ⇒ 造 provider 就是执行路径，旧判据误豁免。
_SRC_KWARG_THEN_CHAINED = """
def _f(cfg):
    return UnifiedSearchService(web_search_provider=build_web_search_provider(cfg)).run("x")
"""

_SRC_KWARG_UNTRACKED_THEN_CHAINED = """
def _f(cfg):
    return SomeOpaqueRunner(web_search_provider=build_web_search_provider(cfg)).go()
"""


def test_provider_injection_is_not_execution_callsite() -> None:
    for src in (_SRC_KWARG_INJECT, _SRC_FACTORY_INJECT):
        direct, _invoker = scan({"x.py": src})
        assert direct["search.web"] == set(), f"注入被误判为执行直呼：{src}"


def test_kwarg_injection_exempts_only_whole_object_handoff() -> None:
    """豁免面收窄自证：`X(provider=build(...))` 交出整枚对象可豁免；
    同一位置**当场链式执行**（`.run()` / `.go()`）就是执行直呼，必须红。"""
    for src in (_SRC_KWARG_THEN_CHAINED, _SRC_KWARG_UNTRACKED_THEN_CHAINED):
        direct, _invoker = scan({"x.py": src})
        assert direct["search.web"] == {"x.py"}, f"链式执行被豁免洞吞掉（分类变豁免面）：{src}"


def test_assign_then_use_still_counts_as_execution() -> None:
    """结构判据的**反例锁**：变量名带 provider 不豁免——用它就是执行路径。"""
    for src in (_SRC_ASSIGN_THEN_USE, _SRC_BARE_CALL):
        direct, _invoker = scan({"x.py": src})
        assert direct["search.web"] == {"x.py"}, f"执行直呼被漏判（分类变豁免洞）：{src}"


def test_real_tree_matches_wave1_ledger() -> None:
    """真树直呼/invoker 两面都必须恰好等于评审过的 ledger——任一侧漂移当场红。

    原判据写死「生产里 invoker 调用点必须为空」，那是 U2 交回时"一点都没通电"的快照。
    Wave 1 首个通电点（root `/bot search`）落地后，改为**登记式**比对：新出现未登记的
    invoker 点照样红（ teeth 保留），已登记的点若消失也红。
    """
    direct, invoker = scan(_load_real_index())
    assert direct == KNOWN_DIRECT_ALLOWLIST, f"直呼面漂移：实得 {direct} ≠ 登记 {KNOWN_DIRECT_ALLOWLIST}"
    actual_invoker = {cap: mods for cap, mods in invoker.items() if mods}
    assert actual_invoker == KNOWN_INVOKER_SITES, (
        f"invoker 调用点漂移：实得 {actual_invoker} ≠ 登记 {KNOWN_INVOKER_SITES}"
    )
    assert check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST) == []


# ---------------------------------------------------------------------------
# ② 注毒自证：每条不变量真的会红（合成树，非真树）
# ---------------------------------------------------------------------------
def _fake_direct(mod: str, symbol: str) -> dict[str, str]:
    body = f"from x import {symbol}\ndef f():\n    return {symbol}(1)\n"
    return {mod: body}


def test_poison_second_direct_callsite_is_red() -> None:
    """注毒：在 allowlist 之外新增一处 build_web_search_provider 直呼点 → 门红。"""
    poison = _fake_direct("domains/food/capabilities/sneaky.py", "build_web_search_provider")
    direct, invoker = scan(poison)
    v = check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST)
    assert any("未登记直呼点" in s and "search.web" in s for s in v), f"注毒未被拦：{v}"


def test_poison_half_migration_is_red() -> None:
    """注毒：同模块既直呼 read_supported_file 又 invoke files.read.* → 半迁移红。"""
    src = (
        "from plugins.bot_unified_runtime.domains.files.sources.file_reader import read_supported_file\n"
        "def f():\n"
        "    read_supported_file('/tmp/a')\n"
        "    default_invoker().invoke(CapabilityRequest(capability_id='files.read.code'))\n"
    )
    direct, invoker = scan({"__init__.py": src})
    v = check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST)
    assert any("半迁移" in s and "files.read" in s for s in v), f"半迁移未被拦：{v}"


def test_poison_second_invoker_site_is_red() -> None:
    """注毒：两个模块各 invoke search.web → 第二调用点红。"""
    src = "def f():\n    default_invoker().invoke(CapabilityRequest(capability_id='search.web'))\n"
    direct, invoker = scan({"m1.py": src, "m2.py": src})
    v = check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST)
    assert any("第二调用点" in s and "search.web" in s for s in v), f"第二 invoker 点未被拦：{v}"


def test_poison_media_second_direct_callsite_defeats_wired_is_red() -> None:
    """注毒（V1 席）：media.anime_ip 已通电，任何模块再直呼 search_saucenao_ex ⇒ 当场红。

    这条锁的是"通电之后有人偷偷走回老路"——它比 未登记直呼点 更狠：
    哪怕那文件本身合法存在，只要该能力已 WIRED，直呼即违规。
    """
    poison = _fake_direct("domains/media/capabilities/sneaky.py", "search_saucenao_ex")
    direct, invoker = scan(poison)
    v = check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST)
    assert any("media.anime_ip" in s and ("已通电却仍直呼" in s or "未登记直呼点" in s) for s in v), (
        f"media 族第二直呼点未被拦：{v}"
    )


def test_poison_media_second_invoker_site_is_red() -> None:
    """注毒（V1 席）：两模块各 invoke media.vision.anime_ip → media 族第二调用点红。"""
    src = (
        "def f():\n    default_invoker().invoke("
        "CapabilityRequest(capability_id='media.vision.anime_ip'))\n"
    )
    direct, invoker = scan({"m1.py": src, "m2.py": src})
    v = check_invariants(direct, invoker, wired=WIRED, allowlist=KNOWN_DIRECT_ALLOWLIST)
    assert any("第二调用点" in s and "media.anime_ip" in s for s in v), f"media 第二 invoker 点未被拦：{v}"


def test_media_family_symbols_are_actually_tracked() -> None:
    """分类面自证：五条 media descriptor 真身都必须在追踪表里，且真身定义文件被豁免。

    漏登记＝该真身的直呼永远不会红（门变哑）。这条锁的是门自己的覆盖面。
    """
    assert {
        "describe_images",
        "search_saucenao_ex",
        "transcribe_audio",
        "build_video_brief",
        "_extract_video_frames",
    } <= set(_TRACKED)
    for symbol, def_file in _DEF_FILES.items():
        if _TRACKED[symbol].startswith("media."):
            assert any(p.startswith("domains/media/") for p in def_file), f"{symbol} 定义文件坐标漂移"
    # 真身内部组合（同 module 内自用）不得被算成直呼点
    _direct, _invoker = scan(
        _fake_direct("domains/media/ingest/vision_describe.py", "_extract_video_frames")
    )
    assert _direct["media.frames"] == set(), "同文件内部组合被误判为第二直呼点"


# ---------------------------------------------------------------------------
# ③ 端到端离线等值：经 invoker 通电 == 直呼真身（逐字段）
# ---------------------------------------------------------------------------
def _file_result(text: str, kind: str) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, title="a.py", text=text, path=Path("/tmp/a.py"), metadata={"format": "text"})


def test_e2e_files_read_code_equals_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.files.sources import file_reader
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    parsed = _file_result("x = 1\n", "code")
    monkeypatch.setattr(file_reader, "read_supported_file", lambda p, *, max_chars=120000: parsed)
    default_invoker()  # 触发 descriptor→_DESCRIPTOR_VIEW 回填
    result = default_invoker().invoke(
        CapabilityRequest(capability_id="files.read.code", payload={"path": "/tmp/a.py"}, principal="u", roles=("user",))
    )
    assert result.status is InvocationStatus.OK
    assert result.via == "file_reader"
    # 与旧直调逐字段等值：invoker 未增删/未伪造真身产出的任何字段
    assert result.data["kind"] == parsed.kind
    assert result.data["title"] == parsed.title
    assert result.data["text"] == parsed.text
    assert result.data["metadata"] == dict(parsed.metadata)


def test_e2e_files_read_denied_for_blocked_role() -> None:
    """接入带来的中央权限门（旧直呼没有）：blocked 角色无条件拒。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    result = default_invoker().invoke(
        CapabilityRequest(capability_id="files.read.code", payload={"path": "/tmp/a.py"}, principal="u", roles=("blocked",))
    )
    assert result.status is InvocationStatus.DENIED


def test_e2e_search_web_equals_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    from plugins.bot_unified_runtime.domains.core.search import web_search
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    class _Hit:
        def __init__(self) -> None:
            self.title = "守岸人设定"
            self.snippet = "泰缇斯第二实例"
            self.url = "https://example.com/a"
            self.source_domain = "example.com"

    class _Provider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def search(self, query: str, *, max_results: int = 8):
            self.calls.append((query, max_results))
            return [_Hit()]

    prov = _Provider()
    monkeypatch.setattr(web_search, "build_web_search_provider", lambda config=None: prov)
    result = default_invoker().invoke(
        CapabilityRequest(
            capability_id="search.web",
            payload={"query": "守岸人", "max_results": 8},
            principal="u",
            roles=("user",),
            context={"config": SimpleNamespace(bot_web_search_enabled=True)},
        )
    )
    assert result.status is InvocationStatus.OK
    assert prov.calls == [("守岸人", 8)]  # 真身被如实调用一次
    raw = prov.search("守岸人", max_results=8)[0]
    assert result.data["hits"] == [
        {"title": raw.title, "snippet": raw.snippet, "url": raw.url, "source_domain": raw.source_domain}
    ]  # 命中逐字段等值，invoker 不伪造/丢弃


def test_unwired_capability_falls_back_to_unavailable() -> None:
    """未注册 handler 的能力 invoke 诚实 UNAVAILABLE（不崩），生产据此回落旧直调。"""
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    result = default_invoker().invoke(
        CapabilityRequest(capability_id="creation.tts.synthesize", payload={"text": "hi"}, principal="u", roles=("user",))
    )
    assert result.status is InvocationStatus.UNAVAILABLE
    # 失败/降级/未接线态不得携带呈现载荷（信封不变量，见 :179）
    assert "presentation_result" not in result.data


def test_shell_wraps_production_handlers() -> None:
    """壳 `_handle_*` 保留：懒 import 指现役真身，implementation_ref 落 descriptor（非新建第二实现）。"""
    src = (_PKG_ROOT / _SHELL_REL).read_text(encoding="utf-8")
    assert "file_reader.read_supported_file" in src
    assert "web_search.build_web_search_provider" in src
    assert "#read_supported_file" in src and "#build_web_search_provider" in src
