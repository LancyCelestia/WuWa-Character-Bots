# LOCKAUDIT — 锁体检报告（B 波 · 变异检验式审计）

Status: DONE（59/59 条逐条判定完毕；78 次注毒/负控制全部还原，末态与开工快照逐字节相同；零残留）
Seat: LOCK-AUDIT
Date: 2026-09-20
HEAD at start: `14e6480`
`git status --porcelain | wc -l` at start: `953`

## 0. 范围与方法

审计对象（仅此两件）：
- `tests/test_outbound_gate.py`（1347 行 / 42 条）
- `tests/test_delivery_verification_tier1.py`（409 行 / 17 条）

被测实现：
- `plugins/bot_unified_runtime/domains/transport/sender/outbound_gate.py`
- `plugins/bot_unified_runtime/domains/transport/sender/onebot.py`（Tier1/Tier2 面）

禁区（D1-FIX 席在写）：`tests/test_emergency_info_core.py`、`tests/test_emergency_info_sources.py`、`domains/emergency_info/**`。

分类口径：
- `A 真锁`：改坏实现即红（经变异验证）。
- `B 方向锁`：钉"不许往错方向走"，须两侧都能失败才有效。
- `C 恒真/空真`：断言在当前树状态下不可能失败（零集合全称命题、比对自身等）。
- `D 弱锁`：只在实现按某特定写法时红（字面串匹配、前缀过松、异常被吞）。

方法：每条用例至少一次最小注毒，注毒只改被测实现文件，`cp` 备份至 `$TEMP/lock-audit/`，每次注毒后立刻还原并复跑回基线。

## 1. 基线 mtime 快照（开工）

| 文件 | mtime | 大小 |
|---|---|---|
| tests/test_outbound_gate.py | 2026-09-20 03:12:36 | 50660 |
| tests/test_delivery_verification_tier1.py | 2026-09-20 01:51:19 | 15318 |
| .../sender/outbound_gate.py | 2026-09-20 02:15:06 | 32271 |
| .../sender/onebot.py | 2026-09-20 02:50:16 | 54666 |

（收工时会比对，若实现文件 mtime 在本席注毒期间被他人推动，将在本报告标注并停手重读。）

## 2. 心跳 #1（批次 1 完成，22 注毒）

Status: RUNNING — 42+17 条中已完成 gate 侧 22 点变异；全部 `restore=OK`（sha256 字节等值复核），
`git diff --numstat` 对两个实现文件**为空**（零残留）。

### 批次 1 注毒记录（实现=outbound_gate.py）

| # | 注毒 | 结果 | 变红的用例 |
|---|---|---|---|
| G01 | 关闭态不再直通（`if not settings.enabled`→`if False`） | **RED 4** | test_gate_disabled_is_passthrough, test_default_settings_keep_gate_off, test_callable_settings_are_reread_on_every_decision, test_settings_resolution_failure_falls_back_to_disabled |
| G02 | store 故障 fail-open→fail-closed(skip) | **RED 2** | test_gate_store_failure_fails_open, test_sqlite_store_failure_is_visible_to_gate |
| G03 | 忽略 `quiet_defer_enabled` 开关 | **RED 1** | test_quiet_defer_switch_off_allows_everything |
| G04 | 紧急判定取反 | **RED 14** | 静默族全量 + 风暴族 + 审计族 + 三门顺序族 |
| G05 | 等级大小写折叠删除 | **RED 1** | test_urgent_severity_matching_is_case_insensitive |
| G06 | 分钟上限 `>=`→`>` | **RED 3** | test_per_target_minute_cap_defers, test_only_allowed_pushes_are_counted, test_rate_gate_decides_before_dedupe_shape |
| G07 | 小时窗 3600→300s | **RED 1** | test_per_target_hour_cap_defers |
| G08 | 去掉「0=该窗关闭」守卫 | **RED 1** | test_zero_cap_means_that_window_is_disabled |
| G09 | defer/skip 也计入滑窗 | **RED 5** | test_only_allowed_pushes_are_counted 等 |
| **G10** | **删除 dedupe 键 `emg` 命名空间校验** | **没红（59 passed）** | **⇒ 命名空间规则零覆盖，见缺口 GAP-1** |
| G11 | 删除空段校验 | **RED 1** | test_malformed_dedupe_keys_are_skipped |
| G12 | daily 族段数 (5,)→(4,5) | **RED 1** | test_dedupe_key_shape_enforced |
| G13 | 风暴阈值 3→4 | **RED 1** | test_three_consecutive_defers_emit_storm_alert |
| G14 | 放行不清连击账 | **RED 1** | test_storm_ledger_resets_after_allow |
| G15 | 审计事件前缀 `outbound_gate_`→`gate_` | **RED 2** | test_allow_defer_skip_each_append_one_gate_audit, test_dedupe_key_shape_enforced |
| G16 | 主体哈希改回明文 | **RED 3** | 三条隐私断言用例 |
| G17 | 关闭态也写审计 | **RED 1** | test_gate_disabled_is_passthrough |
| G18 | 队列不认 deliver_after 时不再报 degraded | **RED 1** | test_legacy_queue_without_deliver_after_fails_open |
| G19 | 设置求值异常回退为「开」 | **RED 1** | test_settings_resolution_failure_falls_back_to_disabled |
| G20 | 静默窗尾跨日进位删除 | **RED 1** | test_quiet_defer_handles_cross_midnight_window |
| G21 | 窗判定不按 settings 时区换算 | **RED 1** | test_quiet_window_evaluated_in_settings_timezone |
| G22 | 静默面 session_types 过滤删除 | **RED 1** | test_quiet_only_applies_to_settings_session_types |

### 开工即实锤的两条结构性事实（只读取证）

1. **T6 生产 import 白名单 = 空真**。全 `plugins/` 树含 `submit_active_push` 的文件**只有 `outbound_gate.py` 自身**
   （定义 + `__all__`），白名单两前缀之外命中数 = 0 ⇒ 全称命题在空集上恒真。G10 之外第二条 C 类证据。
2. **中央闸生产零接线**：`build_outbound_gate` / `OutboundGate` / `submit_active_push` 在 `plugins/` 内
   **除自身模块外零引用**（只有 `runtime/settings.py` 两行注释提及）。`set_outbound_verify_provider`
   同样**全树零调用者**（Tier1 核验开关的生产注入缝没人走）。

## 3. 心跳 #2（批次 2/3/4 + 只读探针完成，事故两处已自纠）

### 3.1 批次 2 注毒记录（实现=outbound_gate.py，判据同批 1）

| # | 注毒 | 结果 | 变红用例 |
|---|---|---|---|
| G23 | **负控制**：审计 private_debug 的 `window_count` 整字段删除 | **没红 59P** | ⇒ GAP-2 |
| G24 | **负控制**：审计 `deliver_after=` 字段删除 | **没红 59P** | ⇒ GAP-2 |
| G25 | **负控制**：info 日志 subject_key_hash/window_count/deliver_after 三值涂掉 | **没红 59P** | ⇒ GAP-2 |
| G26 | **负控制**：`record_send` 不再顺手 prune | **没红 59P** | ⇒ GAP-5 |
| G27 | `record_failure` 日志文本去掉 "outbound_gate" 字样 | **没红 59P** | ⇒ 该用例的日志断言**零消息可辨性**（见 G27b+机制分析） |
| G27b | `record_send` except 分支整条日志删除 | **RED 1** | test_record_failure_still_allows_and_reports |
| G28 | 审计 public_message 泄漏正文 | **RED 1** | 隐私断言用例 |
| G29 | `_accepts_keyword` 恒真 | **RED 1** | legacy queue 用例 |
| G30 | Literal 加入第四态 `drop` | **RED 1** | test_outcome_models_reject_fourth_verdict |
| G31 | 缺省分钟上限 2→3 | **RED 2** | 两条缺省值用例 |
| G32 | 穿窗白名单去掉 P1 | **RED 3** | 两条缺省值 + T2 |
| G33 | config 投影缺省 enabled False→True | **RED 1** | test_default_settings_keep_gate_off |
| G34 | **负控制**：urgent_severities 空串过滤删除 | **没红 59P** | ⇒ GAP-6（`urgent_severities=[""]` + priority 空 = 被当紧急穿窗） |
| G35 | 闸自造 skip 回执 SKIPPED→BLOCKED | **RED 1** | T5 |
| G36 | 主体键丢 scope 前缀 | **RED 4** | 限流族四条 |
| G37 | 分钟顺延时刻 +60s→+1 天 | **RED 1** | T3 |
| G38 | **负控制**：`start == end`（全天静默）分支取反 | **没红 59P** | ⇒ GAP-7 |
| G39 | **负控制**：同天窗下沿 `<=`→`<` | **没红 59P** | ⇒ GAP-7 |
| G40 | passthrough 判据放宽为「任何 allow」 | **RED 1** | 审计用例 |
| G41 | 静默 reason 字面漂移 quiet_hours→quiet_window | **RED 3** | 机读短语族 |
| G42 | 跨零点窗判定 `or`→`and` | **RED 1** | 跨零点用例 |
| G43 | **负控制**：计数保留期 `2*小时窗`→`2*分钟窗` | **没红 59P** | ⇒ GAP-5（生产后果=小时窗被饿死，两分钟内即被剪） |
| G45 | **负控制**：`REASON_STORE_DEGRADED` 机读短语改名 | **没红 59P** | ⇒ GAP-3（degraded 的 reason 串无锁，只锁了 issue.kind） |
| G46 | **负控制**：decide 里 store 故障 `_logger.exception` 整块删除 | **没红 59P** | ⇒ GAP-3（该方向只靠 issue 可观测，日志面裸） |
| G47/G47b | 审计 severity 换源/换成非法常量 | RED 2，但**红因=append 抛异常导致记录缺失**（RiskLevel 只有 LOW/MEDIUM/HIGH/CRITICAL，PROBE-C 实证），非断言在查值 | ⇒ GAP-4（severity 取值无锁） |
| G48 | `AUDIT_STAGE` sender→gate | **RED 1** | 审计用例（A 证） |
| G49 | **负控制**：skip 回执 transport 改名 | **没红 59P** | ⇒ GAP-4 |
| G50 | **负控制**：skip 回执 public_message 恒空 | **没红 59P** | ⇒ GAP-4 |
| G51 | **在 docstring 里加一句"不复用 domains.schedule"（零行为变更）** | **RED 1** | test_gate_does_not_import_schedule_engine ⇒ 该锁**会误伤无辜提及**，判 D |
| G53 | `gate.audit(...)` 调用整体删除 | **RED 2** | 审计两用例（证明审计锁有真判别力） |
| G54 | 连击账失效（deferred 参数被忽略） | **RED 1** | test_storm_ledger_resets_after_allow |
| G55 | `return len(segments) in allowed_counts` → `return True` | **RED 3** | T5 + 段数不足 + 段数超限 两个参数化实例 |
| S01 | count_sends 丢时间谓词（滑窗退化全量） | **RED 1** | test_sqlite_store_counts_and_prunes_deterministically |
| S02 | **负控制**：滑窗下沿 `>=`→`>` | **没红 59P** | ⇒ GAP-8（等号时刻不可辨） |
| S03 | **负控制**：prune 边界 `<`→`<=` | **没红 59P** | ⇒ GAP-8 |
| S04 | prune 谓词反号 `<`→`>` | **RED 1** | 同上（A 证） |

### 3.2 批次 3 注毒记录（实现=onebot.py Tier1/Tier2 面）

| # | 注毒 | 结果 | 变红用例 |
|---|---|---|---|
| O01 | 丢段观测日志整块关掉 | **RED 2** | 指纹两用例 |
| O02 | dropped_types 改塞整段 dict（正文外泄形） | **RED 2** | 同上（指纹是精确串比较，抓得住） |
| O03 | 全段失败回落文本被涂空 | **RED 1** | T8 字节一致用例 |
| O04 | 无丢段也刷观测行 | **RED 1** | test_clean_mixed_emits_no_drop_log |
| O05 | 核验开关缺省 关→开 | **RED 1** | test_sent_receipt_unchanged_when_verify_off |
| O06 | 不看丢段、开关一开就挂 issue | **RED 1** | test_verify_on_clean_mixed_adds_no_issue |
| O07 | 开关 getter 抛异常时 fail-open→fail-closed | **RED 1** | test_verify_provider_failure_fails_open |
| O08 | issue retryable False→True | **RED 1** | T9 真侧 |
| O09 | 丢段注记改判 ReceiptState（SENT→FAILED_RETRYABLE） | **RED 1** | T9 真侧（重投风暴面被住） |
| O10 | issue kind 改名 | **RED 1** | T9 真侧 |
| O11 | Protocol 里 get_msg 声明改名 | **RED 1** | **仅** test_onebot_protocol_declares_optional_get_msg（=钉声明不钉行为） |
| O12 | 鸭子探测失败分支 None→False | **RED 1** | test_confirmer_without_get_msg_returns_none |
| O13 | 无把手时臆造 message_id（盲查） | **RED 1** | test_confirmer_without_message_id_never_queries（`bot.calls==[]` 有牙） |
| O14 | get_msg 命中不再判 True | **RED 1** | test_confirmer_hit_returns_true |
| O15 | 查询异常 None→False（误判未送达→重投双发） | **RED 1** | test_confirmer_exception_returns_none |
| O16 | 去掉 `_ONEBOT_GET_MSG_NOT_FOUND_PROVEN` 取证门 | **RED 1** | not-found 未取证用例（方向锁真侧成立） |
| O17 | not-found retcode 1400→1401 | **RED 1** | 取证翻真用例（两向都可红=B 有效） |
| O18 | 成功回执不再读嵌套 `data.message_id` | **RED 1** | test_sent_receipt_unchanged_when_verify_off |

### 3.3 只读探针（不动树，用于覆盖禁注毒面）

| # | 探针 | 实证 |
|---|---|---|
| PROBE-1 | 根 `__init__.py` 直调 `*queue*.submit` 实数 | **5**（行 2954/3065/3223/3372/5059），锁门槛 `>=5` ⇒ **余量 0**：只在下调时红，新增绕行永不红；且**在飞 S0-ROOT-c 的"直连收编"必然把它推下 5** |
| PROBE-2 | T6 白名单 `startswith` 松紧 | `domains/transport_legacy/old.py`、`domains/transporter/evil.py` **均被判 allowed=True** ⇒ `emergency→emergency_info` 的收紧只做了一半，`transport` 这一支仍松（`domains/emergency_other`、`emergencyinfo` 已正确判 False） |
| PROBE-3 | 全 plugins/ 树含 `submit_active_push` 的文件 | **[] 空集**（唯一命中 outbound_gate.py 自身，而它被 `path.name` 排除）⇒ `assert offenders == []` **在空集上恒真** |
| PROBE-4 | `submit_active_push` 是否在根 `__init__.py` | False ⇒ 该断言当前为真的原因是"接缝不存在"，不是"接对了缝" |
| PROBE-A | T13 单源锁对**行为等价合法改写**的反应 | 用合成件跑同一段 AST 判定：`from ...chat_reply import quiet_hours as _qh` + `_qh._parse_hhmm()` 两向调用 ⇒ `quiet_module in imported` 与 `'_parse_hhmm' in imported[...]` **两条直红** ⇒ 判 D（合法重构必误红） |
| PROBE-B | `ReceiptState` 基数 + 禁词绕过 | 成员数 = **9**，集合相等比较 ⇒ 新增任意成员必红（A）；禁词只钉 `PARTIAL_SENT` 一字面，`PARTIAL_DELIVERED`/`partial_sent` 等改名全穿（该子句 D） |
| PROBE-C | `AuditRecord.severity` 取值域 / StrictBaseModel | severity 是 `RiskLevel` 枚举（LOW/MEDIUM/HIGH/CRITICAL）⇒ G47b 的红来自"append 抛异常"；`StrictBaseModel.model_config = {'extra':'forbid'}` ⇒ 用例 37 的 `unknown_field=1` 断言有实底 |
| PROBE-D | 根 init 接线条件探针 | 真 `Config()` 走线返回 `{'registered': False, 'reason': 'disabled'}`（`bot_send_queue_worker_enabled` 缺省关）⇒ 两条生产接线用例全程用 SimpleNamespace，**真 Config 默认值组合不在其覆盖内** |
| 全树 grep | 缺口是否被别的测试件补住 | `window_count` / `subject_key_hash` / `_RETENTION_SECONDS` / `set_outbound_verify_provider` / `dedupe_key_shape_ok` 在 **tests/ 全目录命中数 = 0** ⇒ 上述缺口是全局缺口，非本两件漏配 |

## 4. 逐条判定（59 条，全量无抽查）

### 4.1 `tests/test_outbound_gate.py`（42 条采集，含 5 个参数化实例）

| 用例 | 它断言了什么 | 类 | 变异证据 |
|---|---|---|---|
| test_gate_disabled_is_passthrough | 关闭态裸 submit 恰一次/零 store 触点/零审计 | **A** | G01 RED4 · G17 RED · G09 RED |
| test_default_settings_keep_gate_off | 六项缺省值 + 空配置投影 + 直通 | **A** | G01 · G31 RED2 · G32 RED3 · G33 RED |
| test_config_keys_keep_gate_off | 真 Config 六键缺省 + db_path 绝对 + 投影 | **A**（附注 skipif 可静默失效 GAP-12） | G31 · G32 RED（当前实跑生效，非 skip） |
| test_quiet_hours_defers_non_urgent_p0_p1_pass | P2 顺延到 quiet_end；P0/P1 立即放行 | **B**（两侧均可红，有效） | G04 RED14 · G32 · G41 RED3 |
| test_quiet_defer_handles_cross_midnight_window | 23:00→07:00 两侧顺延时刻 + 窗外放行 | **A** | G20 RED · G42 RED |
| test_quiet_window_evaluated_in_settings_timezone | 窗判定按 settings 时区换算 | **A** | G21 RED |
| test_quiet_only_applies_to_settings_session_types | 会话维度过滤 | **A** | G22 RED |
| test_quiet_defer_switch_off_allows_everything | 静默面子开关 | **A** | G03 RED |
| test_unknown_severity_is_treated_as_non_urgent | 未知等级一律按非紧急（保守） | **B** | G04 RED |
| test_urgent_severity_matching_is_case_insensitive | `p0` 等同 `P0` | **A** | G05 RED |
| test_per_target_minute_cap_defers | 60s 窗、`>=cap`、主体键 shape、+60s 时刻 | **A** | G06 RED3 · G36 RED4 · G37 RED |
| test_per_target_hour_cap_defers | 3600s 窗与 +3600s | **A** | G07 RED · G36 RED |
| test_zero_cap_means_that_window_is_disabled | 0=该窗不生效 | **B** | G08 RED |
| test_only_allowed_pushes_are_counted | 只 allow 落账 | **A** | G09 RED5 · G06 · G36 |
| test_gate_store_failure_fails_open | store 病→allow + degraded | **B**（方向锁，反号必红） | G02 RED2 |
| test_record_failure_still_allows_and_reports | 写计数失败 fail-open + 日志可观测 + 零正文 | **A**（行为面；"日志可观测"半句＝无效，见 GAP-7） | G27b RED1（整条删才红）/ G27 不红（换文本） |
| test_dedupe_key_shape_enforced | daily 缺 date_key→skip、不触队列、SKIPPED 回执、审计一条 | **A** | G12 RED · G15 · G35 · G53 · G55 · G47b |
| test_malformed…[digest_push:g-1:2026-09-14 / 标称"非 emg 命名空间"] | 名为锁命名空间，实则被**段数**拦下 | **D（名实不符）** | G10（删命名空间校验）**59 全绿** ⇒ 该参数实例对命名空间零判别 |
| test_malformed…[emg:qq::target / 空段] | 空段必 skip | **A** | G11 RED（唯一由空段规则拦下的实例，判别干净） |
| test_malformed…[emg:qq:only-three / 段数不足] | 段数必 skip | **A** | G55 RED |
| test_malformed…[emg:qq:a:b:c:d / 段数超限] | 段数必 skip | **A** | G55 RED |
| test_malformed…[emgqqabcd / 无分隔] | 无分隔必 skip | **A**（过定：段数与命名空间任一都能拦，单独拆一条规则不红） | G55 不红 / G10 不红 / 段数与命名空间同删才红 |
| test_gate_does_not_build_second_dedupe_ledger | 真 SQLite 队列出 skipped（闸不另建账） | **A**（队列侧真断言；未注毒理由见 §5 末） | 断言直取真队列的 state + public_message |
| test_quiet_gate_decides_before_rate_and_dedupe | 三门顺序：第一道赢 | **B** | G41 RED3 · G04 RED |
| test_rate_gate_decides_before_dedupe_shape | 第二道赢第三道 | **B** | G06 RED · G36 RED |
| test_urgent_still_hits_dedupe_shape_gate | 紧急不豁免键规范 | **B** | G04 RED |
| test_three_consecutive_defers_emit_storm_alert | 3 连击恰报一次 + 主体以哈希出现 | **A** | G13 RED · G16 RED · G54 RED |
| test_storm_ledger_resets_after_allow | 放行清连击账 | **A** | G14 RED · G54 RED |
| test_allow_defer_skip_each_append_one_gate_audit | 三事件各一条 + stage + capability + 零正文 + 哈希 | **A** | G15 · G16 · G28 · G40 · G48 · G53 全 RED |
| test_log_line_carries_spec_fields_and_no_content | 日志含 action/request_id/capability_id、零正文、零明文主体 | **A（局部）** | G16 RED；但 G25 涂掉三字段值不红 ⇒ GAP-5 |
| test_legacy_queue_without_deliver_after_fails_open | 队列不认参数时不吞消息 + 报 degraded | **B** | G18 RED · G29 RED |
| test_sqlite_store_counts_and_prunes_deterministically | 真 store 窗内计数/剪枝的四个具体数值 | **A** | S01 RED · S04 RED（S02/S03 边界不红 ⇒ GAP-8） |
| test_sqlite_store_failure_is_visible_to_gate | 真 store 不可用仍 fail-open | **A** | G02 RED2 |
| test_existing_families_still_submit_directly | 根 init 无 submit_active_push + 直调 ≥5 + dedupe 锚点在 | **D** | PROBE-1 实数=5 **余量 0**（单向棘轮，新增绕行永不红）；锚点是子串匹配；"not in source"当前为真的原因是**接缝不存在**（PROBE-4）；与在飞 S0-ROOT-c 正面撞车 |
| test_submit_active_push_production_importers_are_allowlisted | 白名单之外零引用 | **C（空集恒真）** | PROBE-3 offenders 集合基数=0；且 PROBE-2 实证 `domains/transport` 前缀仍放行 `transport_legacy`/`transporter` ⇒ 即便有内容也降为 D |
| test_no_new_receipt_state | ReceiptState 九成员集合相等 + contracts 无 PARTIAL_SENT | **A**（集合半句；禁词半句＝D） | PROBE-B 基数 9；改名 `PARTIAL_DELIVERED` 全穿禁词锁 |
| test_outcome_models_reject_fourth_verdict | action 只三态；extra 字段被拒 | **A** | G30 RED；PROBE-C `extra='forbid'` 实证 |
| test_gate_reuses_quiet_hours_single_source | ImportFrom 必须含 `_parse_hhmm`、调用≥2、禁自造解析 | **D** | PROBE-A：行为完全等价的 `import quiet_hours as qh` 写法**两条断言直红** |
| test_gate_does_not_import_schedule_engine | 源码禁三词 | **D** | G51：只在注释里写"不复用 domains.schedule"、零行为变更即 **RED** |
| test_callable_settings_are_reread_on_every_decision | settings callable 每次判定实时求值 | **A** | G01 RED4 |
| test_quiet_settings_are_also_hot_readable | quiet callable + 窗尾时刻 | **A** | G04 · G41 RED |
| test_settings_resolution_failure_falls_back_to_disabled | 设置求值炸→按关闭直通 | **B** | G19 RED |

小计：**A 28 · B 9 · C 1 · D 4 = 42**

### 4.2 `tests/test_delivery_verification_tier1.py`（17 条）

| 用例 | 它断言了什么 | 类 | 变异证据 |
|---|---|---|---|
| test_mixed_segment_drop_logged_with_fingerprint | 丢段观测行含 request_id/planned/sent/dropped_types | **A** | O01 RED2 · O02 RED2 |
| test_all_parts_dropped_text_fallback_byte_identical | 返回值与纯文本回落逐字节一致 + 回落观测行 | **A**（但 158 行 `segments == [_text_segment(...)]` 是**比对自身**＝C 子句，157 行字面量比较才是锁；GAP-11） | O01 · O02 · O03 RED |
| test_clean_mixed_emits_no_drop_log | 无丢段必须零观测行（反向锁） | **A** | O04 RED |
| test_sent_receipt_unchanged_when_verify_off | 开关缺省关→issue 恒 None + provider_message_id | **A** | O05 RED · O18 RED |
| test_sent_receipt_carries_segment_dropped_local_when_verify_on | 开关开+丢段→SENT 不变、追加 issue(kind/stage/retryable) | **A** | O08 · O09 · O10 RED |
| test_verify_on_clean_mixed_adds_no_issue | 开关开但零丢段→不挂 issue | **A** | O06 RED |
| test_verify_provider_failure_fails_open | 开关 getter 抛异常→按关闭，不炸主链路 | **B** | O07 RED |
| test_receipt_state_enum_frozen | 回执状态集合不得增删 | **A**（分析证+PROBE-B；未注毒=主体在 contracts，非本席被测实现） | 集合相等比较 |
| test_onebot_protocol_declares_optional_get_msg | `get_msg` 在 Protocol `__dict__` | **A（声明锁）**——O11 只有它自己红，钉的是声明不是行为；真实行为由下一条锁住（GAP-10） | O11 RED1 |
| test_confirmer_without_get_msg_returns_none | 无 get_msg→None | **A** | O12 RED |
| test_confirmer_without_message_id_never_queries | 无把手→None **且绝不发起查询** | **A** | O13 RED（`bot.calls==[]` 有牙） |
| test_confirmer_hit_returns_true | 命中→True，且查询用的正是 `part_message_ids[i]` | **A** | O14 RED（`bot.calls==["5"]` 锁住取数路径） |
| test_confirmer_exception_returns_none | 查询异常→None（绝不判未送达） | **B** | O15 RED |
| test_confirmer_not_found_stays_none_until_evidence | 取证前"不存在"形态不得判 False | **B**（与下一条构成双侧） | O16 RED |
| test_confirmer_not_found_false_only_when_proven | 取证翻真后结构化"不存在"→False | **B** | O17 RED（retcode 改 1401 即红） |
| test_production_drain_confirmer_none_by_default | 键缺位/关闭→confirmer=None | **B**（未注毒根 init=禁写面；与下一条互证条件活性，PROBE-D 补真 Config 缺口 GAP-13） | 两条同时绿 ⇒ 分支确为条件式 |
| test_production_drain_wires_confirmer_when_enabled | 显式开启→confirmer 非 None | **B** | 同上 |

小计：**A 11 · B 6 · C 0 · D 0 = 17**

## 5. 一行总账与缺口清单

**总账：A 真锁 39 · B 方向锁 15 · C 恒真/空真 1 · D 弱锁 4 = 59。**
可红率（A+B）= **54/59 = 91.5%**；15 条 B 类**全部双侧验证**（两侧都能红），无"只钉一侧"的方向锁。
本波三次栽跟头的形态，在这 59 条里只复现 **1 处 C（用例 35）+ 4 处 D**；主链行为面（fail-open / 三门顺序 / 双滑窗 / 取证门 / 回执冻结）经变异检验结实。

### 一、会炸（有真实损害路径，当前零锁）

| ID | 缺口 | 证据 | 后果 |
|---|---|---|---|
| GAP-1 | dedupe 键 `emg` **命名空间规则零覆盖** | G10 删该校验 ⇒ **59 全绿**；被标名"非 emg 命名空间"的参数实例实际由**段数**拦下 | 任何四/五段冒号键（含 `digest_push:x:y:z`）都被判合规 ⇒ 闸失去"只服务紧急域"的边界含义 |
| GAP-2 | T6 生产 import 白名单 = **空集恒真 + 前缀仍松** | PROBE-3 offenders 基数 0；PROBE-2 `domains/transport_legacy`、`domains/transporter` 判 allowed=True | 接线起，越界 import 落在 `transport*` 兄弟目录**永不红**，"唯一入口"失守无告警 |
| GAP-3 | 滑窗**保留期与顺手 prune 零锁** | G43（2×小时窗→2×分钟窗）不红；G26（prune 不执行）不红 | 保留期压到分钟级 ⇒ 小时窗计数自剪，**每主体小时上限静默失效**，恰在高峰期失去第二层闸 |
| GAP-4 | 中央闸与核验开关**生产零接线、注入缝无人调** | PROBE-4；`build_outbound_gate`/`submit_active_push` 于 plugins/ 内除自身零引用；`set_outbound_verify_provider` **全树零调用者**（tests/ 亦零命中） | Tier1 用例全靠 monkeypatch 模块变量 ⇒ 忘记调 setter 则功能永久静默关闭，**没有一条测试会红** |

### 二、会错（观测/审计面值可被随意改动，误导排障）

| ID | 缺口 | 证据 |
|---|---|---|
| GAP-5 | 六个面值零锁：审计 `window_count`、审计 `deliver_after`、日志 `subject_key_hash`/`window_count`/`deliver_after`、skip 回执 `transport` 与 `public_message`、审计 `severity` 取值 | G23 G24 G25 G49 G50 不红；G47b 的红来自 append 抛异常而非查值（PROBE-C 钉死机制：severity 是 RiskLevel 枚举）。全树 grep `window_count`、`subject_key_hash` 在 tests/ **命中 0** ⇒ 全局缺口 |
| GAP-6 | store 故障方向的 reason 机读短语与故障日志块零锁 | G45 改名不红；G46 删整块 `_logger.exception` 不红（只靠 issue.kind 撑可观测） |
| GAP-7 | `test_record_failure_still_allows_and_reports` 的"日志可观测"断言**零消息可辨性**：`assert "outbound_gate" in caplog.text` 被 `exc_info=True` 回溯里的**模块文件路径**喂饱 | G27（消息文本改掉）**59 全绿**；G27b（整条删除）才 RED ⇒ 宣称与实效不符，即"docstring 说 A 面、断言读 B 面"同款 |

### 三、欠账（精度/结构弱点，不改当下正确性）

| ID | 缺口 | 证据 |
|---|---|---|
| GAP-8 | 四处等号边界无锁：全天静默窗（start==end）、同天窗下沿 `<=`、滑窗 `>= since`、prune `< before` | G38 G39 S02 S03 全不红 |
| GAP-9 | `urgent_severities` 含空串 + priority 为空 ⇒ 被当紧急穿窗（保守性反向） | G34 删空串过滤不红 |
| GAP-10 | `test_onebot_protocol_declares_optional_get_msg` 钉声明不钉行为 | O11 的 RED 集恰为 {该条}；行为面另由 O12 锁住 |
| GAP-11 | 该文件 158 行 `segments == [_text_segment(...)]` 与被测实现**同源比对＝恒真子句**（有效锁是 157 行字面量比较） | 逻辑判定；O03 由 157 行抓住 ⇒ 删 158 行零损失 |
| GAP-12 | `test_config_keys_keep_gate_off` 挂 skipif ⇒ 六键若被回退删除，该锁**静默转 skip 而非红**（当前六键已落地、实跑生效非 skip） | 读装饰器 + 基线 59 passed 零 skip |
| GAP-13 | 两条生产接线用例全程用 SimpleNamespace ⇒ 真 `Config()` 的 `bot_outbound_verify_enabled` 缺省值与"worker 开+核验键"组合不在覆盖内 | PROBE-D：真 Config 走线返回 registered=False/disabled，进不到分支 |
| GAP-14 | `_mixed_segment_plan` 的 `sent_types` 观测值只在 docstring 出现，断言未取 | 读用例断言集，无 `sent_types=` |

### 未做注毒的面（诚实申明，非"应该没问题"）

1. 根 `__init__.py` 三处（用例 34、35 的锚点面；tier1 的 16、17）：AGENTS.md #42 明载 **S0-ROOT-c 在飞收编同一文件**，属禁写热面 ⇒ 改用只读 PROBE-1 / PROBE-4 / PROBE-D 判定，结论已入表。
2. `domains/core/contracts/*`（用例 36 与 tier1-8 的枚举主体）：非本席被测实现 ⇒ 以"集合相等比较的不可满足性 + PROBE-B 基数 9 实证"判 A。
3. 用例 23（真队列不另建去重账）：要让它红需给闸**新增**去重账（加功能非改坏），不属最小注毒 ⇒ 判 A 依据是其断言直取真 `SQLiteSendRequestQueue` 的 state 与 `public_message == "duplicate dedupe_key"`，为具体值比较、非自比。

### 撞车预警（给主会话，别当实现退化回滚）

- PROBE-1 实证根 init 直调数**恰等于门槛 5、余量 0** ⇒ 在飞 S0-ROOT-c「根 init 直连收编」落地当天 `test_existing_families_still_submit_directly` **必红**；D1-FIX 若把 `submit_active_push` 引进根 init 同理。这是"改道须显式授权"的 intended tripwire，请预先裁决**改锁口径**还是**暂缓收编**。
- 同一条用例硬路径 `domains/assistant/campus/campus.py`：U17-CAMPUS-WIRE 施工若挪该文件会连带红。

## 6. 本席自纠披露（三处，均已复原）

1. **行尾符覆写（已复原）**：前三批用 `Path.write_text(newline="")` 还原 ⇒ 读入时 CRLF 归一为 LF、写回丢 774 个 CR，`outbound_gate.py` 32271→31497 字节。我原先的 sha 自校验拿"内存中 LF 化字符串"比对自身 ⇒ **该校验当时恒真**（与 D1-FIX 席修掉的 `assert True or …` 同形，本席自犯）。已按 as-found 的 CRLF 形态写回，末态 32271 字节 / CRLF 774 / sha `b3fd4ccf1413`。此后批次全改**二进制读写 + 注毒前与 pristine 字节比对（CONFLICT 即停手）**。
2. **一次还原失败、中毒残留约 2 分钟（已复原）**：O10 注毒后 `write_text` 抛 `OSError[Errno 22]`，文件停在中毒态（`git diff --numstat` = 1/1）。已用 HEAD blob 还原并复验 sha `6a6168c76049` / 54666 字节，与开工快照一致。
3. **`.pyc` 污染（已清）**：只读探针 `d6.py` 那次漏设 `PYTHONDONTWRITEBYTECODE`，其 import 图在树中落下 349 个 `.pyc`。已按 mtime ≥ 本席开工时刻精确清理（349 pyc + 90 空 `__pycache__` 目录），末态 `find plugins tests scripts -name '*.pyc'` = **0**。`.mypy_cache`/`.ruff_cache` 为开工即存的他席产物，本席未跑 mypy/ruff 故未动。
4. **未修改任何测试或实现**：四个文件（两件测试 + 两件实现）`git diff --numstat` 全空；未做任何 git 写操作。

## 7. 收工登记

见文末「签核实跑」段（由收工命令生成）。

## 8. 建议（修由主会话派席，本席未动一行代码）

| 优先 | 建议 | 落点 |
|---|---|---|
| P0 | **GAP-1**：补一条让"四/五段但非 emg 命名空间"的键**唯一地**依赖命名空间规则（如 `foo:bar:baz:qux`），使 G10 型回归必红 | test_outbound_gate.py T5 参数表 |
| P0 | **GAP-2**：白名单加"importer 数 ≥ 1"正向下界（接线落地时）+ 前缀比对改为**目录名精确段**（`relative_to(domains).parts[0] in {transport, emergency_info}`），把 `transport_legacy` 拦在外面 | 同上 T6 |
| P0 | **GAP-3/GAP-4**：一条钉"落账后近 2 小时行不被剪 + `_RETENTION_SECONDS >= 小时窗`"；一条走**真 Config** 的装配用例（`bot_send_queue_worker_enabled=True` + 核验键），锁 setter/confirmer 真路径 | 闸与新增装配面 |
| P1 | **GAP-5/GAP-6**：把六个面值 + degraded reason 短语各加一条精确子串断言（成本极低）；**GAP-7**：日志断言改钉 `record_failure` 短语本体、去掉对回溯路径的隐性依赖 | 两用例文件 |
| P2 | **GAP-8/9/10/14** 各补边界/取值用例；**GAP-11** 删恒真子句（158 行）；**GAP-12** 把 skipif 换成"未落地即红"或加并行 `xfail(strict)` 哨兵 | 同上 |
| 流程 | 全仓推广："已覆盖"必须配一次注毒；`assert X == helper(...)` 且 helper 与被测同源者一律判 C 子句。本席的 `git show HEAD:file` + 二进制还原/校验通道可复用 | AGENTS.md 纪律段 |

### 签核实跑（收工命令生成，可整段复跑）

```
impl sha256[:12] gate   = b3fd4ccf1413 size 32271 CRLF 774
impl sha256[:12] onebot = 6a6168c76049 size 54666 CRLF 0
start-of-session snapshot was: gate 32271/CRLF774 b3fd4ccf1413 | onebot 54666/LF 6a6168c76049
git diff --numstat (4 files: 2 impl + 2 tests, empty = zero modification): ''
audited impl unchanged 14e6480..HEAD: ''
final pytest: 59 passed in 2.79s
HEAD now: ff091dc
porcelain count: 965
stray pyc in tree: 0
stray data/ dir: False
```

**注毒总数 78 次**（精确清点：批 1 G01–G22 = 22 · 批 2 G23–G43 = 21 · 批 3 O01–O10 = 10 · 批 3' O11–O18 + G45–G46 = 10 ·
批 4 G27b/G47/G48/G49/G50 = 5 · 批 5 G47b/G51/G52/G53/G54 = 5 · 批 6 S01–S04 = 4 · 批 7 G55 = 1）。
其中**负控制 17 次全部"没红"**（G10 G23 G24 G25 G26 G27 G34 G38 G39 G43 G45 G46 G49 G50 G52 S02 S03），
构成 §5 缺口清单的正面证据；其余 61 次每次至少抓到一条红。
另有 4 次因模式串写错被判 BADPOISON（S01–S04 首试），**未触碰文件**，修正后重跑即上列批 6。
全部 78 次 `restore=OK`，末态字节与开工快照逐字节相同。
G52（静默窗尾秒/微秒归零被去掉）不红属**不可达型**：`_parse_hhmm` 只产 HH:MM、秒必为 0，故无害，不计入缺口。
