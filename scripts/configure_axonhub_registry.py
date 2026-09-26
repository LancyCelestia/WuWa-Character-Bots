"""Configure axonhub as the unified model gateway (user request).

2026-09-24 凭据处置（CM-P-52 真债 / RULINGS-20260924 第 12 项「脚本改读 .env」，S139 波）：
本脚本对 ``.env`` **只读**——不再向 `.env` 回写任何一行，文件内也不再含任何凭据值字面量。
网关 key 只从环境变量或 `.env` 既有行**读判在位**；两处皆无/空值 ⇒ 显式报错、退出码 3
（绝不写回、绝不打印值）。key 的轮替与落进 `.env` 是管理员动作。BOT_CHAT_MODEL /
BOT_CHAT_BASE_URL 经 runtime settings 的 ``overrides`` 传导（`apply_config_batch.py` 同源，
优先于 `.env` 同名条目）。

Writes:
  * runtime settings JSON -> `model_registry` + `overrides`（现役真身，覆盖 .env）

Only model id / base_url / key *slot name* are printed — never key values.

⚠ 本脚本**整段覆写**注册表条目，因此能力标签（`native-audio`/`native-video`/
`native-animation`）不在下面的表里抄第二份：那张表由
`domains/core/channel_capability_tags.py` 唯一在册，`tags_for()` 装配时合成，
`capability_guard_problems()` 在落盘前复查——落不了地就 EXIT 2 拒写（T4 路①）。

Usage:  python scripts/configure_axonhub_registry.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"
RUNTIME_SETTINGS = Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\settings"
    r"\runtime_settings_shorekeeper.json"
)
BACKUP_DIR = Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\backups"
)

AXONHUB_BASE_URL = "http://127.0.0.1:8090/v1"
AXONHUB_KEY_SLOT = "BOT_API_KEY_AXONHUB"
# 凭据值字面量已摘除（S139 波；旧值仍在 git 历史，裁定 12「不改史」，轮替＝管理员）。
# 本脚本只经 resolve_key_presence() 读判「在不在」，值绝不进任何输出/写回面。

DEFAULT_MODEL = "gemini-3.8-flash"

# ---------------------------------------------------------------- axonhub 条目
# 说明：本网关对模型名**大小写敏感**且大小写行为不一致（实测）：
#   gemini-3.8-flash        ✅ 200   |  Gemini-3.8-Flash        ❌ 503
#   gemini-3.8-flash-high   ✅ 200   |  Gemini-3.8-Flash-High   ❌ 503
#   gpt-5.6-terra           ❌ 超时  |  GPT-5.6-Terra           ✅ 200
# 因此下面逐条用**实测可用的那个拼写**。同渠道的两种拼写都登记，交给故障转移兜。
AXONHUB_ROUTES: list[tuple[str, str, list[str], int]] = [
    # (entry_id, model, tags, priority)
    # ⚠ tags 这一列**只写档位/模态标签**（low/high/max/vision/text-only…）。
    # 能力标签 `native-audio`/`native-video`/`native-animation` 一律不在这里写：
    # 它们的唯一真身是
    # `plugins/bot_unified_runtime/domains/core/channel_capability_tags.py`
    # 的 `CHANNEL_CAPABILITY_KINDS`，由 `tags_for()` 在装配条目时合成补上。
    # 之前这里抄了一份，重跑 `--apply` 就把运行时的三枚能力标签整批抹掉——
    # 抹掉不报错、不写日志，只是媒体理解静默退回 ASR/抽帧/拼静态条（S28 现算路①）。
    # 写回前还有 `capability_guard_problems()` 一道闸兜底（路①的保险）。
    ("axon-gemini-38-flash", "gemini-3.8-flash", ["low", "high", "max", "vision"], 1),
    ("axon-gemini-38-flash-high", "gemini-3.8-flash-high", ["high", "max", "vision"], 2),
    # 轻量档：快速、便宜，适合短回复
    ("axon-glm-53-flash", "glm-5.3-flash", ["low", "fast"], 10),
    ("axon-gemini-38-flash-caps", "Gemini-3.8-Flash", ["high", "max", "vision"], 11),
    ("axon-gemini-38-flash-high-caps", "Gemini-3.8-Flash-High", ["high", "max", "vision"], 12),
    # 中档
    ("axon-deepseek-v41-flash", "DeepSeek-V4.1-Flash", ["low", "high", "text-only"], 20),
    ("axon-deepseek-v41-flash-lc", "deepseek-v4.1-flash", ["low", "text-only"], 21),
    ("axon-glm-53", "glm-5.3", ["high", "text-only"], 22),
    ("axon-qwen35-9b", "Qwen3.5-9B", ["low", "fast", "text-only"], 23),
    # 高档
    ("axon-gpt-56-terra", "GPT-5.6-Terra", ["high", "max", "text-only"], 30),
    ("axon-gpt-56-sol", "gpt-5.6-sol", ["high", "max", "text-only"], 31),
    ("axon-gpt-56-luna", "gpt-5.6-luna", ["low", "fast", "text-only"], 32),
    ("axon-gpt-6-astra", "gpt-6-astra", ["high", "max", "text-only"], 33),
    ("axon-grok-46", "grok-4.6", ["high", "text-only"], 34),
    ("axon-claude-sonnet-5", "claude-sonnet-5", ["high", "max", "text-only"], 35),
    ("axon-claude-opus-5", "claude-opus-5", ["high", "max", "text-only"], 36),
    ("axon-claude-fable-5", "claude-fable-5", ["high", "text-only"], 37),
]

# DeepSeek 兜底：网关失败时直连官方（key 槽位已存在）
DEEPSEEK_FALLBACK: list[tuple[str, str, list[str], int]] = [
    ("ds-official-flash", "deepseek-v4-flash", ["low", "high", "max", "text-only"], 900),
]


# 能力标签声明源（AST 读取，不 import 插件根：见该件 docstring）
# CM-P-9（S44）：本脚本的眼睛 = scripts/channel_capability_declaration.load_declaration——
# 「追再导出 + 空表必抛」落在该件里，本文件**不自建第二套解析**（禁第二真身）；
# 声明源降为"从册再导出"的薄壳后，tags_for()/闸照常工作。下面另加本件自己的塌陷锁：
# 闸的判据来自声明，读空 ⇒ 闸变橡皮图章（S28 抹标签事故形），必须当场停。
try:
    from scripts.channel_capability_declaration import (
        declaration_path,
        load_declaration,
    )
except ImportError:  # 直跑态 sys.path[0]=scripts/：补仓库根后重试
    sys.path.insert(0, str(REPO))
    from scripts.channel_capability_declaration import (
        declaration_path,
        load_declaration,
    )


def _declaration():
    return load_declaration(REPO)


def tags_for(entry_id: str, tier_tags: list[str]) -> list[str]:
    """本脚本写回某条目时使用的 tags = 表里的档位标签 + 声明源的能力标签.

    能力标签**不来自本文件的任何字面量**——这就是"消除第二张表"的落点：本表漏抄
    不再等于当场摘掉，因为本表根本不负责那一列。
    """
    declared = load_declaration(REPO).required_tags_for(entry_id)
    merged: list[str] = []
    seen: set[str] = set()
    for tag in [*tier_tags, *declared]:
        key = str(tag).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(tag)
    return merged


class DeclarationBlindError(RuntimeError):
    """塌陷锁（CM-P-9）：能力标签声明被读成「零枚必带标签」⇒ 闸失去判据.

    抛而不是返回空问题列表：``capability_guard_problems`` 的循环对空声明面**恒零问题**，
    「没有需要保护的标签」与「眼睛瞎了读不到标签」两形不可分辨——S28 那次
    ``--apply`` 抹光三枚能力标签还报成功，正是从这条缝里走的。
    """


def capability_guard_problems(registry: dict) -> list[str]:
    """写回前的闸：每条在册能力声明都必须能在待写注册表里找到 carrying 它的条目.

    返回人话问题列表（空 = 放行）。点名渠道 id 与缺失标签字面量，绝不点名密钥。
    判据与体检项、与运行时门同源（都走声明源的 `required_tags_for`）。
    声明面读空（无条目、或所有条目必带标签皆零枚）⇒ 抛 ``DeclarationBlindError``
    并点名声明文件与表名，绝不放行。
    """
    declaration = _declaration()
    declared = declaration.declared_entry_ids()
    if not declared or not any(declaration.required_tags_for(entry_id) for entry_id in declared):
        raise DeclarationBlindError(
            "塌陷锁：能力标签声明读为零枚必带标签——"
            f"真身 = {declaration_path(REPO)} 的 CHANNEL_CAPABILITY_KINDS"
            "（空表已由读取口拒绝，能走到这里的形态是『所有行都被清空』）；"
            "继续写回 = 能力标签整批静默蒸发（S28 事故形），停手"
        )
    problems: list[str] = []
    for entry_id in declaration.declared_entry_ids():
        required = declaration.required_tags_for(entry_id)
        if not required:
            continue
        entry = registry.get(entry_id)
        if entry is None:
            problems.append(
                f"{entry_id} 在册声明了 {'、'.join(required)}，但待写注册表里没有这条渠道"
                "——写回后原生媒体能力将无处生效（静默退回转译）"
            )
            continue
        tags = {str(tag).strip().lower() for tag in entry.get("tags") or ()}
        missing = [tag for tag in required if tag.lower() not in tags]
        if missing:
            problems.append(
                f"{entry_id} 缺能力标签 {'、'.join(missing)}（在册要求 {'、'.join(required)}）"
                "——能力标签消失不报错、不写日志，只会让媒体理解静默降级"
            )
    return problems


def build_registry() -> dict:
    registry: dict[str, dict] = {}
    for entry_id, model, tier_tags, priority in AXONHUB_ROUTES:
        registry[entry_id] = {
            "model": model,
            "base_url": AXONHUB_BASE_URL,
            "api_key": f"env:{AXONHUB_KEY_SLOT}",
            "group": "axonhub",
            "tags": tags_for(entry_id, tier_tags),
            "priority": priority,
            "price_in": 0.0,
            "price_out": 0.0,
            "source": "axonhub",
        }
    return registry


def read_env_assignments() -> dict[str, str]:
    """只读解析 `.env` 为 {key: 原值}；本脚本对 `.env` 零写入。

    结果只用于「在位检查」：凭据的值绝不进打印/日志/写回面（CM-P-52 真债的处置口径）。
    文件不存在返回空表——由零命中报错统一兜住，不在这里猜路径。
    """
    if not ENV_PATH.exists():
        return {}
    table: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        table.setdefault(key.strip(), value.strip())
    return table


def _env_value_non_empty(raw: str) -> bool:
    return bool(raw.strip('"').strip("'").strip())


def resolve_key_presence() -> str | None:
    """凭据从哪读到的：``"environment"`` / ``".env"``；零命中返回 ``None``。

    先查 os.environ（装配时真身），再查 `.env` 非注释非空行。**只判在不在，
    绝不把值带回调用方**——所以返回的是来源名而不是值。
    """
    if os.environ.get(AXONHUB_KEY_SLOT, "").strip():
        return "environment"
    if _env_value_non_empty(read_env_assignments().get(AXONHUB_KEY_SLOT, "")):
        return ".env"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    changes: list[str] = []

    # .env 只读（CM-P-52 处置，裁定 12）：只核对在位情况，绝不回写任何一行。
    # BOT_CHAT_MODEL / BOT_CHAT_BASE_URL 改由下面 runtime overrides 传导（同源、优先于 .env）。
    env_state = read_env_assignments()
    if "BOT_MODEL_REGISTRY" in env_state:
        changes.append(
            ".env  BOT_MODEL_REGISTRY 仍在（只读检查；真身已迁 runtime store，"
            "本脚本不再代删，管理员可自行移除该行）"
        )
    for key in ("BOT_CHAT_MODEL", "BOT_CHAT_BASE_URL", AXONHUB_KEY_SLOT):
        changes.append(
            f".env  read-only presence: {key} = "
            + ("present" if _env_value_non_empty(env_state.get(key, "")) else "absent")
        )

    settings = json.loads(RUNTIME_SETTINGS.read_text(encoding="utf-8"))
    registry = settings.get("model_registry") or {}
    if not isinstance(registry, dict):
        registry = {}
    before = len(registry)
    registry.update(build_registry())
    registry.update({k: v for k, v in {
        "ds-official-flash": {
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "env:BOT_API_KEY_DEEPSEEK_OFFICIAL",
            "group": "deepseek官方",
            "tags": ["low", "high", "max", "text-only"],
            "priority": 900,
        }
    }.items()})
    settings["model_registry"] = registry
    changes.append(
        f"runtime model_registry: {before} -> {len(registry)} entries "
        f"(axonhub {len(AXONHUB_ROUTES)} + deepseek fallback {len(DEEPSEEK_FALLBACK)})"
    )

    overrides = settings.get("overrides") or {}
    overrides["BOT_CHAT_MODEL"] = DEFAULT_MODEL
    overrides["BOT_CHAT_BASE_URL"] = AXONHUB_BASE_URL
    overrides.setdefault("BOT_MODEL_PRIORITY_GROUPS", {})
    settings["overrides"] = overrides
    changes.append(
        f"runtime overrides BOT_CHAT_MODEL = {DEFAULT_MODEL}; "
        f"BOT_CHAT_BASE_URL = {AXONHUB_BASE_URL}"
    )

    # ---- 能力标签闸（路①的保险）：任何一条在册声明在待写注册表里落不了地，
    # 就拒绝落盘——DRY-RUN 只点名，--apply 直接 EXIT 2 且一个字节都不写。
    guard_problems = capability_guard_problems(registry)
    for line in changes:
        print("  " + line)
    if guard_problems:
        print("\n[红] 能力标签闸拦下本次写回（不写 .env、不写运行时注册表）：")
        for problem in guard_problems:
            print("  - " + problem)
        print(
            "  修法：在册真身 = plugins/bot_unified_runtime/domains/core/"
            "channel_capability_tags.py 的 CHANNEL_CAPABILITY_KINDS；"
            "要么让该渠道在 AXONHUB_ROUTES 里回来（tags 列只写档位，"
            "能力标签由 tags_for() 合成），要么确认确要摘牌后改那份声明。"
        )
        return 2

    # 凭据零命中门（裁定 12）：排在能力闸之后——不许抢跑成让上方护栏测试空跑的形态。
    key_presence = resolve_key_presence()
    if key_presence is None:
        print(
            f"\n[红] {AXONHUB_KEY_SLOT} 零命中：环境变量与 .env 都没有非空值。"
            "本脚本对凭据只读（裁定 12），不代写回、不打印值："
            "请管理员把网关 key 轮替/填入 .env（或导出同名环境变量）后重跑。"
            "退出码 3，未写任何文件。"
        )
        return 3
    print(f"  credential presence: {AXONHUB_KEY_SLOT} <- {key_presence}（值不打印）")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    # .env 不再被改动，故不再备份；只备份并写 runtime settings 一枚。
    shutil.copy2(RUNTIME_SETTINGS, BACKUP_DIR / f"runtime_settings_shorekeeper.json.bak-{stamp}")
    RUNTIME_SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwritten. backups in {BACKUP_DIR} (stamp {stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
