"""PR 修复回归：知识文件签名缓存（检视 #9）+ 吃什么辣度过滤确定性（鱼香肉丝 flaky）。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.bot_unified_runtime.capabilities.eat import (
    build_eat_capability,
    clear_recent_dishes,
)
from plugins.bot_unified_runtime.character import providers
from plugins.bot_unified_runtime.character.providers import _build_knowledge_chunks
from plugins.bot_unified_runtime.contracts import SessionType
from plugins.bot_unified_runtime.contracts.runtime import IncomingMessage
from plugins.bot_unified_runtime.sources.food_data import DISHES

# 与 tests/test_eat_capability.py::test_spicy_filter 的判定词保持一致。
SPICY_MARKS = ("麻辣", "香辣", "酸辣")


def _message(text: str, session_id: str = "private:u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.PRIVATE,
        sender_id="u1",
        plain_text=text,
    )


def _capability():
    return build_eat_capability(
        SimpleNamespace(bot_card_render_dir="", bot_card_cache_max_bytes=0)
    )


def _dish_text(dish_name: str) -> str:
    """按推荐卡正文字段拼出完整文案（与 _format_dish_body 同源）。"""
    dish = next(d for d in DISHES if d.name == dish_name)
    return (
        f"{dish.name}（{dish.taste}）{dish.intro}"
        f"食材：{dish.materials}做法：{dish.steps}"
    )


@pytest.fixture(autouse=True)
def _isolated_knowledge_cache() -> Iterator[None]:
    """签名缓存是模块级共享状态，逐用例清空保证隔离。"""
    providers._KNOWLEDGE_TEXT_CACHE.clear()
    yield
    providers._KNOWLEDGE_TEXT_CACHE.clear()


def test_knowledge_text_cache_skips_reread_on_same_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一文件签名未变时二次访问不重读（消除每条消息的重复磁盘 IO）。"""
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("守岸人知识第一段\n", encoding="utf-8")
    calls: list[Path] = []
    real_load = providers.load_character_document

    def counting_load(path: Path) -> str:
        calls.append(path)
        return real_load(path)

    monkeypatch.setattr(providers, "load_character_document", counting_load)

    first = _build_knowledge_chunks(
        files=[knowledge_file], max_chunks=4, chunk_chars=900
    )
    second = _build_knowledge_chunks(
        files=[knowledge_file], max_chunks=4, chunk_chars=900
    )

    assert len(calls) == 1
    assert [(c.chunk_id, c.content) for c in first] == [
        (c.chunk_id, c.content) for c in second
    ]
    assert first and "守岸人知识第一段" in first[0].content


def test_knowledge_text_cache_reloads_when_signature_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内容变化后（同尺寸、仅 mtime 前移）签名失配，必须重读新内容。"""
    knowledge_file = tmp_path / "knowledge.md"
    knowledge_file.write_text("签名缓存旧内容\n", encoding="utf-8")
    calls: list[Path] = []
    real_load = providers.load_character_document

    def counting_load(path: Path) -> str:
        calls.append(path)
        return real_load(path)

    monkeypatch.setattr(providers, "load_character_document", counting_load)

    first = _build_knowledge_chunks(
        files=[knowledge_file], max_chunks=4, chunk_chars=900
    )
    # 同字节数改写（旧→新同为 3 字节 CJK），显式前移 mtime，隔离出 mtime 触发路径。
    knowledge_file.write_text("签名缓存新内容\n", encoding="utf-8")
    bumped = knowledge_file.stat().st_mtime_ns + 1_000_000_000
    os.utime(knowledge_file, ns=(bumped, bumped))

    second = _build_knowledge_chunks(
        files=[knowledge_file], max_chunks=4, chunk_chars=900
    )

    assert len(calls) == 2
    assert first and "签名缓存旧内容" in first[0].content
    assert second and "签名缓存新内容" in second[0].content


def test_mild_dish_pool_has_no_spicy_trigger_words() -> None:
    """数据层不变量：所有显式不辣（spicy=False）的菜，全文案不含辣度触发词。"""
    mild = [dish for dish in DISHES if not dish.spicy]
    assert len(mild) >= 40
    for dish in mild:
        text = (
            f"{dish.name}（{dish.taste}）{dish.intro}"
            f"食材：{dish.materials}做法：{dish.steps}"
        )
        for mark in SPICY_MARKS:
            assert mark not in text, f"非辣菜「{dish.name}」文案含触发词「{mark}」"


def test_yuxiang_rousi_classified_mild_and_filter_respects_flag() -> None:
    """鱼香肉丝（酸甜微辣不辣的家常味）辣度分类必须确定为不辣且文案干净。"""
    dish = next(d for d in DISHES if d.name == "鱼香肉丝")
    assert dish.spicy is False
    assert not any(mark in _dish_text(dish.name) for mark in SPICY_MARKS)


def test_mild_request_never_recommends_spicy_marked_body() -> None:
    """循环抽样：「不辣」请求的输出正文永远不含辣度触发词（确定性回归）。"""
    capability = _capability()
    clear_recent_dishes()
    picked_names: set[str] = set()
    for _ in range(200):
        result = capability(_message("吃什么 不辣"), None)
        assert result.body
        assert "🍽" in result.body
        for mark in SPICY_MARKS:
            assert mark not in result.body, (
                f"「不辣」请求正文出现触发词「{mark}」：\n{result.body}"
            )
        for line in result.body.splitlines():
            if line.startswith("🍽"):
                picked_names.add(line[len("🍽 ") :].split("（", 1)[0])
    # 抽样覆盖面：200 次应命中多个非辣菜；鱼香肉丝分支由上面的
    # test_yuxiang_rousi_classified_mild_and_filter_respects_flag 确定性单查覆盖。
    assert len(picked_names) >= 2
