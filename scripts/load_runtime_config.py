"""load_runtime_config — .env 配置装载唯一入口（生产同构；M-68 收口）.

背景（T29 M-68 / T24 P1-5）：.env 装载语义曾四套并存且与生产不同构——
生产 dotenv（bot.py:255 ``nonebot.init(_env_file=(".env",".env.prod"))``，
真身解析器 = nonebot/config.py ``DotEnvSettingsSource``）vs smoke 装载
（``domains/ops/smoke/smoke.py`` 单文件/不剥行内注释/看不见 .env.prod）
vs ``pre_restart_check.load_env`` 第三套 vs ``verify_chatbot_env`` 第四套。
实测后果：``0.05  # 注释`` 好配置被体检器假红、``.env.prod`` 覆盖假绿。

本模块把「读哪些文件、怎么解析、优先级、JSON 解码、Config 构建」收敛为
单一真身，与生产逐键同构（同库 python-dotenv、同 utf-8 编码、同 environ
优先、同 extras JSON 解码语义），生产语义由
``tests/test_runtime_config_loader.py::test_parity_with_nonebot_dotenv_source``
用 nonebot 自带 ``DotEnvSettingsSource`` 逐键 + Config.model_dump 对拍锁死。

解析语义（=生产 bot.py:255 链）：
  1. 逐文件 python-dotenv ``dotenv_values(path, encoding="utf-8")``，
     后者覆盖前者；缺文件静默跳过（与生产一致，严格模式见 required）。
  2. os.environ 覆盖文件值（键大小写不敏感，与生产
     ``_parse_env_vars`` 全小写对撞同效）；仅覆盖文件中出现的键——
     生产 extras 只从文件取，environ-only 键不入配置。
  3. extras JSON 解码 = nonebot extras 语义：非空值尝试
     ``json.loads(value.strip())``，成功取解码值，失败/空回退原串。
     （真实 .env 实测 198 处裸标量 ``true``/``2097152``/``0.4`` 生产即此
     语义装载；smoke 旧版只解 ``{``/``[`` 开头是第三套分歧，本入口已收编。）
  4. ``translate_env_keys`` → ``Config.model_validate``（懒加载 plugins，
     零行为变更：与生产 ``Config.model_validate(translate_env_keys(
     driver_config.model_dump()))`` 在 Config 层逐字段等价，测试锁死）。

分工（四消费方，禁再各造装载器）：
  - 生产 bot.py   ：nonebot.init 真身（本入口与它对拍同构，不替换它）。
  - 重启门        ：scripts/pre_restart_check.py（值层 load_runtime_env_values）。
  - 手动快查      ：scripts/verify_chatbot_env.py（值层 + config 层）。
  - 冒烟/控制台   ：domains/ops/smoke/smoke.py load_smoke_config（config 层）。

用法：
    from scripts.load_runtime_config import load_runtime_config
    cfg = load_runtime_config()                       # 仓库根 .env + .env.prod
    cfg = load_runtime_config((root / ".env",), required=False)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

# 仓库根由本文件位置自证（scripts/ 的父目录）；缺省 env 文件锚在这里，
# 与运行时 CWD 解耦（bot.py 生产从仓库根跑，二者一致）。
REPO_ROOT = Path(__file__).resolve().parents[1]

#: 生产 bot.py:255 的文件序：.env → .env.prod，后者覆盖。
DEFAULT_ENV_FILES: tuple[str, ...] = (".env", ".env.prod")

#: 生产 nonebot BaseSettings env_file_encoding="utf-8"（nonebot/config.py）。
ENV_FILE_ENCODING = "utf-8"


class RuntimeEnvError(RuntimeError):
    """装载入口的结构性错误（如严格模式下 env 文件全缺）。"""


class RuntimeEnvNotFoundError(RuntimeEnvError):
    """required=True 时请求的 env 文件一个都不存在——拒绝静默回退全默认."""


@dataclass(frozen=True)
class LoadedEnv:
    """一次装载的结果：键值对 + 实际参与的文件（供指纹回显/判定）."""

    values: dict[str, str]
    files: tuple[Path, ...]


def resolve_env_files(
    env_files: Sequence[str | Path] = DEFAULT_ENV_FILES,
    root: str | Path | None = None,
) -> tuple[Path, ...]:
    """把请求的 env 文件名解析为绝对路径；相对名锚 root（缺省=仓库根）."""

    def _resolve_one(name: str | Path) -> Path:
        path = Path(name)
        if path.is_absolute():
            return path
        base = Path(root).resolve() if root is not None else REPO_ROOT
        return base / path

    return tuple(_resolve_one(name) for name in env_files)


def load_runtime_env_values(
    env_files: Sequence[str | Path] = DEFAULT_ENV_FILES,
    *,
    root: str | Path | None = None,
    required: bool = False,
) -> LoadedEnv:
    """值层：生产同构解析，返回原始字符串键值（未 JSON 解码）.

    语义见模块 docstring §1-§2。required=True 且文件全缺时抛
    RuntimeEnvNotFoundError（缺文件即错）；缺省 False（生产 dotenv 对
    缺文件即静默跳过，调用方按需收紧）。
    """
    paths = resolve_env_files(env_files, root)
    values: dict[str, str] = {}
    files: list[Path] = []
    for path in paths:
        if not path.is_file():
            continue
        files.append(path)
        parsed = dotenv_values(path, encoding=ENV_FILE_ENCODING)
        for key, value in parsed.items():
            if value is None:  # 无 `=` 的裸键行：生产装成 None 后无任何消费方，按缺失处理
                continue
            values[str(key)] = value
    # os.environ 覆盖（键大小写不敏感——生产 _parse_env_vars 全小写对撞同效）。
    environ: dict[str, str] = {k.upper(): v for k, v in os.environ.items()}
    for key in values:
        override = environ.get(key.upper())
        if override is not None:
            values[key] = override.strip()
    if required and not files:
        raise RuntimeEnvNotFoundError(
            f"未找到任何 env 文件：{', '.join(str(p) for p in paths)}——"
            "拒绝静默回退全默认配置（T24 P1-3 假安心形态）"
        )
    return LoadedEnv(values=values, files=tuple(files))


def json_decode_env_values(values: Mapping[str, str]) -> dict[str, Any]:
    """JSON 解码层 = nonebot extras 语义（nonebot/config.py extras 循环）.

    非空值尝试 ``json.loads(value.strip())``：成功取解码值（含裸标量，
    生产对 ``true``/``2097152``/``0.4`` 即此装载）；失败或空值回退原串。
    """
    decoded: dict[str, Any] = {}
    for key, value in values.items():
        text = value.strip() if value else ""
        if text:
            try:
                decoded[key] = json.loads(text)
                continue
            except ValueError:
                pass
        decoded[key] = value
    return decoded


def config_from_env_values(values: Mapping[str, str]) -> Any:
    """Config 层：JSON 解码 → translate_env_keys → Config.model_validate.

    与生产 ``Config.model_validate(translate_env_keys(driver_config
    .model_dump()))`` 同一条校验链（plugins/bot_unified_runtime/__init__.py）；
    plugins 懒加载，值层消费方（pre_restart 等）零包导入成本。
    """
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from plugins.bot_unified_runtime.config import Config, translate_env_keys

    return Config.model_validate(translate_env_keys(json_decode_env_values(dict(values))))


def load_runtime_config(
    env_files: Sequence[str | Path] = DEFAULT_ENV_FILES,
    *,
    root: str | Path | None = None,
    required: bool = True,
) -> Any:
    """唯一入口：读 env 文件 → 生产同构解析 → 返回生产 pydantic Config.

    缺省 required=True（缺文件即错）；传 required=False 对齐生产 dotenv
    的缺文件静默跳过。只读，零进程环境副作用（不向 os.environ 注入）。
    """
    loaded = load_runtime_env_values(env_files, root=root, required=required)
    return config_from_env_values(loaded.values)
