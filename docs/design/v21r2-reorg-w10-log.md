# v21r2 板块重组 W10 日志（schedule 域，RW10 席，2026-09-18）

> 施工图=docs/design/v21r2-reorg-plan.md §2/§5/§6；方法论=前六波沉淀八条全守。
> 认领裁决：W1b 由 RW8 认领（COORDINATION L22）、W5=RW5 在飞、W9=RW9 在飞 → 取序列下一无冲突波 **W10 schedule（§5 表 9 件，中冲突=timesync 授时批协调窗口；R3/INT 席均已收波落日志，文件面稳定）**。

## 一、移动清单（9 件真身，文件系统 mv，零内容改动随迁）

| 旧路径 | 新路径（canonical） |
|---|---|
| capabilities/reminder.py | domains/schedule/capabilities/reminder.py |
| capabilities/auto_send/__init__.py | domains/schedule/auto_send/__init__.py（相对导入 `.parser` 随包整体搬迁保持有效） |
| capabilities/auto_send/parser.py | domains/schedule/auto_send/parser.py |
| character/reminders.py | domains/schedule/store/reminders.py |
| runtime/schedule_service.py | domains/schedule/service/schedule_service.py |
| runtime/schedule_dag.py | domains/schedule/service/schedule_dag.py |
| runtime/schedule_store.py | domains/schedule/service/schedule_store.py |
| runtime/schedule_rrule.py | domains/schedule/service/schedule_rrule.py |
| runtime/timesync.py | domains/schedule/timesync/timesync.py |

附加：domains/schedule/{__init__,capabilities/__init__,store/__init__,service/__init__,timesync/__init__}.py（docstring 薄 init）+ **extensions/__init__.py（W-PA5 reserved 占位，首行 `reserved:` docstring，§9.3/§9.4 形态）**。

## 二、真身随迁修正（4 文件）

1. capabilities/reminder.py：`character.reminders` → `domains.schedule.store.reminders`（本域兄弟直连）。`capabilities.notes` 的 from-import（含 8 个 `_NOTES_*` 下划线名）**保持旧路径走 RW9 垫片**——RW9 已在垫片显式转发该批私有名（实读核实），notes 属 RW9 域不越界。
2. schedule_service.py：dag/rrule（×2）/store 三块兄弟导入切新 canonical；**`_PROJECT_ROOT = Path(__file__).resolve().parents[3]` → `parents[5]`**（W2 同款深度锚，sys.path 注入语义保持解析到工作区根，注释注明）。
3. schedule_rrule.py / schedule_store.py：`schedule_dag` 兄弟导入切新 canonical（rrule 含 `_parse_hhmm` 私有名直连）。
4. store/reminders.py：两处惰性 `from ...runtime import timesync` → `from ...domains.schedule.timesync import timesync`；docstring 中 runtime/timesync 路径口径同步。`character.providers`（build_runtime_data_path）保持旧路径（chat_reply 域不越界）。

## 三、垫片（9 张，旧位纯 re-export 薄壳）

私有名显式转出（波前 AST 名字级全量扫描实证，波内命中测试改指真身后仍保留 API 面完整）：

- capabilities/reminder.py → `_LIST_RE`（tests/test_trigger_english.py from-import 实证）
- character/reminders.py → `_REMINDER_TEXT_TEMPLATES`（test_reminder_tone.py:149 from-import 实证）+ `_STORES`
- runtime/schedule_dag.py → `_parse_hhmm`（真身 rrule 消费，随迁后旧路径转出保 API 面）
- runtime/timesync.py → `_https_head_factory` + `_parse_http_date`（test_v21r2_stall_timesync_http.py 模块属性读取实证）
- 其余 4 张（auto_send 包两层/service/store/rrule）纯 `import *`（真身 `__all__` 或公有面覆盖，AST 扫描无私有名消费）
- auto_send 垫片为包形：capabilities/auto_send/{__init__,parser}.py 两张薄壳保留旧包路径。

## 四、monkeypatch/文本锚命中面与波内清零

- AST 名字级扫描（对象式 setattr/字符串式 patch/ATTR 赋值/import_module 四类）：**12 处命中 / 5 测试文件**，全部波内改指真身：
  - test_reminder.py（reminders_mod×5 + reminder_cap_mod `_monotonic`×2）
  - test_reminder_tone.py / test_reminder_governance_receipt.py / test_reminder_delivery.py / test_todo_checkoff.py（reminders_mod `_STORES` 各 1-2 处）
- 字符串式 `monkeypatch.setattr("旧路径…")` / `mock.patch("…")`：全库 **0 命中**。
- timesync/reminder_mod 模块别名纯读取（无 setattr）按垫片覆盖零改动——但两处**盲区补网**（W6 教训②「read_text/getattr/字面串型锚」实证再现）：
  1. test_reminder_tone.py:176：getattr 8 个 `_CHECKOFF_*` 私有模板常量——垫片未转发即 ImportError 面，改指真身（未走「扩垫片转发」路线，与命中测试同法）。
  2. **caplog logger 名锚 ×4**（test_timesync.py:169 + test_v21r2_stall_timesync_http.py:165/185/205）：`caplog.at_level(..., logger="…runtime.timesync")` 锚定模块 `__name__`，真身迁移后 logger 名变为 `…domains.schedule.timesync.timesync`，INFO 级日志收不到 → 2 测假红；4 处全改新 logger 名。
- **copy_redline_gate 扫描面随真身扩面**（方法⑧）：gate_scope() 增 `RUNTIME_PKG.glob("domains/schedule/**/*.py")`（原 capabilities/*.py+auto_send/**+character/*.py 在真身迁出后只剩垫片=门禁假绿的静默盲区）；test_gate_scope_sanity 增 3 条真身在扫描面断言（reminder.py/store/reminders.py/auto_send/parser.py@domains）。allowlist 无本域条目零失配（rg 实证）。`_AUTO_SEND_REL` 为 tmp 假样本语义 rel_path，路径无关零改动。
- test_user_copy_unification_gate 用 `RUNTIME_PKG.rglob("*.py")` 全树递归——domains/ 真身自动在扫描面，零改动。

## 五、AST 终验（名字级程序化，脚本与口径同 W1a/W6）

- 旧路径 patch/setattr/ATTR 命中：**0**；新路径命中：**12**（5 文件，全部指向 domains.schedule.* 真身）——双盲区（包入口 setattr + 多行括号 from-import）由 AST 名字级覆盖，非正则。

## 六、回归实跑（固定解释器 venv；PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；--basetemp=$TEMP/v21r2-rw10 -p no:cacheprovider）

| 门 | 结果 |
|---|---|
| ① 显式域清单 17 文件（reminder×4/todo/schedule_service_v21/timesync×2/auditfix_wave3_logic/trigger_english/traditional_triggers_2/pinyin_triggers_3/help_meta/v21_risk_red_tz/copy_redline_gate/user_copy_unification/capability_registry） | **653 passed**（修锚后复跑） |
| ① 全库关键词扫測 `-k "reminder or reminders or schedule or timesync or auto_send or checkoff or todo"` | **332 passed / 0 failed**（7437 deselected） |
| ③ verify_hashes --check | **exit=0** |
| ④ doc_sync 门 | **4 passed** |
| ⑤ runtime_layout_smoke | **FAIL×2=外部归因**：BOT_KNOWLEDGE_FILES 指向的 `C:/Users/LancyCelestia/Documents/AI智能体有关材料/鸣潮 AI智能体有关材料/` **整目录不存在**（用户侧移动/改名，.env 仍指旧路径）——与本波零关联（本波未触 config/.env/knowledge），需用户归位文件或改 .env |
| ⑤ test_no_source_tree_data_writes | **5 passed** |
| ⑥ ruff（本波 18+8 文件面） | --fix 收 14（RUF100/I001 纯格式）后 **All checks passed** |
| ⑥ mypy（口径=dev.ps1 同款 `--explicit-package-bases --ignore-missing-imports plugins`） | **5 错全外部归因**：worldbook_service×3（他席 WIP 在飞件）+ control_plane/api/platform×2（多席记录既有）；domains/schedule 与全部垫片 **0 错** |
| ⑦ 插件导入冒烟 + 垫片同一性 | **22/22 same-object 断言 OK**（含 5 私有名 + timesync/logger 面）；ruff --fix 后复验 OK |
| 树卫生 | `__pycache__/.pytest_cache/.ruff_cache/.mypy_cache/data/` 源码树 **0 残留**；qx.json 在 W3 随迁位 domains/weather/assets/（sha256 e8285e77…完好），本波未触碰 |

## 七、偏差与移交

1. **layout FAIL 外部归因**（见 §六⑤）：非本波引入，修复动作在用户侧（归位两个百科 md 或更新 .env BOT_KNOWLEDGE_FILES）。
2. W3 weather 垫片 Q03 作用域遗留（方法⑨）：本域不涉及，未越域，仍留 W15d/尾声波。
3. e2e_acceptance.py 的 timesync UnboundLocalError carve-out WARN 文本仍写旧路径——纯信息文本（按 reason 字串匹配非路径），真身该缺陷已被 R3 批修复（`global _SHARED` 在位），WARN 永不触发；scripts 零改动纪律不碰。
4. 未跑 dev.ps1 全量门（席位禁令）；未触 echo/config/command_catalog（无 `--write` 义务）。
5. 禁 git 写：全程文件系统 mv + 逐文件编辑；未 commit（共享工作树，提交裁决权在用户）。
