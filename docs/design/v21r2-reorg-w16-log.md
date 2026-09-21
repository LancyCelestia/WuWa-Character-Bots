# v21r2 板块重组 W16 席施工日志 — location 域（2026-09-18）

> 席位：RW16（板块重组执行·第 16 波）。施工图：`v21r2-reorg-plan.md`（761 行版 §2.1 #5/§2.2/§2.3/§6）。
> 零 git 写操作、未 commit（共享工作树多席并行，提交裁决权在用户）。
> 固定解释器 `ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1`；pytest `--basetemp=$TEMP/v21r2-rw16 -p no:cacheprovider`；未跑 dev.ps1（席位禁令）。

## 一、认领与占域

- 认领时在飞：RW12 subscribe / RW13 assistant / RW14 render（COORDINATION 实时核对）；RW15 未声明。
- 方案书 19 域盘点：已完成 11 域（link_parse×2/music/weather/food/divination/meme/finance/notes+files/schedule/media），chat_reply/ops/core 本席禁认领，transport 热区按规则②仅当非热域已尽才可认领——**剩余非热域唯一=location（5 件，方案书 §5 波次表未显式列出的最小区）**，本席认领。
- 09:xx 先落占域行再动工。**并发竞态如实登记**：RW13 席随后报告「COORDINATION 无 RW16 占域留痕」，复核实证占域行已在盘（L34，RW13 完成行追加于其后）——RW13 读取的是本席 Edit 落盘前快照，竞态窗口自然消解，未重写文件。

## 二、移动清单（文件系统 mv）

| 旧路径 | 新路径（canonical） |
|---|---|
| `capabilities/wiki.py` | `domains/location/capabilities/wiki.py` |
| `capabilities/moegirl.py` | `domains/location/capabilities/moegirl.py` |
| `character/kb_wiki.py` | `domains/location/knowledge/kb_wiki.py` |
| `sources/mediawiki.py` | `domains/location/data/mediawiki.py` |
| `sources/moegirl.py` | `domains/location/data/moegirl.py` |

新建包文件 6：`domains/location/__init__.py`（域根）+ `capabilities/knowledge/data` 三子包 `__init__.py` + **`poi/__init__.py`**（§2.2 结构性空白预留，reserved docstring：POI/地图/导航等外部数据源立项）+ **`extensions/__init__.py`**（W-PA5 每域扩展槽，reserved docstring）。`domains/location` 合计 11 文件。

kb_wiki.py 携 R3 席已收口 WIP（停摆批 `_SYNC_TASK_MUTEX`/`KbSyncCancelled` 等，git status M 态）随迁，**零内容改动**（除下述 import 修正）。

## 三、真身随迁修正（3 处 import）

1. `kb_wiki.py:33` 相对导入 `from .vector_knowledge import (...)` → 绝对 `from plugins.bot_unified_runtime.character.vector_knowledge import (...)`（vector_knowledge 留守 character，chat_reply W15a 未动）。
2. `capabilities/wiki.py:19` → `from plugins.bot_unified_runtime.domains.location.data.mediawiki import (build_wiki_brief, wiki_lookup)`（兄弟切 canonical，多行化）。
3. `capabilities/moegirl.py:29` → `from plugins.bot_unified_runtime.domains.location.data.moegirl import (DEFAULT_API_BASES, MoegirlHit, moegirl_page_summary, moegirl_search)`。

跨域消费零改动（W7 裁定口径：跨域走现行垫片）：`sources.parsers.http_util`（wiki/moegirl/mediawiki/data_moegirl 四处）、`capabilities.user_copy`、`contracts`。驻留模块消费方零改动靠垫片覆盖：根 `__init__.py:49/71/1799`、`runtime/base_router.py:62/82`、`character/providers.py:667`、`character/knowledge_service.py:521`、`smoke.py:3267`、`console_chat.py:57`、`route_demo.py:27`、`sources/acg_search.py:182`。

## 四、垫片（5 张，PEP 562 活转发）

**技术选型偏离标准波**（方法论①）并升格为全 5 张活转发，依据 W11 新技术：

- **时序分裂实锤 1**：`sources/acg_search.py:182` 调用期函数级 `from ...sources.moegirl import moegirl_search` × `tests/test_v21r2_acg_search.py` 打 canonical 模块补丁——纯 re-export 快照垫片下补丁不可达，必红。
- **同型风险 2**：根 `__init__.py:1799` 调用期 `from .character.kb_wiki import _get_shared_store, run_kb_sync_task`（最热区）——活转发一并免疫未来 canonical 补丁。
- PEP 562 `__getattr__` 实时解析 canonical，读路径恒新鲜；显式私名转发自然覆盖（`_get_shared_store`/`_SYNC_TASK_MUTEX`/`_cached_get_json`/`_COMMAND_RE`/`_KB_PROVIDER_CACHE` 等全部免枚举）。

**冒烟实证**：插件导入 OK + 5 垫片 36/36 名（含全部私名）same-object `is` 断言 + 调用期旧路 import 解析 OK。

## 五、波前取证与 monkeypatch 波内清零

取证：rg 全量 import/字符串扫描（plugins+scripts+tests）+ 多行 setattr/mock.patch -U 扫描 + star-import 消费检查（全树零 `import *` 消费旧五路径）+ verify_hashes/doc_sync/echo 帮助/包 `__init__` 锚定检查（零锚定）。

**补丁式测试改写 5 文件**（9 处 import 位点 + 补丁位点 15 处随导入切换生效）：

| 测试文件 | 命中形态 | 改写 |
|---|---|---|
| `test_chat_and_sources_regressions.py` | 对象式 setattr×8（`mediawiki.http_get_json` 等） | 模块导入切 `domains.location.data` |
| `test_moegirl_search.py` | 对象式×8 + 函数级 import×9（`src`/`cap` 别名） | 全部旧路位点切 canonical（顶块 2+函数级 7） |
| `test_moegirl_question_fix.py` | **字符串式×1**（多行 setattr 第一参 `"plugins...capabilities.moegirl.moegirl_search"`，单行正则扫描盲区，-U 扫描抓出） | 补丁目标串切 canonical + 顶块导入切 canonical |
| `test_v21r2_acg_search.py` | 对象式×2（canonical 补丁 × acg_search 调用期旧路 import 时序分裂） | 导入切 `domains.location.data`（配合 PEP 562 垫片闭合分裂） |
| `test_v21r2_stall_kbsync.py` | **手工直赋补丁×2 对**（`kb_wiki.sync_kb_wiki = patched` 无 monkeypatch 包装，rg setattr 扫描盲区，逐行用途审计抓出） | 模块导入切 `domains.location.knowledge` |

纯 import 测试 6 文件垫片覆盖零改动：test_kb_wiki_sync / test_moegirl_yield_fix / test_sdd9_n3re / test_traditional_triggers_2 / test_trigger_english / test_word_boundary_fix / test_phase0_3_features（函数级旧路 import 纯读取，活转发覆盖）。

**AST 名字级终验**（974 文件全扫）：旧路径补丁目标残余 **0**（含字符串式/对象式别名解析）；其余字符串常量命中仅 acg_search.py 文档字符串一处（非锚定）。退出码 0。

## 六、回归实跑

| 门 | 结果 |
|---|---|
| 显式受影响批 12 文件 | **436 passed**（ruff --fix 后终态复跑再证 436 passed，0 failed 0 skipped） |
| 关键词全库扫 `-k "wiki or moegirl or mediawiki or acg or knowledge"` | **288 passed / 7493 deselected / 0 收集错**（终态复跑同绿） |
| `tests/verify_hashes.py --check` | exit 0 |
| `test_doc_sync_gates.py` | 4 passed |
| `test_no_source_tree_data_writes.py` | 5 passed |
| qx.json | `domains/weather/assets/qx.json` sha256 前缀 `e8285e77d8edf2f9` 完好（W3 家），旧位 `sources/data/` 不存在=W3 终态正确 |
| 渲染契约 | 未跑（本波未触 output/） |
| `scripts/runtime_layout_smoke.py` | FAIL×2=BOT_KNOWLEDGE_FILES 两份库街区百科 .md 在用户外部目录缺失（**外部环境漂移**，RW5/RW9/RW10/RW11 四席同款归因，非本波引入，需用户归位或改 .env） |
| ruff（本波 18 文件） | `--fix` 收 3 处 I001 后 **All checks passed**；--fix 后受影响两文件复跑 47 passed |
| mypy（**权威口径复刻**：`--explicit-package-bases --ignore-missing-imports plugins`，cache 置 TEMP） | **547 文件、2 错全在 `control_plane/api/platform.py:79/:254`**（台账 #36 既有基线，与本波零交集）；本波 18 文件零错 |
| 插件入口冒烟（§6 ⑦） | plugin import OK + mail_adapter ResilientMailAdapter + location canonical 可导入 |

## 七、偏差与诚实登记

1. **一次编辑事故（已修复）**：改写 test_moegirl_search.py 顶部导入块时 old_string 卷入 `runtime.base_router.RouteKind` 行致误删，下一个 Edit 即发现并原位恢复，47 passed 复跑实证无损。
2. **mypy 口径教训（后续席避坑）**：先以 `mypy plugins/bot_unified_runtime` 直跑=非权威口径，遭 transport/extensions 他席在飞语法错阻断后，换参试跑产生 assistant 域 dual-name **假错**（调用缺 `--explicit-package-bases`，模块根推导漂移所致，非代码缺陷——Python 导入被全部测试实证正常）。最终复刻 dev.ps1 权威 flags（只读 dev.ps1 取参，未执行 dev.ps1）得 547 文件/2 既有错干净信号。**权威命令=`python -m mypy --explicit-package-bases --ignore-missing-imports plugins`**。
3. **树卫生发现与处置**：仓库根曾存在 `.mypy_cache`（多席累积，含本席早期非权威口径试跑写入可能），已 `rm -rf` 清除；终态全树 `__pycache__/*.pyc/.pytest_cache/.ruff_cache/.mypy_cache` 零残留。建议后续席 mypy 一律 `--cache-dir` 指向工作区外。
4. **并行席在飞瞬态**：`domains/transport/extensions/__init__.py` 曾为裸文本行（无引号包裹）语法错（他席 WIP，02:57 重写后自愈为正规 docstring），期间零触碰、 Scoped mypy 绕行取信号。
5. kb_wiki 携 R3 席已收口 WIP 随迁零内容改动（W6/W9/W10/RW11/RW13 先例）。
6. 本波 12 测试文件迁移前基线未预跑（纯重构波，验收=终态 0 failed 0 skipped 全绿，如实说明）。

## 八、遗留与移交

- **W-PA1 creation 骨架波未做**（§10：`domains/creation/{tts,image,extensions,_common}/` 占位+DTO 草案）——独立小波，零移动零冲突，留待后续席或尾声波。
- **W-PA4 search adapters 槽**随 W16（ops+core）波——ops/core 本席禁认领，未建。
- `location/poi/` 与 `location/extensions/` reserved 占位已建（本席域内 W-PA5 义务履行）。
- 垫片退役：5 张 PEP 562 垫片待尾声波统计旧路径 import 残留后统一裁决（依赖方：根 `__init__`、base_router、providers、knowledge_service、smoke、console_chat、route_demo、acg_search、6 个纯 import 测试文件）。
- 真机验收无新增项（纯搬家，行为零变化；link_parse parsers/platforms_moegirl 虽同名异域本席零触碰）。
