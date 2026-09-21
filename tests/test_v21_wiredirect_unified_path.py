"""WIRE-DIRECT B2③ 契约锁：验收矩阵 L56/L57/L58/L65「走统一出站路径」结构断言。

取证结论（证据链见 ``docs/design/v21r4-b-WIRE-DIRECT-log.md`` §一，2026-09-19）：

- SCHEDULE 三行（L56/L57/L58）生产装配未接（production_wiring=not_wired）——
  ``domains/schedule/`` 域内不存在任何生产直连点可收编；域的出站咽喉唯有
  ``domains/schedule/delivery.py`` 的 ``queue.submit`` 鸭子协议切片
  （真实出站端口未授权前 queue=None → ``not_authorized`` 诚实干跑）。
  存量提醒生产线（根 ``__init__.py`` ``_deliver_due_reminders``）已走
  SendRequest→SendQueue→统一 transport，非绕行（行为面 tests/test_reminder_delivery.py）。
- DIVINATION-002（L65）QQ 出站走 CapabilityResult→pipeline→SendQueue 框架统一面；
  LLM 人格化解释端口=503 ``not_wired`` 诚实位（端口组性质，未获授权不得实装）。

本文件锁四行的「统一路径」结构性质，防后续装配波把直连点带进这两个域、
或解释端口诚实位被静默替换：

1. schedule 域 AST 级零 ``call_api`` / 零直发方法调用；
2. divination 域同上；
3. delivery 出站协议切片只消费 ``submit``（无第二出站面）；
4. 解释端口 ``not_wired`` 常量与 REST 端点诚实位 tripwire。

行为面断言由既有套件承担、此处不重复：tests/test_v21_s11_delivery.py（17 例，
含 not_authorized 干跑/装配工厂干跑）、tests/test_reminder_delivery.py、
tests/test_v21_s12_divination_api.py（27 例，含 interpretation 503 not_wired）。

全离线：零网络、零 NoneBot 启动、零真实发送；AST 静态扫描不 import 插件包。
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "bot_unified_runtime"

# 直发出站方法名集合（口径=domains/core/decision/outbound_registry.py DirectSendEntry）。
_DIRECT_SEND_METHODS = frozenset(
    {
        "send_private_msg",
        "send_group_msg",
        "upload_group_file",
        "upload_private_file",
        "group_poke",
        "friend_poke",
        "set_msg_emoji_like",
        "set_message_reaction",
        "delete_msg",
    }
)


def _domain_files(*relative_parts: str) -> list[Path]:
    return sorted((_PLUGIN_ROOT.joinpath(*relative_parts)).rglob("*.py"))


def _direct_outbound_violations(paths: list[Path]) -> list[str]:
    """AST 扫描：直连 bot 传输面（call_api/直发方法）即为违例。

    两域的合法出站形态只有两种——CapabilityResult 交回管线、queue.submit 交
    SendQueue；任何 ``bot.call_api(...)`` / ``bot.send_group_msg(...)`` 形态
    都意味着绕开统一出站路径。
    """
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            relative = path.relative_to(_REPO_ROOT)
            if func.attr == "call_api":
                violations.append(
                    f"{relative.as_posix()}:{node.lineno} call_api(...) 直连传输面"
                )
            elif func.attr in _DIRECT_SEND_METHODS:
                violations.append(
                    f"{relative.as_posix()}:{node.lineno} .{func.attr}(...) 直发出站"
                )
    return violations


def test_schedule_domain_has_no_direct_outbound_calls() -> None:
    """L56/L57/L58：schedule 域零直连出站（装配波收编时必须保持走统一路径）。"""
    violations = _direct_outbound_violations(_domain_files("domains", "schedule"))
    assert not violations, (
        "domains/schedule 出现直连出站（必须走 SendQueue.submit 统一路径）："
        + "; ".join(violations)
    )


def test_divination_domain_has_no_direct_outbound_calls() -> None:
    """L65：divination 域零直连出站（卡片/文本一律交回 CapabilityResult 管线）。"""
    violations = _direct_outbound_violations(_domain_files("domains", "divination"))
    assert not violations, (
        "domains/divination 出现直连出站（必须走 CapabilityResult→pipeline 统一路径）："
        + "; ".join(violations)
    )


def test_schedule_delivery_outbound_face_is_queue_submit_only() -> None:
    """L58：delivery 的出站协议切片只消费 ``submit``——不存在第二出站面。"""
    delivery_path = _PLUGIN_ROOT / "domains" / "schedule" / "delivery.py"
    tree = ast.parse(delivery_path.read_text(encoding="utf-8"))
    protocol_methods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_QueueProtocol":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    protocol_methods.add(item.name)
    assert protocol_methods == {"submit"}, (
        f"_QueueProtocol 必须只消费 submit（现={sorted(protocol_methods)}）；"
        "扩出站面=绕开统一路径，需先过 DELIVERY-001 裁决"
    )


def _module_level_string_constant(path: Path, constant_name: str) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == constant_name
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    return None


def test_tarot_interpretation_port_stays_honest_not_wired() -> None:
    """L65：解释端口 ``not_wired`` 诚实位 tripwire（未获授权不得静默实装真实 LLM）。"""
    errors_path = _PLUGIN_ROOT / "domains" / "divination" / "api" / "errors.py"
    assert (
        _module_level_string_constant(errors_path, "INTERPRETATION_NOT_WIRED_CODE")
        == "not_wired"
    ), "INTERPRETATION_NOT_WIRED_CODE 语义被改动——解释端口处置需重新过验收矩阵 L65"
    endpoint_path = _PLUGIN_ROOT / "control_plane" / "api" / "divination.py"
    endpoint_tree = ast.parse(endpoint_path.read_text(encoding="utf-8"))
    referenced_names = {
        node.id for node in ast.walk(endpoint_tree) if isinstance(node, ast.Name)
    }
    imported_names: set[str] = set()
    for node in ast.walk(endpoint_tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
    assert "InterpretationNotWiredError" in (referenced_names | imported_names), (
        "解释端点的 503 not_wired 诚实位被移除/替换；"
        "若已获用户授权实装真实 LLM 解释，须同步更新本 tripwire 与矩阵 L65（禁静默替换）"
    )
