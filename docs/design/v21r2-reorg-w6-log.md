# v21r2 重组 W6 meme 域施工日志（RW6 席）

> 波次：W6 meme（方案书 §5 表：移动量 8，冲突面小；前提「reaction_store/reactions 同波（R-18 批已收口）」已核实成立，#36 批已收口）。
> 状态：**完成**（全门禁实跑收口，见 §四终态列）。
> 纪律：零 git 写操作；固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=%TEMP%/v21r2-rw6 -p no:cacheprovider`；禁 dev.ps1。

## 一、波前取证（全部实跑）

### 1.1 域内 8 件与 WIP 态（git status 实证）

| 真身（旧路径） | 行数 | 波前 git 态 | 新路径 |
|---|---|---|---|
| capabilities/meme.py | 413 | 干净 | domains/meme/capabilities/meme.py |
| capabilities/meme_library.py | 241 | 干净 | domains/meme/capabilities/meme_library.py |
| capabilities/randpic.py | 166 | 干净 | domains/meme/capabilities/randpic.py |
| sources/meme_search.py | 341 | 干净 | domains/meme/sources/meme_search.py |
| sources/meme_library.py | 271 | 干净 | domains/meme/sources/meme_library.py |
| sources/meme_library_listener.py | 322 | **M**（他席 WIP 随迁保留） | domains/meme/sources/meme_library_listener.py |
| sources/reaction_store.py | 154 | **??**（#35 批未跟踪新文件随迁） | domains/meme/sources/reaction_store.py |
| runtime/reactions.py | 776 | **M**（#35/#36 批 WIP 随迁保留） | domains/meme/reactions/engine.py（§2.2 映射名 engine） |

### 1.2 全量 from-import 扫描（W2 教训执行：非已知名检索，而是全 import 行×关键词）

**生产侧旧路径消费（全部走垫片零改动）**：
- 根 `__init__.py`：L47/L48/L65（三 capability）、L139-163（`from .runtime.reactions import` ×9 多行括号式，18 个公开名）、L207/L208/L209/L220（四 sources）、惰性 L3733（backfill_meme_tags_loop）、L5783/L7782（meme_library capability）。
- `runtime/base_router.py` L58/L59/L71（is_meme_command / is_meme_library_command / is_randpic_command）。
- `capabilities/chat.py` L98（MemeSearchProvider/NullMemeSearchProvider/extract_meme_query；**chat.py=W15e 热区，本席零触碰**，旧路径经垫片）。
- `console_chat.py` L106、`route_demo.py` L21、`scripts/e2e_acceptance.py` L88/L93/L137。
- `runtime/capability_registry.py` 实读确认=纯数据声明表（模块 docstring 明言「只声明数据，不 import 包内任何模块」），("MEME","meme") 等是声明行非 importlib 路径 → 零风险零改动。
- `decision/shadow.py:153`、`capabilities/echo.py:2790` 均为 capability-id 字符串，非模块路径。

**测试侧消费（垫片覆盖零改动 22 文件 + 波内改写 4 文件）**：`test_meme_conflict_fix / test_meme_image_input / test_meme_domain_fixes / test_randpic_identity / test_randpic_scan_cache_l10 / test_reaction_store / test_reactions / test_traditional_news_randpic / test_poke_unified_reaction_b10 / test_chat_and_sources_regressions / test_outdomain_fixes_20260911 / test_perf_p3 / test_ratchet_fix / test_sdd7_n4 / test_trigger_english / test_traditional_triggers_2` 等。

### 1.3 monkeypatch 命中清单（波内改写=4 文件 10 行，全部对象式补丁打模块别名）

| 文件:行 | 补丁目标 | 改写 |
|---|---|---|
| test_meme_domain_fixes.py:73 | `meme_lib_mod._COOLDOWN_CAP` | L18 import 改指 `domains.meme.capabilities.meme_library` |
| test_meme_domain_fixes.py:161 | `meme_store_mod._PICK_SCAN_LIMIT` | L30 import 改指 `domains.meme.sources.meme_library` |
| test_meme_domain_fixes.py:196 | `meme_library_listener._download_once` | L31 import 改指 `domains.meme.sources.meme_library_listener` |
| test_perf_p3.py:169/197 | `listener._download_once`/`._segment_urls`（×2 处 import） | L161/L189 import 改指 `domains.meme.sources.meme_library_listener` |
| test_randpic_scan_cache_l10.py:39/64/86 | `randpic._SCAN_CACHE`（×3） | L17 import 改指 `domains.meme.capabilities.randpic` |
| test_randpic_identity.py:44/57/66/98 | `randpic._SCAN_CACHE`（×4） | L42/L55/L64/L96 函数级 import 改指真身（L12 公开名 import 留旧路径经垫片） |

垫片不可服务的对象式补丁语义（R1 Critical）：补丁打垫片模块命名空间，真身函数查自身模块全局 → 必须改指真身。

**下划线名全树外引清单（垫片显式转出，测试零改动）**：`_collect_image_sources`（meme；test_meme_image_input:10）、`_extract_ddg_items`+`_CACHE_MAX_ENTRIES`（meme_search；test_outdomain_fixes:82/91/95 模块对象属性访问）、`_REACTION_LRU_CAP`（reactions；test_reactions:659 from-import）。其余（_SCAN_CACHE/_COOLDOWN_CAP/_PICK_SCAN_LIMIT/_download_once/_segment_urls）仅 monkeypatch 打点文件消费→已同波改指真身，垫片不转出。

### 1.4 文件路径式加载锚（垫片无法覆盖的一类）

`scripts/import_meme_packs.py:46` `spec_from_file_location` 按文件路径加载 meme_library（刻意绕开包 __init__ 的 NoneBot 依赖——加载垫片反而会触发全包 import）→ **同波改指真身** `domains/meme/sources/meme_library.py`（W3 pre_restart_check qx 锚同款处置），docstring 口径同步。无测试锚定该脚本（rg 实证零命中）。

### 1.5 其他取证结论

- 8 件真身**零相对导入、零相互依赖**（meme.py:355 惰性 import runtime/cache_policy 属 W15d 域未动，旧路径继续有效）；**零 `__file__`/`parents[]` 深度锚**（W2 教训项不适用）；**零 `__all__`**（`import *` 全公开名转发）。
- `bot.py` 仅涉外部 nonebot_plugin_memes 插件（无关）；conftest 无关；verify_hashes/cross_validate/doc_sync/auto-facts 对本波 8 件零路径锚（auto-facts 仅 RouteKind 枚举名）。
- 门禁预判：渲染契约不跑（未触 plain_text/roleplay/模板）；command_catalog --write 不跑（未触 echo/config，RW4 先例）。

## 二、移动与垫片（已落地）

- `mkdir -p domains/meme/{capabilities,sources,reactions}`；8 件 `mv` 迁入（§1.1 表）。
- 4 个包 `__init__.py`（单行 docstring，同 W2/W3/W4 房屋风格）。
- 8 张 re-export 垫片：`capabilities/{meme,meme_library,randpic}.py`、`sources/{meme_search,meme_library,meme_library_listener,reaction_store}.py`、`runtime/reactions.py`；其中 3 张带下划线显式转出（meme→_collect_image_sources；meme_search→_extract_ddg_items/_CACHE_MAX_ENTRIES；runtime/reactions→_REACTION_LRU_CAP），5 张纯 `import *`。
- 波内测试改写 4 文件 10 行（§1.3 表）；脚本锚改写 1 处（§1.4）。

## 三、AST 终验（W1a 教训执行：程序化扫描替代正则）

自研 AST 扫描器（%TEMP%/v21r2_rw6_ast_scan.py，tests+scripts+bot.py+plugins 全树 824 文件）：
- 模块别名绑定跟踪（Import/ImportFrom 绝对+相对+包级子模块三形态）→ setattr/patch 目标解析；
- **SETATTR_PATCH_HITS=0**（对象式+字符串式全盲区清零）；
- legal_old_path_imports_via_shim=88（垫片期合法消费，尾声波退役统计对象）；
- string_const_refs=8（全部=垫片自身 docstring，预期内）。

## 四、回归门禁矩阵（终态，全部实跑）

| # | 门 | 结果 |
|---|---|---|
| 1 | AST 终验（837 文件，改写后+终态两次） | ✅ SETATTR_PATCH_HITS=0；legal_old_path_imports_via_shim=88（尾声波退役统计对象）；string_const_refs=8（全为垫片自身 docstring） |
| 2 | 插件导入+8 垫片同一性冒烟 | ✅ 根包+mail_adapter 断言+18 个 reactions 名+全部消费名 `is` 同一性全过 |
| 3 | 域测试 | ✅ 关键词广域（meme\|randpic\|reaction）**439 passed**；显式 16 消费文件 **413 passed**（修复下划线漏转出后复跑全绿） |
| 4 | verify_hashes --check | ✅ exit=0（移动前后两跑） |
| 5 | doc_sync 门禁 | ✅ 4 passed |
| 6 | runtime_layout + no_source_tree_data_writes + 树卫生 | ✅ layout PASS（两跑）；no_data_writes 5 passed；源码树 0 缓存目录/0 data 残留 |
| 7 | ruff 本波改动面（25 文件） | ✅ All checks passed（1 处 I001 import 排序 --fix 收口后复跑全绿） |
| 8 | mypy（dev.ps1 同口径 `--explicit-package-bases --ignore-missing-imports plugins`，cache 置 %TEMP% 不触 Runtime） | ✅ 本域 0 新增；全量 424 文件 5 错全外部归因：control_plane/api/platform.py ×2（R1/R4 席同报既有）+ capabilities/chat.py ×3（**chat.py=工作树 M 态他席 WIP**，WebSearchHit sources/contracts 类型分歧，与本波 8 件零交集；web_search.py/contracts 本体干净） |
| 9 | import_meme_packs 真身加载探针 | ✅ spec_from_file_location 直载新路径 MemeLibraryStore 成功（文件路径锚修正实证） |
| 10 | 路径文本锚门 test_user_copy_unification_gate（RW7 移交 q04 红 + Q03 作用域随迁） | ✅ 四处协同改锚随真身迁（§六-5）后 **12 passed**+ruff 绿 |
| — | dev.ps1 全量门 | 不跑（席位禁令）；渲染契约不跑（未触 output/）；command_catalog --write 不跑（未触 echo/config，RW4 先例） |

## 五、并行席事件簿（瞬态阻断归因，非本波断点）

- 冒烟首跑炸 `capabilities.fx` 缺失：W7 finance 席 mv→垫片写入间隙的瞬态窗口（S8/R3 席先例同款），20s 退避后 fx 垫片已由 W7 席回填。
- 二跑炸 `domains.link_parse.parsers.http_util` 缺失：W7 真身链（finance/capabilities/market.py→finance/data/market_data.py:40）前向引用 **W1b 范围产物**（sources/parsers/http_util.py 仍在旧位，ls 实证）——插件根包暂不可导入；本席域互斥零触碰，45s 退避轮询后 W7 席自行改回旧路径引用、树自愈（ROOT IMPORT OK），依赖导入门禁随即全部补跑收口。
- 同期 W5 divination 席 domains/divination/ 亦在盘（未阻断导入）。

## 六、偏差与移交

1. **波内一红一根修（方法论升级）**：`_REACTION_FALLBACK_INTENTS`（test_reactions.py:333/617 函数级 from-import 经垫片）波前人工核对私有名时漏检→域测试红抓到。根修=新增 **AST 名字级全量扫描**（对全树「从旧路径 import 的全部名字」对照真身符号面，非仅 setattr 目标）——实证全树经旧路径索求的私有名共 5 个，4 个已转发、1 个补转即清零。**移交后席：垫片下划线转出清单必须用名字级 AST 扫描产出，人工核对不可靠。**
2. mypy 裸跑（无 --explicit-package-bases）报「Source file found twice」假错——必须复刻 dev.ps1 同口径三旗；cache 置 %TEMP%（席位不触 Runtime/cache）。
3. WIP 随迁保留：runtime/reactions.py(M)、meme_library_listener.py(M)、reaction_store.py(??) 按 #35/#36 批在飞态原样随迁，本席零内容改动。
4. 零 git 写操作、未 commit（提交裁决权在用户）；工作树新增=4 包 init+8 垫片（新文件），移动 8 件=git 视角删旧增新。
5. **RW7 移交 q04 红点复核定性（纠偏）**：RW7 判「RW6 垫片在飞落盘的内容锚定碰撞（瞬态）」——实跑复核证伪：test_user_copy_unification_gate 对 meme_library 真身做**路径文本锚定**（q04 四条 `in` 断言 + Q03_SCOPE_FILES 作用域含 randpic/meme_library + Q03_UNIT_WHITELIST 键 + L410 白名单机制自测 rel_path 实参四处），移动后扫垫片=正断言必红（q04）且防回潮静默失效（Q03）。按 §5 第 4 步「路径锚定门禁波内同步」四处协同改锚随真身迁（改写含 W6 注记），实跑 12 passed+ruff 绿。**移交后席**：①weather 垫片同类遗留（W3 未同步 Q03 作用域，扫垫片防回潮已静默失效）登记待 W15d 或尾声波收口；②此类「对插件源码做文本断言」的门（user_copy_gate 型）是垫片期系统性盲区，各域迁移时应 rg `read_text`+旧路径清点。
