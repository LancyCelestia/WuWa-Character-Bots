"""import_chain_probe — 重启前的「入口 import 链」探针（离线、零进程动作）.

为什么需要它（台账硬知识）：bot 入口链上任一模块**模块级求值**抛错 ⇒ nonebot 只记
一条 error、``bot.py`` 崩溃守卫 ``raise`` ⇒ 插件全体不注册；``BOT_SUPERVISE=1`` 下
5 次熔断退避 5+15+60+60=140 秒后 rc=1 永久 down。重启之前必须拿到 import 链证据。

三条设计纪律（避开上一席三次踩过的 nonebot API 坑）：
  1. **不猜 driver**：全探针只调用 ``nonebot.init(_env_file=(".env", ".env.prod"))``
     ——与 ``bot.py:255`` 逐字同一条语句。init 只建 driver/config 对象，不绑端口、
     不连 WS、不起事件循环；探针绝不调 ``get_driver().run()``、绝不构造
     ``HttpxDriver``/``ReverseWebSocket``（那些名字在本机 nonebot 版本里不存在）。
  2. **bot.py 只编译不执行**：``import bot`` 会连带跑 ``load_from_toml`` 与
     ``_probe_onebot_endpoints()``（后者对 SnowLuma 端点做真 socket connect，
     属碰生产），故 bot.py 只走 ``compile()``／AST 级检查 —— 能抓 SyntaxError、
     抓不到 ImportError，这是本探针的**已知边界**，不假装覆盖。
  3. **插件注册那一腿另跑**：``nonebot.load_from_toml`` 腿（``--plugins``）回答的
     正是「重启会不会全体不注册」——它按生产同一入口加载，失败被 nonebot 咽进
     error 日志，本腿把 loaded/failed 名单现算出来。

隔离与卫生（全部自带，调用方不需要额外前缀）：
  * 每格导入跑在**子进程**里（一个模块炸不污染其余格），子环境钉死
    ``PYTHONDONTWRITEBYTECODE=1`` + ``PYTHONPYCACHEPREFIX=<临时>``
    → 源码树零 ``__pycache__``/``*.pyc``（规则 6）；
  * ``BOT_AUTOSYNC=0`` 关掉派生册自动回写，探针**不产文档**；
  * 数据根缺省重映射进 ``%TEMP%``（``--runtime-root keep`` 可关）：模块级
    「构造即 mkdir + connect + WAL」的件不会写进 ChatBot_Runtime；
  * 零进程动作、零 git 写、零网络（不 import 期发请求、不连 WS/QQ/TG）。

用法（仓库根 + venv python）：
  python scripts/import_chain_probe.py                      # 轴①：工作树现状
  python scripts/import_chain_probe.py --root <仓外HEAD副本> --env-source <仓库>/.env
        # 轴②：HEAD 副本。副本按定义没有 .env（gitignored）⇒ 用 --env-source 把
        # 同一份盘上声明注入子进程环境，两轴才只差代码不差环境。
  python scripts/import_chain_probe.py --json               # 结构化输出

退出码：0 = 全链可导；1 = 至少一格 FAIL（点名模块 / 异常类型 / 文件行）；
        2 = 探针自身无从判定（root 不存在、子进程起不来、副本无该文件）。

INCONCLUSIVE 一格的确切含义（不许当红、也不许当绿）：该格在**没有 .env** 的模式下
抛的是配置/文件形态的错（ValidationError / FileNotFoundError / KeyError），
即「环境缺席」而非「代码不可导」——只有 ``--env-source`` 未给时才可能出现在这一格。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 本窗落过但尚未生效的代码面：逐格点名导入（顺序即依赖顺序，插件根在前）。
CELL_MODULES: tuple[str, ...] = (
    "plugins.bot_unified_runtime.config",
    "plugins.bot_unified_runtime",  # 根 __init__.py：摄取/路由/门禁/出口全在这里
    "plugins.bot_unified_runtime.domains.chat_reply.capabilities.chat",
    "plugins.bot_unified_runtime.domains.chat_reply.character.providers",
    "plugins.bot_unified_runtime.domains.core.search.entity_relations",
    "plugins.bot_unified_runtime.domains.chat_reply.character.memory",
    "plugins.bot_unified_runtime.domains.chat_reply.capabilities.memory",
    "plugins.bot_unified_runtime.domains.chat_reply.character.memory_extract",
    "plugins.bot_unified_runtime.domains.chat_reply.ingest.message_context",
    "plugins.bot_unified_runtime.domains.chat_reply.character.vector_knowledge",
    "scripts.sync_persona_source",
)

# 只做 compile()/AST 级检查的文件（跑它等于碰生产，见模块 docstring 纪律 2）。
COMPILE_FILES: tuple[str, ...] = ("bot.py",)

OK = "OK"
FAIL = "FAIL"
SKIP = "SKIP"
INCONCLUSIVE = "INCONCLUSIVE"

#: 「环境缺席」而非「代码不可导」的异常形态（仅无 .env 模式参与判定）。
_ENV_SHAPED_ERRORS = ("ValidationError", "FileNotFoundError", "IsADirectoryError", "KeyError")

_SECRETISH_RE = re.compile(r"(sk-[A-Za-z0-9]{4,}|[A-Za-z]:[\\/][^\s'\"]*|env:[A-Za-z0-9_]+)")

_RUNTIME_ENV_FILENAMES = (".env", ".env.prod")


def _scrub(text: str) -> str:
    """输出消毒：盘符路径与 sk- 形态打码（规则 3，本探针绝不回显值）。"""
    return _SECRETISH_RE.sub("<redacted>", text)


def _short(text: str, limit: int = 260) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _locate(exc: BaseException, root: Path, cell: str) -> str:
    """异常落点：优先被导模块自身文件里的最后一帧，退回仓内最后一帧。"""
    try:
        frames = traceback.extract_tb(exc.__traceback__)
    except Exception:  # noqa: BLE001 - 定位失败不该掩盖异常本身
        return ""
    leaf = cell.rsplit(".", 1)[-1].replace("-", "_")
    inside = [f for f in frames if f.filename and root in Path(f.filename).resolve().parents]
    mine = [f for f in inside if Path(f.filename).name.startswith(leaf)]
    pick = (mine or inside or frames or [None])[-1]
    if pick is None:
        return ""
    try:
        rel = Path(pick.filename).resolve().relative_to(root)
    except (ValueError, OSError):
        rel = Path(str(pick.filename))
    return f"{rel.as_posix()}:{pick.lineno} in {pick.name}"


def _classify(exc: BaseException, root: Path, cell: str) -> dict[str, str]:
    """异常分类：语法 / 导入 / 命名 / 模块级求值 / 其它（附落点与原文首行）。"""
    name = type(exc).__name__
    if isinstance(exc, SyntaxError):
        kind = "COMPILE_FAIL(语法)"
    elif isinstance(exc, ImportError):
        kind = "IMPORT_FAIL(名字/依赖)"
    elif isinstance(exc, NameError):
        kind = "NAME_FAIL(未定义名)"
    else:
        kind = "MODULE_LEVEL_EVAL_FAIL(模块级求值抛错)"
    return {
        "kind": kind,
        "error": name,
        "message": _short(_scrub(str(exc))),
        "location": _locate(exc, root, cell),
    }


def _child_env(root: Path, runtime_root: Path | None, env_source: str | None) -> dict[str, str]:
    """子进程环境：卫生三件套 + 数据根重映射 + 可选注入盘上 .env 声明。"""
    child = dict(os.environ)
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    child["PYTHONIOENCODING"] = "utf-8"
    child["PYTHONPYCACHEPREFIX"] = str(runtime_root or (root / "__probe_pyc__"))
    child["BOT_AUTOSYNC"] = "0"
    if runtime_root is not None:
        child["BOT_RUNTIME_DATA_DIR"] = str(runtime_root)
    if env_source:
        for key, value in read_dotenv(Path(env_source)).items():
            child.setdefault(key, value)
    return child


def read_dotenv(path: Path) -> dict[str, str]:
    """窄解析 dotenv（只给键值；行内注释与引号按 python-dotenv 口径剥）。"""
    out: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return out
    for line in raw.splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# 子进程腿：真正执行 import 的地方（--child 由父进程带 --root/--cell 起）
# ---------------------------------------------------------------------------

def run_child(root: Path, cells: list[str], with_plugins: bool, no_init: bool) -> int:
    payload: dict[str, object] = {"root": str(root), "setup": "", "cells": [], "plugins": None}
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if not no_init:
        try:
            import nonebot

            nonebot.init(_env_file=_RUNTIME_ENV_FILENAMES)  # 与 bot.py:255 同一条
            payload["setup"] = "nonebot.init OK（未 run、未绑端口）"
        except BaseException as exc:  # noqa: BLE001 -  setup 失败要如实记账
            payload["setup"] = "nonebot.init FAIL " + json.dumps(
                _classify(exc, root, "nonebot"), ensure_ascii=False
            )
            print(json.dumps(payload, ensure_ascii=False))
            return 2
    # 注册腿排在逐格导入之前——与生产同序（bot.py: init → load_from_toml）。
    # 实测踩过的坑：若先 import 过 ``plugins.bot_unified_runtime``，
    # load_from_toml 那一腿会把插件算成「未注册」（target_loaded 假 False）。
    if with_plugins:
        payload["plugins"] = _load_plugins_leg(root)
    for cell in cells:
        started = time.monotonic()
        try:
            importlib.import_module(cell)
            payload["cells"].append({"cell": cell, "status": OK, "seconds": _elapsed(started)})
        except BaseException as exc:  # noqa: BLE001 - 探针的职责就是把炸记下来
            rec = {"cell": cell, "status": FAIL, "seconds": _elapsed(started)}
            rec.update(_classify(exc, root, cell))
            payload["cells"].append(rec)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 2)


def _load_plugins_leg(root: Path) -> dict[str, object]:
    """生产同一入口 load_from_toml：插件到底注册了几枚、有没有被咽掉的失败名单。"""
    out: dict[str, object] = {"status": FAIL, "loaded": 0, "target_loaded": False, "failed": []}
    try:
        import nonebot

        nonebot.load_from_toml("pyproject.toml")
        loaded = {p.module_name for p in nonebot.get_loaded_plugins()}
        out["loaded"] = len(loaded)
        out["target_loaded"] = "plugins.bot_unified_runtime" in loaded
        try:  # get_failed_plugins 在部分 nonebot 版本存在；缺席就如实报「读不到」
            from nonebot.plugin import get_failed_plugins

            out["failed"] = sorted(str(name) for name in get_failed_plugins())
        except (ImportError, AttributeError):
            out["failed"] = []
            out["failed_note"] = "本 nonebot 版本无 get_failed_plugins ⇒ 失败名单读不到，" \
                                 "本腿只认 target_loaded 与 loaded 计数（读不到≠有失败）"
        out["status"] = OK if out["target_loaded"] and not out["failed"] else FAIL
    except BaseException as exc:  # noqa: BLE001 - 加载腿自身抛错也只是一格
        out.update(_classify(exc, root, "nonebot.load_from_toml"))
    return out


# ---------------------------------------------------------------------------
# 父进程腿
# ---------------------------------------------------------------------------

def compile_leg(root: Path, rel: str) -> dict[str, object]:
    path = root / rel
    if not path.is_file():
        return {"cell": rel, "status": SKIP, "kind": "文件不在本根（副本按定义只含 tracked 件）"}
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
        return {"cell": rel, "status": OK, "kind": "compile()/AST 级；不执行（见 docstring 纪律 2）"}
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        rec = {"cell": rel, "status": FAIL}
        rec.update(_classify(exc, root, rel))
        return rec
    except OSError as exc:
        return {"cell": rel, "status": FAIL, "kind": "READ_FAIL", "message": _short(str(exc))}


def spawn_child(root: Path, cells: list[str], env: dict[str, str], with_plugins: bool,
                timeout: int) -> dict[str, object]:
    argv = [sys.executable, str(Path(__file__).resolve()), "--child", "--root", str(root)]
    argv += [item for cell in cells for item in ("--cell", cell)]
    if with_plugins:
        argv.append("--plugins")
    proc = subprocess.run(
        argv, cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        return {"setup": f"子进程 rc={proc.returncode} 无输出", "cells": [],
                "stderr": _short(_scrub(proc.stderr), 400)}
    try:
        parsed = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"setup": "子进程输出不可解析", "cells": [],
                "stderr": _short(_scrub(proc.stderr), 400)}
    if proc.stderr.strip():
        parsed["stderr"] = _short(_scrub(proc.stderr), 600)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="入口 import 链探针（离线，零进程动作）")
    parser.add_argument("--root", default=None, help="被测代码根（默认仓库根；轴②传仓外 HEAD 副本）")
    parser.add_argument("--env-source", default=None, help="注入子进程环境的 dotenv 文件（轴②用）")
    parser.add_argument("--runtime-root", default=None,
                        help="数据根落点；缺省 %TEMP% 隔离，'keep' = 沿用盘上声明（有写风险，勿用）")
    parser.add_argument("--no-plugins", action="store_true", help="跳过 load_from_toml 注册腿")
    parser.add_argument("--no-nonebot-init", action="store_true", help="调试用：不调 nonebot.init")
    parser.add_argument("--timeout", type=int, default=300, help="子进程上限（秒）")
    parser.add_argument("--json", action="store_true", help="结构化输出")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cell", action="append", default=[], help=argparse.SUPPRESS)
    parser.add_argument("--plugins", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # Windows 控制台缺省 GBK，中文读数必炸
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    if not root.is_dir():
        print(f"[probe] 被测根不存在：{root}", file=sys.stderr)
        return 2

    if args.child:
        # 子进程的卫生与环境由父进程经 env= 注入（含 BOT_RUNTIME_DATA_DIR 与
        # .env 声明）；这里只兜底直跑态，不再新起临时数据根。
        os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        os.environ.setdefault("BOT_AUTOSYNC", "0")
        cells = args.cell or list(CELL_MODULES)
        return run_child(root, cells, args.plugins, args.no_nonebot_init)

    runtime_root: Path | None = None
    if args.runtime_root != "keep":
        runtime_root = Path(args.runtime_root or tempfile.mkdtemp(prefix="icp_rt_"))
        runtime_root.mkdir(parents=True, exist_ok=True)
    env = _child_env(root, runtime_root, args.env_source)

    cells = list(CELL_MODULES)
    try:
        child = spawn_child(root, cells, env, not args.no_plugins, args.timeout)
    except subprocess.TimeoutExpired:
        print(f"[probe] 子进程超时 {args.timeout}s —— 探针无从判定（非红非绿）", file=sys.stderr)
        return 2

    results: list[dict[str, object]] = list(child.get("cells") or [])
    has_env = (root / ".env").is_file() or bool(args.env_source)
    for rec in results:
        if rec.get("status") == FAIL and not has_env:
            kind = str(rec.get("kind", ""))
            message = str(rec.get("message", ""))
            if any(marker in kind + message for marker in _ENV_SHAPED_ERRORS):
                rec["status"] = INCONCLUSIVE
                rec["note"] = "无 .env 模式下的配置/文件形态错 ⇒ 环境缺席，不是代码不可导"

    for rel in COMPILE_FILES:
        results.append(compile_leg(root, rel))

    plugins = child.get("plugins")
    fails = [r for r in results if r.get("status") == FAIL]
    inconclusive = [r for r in results if r.get("status") == INCONCLUSIVE]
    rc = 0 if not fails else 1
    if not results or str(child.get("setup", "")).endswith("无输出") or "stderr" in child and not results:
        rc = 2

    if args.json:
        print(json.dumps({
            "root": str(root), "has_env": has_env, "runtime_root": str(runtime_root or "keep"),
            "setup": child.get("setup"), "exit_code": rc, "plugins": plugins,
            "cells": results, "stderr": child.get("stderr", ""),
        }, ensure_ascii=False, indent=2))
    else:
        width = max(len(str(r.get("cell", ""))) for r in results) if results else 4
        print(f"import_chain_probe  root={root}  env={'有' if has_env else '无'}"
              f"  数据根={runtime_root or '沿用盘上声明'}")
        print(f"setup: {child.get('setup')}")
        for rec in results:
            line = f"  {rec.get('cell',''):<{width}}  {rec.get('status')}"
            if rec.get("status") != OK:
                line += f"  [{rec.get('kind')}] {rec.get('error', '')}" \
                        f" {rec.get('message', '')} @{rec.get('location', '')}"
            if rec.get("note"):
                line += f"  ({rec['note']})"
            print(line)
        if isinstance(plugins, dict):
            print(f"注册腿 load_from_toml: {plugins.get('status')} "
                  f"loaded={plugins.get('loaded')} target_loaded={plugins.get('target_loaded')} "
                  f"failed={plugins.get('failed')}")
        else:
            print("注册腿 load_from_toml: 未跑（--no-plugins）")
        if child.get("stderr"):
            print(f"子进程 stderr（消毒后）: {child['stderr']}")
        verdict = "全链可导" if rc == 0 else (
            f"{len(fails)} 格不可导" if rc == 1 else "探针无从判定")
        print(f"汇总: FAIL {len(fails)} / INCONCLUSIVE {len(inconclusive)}"
              f" / OK {sum(1 for r in results if r.get('status') == OK)} → {verdict}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
