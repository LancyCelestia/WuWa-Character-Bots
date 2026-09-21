"""G-4 统一性机器门 · 第一道：TTS 合成出站必经中央管线入口（Wave G · T77）。

病根（plan-G-contract.md §G-4）：「中央统一有一部分是假的」——没有机器门时，
旁支直连（自己拼引擎请求体、绕开装配点直接 POST、不体检就落盘、绕开缓存身份、
绕开打码+内容门取文、从别处 import 私有管线件拼第二条出站路）不会被任何东西
拦住，中央契约层（docs/design/tts-contract-layer.md §4 管线十阶段）就退化成
「恰好只有一条路时才成立」的君子协定。

本门把「出站必经中央」写成 AST 静态断言，主对象 = **登记在册的全部语音产出出站
路径**（FIX8 2026-09-21 扩面：此前只读 tts.py 一个文件，G-3 落地的第二出站路
``domains/media/voice_enricher.py``——:175 直连 ``synthesize``、:200 构造
``update={"audio": …}``——一条不变量都不在射程内）。检测器接受任意源码串，故可对
注入的坏样本自证杀伤力：

  A1 请求体唯一装配点：``_request_tts`` 内 httpx ``.post(json=…)`` 的请求体必须
     来自 ``_build_request_payload(...)``（直接调用或绑定其返回值的变量）；且
     全模块 ``.post(`` 只允许出现在 ``_request_tts`` 体内（第二 HTTP 路径即红）。
  A2 体检闸绑死落盘/缓存：``write_bytes`` / ``_store_cache`` 调用只允许出现在
     synthesize 内，且同函数内 ``_inspect_wav_bytes`` 调用在先——「不可播字节
     绝不落盘、绝不入缓存」从注释变成机器断言。
  A3 取文口先行：``synthesize`` 的每个调用方函数必须先调 ``resolve_speech_text``
     （打码→清洗→词典→内容门的唯一取文口），行序在前——文字面被拦的语音
     不可能从旁路溜出去（M-02/M-03 语义的结构锁）。
  A4 audio 出站构造绑定 synthesize：模块内任何 ``audio=`` 出站构造（kwarg 直挂
     或 ``update={"audio": …}`` 形态）所在函数必须先调用过 synthesize——
     「音频来路不明」即红。
  A5 私有面不外借：plugins/** 其他模块禁止以静态 import、属性访问或字符串
     形态引用私有管线件（_request_tts/_build_request_payload/_inspect_wav_bytes/
     _cache_identity/_cache_key/_store_cache/_lookup_cache）。

负样本自检（plan-G §G-4 原文「负样本必须真能抓：只加正例的门等于没加」）：
每条规则配「注入坏样本 → 门变红」用例；另配一份忠实迷你管线正例对照，
防检测器过度开火（永远红的门同样等于没加）。FIX8 追加**逐在册路径**的变异自检：
以真身 ``voice_enricher.py`` 源码为底本做单点文本变异（不碰生产文件），
证明 A1-A4 对第二出站路真的承重，而不是「恰好也绿」。

射程穷举锁（``test_gate1_scan_set_is_exhaustive_over_plugins_tree``）：在册集合不是手抄
清单——每次运行都用本门自己的检测器重扫 ``plugins/**``，凡出现新的 ``synthesize(``
调用点或新的 audio 出站构造点而未登记/未豁免，门直接红（治「加了第三条路没人知道」）。

边界与已知残留（诚实登记）：capabilities/tts.py 兼容垫片（PEP 562 透传）按
v21r2 契约原样保留，其运行时 getattr 透传面不在本门静态射程内；根 __init__.py
的 hook 装配双态互斥归 G-3/T73 门（tests/test_voice_hook_assembly.py）；
点歌/链接解析/出站 sender 三处 ``audio=`` 构造的是**源媒体**而非合成产物，
按 ``_NON_TTS_AUDIO_CONSTRUCTION_SITES`` 显式豁免（豁免=登记理由，不是静默放过）；
A5 私有面清单只钉 7 枚管线件，``voice_enricher`` 依 G-3 设计复用的
``_build_params``/``_resolve_preset``/``_output_dir``/``_failure_issue`` 等**不在**该清单内
（规格 §4.2 明文允许「只消费其模块级构件」），扩钉这些名字会让门对现存生产码红，
故登记为残留不修、交裁决。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins" / "bot_unified_runtime"
_TTS_SOURCE = _PLUGIN_ROOT / "domains" / "media" / "capabilities" / "tts.py"
# FIX8 扩面：G-3 配音 hook 是**第二条**语音产出出站路（synthesize 直连 +
# update={"audio": …} 构造），旧版门只读 tts.py，对它一条不变量都不承重。
_VOICE_ENRICHER_SOURCE = _PLUGIN_ROOT / "domains" / "media" / "voice_enricher.py"

# 在册语音产出出站路径全集（A1-A4 逐文件生效；新增路必须在这里登记，
# 否则 test_gate1_scan_set_is_exhaustive_over_plugins_tree 直接红）。
_VOICE_OUTBOUND_SOURCES: tuple[Path, ...] = (_TTS_SOURCE, _VOICE_ENRICHER_SOURCE)

# 非合成音频构造面豁免表：posix 相对路径（相对 _PLUGIN_ROOT）→ 豁免理由。
# 判据=该 audio 的来路是**上游源媒体/出站转换**，不是 TTS 合成产物，
# 因此 A3（取文口先行）/A4（audio 绑定 synthesize）对其无意义；豁免是
# **显式登记**（含理由），出现新构造点而未进本表 ⇒ 门红，不许静默放过。
_NON_TTS_AUDIO_CONSTRUCTION_SITES: dict[str, str] = {
    "domains/link_parse/capabilities/content_parser.py": (
        "链接解析产物：audio 段来自平台侧已有音轨（点歌/视频音轨），非合成"
    ),
    "domains/music/capabilities/music.py": (
        "点歌能力：audio 段=供应商返回的音频文件资产，非合成"
    ),
    "domains/transport/sender/nonebot.py": (
        "出站 sender：把 CapabilityResult.audio 转成 OneBot 段的传输层构造，"
        "产物身份由上游中央管线决定，本层不得再合成"
    ),
}

# 私有管线件（下划线族）：只许在 tts.py 模块内出现，出借即旁支。
_PRIVATE_PIPELINE_NAMES: frozenset[str] = frozenset(
    {
        "_request_tts",
        "_build_request_payload",
        "_inspect_wav_bytes",
        "_cache_identity",
        "_cache_key",
        "_store_cache",
        "_lookup_cache",
    }
)

# 白名单：引擎 HTTP 请求 / 音频落盘 / 缓存写入 只许发生的函数。
_HTTP_POST_ALLOWLIST: frozenset[str] = frozenset({"_request_tts"})
_DISK_WRITE_ALLOWLIST: frozenset[str] = frozenset({"synthesize"})
_CACHE_STORE_ALLOWLIST: frozenset[str] = frozenset({"synthesize"})


# ==================== 检测器基座（对任意源码可复用，负样本靠它注入） ====================


@dataclass(frozen=True)
class _Site:
    """模块内一个关注点：最内层 enclosing 函数名 + 行号 + 形态。"""

    func_name: str
    lineno: int
    callee: str = ""  # call 形态：被调名末段（client.post → post）
    label: str = ""  # audio 关键字形态：audio= / update={'audio': …}


def _parse(source: str) -> ast.Module:
    return ast.parse(source)


def _callee_name(call: ast.Call) -> str:
    """被调名末段：Name 直呼或 Attribute 链末段（client.post → post）。"""
    func: ast.expr = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _module_sites(tree: ast.Module) -> list[_Site]:
    """单趟扫描：按最内层函数归属全部函数调用与 audio= 出站构造点。"""
    sites: list[_Site] = []
    stack: list[str] = ["<module>"]

    class _Visitor(ast.NodeVisitor):
        def _enter_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter_fn(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter_fn(node)

        def visit_Call(self, node: ast.Call) -> None:
            sites.append(
                _Site(
                    func_name=stack[-1],
                    lineno=node.lineno,
                    callee=_callee_name(node),
                )
            )
            for kw in node.keywords:
                if kw.arg == "audio":
                    sites.append(
                        _Site(
                            func_name=stack[-1],
                            lineno=kw.value.lineno,
                            label="audio=",
                        )
                    )
                elif (
                    kw.arg == "update"
                    and isinstance(kw.value, ast.Dict)
                    and any(
                        isinstance(k, ast.Constant) and k.value == "audio"
                        for k in kw.value.keys
                    )
                ):
                    sites.append(
                        _Site(
                            func_name=stack[-1],
                            lineno=kw.value.lineno,
                            label="update={'audio': …}",
                        )
                    )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return sites


def _names_assigned_from(tree: ast.Module, callee: str) -> dict[str, set[str]]:
    """按 enclosing 函数归集 ``x = callee(...)`` 的目标变量名。"""
    assigned: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if _callee_name(node.value) != callee:
            continue
        owner = _innermost_func_for_lineno(tree, node.lineno)
        for target in node.targets:
            if isinstance(target, ast.Name):
                assigned.setdefault(owner, set()).add(target.id)
    return assigned


def _innermost_func_for_lineno(tree: ast.Module, lineno: int) -> str:
    """包含给定行的最内层函数名；模块级返回 <module>。"""
    best_name = "<module>"
    best_start = -1

    class _Visitor(ast.NodeVisitor):
        def _enter_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            nonlocal best_name, best_start
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            if node.lineno <= lineno <= end and node.lineno > best_start:
                best_start = node.lineno
                best_name = node.name
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter_fn(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter_fn(node)

    _Visitor().visit(tree)
    return best_name


def _scan_tts_source(source: str) -> list[str]:
    """门主体：对 tts.py 形态源码跑 A1-A4，返回人话违规清单（空=过门）。"""
    tree = _parse(source)
    sites = _module_sites(tree)
    problems: list[str] = []

    # ---- A1 请求体唯一装配点 ----
    post_sites = [s for s in sites if s.callee == "post"]
    builder_assigned = _names_assigned_from(tree, "_build_request_payload")
    for site in post_sites:
        if site.func_name not in _HTTP_POST_ALLOWLIST:
            problems.append(
                f"A1：函数 {site.func_name} 行 {site.lineno} 出现 .post( HTTP 调用"
                f"（白名单={sorted(_HTTP_POST_ALLOWLIST)}）——引擎请求只许"
                " _request_tts 一处，此为第二请求路径"
            )
    request_posts = [
        s for s in post_sites if s.func_name == "_request_tts"
    ]
    request_builder_calls = [
        s
        for s in sites
        if s.func_name == "_request_tts" and s.callee == "_build_request_payload"
    ]
    for site in request_posts:
        if not request_builder_calls:
            problems.append(
                f"A1：_request_tts 行 {site.lineno} 的 .post( 之前没有"
                " _build_request_payload 调用——请求体装配点被绕开"
            )
            continue
        json_value: ast.expr | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.lineno == site.lineno:
                json_value = _keyword_value(node, "json")
                break
        if json_value is None:
            problems.append(
                f"A1：_request_tts 行 {site.lineno} 的 .post( 未带 json= 请求体"
            )
        elif isinstance(json_value, ast.Call):
            if _callee_name(json_value) != "_build_request_payload":
                problems.append(
                    f"A1：行 {site.lineno} 请求体来自 {_callee_name(json_value)}(…)"
                    " 而非 _build_request_payload"
                )
        elif isinstance(json_value, ast.Name):
            bound = builder_assigned.get("_request_tts", set())
            if json_value.id not in bound:
                problems.append(
                    f"A1：行 {site.lineno} 请求体变量 {json_value.id} 并非由 "
                    "_build_request_payload 赋值——旁支直拼"
                )
        else:
            problems.append(
                f"A1：行 {site.lineno} 请求体是内联字面量/表达式——"
                "未经 _build_request_payload 装配"
            )

    # ---- A2 体检闸绑死落盘/缓存写 ----
    for site in sites:
        if site.callee == "write_bytes" and site.func_name not in _DISK_WRITE_ALLOWLIST:
            problems.append(
                f"A2：函数 {site.func_name} 行 {site.lineno} 调用 write_bytes( "
                f"（白名单={sorted(_DISK_WRITE_ALLOWLIST)}）——音频落盘只许 "
                "synthesize 一处"
            )
        if site.callee == "_store_cache" and site.func_name not in _CACHE_STORE_ALLOWLIST:
            problems.append(
                f"A2：函数 {site.func_name} 行 {site.lineno} 调用 _store_cache( "
                "——缓存写入只许 synthesize 一处"
            )
    syn_writes = [
        s
        for s in sites
        if s.func_name == "synthesize" and s.callee in {"write_bytes", "_store_cache"}
    ]
    syn_inspects = [
        s
        for s in sites
        if s.func_name == "synthesize" and s.callee == "_inspect_wav_bytes"
    ]
    if syn_writes and not syn_inspects:
        problems.append(
            "A2：synthesize 落盘/入缓存但全函数未调用 _inspect_wav_bytes"
            "——体检闸被绕开"
        )
    elif syn_writes and syn_inspects:
        first_write = min(s.lineno for s in syn_writes)
        first_inspect = min(s.lineno for s in syn_inspects)
        if first_write < first_inspect:
            problems.append(
                f"A2：synthesize 行 {first_write} 的落盘/缓存写早于行 "
                f"{first_inspect} 的体检——坏字节可能先落盘"
            )

    # ---- A3 取文口先行 ----
    for site in sites:
        if site.callee != "synthesize":
            continue
        if site.func_name == "<module>":
            problems.append(
                f"A3：模块级（行 {site.lineno}）直接调用 synthesize——"
                "出站装配必须在能力函数内"
            )
            continue
        resolves = [
            s
            for s in sites
            if s.func_name == site.func_name and s.callee == "resolve_speech_text"
        ]
        if not resolves:
            problems.append(
                f"A3：函数 {site.func_name} 行 {site.lineno} 调用 synthesize，"
                "但函数内没有 resolve_speech_text——打码/内容门取文口被绕开"
            )
        elif min(s.lineno for s in resolves) > site.lineno:
            problems.append(
                f"A3：函数 {site.func_name} 的 synthesize（行 {site.lineno}）"
                "先于 resolve_speech_text——取文口被绕开"
            )

    # ---- A4 audio 出站构造绑定 synthesize ----
    synth_first: dict[str, int] = {}
    for site in sites:
        if site.callee == "synthesize":
            known = synth_first.get(site.func_name)
            if known is None or site.lineno < known:
                synth_first[site.func_name] = site.lineno
    for site in sites:
        if not site.label:
            continue
        synth_at = synth_first.get(site.func_name)
        if synth_at is None:
            problems.append(
                f"A4：函数 {site.func_name} 行 {site.lineno} 构造 {site.label} "
                "出站，但函数内没有 synthesize 调用——音频来路不明"
            )
        elif synth_at > site.lineno:
            problems.append(
                f"A4：函数 {site.func_name} 行 {site.lineno} 的 {site.label} "
                f"构造先于行 {synth_at} 的 synthesize——音频尚未产出即出站"
            )
    return problems


def _keyword_value(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _rule_private_import_ban() -> list[str]:
    """A5：plugins/** 其他模块不得引用私有管线件（静态 import/属性/字符串）。"""
    problems: list[str] = []
    canonical = _TTS_SOURCE.resolve()
    for path in sorted(_PLUGIN_ROOT.rglob("*.py")):
        if path.resolve() == canonical:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(name in text for name in _PRIVATE_PIPELINE_NAMES):
            continue
        try:
            tree = _parse(text)
        except SyntaxError:
            continue
        module_path = path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()
        imports_tts = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "tts" or node.module.endswith(".tts")
            ):
                imports_tts = True
                for alias in node.names:
                    if alias.name in _PRIVATE_PIPELINE_NAMES:
                        problems.append(
                            f"A5：{module_path}:{node.lineno} 静态 import "
                            f"私有管线件 {alias.name}——旁支直连面"
                        )
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _PRIVATE_PIPELINE_NAMES
                and imports_tts
            ):
                problems.append(
                    f"A5：{module_path}:{node.lineno} 以属性形态访问私有管线件 "
                    f"{node.attr}"
                )
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in _PRIVATE_PIPELINE_NAMES
            ):
                problems.append(
                    f"A5：{module_path}:{node.lineno} 以字符串形态引用私有管线件"
                    f"「{node.value}」（getattr/import_module 旁支形态）"
                )
    return problems


# ==================== 正例门（对全部在册真身源码，逐文件） ====================


def _scan_source(path: Path) -> list[str]:
    """对单在册真身文件跑 A1-A4，违规清单带文件前缀（多路径下可定位）。"""
    rel = path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()
    return [f"[{rel}] {problem}" for problem in _scan_tts_source(_read(path))]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _scan_registered() -> list[str]:
    return [problem for source in _VOICE_OUTBOUND_SOURCES for problem in _scan_source(source)]


def _synthesize_call_sites(path: Path) -> list[int]:
    """该文件里所有 ``synthesize(`` 调用行号（A3/A4 的射程判据来源）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _module_sites(tree) if s.callee == "synthesize"]


def _audio_construction_sites(path: Path) -> list[int]:
    """该文件里所有 audio 出站构造行号（kwarg 直挂与 update={'audio': …} 两形态）。"""
    tree = _parse(_read(path))
    return [s.lineno for s in _module_sites(tree) if s.label]


def _walk_plugin_py() -> list[Path]:
    return sorted(p for p in _PLUGIN_ROOT.rglob("*.py") if p.is_file())


def _rel_to_repo(path: Path) -> str:
    return path.relative_to(_PLUGIN_ROOT.parent.parent.parent).as_posix()


def test_gate1_scan_set_is_exhaustive_over_plugins_tree() -> None:
    """射程穷举锁：全树重扫，新出现的合成调用点/音频构造点必须登记或显式豁免。

    这条门是「扩面」本身的执法件——没有它，登记清单会随第三条路出现而静默失真，
    门退回「恰好只有一条路时才成立」。
    """
    registered = {p.resolve() for p in _VOICE_OUTBOUND_SOURCES}
    unregistered_synthesizers: list[str] = []
    untagged_audio: list[str] = []
    for path in _walk_plugin_py():
        text = _read(path) if path.suffix == ".py" else ""
        if "synthesize" not in text and "audio" not in text:
            continue
        try:
            tree = _parse(text)
        except SyntaxError:  # pragma: no cover - 生产树不允许语法错，出现即另有门拦
            continue
        sites = _module_sites(tree)
        rel = path.relative_to(_PLUGIN_ROOT).as_posix()
        if any(s.callee == "synthesize" for s in sites) and path.resolve() not in registered:
            unregistered_synthesizers.append(rel)
        if (
            any(s.label for s in sites)
            and rel not in _NON_TTS_AUDIO_CONSTRUCTION_SITES
            and path.resolve() not in registered
        ):
            untagged_audio.append(rel)
    assert not unregistered_synthesizers, (
        "语音产出出站路径出现未登记的合成调用点："
        f"{unregistered_synthesizers}——须加入 _VOICE_OUTBOUND_SOURCES 并过 A1-A4"
    )
    assert not untagged_audio, (
        f"出现未归类的 audio 构造点：{untagged_audio}——要么登记为语音出站路径，"
        "要么进 _NON_TTS_AUDIO_CONSTRUCTION_SITES 写明非合成理由"
    )
    # 反向锁：清单不得虚挂（登记的豁免文件若已无 audio 构造点，说明面已迁移，须清理）。
    stale_exemptions = [
        rel
        for rel, _reason in _NON_TTS_AUDIO_CONSTRUCTION_SITES.items()
        if not _audio_construction_sites(_PLUGIN_ROOT / rel)
    ]
    assert not stale_exemptions, f"豁免表虚挂（该文件已无 audio 构造点）：{stale_exemptions}"


@pytest.mark.parametrize("rule_prefix", ["A1", "A2", "A3", "A4"])
@pytest.mark.parametrize(
    "source_name",
    [p.relative_to(_PLUGIN_ROOT).as_posix() for p in _VOICE_OUTBOUND_SOURCES],
)
def test_gate1_real_sources_pass_rule(rule_prefix: str, source_name: str) -> None:
    """A1-A4 正例：每一条在册语音产出出站路径逐规则过门（含第二出站路）。"""
    path = _PLUGIN_ROOT / source_name
    assert path in _VOICE_OUTBOUND_SOURCES, f"{source_name} 未在册"
    problems = [p for p in _scan_source(path) if f"] {rule_prefix}：" in p]
    assert not problems, (
        f"TTS 出站入口门 {rule_prefix} 对 {source_name} 被触发：\n" + "\n".join(problems)
    )


def test_gate1_real_sources_declare_synthesize_and_audio_sites() -> None:
    """在册路径必须真的在射程内（防「登记了但没构造点」的假扩面）。"""
    for path in _VOICE_OUTBOUND_SOURCES:
        assert _synthesize_call_sites(path), f"{_rel_to_repo(path)} 无 synthesize 调用点"
    assert _audio_construction_sites(_VOICE_ENRICHER_SOURCE), (
        "voice_enricher 的 audio 构造点未被检测器识别——A4 对其形同虚设"
    )


def test_gate1_all_registered_sources_fully_clean() -> None:
    """全集正例：所有在册语音出站路径 A1-A4 零违规（一条红即整门红）。"""
    problems = _scan_registered()
    assert not problems, (
        "TTS 出站入口门（单一入口契约）被触发：\n" + "\n".join(problems)
    )


def test_gate1_no_private_pipeline_imports() -> None:
    """A5 正例：plugins/** 无私有管线件外借。"""
    problems = _rule_private_import_ban()
    assert not problems, "TTS 出站入口门 A5（私有面不外借）被触发：\n" + "\n".join(
        problems
    )


# ==================== 负样本自检（注入坏样本 → 门必须变红） ====================

# 负样本①：旁支直拼——_request_tts 内联手搓请求体字典，不经 _build_request_payload。
_BYPASS_INLINE_PAYLOAD = """
import httpx


def _request_tts(*, api_url, text, ref, params, timeout_seconds):
    payload = {
        "text": text,
        "text_lang": "ZH",
        "ref_audio_path": ref.path,
        "prompt_text": ref.text,
        "prompt_lang": ref.lang,
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 0.9,
        "text_split_method": "cut5",
        "speed_factor": 0.85,
        "seed": -1,
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": True,
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(api_url.rstrip("/") + "/tts", json=payload)
    return response.content
"""

# 负样本②：体检闸绕行——不体检直接落盘+入缓存。
_BYPASS_INSPECTION = """
def _fast_lane(text, ref, params, output_dir, key):
    raw = _request_tts(text=text, ref=ref, params=params, timeout_seconds=60.0)
    target = output_dir / (key + ".wav")
    target.write_bytes(raw)
    _store_cache(key, target)
    return target
"""

# 负样本③：取文口绕行——synthesize 照调但未经 resolve_speech_text（A3 射程）。
_BYPASS_RESOLVE = """
def capability(message, _decision):
    path, reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text=message.plain_text,
        ref=None,
        params=None,
        output_dir=None,
    )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(path)}],
    )
"""

# 负样本④：音频来路不明——函数内没有 synthesize 调用却构造 audio 出站
# （kwarg 直挂与 update={"audio": …} 两形态都要抓，A4 射程）。
_BYPASS_AUDIO_KWARG = """
def capability(message, _decision):
    cached = _lookup_cache(message.request_id)
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(cached)}],
    )
"""

_BYPASS_AUDIO_UPDATE_DICT = """
def attach_voice(message, result):
    return result.model_copy(
        update={"audio": [{"file": str(_rogue_path(message))}]}
    )
"""


def test_gate1_negative_inline_payload_caught() -> None:
    """负样本①必须被抓：内联请求体 = 装配点绕行。"""
    problems = _scan_tts_source(_BYPASS_INLINE_PAYLOAD)
    a1 = [p for p in problems if p.startswith("A1")]
    assert a1, "负样本①（内联请求体旁支）未被 A1 抓红——门失效：" + repr(problems)


def test_gate1_negative_inspection_bypass_caught() -> None:
    """负样本②必须被抓：不体检落盘+入缓存。"""
    problems = _scan_tts_source(_BYPASS_INSPECTION)
    a2 = [p for p in problems if p.startswith("A2")]
    assert a2, "负样本②（体检闸绕行）未被 A2 抓红——门失效：" + repr(problems)
    assert any("_fast_lane" in p for p in a2), "A2 未定位到旁支函数名：" + repr(a2)


def test_gate1_negative_resolve_bypass_caught() -> None:
    """负样本③必须被抓：synthesize 照调但取文口被绕开。"""
    problems = _scan_tts_source(_BYPASS_RESOLVE)
    a3 = [p for p in problems if p.startswith("A3")]
    assert a3, "负样本③（取文口绕行）未被 A3 抓红——门失效：" + repr(problems)


def test_gate1_negative_audio_from_nowhere_caught() -> None:
    """负样本④必须被抓：无 synthesize 调用却构造 audio 出站（两形态）。"""
    problems_kwarg = _scan_tts_source(_BYPASS_AUDIO_KWARG)
    a4_kwarg = [p for p in problems_kwarg if p.startswith("A4")]
    assert a4_kwarg, "负样本④a（audio= 直挂，无 synthesize）未被 A4 抓红——门失效：" + repr(
        problems_kwarg
    )
    problems_update = _scan_tts_source(_BYPASS_AUDIO_UPDATE_DICT)
    a4_update = [p for p in problems_update if p.startswith("A4")]
    assert a4_update, "负样本④b（update 字典形态，无 synthesize）未被 A4 抓红——门失效：" + repr(
        problems_update
    )


def test_gate1_negative_private_import_caught() -> None:
    """负样本⑤必须被抓：外部模块静态 import 私有管线件。

    真扫描面在 plugins/**（test_gate1_no_private_pipeline_imports）；
    本用例对同一判定内核注入伪模块源码，验证逻辑本身有杀伤力。
    """
    pseudo = (
        "from plugins.bot_unified_runtime.domains.media.capabilities.tts import (\n"
        "    _request_tts,\n"
        ")\n"
    )
    tree = _parse(pseudo)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (
            node.module == "tts" or node.module.endswith(".tts")
        ):
            for alias in node.names:
                if alias.name in _PRIVATE_PIPELINE_NAMES:
                    problems.append(
                        f"A5：pseudo_vendor.py:{node.lineno} 静态 import "
                        f"私有管线件 {alias.name}——旁支直连面"
                    )
    assert problems, "负样本⑤（私有面外借）未被 A5 逻辑抓红——门失效"


def test_gate1_positive_faithful_pipeline_zero_violations() -> None:
    """正例对照：忠实迷你管线零违规——防检测器过度开火。"""
    faithful = '''
def _build_request_payload(text, ref, params):
    return {"text": text, "text_lang": "zh"}


def _inspect_wav_bytes(data):
    return ""


def _store_cache(key, path):
    return None


def _request_tts(*, api_url, text, ref, params, timeout_seconds):
    import httpx

    payload = _build_request_payload(text, ref, params)
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(api_url.rstrip("/") + "/tts", json=payload)
    return response.content


def resolve_speech_text(config, message, text):
    return text, ""


def synthesize(*, api_url, text, ref, params, output_dir, config, message):
    audio = _request_tts(
        api_url=api_url, text=text, ref=ref, params=params, timeout_seconds=1.0
    )
    bad = _inspect_wav_bytes(audio)
    if bad:
        return None, bad
    target = output_dir / "a.wav"
    target.write_bytes(audio)
    _store_cache("k", target)
    return target, ""


def capability(message, _decision):
    speech, blocked = resolve_speech_text(None, message, message.plain_text)
    if blocked:
        return None
    path, _reason = synthesize(
        api_url="http://127.0.0.1:9880",
        text=speech,
        ref=None,
        params=None,
        output_dir=None,
        config=None,
        message=message,
    )
    return CapabilityResult(
        request_id=message.request_id,
        capability_id="bot.tts",
        kind="text",
        audio=[{"file": str(path)}],
    )
'''
    problems = _scan_tts_source(faithful)
    assert not problems, "忠实迷你管线被误判（门过度开火）：" + repr(problems)


# ==================== FIX8 变异自检：门对第二出站路（voice_enricher）真的承重 ====================
# 底本=真身 voice_enricher.py 源码（**不改生产文件**，只在内存里做单点文本变异），
# 每条变异都同时断言「原样不红 / 变异必红」——否则无法区分「门有效」与「门恰好没反应」。

_ENRICHER_ANCHOR_MAX_CHARS = (
    '        max_chars = int(getattr(config, "bot_tts_auto_reply_max_chars", 0) or 0)\n'
)
_ENRICHER_ANCHOR_RESOLVE = "        speech, blocked = resolve_speech_text("
_ENRICHER_ANCHOR_SYNTH = "        path, reason = synthesize("


def _enricher_mutated(*, old: str, new: str) -> str:
    """单点文本变异（锚点必须唯一命中一次，否则变异本身不可信）。"""
    source = _read(_VOICE_ENRICHER_SOURCE)
    assert source.count(old) == 1, f"变异锚点命中 {source.count(old)} 次（应为 1）：{old!r}"
    return source.replace(old, new)


def _rules_of(problems: list[str], prefix: str) -> list[str]:
    """按规则取违规：兼容「裸 _scan_tts_source 输出」与「带文件前缀的 _scan_source 输出」。"""
    marker = f"{prefix}："
    return [p for p in problems if marker in p]


def test_mutate_enricher_pristine_source_is_clean() -> None:
    """变异前正例：真身 voice_enricher A1-A4 零违规（本席扩面时实测=空清单）。"""
    problems = _scan_source(_VOICE_ENRICHER_SOURCE)
    assert not problems, "底本已红，变异自检失去对照基线：" + repr(problems)


def test_mutate_enricher_bypasses_central_text_gate_caught_by_a3() -> None:
    """A3 杀伤力：把中央取文口换成本地自取文（打码/清洗/词典/内容门全绕）。"""
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_RESOLVE, new="        speech, blocked = _local_text_gate("
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A3"), (
        "voice_enricher 绕过 resolve_speech_text 未被 A3 抓红——门对新路径不承重："
        + repr(problems[:5])
    )


def test_mutate_enricher_synthesize_before_text_gate_caught_by_a3_order() -> None:
    """A3 序杀伤力：取文口仍在、但合成发生在其之前（review 后正文未过门即出货）。"""
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_MAX_CHARS,
        new=(
            "        _early_path, _early_reason = synthesize(\n"
            "            api_url='', text=result.body or '', ref=None, params=None,\n"
            "            output_dir=None,\n"
            "        )\n"
            + _ENRICHER_ANCHOR_MAX_CHARS
        ),
    )
    problems = _rules_of(_scan_tts_source(mutated), "A3")
    assert problems, "synthesize 早于取文口未被 A3 抓红（行序判据失效）"
    assert any("先于" in p for p in problems), f"A3 未走序分支：{problems}"


def test_mutate_enricher_audio_without_synthesize_caught_by_a4() -> None:
    """A4 杀伤力：audio 构造仍在，但产物来路不再是中央 synthesize。"""
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_SYNTH, new="        path, reason = _rogue_produce("
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A4"), (
        "voice_enricher 音频来路不明未被 A4 抓红——门对新路径不承重："
        + repr(problems[:5])
    )


def test_mutate_enricher_second_http_path_caught_by_a1() -> None:
    """A1 杀伤力：新路径自己拼引擎 HTTP 请求（第二条出站请求）。"""
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_MAX_CHARS,
        new=(
            "        import httpx as _httpx\n"
            "        with _httpx.Client(timeout=1.0) as _client:\n"
            "            _client.post('http://127.0.0.1:9880/tts', json={'text': 'x'})\n"
            + _ENRICHER_ANCHOR_MAX_CHARS
        ),
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A1"), (
        "voice_enricher 自建 HTTP 请求未被 A1 抓红：" + repr(problems[:5])
    )


def test_mutate_enricher_write_bytes_outside_synthesize_caught_by_a2() -> None:
    """A2 杀伤力：新路径不经体检直接落盘音频字节。"""
    mutated = _enricher_mutated(
        old=_ENRICHER_ANCHOR_MAX_CHARS,
        new=(
            "        _rogue_target = _output_dir(config) / 'rogue.wav'\n"
            "        _rogue_target.write_bytes(b'RIFF')\n"
            + _ENRICHER_ANCHOR_MAX_CHARS
        ),
    )
    problems = _scan_tts_source(mutated)
    assert _rules_of(problems, "A2"), (
        "voice_enricher 绕体检落盘未被 A2 抓红：" + repr(problems[:5])
    )
