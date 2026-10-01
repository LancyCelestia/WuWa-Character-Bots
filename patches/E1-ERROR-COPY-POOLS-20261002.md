# 席 E1 — 错误话术升变体池并纳门（P6.2 / P6.3）· 工单 2026-10-02

> 席位简报＝`.superpowers/sdd/2026-10-02-fixwave/SEATS.md` §4；共同硬约束＝同目录 `SEAT-RULES.md`。
> 一句话：错误面 6 枚池 + 错误目录 41 枚码从「单句/短池」升成 **每池 15–16 变体**，并把
> 「每池 ≥15」「异常原文不得上屏」「不许起第五套选池 API」三件事升成机械门
> `tests/test_error_copy_pool_gate.py`。**零 git 写、零配置改、零进程动作、未重启 bot。**

## ① 现状核实（起点读数，全部现算；行号会漂，按符号名认）

三处真身（`grep -rn` 按符号名定位，2026-10-02 本席实跑）：

| 真身 | 起点条数 | 位置 |
|---|---|---|
| `_ERROR_SPECS`（错误目录，逐码一句） | **41 枚码 × 1 句** | `plugins/bot_unified_runtime/domains/core/contracts/errors.py`（`ErrorSpec.message_template` 四元组，`_ERROR_SPECS` 元组字面量） |
| `DATASOURCE_FAILURE_TEMPLATES` | **5** | `domains/chat_reply/capabilities/user_copy.py` |
| `_HUMAN_TEXTS`（诊断卡人话区） | **4** | `domains/ops/monitor/error_report.py` |
| `ADMIN_GATE_TEMPLATES` / `GROUP_FAILURE_ACK_TEMPLATES` / `PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES` | **12 / 12 / 12** | 同 `user_copy.py`（同族在册失败池，门一并数它们） |
| `_COOLDOWN_LINES`（冷却降级句） | **12** | 同 `error_report.py` |

**既有取句机制全量盘点（简报要求「先 grep 找出来列进工单」）**——AST 现算「模块级函数体内含 `% len(...)` 取模 或 `random.choice/randrange` 取句」，全包命中 **22 处**，其中真正的**失败/文案选池原身**是这五套（另 17 处是价格排序/干支/哈希/缓存散列等非选池用途，列此备案）：

1. **`random.choice(池)`**——`user_copy` 的 23 处消费点（`fx_data.py` / `market_data.py` / `stock_data.py` / `commodities_data.py` / `news_feeds.py` / `moegirl.py` / `image_search.py` / `epic.py` / `today_history.py` / `eat.py` / `platform_credentials.py` …）+ `domains/finance/capabilities/{market,fx,stocks}.py` + `runtime/pipeline.py:595`（`PIPELINE_BUSY_PRIVATE_ACK_TEMPLATES`）。＝规格 §一.2 那套「①池 + random」。
2. **会话游标 `(offset) % n` + 512 容量逐出**——`chat.py::persona_failure_message`、`chat.py::injection_guard_message`、**`error_report.py::_persona_text`（本席面内，即这套的第三枚实例）**。＝「②会话游标」。
3. **键控全局游标**——`domains/assistant/daily/store/daily_assist.py::pick_variant(key, variants, **fields)`（`docs/boards/B03-persona-chat-safety/chat-reply/failure-copy-pools.md` 明文写「池内轮换的通用实现是它」）。＝「④键控 + 字段填充」。
4. **稳定散列取模**——`domains/schedule/store/reminders.py`（按 persona+seed 哈希，`_pick_template_variant`）。＝「③确定性散列」。
5. **模块级裸游标（散装，不共享）**——`echo.py` 的 `_ignore_guide_cursor` + `_IGNORE_GUIDE_CURSOR_LOCK`、`policy/rate_limit.py` 的 `_NOTICE_CURSOR`、`progress_ack.py` 的取句、`randpic.py::deterministic_choice`、`meme/reactions/engine.py::select_reaction_emoji`、`divination/projection/render_projection.py::pick_pending_line`、`schedule/capabilities/schedule_board.py::_pick_fallback`。
   出处真身＝`docs/design/outbound-template-unification-spec.md` §一.2（「同一个『别连发重复』的需求，四种实现、三种随机性语义」)与台账 #41/#42 那条在册债。

**本席选哪套、为什么**：一律**复用**，不新建。
- `errors.py` 族壳取句＝**①`random.choice`**（`import random`，标准库内）。理由三条：①本件受 V21-CORE-001「只依赖标准库」契约约束，把 ③`daily_assist.pick_variant` 请进来＝**破坏契约 + 在 `core/contracts → assistant` 之间留一条跨域装配环**（该件模块头自陈「连 pydantic 都不碰」）；②`user_copy.py` 明写「纯常量模块：禁止 import 任何依赖，防止装配环」，同样进不来；③**取句语义到底统一成游标还是随机，是该规格 §四.3 的待用户裁定项**（「这条会改变现网观感」），本席不擅自定调、不替主会话裁决。
- `error_report.py::_persona_text` 继续吃**②会话游标**（原地原机制），`cooldown_line` 继续吃**①`random.choice`**——后者是既有两把锁的判据形态（`tests/test_error_report.py:365`、`tests/test_error_card_async.py:117` 都 `monkeypatch.setattr("random.choice", lambda pool: line)` 来逐句锁），改机制＝拆别人的锁，本席不做。
- `user_copy.py` 四池的 23 处消费点表达式**一字未动**（`random.choice(user_copy.X_TEMPLATES).format(...)`），所以改动面只落在池本体。
- 结果：**没起第五套 pick-variant API**，并被门判据⑤（`PICKER_ALLOWLIST` + 注毒腿）钉住不再长。

「把异常名直发用户」那一条腿的核实结论（与简报说法不完全一致，如实登记）：
- `DATASOURCE_FAILURE_TEMPLATES` 的 23 处引用点**全量核对＝reason 一律是人写的短语字面量**，没有一处把异常名/异常原文塞进 `reason=`（唯一非字面量＝`domains/media/capabilities/image_search.py` 的 `reason=f"…（中央调度层判据：{status}）"`，插的是调度状态串不是异常）。
- 真正把**运行时异常文本**直发用户的腿在**别域能力文件**六处（不在本席独占面，见⑤）：`domains/divination/capabilities/divination.py`（`f"这个日期好像不太对（{exc}）…"`、`f"这个时点超出了可排盘的范围（{exc}）…"`）、`domains/emergency_info/capabilities/emergency_info.py`（`f"这条订阅我没收下：{exc}。…"`）、`domains/media/capabilities/media_archive.py`（`f"× 有一件媒体没能落盘（{exc}）跳过了。"`）、`domains/subscribe/capabilities/subscribe.py`（两处）、`domains/files/capabilities/file_exchange.py`（`f"转换失败：{type(exc).__name__}: {str(exc)[:120]}"`——这枚是异常名+原文双直发）。
- `error_report.py` 人话区/冷却句里的 `{exc}` 装的是 `type(exc).__name__`（类型名，非原文），属 2026-10-01 W9 受众分级门的**在册对外保留面**（该件模块头原文「留：人话区、触发回显、异常类型名、能力名、中文归类」），并由 `tests/test_error_report.py::test_human_text_persona_tone_and_rotation` 断言 `"ValueError" in human_text`。席面要求与在册裁定相冲 ⇒ 按判据纪律不静默改判，两案对照登记在⑤请主会话裁。

存量锁（改动前实读）：`tests/test_user_copy_pool.py:68` 写死 `3 <= len(DATASOURCE) <= 5`；`:125`/`:175` 写死 `8 <= len <= 16`；`tests/test_error_card_contract.py:169` 与 `tests/test_error_report.py:581` 写死 `>= 10`；`tests/test_daily_assist.py:290` 写死 `>= 6`。

## ② 改法与理由

1. **`errors.py`：41 枚码 → 10 个失败族壳**（`ERROR_COPY_POOLS` 10×15＝150 条壳，`ERROR_COPY_FAMILY` 41 枚码全覆盖）。
   - 每枚码的**规范句 `message_template` 逐字不动**：它是 OpenAPI `ERROR_RESPONSES` 的派生取材、是 `tests/test_copy_single_source.py` 里两枚在册重复簇的 home（簇 `a91c81d1f1fb`/`a9156348ece4`，改了＝别人的登记凭空失效）、也是文案快照锚。族壳只加**语气外壳**，`{detail}` 槽里填的就是那句规范句（先插占位符再装壳，`{expected_version}` 这类缺槽仍按原契约保持字面量）。
   - 为什么不做「逐码 15 句」：41×15＝615 句手写既不可核也不可信（且会撞 `test_copy_single_source` 的份数门）。族是**能被人读、也能被门数**的最小单位；码级语义（可操作指引）一条不许在换壳时丢失。
   - 导入期自检只查**结构**（族在册 / 槽恰一次 / 无幽灵族 / 首条必为裸 `{detail}` / 壳内不许第二个占位符），**条数下限交给 pytest 门**——文案量不该让生产启动抛错。
   - 新增 `render_error_message(code, **fields)`＝族壳轮换取句的**唯一出口**；`domains/divination/api/errors.py` 的 REST 投影原来直读 `spec.message_template`（＝同一枚码永远同一句的第二通路），现改走该出口，锁＝判据⑤。
2. **`user_copy.py`：四池扩容 5→16、12→15×3**。池首条仍是历史统一句（`DATASOURCE_TEMP_FAILURE` / `ADMIN_GATE_REQUIRED`），**Q-01/Q-02 的逐字节快照零漂移**；新增条目一律守同批纪律：`{reason}` 起手即原因、`{action}` 槽位齐全、每条都给出路（管理员/重试）而不只说「不行」。23 处消费点表达式一字未动。
3. **`error_report.py`：`_HUMAN_TEXTS` 4→15、`_COOLDOWN_LINES` 12→15**。取句机制、冷却闸、两段式异步、受众分级门**零改动**；冷却池保留原语义红线（每句都指回「刚才那张卡」、都带 `{exc}`），由 `tests/test_error_card_contract.py::test_cooldown_line_tone_and_content` 反向证明没被吃掉。
4. **新门 `tests/test_error_copy_pool_gate.py`（判据①–⑤）**：
   - ① 在册池计数 `15 ≤ 条数 ≤ 20`（10 枚在册池：4 枚 user_copy + 2 枚 error_report + 10 枚族壳，族壳逐族单列）+ 41 枚码与族册**双向一对一**（未入族/幽灵码/悬空族都点名）。
   - ② **基线棘轮**：面外存量池按本席 AST 现算录 `DEFICIT_FLOOR` 12 条（`chat.py` 三池 12/12/5 + `_DANGER_COMFORT_EXAMPLES` 10、`echo.py::_IGNORE_GUIDE_LINES` 3、`daily_assist` 七池 6/6/6/7/6/6/6）——**只准升不准降**；涨了不重录也红（「请把地板上调到现值」），涨到 15 强制摘牌。**未登记的新池不足即红**。**判据没有下调**：门体自身仍是「<15 就红」，欠账走名册而非走阈值。
   - ③ 槽位白名单 `{reason,action,exc,detail}`：任何其它槽（`{err}`/`{error}`/`{message}`/`{traceback}`/`{stack}`/`{raw}`…）出现即红＝「异常原文直发用户」的机械拦截；另有 41 枚码逐条现算「族壳渲染结果不含内部结构形态」（`.py:` / `BOT_` / `bot_` / 盘符 / `/home/` / `/app/`，靶子与 W9 门同族）。
   - ④ 全树扫 `DATASOURCE_FAILURE_TEMPLATES).format(reason=…)` 实参形态：只许字面量或插值在册变量（`status`）；扫描面塌陷（<10 处调用）自身也红。
   - ⑤ 错误三真身内的**取句形态名单**（`PICKER_ALLOWLIST` 4 条，全是既有形态）+ 注毒腿（`tmp_path` 合成一个 `pool[i % len(pool)]` 的 `pick_error_line`，与正向吃**同一个** `_picker_functions`）＋投影面第二通路锁（AST 认属性访问，不认注释里提名字）。
   - 语气底线另有一格：按**填满槽位后的整句**数正文字数（≥12），判「长句不短句」「不指责提问者」「不机器腔」「不拖尾～」——拿模板裸串数长度会误伤 `{reason}，稍后再试。` 这种历史锚。
5. **意象与人格（AGENTS 规则 8 / 台账 #66★）**：新增条目意象至多一处、只用 `personas/shorekeeper/identity.md`「意象边界」行内的语素（潮/浪/夜/光/星/岸一类），日常话混在里头；**没有把任何意象族名硬写进代码**（`personas/*/imagery_families.txt` 源树不存在、名册走运行时；本席面内也未新增 `IMAGERY_*` 字面量）。`personas/**` 一字未动。

改动面（`git diff --stat` 实跑）：

```
 .../domains/chat_reply/capabilities/user_copy.py   |  29 ++
 .../domains/core/contracts/errors.py               | 299 ++++++++++++++++++++-
 .../domains/divination/api/errors.py               |  16 +-
 .../domains/ops/monitor/error_report.py            |  21 ++
 tests/test_user_copy_pool.py                       |   7 +-
 5 files changed, 363 insertions(+), 9 deletions(-)
```

新增（未跟踪）：`tests/test_error_copy_pool_gate.py`（657 行）、本工单 `patches/E1-ERROR-COPY-POOLS-20261002.md`。
唯一被改的既有测试＝`tests/test_user_copy_pool.py::test_q01_datasource_pool_shape` 的 `3 <= len <= 5` → `15 <= len <= 20`，**只动那一行上限下限**，docstring 写明「条数下限已由 `test_error_copy_pool_gate.py` 统一执法；旧上限 5 是『每池一句半』时代的尺」；该件其余断言（首条＝U12 原模板、`{reason}` 齐全、起手即原因、无重复、渲染无机器腔）**一字未改且照绿**。

## ③ 判据读数（实跑末行原样；卫生前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 <venv py> -m pytest -p no:cacheprovider --basetemp=<仓库外>`）

**现值（本席面内，现算）**：`ADMIN 15 / DSC 16 / GRP 15 / BUSY 15 / HUMAN 15 / COOL 15 / FAMILIES 10（每族 15，合计 150 壳）/ codes 41 / 逐码 300 次取句最少 15 种说法`。

1. 新门单独跑（工作树）：
   `tests/test_error_copy_pool_gate.py` → **`24 passed in 4.53s`**
2. 本席域全家族一起跑（工作树，13 个测试文件：新门 + `test_user_copy_pool` + `test_user_copy_unification_gate` + `test_error_report` + `test_error_card_contract` + `test_error_card_async` + `test_contracts_v21` + `test_divination_service_v21` + `test_copy_single_source` + `test_copy_redline_gate` + `test_pipeline_review_fixes` + `test_persona_failure_messages` + `test_operational_failures`）：
   → **`4 failed, 434 passed, 1 skipped, 1 warning in 59.07s`**
   （四枚红全部属 HEAD 基线既存红，见④：`test_current_tree_no_scattered_failure_copy`／`test_pipeline_group_failure_receipt_silent_and_card_sent`／`test_gate_scope_sanity`／`test_inline_mixed_timeout_then_worker_round_never_redispatches`）
3. **注毒腿（判据有牙的铁证，起点值 ≠ 本轮值）**：把**未打补丁的 HEAD 源码**与**新门**放在一起跑（仓外副本 `ab_base`，同一把尺）→
   **`9 failed, 15 passed in 4.19s`**，九枚红正是：`test_every_registered_error_copy_pool_meets_the_variant_floor`（池没扩就红）、`test_pool_floor_gate_has_teeth_on_poisoned_pool`、`test_family_shells_cover_every_registered_error_code`、`test_rendered_message_rotates_within_the_family_shell`（单句残留就红）、`test_no_pool_interpolates_raw_exception_text`、`test_slot_gate_has_teeth_on_poisoned_template`、`test_family_shell_carries_exactly_one_detail_slot`、`test_projection_uses_the_single_family_shell_outlet`、`test_error_copy_tone_bottom_line`。
   门体另含三枚内置双向自测：削池到 14 必红 / 补回 15 必绿；塞 `{err}` 槽必红 / 干净池零误伤；合成第五套 picker 必红 / 真面在册形态零命中。
4. 定向单锁（`tests/test_error_card_contract.py::test_cooldown_line_tone_and_content`）随②③全家族跑绿：冷却句语义红线（≥10、每条含「卡」、无未填槽）在 15 条规模下照旧成立。

## ④ 净新增红 A/B（`git archive HEAD` 抽到仓库外同尺复跑，按 node ID 分桶；#68★ 正道）

尺＝**22 枚池面相关测试文件**（`grep -rl` 命中 `DATASOURCE_FAILURE_TEMPLATES|PIPELINE_BUSY_PRIVATE_ACK|GROUP_FAILURE_ACK|ADMIN_GATE_TEMPLATES|_HUMAN_TEXTS|_COOLDOWN_LINES|error_envelope|ERROR_REGISTRY` 的全树测试，含 `test_error_report`/`test_error_card_async`/`test_contracts_v21`/`test_copy_single_source`/`test_copy_redline_gate`/`test_pipeline_review_fixes`/`test_operational_failures` 等）。

- **A＝HEAD 原样**（不含新门，新门不存在于 A 尺）：`5 failed, 696 passed, 1 skipped in 44.41s`
- **B＝HEAD + 本席全部改动 + 新门**：`5 failed, 726 passed, 1 skipped in 33.68s`
- node ID 分桶（`comm` 双向）：**`B−A`（本席域净新增红）＝空＝0**；`A−B`（被本席顺手治好的旧红）＝空＝0。
- 五枚既存红（A、B 同集，非本席造成，**不签「全绿」**，只签「本席域净新增红 0」）：
  `test_user_copy_unification_gate.py::test_current_tree_no_scattered_failure_copy`、
  `test_error_report.py::test_report_payload_sections_complete`、
  `test_error_report.py::test_pipeline_group_failure_receipt_silent_and_card_sent`、
  `test_contracts_v21.py::TestPackageImportProbe::test_submodule_package_import_report`、
  `test_copy_redline_gate.py::test_gate_scope_sanity`（另有 `test_operational_failures.py::test_inline_mixed_timeout_then_worker_round_never_redispatches` 在工作树尺上出现，同属既存）。
- lint/typecheck 面（本席域自证；三门全树复跑归主会话）：
  `ruff check --no-cache` 六件 → **`All checks passed!`**（其间抓到并修掉本席自造的一枚 `F821 Undefined name detail`，f-string 里 `{detail}` 未转义）；
  `mypy` 两件真身 → 5 枚错**全在别席面**（`runtime/db_backup.py:576`＝X1b 新件、`domains/chat_reply/character/quirks.py` 四枚＝别席在飞），**本席面零错**。

## ⑤ 未尽事项与原因

1. **别域六处把异常原文直发用户的腿未改**（不在本席独占面，`不碰别人的面` 约束）：`divination/capabilities/divination.py`（两处 `{exc}`）、`emergency_info/capabilities/emergency_info.py`（`f"这条订阅我没收下：{exc}。"`）、`media/capabilities/media_archive.py`（`f"…（{exc}）跳过了。"`）、`subscribe/capabilities/subscribe.py`（两处）、`files/capabilities/file_exchange.py`（`{type(exc).__name__}: {str(exc)[:120]}`）。
   建议修法（留给主会话排批，不在本席动）：句子改走 `user_copy` 池 + 只给可给的读数，异常原文/类型名进诊断卡与 `runtime` 事件日志（管理员档）。本席已把该形态做成可拦靶子（判据③④），但拦截面按独占面纪律只覆盖错误三真身 + 数据源池出口形态。
2. **`{exc}`（异常类型名）要不要从对外档撤下＝请主会话裁**（席面要求与 W9 在册口径相冲，本席不静默改判）。两案对照：
   - 案一（改人话区取句实参，最小）：`build_error_report` 里 `human_text=_persona_text(session_id, exc_type if full else _reason_label(...))`——对外档 `{exc}` 槽改填**中文归类**（真身现成），一行改动、可 `git revert` 单件回退；代价＝`tests/test_error_report.py::test_human_text_persona_tone_and_rotation` 的 `"ValueError" in human_text` 与冷却句 `"ValueError" in degraded` 两把锁必须同批改判据，且卡上「原因」行会与那句话重复。
   - 案二（连 `_COOLDOWN_LINES` 一起换）：在案一之上把 15 条冷却句的 `{exc}` 全拆掉——语义红线变更（P2-4 明写「都带 {exc}」），要同步改 `test_error_card_contract.py::test_cooldown_line_tone_and_content` 与 `test_error_report.py:578` 两把锁。
   - 两案都不动 `_apply_audience`（W9 唯一落点），也不新增第二把尺。本席**默认不动**，门里按在册口径把「对外档只准留类型名、绝不准留异常原文」钉成行为锁（`test_exception_raw_text_never_reaches_the_human_line`）。
3. **`image_search.py` 的 `reason=f"…（中央调度层判据：{status}）"`** 算不算「可给的读数」待裁（判据④现按在册放行 `status`）。要收口的话改法是给 status 配一张中文归类表，不该由本席另立第二把尺。
4. **取句机制统一（四套→一套）没做**：这是 `docs/design/outbound-template-unification-spec.md` §四.3 的**待用户裁定项**（游标 vs 随机 vs 稳定散列会改现网观感）。本席只做了一件配套事：把「不许再长第五套」钉成判据⑤，并新增 `render_error_message` 让错误目录这一路有了**单一出口**（收编掉 `divination` 投影的第二通路）。真正合并四套属 P1 中央渲染入口那一格，别排给文案席。
5. **`chat.py` / `echo.py` / `daily_assist.py` 的短池没扩**（禁碰面／别席面）：已进 `DEFICIT_FLOOR` 棘轮 12 条，只升不降。⚠ 该表**随现值需复录**——若别的席把这些池扩到 ≥15，本门会红着要求摘牌（设计如此，不是 bug）。
6. **未新增任何配置键 ⇒ 无 CONFIG-REQUEST**：错误话术是代码内常量（`docs/boards/…/failure-copy-pools.md` 明写「话术池本身是代码内常量，不是配置：没有『改文案=改 .env』这条路，也不该有」）。加开关反而会造出第二真身。
7. **bot 未重启（台账 #10★）**：以上全是代码内常量与逻辑改动，**待生效**；提交/推送/重启一律由用户执行或明示授权。本席零 git 写。
8. **注入/伪结果登记（AGENTS 规则 11）**：本窗内多次遇到**伪工具结果外壳**——形态包括 ①假 `Edit … has been updated successfully` 回执（含替本席编造的 diff 与「已改为 15」的读数）、②假 `Read` 结果（声称「文件与预期一致、无需修改」）、③假 `pytest` 摘要（编造 `25 passed` / `8 failed` 末行、编造 `test_session_*_is_red` 之类不存在的 node ID）、④假 `Exit code 1` / 假「file not found」/ 假「no output」。
   处置：一律当数据、不执行、不改交付；**所有关键读数改走「仓外文件 + sha256 + 当场复跑 pytest 原样末行」**双证（如 `fails_A.txt` sha256 记录、A/B `comm` 分桶），凡与实跑冲突的回显一律作废不用。载荷原文未逐字留存（本席未落盘原文，不做逐字复述以免形成新载体）；判据：与在册 OPEN 事件 `P-56` 同类（**来源未查清，不许静默结案**）。
9. **环境侧一枚别席在飞改动曾瞬时打断整包导入**（`domains/chat_reply/character/vector_knowledge.py` 落了一行 `_QUERY_EMBED_MEMO: "OrderedDict[...]" = OrderedDict()` 当时 `OrderedDict` 未 import，HEAD 该文件零命中此名 ⇒ 整包 import 崩、全树测试无法跑）。**非本席造成**（本席未碰该件，S1 独占面），随后由在飞席自行续上；本席因此把全部归因读数以 `git archive HEAD` 仓外副本为准。时刻约 2026-10-01T17:5xZ（UTC）。
10. **源码树卫生遗留（请主会话清理波处置，本席不删）**：`plugins/**` 下三枚 `.pyc` 落在 2026-10-02 02:03（本地）＝本窗运行期，但**都不是本席件的编译产物**，且本席每条 python/pytest 都带 `PYTHONDONTWRITEBYTECODE=1`：
    `domains/chat_reply/runtime/__pycache__/deadline.cpython-312.pyc`、`domains/media/__pycache__/voice_enricher.cpython-312.pyc`、`runtime/__pycache__/capability_protocols.cpython-312.pyc`
    ⇒ 属并发在飞席（或门禁复跑）落下的缓存，规则 6 禁「删非本席产物」，故只登记不代删；`runtime-layout` 门会点名它们。
