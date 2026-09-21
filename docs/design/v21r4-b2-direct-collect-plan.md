# v21r4-B2：S0 直连点收编方案（DIRECT-PLAN 席交付）

> 席位=DIRECT-PLAN｜性质=**只读取证 + 方案文档，零代码改动**｜产出日=2026-09-19（读时快照）。
> 前置=WIRE-DIRECT 席（B2③）移交 5 处 S0 时代真实绕队列直连点坐标（见 `v21r4-b-WIRE-DIRECT-log.md` §二）。
> **诚实红线（先读）**：本文件全部内容为**方案材料**，无一实现、无一接线、无一生效。所有「收编后应……」均为设计意图陈述；矩阵 L 行零改动；`production_wiring` 不升 wired；未 commit/未重启/未部署。坐标为 2026-09-19 读时快照（根 `__init__.py` 正被 WIRE-SVC 席在飞编辑，行号必然漂移，实施席须以符号 grep 重新定位，不得照抄行号）。
> 证据口径：全部断言给出 file:line；本次会话实读源码所得=verified；转引自他人日志未亲证=标注转引；无证据=unknown。
> **漂移实证**：本席两次只读扫描间隔内，①的配置门行已从 :4262 漂至 :4277（约 15 行插入，WIRE-SVC 在飞装配段实证）。第二次扫描复核锚点（2026-09-19 二扫）：①gate=:4277/job=:4279/add_job=:4313/job_id=:4317；②matcher=:5150/gate=:5159/handler=:5155；③cookie_admin matcher=:5411/cookie_login_start=:5472/image_segment=:5475/失败日志=:5493；④rule=:5258/matcher=:5263/handler=:5266。直连调用本体（call_api 行）两次扫描均在（4300/5184/5481/5303 区段），说明漂移来自**上方**装配段插入、五点相对结构未变。实施席一律以符号 grep 重定位。

---

## 〇、总裁定（一句话版）

5 处坐标全部核实为**真实存在的绕统一出站路径直连点**（其中⑤是登记表坐标陈旧问题而非新直连点）。四处生产直连（①②③④）分属三种统一路径形态可收编（调度 job→SendQueue 范式 / 管线统一发送 / 文件网关链），一处（⑤）是纯登记表维护。全部可设计为**配置门缺省关**的渐进收编，行为语义（失败静默、管理员换人重试、文本兜底）逐字节保持。

---

## 一、五处直连点重新定位（读时快照 2026-09-19）

| # | WIRE-DIRECT 移交坐标 | 现坐标（读时快照，会漂移） | 内容 | 定位方式 |
|---|---|---|---|---|
| ① | ~:4300 | `plugins/bot_unified_runtime/__init__.py:4300-4303` | cookie 到期每日提醒 → `call_api("send_private_msg")` | grep `send_private_msg` |
| ② | ~:5184 | `__init__.py:5184-5187` | 入群欢迎 → `call_api("send_group_msg")` | grep `send_group_msg` |
| ③ | ~:5481/5487 | `__init__.py:5481-5491` | cookie 登录二维码图片 → `call_api("send_group_msg"/"send_private_msg")` | grep `send_group_msg` |
| ④ | ~:5303/5310 + file_gateway | `__init__.py:5303-5315`；文件网关真身=`domains/transport/sender/file_gateway.py:377-391`（旧路径 `sender/file_gateway.py` 现为 3 行 compat shim，实读确认） | 文档导出 → `call_api("upload_group_file"/"upload_private_file")` | grep `upload_group_file` |
| ⑤ | outbound_registry 陈旧坐标 | `domains/core/decision/outbound_registry.py:589-600`（登记值 4070/4878/5175-5182）；evidence 字符串陈旧另见 :183-187、:205-216、:607-610、:631-634 | 直连点登记表坐标/状态陈旧 | grep `DirectSendEntry` |

同文件其余 `call_api` 命中甄别（均非出站直连，不收编）：`:1027/1041/7806` get_forward_msg、`:1137` get_record、`:2214-2218` get_stranger_info、`:4802` delete_msg（撤回，登记表 BY_DESIGN 口径）、`:5169-5175` get_group_member_info（欢迎昵称富集，读路径）、`:5230/5234` get_file/download_file（文件接收，读路径）——与登记表 READ_PATH/BY_DESIGN 既有甄别一致（`outbound_registry.py:603-646`）。

---

## 二、逐处现状取证（触发 / 去向 / 失败面 / 绕过方式）

### ① cookie 到期每日提醒（`__init__.py:4262-4320`）

- **触发条件**：APScheduler cron `hour=10, minute=0`（:4313-4320，`misfire_grace_time=600, max_instances=1`）；配置门 `bot_cookie_expiry_reminder_enabled` 缺省 True（:4262）。
- **行为**：`cookie_expiry_report(config)` 线程池取报告（:4265-4272）→ `_select_credential_bot(_all_online_bots())` 选在线 bot（:4274-4276）→ 取 `bot_admin_user_ids` 前 3 个管理员（:4277-4282）→ 逐个尝试 `bot.call_api("send_private_msg", user_id=int(admin_id), message=[text段])`，**成功即 break**，异常降级 debug 日志换下一管理员（:4284-4307，直连本体 :4300-4303）。
- **消息去向**：私聊管理员，纯文本段，内容=凭证过期报告。
- **失败面**：报告空/异常→静默 return（:4272-4273）；全部管理员发送失败→仅 debug 日志（:4305-4307），无回执、无重试、无审计、无幂等（同日多次触发理论上可重复打扰，靠 cron 每日一次兜底）。
- **绕过方式**：调度 job 内直接 `bot.call_api` 发消息——不过 pipeline、不产 SendRequest、不进 SendQueue、不落回执仓、不过 review/renderer、无 dedupe_key/cooldown_key、无 audit_tags。对照同文件提醒生产线 `_deliver_due_reminders`（:2852-2956）已是「构造 SendRequest→`send_queue.submit`→`_find_sent_request`→内联 `_deliver_transport_send_request`→送达才销账」的统一范式——**同为核心调度出站，一处统一一处直连**，收编即对齐自家先例。

### ② 入群欢迎（`__init__.py:5143-5197`）

- **触发条件**：`group_increase` notice matcher（priority=6, block=False，:5161）；配置门 `bot_group_welcome_enabled` 缺省 True（:5147）。
- **行为**：取 group_id/user_id（:5148-5153）→ `get_group_member_info` 昵称富集（5s 超时，失败退通用称呼；**读路径不收编**，:5169-5175）→ `bot.call_api("send_group_msg", group_id=…, message=[text段=_group_welcome_text(nickname)])`（直连本体 :5184-5187）→ 成功记 `group_welcome_sent` runtime 事件（:5188）。
- **消息去向**：来新成员的群，纯文本欢迎语（文本函数 `__init__.py:1150`，既有测试锁内容：`tests/test_group_notice_b05.py:11-33`）。
- **失败面**：发送异常→静默 pass（:5189-5190），无重试无回执。
- **绕过方式**：notice handler 内直接 `bot.call_api`；不走统一管线（同 handler 家族的 poke/表情两路径已在 L34/L35 收编，本 handler 是同批残留）。退群/管理变更 handler 只记事件不发言（:5192-5197+），无直连。

### ③ cookie 登录二维码图片（`__init__.py:5464-5494`）

- **触发条件**：`/bot cookie login <平台>` 管理命令（`cookie_admin` matcher priority=8 block=True :5442；管理员门 `_is_admin_origin` :4760-4767）。
- **行为**：`cookie_login_start` 产出 png_path+login_text（:5471-5472）→ **文本先走统一管线** `_send_text_through_unified_pipeline`（:5473，已收编形态）→ 若有二维码：构造 `file:///` 图片段（:5474-5479）→ 按 GroupMessageEvent 分支 `call_api("send_group_msg"/"send_private_msg", message=[image段])`（**直连本体** :5481-5491）。
- **消息去向**：触发命令的同一会话（群/私聊），本地二维码图片。
- **失败面**：图片失败→debug 日志 `qr image send failed`（:5492-5493），文本兜底已先行给出（注释明示），语义=图片失败不影响命令可用性。
- **绕过方式**：**同一 handler 内文本走统一管线、图片直连**的混合形态——图片未走 `CapabilityResult.images`→`render_reviewed_output` media_parts（`domains/render/renderer.py:206-208`）→transport `_image_segment`（`domains/transport/sender/onebot.py:326-339`，`_resolve_local_file_ref` 对本地路径 `file:///` 引用有显式解析支持 :315-322）的既有链。

### ④ 文档导出上传（`__init__.py:5259-5321`）+ 文件网关登记项

- **触发条件**：文件导出命令（`is_file_export_command`）+ 管理员（matcher priority=8 block=True，:5259-5263）。
- **行为**：LLM 生成 markdown（线程池，:5269-5281）→ `export_document` 落盘 `bot_download_dir/export`（:5291-5298）→ 按群/私聊分支 `call_api("upload_group_file"/"upload_private_file", file=str(path), name=path.name)`（**直连本体** :5301-5315）→ 成功后 `_send_text_through_unified_pipeline` 回执文本（:5317-5321，已收编形态）。
- **消息去向**：触发命令的同一会话，导出文档文件。
- **失败面**：上传异常→统一管线发「文件已生成但上传失败：<名>」（:5316-5318）——诚实但无重试、无断点、无回执仓。
- **绕过方式**：文件上传未走 `CapabilityResult.files` 链。**该链已存在且有测试**：`CapabilityResult(files=[…])` → `render_reviewed_output` files→media_parts（`domains/render/renderer.py:214-216`）→ SendRequest → transport file 部件分支 → `get_default_file_gateway().stage→deliver`（`domains/transport/sender/onebot.py:439-462`，B3 阶段 1 注释明示「文件部件统一经 FileTransferGateway」）；行为测试=`tests/test_phase0_3_features.py:180`（`test_onebot_upload_api_not_fake_file_segment`：files→render→SendRequest→`send_onebot_v11`→断言首调用=`upload_group_file`）。
- **`domains/transport/sender/file_gateway.py:377-391`（登记表记 :382，PENDING_RULING）**：这是 `FileTransferGateway._deliver_onebot` 的上传内环——`getattr(bot, api)` 优先、退化 `call_api`、retcode 拒绝→`upload_rejected`（:359-391）。**裁定建议**：该「直连」实为统一文件出站路径**自身的通道本体**，与 `sender/onebot.py:444,449…` 被登记为 CHANNEL_BODY 同理（`outbound_registry.py:623-628`）——SendQueue worker transport 消费它、管线 file 部件消费它，业务侧无人绕它直调（全库 grep：生产代码仅 capability_protocols.py:1116 文档性提及，无实例化绕行）。建议⑤维护时 PENDING_RULING→CHANNEL_BODY，附 DELIVERY-001 责任席复核注记。本席只读未动，final 裁决归 DELIVERY-001 owner。

### ⑤ 登记表陈旧（`domains/core/decision/outbound_registry.py`）

逐条实读比对（登记值 → 读时快照实况）：

| 登记行 | 登记坐标/口径 | 实况 |
|---|---|---|
| :589-592 | `__init__.py:4070-4071` send_private_msg BYPASS_SUSPECT | 即本方案①，现 :4300-4303（cookie 提醒） |
| :595-598 | `__init__.py:4878-4879` send_group_msg「群成员变动通知区」 | :4878-4879 现为 poke 执行器装配区（`_poke_side_effect_executor` :4873 起）；真实群直连=②欢迎 :5184-5187 |
| :599-602 | `__init__.py:5175-5182` send_group_msg+send_private_msg「管理命令回复区双通道」 | :5169-5175 现为 get_group_member_info 读路径；:5184 起为②欢迎单通道；③二维码双通道在 :5481-5491 |
| :183-187 | SEND_MESSAGE evidence 字符串「4071/4879/5175-5182 为待收编绕行点」 | 坐标全陈旧，收编实施后应改指本方案 §三 编号 |
| :205-211 | poke group_poke/friend_poke「待收编」BY_DESIGN | **已收编**（L34：`control_plane/dispatcher.py:125` OutboundSideEffectExecutor + `__init__.py:4862-4918` 装配）；登记状态未更新 |
| :212-216 | reaction set_msg_emoji_like「待收编」BY_DESIGN | **已收编**（L35：`domains/meme/reactions/engine.py:664` 执行器 + :754 react_to_message）；且坐标陈旧（`runtime/reactions.py` 已是 compat shim，真身 `domains/meme/reactions/engine.py`） |
| :607-610 | delete_msg `__init__.py:4569` | 现坐标 :4802（BY_DESIGN 性质不变） |
| :631-634 | `sender/file_gateway.py:382` PENDING_RULING | 路径陈旧（reorg 后 `domains/transport/sender/file_gateway.py`），性质建议 CHANNEL_BODY（见④裁定建议） |

---

## 三、逐处收编方案

### 3.0 统一路径四形态（本方案的全部技术依据，均已存在、均已测试）

| 形态 | 载体 | 关键证据 | 适用 |
|---|---|---|---|
| A 管线路径（有 Event） | `_send_text_through_unified_pipeline`（`__init__.py:4666-4692`）/ `_send_parts_through_unified_pipeline`（:4694-4741，images/prefix_parts→mixed）→ `_run_capability_through_pipeline`（:2519-2560+）→ pipeline→`render_reviewed_output`（`domains/render/renderer.py:186`）→ SendRequest（`domains/chat_reply/runtime/pipeline.py:807`）→ `send_queue.submit` → `_deliver_transport_send_request`（`__init__.py:2433-2455`）→ UnifiedDeliveryGateway | 现役使用面广（grep `_send_text_through_unified_pipeline` 20+ 调用点）；notice 事件可进摄取：`_incoming_from_nonebot_event`（`__init__.py:1263-1283`）对 NoticeEvent 族 `get_plaintext` ValueError 降级空文本 | ②③④（handler 内回复） |
| B 调度 job 路径（无 Event） | `_deliver_due_reminders` 范式（`__init__.py:2852-2956`）：构造 SendRequest→`send_queue.submit`→`_find_sent_request`→内联 `_deliver_transport_send_request(bot, None, …)`→SENT/REDIRECTED 才销账 | 行为面 `tests/test_reminder_delivery.py` 全覆盖（转引自 WIRE-DIRECT 日志 §一，本席未逐例复核） | ①（cron job 无事件） |
| C 副作用执行器路径 | `OutboundSideEffectExecutor`（`control_plane/dispatcher.py:125-220`）：cancel 前置闸→准入复验→租约线性化→Transport 固定映射（绝不拼 API 名）→`call_api` 通道本体 | L34/L35 已收编 poke/表情（`__init__.py:4862-4918`、`domains/meme/reactions/engine.py:661-702`）；测试 `tests/test_v21_dispatch_outbound_wiring.py`（20+ 例） | 本批四处**不适用**（均为有内容消息/文件，应走 A/B/D 获得 review/回执/幂等；executor 适合原子副作用）；仅作为「同批先例形态」引用 |
| D 文件路径 | `CapabilityResult.files` → media_parts（`domains/render/renderer.py:214-216`）→ transport file 部件 → `get_default_file_gateway().stage→deliver`（`domains/transport/sender/onebot.py:439-462`） | 行为测试 `tests/test_phase0_3_features.py:180` | ④ |

出站协议对齐：`docs/design/backend-protocol-plan.md` B2③ 组动作描述即本方案母题（:160「把绕过统一出站路径的直连点收编」）；SendRequest 契约=`domains/core/contracts/runtime.py:294-334`（dedupe_key/cooldown_key 非空强校验 :319-322；adapter/bot_id 字段供无 Event 投递选 bot :307-308）；SendQueue 协议=`domains/transport/sender/queue.py:167-168`（唯一出站咽喉 `submit`）。

### 3.1 收编①：cookie 到期提醒 → 形态 B（提醒范式）

- **改法**：`_cookie_expiry_reminder_job`（:4264-4310）内，报告产出后不再 `bot.call_api`，改为逐管理员构造 `SendRequest`（capability_id=`bot.cookie_expiry_notice`；request_id/dedupe_key 带日期=`cookie-expiry:{admin_id}:{YYYY-MM-DD}`——顺带获得**当日幂等**，治现实现理论上的重复打扰面；session_id=`private:{admin_id}`；target_scope=PRIVATE；`RenderedOutput(content_type="text", text_fallback=report)`；adapter/bot_id 取所选 bot）→ `send_queue.submit` → `_find_sent_request` → `_deliver_transport_send_request(bot, None, …)`。**管理员换人重试语义逐字节保持**：首个管理员投递回执非 SENT/REDIRECTED 才换下一个（与现 break/continue 等价）。
- **门/配置键（缺省关）**：新增 `bot_cookie_expiry_reminder_via_queue`（bool，**缺省 False**）。False=维持现直连（零行为变更）；True=走统一路径。登记 config.py + config-catalog + .env.example（按项目既有三件套惯例；键名实施席可议，语义必须「缺省关+可配置回滚」）。
- **测试策略**：新增离线测试（fake send_queue + fake bot 断言）：a) 开关 False→`call_api("send_private_msg")` 被调（锁旧路径不回归）；b) 开关 True→零 `call_api` 直发、`send_queue.submit` 恰一次、SendRequest 字段断言（capability_id/dedupe_key 含日期/target_scope）；c) 首管理员失败回执→换第二管理员且 dedupe_key 按管理员区分；d) 全部失败→不销账不抛出（静默语义保持）。
- **风险与回滚**：风险=SendQueue 内联投递路径上 `_select_queue_bot` 选 bot 语义与现 `_select_credential_bot` 的差异（unknown：两选 bot 函数择优口径未逐行比对，实施席须核对）；回滚=配置键拨回 False 即刻恢复直连，零代码回退。

### 3.2 收编②：入群欢迎 → 形态 A（管线统一发送）

- **改法**：`_handle_group_increase`（:5143-5191）欢迎发送行（:5184-5187）替换为 `await _send_text_through_unified_pipeline(bot, event, _group_welcome_text(nickname), capability_id="bot.group_welcome")`。昵称富集 `get_group_member_info`（:5169-5175）**保持不动**（读路径，登记表 READ_PATH 口径一致）。
- **前置可行性（verified）**：notice 事件可进摄取——`_incoming_from_nonebot_event`（`__init__.py:1278-1283`）对 NoticeEvent 族 `get_plaintext` 抛 ValueError 时降级空文本，`group_id`/`user_id` 走属性面（:1289-1303），`_run_capability_through_pipeline` 由此正常建 IncomingMessage。**残余 unknown**：GroupIncreaseNoticeEvent 的 `get_session_id()` 返回形态（决定 session_id/dedupe_key 形态）未实测，实施席以 NoneBot 适配器源码或 fake event 断言钉死。
- **门/配置键（缺省关）**：新增 `bot_group_welcome_via_queue`（bool，缺省 False；与既有 `bot_group_welcome_enabled` 双门串联，任一关即不发/走旧路）。
- **测试策略**：a) 开关 False→`call_api("send_group_msg")` 被调（旧路径锁）；b) True→零直发、走 fake pipeline 面断言 CapabilityResult（capability_id=bot.group_welcome，body=欢迎文本）；c) `bot_group_welcome_enabled=False` 时两形态均零发送；d) 昵称富集失败→通用称呼文本进 CapabilityResult（沿 `test_group_notice_b05.py` 文本断言口径）。
- **风险与回滚**：风险=统一管线会给欢迎语过 review/渲染（现直连无此环节），若 review 拦截规则误伤欢迎语文案则欢迎静默失败——实施时确认 `safe_text` 通过路径；发送成功事件日志（:5188）须迁移到回执态判断处。回滚=拨回 False。

### 3.3 收编③：二维码图片 → 形态 A（mixed 图片件）

- **改法**：`_handle_admin_cookie` login 分支（:5471-5494）：文本 `login_text` 与图片合并为一次 `_send_parts_through_unified_pipeline(bot, event, text=login_text, image="file:///" + png_path.replace("\\\\", "/"), capability_id="bot.cookie_login")`（:4694-4741 已支持 images→kind=mixed；`renderer.py:206-208` images→media_parts；transport `_image_segment`（`onebot.py:326-339`）`_resolve_local_file_ref`（:315-322）解析本地路径——**`file:///` 形态与现直连段逐字节同构**）。若实施席判定「文本先达、图片后达」的时序语义有产品价值，则保留两次调用：文本一次 text、图片一次 parts（kind=mixed 仅图片）——两种子形态任选，均为统一路径。
- **门/配置键（缺省关）**：新增 `bot_cookie_qr_via_queue`（bool，缺省 False）。
- **测试策略**：a) 开关 False→图片 `call_api("send_group_msg"/"send_private_msg")` 被调（旧路径锁）；b) True→零直发、CapabilityResult.images 断言含 `file:///` 引用且 body 含 login_text；c) png_path 为空→仅文本、零图片件；d) 图片链失败→receipt 非 sent 且**不抛出**（失败静默语义保持）。
- **风险与回滚**：风险=管理员命令面多一层 review（与②同风险同解法）；图片经 mixed 件发送时 transport 的 extra_parts 组装（M17 语义，`onebot.py:444-451`）与现直连单段消息的报文形态可能有别（unknown：SnowLuma 对段序的容忍度，真机验收项）。回滚=拨回 False。

### 3.4 收编④：文档导出上传 → 形态 D（文件网关链）

- **改法**：`_handle_admin_file_export`（:5265-5321）上传段（:5301-5315）替换为统一管线发送，capability 返回 `CapabilityResult(files=[{"file": str(path), "name": path.name}], body=成功文案)`——链路=`render_reviewed_output` files→media_parts（`renderer.py:214-216`）→transport file 部件→`get_default_file_gateway().stage→deliver`（`onebot.py:439-462`）→`FileTransferGateway._deliver_onebot` 上传（群 `upload_group_file`/私聊 `upload_private_file`，`domains/transport/sender/file_gateway.py:359-391`）。**平台方法面与现直连逐字节一致**（同两 API 名），行为测试已有（`tests/test_phase0_3_features.py:180`）。成功/失败文案改由回执态驱动（现 :5316-5318 失败文案逻辑迁到 receipt 判断）。
- **门/配置键（缺省关）**：新增 `bot_file_export_via_queue`（bool，缺省 False）。
- **测试策略**：a) 开关 False→`call_api("upload_group_file"/"upload_private_file")` 直调（旧路径锁）；b) True→CapabilityResult.files 断言+transport fake 断言首调用=upload_*（对齐 `test_onebot_upload_api_not_fake_file_segment` 断言风格）；c) 上传失败→失败文案经统一管线发出且零异常上抛；d) 群/私聊分支参数断言（group_id/user_id）。
- **风险与回滚**：风险=文件件走管线后受 `max_messages`/分片策略影响（现直连一次上传一发即达；unknown：mixed file+text 组合在本管线中对超大文件的预算切片行为——`_resolve_call_timeout` 切片语义 `file_gateway.py:337-349` 已有，但与 `budget.slice_for(calls)` 的组合行为须实施席实测）；回滚=拨回 False。

### 3.5 收编⑤：登记表刷新（纯维护，非行为变更）

- **改法**：`domains/core/decision/outbound_registry.py` 逐条更新 §二⑤表：三条 BYPASS_SUSPECT 坐标改指现坐标并挂本方案编号；SEND_MESSAGE evidence 字符串（:183-187）同步；poke/reaction 两条（:205-216）状态改「已收编（L34/L35，executor 面坐标）」；delete_msg 坐标 :4569→:4802（读时快照）；file_gateway 条目路径改 `domains/transport/sender/` 并按 §二④裁定建议改 CHANNEL_BODY（final 归 DELIVERY-001 owner 复核）。若登记表有自检测试锁坐标字面量，随测试同改（unknown：未逐测排查，实施席 grep `4070\|4878\|5175` tests/ 确认）。
- **门/配置键**：无（纯文档性数据面）。
- **测试策略**：改后跑 `tests/test_v21_wiredirect_unified_path.py`（结构锁口径引用 DirectSendEntry，:34-46）+ decision 域既有测试全绿。
- **风险与回滚**：极低（数据面、无行为）；回滚=单文件 revert。

### 3.6 明确不收编清单（防扩界）

- 欢迎昵称富集 `get_group_member_info`（`__init__.py:5169-5175`）与文件接收 `get_file`/`download_file`（:5230/5234）、转发反查 `get_forward_msg`（:1027/1041/7806）、`get_record`（:1137）、`get_stranger_info`（:2214-2218）——全部 READ_PATH（登记表 :629-646 既有甄别）。
- `delete_msg`（:4802）——BY_DESIGN 撤回，非消息投递。
- `domains/transport/sender/file_gateway.py:377-391` 内环 `call_api`——统一路径自身通道本体（§二④裁定建议），收编它=收编统一路径本身，语义不通。

---

## 四、责任面划界

| 项 | 文件 | 现在能否动 | 依据 |
|---|---|---|---|
| ①②③④ 行为收编 | 根 `__init__.py`（:4264-4320 / :5143-5191 / :5471-5494 / :5265-5321 读时快照） | **否——必须等 WIRE-SVC 席交付释放后**。该文件正被 WIRE-SVC 在飞编辑服务装配段（协调表 ：9 认领行：根 `__init__.py` 服务装配插入段归 WIRE-SVC；WIRE-DIRECT 日志实证行号两度漂移） | 协调表让步记录 + 本席读时快照口径 |
| ①④ 新配置键 | `config.py` + `docs/config-catalog-full.md` + `.env.example` | **冲突面核查后可动**：WIRE-SVC 认领行含 `config.py:174-178 三键追加` 与 catalog/env-example——同文件不同区段，须与 WIRE-SVC 错峰或待其交付 | 协调表 ：9 |
| ⑤ 登记表刷新 | `domains/core/decision/outbound_registry.py` | **现在即可动**（无席位写域认领；WIRE-DIRECT 仅只读并移交「修订归该表 owner」） | WIRE-DIRECT 日志 §五.4 |
| ③④ 对应 capability 侧（若采用独立 capability 函数形态） | `domains/**` 或根内联闭包 | 方案按内联闭包设计（沿 `_send_text_through_unified_pipeline` 现役形态），不新增 domains 文件，避开 domains 在飞席位 | 本方案 §3.2-3.4 |
| 新增测试 | `tests/test_v21_direct_collect.py`（建议名） | 现在即可动（新文件零冲突） | — |
| file_gateway PENDING_RULING 终裁 | `domains/transport/sender/file_gateway.py`（无需改码，仅登记状态） | 状态裁定归 DELIVERY-001 owner；本方案只交建议 | 登记表 ：631-634 |

---

## 五、工作量级与建议执行顺序

| 序 | 工作项 | 量级 | 依赖 |
|---|---|---|---|
| 0 | ⑤ 登记表刷新（含 PENDING_RULING 建议落状态） | S（半天内；逐条改数据+跑结构锁） | 无（现在即可） |
| 1 | ④ 文档导出收编（形态 D） | S-M（链路已存在+已有行为测试模板，改动面=handler 上传段+开关+4 例测试） | WIRE-SVC 释放根 `__init__.py` |
| 2 | ② 入群欢迎收编（形态 A） | S-M（同上；多一项 notice 摄取 unknown 钉死） | 同上 |
| 3 | ③ 二维码图片收编（形态 A mixed） | S（最薄：一次调用替换） | 同上 |
| 4 | ① cookie 提醒收编（形态 B） | M（无 Event 路径+管理员换人语义保持+选 bot 口径核对） | 同上 |
| 5 | 真机验收（重启后）：四处各触发一次，回执仓/审计/日志三面取证 | M（须用户提权重启窗口） | 1-4 全部落地+用户授权重启 |

排序理由：⑤零风险先行清账；④→②→③ 按链路成熟度递减（④链路最全、③最薄）；①最后（唯一无 Event 路径，需选 bot 口径核对）。四处共享「开关缺省关+旧路径锁测试」模式，可一批实施分次验收。

**批量前置检查单（实施席开工第一步）**：a) 符号 grep 重定位四处坐标（行号必漂）；b) `git status` 确认 WIRE-SVC 已交付根 `__init__.py`；c) config 键三件套与 WIRE-SVC 区段错峰确认。

---

## 六、证据状态汇总

- verified：五处坐标与行为面（本席逐处实读源码）；统一路径四形态载体与行号；renderer/transport 文件件与图片件支持；ingress 对 notice 降级；登记表陈旧逐条比对；L34/L35 先例形态（代码实读）。
- 转引（未亲证）：`tests/test_reminder_delivery.py` 覆盖面描述（WIRE-DIRECT 日志）；L34/L35 收编的交付时间线（席位日志）。
- unknown（已在文中标注）：GroupIncreaseNoticeEvent 的 `get_session_id()` 形态；`_select_credential_bot` vs `_select_queue_bot` 择优口径差异；mixed 图片/文件件在 SnowLuma 真机的段序容忍度；超大文件过管线的预算切片组合行为；登记表坐标字面量是否被测试锁定。
- 全局诚实声明：本文档为零改动方案材料；「收编后」「应替换」均为设计意图；矩阵零改动；无 commit/无重启/无部署/无真实发送。

——DIRECT-PLAN 席（2026-09-19）。
