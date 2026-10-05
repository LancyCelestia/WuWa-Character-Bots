"""十板块功能树（一级板块 / 二级功能 / 三级功能）的**唯一权威声明源**。

用户裁定（2026-09-21）：全部 Markdown 汇总文档重整为「实现这个 bot 的 10 个大型板块」，
按一级/二级/三级功能归类归档，并且**一处变更、处处跟随**。

因此本模块与 `capability_registry.py` 同一哲学：

- **只声明数据，不 import 包内任何模块**（防循环、可被脚本与门禁静态读取）。
- 板块树**不复制**代码事实：二级功能只登记「我拥有哪些 RouteKind / capability_id /
  帮助主题 / 实现路径 / 配置键前缀」，三级功能清单与计数由 `scripts/board_doc_sync.py`
  在渲染期从 ``ROUTE_CAPABILITY_DECLARATIONS``、``HELP_TOPIC_DECLARATIONS``、
  ``config.py`` 与 ``domains/`` 目录**实时派生**。新增一个能力只要在既有声明源登记，
  板块文档自动多出它的卡片。
- 覆盖度是**活性判据**而不是存在性判据：``board_doc_sync.py --check`` 与
  ``tests/test_board_taxonomy_gate.py`` 双向比对——代码里有而板块树没人认领 ⇒ 红；
  板块树认领了而代码里没有 ⇒ 红；一个 RouteKind 被两个二级功能抢 ⇒ 红。

层级约定：``BNN`` = 一级板块（目录名 ``BNN-<slug>``），``BNN.<slug>`` = 二级功能
（目录名 ``<slug>/``），三级功能 = ``<slug>/<l3-slug>.md``（由派生得到，不手写 id）。

第二根轴（2026-09-26 用户裁定「按一级分类每类建自己的 git 库」的余量）：``LIBRARY_TAXONOMY``
登记**板块账派不出来的发行库**（契约地基库与通道适配器库）。一级板块库的成员**只由本文件的
``BOARD_TAXONOMY`` 派生**（库工厂那一支尺），**绝不抄进 ``LIBRARY_TAXONOMY``**——抄进来就是第二真身。

用法：
    python scripts/board_doc_sync.py --write   # 生成/就地更新 docs/boards/**
    python scripts/board_doc_sync.py --check   # 漂移或覆盖缺口即退出码非 0
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

TAXONOMY_VERSION = "1.0"

@dataclass(frozen=True)
class FeatureNode:
    """二级功能：一个板块内一组同源实现、同一门禁口径的功能簇。"""

    fid: str
    label: str
    slug: str
    summary: str
    route_kinds: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    help_topics: tuple[str, ...] = ()
    impl_paths: tuple[str, ...] = ()
    config_prefixes: tuple[str, ...] = ()
    passive_matchers: tuple[tuple[str, str, int], ...] = ()
    """第三类认领（席7 2026-10-03）：不走 RouteKind 的**被动** matcher。

    ``(matcher 变量名, 注册面, priority)``，真身＝``plugins/bot_unified_runtime/__init__.py``
    里 ``name = on_message(...)/on_notice(...)`` 的字面注册。判据＝规则函数体内**不含**
    ``_cached_route_decision``（含它＝走 base_router，该由 ``route_kinds`` 认领，两条腿
    互斥——``tests/test_taxonomy_passive_matchers.py`` AST 锁双向执法：漏登记红、
    顶替 RouteKind 也红、注册面/优先级与字面漂移同红）。``on_command`` 命令面 matcher
    不属「被动」，不在本类管辖。
    """
    extra_l3: tuple[tuple[str, str], ...] = ()
    """代码里没有对应登记面的三级功能（``(slug, label)``），如「渲染契约」「归档规程」。"""

    @property
    def bid(self) -> str:
        return self.fid.split(".", 1)[0]


@dataclass(frozen=True)
class ReleaseLibNode:
    """发行库：一支自己的 git 仓的**成员账**（与板块账正交的第二把尺，2026-09-26 用户裁定）。

    一级板块库（``kind="board"``）的名字与成员**一律由 ``BOARD_TAXONOMY`` 现派生**（库工厂那一支），
    **绝不写进本表**——写进来就是第二真身。本表只登记「板块账派不出来」的两族：契约地基库与适配器库。

    字段纪律（沿用 ``board_placement.py`` 的豁免纪律：字面路径、禁通配、禁正则、禁目录兜底）：

    - ``slug`` 必须过板块门那把 kebab 尺，它同时是仓外库目录名与 tag 命名空间，与板块 slug 全不相交。
    - 发行名是**派生**属性（``release_name``＝``lib:<slug>``），不许另抄一份字符串。
    - ``member_paths`` 只准逐枚字面文件路径；两族库之间必须互斥（同一字节进两支仓＝库级双认领）。
    - ``pending_seed``＝ ``(候选落点或字面 none, 为什么今天还不在场)``，合法态恰三种：
      ①候选落点不在盘上（搬家/新建未落）；②落点＝``none``（该库按字面没有成员，带理由）；
      ③落点在盘上、但该枚今天已被某支板块库装着（板块账未让位）。
      第四种形态——在盘上、无主、也没进任何成员表——是懒登记，常驻门当场判红。
    """

    lid: str
    label: str
    slug: str
    kind: str
    summary: str
    member_paths: tuple[str, ...] = ()
    pending_seed: tuple[tuple[str, str], ...] = ()
    channel: str = ""

    @property
    def release_name(self) -> str:
        return f"lib:{self.slug}"

    def has_seeds(self) -> bool:
        """纯派生态：有成员路径才算有货；盘上存在性由常驻门去查（数据件不碰文件系统）。"""
        return bool(self.member_paths)


@dataclass(frozen=True)
class BoardNode:
    """一级板块：面向"实现这个 bot 需要哪十块"的大类切分。"""

    bid: str
    label: str
    slug: str
    tagline: str
    responsibilities: tuple[str, ...] = ()
    features: tuple[FeatureNode, ...] = ()
    inbound: tuple[str, ...] = ()
    outbound: tuple[str, ...] = ()


BOARD_TAXONOMY: tuple[BoardNode, ...] = (
    BoardNode(
        bid="B01",
        label="接入与协议",
        slug="ingress-protocol",
        tagline="把任意平台的一条原始事件，变成主链路认识的一条入站消息。",
        responsibilities=(
            "适配器连接与重连（QQ/SnowLuma、Telegram、Mail、Console）",
            "消息段归一、引用链递归反查、语音预转码、TG file_id 转字节",
            "会话键与文本边界的中央件（全仓唯一口径）",
            "平台能力面（群资料、贴纸回应、媒体上传）",
        ),
        features=(
            FeatureNode(
                fid="B01.qq-snowluma",
                label="QQ 协议端接入（SnowLuma / OneBot V11）",
                slug="qq-snowluma",
                summary="forward-WS 连接、段收发、平台 API 封装与断线对账。",
                route_kinds=("GROUP_INFO",),
                capability_ids=("bot.group_info",),
                help_topics=("接入", "合并转发", "群信息"),
                # 〔2026-09-29 S-FIX-PLACE3 粒度统账〕复原波把旧顶层 `sender` 的认领改锚到
                # `domains/transport/sender` 整目录 ⇒ 目录根套住 ②D-5（2026-09-26 用户裁定）窄化出的
                # B08.send-queue 8 枚逐文件根，新长出 8 枚包含对。本 fid 真正只拥有协议侧两枚发送腿
                # （onebot.py＝OneBot V11 手卷腿；nonebot.py＝NoneBot 通用腿，与发行库 A1 成员同件），
                # 队列侧文件归 B08.send-queue（含 failure_class.py，见彼处注）。
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/transport/sender/onebot.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/nonebot.py",
                    "plugins/bot_unified_runtime/message_context.py",
                ),
                config_prefixes=("bot_onebot_", "bot_snowluma_"),
                extra_l3=(
                    ("forward-websocket", "WS 连接与重连"),
                    ("incoming-ingest", "入站摄取与段归一"),
                    ("quote-chain-expand", "引用与合并转发递归反查"),
                    ("platform-capabilities", "群信息与平台能力边界"),
                ),
            ),
            FeatureNode(
                fid="B01.telegram",
                label="Telegram 适配器",
                slug="telegram",
                summary="getUpdates 网络韧性、file_id 取字节、嵌套块级元素降级。",
                help_topics=("Telegram",),
                impl_paths=("scripts/telegram_resilience.py",),
                config_prefixes=("bot_telegram_", "bot_tg_"),
                extra_l3=(
                    ("polling-resilience", "轮询韧性与退避"),
                    ("media-download", "媒体 file_id 取回"),
                ),
            ),
            FeatureNode(
                fid="B01.mail-console",
                label="邮件与控制台适配器",
                slug="mail-console",
                summary="邮件收发桥接与本地控制台交互，共用同一条主链路。",
                help_topics=("邮件",),
                impl_paths=("plugins/bot_unified_runtime/domains/transport/mail/mail_adapter.py", "plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py"),
                config_prefixes=("bot_mail_",),
                passive_matchers=(("mail_notice", "on_message", 9),),
                extra_l3=(
                    ("mail-inbound", "来信解析入链"),
                    ("console-driver", "控制台一次性驱动"),
                ),
            ),
            FeatureNode(
                fid="B01.message-normalization",
                label="消息归一与身份中央件",
                slug="message-normalization",
                summary="会话键、文本边界、发送者显示名等全仓唯一口径的归一层。",
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/core/session_keys.py",
                    "plugins/bot_unified_runtime/domains/core/text_boundary.py",
                    "plugins/bot_unified_runtime/domains/core/board_placement.py",
                ),
                extra_l3=(
                    ("session-keys", "会话键派生"),
                    ("text-boundary", "触发词文本边界谓词"),
                    ("sender-display", "发送者显示名归一"),
                ),
            ),
        ),
    ),
    BoardNode(
        bid="B02",
        label="路由与中央调度",
        slug="routing-dispatch",
        tagline="决定一条消息归谁处理、能不能处理、由哪一个能力入口处理。",
        responsibilities=(
            "RouteKind 判定与优先级拆位（唯一路由真身）",
            "能力声明源与中央调度信封（InvocationResult）",
            "决策引擎影子对照与接管",
            "门禁：角色、黑白名单、安静时间、限流、幂等",
        ),
        features=(
            FeatureNode(
                fid="B02.route-table",
                label="路由表与判定序",
                slug="route-table",
                summary="base_router 的 RouteKind 枚举、RouteRule 注册表与优先级判定序。",
                route_kinds=("ALIAS", "NATURAL_COMMAND", "IGNORE"),
                capability_ids=("bot.alias", "bot.natural_command", "bot.ignore"),
                help_topics=("路由", "昵称", "自然语言", "忽略"),
                impl_paths=("plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py",),
                extra_l3=(
                    ("matcher-family", "matcher 族与谓词"),
                    ("priority-order", "优先级判定序与拆位"),
                    ("command-route-membership", "命令路由成员资格"),
                ),
            ),
            FeatureNode(
                fid="B02.capability-registry",
                label="能力注册表与调度壳",
                slug="capability-registry",
                summary="每能力一行的 keystone 声明源，与中央调度信封的收编进度。",
                help_topics=("功能管理", "帮助"),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/capability_registry.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/service_wiring.py",
                    "plugins/bot_unified_runtime/capabilities",
                ),
                extra_l3=(
                    ("keystone-declarations", "声明源与投影表一致性"),
                    ("invocation-envelope", "调度信封与呈现契约分层"),
                    ("new-capability-checklist", "新增能力登记流程（先建模块与函数）"),
                ),
            ),
            FeatureNode(
                fid="B02.decision-engine",
                label="决策引擎",
                slug="decision-engine",
                summary="影子对照记录分歧，接管进度由配置模式控制。",
                impl_paths=("plugins/bot_unified_runtime/domains/core/decision",),
                config_prefixes=("bot_decision_",),
                help_topics=("决策",),
                extra_l3=(("shadow-mode", "影子对照与分歧记账"),),
            ),
            FeatureNode(
                fid="B02.policy-gate",
                label="门禁与限流",
                slug="policy-gate",
                summary="角色/黑白名单/安静时间/限流/幂等，全能力共用的准入面。",
                capability_ids=("bot.status",),
                route_kinds=("ADMIN",),
                help_topics=("角色", "群策略", "限流", "暂停", "为什么"),
                impl_paths=("plugins/bot_unified_runtime/policy", "plugins/bot_unified_runtime/domains/chat_reply/policy"),
                config_prefixes=("bot_rate_limit_", "bot_quiet_"),
                extra_l3=(
                    ("role-model", "六级角色与权限叠加"),
                    ("quiet-hours", "安静时间与主动搭话门"),
                    ("rate-limiter", "双实现限流与回滚"),
                    ("idempotency", "入站幂等"),
                ),
            ),
        ),
    ),
    BoardNode(
        bid="B03",
        label="人格·对话·内容安全",
        slug="persona-chat-safety",
        tagline="让她像守岸人，并且任何设定都越不过写死的红线。",
        responsibilities=(
            "人格上下文分区注入与反注入包裹",
            "对话回复、称谓与身份、怪癖演化审核",
            "好感度与心情（算法说明只定性，不展示固定数值）",
            "内容安全六硬线与亲密模式路由（任何设定不可架空）",
        ),
        features=(
            FeatureNode(
                fid="B03.chat-reply",
                label="人格对话与回复",
                slug="chat-reply",
                summary="CHAT 主能力：上下文拼装、失败话术池、分段换行统一。",
                route_kinds=("CHAT",),
                capability_ids=("bot.chat",),
                help_topics=("对话", "聊天", "回复", "戳一戳"),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/poke.py",
                ),
                config_prefixes=("bot_chat_", "bot_poke_"),
                passive_matchers=(("poke_notice", "on_notice", 7),),
                extra_l3=(
                    ("prompt-assembly", "人格提示词拼装"),
                    ("failure-copy-pools", "失败与降级话术池"),
                    ("poke-interaction", "戳一戳互动五件套"),
                ),
            ),
            FeatureNode(
                fid="B03.persona-context",
                label="人格上下文与称谓身份",
                slug="persona-context",
                summary="分区上下文、称谓边界、会话身份、人格源与副本同步。",
                help_topics=("人格", "身份", "上下文"),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/character/__init__.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/addressing.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/documents.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/emotion.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/glossary.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/knowledge_service.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/memory.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/memory_extract.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/memory_service.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/persona_injection.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/persona_service.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/persona_set.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/providers.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/reflection.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/relationship.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/relationships.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/session_identity.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/shared_export.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/shared_group.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/source_summary.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/temporal.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/trend.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/worldbook_service.py",
                    "personas/shorekeeper",
                ),
                passive_matchers=(("nickname_set", "on_message", 8),),
                extra_l3=(
                    ("context-sections", "上下文分区渲染"),
                    ("addressing", "称谓与主角边界"),
                    ("session-identity", "会话身份与自助偏好"),
                    ("persona-sync", "人格源与运行副本一致性"),
                    ("anti-injection", "反注入包裹与指令剥离"),
                ),
            ),
            FeatureNode(
                fid="B03.affinity-mood",
                label="好感度与心情",
                slug="affinity-mood",
                summary="好感度多因素步长与心情双轴，驱动语气与主动行为。",
                route_kinds=("AFFINITY",),
                capability_ids=("bot.affinity",),
                help_topics=("好感度",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/character/affinity.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/mood.py",
                ),
                config_prefixes=("bot_affinity_", "bot_mood_"),
                extra_l3=(
                    ("affinity-model", "分数模型与档位"),
                    ("affinity-copy", "态度文案与红线场景"),
                    ("mood-axes", "心情双轴与回归"),
                ),
            ),
            FeatureNode(
                fid="B03.quirks",
                label="怪癖演化",
                slug="quirks",
                summary="propose→管理员 approve→渲染 的审核制人格演化。",
                help_topics=("怪癖",),
                impl_paths=("plugins/bot_unified_runtime/domains/chat_reply/character/quirks.py",),
            ),
            FeatureNode(
                fid="B03.content-safety",
                label="内容安全与亲密模式",
                slug="content-safety",
                summary="六硬线确定性闸、亲密档位判定、名单门与记忆净化。",
                # 2026-09-24 亲密模式分级波（D 席登记）：帮助主题「亲密模式」在案，
                # 板块树必须认领它，否则 `board_doc_sync --check` 判"主题未被认领"。
                help_topics=("亲密模式",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py",
                    # 〔2026-10-04 亲密档波补登记〕`/bot intimate` 命令面的真实入口与三腿分诊口，
                    # 与 content_route 同目录同一条腿（词表真身仍只在 content_route.py 那一处）。
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/intimate_control.py",
                    # 〔2026-09-29 S-FIX-PLACE3 双认领拆账〕B10.security-guardrails 的旧顶层
                    # `security` 垫片（S-SHIM-WAVE1R T6 已退役）被复原波改锚到
                    # `domains/chat_reply/security` 整目录，与本 fid 的字面目录认领撞成
                    # 同一枚路径＝字面双认领（无条件红）。按两板本意逐文件拆开：
                    # 六硬线闸与记忆净化（extra_l3 hard-lines / memory-sanitize 两格）归本 fid；
                    # 反注入咽喉与显示伪装消毒（injection/display_guard/spoof_audit/包门面）归 B10。
                    "plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py",
                ),
                config_prefixes=("bot_content_route_", "bot_master_love_"),
                # dirty_guard_matcher（脏话守卫撤回）：真身住在 files/capabilities/group_files.py
                # 的 DirtyGuard，但行为语义是内容审核，归本 fid；impl 认领不动（防目录双认领）。
                passive_matchers=(("dirty_guard_matcher", "on_message", 3),),
                extra_l3=(
                    ("hard-lines", "六条硬线与不可架空"),
                    ("intimate-mode", "亲密档位与双开关"),
                    ("roster-gates", "四名单与群级门"),
                    ("memory-sanitize", "记忆侧净化同源"),
                ),
            ),
        ),
    ),
    BoardNode(
        bid="B04",
        label="记忆·知识·笔记",
        slug="memory-knowledge-notes",
        tagline="她记得什么、从哪查到、怎么不记错。",
        responsibilities=(
            "会话历史与上下文窗口",
            "长期记忆抽取、反思、召回打分与遗忘",
            "知识库检索与来源约束",
            "用户笔记与授时（笔记不是记忆，两套存储）",
        ),
        features=(
            FeatureNode(
                fid="B04.history",
                label="会话历史与上下文",
                slug="history",
                summary="线性对话历史的读写窗口与注入裁剪。",
                help_topics=("历史", "最近"),
                impl_paths=("plugins/bot_unified_runtime/domains/chat_reply/character/history.py",),
                config_prefixes=("bot_history_", "bot_context_"),
            ),
            FeatureNode(
                fid="B04.long-term-memory",
                label="长期记忆与反思",
                slug="long-term-memory",
                summary="抽取、反思回路、记忆总线 v2 召回打分与生命周期。",
                help_topics=("记忆",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/chat_reply/character/memory_bus_v2.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/memory_store_v21.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py",
                ),
                config_prefixes=("bot_memory_", "bot_reflection_"),
                extra_l3=(
                    ("memory-extract", "抽取与提示词硬化"),
                    ("reflection-loop", "夜间反思回路"),
                    ("memory-recall", "召回打分与冗余惩罚"),
                    ("memory-forget", "遗忘、墓碑与恢复"),
                ),
            ),
            FeatureNode(
                fid="B04.knowledge",
                label="知识库与检索",
                slug="knowledge",
                summary="知识源、分块、索引与配额；来源可信度约束。",
                help_topics=("搜索",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/core/search",
                    "plugins/bot_unified_runtime/domains/chat_reply/character/teaching_service.py",
                    # 检索与知识波（席19 2026-10-03 登记）：联网判定与 GENERAL 域 LLM
                    # 二判钩子真身（原生工具审批账在 domains/core/search 目录认领内）。
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/question_intent.py",
                ),
                config_prefixes=("bot_knowledge_", "bot_search_"),
                extra_l3=(
                    ("kb-indexing", "分块与索引状态"),
                    ("kb-quota", "来源配额与检索预算"),
                    ("web-search-intent", "联网判定与 GENERAL 二判钩子"),
                    ("tool-admission", "工具注册审批账"),
                ),
            ),
            FeatureNode(
                fid="B04.notes",
                label="笔记与授时",
                slug="notes",
                summary="Markdown 笔记 CRUD、自然语言勾选、NTP 授时时序。",
                help_topics=("笔记",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/notes/capabilities/notes.py",
                    "plugins/bot_unified_runtime/domains/notes/store",
                ),
                config_prefixes=("bot_notes_", "bot_time_sync_"),
                extra_l3=(
                    ("notes-crud", "记/看/放下/列表"),
                    ("mark-done", "自然语言完成勾选"),
                    ("time-sync", "NTP 授时与钟差钳制"),
                ),
            ),
        ),
    ),
    BoardNode(
        bid="B05",
        label="外部资讯与数据服务",
        slug="external-data-services",
        tagline="从外部世界取真数，取不到就诚实说取不到。",
        responsibilities=(
            "天气与预警、金融行情、快讯与历史上的今天",
            "订阅源、紧急信息、链接解析、百科参考",
            "缺源必须显式标注，绝不编造数值",
        ),
        features=(
            FeatureNode(
                fid="B05.weather",
                label="天气与预警",
                slug="weather",
                summary="NMC 主通道重试、Open-Meteo 兜底、预警支路与地名定位。",
                route_kinds=("WEATHER",),
                capability_ids=("bot.weather",),
                help_topics=("天气",),
                impl_paths=("plugins/bot_unified_runtime/domains/weather",),
                config_prefixes=("bot_weather_",),
                extra_l3=(
                    ("nmc-forecast", "NMC 预报与码表"),
                    ("alert-branch", "预警支路"),
                    ("geo-locating", "地名解析与变体链"),
                ),
            ),
            FeatureNode(
                fid="B05.finance",
                label="金融行情",
                slug="finance",
                summary="股指、个股、商品、债券、北向与汇率，含交叉核验脚注。",
                route_kinds=("MARKET", "STOCKS", "COMMODITIES", "BOND", "NORTHBOUND", "FX"),
                capability_ids=(
                    "bot.market",
                    "bot.stocks",
                    "bot.commodities",
                    "bot.bond",
                    "bot.northbound",
                    "bot.fx",
                ),
                help_topics=("行情", "个股行情", "商品行情", "国债收益率", "北向资金", "汇率"),
                impl_paths=("plugins/bot_unified_runtime/domains/finance",),
                config_prefixes=("bot_market_", "bot_stocks_", "bot_fx_"),
                extra_l3=(
                    ("global-indices", "全球指数与走势图"),
                    ("single-stocks", "个股 OHLCV 与分布"),
                    ("commodities", "大宗商品"),
                    ("bonds", "国债收益率与期限利差"),
                    ("northbound", "北向资金口径"),
                    ("fx-panels", "汇率面板与定向换算"),
                ),
            ),
            FeatureNode(
                fid="B05.news",
                label="快讯与历史上的今天",
                slug="news",
                summary="多源 RSS 营销过滤、条目限额与日历型推送。",
                route_kinds=("NEWS", "TODAY_HISTORY"),
                capability_ids=("bot.news", "bot.today_history"),
                help_topics=("快报", "历史上的今天"),
                impl_paths=("plugins/bot_unified_runtime/domains/subscribe/feeds",),
                config_prefixes=("bot_news_", "bot_today_history_"),
                extra_l3=(
                    ("news-digest-card", "新闻摘要卡"),
                ),
            ),
            FeatureNode(
                fid="B05.subscription",
                label="订阅与更新推送",
                slug="subscription",
                summary="B 站/YT/小红书/推特/微博/Epic 订阅与 outbox 落库。",
                route_kinds=("SUBSCRIBE", "EPIC"),
                capability_ids=("bot.subscribe", "bot.epic"),
                help_topics=("订阅", "Epic"),
                impl_paths=("plugins/bot_unified_runtime/domains/subscribe", "plugins/bot_unified_runtime/domains/subscribe/adapters"),
                config_prefixes=("bot_subscribe_",),
                extra_l3=(
                    ("platform-subscription", "各平台订阅通道"),
                    ("outbox-delivery", "更新出队与投递"),
                ),
            ),
            FeatureNode(
                fid="B05.emergency-info",
                label="紧急信息与预警",
                slug="emergency-info",
                summary="权威源采集、定级、审核门与群内订阅投递。",
                route_kinds=("EMERGENCY_INFO",),
                capability_ids=("bot.emergency_info",),
                help_topics=("紧急信息",),
                impl_paths=("plugins/bot_unified_runtime/domains/emergency_info",),
                config_prefixes=("bot_emergency_info_",),
                extra_l3=(
                    ("collection-sources", "四权威源采集"),
                    ("alert-taxonomy", "预警谱与定级"),
                    ("review-gate", "权威源审核门"),
                    ("group-subscriptions", "群内订阅与投递门"),
                ),
            ),
            FeatureNode(
                fid="B05.link-parse",
                label="链接解析与内容理解",
                slug="link-parse",
                summary="多平台链接解析、正文抽取与 Cookie 归因。",
                route_kinds=("CONTENT",),
                capability_ids=("bot.content",),
                help_topics=("解析", "链接"),
                impl_paths=("plugins/bot_unified_runtime/domains/link_parse",),
                config_prefixes=("bot_link_parse_", "bot_parse_"),
                extra_l3=(
                    ("parser-rules", "解析器规则族与归因"),
                    ("credential-scoping", "凭证域名绑定与剥离"),
                ),
            ),
            FeatureNode(
                fid="B05.reference-wiki",
                label="百科与参考查询",
                slug="reference-wiki",
                summary="维基百科、萌娘百科与地点/作品参考。",
                route_kinds=("WIKI", "MOEGIRL", "MOEGIRL_QUESTION"),
                capability_ids=("bot.wiki", "bot.moegirl"),
                help_topics=("维基", "萌娘百科"),
                impl_paths=("plugins/bot_unified_runtime/domains/location",),
                config_prefixes=("bot_wiki_", "bot_moegirl_"),
            ),
        ),
    ),
    BoardNode(
        bid="B06",
        label="多媒体与娱乐",
        slug="media-entertainment",
        tagline="声音、图像、表情、点歌、占卜与吃什么。",
        responsibilities=(
            "TTS 语音合成与媒体归档",
            "识图/搜图/视频抽帧",
            "表情与随机图、点歌、占卜、创作与菜谱",
        ),
        features=(
            FeatureNode(
                fid="B06.tts",
                label="语音合成",
                slug="tts",
                summary="GPT-SoVITS 契约层、退避与提交点、缓存身份与音色守望。",
                route_kinds=("TTS",),
                capability_ids=("bot.tts",),
                help_topics=("语音",),
                impl_paths=("plugins/bot_unified_runtime/domains/media/capabilities/tts.py", "plugins/bot_unified_runtime/domains/creation/tts"),
                config_prefixes=("bot_tts_",),
                extra_l3=(
                    ("engine-contract", "引擎契约与参数域"),
                    ("backoff-and-commit", "退避窗口与成功提交点"),
                    ("voice-identity", "参考音频与音色基线"),
                    ("synthesis-cache", "缓存键与落盘命名"),
                ),
            ),
            FeatureNode(
                fid="B06.media-archive",
                label="媒体归档",
                slug="media-archive",
                summary="VLM 判类别×IP 双层归档、去重与限额。",
                route_kinds=("MEDIA_ARCHIVE",),
                capability_ids=("bot.media_archive",),
                help_topics=("媒体归档",),
                impl_paths=("plugins/bot_unified_runtime/domains/media/archive", "plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py"),
                config_prefixes=("bot_media_archive_",),
            ),
            FeatureNode(
                fid="B06.vision",
                label="图像与视频理解",
                slug="vision",
                summary="识图、搜图、视频抽帧与字幕；失败三分类诚实上报。",
                help_topics=("搜图", "视频理解"),
                impl_paths=("plugins/bot_unified_runtime/domains/media",),
                config_prefixes=("bot_vision_", "bot_image_search_"),
                # image_search：旁路 matcher 有意不入 base_router 审计（__init__ 原注），被动类在案。
                passive_matchers=(("image_search", "on_message", 46),),
                extra_l3=(
                    ("image-describe", "识图与场景归属"),
                    ("image-search", "以图搜图与来源"),
                    ("video-frames", "抽帧与字幕链路"),
                ),
            ),
            FeatureNode(
                fid="B06.meme",
                label="表情包与图库",
                slug="meme",
                summary="表情生成、收库、NSFW 降权与随机图。",
                route_kinds=("MEME", "MEME_LIBRARY", "RANDPIC"),
                capability_ids=("bot.meme", "bot.meme_library", "bot.randpic"),
                help_topics=("表情", "偷表情", "表情册", "表情收库", "随机图"),
                impl_paths=("plugins/bot_unified_runtime/domains/meme",),
                config_prefixes=("bot_meme_", "bot_randpic_"),
                # meme_absorb（无 rule 的吸收面 matcher）：收库被动入口，归本 fid。
                passive_matchers=(("meme_absorb", "on_message", 10),),
            ),
            FeatureNode(
                fid="B06.music",
                label="点歌",
                slug="music",
                summary="多供应商点歌、候选卡与真实榜单。",
                route_kinds=("MUSIC", "MUSIC_MODE"),
                capability_ids=("bot.music", "bot.music_mode"),
                help_topics=("点歌",),
                impl_paths=("plugins/bot_unified_runtime/domains/music",),
                config_prefixes=("bot_music_",),
            ),
            FeatureNode(
                fid="B06.divination",
                label="占卜",
                slug="divination",
                summary="八字、塔罗、金钱卦；牌算与抽卡存储单一真身。",
                route_kinds=("DIVINATION",),
                capability_ids=("bot.divination",),
                help_topics=("占卜",),
                impl_paths=("plugins/bot_unified_runtime/domains/divination",),
                config_prefixes=("bot_divination_",),
                extra_l3=(
                    ("deck-math", "牌算与节气算法真身"),
                    ("draw-store", "抽卡记录单一存储"),
                ),
            ),
            FeatureNode(
                fid="B06.creation",
                label="创作与图片生成",
                slug="creation",
                summary="图像/语音创作扩展位与共用件。",
                help_topics=("草稿",),
                impl_paths=("plugins/bot_unified_runtime/domains/creation",),
                config_prefixes=("bot_creation_",),
            ),
            FeatureNode(
                fid="B06.food",
                label="吃什么与菜谱",
                slug="food",
                summary="菜谱检索与饭点推荐，含图片质检与防污染。",
                route_kinds=("EAT",),
                capability_ids=("bot.eat",),
                help_topics=("吃什么",),
                impl_paths=("plugins/bot_unified_runtime/domains/food",),
                config_prefixes=("bot_eat_", "bot_food_"),
            ),
        ),
    ),
    BoardNode(
        bid="B07",
        label="日程·自动化·助理",
        slug="schedule-automation",
        tagline="没有人发消息时，她按时间与条件自己动。",
        responsibilities=(
            "提醒与调度器族（cron 口径统一）",
            "定时推送：每日摘要、收件箱早报晚报、历史上的今天",
            "校园自动转发等纯监听旁路",
            "自检与巡检（同步漂移、就绪度、凭据到期）",
        ),
        features=(
            FeatureNode(
                fid="B07.reminders",
                label="提醒督促",
                slug="reminders",
                summary="自然语言时间点→会话待办→到点投递，含迟到与过期治理。",
                route_kinds=("REMINDER",),
                capability_ids=("bot.reminder",),
                help_topics=("提醒",),
                impl_paths=("plugins/bot_unified_runtime/domains/schedule",),
                config_prefixes=("bot_reminder_",),
                extra_l3=(
                    ("natural-time-parsing", "时间点解析词表"),
                    ("delivery-and-lateness", "投递、顺延与作废"),
                ),
            ),
            FeatureNode(
                fid="B07.schedule-board",
                label="日程板与智能代答",
                slug="schedule-board",
                summary="自然语言/命令/课表导入建日程板（复用 V2.1 引擎），"
                        "别人问「她在干嘛」按可见性分级代答（隐私判定在出站前）。",
                help_topics=("日程",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/schedule/capabilities/schedule_board.py",
                    "plugins/bot_unified_runtime/domains/schedule/service/board_store.py",
                ),
                config_prefixes=("bot_schedule_",),
                extra_l3=(
                    ("visibility-projection", "可见性分级投影（代答腿）"),
                    ("timetable-import", "课表文本/图片导入"),
                ),
            ),
            FeatureNode(
                fid="B07.scheduled-jobs",
                label="调度器族与定时推送",
                slug="scheduled-jobs",
                summary="根装配期注册的全部定时任务清单、时区口径与去重。",
                help_topics=("群摘要",),
                impl_paths=("plugins/bot_unified_runtime/__init__.py",),
                config_prefixes=("bot_digest_", "bot_daily_assist_"),
                extra_l3=(
                    ("send-queue-scheduler", "发送队列驱动"),
                    ("reflection-scheduler", "夜间反思窗口"),
                    ("digest-push", "每日通讯摘要推送"),
                    ("today-history-scheduler", "历史上的今天推送"),
                    ("credential-check-scheduler", "凭据到期巡检"),
                    ("kb-wiki-sync-scheduler", "知识库同步"),
                    # 文件链路波（席19 2026-10-03 登记）：每日 04:50 落盘点 TTL 清扫
                    # （job id bot_file_sweep_tick，清扫真身归 B08.file-gateway）。
                    ("file-sweep-scheduler", "落盘点 TTL 清扫调度"),
                ),
            ),
            FeatureNode(
                fid="B07.daily-assist",
                label="日常助理与收件箱",
                slug="daily-assist",
                summary="收件箱速记、饭点建议、早晚对账推送。",
                route_kinds=("DAILY_ASSIST",),
                capability_ids=("bot.daily_assist",),
                help_topics=("收件箱",),
                impl_paths=("plugins/bot_unified_runtime/domains/assistant/daily",),
                config_prefixes=("bot_daily_assist_",),
            ),
            FeatureNode(
                fid="B07.campus-forward",
                label="校园自动转发",
                slug="campus-forward",
                summary="三重来源门 + 幂等去重的纯监听旁路，绝不向源群发言。",
                impl_paths=("plugins/bot_unified_runtime/domains/assistant/campus",),
                config_prefixes=("bot_campus_",),
                passive_matchers=(("campus_record_matcher", "on_message", 8),),
            ),
            FeatureNode(
                fid="B07.auto-send",
                label="自动发送与主动搭话",
                slug="auto-send",
                summary="主动性行为的门、概率与冷却，以及失败静默口径。",
                route_kinds=("AUTO_SEND",),
                capability_ids=("bot.auto_send",),
                help_topics=("队列",),
                config_prefixes=("bot_auto_send_", "bot_reactions_"),
                # emoji_like_notice＝贴纸回应的群聊 only 派发面；group_increase_notice＝入群欢迎
                # （R-4 走统一管线）。两者都不走 RouteKind，被动类在案。
                passive_matchers=(
                    ("emoji_like_notice", "on_notice", 7),
                    ("group_increase_notice", "on_notice", 6),
                ),
                extra_l3=(("sticker-reactions", "表情回应的五层防刷屏门"),),
            ),
            FeatureNode(
                fid="B07.ops-inspection",
                label="巡检与同步漂移",
                slug="ops-inspection",
                summary="源-副本漂移检测、告警投递与重启前体检。",
                impl_paths=("plugins/bot_unified_runtime/domains/ops/sync_drift", "scripts/pre_restart_check.py"),
                config_prefixes=("bot_sync_drift_",),
            ),
        ),
    ),
    BoardNode(
        bid="B08",
        label="渲染与出站统一",
        slug="render-outbound",
        tagline="所有内容只有一种长法和一条出口。",
        responsibilities=(
            "卡片渲染管线与 token 单一事实源",
            "纯文本兜底与出站文案口径",
            "审核门→发送队列→传输器的唯一出站路径",
            "文件网关与受控下载",
        ),
        features=(
            FeatureNode(
                fid="B08.card-render",
                label="卡片渲染",
                slug="card-render",
                summary="釉瑚云母卡片、主题 token 契约与 playwright 出图。",
                impl_paths=("plugins/bot_unified_runtime/domains/render", "docs/rendering-contract.md"),
                config_prefixes=("bot_render_",),
                extra_l3=(
                    ("theme-tokens", "token 单一事实源与阴影族"),
                    ("templates", "Jinja 模板与 f-string 直拼卡"),
                    ("render-backend", "常驻浏览器与失败兜底"),
                    ("animation-pinning", "动画钉帧与截图确定性"),
                ),
            ),
            FeatureNode(
                fid="B08.outbound-copy",
                label="出站文案与纯文本兜底",
                slug="outbound-copy",
                summary="说人话、分段换行统一、密钥与路径打码。",
                impl_paths=("plugins/bot_unified_runtime/output", "plugins/bot_unified_runtime/domains/render/plain_text.py"),
                extra_l3=(
                    ("plain-text-fallback", "渲染失败降级纯文本"),
                    ("paragraph-breaks", "段间换行统一"),
                    ("secret-redaction", "本地密钥与路径打码"),
                ),
            ),
            FeatureNode(
                fid="B08.review-gate",
                label="出站审核",
                slug="review-gate",
                summary="发送前的统一审核面与 BLOCK 观测。",
                impl_paths=("plugins/bot_unified_runtime/domains/render/reviewer.py",),
            ),
            FeatureNode(
                fid="B08.send-queue",
                label="发送队列与回执",
                slug="send-queue",
                summary="part 级幂等、UNKNOWN 确认、PARTIAL 断点续发与投递回执。",
                help_topics=("回执",),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/transport/sender/__init__.py",
                    # 〔2026-09-29 S-FIX-PLACE3 归主〕failure_class.py 生于 ②D-5 八枚名册之后
                    # （2026-09-28 TG 连接期重投波，台账 #65）：判据产出随失败回执上抛、被
                    # worker 的 UNKNOWN/重投语义逐字消费 ⇒ 队列侧本尊，归本 fid 而非协议腿。
                    "plugins/bot_unified_runtime/domains/transport/sender/failure_class.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/gateway.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/queue.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/receipts.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/timeout.py",
                    "plugins/bot_unified_runtime/domains/transport/sender/worker.py",
                ),
                config_prefixes=("bot_send_queue_",),
                extra_l3=(
                    ("queue-persistence", "SQLite 队列与恢复"),
                    ("delivery-receipt", "回执与对账"),
                ),
            ),
            FeatureNode(
                fid="B08.file-gateway",
                label="文件网关与受控下载",
                slug="file-gateway",
                summary="FileSource→Ticket→通道交付，SSRF 护栏与路径白名单。",
                help_topics=("下载", "文件", "群文件"),
                impl_paths=("plugins/bot_unified_runtime/domains/files",),
                config_prefixes=("bot_file_gateway_", "bot_download_"),
                # 四枚被动面：群文件上传记录 / 管理员私聊文件接收 / 管理员文件导出 / 群文件统计。
                passive_matchers=(
                    ("group_upload_notice", "on_notice", 6),
                    ("file_notice", "on_notice", 8),
                    ("file_export", "on_message", 8),
                    ("group_file_stats", "on_message", 8),
                ),
                # 文件链路波（席19 2026-10-03 登记）两枚机制卡：入站文件上下文回填注记
                # （真身 file_reader.build_incoming_file_context_note，notice 腿接线在
                # 根 __init__ 的 file_notice 处理器）与落盘点 TTL 清扫（真身
                # restricted_runner.sweep_expired_files；每日调度注册面归 B07.scheduled-jobs）。
                extra_l3=(
                    ("incoming-file-context", "入站文件上下文回填注记"),
                    ("file-landing-sweep", "落盘点 TTL 清扫"),
                ),
            ),
            FeatureNode(
                fid="B08.error-reporting",
                label="统一错误报告",
                slug="error-reporting",
                summary="内部异常→诊断卡两段式异步，冷却与纯文本兜底。",
                impl_paths=("plugins/bot_unified_runtime/domains/ops/monitor/error_report.py",),
                config_prefixes=("bot_error_card_",),
            ),
        ),
    ),
    BoardNode(
        bid="B09",
        label="控制面·配置·可观测",
        slug="control-plane-observability",
        tagline="一切状态可查、一切开关可控、一切动作可审计。",
        responsibilities=(
            "/api/v1 统一 envelope、鉴权与 OpenAPI",
            "配置单一入口、热更与重启口径诚实",
            "日志、指标、Trace、审计四类可观测面",
            "模型供应商/渠道/模型三级控制与账本",
        ),
        features=(
            FeatureNode(
                fid="B09.control-plane-api",
                label="控制面 API 与工作区",
                slug="control-plane-api",
                summary="loopback + Bearer 的 /api/v1 端点群、工作区沙箱与动作执行。",
                impl_paths=("plugins/bot_unified_runtime/control_plane",),
                config_prefixes=("bot_control_plane_",),
                extra_l3=(
                    ("api-envelope", "统一响应与错误码"),
                    ("auth-and-rbac", "鉴权与角色边界"),
                    ("workspaces", "工作区沙箱与真实会话"),
                    ("remote-actions", "白名单远程动作"),
                ),
            ),
            FeatureNode(
                fid="B09.config-and-settings",
                label="配置与运行时设置",
                slug="config-and-settings",
                summary="Config 单一入口、SETTABLE_KEYS/RESTART_REQUIRED_KEYS 与读取端点，"
                        "以及危险参数改动的书面同意命令面（咽喉的四档裁决住 safety_exec）。",
                route_kinds=("CONSENT",),
                help_topics=("配置", "设置", "就绪", "书面同意"),
                impl_paths=(
                    "plugins/bot_unified_runtime/config.py",
                    "plugins/bot_unified_runtime/domains/core/config",
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/settings.py",
                    "docs/config-catalog-full.md",
                ),
                extra_l3=(
                    ("config-declaration", "字段声明与校验器"),
                    ("hot-reload-model", "热更、drain 与回滚"),
                    ("env-example-catalog", "示例与目录三处同源"),
                ),
            ),
            FeatureNode(
                fid="B09.feature-switches",
                label="功能开关树",
                slug="feature-switches",
                summary="组/插件/子功能/指令四级开关与依赖阻断显示。",
                help_topics=("运行开关",),
                impl_paths=("plugins/bot_unified_runtime/domains/ops/features",),
                extra_l3=(("feature-gate", "父子继承与 blocked_by"),),
            ),
            FeatureNode(
                fid="B09.observability",
                label="日志·指标·Trace·审计",
                slug="observability",
                summary="统一事件总线、来源枚举、指标结构化与轨迹阶段表。",
                route_kinds=("HOST_STATE",),
                capability_ids=("bot.host_state",),
                help_topics=("日志", "状态", "审计", "用量", "宿主机状态"),
                impl_paths=(
                    "plugins/bot_unified_runtime/domains/ops/audit",
                    "plugins/bot_unified_runtime/domains/ops/collectors",
                    "plugins/bot_unified_runtime/domains/ops/monitor/__init__.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/alerts.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/event_service.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/event_store.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/host_card.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/host_status.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/loop_watchdog.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/result_unknown.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/runtime_event_log.py",
                    "plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py",
                    # 文件链路波（席19 2026-10-03 登记）：宿主快照分区注记口
                    # （采样只复用 host_metrics 在册采集器，注入面在 B03.persona-context）。
                    "plugins/bot_unified_runtime/domains/ops/host_snapshot.py",
                ),
                config_prefixes=("bot_alerts_", "bot_metrics_"),
                # 退群/管理员变动只记事件不发言（公开点名是减分项）——纯可观测面，归本 fid。
                passive_matchers=(
                    ("group_decrease_notice", "on_notice", 6),
                    ("group_admin_notice", "on_notice", 6),
                ),
                extra_l3=(
                    ("event-bus", "统一事件与 SSE"),
                    ("metrics-sources", "指标结构化来源"),
                    ("trace-stages", "轨迹阶段与脱敏"),
                    ("ops-alerts", "运维告警与抑制"),
                    ("host-snapshot-section", "宿主快照分区注记口"),
                ),
            ),
            FeatureNode(
                fid="B09.model-control",
                label="模型路由与账本",
                slug="model-control",
                summary="provider/channel/model 三级、failover、上下文钳制与计费账本。",
                help_topics=("模型", "供应商"),
                impl_paths=("plugins/bot_unified_runtime/llm", "plugins/bot_unified_runtime/domains/chat_reply/llm_engine"),
                config_prefixes=("bot_model_", "bot_llm_", "bot_chat_failover_"),
                extra_l3=(
                    ("model-router", "优先级组与失败转移"),
                    ("fail-fast", "链级快速中止与冷却"),
                    ("context-caps", "上下文与输出钳制"),
                    ("billing-ledger", "调用记录与计价"),
                ),
            ),
            FeatureNode(
                fid="B09.admin-commands",
                label="管理命令面",
                slug="admin-commands",
                summary="管理员与超管专属命令、诊断与恢复动作。",
                impl_paths=("plugins/bot_unified_runtime/domains/ops/admin", "plugins/bot_unified_runtime/domains/ops/incident"),
                extra_l3=(
                    ("diagnostics", "诊断与快照"),
                    ("recovery", "自愈与回滚"),
                ),
            ),
        ),
    ),
    BoardNode(
        bid="B10",
        label="工程基座与治理",
        slug="engineering-governance",
        tagline="门禁、生成物、命名规范与安全护栏——文档与代码不靠自觉。",
        responsibilities=(
            "任务入口 dev.ps1 与四门禁",
            "生成物三件与机器事实册（漂移即红）",
            "命名/结构/文档骨架统一规范",
            "路径重映射、树卫生与归档规程",
        ),
        features=(
            FeatureNode(
                fid="B10.task-entry",
                label="任务入口与门禁",
                slug="task-entry",
                summary="lint / typecheck / runtime-layout / test 四门禁与退出码语义。",
                impl_paths=("scripts/dev.ps1", "scripts/runtime_layout_smoke.py"),
            ),
            FeatureNode(
                fid="B10.generated-artifacts",
                label="生成物与机器事实册",
                slug="generated-artifacts",
                summary="doc_sync / command_catalog / verify_hashes 三件与 auto-facts 投影。",
                impl_paths=(
                    "scripts/doc_sync.py",
                    "scripts/command_catalog.py",
                    "docs/auto-facts.md",
                ),
                extra_l3=(
                    ("machine-ledger", "会漂移计数的唯一落点"),
                    ("hash-bookkeeping", "交付物哈希与重录时机"),
                ),
            ),
            FeatureNode(
                fid="B10.test-gates",
                label="测试与机器门体系",
                slug="test-gates",
                summary="离线 mock 全量树、契约门、棘轮门与交叉验证。",
                impl_paths=("tests",),
                extra_l3=(
                    ("contract-gates", "渲染与出站契约门"),
                    ("ratchet-gates", "棘轮与地板门"),
                    ("mutation-testing", "变异注毒自证"),
                ),
            ),
            FeatureNode(
                fid="B10.naming-conventions",
                label="命名与结构规范",
                slug="naming-conventions",
                summary="模块/函数/参数/配置键命名与一功能一目录的结构规范。",
                impl_paths=("docs/boards/_conventions.md",),
                extra_l3=(
                    ("identifier-naming", "标识符与参数命名规则"),
                    ("module-layout", "模块与目录归属规则"),
                    ("docstring-spec", "函数说明文档骨架"),
                ),
            ),
            FeatureNode(
                fid="B10.security-guardrails",
                label="安全与凭据护栏",
                slug="security-guardrails",
                summary="SSRF 咽喉、凭据域名绑定、打码与最小暴露面。",
                help_topics=("凭据",),
                # 〔2026-09-29 S-FIX-PLACE3 双认领拆账〕`security` 垫片退役后本 fid 改锚真身目录，
                # 与 B03.content-safety 撞成字面双认领——见彼处注：逐文件拆开，反注入咽喉、
                # 显示伪装消毒与其取证台账（ATK-P2D 波，AGENTS 规则 11 的直接应用）与包门面
                # （只再导出 injection 一族）归本 fid；六硬线闸与记忆净化归 B03.content-safety。
                impl_paths=("plugins/bot_unified_runtime/domains/core/credentials",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/__init__.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/dangerous_command.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/injection.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/display_guard.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/security/spoof_audit.py",
                    "plugins/bot_unified_runtime/domains/chat_reply/runtime/database_broker.py"),
                config_prefixes=("bot_ssrf_",),
                # cookie_admin（管理员 cookie 状态/导入命令面）：真身 domains/core/credentials，归本 fid。
                passive_matchers=(("cookie_admin", "on_message", 8),),
                extra_l3=(
                    ("ssrf-throat", "下载入口与落点双查"),
                    ("credential-scrub", "跨域凭证剥离"),
                    ("exposure-floor", "敏感信息不回传"),
                    # 安全与文档波出站面（席19 2026-10-03 登记）：破坏性命令输出审查，
                    # 与 B08.outbound-copy 的渲染层打码（redact_destructive_commands）构成双层。
                    ("outbound-command-screen", "出站危险命令审查"),
                ),
            ),
            FeatureNode(
                fid="B10.workspace-hygiene",
                label="路径重映射与树卫生",
                slug="workspace-hygiene",
                summary="运行数据根重映射、零缓存铁律与归档规程。",
                impl_paths=("scripts/runtime_paths.py", "docs/workspace-archive-policy.md"),
                extra_l3=(
                    ("runtime-paths", "相对路径到 Runtime 的映射"),
                    ("archive-procedure", "压缩→验证→移出"),
                ),
            ),
            FeatureNode(
                fid="B10.documentation",
                label="文档体系与板块树",
                slug="documentation",
                summary="十板块文档树、统一骨架、单一事实源与自动化同步契约。",
                impl_paths=(
                    "docs/README.md",
                    "docs/HANDBOOK.md",
                    "docs/CODE-MAP.md",
                ),
                extra_l3=(
                    ("board-tree", "一/二/三级板块树本体"),
                    ("doc-taxonomy-sync", "板块树与代码的自动同步"),
                    ("legacy-doc-migration", "旧汇总文档的归属与退役"),
                ),
            ),
        ),
    ),
)


#: 板块账派不出来的两族发行库：地基库 ``contracts`` 与四座通道适配器库 A1-A4。
#: 成员一律逐枚字面路径（派生尺见 S741 报告 §三）；``scripts/telegram_resilience.py`` 刻意不入册——
#: 库工厂的成员宇宙只扫 ``plugins/**``，把树外件写进名册＝让一支发版本的库依赖一支根本不存在的仓。
LIBRARY_TAXONOMY: tuple[ReleaseLibNode, ...] = (
    ReleaseLibNode(
        lid='L0',
        label='接口协议地基库',
        slug='contracts',
        kind='foundation',
        summary='全仓唯一「谁都可以依赖、它谁都不依赖」的契约叶子层：不被任何业务板块认领，只被依赖。',
        member_paths=(
            'plugins/bot_unified_runtime/contracts/__init__.py',
            'plugins/bot_unified_runtime/domains/core/contracts/__init__.py',
            'plugins/bot_unified_runtime/domains/core/contracts/auto_send.py',
            'plugins/bot_unified_runtime/domains/core/contracts/character.py',
            'plugins/bot_unified_runtime/domains/core/contracts/envelope.py',
            'plugins/bot_unified_runtime/domains/core/contracts/errors.py',
            'plugins/bot_unified_runtime/domains/core/contracts/finance.py',
            'plugins/bot_unified_runtime/domains/core/contracts/media.py',
            'plugins/bot_unified_runtime/domains/core/contracts/music.py',
            'plugins/bot_unified_runtime/domains/core/contracts/request.py',
            'plugins/bot_unified_runtime/domains/core/contracts/runtime.py',
            'plugins/bot_unified_runtime/domains/core/contracts/subscription.py',
        ),
    ),
    ReleaseLibNode(
        lid='A1',
        label='QQ 通道适配器库',
        slug='adapter-qq',
        kind='adapter',
        summary='OneBot V11 腿（`onebot.py`，手卷 HTTP/WS、不经适配器包）＋ NoneBot 通用腿'
                '（`nonebot.py`：Telegram／Mail／Console 三条通道的 deliver 实现同住这一枚）。'
                '⚠ 座名叫 adapter-qq 而成员跨四通道的口径偏差已登记，见本包 §待裁 F-1。',
        channel='onebot',
        pending_seed=(
            (
                'plugins/bot_unified_runtime/domains/transport/sender/nonebot.py',
                '落点在盘上、已被 B01.qq-snowluma 板块库装着（板块账未让位，S-FIX-PLACE3 2026-09-29 归主）＝播种三态之③',
            ),
            (
                'plugins/bot_unified_runtime/domains/transport/sender/onebot.py',
                '落点在盘上、已被 B01.qq-snowluma 板块库装着（板块账未让位，S-FIX-PLACE3 2026-09-29 归主）＝播种三态之③',
            ),
        ),
    ),
    ReleaseLibNode(
        lid='A2',
        label='Telegram 通道适配器库',
        slug='adapter-telegram',
        kind='adapter',
        summary='getUpdates 轮询韧性与 file_id 取字节；现役真身还住在仓根 scripts/，等搬家。',
        channel='telegram',
        pending_seed=(
            (
                'plugins/bot_unified_runtime/domains/transport/telegram/resilience.py',
                '搬家未落（播种三态之①）：现役真身＝scripts/telegram_resilience.py，落在库工厂成员宇宙之外；且搬进 plugins/** 会提前执行插件根（bot.py 装载序），须她明示授权',
            ),
        ),
    ),
    ReleaseLibNode(
        lid='A3',
        label='Mail 通道适配器库',
        slug='adapter-mail',
        kind='adapter',
        summary='ResilientMailAdapter 与来信桥：全仓唯一以 import 上游适配器包为通道证据的一路。',
        channel='mail',
        pending_seed=(
            (
                'plugins/bot_unified_runtime/domains/transport/mail/mail_adapter.py',
                '落点在盘上、已被 B01.mail-console 板块库装着（板块账未让位）＝播种三态之③',
            ),
            (
                'plugins/bot_unified_runtime/domains/transport/mail/mail_bridge.py',
                '落点在盘上、已被 B01.mail-console 板块库装着（板块账未让位）＝播种三态之③',
            ),
        ),
    ),
    ReleaseLibNode(
        lid='A4',
        label='Console 通道适配器库',
        slug='adapter-console',
        kind='adapter',
        summary='按字面的第四通道：今天零成员，只有两处互相矛盾的触点，建库即建一支空仓。',
        channel='console',
        pending_seed=(
            (
                'none',
                '按字面无成员（播种三态之②）：全仓零 register_adapter 注册到 Console、生产代码零 nonebot.adapters.console import（extra 声明不算）；三案未裁，裁完再定入不入册',
            ),
        ),
    ),
)


def iter_release_libs() -> Iterator[ReleaseLibNode]:
    """按声明序遍历非板块发行库（板块库由板块账派生，绝不在本表）。"""
    yield from LIBRARY_TAXONOMY


def lib_by_slug(slug: str) -> ReleaseLibNode | None:
    for lib in LIBRARY_TAXONOMY:
        if lib.slug == slug:
            return lib
    return None


def board_by_id(bid: str) -> BoardNode | None:
    for board in BOARD_TAXONOMY:
        if board.bid == bid:
            return board
    return None


def iter_features() -> Iterator[FeatureNode]:
    """按板块序、板块内声明序遍历二级功能。"""
    for board in BOARD_TAXONOMY:
        yield from board.features


def feature_by_id(fid: str) -> FeatureNode | None:
    for feature in iter_features():
        if feature.fid == fid:
            return feature
    return None


__all__ = [
    "BOARD_TAXONOMY",
    "LIBRARY_TAXONOMY",
    "TAXONOMY_VERSION",
    "BoardNode",
    "FeatureNode",
    "ReleaseLibNode",
    "board_by_id",
    "feature_by_id",
    "iter_features",
    "iter_release_libs",
    "lib_by_slug",
]
