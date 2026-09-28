"""SUBDELIVERY-4（ATK-SUB-4 投递面消毒腿的在册账）补丁预备锁。

分工：vision 输入腿（远端标题伪装「用户随图消息」）已随 `34c39de` 修——本文件
②腿把它钉死为不回退；根侧出站正文腿已在飞根件里（其 AST 锁＝在飞件
`test_subscribe_root_wiring_sub2sub4.py`，不在此重复）。本席残票＝
**在册账缺席**：`guard_secondhand_text` 的在册名单（attack_surface.py，
AS-INBOX-DIGEST-RETOLD 同族格式）里没有订阅链路，攻击面图上这条腿是隐形的。

两腿两态：
- ①（HEAD 红 → SUBDELIVERY-4 patch 落盘后绿）`AS-SUBSCRIBE-FEED` 必须入
  `attack_surface` 注册表且带防线探针（DEFENDED/PARTIAL 无探针＝在册判据违规，
  `_required_coverage_violations` 同尺）；
- ②（HEAD 绿）`describe_subscription_item` 体内必须出现 `guard_secondhand_text`
  调用——订阅条目视觉腿的 34c39de 修复哨兵，防改名/回退把「已消毒」变暗亏。

离线：只读盘上文本与在册常量，零装配。
"""

from __future__ import annotations

import ast
from pathlib import Path

from plugins.bot_unified_runtime.domains.core.safety_exec import attack_surface

REPO_ROOT = Path(__file__).resolve().parents[1]
VISION_DESCRIBE = (
    REPO_ROOT
    / "plugins"
    / "bot_unified_runtime"
    / "domains"
    / "media"
    / "ingest"
    / "vision_describe.py"
)

SURFACE_ID = "AS-SUBSCRIBE-FEED"


def test_subscribe_feed_surface_is_registered() -> None:
    """①（**待落盘**：patch 全文见 SUBDELIVERY-4.patch.md）。

    落盘前红＝现状在册账缺席（SEAT-ATK-SUBSCRIBE 向量①的点名事实）；
    落盘后绿。attack_surface.py 现为他席在飞态（M），落盘前须读最新态再贴。
    """
    assert SURFACE_ID in attack_surface.surface_ids(), (
        "订阅条目二手链路未入攻击面在册名单——名单是门读的尺，隐形＝零执法"
    )
    entry = attack_surface.register_by_id(SURFACE_ID)
    assert entry.probes, f"{SURFACE_ID} 判为 {entry.state.value} 却无防线探针（散文不算执法）"


def _func_source(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )
    assert fn is not None, f"{path.name} 里找不到 {name}＝坐标已漂，本锁失明"
    return fn


def test_subscription_vision_input_passes_secondhand_throat() -> None:
    """②（HEAD 绿）34c39de 哨兵：远端标题不再以「用户本人」身份裸进 prompt。"""
    fn = _func_source(VISION_DESCRIBE, "describe_subscription_item")
    calls = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "guard_secondhand_text" in calls, (
        "订阅标题的视觉前置咽喉回退（ATK-SUB-4 腿①复发）——真身＝"
        "chat_reply/security/injection.py，禁手拼包裹字面量"
    )
