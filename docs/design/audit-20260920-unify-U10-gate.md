# U10-GATE 审计报告：门禁真值复跑 + 09-19 台账复核 + 文档宣称对账（2026-09-19/20 交接窗口）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。

> **席位**：U10-GATE（只读审计子代理）。**唯一可写文件=本文件**。零代码/配置改动、零 git 写操作、零真实发送/重启/进程 kill/真实 LLM 调用、未读 .env 明文、未写 `ChatBot_Runtime/`。
> **审计窗口**：2026-09-19 **15:52:4x 启动全量 pytest → 16:12 收**（T0 基准钟 `15:53:02`）。
> **对象树**：HEAD=`56d1461`（**2026-09-15** 提交）；`git status --porcelain=v1` = **867 条 @T0 → 874 条 @16:12**（426 M / 329 ?? / 112 D @T0）。渲染/echo 之外的波次 + v21r4-B 后端波**三日累积零提交**。
>
> **四条硬结论（先看这个）**
> 1. **当前树四门禁 3 红 1 红**：`test` **2 failed / 8567 passed / 12 skipped / 3 xfailed（417.57s）**、`lint` **63 errors（36 fixable）**、`typecheck` **1 error**、`runtime-layout` **FAIL（2 项，与 09-19 口径一致）**。AGENTS #41「全量 8532P/0F 四门禁全绿实跑」与 HANDOFF-V21R5 §〇「8561P/4F、后端波零回归」两条**对当前树均不成立**。
> 2. **归因错判是本报告最重要发现**：HANDOFF 把 `feature_gate` 失败归给「TTS 根文件编辑窗」，实为**本波后端未提交新代码**——`__init__.py` 工作树 diff 新增 7 处 `capability_id="bot.*"`，其中 4 处（`bot.cookie_expiry_notice`/`bot.cookie_login`/`bot.file`/`bot.group_welcome`）在 `capability_registry.py` **零登记**（该文件工作树未被改动）。单跑确定性复现。**「后端波零回归」不成立。**
> 3. **09-19 台账 20 条：已修 3（P0-1/P2-18 由并行席在审计窗口内修的也算，标注时点）｜部分修 2｜仍存 14｜无法判定 1｜（P3-22 流程项=仍存，铁证 5 波改写）**。P0 三条中 P0-1 已修（16:04）、P0-2 **半修且地雷仍在**（mypy 唯一余错就是它）、P0-3 **恶化**（837→867→874）。
> 4. **绿的可获取方式本身有问题**：`verify_hashes` 当前 0 DRIFT，但 `tests/render_hashes.json` mtime=**15:39:17**（本席 15:52 起跑前 13 分钟被 `--write` 重录）——宣称的「1 DRIFT（echo.py=TTS 在飞）」与实况同时失效；而 V2.1 §13/dev.ps1:241-246 明文警告的正是这种「把真实回归洗绿」的路径。
>
> **并发写实况（所有数字的前提）**：审计窗口内被并行会话改写的文件（mtime 实测）：`docs/design/tts-handover-20260919.md` 15:54、`v21r5-coordination.md` 15:58、`audit-…-U1-invest.md` 15:59、`domains/render/templates.py` **16:03**、`tests/test_webui_http.py` **16:04:33**（**在我 grep 到硬编码种子之后、在我全量跑之后**）、`r18-taxonomy-20260920.md` 16:06、`audit-…-U11b-sec.md`/`U4-dispatch.md` 16:09、`U2-proto.md` 16:10。`.tmp-test/` 22→35 条目 / **489MB**（`.tmp-test/D9/full/` 在两次 ruff 之间凭空出现）。**本席全量快照只对 15:52:4x 的树负责。**

---

## §A 门禁实跑快照（本席亲跑；命令全部可复跑）

### §A.1 快照总表

| # | 门禁 | 文档/交接宣称 | 本席实跑原文 | 判定 |
|---|---|---|---|---|
| 1 | `dev.ps1 -Task test`（AGENTS 五） | V21R5 §〇/§六：**8561P/4F/12S/3X（570s）**；#41：**8532P/0F** | `collected 8584 items` → **`= 2 failed, 8567 passed, 12 skipped, 3 xfailed, 3 warnings in 417.57s (0:06:57)`** | ✗ 与两种宣称都不一致（F 数与 P 数皆不同；0F 完全不成立） |
| 2 | `dev.ps1 -Task lint` | §〇/§六：「ruff **23 处可修**（在飞文件为主）」；#41「四门禁全绿」 | `Found 63 errors.` `[*] 36 fixable with the --fix option (15 hidden …)` → ruff exit 1、dev.ps1 throw | ✗ 红；数量与「可修」数都不符 |
| 3 | `dev.ps1 -Task typecheck` | #41「全绿」；V21R5 K3「scoped mypy Success 0 error（2 余错在 tts.py:330=TTS 席在飞）」 | **`Found 1 error in 1 file (checked 618 source files)`**，唯一错＝`runtime/capability_protocols.py:1273: error: Module "…sources" has no attribute "web_search" [attr-defined]` → exit 1 | ✗ 红；且余错归属错（非 TTS，是本波 P0-2 残面） |
| 4 | `dev.ps1 -Task runtime-layout` | 09-19 审计「2 项既有（BOT_KNOWLEDGE_FILES 盘外文档）」 | `runtime-layout: FAIL` + 恰 2 行：`configured BOT_KNOWLEDGE_FILES file missing: …\鸣潮库街区百科.md`、`…\战双帕弥什库街区百科.md` | ✓ **与宣称一致**（环境项，非代码缺陷；但门禁仍是红） |
| 5 | `tests/verify_hashes.py --check`（禁 --write） | §〇/§五：「**1 DRIFT**（echo.py=TTS 在飞）」 | 静默通过、`EXIT=0`（清单 19 项，含 `echo.py`、`usage_cards`） | ✗ 与宣称不符；且绿由 15:39 他人 `--write` 重录（见 §C-3） |
| 6 | `scripts/doc_sync.py --check`（禁 --write） | §〇/§六：「doc_sync PASS」 | 静默、`EXIT=0` | ✓ 成立 |
| 7 | `scripts/command_catalog.py --check` | §六：「current (**77 topics**)」 | `command catalog is current (77 topics)` `EXIT=0` | ✓ 成立（77 为真；AGENTS 顶部口径修正亦为真） |
| 8 | `scripts/pre_restart_check.py`（只读） | §六：「PASS **5** / SKIP 1 / **FAIL 3**（hash/kb_drift/ruff），无阻断级」 | 表：**PASS 6 / SKIP 1 / FAIL 2**，`REAL_EXIT=1`。FAIL＝`kb_drift`（`ANN=35341 vs chunks=4611（已嵌入 4539）`）、`ruff`（`[*] 37 fixable`）；`hash_ledger` 已 **PASS**（哈希台账无漂移）；`napcat`=端口可达；`webui`=单文件壳 950KB OK；`control_plane`=SKIP | △ 结构相符但数字不同：FAIL 3→2 只因哈希被重录转绿；ruff 计数在两次跑之间又从 36 漂到 37（活树） |
| 9 | WebUI 版式宪法门 `node scripts/layout-constitution.mjs` | #41/§〇：「GATE_EXIT=0」 | **未跑**——权限系统按调用方后置指令拦截（`Auto mode: action blocked by classifier — …stop checking non-backend areas`），两次尝试各一次即止，未绕行 | ? **无法判定**（本轮无 exit 码取证） |
| 10 | WebUI `tsc -b` | 「0 错」 | 未跑（同上拦截；且 `-b` 会写 tsbuildinfo，只读席位不宜） | ? 无法判定 |
| 11 | WebUI `node --test src/lib/graph-layout.test.ts` | 09-19：7/7 pass | 未跑（同上）。环境就绪：`node v26.7.0`、`npm 11.19.0`、`webui/node_modules/.bin/tsc.cmd` 在位、测试文件 `graph-layout.test.ts` 4027B/03:09 在位 | ? 无法判定 |

> **可复跑命令（全串）**
> ```powershell
> # AGENTS 第五部分四件（本席额外注入 BOT_AUTOSYNC=0，否则 dev.ps1:246 会默认 1 → conftest 自动 --write 洗绿）
> powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task test"        # 417.57s；TEMP 由 dev.ps1 重定向至 ChatBot_Runtime/cache/pytest_ci_<pid>，源码树零污染
> powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task lint"        # Found 63 errors
> powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task typecheck"   # Found 1 error
> powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task runtime-layout"
> ```
> ```bash
> export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0
> ../ChatBot_Runtime/venv/Scripts/python.exe tests/verify_hashes.py --check          # 禁 --write
> ../ChatBot_Runtime/venv/Scripts/python.exe scripts/doc_sync.py --check             # 禁 --write
> ../ChatBot_Runtime/venv/Scripts/python.exe scripts/command_catalog.py --check      # 77 topics
> ../ChatBot_Runtime/venv/Scripts/python.exe scripts/pre_restart_check.py            # 真退出码 1（勿管道取码）
> ../ChatBot_Runtime/venv/Scripts/ruff.exe check . --no-cache --output-format=concise
> ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_http.py tests/test_runtime_feature_gate.py \
>   -p no:cacheprovider --basetemp="$TEMP/u10-scoped1" -q                            # 1 failed, 15 passed（确定性复现）
> ```

### §A.2 两个失败逐条归因（不笼统）

**F1 `tests/test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered` — 定级 P1｜归属：后端波（v21r4-B S0 收编/统一出站）真缺陷，非在飞面**
- **锚点**：`missing = {value for value in ids if … } - set(capability_feature_bindings())`（`tests/test_runtime_feature_gate.py:237`，断言在 `:238`）。
- **实跑原文**：`AssertionError: 入站声明了未登记能力：['bot.cookie_expiry_notice', 'bot.cookie_login', 'bot.file', 'bot.group_welcome']`；单跑确定性复现（`1 failed, 15 passed in 9.76s`，非全量跑污染态）。
- **根因链（四步实证）**：①测试用 AST 解析根 `__init__.py` 收集 `capability_id=` 字面量 → ②与工作树 diff 交叉：`git diff -U0 -- plugins/bot_unified_runtime/__init__.py | grep '^+.*capability_id="bot\.'` 得 **7 条新增**（`bot.chat`×1、`bot.cookie_expiry_notice`×1、`bot.cookie_login`×1、`bot.file`×2、`bot.group_welcome`×1、`bot.poke`×1）→ ③登记真身 = `domains/chat_reply/runtime/capability_registry.py:97 ROUTE_CAPABILITY_DECLARATIONS` / `:533 CONTROLLED_INTERNAL_CAPABILITIES`，四 id 在此 **grep 命中 0**，且该文件**工作树零改动**（`git diff --stat` 空）→ ④消费面：`feature_catalog.capability_feature_bindings()` → `feature_gate.py:38 self.bindings`。
- **改法**：把这 4 个 id 补进 `CONTROLLED_INTERNAL_CAPABILITIES`（内部受控能力，非路由驱动）或为其在 `ROUTE_CAPABILITY_DECLARATIONS` 建带 `has_rule` 的声明；同步复核 `bot.chat`/`bot.poke` 之所以不红是因早已有登记（勿重复）。
- **附带后果（不是纯测试问题）**：这 4 条正是 S0 收编新增的**统一出站/自动发送**入口（`__init__.py:3032` 过期提醒、`:5375` 入群欢迎、`:5437/5452` 附近 `bot.file`×2、`:5722` cookie 登录），未登记 ⇒ 控制树看不见 ⇒ 按特性树「可停可灰」的承诺对这 4 条失效。

**F2 `tests/test_webui_http.py::test_stats_endpoints_require_bearer_and_use_common_envelope` — 定级 P0（测试卫生）｜归属：09-19 台账 P0-1 日历炸弹，与「前端在飞」无关**
- 全量跑原文：`assert payload["data"]["data"]["total_calls"] == 1` → `E assert 0 == 1`（`tests\test_webui_http.py:118`）。
- 我 15:54 grep 时 `:56` 仍是硬编码种子 `'2026-09-18T01:00:00+00:00'`；**16:04:33 并行席改写为动态种子**（现 `:57 recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()`，并新增注释「硬编码日期会在次日滑出窗口（2026-09-19 时间炸弹事故）」），scoped 复跑已 **passed**。
- **口径要点**：该文件在 `tests/` 常驻树，**HANDOFF §六 把它归为「webui（前端）」在飞面属归因错**——它是门禁自身的确定性缺陷，且是 09-19 审计立案、波次报告未落地的那一条。

**「4 失败」对「2 失败」的差异归因（逐条，不猜）**：宣称的 4 条＝`echo.py 哈希×2 + feature_gate + webui`。其中 echo 哈希 2 条**在 15:39 被 `--write` 重录后转绿**（本席 `verify_hashes --check` 0 DRIFT 即旁证）；`feature_gate`+`webui` 2 条本席复现（webui 于 16:04 后修）。⇒ 数量变化**不是**波次收敛，而是哈希基线被移动。**这正是 dev.ps1:241-246 注释所警告的机制。**

### §A.3 ruff 63 错归因（逐条到目录，`--no-cache --output-format=concise`）

| 归属 | 条数 | 明细 |
|---|---|---|
| `.tmp-test/`（源码树内 pytest basetemp 残留，P2-16） | **43** | 例：`.tmp-test\D9\full\test_auto_send_clean_sample_ze0\clean_auto.py:4:1: I001`、`.tmp-test\sus|full|full2\D9\full\…\excluded.py`（各 4 条 RUF100/I001）、`.tmp-test\full|full2|D9\full\test_run_code_debug_reports_sy0\bad.py`（各 2）、`.tmp-test\…\clean_auto.py`（各 2）、`.tmp-test\mutation_test2.py`（3） |
| `%TEMP%\`（源码树内字面 `%TEMP%` 目录，他席探针） | **2** | `%TEMP%\u3_probe_registry.py:15:84: RUF100`、`:22:8: PIE810`（3515B，mtime **15:57**＝审计窗口内并行席写入） |
| **真文件（plugins/tests）** | **18** | 全部 **I001**（import 块未排序）：`plugins/…/control_plane/dispatcher.py`、`domains/chat_reply/{capabilities/chat, security/injection, policy/rate_limit, policy/quiet_hours, pipeline/backend_unit}`、`domains/link_parse/capabilities/content_parser.py`、`domains/music/capabilities/music.py`、`sources/__init__.py`；`tests/` 9 文件（`test_v21_dispatch_outbound_wiring`、`test_soak_growth`、`test_prfix_eat`、`test_pipeline_review_fixes`、`test_metric_labels`、`test_detail_and_priority`、`test_content_video_auto_send`、`test_content_parser_quota_throttle`、`test_a18_gate_idempotency_rollback`） |
> 归因结论：**宣称「23 处可修（在飞文件为主）」两处失真**——可修数是 36（且 pre_restart_check 内口径 37），总数 63；**71%（45/63）不是「在飞代码」，而是残留目录卫生问题（P2-16 未修）+ 他席探针落盘**。真代码欠账只有 18 条同类 I001，可一次性 `--fix` 收口（属他席文件域，本席不改）。

---

## §B 09-19 审计台账 20 条复核（现状 + 坐标 + 证据）

> 判定口径：**已修**（当前树不再复现）｜**部分修**｜**仍存**｜**无法判定**。并行席在窗口内修的，一律注明 mtime 时点——审计记的是当前树真值，不是功劳归属。

| # | 条 | 判定 | 当前坐标/锚点 | 一手证据 |
|---|---|---|---|---|
| **P0-1** | 测试日历炸弹 | **已修（窗口内 16:04:33 由并行席修）** | `tests/test_webui_http.py:13` `from datetime import datetime, timedelta, timezone`、`:57` `recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()` | 我 15:54 grep 仍见 `:56` 硬编码；改写后 scoped 复跑 `test_webui_http.py` **passed**（15 passed 含它）；全量快照（15:52 起跑）里它仍红——两条口径都如实记 |
| **P0-2** | `sources/web_search.py` 垫片未兑现＝运行期 ImportError | **部分修（地雷仍在；mypy 唯一余错即它）** | 修面：`runtime/capability_protocols.py:1128` 走 canonical。残面：**`:1273-1275`** `from plugins.bot_unified_runtime.sources import (\n    web_search,  # RET2B-PREP: … 维持旧路径\n)` | ①`ls plugins/bot_unified_runtime/sources/web_search.py` → No such file；`git status` = ` D`（已删未提交）②`importlib.import_module('plugins.bot_unified_runtime.sources.web_search')` → **`ModuleNotFoundError`**（实测）③mypy：`capability_protocols.py:1273: … has no attribute "web_search"` ④`_WebChainAsSearchProvider.search()` 一旦被调即炸（W7 预留上车点） |
| **P0-3** | 提交漂移失控 | **仍存且扩大** | 工作树整体；`git status --porcelain=v1 \| wc -l` | **837（09-19 审计）→ 867（本席 T0）→ 874（16:12）**；HEAD 仍 `56d1461`（09-15）；AGENTS #42 自述「全波未 commit」为真 |
| **P1-1** | 卡片标题行高塌陷（dist 层叠） | **仍存（产物层逐字节复现）** | `webui/src/components/ui/card.tsx:31` 锚点 `cn('leading-none font-semibold', className)` | 本席 node 复算：`fs-card@949677  leading-none@949805  fs-card later(wins)? false` ⇒ `.leading-none{line-height:1}` 胜；与 09-19 偏移**完全相同**＝12h 零改动；`webui/dist/index.html` mtime **03:55:00** |
| **P1-2** | 前端三门游离于常驻回归 | **仍存** | `tests/test_webui_constitution.py` **不存在**；`grep -rln "layout-constitution\|graph-layout.test\|tsc -b" tests/` → **0 命中** | 三门仍纯手工；（本席亦因权限拦截未能取证其当前 exit 码，见 §A.1 #9-11） |
| **P1-3** | 宪法门执法面四漏 | **仍存（四漏全在）** | `webui/scripts/layout-constitution.mjs:28`（`HEX = /#(?:[0-9a-fA-F]{3,8})\b/g` 只裸 hex）、`:34`（`OFF_SCALE_SPACING = /\b(?:p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y)-…/` **无 m/mx/my/mt/mb/ml**）、全文 **grep `rounded` 0 命中**、`webui/src/components/graph/memory-canvas.tsx:179` `context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif'` | 四类违例（`mt-7`／`rounded-[9px]`／`rgba()` 内联色／canvas 字体字面量）今日仍可畅通 |
| **P1-4** | 日志页重放重复行 | **仍存** | `webui/src/pages/logs.tsx:77-88`（`appendRows`）、`:165-173`（`resubscribe`/`applyFilters`） | 实读：`const merged = [...current, ...incoming]`，全文无 `seenRef`/cursor 去重；两路径均 `sessionStorage.removeItem(CURSOR_KEY)` + `startStream(null)` 而不清 rows |
| **P1-5'** | 零 ErrorBoundary（渲染抛错=白屏） | **仍存** | `grep -rln "ErrorBoundary" webui/src/` → **0 命中** | 九页与根渲染均无边界 |
| **P2-9** | dev 代理漏 `/admin/api/v1` | **仍存** | `webui/vite.config.ts` `proxy` 块仅 `'/api/v1': { target: … }`（实读 1-30 行） | `npm run dev` 下总览页 health/进程两卡必 404（`/admin/api/v1/*`） |
| **P2-10** | 控件字号漏档 | **部分修（2 修 / 4 仍存）** | 已修：`logs.tsx:246-269` 两个 `<select>` 现带 `fs-caption`。仍存：`webui/src/components/settings/settings-dialog.tsx:106`、`:127`、`webui/src/pages/knowledge.tsx:205`、`webui/src/pages/memory-graph.tsx:144`（均 `className='h-9 …'` 无 `fs-`） | **坐标漂移警告**：`settings-dialog.tsx` 已迁至 `components/settings/`，09-19 写的 `components/settings-dialog.tsx` **已不存在**——按锚点/文件名重定位，禁按行号盲改 |
| **P2-11** | dashboard `?? 0` 造数 | **仍存** | `webui/src/pages/dashboard.tsx:184`（`formatInt(tokensData.totals?.calls ?? 0)`）、`:187`（input/output `.value ?? 0` ×2） | 锚点 `?? 0` 两命中；null（unknown quality）被伪造成「0 消耗」，与 tokens 页 `—` 口径互斥 |
| **P2-12** | 移动端无导航 | **仍存** | `app-shell.tsx:73` aside `… hidden … md:flex`；`:107` header 的 `md:hidden` 块**只有 logo+标题** | 实读 60-135：md 以下无任何 nav 条/抽屉，九页不可点达 |
| **P2-13** | a11y 三件 | **仍存（三件全在）** | ①`settings-dialog.tsx`：无 `role='dialog'`/`aria-modal`/`Escape`/焦点管理（`grep "Escape\|aria-modal\|role='dialog'"` → 0 命中，仅两枚按钮 `aria-label`）②`logs.tsx:287` `aria-live='polite'` 仍挂在滚动容器 ③`plugins.tsx:128` `<h2 className='fs-page'>` | 逐条锚点 grep 命中原文 |
| **P2-14** | theme-switch 定位参照物 | **仍存** | `theme-switch.tsx:20` Moon `className='absolute …'`；`ui/button.tsx` cva 基类 `grep relative` → 0 命中 | 仍靠「absolute 无 top/left 时保持静态位置」侥幸不飞 |
| **P2-15** | 框架嵌入头 + IPv6 白名单 | **仍存（两件）** | `grep -rn "X-Frame-Options\|frame-ancestors" plugins/bot_unified_runtime/control_plane/` → **0 命中**；`webui/src/lib/api-client.ts:42` `LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost'])` | meta CSP 的 frame-ancestors 不生效，须服务端头；`http://[::1]:8742` 仍被 `validateBaseUrl` 拒 |
| **P2-16** | `.tmp-test/` 双漏 | **仍存且爆炸性扩大** | `.gitignore`：只有 `tmp/`(:46)、`.pytest_tmp*/`(:74)，**无 `.tmp-test/`**；`pyproject.toml:82` `extend-exclude = ["_crawlwiki_patch2"]` **无 .tmp-test** | `.tmp-test/` 条目 **22→35**、体积 **489MB**，内含他席全量跑日志 `full-suite.log`(158KB/14:29)、`failing-subset.log`(15:38)、`b2-nb.log`(**15:52**)、`mutation_test{,2}.py`、`D9/full/`（两次 ruff 之间新出现）；`grep -rn "tmp-test" tests/ scripts/ plugins/ conftest.py` → **0 命中**＝写入方是会话临时 `--basetemp`，非仓库代码 |
| **P2-17** | 渲染豁免散点无总册 | **仍存（散点仍散）** | `docs/rendering-contract.md` 章节：一铁律/二本命色/三注册表/四 Shell 常量/五 checklist/六 payload 接线——**无「豁免登记表」章** | 豁免只以行内括注存在（`:19`、`:72` error 卡 `wash_blob_mix=24`；`:66` universal amber）；mermaid 伪元素特例、memory-canvas 白名单 #1、song `.ttl`/affinity `.pill` 描边两档均未集中 |
| **P2-18** | `tts.py` mypy no-redef | **已修（窗口外 15:49:52，并行 TTS 席）** | `domains/media/capabilities/tts.py:328` `error_body: Any = response.json()`、`:330` `error_body = None`、`:331-334` 同步 | 与 09-19 建议逐字一致；**本席 mypy 实跑已无 tts 错**＝唯一余错只剩 `capability_protocols:1273` |
| **P2-19** | `__init__.py` mypy index 错 | **已修（结论：关账）** | 原 `__init__.py:5712` `Collection[str] is not indexable` | **本席 typecheck 实跑：`Found 1 error in 1 file`，唯一错非 `__init__.py`** ⇒ 该条已在盘消失（`__init__.py` mtime 15:49:03）。以实跑为准，不采信旧行号 |
| **P3-20** | 死 eslint-disable | **仍存** | `logs.tsx:121`、`:144` `// eslint-disable-next-line react-hooks/exhaustive-deps`；`grep -rn eslint webui/package.json` → 无 eslint/prettier 依赖 | 两条注释指向不存在的 linter |
| **P3-21** | 前端单测运行入口 | **部分修** | `webui/package.json` scripts：`"build": "node scripts/layout-constitution.mjs && vite build"`、`"lint:layout"`、`"typecheck": "tsc -b"`；**无 `"test"`、无 `"check"`** | 宪法门已前置进 build（真实改进）；`graph-layout.test.ts` 仍无 npm 入口，「一条命令过三门」未成立 |
| **P3-22** | 树单写者机制 | **仍存（本席再实证，见 §D）** | 流程项 | §A 前置块 11 个 mtime 改写事件；`.tmp-test/b2-nb.log` 15:52＝并发测试进程活体；14:29 已有他席全量跑 |

**小结**：已修 **3**（P0-1@16:04、P2-18@15:49、P2-19 经 mypy 实证消失）｜部分修 **2**（P0-2、P2-10）｜仍存 **14**｜无法判定 **0**（前端三门的 *exit 码* 无法判定记在 §A.1，不影响台账判定——P1-1/P1-3/P1-4/P1-5'/P2-9~15 全部用文件实读 + 产物字节取证定案）。
**三条 P0 的实况**：P0-1 修于本席窗口内；P0-2 半修且仍是 mypy 唯一红错；P0-3 恶化 37 条。

---

## §C 文档宣称对账（AGENTS #41/#42 + V21R5 §〇/§三/§五/§六 vs 实跑）

> 只列**不成立或证据不足**者；成立者单列 §C.2（防接手者重复怀疑）。定级：P0=据此决策会出错；P1=口径需改；P2=措辞不严。

### §C.1 不成立 / 证据不足清单（12 条）

| # | 原文摘录（出处） | 实跑反证 | 定级 |
|---|---|---|---|
| C-1 | 「**全量 8532P/0F 四门禁全绿实跑**」（AGENTS #41 状态列） | 本席四件：**2 failed**/8567P；lint **63 errors**；typecheck **1 error**；runtime-layout **FAIL**（2 项）。四门禁无一件全绿 | **P0** |
| C-2 | 「8561 passed / 4 failed …4 失败全部归属 TTS/前端在飞面，**后端波零回归**」（V21R5 §〇、§六终局行） | `feature_gate` 失败根因＝本波**未提交新码**：`__init__.py` diff 新增 7 处 `capability_id`、4 处在 `capability_registry.py`（该文件工作树未改）零登记；单跑确定性复现。`webui` 那条＝09-19 立案的日历炸弹（常驻 `tests/`，非前端在飞）。⇒「零回归」不成立，且**两条归属两条都错** | **P0** |
| C-3 | 「verify_hashes **1 DRIFT**（echo.py=TTS 在飞）」（V21R5 §〇、§五） | 实跑 `EXIT=0` **0 DRIFT**；`tests/render_hashes.json` mtime **15:39:17**＝有席在窗口内 `--write` 重录（后端波纪律明禁「`tests/verify_hashes.py` 一律 --check 禁 --write」）。宣称与实况同时失效，且**绿是被移动过的基线**（正是 dev.ps1:241-246 警告的洗绿面） | **P0** |
| C-4 | 「ruff **23 处可修**（在飞席文件为主）」（V21R5 §〇/§六） | 实跑 `Found 63 errors`、`36 fixable`（pre_restart_check 内口径 37）。**45/63=71% 来自 `.tmp-test/` 残留 + `%TEMP%` 目录内他席探针**，非「在飞代码」；真文件仅 18 条、全为 I001 | **P1** |
| C-5 | 「终态：**RET2b 剩余 4 张中 3 张已退役**（contracts.runtime / decision.outbound / **sources.web_search**，69+4 文件消费方归 canonical，**AST 零残余**）」（`v21r4-b-RET2b-R-log.md:34`） | `sources.web_search` 消费方**未归 canonical**：`capability_protocols.py:1273` 包级 `from …sources import (web_search,)` 仍在（mypy + importlib 双证 ModuleNotFoundError）。⇒ 该张的「AST 零残余」不成立 | **P0** |
| C-6 | 「AST 验证旧路径 import 残余 **0**」/「非豁免残余 = 0」（`RET3-log:76`、`RWC6-b-log:65`） | **方法级不成立**：本席用「模块集合成员判定」式 AST 扫描复跑，对 `capability_protocols:1273` 得 **0 命中（假零）**——包级 `from 包 import 子模块名` 的 `module` 字段是**父包**，任何按「旧模块全名」过滤的扫描器必然漏（与 HANDOFF §四.9 自承的「包级 from-import 盲区」同因）。真正有效的检测器是 **mypy + importlib 探针**（本席两者都报红）。⇒ 以该类扫描器得出的「零残余」结论须重做 | **P1** |
| C-7 | 「qx.json 第三次消失→%TEMP% 备份恢复+**随包入库根治**」（#27）／「是随包内置资产（**.gitignore 已加否定规则**）……（铁律 6 已同步新径）」（AGENTS 铁律 6 + 顶部口径修正） | `git ls-files --error-unmatch …/domains/weather/assets/qx.json` → **“Did you forget to 'git add'?”**（从未入库）；`git status` = `??`；`git check-ignore` → exit 1；`.gitignore:33` 唯一否定规则仍指**已废弃旧路径** `!plugins/bot_unified_runtime/sources/data/qx.json`。⇒ 「入库」不成立、「否定规则已同步新径」不成立；`git clean -fdx` 仍可第四次毁它 | **P0** |
| C-8 | 「`pre_restart_check`：PASS **5** / SKIP 1 / **FAIL 3**」 | 实跑 **PASS 6 / SKIP 1 / FAIL 2**（`hash_ledger` 已转 PASS）⇒ 宣称的 FAIL 构成（含 hash）与实况不符；根因同 C-3 | **P1** |
| C-9 | 「4 失败全为常驻门/在飞面归属」「终验四件残余…同归属，只记录一律不修」（#42 ⑪） | 同 C-2：`feature_gate` 是本波自伤；`webui_http` 是 09-19 立案未落地项。「只记录一律不修」把**自家台账 P0 条**也一并登记掉了 | **P1** |
| C-10 | 「整树 collect **8531/0err**」（#42 ⑩ RET2B-PREP） | 本席 `collected 8584 items`，且 scoped/全量均 0 collection error ⇒ collect 面无错为真，但**8584≠8531**；用例基数在波次间漂移 53 项，任何「passed 数」横向比较都需同时报 collect 数，否则「历史最高通过数」（§〇 措辞）不可校验 | **P2** |
| C-11 | 「`.tmp-test/` 源码树残留（154MB）→备份 %TEMP% 后删除中途发现被并发测试进程锁定→立即停手」「.tmp-test 清理｜阻塞于｜占用进程释放｜备份已在 %TEMP%」（V21R5 §L/§五） | 实况：**489MB / 35 条目**且在审计窗口内持续增长（22→35），ruff 因此多吃 43 条错误。备份存在≠清理发生；「待占用释放」无释放条件与截止，属**开放风险**而非阻塞项 | **P1** |
| C-12 | 「重启判定：**能起**」（§〇，指向 `v21r4-b-restart-gate-snapshot.md`）+「插件导入冒烟 ok（3.39s）」 | 本席**未跑** `-Task nonebot-smoke/startup-smoke`（不在本席授权命令清单内）⇒ 该两断言在本轮**证据不足**（未复跑）。可复核的相关实况：`pre_restart_check` 真 `EXIT=1`、四门禁 3 红，「能起」仅指 import/装配面，**不等于门禁可合入或生产可部署** | **P2** |

### §C.2 核验成立的宣称（正面记录，接手者勿重复怀疑）

1. `doc_sync --check` **EXIT=0**＝「doc_sync PASS」为真；`command_catalog --check` 原文 `current (77 topics)`＝**77 topics 为真**（AGENTS 顶部「topics 实值 77（非 79）」口径修正已落地）。
2. runtime-layout 的 2 项失败**与 09-19 审计完全同因同条**（BOT_KNOWLEDGE_FILES 指向盘外文档），非代码回归。
3. **B1 矩阵宣称可复算为真**：`docs/design/backend-v2-acceptance-matrix.md` 实测 `^| V21-` 行 **65**；`production_wiring` 分布 **31 unknown / 17 partial / 17 not_wired**（「not_wired=17 口径」为真，17vs18 争议以现值 17 为准）；`live_validation` 列 **零 passed**（4 blocked / 1 not_applicable / 60 unknown）⇒「live_validation 全表零 passed」为真，§〇「65 行 live_validation 全 0」为真。
4. 「dev.ps1 旧路径 30 处修复」在**模块可导入性**面为真：dev.ps1 引用的 9 个 `plugins.bot_unified_runtime.*` 模块路径 importlib 全 **OK**（含 §五 仍挂账的 `security.memory_sanitize`——垫片 656B 在盘，旧路径可导入，属"仍用旧路径"而非"断链"）。
5. 「4 张垫片挂起」为真：`contracts/media.py` 615B、`config_readiness.py` 631B、`decision/trace.py` 613B、`capabilities/debug.py` 605B **全部在盘**。
6. kb_drift 宣称与实况一致：`ANN=35341 vs chunks=4611（已嵌入 4539）`，与 §〇/B5 记录同数值。
7. WebUI 单文件壳在位（`dist/index.html` 973154B/03:55），`pre_restart_check` 的 `webui` 项 PASS（950KB 内联无外链）——与 #41「MOCKUI 离线夹具」不冲突。

---

## §D 树卫生与并发写实况（只报告，不清理；清理须用户裁定）

| 项 | 实测 | 备注 |
|---|---|---|
| `git status --porcelain=v1 \| wc -l` | **867 @T0(15:53) → 874 @16:12 → 876 @16:2x 收口**；426 M / 329 ?? / 112 D（@T0） | 9 条净增全部发生在本席窗口内（并行写 + 本席唯一日志文件）；HEAD 仍 `56d1461`（09-15） |
| 未跟踪要害件 | `?? plugins/bot_unified_runtime/domains/weather/assets/qx.json`（362774B/09-13 12:18，**未入库**）、`?? webui/`（**42 个未跟踪文件**，不计 node_modules）、`?? docs/design/audit-20260920-unify-U10-gate.md`（本席日志） | qx.json：`git clean -fdx` 即毁；`.gitignore` 否定规则仍指旧路径（§C-7） |
| 源码树缓存 | **本席收口时：`__pycache__` 0 / `*.pyc` 0**；`.pytest_cache`(12:37)、`.ruff_cache`(12:30)、`.mypy_cache`(12:47) 三目录**在树根**且 mtime 全部早于本席窗口＝他席直跑产物（铁律 6 违反，本席未清） | `.tmp-test/` **35 条目 / 489MB**（22→35 增长发生在 15:52→16:12，他席在写）；`data/` 0（干净）；根目录另有字面 `%TEMP%/`（16:00 mtime）内含他席 `u3_probe_registry.py`(15:57)——ruff 因此报 2 条 |
| mtime 铁证（谁在写） | 11 文件在 §A 前置块列出的改写时点；`domains/render/templates.py` 16:03、`tests/test_webui_http.py` 16:04:33、`.tmp-test/D9/full/`（两次 ruff 之间）、`.tmp-test/b2-nb.log` 15:52 | 另有 4 份**同级审计席日志**在本席窗口内落盘：`audit-…-U1-invest.md` 15:59、`U11b-sec.md` 16:09、`U4-dispatch.md` 16:09、`U2-proto.md` 16:10 ⇒ 至少 4-5 席并行在飞，**「唯一被授权跑全量 pytest 的席」这一前提不成立**（14:29 已有他席全量跑 `full-suite.log`，16:0x 仍在动 render 域与测试文件） |
| 本席自造成的事故（**如实披露**） | 本席一条 `while` 循环探针（校验 dev.ps1 引用的模块路径）**漏带 `PYTHONDONTWRITEBYTECODE=1`** → 源码树生成 **93 个 `__pycache__` / 366 个 `.pyc`**（mtime 全部 16:05–16:06，可归因于本席） | 处置按台账 #1 规程：**先 tar 备份 `%TEMP%/u10-audit/pycache-backup-20260919-U10.tar`（5,488,640B，`tar -tf` 复验 459 条目可读）** → PowerShell `Remove-Item` 清零（Git Bash 无 `rm`，首次 `xargs rm` 失败即换法，未误删）→ 复核 `__pycache__`=0/`.pyc`=0 → **`qx.json` 完好（362774B）未被触碰**。**教训与铁律 6/09-19 §6.3 同一条**：绕开 dev.ps1 直跑 python 必带参数，且**多行 heredoc/循环内每次调用都要带**，不能只在循环外 export 一次就以为覆盖（本席循环内以 `$(…)` 调用，env 实为已导出，真正成因是该条命令前置了 `cd` 而**整行未 export**——复盘：探针段确实缺 export，属本席疏漏） |
| 本席是否留下其它产物 | 仅 `docs/design/audit-20260920-unify-U10-gate.md`（任务指定唯一可写件）。日志/备份全部在 `%TEMP%/u10-audit/`（`A-test.log`、`A-typecheck.log`、`A-ruff-concise.txt`、`A-prere.txt`、tar 备份）。`ruff --no-cache` 未写缓存；`dev.ps1` 四任务的缓存/TEMP 由脚本自身重定向至 `ChatBot_Runtime/` | 全量 pytest 使用 dev.ps1（自带 `--basetemp` 至 Runtime），**未在源码树留 basetemp**；scoped 复跑用 `$TEMP/u10-scoped1`（`--basetemp` 未指树内） |

---

## §E 收口前必须重跑的最小验证集

> 全部为**只读**命令；任何一条红即不得宣称「收口」。带 ★ 的是本席发现「宣称与实况背离」的哨兵项，最容易被再次跳过。

```powershell
# 0) 前置纪律（否则下面所有绿都可能是 conftest 自动 --write 洗出来的）
#    BOT_AUTOSYNC=0 必须显式设置；且禁止任何席跑 --write
powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "\$env:BOT_AUTOSYNC='0'; & '.\scripts\dev.ps1' -Task runtime-layout"
```
```bash
export PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0
P=../ChatBot_Runtime/venv/Scripts/python.exe
# ★1 生成物三门（必须 --check；跑前先确认 render_hashes.json / auto-facts.md mtime 未被并行动过）
$P tests/verify_hashes.py --check && $P scripts/doc_sync.py --check && $P scripts/command_catalog.py --check
ls -la --time-style=+%F_%T tests/render_hashes.json docs/auto-facts.md   # mtime 新于自己上一次跑＝基线被移动，绿不可信
# ★2 后端波自伤哨兵（本席 P1 新缺陷的复跑；改动 capability_registry / 根 __init__ 后必跑）
$P -m pytest tests/test_runtime_feature_gate.py -p no:cacheprovider --basetemp="$TEMP/u10-fg" -q
# ★3 垫片地雷（mypy + 动态探针双轨；AST 集合式扫描对本类无效，见 §C-6）
$P -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy-u10 --explicit-package-bases --ignore-missing-imports plugins
$P -c "import importlib;[print(m, importlib.util.find_spec(m) is not None) for m in ['plugins.bot_unified_runtime.sources.web_search','plugins.bot_unified_runtime.decision.outbound']]"
# ★4 常驻测试卫生（日历炸弹类回归的通用形态：全量前后各跑一次，且改日期后必红即判未修）
$P -m pytest tests/test_webui_http.py -p no:cacheprovider --basetemp="$TEMP/u10-webui" -q
# ★5 树卫生（收口定义：无树内缓存 + .tmp-test 归零 + qx.json 入库为可溯状态）
find . -type d -name __pycache__ -not -path './webui/node_modules/*' -not -path './.tmp-test/*' | wc -l   # 期望 0
du -sh .tmp-test 2>/dev/null; git check-ignore -v .tmp-test                                                # 期望命中（P2-16 修后）
git ls-files --error-unmatch plugins/bot_unified_runtime/domains/weather/assets/qx.json                    # 期望成功（当前：失败＝未入库）
git status --porcelain=v1 | wc -l                                                                          # 期望单调下降（当前 874）
# 6) 前端三门（node v26.7.0 就绪；本席因权限拦截未取证，收口时必须补）
#    cd webui && node scripts/layout-constitution.mjs && node_modules/.bin/tsc.cmd -b && node --test src/lib/graph-layout.test.ts
# 7) 重启预检（真退出码；当前 EXIT=1，FAIL=kb_drift+ruff）
$P scripts/pre_restart_check.py; echo "exit=$?"
```

**收口最低门槛（本席建议）**：①F1 的 4 个 capability id 登记 → `dev.ps1 -Task test` 0 failed；②`capability_protocols.py:1273` 归 canonical（或补垫片）→ `typecheck` 0 error；③`.tmp-test/` 进 `.gitignore` + `pyproject extend-exclude`（并用户裁定后清树）→ ruff 从 63 降到真欠账 18（再 `--fix` 归零）；④`qx.json` 显式 `git add`（用户裁定）；⑤哈希基线在**零并写**窗口内一次性 `--write` + 之后 `--check` 复验，并把该窗口时间写进台账（当前 0 DRIFT 的成因不可追溯）。

---

## §F 本席新增发现（09-19 台账之外，七要素全）

**N-1 4 条统一出站能力未登记（本波新码）**
P1｜坐标：`plugins/bot_unified_runtime/__init__.py:3032/5375/5437/5452/5722`（`capability_id=` 字面量）、登记真身 `domains/chat_reply/runtime/capability_registry.py:97 ROUTE_CAPABILITY_DECLARATIONS / :533 CONTROLLED_INTERNAL_CAPABILITIES`｜锚点：`入站声明了未登记能力`｜根因：S0 收编在根 `__init__` 增新出站入口，未同步补 registry（registry 工作树零改动＝改动漏面，非并行覆盖）｜证据：`git diff -U0` 7 条新增 `capability_id`；`grep -cE "bot\.(cookie_login|cookie_expiry_notice|file|group_welcome)\"" capability_registry.py` = **0**；单跑 `1 failed, 15 passed`｜改法：四 id 进 `CONTROLLED_INTERNAL_CAPABILITIES`（或建带 `has_rule` 声明）｜验证：§E★2。附带面：特性树看不见 ⇒ 这 4 条不可停/不可灰，与「业务插件强隔离 + 细分开关」承诺冲突。

**N-2「AST 零残余」类结论的检测器本身有系统性假零**
P1（方法论）｜坐标：`v21r4-b-RET3-log.md:76`、`v21r4-b-RWC6-b-log.md:65`、`RET2b-R-log.md:22/34`；实例 `capability_protocols.py:1273`｜锚点：`from plugins.bot_unified_runtime.sources import (` + 下一行 `web_search,`｜根因：包级 from-import 的 AST `ImportFrom.module` 是**父包**，任何以「旧模块全名集合」做成员判定的扫描（含 09-19 审计建议的那条 grep）都会得假 0；`sources/__init__.py` 亦无 `__getattr__` 转发可遮｜证据：本席 AST 扫描 1079 文件 → 对该行 **0 命中（假零复现）**；mypy 与 importlib **双报红**｜改法：残余扫描必须叠 `mypy plugins` + 逐模块 `importlib.util.find_spec` 探针；把「AST+rg 双轨」升级为「AST+rg+**mypy/importlib** 三轨」写进退役 SOP｜验证：对已知地雷（`sources.web_search`）跑三轨，AST/rg 单轨必须报 0、mypy 必须报 1——不满足即扫描器失效。

**N-3 `%TEMP%` 字面目录落在源码树，且成 ruff 错误源**
P2（卫生）｜坐标：`C:/Users/…/ChatBot/ChatBot/%TEMP%/u3_probe_registry.py`（3515B/15:57）｜锚点：`%TEMP%\u3_probe_registry.py:22:8: PIE810`｜根因：会话在 Git Bash 里用 Windows 风格 `%TEMP%`（不被展开）当路径，目录被就地创建；本席 cwd 默认落在其中（接手即见）｜证据：`ruff … --output-format=concise` 2 条命中该目录；`git status` 未列（目录内文件被 `??` 收在整目录？现仅目录存在、未单列）｜改法：用户裁定后按台账 #1 备份→清树；工具纪律：bash 内一律 `$TEMP`/`mktemp -d`，禁 `%TEMP%`｜验证：`ls './%TEMP%'` 为空或不存在 + ruff 命中归零。

*本席不修任何被审对象。所有判定以上表实跑原文为准；文档与本日志冲突时，以实跑为准并回写本日志。*
