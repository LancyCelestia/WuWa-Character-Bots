# 内容安全与亲密模式 · 亲密档位与双开关

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 亲密档位与双开关

- 层级：一级 B03 → 二级 content-safety → 三级 `intimate-mode`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定「这一段对话走哪个档位、按什么口径注入」的机制件（不占路由席位、无独立能力 id）。它把会话维护成一个亲密度分数，叠加本地信号（强词表 + 近若干轮上下文 + 手动开关）做滞回判定，产出 `intimate` 与 `normal` 两档。**进了亲密档不等于一次拿到全部**：档位只回答「在不在档里」，另外两件事各有各的判据——换不换真实首跳（`_MODEL_SWITCH_SOURCES`）、给不给成段的场景叙述（`grants_intimate_narration`）。三轴互不派生、也不许复用同一枚集合（并轴即红的锁见下方测试），放宽任一枚都不会静默改写另外两枚。普通档走默认链，叙述口径是「只用说话来回应」。

**档与来源是两件事**（2026-09-24 分级裁定）：**深浅**记在 `INTIMATE_TIER_*`，唯一解析口是 `match_intimate_command`（整句「亲密模式 开」=浅档 L1，「亲密模式 深开」及其别名=深档 L2，「关」两档一起解除）；**为什么进档**记在 `INTIMATE_SOURCE_*`（真身只有引擎 `_SessionState.pin_source` 一处，随钉一起过期清零）。Master Love 名单派生（`master_love`）与好感度达档自动（`affinity_tier`）是**来源**、不是档位：调用方没交档时由 `_tier_for_source` 按来源派生缺省深浅。头插判据＝「L2 且来源在册」⇒ 名单派生与好感度自动腿**不改默认模型**（链首照旧缺省，媒体原生照挂），要换首跳得「深开」/管理员钉/内容信号越阈（换首跳后该会话媒体按"先转译、不静默剥"处理，见 chat 功能页）。

**授予面**（2026-10-04 用户裁定新增的概念，与本档旧口径的关键差别）：在「档」与「换模型」之外，**展开叙述另立一张授予面**。场景描写维度（清单以 `INTIMATE_RP_STYLE_INSTRUCTION` 与 `NORMAL_NO_ACTION_INSTRUCTION` 两段常量为真身；亲密段开哪几维、日常段禁令就得点名关哪几维，成对锁见下方测试）只授予**人亲手推动**的那几种来源：显式指令（「开」与「深开」都算，深浅与此无关）、管理员代全群钉、内容信号自己跨阈。名单派生与好感度达档自动从此**只给关系语气与内容放行、不再给展开叙述**，那一轮回落到「只说话」。裁定原话＝「superadmin 的默认 master love 模式仍然为只描述说话内容，不描述动作等，要求输入显式指令打开亲密模式 L1、L2 才变成这样」。消费点＝chat 主链的 `_rp_intimate_now`：它在原有「进了亲密档」之外多读这一枚来源判据，判据只住引擎那一份，调用方不许抄第二份成员表。

同批落下的是**维度补齐**：日常段禁令与亲密段许可对齐点名（补了哪几维以两段常量与 `_SCENE_DIMENSIONS` 为准），唯一刻意不同形的地方是**「语言」只进亲密段的许可、不进日常段的禁令**——日常段的立身句就是「只用说话来回应」，把语言列进禁令＝要求它禁掉自己的正文，模型同一轮读到两句拆台的话。这段理由住 `tests/test_reply_policy_permanent.py` 里 `_SCENE_DIMENSIONS` 的上方注释，别一席看它对不上就顺手补进去。

**篇幅不由档位说**（2026-09-28 T8「档位风格统一」裁定，覆盖本页更早的「亲密档放宽篇幅」写法）：亲密段与日常段都不自带长度口径（黑名单锁见下方测试），篇幅唯一真身＝本轮那一行长度分档指令；亲密侧的升格走 `capabilities/chat.py:intimate_reply_length_tier`（2026-10-04 裁定改为：拿到叙述授予的那一轮**直接取登记表的顶格档**，不再在秩上升一格；登记表同批为这一档新登记了一枚档名「铺写」，此前的「不新增档名也不新增数值」已不成立——数值与档名仍只以 `REPLY_LENGTH_TIERS` 为唯一真身，本页一个字都不抄），出口重问的硬地板读同一个升格。⚠ 连带效果正是所要：没拿到叙述授予的那一轮，长度升格一并失去。

生效条件：外门（名单门，见 [四名单与群级门](roster-gates.md)）先放行，内层才谈档位。它只管「怎么说、谁来答」，能不能说由 [六条硬线与不可架空](hard-lines.md) 决定。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`。

- `ContentRouteEngine`：进程级共享实例 `SHARED_CONTENT_ROUTE_ENGINE`；`observe_turn(...)` 逐轮喂分数与信号、做滞回与惰性过期，`route_verdict(session_key, config)` 给出当前档位。
- `resolve_intimate_context(engine, *, session_type, group_id, sender_id, session_key, config)`：**注入缝与路由侧共用的单一事实源**（chat 侧读它、`build_router_cb` 也经它），双门同源、不各判一套；字段清单以该函数 docstring 与 `route_verdict` 为准（`eligible / route_key / mode / source / tier`）——`source` 回答"为什么亲密"、`tier` 回答"深浅"，这两枚正是「档」与「来源」两轴的读数处，真身只有引擎 `_SessionState.pin_source` / `pin_tier` 一处，本函数只转述、不再判一次。**授予面不在这里判**：它由 `grants_intimate_narration` 现判，见下。
- `build_router_cb(engine, config_provider)`：把档位判定适配成模型路由的 `content_route_cb`，`config_provider` 是零参 callable（装配期闭包返回热覆盖合并视图），保证热改对路由判定即时生效。
- `match_intimate_command(text)` → `(mode, tier)`：**深浅档位的唯一解析口**。词面是「亲密模式 开/关」及倒装「开启亲密模式」，深档另有「深开/开 深/开 二档/开 grok」一类别名（每条正则都带行锚，句中夹带不算命令）；受理与否各回一句人话，见 `MANUAL_ON_REPLY` / `MANUAL_DEEP_ON_REPLY` / `MANUAL_OFF_REPLY`。`match_manual_command(text)` 是它的旧读面薄壳（只转述 mode、不设第二套正则），需要分辨「开」与「深开」的调用方必须读前者。
- `grants_intimate_narration(source)`：**展开叙述授予面的唯一判据**（成员集合真身＝`_INTIMATE_NARRATION_SOURCES`，白名单形）。它只回答"要不要展开叙述"，档位（`INTIMATE_TIER_*`）、换真实首跳（`_MODEL_SWITCH_SOURCES`）、TTL 封顶（`_MAX_TTL_EXEMPT_SOURCES`）三件事一个都不读；调用方（chat 主链 `_rp_intimate_now`）只准调它，不许再抄一份成员表。
- `member_session_key(group_key, sender_id)` 用成员分隔符派生出「群内某成员」键（`split_member_session_key` 反解）——个人钉与滞回落在这个派生键上，天然做到 (群, 用户) 隔离。

## 开关与参数

键前缀 `bot_content_route_`（逐键语义、缺省值与可热改性以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准，本文不写死数值）：

- 滞回：进入 `intimate` 的上阈值与回到 `normal` 的下阈值之间留死区，配分数衰减与空闲归零，避免边界来回抖。
- 时效：`intimate` 档有从激活起算的 TTL 与一条更长的硬上限，重开会重置 TTL、触到硬上限强制归位；两个分钟数以对应键缺省为真身。
- 总闸 `bot_content_route_enabled`、亲密档候选序 `bot_content_route_model` 与 `bot_content_route_order`、上下文轮数 `bot_content_route_context_turns`、追加强词 `bot_content_route_words`。
- Master Love：`bot_master_love_enabled` 与 `bot_master_love_admins`（命中即自动进亲密档并注入恋人语气，但**不覆盖**会话内显式「关」的 normal 钉，也绝不越硬线；2026-09-24 分级裁定起 ML 派生钉交 `master_love` 来源标签——**只给档、不改默认模型**，链首照旧缺省）。
- L1 自动腿：`bot_content_route_l1_auto_enabled` 与 `bot_content_route_l1_auto_min_tier`——好感度**档号**达标的用户自动进浅档，来源标签 `affinity_tier`，与 ML 同类（只给档、不改默认模型）。门槛档号的真身住 `character/affinity.py` 的 `_ATTITUDE_TIERS`，本页不抄档位表；逐键缺省值与热改性以 `docs/config-catalog-full.md` 与 `config.py` 为准。
- **自动派生的那两支都不给展开叙述**（2026-10-04 授予面裁定）：名单派生与好感度达档只换关系语气与内容放行。要拿到场景描写维度、或要换真实首跳，都得由人亲手推动——显式「亲密模式 开/深开」、管理员代全群钉、或内容信号自己跨阈。叙述授予面与头插来源集**不许并轴**（判据分别住 `grants_intimate_narration` 与 `_MODEL_SWITCH_SOURCES`，成员今天恰好同形纯属巧合），见上方「授予面」。
- 谁能改：档位与阈值是管理员/超管侧配置；会话内只有「亲密模式 开/深开/关」这一族整句命令可拨，群内非管理员只影响自己（走成员派生键）。

## 失败时看到什么

- `resolve_intimate_context` 全程 fail-open 到安全侧：异常时 `eligible` 为假、键回退原会话键、档位置 `normal`，绝不因合成失败而放大亲密面。
- 授予面取**白名单**形：未知来源（含未进档时的空串、以及上一条回落出的 `normal`）一律不授予展开叙述 ⇒ 判不准的方向只会「少写一段描写」，不会「多写」；长度升格读同一个门，所以回落时一并收回。
- 判定或路由回调的内部异常不冒泡打断主链路，最坏是这一轮按默认链回复；细节走日志。
- 分数与档位是纯本地启发式，误判方向「宁宽不窄」：误命中只是这一轮换一个更配合的模型、人格照常注入，无实害；代价是公开面里出现强词会被切档（内容信号在头插与叙述两张来源集里都在册，这条是 2026-09-16 在册裁定的原样），已由用户裁定接受。

## 测试与验收

`tests/test_content_route.py`、`tests/test_content_route_v3.py`（滞回、双开关、TTL 惰性过期、成员键隔离、Master Love 自动钉的判别锁、分级来源与"ML 不换模型／显式深开才换"两向格、语气与路由同判据）、`tests/test_content_route_threading.py`（并发共享态）、`tests/test_native_av_input.py`（亲密头插 × 媒体门：ML 会话不剥媒体、深档转译优先）。
**叙述授予面与篇幅口径的锁**：`tests/test_rp_style_directives.py`（日常段与亲密段互斥注入；ML 轮**恋人语气照旧在场、展开叙述必须收回**；授予面与头插面／TTL 豁免面**不是同一枚集合**的防并轴腿，含注毒自证）、`tests/test_reply_policy_permanent.py`（`_SCENE_DIMENSIONS` 成对锁＝亲密段开哪几维、日常段禁令就得点名关哪几维，维度清单以该件常量为真身；`_ROUTE_LENGTH_PHRASES` 黑名单锁＝两段场景常量里不许再长出任何篇幅口径）。
真机：`docs/acceptance-manual.md` §6.6.7（内容感知路由）与 §6.6.15（分级亲密 L1/L2 + 亲密媒体转译）；逐符号行为以测试件为真身，用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
