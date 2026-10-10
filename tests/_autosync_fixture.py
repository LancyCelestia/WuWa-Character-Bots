"""Real, copy-only inputs for autosync integration tests (no Git/Runtime/.env)."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import _AUTOSYNC_STEPS as GENERATORS
from verify_hashes import TRACKED_FILES

from scripts.command_catalog import (
    ALIASES_SOURCE,
    ECHO_SOURCE,
    HELP_LITERAL_PROJECTIONS,
    ROUTER_SOURCE,
    _module_import_targets,
    _module_tree,
)
from scripts.command_catalog import ROOT as CATALOG_ROOT

#: 生成器里唯一会查「import 解析面」的求值口＝`_literal_assign`，它吃三份真身源
#: （echo 的帮助注册表三件 / base_router 的内部路由注记 / aliases 的动词表）。
#: 这三份必须逐字在场：既是被解析的对象，也是投影宿主的**出发点**。
_LITERAL_SOURCES: tuple[Path, ...] = (ECHO_SOURCE, ROUTER_SOURCE, ALIASES_SOURCE)


def projection_host_modules() -> set[str]:
    """在册纯投影的**宿主模块**（仓相对 posix 路径），尺取自生成器真身、递归到不动点。

    为什么必须由本夹具铺进镜像（台账 #74「门瞎」原形，此处记全）：
    `scripts/command_catalog.py::_module_import_targets` 只把
    「`from plugins.… import 名字` 且宿主 `.py` 文件**在盘真实存在**」的名字放进解析面，
    `_eval_projection_call` 判「名字不在解析面」＝当场 `ValueError`。骨架镜像原先只铺
    `aliases.py` 一份宿主；F-13 乙案批 3（`db1e7a6a`）给 echo.py 又加了两枚在册投影
    （`host_state_trigger_words`／`media_archive_trigger_words`），宿主在镜像外 ⇒
    生成器 `--write` 必崩 ⇒ `autosync_repo` 夹具 setup 直接 ERROR ⇒ 四枚用例**一条断言都没跑到**，
    而这枚「自动同步一致性」门在全量读数里仍显示「1 passed」＝看着像绿的瞎门。

    本函数**不自造第二份名单**（自造＝又一处会漂的清单，正是本次要治的病）：
    投影名取自真身注册表 `HELP_LITERAL_PROJECTIONS`，宿主路径取自真身的 import 解析腿；
    将来再登记新投影、或宿主自己转述别模块的投影，镜像自动跟着补齐，无需回来改这里。
    """
    out: set[str] = set()
    seen: set[Path] = set()
    pending = list(_LITERAL_SOURCES)
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for name, (host, _original) in _module_import_targets(_module_tree(path)).items():
            if name not in HELP_LITERAL_PROJECTIONS:
                continue
            out.add(host.relative_to(CATALOG_ROOT).as_posix())
            pending.append(host)
    return out


def copy_autosync_repo(source: Path, destination: Path) -> Path:
    """Copy real scripts, guards and generator inputs, preserving test-file counts."""
    source = source.resolve()
    destination = destination.resolve()
    assert destination != source and not destination.is_relative_to(source)
    assert CATALOG_ROOT == source, (
        f"投影宿主按 {CATALOG_ROOT} 解析，却要从 {source} 拷件＝生成器根与镜像根不同轴，"
        "铺出来的件是真的却对不上号"
    )
    paths = {
        "tests/conftest.py",
        "tests/_autosync_fixture.py",
        "plugins/bot_unified_runtime/config.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py",
        "plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py",
        *TRACKED_FILES,
        *(script for script, _ in GENERATORS),
        *(output for _, output in GENERATORS),
        *projection_host_modules(),
    }
    # doc_sync counts all test_*.py and template names, not just collected tests.
    for pattern in (
        "tests/test_*.py",
        "plugins/bot_unified_runtime/domains/render/card_render/templates/*.html",
    ):
        paths.update(path.relative_to(source).as_posix() for path in source.glob(pattern))
    for name in sorted(paths):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return destination
