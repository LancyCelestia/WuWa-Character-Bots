# v21r2 板块重组 W3 席（weather 域）执行日志

> 席位：RW3（板块重组执行·第 3 波）。日期：2026-09-18。工作树未提交 WIP 多席并行，本席零 git 写操作（无 git mv/add/commit，纯文件系统 mv + 新建），全部改动留在工作树待用户裁决提交。
> 施工图：`docs/design/v21r2-reorg-plan.md` §2.3/§3/§5(W3)/§6；占域核对：`v21r2-COORDINATION.md`（R3b=runtime/pipeline+timesync+loop_watchdog、S8=knowledge_service+database_broker+teaching_service、CMD=docs、RW1a=parsers/link_parse、RW2=music——与本波 weather 域零交集）。

## 1. 本波移动（4 件 + 新建 4 __init__ + 垫片 3）

| 旧路径 | 新路径 |
|---|---|
| `capabilities/weather.py` | `domains/weather/capabilities/weather.py` |
| `sources/nmc_weather.py` | `domains/weather/data/nmc_weather.py` |
| `sources/open_meteo.py` | `domains/weather/data/open_meteo.py` |
| `sources/data/qx.json`（随包资产） | `domains/weather/assets/qx.json`（sha256 前后一致：`e8285e77d8edf2f90faf670b6f39d8dc3b03e995d1128ef64b2cc4d86361b668`；迁移后探针实载 2527 区县） |
| —（新建） | `domains/weather/__init__.py`、`domains/weather/capabilities/__init__.py`、`domains/weather/data/__init__.py`（docstring 薄壳，沿用 RW1a/RW2 惯例；`domains/__init__.py` 已由先波在席创建，未重复写） |
| —（垫片） | 旧三路径各落 re-export 薄壳（`from …domains.weather… import *` + 显式下划线名再导出） |

`sources/data/` 目录迁移后已空，删除。

## 2. 波前取证（rg 实跑清单）

**monkeypatch 旧路径命中（波前 → 波内全部改指新路径，波内清零）**：

| 测试文件 | 命中 | 处置 |
|---|---|---|
| `tests/test_weather_alerts_b10.py` | 6 处串式 `setattr("plugins.bot_unified_runtime.capabilities.weather.*")` | import+6 串全改 `domains.weather.capabilities.weather` |
| `tests/test_weather_card.py` | 9 处串式（nmc_weather_query/http_get_json/open_meteo_query/format_open_meteo） | import+9 串全改 |
| `tests/test_weather_nmc_retry_nmcflix.py` | 8 处对象式 `setattr(weather_mod, …)`（weather_mod 经旧路径导入=垫片陷阱面） | 两处 import 改新路径，patch 落真身 |
| `tests/test_auditfix_subscriptions_capabilities.py` | 2 处串式（L406/410） | 仅改 2 串；L29 旧路径 import 刻意保留（共享测试文件最小 diff，垫片覆盖） |

**旧路径 import（非 patch）保留原样（垫片覆盖，零改动）**：根 `__init__.py:70`（`from .capabilities.weather import build_weather_capability`）、`console_chat.py:53`、`route_demo.py:26`、`runtime/base_router.py:81`（is_weather_command）、`runtime/natural_language.py:28`（is_statement_lead）、`scripts/e2e_acceptance.py:104`、`tests/test_traditional_triggers.py`（`_WEATHER_RE`）、`tests/test_ratchet_fix.py`、`tests/test_trigger_english.py`、`tests/test_weather_statement_guard.py`（`_query_variants`）。
**垫片显式下划线再导出**：`_WEATHER_RE`、`_nmc_query_with_retry`、`_query_variants`（后两者波内首轮回归抓漏后补齐——多行 import 清单取证遗漏教训已记录）。

## 3. 真身内部改写

- `domains/weather/capabilities/weather.py`：`sources.nmc_weather`/`sources.open_meteo` 两个 import 块改指 `plugins.bot_unified_runtime.domains.weather.data.*`（域内新 canonical）；`contracts` 与 `sources.parsers.http_util` 跨域 import 保持旧路径（RW1a 垫片链覆盖，避免跨席耦合）。原文件无相对导入，无需改写。
- `domains/weather/data/nmc_weather.py`：`_QX_PATH = Path(__file__).parent.parent / "assets" / "qx.json"`（原 `parent/"data"` 随迁失效）。
- `open_meteo.py`：无路径依赖，零内部改动。

## 4. 门禁同步

- `scripts/pre_restart_check.py`：`QX_JSON_REL` → `plugins/bot_unified_runtime/domains/weather/assets/qx.json`。
- `tests/test_pre_restart_check.py`：make_project 假项目 qx 落点同步改（L42）。
- `tests/verify_hashes.py`：无 weather/qx 条目，`--check` 实跑 PASS，零改动。
- `tests/test_no_source_tree_data_writes.py`/`tests/conftest.py` 数据写守卫：只盯仓库根 `data/`，qx.json 迁移不触雷，实跑 PASS 零改动（plan W3 要点中「例外规则」在现行守卫中不存在，无需改）。

## 5. 回归实跑（解释器固定 venv；PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；basetemp=%TEMP%/v21r2-rw3）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 域测试（10 文件） | `pytest tests/test_weather_{alerts_b10,card,nmc_retry_nmcflix,statement_guard}.py tests/test_pre_restart_check.py tests/test_auditfix_subscriptions_capabilities.py tests/test_traditional_triggers.py tests/test_ratchet_fix.py tests/test_trigger_english.py tests/test_no_source_tree_data_writes.py -p no:cacheprovider -q` | **259 passed** |
| 全库关键词扫測 | `pytest tests -k "weather or nmc or meteo or qx_json" -q` | **139 passed**, 7525 deselected |
| 插件导入冒烟+垫片同一性 | `python -c` 探针（import 插件 + mail_adapter + shim/real 函数对象同一性 + qx 2527 装载） | **OK**（build_weather_capability/is_weather_command/_WEATHER_RE/_query_variants shim≡real；sources 双垫片符号同一） |
| ruff | scoped（本波全部改动文件） | **0 error**（首轮 6 处可自动修已收口：noqa F403 非 enabled→F401、3 测试文件 I001 排序）；全树 71 error 逐一比对**零命中本波文件**（全为在飞席位 WIP：decision/outbound_registry、parsers、sandbox 等） |
| mypy | `mypy --cache-dir=%TEMP%/mypy-rw3-cache --explicit-package-bases --ignore-missing-imports plugins`（dev.ps1 同口径 flags） | **5 error 全在非本波文件**：`runtime/timesync.py:501`（R3b 在飞）、`character/kb_wiki.py:602`（location 域存量）、`control_plane/api/platform.py:79/248`（台账既有 2 错）；weather 域文件零新增 |
| 树卫生 | `runtime_layout_smoke.py` + data/__pycache__ 巡检 | **PASS**；无 stray data/；波中清理并行席位残留在仓库根的 `__pycache__/bot.cpython-312.pyc`（备份 `%TEMP%/chatbot-stray-pycache-rw3-20260918/` 后删除，脚本双计为 2） |
| 哈希门 | `tests/verify_hashes.py --check` | **PASS** |
| doc_sync 门 | `pytest tests/test_doc_sync_gates.py -q` | **4 passed** |

未跑：`dev.ps1 -Task test` 全量（本席纪律禁用 dev.ps1；按 §6 直跑项覆盖）。提交：按多席并行纪律不做，回滚方式=反向 mv 四件+删 `domains/weather/`+删三垫片内容还原+revert 测试/script 路径串，无中间态。

## 6. 偏差与决定记录

1. **波序并行**：开工时 W1a/W1b/W2 尚未落盘（domains/ 不存在），波中 RW1a/RW2 并行落盘 link_parse/music——按「无冲突域续跑」原则 W3 直接执行，未顺延（plan §5 顺序原则允许无冲突域先行/并行）。
2. **auditfix 共享测试文件最小 diff**：只改 2 个 monkeypatch 串，L29 import 保留旧路径——该文件同时被订阅域（RW2 W8）共享，缩小冲突面；垫片保证语义不变。
3. **首轮回归抓到垫片下划线名漏导出**（`_query_variants`）：多行 import 清单的 rg 取证模式有盲区，已全量枚举旧路径消费符号补齐；后续席位取证建议直接枚举 import 块全名而非关键词过滤。
4. **mypy 必须带 `--explicit-package-bases`**（dev.ps1 口径），裸跑会报 character/memory.py 双模块名假错（与本波无关的既有行为）。
5. **全树 ruff 71 errors / mypy 5 errors 均为在飞席位 WIP 与台账既有**，本波零贡献，未代修（越域）。
