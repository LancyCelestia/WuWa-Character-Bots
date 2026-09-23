"""PX-1 保险腿的回归锁：MCP stdio 服务端 `-m 目标` 模块在册且在位。

被锁住的机制（`scripts/pre_restart_check.py::check_mcp_server_spec`）：
`.env` 的 `MCP_SERVERS`（由 nonebot_plugin_mcpclient 直读、不经 Config）里，
某条 `type=="stdio"` 服务端以 `python -m <module>` 起、而 `<module>` 已从 tree 消失时，
重启前体检必须 FAIL 并点名仓内同名真身。缺 `command` 也 FAIL。
读不到 `.env` / JSON 坏 / 空对象 = 诚实 SKIP（不假绿、也不假红）。
输出绝不回显 command / env / 任何密钥值。

注毒一律进程内 monkeypatch，禁编辑磁盘文件注毒。
"""

import json
from pathlib import Path

from scripts import pre_restart_check as prc

# 一个「本仓根本不存在」的模块名（顶层包 nosuchmcp 哪都找不到 ⇒ find_spec 必判死），
# 它的末段 legacy_server 与下面 tmp 包里造的同名真身对齐，用来验「点真身」这条分支。
DEAD = "nosuchmcp.demo.sources.legacy_server"
HOME = "plugins.demo.domains.legacy_server"


def _make_home_pkg(root: Path) -> None:
    """在 root 下造一条规范包路径 plugins/demo/domains/legacy_server.py（父链均有 __init__.py）。"""
    for pkg in ("plugins", "plugins/demo", "plugins/demo/domains"):
        d = root / pkg
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").write_text("", encoding="utf-8")
    (root / "plugins" / "demo" / "domains" / "legacy_server.py").write_text("", encoding="utf-8")


def _stdio_env(module: str, **extra: object) -> dict[str, str]:
    entry: dict[str, object] = {"type": "stdio", "command": "python", "args": ["-m", module]}
    entry.update(extra)
    return {"MCP_SERVERS": json.dumps({"srv": entry})}


# ---------------------------------------------------------------------------
# 核心五锁 (a)–(e)
# ---------------------------------------------------------------------------

def test_a_dead_module_fails_and_names_the_home(tmp_path: Path) -> None:
    """(a) 死模块 ⇒ FAIL，且点名仓内同名真身与修法。"""
    _make_home_pkg(tmp_path)
    result = prc.check_mcp_server_spec(_stdio_env(DEAD), tmp_path)
    assert result.status == prc.FAIL
    assert DEAD in result.message
    assert HOME in result.message
    assert result.fix_hint


def test_b_live_module_passes(tmp_path: Path) -> None:
    """(b) -m 目标可解析 ⇒ PASS。"""
    result = prc.check_mcp_server_spec(_stdio_env("json"), tmp_path)
    assert result.status == prc.PASS


def test_c_garbage_json_skips_honestly(tmp_path: Path) -> None:
    """(c) JSON 垃圾 ⇒ 诚实 SKIP（不假绿，也不硬判红）。"""
    assert prc.check_mcp_server_spec({"MCP_SERVERS": "{not-json"}, tmp_path).status == prc.SKIP


def test_c_missing_env_or_empty_skips(tmp_path: Path) -> None:
    """(c 续) 键不在（读不到 .env）/ 空对象 ⇒ SKIP。"""
    assert prc.check_mcp_server_spec({}, tmp_path).status == prc.SKIP
    assert prc.check_mcp_server_spec({"MCP_SERVERS": ""}, tmp_path).status == prc.SKIP
    assert prc.check_mcp_server_spec({"MCP_SERVERS": "{}"}, tmp_path).status == prc.SKIP


def test_d_message_never_carries_a_secret_value(tmp_path: Path) -> None:
    """(d) 值里含凭据形态 ⇒ 输出只报键名/模块名，绝不说出任何值里的密钥。

    对齐 tests/test_tag_presence_gate.py::test_check_message_never_carries_a_secret_value。
    这里把同一个 secret 塞进 command / env / url / headers 四个字段——体检一个都不该回显。
    """
    _make_home_pkg(tmp_path)
    secret = "sk-deadbeefabc123token"
    env = {
        "MCP_SERVERS": json.dumps(
            {
                "srv": {
                    "type": "stdio",
                    "command": secret,
                    "args": ["-m", DEAD],
                    "env": {"API_KEY": secret},
                    "url": secret,
                    "headers": {"Authorization": secret},
                }
            }
        )
    }
    result = prc.check_mcp_server_spec(env, tmp_path)
    assert result.status == prc.FAIL
    assert secret not in result.message + result.fix_hint


def test_e_missing_command_fails(tmp_path: Path) -> None:
    """(e) type=stdio 缺 command ⇒ FAIL（client.py:76 运行期才炸，提前挑出）。"""
    env = {"MCP_SERVERS": json.dumps({"srv": {"type": "stdio", "args": ["-m", "json"]}})}
    result = prc.check_mcp_server_spec(env, tmp_path)
    assert result.status == prc.FAIL
    assert "缺 command" in result.message


# ---------------------------------------------------------------------------
# 注毒自证（进程内 monkeypatch）——证明上面几条锁各有牙齿、不是白捡
# ---------------------------------------------------------------------------

def test_poison_availability_always_true_flips_dead_to_pass(tmp_path: Path, monkeypatch) -> None:
    """毒①：把可解析判定恒真 ⇒ 死模块那条 FAIL 必须翻成 PASS。

    证明 (a) 的红真由 find_spec 判死驱动，而非别的原因误报。
    """
    _make_home_pkg(tmp_path)
    monkeypatch.setattr(prc, "_module_available", lambda module, project_root: True)
    assert prc.check_mcp_server_spec(_stdio_env(DEAD), tmp_path).status == prc.PASS


def test_poison_no_home_removes_the_suggestion(tmp_path: Path, monkeypatch) -> None:
    """毒②：让「找真身」恒返 None ⇒ 仍 FAIL、仍点死模块名，但不得再出现真身建议。

    证明「点真身建议」是一条真实分支，不是文案里白捡的字串。
    """
    _make_home_pkg(tmp_path)
    monkeypatch.setattr(prc, "_find_module_home", lambda module, project_root: None)
    result = prc.check_mcp_server_spec(_stdio_env(DEAD), tmp_path)
    assert result.status == prc.FAIL
    assert DEAD in result.message
    assert HOME not in result.message


def test_poison_no_dash_m_extraction_flips_dead_to_pass(tmp_path: Path, monkeypatch) -> None:
    """毒③：让 `-m <module>` 提取恒 None ⇒ 无从判定 ⇒ 该条被跳过、整体 PASS。

    证明「从 args 里提取 -m 目标」这一步在承重。
    """
    _make_home_pkg(tmp_path)
    monkeypatch.setattr(prc, "_stdio_module_from_args", lambda args: None)
    assert prc.check_mcp_server_spec(_stdio_env(DEAD), tmp_path).status == prc.PASS
