# v21r2 重组 W8（subscribe 域）执行日志 — RW12 席（2026-09-18）

> 席位：RW12（板块重组执行·第 12 波）。认领波次：**W8 subscribe（21 件）**——按 COORDINATION 实况取序列下一无冲突波（RW8=W1b link_parse、RW9=notes+files、RW10=schedule、RW11=media 在飞；RW13=assistant、RW14=render 及 location 席后至）。热区 transport/chat_reply/ops/core 零触碰。禁 git 写操作，全程未 commit。

## 一、移动清单（21 件，文件系统 mv，真身零内容改动——仅 import 路径 canonical 化）

| 目标 | 件 | 明细 |
|---|---|---|
| `domains/subscribe/capabilities/` | 5 | subscribe、subscribe_v2、news、epic、today_history |
| `domains/subscribe/adapters/` | 6 | sources/subscriptions/{__init__,social_v2,bilibili_adapter,xiaohongshu_adapter,music_v2,target_notice}（目录删除后旧位重建垫片包） |
| `domains/subscribe/store/` | 6 | subscription_{store,store_v2,scheduler,watcher,migration,runtime_v2} |
| `domains/subscribe/feeds/` | 4 | news_feeds、epicfree、steamfree、today_history |
| 包 init 新建 | 5 | 域根 + 四子包 docstring-only（既有域同风格） |

**真身 import canonical 化 20 处**：域内互指 19 处（capabilities→store/adapters/feeds、store 三兄弟链 runtime_v2→scheduler/store_v2/migration、adapters 互指 social_v2↔music_v2/target_notice/bilibili/xiaohongshu）+ 跨域 canonical 1 处（feeds/today_history.py:138 懒导入 `from .multi_calendar import` → `domains.divination.data.multi_calendar`，W5 真身）。
**保旧路径不动**（在飞兼容，W1b/W15e 接管再迁）：`sources.parsers.{http_util,cookies,wbi}`、`sources.fetchers.playwright_backend`、`capabilities.user_copy`、`capabilities.content_parser`（epic.py:66、today_history.py:189 懒导入）；`contracts.subscription`（W16 core）绝对路径天然不动。

## 二、垫片（21 张，re-export 薄壳）

形如 `"""Compat shim: moved to … (v21r2 reorg W8)."""` + `import *` + 显式转出。**显式转出名 8+2 类**：
- `capabilities/today_history.py`：`_load_push_table`（根 `__init__.py:1660` 懒导入！）、`_save_push_table`、`_load_push_table_checked`（test_today_history_robustness）
- `sources/news_feeds.py`：`_FEEDS`（test_sdd7_n4）
- `sources/subscriptions/social_v2.py`：`_run_legacy_coroutine`、`_reached_cursor`（真身内部/测试跨界）
- `capabilities/epic.py`：`_format_games`；`capabilities/subscribe_v2.py`：`_normalize`（AST 终验抓回的人工清单漏检，见 §四）
- `sources/subscriptions/target_notice.py`：`__all__` 再转出
- `sources/subscriptions/__init__.py` 垫片：除 `import *` 外显式转出**五个子模块对象**（social_v2/bilibili_adapter/xiaohongshu_adapter/music_v2/target_notice），保证 `from 旧包 import social_v2` 拿到真身模块对象（isinstance/monkeypatch 同一性）。
- `subscription_watcher.py`：全库零外部消费（孤儿模块），照迁照垫。

## 三、补丁命中测试同波改写（10 文件）

| 文件 | 改动 |
|---|---|
| test_news.py | `from sources import news_feeds` → `domains.subscribe.feeds`；3 处字符串补丁 `capabilities.news.fetch_headlines` → 新路径 |
| test_subscription_live_column_kinds.py | 2 个 import 块（social_v2/xiaohongshu_adapter 模块对象）→ adapters 新路径 |
| test_social_subscription_fetch_v2.py | 2 个 import 块 → 新路径 |
| test_social_subscription_adapters_v2.py | 头部 + 3 处函数内 `from …subscriptions import social_v2` → 新路径 |
| test_outdomain_fixes_20260911.py | bilibili_adapter/social_v2 import 块 → 新路径 |
| test_epic_card.py | 2 处 f-string 补丁前缀 → `domains.subscribe.capabilities.epic.` |
| test_music_subscription_sources_v2.py / test_music_subscription_netease_v2.py | 2+1 处字符串补丁 → `domains.subscribe.adapters.music_v2.` |
| test_card_prune.py | `import …capabilities.today_history as today_history_module` → 真身路径（W5 divination_module 同款） |
| test_user_copy_unification_gate.py | FILE_WHITELIST 2 锚（subscribe/subscribe_v2）随迁指真身，理由保留改注「v21r2 W8 随迁指真身」（真身 3 处「没有权限操作该订阅」Q02 命中实证=资源属主语义白名单必需） |

**零改留验**：`test_production_wiring.py`（pytest.MonkeyPatch 打旧路径 cap_module/src_module 模块对象 × 消费方根 `__init__.py:1660/1664` 同走旧路径懒导入）——垫片期两侧同源，补丁语义自洽，实跑通过。
**W1b 移交项**：`test_auditfix_subscriptions_capabilities.py:316` 字符串补丁 `sources.parsers.http_util.http_get_json`（消费者=本域 adapters，http_get_json 名绑定在 social_v2 真身模块）——W1b 迁 http_util 时必须同波改指新路径，否则打垫片不进真身。

## 四、事故与教训

1. **adapters `__init__` 覆写事故**：`mv sources/subscriptions/__init__.py → adapters/` 后建包 init 的 docstring printf 把 99 行 pkgutil 发现注册表**覆写**。发现于导入冒烟（build_subscription_registry ImportError）。工作树该文件无未提交改动（git status 实证）→ `git show HEAD:…` 恢复，99 行核验一致。教训：**mv 进目标含同名 init 时先落 init 内容再 mv，或 mv 后 init 只许追加**。
2. **单点懒导入盲区**：波前 grep `\.\.|bot_unified_runtime` 只抓双点相对+绝对导入，`from .multi_calendar import`（feeds/today_history.py:138，函数内懒导入）漏网 → 7 红抓到。AST ImportFrom level≥1 全扫后确认全 21 件仅此一处。**方法论增补：波前扫描必须 AST 化（含 level=1 与函数内 ImportFrom）**。
3. **W6 教训①重演**：`_normalize`（test_traditional_triggers_2）/`_format_games`（test_auditfix_wave3_logic）人工清单漏检 → 收集期 ImportError。AST 名字级扫描 + 程序化 hasattr 核对补齐。
4. **多行 setattr 盲区**：字符串补丁在 `setattr(` 下一行，单行正则首轮漏报（test_news/test_epic_card/test_music_* 共 8 处）——展开调用点后全部清零。

## 五、终验与回归（全部实跑）

| 门 | 结果 |
|---|---|
| 波前基线（43 引用测试文件） | **629 passed** |
| 域回归终轮（同 43 文件） | **629 passed，0 failed**（与基线逐数一致） |
| 插件导入冒烟 | OK（mail_adapter ResilientMailAdapter + 5 子模块对象 `is` 同一性 + 私有名同一性断言） |
| AST 终验 | 字符串式补丁目标旧路径残留 **0**；15 模块 × 40 转出名程序化 hasattr 核对 **NONE-missing** |
| 全库收集扫 | tests 全量 collect-only **7781 项零收集错** |
| ruff（本波改动面） | 全绿（--fix 收 34 处 I001/RUF100，均为 import 排序） |
| mypy（权威口径 `--explicit-package-bases --ignore-missing-imports plugins`） | **547 文件，2 错** = control_plane/api/platform.py:79/254 既有（多席台账在案）；本域 0 新增 |
| verify_hashes --check | exit 0 |
| doc_sync + no_data_writes | 9 passed |
| runtime-layout | 唯一 FAIL = BOT_KNOWLEDGE_FILES 两份库街区百科 .md 用户目录缺失（RW5 已登记的环境项，非代码，提请用户） |
| 树卫生 | 0 缓存残留；qx.json 完好在 `domains/weather/assets/`（W3 位） |

## 六、并行席瞬态与协调记录（全部退避自愈，零越域）

- **W1b（RW8）parsers 窗**：sources/parsers 与 domains/link_parse/parsers 短暂双全量在盘。
- **location 席（未留名）**：moegirl/wiki 移动中垫片未落 → 根 `__init__.py` import 断裂，全库收集 42 错瞬态；90s 退避后自愈。
- **W14 transport 席**：`domains/transport/extensions/__init__.py` W-PA5 占位含全角括号 SyntaxError → 阻断全量 mypy 与 user_copy 门（gate rglob 撞语法错）；等待其自行修复（已修）后两门复跑全绿。
- RW13 assistant / RW14 render / location 波与热区文件本席零触碰。

## 七、遗留与移交

1. **→ W1b（RW8）**：test_auditfix_subscriptions_capabilities.py:316 http_util 字符串补丁（见 §三）。
2. **→ W15e/尾声**：capabilities/user_copy.py 与 content_parser 的旧路径引用（本域 4 文件保旧路径）随其域波改指真身。
3. **→ 尾声波**：本域 21 张垫片退役统计（惯例全保留不设截止）。
4. `subscription_watcher.py` 孤儿模块（build_subscription_watcher 全库零消费）——建议立项评估是否休眠登记，本波照迁未处置。

未 commit（共享工作树，提交裁决权在用户）；重启生效面=无（纯模块迁移，生产 bot 重启后才加载新路径语义，垫片期旧语义不变）。
