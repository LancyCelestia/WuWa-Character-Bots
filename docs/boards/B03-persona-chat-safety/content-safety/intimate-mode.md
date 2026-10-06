# 内容安全与亲密模式 · 亲密档位与双开关

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 亲密档位与双开关

- 层级：一级 B03 → 二级 content-safety → 三级 `intimate-mode`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/runtime/intimate_control.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定「这一段对话走哪个档位、按什么口径注入」的机制件（不占路由席位、无独立能力 id）。它把会话维护成一个亲密度分数，叠加本地信号（强词表 + 近若干轮上下文 + 手动开关）做滞回判定，产出 `intimate` 与 `normal` 两档。**进了亲密档不等于一次拿到全部**：档位只回答「在不在档里」，另外两件事各有各的判据——换不换真实首跳（`_MODEL_SWITCH_SOURCES`）、给不给成段的场景叙述（`grants_intimate_narration`）。三轴互不派生、也不许复用同一枚集合（并轴即红的锁见下方测试），放宽任一枚都不会静默改写另外两枚。普通档走默认链，叙述口径是「只用说话来回应」。

**档与来源是两件事**（2026-09-24 分级裁定）：**深浅**记在 `INTIMATE_TIER_*`，解析口**按词面分两条、同形不同路**——整句面 `match_intimate_command`（「亲密模式 开」=浅档 L1，「亲密模式 深开」及其别名=深档 L2，「关」两档一起解除），命令面 `match_intimate_subcommand`（吃 `/bot intimate` 剥掉前缀剩下的参数串，词表真身＝同文件的 `_INTIMATE_SUBCOMMAND_TABLE`，认不出返回 None 而不猜档）。两套词面互不引用是有意为之：命令面走英文子命令、口语面走中文整句，共用一张表只会让一次改词静默改掉另一条路。两条路都只回 `MODE_*`／`INTIMATE_TIER_*`，档位字面量只落 `content_route.py` 那一处；命令面的入口与三腿分诊在 `intimate_control.py` 的 `build_intimate_control_result`，能力 id 复用 `bot.chat`（未另铸 `bot.intimate`）。**为什么进档**记在 `INTIMATE_SOURCE_*`（真身只有引擎 `_SessionState.pin_source` 一处，随钉一起过期清零）。Master Love 名单派生（`master_love`）与好感度达档自动（`affinity_tier`）是**来源**、不是档位：调用方没交档时由 `_tier_for_source` 按来源派生缺省深浅。头插判据＝「L2 且来源在册」⇒ 名单派生与好感度自动腿**不改默认模型**（链首照旧缺省，媒体原生照挂），要换首跳得「深开」/管理员钉/内容信号越阈（换首跳后该会话媒体按"先转译、不静默剥"处理，见 chat 功能页）。

**授予面**（2026-10-04 用户裁定新增的概念，与本档旧口径的关键差别）：在「档」与「换模型」之外，**展开叙述另立一张授予面**。场景描写维度（清单以 `INTIMATE_RP_STYLE_INSTRUCTION` 与 `NORMAL_NO_ACTION_INSTRUCTION` 两段常量为真身；亲密段开哪几维、日常段禁令就得点名关哪几维，成对锁见下方测试）只授予**人亲手推动**的那几种来源：显式指令（「开」与「深开」都算，深浅与此无关）、管理员代全群钉、内容信号自己跨阈。名单派生与好感度达档自动从此**只给关系语气与内容放行、不再给展开叙述**，那一轮回落到「只说话」。裁定原话＝「superadmin 的默认 master love 模式仍然为只描述说话内容，不描述动作等，要求输入显式指令打开亲密模式 L1、L2 才变成这样」。消费点＝chat 主链的 `_rp_intimate_now`：它在原有「进了亲密档」之外多读这一枚来源判据，判据只住引擎那一份，调用方不许抄第二份成员表。

同批落下的是**维度补齐**：日常段禁令与亲密段许可对齐点名（补了哪几维以两段常量与 `_SCENE_DIMENSIONS` 为准），唯一刻意不同形的地方是**「语言」只进亲密段的许可、不进日常段的禁令**——日常段的立身句就是「只用说话来回应」，把语言列进禁令＝要求它禁掉自己的正文，模型同一轮读到两句拆台的话。这段理由住 `tests/test_reply_policy_permanent.py` 里 `_SCENE_DIMENSIONS` 的上方注释，别一席看它对不上就顺手补进去。

**描写档＝第三轴，但不是第二把尺**（2026-10-04 裁定，代码侧注为 G-0～G-4；⚠ 本段所引三个文件此刻都有别席在飞，符号名与「判据只一枚」这条口径按现读记账、行文会变＝will move）：档位答"在不在档里"、头插来源集答"谁来答"，第三轴只答**说出口之外的那几维写不写**——两值 `speech`（缺省）/ `scene`（也铺开），字面量只在 `runtime/content_route.py` 的 `NARRATION_MODE_*` 一处声明。它**不新铸判据**：新来源 `INTIMATE_SOURCE_NARRATION_PIN`（码串 `narration_pin`）是并进既有那**一把**授予尺 `_INTIMATE_NARRATION_SOURCES` 的一员，问"这一轮铺不铺开写"仍然只准 `grants_intimate_narration(narration_source)` 这一处调用；换模型／TTL 豁免／缺省浅档／跨重启重钉那四张来源集**一个成员都不跟着动**（上方"三轴互不派生、不许并轴"那条纪律对它同样成立）。与本页旧口径的两处关键差别：①**普通档也拿得到**——判据不看档在不在，它是文风偏好而非放行授权，因此命令面**不吃** `bot_content_route_enabled` 总闸、也不吃 `eligible` 名单门（拿总闸当它的门＝让一次路由开关静默改掉文风面）；②它是**持久的**——本人钉写进已有的 `addressing_preferences` 表（owner 在 `character/addressing.py`），且**没有 TTL**：一直活到本人自己说一句 `speech` 或 `reset`（两枚都算表态，见 `_narration_axis_reading` 第②格），`intimate_ttl_minutes` 管不到它也不该管它。
**为什么不另立一张卡**（本页因此就是它的落点）：按 `_conventions.md` 第〇节的三级入口判据——它不占 RouteKind 席位、无独立 `capability_id`（能力 id 复用 `bot.chat`）、也不是第 3 条那种要用 `extra_l3` 独立声明的契约/护栏/生成物件（它的授予判据就是本卡在册的那一枚），于是落进第 5 条「其余任何粒度写在所属入口卡片的正文里」。同一枚判据拆成两页讲＝多一处会漂移的副本；`capability_registry.py` 那条帮助主题也按同理由**并入既有主题、未另立**。

**篇幅不由档位说**（2026-09-28 T8「档位风格统一」裁定，覆盖本页更早的「亲密档放宽篇幅」写法）：亲密段与日常段都不自带长度口径（黑名单锁见下方测试），篇幅唯一真身＝本轮那一行长度分档指令；亲密侧的升格走 `capabilities/chat.py:intimate_reply_length_tier`（2026-10-04 裁定改为：拿到叙述授予的那一轮**直接取登记表的顶格档**，不再在秩上升一格；登记表同批为这一档新登记了一枚档名「铺写」，此前的「不新增档名也不新增数值」已不成立——数值与档名仍只以 `REPLY_LENGTH_TIERS` 为唯一真身，本页一个字都不抄），出口重问的硬地板读同一个升格。⚠ 10-05 起这"一问"变成**两问**：升格腿量在**归一化之前**，出站归一化（`capabilities/chat.py::_finalize_reply_text`）之后另有 `_delivery_length_floor_leg` 按**送达**的那版再判一次（裁定 F-5＝乙，2026-10-05 落码）——每轮至多补一次、产物不回流、上游腿已追过就静默不追，缺口若来自预算截断或危险命令整段替换则**不追只留痕**（`length_delivery_floor_*:budget`/`:guard`），且补写稿要再过同一把出站闸才比长度；数值与档名仍只住 `REPLY_LENGTH_TIERS`，本页一个字都不抄。⚠ 连带效果正是所要：没拿到叙述授予的那一轮，长度升格一并失去。

生效条件：外门（名单门，见 [四名单与群级门](roster-gates.md)）先放行，内层才谈档位。它只管「怎么说、谁来答」，能不能说由 [六条硬线与不可架空](hard-lines.md) 决定。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`。

- `ContentRouteEngine`：进程级共享实例 `SHARED_CONTENT_ROUTE_ENGINE`；`observe_turn(...)` 逐轮喂分数与信号、做滞回与惰性过期，`route_verdict(session_key, config)` 给出当前档位。
- `resolve_intimate_context(engine, *, session_type, group_id, sender_id, session_key, config)`：**注入缝与路由侧共用的单一事实源**（chat 侧读它、`build_router_cb` 也经它），双门同源、不各判一套；字段清单以该函数 docstring 与 `route_verdict` 为准（`eligible / route_key / mode / source / tier`）——`source` 回答"为什么亲密"、`tier` 回答"深浅"，这两枚正是「档」与「来源」两轴的读数处，真身只有引擎 `_SessionState.pin_source` / `pin_tier` 一处，本函数只转述、不再判一次。**授予面不在这里判**：它由 `grants_intimate_narration` 现判，见下。
- `build_router_cb(engine, config_provider)`：把档位判定适配成模型路由的 `content_route_cb`，`config_provider` 是零参 callable（装配期闭包返回热覆盖合并视图），保证热改对路由判定即时生效。
- `match_intimate_command(text)` → `(mode, tier)`：**整句那一面**的档位解析口（与下面 `match_intimate_subcommand` 同形不同路，两条各认各的词面）。词面是「亲密模式 开/关」及倒装「开启亲密模式」，深档另有「深开/开 深/开 二档/开 grok」一类别名（每条正则都带行锚，句中夹带不算命令）；受理与否各回一句人话，见 `MANUAL_ON_REPLY` / `MANUAL_DEEP_ON_REPLY` / `MANUAL_OFF_REPLY`。`match_manual_command(text)` 是它的旧读面薄壳（只转述 mode、不设第二套正则），需要分辨「开」与「深开」的调用方必须读前者。
- `match_intimate_subcommand(arg)` → `(mode, tier)` 或 None：**命令面那一族**的参数解析口。输入＝**已剥掉 `/bot intimate` 前缀**后剩下的参数串（前缀归命令面，本口不管）；三态语义与整句面逐字同——浅档、深档、两档一起解除，大小写不敏感、首尾空白容忍，**认不出的一律 None**（不猜档，也不把「没认出来」悄悄回落成「开」，那等于凭一个错字把会话推进亲密档）。`show` 有意不在词表里、由本口返回 None：给它任何 `(mode, tier)` 都等于「看一眼当前档位，顺手把档位改了」。
- `build_intimate_control_result(...)`（`intimate_control.py`，非本文件）：`/bot intimate` 命令面的真实入口与**三腿分诊口**——开关 → 只读查询 → 用法，三条都不中才回「不认得」。命令面没有「落回普通聊天」这条路，所以不受理那一格也必须有话说；全程 fail-open，读不出来一律收在「不表态」那一侧，绝不少数报一个档位、也绝不因查询失败去动钉。派发在插件 `__init__.py` 的命令分派处，能力 id 复用 `bot.chat`。
- `grants_intimate_narration(source)`：**展开叙述授予面的唯一判据**（成员集合真身＝`_INTIMATE_NARRATION_SOURCES`，白名单形）。它只回答"要不要展开叙述"，档位（`INTIMATE_TIER_*`）、换真实首跳（`_MODEL_SWITCH_SOURCES`）、TTL 封顶（`_MAX_TTL_EXEMPT_SOURCES`）三件事一个都不读；调用方（chat 主链 `_rp_intimate_now`）只准调它，不许再抄一份成员表。
- `member_session_key(group_key, sender_id)` 用成员分隔符派生出「群内某成员」键（`split_member_session_key` 反解）——个人钉与滞回落在这个派生键上，天然做到 (群, 用户) 隔离。

描写档那一族（同上，`content_route.py` 为真身，`runtime/intimate_control.py` 只做分诊与行文；⚠ will move）：

- `normalize_narration_mode(raw)`：任意输入 → 轴上取值，认不出与空的都落缺省、**绝不抛**。它兜的是"值漂走了别放大描写面"这一侧。
- `match_narration_subcommand(arg)` → `str | None`：**命令面参数口**，输入＝已剥掉 `/bot narration`（中文词面 `/bot 描写`）前缀后剩下的串。词表真身＝同文件 `_NARRATION_SUBCOMMAND_TABLE`，返回三态与开关面同纪律：轴上两值 / `""`＝**收回钉**（与"钉上 speech"在库里是两回事：前者无值、后者明写着要 `speech`，`show` 必须分辨得开）/ `None`＝认不出且不猜。`show` 有意不在表里，词面沿用 `intimate_control.SHOW_SUBCOMMAND`（那里声明过一次，这里再列就是第二处声明位）。中文整句那一族今天只说"亲密模式"，描写档**没有**自己的整句词面——另起正则等于新造第三族词面，要做需另裁。
- `_narration_axis_reading(...)` → `(mode, source)`：优先级 **四格**＝①本轮明示 → ②本人持久钉（**两格都算表态**：钉 `scene` 交 `scene`、钉 `speech` 交 `speech`）→ ③**亲密缺省**（裁定 H-1＝甲，2026-10-04 深夜「开'亲密'的话，就给 scene 场景」：亲手把亲密档推上去的那一轮，没在描写轴上说过话也拿到 `scene`；⚠ 这一格只在亲密裁决**不出自整群那一桶**时才交，见 `route_verdict` 的 `from_group_pin` 与 `resolve_intimate_context`，且自动腿那两支交不进来源）→ ④缺省 `speech`。🔴 **模式必须编码进来源**：①②的 `scene` 与③交出的是**授予面上的来源串**（①②＝`INTIMATE_SOURCE_NARRATION_PIN`；③＝她那一句"开亲密"自己的来源，绝不借用别的轴——借它等于没裁定就放宽授予，而分离锁比的是集合成员、不是谁把哪枚塞进去的），`speech` 交出 `INTIMATE_SOURCE_NONE`（白名单外＝不授予）。反过来说＝"来源同一枚、授予却看模式"才是长了第二把尺，正是本波要防的事。本轮那一格**故意不走** `normalize_narration_mode`（拿缺省当"本轮说了"会静默顶掉持久钉），直接对 `NARRATION_MODES` 判成员。
- `resolve_intimate_context(...)` 因此在原字段之外多交 `narration_mode` / `narration_source` 两格；它本身仍不判授予。
- `narration_write_allowed(*, session_type, sender_roles)`：**谁能写这一格**的唯一判据（命令面只调它、不许抄角色集合）。群侧只放 admin/super_admin；非群侧本人自助、不吃角色门（口径同 #66「自助偏好仅本人」——G-3 收的是群侧，不是把整条命令关进管理员屋里）。
- `read_narration_pin` / `write_narration_pin` / `clear_narration_pin`（引擎侧）：**键口与库口只在这一侧**，落盘经 `character/addressing.py` 的 `get_narration_pin` / `set_narration_pin` / `clear_narration_pin`；读写的是既有 `addressing_preferences` 上的 `narration_mode` 与 `narration_updated_at` 两枚列（ALTER-if-missing 加列、与亲密档标记同表；那张时间戳**不参与任何过期判定**，只供审计）。钉的归属键形＝ **(平台域, 会话, 这个人)** 三段（I-2 已落）：人段出自 `person_scope_key`（平台写法归一只准用 `roles.platform_domain_of`，拿不到平台事实＝fail-closed 回空串），会话段出自 `_narration_store_scope`——群 ⇒ 库里既有的 `("group", 群号)` 那一行、**频道 ⇒ `("channel", 该频道会话键)` 那一行**（用户 2026-10-06 裁「telegram：群侧」：一个频道一把桶，频道之间、频道与私聊之间都不同桶；认形只认契约字段 `session_type`，拿不到时才退到 `channel_` 前缀 fallback＝方向恒为 fail-closed，因为中央件对 `guild_` 那形**明写不判**）、私聊/控制台 ⇒ 沿用 `("private", "")`（她已有的私聊钉原地不动＝零迁移），两段的键形都只准出自 `domains/core/session_keys` 中央件（先 `split_member_session_key` **拆**基键，绝不反解重拼）。
- `build_narration_control_result(...)`（`intimate_control.py`，非本文件）：`/bot 描写|narration` 的真实入口与**三腿分诊口**——写腿 → 只读 `show` → 用法，三条都不中才回"不认得"；生效链一条都不重造（解析、作用域门、落盘、读数全指回 `content_route.py`）。`_narration_grant_line` 是「细节描写」那一格的**唯一渲染口**，`/bot intimate show` 与 `/bot 描写 show` 因此在同一轮里必然同值。返回值永远是 `CapabilityResult`（命令面没有"落回普通聊天"这条路）。能力 id 复用 `bot.chat`，未另铸 `bot.narration`。
- 样式段的取数＝`capabilities/chat.py` 的 `RP_STYLE_BLOCKS`（⚠ will move）：键是 `(描写档, 亲密授予态)` 两轴、值指向表里登记的那几段样式常量——**确切段名与各段开哪几维一律以 `RP_STYLE_BLOCKS`、`RP_STYLE_GROUP_BLOCKS`、`resolve_rp_style_block` 与那几段常量为真身，本页一个字都不抄**（日常段 `NORMAL_NO_ACTION_INSTRUCTION` 留在原位不动，为的是在册锁判它在普通轮与未授予轮逐字在场）。会话面是**第二把表**不是第三个键：群聊那一侧走 `RP_STYLE_GROUP_BLOCKS`（I-3＝丙：群内 `scene` 不落笔身形／衣着），`resolve_rp_style_block(mode, intimate=…, group=…)` 一次选表、零嵌套分支，`group` 缺省 `False`＝私聊面＝改前形态。`resolve_rp_style_block` 把表外／漂走的轴值 fail-closed 收到只说话那一格。🔴 一枚谓词曾被喂进过两种量，故 `chat.py` 立了两枚**取量口**：`narration_ruler_source`（叙述轴，答这一轮能不能铺开写）与 `intimate_axis_source`（亲密轴，答这档是谁推上去的、供亲密轮出站动作括号豁免读）——「细节描写」那一格只准问前者。

## 开关与参数

键前缀 `bot_content_route_`（逐键语义、缺省值与可热改性以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准，本文不写死数值）：

- 滞回：进入 `intimate` 的上阈值与回到 `normal` 的下阈值之间留死区，配分数衰减与空闲归零，避免边界来回抖。
- 时效：`intimate` 档有从激活起算的 TTL 与一条更长的硬上限，重开会重置 TTL、触到硬上限强制归位；两个分钟数以对应键缺省为真身。
- 总闸 `bot_content_route_enabled`、亲密档候选序 `bot_content_route_model` 与 `bot_content_route_order`、上下文轮数 `bot_content_route_context_turns`、追加强词 `bot_content_route_words`。
- Master Love：`bot_master_love_enabled` 与 `bot_master_love_admins`（命中即自动进亲密档并注入恋人语气，但**不覆盖**会话内显式「关」的 normal 钉，也绝不越硬线；2026-09-24 分级裁定起 ML 派生钉交 `master_love` 来源标签——**只给档、不改默认模型**，链首照旧缺省）。
- L1 自动腿：`bot_content_route_l1_auto_enabled` 与 `bot_content_route_l1_auto_min_tier`——好感度**档号**达标的用户自动进浅档，来源标签 `affinity_tier`，与 ML 同类（只给档、不改默认模型）。门槛档号的真身住 `character/affinity.py` 的 `_ATTITUDE_TIERS`，本页不抄档位表；逐键缺省值与热改性以 `docs/config-catalog-full.md` 与 `config.py` 为准。
- **自动派生的那两支都不给展开叙述**（2026-10-04 授予面裁定）：名单派生与好感度达档只换关系语气与内容放行。要拿到场景描写维度、或要换真实首跳，都得由人亲手推动——显式「亲密模式 开/深开」、管理员代全群钉、或内容信号自己跨阈。叙述授予面与头插来源集**不许并轴**（判据分别住 `grants_intimate_narration` 与 `_MODEL_SWITCH_SOURCES`，成员今天恰好同形纯属巧合），见上方「授予面」。
- 谁能改：档位与阈值是管理员/超管侧配置；会话内只有「亲密模式 开/深开/关」这一族整句命令可拨，群内非管理员只影响自己（走成员派生键）。
- 描写档**不新增配置键、不新增库**（键清单以 `config.py` 与 `docs/config-catalog-full.md` 为准，缺省值一律指真身）：它借的是既有会话存储里那条已有的表，长度旋钮仍走 `REPLY_LENGTH_TIERS` 那一行。`bot_content_route_enabled` 总闸与 `bot_content_route_intimate_ttl_minutes` 那一类 TTL 键**都不辖它**——一个只管路由与放行，一个只管档态过期。
- 谁能改（描写档）：写腿的门只有一枚 `narration_write_allowed`，它读的公共空间判据也只有一枚 `is_public_space_session`（群与**频道**同侧，用户 2026-10-06 裁「telegram：群侧」）。公共空间侧非管理员被拒；钉的键形带会话段，所以管理员在群里写得进的是**他自己在那一个群里**的一格，替整群拨的那一枚亲密档永不广播描写档（两腿同守：群作用域键读不出本人段；「开亲密即缺省 `scene`」那一格只在裁决不出自整群那一桶时才交，见 `route_verdict` 的 `from_group_pin`）。非公共空间侧本人自助即可。
- 四条裁定**已全部落地**（本页此前把它们记作"在途"，现按盘面改口）：①**H-1＝甲**——亲手把亲密档推上去的那一轮，描写轴缺省跟着走 `scene`（`_narration_axis_reading` 第③格；自动腿 `master_love`／`affinity_tier` 仍交空串＝照旧只说话）；②**G-4＝乙**——日常 `scene` 那一格**衣着与环境照写**，禁的只剩"落在身体上的细部"（禁令半句的标记＝`NORMAL_SCENE_BAN_CLAUSE_MARKER`，身体词名册＝`SCENE_CORPORAL_TERMS`）；③**I-2**——钉的键形是 (平台域, 会话, 人)，换一个群、换一个频道、换一路会话都要重说一次（三形的会话段各出自 `_narration_store_scope`，见上方「怎么调用」那一条）；重说一次之后**没有到期这一说**——`read_narration_pin` 取出 `narration_updated_at` 即丢，全仓没有一条通路让这枚钉过期，收回只准本人那句 `speech`／`reset`（2026-10-06 主人原话「激活一次就可以永久，除非用户又发出新的指令，让它切换回 speech」；人读话术用她的形状「说一次就一直算」，不写"永久"）；④**I-3＝丙**——**群侧的 `scene` 不落笔身形／衣着**（公共空间、旁人也在看），私聊那一格照旧写：群侧另有一张表 `RP_STYLE_GROUP_BLOCKS`，由 `resolve_rp_style_block(..., group=)` 按会话面二选一（注入点的 `group=` **只准转述** `is_public_space_session`，手抄 `== "group"` 就是第二把尺、并把频道悄悄放回私聊面），两表的 `speech` 两格**复用同一枚对象**（群里"只说话"与私聊"只说话"本就是同一句话）。

## 失败时看到什么

- `resolve_intimate_context` 全程 fail-open 到安全侧：异常时 `eligible` 为假、键回退原会话键、档位置 `normal`，绝不因合成失败而放大亲密面。
- 授予面取**白名单**形：未知来源（含未进档时的空串、以及上一条回落出的 `normal`）一律不授予展开叙述 ⇒ 判不准的方向只会「少写一段描写」，不会「多写」；长度升格读同一个门，所以回落时一并收回。
- 判定或路由回调的内部异常不冒泡打断主链路，最坏是这一轮按默认链回复；细节走日志。
- 分数与档位是纯本地启发式，误判方向「宁宽不窄」：误命中只是这一轮换一个更配合的模型、人格照常注入，无实害；代价是公开面里出现强词会被切档（内容信号在头插与叙述两张来源集里都在册，这条是 2026-09-16 在册裁定的原样），已由用户裁定接受。
- 描写档全程 fail-open 到"少写"那一侧：落库失败**不改变本轮判定**（那句明示照样生效，只是留不到下一轮），回执据实说一句"没钉上"并打 `narration_unsaved` 标，绝不因为写失败把命令升级成报错。
- 三处方向一致、没有一处会凭错字放大描写面：`match_narration_subcommand` 认不出回 `None`（不猜）、`normalize_narration_mode` 把糊值落缺省 `speech`、`resolve_rp_style_block` 把表外轴值收到只说话。授予面取**白名单**形——`speech` 那一格交出的 `INTIMATE_SOURCE_NONE` 也在白名单外，判不准的后果只会少写、不会多写。
- 群／频道侧被 `narration_write_allowed` 挡下时给 `NARRATION_REFUSED_REPLY`（真身＝`plugins/bot_unified_runtime/domains/chat_reply/runtime/intimate_control.py` 那一枚常量，本页不抄整句以免成第二处副本）。这一格必须有话说：命令面不像整句面那样能落回普通聊天。被这支拒到的永远是群／频道里的非管理员本人——管理员不被拒、私聊不吃门，所以一句就够、不按角色分叉。这句话 2026-10-06 按主人原话补齐了两层（此前只说"换一个群"）：**三形各桶**（换一个群、换一个频道、换一路会话都要再说一次，与 `_narration_store_scope` 的 `group`／`channel`／`private` 三桶同轴）＋**一次即长期**（说一次就一直算，收回只在本人自己另说一句 `speech` 或 `reset`）；句里的裁定编号也去了（那是我们的账，不是给她看的话）。文案与那句"长期"的现算证据同批锁在 `tests/test_narration_axis_show_consistency.py` 第⑤节。

## 测试与验收

`tests/test_content_route.py`、`tests/test_content_route_v3.py`（滞回、双开关、TTL 惰性过期、成员键隔离、Master Love 自动钉的判别锁、分级来源与"ML 不换模型／显式深开才换"两向格、语气与路由同判据）、`tests/test_content_route_threading.py`（并发共享态）、`tests/test_native_av_input.py`（亲密头插 × 媒体门：ML 会话不剥媒体、深档转译优先）。
**叙述授予面与篇幅口径的锁**：`tests/test_rp_style_directives.py`（日常段与亲密段互斥注入；ML 轮**恋人语气照旧在场、展开叙述必须收回**；授予面与头插面／TTL 豁免面**不是同一枚集合**的防并轴腿，含注毒自证）、`tests/test_reply_policy_permanent.py`（`_SCENE_DIMENSIONS` 成对锁＝亲密段开哪几维、日常段禁令就得点名关哪几维，维度清单以该件常量为真身；`_ROUTE_LENGTH_PHRASES` 黑名单锁＝两段场景常量里不许再长出任何篇幅口径）。
**描写档（第三轴）的锁**：`tests/test_narration_axis_command.py`（词表三态、写腿与作用域门，含"其余四张来源集不被这枚新成员动过"那一腿）、`tests/test_narration_axis_show_consistency.py`（`/bot intimate show` 与 `/bot 描写 show` 同轮同值，钉住 `_narration_grant_line` 那一处渲染口）、`tests/test_narration_axis_styles.py` 与 `tests/test_rp_style_directives.py`（样式段按两轴取数、日常段禁令在普通轮与未授予轮逐字在场、授予面与头插面／TTL 豁免面不是同一枚集合的防并轴腿）、`tests/test_narration_command_dispatch.py` 与 `tests/test_narration_alias_dispatch.py`（命令面三腿互不吞、`/bot narration` 与中文词面同路）、`tests/test_intimate_slash_command.py`（末段一枚 AST 锁盯"绝不在旁边再写一套上钉逻辑"）、`tests/test_e2e_acceptance_narration.py`。
⚠ `tests/test_intimate_source_set_separation.py` 里"叙述集与头插集今天同形"那枚等值断言随这枚新成员**按该锁自己写明的用法过期**（放宽必须红一次、要人确认这是有意的轴分离而非并枚）——改的是断言、不是尺，归主会话按裁定重锚，不是本页也不是本波的动作。
本页所引三个文件（`runtime/content_route.py`、`runtime/intimate_control.py`、`capabilities/chat.py`）在写作当刻都有别席在飞：符号名与"判据只一枚"这条口径按现读记账，**措辞与维度清单会变（will move）**，以代码与测试件为真身。

真机：`docs/acceptance-manual.md` §6.6.7（内容感知路由）与 §6.6.15（分级亲密 L1/L2 + 亲密媒体转译）；逐符号行为以测试件为真身，用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
