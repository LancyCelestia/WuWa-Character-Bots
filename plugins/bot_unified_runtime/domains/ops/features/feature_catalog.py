"""把唯一在册表（Wave 2）投影为控制树；不在运行时扫描源码。

真源指针：本文件不再直接读 ``ROUTE_CAPABILITY_DECLARATIONS`` /
``CONTROLLED_INTERNAL_CAPABILITIES``——两张表降为
``runtime/capability_protocols.CAPABILITY_DESCRIPTOR`` 的声明式输入源。
「哪个能力受门执法、它的 feature id 叫什么」唯一答案 = 该表（规格 §1 D-a/D-f）。
"""
from __future__ import annotations

from dataclasses import replace

from plugins.bot_unified_runtime.control_plane.features import (
    FeatureDescriptor,
    default_feature_descriptors,
)
from plugins.bot_unified_runtime.runtime.capability_protocols import (
    gate_feature_bindings,
    gate_route_projection,
)

RECOVERY_CAPABILITIES = frozenset({"bot.status", "bot.control", "bot.runtime", "bot.audit", "bot.logs", "bot.queue", "bot.send_queue_worker"})


def capability_feature_bindings() -> dict[str, str]:
    """capability_id → feature 节点 id（唯一表的 gate 投影，与迁移前逐键等价）。"""
    return gate_feature_bindings()


# 显式登记真正接线的子功能；未登记内部步骤不假称可独立控制。
#
# 行形如 ``(节点 id, 父节点, 标签, 实现符号, default_enabled)``；第 5 位**逐枚写死**
# （不留「省略即缺省开」的隐式档 —— 那张表要说的是「这一枚今天到底开不开」）。
# **为什么需要第 5 位**：``FeatureSwitchSnapshot
# .enabled()`` 对「未登记 id」恒返回 False（feature_gate.py:35-36 的
# ``states.get(feature_id, False)``），而 ``states`` 只遍历注册表描述符
# （control_plane/features.py:329-331）。根 ``__init__.py:8614`` 一直在问
# ``switches.enabled("bot.plugin.chat.reactions.meme")`` —— 这一枚此前**不在册**，
# 于是「情绪时刻发一张表情包」这条腿在生产结构性死路（与 config 的
# ``bot_reactions_meme_enabled`` 缺省 True 无关：那是第二道门，第一道门先关死）。
# 补登记即通；按「新增自动外发行为不得未经用户点头就上现网」的口径显式置 False，
# 由超管在控制面 / WebUI 打开（父链 ``bot.plugin.chat.reactions`` 缺省开）。
_SUBFEATURE_ROWS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("bot.plugin.poke.reply", "bot.plugin.poke", "戳一戳文字回复", "_handle_poke_notice", True),
    ("bot.plugin.poke.poke_back", "bot.plugin.poke", "戳一戳反戳", "_handle_poke_notice", True),
    ("bot.ingress.file_read", "bot.ingress", "入站文件内容读取", "_incoming_from_nonebot_event", True),
    ("bot.ingress.audio_transcode", "bot.ingress", "语音段预转码", "_transcode_record_segments", True),
    ("bot.ingress.telegram_media", "bot.ingress", "Telegram 媒体文件富化", "_handle_chat", True),
    ("bot.ingress.reply_lookup", "bot.ingress", "引用链远程反查", "_handle_chat", True),
    ("bot.plugin.chat.recent_image", "bot.plugin.chat", "群聊最近图片注入", "_handle_chat", True),
    ("bot.plugin.chat.forward_lookup", "bot.plugin.chat", "合并转发内容反查", "_handle_chat", True),
    ("bot.plugin.chat.video_preprocess", "bot.plugin.chat", "视频理解预处理", "_handle_chat", True),
    ("bot.plugin.chat.parrot", "bot.plugin.chat", "群聊复读自动回应", "_handle_chat", True),
    ("bot.plugin.affinity.passive", "bot.plugin.affinity", "被动好感画像与心情感知", "_handle_chat", True),
    ("bot.plugin.chat.reactions.receive", "bot.plugin.chat.reactions", "接收表情回应上下文", "_handle_msg_emoji_like_notice", True),
    ("bot.plugin.chat.reactions.emotion", "bot.plugin.chat.reactions", "情绪触发表情回应", "_handle_chat", True),
    ("bot.plugin.chat.reactions.after_reply", "bot.plugin.chat.reactions", "回复后表情回应", "_handle_chat", True),
    ("bot.plugin.chat.reactions.meme", "bot.plugin.chat.reactions", "情绪时刻发送表情包", "_handle_chat", False),
    ("bot.plugin.meme_library.auto_absorb", "bot.plugin.meme_library", "群图自动收库", "_handle_meme_absorb", True),
)
SUBFEATURE_DESCRIPTORS = tuple(
    FeatureDescriptor(
        node, parent, "sub_feature", label,
        # 第 5 位=缺省开关，逐枚写死不留隐式缺省：登记一张子功能表最重要的就是
        # 「这一枚今天到底开不开」，靠 `len(row) > 4` 猜等于把它藏进语法里。
        # 只有「新增的自动外发腿」这类需要她本人点头才上线的才写 False。
        default_enabled=default_enabled,
        implementation_ref=f"plugins/bot_unified_runtime/__init__.py#{symbol}",
        documentation_refs=("docs/design/control-plane-registry.md",),
    )
    for row in _SUBFEATURE_ROWS
    for node, parent, label, symbol, default_enabled in (row,)
)


def build_product_descriptors() -> tuple[FeatureDescriptor, ...]:
    rows = {item.id: item for item in default_feature_descriptors()}
    declarations = gate_route_projection()
    for capability_id, feature_id in capability_feature_bindings().items():
        parts = feature_id.split(".")
        for index in range(3, len(parts) + 1):
            node_id = ".".join(parts[:index])
            parent = "bot" if index == 3 else ".".join(parts[:index - 1])
            if node_id not in rows:
                rows[node_id] = FeatureDescriptor(node_id, parent, "plugin" if index == 3 else "feature", node_id)
        node = rows[feature_id]
        declared = declarations.get(capability_id)
        rows[feature_id] = replace(
            node, capability_id=capability_id,
            route_kind=declared[0] if declared else None,
            label=declared[1] if declared else capability_id,
            protected=capability_id in RECOVERY_CAPABILITIES,
        )
    rows["bot.ingress"] = FeatureDescriptor("bot.ingress", "bot", "group", "入站富化")
    rows["bot.plugin.chat.reactions"] = FeatureDescriptor("bot.plugin.chat.reactions", "bot.plugin.chat", "feature", "表情回应")
    for node in SUBFEATURE_DESCRIPTORS:
        if node.id in rows:
            raise ValueError(f"duplicate explicit subfeature: {node.id}")
        rows[node.id] = node
    return tuple(rows.values())
