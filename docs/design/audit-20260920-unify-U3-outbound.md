# 统一性审查 · 席位 U3-OUTBOUND（出站/发送统一）— 2026-09-20

> 只读审计席。审计对象=**当前工作树**（全树未 commit，含前端/TTS/控制面在飞面）。
> 本席未改任何代码/配置/文档，未跑全量 pytest，未做任何 git 写操作，未真实发送、未重启、未杀进程。
> 唯一产出=本文件。所有坐标为**本席实读现值**（不采信文档行号）。

---

## 〇、一页结论

**席位名**：U3-OUTBOUND 出站/发送统一
**发现总数**：16（P1×3 · P2×7 · P3×6）
**核心判定**：出站**并非**单一咽喉。当前工作树存在 **4 类互不相同的出站出口**（SendQueue 统一管线 / 统一副作用执行器 / 通道本体直调 / 完全旁路），其中：

1. **P1 两条是同一根因**：`RuntimePipeline` 新接的 `feature_gate` 对**未登记 capability_id 一律 fail-closed 拒绝**，而统一管线 helper 的缺省 capability_id `bot.file` 与 S0 收编新造的 `bot.group_welcome`/`bot.cookie_login`/`bot.cookie_expiry_notice` **四个全部未登记**。后果：**管理端 21 处出站文案今日即被静默吞掉**（门关也吞，因为吞的是投递段不是队列段），且 **S0 四处门只要拨开，对应功能整链哑掉**。scoped 测试 126 项全绿，因为它们把 `_run_capability_through_pipeline` 整个 spy 掉了 → 典型假绿。
2. **P1 第三条**：part 级 UNKNOWN 确认协议（`unknown_part_confirmer`）**生产零接线**，唯一回退路（`provider_message_id`）**在 UNKNOWN 路径上从不写入** → 结构不可达。「UNKNOWN 走确认、绝不盲重发」这条对外承诺的可靠性契约，实际形态是「UNKNOWN 永久休眠、永不确认」。
3. **登记表自身不可信**：`outbound_registry.direct_sends` 12 条条目 **23 处坐标失效**（含把 CHANNEL_BODY 钉在 12 行的 compat shim 上），而所谓「陈旧坐标棘轮」只断言 `location` 字串子串 → **恒真门**，实测 23 处失效仍 126 passed。

**同时，以下经取证确认是好的**（§九 逐项给证据，不含糊）：part 幂等键单源、A-22 内联认领台账、onebot「有副作用即不整体重投」四道守卫、prune 不淘汰非终态行、四门缺省 False、门关分支对 S0-ROOT-c diff 逐字节等价（一处例外见 U3-06）、文件出站单路径（无死码双实现）。

### 严重度分布表

| 严重度 | 数量 | 编号 |
|---|---|---|
| P1 | 3 | U3-01 · U3-02 · U3-03 |
| P2 | 7 | U3-04 · U3-05 · U3-06 · U3-07 · U3-08 · U3-09 · U3-10 |
| P3 | 6 | U3-11 · U3-12 · U3-13 · U3-14 · U3-15 · U3-16 |

---

## 一、全树直连点清单（绕过统一出站面全枚举）

扫描式样（plugins/ + scripts/ + bot.py + webui/ + third_party/）：
`send_group_msg|send_private_msg|upload_group_file|upload_private_file|set_msg_emoji_like|set_message_reaction|delete_msg|send_forward_msg|call_api|\.send\(|\.finish\(|send_mail|push_serverchan|push_pushplus|send_document`
证据来源=本席 Grep 全树 + 逐条读码判定，非文档转录。

| # | 坐标 文件:行 | 锚点字符串 | 分类 | 备注 |
|---|---|---|---|---|
| 1 | `plugins/bot_unified_runtime/__init__.py:4446` | `await bot.call_api(` + `"send_private_msg",` | **门关旧直连（有意保留）** | 门 `bot_cookie_expiry_reminder_via_queue`（config.py:747，缺省 False） |
| 2 | `__init__.py:5385` | `await bot.call_api(` + `"send_group_msg",` | **门关旧直连（有意保留）** | 门 `bot_group_welcome_via_queue`（config.py:658，缺省 False） |
| 3 | `__init__.py:5737` / `:5743` | `"send_group_msg",` / `"send_private_msg",` | **门关旧直连（有意保留）** | 门 `bot_cookie_qr_via_queue`（config.py:748，缺省 False），双通道 |
| 4 | `__init__.py:5533` / `:5540` | `"upload_group_file",` / `"upload_private_file",` | **门关旧直连（有意保留）** | 门 `bot_file_export_via_queue`（config.py:760，缺省 False） |
| 5 | `__init__.py:4985` | `await bot.call_api("delete_msg", message_id=message_id)` | **完全旁路（缺陷）** | 无门、无 executor、无回执、无审计 → U3-10 |
| 6 | `__init__.py:5352` | `bot.call_api("get_group_member_info",` | 读路径 | 非出站 |
| 7 | `__init__.py:1054`·`:1150`·`:2232`·`:5431`·`:5435`·`:8075` | `call_api("get_forward_msg"` / `"get_record"` / `"get_stranger_info"` / `"get_file"` / `"download_file"` | 读路径 | 登记表 READ_PATH 条目对应真身（登记坐标全失效 → U3-04） |
| 8 | `__init__.py:3900-3904` | `return await send_onebot_v11(bot, request)` | **旁路（通道本体直调）** | `_deliver_admin_alert`：绕 SendQueue → U3-07 |
| 9 | `__init__.py` × 37 处（5636·5639·5867·5874·5938·6147·6398·6435·6484·7211·7247·7723·7741·7803·7809·7860·7866·7909·7912·7956·7961·8013·8017·8172·8176·8189·8231·8234·8241·8252·8259·8373·8394·8557·8615·8629 …） | `await <matcher>.finish(receipt.public_message)` | **旁路（用户可见文本）** | 受 `should_finish_nonebot_matcher`（:2276-2286）门控，SENT/operational_issue 不发 → U3-11 |
| 10 | `__init__.py:3052`·`:3210`·`:3357`·`:5029` | `send_queue.submit(request)` | **走统一队列** | ①cookie 门开 / 群摘要 / 每日助理 / 校园转发 |
| 11 | `__init__.py:2472` | `receipt = await gateway.deliver(bot, event, send_request)` | **走统一队列（内联投递段）** | `UnifiedDeliveryGateway`，19 处 `_deliver_transport_send_request` 汇聚于此 |
| 12 | `domains/ops/monitor/disconnect_notice.py:188` | `await send_mail_from_account(` | **完全旁路（缺陷）** | 绕队列/回执/审计 → U3-14 |
| 13 | `disconnect_notice.py:158`·`:168` | `push_serverchan,` / `push_pushplus,` | **完全旁路 + 注册表外渠道** | TransportRegistry 无 ServerChan/PushPlus 平台条目 → U3-14 |
| 14 | `disconnect_notice.py:178` | `sent = await notify_telegram_admins(` | **完全旁路（缺陷）** | 与 #12 同函数族 |
| 15 | `domains/transport/mail/mail_bridge.py:450` | `await send_mail_from_account(` | **完全旁路（缺陷）** | `/mail send` 管理命令 → U3-14 |
| 16 | `domains/transport/mail/mail_bridge.py:346` | `await target.send_mail(message)` | 通道本体 | mail 第二实现的底层 |
| 17 | `domains/transport/sender/onebot.py:480·485·505·513·582·590·619·624·979` | `bot.send_group_msg(` / `bot.send_private_msg(` | 通道本体（合法） | SendQueue worker 与内联投递的唯一 QQ 出口 |
| 18 | `domains/transport/sender/nonebot.py:495` | `return await bot.send(event, remaining, **kwargs)` | 通道本体（合法） | TG/Mail 等 |
| 19 | `domains/transport/sender/file_gateway.py:366·369·377·382·425` | `api = "upload_group_file"` / `await bot.send_document(` | 通道本体（合法） | 统一文件出站唯一实现 |
| 20 | `control_plane/dispatcher.py:200` | `await target_bot.call_api(method, **params)` | **统一副作用出站面通道本体（合法）** | poke/reaction 共用；方法名固定映射，不拼接 |
| 21 | `domains/meme/reactions/engine.py:760`·`:800` | `result = await _REACTION_OUTBOUND_SERVICE.handle(` | **已收编统一面（合法）** | executor 装配 engine.py:664 |
| 22 | `domains/chat_reply/capabilities/group_info.py:146` | `coro = bot.call_api(action, **params)` | 通用透传 sink | 动作面宽，DISPATCH-001 单列（本席不重复记账） |
| 23 | `domains/media/video/video_pipeline.py:72·74`、`domains/media/ingest/telegram_media.py:133` | `payload = await bot.call_api("get_msg",` / `bot.call_api("get_file",` | 读路径 | 真身（登记表仍指 `runtime/`·`sources/` shim → U3-04） |
| 24 | `domains/ops/integrations/gscore_bridge.py:257` | `await ws.send(json.dumps(payload, ensure_ascii=False))` | 非聊天出站（外部服务集成） | 但自带第二套迷你队列 `self._queue`+`_flush_queue`，零幂等零审计 → U3-16 |
| 25 | `domains/ops/smoke/smoke.py:1304·1310` | `async def send_private_msg(self, **_kwargs` | 测试假 bot | 非生产 |
| 26 | `scripts/e2e_acceptance.py:1579·1582` | `action = "send_group_msg"` | 验收脚本 payload 构造 | 缺省 DRY-RUN 只构造；`--execute` 走 SnowLuma HTTP 侧，不经 bot → 归类「外部注入面，不计入绕过」 |
| 27 | `third_party/astrbot_plugin_meme_manager/mixins/event_handlers.py:1563` | `await self.context.send_message(...)` | **死参照件**（未加载） | `bot.py`/`plugins/`/`scripts/` 全域零 `astrbot` 引用（本席 grep 实证）→ U3-16 |

**清点结论**：真正的「完全旁路」= #5（撤回）、#8（管理告警）、#12-15（掉线通知三渠道 + `/mail send`）。#9（37 处 `.finish()`）= 半旁路（受门控的失败回执）。#1-4 = 门关旧直连，**与 S0 收编书声明一致**。

---

## 二、S0 四处收编真伪与等价性核验（逐项）

统一核验口径：门键名与缺省值 / 门关分支是否与旧行为逐字节等价 / 门开是否真走 SendQueue 且 SENT·REDIRECTED 判定 / 幂等键是否含日期 / 失败面是否落 result_unknown·告警。

| 处 | 门键（缺省） | 门开是否真走队列 | SENT/REDIRECTED 判定 | 幂等键含日期 | 门关逐字节等价 | 失败面落 result_unknown/告警 |
|---|---|---|---|---|---|---|
| ① cookie 到期 | `bot_cookie_expiry_reminder_via_queue`（False，config.py:747） | 是（`_deliver_cookie_expiry_report_via_queue` :2980 → `submit` :3052 → 内联 `deliver` :3060） | 是（:3069-3073） | **是**（`request_id` :3016 + `dedupe_key` :3043 均带 `today`） | **否**（U3-06） | **否**（U3-13） |
| ② 入群欢迎 | `bot_group_welcome_via_queue`（False，config.py:658） | 是（`_send_text_through_unified_pipeline` :5371 → pipeline → submit） | 是（:5379） | 不适用（事件级一次性，无日期键） | 是 | 是（pipeline 内联 `_notify_operational_receipt`）但**被 U3-02 门吞** |
| ③ 二维码图片 | `bot_cookie_qr_via_queue`（False，config.py:748） | 是（`_send_parts_through_unified_pipeline` :5716） | 是（:5724-5731） | 不适用 | 是 | 同 ② |
| ④ 文档导出上传 | `bot_file_export_via_queue`（False，config.py:760） | 是（`_send_files_through_unified_pipeline` :5508，`files`→`FileTransferGateway`） | 是（:5516-5519） | 不适用 | 是 | 是（失败落文案 :5527）但**被 U3-02 门吞** |

四门缺省 False 已实读 config.py:658/747/748/760 逐一确认 → **重启不拨门 = 生产零变更** 这条成立（但见 U3-01：`_send_text_through_unified_pipeline` 的**投递段**已被在飞 feature_gate 影响，与门无关）。

### U3-01 ｜ P1 ｜ feature_gate 对未登记 capability_id 一律拒绝，21 处统一管线文案今日静默不发

- **坐标**：`plugins/bot_unified_runtime/domains/ops/features/feature_gate.py:57-59`（判定）+ `plugins/bot_unified_runtime/__init__.py:4811`（缺省 `capability_id: str = "bot.file"`）+ 21 个未显式传 capability_id 的调用点（AST 枚举：5450·5453·5457·5487·5491·5500·5527·5547·5549·5658·5662·5680·5684·5686·5696·5703·5753·5759·5765·5771·5780）
- **锚点**：`return FeatureAccess(False, "feature_unregistered")`
- **根因**：`ProductFeatureGate.__call__` 对不在 `capability_feature_bindings()` 内的 capability_id 直接判否；`pipeline._prepare`（pipeline.py:484-500）据此返回 `ReceiptState.BLOCKED` 并**在入队之前**结束，`public_message="这项功能暂时不可用。"`。而 `_send_text_through_unified_pipeline` 的缺省 capability_id 是 `bot.file`，该 id **既不在 `ROUTE_CAPABILITY_DECLARATIONS`（有 rule 者）也不在 `CONTROLLED_INTERNAL_CAPABILITIES`**（实跑枚举 69 条绑定，`bot.file` 缺席）。21 处调用点在 cookie/file_export 分支里**从不 `finish()` 兜底**（如 :5696-5700 `await _send_text_through_unified_pipeline(...)` 后直接 `return`）→ 用户/管理员端**一个字都收不到**。
- **证据**（本席实跑）：
  ```
  bot.file                   allowed=False reason=feature_unregistered
  bot.group_welcome          allowed=False reason=feature_unregistered
  bot.cookie_login             allowed=False reason=feature_unregistered
  bot.cookie_expiry_notice   allowed=False reason=feature_unregistered
  ```
  （探针：直调 `ProductFeatureGate.__call__`；`bot.chat`/`bot.poke` 因已登记而**越过**该行、进到 `service.detail`，反证判定分支只对未登记 id 生效。）
  AST 统计：`total pipeline-helper call sites = 27`，`without explicit capability_id = 21`。
  归因：`git show HEAD:plugins/bot_unified_runtime/__init__.py | grep -c "_send_text_through_unified_pipeline"` = **22**（HEAD 已有该批调用点），而 `git show HEAD:...__init__.py | grep "feature_gate=product_feature_gate"` = **空** → **本缺陷由在飞未 commit 的控制面/feature-gate 席引入，非 S0-ROOT-c 引入**；`RuntimePipeline.__init__` 缺省 `feature_gate=None`（pipeline.py:396）佐证 HEAD 无此门。
- **改法 before→after**：
  before：`feature_gate.py:58-59` 未登记即 `FeatureAccess(False, "feature_unregistered")`
  after（二选一，建议 A）：
  A. 把 `bot.file`/`bot.group_welcome`/`bot.cookie_login`/`bot.cookie_expiry_notice` 补进 `CONTROLLED_INTERNAL_CAPABILITIES`（feature_catalog.py:15 同款登记），使 `capability_feature_bindings()` 覆盖之；
  B. 或 `_send_text_through_unified_pipeline` 缺省值改成一个**已登记** id（如 `bot.poke` 那样在表内的系统投递 id），并对 21 处调用点逐个显式传正确 capability_id。
  另需独立决策（不在本条修法内）：未登记是否应 **fail-open**（见 U3-03 附注的 fail-closed 面）。
- **验证命令**：
  ```
  PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "%TEMP%/u3_probe_blocked_caps.py"
  # 期望：BLOCKED by feature gate = 0（当前 = 4）
  ```
  并补一条常驻门：遍历 `__init__.py` 内全部 `capability_id="..."` 字面量 ∧ 三个管线 helper 缺省值，断言 ⊆ `capability_feature_bindings()`。

### U3-02 ｜ P1 ｜ S0 门开②③④ 必被 feature_gate 吞 → 拨门即整功能静默失效，且 126 项 scoped 测试全绿=假绿

- **坐标**：`__init__.py:5375`（`capability_id="bot.group_welcome"`）· `:5722`（`"bot.cookie_login"`）· `:5512`/`:5524`（`"bot.file"`）；判定链同 U3-01（feature_gate.py:57-59 → pipeline.py:489-500）
- **锚点**：`capability_id="bot.group_welcome"`
- **根因**：S0 收编把三条出站塞进 `RuntimePipeline`，但选定的 capability_id 三个全部未登记 → 门开即 `BLOCKED`，`_send_*_through_unified_pipeline` 返回的 receipt 永不可能是 SENT/REDIRECTED。②的后果是欢迎语消失且 `group_welcome_sent` 永不记（:5379 判空返回）；③是二维码图片消失（文本兜底仍在）；④最重——门开分支的成功回执走 :5520（`bot.file`，BLOCKED）、失败回执走 :5527（缺省 `bot.file`，也 BLOCKED）→ **文件上传成功与否管理员都收不到任何文案**。
- **证据**：U3-01 探针输出四行 `allowed=False reason=feature_unregistered`；`scoped` 测试实跑 `126 passed in 8.42s`（`tests/test_v21_s0_root_collect.py tests/test_v21_s0_collect.py tests/test_outbound_v21.py tests/test_part_idempotent_resume.py tests/test_v21_dispatch_outbound_wiring.py`）——而 `tests/test_v21_s0_root_collect.py:268` 写着 `_run_capability_through_pipeline=_fake_run`、`:208-209` 把 `_send_files_through_unified_pipeline`/`_send_text_through_unified_pipeline` 整体换成 spy → **真实 pipeline 与 feature_gate 从未进入被测路径**，故 27 例「全绿」不能证明门开可用。
- **改法 before→after**：
  before：门开分支 capability_id = `bot.group_welcome` / `bot.cookie_login` / `bot.file`（未登记）
  after：三 id 登记进 `CONTROLLED_INTERNAL_CAPABILITIES`（连带进 feature_catalog → `capability_feature_bindings()` 覆盖）；`bot.file` 建议同时改名 `bot.file_export` 以免与 `/bot download` 域混淆，或复用既有 `bot.download`。
  **并且**：把 `tests/test_v21_s0_root_collect.py` 的门开用例从「spy 掉管线 helper」升级为「真 `RuntimePipeline(feature_gate=ProductFeatureGate(stub))` + 断言 receipt.state ∈ {SENT,REDIRECTED}」，否则门开仍无真回归覆盖。
- **验证命令**：
  ```
  PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "%TEMP%/u3_probe_blocked_caps.py"   # 期望 0
  ../ChatBot_Runtime/venv/Scripts/python.exe -m pytest tests/test_v21_s0_root_collect.py -q --basetemp="$TEMP/u3-verify-$$" -p no:cacheprovider
  ```

### U3-03 ｜ P1 ｜ part 级 UNKNOWN 确认协议生产零接线，唯一回退路结构不可达

- **坐标**：`__init__.py:1649-1656`（`drain_send_queue_once(...)` 未传 `unknown_part_confirmer`）；`domains/transport/sender/worker.py:217`（参数定义）、`:780-785`（两级确认）、`:833-835`（`mark_part_unknown` 不写 provider_message_id）；`domains/transport/sender/queue.py:1147-1153`（形参存在但无人传）
- **锚点**：`unknown_part_confirmer: UnknownPartConfirmer | None = None,`
- **根因**：worker 的 UNKNOWN 恢复有两条路——(a) `record.provider_message_id` 非空即判已送达；(b) 注入 confirmer 主动问平台。生产中：`mark_part_unknown` 调用点只传 `error_kind`，UNKNOWN 行按定义拿不到 provider_message_id ⇒ (a) **结构不可达**；(b) 全树仅 `tests/test_part_idempotent_resume.py:210·299` 传参，`grep -rn "unknown_part_confirmer" plugins/ scripts/` 除 worker 自身外**零命中** ⇒ (b) 不存在。结论：任何 part 进入 UNKNOWN，该请求永久停摆为 PARTIAL 休眠行（见 U3-12），对外宣称的「UNKNOWN 确认」实为「UNKNOWN 搁置」。
- **证据**：
  ```
  $ grep -rn "unknown_part_confirmer|UnknownPartConfirmer|confirm_part_delivered|can_confirm_unknown_parts" plugins/ scripts/ tests/
  plugins/.../domains/transport/sender/worker.py:50,217,686,737,782,784
  plugins/.../__init__.py:（无命中）
  tests/test_part_idempotent_resume.py:210: unknown_part_confirmer=confirmer,
  tests/test_part_idempotent_resume.py:299: unknown_part_confirmer=confirmer,
  ```
  配合 §一 表 #11：生产 `drain_send_queue_once` 恰有一处调用（`__init__.py:1649`），实参清单里无 confirmer。
- **改法 before→after**：
  before：`drain_send_queue_once(send_queue, transport, receipt_repository=…, audit_logger=…, limit=batch_size, operational_notifier=…)`
  after：追加 `unknown_part_confirmer=_make_onebot_unknown_part_confirmer(bot_provider)`——OneBot 侧用既有 `get_msg`（真身 `domains/media/video/video_pipeline.py:72` 已在用该 API，能力现成）按 `dedupe_key`/时间窗反查是否已出现本 bot 消息；**Mail/Telegram 无对等查询 API，如实注册为「不可确认」并显式终态化**（不得沿用休眠）。同时把 `mark_part_unknown` 调用点补传 `provider_message_id=receipt.provider_message_id`（形参已存在），让 (a) 通道在「平台已回 id 但结果不可判」的场景下可用。
- **验证命令**：`pytest tests/test_part_idempotent_resume.py -q --basetemp="$TEMP/u3-unknown-$$" -p no:cacheprovider` + 新增断言：`_register_send_queue_scheduler` 装配出的 job 闭包含 confirmer（可用 AST 门：`assert "unknown_part_confirmer" in ast.unparse(...)`）。

### U3-05 ｜ P2 ｜ S0① 丢弃队列 SKIPPED 回执，当日幂等单腿依赖回执仓

- **坐标**：`__init__.py:3051-3058`（`send_queue.submit(request)` 返回值丢弃 → `_find_sent_request(...)` → `deliver(...)`）；`domains/transport/sender/queue.py:474-476`（`ON CONFLICT DO NOTHING` → `skipped_receipt`）；`queue.py:502-507` + `:1680-1699`（`find_request` **不按 state 过滤**）
- **锚点**：`send_queue.submit(request)` / `sent_request = _find_sent_request(send_queue, request_id) or request`
- **根因**：队列已用 `dedupe_key` 主键给出权威答案（`SKIPPED`），但调用方不看它，转而**用回执仓做前置判定**（:3017-3026 `receipt_repository.latest(request_id)`）。`find_request` 会按 request_id 命中那行**已 SENT 的记录**并原样返回请求体，于是 `deliver()` 第二次真实投递。防线只剩三条间接条件：回执仓启用（`bot_receipts_enabled` 缺省 **False**，config.py:204）、SQLite 落盘、`record()` 未抛异常。生产 `.env` 实测 `BOT_RECEIPTS_ENABLED=true`/`BOT_RECEIPTS_DB_PATH=…`，故**今日不成灾**；但 `BOT_RECEIPTS_MAX_ITEMS=1000` 有 prune（receipts.py:182/:303），且缺省配置（未显式开回执仓的部署/测试环境）下这条幂等**完全失效**。cron `misfire_grace_time=600`（:4465）+ 重启补触发正落在同一天窗口内。
- **证据**：上述四处代码摘录 + `grep -n "bot_receipts_enabled" config.py:204` → `bool = False`。
- **改法 before→after**：
  before：
  ```
  try:
      send_queue.submit(request)
  except Exception:
      ...continue
  sent_request = _find_sent_request(send_queue, request_id) or request
  ```
  after：
  ```
  queued = send_queue.submit(request)
  if queued.state is ReceiptState.SKIPPED:
      return True          # 队列权威判重：当日已受理，绝不再投递
  sent_request = _find_sent_request(send_queue, request_id) or request
  ```
  并把回执仓判定降级为**第二道**（可选）而非唯一道。
- **验证命令**：`pytest tests/test_v21_s0_root_collect.py -q --basetemp="$TEMP/u3-dedupe-$$" -p no:cacheprovider`，新增用例：`receipt_repository=None` + 同日二次调用 ⇒ 断言 `deliver` 只被调一次。

### U3-06 ｜ P2 ｜ S0① 门关/门开非逐字节等价：非数字管理员 id 时新路径整份丢弃、旧路径换人重试

- **坐标**：`__init__.py:4444-4456`（门关：per-admin `try`，`user_id=int(admin_id)` 在 try **内**）vs `:3027-3050`（门开：`target_id=str(int(admin_id))` 在 `SendRequest(...)` 构造里，即 try **外**；:3051 的 `try` 只包 `submit`）；冒泡出口 `:4439-4443`（`except Exception:` → `logger.debug` → `return`）
- **锚点**：`target_id=str(int(admin_id)),`
- **根因**：门关语义 = 单个管理员 id 不可 int 化 → `continue` 换下一个；门开语义 = 同一异常在函数体内抛出，穿过 :4439 的捕获后**整份报告放弃**，后续管理员一个都收不到。收编书「门关保留旧路径逐字节等价」只约束了门关分支（成立），未约束门开与原行为等价，但拨门验收会踩到。
- **证据**：上文坐标对照摘录（`break`/`continue` 结构差异）。
- **改法 before→after**：把 `:3027` 起的 `SendRequest` 构造并入 per-admin `try`（或将 `int(admin_id)` 前置为 `try: numeric = int(admin_id) except (TypeError, ValueError): continue`），使「脏 id」只跳过该收件人。
- **验证命令**：`pytest tests/test_v21_s0_root_collect.py -q --basetemp="$TEMP/u3-adminid-$$" -p no:cacheprovider`，新增用例：`admins=["abc", "123"]` ⇒ 断言第二个仍被投递、返回 True。

> **交叉索引**：本表相关但成文于后文的发现——U3-07（管理告警绕队列，§六）、U3-13（S0① 失败面不落 result_unknown，§四）、U3-04（登记表坐标失效，§三）。共 16 条（P1×3 / P2×7 / P3×6）。

---

## 三、outbound_registry 登记表实况核验（item 3）

被验对象：`domains/core/decision/outbound_registry.py` `build_default_takeover_registry().direct_sends`（12 条）。
方法：本席写只读探针 `%TEMP%/u3_probe_registry.py`，把每条 `location` 解析为 `文件:行/区间`，逐坐标读实际行文本，断言是否命中被登记的 API 字面量（`send_group_msg`/`upload_*_file`/`delete_msg`/`set_msg_emoji_like`/`call_api`/`get_*`）。

```
RESULT: coordinate problems = 23
```

| 条目 location（登记值） | 登记状态 | 实跑判定 | 结论 |
|---|---|---|---|
| `__init__.py:4440-4444` `send_private_msg` | BYPASS_SUSPECT 已收编 | **[MISS]** 该区间实文 = `logging.getLogger(__name__).debug(` / `"cookie expiry notice via queue failed", exc_info=True` / `)` / `return` / `for admin_id in admins[:3]:` | 坐标错位（真身 :4446-4450，偏 6 行）；**登记文本本身（门键/测试/语义）为真** |
| `__init__.py:5378-5382` `send_group_msg` | BYPASS_SUSPECT 已收编 | **[MISS]** 实文 = `return` / `if receipt.state in {ReceiptState.SENT,` / `_log_runtime_event(` | 坐标错位（真身 :5385-5389，偏 7 行）；语义为真 |
| `__init__.py:5730-5740` | BYPASS_SUSPECT | **[OK]** L5737 命中 | 区间未覆盖 `send_private_msg`（真身 :5743），半 stale |
| `__init__.py:5526-5538` | BYPASS_SUSPECT | **[OK]** L5533 命中 | 区间未覆盖 `upload_private_file`（真身 :5540），半 stale |
| `__init__.py:4978` `delete_msg` | BY_DESIGN | **[MISS]** 实文 = `text = event.get_plaintext().strip()` | 真身 :4985，偏 7 行 |
| `control_plane/dispatcher.py:162-220` | BY_DESIGN（已收编 L34） | **[OK]** L200 `await target_bot.call_api(method, **params)` | 真 |
| `domains/meme/reactions/engine.py:754-782` `set_msg_emoji_like` | BY_DESIGN（已收编 L35） | **[MISS]** 区间内是 `react_to_message` 函数体，**无 API 字面量** | 判定正确（收编后字面量只存注册表），但 evidence 串把该区间描述为含 API → 描述与实文不符 |
| `domains/meme/reactions/engine.py:785-813` | BY_DESIGN | **[OK]** L793 docstring 命中 | 真（docstring 自述「未接线触发点」） |
| `domains/transport/sender/file_gateway.py:349-391` | CHANNEL_BODY | **[OK]** L359 注释命中，call_api 在 :382 | 真 |
| `sender/onebot.py:444,449,469,477,546,554,583,588,962` | CHANNEL_BODY | **[OUT OF RANGE] ×9** 文件仅 **12 行**（compat shim） | **假绿实锤**：唯一合法 QQ 通道本体的登记坐标指向 12 行垫片；真身 `domains/transport/sender/onebot.py` 的对应点在 480/485/505/513/582/590/619/624/979 |
| `capabilities/group_info.py:146` | READ_PATH | **[OUT OF RANGE]** 文件仅 **18 行**（shim） | 真身 `domains/chat_reply/capabilities/group_info.py:146` |
| `__init__.py:949,1014,2059,4924,4928,7468 + runtime/video_pipeline.py:72,74 + sources/telegram_media.py:133` | READ_PATH | **[MISS] ×6 + [OUT OF RANGE] ×3** | 9 个坐标全废：真实读点在 :1054/:1150/:2232/:5431/:5435/:8075；`runtime/`、`sources/` 为 18 行 shim（真身 `domains/media/video/video_pipeline.py`、`domains/media/ingest/telegram_media.py`） |

### U3-04 ｜ P2 ｜ 登记表 12 条中 23 处坐标失效，「陈旧坐标棘轮」为恒真门

- **坐标**：`domains/core/decision/outbound_registry.py:602-714`（direct_sends 全表）+ `tests/test_outbound_v21.py:693-696·708-713·717`（所谓棘轮）
- **锚点**：`assert any("4440" in e.location for e in suspects)`
- **根因**：棘轮全部形如「`location` 字符串是否含某字面量」，**从不回读源文件校核坐标**。因此：(a) 四条门坐标错位照样绿；(b) `test_outbound_v21.py:717 assert any("sender/onebot.py" in e.location for e in bodies)` 把 **shim 路径钉成契约**，与同批 REG-REFRESH 对其他条目「shim 旧路径清零」的收编方向**正好相反**；(c) `:711 assert "4978" in coordinates` 把已被自己写歪的行号锁死。REG-REFRESH 书声称「四条坐标 grep 实读刷新」，实际刷新值与本席 grep 值各偏 6-7 行 → 刷新动作做了但没校核闭环。
- **证据**：本席探针整表输出（上文 表格 + `RESULT: coordinate problems = 23`）；同一次运行里 `pytest tests/test_outbound_v21.py ...` → **126 passed**（绿与 23 处失效并存 = 门恒真的直接证明）。
- **改法 before→after**：
  before：`assert any("4440" in e.location for e in suspects)`（子串断言）
  after：把本席探针**收编为常驻测试**（`tests/test_outbound_registry_coordinates_are_live.py`）：解析每条 `location` → 打开 `PKG/路径` → 断言 ①文件存在且行数 ≥ 登记行号 ②该行或 ±3 行窗口含条目 `api` 字面量 ③路径不在 compat-shim 白名单（≤20 行且首行含 `Compat shim:`）内；shim 路径一律判红。同时把 `:717` 改为 `domains/transport/sender/onebot.py`、`:711` 改 `4985`、四条门坐标改 4446/5385/5737(+5743)/5533(+5540)。
  （注：行号型坐标天然易漂。更稳的登记形态 = `文件 + 函数名 + 符号锚`，行号仅作辅助，棘轮按符号判。）
- **验证命令**：`PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "%TEMP%/u3_probe_registry.py"`（收编后等价：`pytest tests/test_outbound_registry_coordinates_are_live.py -q --basetemp="$TEMP/u3-coord-$$" -p no:cacheprovider`，期望 `coordinate problems = 0`）

**「已登记为已收编但代码仍直连」的假绿专项结论**：四条 `*_via_queue` 门**没有**假绿——门关旧直连确实在、门开确实走队列（§二 逐条读码），只是门开被 U3-02 的 feature_gate 吞掉，属另一类缺陷。真正的假绿在别处：**登记表的坐标/证据串**（本条）与 **S0 测试的管线 spy**（U3-02 证据段）。

---

## 四、SendQueue 语义一致性（item 4）

### 4.1 part 级幂等键是否单源 —— **是（无缺陷，取证见 §九-F1）**
`queue.py:104-106` `_part_key(request_id, part_index) -> f"{request_id}#part{int(part_index)}"` 是全树唯一生成点；全库引用仅 queue.py 内部两处（:1070 写、:1219 更新）。worker/onebot/gateway **零** 自算 part 键。

### 4.2 UNKNOWN 确认是否所有通道都实现 —— **否，一个都没实现**
见 **U3-03（P1）**。逐通道补充取证：
- **OneBot**：具备确认能力（`get_msg`，真身已在 `domains/media/video/video_pipeline.py:72` 使用），但无人注册 confirmer；
- **Telegram**：成功路径有 `provider_message_id`（`domains/transport/sender/nonebot.py:614 provider_message_id=_provider_message_id(result)`），但**无按 id 反查消息的读 API** → 结构上不可确认，需显式声明而非休眠；
- **Mail**：`send_mail_from_account`（mail_bridge.py:312-346）返回 `None`，成功与否只靠「没抛异常」，`provider_message_id` 恒缺 → 三通道里最弱。

### U3-12 ｜ P3 ｜ UNKNOWN 造成的 PARTIAL 休眠行：永不 prune、无人可推
- **坐标**：`queue.py:1344-1396`（`mark_partial(resumable=False)` → `next_retry_at = None`）、`queue.py:1630-1651`（`_prune` 只删 `sent`/`failed_final`/`skipped`，**不含 `partial`**）、`queue.py:1095`（`list_partial_requests` 定义）
- **锚点**：`DELETE FROM send_requests WHERE state IN (?, ?, ?)`
- **根因**：PARTIAL 与 QUEUED/PROCESSING/FAILED_RETRYABLE 同属「非终态不淘汰」（该取舍本身正确：A4 宁超限不丢在途）。但配合 U3-03（永不可确认），这些行成为**只增不减的死信表**；且 `list_partial_requests` 生产消费者为 0（`grep -rn list_partial_requests plugins/ scripts/` 仅命中定义与 docstring；唯一消费者是 `tests/test_part_idempotent_resume.py:264`）。运维侧只能从 `safe_summary()`（含 `PARTIAL_ROW_STATE: 0`，queue.py:1455）看到一个**计数**，拿不到清单、无法人工推进。
- **证据**：上列三处摘录 + `grep` 零命中。
- **改法 before→after**：before=`/bot queue` 只出计数；after=接 `list_partial_requests()` 出「request_id/age/已送达 part/UNKNOWN part/最后错误」列表，并加管理指令 `part_reconcile`（人工判已送达→`mark_part_sent`/判未送达→`mark_part_pending`，正是 `queue.py:1028-1029` 注释承诺的确认协议）。prune 策略保持不动（不丢在途优先）。
- **验证命令**：`pytest tests/test_part_idempotent_resume.py tests/test_queue_poison_row.py -q --basetemp="$TEMP/u3-partial-$$" -p no:cacheprovider`

### 4.3 PARTIAL 断点续发是否可能造成重复打扰 —— **不会（取证见 §九-F3），但代价是半投递永久失踪**
worker 只补发 `pending_indexes()`（:801），UNKNOWN 不重发（:794-795），全部 SENT 才 `mark_sent`（:930-933）。跨通道重放保护另有 onebot 侧 `progress.count > 0` → `result_unknown` 四道守卫（onebot.py:717/777/818/934）。风险不在重发，在 **U3-03/U3-12 的「永不收敛」**。

### 4.4 队列与工作线程并发/锁语义 —— **正确（§九-F2）**
`queue.py:269-286`：进程内单共享连接 `check_same_thread=False` + `threading.RLock`；`_transaction`/`_transaction_immediate`（:313-367）把 mark_* 的读-改-写收进单事务；`submit` 用 `INSERT … ON CONFLICT DO NOTHING` 取代 SELECT→INSERT 两步（:441-473，注释自陈治未捕获 IntegrityError）；A-22 内联认领台账（:373-416）把「内联在途」从时间推断升级为任务存活推断，线程提交（无运行 loop）显式退回时间宽限（:388-389）。本席未发现竞态缺口。

### U3-13 ｜ P3 ｜ S0① 门开失败面不落 result_unknown/告警，与②③④不同构
- **坐标**：`__init__.py:4439-4443`（`except Exception: logger.debug` → `return`）、`:3074-3076`（未送达只 `logger.debug`）、`:3060-3062`（直接 `deliver(...)`，不经 `operational_notifier`）
- **锚点**：`"cookie expiry notice via queue failed", exc_info=True`
- **根因**：②③④经 `_run_capability_through_pipeline`，其中两次 `await _notify_operational_callback(operational_notifier, message, receipt)`（:2547/2559 区段）+ `_record_runtime_diagnostic`（:2579）→ 触发 `_notify_operational_receipt`（:3906-3922）→ **`result_unknown_ledger.record(...)`（:3916）+ 管理员告警**。① 手搓 submit+deliver，这三件一件都没有：`result_unknown` 不入账、不告警、不出诊断，`logging.debug` 级别在生产日志口径下近似不可见。全树 `result_unknown_ledger.record` 仅 1 个调用点（:3916）可反证。
- **改法 before→after**：after=`_deliver_cookie_expiry_report_via_queue` 拿到非 SENT 回执时显式 `_notify_operational_receipt(message=None 兼容形态)` 或最小化补 `result_unknown_ledger.record(request_id=…, adapter=…, session_id=f"private:{admin_id}")`，与提醒范式（`_deliver_due_reminders` :2963-2976 有 `logger.warning` + 保留重试）对齐。
- **验证命令**：`pytest tests/test_v21_s0_root_collect.py -q --basetemp="$TEMP/u3-ru-$$" -p no:cacheprovider`（新增：门开投递失败 ⇒ `result_unknown_ledger` 有该 request_id）

---

## 五、文件/媒体出站是否统一（item 5）

**结论：OneBot 文件出站单一咽喉，无死码双实现。**
链路：`CapabilityResult.files` → `renderer.py:219-221`（`media_parts` type=`file`）→ `onebot.py:552 return await _send_file_parts(...)` → `onebot.py:450/459/461 gateway = get_default_file_gateway(); ticket = gateway.stage(...); await gateway.deliver(...)` → `file_gateway.py:331 _deliver_onebot`（:366/:369 选 `upload_group_file`/`upload_private_file`，:373-382 `getattr(bot, api)` 优先、退化 `call_api`）/ `file_gateway.py:327 → :407 _deliver_telegram_document`（:425 `bot.send_document`）。

- `_send_file_parts`（onebot.py:423）与 `FileTransferGateway._deliver_onebot`（file_gateway.py:349）**不是**两套上传实现：前者只保留编排（预算切片、副作用计数、失败分类字面量映射），真实平台调用委托后者。二处 docstring 互标「等价搬运」（file_gateway.py:358 / onebot.py:437），与代码一致。
- `domains/files/`（capabilities/download.py·file_exchange.py·group_files.py，sources/downloader.py·file_reader.py）**只做取数与解析**，不自行触平台；`file_exchange.export_document` 只落盘，发送交回统一链。→ **无第二套「发文件」**。

### U3-15 ｜ P3 ｜ 传输域自我引用 compat shim（退役阻塞 + 文档口径失真）
- **坐标**：`domains/transport/sender/file_gateway.py:342`（`from plugins.bot_unified_runtime.sender.timeout import resolve_transport_timeout`）、`domains/transport/sender/nonebot.py:33`（`from plugins.bot_unified_runtime.output.plain_text import redact_local_secrets`）、`domains/chat_reply/capabilities/chat.py:70·74·2301·2347`
- **锚点**：`from plugins.bot_unified_runtime.sender.timeout import (`
- **根因**：真身已在 `domains/transport/sender/timeout.py`、`domains/render/plain_text.py`，但**同域**代码仍从旧包路径进。铁律 #3 与 AGENTS.md 第三部分把脱敏咽喉写成 `output/plain_text.py`——那是 3 行垫片（本席 `head -5` 实证：`"""Compat shim: moved to domains/render/plain_text (v21r2 reorg W13 render)."""`），文档指向垫片而非真身。
- **证据**：`head -5 plugins/bot_unified_runtime/output/plain_text.py` 输出即上引；`grep -rn "from plugins.bot_unified_runtime.output\.\|from plugins.bot_unified_runtime.sender\." plugins/bot_unified_runtime/domains/` 命中 20+ 行。
- **改法 before→after**：before=`…sender.timeout`／`…output.plain_text`；after=`…domains.transport.sender.timeout`／`…domains.render.plain_text`；文档侧把咽喉路径改写为真身（垫片面保留说明）。属 RET*/RWC* 退役波的低风险清扫，本席只登记不代做。
- **验证命令**：`../ChatBot_Runtime/venv/Scripts/python.exe scripts/dev.ps1`（不适用）→ 用 AST 扫描门：`pytest tests/test_datafix_runtime_paths.py -q --basetemp=… -p no:cacheprovider` 或 `grep -rn "from plugins\.bot_unified_runtime\.\(output\|sender\)\." plugins/bot_unified_runtime/domains/ | wc -l`（期望随退役波降到 0）

### U3-16 ｜ P3 ｜ 域外第二套出站/队列栈两处（需显式定籍，避免误当统一面收编）
- **坐标**：`domains/ops/integrations/gscore_bridge.py:246-257`（`self._queue` + `_flush_queue` → `await ws.send(...)`）；`third_party/astrbot_plugin_meme_manager/mixins/event_handlers.py:1563`（`await self.context.send_message(...)`）
- **锚点**：`await ws.send(json.dumps(payload, ensure_ascii=False))`
- **根因/判定**：gscore 是外部分数服务集成，非聊天出站，但**自造了一套无幂等、无回执、无审计的 flush 队列**，语义上与 SendQueue 重叠；astrbot 插件经本席 grep（`bot.py`/`plugins/`/`scripts/`/`pyproject.toml` 全域零 `astrbot` 引用）判定为**死参照件**，其 `context.send_message` 属 AstrBot 运行时而非本项目，不计入绕过。
- **改法 before→after**：before=两处身份不明；after=登记表 `DirectSendCategory` 增 `EXTERNAL_INTEGRATION`（gscore：登记自有重试/去重语义并声明不进 SendQueue）与 `NOT_LOADED_REFERENCE`（astrbot：标注未加载），并加负锁 `assert "astrbot" not in loaded_plugin_paths`。
- **验证命令**：`grep -rn "astrbot" --include=*.py bot.py plugins/ scripts/ | grep -v third_party | wc -l`（本席实跑 = 0）

---

## 六、回执与审计闭环（item 6）：「发出去但无人知道成败」清单

| 编号 | 路径 | 队列 | 回执 | 审计 | 告警 |
|---|---|---|---|---|---|
| U3-07 | 管理告警 `_deliver_admin_alert`（`__init__.py:3895-3904` → `alerts.py:463 delivery(target, bot, request)`） | 否 | 否 | 否 | 是（自身即告警，但其成败无人知） |
| U3-14 | 掉线通知四渠道（`disconnect_notice.py:158/168/178/188`） | 否 | 否 | 否 | 否 |
| U3-14 | `/mail send`（`mail_bridge.py:450`） | 否 | 否 | 否 | 否 |
| U3-11 | 37 处 `.finish()`（`__init__.py:5636 … 8629`） | 否 | 否 | 否 | 否 |
| U3-09 | 主动推送族（`:3210` 群摘要 / `:3357` 每日助理 / `:5029` 校园 / `:2941` 提醒） | 是 | 部分（worker 侧） | 部分 | 否（返回值被丢） |
| U3-13 | S0① 门开 | 是 | 是 | 是（transport 段） | **否** |
| U3-10 | `delete_msg` 撤回（`:4985`） | 否 | 否 | 否（`except: pass`） | 否 |

### U3-07 ｜ P2 ｜ 管理员告警直调通道本体，绕开队列/回执/审计，且模块 docstring 宣称「不绕过审计」
- **坐标**：`__init__.py:3895-3904`（`_deliver_admin_alert`）+ `domains/ops/monitor/alerts.py:11`（docstring）+ `alerts.py:455-476`（`dispatch_admin_alert`）
- **锚点**：`return await send_onebot_v11(bot, request)`
- **根因**：alerts.py 头注（:11）写「``SendRequest -> DeliveryReceipt -> AuditRecord``，不绕过审计」，实际 `grep -n "AuditRecord|audit_logger|receipt_repository|record(" alerts.py` 只命中 `audit_tags=` 两处（:302/:499）——**SendRequest 从未 `submit`，其 receipt 从未 `.record()`，全程零 `AuditRecord`**。`dispatch_admin_alert` 只把结果聚合进返回值（`AdminAlertDispatchResult`）。`request_id = new_request_id("admin_alert")` 每次全新随机 ⇒ **无 dedupe_key、无幂等**，去重完全依赖 `AdminAlertSuppression` 的 300s 折叠窗（不是幂等）。
- **证据**：上列 grep 命中清单 + `__init__.py:3895-3904` 摘录；对照合法路径 `_record_transport_receipt`（:2350-2444，含 `audit_logger.append(AuditRecord(...))` :2416 与 `receipt_repository.record(receipt)` :2430）——告警路径两者皆不经。
- **改法 before→after**：before=`_deliver_admin_alert` 直调 sender；after=改 `_deliver_transport_send_request(bot, None, request, audit_logger, receipt_repository, send_queue)`（该函数已内聚 `UnifiedDeliveryGateway` + 回执 + 审计 + queue 状态回写，见 :2467-2473），并给 `build_admin_alert_send_request` 补 `dedupe_key=f"admin_alert:{issue.debug_id}:{target.target_id}"`（300s 窗内天然同键）。
- **验证命令**：`pytest tests/test_bgroup_sender_delivery.py tests/test_auditfix_sender_queue.py -q --basetemp="$TEMP/u3-alert-$$" -p no:cacheprovider`，新增：告警投递后 `audit_logger.list_records(request_id)` 非空 + `receipt_repository.latest(request_id)` 非空。

### U3-14 ｜ P2 ｜ 掉线通知四渠道与 `/mail send` 全在统一出站协议之外；Mail 存在两套实现且 ServerChan/PushPlus 无平台登记
- **坐标**：`domains/ops/monitor/disconnect_notice.py:158`（`push_serverchan,`）· `:168`（`push_pushplus,`）· `:178`（`sent = await notify_telegram_admins(`）· `:188`（`await send_mail_from_account(`）· `:196-197`（`except Exception: continue`）；`domains/transport/mail/mail_bridge.py:450`（`/mail send`）与 `:312-346`（`send_mail_from_account` → `await target.send_mail(message)`）；对照第二实现 `domains/transport/sender/nonebot.py:494-495`（`return await send_mail(_build_mail_reply_message(...))` → `bot.send(event, ...)`）
- **锚点**：`await send_mail_from_account(`
- **根因**：三件独立问题一并在此：
  (a) **完全旁路**——掉线通知四渠道与 `/mail send` 均不经 `SendQueue`/`UnifiedDeliveryGateway`/`_deliver_transport_send_request`，因此无 part 幂等、无 `DeliveryReceipt`、无 `AuditRecord`、无 `result_unknown` 入账；
  (b) **Mail 出站两套实现**——队列侧走 NoneBot mail 适配器 `send_mail`（回复语义、绑事件），运维侧走 `aiosmtplib` 直投 `send_mail_from_account`（主动语义）。两套**都不算死码**（各服务不同场景），但只有前者在统一协议内，后者连 `request_id` 都不生成；
  (c) **注册表外渠道**——`push_serverchan`（disconnect_notice.py:86）与 `push_pushplus`（:101）是自建 HTTP 推送，`TransportPlatform` 枚举（outbound_registry.py:52-58）无对应平台条目，`build_default_transport_registry()` 亦无登记 ⇒ 登记表对「全部出站通道」的覆盖声明不成立。
- **证据**：`grep -rn "send_mail_from_account|send_mail(" plugins/ scripts/` → 生产命中恰为 `disconnect_notice.py:188`、`mail_bridge.py:450`（旁路两处）+ `nonebot.py:494`（统一侧）+ 定义处；`grep -n "def push_serverchan|def push_pushplus|def notify_telegram_admins"` 三定义全落在 `disconnect_notice.py:86/:101` 与 `mail_bridge.py:351`，均无 `send_queue.submit`。
- **改法 before→after**：
  (a)(b) before=`await send_mail_from_account(bots, account=…, recipient=…, …)` 直投；after=构造 `SendRequest(target_scope=SessionType.EMAIL, capability_id="bot.mail.notify", dedupe_key=…, …)` 走 `submit + _deliver_transport_send_request`（`bot.mail.notify` **已在** `CONTROLLED_INTERNAL_CAPABILITIES`，本席探针实证，故不会踩 U3-01 的未登记坑）；`send_mail_from_account` 降级为 mail 通道本体（与 `send_onebot_v11` 同层），不再被业务直接调用。
  (c) 短期：在 `direct_sends` 增 3 条 `BY_DESIGN` 条目（serverchan/pushplus/telegram-admins）并补真值测试；长期：`TransportPlatform` 增 `SERVERCHAN`/`PUSHPLUS`，经 `TransportRegistry` 固定映射，与 poke/reaction 同构。
- **验证命令**：`grep -rn "send_mail_from_account" plugins/ | grep -v "def \|mail_bridge.py:312" | wc -l`（现状 3：定义引用+2 旁路；收口后应仅 1 通道本体引用）+ `pytest tests/test_nonebot_sender.py -q --basetemp="$TEMP/u3-mail-$$" -p no:cacheprovider`

### U3-09 ｜ P2 ｜ 主动推送族自构 RenderedOutput（绕 reviewer+脱敏）且丢弃 submit 回执仍计数 `pushed`
- **坐标**：`__init__.py:3188-3211`（群摘要 `send_queue.submit(request)` / `pushed.append(group_id)`）、`__init__.py:3335-3358`（每日助理 `pushed += 1`）、`domains/assistant/campus/campus.py:156`、`__init__.py:2915-2941`（提醒）
- **锚点**：`content=RenderedOutput(` + `send_queue.submit(request)`
- **根因**：这四处不走 `render_reviewed_output`，故 reviewer 的 secret 面与 `_PUBLIC_OUTPUT_UNSAFE` 群泄露面（reviewer.py:33-37/134-139）**全部不适用**。其中群摘要与每日助理的正文是 **LLM 产物**（`_build_digest_push_text(summary)` :3198；助理早报 LLM 划重点），每日助理/群摘要的 `request_id`+`dedupe_key` 带日期做得对（:3334/:3351），但 `submit()` 返回的 `skipped_receipt` 被丢弃、仍记 `pushed`，**虚报成功**；提醒路径同理（但提醒由 `store.mark_done` 兜住，见 :2967）。
- **证据**：`grep -rn "RenderedOutput(" plugins/` 生产构造点 8 处（campus.py:156 / pipeline.py:892 / alerts.py:286 / error_report.py:997 / smoke.py:1096,1222 / __init__.py:2921,3033,3194,3341），其中 **alerts.py 与 error_report.py 各自显式 `redact_local_secrets`**（alerts.py:278/356，error_report.py:70），而 __init__.py 的 4 处推送**无任何脱敏/审核**。
- **改法 before→after**：before=直构 `RenderedOutput` + `submit()` 返回值丢弃；after=(a) 主动推送统一改调 `_send_text_through_unified_pipeline`（含 reviewer+脱敏+回执+告警），或最低限度在构 `RenderedOutput` 前套 `redact_local_secrets`；(b) `receipt = send_queue.submit(request)`，`SKIPPED` 不计数 `pushed`、并落一条 `digest_push_skipped_duplicate` 审计。
- **验证命令**：`pytest tests/test_group_digest_push.py tests/test_daily_assist.py tests/test_campus_digest.py -q --basetemp="$TEMP/u3-push-$$" -p no:cacheprovider`，新增：同日二次调用 ⇒ `pushed == []`。

### U3-10 ｜ P2 ｜ 撤回 `delete_msg` 仍裸 `call_api`，同表已登记 DELETE 通道却未走统一副作用面
- **坐标**：`__init__.py:4982-4987`（`await bot.call_api("delete_msg", message_id=message_id)` + `except Exception: pass`）
- **锚点**：`await bot.call_api("delete_msg", message_id=message_id)`
- **根因**：poke（L34）/reaction（L35）已迁 `OutboundSideEffectExecutor`（cancel 闸 → 准入复验 → 租约线性化 → **TransportRegistry 固定映射** → call_api 通道本体，dispatcher.py:162-220），且 `TransportRegistry` **已为 QQ 注册 `TransportChannel.DELETE → {"*": "delete_msg"}`**（outbound_registry.py:205-211）。即：统一面已具备执行 DELETE 的能力与登记，唯独 dirty guard 这一个生产调用点没用它。登记表把该项标 `BY_DESIGN`「撤回，非消息投递」（:651-657），语义上把「无队列」讲通，但**回避了「无 executor、无回执、无审计、失败静默 `pass`」** 这四件；同类副作用（poke/reaction）已收口，唯此一处例外。
- **证据**：`__init__.py:4986-4987` 摘录（`except Exception: pass`，无日志）+ `dispatcher.py:200` 已具备 `call_api(method, **params)` 通道本体 + `outbound_registry.py:205-211` DELETE 条目已登记。
- **改法 before→after**：before=裸 `call_api("delete_msg")` + `pass`；after=照 `__init__.py:5056` poke 装配形态，构造 `OutboundIntent(channel=DELETE, dedupe_key=f"dirty_guard_delete:{message_id}")` 经 `_poke_side_effect_executor` 同族的执行器执行，`SideEffectReceipt.status != "delivered"` 落 `_log_runtime_event(..., "dirty_guard_delete_failed", ...)`；方法名仍只从注册表解析。
- **验证命令**：`pytest tests/test_v21_dispatch_outbound_wiring.py tests/test_outbound_v21.py -q --basetemp="$TEMP/u3-del-$$" -p no:cacheprovider` + AST 负锁：根 `__init__.py` 内 `call_api("delete_msg"` 字面量计数 = 0。

### U3-11 ｜ P3 ｜ 37 处 `Matcher.finish()` 直发用户可见文本（半旁路，风险受控）
- **坐标**：`__init__.py` 5636·5639·5867·5874·5938·6147·6398·6435·6484·7211·7247·7723·7741·7803·7809·7860·7866·7909·7912·7956·7961·8013·8017·8172·8176·8189·8231·8234·8241·8252·8259·8373·8394·8557·8615·8629（`grep -c "\.finish(" = 37`，全树唯一分布文件=根 `__init__.py`）
- **锚点**：`await image_search.finish(transport_receipt.public_message)`
- **根因/判定**：NoneBot `Matcher.finish` 由适配器直发，**不经 SendQueue/回执/审计**。但 `should_finish_nonebot_matcher`（:2276-2286）显式排除 `SENT`/`SKIPPED` 与任何带 `operational_issue` 的回执 ⇒ **队列已成功或已判 result_unknown 时不会再发一遍**，双发风险已被构造掉。残余是：这些兜底文案无幂等、无留痕，且绕过 reviewer 的 secret/privacy 判定（内容是固定短语或 `receipt.public_message`，后者已由 reviewer 产，故今日无实据泄漏）。
- **改法 before→after**：before=`finish(public_message)` 直发；after=保持「matcher 必须结束」的 NoneBot 语义，但把发送改为 `submit + _deliver_transport_send_request`（与同文件 `_send_text_through_unified_pipeline` 同构），`finish("")` 只做控制流；或最低成本方案：新增常驻 AST 门，把 `.finish(` 调用点数钉成棘轮（当前 37，只准降不准升），并强制其参数只能是 `receipt.public_message`/字面量白名单。
- **验证命令**：`grep -c "\.finish(" plugins/bot_unified_runtime/__init__.py`（基线 37）+ `pytest tests/test_nonebot_sender.py -q --basetemp="$TEMP/u3-finish-$$" -p no:cacheprovider`

---

## 七、副作用类出站是否统一（item 7）

| 副作用 | 现出口 | 是否统一面 | 判定 |
|---|---|---|---|
| 回戳 group_poke/friend_poke | `OutboundSideEffectExecutor`（`__init__.py:5056` 装配 → `dispatcher.py:200`） | **是** | 已收编（L34），根文件 `group_poke`/`friend_poke` 字面量零命中（探针 `[OK]` control_plane/dispatcher.py:162-220） |
| 贴表情 set_msg_emoji_like / set_message_reaction | 同一执行器（`domains/meme/reactions/engine.py:664` `_REACTION_OUTBOUND_EXECUTOR` → `:760`/`:800` handle） | **是** | 已收编（L35），失败诚实落 `SideEffectReceipt`（dispatcher.py:201-209） |
| 撤回 delete_msg | 裸 `bot.call_api`（`__init__.py:4985`） | **否** | U3-10 |
| 设置群名片 set_group_card / 踢人 set_group_kick | **未实现** | 不适用 | 全树 `grep "set_group_card|set_group_kick"` = 0 命中（本席扫描结果，无此项） |
| 群文件记录 group_upload | 纯入库（`__init__.py:4959 group_file_store.record(`） | 不适用 | 只读事件，无出站 |

**协议差异取证**：执行器面已实现「cancel 闸 → 准入复验 → 租约线性化 → 固定映射解析方法名 → 失败诚实回执」（dispatcher.py:129-144 docstring 与 :175-209 代码一致，非仅注释）；但它与 SendQueue 是**两条独立出站协议**（`SideEffectReceipt` vs `DeliveryReceipt`），共享的只有最底层 `call_api` 通道本体。用户 mandate 的「一切出站必须经中央统一处理」在副作用面已**部分**兑现（poke/reaction），delete_msg 是唯一漏点。

---

## 八、脱敏/安全出口统一性（item 8，安全面实证）

### U3-08 ｜ P2 ｜ `redact_local_secrets` 不在咽喉，而在各能力自愿调用；咽喉实测放行盘符路径与 URL 凭据
- **坐标**：咽喉 = `domains/render/reviewer.py:114-165`（`review_capability_result`，`safe_text=output_text` 原样返回 :163）+ `domains/render/renderer.py:186-272`（`render_reviewed_output`）；真脱敏函数 = `domains/render/plain_text.py:340-364`（`redact_local_secrets`）；能力侧自调用仅 3 处（`domains/chat_reply/capabilities/chat.py:2354`、`domains/files/capabilities/download.py:137`、`domains/media/capabilities/media_archive.py:208/227`）
- **锚点**：`safe_text=output_text,`（reviewer.py:163）
- **根因**：reviewer 的 secret 正则集（`_SECRET_OUTPUT_PATTERNS` reviewer.py:22-30）只覆盖 `api_key|token|cookie|authkey|authorization|bearer|sk-` 七形，**不含盘符路径、`BOT_XXX=` 赋值、URL userinfo、JWT**——这四形只存在于 `redact_local_secrets`（plain_text.py:340-364）。而 `redact_local_secrets` **不在** pipeline 的任何统一阶段（AGENTS.md 第三部分把它写成链路一节 `output/plain_text(说人话/数值打码/密钥与路径打码)`，铁律 #3 称其为出站前咽喉），实际只在 chat.py 一处 + 两处零散调用。
- **证据（本席实跑行为探针，非静态推断）**：
  ```
  === review + render chokepoint behaviour (non-chat capability) ===
  drive path backslash   approved=True  changed=False out='C:\\Users\\LancyCelestia\\Documents\\secret\\note.md 已保存'
  drive path slash       approved=True  changed=False out='请看 file:///C:/Users/LancyCelestia/secrets/a.png'
  url userinfo           approved=True  changed=False out='redis://user:hunter2@10.0.0.9:6379/0'
  BOT_ env assignment    approved=False …      api key form    approved=False …
  ```
  即：`sk-`/`api_key=`/`BOT_XXX=sk-…` 三形在咽喉被**拦截**（approved=False，pipeline.py:732 提前返回，不上线），而**盘符绝对路径与 URL 内联凭据在咽喉全放行**。
  现状风险量化：本席另以 `grep -rn "body=.*str(path)|body=f\"{.*path|body=.*local_path"` 全树搜能力层把绝对路径写进正文的实据，**零命中**（file_export 只写 `path.name`，chat.py:2332 artifact 正文只 `generated.path.name`）⇒ **今日无实测泄漏面**，本条定性为**纵深防御缺口 + 文档口径失真**，非现行数据外泄事故。
- **改法 before→after**：
  before：`reviewer.review_capability_result → safe_text=output_text`（原样），`renderer` 不脱敏，脱敏靠能力自觉
  after：在咽喉**单点强制**——`reviewer.py:163` 改 `safe_text=redact_local_secrets(output_text)`（幂等：无命中即原样返回，plain_text.py:343-353 已有快路径哨兵，热路径近零成本），并把 `_SECRET_OUTPUT_PATTERNS` 扩到与 `redact_local_secrets` 同集（盘符/`BOT_`/userinfo/JWT）；能力侧的 3 处自调用保留为冗余无害。文档同步：AGENTS.md 铁律 #3 与第三部分的咽喉路径改写真身 `domains/render/plain_text.py`（见 U3-15）。
- **验证命令**：
  ```
  PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0 ../ChatBot_Runtime/venv/Scripts/python.exe "%TEMP%/u3_probe_redact.py"
  # 期望：drive path / url userinfo 三行 changed=True 且 out 含 [redacted]/占位
  pytest tests/test_rendering_contract.py tests/test_media_archive.py -q --basetemp="$TEMP/u3-redact-$$" -p no:cacheprovider
  ```
  新增回归锁：任意 capability_id 过 `review→render` 后正文不得含 `[A-Za-z]:\\` / `[A-Za-z]:/` / `://[^/]*:[^/]*@`。

### 旁路咽喉的构造点枚举（同 §六 U3-09）
8 处生产 `RenderedOutput(` 直构中，`alerts.py:286` 与 `error_report.py:997` **各自已 `redact_local_secrets`**（alerts.py:278/356），`pipeline.py:892`（群失败兜底，固定短语池）无风险，`__init__.py` 四处推送无脱敏 → 归 U3-09。

---

## 九、无缺陷项取证清单（本席查过且判定合规的）

| # | 项 | 取证 |
|---|---|---|
| F1 | part 幂等键单源 | `queue.py:104-106` 唯一定义；全库仅 `:1070`/`:1219` 两处内部使用；`grep -rn "_part_key" plugins/` 无第三方生成点 |
| F2 | 队列并发/锁语义 | `queue.py:269-333`（RLock+单共享连接+显式 BEGIN 事务）+ `:441-473`（`ON CONFLICT DO NOTHING` 原子判重）+ `:373-416`（A-22 内联认领台账，线程提交显式退回时间宽限） |
| F3 | PARTIAL 续发不重复打扰 | `worker.py:801`（只发 pending）+ `:794-795`（UNKNOWN 不重发）+ `:930-933`（全 SENT 才 mark_sent）+ `onebot.py:717/777/818/934` 四道 `progress.count>0 → result_unknown` |
| F4 | 四门缺省关 | `config.py:658/747/748/760` 全 `= False`；生产 `.env` 未出现任何 `*_VIA_QUEUE` 键（本席 `grep "BOT_VIA_QUEUE\|_VIA_QUEUE" .env.example` 亦无），不拨门=零变更成立 |
| F5 | 门关分支对 S0-ROOT-c diff 逐字节等价 | ②:5384-5392 与门开 :5366-5383 同文案（同调 `_group_welcome_text(nickname)`）、同 `group_welcome_sent` 触发条件、同「失败不影响主链路」；③门关 :5735-5749 与门开 :5710-5734 图像段同构（`{"file": qr_file_ref}` → `renderer.py:207-209` → `mixed` parts，`text.strip()` 空 ⇒ 不追加文本段 :253-254 ⇒ 与旧 `message=[image_segment]` 同形态）；④门关 :5531-5553 成功/失败文案与门开 :5516-5530 字面一致。唯一非等价 = U3-06 |
| F6 | 安静时间不误伤 S0② | `policy/quiet_hours.py:120` `if message.mentions_bot or capability_id not in {"bot.chat", "bot.content"}` → 放行 ⇒ `bot.group_welcome` 不受安静时间约束（等价性保住；该风险本席专项验证过） |
| F7 | 文件出站单实现 | §五 链路枚举：`onebot.py:459/461` 委托 `FileTransferGateway`，无第二套上传 |
| F8 | 副作用统一面语义非纸面 | `dispatcher.py:175-209` 代码与 :129-144 docstring 逐条对应（cancel 闸/准入/租约/mark_irreversible/固定映射/诚实回执），非仅注释宣称 |
| F9 | 读路径未混入出站 | §一 表 #6/#7/#23 全部为 `get_*`/`download_file` 读语义（`__init__.py:1054/1150/2232/5352/5431/5435/8075`） |
| F10 | 本席自身树卫生 | 见文末自查 |

---

## 十、出站单一咽喉收口清单（按解锁顺序）

> 排序原则：先止血（门吞=功能级失效），再补可靠性承诺（UNKNOWN/幂等），再收旁路（审计闭环），最后清登记与纵深防御。第 1 条不解，第 3/5/6 条拨门验收必翻车。

| 序 | 前置依赖 | 动作 | 涉及 | 完成判据（可复跑） |
|---|---|---|---|---|
| **1** | 无（最高优先，今日即红） | 把 `bot.file`/`bot.group_welcome`/`bot.cookie_login`/`bot.cookie_expiry_notice` 登记进 `CONTROLLED_INTERNAL_CAPABILITIES`（或统一管线 helper 缺省改已登记 id），并给 21 处未显式传 capability_id 的调用点补正确 id | U3-01 · U3-02 | `u3_probe_blocked_caps.py` → `BLOCKED = 0`；新增 capability_id ⊆ bindings 常驻门 |
| **2** | 与 1 同批 | 把 S0 门开的 ②③④ 测试从「spy `_run_capability_through_pipeline`」改为「真 `RuntimePipeline(feature_gate=ProductFeatureGate(stub))` + 断言 SENT/REDIRECTED」，消除假绿 | U3-02 | 新用例在 1 未做前应**红**、做完转**绿**（红-绿序列即证据） |
| **3** | 1（拨门前置） | feature_gate fail-closed 语义单独裁决：未登记/状态读取失败是否允许吞**用户可见出站**（建议：控制面读失败 ⇒ 放行 + WARN 审计；未登记 ⇒ 启动期即报错，而非运行期静默） | U3-01 附 | 新增门：`pipeline._prepare` 在 gate 拒绝时必须产生 AuditRecord 且不得无提示结束 |
| **4** | 无 | 生产 `drain_send_queue_once` 接 OneBot `get_msg` confirmer；`mark_part_unknown` 补传 `provider_message_id`；Mail/TG 显式声明「不可确认」并终态化而非休眠 | U3-03 · U3-12 | `grep -rn "unknown_part_confirmer" plugins/` ≥2 命中（含 `__init__.py:1649` 装配处）；`list_partial_requests` 生产消费者 ≥1 |
| **5** | 无 | `delete_msg` 收编 `OutboundSideEffectExecutor`（注册表 DELETE 条目已在，直接复用）；失败落 runtime_event | U3-10 | AST 负锁：根文件 `call_api("delete_msg"` = 0 |
| **6** | 无 | 管理告警改走 `_deliver_transport_send_request`（补队列/回执/审计 + `dedupe_key`）；修正 alerts.py:11 失实 docstring | U3-07 | 告警后 `audit_logger.list_records(request_id)` 非空 |
| **7** | 无 | 主动推送族（群摘要/每日助理/校园/提醒）统一 `_send_text_through_unified_pipeline` 或至少前置 `redact_local_secrets`；`submit()` 回执纳入计数与审计 | U3-09 | `grep -c "RenderedOutput(" __init__.py` 由 4 降为 0；同日二次调用 `pushed == []` |
| **8** | 无 | `redact_local_secrets` 上提到 `reviewer.safe_text`，咽喉单点强制；扩 `_SECRET_OUTPUT_PATTERNS` 到盘符/`BOT_`/userinfo/JWT | U3-08 | `u3_probe_redact.py` 三行 `changed=True`；新增「咽喉后正文无盘符」回归锁 |
| **9** | 无 | S0① 两处语义修正：`submit()` 返回 SKIPPED 即视为已送达（幂等单源化）；非数字 admin id 改 `continue`；失败补 `result_unknown_ledger.record` | U3-05 · U3-06 · U3-13 | 新增 3 例（None 回执仓仍不双发 / 脏 id 换人 / 失败入账） |
| **10** | 无 | 登记表坐标收编为常驻真值测试（文件存在+行内命中 API 字面量+shim 路径判红）；修 `sender/onebot.py`→`domains/transport/sender/onebot.py`、`4978`→`4985`、四条门→4446/5385/5737(+5743)/5533(+5540)、READ_PATH 全表真身 | U3-04 | `u3_probe_registry.py` → `coordinate problems = 0` |
| **11** | 无 | 掉线通知三渠道 + `/mail send` 定籍：纳入 TransportRegistry（新增 SERVERCHAN/PUSHPLUS 平台条目）+ 至少一条 `send_attempted/send_failed` 审计，或显式登记为「域外运维通道」并在登记表加 BY_DESIGN 条目 | U3-14 | `direct_sends` 新增 4 条且真值测试通过 |
| **12** | 随退役波 | `.finish(` 调用点棘轮（基线 37，只降不升）+ 参数白名单；传输域自引用 shim 清扫（`sender.timeout`/`output.plain_text`）；gscore 自造队列与 astrbot 死参照件定籍 | U3-11 · U3-15 · U3-16 | `grep -c "\.finish("` ≤37 且单调降；`grep -rn "from plugins\.bot_unified_runtime\.\(output\|sender\)\." plugins/.../domains/` = 0 |

**明确不建议现在做的事**：把四门拨开做真机验收（在 1-3 完成前，拨门 = 对应功能静默失效，比门关更糟）；把 `delete_msg`/`.finish()` 一律判为 P0 事故级重构（前者有注册表条目可直接复用，后者已被 `should_finish_nonebot_matcher` 构造性去双发）。

---

## 十一、方法与会话卫生

**解释器/环境**：`../ChatBot_Runtime/venv/Scripts/python.exe`，一律带 `PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 BOT_AUTOSYNC=0`；pytest 一律带 `--basetemp="$TEMP/u3-<用途>-$$" -p no:cacheprovider`。

**本席实跑记录（全部可复跑）**：
1. `pytest tests/test_v21_s0_root_collect.py tests/test_v21_s0_collect.py tests/test_outbound_v21.py tests/test_part_idempotent_resume.py tests/test_v21_dispatch_outbound_wiring.py -q` → **126 passed in 8.42s**（未跑全量）
2. `python "%TEMP%/u3_probe_registry.py"` → **RESULT: coordinate problems = 23**（U3-04 证据）
3. `python "%TEMP%/u3_probe_redact.py"` → 盘符/URL-userinfo 三行 `approved=True changed=False`（U3-08 证据）
4. `python "%TEMP%/u3_probe_featuregate.py"` → `total_bindings=69`，四个 S0/管线 id 全 `gated=YES-UNREGISTERED->BLOCKED`（U3-01/02 证据）
5. `python "%TEMP%/u3_probe_blocked_caps.py"` → `capability_id literals=31 / BLOCKED=4`：`bot.cookie_expiry_notice(3032)`·`bot.cookie_login(5722)`·`bot.file(5512,5524)`·`bot.group_welcome(5375)`
6. AST 枚举管线 helper 调用点 → `total=27 / without explicit capability_id=21`
7. 直调 `ProductFeatureGate.__call__` → `bot.file/group_welcome/cookie_login/cookie_expiry_notice allowed=False reason=feature_unregistered`；`bot.chat`/`bot.poke` 越过该行进 `service.detail`（反证分支归因）
8. `git show HEAD:...__init__.py` 对照 → HEAD 已含 22 处管线 helper、**无** `feature_gate=product_feature_gate` ⇒ U3-01 归因在飞控制面席，非 S0-ROOT-c（只读 git，无写操作）

**源码树零缓存自查（结束时）**：
```
find plugins scripts tests -name "__pycache__" -o -name "*.pyc"  → 空
ls -d data → no data/ dir
```
本席零 `__pycache__`/零 `.pyc`/零 `data/` 产生；`.pytest_cache`/`.ruff_cache`/`.mypy_cache` 目录树内确实存在近 60 分钟改动，但**非本席所为**——本席 pytest 带 `-p no:cacheprovider`，且全程未执行 ruff/mypy；本席只读时间戳核对：`git status --porcelain -- '%TEMP%'` 显示本席仅新增 4 个探针脚本，位于仓库内既有 `%TEMP%` 字面量目录（另一审计席 `u12_scan.py` 同处，说明为该波次约定scratch位）。本席未删除任何文件（含自有探针），以免与他席清理冲突；如需清账，请收尾席统一处置 `%TEMP%/u3_probe_*.py`（4 件）。

**未覆盖/让渡面（如实声明）**：
- `TransportRegistry.bind_handler` 全树零生产调用（仅 `outbound_registry.py:136` 定义 + 一处 docstring），即**全部 transport 条目 status=placeholder**——该「登记表与实际 sender 从未真正绑定」的判断本席只做了 grep 取证，未展开成正式发现（属 DELIVERY-001/PORT-PLAN 席职权，且 HANDOFF §五已记「端口组真实发送待用户逐项勾选」）。
- `domains/chat_reply/capabilities/group_info.py:146` 通用 `call_api` 透传 sink 的动作面宽度：登记表已标 `DISPATCH-001 单列审计`，本席**不重复记账**。
- `control_plane/api/*` 的出站端点（`workspaces.py:82 require_service().send(...)`）语义属工作区投递面，503 根因与真实发送已在 PORT-PLAN 台账，本席未审。
- 本席**未**重启、**未**真实发送、**未**读 `.env` 明文内容（仅按键名定向 grep `BOT_SEND_QUEUE_*`/`BOT_RECEIPTS_*` 三个布尔/路径开关值），**未**写 `ChatBot_Runtime/`。
