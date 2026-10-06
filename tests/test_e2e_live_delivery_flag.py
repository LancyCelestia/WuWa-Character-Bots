"""验收器真发旗 `--live-delivery`（用户 2026-10-06 裁「A＝隔离为默认＋真发要显式旗」）。

背景两路意图相撞：另一路会话把 `--execute` 的发送队列改指 OS 临时库（根治"验收器写进她的
生产投递台账"，`1eda900`），而用户 10-06 那晚要的是「往群里全都测一遍」＝**真发**（靠真发
才验出 `bot_id` 哨兵洞，见 §76.20）。她的裁语＝两者都要：缺省隔离，带旗才真发。

三条判据（这个文件只锁这三条）：
1. 不带旗 ⇒ 与 `1eda900` 之后逐字节相同（临时库、label 里带 `isolated`）；
2. 带旗 ⇒ 用的就是 config 那枚生产库路径，label 点名 `live-production-queue`；
3. **旗越不过 DRY-RUN**：预览态带旗也绝不真发（防"我以为只是预览"）。
"""

from __future__ import annotations

import pytest

import scripts.e2e_acceptance as e2e
from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.domains.transport.sender import SQLiteSendRequestQueue


def _runtime(tmp_path, *, execute: bool, live: bool, db_path: str) -> e2e.E2eRuntime:
    """离线装配替身：只喂 `choose_send_queue` 真读的那三枚键，库路径一律给仓外绝对路径。

    🔴 `bot_runtime_data_dir` 必须是 `tmp_path`——直呼 ``Config(...)`` 的缺省 ``"data"``
    会被折成**源码树** ``data/``（2026-10-02 runtime-layout 红实案，见
    tests/test_e2e_acceptance.py 的 `_runtime_stub` 同款注释）。
    """
    config = Config(
        bot_runtime_data_dir=str(tmp_path / "runtime-data"),
        bot_send_queue_enabled=True,
        bot_send_queue_db_path=db_path,
    )
    fields = {"config": config, "runtime_settings": None, "render_backend": None,
              "execute": execute, "city": "北京", "bot_id": "", "sender_id": "10000"}
    try:
        return e2e.E2eRuntime(**fields, live_delivery=live)  # type: ignore[call-arg]
    except TypeError as exc:  # 旗还没实装时：这一句就是 RED 的本体
        raise AssertionError(f"E2eRuntime 缺 live_delivery 字段（功能未实装）：{exc}") from exc


def test_default_execute_still_isolates_the_queue(tmp_path) -> None:
    """不带旗 ⇒ 生产库路径不许出现在任何产物里，落在临时根上。"""
    production = str(tmp_path / "prod-send-queue.sqlite3")
    runtime = _runtime(tmp_path, execute=True, live=False, db_path=production)
    queue, label = e2e.choose_send_queue(
        runtime, InMemoryAuditLogger(), isolation_root=str(tmp_path / "iso")
    )
    assert isinstance(queue, SQLiteSendRequestQueue)
    assert "live-production-queue" not in label
    assert str(queue.db_path) != production
    assert "iso" in str(queue.db_path)


def test_live_flag_uses_the_production_configured_db(tmp_path) -> None:
    """带旗 ⇒ 真用 config 那枚生产库路径（这才叫"真发"：在线 worker 看得见它）。"""
    production = str(tmp_path / "prod-send-queue.sqlite3")
    runtime = _runtime(tmp_path, execute=True, live=True, db_path=production)
    queue, label = e2e.choose_send_queue(
        runtime, InMemoryAuditLogger(), isolation_root=str(tmp_path / "iso")
    )
    assert label.startswith("execute:sqlite:live-production-queue"), label
    assert str(queue.db_path) == production, f"带旗却还指临时库＝旗是假的：{queue.db_path}"


def test_dry_run_never_goes_live_even_with_the_flag(tmp_path) -> None:
    """预览态带旗也必须是 InMemory——旗只作用于 `--execute`。"""
    from plugins.bot_unified_runtime.domains.transport.sender import InMemorySendQueue

    production = str(tmp_path / "prod-send-queue.sqlite3")
    runtime = _runtime(tmp_path, execute=False, live=True, db_path=production)
    queue, label = e2e.choose_send_queue(runtime, InMemoryAuditLogger())
    assert label == "dry-run:in-memory"
    assert isinstance(queue, InMemorySendQueue), "预览态被旗换成了真队列"


def test_live_mode_is_disclosed_on_the_console(tmp_path, capsys) -> None:
    """带旗＝真发 ⇒ 必须当场说出来（她的裁语里"披露"是这一腿的判据，不是注释）。"""
    e2e.warn_live_delivery("execute:sqlite:live-production-queue:C:/x/prod.sqlite3")
    out = capsys.readouterr().out
    assert "真实投递" in out and "生产" in out, f"带旗没披露＝旗成了静默开关：{out!r}"

    capsys.readouterr()
    e2e.warn_live_delivery("execute:sqlite:isolated:C:/temp/iso/prod.sqlite3")
    assert capsys.readouterr().out == "", "缺省隔离态被喊成'真发'＝反向谎报"


def test_cli_flag_exists_and_defaults_off() -> None:
    """旗的缺省必须是"不真发"——默认态由命令行层再锁一遍。"""
    parser = e2e.build_arg_parser()
    base = ["--target-group", "662948429"]
    assert parser.parse_args(base + ["--execute"]).live_delivery is False
    assert parser.parse_args(base + ["--execute", "--live-delivery"]).live_delivery is True


def test_live_mode_still_requires_a_persistent_queue(tmp_path) -> None:
    """带旗不等于绕过准入：没启用持久化队列时仍须拒绝，不许"假真发"。"""
    config = Config(
        bot_runtime_data_dir=str(tmp_path / "runtime-data"),
        bot_send_queue_enabled=False,
        bot_send_queue_db_path="",
    )
    runtime = e2e.E2eRuntime(
        config=config, runtime_settings=None, render_backend=None, execute=True,
        city="北京", bot_id="", sender_id="10000",
        **{"live_delivery": True} if _supports_live_field() else {},
    )
    with pytest.raises(e2e.E2eSafetyError):
        e2e.choose_send_queue(runtime, InMemoryAuditLogger())


def _supports_live_field() -> bool:
    return "live_delivery" in getattr(e2e.E2eRuntime, "__dataclass_fields__", {})
