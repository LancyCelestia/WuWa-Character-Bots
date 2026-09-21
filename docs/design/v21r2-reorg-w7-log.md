# v21r2 重组 W7 席日志（finance 域）

> 席位：RW7（板块重组执行·第 7 波）。执行时间：2026-09-18。解释器固定 `ChatBot_Runtime/venv/Scripts/python.exe` 直跑，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp=$TEMP/v21r2-rw7/*` 预创建父目录，`-p no:cacheprovider`。未 commit（共享工作树，提交裁决权在用户）。禁 git 写操作、禁 dev.ps1（席位纪律）。

## 波次裁定（零顺延）

方案书 §5 第 7 波 = **W7 finance**（10 件，小冲突面）。波前核对 COORDINATION：RW5/W5 divination、RW6/W6 meme 在飞（均未落盘占域行，但工作树可见 `capabilities/divination.py`、`runtime/reactions.py`、`capabilities/meme_library.py` 在飞改动=RW5/RW6 活动痕迹）；本波域 10 件经 `git status --porcelain` 实证**零在飞未收口改动**（唯一 finance 相邻 WIP=`tests/test_market_github.py`，属 RW1a 波 platforms_github 路径改写的未提交存量，与本波不同 hunk，保留不动）。`contracts/finance.py` 按方案留 core（W16），capability 经其原位引用不受影响。零顺延执行。

## 一、波前取证（rg + AST 双轨清单）

全量引用扫描（plugins+tests+scripts，AST 程序化扫描器覆盖 Import/ImportFrom/字符串常量/setattr 对象式/属性链四类，脚本存 `%TEMP%/v21r2-rw7/scan_finance_refs.py`）：

| 命中点 | 形态 | 波内处置 |
|---|---|---|
| 根 `__init__.py:32-67` `from .capabilities.{fx,market,stocks} import build_*` + `:3842-3848` 工厂调用 | 生产导入 | 垫片覆盖，根 `__init__.py` 零改动（§4.4 铁律） |
| `runtime/base_router.py:47/49/73` is_*_command 名导入 | 生产导入 | 垫片覆盖，零改动（base_router 属 W15d） |
| 10 真身内部：capabilities→sources 兄弟导入 15 处 + sources→market_data 4 处 + sources→http_util 7 处 | 真身随迁 | 直连真身/现行真身路径（见 §二偏差 1） |
| `runtime/capability_registry.py:183-214/497-500` | 纯字符串元数据（note 引「触发词见 capabilities/market.py」） | 零改动（垫片使路径引用仍有效；装饰性残留留给 W15d） |
| `scripts/e2e_acceptance.py:83-97`、`scripts/render_card_samples.py:522` | 公名导入 | 垫片覆盖，脚本零改动（§3.1 底线） |
| tests 23 文件导入面 | 名导入/模块对象导入混合 | 13 文件波内改写（补丁命中），10 文件纯读取垫片覆盖零改动 |
| `tests/test_user_copy_unification_gate.py:439/448` | 模块对象导入但仅 getattr/调用（零补丁） | 垫片同对象覆盖，零改动 |
| 旧位 parsers 补丁残余（`sources.parsers.http_util.*` setattr 字符串） | — | **0 命中**（W1a 波内已清零实证）→ http_util 导入路径选择安全（见偏差 1） |

**monkeypatch 命中清单**：字符串式 patch 目标 **21 处**（test_finance_data ×9、test_fx_card_semantics ×3、test_market_card ×6、test_market_github ×3）+ 对象式 `setattr(<module_obj>, ...)` 约 **128 处**（12 文件，含属性链 D 类 3 处与**多行括号 from-import 盲区 1 处**=test_market_fin_phase1:24，正则漏网 AST 抓到）。合计命中测试文件 **13 个**。

私有名跨界扫描（RW2 教训：系统性 from-import 扫描）：`_RETRY_BACKOFF_SECONDS`（market_data←test_bond_data/test_commodities_data）、`_box_stats`（finance_chart←test_finance_charts）、`_COMPANY_BY_TICKER`（stock_data←capabilities/stocks.py 直连后垫片兜底）、`_MAX_PAYLOAD_BYTES`（market_data←bond/commodities 直连后垫片兜底）。真身 `__all__` 仅 finance_chart 有 → 其垫片带 `import __all__` 行。

## 二、移动清单（10 件 + 域骨架）

| 现路径（旧） | 新路径（真身） |
|---|---|
| `capabilities/market.py`（826 行） | `domains/finance/capabilities/market.py` |
| `capabilities/stocks.py`（786 行） | `domains/finance/capabilities/stocks.py` |
| `capabilities/fx.py`（298 行） | `domains/finance/capabilities/fx.py` |
| `sources/stock_data.py`（1697 行） | `domains/finance/data/stock_data.py` |
| `sources/market_data.py`（752 行） | `domains/finance/data/market_data.py` |
| `sources/fx_data.py`（589 行） | `domains/finance/data/fx_data.py` |
| `sources/commodities_data.py`（358 行） | `domains/finance/data/commodities_data.py` |
| `sources/bond_data.py`（285 行） | `domains/finance/data/bond_data.py` |
| `sources/market_crosscheck.py`（189 行） | `domains/finance/data/market_crosscheck.py` |
| `sources/finance_chart.py`（256 行） | `domains/finance/data/finance_chart.py` |

新建骨架：`domains/finance/__init__.py`、`domains/finance/capabilities/__init__.py`、`domains/finance/data/__init__.py`（纯 docstring；`domains/__init__.py` RW2 已建未动）。移动方式：文件系统 `mv`（RW2/RW4 同款，最终提交时 git 相似度检测识别 rename）。

**真身随迁修正**（`sed` 语句级精确替换 + 逐点复核）：
- capabilities→data 兄弟导入 15 处改直连真身 `plugins.bot_unified_runtime.domains.finance.data.*`（market 6/stocks 7/fx 2）；
- sources 兄弟导入 4 处（stock/fx/commodities/bond→market_data）同改直连；
- docstring 口径同步 4 处（market:3、stocks:5/8、fx:3、stocks `python -m` 自跑注释 :778）；
- `finance_chart` 模板串 `` `​`​`finance_chart.`` → ``domains.finance.data.finance_chart.``（stocks docstring）。

## 三、偏差与事故记录

1. **http_util 跨域直连误判→即改即复**：初版把 7 处（6 data 头部 + stocks.py:119 函数级）http_util 导入切到 `domains.link_parse.parsers.http_util`——**W1b 顺延未执行**，该路径不存在（`domains/link_parse/parsers/` 现仅 28 个 platforms_*.py，基建 9 件仍在旧位真身非垫片），全量收集 107 error 实锤。回改为现行真身 `plugins.bot_unified_runtime.sources.parsers.http_util`（波前已实证旧位 parsers 补丁 0 残余，选择安全），107 error 清零。**W1b 执行时需接管这 7 处再迁**。
2. **RW6 在飞碰撞 1 红（非本波域，移交）**：`test_user_copy_unification_gate.py::test_q04_self_reference_unified:490` 直读 `capabilities/meme_library.py` 文件内容断言守岸人文案，RW6 波在飞行进中把该文件落成垫片（本波执行期间落盘），内容锚定断言红。归属 RW6 波内收口（方法论③），本席不碰防写写碰撞，如实登记。
3. **ruff --fix 收口 32+5 处**：测试改写后 import 排序（I001，domains 应排 capabilities/contracts 之后）与真身函数级单导入转括号风格，`--fix` 波内收口并复跑确认无回归（W4 同款）。
4. **未跑 command_catalog --write**：本波未触 echo/_HELP_ENTRIES/config（门禁清单不含）。
5. **§6 ⑧ 全量权威门未跑**：`dev.ps1 -Task test` 席位禁令，全量回归留协调方收口统一实跑；以 ①②③⑤⑥⑦ + AST 清零为收口判据。

## 四、垫片清单（10 张）

| 垫片 | 显式转出 |
|---|---|
| `capabilities/{market,stocks,fx}.py` ×3 | 无（外引全公名） |
| `sources/market_data.py` | `_RETRY_BACKOFF_SECONDS`、`_MAX_PAYLOAD_BYTES` |
| `sources/stock_data.py` | `_COMPANY_BY_TICKER` |
| `sources/finance_chart.py` | `_box_stats` + `__all__` |
| `sources/{fx_data,commodities_data,bond_data,market_crosscheck}.py` ×4 | 无 |

形态与 W2/W3/W4 一致：docstring + `import *` + 私名显式 `import (...)  # noqa: F401`。**同一性实证（插件导入冒烟内联断言）：10 垫片 35/35 符号 same-object True**（含私名 4 + `__all__` 同一性）。

## 五、monkeypatch 波内清零（13 文件）

改写原则（W2/W3/W4 同款）：**补丁目标相关导入改真身**（模块对象导入→`domains.finance.data/capabilities` 真身；字符串式 patch→真身全路径），**纯读取名导入留垫片**（零改动底线）。

| 文件 | 改写 |
|---|---|
| test_bond_data / test_commodities_data / test_fx_data / test_market_backoff / test_northbound_data / test_stock_data / test_market_crosscheck_tencent_gbk | 头部模块对象导入 ×1 各改真身（`_RETRY_BACKOFF_SECONDS` 函数级值读留垫片） |
| test_finance_data | 头部 3 模块对象 + 函数级 stocks_cap/fx_cap ×22 + market_data/stock_data ×3 + 字符串式 ×9 |
| test_finance_market_expansion | 头部 2 模块对象 |
| test_fx_card_semantics | fx_cap 对象 + 字符串式 ×3 |
| test_market_card | mc 对象 ×4 + market_data ×2 + capabilities.market 字符串式 ×6 |
| test_market_fin_phase1 | market_cap/stocks_cap + **多行括号 from-import**（bond/commodities/market_data）+ stock_data 函数级 |
| test_market_github | market_data 对象（RW1a WIP 文件，仅动 finance hunk）+ 字符串式 ×3 |

**AST 终验**：波后重扫 B/C/D 类（字符串补丁/对象补丁/属性链）非真身、非 docstring 残余 = **0 命中**；A-OBJ 残余仅 test_user_copy_unification_gate 2 处纯读取（刻意保留）。测试改动合计 **13 文件**，其余 10 命中测试文件零改动。

## 六、回归实跑

```
① 域测试（23 个命中测试文件）      → 780 passed, 2 skipped（唯一 1 failed=偏差 2 RW6 在飞碰撞，非本波域）
   宽域关键词清扫 -k                → 857 passed, 2 skipped, 0 collection error
② 渲染契约（双保险，finance 卡走 bridge）→ 171 passed
③ verify_hashes --check            → exit 0
④ test_doc_sync_gates.py           → 4 passed（与 ⑤ 合跑 9 passed）
⑤ scripts/runtime_layout_smoke.py  → PASS（source_generated_dirs=empty, bytecode=absent）
   test_no_source_tree_data_writes → 5 passed（qx.json 未触，domains/weather/assets/ e8285e77 完好）
⑥ ruff（真身 10+垫片 10+测试 13）   → All checks passed!
   mypy --explicit-package-bases（本波面 23 文件）→ 本波 0 错；5 错全外部归因
   （control_plane/api/platform.py ×2 既有 + capabilities/chat.py ×3 他席在飞 WebSearchHit 面）
⑦ 插件导入冒烟                     → plugin import OK; shims identity OK (35/35)
树卫生终检：__pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache → 0 命中
```

## 七、回滚说明

本波未 commit。若需回滚：删除 `plugins/bot_unified_runtime/domains/finance/`（13 文件），`git checkout --` 恢复旧位 10 真身与 13 测试文件（`git checkout -- plugins/bot_unified_runtime/capabilities/market.py plugins/bot_unified_runtime/capabilities/stocks.py plugins/bot_unified_runtime/capabilities/fx.py plugins/bot_unified_runtime/sources/stock_data.py plugins/bot_unified_runtime/sources/market_data.py plugins/bot_unified_runtime/sources/fx_data.py plugins/bot_unified_runtime/sources/commodities_data.py plugins/bot_unified_runtime/sources/bond_data.py plugins/bot_unified_runtime/sources/market_crosscheck.py plugins/bot_unified_runtime/sources/finance_chart.py tests/test_bond_data.py tests/test_commodities_data.py tests/test_finance_data.py tests/test_finance_market_expansion.py tests/test_fx_card_semantics.py tests/test_fx_data.py tests/test_market_backoff.py tests/test_market_card.py tests/test_market_crosscheck_tencent_gbk.py tests/test_market_fin_phase1.py tests/test_northbound_data.py tests/test_stock_data.py`；test_market_github.py 需手工只回退 finance hunk 以保 RW1a WIP），无残留中间态。
