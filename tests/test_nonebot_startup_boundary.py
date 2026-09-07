from __future__ import annotations

from plugins.bot_unified_runtime import defer_optional_subscription_registration


def test_optional_subscription_failure_is_deferred():
    def register(*_args, **_kwargs):
        raise OSError("subscription database is not writable")

    result = defer_optional_subscription_registration(register)

    assert result.status == "deferred"
    assert result.context == {}
    assert result.error_kind == "OSError"