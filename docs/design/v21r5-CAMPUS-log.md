# v21r5 CAMPUS-FIX 席工作日志

## 简报摘要（开场）
- 任务：修复 tests/test_campus_digest.py 全文件 14 例失败（v21r2 域重组遗留测试债 + 坐标耦合漂移）。
- 纪律：零生产行为改动（除非实锤生产回归）；禁 git 写操作；禁子代理；不 commit。
- 已取证四类根因（主会话诊断，本席复核）：
  1. 纯函数 build_campus_forward_text 丢失 → 恢复模块级纯函数 + _build_forward_request 单一来源调用。
  2. outbound_registry.py campus 条目坐标漂移 → 刷新登记坐标至实际行号。
  3. capability id 注册集 bot.campus_forward 断言失败 → 按事实修对的一侧。
  4. 其余例逐例归因。
- 文件所有权：domains/assistant/campus/**、tests/test_campus_digest.py、outbound_registry.py（仅 campus 坐标行）、capability_registry.py（仅 campus 相关）。
- 解释器：ChatBot_Runtime venv；测试命令带 PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1。

## 进度
- [开场] 日志已建立。开始：实跑复现 14 例失败 + 通读测试文件。

## 五派开工（2026-09-19）
- 前四任死于平台故障即刻拒，零代码改动，断点即上表。
- 计划：①实跑复现 14 例 → ②通读测试+生产真身 → ③逐类修复（纯函数恢复/坐标刷新/注册集） → ④全绿+棘轮族回归 → ⑤逐例归因落盘。

## 六派开工（2026-09-19）
- 第五任同样平台故障零改动退场，断点同上。开始：①追加本条 log → ②实跑复现 14 例 → ③通读测试+campus 真身 → ④按四类根因逐类修复 → ⑤全绿+outbound 棘轮族回归 → ⑥逐例归因落盘 `CAMPUS-SEAT DONE`。

## 七派开工（2026-09-19）
- 前六任均死于平台故障（部分只来得及建 log），零代码改动遗留，断点同上。
- 本席策略：立即动手，边修边落盘，不等完整诊断。顺序=①纯函数恢复 → ②坐标刷新 → ③注册集 → ④逐例复核 → ⑤全绿+棘轮回归 → ⑥归因表 `CAMPUS-SEAT DONE`。

## 八派开工（2026-09-19，CAMPUS-FIX-8）
- 前七任均死于平台故障（多死于通读期零改动），断点=零代码改动，简报四类根因不变。
- 已实读真身 `domains/assistant/campus/campus.py`：`_build_forward_request`（L137-172）内联 `who/prefix/budget/body` 逻辑确认存在，纯函数待恢复。
- **修法计划**：
  1. 在 campus.py 模块级恢复 `build_campus_forward_text(group_id, sender_name, text) -> str`：逻辑=内联四行原样提出（who/prefix/budget/body，逐字节行为不变）；`_build_forward_request` 的 body 改调该函数（单一事实源）；`capabilities/campus.py` 垫片走 import * 自动带出，不动。
  2. 实读 `domains/core/decision/outbound_registry.py` campus 条目与 root `__init__.py` 实际行号，方向以实读为准刷新坐标；`.submit(` 扫描窗断言一并核对（漂移→修坐标；真残留→上报）。
  3. 实读 `runtime/campus` 注册面（capability_registry.py / 断言所指），campus=被动监听语义（#33 批），按事实修对的一侧。
  4. 其余例逐例跑归因，多为 1/2 连带。
  5. 收尾：全文件绿 + test_outbound_v21.py 棘轮族回归 + 归因表 + `CAMPUS-SEAT DONE`。
- 每修一类立即实跑对应测试并在此落盘。

## 九派开工（2026-09-20，CAMPUS-FIX-9）
- 实跑复现：**14 failed / 15 passed**，与简报一致。但根因取证**推翻简报前提**：
- **真身路径修正**：域真身=`plugins/bot_unified_runtime/domains/assistant/campus/campus.py`（简报写 `domains/...` 少了插件前缀）。垫片 `capabilities/campus.py` 为未跟踪新文件（import * 薄壳），测试文件 `tests/test_campus_digest.py` 也是**未跟踪新文件**（mtime 01:40）。
- **决定性证据 `docs/design/audit-20260920-unify-U17-campus-wire.md`**：U17-CAMPUS-WIRE 席只完成 §0 取证 + §1.0 基线 RED，**§2 改动清单/§3 GREEN 全空、§4 裁定点标注「必须用户过目」**——收编改后态从未落地。全树 grep 证实 `build_campus_forward_text/message/capability` 三函数**零存在**（HEAD 与工作树皆无）；root `__init__.py:5044` handler 仍 `send_queue.submit(request)` 旁路；`CONTROLLED_INTERNAL_CAPABILITIES`/feature_catalog 均无 campus 登记；outbound_registry L432 campus 条目=改前形态（location 4581/priority None/note "campus"），而 matcher 真身=5012/priority 8。
- **14 例逐类归因（非 v21r2 域重组测试债，而是 U17 未实施规约）**：
  - test_forward_text_matches_legacy_bypass_verbatim：缺纯函数 + `_recorded_body` 依赖 record() 返回 `.body`（U17 payload 设计；现 record() 返回 SendRequest，contracts 实读**无 body 属性**）——只补纯函数仍红。
  - handler 四例 + 结构锁 test_handler_isolated_and_send_api_free + 端到端四例 + 目标私聊一例（共 10 例）：需要 `build_campus_forward_message/capability` + root handler 改走 `pipeline`（**root `__init__.py` 不在本席文件所有权**，且属生产行为改动）。
  - test_campus_forward_registered_for_feature_gate / test_campus_capability_id_literals_all_registered：需要注册登记 + **feature_catalog 绑定（不在所有权）** + builder（缺）。
  - test_outbound_registry_campus_coordinate_is_live：location 4581→5012（真实漂移，可修）+ priority→8（事实）+ note 需含 U17-CAMPUS-WIRE/中央管线（描述收编后形态）。
- 协调文档 v21r5-coordination.md L31 波次口径「14 例全部=campus 域重组遗留测试债…campus 生产链路完好」对本文件**不成立**——此为前提缺陷，按纪律上报，不自行默默改前提。
- 本席施工边界（照八派计划+所有权+零生产行为改动）：①恢复纯函数（零行为，git 证实纯函数历史上也不存在，属 U17 目标设计的安全前置件）→②registry campus 条目事实刷新→③注册面按事实核查后处置→④全文件实跑归因→⑤test_outbound_v21 棘轮回归→⑥归因表+U17 施工坐标移交清单落盘 `CAMPUS-SEAT DONE`。

### ① 纯函数恢复完成（GREEN）
- `campus.py` 模块级新增 `build_campus_forward_text`（内联四行原样提出）+ `_build_forward_request` body 改调该函数（单一事实源）；垫片 import * 自动带出未动。
- **计划外最小补件（已论证零风险）**：`CampusForwardRequest(SendRequest)` 子类——仅追加 `body` 只读 property（=content.text_fallback），**零新字段**；pydantic property 不参与序列化，`model_dump_json` 与基类逐字节一致（SQLiteSendRequestQueue L465 持久化零感知），StrictBaseModel extra="forbid" 不受影响。动机=测试文件两段对 record() 返回类型要求不相容（旧段要 SendRequest 字段、U17 段 `_recorded_body` 要 `.body`），子类 IS-A 是唯一零行为调和。record() 返回注解同步收窄。
- **测试夹具缺陷修正（所有权内）**：用例 c4 群号 "999999" 不在 `_source()` 白名单 {"111","222"}→被来源门正确拒绝 record()=None；该用例意图=预算边界附近非门外群，最小修正 "999999"→"222"（白名单内未用过的群，保用例区分度），注释留痕。
- 实跑：`pytest tests/test_campus_digest.py::test_forward_text_matches_legacy_bypass_verbatim` → **1 passed**（含 5 组 oracle 互证+1501 边界断言）。

### ② outbound_registry campus 条目刷新完成（GREEN）
- `MatcherEntry` 补 `note: str = ""` 字段（与 SchedulerEntry/RouteGroupEntry 同构，默认空零影响；此前 MatcherEntry 无 note 载体，测试 `entry.note` 断言必然 AttributeError）；campus 条目 location 4581→**5012**、priority None→**8**（实读 matcher 真身 `on_message(priority=8, block=False)`）、note 记 U17-CAMPUS-WIRE 收编指定+审计留痕，**status 保持 LEGACY=如实（旁路仍在岗）**。
- 实跑：coordinate 测试 + `tests/test_outbound_v21.py` 棘轮族全量 → **60 passed 零回归**。

### ③ 注册面补登完成（GREEN，F3 同口径）
- `domains/chat_reply/runtime/capability_registry.py` `CONTROLLED_INTERNAL_CAPABILITIES` 补登 `bot.campus_forward`（注释留痕：#33 批起随 SendRequest 真实流经队列/审计；U17 收编后 feature_gate 依赖，未登记即整链 fail-closed，audit §0.5）。绑定 `bot.campus_forward→bot.plugin.campus_forward` 由 `capability_feature_bindings()` 自动派生、descriptor 由 `build_product_descriptors()` 自动建节点，**无需碰 feature_catalog.py**（不在所有权的文件零接触）。
- 收编前门永不咨询该 id（旁路不经 feature_gate）→ 生产行为零变化。
- 实跑：`tests/test_v21_f3_outbound_capability_registration.py` + `test_runtime_feature_gate.py` + `test_runtime_subfeatures.py` 全绿（合跑 57 passed）。

### 静态门
- ruff：四文件（campus.py/outbound_registry.py/capability_registry.py/test_campus_digest.py）**All checks passed**（测试文件 10 处既有 lint 债清零：S102 按先例补 noqa、RUF100×3、I001×4、SIM102×2 合并嵌套 if）。
- mypy（项目口径 `--explicit-package-bases --ignore-missing-imports plugins`）：**Success: no issues found in 630 source files**。

## 终版归因表（14 failed→11 failed；18/29 绿）

| 测试 | 改前失败形态 | 本席处置 | 终态 |
|---|---|---|---|
| test_forward_text_matches_legacy_bypass_verbatim | ImportError 缺纯函数；又暴露测试文件自身两段 record() 返回类型不相容（`.body` vs SendRequest 字段） | ①恢复纯函数+单一事实源；②CampusForwardRequest(SendRequest) 仅加 body property（零新字段零序列化差异）；③修用例 c4 夹具缺陷（"999999" 不在其自身白名单→"222"） | **GREEN** |
| test_campus_capability_id_literals_all_registered | `campus_ids ⊄ bindings`（零登记） | ③补登后绑定自动派生 | **GREEN** |
| test_outbound_registry_campus_coordinate_is_live | location 漂移 4581≠5012、priority None≠8、MatcherEntry 无 note 字段 | ②坐标+priority 事实刷新+note 字段补齐 | **GREEN** |
| test_handler_dispatches_through_central_pipeline / no_forward_outside_source_gate / source_gate_rejects_foreign_group / duplicate_message_id_forwards_once | ImportError：`build_campus_forward_capability/message` 全树不存在（U17 从未实施） | **U17 残留，移交**（需 root `__init__.py` handler 改走 pipeline——不在本席所有权） | RED |
| test_handler_isolated_and_send_api_free | AssertionError：现网 handler 仍 `.submit(`（旁路在岗=被测「改后态」未落地）；域文件仍含 SendRequest 字面量 | **U17 残留，移交** | RED |
| test_forward_message_expresses_owner_private_target / complete_enqueues_owner_private_request_end_to_end / no_outbound_request_ever_targets_school_group / quiet_hours_and_rate_limit_do_not_swallow / central_claim_adds_second_idempotency_layer | ImportError：缺两个 builder（IncomingMessage 合成+能力工厂） | **U17 残留，移交**（audit §0.3 形态 A 三先例坐标已录） | RED |
| test_campus_forward_registered_for_feature_gate | ImportError（builder 在断言之首）；**登记面本身已由本席补齐**，builder 落地即过 | 登记半 DONE；builder=U17 残留 | RED |

**实跑定版**：campus+outbound_v21+F3+feature_gate+subfeatures 五套件合跑 **116 passed / 11 failed**（11 例全部=U17-CAMPUS-WIRE 生产实现残留，零 v21r2 重组债残余）。

## U17 移交清单（下一席施工坐标）
1. `domains/assistant/campus/campus.py`：实现 `build_campus_forward_message(source, payload)`（audit §0.3 形态 A：`session_id=f"private:{notify_qq}"`/PRIVATE/sender_id=notify_qq/group_id=None/bot_id=push_bot_id/message_id=payload.message_id/personal）+ `build_campus_forward_capability(source, payload)`；record() 转 payload 设计；届时撤 `CampusForwardRequest` 子类脚手架并同步重写旧段 L137-205 两例（现经 SendRequest 设计绿）。
2. `__init__.py` L5007-5044：handler 尾 `send_queue.submit(request)`（L5044）改 pipeline 分发（先例=今天历史推送 `:1819-1862`/订阅推送 `:4314-4351`），capability_id="bot.campus_forward" 字面量落 handler（test 13 扫描⊆bindings 已备好）。**注意与在飞席 S0-ROOT-c（根 init 直连收编）同文件，需主会话协调先后。**
3. 注册面：本席已备妥（CONTROLLED_INTERNAL_CAPABILITIES+自动绑定+自动 descriptor），无剩余动作。
4. **audit §4 裁定点（该席自标「必须用户过目」，落地前须用户裁决）**：①review 门新风险面——源群文本含密钥/路径形态会被拦；②截断满额 1501 字边缘消息在 min_chars=1500 时转合并转发。
5. 对照规约=`docs/design/audit-20260920-unify-U17-campus-wire.md`（§0 取证完整，§1.1 待补 RED 实跑原文，§2/§3 空）。

## 前提缺陷结论（上报主会话）
- 波次口径「14 例全部=campus 域重组遗留测试债」（v21r5-coordination.md L31）**不成立**：其中 11 例是 U17-CAMPUS-WIRE 席未实施收编的**验收规约**（测试文件未跟踪、审计文档 §2/§3 空、三 builder 全树零存在、root handler 旁路在岗），非重组债；修绿=生产收编实施+越席文件（root `__init__.py`）改动，超出本席「零生产行为改动+所有权」边界，按八派计划「真残留→上报」条款移交。
- 本席 3 绿（纯函数/注册登记/坐标刷新）全部零生产行为改动、所有权内、有实跑证据。

**CAMPUS-SEAT DONE** — 2026-09-20，CAMPUS-FIX-9（第九派；前八派零改动死于平台故障）。

## XFAIL 席开工（2026-09-20，CAMPUS-XFAIL）
- 任务：把剩余 11 例 U17 残留失败**诚实挂账 xfail**（编码的是 U17-CAMPUS-WIRE 席起草但从未实施的生产收编规约），只改 tests/test_campus_digest.py，零生产代码改动，不实施 U17。
- 开场实跑：**11 failed / 18 passed**（`pytest tests/test_campus_digest.py --basetemp=$TEMP/campusxfail-tmp -p no:cacheprovider -q`），与简报预期一致，无差异。
- 红线确认：不碰 domains/assistant/campus/**、root `__init__.py`、production 任何文件；不删不改 18 绿例；strict=False。

### XFAIL 挂账完成（2026-09-20）
- **11 例逐例标注**（`@pytest.mark.xfail(reason="U17-CAMPUS-WIRE 生产收编未实施（audit-20260920-unify-U17-campus-wire.md §4 两裁定点待用户过目），测试先行挂账", strict=False)`，11 处 reason 逐字节一致——`sort -u` 实证唯一形态；`import pytest` 原已在 L21 无需补）：
  1. `test_handler_dispatches_through_central_pipeline`（原 L534，ImportError 缺 `build_campus_forward_capability`）
  2. `test_handler_no_forward_outside_source_gate`（原 L549，同上缺 builder）
  3. `test_handler_source_gate_rejects_foreign_group`（原 L574，同上）
  4. `test_handler_duplicate_message_id_forwards_once`（原 L584，同上）
  5. `test_handler_isolated_and_send_api_free`（原 L595，结构锁断言「旁路已收编」而 root handler `.submit(` 仍在岗=被测改后态未实施）
  6. `test_forward_message_expresses_owner_private_target`（原 L632，ImportError 缺 `build_campus_forward_message`）
  7. `test_complete_enqueues_owner_private_request_end_to_end`（原 L703，缺两 builder）
  8. `test_no_outbound_request_ever_targets_school_group`（原 L742，缺两 builder）
  9. `test_quiet_hours_and_rate_limit_do_not_swallow_campus_forward`（原 L793，缺两 builder）
  10. `test_central_claim_adds_second_idempotency_layer`（原 L826，缺两 builder）
  11. `test_campus_forward_registered_for_feature_gate`（原 L860，builder 在断言之首 ImportError；注册登记半边已由前席补齐）
  行号为标注前坐标（各 def 上方插 1 行装饰器后整体 +1 递增）。
- **18 绿例零触碰**：纯函数/来源门/录制幂等/prune/config 四组 + `test_forward_text_matches_legacy_bypass_verbatim` + `test_campus_capability_id_literals_all_registered` + `test_outbound_registry_campus_coordinate_is_live`，断言与夹具一个字节未动（标注仅落在 11 个失败 def 上方，diff 可证）。
- **实跑定版**：
  - 全文件：**18 passed, 11 xfailed, 0 failed**（`pytest tests/test_campus_digest.py --basetemp=$TEMP/campusxfail-tmp -p no:cacheprovider -q`，进度行 `................xxxxxxxxxxx..`）。
  - 合跑棘轮族：`tests/test_campus_digest.py + tests/test_outbound_v21.py` → **77 passed, 11 xfailed, 0 failed**，零回归。
  - ruff `tests/test_campus_digest.py`：**All checks passed**。
- **前后对照（本文件 14F→0F 全路径）**：CAMPUS-FIX-9 席修复 3 绿（纯函数恢复/registry 坐标+note 刷新/注册面补登）+ 本席诚实挂账 11 xfail = 29 例全绿态（18 passed + 11 xfailed）。挂账定性如实：11 例编码的是 U17-CAMPUS-WIRE 席起草但从未实施的生产收编规约（audit §2/§3 空、三 builder 全树零存在、root `__init__.py:5044` 旁路在岗、audit §4 两裁定点自标「必须用户过目」），非已实现功能的遮羞布。
- **实施 U17 时的摘牌指引**：全文件搜 `U17-CAMPUS-WIRE` 即可全数定位 11 处装饰器（reason 内含该标记），逐一删除装饰器→实现 builder+handler 管线分发→全文件应回到 29 passed；strict=False 保证实施后若暂未摘牌的 xfail 变 XPASS 不炸套件，摘牌由实施席完成（属用户裁决后的独立任务）。
- 变更面：仅 `tests/test_campus_digest.py`（+11 行装饰器）与本 log；零生产代码改动；未 commit（两文件本就未跟踪，提交裁决权在用户）。

**XFAIL-SEAT DONE** — 2026-09-20，CAMPUS-XFAIL。
