# F18 · WebUI 三门常驻化实施设计（gate residency）— 2026-09-19

> **快照声明（实读值，非转述）**
> - `date` = Sat Sep 19 16:50:53 2026（写稿尾段约 17:10，同日下午）
> - `node -v` = **v26.7.0**；`shutil.which("node")` = `C:\Software\nodejs\node.EXE`（venv Python 内实测可见）
> - 系统 `python --version` = 3.12.10；venv `../ChatBot_Runtime/venv/Scripts/python.exe --version` = **3.12.10**（门禁固定用它）
> - 本文档为**设计稿**：本席零修改工作树（除本文件外未新建/编辑/删除任何文件；未 commit；未跑 `npm install`/`npm run build`/`tsc -b`）。
> - **本文所有「实跑」字样=本席本机亲自执行**，证据见附录；旧审计骨架（`docs/design/audit-20260919-unify-wave.md` P1-2，:149-190 的 skipif 方案）**已被 F4 席裁定推翻**，本稿按「缺 node 即 FAIL 不 skip」重写，不复用其代码。

---

## §0 结论速览

| 项 | 结论 |
|---|---|
| 三门只读可跑命令 | 全部实证可用（§1.1 表），当前树全绿（exit 0×4 条命令） |
| tsc 无副作用调用法 | **有**：`node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json`（+ node 项目一条），实跑前后 tsbuildinfo mtime 与全树文件清单零变化（§3） |
| 三门常驻净新增耗时 | venv Python subprocess 实跑 **3.10s**（复刻验证 **2.61s**，量级 ≈3s） |
| 必须进 .gitignore 的条目 | **无新增**——三门按本稿参数跑，全部产物路径已被现有 .gitignore:14/85/86 覆盖（§3.3） |
| dist 新鲜度锁推荐落点 | **`scripts/pre_restart_check.py` 第 8 项 `check_webui` 内扩展**（不是 pytest 常驻新用例），理由与误伤分析见 §4 |
| 本席待清项 | **零**（未产生任何工作树写入；`node_modules/.tmp/*.tsbuildinfo` 现存两枚 mtime=09-19 16:39:44，系本席开工前他人在飞 `tsc -b` 所留，gitignored，非本席产物，仅如实披露） |

---

## §1 实盘阅读结论（先读后设计，逐条给坐标）

### 1.1 三门本体（本席实跑取证）

| 门 | 命令（cwd=`webui/`） | 实跑 exit | 绿判据 stdout | 耗时（bash / venv-py） |
|---|---|---|---|---|
| 版式宪法 | `node scripts/layout-constitution.mjs` | 0 | `版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）`（脚本 `webui/scripts/layout-constitution.mjs:66`） | 184ms / 82ms |
| TS 编译（app 项目） | `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json` | 0 | stdout 为空、exit 0 | 3008ms / 2210ms |
| TS 编译（node 项目） | 同上 `-p tsconfig.node.json` | 0 | 同上 | 1054ms / 530ms |
| 图布局确定性 | `node --test --test-reporter=tap src/lib/graph-layout.test.ts` | 0 | TAP 摘要 `# pass 7` `# fail 0` `# cancelled 0` | 307ms / 276ms |

宪法门**只读**：脚本仅 `readdirSync/readFileSync/statSync`（:12），违例走 `console.error`+`process.exit(1)`（:61-64），无任何写文件调用；SRC 定位用脚本自身 URL（:16），cwd 无关（仍按人类惯例 cwd=webui 跑）。

### 1.2 关键配置事实

- `webui/tsconfig.json` 是 solution 式（`files: []` + references，:2-3）→ **`tsc -p . --noEmit` 会零文件空转绿（静默假绿陷阱），绝不可用**；`tsc -b` 检查的恰是 app+node 两项目，逐项目 `--noEmit -p` 覆盖等价（同一 compilerOptions、同一 diagnostics；差异仅在 -b 的 up-to-date 跳过与增量缓存，常驻门反而**不要**增量跳过——每次全查才是门语义）。
- `tsc -b` 写入位置已被 tsconfig 钉进 node_modules：`tsconfig.app.json:3` 与 `tsconfig.node.json:3` 的 `tsBuildInfoFile: ./node_modules/.tmp/tsconfig.*.tsbuildinfo`。树中现存两枚（16:39:44，本席前留）即 `-b` 实写过的位置证据。
- 两项目均自带 `"noEmit": true`（app :14 / node :14），`--noEmit -p` 命令行再显式重申一次，双保险。
- `webui/package.json:6-12`：现有 `dev/build/typecheck/lint:layout/preview` 五脚本；`build` 已前置宪法门（:8）；**无 `test`/`check`**（P3-21 属实）。
- `webui/src/lib/graph-layout.test.ts:3` 以 `./graph-layout.ts` 带扩展名导入 → 依赖 Node 原生 TS type stripping；文件头注释标 Node ≥23（:6）；本机 v26.7.0 实跑**无需 `--experimental-strip-types`、零 ExperimentalWarning**（stdout 干净）。
- `.gitignore`：`:14 dist/`、`:85 webui/node_modules/`、`:86 webui/dist/` 三条已在——**三门按本稿参数运行不触碰任何未忽略路径**。
- `git ls-files webui/` = **0 个跟踪文件**（整个 webui 未 commit，与台账 #41/#42「未 commit」口径一致）→ dist 新鲜度只能做**本机 mtime 锁**，不可做仓库级内容锁。

### 1.3 仓库测试惯例（照抄源）

- 门脚本 subprocess 惯例：`tests/test_cross_validation_gates.py:20-28`（绝对路径、`cwd=ROOT`、`capture_output=True`、`timeout=120`、`check=False`、断言 rc==0 且失败消息内嵌 stderr + `--write` 修复指引）。
- env 构造惯例：`tests/test_autosync_hook.py:46` `env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", ...}`——**继承 PATH，定点覆盖**，不白名单清空（白名单会杀掉 node 的 PATH 解析）。
- 解码惯例补充：宪法门绿文案是中文，`text=True` 在 Windows 下按 locale(cp936) 解码子进程字节流有乱码风险 → 本稿**按 bytes 捕获、手工 `utf-8` decode**（`errors="replace"`），TAP 断言用 ASCII（`# pass/# fail` 行，实跑验证见 §1.1），彻底免疫控制台编码。
- `tests/conftest.py:214-251` 的 data/ 守卫只快照仓库 `data/`；三门写入面为零且即便有也不落 `data/`，与该守卫无交互。autosync 钩子（conftest.py:46-50）只碰三个机器文件，与 webui 无交集。
- `scripts/dev.ps1`：`Invoke-Test`（:234-306）把 TMP/TEMP/PYTEST_DEBUG_TEMPROOT 重定向到 `ChatBot_Runtime/cache/pytest_ci_<PID>`（:252-262）后跑 pytest——node 子进程继承该 env 但**不写 TMP**（type stripping 与宪法门均无临时文件），无冲突。

### 1.4 dist 现网与 /ui 挂载（新鲜度锁的背景事实）

- /ui 服务面读的就是 `webui/dist/index.html`：`plugins/bot_unified_runtime/control_plane/_app.py:225`（`webui_dist_dir` 参数）→ :578 `build_ui_router(dist_dir=...)`；默认解析 `control_plane/webui_stats.py:341-346`（仓库根 `webui/dist`）。
- 本席实读取证：`webui/dist/index.html` mtime = **2026-09-19 16:47:19**，而 `webui/src/** + 构建配置` 最新 mtime ≈ 16:46:37 → **当下 dist 比 src 新鲜**（旧审计「落后 12.7 小时」的快照状态已被修复波刷新，但**无常驻锁，漂移必然复发**）。

---

## §2 交付成品：`tests/test_webui_constitution.py` 全文（可直接落盘）

> 以下代码的**每一条命令、每一个断言**已用等价复刻脚本在 venv Python 实跑全绿（`%TEMP%/f18/verify_impl.py`，输出见附录 A2）；文件本体经 `py_compile` 语法验证。**本席未在工作树创建此文件**（实施权在主会话）。

```python
"""WebUI 前端三门常驻回归（F18 设计，2026-09-19）：版式宪法 / tsc 编译 / 图布局确定性。

背景：三门此前只在 `docs/design/audit-20260919-unify-wave.md` P1-2 记为「游离于
pytest 之外」；F4 席裁定常驻化必须**硬依赖 node——缺 node 即 FAIL，不许 skip**
（skip 化等于门消失）。本文件即该裁定的落地稿。

三门本体（人肉等价命令，cwd=webui/）：
  1) node scripts/layout-constitution.mjs
  2) node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json
     node node_modules/typescript/bin/tsc --noEmit -p tsconfig.node.json
  3) node --test --test-reporter=tap src/lib/graph-layout.test.ts

零缓存纪律（AGENTS.md 铁律 6）：
  - 绝不在门里跑 `tsc -b`——它写 node_modules/.tmp/*.tsbuildinfo（tsconfig 的
    tsBuildInfoFile 所指）；`--noEmit -p <project>` 实跑验证零写入（前后全树文件
    清单与 tsbuildinfo mtime 不变）。tsbuildinfo 虽被 .gitignore:85 覆盖，
    常驻门仍取零写入形态，双保险。
  - 绝不跑 `npm install` / `npm run build`（前者破坏离线纪律、后者写 dist 且慢）。
  - 依赖缺位 = FAIL 并给修复指引，不 skip：node 本体、typescript 包、宪法脚本、
    测试文件四者任一缺失都直接红——那是环境本身不合格。

编码纪律：子进程按 bytes 捕获、手工 utf-8 解码（宪法门绿文案含中文，text=True
在 Windows locale 下有乱码风险）；node --test 用 TAP reporter（`# pass/# fail`
行纯 ASCII）。

耗时基线（2026-09-19 本机 venv 实跑）：layout ≈0.1s、tsc app+node ≈2.7s、
node --test ≈0.3s，合计 ≈3.1s（全量套件净新增同量级）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui"
NODE = shutil.which("node")

# 子进程 env：按仓库惯例继承 os.environ 定点覆盖（tests/test_autosync_hook.py:46）。
# NODE_OPTIONS 有意随继承透传——机器级 node 配置属环境事实，门不暗改；
# 若它导致红，属「失败模式清单·node 环境漂移」类（见设计文档 §7）。
GATE_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}

TSC_BIN = "node_modules/typescript/bin/tsc"  # 相对 WEBUI；node 直跑 JS 入口，
# 绕开 Windows .bin/tsc.cmd 垫片（cmd 包装层不可靠且丢 stderr 语义）。


def _require_node() -> str:
    """F4 裁定：缺 node = 红，绝不 skip。"""
    if NODE is None:
        pytest.fail(
            "常驻门硬依赖 node（F4 裁定 2026-09-19：skip 化=门消失）。"
            "请安装 Node ≥23.6（本机基线 v26.7.0，type stripping 原生）"
            "并确保其在 PATH；随后复跑本文件。"
        )
    return NODE


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=str(WEBUI),
        capture_output=True,
        timeout=timeout,
        env=GATE_ENV,
        check=False,
    )


def _run_checked(name: str, args: list[str], timeout: int) -> tuple[str, str]:
    """跑一门子命令：rc!=0 / 超时都抛 AssertionError，消息带完整可诊断输出。"""
    try:
        proc = _run(args, timeout)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", errors="replace")
        pytest.fail(f"{name} 超时（>{timeout}s），命令={args}\n已捕获输出：\n{partial}")
    stdout = proc.stdout.decode("utf-8", errors="replace")
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 0, (
        f"{name} 红：exit={proc.returncode}，命令={args}，cwd={WEBUI}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    return stdout, stderr


# ---------------------------------------------------------------------------
# 门 1：版式宪法（脚本只读；违例逐条打印 文件:行 后 exit 1）
# ---------------------------------------------------------------------------

def test_layout_constitution_gate() -> None:
    node = _require_node()
    script = WEBUI / "scripts/layout-constitution.mjs"
    assert script.is_file(), f"宪法门脚本缺失：{script}（webui 树不完整？请恢复该文件）"
    stdout, _ = _run_checked("版式宪法门", [node, "scripts/layout-constitution.mjs"], 60)
    # rc==0 还不够——再锚定绿文案，防「脚本被改成空转恒真」。措辞契约=脚本 :66 行。
    assert "全部通过" in stdout, (
        f"宪法门 exit 0 但 stdout 无绿文案（脚本被改动？措辞契约见其最后一行）：\n{stdout}"
    )


# ---------------------------------------------------------------------------
# 门 2：TS 编译（solution tsconfig 拆两项目各查一次；--noEmit 零写入）
# ---------------------------------------------------------------------------

def test_tsc_typecheck_all_projects() -> None:
    node = _require_node()
    tsc = WEBUI / TSC_BIN
    assert tsc.is_file(), (
        f"typescript 包缺失：{tsc}——常驻门不代跑安装（离线纪律），"
        "请在 webui/ 人工 npm install（或恢复 node_modules）后复跑。"
    )
    for project in ("tsconfig.app.json", "tsconfig.node.json"):
        assert (WEBUI / project).is_file(), f"{WEBUI / project} 缺失"
        _run_checked(
            f"tsc --noEmit -p {project}",
            [node, str(tsc), "--noEmit", "-p", project],
            180,
        )
    # 注：禁用 `-p .`——root tsconfig files:[]，零文件空转必假绿（设计 §1.2）。


# ---------------------------------------------------------------------------
# 门 3：图布局确定性单测（node:test 原生 type stripping，Node ≥23.6）
# ---------------------------------------------------------------------------

def test_graph_layout_determinism() -> None:
    node = _require_node()
    case = WEBUI / "src/lib/graph-layout.test.ts"
    assert case.is_file(), f"确定性单测文件缺失：{case}"
    stdout, _ = _run_checked(
        "node --test graph-layout",
        [node, "--test", "--test-reporter=tap", "src/lib/graph-layout.test.ts"],
        120,
    )
    assert "# fail 0" in stdout, f"node --test 有失败用例：\n{stdout}"
    assert "# cancelled 0" in stdout, f"node --test 有取消用例：\n{stdout}"
    match = re.search(r"^# pass (\d+)$", stdout, re.MULTILINE)
    assert match is not None, f"TAP 摘要行缺失（reporter 形态变了？Node 版本漂移？）：\n{stdout}"
    passed = int(match.group(1))
    # 下限而非定值：加用例不砸门；删到 7 以下（如误删确定性种子族）才红。
    assert passed >= 7, f"pass 数 {passed} < 7（2026-09-19 基线 7 例，不应回退）"


# ---------------------------------------------------------------------------
# 门 4（一致性锁，纯文件读取零子进程）：package.json 与常驻门双入口不漂移
# 注意：本用例与 F18 设计 §5（package.json 增 test/check 脚本）耦合——
# §5 落地前本条会红（P3-21 现状 scripts 无 test/check），属有意 TDD 红，
# 实施时 §2 与本节、§5 同波次同落。
# ---------------------------------------------------------------------------

def test_package_json_entries_match_gates() -> None:
    pkg = json.loads((WEBUI / "package.json").read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    assert "layout-constitution.mjs" in scripts.get("build", ""), (
        "build 不再前置宪法门——产物将绕过版式约束（原契约 package.json:8）"
    )
    assert "layout-constitution.mjs" in scripts.get("lint:layout", "")
    assert "node --test" in scripts.get("test", "") and "graph-layout.test.ts" in scripts.get(
        "test", ""
    ), "scripts.test 缺失/不指向确定性单测（P3-21 修复件，见设计 §5）"
    check = scripts.get("check", "")
    for needle in ("typecheck", "lint:layout", "test"):
        assert needle in check, f"scripts.check 应链 {needle}（P3-21 修复件）"
```

### 2.1 参数依据逐条

| 参数/写法 | 取值 | 依据（文件:行 / 实跑） |
|---|---|---|
| 调用形态 | `[node, 脚本/入口, ...]` 列表、无 shell | Windows 下 `.bin/tsc.cmd` 是 cmd 垫片（多一层包装、诊断语义弱）；`node <js入口>` 本席实跑 exit 0（附录 A1/A2）。审计旧骨架的 `.cmd` 方案（audit :177）不采纳 |
| cwd | `str(WEBUI)` 绝对路径 | 宪法门 cwd 无关（mjs:16 自定位），但 TSC/`--test` 的参数按 webui 相对写——固定 cwd 与人类用法一致；同 `test_cross_validation_gates.py:26` 惯例 |
| env | `{**os.environ, PYTHONDONTWRITEBYTECODE, PYTHONUTF8}` | 仓库惯例 `test_autosync_hook.py:46`；白名单式清空会杀 PATH → node 直接找不到，故**继承+定点覆盖**。两枚 PY 变量对 node 是 no-op，保留纯为惯例一致 |
| 超时 | layout 60s / tsc 180s×2 / node--test 120s | 实跑上界 0.2s / 3.0s / 0.3s，取 20-60 倍余量抗慢盘冷启动；全量惯例 timeout=120-600（`test_cross_validation_gates.py:25` 用 120、prc `run_cmd` 默认 600），本档在两者之间取语义贴合值 |
| 绿判据 | rc==0 **且** stdout 含绿文案/TAP 摘要行 | 单看 rc 挡不住「脚本被改成恒 exit 0」；措辞契约= mjs:66 / TAP 摘要行=实跑输出。断言强度与 `test_cross_validation_gates.py:33-37` 的 rc+stderr 双要素同格 |
| pass 数 | `>= 7`（下限） | 定值 7 会让「前端加一例」必砸常驻门（错误激励）；下限防的是「删例/漏跑」回退。基线 7 例=实跑 `# pass 7` |
| TAP reporter | `--test-reporter=tap` | spec reporter 摘要行带「ℹ」U+0068 符号，bytes 手工解码虽可行但 TAP 的 `# pass N` 更稳且为 Node test runner 的机器消费面；两形态本席都实跑过（附录 A1） |
| 缺 node | `pytest.fail`（每用例内）而非模块级 raise | 模块级 fail 会把收集期炸成一条 collection error，日志难读；用例内 `_require_node()` = 三条各自干净红，消息含修复指引（F4 裁定的工程化形态） |
| 缺 node_modules | FAIL + 「人工 npm install」指引 | 与缺 node 同理——环境不合格就该红；门自身**绝不**触发 install（离线纪律 + 会写树） |

---

## §3 零缓存与产物污染防线

### 3.1 三门可能的写入面（穷举 + 实证）

| 命令 | 写什么 | 写到哪 | 本稿防线 |
|---|---|---|---|
| `node scripts/layout-constitution.mjs` | 无（只读 import，mjs:12） | — | 无需 |
| `node --test ...`（type stripping） | 无临时文件（v26.7.0 实跑，前后文件清单 diff 为空、`node_modules/.tmp` 无新增） | — | 无需 |
| `tsc --noEmit -p <proj>` | **无**：非 build 模式 + 无 `incremental: true` → 不产 tsbuildinfo；`noEmit` 双保险（项目内建 + 命令行显式） | — | 实跑前后 tsbuildinfo mtime 逐字节不变（16:39:44→16:39:44，附录 A1） |
| `tsc -b`（**不采纳**） | `*.tsbuildinfo` ×2 | `node_modules/.tmp/`（tsconfig.app.json:3 / tsconfig.node.json:3 钉死） | 常驻门不用 -b；即便人在外面跑了 -b，产物也被 .gitignore:85 吸收，不污染跟踪面 |
| `npm run build` / vite（**禁入常驻门**） | `dist/**`、`node_modules/.vite` | webui/dist、node_modules | 只在 pre_restart 检查面读不写；§4 新鲜度锁判 dist **读时不触发构建** |

### 3.2 兜底守卫（既有，无需新增）

- pytest 侧：conftest data/ 守卫（conftest.py:214-251）与 `dev.ps1 -Task runtime-layout`（`scripts/runtime_layout_smoke.py:101` 扫 `__pycache__`，不涉 node 面）都不被本门触发。
- `dev.ps1 -Task test` 的 TMP/TEMP 重定向（dev.ps1:252-262）对 node 子进程透传但无写入需求（§1.3）。

### 3.3 须进 .gitignore 的条目清单（给主会话，**本席未加**）

**空集。** 理由：三门按 §2 参数运行写入为零；被否决形态（`tsc -b`）的产物落 `node_modules/.tmp/`（.gitignore:85 覆盖）；dist 落 `webui/dist/`（:86/`dist/` :14 覆盖）。
**条件触发项**（仅当未来有人改 tsconfig 把 `tsBuildInfoFile` 挪出 node_modules 才需要）：若挪至 `webui/.tmp/` 一类路径 → 届时补一行 `webui/.tmp/`。当前不动。

---

## §4 dist 新鲜度锁（F10 P1：dist 曾落后 src 12.7h 仍全绿）

### 4.1 方案裁决：mtime 比较，**不做**内容哈希

- 内容哈希双向不可行：①对 dist 重算哈希没有对照基线——「src 应有的构建产物哈希」只能靠**现场 `npm run build` 再比**（常驻门禁 build：慢、写树、且 vite+singlefile 产物含模块 id 哈希不承诺字节可复现）；②把一次 build 产物哈希钉进清单=每次前端改动都要有人 --write，等于把渲染哈希清单那套「有意识重录」成本强加给重启流。
- mtime 方案在本仓可用性额外加成：webui 整体未 commit（git ls-files=0）→ 不存在「clone 后 checkout 打乱 mtime」的误报源；单机场景无时钟跨机偏移。
- 已知漏判面（如实披露）：把 src 文件 mtime 改回更早（从旧归档拷贝）会漏判；touch-only 无实改会误报（代价=一条 rebuild 命令，可接受）。

### 4.2 落点推荐：**并入 `scripts/pre_restart_check.py` 第 8 项**，不进 pytest 常驻树

- 现状：`check_webui`（pre_restart_check.py:432-476）已判 缺失=SKIP/空=FAIL/超限=FAIL/外链=FAIL；新鲜度是同项语义的自然延伸（「坏资产」含「过期资产」）。**扩展函数内部判定，不新增第 10 个检查 id**——`run_all` 的 id 清单被 `tests/test_pre_restart_check.py:267-270` 与 :456-459 两处定值断言钉死，加 id 会连坐两既有用例（可改，但无必要）。
- 为什么不进常驻 pytest 树（误伤分析，**推荐裁决**）：
  1. **责任归属错位**：谁改 src 不 build，锁就该砸谁。常驻树里它砸的是**下一次跑全量的人**——后端单线程会话明明什么都没碰前端，会因为某前端席「改了没来得及 build」的在飞中间态被连坐红（09-18 波已有「在飞批红只记录不修」的既有痛点，P1-2 门不该再供弹药）。
  2. **门生效时点贴合**：dist 唯一的生产消费点=控制面 /ui（_app.py:225/578、webui_stats.py:341-346），过期 dist 的实际危害发生在**重启后**；pre_restart_check 正是重启前一键门（其 docstring：全绿才动手），新鲜度在这道的语义=「重启上去的壳必须是最新构建」——判责对象恰是重启执行人（通常主会话），一人统一 build 即绿，成本 O(1)。
  3. 若仍想要「看得见」：pre_restart_check 人读表格会打印该项与滞后小时数，跑全量后顺手 `--json` 一眼即得，不需要常驻红。
- 取舍的诚实另一半：放 pre_restart 意味着**平时全量测试不再提示前端漂移**（漂移最迟在重启时被拦下，拦得很硬=FAIL+exit 1）。若主会话想要常驻可见性折中，可把该项降格为 `pytest.skip` 前的 warning——但那就是 F4 否决过的软化路线，**不推荐**。

### 4.3 成品代码稿（供主会话直接贴，本席未改 `pre_restart_check.py`）

`scripts/pre_restart_check.py` 常量区（:63-64 旁）加：

```python
WEBUI_STALE_TOLERANCE_S = 2.0  # mtime 粒度/文件系统时钟余量，防同秒误报
WEBUI_BUILD_INPUTS_REL: tuple[str, ...] = (
    "webui/src",                                # 目录：递归取最新
    "webui/index.html",
    "webui/vite.config.ts",
    "webui/tsconfig.json",
    "webui/tsconfig.app.json",
    "webui/tsconfig.node.json",
    "webui/package.json",
    "webui/package-lock.json",
    "webui/scripts/layout-constitution.mjs",
)  # = vite build 的全部输入面（宪法门是 build 前置，package.json:8，一并计入）
```

`check_webui`（:476 行最终 PASS 返回**之前**）插入：

```python
    # 8.1 新鲜度锁（F18 设计 §4）：dist 落后任何构建输入 = 过期壳，拦重启。
    latest_input_ns, latest_input = 0, ""
    for rel in WEBUI_BUILD_INPUTS_REL:
        base = project_root / rel
        candidates = base.rglob("*") if base.is_dir() else ([base] if base.is_file() else [])
        for f in candidates:
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            if m > latest_input_ns:
                latest_input_ns, latest_input = m, rel
    dist_mtime = index_path.stat().st_mtime
    if latest_input and latest_input_ns > dist_mtime + WEBUI_STALE_TOLERANCE_S:
        lag_h = (latest_input_ns - dist_mtime) / 3600
        return CheckResult(
            cid, name, FAIL,
            f"dist 落后源码 {lag_h:.1f}h（构建输入 {latest_input} 在 index.html 之后被改）",
            f"重启上去的 /ui 会是旧壳：cd webui && npm run build 重建后再跑预检"
            f"（容差 {WEBUI_STALE_TOLERANCE_S}s 内不算过期）。",
        )
```

`tests/test_pre_restart_check.py` 第 8 节追加 3 例（tmp_path 离线，`os.utime` 钉显式 epoch，零 sleep 零网络；注意该文件用假项目 `make_project`，webui 路径在其 tmp 根下天然可造）：

```python
def test_webui_stale_dist_fail(tmp_path: Path) -> None:
    """8.1 新鲜度锁：src 在 dist 之后被改 → FAIL 带重建指引."""
    root = make_project(tmp_path)
    index = write_webui(root, SINGLE_FILE_HTML)
    src = root / "webui" / "src" / "App.tsx"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("export default function App() { return null }", encoding="utf-8")
    os.utime(index, (1_700_000_000, 1_700_000_000))          # dist：T0
    os.utime(src, (1_700_000_000 + 7200, 1_700_000_000 + 7200))  # src：T0+2h
    result = prc.check_webui(root)
    assert result.status == FAIL
    assert "落后" in result.message and "npm run build" in result.fix_hint
    assert "2.0h" in result.message

def test_webui_fresh_dist_pass(tmp_path: Path) -> None:
    root = make_project(tmp_path)
    index = write_webui(root, SINGLE_FILE_HTML)
    src = root / "webui" / "src" / "App.tsx"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x", encoding="utf-8")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    os.utime(index, (1_700_000_000 + 60, 1_700_000_000 + 60))  # dist 后 60s 构建
    assert prc.check_webui(root).status == PASS

def test_webui_stale_within_tolerance_pass(tmp_path: Path) -> None:
    """容差带：src 仅晚 1s（文件系统抖动/同秒双写）不误伤."""
    root = make_project(tmp_path)
    index = write_webui(root, SINGLE_FILE_HTML)
    src = root / "webui" / "src" / "App.tsx"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x", encoding="utf-8")
    os.utime(index, (1_700_000_000, 1_700_000_000))
    os.utime(src, (1_700_000_000 + 1, 1_700_000_000 + 1))
    assert prc.check_webui(root).status == PASS
```

（文件头需补 `import os`——现文件无该 import，实读 :8-14。）

---

## §5 `webui/package.json` scripts 成品（P3-21）

`"scripts"` 块在现有五键（package.json:6-12）之上加两键（**保持 build/typecheck/lint:layout 原文不动**）：

```json
    "test": "node --test src/lib/graph-layout.test.ts",
    "check": "npm run typecheck && npm run lint:layout && npm run test"
```

- `node --test src/lib/graph-layout.test.ts` 写法依据：本机 v26.7.0 实跑 exit 0、7/7 pass、无 flag 依赖（附录 A1）；npm scripts 走 cmd.exe，路径含 `src/lib` 正斜杠 node 全平台可解析。人用形态不带 `--test-reporter=tap`（spec 形态可读性好）；**常驻机读形态（TAP）只活在 §2 pytest 门里**——两入口命令同源、输出格式各取所需。
- `check` 串三门（typecheck=tsc -b 人用增量形态，产物落 gitignored node_modules/.tmp，与 §2 门形态等价覆盖同两项目）。
- **真相源裁决**：pytest 常驻门（§2）=唯一执法真相源；package.json `test/check` 是人肉便捷面与 `npm run build` 前置的存量契约。防两处漂移的机制件=§2 第 4 用例 `test_package_json_entries_match_gates`（纯文件读断言 scripts 指向同一批命令实体，措辞改动不再自由发挥余地）。
- 可选登记项（给主会话，非必须）：`"engines": { "node": ">=23.6" }` 显式钉 type-stripping 下限；本席不擅自加。

## §6 `dev.ps1` 接线（最小改动，三处，全在既有骨架内）

> 前提裁决：**pytest 常驻化本身不需要 dev.ps1 任何改动**——`-Task test`（dev.ps1:275 `python -m pytest`）自动收集新文件，三门即常驻。以下 `webui` 任务是**独立人肉入口**（改前端时的秒级自检，不用等全量），属可选增值件。

1. ValidateSet（:3-46）`"test",` 行附近插一行 `"webui",`。
2. 新增函数（模板照抄 `Invoke-Lint` :330-344 形状）：

```powershell
function Invoke-Webui {
    # WebUI 三门独立入口（F18 设计 §6）：宪法 / tsc --noEmit（零写入形态）/ 确定性单测。
    $node = Get-Command "node" -ErrorAction SilentlyContinue
    if (-not $node) {
        throw "node was not found. The WebUI gates hard-require Node (>=23.6) on PATH."
    }
    Push-Location (Join-Path $Root "webui")
    try {
        Write-Step "running webui layout constitution gate"
        Invoke-External $node.Source @("scripts/layout-constitution.mjs")
        Write-Step "running tsc --noEmit (app + node projects, zero-write)"
        $tsc = Join-Path (Get-Location) "node_modules/typescript/bin/tsc"
        if (-not (Test-Path -LiteralPath $tsc)) { throw "webui/node_modules missing. Run npm install in webui/ first." }
        Invoke-External $node.Source @($tsc, "--noEmit", "-p", "tsconfig.app.json")
        Invoke-External $node.Source @($tsc, "--noEmit", "-p", "tsconfig.node.json")
        Write-Step "running graph-layout determinism unit tests"
        Invoke-External $node.Source @("--test", "src/lib/graph-layout.test.ts")
    }
    finally { Pop-Location }
}
```

3. switch（:875-918）`"test" { Invoke-Test }` 后加 `"webui" { Invoke-Webui }`；Show-Help（:774-822）`test` 行后加 `'  webui         Run WebUI quality gates (layout constitution / tsc --noEmit / determinism). Requires Node on PATH.'`。

**取舍账**：`-Task test` 是否「顺带」显式加跑三门？——**不加，不需要**：常驻化后 pytest 树里已含三门（净新增 ≈3.1s/全量），`-Task test` 天然覆盖；再在 PowerShell 层重复编排=双真相源，违「谁是真相源」原则。`webui` 任务只服务「前端改完 20 秒自检」的短反馈需求。

**牵动的文档登记（列出不改，主会话实施时一并处理）**：
- `AGENTS.md` 第五部分验证与门禁清单（追加 `-Task webui` 一行 + 「全量 pytest 已含 WebUI 三门」口径一句）；
- `docs/HANDBOOK.md`（维护规矩=增量直接更 HANDBOOK，本件即其素材）；
- `docs/design/audit-20260919-unify-wave.md` P1-2 状态行（skipif 骨架 → 本文档 F4 裁定形态）与 :424 开放问题 6（已有裁决，可关账）；
- `docs/README.md` 文档索引（若该目录未自动收录 unify-audit 系列则补一行）。

## §7 失败模式清单（落地后可能出现的五类红）

| # | 类 | 症状 | 诊断 | 谁修 |
|---|---|---|---|---|
| 1 | **node 缺失/PATH 变** | 三用例全红，消息=「常驻门硬依赖 node…」 | `where node` / `node -v`；确认 dev.ps1/venv 继承的 PATH 是否被会话改 environment 截走 | 环境责任在安装方（本机器=node 装在 `C:\Software\nodejs`，本席实测 `shutil.which` 可见）；测试面**不修**——红是对的，F4 裁定不许洗绿 |
| 2 | **node 版本漂移（降回 <22.6）** | 门 3 红，stderr 含 `Unknown file extension ".ts"`；或门 2 红（vite7/TS5.8 工具链对老 node 的兼容断裂） | `node -v` 对基线 v26.7.0；TAP 摘要行缺失也会触发「Node 版本漂移？」提示（§2 已埋） | 主会话/用户升 node；**不要**给门加 `--experimental-strip-types` 兜底（22.6-23.5 才需要，降级兼容=隐性扩面）；可上 §5 engines 显式化 |
| 3 | **tsbuildinfo 污染** | 理论上不触发（§2 无 -b）；若有人把门改回 `tsc -b` 或把 `tsBuildInfoFile` 挪出 node_modules → git status 见新未忽略文件 / 未来 runtime-layout 扩面红 | `git status --porcelain webui/` 见 `.tsbuildinfo`；比对 tsconfig.app.json:3 | 改门的人回滚到 §2 形态；确需 -b 形态时由主会话补 .gitignore 条目（§3.3 条件触发项） |
| 4 | **宪法门自身误伤** | 门 1 红、逐条「文件:行」指向**合法**写法（先例=PAGES2 空转正则事故，mjs:32-33 注释自述）| 手跑 `node scripts/layout-constitution.mjs` 看清单；对可疑条目人判是否真违例（栅格/五档/语义色三契约见 mjs:1-9 头注） | 前端域席：违例改 src；误伤改 mjs 正则——改 mjs 须同步复核 §2 门 1 的「全部通过」措辞契约，并 consciously 评估是否把 mjs 纳入 verify_hashes 清单（现 19 项不含 webui，F9/F10 相邻议题） |
| 5 | **前端在飞中间态** | 门 2 红（半改完的 src 引用不闭合）或门 3 红（graph-layout.ts 正在改），**全量合跑才现、单跑绿**——与台账 #42「在飞批红」同类 | 复跑归属判定：该前端文件是否在他席 WIP 清单（`.superpowers/sdd/*/progress-*.md`）；对 mtime 看改动时刻 | 按仓库既有规程：**只记录不修**，等该席收口后复跑；禁止为绿改断言或临时 deselect（那正是 F4 否决 skip 的原因） |

## §8 工时与顺序建议

**依赖顺序**（采纳 audit :399 既有裁定「P1-2 最后落，把前面的修复全罩进门里」）：

1. **前置**（他席/主会话在飞项，先落）：P1-1 行高、P1-5' ErrorBoundary、P1-3 gate 补缺——若未落就常驻，落地首日门 1/门 4 可能吞存量违例（当前树实跑三门**已全绿**（§1.1），此项风险实测为零，但仍按此序稳）。
2. **一波同落**（合计编码 ≈25 分钟 + 复跑 ≈10 分钟）：§2 测试文件 + §5 package.json 两键 + §6 dev.ps1 三处（**三者互锁**：§2 第 4 用例锚 §5 产物；单独落 §2 会留一条有意 TDD 红，须预告）。验证=`pytest tests/test_webui_constitution.py` 4 passed + `-Task test` 全量时长 +≈3.1s。
3. **第二波**（稍重，≈45 分钟）：§4 新鲜度锁（prc 扩展 + 3 新用例 + `import os`）。不等任何人——它只读文件，独立可落。
4. **登记波**（≈15 分钟，随主会话收尾批）：§6 末列的四份文档口径 + `verify_hashes` 是否扩纳 `layout-constitution.mjs`（开放题，建议主会话裁「纳入」，它是唯一改 src 不跑测试就可能被洗白的机器门）。
5. **明确不在本设计**（相邻席议题，勿混装）：webui 进 verify_hashes 全量清单（F9/F10）、`npm ci --ignore-scripts` 类供应链门、CI 化。

---

## 附录 A · 本席实跑证据

**A1 只读验证序列**（全部于 2026-09-19，webui/ 下；工作树零写入）：
- `node scripts/layout-constitution.mjs` → exit 0，stdout 见 §1.1，184ms。
- `node --test src/lib/graph-layout.test.ts` → exit 0，spec 摘要 `ℹ pass 7 / ℹ fail 0`，307ms；`--test-reporter=tap` → `# tests 7 / # pass 7 / # fail 0 / # cancelled 0`，exit 0。
- `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json` → exit 0（3008ms）；`-p tsconfig.node.json` → exit 0（1054ms）。
- 零写入证明：跑前后 `find . -path ./node_modules -prune -o -type f -print | sort` 清单 diff=空；`node_modules/.tmp/*.tsbuildinfo` 两枚 mtime 前后同为 `2026-09-19 16:39:44`（且该两枚系本席 16:50 开工**之前**他人在飞所留——如实披露，非本席产物，无待清项）。
- `node -v`=v26.7.0；`which node`=`/c/Software/nodejs/node`。

**A2 venv Python 复刻验证**（`%TEMP%/f18/verify_impl.py`，§2 全部断言等价复刻）：
```
layout OK rc=0 0.07s  stdout=版式宪法机器门：全部通过（hex=0 / 字号五档 / 间距 4px 栅格 / 调色板类=0）
tsconfig.app.json OK rc=0 1.83s  stdout_empty=True
tsconfig.node.json OK rc=0 0.49s  stdout_empty=True
node-test OK rc=0 0.22s pass=7
ALL-ASSERTIONS-VERIFIED
```
四门合计 2.61s；另一次直测 3.10s（layout 82ms + tsc 2210+530ms + test 276ms）→ **净新增耗时量级 ≈3 秒**。

**A3 dist 现值**：`webui/dist/index.html` mtime 2026-09-19 16:47:19 > src 侧最新输入（≈16:46:37）→ 新鲜度锁今日口径=绿。

**A4 纪律自证**：本席未创建/修改工作树任何其它文件；未跑 `tsc -b`/`npm install`/`npm run build`/`npm ci`；未 git 写操作；未派子代理；未 kill 进程；python 直跑均带 `PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1` + venv 解释器；临时件仅 `$TEMP/f18/`（before/after 清单、verify_impl.py）。
