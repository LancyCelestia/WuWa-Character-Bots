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
另一表即测试红。

二期（2026-09-14）：帮助注册表同哲学对齐——``HELP_TOPIC_DECLARATIONS``
以每主题一行的 (topic, admin_only, capability) 权威三元组登记 echo.py
全部帮助主题；echo 的 ``_HELP_ENTRIES``/``_HELP_ENTRY_META`` 因
command_catalog.py 与 doc_sync.py 的 AST/正则静态提取而保持字面形态
（不改为运行时构建），逐 topic 强一致性由同一测试文件常驻锁定。
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


@dataclass(frozen=True)
class HelpTopicDecl:
    """单个帮助主题的登记属性（每主题一行，审查 C-06 二期）。

    (topic, admin_only, capability) 三元组是帮助注册表的权威声明：
    topic = ``/bot help`` 主题名；admin_only = 可见性（False = 普通用户
    可见，等价 echo._PUBLIC_HELP_TOPICS 成员资格）；capability = 能力入口
    登记文（echo._HELP_ENTRY_META 的 capability 列：bot.* 能力 id、/bot
    子命令或非命令登记说明）。条目正文/别名/分类/教程文案等表现层仍以
    echo.py 字面为准（两份静态解析器依赖），不进本表。
    """

    topic: str
    admin_only: bool
    capability: str = ""


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
        kind="DAILY_ASSIST", value="daily_assist", capability_id="bot.daily_assist", priority=42,
        label="收件箱速记", reason="收件箱（收件箱 买牛奶/收件箱）",
        tags=("base_route:daily_assist",), command=True, has_rule=True,
        matcher_name="daily_assist_match",
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
        interface_id="capability.daily_assist", label="收件箱速记/早晚简报", status="active",
        route_kind="daily_assist", priority=42,
        description="收件箱随手记 + 定时吃什么推荐与早晚简报（BOT_DAILY_ASSIST_*，纯文本文件驱动）",
        help_topic="收件箱",
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

# ---------------------------------------------------------------------------
# 帮助注册表权威声明（审查 C-06 二期，2026-09-14 批）
# ---------------------------------------------------------------------------
# echo._HELP_ENTRIES 是 /bot help、/bot commands 与 docs/command-catalog.md 的
# 数据体；scripts/command_catalog.py（AST 提取三表）与 scripts/doc_sync.py
# （正则数 topic 行）按源码文本静态解析、不 import 插件包，故该表必须保持
# 字面形态、不改为运行时构建。作为对价：每主题的 (topic, admin_only,
# capability) 权威三元组登记于下表，与 echo 字面表的逐 topic 强一致性由
# tests/test_capability_registry.py 常驻锁定——增删主题、翻转可见性、
# 改能力入口而不同步本表即测试红（漏登不可见从此消灭，与第一期同哲学）。
#
# 书写序 = echo._HELP_ENTRIES 字面书写序（帮助总览/命令目录渲染序）。
HELP_TOPIC_DECLARATIONS: tuple[HelpTopicDecl, ...] = (
    HelpTopicDecl(topic="状态", admin_only=True, capability="bot.status"),
    HelpTopicDecl(topic="记忆", admin_only=False, capability="bot.memory"),
    HelpTopicDecl(topic="为什么", admin_only=True, capability="bot.why"),
    HelpTopicDecl(topic="回执", admin_only=True, capability="/bot receipt"),
    HelpTopicDecl(topic="审计", admin_only=True, capability="/bot audit"),
    HelpTopicDecl(topic="最近", admin_only=True, capability="/bot recent"),
    HelpTopicDecl(topic="队列", admin_only=True, capability="/bot queue"),
    HelpTopicDecl(topic="上下文", admin_only=True, capability="/bot context"),
    HelpTopicDecl(topic="对话", admin_only=True, capability="bot.dialogue"),
    HelpTopicDecl(topic="接入", admin_only=True, capability="/bot setup llm"),
    HelpTopicDecl(topic="配置", admin_only=True, capability="bot.config"),
    HelpTopicDecl(topic="就绪", admin_only=True, capability="bot.readiness"),
    HelpTopicDecl(topic="角色", admin_only=True, capability="bot.roles"),
    HelpTopicDecl(topic="人格", admin_only=True, capability="bot.persona"),
    HelpTopicDecl(topic="路由", admin_only=False, capability="/bot route"),
    HelpTopicDecl(topic="历史", admin_only=True, capability="bot.history"),
    HelpTopicDecl(topic="暂停", admin_only=True, capability="bot.control"),
    HelpTopicDecl(topic="回复", admin_only=True, capability="/bot reply"),
    HelpTopicDecl(topic="模型", admin_only=True, capability="/bot model"),
    HelpTopicDecl(topic="用量", admin_only=True, capability="/bot model usage"),
    HelpTopicDecl(topic="设置", admin_only=True, capability="/bot runtime"),
    HelpTopicDecl(topic="搜索", admin_only=True, capability="/bot search"),
    HelpTopicDecl(topic="解析", admin_only=True, capability="/bot parse"),
    HelpTopicDecl(topic="凭据", admin_only=True, capability="/bot cookie"),
    HelpTopicDecl(topic="群策略", admin_only=True, capability="/bot group"),
    HelpTopicDecl(topic="群文件", admin_only=True, capability="/bot 群文件"),
    HelpTopicDecl(topic="日志", admin_only=True, capability="bot.logs"),
    HelpTopicDecl(topic="文件", admin_only=True, capability="matcher:admin_file_export（文件导出）"),
    HelpTopicDecl(topic="身份", admin_only=True, capability="/bot identity"),
    HelpTopicDecl(topic="怪癖", admin_only=True, capability="/bot quirk"),
    HelpTopicDecl(topic="限流", admin_only=True, capability="/bot runtime set（配置型模块，无独立命令）"),
    HelpTopicDecl(topic="合并转发", admin_only=True, capability="/bot runtime set（配置型模块，无独立命令）"),
    HelpTopicDecl(topic="群摘要", admin_only=True, capability="/bot runtime set（配置型模块，无独立命令）"),
    HelpTopicDecl(topic="视频理解", admin_only=True, capability="/bot runtime set（配置型模块，无独立命令）"),
    HelpTopicDecl(topic="运行开关", admin_only=True, capability=".env（持久化开关，改后重启生效，无运行时命令）"),
    HelpTopicDecl(topic="邮件", admin_only=True, capability="on_command:mail"),
    HelpTopicDecl(topic="Telegram", admin_only=True, capability=".env（Telegram 适配器配置）"),
    HelpTopicDecl(topic="供应商", admin_only=True, capability=".env（模型注册表；/bot model 亦可视图）"),
    HelpTopicDecl(topic="订阅", admin_only=False, capability="bot.subscribe"),
    HelpTopicDecl(topic="点歌", admin_only=False, capability="bot.music / bot.music_mode"),
    HelpTopicDecl(topic="表情", admin_only=False, capability="bot.meme"),
    HelpTopicDecl(topic="偷表情", admin_only=False, capability="bot.meme_library"),
    HelpTopicDecl(topic="搜图", admin_only=False, capability="on_message:搜图"),
    HelpTopicDecl(topic="天气", admin_only=False, capability="bot.weather"),
    HelpTopicDecl(topic="行情", admin_only=False, capability="bot.market"),
    HelpTopicDecl(topic="个股行情", admin_only=False, capability="bot.stocks"),
    HelpTopicDecl(topic="商品行情", admin_only=False, capability="bot.commodities"),
    HelpTopicDecl(topic="国债收益率", admin_only=False, capability="bot.bond"),
    HelpTopicDecl(topic="北向资金", admin_only=False, capability="bot.northbound"),
    HelpTopicDecl(topic="汇率", admin_only=False, capability="bot.fx"),
    HelpTopicDecl(topic="占卜", admin_only=False, capability="bot.divination"),
    HelpTopicDecl(topic="快报", admin_only=False, capability="bot.news"),
    HelpTopicDecl(topic="维基", admin_only=False, capability="bot.wiki"),
    HelpTopicDecl(topic="萌娘百科", admin_only=False, capability="bot.moegirl（二次元问句路由同归此能力）"),
    HelpTopicDecl(topic="历史上的今天", admin_only=False, capability="bot.today_history"),
    HelpTopicDecl(topic="下载", admin_only=False, capability="/bot download"),
    HelpTopicDecl(topic="昵称", admin_only=False, capability="bot.alias"),
    HelpTopicDecl(topic="链接", admin_only=False, capability="bot.content"),
    HelpTopicDecl(topic="草稿", admin_only=False, capability="bot.auto_send"),
    HelpTopicDecl(topic="吃什么", admin_only=False, capability="bot.eat"),
    HelpTopicDecl(topic="媒体归档", admin_only=True, capability="bot.media_archive"),
    HelpTopicDecl(topic="群信息", admin_only=False, capability="bot.group_info"),
    HelpTopicDecl(topic="好感度", admin_only=False, capability="bot.affinity"),
    HelpTopicDecl(topic="Epic", admin_only=False, capability="bot.epic"),
    HelpTopicDecl(topic="随机图", admin_only=False, capability="bot.randpic"),
    HelpTopicDecl(topic="提醒", admin_only=False, capability="bot.reminder"),
    HelpTopicDecl(topic="笔记", admin_only=False, capability="bot.reminder"),
    HelpTopicDecl(topic="收件箱", admin_only=False, capability="bot.daily_assist"),
    HelpTopicDecl(topic="帮助", admin_only=False, capability="bot.help"),
    HelpTopicDecl(topic="聊天", admin_only=False, capability="bot.chat"),
    HelpTopicDecl(topic="戳一戳", admin_only=False, capability="on_notice:戳一戳"),
    HelpTopicDecl(topic="表情收库", admin_only=False, capability="meme_absorb（群图自动收库，无命令）"),
    HelpTopicDecl(topic="自然语言", admin_only=False, capability="bot.natural_command"),
    HelpTopicDecl(topic="忽略", admin_only=True, capability="matcher:IGNORE（空消息静默；未知命令形态回引导）"),
    HelpTopicDecl(topic="决策", admin_only=True, capability="/bot decision"),
)
