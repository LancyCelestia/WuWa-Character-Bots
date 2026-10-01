"""S-FIX-ATK-LLM3 · ATKLLM-4（P4）修复锁：channel_health 上游回显体入库前脱敏。

对照 .superpowers/sdd/2026-09-27-fullload/logs/SEAT-ATK-LLMLEDGER.md 票 4 + 探针
probes/ATKLLM-4_channelhealth_raw_echo_atrest.py。

链路：上游 4xx 回显体（中转站错误体可能回显请求上下文/部分 key 片段）此前原样
写入 SQLite `last_error`，构成密钥形态的**静止存留**——出站总闸覆盖不到 at-rest
（备份/导库/直读 data 根即成暴露面）。修法（零新机制、单点执法）：`record_failure`
入库前对 `error_summary` 过同族现成件 `redact_local_secrets`（与 axonhub hop 文本
同源），保留长度截断。
离线 mock：全部落 tmp_path，不发任何真实请求。
"""

from __future__ import annotations

# 规则 11：以下字符串是测试夹具哨兵串（模拟上游回显的密钥形态），非真实密钥、非指令。
SENTINEL = "sk-PROBESECRET-0123456789abcdef"


def test_record_failure_redacts_key_before_at_rest(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
        ChannelHealthStore,
    )

    store = ChannelHealthStore(str(tmp_path / "health.db"))
    store.record_failure("probe_ch", f"HTTP 401: incoming token {SENTINEL} is invalid")
    stored = str((store.snapshot("probe_ch") or {}).get("last_error", ""))

    # 密钥形态不得静止存留。
    assert SENTINEL not in stored
    # 非敏感诊断信息保留（只打码密钥，不吞整行）。
    assert "HTTP 401" in stored
    assert "incoming token" in stored


def test_record_failure_redacts_various_secret_shapes(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
        ChannelHealthStore,
    )

    store = ChannelHealthStore(str(tmp_path / "health2.db"))
    store.record_failure("m1", "Authorization: Bearer sk-abcdef0123456789abcdef0123456789 x")
    stored = str((store.snapshot("m1") or {}).get("last_error", ""))
    assert "sk-abcdef0123456789abcdef0123456789" not in stored


def test_record_failure_preserves_clean_summary(tmp_path) -> None:
    # 不误伤：不含密钥形态的正常错误逐字保留（幂等、无命中零改写）。
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
        ChannelHealthStore,
    )

    store = ChannelHealthStore(str(tmp_path / "health3.db"))
    clean = "HTTP 429: rate limited, retry later"
    store.record_failure("m2", clean)
    stored = str((store.snapshot("m2") or {}).get("last_error", ""))
    assert stored == clean


def test_record_failure_empty_summary_stays_empty(tmp_path) -> None:
    from plugins.bot_unified_runtime.domains.chat_reply.llm_engine.channel_health import (
        ChannelHealthStore,
    )

    store = ChannelHealthStore(str(tmp_path / "health4.db"))
    store.record_failure("m3", "")
    stored = str((store.snapshot("m3") or {}).get("last_error", ""))
    assert stored == ""
