# v21r2 重组 W4 席日志（food 域）

> 席位：RW4（板块重组执行·第 4 波）。执行时间：2026-09-18。解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe` 直跑，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=$TEMP/v21r2-rw4/*` 预创建父目录，`-p no:cacheprovider`。未 commit（共享工作树，提交裁决权在用户）。禁 git 写操作、禁 dev.ps1（席位纪律）。

## 波次裁定（零顺延）

方案书 §5 第 4 波 = **W4 food**（2 件，极小冲突面）。波前核对 COORDINATION 在飞占域：R3b=runtime/pipeline+timesync+loop_watchdog、PA=本文档 §8-§10 追加、RW1a=sources/parsers+domains/link_parse、RW2=music（已收口）、RW3=weather——与本波域零交集。波前 `git status --porcelain` 实证 `capabilities/eat.py`、`sources/food_data.py` 均干净（零在飞未收口改动）。无需顺延，直接执行。

## 一、波前取证（实跑 rg 清单）

引用面（plugins+scripts+tests+bot.py 全树）：

| 命中点 | 形态 | 波内处置 |
|---|---|---|
| `plugins/bot_unified_runtime/__init__.py:32` `from .capabilities.eat import build_eat_capability` | 插件根入口导入 | 垫片覆盖，根 `__init__.py` 零改动（§4.4 铁律） |
| `runtime/base_router.py:42` `from …capabilities.eat import (is_eat_command, is_recipe_command)` | 生产导入 | 垫片覆盖，零改动 |
| `character/daily_assist.py:147` 函数级 `from …sources.food_data import DISHES` | 只读 | 垫片覆盖，零改动 |
| tests ×7 文件头/函数级导入（test_eat_capability / test_eat_image_quality / test_prfix_eat / test_route_order_semantics / test_trigger_english / test_word_boundary_fix / test_auditfix_subscriptions_capabilities） | 只读 | 垫片覆盖，零改动（§3.1 底线） |
| `tests/test_eat_image_quality.py:214` 字符串式 `monkeypatch.setattr("…capabilities.eat._tavily_image_candidates", …)` | **补丁命中①** | 波内改指真身（见 §三） |
| `tests/test_auditfix_wave3_resources.py:11+147` `import eat as eat_mod` + 对象式 `monkeypatch.setattr(eat_mod, "random_dish", …)`（另 :158/:186 直读 `_RECENT`/`_RECENT_MAX_SESSIONS`） | **补丁命中②（对象式）** | 波内改指真身（见 §三） |
| `scripts/clean_food_gallery.py` | **零模块引用**（直连 DB 表/文件操作，方案 W4 注的「联动」实为空） | 无需处置，如实登记 |

私有名跨界扫描（RW2 教训：系统性全量 from-import 扫描，非已知名检索）：跨界私有名仅 2——`_fetch_dish_image`（test_eat_image_quality.py:20）、`_tavily_image_candidates`（:214 补丁 + :296 函数级导入）。`_RECENT`/`_RECENT_MAX_SESSIONS` 经 `eat_mod` 访问，随命中②改真身后不再走垫片。

真身体检：两文件**零相对导入**（全绝对导入）；`_food_image_root` 走 `config.bot_food_image_dir` + `build_runtime_data_path` 重映射（无 `__file__`/`parents[]` 深度推导）→ **零路径深度修正**；`food_data.py` 仅 stdlib 导入（dataclasses）→ 零改动随迁。

## 二、移动清单（2 件 + 域骨架）

| 现路径（旧） | 新路径（真身） |
|---|---|
| `capabilities/eat.py` | `domains/food/capabilities/eat.py` |
| `sources/food_data.py` | `domains/food/data/food_data.py` |

新建骨架：`domains/food/__init__.py`、`domains/food/capabilities/__init__.py`、`domains/food/data/__init__.py`（均纯 docstring；`domains/__init__.py` 已由 RW2 建立，未动）。

真身随迁修正 1 处：`domains/food/capabilities/eat.py:28` food_data 导入改直连真身 `from plugins.bot_unified_runtime.domains.food.data.food_data import (DISHES, Dish, random_dish, search_dishes)`（不经旧位垫片，RW2 同款）；顺带 :478 docstring 口径同步为 `domains.food.data.food_data.DISHES`。

移动方式：文件系统 `mv`（席位禁 git 写操作；未 commit 状态下与 RW2 同款，最终提交时 git 相似度检测仍识别 rename）。

## 三、垫片清单（2 张）

| 垫片 | 显式私有名转出 | 依据 |
|---|---|---|
| `capabilities/eat.py` | `_fetch_dish_image`、`_tavily_image_candidates` | 波前系统性扫描实证跨界私有名仅此 2 名 |
| `sources/food_data.py` | 无 | 全树外引仅公名（DISHES/Dish/random_dish/search_dishes） |

垫片形态与 RW2 一致：docstring + `import *`；两真身均无 `__all__`，故不写 `import __all__` 行（方案 §3.1 模板的该行仅在有 `__all__` 时适用）。

**同一性实证（插件导入冒烟内联断言）**：`shim.build_eat_capability is real.build_eat_capability` 等 **10/10 符号 same-object → True**（公名 4 + 私名 2 + food_data 公名 4）。

## 四、monkeypatch 波前清单 → 波内清零（2 处）

| 文件:行 | 形态 | 波内处置 |
|---|---|---|
| tests/test_eat_image_quality.py:214 | 字符串式 `setattr("…capabilities.eat._tavily_image_candidates", …)` | 改指真身 `…domains.food.capabilities.eat._tavily_image_candidates`（文件头/函数级 from-import 仍走垫片，纯读取语义） |
| tests/test_auditfix_wave3_resources.py:11 | 对象式：`import eat as eat_mod` → `setattr(eat_mod, "random_dish", …)` + `_RECENT` 直读 | 导入改指真身 `from plugins.bot_unified_runtime.domains.food.capabilities import eat as eat_mod`（补丁打真身才生效，§3.1 垫片陷阱） |

清零验证（波后 rg 双模式）：`capabilities\.eat\.|capabilities import eat|sources\.food_data` 在 plugins+tests+scripts+bot.py 扫描，非垫片/非只读残余 **0 命中**；字符串式 monkeypatch 旧路径 **0 命中**。测试改动合计 **2 文件**，其余 7 个命中测试文件零改动（垫片覆盖底线守住）。

## 五、回归实跑（全绿）

```
① 域测试（8 个命中测试文件：eat_capability / eat_image_quality / prfix_eat /
   route_order_semantics / trigger_english / word_boundary_fix /
   auditfix_subscriptions_capabilities / auditfix_wave3_resources）
   → 214 passed in 3.24s（ruff --fix 后复跑 22 passed 再证）
③ verify_hashes --check                             → exit 0
④ test_doc_sync_gates.py                            → 4 passed
⑤ scripts/runtime_layout_smoke.py                   → PASS（bytecode=absent, source_generated_dirs=empty）
   test_no_source_tree_data_writes.py               → 5 passed（qx.json 等资产未触）
⑥ ruff check（本波改动面 7 文件）                    → All checks passed!
   mypy --explicit-package-bases --ignore-missing-imports --cache-dir=$TEMP
   （domains/food + 2 垫片）→ 2 errors in 1 file，全部外部归因：
   control_plane/api/platform.py:79/248（台账 #36 既有，R1/R2 席同证）；本波域 0 错
⑦ 插件导入冒烟                                       → plugin import OK; shims identity OK (10/10)
树卫生终检：find plugins tests scripts __pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache → 0 命中
```

§6.1 `tests/test_domain_layout.py` 暂不存在（他席未建），本波无需对齐。

## 六、偏差与事故记录

1. **git mv → 文件系统 mv**：席位纪律禁 git 写操作（与 RW2 同款替代），内容零改动。
2. **未跑 command_catalog --write**：本波未触 echo/_HELP_ENTRIES/config（门禁清单亦不含），避免卷入他席在飞生成物漂移（RW2 先例）。
3. **§6 ⑧ 全量权威门未跑**：`dev.ps1 -Task test` 为席位禁令，全量回归留待协调方收口时统一实跑；本波以 ①③④⑤⑥⑦ + 清零验证为收口判据，如实登记。
4. **ruff I001 自伤即修**：命中②改导入时排序位放错（domains 应排在 capabilities/contracts 之后），ruff 抓到，`--fix` 波内收口并复跑 22 passed 确认无回归。
5. **clean_food_gallery「联动」证伪**：方案 W4 注预期脚本引用需垫片覆盖，实查脚本零模块导入（直连 SQLite/文件），无需处置——按诚实原则登记为方案预期与实况的偏差，非缺陷。

## 七、回滚说明

本波未 commit。若需回滚：删除 `plugins/bot_unified_runtime/domains/food/`（5 文件），`git checkout -- plugins/bot_unified_runtime/capabilities/eat.py plugins/bot_unified_runtime/sources/food_data.py tests/test_eat_image_quality.py tests/test_auditfix_wave3_resources.py` 恢复 2 垫片位原文件与 2 测试，无残留中间态（`domains/food/` 若回滚则其余域不受影响）。
