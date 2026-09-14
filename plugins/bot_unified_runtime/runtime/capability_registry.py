"""能力单一声明源（Keystone，审查 C-06）。

此前一个能力的 5 份属性（路由 kind / capability_id / priority / 接口登记 /
命令路由成员资格 / 内部能力说明）散落在 base_router.py 的 5 张手写清单里，
新增能力要改 4-5 处，漏登即不可见。本模块把它们收拢为**每能力一行**的常量
声明表：

- ``ROUTE_CAPABILITY_DECLARATIONS``：全部 32 个 RouteKind 成员（含 IGNORE
  兜底席）逐能力一行；``command`` 列在 base_router 派生
  ``COMMAND_ROUTE_KINDS``，``note`` 列对应 ``INTERNAL_CAPABILITY_NOTES``。
- ``INTERFACE_DECLARATIONS``：接口清单（含 reserved 预留席）逐行登记，
  字段与 ``base_router.InterfaceEntry`` 一一对应。

依赖方向（防循环）：本模块**只声明数据，不 import 包内任何模块**；
``base_router`` 在 import 时从本表构造 ``COMMAND_ROUTE_KINDS``。

与 base_router 字面表的关系：``scripts/doc_sync.py``、
``scripts/command_catalog.py``、``tests/test_doc_sync_gates.py`` 与
``scripts/extract_trigger_words.py`` 四处静态解析器按源码文本提取
base_router 的字面四表（机器册/命令目录/文档门禁不 import 插件包），
故 RouteKind 枚举、RouteRule 注册表、InterfaceEntry 清单与
INTERNAL_CAPABILITY_NOTES 的字面形态必须留在 base_router.py；
本表为权威声明，字面表为运行时+静态解析投影，两方向逐字段一致性由
``tests/test_capability_registry.py`` 常驻锁定——改动任何一表而不同步
另一表即测试红。echo.py 帮助注册表（_HELP_ENTRIES）的对齐计划见该文件头部。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteCapabilityDecl:
    """单个路由能力的全部登记属性（每能力一行）。

    kind/value 与 base_router.RouteKind 成员一一对应；has_rule=False 表示
    该 kind 不在 build_route_rules 注册 RouteRule（当前仅 IGNORE 兜底席）；
    command=True 表示属于 COMMAND_ROUTE_KINDS（群门禁按确定性命令处理）；
    note 非空时即 base_router.INTERNAL_CAPABILITY_NOTES 的登记文；
    matcher_name 是 build_route_rules 里绑定的判定函数名（审计列）。
    """

    kind: str
    value: str
    capability_id: str
    priority: int
    label: str
    reason: str
    tags: tuple[str, ...]
    command: bool
    has_rule: bool
    matcher_name: str = ""
    note: str = ""


@dataclass(frozen=True)
class InterfaceDecl:
    """接口清单条目声明（字段与 base_router.InterfaceEntry 一一对应）。"""

    interface_id: str
    label: str
    status: str  # "active" | "reserved"
    route_kind: str
    priority: int | None
    description: str
    help_topic: str = ""
    internal_note: str = ""


# 书写序 = RouteKind 枚举成员序（与 base_router.RouteKind 逐行对照审计）。
# RouteRule 注册表的书写序（判定循环的书写序语义）以 base_router 字面表为准，
# 由 tests/test_capability_registry.py 对改动前快照逐行锁定。
ROUTE_CAPABILITY_DECLARATIONS: tuple[RouteCapabilityDecl, ...] = (
    RouteCapabilityDecl(
        kind="ALIAS", value="alias", capability_id="bot.alias", priority=10,
        label="昵称命令", reason="昵称命令（/岸宝… /守岸人…）",
        tags=("base_route:alias",), command=True, has_rule=True,
        matcher_name="alias_match",
    ),
    RouteCapabilityDecl(
        kind="ADMIN", value="admin", capability_id="bot.status", priority=11,
        label="管理员命令", reason="管理员命令（/bot …）",
        tags=("base_route:admin",), command=True, has_rule=True,
        matcher_name="admin_match",
    ),
    RouteCapabilityDecl(
        kind="SUBSCRIBE", value="subscribe", capability_id="bot.subscribe", priority=12,
        label="订阅命令", reason="订阅命令（中文/英文）",
        tags=("base_route:subscribe",), command=True, has_rule=True,
        matcher_name="subscribe_match",
    ),
    RouteCapabilityDecl(
        kind="AUTO_SEND", value="auto_send", capability_id="bot.auto_send", priority=13,
        label="自动发送", reason="自动发送/定时任务命令",
        tags=("base_route:auto_send",), command=True, has_rule=True,
        matcher_name="auto_send_match",
    ),
    RouteCapabilityDecl(
        kind="MEME", value="meme", capability_id="bot.meme", priority=20,
        label="表情包生成", reason="表情包生成命令",
        tags=("base_route:meme",), command=True, has_rule=True,
        matcher_name="meme_match",
    ),
    RouteCapabilityDecl(
        kind="MEME_LIBRARY", value="meme_library", capability_id="bot.meme_library", priority=22,
        label="偷表情", reason="偷表情/表情库命令",
        tags=("base_route:meme_library",), command=True, has_rule=True,
        matcher_name="meme_library_match",
    ),
    RouteCapabilityDecl(
        kind="MUSIC_MODE", value="music_mode", capability_id="bot.music_mode", priority=40,
        label="点歌模式", reason="点歌输出模式设置",
        tags=("base_route:music_mode",), command=True, has_rule=True,
        matcher_name="music_mode_match",
    ),
    RouteCapabilityDecl(
        kind="MUSIC", value="music", capability_id="bot.music", priority=41,
        label="点歌", reason="点歌",
        tags=("base_route:music",), command=True, has_rule=True,
        matcher_name="music_match",
    ),
    RouteCapabilityDecl(
        kind="TODAY_HISTORY", value="today_history", capability_id="bot.today_history", priority=41,
        label="历史上的今天", reason="历史上的今天",
        tags=("base_route:today_history",), command=True, has_rule=True,
        matcher_name="today_history_match",
    ),
    RouteCapabilityDecl(
        kind="WIKI", value="wiki", capability_id="bot.wiki", priority=41,
        label="维基百科", reason="维基百科查询",
        tags=("base_route:wiki",), command=True, has_rule=True,
        matcher_name="wiki_match",
    ),
    RouteCapabilityDecl(
        kind="MOEGIRL", value="moegirl", capability_id="bot.moegirl", priority=41,
        label="萌娘百科", reason="萌娘百科查询",
        tags=("base_route:moegirl",), command=True, has_rule=True,
        matcher_name="moegirl_match",
    ),
    RouteCapabilityDecl(
        kind="MOEGIRL_QUESTION", value="moegirl_question", capability_id="bot.moegirl", priority=46,
        label="二次元问句", reason="二次元问句（萌娘百科自动查询，未命中降级聊天）",
        tags=("base_route:moegirl_question",), command=False, has_rule=True,
        matcher_name="moegirl_question_match",
    ),
    RouteCapabilityDecl(
        kind="EPIC", value="epic", capability_id="bot.epic", priority=41,
        label="Epic 免费游戏", reason="Epic 免费游戏查询",
        tags=("base_route:epic",), command=True, has_rule=True,
        matcher_name="epic_match",
    ),
    RouteCapabilityDecl(
        kind="WEATHER", value="weather", capability_id="bot.weather", priority=41,
        label="天气查询", reason="天气查询",
        tags=("base_route:weather",), command=True, has_rule=True,
        matcher_name="weather_match",
    ),
    RouteCapabilityDecl(
        kind="MARKET", value="market", capability_id="bot.market", priority=41,
        label="全球股指行情", reason="全球股指行情（行情/美股行情/大盘）",
        tags=("base_route:market",), command=True, has_rule=True,
        matcher_name="market_match",
    ),
    RouteCapabilityDecl(
        kind="STOCKS", value="stocks", capability_id="bot.stocks", priority=42,
        label="个股行情", reason="个股行情（英伟达/AMD/英特尔股价）",
        tags=("base_route:stocks",), command=True, has_rule=True,
        matcher_name="stocks_match",
        note="个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）",
    ),
    RouteCapabilityDecl(
        kind="COMMODITIES", value="commodities", capability_id="bot.commodities", priority=41,
        label="商品行情", reason="商品行情（黄金/金价/白银/原油/铜价/大宗商品）",
        tags=("base_route:commodities",), command=True, has_rule=True,
        matcher_name="commodities_match",
        note="商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 capabilities/market.py；帮助页 topic=商品行情）",
    ),
    RouteCapabilityDecl(
        kind="BOND", value="bond", capability_id="bot.bond", priority=41,
        label="国债收益率", reason="国债收益率（国债/期限利差/收益率曲线）",
        tags=("base_route:bond",), command=True, has_rule=True,
        matcher_name="bond_match",
        note="国债收益率（国债/期限利差/收益率曲线，触发词见 capabilities/market.py；帮助页 topic=国债收益率）",
    ),
    RouteCapabilityDecl(
        kind="NORTHBOUND", value="northbound", capability_id="bot.northbound", priority=41,
        label="北向资金", reason="北向资金（北向资金/沪股通/深股通）",
        tags=("base_route:northbound",), command=True, has_rule=True,
        matcher_name="northbound_match",
        note="北向资金（北向资金/沪股通/深股通成交总额，触发词见 capabilities/market.py；帮助页 topic=北向资金）",
    ),
    RouteCapabilityDecl(
        kind="FX", value="fx", capability_id="bot.fx", priority=41,
        label="汇率查询", reason="汇率（美元兑人民币/汇率面板）",
        tags=("base_route:fx",), command=True, has_rule=True,
        matcher_name="fx_match",
        note="汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）",
    ),
    RouteCapabilityDecl(
        kind="NEWS", value="news", capability_id="bot.news", priority=41,
        label="今日快报", reason="今日快报（快报/科技新闻/财经快报/国际新闻）",
        tags=("base_route:news",), command=True, has_rule=True,
        matcher_name="news_match",
    ),
    RouteCapabilityDecl(
        kind="RANDPIC", value="randpic", capability_id="bot.randpic", priority=41,
        label="随机图片", reason="随机图片（随机图/来张图）",
        tags=("base_route:randpic",), command=True, has_rule=True,
        matcher_name="randpic_match",
    ),
    RouteCapabilityDecl(
        kind="REMINDER", value="reminder", capability_id="bot.reminder", priority=41,
        label="提醒", reason="提醒（12点提醒我写作业/提醒列表/取消提醒）",
        tags=("base_route:reminder",), command=True, has_rule=True,
        matcher_name="reminder_match",
    ),
    RouteCapabilityDecl(
        kind="MEDIA_ARCHIVE", value="media_archive", capability_id="bot.media_archive", priority=43,
        label="媒体归档", reason="媒体归档（收藏/归档/存图+媒体；存聊天记录）",
        tags=("base_route:media_archive",), command=True, has_rule=True,
        matcher_name="media_archive_match",
    ),
    RouteCapabilityDecl(
        kind="GROUP_INFO", value="group_info", capability_id="bot.group_info", priority=41,
        label="群信息", reason="群信息（群信息/群主是谁/群人数/群公告/群精华/本群多大了）",
        tags=("base_route:group_info",), command=True, has_rule=True,
        matcher_name="group_info_match",
    ),
    RouteCapabilityDecl(
        kind="EAT", value="eat", capability_id="bot.eat", priority=41,
        label="吃什么推荐", reason="吃什么/菜谱推荐",
        tags=("base_route:eat",), command=True, has_rule=True,
        matcher_name="eat_match",
    ),
    RouteCapabilityDecl(
        kind="AFFINITY", value="affinity", capability_id="bot.affinity", priority=41,
        label="好感度查询", reason="好感度/好感查看/查询好感",
        tags=("base_route:affinity",), command=False, has_rule=True,
        matcher_name="affinity_match",
    ),
    RouteCapabilityDecl(
        kind="DIVINATION", value="divination", capability_id="bot.divination", priority=41,
        label="占卜", reason="占卜/塔罗/八字排盘",
        tags=("base_route:divination",), command=True, has_rule=True,
        matcher_name="divination_match",
    ),
    RouteCapabilityDecl(
        kind="NATURAL_COMMAND", value="natural_command", capability_id="bot.natural_command", priority=45,
        label="自然语言命令", reason="自然语言命令归一化",
        tags=("base_route:natural_command",), command=True, has_rule=True,
        matcher_name="natural_match",
    ),
    RouteCapabilityDecl(
        kind="CONTENT", value="content", capability_id="bot.content", priority=46,
        label="链接解析", reason="链接解析（视频/图片/社交媒体/商品等）",
        tags=("base_route:content",), command=False, has_rule=True,
        matcher_name="content_match",
    ),
    RouteCapabilityDecl(
        kind="CHAT", value="chat", capability_id="bot.chat", priority=50,
        label="人格对话", reason="自然语言对话（人格+世界观+价值观+方法论）",
        tags=("base_route:chat",), command=False, has_rule=True,
        matcher_name="chat_match",
    ),
    # 兜底席：不注册 RouteRule；capability_id/priority 与 classify_message_route
    # 的两条 IGNORE 兜底 RouteDecision 字面量一致（测试锁定）。
    RouteCapabilityDecl(
        kind="IGNORE", value="ignore", capability_id="bot.ignore", priority=999,
        label="", reason="", tags=(), command=False, has_rule=False,
    ),
)

# 声明序 = base_router.build_interface_manifest 的字面书写序（审计/命令目录
# 按此序渲染，不做物理重排）。
INTERFACE_DECLARATIONS: tuple[InterfaceDecl, ...] = (
    InterfaceDecl(
        interface_id="transport.onebot", label="NapCat / OneBot V11 传输", status="active",
        route_kind="transport", priority=None,
        description="入站 QQ 消息与出站发送统一走 OneBot V11（NapCat），由发送队列收口",
        internal_note="内部：传输层，无用户命令",
    ),
    InterfaceDecl(
        interface_id="core.gscore", label="GsCore / 早柚核心桥", status="active",
        route_kind="bridge", priority=None,
        description="ws://HOST:PORT/BOT_ID?token=TOKEN 桥接，接收游戏侧消息，配置 BOT_GSCORE_*",
        internal_note="内部：桥接层，接收游戏侧消息，无用户命令",
    ),
    InterfaceDecl(
        interface_id="parser.content", label="平台链接解析插件组", status="active",
        route_kind="content", priority=46,
        description="B站/小红书/抖音/油管/推特/Lofter/Pixiv/allcpp/米画师/小黑盒/音乐平台",
        help_topic="链接",
    ),
    InterfaceDecl(
        interface_id="persona.chat", label="人格大模型对话", status="active",
        route_kind="chat", priority=50,
        description="人格档案 + 向量知识库 + 世界观注入的大模型回复",
        help_topic="聊天",
    ),
    InterfaceDecl(
        interface_id="capability.weather", label="天气", status="active",
        route_kind="weather", priority=41,
        description="中国气象局 NMC 免 key 查询",
        help_topic="天气",
    ),
    InterfaceDecl(
        interface_id="capability.music", label="点歌", status="active",
        route_kind="music", priority=41,
        description="网易云/酷我/酷狗/QQ音乐/Apple Music/Spotify 搜索",
        help_topic="点歌",
    ),
    InterfaceDecl(
        interface_id="capability.wiki", label="维基百科", status="active",
        route_kind="wiki", priority=41,
        description="MediaWiki 公开 API",
        help_topic="维基",
    ),
    InterfaceDecl(
        interface_id="capability.moegirl", label="萌娘百科", status="active",
        route_kind="moegirl", priority=46,
        description="萌百 MediaWiki 公开 API：显式指令 + 二次元问句自动查询（未命中降级人格聊天）",
        help_topic="萌娘百科",
    ),
    InterfaceDecl(
        interface_id="capability.epic", label="Epic 免费游戏", status="active",
        route_kind="epic", priority=41,
        description="Epic 公开接口",
        help_topic="Epic",
    ),
    InterfaceDecl(
        interface_id="capability.today_history", label="历史上的今天", status="active",
        route_kind="today_history", priority=41,
        description="百度百科公开接口 + 每日推送",
        help_topic="历史上的今天",
    ),
    InterfaceDecl(
        interface_id="capability.subscribe", label="订阅博主/直播推送", status="active",
        route_kind="subscribe", priority=12,
        description="UP主/番剧/小红书博主等新内容与开播推送",
        help_topic="订阅",
    ),
    InterfaceDecl(
        interface_id="capability.meme", label="表情包生成", status="active",
        route_kind="meme", priority=20,
        description="调用本地 meme-generator-rs HTTP API 生成表情包",
        help_topic="表情",
    ),
    InterfaceDecl(
        interface_id="capability.auto_send", label="自动发送/定时任务", status="active",
        route_kind="auto_send", priority=13,
        description="报存 给 A 发… 草稿/预览/发送",
        help_topic="草稿",
    ),
    InterfaceDecl(
        interface_id="capability.game_live", label="游戏直播状态", status="reserved",
        route_kind="game_live", priority=None,
        description="预留：游戏内直播/活动事件接入",
        internal_note="预留：游戏直播事件接入，尚未实现",
    ),
    InterfaceDecl(
        interface_id="capability.meme_absorb", label="吸收表情包", status="active",
        route_kind="meme_absorb", priority=None,
        description="监听群图片异步下载、MD5 去重、权重筛选、VLM 打标与 NSFW 过滤",
        help_topic="表情收库",
    ),
    InterfaceDecl(
        interface_id="capability.group_info", label="群信息", status="active",
        route_kind="group_info", priority=41,
        description="OneBot V11 群 API（get_group_info/成员列表/公告/精华）：群资料/人数全员，公告与精华仅管理员；诚实降级清单见 capabilities/group_info.py",
        help_topic="群信息",
    ),
    InterfaceDecl(
        interface_id="capability.emotion", label="情绪状态注入", status="active",
        route_kind="context", priority=None,
        description="作为上下文能力注入，不单独占用文本路由",
        internal_note="内部：心情引擎，经上下文注入，不占文本路由",
    ),
    InterfaceDecl(
        interface_id="capability.gscore", label="GsCore 上行命令", status="reserved",
        route_kind="gscore", priority=None,
        description="预留：GsCore 侧指令统一进入基层路由",
        internal_note="预留：GsCore 侧指令统一进入基层路由，尚未实现",
    ),
)

# base_router.COMMAND_ROUTE_KINDS 在 import 时从本名单派生（成员单一声明源）。
COMMAND_ROUTE_KIND_NAMES: frozenset[str] = frozenset(
    decl.kind for decl in ROUTE_CAPABILITY_DECLARATIONS if decl.command
)
