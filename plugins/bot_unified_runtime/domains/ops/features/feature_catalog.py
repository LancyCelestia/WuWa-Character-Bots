"""把现有显式能力声明投影为控制树；不在运行时扫描源码。"""
from __future__ import annotations

from dataclasses import replace

from plugins.bot_unified_runtime.control_plane.features import (
    FeatureDescriptor,
    default_feature_descriptors,
)
from plugins.bot_unified_runtime.runtime.capability_registry import (
    CONTROLLED_INTERNAL_CAPABILITIES,
    ROUTE_CAPABILITY_DECLARATIONS,
)

RECOVERY_CAPABILITIES = frozenset({"bot.status", "bot.control", "bot.runtime", "bot.audit", "bot.logs", "bot.queue", "bot.send_queue_worker"})


def capability_feature_bindings() -> dict[str, str]:
    ids = {item.capability_id for item in ROUTE_CAPABILITY_DECLARATIONS if item.has_rule}
    ids.update(CONTROLLED_INTERNAL_CAPABILITIES)
    return {item: item.replace("bot.", "bot.plugin.", 1) for item in sorted(ids)}


# 显式登记真正接线的子功能；未登记内部步骤不假称可独立控制。
_SUBFEATURE_ROWS = (
    ("bot.plugin.poke.reply", "bot.plugin.poke", "戳一戳文字回复", "_handle_poke_notice"),
    ("bot.plugin.poke.poke_back", "bot.plugin.poke", "戳一戳反戳", "_handle_poke_notice"),
    ("bot.ingress.file_read", "bot.ingress", "入站文件内容读取", "_incoming_from_nonebot_event"),
    ("bot.ingress.audio_transcode", "bot.ingress", "语音段预转码", "_transcode_record_segments"),
    ("bot.ingress.telegram_media", "bot.ingress", "Telegram 媒体文件富化", "_handle_chat"),
    ("bot.ingress.reply_lookup", "bot.ingress", "引用链远程反查", "_handle_chat"),
    ("bot.plugin.chat.recent_image", "bot.plugin.chat", "群聊最近图片注入", "_handle_chat"),
    ("bot.plugin.chat.forward_lookup", "bot.plugin.chat", "合并转发内容反查", "_handle_chat"),
    ("bot.plugin.chat.video_preprocess", "bot.plugin.chat", "视频理解预处理", "_handle_chat"),
    ("bot.plugin.chat.parrot", "bot.plugin.chat", "群聊复读自动回应", "_handle_chat"),
    ("bot.plugin.affinity.passive", "bot.plugin.affinity", "被动好感画像与心情感知", "_handle_chat"),
    ("bot.plugin.chat.reactions.receive", "bot.plugin.chat.reactions", "接收表情回应上下文", "_handle_msg_emoji_like_notice"),
    ("bot.plugin.chat.reactions.emotion", "bot.plugin.chat.reactions", "情绪触发表情回应", "_handle_chat"),
    ("bot.plugin.chat.reactions.after_reply", "bot.plugin.chat.reactions", "回复后表情回应", "_handle_chat"),
    ("bot.plugin.meme_library.auto_absorb", "bot.plugin.meme_library", "群图自动收库", "_handle_meme_absorb"),
)
SUBFEATURE_DESCRIPTORS = tuple(
    FeatureDescriptor(
        node, parent, "sub_feature", label,
        implementation_ref=f"plugins/bot_unified_runtime/__init__.py#{symbol}",
        documentation_refs=("docs/design/control-plane-registry.md",),
    )
    for node, parent, label, symbol in _SUBFEATURE_ROWS
)


def build_product_descriptors() -> tuple[FeatureDescriptor, ...]:
    rows = {item.id: item for item in default_feature_descriptors()}
    declarations = {item.capability_id: item for item in ROUTE_CAPABILITY_DECLARATIONS if item.has_rule}
    for capability_id, feature_id in capability_feature_bindings().items():
        parts = feature_id.split(".")
        for index in range(3, len(parts) + 1):
            node_id = ".".join(parts[:index])
            parent = "bot" if index == 3 else ".".join(parts[:index - 1])
            if node_id not in rows:
                rows[node_id] = FeatureDescriptor(node_id, parent, "plugin" if index == 3 else "feature", node_id)
        node = rows[feature_id]
        declaration = declarations.get(capability_id)
        rows[feature_id] = replace(
            node, capability_id=capability_id,
            route_kind=declaration.value if declaration else None,
            label=declaration.label if declaration else capability_id,
            protected=capability_id in RECOVERY_CAPABILITIES,
        )
    rows["bot.ingress"] = FeatureDescriptor("bot.ingress", "bot", "group", "入站富化")
    rows["bot.plugin.chat.reactions"] = FeatureDescriptor("bot.plugin.chat.reactions", "bot.plugin.chat", "feature", "表情回应")
    for node in SUBFEATURE_DESCRIPTORS:
        if node.id in rows:
            raise ValueError(f"duplicate explicit subfeature: {node.id}")
        rows[node.id] = node
    return tuple(rows.values())
