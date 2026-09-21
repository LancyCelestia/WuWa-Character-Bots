# v21r4-B 重启就绪快照（RESTART-GATE 席 25 分钟处阵亡，主代理席吸收收口 · 2026-09-20 14:1x）

> 时点证据：RESTART-GATE 席与主代理席合并产出。在飞席位（TTS/前端）仍会改树，非合流终态。

## 一、结果总表

| 项 | 结果 | 归属 |
|---|---|---|
| 全量回归 | **8561 passed / 4 failed / 12 skipped / 3 xfailed**（570s，历史最高通过数） | 4 失败全在飞面：echo.py 哈希族×2（test_verify_hashes_manifest_clean/test_builder_drift_gate）=TTS 席在飞；test_main_ingress_capability_ids=TTS 根文件在飞编辑窗口；test_webui_http=前端在飞（历轮基线同在）。**后端波零回归** |
| 插件导入冒烟 | `import bot; import plugins.bot_unified_runtime` = ok（3.39s，venv 3.12.10） | — |
| ruff check . | 23 处可修（在飞席文件为主） | 前端/TTS 在飞面，不代修 |
| verify_hashes --check | 1 DRIFT=echo.py | TTS 在飞，重录归其收口 |
| doc_sync --check | PASS (exit 0) | — |
| command_catalog --check | current (77 topics) | — |
| pre_restart_check.py | PASS 5 / SKIP 1（控制面未启用）/ **FAIL 3** | hash_ledger=echo.py 在飞；kb_drift=ANN 35341 vs chunks 4611（等你裁决的已知漂移，解释文档 v21r4-kb-drift-explainer.md）；ruff=在飞文件 |
| SnowLuma 3001 | 在线可达 | — |

## 二、能否立即重启（证据化判定）

**能起**：全量 8561P 零后端回归 + 导入冒烟通过 + 三个文档类门禁 PASS。三个预检 FAIL 均为在飞/已知项，不属于阻断级：hash 与 ruff 随 TTS/前端收口自愈重录；kb_drift 是等你裁决的存量（忽略或重建均不影响启动）。

**最坏情形**=某新功能（四直连门/WIRE-SVC 服务门，全部缺省关）行为异常——不拨门即零行为变化，历史功能经垫片保底。

## 三、重启步骤（建议序列）

1. **先处置双实例**（见 v21r4-b-20260920-alert-triage.md）：提权杀两个现存 bot.py 进程。
2. 跑 `PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe scripts/pre_restart_check.py`（预期同上三 FAIL，可接受）。
3. 提权**先 SnowLuma 后 bot.py**，bot 必须用 venv 解释器单实例启动。
4. 首问观测：日志 `loop-watchdog` 心跳、`served_by=` 路由轨迹；管理命令四直连门/服务门均缺省关，拨门才生效。
5. live 证据采集：真实对话后跑 `python scripts/collect_v21r4_live_evidence.py [--json]`（九项统计）。
6. 真机验收清单：docs/design/v21r4-b-restart-acceptance-checklist.md。
