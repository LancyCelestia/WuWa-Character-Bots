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
  「descriptor 在册但执行体未注册」→ invoke 诚实 UNAVAILABLE（回落旧直调不崩；2026-09-25
  P4-C2 语音接真后该样本已非生产 cid 实况，机制腿改由真 descriptor 册 + 空 handler 册装配自证）。

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
    # 2026-10-03 S28 补登记（账跟实现新形态，判据零放松）：vision/asr 的**执行体**已迁
    # `*_with_status` 变体（provider.generate 真跑在那边；裸符号退化为文本投影 shim、
    # 内部委托 with_status），chat.py 识图/转写生产点已吃新形（:5727/:5915）⇒ 旧表对
    # 该两执行体结构性失明（S-PROV 同类洞：符号不在表里 ⇒ 两把门都看不见）。裸符号
    # 保留追踪：control_plane / modality_preprocessing 仍经它执行。
    "describe_images_with_status": "media.vision",
    "transcribe_audio_with_status": "media.asr",
    # files 族产物构造真身（2026-09-21 S-PROV 实证：chat.py:2406 生产直呼，
    # 旧追踪表没有这个符号 ⇒ 该旁路两把门都看不见，属门的覆盖面漏登记而非新违规）。
    "build_generated_file": "files.artifact",
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
    "transcribe_audio_with_status": {"domains/media/ingest/transcribe.py"},
    "describe_images_with_status": {"domains/media/ingest/vision_describe.py"},
    "build_video_brief": {"domains/media/ingest/video_understanding.py"},
    "_extract_video_frames": {"domains/media/ingest/vision_describe.py"},
    "build_generated_file": {"domains/files/sources/file_reader.py"},
}
# invoker 调用点归属：capability_id → 能力族（同族多成员按族计，全树每族恰一处）。
_FILES_SEARCH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("files.read", "files.read"),
    ("files.artifact", "files.artifact"),
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


def seam_registered_cids() -> dict[str, set[str]]:
    """命令形/预装配形接缝**声明式通电**的能力 ⇒ {capability_id: 声明所在文件}。

    为什么单独一支（三席独立点名的假账源，S-TTSPIPE/S-OPSOPS/S-PREP）：Wave 4.1 起
    根装配用 `orchestrated_command(capability_id, ...)` 传**变量**，中央内部才
    `invoke(CapabilityRequest(capability_id=<变量>))` ⇒ 只看字面量的 `_invoker_cids`
    对整条命令形通路结构性失明：能力真走了中央，缺口账却恒记 not_wired，
    而把 id 登记进 `WIRED` 又会因"真树找不到 invoke 点"被 INV-WIRED 判红（死结）。
    通电事实的权威答案＝唯一在册表的 route 执行形（`adapter` 属于壳侧 `_KNOWN_ADAPTERS`
    的那些行），其点位就是 `capability_registry.py` 里那一行声明本身。
    用法：缺口账把本函数的结果并进 invoke 命中集，再判 WIRED/NOT_WIRED。

    ⚠ 名字从 `seam_registered_command_cids` 改掉（2026-09-22 prepared 形落地）：认的不再
    只有 `command` 一种形态，留着旧名就是让名字骗人——本波整波在治这个。
    **通电的另一半前提由独立锁负责，不由本函数自证**：①调用方确实把成品交上来；
    ②该能力在 root 的**每一条**分发入口都汇到缝
    （`tests/test_prepared_adapter_canary.py::test_every_resolved_capability_entry_reaches_the_central_seam`）。
    R-PREP C-1 的教训正是本函数当时只证 ①，而 weather/wiki/news/eat/epic 的别名与自然语言
    入口绕过了缝 ⇒ "声明即 WIRED" 是假账。两把锁缺一，本表不得用于降棘轮。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    registry_file = "domains/chat_reply/runtime/capability_registry.py"
    return {
        capability_id: {registry_file}
        for capability_id, adapter in cp._route_execution_adapters().items()
        if adapter in cp._KNOWN_ADAPTERS
    }


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
    # 2026-10-03 S31 跟随账（9469445 有意直读，非旁路）：邮件附件取字
    # mail_ingress_files.py 的 `_read_one` 直呼 `read_supported_file`——该件模块头
    # 自声明「禁第二通路」＝与 QQ 文件段、TG document 段共用 file_reader 同一颗咽喉
    # （降级措辞/解压体检/口令保护/扫描件四族在那里逐字生效，本件不复述文案）；
    # 且消费面是真身原生产物（result.text / file_read_failure_note / labelled_text），
    # 中央壳信封无对位契约 ⇒ 现阶段无等值翻点，登记＝待翻面（同 chat.py 格）。
    "files.read": {
        "__init__.py",
        "control_plane/api/platform.py",
        "domains/transport/mail/mail_ingress_files.py",
    },
    # 2026-09-21 S-PROV 实证补登记（本符号此前**根本不在追踪表里** ⇒ 两把门都看不见这条旁路）：
    # 聊天侧生成文件在 chat.py:2406 直呼 `build_generated_file`；中央 `files.artifact.generate`
    # 有 descriptor+handler 却生产零调用点 ⇒ 登记为待翻面，归 files/Wave4.1 席。
    "files.artifact": {"domains/chat_reply/capabilities/chat.py"},
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
    # 2026-09-25 S220 逐条评审补登记（账跟随真值；AGENTS #50 台账段已归因"该件致本门直呼面漂移"、
    # 当时按纪律不代修，本条是那次归因的跟随补账）：`domains/vision/capabilities/
    # modality_preprocessing.py`（五段"多模态原生矩阵"接货件）的委托 handler 直呼三真身——
    # transcribe_audio(:394)=media.asr、build_video_brief(:438)=media.video_brief、
    # describe_images(:475)=media.vision。**非第二真身**：该文件自声明的 implementation_ref
    # 恰指这些真身（"不指本模块新写的第二实现"，禁平行造轮子裁定的产物）；三枚接货能力
    # 现算**不在** descriptor 册（49 枚之外：creation.audio.transcribe / creation.video.understand /
    # creation.image.upscale 未转录），通电坐标=该文件自声明 WIRING_COORDINATES，注册面归其 owner，
    # 届时直呼应改 invoker ⇒ 与 chat.py/control_plane 两线同格＝待翻面，不是豁免。
    # 2026-10-03 S28 跟随账：chat.py 识图/转写执行面已迁 `*_with_status` 变体（见 _TRACKED 注），
    # **直呼集合不变**——chat.py 仍是这三族的执行直呼点（经新形），登记面零改动，只补符号账。
    "media.vision": {
        "domains/chat_reply/capabilities/chat.py",
        "control_plane/api/platform.py",
        "domains/vision/capabilities/modality_preprocessing.py",
    },
    "media.asr": {
        "domains/chat_reply/capabilities/chat.py",
        "control_plane/api/platform.py",
        "domains/vision/capabilities/modality_preprocessing.py",
    },
    "media.video_brief": {
        "domains/chat_reply/capabilities/chat.py",
        "domains/vision/capabilities/modality_preprocessing.py",
    },
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


def test_central_permission_gate_is_hierarchical_not_flat() -> None:
    """中央权限门必须是**层级最低门槛**——平坦求交会把管理员挡在自己的能力门外。

    2026-09-21 实锤的 Critical：旧判据 `set(held) & set(required)` 下
    `required_roles=("user",)` 对 admin/super_admin/trusted 一律 DENIED，
    而本仓角色模型是叠加式（超管叠 admin）。本锁双向钉死，任何回退即红。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import roles_satisfy

    # 高档位满足低门槛（旧判据在这三发上是 DENIED＝杀伤力所在）。
    assert roles_satisfy(("admin",), ("user",))
    assert roles_satisfy(("super_admin", "admin"), ("user",))
    assert roles_satisfy(("trusted",), ("user",))
    assert roles_satisfy(("admin",), ("trusted",))
    # 低档位不得越过高门槛。
    assert not roles_satisfy(("user",), ("admin",))
    assert not roles_satisfy(("trusted", "user"), ("super_admin",))
    # blocked / 未知角色：由 invoker 无条件拒（见上一条用例），谓词本身只管定秩。
    assert not roles_satisfy(("godmode",), ("user",))
    assert not roles_satisfy((), ("user",))
    assert not roles_satisfy(("admin",), ())

    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityRequest,
        InvocationStatus,
        default_invoker,
    )

    mixed = default_invoker().invoke(
        CapabilityRequest(
            capability_id="files.read.code",
            payload={"path": "/tmp/a.py"},
            principal="u",
            roles=("blocked", "admin"),
        )
    )
    assert mixed.status is InvocationStatus.DENIED


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
    """「descriptor 在册、执行体未注册」的能力 invoke 诚实 UNAVAILABLE（不崩），生产据此回落旧直调。

    2026-09-25 S220 真值跟随：原版直接拿 `creation.tts.synthesize` 当"未注册 handler"样本，
    该前提已被本波 P4-C2「语音接真」作废（执行体注册在 `capability_protocols.py:2716`，接真后
    总开关关闭态回诚实 NOT_CONFIGURED——那面行为由 `tests/test_tts_creation_gate_reality.py`
    执法，本例不重复断言、也不据它改期望值）。现算 descriptor 与 handler 两册 49/49 等值，
    生产已无"在册却缺执行体"的 cid 可当样本 ⇒ 本例改用**真 descriptor 册 + 空 handler 册**
    装配一台 invoker，直接钉住机制那条腿（缺执行体分支见 `capability_protocols.py:745-752`；
    对照：descriptor 都不在册的 id 走 FAILED「未登记能力」，两分支各归各，不得混同）。
    """
    from plugins.bot_unified_runtime.runtime.capability_protocols import (
        CapabilityInvoker,
        CapabilityRequest,
        HandlerRegistry,
        InvocationStatus,
        default_invoker,
    )

    unwired = CapabilityInvoker(
        registry=default_invoker().registry, handlers=HandlerRegistry()
    )
    result = unwired.invoke(
        CapabilityRequest(capability_id="creation.tts.synthesize", payload={"text": "hi"}, principal="u", roles=("user",))
    )
    assert result.status is InvocationStatus.UNAVAILABLE
    # 失败/降级/未接线态不得携带呈现载荷（信封不变量，见 :179）
    assert "presentation_result" not in result.data


def test_wave41_seam_routes_command_facet_through_central_gate() -> None:
    """Wave 4.1 主缝的活性判据：command 形能力经根缝时，**中央权限门真的在执法**。

    三条一起才叫证据：①在册 id 的正常主体 ⇒ 呈现契约与直呼真身逐字段等值；
    ②blocked 主体 ⇒ 旧直呼会照跑，缝必须给出温和短句且把终态写进 audit_tags；
    ③未在册 id ⇒ 必须原样走旧路（不得被缝吞掉）。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    def _msg() -> SimpleNamespace:
        return SimpleNamespace(request_id="req-seam", text="说一句", session_key="group_1_2", sender_id="9")

    seen: list[object] = []

    def _legacy_capability(message: object, decision: object) -> object:
        seen.append((message, decision))
        return _present_result(message)

    cfg = SimpleNamespace(bot_tts_enabled=False)
    step = cp.orchestrated_command("bot.tts", _legacy_capability, cfg)
    ok = step(_msg(), SimpleNamespace(actor_roles=("user",)))
    assert ok.audit_tags == ["tts", "legacy"], ok.audit_tags
    assert ok.body == "旧直呼产物", "在册 id 未原样复用调用方已装配执行体"
    assert len(seen) == 1 and seen[0][1].actor_roles == ("user",)

    blocked = step(_msg(), SimpleNamespace(actor_roles=("blocked",)))
    assert "orchestration:denied" in blocked.audit_tags, blocked.audit_tags
    assert blocked.body.strip() and "bot.tts" == blocked.capability_id

    fallback = cp.orchestrated_command("bot.never_registered", _legacy_capability, cfg)
    returned = fallback(_msg(), SimpleNamespace(actor_roles=("user",)))
    assert len(seen) == 2 and returned is not None, "未在册 id 必须原样走旧路（缝不得吞回复）"
    assert blocked.body != returned.body, "被拒态不得伪装成执行体产物"


def test_wave41_seam_returns_crash_to_layer1_error_card() -> None:
    """S-ROWS X-8 根修锁：能力真崩了，缝必须把**原始异常**交回层 1（错误卡路）。

    接入中央 invoker 后，"崩了" 被吞成 FAILED 终态 → 层 1 只见温和短句 →
    `RuntimePipeline._internal_error`→诊断卡旁路结构性失效。这条锁钉死：
    ①崩＝同一次调用抛回同一异常对象（栈帧不丢）；②被拒/超限≠崩，仍走温和短句。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    boom = RuntimeError("能力内部炸了")

    def _crashing(message: object, decision: object) -> object:
        raise boom

    step = cp.orchestrated_command("bot.tts", _crashing, SimpleNamespace())
    with pytest.raises(RuntimeError) as caught:
        step(_seam_msg(), SimpleNamespace(actor_roles=("user",)))
    assert caught.value is boom, "交回层 1 的必须是原始异常对象（错误卡要原栈帧）"


def test_wave41_seam_denial_does_not_raise() -> None:
    """对照锁（防把"一律抛"当成修复）：中央拒判不是崩溃，必须出短句、不抛。"""
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    def _fine(message: object, decision: object) -> object:
        return _present_result(message)

    step = cp.orchestrated_command("bot.tts", _fine, SimpleNamespace())
    denied = step(_seam_msg(), SimpleNamespace(actor_roles=("blocked",)))
    assert "orchestration:denied" in denied.audit_tags, denied.audit_tags


def _seam_msg() -> SimpleNamespace:
    return SimpleNamespace(
        request_id="req-seam-2", text="说一句", session_key="group_1_2", sender_id="9"
    )


def test_central_gate_admits_system_principal_without_roles() -> None:
    """D-4 锁：空 roles＝系统/内部主体，不受人门约束（真人恒含 user）。

    定时任务与 decision=None 的调用方拿不到角色；若按"人门"判，中央一接就把
    campus/订阅/摘要/日常助理这类**无人类主体**的链路全量 DENIED（S-ROWS probe3 实跑）。
    豁免只做在 invoker 门上：`roles_satisfy` 谓词本体仍对空 held 判不满足，
    因为 `/bot why`（diagnostics.py）裸用该谓词，改谓词会把"过拒"翻成"过放"。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    assert not cp.roles_satisfy((), ("user",)), "谓词本体被放宽＝I-1 反向咬合"
    invoker = cp.default_invoker()
    descriptor = invoker.registry.get("bot.routes") or invoker.registry.get("bot.tts")
    assert descriptor is not None, "取不到在册描述符＝本锁前提失效"
    result = invoker.invoke(
        cp.CapabilityRequest(
            capability_id=descriptor.capability_id,
            payload={"message": _seam_msg()},
            principal="system:job",
            roles=(),
            context={"config": SimpleNamespace()},
        )
    )
    assert result.status is not cp.InvocationStatus.DENIED, result.detail


def _present_result(message: object) -> object:
    from plugins.bot_unified_runtime.domains.core.contracts.runtime import (
        CapabilityResult,
    )

    return CapabilityResult(
        request_id=getattr(message, "request_id", ""),
        capability_id="bot.tts",
        kind="text",
        body="旧直呼产物",
        audit_tags=["tts", "legacy"],
    )


def test_wave41_seam_lock_is_not_toothless(monkeypatch: pytest.MonkeyPatch) -> None:
    """注毒：把 command 视图掏空 ⇒ 缝会退回旧路，活性锁①必须红（证明这把锁真在测缝）。"""
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    monkeypatch.setattr(cp, "_route_execution_adapters", dict)
    seen: list[object] = []

    def _legacy(message: object, decision: object) -> object:
        seen.append(message)
        return _present_result(message)

    step = cp.orchestrated_command("bot.tts", _legacy, SimpleNamespace(bot_tts_enabled=False))
    out = step(SimpleNamespace(request_id="r", text="x", session_key="s", sender_id="9"), SimpleNamespace(actor_roles=("user",)))
    assert seen and out.audit_tags == ["tts", "legacy"], "毒注下去却仍走中央 ⇒ 本锁是假牙"


def _central_sink_facts(source: str) -> tuple[int, int, bool]:
    """(注册点处数, 其中写 AuditRecord(stage="capability_invoke") 的处数, sink 是否 fail-open)。"""
    tree = ast.parse(source)
    registrations = 0
    audited = 0
    guarded = False
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "attach_default_audit_sink"
            and node.args
        ):
            continue
        registrations += 1
        callback = node.args[0]
        if not isinstance(callback, ast.Name):
            continue
        target = next(
            (
                item
                for item in ast.walk(tree)
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == callback.id
            ),
            None,
        )
        if target is None:
            continue
        guarded = any(isinstance(item, ast.Try) for item in ast.walk(target))
        for inner in ast.walk(target):
            if not (
                isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "AuditRecord"
            ):
                continue
            stages = {
                keyword.value.value
                for keyword in inner.keywords
                if keyword.arg == "stage" and isinstance(keyword.value, ast.Constant)
            }
            audited += int(stages == {"capability_invoke"})
    return registrations, audited, guarded


def test_production_registers_the_central_audit_sink_exactly_once() -> None:
    """D-d 闭合锁（S-TTSPIPE 实测根修）：中央执行终态在生产必须真的落到审计库。

    invoker 每次终态都 emit，但注册表全树零注册 ⇒ "走中央"在运维面等于没走。
    根装配必须**恰一处**经壳侧唯一口子注册 sink，且该 sink 写
    `AuditRecord(stage="capability_invoke")`、并 fail-open（审计坏不得拖垮执行）。
    """
    facts = _central_sink_facts((_PKG_ROOT / "__init__.py").read_text(encoding="utf-8"))
    assert facts == (1, 1, True), f"中央审计 sink 登记面异常：{facts}"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def _sink(record): pass\n", (0, 0, False)),
        (
            (
                "def _a(record): AuditRecord(stage='other')\n"
                "attach_default_audit_sink(_a)\n"
            ),
            (1, 0, False),
        ),
        (
            (
                "def _a(record):\n"
                "    try:\n"
                "        AuditRecord(stage='capability_invoke')\n"
                "    except Exception:\n"
                "        pass\n"
                "attach_default_audit_sink(_a)\n"
            ),
            (1, 1, True),
        ),
    ],
)
def test_central_sink_lock_has_teeth(source: str, expected: tuple[int, int, bool]) -> None:
    """判据自证：没注册/注册了但不写审计/写对且 fail-open，三种世界要分得开。"""
    assert _central_sink_facts(source) == expected


def _exec_root_function(name: str, namespace: dict[str, object]) -> object:
    """从根 `__init__.py` 里抠出**单个函数节点**（含装配闭包内的嵌套 def）单独执行。

    根装配函数没法整体跑（要 NoneBot 运行时），沿用本仓 `test_v21_s0_root_collect.py`
    的受控命名空间口径：函数体引用的名字必须在 ns 里显式给全，缺一个就 NameError——
    这正是"活性"的来源（结构锁只能证明写了，证不了会跑）。
    """
    source = (_PKG_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )
    assert target is not None, f"根装配里找不到 {name}（被改名/挪走＝本锁失效）"
    module = ast.Module(body=[target], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(_PKG_ROOT / "__init__.py"), "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_production_audit_sink_really_writes_and_fails_open() -> None:
    """活性锁：根注册的中央审计 sink 必须真把执行终态写进审计库，且写坏不影响执行。

    只有结构锁（"注册点恰一处、函数里出现 AuditRecord(stage=...)"）是不够的——
    闭包引用取不到、severity 映射写反、异常没兜住，都得靠真跑一次才发现。
    """
    import logging
    from dataclasses import dataclass, field
    from datetime import datetime, timezone

    from plugins.bot_unified_runtime.contracts import AuditRecord, RiskLevel
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    @dataclass
    class _Recorder:
        records: list[AuditRecord] = field(default_factory=list)

        def append(self, record: AuditRecord) -> None:
            self.records.append(record)

    sink_logger = _Recorder()
    namespace: dict[str, object] = {
        "AuditRecord": AuditRecord,
        "RiskLevel": RiskLevel,
        "logging": logging,
        "audit_logger": sink_logger,
        "__name__": "plugins.bot_unified_runtime",
    }
    sink = _exec_root_function("_record_capability_audit", namespace)
    assert callable(sink)

    now = datetime.now(timezone.utc)
    sink(
        cp.CapabilityAuditRecord(
            at_utc=now,
            capability_id="bot.tts",
            principal="3865067623",
            status=cp.InvocationStatus.OK,
            via="caller_capability",
            elapsed_ms=12,
            detail="",
            request_id="req-1",
            session_key="group_1_2",
        )
    )
    sink(
        cp.CapabilityAuditRecord(
            at_utc=now,
            capability_id="bot.tts",
            principal="3865067623",
            status=cp.InvocationStatus.DENIED,
            via="invoker",
            elapsed_ms=0,
            detail="需要 admin 及以上角色",
            request_id="req-2",
            session_key="private:9",
        )
    )

    first, second = sink_logger.records
    assert first.stage == "capability_invoke" and second.stage == "capability_invoke"
    assert (first.event, second.event) == ("invoke_ok", "invoke_denied")
    # 关联键必须真的落到审计记录上（否则"可观测"只是口号）
    assert (first.request_id, first.session_id) == ("req-1", "group_1_2")
    assert (second.request_id, second.session_id) == ("req-2", "private:9")
    # 成功=LOW、非成功=MEDIUM；反向＝把运维噪音和正常流量分不开
    assert first.severity is RiskLevel.LOW and second.severity is RiskLevel.MEDIUM
    assert "admin" in second.private_debug, second.private_debug

    class _Broken:
        def append(self, record: AuditRecord) -> None:
            raise RuntimeError("审计库坏了")

    namespace["audit_logger"] = _Broken()
    broken_sink = _exec_root_function("_record_capability_audit", namespace)
    broken_sink(  # 不得抛：审计失败绝不能拖垮能力执行
        cp.CapabilityAuditRecord(
            at_utc=now,
            capability_id="bot.tts",
            principal="p",
            status=cp.InvocationStatus.OK,
            via="v",
            elapsed_ms=1,
            detail="",
        )
    )


def test_shell_wraps_production_handlers() -> None:
    """壳 `_handle_*` 保留：懒 import 指现役真身，implementation_ref 落 descriptor（非新建第二实现）。"""
    src = (_PKG_ROOT / _SHELL_REL).read_text(encoding="utf-8")
    assert "file_reader.read_supported_file" in src
    assert "web_search.build_web_search_provider" in src
    assert "#read_supported_file" in src and "#build_web_search_provider" in src


# ------------------------------------------------- I-1/M-1：审计身份与注册表幂等（R-CENTRAL）
class _Presented:
    """最小"呈现契约"替身：壳侧只要求它可 `model_dump()`。"""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def model_dump(self) -> dict[str, str]:
        return {"tag": self.tag}


def _command_request(capability: object) -> object:
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    return cp.CapabilityRequest(
        capability_id="bot.seam.identity",
        principal="3865067623",
        roles=("user",),
        payload={"message": _seam_msg()},
        context={"capability": capability, "decision": SimpleNamespace(), "config": SimpleNamespace()},
    )


def test_command_handler_records_which_callable_actually_ran() -> None:
    """I-1：`via` 必须能区分**跑的是哪一段代码**，而不只是"走了调用方那条路"。

    缝与 handler 都优先用调用方交来的成品（保留装配期注入），`implementation_ref` 只作
    provenance ⇒ 若审计只写 `caller_capability` 五个字，"在册说 A、实跑 B"事后无从判定，
    中央调度层的可观测性就只剩"经过了一道门"。

    ⚠ 本用例一度写成"两个同一工厂造出的闭包要给出不同 via"，那是**要求错的东西**：
    `__qualname__` 记的是代码路径，同厂两实例本来就是同一段码，分不出也不该分
    （拿 `id()` 去分只会造出跨重启无意义的噪音）。生产上真正要分开的是"哪个装配现场
    造的哪个 handler"，那是不同的 def、不同的 qualname。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    def _weather_flavoured(message: object, decision: object) -> object:
        return _Presented("weather")

    def _tts_flavoured(message: object, decision: object) -> object:
        return _Presented("tts")

    handler = cp._make_command_handler("plugins/bot_unified_runtime/x.py#builder")
    first = handler(_command_request(_weather_flavoured))
    second = handler(_command_request(_tts_flavoured))

    assert first.status is cp.InvocationStatus.OK and second.status is cp.InvocationStatus.OK
    assert first.via.startswith("caller_capability:") and second.via.startswith(
        "caller_capability:"
    )
    assert first.via != second.via, (
        f"两次调用跑的是不同代码路径，审计却分不开：{first.via} / {second.via}"
    )
    assert "_weather_flavoured" in first.via and "_tts_flavoured" in second.via, (
        f"via 没带可定位的限定名：{first.via} / {second.via}"
    )
    assert __name__ in first.via, f"via 没带模块名，跨包重名时无从定位：{first.via}"


def test_audit_hook_registry_is_idempotent_by_identity() -> None:
    """M-1：同一钩子重复注册不得让一次终态落多行审计。

    根装配块被重放（测试期受控 exec、二次装配）时若审计翻倍，"每次调用恰一行"这条
    现役判据（`test_production_audit_sink_really_writes_and_fails_open`）就被污染，
    用量统计也会虚高。不同函数对象仍须各自收到。
    """
    from datetime import datetime, timezone

    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    registry = cp.AuditHookRegistry()
    seen: list[str] = []
    def _hook(record: object) -> None:
        seen.append("x")

    registry.register(_hook)
    registry.register(_hook)
    registry.register(_hook)
    registry.emit(
        cp.CapabilityAuditRecord(
            at_utc=datetime.now(timezone.utc),
            capability_id="bot.seam.identity",
            principal="u",
            status=cp.InvocationStatus.OK,
            via="test",
            elapsed_ms=1,
            detail="",
        )
    )
    assert seen == ["x"], f"重复注册把一次终态放大成 {len(seen)} 行审计"

    other_seen: list[str] = []
    registry.register(lambda record: other_seen.append("y"))
    registry.emit(
        cp.CapabilityAuditRecord(
            at_utc=datetime.now(timezone.utc),
            capability_id="bot.seam.identity",
            principal="u",
            status=cp.InvocationStatus.OK,
            via="test",
            elapsed_ms=1,
            detail="",
        )
    )
    assert seen == ["x", "x"] and other_seen == ["y"], "幂等判定误伤了不同的钩子"


# ------------------------- I-2：空角色=系统主体 这条豁免的作用域锁（R-CENTRAL）
def _probe_invoker() -> object:
    """一枚**私有** invoker：豁免探针要注册描述符，绝不能用 default_invoker()。

    往单例里塞探针会污染别的门——本波已实跑踩过一次（某测试注册 `media.test.limited`
    导致 `registry_ids == orchestration_ids | route_execution_ids` 由 23 变 24 假红）。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    return cp.CapabilityInvoker(
        registry=cp.CapabilityRegistry(),
        handlers=cp.HandlerRegistry(),
    )


def _probe_descriptor(roles: tuple[str, ...]) -> object:
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    return cp.CapabilityDescriptor(
        capability_id="roles.probe.exempt",
        family=cp.CapabilityFamily.SEARCH,
        title="角色豁免探针",
        input_protocol="probe.v1 Probe{}",
        output_protocol="probe.v1 ProbeResult{}",
        required_roles=roles,
        implementation_ref=(
            "plugins/bot_unified_runtime/runtime/capability_protocols.py#_make_command_handler"
        ),
    )


def test_system_principal_exemption_is_locked_to_empty_roles_only() -> None:
    """钉死"空角色 ⇒ 系统主体"豁免的**唯一触发条件**，并如实登记它的杀伤半径。

    为什么本波不直接改严（记录优先于假装修好）：豁免是给主动投递族用的——它们没有
    会话主体、`roles` 天然为空；会话侧走 `orchestrated_command` 时角色来自
    `decision.actor_roles`。把"报了主体却没角色"当场拒掉确实更安全，但根缝里 principal
    缺省会写成 `"anonymous"`，而"某些适配器是否真会不带 `sender_id`"离线不可证——
    拿不可证的判断改线上准入，换来的可能是一条吞掉真实消息的红。
    ⇒ 本用例只做三件事：①证明豁免**只由 roles 空触发**（与 principal 无关，冒充不了）；
    ②证明报了角色就必须按角色执法（blocked 冒充 admin 当场拒、且 handler 一次没跑）；
    ③证明**所有在册路由能力**的角色下限都在 user 及以上 ⇒ 真人永远走不到空角色分支。
    残留风险已进 `PENDING-RULINGS-20260922.md` 第 12 项，由她裁定要不要收紧。
    """
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    invoker = _probe_invoker()
    executed: list[str] = []

    def _handler(request: cp.CapabilityRequest) -> cp.InvocationResult:
        executed.append(request.capability_id)
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            via="test",
            attempts=1,
        )

    invoker.registry.register(_probe_descriptor(("admin",)))  # 下限刻意高于真人
    invoker.handlers.register("roles.probe.exempt", _handler)

    def _request(roles: tuple[str, ...], principal: str) -> cp.CapabilityRequest:
        return cp.CapabilityRequest(
            capability_id="roles.probe.exempt",
            payload={},
            principal=principal,
            roles=roles,
        )

    # ① 空角色 ⇒ 系统主体，越过 admin 下限；报不报主体都一样（豁免只看 roles）。
    # 注：`principal` 在契约层就 min_length=1 ⇒ "空主体"这种请求根本构造不出来，
    # 所以冒充系统桶的唯一入口只剩"roles 交空"，本锁锁的正是这一条。
    assert invoker.invoke(_request((), "system")).status is cp.InvocationStatus.OK
    assert invoker.invoke(_request((), "3865067623")).status is cp.InvocationStatus.OK
    assert len(executed) == 2

    # ② 只要报了角色就按角色执法：blocked 想借"主体"翻身 ⇒ 拒，且一次都不执行。
    denied = invoker.invoke(_request(("blocked",), "3865067623"))
    assert denied.status is cp.InvocationStatus.DENIED, denied
    assert len(executed) == 2, "被拒却仍执行＝权限门是装饰"

    # ③ 在册路由能力角色下限都在 user 及以上（读 default_invoker，不往它里面写）。
    central = cp.default_invoker()
    for cid in cp._route_execution_adapters():
        registered = central.registry.get(cid)
        assert registered is not None, f"{cid} 在册却没有描述符"
        assert registered.required_roles, f"{cid} 角色下限为空＝任何主体都过"
        assert "user" in registered.required_roles, (
            f"{cid} 角色下限 {registered.required_roles} 不含 user＝真人桶与系统桶混用"
        )


def test_system_principal_exemption_lock_has_teeth() -> None:
    """注毒：若角色门其实不执法（恒放行），上面那条锁的第②段就是空转——本例证明它会红。"""
    from plugins.bot_unified_runtime.runtime import capability_protocols as cp

    def _handler(request: cp.CapabilityRequest) -> cp.InvocationResult:
        return cp.InvocationResult(
            capability_id=request.capability_id,
            status=cp.InvocationStatus.OK,
            via="test",
            attempts=1,
        )

    strict = _probe_invoker()
    strict.registry.register(_probe_descriptor(("admin",)))
    strict.handlers.register("roles.probe.exempt", _handler)
    assert (
        strict.invoke(
            cp.CapabilityRequest(
                capability_id="roles.probe.exempt", payload={}, principal="u", roles=("user",)
            )
        ).status
        is cp.InvocationStatus.DENIED
    ), "admin 下限挡不住 user ⇒ 角色门恒放行，上一条锁的第②段就是空转"
