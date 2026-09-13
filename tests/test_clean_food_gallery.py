"""clean_food_gallery 离线单测：mock VLM provider，零网络、零真实图库。

验证三类判定的清理语义：
- is_food=False → DB 行删除 + 图片与 .source.txt 移入隔离区；
- 无法判定（VLM 异常/bad JSON → None）→ 保守保留（行与文件原样）；
- is_food=True → 保留；
另锁 DRY-RUN 缺省不动库不挪文件。
"""

from __future__ import annotations

import base64
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.clean_food_gallery as cleaner


class _FakeProvider:
    """按图片字节路由判定的假 provider（模拟 VLM JSON 应答）。"""

    def __init__(self, verdicts: dict[bytes, str]) -> None:
        self._verdicts = verdicts

    def generate(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> SimpleNamespace:
        content = messages[-1]["content"]
        data_url = content[1]["image_url"]["url"]
        payload = base64.b64decode(data_url.split(";base64,", 1)[1])
        return SimpleNamespace(text=self._verdicts[payload])


def _seed_db(root: Path, entries: list[tuple[str, bytes, str]]) -> Path:
    """在 root 建 library.sqlite + 图片/旁车文件，返回库路径。"""
    conn = sqlite3.connect(str(root / "library.sqlite"))
    try:
        conn.execute(
            "CREATE TABLE food_images ("
            "name TEXT PRIMARY KEY, path TEXT NOT NULL, "
            "source_url TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL DEFAULT '')"
        )
        for name, payload, url in entries:
            image = root / f"{name}.jpg"
            image.write_bytes(payload)
            image.with_suffix(".source.txt").write_text(
                f"{url}\n2026-09-13T00:00:00+08:00\n", encoding="utf-8"
            )
            conn.execute(
                "INSERT INTO food_images(name, path, source_url, fetched_at) "
                "VALUES(?,?,?,?)",
                (name, str(image), url, "2026-09-13T00:00:00+08:00"),
            )
        conn.commit()
    finally:
        conn.close()
    return root / "library.sqlite"


def _db_names(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {name for (name,) in conn.execute("SELECT name FROM food_images")}
    finally:
        conn.close()


def _quarantine(tmp_path: Path) -> Path:
    return tmp_path / f"food_quarantine_{datetime.now().astimezone():%Y%m%d}"


def _patch_cleaner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: _FakeProvider
) -> Path:
    """config/模型/隔离区全部指进 tmp_path，返回种子图库根目录。"""
    root = tmp_path / "gallery"
    root.mkdir()
    monkeypatch.setattr(
        cleaner, "_load_config", lambda: SimpleNamespace(bot_food_image_dir=str(root))
    )
    monkeypatch.setattr(cleaner, "_build_provider", lambda _config: provider)
    monkeypatch.setenv("TEMP", str(tmp_path))
    return root


def test_execute_removes_non_food_and_keeps_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = b"\xff\xd8\xff\xe0bad-polluted"
    unclear = b"\xff\xd8\xff\xe0vlm-error"
    good = b"\xff\xd8\xff\xe0real-food"
    provider = _FakeProvider(
        {
            bad: '{"is_food": false, "reason": "动漫剧照"}',
            unclear: "抱歉，我无法判定这张图。",  # 无 JSON → 保守保留
            good: '{"is_food": true, "reason": "红烧肉"}',
        }
    )
    root = _patch_cleaner(monkeypatch, tmp_path, provider)
    db = _seed_db(
        root,
        [("bad", bad, "https://www.boredpanda.com/x.jpg"),
         ("unclear", unclear, "https://93.184.216.34/u.jpg"),
         ("good", good, "https://93.184.216.34/g.jpg")],
    )

    assert cleaner.main(["--execute"]) == 0

    assert _db_names(db) == {"unclear", "good"}  # 仅非食物行被删
    assert not (root / "bad.jpg").is_file()
    assert not (root / "bad.source.txt").is_file()
    moved = _quarantine(tmp_path) / "gallery"
    assert (moved / "bad.jpg").read_bytes() == bad  # 图片进隔离区可回捞
    assert (moved / "bad.source.txt").is_file()  # 旁车随行
    assert (root / "unclear.jpg").is_file()  # 无法判定原样保留
    assert (root / "good.jpg").is_file()


def test_dry_run_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = b"\xff\xd8\xff\xe0dry-run-me"
    provider = _FakeProvider({bad: '{"is_food": false, "reason": "广告图"}'})
    root = _patch_cleaner(monkeypatch, tmp_path, provider)
    db = _seed_db(root, [("bad", bad, "https://img95.699pic.com/y.jpg")])

    assert cleaner.main([]) == 0  # 缺省 DRY-RUN

    assert _db_names(db) == {"bad"}  # 不动库
    assert (root / "bad.jpg").is_file()  # 不挪文件
    assert not (_quarantine(tmp_path) / "gallery").exists()
