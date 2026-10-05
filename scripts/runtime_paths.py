"""Stable paths for maintenance commands.

The source tree is the AI workspace; mutable databases, media and plugin state
live in the sibling ``ChatBot_Runtime`` directory.  This module deliberately
reads only path settings from dotenv files and never prints their contents.

测试进程 Runtime 根隔离缝（2026-09-29 P0，执法锁＝``tests/test_datafix_runtime_paths.py``
下半部分 A/B/C 三组）：``.env`` 把 ``BOT_RUNTIME_DATA_DIR`` 指向**生产**根，而
``tests/conftest.py`` 的 G1 守卫只快照源码树 ``data/``，于是测试树里没传隔离根的
构造点（``ReplyPolicyStore`` 之类「构造即 mkdir + connect + WAL」）会在测试进程里
直接打开生产库。本模块是这条判定的**全仓唯一实现**，两态语义：

* ``guard_test_runtime_root`` —— 命中生产根即抛 ``RuntimeIsolationViolation``；
* 未装配（``BOT_TEST_PROCESS`` 缺席）时**原样放行**＝生产 bot 进程零行为变化。

问它的腿只有两条（判据不得在别处再抄一份）：本模块 ``runtime_path`` 的绝对分支与
``runtime_data_dir``；``plugins/bot_unified_runtime/config.py`` 经
``_test_runtime_root_judge`` **只判定不改写**——绝对读数逐字返回，否则生产字符串会漂。

装配期入口是 ``isolate_test_runtime_environment``（由 ``tests/conftest.py`` 以**赋值**式
调用，把生产根挤掉并登记成禁写根）；判定模式默认 ``refuse``＝fail-closed，在册的
只读对照用例要显式设 ``BOT_TEST_RUNTIME_GUARD_MODE=redirect`` 才会被「挪走」而不是打死。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ---- 环境口径（键名即契约；判定只看这几枚，不看调用方写法）----
RUNTIME_DATA_DIR_ENV: str = "BOT_RUNTIME_DATA_DIR"
TEST_PROCESS_ENV: str = "BOT_TEST_PROCESS"
TEST_RUNTIME_DATA_DIR_ENV: str = "BOT_TEST_RUNTIME_DATA_DIR"
TEST_RUNTIME_GUARD_MODE_ENV: str = "BOT_TEST_RUNTIME_GUARD_MODE"
TEST_FORBIDDEN_ROOTS_ENV: str = "BOT_TEST_FORBIDDEN_RUNTIME_ROOTS"

#: 缺省＝命中即抛（fail-closed）；``redirect`` 是显式 opt-in，只给在册的对照用例。
GUARD_MODE_REFUSE: str = "refuse"
GUARD_MODE_REDIRECT: str = "redirect"
_DEFAULT_GUARD_MODE: str = GUARD_MODE_REFUSE

_DOTENV_FILENAMES: tuple[str, ...] = (".env", ".env.prod")
_SOURCE_TREE_FALLBACK: str = "data"


class RuntimeIsolationViolation(BaseException):
    """测试进程把落点解析进了生产 Runtime 根。

    故意住 ``BaseException`` 族而**不是** ``Exception``：真身链路上
    ``ReplyPolicyStore.__post_init__`` 与 ``shared_reply_policy_store`` 的解析段全裹
    ``except Exception`` ⇒ Exception 族只会被降级成两声日志＝「全树绿、库被写了、
    她的偏好静默失效」这种静默绿形态。
    """


def _strip_inline_comment(raw_value: str) -> str:
    """去掉 dotenv 行内注释（引号感知）：仅在未闭合引号外、且 ``#`` 前有空白时截断。

    与 python-dotenv 行为对齐：``data # 注释`` → ``data``；
    ``"a # b"`` 引号内的 # 不算注释；``a#b`` 无空白不算注释。
    """
    quote = ""
    for index, char in enumerate(raw_value):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and index > 0 and raw_value[index - 1] in " \t":
            return raw_value[:index].rstrip()
    return raw_value


def _dotenv_file_value(key: str) -> str:
    """盘上 ``.env`` → ``.env.prod`` 的声明值，**不看** ``os.environ``。

    测试进程里 env 已被装配层挪成隔离根，「什么叫生产根」只能问盘上声明；
    这条口径是 ``production_runtime_data_dirs`` 的一半骨头。
    """
    value = ""
    for filename in _DOTENV_FILENAMES:
        path = PROJECT_ROOT / filename
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = _strip_inline_comment(raw_value).strip().strip('"').strip("'")
    return value


def _dotenv_value(key: str) -> str:
    """Read one non-secret setting using the same .env then .env.prod order."""
    return os.environ.get(key, _dotenv_file_value(key)).strip()


# ---------------------------------------------------------------------------
# 隔离缝：读数工具（全部现算，不留模块级状态——本模块可能被 ``runtime_paths`` 与
# ``scripts.runtime_paths`` 两个模块名各载一份，任何模块内缓存都会分裂。）
# ---------------------------------------------------------------------------


def _text(value: object) -> str:
    return str(value if value is not None else "").strip()


def _env_text(key: str, environ: Mapping[str, object] | None = None) -> str:
    source: Mapping[str, object] = os.environ if environ is None else environ
    return _text(source.get(key, ""))


def _split_root_texts(raw: str) -> list[str]:
    """``os.pathsep`` 分隔的禁写根读数：逐字保留、空段丢弃（顺序即优先级）。"""
    if not raw:
        return []
    return [_text(piece) for piece in raw.split(os.pathsep) if _text(piece)]


def _as_root(text: str) -> Path:
    """读数 → 绝对解析根：相对值按项目根拼接（与 ``runtime_path`` 同口径）。"""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _marker_on(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def in_pytest_process() -> bool:
    """本进程像不像 pytest 跑起来的（装配入口用来自证「不许在生产进程里挪根」）。"""
    if _env_text("PYTEST_CURRENT_TEST"):
        return True
    if any(name in sys.modules for name in ("pytest", "_pytest")):
        return True
    argv0 = os.path.basename(sys.argv[0]).lower() if sys.argv else ""
    return "pytest" in argv0


def test_runtime_isolation_active() -> bool:
    """L1（装配期重定向）到底有没有在本进程生效——只认标记，不认「像不像测试」。

    标记被摘掉就等于「复现非测试进程」，所以 ``in_pytest_process()`` 不参与本判定：
    否则 ``tests/conftest.py`` 的 L1 缺席会被自动探测洗成「一直在」＝假绿。
    """
    return _marker_on(_env_text(TEST_PROCESS_ENV))


def production_runtime_data_dirs() -> tuple[Path, ...]:
    """「什么叫生产根」的唯一口径（别处不得再拼第二份）。

    三源按优先级拼接、去重：① 进程 env 现值——**只在缝未装配时算数**（装配后它要么是缝
    自己的落点、要么被用例拨成 ``tmp_path``，而「用例把数据根指到 tmp」是测试树的常规
    写法，把它当生产根＝把整棵测试树打死）；② ``BOT_TEST_FORBIDDEN_RUNTIME_ROOTS``
    （装配层登记的「被挤掉的那一枚」——``.env`` 里查不到键不等于值拿不到，它可能只活在
    进程 env 里）；③ 盘上 ``.env``/``.env.prod`` 声明值。
    本进程登记的隔离根（``BOT_TEST_RUNTIME_DATA_DIR``）永不算生产根，否则 ``redirect``
    态会把重定向落点自己也禁掉，缝就变成打死在册件。
    """
    isolated = _env_text(TEST_RUNTIME_DATA_DIR_ENV)
    texts: list[str] = []
    ambient = _env_text(RUNTIME_DATA_DIR_ENV)
    if ambient and ambient != isolated and not test_runtime_isolation_active():
        texts.append(ambient)
    texts.extend(_split_root_texts(_env_text(TEST_FORBIDDEN_ROOTS_ENV)))
    declared = _dotenv_file_value(RUNTIME_DATA_DIR_ENV)
    if declared:
        texts.append(declared)

    roots: list[Path] = []
    for text in texts:
        root = _as_root(text)
        if isolated and root == _as_root(isolated):
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _under_any(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _effective_data_root_text() -> str:
    """数据根的**未判定**读数（env → dotenv → 源码树 ``data`` 既有缺省）。

    一条例外：隔离标记已被摘掉、而 env 里躺着的那枚正是本进程登记的隔离根时，
    那枚是上一轮装配留下的足迹、不是生产声明，退回盘上 ``.env`` 口径——
    「非测试进程」复现腿必须量到真实世界的缺省落点，否则测的是缝自己的记忆。
    """
    raw = _dotenv_value(RUNTIME_DATA_DIR_ENV)
    seam_footprint = raw == _env_text(TEST_RUNTIME_DATA_DIR_ENV)
    if raw and seam_footprint and not test_runtime_isolation_active():
        raw = _dotenv_file_value(RUNTIME_DATA_DIR_ENV)
    return raw or _SOURCE_TREE_FALLBACK


def guard_test_runtime_root(path: str | Path) -> Path:
    """测试进程 Runtime 根的唯一判定（两态；非测试进程原样放行）。

    * 标记缺席 ⇒ 返回逐字解析结果＝生产语义零变化（不许静默改生产落点）；
    * 标记在、落点不在任何生产根内 ⇒ 放行（在册件不误伤）；
    * 标记在、落点命中生产根 ⇒ 缺省抛 ``RuntimeIsolationViolation``；只有显式
      ``BOT_TEST_RUNTIME_GUARD_MODE=redirect`` 且登记过隔离根时才连根内相对尾巴一起
      挪进隔离根。
      模式读数不认识的值一律按缺省 refuse 处理（fail-closed）。
    """
    resolved = _as_root(str(path))
    if not test_runtime_isolation_active():
        return resolved
    roots = production_runtime_data_dirs()
    if not roots or not _under_any(resolved, roots):
        return resolved
    mode = (_env_text(TEST_RUNTIME_GUARD_MODE_ENV) or _DEFAULT_GUARD_MODE).lower()
    replacement = _env_text(TEST_RUNTIME_DATA_DIR_ENV)
    if mode == GUARD_MODE_REDIRECT and replacement:
        isolated = _as_root(replacement)
        # 尾巴要一起挪：``<生产根>/data/x.sqlite3`` 折成隔离根**目录**本身的话，在册的
        # 只读对照用例会拿目录当库文件开（＝假绿形态），而相对值那条腿本来就保留尾巴
        # （``runtime_path("data/x")`` → 隔离根/x）。同一条腿两种形状＝第二套口径。
        for root in roots:
            if resolved != root and resolved.is_relative_to(root):
                return (isolated / resolved.relative_to(root)).resolve()
        return isolated
    raise RuntimeIsolationViolation(
        f"测试进程把落点解析进了生产 Runtime 根：{resolved}"
        f"（禁写根={', '.join(str(root) for root in roots)}；判定模式={mode}）——"
        f"装配层（tests/conftest.py）要么以赋值式调用 isolate_test_runtime_environment "
        f"把 {RUNTIME_DATA_DIR_ENV} 挤成隔离根，要么为在册的只读对照用例显式设 "
        f"{TEST_RUNTIME_GUARD_MODE_ENV}={GUARD_MODE_REDIRECT}"
    )


def isolate_test_runtime_environment(
    environ: MutableMapping[str, str],
    *,
    replacement_root: str | Path,
    dotenv_reader: Callable[[str], str] | None = None,
) -> tuple[str, ...]:
    """装配期入口（``tests/conftest.py`` 模块级）：把生产根从 ``environ`` 挤掉并登记禁写。

    必须是**赋值**而不是 ``setdefault``——本仓已两次实测 ``setdefault`` 对已启动解释器
    无效，而带生产值进来的父进程正是这里要拦的那种；写成 setdefault 生产值会原样活着。

    返回被登记为禁写的生产根**读数**（逐字、不解析）：①「登记过什么」必须与
    「挤掉了什么」逐字一致，Windows 下 ``str(Path(...))`` 会把 ``/`` 换成 ``\\``，
    解析过就再也对不上原读数；②生产根在本机可以不存在（换机器/换检出），登记面
    不该为此炸。判定面另由 ``production_runtime_data_dirs`` 现算。

    ``replacement_root`` 为空 ⇒ 抛（没有落点的重定向等于把测试进程悬空，不许静默绿）。
    非 pytest 进程 ⇒ 抛：缝不得在生产进程里挪根。
    """
    if not in_pytest_process():
        raise RuntimeIsolationViolation(
            "拒绝在非 pytest 进程里装配测试隔离缝：那会把生产落点悄悄挪走（fail-closed）"
        )
    replacement = _text(replacement_root)
    if not replacement:
        raise RuntimeIsolationViolation("isolate_test_runtime_environment 需要一枚非空隔离根")
    reader = dotenv_reader or _dotenv_value

    displaced: list[str] = []
    for raw in (environ.get(RUNTIME_DATA_DIR_ENV, ""), reader(RUNTIME_DATA_DIR_ENV)):
        text = _text(raw)
        if text and text != replacement and text not in displaced:
            displaced.append(text)
    # 同一进程二次装配：上一轮登记的禁写根要一起活着，不许被洗成空名单。
    for text in _split_root_texts(_text(environ.get(TEST_FORBIDDEN_ROOTS_ENV, ""))):
        if text != replacement and text not in displaced:
            displaced.append(text)

    environ[RUNTIME_DATA_DIR_ENV] = replacement
    environ[TEST_RUNTIME_DATA_DIR_ENV] = replacement
    environ[TEST_PROCESS_ENV] = "1"
    environ[TEST_FORBIDDEN_ROOTS_ENV] = os.pathsep.join(displaced)
    return tuple(displaced)


def runtime_data_dir() -> Path:
    return guard_test_runtime_root(_as_root(_effective_data_root_text()))


def runtime_path(value: str | Path) -> Path:
    """Resolve data/... into the configured external runtime data directory."""
    path = Path(value).expanduser()
    if path.is_absolute():
        # 绝对腿过去**直接 return path.resolve()**＝缝的第二处缺口：测试进程里一枚已经
        # 是绝对形态的生产落点（``.env`` 读数、model_copy 合并值、夹具直传）原样放行，
        # 2026-10-04 实测由此往生产 addressing_preferences.sqlite3 插了一条真行。
        # 判定件在 inert 态返回 ``Path(value).expanduser().resolve()``＝与本行旧读数
        # 逐字相同（expanduser 已在上一行做过）⇒ 生产路径零字节变化（锁＝D4 反向腿）。
        return guard_test_runtime_root(path)
    # 与 config.py 的路径解析器对齐：统一剥 ./ 前缀并对 data/ 前缀
    # 大小写不敏感重映射，两侧对 "./DATA/x"、"data/x" 得到同一结果。
    normalized = str(path).replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    data_root = runtime_data_dir()
    if normalized.lower() == "data":
        return data_root
    if normalized.lower().startswith("data/"):
        return (data_root / normalized[5:]).resolve()
    return (PROJECT_ROOT / path).resolve()
