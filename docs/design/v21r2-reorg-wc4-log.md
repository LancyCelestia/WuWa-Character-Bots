# v21r2 板块重组 — W15d 执行日志（RWC4 席，chat_reply 子波 4/5）

> 波次：方案书 §5 W15 = chat_reply 主体 71 件之**子波 4/5（15d）= runtime 核心 18 + ingest/pipeline 2**。
> 席位：RWC4。工作树多席并行 WIP 共享，**零 git 写操作**；dev.ps1 未跑（席位禁令）；未 commit。

## 一、移动清单（20 真身 + 3 包 init + 20 垫片）

| 旧位（→ 垫片） | 真身（canonical） |
|---|---|
| `runtime/{pipeline,base_router,settings,natural_language,question_intent,mentions,parrot,aliases,ingress,cache_policy,group_cache,time_window,deadline,event_idempotency,prompt_audit,prompt_preview,capability_registry,content_route}.py` ×18 | `domains/chat_reply/runtime/` 同名 |
| `message_context.py`（插件根） | `domains/chat_reply/ingest/message_context.py` |
| `backend_unit.py`（插件根） | `domains/chat_reply/pipeline/backend_unit.py` |

- 包 init ×3：`domains/chat_reply/runtime/__init__.py`（镜像旧 runtime/__init__ 的 3 名再导出：RuntimeControlState/RuntimePipeline/offload_capability，包级导入语义双向兼容）；`ingest/__init__.py`、`pipeline/__init__.py`（docstring 占位）。
- 垫片形态：**PEP 562 活转发**（W11/W16/RWC2 形态：`__getattr__` 调用期解析 canonical），治「主链咽喉 call-time 旧路 import × 测试 canonical 补丁」时序分裂。旧 `runtime/__init__.py` 与根 `__init__.py` **零改动**（模块级导入经垫片自然中继）。
- 方案书未列清单的 runtime 留守件零触碰：`capability_protocols/database_broker/loop_watchdog`（方案书后新增件）+ `error_report 族 8 件/feature_catalog/feature_gate/video_pipeline`（W16 ops 归属）；RWC2 已落垫片 `runtime/{model_schedule,pricing}` 零触碰。
- WIP 随迁零内容改动（仅下列 §二 导入切换）：M 态 ×5（pipeline/base_router/settings/aliases/capability_registry）+ untracked ×1（content_route，R-18 批真身）。

## 二、真身随迁修正（5 文件 8 处导入）

1. `pipeline.py`：event_idempotency → canonical（feature_gate/error_report/decision.shadow/capabilities/contracts/output/policy/sender/audit **保旧路径**=未迁真身或既有垫片，禁前向引用）。
2. `base_router.py`：capability_registry、natural_language → canonical（capabilities/* 26 触发判别保旧路径待 W15e）。
3. `settings.py`：`..control_plane.config_store` 相对导入 ×2（TYPE_CHECKING + 惰性）→ 绝对（从新深度 `..` 语义已变，必须绝对化）。
4. `prompt_preview.py`：prompt_audit、settings → canonical。
5. `backend_unit.py`：pipeline、settings → canonical。
- 深度锚核查：20 文件 `parents[]`/`__file__`/`_PROJECT_ROOT` **零命中**（RWC1 式深度锚风险本波天然免疫）。

## 三、monkeypatch/路径锚波内清零（AST 清单机读直驱）

- **OBJ 式 ×8/6 文件**（setattr 目标=旧路模块绑定 → import 切 canonical）：test_config_control_service（settings.os ×2）、test_content_parser_quota_throttle（cache_policy）、test_perf_final（base_router ×2）、test_perf_p3（settings）、test_route_order_semantics（base_router ×2）。
- **ASSIGN 式 ×2/1 文件**：test_pipeline_review_fixes `_chat_pool`/`_chat_pool_gate` 手工直赋（绑定切 canonical pipeline_module）。
- **STR 式**：测试面 0 命中（仅 test_perf_final:1 docstring 模块路径，随波已改 canonical）。
- **文件路径负载锚 ×8 文件**（read_text/Path 段拼接，AST 单串扫描漏 Path 段形，按 W6 教训补扫抓全）：
  `scripts/doc_sync.py`(_route_kinds)、`scripts/command_catalog.py`(ROUTER_SOURCE+ALIASES_SOURCE)、`scripts/extract_trigger_words.py`(BASE_ROUTER_MODULE+BASE_ROUTER_REL——**不改则 AST 解析读到垫片 15 行壳，触发词提取静默空转**)、`scripts/gen_trigger_pinyin.py`、`tests/test_documentation_consistency.py`(SETTINGS_PY+_DISPATCH_SOURCES+入口测试共 6 锚)、`tests/test_doc_sync_gates.py`、`tests/test_capability_registry.py`(BASE_ROUTER_PY)、`tests/_autosync_fixture.py`(scratch repo 复制清单 ×2)。
- **log_collectors._SUBSYSTEMS** +1 canonical 锚 `domains.chat_reply.runtime.pipeline → pipeline`（`_namespace` 系**前缀**匹配，真身迁移后旧锚 `runtime.pipeline` 不再命中，不补则 pipeline 事件源降级 bot；旧锚保留。settings 无锚前后同为 bot 零差异不补）。
- **AST 名字级终验最终态：OBJ 0 / ASSIGN 0 / STR 0**；TXT 残余全为装饰性散文（历史叙述 docstring，无 read_text 负载），逐条列名：test_capability_registry:1、test_content_route:1、test_nickname_verb_gaps:1、test_runtime_settings_restart_required:1、test_time_window_summary:1、command_catalog:1/:201、extract_trigger_words:1/:393、gen_trigger_pinyin:1、settings.py:354-363、finance/market_data:167、sources/web_search:1、chat_reply/capabilities/group_info:1（RWC3 域未触碰）。

## 四、回归实跑（解释器=Runtime venv；env PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0；basetemp=$TEMP/v21r2-rwc4/*；-p no:cacheprovider）

| 轮 | 范围 | 结果 |
|---|---|---|
| 批A 改写+锚文件（11 文件） | config_control/content_parser_quota/perf_final/perf_p3/route_order/pipeline_review/capability_registry/doc_consistency/doc_sync_gates/autosync_gate/autosync_hook | **240 passed** |
| 批B1 咽喉面 | a18/a19/affinity_query/bgroup/catalog_b10/content_route/deadline/decision_shadow/detail_priority/divination_hijack/event_idempotency/finance_wiring/finance_routing/group_info/help×2/market_exclusion/media_archive/memory_reuse/model_admin/model_effort | **604 passed 1 skipped** |
| 批B2 咽喉面 | moegirl×2/natural_settings/nickname×2/notes/operational_failures/parrot/perf_regression/prompt_audit/prompt_preview/rate_limit/route_ignore/rp_style/feature_gate/restart_required/sdd9/settings_hot/time_window/backend_unit/internal_marker/phase0_3/reply_chain/voice_media | **398 passed** |
| 批C 剩余引用面 | auditfix×2/error×3/finance_expansion/tts/trigger×3/transport_timeout/unified_gateways/usage_cards/content_probe/hotzone×2/vision_failover/weather_guard/soak/stocks_hijack | **1320 passed 3 skipped 1 xfailed** |
| 关键词全库轮 | -k "pipeline or base_router or … or message_context"（24 词） | **644 passed 7290 deselected 0 failed** |
| control_plane 批 | services/v1/log_collectors/lifecycle/metrics/resources/m1/workspaces×2 | **215 passed** |
| 全库收集 | tests/ --collect-only | **7934 collected 0 收集错** |
| 门禁族 | verify_hashes --check **exit0**；doc_sync gates+autosync 复跑 **45 passed**；no_data_writes **5 passed**；qx.json **e8285e77 完好** | 全绿 |
| 垫片同一性 | 20 垫片 × 508 名 `is` 同对象 + `_chat_pool_gate`/ROUTE_RULES 私名活转发探针 + 插件导入 + runtime 包级 3 名 | **全过** |
| 并行移交复核 | S11 席在飞期观测两红终态复核：test_pinyin_triggers_3 收集期 StopIteration（extract_trigger_words 旧路文本锚，本波已切 canonical）+ copy_redline_gate criticals（见 §五.7） | pinyin×3 + redline gate **530 passed** |
| ruff | 波面 38 项（20 真身+20 垫片+3 init+log_collectors+13 测试脚本）——先 6×I001 `--fix` 自收后复跑 | **All checks passed**（fix 后批A 子集复跑 199 passed + autosync 45 passed 确认无副作用） |
| mypy 权威口径 | `--explicit-package-bases --ignore-missing-imports plugins`（708 文件） | 4 错全 control_plane 既有（dispatcher×2+platform×2，在飞批域多席同证），**本波 0 错** |
| runtime-layout | scripts/runtime_layout_smoke.py | 唯一 FAIL=BOT_KNOWLEDGE_FILES 两份用户外部 .md 缺失（RW5-RWC2 十席同款环境项，非本波引入） |
| 树卫生 | `__pycache__`/`*.pyc`/`.pytest_cache`/`.ruff_cache`/`.mypy_cache`/游离 `data/` | **0 残留** |

## 五、偏差与诚实登记

1. **backend_unit 编辑事故（当场修复）**：canonical 切换时误入一行自导入 `_PLACEHOLDER_NEVER`（不存在的名字），下一工具调用即发现并回退为正确两行；插件导入冒烟+批A 回归均实证无残迹。
2. **command_catalog.py:201 生成物 header 装饰行未改**：仍写「`runtime/base_router.py` 的路由/接口清单」。功能路径常量已切 canonical；再生 docs/command-catalog.md 会吸收并行帮助批在飞漂移，留尾声波统一 `--write`。零功能影响。
3. **散文 docstring 旧路径叙述残留**（§三 TXT 清单）：非负载锚，外域文件（group_info/web_search/market_data）按禁触纪律未动；settings.py 4 处字段 docstring 的「runtime/pipeline.py」为历史叙述保留。
4. **观测到 RWC3（15e）已在飞**：`domains/chat_reply/capabilities/group_info.py` 已现身（他席占域），本席零触碰；test_group_info 经 group_cache 垫片全绿证明跨垫片协同成立。
5. **AST 单串扫描盲区复证**：Path 段拼接路径（`ROOT / "runtime" / "base_router.py"`）单串模式漏检——本波靠 W6 教训先验补扫抓出 5 文件；建议后续席位扫描器把 Path 段拼接纳入常规轨。
6. 未跑 dev.ps1 全量门（席位禁令）/渲染契约（未触 output/）/command_catalog --write（见偏差 2）。
7. **copy_redline_gate 1 红（本波引入，当波收口）**：content_route.py 真身（R-18 L1 强词表检测器词库本体，2026-09-17 内容政策 v2 批落盘）自 `runtime/`（gate 扫描面外）迁入 `domains/chat_reply/runtime/`（RWC1 扩面 `domains/chat_reply/**` 扫描范围内）后**首次被扫描命中**——r18_terms ×8 critical 全为词表元组字面量（检测器判定词库，非用户可见文案，逐条核对无新增语义）。按门纪流程登记 `tests/_redline_allowlist.py` 新增 `r18_terms` 豁免（单 canonical 路径；旧垫片路径不在 scope，登记反而炸 allowlist 完整性门），理由全文见该文件。修后 redline gate+pinyin×3 全量 **530 passed**（含 allowlist_integrity）。
8. 全程零 git 写操作；qx.json 完好；personas/ 只读未触；Runtime 零触碰。

## 六、收波清单核对

- [x] 移动 20 件 + 3 包 init + 20 张 PEP 562 活转发垫片
- [x] 真身随迁 5 文件 8 处 canonical 切换；深度锚零命中核验
- [x] OBJ 8 + ASSIGN 2 + 文件路径锚 8 文件 + log_collectors 锚 1，波内清零
- [x] AST 名字级终验 OBJ 0/ASSIGN 0/STR 0
- [x] 回归六轮 3221 passed 级联全绿 + 门禁族全绿 + 同一性 508 名
- [x] ruff/mypy/layout/树卫生/verify_hashes/doc_sync/no_data_writes/qx 全过或外部归因如实登记
