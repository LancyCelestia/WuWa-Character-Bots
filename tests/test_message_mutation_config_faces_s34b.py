"""席 S34b（2026-10-04 开面批）：消息编辑/撤回两枚键的「三面齐 + 直读无容缺省」锁。

为什么再立一把（台账 #68★ 幽灵字段）：``bot_message_mutation_*`` 两枚键在 S34 那席是
**故意不进三面**的（读点用 ``getattr(config, ..., False)`` 容缺省），因为新增可改面要走
裁定。用户 2026-10-04 点头开面后，字段进了 ``config.py``：此时若读点仍留 ``getattr`` 缺省
容错，就等于「字段在册」与「字段缺席」两套口径并存——改缺省值不会有人发现。本件钉死：

1. **三面齐**：``config.py`` 字段 / ``runtime/settings.py`` 热改名单 / ``.env.example``
   激活键行，三面逐枚都在，且**默认关**（``False`` / ``120``）。
2. **热改档位唯一表态**：两枚键进 ``RESTART_REQUIRED_KEYS``（读点在装配期快照闭包里，
   未进 ``_RUNTIME_HOT_OVERRIDE_FIELDS`` ⇒ 登记 SETTABLE 就是 C-09 反的那类死开关）。
3. **只有一处读法**：生产源件里不再出现以这两枚键名为字面量的 ``getattr``。

全离线、零网络、零平台调用；不 import 插件包根（避免装配副作用）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"
SETTINGS_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py"
)
MUTATION_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/transport/message_mutation.py"
)
ENV_EXAMPLE = ROOT / ".env.example"

NEW_KEYS = (
    "bot_message_mutation_enabled",
    "bot_message_mutation_window_seconds",
)
NEW_ENV_KEYS = tuple(name.upper() for name in NEW_KEYS)


def _config_field_defaults() -> dict[str, ast.expr]:
    """``Config`` 类体里的 ``bot_*`` 字段 → 缺省表达式（AST 现算，不 import 包）。"""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    out: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Config":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            if stmt.value is not None:
                out[stmt.target.id] = stmt.value
    return out


def test_two_fields_registered_with_closed_defaults() -> None:
    """面①：两枚字段在册，且缺省=关面（``False`` / ``120``）＝行为零变化。"""
    defaults = _config_field_defaults()
    enabled = defaults.get(NEW_KEYS[0])
    window = defaults.get(NEW_KEYS[1])
    assert isinstance(enabled, ast.Constant) and enabled.value is False, (
        f"{NEW_KEYS[0]} 缺省必须是 False（关面），现算 {getattr(enabled, 'value', enabled)!r}"
    )
    assert isinstance(window, ast.Constant) and window.value == 120, (
        f"{NEW_KEYS[1]} 缺省必须是 120，现算 {getattr(window, 'value', window)!r}"
    )


def test_hot_surface_face_registered_once_in_restart_list() -> None:
    """面②：热改态登记在 RESTART_REQUIRED_KEYS，且**不**在 SETTABLE_KEYS（两面各一次表态）。"""
    text = SETTINGS_PY.read_text(encoding="utf-8")
    restart = text.split("RESTART_REQUIRED_KEYS: dict[str, str] = {", 1)[1]
    restart = restart.split("\n}\n", 1)[0]
    settable_marker = "SETTABLE_KEYS: dict[str, Callable[[str], Any]] = {"
    settable = text.split(settable_marker, 1)[1].split("\n}", 1)[0]
    for env_key in NEW_ENV_KEYS:
        assert f'"{env_key}"' in restart, f"{env_key} 未登记 RESTART_REQUIRED_KEYS＝幽灵字段面②缺席"
        assert f'"{env_key}"' not in settable, (
            f"{env_key} 同时进了 SETTABLE_KEYS：读点在装配期快照闭包、合并层未登记 ⇒"
            " set 写了不生效＝C-09 死开关，两表不得同时表态"
        )


def test_env_example_declares_active_lines() -> None:
    """面③：``.env.example`` 有**激活**键行（``KEY=``，注释形态不算，同 env_example_gate 尺）。"""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    active = {
        line.split("=", 1)[0].strip()
        for line in lines
        if "=" in line and not line.lstrip().startswith("#")
    }
    for env_key in NEW_ENV_KEYS:
        assert env_key in active, f"{env_key} 在 .env.example 缺激活键行（注释不算）"


def test_production_read_point_is_direct_field_access() -> None:
    """单一口径：读点属性式直取在册字段；全树生产源件不得再以键名字面量走 getattr。"""
    source = MUTATION_PY.read_text(encoding="utf-8")
    assert "config.bot_message_mutation_enabled" in source
    assert "config.bot_message_mutation_window_seconds" in source
    for name in NEW_KEYS:
        assert not re.search(rf"getattr\(\s*\w+\s*,\s*[\"']{name}[\"']\s*,", source), (
            f"{name} 又长出 getattr 容缺省的读法＝在册字段之外的第二套口径"
        )
    init_text = (ROOT / "plugins/bot_unified_runtime/__init__.py").read_text(encoding="utf-8")
    for name in NEW_KEYS:
        assert f'"{name}"' not in init_text, "根装配文件不该另养一枚按名读法（第二真身）"


def test_default_off_means_gate_denies_admin() -> None:
    """缺省面的行为判据：字段=False 时管理员也被拒且零出站（开面与否由配置，不由代码）。"""
    import asyncio

    from plugins.bot_unified_runtime.config import Config
    from plugins.bot_unified_runtime.domains.transport import message_mutation as mm

    assert Config().bot_message_mutation_enabled is False
    assert Config().bot_message_mutation_window_seconds == 120

    class RecordingBot:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def call_api(self, api: str, params: dict[str, object]) -> object:
            self.calls.append((api, params))
            return {}

    class Receipt:
        provider_message_id = "4242"
        created_at = "2026-10-04T00:00:00+00:00"

    class Ledger:
        def list_receipts(self) -> list[object]:
            return [Receipt()]

    bot = RecordingBot()
    request = mm.MutationRequest(
        operation=mm.OPERATION_DELETE,
        actor=mm.MutationActor(
            platform="qq", sender_id="1", chat_id="777", is_admin=True
        ),
        target=mm.MutationTarget(
            platform="qq", session_type="group", chat_id="777", message_id="4242"
        ),
    )
    outcome = asyncio.run(
        mm.execute_mutation(request, config=Config(), bot=bot, ledger=Ledger())
    )
    assert (outcome.ok, outcome.status, outcome.reason) == (
        False,
        "refused",
        "feature_disabled",
    ), "默认关必须整门拒（开面是用户的动作，不是代码的缺省）"
    assert bot.calls == []


def test_poison_missing_env_example_line_is_named(tmp_path: Path) -> None:
    """注毒自证：抹掉面③的一行，本件的判据必须变红（防「集合恒真」的空转门）。"""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    poisoned = "\n".join(
        line for line in text.splitlines() if not line.startswith(f"{NEW_ENV_KEYS[0]}=")
    )
    probe = tmp_path / ".env.example"
    probe.write_text(poisoned, encoding="utf-8")
    active = {
        line.split("=", 1)[0].strip()
        for line in probe.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    assert NEW_ENV_KEYS[0] not in active, "注毒失败：删掉键行后仍判成在册 ⇒ 尺写瞎了"
