# v21r2 重组日志 — RWC5 席（chat_reply 子波 5/5 = 根 `__init__.py` 装配收尾·惰性导入切换）

- 日期：2026-09-18；席位=RWC5；占域=根 `plugins/bot_unified_runtime/__init__.py` + 域包 `__init__.py` 的旧路径惰性导入切换（独占窗口）。
- 禁触面遵守情况：S14b（domains/ops/recovery+incident+collectors）、AFF（affinity_replay）、LEG（纯文档）、ACC（domains/ops/acceptance）、RWOCb 在飞域零触碰；未 commit；零 git 写操作。
- 固定解释器：`ChatBot_Runtime/venv/Scripts/python.exe`；env `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=%TEMP%/v21r2-rwc5` `-p no:cacheprovider`；未用 dev.ps1。

## 1. 波前取证（AST 机核，零人工转录）

脚本三件（%TEMP%/v21r2-rwc5/：scan_root_imports.py / classify_shims.py / switch_list2.py + repls.json）：

1. **全量 import 点盘点**（根 init + 全部 domains/**/__init__.py）：329 个旧路径 import 名点（根 init 324 = 180 惰性名点 + 144 模块级名点；域包 init 5 = link_parse/parsers 3 + subscribe/adapters 2）。
2. **旧模块形态分类**（125 个 distinct 旧路径模块）：
   - **PEP562 活转发垫片 62**（W11/W16/RWC1-RWC4 升格形态）→ 调用期惰性 from-import 经 `__getattr__` 实时解析 canonical，测试 canonical 补丁天然可见 → **按简报「不过度切换」验证后保留**（46 名 is 同对象冒烟 + 全批 keyword 回归佐证）。
   - **静态 re-export 垫片 49**（`from canonical import *` + 显式私名转出，W2-W14 形态）→ 惰性消费点存在快照分裂/退役阻塞 → **全部切换**。
   - **真身未迁 14**（contracts/audit/control_plane/policy/security/runtime(包中继)/loop_watchdog/config 等）→ 旧路径即唯一真路径 → 保留。
3. **垫片解耦数**：静态惰性消费点 40 处（根 init 38 + 域包 init 2），涉 26 个静态垫片模块 → 全部切至 canonical 后 **AST 终验 STATIC-lazy 残余=0**（26 垫片的根惰性消费边清零；模块级消费 50 名点按简报范围不动，归退役波）。

## 2. 切换清单（40 点，全 AST 定位 + 精确文本替换 + 计数断言 + 复扫验证）

根 `__init__.py` 38 点（旧行号→canonical）：

| 旧行 | 函数 | 旧模块 | canonical |
|---|---|---|---|
| 438-440 | _writer | character.reminders | domains.schedule.store.reminders |
| 471 | _is_plain_chat_text | capabilities.auto_send | domains.schedule.auto_send |
| 1218 | _incoming_from_nonebot_event | sources.file_reader | domains.files.sources.file_reader |
| 1504 | transport 内 | sender.nonebot | domains.transport.sender.nonebot |
| 1660-1663 | _register_today_history_scheduler | capabilities.today_history（_load_push_table+工厂） | domains.subscribe.capabilities.today_history |
| 1664 | 同上 | sources.today_history（TodayHistoryProvider） | domains.subscribe.feeds.today_history |
| 2030 / 2051 | _refresh_local_bot_avatar / _resolve_bot_avatar_url | output.bot_avatar ×2 | domains.render.bot_avatar |
| 2106-2109 | _cached_content_parser_registry | sources.parsers | domains.link_parse.parsers |
| 2311 / 2312 | _deliver_transport_send_request | sender.gateway / sender.nonebot | domains.transport.sender.gateway / …nonebot |
| 2738 | _deliver_due_reminders | character.reminders | domains.schedule.store.reminders |
| 3047 / 3114 | _build_meal_push_text / _run_daily_assist_meal_push | character.daily_assist ×2 | domains.assistant.daily.store.daily_assist |
| 3305 | _register_nonebot_handlers | capabilities.auto_send | domains.schedule.auto_send |
| 3336-3345 | 同上 | mail_bridge 8 名 | domains.transport.mail.mail_bridge |
| 3355 | 同上 | sender（包垫片，build_send_queue） | domains.transport.sender |
| 3418 / 3419 | 同上 | capabilities.campus / sources.campus_store | domains.assistant.campus.campus / …campus_store |
| 3431 / 3455 / 3640 | 同上/_deliver_admin_alert | sender.nonebot / sender.queue | domains.transport.sender.* |
| 3759-3761 | _log_bot_connect | sources.meme_library_listener | domains.meme.sources.meme_library_listener |
| 3988 | _register_nonebot_handlers | sources.subscription_runtime_v2 | domains.subscribe.store.subscription_runtime_v2 |
| 4020 | _deliver_v2_event | capabilities.content_parser | domains.link_parse.capabilities.content_parser |
| 4263 | 同上 | sources.fetchers | domains.link_parse.fetchers |
| 4586-4591 / 5109 | _register_nonebot_handlers / _handle_admin_file_export | capabilities.file_exchange ×2 | domains.files.capabilities.file_exchange |
| 5821+7901 / 5975 | _handle_alias/_handle_natural/_handle_music_mode | capabilities.music ×3 | domains.music.capabilities.music |
| 5855+6009 | capability/_handle_standalone_subscribe | capabilities.subscribe ×2 | domains.subscribe.capabilities.subscribe |
| 5856+6010+6563 | 同上 | capabilities.subscribe_v2 ×3 | domains.subscribe.capabilities.subscribe_v2 |
| 5882+7881 | _handle_alias/_handle_natural | capabilities.meme_library ×2 | domains.meme.capabilities.meme_library |

域包 init 2 点：`domains/subscribe/adapters/__init__.py:89-94`（build_subscription_registry_v2 内）`sources.subscriptions.music_v2/social_v2` → `domains.subscribe.adapters.music_v2/social_v2`（域内兄弟直连）。

**执行安全**：每模式替换前 count 断言（捕获并修正两处缩进子串包含陷阱：indent-4 模式曾误中 indent-8 行→改 `\n` 锚定精确缩进匹配）；应用后 AST 复扫 STATIC-lazy=0（ruff --fix 后三复扫同结果）。

**前置验证**：26 canonical 模块 × 46 名运行时 import+getattr 全存在；垫片名↔canonical 名 `is` 同一 46/46（切换语义=补丁可见性变化，唯一变化面）。

## 3. 同波测试改写（AST 耦合扫描 + 红点驱动盲区补扫）

耦合扫描器（setattr 字符串式/对象式，最长前缀匹配）首轮命中 2：
- `tests/test_production_wiring.py:333-340`：旧垫片对象补丁 `capabilities.today_history.build_today_history_capability` / `sources.today_history.TodayHistoryProvider` × root 懒导入同源（RW12 留验对）→ 按 RW13 双侧同波切 canonical（import 与 mp.setattr 靶同步改 `domains.subscribe.capabilities/feeds.today_history`）。

红点驱动补抓「包级 from-import 绑定旧垫片子模块×setattr」盲区形态（首轮扫描器盲区，教训同 W6/W15）2 处：
- `tests/test_runtime_subfeatures.py:107`：`from ...sources import file_reader` 绑垫片再 setattr `read_supported_file`（root:1217 消费名）→ 改绑 `domains.files.sources` 真身。
- `tests/test_cookie_import_hot_reload.py:19`：`from ...sources import parsers as parsers_module` 再 setattr build_content_parser_registry/build_cookie_provider（root:2105 消费名）→ 改绑 `domains.link_parse.parsers`。
- 补扫全 tests/ 该形态：其余命中均为非本波切换集模块（onebot_sender/render_backends_module/metrics/fx_data 等），零本波耦合。

## 4. 回归（全实跑）

| 门 | 结果 |
|---|---|
| 插件导入冒烟（nonebot.init→import 插件） | OK ×2（切换后+ruff 后各一） |
| 垫片同一性 | 46 名 `is` 同对象 0 分裂 ×2 |
| 全库收集 | 8122 collected，0 收集错 |
| 批A（切换相邻 13 文件：production_wiring/reminder×2/todo_checkoff/daily_assist×2/campus/mail_bridge/file_exchange/phase0_3/runtime_subfeatures/risk_red/cookie_reload） | **163 passed**（修 2 盲区后） |
| 批B（宽域 29 文件：sender/music/subscribe 族/meme/parser/today_history） | **334 passed** |
| 关键词全库扫測（chat|poke|event|hotzone|reminder|subscribe|music|meme|avatar|file_*|parser|daily_assist|campus|mail|auto_send|today_history|cookie） | **1331 passed / 3 skipped / 1 failed**（唯一红=test_parsers_batch_a2 discourse，见 §5 偏差①） |
| ruff（5 触达文件） | 12 I001 --fix 自愈 → **All checks passed** |
| mypy 权威口径（--explicit-package-bases --ignore-missing-imports plugins，689 文件） | **2 错全 control_plane/api/platform.py:79/:254 既有基线（台账 #36）**，本波 0 新增 |
| verify_hashes --check | **exit 0** |
| doc_sync + no_source_tree_data_writes + p1_hotspot_hygiene | **26 passed** |
| runtime-layout | FAIL=BOT_KNOWLEDGE_FILES 两外部用户文件缺失（RW5/RW9-RW16 十席同款环境项，非代码） |
| 源文本锚测试核查 | 5 个读根 init 源码的测试（documentation_consistency/runtime_subfeatures SOURCE/runtime_feature_gate/unified_delivery_routes/traditional_triggers_2）断言面均为 capability_id/触发词/函数体，与 import 行零交集；tests/scripts 对被切 import 行文本锚 0 命中 |

## 5. 偏差与移交（如实登记）

1. **关键词轮唯一红** `test_parsers_batch_a2::test_discourse_linuxdo_parses_topic`：外部真实样本目录 `C:/Users/LancyCelestia/Downloads/Archives/nonebot-plugin-parser-lite-1.3.5/api_txt` 当前缺失→`_HAS=False` 走 fallback 样本（posts_count=3→comment_count=2）vs 硬编码 6848。=RW8 log 已登记「discourse 真实样本指 Downloads 外部目录缺失」环境型既有红同款；本波零交集（测试直绑 canonical，不经根 init 惰性点），移交环境面/该测试属主波。
2. **保留不动面（按简报「不过度切换」）**：PEP562 活转发垫片惰性点 79 名点（活转发天然透传，identity 冒烟佐证）+ 真身未迁 14 模块（contracts/control_plane/policy/security 等）+ 模块级旧路径消费（含静态 50 名点）→ 静态垫片模块级消费点仍存，**该 26 张解耦垫片的「可直接退役」仍需退役波处理模块级消费方与其余 src/test 消费边**（EP1 清单 §2 判定规则不变）。
3. `domains/link_parse/parsers/__init__.py:17` 3 处模块级 `contracts.media` 旧路 import=RWOC 在飞占域（清单 §2.4 不得代拆）+模块级非本波范围 → 保留已登记。
4. ruff --fix 顺带自愈触达文件内 12 处 I001（含把本波部分单行 import 规范为括号形态）；AST 复扫+冒烟+批测试三重复核语义等价。

## 6. 收尾补录

- 树卫生终验：见 §7 追加；qx.json 完好性：见 §7 追加。
- COORDINATION.md 已追加本席一行。
- 未 commit（共享工作树，提交裁决权在用户）；重启生效（根 init 为装配文件，bot 进程须重启加载）。
