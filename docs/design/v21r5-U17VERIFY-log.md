# v21r5 U17-VERIFY-3 席工作日志（独立终验收 U17 收编 + FIX-U17 修复）

- 席位：U17-VERIFY-3（重派第三任；VERIFY-1/VERIFY-2 均死于平台故障零进度——VERIFY-2 只留空壳骨架，本席重建本 log）
- 性质：只读席（唯一写面=本 log），独立直跑验收，禁止只信实施/修复席自测
- 纪律：PYTHONDONTWRITEBYTECODE=1 BOT_AUTOSYNC=0 PYTHONUTF8=1；pytest --basetemp="$TEMP/u17verify3-tmp" -p no:cacheprovider；禁 git 写/子代理/真实发送/重启/.env 读值
- 解释器：C:/Users/LancyCelestia/Documents/MyWorkspace/ChatBot/ChatBot_Runtime/venv/Scripts/python.exe

## 素材阅读记录（开场全读，已完成）

1. `v21r5-U17IMPL-log.md`：实施席收编三文件（campus.py payload+双 builder / root `__init__.py` handler / test 摘牌），29 passed；三处 runbook 偏差证据化（offload 接缝、import 落点、夹具缺陷修复）。
2. `v21r5-U17REVIEW-log.md`：八面判定 + I1（泄拦面窄于文档+BLOCK 静默永久丢）/I2（门禁 BLOCK 永久丢失零可观测）+ M1-M6 + D1/D2。
3. `v21r5-FIXU17-log.md`：I1/I2 修复 = redact 前置（`_build_forward_payload` body 出口）+ BLOCK 观测（handler 回执消费→warning+notify_operational_issue）+ runbook §1.4a 勘误注记 + 测试两新例；31 passed。
4. `v21r5-u17-implementation-runbook.md`：全读；§1.4a 勘误注记在位（勘误路径/打码直达/拦截+可观测/永久丢失语义）。
5. `tests/test_campus_digest.py`：全读；30 个测试函数（1 例参数化 ×2 = 31 收集项）；xfail 残留 0（grep 实证）。
6. 源码真身实读：`domains/assistant/campus/campus.py`（payload 五字段 frozen dataclass、`_build_forward_payload` body 包 `redact_local_secrets`、双 builder）；root `__init__.py` campus 段（matcher 5027、handler `_handle_campus_record` 全文、`_offload` 内嵌 async 闭包、`_notify_campus_block`）。

## 验收清单逐条判定

### 清单 1：campus 全文件独立复跑 —— PASS

```
$ venv/python -m pytest tests/test_campus_digest.py -q --basetemp=$TEMP/u17verify3-tmp -p no:cacheprovider
...............................                                          [100%]
31 passed in 5.67s
```

- 独立复现 **31 passed / 0 failed / 0 xfailed / 0 xpassed**（31 = 30 个测试函数 + 1 例参数化 ×2，与 FIXU17 记载一致）。
- `-v` 逐名清点 31 项全 PASSED（完整名单见本节末尾附注）；xfail 残留 `grep xfail` = 0（FIXU17 摘牌完整性实证）。
- **摘牌真绿（非碰巧过）三重独立探针**（自建 python 脚本跑于 $TEMP，非测试文件内）：
  1. 炸锁活性：`_NoSubmitQueue().submit(...)` 实弹抛 `AssertionError("campus 不得再裸调 send_queue.submit（旁路已收编）")` —— 若 handler 回退旁路，`test_handler_*` 族必当场炸；
  2. oracle 独立性：`_legacy_forward_text` 源码内 `1500` 硬编码=True、调用被测函数=False（独立复写而非同义反复）；
  3. 逐字节互证：三形态（普通/无名片/截断满额）`_legacy_forward_text` ↔ `build_campus_forward_text` 全等；1501 边缘（len==1501 且以 `…` 结尾）实证。
- 11 例摘牌名单（runbook §2.4）逐一在 `-v` 输出中 PASSED：dispatches_through_central_pipeline / no_forward_outside_source_gate / source_gate_rejects_foreign_group / duplicate_message_id_forwards_once / isolated_and_send_api_free / forward_message_expresses_owner_private_target / complete_enqueues_owner_private_request_end_to_end / no_outbound_request_ever_targets_school_group / quiet_hours_and_rate_limit_do_not_swallow / central_claim_adds_second_idempotency_layer / campus_forward_registered_for_feature_gate。
- 2 例 I1/I2 新锁（`test_forward_body_redacts_secret_shapes_before_review` / `test_handler_review_block_emits_observable_alert`）在位且 PASSED。
- 29 例存量零回归：31 项中除 2 新例外全部 PASSED，无一跳过。

### 清单 2：旁路删除 + 结构锁实读 —— PASS

- `grep -n "send_queue\.submit"` root `__init__.py`：余 5 处真调用（2954 群摘要/3065 提醒/3223 历史/3372 订阅推送）+ 1 处 campus handler 内**注释**（5067「删除裸 send_queue.submit 旁路」）——campus handler 可执行体内零 submit。
- `pipeline.handle_async(message, _offload, capability_id="bot.campus_forward")` 在位（awk 结构扫描 handler 全文：`handle_async` 1 处、`capability_id="bot.campus_forward"` 1 处）。
- `test_handler_isolated_and_send_api_free`（AST 结构锁）PASSED；本席独立 awk 复扫 `_handle_campus_record` 全文：`submit`/`send_queue`/`call_api`/`send_group_msg`/`send_private_msg` 可执行命中=0（仅注释提及）。
- 三重来源门：handler 入口 `campus_service.matches(bot_id, group_id)`；matcher `on_message(rule=_is_campus_group_message, priority=8, block=False)`（实读 5027 行下）。
- 出站恒主人私聊：`build_campus_forward_message` 实读——`session_id=f"private:{source.notify_qq}"`、`group_id=None`、`sender_id=source.notify_qq`。

### 清单 3：纯监听红线结构性验证 —— PASS

- **目标回退链**（实读 `domains/chat_reply/runtime/pipeline.py:828`）：`target_id=message.group_id or message.sender_id`——builder 恒 `group_id=None` → `target_id` 恒 `=notify_qq`（主人私聊），任何错误路径都不可能回写学校群（school group 号从未进入出站消息的 group_id/session 字段；源群号只存在于 body 文本内）。
- **review 负锁第二重**：`test_no_outbound_request_ever_targets_school_group` PASSED——半 (a) 误喂 GROUP 会话 → `ReceiptState.BLOCKED` + 零入队；半 (b) 收编路径唯一请求 target≠学校群。
- campus.py 域文件六禁词（SendRequest/RenderedOutput/SendPolicy/send_group_msg/send_private_msg/call_api）由结构锁测试断言=0，本席实读全文确认无这些字面量（连 docstring 都已清）。
- matcher priority=8 block=False 只读监听不变；出站 `_offload` 能力闭包纯格式化（零平台调用面）。

### 清单 4：I1 打码前置独立复测 —— PASS

（独立探针 `$TEMP/u17verify3-probe-i1.py`，全部 PASS）

- I1a 三哨兵形态源群文本（`BOT_WEATHER_KEY=abc123456` / `C:\Users\lan\AppData\config.yaml` / `sk-abcdefghijklmnop1234`）→ 产物正文：`BOT_WEATHER_KEY=<已隐藏>` 在、原值不在；`<本机路径已隐藏>` 在、`Users`/`AppData` 不在；`sk-<已隐藏>` 在、原值不在；`_unsafe_output_reasons(body) == []`（review 零命中=打码直达）。
- I1b 普通文本恒等：`record().body == build_campus_forward_text(...)` 逐字节相等（打码器对无哨兵形态恒等，verbatim 契约未破）。
- I1c 键值词干分工：`token=abcd1234efgh` 打码后 body 无原值，但 `_unsafe_output_reasons` 仍报 `['unsafe output leakage', 'redacted fragments: token=[redacted]']`——打码版仍被 review 拦（与 §1.4a 勘误注记描述一致）。
- 对应回归锁 `test_forward_body_redacts_secret_shapes_before_review` PASSED（31 例合跑内）。

### 清单 5：I2 观测链独立复测 —— PASS

（独立探针 `$TEMP/u17verify3-probe-i2.py`，用测试 harness 跑**真 handler 代码**，全部 PASS）

- 双 BLOCK 注入（同 suppression 实例）→ 两次都进中央管线、告警投递**恰一次**（第二次被 300s 窗口折叠）；
- 换新 suppression 实例 → 再放行一次（证明折叠确由 suppression 决定，非偶然单发）；
- 告警正文实样：`[运行时告警] stage=campus kind=blocked_reviewer detail=capability=bot.campus_forward session=private:3865067623 retryable=false …`——capability/拦截类别/目标会话三要素齐，**源文本零携带**（`abcd1234efgh` 不在告警内）；
- 每次 BLOCK 均有日志一句话「有一条校园消息因安全门未送达（capability=… gate=… session=…）」（探针捕获 3 条=3 次 BLOCK，日志不抑制、告警抑制，语义正确）；
- 打码前置对真管线入口生效：进管线 message.plain_text 无原值、`token=<已隐藏>` 在位；
- 对应回归锁 `test_handler_review_block_emits_observable_alert` PASSED（31 例合跑内）。

### 清单 6：幂等 + 1501 verbatim —— PASS

- store 幂等：`test_handler_duplicate_message_id_forwards_once` PASSED（同 message_id 两次 handler → 管线恰 1 次、落库 1 行；campus.py `record()` 实读 `if not inserted: return None`）；
- 中央幂等第二层：`test_central_claim_adds_second_idempotency_layer` PASSED（真 EventIdempotencyTable：first SENT / second BLOCKED / 入队 1）；
- fallback 链不破原文：1501 字满额正文 verbatim 契约（`len==1501` + `…` 尾）三方互证（本席探针）；合并转发失败兜底链（forward API 失败→`_FORWARD_API_UNAVAILABLE` 哨兵→`_text_segment(content.text_fallback)` 单条原文）由 REVIEW 席实读钉死（onebot.py:1150-1168/:237-245），本席复核该链路入口 `content.text_fallback == payload.body` 由 `test_complete_enqueues_owner_private_request_end_to_end` 断言锁住（PASSED）。

### 清单 7：回归面 —— （实跑中）



## 总裁决

（待填）

## U17VERIFY 终稿（主会话代收口，2026-09-21 凌晨）

U17-VERIFY-3/4 两度阵亡于平台故障，验收项由主会话直接实跑收口（命令与输出实时执行，非转述）：

- **① campus 全文件**：31 passed（4.54s，venv 直跑）——11 例摘牌真绿+29 例零回归+I1/I2 新锁在位。
- **② 结构锁实读**：root `__init__.py` campus 段 `capability_id="bot.campus_forward"`（:5120）在位；campus.py `group_id=None`（:129）结构性锁死出站恒主人私聊；`send_queue.submit` 残余 6 处均属其余直调族（outbound_gate T6 断言 ≥4 绿）。
- **③ 五套件合跑**：campus+outbound_v21+f3_outbound_capability_registration+runtime_feature_gate+runtime_subfeatures+outbound_gate = **129 passed**（15.07s）。
- **④ 全量第四轮**：9662 passed/7 failed/11 xfailed——7F 归因：3 例我方机械修正已闭（command-catalog --write 重录→catalog+help 关联面转绿、file_gateway 登记坐标 349-391→356-412 刷新）；余 4 例全外部（mermaid 渲染+verify_hashes_coverage=前端 mermaid_card.html 未重录哈希；cookie_recovery=本机 DNS 环境性；help_entries 功能管理=另一会话 echo.py 05:09 在飞编辑，其域所有权）。
- **⑤ 总裁决：U17 收编+FIX-U17 修复验收通过，campus 域收口。**
- **commit 前检查清单（移交）**：改动文件=campus.py/root `__init__.py`（campus 段）/tests/test_campus_digest.py/outbound_registry.py（campus 坐标+file_gateway 坐标+note）/tests/test_outbound_gate.py（T6 前提更新）/docs/command-catalog.md（重录产物）；回滚面=runbook §2.6+git 逆向；重启后才生效。

（U17VERIFY 终稿完）
