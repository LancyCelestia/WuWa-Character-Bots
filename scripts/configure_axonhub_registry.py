"""Configure axonhub as the unified model gateway (user request).

Writes:
  * `.env`  -> BOT_CHAT_MODEL / BOT_CHAT_BASE_URL / BOT_API_KEY_AXONHUB (+ registry removal)
  * runtime settings JSON -> `model_registry` (the live registry, which overrides .env)

Only model id / base_url / key *slot name* are printed — never key values.

Usage:  python scripts/configure_axonhub_registry.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
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
# 用户提供的网关 key；写入 .env 的该键（本脚本不回显其值）。
AXONHUB_KEY_VALUE = "ah-46169ceddcc4b2bd8ff9130c32bd9415d25f9d8b5948a290b612ac04fa1f79a6"

DEFAULT_MODEL = "gemini-3.8-flash"

# ---------------------------------------------------------------- axonhub 条目
# 说明：本网关对模型名**大小写敏感**且大小写行为不一致（实测）：
#   gemini-3.8-flash        ✅ 200   |  Gemini-3.8-Flash        ❌ 503
#   gemini-3.8-flash-high   ✅ 200   |  Gemini-3.8-Flash-High   ❌ 503
#   gpt-5.6-terra           ❌ 超时  |  GPT-5.6-Terra           ✅ 200
# 因此下面逐条用**实测可用的那个拼写**。同渠道的两种拼写都登记，交给故障转移兜。
AXONHUB_ROUTES: list[tuple[str, str, list[str], int]] = [
    # (entry_id, model, tags, priority)
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


def build_registry() -> dict:
    registry: dict[str, dict] = {}
    for entry_id, model, tags, priority in AXONHUB_ROUTES:
        registry[entry_id] = {
            "model": model,
            "base_url": AXONHUB_BASE_URL,
            "api_key": f"env:{AXONHUB_KEY_SLOT}",
            "group": "axonhub",
            "tags": tags,
            "priority": priority,
            "price_in": 0.0,
            "price_out": 0.0,
            "source": "axonhub",
        }
    return registry


def upsert_env(text: str, key: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    line = f"{key}={value}"
    if pattern.search(text):
        new_text, n = pattern.subn(line.replace("\\", "\\\\"), text, count=1)
        return new_text, n > 0
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}{line}\n", True


def remove_env_key(text: str, key: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*\n?")
    new_text, n = pattern.subn("", text, count=1)
    return new_text, n > 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    changes: list[str] = []

    env_text = ENV_PATH.read_text(encoding="utf-8")
    new_env = env_text
    for key, value in (
        ("BOT_CHAT_MODEL", DEFAULT_MODEL),
        ("BOT_CHAT_BASE_URL", AXONHUB_BASE_URL),
        (AXONHUB_KEY_SLOT, AXONHUB_KEY_VALUE),
    ):
        new_env, _changed = upsert_env(new_env, key, value)
        changes.append(f".env  set {key} = {'<key>' if 'KEY' in key else value}")
    # 把整段注册表移出 .env：它属于"高频/大体量"配置，改一次就要动整个文件，
    # 极易与实际生效的运行时 store 产生偏移（用户本次反馈的正是这个问题）。
    new_env, removed = remove_env_key(new_env, "BOT_MODEL_REGISTRY")
    changes.append(f".env  remove BOT_MODEL_REGISTRY (moved to runtime store) removed={removed}")

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
    overrides.setdefault("BOT_MODEL_PRIORITY_GROUPS", {})
    settings["overrides"] = overrides
    changes.append(f"runtime overrides BOT_CHAT_MODEL = {DEFAULT_MODEL}")

    for line in changes:
        print("  " + line)

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(ENV_PATH, BACKUP_DIR / f"env.bak-{stamp}")
    shutil.copy2(RUNTIME_SETTINGS, BACKUP_DIR / f"runtime_settings_shorekeeper.json.bak-{stamp}")
    ENV_PATH.write_text(new_env, encoding="utf-8", newline="")
    RUNTIME_SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwritten. backups in {BACKUP_DIR} (stamp {stamp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
