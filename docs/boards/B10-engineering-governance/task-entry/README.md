# B10.task-entry 任务入口与门禁

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.task-entry 任务入口与门禁

> lint / typecheck / runtime-layout / test 四门禁与退出码语义。

- 归属板块：[B10](../README.md)
- 实现落点：`scripts/dev.ps1`、`scripts/runtime_layout_smoke.py`

### 三级入口

| 三级入口 | 路由席位 | 能力 id | 别名/帮助页 | 优先级 |
|---|---|---|---|---|
<!-- BOARD-AUTO:END -->

## 这个功能解决什么

`scripts/dev.ps1` 是本仓唯一的任务入口。它替「改完代码想知道有没有改坏」的人（和 AI）把一长串环境细节吞掉：Python 解释器在哪、缓存该落哪、临时目录怎么躲开 Windows 的坑、哪些命令算交付前必跑。

交付判定只有四道门，全绿才算「本地可交」：

- `lint` —— `ruff check .`，但 `--cache-dir` 强制指到 `ChatBot_Runtime/cache/ruff`，不让缓存进 AI 工作区。
- `typecheck` —— 经选定的解释器跑 `python -m mypy`（不走 `mypy.exe` 启动器：venv 搬出源码区后它的内嵌路径会失效），参数为 `--explicit-package-bases --ignore-missing-imports`，只检 `plugins` 项目自代码。
- `runtime-layout` —— `scripts/runtime_layout_smoke.py`，纯结构体检（详见 `workspace-hygiene/runtime-paths.md`）。
- `test` —— 全量 pytest，离线 mock，不连 QQ、不调 LLM、不联网。用例数以最近一次实跑输出为准，规模口径看机器册 `docs/auto-facts.md`。

另有 `sync`（链式跑三件生成物的 `--write` 再 `--check`）与 `verify`（docs-check + plugin-check + test + lint + typecheck 的组合门），以及一批 `*-smoke` 诊断任务（readiness / config / startup / queue / transport / credential / embedding / route-demo 等）。

## 处理流程

```mermaid
flowchart LR
  task[-Task 名] -> py[Get-ProjectPython: Runtime venv -> .venv -> PATH]
  py -> env[注入 PYTHONDONTWRITEBYTECODE / PYTHONUTF8 / PYTHONIOENCODING]
  env -> gate{四门禁}
  gate ->|退出码非零| throw[Invoke-External throw]
  gate ->|零| ok[绿]
```

任务清单由 `param` 上的 `ValidateSet` 钉死，写错任务名 PowerShell 直接拒。每条外部命令都走 `Invoke-External`，它对任何非零退出码 `throw`，配合脚本头 `$ErrorActionPreference = "Stop"`——所以「某一步没跑成」不可能被静默跳过，整条命令以非零退出收场。`runtime-layout` 与 `test` 的自身退出码即门禁结论。

## 边界与降级

- **环境缺件**：ruff / mypy / pytest 不在选定环境里时 `throw` 并附「先 install」提示；解释器完全找不到时抛「Install Python 3.10+」。不会退化成「跳过即通过」。
- **tests/ 缺失**：`test` 任务直接 `throw`（历史上测试树曾被移出工作区），`verify` 则 `Write-Warning` 后继续——两者语义不同，别把 `verify` 当全量门。
- **端口占用**：`run` / `run-watch` 先查 8080 监听，占用时只提示不重启，避免起第二个 bot。
- **临时目录**：`test` 把 `TMP`/`TEMP`/`PYTEST_DEBUG_TEMPROOT` 全指到 `ChatBot_Runtime/cache/pytest_ci_<pid>`，收尾删除。原因写实：共享的 `%TEMP%\pytest-of-<user>` 里有个 ACL 被拒的环状 `pytest-current` 软链，会让 pytest 收尾清理崩掉。
- **自动重录门**：`test` 仅当调用方**未显式设置** `BOT_AUTOSYNC` 时才默认置一。显式设 `BOT_AUTOSYNC=0` = 禁止 conftest 自动 `--write`，用于验收模式（生成物基线必须逐字节不变）。此前无条件覆盖外层值的写法会让「测试失败后自动重录基线」把真实回归洗绿。

## 测试与验收

门禁自身的门：`tests/test_cross_validation_gates.py`（生成物 `--check` 双件）、`tests/test_autosync_gate.py` 与 `tests/test_autosync_hook.py`（自动同步语义，含显式关断的负样本）、`tests/test_verify_hashes_coverage.py`（哈希清单覆盖范围）、`tests/test_doc_sync_gates.py`（配置目录与路由矩阵对代码取集合比对）、`tests/test_board_taxonomy_gate.py`（板块树一致性）、`tests/test_runtime_layout` 类断言并入 `runtime-layout` 体检本身。

复跑命令（PowerShell，逐条独立可跑）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task test"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task lint"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task typecheck"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '.\scripts\dev.ps1' -Task runtime-layout"
```

绕开 `dev.ps1` 直跑解释器属例外，必须自带 `PYTHONDONTWRITEBYTECODE=1` 与 `-p no:cacheprovider --basetemp=$TEMP/xxx`。真机验收清单见 `docs/acceptance-manual.md`（本板块相关条目在 §6.6 族）。

**红了怎么办**：先归因，再决定修不修。全量树的失败要逐条对号「是不是我这波改的」，属他波/在飞的只登记、不代修、更不代降基线。这条纪律是并发多席作业时唯一防互相踩门的约束。

## 现行缺陷

- `Show-Help` 文案有陈旧处（如 lint/typecheck 仍写「Fails until ruff is installed」），与实际行为不符；属 P2 文案债，未修。
- `dev.ps1` 不跑生成物 `--check`：四门禁里没有任何一道直接比对 `docs/command-catalog.md`、`docs/auto-facts.md`、`tests/render_hashes.json`，它们靠 pytest 常驻门间接守；裸跑 `runtime-layout`/`lint` 时生成物漂移不会被发现。
- `verify` 在 `tests/` 缺失时只警告不失败（见上），与「交付前必全绿」的口径有落差。
- 全仓 `subprocess.run(..., text=True)` 未钉 `encoding` 的调用点仍有十余处未 sweep-fix（`tests/test_cross_validation_gates.py:_run_script` 是一例）；按铁律 `export PYTHONIOENCODING=utf-8` 时会出现 GBK 解码崩的假红。已登记于 `docs/issue-ledger-p2-p3.md`，未批量清。
- 根 `__init__.py` 同文件多主：该文件承载多个 matcher，插入位置会顶漂其它席的坐标棘轮（`tests/test_doc_link_integrity.py` 的坐标基线族），故改它必须最后改、改完即复跑棘轮门。
