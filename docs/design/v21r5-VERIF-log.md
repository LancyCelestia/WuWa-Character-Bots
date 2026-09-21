# v21r5 VERIF-GATES-2 预检日志（重派席）

> 术语说明：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [snowluma-setup.md](../snowluma-setup.md)。

- 时间：2026-09-19
- 工作区：c:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
- 解释器：ChatBot_Runtime venv python
- 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest --basetemp 显式临时目录 -p no:cacheprovider；只读验证席（唯一写面=本 log）；禁 git 写操作/子代理/真实 LLM/发送/重启/.env 读值；全离线。
- 预检基线：当前工作树（未 commit 状态，多席共享）。

## 门禁1：ruff 全树 lint — **FAIL（但为样式级+垃圾文件噪声）**

实跑：`powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"` → exit 1，**Found 134 errors**（90 fixable）。

原始输出（dev.ps1 末段）：
```
FURB167 [*] Use of regular expression alias `re.M`
   --> tests\test_webui_labels_backend_parity.py:161:69
...
Found 134 errors.
[*] 90 fixable with the `--fix` option
ruff.exe exited with code 1.
```

归属拆解（ruff --statistics + concise 补跑）：
- **全树 134 = 真源码面 37 + 树内垃圾 ~97**。垃圾面：`.tmp-test/`（mutation 测试残留，invalid-syntax ×6 + F821 ×4 全在此）+ 字面名 `%TEMP%/` 目录（u*_probe/extract 脚本草稿）——属树卫生残余，不是源码问题。
- 真源码面 37 规则分布：I001 未排序导入 ×21（全可自动修）、FURB167 re.M 别名 ×7、RUF100 无效 noqa ×6、SIM102 ×2、S102 exec ×1。
- 明细归属：
  - `tests/test_campus_digest.py` ×10 → **campus 在飞域（另一席正在修债），不阻断**
  - `tests/test_webui_labels_backend_parity.py` ×7 → **前端/WebUI 在飞域，不阻断**
  - `plugins/.../domains/location/knowledge/kb_wiki.py` ×3（RUF100）→ 非在飞清单，**需主会话裁决（或并入收尾统一 ruff --fix）**
  - 插件面其余 8：chat_reply policy×3+backend_unit、control_plane/dispatcher、sources/__init__、music.py、content_parser 各 1 I001（纯导入排序）→ 非三席域，**需主会话裁决（同上，trivial）**
  - tests 面其余 ~19：test_v21_dispatch_outbound_wiring/test_soak_growth/test_prfix_eat 等各 1 条样式错 → 收尾统一 fix 面
- 判定：**FAIL**；性质=样式级（34/37 可 --fix），无功能性缺陷信号；campus/webui 部分在飞归属；其余归收尾统一收敛，不构成收口阻断项但不可宣称 lint 全绿。

## 门禁2：mypy 全树 typecheck — **PASS**

实跑：`dev.ps1 -Task typecheck` → exit 0。

原始输出（末段）：
```
[dev] running mypy for project-owned code (cache outside workspace)
plugins\...\chat_reply\character\vector_knowledge.py:1664: note: By default the bodies of untyped functions are not checked ... [annotation-unchecked]
plugins\...\subscribe\adapters\social_v2.py:1379: note: ... [annotation-unchecked]
plugins\...\subscribe\adapters\music_v2.py:207: note: ... [annotation-unchecked]
Success: no issues found in 618 source files
```
判定：PASS（618 文件零错误；输出仅 annotation-unchecked note，非错误）。对比 v21r4-B 时点「mypy 剩 2 错 control_plane/api/platform.py」已收敛归零。

## 门禁3：runtime-layout 源码树/边界体检 — **PASS**

实跑：`dev.ps1 -Task runtime-layout` → exit 0。

原始输出（末段）：
```
[dev] checking external runtime data boundary
runtime-layout: PASS
source_workspace=C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot
runtime_root=C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime
runtime_data=C:\Users\LancyCelestia\Documents\MyWorkspace\ChatBot\ChatBot_Runtime\data
external_databases=knowledge_embeddings.sqlite3, knowledge_faiss.index
localstore=external cache/config/data
source_generated_dirs=empty
python_bytecode=absent
```
判定：PASS。附观察：树内存在 `.tmp-test/` 与字面名 `%TEMP%/` 垃圾目录（门禁1 噪声源），runtime-layout 的检查面未覆盖该两类，建议收尾波清理（只读席不清理）。

## 门禁4：verify_hashes 哈希门 — **PASS**

实跑：`python tests/verify_hashes.py --check` → **EXIT=0**（成功时静默，无输出）。
判定：PASS。注：任务书预警的 echo.py 漂移本次未出现（可能 TTS 席已重录或已收敛）；本次哈希门全绿，无归属项。

## 门禁5：doc_sync 机器事实册门 — **FAIL（1 项漂移，归属=在飞席新增测试文件）**

实跑：`python scripts/doc_sync.py --check` → 退出码非 0：
```
doc_sync: docs/auto-facts.md 与代码推导结果不一致；跑 python scripts/doc_sync.py --write 重生成。
```
只读复算漂移面（difflib 对比现存册 vs build_document()，未落盘）：
```
--- auto-facts.md(现存)
+++ 代码推导(重生成)
@@ -11,3 +11,3 @@
 - 帮助 topic 数：77（重名 0）
-- 测试文件数：432
+- 测试文件数：438
 - config.py bot_* 字段数：620
```
唯一漂移=测试文件数 432→438（+6，在飞各席新增测试文件所致：campus/前端/TTS 等域）。topic 数 77、config 字段数 620 均一致。
判定：**FAIL**；归属=**在飞面（多席新增测试），非代码缺陷**；不阻断，但**收口合流前必须 `doc_sync.py --write` 重录**（本席只读未执行 --write）。

## 门禁6：scripts/pre_restart_check.py 重启预检 — **FAIL×3（doc_sync/ruff 同前述归属 + kb_drift 已知用户裁决项）**

实跑：`python scripts/pre_restart_check.py` → 汇总 **PASS 5 / SKIP 1 / FAIL 3**。

原始输出（末段）：
```
检查项            说明                                   状态  详情
env_paths      .env 关键路径存在性                         PASS  wiki 根 OK; 人格副本 x1 OK; media_archive DB 父目录 OK; qx.json OK
persona_sync   人格副本与锚定一致                            PASS  [绿] 副本与锚定一致 sha256=f3de618998f662c2…（锚定于 2026-09-19T09:43:13+00:00）
hash_ledger    交付物 SHA-256 台账                       PASS  哈希台账无漂移
doc_sync       机器事实册 docs/auto-facts.md             FAIL  doc_sync: ... --write 重生成。
kb_drift       知识库 ANN==chunks 无漂移                  FAIL  ANN=35341 vs chunks=35477（已嵌入 4539）——存在向量通道漂移
ruff           静态门 ruff check .                     FAIL  [*] 90 fixable with the `--fix` option ...
napcat         NapCat WS 127.0.1:3001 可达性（提示不阻断）  PASS  端口可达（NapCat 在线）
webui          WebUI 单文件壳资产                         PASS  单文件壳 OK（958 KB，内联无外链）
control_plane  控制面配置三键                              SKIP  三键全部未配置——控制面/WebUI 未启用（不阻断重启）
汇总: PASS 5 / SKIP 1 / FAIL 3 → 存在 FAIL 项，先修再重启
```
归属：
- doc_sync FAIL = 门禁5 同源（测试文件数 432→438 在飞漂移），不阻断、收口重录。
- ruff FAIL = 门禁1 同源（134 全树/37 真源码，样式级），不阻断、收口收敛。
- **kb_drift FAIL = ANN 35341 vs chunks 35477（已嵌入 4539）**——与 v21r4-B 快照登记的 B5 kb_drift（当时 35341 vs 4611）同一问题族，属**既有登记项、重建与否待用户裁决**，非本轮新增回归；不阻断。
- 新增正信息：persona_sync 绿（锚定 2026-09-19T09:43Z）、hash_ledger 无漂移、qx.json 在位、SnowLuma 在线。

## 门禁7：抽样回归（三席域）— **PASS（54 passed / 0 failed）**

实跑：`python -m pytest tests/test_llm_failfast.py tests/test_content_route_v3.py tests/test_content_safety_v3.py --basetemp=...verif2-tmp2 -p no:cacheprovider -q` → EXIT=0。
原始输出（末段）：
```
......................................................                   [100%]
54 passed in 2.60s
```
判定：PASS。三席域抽样（llm failfast / content_route v3 / content_safety v3）全绿，无回归信号。

---

# v21r5 VERIF-GATES-2 预检报告（终）

门禁×7 逐项判定：

| # | 门禁 | 判定 | 关键证据 | 归属 |
|---|---|---|---|---|
| 1 | ruff 全树 lint | **FAIL** | 134 errors（真源码 37：I001×21/FURB167×7/RUF100×6/SIM102×2/S102×1，34 可 --fix；另 ~97 为 `.tmp-test/`+字面 `%TEMP%/` 垃圾目录噪声，含 invalid-syntax×6/F821×4） | campus ×10 在飞不阻断；webui ×7 在飞不阻断；kb_wiki×3+插件 I001×8 → **需主会话裁决**（trivial，建议收尾统一 ruff --fix） |
| 2 | mypy 全树 typecheck | **PASS** | Success: no issues found in 618 source files | — |
| 3 | runtime-layout | **PASS** | source_generated_dirs=empty, python_bytecode=absent | —（观察：`.tmp-test/`/`%TEMP%/` 不在其检查面） |
| 4 | verify_hashes --check | **PASS** | EXIT=0（成功静默）；任务书预警的 echo.py 漂移未出现 | 无归属项 |
| 5 | doc_sync --check | **FAIL** | 唯一漂移=测试文件数 432→438（topic 77、config 620 均一致） | **在飞面**（多席新增测试文件），收口前必须 --write 重录（本席未写） |
| 6 | pre_restart_check 重启预检 | **FAIL×3** | PASS 5/SKIP 1/FAIL 3：doc_sync+ruff=门禁1/5 同源；kb_drift=ANN 35341 vs chunks 35477 | kb_drift=既有登记项（v21r4-B B5 同族），重建与否待**用户裁决**；新增正信息：persona_sync 绿（锚定 2026-09-19T09:43Z）、hash_ledger 无漂移、qx.json 在位、SnowLuma 在线 |
| 7 | 抽样回归（三席域） | **PASS** | 54 passed in 2.60s | — |

**总裁决（供主会话判断能否宣布波次收口）**：
- **代码面健康**：mypy 618 文件零错、哈希门零漂移、runtime-layout 边界干净、三席域抽样 54 例全绿——未发现任何三席域（llm_engine/content_route/chat 亲密缝/content_safety/memory_sanitize/affinity/personas）FAIL，无需最小复现上报。
- **收口前残留三件事（均非功能性回归）**：①`doc_sync.py --write` 重录测试文件数（机械，1 分钟）；②ruff 37 条真源码样式错收敛（90 条全树可 --fix；建议同时清理 `.tmp-test/` 与字面 `%TEMP%/` 垃圾目录，属树卫生）；③kb_drift 知识库重建与否=既有用户裁决项，非本轮新增。
- 宁多标存疑：kb_wiki.py RUF100×3 与 8 条插件 I001 不属任何在飞清单，虽 trivial，按纪律标「需主会话裁决」，不得由本席擅自归零或代修。
- 本席全程零代码编辑、零文件修改（唯一写面=本 log）、零 git 写操作、全离线；7 门禁均实跑取证。

VERIF-SEAT DONE
