"""能力单一声明源（Keystone，审查 C-06）。

此前一个能力的 5 份属性（路由 kind / capability_id / priority / 接口登记 /
命令路由成员资格 / 内部能力说明）散落在 base_router.py 的 5 张手写清单里，
新增能力要改 4-5 处，漏登即不可见。本模块把它们收拢为**每能力一行**的常量
声明表：

- ``ROUTE_CAPABILITY_DECLARATIONS``：全部 RouteKind 成员（含 IGNORE
  兜底席）逐能力一行（成员数以 ``docs/auto-facts.md``/该表自身为准，本文不写死）；
  ``command`` 列在 base_router 派生
  ``COMMAND_ROUTE_KINDS``，``note`` 列对应 ``INTERNAL_CAPABILITY_NOTES``。
- ``INTERFACE_DECLARATIONS``：接口清单（含 reserved 预留席）逐行登记，
  字段与 ``base_router.InterfaceEntry`` 一一对应。

Wave 2（2026-09-21 统一接入波）· 本文件四张表在「能力在册」问题上的新身份：
本文件的 ``ROUTE_CAPABILITY_DECLARATIONS`` / ``CONTROLLED_INTERNAL_CAPABILITIES`` /
``HELP_TOPIC_DECLARATIONS`` / ``INTERFACE_DECLARATIONS`` 是**声明式输入源**，
「某个 capability_id 是否在册 + 它的 handler_ref/健康/降级/gate id/帮助主题/路由 kind」
的**唯一答案** = ``runtime/capability_protocols.CAPABILITY_DESCRIPTOR``
（五路输入取并集派生，编排侧第 5 路=该模块的 ``DESCRIPTOR_BUILDERS``）。
消费面已改读唯一表：``domains/ops/features/feature_catalog.py``（feature gate 绑定）
与 ``scripts/command_catalog.py``（路由派生，静态 AST 读本表字面而非正则扫 base_router）。
**纪律**：新能力只在本表 *或* 编排侧 builders 各登记一次，**不得为同一 id 在第二处
另立注册**；执法=``tests/test_capability_single_registration.py``（D-a 唯一在册 +
D-f gate 读同一处）。本四张表的字面形态不可改为运行时构造（四处静态解析器依赖，见下）。

依赖方向（防循环）：本模块除**一枚叶子**（`domains/core/capability_manifest.py`，其顶层只
import 标准库、且不被任何被依赖者反向 import ⇒ 无环）外不 import 包内模块；`base_router` 在
import 时从本表构造 ``COMMAND_ROUTE_KINDS``。这枚叶子边专供 ``config_keys_for(id)`` 把配置键
声明降为读册（S186 收编波 P2，见文件头注）。
⚠ 副作用如实报备：经包路径 import 该叶子会连带执行父包 ``plugins/bot_unified_runtime/__init__.py``
（其顶层 import nonebot），故 ``test_generic_executor_facets`` 之类"按文件 spec 装载、想绕开插件装配"
的取数件，装载本表时会触发一次父包装配（父包 ``sys.modules`` 全局缓存 ⇒ 只装配一次、不重复注册驱动、
实测 import 成功）——"绕开装配"这条便利自此对本表不再严格成立，是收编"配置键单一真身"换来的代价，
由该件实跑绿背书，不留"以为仍纯数据可裸装载"的旧假设。

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

# S186 中央调度收编波 P2：配置键声明降为读唯一真身册。
# 本模块其余四表的路由四要素（kind/value/capability_id/priority/has_rule…）仍保持字面形态
# （见上方纪律——command_catalog/doc_sync 等静态解析器按字面读那些字段）。
# 唯 `execution.config_keys` / `PipelineManagedExecution.config_keys` 两处例外：改由
# `config_keys_for(id)` 从 `domains/core/capability_manifest.py::FACETS` 现读，使「这枚能力读
# 哪几枚 Config 字段」只有一个真身。该 import 是本模块**唯一**的包内依赖，且被依赖者＝叶子
# （capability_manifest 顶层只 import 标准库），故不构成环、亦不改「只声明数据」的下游纯度：
# 本模块仍不被 capability_manifest 反向 import，base_router 在 import 期从本表构造 COMMAND_ROUTE_KINDS 不破。
from plugins.bot_unified_runtime.domains.core.capability_manifest import config_keys_for


@dataclass(frozen=True)
class CapabilityExecution:
    """一个路由能力的**执行面**（Wave 4.1：中央 invoker 治理 bot.* 的唯一 authoring 处）。

    为什么住在这里而不是壳的 descriptor 表：`test_no_capability_id_is_authored_in_two_places`
    钉死「同一 capability id 全树只准一处 authoring」，而路由能力的在册之家本就是本表
    （见 `ROUTE_CAPABILITY_DECLARATIONS` 上方指针注释）。壳按本字段**派生** CapabilityDescriptor
    并注册信封 handler ⇒ 一个 id 一个家、零第二真源、不放宽任何判据。
    不填＝该能力当前不经 invoker 执行（诚实在册，非已接入）。
    """

    implementation_ref: str
    """执行真身，路径式 `plugins/bot_unified_runtime/<域>/.../mod.py#symbol`（与描述符 implementation_ref 同形，完整性校验按此查文件存在）。命令形约定：`build_x_capability(config) -> (message, decision) -> CapabilityResult`。"""

    family: str
    """能力族（描述符 family）：bot.* 路由能力的执行面用 "command"（R-A/C-01：不混进内容契约族）；注册册不 import 壳，故存字面串由壳转枚举并派生即校验。"""

    adapter: str = "command"
    """信封适配器形态。目前只有 `command`（builder 收 config，返回 (message, decision) 可调用）。"""

    roles: tuple[str, ...] = ("user",)
    timeout_seconds: float = 30.0
    health_probe: str = ""
    """中央健康探针名；填了必须是壳内已注册探针，否则描述符完整性校验当场红。"""

    degrade_note: str = "真身异常/依赖缺失=诚实降级，不冒充成功"
    config_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineManagedExecution:
    """一条「管线管理形」（pipeline_managed）能力的执行面（第三种形态，2026-09-22）。

    与前两形的分野（见 docs/design/capability-orchestration-execution-morphology.md）：
    - 命令形（command）：builder 只吃 config，返回 `(message, decision) -> CapabilityResult`；
    - 预备形（prepared）：执行体由装配现场把**已装配**成品交来，壳绝不按 ref 自建；
    - 管线管理形（pipeline_managed）：执行体**不是**一个纯能力闭包，而是层 1 的
      `RuntimePipeline.handle_async(message, capability, capability_id)`——它自带门禁/
      审核/渲染/投递，返回 `DeliveryReceipt` 而非呈现契约。bot.chat 主链、订阅 outbox
      推送、campus 转发这几条「层 1 直呼面」正是这种形态（运维告警 bot.alert 走的是**同步**
      `pipeline.handle` 且被禁改的现状锁钉住，本波不登记，见下表内联注记）。

    为什么另立一张表、**不写进 `ROUTE_CAPABILITY_DECLARATIONS.execution`**：
    常驻缺口账门 `test_descriptor_wiredness_ledger.py`（禁改）的 `execution_shape_cids()`
    直读 `_route_execution_adapters()`，并要求其中**每一枚**都在根里有 `_run_simple_capability`
    / `_run_capability_through_pipeline` 汇缝字面量站点（⑤入口耐久锁）。而这几条直呼面
    今天走的是**裸 `pipeline.handle_async`**、不经那两个汇合函数（根文件正被另一波并发修改、
    本席禁动），把它们塞进 route 执行形会**当场把「登记即通电」的假账坐实**——账面翻绿而
    生产零变化。故本表把管线管理形单独登记，由壳经独立 builder 派生描述符 + 挂 handler，
    使 `default_invoker().invoke` 认得并能真跑它们，同时**不进** `_route_execution_adapters()`
    / `seam_registered_cids()`，缺口账对它们的现算归位（generic / not_wired）一寸不动。
    """

    capability_id: str
    """能力 id（须与根直呼面上 `handle_async(..., capability_id=X)` 的字面量同串）。"""

    title: str
    """人类标题（`validate_registry` 承重面，非空）。"""

    implementation_ref: str
    """执行真身，指向层 1 管线（`plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py#RuntimePipeline.handle_async`）。"""

    adapter: str = "pipeline_managed"
    """形态名（在册标记；壳按此挂 `_make_pipeline_managed_handler` 信封，不进 command/prepared 派发）。"""

    family: str = "pipeline"
    """能力族（描述符 family）：单独一族，避免污染 COMMAND 族计数锁（`len(iter(COMMAND))==len(_route_execution_rows())`）。"""

    roles: tuple[str, ...] = ("user",)
    timeout_seconds: float = 60.0
    degrade_note: str = "能力体/管线异常=诚实降级，不冒充投递成功"
    config_keys: tuple[str, ...] = ()
    input_protocol: str = (
        "pipeline.v1 {payload.message; context{pipeline,capability,decision?}}"
    )
    output_protocol: str = "delivery.v1 DeliveryReceipt{request_id,state,transport}"
    notes: str = ""


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
    execution: CapabilityExecution | None = None
    """执行面（可空）。填了＝这条路由能力**已在册且可经中央 invoker 执行**；
    没填＝只在册、未接入（缺口账见 tests/test_descriptor_wiredness_ledger.py）。"""


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
# 指针（Wave 2）：本表=唯一在册表 route 侧输入源；在册答案见
# runtime/capability_protocols.CAPABILITY_DESCRIPTOR，勿在他处为同 id 另立注册。
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
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/meme/capabilities/meme.py"
                "#build_meme_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=120.0,  # 内层串行之和才作数：信息 15s + N×(取图 10s+上传 15s) + 生成 15s + 取图 15s = 60+25N；N=2⇒110，留 10s 余量（S-TIMEOUT 实算）
            health_probe="",  # generator 可达性无在册探针映射，诚实留空
            degrade_note="生成器不可达=诚实失败，绝不假发图",
            config_keys=("bot_meme_api_timeout_seconds",),
        ),
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
        # prepared 形 P9 批（S63 施工图 §3.1 试点，主代理落码 2026-09-24T00:15Z）：
        # 命令入口早已汇进层 2 主缝（根 :7013 `_run_capability_through_pipeline(...,
        # capability_id="bot.music_mode")`），执行体是根内联闭包——它吃运行期
        # `runtime_settings` 与从 event 解析出的 mode ⇒ 只能 prepared（自建=丢注入=第二通路）。
        # 根零改动、净 0 行 ⇒ campus 与全部登记坐标零位移。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/music/capabilities/music.py"
                "#build_music_mode_result"
            ),
            family="command",
            adapter="prepared",
            # roles 用本表缺省 ("user",)——与全部路由行同口径。**故意不写 admin**：
            # 点歌模式的权限真身在 `build_music_mode_result(..., actor_roles=...)` 自己判，
            # 层 2 再叠一道更严的 role 门＝本批凭空收紧现网行为（行为等值优先于猜测）。
            timeout_seconds=30.0,  # 本地设置读写，无网络出口；取保守缺省
            health_probe="",  # 无在册探针映射，诚实留空
            degrade_note="模式非法=诚实拒绝，绝不静默改设置",
            config_keys=(),
        ),
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
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/location/capabilities/wiki.py"
                "#build_wiki_capability"
            ),
            family="command",
            roles=("user",),
            # 无专属超时键（bot_wiki_timeout_seconds 不存在，幽灵键禁入）；真身 requests 级
            # 超时自带，中央缝只兜底。TIMEOUT 态无原始异常交回（错误卡不触发）⇒ 宁大勿小。
            # 60→75：内层串行之和最坏 53s（11 + 6 + 6 跳×6s，含 1s/请求节流，无总时限闸），
            # 原值只剩 7s 余量，一次抖动就被中央掐断（S-TIMEOUT 实算）。
            timeout_seconds=75.0,
            health_probe="",  # 在册探针无一映射维基，诚实留空
            degrade_note="查询失败/超时=温和说明，绝不编词条",
            config_keys=(),
        ),
    ),
    RouteCapabilityDecl(
        kind="MOEGIRL", value="moegirl", capability_id="bot.moegirl", priority=41,
        label="萌娘百科", reason="萌娘百科查询",
        tags=("base_route:moegirl",), command=True, has_rule=True,
        matcher_name="moegirl_match",
        execution=CapabilityExecution(  # 同 id 的 MOEGIRL_QUESTION 行禁再填 execution——
            # _route_execution_rows 按行产出，双行同填=同 id 两描述符，register 当场
            # ValueError 炸装配。adapter/描述符按 id 取，填本行即覆盖两条路由的 dispatch。
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py"
                "#build_moegirl_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=60.0,  # bot_moegirl_timeout_seconds=5.0/请求 × 重试+问句降级链，兜底取宽
            health_probe="",  # 在册探针无一映射萌百，诚实留空
            degrade_note="无条目/网络失败区分说明，绝不硬答",
            config_keys=config_keys_for("bot.moegirl"),
        ),
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
        # prepared 形（P1/B2）：builder 除 config 还要运行期 render_backend（根 :4326
        # `_build_epic_with_backend` 捕获），执行体由装配现场交来，壳不得按 ref 自建。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/subscribe/capabilities/epic.py"
                "#build_epic_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层 fetch_epic_free_games timeout=12.0 单跳（无重试环）；中央这颗只做
            # "别吊死"的安全网，必须高于它，否则内层诚实失败面永不可达（I-4）。
            timeout_seconds=30.0,
            degrade_note="Epic 接口失败/无免费游戏=诚实说明，绝不编一张库存",
            config_keys=("bot_epic_enabled",),
        ),
    ),
    RouteCapabilityDecl(
        kind="WEATHER", value="weather", capability_id="bot.weather", priority=41,
        label="天气查询", reason="天气查询",
        tags=("base_route:weather",), command=True, has_rule=True,
        matcher_name="weather_match",
        # 金丝雀（prepared 形 B0）：weather 的 builder 除 config 还要运行期 render_backend，
        # 属"执行体由装配现场交来"那一族 ⇒ 申报 prepared，壳不得按 ref 自建（自建＝丢注入）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/weather/capabilities/weather.py"
                "#build_weather_capability"
            ),
            family="command",
            adapter="prepared",
            # S-FIX-WX-T6 根修（2026-09-27）：`bot_weather_timeout_seconds`（键值缺省
            # 8.0）现由 builder 装配实传给各外呼腿——NMC 重试、Open-Meteo
            # geocode/forecast、预警支路同吃该值，内层预算自此才有权威；本颗
            # timeout_seconds 只是外层「别吊死」安全网，真实最坏时长＝键值乘
            # 重试/变体链，不在此钉死单一秒数。旧注释宣称命令路径吃这颗键、
            # 还钉了具体秒数——皆假账（键当时根本不被命令链读取），证伪锁：
            # tests/test_wx_t6_timeout_plumbing.py。
            timeout_seconds=45.0,
            degrade_note="无源/超时=诚实播报查不到，绝不编一个城市天气",
            config_keys=("bot_weather_enabled", "bot_weather_cache_seconds", "bot_weather_timeout_seconds"),
        ),
    ),
    RouteCapabilityDecl(
        kind="MARKET", value="market", capability_id="bot.market", priority=41,
        label="全球股指行情", reason="全球股指行情（行情/美股行情/大盘）",
        tags=("base_route:market",), command=True, has_rule=True,
        matcher_name="market_match",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4342）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/market.py"
                "#build_market_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：报价 6s + 走势并行 future.result(timeout=6+2) + 交叉核验 min(6,4)，
            # 空响应重试×2 ⇒ 最坏 ≈36s（bot_market_timeout_seconds 缺省 6.0）；中央取宽 60。
            timeout_seconds=60.0,
            degrade_note="东财/腾讯源失败=已得条目+诚实脚注，绝不编行情",
            config_keys=("bot_market_enabled", "bot_market_timeout_seconds", "bot_market_cache_seconds", "bot_market_retry_on_empty"),
        ),
    ),
    RouteCapabilityDecl(
        kind="STOCKS", value="stocks", capability_id="bot.stocks", priority=42,
        label="个股行情", reason="个股行情（英伟达/AMD/英特尔股价）",
        tags=("base_route:stocks",), command=True, has_rule=True,
        matcher_name="stocks_match",
        note="个股行情（英伟达/AMD/英特尔股价兜底，触发词见 capabilities/stocks.py；帮助页 topic=个股行情）",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4345）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/stocks.py"
                "#build_stocks_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层最坏：报价 6s + 历史三取数点带重试退避 + 9 家 logo 首次下载 local_logo_uri 6s×9=54s + 卡片渲染；
            # 无专属超时键，中央这颗取宽 150，远高于最坏内层，避免截断诚实失败/重试面（I-4 宁大勿小）。
            timeout_seconds=150.0,
            degrade_note="push2his RemoteDisconnected/无历史=温和说明，OpenAI/Anthropic/字节非上市红线不编价格",
            config_keys=("bot_stocks_enabled",),
        ),
    ),
    RouteCapabilityDecl(
        kind="COMMODITIES", value="commodities", capability_id="bot.commodities", priority=37,
        label="商品行情", reason="商品行情（黄金/金价/白银/原油/铜价/大宗商品）",
        tags=("base_route:commodities",), command=True, has_rule=True,
        matcher_name="commodities_match",
        note="商品行情（黄金/白银/原油/铜现货与 30 日走势，触发词见 domains/finance/capabilities/market.py；帮助页 topic=商品行情）",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4351）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/market.py"
                "#build_commodities_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：报价 6s + 4 品种走势并行 future.result(timeout=6+2)，空响应重试×2 ⇒ 最坏 ≈28s；中央取宽 45。
            timeout_seconds=45.0,
            degrade_note="COMEX/NYMEX 源失败=诚实说明，LME/Brent 无源不接不编",
            config_keys=("bot_commodities_enabled", "bot_market_timeout_seconds", "bot_market_retry_on_empty"),
        ),
    ),
    RouteCapabilityDecl(
        kind="BOND", value="bond", capability_id="bot.bond", priority=38,
        label="国债收益率", reason="国债收益率（国债/期限利差/收益率曲线）",
        tags=("base_route:bond",), command=True, has_rule=True,
        matcher_name="bond_match",
        note="国债收益率（国债/期限利差/收益率曲线，触发词见 domains/finance/capabilities/market.py；帮助页 topic=国债收益率）",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4354）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/market.py"
                "#build_bond_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：fetch_bond_yields(timeout_seconds=6) 单跳，空响应重试×2 ⇒ 最坏 ≈12s；中央取宽 30。1Y 无源不接。
            timeout_seconds=30.0,
            degrade_note="中/美债源失败=诚实说明，1Y 无源不接绝不编收益率",
            config_keys=("bot_bond_enabled", "bot_market_timeout_seconds"),
        ),
    ),
    RouteCapabilityDecl(
        kind="NORTHBOUND", value="northbound", capability_id="bot.northbound", priority=39,
        label="北向资金", reason="北向资金（北向资金/沪股通/深股通）",
        tags=("base_route:northbound",), command=True, has_rule=True,
        matcher_name="northbound_match",
        note="北向资金（北向资金/沪股通/深股通成交总额，触发词见 domains/finance/capabilities/market.py；帮助页 topic=北向资金）",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4357）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/market.py"
                "#build_northbound_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：fetch_northbound_flows(timeout_seconds=6) 单跳，重试×2 ⇒ 最坏 ≈12s；中央取宽 30。
            timeout_seconds=30.0,
            degrade_note="源失败=诚实说明，净买入 2024-08 停止披露只报成交总额口径不编数",
            config_keys=("bot_northbound_enabled", "bot_market_timeout_seconds"),
        ),
    ),
    RouteCapabilityDecl(
        kind="FX", value="fx", capability_id="bot.fx", priority=36,
        label="汇率查询", reason="汇率（美元兑人民币/汇率面板）",
        tags=("base_route:fx",), command=True, has_rule=True,
        matcher_name="fx_match",
        note="汇率查询（美元兑人民币/汇率面板，触发词见 capabilities/fx.py；帮助页 topic=汇率）",
        # prepared 形（P1/B1）：builder 除 config 还要运行期 render_backend（根 :4348）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/finance/capabilities/fx.py"
                "#build_fx_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：面板 fetch(timeout=6) + 换算 fetch(attempts 2×6=12，retry_on_empty 时) ⇒ 最坏 ≈18s；中央取宽 40。
            timeout_seconds=40.0,
            degrade_note="源失败=诚实说明，TWD/MOP/AED 东财无源诚实标注不硬换",
            config_keys=("bot_fx_enabled",),
        ),
    ),
    RouteCapabilityDecl(
        kind="NEWS", value="news", capability_id="bot.news", priority=41,
        label="今日快报", reason="今日快报（快报/科技新闻/财经快报/国际新闻）",
        tags=("base_route:news",), command=True, has_rule=True,
        matcher_name="news_match",
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/subscribe/capabilities/news.py"
                "#build_news_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=60.0,  # bot_news_timeout_seconds=6.0/源 × 多源+营销过滤，中央缝兜底取宽
            health_probe="",  # 在册探针无一映射快报各源，诚实留空
            degrade_note="各源失败=已得条目+诚实脚注，绝不冒充全量",
            config_keys=("bot_news_timeout_seconds",),
        ),
    ),
    RouteCapabilityDecl(
        kind="RANDPIC", value="randpic", capability_id="bot.randpic", priority=41,
        label="随机图片", reason="随机图片（随机图/来张图）",
        tags=("base_route:randpic",), command=True, has_rule=True,
        matcher_name="randpic_match",
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/meme/capabilities/randpic.py"
                "#build_randpic_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=30.0,  # 本地盘读，无网络；体积帽走 config，时限兜底即可
            health_probe="",  # 在册探针无一映射随机图目录，诚实留空
            degrade_note="目录空/图坏=一句说明，不重编码不假发",
            config_keys=config_keys_for("bot.randpic"),
        ),
    ),
    RouteCapabilityDecl(
        kind="REMINDER", value="reminder", capability_id="bot.reminder", priority=41,
        label="提醒", reason="提醒（12点提醒我写作业/提醒列表/取消提醒）",
        tags=("base_route:reminder",), command=True, has_rule=True,
        matcher_name="reminder_match",
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/schedule/capabilities/reminder.py"
                "#build_reminder_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=30.0,  # 本地 sqlite；LLM 抽取缺省关，时限兜底即可
            health_probe="",  # 在册探针无一映射提醒库，诚实留空
            degrade_note="时间解析不确定=问不清，绝不猜点位",
            config_keys=config_keys_for("bot.reminder"),
        ),
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
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/assistant/daily/capabilities/daily_assist.py"
                "#build_daily_assist_capability"
            ),
            family="command",
            roles=("user",),
            timeout_seconds=30.0,  # 纯文本文件 IO（收件箱速记），无网络无 LLM，兜底即可
            health_probe="",  # 在册探针无一映射助理目录，诚实留空
            degrade_note="目录不可写=诚实失败，绝不丢用户速记",
            config_keys=config_keys_for("bot.daily_assist"),
        ),
    ),
    RouteCapabilityDecl(
        kind="GROUP_INFO", value="group_info", capability_id="bot.group_info", priority=41,
        label="群信息", reason="群信息（群信息/群主是谁/群人数/群公告/群精华/本群多大了）",
        tags=("base_route:group_info",), command=True, has_rule=True,
        matcher_name="group_info_match",
    ),
    RouteCapabilityDecl(
        kind="HOST_STATE", value="host_state", capability_id="bot.host_state", priority=41,
        label="宿主机状态", reason="宿主机状态（机器状态/机器配置/宿主状态；超管视图卡片）",
        tags=("base_route:host_state",), command=True, has_rule=True,
        matcher_name="host_state_match",
    ),
    RouteCapabilityDecl(
        kind="CONSENT", value="consent", capability_id="bot.consent", priority=41,
        label="书面同意", reason="书面同意（同意卡 待批/看/批/驳；危险参数改动的批准入口，仅管理员）",
        tags=("base_route:consent",), command=True, has_rule=True,
        matcher_name="consent_match",
    ),
    RouteCapabilityDecl(
        kind="EAT", value="eat", capability_id="bot.eat", priority=41,
        label="吃什么推荐", reason="吃什么/菜谱推荐",
        tags=("base_route:eat",), command=True, has_rule=True,
        matcher_name="eat_match",
        # prepared 形（P1/B2）：builder 除 config 还要运行期 render_backend（根 :4332）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/food/capabilities/eat.py"
                "#build_eat_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层最坏：「教我做X」分支调 LLM 受限续写（`_llm_constrained`）走故障转移预算
            # BOT_CHAT_FAILOVER_MAX_SECONDS≈300s，+ 图片抓取 urlopen 6s×2 + Tavily 搜图 + 卡片渲染；
            # 中央这颗必须高于 LLM 诚实降级面，取 360（=failover 300 + 图/渲染余量），否则截断即 I-4。
            timeout_seconds=360.0,
            degrade_note="LLM/图库失败=回落内置菜谱与温和说明，绝不推错菜也不假发图",
            config_keys=("bot_eat_enabled",),
        ),
    ),
    RouteCapabilityDecl(
        kind="AFFINITY", value="affinity", capability_id="bot.affinity", priority=41,
        label="好感度查询", reason="好感度/好感查看/查询好感",
        tags=("base_route:affinity",), command=False, has_rule=True,
        matcher_name="affinity_match",
        # prepared 形（P2/B3）：builder 除 config 还要**两件**运行期注入——装配期现构的
        # affinity_store 与函数局部 render_backend（根 :4338-4343
        # `_build_affinity_with_backend`：`build_affinity_capability(config_,
        # affinity_store=build_character_affinity_store(config_), render_backend=render_backend)`）。
        # 壳按 ref 自建只会得到 `build_affinity_capability(config)` ⇒ store=None ⇒ 真身第一句
        # 就回「好感度功能未开启。」（capabilities/affinity.py:376-383）＝静默把能用的功能
        # 变成永久关闭，比没接中央更坏 ⇒ 申报 prepared，执行体只认装配现场交来的成品。
        # 生产可达：根 :9000 `await _run_simple_capability(bot, event,
        # _build_affinity_with_backend, "bot.affinity", affinity)`。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py"
                "#build_affinity_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层无网络无 LLM：本地 SQLite 读（snapshot/sentiment，毫秒级）+ **一次** playwright
            # 出卡（payload wait_ms=0；页面默认超时 `_SET_CONTENT_TIMEOUT_MS=8000` 罩住
            # set_content(networkidle) 与 screenshot ⇒ 单卡最坏 ≈8+8=16s），且
            # `bot_render_max_concurrency` 缺省 1 ⇒ 前面排队一张卡时头阻塞翻倍 ≈32s。
            # 中央这颗只做"别吊死"的安全网，取 45（=32 最坏 + 余量）：宁大勿小，
            # 到点被硬杀会连内层既有的「渲染失败→纯文本」诚实降级面一起掐掉（I-4）。
            timeout_seconds=45.0,
            degrade_note="好感库未启用/出卡失败=一句温和说明+纯文本，绝不拿默认分冒充档案",
            # 两枚都在 Config.model_fields（幽灵键门）：enabled 决定 store 是否为 None、
            # db_path 决定取哪座好感库（二者均是装配现场 `build_character_affinity_store` 的读点）。
            config_keys=("bot_affinity_enabled", "bot_affinity_db_path"),
        ),
    ),
    RouteCapabilityDecl(
        kind="DIVINATION", value="divination", capability_id="bot.divination", priority=41,
        label="占卜", reason="占卜/塔罗/八字排盘",
        tags=("base_route:divination",), command=True, has_rule=True,
        matcher_name="divination_match",
        # prepared 形（P1/B3）：builder 除 config 还要运行期 render_backend（另有可选
        # draw_store/fortune_key/clock，全部装配现场交来）（根 :4360）⇒ 自建＝丢注入。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/divination/capabilities/divination.py"
                "#build_divination_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：八字/塔罗/金钱卦为纯本地计算（deck_math），无网络无 LLM；卡片渲染在下游 renderer，
            # 不经本能力步。无专属超时键，中央这颗只做"别吊死"的顶，取 30s 远高于计算面。
            timeout_seconds=30.0,
            degrade_note="起卦/排盘异常=诚实说明，绝不硬编一卦冒充",
            config_keys=("bot_divination_enabled", "bot_divination_fortune_secret"),
        ),
    ),
    RouteCapabilityDecl(
        kind="TTS", value="tts", capability_id="bot.tts", priority=41,
        label="语音合成", reason="语音合成（说/语音/念+正文）",
        tags=("base_route:tts",), command=True, has_rule=True,
        matcher_name="tts_match",
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/media/capabilities/tts.py"
                "#build_tts_capability"
            ),
            family="command",
            # 中央时限必须**高于**域内自身预算才只做安全网：真身 `BOT_TTS_TIMEOUT_SECONDS`
            # 缺省 60s 且计时起点更早（含装配与落盘），两值同 60 时内层诚实失败面永不可达
            # ——到点线程继续跑完照旧写出 wav，用户却只拿到温和短句（R-CENTRAL I-4）。
            # 时限的权威在域内（退避真闸/静音陷阱都认它），中央这颗只是"别吊死"的顶。
            timeout_seconds=90.0,
            health_probe="tts_config",
            degrade_note="合成失败/无参考音频=守岸人温和降级，绝不冒充发声",
            # 生效硬顶的唯一家是 domains/media/tts_presets.resolve_*（config 显式值优先，
            # 0/未配⇒内置常量）；此处只声明读哪两把键，**不在描述符里留数值**。
            config_keys=config_keys_for("bot.tts"),
        ),
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
    RouteCapabilityDecl(
        kind="EMERGENCY_INFO", value="emergency_info", capability_id="bot.emergency_info", priority=44,
        label="紧急信息", reason="紧急信息（外部预警与政务应急聚合：紧急信息｜紧急信息 待审）",
        tags=("base_route:emergency_info",), command=True, has_rule=True,
        matcher_name="emergency_info_match",
        # prepared 形（P1/B5）：builder 除 config 还要运行期 render_backend（根 :5414）。
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/emergency_info/capabilities/emergency_info.py"
                "#build_emergency_info_capability"
            ),
            family="command",
            adapter="prepared",
            # 内层：命令面读写本地 sqlite（订阅/查询/待审），采集轮询是独立调度器 job 不经本能力，
            # 无网络无 LLM；中央这颗只做"别吊死"的顶，取 30s 远高于本地读写。
            timeout_seconds=30.0,
            degrade_note="库不可读/无在册条目=诚实说明，权限门与订阅写腿留在域内",
            config_keys=("bot_emergency_info_enabled", "bot_emergency_info_db_path"),
        ),
    ),
    # 兜底席：不注册 RouteRule；capability_id/priority 与 classify_message_route
    # 的两条 IGNORE 兜底 RouteDecision 字面量一致（测试锁定）。
    # S-PREP-B3（2026-09-22）：S-PREP-B2 当年的拦路判据「壳按 `title=decl.label` 派生 ⇒
    # 空标签行撞 validate_registry『bot.ignore: title 缺失』」已由主会话一行修解除
    # （`runtime/capability_protocols.py` 现为 `title=decl.label or decl.value`，并由
    # `tests/test_prepared_adapter_canary.py::test_row_without_human_label_still_derives_a_title`
    # 常驻钉住）。本行不改 label、不动 docs 生成物 ⇒ board_doc_sync 无连带。
    #
    # 证明①（prepared 而非 command）：本能力的执行体在根里是**内层闭包**
    # （`__init__.py:8573` `lambda cfg: lambda message, _decision:
    # build_ignore_guide_result(message.request_id)`），全树没有 `build_ignore_capability(config)`
    # 这样的具名工厂（S-PREP §2 P8 形态：零依赖但缺具名 builder）。命令形要求「壳按
    # implementation_ref 用 config 自建」⇒ 这里根本无从自建：ref 指到的
    # `build_ignore_guide_result(request_id: str, *, guidance: str | None = None)`
    # 首参是**运行期 request_id**（非 config），拿来重建只会造出一句跑不了的话术。
    # ⇒ 执行体只认装配现场交来的成品，adapter 必须是 prepared。
    #
    # 证明②（每一条生产入口都汇到中央缝）：全树唯一的 IGNORE 引导生产入口 =
    # `__init__.py:8568-8578` `_handle_ignore_guide` → `_run_simple_capability(..., "bot.ignore", ...)`，
    # 而 `_run_simple_capability`（:8432-8455）体内 `orchestrated_command(capability_id,
    # capability_factory(config), config)` 就是层 2 主缝。`build_ignore_guide_result` 的
    # 全树调用点只有那一条（+ echo 定义处 + base_router 注释），无第二入口；
    # 规则函数 `_is_ignore_command_guide_event` 按 `RouteKind.IGNORE` 分流、不比较
    # capability_id ⇒ canary 的多入口活性锁不适用也不会被顶红。
    #
    # 证明③（零幽灵配置键）：本能力不读任何 Config 字段（`Config.model_fields` 里
    # 没有 `bot_ignore*` 一枚，实测枚举为 0 命中），故 config_keys 留空 = 如实「无键可读」，
    # 比塞一枚近似键诚实。会话节流 `_ignore_guide_gate = IgnoreGuideGate()`（根 :8554）
    # 无配置参数，且它在 rule 侧、不在能力执行步内。
    #
    # 证明④（超时严格高于内层预算，算术在此）：执行步产出 `kind="text"`，无网络、无 LLM、不出卡，
    # 内层最坏 = `build_ignore_command_guidance()` 走一遍进程内 `_IGNORE_GUIDE_LINES` 取句轮转
    # （纯内存 + 一把游标锁）≈ 0.01s。但 `budget` 罩的不只是执行体本身：壳把 handler 交给
    # **共享** 线程池再 `future.result(timeout=budget)`（capability_protocols.py:422
    # `_MAX_WORKERS=4`、:624-626），排队时间一并计入 ⇒ 同池被 batch1 的 eat（内层带 LLM
    # failover 预算 300s）这类长任务占满时，头阻塞就能吃掉秒级余量。取 30.0
    # = 内层 0.01s + 4 工位排队余量，与 B1 对纯本地件（divination/emergency_info/bond/northbound）
    # 的同款取值一致；仍远低于硬顶 `_MAX_TIMEOUT_SECONDS=600.0`。宁大勿小（I-4）：
    # 到点被硬杀只是把一句引导换成温和降级句，但掐错的代价是用户侧静默感，故不留太紧的顶。
    RouteCapabilityDecl(
        kind="IGNORE", value="ignore", capability_id="bot.ignore", priority=999,
        label="", reason="", tags=(), command=False, has_rule=False,
        execution=CapabilityExecution(
            implementation_ref=(
                "plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py"
                "#build_ignore_guide_result"
            ),
            family="command",
            adapter="prepared",
            timeout_seconds=30.0,
            degrade_note="兜底引导是纯内存话术拼装；拿不到成品就诚实说没交执行体，绝不按 ref 自建一句假引导",
            config_keys=(),
        ),
    ),
)

# 声明序 = base_router.build_interface_manifest 的字面书写序（审计/命令目录
# 按此序渲染，不做物理重排）。
# 指针（Wave 2）：本表=唯一在册表 interface 侧输入源（interface_id 与能力 id 同形者
# 并入同一行），在册答案见 capability_protocols.CAPABILITY_DESCRIPTOR。
INTERFACE_DECLARATIONS: tuple[InterfaceDecl, ...] = (
    InterfaceDecl(
        interface_id="transport.onebot", label="SnowLuma / OneBot V11 传输", status="active",
        route_kind="transport", priority=None,
        description="入站 QQ 消息与出站发送统一走 OneBot V11（SnowLuma），由发送队列收口",
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
        interface_id="capability.host_state", label="宿主机状态", status="active",
        route_kind="host_state", priority=41,
        description="本机运行时事实（版本族/硬件/占用率）经 host_metrics 单一取数口现读，Mica 卡片出图；仅超管视图，读数逐行脱敏",
        help_topic="宿主机状态",
    ),
    InterfaceDecl(
        interface_id="capability.consent", label="书面同意命令面", status="active",
        route_kind="consent", priority=41,
        description="危险参数改动（R1/R2）签出的同意卡在这里批/驳/看：判定唯一住 safety_exec/settings_gate，同意账唯一住 safety_exec/consent，本接口只把一句入站消息交给它",
        help_topic="书面同意",
    ),
    InterfaceDecl(
        interface_id="capability.daily_assist", label="收件箱速记/早晚简报", status="active",
        route_kind="daily_assist", priority=42,
        description="收件箱随手记 + 定时吃什么推荐与早晚简报（BOT_DAILY_ASSIST_*，纯文本文件驱动）",
        help_topic="收件箱",
    ),
    InterfaceDecl(
        interface_id="capability.tts", label="语音合成", status="active",
        route_kind="tts", priority=41,
        description="本机 GPT-SoVITS v2ProPlus HTTP API（api_v2.py 的 /tts）：文本合成守岸人音色语音；参考音频与开关见 BOT_TTS_*",
        help_topic="语音",
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
# 指针（Wave 2）：本表=唯一在册表 help 侧输入源（干净能力 id 行的 help_topics 列由此
# 并入 CAPABILITY_DESCRIPTOR；prose 型能力入口列不并进表，由常驻门①按并集核）。
HELP_TOPIC_DECLARATIONS: tuple[HelpTopicDecl, ...] = (
    HelpTopicDecl(topic="功能管理", admin_only=True, capability="bot.runtime（/bot feature）"),
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
    HelpTopicDecl(topic="宿主机状态", admin_only=True, capability="bot.host_state"),
    HelpTopicDecl(topic="书面同意", admin_only=True, capability="bot.consent"),
    HelpTopicDecl(topic="好感度", admin_only=False, capability="bot.affinity"),
    HelpTopicDecl(topic="Epic", admin_only=False, capability="bot.epic"),
    HelpTopicDecl(topic="随机图", admin_only=False, capability="bot.randpic"),
    HelpTopicDecl(topic="提醒", admin_only=False, capability="bot.reminder"),
    HelpTopicDecl(topic="笔记", admin_only=False, capability="bot.reminder"),
    # 第 20 项「日程记录与智能代答」（2026-09-26）：挂 REMINDER 车道（notes 同型），
    # 能力入口归属字面与 echo._HELP_ENTRY_META['日程']['capability'] 一致。
    HelpTopicDecl(topic="日程", admin_only=False, capability="bot.reminder"),
    HelpTopicDecl(topic="收件箱", admin_only=False, capability="bot.daily_assist"),
    HelpTopicDecl(topic="语音", admin_only=False, capability="bot.tts"),
    HelpTopicDecl(topic="帮助", admin_only=False, capability="bot.help"),
    HelpTopicDecl(topic="聊天", admin_only=False, capability="bot.chat"),
    HelpTopicDecl(topic="戳一戳", admin_only=False, capability="on_notice:戳一戳"),
    HelpTopicDecl(topic="表情收库", admin_only=False, capability="meme_absorb（群图自动收库，无命令）"),
    # S-ALBUM（2026-09-30）表情册面：管理员册账，能力仍走 bot.meme_library（路由席
    # 已把「表情册」并进 is_meme_library_command），故 RouteCapabilityDecl 零改动。
    HelpTopicDecl(topic="表情册", admin_only=True, capability="bot.meme_library"),
    HelpTopicDecl(topic="自然语言", admin_only=False, capability="bot.natural_command"),
    HelpTopicDecl(topic="忽略", admin_only=True, capability="matcher:IGNORE（空消息静默；未知命令形态回引导）"),
    HelpTopicDecl(topic="决策", admin_only=True, capability="/bot decision"),
    HelpTopicDecl(topic="紧急信息", admin_only=True, capability="bot.emergency_info"),
    # 2026-09-24 亲密模式分级波（D 席登记）：位置必须与 echo._HELP_ENTRIES 同序
    # （tests/test_capability_registry.py 逐行 zip 比对，含 topic/admin_only/capability）。
    HelpTopicDecl(
        topic="亲密模式",
        admin_only=False,
        capability="bot.chat（整句「亲密模式 开/深开/关」；关系档子命令见 /bot identity）",
    ),
)

# 入站/管理/通知链里显式使用、尚不属于 RouteKind 主表的能力。
# 只登记稳定 ID；行为接线由 feature_catalog / FeatureGate 消费。
# F3（2026-09-20 统一性波次，审计 U3-01/02）：补登 bot.file / bot.group_welcome /
# bot.cookie_login / bot.cookie_expiry_notice——四个 id 在根 __init__.py 的
# 统一管线出站调用点（含 _send_text/_send_files 两形参缺省值，约 21 处）真实使用；
# 门对未登记 id 一律 fail-closed（有意设计，见 control-plane-registry.md bot.poke
# 补登记先例），漏登即出站文案被「这项功能暂时不可用。」吞掉。
# CAMPUS-FIX-9（2026-09-20）：补登 bot.campus_forward——自 #33 批起该 id 随
# campus SendRequest 真实流经发送队列/审计（capability_id=bot.campus_forward），
# 与 bot.group_digest_push 同族（入站/通知链显式使用、无 RouteKind 主表项）；
# U17-CAMPUS-WIRE 收编走中央管线后 feature_gate 依赖此登记（未登记即整链
# fail-closed，见 docs/design/audit-20260920-unify-U17-campus-wire.md §0.5）。
# 指针（Wave 2）：本表=唯一在册表 gate 侧输入源；gate 绑定改由
# capability_protocols.gate_feature_bindings() 派生，勿在本表之外为同 id 另立登记。
CONTROLLED_INTERNAL_CAPABILITIES: tuple[str, ...] = (
    "bot.alert", "bot.audit", "bot.auto_send.preview", "bot.campus_forward",
    "bot.config", "bot.context",
    "bot.control", "bot.cookie_expiry_notice", "bot.cookie_login",
    "bot.credential_check", "bot.dialogue", "bot.download", "bot.emergency_info_push",
    "bot.file",
    "bot.group_digest_push", "bot.group_policy", "bot.group_welcome",
    "bot.help", "bot.history",
    "bot.identity", "bot.image_search", "bot.llm", "bot.logs", "bot.mail.control",
    "bot.mail.notify", "bot.memory", "bot.parse", "bot.persona", "bot.poke", "bot.queue",
    "bot.quirk", "bot.readiness", "bot.receipt", "bot.recent", "bot.reply",
    "bot.roles", "bot.route", "bot.routes", "bot.runtime", "bot.search",
    "bot.send_queue_worker", "bot.setup.llm", "bot.why",
)


# ===========================================================================
# 管线管理形（pipeline_managed）执行面 —— 第三种形态，2026-09-22 本波新立
#
# 一句话：这几条「层 1 直呼面」在根里走的是裸 `pipeline.handle_async(...)`（自带门禁/
# 审核/渲染/投递，返回 DeliveryReceipt），不是纯能力闭包。把它们登记成管线管理形，
# 让中央 invoker **认得并真能跑**（走 default_invoker().invoke）；但生产根尚未改道
# （根 __init__.py 正被另一波并发修改、本席禁动），所以它们**不进** route 执行形、
# **不被** seam_registered_cids / execution_shape_cids 认成通电——缺口账对它们的现算
# 归位一寸不动（诚实：真接线要等根把那处 handle_async 换成经中央出口）。
# 判据单一真身见类 `PipelineManagedExecution` 与
# docs/design/capability-orchestration-execution-morphology.md（含「禁第二通路」红线）。
# 指针（Wave 2 同哲学）：本表=管线管理形执行面的唯一 authoring 家；勿在别处为同 id 另立。
# ===========================================================================
PIPELINE_MANAGED_CAPABILITY_DECLARATIONS: tuple[PipelineManagedExecution, ...] = (
    PipelineManagedExecution(
        capability_id="bot.chat",
        title="人格对话（主链）",
        implementation_ref=(
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py"
            "#RuntimePipeline.handle_async"
        ),
        timeout_seconds=120.0,
        config_keys=config_keys_for("bot.chat"),
        notes=(
            "层 1 直呼面（root handle_async 主聊天 / 复读短答 / 萌百未命中回落）。"
            "管线管理形在册：invoker 能跑；生产根未改道 ⇒ 缺口账仍按 generic 现算。"
        ),
    ),
    PipelineManagedExecution(
        capability_id="bot.subscribe",
        title="订阅 outbox 推送",
        implementation_ref=(
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py"
            "#RuntimePipeline.handle_async"
        ),
        timeout_seconds=120.0,
        config_keys=config_keys_for("bot.subscribe"),
        notes=(
            "订阅 outbox 推送 job 走裸 handle_async（root 内联投递）。管线管理形在册；"
            "生产根未改道 ⇒ 缺口账仍按 generic 现算。"
        ),
    ),
    PipelineManagedExecution(
        capability_id="bot.campus_forward",
        title="校园自动转发",
        implementation_ref=(
            "plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py"
            "#RuntimePipeline.handle_async"
        ),
        timeout_seconds=60.0,
        config_keys=("bot_campus_enabled",),
        notes=(
            "U17 收编走层 1 管线（回执用于 BLOCK 告警），无 RouteKind 宿主行 ⇒ "
            "结构上无处填 command/prepared execution，正属管线管理形。纯监听红线：绝不向学校群发。"
        ),
    ),
    # ⚠ 运维告警 bot.alert **本波不登记为管线管理形**（两处硬约束叠加）：
    # ① alerts.py 走的是**同步** `pipeline.handle`，不是 `handle_async` ⇒ 不在
    #    「包裹现有的 pipeline.handle_async 调用」这一 adapter 的字面范围内（要接需另立
    #    同步形适配器）。
    # ② 常驻现状锁 `tests/test_orchestration_callsite_wave3_c.py`（本波禁改）把 bot.alert
    #    钉在 `DESCRIPTOR_SHELL_ONLY_IDS`：一旦给它任何编排事实（family/timeout/…）即红。
    #    该锁自述为「要求随迁」信号（先例：bot.divination 于 prepared B1 摘出），但摘它=改
    #    禁改测试，且本席禁动根文件去把直发改经中央出口。⇒ bot.alert 保持现状（在册无执行体），
    #    待能改测试的 owner 随迁后再补登记。详见 logs/WP3-IMPL-handoff.md「受阻项」。
)