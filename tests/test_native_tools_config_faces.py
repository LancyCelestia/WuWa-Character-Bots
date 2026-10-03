"""`bot_chat_native_tools_enabled` 的多面同生静态锁（S3 席，2026-10-02）。

为什么再立一把（台账 #68★ 的正面）：这枚键经历过一次「幽灵字段」——判定口
``domains/core/search/native_tools.py`` 早在册，``config.py`` 却没字段，于是
`.env` 写什么都不生效（`extra="ignore"` 静默吞）。09-29 复原波补上了字段，
但**没有任何一把门盯着「四面是否还在」**：补一面红另一面的同型病会原地重犯。
本件只判这一件事，且**全部走既有真身取数口**（字段 AST／pilot 热改档／catalog 键名归一），
不抄第二份名单。

零 import 插件包：config.py 与 settings.py 一律 AST/文本静态读，离线、不读生产 `.env`。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
for _p in (str(ROOT), str(TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

# 目录键名归一口复用既有门的尺（禁第二真身：`_chat_native_tools_enabled` 这种
# 「省略 BOT_ 前缀」的写法只有它那把尺认得）。
from test_doc_sync_gates import _catalog_registered_keys

from scripts.config_catalog_generator_pilot import load_hot_tiers

KEY = "bot_chat_native_tools_enabled"
ENV_NAME = "BOT_CHAT_NATIVE_TOOLS_ENABLED"
CONFIG_PY = ROOT / "plugins/bot_unified_runtime/config.py"
SETTINGS_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py"
)
ENV_EXAMPLE = ROOT / ".env.example"
CATALOG_MD = ROOT / "docs/config-catalog-full.md"
NATIVE_TOOLS_PY = (
    ROOT / "plugins/bot_unified_runtime/domains/core/search/native_tools.py"
)
PRODUCTION_ROOTS = ("plugins", "scripts")
PRODUCTION_ENTRY = ROOT / "bot.py"


def _annotated_field_default(path: Path, name: str) -> ast.expr | None:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id == name:
            return node.value
    return None


def _string_constants(source: str) -> list[ast.Constant]:
    tree = ast.parse(source)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _production_files() -> list[Path]:
    files: list[Path] = []
    for base in PRODUCTION_ROOTS:
        files.extend((ROOT / base).rglob("*.py"))
    if PRODUCTION_ENTRY.is_file():
        files.append(PRODUCTION_ENTRY)
    return [
        path
        for path in files
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


# ---------------------------------------------------------------------------
# 四面逐面点名（缺一面即红＝#68★ 的「只补一面必红另一面」反向利用）
# ---------------------------------------------------------------------------


def test_face_one_config_field_exists_and_defaults_off() -> None:
    default = _annotated_field_default(CONFIG_PY, KEY)
    assert default is not None, f"{KEY} 不在 config.py ⇒ .env 写了也被 extra='ignore' 吃掉"
    assert isinstance(default, ast.Constant) and default.value is False, (
        "缺省必须逐字 False（开＝行为变化，缺省开就是把未接线的工具面白发给模型）"
    )


def test_face_two_settings_hot_change_declaration() -> None:
    tiers = load_hot_tiers(SETTINGS_PY.read_text(encoding="utf-8"))
    lowered = {key.lower(): value for key, value in tiers.items()}
    assert KEY in lowered, (
        f"{KEY} 既不在 SETTABLE_KEYS 也不在 RESTART_REQUIRED_KEYS ⇒ "
        "对热改面「无表态」，管理员照名单改会静默无效"
    )
    # 读点是装配期快照（chat 侧构建期取用）⇒ 唯一合法档是「需重启」，不是「可热更」。
    assert lowered[KEY] == "restart", (
        f"当前档={lowered[KEY]}：读的是调用方交来的快照 config，写成可热更＝骗人（审查 C-09）"
    )


def test_face_three_env_example_has_active_line() -> None:
    active = {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
    }
    assert ENV_NAME in active, (
        f".env.example 缺 **激活行** `{ENV_NAME}=…`（注释形态不算，ISYNC 门的同一口径）"
    )
    # 🔑 铁律 3：本文件不许出现真实 key——这枚是 bool 开关，值只能是 true/false/空。
    value = re.search(rf"^{ENV_NAME}=(.*)$", ENV_EXAMPLE.read_text(encoding="utf-8"), re.MULTILINE)
    assert value and value.group(1).strip() in {"", "true", "false", "0", "1"}, (
        f"{ENV_NAME} 的示例值不是布尔形态：{value.group(1) if value else None!r}"
    )


def test_face_four_catalog_row_exists() -> None:
    registered = _catalog_registered_keys(CATALOG_MD.read_text(encoding="utf-8"))
    assert KEY in registered, f"{KEY} 未登记进 docs/config-catalog-full.md"


# ---------------------------------------------------------------------------
# 单一读取口 + 消毒口
# ---------------------------------------------------------------------------


#: 允许以**字面量**碰过这枚键的生产件（各带理由，多一枚就是第二真身）：
#: · native_tools.py ＝ 唯一读取口（``getattr(config, NATIVE_TOOLS_CONFIG_KEY, None)``）；
#: · settings.py ＝ 热改台账行（``RESTART_REQUIRED_KEYS`` 的登记，不是取值）。
EXPECTED_KEY_HOLDERS: dict[str, str] = {
    "plugins/bot_unified_runtime/domains/core/search/native_tools.py": "唯一读取口",
    "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py": "热改名单登记面",
}


def test_key_has_exactly_one_read_point_outside_config() -> None:
    """键名字面只许住在上面那两枚在册件里（第三处＝第二个开关真身，当场红）。"""
    holders: list[str] = []
    for path in _production_files():
        if path == CONFIG_PY:
            continue  # config.py 自家的字段声明与注释不算读点
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        if any(node.value == KEY for node in _string_constants(source)):
            holders.append(path.relative_to(ROOT).as_posix())
        if f'"{ENV_NAME}"' in source or f"'{ENV_NAME}'" in source:
            holders.append(path.relative_to(ROOT).as_posix())
    extra = sorted(set(holders) - set(EXPECTED_KEY_HOLDERS))
    missing = sorted(set(EXPECTED_KEY_HOLDERS) - set(holders))
    assert not extra, f"这枚键长出了第二读取面（登记面见 EXPECTED_KEY_HOLDERS 的理由）：{extra}"
    assert not missing, f"在册读取/登记面不见了（键被改名或读取口被摘）：{missing}"


def test_no_attribute_style_read_of_the_key() -> None:
    """属性式 ``config.bot_chat_native_tools_enabled`` 一律不许出现（第二取值形状）。"""
    offenders: list[str] = []
    for path in _production_files():
        if path == CONFIG_PY:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == KEY:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not offenders, f"绕过唯一读取口的属性式取值：{offenders}"


def test_enabled_reader_only_accepts_strict_true() -> None:
    """fail-closed 形状锁：只认 ``is True``，字符串 "true"/1 都不算开。"""
    source = NATIVE_TOOLS_PY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    reader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "native_tools_enabled"
    )
    checks = [node for node in ast.walk(reader) if isinstance(node, ast.Compare)]
    assert any(
        len(node.ops) == 1 and isinstance(node.ops[0], ast.Is) for node in checks
    ), "native_tools_enabled 不再用 `is True` ⇒ 宽容真值面回来了"


@pytest.mark.parametrize(
    ("source", "must_be_named"),
    [
        (
            (
                "def guard_tool_result_text(text, *, tool_name):\n"
                "    from x import guard_secondhand_text\n"
                "    return guard_secondhand_text(text, source_label=f'内置工具 {tool_name} 结果')\n"
            ),
            False,
        ),
        (
            (
                "def guard_tool_result_text(text, *, tool_name):\n"
                "    return '【工具结果开始】\\n' + text + '\\n【工具结果结束】'\n"
            ),
            True,
        ),
    ],
    ids=["central-guard", "hand-rolled-tags"],
)
def test_tool_result_guard_rule_is_enforceable(source: str, must_be_named: bool) -> None:
    """消毒判据本体（喂合成源码测牙口，不碰真件）：手拼边界标签必须被点名。"""

    def violations(code: str) -> list[str]:
        problems: list[str] = []
        tree = ast.parse(code)
        function = next(
            (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)), None
        )
        if function is None:
            return ["找不到工具结果处置函数"]
        calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if "guard_secondhand_text" not in calls:
            problems.append("未走中央处置件 guard_secondhand_text（禁手拼边界标签）")
        for node in ast.walk(function):
            if isinstance(node, ast.JoinedStr) and any(
                isinstance(part, ast.Constant)
                and isinstance(part.value, str)
                and ("【" in part.value or "】" in part.value)
                for part in node.values
            ):
                problems.append(f"第 {node.lineno} 行自拼边界标签")
        return problems

    found = violations(source)
    assert bool(found) is must_be_named, f"{source!r} 判成 {found}"


def test_real_guard_delegates_to_central_injection_module() -> None:
    """真件自查：`guard_tool_result_text` 必须延迟 import 中央件（不另起一套边界标签）。"""
    source = NATIVE_TOOLS_PY.read_text(encoding="utf-8")
    assert "guard_secondhand_text" in source, "消毒口不见了"
    assert "injection" in source, "中央处置件出处（security/injection）不在读取路径里"
    # 边界标签原文（【…】）绝不许出现在本件源码里——它只住中央件。
    assert "【" not in source, "native_tools 自拼了边界标签 ⇒ 长出第二份处置真身"
