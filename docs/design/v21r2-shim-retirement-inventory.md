# v21r2 垫片退役清单（EP1 席盘点·只读产出·退役施工图）

- 盘点席：EP1（2026-09-18）；方法=全仓 AST 机核（1155 个 .py：plugins+tests+scripts+根），零人工转录。
- 垫片判定：非 domains/ 路径的 .py，顶层体仅含 docstring/import/`__all__`/`__path__`/`__getattr__`/`__dir__`，且拓扑目标含 `plugins.bot_unified_runtime.domains.*`（绝对 import 或 PEP562 `_CANONICAL` 常量，相对导入已解析）。
- 消费方计数：AST import 边（精确模块匹配+包内 `from pkg import shim_name` 父绑定，相对导入 level 解析；模块级/函数级分列）+ 字符串引用（monkeypatch.setattr 字符串式/importlib 动态串/路径文本锚，只计非 AST 消费文件，增量计数）。
- 快照总计：**275 张垫片**，消费边 1591 条，含字符串引用垫片 22 张。
- 已知盲区（方法注记）：拼接字符串动态 import 理论漏检（各波日志未见实例；spec_from_file_location 文件路径锚类已在各波波内清零）；1 个在飞文件语法红未入扫（见 §3 第 5 条）。

## 1. 总览统计

| 维度 | 分布 |
|---|---|
| 形态 | 静态 re-export 139；PEP562 活转发 131；包静态 re-export 5 |
| 退役判定 | 需先改写消费方 135；在飞占域 55；仅测试消费方 44；可直接退役 41 |
| 来源波（docstring 标记） | RWC3 7；RWOC 55；W10 9；W11 11；W12 4；W13 11；W14 11；W15a 23；W15b 10；W15d 20；W16 5；W1a 28；W1b 16；W2 4；W3 3；W4 2；W5 10；W6 8；W7 10；W8 21；W9 7 |
| 被根 __init__ 消费的垫片 | 108 张（退役前置=子波 5 根 __init__ 清账） |

## 2. 退役判定规则（成文）

1. **可直接退役**：AST 消费边=0 且字符串引用=0 → 最后退役波直接删文件。
2. **仅测试消费方**：src 消费边=0、无字符串引用，仅 tests/ 有 import → 同波改写测试 import 指向 canonical 后删除。
3. **需先改写消费方**：存在 src import 或字符串引用 → 全部消费点改指 canonical（对象式补丁与字符串式补丁都必须同波清零）后删除；含根 __init__ 消费方者其根 __init__ 部分归子波 5。
4. **在飞占域（RWOC）**：docstring 波次标记 = RWOC（RWOCb 原位垫片在飞面）→ 本盘点只记账现状，退役施工归 RWOC 收官清单，其它席位不得代拆。
5. **疑似 LEGAL 配对**：src 函数级旧路取符号 × 测试旧路补丁同模块并存（RW8 social_v2/eat:518 先例=语义载对）→ 拆除前须双侧同波同步改写并跑该测试锁定语义。

## 3. 全局前置条件（最后退役波施工纪律）

1. **子波 5（根 __init__ 清账）先行**：108 张垫片由根 __init__.py 惰性导入消费；根 __init__ 本轮禁触（等 RWOCb 收官），未清前这些垫片不可删。
2. **RWOCb 收官先行**：在飞占域垫片（§5 表内「在飞占域」行）按其收官清单处置。
3. **每批退役同波门禁**：改写/删除后必跑 全量收集（collect-only 0 错）+ verify_hashes --check + doc_sync + 渲染契约（涉 output/ 时）+ 受影响域回归；垫片删除后旧路径 import 必须 ImportError 由测试网兜住。
4. **同目录整批退役**：包垫片与其子模块垫片同批删除（子模块 import 会隐式初始化父包，父包垫片单独存活无意义）。
5. **S14b 在飞语法红**：`domains/ops/incident/service.py:215` invalid syntax（S14 席在飞 WIP，本席未触）→ 该文件不在消费统计内；其收波后如需精确重盘可重跑本席脚本。

## 4. 零消费方可直接退役清单（41 张）

| 垫片 | 形态 | 来源波 |
|---|---|---|
| `character.relationship` | PEP562 活转发 | W15a |
| `character.shared_export` | PEP562 活转发 | W15a |
| `sources.draw_store` | 静态 re-export | W5 |
| `sources.epicfree` | 静态 re-export | W8 |
| `sources.fetchers.xhs_sign` | 静态 re-export | W1b |
| `sources.market_crosscheck` | 静态 re-export | W7 |
| `sources.nmc_weather` | 静态 re-export | W3 |
| `sources.open_meteo` | 静态 re-export | W3 |
| `sources.parsers.image_stitch` | 静态 re-export | W1b |
| `sources.parsers.platforms_acfun` | 静态 re-export | W1a |
| `sources.parsers.platforms_allcpp` | 静态 re-export | W1a |
| `sources.parsers.platforms_bilibili` | 静态 re-export | W1a |
| `sources.parsers.platforms_bilibili_goods` | 静态 re-export | W1a |
| `sources.parsers.platforms_community` | 静态 re-export | W1a |
| `sources.parsers.platforms_discourse` | 静态 re-export | W1a |
| `sources.parsers.platforms_douban` | 静态 re-export | W1a |
| `sources.parsers.platforms_epic` | 静态 re-export | W1a |
| `sources.parsers.platforms_facebook` | 静态 re-export | W1a |
| `sources.parsers.platforms_github` | 静态 re-export | W1a |
| `sources.parsers.platforms_huajia` | 静态 re-export | W1a |
| `sources.parsers.platforms_kuaishou` | 静态 re-export | W1a |
| `sources.parsers.platforms_kurobbs` | 静态 re-export | W1a |
| `sources.parsers.platforms_lofter` | 静态 re-export | W1a |
| `sources.parsers.platforms_media_share` | 静态 re-export | W1a |
| `sources.parsers.platforms_mihuashi` | 静态 re-export | W1a |
| `sources.parsers.platforms_miyoushe` | 静态 re-export | W1a |
| `sources.parsers.platforms_moegirl` | 静态 re-export | W1a |
| `sources.parsers.platforms_music` | 静态 re-export | W1a |
| `sources.parsers.platforms_pixiv` | 静态 re-export | W1a |
| `sources.parsers.platforms_skland` | 静态 re-export | W1a |
| `sources.parsers.platforms_steam` | 静态 re-export | W1a |
| `sources.parsers.platforms_taptap` | 静态 re-export | W1a |
| `sources.parsers.platforms_telegram` | 静态 re-export | W1a |
| `sources.parsers.platforms_weibo` | 静态 re-export | W1a |
| `sources.parsers.platforms_xiaoheihe` | 静态 re-export | W1a |
| `sources.parsers.platforms_zhihu` | 静态 re-export | W1a |
| `sources.steamfree` | 静态 re-export | W8 |
| `sources.subscription_watcher` | 静态 re-export | W8 |
| `sources.subscriptions.bilibili_adapter` | 静态 re-export | W8 |
| `sources.subscriptions.target_notice` | 静态 re-export | W8 |
| `sources.url_cleaner` | 静态 re-export | W1b |

## 5. 按目录分组明细（全部垫片）

### `…`（9 张；零消费 0；在飞 5）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `backend_unit` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15d | 仅测试消费方 |
| `config_readiness` | PEP562 活转发 | 2 | 3/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `console_chat` | PEP562 活转发 | 2 | 2/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `diagnostics` | PEP562 活转发 | 2 | 1/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `mail_adapter` | 静态 re-export | 0* | 1/0 | 2/0 | 0 | W14 | 需先改写消费方 |
| `mail_bridge` | 静态 re-export | 0* | 1/1 | 1/1 | 0 | W14 | 需先改写消费方 |
| `message_context` | PEP562 活转发 | 2 | 3/0 | 3/3 | 0 | W15d | 需先改写消费方 |
| `route_demo` | PEP562 活转发 | 2 | 0/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `smoke` | PEP562 活转发 | 2 | 1/1 | 1/2 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
- `backend_unit`：测试 import 1 处；消费方示例：tests/test_backend_unit.py
- `mail_adapter`：src 模块级 import 1 处；测试 import 2 处；消费方示例：bot.py, tests/test_mail_adapter_resilience.py, tests/test_v21r2_lifecycle_r2.py
- `mail_bridge`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/monitor/disconnect_notice.py, tests/test_mail_bridge.py
- `message_context`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/core/contracts/runtime.py, tests/test_internal_marker_regex.py, tests/test_phase0_3_features.py, tests/test_reply_chain_recursion.py 等7文件

### `…/audit`（2 张；零消费 0；在飞 2）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `file_logger` | PEP562 活转发 | 2 | 1/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `logger` | PEP562 活转发 | 2 | 2/4 | 0/4 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
-（本目录全部为零消费/在飞，无前置）

### `…/capabilities`（40 张；零消费 0；在飞 5）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `affinity` | PEP562 活转发 | 2 | 3/0 | 4/7 | 0 | RWC3 | 需先改写消费方 |
| `campus` | 静态 re-export | 2* | 1/1 | 1/0 | 0 | W12 | 需先改写消费方 |
| `chat` | PEP562 活转发 | 2 | 7/2 | 18/26 | 0 | RWC3 | 需先改写消费方 |
| `content_parser` | 静态 re-export | 3* | 3/9 | 5/1 | 1 | W1b | 需先改写消费方 |
| `daily_assist` | 静态 re-export | 4* | 2/0 | 1/0 | 0 | W12 | 需先改写消费方 |
| `debug` | PEP562 活转发 | 2 | 0/1 | 2/2 | 0 | RWOC | 在飞占域 |
| `divination` | 静态 re-export | 2* | 3/0 | 9/1 | 0 | W5 | 需先改写消费方 |
| `download` | 静态 re-export | 0* | 2/0 | 1/0 | 0 | W9 | 需先改写消费方 |
| `eat` | 静态 re-export | 2* | 2/0 | 7/2 | 0 | W4 | 需先改写消费方 |
| `echo` | PEP562 活转发 | 2 | 2/8 | 16/15 | 0 | RWC3 | 需先改写消费方 |
| `epic` | 静态 re-export | 1* | 4/0 | 4/0 | 0 | W8 | 需先改写消费方 |
| `feature_control` | PEP562 活转发 | 2 | 0/1 | 0/1 | 0 | RWOC | 在飞占域 |
| `file_exchange` | 静态 re-export | 2* | 0/2 | 1/0 | 0 | W9 | 需先改写消费方 |
| `fx` | 静态 re-export | 0* | 3/0 | 3/0 | 0 | W7 | 需先改写消费方 |
| `group_files` | 静态 re-export | 0* | 1/0 | 1/0 | 0 | W9 | 需先改写消费方 |
| `group_info` | PEP562 活转发 | 2 | 2/0 | 1/0 | 0 | RWC3 | 需先改写消费方 |
| `image_search` | PEP562 活转发 | 2 | 0/1 | 1/0 | 0 | W11 | 需先改写消费方 |
| `market` | 静态 re-export | 0* | 3/0 | 6/3 | 0 | W7 | 需先改写消费方 |
| `media_archive` | PEP562 活转发 | 2 | 2/0 | 0/0 | 1 | W11 | 需先改写消费方 |
| `meme` | 静态 re-export | 1* | 3/0 | 6/0 | 3 | W6 | 需先改写消费方 |
| `meme_library` | 静态 re-export | 0* | 3/2 | 6/0 | 0 | W6 | 需先改写消费方 |
| `memory` | PEP562 活转发 | 2 | 0/1 | 0/0 | 0 | RWC3 | 需先改写消费方 |
| `moegirl` | PEP562 活转发 | 2 | 2/0 | 4/0 | 0 | W16 | 需先改写消费方 |
| `music` | 静态 re-export | 2* | 7/4 | 8/3 | 0 | W2 | 需先改写消费方 |
| `news` | 静态 re-export | 0* | 3/0 | 3/0 | 0 | W8 | 需先改写消费方 |
| `notes` | 静态 re-export | 10* | 1/0 | 0/0 | 0 | W9 | 需先改写消费方 |
| `platform_credentials` | PEP562 活转发 | 2 | 1/1 | 2/1 | 0 | RWOC | 在飞占域 |
| `poke` | PEP562 活转发 | 2 | 0/1 | 4/1 | 0 | RWC3 | 需先改写消费方 |
| `randpic` | 静态 re-export | 0* | 3/0 | 3/0 | 0 | W6 | 需先改写消费方 |
| `reminder` | 静态 re-export | 1* | 3/0 | 5/2 | 0 | W10 | 需先改写消费方 |
| `runtime_admin` | PEP562 活转发 | 2 | 0/3 | 7/10 | 0 | RWOC | 在飞占域 |
| `runtime_logs` | PEP562 活转发 | 2 | 0/2 | 0/1 | 0 | RWOC | 在飞占域 |
| `stocks` | 静态 re-export | 0* | 3/0 | 4/2 | 0 | W7 | 需先改写消费方 |
| `subscribe` | 静态 re-export | 0* | 1/2 | 4/0 | 6 | W8 | 需先改写消费方 |
| `subscribe_v2` | 静态 re-export | 1* | 0/3 | 8/0 | 0 | W8 | 需先改写消费方 |
| `today_history` | 静态 re-export | 3* | 4/1 | 7/2 | 0 | W8 | 需先改写消费方 |
| `tts` | PEP562 活转发 | 2 | 2/0 | 0/0 | 0 | W11 | 需先改写消费方 |
| `user_copy` | PEP562 活转发 | 2 | 24/0 | 10/1 | 0 | RWC3 | 需先改写消费方 |
| `weather` | 静态 re-export | 3* | 6/0 | 5/0 | 0 | W3 | 需先改写消费方 |
| `wiki` | PEP562 活转发 | 2 | 4/0 | 2/0 | 0 | W16 | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `capabilities.affinity`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 11 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_affinity_query.py, tests/test_affinity_v6_smoothing.py, tests/test_ratchet_fix.py 等9文件
- `capabilities.campus`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_campus_digest.py
- `capabilities.chat`：含根 __init__ 消费方→随子波 5；src 模块级 import 7 处；src 函数级 import 2 处；测试 import 44 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/prompt_preview.py, plugins/bot_unified_runtime/domains/ops/admin/debug.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py 等37文件
- `capabilities.content_parser`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；src 函数级 import 9 处；字符串引用 1 文件；测试 import 6 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/divination/capabilities/divination.py, plugins/bot_unified_runtime/domains/divination/projection/render_projection.py, plugins/bot_unified_runtime/domains/food/capabilities/eat.py, plugins/bot_unified_runtime/domains/music/capabilities/music.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py 等16文件
- `capabilities.daily_assist`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_daily_assist.py
- `capabilities.divination`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 10 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_divination.py, tests/test_divination_hijack_guard.py, tests/test_feature_cards.py 等13文件
- `capabilities.download`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, tests/test_f03_notice_redaction.py
- `capabilities.eat`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 9 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_auditfix_subscriptions_capabilities.py, tests/test_eat_capability.py, tests/test_eat_image_quality.py, tests/test_prfix_eat.py 等9文件
- `capabilities.echo`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；src 函数级 import 8 处；测试 import 31 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, scripts/e2e_acceptance.py, scripts/extract_trigger_words.py, scripts/render_card_samples.py, tests/test_affinity_query.py 等28文件
- `capabilities.epic`：含根 __init__ 消费方→随子波 5；src 模块级 import 4 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, tests/test_auditfix_wave3_logic.py, tests/test_epic_card.py 等8文件
- `capabilities.file_exchange`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_file_exchange.py
- `capabilities.fx`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_finance_routing.py, tests/test_traditional_triggers_2.py, tests/test_trigger_english.py
- `capabilities.group_files`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_batch_cdf_modules.py
- `capabilities.group_info`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_group_info.py
- `capabilities.image_search`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_auditfix_wave3_logic.py
- `capabilities.market`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 9 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_finance_market_expansion.py, tests/test_finance_routing.py, tests/test_help_deep_teaching_n2re.py 等10文件
- `capabilities.media_archive`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；字符串引用 1 文件；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py
- `capabilities.meme`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；字符串引用 3 文件；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, tests/test_meme_conflict_fix.py, tests/test_meme_domain_fixes.py, tests/test_meme_image_input.py 等9文件
- `capabilities.meme_library`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；src 函数级 import 2 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_meme_conflict_fix.py, tests/test_meme_domain_fixes.py, tests/test_ratchet_fix.py 等9文件
- `capabilities.memory`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py
- `capabilities.moegirl`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_moegirl_yield_fix.py, tests/test_traditional_triggers_2.py, tests/test_trigger_english.py, tests/test_word_boundary_fix.py
- `capabilities.music`：含根 __init__ 消费方→随子波 5；src 模块级 import 7 处；src 函数级 import 4 处；测试 import 11 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/natural_language.py, plugins/bot_unified_runtime/domains/link_parse/capabilities/content_parser.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py 等17文件
- `capabilities.news`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_news.py, tests/test_traditional_news_randpic.py, tests/test_trigger_english.py
- `capabilities.notes`：src 模块级 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/schedule/capabilities/reminder.py
- `capabilities.poke`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_meme_domain_fixes.py, tests/test_phase0_3_features.py, tests/test_poke_unified_reaction_b10.py, tests/test_poke_v2.py, tests/test_runtime_subfeatures.py
- `capabilities.randpic`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_randpic_identity.py, tests/test_traditional_news_randpic.py, tests/test_trigger_english.py
- `capabilities.reminder`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 7 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_reminder.py, tests/test_reminder_tone.py, tests/test_todo_checkoff.py 等8文件
- `capabilities.stocks`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, scripts/e2e_acceptance.py, tests/test_finance_market_expansion.py, tests/test_finance_routing.py, tests/test_route_order_semantics.py 等8文件
- `capabilities.subscribe`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；字符串引用 6 文件；测试 import 4 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_audit_fixes_b.py, tests/test_subscribe_capability_bridge.py, tests/test_traditional_triggers_2.py, tests/test_trigger_english.py
- `capabilities.subscribe_v2`：含根 __init__ 消费方→随子波 5；src 函数级 import 3 处；测试 import 8 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_audit_fixes_b.py, tests/test_auditfix_subscriptions_capabilities.py, tests/test_music_subscription_removed_platforms_j06_v2.py, tests/test_reaudit_20260911.py, tests/test_subscribe_capability_v2.py 等9文件
- `capabilities.today_history`：含根 __init__ 消费方→随子波 5；src 模块级 import 4 处；src 函数级 import 1 处；测试 import 9 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, tests/test_card_prune.py, tests/test_feature_cards.py 等11文件
- `capabilities.tts`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py
- `capabilities.user_copy`：src 模块级 import 24 处；测试 import 11 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py, plugins/bot_unified_runtime/domains/core/credentials/platform_credentials.py, plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py, plugins/bot_unified_runtime/domains/finance/capabilities/fx.py, plugins/bot_unified_runtime/domains/finance/capabilities/market.py 等35文件
- `capabilities.weather`：含根 __init__ 消费方→随子波 5；src 模块级 import 6 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/natural_language.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, scripts/e2e_acceptance.py 等11文件
- `capabilities.wiki`：含根 __init__ 消费方→随子波 5；src 模块级 import 4 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, tests/test_trigger_english.py, tests/test_word_boundary_fix.py

### `…/capabilities/auto_send`（2 张；零消费 0；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `__init__` | 包静态 re-export | 0* | 1/2 | 1/0 | 3 | W10 | 需先改写消费方 |
| `parser` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W10 | 仅测试消费方 |

退役前置（本目录有消费方垫片）：
- `capabilities.auto_send`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；字符串引用 3 文件；测试 import 1 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/base_router.py, tests/test_trigger_english.py
- `capabilities.auto_send.parser`：测试 import 2 处；消费方示例：tests/test_auditfix_wave3_logic.py, tests/test_traditional_triggers_2.py

### `…/character`（29 张；零消费 2；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `addressing` | PEP562 活转发 | 2 | 2/0 | 2/2 | 0 | W15a | 需先改写消费方 |
| `affinity` | PEP562 活转发 | 2 | 1/5 | 14/3 | 0 | W15a | 需先改写消费方 |
| `daily_assist` | 静态 re-export | 9* | 1/2 | 2/2 | 0 | W12 | 需先改写消费方 |
| `documents` | PEP562 活转发 | 2 | 1/1 | 0/0 | 0 | W15a | 需先改写消费方 |
| `draw_store` | 静态 re-export | 1* | 0/0 | 1/0 | 0 | W5 | 仅测试消费方 |
| `emotion` | PEP562 活转发 | 2 | 1/2 | 0/0 | 0 | W15a | 需先改写消费方 |
| `glossary` | PEP562 活转发 | 2 | 1/0 | 2/0 | 0 | W15a | 需先改写消费方 |
| `history` | PEP562 活转发 | 2 | 5/0 | 1/2 | 0 | W15a | 需先改写消费方 |
| `kb_wiki` | PEP562 活转发 | 2 | 0/4 | 2/0 | 0 | W16 | 需先改写消费方 |
| `media_registry` | PEP562 活转发 | 2 | 0/2 | 1/0 | 0 | W11 | 需先改写消费方 |
| `memory` | PEP562 活转发 | 2 | 3/1 | 2/1 | 3 | W15a | 需先改写消费方 |
| `memory_extract` | PEP562 活转发 | 2 | 0/2 | 2/0 | 0 | W15a | 需先改写消费方 |
| `mood` | PEP562 活转发 | 2 | 0/1 | 1/1 | 0 | W15a | 需先改写消费方 |
| `notes_store` | 静态 re-export | 1* | 0/2 | 2/2 | 0 | W9 | 需先改写消费方 |
| `persona_service` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15a | 仅测试消费方 |
| `persona_set` | PEP562 活转发 | 2 | 0/1 | 1/0 | 0 | W15a | 需先改写消费方 |
| `providers` | PEP562 活转发 | 2 | 1/12 | 4/10 | 0 | W15a | 需先改写消费方 |
| `quirks` | PEP562 活转发 | 2 | 0/3 | 3/0 | 0 | W15a | 需先改写消费方 |
| `reflection` | PEP562 活转发 | 2 | 0/2 | 3/0 | 0 | W15a | 需先改写消费方 |
| `relationship` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | W15a | 可直接退役 |
| `reminders` | 静态 re-export | 2* | 0/3 | 5/2 | 0 | W10 | 需先改写消费方 |
| `session_identity` | PEP562 活转发 | 2 | 0/2 | 1/1 | 0 | W15a | 需先改写消费方 |
| `shared_export` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | W15a | 可直接退役 |
| `shared_group` | PEP562 活转发 | 2 | 0/2 | 2/1 | 0 | W15a | 需先改写消费方 |
| `source_summary` | PEP562 活转发 | 2 | 2/0 | 0/0 | 0 | W15a | 需先改写消费方 |
| `temporal` | PEP562 活转发 | 2 | 0/0 | 2/1 | 0 | W15a | 仅测试消费方 |
| `trend` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15a | 仅测试消费方 |
| `vector_knowledge` | PEP562 活转发 | 2 | 4/2 | 5/4 | 0 | W15a | 需先改写消费方 |
| `worldbook_service` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15a | 仅测试消费方 |

退役前置（本目录有消费方垫片）：
- `character.addressing`：src 模块级 import 2 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/character/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_addressing_context.py, tests/test_identity_preference_commands.py
- `character.affinity`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 5 处；测试 import 17 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py, tests/test_affection_alias.py, tests/test_affinity.py, tests/test_affinity_numerical.py, tests/test_affinity_query.py 等17文件
- `character.daily_assist`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_daily_assist.py, tests/test_rp_style_directives.py, tests/test_v21r2_hotzone_meal_variants.py
- `character.documents`：src 模块级 import 1 处；src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/control_plane/factory.py, plugins/bot_unified_runtime/domains/core/config/config_readiness.py
- `character.draw_store`：测试 import 1 处；消费方示例：tests/test_divination_service_v21.py
- `character.emotion`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/character/__init__.py, plugins/bot_unified_runtime/policy/rate_limit.py
- `character.glossary`：src 模块级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_glossary_recall.py, tests/test_glossary_seed.py
- `character.history`：src 模块级 import 5 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/character/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/prompt_preview.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, tests/test_perf_p1.py 等7文件
- `character.kb_wiki`：含根 __init__ 消费方→随子波 5；src 函数级 import 4 处；测试 import 2 处；消费方示例：bot.py, plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/character/knowledge_service.py, plugins/bot_unified_runtime/domains/ops/smoke/smoke.py, tests/test_kb_wiki_sync.py, tests/test_sdd9_n3re.py
- `character.media_registry`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_media_registry.py
- `character.memory`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；src 函数级 import 1 处；字符串引用 3 文件；测试 import 3 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/character/__init__.py, plugins/bot_unified_runtime/character/memory_service.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/memory.py, tests/test_help_deep_teaching_n2re.py, tests/test_persona_prompt_and_memory.py 等7文件
- `character.memory_extract`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_persona_prompt_and_memory.py, tests/test_sdd7_n4.py
- `character.mood`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_affinity_v21.py, tests/test_mood.py
- `character.notes_store`：src 函数级 import 2 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/domains/schedule/capabilities/reminder.py, tests/test_reminder.py, tests/test_todo_checkoff.py
- `character.persona_service`：测试 import 1 处；消费方示例：tests/test_persona_service_v21.py
- `character.persona_set`：src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, tests/test_reaudit_20260911.py
- `character.providers`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 12 处；测试 import 14 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/character/__init__.py, plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/food/capabilities/eat.py, plugins/bot_unified_runtime/domains/notes/capabilities/notes.py 等20文件
- `character.quirks`：含根 __init__ 消费方→随子波 5；src 函数级 import 3 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, tests/test_quirks.py, tests/test_quirks_scope.py, tests/test_sdd7_n4.py
- `character.reflection`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_quirks_scope.py, tests/test_reflection.py, tests/test_sdd7_n4.py
- `character.reminders`：含根 __init__ 消费方→随子波 5；src 函数级 import 3 处；测试 import 7 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/notes/capabilities/notes.py, tests/test_reminder.py, tests/test_reminder_governance_receipt.py, tests/test_reminder_tone.py, tests/test_todo_checkoff.py 等8文件
- `character.session_identity`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, tests/test_help_deep_teaching_n2re.py, tests/test_randpic_identity.py
- `character.shared_group`：含根 __init__ 消费方→随子波 5；src 函数级 import 2 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_addressing_context.py, tests/test_auditfix_main_character.py, tests/test_shared_group_digest_list.py
- `character.source_summary`：src 模块级 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/ops/admin/debug.py, plugins/bot_unified_runtime/domains/ops/smoke/smoke.py
- `character.temporal`：测试 import 3 处；消费方示例：tests/test_auditfix_main_character.py, tests/test_temporal_http_client.py, tests/test_v21_risk_red_tz_and_files.py
- `character.trend`：测试 import 1 处；消费方示例：tests/test_trend_write.py
- `character.vector_knowledge`：src 模块级 import 4 处；src 函数级 import 2 处；测试 import 9 处；消费方示例：plugins/bot_unified_runtime/character/knowledge_service.py, plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py, plugins/bot_unified_runtime/domains/location/knowledge/kb_wiki.py, plugins/bot_unified_runtime/domains/ops/smoke/smoke.py, scripts/knowledge_bench.py, tests/test_auditfix_main_character.py 等11文件
- `character.worldbook_service`：测试 import 1 处；消费方示例：tests/test_persona_service_v21.py

### `…/contracts`（10 张；零消费 0；在飞 10）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `auto_send` | PEP562 活转发 | 2 | 1/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `character` | PEP562 活转发 | 2 | 9/0 | 1/1 | 0 | RWOC | 在飞占域 |
| `envelope` | PEP562 活转发 | 2 | 3/0 | 1/0 | 1 | RWOC | 在飞占域 |
| `errors` | PEP562 活转发 | 2 | 1/0 | 2/0 | 0 | RWOC | 在飞占域 |
| `finance` | PEP562 活转发 | 2 | 3/0 | 6/13 | 0 | RWOC | 在飞占域 |
| `media` | PEP562 活转发 | 2 | 33/2 | 11/1 | 0 | RWOC | 在飞占域 |
| `music` | PEP562 活转发 | 2 | 4/1 | 5/1 | 0 | RWOC | 在飞占域 |
| `request` | PEP562 活转发 | 2 | 1/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `runtime` | PEP562 活转发 | 2 | 9/0 | 11/0 | 0 | RWOC | 在飞占域 |
| `subscription` | PEP562 活转发 | 2 | 9/0 | 22/1 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
-（本目录全部为零消费/在飞，无前置）

### `…/decision`（8 张；零消费 0；在飞 8）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `dispatcher` | PEP562 活转发 | 2 | 0/0 | 2/0 | 0 | RWOC | 在飞占域 |
| `engine` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `ingress` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `outbound` | PEP562 活转发 | 2 | 2/2 | 3/2 | 0 | RWOC | 在飞占域 |
| `outbound_contracts` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `outbound_registry` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `shadow` | PEP562 活转发 | 2 | 0/1 | 1/0 | 0 | RWOC | 在飞占域 |
| `trace` | PEP562 活转发 | 2 | 1/1 | 2/1 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
-（本目录全部为零消费/在飞，无前置）

### `…/llm`（8 张；零消费 0；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `billing_entities` | PEP562 活转发 | 2 | 0/0 | 2/0 | 0 | W15b | 仅测试消费方 |
| `billing_pricing` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15b | 仅测试消费方 |
| `billing_service` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15b | 仅测试消费方 |
| `channel_health` | PEP562 活转发 | 2 | 0/10 | 0/0 | 0 | W15b | 需先改写消费方 |
| `ledger` | PEP562 活转发 | 2 | 0/6 | 3/0 | 0 | W15b | 需先改写消费方 |
| `model_router` | PEP562 活转发 | 2 | 5/22 | 10/4 | 0 | W15b | 需先改写消费方 |
| `providers` | PEP562 活转发 | 2 | 3/1 | 9/3 | 1 | W15b | 需先改写消费方 |
| `usage_service` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15b | 仅测试消费方 |

退役前置（本目录有消费方垫片）：
- `llm.billing_entities`：测试 import 2 处；消费方示例：tests/test_billing_service_v21.py
- `llm.billing_pricing`：测试 import 1 处；消费方示例：tests/test_billing_service_v21.py
- `llm.billing_service`：测试 import 1 处；消费方示例：tests/test_billing_service_v21.py
- `llm.channel_health`：含根 __init__ 消费方→随子波 5；src 函数级 import 10 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/_app.py, plugins/bot_unified_runtime/control_plane/llm_admin.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py
- `llm.ledger`：src 函数级 import 6 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/control_plane/_app.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py, plugins/bot_unified_runtime/runtime/database_broker.py, tests/test_ledger_channel_breakdown.py, tests/test_ledger_range_query.py 等7文件
- `llm.model_router`：含根 __init__ 消费方→随子波 5；src 模块级 import 5 处；src 函数级 import 22 处；测试 import 14 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/factory.py, plugins/bot_unified_runtime/control_plane/llm_admin.py, plugins/bot_unified_runtime/domains/assistant/daily/store/daily_assist.py, plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py, plugins/bot_unified_runtime/domains/link_parse/capabilities/content_parser.py 等24文件
- `llm.providers`：src 模块级 import 3 处；src 函数级 import 1 处；字符串引用 1 文件；测试 import 12 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/control_plane/factory.py, plugins/bot_unified_runtime/control_plane/sandbox.py, plugins/bot_unified_runtime/domains/chat_reply/character/temporal.py, scripts/probe_intimate_route.py, tests/test_chat_provider_chain.py, tests/test_control_plane_sandbox.py 等15文件
- `llm.usage_service`：测试 import 1 处；消费方示例：tests/test_usage_billing_v21.py

### `…/output`（7 张；零消费 0；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `bot_avatar` | 静态 re-export | 0* | 6/2 | 0/0 | 0 | W13 | 需先改写消费方 |
| `plain_text` | 静态 re-export | 0* | 10/1 | 5/1 | 0 | W13 | 需先改写消费方 |
| `render_backends` | 静态 re-export | 3* | 5/2 | 7/5 | 0 | W13 | 需先改写消费方 |
| `renderer` | 静态 re-export | 0* | 1/0 | 4/3 | 0 | W13 | 需先改写消费方 |
| `reviewer` | 静态 re-export | 1* | 1/1 | 0/1 | 0 | W13 | 需先改写消费方 |
| `roleplay` | 静态 re-export | 0* | 1/0 | 2/0 | 0 | W13 | 需先改写消费方 |
| `templates` | 静态 re-export | 0* | 0/3 | 4/0 | 0 | W13 | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `output.bot_avatar`：含根 __init__ 消费方→随子波 5；src 模块级 import 6 处；src 函数级 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py, plugins/bot_unified_runtime/domains/finance/capabilities/fx.py, plugins/bot_unified_runtime/domains/finance/capabilities/market.py, plugins/bot_unified_runtime/domains/finance/capabilities/stocks.py, plugins/bot_unified_runtime/domains/link_parse/capabilities/content_parser.py 等7文件
- `output.plain_text`：src 模块级 import 10 处；src 函数级 import 1 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/character/knowledge_service.py, plugins/bot_unified_runtime/control_plane/events.py, plugins/bot_unified_runtime/control_plane/workspaces.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/files/capabilities/download.py, plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py 等16文件
- `output.render_backends`：含根 __init__ 消费方→随子波 5；src 模块级 import 5 处；src 函数级 import 2 处；测试 import 12 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/monitor/error_report.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, scripts/e2e_acceptance.py, scripts/fetch_mermaid_js.py, scripts/measure_latency_chains.py 等18文件
- `output.renderer`：src 模块级 import 1 处；测试 import 7 处；消费方示例：plugins/bot_unified_runtime/output/__init__.py, tests/test_auditfix_sender_queue.py, tests/test_chat_and_sources_regressions.py, tests/test_forward_and_mood.py, tests/test_phase0_3_features.py, tests/test_poke_v2.py 等7文件
- `output.reviewer`：src 模块级 import 1 处；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/output/__init__.py, tests/test_phase0_3_features.py
- `output.roleplay`：src 模块级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_chat_and_sources_regressions.py, tests/test_roleplay_paragraphs.py
- `output.templates`：src 函数级 import 3 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/domains/link_parse/capabilities/content_parser.py, plugins/bot_unified_runtime/domains/music/capabilities/music.py, scripts/render_card_samples.py, tests/test_metric_labels.py, tests/test_mica_builders_contract.py, tests/test_phase_determinism.py 等7文件

### `…/output/card_render`（4 张；零消费 0；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `bridge` | 静态 re-export | 123* | 1/11 | 4/2 | 0 | W13 | 需先改写消费方 |
| `models` | 静态 re-export | 7* | 1/0 | 0/0 | 0 | W13 | 需先改写消费方 |
| `theme_tokens` | 静态 re-export | 53* | 0/2 | 3/1 | 0 | W13 | 需先改写消费方 |
| `usage_cards` | 静态 re-export | 19* | 0/1 | 3/0 | 0 | W13 | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `output.card_render.bridge`：src 模块级 import 1 处；src 函数级 import 11 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/finance/capabilities/fx.py, plugins/bot_unified_runtime/domains/finance/capabilities/market.py, plugins/bot_unified_runtime/domains/finance/capabilities/stocks.py, plugins/bot_unified_runtime/domains/ops/admin/debug.py 等14文件
- `output.card_render.models`：src 模块级 import 1 处；消费方示例：plugins/bot_unified_runtime/output/card_render/__init__.py
- `output.card_render.theme_tokens`：src 函数级 import 2 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/ops/admin/debug.py, tests/test_help_card_twocol.py, tests/test_render_card_samples.py, tests/test_usage_card.py, tests/test_usage_card_channels.py
- `output.card_render.usage_cards`：src 函数级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py, tests/test_phase_determinism_2.py, tests/test_usage_card.py, tests/test_usage_card_channels.py

### `…/runtime`（40 张；零消费 0；在飞 10）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `alerts` | PEP562 活转发 | 2 | 2/1 | 5/1 | 0 | RWOC | 在飞占域 |
| `aliases` | PEP562 活转发 | 2 | 3/2 | 4/1 | 0 | W15d | 需先改写消费方 |
| `base_router` | PEP562 活转发 | 2 | 5/3 | 21/11 | 0 | W15d | 需先改写消费方 |
| `cache_policy` | PEP562 活转发 | 2 | 0/13 | 0/0 | 0 | W15d | 需先改写消费方 |
| `capability_registry` | PEP562 活转发 | 2 | 1/0 | 1/1 | 0 | W15d | 需先改写消费方 |
| `content_route` | PEP562 活转发 | 2 | 4/1 | 3/0 | 0 | W15d | 需先改写消费方 |
| `deadline` | PEP562 活转发 | 2 | 3/0 | 2/0 | 0 | W15d | 需先改写消费方 |
| `disconnect_notice` | PEP562 活转发 | 2 | 1/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `divination_service` | 静态 re-export | 2* | 0/0 | 1/0 | 0 | W5 | 仅测试消费方 |
| `error_report` | PEP562 活转发 | 2 | 0/1 | 1/3 | 0 | RWOC | 在飞占域 |
| `event_idempotency` | PEP562 活转发 | 2 | 1/0 | 3/0 | 0 | W15d | 需先改写消费方 |
| `event_service` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `event_store` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `feature_catalog` | PEP562 活转发 | 2 | 1/0 | 1/4 | 0 | RWOC | 在飞占域 |
| `feature_gate` | PEP562 活转发 | 2 | 1/1 | 1/3 | 0 | RWOC | 在飞占域 |
| `fortune` | 静态 re-export | 1* | 0/0 | 1/0 | 0 | W5 | 仅测试消费方 |
| `group_cache` | PEP562 活转发 | 2 | 2/0 | 1/0 | 0 | W15d | 需先改写消费方 |
| `ingress` | PEP562 活转发 | 2 | 0/1 | 1/0 | 0 | W15d | 需先改写消费方 |
| `intent_telemetry` | PEP562 活转发 | 2 | 2/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `mentions` | PEP562 活转发 | 2 | 2/0 | 2/0 | 0 | W15d | 需先改写消费方 |
| `model_schedule` | PEP562 活转发 | 2 | 0/1 | 2/1 | 0 | W15b | 需先改写消费方 |
| `natural_language` | PEP562 活转发 | 2 | 1/1 | 4/1 | 0 | W15d | 需先改写消费方 |
| `parrot` | PEP562 活转发 | 2 | 1/0 | 1/0 | 0 | W15d | 需先改写消费方 |
| `pipeline` | PEP562 活转发 | 2 | 3/1 | 11/0 | 0 | W15d | 需先改写消费方 |
| `pricing` | PEP562 活转发 | 2 | 1/10 | 3/0 | 0 | W15b | 需先改写消费方 |
| `prompt_audit` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15d | 仅测试消费方 |
| `prompt_preview` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W15d | 仅测试消费方 |
| `question_intent` | PEP562 活转发 | 2 | 4/0 | 1/0 | 0 | W15d | 需先改写消费方 |
| `reactions` | 静态 re-export | 2* | 9/0 | 2/7 | 0 | W6 | 需先改写消费方 |
| `result_unknown` | PEP562 活转发 | 2 | 1/0 | 1/0 | 0 | RWOC | 在飞占域 |
| `schedule_dag` | 静态 re-export | 1* | 0/0 | 1/0 | 0 | W10 | 仅测试消费方 |
| `schedule_rrule` | 静态 re-export | 0* | 0/2 | 1/0 | 0 | W10 | 需先改写消费方 |
| `schedule_service` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W10 | 仅测试消费方 |
| `schedule_store` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W10 | 仅测试消费方 |
| `settings` | PEP562 活转发 | 2 | 6/4 | 12/11 | 0 | W15d | 需先改写消费方 |
| `tarot_draw` | 静态 re-export | 2* | 0/0 | 1/1 | 0 | W5 | 仅测试消费方 |
| `time_window` | PEP562 活转发 | 2 | 1/0 | 1/0 | 0 | W15d | 需先改写消费方 |
| `timesync` | 静态 re-export | 2* | 0/0 | 2/0 | 0 | W10 | 仅测试消费方 |
| `usage_monitor` | PEP562 活转发 | 2 | 0/1 | 3/1 | 0 | RWOC | 在飞占域 |
| `video_pipeline` | PEP562 活转发 | 2 | 10/0 | 0/0 | 0 | W11 | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `runtime.aliases`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；src 函数级 import 2 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/core/decision/shadow.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, scripts/extract_trigger_words.py, tests/test_model_admin_and_schedule.py 等10文件
- `runtime.base_router`：含根 __init__ 消费方→随子波 5；src 模块级 import 5 处；src 函数级 import 3 处；测试 import 32 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/core/decision/engine.py, plugins/bot_unified_runtime/domains/ops/monitor/error_report.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py, scripts/e2e_acceptance.py 等33文件
- `runtime.cache_policy`：src 函数级 import 13 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/affinity.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py, plugins/bot_unified_runtime/domains/files/sources/downloader.py, plugins/bot_unified_runtime/domains/finance/capabilities/fx.py, plugins/bot_unified_runtime/domains/finance/capabilities/market.py, plugins/bot_unified_runtime/domains/finance/capabilities/stocks.py 等11文件
- `runtime.capability_registry`：src 模块级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/ops/features/feature_catalog.py, tests/test_capability_registry.py, tests/test_runtime_feature_gate.py
- `runtime.content_route`：含根 __init__ 消费方→随子波 5；src 模块级 import 4 处；src 函数级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, scripts/probe_intimate_route.py, tests/test_content_route.py, tests/test_rp_style_directives.py, tests/test_v21r2_content_probe.py
- `runtime.deadline`：src 模块级 import 3 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/transport/sender/nonebot.py, plugins/bot_unified_runtime/domains/transport/sender/onebot.py, tests/test_bgroup_chat_pipeline.py, tests/test_deadline_budget.py
- `runtime.divination_service`：测试 import 1 处；消费方示例：tests/test_divination_service_v21.py
- `runtime.event_idempotency`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_a18_gate_idempotency_rollback.py, tests/test_event_idempotency.py, tests/test_soak_growth.py
- `runtime.fortune`：测试 import 1 处；消费方示例：tests/test_divination_service_v21.py
- `runtime.group_cache`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/group_info.py, tests/test_group_info.py
- `runtime.ingress`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_unified_gateways.py
- `runtime.mentions`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/policy/gate.py, tests/test_nickname_default_seed.py, tests/test_p1_hotspot_hygiene.py
- `runtime.model_schedule`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_auditfix_runtime_policy.py, tests/test_chat_and_sources_regressions.py, tests/test_model_admin_and_schedule.py
- `runtime.natural_language`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 1 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, scripts/extract_trigger_words.py, tests/test_moegirl_yield_fix.py, tests/test_natural_settings_nl.py, tests/test_traditional_triggers_2.py, tests/test_weather_statement_guard.py
- `runtime.parrot`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_parrot.py
- `runtime.pipeline`：src 模块级 import 3 处；src 函数级 import 1 处；测试 import 11 处；消费方示例：plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/runtime/__init__.py, plugins/bot_unified_runtime/runtime/loop_watchdog.py, scripts/e2e_acceptance.py, tests/test_a18_gate_idempotency_rollback.py, tests/test_a19_group_failure_notice.py 等15文件
- `runtime.pricing`：src 模块级 import 1 处；src 函数级 import 10 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, plugins/bot_unified_runtime/domains/ops/monitor/usage_monitor.py, tests/test_ledger_channel_breakdown.py, tests/test_model_effort_groups_and_pricing.py, tests/test_model_family_pricing.py
- `runtime.prompt_audit`：测试 import 1 处；消费方示例：tests/test_prompt_audit.py
- `runtime.prompt_preview`：测试 import 1 处；消费方示例：tests/test_prompt_preview.py
- `runtime.question_intent`：含根 __init__ 消费方→随子波 5；src 模块级 import 4 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/chat_reply/character/glossary.py, plugins/bot_unified_runtime/domains/ops/monitor/intent_telemetry.py, tests/test_sdd9_n3re.py
- `runtime.reactions`：含根 __init__ 消费方→随子波 5；src 模块级 import 9 处；测试 import 9 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_reaction_store.py, tests/test_reactions.py
- `runtime.schedule_dag`：测试 import 1 处；消费方示例：tests/test_schedule_service_v21.py
- `runtime.schedule_rrule`：src 函数级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/schedule/service/schedule_service.py, tests/test_schedule_service_v21.py
- `runtime.schedule_service`：测试 import 1 处；消费方示例：tests/test_schedule_service_v21.py
- `runtime.schedule_store`：测试 import 1 处；消费方示例：tests/test_schedule_service_v21.py
- `runtime.settings`：含根 __init__ 消费方→随子波 5；src 模块级 import 6 处；src 函数级 import 4 处；测试 import 23 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/_app.py, plugins/bot_unified_runtime/control_plane/config_service.py, plugins/bot_unified_runtime/control_plane/config_store.py, plugins/bot_unified_runtime/domains/chat_reply/character/relationship.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py 等26文件
- `runtime.tarot_draw`：测试 import 2 处；消费方示例：tests/test_divination_service_v21.py
- `runtime.time_window`：src 模块级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_time_window_summary.py
- `runtime.timesync`：测试 import 2 处；消费方示例：tests/test_timesync.py, tests/test_v21r2_stall_timesync_http.py
- `runtime.video_pipeline`：含根 __init__ 消费方→随子波 5；src 模块级 import 10 处；消费方示例：plugins/bot_unified_runtime/__init__.py

### `…/sender`（9 张；零消费 0；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `__init__` | 包静态 re-export | 0* | 8/1 | 9/1 | 31 | W14 | 需先改写消费方 |
| `file_gateway` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W14 | 仅测试消费方 |
| `gateway` | 静态 re-export | 0* | 0/1 | 1/0 | 0 | W14 | 需先改写消费方 |
| `nonebot` | 静态 re-export | 0* | 0/4 | 4/0 | 0 | W14 | 需先改写消费方 |
| `onebot` | 静态 re-export | 4* | 1/0 | 8/6 | 0 | W14 | 需先改写消费方 |
| `queue` | 静态 re-export | 0* | 1/2 | 18/8 | 0 | W14 | 需先改写消费方 |
| `receipts` | 静态 re-export | 0* | 0/0 | 2/1 | 0 | W14 | 仅测试消费方 |
| `timeout` | 静态 re-export | 0* | 1/1 | 1/0 | 0 | W14 | 需先改写消费方 |
| `worker` | 静态 re-export | 4* | 0/0 | 7/1 | 1 | W14 | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `sender`：含根 __init__ 消费方→随子波 5；src 模块级 import 8 处；src 函数级 import 1 处；字符串引用 31 文件；测试 import 10 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/pipeline/backend_unit.py, plugins/bot_unified_runtime/domains/chat_reply/runtime/pipeline.py, plugins/bot_unified_runtime/domains/ops/admin/debug.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/ops/smoke/route_demo.py 等18文件
- `sender.file_gateway`：测试 import 2 处；消费方示例：tests/test_f03_notice_redaction.py, tests/test_file_gateway_phase1.py
- `sender.gateway`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_unified_gateways.py
- `sender.nonebot`：含根 __init__ 消费方→随子波 5；src 函数级 import 4 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_f03_notice_redaction.py, tests/test_file_gateway_phase1.py, tests/test_nonebot_sender.py, tests/test_operational_failures.py
- `sender.onebot`：src 模块级 import 1 处；测试 import 14 处；消费方示例：plugins/bot_unified_runtime/domains/ops/smoke/smoke.py, tests/test_a03_timeout_retry_semantics.py, tests/test_chat_and_sources_regressions.py, tests/test_deadline_budget.py, tests/test_file_gateway_phase1.py, tests/test_media_rejection_retry_and_fallback.py 等15文件
- `sender.queue`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；测试 import 26 处；消费方示例：plugins/bot_unified_runtime/__init__.py, scripts/e2e_acceptance.py, tests/test_a03_timeout_retry_semantics.py, tests/test_a19_group_failure_notice.py, tests/test_a20_sender_session_order.py, tests/test_a22_inline_claim_race.py 等21文件
- `sender.receipts`：测试 import 3 处；消费方示例：tests/test_operational_failures.py, tests/test_perf_hotpath.py, tests/test_prfix_sender.py
- `sender.timeout`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/transport/sender/file_gateway.py, tests/test_transport_timeout.py
- `sender.worker`：字符串引用 1 文件；测试 import 8 处；消费方示例：tests/test_a03_timeout_retry_semantics.py, tests/test_a20_sender_session_order.py, tests/test_a22_inline_claim_race.py, tests/test_media_rejection_retry_and_fallback.py, tests/test_operational_failures.py, tests/test_part_idempotent_resume.py 等7文件

### `…/sources`（55 张；零消费 8；在飞 9）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `bond_data` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W7 | 仅测试消费方 |
| `campus_store` | 静态 re-export | 0* | 0/1 | 1/0 | 0 | W12 | 需先改写消费方 |
| `commodities_data` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W7 | 仅测试消费方 |
| `credential_health` | PEP562 活转发 | 2 | 1/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `credentials` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `downloader` | 静态 re-export | 1* | 3/6 | 5/0 | 0 | W9 | 需先改写消费方 |
| `draw_store` | 静态 re-export | 1* | 0/0 | 0/0 | 0 | W5 | 可直接退役 |
| `epicfree` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W8 | 可直接退役 |
| `file_reader` | 静态 re-export | 0* | 1/2 | 0/5 | 0 | W9 | 需先改写消费方 |
| `finance_chart` | 静态 re-export | 2* | 0/1 | 1/0 | 0 | W7 | 需先改写消费方 |
| `food_data` | 静态 re-export | 0* | 0/0 | 1/1 | 0 | W4 | 仅测试消费方 |
| `fx_data` | 静态 re-export | 0* | 0/0 | 1/1 | 0 | W7 | 仅测试消费方 |
| `ganzhi` | 静态 re-export | 2* | 0/0 | 2/0 | 0 | W5 | 仅测试消费方 |
| `gscore_bridge` | PEP562 活转发 | 2 | 0/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `iching` | 静态 re-export | 2* | 0/0 | 1/0 | 0 | W5 | 仅测试消费方 |
| `market_crosscheck` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W7 | 可直接退役 |
| `market_data` | 静态 re-export | 2* | 0/0 | 6/6 | 0 | W7 | 仅测试消费方 |
| `mcp_web_search_server` | PEP562 活转发 | 2 | 0/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `media_archive` | PEP562 活转发 | 2 | 0/1 | 0/0 | 0 | W11 | 需先改写消费方 |
| `mediawiki` | PEP562 活转发 | 2 | 0/0 | 0/1 | 0 | W16 | 仅测试消费方 |
| `meme_library` | 静态 re-export | 0* | 2/0 | 1/0 | 1 | W6 | 需先改写消费方 |
| `meme_library_listener` | 静态 re-export | 0* | 1/1 | 0/0 | 0 | W6 | 需先改写消费方 |
| `meme_search` | 静态 re-export | 2* | 3/0 | 2/0 | 0 | W6 | 需先改写消费方 |
| `moegirl` | PEP562 活转发 | 2 | 0/1 | 0/0 | 0 | W16 | 需先改写消费方 |
| `multi_calendar` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W5 | 仅测试消费方 |
| `music_charts` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W2 | 仅测试消费方 |
| `music_normalization` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W2 | 仅测试消费方 |
| `music_request_store` | 静态 re-export | 0* | 1/0 | 2/0 | 0 | W2 | 需先改写消费方 |
| `news_feeds` | 静态 re-export | 1* | 0/0 | 2/1 | 0 | W8 | 仅测试消费方 |
| `nmc_weather` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W3 | 可直接退役 |
| `open_meteo` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W3 | 可直接退役 |
| `parse_history` | 静态 re-export | 0* | 2/1 | 0/0 | 0 | W1b | 需先改写消费方 |
| `reaction_store` | 静态 re-export | 0* | 1/0 | 1/0 | 0 | W6 | 需先改写消费方 |
| `registry` | 静态 re-export | 4* | 1/0 | 3/0 | 0 | W1b | 需先改写消费方 |
| `runtime_event_log` | PEP562 活转发 | 2 | 0/2 | 3/3 | 0 | RWOC | 在飞占域 |
| `sauce_search` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | W11 | 仅测试消费方 |
| `search_api` | PEP562 活转发 | 2 | 1/3 | 1/0 | 0 | RWOC | 在飞占域 |
| `search_service` | PEP562 活转发 | 2 | 0/4 | 1/0 | 0 | RWOC | 在飞占域 |
| `search_smoke` | PEP562 活转发 | 2 | 0/0 | 0/0 | 1 | RWOC | 在飞占域 |
| `steamfree` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W8 | 可直接退役 |
| `stock_data` | 静态 re-export | 1* | 0/0 | 4/3 | 0 | W7 | 仅测试消费方 |
| `subscription_migration` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W8 | 仅测试消费方 |
| `subscription_runtime_v2` | 静态 re-export | 0* | 0/1 | 7/0 | 0 | W8 | 需先改写消费方 |
| `subscription_scheduler` | 静态 re-export | 0* | 0/0 | 10/0 | 0 | W8 | 仅测试消费方 |
| `subscription_store` | 静态 re-export | 0* | 0/0 | 2/0 | 12 | W8 | 需先改写消费方 |
| `subscription_store_v2` | 静态 re-export | 0* | 0/0 | 13/0 | 0 | W8 | 仅测试消费方 |
| `subscription_watcher` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W8 | 可直接退役 |
| `tarot` | 静态 re-export | 1* | 0/0 | 2/0 | 0 | W5 | 仅测试消费方 |
| `telegram_media` | PEP562 活转发 | 2 | 1/0 | 0/0 | 0 | W11 | 需先改写消费方 |
| `today_history` | 静态 re-export | 0* | 0/1 | 3/1 | 0 | W8 | 需先改写消费方 |
| `transcribe` | PEP562 活转发 | 2 | 1/2 | 1/0 | 0 | W11 | 需先改写消费方 |
| `url_cleaner` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1b | 可直接退役 |
| `video_understanding` | PEP562 活转发 | 2 | 0/2 | 1/1 | 0 | W11 | 需先改写消费方 |
| `vision_describe` | PEP562 活转发 | 2 | 1/9 | 2/1 | 0 | W11 | 需先改写消费方 |
| `web_search` | PEP562 活转发 | 2 | 3/3 | 3/4 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
- `sources.bond_data`：测试 import 2 处；消费方示例：tests/test_bond_data.py, tests/test_market_fin_phase1.py
- `sources.campus_store`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_campus_digest.py
- `sources.commodities_data`：测试 import 2 处；消费方示例：tests/test_commodities_data.py, tests/test_market_fin_phase1.py
- `sources.downloader`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；src 函数级 import 6 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/food/capabilities/eat.py, plugins/bot_unified_runtime/domains/link_parse/parsers/ssrf_guard.py, plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py, plugins/bot_unified_runtime/domains/media/ingest/transcribe.py, plugins/bot_unified_runtime/domains/media/ingest/video_understanding.py 等14文件
- `sources.file_reader`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；测试 import 5 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/api/platform.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_phase0_3_features.py, tests/test_runtime_subfeatures.py, tests/test_v21_risk_red_tz_and_files.py
- `sources.finance_chart`：src 函数级 import 1 处；测试 import 1 处；消费方示例：scripts/render_card_samples.py, tests/test_finance_charts.py
- `sources.food_data`：测试 import 2 处；消费方示例：tests/test_auditfix_wave3_resources.py, tests/test_prfix_eat.py
- `sources.fx_data`：测试 import 2 处；消费方示例：tests/test_fx_data.py, tests/test_user_copy_unification_gate.py
- `sources.ganzhi`：测试 import 2 处；消费方示例：tests/test_divination.py, tests/test_sdd7_n4.py
- `sources.iching`：测试 import 1 处；消费方示例：tests/test_divination.py
- `sources.market_data`：测试 import 12 处；消费方示例：tests/test_bond_data.py, tests/test_commodities_data.py, tests/test_finance_market_expansion.py, tests/test_market_backoff.py, tests/test_market_card.py, tests/test_market_fin_phase1.py 等9文件
- `sources.media_archive`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py
- `sources.mediawiki`：测试 import 1 处；消费方示例：tests/test_phase0_3_features.py
- `sources.meme_library`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；字符串引用 1 文件；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, scripts/e2e_acceptance.py, tests/test_meme_domain_fixes.py
- `sources.meme_library_listener`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py
- `sources.meme_search`：含根 __init__ 消费方→随子波 5；src 模块级 import 3 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, tests/test_chat_and_sources_regressions.py, tests/test_outdomain_fixes_20260911.py
- `sources.moegirl`：src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/sources/acg_search.py
- `sources.multi_calendar`：测试 import 1 处；消费方示例：tests/test_multi_calendar.py
- `sources.music_charts`：测试 import 2 处；消费方示例：tests/test_music_charts_real_sources_v2.py, tests/test_music_charts_v2.py
- `sources.music_normalization`：测试 import 1 处；消费方示例：tests/test_music_backend_v2.py
- `sources.music_request_store`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_music_analytics_v2.py, tests/test_music_capability_analytics_v2.py
- `sources.news_feeds`：测试 import 3 处；消费方示例：tests/test_news.py, tests/test_sdd7_n4.py, tests/test_user_copy_unification_gate.py
- `sources.parse_history`：含根 __init__ 消费方→随子波 5；src 模块级 import 2 处；src 函数级 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, scripts/e2e_acceptance.py
- `sources.reaction_store`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_reaction_store.py
- `sources.registry`：src 模块级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/sources/__init__.py, tests/test_content_video_auto_send.py, tests/test_p1_hotspot_hygiene.py, tests/test_parser_ssrf_guard.py
- `sources.sauce_search`：测试 import 1 处；消费方示例：tests/test_batch_cdf_modules.py
- `sources.stock_data`：测试 import 7 处；消费方示例：tests/test_finance_data.py, tests/test_finance_market_expansion.py, tests/test_stock_data.py, tests/test_stock_technical_indicators.py
- `sources.subscription_migration`：测试 import 1 处；消费方示例：tests/test_subscription_v2_core.py
- `sources.subscription_runtime_v2`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 7 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_music_subscription_removed_platforms_j06_v2.py, tests/test_subscribe_capability_v2.py, tests/test_subscribe_platform_switch_j02.py, tests/test_subscription_runtime_delivery_v2.py, tests/test_subscription_runtime_v2.py 等8文件
- `sources.subscription_scheduler`：测试 import 10 处；消费方示例：tests/test_auditfix_subscriptions_capabilities.py, tests/test_music_subscription_routing_v2.py, tests/test_outdomain_fixes_20260911.py, tests/test_subscribe_platform_switch_j02.py, tests/test_subscription_async_sqlite.py, tests/test_subscription_context_v2.py 等10文件
- `sources.subscription_store`：字符串引用 12 文件；测试 import 2 处；消费方示例：tests/test_audit_fixes_b.py, tests/test_subscribe_capability_bridge.py
- `sources.subscription_store_v2`：测试 import 13 处；消费方示例：tests/test_audit_fixes_b.py, tests/test_auditfix_subscriptions_capabilities.py, tests/test_music_subscription_routing_v2.py, tests/test_reaudit_20260911.py, tests/test_subscribe_platform_switch_j02.py, tests/test_subscription_async_sqlite.py 等13文件
- `sources.tarot`：测试 import 2 处；消费方示例：tests/test_divination.py, tests/test_divination_service_v21.py
- `sources.telegram_media`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py
- `sources.today_history`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/__init__.py, tests/test_card_prune.py, tests/test_feature_cards.py, tests/test_production_wiring.py
- `sources.transcribe`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/api/platform.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_voice_media_routing.py
- `sources.video_understanding`：src 函数级 import 2 处；测试 import 2 处；消费方示例：plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, tests/test_video_understanding.py
- `sources.vision_describe`：含根 __init__ 消费方→随子波 5；src 模块级 import 1 处；src 函数级 import 9 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/control_plane/api/platform.py, plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py, plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py, plugins/bot_unified_runtime/policy/gate.py, scripts/clean_food_gallery.py 等9文件

### `…/sources/fetchers`（3 张；零消费 1；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `__init__` | 包静态 re-export | 2* | 0/1 | 0/0 | 1 | W1b | 需先改写消费方 |
| `playwright_backend` | 静态 re-export | 0* | 1/0 | 0/0 | 0 | W1b | 需先改写消费方 |
| `xhs_sign` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1b | 可直接退役 |

退役前置（本目录有消费方垫片）：
- `sources.fetchers`：含根 __init__ 消费方→随子波 5；src 函数级 import 1 处；字符串引用 1 文件；消费方示例：plugins/bot_unified_runtime/__init__.py
- `sources.fetchers.playwright_backend`：src 模块级 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/subscribe/adapters/xiaohongshu_adapter.py

### `…/sources/parsers`（37 张；零消费 28；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `__init__` | 包静态 re-export | 14* | 6/4 | 14/3 | 32 | W1b | 需先改写消费方 |
| `context` | 静态 re-export | 0* | 0/0 | 2/0 | 0 | W1b | 仅测试消费方 |
| `cookies` | 静态 re-export | 1* | 2/1 | 2/1 | 0 | W1b | 需先改写消费方 |
| `http_util` | 静态 re-export | 0* | 15/3 | 13/0 | 1 | W1b | 需先改写消费方 |
| `image_stitch` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1b | 可直接退役 |
| `platform_login` | 静态 re-export | 0* | 0/6 | 0/0 | 0 | W1b | 需先改写消费方 |
| `platforms_acfun` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_allcpp` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_bilibili` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_bilibili_goods` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_community` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_discourse` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_douban` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_epic` | 静态 re-export | 1* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_facebook` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_generic` | 静态 re-export | 3* | 0/0 | 1/1 | 0 | W1a | 仅测试消费方 |
| `platforms_github` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_huajia` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_kuaishou` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_kurobbs` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_lofter` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_media_share` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_mihuashi` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_miyoushe` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_moegirl` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_music` | 静态 re-export | 1* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_pixiv` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_skland` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_steam` | 静态 re-export | 1* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_taptap` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_telegram` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_weibo` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_xiaoheihe` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `platforms_zhihu` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W1a | 可直接退役 |
| `ssrf_guard` | 静态 re-export | 0* | 2/0 | 1/0 | 0 | W1b | 需先改写消费方 |
| `types` | 静态 re-export | 0* | 0/0 | 0/1 | 0 | W1b | 仅测试消费方 |
| `wbi` | 静态 re-export | 0* | 1/0 | 1/0 | 0 | W1b | 需先改写消费方 |

退役前置（本目录有消费方垫片）：
- `sources.parsers`：含根 __init__ 消费方→随子波 5；src 模块级 import 6 处；src 函数级 import 4 处；字符串引用 32 文件；测试 import 17 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/__init__.py, plugins/bot_unified_runtime/domains/files/capabilities/download.py, plugins/bot_unified_runtime/domains/music/capabilities/music.py, plugins/bot_unified_runtime/domains/ops/smoke/console_chat.py, plugins/bot_unified_runtime/domains/subscribe/adapters/bilibili_adapter.py, plugins/bot_unified_runtime/domains/subscribe/capabilities/subscribe.py 等24文件
- `sources.parsers.context`：测试 import 2 处；消费方示例：tests/test_parser_v2_boundary.py, tests/test_telegram_parser_v2.py
- `sources.parsers.cookies`：src 模块级 import 2 处；src 函数级 import 1 处；测试 import 3 处；消费方示例：plugins/bot_unified_runtime/domains/core/credentials/platform_credentials.py, plugins/bot_unified_runtime/domains/subscribe/adapters/social_v2.py, plugins/bot_unified_runtime/security/memory_sanitize.py, tests/test_auditfix_parsers.py, tests/test_datafix_runtime_paths.py, tests/test_platform_credentials.py
- `sources.parsers.http_util`：src 模块级 import 15 处；src 函数级 import 3 处；字符串引用 1 文件；测试 import 13 处；疑似 LEGAL 配对→双侧同波同步（RW8 先例）；消费方示例：plugins/bot_unified_runtime/domains/core/credentials/platform_credentials.py, plugins/bot_unified_runtime/domains/location/capabilities/moegirl.py, plugins/bot_unified_runtime/domains/location/data/mediawiki.py, plugins/bot_unified_runtime/domains/location/data/moegirl.py, plugins/bot_unified_runtime/domains/music/data/music_charts.py, plugins/bot_unified_runtime/domains/subscribe/adapters/bilibili_adapter.py 等29文件
- `sources.parsers.platform_login`：src 函数级 import 6 处；消费方示例：plugins/bot_unified_runtime/domains/core/credentials/platform_credentials.py
- `sources.parsers.platforms_generic`：测试 import 2 处；消费方示例：tests/test_douyin_topics.py, tests/test_media_quality_port.py
- `sources.parsers.ssrf_guard`：src 模块级 import 2 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/core/search/search_service.py, tests/test_parser_ssrf_guard.py
- `sources.parsers.types`：测试 import 1 处；消费方示例：tests/test_parser_contract_migration_v2.py
- `sources.parsers.wbi`：src 模块级 import 1 处；测试 import 1 处；消费方示例：plugins/bot_unified_runtime/domains/subscribe/adapters/bilibili_adapter.py, tests/test_auditfix_parsers.py

### `…/sources/subscriptions`（6 张；零消费 2；在飞 0）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `__init__` | 包静态 re-export | 5* | 0/0 | 0/0 | 10 | W8 | 需先改写消费方 |
| `bilibili_adapter` | 静态 re-export | 0* | 0/0 | 0/0 | 0 | W8 | 可直接退役 |
| `music_v2` | 静态 re-export | 0* | 0/1 | 6/0 | 0 | W8 | 需先改写消费方 |
| `social_v2` | 静态 re-export | 2* | 0/1 | 4/0 | 0 | W8 | 需先改写消费方 |
| `target_notice` | 静态 re-export | 1* | 0/0 | 0/0 | 0 | W8 | 可直接退役 |
| `xiaohongshu_adapter` | 静态 re-export | 0* | 0/0 | 1/0 | 0 | W8 | 仅测试消费方 |

退役前置（本目录有消费方垫片）：
- `sources.subscriptions.music_v2`：src 函数级 import 1 处；测试 import 6 处；消费方示例：plugins/bot_unified_runtime/domains/subscribe/adapters/__init__.py, tests/test_music_subscription_netease_v2.py, tests/test_music_subscription_removed_platforms_j06_v2.py, tests/test_music_subscription_routing_v2.py, tests/test_music_subscription_sources_v2.py, tests/test_music_subscription_v2.py
- `sources.subscriptions.social_v2`：src 函数级 import 1 处；测试 import 4 处；消费方示例：plugins/bot_unified_runtime/domains/subscribe/adapters/__init__.py, tests/test_auditfix_subscriptions_capabilities.py, tests/test_twitter_subscription_graphql_v2.py, tests/test_twitter_subscription_registration_j01_v2.py
- `sources.subscriptions.xiaohongshu_adapter`：测试 import 1 处；消费方示例：tests/test_platform_deepening_b7_fixtures.py

### `…/supervisor`（6 张；零消费 0；在飞 6）

| 垫片（短名） | 形态 | 转出名 | src 模/函 | test 模/函 | 串引用 | 波 | 判定 |
|---|---|---|---|---|---|---|---|
| `acl_windows` | PEP562 活转发 | 2 | 0/0 | 0/1 | 0 | RWOC | 在飞占域 |
| `appcontainer_windows` | PEP562 活转发 | 2 | 0/0 | 0/1 | 0 | RWOC | 在飞占域 |
| `ipc` | PEP562 活转发 | 2 | 0/0 | 2/0 | 0 | RWOC | 在飞占域 |
| `job_objects` | PEP562 活转发 | 2 | 0/0 | 0/1 | 0 | RWOC | 在飞占域 |
| `sandbox_windows` | PEP562 活转发 | 2 | 0/0 | 0/0 | 0 | RWOC | 在飞占域 |
| `windows_sandbox` | PEP562 活转发 | 2 | 0/0 | 1/0 | 0 | RWOC | 在飞占域 |

退役前置（本目录有消费方垫片）：
-（本目录全部为零消费/在飞，无前置）

## 6. 疑似 LEGAL 配对清单（拆除须双侧同步）

- `capabilities.auto_send`：src 函数级 2 处；测试旧路补丁文件：tests/test_auditfix_wave3_logic.py, tests/test_traditional_triggers_2.py
- `capabilities.content_parser`：src 函数级 9 处；测试旧路补丁文件：tests/test_eat_image_quality.py
- `capabilities.subscribe`：src 函数级 2 处；测试旧路补丁文件：tests/test_auditfix_subscriptions_capabilities.py, tests/test_music_subscription_removed_platforms_j06_v2.py, tests/test_reaudit_20260911.py, tests/test_subscribe_capability_v2.py, tests/test_subscribe_platform_switch_j02.py, tests/test_twitter_subscription_registration_j01_v2.py
- `character.memory`：src 函数级 1 处；测试旧路补丁文件：tests/test_memory_service_v21.py, tests/test_sdd7_n4.py, tests/test_v21_teaching_service.py
- `llm.providers`：src 函数级 1 处；测试旧路补丁文件：tests/test_control_plane_log_collectors.py
- `sender`：src 函数级 1 处；测试旧路补丁文件：tests/test_a03_timeout_retry_semantics.py, tests/test_a19_group_failure_notice.py, tests/test_a20_sender_session_order.py, tests/test_a22_inline_claim_race.py, tests/test_auditfix_sender_queue.py, tests/test_bgroup_sender_delivery.py, tests/test_chat_and_sources_regressions.py, tests/test_control_plane_log_collectors.py, tests/test_deadline_budget.py, tests/test_f03_notice_redaction.py, tests/test_media_rejection_retry_and_fallback.py, tests/test_mermaid_reply_render.py, tests/test_nonebot_sender.py, tests/test_onebot_chunk_budget_floor.py, tests/test_operational_failures.py, tests/test_part_idempotent_resume.py, tests/test_perf_hotpath.py, tests/test_phase0_3_features.py, tests/test_poke_v2.py, tests/test_prfix_sender.py, tests/test_queue_poison_row.py, tests/test_soak_growth.py, tests/test_startup_queue_warning.py, tests/test_transport_timeout.py, tests/test_tts_outbound_chain.py, tests/test_unified_gateways.py, tests/test_v21r2_hotzone_notice_chain.py, tests/test_v21r2_hotzone_quiet_silence.py, tests/test_v21r2_lifecycle_r2.py
- `sources.parsers`：src 函数级 4 处；测试旧路补丁文件：tests/test_auditfix_subscriptions_capabilities.py, tests/test_commodities_data.py, tests/test_datafix_runtime_paths.py, tests/test_finance_market_expansion.py, tests/test_market_github.py, tests/test_media_quality_port.py, tests/test_moegirl_search.py, tests/test_parser_ssrf_guard.py, tests/test_parser_v2_boundary.py, tests/test_platform_credentials.py, tests/test_search_service_v21.py, tests/test_subscription_live_column_kinds.py, tests/test_twitter_subscription_graphql_v2.py, tests/test_v21r2_acg_search.py, tests/test_weather_alerts_b10.py
- `sources.parsers.http_util`：src 函数级 3 处；测试旧路补丁文件：tests/test_auditfix_subscriptions_capabilities.py

## 7. 高消费垫片 TOP15（退役收益=需改写量）

| 垫片 | src 模/函 | test 模/函 | 判定 |
|---|---|---|---|
| `capabilities.chat` | 7/2 | 18/26 | 需先改写消费方 |
| `contracts.media` | 33/2 | 11/1 | 在飞占域 |
| `capabilities.echo` | 2/8 | 16/15 | 需先改写消费方 |
| `llm.model_router` | 5/22 | 10/4 | 需先改写消费方 |
| `runtime.base_router` | 5/3 | 21/11 | 需先改写消费方 |
| `capabilities.user_copy` | 24/0 | 10/1 | 需先改写消费方 |
| `runtime.settings` | 6/4 | 12/11 | 需先改写消费方 |
| `contracts.subscription` | 9/0 | 22/1 | 在飞占域 |
| `sources.parsers.http_util` | 15/3 | 13/0 | 需先改写消费方 |
| `sender.queue` | 1/2 | 18/8 | 需先改写消费方 |
| `character.providers` | 1/12 | 4/10 | 需先改写消费方 |
| `sources.parsers` | 6/4 | 14/3 | 需先改写消费方 |
| `character.affinity` | 1/5 | 14/3 | 需先改写消费方 |
| `capabilities.music` | 7/4 | 8/3 | 需先改写消费方 |
| `contracts.finance` | 3/0 | 6/13 | 在飞占域 |

---
*机核快照 2026-09-18 EP1 席；脚本/JSON 存 %TEMP%（v21r2-ep1-shim-inventory.py/.json），重跑可复现。本文件为施工图，不含任何退役动作。*