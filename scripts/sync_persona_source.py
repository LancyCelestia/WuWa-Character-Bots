"""sync_persona_source — 守岸人「人格源 ↔ 运行时副本」一致性门（同步声明机制）.

测绘结论（2026-09-14，详见
.superpowers/sdd/2026-09-13-six-domain-batch/persona-sync-report.md）：
- 生产 BOT_PERSONA_FILES 指向 ChatBot_Runtime/data/persona/守岸人_核心人格.md
  （运行时副本，生产人格正文唯一来源）；
- 仓库 personas/shorekeeper/identity.md 是 git 策展人格源；knowledge/ 两文件被
  BOT_KNOWLEDGE_FILES 生产直读（同一份文件，无副本分叉问题）；
- 副本与源是**各自演化的独立文本**（difflib 相似度最高 0.095，非逐字节拷贝），
  无法逐字节对源比对 → 门采用「同步声明」：锚定文件记录最近一次**经人工审阅**
  的副本 sha256 + 源侧快照；副本被单方面改动而未重录锚定 → 红。

注：任务原设计把锚定放 personas/shorekeeper/SYNC.md；因「personas/ 只读」纪律
优先（人格资产目录不夹带工程元数据），锚定改放 scripts/persona_sync_anchor.json。
日后如需迁回，改 ANCHOR_PATH 常量并挪文件即可。

用法：
  python scripts/sync_persona_source.py           # --check：绿/跳过 exit 0，红 exit 1
  python scripts/sync_persona_source.py --adopt --note "…人工审阅说明…"
                                                  # 把当前副本哈希重录为锚定
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_PATH = Path(__file__).resolve().parent / "persona_sync_anchor.json"
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_COPY_FALLBACK = (
    REPO_ROOT.parent / "ChatBot_Runtime" / "data" / "persona" / "守岸人_核心人格.md"
)

# 信息性源侧快照（不参与红绿判定）：提醒「源已演进、副本待人工对齐」。
# knowledge/ 两文件虽被生产直读，仍入快照以便 --check 时报告演进。
SOURCE_SNAPSHOT_FILES: tuple[str, ...] = (
    "personas/shorekeeper/aliases.txt",
    "personas/shorekeeper/identity.md",
    "personas/shorekeeper/knowledge/守岸人_核心知识.md",
    "personas/shorekeeper/knowledge/守岸人_人格与表达规范.md",
)

# check 状态码
OK = "OK"                            # 绿：副本哈希 == 锚定
DRIFT = "DRIFT"                      # 红：副本被单方面改动
SKIP_COPY_MISSING = "SKIP_COPY_MISSING"  # 跳过：副本不存在（bot 未部署/已移除）
ANCHOR_MISSING = "ANCHOR_MISSING"    # 红：锚定文件缺失或损坏
COPY_UNREADABLE = "COPY_UNREADABLE"  # 红：副本存在但读不到


@dataclass(frozen=True)
class CheckResult:
    status: str
    message: str

    @property
    def is_red(self) -> bool:
        return self.status in (DRIFT, ANCHOR_MISSING, COPY_UNREADABLE)

    @property
    def is_skip(self) -> bool:
        return self.status == SKIP_COPY_MISSING


def resolve_copy_path() -> Path:
    """解析生产人格副本路径：BOT_PERSONA_FILES（环境变量→.env）首项，失败回退常量."""
    raw = os.environ.get("BOT_PERSONA_FILES")
    if not raw:
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("BOT_PERSONA_FILES="):
                    raw = line.split("=", 1)[1].strip()
                    break
        except OSError:
            raw = None
    if raw:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            items = None
        if (
            isinstance(items, list)
            and items
            and isinstance(items[0], str)
            and items[0].strip()
        ):
            return Path(items[0])
    return DEFAULT_COPY_FALLBACK


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_source_snapshot() -> dict[str, str]:
    snap: dict[str, str] = {}
    for rel in SOURCE_SNAPSHOT_FILES:
        try:
            snap[rel] = sha256_path(REPO_ROOT / rel)
        except OSError:
            snap[rel] = "<missing>"
    return snap


def source_drift_since(anchor: dict[str, object]) -> list[str]:
    """信息性：锚定之后源侧演进的文件清单（不参与红绿判定）."""
    old = anchor.get("source_snapshot")
    if not isinstance(old, dict):
        return []
    return [
        rel
        for rel, now_hash in current_source_snapshot().items()
        if old.get(rel) != now_hash
    ]


def build_anchor(copy_path: Path, note: str = "") -> dict[str, object]:
    return {
        "schema": 1,
        "copy_path": str(copy_path),
        "copy_sha256": sha256_path(copy_path),
        "copy_size": copy_path.stat().st_size,
        "adopted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "source_snapshot": current_source_snapshot(),
    }


def load_anchor(anchor_path: Path) -> dict[str, object] | None:
    """读锚定；缺失/损坏/缺关键字段一律返回 None（门按 ANCHOR_MISSING 红）."""
    try:
        data = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("copy_sha256"):
        return None
    return data


def write_anchor(anchor_path: Path, anchor: dict[str, object]) -> None:
    anchor_path.write_text(
        json.dumps(anchor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def check(copy_path: Path, anchor_path: Path) -> CheckResult:
    """门本体：副本缺失→skip；不可读/锚缺失/漂移→红；哈希一致→绿."""
    if not copy_path.exists():
        return CheckResult(
            SKIP_COPY_MISSING,
            f"[SKIP] 生产人格副本不存在（bot 未部署或已移除），门跳过：{copy_path}",
        )
    try:
        actual = sha256_path(copy_path)
    except OSError as exc:
        return CheckResult(
            COPY_UNREADABLE,
            f"[红] 生产人格副本存在但不可读：{copy_path}（{exc}）",
        )
    anchor = load_anchor(anchor_path)
    if anchor is None:
        return CheckResult(
            ANCHOR_MISSING,
            f"[红] 锚定文件缺失或损坏：{anchor_path}。"
            f"副本当前 sha256={actual[:16]}…；人工审阅后运行 "
            "python scripts/sync_persona_source.py --adopt 重录锚定。",
        )
    expected = str(anchor.get("copy_sha256", ""))
    adopted = str(anchor.get("adopted_at", "?"))
    if actual == expected:
        msg = f"[绿] 副本与锚定一致 sha256={actual[:16]}…（锚定于 {adopted}）"
        drifted = source_drift_since(anchor)
        if drifted:
            msg += (
                "；注意：源侧 personas/shorekeeper 自锚定后已有演进"
                "（不影响红绿，同步时需人工对齐）："
                + "、".join(drifted)
            )
        return CheckResult(OK, msg)
    return CheckResult(
        DRIFT,
        f"[红] 生产人格副本被单方面改动：现 sha256={actual[:16]}… ≠ 锚定 "
        f"{expected[:16]}…（锚定于 {adopted}，note={anchor.get('note', '')!r}）。"
        "人工审阅副本改动（或对照 personas/shorekeeper/ 源）后运行 "
        "python scripts/sync_persona_source.py --adopt 重录锚定；"
        "若属误改请先从备份恢复副本。",
    )


def adopt(copy_path: Path, anchor_path: Path, note: str = "") -> dict[str, object]:
    """显式重录锚定（须人工审阅后调用）；副本缺失/不可读时拒绝并退出."""
    if not copy_path.exists():
        raise SystemExit(f"[abort] 副本不存在，无法锚定：{copy_path}")
    try:
        anchor = build_anchor(copy_path, note=note)
    except OSError as exc:
        raise SystemExit(
            f"[abort] 副本不可读，无法锚定：{copy_path}（{exc}）"
        ) from exc
    write_anchor(anchor_path, anchor)
    return anchor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="人格源-运行时副本一致性门（--check 校验 / --adopt 重录锚定）"
    )
    parser.add_argument(
        "--check", action="store_true", help="校验副本哈希==锚定（默认行为）"
    )
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="把当前副本哈希重录为锚定（需人工审阅后显式调用）",
    )
    parser.add_argument("--note", default="", help="--adopt 时的审阅说明")
    parser.add_argument(
        "--copy", default=None, help="覆盖副本路径（默认解析 BOT_PERSONA_FILES）"
    )
    parser.add_argument(
        "--anchor",
        default=None,
        help="覆盖锚定文件路径（默认 scripts/persona_sync_anchor.json）",
    )
    args = parser.parse_args(argv)

    copy_path = Path(args.copy) if args.copy else resolve_copy_path()
    anchor_path = Path(args.anchor) if args.anchor else ANCHOR_PATH

    if args.adopt:
        anchor = adopt(copy_path, anchor_path, note=args.note)
        print(f"[adopt] 已重录锚定：{anchor_path}")
        print(f"        副本 sha256={anchor['copy_sha256']}")
        snap = anchor["source_snapshot"]
        assert isinstance(snap, dict)
        print(f"        源侧快照 {len(snap)} 个文件（信息性，不参与红绿）")
        return 0

    result = check(copy_path, anchor_path)
    print(result.message)
    return 1 if result.is_red else 0


if __name__ == "__main__":
    sys.exit(main())
