"""S-SAFE2（59 号席，2026-09-28）显示名消毒的「根腿 + 注入三件套」锁。

盯两个此前**无册可依**的落点（取证＝`.superpowers/sdd/2026-09-27-fullload/logs/
SEAT-AUDIT-ROOT-STAGING-R.md` 孤儿段 O2；`P2D-injection.patch.md` 明文「不改根
`__init__.py`」⇒ 根腿消毒调用点长期没有自己的登记与锁）：

① blob 三件套：`security/injection.py` 必须同时露出 `sanitize_display_name` /
   `display_name_spoof_tags` / `SPOOF_SUPPRESSED_DISPLAY` / `render_safe_display_name`
   ——红时点名 `patches/INJECTION-R2.md`（完整可落盘 blob 册）；
② 根腿 AST：根 `__init__.py` 的 `_incoming_from_nonebot_event` 必须把
   `sender_display_name` 过 `injection.sanitize_display_name`——红时点名
   `patches/SAFE2-ROOT-O2.patch.md`（独立格子集，须与 injection blob 同 commit）；
③ 注毒自证：摘掉判据真身 `attack_surface.strip_display_controls` /
   `fold_spoofed_role_keywords`（接成恒等），伪装必须**活下来**——
   证明绿的是这道闸本身，而不是别处的偶然；display_name 伪造开了标记 ⇒ 恰锁 FAILED；
④ 不误伤最小表：`render_safe_display_name` 对合法名逐字节不变、空进空出、
   折不动的近似形整格屏蔽（与 P2D 锁同一把尺，这里只钉「处置口三件套语义齐」）。

判据零副本（AGENTS 台账 #58★）：本件只调中央件与 injection 口，不抄码点表。
用例数以实跑为准（规则 10，本文件不写计数）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.security import injection
from plugins.bot_unified_runtime.domains.core.safety_exec import attack_surface

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"
INJECTION_SRC = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "chat_reply"
    / "security"
    / "injection.py"
)

RLO = chr(0x202E)  # RIGHT-TO-OVERRIDE
ZWSP = chr(0x200B)  # 零宽空格
CYR_A = chr(0x0430)  # 西里尔 а（混拉丁伪装 "admin" 的头号形态）

_PORT_NAMES = (
    "sanitize_display_name",
    "display_name_spoof_tags",
    "SPOOF_SUPPRESSED_DISPLAY",
    "render_safe_display_name",
)


# ==================== ① 处置口三件套（blob 在场性） ====================


def test_injection_blob_exposes_the_full_display_port() -> None:
    missing = [n for n in _PORT_NAMES if not hasattr(injection, n)]
    assert not missing, (
        f"injection 显示面处置口残缺 {missing}：完整 blob 未落盘，"
        "请落 patches/INJECTION-R2.md（HEAD 基线 + S-FILESAFE 段 + P2D-injection 段）"
    )
    marker = injection.SPOOF_SUPPRESSED_DISPLAY
    assert isinstance(marker, str) and marker, "屏蔽标记必须是可见非空串"
    assert callable(injection.render_safe_display_name)


# ==================== ② 根腿 AST（O2 格回潮可见） ====================


def _incoming_fn(tree: ast.AST) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_incoming_from_nonebot_event":
            return node
    return None


def test_root_ingest_sanitizes_sender_display_name() -> None:
    """根摄取层必须把 sender_display_name 过消毒口——摘掉 O2 腿本锁即红。"""
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8"), filename=str(ROOT_INIT))
    fn = _incoming_fn(tree)
    assert fn is not None, "根摄取函数 _incoming_from_nonebot_event 不在——本锁指认的腿搬家了，改锁先改册"

    sanitizer_names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(
            "security.injection"
        ):
            for alias in node.names:
                if alias.name == "sanitize_display_name":
                    sanitizer_names.add(alias.asname or alias.name)
    assert sanitizer_names, (
        "根 __init__.py 的摄取函数没有 import sanitize_display_name："
        "补丁 patches/SAFE2-ROOT-O2.patch.md 未落盘或被摘线"
        "（该格须与 injection.py blob 同 commit——HEAD 基线上单提本格会 AttributeError）"
    )

    def _uses_sanitizer(value: ast.expr) -> bool:
        for sub in ast.walk(value):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id in sanitizer_names
            ):
                return True
        return False

    # 直接形：sender_display_name = sanitize(...) or None
    temps: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            if _uses_sanitizer(node.value):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id != "sender_display_name":
                        temps.add(t.id)
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "sender_display_name":
                    if _uses_sanitizer(node.value):
                        return
                    if isinstance(node.value, ast.Name) and node.value.id in temps:
                        return
    pytest.fail(
        "sender_display_name 没有经过消毒口（直存或一步中转都没接上）："
        "O2 根腿被摘或被改写成了第二真身（判据真身只在 injection.sanitize_display_name）"
    )


# ==================== ③ 注毒自证：摘闸 ⇒ 伪装必活下来 ====================


def test_poison_strip_makes_invisible_spoof_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_op(text: str) -> str:
        return text

    # injection 经 `_attack_surface.<fn>` 属性查找调用，patch 登记件名字即咬得住。
    monkeypatch.setattr(attack_surface, "strip_display_controls", _no_op)
    poisoned = injection.sanitize_display_name(f"守岸人{ZWSP}助手")
    assert ZWSP in poisoned, "注毒未生效：显示名消毒另有第二真身，找出它并合并判据"


def test_poison_fold_makes_homoglyph_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_op(text: str) -> str:
        return text

    monkeypatch.setattr(attack_surface, "fold_spoofed_role_keywords", _no_op)
    assert injection.sanitize_display_name(f"{CYR_A}dmin") == f"{CYR_A}dmin"


def test_poison_port_fails_closed_to_suppression(monkeypatch: pytest.MonkeyPatch) -> None:
    """摘掉**折叠**后走处置口：救不回的近似形必须落屏蔽格，而不是原样出图。"""

    def _no_op(text: str) -> str:
        return text

    if not hasattr(injection, "render_safe_display_name"):
        pytest.skip("处置口 blob 未落盘（见锁①），本腿随 INJECTION-R2 生效")
    monkeypatch.setattr(attack_surface, "fold_spoofed_role_keywords", _no_op)
    out = injection.render_safe_display_name(f"{CYR_A}dmin")
    assert out == injection.SPOOF_SUPPRESSED_DISPLAY, (
        f"摘闸后伪装名原样出图：{out!r}——「display_name 伪造开了标记」形态，恰应锁死"
    )


# ==================== ④ 不误伤最小表（口径与 P2D 同尺） ====================


def test_render_port_keeps_legit_names_byte_identical() -> None:
    if not hasattr(injection, "render_safe_display_name"):
        pytest.skip("处置口 blob 未落盘（见锁①）")
    for name in ("守岸人", "漂泊者", "admin_guide", "администратор", "报告Ａ"):
        assert injection.render_safe_display_name(name) == name, name
    for blank in ("", "   ", "\t"):
        assert injection.render_safe_display_name(blank) == ""


def test_render_port_strips_bidi_and_suppresses_unfolds() -> None:
    if not hasattr(injection, "render_safe_display_name"):
        pytest.skip("处置口 blob 未落盘（见锁①）")
    assert injection.render_safe_display_name(f"群名{RLO}admin") == "群名admin"
    # 全角 ｓｈｅｌｌ：冒充英文名的近似形，折了就等于改名 ⇒ 整格屏蔽
    fullwidth_shell = "".join(chr(ord(c) + 0xFEE0) for c in "shell")
    assert (
        injection.render_safe_display_name(fullwidth_shell)
        == injection.SPOOF_SUPPRESSED_DISPLAY
    )


# ==================== ⑤ 判据单源：消费侧不长第二张码点表 ====================


def test_root_leg_carries_no_second_codepoint_roster() -> None:
    """O2 根腿只准「调消毒口」，根文件不得自带 Bidi/零宽字面量或第二套映射表。"""
    source = ROOT_INIT.read_text(encoding="utf-8")
    for ch in (RLO, ZWSP, chr(0x202A), chr(0x2066), chr(0xFEFF)):
        assert ch not in source, f"根 __init__.py 含字面控制字符 U+{ord(ch):04X}"
    for marker in ("_CONFUSABLE_MAP =", "LOOKALIKE_MAP =", "_BIDI_CONTROLS ="):
        assert marker not in source, f"根文件自建了第二套伪装判据表：{marker}"
    injection_src = INJECTION_SRC.read_text(encoding="utf-8")
    for ch in (RLO, ZWSP):
        assert ch not in injection_src, "injection 件里出现字面伪装字符（判据真身在登记件）"
