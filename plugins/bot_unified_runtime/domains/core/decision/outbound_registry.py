"""V2.1 S6 出站收编注册表层（A16）：Transport 固定映射注册表 + 入口接管登记表。

合同来源：
- 主规范 §10：「Transport固定映射平台方法，不接原始API名」「启动门拒绝
  未登记入口/出站绕行」。
- A1 冻结清单（docs/design/v21-s0-inventory.md §2）：50 matcher / 12 调度族 /
  62 控制面路由 / 直发出站嫌疑点（含取证坐标）——本模块是其结构化数据形态。
- 风险 5（docs/design/v21-risk-red-report.md）：直连坐标复核来源。

诚实边界：
- Transport 条目全部为**占位**（``bound_handler=None``，status="placeholder"）；
  真实 sender 绑定经 ``bind_handler`` 由接线席位执行。平台方法名只收录有
  出处的字面量（evidence 字段给出坐标或标准来源），绝不拼接合成。
- 接管登记表是 A1 冻结快照的结构化投影，不是实时状态；行号随工作树漂移，
  以 A1 冻结时刻为准（A1 原文已声明）。
- v1.py 路由明细 A1 只冻结到分组粒度（28 条中 26 条可从分组清单枚举），
  登记 group 级条目并如实记录 members 覆盖数，不臆造缺额路由名。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "DirectSendCategory",
    "DirectSendEntry",
    "EntryKind",
    "MatcherEntry",
    "MigrationStatus",
    "RouteGroupEntry",
    "SchedulerEntry",
    "TakeoverChecklist",
    "TakeoverRegistry",
    "TransportChannel",
    "TransportEntry",
    "TransportPlatform",
    "TransportRegistry",
    "UnregisteredTransportError",
    "build_default_takeover_registry",
    "build_default_transport_registry",
]


# ---------------------------------------------------------------------------
# Transport 固定映射注册表
# ---------------------------------------------------------------------------


class TransportPlatform(str, Enum):
    QQ = "qq"
    TELEGRAM = "telegram"
    MAIL = "mail"
    CONSOLE = "console"


class TransportChannel(str, Enum):
    SEND_MESSAGE = "send_message"
    SEND_FILE = "send_file"
    SEND_MAIL = "send_mail"
    STICKER = "sticker"
    REACTION = "reaction"
    POKE = "poke"
    EDIT = "edit"
    DELETE = "delete"


@dataclass(frozen=True)
class TransportEntry:
    """一条固定映射：平台 × 通道 → 显式登记的平台方法名（字面量，禁拼接）。

    ``methods`` 按会话形态给出方法名（QQ 私聊/群聊方法名不同）；单方法通道
    用 {"*": 名字}。``evidence`` 记录方法名出处（file:line 坐标或标准来源），
    无出处的名字不收录。``handler`` 由 ``bind_handler`` 运行时绑定（真实
    sender 通道本体），占位阶段恒为 None。
    """

    platform: TransportPlatform
    channel: TransportChannel
    methods: Mapping[str, str]
    description: str
    evidence: str
    status: str = "placeholder"  # placeholder / bound
    handler: Callable[[Any], Any] | None = None

    def platform_method_for(self, session_type: str = "*") -> str:
        """查显式登记的方法名；未登记组合显式报错（绝不合成 API 名）。"""
        if session_type in self.methods:
            return self.methods[session_type]
        if "*" in self.methods:
            return self.methods["*"]
        raise UnregisteredTransportError(
            f"no registered platform method for {self.platform.value}/"
            f"{self.channel.value} session_type={session_type!r} "
            "(fixed mapping only; synthesizing API names is forbidden)"
        )

    def with_handler(self, handler: Callable[[Any], Any]) -> TransportEntry:
        return TransportEntry(
            platform=self.platform,
            channel=self.channel,
            methods=dict(self.methods),
            description=self.description,
            evidence=self.evidence,
            status="bound",
            handler=handler,
        )


class UnregisteredTransportError(Exception):
    """未注册的平台方法/通道组合：显式错误（§10 启动门拒绝出站绕行同源）。"""


class TransportRegistry:
    """固定映射注册表：resolve 只回登记条目，未注册即显式错误。"""

    def __init__(self) -> None:
        self._entries: dict[tuple[TransportPlatform, TransportChannel], TransportEntry] = {}

    def register(self, entry: TransportEntry, *, replace: bool = False) -> None:
        key = (entry.platform, entry.channel)
        if key in self._entries and not replace:
            raise ValueError(
                f"transport already registered: {entry.platform.value}/{entry.channel.value}"
            )
        self._entries[key] = entry

    def bind_handler(
        self,
        platform: TransportPlatform,
        channel: TransportChannel,
        handler: Callable[[Any], Any],
    ) -> TransportEntry:
        """真实 sender 绑定接口：绑定后条目 status=bound（条目不可变，替换实例）。"""
        entry = self.resolve(platform, channel)
        bound = entry.with_handler(handler)
        self._entries[(platform, channel)] = bound
        return bound

    def resolve(
        self,
        platform: TransportPlatform,
        channel: TransportChannel,
    ) -> TransportEntry:
        entry = self._entries.get((platform, channel))
        if entry is None:
            raise UnregisteredTransportError(
                f"unregistered transport: platform={platform.value} channel={channel.value}"
            )
        return entry

    def entries(self) -> list[TransportEntry]:
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


def build_default_transport_registry() -> TransportRegistry:
    """占位登记表：QQ/TG/Mail/sticker/reaction/poke/edit/delete 通道全占位。

    方法名出处（evidence）全部来自 A1 冻结清单 §2.4 / 风险 5 取证坐标，
    或 OneBot v11 / Telegram Bot API 标准方法面；真实 sender 绑定留接口。
    Telegram POKE 有意不注册（平台无此通道）——resolve 显式报错即契约行为。
    """
    reg = TransportRegistry()
    placeholder = "placeholder"

    def entry(
        platform: TransportPlatform,
        channel: TransportChannel,
        methods: Mapping[str, str],
        description: str,
        evidence: str,
    ) -> TransportEntry:
        return TransportEntry(
            platform=platform,
            channel=channel,
            methods=dict(methods),
            description=description,
            evidence=evidence,
            status=placeholder,
        )

    # QQ（OneBot v11 / SnowLuma）
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.SEND_MESSAGE,
        {"private": "send_private_msg", "group": "send_group_msg"},
        "QQ 文本/段消息发送（SendQueue worker 通道本体）",
        "v21-s0-inventory §2.4（sender/onebot.py:444,449,469,477 通道本体；"
        "原四处待收编绕行点已由 S0-ROOT-c 收编为 *_via_queue 门开分支（门缺省 "
        "False=门关直连等价；REG-REFRESH 2026-09-19 复核门关分支现坐标 "
        "4440-4444/5378-5382/5730-5740/5526-5538，行号会漂以符号 grep 复核））",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.SEND_FILE,
        {"private": "upload_private_file", "group": "upload_group_file"},
        "QQ 文件出站（file_gateway Phase-1 deliver 通道）",
        "v21-s0-inventory §2.4（domains/transport/sender/file_gateway.py:356-412 "
        "_deliver_onebot=通道本体；reorg 前 shim 旧坐标的 PENDING_RULING 已依 "
        "DIRECT-PLAN §二④ 改判 CHANNEL_BODY；v21r4-b S0-COLLECT 2026-09-18）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.DELETE,
        {"*": "delete_msg"},
        "QQ 撤回（dirty guard 等 by-design 撤回面）",
        "v21-s0-inventory §2.4（__init__.py delete_msg；REG-REFRESH 2026-09-19 复核"
        "现坐标 :4978，原登记 :4569 已漂移）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.POKE,
        {"group": "group_poke", "private": "friend_poke"},
        "QQ 戳一戳（回戳 v2 by-design 副作用；L34 已收编=executor 经本映射解析方法名）",
        "v21-risk-red-report 风险5（原直连 :4745-4746/:4751 已随收编消失；现执行面="
        "control_plane/dispatcher.py:162-220，装配 __init__.py:5049-5099；"
        "REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.REACTION,
        {"*": "set_msg_emoji_like"},
        "QQ 贴表情（贴纸回应 v2 by-design 副作用；L35 已收编=统一出站面经本映射）",
        "v21-risk-red-report 风险5（真身 domains/meme/reactions/engine.py:754-782 "
        "react_to_message→executor；runtime/ 旧路径为 shim；REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.EDIT,
        {"group": "edit_msg", "private": "edit_msg"},
        "QQ 消息编辑（NapCat 扩展方法；OneBot v11 标准无编辑面）",
        "NapCat 扩展 API 占位——OneBot v11 标准无此方法，bind 前必须对生产 "
        "NapCat 实测验证（A1/风险5 清单未取证，如实标注待验证）",
    ))
    reg.register(entry(
        TransportPlatform.QQ, TransportChannel.STICKER,
        {"private": "send_private_msg", "group": "send_group_msg"},
        "QQ 表情包/贴纸发送（meme 图走消息通道，方法同 SEND_MESSAGE）",
        "v21-s0-inventory §2.4（sender/onebot.py 通道本体）",
    ))

    # Telegram（Bot API 标准方法面；set_message_reaction 坐标已取证）
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.SEND_MESSAGE,
        {"*": "sendMessage"},
        "TG 消息发送（不设 Markdown parse_mode，§10 纯文本契约）",
        "Telegram Bot API 标准（发送通道本体）",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.EDIT,
        {"*": "editMessageText"},
        "TG 消息编辑",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.DELETE,
        {"*": "deleteMessage"},
        "TG 消息撤回",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.REACTION,
        {"*": "set_message_reaction"},
        "TG 贴 reaction（docstring 自述未接线触发点；出站面已统一经 executor）",
        "v21-risk-red-report 风险5（真身 domains/meme/reactions/engine.py:785-813 "
        "react_telegram_message；REG-REFRESH 2026-09-19）",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.SEND_FILE,
        {"*": "sendDocument"},
        "TG 文件出站",
        "Telegram Bot API 标准",
    ))
    reg.register(entry(
        TransportPlatform.TELEGRAM, TransportChannel.STICKER,
        {"*": "sendSticker"},
        "TG 贴纸发送",
        "Telegram Bot API 标准",
    ))
    # TG POKE：有意不注册（平台无 poke 通道）→ resolve 显式 UnregisteredTransportError。

    # Mail
    reg.register(entry(
        TransportPlatform.MAIL, TransportChannel.SEND_MAIL,
        {"*": "smtp_send"},
        "邮件发送（mail 适配器通道本体）",
        "v21-s0-inventory §2.4（sender/onebot.py 合法通道族；mail 适配器 SMTP 出站）",
    ))

    # Console
    reg.register(entry(
        TransportPlatform.CONSOLE, TransportChannel.SEND_MESSAGE,
        {"*": "console_print"},
        "控制台适配器出站（开发/验收用）",
        "适配器面（console 适配器，无平台 API 名；占位名仅为注册表占位）",
    ))
    return reg


# ---------------------------------------------------------------------------
# 入口接管登记表（A1 冻结清单的结构化投影）
# ---------------------------------------------------------------------------


class EntryKind(str, Enum):
    MATCHER = "matcher"
    SCHEDULER = "scheduler"
    CONTROL_ROUTE = "control_route"


class MigrationStatus(str, Enum):
    LEGACY = "legacy"  # 旧入口仍在岗
    TAKEOVER_READY = "takeover_ready"  # 已按 checklist 备妥，待切换
    TAKEN_OVER = "taken_over"  # 已收编（本轮无）


@dataclass(frozen=True)
class TakeoverChecklist:
    """接管前三问（接线席位逐项落答案后才能置 takeover_ready）。

    - idempotency_key_source：幂等键来源（平台+事件id+入口kind 的具体取值点）
    - feature_gate：FeatureGate id（或 none=无开关，须给理由）
    - trace_point：Trace 贯通点（事件入口/出站回执的 trace 注入位置）
    """

    idempotency_key_source: str = "todo"
    feature_gate: str = "todo"
    trace_point: str = "todo"

    def is_complete(self) -> bool:
        return all(
            value != "todo" and bool(value.strip())
            for value in (self.idempotency_key_source, self.feature_gate, self.trace_point)
        )


@dataclass(frozen=True)
class MatcherEntry:
    name: str
    location: str  # __init__.py:4398 形态（A1 冻结坐标）
    matcher_type: str  # on_message / on_notice / on_command
    priority: int | None  # A1 未冻结 priority 的如实为 None
    route_kind_hint: str  # 功能名提示；精确 RouteKind 以 base_router ROUTE_RULES 为准
    status: MigrationStatus = MigrationStatus.LEGACY
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)
    note: str = ""  # 接线席收编指定/坐标审计留痕（与 Scheduler/RouteGroup 条目同构）


@dataclass(frozen=True)
class SchedulerEntry:
    family: str
    register_location: str
    add_job_locations: tuple[str, ...]
    status: MigrationStatus = MigrationStatus.LEGACY
    note: str = ""
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)


@dataclass(frozen=True)
class RouteGroupEntry:
    """控制面路由组：A1 以文件分组冻结（62 条）；v1.py 明细仅冻结到分组。"""

    module: str  # control_plane/api/v1.py
    prefix: str
    route_count: int  # A1 冻结的组内路由数（计数为准）
    members: tuple[str, ...]  # 可从 A1 分组清单枚举的明细；不臆造缺额
    status: MigrationStatus = MigrationStatus.LEGACY
    note: str = ""
    checklist: TakeoverChecklist = field(default_factory=TakeoverChecklist)


class DirectSendCategory(str, Enum):
    BYPASS_SUSPECT = "bypass_suspect"  # 绕 SendQueue 嫌疑（首要核对）
    BY_DESIGN = "by_design"  # 设计上旁路（poke/贴纸/撤回等，待收编裁决）
    CHANNEL_BODY = "channel_body"  # 合法通道本体（非绕行）
    PENDING_RULING = "pending_ruling"  # 待裁决（file_gateway 等）
    READ_PATH = "read_path"  # 读路径非出站（甄别用）


@dataclass(frozen=True)
class DirectSendEntry:
    location: str
    api: str
    category: DirectSendCategory
    note: str = ""
    evidence: str = "v21-s0-inventory §2.4 / v21-risk-red-report 风险5"


@dataclass(frozen=True)
class TakeoverRegistry:
    matchers: tuple[MatcherEntry, ...]
    schedulers: tuple[SchedulerEntry, ...]
    route_groups: tuple[RouteGroupEntry, ...]
    direct_sends: tuple[DirectSendEntry, ...]

    @property
    def total_control_routes(self) -> int:
        return sum(group.route_count for group in self.route_groups)

    def summary(self) -> dict[str, int]:
        return {
            "matchers": len(self.matchers),
            "schedulers": len(self.schedulers),
            "control_route_groups": len(self.route_groups),
            "control_routes": self.total_control_routes,
            "direct_send_entries": len(self.direct_sends),
        }


def _m(*items: MatcherEntry) -> tuple[MatcherEntry, ...]:
    return tuple(items)


def build_default_takeover_registry() -> TakeoverRegistry:
    """A1 冻结清单（v21-s0-inventory §2，HEAD=56d1461）的结构化登记表。

    逐条对齐 A1 §2.1（50 matcher）/§2.2（12 调度族）/§2.3（62 路由）/
    §2.4（直发嫌疑 8 组+读路径甄别）。checklist 除已知事实外一律 "todo"，
    由接线席位补齐——不臆造未验证的幂等来源。
    """
    # --- 50 matcher（A1 §2.1 逐行誊录；priority 缺失处 None 如实） ---
    matchers = _m(
        MatcherEntry("status", "__init__.py:4391", "on_command", None, "status"),
        MatcherEntry("auto_send", "__init__.py:4398", "on_message", 13, "auto_send"),
        MatcherEntry("mail_control", "__init__.py:4399", "on_command", None, "mail"),
        MatcherEntry("mail_notice", "__init__.py:4406", "on_message", 9, "mail"),
        MatcherEntry("chat", "__init__.py:4407", "on_message", 50, "chat"),
        MatcherEntry("meme", "__init__.py:4420", "on_message", 20, "meme"),
        MatcherEntry("natural", "__init__.py:4421", "on_message", 45, "natural"),
        MatcherEntry("meme_library", "__init__.py:4429", "on_message", 22, "meme_library"),
        MatcherEntry("meme_absorb", "__init__.py:4431", "on_message", 10, "meme_absorb"),
        MatcherEntry("group_upload_notice", "__init__.py:4537", "on_notice", 6, "group_upload"),
        MatcherEntry("dirty_guard_matcher", "__init__.py:4558", "on_message", 3, "dirty_guard"),
        MatcherEntry(
            "campus_record_matcher",
            "__init__.py:5027",
            "on_message",
            8,
            "campus",
            note=(
                "U17-CAMPUS-WIRE 收编中央管线（测试规约已立，生产接线待落地）；"
                "坐标/priority 为 2026-09-20 同波审计实读刷新（matcher 真身 "
                "on_message(priority=8, block=False)）"
            ),
        ),
        MatcherEntry("file_notice", "__init__.py:4615", "on_notice", 8, "file"),
        MatcherEntry("poke_notice", "__init__.py:4725", "on_notice", 7, "poke"),
        MatcherEntry("emoji_like_notice", "__init__.py:4811", "on_notice", 7, "emoji_like"),
        MatcherEntry("group_increase_notice", "__init__.py:4844", "on_notice", 6, "group_increase"),
        MatcherEntry("group_decrease_notice", "__init__.py:4845", "on_notice", 6, "group_decrease"),
        MatcherEntry("group_admin_notice", "__init__.py:4846", "on_notice", 6, "group_admin"),
        MatcherEntry("file_export", "__init__.py:4957", "on_message", 8, "file_export"),
        MatcherEntry("image_search", "__init__.py:5026", "on_message", 46, "image_search"),
        MatcherEntry("cookie_admin", "__init__.py:5105", "on_message", 8, "cookie_admin"),
        MatcherEntry("nickname_set", "__init__.py:5112", "on_message", 8, "nickname"),
        MatcherEntry("group_file_stats", "__init__.py:5138", "on_message", 8, "group_file_stats"),
        MatcherEntry("content", "__init__.py:5526", "on_message", 46, "content"),
        MatcherEntry("music_mode", "__init__.py:5527", "on_message", 40, "music_mode"),
        MatcherEntry("music", "__init__.py:5528", "on_message", 41, "music"),
        MatcherEntry("today_history", "__init__.py:5529", "on_message", None, "today_history"),
        MatcherEntry("wiki", "__init__.py:5532", "on_message", 41, "wiki"),
        MatcherEntry("moegirl", "__init__.py:5533", "on_message", 41, "moegirl"),
        MatcherEntry("moegirl_question", "__init__.py:5534", "on_message", None, "moegirl"),
        MatcherEntry("epic", "__init__.py:5537", "on_message", 41, "epic"),
        MatcherEntry("weather", "__init__.py:5538", "on_message", 41, "weather"),
        MatcherEntry("market", "__init__.py:5539", "on_message", 41, "market"),
        MatcherEntry("fx", "__init__.py:5540", "on_message", 41, "fx"),
        MatcherEntry("stocks", "__init__.py:5541", "on_message", 42, "stocks"),
        MatcherEntry("commodities", "__init__.py:5542", "on_message", 41, "commodities"),
        MatcherEntry("bond", "__init__.py:5543", "on_message", 41, "bond"),
        MatcherEntry("northbound", "__init__.py:5544", "on_message", 41, "northbound"),
        MatcherEntry("divination", "__init__.py:5545", "on_message", 41, "divination"),
        MatcherEntry("news", "__init__.py:5546", "on_message", 41, "news"),
        MatcherEntry("randpic", "__init__.py:5547", "on_message", 41, "randpic"),
        MatcherEntry("reminder", "__init__.py:5548", "on_message", 41, "reminder"),
        MatcherEntry("daily_assist", "__init__.py:5549", "on_message", 42, "daily_assist"),
        MatcherEntry("eat", "__init__.py:5550", "on_message", 41, "eat"),
        MatcherEntry("subscribe_cmd", "__init__.py:5551", "on_message", 12, "subscribe"),
        MatcherEntry("affinity", "__init__.py:5561", "on_message", 41, "affinity"),
        MatcherEntry("alias", "__init__.py:5571", "on_message", 10, "alias"),
        MatcherEntry("group_info_matcher", "__init__.py:7368", "on_message", 41, "group_info"),
        MatcherEntry("ignore_guide", "__init__.py:7432", "on_message", None, "ignore_guide"),
        MatcherEntry("media_archive", "__init__.py:7454", "on_message", 43, "media_archive"),
    )

    # --- 12 调度族（A1 §2.2） ---
    def sched(
        family: str,
        register: str,
        jobs: tuple[str, ...],
        note: str = "",
    ) -> SchedulerEntry:
        return SchedulerEntry(
            family=family,
            register_location=register,
            add_job_locations=jobs,
            note=note,
        )

    schedulers = (
            sched(
                "send_queue_worker", "__init__.py:1455", ("__init__.py:1494",),
                "发送队列 worker；dedupe_key 幂等已内建（SQLite part 级）",
            ),
            sched("credential_check", "__init__.py:1512", ("__init__.py:1609",)),
            sched(
                "today_history", "__init__.py:1625", ("__init__.py:1707", "__init__.py:1743"),
                "含 job 重排",
            ),
            sched("kb_wiki_sync", "__init__.py:1764", ("__init__.py:1799", "__init__.py:1815")),
            sched("reflection", "__init__.py:2608", ("__init__.py:2643", "__init__.py:2658")),
            sched("reminder_delivery", "__init__.py:2804", ("__init__.py:2832",)),
            sched("digest_push", "__init__.py:2939", ("__init__.py:2966",)),
            sched(
                "daily_assist", "__init__.py:3174",
                ("__init__.py:3196", "__init__.py:3216", "__init__.py:3234"),
            ),
            sched(
                "model_schedule", "domains/chat_reply/llm_engine/model_schedule.py:133", ("domains/chat_reply/llm_engine/model_schedule.py:162",),
            ),
            sched(
                "usage_monitor", "domains/ops/monitor/usage_monitor.py:396",
                ("domains/ops/monitor/usage_monitor.py:656", "domains/ops/monitor/usage_monitor.py:674"),
            ),
            sched(
                "subscription_poll", "sources/subscription_runtime_v2.py:module",
                ("sources/subscription_runtime_v2.py:40", "sources/subscription_runtime_v2.py:49"),
            ),
            sched(
                "unattributed_bare_add_jobs", "__init__.py:4027,4082",
                ("__init__.py:4027", "__init__.py:4082"),
                "A1 §2.2：用途 unknown——接管调度面前必须先定位",
            ),
        )

    # --- 控制面路由组（A1 §2.3；62 条按组计数，明细以 A1 冻结粒度为准） ---
    route_groups = (
            RouteGroupEntry(
                module="control_plane/api/v1.py",
                prefix="/api/v1",
                route_count=28,
                members=(
                    "/protocol", "/openapi.json",
                    "/features", "/features/tree", "/features/{id}", "/features/{id}/children",
                    "/features/state", "/features/preview", "/features/enable",
                    "/features/disable", "/features/reset", "/features/audit",
                    "/config/schema", "/config/changes", "/config/{key}",
                    "/config/{key}/preview", "/config/{key}/set", "/config/{key}/reset",
                    "/logs", "/logs/sources",
                    "/metrics/resources", "/metrics/overview", "/metrics/models",
                    "/metrics/sessions", "/metrics/tokens", "/metrics/trends",
                    "/traces",
                ),
                note="A1 分组清单可枚举 27/28；缺额 1 条为 A1 未冻结明细，不臆造",
            ),
            RouteGroupEntry(
                module="control_plane/api/workspaces.py",
                prefix="/api/v1/workspaces",
                route_count=10,
                members=(
                    "GET /workspaces", "POST /workspaces", "GET /workspaces/{id}",
                    "DELETE /workspaces/{id}", "GET /workspaces/{id}/messages",
                    "POST /workspaces/{id}/messages", "POST /workspaces/{id}/reset",
                    "POST /workspaces/{id}/preview", "POST /workspaces/{id}/send",
                    "GET /workspaces/{id}/audit",
                ),
                note="/send 为模拟发送；绝不触达生产 SendQueue 属红线，接管时验证",
            ),
            RouteGroupEntry(
                module="control_plane/api/llm.py",
                prefix="/api/v1/llm",
                route_count=9,
                members=(
                    "GET /llm/providers", "PUT /llm/providers",
                    "GET /llm/channels", "PUT /llm/channels",
                    "GET /llm/models", "PUT /llm/models",
                    "GET /llm/health", "GET /llm/routes", "POST /llm/routes/preview",
                ),
            ),
            RouteGroupEntry(
                module="control_plane/api/actions.py",
                prefix="/api/v1/actions",
                route_count=7,
                members=(
                    "GET /actions", "GET /actions/runs", "GET /actions/runs/{id}",
                    "POST /actions/runs/{id}/cancel", "GET /actions/{id}",
                    "POST /actions/{id}/preview", "POST /actions/{id}/execute",
                ),
            ),
            RouteGroupEntry(
                module="control_plane/api/health.py",
                prefix="/admin/api/v1",
                route_count=4,
                members=("GET /healthz", "GET /health", "GET /status/bot", "GET /status/models"),
            ),
            RouteGroupEntry(
                module="control_plane/api/events.py",
                prefix="/api/v1/logs",
                route_count=4,
                members=("GET /logs/events", "GET /logs/sources", "GET /logs/stream", "GET /logs/events/{event_id}"),
            ),
            RouteGroupEntry(
                module="control_plane/api/platform.py",
                prefix="(动态 APIRouter)",
                route_count=0,
                members=(),
                note="A1 §2.3：动态注册未枚举（unknown）；OpenAPI 实际面以 /protocol 实跑为准",
            ),
        )

    # --- 直发出站嫌疑点（A1 §2.4 + 风险5 坐标复核；v21r4-b S0-COLLECT+REG-REFRESH） ---
    # 根 __init__.py 四处已由 S0-ROOT-c（2026-09-19）收编为 *_via_queue 门开分支
    # （方案形态 B/A/A/D；门缺省 False=门关旧直连逐字节等价，重启不拨门=零变更）；
    # 坐标=REG-REFRESH 2026-09-19 grep 实读门关分支（行号会漂，以符号 grep 复核）。
    direct_sends = (
            DirectSendEntry(
                "__init__.py:4440-4444", "send_private_msg",
                DirectSendCategory.BYPASS_SUSPECT,
                "cookie 到期提醒调度 job 旧直连（管理员换人重试）——已收编（S0-ROOT-c "
                "2026-09-19，方案 §3.1 形态B）：bot_cookie_expiry_reminder_via_queue "
                "门开走 _deliver_cookie_expiry_report_via_queue（SendRequest→"
                "SendQueue→内联投递，dedupe 带日期=当日幂等）；门缺省 False=本直连"
                "分支逐字节等价，重启不拨门=生产零变更。前态注记 pending-on-RWC5-b "
                "已终结。测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（:4440-4444）；复核锚=符号 grep send_private_msg",
            ),
            DirectSendEntry(
                "__init__.py:5378-5382", "send_group_msg",
                DirectSendCategory.BYPASS_SUSPECT,
                "入群欢迎 notice handler 旧直连——已收编（S0-ROOT-c 2026-09-19，方案 "
                "§3.2 形态A）：bot_group_welcome_via_queue 门开走 "
                "_send_text_through_unified_pipeline（capability=bot.group_welcome，"
                "SENT/REDIRECTED 才记 group_welcome_sent）；门缺省 False=本直连分支"
                "逐字节等价，重启不拨门=生产零变更。前态注记 pending-on-RWC5-b 已终结。"
                "测试=tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（:5378-5382）；复核锚=符号 grep send_group_msg",
            ),
            DirectSendEntry(
                "__init__.py:5730-5740", "send_group_msg + send_private_msg",
                DirectSendCategory.BYPASS_SUSPECT,
                "cookie 登录二维码图片旧直连（双通道）——已收编（S0-ROOT-c 2026-09-19，"
                "方案 §3.3 形态A mixed）：bot_cookie_qr_via_queue 门开走 "
                "_send_parts_through_unified_pipeline（text=\"\"+image=file:///，"
                "audit_tags=cookie_login_qr）；门缺省 False=本直连分支逐字节等价，"
                "重启不拨门=生产零变更。前态注记 pending-on-RWC5-b 已终结。测试="
                "tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（:5730-5740）；复核锚=符号 grep send_group_msg",
            ),
            DirectSendEntry(
                "__init__.py:5526-5538", "upload_group_file + upload_private_file",
                DirectSendCategory.BYPASS_SUSPECT,
                "文档导出上传旧直连（原登记缺口补齐项）——已收编（S0-ROOT-c "
                "2026-09-19，方案 §3.4 形态D）：bot_file_export_via_queue 门开走 "
                "_send_files_through_unified_pipeline（CapabilityResult.files→"
                "FileTransferGateway 既有链）；门缺省 False=本直连分支逐字节等价，"
                "重启不拨门=生产零变更。前态注记 pending-on-RWC5-b 已终结。测试="
                "tests/test_v21_s0_root_collect.py",
                "v21r4-b S0-COLLECT 2026-09-18 快照→REG-REFRESH 2026-09-19 grep 复核"
                "（:5526-5538）；复核锚=符号 grep upload_group_file",
            ),
            DirectSendEntry(
                "__init__.py:4978", "delete_msg",
                DirectSendCategory.BY_DESIGN,
                "撤回（dirty guard），非消息投递",
                "v21-risk-red-report 风险5（REG-REFRESH 2026-09-19 复核现坐标 :4978；"
                "原登记 :4569→S0-COLLECT 观测 :4802 均已漂移）",
            ),
            DirectSendEntry(
                "control_plane/dispatcher.py:162-220", "group_poke / friend_poke",
                DirectSendCategory.BY_DESIGN,
                "回戳 v2（by-design 副作用）——已收编（L34）：直连点已不存在，"
                "经 OutboundSideEffectExecutor 统一出站面（cancel 闸→准入复验→租约"
                "线性化→Transport 固定映射解析方法名→call_api 通道本体）；装配 "
                "__init__.py:5049-5099；方法名字面量仅存本表 POKE 映射（绝不拼接）",
                "v21-risk-red-report 风险5（原直连坐标 :4745,4751 已随 L34 收编消失；"
                "REG-REFRESH 2026-09-19 grep 实证根 __init__.py 零 group_poke/"
                "friend_poke 直连）",
            ),
            DirectSendEntry(
                "domains/meme/reactions/engine.py:754-782", "set_msg_emoji_like",
                DirectSendCategory.BY_DESIGN,
                "贴表情旁路（by-design 副作用）——已收编（L35）：react_to_message 经 "
                "_REACTION_OUTBOUND_EXECUTOR（engine.py:664）统一出站面，方法名由 "
                "Transport 固定映射解析，失败静默语义保持；runtime/reactions.py 旧"
                "路径现为 compat shim（真身本路径）",
                "v21-risk-red-report 风险5（原登记 runtime/reactions.py:652-655 系 "
                "shim 旧路径；REG-REFRESH 2026-09-19 实读 engine.py 真身）",
            ),
            DirectSendEntry(
                "domains/meme/reactions/engine.py:785-813", "set_message_reaction",
                DirectSendCategory.BY_DESIGN,
                "TG reaction（docstring 自述未接线触发点，预留可选接线）——出站面已"
                "统一：react_telegram_message 经同一 executor（Transport 固定映射）",
                "v21-risk-red-report 风险5（原登记 runtime/reactions.py:681-686 系 "
                "shim 旧路径；REG-REFRESH 2026-09-19 实读 engine.py 真身）",
            ),
            DirectSendEntry(
                "domains/transport/sender/file_gateway.py:356-412", "call_api",
                DirectSendCategory.CHANNEL_BODY,
                "统一文件出站路径通道本体（FileTransferGateway._deliver_onebot 上传内环："
                "getattr(bot, api) 优先、退化 call_api、retcode 拒绝→upload_rejected）；"
                "onebot.py 文件部件分支统一经 get_default_file_gateway().stage→deliver 消费，"
                "生产侧无绕行实例；原 PENDING_RULING 依 DIRECT-PLAN §二④ 裁定建议改判，"
                "final 归 DELIVERY-001 owner 复核",
                "v21r4-b S0-COLLECT 2026-09-18 实读：旧坐标 sender/file_gateway.py:382 "
                "系 reorg 前 shim 路径（旧路径现为 3 行 compat shim）",
            ),
            DirectSendEntry(
                "sender/onebot.py:444,449,469,477,546,554,583,588,962",
                "send_*_msg / call_api",
                DirectSendCategory.CHANNEL_BODY, "SendQueue worker 合法通道本体，非绕行",
            ),
            # 读路径甄别（非出站；group_info.py:146 通用透传单列审计）
            DirectSendEntry(
                "capabilities/group_info.py:146", "call_api",
                DirectSendCategory.READ_PATH,
                "通用 call_api 透传 sink，动作面宽——DISPATCH-001 单列审计",
            ),
            DirectSendEntry(
                "__init__.py:949,1014,2059,4924,4928,7468 + runtime/video_pipeline.py:72,74 + sources/telegram_media.py:133",
                "get_forward_msg/get_record/get_stranger_info/get_file/download_file/get_msg",
                DirectSendCategory.READ_PATH, "读路径，非出站（A1 §2.4 甄别保留）",
            ),
        )

    return TakeoverRegistry(
        matchers=matchers,
        schedulers=schedulers,
        route_groups=route_groups,
        direct_sends=direct_sends,
    )
