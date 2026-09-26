"""S211 · 目标 5：绘画 provider 在册键「唯一走真身册读」的对账 + 活性 + fail-closed 锁。

真身＝``domains/core.capability_manifest.FACETS["creation.image.generate"].config_keys``
（读侧 ``config_keys_for``）。本窗此前该枚键在**三处各写一份**（册 / reserved_provider 探测表
/ provider_factory 选择器常量），撞"禁第二处手抄"。落码后取数链＝
``provider_factory.provider_selector_config_key()`` → ``reserved_provider.image_presence_keys()``
→ ``config_keys_for("creation.image.generate")``——**一条链、一个家**。本件钉四件事：

1. 三方等值：册 == 探测表 == 工厂选择器键（起点==实测，非"看起来一致"）。
2. 在册：这枚键名必须是 ``config.py`` 的真字段（点一枚不存在的键比不点名更坏）。
3. **活性**（不是副本）：monkeypatch 真身册读数 → 本域取数链**当场跟着变**；
   等值抄一份副本骗不过这条（与 ``test_config_keys_single_source.py`` 同一哲学）。
4. **fail-closed**：册返回空 / 多义 → 本域抛错，绝不退化成"空探测表"或"猜第一枚"。
5. 依赖方向：本域读真身册（数据叶 ``domains.core``），但绝不读中央执行协议
   （``runtime.capability_protocols``）——后者是 reserved_provider 头注写死的红线。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.core import capability_manifest as cm
from plugins.bot_unified_runtime.domains.creation import reserved_provider as rprov
from plugins.bot_unified_runtime.domains.creation.image import provider_factory as pf

_REPO = Path(__file__).resolve().parents[1]
_FACTORY = (
    _REPO / "plugins" / "bot_unified_runtime" / "domains" / "creation" / "image"
    / "provider_factory.py"
)
_RESERVED = _REPO / "plugins" / "bot_unified_runtime" / "domains" / "creation" / "reserved_provider.py"

_CONFIG_FIELDS = set(Config.model_fields)


# ---------------------------------------------------------------------------
# 1 + 2：三方等值 & 键在册
# ---------------------------------------------------------------------------


def test_image_selector_key_traces_to_single_manifest_source() -> None:
    """册 == 探测表 == image_presence_keys() == 工厂选择器键（一条链、一个家）。"""
    keys = cm.config_keys_for("creation.image.generate")
    assert keys == ("bot_creation_image_provider",)  # 现值起点（非"达标"宣称）
    assert rprov.image_presence_keys() == keys
    assert rprov.PROVIDER_PRESENCE_KEYS["creation.image"] == keys
    assert (pf.provider_selector_config_key(),) == keys


def test_image_key_is_registered_config_field() -> None:
    """在册：工厂选择器键名必须是 config.py 真字段（探测表点了不存在的键＝误导运维）。"""
    assert pf.provider_selector_config_key() in _CONFIG_FIELDS
    assert set(rprov.image_presence_keys()) <= _CONFIG_FIELDS


# ---------------------------------------------------------------------------
# 3：活性——值确实来自真身册，不是一份等值副本
# ---------------------------------------------------------------------------


def test_image_presence_keys_live_reads_manifest_not_a_copy(monkeypatch) -> None:
    """monkeypatch 真身册读数 → 本域取数链当场跟着变（等值副本骗不过这条）。"""
    monkeypatch.setattr(rprov, "config_keys_for", lambda cid: ("poisoned_from_manifest",))
    # reserved_provider 侧
    assert rprov.image_presence_keys() == ("poisoned_from_manifest",)
    # provider_factory 侧（经 reserved_provider 同源，活性传递到底）
    assert pf.provider_selector_config_key() == "poisoned_from_manifest"
    # 且 build_image_provider 的理由串点名的是**跟着变的键名**，不是写死的旧名
    from types import SimpleNamespace

    sel = pf.build_image_provider(SimpleNamespace())
    assert "poisoned_from_manifest" in sel.reason
    assert sel.state == "not_configured"


def test_poison_empty_manifest_fails_closed(monkeypatch) -> None:
    """册返回空 → 抛错（不退化成空探测表：空会让缺位告警永不太平）。"""
    monkeypatch.setattr(rprov, "config_keys_for", lambda cid: ())
    try:
        rprov.image_presence_keys()
    except RuntimeError as exc:
        assert "真身册" in str(exc) or "绘画" in str(exc)
    else:  # pragma: no cover - 未抛即假绿
        raise AssertionError("册返回空却未 fail-closed＝静默退化成空探测表")


def test_poison_multi_manifest_fails_closed(monkeypatch) -> None:
    """册返回多枚 → 抛错（绘画选择器只认单枚 env，多义不猜第一枚）。"""
    monkeypatch.setattr(rprov, "config_keys_for", lambda cid: ("a_key", "b_key"))
    try:
        rprov.image_presence_keys()
    except RuntimeError:
        return
    raise AssertionError("多义在册键被静默挑第一枚＝本域偷偷再造判据")


# ---------------------------------------------------------------------------
# 5：禁第二处手抄 + 依赖方向（AST 静态锁）
# ---------------------------------------------------------------------------


def test_provider_factory_has_no_handwritten_config_key_literal() -> None:
    """工厂源码不得再出现"某在册键名"的字面量赋值（旧 selector_config_key 那枚的常驻反证）。"""
    tree = ast.parse(_FACTORY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            val = node.value.value
            if isinstance(val, str) and val in _CONFIG_FIELDS:
                raise AssertionError(
                    f"工厂手抄在册键字面量 {val!r}＝第二真身；唯一来源应为 config_keys_for"
                )
    # 反向：工厂必须经真身册来源读键（调用 image_presence_keys），否则上面只是"没抄也没读"。
    assert "image_presence_keys" in _FACTORY.read_text(encoding="utf-8")


def test_reserved_provider_reads_manifest_but_not_execution_protocol() -> None:
    """依赖方向：本域读真身册（数据叶），但绝不 import 中央执行协议（红线，勿破）。

    只查**真实 import 边**（AST），不查整篇文本——docstring 里"绝不 import
    capability_protocols"这句本身就含该词，拿子串判会打自己脸。
    """
    src = _RESERVED.read_text(encoding="utf-8")
    assert "config_keys_for" in src  # 真身册读点在场
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert any("capability_manifest" in m for m in imported), "本域未读真身册＝目标 5 未落"
    assert not any("capability_protocols" in m for m in imported), (
        "reserved_provider import 中央执行协议＝依赖方向反转（头注红线）"
    )
