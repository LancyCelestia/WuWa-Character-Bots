"""Cleanup: scrub plaintext credentials from the runtime history store (H8).

Safety properties:
  * Writes a byte-copy backup of the DB (and its -wal/-shm) BEFORE any change.
  * Only rewrites matched credential literals; all other text is untouched.
  * Prints counts and credential NAMES only — never values.
  * Idempotent: re-running reports 0 changes.
  * Verifies afterwards with an independent read-only re-scan.

Usage:
    python scrub_history_credentials.py            # dry-run (no writes)
    python scrub_history_credentials.py --apply    # perform the scrub
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data\wuwa_history.sqlite3"
)
BACKUP_DIR = Path(
    r"C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\backups"
)

_KEYISH = re.compile(
    r"(?i)\b(?P<name>[a-z0-9_]*(?:key|token|secret|password|passwd|authkey|cookie|credential)[a-z0-9_]*)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>(?!env:)[^\s,;\"']{6,})"
)
_BEARER = re.compile(r"(?i)\b(?P<name>bearer)(?P<sep>\s+) (?P<value>[A-Za-z0-9._\-]{8,})".replace(" ", ""))
_SK = re.compile(r"(?<![A-Za-z0-9])(?P<value>sk-[A-Za-z0-9][A-Za-z0-9_\-]{8,})")
_COOKIE = re.compile(
    r"(?i)\b(?P<name>SESSDATA|bili_jct|DedeUserID|SUBP|SUB|ALF|SSOLoginState|web_session|"
    r"sessionid|d_c0|z_c0|ct0)(?P<sep>\s*=\s*)(?P<value>[^\s;]{6,})"
)

# 辅助函数/字段名本身不是凭据：这些名字的"值"是函数签名或字段名，遮蔽反而
# 破坏审计文本的可读性（实测命中：required_env_keys / BOT_CHAT_API_KEY）。
_BENIGN_NAMES = {
    "required_env_keys",
    "bot_chat_api_key",
    "bot_api_key",
    "api_key_field",
    "api_key_env",
}


def _secret_names(text: str) -> list[str]:
    names: list[str] = []
    for match in _KEYISH.finditer(text):
        name = match.group("name")
        if name.lower() in _BENIGN_NAMES:
            continue
        if name not in names:
            names.append(name)
    for match in _COOKIE.finditer(text):
        name = match.group("name")
        if name not in names:
            names.append(name)
    if _SK.search(text):
        names.append("<sk-key>")
    if _BEARER.search(text):
        names.append("<bearer>")
    return names


def _scrub(text: str) -> tuple[str, int]:
    changes = 0

    def keyish(match: re.Match[str]) -> str:
        nonlocal changes
        name = match.group("name")
        if name.lower() in _BENIGN_NAMES:
            return match.group(0)
        changes += 1
        return f"{name}{match.group('sep')}[redacted]"

    def cookie(match: re.Match[str]) -> str:
        nonlocal changes
        changes += 1
        return f"{match.group('name')}{match.group('sep')}[redacted]"

    def sk(match: re.Match[str]) -> str:
        nonlocal changes
        changes += 1
        return "sk-[redacted]"

    def bearer(match: re.Match[str]) -> str:
        nonlocal changes
        changes += 1
        return f"{match.group('name')} [redacted]"

    out = _KEYISH.sub(keyish, text)
    out = _COOKIE.sub(cookie, out)
    out = _SK.sub(sk, out)
    out = _BEARER.sub(bearer, out)
    return out, changes


def _backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"wuwa_history.sqlite3.bak-{stamp}"
    shutil.copy2(DB, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(DB) + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, Path(str(target) + suffix))
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the scrub")
    args = parser.parse_args()

    if not DB.exists():
        print(f"history DB not found: {DB}")
        return 2

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT rowid, COALESCE(kind,'?'), text FROM conversation_turns"
        ).fetchall()
    finally:
        connection.close()

    targets: list[tuple[int, str, str, list[str]]] = []
    for rowid, kind, text in rows:
        if not isinstance(text, str) or len(text) < 6:
            continue
        names = _secret_names(text)
        if not names:
            continue
        scrubbed, changes = _scrub(text)
        if changes and scrubbed != text:
            targets.append((rowid, kind, scrubbed, names))

    print(f"DB: {DB}")
    print(f"scanned turns      : {len(rows)}")
    print(f"rows needing scrub : {len(targets)}")
    for rowid, kind, _scrubbed, names in targets:
        print(f"   rowid={rowid} kind={kind} names={names}")

    if not args.apply:
        print("\nDRY-RUN: nothing written. Re-run with --apply to scrub.")
        return 0

    if not targets:
        print("\nnothing to do.")
        return 0

    backup = _backup()
    print(f"\nbackup written: {backup}")

    connection = sqlite3.connect(str(DB))
    try:
        with connection:
            for rowid, _kind, scrubbed, _names in targets:
                connection.execute(
                    "UPDATE conversation_turns SET text = ? WHERE rowid = ?",
                    (scrubbed, rowid),
                )
    finally:
        connection.close()
    print(f"scrubbed rows: {len(targets)}")

    # independent verification
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        remaining = 0
        for (_rowid, _kind, text) in connection.execute(
            "SELECT rowid, COALESCE(kind,'?'), text FROM conversation_turns"
        ).fetchall():
            if isinstance(text, str) and _secret_names(text):
                remaining += 1
    finally:
        connection.close()
    print(f"verification: rows still matching after scrub = {remaining}")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
