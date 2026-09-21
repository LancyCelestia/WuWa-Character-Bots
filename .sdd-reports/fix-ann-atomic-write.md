# fix-ann-atomic-write（2026-09-20）

范围：只改 `vector_knowledge.py` + 新增 `tests/test_ann_atomic_publish.py`。零生产写入、零 git 写操作、零网络。

## 1. 改动坐标（`plugins/bot_unified_runtime/domains/chat_reply/character/vector_knowledge.py`）

| 行 | 内容 |
|---|---|
| 143-148 | `_ANN_ATTESTATION_KEY` / 锁文件名 / 抢锁超时常量 |
| 151-231 | `_AnnBuildGate`：OS 文件锁（win `msvcrt.locking` / posix `fcntl.flock`），进程死亡自动释放 |
| 236-270 | `_fsync_path` / `_atomic_replace_from`（tmp→fsync→`os.replace`，失败清 tmp）/ `_sha256_file` / `_stat_stamp` |
| 600,897,1650 | `_ann_loaded_stamp`（载入态文件指纹）+ 缓存失效点一并复位 |
| 1630-1647 | `_ann_lock_path` / `_ann_stat_pair` / `_read|_write_ann_attestation` |
| 1680-1721 | `_ann_pair_consistent`：按代际证明校验 `.index`/`.order.json` 同代 |
| **1722-1779** | **`load_ann_index` 代际感知**：命中缓存只比两次 stat；指纹变了丢弃重开；不成对→拒绝载入回落暴力 |
| **1804-1835** | **`build_ann_index`**：`_maintenance_lock` → 建锁闸；抢不到返回 `{"built":false,"reason":"locked_by_other_process"}` |
| 1837-1844 | `_require_ann_lock`：无锁覆写直接 `RuntimeError`（堵旁路写口） |
| **1846-1899** | **`_publish_ann_pair`**：两文件各写 `.tmp`+fsync → 成对 `os.replace` → SQLite 写代际证明作提交点 |
| 1900+ | `_build_ann_index_locked`：原重建主体，**删除其内部重复取维护锁**（非重入锁，否则每次自锁死；代价是 65 行机械缩进 diff） |

原 1606 `faiss.write_index(index, str(index_path))` 就地覆写已消失；全文件仅剩 1865 一处，目标恒为 `.tmp`。

## 2. 实跑证据

GREEN（scoped，14 例）：
```
$ PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -B -m pytest \
    tests/test_ann_atomic_publish.py -q --basetemp=$TEMP/annfix2 -p no:cacheprovider
14 passed in 10.23s
```
回归网（含 kb_wiki / knowledge_service / perf / 装配 / 检索族）：
```
... -m pytest tests/test_ann_atomic_publish.py tests/test_perf_p1.py tests/test_kb_wiki_sync.py \
    tests/test_kb_wiki_metadata_sync.py tests/test_knowledge_mtime_cache.py \
    tests/test_v21_knowledge_service.py tests/test_sdd9_n3re.py tests/test_auditfix_main_character.py \
    tests/test_v21_wire_svc_assembly.py tests/test_moegirl_question_fix.py -q --basetemp=$TEMP/annfix-final -p no:cacheprovider
114 passed in 15.82s
```
静态门：`ruff check` → `All checks passed!`；`mypy --explicit-package-bases --ignore-missing-imports <本文件>` → `Success: no issues found`。

RED（同一套用例，用插件把发布段还原成修复前语义：就地写、无锁、缓存不失效）：
```
$ PYTHONPATH=$TEMP/annfix_plugin_dir ... -m pytest tests/test_ann_atomic_publish.py -q \
    --basetemp=$TEMP/annfix-red-run -p no:cacheprovider -p legacy_ann_plugin
10 failed, 4 passed in 6.06s
```
（失败集含三项验收点：`test_faiss_write_never_targets_the_live_index_path`、`test_mixed_generation_pair_is_never_served`、`test_second_writer_is_locked_out_and_files_untouched`。）

零生产写入自证：`knowledge_faiss.index` mtime 仍为 `Sep 14 05:55`，Runtime 下无 `.tmp`、无 `.build.lock`；生产 WAL `Sep 20 06:02` 64MB = 补嵌进程在跑，未被触碰。源码树无 `__pycache__`/`.pytest_cache`/`data/`。

## 3. 与你给的口径不一致处（实测推翻，别按原话记）

简报说 mmap 文件被就地覆写会让运行中 Bot「读到撕裂页」。我在 `%TEMP%` 用真 faiss 1.15 实测：`write_index` 就地截断重写后，**已持有的 mmap 句柄仍稳定服务旧代**（ntotal 2000→50、50→20000 双向都复现），Windows 上 `os.replace` 在 mmap 打开时也能成功。所以本机实害不是「撕裂常驻映射」，而是三条同样致命的：①覆写窗口内**任何新载入**该文件的进程（重启的 Bot、第二个 store、`pre_restart_check` 的 `read_index`）打开的是半写文件；②`.index` 与 `.order.json` 分两次写 → 混代被当成有效索引用（邻居 id 错位，**不报错、直接答错**，比段错误更坏）；③无跨进程锁 → 两个写者交织可把 154MB 文件永久写坏。修法不变，只是理由要换这几条才站得住。

## 4. 残留（未修，越界了）

- `knowledge_service._swap`（422-444）与 `smoke.py:2908` 我不可改。前者 move-out→backup→move-in 仍有「index 已进、order 未进」窗口——但被本次读方代际校验兜住（不成对即拒用），已从「可能错答」降为「短暂回落暴力扫描」。
- 正在跑的补嵌进程是**修复前代码**，不受新锁保护；它只 embed 不碰 ANN，所以真正危险方是新起的 knowledge-sync（走新代码、会拿锁）。
- `ann_pair_attestation` 只在 `knowledge_meta`，删库内该行即退回旧宽松校验（向后兼容存量产物，刻意为之，有用例锁）。

## 5. 步骤 2（重建 ANN）安全顺序

**先记一条实测结论：停 Bot 不是文件层面的必需品。** 跨进程实测（`%TEMP%/xproc`，两个真 python 进程）：子进程 `read_index(IO_FLAG_MMAP)` 持有 `shared.index` 期间，父进程 `os.replace` 换入 500→900 条的新索引返回 **OK**，且持有者之后仍能正常检索旧代（ids 全在 0..499）——Windows 上 faiss 的 mmap 不挡同卷原子换名，旧映射钉在旧文件对象上。所以「停 Bot」的真实理由是第 6 条（代码要重启才生效），不是怕换不入失败。

1. **等补嵌进程退出**（看 `Get-Process` / WAL 是否停止增长）。别在它跑的同时重建：它是修复前代码、不受新锁保护。
2. 跑 `dev.ps1 -Task knowledge-sync`（内部 `build_ann_index`）。核对返回 `ann_index_built=true`、`vectors≈35479`；若 `reason=locked_by_other_process` 说明另有写者在持锁，**先查是谁，别绕锁硬来**。
3. 三件核对：`data/` 下无 `*.tmp` 残留；`knowledge_faiss.index.build.lock`（0 字节凭证）可留不用删；`pre_restart_check` 的 `kb_drift` 门转绿（ANN ntotal == chunks 行数 == 无待嵌行）。
4. **提权重启 Bot**（本仓铁律：改代码必须重启；本次改动含 `load_ann_index`，旧生产进程内存里仍是「载入即永久缓存」的老逻辑）。
5. 重启后验证收敛：此后任何一次外部重建，运行中的 Bot **不需要再重启**就会换到新一代（`load_ann_index` 比对 (size, mtime_ns) 指纹自动重开；日志会出一条 `knowledge ANN generation changed externally, reopening`）。
6. 磁盘不是瓶颈：原子换入峰值 ≈2×154MB（将来 kb_wiki 全量重建 ≈2×1.04GB），C: 现有 134.36GB 余量。

**最省事的正确顺序 = 补嵌跑完 → knowledge-sync 重建 → 提权重启 Bot**（重建可放在停 Bot 前，也可放后，两者都安全；只有「补嵌未结束就重建」这一种是危险的）。
