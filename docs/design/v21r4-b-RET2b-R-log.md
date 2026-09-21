# v21r4-B RET2b-R 席日志——挂起解除 4 张垫片退役（contracts.runtime / decision.outbound / sources.web_search / contracts.media）

- 席位：RET2b-R2（2026-09-19 开工）。接替两任阵亡前任：均平台瞬时故障 5 秒内即死、零产出、无断点，本日志为该席位首份落盘。
- 任务来源：RET2B-PREP §三移交清单挂起 7 张中冲突已解除的 4 张——
  - `contracts.runtime`（挂起因 RWC6-b policy/security 新领地+S0-COLLECT file_gateway 在飞，两者均已交付✅）
  - `decision.outbound`（挂起因 S0-COLLECT test_v21_s0_collect 在飞，已交付✅）
  - `sources.web_search`（挂起因 control_plane/api 硬禁，RK5 已交付释放✅）
  - `contracts.media`（35 src 面过大未做；其中 output/card_render/bridge 消费点属本波禁触面——开工前实扫裁决，见下）
  - 仍挂起不动（本席不触）：config_readiness / decision.trace / capabilities.debug（前端 echo/drift 面在飞未收口）。
- 方法沿 RET1/RET3/RET2B-PREP：①AST+rg 双轨全量消费方扫描（含 dev.ps1）→②消费方改指 canonical→③AST 级零残余验证（v2 教训：防 relative_to 吞前缀假 0，用绝对路径+显式归属判定）→④备份至 `%TEMP%/v21r4-ret2b-r-backup/plugins/bot_unified_runtime/<相对路径>`（逐件 sha256 记录）→⑤域回归实跑。
- 开工前检查：tests/render_hashes.json 对 4 张垫片路径零命中（涉即停红线未触发）；scripts/dev.ps1 对 4 张垫片零引用（PREP 批6 已修 30 处，无新增断链）。
- 纪律：固定解释器 `../ChatBot_Runtime/venv/Scripts/python.exe`；`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest `--basetemp=$TEMP/<唯一名> -p no:cacheprovider -q`；零 git 写操作；禁触面=根 `__init__.py`、echo.py/config_readiness/decision.trace/capabilities.debug 相关面、tts.py/config.py bot_tts_* 键块/tests/test_tts.py、theme_tokens.py/tests/render_hashes.json/domains/render/**/output/card_render/**/card_render/templates/**、docs/design/backend-v2-acceptance-matrix.md。

## 一、扫描与施工记录

（续写中）

## 二、主代理席接管（2026-09-20 12:4x，按用户「2 子代理+主代理干活」新规）

- RET2b-R2 阵亡（并发超限 4.5 分钟），主代理接管剩余 4 张，认领行已入 coordination.md。
- 宽口径扫描修正初扫漏计：contracts.runtime 实际 9 src 消费（含 media/registry、transport/sender file_gateway 两处漏网）+ dev.ps1:169 断言；contracts.media 实际 35+（**含 domains/render/card_render/bridge.py:683 前端独占消费→维持挂起**）；decision.outbound 4 消费；sources.web_search 7 消费（含 control_plane/api/platform.py:457 三点相对导入）。
- 施工：Python 行级批量改写（只动 import 行，不碰 docstring；跳过 bridge.py）→ plugins 39 文件 + tests/scripts/bot.py 30 文件 = **69 文件**改指 canonical；AST 验证旧路径 import 残余 **0**（bridge.py 豁免面除外）。
- 删除 3 张垫片（contracts/runtime.py、decision/outbound.py、sources/web_search.py），备份 sha256 前缀：5e9a1237a8413608 / d116611792ac3125 / bd03598a19888150（%TEMP%/v21r4-mainagent-ret2b-backup/）。**contracts/media.py 保留**（bridge.py 前端收口后随挂起队列退役）。
- dev.ps1:169 断言已改指 domains\core\contracts\runtime.py。
- 全量回归后台实跑中（basetemp=v21r4-mainagent-ret2b-full），结果待录。

## 三、全量回归与两处连带修复（主代理席，2026-09-20 13:0x）

- 全量二跑：**8535 passed / 3 failed / 12 skipped / 3 xfailed（486s）**。3 失败归属：test_webui_http×1=前端在飞面（与 SYNC-FINAL-b 两时点基线一致）；另 2 条为我删垫片连带、**已修复**：
  1. test_outbound_v21 子进程导入探针字符串仍指已删垫片 → 改指 domains.core.decision.outbound（import 行过滤的盲区=字符串参数形态）；
  2. test_v21_s10_protocols 描述符 implementation_ref 不可解析 → capability_protocols.py `_SEARCH_REF` 改指 domains/core/search + search.acg 显式指 sources/acg_search.py（acg 真身未迁，逐 descriptor 校准）。复跑：test_outbound_v21+s10 族 **117 passed + 59 passed, 1 skipped** 全绿。
- 包级 from-import 盲区补修 4 处（capability_protocols:1128 / test_auditfix_parsers:430,438 / test_outdomain_fixes_20260911:42 拆行）。
- 门禁：ruff 触碰面零错；command_catalog current (77 topics)；doc_sync --check 结果见门禁轮记录。
- 终态：**RET2b 剩余 4 张中 3 张已退役**（contracts.runtime / decision.outbound / sources.web_search，69+4 文件消费方归 canonical，AST 零残余）；**contracts/media.py 维持挂起**（bridge.py:683 前端独占消费，随前端收口退役）。垫片备份=%TEMP%/v21r4-mainagent-ret2b-backup/。
- 门禁补录：ruff 触碰面 2×I001 --fix 清零；doc_sync 预告 TTS 席后 --write 收敛、--check PASS。主代理席 RET2b 任务**关账**。
