# HDN 席工单 · half-done 盘点（2026-10-02 下午窗，只读）

## ① 目录清单（`.superpowers/sdd/2026-10-02-fixwave/half-done/`）
仅 1 件：`test_db_backup.py.HALF-WRITTEN` · 31813 B · 674 行 · mtime 2026-10-02 01:56。
**git 视角**：该路径不在索引、status 不可见（`.superpowers/` 疑被 ignore）→ 移动≠git 操作；正式件 `tests/test_db_backup.py` 现为 **untracked（`??`）**，641 行 28 腿，尚未入库。

## ② 腿名对比（半成品 32 腿 vs 正式件 28 腿）
- 精确同名 3 枚：`test_backup_root_inside_repo_is_refused`、`test_naive_now_is_rejected`、`test_restore_stage_refuses_production_and_repo_targets`。
- 意图改名覆盖（抽样证实）：WAL→`test_uncheckpointed_wal_row_reaches_copy_but_not_naive_copy`；backup API→`..._uses_connection_backup_api_only`；毒模式→`test_static_ruler_flags_poisoned_source`；keep_last/footprint 折进 `test_plan_lists_then_named_apply_deletes_exactly_the_victims`（keep_last=1/64 两枝在腿内）；清扫只读→`test_sweep_leaves_source_files_byte_identical`＋`test_ro_connection_rejects_writes`；递归删→`test_module_has_no_recursive_or_bulk_delete_shape`。
- **疑似缺口（关键字全 tests/ 无命中，需 owner 现算）**：a) verify 簇 4→1（正式件仅 `test_verify_backup_catches_bit_flip`；"passes on untouched copy"/"missing+truncated"/"row drift" 无同名腿）；b) 命令面簇 6 腿（roster 门/status 回执/run-then-verify/unknown verb usage/usage lines/派发腿）仅 `test_admin_import_points_to_domains_ops` 部分覆盖。
- 正式件另有半成品没有的新腿（safe_stem / copy_name regex / oversize skip / 旧路径扫描器 3 腿等）。

## ③ 在册引用（`git grep -c "HALF-WRITTEN" -- "*.md"`＝3 处 / 2 件）
- `docs/HANDBOOK.md:5747`：死坐标账（"测试件真身现为…"，归该波 owner）。
- `docs/HANDOFF-FIXWAVE-20261002.md:68`：X1c 入册行（"不是删除"裁定出处；"续写或重写"两选项，DBT 席已择重写）。
- `docs/HANDOFF-FIXWAVE-20261002.md:456`："半成品未删"。

## ④ 处置素材（不代裁）
- **留档原地**：零成本；两册引用路径保持字面有效；裁令"只准移不准删"下最稳。
- **移入更深归档**（规则 9 口径）：文件在 git 外，移动无 git 面；但 HANDBOOK:5747＋HANDOFF:68/456 三处字面路径同批失真 ⇒ 按 #68 教训须"移件＋改账本行"同批动，且需 owner/用户授权（引用行不在本席许可面）。
- **用户点名后删**：同样牵动三处引用行；删除后 HANDOFF:68 的"续写"选项证据链消失（重写已择，损失有限——素材如此，裁决归用户）。
- 附带事实：正式件未入库 ⇒ 无论怎么处置半成品，"正式件已覆盖原意"的结论在 commit 前都只算盘面态。

## ⑤ 未尽
- 疑似缺口两簇（verify 簇、命令面簇）未做行为级比对，仅腿名+关键字扫描；是否真缺口由 owner 现算裁。
- `.superpowers/` 是否 gitignore 未读 `.gitignore` 原文（由 status 不可见反推，置信 high）。
- 本席零写源码/测试，全程只读；本工单为唯一写面。
