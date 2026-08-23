from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.audit.file_logger import (
    FileAuditLog,
    build_audit_with_file_log,
)
from plugins.bot_unified_runtime.contracts import (
    AuditRecord,
    RiskLevel,
)
from plugins.bot_unified_runtime.output.renderer import (
    build_forward_output,
    should_forward_long_text,
    split_text_chunks,
)


def test_split_text_chunks_respects_limits():
    text = "\n\n".join(f"第{i}段：" + "内容" * 60 for i in range(12))
    chunks = split_text_chunks(text, node_chars=200, max_nodes=4)

    assert len(chunks) <= 4
    assert all(chunk.strip() for chunk in chunks)
    # 内容不丢失（只允许段落合并时产生少量连接换行差异）。
    joined = "\n".join(chunks)
    assert len(joined) >= len(text) - 60
    assert "第0段" in chunks[0]
    assert "第11段" in chunks[-1]


def test_build_forward_output_structure():
    output = build_forward_output(
        "req_forward",
        "第一段。" + "长内容。" * 200,
        node_chars=200,
        max_nodes=4,
        sender_name="守岸人",
    )

    assert output.content_type == "forward"
    nodes = output.content_ref["messages"]
    assert nodes
    assert all(node["type"] == "node" for node in nodes)
    assert output.text_fallback.startswith("第一段。")


def test_should_forward_long_text_threshold():
    assert should_forward_long_text("短文本", min_chars=1500) is False
    assert should_forward_long_text("长" * 1500, min_chars=1500) is True
    assert should_forward_long_text("", min_chars=100) is False


def test_file_audit_log_writes_redacted_jsonl(tmp_path):
    log_path = tmp_path / "audit.jsonl"
    log = FileAuditLog(log_path, max_bytes=1024)

    log.append(
        AuditRecord(
            request_id="req_1",
            session_id="private:42",
            capability_id="bot.chat",
            stage="policy",
            event="test",
            severity=RiskLevel.LOW,
            public_message="公开说明",
            private_debug="api_key=secret-value-here",
        )
    )

    records = log.read_recent()
    assert len(records) == 1
    assert records[0]["request_id"] == "req_1"
    assert "secret-value-here" not in str(records[0])
    assert "api_key=secret-value-here" not in str(records[0])


def test_build_audit_with_file_log_tees(tmp_path):
    primary = InMemoryAuditLogger()
    log_path = tmp_path / "audit.jsonl"
    repository = build_audit_with_file_log(primary, str(log_path), max_bytes=1024)

    record = AuditRecord(
        request_id="req_2",
        session_id="private:42",
        capability_id="bot.chat",
        stage="transport",
        event="test",
        severity=RiskLevel.LOW,
        public_message="ok",
        private_debug="token=abc123",
    )
    repository.append(record)

    assert len(primary.list_records()) == 1
    log = FileAuditLog(log_path)
    records = log.read_recent()
    assert len(records) == 1
    assert "abc123" not in str(records[0])


def test_build_audit_without_log_file_returns_primary():
    primary = InMemoryAuditLogger()

    assert build_audit_with_file_log(primary, "") is primary


def test_should_forward_long_text_zero_means_never_forward():
    long_text = "鸣潮设定" * 600

    assert should_forward_long_text(long_text, min_chars=0) is False
    assert should_forward_long_text(long_text, min_chars=1500) is True


def test_split_text_chunks_breaks_at_punctuation_keeps_kaomoji_intact():
    paragraph = "鸣" * 880 + "。" + "鸣" * 19 + "(≧▽≦)"
    chunks = split_text_chunks(paragraph, node_chars=900, max_nodes=6)

    assert len(chunks) >= 2
    assert chunks[0].endswith("。")
    assert "(≧▽≦)" in chunks[-1]
