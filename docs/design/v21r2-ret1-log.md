# v21r2 RET1 席日志——垫片退役第一梯队（零消费方可直接退役）

- 席位：RET1（2026-09-18）；施工图=`docs/design/v21r2-shim-retirement-inventory.md`（EP1 机核快照 §4「可直接退役 41 张」）。
- 结论：**复验 41 → 退役 39，剔除 2（移交第二梯队），回退 0**。未 commit（共享工作树，提交裁决权在用户）。

## 一、退役前复验（三轨，防 EP1 快照后新增消费）

1. **AST 全库扫**（plugins+tests+scripts+根 .py）：绝对/相对 import 解析 + 父绑定（`from <旧父包> import <垫片短名>`）+ 子模块边 + 字符串常量 + f-string 静态段 → 41 张旧路径消费边 **0**（命中 5 条全为垫片自指 docstring/`_CANONICAL`）。
2. **rg 行级扫**：旧路径模块名全库 → 仅垫片自指。
3. **拼接动态 import 专项 AST 扫**（`bot_unified_runtime.sources/character.` 前缀 + 变量拼接）→ 全库唯一命中：`tests/test_datafix_runtime_paths.py:143-154` 以 `__import__(f"plugins.bot_unified_runtime.sources.parsers.{module_name}")` 动态消费 `platforms_epic`/`platforms_steam`（parametrize 两值）。**此为 EP1 声明盲区「拼接字符串动态 import」的实锤实例**（EP1 对这两张记 串引用=0）。

**剔除裁定**：`sources.parsers.platforms_epic`、`sources.parsers.platforms_steam` 消费方≠0，按纪律不移交本梯队；其垫片内下划线符号 re-export 注释（W1a「动态旧路径消费者 test_datafix_runtime_paths」）与此互证。留待第二梯队「同波改写该测试动态 import 指 canonical 后删除」。

## 二、退役清单（39 张，全部为删除动作；原位真身已核实在 domains/）

**批1（parsers platforms×10）**：platforms_acfun / allcpp / bilibili / bilibili_goods / community / discourse / douban / facebook / github / huajia
**批2（parsers platforms×10）**：platforms_kuaishou / kurobbs / lofter / media_share / mihuashi / miyoushe / moegirl / music / pixiv / skland
**批3（parsers ×6）**：platforms_taptap / telegram / weibo / xiaoheihe / zhihu + image_stitch
**批4（sources 根 + fetchers ×9）**：sources.draw_store / epicfree / market_crosscheck / nmc_weather / open_meteo / steamfree / subscription_watcher / url_cleaner + sources.fetchers.xhs_sign
**批5（subscriptions + character ×4）**：sources.subscriptions.bilibili_adapter / target_notice + character.relationship / character.shared_export

结构核验：父包垫片（sources/parsers/__init__.py、sources/subscriptions/__init__.py、sources/fetchers/__init__.py、sources/__init__.py）的聚合/属性均取自 **canonical**（`domains.*`），不本地 import 被删垫片文件——删除后父包聚合属性与 canonical 同源实测 `is True`；其余 parsers 垫片（context/cookies/http_util/platform_login/platforms_epic/platforms_generic/platforms_steam/ssrf_guard/types/wbi）按清单保留待后续梯队。与在飞席位占域（RWC5 根 __init__+域包 init / S14b ops 三子包 / AFF affinity_replay / ACC domains/ops/acceptance / LEG 文档）零交集，未跳张。

## 三、每批回归（解释器=Runtime venv；PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；basetemp=%TEMP%/v21r2-ret1；-p no:cacheprovider）

| 批 | 导入冒烟 | 域回归 | 全库 collect-only |
|---|---|---|---|
| 基线（改前） | OK | — | 8094 collected / 0 error |
| 批1 | OK + parsers 聚合 is canon=True | test_auditfix_parsers 等 7 文件：106 passed/2 skipped/1 failed* | 8094 / 0 error |
| 批2 | OK | parser 族 9 文件：74 passed/1 failed* | 8094 / 0 error |
| 批3 | OK + image_stitch 属性 is canon=True | parser 族 6 文件：52 passed/2 skipped/1 failed* | 8122 / 0 error（AFF 席并行加测试） |
| 批4 | OK | divination+weather+crosscheck+datafix 10 文件：**351 passed/1 skipped** | 8122 / 0 error |
| 批5 | OK + subscriptions 属性 is canon=True | subscribe+character 7 文件：**71 passed** | 8122 / 0 error |

\* 批1/2/3 唯一红=`tests/test_parsers_batch_a2.py::test_discourse_linuxdo_parses_topic`，**归因=存量环境依赖缺陷，与本席零因果**：样本目录 `C:/Users/LancyCelestia/Downloads/Archives/nonebot-plugin-parser-lite-1.3.5/api_txt` 在本机不存在 → 走 fallback 样本（posts_count=3→comment_count=2），断言硬编码 6848 必红；且该测试 import 的是 canonical 真身（`domains.link_parse.parsers.platforms_discourse`）打补丁，代码路径完全不经过被删旧路径垫片。未回退（回退无法改变该红）。

## 四、终验

- **全库关键词扫（退役后）**：39 张旧路径模块名 grep 全库（plugins/tests/scripts/bot.py）→ **0 命中**。
- **verify_hashes --check**：EXIT=0 绿。
- **doc_sync**：--check 报漂移 → 内存 diff 定位=测试文件数 401→408、config 字段数 606→607，**全部来自并行在飞席位新增（本席未删任何测试/config）**；按常驻门规程 --write 重录 docs/auto-facts.md 后 --check EXIT=0 绿。
- **runtime-layout（scripts/runtime_layout_smoke.py 直跑）**：EXIT=1，两条 FAIL 均为 `BOT_KNOWLEDGE_FILES` 配置指向的外部用户文件缺失（`Documents/AI智能体有关材料/鸣潮库街区百科.md` 等）——**存量环境项，与本席垫片删除零耦合**（本席未触配置/外部文件）。
- **树卫生**：plugins/tests/scripts 下 `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache` 零残留；源码树无 `data/` 目录；全程 basetemp=%TEMP% 隔离。

## 五、观察记录（非本席动作，仅记账）

工作树 git D 共 46 项：39 项=本席；另 7 项 card_render 模板（affinity/error/finance/market/mermaid/song_candidates/universal）+ `sources/data/qx.json` 为**他席在飞迁移删除**，已核实 canonical 在位：模板→`domains/render/card_render/templates/`、qx.json→`domains/weather/assets/qx.json`（NMC 码表资产安全）。本席未触碰。

## 六、移交下一梯队

1. **platforms_epic / platforms_steam**（原列第一梯队，复验降级）：同波改写 `tests/test_datafix_runtime_paths.py:143-154` 动态 import 指向 canonical（`domains.link_parse.parsers.platforms_epic/steam`）后删除两张垫片，跑该测试锁定。
2. 仅测试消费方 44 张、需先改写消费方 135 张、在飞占域 55 张：按 EP1 清单 §2 规则推进；父包垫片（parsers/subscriptions/fetchers __init__）随其消费方清零波次同批退役。
