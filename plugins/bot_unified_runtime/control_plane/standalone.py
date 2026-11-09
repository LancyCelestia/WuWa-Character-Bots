"""独立控制面 CLI（W2/W8）：显式配置引用、默认不监听、独立写 fail-closed。

设计口径（与操作包第 4 条逐条对应）
----
- **不读 dotenv**：配置只来自①``--config-file`` 指向的显式 JSON 文件、②调用方显式传入的
  ``environ`` 映射、③命令行开关。绝不 import/解析 ``.env``，也不去 ``ChatBot_Runtime``
  取生产配置——独立面板与 Bot 解耦，面板挂掉不该牵动业务。
- **默认不监听**：``enabled`` 缺省 False；关闭态直接返回 0，不建 app、不 bind。
- **loopback 安全**：host 缺省 ``127.0.0.1``；非环回地址仍由 ``_app.serve`` 的确认文件门
  拦（本模块不重复那套判定，只把显式值透传）。
- **独立写 fail-closed**：standalone 模式（无 bot 消费者）默认 ``allow_direct_config_write=False``
  ⇒ HTTP 写腿必须走命令面；``embedded`` 模式（Bot 宿主内）保持旧直写。
- **库路径必须显式绝对**（父裁 B，2026-10-15）：``BOT_CONTROL_PLANE_CONFIG_DB`` 相对值一律
  拒（非零退出、不建库）；命令库与布局库由**同一枚 canonical 绝对路径**建，不按 cwd 解析、
  不 import ``runtime_paths``、不读 dotenv。
- **mode 参数不新增无注册键**：模式是命令行开关，不是新的 ``BOT_*`` 配置键。

测试只注入 ``app_factory``/``serve_fn`` 假件；本模块自身不启动真实服务。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any

__all__ = ["build_config", "load_explicit_config", "main", "run"]

_MODES = ("standalone", "embedded")

#: 父裁 B（2026-10-15）：面板命令/布局库必须显式**绝对**路径。相对值会被面板按自身
#: cwd 解析，而 Bot 侧的 `bot_control_plane_config_db` 经 `PATH_REMAPPED_FIELDS`
#: 折进 `ChatBot_Runtime` ⇒ 两本库静默分裂（命令永不被消费、布局永不被渲染）。
#: 故相对值一律 fail-closed；本模块**不**调用 `runtime_paths`、**不**读 dotenv。
_RELATIVE_DB_EXIT_CODE = 2
_ABSOLUTE_DB_GUIDANCE = (
    "面板命令库需要显式绝对路径：请把 BOT_CONTROL_PLANE_CONFIG_DB 设为绝对路径"
    "（相对路径会被拒绝——面板与 Bot 会各自按 cwd 解析到不同库，命令与布局将无法共享）。"
)


def _flag(raw: object) -> bool | None:
    # 布尔字面量词集的唯一真身在 `domains/core/config/config_readiness.py`（F-13 乙案批 1
    # 落位；同型先例＝本包 `__init__.py::_flag_value`）。这里**函数内**导入：本模块顶层
    # 刻意不引域内件（独立面板进程零导入副作用）。三态判定的**逻辑**照旧自持，
    # 只把撞词面的字集收成一处；判定语义逐格不变。
    from plugins.bot_unified_runtime.domains.core.config.config_readiness import (
        ENV_FALSE_WORDS,
        ENV_TRUE_WORDS,
    )

    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ENV_TRUE_WORDS:
        return True
    if text in ENV_FALSE_WORDS:
        return False
    return None


def load_explicit_config(
    config_file: str | Path | None, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """只认显式文件 + 显式环境映射；返回 ``{lowercase_key: value}``。

    文件缺省 ⇒ 只用 ``environ``；两者都给 ⇒ 文件为准、环境补齐。**绝不读 .env**。
    """
    values: dict[str, Any] = {}
    source = dict(environ or {})
    for name, raw in source.items():
        if name.startswith("BOT_"):
            values[name.lower()] = raw
    if config_file is None:
        return values
    path = Path(config_file).expanduser()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("显式配置文件必须是 JSON 对象")
    for name, raw in payload.items():
        values[str(name).strip().lower()] = raw
    return values


def build_config(
    config_file: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> SimpleNamespace:
    """构造 getattr 防御式配置对象（与 ``control_plane_settings`` 的读取口径同形）。"""
    values = load_explicit_config(config_file, environ=environ)
    for name, raw in (overrides or {}).items():
        if raw is not None:
            values[str(name).lower()] = raw
    return SimpleNamespace(**values)


def _default_app_factory(
    config: object,
    *,
    gateway: Any,
    allow_direct_write: bool,
    visual_service: Any = None,
    standalone: bool = True,
) -> Any:
    """装配 app：把命令网关、直写开关与共享布局服务**真的**交给工厂。

    刻意**不做**签名探测式省略——父工厂缺参数就该当场 `TypeError`（装配期失败），
    绝不允许「参数对不上就悄悄退回直写」那种静默放宽。

    ``standalone``：独立面板必为 True——`_app` 据此对 audit/actions/metrics/
    settings 等一切**隐式持久化 resolver** 与相对路径值 fail-closed（无显式绝对
    路径即让服务缺席，写腿 503 诚实拒），不再猜 Runtime 落点、不读 dotenv。
    Bot 宿主（embedded）不传本标志，走 ``runtime_attached=True`` 的 legacy 面。
    """
    from ._app import create_control_plane_app

    return create_control_plane_app(
        config,
        config_command_gateway=gateway,
        allow_direct_config_write=allow_direct_write,
        visual_service=visual_service,
        standalone=standalone,
    )


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="control_plane", add_help=True)
    parser.add_argument("--config-file", default=None, help="显式 JSON 配置文件路径（不读 .env）")
    parser.add_argument("--enabled", default=None, help="总开关（缺省关；true/false）")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", default=None)
    parser.add_argument("--mode", default="standalone", choices=_MODES)
    parser.add_argument("--allow-direct-write", default=None, help="仅 embedded 语义；独立面默认禁直写")
    return parser.parse_args(argv)


def run(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    app_factory: Callable[..., Any] | None = None,
    serve_fn: Callable[[Any, str, int], int] | None = None,
    stdout: Any = None,
) -> int:
    """CLI 主体；返回退出码。测试注入 ``app_factory``/``serve_fn`` 假件，不真起服务。"""
    out = sys.stdout if stdout is None else stdout
    args = _parse(list(sys.argv[1:] if argv is None else argv))
    source_environ = os.environ if environ is None else environ
    config = build_config(
        args.config_file,
        environ=source_environ,
        overrides={
            "bot_control_plane_enabled": _flag(args.enabled),
            "bot_control_plane_host": args.host,
            "bot_control_plane_port": int(args.port) if args.port is not None else None,
        },
    )
    from . import control_plane_settings

    settings = control_plane_settings(config)
    if not settings.enabled:
        print("控制面未启用（--enabled 未开或配置为关），不监听。", file=out)
        return 0
    # 父裁 B：面板库必须显式**绝对**路径（相对值 ⇒ fail-closed，不按 cwd 另建库）。
    # 本模块不 import ``scripts.runtime_paths``、不读 dotenv：面板与 Bot 解耦。
    db = str(getattr(config, "bot_control_plane_config_db", "") or "").strip()
    if db and not Path(db).expanduser().is_absolute():
        print(_ABSOLUTE_DB_GUIDANCE, file=out)
        return _RELATIVE_DB_EXIT_CODE
    canonical_db = Path(db).expanduser().resolve() if db else None
    # 非环回地址的准入门**不在这里判第二次**：那套判定（公网确认文件）唯一住在
    # ``_app.serve``。本模块只保证「默认 host 是环回」这一条，显式非环回仍由
    # ``_serve`` 的确认文件门拦（禁第二判据漂移）。
    allow_direct_write = _flag(args.allow_direct_write)
    if allow_direct_write is None:
        allow_direct_write = args.mode == "embedded"
    gateway = None
    visual_service = None
    if args.mode == "standalone" and canonical_db is not None:
        # 独立面板也挂命令面：写腿变成提交（需要 bot 消费者执行），不共享库即写成功。
        from .config_commands import ConfigCommandGateway, SQLiteConfigCommandStore
        from .visual_layouts import VisualLayoutService, VisualLayoutStore

        gateway = ConfigCommandGateway(SQLiteConfigCommandStore(canonical_db))
        # 命令库与布局库**同一枚 canonical 路径**（父裁 B：不另造第二个布局 store）。
        visual_service = VisualLayoutService(VisualLayoutStore(canonical_db))
    # 独立面标志由 CLI 单点判定：默认工厂用 ``functools.partial`` 预绑（把
    # ``standalone`` 沿到 ``_app``）；调用方注入的 ``app_factory`` 保持既有签名，
    # 不被追加新 kwarg（避免静默改变其契约）。
    if app_factory is not None:
        factory = app_factory
    else:
        factory = partial(_default_app_factory, standalone=args.mode == "standalone")

    def build_app() -> Any:
        # 零参延迟构造：交给 ``_serve`` 在**通过 host 审批之后**才调用，
        # 保证「先 gate 后建 app」，且只构造一次（不重复两构造）。
        return factory(
            config,
            gateway=gateway,
            allow_direct_write=allow_direct_write,
            visual_service=visual_service,
        )

    if serve_fn is not None:
        return int(serve_fn(build_app(), settings.host, settings.port))
    # 真实路径沿用 ``_app.serve``（含公网确认文件门，唯一权威）；把**已带网关**的
    # 构造器交进去，避免 ``_serve`` 自己再造一个丢了网关/直写开关的 app。
    from ._app import serve as _serve

    return int(_serve(config, app_factory=build_app))


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover - 手动入口
    raise SystemExit(main())
