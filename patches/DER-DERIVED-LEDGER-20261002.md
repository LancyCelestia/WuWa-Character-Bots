# 工单 DER — 生成册三尺 + 结构门族复检（2026-10-02 下午窗，只读复检席）

席 DER｜只读复检｜全程零写入（本工单除外）。python＝Runtime venv；一律 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`，pytest 加 `-p no:cacheprovider --basetemp=<仓库外>`；生成器只 `--check`。

## ① 命令与末行汇总表

| # | 命令 | RC | 末行 / 关键行 |
|---|---|---|---|
| 1 | `scripts/shim_retirement_census.py --check` | 0 | `对账问题: ①漏记 0 | ②非垫片登记 0 | ②b已退役被回引 0 | ③真身不存在 0 | ④引用超上限 0 | ⑤手抄真身不符 0`；`硬锁·三态之和(域外全量) 74/基线 74 (OK)`；垫片 23 枚；读点盲区 3 枚（audit/contracts/llm 三 `__init__.py` [no-canonical-derived]）；G-P2 豁免 28（同门上限 29） |
| 2 | `scripts/doc_sync.py --check` | **1（漂）** | `doc_sync: docs/auto-facts.md 与代码推导结果不一致；跑 python scripts/doc_sync.py --write 重生成。` |
| 3 | `scripts/command_catalog.py --check` | 0 | `command catalog is current (83 topics)` |
| 4 | `tests/verify_hashes.py` | 0 | 输出 **0 字节**（stdout+stderr 合计） |
| 5 | pytest 五把 `-q` | 全 0 | shim_retirement_ledger **26 passed** / db_owners_coverage **10 passed** / datafix_runtime_paths **20 passed** / documentation_consistency **31 passed** / doc_link_integrity **23 passed**（零 fail、零 error、零 skip 报出） |
| 6 | `scripts/runtime_layout_smoke.py` | 0 | `generated_residue=absent`；`source_generated_dirs=empty`；runtime_data 重映射正常 |
| 附 | `tests/test_cross_validation_gates.py -q`（追加取证，非清单内） | 1 | `FAILED tests/test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync`（doc_sync 常驻门红，与 #2 RC=1 互证）；同文件另一用例 passed |

## ② 漂移点名（预期零，实测一处）

- **文件**：`docs/auto-facts.md`（mtime 2026-10-02 09:20:21 +0800，2481 字节）
- **尺**：`scripts/doc_sync.py::build_document()`（测试文件数取数口＝`tests/test_*.py` 顶层 glob，doc_sync.py:238）
- **漂移量**：仅一行——`- 测试文件数：980` → 应为 `982`（**净 +2**）。diff 全文仅此一处 hunk（unified diff 共 7 行）；帮助 topic 83、config bot_* 784 等其余行零漂。
- **mtime 旁证**：账后（>09:20:21）新建的未跟踪测试件 8 枚（16:21 `test_migration_status_assignment_gate.py` → 17:09 `test_config_key_registration_ledger.py` 止，其间含 17:01 `test_db_backup.py`、17:07 `test_intimate_group_switch_delivery.py`）；git 只读口径 tracked 测试件删除 0。⇒ 净 +2 意味着 09:20 时点另存在约 6 枚其后被移走的未跟踪测试件（推断，**不判归属**）。
- **预期重生成内容**已存 `%TEMP%\qoder-DER\autofacts-expected.md`（内存 build 落盘到仓库外，供主会话比对；**未执行 `--write`**）。
- **处置建议**：属生成册例行过期（本窗新增测试件所致），非缺陷；由主会话裁是否 `doc_sync.py --write`（写后注意该册会连带刷新其余机器行）。

## ③ 结构门族读数

- `test_shim_retirement_ledger.py` 26 passed（垫片退役账门绿）
- `test_db_owners_coverage.py` 10 passed（DB owner 双向锁绿）
- `test_datafix_runtime_paths.py` 20 passed（data/ 残留根治门绿）
- `test_documentation_consistency.py` 31 passed（叙述文档计数让位机器册门绿——注意：该门只执法「让位措辞」，不校验 auto-facts 本身新鲜度）
- `test_doc_link_integrity.py` 23 passed（载体字面真身门绿）
- 追加：`test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync` **FAILED**（doc_sync 常驻门，即当前唯一红点，与②同源）

## ④ 与在册对照差

| 项 | 在册 | 实测 | 判 |
|---|---|---|---|
| shim census | 74/74 OK、对账五项全 0 | 同 | 一致 |
| doc_sync | （未记漂） | RC=1，测试文件数 980→982 | **漂 +2** |
| command_catalog | current, 83 topics | current, 83 topics | 一致 |
| verify_hashes | RC=0 零字节 | RC=0 零字节 | 一致 |
| 五把 pytest | （复检基线绿） | 26/10/20/31/23 全绿 | 一致 |
| runtime_layout_smoke | dev.ps1 口径 PASS | 直接跑 RC=0、residue absent | 一致 |

## ⑤ 未尽事项

1. auto-facts 漂 +2 待主会话裁 `--write` 时机（本席无写权，已备 expected 件）。
2. census 两行只读旁注未深究（均在册允许态）：读点盲区 3 枚 [no-canonical-derived]；G-P2 豁免 28/上限 29。
3. 「09:20 后被移走的约 6 枚未跟踪测试件」身份未考（不判归属；如需可由主会话派有权席考古）。
4. 本席全程未重启、未写仓库内任何文件；pytest basetemp 与取证产物均在 `%TEMP%\qoder-DER\`。
