# v21r4-B · S0-COLLECT 席日志（S0 直连点收编·非 root 件）

> 席位=S0-COLLECT｜开工=2026-09-18（会话时钟）｜协调表已登记。
> 方案权威=`docs/design/v21r4-b2-direct-collect-plan.md`（DIRECT-PLAN 席交付，已实读）。
> 范围（brief ②）：仅非 root 两件——file_gateway.py:382 直连收编 + outbound_registry.py:589-600 陈旧坐标清理/对齐。根 `__init__.py` 四处=pending-on-RWC5-b（见 §四），本席零改动。

## 一、取证（全 verified=本会话实读实跑；坐标为 2026-09-18 读时快照）

### 1. file_gateway.py:382 定性复核（brief ① 的前提核实）

- 旧路径 `plugins/bot_unified_runtime/sender/file_gateway.py` 现为 **3 行 compat shim**（实读），真身=`domains/transport/sender/file_gateway.py`（460 行）。
- 登记坐标 :382 实为 `FileTransferGateway._deliver_onebot`（def :349）的 **call_api 退化分支**（`:382 result = await asyncio.wait_for(call_api(api, **params), ...)`；getattr(bot, api) 优先 :377-380）。
- **该「直连」=统一文件出站路径自身的通道本体**：`domains/transport/sender/onebot.py` `_send_file_parts`（:423）文件部件分支统一经 `get_default_file_gateway()`（:450，import 自 file_gateway 模块 :19-22）stage→deliver；上游 `domains/render/renderer.py:214-216` `CapabilityResult.files`→media_parts。全库生产侧无绕行实例（DIRECT-PLAN §二④ grep 同证）。
- **结论**：brief ① 的「收编走统一文件出站路径」在本坐标上无行为可收编——它已是统一路径本体；真正绕行点=根 `__init__.py:5303-5314`（文档导出 upload 直连，pending-on-RWC5-b）。本席动作=登记表修正（PENDING_RULING→CHANNEL_BODY + 路径/证据对齐真值）+ 统一路径锁测试，与 DIRECT-PLAN §二④裁定建议、§3.5 一致。

### 2. outbound_registry.py 陈旧面实读（`domains/core/decision/outbound_registry.py`）

- `:591-594` BYPASS_SUSPECT `__init__.py:4070-4071` send_private_msg → 现真身=cookie 到期提醒 `__init__.py:4300-4304`（:4301 API 名，grep 实证）。
- `:595-598` BYPASS_SUSPECT `__init__.py:4878-4879` send_group_msg「群成员变动通知区」→ 现真身=入群欢迎 `__init__.py:5184-5188`；:4878 区现为 poke 执行器装配区（OutboundSideEffectExecutor :4860/:4873，L34 已收编）。
- `:599-602` BYPASS_SUSPECT `__init__.py:5175-5182` 双通道「管理命令回复区」→ 现真身=二维码图片 `__init__.py:5481-5492`（:5482/:5488）；:5169-5175 现为 get_group_member_info 读路径。
- **登记缺口**：文档导出上传（根 `__init__.py:5303-5314`，upload_group_file :5304 / upload_private_file :5311，grep 实证）在 direct_sends 无登记项（原 SEND_FILE 证据串错指 file_gateway:382 顶缺）→ 按「不删语义、补真值」补一条 BYPASS_SUSPECT。
- `:619-622` PENDING_RULING `sender/file_gateway.py:382` → 见 §一.1，改 CHANNEL_BODY + `domains/transport/sender/file_gateway.py:349-391`。
- `:192-193`（SEND_MESSAGE evidence）引用陈旧坐标 4071/4879/5175-5182；`:199`（SEND_FILE evidence）引用 `sender/file_gateway.py:382` ——随坐标修正同步（内部一致性）。
- **测试锁实证**（DIRECT-PLAN unknown→verified）：`tests/test_outbound_v21.py::test_direct_send_categories_cover_a1`（:680-706）钉死字面量 4070/4878/5175/4745/reactions.py:652/file_gateway.py:382；`:633` `direct_send_entries >= 10`（现 12→补 1 后 13，仍绿）。

### 3. 明确不动（防扩界）

- poke（:607-610，:4745,4751 陈旧+已收编未记）、reaction（:611-618，runtime/reactions.py 已是 shim 真身 domains/meme/reactions/engine.py）、delete_msg（:603-606，:4569→现 :4802）三条相邻陈旧：**不在 brief 坐标（:589-600 + file_gateway）内，零改动**，列 §五残余移交。
- 根 `__init__.py` 四处直连本体：零改动（RWC5-b 独占写域）。

## 二、TDD 两态记录（实跑）

- **RED**（修复前，`--basetemp=$TEMP/s0collect-red`）：`4 failed, 1 passed in 1.45s`
  - failed=test_file_gateway_entry_reclassified_channel_body_at_real_path（PENDING_RULING 仍在）/ test_file_gateway_entry_resolves_to_deliver_onebot_inner_loop（坐标指 shim）/ test_root_bypass_suspects_refreshed_and_doc_export_registered（3 suspects 非四、旧坐标在）/ test_transport_registry_evidence_no_longer_cites_stale_coordinates（4071/4879/5175 在）；
  - passed=test_unified_file_outbound_chain_consumes_file_gateway（统一链**本就存在**，属回归锁性质，先绿=链路在位的前提实证）。
- **修复面（最小）**：`outbound_registry.py` 直发登记 3 条坐标刷新 + 1 条文档导出补登 + file_gateway 条目改判（PENDING_RULING→CHANNEL_BODY、路径对齐真身）+ SEND_MESSAGE/SEND_FILE 两条 evidence 串同步；`tests/test_outbound_v21.py` 坐标字面量同测同改（DIRECT-PLAN §3.5「随测试同改」授权；unknown→verified：坐标字面量确被 `test_direct_send_categories_cover_a1` 钉死）。中途一处自纠：SEND_FILE 证据串初版含旧字面量与本席断言相抵，去字面量保语义（历史注记保留在直发登记项 evidence 侧）。
- **GREEN**（修复后，`--basetemp=$TEMP/s0collect-green2`）：`64 passed in 3.23s`（test_v21_s0_collect 5 例 + test_outbound_v21 59 例）。

## 三、交付清单

1. `plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py`（登记数据面修正）
2. `tests/test_v21_s0_collect.py`（新增，离线契约锁 5 例）
3. `tests/test_outbound_v21.py`（坐标字面量同改，方案 §3.5）
4. 本日志

## 四、pending-on-RWC5-b（根内四处，本席不执行）

依赖：等协调表 RWC5-b（根 `__init__.py` 独占写）交付释放后，由后续席按 DIRECT-PLAN §3.1-§3.4 执行行为收编（形态 B/A/A/D，配置门缺省关）。四处读时快照（2026-09-18，实施席须符号 grep 复核，勿照抄行号）：

| # | 内容 | 快照坐标 | API | 收编形态 |
|---|---|---|---|---|
| ① | cookie 到期每日提醒 | `__init__.py:4300-4304` | send_private_msg | B（提醒范式 `_deliver_due_reminders`） |
| ② | 入群欢迎 | `__init__.py:5184-5188` | send_group_msg | A（`_send_text_through_unified_pipeline`） |
| ③ | cookie 二维码图片 | `__init__.py:5481-5492` | send_group_msg + send_private_msg | A（mixed 图片件） |
| ④ | 文档导出上传 | `__init__.py:5303-5314` | upload_group_file + upload_private_file | D（`CapabilityResult.files`→FileTransferGateway 既有链） |

本席已把四处快照坐标+pending-on-RWC5-b 注记写入登记表 BYPASS_SUSPECT 条目，后续席接手即有锚。

## 五、残余移交（登记表相邻陈旧，零行为影响，建议归登记表 owner/后续维护席）

- poke 条目（:4745,4751）：L34 已收编（OutboundSideEffectExecutor，根 :4860-4918 装配），登记未记；坐标陈旧。
- reaction 条目（runtime/reactions.py:652-655 / :681-686）：真身已迁 `domains/meme/reactions/engine.py`（旧路径为 shim）；L35 收编未记。
- delete_msg 条目（:4569 → 现 :4802）。
- `tests/test_outbound_v21.py:693-698` 仍钉上述旧字面量——三条若刷新须同测同改（本席未动，保持其绿）。

## 六、实跑证据（解释器=`../ChatBot_Runtime/venv/Scripts/python.exe`——venv 实际在工作区上级目录，brief 模板相对路径的落点修正；全部离线）

1. RED：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_s0_collect.py --basetemp="$TEMP/s0collect-red" -p no:cacheprovider -q` → **4 failed, 1 passed in 1.45s**（失败原因=被锁事实未修，见 §二）。
2. GREEN：同命令 +test_outbound_v21.py `--basetemp="$TEMP/s0collect-green2"` → **64 passed in 3.23s**（新 5 例 + 存量 59 例）。
3. 相关存量面终跑（六文件合跑 `--basetemp="$TEMP/s0collect-final"`）：test_v21_s0_collect + test_outbound_v21 + test_runtime_subfeatures + test_v21_dispatch_outbound_wiring（L34 executor 装配）+ test_v21_wiredirect_unified_path（L56/57/58/65 结构锁）+ test_phase0_3_features（upload 走 FileTransferGateway 行为测试）→ **125 passed in 5.78s**。
4. ruff 本席三文件（outbound_registry.py / test_v21_s0_collect.py / test_outbound_v21.py）→ **All checks passed!**（全树现存红属前端在飞域，未代修）。
5. `python scripts/command_catalog.py --check` → **command catalog is current (77 topics)**。
6. `python scripts/doc_sync.py --check` → 漂移（本席新增测试文件 +1 直改 `_test_file_count()` 事实）→ 按 brief 执行 `--write` 重录 → 复检 **exit=0**。注意：重录=当前树机械真值全量刷新，含他席在飞计数（RouteKind 33→34 含 TTS、帮助 topic 75→77、config 字段 529→610、测试文件 326→416 含本席 +1、哈希清单路径 reorg 后真身）——共享机械事实册的既定刷新语义，非本席业务改动。
7. `python tests/verify_hashes.py --check` → **15 项漂移，零项属本席文件**（全清单=domains/render/** 模板×7+theme_tokens+bridge+usage_cards+templates.py、docs/rendering-contract.md、DESIGN-SPEC.md、domains/ops/admin/debug.py、domains/chat_reply/capabilities/echo.py——全为渲染/前端在飞席位的工作树在飞态）。本席改动文件无一在 19 项哈希清单（全为 render/contract 面）→ **红非本席致**，且**不代执行 --write**（会把他人半成品态录进清单）。连带实测：test_cross_validation_gates.py → 1 failed（test_verify_hashes_manifest_clean，同一 15 项漂移的常驻门形态，非本席致）+ 1 passed（doc_sync 门，本席 --write 后转绿）。

## 七、诚实声明

全部改动=离线数据面+测试，零生产行为变更、零真实 LLM 调用、零对外发送、零重启、零 git 写操作。「登记表坐标对齐」≠「直连点已收编」——根内四处直连仍在，行为收编待 RWC5-b 交付后由后续席执行。
