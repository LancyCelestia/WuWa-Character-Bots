"""审计#17/#18/#19/#36/#9/#31/#28/#29a 修复回归（批次B，离线）。"""

from __future__ import annotations

import inspect
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from plugins.bot_unified_runtime.capabilities import eat as eat_mod
from plugins.bot_unified_runtime.capabilities import platform_credentials as pcred_mod
from plugins.bot_unified_runtime.capabilities.file_exchange import _safe_file_name
from plugins.bot_unified_runtime.contracts import (
    BotDecision,
    IncomingMessage,
    SessionType,
)
from plugins.bot_unified_runtime.sources import runtime_event_log as rel_mod
from plugins.bot_unified_runtime.sources.parsers import wbi as wbi_mod

_DECISION = BotDecision(
    request_id="r-w3",
    should_respond=True,
    mode="command",
    trigger="test",
    capability_id="bot.test",
    target_scope=SessionType.GROUP,
    decision_reason="unit-test",
)


def _message(text: str, *, session_id: str = "group:1", sender_id: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        platform="onebot",
        adapter="onebot.v11",
        bot_id="bot",
        session_id=session_id,
        session_type=SessionType.GROUP,
        group_id=session_id.split(":", 1)[-1],
        sender_id=sender_id,
        plain_text=text,
    )


# ---------------------------------------------------------------- 审计#18


def test_read_recent_tail_bounded(tmp_path) -> None:
    log = rel_mod.RuntimeEventLog(tmp_path / "events.log")
    for index in range(50):
        log.emit("INFO", f"tick{index}")
    got = log.read_recent(limit=5)
    assert len(got) == 5
    assert "tick45" in got[-5] and "tick49" in got[-1], "应取最新 5 条且保持时间序"


def test_read_recent_oversized_file_still_returns_tail(tmp_path) -> None:
    log = rel_mod.RuntimeEventLog(tmp_path / "big.log")
    # 超过 _READ_RECENT_MAX_BYTES 的文件：尾部命中仍在窗口内。
    filler = "x" * 200
    with (tmp_path / "big.log").open("w", encoding="utf-8") as handle:
        for _ in range(int(rel_mod.RuntimeEventLog._READ_RECENT_MAX_BYTES * 1.5) // (len(filler) + 1)):
            handle.write(filler + "\n")
        for index in range(6):
            handle.write(f"2026-09-11T00:00:00 [INFO] tail{index}\n")
    got = log.read_recent(limit=6)
    assert len(got) == 6 and "tail5" in got[-1], "窗口截断不得丢最新日志"


# ---------------------------------------------------------------- 审计#19/#36


def test_safe_file_name_hash_disambiguates_slug_collision() -> None:
    long_prefix = "很长的标题" * 20  # 归一化截断后 slug 相同
    name_a = _safe_file_name(long_prefix + "甲", "pdf")
    name_b = _safe_file_name(long_prefix + "乙", "pdf")
    assert name_a != name_b, "不同主题不得静默共用同一文件名"
    assert _safe_file_name("教程", "md") == _safe_file_name("教程", "md"), "同主题保持稳定"


def test_debug_tmpdir_ignores_cleanup_errors() -> None:
    import plugins.bot_unified_runtime.capabilities.file_exchange as fx

    source = inspect.getsource(fx)
    assert "ignore_cleanup_errors=True" in source, "孙进程锁 workdir 时清理异常不得吞掉运行结果"


# ---------------------------------------------------------------- 审计#9


def test_wbi_cache_lazy_purge_and_cap(monkeypatch) -> None:
    monkeypatch.setattr(wbi_mod, "_WBI_CACHE_CAP", 4)
    wbi_mod._WBI_CACHE.clear()
    now = wbi_mod.time.monotonic()
    # 6 个早已过期的旧 key + 1 个新鲜 key：惰性清扫 + 容量封顶都要生效。
    for index in range(6):
        wbi_mod._WBI_CACHE[f"stale{index}|p"] = (now - wbi_mod._WBI_CACHE_TTL_SECONDS - index, "old")
    wbi_mod._WBI_CACHE["fresh|p"] = (now, "current")

    def fake_fetch() -> dict:
        raise AssertionError("fresh 命中时不得触发 nav 拉取")

    got = wbi_mod._cached_mixin_key("fresh", "p", fetch=fake_fetch)
    assert got == "current"
    assert all(not key.startswith("stale") for key in wbi_mod._WBI_CACHE), "过期条目应被清扫"
    assert len(wbi_mod._WBI_CACHE) <= 4

    # 未过期但超容量：插入新 key 后总量不超上限。
    # img/sub 文件名须为真实形态（各 32 位十六进制），extract_mixin_key 的
    # 索引表最大值 58，短文件名会 IndexError。
    calls: list[str] = []

    def nav_fetch() -> dict:
        stem = f"{len(calls):032x}"
        calls.append(stem)
        return {
            "data": {
                "wbi_img": {
                    "img_url": f"https://i0.hdslb.com/bfs/wbi/{stem}.png",
                    "sub_url": f"https://i0.hdslb.com/bfs/wbi/{stem}_sub.png",
                }
            }
        }

    for index in range(6):
        wbi_mod._cached_mixin_key(f"dyn{index}", "p", fetch=nav_fetch)
    assert len(wbi_mod._WBI_CACHE) <= 4


# ---------------------------------------------------------------- 审计#31


def _eat_dish_monkeypatch(monkeypatch, names: list[str]) -> None:
    from plugins.bot_unified_runtime.sources.food_data import DISHES

    prototype = DISHES[0]
    queue = iter(names)

    def fake_random_dish(exclude=None, *, spicy=None):
        try:
            name = next(queue)
        except StopIteration:
            return prototype
        return replace(prototype, name=name)

    monkeypatch.setattr(eat_mod, "random_dish", fake_random_dish)


def test_eat_recent_evicts_oldest_half_not_clear(monkeypatch) -> None:
    eat_mod.clear_recent_dishes()
    _eat_dish_monkeypatch(monkeypatch, [f"菜{index:02d}" for index in range(40)])
    capability = eat_mod.build_eat_capability()
    for _ in range(30):
        result = capability(_message("吃什么 不辣"), _DECISION)
        assert "抽不出" not in result.body
    # 会话键是 f"{session_type.value}:{session_id}"，与消息 helper 拼接后带前缀。
    recent = next(iter(eat_mod._RECENT.values()))
    assert len(recent) <= 24, "超限后不得全量保留"
    assert "菜00" not in recent and "菜05" not in recent, "最旧的一半应被逐出"
    assert "菜29" in recent, "近期推荐必须保留"


def test_eat_recent_concurrent_no_crash(monkeypatch) -> None:
    eat_mod.clear_recent_dishes()
    _eat_dish_monkeypatch(monkeypatch, [])
    capability = eat_mod.build_eat_capability()
    errors: list[Exception] = []

    def worker(worker_id: int) -> None:
        try:
            for index in range(60):
                capability(
                    _message("吃什么 不辣", session_id=f"group:{worker_id}-{index % 7}"),
                    _DECISION,
                )
        except Exception as exc:  # noqa: BLE001 - 测试收集线程异常
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"并发访问 _RECENT 出现异常: {errors[:3]}"
    assert len(eat_mod._RECENT) <= eat_mod._RECENT_MAX_SESSIONS


# ---------------------------------------------------------------- 审计#28


def test_cookie_import_concurrent_single_line(tmp_path, monkeypatch) -> None:
    cookie_file = tmp_path / "cookies.txt"
    monkeypatch.setattr(pcred_mod, "_resolve_cookie_file", lambda config: cookie_file)
    errors: list[Exception] = []

    def do_import(worker_id: int) -> None:
        try:
            pcred_mod.import_cookie_header(
                SimpleNamespace(), "bilibili", f"SESSDATA=s{worker_id}; bili_jct=j{worker_id}"
            )
        except Exception as exc:  # noqa: BLE001 - 测试收集线程异常
            errors.append(exc)

    threads = [threading.Thread(target=do_import, args=(worker_id,)) for worker_id in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"并发 import 出现异常: {errors[:3]}"
    lines = [line for line in cookie_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    names = [line.split("\t")[5] for line in lines]
    assert len(names) == len(set(names)), f"cookies.txt 出现重复行: {names}"


# ---------------------------------------------------------------- 审计#29a


def test_bot_memory_is_offloaded() -> None:
    # __init__.py 根导入会拉起 NoneBot 运行时，单测只做源码级锁定。
    import plugins.bot_unified_runtime as pkg

    source = Path(pkg.__file__).read_text(encoding="utf-8")
    tail = source.split("OFFLOADED_CAPABILITY_IDS", 1)[1].split("}", 1)[0]
    assert '"bot.memory"' in tail
