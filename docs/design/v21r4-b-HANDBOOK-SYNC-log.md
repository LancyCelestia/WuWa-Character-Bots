# v21r4-B HANDBOOK-SYNC 席日志（波末文档套用，2026-09-19/20）

> 席位：HANDBOOK-SYNC｜数据源：`docs/design/v21r4-b-doc-sync-draft.md`（DOC-SYNC §①②③ + SYNC-FINAL/-b §五/§5.4）。
> 性质：纯文档套用，零代码、零 git 写、零子代理、零 --write/--fix、零真实 LLM 调用。全文只记录「已落盘+离线证据」，不写「已生效」；全波未 commit/未重启/未部署。

## 一、编号裁决（草案两处预判被实盘推翻，已顺延并在正文同步）

1. **AGENTS.md 台账行**：草案拟 #41（其时点 #37-#40 空、#41 空闲）。实盘核验：**#41 已被「2026-09-18/19 统一收尾大波次」行占用**（套用前 grep 实证该行位于旧 186 行，行尾锚=`acceptance-manual §6.6.9/6.6.10 |` 全文唯一）。→ 本席落 **#42**，插于 #41 行后、「## 第七部分」前（保持表格连续，无空行断表）。
2. **HANDBOOK 节号**：任务书拟 §31、草案修正拟 §32。实盘核验：**§31（内容政策 v2 批，旧 2168 行）与 §32（统一收尾大波次总账，旧 2200 行）均已被占用**，实尾=§32.7。→ 本席落 **§33**，文末追加，既有章节零改动。README/HANDBOOK 内对该草案的描述行同步写实际编号（#42/§33）。

## 二、四文件改动摘要（diff 摘要：行数/节号）

| 文件 | 行数变化 | 落点与形态 |
|---|---|---|
| `AGENTS.md`（根） | 196 → **197**（+1 超长单行表行） | 第六部分已知问题台账追加 **#42 行**（v21r4-B 后端并发波：一句话总账+⑪项逐包结论含各席实跑计数+两时点基线 8531P/1F→8528P/4F 及 4 失败逐条归属+哈希占位/全量计数「以收尾实跑为准」+在飞空位 S0-ROOT-c/RET2b 剩余 4 张+裁决指针=wave-snapshot §二）；置于 #41 行后 |
| `docs/HANDBOOK.md` | 2258 → **2302**（+44 行） | 文末追加 **「## §33 v21r4-B 后端并发波总账」**（§33.1 承接定位／§33.2 交付清单 10 项／§33.3 六席终态与在飞空位／§33.4 两时点全量基线+终验四件残余／§33.5 状态口径诚实红线／§33.6 剩余待办终表 3 行）；既有 §1-§32 零改动 |
| `docs/README.md` | 105 → **123**（+18 行） | 文末追加 **「## 波次文档（v21r4-B 后端协议波，2026-09-19）」** 索引表 13 行：wave-snapshot／qa-probe-report／doc-sync-draft／l41-decision-memo／l41-exec-runbook／L60·L71·L74 立项书／b2-port-wiring-plan／b2-direct-collect-plan／command-format-review／kb-drift-explainer／b6-ledger-memo／b-restart-acceptance-checklist／v21r4-b-*-log.md 席位日志族（14 份目标件 `ls` 在盘实证后录入） |
| `HANDOFF-V21R4-20260918.md`（根） | 343 → **348**（+5 行） | 三处增量：①§5.1 交付物节末追加 blockquote 一段「v21r4-B 波交付（2026-09-19）」；②§5.3「核准数字」段后追加 blockquote 更正句（not_wired 18→**17**，L65=partial 口径差留档指 wave-snapshot §三.1）；③§6.3 追加第 5 条「v21r4-B 波 50+ 项裁定点→wave-snapshot §二」 |
| `docs/design/v21r4-b-coordination.md` | 登记行 1 行 | 开工首动作登记本席（执行中→收口时补 ✅完成） |

## 三、验证（实跑证据）

- **落点核验**（grep 计数全=1）：`^| 42 |`（AGENTS）／`^## §33 v21r4-B 后端并发波总账`（HANDBOOK）／`^## 波次文档（v21r4-B 后端协议波`（README）／`v21r4-B 波交付（2026-09-19`／`更正（2026-09-19 MAT 落定）`／`v21r4-B 波 50+ 项裁定点`（HANDOFF）——六锚点全部命中一次。
- **ruff**（实跑命令：`../ChatBot_Runtime/venv/Scripts/python.exe -m ruff check . --no-cache`，本席时点）：**Found 28 errors**（22 fixable）——10 条在 `.tmp-test/full/`（全量 pytest basetemp 残留夹具目录）、18 条 I001 import-sort 散布在飞席文件（control_plane/dispatcher.py、domains/chat_reply/{capabilities/chat,pipeline/backend_unit,policy/quiet_hours,policy/rate_limit,security/injection}、link_parse/content_parser、music、sources/__init__、tests/ 9 件）。**本席只改 .md 文件，ruff 不涉，28 错零条可归因本席**；§5.4 时点的 tests/test_tts.py F401 已不在当前错误面（在飞席位持续改树，门禁态随波流动）。未跑任何 `--fix`（等同写入，禁）。收尾判定以合流后实跑为准。
- **观察项（只记录不动手，移交收尾席）**：源码树出现 `.tmp-test/` 残留目录（ruff 10 错来源），疑某席全量直跑 basetemp 落错位；按波次禁触面本席不清不删。

## 四、诚实红线自查

- 台账 #42 与 §33 内一切计数均转写自草案 §①/§五/§5.4（各席日志时点证据），未新增结论；「在飞终态」只录日志已落盘者（RET3/RET2B-PREP/RWC6-b/RWC5-b/S0-COLLECT），S0-ROOT-c 与 RET2b 剩余 4 张保持「在飞」不预填。
- 全波未 commit → 哈希占位明示「收尾 commit 后补」；全量计数占位「以收尾实跑为准」；零「已生效/已上线」类断言（提醒双修、装配链均写「重启后才生效」）。
- 禁改面核对：草案本体/auto-facts.md/command-catalog.md/theme_tokens.py/render_hashes.json/domains/render/**/output/card_render/**/验收矩阵/tts.py·config.py bot_tts_* 块——零触碰。

—— HANDBOOK-SYNC 席收口，2026-09-19/20。
