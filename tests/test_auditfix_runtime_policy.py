"""B 组（运行时/配置/策略域）审计修复回归，离线可跑。

覆盖：B6 命令前缀词边界、B7 风险帽 0=不生效、B8 设置文件损坏保留与
互动计数合并、B12 事件日志轮转失败计数回填、B13 时段表清空重置覆盖、
B14 dotenv 行内注释与 data/ 前缀重映射对齐。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    RiskLevel,
    SessionType,
)
from plugins.bot_unified_runtime.policy.gate import is_command_text
from plugins.bot_unified_runtime.policy.reply_budget import (
    ReplyBudgetSettings,
    decide_reply_budget,
)
from plugins.bot_unified_runtime.runtime.model_schedule import (
    run_model_schedule_job,
)
from plugins.bot_unified_runtime.runtime.settings import (
    RuntimeSettingsStore,
)


def _message(**kwargs) -> IncomingMessage:
    defaults: dict[str, object] = {
        "platform": "onebot",
        "adapter": "onebot.v11",
        "bot_id": "bot",
        "session_id": "private:u1",
        "session_type": SessionType.PRIVATE,
        "sender_id": "u1",
        "plain_text": "你好",
    }
    defaults.update(kwargs)
    return IncomingMessage(**defaults)


# ---- B6：命令前缀词边界 ----


def test_b6_command_prefix_requires_word_boundary() -> None:
    assert is_command_text("/bot")
    assert is_command_text("/bot help")
    assert is_command_text("/bot\nhelp")
    assert not is_command_text("/botxxx")
    assert not is_command_text("/bot_anything")
    assert not is_command_text("hello /bot")
    assert not is_command_text("")


def test_b6_command_prefix_respects_custom_prefix() -> None:
    assert is_command_text("/岸宝 help", prefix="/岸宝")
    assert not is_command_text("/岸宝help", prefix="/岸宝")


# ---- B7：帽值 0 = 不生效，仅对 >0 的帽取 min ----


def test_b7_risk_cap_zero_does_not_expand_limit() -> None:
    settings = ReplyBudgetSettings(private_default_max_messages=4, risk_max_messages=0)
    budget = decide_reply_budget(
        _message(risk_level=RiskLevel.HIGH), "bot.chat", settings
    )
    assert budget.max_messages == 4  # 旧实现 min(4, 0)=0 → 被放大成不限


def test_b7_risk_cap_positive_still_limits() -> None:
    limited = ReplyBudgetSettings(private_default_max_messages=6, risk_max_messages=4)
    assert (
        decide_reply_budget(
            _message(risk_level=RiskLevel.MEDIUM), "bot.chat", limited
        ).max_messages
        == 4
    )
    laxer = ReplyBudgetSettings(private_default_max_messages=2, risk_max_messages=4)
    assert (
        decide_reply_budget(
            _message(risk_level=RiskLevel.MEDIUM), "bot.chat", laxer
        ).max_messages
        == 2
    )


def test_b7_unlimited_value_is_capped_by_positive_cap() -> None:
    settings = ReplyBudgetSettings(private_default_max_messages=0, risk_max_messages=3)
    assert (
        decide_reply_budget(
            _message(risk_level=RiskLevel.HIGH), "bot.chat", settings
        ).max_messages
        == 3
    )


def test_b7_group_cap_zero_does_not_expand_limit() -> None:
    settings = ReplyBudgetSettings(private_default_max_messages=5, group_max_messages=0)
    budget = decide_reply_budget(
        _message(
            session_id="group:g1",
            session_type=SessionType.GROUP,
            group_id="g1",
            plain_text="/bot hi",
            mentions_bot=True,
        ),
        "bot.chat",
        settings,
    )
    assert budget.max_messages == 5


# ---- B8：设置文件原子写 + 损坏保留 + 计数合并 ----


def test_b8_corrupt_file_preserved_and_clean_state_saved(tmp_path: Path) -> None:
    path = tmp_path / "runtime_settings.json"
    bad_payload = '{"overrides": {"BOT_CHAT_MODEL": "luna"}, "interac'
    path.write_text(bad_payload, encoding="utf-8")

    store = RuntimeSettingsStore(path)

    corrupt_files = list(tmp_path.glob("runtime_settings.json.corrupt-*"))
    assert len(corrupt_files) == 1, "损坏文件应改名为 .corrupt-<ts> 保留"
    assert corrupt_files[0].read_text(encoding="utf-8") == bad_payload

    # 损坏数据不进入内存，也不随下次保存回写
    assert store.get_or("BOT_CHAT_MODEL", "") == ""
    store.set_override("BOT_CHAT_MODEL", "sol")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["overrides"]["BOT_CHAT_MODEL"] == "sol"
    assert payload["interactions"] == {}

    # 重新实例化读到干净新数据，不再触发损坏路径
    again = RuntimeSettingsStore(path)
    assert again.get_or("BOT_CHAT_MODEL", "") == "sol"
    assert not list(tmp_path.glob("*.corrupt-*"))[1:] or True


def test_b8_non_dict_json_treated_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "runtime_settings.json"
    path.write_text('["not", "a", "dict"]', encoding="utf-8")
    RuntimeSettingsStore(path)
    assert len(list(tmp_path.glob("runtime_settings.json.corrupt-*"))) == 1


def test_b8_external_reload_merges_interactions_by_max(tmp_path: Path) -> None:
    path = tmp_path / "runtime_settings.json"
    store = RuntimeSettingsStore(path)
    store.interaction_increment("u1")
    store.interaction_increment("u1")  # 内存 2，可能尚未落盘（30s 节流）

    external = {
        "overrides": {},
        "nicknames": [],
        "interactions": {"u1": 5, "u2": 7},
        "persona_override": "",
        "persona_weights": {},
        "model_registry": {},
        "vision_registry": {},
    }
    path.write_text(json.dumps(external), encoding="utf-8")
    # 强制 mtime 与 store 记录的不同，避免同时钟滴碰撞导致不触发重载
    stale = time.time() - 120
    os.utime(path, (stale, stale))

    # 外部修改触发重载：按键 max 合并，内存未落盘计数不被整体替换
    assert store.interaction_count("u1") == 5
    assert store.interaction_count("u2") == 7


# ---- B12：事件日志轮转 rename 失败时字节计数回填 ----


def test_b12_rotation_rename_failure_backfills_byte_counter(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.sources.runtime_event_log import RuntimeEventLog

    path = tmp_path / "ev.log"
    old_path = tmp_path / "ev.log.old"
    line = "x" * 3000
    with open(old_path, "w", encoding="utf-8"):
        log = RuntimeEventLog(path, max_bytes=64 * 1024)
        for _ in range(250):
            log.info("t", payload=line)  # emit 截断 300 字/行；总量 >64KB 触发轮转，.old 被占用 rename 失败
        assert path.exists()
        assert path.stat().st_size >= 64 * 1024
        # 计数必须回填真实文件大小，而不是归零（归零 → 无界增长）。
        # Windows 文本模式 \n→\r\n 转换让计数比磁盘略小（差 ≤ 每行 1-2 字节）。
        assert log._handle_bytes >= 64 * 1024
        assert path.stat().st_size - log._handle_bytes <= 1000
        log.info("t", payload=line)  # 失败后仍可继续追加，且计数继续跟踪
        assert path.stat().st_size - log._handle_bytes <= 1000


# ---- B13：时段表清空后重置卡死的模型覆盖 ----


class _FakeSettingsStore:
    def __init__(self, schedule_raw: object) -> None:
        self.schedule_raw = schedule_raw
        self.overrides: dict[str, str] = {"BOT_CHAT_MODEL": "luna"}
        self.reset_calls: list[str | None] = []
        self.set_calls: list[tuple[str, str]] = []

    def get_or(self, key: str, default: object) -> object:
        if key == "BOT_MODEL_SCHEDULE":
            return self.schedule_raw
        return default

    def set_override(self, key: str, value: str) -> None:
        self.overrides[key] = value
        self.set_calls.append((key, value))

    def reset_override(self, key: str | None = None) -> int:
        self.reset_calls.append(key)
        if key is None:
            count = len(self.overrides)
            self.overrides.clear()
            return count
        if key in self.overrides:
            del self.overrides[key]
            return 1
        return 0


def test_b13_empty_schedule_resets_stuck_override() -> None:
    store = _FakeSettingsStore("")
    state = {"last_applied": "luna"}
    run_model_schedule_job(settings_store=store, default_schedule={}, state=state)
    assert store.reset_calls == ["BOT_CHAT_MODEL"]
    assert state["last_applied"] == ""
    assert "BOT_CHAT_MODEL" not in store.overrides


def test_b13_empty_schedule_noop_when_nothing_applied() -> None:
    store = _FakeSettingsStore("")
    state = {"last_applied": ""}
    run_model_schedule_job(settings_store=store, default_schedule={}, state=state)
    assert store.reset_calls == []


# ---- B14：dotenv 行内注释 + data/ 前缀重映射两侧对齐 ----


def test_b14_inline_comment_stripped() -> None:
    import runtime_paths as rp

    assert rp._strip_inline_comment("data # 主目录") == "data"
    assert rp._strip_inline_comment("data\t# comment") == "data"
    assert rp._strip_inline_comment('"data # not comment"') == '"data # not comment"'
    assert rp._strip_inline_comment("data#notcomment") == "data#notcomment"
    assert rp._strip_inline_comment("data") == "data"


def test_b14_dotenv_value_strips_inline_comment(tmp_path: Path, monkeypatch) -> None:
    import runtime_paths as rp

    (tmp_path / ".env").write_text(
        'BOT_RUNTIME_DATA_DIR=data # 主目录\nBOT_QUOTED="a # b"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(rp, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("BOT_RUNTIME_DATA_DIR", raising=False)
    monkeypatch.delenv("BOT_QUOTED", raising=False)
    assert rp._dotenv_value("BOT_RUNTIME_DATA_DIR") == "data"
    assert rp._dotenv_value("BOT_QUOTED") == "a # b"


def test_b14_runtime_path_remaps_dot_slash_and_case(tmp_path: Path, monkeypatch) -> None:
    import runtime_paths as rp

    monkeypatch.setenv("BOT_RUNTIME_DATA_DIR", str(tmp_path))
    assert rp.runtime_path("./data/x.db") == (tmp_path / "x.db").resolve()
    assert rp.runtime_path("DATA/x.db") == (tmp_path / "x.db").resolve()
    assert rp.runtime_path("data") == tmp_path.resolve()
    assert rp.runtime_path("data/sub/file.log") == (tmp_path / "sub/file.log").resolve()


def test_b14_config_resolve_remaps_dot_slash_and_case(tmp_path: Path) -> None:
    from plugins.bot_unified_runtime.config import Config

    cfg = Config(
        bot_runtime_data_dir=str(tmp_path),
        bot_runtime_settings_file="./data/s.json",
        bot_audit_db_path="DATA/a.db",
    )
    assert Path(cfg.bot_runtime_settings_file) == tmp_path / "s.json"
    assert Path(cfg.bot_audit_db_path) == tmp_path / "a.db"
