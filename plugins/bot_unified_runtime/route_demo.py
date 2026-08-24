"""基层路由全问法演示与真实烟测（route-demo）。

用法：
    python -m plugins.bot_unified_runtime.route_demo
    python -m plugins.bot_unified_runtime.route_demo --real

离线模式只打印“问法 -> 路由 -> 能力 -> 优先级 -> 归一化命令 -> 理由”，
并把群聊门禁（点名/命令/被动/自动接话）模拟一遍；--real 模式额外用
真实网络跑天气/维基/Epic/历史上的今天/点歌/表情包六条链路，输出
receipt 状态与脱敏正文预览。任何链路失败都返回非零退出码。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from plugins.bot_unified_runtime.audit import InMemoryAuditLogger
from plugins.bot_unified_runtime.capabilities.epic import build_epic_capability
from plugins.bot_unified_runtime.capabilities.meme import build_meme_capability
from plugins.bot_unified_runtime.capabilities.music import build_music_capability
from plugins.bot_unified_runtime.capabilities.today_history import (
    build_today_history_capability,
)
from plugins.bot_unified_runtime.capabilities.weather import build_weather_capability
from plugins.bot_unified_runtime.capabilities.wiki import build_wiki_capability
from plugins.bot_unified_runtime.config import Config
from plugins.bot_unified_runtime.contracts import (
    IncomingMessage,
    ReceiptState,
    SessionType,
)
from plugins.bot_unified_runtime.policy.gate import (
    PolicySettings,
    evaluate_policy,
)
from plugins.bot_unified_runtime.runtime import RuntimePipeline
from plugins.bot_unified_runtime.runtime.aliases import build_command_alias_resolver
from plugins.bot_unified_runtime.runtime.base_router import classify_message_route
from plugins.bot_unified_runtime.sender import InMemorySendQueue

# (分组, 问法)
DEMO_MATRIX: list[tuple[str, str]] = [
    ("昵称命令", "/岸宝帮助"),
    ("昵称命令", "/岸宝天气 杭州"),
    ("昵称命令", "守岸人点歌 晴天"),
    ("管理员命令", "/bot status"),
    ("管理员命令", "/bot routes"),
    ("订阅命令", "/订阅 状态"),
    ("订阅命令", "/bot subscribe add https://space.bilibili.com/3577566"),
    ("自动发送", "报存 给 A 发邮件，主题：周末安排，内容根据你对他们的了解分别写"),
    ("表情包", "/表情 列表"),
    ("表情包", "/meme petpet 可爱"),
    ("点歌模式", "/点歌模式 卡片"),
    ("点歌", "/点歌 晴天"),
    ("历史上的今天", "/历史上的今天"),
    ("维基百科", "/wiki 鸣潮"),
    ("维基百科", "/WIKIPEDIA Python"),
    ("Epic", "/epic"),
    ("Epic", "/Epic Free"),
    ("天气", "/天气 杭州"),
    ("天气", "/查天气 上海"),
    ("自然语言", "帮我查一下杭州天气"),
    ("自然语言", "杭州天气怎么样"),
    ("自然语言", "帮我查天气 杭州"),
    ("自然语言", "来首晴天"),
    ("自然语言", "放首歌 晴天"),
    ("自然语言", "帮我放一首周杰伦的歌"),
    ("自然语言", "帮我查维基 鸣潮"),
    ("自然语言", "今天有什么免费游戏"),
    ("自然语言", "今天历史上发生了什么"),
    ("链接解析", "看这个 https://www.bilibili.com/video/BV1xx411c7mD"),
    ("人格对话", "今天有点累，陪我说说话。"),
    ("人格对话", "漂泊者是谁"),
    ("闲聊不劫持", "今天天气不错"),
    ("闲聊不劫持", "播放量好高"),
]


def _decision_line(text: str, config: Config, alias_resolver) -> dict:
    decision = classify_message_route(text, config=config, alias_resolver=alias_resolver)
    return {
        "text": text,
        "kind": decision.kind.value,
        "priority": decision.priority,
        "capability": decision.capability_id,
        "target": decision.target_capability_id or "",
        "normalized": decision.normalized_text or "",
        "reason": decision.reason,
    }


def _print_matrix(config: Config, alias_resolver) -> None:
    print("=== 1. 问法矩阵：文本 -> 路由 -> 能力 -> 归一化 ===")
    for group, text in DEMO_MATRIX:
        row = _decision_line(text, config, alias_resolver)
        extra = ""
        if row["target"]:
            extra = f" -> 归一化[{row['normalized']}] -> {row['target']}"
        if row["kind"] == "admin":
            extra += " （进入 bot.status 后按子命令分派到 subscribe/download/…）"
        print(
            f"[{group:<6}] {row['text']:<32} => kind={row['kind']:<15} "
            f"priority={row['priority']:<3} capability={row['capability']:<22}"
            f"{extra}  ({row['reason']})"
        )


def _policy_scenario(config: Config, alias_resolver) -> None:
    print("\n=== 2. 群聊门禁模拟（谁会被放行，谁会被静默观察） ===")
    scenarios = [
        ("私聊直接聊天", SessionType.PRIVATE, "你是谁", False, PolicySettings()),
        ("群聊 @机器人", SessionType.GROUP, "你是谁", True, PolicySettings()),
        ("群聊写昵称点名", SessionType.GROUP, "岸宝 帮我查天气", True, PolicySettings()),
        ("群聊管理员命令", SessionType.GROUP, "/bot status", False, PolicySettings()),
        ("群聊昵称命令", SessionType.GROUP, "/岸宝帮助", False, PolicySettings()),
        ("群聊被动消息(默认)", SessionType.GROUP, "大家晚上好", False, PolicySettings()),
        (
            "群聊自动接话(开,概率1)",
            SessionType.GROUP,
            "大家晚上好",
            False,
            PolicySettings(group_auto_reply_enabled=True, group_auto_reply_probability=1.0),
        ),
    ]
    command_check = (
        lambda text: alias_resolver.resolve(text) is not None
        or text.startswith(config.bot_runtime_admin_prefix)
    )
    for label, session_type, text, mention, settings in scenarios:
        settings = PolicySettings(
            group_command_prefix=settings.group_command_prefix,
            extra_command_check=command_check,
            group_auto_reply_enabled=settings.group_auto_reply_enabled,
            group_auto_reply_probability=settings.group_auto_reply_probability,
        )
        message = IncomingMessage(
            platform="qq",
            adapter="onebot.v11",
            bot_id="3958874605",
            session_id=(
                "private:3865067623"
                if session_type is SessionType.PRIVATE
                else "group:1020272595"
            ),
            session_type=session_type,
            sender_id="3865067623",
            group_id="1020272595" if session_type is SessionType.GROUP else None,
            plain_text=text,
            raw_segments=[{"type": "text", "data": {"text": text}}],
            mentions_bot=mention,
            message_id="demo_1",
        )
        evaluation = evaluate_policy(message, "bot.chat", settings=settings)
        print(
            f"- {label:<18} allowed={evaluation.allowed!s:<5} "
            f"reason={evaluation.reason}"
        )


def _capability_smoke(config: Config) -> int:
    print("\n=== 3. 真实接口烟测（--real，网络/服务真实调用） ===")
    audit = InMemoryAuditLogger()
    queue = InMemorySendQueue(audit_logger=audit)
    pipeline = RuntimePipeline(send_queue=queue, audit_logger=audit)

    cases: list[tuple[str, str, Any]] = [
        ("天气", "/天气 杭州", build_weather_capability(config)),
        ("维基", "/wiki 鸣潮", build_wiki_capability(config)),
        ("Epic", "/epic", build_epic_capability(config)),
        ("历史上的今天", "/历史上的今天", build_today_history_capability(config)),
        ("点歌", "/点歌 晴天", build_music_capability(config, default_mode="card")),
    ]
    # 表情包走本地 meme-generator-rs；未启用时按配置执行。
    meme_config = config.model_copy(
        update={"bot_meme_api_enabled": True, "bot_meme_api_output_dir": "data/memes"}
    )
    cases.append(("表情包", "/表情 nokia 无内鬼继续交易", build_meme_capability(meme_config)))

    failures = 0
    for label, text, capability in cases:
        message = IncomingMessage(
            platform="qq",
            adapter="onebot.v11",
            bot_id="3958874605",
            session_id="private:demo",
            session_type=SessionType.PRIVATE,
            sender_id="demo",
            plain_text=text,
            raw_segments=[{"type": "text", "data": {"text": text}}],
            mentions_bot=True,
        )
        receipt = pipeline.handle(message, capability, capability_id=f"bot.{label}")
        preview = "".join(receipt.public_message.splitlines()[:2])[:70]
        if queue.sent_requests:
            content = queue.sent_requests[-1].content.text_fallback
            if content.strip():
                preview = "".join(content.splitlines()[:2])[:70]
        ok = receipt.state is ReceiptState.SENT
        if not ok:
            failures += 1
        print(f"- {label:<6} state={receipt.state.value:<10} preview={preview}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="基层路由全问法演示与真实烟测")
    parser.add_argument("--real", action="store_true", help="额外执行真实网络/服务烟测")
    args = parser.parse_args()

    from plugins.bot_unified_runtime.smoke import load_smoke_config

    try:
        config = load_smoke_config(None)
    except Exception as exc:  # noqa: BLE001
        print(f"config_error={exc}")
        return 2
    alias_resolver = build_command_alias_resolver(config)

    _print_matrix(config, alias_resolver)
    _policy_scenario(config, alias_resolver)
    failures = 0
    if args.real:
        failures = _capability_smoke(config)
    print(f"\nroute-demo done; real_failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
