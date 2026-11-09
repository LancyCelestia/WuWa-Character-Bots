"""bot.py 驱动监听端口可绑定性（2026-10-17 崩溃熔断根修）。

生产事故（supervisor.log）：600s 内连续崩溃 5 次、退出码恒为 **3**。
根因链已实测坐实——

1. NoneBot fastapi 驱动的监听地址取**驱动自身 Config** 的 ``host``/``port``
   （``nonebot/drivers/fastapi.py:189-190``），两者缺省 = ``127.0.0.1:8080``；
2. 本机 8080 处于 Windows 保留态、**无人监听却拒绝绑定**：
   ``bind(("127.0.0.1", 8080))`` → ``OSError errno=13 winerror=10013``
   （同一时刻 8742/3014/8081 均 BIND OK）；
3. uvicorn ``server.py:180-183`` 捕到该 OSError 后 ``sys.exit(STARTUP_FAILURE)``，
   而 ``uvicorn/config.py:80`` 的 ``STARTUP_FAILURE`` **就是 3** ⇒ 整进程退 3；
4. supervisor 把非零退出当崩溃 → 退避重拉 → 熔断停拉（QQ 随之「登录失败」）。

修法（用户 2026-10-17 裁 A）：驱动监听端口不再吃缺省 8080，启动前显式钉住，
并在绑不上时给出可执行的人话告警（而不是让 uvicorn 静默退 3）。

覆盖：
① 端口钉在 ``nonebot.init`` **之前**（驱动 Config 在那时读环境变量）；
② 端口确实可绑——用 8080 的实测不可绑性做**反向对照**，防「换了个同样绑不上的口」；
③ 绑不上时诊断消息点名端口与修法；能绑时返回 None（不影响启动）。
"""

from __future__ import annotations

import ast
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOT_PATH = PROJECT_ROOT / "bot.py"
_HELPERS = (
    "_webhook_endpoint",
    "_webhook_bind_error",
    "_dotenv_declares",
    "_dotenv_declares_keys",
)
_CONSTS = ("_DEFAULT_WEBHOOK_PORT", "_DEFAULT_WEBHOOK_HOST")
_RESERVED_PORT = 8080  # 本机实测：无人监听但 bind 报 winerror 10013


def _load_bot_namespace() -> dict:
    """AST 摘取 bot.py 顶层 import + 端口常量 + 两个端口助手 → 独立命名空间。

    不能 ``import bot``：模块级会执行 nonebot.init + 全插件加载（重、带生产
    副作用）。与 ``tests/test_bot_supervisor.py`` 同一套摘取手法；助手依赖的
    模块级常量必须一并摘出，否则 Namespace 里会 NameError（这层依赖关系
    本身也是结构约束）。
    """
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"), filename=str(BOT_PATH))
    body = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        or (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in _HELPERS
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in _CONSTS
                for target in node.targets
            )
        )
    ]
    found = {n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert found == set(_HELPERS), f"bot.py 端口助手缺失/改名: {found}"
    namespace: dict = {"__file__": str(BOT_PATH), "__name__": "bot_webhook_port_under_test"}
    # exec 仅用于摘取本仓库自有源码的函数定义（入口脚本模块级有 nonebot.init
    # 副作用，不能正常 import），非外部输入。
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BOT_PATH), "exec"), namespace)  # noqa: S102
    missing = [name for name in _CONSTS if name not in namespace]
    assert not missing, f"bot.py 端口常量缺失/改名: {missing}"
    return namespace


def _bindable(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


# ---------------------------------------------------------------------------
# ① 端口钉在 nonebot.init 之前
# ---------------------------------------------------------------------------
def test_driver_port_is_pinned_before_nonebot_init() -> None:
    source = BOT_PATH.read_text(encoding="utf-8")
    pin = 'os.environ.setdefault("PORT",'
    assert pin in source, "驱动监听端口没有被显式钉住（缺 os.environ.setdefault(\"PORT\", ...)）"
    assert source.index(pin) < source.index("nonebot.init("), (
        "端口钉设必须在 nonebot.init 之前——驱动 Config 在那一步就读走环境变量"
    )


# ---------------------------------------------------------------------------
# ② 钉住的端口真的可绑 + 反向对照（8080 不可绑是本机事实）
# ---------------------------------------------------------------------------
def test_pinned_port_is_not_the_reserved_8080() -> None:
    namespace = _load_bot_namespace()
    _, port = namespace["_webhook_endpoint"](SimpleNamespace())
    assert port != _RESERVED_PORT, "仍指向本机保留态端口 8080（bind 必报 winerror 10013）"
    assert _bindable(port), f"钉住的端口 {port} 在本机同样绑不上"


def test_dotenv_port_declaration_wins_over_the_pin() -> None:
    """`.env` 声明了 PORT ⇒ 不许再钉缺省（否则那条声明永远读不到）。

    NoneBot 的优先级是「进程环境 ＞ dotenv」（``nonebot/config.py:188-190``），
    所以 ``os.environ.setdefault("PORT", ...)`` 会把 `.env` 的 PORT 永久盖掉——
    这曾让诊断里「在 .env 里设 PORT」这句改法恒不生效（2026-10-17 复核 P1）。

    纯解析腿 + 真文件腿：本沙箱不允许 chdir/写临时目录（WinError 5），
    故不去造临时 dotenv，直接拿仓库现成的 `.env` 当正腿（它确有 BOT_ 键、无 PORT）。
    """
    namespace = _load_bot_namespace()
    declares_keys = namespace["_dotenv_declares_keys"]
    declares = namespace["_dotenv_declares"]
    keys = frozenset({"PORT", "HOST"})

    assert declares_keys("BOT_X=1\nPORT=8123\n", keys) is True
    assert declares_keys("PORT=8123\n", frozenset({"HOST"})) is False
    assert declares_keys("# PORT=8123 注释不算\n", keys) is False
    assert declares_keys("export PORT=8123\n", keys) is True
    assert declares_keys("PORTABLE=1\n", keys) is False, "前缀相同的别的键不算"

    # 真文件腿：仓库 .env 里没有 PORT/HOST 声明（⇒ 缺省钉设生效），
    # 但它确实声明了别的键（⇒ 读文件这条路真的通）。
    assert declares("PORT", "HOST") is False
    assert declares("BOT_RUNTIME_DATA_DIR") is True


def test_pinned_port_constant_is_the_same_everywhere() -> None:
    """三处 8099 必须同值——常量漂移会让判活/撞口判据静默失灵。

    本波刚修掉的病就是「拿一枚错端口当判据」；若只改 bot.py 的常量而
    lifecycle / dev.ps1 / 探针不同步，同样的病会以另一枚数字复发。
    """
    namespace = _load_bot_namespace()
    expected = namespace["_DEFAULT_WEBHOOK_PORT"]
    src = BOT_PATH.read_text(encoding="utf-8")
    assert f"_DEFAULT_WEBHOOK_PORT = {expected}" in src

    lifecycle_src = (PROJECT_ROOT / "plugins/bot_unified_runtime/control_plane/lifecycle.py").read_text(
        encoding="utf-8"
    )
    assert f"_DEFAULT_WEBHOOK_PORT = {expected}" in lifecycle_src, "lifecycle 的缺省口没跟 bot.py 同步"

    dev_src = (PROJECT_ROOT / "scripts/dev.ps1").read_text(encoding="utf-8")
    assert f"$port = {expected}" in dev_src, "dev.ps1 的判活口没跟 bot.py 同步"

    probe_src = (PROJECT_ROOT / "scripts/media_capability_probe.py").read_text(encoding="utf-8")
    assert f"or {expected}" in probe_src, "媒体探针的判活口没跟 bot.py 同步"


# ---------------------------------------------------------------------------
# ③ 绑不上 → 人话诊断；能绑 → None
# ---------------------------------------------------------------------------
def test_bind_error_names_port_on_real_busy_port() -> None:
    """真占住一个口再探：诊断必须点名该端口（走真实 socket，不打桩）。"""
    namespace = _load_bot_namespace()
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    busy_port = holder.getsockname()[1]
    try:
        message = namespace["_webhook_bind_error"](
            SimpleNamespace(host="127.0.0.1", port=busy_port)
        )
    finally:
        holder.close()
    assert message is not None, "占用中的端口必须被预检判为绑不上"
    assert str(busy_port) in message, "诊断消息必须点名端口"
    assert "PORT" in message, "诊断消息必须给出改法（PORT 环境变量）"


def test_internal_probe_failure_is_reported_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """预检自身炸了也必须说话：fail-open ≠ fail-silent。

    历史事故：助手用了模块级没导入的名字 ⇒ NameError 被兜底吞掉 ⇒ 预检恒返回
    None（看着有牙、其实恒通过）。本腿把 socket 构造打桩成炸，断言仍返回诊断。
    """
    namespace = _load_bot_namespace()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(namespace["socket"], "socket", _boom)
    message = namespace["_webhook_bind_error"](SimpleNamespace(host="127.0.0.1", port=8099))
    assert message is not None, "预检自身出错被静默吞掉（fail-silent）"
    assert "不阻断启动" in message


def test_bind_error_returns_none_for_free_port() -> None:
    namespace = _load_bot_namespace()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    assert namespace["_webhook_bind_error"](
        SimpleNamespace(host="127.0.0.1", port=free_port)
    ) is None
