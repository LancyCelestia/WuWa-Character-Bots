# U17-CAMPUS-WIRE 裁定卡 + 实施 runbook（v21r5 U17-PLAN-2 席，2026-09-20）

> **文档身份**：纯文档席产出，供用户裁决「U17-CAMPUS-WIRE 是否实施」。**零代码改动**——本席未改任何
> .py 文件、未碰 root `__init__.py`、未 commit、未重启、未读 `.env` 明文值。
> 一切「事实/实测」均为本席逐文件实读或引自带实跑证据的前席记录；无实证据处标注 unknown。
> 证据基线：`docs/design/audit-20260920-unify-U17-campus-wire.md`（U17 取证 §0 完整）+
> `docs/design/v21r5-CAMPUS-log.md`（CAMPUS-FIX-9 终态 18P/11xF + CAMPUS-XFAIL 挂账）+
> 本席实读（坐标逐一列出，行号为 2026-09-20 实读值，会漂）。

---

## 一、裁定卡（用户裁决面）

### 1.1 U17 是什么

一句话：**把校园自动转发的出站面从「handler 内自建 SendRequest + 裸 `send_queue.submit` 旁路」收编进
中央管线**（`pipeline.handle_async` → `_prepare` 门禁/幂等 → 能力 → `_complete` 统一构造 SendRequest
入队），删除旁路。**零新机制**：无第二 submit 通路、无 target 改写框架、无新配置键（audit §0.3 复核结论）。

「异会话投递」（学校群消息 → 主人私聊）用项目既有表达：**按目标会话合成 `IncomingMessage` 交给中央管线**，
三处同构先例全部在 root `__init__.py`（今天历史推送 `:1832-1875`、订阅推送 `:4329-4353`、ops 告警）。

**现状实测（verified）**：

| 件 | 状态 | 坐标 |
|---|---|---|
| 旁路在岗 | 是：`send_queue.submit(request)` 直入队，绕过门禁/review/中央幂等 | root `__init__.py:5044` |
| 验收规约 | 已立：`tests/test_campus_digest.py` 29 例 = 18 绿 + 11 xfail（U17 规约诚实挂账） | CAMPUS-XFAIL 席实跑定版 |
| 纯函数（verbatim 契约） | 已就位：`build_campus_forward_text`，与改前旁路逐字节互证 | `domains/assistant/campus/campus.py:81-90` |
| 注册登记 | 已就位：`bot.campus_forward` 入 `CONTROLLED_INTERNAL_CAPABILITIES`，绑定/描述符自动派生 | `capability_registry.py:544` |
| 出站登记 | 已刷新：location 5012/priority 8/note 记 U17 指定 | `outbound_registry.py:433-444` |
| 两 builder | **全树零存在**：`build_campus_forward_message` / `build_campus_forward_capability` | grep 实证 |
| record() 返回 | 过渡态：`CampusForwardRequest(SendRequest)` 子类脚手架（仅加 body property） | `campus.py:93-104` |

### 1.2 不实施后果（维持现状）

1. 11 例 xfail 永久挂账——strict=False 不炸套件，但**规约与生产长期背离**，后续接手者需每次重新考古。
2. 旁路长期在岗的实际代价（每条均实测）：
   - **控制面停用对 campus 无效**：旁路不经 feature_gate，控制面把 `bot.plugin.campus_forward` 停了转发照发；
   - **runtime 暂停不拦**：全局/能力暂停期间校园转发照发（旁路不理会）；
   - **无 review**：源群原文（含密钥/路径形态）不经任何审查直达主人私聊；
   - **无中央幂等第二层**：只有 store 侧 message_id 幂等单保险；
   - **审计面缺门禁轨迹**：_prepare/_complete 各阶段审计记录全无，只有队列审计。
3. root `__init__.py` 后续每次相关重构都要绕着这段旁路做豁免（结构锁测试已把「旁路该死未死」钉成显式 xfail）。

### 1.3 实施收益

1. **门禁统一**：feature_gate fail-closed 可控停用（未登记即 BLOCK，登记已备妥）；runtime 暂停生效；
   中央幂等双保险（`bot_event_idempotency_enabled` 开启时）。
2. **审计统一**：_prepare（policy/budget/limit）→ review → render → queue 全链审计轨迹。
3. **删除旁路构件**：campus 域源码零 `SendRequest`/裸 submit/平台发送 API——「绝不向学校群发消息」获得
   结构锁第二重保障（`test_handler_isolated_and_send_api_free` 转绿后永久在岗）。
4. 测试全绿态 29/29，规约-生产一致，campus 域测试债清零。

### 1.4 实施风险（两项大风险 + 行为差清单）

**风险一（最高）：root `__init__.py` 多会话共享。** 在飞席 S0-ROOT-c（根 init 直连收编）与本席改同一文件
（CAMPUS-FIX-9 移交清单第 2 条已点名「需主会话协调先后」）。缓解：主会话排程互斥，两席不并行开根文件；
本 runbook 把根文件改动压缩到 2 处（§2.2）。

**风险二：校园纯监听红线。** 「对学校群只读不写」是 #33 批硬约束。收编**不改**三重来源门、不改 matcher
（仍 priority=8/block=False 只读监听）；且 `test_no_outbound_request_ever_targets_school_group` 转绿后，
「任何出站请求不以学校群为目标」获得中央 review 层负锁（PERSONAL 正文喂群会话=结构性 BLOCK）。红线零削弱。

**行为差清单（收编后 vs 旁路，全部为与推送先例同构的既有管线语义，非新造）**：

| # | 差异 | 方向 | 说明 |
|---|---|---|---|
| 1 | 源群文本经 review 门 | 需裁决（裁定点①） | 旁路零审查；收编后泄漏面命中即 BLOCK |
| 2 | 截断满额 1501 字可能转合并转发 | 需裁决（裁定点②） | 取决于生产 `bot_render_forward_min_chars` |
| 3 | runtime 暂停期间转发被拦 | 收编本意 | 旁路不理会暂停 |
| 4 | offload 池饱和时该条 SKIPPED | 低概率 | `offload_capability` gate（pipeline.py:225-237）busy→SILENT_AUDIT→SKIPPED；旁路无此门。学校群流量低，与全部推送能力同语义 |
| 5 | send_policy QUEUED→IMMEDIATE | 无实际差 | _prepare 决策恒 IMMEDIATE（pipeline.py:668）；订阅/今天历史推送同此值，生产投递正常；同一 SQLite 队列 worker 投递，UNKNOWN 确认/PARTIAL 续发语义不变 |
| 6 | dedupe_key 公式变化 | 等价 | `campus_fwd:<mid>` → `bot.campus_forward:private:<owner>:<mid>`（pipeline.py:818-821），同为 message_id 级去重 |
| 7 | cooldown_key 变化 | 惰性 | 转 policy 键；非 chat 能力限流恒 bypass（audit §0.4），该键实际不产生节流 |
| 8 | adapter 字段 "" → "onebot.v11" | 改善 | SendRequest.adapter 由 message 带出，队列选 bot 多一个提示位 |

### 1.4a 勘误注记（2026-09-20 FIX-U17 席增补，只加注不改上表/裁定①原文）

上表 #1 与裁定①「密钥/**路径**形态命中即 BLOCK」中「路径」半句与实现不符（U17-REVIEW-3
python 探针实测）：reviewer `_unsafe_output_reasons` 实际拦截面=api_key/token/cookie/authkey、
`authorization: Bearer`、`bearer sk-`、裸 `sk-`（≥9 字符）与注入标记——**不含盘符路径、
不含 `BOT_XXX=`**；这两类改前原文直达主人。FIX-U17 修复后的实际行为分三路：

1. **打码直达**（新增）：转发正文出域前过 `redact_local_secrets`——`BOT_XXX=`/盘符路径/
   裸 `sk-` 形态打码后**不再命中 review**，主人收到的是打码版（`<已隐藏>`/`<本机路径已隐藏>`），
   信息流与安全兼得；
2. **拦截+可观测**（新增）：`token=`/`cookie=`/`authorization: Bearer` 等键值形态打码后仍命中
   review 词面（设计如此）→ BLOCK；且一切 BLOCK（review 泄拦/门禁停用/运行时暂停）不再静默——
   handler 走既有运行时告警通道发一条告警（stage=campus、kind=blocked_<transport>、
   detail=capability+目标会话，**不含源文本原文**），日志同步留痕守岸人一句话
   「有一条校园消息因安全门未送达」；
3. **永久丢失语义补充**（上表 #3 与裁定①④的勘误）：BLOCK 后该条 store 已记账、同 id 重放
   不再进管线=不可恢复，暂停窗口内的教务通知不可重放——现至少有告警+日志可事后知晓，
   完全静默语义已消除，但「不可恢复」属性仍需用户知情。

回归锁：`tests/test_campus_digest.py` ⑤节两例（打码断言+BLOCK 告警断言）。

### 1.5 两裁定点（audit §4 自标「必须用户过目」，实施前须裁决）

#### 裁定点①：源群文本含密钥/路径形态是否过 review 门

- **事实**：收编后 `review_capability_result` 对能力 body 跑泄漏面扫描（reviewer.py:156-174，
  `_unsafe_output_reasons`：密钥/内部标记形态命中即 BLOCK；persona drift 仅对 bot.chat 生效，campus 豁免）。
  BLOCK 的后果（pipeline.py:731-753）：该条**不转发**、主人收不到、审计留痕（stage=review）。
  旁路现状 = 完全不经 review，密钥/路径形态**原文直达**主人私聊（无打码）。
- **选项 A（推荐）：接受 review 门（fail-closed）。**
  理由：①与「密钥不入聊天/出站打码」全局铁律同向——旁路把未打码的密钥形态文本送进聊天出口本就是
  既有缺口，收编顺带补上；②学校群是教务通知场景，触码概率低，只拦形态命中的极少数条；
  ③BLOCK 有审计可回查，不是黑洞；④无中间态可选——给 campus 开 review 豁免=新造机制，
  被「零新框架」规约禁止，且等于对转发通道豁免密钥审查，安全上倒退。
- **选项 B：不收编（维持旁路）。** 该风险面不引入，但 §1.2 全部代价继续存在。
- 建议裁决：**A**。

#### 裁定点②：1501 字边缘消息转合并转发

- **事实**：verbatim 契约把截断预算钉死在 1500（测试 oracle `_legacy_forward_text` 硬编码
  `1500`，`build_campus_forward_text` 逐字节对齐，`campus.py:34` `_CAMPUS_FORWARD_MAX_CHARS = 1500`）
  → 截断满额的转发正文恰为 **1501 字**（前缀+1491 字+省略号，测试断言 len==1501）。
  中央 `_complete` 的合并转发触发：`should_forward_long_text(min_chars=pipeline.forward_min_chars)`，
  生产取 `config.bot_render_forward_min_chars`（root `__init__.py:3772`）——**代码缺省 1500、
  `.env.example` 样例 0**（audit §0.4）。生产现值本席禁读 .env，**unknown**。
  若生产值=1500：原文 ≥1491 字被截断满额的那条消息会以合并转发（约 2 节点）形态出现在主人私聊；
  若生产值 <1501（如 0）：永不转换，形态与旁路完全一致。
- **选项 A（推荐）：接受，零改动。**
  理由：①只影响截断满额的长消息（低频边缘）；②合并转发 2 节点可读性可接受；
  ③改截断预算（如 1500→1498）会破坏 verbatim oracle 契约，测试返工且违背「收编不改用户可见形态」
  的收编初衷；④若用户嫌合并转发形态，可自行调生产 `BOT_RENDER_FORWARD_MIN_CHARS ≥ 1502`
  （纯配置面动作，不动代码，但注意该键全局作用于所有非 chat 能力的合并转发阈值）。
- **选项 B：实施时顺带改 `_CAMPUS_FORWARD_MAX_CHARS`。** 需同步重写 verbatim oracle 与 1501 断言，
  契约返工，不推荐。
- 建议裁决：**A**；实施前由用户或实施席确认生产 `BOT_RENDER_FORWARD_MIN_CHARS` 现值（本席未验证）。

---

## 二、实施 runbook（用户裁决 A/A 或 B 后，由实施席执行）

### 2.0 前置条件与红线

1. 用户已过目 §1 裁定卡并对两点做出裁决；若裁②选 B，先按 §2.6 的契约返工路径修订本 runbook 再开工。
2. **主会话排程互斥**：root `__init__.py` 与 S0-ROOT-c 不并行开工；开工前确认该席不在根文件写程中。
3. 开工先打 **diff 快照**（工作树未提交，这是回滚唯一依据，§2.6）：
   `git diff -- plugins/bot_unified_runtime/domains/assistant/campus/campus.py plugins/bot_unified_runtime/__init__.py tests/test_campus_digest.py plugins/bot_unified_runtime/domains/core/decision/outbound_registry.py > /tmp/u17-baseline.diff`（落 %TEMP%）。
4. 红线：绝不向学校群发任何消息（三重来源门一字不动）；禁真实发送/重启/.env 读值/子代理/git 写。

### 2.1 campus.py（`domains/assistant/campus/campus.py`）

**契约前提**（结构锁 `test_handler_isolated_and_send_api_free` 转绿即生效）：域文件禁出现
`SendRequest`、`RenderedOutput`、`SendPolicy`、`call_api`、`send_group_msg`、`send_private_msg`
字面量 → 现 `CampusForwardRequest` 子类与 `_build_forward_request` 必须撤除。

**两 builder 签名与测试期望对照**（测试是规约，签名以下表为准，逐条对应断言坐标）：

| builder | 签名 | 测试期望（断言来源） |
|---|---|---|
| `build_campus_forward_message` | `(source: CampusSource, payload: CampusForwardPayload) -> IncomingMessage` | test_forward_message_expresses_owner_private_target：`session_id=f"private:{source.notify_qq}"`、`session_type is SessionType.PRIVATE`、`sender_id == source.notify_qq`、`group_id is None`（目标私聊绝不能带学校群号）、`bot_id == source.push_bot_id`（选通道语义）、`message_id == payload.message_id`（中央幂等 claim 键来源）、`privacy_level.value == "personal"`（显式传 `PrivacyLevel.PERSONAL`） |
| `build_campus_forward_capability` | `(source: CampusSource, payload: CampusForwardPayload) -> 能力闭包` | test_complete_enqueues_owner_private_request_end_to_end（经真管线后）：`content.text_fallback == payload.body`、`content_type=="text"`、`privacy_level is PERSONAL`、`origin_message_id=="m1"`（来自 message.message_id）、`persona_profile_id == source.persona_profile_id`（经 audit_tags `persona:<id>`，机制=pipeline.py:293-302）、`"campus" in audit_tags and "forward" in audit_tags`、`dedupe_key == f"bot.campus_forward:private:{owner}:m1"`（_complete 公式自动满足，勿自造） |

**施工步骤**：

1. **撤脚手架**：删 `CampusForwardRequest`（campus.py:93-104）；contracts import 收窄——去
   `RenderedOutput/SendRequest/SendPolicy`，增 `IncomingMessage/CapabilityResult/RiskLevel`
   （`PrivacyLevel/SessionType` 保留）。
2. **增载荷**：`@dataclass(frozen=True) class CampusForwardPayload`，五字段
   `group_id/sender_name/text/message_id/body: str`。测试期望面：`_recorded_body` 用 `.body`
   （test_campus_digest.py:503-528）、builder 用 `.message_id/.body`。
3. **record() 转 payload**：`_build_forward_request`（:163-195）改名/改形为 `_build_forward_payload`，
   `body = build_campus_forward_text(...)`（单一事实源不变，逐字节契约不动）；`record()` 返回注解
   `CampusForwardPayload | None`；请求级字段（session_id/dedupe_key/capability_id/send_policy/
   max_messages/cooldown_key 等）**全部删除**——这些由中央 `_complete` 统一推导（对照表见 §1.4 行为差
   #5/#6/#7，均有先例背书）。
4. **builder 一（消息）**：字段映射沿订阅推送先例（root `__init__.py:4337-4347`）：
   `platform="nonebot"`、`adapter="onebot.v11"`（测试不断言，取先例值）、`bot_id=source.push_bot_id`、
   `session_id=f"private:{source.notify_qq}"`、`session_type=SessionType.PRIVATE`、
   `sender_id=source.notify_qq`、`group_id=None`、`plain_text=payload.body`、
   `raw_segments=[{"type": "text", "data": {"text": payload.body}}]`、
   `message_id=payload.message_id`、`privacy_level=PrivacyLevel.PERSONAL`。
5. **builder 二（能力）**：闭包 `(message, _decision) -> CapabilityResult`，先例=
   `build_subscription_push_capability`（content_parser.py:550-569）：
   `request_id=message.request_id`、`capability_id="bot.campus_forward"`（**字面量保留在域内**——
   字面量门 `test_campus_capability_id_literals_all_registered` 要求两文件合计恰此一个 id）、
   `kind="text"`、`body=payload.body`、`risk_level=RiskLevel.LOW`、
   `privacy_level=PrivacyLevel.PERSONAL`、
   `audit_tags=["campus", "forward", f"persona:{source.persona_profile_id}"]`。
6. **旧段两例同步重写**（tests/test_campus_digest.py，授权=CAMPUS-FIX-9 移交清单第 1 条
   「届时撤 CampusForwardRequest 子类脚手架并同步重写旧段两例」；其余 16 绿例一字不动）：
   - `test_record_builds_private_forward_request`（:137-158）：SendRequest 级断言全部改 payload 级
     （`payload.message_id=="m1"`、`payload.body` 前缀/含群号/发言人/原文；请求级断言由
     `test_complete_enqueues_owner_private_request_end_to_end` 承接，不重复）；
   - `test_record_long_text_truncated`（:197-205）：`request.content.text_fallback` → `request.body`。
   - 不删任何用例，用例总数 29 保持稳定。

### 2.2 root `__init__.py`（共享文件，改动压缩到 2 处）

**行号耦合警告**：`outbound_registry.py:435` 硬编码 matcher 坐标 `__init__.py:5012`，而
`test_outbound_registry_campus_coordinate_is_live` 以实读行号互证。**在 :5012 之上的任何增删行都会
打断坐标门**。因此：import 用原地扩展（零增行），handler 改动全部在 matcher 定义之下 → 坐标不漂、
登记零动作。若因合并冲突等原因在上方产生了行数变动：实读新行号后同步刷新
`outbound_registry.py` campus 条目 location（唯一允许的额外改动）。

1. **:36 import 原地扩展**（零新增行）：
   `from .domains.assistant.campus.campus import build_campus_source` →
   `from .domains.assistant.campus.campus import (build_campus_forward_capability, build_campus_forward_message, build_campus_source)`。
   模块级导入使 handler 以全局名引用（AST 提取测试的注入接缝即按全局名设计）。
2. **handler 尾段改写**（现 :5034-5044；`campus_source` :3688、`pipeline` :3747、
   `offload_capability` :3588 均已在同函数作用域，实读核实）：
   - `request = await asyncio.to_thread(campus_service.record, ...)` → `payload = await asyncio.to_thread(...)`（参数零变化）；
   - `if request is not None: send_queue.submit(request)` 替换为：
     ```python
     if payload is not None:
         message = build_campus_forward_message(campus_source, payload)
         capability = build_campus_forward_capability(campus_source, payload)
         try:
             await pipeline.handle_async(
                 message,
                 offload_capability(capability),
                 capability_id="bot.campus_forward",
             )
         except Exception:  # noqa: BLE001 - 转发失败不影响监听主链路。
             logging.getLogger(__name__).exception("校园转发经中央管线失败")
     ```
   - 结构锁自检（`test_handler_isolated_and_send_api_free`）：handler 内名字含 `pipeline`、
     不含 `send_queue`；属性不含 `submit`/`call_api`/`send_msg`/`send_group_msg`/`send_private_msg`。
3. **不改**：matcher 定义与 rule（:5009-5014）、三重来源门、装配段（:3687-3701）、
   handler 前半采集逻辑（:5018-5033 逐字节保留）。
4. **无需** `_find_sent_request`+内联投递（两先例里那是调度器侧专用；campus 与旁路时代同样走
   SQLite 队列 worker 投递，测试也只断言入队）。

### 2.3 注册面：零动作

`bot.campus_forward` 登记（`capability_registry.py:544`）、`bot.plugin.campus_forward` 自动绑定、
descriptor 自动建节点均由 CAMPUS-FIX-9 备妥并有实跑证据（F3/feature_gate/subfeatures 合跑 57 passed）。
无剩余动作；**不要碰 feature_catalog.py**。

### 2.4 11 处 xfail 摘牌

`tests/test_campus_digest.py` 全文件搜 `U17-CAMPUS-WIRE` → 恰 11 处装饰器（reason 逐字节一致，
CAMPUS-XFAIL 席 `sort -u` 实证唯一形态），逐一删除装饰器行。strict=False 下漏摘只会 XPASS 不炸套件，
但摘牌是实施席的收尾职责。清单：test_handler_dispatches_through_central_pipeline /
no_forward_outside_source_gate / source_gate_rejects_foreign_group / duplicate_message_id_forwards_once /
isolated_and_send_api_free / forward_message_expresses_owner_private_target /
complete_enqueues_owner_private_request_end_to_end / no_outbound_request_ever_targets_school_group /
quiet_hours_and_rate_limit_do_not_swallow / central_claim_adds_second_idempotency_layer /
campus_forward_registered_for_feature_gate。

### 2.5 验收（全部实跑，附输出原文）

1. **主验收**：`pytest tests/test_campus_digest.py -p no:cacheprovider --basetemp=$TEMP/u17-verify -q`
   → **29 passed / 0 failed / 0 xfailed**（11 例转绿 + 2 例重写例绿 + 16 例零触碰照旧）。
2. **棘轮族合跑**：test_campus_digest.py + test_outbound_v21.py + test_v21_f3_outbound_capability_registration.py
   + test_runtime_feature_gate.py + test_runtime_subfeatures.py 全绿。
   注意：`test_runtime_feature_gate.py::test_main_ingress_capability_ids_are_registered` 存量基线 FAIL
   （缺登记的是 S0 收编四条 `bot.cookie_expiry_notice/bot.cookie_login/bot.file/bot.group_welcome`，
   audit §0.5/§6）——**不在本席范围，勿扩权代修**，campus 定向门
   `test_campus_capability_id_literals_all_registered` 才是本域门。
3. **坐标门**：test_outbound_registry_campus_coordinate_is_live 绿（若红=根文件上方行数变了，
   按 §2.2 刷新 registry location 后复跑）。
4. **静态门**：ruff（campus.py / test_campus_digest.py / root `__init__.py`）All checks passed；
   mypy 项目口径（630 文件基线）无新增错误。
5. **全量**：`dev.ps1 -Task test`（计数以实跑为准）+ `-Task lint/typecheck/runtime-layout`。
6. **真机**（重启后，用户手动）：acceptance-manual §6.6 校园段——学校群来消息 → 主人私聊收到
   【校园转发】；安静时间/限流开启下仍转；控制面暂停 campus 时停转（收编新能力，顺手验）。

### 2.6 回滚方式

1. **代码回滚**：按 §2.0 diff 快照逆向恢复 campus.py / root `__init__.py` / test_campus_digest.py
   （若动过 outbound_registry.py 一并恢复）。恢复后重挂 11 xfail（reason 唯一形态见 CAMPUS-XFAIL log），
   全文件应回到 18P/11xF。
2. **运行态回滚**：重启回旧代码即回旁路（铁律：改码必须重启才生效）；SQLite 队列无 schema 迁移、
   campus.sqlite3 store 结构不变，双向无数据负担。
3. **不回滚项**（与实施解耦的既成事实，CAMPUS-FIX-9 收编）：纯函数 build_campus_forward_text、
   注册登记、outbound 坐标刷新——三者在「不实施 U17」的现网也是正确事实。

---

## 三、工作量与风险评估

| 维度 | 预估 |
|---|---|
| 文件数 | 必改 3（campus.py / root `__init__.py` / test_campus_digest.py）+ 条件 1（outbound_registry.py 坐标，仅当根文件上方行数变动） |
| 改动行数 | campus.py 约 ±90 行 churn（撤 47 行脚手架、增 payload+两 builder 约 75 行，净 +28）；root `__init__.py` 约 20 行（import 1 行原地扩展 + handler 尾段 11→16 行）；测试约 45 行（11 行装饰器删除 + 2 例重写 ~30 行）；净增约 +60 行 |
| 测试面 | campus 全文件 29 例 + 棘轮四套件约 120 例 + 静态门 + 全量回归（基线 8532P 量级，campus 面零交叉回归预期） |
| 工时 | 单席单会话 1-2h 级（builder+handler 均有逐字段先例与逐断言规约，无设计自由度）；瓶颈在 root `__init__.py` 协调等窗，非编码 |
| 风险 | 高：与 S0-ROOT-c 同文件并发（缓解=主会话排程互斥 + diff 快照）；中：两裁定点未裁决先实施（缓解=本卡先行，裁决 A/A 后无开放设计点）；低：offload 池 busy 丢弃/暂停吞转/IMMEDIATE 语义差（均有推送先例背书，见 §1.4 行为差表）；低：坐标漂移打断坐标门（缓解=import 原地扩展零增行 + 失败即按 §2.5.3 处置） |

（U17-RUNBOOK 完）
