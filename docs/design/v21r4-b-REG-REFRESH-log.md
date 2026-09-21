# v21r4-B · REG-REFRESH 席日志（outbound_registry BYPASS_SUSPECT 四条刷新 + S0-COLLECT §五残余对齐）

> 席位=REG-REFRESH｜开工=2026-09-19（协调表已登记认领行）。
> 移交链：DIRECT-PLAN §3.5（⑤登记表刷新方案）→ S0-COLLECT 日志 §五（poke/reaction/delete_msg 残余移交 + test_outbound_v21.py:693-698 钉死字面量）→ S0-ROOT-c 日志（四处已收编终态 + 登记表状态刷新移交）→ **本席**。

## 一、取证终态（全 verified=本席实读实跑，2026-09-19）

1. **四处 BYPASS_SUSPECT 已收编**（S0-ROOT-c 交付，本席逐一 grep/实读复核）：四处旧直连全部保留为 `*_via_queue` 门**关分支**（缺省 False），门开分支走统一路径——①cookie 提醒=形态B（`_deliver_cookie_expiry_report_via_queue` @ :2974，门 :4418）、②入群欢迎=形态A（门 :5359）、③二维码=形态A mixed（门 :5703）、④文档导出=形态D（门 :5495）。测试=`tests/test_v21_s0_root_collect.py`（27 例）。
2. **门关旧直连现坐标**（根 `__init__.py` 在飞编辑后又漂，grep 实读）：①:4440-4444 / ②:5378-5382 / ③:5730-5740 / ④:5526-5538。
3. **poke 直连点已不存在**：根 `__init__.py` grep `group_poke|friend_poke` **零命中**——L34 全接管，现执行面=`control_plane/dispatcher.py:162-220`（`OutboundSideEffectExecutor.execute`→:200 `call_api`，方法名经 Transport 固定映射解析），装配 `__init__.py:5049-5099`。
4. **reaction 真身**：`domains/meme/reactions/engine.py`（`runtime/reactions.py`=纯 re-export shim，实读确认）——QQ=`react_to_message` :754-782 经 `_REACTION_OUTBOUND_EXECUTOR`（:664）统一出站面；TG=`react_telegram_message` :785-813（docstring 自述未接线触发点，语义保持）。
5. **delete_msg 现坐标 :4978**（dirty guard `_handle_dirty_guard`）——brief 所引 :4802 为 S0-COLLECT 读时快照，其后行号又漂，按诚实红线以 grep 实况登记。

## 二、刷新 diff 摘要

### `plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py`（8 处，零新字段、零行为改动）

| # | 位置 | 旧 → 新 |
|---|---|---|
| 1 | direct_sends 节头注释 | 「四处 pending-on-RWC5-b 待收编」→「已由 S0-ROOT-c 收编为 *_via_queue 门开分支（门缺省 False=门关直连等价）」 |
| 2 | BYPASS_SUSPECT ① | 坐标 :4300-4304→**:4440-4444**；note=已收编（形态B+门键+当日幂等+测试坐标），前态 pending-on-RWC5-b 注记保留为「已终结」 |
| 3 | BYPASS_SUSPECT ② | :5184-5188→**:5378-5382**；note=已收编（形态A+SENT/REDIRECTED 才记事件） |
| 4 | BYPASS_SUSPECT ③ | :5481-5492→**:5730-5740**；note=已收编（形态A mixed+audit_tags=cookie_login_qr） |
| 5 | BYPASS_SUSPECT ④ | :5303-5314→**:5526-5538**；note=已收编（形态D+FileTransferGateway 链） |
| 6 | delete_msg（BY_DESIGN） | :4569→**:4978**（evidence 记 :4569→:4802→:4978 漂移链） |
| 7 | poke（BY_DESIGN） | :4745,4751→**control_plane/dispatcher.py:162-220**（L34 executor 面；note 记「直连点已不存在」+装配坐标+映射解析语义） |
| 8 | reaction QQ/TG（BY_DESIGN） | runtime/reactions.py:652-655 / :681-686→**domains/meme/reactions/engine.py:754-782 / :785-813**（L35 已收编+shim 注记） |

- Transport 侧同批对齐（内部一致性）：QQ SEND_MESSAGE evidence（四处坐标改「已收编」+现门关坐标）、QQ DELETE/POKE/REACTION 与 TG REACTION 的 description/evidence（「待收编」→「已收编」、shim 路径→真身路径）。
- **类别面零变更**：四条保持 BYPASS_SUSPECT、poke/reaction/delete 保持 BY_DESIGN（登记表是快照投影，收编语义入 note/evidence，不改分类学）。

### `tests/test_outbound_v21.py`（`test_direct_send_categories_cover_a1` 同测同改，DIRECT-PLAN §3.5 授权）

- suspects 钉死坐标 4300/5184/5481/5303 → **4440/5378/5730/5526**；新增 `all("已收编" in note)` + `all("via_queue" in note)` 状态锁（注释明示不写「已生效」）。
- by_design 钉死 `4745`/`reactions.py:652` → `control_plane/dispatcher.py:162` / `reactions/engine.py:754` / `reactions/engine.py:785` / `4978`；新增负锁 `4745 not in` / `runtime/reactions.py not in`（陈旧清零棘轮）。
- bodies/PENDING_RULING 断言不变（file_gateway 改判与通道本体口径未动）。

## 三、关键裁决记录（两处，本席自主裁定+依据）

1. **pending-on-RWC5-b 字面量以前态注记保留**：S0-COLLECT 契约锁 `tests/test_v21_s0_collect.py:171` 钉死四条 suspect note 须含该字面量，且该文件**不在本席可改清单**（只准改 outbound_registry.py + test_outbound_v21.py）。解法=note 写「前态注记 pending-on-RWC5-b 已终结」——锁保持绿、语义如实（收编事实以 S0-ROOT-c 日志为准）。**建议**：该锁的「pending」意图已过时，归后续 owner 演进为钉「已收编+via_queue」（与本席 test_outbound_v21 新状态锁同构）。
2. **delete_msg 按 grep 实况 :4978 登记**（brief 的 :4802 已漂）：登记表坐标一贯为读时快照口径，漂移链入 evidence（:4569→:4802→:4978）。

## 四、实跑证据（解释器=`../ChatBot_Runtime/venv/Scripts/python.exe`，全离线）

1. **RED**：`PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1 …python.exe -m pytest tests/test_outbound_v21.py --basetemp="$TEMP/regrefresh-red" -p no:cacheprovider -q` → **`1 failed, 58 passed`**（唯一红=本席目标测试 `test_direct_send_categories_cover_a1`，断言 :693 `any("4440"…)` 先炸=钉新实况生效）。
2. **GREEN（家族五文件合跑）**：`…-m pytest tests/test_outbound_v21.py tests/test_v21_s0_collect.py tests/test_v21_s0_root_collect.py tests/test_v21_wiredirect_unified_path.py tests/test_v21_dispatch_outbound_wiring.py --basetemp="$TEMP/regrefresh-green" -p no:cacheprovider -q` → **`115 passed`**（含 S0-COLLECT 契约锁 5 例全绿=前态注记方案成立）。
3. **陈旧坐标清零核验**：grep 登记表 `4300-4304|5184-5188|5481-5492|5303-5314|4745,4751|:4569|runtime/reactions.py:|4070|4071|4878|4879|5175` → 残余 5 行全为 evidence/note 内**历史注记**（「原登记…已漂移/已消失/系 shim 旧路径」），登记 location 本体零残留。
4. **ruff**：`python -m ruff check plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py tests/test_outbound_v21.py` → **All checks passed!**
5. **command_catalog**：`python scripts/command_catalog.py --check` → **command catalog is current (77 topics)**。

## 五、诚实边界与硬约束

- 「已收编」=代码面收编（门开分支在位+测试锁在位）；**≠已生效**——四门缺省 False，重启不拨门=生产零变更（与 S0-ROOT-c 日志口径一致）；真机验收仍=acceptance-manual 重启窗口四处各触发一次。
- 本席零 git 写、零子代理、零真实 LLM 调用、零对外发送、零重启；触碰文件仅 `outbound_registry.py` + `tests/test_outbound_v21.py` + 本日志 + 协调表两行（认领+收工）；禁改域（根 `__init__.py`/echo.py/theme_tokens/render/**/tts 等）零触碰。
- 遗留移交：S0-COLLECT 契约锁（test_v21_s0_collect.py）的 pending 语义演进（见 §三.1 建议）。

——REG-REFRESH 席 收尾（2026-09-19）。
