"""Apply the user's requested configuration batch.

Writes runtime overrides (the live source of truth) + the few .env keys that
are genuinely deployment-level.  Backs up both files first.

Usage: python scripts/apply_config_batch.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = REPO / ".env"
SETTINGS = pathlib.Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\settings"
    r"\runtime_settings_shorekeeper.json"
)
BACKUP_DIR = pathlib.Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\backups"
)

# 群聊回复策略（用户本轮指定）
GROUP_LISTS = {
    "BOT_GROUP_BLACK1": [],
    "BOT_GROUP_BLACK2": [],
    "BOT_GROUP_WHITE1": [1106678641, 257344054, 1108838060],
    "BOT_GROUP_WHITE2": [662948429, 1076073471, 905324184, 936891679],
}

# 迁移到运行时 store 的键（高频变更，放 .env 必然与生效值漂移）
RUNTIME_OVERRIDES: dict[str, object] = {
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY": 0.01,
    "BOT_QUIET_HOURS_ENABLED": True,
    "BOT_QUIET_HOURS_START": "00:00",
    "BOT_QUIET_HOURS_END": "07:00",
    "BOT_QUIET_HOURS_TIMEZONE": "Asia/Hong_Kong",
    "BOT_QUIET_HOURS_SESSION_TYPES": ["group"],
    "BOT_QUIET_HOURS_BYPASS_ROLES": ["admin"],
    **GROUP_LISTS,
    # 群摘要：白名单默认开、黑名单默认关
    "BOT_SHARED_GROUP_CONTEXT_ENABLED": True,
    "BOT_GROUP_DIGEST_LIST_MODE": "whitelist",
    "BOT_GROUP_DIGEST_WHITELIST": [1108838060, 1076073471],
    "BOT_GROUP_DIGEST_BLACKLIST": [],
    # 合并转发：>3 条才合并
    "BOT_RENDER_FORWARD_MIN_NODES": 4,
    # 群聊限流：每小时 60 句、每分钟 3 句
    "BOT_RATE_LIMIT_GROUP_MAX_PER_HOUR": 60,
    "BOT_RATE_LIMIT_GROUP_MAX_PER_MINUTE": 3,
    # 情绪低落安抚豁免限流
    "BOT_RATE_LIMIT_EMOTION_EXEMPT": True,
}

ENV_UPDATES = {
    "BOT_VIDEO_UNDERSTANDING_ENABLED": "true",
    "BOT_VISION_MODE": "direct",
}

# 从 .env 删除（改由运行时 store 统一管理，避免与实际生效值漂移）
ENV_REMOVE = [
    "BOT_GROUP_CHAT_AUTO_REPLY_PROBABILITY",
    "BOT_QUIET_HOURS_ENABLED",
    "BOT_QUIET_HOURS_START",
    "BOT_QUIET_HOURS_END",
    "BOT_QUIET_HOURS_TIMEZONE",
    "BOT_QUIET_HOURS_SESSION_TYPES",
    "BOT_QUIET_HOURS_BYPASS_ROLES",
    "BOT_GROUP_BLACK1",
    "BOT_GROUP_BLACK2",
    "BOT_GROUP_WHITE1",
    "BOT_GROUP_WHITE2",
    "BOT_RENDER_FORWARD_MIN_CHARS",
    "BOT_RENDER_FORWARD_MAX_NODES",
    "BOT_RENDER_FORWARD_MIN_NODES",
]


def _set_line(text: str, key: str, value: str) -> str:
    import re

    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}{line}\n"


def _drop_line(text: str, key: str) -> tuple[str, bool]:
    import re

    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*\n?")
    new_text, count = pattern.subn("", text, count=1)
    return new_text, count > 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    overrides = settings.get("overrides") or {}
    report: list[str] = []

    for key, value in RUNTIME_OVERRIDES.items():
        old = overrides.get(key, "<unset>")
        overrides[key] = value
        report.append(f"runtime {key}: {old} -> {json.dumps(value, ensure_ascii=False)}")
    settings["overrides"] = overrides

    env_text = ENV_PATH.read_text(encoding="utf-8")
    for key, value in ENV_UPDATES.items():
        env_text = _set_line(env_text, key, value)
        report.append(f".env    set {key} = {value}")
    for key in ENV_REMOVE:
        env_text, removed = _drop_line(env_text, key)
        report.append(f".env    remove {key} (moved to runtime store) removed={removed}")

    for line in report:
        print("  " + line)

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to write.")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(ENV_PATH, BACKUP_DIR / f"env.bak-{stamp}")
    shutil.copy2(SETTINGS, BACKUP_DIR / f"runtime_settings_shorekeeper.json.bak-{stamp}")
    ENV_PATH.write_text(env_text, encoding="utf-8", newline="")
    SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwritten. backups stamp {stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
