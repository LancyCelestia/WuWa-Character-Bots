# LOCK-FIX 席报告 —— 锁补强（F-1…F-4）

Status: DONE_WITH_CONCERNS（F-1/F-2/F-3/F-4 全部 RED→GREEN→注毒回退红→还原绿四段齐；
Concerns=§0 那条开工即有的常驻红待主会话与用户裁 + §未做与原因 1/2/3/6 四条）

- 开工时间（本地）：见文件 mtime
- 上游证据：`reports/LOCKAUDIT-report.md`（324 行，59 锁判定 A39/B15/C1/D4，78 次注毒）
- 独占可写面：
  - `plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`
  - `plugins/bot_unified_runtime/domains/emergency_info/service/dedupe.py`
  - `tests/test_outbound_gate.py`
  - `reports/LOCKFIX-report.md`（本文件）
- 禁写面已登记：根 `__init__.py`、`tests/test_capability_registry.py`、`tests/test_emergency_info_{core,sources}.py`、
  `domains/chat_reply/**`、`docs/**`、`AGENTS.md`、`config.py`、`base_router.py`、`echo.py`、`.env*`、`tests/fixtures/**`
- 基线（不得倒退）：闸 42 passed / core 101P+2x / sources 58P+1x / 合跑 218 passed + 3 xfailed

## 0. 开工基线（实跑，与任务书不符处已如实登记）

```
tests/test_outbound_gate.py            41 passed, 1 FAILED   ← 任务书称 42 passed
tests/test_emergency_info_core.py     101 passed, 2 xfailed  ← 相符
tests/test_emergency_info_sources.py   58 passed, 1 xfailed  ← 相符
三件合跑                            200 passed, 3 xfailed, 1 FAILED  ← 任务书称 218P+3x
```

**开工即有的那条红不是本席造成的，也不是实现退化**：
`test_existing_families_still_submit_directly` 断言根 `__init__.py` 直调 `*queue*.submit` ≥5，
实跑 `assert 4 >= 5`（命中行 2954/3065/3223/3372，**校园那一处已消失**，原位置注释见
`__init__.py:5059` 附近「统一入队），删除裸 send_queue.submit 旁路」）。这正是 LOCK-AUDIT
§撞车预警 PROBE-1 预告的那一枪（实数恰=5、余量 0，在飞收编席落地当天必红）。
根 `__init__.py` 与本条锁口径均为本席禁写面 ⇒ **不动、不解释性放宽、只登记**，
处置权在主会话与用户。本席全部「不得倒退」以此为基准：闸面 41P、合跑 200P+1F 已知红。

任务书「合跑 218」与其自带分件数（42+101+58=201）自相矛盾，按分件实跑记账。

## 0.1 字节快照纪律（本席踩过一次的真坑）

- **`--basetemp` 会在每次 pytest 开头整目录删除**。本席最初把 harness 与快照放在
  `$TEMP/lock-fix/`，而 basetemp 也用它 ⇒ 第一次注毒跑完后 harness 与快照**被 pytest 抹掉**，
  中毒态残留了一次（约 1 分钟内自查发现）。此后：harness/快照一律放
  `$TEMP/lock-fix-seat/`，basetemp 改用 `$TEMP/lock-fix-tt/`。
- 那次还原未走 cp，走的是**反向字节替换**（`POISONED-M1` 注释换回原两行），复核
  `sha=ea5beea1f5af size=7606 crlf=157 POISONED 残余=0` 与注毒前快照逐字节相同。
- **行尾符事故本席也踩过一次**：`dedupe.py` as-found 是 CRLF（134/134），本席首轮编辑后
  变成纯 LF（157 行 / 0 CR / 7449 字节）——即任务书警告的「文本通道把 CRLF 刷成 LF」。
  已用二进制通道整表换回 `\r\n`（`LF=157 CR=157 CRLF=157 size=7606`），此后每次编辑后复查。
  三件真身末态行尾符见文末签核段。
- `dedupe.py` 是**未入 HEAD 的新文件**（`git cat-file -e HEAD:...` 报 not in HEAD）⇒
  该件无 HEAD 基线可自证还原，本席的还原证据只有 `$TEMP/lock-fix-seat/fixed/` 字节快照。

## F-1 dedupe 键命名空间与段字符集（GAP-1）

### 定位修正（先说与任务书不一致的一处，因为它决定修法）

任务书说「闸侧谓词不查段字符集也不锁命名空间」。实跑证据：**前缀等值校验闸侧一直在**
（`outbound_gate.py` 原 `:270` 那行 `segments[0] != DEDUPE_NAMESPACE`），缺的是
①**锁**（G10 删掉它 59 全绿＝零覆盖，不是零实现）②**逐段字符集与日期段形态**（真缺实现）。
所以 F-1 的「补前缀」这一半落成**补锁**（下面 M1 就是那条锁的牙），「补段字符集」落成
补实现。二者都不需要新造规则——紧急域谓词 `is_emergency_dedupe_key` 早就四条齐全。

### 方向裁定（这一步被一枚禁写锁钉死，不是本席口味）

同源化两个方向本席都试了：
- **闸侧实现、域侧委托**（`dedupe.py` import 闸）→ 被禁写锁当场拦下：
  `test_emergency_info_core.py::test_kernel_never_imports_network_or_llm` 的 forbidden 元组
  含 `"transport"` 令牌，扫 `service/*.py` 的 AST import ⇒ 实跑红
  `offenders == ['dedupe.py:plugins...transport.sender.outbound_gate']`。该文件禁写。
- **域侧实现、闸侧委托**（本席采用）→ 与 `dedupe.py:9-10` 原注释的宣称**一致**（F-4 的
  账正好对上），也与 `test_emergency_info_core.py:459` 的「中央闸可直接 import 本判定口」
  一致；且无 import 环风险（域内核永不 import 闸）。

### RED（实现未改前，缺校验导致）

```
8 failed, 5 passed
test_segment_charset_and_date_key_shape_are_enforced[...7 例全红：has space / 段前空白 /
  尾随空白 / 中文段 / private:3865067623 伪装五段 / 2026-9-14 / 20260914]
test_dedupe_predicates_share_one_implementation
  AssertionError: 紧急域谓词不再引用闸侧唯一键规范实现（实有 import：['__future__','datetime',
  '...emergency_info.contracts']）
```
4 条命名空间用例与 1 条现役合法键用例首跑即绿 ⇒ 记为「实现已在、锁缺失」那一半
（其判别力由 M1 注毒证明，见下）。

### GREEN（改闸侧委托 + 域侧严格化后）

```
tests/test_outbound_gate.py + core + sources 合跑：214 passed, 3 xfailed, 1 failed
（唯一失败=§0 那条开工即有的 `test_existing_families_still_submit_directly`）
净增 14 条：200 → 214
```

### 变异回退红（4 次，全部 `restore=OK` 磁盘字节复核）

| 注毒 | 落点 | 红况（不含常驻那条 `test_existing_families...`） |
|---|---|---|
| M1 删命名空间等值校验（=G10 同形） | dedupe.py | 本席 5 红（4 命名空间用例 + 改过的 `digest_push` 四段例）+ **禁写件 core 侧 2 红**（`test_dedupe_key_shape_check[emergency…]`、`[daily_assist…]`）⇒ 该规则两侧都有牙了 |
| M2 删逐段字符集循环 | dedupe.py | 5 红：4 条字符集用例 + `test_malformed[emg:qq::target]`（空段现由字符集规则担当，见下「一处口径变化」） |
| M3 恢复域侧整串预 `strip()` 宽松态 | dedupe.py | 2 红：`[emg:qq:item-1:g-1 ]` + 新用例 `test_whitespace_padded_dedupe_key_is_rejected` |
| M4 闸侧重新分叉（回到只查段数/空段的旧实现） | outbound_gate.py | **13 红**，含结构锁 `test_dedupe_predicates_share_one_implementation` ⇒ 分叉即红 |

还原核验样例：
```
restore dedupe: disk_sha=ea5beea1f5af snapshot_sha=ea5beea1f5af residue=0 RESTORE_OK
restore gate:   disk_sha=d5d4a7948f39 snapshot_sha=d5d4a7948f39 residue=0 RESTORE_OK
```

### 一处口径变化（诚实登记，非静默）

原闸侧有一条独立的「任一段 `strip()` 后为空 ⇒ False」检查；委托后不再有独立空段分支，
**空段由段字符集（`{1,120}` 至少一字符）拒绝**——M2 的 `[emg:qq::target]` 转红正是这个
事实的证明。行为对外等价，规则少一条。

### 落点与新增锁清单

- `plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`：
  删自带宽松谓词与 `import re`；`DEDUPE_NAMESPACE = EMERGENCY_DEDUPE_PREFIX`（别名，不再自带
  字面量）；`dedupe_key_shape_ok` 变委托口（docstring 写明唯一实现处 + GAP-1 后果）；
  模块头注「不另建去重账」条补「键规范唯一实现=域侧」；`__all__` 未扩张。
- `plugins/bot_unified_runtime/domains/emergency_info/service/dedupe.py`：正则与前缀字面量
  留在本处（唯一出处）；`is_emergency_dedupe_key` 去掉整串预 `strip()`（严格化，docstring
  写明理由与替代路径）；build 的「归一一次」段把「过闸侧宽松校验」改为过去时（该宽松态已没了）。
- `tests/test_outbound_gate.py` 新增：`_NAMESPACE_ONLY_KEYS` 4 例
  + `test_namespace_only_violations_are_skipped` /
  `test_segment_charset_and_date_key_shape_are_enforced` 7 例 /
  `test_canonical_emg_keys_still_pass_after_charset_tightening` /
  `test_dedupe_predicates_share_one_implementation`（AST 结构锁）/
  `test_whitespace_padded_dedupe_key_is_rejected`；并把名实不符的
  `digest_push:g-1:2026-09-14`（三段，实为段数拦下）改成四段真形
  `digest_push:g-1:u-2:2026-09-14`。



## F-2 生产 import 白名单：空集恒真 + 收紧只做一半（GAP-2）

### 定位修正 ②：白名单其实还有第三个问题（比任务书说的更糟）

原实现 `allowed_prefixes = ((PLUGIN_ROOT/"domains"/"transport",), (…, "emergency_info",))` 是
**嵌套元组**，判定却写 `any(str(path).startswith(str(root)) for root in allowed_prefixes)`
⇒ `str(root)` 得到的是 `"(WindowsPath('C:/…/domains/transport'),)"` 这种 repr 串。
本席实测（摊平前的对照跑）：`transport_legacy/old.py`、`transporter/evil.py`、
`emergency_other/x.py`、`emergencyinfo/x.py` 四个兄弟样本 **inside 全 = False**。
也就是说：这条锁今天不是「松」，而是**谁都拦在外面**——一旦接线落地，紧急域自己的合法
import 会被判越界（假红），而今天它只是叠在空集上没人发现。LOCK-AUDIT PROBE-2 只看到了
`startswith` 的一半（它是用摊平后的根去探的），没看到这半个 repr 缺陷。
修法：摊平成 `tuple[Path, …]` + 目录段等值匹配，两个缺陷一次收掉。

### 形制纪律（改这里会撞禁写锁，已实测）

`tests/test_emergency_info_core.py::_gate_t6_allowed_roots` 用 AST 从**本函数体内**抓第一个
名字含 `allowed` 的赋值，按字符串常量拼回 `PLUGIN_ROOT.joinpath(*segments)`，再判「白名单是否
仍覆盖紧急域 / 是否仍覆盖闸自身」。所以该赋值必须留在函数体内、必须写全三段字面量。
本席保留该形制并在锁上注释写明，注毒 M7 证明这条对齐是活的（见下表）。

### RED（保留 `startswith`、只摊平根之后）

```
FAILED test_submit_active_push_production_importers_are_allowlisted
AssertionError: 兄弟目录 transport_legacy/old.py 被判进白名单＝`transport*` 前缀仍松
assert not True
1 failed, 55 deselected
```
（这一步同时复现了 PROBE-2 的原始实证形态。）

### GREEN

```
三件合跑：215 passed, 4 xfailed, 1 failed（唯一失败=§0 常驻那条）
禁写件 tests/test_emergency_info_core.py::test_domain_reaches_the_queue_only_through_the_central_gate
  → 仍绿（两侧对齐未破）
```

### 变异回退红（3 次，均 RESTORE_OK）

| 注毒 | 红况 |
|---|---|
| M5 `_under_directory` 退回 `startswith` | 2 红：`…_are_allowlisted` + `test_allowlist_helper_itself_is_not_vacuous` |
| M6 判定恒 `False`（把合法侧也收死） | 同上 2 红 ⇒ 正/负两侧的活性断言都有牙，不是「全 False 也算收紧成功」的假绿 |
| M7 `allowed_roots` 退回裸目录名字符串 `("transport","emergency_info")` | **禁写件**红：`test_emergency_info_core.py::test_domain_reaches_the_queue_only_through_the_central_gate` `assert []` ⇒ 形制纪律不是嘴上说的 |

### 「零 importers 期空真」的处置（按任务书：不蒙）

新增 `test_submit_active_push_has_at_least_one_production_caller`，`@pytest.mark.xfail(strict=True)`，
断言的是**真实使用**（AST：`ImportFrom` 含该符号，或 `submit_active_push(...)` 调用点），
不是文本命中；闸自身排除。当前 `_production_uses_of_central_entry()` 实跑返回 `[]` ⇒
本用例真红→按预期失败记 xfail。落地当天它会 XPASS ⇒ strict=True 立刻转红，逼接线席删标记。
**没有**为此造任何假 importer（生产树零新增文件，见 §自证）。
转正条件写在 reason 里（机器可读，`-rx` 可见），锁的 docstring 另写「双侧」分工：
allowlisted 钉「越界为零」，本条钉「引用者不为零」。

### 落点

`tests/test_outbound_gate.py`：新增模块级 `_under_directory()` / `_production_uses_of_central_entry()`
两个纯判定助手 + 改写 `test_submit_active_push_production_importers_are_allowlisted`
+ 新增 `test_allowlist_helper_itself_is_not_vacuous`（不依赖接线的活性锁）
+ 新增上述 xfail 锁。生产面零改动（本件纯测试面）。



## F-3 日志锁被回溯喂饱 + 六观测面值零锁（GAP-5/GAP-7）

本件**零生产代码改动**（日志与审计字段本来就写得很全，缺的是锁），故 RED 不能靠
「实现缺校验」给出。替代方案：把 LOCK-AUDIT 的负控制原样重放一遍，用一条
**盘外探针**（`$TEMP/lock-fix-seat/probe_f3.py`，不落源码树）直接对比同一中毒态下
旧断言与新断言的判别力——这才是「先 RED」的等价物。

### 负控制实跑（G27 同形：只改 `record_failure` 消息文本，保留 `%s` 与 `exc_info=True`）

```
健康态：    消息="outbound_gate record_failure subject_key_hash=f12ed7add38c"
            旧断言 True ／ 新断言 True
中毒态：    消息="gate counting broke (see traceback) f12ed7add38c"
            旧断言 assert "outbound_gate" in caplog.text -> True   ← 被回溯里的模块路径喂饱＝零判别
            新断言（短语 startswith + subject_key_hash 取值） -> False   ← 注毒被抓
            回溯里是否含模块路径 outbound_gate.py -> True（健康态同样是 True，即旧断言恒真）
pytest 侧：FAILED test_record_failure_still_allows_and_reports（+where False = any(<genexpr>)）
```
⇒ 与 LOCK-AUDIT「G27 改文本 59 全绿 / G27b 整块删才红」完全对上，现在文本漂移即红。

### 六面逐条 GREEN + 注毒必红（9 次变异，全部 RESTORE_OK 字节复核）

| 面 | 新锁（tests/test_outbound_gate.py） | 注毒 | 红况（已剔除常驻那条） |
|---|---|---|---|
| 日志 `window_count` 取值 | `test_log_line_carries_spec_fields_and_no_content`（重写：预置 1 笔窗内已投 ⇒ 钉 `window_count=1`，不用 0 做正样本） | `m3b_logzero`（该实参恒 0） | 2 红（本条 + 顺延那条共用字段） |
| 日志字段名 | 同上钉 `subject_key_hash=` / `deliver_after=none` | `m3b_logfields`（三字段名改名 subject=/cnt=/after=） | 2 红 |
| 审计 `window_count` | `test_audit_private_debug_carries_window_count_and_deliver_after` | `m3b_wcount`（整字段删除，=G23） | 1 红 |
| 审计 `deliver_after` | 同上 + `test_deferred_audit_and_log_carry_the_real_defer_moment`（钉到 `2026-09-14T12:01:00+00:00` 秒级） | `m3b_dafield`（整字段删除，=G24） | 2 红 |
| 审计事件名 allow/defer/skip | `test_audit_severity_comes_from_the_request_content_risk_level` 三事件逐条列表比较（`G53` 型整块删仍由存量锁抓） | — 存量 G15/G53 已证，本席补的是同用例内的取值面 | — |
| skip 回执三字段 | `test_skip_receipt_is_shaped_by_the_gate_and_never_invents_a_handle`：`transport=="outbound_gate"`、`provider_message_id is None`、`public_message=="dedupe_key_shape"`；另一侧喂 `operational_issue` 时 `public_message==""` 且 issue 保留 | `m3b_skipreceipt`（transport 改名 + public_message 恒空，=G49+G50 同形） | 1 红 |
| 审计 `severity` 取值 | 同上（喂 HIGH/CRITICAL/MEDIUM 三个**合法但各不同**的 risk_level） | `m3b_severity` 换源为 `OperationalIssue().severity`（=MEDIUM，合法常量、不抛异常） | 1 红 ⇒ 红因是**断言在查值**，不是 LOCK-AUDIT G47b 那种「append 抛异常」假红 |
| `_severity_of` 归一 | `test_severity_normalisation_and_blank_severity_is_never_urgent`：`" p2 "→"P2"`、`""→""`、`priority=None` 进不了契约（`ValidationError`） | `m4b_severityof`（去 `.upper()`） | 2 红（含存量 `test_urgent_severity_matching_is_case_insensitive`） |
| （顺带）空串白名单穿窗 | 同上一条 `_is_urgent(_request(priority=""), ["", " "]) is False` | `m4b_urgentfilter`（删 `if str(value).strip()` 过滤，=G34） | 1 红 |

`subject_key_hash` 的期望值在测试里用 `hashlib` **独立算**（`_expected_subject_hash()`），
不 import 闸的 `_subject_hash`——拿被测实现算期望值再比自身＝C 类恒真，本席不犯。
「不得含明文 target_id」同时锁：`"group:g-1" not in 日志行`、`not in 审计拼接串`、
`"暴雨红色预警" not in` 三处。

### 一处有代价的整理（不是静默改口径）

原 `test_log_line_carries_spec_fields_and_no_content`（LOCK-AUDIT 判「A（局部）」、
G25 涂值不红）被我**原位替换**为钉取值的版本，同名不重复定义：正样本从
「`window_count` 恰为 0」改成「预置 1 笔窗内已投 ⇒ `window_count=1`」。旧版那五条断言
（action/request_id/capability_id/零正文/零明文）全部保留，只加不减。

## F-4 注释与实现不符 + 双谓词同源化

- 旧账：`dedupe.py:9-10` 宣称「transport 侧中央闸按本模块的 `is_emergency_dedupe_key`
  做键规范核验」——**当时为假**（闸自带一套宽松谓词，两侧从未接通）。
- 处置：不删注释迁就实现，而是把实现改成注释说的那样（闸侧委托域侧，见 F-1 方向裁定）。
  现在那句话为真，且有 `test_dedupe_predicates_share_one_implementation` 的 AST 锁兜底
  （M4 分叉注毒 ⇒ 该条当场红）。锁**不钉散文**：钉的是散文所述的那条结构事实。
- 同源化细节：链接注释双向留痕（闸侧 docstring 指回域侧唯一实现；域侧头注写明闸侧委托、
  并登记本席踩过的两个坑）；`DEDUPE_NAMESPACE` 在闸侧改为引用 `EMERGENCY_DEDUPE_PREFIX`
  （结构锁断言它不得再是字面量）；段字符集/日期段正则只剩域侧一处（结构锁断言闸侧
  `re.compile` 出现即红）。
- 行号更正：`queue.py` 的 `ON CONFLICT(dedupe_key) DO NOTHING` 实测在
  `:459`、skipped 分支 `:475` ⇒ 注释由 `444-476` 改 `443-475`（原引范围上下各偏一行）。
  `tests/test_emergency_info_core.py:503` 仍写 `444-476`——禁写面，登记不改。

## 未做与原因（含「判断不该现在做」的部分）

1. **常驻红 `test_existing_families_still_submit_directly` 未动**（开工即有，见 §0）。
   它红在根 `__init__.py` 直调数 5→4（他席 campus 收编已落地），而该文件与本条锁口径
   都是我的禁写面。**没有**用「把门槛改成 ≥4」这种改断言口径换绿的做法——那正是任务书
   禁止的「为凑绿改口径」。处置权在主会话与用户：要么承认 4 是新常态并显式授权改锁，
   要么要求收编席回退一处。
2. **GAP-3（滑窗保留期与顺手 prune 零锁）未做**——它是 LOCK-AUDIT 清单里排在
   我这四件之前的「会炸」级（G43：保留期 2×小时窗→2×分钟窗 不红 ⇒ 每主体小时上限
   静默失效）。不在我的四件授权内，故不越权补，提请主会话优先派席。
   成本已压低：`FakeStore` 只需再记 `prune_calls` 就能钉「落账后近 2 小时行不被剪 +
   `_RETENTION_SECONDS >= 小时窗`」。
3. **GAP-4（中央闸生产零接线、`set_outbound_verify_provider` 全树零调用者）未做**——
   属接线席（WIRE-MAP/LINK-AUDIT 那条线），且我若「顺手接线」必然要碰根 `__init__.py`。
4. **GAP-6 的 store 故障日志块（G46：`decide` 里 `_logger.exception` 整块删除不红）
   与 `REASON_STORE_DEGRADED` 短语改名（G45）未做**——不在 F-3 的六面清单里，我没擅自
   扩面。补它只需两条断言（短语本体 + 该日志存在），建议并入下一席。
5. **GAP-8（四处等号边界）/GAP-10/GAP-11/GAP-12/GAP-13/GAP-14 未做**——均在四件之外；
   GAP-13 还要碰真 `Config()` 装配面（config.py 与根 init 双禁写）。
   唯一顺手做的是 **GAP-9**（`urgent_severities=[""]` + priority 空 ⇒ 被当紧急穿窗）：
   它与 F-3「`_severity_of` 取值归一」是同一条代码路径的两半（`_is_urgent` 里的
   `if str(value).strip()` 过滤），补锁零生产改动，故一并钉住（`m4b_urgentfilter` 实证）。
6. **同源化的架构代价，未「顺手」优化**：现在 `transport/sender/outbound_gate.py`
   import 了业务域的服务模块 `emergency_info/service/dedupe.py`（基础设施引用域内键规范）。
   更干净的落点是搬进中立件让两侧同引，但那 ①要新建文件（超出四件独占面）②仍解不开
   「域内核不许 import transport」这条禁写锁（它拦的是我试过的另一方向）。已用
   `test_dedupe_predicates_share_one_implementation` 里的**防环断言**把方向钉死（域侧
   代码段出现 `outbound_gate` 即红），中立件方案写进 §落地请求 供裁。
7. **未做公开面清理**：委托后闸侧 `DEDUPE_NAMESPACE`（引用别名）、`AUDIT_TRANSPORT`
   内部消费者变少。未删——收缩公开面归主会话裁定，且 `__all__` 一字未动。
8. **未碰 git 写操作、未再派子代理、未在源码树落任何临时件**（harness/探针/快照/全量
   日志全在 `$TEMP/lock-fix-seat/`，见 §0.1）。

## 落地请求（需要热面/主会话配合的）

1. **请收尾席记账**（`docs/**`、`AGENTS.md` 对我禁写）：本席交付 =
   `reports/LOCKFIX-report.md`；改动面 3 件（生产 2 + 测试 1）；数字见 §签核。
2. **请主会话裁**：`test_existing_families_still_submit_directly` 的门槛口径
   （5 → 4，或要求回退一处直调）。这是 LOCK-AUDIT 撞车预警的兑现，不是本席能定的。
3. **请接线席落地时做两件事**（我的锁会自动催）：
   ① 生产面出现 `submit_active_push` 的真实使用后，删
   `test_submit_active_push_has_at_least_one_production_caller` 的
   `@pytest.mark.xfail(strict=True)` 标记——不删会以 XPASS→FAIL 挡全量；
   ② 若要新增键命名空间（`emg:` 之外），改 `domains/emergency_info/service/dedupe.py`
   一处，别在闸侧加分支（AST 结构锁会红）。
4. **中立件方案（建议，不实施）**：把 `EMERGENCY_DEDUPE_PREFIX`/`_SEGMENT_RE`/
   `_DATE_KEY_RE`/`is_emergency_dedupe_key` 整体搬入新建 `domains/core/dedupe_key.py`，
   闸与紧急域同引；同时把 `test_kernel_never_imports_network_or_llm` 的 forbidden
   `"transport"` 令牌改判为「禁止 import 闸真身（outbound_gate）」而非按目录前缀一刀切，
   否则域内核永远只能单向被引用。需用户裁定（动禁写件 + 新建件）。
5. **生产代码 diff 原文（本席唯一的行为变更，评审一眼看完）**：

```python
# 前：outbound_gate.dedupe_key_shape_ok —— 只查段数与空段，脏键照过
def dedupe_key_shape_ok(dedupe_key: str, *, family: str = DEDUPE_FAMILY_ONCE) -> bool:
    segments = dedupe_key.split(KEY_SEPARATOR)
    if any(not segment.strip() for segment in segments):
        return False
    if segments[0] != DEDUPE_NAMESPACE:
        return False
    allowed_counts = (5,) if family == DEDUPE_FAMILY_DAILY else (4, 5)
    return len(segments) in allowed_counts

# 后：委托域侧唯一实现（前缀等值 + 段数 + 逐段字符集 + 日期段形态，四条齐全）
def dedupe_key_shape_ok(dedupe_key: str, *, family: str = DEDUPE_FAMILY_ONCE) -> bool:
    return is_emergency_dedupe_key(
        dedupe_key,
        require_date_key=family == DEDUPE_FAMILY_DAILY,
    )
```
   `dedupe.py` 侧唯一行为变更 = `is_emergency_dedupe_key` 去掉整串预 `strip()`
   （`"  emg:qq:a:b  "` 由 True 改判 False，方向=收紧）。禁写件 core 那 12 例逐条复跑全绿。

## 签核（收工实跑，可整段复跑）

```
命令：PYTHONDONTWRITEBYTECODE=1 ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest \
       tests/test_outbound_gate.py tests/test_emergency_info_core.py \
       tests/test_emergency_info_sources.py -q -p no:cacheprovider --basetemp=$TEMP/lock-fix-tt

开工基线  三件合跑 200 passed, 3 xfailed, 1 failed（闸 41P+1F / core 101P+2x / sources 58P+1x）
收工      三件合跑 220 passed, 4 xfailed, 1 failed（闸 61P+1x+1F=63 采集 / core 101P+2x / sources 58P+1x）
          净增 20 条用例 + 1 条 xfail(strict)；三件之外零失败
全量      9640 passed, 6 failed, 12 skipped, 11 xfailed in 477.95s
ruff      All checks passed（本席三件，--no-cache）
mypy      Success: no issues found in 2 source files（项目 flags：--explicit-package-bases
          --ignore-missing-imports；--cache-dir 指到 $TEMP，树内零新增缓存）
```

**全量那 6 条失败逐条归属（无一条属本席）**：

| 失败 | 归属证据 |
|---|---|
| `test_outbound_gate.py::test_existing_families_still_submit_directly` | 开工即有（§0），他席 U17 campus 收编删掉根 init 一处直调；本席禁写面 |
| `test_cross_validation_gates.py::test_doc_sync_auto_facts_in_sync` | 实跑 `scripts/doc_sync.py` 与 `docs/auto-facts.md` 做行级 diff ⇒ **唯一差异=「测试文件数：466→468」**（他席新增 2 个 tests/ 文件）；本席零新增 tests/ 文件 |
| `test_cross_validation_gates.py::test_verify_hashes_manifest_clean` | 全量后立刻单跑该文件 ⇒ 本条转绿 ⇒ 多席并发改哈希件（echo.py 等在飞）的窗口性漂移，非稳定红 |
| `test_autosync_hook.py::test_autosync_end_to_end_mini_session` | autosync 钩子域，与本席三面零交集 |
| `test_chat_and_sources_regressions.py::test_cookie_recovery_preserves_other_rows_and_never_writes_source` | cookie/chat 域 |
| `test_mermaid_reply_render.py::test_render_mermaid_html_mica_and_escapes` | render 域（台账 #26 已登记 mermaid 真机待重启观察） |

**字节终态（三件真身，全部纯 CRLF、零 POISONED 残余）**：

```
outbound_gate.py     as-found 32271B/CRLF774/b3fd4ccf1413 → 收工 33666B/CRLF791 /d5d4a7948f39
dedupe.py            as-found  5485B/CRLF134/68e9d8399e04 → 收工  7606B/CRLF157 /ea5beea1f5af
tests/test_outbound_gate.py    as-found 50660B/CRLF1347/8b6434483fae
                                                     → 收工 78735B/CRLF1947/6953e4148be6
```
（sha 取 sha256 前 12 位；CR 计数与 LF 计数相等 ⇒ 行尾未漂移，§0.1 那次 LF 事故已修正
并保持到收工。`git diff --numstat`：gate 26/9、test 637/37；dedupe 为 untracked 故无 diff 行。）

**注毒计数**：17 次中毒态 pytest 运行（F-1 4 · F-2 3 · F-3 10；其中 F-3 的
`m3b_recordmsg` 首版注毒丢了 `%s` 占位、不忠实于 G27，改好后重跑一次），
**全部 `restore=OK`（磁盘字节 sha 与快照等值 + POISONED 残余=0）**；另有 2 次盘外探针
运行（健康态/中毒态对照，见 §F-3 负控制）。一次中毒残留约 2 分钟后自查回
（§0.1 第 2 条：harness 被 basetemp 抹掉那次），按反向字节替换复原并复核 sha，已如实登记。

**禁写面自证**：`git status --porcelain -- tests/test_emergency_info_core.py
tests/test_emergency_info_sources.py` ⇒ **输出为空**（与 HEAD 逐字节相同，铁证本席未碰）。
根 `__init__.py`(81/3)、`runtime/base_router.py`(11/772)、`tests/test_capability_registry.py`
(13/10)、`docs/auto-facts.md`(M) 均有改动，归属他席在飞工作——本席对这些文件零写入调用。
树内卫生：`*.pyc`=0、`__pycache__`=0、源码树 `data/` 不存在、`.pytest_cache` 不存在；
`.ruff_cache`/`.mypy_cache` 为开工即存的他席产物（本席 `--no-cache` + `--cache-dir=$TEMP`
未追加）。收工时 HEAD=`c3ac342`（本席零 git 写操作）。

**未生效声明**：以上全为离线 mock 实跑，**未 commit、未部署、未重启生产 bot**；
中央闸在生产仍零接线（LOCK-AUDIT GAP-4），故本席改动对现网行为零影响。

Status: DONE_WITH_CONCERNS（四件全绿落地；Concerns=§未做 1/2/3/6 四条 + §0 那条常驻红待裁）
