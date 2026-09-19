# B4-spec — 中央出站防风暴闸 + 送达核验（规格，不写码）
> **术语说明（2026-09-20）**：本文中的 **NapCat** 指 2026-09-18 之前的 QQ 协议端（当时实况记录，保留原文不改写）；现役协议端为 **SnowLuma**，见 [../snowluma-setup.md](../snowluma-setup.md)。
Status: DONE
> 席面：B4-spec。性质=只读代码+本规格。上游输入：`reports/E1-report.md` §1#8/§3 G2/§4 D3、`reports/E5-report.md` §1.5/§1.7/§1.9/§2-B2/B4/B6/§4.6、`reports/E6-report.md` §3、`findings.md` F-07。
> 行号以 2026-09-19/20 工作树实况为准（树脏多会话共享，函数名/锚点为稳定定位符）。所有路径为 `plugins/bot_unified_runtime/` 相对。
> 简报校正一处：任务书所称协议类 `OneBotAdapterProtocol(:53)` 树上真身名为 **`OneBotV11Bot`（domains/transport/sender/onebot.py:52-65）**，仅声明 `send_private_msg`/`send_group_msg` 两口，无读侧 API。

## §0 设计裁定速览（供评审席 30 秒核对）

| # | 裁定点 | 本规格结论 |
|---|---|---|
| 1 | 闸的唯一插入点 | 新中央件 `domains/transport/sender/outbound_gate.py::submit_active_push`，聚合域**只允许经它触达 `send_queue.submit`**；`queue.py:418` 本体不改（理由见 §1.2 三选否） |
| 2 | 存量 6 族 | 只登记不迁移（§1.5 登记表），结构性锁测试防实施席顺手迁移 |
| 3 | 限流真值口径 | 以代码坐标为准（§2 表），「3/分钟·20/小时」仅对未接线 schedule v2 引擎内部成立 |
| 4 | 送达核验分层 | 本地可判定（发前摘段可感知+回执指纹）归 B4 实施；需适配器确认（get_msg 系）协议扩展归 B4、语义启用等真机取证（§3.3 分界表） |
| 5 | 与日程 v2 关系 | 复用其**词汇与接口位**（枚举/quiet 设置对象/deliver_after 原语），不复用其**实例**（引擎未接线且 schema 深耦合日程语义）——不构成第三套（§5） |
| 6 | 缺省 | 全部新键缺省=关闭/现状字节级不动；`bot_outbound_gate_db_path` 进 path_fields 重映射 |

## §1 中央出站防风暴闸（Outbound Gate）

### 1.1 问题钉死（不重复盘点，仅锁证据）
- 现役主动投递全绕入站门禁：quiet/限流在 policy 入站侧，`grep -rn "quiet" domains/transport/` 零命中（E5 §5 复跑证据）；六族 submit 直连队列（`__init__.py:2941/3052/3210/3359/5031` + 订阅经 pipeline `domains/chat_reply/runtime/pipeline.py:835`），队列侧只有 dedupe/租约/退避三类约束（E5 §2-B6 表：对调度器推送「生效」的仅队列自身）。
- 唯一风暴门在未接线引擎：`domains/schedule/service/schedule_service.py:484-550`（`bot_schedule_delivery_enabled=False` 缺省，`config.py:405-406`，全仓零生产调用点，E1 §2#7）。

### 1.2 唯一插入点（含三选否）
**采纳**：新文件 `domains/transport/sender/outbound_gate.py`，公开唯一入口：

```python
def submit_active_push(
    send_queue: SendQueue,            # domains/transport/sender/queue.py:167 协议
    send_request: SendRequest,        # domains/core/contracts/runtime.py:294-330
    gate: OutboundGate,               # 装配期构建（注入 settings/clock/store）
    *,
    now: datetime | None = None,
) -> ActivePushOutcome: ...

class ActivePushOutcome(StrictBaseModel):
    verdict: OutboundGateVerdict
    receipt: DeliveryReceipt | None   # skip=未触队列时为 None；defer/allow 均为 submit 回执
class OutboundGateVerdict(StrictBaseModel):
    action: Literal["allow", "defer", "skip"]
    reason: str                        # 稳定机读短语（见 1.4 日志字段）
    deliver_after: datetime | None     # defer 时=闸给出的最早可投时刻
    audit_tags: list[str]
```

`submit_active_push` 内部按序过三道门（quiet → 每主体限流 → dedupe 键规范核验），allow/defer 才调 `send_queue.submit(request, deliver_after=verdict.deliver_after)`（defer 用队列原生 `deliver_after` 语义=worker 最早投递时刻且声明无内联首投，`queue.py:418-438`，E5 §2-B2 实证可复用）；skip 不调 submit、返回 `skipped_receipt` 同形态回执（`queue.py:475` 先例）。聚合域一切主动投递（含未来 fan-out，E5 §4.4 `fanout_emergency_push` 抄 `__init__.py:3333-3358` 骨架）以本函数为**唯一** submit 触点。

**三选否（为什么不是别处）**：
- (a) `SQLiteSendRequestQueue.submit` 体内（`queue.py:418`）：①非单点——`SendQueue` 是协议（`queue.py:167-176`），`InMemorySendQueue.submit`（`:191`）是第二实现，闸要么双插（漂移风险）要么破坏协议等价；②会误伤消息流回复（pipeline `:807-835` 同走此口，用户问答回复不该被 quiet/日 dedupe 拦截或顺延）；③捕获存量 6 族同口 submit——功能一旦开启即改其行为，直接违反「缺省=现状字节级不动 + 存量只登记不迁移」裁定；④队列是传输基础设施，不应持有内容策略知识（架构分层与 `docs/design/backend-v2-implementation-guide.md` 精神一致）。
- (b) worker 认领/投递循环（`worker.py:737+`）：入队已发生，拦不住队列膨胀与 dedupe 键占用；且会连坐正常重试流。
- (c) 根 `__init__.py` 各推送点逐个插：6+ 处分散，未来新域每处都要记得插=必然漏，非中央。

### 1.3 三道门语义
1. **Quiet hours**（缺省行为=顺延）：判定复用既有设置对象 `QuietHoursSettings` 与窗判定逻辑（`domains/chat_reply/policy/quiet_hours.py:23/:66`，配置族 `bot_quiet_hours_*`，`config.py:949-954`，缺省 00:00-06:00/Asia_Hong_Kong/仅 group）。注意 `QuietHoursChecker.check()` 入参是 `IncomingMessage`（`:93`），出站闸不能直接调——**提取/导入其 `_is_in_quiet_hours` 同级纯函数**（`next_quiet_end` 语义已有先例 `schedule_service.py:509-511`），闸侧以 `SendRequest.target_scope/privacy_level` 判会话维度。产品裁定 D-2：**仅 severity∈{P0,P1} 穿静默**（映射键 `bot_outbound_gate_urgent_severities=["P0","P1"]`），其余 `defer` 至安静结束；显式批准例外口本波不做（日程 v2 的 `approve_quiet_exception`，`schedule_service.py:519-524`，留给引擎接线波，不造第二套审批）。
2. **每主体限流**：主体键 = `f"{target_scope}:{target_id}"`；60s/3600s 双滑窗计数，落新 store（`outbound_gate_sends(subject_key, sent_at_utc)` 单表，确定性计数样板抄 `schedule_send_log`，`schedule_service.py:526-550`）。超限 → `defer(deliver_after=now+60s)`（不做 digest 合并——合并摘要依赖 `build_digest` 留接口未实现，`schedule_service.py:551-560`，本波诚实不装）。
3. **按日 dedupe**：**不新建第二去重账**——队列 `INSERT ... ON CONFLICT(dedupe_key) DO NOTHING → skipped` 已是中央幂等（`queue.py:444-476`）。闸的职责=**键规范强制**：`SendRequest.dedupe_key` 必须匹配 E5 §4.3 约定 `emg:{channel}:{item_id}:{target_id}[:{date_key}]`（按日重投族必须带 date_key 段），不合规范 → `action=skip, reason="dedupe_key_shape"` 并入告警（编程错误，不是运行态）。

### 1.4 失败/降级语义、日志与告警
- **fail-open**：store 异常/设置读取异常 → `allow` + `logger.error("outbound_gate_store_failure ...")` + OperationalIssue(kind=`outbound_gate_degraded`)。依据：闸是「更好」而现役 6 族本无闸，闸自身故障不得变成丢消息（同族先例：quiet 设置求值失败回退默认不误拦，`quiet_hours.py:88-92`；错误卡冷却降级不吞回执，台账#29 惯例）。
- 时钟注入：`OutboundGate(clock=...)` 可注入（`QuietHoursChecker` 同款纪律，`:70-75`），离线测试确定性。
- settings 支持 callable 热改（quiet 面先例 `quiet_hours.py:72-76`；限流阈值两键支持热改，明确**不做**「SQLite 限流不支持热改」旧坑复刻，台账#3）。
- 日志字段（全 determinstic、无正文、经 `output/plain_text.py` 打码口径不打日志但禁含 content）：`request_id / verdict.action / reason / subject_key_hash(sha256[:12]) / window_count / deliver_after / capability_id`。
- 审计：每次放行/顺延/拒绝经 `AuditRepository` 记一条（`queue.py:487 _append_sender_audit` 同族口），event ∈ `outbound_gate_allow/defer/skip`。
- 告警 kind 新增两枚（进 `domains/ops/monitor/alerts.py` 折叠族，复用 300s 抑制 `:155-171`）：`outbound_gate_degraded`（store 病）、`outbound_gate_storm`（同一主体连续 3 次 defer，说明上游在轰闸）。

### 1.5 配置键（落地请求原文——本席不改 config.py，交 B8/B9 合流席）
| 键 | 类型/缺省 | 语义 |
|---|---|---|
| `bot_outbound_gate_enabled` | bool = **False** | 总闸；False=`submit_active_push` 直通 submit 零判定点（字节级现状） |
| `bot_outbound_gate_quiet_defer_enabled` | bool = True | 仅 enabled=True 时生效：非 P0/P1 静默顺延 |
| `bot_outbound_gate_urgent_severities` | list[str] = ["P0","P1"] | 穿静默白名单等级（D-2 裁定映射） |
| `bot_outbound_gate_max_per_target_per_minute` | int = 2 | 60s 窗内每主体上限 |
| `bot_outbound_gate_max_per_target_per_hour` | int = 6 | 3600s 窗内每主体上限 |
| `bot_outbound_gate_db_path` | str = "data/outbound_gate.sqlite3" | **必须进 path_fields 重映射**（runtime_paths 铁律，先例 `bot_campus_db_path`，config.py:395 注释族） |
数值缺省为保守建议值，非实测推导，评审可改；唯一硬约束=enabled 缺省 False。

**存量 6 族登记表（只登记不迁移；结构性锁见 §4 T6）**：
| 族 | submit 现坐标 | 未来迁移时补什么 |
|---|---|---|
| 提醒 | `__init__.py:2941`（+内联补投/送达才销账 `:2903-2915`） | 迁移时保留其对账闭环，仅包闸 |
| cookie 到期 | `:3052`（当日 SENT 回执对账 `:3014-3023`） | 同上 |
| 群摘要 21:30 | `:3210`，dedupe `digest_push:{group}:{today}`（`:3204`） | 键并入 emg 规范或豁免登记 |
| 日常助理 | `:3359`，dedupe `daily_assist:{tag}:{user}:{today}`（`:3351`） | 同上 |
| 校园转发 | `:5031`，dedupe `campus_fwd:{message_id}`（campus.py:166） | 同上 |
| 错误卡补发 | `domains/ops/monitor/error_report.py:1029-1033`（deliver_after 形态） | 诊断面**永久豁免限流**候选（防「闸把故障上报拦掉」），迁移波裁决 |
| （旁路）运维告警 | `__init__.py:3895-3904` 直调 transport 不过队列（E1 §3 G1） | 属 D5 收编议题，非本闸范围，登记 |

## §2 限流真值口径（冲突裁决）

**裁决：以代码坐标为唯一真相源**（工作区铁律：文档手写数字一律视为待核）。三套数字其实描述三个不同对象，冲突根因是把它们混为一张口径表：

| 口径 | 真值 | 适用对象 | 代码真身坐标 |
|---|---|---|---|
| A. 入站 chat 限流（现役生产门） | 60s 窗：全局 60 / session 6 / sender 4（代码缺省）；**生产实值 60/12/8**（`.env:62-64` 实测，仅引键名阈值无密钥）+ R3 同人 45s | 用户消息触发的 bot 回复 | `domains/chat_reply/policy/rate_limit.py:30-49`；`config.py:938-944`（`bot_rate_limit_chat_global/session/sender_max_requests`、`bot_rate_limit_chat_sender_min_interval_seconds=45`） |
| B. 群句数帽 | 缺省 **0=关闭**（hour/minute 两键） | 群聊被动回复脉冲防护 | `config.py:943-944`；E5 §2-B6 |
| C. 日程 v2 引擎每主体风暴门 | 3/分钟·20/小时 | **未接线引擎内部**（`bot_schedule_delivery_enabled=False`，`config.py:405-406`，全仓零生产调用点） | `schedule_service.py:152-153/:526-550` |
| D. 新中央出站闸（本规格） | 2/分钟·6/小时（建议值，缺省整体关闭） | 聚合域主动推送 | 本规格 §1.5 |

**简报旧口径「每主体 3/分钟·20/小时」不成立于现役生产**（E5 §1.9 实证）——它是 C 行引擎缺省值。凡引用它描述现状的文档行必须更正或加限定语：

需要更正/加限定的文档行清单：
1. `docs/design/backend-v2-product-extensions.md:170`——「每主体 3/分钟、20/小时，超限合并摘要」须加注「=日程 v2 引擎内部缺省（未接生产）；现役入站真值见 config.py:938-944，出站中央闸另立口径 bot_outbound_gate_*」。
2. `AGENTS.md` / `docs/HANDBOOK.md` 总账中同口径句子（E5 §3.4 已点名的「AGENTS.md 同口径需一并更正」；本规格 grep 未命中 AGENTS.md 现行文本含 3/分钟，故以 E5 报告为准由合流席复核 HANDBOOK）。
3. `docs/design/emergency-info-unify-summary-20260919.md:47` 已载更正，无需动。
4. 不动项：`docs/command-catalog.md:1060`、`echo.py:1266`、`docs/design/v21r2-command-spec-entries-3.md:241` 中「用户口径建议 60/小时、3/分钟」是**群句数帽的人工建议值**（对象=B），与 C 无关，保持原文。

## §3 送达核验（「谎报送达」最小可实现方案）

### 3.1 现状钉死（A 波已证，仅列规格依赖的事实）
- SENT 唯一依据=`status∉{failed,fail,error} ∧ retcode∈{None,0}`（`onebot.py:111-116`），message_id 取不到仍记 SENT（`:975-981`）。
- **本地静默降级第一层（bot 自己丢段）**：`_mixed_segments`（`onebot.py:244-259`）逐 part 构造，失败返回 None 即无声丢弃（record 缺 file/url `:281-282`、未知类型 `:308`）；全丢才兜底 text_fallback（`:259`）；`build_onebot_message_segments:208` 的 `segments or [_text_segment(...)]` 是回落终点。零日志零 OperationalIssue（E6 §3.2 表首行）。
- **协议端摘段第二层（上游）**：SnowLuma/NapCat 对每段 `?.catch(void 0)`+`filter(!!u)`，语音段失败被摘、文字照发、API 回 ok ⇒ SENT=谎报（F-07；NapCat 侧实证 `HANDOFF-SESSIONS-unify-audit-20260919.md:138`，**SnowLuma 侧同构性未证**，禁读外部目录，E6 §3.1/§6）。
- UNKNOWN 分片生产无确认器：`UnknownPartConfirmer = Callable[[SendRequest,int],Awaitable[bool|None]]`（`worker.py:50`），形参在 `worker.py:217/:737`，判定协议 `:776-795`（先查 part.provider_message_id→再问确认器→None 保持 UNKNOWN），生产调用点 `__init__.py:1649` `drain_send_queue_once(...)` **未传**（E5 §1.5）。

### 3.2 分层方案
**Tier 1 —— 本地可判定（零外呼，B4 全量实施）**
- T1-a 发前摘段可感知：`_mixed_segments` 循环尾（`onebot.py:252-259`，E6 §3.3 坐标 1）比对 `len(segments)` vs 输入 `parts` 中 dict 项数，丢段即 `logger.warning("onebot mixed segment dropped request_id=%s debug_id=%s dropped_types=%s planned=%d sent=%d", ...)`（只记**类型名**列表，正文不入日志）；开关 `bot_outbound_verify_enabled`（bool=False）开启时**同时**给返回的 DeliveryReceipt 路径挂 OperationalIssue(kind=`segment_dropped_local`, stage="onebot", retryable=False)。日志本体**无条件常开**（纯观测零行为变更，E6 判「改动零风险」；若评审坚持字节级缺省，则日志也收进开关，二选一由合流席裁）。
- T1-b 计划/实发指纹常存：submit 侧 audit detail（`queue.py:487 _append_sender_audit` 扩展点）追加 `planned_parts`（content_ref.parts 计数）与 `sent_segment_types`（发送前构建结果类型序列）——**不动 `DeliveryReceipt`/`SendRequest` 契约**（contracts 本轮禁改纪律，E5 §2-B2 注），落审计面即可供事后取证与 Tier 2 比对锚（E6 §3.3 坐标 4）。
- T1-c 回落语义显式化：`:208` 空段回落后纯文本路径返回值不变，但审计多记一行 `reason="segment_build_fallback_text"`（与 `text_fallback` 语义对齐，renderer 侧 `text_fallback` 契约零破坏，docs/rendering-contract.md 口径）。
- **失败语义**：Tier 1 一律**不改 ReceiptState**（本地丢段是既成事实，段没了就是没了，重试也不会更多——除非上游内容重出），只产生「SENT+观测注记」；聚合域上层文案据 `receipt.operational_issue` 决定「语音可能未包含」类诚实措辞（D-7「先修谎报再接播报」的最低满足面）。

**Tier 2 —— 需适配器确认（要扩 protocol 一个回执查询口）**
- T2-a protocol 扩展：`OneBotV11Bot`（`onebot.py:52-65`）追加**可选**只读方法声明 `async def get_msg(self, *, message_id: int | str) -> Any: ...`；消费侧一律鸭子探测 `getattr(bot, "get_msg", None)`，缺失=静默不核验（与确认器缺省 None 同语义），sender 层零新依赖（同 `_exception_platform_rejection` 鸭子风格 `:125-146`）。
- T2-b 生产注入 `unknown_part_confirmer`（治 E5 §1.5 祖传缺口，同时服务核验）：在 `__init__.py:1649` 调用点传入实现——按 part 的 `provider_message_id` 反查 `get_msg`：查到→True（SENT）；明确「消息不存在」→False（回 PENDING 重发安全）；异常/不支持→None（保持 UNKNOWN）。状态影响：走 worker 既有合法转换（`:786-795`），**无新枚举**。前置条件=真机取证（见 3.3）。
- T2-c SENT 后异步抽验（E6 §3.3 坐标 2）：`onebot.py:975-981` 成功路径上，当发送段含富媒体且拿到 provider_message_id 且开关开启时，投递旁路任务经队列（或 `asyncio.to_thread`+强引用台账样板 `__init__.py:4020-4035` 反例教训——**必须走队列/受管任务**，禁裸 create_task）执行 `get_msg` 反查落地段类型集合 vs T1-b 指纹；不符→ alerts 族告警 kind=`delivery_segment_mismatch`（300s 抑制自带）+ receipt 审计注记；**不改已记的 SENT 状态**（OneBot v11 无撤回/改判语义，改判会造成重投风暴反例=9-15 事故族）。
- 日志/告警字段汇总：kind ∈ {`segment_dropped_local`, `delivery_segment_mismatch`, `unknown_part_confirmed`, `outbound_gate_degraded`, `outbound_gate_storm`}；必带 `request_id/debug_id/transport`，禁止正文。

### 3.3 B4 实施 vs 真机取证分界
| 项 | 归属 | 依据 |
|---|---|---|
| T1-a/b/c 全部 | **B4 实施**（纯本地，离线可测） | 零外呼零新协议依赖 |
| T2-a protocol 声明+鸭子探测 | **B4 实施**（缺能力=不核验，安全缺省） | 声明本身零行为变更 |
| T2-b confirmer 生产接线 | **B4 实施代码 + 真机启用验收**：实现与注入写好，但「明确不存在→False」判定必须等 SnowLuma get_msg 返回 schema 证实后才可开（防把「查询失败」误判成「未送达」→重投双发，违背「防重复投递优先于防漏发」worker.py:45-50/543 裁定） | E6 §2.2：message_id 非纯数字串时 int 强转静默 ValueError 先例（`__init__.py:8096-8104`） |
| T2-c 抽验开关 | **等真机取证**（`bot_outbound_verify_enabled` 缺省 False，真机验收通过前生产不开） | SnowLuma 侧摘段/`get_msg` 可用性/message_id 恒带与否全未证（F-07、E5 §6.5、E6 §6.1） |
| 真机探针 | 验收清单：E6 §5-⑫「mixed record+text 谎报探针」+ 发一条含图+语音私聊后 get_msg 回读比对 | 属重启后动作，非本席 |

## §4 反证测试清单（每条必须「能失败」；实现席据此先写 RED）
新测试文件两件：`tests/test_outbound_gate.py`、`tests/test_outbound_delivery_verification.py`。

| # | 用例 | 断言要点 | 为什么会失败（反证性） |
|---|---|---|---|
| T1 | `test_gate_disabled_is_passthrough` | `enabled=False` 时 submit 恰被调 1 次、`deliver_after` 传参与裸调用等价、零审计门事件 | 若实现「关而不止」（闸关了仍记 store）即红 |
| T2 | `test_quiet_hours_defers_non_urgent_p0_p1_pass` | 注入静默窗时钟+假 store：severity=P2 → verdict=defer 且 `deliver_after==quiet_end`；P0 → allow 立即 | urgent 穿闸未实现则 P0 被顺延即红；顺延时刻算错（跨零点窗）亦红 |
| T3 | `test_per_target_minute_cap_defers` | 同主体连发 cap+1 条，第 cap+1 条 defer 且 `deliver_after<=now+60s`；换主体不受累 | 计数窗写死/主体键错并则红 |
| T4 | `test_gate_store_failure_fails_open` | store 抛 RuntimeError → verdict=allow + OperationalIssue(`outbound_gate_degraded`) 挂出 | 实现若 fail-closed（丢消息）即红——方向性锁 |
| T5 | `test_dedupe_key_shape_enforced` | `dedupe_key="emg:qq:abc:target"`（按日族缺 date_key）→ skip+告警事件；合规键 → 透传队列由 ON CONFLICT 出 skipped | 键规范不检则红；同时在真队列集成用例锁「闸不重复建去重账」 |
| T6 | `test_existing_families_not_routed_through_gate`（结构锁） | AST/grep 断言：`__init__.py:2941/3052/3210/3359/5031` 五处仍直调 `send_queue.submit`，`submit_active_push` 生产 import 仅出现在 emergency 域文件 | 实施席顺手迁移存量即红（同族先例 `tests/test_v21_wiredirect_unified_path.py:103`） |
| T7 | `test_mixed_segment_drop_logged` | `content_ref.parts=[{"type":"record"},{"type":"text","text":"x"}]`（record 无 file/url）→ 返回 1 text 段 且 caplog 命中 `dropped_types=['record']`+request_id | 现状零日志，必 RED；回归时删观测行即回红 |
| T8 | `test_all_parts_dropped_text_fallback_unchanged` | 全 part 无效 → `segments==[_text_segment(text_fallback)]` 逐字节现状 | 行为变更锁（防「顺手改成 FAILED」破坏渲染契约零破坏铁律） |
| T9 | `test_verify_switch_adds_operational_issue` | `bot_outbound_verify_enabled=True`+丢段 → SENT 回执携 kind=`segment_dropped_local`；False → 无 issue | 开关两侧都可失败=非恒真 |
| T10 | `test_production_drain_wires_confirmer` | 装配期断言 `drain_send_queue_once` 收到的 `unknown_part_confirmer is not None`（monkeypatch 捕获实参） | 现状 `__init__.py:1649` 未传，真 RED（E5 §1.5） |
| T11 | `test_confirmer_semantics_matrix` | 假 bot：get_msg 命中→True；结构化「不存在」回执→False；任意异常/无 get_msg 属性→None（三分支直达 worker `:786-795` 既有协议，不重新发明） | 若把「查询异常」错归 False（→重发双发）即红，此条是安全方向锁 |
| T12 | `test_no_new_receipt_state` | 断言 `ReceiptState` 枚举成员集合不变 + `partial/processing` 裸串仍不入 contracts（E5 §2-B2 禁改纪律） | 任何「新增 PARTIAL_SENT 之类状态」的野路子实现即红 |
| T13 | `test_gate_reuses_quiet_settings_type`（G5 锁） | AST 断言 outbound_gate.py import 的是 `policy.quiet_hours.QuietHoursSettings`，且本文件不定义任何 `HH:MM` 解析函数 | 自造第二套时间窗解析即红 |

复跑口径（实装波）：`PYTHONDONTWRITEBYTECODE=1 <venv>/Scripts/python.exe -m pytest tests/test_outbound_gate.py tests/test_outbound_delivery_verification.py -p no:cacheprovider --basetemp=$TEMP/e-wave-B4`。

## §5 与日程 v2 引擎的关系（G5 裁决：复用 / 另建）

**裁定：复用其「词汇、设置对象与队列原语」，不复用其「引擎实例」；闸本体新建于 transport 层。不构成第三套。**

依据：
1. **不能直接复用实例**：引擎整体未接生产（`config.py:405-406` 缺省关 + 全仓零生产调用点，E1 §2#7/§3 G6），且 `split_quiet_hours`/`acquire_send_slot` 的输入是日程 schema（claimed rows/`plan_id`/`owner`/`SchedulePlan.quiet_hours`，`schedule_service.py:484-550`），泛化成通用闸=把日程域拖进 transport 依赖，违背域隔离；其 digest 合并出口 `build_digest` 自述留接口未实现（`:551-560`），「超限合并摘要」承诺本波兑现不了，规格里诚实降级为 defer。
2. **也不是造第三套**，因为：quiet 窗判定唯一事实源仍是 `policy/quiet_hours.py` 设置族（T13 锁死不得自造解析）；穿静默/顺延/审批语义词汇直接收编引擎既有枚举（`ReminderPolicy.urgent`、`quiet_hours_behavior∈{defer,send}`、`SendDecision.decision∈{allow,digest}`——E1 §4「定级/紧急语义词汇直接收编、勿另造第二套」原文执行）；顺延执行原语用队列原生 `deliver_after`（`queue.py:418-438`），不造 delay 表。本仓现存的「主动侧 quiet/风暴」实现集 = {未接线引擎实例} + {本规格闸}，闸是引擎 send 层「留接口」（`delivery.py:51-54` 已按同协议写）未来可直接改调的**那个中央件**——终态合流：日程 v2 接线授权后，其发送层接本闸，两套判定并成一套。
3. 若评审倾向更彻底复用，备选 B 案=「先接线日程引擎再扩通用」——被否：L41 等行仍 blocked 等用户裁决（`docs/design/v21r4-b-wave-snapshot.md`），紧急域不应被无关域的授权卡死。

## §6 复跑证据（本席只读取证命令 + 输出摘要）
- `sed -n '418,488p' domains/transport/sender/queue.py` → SQLite submit 全文（ON CONFLICT dedupe `:459`；deliver_after 文档串 `:425-432`；A-22 内联认领 `:484-485`）。
- `grep -n "def submit" queue.py` → `:168`（协议）/`:191`（InMemory）/`:418`（SQLite）三点位，支撑 §1.2(a)「双实现」论点。
- `sed -n '52,65p;201,259p;920,981p' onebot.py` → protocol 仅两 send 口、`_mixed_segments` 静默丢段、SENT 终点携 `provider_message_id=_extract_message_id(result)`。
- `grep -n "send_queue.submit" __init__.py` → `:2941/:3052/:3210/:3359/:5031` 五处现役直调。
- `sed -n '395,410p;930,960p' config.py` → `bot_schedule_delivery_enabled=False`、rate_limit 族（60/6/4、45s、群帽 0）、quiet_hours 族实测在位。
- `sed -n '484,560p' domains/schedule/service/schedule_service.py` → split_quiet_hours/acquire_send_slot/build_digest「留接口」原文。
- `sed -n '60,140p' domains/chat_reply/policy/quiet_hours.py` → `check()` 入参 `IncomingMessage` 实证（闸不可直调，取 settings 复用）。
- `grep -n "unknown_part_confirmer" worker.py __init__.py` → 形参 `:217/:737`、协议 `:50`、生产 `__init__.py:1649` 调用未传（与 E5 §1.5 一致）。
- `grep -rn "3/分钟|20/小时|max_sends_per_minute"` 全仓 → 命中清单即 §2 「需更正文档行」表（backend-v2-product-extensions.md:170 / schedule_service.py:152-153 / summary §8 / command-catalog+echo 属 B 对象）。
- 纪律自证：本席零改码、零 pytest 实跑（故无 passed 数可报，规格件性质）、仅写本规格文件一件、无 git 写、无子代理。

## §7 我没查到的（诚实缺口）
1. SnowLuma `get_msg` 是否存在、返回 schema、message_id 数字形态——禁读外部目录，全部 Tier 2 语义启用等真机（§3.3）。
2. `.env` 生产实值仅转述 E5 实测行号（`.env:62-64`），本席未复读 `.env`（避免密钥入面）。
3. `backend-v2-implementation-guide.md` 对 transport 层「不得持有内容策略」是否有明文分层条款——只引了精神，未逐句核。
4. 告警 kind 折叠注册表（`alerts.py:247-267` v21r2 R1）新增两枚 kind 是否需同步 control_plane OpenAPI 登记——属 E9/控制面席领地，未核。

---

## §8 Amendment（2026-09-20 02:05，据 B4b 实施结果更正本规格两处**错**）

本规格 §3.2 的两条断言被实施席以代码/mypy 实证推翻，现就地作废并给出正确形态。**凡本 §8 与上文冲突处，以本 §8 为准。**

| # | 原文（错） | 更正后 | 证据 |
|---|---|---|---|
| A-1 | T2-b「确认器按 part 的 `provider_message_id` 反查」 | **规格自相矛盾**：worker 只在 part **没有** `provider_message_id` 时才调用确认器（`worker.py:780` 一带），故确认器按原文永远拿不到要查的 id。正确设计=先定「id 供给链」（谁在何时把 part→message_id 写进 `content_ref["part_message_ids"]`），供给链未落地前确认器只能**安全空转**（现实现即取此路径，生产无人写⇒恒 None） | B4b-report §concern；实现在 `onebot.py::build_unknown_part_confirmer` |
| A-2 | T2-a「给 `OneBotV11Bot` 增 `get_msg` 声明属零行为变更」 | **不成立**：声明直进原协议会打断 5 个 smoke 替身（mypy 实锤）。正确形态=分层出独立消费面（实现取 `OneBotV11SendBot`），原协议只被发送路径消费 | B4b-report Concerns#2 |
| A-3 | T1-b「审计指纹字段挂 `queue.py::_append_sender_audit`」 | 该面不属任何在飞席位 ⇒ 拆为**独立合流请求**（Tier1 先落「日志 + SENT 注记」两半，队列审计字段第二批） | B4b-report §落地请求#3 |
| A-4 | §3.2「不符则可能改判」的含糊表述 | 统一钉死：**Tier1/Tier2 一律不改 `ReceiptState`**（本规格 T12 冻结锁），不符只出告警 + 审计注记。E7 席旧提法「改判 FAILED_RETRYABLE/UNKNOWN」同步作废（改判=重投风暴） | `reports/E7-report.md` 顶部 Amendment；`tests/test_delivery_verification_tier1.py` 枚举冻结锁用例 |

**生产可达性缺口（实施完成但仍不可用，须由合流席或用户裁决闭合）**：
`grep -c "bot_outbound" plugins/bot_unified_runtime/config.py` = **0** ⇒ Tier1/Tier2 代码在树、
`getattr(config, "bot_outbound_verify_enabled", False)` 恒取缺省 False ⇒ **没有旋钮可开**。
最小闭合=补 1 枚 `bot_outbound_verify_enabled: bool = False`；完整闭合=§1.5 六键 + 该核验键，
且 `bot_outbound_gate_db_path` 必须进 `path_fields` 重映射（铁律 6）。
