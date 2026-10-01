# 内容安全与亲密模式 · 亲密档位与双开关

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B03.content-safety · 亲密档位与双开关

- 层级：一级 B03 → 二级 content-safety → 三级 `intimate-mode`
- 实现落点：`plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/content_safety.py`、`plugins/bot_unified_runtime/domains/chat_reply/security/memory_sanitize.py`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

决定「这一段对话走哪个档位、按什么口径注入」的机制件（不占路由席位、无独立能力 id）。它把会话维护成一个亲密度分数，叠加本地信号（强词表 + 近若干轮上下文 + 手动开关）做滞回判定，产出 `intimate` 与 `normal` 两档：亲密档放宽篇幅与表现力并注入恋人语气，普通档走默认链与日常叙述口径。**2026-09-24 分级裁定（T8）**：亲密档不再是单一布尔，还带**来源**（`pin_source`，只住引擎一处、随钉一起过期清零）——**L1**=Master Love 名单派生：给语气与内容放行、**不改默认模型**（链首照旧 gemini，媒体原生照挂）；**L2**=本人显式「亲密模式 开」/管理员钉/内容信号越阈：档 + grok 头插（判据唯一=`_MODEL_SWITCH_SOURCES`，换首跳后该会话媒体按"先转译、不静默剥"处理，见 chat 功能页）。生效条件：外门（名单门，见 [四名单与群级门](roster-gates.md)）先放行，内层才谈档位。它只管「怎么说、谁来答」，能不能说由 [六条硬线与不可架空](hard-lines.md) 决定。

## 怎么调用

真身在 `plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py`。

- `ContentRouteEngine`：进程级共享实例 `SHARED_CONTENT_ROUTE_ENGINE`；`observe_turn(...)` 逐轮喂分数与信号、做滞回与惰性过期，`route_verdict(session_key, config)` 给出当前档位。
- `resolve_intimate_context(engine, *, session_type, group_id, sender_id, session_key, config)`：**注入缝与路由侧共用的单一事实源**（chat 侧读它、`build_router_cb` 也经它），双门同源、不各判一套；返回 `eligible / route_key / mode / source` 四项——`source` 回答"为什么亲密"（`INTIMATE_SOURCE_*`，2026-09-24 分级裁定后新增，真身只有引擎 `_SessionState.pin_source` 一处，本函数只转述）。
- `build_router_cb(engine, config_provider)`：把档位判定适配成模型路由的 `content_route_cb`，`config_provider` 是零参 callable（装配期闭包返回热覆盖合并视图），保证热改对路由判定即时生效。
- `match_manual_command(text)`：手动开关识别（「亲密模式 开/关」及倒装「开启亲密模式」），开与关各回一句人话，见 `MANUAL_ON_REPLY` / `MANUAL_OFF_REPLY`。
- `member_session_key(group_key, sender_id)` 用成员分隔符派生出「群内某成员」键（`split_member_session_key` 反解）——个人钉与滞回落在这个派生键上，天然做到 (群, 用户) 隔离。

## 开关与参数

键前缀 `bot_content_route_`（逐键语义、缺省值与可热改性以 `docs/config-catalog-full.md` 与 `config.py` 真身字段为准，本文不写死数值）：

- 滞回：进入 `intimate` 的上阈值与回到 `normal` 的下阈值之间留死区，配分数衰减与空闲归零，避免边界来回抖。
- 时效：`intimate` 档有从激活起算的 TTL 与一条更长的硬上限，重开会重置 TTL、触到硬上限强制归位；两个分钟数以对应键缺省为真身。
- 总闸 `bot_content_route_enabled`、亲密档候选序 `bot_content_route_model` 与 `bot_content_route_order`、上下文轮数 `bot_content_route_context_turns`、追加强词 `bot_content_route_words`。
- Master Love：`bot_master_love_enabled` 与 `bot_master_love_admins`（命中即自动进亲密档并注入恋人语气，但**不覆盖**会话内显式「关」的 normal 钉，也绝不越硬线；2026-09-24 分级裁定起 ML 派生钉交 `master_love` 来源标签——**只给档、不改默认模型**，链首照旧缺省 gemini，要换 grok 须本人显式「开」或管理员钉）。
- 谁能改：档位与阈值是管理员/超管侧配置；会话内只有「亲密模式 开/关」这一条命令可拨，群内非管理员只影响自己（走成员派生键）。

## 失败时看到什么

- `resolve_intimate_context` 全程 fail-open 到安全侧：异常时 `eligible` 为假、键回退原会话键、档位置 `normal`，绝不因合成失败而放大亲密面。
- 判定或路由回调的内部异常不冒泡打断主链路，最坏是这一轮按默认链回复；细节走日志。
- 分数与档位是纯本地启发式，误判方向「宁宽不窄」：误命中只是这一轮换一个更配合的模型、人格照常注入，无实害；代价是公开面里出现强词会被切档，已由用户裁定接受。

## 测试与验收

`tests/test_content_route.py`、`tests/test_content_route_v3.py`（滞回、双开关、TTL 惰性过期、成员键隔离、Master Love 自动钉的判别锁、分级来源与"ML 不换模型/显式开才换"两向格、语气与路由同判据）、`tests/test_content_route_threading.py`（并发共享态）、`tests/test_native_av_input.py`（亲密头插 × 媒体门：ML 会话不剥媒体、L2 转译优先）。
真机：`docs/acceptance-manual.md` §6.6.7（内容感知路由）与 §6.6.15（分级亲密 L1/L2 + 亲密媒体转译）；逐符号行为以测试件为真身，用例数以最近一次 `scripts/dev.ps1 -Task test` 实跑输出为准。
