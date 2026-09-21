# v21r4-B RET3 席日志——垫片退役第三梯队（epic/steam 对 + 仅测试消费 44 张）

- 席位：RET3（2026-09-18 开工，断点续跑）；施工图=`docs/design/v21r2-shim-retirement-inventory.md`（EP1 机核快照 §2 规则 2「仅测试消费方」44 张 + RET1 移交的 `sources.parsers.platforms_epic/steam` 2 张）。
- 方法（沿 RET1/RET2 先例）：①逐张复验消费方（AST+rg 双轨）→②消费方（仅 tests/）改指 canonical→③AST 验证零残余→④备份至 `%TEMP%/v21r4-ret3-backup/<相对路径>` 后删垫片→⑤域回归实跑。
- 前置：`tests/test_datafix_runtime_paths.py` 动态 import（`__import__(f"plugins.bot_unified_runtime.sources.parsers.{module_name}")`）先改指 canonical 再删 epic/steam。
- 冲突裁定：消费方若落在在飞席域（根 __init__.py 装配段/domains/chat_reply/character/ 装配面/control_plane api/domains/schedule/store/reminders.py）→ 跳过记「在飞冲突挂起」。EP1 快照中本梯队 44 张均无根 __init__ 消费标记，与 RWC5 依赖面零交集（逐张复验仍会再核）。
- 纪律：固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/v21r4-ret3 -p no:cacheprovider -q`；零 git 写操作；未 commit（提交裁决权在用户）。

## 一、复验（改前）

（待填）

## 二、批次台账

（待填）

## 三、终验与移交

（待填）
### 批1（11 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | sources/parsers/{platforms_epic,platforms_steam,context,platforms_generic,types}.py、sources/subscriptions/xiaohongshu_adapter.py、character/{draw_store,persona_service,temporal,trend,worldbook_service}.py |
| 前置 | tests/test_datafix_runtime_paths.py:151 动态 import 前缀改 `domains.link_parse.parsers.{module_name}`（RET1 移交代办清账） |
| 改写 | 13 测试文件消费方→canonical（含 platforms_generic 父绑定 1 处）；复验三轨（AST+rg+动态拼接）确认 46 张零 src 消费、消费面全在 tests/ |
| AST 零残余 | 批1 11 张退役后重扫=0（除垫片自指 docstring 随删消失） |
| 备份 | `%TEMP%/v21r4-ret3-backup/plugins/bot_unified_runtime/<相对路径>`（11 件，字节级核验后删） |
| 回归 | 13 文件 `pytest --basetemp=$TEMP/v21r4-ret3/b1`：**148 passed**（10.17s） |
| ruff | 改写致 5 文件 I001（canonical 字典序变化）→ ruff --fix 仅限本席 5 文件后 All checks passed + 5 文件复跑 80 passed；另 2 处存量红（test_phase_determinism I001 / test_v21r3_visual_gates UP033）非本席触碰面=在飞席遗留，未动 |
### 批2（13 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | llm/{billing_entities,billing_pricing,billing_service,usage_service}.py、runtime/{divination_service,fortune,prompt_audit,prompt_preview,schedule_dag,schedule_service,schedule_store,tarot_draw,timesync}.py |
| 改写 | 8 测试文件（billing×4、divination_service_v21、prompt_audit、prompt_preview、schedule_service_v21、timesync×2 父绑定 `from …runtime import timesync`→`domains.schedule.timesync import timesync`） |
| AST 零残余 | 批2 13 张重扫=0 |
| 备份 | `%TEMP%/v21r4-ret3-backup/`（13 件，字节核验后删） |
| 回归 | 8 文件：**204 passed**（14.23s） |
| ruff | 4 文件 I001 → --fix 后 All checks passed；4 文件复跑通过 |
### 批3（10 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | backend_unit.py、capabilities/auto_send/parser.py、sender/{file_gateway,receipts}.py、sources/{bond_data,commodities_data,food_data,fx_data,market_data,stock_data}.py |
| 改写 | 23 测试文件（含 fx_data/news_feeds 双绑定拆分 2 行、market_data 父绑定改 `domains.finance.data import market_data`） |
| AST 零残余 | 批3 10 张重扫=0 |
| 备份 | `%TEMP%/v21r4-ret3-backup/`（10 件，字节核验后删） |
| 回归 | 23 文件：585 passed/2 skipped/1 failed → failed=`test_user_copy_unification_gate::test_scope_covers_sources_layer`（门禁钉住已删垫片文件 `sources/market_data.py` 作扫描面代表）→ 按同波规则改钉 canonical `domains/finance/data/market_data.py`（带注释）→ 该文件复跑 **12 passed**，批3合计全绿 |
| ruff | 15 文件 17 处 I001 → --fix 后 0 残余；受影响 15 文件复跑 **418 passed/2 skipped** |
| 备注 | 批2 复跑时曾现 2 个瞬态收集错误，b2fix2/b2fix3 立即复跑均 115 passed（无代码变化）——定性=与在飞席位的文件读写瞬态竞争，非本席 import 破坏（同文件集此前 204 passed 铁证在案） |
### 批4（12 张，2026-09-18）

| 项 | 内容 |
|---|---|
| 退役 | sources/{ganzhi,iching,mediawiki,multi_calendar,music_charts,music_normalization,news_feeds,sauce_search,subscription_migration,subscription_scheduler,subscription_store_v2,tarot}.py |
| 改写 | 24 测试文件（news_feeds 消费面已随批3 的 fx_data/news_feeds 拆分提前指 canonical，本批零冲突） |
| AST 零残余 | 批4 12 张重扫=0 |
| 备份 | `%TEMP%/v21r4-ret3-backup/`（12 件，字节核验后删） |
| 回归 | 24 文件：**331 passed**（18.33s） |
| ruff | 8 文件 10 处 I001 → --fix 后 0 残余；复跑 **138 passed** |

## 二、退役总清单（46/46，与 EP1 快照「仅测试消费方 44」+ RET1 移交 epic/steam 对完全对齐）

- **批1（11）**：sources/parsers/{platforms_epic,platforms_steam,context,platforms_generic,types}、sources/subscriptions/xiaohongshu_adapter、character/{draw_store,persona_service,temporal,trend,worldbook_service}
- **批2（13）**：llm/{billing_entities,billing_pricing,billing_service,usage_service}、runtime/{divination_service,fortune,prompt_audit,prompt_preview,schedule_dag,schedule_service,schedule_store,tarot_draw,timesync}
- **批3（10）**：backend_unit、capabilities/auto_send/parser、sender/{file_gateway,receipts}、sources/{bond_data,commodities_data,food_data,fx_data,market_data,stock_data}
- **批4（12）**：sources/{ganzhi,iching,mediawiki,multi_calendar,music_charts,music_normalization,news_feeds,sauce_search,subscription_migration,subscription_scheduler,subscription_store_v2,tarot}
- **备份位置**：`%TEMP%/v21r4-ret3-backup/plugins/bot_unified_runtime/<原相对路径>`（46 件，删除前字节级比对核验；另有批1 首次 cp 的 11 件短路径同内容副本在备份根，冗余无害）
- **在飞冲突挂起：0 张**（复验实证 46 张零 src 消费方，消费面全在 tests/，与根 __init__/chat_reply/character 装配面/control_plane api/schedule store reminders 四在飞域零交集）

## 三、终验（全部实跑）

| 门 | 结果 |
|---|---|
| AST 全库终扫（plugins+tests+scripts+bot.py，绝对/相对 import+父绑定+字符串+f-string） | 46 旧路径引用 **0**；46 垫片文件在盘 **0** |
| 域回归 | 批1 148 passed；批2 204 passed；批3 585+12 passed（门禁件修复后）；批4 331 passed；ruff 修复面复跑 80+115+418+138 passed——**合计零回归** |
| 全库 collect-only | **8403 collected / 0 error**（`pytest --collect-only -q --basetemp=$TEMP/v21r4-ret3/collect -p no:cacheprovider`） |
| `python -m ruff check .` | **本席全部触碰面（68 测试文件）全绿**；全库余 24 处 I001 全数落在本席**从未触碰**的文件（canonical 真身 chat/echo/backend_unit/persona_service/pipeline、ops smoke 族、divination/facet、e2e_acceptance、capability_protocols、10 个他席测试文件）=**在飞席位并发编辑 WIP**，本席不代修防冲突；其中 `tests/test_auditfix_main_character.py` 为本席修净后被在飞席新增 import 再弄脏，已再次修复+复跑 11 passed |
| `python scripts/doc_sync.py --check` | 首跑红→复跑 **EXIT=0 绿**（瞬态：他席在飞期读写窗口；六项受管事实=模板清单/RouteKind/topic 数/测试文件数/config 字段数/哈希清单范围，本席零触碰——46 张删除全在 plugins/ 非事实项，测试文件零增删）；本席未执行 --write |
| `python scripts/command_catalog.py --check` | **current (77 topics)** ✓ |
| `python tests/verify_hashes.py --check` | 红（15 项漂移），**零项涉本席**：15 项全落 render 域（card_render templates×7/theme_tokens/bridge/usage_cards/templates.py）+docs/rendering-contract.md+DESIGN-SPEC.md+ops/admin/debug.py+chat_reply/capabilities/echo.py=他席在飞面；**按禁令未自行 --write，移交合流波重录** |
| 树卫生 | plugins/tests/scripts 下 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache` 零残留；无游离 `data/`；qx.json canonical 位完好（`domains/weather/assets/qx.json`，2527 区县码，362774 字节）；全程 basetemp=%TEMP% 隔离 |
| git | 零写操作；未 commit（共享工作树，提交裁决权在用户） |

## 四、语义修正件（同波消费方修复，非纯路径替换）

1. `tests/test_user_copy_unification_gate.py::test_scope_covers_sources_layer`——门禁钉住已删垫片文件作「sources 层在扫描面内」代表 → 改钉 canonical `domains/finance/data/market_data.py`（附注释）。
2. `tests/test_datafix_runtime_paths.py` 动态 import 前缀 `sources.parsers.{module_name}` → `domains.link_parse.parsers.{module_name}`（RET1 移交代办清账；epic/steam `_cookie_file_candidates` 在真身原生定义，语义等价）。

## 五、诚实声明

以上全部为**离线测试实跑证据**；「垫片已退役」=源码树文件删除+全库引用清零，**不等于生产生效**——生产进程未重启、未部署，遵循项目铁律（改码须重启 bot 才生效；代码补丁待审不自动部署）。EP1 快照时代基线 8122→本次 8403 collected 的增量全部来自并行在飞席位新增测试，与本席无关。

（RET3 席完）
