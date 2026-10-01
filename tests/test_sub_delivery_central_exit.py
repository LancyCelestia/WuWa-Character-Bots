"""SUBDELIVERY-3（F-1 收编中央出口 + BYPASS_SUSPECT 改判 + 幂等键段）补丁预备锁。

在册事实（不改判、不弱化）：`outbound_registry.py` 的
`DirectSendEntry("__init__.py:_deliver_v2_event", …, BYPASS_SUSPECT)` 由
S-FIX-SUB-SEC 登记（该件今天在他席在飞态，HEAD 上还没有这条目——本文件不钉
registry 形状，改判动作写在 patch md 里）。台账 #46★ 的硬线在这里的含义：
`sub_push` 族收编进中央出口后，dedupe 键每一段都必须过 `is_legal_segment`
（段内禁 `:`），脏段在开闸态＝整条静默丢。

两腿两态：
- ①（HEAD 绿）纯逻辑洗段腿：旧冒号形 event_id（f3e2972 前的存量行）与新形
  `sub-<hex>` 拼 `sub_push` 族键，逐段过 `active_push_key_segment` 后必须
  段段合法、近似单射、新形逐字节不变（迁移锁同口径）；
- ②（红，**待裁 Q-2 + 待 root 批**）AST 根锁：根 `_deliver_v2_event` 体内出现
  中央主动推送出口符号 `_push_via_central_exit_now`，且申报
  `dedupe_namespace="sub_push"`——收编真落地才会绿；今天不许为凑绿放宽。

离线：零网络、零 NoneBot、不 import 根件。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.emergency_info.service.dedupe import (
    active_push_key_segment,
    is_legal_segment,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = REPO_ROOT / "plugins" / "bot_unified_runtime" / "__init__.py"

_SUB_PUSH_NAMESPACE = "sub_push"


def test_sub_push_key_segments_legal_and_near_injective() -> None:
    """①（HEAD 绿）台账 #46★ 键段红线的收编前体检（纯逻辑，不碰生产）。"""
    legacy_event_id = "probe:creator:collide:video:a:b"  # f3e2972 前的冒号拼串形
    new_event_id = "sub-0123456789abcdef0123456789abcdef"  # 规范摘要形
    destination_key = "123"  # subscription_destinations 行 id（自增数字）

    legacy_seg = active_push_key_segment(legacy_event_id)
    assert is_legal_segment(legacy_seg), f"旧冒号形洗完仍非法段：{legacy_seg!r}"
    assert ":" not in legacy_seg
    # 新形零改写：已入生产库的合法键段逐字节不变（迁移锁同一条纪律）
    assert active_push_key_segment(new_event_id) == new_event_id
    # 近似单射：不同旧串不得折成同一段（S184 教训——同段＝共享幂等桶＝继续静默丢）
    siblings = [
        "probe:creator:collide:video:a:b",
        "probe:creator:collide:video:a",
        "probe:creator:collide:video:a:",
        "probe:creator:collide:vide:oa:b",
    ]
    washed = {active_push_key_segment(value) for value in siblings}
    assert len(washed) == len(siblings), f"洗段折叠：{sorted(washed)}"

    key = ":".join(
        [
            active_push_key_segment(_SUB_PUSH_NAMESPACE),
            legacy_seg,
            active_push_key_segment(destination_key),
        ]
    )
    assert key.count(":") == 2 and all(is_legal_segment(part) for part in key.split(":"))


def _root_delivery_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse(ROOT_INIT.read_text(encoding="utf-8-sig"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_deliver_v2_event"
        ),
        None,
    )
    assert fn is not None, "根文件里找不到 _deliver_v2_event＝锚点已漂，本锁失明"
    return fn


def test_root_delivery_goes_through_central_exit() -> None:
    """②（红·两态见 docstring）F-1 收编落地的 AST 哨兵。**待裁 Q-2**。

    修前红＝现状在册（BYPASS_SUSPECT 注记「F-1 落地后随迁改判」）；
    修后绿＝根腿经 `_push_via_central_exit_now(..., dedupe_namespace="sub_push")`。
    收编若被裁定为「另立波」，本锁保持红到那一波落地，期间由
    `test_subscription_per_destination_ledger_sub2.py` +
    `test_sub_delivery_pending_filter.py` 守逐目的地台账面。
    """
    fn = _root_delivery_fn()
    names = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_push_via_central_exit_now" in names, (
        "订阅投递仍走 pipeline→_deliver_transport_send_request 直落传输段"
        "＝BYPASS_SUSPECT 在册事实未翻正（F-1）"
    )
    declared = {
        keyword.value.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if isinstance(keyword.arg, str) and keyword.arg == "dedupe_namespace"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    assert _SUB_PUSH_NAMESPACE in declared, (
        "收编必须申报 sub_push 命名空间——漏报回落 emg 口径＝开闸态整链静默丢（R-CENTRAL C-1）"
    )
