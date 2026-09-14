"""clean_food_gallery 离线单测：mock VLM provider，零网络、零真实图库。

验证三类判定的清理语义：
- is_food=False → DB 行删除 + 图片与 .source.txt 移入隔离区；
- 无法判定（VLM 异常/bad JSON → None）→ 保守保留（行与文件原样）；
- is_food=True → 保留；
另锁 DRY-RUN 缺省不动库不挪文件。

P3-14 三缺陷回归（2026-09-15）：
- 缺陷① is_food 为 JSON 字符串 "false" 时 bool("false")=True 污染图反被保留；
- 缺陷② os.environ["TEMP"] 缺失直接 KeyError 炸脚本；
- 缺陷③ 删行失败与移文件的顺序无一致性保障（孤儿行/孤儿文件）。
"""

from __future__ import annotations

import base64
import shutil
import sqlite3
import sys
import tempfile
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


# ---------- P3-14 缺陷①：is_food 字符串严格解析 ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        ("True", True),
        ("1", True),
        (" yes ", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("", False),
        ("no", False),
        ("garbage", False),
        # 缺键/数字/列表等无法识别 → None 保守保留（宁留勿删红线）
        (None, None),
        (1, None),
        ([True], None),
    ],
)
def test_parse_is_food_strict(
    value: object, expected: bool | None
) -> None:
    payload: dict = {"is_food": value}
    assert cleaner._parse_is_food(payload) is expected


def test_parse_is_food_missing_key_is_none() -> None:
    assert cleaner._parse_is_food({"reason": "x"}) is None
    assert cleaner._parse_is_food("not-a-dict") is None


def test_string_false_pollution_is_moved_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VLM 回 JSON 字符串 "false"：污染图必须判假移出，不再被 bool() 反转保留。"""
    bad = b"\xff\xd8\xff\xe0string-false-polluted"
    provider = _FakeProvider({bad: '{"is_food": "false", "reason": "饮料广告"}'})
    root = _patch_cleaner(monkeypatch, tmp_path, provider)
    db = _seed_db(root, [("bad", bad, "https://ad.example.com/x.jpg")])

    assert cleaner.main(["--execute"]) == 0

    assert _db_names(db) == set()
    assert not (root / "bad.jpg").is_file()
    assert (_quarantine(tmp_path) / "gallery" / "bad.jpg").read_bytes() == bad


# ---------- P3-14 缺陷②：TEMP 环境变量缺失不炸 ----------


def test_quarantine_dir_without_temp_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(var, raising=False)
    # 强制落到可控兜底目录（同时绕开 gettempdir 的进程内缓存）。
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "fallback"))

    q = cleaner._quarantine_dir()

    assert q == tmp_path / "fallback" / (
        f"food_quarantine_{datetime.now().astimezone():%Y%m%d}"
    )


def test_quarantine_dir_env_wins_over_cached_tempdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "unused-cache"))
    monkeypatch.setenv("TEMP", str(tmp_path))

    assert cleaner._quarantine_dir().parent == tmp_path


def test_main_survives_missing_temp_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """清空 TEMP/TMP/TMPDIR 后 main 全链不炸，文件落 gettempdir 兜底目录。"""
    bad = b"\xff\xd8\xff\xe0no-temp-env"
    provider = _FakeProvider({bad: '{"is_food": false, "reason": "证书"}'})
    root = _patch_cleaner(monkeypatch, tmp_path, provider)
    for var in ("TEMP", "TMP", "TMPDIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "fallback"))
    db = _seed_db(root, [("bad", bad, "https://cert.example.com/c.jpg")])

    assert cleaner.main(["--execute"]) == 0  # 不再 KeyError

    assert _db_names(db) == set()
    assert not (root / "bad.jpg").is_file()
    fallback_q = tmp_path / "fallback" / _quarantine(tmp_path).name
    assert (fallback_q / "gallery" / "bad.jpg").is_file()


# ---------- P3-14 缺陷③：删除序一致性（先移文件再删行，失败回捞） ----------


class _FailDeleteConn:
    """DELETE 一律失败的 sqlite3 连接壳（其余语句透传）。"""

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real

    def execute(self, sql: str, *params: object):
        if "DELETE" in sql.upper():
            raise sqlite3.OperationalError("simulated delete failure")
        return self._real.execute(sql, *params)

    def commit(self) -> None:
        self._real.commit()

    def close(self) -> None:
        self._real.close()


def test_execute_removal_moves_files_then_deletes_row(tmp_path: Path) -> None:
    image = tmp_path / "sub" / "a.jpg"
    image.parent.mkdir()
    image.write_bytes(b"img")
    sidecar = image.with_suffix(".source.txt")
    sidecar.write_text("url\n", encoding="utf-8")
    conn = sqlite3.connect(str(tmp_path / "library.sqlite"))
    conn.execute(
        "CREATE TABLE food_images (name TEXT PRIMARY KEY, path TEXT, source_url TEXT)"
    )
    conn.execute(
        "INSERT INTO food_images VALUES ('a.jpg', ?, 'u')", (str(image),)
    )
    conn.commit()

    status = cleaner._execute_removal(conn, "a.jpg", image, tmp_path / "q")

    conn.close()
    assert status == "removed"
    assert not image.exists() and not sidecar.exists()
    quarantined = {p.name for p in (tmp_path / "q").rglob("*") if p.is_file()}
    assert quarantined == {"a.jpg", "a.source.txt"}


def test_execute_removal_db_delete_failure_restores_no_orphan(
    tmp_path: Path,
) -> None:
    """删行失败：文件回捞回原位、DB 行仍在——不产生孤儿行/孤儿文件。"""
    image = tmp_path / "a.jpg"
    image.write_bytes(b"img")
    sidecar = image.with_suffix(".source.txt")
    sidecar.write_text("url\n", encoding="utf-8")
    real = sqlite3.connect(str(tmp_path / "library.sqlite"))
    real.execute(
        "CREATE TABLE food_images (name TEXT PRIMARY KEY, path TEXT, source_url TEXT)"
    )
    real.execute("INSERT INTO food_images VALUES ('a.jpg', ?, 'u')", (str(image),))
    real.commit()

    status = cleaner._execute_removal(
        _FailDeleteConn(real), "a.jpg", image, tmp_path / "q"
    )

    assert status == "restored"
    assert image.read_bytes() == b"img"  # 文件已回捞
    assert sidecar.is_file()
    assert not (tmp_path / "q").exists() or not any(
        (tmp_path / "q").rglob("a.jpg")
    )  # 隔离区无残留
    row = real.execute("SELECT name FROM food_images").fetchall()
    real.close()
    assert row == [("a.jpg",)]  # 行仍在


def test_main_rollback_failure_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回捞不彻底：main 如实报错退出非零，行保留待人工核查，不静默吞掉。"""
    bad = b"\xff\xd8\xff\xe0rollback-fail"
    provider = _FakeProvider({bad: '{"is_food": false, "reason": "海报"}'})
    root = _patch_cleaner(monkeypatch, tmp_path, provider)
    db = _seed_db(root, [("bad", bad, "https://poster.example.com/p.jpg")])
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        cleaner.sqlite3,
        "connect",
        lambda path: _FailDeleteConn(real_connect(path)),
    )
    real_move = shutil.move

    def _flaky_move(src: object, dst: object, *args: object, **kwargs: object):
        if Path(str(dst)) == root / "bad.jpg":  # 回捞（目标=原位）时模拟失败
            raise OSError("simulated rollback failure")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "move", _flaky_move)

    assert cleaner.main(["--execute"]) == 1

    assert _db_names(db) == {"bad"}  # 行保留（未删成）
    assert not (root / "bad.jpg").is_file()  # 文件滞留隔离区，等人工回捞
