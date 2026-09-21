# v21r2 板块重组 · chat_reply 热区 · 子波 2/5（RWC2 席）执行日志

- 波次：方案书 §5 W15 拆五子波之 **15b llm_engine 11 件**（15a character=RWC1 在飞 → **15b 本席** → 15c policy+security → 15d runtime 核心+ingest/pipeline → 15e capabilities）
- 日期：2026-09-18；工作树多席并行（RWC1/S9/W-PA1 等同时在飞），零 git 写操作
- 纪律：固定 venv 解释器、PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0、pytest --basetemp=%TEMP%/v21r2-rwc2 -p no:cacheprovider、未跑 dev.ps1（席位禁令）

## 一、范围裁定（简报 candidates 偏差，以方案书为准）

简报 candidates 所列 runtime/pipeline.py、runtime/ingress.py、runtime/base_router.py 属方案书 §5 **15d（子波 4）**；decision/ 9 件归 `domains/core/decision/`（§2.3 L321，W16 core 波）；capabilities/chat.py 属 15e（子波 5）。本席按「以方案书为准」取 **15b llm_engine 11 件**，其余留给后续席位——已在 COORDINATION 占域行如实登记。此裁定沿 RW15 席先例（简报原派与实读不符时，实读/方案书为准并记录）。

## 二、波前取证

1. AST 扫描器（$TEMP/v21r2-rwc2/scan.py）：全树（plugins+tests+scripts+bot.py）旧路径 `plugins.bot_unified_runtime.llm*` / `runtime.pricing` / `runtime.model_schedule` 的 import、setattr 目标、字符串锚全量清点。
2. 波前状态：llm/ 9 件 + model_schedule/pricing 共 9159 行；WIP 面=channel_health/model_router/model_schedule（M，R1 席已收口未提交）+ billing_*×3/usage_service（untracked，S5 批）——按 RW6/RW9/RW10/RW15 先例随迁零内容改动。
3. 消费面：插件侧 30+ 文件（root __init__:98/99/4076/3898、backend_unit、console_chat、config_readiness、smoke、capabilities/{chat,debug,runtime_admin}、control_plane/{_app,api/llm,llm_admin,factory,sandbox,api/v1}、runtime/{database_broker,usage_monitor}、bot.py 0 处、scripts/probe_intimate_route.py）全部走旧路径——垫片覆盖，未改一字（chat_reply 热区 call-time import 密集，禁碰消费方）。
4. monkeypatch 命中清单（波前）：OBJ 式模块对象补丁 29 处/12 文件 + STR 式 2 处/2 文件（见 §四）。
5. 交叉验证：llm_engine 11 件内部闭环（model_router 不引 runtime.pricing/model_schedule；pricing/model_schedule 零跨模块依赖）；对外仅 contracts.runtime、audit.logger（留守，不动）。
6. verify_hashes TRACKED_FILES 零 llm 引用；outbound_registry「runtime/model_schedule.py:133/:162」trace 字符串=决策引擎 trace 数据表，零 domains/ 同步先例（W16 core 波统一对账），未动。

## 三、移动（文件系统 mv，shutil）

11 件 → `plugins/bot_unified_runtime/domains/chat_reply/llm_engine/`（平铺，含包 __init__）：
llm/{__init__,model_router,providers,channel_health,ledger,billing_entities,billing_pricing,billing_service,usage_service}.py + runtime/{model_schedule,pricing}.py

### 真身随迁修正（19 行 / 7 文件，旧路→canonical）

- `__init__.py`：`from .providers import` → 绝对 canonical（方案书「相对→绝对」）
- `model_router.py` ×9：:53 包级 import + 6 处惰性 channel_health + 2 处惰性 ledger
- `channel_health.py` :678 惰性 model_router（_resolve_api_key 私名跨件）
- `ledger.py` :37 providers；`usage_service.py` :39 ledger
- `billing_pricing.py` ×3 billing_entities；`billing_service.py` ×3（billing_entities/billing_pricing/ledger 惰性）

## 四、垫片（11 张，PEP 562 活转发，W11/W16 模板）

- 10 张模块垫片：llm/{model_router,providers,channel_health,ledger,billing_entities,billing_pricing,billing_service,usage_service}.py + runtime/{model_schedule,pricing}.py = `__getattr__` 实时解析 canonical。**升格活转发的理由**：chat_reply 热区消费方（runtime_admin/chat/control_plane/usage_monitor 等 30+ 文件）大量 call-time 旧路 from-import × 测试 canonical 补丁 = 时序分裂（W11 实锤同型），纯 re-export 薄壳会假绿。
- llm/__init__.py 包垫片特殊形：先取 canonical 包属性、AttributeError 再惰性 import canonical 子模块（治 `from llm import model_router` 型子模块名 from-import；import 机器把垫片子模块文件绑为包属性属预期，属性级活转发保同源）。
- 垫片同一性冒烟：83 断言全部 same-object（11 垫片 × 公有+跨界私名 `_resolve_api_key/_spec_from_entry/_intimate_mode_for_session/_price_rank/_flag_value/_SCHEMA_SQL/_shared_http_client/_register_model_schedule_scheduler` 等）+ 插件根导入 OK + log_collectors 双锚分类断言 OK。

## 五、测试同波改写（16 文件 / 45 处 + 1 消费方锚）

OBJ 式模块对象补丁重定向（12 文件 29 处，import 行切 canonical）：test_auditfix_llm_route / test_bgroup_llm_route / test_channel_health / test_channel_health_v2 / test_llm_error_classification / test_llm_httpx_client / test_llm_ledger / test_llm_route_priority_v21r2 / test_model_router_channel_failover / test_model_router_failover / test_usage_card_channels / test_channel_probe_config。
STR 式补丁（2 文件）：test_v21_s9_llm_api / test_v21_s9_workspace（get_channel_health_store 补丁串切 canonical）。
caplog logger 名锚（真身 `__name__` 随迁变化）：test_llm_ledger（logger=+r.name 双处）、test_llm_route_priority_v21r2（logger= 两处）。
文件路径锚：test_control_plane_metrics（read_text 读 ledger.py DDL → canonical 路径）。
包级子模块绑定补丁（扫描器升格后补抓）：test_outdomain_fixes_20260911（`from llm import model_router as router_module` 垫片绑定 × setattr 301 行，切 canonical 三行）。
消费方锚（RW15 先例）：control_plane/log_collectors.py `_SUBSYSTEMS` 增 `"domains.chat_reply.llm_engine": "llm"`（旧锚保留），防真身 logger 事件源从 llm 降级 bot。
纯读取消费（24 测试文件 + 插件 30+ 处）垫片覆盖零改动。

## 六、AST 终验（名字级清零）

- OBJ 式旧路径补丁根：29 → **0**；STR 式：2 → **0**。
- 扫描器升格：补「包级 `from llm import <submodule> as X` + setattr(X,…)」盲区类（首版 OBJ 追踪漏此形，被 test_strip_retry 红点抓出即改即复——教训：模块对象绑定追踪必须含包属性子模块 from-import 形）。
- 残留字符串锚唯一：test_control_plane_log_collectors:116 合成 LogRecord 旧名=有意保留（验证旧锚仍分类 llm，与 _SUBSYSTEMS 旧锚配对）。
- 真身旧路径引用：grep 残余 0。

## 七、回归实跑

| 门 | 结果 |
|---|---|
| 波前基线（46 文件批） | 738 passed / 1 failed（test_sdd7_n4=RWC1 character 在飞瞬态，零交集，终批复跑自愈）/ 1 skipped / 2 xfailed |
| **波后显式批（46 文件）** | **739 passed / 1 skipped / 2 xfailed / 0 failed** |
| 插件导入冒烟 + 11 垫片 83 名同一性 | OK |
| ruff 本波 20 文件 | 18×I001（canonical 路径变长连带）--fix 归零 → All checks passed；全树 36 错零命中本波（character×6=RWC1 WIP、creation×6=W-PA1、outbound_registry×3=W16、其余 tests 既有） |
| mypy 权威口径（--explicit-package-bases --ignore-missing-imports plugins） | 604 文件 4 错全外部归因：creation/tts/contracts.py ×2（W-PA1 席在飞）+ control_plane/api/platform.py ×2（台账 #36 既有）；本波面 0 错 |
| verify_hashes --check | exit 0 |
| doc_sync + no_data_writes | 9 passed |
| runtime-layout | 唯一 FAIL=BOT_KNOWLEDGE_FILES 两份用户外部目录 .md 缺失（RW5/RW9/RW10/RW11/RW12/RW15/RW16 同款环境项，非本波引入） |
| qx.json | domains/weather/assets/qx.json sha256 e8285e77 完好（W3 席随迁后 canonical 位） |
| 树卫生 | 源码树零 __pycache__/.pytest_cache/.mypy_cache 残留（终查见 §八后清理） |
| 全库关键词域 | 见 §八补记 |

## 八、收波补记（终态）

- **全库关键词域 sweep**（-k "llm or model_router or channel_health or ledger or billing or usage_service or model_schedule or model_family or effort"）：**391 passed / 0 failed / 0 收集红**；全树 collect 隐含完成（7820 项收集零错）。
- 树卫生终态：源码树 __pycache__ 0（含清理 tests/__pycache__×1 与 domains/creation/*×4——他席运行残留，可再生缓存非数据）、根 .mypy_cache/.ruff_cache 已清、stray data/ 0。
- 未跑项（席位禁令/越域）：dev.ps1 全量门（禁）、command_catalog --write（未触 echo/config）、渲染契约（未触 output/）。
- 移交/登记：①15d（runtime 核心 18+ingest/pipeline 2）与 decision/（→core）留给后续席，简报 candidates 偏差已在 COORDINATION 登记；②runtime/settings.py:377 docstring 仍提「runtime/model_schedule.py」（15d 席随迁时顺手改）；③decision/outbound_registry.py:498 的 model_schedule trace 路径串=W16 core 波统一对账（历史零同步先例）；④mypy 基线从「2 错」涨到「4 错」的增量=domains/creation/tts/contracts.py ×2（W-PA1 席在飞 WIP，非本波）。
- 未 commit（禁 git 写）；波文件清单：真身 11（domains/chat_reply/llm_engine/）+ 垫片 11（llm/×9+runtime/×2）+ log_collectors.py 锚 +2 行 + 测试 17 文件 + 本日志 + COORDINATION 两行。
