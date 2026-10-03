# CHK-LOCKFAMILY-20261002 — 席 CHK 锁族普查工单（2026-10-02 下午窗·第三派）

- 席位：CHK（普查实跑，全程只读；唯一写面＝本工单）
- 跑窗：2026-10-02 16:35–17:05 (+0800) 本地
- 解释器：`../ChatBot_Runtime/venv/Scripts/python.exe`（Python 3.12.10 / pytest 9.1.1 / nonebot OK）。简报未指明解释器；系统 Python 3.12.10 无 nonebot（锁 2 首跑收集即败实证），锚必然出自运行时 venv ⇒ 自锁 1 复跑起统一 venv。
- HEAD：`143098d` docs(handoff): 十八节取证回收——两席产出入库副本+现算复核三格+三席额度墙阵亡账
- 前两席（平台并发墙弹回零产出）遗留缺口由本席全额补跑。

## ① 命令原文

```bash
mkdir -p "$TEMP/qoder-CHK/bt"
git status --porcelain          # 快照见⑤前附
# 模板（一条一把，不合并）：
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 \
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/<锁文件> \
  -q -p no:cacheprovider --basetemp="$TEMP/qoder-CHK/bt" --tb=short
# 锁 5+6 合跑：pytest tests/test_meme_album_commands.py tests/test_sticker_pools_consumers.py -q …
```
（`--tb=short` 为本席附加，仅为保断言首行；env 前缀与简报逐字一致，`BOT_AUTOSYNC=0` 全程硬带。）

## ② 逐把读数表（末行原样）

| # | 锁 | 末行原样 | 锚 | 与锚差 |
|---|---|---|---|---|
| 1 | tests/test_command_admin_gate_registration.py | `9 passed in 36.91s`（系统 python 亦 9 passed 31.48s） | 全绿 | ✓ |
| 2 | tests/test_tts_cache_quota_shape_guard.py | `22 passed in 11.86s` | 全绿 | ✓（系统 python 首跑收集败＝无 nonebot，解释器错配非文件漂移） |
| 3 | tests/test_download_artifact_container_gate.py | `21 passed in 14.70s` | 全绿 | ✓ |
| 4 | tests/test_central_dispatch_closure_gate.py | `25 passed in 14.02s` | 25 passed | ✓ |
| 5+6 | test_meme_album_commands.py + test_sticker_pools_consumers.py（合跑） | `143 passed in 44.25s` | 合跑 143 passed | ✓ |
| 7 | tests/test_config_key_registration_ledger.py | `4 failed, 35 passed in 637.92s (0:10:37)` | 39 passed in ~461s | ❌ **4 红**（总数 39 与锚同，仅 poison 地板腿翻红；耗时+176s 不判读） |
| 8 | tests/test_pipeline_offload_always.py | `10 passed in 3.79s` | 10 passed | ✓ |
| 9 | tests/test_documentation_consistency.py | `31 passed in 6.47s` | （简报未给锚） | — 记录 |
| 10 | tests/test_doc_link_integrity.py | `23 passed in 27.33s` | （简报未给锚） | — 记录 |
| 11 | tests/test_datafix_runtime_paths.py | `20 passed in 10.84s` | （简报未给锚） | — 记录 |

## ③ 红点名（失败 node ID＋断言首行，原样；未修、未判归属）

1. `tests/test_config_key_registration_ledger.py::test_poison_11_new_field_floor_tracks_the_field_set`
   — `Failed: DID NOT RAISE AssertionError`（tests\test_config_key_registration_ledger.py:1442: `with pytest.raises(AssertionError):`）
2. `tests/test_config_key_registration_ledger.py::test_poison_14_direct_read_floor_biteth_both_ways`
   — `AssertionError: 第 1 维红腿不红：喂 现算−容差−1＝1411 竟被判「没变瞎」 ⇒ 地板 1610 已低于现算 1612（放宽一格／容差被改宽）＝盲区回来了`
3. `tests/test_config_key_registration_ledger.py::test_poison_15_py_file_floor_biteth_both_ways`
   — `AssertionError: 第 3 维红腿不红：喂 现算−容差−1＝637 竟被判「没变瞎」 ⇒ 地板 687 已低于现算 688（放宽一格／容差被改宽）＝盲区回来了`
4. `tests/test_config_key_registration_ledger.py::test_poison_16_floor_boundary_shape_lock`
   — 同 2 原文（第 1 维：`地板 1610 已低于现算 1612`）

形态：四枚全是「地板/棘轮 双向咬合」poison 腿——地板落后现算 2／1 格且红腿判「没变瞎」，与台账 #68「★地板/棘轮按现算复录、容差一字不动」、#72「★地板落后现算会吃掉『砍穿容差』腿」同形。归属待裁。

## ④ 「漂了」格子的 mtime 旁证

| 项 | 值 |
|---|---|
| tests/test_config_key_registration_ledger.py mtime | `2026-10-02 12:12:20.974098800`（+0800，full-iso；普查跑于 16:35 起） |
| git status | ` M tests/test_config_key_registration_ledger.py`（工作树未入库件） |
| 旁证 | 本文件是 11 把锁中唯一 mtime 落在「当天午窗」且普查翻红者；其余十把 mtime ≤ Oct 2 08:53 且全绿（全 11 把 mtime 已留本席会话记录，漂移格以上两行为准） |

## ⑤ 未尽事项

1. 锁 7 的 4 枚红**未修、未判归属**（本席职责止于普查取证）；修法指向＝按现算复录地板＋容差逐字核对，或等在飞席交卷后重跑定论。
2. 六件别席已交卷件（test_seat_t1 / test_claims_subset / test_store_write_trace_d2 / test_prompt_template_w1 / test_migration_status / test_intimate）按简报未跑。
3. 锚未给解释器口径；本席统一 venv 解释器（见头注）。若锚出自其他环境，锁 7 耗时差（637.92s vs ~461s）请勿当漂移读。
4. 锁 9/10/11 无锚，本席读数即首锚（31P / 23P / 20P）。
5. 工作树在飞面很大（M×60＋??×15，快照见下），本普查只对上表 11 把锁背书，其余面零背书。

## 附：跑前 git status --porcelain 快照（原样）

```text
 M AGENTS.md
 M docs/HANDBOOK.md
 M docs/HANDOFF-FIXWAVE-20261002.md
 M docs/auto-facts.md
 M docs/boards/B02-routing-dispatch/README.md
 M docs/boards/B02-routing-dispatch/capability-registry/README.md
 M docs/boards/B02-routing-dispatch/decision-engine/README.md
 M docs/command-catalog.md
 M docs/db-owners.md
 M docs/design/capability-orchestration-adoption-spec.md
 M patches/R1-RUNTIME-LAYOUT-SCAN-20261002.md
 M plugins/bot_unified_runtime/control_plane/config_store.py
 M plugins/bot_unified_runtime/domains/chat_reply/capabilities/chat.py
 M plugins/bot_unified_runtime/domains/chat_reply/capabilities/echo.py
 M plugins/bot_unified_runtime/domains/chat_reply/character/memory_extract.py
 M plugins/bot_unified_runtime/domains/chat_reply/character/quirks.py
 M plugins/bot_unified_runtime/domains/chat_reply/character/reflection.py
 M plugins/bot_unified_runtime/domains/chat_reply/character/reply_policy.py
 M plugins/bot_unified_runtime/domains/chat_reply/runtime/aliases.py
 M plugins/bot_unified_runtime/domains/chat_reply/runtime/content_route.py
 M plugins/bot_unified_runtime/domains/chat_reply/runtime/deadline.py
 M plugins/bot_unified_runtime/domains/core/board_doc_ownership.py
 M plugins/bot_unified_runtime/domains/core/board_shim_ledger.py
 M plugins/bot_unified_runtime/domains/files/capabilities/download.py
 M plugins/bot_unified_runtime/domains/files/capabilities/file_exchange.py
 M plugins/bot_unified_runtime/domains/media/capabilities/media_archive.py
 M plugins/bot_unified_runtime/domains/media/capabilities/tts.py
 M plugins/bot_unified_runtime/domains/media/voice_enricher.py
 M plugins/bot_unified_runtime/domains/meme/capabilities/meme_library.py
 M plugins/bot_unified_runtime/domains/ops/admin/runtime_admin.py
 M plugins/bot_unified_runtime/domains/schedule/llm_draft.py
 M plugins/bot_unified_runtime/domains/schedule/timetable.py
 M plugins/bot_unified_runtime/domains/transport/sender/nonebot.py
 M plugins/bot_unified_runtime/runtime/capability_protocols.py
 M tests/render_hashes.json
 M tests/render_hashes.meta.json
 M tests/test_config_key_registration_ledger.py
 M tests/test_db_owners_coverage.py
 M tests/test_doc_link_integrity.py
 M tests/test_doc_ownership_ledger.py
 M tests/test_documentation_consistency.py
 M tests/test_e2e_acceptance.py
 M tests/test_e2e_help_matrix.py
 M tests/test_item9_bypass_retention_ledger.py
 M tests/test_legacy_shim_import_ratchet.py
 M tests/test_mica_builders_contract.py
 M tests/test_nonebot_sender.py
 M tests/test_ops_llm_diagnostic_single_source.py
 M tests/test_parser_contract_migration_v2.py
 M tests/test_persona_appearance_role_gate_pg1.py
 M tests/test_prompt_injection_order.py
 M tests/test_randpic_mutation_teeth.py
 M tests/test_reply_policy_permanent.py
 M tests/test_reply_policy_preset_command.py
 M tests/test_reply_style_imagery_default.py
 M tests/test_shim_retirement_ledger.py
 M tests/test_silent_skip_ratchet.py
 M tests/test_ssrf_throat_coverage.py
 M tests/test_trigger_word_single_source.py
 M tests/test_voice_hook_error_card_leg.py
?? .zcodeignore
?? patches/B1-CONFIG-REQUEST.md
?? patches/B1-TTS-CACHE-OUTTMPL-20261002.md
?? patches/DOC-DBBACKUP-REFS-20261002.md
?? patches/INT-INTIMATE-PERSON-GATE-20261002.md
?? patches/L1-TESTLINT-20261002.md
?? patches/MIG-STATUS-GATE-PREDICATE-20261002.md
?? patches/P3A-ROUTE-GATE-PROPOSAL-20261002.md
?? personas/shorekeeper/imagery_families.txt
?? plugins/bot_unified_runtime/domains/chat_reply/llm_engine/prompt_template.py
?? plugins/bot_unified_runtime/domains/core/write_trace.py
?? plugins/bot_unified_runtime/domains/ops/db_backup.py
?? tests/test_central_dispatch_closure_gate.py
?? tests/test_claims_subset_implementation_gate.py
?? tests/test_command_admin_gate_registration.py
?? tests/test_download_artifact_container_gate.py
?? tests/test_intimate_group_switch_delivery.py
?? tests/test_migration_status_assignment_gate.py
?? tests/test_prompt_template_layer_w1.py
?? tests/test_seat_t1_persona_contract_20261002.py
?? tests/test_store_write_trace_d2.py
?? tests/test_timeout_umbrella_remaining_legs.py
?? tests/test_tts_cache_quota_shape_guard.py
```
