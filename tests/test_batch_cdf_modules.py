from __future__ import annotations

from plugins.bot_unified_runtime.domains.files.capabilities.group_files import (
    DirtyGuard,
    GroupFileStore,
    category_for_filename,
)
from plugins.bot_unified_runtime.domains.media.search.sauce_search import (
    search_saucenao,
)
from plugins.bot_unified_runtime.output.plain_text import humanize_reply


def test_flatten_article_scaffolding_collapses_wiki_skeleton() -> None:
    """A-12 兜底：词条骨架（编号小标题/markdown）不许原样发给用户（2026-09-27 实弹）。"""
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        flatten_article_scaffolding,
    )

    src = (
        "一、 身份与背景来历\n她的本名叫陈晖洁。\n1. 散射手特性：攻击范围为扇形\n"
        "- 节约风气：有概率不消耗弹药\n- 假日余韵：常驻攻速加成"
    )
    out = flatten_article_scaffolding(src)
    assert "一、" not in out and "1. " not in out and "- " not in out
    assert "她的本名叫陈晖洁。" in out  # 正文一字不删
    assert "散射手特性" in out


def test_flatten_article_scaffolding_leaves_plain_speech_alone() -> None:
    """反例锁：日常语气里的数字/破折号/「第一」不是骨架，必须逐字节原样返回。"""
    from plugins.bot_unified_runtime.domains.render.plain_text import (
        flatten_article_scaffolding,
    )

    plain = "……先是品牌与人物的映射出现了偏差。第一张图我没看懂，1.5 秒后才反应过来。\n- 那也算一种默契。"
    assert flatten_article_scaffolding(plain) == plain
    # 单行 bullet 是行文不是列表（连续两行才认）：
    assert flatten_article_scaffolding("- 我在。") == "- 我在。"


def test_humanize_reply_flattens_before_stripping_cliches() -> None:
    from plugins.bot_unified_runtime.domains.render.plain_text import humanize_reply

    assert humanize_reply("好的！以下是干员资料：\n一、 身份与背景来历\n她叫陈晖洁。") == (
        "干员资料：\n身份与背景来历\n她叫陈晖洁。"
    )


def test_knowledge_block_carries_anti_recital_rule() -> None:
    """A-12 提示词腿：有命中时【知识库】区第一行必须是"消化成自己的话"那条令。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    assert "不是稿子" in chat._KB_RECITAL_RULE_LINE
    assert "不许贴链接" in chat._KB_RECITAL_RULE_LINE


def test_coalescing_window_is_off_in_production_env() -> None:
    """2026-09-27 裁定：合并窗暂关 ⇒ .env 必须显式 false（缺省 True 会照旧合并）。"""
    from dotenv import dotenv_values

    values = dotenv_values(".env")
    assert str(values.get("BOT_CHAT_MESSAGE_COALESCING_ENABLED")).lower() == "false"


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
