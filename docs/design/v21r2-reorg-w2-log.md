# v21r2 重组 W2 席日志（music 域）

> 席位：RW2（板块重组执行·第 2 波）。执行时间：2026-09-18。解释器固定 venv 直跑，`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest `--basetemp` 预创建，`-p no:cacheprovider`。未 commit（共享工作树，提交裁决权在用户）。

## 波次裁定（顺延记录）

方案书 §5 表「紧跟 W1a 之后」的第一候选 W1b（link_parse 其余 16 件）与在飞 RW1a 席占域（sources/parsers + domains/link_parse）直接冲突 → 按 §4.1 顺延至下一无冲突小域 **W2 music**（4 件）。与 R5/R3b/S8/CMD 全部零交集，波前 `git status` 确认本域 4 文件零在飞未收口改动。

## 一、移动清单（4 件 + 域骨架）

| 现路径（旧） | 新路径（真身） |
|---|---|
| `capabilities/music.py` | `domains/music/capabilities/music.py` |
| `sources/music_charts.py` | `domains/music/data/music_charts.py` |
| `sources/music_request_store.py` | `domains/music/data/music_request_store.py` |
| `sources/music_normalization.py` | `domains/music/data/music_normalization.py` |

新建骨架：`domains/__init__.py`（**本席新建，RW1a 未建根 init，共享新增请知悉**）、`domains/music/__init__.py`、`domains/music/capabilities/__init__.py`、`domains/music/data/__init__.py`（均纯 docstring）。

真身随迁修正 2 处：
1. `domains/music/capabilities/music.py`：`Path(__file__).resolve().parents[3]` → `parents[5]`（层级 +2，项目根推导跟随；`_resolve_music_data_dir` → `scripts.runtime_paths` 链路保真）。
2. `domains/music/data/music_request_store.py`：sibling 导入改直连真身 `from plugins.bot_unified_runtime.domains.music.data.music_normalization import canonical_key`（不经旧位垫片）。

相对导入：波前 rg 实证 4 文件**零相对导入**（全部已是绝对导入），无需改写。

## 二、垫片清单（4 张）

旧位全部落纯 re-export 薄壳（`import *`，符号与真身同一对象）：

| 垫片 | 显式私有名转出 | 依据 |
|---|---|---|
| `capabilities/music.py` | `_resolve_music_data_dir`、`_media_parts_from_item` | 波后系统性 from-import 全树扫描：跨界私有名仅此 2 名（前者 tests/test_datafix_runtime_paths.py:161，后者 capabilities/content_parser.py:15） |
| `sources/music_charts.py` | 无 | 全树无私有名外引 |
| `sources/music_request_store.py` | 无 | 同上 |
| `sources/music_normalization.py` | 无 | 同上 |

垫片同一性实证：`shim.clear_music_candidate_sessions is real.clear_music_candidate_sessions` → True（import 冒烟断言）。

## 三、monkeypatch 波前清单 → 波内清零

| 文件:行 | 形态 | 波内处置 |
|---|---|---|
| tests/test_music_charts_real_sources_v2.py:143/182/218/296 | 字符串式 `monkeypatch.setattr("…sources.music_charts.http_get_json/http_post_json")` ×4 | 4 处全改指真身 `…domains.music.data.music_charts.http_*`（文件头 from-import 仍走垫片，纯读取语义） |
| tests/test_audit_fixes_b.py:12+559-572 | 对象式 `setattr(music_module,…)` + 私有状态直改（`_CANDIDATE_MAX_SESSIONS/_CANDIDATE_SESSIONS/_prune_candidate_sessions`） | 导入改指真身 `from plugins.bot_unified_runtime.domains.music.capabilities import music as music_module`（补丁打真身才生效，垫片陷阱 §3.1） |

波内清零验证：`rg monkeypatch 旧 music 路径` 双模式检索均 0 命中（字符串式 rg_exit=1；对象式仅剩真身路径命中）。测试改动合计 2 文件，未触碰其他任何测试（垫片覆盖零改动底线守住：test_music_candidates_v2/card、test_music_charts_v2、test_music_analytics/backend、test_auditfix_subscriptions、test_pinyin_triggers_2、test_trigger_english、test_traditional_triggers、test_ratchet_fix、test_parse_presentation_v2 全部原样通过）。

## 四、回归实跑（全绿）

```
① 域测试（7 个 music 测试文件 + 8 个命中文件，15 文件 432 用例）
   432 passed in 17.77s
③ verify_hashes --check                    → exit 0
④ test_doc_sync_gates.py                   → 4 passed
⑤ runtime_layout_smoke.py                  → source_generated_dirs=empty, python_bytecode=absent
   test_no_source_tree_data_writes.py      → 5 passed（qx.json 例外完好，资产未触）
⑥ ruff check（本波改动面 7 文件）           → All checks passed!
   mypy（dev.ps1 同参：--explicit-package-bases --ignore-missing-imports plugins）
   → 5 errors in 3 files，全部外部归因：runtime/timesync.py×2（R3b 在飞域）、
     character/kb_wiki.py×1（R2/R5 坐标）、control_plane/api/platform.py×2（台账#36 既有）；
     本波域（domains/music/** + 4 垫片）0 错
⑦ 插件导入冒烟                              → plugin import OK; shims OK（含 shim==real 同一性断言）
```

## 五、偏差与事故记录

1. **git mv → 文件系统 mv**：任务纪律禁 git 写操作（index 污染会波及并行席位），改用 `mv`；内容零改动，最终提交时 git 相似度检测仍识别 rename，历史不丢（与方案 R8 意图等价）。
2. **波前 rg 漏检私有名（方法论修正）**：按已知名检索漏掉 `_media_parts_from_item`（content_parser.py:15），插件导入冒烟当场抓获 ImportError → 补做**系统性 from-import 全树扫描**（正则抽全部 import 块符号比对下划线前缀）后垫片补转出。**后续席位教训：垫片落地前必须跑全量 from-import 扫描，不能只检索已知符号名。**
3. **并行扰动归因（非本波红，未修）**：① W3 天气席迁移间隙 `capabilities/weather.py` 短暂消失致收集期 ModuleNotFoundError，轮询 ~20s 其垫片落位后自愈；② RW1a 在飞改 platforms_epic/steam（W1b cookies 链路）期间 test_epic_steam_cookie_candidates 2 failed，其收口后复跑消失（终局 432 全绿）。
4. **全树静态门既有外部错误（未修，不越域）**：ruff 全树 75 错（decision/outbound_registry×3 C409、test_weather_*/test_parsers_*/test_music_provider_projection 等 I001——多为并行席新落文件）；mypy 5 错见上。均与本波改动面零交集。
5. **树卫生清理两笔**：`scripts/__pycache__`（telegram_resilience.cpython-312.pyc，R2 席在飞残留）备份 `%TEMP%/chatbot-stray-cache-rw2-20260918-011105` 后清除；根 `.mypy_cache`（本席一次未带 --cache-dir 直跑所生，自清）。终局 layout 实证 bytecode=absent。
6. **pytest --basetemp 纪律增补**：basetemp 父目录必须预存在（pytest `parents=False`），且并行 pytest 共享 basetemp 父目录会 rm_rf 竞态出批量 fixture ERROR——本席以独立子目录 + `mkdir -p` 预创建规避（先前 38+4 ERROR 均此环境因，非域代码红）。
7. **未跑 command_catalog --write**：本波未触 echo/_HELP_ENTRIES/config（任务门禁清单也不含）；避免卷入其他席位在飞生成物漂移。

## 六、回滚说明

本波未 commit。若需回滚：删除 `plugins/bot_unified_runtime/domains/music/`（含 4 真身 + 4 __init__；`domains/__init__.py` 若 RW1b/W3 后续域也已依赖则保留），并用 `git checkout -- plugins/bot_unified_runtime/capabilities/music.py plugins/bot_unified_runtime/sources/music_charts.py plugins/bot_unified_runtime/sources/music_request_store.py plugins/bot_unified_runtime/sources/music_normalization.py tests/test_music_charts_real_sources_v2.py tests/test_audit_fixes_b.py` 恢复 4 垫片位原文件与 2 测试，无残留中间态。
