"""capability_manifest — 能力「入口形态 ＋ 多维标签 ＋ 触发词指针」的唯一真身（中央调度收编波 P1）。

## 这枚册管什么、不管什么（先划界，防第二真身）
唯一在册表 `CAPABILITY_DESCRIPTOR` 现居 `runtime/capability_protocols.py:2805`，
行内已有 capability_id / title / handler_ref（执行体）/ routes / help_topics / gate_feature_id /
authored_by / fallbacks / timeout / family。**那一行一行就是"在册事实"，本册不复制它——**
**唯一的例外是一枚「镜像指针」**：`CapabilityFacets.implementation_ref` 逐字抄中央的 `handler_ref`
（执行体真身路径＋符号）。它不是第二真身：判"执行体能不能解析"的尺**只有一把**（腿②读中央侧），
本列只是把同一件事在册这一侧留一份可被人读的镜像，并由**常驻锁腿②c**（`test_leg2c_*`）钉死
"册内非空 ⇔ 与中央逐字相等、中央非空而册空须落显式名册"——两处各写一份且允许各写各的，才是第二真身；
锁住等值后它退化为中央的投影，漂移即红。加列动机＝CM-P-14（每次接线都得靠人回头补指针，改不成不回头）。
**目标 1 原句要求执行体"真身路径＋行号"两件套**（S178 补 A2 半落项）：路径走 `implementation_ref`、
行号走 `implementation_line`——后者是对 `implementation_ref` 锚点的 **AST 现算投影**（不是手填），
由常驻锁腿②d（`test_leg2d_*`）每次重定位并两问"声明行==现算行 & 行号处符号名==锚点"，不匹配即红。
ref 格式不动（保持与 handler_ref 逐字相等），行号另立一列，故镜像等值与行号执法互不打脸。

本册补三件**今天在代码里没有家**的维度，外加一枚**镜像指针**（见上，非无家维度）：
  1. `entry_kinds`：这个能力从哪几类入口进来（命令/别名/自然语言/主动投递/语音回执/调度器/控制面/被动匹配）。
     —— 没有这一维，「五入口同缝同权」这句话根本无从执法（P3 的多入口活性锁要读它）。
  2. `tags`：这个能力**消费或产出**哪几类内容形态（vision / native-vision / native-animation /
     native-audio / native-video / tts / image / serves-image / media-read）。
     —— 渠道侧的 `native-*` 标签真身在 `domains/core/channel_capability_tags.py` ＋运行时注册表；
        本册记的是**能力侧需求**，两侧对齐才算"能不能真读这段音频"有唯一答案。
        `serves-image` 是 2026-09-24 用户裁定 **D3=B** 扩出的一枚（词表缺口，不是漏填）：
        它的**取值口径由常驻锁腿㉖ 从执行体真身现算派生**（`tests/test_capability_manifest_gate.py::
        test_leg26_serves_image_tag_is_derived_from_implementation`），不靠人自报。
  3. `trigger_source` / `board`：触发词与板块归属的**指针**（指真身位置，绝不抄一份词表/板块清单进来）。
     `trigger_source` 由常驻锁腿④核"指针可解析到真实符号"；`board` 存一级板块 bid，由常驻锁腿㉔
     双向核"板块码合法 + 板块树（`board_taxonomy.py` 现算）对该能力的归属一致"（S196 补，此前该维空挂）。

**另有两维是「投影 + 等值锁」而非新事实（S130 补，2026-09-24 用户裁定第 6 项与 CM-P-35-R 裁定 A）**：
  4. `direct_callsites`：这枚能力被谁直接调用。事实只由 `scripts/central_seam_census.py` 算一次，
     本列存它的**去行号投影**（行号随宿主文件编辑漂移＝常驻假红源，`#xN` 计数取代且新增站点必变 N），
     由常驻锁腿⑧双向钉死（册少申报／册多申报／现算零处未点名三本账分开红）。
  5. `config_keys`：这枚能力读哪几枚 `Config` 字段。本列**对已合流的声明面已是唯一真身**：
     编排侧描述符（②）与路由/管线管理形执行面（①/①B）不再各写一份键、改经
     `config_keys_for(capability_id)` 读本列（S180 落 ② 的在册枚、S186 落 ①/①B 的在册枚，
     键集合逐枚等值＝搬账不改账）。**尚未合流**的只剩装饰位/未进册面（③`FeatureDescriptor`、
     ⑤`ModalityCapabilitySpec`、⑥`CreationCapabilityEntry`——③/⑥ 全零填充、⑤ 携键未进本册）。
     合流进度的**现算真值不写在本 docstring**：未降为读册的在册手抄枚数以
     `tests/test_config_keys_single_source.py::LITERAL_DEBT_ROSTER` 现算为准、携键未进册枚数以同件
     `NOT_YET_IN_MANIFEST_ROSTER` 现算为准（AGENTS 规则 10：叙述文档禁手写会过期的计数）；
     每一枚键还须真是 `Config.model_fields`（腿⑨b 反幽灵键）。**别把本列读成"六处已全部归一"**——
     ①①B② 三面已归一读本列，③⑤⑥ 仍是各自装饰/未进册的第二形态，合流账以上述两本名册现算为准。

## 五条教义（写进代码，也写进门）
  · **在册必有执行面**：凡 `FACETS` 出现的 id，必须同时能在 `CAPABILITY_DESCRIPTOR` 找到行，
    且该行 `handler_ref` 非空；否则红（禁"在册不执行"——今天有 96 枚三态皆空，见 BASELINE）。
  · **镜像指针不得各写各的**：`implementation_ref` 是中央 `handler_ref` 的镜像，由常驻锁腿②c
    双向钉死——册内非空 ⇔ 逐字相等（不等＝两处各写一份＝红）；中央非空而册空 ⇒ 必须落
    `IMPL_REF_UNDECLARED_ROSTER` 显式名册（只准降、须现算证明是诚实缺位）。
    解析真伪只有一把尺（腿②读中央侧），本列**不重算可解析性**，只比字符串等值。
    **同族判据（S130 起扩到两枚新投影）**：`direct_callsites` 是普查站点的投影（唯一投影尺
    `tests/test_capability_manifest_gate.py::project_direct_callsites`，腿⑧双向钉）、
    `config_keys` 是编排侧描述符键并集的投影（腿⑨双向钉 + 腿⑨b 反幽灵键）。
    三枚共同的铁律＝**事实各只算一次、册只存投影、漂移即红、留空必须点名**
    （零值名册 `DIRECT_CALLSITES_ZERO_ROSTER` / `CONFIG_KEYS_ZERO_ROSTER`）。
  · **标签只能声明有实测票根的值**：`tags` 里每枚 `native-*` 都必须能在独立票根册
    `capability_tag_evidence.TICKETS` 里指到一条**真跑过的**证据（件:用例名 或 复现命令）。
    票根单一真源＝该册，`EVIDENCE` 只留非原生内容档（media.tts.autodub/TTS）——把票根抄进
    `EVIDENCE` ＝第二真身。HTTP 200 不算票根——
    本仓实证：模型回 200 却自陈"没有附带任何视频"；动图只读到首帧。
    **两个方向都成立才算唯一答案**：无票根不得声明（腿⑥）、有票根则须申报（票根门反向腿 +
    `test_manifest_tag_evidence` 逐枚对账）——S178 起 `bot.chat`（统一原生消费者）按三枚实测
    票根升报 native-audio/video/animation。
    推论：**不得用状态码推断能力**，也不得把渠道 tags 当能力 tags 抄。
  · **正交共存**：入口形态、内容档分级（`gate_feature_id`）、主动投递配额、渲染面四者互不压制；
    本册只声明"这个能力会走哪些入口"，权限/配额仍归各自真身。
  · **覆盖面只增不减、未覆盖账只降不升**：`UNCOVERED_CEILING` 是"还没申报的枚数"上限，
    只准降；降必须由现算证据驱动（不许靠把 id 从名册里删掉）。

## 迁移路线（P2 的搬家方向，先声明后动手）
本册是**目的地**。P2 把 `CapabilityRegistration` ＋ `CAPABILITY_DESCRIPTOR` ＋ `DESCRIPTOR_BUILDERS`
从 `capability_protocols.py` 搬进本文件，`capability_protocols.py` 退回机制（invoker/注册表/审计）
＋再导出；搬迁前后由 `scripts/declaration_projection_check.py` 证明**逐字节等值**（搬账不改账）。
在那之前，本册**只读**那张表做交叉核对，绝不另立第二份行集。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final


class EntryKind(str, Enum):
    """能力被触达的入口形态（一个能力可同时占多格）。"""

    COMMAND = "command"                    # /bot 直呼与命令面
    ALIAS = "alias"                        # 别名/昵称动词
    NATURAL_LANGUAGE = "natural_language"  # 自然语序触发
    ACTIVE_PUSH = "active_push"            # 主动投递（提醒/摘要/紧急/助理/回执）
    VOICE_ACK = "voice_ack"                # 语音出站与等待回执
    SCHEDULER = "scheduler"                # 定时/轮询装配期任务
    CONTROL_PLANE = "control_plane"        # 控制面 API 触发
    PASSIVE_MATCHER = "passive_matcher"    # 被动监听（不改写回复）


class CapabilityTag(str, Enum):
    """能力侧的内容形态需求/产出（与渠道侧 native-* 标签对齐后才可声明）。

    `SERVES_IMAGE` 一枚是 2026-09-24 用户裁定 **D3=B** 扩出来的**词表缺口**补枚（不是有人漏填）：
    本枚举此前只覆盖「需模型解码」（`vision`/`native-*`）与「由模型生成」（`image`＝AI 绘画，
    注释逐字限定），而**把库里/平台上已经存在的图像交给会话**这一形态没有格子——`bot.randpic`
    （本机图库原字节直发）与 `bot.subscribe`（订阅条目既有封面图）因此曾被判「无标签可声明」
    并落 `TAGS_ZERO_ROSTER`（S242R 首届核账留痕）。扩枚的两条硬约束写在这里，由常驻锁执法：
      · **不得白贴**：声明它者必须被腿㉖ 从执行体真身现算派生出来（`CapabilityResult` 真带
        `images=` 非空载荷），派生命中而不声明者须落 `SERVES_IMAGE_UNDECLARED_ROSTER` 点名；
      · **不得空扩**：枚枚非 native-* 标签都要有 ≥1 枚在册使用者（腿㉖b）， native-* 的成员资格
        走票根轴（`capability_tag_evidence`），本锁不越界、也不放松它的地板。
    """

    VISION = "vision"                    # 需要看图（任一形态，可走转译）
    NATIVE_VISION = "native-vision"      # 需渠道原生解图
    NATIVE_ANIMATION = "native-animation"  # 需渠道原生解动图（gemini 亦不解 gif ⇒ 默认不声明）
    NATIVE_AUDIO = "native-audio"        # 需渠道原生听音频
    NATIVE_VIDEO = "native-video"        # 需渠道原生看视频
    TTS = "tts"                          # 产出语音
    IMAGE = "image"                      # 产出图像（AI 绘画）
    SERVES_IMAGE = "serves-image"        # 交付**既有**图像（图库/平台已有图，非生成、不要求解码）
    MEDIA_READ = "media-read"            # 读入任意媒体段（链接/附件解析面）


@dataclass(frozen=True)
class TagEvidence:
    """一枚票根：说清「哪件哪用例」或「哪条可复跑命令」证成了某个声明。"""

    capability_id: str
    tag: CapabilityTag
    evidence: str  # 件:用例名 / 复现命令；不得填"文档说支持""返回 200"


@dataclass(frozen=True)
class CapabilityArm:
    """一枚「臂」＝某能力经由某个**入口臂形**抵达中央调度缝的一条执行边（收编波第 1/2 项交界，S187）。

    **臂 ≠ 路由优先级、≠ 内容档分级、≠ 主动投递配额、≠ 渲染面**（目标 1 的正交性，逐条划界）：
      · 臂说的是"这个能力从哪一类入口进来、进来后交进哪一枚中央汇缝"，是**执行形态**，
        与优先级数字无关（优先级住在 `base_router` 的 RouteRule priority，臂不复制它）；
      · 与内容档分级正交：分级走 `gate_feature_id`（唯一在册表），臂不判"能不能露骨"；
      · 与主动投递配额正交：配额走 `outbound_gate`，臂只说"这能力有主动投递这一形"，不数它能投几条；
      · 与渲染面正交：渲不渲染、渲成什么走 renderer / `render_card`，臂不管卡片。
      四者各归各真身，臂只声明"入口形态 ↔ 中央汇缝"这一层，与 `entry_kinds`（抽象形态名）互补：
      `entry_kinds` 是自由声明、**没有**外部活性校验；臂是"被入口活性件真走过的形态"，
      每枚臂的 `seam_host` 必须等于该形经由的中央汇缝，且这一等式由常驻锁腿㉓双向钉到
      `tests/test_three_entry_form_seam_liveness.py` 与 `tests/test_five_entry_seam_lock.py`。

    字段（照 SEAT-S141 的类型设计，字段名与本席现算形态一致）：
      · `arm_id`    —— 身份 `"<capability_id>:<entry_key>"`（一能力一形一枚，供集合等值双向对账）。
      · `entry_key` —— 臂形＝`EntryKind` 的 value（"command"/"alias"/…），必须 ∈ 本能力的 `entry_kinds`。
      · `seam_host` —— 该形经由的**中央汇缝符号**（形级规范值，由本册 `ARM_FORM_SEAMS` 单源投影，
        不是该能力逐调用点的实测路径——某能力的实际投递可能经该形规范汇缝或其封装变体
        （例：`bot.chat` 的命令形实际经 `_send_parts_through_unified_pipeline` 变体），
        **本维只锁「形 ↔ 中央汇缝」这一层，不锁具体调用点**；具体调用点是腿⑧ `direct_callsites` 的账。
      · `executor`  —— 「K-合成子边」的执行体真身 `<file>#<fn>`（**去行号**，同 `implementation_ref`
        的投影口径）。**缺省空串＝本臂不是合成子边**（普通入口形臂一律留空：`bot.chat` 的 command 臂
        只是"命令形经某缝"，其下没有一条被并的独立调用边）。非空只在 `bot.debug` 这类把多条真实调用边
        合成一枚在册能力时才出现，一子边一臂，各指自己的 builder（例
        `plugins/bot_unified_runtime/domains/ops/admin/debug.py#build_receipt_query_result`）。
        这一列由常驻锁**腿⑩**（`test_capability_manifest_gate.py::test_leg10_*`）双向钉到真身：
        ① 每枚非空 executor 必须 `_resolve_symbol` 解析得到真符号（可归因，关③）；
        ② 合成能力的臂集必须等于「该 executor 文件里正文写有 `capability_id==<本能力 id>` 的函数集」
        （missing/stale 两本账分开红）；③ 合成能力必须被普查看见且态非 none（真被执行，关①）。
        **⚠ 顺序锁死**：`bot.debug` 的 FACETS 行 + executor 列填值须与「debug.py 各 builder 改指
        `capability_id="bot.debug"`」**同批**——只提册不改 debug.py ⇒ 腿⑩按 missing/stale 红；
        只改 debug.py 不提册 ⇒ 该枚仍不在 FACETS、腿⑩无宿主可扫、保持真空绿（不误报也不误放）。
        S141 交付四当年只出字段设计不落码（册内零合成行、造 executor＝预填达标值）；S212 按用户已裁
        K-合成把**列**落下（加列不加行、既有 20 行 arm 一律 executor="")，**值**随 root/debug.py/CIC/
        descriptor/FACETS 五面同批由 owner 落（见 SEAT-S212 §3 补丁文本）。
    """

    arm_id: str
    entry_key: str
    seam_host: str
    executor: str = ""
    """K-合成子边的执行体真身 `路径#符号`（去行号）；空串＝非合成臂（普通入口形臂的缺省，占绝大多数）。
    判"是否合成臂"只看本列非空——不另立合成标志位，防"标志与数据各写一份"的第二真身。"""


@dataclass(frozen=True)
class CapabilityFacets:
    """一个能力在本册里的行（与 CAPABILITY_DESCRIPTOR 的行一一对应，不复制其行集）。"""

    capability_id: str
    entry_kinds: tuple[EntryKind, ...]
    tags: tuple[CapabilityTag, ...] = ()
    trigger_source: str = ""  # 真身指针（例：domains/chat_reply/capabilities/echo.py#_HELP_ENTRIES）
    board: str = ""           # 一级板块 bid（例：B06，以 domains/core/board_taxonomy.py 现算为准；
                              # 常驻锁腿㉔双向核：合法板块码 + 板块树对该能力的归属一致；S196 补执法）
    implementation_ref: str = ""  # 执行体真身指针（中央 handler_ref 的镜像，逐字相等由常驻锁腿②c 执法）
    implementation_line: int = 0
    """执行体真身的**行号**（S178 补，闭合目标 1 原句「真身路径＋行号」，CM 六维 A2 的半落项）。

    与 `implementation_ref`（`路径#符号`）配成"真身路径＋行号"这一整维：路径走 ref、行号走本列。
    `implementation_ref` 格式**不改**（保持与中央 `handler_ref` 逐字相等、腿②c 只比字符串），
    行号另立一列，避免把行号塞进 ref 打断镜像等值。

    值是**现算派生**的投影、不是手填达标值：锚点＝`ref` 的 `#符号` 首段（与真身唯一尺
    `_resolve_symbol` 同一口径），行号＝实现件里该符号定义所在行。常驻锁腿②d
    （`test_leg2d_execution_body_line_matches_ast`）每次跑都重新 AST 定位并两问：
    ①声明行 == 现算行？②行号处符号名 == 锚点？任一不符即红——这正是"防漂移假绿"：
    旧腿②只判"符号名在文件里存在"，符号被搬走也照样绿；补了行号后，实现件被编辑到符号漂移
    而册没回头 ⇒ 当场红，逼"一处变更处处跟随"。行号随实现件编辑漂移是**本维的代价、也是本维的目的**
    （把漂移变可见而非静默）；实现件均是各能力自家文件（非根 `__init__.py`），漂移面比直呼点小得多。
    0 ＝「本行无 implementation_ref（执行体缺位）⇒ 无行号可锚」的显式判定，须与
    `IMPL_REF_UNDECLARED_ROSTER`（在册却选择漏镜像）或占位名册同批点名；有 ref 的行不得留 0。
    """
    direct_callsites: tuple[str, ...] = ()
    """「谁直接调用这枚能力」的**投影**（S130 补，CM-P-35-R 裁定 A／目标 1 缺口）。

    形状＝`<桶>:<文件>#<宿主>[<子形>][-><符号>]#x<站点数>`，桶 ∈ {seam, invoke, generic, offseam}，
    由**唯一投影尺** `tests/test_capability_manifest_gate.py::project_direct_callsites`
    从 `scripts/central_seam_census.py`（S01 尺，腿③/③b 共用同一份产物）的 roster 行派生。
    它是投影不是第二真身：站点事实只由普查件算一次，本列抄它的**去行号**形态，
    漂移由常驻锁腿⑧双向钉死（少申报／多申报两方向各红、现算零处须落名册点名）。
    去行号的理由写死在这儿：行号随任何人对宿主文件的编辑漂移（AGENTS 台账 #50 两记 campus
    坐标顶漂即此病），留行号只会制造常驻假红；`#xN` 计数替代它，**新增一处直呼必变 N** ⇒ 咬得住。
    空 tuple ＝「现算零处直呼点」这一** affirmative 判定**，必须同时落
    `DIRECT_CALLSITES_ZERO_ROSTER` 点名（禁把"没填"读成"没有"）。
    """
    config_keys: tuple[str, ...] = ()
    """这枚能力读哪几枚 `Config` 字段（S130 起手，用户 2026-09-24 裁定第 6 项「B 起手 → A 收口」）。

    本列逐枚**手填**，是配置键的**唯一真身**：编排侧描述符（②）与路由/管线管理形执行面
    （①/①B）不再各写一份键、改经 `config_keys_for(capability_id)` 读本列
    （S180 落 ② 的在册枚、S186 落 ①/①B 的在册枚，改前改后键集合逐枚等值＝搬账不改账）。
    读点与本列的等值由常驻锁腿⑨双向钉死；每一枚还必须真是 `Config.model_fields` 里的字段
    （腿⑨b 反幽灵键）。

    ⚠ **未合流的还剩哪些，一律看名册现算、不写在本 docstring**（AGENTS 规则 10）：
    未降为读册的在册手抄枚数＝`tests/test_config_keys_single_source.py::LITERAL_DEBT_ROSTER` 现算；
    携键但尚未进本册的 id（如装饰位 ③`FeatureDescriptor`/⑥`CreationCapabilityEntry`、
    携键未进册的 ⑤`ModalityCapabilitySpec`）＝同件 `NOT_YET_IN_MANIFEST_ROSTER` 现算。
    旧叙述「六处跨五文件各写一遍、本列今天仍是镜像」已随 ①①B② 收编过期：那三面读本列，
    别把本列读成"六处已全部归一"——③⑤⑥ 仍是第二形态，合流进度只认上面两本名册。
    空 tuple ＝「该能力不读任何 Config 字段」的显式判定，须落 `CONFIG_KEYS_ZERO_ROSTER` 点名。
    """
    arms: tuple[CapabilityArm, ...] = ()
    """这枚能力声明它支持哪些**臂**（收编波第 1/2 项交界，S187 落，SEAT-S141 类型设计）。

    一臂＝「一个入口臂形 ＋ 该形经由的中央汇缝」（见 `CapabilityArm` 的逐条划界：臂≠优先级／≠分级／
    ≠配额／≠渲染面）。值＝本能力 `entry_kinds` 里**被入口活性件真走过**的那几形，各携其形级规范汇缝：
    `command→_run_simple_capability`、`alias/natural_language→_run_capability_through_pipeline`
    （`tests/test_three_entry_form_seam_liveness.py` 派生）、`active_push/voice_ack→submit_active_push`
    （`tests/test_five_entry_seam_lock.py` 派生）。三形/两形之外的 `entry_kinds`（scheduler /
    control_plane / passive_matcher）**没有**中央汇缝活性件走过 ⇒ 不生成臂（诚实留空，非漏填）。

    与 `entry_kinds` 的分工（防第二真身）：`entry_kinds` 是**抽象形态名**的自由声明、无外部校验；
    `arms` 是"哪些形态真经中央调度"的**投影**，其形集与形↔缝由常驻锁腿㉓**双向**钉到那两件活性件
    （在册臂形无执法点＝红；活性件长出册外臂形＝红；某能力有活入口形却不声明该臂＝红；
    臂的 `seam_host` 漂离活性件派生的缝＝红）。缝字符串只单源住 `ARM_FORM_SEAMS`（本文件），
    逐臂的 `seam_host` 由它投影，不各写各的。
    """


def _f(
    capability_id: str,
    *entry_kinds: EntryKind,
    tags: tuple[CapabilityTag, ...] = (),
    trigger_source: str = "",
    board: str = "",
    implementation_ref: str = "",
    implementation_line: int = 0,
    direct_callsites: tuple[str, ...] = (),
    config_keys: tuple[str, ...] = (),
    arms: tuple[CapabilityArm, ...] = (),
) -> CapabilityFacets:
    return CapabilityFacets(
        capability_id=capability_id,
        entry_kinds=tuple(entry_kinds),
        tags=tags,
        trigger_source=trigger_source,
        board=board,
        implementation_ref=implementation_ref,
        implementation_line=implementation_line,
        direct_callsites=direct_callsites,
        config_keys=config_keys,
        arms=arms,
    )


_EK = EntryKind
_TG = CapabilityTag

#: 「臂形 ↔ 中央汇缝」的单源投影表（S187 立）——本册声明的**形集**，与入口活性件双向对账（腿㉓）。
#: 事实真身在那两件活性件里各派生一份：三形来自 `test_three_entry_form_seam_liveness.py`
#: （`SIMPLE_SEAM`/`PIPELINE_SEAM` 两枚汇缝＋dispatch_table 的形字面量），主动投递/语音回执两形来自
#: `test_five_entry_seam_lock.py`（`_CENTRAL_TERMINALS` 含 `submit_active_push` ＋主动投递/回执两套执法）。
#: 本表**不是**第二真身：逐臂 `seam_host` 由它投影（不各写各的），形↔缝的等值由腿㉓双向钉到活性件
#: （在册臂形无执法点＝红；活性件长出本表没有的臂形＝红；本表写了活性件不走的形/缝＝红）。
#: scheduler / control_plane / passive_matcher 三形**不进本表**——它们没有中央汇缝的入口活性件走过，
#: 于是任何能力都不会为它们生成臂（诚实留空，与"漏填"用零值名册区分无关：形不在表里就不该有臂）。
ARM_FORM_SEAMS: MappingProxyType[str, str] = MappingProxyType(
    {
        EntryKind.COMMAND.value: "_run_simple_capability",
        EntryKind.ALIAS.value: "_run_capability_through_pipeline",
        EntryKind.NATURAL_LANGUAGE.value: "_run_capability_through_pipeline",
        EntryKind.ACTIVE_PUSH.value: "submit_active_push",
        EntryKind.VOICE_ACK.value: "submit_active_push",
    }
)


def _arms(capability_id: str, *entry_kinds: EntryKind) -> tuple[CapabilityArm, ...]:
    """按 `ARM_FORM_SEAMS` 单源，为某能力的若干入口形生成臂（缝/身份都投影、不手抄）。

    只认 `ARM_FORM_SEAMS` 里的形（＝被入口活性件走过的那几形）；传进来的形若不在表里
    （scheduler/control_plane/passive_matcher）一律不生成臂——腿㉓的逐能力一致性会抓到"少声明臂"，
    所以这里**不能**悄悄吞掉一个本该成臂的形：本函数与表同源、与逐能力判据同尺。
    """
    return tuple(
        CapabilityArm(
            arm_id=f"{capability_id}:{ek.value}",
            entry_key=ek.value,
            seam_host=ARM_FORM_SEAMS[ek.value],
        )
        for ek in entry_kinds
        if ek.value in ARM_FORM_SEAMS
    )

# 首批申报面：只填**今天已有真身与票根**的行；未申报者进"未覆盖账"（UNCOVERED_CEILING 执法）。
# 每行落笔前都须现算核对 CAPABILITY_DESCRIPTOR 有该 id、handler_ref 非空——由常驻门逐次复检。
FACETS: MappingProxyType[str, CapabilityFacets] = MappingProxyType(
    {
        row.capability_id: row
        for row in (
            _f(
                "bot.chat",
                _EK.COMMAND,
                _EK.ALIAS,
                _EK.NATURAL_LANGUAGE,
                # bot.chat 是统一原生消费者（cte.NATIVE_CONSUMER_CAPABILITY）：native-* 三枚均按
                # capability_tag_evidence.TICKETS 里 2026-09-23 实测票根申报（腿⑥指 cte.TICKETS，
                # 票根门双向对账；HTTP 200 不算票根）。非原生 media-read 保留。
                tags=(_TG.MEDIA_READ, _TG.NATIVE_AUDIO, _TG.NATIVE_VIDEO, _TG.NATIVE_ANIMATION),
                trigger_source="domains/chat_reply/capabilities/echo.py#_HELP_ENTRIES",
                board="B03",  # 现算自 board_taxonomy：①B03.chat-reply capability_ids 点名 bot.chat
                implementation_ref="plugins/bot_unified_runtime/domains/chat_reply/runtime"
                                   "/pipeline.py#RuntimePipeline.handle_async",
                implementation_line=535,  # 现算 AST：pipeline.py 里 `class RuntimePipeline`
                # 现算 2026-09-24T06:35:06Z，尺＝门件 project_direct_callsites × central_seam_census
                direct_callsites=(
                    "generic:plugins/bot_unified_runtime/__init__.py#handle_async#x3",
                    ("seam:plugins/bot_unified_runtime/__init__.py"
                     "#_send_parts_through_unified_pipeline#x1"),
                ),
                config_keys=("bot_chat_enabled",),
                # 三形都经中央调度（command/alias/natural 各有入口活性件走过）；臂缝＝形级规范值，
                # 注意 bot.chat 的**命令形实际**投递经 `_send_parts_through_unified_pipeline` 变体
                # （见 direct_callsites），本臂记的是"命令形经由的规范中央汇缝"，非逐调用点。
                arms=_arms("bot.chat", _EK.COMMAND, _EK.ALIAS, _EK.NATURAL_LANGUAGE),
            ),
            _f(
                "bot.tts",
                _EK.COMMAND,
                _EK.ALIAS,
                tags=(_TG.TTS,),
                trigger_source="plugins/bot_unified_runtime/domains/media/capabilities/tts.py"
                               "#DEFAULT_TRIGGER_WORDS",
                board="B06",  # 现算自 board_taxonomy：①B06.tts capability_ids 点名 + ②impl=tts.py 同目录，二者一致
                implementation_ref="plugins/bot_unified_runtime/domains/media/capabilities/tts.py"
                                   "#build_tts_capability",
                implementation_line=1070,  # 现算 AST：tts.py 里 `def build_tts_capability`
                direct_callsites=(
                    "seam:plugins/bot_unified_runtime/__init__.py#_run_simple_capability#x1",
                ),
                config_keys=("bot_tts_hard_max_chars", "bot_tts_max_audio_bytes"),
                arms=_arms("bot.tts", _EK.COMMAND, _EK.ALIAS),
            ),
            _f(
                "media.tts.autodub",
                _EK.ACTIVE_PUSH,
                tags=(_TG.TTS,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/capabilities/tts.py 落在 B06.tts impl_paths
                implementation_ref="plugins/bot_unified_runtime/domains/media/capabilities"
                                   "/tts.py#synthesize_autodub",
                implementation_line=1513,  # 现算 AST：tts.py 里 `def synthesize_autodub`
                direct_callsites=(
                    # S270 归位：产出步唯一 invoke 从 voice_enricher 移到单一组合口
                    # result_transform.dub_via_central（直呼面清零，见 wave 门 KNOWN_INVOKER_SITES_MEDIA）。
                    ("invoke:plugins/bot_unified_runtime/domains/media/tts"
                     "/result_transform.py#invoke#x1"),
                ),
                config_keys=(
                    "bot_tts_api_url", "bot_tts_enabled", "bot_tts_hard_max_chars",
                    "bot_tts_max_audio_bytes", "bot_tts_ref_audios", "bot_tts_timeout_seconds",
                ),
                arms=_arms("media.tts.autodub", _EK.ACTIVE_PUSH),
            ),
            # S91 自动配音第二条腿（内联变换退役为中央第三形）：entry_kinds 与同腿的
            # `media.tts.autodub` **故意不同格**——那枚由作者登记成 ACTIVE_PUSH，而本枚不自己
            # 投任何一条消息，它只把「已审核的呈现结果」换成「带音频的呈现结果」，属语音出站面，
            # 故取 VOICE_ACK。这不是漂移，是两枚各自如实登记；改任一侧前先读 SEAT-S91 §1/§6。
            _f(
                "media.tts.autodub_transform",
                _EK.VOICE_ACK,
                tags=(_TG.TTS,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/tts/result_transform.py 落在 B06.vision impl_paths(…/domains/media)
                implementation_ref="plugins/bot_unified_runtime/domains/media/tts"
                                   "/result_transform.py#handle",
                # 308→377：S270 把产出步单一组合口 dub_via_central + envelope_failure_reason 落进
                # 本件并加长头 docstring，符号 `handle` 随之下移（改行为也改行数，同批刷册）。
                implementation_line=377,  # 现算 AST：result_transform.py 里符号 `handle`
                direct_callsites=(
                    ("invoke:plugins/bot_unified_runtime/domains/media/voice_enricher.py"
                     "#invoke#x1"),
                ),
                config_keys=(
                    "bot_tts_auto_reply_max_chars", "bot_tts_auto_reply_split_max_chars",
                    "bot_tts_hard_max_chars", "bot_tts_voice_hook_enabled",
                ),
                arms=_arms("media.tts.autodub_transform", _EK.VOICE_ACK),
            ),
            _f(
                "media.asr.speech",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.MEDIA_READ,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/transcribe.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/transcribe.py#transcribe_audio",
                implementation_line=472,  # 现算 AST：transcribe.py 里 `def transcribe_audio`
                # 零处直呼点：在册有执行体、却不经中央调用链（普查 state=none，腿③b 那本账）。
                # 显式判「无」由 DIRECT_CALLSITES_ZERO_ROSTER 点名，不是留空。
                direct_callsites=(),
                config_keys=(
                    "bot_asr_enabled", "bot_asr_model_registry", "bot_asr_timeout_seconds",
                ),
            ),
            _f(
                "media.asr.audio_file",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.MEDIA_READ,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/transcribe.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/transcribe.py#transcribe_audio",
                implementation_line=472,  # 现算 AST：transcribe.py 里 `def transcribe_audio`
                direct_callsites=(),  # 同上：零处直呼点，已入零值名册点名
                config_keys=("bot_asr_enabled", "bot_asr_model_registry"),
            ),
            _f(
                "media.vision.image",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.VISION, _TG.MEDIA_READ),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/vision_describe.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/vision_describe.py#describe_images",
                implementation_line=793,  # 现算 AST：vision_describe.py 里 `def describe_images`
                direct_callsites=(),  # 零处直呼点（已入零值名册点名）
                config_keys=(
                    "bot_vision_enabled", "bot_vision_model_registry", "bot_vision_timeout_seconds",
                ),
            ),
            _f(
                "media.vision.anime_ip",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.VISION,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/search/sauce_search.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/search"
                                   "/sauce_search.py#search_saucenao_ex",
                implementation_line=32,  # 现算 AST：sauce_search.py 里 `def search_saucenao_ex`
                direct_callsites=(
                    ("invoke:plugins/bot_unified_runtime/domains/media/capabilities"
                     "/image_search.py#invoke#x1"),
                ),
                config_keys=("bot_saucenao_api_key",),
            ),
            _f(
                "media.vision.ocr",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.VISION,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/vision_describe.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/vision_describe.py#describe_images",
                implementation_line=793,  # 现算 AST：vision_describe.py 里 `def describe_images`
                direct_callsites=(),  # 零处直呼点（已入零值名册点名）
                config_keys=("bot_vision_enabled", "bot_vision_model_registry"),
            ),
            _f(
                "media.video.recognize",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.VISION,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/video_understanding.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/video_understanding.py#build_video_brief",
                implementation_line=271,  # 现算 AST：video_understanding.py 里 `def build_video_brief`
                direct_callsites=(),  # 零处直呼点（已入零值名册点名）
                config_keys=(
                    "bot_video_asr_max_seconds", "bot_video_max_frames",
                    "bot_video_understanding_enabled",
                ),
            ),
            _f(
                "media.video.subtitle",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.MEDIA_READ,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/video_understanding.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/video_understanding.py#build_video_brief",
                implementation_line=271,  # 现算 AST：video_understanding.py 里 `def build_video_brief`
                direct_callsites=(),  # 零处直呼点（已入零值名册点名）
                config_keys=("bot_video_skip_asr_with_subtitle",),
            ),
            _f(
                "media.video.frame_extract",
                _EK.PASSIVE_MATCHER,
                tags=(_TG.MEDIA_READ,),
                board="B06",  # 现算自 board_taxonomy：②impl=media/ingest/vision_describe.py 落在 B06 目录
                implementation_ref="plugins/bot_unified_runtime/domains/media/ingest"
                                   "/vision_describe.py#_extract_video_frames",
                implementation_line=567,  # 现算 AST：vision_describe.py 里 `def _extract_video_frames`
                direct_callsites=(),  # 零处直呼点（已入零值名册点名）
                config_keys=("bot_video_max_frames", "bot_vision_video_frames"),
            ),
            # 绘画：中央 handler 已挂上 engine_provider.py#handle（执行体真身可解析＝腿②读中央侧），
            # 但 provider 工厂仍缺位 ⇒ 真调诚实 UNAVAILABLE（缺位可见由诊断卡/status/巡检告警三处
            # 执法，见 PARKED CM-P-4）；本列只镜像"执行体是谁"，不宣称"绘画是一条能跑的路"。
            _f(
                "creation.image.generate",
                _EK.CONTROL_PLANE,
                tags=(_TG.IMAGE,),
                board="B06",  # 现算自 board_taxonomy：②impl=creation/image/engine_provider.py 落在 B06.creation impl_paths(…/domains/creation)
                implementation_ref="plugins/bot_unified_runtime/domains/creation/image"
                                   "/engine_provider.py#handle",
                implementation_line=359,  # 现算 AST：image/engine_provider.py 里符号 `handle`
                # 两枚 creation 描述符按简报要求逐枚表态：**有值就写值，没有就显式判「无」并说明**。
                # 2026-09-25 跟随（S262 A 案）：控制面门面件 `domains/creation/image/routes.py` 落了
                # 一发**字面量** `default_invoker().invoke(capability_id="creation.image.generate")`，
                # 故本枚直呼点由零处变一处、同时从 `DIRECT_CALLSITES_ZERO_ROSTER` 摘牌（接真一枚摘一枚）。
                # ⚠ 这仍然**不等于"绘画能出图"**：provider 工厂缺位 ⇒ 真调诚实回 UNAVAILABLE／HTTP 503，
                #   且控制面缺省关 ⇒ 账面通电、现网零流量（见 descriptor 账本同枚的 caveat）。
                direct_callsites=(
                    "invoke:plugins/bot_unified_runtime/domains/creation/image/routes.py#invoke#x1",
                ),
                config_keys=("bot_creation_image_provider",),
            ),
            _f(
                "creation.tts.synthesize",
                _EK.CONTROL_PLANE,
                tags=(_TG.TTS,),
                board="B06",  # 现算自 board_taxonomy：②impl=creation/tts/engine_provider.py 落在 B06.tts impl_paths(…/domains/creation/tts)
                implementation_ref="plugins/bot_unified_runtime/domains/creation/tts"
                                   "/engine_provider.py#handle",
                implementation_line=254,  # 现算 AST：tts/engine_provider.py 里符号 `handle`（S270 改产出步归位，handle 前增行随之下移）
                # 与上枚同规表态：语音这枚**有**直呼点（控制面 API 经中央 `invoke` 直呼），
                # 不是零处；键六枚＝该能力真读的 TTS 面 + 自身的 provider 选择键。
                direct_callsites=(
                    "invoke:plugins/bot_unified_runtime/domains/creation/tts/routes.py#invoke#x1",
                ),
                config_keys=(
                    "bot_creation_tts_provider", "bot_tts_api_url", "bot_tts_enabled",
                    "bot_tts_hard_max_chars", "bot_tts_max_audio_bytes", "bot_tts_ref_audios",
                ),
            ),
            # S67 扩册批①（现算 2026-09-24T00:27:25Z，尺＝`scripts/facets_candidate_dump.py`
            # 复用 G-CM 门 `_resolve_symbol`＋普查件；六枚全部满足「在册 ∩ handler_ref 可解析
            # ∩ 普查可见且 state==wired ∩ 无 offseam 直呼」＝「申报一枚不顶高腿③b unwired
            # 账」的诚实可补集。entry_kinds 逐枚只填候选表里 verdict==candidate 且带证据的那几格；
            # command/alias/natural_language 者 trigger_source 给可解析指针（不抄词表，腿④）；
            # 一律不申报 native-*（无渠道侧真实例票根，腿⑥）。字段从真码读、不预填达标值。
            _f(
                "bot.daily_assist",
                _EK.COMMAND,
                _EK.NATURAL_LANGUAGE,
                _EK.SCHEDULER,
                trigger_source="plugins/bot_unified_runtime/domains/assistant/daily"
                               "/capabilities/daily_assist.py#is_daily_assist_command",
                board="B07",  # 现算自 board_taxonomy：①B07.daily-assist capability_ids 点名 + ②impl 同目录，二者一致
                implementation_ref="plugins/bot_unified_runtime/domains/assistant/daily"
                                   "/capabilities/daily_assist.py#build_daily_assist_capability",
                implementation_line=72,  # 现算 AST：daily_assist.py 里 `def build_daily_assist_capability`
                direct_callsites=(
                    "seam:plugins/bot_unified_runtime/__init__.py#_run_simple_capability#x1",
                ),
                config_keys=("bot_daily_assist_dir", "bot_daily_assist_enabled"),
                arms=_arms("bot.daily_assist", _EK.COMMAND, _EK.NATURAL_LANGUAGE),
            ),
            _f(
                "bot.moegirl",
                _EK.COMMAND,
                trigger_source="plugins/bot_unified_runtime/domains/location"
                               "/capabilities/moegirl.py#is_entity_question",
                board="B05",  # 现算自 board_taxonomy：①B05.reference-wiki capability_ids 点名 + ②impl 同目录，二者一致
                implementation_ref="plugins/bot_unified_runtime/domains/location"
                                   "/capabilities/moegirl.py#build_moegirl_capability",
                implementation_line=381,  # 现算 AST：moegirl.py 里 `def build_moegirl_capability`
                # `#x2` ＝同一个汇缝宿主里有两处把本枚交上去（MOEGIRL 与 MOEGIRL_QUESTION 两条
                # RouteKind 的判定分支），不是"两条通路"；第二条路的判据仍是腿③（offseam 必须零）。
                direct_callsites=(
                    ("seam:plugins/bot_unified_runtime/__init__.py"
                     "#_run_capability_through_pipeline#x2"),
                    "seam:plugins/bot_unified_runtime/__init__.py#_run_simple_capability#x1",
                ),
                config_keys=("bot_moegirl_timeout_seconds",),
                arms=_arms("bot.moegirl", _EK.COMMAND),
            ),
            _f(
                "bot.randpic",
                _EK.COMMAND,
                _EK.ALIAS,
                _EK.NATURAL_LANGUAGE,
                # D3=B 扩枚（词表缺口补挂，非"终于想起来了"）：取值口径＝执行体真身在结果契约里
                # 交付**既有图像**——`randpic.py` 的 capability 闭包返回
                # `images=[{"file": str(picked)}]`，picked 来自 `list_gallery_images(bot_randpic_dirs)`
                # 按 `_IMAGE_EXTENSIONS` 扫出的本机图片，原字节直发（不生成、不重编码、不给模型解码）。
                # 这一格不是手填达标值：常驻锁腿㉖ 每次跑都从真身 AST 重算，派生不出图像载荷就红。
                tags=(_TG.SERVES_IMAGE,),
                trigger_source="plugins/bot_unified_runtime/domains/meme"
                               "/capabilities/randpic.py#DEFAULT_TRIGGER_WORDS",
                board="B06",  # 现算自 board_taxonomy：①B06.meme capability_ids 点名 + ②impl 同目录，二者一致
                implementation_ref="plugins/bot_unified_runtime/domains/meme"
                                   "/capabilities/randpic.py#build_randpic_capability",
                implementation_line=130,  # 现算 AST：randpic.py 里 `def build_randpic_capability`
                direct_callsites=(
                    "seam:plugins/bot_unified_runtime/__init__.py#_run_simple_capability#x1",
                ),
                config_keys=("bot_randpic_dirs", "bot_randpic_max_file_mb"),
                arms=_arms("bot.randpic", _EK.COMMAND, _EK.ALIAS, _EK.NATURAL_LANGUAGE),
            ),
            _f(
                "bot.reminder",
                _EK.COMMAND,
                _EK.NATURAL_LANGUAGE,
                _EK.ACTIVE_PUSH,
                _EK.SCHEDULER,
                trigger_source="plugins/bot_unified_runtime/domains/schedule"
                               "/capabilities/reminder.py#is_reminder_command",
                board="B07",  # 现算自 board_taxonomy：①B07.reminders capability_ids 点名 + ②impl 同目录，二者一致
                implementation_ref="plugins/bot_unified_runtime/domains/schedule"
                                   "/capabilities/reminder.py#build_reminder_capability",
                implementation_line=354,  # 现算 AST：reminder.py 里 `def build_reminder_capability`
                direct_callsites=(
                    "seam:plugins/bot_unified_runtime/__init__.py#_run_simple_capability#x1",
                ),
                config_keys=("bot_reminder_db_path", "bot_reminder_enabled"),
                arms=_arms(
                    "bot.reminder", _EK.COMMAND, _EK.NATURAL_LANGUAGE, _EK.ACTIVE_PUSH,
                ),
            ),
            _f(
                "bot.subscribe",
                _EK.COMMAND,
                _EK.ALIAS,
                _EK.ACTIVE_PUSH,
                # D3=B 扩枚。取值口径同上（腿㉖ 现算派生），但这一枚的**两半必须一起读**：
                #   · 在册的那半＝执行体真身 `content_parser.py::build_subscription_push_capability`
                #     把图像装进结果契约（`images=payload_images`、`kind="mixed" if payload_images`），
                #     载荷来源是订阅条目的**既有图**（`NormalizedSubscriptionItem.cover_url` / 条目 media）；
                #   · 不在册的那半＝生产根今天只交文本（`__init__.py` 调用点不传 images），且
                #     `render_subscription_push_card` 全树零生产调用点 ⇒ **不得叙述成"订阅推送已带图"**。
                # 差账登记在 .superpowers/sdd/2026-09-24-central-dispatch/SEAT-S259.md §7 PX-259-1。
                tags=(_TG.SERVES_IMAGE,),
                trigger_source="plugins/bot_unified_runtime/domains/subscribe"
                               "/capabilities/subscribe.py#is_standalone_subscribe_command",
                board="B05",  # 现算自 board_taxonomy：①B05.subscription capability_ids 点名 bot.subscribe（impl 指 pipeline.py，②不命中）
                implementation_ref="plugins/bot_unified_runtime/domains/chat_reply/runtime"
                                   "/pipeline.py#RuntimePipeline.handle_async",
                implementation_line=535,  # 现算 AST：pipeline.py 里 `class RuntimePipeline`
                direct_callsites=(
                    "generic:plugins/bot_unified_runtime/__init__.py#handle_async#x1",
                    ("seam:plugins/bot_unified_runtime/__init__.py"
                     "#_run_capability_through_pipeline#x1"),
                ),
                config_keys=("bot_subscribe_enabled",),
                arms=_arms("bot.subscribe", _EK.COMMAND, _EK.ALIAS, _EK.ACTIVE_PUSH),
            ),
            # search.web＝被 chat 经中央 `invoke()` 调用的子提供者（普查唯一调用点
            # __init__.py:7461 fn=invoke），八类用户入口格无一对应 ⇒ entry_kinds 诚实留空、
            # 不配 trigger_source（腿④无命令面即不索要指针）。在册有执行面这条属实、
            # implementation_ref 亦如实镜像中央 handler_ref（无命令面 ≠ 无执行体）。
            _f(
                "search.web",
                board="B04",  # 现算自 board_taxonomy：②impl=core/search/web_search.py 落在 B04.knowledge impl_paths(…/domains/core/search)
                implementation_ref="plugins/bot_unified_runtime/domains/core/search"
                                   "/web_search.py#build_web_search_provider",
                # 874→914：#51 web 波把 web_search.py 改到 +330/−24 未回头刷册（一处变更未处处跟随），
                # 由本窗现算 AST 重锚；行号是判据不是注释，别照抄旧值。
                implementation_line=914,  # 现算 AST：web_search.py 里 `def build_web_search_provider`
                direct_callsites=(
                    "invoke:plugins/bot_unified_runtime/__init__.py#invoke#x1",
                ),
                config_keys=(
                    "bot_web_search_enabled", "bot_web_search_provider",
                    "bot_web_search_tavily_api_key",
                ),
            ),
        )
    }
)

# 票根册：凡 FACETS 里出现 native-* 标签，必须在此有对应行；今天**一律不声明 native-***，
# 因为能力侧的票根（渠道 tag × 真实例）尚未按 S05 的票根册格式逐枚收齐。
# 违反该约束的形态在门里以注毒自证（给某行加 native-audio 而不加票根 ⇒ 必红）。
EVIDENCE: MappingProxyType[tuple[str, CapabilityTag], TagEvidence] = MappingProxyType(
    {
        (row.capability_id, row.tag): row
        for row in (
            TagEvidence("media.tts.autodub", _TG.TTS, "tests/test_media_orchestration_wiring.py"),
        )
    }
)

# 未覆盖枚数上限（只降不升）。首届核账＝2026-09-23T19:37:50Z 现算：
#   尺＝`registered_capability_ids()`（capability_protocols.py:2844）∖ `declared_ids()`
#   命令＝`python -c "import sys;sys.path.insert(0,'.');from plugins.bot_unified_runtime.runtime.
#          capability_protocols import registered_capability_ids as r;from plugins.bot_unified_runtime.
#          domains.core import capability_manifest as m;print(len(r()-m.declared_ids()))"`
#   读数＝在册 120 － 已申报 13 ＝ **107**。此后只准降（每降一枚须是新申报，不许把 id 从名册删掉）。
# S67 降账（现算 2026-09-24T00:27:25Z）：本批诚实新申报 6 枚（bot.daily_assist / bot.moegirl /
#   bot.randpic / bot.reminder / bot.subscribe / search.web，逐枚理由见上方 FACETS 批①注释），
#   已申报 13→19、在册仍 120 ⇒ 现算 120－19＝**101**，本上限同批由 107 改小到 101。
#   尺身份三元组同首届（registered_capability_ids ∖ declared_ids）；复跑＝
#   `../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_capability_manifest_gate.py
#    tests/test_capability_manifest_ratchet_direction.py -q`（腿⑦现算 101≤101、腿③b unwired 仍 8）。
UNCOVERED_CEILING: Final[int] = 101


def declared_ids() -> frozenset[str]:
    return frozenset(FACETS)


#: 「协议在册、**执行体**缺位」的显式名册（教义：允许预留协议，禁止把未实现写成已实现）。
#: 判据按名册自己的定义走：本名册只收「`handler_ref` 指向 `reserved` 占位包（只有 docstring
#: 的 `domains/creation/{tts,image}/__init__.py` ⇒ 执行体解析必失败）」的 id。
#: **缺位必须点名，且枚数只降不升**：接真一枚就从本名册摘一枚，同时 G-CM 门上限跟着降。
#: 现摘牌两枚：
#:   ① `creation.tts.synthesize` —— P4-C2/C3 接上 `tts/engine_provider.py#handle`；
#:   ② `creation.image.generate` —— P5 挂上 `image/engine_provider.py#handle`（中央注册 +
#:      契约自验 + provider 接线闸）。**这不等于"绘画能用"**：provider 工厂仍缺位，
#:      真调仍诚实 UNAVAILABLE，且缺位在诊断卡（INVOKER_ERROR_DATA_KEY）、`/bot status`
#:      行与中央告警（reserved_health_alert「要而不得」）三处可见——欠账换了个更靠前的
#:      名字（"无执行体"→"有执行体、无 provider 实现"），没有消失，见 PARKED CM-P-4。
PLACEHOLDER_UNIMPLEMENTED: Final[frozenset[str]] = frozenset()


#: 「在册（FACETS 有行）且中央描述符 `handler_ref` 非空，却**故意**不把镜像指针写进本册」的
#: 显式名册（常驻锁腿②c 的反向判据读它）。与 PLACEHOLDER_UNIMPLEMENTED 同族：缺位必须点名、
#: 枚数只准降——新入册须现算证明是诚实缺位（中央确有执行体而本册选择不镜像）并在席位报告点名，
#: 否则"漏填"会被腿②c 当场打红，而不是被默默读成"没有执行体"。
#: 首届核账＝2026-09-24T01:0xZ 现算：FACETS 19 枚全部逐字镜像中央 handler_ref ⇒ 本名册为空。
#: 尺身份三元组＝本文件 `FACETS[*].implementation_ref` × `CAPABILITY_DESCRIPTOR[*].handler_ref`
#:   × `tests/test_capability_manifest_gate.py::_implementation_ref_consistency`（唯一双向判据真身）。
IMPL_REF_UNDECLARED_ROSTER: Final[frozenset[str]] = frozenset()


#: 「在册且普查**现算零处**直呼点」的显式名册（常驻锁腿⑧的反向判据读它，S130 立）。
#: 为什么要有这本册：`direct_callsites=()` 同时可能是两件相反的事——「现算确实零处（诚实缺位）」
#: 与「这一格我忘了填」。腿⑨比集合等值时两者都落进"册空/算空"，光看等值分不开，
#: 所以**零处必须点名**；名册每枚须由"真缺位诚实腿"现算复核仍是零处（接真一枚摘一枚，只准降）。
#: 首届核账＝2026-09-24T06:28:09Z 现算（尺＝`project_direct_callsites` × `central_seam_census.py`
#: roster；探针见 SEAT-S130 §1.2）：本册申报 20 枚中 **8 枚**零处，逐枚＝
#: `creation.image.generate`（协议预留点，全仓无 `invoke(capability_id=…)` 调用点）＋
#: `media.*` 七枚（在册有执行体、但今天不经中央调用链，即 `DECLARED_UNWIRED_BASELINE` 那本账）。
#: ⚠ 零处 ≠ 能力不存在，也 ≠ 能力能用；它只说"没有人直接调它"。
#: 跟随（2026-09-25，S262 A 案落控制面门面件后由主代理补）：`creation.image.generate` 一枚已**摘牌**，
#: 现存零处枚＝`media.*` 七枚；上面那段"8 枚／逐枚"是首届核账的**当时值**，按规矩保留不删。
DIRECT_CALLSITES_ZERO_ROSTER: Final[frozenset[str]] = frozenset({
    "media.asr.audio_file",
    "media.asr.speech",
    "media.vision.image",
    "media.vision.ocr",
    "media.video.frame_extract",
    "media.video.recognize",
    "media.video.subtitle",
})


#: 「在册且编排侧描述符**现算零枚**配置键」的显式名册（常驻锁腿⑨读它，与上册同型，S130 立）。
#: 首届核账＝同刻现算：本册申报 20 枚**全部 ≥1 键** ⇒ 名册为空（合法可空，非"没写"）。
#: 今后若某枚真能力确实一把键都不读，须现算证明后写进本名册并在席位报告点名，否则"漏填"
#: 会被腿⑨当场打红，而不是被默默读成"这能力不读配置"。
CONFIG_KEYS_ZERO_ROSTER: Final[frozenset[str]] = frozenset()


#: 「在册且**未声明任何内容形态标签**（tags 为空）」的显式名册（常驻锁腿㉕「维↔值」完整性读它，
#: S242 立，防第二种空挂＝有腿、值全空——`tags` 维有腿⑥，但腿⑥只判 native-* 有无票根、
#: **不判这格到底填没填**，空 tags 今天无人点名，正是 `board` 曾经的病，见防回潮锁缘由段）。
#: 与 `DIRECT_CALLSITES_ZERO_ROSTER` / `CONFIG_KEYS_ZERO_ROSTER` 同族铁律：**空必须点名**，
#: 一枚能力若真不消费/不产出词表里的任何内容形态（词表枚数以 `CapabilityTag` 现算为准，本注释不抄数），
#: 须写进本册并在此逐枚说理由；"忘了填"与"确实无"从此分得开。名册每枚须现算仍是真空位
#: （给某枚补上一枚标签⇒必须摘牌，只准降）。
#: 首届核账＝2026-09-25 S242R 现算，逐枚理由；**D3=B（2026-09-24T19:39:57Z 用户裁定）摘掉两枚**：
#:   · `bot.daily_assist` 纯文本速记/三餐/早晚推送，不产图不合成语音；
#:   · `bot.moegirl` 萌娘百科文字词条；
#:   · `bot.reminder` 到点督促纯文本（⚠ 但 `notes.py` 借用本 id 交付笔记配图 ⇒ 见
#:     `SERVES_IMAGE_UNDECLARED_ROSTER` 与本行下方注记；那条账归 id 归属，不属"标签词表"）；
#:   · `search.web` 交回网页命中（文字＋URL），无内容形态产出。
#: 摘牌两枚（原为首届核账的**边界枚**，S242R 当时留话「若词表扩出 serves-existing-image 一类，
#: 应把它们摘牌、改挂真标签——这是词表问题、不是漏填」）：
#:   · `bot.randpic` —— 本机图库既有图片原字节直发 ⇒ 现挂 `CapabilityTag.SERVES_IMAGE`；
#:   · `bot.subscribe` —— 订阅条目既有封面图经结果契约 `images=` 交付 ⇒ 现挂同一枚
#:     （**注意两半**：生产根今天不传 images ⇒ "在册的交付形态"≠"每条推送都带图"，见该 FACETS 行注）。
TAGS_ZERO_ROSTER: Final[frozenset[str]] = frozenset({
    "bot.daily_assist",
    "bot.moegirl",
    "bot.reminder",
    "search.web",
})


#: 「执行体真身**现算派生出图像交付载荷**、却选择不给它挂 `CapabilityTag.SERVES_IMAGE`」的显式名册
#: （常驻锁腿㉖ 的反向判据读它，S259 依用户裁定 D3=B 立）。
#: 为什么要有：腿㉖ 双向钉「声明 ⇔ 派生」。只有正向锁会鼓励人往能派生出处贴标签；
#: 只有反向等值又会被"AI 绘画那一枚不该算既有图像"这一语义差顶死。**豁免必须点名 + 逐枚给理由**，
#: 于是"派生命中却没声明"要么补标签、要么落到这里写清楚为什么不算——不许默默留空、也不许默默漏红。
#: 同族铁律：只准降（接真一枚摘一枚），每枚须由腿㉖b 的诚实腿现算复核仍是"命中但未声明"。
#: 首届核账＝2026-09-24T19:5xZ S259 现算（尺＝`tests/test_capability_manifest_gate.py::
#: derive_serves_image_capability_ids`，扫全 `plugins/**.py` 的 `CapabilityResult(capability_id=…, images=…)`）：
#:   · `bot.reminder` —— 命中点在 `domains/notes/capabilities/notes.py` 的 `_result()`
#:     （笔记配图 `images=[{"file": str(note_image)} …]`），但那处结果契约写的是
#:     `capability_id="bot.reminder"`：**笔记能力复用提醒的 id**（id 归属旧账，另有主）。
#:     D3=B 只裁 `bot.randpic`/`bot.subscribe` 两枚，本席不越裁定给第三枚挂标签，
#:     也不裁"提醒该不该带配图语义"——已连同 id 归属异常一并交回（SEAT-S259 §7 PX-259-2）。
SERVES_IMAGE_UNDECLARED_ROSTER: Final[frozenset[str]] = frozenset({
    "bot.reminder",
})


#: 「在册且**未归属任何一级板块**（board 为空）」的显式名册（常驻锁腿㉕「维↔值」完整性读它，
#: S242 立，与 `TAGS_ZERO_ROSTER` 同型）。board 是防回潮锁点名的"曾有腿、值却可能全空"的样板维
#: （`board` 曾长期空挂，S196 补腿㉔后仍不强制非空——见腿㉔ docstring「本腿不强制非空」），
#: 故本锁把"board 值到底填没填"另立一账：非空即已执法（腿㉔），空则必须落本名册点名。
#: 首届核账＝同刻现算：本册 20 枚 board **全部非空**（S198 按板块树派生填满）⇒ 名册为空
#: （合法可空，非"没写"）。今后某枚若真无法归属任何板块，须现算证明后写进本册并在席位报告点名，
#: 否则"没想好归哪"会被默默读成"无板块"，正是本锁要堵的空挂。
BOARD_ZERO_ROSTER: Final[frozenset[str]] = frozenset()


def entry_kinds_for(capability_id: str) -> tuple[EntryKind, ...]:
    row = FACETS.get(capability_id)
    return () if row is None else row.entry_kinds


def tags_for(capability_id: str) -> tuple[CapabilityTag, ...]:
    row = FACETS.get(capability_id)
    return () if row is None else row.tags


def evidence_for(capability_id: str, tag: CapabilityTag) -> str | None:
    row = EVIDENCE.get((capability_id, tag))
    return None if row is None else row.evidence


def implementation_ref_for(capability_id: str) -> str:
    """本册申报的执行体真身指针（中央 handler_ref 的镜像；未申报行返回空串）。"""
    row = FACETS.get(capability_id)
    return "" if row is None else row.implementation_ref


def implementation_line_for(capability_id: str) -> int:
    """本册申报的执行体真身行号（对 `implementation_ref` 锚点的 AST 定位投影；未申报返回 0）。

    ⚠ 0 有两种读法（"无 implementation_ref" 与 "忘了填行号"），分辨只认
    `implementation_ref` 是否非空——有 ref 却 0 即由常驻锁腿②d 当场打红。
    """
    row = FACETS.get(capability_id)
    return 0 if row is None else row.implementation_line


def unsupported_native_tags() -> list[str]:
    """声明了 native-* 却没有实测票根的行（正常应为空；非空即门红）。

    native-* 票根的**单一真源**＝`capability_tag_evidence.TICKETS`（S68 立的独立票根册，
    配扫描面地板 + kind 覆盖两把真牙）——**不**读 `EVIDENCE`：把票根复制进 `EVIDENCE` 会变成
    第二真身（各写一份＝漂移）。`EVIDENCE` 只留非原生内容档（如 media.tts.autodub/TTS）的在册
    指针。懒导入（函数体内）保 `capability_manifest` 顶层零包依赖、静态求值器照旧算得动 FACETS。
    """
    from plugins.bot_unified_runtime.domains.core import capability_tag_evidence as cte

    bad: list[str] = []
    for capability_id, row in FACETS.items():
        for tag in row.tags:
            if tag.value.startswith("native-") and (capability_id, tag.value) not in cte.TICKETS:
                bad.append(f"{capability_id}:{tag.value}")
    return sorted(bad)


def direct_callsites_for(capability_id: str) -> tuple[str, ...]:
    """本册申报的直呼点投影（普查产物的去行号镜像；未申报行返回空 tuple）。

    ⚠ 空 tuple 有第二种读法（"现算真的零处"），两者的分辨**只认**
    `DIRECT_CALLSITES_ZERO_ROSTER`，别拿本函数的返回值当"这能力没接线"的结论——
    接线态的唯一尺是普查 `state`（腿③b 读它）。
    """
    row = FACETS.get(capability_id)
    return () if row is None else row.direct_callsites


def config_keys_for(capability_id: str) -> tuple[str, ...]:
    """本册申报的配置键（编排侧描述符 `config_keys` 并集的镜像；未申报行返回空 tuple）。"""
    row = FACETS.get(capability_id)
    return () if row is None else row.config_keys


def arms_for(capability_id: str) -> tuple[CapabilityArm, ...]:
    """本册申报的臂（入口形↔中央汇缝的投影；未申报或非合成行返回空 tuple）。

    臂不是"入口形态名"（那住 `entry_kinds_for`），是"哪些形态真经中央调度、经哪一枚汇缝"。
    一能力 `arms` 空只说明它没有**被入口活性件走过**的形（例：passive_matcher/control_plane），
    不等于"这能力没有入口"。逐臂 `seam_host` 由 `ARM_FORM_SEAMS` 单源投影，形↔缝对活性件的
    双向等值由常驻门 `tests/test_capability_manifest_gate.py` 的腿㉓执法。
    """
    row = FACETS.get(capability_id)
    return () if row is None else row.arms
