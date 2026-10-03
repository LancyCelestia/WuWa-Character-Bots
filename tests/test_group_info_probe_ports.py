"""两条补接的在册探测（2026-10-03 检索与知识波·施工席2）的 group_info 侧判据锁。

锁三件事：

① 常量与缓存登记：``nc_get_user_status`` / ``get_group_root_files`` 两口的
   kind/动作名/TTL 必须登记在两处共享缓存的 TTL 表里（未登记＝TTL 0＝永不缓存
   ＝每轮一次 RPC，那是 group_info 模块头点名过的坑）。
② ``qq_user_status_from_payload``：扁平码 / 嵌套对象 / 非码形态 / 空值各态，
   渲染必须走 ``_qq_status_label`` 唯一真身（不抄第二份值表）。
③ 群文件全量口的消费纪律锁在画像层（tests/test_conversation_profile_meta.py），
   本件只锁解析面的输入侧常量存在且非空——候选表空表＝解析永远 missing 的哑面。

全部离线、零网络、零 Runtime 写。
"""

from __future__ import annotations

import pytest

from plugins.bot_unified_runtime.domains.chat_reply.capabilities import group_info as gi
from plugins.bot_unified_runtime.domains.chat_reply.runtime import (
    conversation_profile as cp,
)


def test_probe_port_constants_are_registered_for_caching() -> None:
    for cache, owner in ((gi._SHARED_CACHE, "group_info"), (cp.make_shared_cache(), "profile")):
        table = cache._ttl
        assert table.get(gi.KIND_QQ_USER_STATUS) == gi.QQ_USER_STATUS_TTL_SECONDS, owner
        assert table.get(gi.KIND_GROUP_ROOT_FILES) == gi.GROUP_ROOT_FILES_TTL_SECONDS, owner
    assert gi.QQ_USER_STATUS_ACTION == "nc_get_user_status"
    assert gi.GROUP_ROOT_FILES_ACTION == "get_group_root_files"
    # 画像层看到的常量必须就是 group_info 的同一对象（不抄第二份）。
    assert cp.KIND_QQ_USER_STATUS is gi.KIND_QQ_USER_STATUS
    assert cp.qq_user_status_from_payload is gi.qq_user_status_from_payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": 1}, "在线（状态码 1）"),
        ({"status": 0}, "离线（状态码 0）"),
        ({"status": {"status": 2, "key": "offline"}}, "隐身（状态码 2）"),
        ({"online_status": 10}, "状态码 10（动作册没给中文名，不替你猜）"),
        ({"ext_status": "offline"}, "状态 offline（动作册没给这一形态的中文名，不替你猜）"),
    ],
)
def test_qq_user_status_from_payload_known_shapes(payload: dict, expected: str) -> None:
    assert gi.qq_user_status_from_payload(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [{}, {"unrelated": 1}, {"status": None}, {"status": ""}, None, "text", []],
)
def test_qq_user_status_from_payload_unreadable_shapes_return_empty(payload: object) -> None:
    assert gi.qq_user_status_from_payload(payload) == ""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
