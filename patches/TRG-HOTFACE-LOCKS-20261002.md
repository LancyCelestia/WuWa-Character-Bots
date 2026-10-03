# TRG 工单 · 14:10-14:27 热写面锁族核验（2026-10-02 下午窗，只读席）

席 TRG｜基线 HEAD＝143098d（10-02 11:27）｜验证窗口内零写入源码/测试/git 态；本工单为唯一产出件。
环境：`ChatBot_Runtime/venv/Scripts/python.exe`（pytest 9.1.1）；卫生前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 -p no:cacheprovider --basetemp=$TEMP/qoder-TRG/bt/*`。
HEAD 对照法：`git clone --shared --no-hardlinks` 至 `$TEMP/qoder-TRG/head-clone`（源树零触碰），克隆内 `import plugins.bot_unified_runtime` 实证解析到克隆树后复跑＝HEAD 态读数。

## ① 逐件读数表（末行原样）

| # | 件 | 末行原样 | 失败 node ID |
|---|---|---|---|
| 1 | tests/test_trigger_word_single_source.py | `2 failed, 16 passed in 82.18s (0:01:22)` | ::test_word_site_debt_within_ceiling、::test_copy_turned_into_reference_lowers_ledger_stays_green（计账债 475 > 上限 467） |
| 2 | tests/test_e2e_help_matrix.py | `25 passed in 7.06s` | — |
| 3 | tests/test_e2e_acceptance.py（DRY-RUN 件） | `13 passed in 2.48s` | — |
| 4 | echo 消费 4 件合跑：test_bot_commands_catalog_b10.py + test_capability_registry.py + test_addressing_single_source_gate.py + test_capability_health_readout.py | `2 failed, 63 passed in 20.52s` | 两红均在 test_capability_registry.py：::test_help_topics_equal_registry_book_order、::test_help_public_visibility_derived_from_declaration（`44 == 43` admin 主题锁） |
| 5 | tests/test_capability_declaration_parity.py | `2 failed, 15 passed in 11.89s` | ::test_capability_id_not_reshaped_by_two_unregistered_authors、::test_admin_only_help_set_is_fully_covered |

件 4 圈法：简报 `git grep -l … | head -8` 圈出 7 测试件（render_hashes.json 非测试），取 4 件、避开第⑤件 parity；未跑余量见 §⑤。

## ② 红与 HEAD 对照结论（全部六枚红）

| 红 | WT | HEAD 克隆复跑 | 分桶 |
|---|---|---|---|
| t1 词面债两枚 | 475>467 | 亦红，同 node ID（HEAD 债 487>467） | **既存**（11:27 前已在） |
| registry 两枚（44==43） | 红 | 亦红，同 node ID | **既存** |
| parity 两枚 | 红 | 亦红，同 node ID | **既存** |

WT 侧 t1 唯一数值变动：计账债 487→475、名册登记 62→74 条（＝热写会话在 test 件新增的「第五批」12 枚 INTENTIONAL_UNITS）；raw 两态同为 549（抄位零新增）。尺指纹：WT `1d79ee4ee58f1504`／HEAD `a9afaed777f6a1de`。

## ③ 总判定：热写面是否留了半成品

**码面与生成册：无半成品。** 六件热写物互相一致：meme_library.py `_ALBUM_RE` 加全拼 `biaoqingce(?![a-z0-9])`（bqc 有意不收防抢 `bqcq`）⇄ echo.py 表情册 aliases 加 `'biaoqingce'` ⇄ command-catalog.md 别名数 574→575 + 表情册别名行同批 ⇄ render_hashes.json/meta.json 同步（full_write_at `2026-10-02T06:27:16+00:00`＝14:27:16+0800，恰在窗内）。消费锁族（catalog b10／addressing 门／health readout／e2e 两件）全绿。

**一处悬账（点名交主会话）**：词面债锁为 **HEAD 既存红**（487>467，11:27 前已破），热写会话做了 12 枚登记把债压到 475，**仍未达上限 467、差 8 枚**——属「对既存红的减债未做完」，非热写新破坏。需裁定：续登记 ≥8 枚，或评审抬锁；现状下件 1 两红会持续挂红。

## ④ parity 两红是否仍恰是同两枚

**是。** WT 与 HEAD 恰为同两枚：`test_capability_id_not_reshaped_by_two_unregistered_authors`、`test_admin_only_help_set_is_fully_covered`（后者点名 bot.consent / bot.host_state / bot.meme_library 三能力缺执法判据覆盖）。无恶化、无新增。

## ⑤ 未尽事项

1. echo 消费件未跑余量：test_affinity_query.py、test_consent_command_surface.py 及 grep 第 8 位之后各件（简报只要求 4 件；test_capability_declaration_parity.py 由第⑤件单跑覆盖）。
2. render_hashes 自身的执法门（test_rendering_contract / test_mica_builders_contract / test_template_visual_audit）不在本席清单，未跑；本席只核对三生成册 diff 与码面一致性（人工比对）。
3. 首跑件 2/3 曾用系统 Python（无 nonebot）收集期 `ModuleNotFoundError`——环境误配非产品红，已换 Runtime venv 重跑双绿；结论以 venv 读数为准。
4. HEAD 对照凭 `$TEMP/qoder-TRG/head-clone`（--shared 克隆，占盘小），主会话如需复核 HEAD 读数可直接复用，否则可删。
5. registry `44==43` 与 parity 三能力的既存红属同族（admin 帮助主题扩张未同步锁面），归属在 11:27 之前的波次，本席不深挖，交主会话按台账路线处理。
