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

# 反照本宣科的「词条骨架压平」已从出站咽喉退役（W3 收尾 2026-09-30）：它与打码
# 无关、判据不可收敛，实测把「一切都会好的」啃成「切都会好的」、把行首名次与空行
# 一起吃掉。理由与四类误伤逐条写在 plain_text.py 的退役注释里，退役锁住在
# tests/test_secret_redaction_hardening.py（名册消失 + 结构恒等）。随件的两枚直测
# 按「退役要文件＋账本行同批」一并撤走，下面这枚改写成**反向锁**：不许再吞。


def test_humanize_reply_keeps_ordinal_and_blank_lines() -> None:
    from plugins.bot_unified_runtime.domains.render.plain_text import humanize_reply

    # 开场客套照旧剥，行首序号与空行照旧留（段间换行的唯一真身＝roleplay）。
    assert humanize_reply("好的！以下是干员资料：\n一、 身份与背景来历\n她叫陈晖洁。") == (
        "干员资料：\n一、 身份与背景来历\n她叫陈晖洁。"
    )
    assert humanize_reply("一、身份\n\n她叫陈晖洁。") == "一、身份\n\n她叫陈晖洁。"


def test_knowledge_block_carries_anti_recital_rule() -> None:
    """A-12 提示词腿：有命中时【知识库】区第一行必须是"消化成自己的话"那条令。"""
    from plugins.bot_unified_runtime.domains.chat_reply.capabilities import chat

    assert "不是稿子" in chat._KB_RECITAL_RULE_LINE
    assert "不许贴链接" in chat._KB_RECITAL_RULE_LINE


def test_coalescing_window_is_on_in_production_env() -> None:
    """窗开形态锁（2026-10-03 用户裁定：折句窗开，.env/.env.example 已同批改 true）。

    旧姿态（2026-09-27「合并窗暂关 ⇒ 显式 false」）随裁定失效：本锁改为钉「两处申报面
    都显式 true」——防缺省漂移回关（漏申报＝形态退化），也防有人不声不响再关窗。
    """
    from dotenv import dotenv_values

    assert str(dotenv_values(".env").get("BOT_CHAT_MESSAGE_COALESCING_ENABLED")).lower() == "true"
    assert str(dotenv_values(".env.example").get("BOT_CHAT_MESSAGE_COALESCING_ENABLED")).lower() == "true"


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
