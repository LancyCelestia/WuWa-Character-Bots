"""DATAFIX 回归（2026-09-12）：运行时数据路径永落 Runtime 根，绝不写源码树。

背景：源码树 data/ 曾泄漏三个文件——platform_cookies.txt、reflection.sqlite3、
usage_report_state.json。根因是三类入口绕过 BOT_RUNTIME_DATA_DIR 重映射：

1. config 校验器 path_fields 遗漏 bot_usage_report_state_file（默认值保持
   CWD 相对路径，usage_monitor 按 CWD 解析落盘）；
2. cookies._resolve_relative_cookie_path 只读进程 env 不读 dotenv，
   dotenv-only 入口回退 project_root/data（platform_credentials 写入即泄漏）；
3. 消费点 getattr 兜底默认值（reflection/music/epic/steam）是纯相对路径。

本文件在「env 设置」与「env 未设置（dotenv 亦空）」两种环境下断言解析结果，
锁定源码树 data/ 不再成为解析目标。

下半部分（2026-09-29 追加，P0）：**测试进程的 Runtime 根隔离**——同一枚解析器
的另一侧事故：`.env` 把 `BOT_RUNTIME_DATA_DIR` 指向**生产**根，conftest 只守源码树
`data/`，于是装配腿里没传隔离根的构造点会在测试进程里直接打开生产的
`reply_policy.sqlite3`。判据一律量**解析结果**、不量夹具写法（写法可以被
`**llm_options` 静默吞掉，见本文件 C 组）。
"""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import runtime_paths
from scripts.runtime_paths import runtime_data_dir, runtime_path

# 三个曾泄漏到源码树的文件（data/ 相对默认值）。
LEAKED_RELATIVE_PATHS = (
    "data/platform_cookies.txt",
    "data/reflection.sqlite3",
    "data/usage_report_state.json",
)

# config 校验器必须覆盖的字段（含 DATAFIX 前遗漏的）。
RESOLVED_CONFIG_FIELDS = (
    "bot_control_plane_config_db",
    "bot_control_plane_events_db",
    "bot_control_plane_features_db",
    "bot_usage_report_state_file",
    "bot_media_registry_path",
    "bot_music_dir",
    "bot_mood_db_path",
    "bot_quirks_db_path",
    "bot_session_identity_db_path",
    "bot_reminder_db_path",
    "bot_affinity_db_path",
    "bot_reflection_db_path",
    "bot_cookies_file",
)


def _isolate_dotenv(monkeypatch: pytest.MonkeyPatch, value: str = "") -> None:
    """env 未设置场景下屏蔽真实 .env，令数据根解析完全确定。"""
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    monkeypatch.setattr(runtime_paths, "_dotenv_value", lambda key: value)


def test_runtime_path_env_set_remaps_leaked_defaults(tmp_path: Path, monkeypatch) -> None:
    """env 设置时：data/ 相对值必须重映射进 env 指定的数据根。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    for raw in LEAKED_RELATIVE_PATHS:
        resolved = runtime_path(raw)
        assert resolved == (tmp_path / Path(raw).name).resolve()
        assert PROJECT_ROOT / "data" not in resolved.parents


def test_runtime_path_env_set_handles_data_root_and_case(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert runtime_path("data") == tmp_path.resolve()
    assert runtime_path("./DATA/x.txt") == (tmp_path / "x.txt").resolve()


def test_runtime_path_non_data_relative_stays_project_rooted(tmp_path: Path, monkeypatch) -> None:
    """非 data/ 前缀的相对值保持「项目根相对」契约（与 runtime_paths 文档一致）。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert runtime_path("foo/bar.txt") == (PROJECT_ROOT / "foo" / "bar.txt").resolve()


def test_runtime_data_dir_unset_follows_dotenv_then_source_default(
    tmp_path: Path, monkeypatch
) -> None:
    """env 未设置：dotenv 命中则用 dotenv；两者皆空才回退源码 data/（既有默认）。"""
    _isolate_dotenv(monkeypatch)
    assert runtime_data_dir() == (PROJECT_ROOT / "data").resolve()
    _isolate_dotenv(monkeypatch, str(tmp_path))
    assert runtime_data_dir() == tmp_path.resolve()


def test_config_resolver_covers_all_runtime_data_fields(tmp_path: Path, monkeypatch) -> None:
    """Config 构造后全部 data/ 字段必须是数据根下的绝对路径（含此前遗漏项）。"""
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    from plugins.bot_unified_runtime.config import Config

    config = Config(bot_runtime_data_dir=str(tmp_path))
    for name in RESOLVED_CONFIG_FIELDS:
        raw = str(getattr(config, name))
        if not raw.strip():
            # 空值语义 = 功能关闭（如 bot_cookies_file 留空匿名解析），保持为空。
            continue
        value = Path(raw)
        assert value.is_absolute(), f"{name} 未被重映射: {value}"
        assert value == (tmp_path / value.name).resolve(), f"{name} 指向错误数据根"
        assert PROJECT_ROOT / "data" not in value.parents, f"{name} 落在源码树"


def test_cookie_relative_path_uses_dotenv_aware_root(tmp_path: Path, monkeypatch) -> None:
    """cookies 解析（platform_credentials 写入共用）env 与 dotenv 双通道生效。"""
    from plugins.bot_unified_runtime.domains.link_parse.parsers.cookies import (
        _resolve_relative_cookie_path,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    resolved = _resolve_relative_cookie_path(Path("data/platform_cookies.txt"))
    assert resolved == (tmp_path / "platform_cookies.txt").resolve()

    _isolate_dotenv(monkeypatch, str(tmp_path))
    resolved = _resolve_relative_cookie_path(Path("data/platform_cookies.txt"))
    assert resolved == (tmp_path / "platform_cookies.txt").resolve()


def test_platform_credentials_write_target_never_source_tree(
    tmp_path: Path, monkeypatch
) -> None:
    """/bot cookie 写入路径与读取路径同源，env 设置时绝不指向源码树。"""
    from types import SimpleNamespace

    from plugins.bot_unified_runtime.domains.core.credentials.platform_credentials import (
        _resolve_cookie_file,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    target = _resolve_cookie_file(
        SimpleNamespace(bot_cookies_file="data/platform_cookies.txt")
    )
    assert target is not None
    assert target == (tmp_path / "platform_cookies.txt").resolve()
    assert PROJECT_ROOT / "data" not in target.parents


@pytest.mark.parametrize("module_name", ["platforms_epic", "platforms_steam"])
def test_epic_steam_cookie_candidates_prefer_runtime_root(
    tmp_path: Path, monkeypatch, module_name: str
) -> None:
    """epic/steam 只读候选首位必须落在数据根（dotenv-only 入口也不跳源码树）。"""
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BOT_COOKIES_FILE", raising=False)
    module = __import__(
        f"plugins.bot_unified_runtime.domains.link_parse.parsers.{module_name}",
        fromlist=["_cookie_file_candidates"],
    )
    candidates = module._cookie_file_candidates()
    assert candidates, "候选列表不应为空"
    assert candidates[0] == (tmp_path / "platform_cookies.txt").resolve()


def test_music_default_dir_routes_to_runtime_root(tmp_path: Path, monkeypatch) -> None:
    """点歌试听下载目录：相对默认值落数据根；绝对配置原样保留。"""
    from plugins.bot_unified_runtime.domains.music.capabilities.music import (
        _resolve_music_data_dir,
    )

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert _resolve_music_data_dir("data/music") == (tmp_path / "music").resolve()

    absolute = tmp_path / "custom_music"
    assert _resolve_music_data_dir(str(absolute)) == absolute

    _isolate_dotenv(monkeypatch, str(tmp_path))
    assert _resolve_music_data_dir("data/music") == (tmp_path / "music").resolve()


def test_tts_gptsovits_dir_remap_semantics(tmp_path: Path, monkeypatch) -> None:
    """M-52（T125）：gptsovits_dir 引擎目录键入 path_fields 的三态语义锁。

    绝对值（GPT-SoVITS 引擎目录，C:/Software 语义）必须原样透传=生产零行为
    变化；data/ 相对误配必须重定向 Runtime 数据根（铁律 6，防 CWD join 落
    源码树）；缺省空串（功能未配语义）必须保持空。
    """
    from plugins.bot_unified_runtime.config import Config

    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)

    engine_dir = tmp_path / "GPT-SoVITS"
    config = Config(
        bot_runtime_data_dir=str(tmp_path),
        bot_tts_gptsovits_dir=str(engine_dir),
    )
    assert Path(config.bot_tts_gptsovits_dir) == engine_dir.resolve()

    config = Config(
        bot_runtime_data_dir=str(tmp_path),
        bot_tts_gptsovits_dir="data/gptsovits",
    )
    resolved = Path(config.bot_tts_gptsovits_dir)
    assert resolved == (tmp_path / "gptsovits").resolve()
    assert PROJECT_ROOT / "data" not in resolved.parents

    config = Config(bot_runtime_data_dir=str(tmp_path))
    assert config.bot_tts_gptsovits_dir == ""


# ===========================================================================
# P0（2026-09-29）测试进程 Runtime 根隔离：一条中央缝 ＋ 判解析结果的三组腿
# ===========================================================================
# 现算危险面（判据＝(文件, 被调符号, 是否传隔离件)，行号只作辅助）：
#   `build_chat_capability(content_route_config=<非 None>)` 且未注 store 的构造点
#   在测试树里成族存在；该函数体经 reply_policy.shared_reply_policy_store →
#   providers.build_runtime_data_path → **本文件的 runtime_path** 解析 store 落点，
#   而 ReplyPolicyStore.__post_init__ 是 mkdir + connect + PRAGMA journal_mode=WAL
#   + CREATE TABLE ⇒ 「跑一次就动盘」与有没有逻辑行变化无关。
# 执法次序（缺一枚就退回今天的形状）：
#   L1 tests/conftest.py 装配期调用 isolate_test_runtime_environment（**赋值**式）
#   L2 scripts/runtime_paths.guard_test_runtime_root（全仓唯一判定实现，两态）
#   L3 本文件：A 组量 L1、B 组量 L2、C 组量「注了 store 却被子形参吞掉」。
# 注毒三形（本席实跑读数见席位报告）：摘 L1 ⇒ A1/A3/C1 红；摘 L2 ⇒ B1/B2 红；
# 从形参表里删掉 reply_policy_store ⇒ C2 红；把赋值改成 setdefault ⇒ A2 红。

CAPABILITY_BUILDERS: tuple[str, ...] = ("build_chat_capability", "build_chat_result")
REPLY_POLICY_STORE_PARAM = "reply_policy_store"
REPLY_POLICY_LAZY_FACTORY = "shared_reply_policy_store"
CHAT_CAPABILITY_SOURCE = "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py"
REPLY_POLICY_SOURCE = "plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py"


def _seam(name: str) -> Any:
    """取真身符号；缺席即 pytest.fail（不许退成 AttributeError/ERROR，也不许 skip）。"""
    symbol = getattr(runtime_paths, name, None)
    if symbol is None:
        pytest.fail(f"scripts/runtime_paths 缺少中央缝符号 {name} ⇒ 测试进程无人拦生产根")
    return symbol


def _forbidden_roots() -> tuple[Path, ...]:
    reader = _seam("production_runtime_data_dirs")
    roots = tuple(reader())
    if not roots:
        pytest.fail(
            "本检出既没在盘上 .env/.env.prod 声明 BOT_RUNTIME_DATA_DIR，也没有 "
            "BOT_TEST_FORBIDDEN_RUNTIME_ROOTS ⇒ 本锁在此检出无法执法。"
            "故意不用 pytest.skip：零执法的锁会被在册尺算作在场（假绿形态册）。"
        )
    return roots


def _under(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


# ---------------------------------------------------------------------------
# A 组：量 L1（conftest 的赋值式重定向到底跑没跑）
# ---------------------------------------------------------------------------


def test_pytest_process_runtime_root_is_never_the_production_root() -> None:
    """在册测试件跑起来时，解析出的数据根不得是生产根（量结果，不量夹具写法）。"""
    active = _seam("test_runtime_isolation_active")
    guard = _seam("guard_test_runtime_root")
    roots = _forbidden_roots()
    if not active():
        pytest.fail(f"tests/conftest.py 的 L1 缺席：本进程未开启 Runtime 根隔离（禁写根={roots}）")
    resolved = runtime_data_dir()
    if _under(resolved, roots):
        pytest.fail(f"测试进程把数据根解析进了生产根：{resolved}")
    # 缝必须真在链路上（不是只住在 conftest 的 if 里）：对同一枚解析器再问一次。
    assert guard(resolved) == resolved, "缝对本进程已解析出的安全根应当原样放行"


def test_lazy_leg_default_store_path_lands_outside_production_root() -> None:
    """装配腿没注 store 时走的那条缺路径，解析结果必须在生产根之外。

    常量从真身取（AST 读 reply_policy.py 的赋值，不 import 插件包＝不建库）。
    """
    tree = ast.parse((PROJECT_ROOT / REPLY_POLICY_SOURCE).read_text(encoding="utf-8"))
    literal = ""
    for node in ast.walk(tree):
        # 两种赋值形态都要认：``X = "..."``（Assign）与 ``X: Final[str] = "..."``
        # （AnnAssign）——真身用的是后者，只认 Assign 会把活着的符号读成"改名"。
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None or not isinstance(value, ast.Constant):
            continue
        if any(isinstance(t, ast.Name) and t.id == "REPLY_POLICY_DB_FALLBACK_PATH" for t in targets):
            literal = str(value.value)
    if not literal:
        pytest.fail(
            "reply_policy.py 里读不到 REPLY_POLICY_DB_FALLBACK_PATH"
            " ⇒ 真身改名或换了赋值形态，本锁已瞎"
        )
    roots = _forbidden_roots()
    resolved = runtime_path(literal)
    if _under(resolved, roots):
        pytest.fail(f"缺路径解析进生产根（构造即动盘）：{resolved}")
    assert resolved.name.endswith(".sqlite3"), f"缺路径形状变了：{resolved}"


# ---------------------------------------------------------------------------
# B 组：量 L2（唯一判定实现的两态）
# ---------------------------------------------------------------------------


def test_isolation_helper_overrides_preexisting_value_by_assignment() -> None:
    """赋值 vs setdefault：本仓已两次实测 setdefault 对已启动解释器无效。

    父进程带着「生产值」进来时，L1 必须把它**挤掉**并登记成禁写根；写成
    setdefault 的话生产值原样活着 ⇒ 本腿当场红。
    """
    isolate = _seam("isolate_test_runtime_environment")
    decoy = "Z:/decoy/production-runtime/data"
    replacement = "Z:/tmp/chatbot-pytest-runtime/4242"
    environ = {runtime_paths.RUNTIME_DATA_DIR_ENV: decoy}
    recorded = tuple(isolate(environ, replacement_root=replacement, dotenv_reader=lambda key: ""))
    assert environ[runtime_paths.RUNTIME_DATA_DIR_ENV] == replacement, (
        "L1 必须是赋值：setdefault 只在键缺席时写，生产值会活下来"
    )
    assert environ[runtime_paths.TEST_PROCESS_ENV] == "1"
    assert environ[runtime_paths.TEST_RUNTIME_DATA_DIR_ENV] == replacement
    assert decoy in {str(p) for p in recorded}, "被挤掉的那一枚必须登记成禁写根"


def test_seam_redirects_a_production_root_hit_into_the_test_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式把 env 指回生产根 ⇒ 缝把它挪走（挪走＝在册件不误伤，不是打死）。"""
    roots = _forbidden_roots()
    prod = roots[0]
    replacement = (tmp_path / "isolated-runtime").resolve()
    monkeypatch.setenv(runtime_paths.RUNTIME_DATA_DIR_ENV, str(prod))
    monkeypatch.setenv(runtime_paths.TEST_PROCESS_ENV, "1")
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_DATA_DIR_ENV, str(replacement))
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_GUARD_MODE_ENV, "redirect")
    monkeypatch.setenv(runtime_paths.TEST_FORBIDDEN_ROOTS_ENV, os.pathsep.join(str(r) for r in roots))
    got = runtime_data_dir()
    assert got != prod, "缝没生效：测试进程仍解析到生产根"
    assert got == replacement, f"重定向落点不是登记过的隔离根：{got}"


def test_seam_refuses_production_root_in_refuse_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """refuse 态＝命中即抛；异常必须住 BaseException 族（普通 Exception 会被咽）。

    真身链路上 ReplyPolicyStore.__post_init__ 与 shared_reply_policy_store 的解析段
    全裹 ``except Exception`` ⇒ Exception 族只会被降级成两声日志＝静默绿。
    """
    violation = _seam("RuntimeIsolationViolation")
    assert issubclass(violation, BaseException), "违规族必须是 BaseException 子族"
    assert not issubclass(violation, Exception), (
        "违规族不得是 Exception：懒建腿与 __post_init__ 的双层 except Exception 会把它咽成日志"
    )
    roots = _forbidden_roots()
    guard = _seam("guard_test_runtime_root")
    monkeypatch.setenv(runtime_paths.TEST_PROCESS_ENV, "1")
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_DATA_DIR_ENV, str((tmp_path / "unused").resolve()))
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_GUARD_MODE_ENV, "refuse")
    monkeypatch.setenv(runtime_paths.TEST_FORBIDDEN_ROOTS_ENV, os.pathsep.join(str(r) for r in roots))
    with pytest.raises(violation):
        guard(roots[0] / "reply_policy.sqlite3")


def test_guard_is_inert_for_non_test_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产语义零变化：非测试进程里缝必须原样放行（不许静默改生产落点）。"""
    roots = _forbidden_roots()
    guard = _seam("guard_test_runtime_root")
    monkeypatch.delenv(runtime_paths.TEST_PROCESS_ENV, raising=False)
    assert guard(roots[0]) == roots[0], "生产进程里缝改了落点＝越权改生产语义"
    assert runtime_data_dir() == roots[0], "生产缺省落点必须还是 .env 声明的那一枚"


# ---------------------------------------------------------------------------
# C 组：判「注入有没有真生效」——写法面只有一枚真身尺：被调函数的形参表
# ---------------------------------------------------------------------------


def _builder_signatures(chat_tree: ast.AST) -> dict[str, tuple[set[str], str, bool]]:
    """{函数名: (形参名, **兜底名, 函数体是否用懒建工厂)}；用名字不用行号。"""
    out: dict[str, tuple[set[str], str, bool]] = {}
    for node in ast.walk(chat_tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in CAPABILITY_BUILDERS:
            continue
        params = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
        catch_all = node.args.kwarg.arg if node.args.kwarg else ""
        used_names = {
            n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
        }
        out[node.name] = (params, catch_all, REPLY_POLICY_LAZY_FACTORY in used_names)
    return out


def _audit_store_injection(
    code_root: Path,
    *,
    isolation_active: bool,
) -> list[str]:
    """现算测试树里「够得着 store 却没被隔离」与「注了 store 却被吞」两类站。

    两类判据都来自真身，不来自写法约定：
    * 够得着＝被调函数体里真出现懒建工厂名（哪天 build_chat_result 也长出懒建腿，
      它当场并入，不靠人记得改本锁）；
    * 被吞＝传了关键字，但被调函数形参表里没有这个名字、却有 ``**`` 兜底 ⇒
      Python 语义上这个关键字进了兜底字典，注入根本没生效（＝「注了 store
      不等于已隔离」的机械形态）。
    """
    chat = code_root / CHAT_CAPABILITY_SOURCE
    if not chat.is_file():
        pytest.fail(f"真身缺席：{CHAT_CAPABILITY_SOURCE} ⇒ 本锁尺已瞎")
    signatures = _builder_signatures(ast.parse(chat.read_text(encoding="utf-8")))
    for name in CAPABILITY_BUILDERS:
        if name not in signatures:
            pytest.fail(f"真身函数 {name} 已改名/搬走 ⇒ 本锁必须跟着改，不许静默零命中")
    violations: list[str] = []
    for test_file in sorted((code_root / "tests").glob("*.py")):
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        for container in ast.walk(tree):
            calls: list[ast.Call] = []
            if isinstance(container, ast.FunctionDef):
                calls = [n for n in ast.walk(container) if isinstance(n, ast.Call)]
                patches_factory = any(
                    isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "setattr"
                    and len(n.args) > 1
                    and isinstance(n.args[1], ast.Constant)
                    and n.args[1].value == REPLY_POLICY_LAZY_FACTORY
                    for n in calls
                )
            elif isinstance(container, ast.Module):
                # 收的是 **Call 节点**（不是包着它的 Expr）：取 Expr 会让下面的
                # ``call.func`` 当场 AttributeError（尺自己瞎＝零命中假绿）。
                calls = [
                    n.value
                    for n in container.body
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                ]
                for call in list(calls):
                    calls.extend(
                        n for n in ast.walk(call) if isinstance(n, ast.Call) and n is not call
                    )
                patches_factory = False
            else:
                continue
            for call in calls:
                func = call.func
                callee = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if callee not in CAPABILITY_BUILDERS:
                    continue
                params, catch_all, reaches_store = signatures[callee]
                kwargs = {k.arg: ast.unparse(k.value) for k in call.keywords if k.arg}
                injected = REPLY_POLICY_STORE_PARAM in kwargs
                route = kwargs.get("content_route_config", "").strip()
                reaches = reaches_store and route not in {"", "None"}
                tag = f"{test_file.name}:{call.lineno} {callee}"
                if injected and catch_all and REPLY_POLICY_STORE_PARAM not in params:
                    violations.append(f"{tag} 注入被 **{catch_all} 静默吞掉（形参表里没有这个名字）")
                elif reaches and not injected and not patches_factory and not isolation_active:
                    violations.append(f"{tag} 够得着 store 却没传隔离根，且本进程未开启 Runtime 根隔离")
    return violations


def test_store_injection_sites_are_neither_swallowed_nor_unprotected() -> None:
    """现役树：既不许有被吞的注入，也不许有「没隔离又没缝」的构造点。"""
    active = _seam("test_runtime_isolation_active")
    violations = _audit_store_injection(PROJECT_ROOT, isolation_active=bool(active()))
    assert not violations, "构造点注入形＝假隔离：\n" + "\n".join(violations)


def test_auditor_bites_when_the_store_param_is_swallowed(tmp_path: Path) -> None:
    """注毒①：从形参表里摘掉 reply_policy_store ⇒ 同一枚尺必须报「被吞」。

    在 tmp_path 副本上注毒（先验锚点、逐字节核对未动的部分），主树一件不动。
    """
    anchor = f"    {REPLY_POLICY_STORE_PARAM}: Any | None = None,\n"
    source = (PROJECT_ROOT / CHAT_CAPABILITY_SOURCE).read_text(encoding="utf-8")
    if source.count(anchor) != 1:
        pytest.fail(f"注毒锚点不再是唯一一枚（命中 {source.count(anchor)}），本毒未验先落＝作废")
    staged = tmp_path / "tree"
    (staged / "tests").mkdir(parents=True)
    poisoned = source.replace(anchor, "", 1)
    assert anchor not in poisoned and len(poisoned) == len(source) - len(anchor)
    (staged / CHAT_CAPABILITY_SOURCE).parent.mkdir(parents=True, exist_ok=True)
    (staged / CHAT_CAPABILITY_SOURCE).write_text(poisoned, encoding="utf-8")
    donor = PROJECT_ROOT / "tests" / "test_reply_policy_permanent.py"
    if not donor.is_file():
        pytest.fail("注毒供体件缺席（本毒要靠一枚真会注 store 的在册件）")
    shutil.copyfile(donor, staged / "tests" / donor.name)

    violations = _audit_store_injection(staged, isolation_active=True)
    assert any("静默吞掉" in line for line in violations), (
        f"摘掉形参后尺子没咬住（读数={violations}）⇒ 这把锁只会量已知的绿"
    )


def test_auditor_bites_when_a_live_site_drops_its_isolation(tmp_path: Path) -> None:
    """注毒②：构造点不传隔离根 ⇒ 同一枚尺在「缝没开」时必须报红。

    两半都要：缝关掉 ⇒ 必须命中；缝开着 ⇒ 必须放行（证明中央缝真的在替这族
    构造点兜底，而不是本锁放过它们）。
    """
    staged = tmp_path / "tree"
    (staged / "tests").mkdir(parents=True)
    # copyfile 不建父目录：仓外副本的 plugins/... 一层不存在 ⇒ 本毒会在自己家
    # fixture 上 FileNotFoundError（注毒腿炸在装配面＝从没验过尺，等于零执法）。
    (staged / CHAT_CAPABILITY_SOURCE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT_ROOT / CHAT_CAPABILITY_SOURCE, staged / CHAT_CAPABILITY_SOURCE)
    site = (
        "from plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat import (\n"
        "    build_chat_capability,\n"
        ")\n\n\n"
        "def test_unprotected_site(cfg) -> None:\n"
        "    build_chat_capability(content_route_config=cfg)\n"
    )
    (staged / "tests" / "test_poison_site.py").write_text(site, encoding="utf-8")

    off = _audit_store_injection(staged, isolation_active=False)
    assert any("没传隔离根" in line for line in off), f"缝关掉后尺子没咬住：{off}"
    on = _audit_store_injection(staged, isolation_active=True)
    assert on == [], f"缝开着却仍报这族构造点＝中央缝没真正兜底（读数={on}）"


# ===========================================================================
# D 组（2026-10-04 seat-pathguard）：**绝对路径腿**——缝的第二处缺口
# ===========================================================================
# A/B/C 三组量的是「相对 data/ 值按 env 解析」那条路：conftest L1 把 env 挤成隔离根
# ⇒ 相对值天然落隔离根。缺口在**读数本身已经是绝对路径**的那一支：
#   ① ``runtime_path()`` 的绝对分支 ``return path.resolve()``——判定件一个字没问；
#   ② ``config.runtime_data_root_of`` / ``remap_runtime_data_paths``——合并/装配层
#      交进来的绝对读数被当终值，同样没问判定件。
# 已实现的后果（2026-10-04 现算）：一枚测量夹具往**生产**
# ``ChatBot_Runtime\data\addressing_preferences.sqlite3``（她跨重启亲密称谓的私库）
# 插了一条真行——它的「只重映射相对 data/ 路径」过滤器永不相交，因为路径早就是绝对的。
# 本组只判**解析出的字符串**：不 import store、不建目录、不开库，且逐条核对生产根
# 目录清单前后一致（`_live_root_listing`）＝本锁自己绝不制造第二起事故。

#: 事故落点的文件名（生产私库；本组只拿它拼字符串）。
PRODUCTION_STORE_TAIL = "addressing_preferences.sqlite3"


def _live_root_listing() -> tuple[str, ...] | None:
    """生产数据根的目录清单快照（只读）：缺席检出返回 None（前后同为 None 即未动）。"""
    target = _forbidden_roots()[0]
    return tuple(sorted(os.listdir(target))) if target.is_dir() else None


def _assert_live_root_untouched(before: tuple[str, ...] | None) -> None:
    assert _live_root_listing() == before, "本用例在生产数据根里创建了东西（越界写）"


def _arm_refuse_mode(monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ...]:
    """把判定件装配成「测试进程 + refuse（缺省态）」：逐枚显式设，不蹭环境运气。"""
    roots = _forbidden_roots()
    monkeypatch.setenv(runtime_paths.TEST_PROCESS_ENV, "1")
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_GUARD_MODE_ENV, runtime_paths.GUARD_MODE_REFUSE)
    monkeypatch.setenv(
        runtime_paths.TEST_FORBIDDEN_ROOTS_ENV, os.pathsep.join(str(root) for root in roots)
    )
    monkeypatch.setenv(
        runtime_paths.TEST_RUNTIME_DATA_DIR_ENV, str(Path(tempfile.gettempdir()) / "pg-seat-unused")
    )
    return roots


def test_runtime_path_refuses_absolute_production_rooted_value(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """①缺口：测试进程把**绝对**生产落点喂给 ``runtime_path`` ⇒ 必须拒，不许原样放行。"""
    violation = _seam("RuntimeIsolationViolation")
    roots = _arm_refuse_mode(monkeypatch)
    before = _live_root_listing()
    target = roots[0] / PRODUCTION_STORE_TAIL
    with pytest.raises(violation):
        runtime_path(target)
    _assert_live_root_untouched(before)


def test_config_remap_refuses_absolute_production_rooted_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """②缺口（字段面）：数据根安全、但**某枚路径字段本身**是生产根下的绝对值 ⇒ 拒。

    这是测量夹具那次的形状：它的过滤器只盯 ``data/`` 相对写法，绝对读数直接成了终值。
    """
    violation = _seam("RuntimeIsolationViolation")
    from plugins.bot_unified_runtime.config import Config

    roots = _arm_refuse_mode(monkeypatch)
    before = _live_root_listing()
    poisoned = str(roots[0] / PRODUCTION_STORE_TAIL)
    with pytest.raises(violation):
        Config(bot_runtime_data_dir=str(tmp_path), bot_addressing_preferences_db_path=poisoned)
    _assert_live_root_untouched(before)


def test_config_remap_refuses_a_production_data_root(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """②缺口（根面）：测试进程把 ``bot_runtime_data_dir`` 直接设成生产根 ⇒ 拒。

    ``.env`` 那枚读数就是生产根；任何「按盘上声明原样装载」的测试构造点都走这条腿，
    于是整张路径名册一起指向生产——比单枚字段更狠，必须同一条判定件拦住。
    """
    violation = _seam("RuntimeIsolationViolation")
    from plugins.bot_unified_runtime.config import Config

    roots = _arm_refuse_mode(monkeypatch)
    before = _live_root_listing()
    with pytest.raises(violation):
        Config(bot_runtime_data_dir=str(roots[0]))
    _assert_live_root_untouched(before)


def test_config_side_consults_the_single_judge() -> None:
    """结构锁：config 侧只**问**那唯一判定件，不抄第二份判据；取用口瞎了要当场红。

    ``_test_runtime_root_judge()`` 返回 None 的两种含义必须分开：骨架最小仓（判定件
    文件本身缺席，conftest L1 同一口径放行）＝可接受；真树里 import 失败被 try/except
    洗成 None＝「全树绿、库被写了」的静默形态 ⇒ 本腿红。
    """
    judge = _seam("guard_test_runtime_root")
    config_module = importlib.import_module("plugins.bot_unified_runtime.config")
    accessor = getattr(config_module, "_test_runtime_root_judge", None)
    if accessor is None:
        pytest.fail("config.py 没有 _test_runtime_root_judge 取用口 ⇒ 绝对腿仍无人判定")
    if runtime_paths.__file__ and (PROJECT_ROOT / "scripts" / "runtime_paths.py").is_file():
        assert accessor() is judge, (
            f"config 侧问到的不是唯一判定件（拿到={accessor()}）⇒ 判据出现第二副本或取用口已瞎"
        )
    resolver_source = inspect.getsource(runtime_paths.runtime_path)
    guard_branch_calls: set[str] = set()
    for node in ast.walk(ast.parse(resolver_source)):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Call) and getattr(test.func, "attr", "") == "is_absolute"):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                callee = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
                if callee:
                    guard_branch_calls.add(callee)
    assert guard_branch_calls, "runtime_path 里读不到绝对分支 ⇒ 尺已瞎（形状改了）"
    assert "guard_test_runtime_root" in guard_branch_calls, (
        f"runtime_path 的绝对分支不再问判定件（该分支调用={sorted(guard_branch_calls)}）⇒ ①缺口复发"
    )


def test_absolute_leg_is_inert_without_the_test_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产方向锁（与 D1–D3 反向）：标记缺席 ⇒ 绝对生产落点**逐字**照旧放行。

    她的运行时真的住在这枚根里：判定件在未装配时必须原样返回，且 config 侧不得改写
    读数（今天 ``runtime_data_root_of`` 返回未 resolve 的 ``Path``、字段值＝
    ``str(data_root / tail)``，改一个字都会漂出哈希/链接门）。
    """
    roots = _forbidden_roots()
    monkeypatch.delenv(runtime_paths.TEST_PROCESS_ENV, raising=False)
    before = _live_root_listing()
    target = roots[0] / PRODUCTION_STORE_TAIL
    assert runtime_path(target) == target, "非测试进程里判定件改了落点＝越权改生产语义"

    from plugins.bot_unified_runtime.config import Config

    config = Config(bot_runtime_data_dir=str(roots[0]))
    assert config.bot_runtime_data_dir == str(roots[0])
    assert config.bot_addressing_preferences_db_path == str(target), "生产缺省落点漂了"
    assert config.bot_reminder_db_path == str(roots[0] / "reminders.sqlite3"), "相对名册读数漂了"
    assert _live_root_listing() == before, "装载一次就在生产根里建了东西"


def test_runtime_path_redirect_moves_absolute_value_but_keeps_its_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """redirect 态（在册只读对照用例的显式 opt-in）：挪进隔离根、**保留相对尾巴**。

    尾巴丢了会把 ``<库文件>`` 折成一枚目录：只读对照用例从此开目录当库＝假绿形态。
    """
    roots = _forbidden_roots()
    isolated = (tmp_path / "isolated-runtime").resolve()
    monkeypatch.setenv(runtime_paths.TEST_PROCESS_ENV, "1")
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_DATA_DIR_ENV, str(isolated))
    monkeypatch.setenv(runtime_paths.TEST_RUNTIME_GUARD_MODE_ENV, runtime_paths.GUARD_MODE_REDIRECT)
    monkeypatch.setenv(
        runtime_paths.TEST_FORBIDDEN_ROOTS_ENV, os.pathsep.join(str(root) for root in roots)
    )
    before = _live_root_listing()
    got = runtime_path(roots[0] / PRODUCTION_STORE_TAIL)
    assert not _under(got, roots), f"redirect 后仍在生产根里：{got}"
    assert got == (isolated / PRODUCTION_STORE_TAIL).resolve(), (
        f"重定向落点形状不对（期望尾巴={PRODUCTION_STORE_TAIL}）：{got}"
    )
    assert not got.exists(), "重定向落点被创建了"
    _assert_live_root_untouched(before)

