# 生成物与机器事实册 · 交付物哈希与重录时机

<!-- BOARD-AUTO:BEGIN -->
<!-- 本节由 scripts/board_doc_sync.py 生成，请勿手改；正文写在标记外 -->

## B10.generated-artifacts · 交付物哈希与重录时机

- 层级：一级 B10 → 二级 generated-artifacts → 三级 `hash-bookkeeping`
- 实现落点：`scripts/doc_sync.py`、`scripts/command_catalog.py`、`tests/verify_hashes.py`、`docs/auto-facts.md`
<!-- BOARD-AUTO:END -->

## 这个入口做什么

`tests/verify_hashes.py` 给「改了必须被人看见」的交付物记一份 SHA-256 台账（`tests/render_hashes.json`）。跟踪集是视觉与规范交付物一族：卡片 Jinja 模板全家、渲染 token 单一来源 `theme_tokens.py`、`docs/rendering-contract.md`、`DESIGN-SPEC.md`、`docs/design/` 三份视觉规格，外加产出/装配这些卡片的 builder 源文件（`bridge.py` / `renderer.py` / `templates.py` / `usage_cards.py` / `echo.py` / `domains/ops/admin/debug.py`）。清单具体有几项、含哪些路径，一律以 `TRACKED_FILES` 真身与机器册为准，本页不抄。

它治的病很具体：**改了 A 忘了 B**。模板与规范件之间有等值关系（文档写的数值必须等于代码里的数值），单边改动会让人体感「一切正常」而视觉已经裂开。清单在册文件出现任何未记录的内容变更，全量测试直接红，强制走一次「有意识地 `--write`」。

builder 源文件是后加的扩面（审查 K-06 定性）：模板只是壳，改 builder 的 f-string 文案同样改变出卡内容，不进清单就等于给哈希门开了个后门。

## 怎么调用

- 重录基线：`python tests/verify_hashes.py --write`（集中面）。
- 校验：`python tests/verify_hashes.py --check`（无参即 `--check`），退出码一表示有未记录变更。
- 代码入口：`sha256_of(path)`（读字节、`\r\n` 归一为 `\n` 再哈希）、`build_manifest()`（清单名 → 哈希）、`check(quiet=False)`（返回问题行列表，空表即干净）、`write()`。
- 清单真身：模块常量 `TRACKED_FILES`。`scripts/doc_sync.py:_tracked_files()` 直接 import 它派生机器册的「哈希清单范围」行，**不建第二份清单**。
- 常驻消费方：`tests/test_cross_validation_gates.py::test_verify_hashes_manifest_clean`；`tests/test_verify_hashes_coverage.py` 反过来审清单本身（覆盖范围与跟踪状态），防止「把漂的文件悄悄摘出清单」这种自欺。

## 开关与参数

无配置键。外部变量只有一个：`BOT_AUTOSYNC`（置一时 conftest 在 session 开始自动重录 `tests/render_hashes.json`，并在收尾点名被改动的交付物——自动修但留痕；显式零 = 禁，验收模式下基线必须逐字节不变）。

谁能改清单：只有确认「该交付物纳入/退出哈希治理」的人。摘项比加项危险——摘项等于放弃门禁，必须在台账写明理由。

## 失败时看到什么

每类一行，前缀即语义：

- `DRIFT    <名>（字节变更未记录——确认后 --write）`
- `NEW      <名>（未登记的新交付物——确认后 --write）`
- `MISSING  <名>（清单在册但文件不存在）`——文件搬家（垫片退役、域重组）后最容易撞这条
- `STALE    <名>（清单已登记但不在跟踪集——清理后 --write）`

末尾汇总 `verify_hashes: N 项漂移；确认属预期改动后执行 python tests/verify_hashes.py --write 重录。`

**红先归因**是这里的常规动作：多席并发时哈希门常因他波改 `echo.py`（在册件）而红，此时本席不动基线，报备给生成物 owner 在树稳定后统一重录。历史上出现过同一原因连红数轮、以及干净检出误报四项漂移（行尾差异，已由 LF 归一根修）两类假象。

## 测试与验收

`tests/test_cross_validation_gates.py`（本门与机器册门同文件成对）、`tests/test_verify_hashes_coverage.py`（清单覆盖与跟踪状态自审）、`tests/test_rendering_contract.py` 与 `tests/test_mica_builders_contract.py`（契约内容门，与哈希门互补：前者管「值是否合规」，后者管「值有没有被人偷偷改」）。

复跑（只读）：`python tests/verify_hashes.py --check`。真机验收侧无需动作——哈希门是静态门，重启前后结论一致。
