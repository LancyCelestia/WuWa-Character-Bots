from __future__ import annotations

from plugins.bot_unified_runtime.capabilities.group_files import (
    DirtyGuard,
    GroupFileStore,
    category_for_filename,
)
from plugins.bot_unified_runtime.output.plain_text import humanize_reply
from plugins.bot_unified_runtime.sources.sauce_search import search_saucenao


def test_category_mapping() -> None:
    assert category_for_filename("a.pdf") == "文档"
    assert category_for_filename("b.mp4") == "视频"
    assert category_for_filename("noext") == "其他"


def test_group_file_store_summary(tmp_path) -> None:
    store = GroupFileStore(tmp_path / "gf.sqlite3")
    store.record(group_id="g1", file_id="f1", name="攻略.pdf", size=2048, uploader_id="u1")
    store.record(group_id="g1", file_id="f2", name="录屏.mp4", size=1024 * 1024)
    text = store.summary("g1")

    lines = text.splitlines()
    assert any("文档" in line for line in lines)
    assert any("攻略.pdf" in line for line in lines)
    assert "没有记录" not in text


def test_dirty_guard_levels_and_default_off() -> None:
    guard = DirtyGuard(delete_enabled=False)
    assert guard.assess("正常聊天内容") == "clean"
    assert guard.assess("你是傻逼") == "warn"
    assert guard.assess("非法内容示例：制毒教程") == "severe"
    # 默认不启用撤回动作。
    assert guard.delete_enabled is False


def test_humanize_reply_strips_ai_cliches() -> None:
    assert humanize_reply("好的！以下是配队思路：\n核心是XX。") == "配队思路：\n核心是XX。"
    assert humanize_reply("核心输出靠重击。总之以上就是全部内容。") == "核心输出靠重击。"
    plain = "这句本来就很人话。"
    assert humanize_reply(plain) == plain


def test_saucenao_ignores_non_http_url() -> None:
    assert search_saucenao("file:///tmp/x.png", api_key="k") == []
    assert search_saucenao("", api_key="k") == []
