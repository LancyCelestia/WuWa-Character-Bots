# B2② 端口装配组「接线方案材料」（v21r4-B · PORT-PLAN 席）

> ## ⚠️ 本文件是待用户逐项确认的方案材料，不构成实施授权；未确认前不得动码
>
> - 本席**零代码改动、零实装、零真实发送**；本文全部「接线方案」均为**未实施的建议**。
> - `real_session` 真实发送端口=**真实对外发消息**（HANDOFF-V21R4-B-20260918.md §2.5 硬约束 3「对外动作先问」、§四 B2②「高风险——必须先给用户方案并逐项确认」）。
> - 真实发送一日未获逐项确认：矩阵相关行保持 `not_wired`（或回填草案的 `not_wired` 建议值），代码保持 **503 `not_wired`**，工作区 `real_session` 工作区不可创建/预览（503）。
> - 本文若与后端 V2.1 权威文档（backend-v2-implementation-guide.md、control-plane-workspaces.md、backend-protocol-plan.md）冲突，以权威文档为准并视为本方案缺陷，请指出。
> - 席位：PORT-PLAN｜日期：2026-09-18｜未 commit（共享工作树）。

---

## 〇、范围与行号对照（先读）

**行号漂移声明**：交接书/回填草案的 L 编号基于回填前的矩阵版面；MAT 席（B1）回填批注合入矩阵头部后（`docs/design/backend-v2-acceptance-matrix.md:7`），主表各行**整体 +2**。即：**交接书 L 编号 = 现矩阵文件行号 − 2**。旁证（in-repo 自引）：`domains/creation/tts/contracts.py:3` 自称「矩阵 L51 V21-TTS-001」、`domains/creation/image/contracts.py:3` 自称「矩阵 L52 V21-IMAGE-001」，而这两行在现矩阵文件分别位于第 53/54 行。本文双编号并列，杜绝歧义。

**B2② 端口装配组 = 交接书 L46–L54 共 9 行**（backend-protocol-plan.md §三 B2②：「L46 WORKSPACE（真实发送端口）、L47–L54 相关行」）：

| 交接书/草案 L | 现矩阵文件行 | requirement_id | 主题 |
|---|---|---|---|
| L46 | 48 | V21-WORKSPACE-001 | sandbox 隔离与 real_session 确认摘要（**本方案主角**） |
| L47 | 49 | V21-MEDIA-001 | 图片/OCR/GIF 真实处理与证据位置 |
| L48 | 50 | V21-MEDIA-002 | ASR/视频/字幕/抽帧与时间对齐 |
| L49 | 51 | V21-FILE-001 | Word/PPT/Excel/PDF/代码读取 |
| L50 | 52 | V21-FILE-002 | 受控生成保存发送代码资产，默认不执行 |
| L51 | 53 | V21-TTS-001 | TTS 协议/任务/编码/取消/usage/出站 |
| L52 | 54 | V21-IMAGE-001 | 绘图协议/任务/参数/资产/usage/出站 |
| L53 | 55 | V21-SEARCH-001 | 九源检索 |
| L54 | 56 | V21-SEARCH-002 | 网络/文档注入和 SSRF 防护 |

> 注意：若按「现文件第 46–54 行」字面取行，得到的是 ROUTE-001/MEDIA-001…IMAGE-001 混合集——那是漂移误读，本方案不采用（对照表为准）。

---

## 一、逐行现状取证（①）

### 1.1 矩阵行原文

**（a）回填草案 §一 原文**（`docs/design/v21r2-matrix-backfill-draft.md:60-68`，B1 合入的数据源，production_wiring 列全部为 `not_wired`）：

- **L46** `V21-WORKSPACE-001 sandbox/确认摘要`：implementation=partial（sandbox 隔离/确认协议/审计/trace 齐；real_session 真实发送端口合同内不实装，确认消费前诚实 503 not_wired 不烧确认）｜production_wiring=**not_wired（真实发送端口待装配席[s9 §六.1]）**｜offline=passed（s9 §四.1 6 例）｜live=**blocked（端口未实装）**｜conf=verified。
- **L47** `V21-MEDIA-001`：partial（协议面 closed：8 描述符+受控调用面+权限/限额/降级；OCR=VLM 代位诚实 degraded，真 OCR 引擎仍缺）｜**not_wired（协议面未接 control_plane[s10 §六.1]；媒体归档未纳 descriptor[s10 §六.2]）**｜passed（s10 §四 59 passed）｜unknown。
- **L48** `V21-MEDIA-002`：partial（四能力协议化+抽帧上限 24；矩阵「ASR 无」括注已过时应删：transcribe.py/build_asr_provider 已在盘）｜**not_wired（同上）**｜passed｜unknown。
- **L49** `V21-FILE-001`：partial（7 读通道+`.tex` 补文本路；.ppt/.xls 诚实 parser_unavailable 锁死；pypdf 未装=PDF 整类诚实降级）｜**not_wired（协议面）**｜passed（真实文件实调）｜unknown。
- **L50** `V21-FILE-002`：partial（域内侧：build_generated_file 入协议面 admin 门+禁冒充 Office 实测；transport/FileGateway 侧未动）｜**not_wired**｜passed（限定域内侧）｜unknown。
- **L51** `V21-TTS-001`：partial（协议对接点 descriptor+limits+字段级契约草案 reserved；invoke=unavailable 不假成功；实现体缺。wpa1 主张整行维持 unknown，草案折中 partial+live blocked，主会话终裁）｜**not_wired**｜passed（限定协议面）｜**blocked（无 provider 配置；capabilities/tts.py 归属=W-PA2 待裁决）**。
- **L52** `V21-IMAGE-001`：partial（零现载体如实登记+SafetyCheckHook/资产/ConfirmToken 契约草案 reserved+注册面 dormant 三道门）｜**not_wired**｜passed（限定协议面）｜**blocked（无 provider）**。
- **L53** `V21-SEARCH-001`：partial（九源逐源诚实状态面 closed；xhs/YT/X/LinuxDo 实现仍缺）｜**not_wired（search_service provider 生产装配未接[s10 §一]）**｜passed（限定协议/意图/融合面）｜unknown（九源真实可达性未实测）。
- **L54** `V21-SEARCH-002`：partial（协议面 URL 入口强制 check_download_url+guard_user_url 沿用不绕过；DNS rebinding 深防仍无证据保持）｜**not_wired（协议面）**｜passed（限定拒绝分支）｜unknown。

**（b）共享矩阵读时快照**（`docs/design/backend-v2-acceptance-matrix.md`，本席 2026-09-18 读时值，只读未改）：现第 48–56 行仍为回填前形态（implementation=partial 附旧路径坐标、production_wiring=unknown、无〔v21r2 conf〕括注；第 53/54 行 TTS/IMAGE 整行 unknown）。第 7 行 B1 批注宣称 65 行回填完成，与 L46+ 现值不一致——**判定：MAT 席对该区间回填在飞或待续（unknown，归 MAT 域，本席不代写）**。本表合入以后续矩阵实际值为准；草案 (a) 是本方案的状态基线。

### 1.2 workspace/real_session 实现坐标（S9 已落盘件）

**域归属事实**：v21r2 板块重组后 20 域（`domains/`）**无 workspace 域**（`ls plugins/bot_unified_runtime/domains/` 实查 20 目录无 workspace）；workspace/real_session 全量在 **control_plane**，测试在 tests/。任务书所提示「tests/test_v21*workspace*/contracts 与 domains/」两处：contracts/ 下无 workspace 专件（最近缘=`contracts/auto_send.py`→reorg shim→`domains/core/contracts/auto_send.py`，见 §3.1.5）；domains/ 下 workspace 字样仅散见于无关文件。

| 件 | 坐标（file:line） | 内容 |
|---|---|---|
| 服务本体 | `plugins/bot_unified_runtime/control_plane/workspaces.py:96` | `class WorkspaceService`（矩阵行引旧坐标 control_plane/workspaces.py:96 即此） |
| 模式开关 | 同上 `:39` | `mode: Literal["sandbox","real_session"]="sandbox"` |
| 隔离校验 | 同上 `:54-69` | sandbox 禁生产 session/记忆；real_session 必须显式 session_id；`allow_external_tools` 一律拒绝（:60-61）；ID 白名单正则（:65-68） |
| 适配器协议 | 同上 `:72-75` | `RealWorkspaceAdapter`：`context(session_id)`/`generate(scope)`/`deliver(scope)` 三端口 |
| **诚实 503（send）** | 同上 `:325-328` | **`raise ControlServiceError("not_wired", "真实发送端口尚未装配，本次未发送、确认仍有效。", 503)`**——位于 `_begin_send`，token 校验通过后（:323）、**消费确认之前**（:330 置空 token_hash、:332 插回执之前）；条件=`mode=="real_session" and getattr(self.real_adapter,"deliver",None) is None`（:327）。即：**接线=注入带 deliver 的 real_adapter 后此分支自然不再触发，无需删码** |
| 诚实 503（create） | 同上 `:186-187` | real_session 且 `real_adapter is None` → 503 `real_session_unavailable`（"生产会话适配器尚未装配"） |
| 诚实 503（preview） | 同上 `:279-280` | real 且 `real_adapter is None` → 503 `workspace_generator_unavailable` |
| 协议面宣告 | `control_plane/api/v1.py:72-75` | `/api/v1/protocol` → `workspaces.real_session = workspace_service is not None and workspace_service.real_adapter is not None`（**当前恒 False**） |
| API 层 | `control_plane/api/workspaces.py:36-90` | 10 端点（CRUD/messages/preview/send/reset/audit）；send 载荷=`expected_version+confirmation_token+idempotency_key`（:20-22）；服务未装配→503 `workspace_unavailable`（:39-42） |
| 装配点 | `control_plane/factory.py:70-106` | `build_workspace_service`：**只传 `sandbox_generator` 与 `default_persona_profile_id`（:105-106），`real_adapter` 从未注入**——这就是 not_wired 的唯一根因坐标 |
| app 装配 | `control_plane/_app.py:387-389` | `workspace_service = build_workspace_service(config)` |
| 确认机制 | `workspaces.py:272,306,323,330` | 预览产出 32 字节 `token_urlsafe`（:306），库存 sha256 `token_hash`+`expires_at=clock()+300`（:272）；send 时 `compare_digest`（:323），接受即 `token_hash=""` 一次消费（:330） |
| 幂等回执 | 同上 `:119-121,308-334,336-344` | `cp_workspace_sends` 表（workspace_id+idem 主键）；同键不同摘要 409（:317-319）；同键同摘要返回原回执不重发（:316-320）；pending 先落库再调端口（:331-333） |
| 失败面 | 同上 `:365-370` | deliver 异常/超时→receipt=`unknown`→503 `workspace_send_unknown`（"请按回执核查，勿重新发送"） |
| 审计 | 同上 `:115-118,163-167,245-248` | `cp_workspace_audit` 表（workspace_id/owner/request_id/operation/version/occurred_at）+ `GET /workspaces/{id}/audit` |
| 超管门 | 同上 `:140-144` | `_authorize`：仅 `super_admin` 角色（403 otherwise）；API 写依赖=超管 token（v21r2-s9-log.md §一.5） |
| 契约文档 | `docs/design/control-plane-workspaces.md`「真实会话端口（尚未连接生产）」节 | **deliver 必须实现 Policy、Review、Renderer、SendQueue 及 receipt；不可直接调用平台 API；底层以稳定 delivery_id 幂等；受理发送先写 pending 并消费确认再调端口；unknown 不得展示为成功；确认绑定拥有者+当前版本+五分钟期限；真实预览不返回原始 Prompt** |
| 测试 | `tests/test_v21_s9_workspace.py:151-176` | `test_real_session_send_without_deliver_port_is_honest_not_wired`：断言 `code=="not_wired"`（:168），**确认不消费**——同 token 新幂等键重试仍 not_wired 而非 confirmation_required（:170-176）；:45 fake 仅 context+generate 无 deliver；:129 超管门+只读脱敏上下文；:182 `FullRealAdapter` 对照组走通 queued；:196 无适配器 create=503 |
| 测试（API） | `tests/test_control_plane_workspaces_api.py:36,64` | protocol 宣告 `real_session is False`（:36）；`POST /workspaces mode=real_session` → 503（:64） |
| 测试（服务） | `tests/test_control_plane_workspaces.py:24,121,156` | 注入真实 fake adapter 的确认+投递路径用例 |

### 1.3 端口族其余 8 行 canonical 实现坐标（v21r2 重组后；旧路径 shim 保留）

| 行 | 实现载体（canonical file:line） | 缺口（=not_wired 内容） |
|---|---|---|
| L47 MEDIA-001 | `domains/media/ingest/vision_describe.py:620`（build_vision_provider）`:654`（describe_images）；媒体归档 `domains/media/capabilities/media_archive.py:353`（build_media_archive_capability） | 协议面（`runtime/capability_protocols.py` 22 描述符）**未接 control_plane REST**（s10 §六.1）；媒体归档未纳 descriptor（chat 链 handler 形态需 send 口依赖，s10 §六.2）；真 OCR 引擎缺（VLM 代位诚实 degraded） |
| L48 MEDIA-002 | `domains/media/ingest/transcribe.py:277`（build_asr_provider）`:410`（transcribe_audio）；`domains/media/ingest/video_understanding.py:263`（build_video_brief） | 同上 REST 化缺口；抽帧产物 asset 化留 asset 注册表（s10 §六.3） |
| L49 FILE-001 | `domains/files/sources/file_reader.py:93`（read_supported_file；矩阵引旧路径 :102-137） | 协议面 REST 化；环境缺口：**venv 未装 pypdf**→PDF 整类诚实降级（s10 §四.1/§六.6） |
| L50 FILE-002 | `domains/transport/sender/file_gateway.py:165`（FileTicket）`:230`（stage）`:316`（deliver）；files 侧 `domains/files/sources/file_reader.py:222`（build_generated_file） | **transport/FileGateway 侧未动**（s10 §五）：「生成→静态检查→原子保存→Review→FileGateway→Queue」链（guide §11 L254）未串全；FileGateway 现有生产消费方仅 `control_plane/file_access.py` 与 `runtime/capability_protocols.py`（grep 实证），chat 主链 `__init__.py` 无直接引用 |
| L51 TTS-001 | 现载体 `domains/media/capabilities/tts.py`（GPT-SoVITS，`bot_tts_*`；**归属裁决=W-PA2 待裁决**，s10 §一）；契约草案 `domains/creation/tts/contracts.py`（reserved，含 §11 L256 全部硬上限） | **实现体缺**：descriptor 已注册（`runtime/capability_protocols.py`），无 handler→invoke 诚实 `unavailable`（:493-497 "能力未接线（not_wired）"）；等 provider 配置+creation 激活波（s10 §六.5） |
| L52 IMAGE-001 | 零现载体；契约草案 `domains/creation/image/contracts.py`（reserved；`CONFIRM_TTL_SECONDS=120` 预览→确认发送） | 同上：无 provider、无 handler→unavailable |
| L53 SEARCH-001 | `domains/core/search/search_service.py:388`（SOURCE_REGISTRY 九源）`:623`（search_provider） | **provider 生产装配未接**（s10 §一）：九源核心离线已落，但生产装配点不构建授权 provider；xhs/YT/X/LinuxDo 源实现缺 |
| L54 SEARCH-002 | `domains/files/sources/downloader.py:363`（check_download_url）+ `sources/parsers/ssrf_guard.py`（guard_user_url/check_fetch_landing）；协议面 URL 入口强制（s10 §二.2） | DNS rebinding 深防**无证据（unknown）**；其余=沿用不绕过，接线动作最小 |

### 1.4 统一出站路径现状（接线的关系锚点）

- `domains/core/contracts/runtime.py:294`（SendRequest）、`:343`（DeliveryReceipt）——V2.1 权威出站 DTO。
- `domains/transport/sender/queue.py:167`（SendQueue Protocol，submit :168）、`:178`（InMemorySendQueue）、`:242`（SQLiteSendRequestQueue：part 级幂等、`PARTIAL_ROW_STATE` :37、`PART_STATE_UNKNOWN` :41、PARTIAL 补偿扫描 :589-590）。
- `domains/transport/sender/gateway.py`（UnifiedDeliveryGateway：deliver→按 adapter 分发 onebot/nonebot sender→record_receipt）；生产装配=`__init__.py:2433-2460`（`_deliver_transport_send_request`）。
- **workspace 契约对出站的要求**（workspaces.py:1-5 模块 docstring + control-plane-workspaces.md）：real_adapter.deliver **必须重新执行 Policy/Review 并入 SendQueue**，禁止直调平台 API——即 real_session 真实发送与 DELIVERY-001「全部副作用进入统一 Queue」（矩阵现 L37）同一归宿。

---

## 二、逐行接线方案（②，全部为**建议**，未实施）

### 2.1 L46 WORKSPACE-001：real_session 真实发送端口（主方案）

**接线本质（一句话）**：给 `WorkspaceService` 注入一个带 `deliver` 的 `RealWorkspaceAdapter`（factory.py:105-106 补第 4 个装配参数），并加配置总门——**服务层协议已 100% 就位，唯一缺口是装配与门**（v21r2-s9-log.md §六.1：「接线后删 503 短路即可，协议已就位」；经核实：not_wired 分支是条件判断（workspaces.py:327），注入后自然失效，**无需删码**，且应**保留**作为拔门后的诚实降级）。

#### 2.1.1 配置门（键名建议，全部缺省关）

| 建议键 | 类型/缺省 | 语义 |
|---|---|---|
| `bot_control_plane_workspace_real_session_enabled` | bool，**False** | 总门。False=工厂不注入 real_adapter，一切维持现状（create/preview/send 三处 503 原样） |
| `bot_control_plane_workspace_real_session_session_allowlist` | tuple[str,...]，**空** | 允许 real_session 工作区绑定的 session_id 白名单。**空=整链关闭（连 context 只读也不许），绝不猜会话**（沿用 campus/群白名单「空=关」先例，AGENTS.md §33/#36） |
| `bot_control_plane_workspace_real_session_daily_send_limit` | int，建议 10 | 每 24h 全局确认发送上限（超限 429，复用 workspace_limit 错误码形态） |
| `bot_control_plane_workspace_real_session_confirm_ttl_seconds` | int，缺省 300 | 维持现状（workspaces.py:272 的 300s）。**TTL 口径分歧见 §2.1.3-C，需用户裁定** |

同步义务：入 `config.py` + config-catalog + `.env.example` 三处（doc_sync_gates 门禁常驻，AGENTS.md #26 收尾波）；db 类键走 runtime_paths 重映射（先例：`bot_control_plane_workspaces_db` config.py:63+1056）。

#### 2.1.2 real_adapter 三端口实现方案（建议落点：`control_plane/real_session_adapter.py` 新件，装配于 factory.py）

| 端口 | 实现（全部复用既有件，零新轮子） | 契约依据 |
|---|---|---|
| `context(session_id)` | 只读查询会话历史（character/history 读路径）→ `workspaces.py:81-93 _safe`（redact_local_secrets+redact_private_debug）脱敏后返回；**只读，绝不写生产记忆/好感** | workspaces.py:286 已对 context 做 `_safe`；control-plane-workspaces.md「提供已脱敏上下文」 |
| `generate(scope)` | 与 `factory.py:77-103 sandbox_generate` 同构（人格 loader+OpenAI 兼容 provider），但 scope.context 来自真实 session 只读快照；只产预览不发送 | workspaces.py:284-287；「真实预览不返回原始 Prompt」（:295-296 已剥 prompt） |
| `deliver(scope)` | 构造 **SendRequest**（domains/core/contracts/runtime.py:294，`delivery_id=scope["delivery_id"]` 幂等）→ policy 门（domains/core/policy/gate.py：黑白名单/安静时间/限流）→ `output/plain_text` 脱敏红线 → Review → **`SQLiteSendRequestQueue.submit`**（queue.py:242）落库 → 由既有 SendQueue 消费链发送 → 把 DeliveryReceipt 映射为 `{"state":"queued"/"rejected"}`（workspaces.py:362 只认这两态） | workspaces.py:1-5 docstring + control-plane-workspaces.md「deliver 必须实现 Policy、Review、Renderer、SendQueue 及 receipt；不可直接调用平台 API」 |

**与 UnifiedDeliveryGateway 的关系**：`__init__.py:2453` 的 gateway 是「事件驱动即时发送」路径（deliver 直发+record_receipt）；workspace 真实发送走「**队列化**」路径（submit 入 SQLiteSendRequestQueue，由队列 worker 消费）——两者最终都落到 DELIVERY-001 统一队列面。建议 deliver 实现只依赖 SendQueue Protocol（queue.py:167），**不直调 gateway/onebot sender**，与契约「不可直接调用平台 API」一致。

#### 2.1.3 确认协议（现状已闭合，方案只补运营裁定点）

**谁确认**：持有控制面**超管 Bearer 写令牌**的主体（API 写依赖=super_admin；工作区内容读取亦仅 super_admin 且限拥有者，workspaces.py:140-144）。**没有第二确认人设计**——令牌持有者即确认责任人。

**确认什么**：`POST /workspaces/{id}/send` 携带 `expected_version + confirmation_token + idempotency_key`（api/workspaces.py:20-22），确认对象=最近一次 preview 的 artifact 摘要（reply 全文+目标 session_id），绑定拥有者+版本+期限。

**防误触（已有五层，全部实测有测试锁定）**：
1. 预览 300s 过期（workspaces.py:272；过期 409 confirmation_required :323-324）；
2. 确认 token 一次消费（:330 置空；二次 409）；
3. **消息变更/reset 即失效**（message/reset 置 `preview=None`，:224/:232；测试 test_v21_s9_workspace.py「消息变更使旧确认失效」）；
4. 幂等键 409 防同键异参重放（:317-319）；
5. **not_wired 前置检查在消费确认之前**（:325-328）——接线后建议**原样保留**：它等价于「拔门即停」的保险丝。

**需用户裁定的确认协议增量点**：
- A. receipt 增强：现回执仅 `{state, receipt_id}`（:331）。建议增发 `session_id`（脱敏形）+SendQueue `request_id` 关联，便于事后对账。要/不要？
- B. SSE 事件：send 受理/完成是否推控制面事件流（RuntimeEventService，matrix L26）？建议二期，一期仅审计表。
- C. **确认 TTL 口径分歧**：guide §6 L149 通用规则=「确认 token 绑定 actor/目标/版本/摘要，120s、一次消费」；workspace 合同=五分钟（300s），实现=300s（workspaces.py:272）；image 契约=120s（image/contracts.py CONFIRM_TTL_SECONDS）。三处并存，需裁定 workspace 维持 300s 还是统一 120s。
- D. 安静时间：超管手动确认发送是否豁免安静时间（建议：豁免但审计行显式记录；待裁定）。

#### 2.1.4 审计与回执面（现状+建议）

- 现状：`cp_workspace_audit`（workspaces.py:115-118）逐操作记录（created/preview_started/preview_ready/send_accepted/send_queued/…，operation 名见 :198,260,273,333,343）；envelope meta 带 trace_id（v21r2-s9-log.md §一.6）；`cp_workspace_sends` 幂等回执持久化。
- 建议增量（可选，待确认）：①send 成功回执关联 SendQueue DeliveryReceipt 全文（state/request_id/parts）；②审计表按 db-owners.md 惯例登记保留期（cp_workspaces 三表已登记，v21r2-s9-log.md §五）。

#### 2.1.5 频控与白名单

- session 白名单必填非空（§2.1.1 键 2）+ real_session 建工作区时校验 session_id ∈ 白名单（建议在 create 门（workspaces.py:186 附近）加一道，非白名单 403/422，杜绝「先建后审」）。
- 每日全局上限（§2.1.1 键 3）。
- deliver 路径复用 policy gate 限流器（InMemory+SQLite 同语义），不新建频控。
- 目标面约束：real_session 只能向**已存在的真实会话**回发（session_id 格式 `^[A-Za-z0-9_.:@-]+$` workspaces.py:40；不允许新收件人发现——与 auto_send 契约的 RecipientResolution/allowlist_state（domains/core/contracts/auto_send.py:24-39）相比是更强的白名单制，本方案不引入自由收件人）。

#### 2.1.6 失败面与回滚

- 发送失败：receipt=unknown + 503 workspace_send_unknown + 「勿重新发送」提示（workspaces.py:365-370）；底层由 SendQueue 的 PARTIAL 断点续发/UNKNOWN 对账兜底（queue.py:37-45,589-590）。
- 回滚三级：①配置门关（`..._enabled=False`）→ 下次装配起恢复 503 not_wired，**零代码回滚**；②白名单清空 → 整链关；③代码回滚=工厂删去 real_adapter 实参（factory.py:105-106 单点），not_wired 分支自动复活。矩阵相应行同步降回 not_wired（红线：重启+实跑证据前不得升 wired）。

#### 2.1.7 实施工作量与波次建议（若获确认）

1. config 四键三同步（config.py+catalog+.env.example）；
2. `control_plane/real_session_adapter.py`（context/generate/deliver 三端口，全部懒 import 复用既有件）；
3. factory.py 装配（总门+白名单+上限校验，门关=不注入）；
4. create 门白名单校验+每日上限（workspaces.py 两处小改）；
5. 测试：真实 adapter 的 queued/rejected/unknown 三态+白名单拒绝+上限+门关回归（现 not_wired 测试 :151-176 必须保持全绿——门关路径即其现状）；
6. 文档：control-plane-workspaces.md「真实会话端口」节由「尚未连接生产」改记实装边界+db-owners 复核。
7. **生效条件=用户提权重启**（改码不重启不生效，AGENTS.md 铁律）；重启前矩阵不得升 wired。

### 2.2 L47–L54 其余 8 行接线方案（要点式）

| 行 | 接线动作（若实施） | 对外发送? | 阻塞/前置 |
|---|---|---|---|
| L47 MEDIA-001 | 协议面 REST 化：`runtime/capability_protocols.py` 8 media 描述符暴露为控制面只读/受控调用端点（s10 §六.1 移交）；媒体归档纳 descriptor 需先解决 send 口依赖注入（s10 §六.2：直接包装会造第二装配路径）；真 OCR 引擎=等选型（VLM 代位是诚实现状，非缺陷） | 否（受控下载走 SSRF 护栏，downloader.py:363） | 低-中；不涉对外消息，无需「对外动作」确认；属控制面增量批次 |
| L48 MEDIA-002 | 同 REST 化；抽帧产物 asset 化留 asset 注册表面（s10 §六.3） | 否 | 同上 |
| L49 FILE-001 | 同 REST 化；**venv 安装 pypdf** 即解除 PDF 诚实降级（环境动作，装前 .ppt/.xls 锁死与 pypdf 缺失语义均须维持） | 否 | 环境：装 pypdf（用户/环境动作） |
| L50 FILE-002 | 串全「生成→静态检查→原子保存→Review→FileGateway→Queue」链（guide §11 L254 原文）：files 侧 build_generated_file（file_reader.py:222）已入协议面 admin 门，缺 transport 侧 FileGateway.deliver（file_gateway.py:316）到 SendQueue 的提交段与生产装配 | **是**（文件真实发进会话） | **同受「对外动作先问」**——建议与 L46 同批逐项确认或单独批次 |
| L51 TTS-001 | 实现 CreationJobState 状态机 handler（contracts.py 已钉全部上限/计费字段）+出站；descriptor/limits 已预置（s10 §六.5） | **是**（音频发进会话） | **blocked：无 provider 配置**；capabilities/tts.py 归属 W-PA2 待用户裁决（media 留守 vs creation 激活波） |
| L52 IMAGE-001 | 同上；零现载体，按契约草案从零实现 handler（预览→确认发送 120s token） | **是**（图片发进会话） | **blocked：无 provider**；建议与 TTS 同一「creation 激活波」立项 |
| L53 SEARCH-001 | 生产装配点构建授权 provider（build_web_search_provider 链+九源注册）注入 SearchService；xhs/YT/X/LinuxDo 四源实现缺=诚实 not_configured 不冒充（s10 §三） | 否（出站读请求，非消息；受 SEARCH-002 护栏） | 中；九源真实可达性 live 实测需白名单真机（s10 §六.4） |
| L54 SEARCH-002 | 接线动作最小=保持协议面强制（已在）；DNS rebinding 深防无证据（unknown）——建议独立小立项，不在本波 | 否 | 低 |

---

## 三、风险分级与前置条件（③）

### 3.1 风险分级

| 级 | 行 | 风险内容 |
|---|---|---|
| **高** | L46（real_session deliver）、L50（资产发送段）、L51/L52（TTS/绘图出站） | **真实对外发消息/媒体**；误确认、错会话、刷屏、内容越界都直达真实用户；L51/L52 另有 provider 凭据与计费面 |
| 中 | L47/L48（REST 化）、L49（REST 化+pypdf）、L53（provider 装配） | 控制面增量装配与启动顺序；无直接对外发送；REST 化扩大控制面攻击面（loopback+Bearer 既有门内） |
| 低 | L54 | 护栏沿用+观测；深防缺证 = unknown 如实登记 |

### 3.2 实施前置条件清单（用户逐项勾选；未勾满不得动码）

**总闸**
- [ ] 1. 本波次是否实装 real_session 真实发送端口？（是/否——否则本文 §2.1 全部作废，矩阵与代码维持 not_wired/503 现状）
- [ ] 2. 确认总门键名 `bot_control_plane_workspace_real_session_enabled`，缺省 **False**（关）。
- [ ] 3. 提供 session 白名单内容（`..._session_allowlist`）：**留空=整链关闭**；提供即视为授权向这些会话发送。
- [ ] 4. 确认每日全局发送上限数值（建议 10）。
- [ ] 5. 确认确认-token 有效期：workspace 维持 **300s**（合同口径）还是统一 guide 的 120s（§2.1.3-C 三处口径分歧裁定）。
- [ ] 6. 确认确认主体=控制面超管 Bearer 写令牌持有者，无第二确认人。
- [ ] 7. 回执增强（session 脱敏回显+SendQueue request_id 关联）：要/不要。
- [ ] 8. send 受理/完成是否推控制面 SSE 事件：建议一期不做。
- [ ] 9. 安静时间豁免与否（建议豁免+审计显式记录）。
- [ ] 10. L50（FILE-002 发送段）是否纳入同批确认？（建议：单独批次，待 L46 首证稳定后再议）
- [ ] 11. L51/L52（TTS/绘图）：先裁定 provider 选型+`capabilities/tts.py` 归属（W-PA2），未裁前**不做**（live 维持 blocked）。
- [ ] 12. L47/L48/L49/L53（中风险组）是否随控制面增量批次另排（不经本清单）？
- [ ] 13. 知悉回滚方式：配置门关/白名单清空/工厂单点摘除，三级均可回到 503 not_wired；SendQueue 自带 PARTIAL/UNKNOWN 对账兜底。
- [ ] 14. 知悉生效条件：接线合入后需**用户手动提权重启** bot；重启+实跑证据前，矩阵相关行**不得**升 wired（诚实红线 4）。
- [ ] 15. （边界知悉）L41 记忆库「独立新库 vs 同源同库」未裁决，不在本方案（§四）。

---

## 四、明确边界（④）

1. **L41（V21-MEM-001）不在本方案**：阻塞于用户裁决「独立新库 vs 同源同库」（HANDOFF §3.4/§七.2）；本方案不覆盖、不建议、不预设。
2. **真实发送未获确认前的静止态**：矩阵 L46（及端口族相关行）保持 `not_wired`（以草案回填值为准）；代码保持 workspaces.py:327-328 的 503 `not_wired`（create/preview 两处 503 同）；`/api/v1/protocol` 的 `real_session` 宣告保持 False（api/v1.py:75）。任何席位不得在未确认下改此三处。
3. **本方案不等于接线**：即使全部勾选，实施仍需走「改码→测试全绿→用户重启→实跑取证」流程；离线测试绿不升 live passed（诚实红线 1）。
4. B2①（服务装配组 L39-L43）/B2③（直连点收编 L56/L57/L58/L65）归其他席位/批次，本方案不越界。
5. 矩阵四列的合入/改写归 MAT 席独占（本席只引用只读）。

---

## 附 A：证据与置信度

- 本文件现状断言全部来自本席 2026-09-18 对工作树的实读（file:line 已随文标注），置信度 **high**（源码/文档直读，未实跑测试；本席零实跑义务，s9/s10 席日志中的测试结论均标注为该席实跑转引，非本席复跑）。
- 实跑证据转引（均注明出处）：tests/test_v21_s9_workspace.py 6 例、test_control_plane_workspaces_api.py、test_v21_s10_protocols.py 59 passed 1 skipped → v21r2-s9-log.md §四.1、v21r2-s10-log.md §四.1。
- unknown 清单：①矩阵 L46+ 行回填现值（MAT 在飞）；②DNS rebinding 深防证据；③九源真实可达性；④SendQueue worker 消费链与 workspace deliver 的对接细节（本席未读 worker 全文，实施席需先勘 `domains/transport/sender/worker.py`）；⑤pypdf 安装后 PDF 行为升级面。
- 数字口径注：交接书 §1.3 记 not_wired 18 行（含 L65），草案 §尾注（draft:143）记 17 行——差 1 系计数口径，交接书已声明按 18 推进，与本方案无冲突（本方案只涉 L46–L54）。

## 附 B：本方案引用的权威链

HANDOFF-V21R4-B-20260918.md（§2.5/§2.7/§四 B2②）← backend-protocol-plan.md §三 B2② ← backend-v2-acceptance-matrix.md（L46–L54 行）← v21r2-matrix-backfill-draft.md §一（:60-68）← docs/design/control-plane-workspaces.md（真实会话端口契约）← backend-v2-implementation-guide.md（§6 L149、§11 L252-L258）← v21r2-s9-log.md §六.1 / v21r2-s10-log.md §六（两处移交原文）。
