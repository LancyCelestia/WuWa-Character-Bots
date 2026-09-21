# v21r2 重组波日志 — RW13 席（席位序第 13 波；执行方案书 W12 assistant 域）

> 时间：2026-09-18 02:20–03:05。认领依据：COORDINATION 实况（subscribe=RW12、media=RW11、W1b=RW8 在飞；download 已随 W9 files 收编）→ 按方案书序列下一个无冲突域 = W12 assistant。
> **编号澄清**：席位号 RW13 ≠ 方案书 W13（render）波；本席按任务指令「剩余候选域按方案书序列」取 W12，render/热区波（transport/chat_reply/ops/core）未触碰。

## 一、移动面（4 件，文件系统 mv）

| 旧路径 | 新路径（canonical） | WIP 态随迁 |
|---|---|---|
| `capabilities/daily_assist.py` (119 行) | `domains/assistant/daily/capabilities/daily_assist.py` | M（R6 文案池批，零内容改动随迁） |
| `character/daily_assist.py` (454 行) | `domains/assistant/daily/store/daily_assist.py` | M（R6 批，零内容改动随迁） |
| `capabilities/campus.py` (181 行) | `domains/assistant/campus/campus.py` | untracked（campus v1 批），零内容改动随迁 |
| `sources/campus_store.py` (109 行) | `domains/assistant/campus/campus_store.py` | untracked，零内容改动随迁 |

包 init ×5：`domains/assistant/__init__.py`、`daily/__init__.py`、`daily/capabilities/__init__.py`、`daily/store/__init__.py`、`campus/__init__.py`（一行 docstring，RW9 house style）。

**结构偏差如实登记**：方案书 §2.2 树将 `assistant/daily/` 画为平铺「capability+store 两件」——两件同名 `daily_assist.py` 平铺必撞名，按 RW5（divination/store/）与 RW9（notes/capabilities+store/）先例拆 `daily/capabilities/`+`daily/store/` 子包；campus 两件不同名，按树平铺 `campus/`。

## 二、垫片（4 张，纯 re-export 薄壳）

| 垫片 | 显式转出的跨界私名（逐名 rg 全树扫描实证，AST 复核） |
|---|---|
| `capabilities/daily_assist.py` | `_HELP_VARIANTS` `_QUERY_EMPTY_VARIANTS` `_QUERY_LISTING_VARIANTS` `_CAPTURE_VARIANTS`（test_daily_assist 模块级 from-import） |
| `character/daily_assist.py` | `__all__` + `_VARIANT_CURSORS`（test_daily_assist:291 函数级 + test_rp_style:232 父包属性式，均共享 dict 对象突变）+ `_MORNING_EMPTY_OPENERS` `_MORNING_OPENERS` `_MORNING_IDEA_NOTES` `_EVENING_OPENERS` `_EVENING_INBOX_EMPTY_LINES` `_EVENING_INBOX_COUNTED_LINES` `_EVENING_IDEA_NUDGES`（test_daily_assist 语气门） |
| `capabilities/campus.py` | `_CAMPUS_FORWARD_INTRO` `_CAMPUS_FORWARD_MAX_CHARS`（test_campus_digest） |
| `sources/campus_store.py` | 无私名外引，`import *` 即足（`_SCHEMA` 他处命中均为同名不同物的各自全局） |

垫片同一性冒烟：38 名 `is` 断言全过（ruff --fix 后复验仍过）。

## 三、真身随迁修正（4 文件）

- `daily/capabilities/daily_assist.py:76` 惰性导入 `character.daily_assist` → canonical `domains.assistant.daily.store.daily_assist`；docstring 两处路径口径同步。
- `daily/store/daily_assist.py:147` 惰性导入 `sources.food_data` → canonical `domains.food.data.food_data`（W4 已迁域直连先例）；`:36` `character.providers` 与 `:351` `llm.model_router` **有意保留旧路径**（W15a/W15b 未迁，保持可解析）。
- `campus/campus.py:28` sibling `sources.campus_store` → canonical `domains.assistant.campus.campus_store`。
- `campus/campus_store.py:4` docstring 陈旧引用 `capabilities.campus.CampusDigestService` → `domains.assistant.campus.campus.CampusForwardService`（顺带纠正历史类名漂移）。

## 四、根 `__init__.py` 消费链重定向（本波唯一热区编辑，2 块）

**为何必须动**：`test_daily_assist.py:441` 字符串式 monkeypatch 指向 `summarize_with_llm`，消费方是根 `__init__` 晨/晚报函数的**调用期惰性 from-import**。若测试改打真身而消费方仍走静态 re-export 垫片，垫片命名空间在首次导入时已捕获原函数对象，补丁不可达（双跳陷阱）→ 测试假绿/语义失效。方法①既定纯 re-export 垫片（无 sys.modules 别名先例，全树核验为零），故唯一正解=消费链切 canonical。

- `_run_daily_assist_morning_push`（:3134 区）与 `_run_daily_assist_evening_push`（:3175 区）两处惰性导入块 → canonical 新路径（唯一含 `summarize_with_llm` 的两个消费点）。
- 其余 6 处（:24/:29 顶层、:3047/:3114 惰性、:3418/:3419 campus 装配）**零改动**走垫片（非补丁目标，最小编辑纪律）；`base_router.py:38`、`chat.py:23`（chat_reply 热区）同样零改动走垫片。

## 五、测试同波改写（2 文件）

1. `tests/test_daily_assist.py:441` monkeypatch 串 → `plugins.bot_unified_runtime.domains.assistant.daily.store.daily_assist.summarize_with_llm`（+1 行注释）。
2. `tests/test_v21r2_hotzone_meal_variants.py:5` docstring 路径口径同步（非断言文本，诚实卫生）。
3. 其余命中测试（test_campus_digest/test_rp_style_directives 及全部 from-import 消费方）垫片同对象语义保活**零改动**。

**AST 名字级终验**：全 tests/ 树旧四路径字符串常量命中=0；旧路径 from-import 别名 setattr 对象式命中=0。

## 六、回归实跑（解释器=Runtime venv；env PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；basetemp=$TEMP/v21r2-rw13）

| 门 | 结果 |
|---|---|
| 域测试显式 4 文件（修后复跑） | **47 passed** |
| 关键词广域 `-k "daily_assist or campus or inbox"` | **43 passed**（2 收集错=RW12 epic/subscribe_v2 垫片在飞中间态，见 §七；其补齐私名后自愈消失） |
| lifecycle_r2+域 4 文件合并 | **68 passed** |
| test_capability_registry（AST 解析 base_router） | 18 passed |
| 全库收集红自证 | **7781 collected, 0 errors** |
| 插件导入冒烟+垫片同一性 | OK；38/38 same-object |
| verify_hashes --check | exit=0 |
| doc_sync 门 | 4 passed |
| no_source_tree_data_writes | 5 passed |
| runtime-layout | 2 FAIL=BOT_KNOWLEDGE_FILES 用户外部目录 .md 缺失（RW5/RW10 两席同证的外部环境面，与本波零关联） |
| ruff 本波面（9 域文件+4 垫片+2 测试） | 0 错（--fix 自收 6 处 RUF100/I001）；根 `__init__.py` All checks passed |
| mypy 权威口径（--explicit-package-bases，523 文件） | 2 错=control_plane/api/platform.py:79/:254 既有（多席同证），本域 0 |
| 树卫生 | 0 缓存残留、无 data/ 残留 |
| qx.json | sha e8285e77 完好 |

未跑：dev.ps1 全量门（席位禁令）、渲染契约（未触 output/）、command_catalog --write（未触 echo/config）。未 commit（禁 git 写）。

## 七、并行席瞬态事件（取证后零越域）

1. **RW12 在飞中间态**：`capabilities/epic.py`/`subscribe_v2.py` 垫片（02:47:49 落盘）最初为裸 `import *` 未转出 `_format_games`/`_normalize` → 关键词扫 2 收集错；rg 实证 `_format_games` 真身在 `domains/subscribe/capabilities/epic.py:35`，归因 RW12 波内清零职责；其补齐后错误消失（后续收集 0 错旁证）。
2. **location 席未声明开工**：02:58:46 `capabilities/moegirl.py`/`wiki.py` 垫片落盘窗口内，根 `__init__:49` from-import 瞬时 ModuleNotFoundError（lifecycle 测试收集错复现）；45s 退避后自愈（插件导入 OK、最终全库收集 0 错）。**提请**：该席开工未在 COORDINATION 留痕，建议主会话提醒补声明。

## 八、教训与移交

- **双跳陷阱显性化**：字符串 monkeypatch 的消费方若在根 `__init__` 等不改文件里做调用期惰性 from-import，「测试改打真身」必须与「消费链切 canonical」同波同件落地，二者缺一即假绿。本波以 2 块最小重定向解决；建议后续迁移波波前对每个补丁目标画「补丁模块→消费方解析模块」链路图。
- 遗留：根 `__init__` 尚有 6 处本域旧路径 import（:24/:29/:3047/:3114/:3418/:3419）按垫片期纪律保留，归尾声波统一收编；`character.providers`/`llm.model_router` 两惰性导入待 W15a/W15b 随迁直连。
