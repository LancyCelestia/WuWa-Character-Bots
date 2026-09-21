# S15 全量门禁预检报告（v21r2 GATE 席）

- 生成时间：2026-09-18（UTC+8 实跑当日）
- 执行席：S15 GATE（只读门禁实跑，不修码、不处置红项、无 git 写操作、未派子代理）
- 工作区：`C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot`
- **在飞声明：工作树存在大量未提交 WIP 多席并行（在飞：RWOCc=domains/core+ops 迁移与原位垫片、S14b=domains/ops 三子包、WIREb=domains/chat_reply/capabilities/chat.py+persona_service+config、EP1=scripts+树卫生清扫、LOG=V21-UPDATE-LOG.md）。本报告所有数字均为「在飞席位移动态」的瞬时快照，不代表最终收口态。**

## 执行环境与方法（可复跑）

- 解释器：`C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`
- 环境变量：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`
- pytest：`--basetemp="$TEMP/v21r2-gate/pytest" -p no:cacheprovider`；ruff/mypy cache-dir 置于 `%TEMP%`（源码树零缓存）
- 未使用 dev.ps1（本报告命令为与 dev.ps1 等价的直接调用）；未跑全量 pytest（在飞席太多红绿无法切割，仅 collect-only）
- 原始日志：`%TEMP%/v21r2-gate-logs/`（ruff.txt / mypy.txt / collect.txt）
- 门禁命令（均从工作区根执行）：
  1. `tests/verify_hashes.py --check`
  2. `scripts/doc_sync.py --check`
  3. `scripts/command_catalog.py --check`
  4. `scripts/runtime_layout_smoke.py`
  5. `ruff check --cache-dir %TEMP%/v21r2-gate/ruffcache .`
  6. `python -m mypy --cache-dir %TEMP%/v21r2-gate/mypycache --explicit-package-bases --ignore-missing-imports plugins`
  7. `python -m pytest tests --collect-only -q --basetemp=... -p no:cacheprovider`
  8. 树卫生扫描 + 插件导入冒烟计时

## 门禁总览

| # | 门禁 | 结果 | exit | 备注 |
|---|---|---|---|---|
| 1 | verify_hashes --check | **PASS** | 0 | 零漂移、零输出 |
| 2 | doc_sync --check | **FAIL** | 1 | 漂移 2 行（测试文件数、bot_* 字段数），见 §2 |
| 2b | command_catalog --check | **PASS** | 0 | `command catalog is current (77 topics)` |
| 3 | runtime-layout | **FAIL（环境项）** | 1 | 仅 BOT_KNOWLEDGE_FILES 外部文件缺失 ×2，代码侧边界全绿，见 §3 |
| 4 | ruff 全仓 | **FAIL** | 1 | 36 错，**100% 落在在飞席位域文件**，见 §4 |
| 5 | mypy (plugins) | **BLOCKED** | 2 | 1 处 SyntaxError 阻断全量检查，无法给出 plugins 全量结论，见 §5 |
| 6 | pytest collect-only | **FAIL** | 2 | 收集 8002 用例 + 2 collection errors（同一根因），见 §6 |
| 7 | 树卫生 | **基本干净** | — | 无 __pycache__/.pytest_cache/*.pyc；根部 .mypy_cache/.ruff_cache 残留，见 §7 |
| 8 | 插件导入冒烟 | **PASS** | 0 | 1.218s，见 §8 |

**绿门 3（verify_hashes / command_catalog / 导入冒烟）+ 环境项 1；红门 4（doc_sync / ruff / mypy / collect）——全部红项根因收敛到在飞席位 WIP，存量稳定代码零新增红。**

## §1 verify_hashes --check — PASS

- exit=0，无任何漂移输出。12+ 交付物哈希清单（TRACKED_FILES）与磁盘一致。

## §2 doc_sync --check — FAIL（漂移 2 行，在飞新增）

用 `build_document()` 只读复算 diff（未执行 --write）：

```diff
--- auto-facts.md(current)
+++ expected(from code)
- 测试文件数：401
- config.py bot_* 字段数：606
+ 测试文件数：405
+ config.py bot_* 字段数：607
```

- 归因：在飞席位新增 4 个测试文件（test_v21_s14_incident / test_v21_s14_recovery 等）与 1 个 bot_* 配置键（WIREb persona_service/config 批）。属「事实册滞后于在飞代码」的预期漂移，待各席收口时统一 `doc_sync.py --write` 重录；本轮 GATE 只记录不处置。

## §2b command_catalog --check — PASS

- exit=0：`command catalog is current (77 topics)`。（`--check` 受支持，已实跑。）

## §3 runtime-layout — FAIL（仅环境项，代码边界全绿）

```
runtime-layout: FAIL
- configured BOT_KNOWLEDGE_FILES file missing: C:\Users\LancyCelestia\Documents\AI智能体有关材料\鸣潮 AI智能体有关材料\鸣潮库街区百科.md
- configured BOT_KNOWLEDGE_FILES file missing: C:\Users\LancyCelestia\Documents\AI智能体有关材料\鸣潮 AI智能体有关材料\战双帕弥什库街区百科.md
```

- **单列环境项（已知，SBX 席登记同源）**：BOT_KNOWLEDGE_FILES 指向的用户外部目录文件缺失，非代码缺陷。工作区外文件，GATE 席未核查、不处置。
- 除上述 2 行外无其他输出：源码树/外部数据边界检查（data 重映射、生成物零残留、运行时边界）全部通过。domains/*/data 子包（7 个，均为源码模块非生成物）未被误报。

## §4 ruff 全仓 — FAIL（36 错，全部在飞席位域）

exit=1；`Found 36 errors. [*] 6 fixable with --fix`。**存量稳定代码（legacy capabilities/sources/output/runtime 等）0 错**。逐文件明细与归因（席位=在飞移动态归属，非最终裁决）：

| 文件 | 错数 | 规则 | 归因 |
|---|---|---|---|
| domains/core/decision/outbound.py:73 | 1 | RUF022 `__all__` 未排序 | **在飞 RWOCc**（domains/core 迁移） |
| domains/core/decision/outbound_registry.py:478/517/594 | 3 | C409 | **在飞 RWOCc** |
| domains/ops/incident/service.py:215-221 | 9 | C409（同文件另含 SyntaxError，见 §5） | **在飞 S14b/RWOCc**（domains/ops） |
| tests/test_outbound_v21.py | 4 | I001/DTZ001/PLW1510/ISC004 | **在飞 RWOCc 配套测试** |
| tests/test_outdomain_fixes_20260911.py:9 | 1 | I001 | **在飞迁移关联测试** |
| tests/test_search_service_v21.py:10 | 1 | I001 | **在飞迁移关联测试** |
| tests/test_v21_risk_red_cp_platform.py | 2 | F401/F841 | **在飞控制面关联测试** |
| tests/test_v21_s14_incident.py | 2 | F401/F821（364 行 `RecoveryOutcome` 未定义） | **在飞 S14b 配套测试** |
| tests/test_v21_s14_recovery.py | 13 | F401/PERF102/RUF059×10 | **在飞 S14b 配套测试** |
| **合计** | **36** | | 在飞域 36 / 存量 0 |

注意：ruff 对 service.py:215 给出 C409 而非 invalid-syntax（ruff 自研解析器与 CPython 语法判定不一致）；以 CPython 实锤（pytest 导入失败）为准，见 §5/§6。

## §5 mypy (plugins) — BLOCKED（1 处 SyntaxError 阻断全量）

```
plugins\bot_unified_runtime\domains\ops\incident\service.py:215: error: Invalid syntax  [syntax]
Found 1 error in 1 file (errors prevented further checking)
```

- 归因：**在飞 S14b/RWOCc**（domains/ops 三子包）。`service.py:215` 形如 `clock: (() -> float) | None = None,` 的参数注解被 CPython 判非法（参数注解位置不允许括号包裹的函数类型表达式），mypy/pytest 双工具实锤。
- **BLOCKED 语义**：mypy 因语法错误提前终止，本轮**无法**给出 plugins 全仓类型检查结论；AGENTS 记载的历史存量（control_plane/api/platform.py 2 错）本轮不可证（unknown），待语法错误修复后复跑才有全量数字。

## §6 pytest collect-only — FAIL（8002 collected + 2 errors，单一根因）

```
8002 tests collected, 2 errors in 17.08s   (exit=2)
ERROR tests/test_v21_s14_incident.py
ERROR tests/test_v21_s14_recovery.py
```

- 两处 collection error 同根因：导入 `plugins.bot_unified_runtime.domains.ops.incident.service` 时触发 §5 同一 SyntaxError（service.py:215）。
- **收集零错断言：不成立**（2 错，均 S14b 在飞域）。除该文件外其余收集全部成功，用例总数快照 **8002**。
- 按纪律未跑全量 pytest（在飞红绿无法切割）。

## §7 树卫生

- `__pycache__`：0；`.pytest_cache`：0；`*.pyc`：0 —— 干净（本轮门禁全程 PYTHONDONTWRITEBYTECODE + cache 外置 + no:cacheprovider，未新增污染）。
- **根部残留**：`.mypy_cache`（34MB，mypy 3.12）与 `.ruff_cache`（8KB，ruff 0.16.4）——历史直跑遗留，**EP1 树卫生清扫域**，GATE 不处置。
- 运行时 `data/` 残留：源码树无（ domains/*/data 均为源码子包，属允许项）。
- **qx.json 资产核查（重要）**：旧位 `sources/data/qx.json` 已被在飞迁移删除（git ` D`），新位 **`domains/weather/assets/qx.json` 磁盘在**；整个 `plugins/bot_unified_runtime/domains/` 为**未跟踪（untracked）新树**。风险提示：EP1 清扫与任何 `%TEMP%` 备份清理波**不得**把 untracked 的 domains/ 树当垃圾清除，否则 NMC 天气码表将第四次丢失。

## §8 插件导入冒烟 — PASS

```
IMPORT_OK plugins.bot_unified_runtime (__init__.py 于工作区)
ELAPSED_SEC 1.218
```

- 成功导入、1.218s（冷导入快照）。注意：插件顶层导入不触碰 domains/ops/incident（该坏文件仅在 ops 子包内部相对导入链上，故顶层导入仍绿）；这与此后 pytest 按 ops 子包导入失败不矛盾。

## 红项归因统计（瞬时快照）

| 红项 | 数量 | 根因 | 归因席位 |
|---|---|---|---|
| SyntaxError 阻断 | 1 处（service.py:215） | 单点语法错误，连坐 mypy 全量阻断 + pytest 收集 2 错 | **在飞 S14b/RWOCc** |
| ruff 错 | 36（在飞域 36 / 存量 0） | domains 迁移新代码与配套测试 | 在飞 RWOCc≈9、S14b≈24、v21 关联 3 |
| doc_sync 漂移 | 2 行 | 在飞新增测试×4、配置键×1 | 在飞各席（待收口 --write） |
| runtime-layout | 2 失败 | BOT_KNOWLEDGE_FILES 用户外部文件缺失 | 环境项（非代码） |
| 树卫生 | 2 目录 | 根部 .mypy_cache/.ruff_cache 历史残留 | EP1 域 |
| verify_hashes / command_catalog / 导入冒烟 | 0 | — | 全绿 |

## S15/16 收口清单

**A. 各席收官后必须复跑的门（本报告数字不作数）**
1. S14b/RWOCc 修复 `domains/ops/incident/service.py:215` 语法后：mypy 全量复跑（才能拿到 plugins 全仓真实错误数，含历史 control_plane 2 错存量的可证性）+ pytest collect-only 复跑（8002+2err → N+0err）。
2. RWOCc/S14b 配套测试清 ruff（36 错全在其域）：`ruff check .` 复跑至 0。
3. WIREb config 键定稿 + 测试文件数定稿后：`doc_sync.py --write` + `--check` 复跑；`command_catalog.py --check` 随 echo 帮助面改动复跑（当前 77 topics 基线）。
4. EP1 清扫后：树卫生复扫（根部 .mypy_cache/.ruff_cache 应清除；**保护 domains/ untracked 树与 domains/weather/assets/qx.json**）+ `verify_hashes.py --check`（domains 迁移若改动受册文件需先 --write 重录）。
5. LOG 席 V21-UPDATE-LOG.md 落稿后：doc_sync --check 一并复跑（文档面一致性门）。

**B. 全量 pytest 何时该跑**：上述 1-4 全部收口、collect-only 达到「N collected, 0 errors」、ruff/mypy 给出全量真实数字后，由 S16 收口席统跑全量（`dev.ps1 -Task test` 或等价直跑）；在飞期间任何红绿数字均不可用于收口判定。

**C. 剩余已知红项/尾巴清单**
- 【在飞·阻断】service.py:215 SyntaxError → 等 S14b/RWOCc。
- 【在飞】ruff 36 错（§4 明细）；test_v21_s14_incident.py:364 `RecoveryOutcome` 未定义（F821）预计同样是 S14b 未完成的导出/命名。
- 【在飞】doc_sync 2 行漂移 → 收口 sync。
- 【环境项】BOT_KNOWLEDGE_FILES 两外部文件缺失（SBX 席同源登记）；属用户外部目录，GATE 未核查。
- 【EP1 域】根部 .mypy_cache/.ruff_cache 残留待清。
- 【不可证→unknown】mypy 历史存量 control_plane/api/platform.py 2 错：本轮被语法错误阻断未能验证，复跑后确认。
- 【风险提示】domains/ 树整体 untracked + 旧 sources/data/qx.json 显示已删——git 提交裁决权在用户；清扫波严禁波及。

—— S15 GATE 席，全部结论基于本报告所列命令实跑（原始日志 %TEMP%/v21r2-gate-logs/），无编造项；未修任何码、未做任何 git 写操作。
