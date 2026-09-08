from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities.platform_credentials import (
    cookie_status_text,
    import_cookie_header,
    is_cookie_command,
    parse_cookie_command,
)
from plugins.bot_unified_runtime.sources.parsers.cookies import (
    parse_netscape_cookie_file,
)


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bot_cookies_file="data/platform_cookies.txt",
        bot_runtime_data_dir=str(tmp_path),
    )


def test_command_detection_and_parsing() -> None:
    assert is_cookie_command("cookie")
    assert is_cookie_command("/bot cookie")
    assert is_cookie_command("凭证")
    assert not is_cookie_command("点歌 晴天")

    assert parse_cookie_command("cookie") == ("status", "", "")
    assert parse_cookie_command("/bot 凭证") == ("status", "", "")
    parsed = parse_cookie_command("cookie import bilibili SESSDATA=abc; bili_jct=xyz")
    assert parsed == ("import", "bilibili", "SESSDATA=abc; bili_jct=xyz")
    assert parse_cookie_command("cookie import bilibili") == ("import", "bilibili", "")


def test_import_writes_netscape_entries_and_skips_duplicates(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    config = _config(tmp_path)

    first = import_cookie_header(
        config, "bilibili", "SESSDATA=token-1; bili_jct=csrf-1; buvid3=idx"
    )
    assert "bilibili" in first and "3 项" in first

    entries = {
        entry.name: entry
        for entry in parse_netscape_cookie_file(
            tmp_path / "platform_cookies.txt"  # resolver 把 data/ 前缀映射进 Runtime 根
        )
    }
    assert entries["SESSDATA"].value == "token-1"
    assert entries["SESSDATA"].domain == ".bilibili.com"

    second = import_cookie_header(config, "bilibili", "SESSDATA=token-1; bili_jct=csrf-1")
    assert "已存在" in second


def test_import_rejects_unknown_platform_and_bad_header(tmp_path: Path) -> None:
    config = _config(tmp_path)

    unknown = import_cookie_header(config, "not-a-platform", "a=1")
    assert "未知平台" in unknown and "bilibili" in unknown

    bad = import_cookie_header(config, "bilibili", "没有等号的文本")
    assert "解析失败" in bad


def test_status_text_lists_platforms_without_values(tmp_path: Path) -> None:
    config = _config(tmp_path)
    import_cookie_header(config, "bilibili", "SESSDATA=secret-value")

    text = cookie_status_text(config)

    assert "bilibili" in text and "SESSDATA" in text
    assert "secret-value" not in text  # 值永不回显
    assert "未配置" in text
