# v21r5 CLEANUP 席日志

- 时间：2026-09-19
- 工作区：c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
- 解释器：C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe
- 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest --basetemp 显式临时目录 -p no:cacheprovider；禁 git 写操作/子代理/真实 LLM/发送/重启/.env 读值；全部不 commit。
- 任务书：依据 docs/design/v21r5-VERIF-log.md 实名三件收尾项（ruff 真源码收敛 / 垃圾目录清理 / doc_sync --write 重录）+ 复验（verify_hashes --check、dev.ps1 lint 全树）。
- 改动面红线：剔除在飞域（domains/assistant/campus/**、domains/chat_reply/**、domains/render/**、webui/echo/TTS 相关、tests/test_campus_digest.py）；verify_hashes 只 --check；哈希清单交付物零字节；qx.json 绝不可删；ChatBot_Runtime 只读；.tmp-test 被锁不强删。

## 任务 1：ruff 真源码样式收敛 — **DONE（scope 内 18/18 清零）**

**取证（2026-09-20 00:30 前后实跑，`--no-cache`）**：
- 全树真源码 39 条（I001×23/FURB167×7/RUF100×6/SIM102×2/S102×1）；在飞域占 21：`domains/chat_reply/**` I001×4（backend_unit/quiet_hours/rate_limit/injection）、`tests/test_campus_digest.py` ×10（S102+RUF100×3+I001×4+SIM102×2）、`tests/test_webui_labels_backend_parity.py` FURB167×7 → 按红线全部不动。
- **本席 scope = 18 条 / 16 文件**（39−21），全部 `[*]` 可自动修。
- 勘误记录：首次 statistics 跑出 134 系树内 `.ruff_cache` 陈旧缓存干扰（裸跑 python -m ruff 未加 --no-cache 所致）；--no-cache 复核 39 才是真值。dev.ps1 的 ruff cache 在 `ChatBot_Runtime/cache/ruff`（树外），不受影响。树内 `.ruff_cache` 系本席裸跑足迹，任务 2 一并清除。
- 垃圾目录显式扫描（`ruff check .tmp-test "%TEMP%"`）另有 53 条噪声（RUF100×11/F401×9/UP031×9/I001×8/UP009×4/invalid-syntax 计入全树门禁 1 的 134 口径），随任务 2 删除目录后消失，不属源码修复面。

**执行**：`ruff check --fix --no-cache <16 文件显式列表>` → `Found 18 errors (18 fixed, 0 remaining)` EXIT=0。未对全树跑 --fix，避免触碰在飞文件。

**被改文件清单（16）**：
- 插件面 7：`plugins/bot_unified_runtime/control_plane/dispatcher.py`（I001）、`domains/divination/data/draw_store.py`（I001）、`domains/finance/data/bond_data.py`（I001）、`domains/link_parse/capabilities/content_parser.py`（I001）、`domains/location/knowledge/kb_wiki.py`（RUF100×3，摘 3 处失效 `# noqa: BLE001`）、`domains/music/capabilities/music.py`（I001）、`sources/__init__.py`（I001）——其中 6+tests/test_v21_dispatch_outbound_wiring.py 为 untracked 新文件（git 状态 `??`，未 commit 波次新文件），改动不进 git diff 属预期。
- tests 面 9：test_a18_gate_idempotency_rollback / test_content_parser_quota_throttle / test_content_video_auto_send / test_detail_and_priority / test_metric_labels / test_pipeline_review_fixes / test_prfix_eat / test_soak_growth / test_v21_dispatch_outbound_wiring（均 I001）。

**复核结论**：diff 审读确认——文件中 `contracts.media`→`domains.core.contracts.media`、`character.providers`→`domains.chat_reply.character.providers` 等路径改写为**其他在飞席遗留的未 commit 迁移改动**（工作树旧态），本席 --fix 仅在其上重排/重格式化 import 块与摘除失效 noqa，未新增任何语义改动；kb_wiki 三处 noqa 摘除后上下文逐行核过。

**验证实跑**：
- import 冒烟（7 插件模块逐一 importlib）→ 7×OK，EXIT=0。
- 9 个被改测试文件 pytest：`85 passed in 11.56s`（--basetemp=%TEMP%\cleanup4-task1-pytest -p no:cacheprovider，全离线）。
- 样式改动（import 排序/noqa 摘除）无语义面，未触发更多测试族；campus/chat_reply/webui 域零触碰。

## 任务 2：垃圾目录清理 — **DONE**

**动手前取证（2026-09-20 00:45 前后）**：
- 进程核查：仅 2 个 bot.py（生产，数据面在 ChatBot_Runtime）+ turn-toast usage_server 在跑，均不持垃圾目录句柄；无 pytest 进程在跑；20:00 后 3 个 png 系已结束测试的残留物。
- git 追踪核查：`git ls-files .tmp-test "%TEMP%" ".ruff_cache"` → 空（三个目录均零 git 追踪物；`.gitignore` 的 `!.tmp-test/full-suite.log` 否定组实际无追踪文件，删除不产生 git 变更）。

**待删清单（先落盘后动手，仅两类 + 本席足迹）**：
| 路径 | 大小 | 内容 |
|---|---|---|
| `.tmp-test/` | 489 MB / 8236 文件 | full2 162M、D9 161M、full 160M、sus 10.5M、wide3 2.8M、D9-collect.log 0.8M，及 D2/D9-full.log/full-suite.log/v1/tts3/tts/T5/T39h/T39/T34/T30/D7/mutation_test2.py 等小件——历史测试 basetemp/mutation 残留（VERIF 点名类 1） |
| `%TEMP%/`（字面名目录） | 144 KB / 16 文件 | u*_probe/u*_scan/extract_*.py 脚本草稿 + p0-digest.md/session-22bb-digest.md（VERIF 点名类 2） |
| `.ruff_cache/` | <1 MB | 本席任务 1 裸跑 ruff 的足迹（铁律 6 源码树零缓存；非 VERIF 点名类，系自清） |

**qx.json 在位确认**：`plugins/bot_unified_runtime/domains/weather/assets/qx.json` 362,774 字节（2026-09-13 12:18）——删除前复核在位；`ChatBot_Runtime/` 零触碰。

**执行结果（2026-09-20 00:47–00:52）**：
- `.tmp-test/`：**已整树删除**（Remove-Item -Recurse，8236 文件 / 489MB 全清，post-check 目录不存在）。注：本环境 Git Bash 无 `rm`（PATH 异常），改走 PowerShell。
- 字面 `%TEMP%/`：**内容 16 文件已全清**（Remove-Item -Recurse 先删子项、最后在目录本体撞锁）；**目录壳仍锁**——某进程 cwd 停在该目录（「正由另一进程使用」IOException，非文件锁），按红线绝不强删 → **标「待用户解锁」**：请用户找到 cwd 停在 `ChatBot\%TEMP%` 的会话/终端关闭后手删空目录即可（现已是空壳，零数据）。
- `.ruff_cache/`：本席足迹已删；**00:48 曾被在飞席位裸跑 ruff 重建一次**（内容全新时间戳，系并发席行为非本席），已再删。收尾合流后建议终扫一遍（dev.ps1 的 ruff cache 在 Runtime\cache\ruff 树外，不会再生）。
- 删除后复核：`.tmp-test`/`.ruff_cache` 不存在；`%TEMP%` 空壳在；**qx.json 仍在位（362,774 字节原样）**；git 追踪物零损失（三目录本就零追踪）。

## 任务 3：doc_sync --write 重录 — **DONE（--check 归零 EXIT=0）**

- 形态确认：`doc_sync.py [-h] [--write] [--check]`（机器事实册同步门）。
- `--write` → `doc_sync: 已重生成 docs\auto-facts.md` EXIT=0；`--check` 复核 → EXIT=0 归零。
- 重录差异（git diff，5 行）：①测试文件数 326→**440**（VERIF 时点 438，此后在飞席又 +2）；②帮助 topic 数 75→**77**（重名 0，与 VERIF 门禁5 观察一致）；③config 字段数 529→**620**；④RouteKind 33→**34**（新增 `TTS`——在飞 TTS 席新增路由）；⑤哈希清单范围（19）路径从旧布局迁至新域布局（render/chat_reply/ops 域重组后的真身路径）。
- **提示（非失败）**：在飞席位仍在增删测试文件，测试文件数 440 与 RouteKind/topic 数**需终跑后再录一次**（重跑 `python scripts/doc_sync.py --write` 即可，1 分钟机械操作）。

## 任务 4：复验 — **DONE（本席范围内全绿）**

- **verify_hashes 门**：`python tests/verify_hashes.py --check` → **EXIT=0**（哈希台账 19 交付物零漂移；本席 16 个被改文件均不在哈希清单覆盖面，未破坏）。
- **dev.ps1 -Task lint 全树复跑**：**Found 21 errors**（134 → 21；18 fixable）。逐条归属（ruff concise 复核）：
  - `tests/test_campus_digest.py` ×10（S102+RUF100×3+I001×4+SIM102×2）→ **campus 在飞域**
  - `tests/test_webui_labels_backend_parity.py` ×7（FURB167）→ **webui 在飞域**
  - `domains/chat_reply/{security/injection,policy/rate_limit,policy/quiet_hours,pipeline/backend_unit}.py` ×4（I001）→ **chat_reply 在飞域**
  - **本席 scope 残余 = 0；垃圾目录噪声 = 0**（对照：VERIF 时点 134 = 真源码 37/39 + 垃圾 ~95/97）。
- 树卫生终扫：`__pycache__` ×0、`.pytest_cache` 无、`.ruff_cache` 已清未再生；`domains/*/data/` 系 v21r2 域重组源码子包（.gitignore 否定组放行，非垃圾）；`.mypy_cache/`（278KB，09-19 17:58 创建、00:49 仍有活动痕迹）**系在飞席位足迹，按红线「只删两类」不删，移交收尾终扫处理**。

---

# v21r5 CLEANUP-4 席总结

| # | 任务 | 判定 | 关键证据 |
|---|---|---|---|
| 1 | ruff 真源码样式收敛 | **DONE** | scope 18 条/16 文件全清（--fix + 复核）；import 冒烟 7×OK；9 被改测试文件 85 passed |
| 2 | 垃圾目录清理 | **DONE（一处待用户解锁）** | `.tmp-test/` 489MB/8236 文件全删；字面 `%TEMP%/` 内容 16 文件全清、**空目录壳被进程 cwd 锁住待用户解锁**；`.ruff_cache` 自清；qx.json 全程在位（362,774 字节）；ChatBot_Runtime 零触碰 |
| 3 | doc_sync 重录 | **DONE** | --write 重生成 + --check EXIT=0；440 测试文件/77 topics/620 字段/RouteKind 34（+TTS）；**终跑后需再录一次**（在飞面持续新增，非失败） |
| 4 | 复验 | **PASS（本席范围）** | verify_hashes EXIT=0；dev.ps1 lint 134→21（余 21 全部在飞归属：campus×10/webui×7/chat_reply×4）；树卫生干净 |

**遗留与移交**：
1. `%TEMP%` 空目录壳——待用户关闭持锁会话后手删（零数据，仅目录本体）。
2. ruff 余 21 条——campus/webui/chat_reply 三在飞域归属，随各席收口收敛（18 条可 --fix，1 条 S102 需评审）。
3. doc_sync 测试文件数/RouteKind——终跑后重录一次。
4. `.mypy_cache/`——在飞席足迹，收尾终扫统一处理。
5. kb_drift（ANN 35341 vs chunks 35477）——既有用户裁决项，本席不涉及。

CLEANUP-SEAT DONE
