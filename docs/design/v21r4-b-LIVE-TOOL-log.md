# v21r4-B LIVE-TOOL 席位日志（断点续跑依据）

席位：LIVE-TOOL ｜ 任务：v21r4-B live 取证采集脚本（TDD，新脚本+新测试，不改既有产品代码）
交付物：`scripts/collect_v21r4_live_evidence.py` + `tests/test_v21_live_evidence_tool.py`

## 开工快照（2026-09-18）

- 协调表已追加 LIVE-TOOL 行（docs/design/v21r4-b-coordination.md 末行）。
- 九项统计口径已按 LEDGER-b memo（v21r4-b6-ledger-memo.md §四）对照**真身代码**逐一取证，
  日志格式串全部来自真身源码实测（禁臆造），证据坐标如下：

| # | 统计项 | 真格式串（源码实测） | 坐标（真身） |
|---|---|---|---|
| 1 | served_by 轨迹 | `content_route: has_session=%s mode=%s tag=%s served_by=%s refusal_boilerplate=%s attempts=%s` | domains/chat_reply/capabilities/chat.py:2003-2008 |
| 2 | 逐跳失败 | `llm route hop failed model=%s family=%s kind=%s elapsed_ms=%d timeout=%s intimate=%s`；provider_error 变体无 timeout= 段 | domains/chat_reply/llm_engine/model_router.py:2204-2213 / :2229-2236 |
| 3 | chain 长度分布 | 告警压缩形 `chain=N跳全败`；safe_summary 形 `chain=N last=x` | domains/ops/monitor/alerts.py:326（_compress）、chat.py:2495-2497（_llm_error_result） |
| 4 | 90s 冷却 | `llm route cooldown demote count=%d ids=%s`；缺省 90s（`_DEFAULT_COOLDOWN_SECONDS=90.0`） | model_router.py:1982-1986；channel_health.py:41、:457-474 |
| 5 | INTIMATE grok | 回落=`llm intimate grok fallback: grok 熔断冷却/不可用中，临时回落 head=%s demoted=%s health_filtered=%s`；命中=content_route 行 mode=intimate ∧ served_by 含 grok | model_router.py:1998-2004；chat.py:2003-2008；content_route.py route_verdict mode∈{intimate,normal} |
| 6 | 严格优先级探针 | **无独立日志行**（model_router 全文件仅 4 处 logger 调用，已核实）；探针=attempts 序列对照可选 `--expected-order`（缺序跳过=0 违例，fail-open） | model_router.py:611（_strict_priority_enabled）、:1119-1120 |
| 7 | 时段分组命中 | `model schedule switched override=%s window active` / `model schedule cleared override (outside windows)` / `(schedule emptied)`；**BOT_MODEL_PRIORITY_GROUPS 命中无日志行**（报告须如实注明） | domains/chat_reply/llm_engine/model_schedule.py:114/124-126/128-129 |
| 8 | axonhub 对照 | bot 侧 20s 掐断候选=hop failed ∧ kind=timeout ∧ elapsed_ms∈[18000,25000]（--timeout-band 可调），与 axonhub 控制台「已取消」人工对照 | model_router.py:2204-2213；bot 20s 读超时用户令保持（AGENTS.md #36 四段） |
| 9 | 告警折叠 | `[运行时告警] stage=llm … suppressed_count=N llm_kinds=[a|b]`（>1 kind 才随行） | alerts.py:332-362（build_operational_alert_text）、:352 |

- 垫片注意：`llm/` 与 `runtime/alerts.py` 是垫片，本席全部 grep 在 domains/ 真身完成。

## 进度

- [x] 协调表落盘
- [x] 九项格式取证（上表）
- [x] 测试先行（RED）：`tests/test_v21_live_evidence_tool.py` 先写；首跑实锤
  `ModuleNotFoundError: No module named 'collect_v21r4_live_evidence'`（1 error，RED 达成）
- [x] 实现脚本（GREEN）：`scripts/collect_v21r4_live_evidence.py` 落地后
  **20 passed**（`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest
  tests/test_v21_live_evidence_tool.py --basetemp=$TEMP/v21r4-livetool-green4
  -p no:cacheprovider -q` → `20 passed in 0.12s`）
- [x] 四门验收：
  1. **ruff**：本席两文件 `All checks passed!`（修掉 DTZ005/S112/ISC004×2/I001/RUF100 共 6 处，全部在本席新文件内）；repo 全树 29 处 I001 全在他人测试文件（`grep -c "collect_v21r4_live_evidence\|test_v21_live_evidence"` 对全树 ruff 输出 = **0**，与本席零交集）
  2. **command_catalog --check**：`command catalog is current (77 topics)` ✓
  3. **doc_sync**：新增测试文件致计数漂移 → 按任务书 `--write` 重生成 `docs/auto-facts.md`（5 行：RouteKind 33→34 含 TTS、topics 75→77、测试文件 326→417、config 字段 529→610、哈希清单路径 output/→domains/——后四项同时收编了并行席位在飞变更的机器事实口径，`--check` 后 rc=0；`tests/test_doc_sync_gates.py` 4 passed）
  4. **verify_hashes --check**：15 项 DRIFT 全部为 `domains/render/**`、`echo.py`、`debug.py`、`rendering-contract.md`、`DESIGN-SPEC.md` 等并行席位在飞文件（RWC6-b 已登记"红为预在飞"）；**与本席四份触点文件（coordination.md / 本日志 / 新脚本 / 新测试）零交集**，本席未跑 `--write`（不替他席在飞改动背书重录哈希）
- [x] 真实日志 smoke（只读）：
  - 默认路径两份现行日志均 **0 字节**（bot 停机态，历史在 `.old` 轮转）→ 零计报告=正确的 fail-open 形态；
  - 对 `nonebot.out.log.20260908_001222.old`（**1,602,460 行**真实历史）全量扫描：无异常无崩溃，九项全 0=诚实结果（v21r2 R1 新格式串未重启未生效，旧日志本就不该有）；
  - **诚实红线兑现：脚本能跑 ≠ 生产已验证。当前全 0 恰是「live 证据未产生」的真值。**
- [x] 树卫生：全程 `PYTHONDONTWRITEBYTECODE=1 + --basetemp + -p no:cacheprovider`，扫描无 `__pycache__/.pytest_cache/*.pyc/data` 残留。

## 交付终态

- `scripts/collect_v21r4_live_evidence.py`（~560 行，纯 stdlib，只读）：
  - 九项统计全部按真身格式串解析（本文件开工快照表坐标）；
  - CLI：`--log PATH`（可重复，缺省 `ChatBot_Runtime/logs/nonebot.{out,err}.log` 存在者）· `--json`（stdout JSON，提示语转 stderr 不污染）· `--expected-order JSON`（严格优先级探针，缺省 skip=0）· `--timeout-band LOW HIGH`（缺省 18000-25000）· `--sample N`（缺省 20）；
  - fail-open：空输入/乱格式/不可读文件/单行解析失败一律静默跳过出零计报告；
  - 文件末尾固定 print：**「live 证据需重启后真实对话产生，本工具只做采集统计」**；
  - 设计取舍：逐行按九族独立匹配（不互斥 continue）——告警文本一行同时携带 chain 压缩+suppressed_count+llm_kinds，各统计族都须计入。
- `tests/test_v21_live_evidence_tool.py`：20 例全离线（fixture 按真身格式串逐字构造），
  覆盖九项解析计数 + 序列时序分组 + 探针跳过/命中 + fail-open 三态 + CLI 端到端（人类报告/JSON/默认路径缺失）+ 只读字节不变断言。
- **重启后用法**：`python scripts/collect_v21r4_live_evidence.py [--json]`（重启+真实对话后九项即见真值；严格优先级探针需 `--expected-order '["axon-grok","aiprc-gemini"]'` 传入现行期望序）。
