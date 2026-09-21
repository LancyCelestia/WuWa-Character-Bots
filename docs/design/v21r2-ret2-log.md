# v21r2 RET2c 席日志——垫片退役第二梯队（RWOC 迁移面 55 张）

- 席位：RET2c（2026-09-18 开工）；施工图=`docs/design/v21r2-shim-retirement-inventory.md`（EP1 机核快照，波次归因=RWOC）+`v21r2-ret1-log.md`（RET1 先例：复验→删→批回归→终验）+`v21r2-reorg-woc-log.md` §六（RWOCc 终验：全库 AST 旧路径引用=0、monkeypatch 零 legacy 打点、59 垫片+4 包 init 收官）。
- 子集声明：**归因 RWOC 的 55 张原位模块垫片**（RWOCc §四清单逐一对应）。排除（占域在飞，零交集声明）：RET1 已退役 39 张；RET3 在飞（epic/steam 动态消费 2 张+仅测试消费方 44 张）；RWC5 根 __init__ 相关 108 张（含 contracts/decision/supervisor/audit 四张包 `__init__` 垫片——contracts 包 init 被根 `__init__.py:78` 多行 from-import 消费，RWC5 清账前禁触）；S14c 域（ops/recovery+incident+collectors 新建件）；ACC 域（ops/acceptance）；RWC6=policy/security；RK5=control_plane。
- 纪律：固定解释器 `C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=%TEMP%/v21r2-ret2c -p no:cacheprovider`；禁 dev.ps1；零 git 写操作、未 commit。

## 一、子集清单（55 张，全 PEP 562 活转发，路径前缀 `plugins/bot_unified_runtime/`）

**批1（根+audit，7 张）**：config_readiness.py / console_chat.py / diagnostics.py / route_demo.py / smoke.py / audit/file_logger.py / audit/logger.py
**批2（capabilities 5 + sources 5）**：capabilities/{debug,feature_control,platform_credentials,runtime_admin,runtime_logs}.py + sources/{credential_health,credentials,gscore_bridge,mcp_web_search_server,runtime_event_log}.py
**批3（sources 4 + runtime 6）**：sources/{search_api,search_service,search_smoke,web_search}.py + runtime/{alerts,disconnect_notice,error_report,event_service,event_store,feature_catalog}.py
**批4（runtime 4 + supervisor 6）**：runtime/{feature_gate,intent_telemetry,result_unknown,usage_monitor}.py + supervisor/{acl_windows,appcontainer_windows,ipc,job_objects,sandbox_windows,windows_sandbox}.py
**批5（contracts，10 张）**：contracts/{auto_send,character,envelope,errors,finance,media,music,request,runtime,subscription}.py
**批6（decision，8 张）**：decision/{dispatcher,engine,ingress,outbound,outbound_contracts,outbound_registry,shadow,trace}.py

合计 7+10+10+10+10+8=55。**不删**：四张包 `__init__`（audit/contracts/decision/supervisor，RWC5 面）；runtime/sources/capabilities 根 init（他波垫片与留守真身仍在用）。

## 二、批次计划（每批 10 张左右回归）→ **复验后修订（见 §三·复验结论）**

1. **退役前复验（逐张三轨）**：①rg 行级扫全库（plugins/tests/scripts/bot.py）；②AST 全库扫（import/ImportFrom 相对解析/父绑定/字符串常量/import_module/__import__）；③动态拼接专项（f-string/BinOp 静态段重组）。消费方≠0 → 该张移交不改（RET1 platforms_epic/steam 先例）；消费方=0 → 删文件。
2. **每批回归**：插件导入冒烟 + core/ops 域测试显式批 + 全库 collect-only 零错；红=回退该张并归因。
3. **终验**：退役张旧路径关键词全库扫 + verify_hashes --check + doc_sync + runtime-layout + 树卫生。
4. 收官向 `v21r2-COORDINATION.md` 追加一行。

## 三、执行台账（随批追加）

- **复验结论（定案前提修正）**：简报前提「RWOCc 已证全库 AST 旧路径零残余」**取证面核实为 canonical core+ops 两树**（woc-log §六原文），非全库；RWOC §五明写「纯名字导入消费（contracts 159 文件+decision/supervisor/monitor/features 族 50+ 文件）垫片覆盖零改动」——55 张在广域仓库仍有 **284 处 from-import + 17+ 处父绑定** 按设计走垫片。逐张普查（脚本 `$TEMP/v21r2-ret2c/scan.py`+`census.py`，AST 相对导入修正后复跑）：**真零消费仅 4 张**；15 张被根 `__init__.py` 顶层相对导入静态消费（`from .diagnostics import`/`from .audit.file_logger import`/`from .capabilities.platform_credentials import`/`from .config_readiness import` 等，root __init__ 属 RWC5 禁触面）→ 全部按「消费方≠0 不退役」移交。基线：全库 collect-only **8122 collected / 0 error**（EXIT=0）。
- **修订后退役批（4 张，单批）**：sources/credentials.py + supervisor/sandbox_windows.py + decision/outbound_contracts.py + decision/outbound_registry.py。
- 批1 回归：（待填）
- 终验：（待填）
- 移交清单：见 §四。
