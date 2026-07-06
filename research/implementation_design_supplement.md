# 实现设计补充

## 目的

本文补齐实现前的关键细节：fetch/crawl 策略、用户可见投递反馈、GsCore/GScore 来源选择、第一批运行时契约和实现门禁。它扩展 `architecture_report.md` 和分析矩阵，不替代 `docs/specs/`。

相关核心规格：

- `docs/specs/runtime-parameter-flow.md`
- `docs/specs/input-output-contracts.md`
- `docs/specs/auto-send-capability.md`
- `docs/specs/character-intelligence-and-knowledge.md`
- `docs/specs/media-source-pipeline.md`

统一规则：adapter 可以抓取、解析、检索、渲染，但最终投递只能由统一运行时创建 `SendRequest`。

## 证据基线

- 第一批 NoneBot：53 个 wheel 和 53 个源码目录。
- 第二批官方商店候选：17 个 wheel 和 17 个源码目录。
- GsCore/GScore 本地仓库：12 个浅克隆。
- 本地 AstrBot 插件目录：24 个。
- 官方 NoneBot registry 快照：2026-07-06，共 903 条。
- GsCore/GScore GitHub 状态快照：`research/gscore_sources/github_repo_status_2026-07-06.json`。

## Fetch / Crawl 契约

所有 parser、searcher、crawler、subscription source、外部游戏 bridge 都视为 source adapter。

```text
SourceAdapter
- source_id
- supported_inputs
- auth_modes
- risk_level
- resolve(input, context) -> FetchRequest | RejectReason
- fetch(request) -> FetchResult
- parse(fetch_result) -> ParsedItem[]
- normalize(parsed_items) -> CapabilityResult
```

### FetchRequest

```text
FetchRequest
- source_id
- url_or_endpoint
- method
- params
- body
- headers_ref, never raw secret headers
- auth_mode: none, api_key, cookie, oauth, qr, bridge
- cache_key
- ttl_seconds
- timeout_seconds
- retry_policy
- min_interval_key
- priority: immediate, normal, background
- privacy: public, personal, credentialed
- allowed_content_types
- robots_policy: respect, api_only, manual_review_required
```

### FetchResult

```text
FetchResult
- ok
- status_code
- final_url
- content_type
- body_ref or parsed_json
- fetched_at
- source_etag
- source_last_modified
- rate_limit_remaining
- error_kind
- debug_id
```

## Crawl 模式

| 模式 | 触发 | 首批是否允许 | 规则 |
| --- | --- | --- | --- |
| 直接链接解析 | 用户发送支持链接或显式命令 | 是，P1 | URL/content id 缓存，同群去重，一张简洁卡。 |
| 订阅轮询 | 用户/管理员订阅目标 | 是，P1/P2 | 加权调度、目标去重、群里默认摘要，紧急告警例外。 |
| 搜索/摘取 | 显式命令 | 是，P1/P2 | 优先 API/搜索服务，带引用，结果不当指令。 |
| 同人发现 | 私聊命令或 opt-in 摘要 | 后续 | metadata 优先，默认私密，过滤 NSFW/版权/来源条款。 |
| 表情/媒体学习 | 显式保存或群 opt-in | 后续 | 同意、容量限制、审核、删除/列表/导出。 |
| 账号抓取 | 绑定私有账号 | 后续 | 密钥库、私聊输出、撤销、审计，不发群凭据。 |

## 必需控制

- 每来源 rate limit。
- 每目标最小轮询间隔。
- 429、403、验证码、登录要求、超时、解析器变化退避。
- item identity 来自平台 id、canonical URL 或内容 hash。
- 渲染前和发送前都去重。
- 用户等待的即时回复和后台抓取任务分开。
- 公共解析可以短缓存；凭据/私密结果只有策略允许才缓存。
- 订阅 cursor 和 last successful item 持久化。
- 抓取内容进入 LLM 前标记为不可信事实。
- 默认不重托管同人，只发来源链接/卡片。

## 投递与反馈模型

内部投递状态和用户反馈必须分开。用户要短而有用的状态，运营者要完整审计。

### SendRequest

```text
SendRequest
- request_id
- session_id
- target_scope: private, group, channel
- target_id
- origin_message_id
- capability_id
- content: text, card, image, forward, mixed
- send_policy: immediate, queued, digest, private_fallback, admin_confirm, silent_audit
- priority: user_waiting, normal, background, urgent_alert
- max_messages
- dedupe_key
- cooldown_key
- expires_at
- privacy_level
- allow_split
- allow_forward
- persona_profile_id
- audit_tags
```

### DeliveryReceipt

```text
DeliveryReceipt
- accepted: policy 和队列接受
- rendered: 渲染成功或选择文本 fallback
- sent: transport 发送成功
- queued: 等待后台队列或摘要窗口
- skipped: 去重、冷却或过期
- redirected: 从群转私聊
- blocked: 策略、安全、隐私、OOC 或内容过滤拦截
- failed_retryable: 上游/transport 临时失败
- failed_final: 不可重试失败
```

### 用户反馈规则

- 两秒内完成：只回结果。
- 超过两秒：最多一条等待提示。
- 后台订阅：不公告每次轮询，只发新内容、摘要或管理员失败汇总。
- 群自动解析：重复和冷却命中静默。
- 私聊回退：只告知一次。
- 管理员确认：展示来源、风险、目标、过期、确认/取消命令。
- 失败：用户看到可行动原因；审计记录原始异常、来源、request id、重试历史。

## 错误分类

| 错误类型 | 用户文本策略 | 审计细节 |
| --- | --- | --- |
| `user_input_invalid` | 说明格式。 | 原始输入、parser、校验错误。 |
| `auth_required` | 要求私聊绑定/登录。 | 缺失凭据类型、source id。 |
| `permission_denied` | 说明该 chat/user 未启用。 | ACL 规则、主体、能力。 |
| `rate_limited` | 说明来源冷却中。 | source、target、retry_after。 |
| `upstream_changed` | 说明来源格式变了。 | parser 异常和样本 id。 |
| `content_blocked` | 说明内容不能发。 | 安全类别和 reviewer 阶段。 |
| `privacy_blocked` | 转私聊或要求同意。 | privacy level、target scope。 |
| `timeout` | 说明来源超时。 | 耗时、超时配置、重试次数。 |
| `internal_error` | 给 debug id。 | 堆栈和运行时状态。 |

## 防刷屏不变量

- 一次用户动作通常最多一条群消息。
- 长结果转卡片、图片、合并转发或私聊继续。
- 后台事件默认摘要，紧急例外。
- 每次发送有 dedupe key 和 cooldown key。
- 群 LLM 回复采用 latest-only，旧请求可取消。
- 最终出站钩子必须能拦截非 LLM 插件输出。

## GsCore / GScore 来源选择

| 领域 | 主来源 | 原因 | 备注 |
| --- | --- | --- | --- |
| Core runtime | `Genshin-bots/gsuid_core` | 活跃、非归档，主 `SV`/权限/调度/runtime 来源。 | 当相邻服务桥接，不合并。 |
| NoneBot bridge | `Genshin-bots/nonebot-plugin-genshinuid` | 已有 NoneBot 到 gsuid-core 桥接模式。 | 用作桥接参考。 |
| AstrBot bridge | `astrbot_plugin_gscore_adapter` | 本地队列、重连、下游分发模式强。 | 可靠性参考。 |
| Genshin | `KimigaiiWuyi/GenshinUID` | 活跃、高星、功能完整。 | 公共功能先做。 |
| Star Rail | `baiqwerdvd/StarRailUID` | 快照中更活跃。 | CM-Edelweiss 镜像作比较。 |
| ZZZ | `ZZZure/ZZZeroUID` | 已验证并克隆，作为主参考。 | `CM-Edelweiss/ZZZeroUID` 次要。 |
| Wuthering Waves | `Loping151/XutheringWavesUID` | 活跃、非归档、星数强。 | `WutheringWavesUID` 归档，CM-Edelweiss 次要。 |
| WuWa scoring | `Loping151/ScoreEcho` | 鸣潮评分/卡片专用。 | 需确认许可和数据正确性。 |
| Endfield | `Loping151/EndUID` | 活跃 Endfield 来源。 | token/账号能力后置。 |
| Governance ops | `Loping151/BotShepherd` | 全局开关、黑名单、统计、代理治理。 | 运营参考，不作依赖。 |

## 首个 GsCore bridge allowlist

允许：

- 公共帮助/list。
- 公共 wiki 查询。
- 公共兑换码、日历、活动。
- 不需要 cookie 的材料/日程查询。
- 标明模拟的抽卡模拟。
- 鸣潮公共评分/卡片在许可确认后开放。

阻断：

- QR 登录、cookie 绑定、token 绑定、authkey 导入。
- 个人面板、抽卡历史、账号资源、owner cookies。
- 绕过统一发送策略的 DM 或群发送。
- 未显式批准的管理动作。

GsCore 输出也是 `CapabilityResult`，必须经过 permission、privacy、persona/OOC、renderer、send queue、audit。

## 第一批运行时模型

实现广泛功能前先写这些模型：

```text
IncomingMessage
- platform
- adapter
- bot_id
- session_id
- session_type
- sender_id
- sender_display_name
- group_id
- raw_segments
- plain_text
- mentions_bot
- reply_to_message_id
- timestamp
- message_id
```

```text
PolicyEvaluation
- allowed
- reason
- risk_level
- required_scope
- cooldown_key
- quota_key
- privacy_level
- audit_tags
```

```text
BotDecision
- should_respond
- mode
- trigger
- capability_id
- target_scope
- max_messages
- send_policy
- persona_profile_id
- context_budget
- decision_reason
```

```text
CapabilityResult
- kind
- title
- summary
- body
- url
- source
- source_timestamp
- images
- actions
- confidence
- risk_level
- privacy_level
- private_recommended
- send_policy
- debug_id
```

```text
PersonaProfile
- profile_id
- identity
- worldview
- tone_rules
- forbidden_phrases
- forbidden_behaviors
- world_mapping
- examples
- refusal_templates
- ooc_thresholds
```

```text
AuditRecord
- audit_id
- request_id
- session_id
- capability_id
- stage
- event
- severity
- public_message
- private_debug
- created_at
```

## 实现门禁

广泛功能前必须证明：

1. capability adapter 不能直接发送，只能返回 `CapabilityResult`。
2. 每个外部 fetch 有 timeout、retry、rate-limit key、audit id。
3. 每个发送都通过 `SendRequest` 并返回 `DeliveryReceipt`。
4. 每个群回复有 `max_messages`、dedupe、cooldown。
5. 私密/账号能力有同意、撤销、删除、导出、密钥脱敏。
6. 每个 LLM 调用都把上下文标为不可信事实。
7. 每条最终消息都过人格/OOC/安全/防刷屏审查。
8. 每个阻断或失败动作都能通过用户安全 debug id 定位。

## 更新后的第一实现范围

1. 统一 runtime 插件骨架。
2. 上述 schema 模型。
3. policy gate 和 audit logger。
4. 一个 LLM provider adapter。
5. 一个 parser adapter，优先 Bilibili 或通用 URL。
6. 一个基于 chatrecorder 的手动总结命令。
7. 一个天气或告警命令。
8. 一个公共游戏/wiki 命令。
9. 一个渲染路径和一个 sender 路径。
10. 测试证明 direct-send 被阻断、冷却、私聊回退和安全错误处理。
