"""P0 性能落地回归：命令能力 offload 契约、诊断文件读缓存、affinity 复用、内存仓库有界。

对应 2026-09 性能审计 P0-1/2/3/4 四项修复的行为契约，全部离线。
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------- P0-3 offload 契约


def test_network_command_capabilities_are_offloaded():
    """凡走网络/重 IO 的命令能力 id 必须在 offload 集，否则会冻结事件循环。"""
    from plugins.bot_unified_runtime import OFFLOADED_CAPABILITY_IDS

    required = {
        "bot.context",
        "bot.help",
        "bot.llm",
        "bot.dialogue",
        "bot.weather",
        "bot.music",
        "bot.wiki",
        "bot.epic",
        "bot.today_history",
        "bot.subscribe",
        "bot.meme_library",
        "bot.download",
        "bot.search",
    }
    missing = required - set(OFFLOADED_CAPABILITY_IDS)
    assert not missing, f"以下能力会同步阻塞事件循环，必须加入 offload 集: {sorted(missing)}"


# ---------------------------------------------------------------- P0-1 诊断缓存


@pytest.fixture()
def _clean_readiness_cache():
    # v21r2 RWOC：config_readiness 真身迁 domains/core/config/；monkeypatch 拦截
    # canonical 内部调用必须绑 canonical（垫片对象 setattr 不穿透，见 woc 日志 §六）。
    from plugins.bot_unified_runtime.domains.core.config import config_readiness

    config_readiness._reset_readiness_cache()
    yield
    config_readiness._reset_readiness_cache()


def _smoke_config(persona_path):
    from plugins.bot_unified_runtime.config import Config

    # 用真实 Config 默认值打底，避免逐个追补 run_config_smoke 读取的字段。
    return Config().model_copy(
        update={
            "bot_persona_files": [str(persona_path)],
            "bot_knowledge_files": [],
            "bot_chat_provider": "static",
        }
    )


def test_run_config_smoke_caches_file_reads(tmp_path, monkeypatch, _clean_readiness_cache):
    # v21r2 RWOC：config_readiness 真身迁 domains/core/config/；monkeypatch 拦截
    # canonical 内部调用必须绑 canonical（垫片对象 setattr 不穿透，见 woc 日志 §六）。
    from plugins.bot_unified_runtime.domains.core.config import config_readiness

    persona = tmp_path / "persona.md"
    persona.write_text("人格内容\n", encoding="utf-8")
    config = _smoke_config(persona)

    calls: list[str] = []
    real_load = config_readiness.load_character_document

    def counting_load(path):
        calls.append(str(path))
        return real_load(path)

    monkeypatch.setattr(config_readiness, "load_character_document", counting_load)

    first = config_readiness.run_config_smoke(config)
    second = config_readiness.run_config_smoke(config)
    assert len(calls) == 1, "文件未变更时第二次体检不应重读盘"
    assert first == second

    os.utime(persona, ns=(1_000_000_000_000, 1_000_000_000_000))
    persona.write_text("人格内容改\n", encoding="utf-8")
    config_readiness.run_config_smoke(config)
    assert len(calls) == 2, "文件变更后应重新读取"


def test_run_config_smoke_cache_distinguishes_files(tmp_path, _clean_readiness_cache):
    # v21r2 RWOC：config_readiness 真身迁 domains/core/config/；monkeypatch 拦截
    # canonical 内部调用必须绑 canonical（垫片对象 setattr 不穿透，见 woc 日志 §六）。
    from plugins.bot_unified_runtime.domains.core.config import config_readiness

    config_a = _smoke_config(tmp_path / "a.md")
    (tmp_path / "a.md").write_text("A\n", encoding="utf-8")
    config_b = _smoke_config(tmp_path / "b.md")
    (tmp_path / "b.md").write_text("B\n", encoding="utf-8")
    assert config_readiness.run_config_smoke(config_a)["persona_total_chars"] == 1
    assert config_readiness.run_config_smoke(config_b)["persona_total_chars"] == 1


# ---------------------------------------------------------------- P0-2 affinity 复用


@pytest.fixture()
def _clean_affinity_cache():
    import plugins.bot_unified_runtime as plugin

    plugin._reset_affinity_store_cache()
    yield
    plugin._reset_affinity_store_cache()


def test_build_character_affinity_store_reuses_instance(
    tmp_path, monkeypatch, _clean_affinity_cache
):
    import plugins.bot_unified_runtime as plugin
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    monkeypatch.setattr(
        providers,
        "build_runtime_data_path",
        lambda config, value: tmp_path / "affinity.sqlite3",
    )
    config = SimpleNamespace(bot_affinity_enabled=True)

    store_a = plugin.build_character_affinity_store(config)
    store_b = plugin.build_character_affinity_store(config)
    assert store_a is store_b, "同 db_path 必须复用同一实例，禁止每消息重建"


def test_build_character_affinity_store_disabled(tmp_path, monkeypatch, _clean_affinity_cache):
    import plugins.bot_unified_runtime as plugin
    from plugins.bot_unified_runtime.domains.chat_reply.character import providers

    monkeypatch.setattr(
        providers,
        "build_runtime_data_path",
        lambda config, value: tmp_path / "affinity.sqlite3",
    )
    assert (
        plugin.build_character_affinity_store(SimpleNamespace(bot_affinity_enabled=False))
        is None
    )


# ---------------------------------------------------------------- P0-4 内存仓库有界


def _audit_record(request_id: str):
    from plugins.bot_unified_runtime.contracts import AuditRecord, RiskLevel

    return AuditRecord(
        request_id=request_id,
        session_id="private:1",
        capability_id="bot.chat",
        stage="test",
        event="test_event",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="debug",
    )


def test_in_memory_audit_logger_bounded():
    from plugins.bot_unified_runtime.domains.ops.audit.logger import InMemoryAuditLogger

    logger = InMemoryAuditLogger(max_entries=3)
    for index in range(5):
        logger.append(_audit_record(f"req-{index}"))

    records = logger.list_records()
    assert len(records) == 3
    assert [record.request_id for record in records] == ["req-2", "req-3", "req-4"]
    # 按 request_id 过滤同样只看到未淘汰的
    assert [r.request_id for r in logger.list_records("req-0")] == []
    assert [r.request_id for r in logger.list_records("req-4")] == ["req-4"]


def test_in_memory_audit_logger_default_backward_compatible():
    from plugins.bot_unified_runtime.domains.ops.audit.logger import InMemoryAuditLogger

    logger = InMemoryAuditLogger()
    logger.append(_audit_record("req-1"))
    assert [r.request_id for r in logger.list_records("req-1")] == ["req-1"]


def _send_request(request_id: str, dedupe_key: str):
    from plugins.bot_unified_runtime.contracts import (
        PrivacyLevel,
        RenderedOutput,
        SendPolicy,
        SendRequest,
        SessionType,
    )

    return SendRequest(
        request_id=request_id,
        session_id="private:1",
        target_scope=SessionType.PRIVATE,
        target_id="1",
        capability_id="bot.chat",
        content=RenderedOutput(
            request_id=request_id,
            content_type="text",
            content_ref={},
            text_fallback="hi",
            privacy_level=PrivacyLevel.PERSONAL,
        ),
        send_policy=SendPolicy.IMMEDIATE,
        priority="normal",
        max_messages=1,
        dedupe_key=dedupe_key,
        cooldown_key="private:1",
        privacy_level=PrivacyLevel.PERSONAL,
        persona_profile_id="default",
    )


def test_in_memory_send_queue_bounded():
    from plugins.bot_unified_runtime.domains.ops.audit.logger import InMemoryAuditLogger
    from plugins.bot_unified_runtime.sender.queue import InMemorySendQueue

    queue = InMemorySendQueue(audit_logger=InMemoryAuditLogger(), max_requests=3)
    for index in range(5):
        queue.submit(_send_request(f"req-{index}", f"dedupe-{index}"))

    assert len(queue.sent_requests) == 3
    assert [r.request_id for r in queue.sent_requests] == ["req-2", "req-3", "req-4"]
    assert queue.find_request("req-0") is None
    assert queue.find_request("req-4") is not None


def test_in_memory_receipt_repository_bounded():
    from plugins.bot_unified_runtime.contracts import DeliveryReceipt, ReceiptState
    from plugins.bot_unified_runtime.domains.transport.sender.receipts import (
        InMemoryReceiptRepository,
    )

    repository = InMemoryReceiptRepository(max_receipts=3)

    def receipt(request_id: str):
        return DeliveryReceipt(
            request_id=request_id,
            state=ReceiptState.SENT,
            transport="test",
            public_message="ok",
        )

    for index in range(5):
        repository.record(receipt(f"req-{index}"))

    assert len(repository.list_receipts()) == 3
    assert repository.find("req-0") is None
    assert repository.find("req-4") is not None
