# 统一收尾大波次全面审计报告（2026-09-19）— NoneBot 插件 + WebUI 前端

> **性质**：独立第三方审计（非交付席自报）。对象=2026-09-18/19 统一收尾大波次（渲染统一收口 + AxonHub WebUI 路线 B 一二期）在当前工作树的真实状态。
> **总裁决**：波次交付的**内容面基本属实**（渲染收口核心承诺、WebUI 契约层、mock 隔离、qx.json 链路均经实证通过），但**「四门禁全绿」宣称对当前树不成立**——全量 test 3 failed、ruff 43 错且在实时恶化、mypy 4 错、1 条测试为日历炸弹。另发现 5 处前端实锤缺陷与一批执法面缺口。
> **接手入口**：本文件 §2 故障台账（20 条，精确到行，每条含改法与验证）+ §4 执行计划。配套接手提示词由用户在对话中交接。
> **快照口径**：行号=2026-09-19 13:03–14:22 复核快照。**树正被并行会话改写**（mtime 铁证：capability_protocols.py 12:55 → tests/test_outbound_v21.py 12:57 → domains/core/search/ 12:59 → __init__.py 13:09；ruff 错误数 21→31→43 随时间上涨）。**每条台账都给了「锚点字符串」，行号漂移时用锚点重新定位，禁止按行号盲改。**

---

## §0 审计口径与方法

- **审计时间**：2026-09-19 12:47（全量测试启动）至 14:22（末次快照复核）。
- **方法**：①四门禁全部亲跑（非转述）：`dev.ps1 -Task test / lint / typecheck / runtime-layout` + `tests/verify_hashes.py --check` + 前端三手动门（`layout-constitution.mjs` / `tsc -b` / `node --test graph-layout.test.ts`）；②WebUI 前端 35 文件全量逐行审读（pages/components/lib/scripts/css/config）；③控制面 webui 端点层+服务层+安全面（auth/Host 白名单/SSE/mock 边界）审读；④渲染域抽查（keyframes 单源/垫片/WAAPI 钉帧/九门测试结构/哈希门实跑）；⑤dist 构建产物层叠顺序取证（node 读 dist/index.html 字节偏移）。
- **串行纪律**：全程零子代理、单线程串行；唯一长负载=单进程全量 pytest（后台单跑，8:58）。
- **诚实声明**：本审计中审计者本人直跑 `python -c` 曾漏带 `PYTHONDONTWRITEBYTECODE=1` 生成 90 个 `__pycache__`，已按台账#1 规程备份 `%TEMP%/pycache-backup-20260919-review.tar`（5.1MB）后清零，`qx.json` 复核完好。详 §6.3。

---

## §1 门禁实测快照（2026-09-19）

| 门禁 | 波次报告宣称 | 审计实测（12:47–14:22） | 判定 |
|---|---|---|---|
| 全量 test | 8532 passed / **0 failed** | **3 failed** / 8535 passed / 12 skipped / 3 xfailed（538.89s） | ✗ 红 |
| ruff | 全绿 | **43 错**（20 分钟内 21→31→43，仍在恶化） | ✗ 红且恶化中 |
| mypy | 621 文件 0 错 | **4 错 3 文件**（618 文件） | ✗ 红 |
| runtime-layout | 余 2 项既有 | 2 项既有（BOT_KNOWLEDGE_FILES 盘外文档缺失） | ✓ 与宣称一致 |
| verify_hashes --check | 0 DRIFT | exit 0（静默通过） | ✓ |
| WebUI 版式宪法门 | GATE_EXIT=0 | exit 0（`node scripts/layout-constitution.mjs`） | ✓（但执法面有缺口，见 P1-6） |
| WebUI tsc | 0 错 | exit 0（`tsc -b`） | ✓ |
| WebUI 确定性单测 | — | `node --test src/lib/graph-layout.test.ts` 7/7 pass（Node 26.7.0） | ✓（但未入任何常驻门，见 P1-5） |

### 三个测试失败明细（快照时刻）

1. `tests/test_outbound_v21.py::TestImportProbe::test_module_importable_in_subprocess`
   失败时探针命令还是旧路径 `import plugins.bot_unified_runtime.decision.outbound` → `ModuleNotFoundError`。**并行会话于 12:57 将探针改为新路径 `domains.core.decision.outbound`**，复审单跑通过（OK 49）。此失败已救活，但暴露「重组删旧路径时探针/垫片清单未一次对齐」的流程缺陷（P0-2 同族）。
2. `tests/test_v21_s10_protocols.py::TestDescriptorCompleteness::test_every_descriptor_has_required_fields_and_resolvable_refs`
   失败原因 `search.web: implementation_ref 文件不存在 plugins/bot_unified_runtime/sources/web_search.py`。并行会话 12:59 动过 `domains/core/search/` 后复审通过——**但 `sources/web_search.py` 至 14:22 仍不存在**，`capability_protocols.py:1273` 的运行期引用仍是活雷（P0-2）。
3. `tests/test_webui_http.py::test_stats_endpoints_require_bearer_and_use_common_envelope`
   `assert payload["data"]["data"]["total_calls"] == 1` 得 0。**复审（14:2x）仍失败**——日历炸弹，见 P0-1。

### ruff 43 错分布（14:22 快照，|--fix| 27 可机械修）

- `.tmp-test/`（源码树根部 pytest 基座残留目录，12:56 出现，疑似并行会话工具产物）：约 10+ 错（RUF100/I001）；
- 真文件 I001（import 排序）：dispatcher.py:157、domains/chat_reply/{chat,backend_unit,quiet_hours,rate_limit,injection}、link_parse/content_parser、music/music.py:262、sources/__init__.py、tests/ 下 10+ 文件；
- `plugins/bot_unified_runtime/__init__.py`：2 错（并行编辑中间态）。
- 完整清单复跑命令见 §6.1。**`.tmp-test/` 既不在 .gitignore 也不在 ruff exclude**（P2-16）。

---

## §2 故障台账（20 条）

> 每条七要素：**严重度｜坐标｜锚点（行号漂移时 grep 它）｜根因｜精确改法（before→after）｜验证命令｜回归锁**。
> 状态全部为「待执行」——本审计不改任何代码。改法代码以审计实读内容为准。

### §2.1 P0 —— 会炸的

---

#### P0-1 测试日历炸弹：stats/calls 契约测试每天烂一次

- **严重度**：P0（常驻回归必红；且证明波次「0 failed」是时钟恰好没出窗的假绿）。
- **坐标**：`tests/test_webui_http.py:56`（种子时间戳）、`:118`（断言）。[14:22 复核未漂移]
- **锚点**：`'2026-09-18T01:00:00+00:00'`（全库唯一）；断言锚点 `assert payload["data"]["data"]["total_calls"] == 1`。
- **根因**：`_audit_table()` 给 `audit_records` 插入写死时间戳 `2026-09-18T01:00:00+00:00`，测试断言默认 24h 滚动窗口内 `total_calls==1`。窗口按墙钟滚动，09-19 13:00 起（出窗 36h）必然 `0 != 1`。该项目天天讲「确定性」，门禁自己却是日历炸弹。
- **改法**（种子改动态，与墙钟解耦）：
  ```python
  # before（:54-57）
  connection.execute(
      "INSERT INTO audit_records VALUES ('a1','r1','private_777','bot.chat',"
      "'invoke','done','low','ok','','2026-09-18T01:00:00+00:00')"
  )
  # after
  from datetime import datetime, timedelta, timezone  # 文件顶部补 import
  fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
  connection.execute(
      "INSERT INTO audit_records VALUES ('a1','r1','private_777','bot.chat',"
      "'invoke','done','low','ok',''," + repr(fresh_ts) + ")"
  )
  ```
  （或保持 SQL 模板、用参数绑定传入 `fresh_ts`——更干净，二选一；核心是「now-1h」。）
- **验证**：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_webui_http.py -p no:cacheprovider --basetemp="$TEMP/pt-fix1" -q`
- **回归锁**：本条本身即锁；可在 `test_webui_http.py` 头部加注释「种子必须相对 now，禁止写死绝对时间」防复发。

---

#### P0-2 `sources/web_search.py` 垫片承诺未兑现 = 运行期 ImportError 地雷

- **严重度**：P0（mypy 现行报错 + 运行期地雷；同类问题第二次出现）。
- **坐标**：`plugins/bot_unified_runtime/runtime/capability_protocols.py:1273-1275`。[14:22 复核未漂移（文件 mtime 12:55）]
- **锚点**：`from plugins.bot_unified_runtime.sources import (` + 注释 `RET2B-PREP: web_search 垫片挂起（control_plane/api 消费），维持旧路径`。
- **根因**：v21r2 重组把 `sources/web_search.py` 真身迁到 `domains/core/search/web_search.py`，旧路径文件已删（git D 态），但 `capability_protocols.py:1273` 仍按注释承诺「垫片挂起」——**垫片从未落盘**（14:22 实测仍不存在）。后果三连：①mypy `attr-defined`（`Module "…sources" has no attribute "web_search"`）；②`_WebChainAsSearchProvider.search()`（W7 search_service 预留上车点）一旦被调用当场 `ImportError`；③全量套件里 descriptor 完整性门因此红过一次（implementation_ref 文件不存在）。
- **改法（方案 A，推荐——与既有垫片惯例一致）**：新建 `plugins/bot_unified_runtime/sources/web_search.py`：
  ```python
  """Compat shim: moved to domains/core/search/web_search (v21r2 reorg)."""
  from plugins.bot_unified_runtime.domains.core.search.web_search import *  # noqa: F401,F403
  from plugins.bot_unified_runtime.domains.core.search.web_search import (  # noqa: F401
      build_web_search_provider,
      NullWebSearchProvider,
  )
  ```
  （显式名列以真身实际导出面为准，先 `grep -n "^def \|^class \|^__all__" domains/core/search/web_search.py`。）
  **方案 B**：把 `capability_protocols.py:1273-1275` 改为 `from plugins.bot_unified_runtime.domains.core.search import web_search`，并确认 v21 descriptor 登记表 `search.web` 的 implementation_ref 指向新路径（现已被并行会话指新，方案 B 则零改动+删旧注释）。
  **两案收尾相同**：全树确认零旧引用后，`grep -rn "sources import web_search\|sources\.web_search" plugins/ tests/` 应仅剩垫片自身或零命中。
- **验证**：`PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_s10_protocols.py tests/test_outbound_v21.py -p no:cacheprovider --basetemp="$TEMP/pt-fix2" -q`；mypy 单文件：`python -m mypy --cache-dir ../ChatBot_Runtime/cache/mypy-fix2 --explicit-package-bases --ignore-missing-imports plugins/bot_unified_runtime/runtime/capability_protocols.py`。
- **回归锁**：descriptor 完整性门（test_v21_s10_protocols）已是锁；勿拆。

---

#### P0-3 提交漂移失控：837 文件压树，宣称与真实差距每小时扩大

- **严重度**：P0（流程级，且正在实时恶化：ruff 12:52=21 错 → 13:03=31 → 14:22=43）。
- **坐标**：工作树整体（git status 837 行）；清单=`.superpowers/sdd/2026-09-18-unify-wave/commit-checklist.md`（§1 要害件/§2 渲染/§3 WebUI/§4 文档/§5 待裁决/§7 勿 add）。
- **锚点**：commit-checklist §5「跨批耦合·需用户裁决后才 add」；§1 两要害件 `domains/weather/assets/qx.json` + `domains/render/card_render/usage_cards.py`。
- **根因**：波次收口后未提交，多个并行会话继续在共享树上写码，无任何「收口窗口」机制；门禁快照（8532P/0F 全绿）只对收口时刻负责，之后树持续漂红且无人重跑。qx.json 新家仍未跟踪（第四次丢失风险一直开着）。
- **改法**：
  1. **用户先落 §5 裁决**（方案 A 推荐：echo/debug 真身随 v21r2 域整批另行提交，本波渲染 commit 不含；方案 B=渲染 commit 携带两域整包 123 文件）。
  2. 按清单顺序执行：§1 要害件 → §2 渲染（含 §2c 七模板 D 态登记）→ §3 WebUI → §4 文档；逐文件显式 add，禁 `git add -A`/`git add .`；每 commit 后 `git show --stat HEAD` 核对。
  3. **每个 commit 之前重跑一次四门禁快照**（这是把「宣称全绿」重新变真的唯一办法），把当时的输出贴进 commit message 或台账。
  4. 确立「树单写者」约定：收口窗口内只允许一个会话写盘（见 §5 决策点 1）。
- **验证**：`git status --porcelain=v1 | wc -l` 应只余 §5/§6/§7 未裁决项；四门禁全量（§6.1 命令）。
- **回归锁**：无代码锁——靠 §4 执行纪律 + commit-checklist §10 自检清单。

---

### §2.2 P1 —— 会错的（WebUI 前端实锤）

> 前端文件 mtime 全部 ≤02:06（14:22 复核），以下坐标稳定。

---

#### P1-1 全站卡片标题行高塌陷（dist 产物层叠实锤）

- **严重度**：P1（视觉 bug，影响全部 SectionCard/StatCard/TermCard 标题）。
- **坐标**：`webui/src/components/ui/card.tsx:31`（CardTitle 基类）。
- **锚点**：`cn('leading-none font-semibold', className)`。
- **根因**：CardTitle 基类带 `leading-none`（line-height:1），页面传入 `fs-card`（line-height:1.375rem）。两类同特异性共存，**产物 CSS 中 `.fs-card{…line-height:1.375rem}` 生成于 dist/index.html 字节偏移 949677，`.leading-none{line-height:1}` 在 949805——后生成者胜，行高恒为 1**。多行标题（知识库词条卡/插件名+徽章换行）必然粘连。版式宪法门与 9 页验收都没拦住：这是层叠顺序 bug，不是缺类名。
- **改法**：
  ```tsx
  // before（card.tsx:31）
  return <div data-slot='card-title' className={cn('leading-none font-semibold', className)} {...props} />;
  // after（删 leading-none——fs-* 阶梯自带行高，不该有第二来源）
  return <div data-slot='card-title' className={cn('font-semibold', className)} {...props} />;
  ```
- **验证**：`cd webui && npm run build`，然后 `node -e "const h=require('fs').readFileSync('dist/index.html','utf8'); console.log(h.indexOf('.fs-card{') < h.indexOf('.leading-none{'))"` 应打印 `true`（fs-card 在后则赢）；浏览器目验知识库页多行词条标题行距。
- **回归锁**：在 P1-5 的常驻门里加一条 dist 断言（fs-card 必须晚于 leading-none 生成，或直接断言 CardTitle 源码无 leading-none）。

---

#### P1-2 前端三道质量门游离于常驻回归之外

- **严重度**：P1（门存在但没人跑=没有门；下个会话改坏 src 不重建、写裸 hex、删确定性种子，8532 条测试照样全绿）。
- **坐标**：`webui/scripts/layout-constitution.mjs`（版式宪法门）、`tsc -b`、`webui/src/lib/graph-layout.test.ts`（7 例确定性单测，`node --test` 手工跑通）。pytest 套件中**一个都不执行**；唯一常驻前端门=pre_restart_check 的 dist 形态检查（tests/test_pre_restart_check.py:294 起）。
- **锚点**：`grep -rn "layout-constitution\|tsc -b\|node --test" tests/` 应命中 0（现状）。
- **改法**：新建 `tests/test_webui_constitution.py`：
  ```python
  """WebUI 前端三门常驻回归：版式宪法 / tsc / 图布局确定性。无 node 环境 xfail。"""
  from __future__ import annotations
  import shutil, subprocess
  from pathlib import Path
  import pytest

  ROOT = Path(__file__).resolve().parents[1]
  WEBUI = ROOT / "webui"
  NODE = shutil.which("node")

  pytestmark = pytest.mark.skipif(NODE is None, reason="node 不可用（离线纪律豁免）")

  def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
      return subprocess.run(args, cwd=WEBUI, capture_output=True, text=True, timeout=300,
                            env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": __import__("os").environ["PATH"]})

  def test_layout_constitution_gate() -> None:
      proc = _run([NODE, "scripts/layout-constitution.mjs"])
      assert proc.returncode == 0, proc.stdout + proc.stderr

  def test_tsc_typecheck() -> None:
      tsc = WEBUI / "node_modules" / ".bin" / "tsc.cmd" if (WEBUI / "node_modules/.bin/tsc.cmd").exists() else "tsc"
      proc = _run([str(tsc), "-b"])
      assert proc.returncode == 0, proc.stdout + proc.stderr

  def test_graph_layout_determinism() -> None:
      proc = _run([NODE, "--test", "src/lib/graph-layout.test.ts"])
      assert proc.returncode == 0, proc.stdout + proc.stderr
  ```
  （Windows 下 tsc 用 `.bin/tsc.cmd` 或 `node node_modules/typescript/bin/tsc -b` 更稳；`env` 构造按仓库测试惯例调整。）
- **验证**：`PYTHONDONTWRITEBYTECODE=1 …python.exe -m pytest tests/test_webui_constitution.py -p no:cacheprovider --basetemp="$TEMP/pt-fix3" -q` → 3 passed。
- **回归锁**：本条即锁，纳入全量套件自然常驻。

---

#### P1-3 版式宪法机器门执法面四处漏判 + 一处未登记豁免

- **严重度**：P1（宣称「机器门扫描锁死」与实际执法面不符）。
- **坐标**：`webui/scripts/layout-constitution.mjs:28`（HEX 正则）、`:34`（间距正则，只扫 p/px/py/pt/pb/pl/ps/pe/gap 族）、`:37`（调色板类）；**圆角三档完全没有门**；`webui/src/components/graph/memory-canvas.tsx:179` canvas 标签硬编码字体。
- **锚点**：`const OFF_SCALE_SPACING = /\\b(?:p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y)-/`；`context.font = '12px "Segoe UI", "Microsoft YaHei", sans-serif'`。
- **根因**：①`m/mx/my/mt/mb/ml` 不扫 → `mt-7`（28px 脱刻度）畅通；②报告宣称「圆角三档机器门锁死」，实际宪法④只活在 index.css 注释里，gate 无 rounded 断言；③只扫裸 hex，`rgba()/hsl()/color-mix()` 内联色可绕过；④canvas 字体字面量绕过五档阶梯且未登记豁免（同文件 height:480 都标了「内联白名单 #1」，双标）。
- **改法**：
  1. `:34` 正则补 margin 族：`(p|px|py|pt|pb|pl|ps|pe|gap|gap-x|gap-y|m|mx|my|mt|mb|ml|mr|gap…)`（注意负值前缀 `-p-` 是否放行由用户裁定）。
  2. 新增圆角门：`/\\brounded-(?!xl|lg|md|full|none)[\\w\\[-]/` 视为违例（xl/lg/md/full/none 放行——xl/lg/md 已在 index.css 钉为 30/18/14）。
  3. 新增内联色门：tsx 内 `/rgba?\\(/`、`/hsl\\(/` 拦截（canvas getComputedStyle 消费 token 不受影响）。
  4. `memory-canvas.tsx:179` 改读 token：`context.font = \`12px \${readToken('--font-sans')}\``——或最低限度在 gate 中显式登记该字符串豁免并注明理由（与 recharts 12px 的 CSS 钉法同构更佳）。
- **验证**：改后故意写一行 `mt-7` / `rounded-[9px]` / `rgba(0,0,0,.3)` 到临时 tsx → gate 必须红；删除后 gate 绿。
- **回归锁**：gate 本身 + P1-5 常驻化。

---

#### P1-4 日志页重放必产生重复行

- **严重度**：P1（用户可见缺陷：凡点「重新订阅」或改过滤条件，同一批日志在界面上重复显示）。
- **坐标**：`webui/src/pages/logs.tsx:165-173`（resubscribe/applyFilters）、`:77-88`（appendRows 无去重）。
- **锚点**：`const resubscribe = () => {` / `sessionStorage.removeItem(CURSOR_KEY);` / `startStream(null); // 过滤变更语义=新订阅`。
- **根因**：两条路径都清游标后 `startStream(null)`=从保留窗口回放（后端语义），但 `rows` state 未清空也不去重——同一批事件（同 cursor）二次 append，React key（`key={row.cursor}`）重复告警 + 界面重复行。断线重连（带游标续传）不受影响。
- **改法**（appendRows 按 cursor 去重，保留 MAX_ROWS 裁剪语义）：
  ```tsx
  // before（logs.tsx:77-88）
  const appendRows = (incoming: LogEventRow[]) => {
    if (incoming.length === 0) return;
    setRows((current) => {
      const merged = [...current, ...incoming];
      ...
  // after
  const seenRef = useRef<Set<number>>(new Set());
  const appendRows = (incoming: LogEventRow[]) => {
    const fresh = incoming.filter((row) => !seenRef.current.has(row.cursor));
    if (fresh.length === 0) return;
    for (const row of fresh) seenRef.current.add(row.cursor);
    setRows((current) => {
      const merged = [...current, ...fresh];
      const overflow = merged.length - MAX_ROWS;
      if (overflow > 0) {
        for (let i = 0; i < overflow; i++) seenRef.current.delete(merged[i].cursor); // 同步收缩，防 Set 无界增长
        setDroppedCount((count) => count + overflow);
        return merged.slice(overflow);
      }
      return merged;
    });
  };
  ```
  `clearView()` 同步 `seenRef.current.clear()`。
- **验证**：连 mock 服务器（`python scripts/webui_mock_server.py`）→ 打开日志页 → 点「重新订阅」→ 界面无重复行、控制台无 key 告警。
- **回归锁**：无前端组件测试基建；登记进 §6.2 目验清单 + `graph-layout.test.ts` 同级的轻量纯函数测试（若把去重逻辑抽成纯函数可单测）。

---

#### P1-5 → 已并入 P1-2（ErrorBoundary 见下条 P1-5'）

#### P1-5' 零 ErrorBoundary：任何页面渲染抛错 = 白屏

- **严重度**：P1（鲁棒性；违背项目「失败面诚实降级」全站哲学——后端端点层层 fail-open，前端却一炸全炸）。
- **坐标**：`webui/src/main.tsx`（根渲染，无边界）；九页均无局部边界。
- **锚点**：`root.render(`；`<RouterProvider router={router} />`。
- **根因**：DTO 形态漂移（旧控制面/后端演进）或组件内异常 → React 19 无边界=整树卸载白屏。九页验收只覆盖 happy/graceful 两态，渲染期异常路径零覆盖。
- **改法**（router 层 per-route 边界，fallback 复用 SemanticState 的 error 形态）：
  ```tsx
  // webui/src/components/layout/error-boundary.tsx（新建）
  import { Component, type ReactNode } from 'react';
  export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
    state = { error: null as Error | null };
    static getDerivedStateFromError(error: Error) { return { error }; }
    render() {
      if (this.state.error) {
        return (
          <div className='mx-auto flex w-full max-w-6xl flex-col gap-4'>
            <h1 className='fs-page'>{String(this.state.error.message || this.state.error)}</h1>
            <p className='fs-caption text-muted-foreground'>页面渲染异常，请刷新或返回。</p>
          </div>
        );
      }
      return this.props.children;
    }
  }
  // main.tsx / router.tsx：RootLayout 的 <Outlet /> 外包一层 <ErrorBoundary>
  ```
  （颜色文案走 i18n；如需复用 `SemanticState` error 卡，把 `state` 构造成 `{phase:'error',message}` 传入即可。）
- **验证**：临时在某页 throw → 显示边界文案而非白屏；恢复后九页正常。
- **回归锁**：webui_acceptance.py 增加一条「注入异常页」用例（可选）；最低限度登记 §6.2 目验清单。

---

### §2.3 P2/P3 —— 欠账的（按性价比排序）

---

#### P2-9 dev 代理漏 `/admin/api/v1`：npm run dev 下总览页两卡恒失败

- **坐标**：`webui/vite.config.ts:18-23`。**锚点**：`'/api/v1': { target: …`。
- **根因**：proxy 只配 `/api/v1`；dashboard 调的 `/admin/api/v1/health`、`/admin/api/v1/status/bot`（api-client.ts:450-452）落到 vite 404。验收走单文件/mock 路径未暴露。
- **改法**：proxy 增 `'/admin/api/v1': { target: process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8742', changeOrigin: true }`。
- **验证**：`npm run dev` 打开总览页，健康/进程两卡出数据。

#### P2-10 五处表单控件漏出字号阶梯（「全站只有五档」名不副实）

- **坐标**：`settings-dialog.tsx:106`（baseUrl input）与 `:127`（token input）；`knowledge.tsx:205`（搜索框）；`memory-graph.tsx:144`（过滤框）；`logs.tsx:249` 与 `:261`（两个 select）。**锚点**：各 input/select 的 `className='h-9 …'`（无 `fs-`）。
- **根因**：控件未挂 fs-* 类，渲染浏览器默认 16px vs 正文 13px（fs-body）。
- **改法**：input 加 `fs-body`；logs 两个 select 加 `fs-caption`。逐处一行。
- **验证**：目验 + P1-5 门（可加断言：所有 input/select className 必含 fs-）。

#### P2-11 dashboard 把「未知 token 数」画成 0（违背自家不造数原则）

- **坐标**：`webui/src/pages/dashboard.tsx:184`（`tokensData.totals?.calls ?? 0`）、`:187`（`tokens.input.value ?? 0`×2）。**锚点**：`?? 0`。
- **根因**：TokenBlock.value 契约允许 null（unknown quality），tokens 页同字段显示「—」，总览页却 `?? 0` 兜成 0——把「未上报」伪造成「零消耗」。
- **改法**：null 时显示 `'—'`（复用 `formatInt(value)` 即可，它对 null/undefined 本就返回 '—'；即把 `?? 0` 去掉，直接传原值）。`totals?.calls` 同理。
- **验证**：mock 数据造一个 value:null 的族 → 总览卡显示 —；对照 tokens 页口径一致。

#### P2-12 移动端无导航：九页在手机上只能手敲 hash

- **坐标**：`webui/src/components/layout/app-shell.tsx:71-75`（aside `hidden … md:flex`）；顶栏（:106-120）只有主题+设置按钮。
- **锚点**：`hidden h-svh w-60 shrink-0 flex-col border-r bg-sidebar … md:flex`。
- **改法**（最小方案）：md 以下在顶栏下加一条横向滚动 nav 条（`flex overflow-x-auto no-scrollbar md:hidden`，复用现有 nav 数组渲染 NavItem 紧凑版）；不必做抽屉。
- **验证**：视口 390px 下九页可达。

#### P2-13 a11y 三件

- **坐标/改法**：
  1. `settings-dialog.tsx:77-85` 弹窗：补 `role='dialog' aria-modal='true' aria-labelledby`、Esc 关闭（useEffect 监 keydown）、打开时焦点移入首个 input、关闭归还焦点。
  2. `logs.tsx:287`：滚动区 `aria-live='polite'` 会对读屏器轰炸 500 行 → 删 aria-live，改 `role='log'`（其隐含 polite 但配合容器裁剪语义更正确）或干脆无 live。
  3. `plugins.tsx:128`：组标题 `<h2 className='fs-page'>` 与页面 `<h1>` 同字号 → 改 `fs-card`，保标题层级。
- **锚点**：`aria-live='polite'`（logs）；`<h2 className='fs-page'>`（plugins）。
- **验证**：目验 + 读屏抽查（可选）。

#### P2-14 theme-switch 图标绝对定位脆弱写法

- **坐标**：`webui/src/components/theme-switch.tsx:19-20`（Moon `absolute`）；`button.tsx` cva 基类无 `relative`。
- **根因**：Moon 的定位参照物是最近定位祖先（header 是 sticky=定位上下文）而非按钮本身；目前靠「absolute 无 top/left 时保持静态位置」的特性碰巧不飞。
- **改法**：Button 基类补 `relative`（或 ThemeSwitch 的 Button 加 className='relative'）。
- **验证**：亮暗切换目验图标不位移。

#### P2-15 控制面框架嵌入防护 + baseUrl 白名单漏 IPv6

- **坐标**：控制面 FastAPI app 工厂（`control_plane/_app.py`，中间件段）——补响应头 `X-Frame-Options: DENY`（meta CSP 里 frame-ancestors **无效**，必须服务端头发）；`webui/src/lib/api-client.ts:42` `LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost'])` 补 `::1`（同时 validateBaseUrl 的 `parsed.hostname` 对 IPv6 返回不带括号形式，直接可用）。
- **锚点**：`const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost']);`。
- **验证**：uv 单测补两条（响应头存在；`https://[::1]:8742` 判 ok）；手测 iframe 嵌 /ui 被拒。

#### P2-16 `.tmp-test/` 残留双漏（gitignore + ruff exclude）

- **坐标**：源码树根部 `.tmp-test/`（12:56 出现，pytest 基座样式的子目录，静态 grep 无法归因到具体测试）；`.gitignore`（只有 `tmp/`、`.pytest_tmp*/`）；ruff 配置 exclude 同缺。
- **根因/后果**：ruff 对它报 10+ 错且随残留增长；`git status` 噪音。
- **改法**：`.gitignore` 补 `.tmp-test/`；pyproject ruff `extend-exclude` 补 `".tmp-test"`；再 `grep -rn "tmp-test" tests/ scripts/` 空手而归时，留一条待办查明写入方（疑似并行会话工具的 basetemp）。
- **验证**：`ruff check . --no-cache` 中 .tmp-test 命中归零。

#### P2-17 渲染豁免散点无总册

- **坐标**：`docs/rendering-contract.md`（增一章）。散点现状：error 卡 wash_blob_mix=24 豁免、mermaid 伪元素 keyframes 特例、.footer-colored 0.98/0.88 sanctioned 变体、memory-canvas 内联白名单 #1（height:480）、song .ttl/affinity .pill 描边两档（P3-21）。
- **改法**：增设「豁免登记表」章节：每条=豁免物｜所在面｜理由｜验收判据｜登记批次。下次收口免考古。
- **验证**：九门测试中现有豁免注释逐一回链该表。

#### P2-18 tts.py mypy no-redef（并行批新码）

- **坐标**：`plugins/bot_unified_runtime/domains/media/capabilities/tts.py:292`（`payload: dict[str, Any] = {`）、`:328`（`payload: Any = response.json()`）、`:330`（`payload = None`）。**锚点**：`payload: Any = response.json()`。
- **改法**：:328 起的响应体解析改用新变量名 `error_body: Any`（含 :330 的 `error_body = None` 与后续 isinstance 判断同步改名）。零行为变化。
- **验证**：mypy 单文件归零 + `pytest tests/ -k tts -q`（tts 相关测试族）。

#### P2-19 `__init__.py:5712` mypy index 错（并行会话正在改，执行时重定位）

- **坐标**：`plugins/bot_unified_runtime/__init__.py:5712`（`Value of type "Collection[str]" is not indexable`；13:09 仍在编辑）。
- **改法**：执行时以**当时最新** mypy 输出为准（§6.1 命令），按报错行上下文判明集合类型后加显式类型注解或改判别式；**若并行会话已改完则核销**。

#### P3-20 前端无 ESLint/Prettier，死 disable 注释与依赖正确性无人守

- **坐标**：webui/package.json（无 eslint/prettier 依赖）；`logs.tsx:121,144` 两处 `eslint-disable-next-line react-hooks/exhaustive-deps` 指向一个不存在的 linter。
- **改法**：最低成本=删两条死注释（或装 eslint 并只开 react-hooks 规则）；不强制全量 lint 基建。

#### P3-21 补齐现有单测运行入口

- **坐标**：webui/package.json scripts 增 `"test": "node --test src/lib/graph-layout.test.ts"`、`"check": "npm run typecheck && node scripts/layout-constitution.mjs && npm run test"`。
- **验证**：`npm run check` 一条命令过三门。

#### P3-22 流程级：树单写者机制缺失

- 见 §5 决策点 1。这不是代码缺陷，是本次审计最深的一条：任何「全绿」宣称在并发写树下都只维持到下一次写盘。

---

## §3 核验通过清单（正面记录，接手者勿重复怀疑）

1. **渲染收口核心承诺属实**：模板内 `@keyframes` 手抄副本清零（单源=`domains/render/card_render/mica_shell.py:132/139/146` 三族 + mermaid_card.html 登记特例 1 处）；bridge 双键注入（`decor_css`/`blobs_html`，bridge.py:171-189）。
2. **WAAPI 截图钉帧**（`domains/render/render_backends.py:233-278`）：pause+currentTime=0、`.card` 子树限定、fail-open 面干净、排除 `animations="disabled"` 的论证充分（注释内探针实证记录）。
3. **哈希门**：`verify_hashes.py --check` exit 0（19 项含 domains/ 新路径）。
4. **九门×11 面**（tests/test_v21r3_visual_gates.py）：断言实质有效（半径登记表/色斑三枚/字号地板/gap 刻度/宽度表/字体栈/hex 黑名单/玻璃档），非玩具门。
5. **WebUI 后端契约层**：Bearer 双令牌回退、422 固定错误码映射、200 信封内 `source_unavailable` 诚实降级、知识库集合白名单（collection 不可选任意文件）+ q≤200 + 分页钳制、`/ui` 无 Bearer 但壳零数据（api/webui.py 文档化决策）。
6. **安全面**：Host 白名单防 DNS rebinding（多值 Host 拒绝，_app.py:687-710）；Bearer 禁入 URL/query；SSE 游标 410 语义与前端 sse.ts 完全对齐；mock 服务器（scripts/webui_mock_server.py）文档化「绝不接生产」隔离成立。
7. **qx.json 链路**：新家在位（`domains/weather/assets/qx.json` 362774B）、`domains/weather/data/nmc_weather.py:20` 解析路径正确（`Path(__file__).parent.parent/"assets"/"qx.json"`）、全树旧路径引用零残留、%TEMP% 备份在（%TEMP%/qx-guard-20260919）。
8. **双语言 238=238 键零漂移**；graph-layout 确定性 7/7（Node 26.7.0）。
9. **runtime-layout** 仅余 2 项既有 BOT_KNOWLEDGE_FILES 环境缺失——波次报告此条口径诚实。

---

## §4 修复执行计划

### 阶段 0：开工前置（一次性）
1. 确认**树单写者**（§5 决策点 1）——用户裁决后其他会话停写。
2. 通读根 AGENTS.md 硬约束 + 本文件 §2 全部台账。

### 阶段 1：P0 三条（半天内可完成）
- P0-1 → P0-2 → P0-3 前置裁决。
- 每条修完立即跑该条「验证」命令；P0-1/P0-2 完成后全量 test 应回到 0 failed（假设无新漂移）。

### 阶段 2：P1 五条（前端）
- 顺序：P1-1（行高）→ P1-5'（ErrorBoundary）→ P1-4（logs 去重）→ P1-3（gate 补缺）→ P1-2（三门常驻化，最后落，把前面的修复全部罩进门里）。
- 前端改动后必须 `npm run build` 重建 dist 并复跑 webui_acceptance（9 页）确认无回归。

### 阶段 3：P2/P3 按性价比清账（可分批）
- 建议 order：P2-9（一行）→ P2-16（两行）→ P2-18/P2-19（mypy 清零）→ P2-11 → P2-10 → P2-12 → P2-13/14/15 → P2-17 → P3-20/21。

### 阶段 4：收口
1. 四门禁全量复跑（§6.1），目标全绿；输出贴台账。
2. 按 commit-checklist（§1→§2→§3→§4）提交；**每 commit 前重跑四门禁快照**。
3. 更新 AGENTS.md 台账 + HANDBOOK（按项目交接规矩），核销本审计台账。

### 回滚方式
- 前端：webui/ 全部是未跟踪新文件，`git clean` 面即回滚面；dist 可随时 `npm run build` 重造。
- 后端垫片/测试修复：单文件小 diff，`git checkout -- <file>`（未跟踪件直接删）。
- 不触碰 Runtime/、personas/、.env、qx.json——不存在数据回滚面。

---

## §5 决策点清单（需用户裁决，接手 AI 不得代裁）

1. **树单写者**：审查期间实测四个文件被并行会话连续改写（12:55→13:09），ruff 21→43。是否立即冻结其他会话写入、由接手 AI 独占收口？
2. **commit-checklist §5 二选一**：echo/debug 真身随 v21r2 域整批走（方案 A，推荐）vs 渲染 commit 携带两域 123 文件（方案 B）。
3. **P0-2 方案 A/B**：建旧路径垫片 vs 改新路径引用（推荐 A，与仓库垫片惯例一致）。
4. **P1-3 负 margin 是否放行**（`-mt-2` 等）。
5. **P3-16~22 既有顺延项的里程碑**（latency 历史持久化、audit user 列、审计库路径、玻璃 var() 切换等）——维持顺延还是排期。
6. **`test_webui_constitution.py` 对 CI/离线的门**：node 不可用时 skip 是否可接受（本审计建议可接受，理由=离线纪律优先）。

---

## §6 附录

### §6.1 门禁复跑命令原文（全部实测过）

```powershell
# 全量 test（约 9 分钟）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
# lint / typecheck / runtime-layout
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
# 哈希门
$env:PYTHONDONTWRITEBYTECODE="1"; ..\ChatBot_Runtime\venv\Scripts\python.exe tests\verify_hashes.py --check
# 前端三门（在 webui/ 下）
node scripts/layout-constitution.mjs; node_modules\.bin\tsc.cmd -b; node --test src/lib/graph-layout.test.ts
# ruff 明细（concise）
..\ChatBot_Runtime\venv\Scripts\ruff.exe check . --no-cache --output-format=concise
# mypy（dev.ps1 同口径）
..\ChatBot_Runtime\venv\Scripts\python.exe -m mypy --cache-dir ..\ChatBot_Runtime\cache\mypy-review --explicit-package-bases --ignore-missing-imports plugins
```

### §6.2 目验清单（代码门之外的观感项）

- 知识库页多行词条标题行距（P1-1）；总览页 token 数未知显示（P2-11）；390px 视口导航可达（P2-12）；日志页「重新订阅」无重复行（P1-4）；设置弹窗 Esc/焦点（P2-13）。
- mock 服务器目验法：`python scripts/webui_mock_server.py` → 浏览器开 `webui/dist/index.html` → 设置面板 baseUrl 填 `http://127.0.0.1:8743`。

### §6.3 审计者事故披露（诚实底线）

- 直跑 `python -c` 验证导入漏带 `PYTHONDONTWRITEBYTECODE=1` → 源码树生成 90 个 `__pycache__`。处置：tar 备份 `%TEMP%/pycache-backup-20260919-review.tar`（5,160,960B）→ `find -delete` 清零（复核 pycache=0 / pyc=0）→ `qx.json` 完好核验。**教训与铁律 6 一致：绕开 dev.ps1 直跑 python 必带双参数。**
- 全量测试期间树被并行改写导致 1 个失败用例「复活」（test_outbound_v21 探针 12:57 被改）——本审计按「快照+复审」双口径如实记录，未采信复活后的绿。

### §6.4 快照证据摘要

- 全量：`3 failed, 8535 passed, 12 skipped, 3 xfailed in 538.89s (0:08:58)`。
- 三个失败原文：`ModuleNotFoundError: No module named 'plugins.bot_unified_runtime.decision.outbound'`（已救活）；`'search.web: implementation_ref 文件不存在 plugins/bot_unified_runtime/sources/web_search.py'`（ref 已被并行指新，垫片仍缺）；`assert 0 == 1`（time bomb，仍红）。
- mypy：`Found 4 errors in 3 files (checked 618 source files)`——tts.py:328/330、capability_protocols.py:1273、__init__.py:5712。
- dist 层叠：`.fs-card{font-size:.875rem;font-weight:600;line-height:1.375rem}` @949677；`.leading-none{--tw-leading:1;line-height:1}` @949805。
- mtime 铁证：capability_protocols.py 12:55 / test_outbound_v21.py 12:57 / domains/core/search/ 12:59 / __init__.py 13:09；ruff 21(12:52)→31(13:03)→43(14:22)。

---

*审计完。下一步=按对话交接提示词开工，本文件即唯一事实源；两份文档与代码不一致时，以代码实测为准并回写本文件。*
